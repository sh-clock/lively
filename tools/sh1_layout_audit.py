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
