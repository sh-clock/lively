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
