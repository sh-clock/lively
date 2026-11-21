#!/usr/bin/env python3
"""sh1_ipc_test.py — the REAL-USER launch test for Lively.Player.Sh1.exe.

Spawns the player exactly the way the Lively app does (piped stdin/stdout,
working directory = the plugin dir, the --wallpaper-* arguments), then
asserts the IPC contract the C# side depends on:
  1. {"Type":0,"Hwnd":N}  — msg_hwnd handshake (N > 0)
  2. {"Type":2,"Success":true} — msg_wploaded after the first frame
  3. LIVE scene switch: {"Type":14,"Name":"scene","Value":33} (SU0203)
     -> the player must report the switch (msg_console "scene switched")
  4. suspend (7) / resume (8) — must not crash
  5. close (5) — the process must exit cleanly

S18: the launch now uses the EXACT argv the C# Sh1Wallpaper builds — NO
--wallpaper-scene (LivelyInfo.json Arguments is empty and the C# passes
none) and WITH --wallpaper-property pointing at a copy of the bundled
LivelyProperties.json (the CreateLivelyPropertyFolder copy the app passes).
The v1.0.2 player exit(1)-before-msg_hwnd bug hid behind this difference:
the old test passed --wallpaper-scene explicitly, so the no-scene default
boot path (which must probe <wallpaperDir>\\sh1\\ for the GLB) was never
exercised on CI. The real app always launches that path.

Run from the repo root (CI does it after the layout audit).
Exit non-zero on any contract violation; prints a PASS/FAIL verdict.
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

# The app's CreateLivelyPropertyFolder writes a COPY of the wallpaper's
# LivelyProperties.json and passes its path via --wallpaper-property.
# Reproduce that copy exactly (temp dir, real file content).
_props_src = os.path.join(WPDIR, "LivelyProperties.json")
if not os.path.exists(_props_src):
    print("FATAL: bundle LivelyProperties.json missing:", _props_src)
    sys.exit(1)
_propdir = tempfile.mkdtemp(prefix="sh1_props_")
_props_copy = os.path.join(_propdir, "LivelyProperties.json")
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

seen = {"hwnd": None, "loaded": False, "scene_switch": False, "console": []}


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
            seen["console"].append(str(obj.get("Message", "")))
            if "scene switched" in str(obj.get("Message", "")):
                seen["scene_switch"] = True


stderr_lines = []
def err_reader():
    for line in p.stderr:
        stderr_lines.append(line.rstrip())

t = threading.Thread(target=reader, daemon=True)
te = threading.Thread(target=err_reader, daemon=True)
t.start(); te.start()

deadline = time.time() + 180  # the engine boots + renders the first frame
while not seen["loaded"] and time.time() < deadline and p.poll() is None:
    time.sleep(0.2)

if not seen["loaded"]:
    print("FATAL: msg_wploaded never arrived")
    print("--- player stderr (engine boot log) ---")
    for l in stderr_lines[:40]:
        print(l)
    p.kill()
    try:
        os.remove(_props_copy)
        os.rmdir(_propdir)
    except OSError:
        pass
    sys.exit(1)

# LIVE property changes — exactly the messages the Customise panel sends
p.stdin.write('{"Type":14,"Name":"scene","Value":33}\n')  # SU0203
p.stdin.flush()
time.sleep(6)
p.stdin.write('{"Type":7}\n')  # suspend
p.stdin.flush()
time.sleep(2)
p.stdin.write('{"Type":8}\n')  # resume
p.stdin.flush()
time.sleep(2)
p.stdin.write('{"Type":5}\n')  # close
p.stdin.flush()

try:
    rc = p.wait(timeout=30)
except subprocess.TimeoutExpired:
    p.kill()
    rc = p.wait()

# the props copy is test scratch — remove it (best-effort)
try:
    os.remove(_props_copy)
    os.rmdir(_propdir)
except OSError:
    pass

print("handshake:", seen["hwnd"], "| loaded:", seen["loaded"],
      "| scene_switch:", seen["scene_switch"], "| exit:", rc)

ok = (seen["hwnd"] is not None and seen["loaded"]
      and seen["scene_switch"] and rc in (0, None))
print("PLAYER IPC TEST:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
