#!/usr/bin/env python3
"""sh1_ipc16_test.py — the Type-16 "Restore default" IPC round-trip gate.

The REAL panel sequence (CustomiseWallpaperViewModel.cs): the user
modifies properties, then clicks "Restore default" — the app re-copies
the PRISTINE LivelyProperties.json over the property copy and sends
{"Type":16}. A correct player re-reads the file and reverts everything.

This gate builds the seam as the LINUX LP_POSIX_STUB (zig cc
-DLIVELY_PLAYER, non-Win32: types + no-op window + pthread thread — the
stub never ships; the shipped exe is the Windows build byte-checked
separately), then drives the REAL binary through the exact stdin pipe
sequence:

  boot (pristine props) -> {"Type":14 scene SU0203} -> {"Type":18 fog off}
  -> [pristine re-copy] -> {"Type":16} -> suspend/resume -> close (EOF)

PASS = handshake (Type:0 Hwnd) + wploaded (Type:2) + "scene switched:
<ROOM>" with the EXACT rooms (SU0203 then THRF9FE — a wrong-index
regression cannot pass) + the reload ack echoing the staged slots +
zero Category:1 errors + clean exit 0.

Run from the repo root on any Linux x64 with zig in $PATH (or zig via
the ZIG env var). Exit non-zero on any violation.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src", "Lively", "Lively.Player.Sh1", "fog_poc.c")
WPDIR = os.path.join(REPO, "bundle", "wallpapers", "sh1-wallpaper")
ZIG = os.environ.get("ZIG", "zig")

if not os.path.exists(SRC):
    print("FATAL: engine source missing:", SRC); sys.exit(1)
if not os.path.isdir(WPDIR):
    print("FATAL: wallpaper dir missing:", WPDIR); sys.exit(1)

work = tempfile.mkdtemp(prefix="sh1_ipc16_")
exe = os.path.join(work, "lp_stub_player")
try:
    subprocess.run(
        [ZIG, "cc", "-target", "x86_64-linux-gnu", "-O2", "-std=c99",
         "-DLIVELY_PLAYER", "-o", exe, SRC, "-lm", "-lpthread"],
        check=True, cwd=REPO)
except Exception as e:
    print("FATAL: zig cc build failed:", e); sys.exit(1)

props_src = os.path.join(WPDIR, "LivelyProperties.json")
props = os.path.join(work, "LivelyProperties.json")
shutil.copyfile(props_src, props)

p = subprocess.Popen(
    [exe, "--wallpaper-path", WPDIR,
     "--wallpaper-property", props, "--wallpaper-type", "sh1"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL, text=True, cwd=work)

seen = {"hwnd": False, "loaded": False, "scene_switch": 0,
        "acks": [], "rooms": [], "errors": 0}


def reader():
    for line in p.stdout:
        line = line.strip()
        if not line.startswith("{"):
            continue
        m = re.search(r'"Type":(\d+)', line)
        if not m:
            continue
        t = int(m.group(1))
        if t == 0 and re.search(r'"Hwnd":\d+', line):
            seen["hwnd"] = True
        elif t == 2 and '"Success":true' in line:
            seen["loaded"] = True
        elif t == 1 and '"Category":1' in line:
            seen["errors"] += 1          # error check FIRST (R4 hardening)
        elif t == 1 and "scene switched" in line:
            seen["scene_switch"] += 1
            m2 = re.search(r"scene switched: ([A-Za-z0-9_.-]+)", line)
            if m2:
                seen["rooms"].append(m2.group(1))
        elif t == 1 and "defaults reloaded" in line:
            seen["acks"].append(line.strip())


t = threading.Thread(target=reader, daemon=True)
t.start()

deadline = time.time() + 120
while not seen["loaded"] and time.time() < deadline and p.poll() is None:
    time.sleep(0.2)

if not seen["loaded"]:
    print("FATAL: msg_wploaded never arrived")
    p.kill(); shutil.rmtree(work, ignore_errors=True); sys.exit(1)

def send(s):
    try:
        p.stdin.write(s + "\n"); p.stdin.flush()
    except (BrokenPipeError, OSError):
        print("FATAL: player exited before receiving:", s)
        p.kill(); sys.exit(1)

send('{"Type":14,"Name":"scene","Value":33}')       # user: SU0203
time.sleep(4)
send('{"Type":18,"Name":"fog","Value":false}')      # user: fog off
time.sleep(1)
shutil.copyfile(props_src, props)                   # the panel's pristine re-copy
send('{"Type":16}')                                 # "Restore default"
time.sleep(4)

# R4-M4b discriminator: a hardcoded/lying ack cannot echo values it never
# read. Rewrite the copy to a DIFFERENT state and send a second Type 16 —
# the revert must now echo THOSE values (scene=SU0203 fog=0 fps=15) and
# switch the room a THIRD time. Kills any constant-string ack mutant.
with open(props, "r", encoding="utf-8") as f:
    txt = f.read()
txt2 = re.sub(r'("scene":\s*\{[^}]*"value":\s*)42', r'\g<1>33', txt, count=1)
txt2 = re.sub(r'("fog":\s*\{[^}]*"value":\s*)true', r'\g<1>false', txt2, count=1)
txt2 = re.sub(r'("fps":\s*\{[^}]*"value":\s*)30', r'\g<1>15', txt2, count=1)
if txt2 == txt:
    print("FATAL: discriminator rewrite failed (bundle format drift?)")
    p.kill(); shutil.rmtree(work, ignore_errors=True); sys.exit(1)
with open(props, "w", encoding="utf-8") as f:
    f.write(txt2)
send('{"Type":16}')                                 # second revert
time.sleep(4)

send('{"Type":7}')                                  # suspend
time.sleep(1)
send('{"Type":8}')                                  # resume
time.sleep(1)
send('{"Type":5}')                                  # close
try:
    p.stdin.close()   # EOF like the real parent (the C# app closes on exit)
except Exception:
    pass

try:
    rc = p.wait(timeout=60)
except subprocess.TimeoutExpired:
    p.kill(); rc = p.wait()
t.join(timeout=5)   # drain the reader before the verdict

print("hwnd:", seen["hwnd"], "| loaded:", seen["loaded"],
      "| scene_switch:", seen["scene_switch"],
      "| rooms:", seen["rooms"],
      "| acks:", seen["acks"],
      "| errors:", seen["errors"],
      "| exit:", rc)

# Round 1: the exact rooms (SU0203 user switch, then the THRF9FE revert of
# the pristine file) with the ack echoing the pristine staged slots.
# Round 2 (the M4b discriminator): a THIRD switch back to SU0203 and the
# second ack echoing the REWRITTEN values (fog=0 fps=15) — a hardcoded or
# self-reporting ack cannot pass; only a revert that actually re-reads the
# file can. Zero Category:1 errors, clean exit.
ok = (seen["hwnd"] and seen["loaded"]
      and seen["scene_switch"] == 3
      and seen["rooms"] == ["SU0203", "THRF9FE", "SU0203"]
      and len(seen["acks"]) == 2
      and "scene=THRF9FE" in seen["acks"][0]
      and "fog=1" in seen["acks"][0]
      and "fps=30" in seen["acks"][0]
      and "env=camdat" in seen["acks"][0]
      and "scene=SU0203" in seen["acks"][1]
      and "fog=0" in seen["acks"][1]
      and "fps=15" in seen["acks"][1]
      and seen["errors"] == 0
      and rc == 0)
print("IPC16 TEST:", "PASS" if ok else "FAIL")
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
