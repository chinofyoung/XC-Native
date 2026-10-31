# In-game toggle keys: feasibility findings

## Test A: 30 / 60 live (key 3)

**Verdict: LIVE.** We switched both ways 3 times while the game ran, in the field. Each switch took effect at once: 30.0-30.1 fps against 46 fps, the M1's limit, the same as the 2026-10-23 runs. Walking speed stayed at 8.54-8.67 m/s at both rates, which is 8.66 m/s at 30 fps today. There was no crash, no FATAL line and no stall, and the game closed normally.

### Mechanism (2.0.0 main, read from `XCX_build/rewritten/v200/main.patched.bin` with capstone)

- `SetVsyncCount` (main+0x13a2fd8) stores **N in the int32 at main+0x1d943a0** (through the GOT at main+0x1d6ebf0). The previous N goes to main+0x1d943a4 (GOT main+0x1d6ec00).
- Readers of N, all reading it fresh on every call:
  - Through the GOT: GetFrameTime main+0x13a2520; the limiter main+0x13a9acc, which reads it again inside its spin at +0x13a9aec and +0x13a9b3c; a frame-time function main+0x13a9094; and the per-frame sync main+0x13a3174, which copies N into the previous-N slot when they differ (nothing branches on that).
  - Directly (adrp+add): only GetVsyncCount main+0x13a25a4.
- GetVsyncCount's 4 callers, checked for a step worked out from N at start-up and kept:
  - main+0x251e0 (call at +0x25204): builds the step 1/(60/N) and a 30/fps ratio into stack locals on every call. Not cached.
  - main+0x138a50 (call at +0x138a78): works out 1/(60/N) on every call and adds it to an accumulator at obj+0x208. Not cached.
  - main+0x927e10 (call at +0x927e30): works out 60/N, 1/(60/N) and the 30/fps ratio and stores them in obj+0x968f8.., but again on every call. Not cached beyond one call.
  - main+0x13cd164: only tests N != 0 (cbz). No step.
  None keeps a start-up value. (The CHANGELOG notes that main+0x138a40 / main+0x927e10 run at their nominal rate. That still holds at 60, but it follows N live.)
- **To switch:**
  - write N (1 = 60, 2 = 30) to main+0x1d943a0;
  - set `Fps60Page.vsync` (+4) and `Fps60Page.realtime` (+8);
  - set `fps60_on`, so `runtime_frame_step_update` measures;
  - when going to 60, put 1/30 s into `frame_bits`, so the first frames use the real step until the mean of 4 takes over.
- No need to call SetVsyncCount again. The patch has to be applied from the start (the patched start-up call still takes N from the page). **When it is safe to apply:** any time. Every reader reads N fresh, and the switches were sent from the input thread at any point in a frame with no visible effect. At worst, one frame mixes the two steps.
- 1.0.1: assumed to be +0xfd40 (main+0x1da40e0). Not checked.

### Measured

Device: MacBook Air M1 (MacBookAir10,1, 8-core GPU, 16 GB), macOS 26, game 2.0.0. Docked, default window, no MetalFX. `XCX_CAMLOG=1`; FPS and speed come from the camera log. Continue from a copy of the user's profile (Primordia, East Gate Plain, daytime). Each phase: 6 s standing, then W or S held 7 s; speed is horizontal, in 1 s windows after the first 1.5 s.

| Run / phase | FPS (standing / walking) | frame p50 | Walking m/s (1 s windows) |
|---|---|---|---|
| Today's code, no patch (`XCX_PATCHES` unset), 4 phases | 30.1, 30.1, 30.1, 29.6 / 30.1, 30.1, 30.1, 29.9 | 33.2 ms | 8.65-8.67 (one window 8.33, 8.60) |
| Patch, mode 0 start (`XCX_PATCHES=60fps XCX_FPS60=0`) | 30.0 / 30.1 | 33.2 ms | 8.66-8.67 |
| `fps 60` #1 | 46.4 / 45.9 | 21.4 ms | 8.62-8.67 |
| `fps 30` #1 | 30.1 / 30.1 | 33.2 ms | 8.65-8.67 |
| `fps 60` #2 | 46.3 / 47.8 | 21.4 ms | 8.54-8.64 |
| `fps 30` #2 | 30.1 / 30.1 | 33.2 ms | 8.63-8.66 |
| `fps 60` #3 | 46.3 / 46.3 | 21.5 ms | 8.62-8.66 |
| `fps 30` #3 | 30.1 / 30.1 | 33.2 ms | 8.66 |

- `peek main+1d943a0` after each switch read N = 2 at the start, then 1, 2, 1, 2, 1, 2, as written.
- The runtime's own 1800-frame line in the 60 phases: "mean 21.52 ms (46.5 fps), 0 held at 50 ms".
- Step 4: the mode-0 start equals today's build: 30.0-30.1 fps, p50 33.2 ms, 8.66 m/s in both.
- 60 is about 46 fps here, not 60: the M1 Air is GPU-bound, as measured on 2026-10-23. Walking speed is right regardless, because the measured frame step drives GetFrameTime.
- Screenshots (local): `docs/screenshots/fps-live-test-60.png` (after the second switch to 60, picture normal), `fps-live-test-end.png`, `fps-live-test-base-end.png`.

### Untested

- The item pickup effect and the timed B-button prompt after a live switch. Their veneers read the page's mode each frame, so they should follow, but this was not looked at.
- Battles, cutscenes and Skells while switching; switching during a load or in a menu.
- 1.0.1; iOS (code is patched at build time there, but the page and N would be written the same way).
- Thermal throttling over a long session.

### Prototype (throwaway, reverted; its binary was deleted)

```diff
diff --git a/games/xcx/runtime/game_patches.c b/games/xcx/runtime/game_patches.c
index 3035d46..1e8addd 100644
--- a/games/xcx/runtime/game_patches.c
+++ b/games/xcx/runtime/game_patches.c
@@ -254,6 +254,24 @@ void runtime_frame_step_pin(double ms) {
     if (fps60_page && fps60_on && us) frame_step_store((float)(us / 1e6));
     fprintf(stderr, "[xcx] frame step %s%s\n", us ? "pinned (diagnostics)" : "measured again", fps60_page && fps60_on ? "" : " -- but the 60 fps patch is off, nothing changes");
 }
+/* TEST A (throwaway): switch 30 / 60 while the game runs. SetVsyncCount (v200 main+0x13a2fd8) stores N in the int at
+   main+0x1d943a0 (GOT main+0x1d6ebf0; the previous N at main+0x1d943a4, GOT +0x1d6ec00). The limiter (main+0x13a9a50)
+   and GetFrameTime (main+0x13a250c) load it fresh on every call, so writing it is enough. */
+void runtime_fps60_switch(int on) {
+    if (!fps60_page) { fprintf(stderr, "[keys] fps switch: the 60 fps patch is not applied\n"); return; }
+#if defined(XCX_GAME_V200)
+    _Atomic int32_t *n = (_Atomic int32_t *)(void *)(runtime_module_base("main") + 0x1d943a0);
+#else
+    _Atomic int32_t *n = (_Atomic int32_t *)(void *)(runtime_module_base("main") + 0x1d943a0 + 0xfd40);   /* untested guess */
+#endif
+    int32_t was = atomic_load(n);
+    if (on) frame_step_store(1.0f / 30.0f);   /* the frames now still last 33 ms; the measured mean takes over in 4 frames */
+    fps60_on = on;
+    atomic_store(&fps60_page->vsync, on ? 1 : 2);
+    atomic_store(&fps60_page->realtime, on ? 1 : 0);
+    atomic_store(n, on ? 1 : 2);
+    fprintf(stderr, "[keys] fps %d: game vsync count %d -> %d, mode %d\n", on ? 60 : 30, was, on ? 1 : 2, on);
+}
 void runtime_frame_step_update(uint64_t now_ns) {
     static uint64_t last; static double samples[4], sum_all; static unsigned count, next, frames, clamped;
     if (!fps60_page || !fps60_on || !now_ns) return;
diff --git a/games/xcx/runtime/input.c b/games/xcx/runtime/input.c
index 94b5dee..d66fd04 100644
--- a/games/xcx/runtime/input.c
+++ b/games/xcx/runtime/input.c
@@ -236,6 +236,8 @@ static void *input_file(void *arg) {
         } else if (!strncmp(line, "framestep ", 10)) {   /* "framestep <ms>": pin the real-time frame step, 0 = back to real time */
             char *end; double ms = strtod(line + 10, &end); if (end == line + 10 || ms < 0 || ms > 100) runtime_fail("framestep takes milliseconds (0 = real time)");
             runtime_frame_step_pin(ms);
+        } else if (!strcmp(line, "fps 60\n") || !strcmp(line, "fps 30\n")) {   /* TEST A (throwaway) */
+            extern void runtime_fps60_switch(int on); runtime_fps60_switch(line[4] == '6');
         } else if (!strncmp(line, "memsnap ", 8) || !strncmp(line, "peek ", 5)) {   /* diagnostics, see mem_diag below */
             mem_diag(line);
         } else if (!strcmp(line, "threads\n")) {   /* every guest thread's wait state and guest return chain, now (a hang: what is each thread waiting for) */
```

## Test B: docked / handheld live (key 4)

**Verdict: none yet (blocked, not measured).** The test session was started, but the log showed `[input] user input (keyboard)` at the moment its window first took focus (log line 3233, before the title screen; it also cancelled the auto-load). By the rule, the scripted input stopped there and the window was left open on the title screen. It was still open, with no further input, 33 minutes later (the window gained and lost focus three more times, no keys). No mode switch was sent, so nothing below is measured in play. What follows is read from the code and the game, and is what the rerun needs.

### Mechanism (read from the runtime and 2.0.0 main, `XCX_build/rewritten/v200/main.patched.bin`)

- **The runtime has the message queue.** `runtime_oe_push_message()` (`runtime/applet_host.c:22`) fills a 32-entry queue; the game drains it with `nn::oe::TryPopNotificationMessage` (overridden in the same file). The window focus messages (15) already go this way, and the test log shows the game popping them (`[test-b] game popped applet message 15`, twice).
- **The game enables both notifications.** Log of the test start: `operation mode notification enabled 1`, `performance mode notification enabled 1` (`SetOperationModeChangedNotificationEnabled(true)`, `SetPerformanceModeChangedNotificationEnabled(true)`).
- **The game reads the mode once at start-up** (main+0x13acdc4, an oe object constructor): `GetOperationMode` at main+0x13acdf0 stores "docked" (mode != 0) at obj+0x1c, `GetPerformanceMode` at main+0x13ace00 stores 1 (normal) or 2 (boost) at obj+0x20. The log of the test showed exactly one call of each up to the title screen. Setters for the same fields: main+0x13aceec (+0x1c), main+0x13acefc (+0x20).
- **The game handles messages 30 and 31.** Its message loop (main+0x13d9a40) pops messages and switches on `msg - 4` through a byte table at main+0x1874f27. Decoded: 4 -> main+0x13d9ae0, 15 -> +0x13d9b44 (focus), 16 -> +0x13d9bb8, **30 (OperationModeChanged) -> main+0x13d9c28**: calls `GetOperationMode` again and calls every registered listener's virtual +0x10 with (mode == 1, docked); **31 (PerformanceModeChanged) -> main+0x13d9c78**: calls `GetPerformanceMode` again and calls each listener's virtual +0x18 with 2 (boost) or 1 (normal). Other values from 5 to 31 are ignored; 92 and 93 are handled separately. These are the only two other calls of the two imports in main.
- So the delivery path exists on both sides: change the value `GetOperationMode` / `GetPerformanceMode` return, then push 30 and 31. **Unknown until measured:** whether the renderer's listener changes the output (in handheld at start the game sets `[nvn] WindowCrop 0,0 1280x720` on its 1920x1080 swap chain; a live switch should show that line, and `0,0 1920x1080` or no crop going back) and the internal render size, at once or at the next load.
- **Controller.** The game supports ids `0 0x1 0x2 0x20` and styles 0x7 (log, `TOTK_INPUT_LOG=1`), so both player 1 (full-key, docked) and the handheld id 0x20 are allowed by the game. `pad_id()` / `pad_style()` (`runtime/input.c:47-48`) already follow `runtime_handheld_mode()` on every call; what is cached is `allowed`, worked out from the id list in `SetSupportedNpadIdType` and cleared by `DisconnectNpad` of the pad in use. The prototype keeps the id list and recomputes `allowed` on a switch, and clears held keys. Untested: whether XCX disconnects player 1 itself after a live switch to handheld (TotK does at start), and whether it re-reads styles.

### Measured

Nothing in play. Only the start-up facts above (one call of each mode getter, both notifications enabled, focus messages popped, controller ids and styles). Device: MacBook Air M1, macOS 26, game 2.0.0, docked start, test binary `xcx-native-v200-modetest` (deleted), copy of the user's profile.

### Untested

Everything the pass test asks for: the output and canvas size after a switch, FPS in each mode, input after each switch, 3 round trips, a loading screen. The rerun: apply the prototype below, build it as a separate binary, start docked, reach the field, send `mode handheld` / `mode docked` through `TOTK_INPUT_FILE`, and watch for `[test-b] game popped applet message 30/31`, the `GetOperationMode ... (call 2)` line, `[nvn] WindowCrop` and `出图裁切` lines, the camera log FPS and a W walk after each switch. If nothing changes at once, cross a load (e.g. fast travel or a menu that reloads) before judging.

### Prototype (throwaway, reverted; its binary was deleted; built and started, never switched)

Commands: `mode handheld` and `mode docked` in `TOTK_INPUT_FILE`. `TEST_B_FORCE_MSG=1` pushes the messages even if the game had not enabled them (not needed: it does).

```diff
diff --git a/games/xcx/runtime/applet_host.c b/games/xcx/runtime/applet_host.c
index eb08933..8d185b6 100644
--- a/games/xcx/runtime/applet_host.c
+++ b/games/xcx/runtime/applet_host.c
@@ -44,7 +44,9 @@ static unsigned char try_pop_launch_parameter(uint64_t *size,void *buffer,uint64
     (void)buffer;(void)capacity;if(size)*size=0;return 0;
 }
 static unsigned char try_pop(uint32_t *out) {
-    pthread_mutex_lock(&lock); int ok = head != tail; if (ok && out) *out = messages[head++ % 32]; pthread_mutex_unlock(&lock); return (unsigned char)ok;
+    pthread_mutex_lock(&lock); int ok = head != tail; uint32_t m = 0; if (ok) { m = messages[head++ % 32]; if (out) *out = m; } pthread_mutex_unlock(&lock);
+    if (ok) fprintf(stderr, "[test-b] game popped applet message %u\n", m);   /* TEST B (throwaway) */
+    return (unsigned char)ok;
 }
 int runtime_core_away(void); void runtime_core_back(int *away);
 static uint32_t pop(void) {
diff --git a/games/xcx/runtime/input.c b/games/xcx/runtime/input.c
index 94b5dee..df011c8 100644
--- a/games/xcx/runtime/input.c
+++ b/games/xcx/runtime/input.c
@@ -46,7 +46,10 @@ static void input_log(const char *what,uint32_t id){static int on=-1;static uint
  fprintf(stderr,"[totk-input] game reads %s for controller %#x (supported styles %#x, ids allowed %d)\n",what,id,styles,allowed);}
 static uint32_t pad_id(void){return runtime_handheld_mode()?0x20u:0u;}
 static uint32_t pad_style(void){return runtime_handheld_mode()?2u:1u;}
-static void supported_ids(const uint32_t *ids,uint64_t n){if(n>10||(!ids&&n))runtime_fail("invalid controller ids");
+static uint32_t supportedIds[10];static uint64_t supportedN;static bool idsSet;   /* TEST B (throwaway) */
+void runtime_input_mode_changed(void){runtime_input_clear();pthread_mutex_lock(&inputLock);bool was=allowed;if(idsSet){allowed=false;for(uint64_t i=0;i<supportedN;i++)if(supportedIds[i]==pad_id())allowed=true;}pthread_mutex_unlock(&inputLock);
+ fprintf(stderr,"[keys] pad now id %#x style %u, allowed %d -> %d (styles %#x)\n",pad_id(),pad_style(),was,allowed,styles);}
+static void supported_ids(const uint32_t *ids,uint64_t n){if(n>10||(!ids&&n))runtime_fail("invalid controller ids");pthread_mutex_lock(&inputLock);supportedN=n;idsSet=true;for(uint64_t i=0;i<n;i++)supportedIds[i]=ids[i];pthread_mutex_unlock(&inputLock);
  if(getenv("TOTK_INPUT_LOG")){char b[128];size_t o=0;for(uint64_t i=0;i<n&&o<100;i++)o+=(size_t)snprintf(b+o,sizeof b-o," %#x",ids[i]);b[o]=0;fprintf(stderr,"[totk-input] game supports controller ids:%s\n",b);}pthread_mutex_lock(&inputLock);allowed=false;for(uint64_t i=0;i<n;i++)if(ids[i]==pad_id())allowed=true;pthread_mutex_unlock(&inputLock);}
 static void supported_styles(uint32_t value){pthread_mutex_lock(&inputLock);styles=value;pthread_mutex_unlock(&inputLock);}
 static uint32_t style(const uint32_t *id){if(!id)runtime_fail("controller id pointer");input_log("style set",*id);pthread_mutex_lock(&inputLock);uint32_t v=enabled&&allowed&&*id==pad_id()?(styles&pad_style()):0;pthread_mutex_unlock(&inputLock);return v;}
@@ -233,6 +236,8 @@ static void *input_file(void *arg) {
             runtime_front_text_test(line[2] == 'e' && line[3] == 'n' ? "enter" : "esc", NULL);
         } else if (sscanf(line, "hletrace %u %n", &code, &used) == 1 && used && !line[used] && code <= 2) {
             runtime_hle_trace_set((int)code);   /* 1 count host calls, 2 also log the first call of each, 0 stop and print the counts */
+        } else if (!strcmp(line, "mode handheld\n") || !strcmp(line, "mode docked\n")) {   /* TEST B (throwaway) */
+            extern void runtime_handheld_switch(int h); runtime_handheld_switch(line[5] == 'h');
         } else if (!strncmp(line, "framestep ", 10)) {   /* "framestep <ms>": pin the real-time frame step, 0 = back to real time */
             char *end; double ms = strtod(line + 10, &end); if (end == line + 10 || ms < 0 || ms > 100) runtime_fail("framestep takes milliseconds (0 = real time)");
             runtime_frame_step_pin(ms);
diff --git a/games/xcx/runtime/services.c b/games/xcx/runtime/services.c
index 6459737..9341d08 100644
--- a/games/xcx/runtime/services.c
+++ b/games/xcx/runtime/services.c
@@ -272,18 +272,27 @@ static void cpu_boost(int mode) { if(mode<0||mode>2)runtime_fail("unknown CPU bo
 /* TOTK_OPERATION_MODE=handheld reports the Switch handheld mode (oe OperationMode 0, PerformanceMode Normal 0) instead of
    docked (1, Boost 1): the game then uses its own handheld settings (1280x720 output, lower internal resolution), which
    Nintendo made for half the docked GPU clock. Read once; any other value stops the start. */
-static int handheld_mode(void) {static int v=-1;if(v<0){const char *e=getenv("TOTK_OPERATION_MODE");int h;if(!e||!strcmp(e,"docked"))h=0;else if(!strcmp(e,"handheld"))h=1;else runtime_fail("TOTK_OPERATION_MODE must be docked or handheld");
- fprintf(stderr,"[totk] operation mode reported to the game: %s\n",h?"handheld (performance normal)":"docked (performance boost)");v=h;}return v;}
+static _Atomic int handheld_live=-1;   /* TEST B (throwaway): the mode is a variable, switched by "mode docked|handheld" */
+static int handheld_mode(void) {int v=atomic_load(&handheld_live);if(v<0){const char *e=getenv("TOTK_OPERATION_MODE");int h;if(!e||!strcmp(e,"docked"))h=0;else if(!strcmp(e,"handheld"))h=1;else runtime_fail("TOTK_OPERATION_MODE must be docked or handheld");
+ fprintf(stderr,"[totk] operation mode reported to the game: %s\n",h?"handheld (performance normal)":"docked (performance boost)");atomic_store(&handheld_live,h);v=h;}return v;}
 int runtime_handheld_mode(void){return handheld_mode();}   /* runtime/input.c: the pad is the handheld controller then */
-static int operation_mode(void) {return handheld_mode()?0:1;}
-static int performance_mode(void) {return handheld_mode()?0:1;}
+static _Atomic int om_trace=3,pm_trace=3;static _Atomic unsigned om_calls,pm_calls;
+static int operation_mode(void) {atomic_fetch_add(&om_calls,1);if(atomic_fetch_sub(&om_trace,1)>0)fprintf(stderr,"[test-b] GetOperationMode -> %d from main+%#llx (call %u)\n",handheld_mode()?0:1,(unsigned long long)((uintptr_t)__builtin_return_address(0)-(uintptr_t)runtime_module_base("main")),atomic_load(&om_calls));return handheld_mode()?0:1;}
+static int performance_mode(void) {atomic_fetch_add(&pm_calls,1);if(atomic_fetch_sub(&pm_trace,1)>0)fprintf(stderr,"[test-b] GetPerformanceMode -> %d from main+%#llx (call %u)\n",handheld_mode()?0:1,(unsigned long long)((uintptr_t)__builtin_return_address(0)-(uintptr_t)runtime_module_base("main")),atomic_load(&pm_calls));return handheld_mode()?0:1;}
 static int focus_policy;
 static void focus_mode(int mode) {if(mode<0||mode>3)runtime_fail("unknown focus handling mode");focus_policy=mode;runtime_startup_checkpoint((uintptr_t)__builtin_return_address(0));fprintf(stderr,"[totk] focus policy stored: %d (window lifecycle pending)\n",focus_policy);}
 static int focus_state(void) {return runtime_front_focus();}
 static unsigned resume_notification,operation_notification,performance_notification;
 static void resume_enabled(unsigned value) {resume_notification=value&255;}
-static void operation_enabled(unsigned value) {operation_notification=value&255;}
-static void performance_enabled(unsigned value) {performance_notification=value&255;}
+static void operation_enabled(unsigned value) {operation_notification=value&255;fprintf(stderr,"[test-b] operation mode notification enabled %u\n",value&255);}
+static void performance_enabled(unsigned value) {performance_notification=value&255;fprintf(stderr,"[test-b] performance mode notification enabled %u\n",value&255);}
+/* TEST B (throwaway): switch docked / handheld while the game runs: change the mode, move the pad, post the applet
+   messages a Switch sends on (un)docking: OperationModeChanged 30 (0x1e), PerformanceModeChanged 31 (0x1f). */
+void runtime_handheld_switch(int h){int was=handheld_mode();atomic_store(&handheld_live,h);
+ extern void runtime_input_mode_changed(void);runtime_input_mode_changed();
+ fprintf(stderr,"[keys] rendering %s (was %s): GetOperationMode calls so far %u, GetPerformanceMode %u; notifications enabled op %u perf %u\n",h?"handheld":"docked",was?"handheld":"docked",atomic_load(&om_calls),atomic_load(&pm_calls),operation_notification,performance_notification);
+ atomic_store(&om_trace,3);atomic_store(&pm_trace,3);
+ if(operation_notification||getenv("TEST_B_FORCE_MSG"))runtime_oe_push_message(30);if(performance_notification||getenv("TEST_B_FORCE_MSG"))runtime_oe_push_message(31);}
 static uint32_t performance_configuration[2];
 static void performance_config(int mode,int cfg) {if(mode<0||mode>1)runtime_fail("invalid performance mode");performance_configuration[mode]=(uint32_t)cfg;fprintf(stderr,"[totk] performance request mode=%d cfg=%x: native macOS scheduling\n",mode,(uint32_t)cfg);}
 /* The game's language: TOTK_LANG as given (a Switch language code), otherwise from a locale: TOTK_LOCALE, which the
```
