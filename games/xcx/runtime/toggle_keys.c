/* The in-game toggle keys (toggle_keys.h). Window keys arrive on the main thread, scripted ones (TOTK_INPUT_FILE) on
   the input file's thread, and the HUD reads on the main thread: the state is atomic, and a confirmation is a message
   number and a time, so the HUD never reads a string while a press writes it. Every switch logs one line
   "[keys] <what> -> <value> (<live | next start>)", so a run's log shows what the player
   switched. tests/test_toggle_keys.py builds this file with a small harness (TOGGLE_KEYS_TEST: the settings writer is the harness's). */
#include <TargetConditionals.h>
#if !TARGET_OS_IPHONE
#include "toggle_keys.h"
#include "totk_ui_lang.h"
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef TOGGLE_KEYS_TEST
#include <CoreFoundation/CoreFoundation.h>
#endif

enum { KEY_1 = 18, KEY_2 = 19, KEY_3 = 20, KEY_4 = 21, KEY_5 = 23, CONFIRM_NS = 2000000000ull };
enum { MSG_NONE, MSG_MFX_ON, MSG_MFX_OFF, MSG_FPS60, MSG_FPS30, MSG_FPS60_NEXT, MSG_FPS30_NEXT, MSG_HANDHELD, MSG_DOCKED,
       MSG_HANDHELD_NEXT, MSG_DOCKED_NEXT };
/* fps60 and the other switches are flipped with atomic_fetch_xor, the level with a compare-and-swap loop, so two
   presses at once (a window key and a scripted one) each count. */
static _Atomic int ready, level, scaling, fps60, fps_pending, handheld, handheld_pending;
static _Atomic int message; static _Atomic uint64_t message_at;
static void (*_Atomic handlers[128])(void);

static void confirm(int msg) { atomic_store(&message_at, runtime_now_ns()); atomic_store(&message, msg); runtime_hud_poke(); }
const char *toggle_confirmation(uint64_t now_ns) {
    int msg = atomic_load(&message); uint64_t at = atomic_load(&message_at);
    if (msg == MSG_NONE || now_ns - at >= CONFIRM_NS) return NULL;
    switch (msg) {
    case MSG_MFX_ON: return TOTK_UI("MetalFX 已开启", "MetalFX on");
    case MSG_MFX_OFF: return TOTK_UI("MetalFX 已关闭", "MetalFX off");
    case MSG_FPS60: return TOTK_UI("60 帧", "60 fps");
    case MSG_FPS30: return TOTK_UI("30 帧", "30 fps");
    case MSG_FPS60_NEXT: return TOTK_UI("60 帧：下次启动生效", "60 fps: applies next start");
    case MSG_FPS30_NEXT: return TOTK_UI("30 帧：下次启动生效", "30 fps: applies next start");
    case MSG_HANDHELD: return TOTK_UI("掌机模式", "Handheld");
    case MSG_DOCKED: return TOTK_UI("主机模式", "Docked");
    case MSG_HANDHELD_NEXT: return TOTK_UI("掌机模式：下次启动生效", "Handheld: applies next start");
    case MSG_DOCKED_NEXT: return TOTK_UI("主机模式：下次启动生效", "Docked: applies next start");
    }
    return NULL;
}

/* Only app runs write the launcher's settings: the launcher sets XCX_REMEMBER_KEYS=1 (and XCX_SETTINGS_DOMAIN, its
   bundle identifier: after its execv the process has no bundle of its own). Terminal runs and scripted checks never
   change the player's settings. */
#ifndef TOGGLE_KEYS_TEST
void toggle_keys_write_setting(const char *domain, const char *key, int value, int boolean) {
    CFStringRef d = CFStringCreateWithCString(NULL, domain, kCFStringEncodingUTF8), k = CFStringCreateWithCString(NULL, key, kCFStringEncodingUTF8);
    CFNumberRef n = boolean ? NULL : CFNumberCreate(NULL, kCFNumberIntType, &value);
    CFPreferencesSetAppValue(k, boolean ? (value ? kCFBooleanTrue : kCFBooleanFalse) : (CFPropertyListRef)n, d);
    Boolean ok = CFPreferencesAppSynchronize(d);
    if (n) CFRelease(n);
    CFRelease(k); CFRelease(d);
    if (!ok) fprintf(stderr, "[keys] could not save %s for the next start\n", key);
}
#endif
void toggle_keys_remember(const char *key, int value) {
    const char *r = getenv("XCX_REMEMBER_KEYS"); if (!r || strcmp(r, "1")) return;
    const char *d = getenv("XCX_SETTINGS_DOMAIN"); if (!d || !*d) d = "org.xcnative.xcx";
    int boolean = !strcmp(key, "metalfx") || !strcmp(key, "handheld");
    toggle_keys_write_setting(d, key, value, boolean);
    /* MetalFX is part of the launcher's presets: without "Custom" the preset would set it back at the next start. */
    if (!strcmp(key, "metalfx")) toggle_keys_write_setting(d, "preset", XCX_PRESET_CUSTOM, 0);
    fprintf(stderr, "[keys] saved %s = %d for the next start (%s)\n", key, value, d);
}

/* The start values: the launcher's choices reach the runtime as the environment, like every other setting. */
void toggle_keys_init(void) {
    if (atomic_exchange(&ready, 1)) return;
    const char *o = getenv("TOTK_FPS_OVERLAY"), *m = getenv("TOTK_MFX_UPSCALE");
    atomic_store(&level, o && !strcmp(o, "0") ? 3 : 0);
    atomic_store(&scaling, m && strcmp(m, "0") ? 1 : 0);
    atomic_store(&fps60, runtime_fps60_get() ? 1 : 0);
    atomic_store(&handheld, runtime_handheld_mode() ? 1 : 0);
    fps_overlay_set_hints(atomic_load(&level) != 3);
}
int toggle_overlay_level(void) { toggle_keys_init(); return atomic_load(&level); }
int toggle_scaling(void) { toggle_keys_init(); return atomic_load(&scaling); }
int toggle_frame_rate(void) { toggle_keys_init(); return atomic_load(&fps60) ? 60 : 30; }
int toggle_frame_rate_pending(void) { toggle_keys_init(); return atomic_load(&fps_pending); }
int toggle_handheld(void) { toggle_keys_init(); return atomic_load(&handheld); }
int toggle_handheld_pending(void) { toggle_keys_init(); return atomic_load(&handheld_pending); }

/* Key 1: full (lines, toggle states, key list), smaller (FPS line and toggle states), FPS only, hidden. Not remembered:
   the launcher's HUD setting decides the start (full or hidden). Hidden also stops the lines being published. */
static void key_overlay(void) {
    int was = atomic_load(&level), l;
    do l = (was + 1) % 4; while (!atomic_compare_exchange_weak(&level, &was, l));
    fps_overlay_set_hints(l != 3);
    static const char *names[] = {"full", "smaller", "FPS only", "hidden"};
    fprintf(stderr, "[keys] overlay -> %s (live)\n", names[l]);
    runtime_hud_poke();
}
/* Key 2: both MetalFX steps together, as the launcher's scaler: the game's picture to 1080p (mfx_upscale) and the
   enlargement to the window or screen (mfx_output); none = the game's own upscale and a plain stretch. Frame
   interpolation (mfx_interp) is not on any key until it is fixed (a net loss on an M1, ghosting). */
static void key_scaling(void) {
    int on = atomic_fetch_xor(&scaling, 1) ^ 1;
    dm_gfx_set_flag("mfx_upscale", on); dm_gfx_set_flag("mfx_output", on);
    fprintf(stderr, "[keys] scaling -> %s (live)\n", on ? "MetalFX" : "none");
    toggle_keys_remember("metalfx", on);
    confirm(on ? MSG_MFX_ON : MSG_MFX_OFF);
}
/* Key 3: the game's vsync count, live (game_patches.c, runtime_fps60_set). When the 60 fps patch is not in this run
   (a terminal run without XCX_PATCHES=60fps) the choice is only saved, for the next start. */
static void key_frame_rate(void) {
    int to = (atomic_fetch_xor(&fps60, 1) ^ 1) ? 60 : 30;
    int live = runtime_fps60_set(to == 60);
    atomic_store(&fps_pending, !live);
    fprintf(stderr, "[keys] frame rate -> %d (%s)\n", to, live ? "live" : "next start");
    toggle_keys_remember("frame_rate", to);
    confirm(live ? (to == 60 ? MSG_FPS60 : MSG_FPS30) : (to == 60 ? MSG_FPS60_NEXT : MSG_FPS30_NEXT));
}
/* Key 4: the operation mode the game is told, and the applet messages a Switch sends on (un)docking (services.c). The
   game changes its output at once (2026-11-01: WindowCrop 1280x720 / 1920x1080 on each press, checked by hand too).
   Before the game has enabled the mode notification (early start-up) nothing is switched: the choice is only saved. */
static void key_rendering(void) {
    int h = atomic_fetch_xor(&handheld, 1) ^ 1;
    int live = runtime_handheld_set(h);
    atomic_store(&handheld_pending, !live);
    fprintf(stderr, "[keys] rendering -> %s (%s)\n", h ? "handheld" : "docked", live ? "live" : "next start");
    toggle_keys_remember("handheld", h);
    confirm(live ? (h ? MSG_HANDHELD : MSG_DOCKED) : (h ? MSG_HANDHELD_NEXT : MSG_DOCKED_NEXT));
}

void toggle_keys_register(int code, void (*on_press)(void)) { if (code >= 0 && code < 128) atomic_store(&handlers[code], on_press); }
void toggle_keys_press(unsigned code) {
    toggle_keys_init();
    if (code >= 128) return;
    void (*h)(void) = atomic_load(&handlers[code]);
    if (h) { h(); return; }
    switch (code) {
    case KEY_1: key_overlay(); break;
    case KEY_2: key_scaling(); break;
    case KEY_3: key_frame_rate(); break;
    case KEY_4: key_rendering(); break;
    default: break;   /* key 5 (23): nothing for now */
    }
}
#endif   /* !TARGET_OS_IPHONE */
