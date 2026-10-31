# In-game toggle keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keys 1 to 4 in the Mac game window: overlay levels (1), MetalFX scaling (2), 30/60 fps (3), docked/handheld
(4); 2 to 4 remembered by the launcher; key 5 unbound (interpolation hidden).

**Architecture:** Key presses arrive in `runtime/input.c` (`runtime_input_key_synthetic`). A new small module
`runtime/toggle_keys.c` owns the toggle state, the confirmation text and the "remember" write to the launcher's
defaults. The HUD in `runtime/frontend.m` reads that state. Frame rate and operation mode get run-time setters in
`runtime/game_patches.c` and `runtime/services.c`, built only as far as the two feasibility tests (Tasks 1 and 2) allow.

**Tech Stack:** C and Objective-C (Mac runtime, launcher), Python `unittest` for static checks (`games/xcx/tests`).

**Spec:** `docs/superpowers/specs/2026-10-31-in-game-toggle-keys-design.md` (read it first; it holds the decisions)

## Global Constraints

- Mac only. The iOS build (`ios/`, `runtime/frontend_ios.m`, `CODE_PATCHED_AT_BUILD`) must still compile and behave as
  before.
- Mac key codes (US positions): 1 = 18, 2 = 19, 3 = 20, 4 = 21, 5 = 23. Held-key repeats do nothing.
- Launcher defaults keys: `metalfx` (bool), `frame_rate` (30 | 60), `handheld` (bool), `preset` (set to `NPRESETS`,
  the Custom index, whenever `metalfx` is written). Written only when the launcher set `XCX_REMEMBER_KEYS=1`.
- Every switch logs one line: `[keys] <what> -> <value> (<live | next start | after next load>)`.
- Overlay strings in English and Chinese via `TOTK_UI`, matching the existing HUD.
- Code style: match the surrounding dense C / Objective-C and its why-comments.
- **No git commands that change state** (no add, commit, branch, stash). Leave changes uncommitted; the user commits.
- Never close a game window the user is playing in (log line `[input] user input` in a test session).
- Game runs for measurement: work folder `/Users/chinoyoung/Code/xcnative/XCX_build`, `make -C games/xcx boot
  WORK=... ` or the scripted input file (`TOTK_INPUT_FILE`, commands in `runtime/input.c`); see README "Developer build"
  and the CHANGELOG entries on the 60 fps patch for how walking speed and FPS were measured before.

## Review Focus

1. Pressing 3 or 4 during a loading screen, a cutscene or the title screen: no crash; the switch applies or is deferred.
2. Pressing 3 / 4 rapidly many times: the final state matches the last press, no half-applied state.
3. 30 fps start after these changes is identical to today's (FPS ~30, walking speed ~8.8 m/s in the field).
4. A terminal or scripted run never writes the launcher defaults (`XCX_REMEMBER_KEYS` unset).
5. Remembered `metalfx` survives the next launcher start (preset shows Custom, MetalFX still on).

Each line is pinned by a check in the task that owns the code (Tasks 3, 4, 5).

---

### Task 1: Feasibility test A, 30 / 60 fps live (throwaway)

**Files:** scratch changes to `games/xcx/runtime/game_patches.c`, revert afterwards. Findings go in
`docs/superpowers/plans/2026-10-31-in-game-toggle-keys-findings.md` (create).

**Interfaces:**
- Produces: a findings section "Test A" stating LIVE or NEXT-START, and if LIVE the exact mechanism (the address
  where the game stores the vsync count N, or the safe way to call `SetVsyncCount` again) and measured numbers.

- [ ] **Step 1:** Find where `SetVsyncCount` (v200 main+0x13a2fd8) stores N, read by the limiter (main+0x13a9a50) and
  `GetFrameTime` (main+0x13a250c). Use the disassembly tools in the repo or `rea`/objdump on
  `XCX_build/rewritten/2.0.0`. Record the address or global.
- [ ] **Step 2:** Prototype: apply the 60 fps patch always (mode from `XCX_FPS60`), and on a scripted trigger write N
  (1 or 2) to that storage plus `Fps60Page.realtime`. Trigger via the input file or an environment-timed thread.
- [ ] **Step 3:** Measure in the field (scripted run): FPS before and after switching both ways at least 3 times; walking
  speed at both rates (method as in CHANGELOG line ~1184); no crash. Pass: ~30 and ~60 fps (or the machine's max),
  walking speed within 10% of 8.8 m/s at both.
- [ ] **Step 4:** Measure a 30 fps start with the patch applied in mode 0 against today's build: same FPS and speed.
- [ ] **Step 5:** Write "Test A" in the findings file (LIVE or NEXT-START, numbers, mechanism), then revert the scratch
  changes (`git diff games/xcx/runtime` shows nothing from this task).

### Task 2: Feasibility test B, docked / handheld live (throwaway)

**Files:** scratch changes to `games/xcx/runtime/services.c`, `games/xcx/runtime/input.c`; findings in the same file.

**Interfaces:**
- Produces: findings section "Test B": LIVE, AFTER-NEXT-LOAD or NOT-POSSIBLE, and the mechanism (how the applet
  message is delivered, how the controller id / style change is handled).

- [ ] **Step 1:** Find whether the runtime has an applet message queue the game polls (`nn::oe` / `nn::am`
  `ReceiveMessage`/`PopNotificationMessage` or equivalent in `runtime/`), and how the game reacts to messages
  OperationModeChanged (0x1e) and PerformanceModeChanged (0x1f).
- [ ] **Step 2:** Prototype: make `handheld_mode()` a variable; on a trigger flip it and post both messages (if the
  enabled flags are set). Handle the controller: the pad id/style follow the mode (`input.c:47-48`); check the game
  sees the new controller (`TOTK_INPUT_LOG=1`).
- [ ] **Step 3:** Measure: canvas / output size in the log and a screenshot before and after (handheld 1280x720 output),
  FPS change, controller input still moves the player (scripted key), switch back, 3 round trips, also across a
  loading screen if the switch is not immediate. Classify LIVE / AFTER-NEXT-LOAD / NOT-POSSIBLE.
- [ ] **Step 4:** Write "Test B" in the findings file, revert the scratch changes.

### Task 3: Toggle module, key 1 overlay levels, key 2 scaling, key 5 unbound, remembering

**Files:**
- Create: `games/xcx/runtime/toggle_keys.c`, `games/xcx/runtime/toggle_keys.h`
- Modify: `games/xcx/runtime/input.c:28-36` (key dispatch), `games/xcx/runtime/frontend.m:113-151` (HUD),
  `games/xcx/app/launcher.m:528-531` (set `XCX_REMEMBER_KEYS=1`), the Makefile / build list that compiles runtime
  sources (and the iOS build list only if it shares it; iOS must not get the key handling)
- Test: `games/xcx/tests/test_toggle_keys.py`

**Interfaces:**
- Produces (toggle_keys.h):
  - `void toggle_keys_press(unsigned code);` called from input.c for a fresh press of 18..23
  - `int toggle_overlay_level(void);` 0 full, 1 smaller, 2 FPS only, 3 hidden
  - `int toggle_scaling(void);` 1 MetalFX, 0 none
  - `const char *toggle_confirmation(uint64_t now_ns);` the current confirmation text or NULL after ~2 s
  - `void toggle_keys_remember(const char *key, int value);` writes the launcher default if `XCX_REMEMBER_KEYS=1`
    (CFPreferences, app domain), and for `metalfx` also `preset` = Custom index (2 today; take it from the launcher's
    `NPRESETS` via a shared define, not a literal)
  - `void toggle_keys_register(int code, void (*on_press)(void));` lets Tasks 4 and 5 add keys 3 and 4

- [ ] **Step 1: Write the failing test** `test_toggle_keys.py`: compiles `toggle_keys.c` with a tiny C harness (cc,
  stubbed `dm_gfx_set_flag` recording calls and a stubbed CFPreferences writer) and asserts:
  - key 18 pressed 4 times gives levels 1, 2, 3, 0
  - key 19 calls `dm_gfx_set_flag("mfx_upscale", v)` and `("mfx_output", v)` with the same v, toggling
  - key 19 with `XCX_REMEMBER_KEYS=1` writes `metalfx` and `preset`; without it writes nothing
  - key 23 (5) does nothing and calls no flag; `mfx_interp` is never called
  - confirmation "MetalFX on" / "MetalFX off" returned at t, NULL at t + 2.1 s
- [ ] **Step 2:** Run `python3 -m unittest games/xcx/tests/test_toggle_keys.py -v`; expect FAIL (missing file).
- [ ] **Step 3:** Implement `toggle_keys.c`; rewire `input.c` (18 and 19 to `toggle_keys_press`, remove the 19 ->
  `mfx_interp` binding, update the comment at lines 28-31); initial scaling from `TOTK_MFX_UPSCALE`; initial overlay
  level full if the overlay is on at start, hidden if `TOTK_FPS_OVERLAY=0`.
- [ ] **Step 4:** HUD in `frontend.m`: level 0 = FPS/shader/load lines + toggle states + key list
  (1 overlay, 2 scaling, 3 fps, 4 docked/handheld; no interpolation line); level 1 = FPS line + toggle states; level 2 =
  FPS line; level 3 = hidden but the confirmation still shows. Toggle states read from the toggle module (keys 3 and 4
  show their current values from Tasks 4 and 5 via a getter each; until then show the start values from the env).
- [ ] **Step 5:** Launcher: `setenv("XCX_REMEMBER_KEYS", "1", 1)` before `execv`.
- [ ] **Step 6:** Run the test (PASS), `make -C games/xcx runtime WORK=/Users/chinoyoung/Code/xcnative/XCX_build`
  and `make ... launcher` (both build), and the iOS build check the repo uses (`python3 -m unittest
  games/xcx/tests/test_ios_start_screen.py`).
- [ ] **Step 7:** Scripted run: press 1 four times and 2 twice via the input file, screenshot each overlay level into
  `docs/screenshots/`, check the `[keys]` log lines and that a terminal run wrote no defaults
  (`defaults read <app bundle id>` unchanged). Do not commit.

### Task 4: Key 3, frame rate

**Files:** `games/xcx/runtime/game_patches.c`, `games/xcx/runtime/toggle_keys.c`, `games/xcx/app/launcher.m:503-511`,
test `games/xcx/tests/test_toggle_keys.py`.

**Interfaces:**
- Consumes: Task 1 findings; `toggle_keys_register`, `toggle_keys_remember` (Task 3).
- Produces: `int runtime_fps60_get(void);` and, if LIVE, `void runtime_fps60_set(int on);` in game_patches.c.

- [ ] **Step 1: Failing test cases:** key 20 toggles 30 -> 60 -> 30; writes `frame_rate` 60 / 30 when remembering;
  confirmation is "60 fps" / "30 fps" if LIVE, "60 fps: applies next start" if NEXT-START (stub
  `runtime_fps60_set`).
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3 (LIVE):** Mac: apply the 60 fps patch at every start (launcher always adds `60fps`, sets `XCX_FPS60=0`
  for 30), implement `runtime_fps60_set` with Task 1's mechanism, applied at a safe point between frames; iOS
  unchanged. **(NEXT-START):** key 3 only remembers and confirms; the launcher keeps today's behaviour.
- [ ] **Step 4:** Run test (PASS); build runtime and launcher.
- [ ] **Step 5:** Scripted run checks Review Focus 1 to 3: press 3 on the title screen, during a loading screen and 6
  times quickly in the field; final FPS matches the last press; a 30 fps start measures as in Task 1 Step 4. Do not
  commit.

### Task 5: Key 4, docked / handheld (skip if Test B is NOT-POSSIBLE)

**Files:** `games/xcx/runtime/services.c:272-286`, `games/xcx/runtime/input.c:47-48`, `games/xcx/runtime/toggle_keys.c`,
test `games/xcx/tests/test_toggle_keys.py`.

**Interfaces:**
- Consumes: Task 2 findings; Task 3's register / remember.
- Produces: `void runtime_handheld_set(int on);` in services.c; `runtime_handheld_mode()` becomes the live value.

- [ ] **Step 1: Failing test cases:** key 21 toggles; writes `handheld`; confirmation "Handheld" / "Docked", with
  " (after next load)" appended when Test B was AFTER-NEXT-LOAD.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement with Task 2's mechanism (mode variable, messages posted only if the game enabled them,
  controller id/style switched safely under `inputLock`).
- [ ] **Step 4:** Run test (PASS); build.
- [ ] **Step 5:** Scripted run: 3 round trips, rapid presses, a press during loading; screenshots before/after in
  `docs/screenshots/`; player still moves after each switch. Do not commit.

### Task 6: Docs and the website note

**Files:** `README.md` (Controls "Extra keys", Known issues interpolation line), `games/xcx/CHANGELOG.md` (new entry
with Test A / B findings and measurements), `/Users/chinoyoung/Code/xcnativesite/tool-updates/2026-10-31-in-game-toggle-keys.md`
(create, format from `CLAUDE.md`, Status: uncommitted).

- [ ] **Step 1:** README: replace the key 1 / 2 / 3-4 bullets with the final keys (as built: live or next start, after
  next load), say interpolation has no key for now (developer switch `TOTK_MFX` only), plain style, no em dashes.
- [ ] **Step 2:** CHANGELOG entry with the measured numbers and the mechanisms.
- [ ] **Step 3:** Tool-update note: what changed for players, facts (keys, defaults keys, measured FPS, checked on this
  Mac), website impact (`src/content/*.ts` controls / known issues entries; current and suggested text), repo
  references.
- [ ] **Step 4:** Run the whole Python test suite `python3 -m unittest discover -s games/xcx/tests -v`; all pass. Do
  not commit.
