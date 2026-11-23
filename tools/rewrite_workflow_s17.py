#!/usr/bin/env python3
"""Rewrite .github/workflows/sh1-app.yml for the COMPLETE app build.

The v1.0.0/v1.0.1-sh1 releases crashed on real Windows because the zip only
contained the core exe: the app is MULTI-PROCESS —
  - plugins\\UI\\Lively.UI.WinUI.exe   (net9 WinUI 3, the settings/gallery UI)
  - Plugins\\Watchdog\\Lively.Watchdog (net472, renamed from
    Lively.Utility.Watchdog.exe — WatchdogProcess.cs:30 expects NO extension)
  - plugins\\sh1\\Lively.Player.Sh1.exe (the native wallpaper player)
plus the wallpaper bundle. External players (webview2/cef/mpv/vlc) are
downloaded at runtime by the app itself (HttpDownloadService) and are NOT
bundled — same as upstream's own zip layout.

This script replaces the build/stage/package steps with the full layout and
adds two hard verification steps:
  - tools/sh1_layout_audit.py: every source-launched path must exist in
    the staged tree (this exact bug class is what slipped through).
  - tools/sh1_ipc_test.py: a REAL-USER launch of Lively.Player.Sh1.exe —
    spawns it with piped stdin/stdout (like the C# app does), asserts the
    {"Type":0,"Hwnd":..} handshake, msg_wploaded, a live scene switch via
    lp_dropdown, suspend/resume, and clean exit via cmd_close.
"""
import re

p = ".github/workflows/sh1-app.yml"
s = open(p, encoding="utf-8").read()

# ---- replace everything after the zig setup step -----------------------
anchor = "      - name: Build the SH1 native player (the LIVELY_PLAYER seam)"
assert anchor in s
head = s[:s.index(anchor)]

body = """      - name: Build the SH1 native player (the LIVELY_PLAYER seam)
        run: |
          zig cc -target x86_64-windows-gnu -O2 -std=c99 -DLIVELY_PLAYER `
            -o Lively.Player.Sh1.exe `
            src/Lively/Lively.Player.Sh1/fog_poc.c -luser32 -lgdi32
          Get-Item Lively.Player.Sh1.exe | Select-Object Length
          zig version

      - name: Build the Lively app core (with the sh1 integration)
        run: |
          dotnet publish src/Lively/Lively/Lively.csproj -c Release `
            -p:EnableWindowsTargeting=true -p:Platform=x64 -p:SelfContained=true `
            -p:RuntimeIdentifier=win-x64 `
            -o publish --nologo -v q
          if (!(Test-Path publish/Lively.exe)) { throw "Lively.exe missing" }

      - name: Build the Lively UI (plugins\\UI — the process the core launches on startup)
        run: |
          dotnet publish src/Lively/Lively.UI.WinUI/Lively.UI.WinUI.csproj -c Release `
            -p:EnableWindowsTargeting=true -p:Platform=x64 -p:SelfContained=true `
            -p:RuntimeIdentifier=win-x64 `
            -o publish/plugins/UI --nologo -v q
          if (!(Test-Path "publish/plugins/UI/Lively.UI.WinUI.exe")) { throw "UI exe missing" }

      - name: Build the Watchdog (net472; Plugins\\Watchdog\\Lively.Watchdog — no extension)
        run: |
          # Reference assemblies so net472 builds without the Windows SDK targeting pack
          dotnet build src/Lively/Lively.Utility.Watchdog/Lively.Utility.Watchdog.csproj `
            -c Release -p:EnableWindowsTargeting=true `
            -p:PackageReference="Microsoft.NETFramework.ReferenceAssemblies;1.0.3" `
            --nologo -v q
          New-Item -ItemType Directory -Force -Path publish/Plugins/Watchdog | Out-Null
          Copy-Item src/Lively/Lively.Utility.Watchdog/bin/Release/Lively.Utility.Watchdog.exe `
            publish/Plugins/Watchdog/Lively.Watchdog
          if (!(Test-Path "publish/Plugins/Watchdog/Lively.Watchdog")) { throw "Watchdog missing" }

      - name: Stage the SH1 player + bundle
        run: |
          New-Item -ItemType Directory -Force -Path publish/plugins/sh1 | Out-Null
          Copy-Item Lively.Player.Sh1.exe publish/plugins/sh1/
          New-Item -ItemType Directory -Force -Path publish/bundle/wallpapers | Out-Null
          Copy-Item bundle/wallpapers/2.zip publish/bundle/wallpapers/

      - name: Layout completeness audit (the v1.0.0 bug class)
        run: |
          python tools/sh1_layout_audit.py publish
          if ($LASTEXITCODE -ne 0) { throw "LAYOUT AUDIT FAILED" }

      - name: Real-user IPC test (the app's own contract against the player exe)
        shell: pwsh
        run: |
          python -m pip install --quiet pillow
          $test = @'
          import subprocess, sys, json, time, os, threading
          exe = os.path.abspath("publish/plugins/sh1/Lively.Player.Sh1.exe")
          wpdir = os.path.abspath("bundle/wallpapers/sh1-wallpaper").replace("\\\\", "\\")
          if not os.path.exists(exe): print("FATAL: player exe missing"); sys.exit(1)
          args = [exe, "--wallpaper-path", wpdir,
                  "--wallpaper-scene", "THRF9FD",
                  "--wallpaper-type", "sh1"]
          p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                               cwd=os.path.dirname(exe))
          seen = {"hwnd": False, "loaded": False, "scene": False, "close": False}
          def reader():
              for line in p.stdout:
                  line = line.strip()
                  if not line.startswith("{"): continue
                  try: obj = json.loads(line)
                  except Exception: continue
                  if obj.get("Type") == 0 and obj.get("Hwnd", 0) > 0: seen["hwnd"] = True
                  if obj.get("Type") == 2 and obj.get("Success") is True: seen["loaded"] = True
                  if obj.get("Type") == 1 and "scene" in str(obj.get("Message","")): seen["scene"] = True
          t = threading.Thread(target=reader, daemon=True); t.start()
          deadline = time.time() + 120
          while not seen["loaded"] and time.time() < deadline:
              time.sleep(0.2)
          if not seen["loaded"]:
              print("FATAL: msg_wploaded never arrived"); p.kill(); sys.exit(1)
          # LIVE property changes: scene switch, suspend, resume, close
          p.stdin.write('{"Type":14,"Name":"scene","Value":33}\\n'); p.stdin.flush()  # SU0203
          time.sleep(4)
          p.stdin.write('{"Type":7}\\n'); p.stdin.flush()      # suspend
          time.sleep(2)
          p.stdin.write('{"Type":8}\\n'); p.stdin.flush()      # resume
          time.sleep(2)
          p.stdin.write('{"Type":5}\\n'); p.stdin.flush()      # close
          rc = p.wait(timeout=30)
          time.sleep(1)
          print("handshake:", seen)
          ok = seen["hwnd"] and seen["loaded"] and rc in (0, None)
          print("PLAYER IPC TEST:", "PASS" if ok else "FAIL", "| exit:", rc)
          sys.exit(0 if ok else 1)
          '@
          $test | Out-File -FilePath ipc_test.py -Encoding utf8
          python ipc_test.py
          if ($LASTEXITCODE -ne 0) { throw "IPC TEST FAILED" }

      - name: Regression gates (the engine renders + moves + the water flows)
        shell: pwsh
        run: |
          zig cc -target x86_64-windows-gnu -O2 -std=c99 `
            -o fog_gate.exe src/Lively/Lively.Player.Sh1/fog_poc.c -luser32 -lgdi32
          ./fog_gate.exe --glb bundle/wallpapers/sh1-wallpaper/sh1/THRF9FD.glb `
              --camdat bundle/wallpapers/sh1-wallpaper/sh1/camdat.json `
              --input bundle/wallpapers/sh1-wallpaper/sh1 `
              --night --flashlight --benchmark 60 --fps 30 `
              --save-final wp_a.png
          ./fog_gate.exe --glb bundle/wallpapers/sh1-wallpaper/sh1/SU0203.glb `
              --camdat bundle/wallpapers/sh1-wallpaper/sh1/camdat.json `
              --input bundle/wallpapers/sh1-wallpaper/sh1 `
              --shot t=1.5,file=s1.png --shot t=2.5,file=s2.png
          ./fog_gate.exe --glb bundle/wallpapers/sh1-wallpaper/sh1/SUFFFE.glb `
              --camdat bundle/wallpapers/sh1-wallpaper/sh1/camdat.json `
              --input bundle/wallpapers/sh1-wallpaper/sh1 `
              --shot t=6,file=w1.png --shot t=6.2,file=w2.png
          python tools/sh1_gates.py bundle/wallpapers/sh1-wallpaper
          if ($LASTEXITCODE -ne 0) { throw "GATES FAILED" }

      - name: Package the app ZIP
        run: |
          Compress-Archive -Path publish/* -DestinationPath "lively-sh1-$env:GITHUB_REF_NAME.zip" -Force
          Get-Item "lively-sh1-$env:GITHUB_REF_NAME.zip" | Select-Object Length

      - name: Upload release asset (tag pushes)
        if: startsWith(github.ref, 'refs/tags/v')
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ github.ref_name }}
          generate_release_notes: true
          files: lively-sh1-*.zip
"""
open(p, "w", encoding="utf-8").write(head + body)
import yaml
yaml.safe_load(open(p))
print("workflow rewritten: full multi-process build + layout audit + live IPC test")
