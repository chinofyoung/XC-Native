# In-game toggle keys (1 to 5)

Date: 2026-10-31 · Status: approved, built 2026-11-01

## Why

When the game slows down mid-play (a city, a big fight), the player wants to drop to a lighter setting with one key
instead of quitting to the launcher. The two settings that matter most are the frame rate (30 / 60) and Rendering
(docked / handheld), both for performance. Today both are chosen only in the launcher before the game starts.

## What the player gets (Mac app)

| Key | Does | Remembered for the next start |
|---|---|---|
| 1 | Overlay, cycles: full, smaller, FPS only, hidden, then full again | no (my call, see below) |
| 2 | Scaling: MetalFX or none | yes |
| 3 | Frame rate: 30 or 60 fps | yes |
| 4 | Rendering: docked or handheld | yes |
| 5 | Nothing for now (see below) | |

Each press of 2, 3 or 4 shows a short confirmation (e.g. "60 fps", "Handheld", "MetalFX on") for about 2 s, even
when the overlay is hidden. Held-key repeats do nothing (as key 2 does today).

### Key 1 overlay levels

- **Full:** FPS, shader and load lines, the current state of each toggle (scaling, fps, rendering) and
  the key list.
- **Smaller:** FPS line plus the toggle states, no key list, no shader / load lines (my guess at the middle step; the
  user may adjust).
- **FPS only:** the FPS line.
- **Hidden.**

Start level: full when the launcher's FPS overlay setting is on, hidden when it is off (as today).

### Key 5: frame interpolation hidden for now

MetalFX frame interpolation (today on key 2) is not fixed yet (a net loss on an M1, ghosting on moving characters), so
the user chose to hide it: no key cycles it and the overlay does not mention it. Key 5 does nothing. The interpolation
code and its developer environment switch (`TOTK_MFX`) stay as they are; it moves to key 5 once it is fixed.

### Key 2 scaling

"MetalFX" turns on both existing MetalFX steps together, the same pair the launcher's scaler setting sets today:
`mfx_upscale` (the game's 1600x900 to 1080p step) and `mfx_output` (the enlargement to the window or full screen).
"None" turns both off: the game's own upscale and a plain stretch. Both flags already switch at run time
(`dm_gfx_set_flag`, `third_party/d2r_gfx/gfx/nvn/nvn_mtl.m:2461,2465`). MetalFX upscaling has not been checked with this
game; the first test checks the picture.

### Remembering 2, 3, 4

A change by key 2, 3 or 4 is written to the launcher's own settings (NSUserDefaults of the app; the game is `execv`'d
by the launcher in the same process, `app/launcher.m`, so it has the same bundle and defaults domain):

- key 2: `metalfx`. It is a preset field, so the runtime also sets `preset` to the Custom index (`NPRESETS`);
  otherwise `applyPreset` overwrites `metalfx` at the next start (`app/launcher.m:189-196, 229-232`).
- key 3: `frame_rate` (30 or 60)
- key 4: `handheld` (bool)

Only app runs write settings. Terminal runs (`make boot`) and scripted checks do not (the launcher sets a marker
variable for the runtime, e.g. `XCX_REMEMBER_KEYS=1`). An environment override for one start (`XCX_FRAME_RATE`,
`TOTK_OPERATION_MODE`) still wins at start; a key press during that run is still remembered.

## Goals

- Keys 3 and 4 change frame rate and rendering live, with the game running correctly after the switch.
- Keys 1 and 2 as above; key 5 unbound.
- The launcher and the README / website show the new keys.

## Non-goals

- iPhone and iPad (no keyboard in normal play; on-screen buttons would be separate work). The runtime changes must not
  break the iOS build, which patches the 60 fps code at build time (`CODE_PATCHED_AT_BUILD`).
- Internal resolution beyond the game's own, interface mods, monitor and window size: not changeable mid-game.
- Full screen toggle on a key (not asked for).

## Anti-goals (a failure even if the key "works")

- After a switch the game runs too fast or too slow (walking speed, effects, the timed B-button prompt), a stretched or
  wrong-size picture, the controller stops responding, or a crash.
- A 30 fps start that behaves differently from today's 30 fps (the game's own timing must be unchanged at 30).
- A test or terminal run that changes the player's launcher settings.

## Feasibility: throwaway tests first

Keys 3 and 4 need a switch that does not exist yet. Each starts as a throwaway test (no plan, no polish, minimal code)
to learn whether the game survives the change. Only what passes is built properly.

Decided by the user (2026-10-31):
- **Key 3 fallback:** if a live frame-rate switch is not possible, key 3 still saves the choice and confirms
  "60 fps: applies next start" (or "30 fps: ..."). The 60 fps patch is then applied as today (only when 60 is chosen),
  not always.
- **Key 4:** a switch that takes effect only at the next loading screen or area change counts as working; the
  confirmation then says so, e.g. "Handheld (after next load)". If it does not take effect even then, key 4 is
  dropped and keys 1, 2 and 3 ship.
- **Judging:** the builder's own measurements are enough (FPS and walking speed from the log, screenshots, scripted
  sessions); no stop for the user to play. Never close a test window the user is playing in (the log's
  `[input] user input` line).

### Test A: 30 / 60 live (key 3)

What is known (`runtime/game_patches.c`, comment at line 44 and `apply_fps60`):
- The game calls `SetVsyncCount(2)` once at start-up; the patch turns that `mov w0, #2` into a call to a veneer that
  loads N from the host page (`Fps60Page.vsync`). N sets the frame limiter at the end of every frame and the frame time
  `GetFrameTime()` returns (period x N).
- `Fps60Page.realtime` (mode) is read every frame by the frame-time, prompt-timer and effect veneers.
- With `XCX_FPS60=0` the patch is applied but behaves as the original (N = 2, mode 0).

So the plan for the test: always apply the 60 fps patch on the Mac (mode from the setting), and at a key press change
the page's mode and also the vsync count the game stored at start-up. Unknown: where `SetVsyncCount` stores N (the
limiter at main+0x13a9a50 and `GetFrameTime` at main+0x13a250c read it); the test finds it, or calls the game's
`SetVsyncCount` again from a safe point. Pass: switching both ways several times in the field, the FPS settles at about
30 and about 60, walking speed and an item pickup effect look normal at both, no crash.

Risk to check: applying the patch always must leave 30 fps identical to today (compare FPS and walking speed with a
build without the patch).

### Test B: docked / handheld live (key 4)

What is known (`runtime/services.c:272-286`, `runtime/input.c:47-48`):
- `handheld_mode()` is read from `TOTK_OPERATION_MODE` once and cached; `GetOperationMode` / `GetPerformanceMode`
  answer from it.
- The game enables the operation-mode and performance-mode changed notifications (stored, never sent).
- The controller id and style the runtime reports depend on the mode (player 1 full-key docked, handheld id 0x20).

Plan for the test: make the mode a variable, and at a key press change it and post the applet messages a real Switch
sends on undocking (OperationModeChanged, PerformanceModeChanged), if the runtime has a message queue the game polls;
the test finds out. Pass: the game switches its resolution (handheld 1280x720 output with a lower internal size), the
picture fills the window correctly, the controller keeps working, FPS changes in the expected direction, switching
back restores docked, no crash, several times in a row.

## Constraints

- Mac only: `runtime/frontend.m` (key events), `runtime/input.c` (key handling, key 2 today), the HUD in
  `frontend.m` and `gfx/nvn/fps_overlay.c`, `runtime/game_patches.c`, `runtime/services.c`, `app/launcher.m`.
- Keys use Mac key codes for the US layout positions: 1 = 18, 2 = 19, 3 = 20, 4 = 21, 5 = 23.
- The repo's style: dense C / Objective-C, comments that explain the why, log lines for each state change
  (`[keys] ...`) so a run's log shows what the player switched.
- Project rule: every player-visible change gets a note in `/Users/chinoyoung/Code/xcnativesite/tool-updates/`, and the
  README "Controls" and "Known issues" sections are updated (keys 3 and 4 there today say "do nothing").
- No git commits without the user's say-so.

## Left to the builder

- Exact text and look of the confirmation and the overlay's toggle lines (match the existing HUD; Chinese strings via
  `TOTK_UI` alongside English, as today).
- How the runtime writes NSUserDefaults (CFPreferences from C is fine).
- Where in the frame a live switch is applied (between frames, on the game thread or present thread) so it is safe.

## Calls I made (the user did not decide these)

- Key 2 switches both MetalFX steps together, as the launcher does.
- Key 1's level is not remembered.
- The middle overlay level drops the shader / load lines and the key list.
- Short on-screen confirmation for keys 2 to 4.
- Only app runs write the launcher settings.
