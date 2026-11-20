#!/usr/bin/env python3
"""Insert the LIVELY_PLAYER seam into the engine copy used by
Lively.Player.Sh1. The seam mirrors the __ANDROID__ integration pattern:
a new #ifdef LIVELY_PLAYER block placed right before run_realtime(), with
 - the lively wallpaper cmdline contract (--wallpaper-*)
 - the stdout JSON IPC channel (printf is re-routed: chatter -> silent,
   only IPC lines on stdout, exactly like the C# players' WriteToParent)
 - the stdin command thread (cmd_suspend/cmd_resume/cmd_close/lp_* props)
 - a borderless WS_POPUP window loop that reports msg_hwnd + msg_wploaded
   and consumes the IPC requests each frame (pause/play/property changes).
Zero engine math is touched: the seam only calls the existing live_advance/
render_frame/fb_to_argb/win32_present and the same toggle entry points the
keyboard handler uses (K_SPACE/K_M/K_B/K_D/K_P/K_F semantics).
Run from the repo root: python3 tools/insert_lively_seam.py
"""
import re, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "Lively", "Lively.Player.Sh1", "fog_poc.c")
src = open(SRC, encoding="utf-8").read()

if "#ifdef LIVELY_PLAYER" in src:
    print("seam already present")
    sys.exit(0)

SEAM = r'''
/* ==================================================================== */
/* LIVELY PLAYER SEAM — the Lively Wallpaper app integration.           */
/* Compiled only with -DLIVELY_PLAYER (the shipped plugins\sh1 exe).    */
/* Mirrors the __ANDROID__ seam philosophy: presentation + IPC only,   */
/* ZERO engine math touched.                                            */
/*                                                                      */
/* The contract (verified against Lively's own players, GPLv3):         */
/*  - stdout is the IPC channel: JSON lines, one object per line,       */
/*    {"Type":0,"Hwnd":<int>}  = msg_hwnd (the child window handle)     */
/*    {"Type":2,"Success":true} = msg_wploaded (first frame presented)  */
/*    {"Type":1,"Category":...,"Message":...} = console log/error       */
/*    Everything else the engine prints goes to /dev/null (the C#       */
/*    players do exactly this — Console.WriteLine IS the wire).         */
/*  - stdin is the command channel: JSON lines                           */
/*    {"Type":7} suspend   {"Type":8} resume   {"Type":5} close         */
/*    {"Type":9,"Volume":N} (ignored — silent engine, kept for parity)  */
/*    {"Type":14,"Name":..,"Value":N} lp_dropdown (scene / env pair)    */
/*    {"Type":18,"Name":..,"Value":true|false} lp_chekbox (fog/snow/..) */
/*    {"Type":12,"Name":..,"Value":N} lp_slider (fps cap)              */
/*  - The window is WS_POPUP borderless (Lively parents it to WorkerW   */
/*    and sizes it to the display; ExtPrograms/WebWebView2 parity).      */
/* ==================================================================== */
#ifdef LIVELY_PLAYER

static LiveApp *g_lp_app = NULL;
static HWND g_lp_hwnd = NULL;
static volatile int g_lp_quit = 0;      /* cmd_close / WM_DESTROY        */
static volatile int g_lp_suspend = 0;   /* cmd_suspend / cmd_resume      */
static volatile int g_lp_loaded_reported = 0;
static volatile int g_lp_fps_cap = 0;   /* lp_slider "fps" (0 = default) */

/* -- the property request slots (consumed on the render frame ---------- */
#define LP_SCENE_MAX 32
static char g_lp_scene_new[LP_SCENE_MAX] = {0};   /* "" = no request     */
static volatile int g_lp_scene_reload = 0;
static int  g_lp_prop_fog = -1, g_lp_prop_snow = -1;
static int  g_lp_prop_dither = -1, g_lp_prop_wobble = -1;
static int  g_lp_prop_flashlight = -1;
static int  g_lp_prop_pair0 = -1, g_lp_prop_pair1 = -1;

/* -- tiny JSON scan helpers over a single command line ----------------- *
 * The C# side sends well-formed single-line JSON from known senders
 * (Lively's own JsonConvert.SerializeObject of fixed message classes),
 * so a targeted scan (not a full parser) is the robust minimal core.   */
static int lp_json_int(const char *j, const char *key) {
    char pat[64]; snprintf(pat, sizeof(pat), "\"%s\":", key);
    const char *p = strstr(j, pat);
    if (!p) return -1;
    p += strlen(pat);
    while (*p == ' ' || *p == '\t') p++;
    return (int)strtol(p, NULL, 10);
}
static int lp_json_bool(const char *j, const char *key, int dflt) {
    char pat[64]; snprintf(pat, sizeof(pat), "\"%s\":", key);
    const char *p = strstr(j, pat);
    if (!p) return dflt;
    p += strlen(pat);
    while (*p == ' ' || *p == '\t') p++;
    if (!strncmp(p, "true", 4)) return 1;
    if (!strncmp(p, "false", 5)) return 0;
    return dflt;
}
/* lp_json_str: copy a JSON string value (no escapes in our senders) */
static int lp_json_str(const char *j, const char *key,
                       char *out, size_t outn) {
    char pat[64]; snprintf(pat, sizeof(pat), "\"%s\":\"", key);
    const char *p = strstr(j, pat);
    if (!p) return 0;
    p += strlen(pat);
    const char *e = strchr(p, '"');
    if (!e) return 0;
    size_t n = (size_t)(e - p);
    if (n >= outn) n = outn - 1;
    memcpy(out, p, n); out[n] = 0;
    return 1;
}

/* the engine scene names (the 44-room corpus) — validated before reload */
static const char *g_lp_scenes[] = {
"APU0002","APU00FF","APUFFFE","DR0000","DR0100","DRFD00","DRU0100",
"ER00FE","ER01FC","ER01FE","ER0201","ER02FC","ER0301","ER03FD",
"ER0401","ERFCFC","ERFDFE","ERFDFF","ERFFFF","HP0003","HP0100",
"HU0001","HU0103","HU01FF","SCFD00","SCFE00","SPU0100","SPU0301",
"SPU03FD","SPU0401","SU0001","SU00FF","SU01FE","SU0203","SUFE00",
"SUFFFE","SUFFFF","THR05FE","THRF905","THRF906","THRF9FC",
"THRF9FD","THRF9FE","THRFE08",
};
#define LP_SCENE_COUNT (int)(sizeof(g_lp_scenes)/sizeof(g_lp_scenes[0]))

/* -- IPC OUT (stdout = the wire; chatter is silenced) ------------------ */
static void lp_ipc(const char *json) {
    if (!json || !*json) return;
    fputs(json, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}
static void lp_send_hwnd(HWND hwnd) {
    char line[96];
    snprintf(line, sizeof(line), "{\"Type\":0,\"Hwnd\":%ld}",
             (long)(intptr_t)hwnd);
    lp_ipc(line);
}
static void lp_send_loaded(int ok) {
    lp_ipc(ok ? "{\"Type\":2,\"Success\":true}"
              : "{\"Type\":2,\"Success\":false}");
}
static void lp_send_console(int error, const char *msg) {
    /* JSON-escape the minimal set that ever appears in engine messages */
    char esc[512]; size_t o = 0;
    for (const char *s = msg; *s && o + 6 < sizeof(esc); s++) {
        char c = *s;
        if (c == '\n') { esc[o++]='\\'; esc[o++]='n'; }
        else if (c == '\r') { esc[o++]='\\'; esc[o++]='r'; }
        else if (c == '"') { esc[o++]='\\'; esc[o++]='"'; }
        else if (c == '\\') { esc[o++]='\\'; esc[o++]='\\'; }
        else if ((unsigned char)c < 0x20) { /* drop other controls */ }
        else esc[o++] = c;
    }
    esc[o] = 0;
    char line[560];
    snprintf(line, sizeof(line),
             "{\"Type\":1,\"Category\":%d,\"Message\":\"%s\"}",
             error ? 1 : 0, esc);
    lp_ipc(line);
}

/* in LIVELY_PLAYER builds the engine's printf(...) chatter is REROUTED
 * away from stdout (the C# players keep stdout clean for the IPC wire;
 * Android's seam did the same to logcat). fprintf(stderr,...) stays.   */
#define printf(...) ((void)0)   /* chatter silenced; stderr untouched    */

/* -- IPC IN: the stdin command thread ---------------------------------- */
static DWORD WINAPI lp_stdin_thread(LPVOID arg) {
    (void)arg;
    char line[1024];
    size_t n = 0;
    int c;
    /* _fgetchar on the redirected pipe; NULL line (EOF) => parent gone */
    while ((c = _fgetchar()) != EOF) {
        if (c == '\n' || c == '\r') {
            if (n == 0) continue;
            line[n] = 0;
            int type = lp_json_int(line, "Type");
            switch (type) {
            case 7: g_lp_suspend = 1; break;             /* cmd_suspend  */
            case 8: g_lp_suspend = 0; break;             /* cmd_resume   */
            case 5: g_lp_quit = 1; break;                /* cmd_close    */
            case 9: /* volume: silent engine — accepted, ignored */ break;
            case 12: { /* lp_slider: only "fps" is a live concern      */
                char name[64] = {0};
                lp_json_str(line, "Name", name, sizeof(name));
                if (!strcmp(name, "fps"))
                    g_lp_fps_cap = lp_json_int(line, "Value");
                break;
            }
            case 14: { /* lp_dropdown: scene / envpair               */
                char name[64] = {0}, val[LP_SCENE_MAX] = {0};
                lp_json_str(line, "Name", name, sizeof(name));
                if (!strcmp(name, "scene") &&
                    lp_json_str(line, "Value", val, sizeof(val))) {
                    int hit = -1;
                    for (int i = 0; i < LP_SCENE_COUNT; i++)
                        if (!strcmp(val, g_lp_scenes[i])) { hit = i; break; }
                    if (hit >= 0) {
                        snprintf(g_lp_scene_new, LP_SCENE_MAX, "%s", val);
                        g_lp_scene_reload = 1;
                    } else {
                        lp_send_console(1, "unknown scene (dropdown index "
                                          "out of range)");
                    }
                } else if (!strcmp(name, "envpair")) {
                    /* the C# DropdownModel sends the ITEM STRING; the
                     * bundled properties use "camdat" or "A,B"         */
                    if (!strcmp(val, "camdat")) {
                        g_lp_prop_pair0 = -2;   /* -2 = revert to authored */
                    } else {
                        int a = -1, b = -1;
                        if (sscanf(val, "%d,%d", &a, &b) == 2 &&
                            a >= 0 && a <= 20 && b >= 0 && b <= 20) {
                            g_lp_prop_pair0 = a; g_lp_prop_pair1 = b;
                        }
                    }
                }
                break;
            }
            case 18: { /* lp_chekbox: fog/snow/dither/wobble/flashlight  */
                char name[64] = {0};
                lp_json_str(line, "Name", name, sizeof(name));
                int v = lp_json_bool(line, "Value", -1);
                if (v >= 0) {
                    if      (!strcmp(name, "fog"))        g_lp_prop_fog = v;
                    else if (!strcmp(name, "snow"))       g_lp_prop_snow = v;
                    else if (!strcmp(name, "dither"))     g_lp_prop_dither = v;
                    else if (!strcmp(name, "wobble"))     g_lp_prop_wobble = v;
                    else if (!strcmp(name, "flashlight")) g_lp_prop_flashlight = v;
                    /* "night" handled at boot only (a boot env, not live) */
                }
                break;
            }
            default: break;   /* unknown/unsupported: ignore, keep running */
            }
            n = 0;
        } else if (n + 1 < sizeof(line)) {
            line[n++] = (char)c;
        }
    }
    /* stdin closed = parent died: exit soon (the watchdog path) */
    g_lp_quit = 1;
    return 0;
}

/* -- the borderless player window loop --------------------------------- */
static LRESULT CALLBACK lp_wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    if (msg == WM_CLOSE || msg == WM_DESTROY) {
        g_lp_quit = 1;
        PostQuitMessage(0);
        return 0;
    }
    if (msg == WM_ERASEBKGND) return 1;
    if (msg == WM_PAINT) {
        PAINTSTRUCT ps;
        BeginPaint(hwnd, &ps);
        EndPaint(hwnd, &ps);
        if (g_lp_app) win32_present(hwnd, g_lp_app);
        return 0;
    }
    return DefWindowProcA(hwnd, msg, wp, lp);
}

/* apply pending property toggles ONCE per presented frame — using the
 * SAME toggle entry semantics as the keyboard handler (the engine's own
 * live_action cases), never touching the math directly.               */
static void lp_apply_props(LiveApp *A) {
    if (g_lp_prop_fog >= 0) {
        if ((A->R.fogEnabled ? 1 : 0) != g_lp_prop_fog) {
            A->R.fogEnabled = g_lp_prop_fog;   /* K_M semantics, set-not-toggled */
        }
        g_lp_prop_fog = -1;
    }
    if (g_lp_prop_snow >= 0) {
        if ((A->snow.enabled ? 1 : 0) != g_lp_prop_snow) {
            A->snow.enabled = g_lp_prop_snow;
            if (A->snow.enabled) snow_reset(&A->snow);
        }
        g_lp_prop_snow = -1;
    }
    if (g_lp_prop_dither >= 0) {
        if ((A->R.dither ? 1 : 0) != g_lp_prop_dither) A->R.dither = g_lp_prop_dither;
        g_lp_prop_dither = -1;
    }
    if (g_lp_prop_wobble >= 0) {
        int ps1 = A->R.opts.ps1 ? 1 : 0;
        if (ps1 != g_lp_prop_wobble) {
            A->R.opts.ps1 = g_lp_prop_wobble;
            A->R.opts.linear = !g_lp_prop_wobble;
            A->R.quantize = A->R.opts.ps1;
        }
        g_lp_prop_wobble = -1;
    }
    if (g_lp_prop_flashlight >= 0) {
        int fl = A->env.isFlashlightOn ? 1 : 0;
        if (fl != g_lp_prop_flashlight &&
            sh_env_flashlight_allowed(&A->env)) {
            sh_flashlight_toggle(&A->env);   /* K_F semantics verbatim */
        }
        g_lp_prop_flashlight = -1;
    }
    if (g_lp_prop_pair0 == -2) {   /* "camdat": revert to the authored env */
        /* the boot pair is re-derived from the GLB/camdat exactly like the
         * boot path: the simplest verbatim route is live_apply_preset on
         * the room's own SH1X env indices when present */
        if (A->R.sc && A->R.sc->sh1x.hasEnv)
            live_apply_preset(A, A->R.sc->sh1x.envIdx1, "lively envpair=camdat");
        g_lp_prop_pair0 = -1;
    } else if (g_lp_prop_pair0 >= 0) {
        live_apply_preset(A, g_lp_prop_pair0, "lively envpair"); /* Gfx_MapEnvSet */
        g_lp_prop_pair0 = -1;
    }
}

static const char *g_lp_glb_path = NULL;
static const char *g_lp_camdat_path = NULL;
static const char *g_lp_input_dir = NULL;
static const char *g_lp_props_path = NULL;

static int run_window_lively(LiveApp *A, const char *lpSceneGlb,
                             const char *lpCamdat, const char *lpInput,
                             const char *lpProps) {
    (void)lpProps;   /* restored by the APP before launch (args carry it) */
    g_lp_app = A;
    SetProcessDPIAware();

    void *winmm = sys_dlopen("winmm.dll");
    time_period_fn tbp = NULL, tep = NULL;
    if (winmm) {
        tbp = (time_period_fn)sys_dlsym(winmm, "timeBeginPeriod");
        tep = (time_period_fn)sys_dlsym(winmm, "timeEndPeriod");
        if (tbp) tbp(1u);
    }

    WNDCLASSA wc;
    memset(&wc, 0, sizeof(wc));
    wc.style = CS_OWNDC;
    wc.lpfnWndProc = lp_wndproc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "LIVELY_PLAYER_SH1";
    RegisterClassA(&wc);

    /* borderless WS_POPUP at a lively-plausible size; lively's
     * TrySetWallpaperPerScreen does SetWindowPos to the display bounds
     * right after parenting — the engine just renders whatever client
     * rect it is given (win32_present reads GetClientRect).           */
    HWND hwnd = CreateWindowA("LIVELY_PLAYER_SH1", "Lively SH1 Player",
                              WS_POPUP | WS_VISIBLE,
                              0, 0, 1280, 720,
                              NULL, NULL, wc.hInstance, NULL);
    if (!hwnd) {
        lp_send_console(1, "CreateWindow failed");
        return 0;
    }
    g_lp_hwnd = hwnd;

    /* THE HANDSHAKE: report the window handle (msg_hwnd). Lively's
     * app-side then parents this hwnd to the WorkerW. */
    lp_send_hwnd(hwnd);

    /* the stdin command thread */
    HANDLE th = CreateThread(NULL, 0, lp_stdin_thread, NULL, 0, NULL);
    if (th) CloseHandle(th);

    MSG msg;
    double prev = now_sec();
    int frames = 0; double statT = 0;

    while (!g_lp_quit) {
        while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) { g_lp_quit = 1; break; }
            TranslateMessage(&msg);
            DispatchMessageA(&msg);
        }
        if (g_lp_quit) break;

        /* LIVE SCENE SWITCH (lp_dropdown scene): full reload like the app
         * restart path — load the new GLB, re-bind camdat, restart state */
        if (g_lp_scene_reload && g_lp_scene_new[0]) {
            g_lp_scene_reload = 0;
            char path[512];
            snprintf(path, sizeof(path), "%s\\%s.glb",
                     lpInput ? lpInput : ".", g_lp_scene_new);
            Scene nsc;
            if (scene_load_glb(&nsc, path)) {
                Camdat ncd;
                if (camdat_load(&ncd, lpCamdat ? lpCamdat : "camdat.json",
                                path)) {
                    /* swap under the same discipline the boot path uses */
                    scene_free((Scene *)A->R.sc);
                    camdat_free((Camdat *)A->cd);
                    memcpy((Scene *)A->R.sc, &nsc, sizeof(nsc));
                    memcpy((Camdat *)A->cd, &ncd, sizeof(ncd));
                    A->track = &A->cd->tracks[A->cd->activeTrack];
                    A->play.t = 0; A->play.sessionT = 0;
                    A->play.speed = 1.0;
                    sh1x_anims_reset((Sh1x *)&((Scene *)A->R.sc)->sh1x);
                    turn_init(&A->play.turn);
                    lp_send_console(0, "scene switched");
                } else {
                    scene_free(&nsc);
                    lp_send_console(1, "camdat re-bind failed");
                }
            } else {
                lp_send_console(1, "GLB load failed");
            }
            prev = now_sec();
        }

        double t0 = now_sec();
        double dt = t0 - prev;
        prev = t0;

        /* suspend = hold the frame (the C# players pause media + notify;
         * the engine equivalent is the paused hold: no ticks, no render;
         * the last presented buffer stays — the WorkerW surface keeps it */
        if (g_lp_suspend) {
            Sleep(50);
            lp_apply_props(A);   /* property changes still apply + repaint */
            CamPose cp = live_current_pose(A);
            render_frame(&A->fb, &A->R, &cp);
            fb_to_argb(&A->fb, A->argb);
            win32_present(hwnd, A);
            continue;
        }

        CamPose cp = live_advance(A, dt);
        render_frame(&A->fb, &A->R, &cp);
        fb_to_argb(&A->fb, A->argb);
        win32_present(hwnd, A);

        lp_apply_props(A);

        /* the fps slider cap (0 = the engine's authentic 30) */
        double cap = g_lp_fps_cap > 0 ? (double)g_lp_fps_cap : A->maxFps;
        live_pace(t0, cap > 0 ? 1.0 / cap : 0.0);

        double t1 = now_sec();
        frames++; statT += t1 - t0;
        if (statT >= 0.25) {
            A->play.fps = (double)frames / statT;
            frames = 0; statT = 0;
        }

        /* msg_wploaded AFTER the first presented frame (the C# players
         * report it once the content is on screen) */
        if (!g_lp_loaded_reported) {
            g_lp_loaded_reported = 1;
            lp_send_loaded(1);
        }
    }

    if (IsWindow(hwnd)) DestroyWindow(hwnd);
    g_lp_hwnd = NULL;
    g_lp_app = NULL;
    if (tep) tep(1u);
    return 1;
}
#endif /* LIVELY_PLAYER */
'''

anchor = "/* ------------------------------------------------------------------ */\n/* realtime dispatcher + headless benchmark                            */"
assert anchor in src, "anchor (run_realtime header comment) not found"
src = src.replace(anchor, SEAM + "\n" + anchor, 1)

# 2) run_realtime dispatch: LIVELY_PLAYER builds route to the lively loop
old_dispatch = """static int run_realtime(LiveApp *A, int winW, int winH) {
#if defined(_WIN32)
    return run_window_win32(A, winW, winH);"""
new_dispatch = """static int run_realtime(LiveApp *A, int winW, int winH) {
#ifdef LIVELY_PLAYER
    (void)winW; (void)winH;
    return run_window_lively(A, g_lp_glb_path, g_lp_camdat_path,
                             g_lp_input_dir, g_lp_props_path);
#elif defined(_WIN32)
    return run_window_win32(A, winW, winH);"""
assert old_dispatch in src, "run_realtime dispatch not found"
src = src.replace(old_dispatch, new_dispatch, 1)

open(SRC, "w", encoding="utf-8").write(src)
print("seam inserted; dispatch routed")
