#!/usr/bin/env python3
"""sh1_type16_logic_test.py — the LOCAL logic-level test for the Type-16
"Restore default" handler (lp_reload_props_live, S19 audit D1).

The end-to-end IPC contract (real exe + real panel messages) is covered on
CI by tools/sh1_type16_ipc_test.py (needs Windows). This test compiles a
tiny C harness that #includes the ACTUAL fog_poc.c functions VERBATIM
(extracted from the shipped source, never re-typed):

  - the 7 lp_json_* scan helpers (the same set sh1_nested_props_test.py
    extracts), and
  - lp_reload_props_live itself — the function the Type-16 case calls,
  - the g_lp_scenes table (the same 44 scene names, verbatim),

plus faithful re-declarations of the seam slot statics it writes (the same
types/initializers the file declares: g_lp_prop_fog family, g_lp_fps_cap,
g_lp_prop_pair0/1, g_lp_scene_new, g_lp_scene_reload). lp_send_console is
stubbed to a printf (the harness observes the ack).

Every case: stage a DIVERGED live state (the user's modified settings),
point g_lp_props_path at the case file (what CustomiseWallpaperViewModel
re-copied just before sending Type 16), call lp_reload_props_live once,
and CHECK every slot against the expected revert.

Cases: the pristine bundled schema, a diverged panel-schema copy, flat
hand-sender shapes, envpair int-index / camdat forms, scene by name vs by
index, out-of-range fps/envpair/scene (ignored — slot keeps prior), a
missing file (silent no-op), and readable malformed JSON (no-op revert
with the ack — the shipped control flow acks after the early bails).

Exit non-zero on any mismatch.
"""
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOG = os.path.join(REPO, "src", "Lively", "Lively.Player.Sh1", "fog_poc.c")
PROPS = os.path.join(REPO, "bundle", "wallpapers", "sh1-wallpaper",
                     "LivelyProperties.json")

if not os.path.exists(FOG):
    print("FATAL: engine source missing:", FOG); sys.exit(1)
if not os.path.exists(PROPS):
    print("FATAL: bundled LivelyProperties.json missing:", PROPS); sys.exit(1)

src = open(FOG, encoding="utf-8").read()


def grab(sig):
    i = src.index(sig)
    j = src.index("\n}", i)
    return src[i:j + 2]


def grab_semi(sig):
    """extract a top-level declaration that ends with `};` (arrays)."""
    i = src.index(sig)
    j = src.index("\n};", i)
    return src[i:j + 3]


helpers = "\n".join(grab(f) for f in [
    "static int lp_json_int(const char *j, const char *key)",
    "static int lp_json_bool(const char *j, const char *key, int dflt)",
    "static int lp_json_str(const char *j, const char *key,\n                       char *out, size_t outn)",
    "static const char *lp_json_value_ptr(const char *j, const char *key)",
    "static int lp_json_value_int(const char *j, const char *key)",
    "static int lp_json_value_bool(const char *j, const char *key, int dflt)",
    "static int lp_json_value_str(const char *j, const char *key,\n                             char *out, size_t outn)",
])
reload_fn = grab("static void lp_reload_props_live(void) {")
scenes_tbl = grab_semi("static const char *g_lp_scenes[] = {")

# lp_reload_props_live is extracted verbatim WITHOUT its preceding comment
# block; the slot statics are re-declared here with the file's own types and
# initializers so the function body compiles unmodified.
harness = r"""
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/stat.h>   /* the extracted fn's R4b-2 regular-file guard */
__HELPERS__

/* ---- the seam slot statics, re-declared with the file's own types ---- */
#define LP_SCENE_MAX 32
static const char *g_lp_props_path = NULL;
static volatile int g_lp_fps_cap = 0;
static char g_lp_scene_new[LP_SCENE_MAX] = {0};
static volatile int g_lp_scene_reload = 0;
static int  g_lp_prop_fog = -1, g_lp_prop_snow = -1;
static int  g_lp_prop_dither = -1, g_lp_prop_wobble = -1;
static int  g_lp_prop_flashlight = -1;
static int  g_lp_prop_pair0 = -1, g_lp_prop_pair1 = -1;
__SCENES__
#define LP_SCENE_COUNT (int)(sizeof(g_lp_scenes)/sizeof(g_lp_scenes[0]))

static int fails = 0;
static int console_acks = 0;
/* the stub for the seam's IPC-out (the real one writes the wire JSON) */
static void lp_send_console(int error, const char *msg) {
    (void)error;
    if (strstr(msg, "defaults reloaded")) console_acks++;
    printf("[console] %s\n", msg);
}

#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); fails++; } } while (0)

/* the diverged live state the user built via the panel before clicking
 * "Restore default" — the revert must overwrite every one of these       */
static void diverge(void) {
    g_lp_prop_fog = 0; g_lp_prop_snow = 1; g_lp_prop_dither = 0;
    g_lp_prop_wobble = 1; g_lp_prop_flashlight = 0;
    g_lp_fps_cap = 15;
    g_lp_prop_pair0 = 2; g_lp_prop_pair1 = 2;      /* envpair item 2,2 */
    snprintf(g_lp_scene_new, LP_SCENE_MAX, "ER00FE");  /* the marker */
    g_lp_scene_reload = 0;
}

__RELOAD__

static void reload_from(const char *path) {
    g_lp_props_path = path;
    lp_reload_props_live();
}

int main(int argc, char **argv) {
    char buf[512];
    /* ---- 1. the pristine bundled schema (the panel's re-copy) -------- */
    diverge();
    reload_from(argv[1]);
    CHECK(g_lp_prop_fog == 1, "pristine: fog reverts to 1");
    CHECK(g_lp_prop_snow == 1, "pristine: snow reverts to 1");
    CHECK(g_lp_prop_dither == 1, "pristine: dither reverts to 1");
    CHECK(g_lp_prop_wobble == 1, "pristine: wobble reverts to 1");
    CHECK(g_lp_prop_flashlight == 1, "pristine: flashlight reverts to 1");
    CHECK(g_lp_fps_cap == 30, "pristine: fps reverts to 30");
    CHECK(g_lp_prop_pair0 == -2 && g_lp_prop_pair1 == -1,
          "pristine: envpair item 0 'camdat' stages the authored-env slot");
    CHECK(!strcmp(g_lp_scene_new, "THRF9FE"),
          "pristine: scene index 42 reverts to THRF9FE");
    CHECK(g_lp_scene_reload == 1, "pristine: the live scene reload is scheduled");
    CHECK(console_acks == 1, "pristine: the console ack fired");

    /* ---- 2. the diverged panel schema (what the user saved) ---------- */
    diverge();
    reload_from(argv[2]);
    CHECK(g_lp_prop_fog == 0 && g_lp_prop_snow == 0 &&
          g_lp_prop_dither == 0 && g_lp_prop_wobble == 0 &&
          g_lp_prop_flashlight == 0, "diverged: every checkbox re-read");
    CHECK(g_lp_fps_cap == 15, "diverged: fps 15 re-read");
    CHECK(g_lp_prop_pair0 == 7 && g_lp_prop_pair1 == 4,
          "diverged: envpair index 4 -> the 7,4 pair");
    CHECK(!strcmp(g_lp_scene_new, "SU0203"),
          "diverged: scene index 33 -> SU0203");
    CHECK(g_lp_scene_reload == 1, "diverged: reload scheduled");
    CHECK(console_acks == 2, "diverged: ack #2");

    /* ---- 3. flat hand-sender schema (flat first, like the boot) ------ */
    diverge();
    reload_from(argv[3]);
    CHECK(g_lp_prop_fog == 1 && g_lp_prop_snow == 0 &&
          g_lp_prop_dither == 1 && g_lp_prop_wobble == 0 &&
          g_lp_prop_flashlight == 1, "flat: checkbox family");
    CHECK(g_lp_fps_cap == 60, "flat: fps 60");
    CHECK(g_lp_prop_pair0 == 9 && g_lp_prop_pair1 == 9,
          "flat: envpair \"9,9\"");
    CHECK(!strcmp(g_lp_scene_new, "SU0203"), "flat: scene by name");
    CHECK(console_acks == 3, "flat: ack #3");

    /* ---- 4. envpair int index only (scene key absent) ---------------- */
    diverge();
    reload_from(argv[4]);
    CHECK(g_lp_prop_pair0 == 6 && g_lp_prop_pair1 == 3,
          "envpair nested int index 3 -> 6,3");
    CHECK(!strcmp(g_lp_scene_new, "ER00FE"),
          "no scene key: the marker survives (no reload staged)");
    CHECK(g_lp_scene_reload == 0, "no scene key: reload stays unset");
    CHECK(g_lp_prop_fog == 0, "no fog key: diverged value survives");
    CHECK(console_acks == 4, "envpair-only: ack #4");

    /* ---- 5. scene by NAME inside the nested schema ------------------- */
    diverge();
    reload_from(argv[5]);
    CHECK(!strcmp(g_lp_scene_new, "SUFE00"),
          "nested scene value as a STRING is accepted");
    CHECK(g_lp_scene_reload == 1, "string scene stages the reload");
    CHECK(console_acks == 5, "scene-by-name: ack #5");

    /* ---- 6. out-of-range values are IGNORED (slot keeps prior) ------- */
    diverge();
    reload_from(argv[6]);
    CHECK(g_lp_fps_cap == 15, "fps 300 out-of-range: diverged 15 survives");
    CHECK(g_lp_prop_pair0 == 2 && g_lp_prop_pair1 == 2,
          "envpair \"99,99\" out-of-range: diverged 2,2 survives");
    CHECK(!strcmp(g_lp_scene_new, "ER00FE"),
          "scene index 45 out-of-range (44 entries): marker survives");
    CHECK(g_lp_scene_reload == 0, "out-of-range scene: no reload staged");
    CHECK(console_acks == 6, "oob: ack #6 (file read fine)");

    /* ---- 7. readable MALFORMED json: the no-op revert ---------------- */
    diverge();
    reload_from(argv[7]);
    CHECK(!strcmp(g_lp_scene_new, "ER00FE") && g_lp_scene_reload == 0 &&
          g_lp_prop_fog == 0 && g_lp_fps_cap == 15 &&
          g_lp_prop_pair0 == 2 && g_lp_prop_pair1 == 2,
          "malformed json: every slot untouched (no-op revert)");
    CHECK(console_acks == 7,
          "malformed-but-readable: the shipped flow still acks (#7)");

    /* ---- 8. MISSING file: the silent no-op --------------------------- */
    diverge();
    snprintf(buf, sizeof(buf), "%s/definitely_missing.json", argv[8]);
    reload_from(buf);
    CHECK(!strcmp(g_lp_scene_new, "ER00FE") && g_lp_scene_reload == 0 &&
          g_lp_prop_fog == 0 && g_lp_fps_cap == 15,
          "missing file: every slot untouched (no-op revert)");
    CHECK(console_acks == 7, "missing file: NO ack (fopen bail is silent)");

    /* ---- 9. envpair flat "camdat" ------------------------------------ */
    diverge();
    reload_from(argv[9]);
    CHECK(g_lp_prop_pair0 == -2 && g_lp_prop_pair1 == -1,
          "flat envpair camdat stages the authored-env slot");
    CHECK(console_acks == 8, "flat camdat: ack #8");

    /* ---- 10. same-scene revert still stages the reload -------------- */
    diverge();
    snprintf(g_lp_scene_new, LP_SCENE_MAX, "THRF9FD");
    reload_from(argv[10]);
    CHECK(!strcmp(g_lp_scene_new, "THRF9FD"),
          "same-scene: staged name is THRF9FD (index 41)");
    CHECK(g_lp_scene_reload == 1,
          "same-scene: the reload still stages (unconditional, like Type-14)");
    CHECK(console_acks == 9, "same-scene: ack #9");

    printf(fails ? "TYPE16 LOGIC TEST: FAIL (%d)\n"
                 : "TYPE16 LOGIC TEST: PASS\n", fails);
    return fails ? 1 : 0;
}
""".replace("__HELPERS__", helpers).replace("__SCENES__", scenes_tbl) \
   .replace("__RELOAD__", reload_fn)

tmp = tempfile.mkdtemp(prefix="sh1_t16_")
cpath = os.path.join(tmp, "t16.c")
binpath = os.path.join(tmp, "t16" + (".exe" if os.name == "nt" else ""))
open(cpath, "w").write(harness)

# ---- the case files ------------------------------------------------------
def w(name, text):
    p = os.path.join(tmp, name)
    open(p, "w").write(text)
    return p

f_pristine = w("pristine.json", open(PROPS).read())
f_diverged = w("diverged.json", """{
  "scene": {"type":"dropdown","value":33},
  "envpair": {"type":"dropdown","value":4},
  "fog": {"type":"checkbox","value":false},
  "flashlight": {"type":"checkbox","value":false},
  "snow": {"type":"checkbox","value":false},
  "dither": {"type":"checkbox","value":false},
  "wobble": {"type":"checkbox","value":false},
  "fps": {"type":"slider","value":15}
}""")
f_flat = w("flat.json", """{"scene":"SU0203","envpair":"9,9","fog":true,"snow":false,"dither":true,"wobble":false,"flashlight":true,"fps":60}""")
f_envidx = w("envpair_idx.json", """{"envpair":{"type":"dropdown","value":3}}""")
f_scenestr = w("scene_by_name.json", """{"scene":{"type":"dropdown","value":"SUFE00"}}""")
f_oob = w("oob.json", """{"fps":300,"envpair":"99,99","scene":45}""")
f_bad = w("malformed.json", "{ this is not ] json at all ")
f_camdat = w("envpair_flat_camdat.json", """{"envpair":"camdat"}""")
f_same = w("same_scene.json", """{"scene":{"type":"dropdown","value":41}}""")

cc = shlex.split(os.environ.get("CC", "gcc"))
cmd = cc + ["-O1", "-std=c99", "-o", binpath, cpath]
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    print("FATAL: harness compile failed")
    print(r.stdout); print(r.stderr)
    sys.exit(1)

run = [binpath, f_pristine, f_diverged, f_flat, f_envidx,
       f_scenestr, f_oob, f_bad, tmp, f_camdat, f_same]
r = subprocess.run(run, capture_output=True, text=True)
print(r.stdout)
if r.stderr:
    print("STDERR:", r.stderr[:2000])
shutil.rmtree(tmp, ignore_errors=True)
ok = r.returncode == 0
print("TYPE16 LOGIC TEST:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
