"""runtime/toggle_keys.c (the Mac app's in-game keys 1 to 5): compiles the file with a small C program that stands in for
the graphics flags, the 60 fps switch, the operation mode, the HUD and the launcher's settings, and runs it.

Covers: key 1 cycles the overlay levels, key 2 switches both MetalFX steps together and never frame interpolation, key 3
switches 30 / 60 (live, or "applies next start" when the 60 fps patch is not in the run), key 4 switches docked /
handheld, key 5 does nothing, the confirmations and their 2 s, and that only app runs (XCX_REMEMBER_KEYS=1) write the
launcher's settings. Key 4 before the game listens for the mode only saves the choice. Skipped when no C compiler is available."""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.normpath(os.path.join(HERE, "..", "runtime"))
UI_INCLUDE = os.path.normpath(os.path.join(HERE, "..", "third_party", "d2r_gfx", "gfx", "nvn", "include"))
LAUNCHER = os.path.normpath(os.path.join(HERE, "..", "app", "launcher.m"))

C_TEST = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "toggle_keys.h"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)
#define S 1000000000ull

/* stand-ins */
static uint64_t now = 100 * S;
uint64_t runtime_now_ns(void) { return now; }
static char flags[16][32]; static int flag_v[16], nflags, interp_calls;
void dm_gfx_set_flag(const char *name, int v) {
    if (!strcmp(name, "mfx_interp")) interp_calls++;
    if (nflags < 16) { snprintf(flags[nflags], sizeof flags[nflags], "%s", name); flag_v[nflags++] = v; }
}
static int hints = -1; void fps_overlay_set_hints(int on) { hints = on; }
static int fps60, fps60_live = 1, fps60_sets; int runtime_fps60_get(void) { return fps60; }
int runtime_fps60_set(int on) { fps60_sets++; if (!fps60_live) return 0; fps60 = on; return 1; }
static int hh, hh_sets, hh_live = 1; int runtime_handheld_mode(void) { return hh; }
int runtime_handheld_set(int on) { hh_sets++; if (!hh_live) return 0; hh = on; return 1; }
static int pokes; void runtime_hud_poke(void) { pokes++; }
static char wrote[16][32]; static int wrote_v[16], wrote_b[16], nwrote;
void toggle_keys_write_setting(const char *domain, const char *key, int value, int boolean) {
    if (strcmp(domain, "org.example.test")) { printf("FAIL: domain %s\n", domain); fails++; }
    if (nwrote < 16) { snprintf(wrote[nwrote], sizeof wrote[nwrote], "%s", key); wrote_v[nwrote] = value; wrote_b[nwrote++] = boolean; }
}
static void reset(void) { nflags = nwrote = 0; }
static int called5; static void on5(void) { called5++; }
static const char *conf(void) { const char *c = toggle_confirmation(now); return c ? c : "(none)"; }

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "";
    if (!strcmp(mode, "levels")) {   /* key 1: 4 presses, full start */
        toggle_keys_init(); CHECK(toggle_overlay_level() == 0, "start level %d", toggle_overlay_level()); CHECK(hints == 1, "hints %d", hints);
        int want[4] = {1, 2, 3, 0};
        for (int i = 0; i < 4; i++) { toggle_keys_press(18); CHECK(toggle_overlay_level() == want[i], "press %d: level %d", i + 1, toggle_overlay_level());
                                      CHECK(hints == (want[i] != 3), "press %d: hints %d", i + 1, hints); }
        CHECK(nwrote == 0, "key 1 is not remembered (%d writes)", nwrote);
        CHECK(toggle_confirmation(now) == NULL, "key 1 has no confirmation");
    } else if (!strcmp(mode, "hidden-start")) {   /* TOTK_FPS_OVERLAY=0 */
        CHECK(toggle_overlay_level() == 3, "start level %d", toggle_overlay_level()); CHECK(hints == 0, "hints %d", hints);
        toggle_keys_press(18); CHECK(toggle_overlay_level() == 0, "after a press %d", toggle_overlay_level());
    } else if (!strcmp(mode, "scaling")) {   /* key 2, TOTK_MFX_UPSCALE unset: none at start */
        CHECK(toggle_scaling() == 0, "start scaling %d", toggle_scaling());
        reset(); toggle_keys_press(19);
        CHECK(nflags == 2 && !strcmp(flags[0], "mfx_upscale") && !strcmp(flags[1], "mfx_output") && flag_v[0] == 1 && flag_v[1] == 1,
              "first press: %d flags %s=%d %s=%d", nflags, flags[0], flag_v[0], flags[1], flag_v[1]);
        CHECK(toggle_scaling() == 1, "scaling %d", toggle_scaling());
        CHECK(!strcmp(conf(), "MetalFX on"), "confirmation %s", conf());
        now += 2100000000ull; CHECK(toggle_confirmation(now) == NULL, "confirmation after 2.1 s: %s", conf());
        reset(); toggle_keys_press(19);
        CHECK(nflags == 2 && flag_v[0] == 0 && flag_v[1] == 0, "second press: %s=%d %s=%d", flags[0], flag_v[0], flags[1], flag_v[1]);
        CHECK(!strcmp(conf(), "MetalFX off"), "confirmation %s", conf());
        CHECK(interp_calls == 0, "mfx_interp called %d times", interp_calls);
    } else if (!strcmp(mode, "remember")) {   /* XCX_REMEMBER_KEYS=1 */
        reset(); toggle_keys_press(19);
        CHECK(nwrote == 2 && !strcmp(wrote[0], "metalfx") && wrote_v[0] == 1 && wrote_b[0] && !strcmp(wrote[1], "preset") && wrote_v[1] == XCX_PRESET_CUSTOM && !wrote_b[1],
              "key 2 writes: %d (%s=%d, %s=%d)", nwrote, wrote[0], wrote_v[0], wrote[1], wrote_v[1]);
        reset(); toggle_keys_press(20); CHECK(nwrote == 1 && !strcmp(wrote[0], "frame_rate") && wrote_v[0] == 60 && !wrote_b[0], "key 3 writes %s=%d", wrote[0], wrote_v[0]);
        reset(); toggle_keys_press(20); CHECK(nwrote == 1 && !strcmp(wrote[0], "frame_rate") && wrote_v[0] == 30, "key 3 again writes %s=%d", wrote[0], wrote_v[0]);
        reset(); toggle_keys_press(21); CHECK(nwrote == 1 && !strcmp(wrote[0], "handheld") && wrote_v[0] == 1 && wrote_b[0], "key 4 writes %s=%d", wrote[0], wrote_v[0]);
        hh_live = 0; reset(); toggle_keys_press(21); CHECK(nwrote == 1 && !strcmp(wrote[0], "handheld") && wrote_v[0] == 0, "key 4 (next start) writes %s=%d", wrote[0], wrote_v[0]);
        reset(); toggle_keys_press(18); CHECK(nwrote == 0, "key 1 writes %d", nwrote);
    } else if (!strcmp(mode, "no-remember")) {   /* a terminal run: nothing written */
        toggle_keys_press(19); toggle_keys_press(20); toggle_keys_press(21);
        CHECK(nwrote == 0, "%d writes without XCX_REMEMBER_KEYS", nwrote);
    } else if (!strcmp(mode, "fps")) {   /* key 3, live */
        CHECK(toggle_frame_rate() == 30, "start %d", toggle_frame_rate());
        toggle_keys_press(20); CHECK(fps60 == 1 && toggle_frame_rate() == 60 && !toggle_frame_rate_pending(), "60: game %d, choice %d", fps60, toggle_frame_rate());
        CHECK(!strcmp(conf(), "60 fps"), "confirmation %s", conf());
        toggle_keys_press(20); CHECK(fps60 == 0 && toggle_frame_rate() == 30, "30: game %d, choice %d", fps60, toggle_frame_rate());
        CHECK(!strcmp(conf(), "30 fps"), "confirmation %s", conf());
        CHECK(fps60_sets == 2, "%d switches", fps60_sets);
    } else if (!strcmp(mode, "fps-next")) {   /* key 3 without the 60 fps patch in the run */
        fps60_live = 0; toggle_keys_press(20);
        CHECK(toggle_frame_rate() == 60 && toggle_frame_rate_pending(), "choice %d pending %d", toggle_frame_rate(), toggle_frame_rate_pending());
        CHECK(!strcmp(conf(), "60 fps: applies next start"), "confirmation %s", conf());
        toggle_keys_press(20); CHECK(!strcmp(conf(), "30 fps: applies next start"), "confirmation %s", conf());
    } else if (!strcmp(mode, "rendering")) {   /* key 4 */
        CHECK(toggle_handheld() == 0, "start %d", toggle_handheld());
        toggle_keys_press(21); CHECK(hh == 1 && toggle_handheld() == 1, "handheld: %d %d", hh, toggle_handheld());
        CHECK(!strcmp(conf(), "Handheld"), "confirmation %s", conf()); CHECK(!toggle_handheld_pending(), "pending");
        toggle_keys_press(21); CHECK(hh == 0 && toggle_handheld() == 0, "docked: %d %d", hh, toggle_handheld());
        CHECK(!strcmp(conf(), "Docked"), "confirmation %s", conf());
        CHECK(hh_sets == 2, "%d switches", hh_sets);
    } else if (!strcmp(mode, "rendering-next")) {   /* key 4 before the game enabled the mode notification */
        hh_live = 0; toggle_keys_press(21);
        CHECK(hh == 0 && toggle_handheld() == 1 && toggle_handheld_pending(), "game %d choice %d pending %d", hh, toggle_handheld(), toggle_handheld_pending());
        CHECK(!strcmp(conf(), "Handheld: applies next start"), "confirmation %s", conf());
        toggle_keys_press(21); CHECK(!strcmp(conf(), "Docked: applies next start"), "confirmation %s", conf());
    } else if (!strcmp(mode, "key5")) {   /* key 5 (23) and other keys do nothing */
        int level = toggle_overlay_level(); toggle_keys_press(23); toggle_keys_press(22); toggle_keys_press(38);
        CHECK(nflags == 0 && nwrote == 0 && fps60_sets == 0 && hh_sets == 0 && toggle_overlay_level() == level && toggle_confirmation(now) == NULL,
              "key 5: flags %d writes %d fps %d mode %d", nflags, nwrote, fps60_sets, hh_sets);
    } else if (!strcmp(mode, "register")) {   /* a registered handler replaces the key */
        toggle_keys_register(23, on5); toggle_keys_press(23); CHECK(called5 == 1, "handler called %d", called5);
    } else { printf("unknown mode\n"); return 2; }
    printf("%s: %d failures\n", mode, fails);
    return fails ? 1 : 0;
}
"""


@unittest.skipUnless(shutil.which("cc"), "no C compiler")
class ToggleKeysTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        src = os.path.join(cls.tmp, "t.c")
        with open(src, "w") as f:
            f.write(C_TEST)
        cls.exe = os.path.join(cls.tmp, "t")
        subprocess.run(["cc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-DTOGGLE_KEYS_TEST", "-I", RUNTIME, "-I", UI_INCLUDE,
                        src, os.path.join(RUNTIME, "toggle_keys.c"), "-framework", "CoreFoundation", "-o", cls.exe], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_mode(self, mode, **env):
        e = {k: v for k, v in os.environ.items() if k not in ("XCX_REMEMBER_KEYS", "TOTK_FPS_OVERLAY", "TOTK_MFX_UPSCALE")}
        e.update({"TOTK_UI_LANG": "en", "XCX_SETTINGS_DOMAIN": "org.example.test"}, **env)
        r = subprocess.run([self.exe, mode], capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def test_overlay_levels(self):
        self.run_mode("levels")

    def test_overlay_hidden_at_start(self):
        self.run_mode("hidden-start", TOTK_FPS_OVERLAY="0")

    def test_scaling_both_steps_and_confirmation(self):
        self.run_mode("scaling")

    def test_remember_in_app_runs(self):
        r = self.run_mode("remember", XCX_REMEMBER_KEYS="1")
        self.assertIn("[keys] saved metalfx = 1", r.stderr)

    def test_terminal_runs_write_nothing(self):
        self.run_mode("no-remember")

    def test_frame_rate_live(self):
        r = self.run_mode("fps")
        self.assertIn("[keys] frame rate -> 60 (live)", r.stderr)

    def test_frame_rate_next_start(self):
        r = self.run_mode("fps-next")
        self.assertIn("[keys] frame rate -> 60 (next start)", r.stderr)

    def test_rendering(self):
        r = self.run_mode("rendering")
        self.assertIn("[keys] rendering -> handheld (live)", r.stderr)

    def test_rendering_next_start_before_the_game_listens(self):
        r = self.run_mode("rendering-next")
        self.assertIn("[keys] rendering -> handheld (next start)", r.stderr)

    def test_key5_unbound(self):
        self.run_mode("key5")

    def test_register(self):
        self.run_mode("register")

    def test_launcher_preset_count_matches(self):
        """The Custom index the runtime saves is the launcher's NPRESETS (checked at compile time there)."""
        with open(LAUNCHER) as f:
            text = f.read()
        self.assertIn("_Static_assert(NPRESETS == XCX_PRESET_CUSTOM", text)
        self.assertIn('setenv("XCX_REMEMBER_KEYS", "1", 1)', text)


if __name__ == "__main__":
    unittest.main()
