# Lively Wallpaper — SH1 Fog Engine port

Fork of [Lively Wallpaper](https://github.com/lively-community/lively) (GPL-3.0) with a **native Silent Hill 1 fog-engine wallpaper type integrated into the app itself** — not an external exe package.

## What was added

**`WallpaperType.sh1`** — a new first-class wallpaper type:

- `src/Lively/Lively.Player.Sh1/` — the GPL engine (`fog_poc.c` + embedded TIM assets, the sh-clock/PoC v39 tree) with a `#ifdef LIVELY_PLAYER` seam: lively `--wallpaper-*` args, stdout JSON IPC (`msg_hwnd`/`msg_wploaded` handshake), a stdin command thread (suspend/resume/close + **live** `lp_dropdown` scene/env switches and `lp_chekbox` fog/snow/dither/wobble/flashlight toggles), and a borderless `WS_POPUP` window loop. Plain builds (no define) are **bit-identical** to the upstream engine.
- `src/Lively/Lively/Core/Wallpapers/Sh1Wallpaper.cs` — the app-side `IWallpaper` player (modeled on `WebWebView2`): launches `plugins\sh1\Lively.Player.Sh1.exe`, reads the stdout handshake, delivers stdin commands.
- `WallpaperPluginFactory` dispatch, `WallpaperType.sh1` enum member, `WallpaperExtensions` (directory-project + device-input), `Constants.PlayerPartialPaths.Sh1Path`, `ResourceService` names, `WallpaperLibraryFactory` import case.
- `bundle/wallpapers/2.zip` — the bundled SH1 wallpaper (44 scene GLBs + camdat + schema-valid `LivelyProperties.json`) that auto-installs into the user's library on first boot; the Customise panel drives it live.

## CI

`.github/workflows/sh1-app.yml` (windows-latest): zig cc builds the native player, dotnet builds the app, the bundle + player are staged, three regression gates run (render non-blank, SU0203 motion, SUFFFE waterfall), and tag pushes publish a release.

## Verify locally

```
zig cc -target x86_64-windows-gnu -O2 -std=c99 -DLIVELY_PLAYER \
    -o Lively.Player.Sh1.exe src/Lively/Lively.Player.Sh1/fog_poc.c -luser32 -lgdi32
dotnet build src/Lively/Lively/Lively.csproj -p:EnableWindowsTargeting=true
```

## Legal

Lively Wallpaper: GPL-3.0 (rocksdanister/lively-community). The SH1 engine code: GPL-3.0, logic ported from silent-hill-decomp research. Scene data: © Konami, non-commercial fan preservation. Not affiliated with Konami.
