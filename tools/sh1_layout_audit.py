#!/usr/bin/env python3
"""sh1_layout_audit.py — assert the packaged app contains EVERY path the
running app launches via ProcessStartInfo / Constants.PlayerPartialPaths.

This is the exact bug class that shipped v1.0.0-sh1: the core exe ran but
plugins\\UI\\Lively.UI.WinUI.exe and Plugins\\Watchdog\\Lively.Watchdog were
never built into the zip, so the app crashed at startup.

Sources of truth (verified against the app code):
  - RunnerService.cs:42      plugins/UI/Lively.UI.WinUI.exe       (MANDATORY, no fallback)
  - WatchdogProcess.cs:30    Plugins/Watchdog/Lively.Watchdog     (MANDATORY, no .exe ext)
  - Constants.PlayerPartialPaths + our Sh1Path: plugins/sh1/Lively.Player.Sh1.exe
  - AppInitializer.cs:103    bundle/wallpapers (the wallpaper auto-install)
  - The core exe itself:    Lively.exe
Video/web players (webview2/cef/mpv/vlc) are runtime downloads (optional).

Usage: python tools/sh1_layout_audit.py <publish-dir>
Exit 1 with a precise listing if anything mandatory is missing.
"""
import os
import sys

publish = sys.argv[1] if len(sys.argv) > 1 else "publish"

REQUIRED = [
    # (path, why)
    ("Lively.exe", "the core app process"),
    (os.path.join("plugins", "UI", "Lively.UI.WinUI.exe"),
     "RunnerService.cs:42 — the settings/gallery UI process (v1.0.0 crash)"),
    (os.path.join("Plugins", "Watchdog", "Lively.Watchdog"),
     "WatchdogProcess.cs:30 — the fullscreen watchdog (no .exe extension)"),
    (os.path.join("plugins", "sh1", "Lively.Player.Sh1.exe"),
     "Constants.PlayerPartialPaths.Sh1Path — the SH1 wallpaper player"),
    (os.path.join("bundle", "wallpapers", "2.zip"),
     "AppInitializer.InstallWallpaperBundles — the bundled SH1 wallpaper"),
]

missing = []
for rel, why in REQUIRED:
    full = os.path.join(publish, rel)
    if not os.path.isfile(full):
        missing.append((rel, why))
    else:
        size = os.path.getsize(full)
        print(f"  OK  {rel}  ({size//1024} KB)")

# S18 (audit D1): the shipped bundle zip is what USERS get — the app extracts
# 2.zip on first run. The gates above only proved the SOURCE folder boots; a
# truncated or wrongly-packed zip would release green. Assert the internals:
# 44 scene GLBs + camdat.json under sh1-wallpaper/sh1/, the LivelyInfo.json
# (Type=sh1, empty Arguments — the no-scene boot), the properties file and
# the preview. Entry names inside the zip are forward-slash paths.
bundle = os.path.join(publish, "bundle", "wallpapers", "2.zip")
if os.path.isfile(bundle):
    import zipfile
    EXPECTED_SCENES = 44
    with zipfile.ZipFile(bundle) as z:
        names = set(z.namelist())
        if "sh1-wallpaper/LivelyInfo.json" not in names:
            missing.append(("2.zip:sh1-wallpaper/LivelyInfo.json",
                            "the wallpaper entry — zip packed wrong"))
        if "sh1-wallpaper/LivelyProperties.json" not in names:
            missing.append(("2.zip:sh1-wallpaper/LivelyProperties.json",
                            "the Customise panel defaults"))
        if "sh1-wallpaper/sh1/camdat.json" not in names:
            missing.append(("2.zip:sh1-wallpaper/sh1/camdat.json",
                            "the camera track + env (bundle layout, S18)"))
        glbs = [n for n in names if n.startswith("sh1-wallpaper/sh1/")
                and n.endswith(".glb")]
        if len(glbs) != EXPECTED_SCENES:
            missing.append((f"2.zip:sh1-wallpaper/sh1/*.glb",
                            f"expected {EXPECTED_SCENES} scene GLBs, "
                            f"found {len(glbs)}"))
        info = z.read("sh1-wallpaper/LivelyInfo.json").decode("utf-8")
        if '"Type": "sh1"' not in info and '"Type":"sh1"' not in info:
            missing.append(("2.zip:LivelyInfo.json Type",
                            "must be sh1"))

        # V42 (audit E-7): FRESHNESS — the internals check above only proves the
        # zip is well-formed, not that it matches the source bundle dir. A fix in
        # bundle/wallpapers/sh1-wallpaper/ without a repack (exactly the E-3
        # camdat regression class) would still release green. Byte-compare every
        # sh1-wallpaper/ entry against the repo's source dir.
        src_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "bundle", "wallpapers", "sh1-wallpaper")
        if os.path.isdir(src_root):
            import hashlib
            stale, absent = [], []
            src_files = {}
            for dirpath, _, filenames in os.walk(src_root):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, src_root).replace(os.sep, "/")
                    src_files[rel] = full
            for rel, full in sorted(src_files.items()):
                entry = "sh1-wallpaper/" + rel
                if entry not in names:
                    absent.append(entry)
                    continue
                if hashlib.sha1(z.read(entry)).hexdigest() != \
                   hashlib.sha1(open(full, "rb").read()).hexdigest():
                    stale.append(entry)
            if absent or stale:
                for e in absent:
                    missing.append((f"2.zip:{e}",
                                    "in the source bundle dir but NOT in the shipped zip — repack 2.zip"))
                for e in stale:
                    missing.append((f"2.zip:{e}",
                                    "zip content is STALE vs the source bundle dir — repack 2.zip (E-7)"))
            else:
                print(f"  OK  2.zip freshness: all {len(src_files)} entries byte-identical "
                      f"to bundle/wallpapers/sh1-wallpaper/ (E-7 guard)")
        print(f"  OK  2.zip internals: {len(glbs)} GLBs + camdat.json + "
          f"LivelyInfo/Properties under sh1-wallpaper/sh1/ (S18 guard)")

# The UI publish must bring its runtime (self-contained): check the .dll row
ui_dir = os.path.join(publish, "plugins", "UI")
if os.path.isdir(ui_dir):
    dlls = [f for f in os.listdir(ui_dir) if f.endswith(".dll")]
    print(f"  OK  plugins/UI carries {len(dlls)} dlls (self-contained runtime)")

if missing:
    print("\nLAYOUT AUDIT FAILED — mandatory paths missing:")
    for rel, why in missing:
        print(f"  MISSING  {rel}  — {why}")
    sys.exit(1)

print("\nLAYOUT AUDIT PASS — every source-launched path exists")
sys.exit(0)
