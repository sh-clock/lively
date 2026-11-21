#!/usr/bin/env python3
"""sh1_type16_ipc_test.py — the REAL-USER "Restore default" (Type 16) IPC
test. Runs on CI (windows-latest) against the real Lively.Player.Sh1.exe.

The exact panel contract (CustomiseWallpaperViewModel.cs:202):
    File.Copy(Model.LivelyPropertyPath, currentFilePath, true);
    WallpaperSendMsg(new LivelyButton()
        { Name = "lively_default_settings_reload", IsDefault = true });
The C# re-copies the PRISTINE LivelyProperties.json over the live property
copy BEFORE sending the Type-16 message, then expects the wallpaper to
revert live. S19 audit D1: the native player used to ignore the message
(state divergence until relaunch); lp_reload_props_live now re-reads the
copy and stages every value into the same live slots Type 12/14/18 use.

Test sequence (all messages byte-exact with the C# senders):
  1. Launch with the app's own argv (S18: no --wallpaper-scene — the C#
     passes none) + a props COPY (CreateLivelyPropertyFolder).
  2. DIVERGE exactly like a user editing the panel: write a user-modified
     props copy (scene 33 SU0203, fog off, fps 15, envpair item 4) AND send
     the live messages the panel sends while editing:
       {"Type":14,"Name":"scene","Value":33}
       {"Type":12,"Name":"fps","Value":15.0}
       {"Type":18,"Name":"fog","Value":false}
     -> assert "scene switched" #1 (the live scene reload).
  3. RESTORE exactly like the panel button: re-copy the pristine bundle
     LivelyProperties.json over the copy (File.Copy semantics) + send
       {"Type":16,"Name":"lively_default_settings_reload","IsDefault":true}
     -> assert the console ack "defaults reloaded from ..."
     -> assert "scene switched" #2 (the revert reload: pristine scene 42
        THRF9FE != the diverged live SU0203).
  4. Close (Type 5) -> the process must exit cleanly.

Exit non-zero on any contract violation.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(REPO, "publish", "plugins", "sh1", "Lively.Player.Sh1.exe")
WPDIR = os.path.join(REPO, "bundle", "wallpapers", "sh1-wallpaper")

if not os.path.exists(EXE):
    print("FATAL: player exe missing:", EXE)
    sys.exit(1)
if not os.path.isdir(WPDIR):
    print("FATAL: wallpaper folder missing:", WPDIR)
    sys.exit(1)

_props_src = os.path.join(WPDIR, "LivelyProperties.json")
if not os.path.exists(_props_src):
    print("FATAL: bundle LivelyProperties.json missing:", _props_src)
    sys.exit(1)
_propdir = tempfile.mkdtemp(prefix="sh1_t16_props_")
_props_copy = os.path.join(_propdir, "LivelyProperties.json")

# the app's CreateLivelyPropertyFolder writes a COPY of the wallpaper's
# LivelyProperties.json and passes its path via --wallpaper-property.
shutil.copyfile(_props_src, _props_copy)


def write_diverged_copy():
    """the user-modified property copy: scene 33 (SU0203), fog off, fps 15,
    envpair item 4 — the exact shape the panel saves while editing."""
    with open(_props_src, encoding="utf-8") as f:
        doc = json.load(f)
    doc["scene"]["value"] = 33
    doc["fog"]["value"] = False
    doc["fps"]["value"] = 15
    doc["envpair"]["value"] = 4
    with open(_props_copy, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def restore_pristine_copy():
    """CustomiseWallpaperViewModel.RestureDefault step 1: File.Copy(
    Model.LivelyPropertyPath, currentFilePath, true)."""
    shutil.copyfile(_props_src, _props_copy)


args = [
    EXE,
    "--wallpaper-path", WPDIR,
    "--wallpaper-property", _props_copy,
    "--wallpaper-type", "sh1",
]

p = subprocess.Popen(
    args,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    cwd=os.path.dirname(EXE),
)

seen = {"hwnd": None, "loaded": False, "scene_switches": 0,
        "defaults_ack": False, "console": []}


def reader():
    for line in p.stdout:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        t = obj.get("Type")
        if t == 0 and obj.get("Hwnd", 0) > 0:
            seen["hwnd"] = obj["Hwnd"]
        elif t == 2 and obj.get("Success") is True:
            seen["loaded"] = True
        elif t == 1:
            msg = str(obj.get("Message", ""))
            seen["console"].append(msg)
            if "scene switched" in msg:
                seen["scene_switches"] += 1
            if "defaults reloaded" in msg:
                seen["defaults_ack"] = True


stderr_lines = []


def err_reader():
    for line in p.stderr:
        stderr_lines.append(line.rstrip())


t = threading.Thread(target=reader, daemon=True)
te = threading.Thread(target=err_reader, daemon=True)
t.start(); te.start()


def wait_for(pred, timeout, what):
    deadline = time.time() + timeout
    while time.time() < deadline and p.poll() is None:
        if pred():
            return True
        time.sleep(0.2)
    return pred()


# ---- 1. the boot handshake ----------------------------------------------
if not wait_for(lambda: seen["loaded"], 180):
    print("FATAL: msg_wploaded never arrived")
    print("--- player stderr (engine boot log) ---")
    for l in stderr_lines[:40]:
        print(l)
    p.kill()
    sys.exit(1)

# ---- 2. DIVERGE: the user edits (panel writes the copy + live msgs) ----
write_diverged_copy()
p.stdin.write('{"Type":12,"Name":"fps","Value":15.0}\n')
p.stdin.flush()
time.sleep(1)
p.stdin.write('{"Type":18,"Name":"fog","Value":false}\n')
p.stdin.flush()
time.sleep(1)
p.stdin.write('{"Type":14,"Name":"scene","Value":33}\n')
p.stdin.flush()

# the live scene switch (SU0203 loaded from the bundle)
if not wait_for(lambda: seen["scene_switches"] >= 1, 60):
    print("FATAL: the diverge scene switch never happened")
    p.kill()
    sys.exit(1)

# ---- 3. RESTORE DEFAULT (the panel button, byte-exact) -------------------
time.sleep(2)   # let the diverged state settle (frames + props applied)
restore_pristine_copy()
p.stdin.write('{"Type":16,"Name":"lively_default_settings_reload","IsDefault":true}\n')
p.stdin.flush()

ok_ack = wait_for(lambda: seen["defaults_ack"], 30)
ok_revert = wait_for(lambda: seen["scene_switches"] >= 2, 60)

time.sleep(3)   # let the revert settle before closing

# ---- 4. close cleanly -----------------------------------------------------
p.stdin.write('{"Type":5}\n')
p.stdin.flush()

try:
    rc = p.wait(timeout=30)
except subprocess.TimeoutExpired:
    p.kill()
    rc = p.wait()

try:
    os.remove(_props_copy)
    os.rmdir(_propdir)
except OSError:
    pass

print("handshake:", seen["hwnd"], "| loaded:", seen["loaded"],
      "| scene_switches:", seen["scene_switches"],
      "| defaults_ack:", seen["defaults_ack"], "| exit:", rc)
print("console:", seen["console"][:12])

ok = (seen["hwnd"] is not None and seen["loaded"]
      and seen["scene_switches"] >= 2 and seen["defaults_ack"]
      and rc in (0, None) and ok_ack and ok_revert)
print("TYPE16 IPC TEST:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
