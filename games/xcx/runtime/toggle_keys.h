#pragma once
#include <stdint.h>

/* The in-game toggle keys of the Mac app (docs/superpowers/specs/2026-10-31-in-game-toggle-keys-design.md), on the
   number row's Mac key codes (US layout positions): 1 = 18 the overlay (full, smaller, FPS only, hidden), 2 = 19 the
   scaling (MetalFX or none), 3 = 20 the frame rate (30 / 60, live), 4 = 21 the rendering (docked / handheld), 5 = 23
   nothing for now (frame interpolation, hidden until it is fixed). Keys 2 to 4 show a short confirmation and are
   remembered for the next start in app runs. Not on iOS (no keyboard in normal play): toggle_keys.c is empty there. */

/* The launcher's preset count: its "Custom" entry has this index (app/launcher.m checks NPRESETS against it). Key 2
   saves preset = Custom too, or the launcher's preset would set MetalFX back at the next start. */
#define XCX_PRESET_CUSTOM 2

void toggle_keys_init(void);                      /* frontend.m, before the HUD: the start values from the environment */
void toggle_keys_press(unsigned code);            /* input.c: a fresh press (not a held-key repeat) of 18..23 */
void toggle_keys_register(int code, void (*on_press)(void));   /* replace what a key does (key 5 once interpolation works) */
int toggle_overlay_level(void);                   /* 0 full, 1 smaller, 2 FPS only, 3 hidden */
int toggle_scaling(void);                         /* 1 MetalFX, 0 none */
int toggle_frame_rate(void);                      /* 30 or 60: the choice (the live one unless it applies next start) */
int toggle_frame_rate_pending(void);              /* 1: the choice applies at the next start (no live switch possible) */
int toggle_handheld(void);                        /* 1 handheld, 0 docked: the choice */
int toggle_handheld_pending(void);                /* 1: the choice applies at the next start (the game could not be told yet) */
const char *toggle_confirmation(uint64_t now_ns); /* the confirmation of the last key 2 to 4 press, NULL after about 2 s */
void toggle_keys_remember(const char *key, int value);   /* the launcher's setting, only when XCX_REMEMBER_KEYS=1 */

/* What the keys switch, elsewhere in the runtime (a test harness supplies its own). */
void dm_gfx_set_flag(const char *name, int v);    /* third_party/d2r_gfx/gfx/nvn/nvn_mtl.m */
void fps_overlay_set_hints(int on);               /* third_party/d2r_gfx/gfx/nvn/fps_overlay.c: the HUD lines published or not */
int runtime_fps60_get(void);                      /* game_patches.c: 1 while the game runs at 60 */
int runtime_fps60_set(int on);                    /* game_patches.c: 1 switched live, 0 not possible in this run */
int runtime_handheld_mode(void);                  /* services.c */
int runtime_handheld_set(int on);                 /* services.c: 1 switched live, 0 not possible yet (nothing changed) */
void runtime_hud_poke(void);                      /* frontend.m: show a change in the HUD now */
uint64_t runtime_now_ns(void);
/* The launcher's settings (CFPreferences of its bundle identifier, XCX_SETTINGS_DOMAIN); boolean values as booleans. */
void toggle_keys_write_setting(const char *domain, const char *key, int value, int boolean);
