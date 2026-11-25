# Lively Wallpaper — SH1 Fog Engine port

Fork of [Lively Wallpaper](https://github.com/lively-community/lively) (GPL-3.0) with a **native Silent Hill 1 fog-engine wallpaper type integrated into the app itself** — not an external exe package.

## What was added

**`WallpaperType.sh1`** — a new first-class wallpaper type:

- `src/Lively/Lively.Player.Sh1/` — the GPL engine (`fog_poc.c` + embedded TIM assets, the sh-clock/PoC tree **@ e1f35af, v33.25** — resynced V42 from the stale v39 base: D-1/D-2 TV 4bpp, D-F2 clut, A-F1 glint, the sprite-quad interior + (v2,v1,v3) split, C-1..C-5 + the V42 C-2 flare occluded-branch gate, A-3..A-6, B-1/B-6/B-B1/B-B9/A-F6/C-F1..C-F3, E-1..E-5/E-8..E-13 CLI hardening, --snow-seed, the R-restart group, Gate-2 chain, light.ahead mode-2) with a `#ifdef LIVELY_PLAYER` seam: lively `--wallpaper-*` args, stdout JSON IPC (`msg_hwnd`/`msg_wploaded` handshake), a stdin command thread (suspend/resume/close + **live** `lp_dropdown` scene/env switches and `lp_chekbox` fog/snow/dither/wobble/flashlight toggles), and a borderless `WS_POPUP` window loop. The `#ifdef LIVELY_PLAYER` seam (plus the `LP_POSIX_STUB` Linux test surface, compiled out on Windows) is the ONLY engine-file delta besides the C-2 flare gate; the full file diff vs PoC main = the C-2 hunks + the seam + the sanctioned main()-layer inherited hunks (the S19 `--tim-file` viewer before camdat discovery — the one plain-mode delta, re-landed by the w8 audit after it silently went missing; the three S18 `<dir>/sh1/` bundle probes for camdat/scene/default GLB live INSIDE the LIVELY_PLAYER seam, LIVELY-only; zero engine math, render-parity-neutral; plain CLI differs from PoC in exactly one case: a lone `--tim-file` boots the viewer here where PoC exits "cannot find camdat.json" — `--input <bundle>` boots the bundled scene only via the seam's probe, the plain CLI is otherwise identical). Plain-mode render probes are md5-equal vs the PoC binary (V42-verified 5/5, re-verified 6/6 after the merge — the plain binary is 512 B larger from the carried hunks). `tim_load` is byte-identical to PoC main's V41-E5 hardened form (exact read-extent checks); the S19-local plen/cavail clamps were dropped — cavail was provably dead under PoC's blen checks, and the plen clamp's acceptance narrowing (reject plen-understating files) gave way to PoC's documented plen-advisory semantics (file-length-bounded reads either way).
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
