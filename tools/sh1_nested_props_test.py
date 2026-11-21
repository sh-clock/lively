#!/usr/bin/env python3
"""S19 nested-props restore test — feeds a LivelyProperties.json copy in the
EXACT panel schema (nested objects) to the LIVELY_PLAYER arg-parser path and
verifies the parsed values, by driving the shipped exe's own --wallpaper-*
consumers through the plain build (same parser source).

Since the lp_json_value_* helpers are static C inside fog_poc.c, this test
exercises them END-TO-END the way the app does:
  - writes the panel-schema props copy (scene 42 nested, fog false nested)
  - launches the plain engine with --input <bundle> + props via the same
    flat-scan semantics... (not possible directly — the props path is
    LIVELY_PLAYER-only).

So instead this test compiles a tiny C harness that #includes the ACTUAL
fog_poc.c helper functions (copy-paste of the three lp_json_value_* +
lp_json_str/int/bool definitions extracted verbatim from the shipped file)
and asserts the nested/flat behaviors against the real bundled
LivelyProperties.json bytes.

Exit non-zero on any mismatch.
"""
import json
import os
import shlex
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

# --- extract the helper functions verbatim from the shipped C source -----
src = open(FOG, encoding="utf-8").read()
def grab(sig):
    # sig = the full signature text as it appears in the source
    i = src.index(sig)
    # function body ends at the first line that starts with '}' at col 0
    j = src.index("\n}", i)
    return src[i:j + 2]

helpers = "\n".join(grab(f) for f in [
    "static int lp_json_int(const char *j, const char *key)",
    "static int lp_json_bool(const char *j, const char *key, int dflt)",
    "static int lp_json_str(const char *j, const char *key,\n                       char *out, size_t outn)",
    "static const char *lp_json_value_ptr(const char *j, const char *key)",
    "static int lp_json_value_int(const char *j, const char *key)",
    "static int lp_json_value_bool(const char *j, const char *key, int dflt)",
    "static int lp_json_value_str(const char *j, const char *key,\n                             char *out, size_t outn)",
])

harness = r"""
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
__HELPERS__
static int fails = 0;
#define CHECK(cond, msg) do { if (!(cond)) { printf("FAIL: %s\n", msg); fails++; } } while (0)
int main(int argc, char **argv) {
    /* argv[1] = the props json file (nested panel schema) */
    FILE *f = fopen(argv[1], "rb");
    if (!f) { printf("FAIL: open\n"); return 1; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *txt = malloc(n + 1);
    if (fread(txt, 1, n, f) != (size_t)n) { printf("FAIL: read\n"); return 1; }
    txt[n] = 0; fclose(f);

    char scene[32] = {0};
    int flat_str = lp_json_str(txt, "scene", scene, sizeof(scene));
    int flat_int = lp_json_int(txt, "scene");
    CHECK(flat_str == 0, "flat scene str should miss the nested object");
    CHECK(flat_int == -1, "flat scene int should miss the nested object");
    CHECK(scene[0] == 0, "flat scene buf untouched");

    int nest_int = lp_json_value_int(txt, "scene");
    CHECK(nest_int == 42, "nested scene value must be 42 (THRF9FE — index 42 of 44; THRF9FD is 41)");

    char nscene[32] = {0};
    int nest_str = lp_json_value_str(txt, "scene", nscene, sizeof(nscene));
    (void)nest_str;  /* the bundled schema stores an index, not a string */

    /* checkbox family — all true in the bundled defaults */
    CHECK(lp_json_value_bool(txt, "fog", -1) == 1, "nested fog == true");
    CHECK(lp_json_value_bool(txt, "snow", -1) == 1, "nested snow == true");
    CHECK(lp_json_value_bool(txt, "dither", -1) == 1, "nested dither == true");
    CHECK(lp_json_value_bool(txt, "wobble", -1) == 1, "nested wobble == true");
    CHECK(lp_json_value_bool(txt, "flashlight", -1) == 1, "nested flashlight == true");
    CHECK(lp_json_bool(txt, "fog", -1) == -1, "flat fog scan must miss (nested)");
    CHECK(lp_json_value_bool(txt, "nosuchkey", -1) == -1, "missing key -> dflt");
    CHECK(lp_json_value_int(txt, "nosuchkey") == -1, "missing key int -> -1");

    /* envpair nested: value 0 (the "camdat" item index) */
    char envp[32] = {0};
    int env_r = lp_json_value_str(txt, "envpair", envp, sizeof(envp));
    CHECK(env_r == 0 || envp[0] == 0, "envpair nested is an index (no string)");
    CHECK(lp_json_value_int(txt, "envpair") == 0, "nested envpair index 0");
    /* the app later sends the STRING "1,1" when the user picks an item;
     * simulate the saved string shape too */
    const char *saved = "{\"envpair\":{\"type\":\"dropdown\",\"value\":\"6,3\"}}";
    char e2[32] = {0};
    CHECK(lp_json_value_str(saved, "envpair", e2, sizeof(e2)) == 1 &&
          !strcmp(e2, "6,3"), "nested envpair string shape");
    /* flat sender shapes still work (the live IPC lines) */
    const char *flatline = "{\"Name\":\"scene\",\"Value\":33}";
    CHECK(lp_json_int(flatline, "Value") == 33, "flat int line");
    const char *flatbool = "{\"fog\":true}";
    CHECK(lp_json_bool(flatbool, "fog", -1) == 1, "flat bool");
    const char *flatstr = "{\"scene\":\"SU0203\"}";
    char s3[32] = {0};
    CHECK(lp_json_str(flatstr, "scene", s3, sizeof(s3)) == 1 &&
          !strcmp(s3, "SU0203"), "flat str");

    /* the string-skip path: braces inside string contents must not
     * break the depth scan (e.g. items with '{' chars) */
    const char *tricky = "{\"scene\":{\"type\":\"dropdown\",\"value\":7,"
        "\"items\":[\"a{b}\",\"c}d\"]},\"fog\":{\"type\":\"checkbox\",\"value\":false}}";
    CHECK(lp_json_value_int(tricky, "scene") == 7, "tricky braces in items: scene");
    CHECK(lp_json_value_bool(tricky, "fog", -1) == 0, "tricky braces: fog false");

    /* audit D5: envpair saved as INT item index (what the panel writes) */
    const char *idxenv = "{\"envpair\":{\"type\":\"dropdown\",\"value\":3}}";
    char e3[32] = {0};
    CHECK(lp_json_value_str(idxenv, "envpair", e3, sizeof(e3)) == 0,
          "envpair int-index is not a string");
    CHECK(lp_json_value_int(idxenv, "envpair") == 3,
          "envpair int-index reads 3 (maps to 6,3 at boot)");
    const char *idxenv0 = "{\"envpair\":{\"type\":\"dropdown\",\"value\":0}}";
    CHECK(lp_json_value_int(idxenv0, "envpair") == 0,
          "envpair index 0 = camdat (skip at boot)");

    printf(fails ? "NESTED PROPS TEST: FAIL (%d)\n" : "NESTED PROPS TEST: PASS\n", fails);
    return fails ? 1 : 0;
}
""".replace("__HELPERS__", helpers)

tmp = tempfile.mkdtemp(prefix="sh1_nested_")
cpath = os.path.join(tmp, "nest.c")
binpath = os.path.join(tmp, "nest" + (".exe" if os.name == "nt" else ""))
open(cpath, "w").write(harness)
cc = shlex.split(os.environ.get("CC", "gcc"))
r = subprocess.run(cc + ["-O2", "-o", binpath, cpath],
                   capture_output=True, text=True)
if r.returncode != 0:
    print("FATAL: harness compile failed:\n" + r.stderr[:2000]); sys.exit(1)

r = subprocess.run([binpath, PROPS], capture_output=True, text=True)
print(r.stdout, end="")
sys.exit(r.returncode)
