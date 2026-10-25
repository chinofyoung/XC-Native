# Xenoblade Chronicles X: Definitive Edition port: work log

A record of how this port is being made, for anyone who continues it or tries the same with another game. Each entry
says what was found, what was done and why, what went wrong on the way, and how it was checked. Newest entries go at
the bottom of [Log](#log); [Status](#status) is kept current.

Conventions: dates are absolute; "verified" means a check with a recorded result, never "it looked right"; commits are
named by hash and subject. Game data, keys and saves are never committed (see `.gitignore` in this folder).

## Status

| Stage | Goal | State |
|---|---|---|
| 0 | Feasibility: does the game fit the TotK / Bayonetta 3 architecture? | done 2026-10-23 |
| 1 | Code and data out of the dump; code rewritten for Apple silicon | done 2026-10-23 |
| 2 | A runtime target with the Bayonetta-only parts compiled out, booting to `nnMain` | done 2026-10-23 |
| 3 | Follow every unknown service / command / NVN call until the first `nvnQueuePresentTexture` | done 2026-10-23 (title screen; menus answer input) |
| 4 | A picture, audio (Wwise), input, saves | in progress: controllable gameplay and battle with characters drawn; saves write; key 2 interpolates (too slow on an M1) |
| 5 | Performance, shaders, packaging as an app | in progress: update 2.0.0 supported next to 1.0.1 (built and played to the field, 2026-10-23); `build_app.py` turns the player's XCI into a self-contained app in one command (7.2 min clean, 1.7 s again), checked after a move out of the work folder; `--gui` does the same from a native window; `--platform ios` makes an experimental unsigned IPA (installed and played on an iPhone 15 Pro Max at 30 fps in the first area; draws whose shaders the IPA does not carry are skipped until `fill_shaders.py` sends them, first done 2026-10-24); `make app` builds a development app; clear sinking cuts GPU time per frame on an M1 from about 20 to about 17 ms (2026-10-23); an experimental 60 fps patch, off by default, lifts the game's own 30 fps cap on Mac and iPhone (2026-10-23) |

## Log

### 2026-10-23: stage 0, feasibility

Inputs: one XCI (`Xenoblade Chronicles X Definitive Edition.xci`, 15.97 GB) and `prod.keys` from the same Switch.
The full study, with every command, is `nsw/XCX_build/FEASIBILITY.md` (outside the repository, next to the game file);
its tools are in `nsw/XCX_build/tools/`. Nothing was booted. Verdict: go, with caveats.

Findings, each read from the dump:

- **The XCI holds base and update.** The secure partition has 8 NCAs, 1 common ticket, 1 cert: base
  `0100453019AA8000` v0 and update 1.0.1 `0100453019AA8800` v65536. Both Program NCAs carry the base title ID. No DLC,
  one program per title (Bayonetta 3's update had a second program). The XCI's update partition carries a system
  update, a source of shared fonts.
- **The base is complete**: ExeFS and RomFS stored, not sparse, not compressed. The update has a full ExeFS and a BKTR
  RomFS. Only `main` differs between the two ExeFS; `sdk`, `subsdk0`, `rtld` are byte-identical. **1.0.1 is the target.**
- **Same module layout as TotK and Bayonetta 3**: `main`, `sdk`, `subsdk0`, `rtld`, `main.npdm`. SDK 19.3.2 (nnSdk, NVN,
  movie). `main` (build ID `3F2425864CF226844511065F77AA3E36FB5FC33F`) links NPLN 1.32.1 with gRPC, OpenSSL, WebRTC
  and libcurl, Havok Physics 2023.2 and Wwise 2021.1.10. DT_RELR, which the loader already handles.
- **Graphics are NVN** only. Of 535 names main loads, 430 are implemented in Bayonetta 3's copy of the layer and 7
  are deliberate no-ops; 97 are missing (two-thirds getters or debug; the rest: integer clears, downsample / resolve,
  ReportValue, tessellation levels, viewport swizzles, sample shading, transform feedback, GL interop).
- **The npdm's 49 services and syscall mask equal TotK 1.4.3's.** Service-backed imports no host answers today:
  `nifm` (2), `friends` (11), `account` (OpenUser and others), the network clock, `ssl` Context, `nsd` ResolveEx,
  `ngc` profanity filter, `caps:su` screenshots, swkbd text check, `nn::err::NplnContext`. `main` uses `nn::os`
  fibers, which neither earlier game did.
- **Data**: 53 RomFS files: `sts.ard` (10.2 GB) + `sts.arh`, 5 Wwise `.pck`, 46 VP9 `.webm` movies.
- **The stock rewriter stops on `main`** with `KeyError: 24149652` (`0x1707e94`): capstone ends the per-function scan at
  the inline trap word `0xe7ffdefe`, and two `br x18` jump tables sit past such words. A copy of `patch_nso.py` that
  scans past undecodable words rewrote all three modules; `sdk` and `subsdk0` came out byte-identical to the stock
  tool's. Verified with that copy: `structck` OK for all three (0 violations; a moved branch fails), `equiv` 36,697
  sites, 0 divergent, 900 of 900 mutation controls caught.

### 2026-10-23: stage 1, code and data

**Layout.** `games/xcx` is a fork of `games/by3`: `runtime/`, `app/`, `third_party/` (`d2r`, `d2r_gfx`, `licenses`),
`prebuilt/`, `scripts/`, `Makefile`, `requirements.txt`, `.gitignore`, copied unchanged and then renamed where a name
is involved: the work folder default `XCX_build`, the binary `xcx-native`, the app `Xenoblade Chronicles X.app`
(`org.macnativegames.xcx`, Info.plist `XCXWorkFolder`, launcher env `XCX_WORK`, its own Application Support folder and
log names), the version folder `v101` in the Makefile and launcher. The runtime's logic is Bayonetta 3's, untouched
(only the work folder named in one error message); stage 2 retargets it. `.gitignore` ignores `XCX_build/`, `mods/` and
the game's data formats.

The work folder is `nsw/XCX_build` (next to the XCI, as `TOTK_build` is next to TotK's dump), passed as `WORK=`. It
now has the Bayonetta layout: `extracted/v101/{exefs,romfs,elf}`, `rewritten/v101`. Stage 0's stock rewrite moved
from `rewritten/` to `rewritten_stock/`; the other stage-0 folders stay where `FEASIBILITY.md` names them.

**Rewrite.** The stage-0 fix is now in `third_party/d2r/patch_nso.py`: `disasm_through_traps()` continues capstone
past an undecodable word, leaves the word in place (an undefined encoding that traps on both platforms) and counts it.
`main` skips 5 such words inside x18 functions (all `e7ffdefe`), `subsdk0` 1 (`33e425af`), `sdk` none.
`third_party/d2r/structck.py` writes its one-section aarch64 ELF in Python instead of calling `llvm-objcopy`, which
Xcode does not ship; `LLVM_BIN` points at Xcode's `llvm-objdump`. Both changes are listed in `third_party/d2r/README.md`.

| Module | Sites | Kinds | Undecodable words skipped | Time |
|---|---|---|---|---|
| sdk | 15,078 | 14,614 plain, 171 cond, 55 pcrel, 8 br, 4 windows, 2 + 3 tpidr read / write, 123 tpidrro, 40 cntpct, 58 svc; 98 gates | 0 | 17 s |
| subsdk0 | 9,787 | 9,634 plain, 131 cond, 17 pcrel, 5 br | 1 | 9 s |
| main | 11,930 | 11,083 plain, 167 cond, 100 pcrel, 5 br, 1 spset, 11 windows, 563 tpidr read | 5 | 52 s |

The two previously hidden jump tables (`0x1707e94`, `0x1707f20`, width 256) are in `main.sites.tsv`. The one `spset`
site (`mov sp, x18` at `main+0xaeda04`) is the case Bayonetta 3 added `site_spset` for, handled unchanged.

Verified:

- The `sdk` and `subsdk0` output (`patched.bin`, `fixups`, `gates`, `sites`, `cuts`, `obs`, `params`) is byte-identical
  to a fresh run of the stock `games/by3/third_party/d2r/patch_nso.py` and to stage 0's stock run. Only
  `build_src.sha256` differs, since it hashes the rewriter's own source.
- `main`'s output is byte-identical to stage 0's run with the tool copy: two rewrites give the same bytes.
- `structck.py` (fresh cache, so `llvm-objdump` really ran on the new ELF): OK for all three, 0 violations, 0 failed
  items. Independent `llvm-objdump` denominators: sdk 15,086, subsdk0 9,787, main 11,938.
- `structck.py` negative control: in a copy of `main.patched.bin`, the trampoline branch of the first site
  (`0x1104c`, `b` `0x151f3ca9` → `0x151f3caa`, target +4) gives `STRUCT main FAIL … 失败项=2` ("failed items: 2").
- `equiv.py`, seed 1, 8 jobs:

| Module | Sites | Trials (effective) | Divergent | Mutation controls | Time |
|---|---|---|---|---|---|
| sdk | 14,980 (+98 gates checked structurally) | 45,963 (40,725) | **0** | 300 / 300 caught | 14 s |
| subsdk0 | 9,787 | 29,861 (26,630) | **0** | 300 / 300 | 8 s |
| main | 11,930 | 36,970 (32,375) | **0** | 300 / 300 | 20 s |

  Total 36,697 sites, 0 divergent, 900 of 900 mutations caught; every site had at least 2 effective trials. The hidden
  jump tables had 2 of 2 effective trials each, the spset site 3 of 3.

**Data.** `scripts/merge_romfs.py` (adapted from Bayonetta 3's) finds both Program NCAs through the content metas:
every Meta NCA's PFS0 is read with its hash table and blocks verified, the Application meta names the base Program and
the Patch meta (required to be v65536) names the update Program. The base layer is plain AES-CTR (the script refuses a
sparse or compressed base); the update layers are unchanged from Bayonetta 3's: AES-CTR-Ex table, then the indirect
table over the base section and the update data. The update's IVFC header covers the merged image, so a wrong layer
fails a block hash. The image is streamed straight to `extracted/v101/romfs/romfs.bin`; no separate base or patch
image was ever written.

Verified:

- All six IVFC levels: 1 + 1 + 1 + 4 + 1,709 hash blocks and **874,727 of 874,727** data blocks. 53 files
  (`sts.ard` 10.22 GB, `sts.arh`, 5 `.pck` 3.16 GB, 46 `.webm` 0.95 GB), 14,331,516,488 bytes, SHA-256 `12c1bf46…`,
  re-hashed from disk. 14.28 GB come from the base, 79.8 MB from the update. Merge time 34 s.
- `scripts/romfs_control.py`: one encrypted byte flipped as it is read from the XCI, in the first update-data range of
  the data level (NCA offset `0x1a87a63`, merged `0xb3b6893`) fails with `IVFC level 5 block 9785 failed`, the
  predicted block; one in the first base range (`0x1ae8163`, merged `0x1ad0163`) fails at block 0, as predicted.
  `ROMFS CONTROL OK 2/2 caught`.
- `scripts/extract_code.py` takes the ExeFS of the Program the Patch meta 1.0.1 names
  (`4e7bdfd67782f0ffd791758053a1accb.nca`), with the FS header, hash table and every block verified. Its five files are
  byte-identical to stage 0's extraction (`xcx_inventory.py`, built on `games/totk/scripts/extract_exefs.py`).
  `--program base` gives the five base v0 files, identical to stage 0's too.
- `scripts/prepare_modules.py` wrote `extracted/v101/elf` (main, sdk, subsdk0, rtld; segment hashes verified).
- `assets/expected-v1.0.1.json` pins the ExeFS, the three rewrites and the RomFS (size, SHA-256, file count, bytes from
  base and update) with both Program NCAs.

Pitfalls, so nobody repeats them:

- The XCI has two Program NCAs with the same title ID, so "the Program of title X" is ambiguous. Choose through the
  content metas, never by order or size.
- `structck.py` caches the `llvm-objdump` lines by image hash (`DM_VCACHE`, default `~/dm-work/build/cache/dm/verify`).
  A cached run does not exercise the disassembler; the stage-1 run used a new cache folder.
- Run the repository's Python with `PYTHONDONTWRITEBYTECODE=1` when importing other games' scripts, or `__pycache__`
  lands in their folders.
- In this shell `sort` is an alias and `find` a shell function; use `/usr/bin/sort` and `/usr/bin/find`.

Logs: `nsw/XCX_build/logs/stage1/`. Commits: none; this checkout is not a git repository.

Open questions carried forward: whether SDK-19 NVN struct layouts match `nvn.h`; the shader binaries' GPU code version;
the heap and pool the game requests at boot; whether `nn::os` fibers work on the host's per-thread state; the audio
renderer revision Wwise 2021.1.10 requests.

### 2026-10-23: stage 2, the game reaches `nnMain`

**What changed in the fork** (the runtime was Bayonetta 3's, unchanged, after stage 1):

- `runtime/game_version.h`: XCX 1.0.1, main build ID `3F2425864CF226844511065F77AA3E36FB5FC33F`, version folder `v101`,
  title `0100453019AA8000` (save ownership in `fs_host.c`, `svcGetInfo` 18 in `services.c`). Still no game address
  on purpose: any leftover TotK or Bayonetta `GAME_ADDR` is a compile error, and none turned up.
- `scripts/prepare_runtime.py`: `v101` and `assets/expected-v1.0.1.json`. All three XCX modules have the same DT_INIT
  shape: the constructor-state load is `adrp x19` at +0x10, `ldr` at +0x14 (Bayonetta 3: x20, +0x10 / +0x18); the
  decoder added for Bayonetta 3 reads it without change. `scripts/prepare_patches.py` (exefs mods) takes `mods/1.0.1`
  and checks main 1.0.1's build ID; none are known for this game yet.
- Bayonetta names out: `BY3_PATCHES`, `BY3_DISPLAY`, `BY3_FULLSCREEN`, `BY3_AUDIO`, `BY3_HUD_RENDER` are now `XCX_*`
  (runtime, launcher, the graphics layer's HUD); window and menu titles; `runtime_by3_override` is
  `runtime_xcx_override`; `nn::oe::ExecuteProgram` stops with "Xenoblade Chronicles X has only one" program.
- Kept from Bayonetta 3 on purpose, each to be measured: `DM_POOL_BUFFER_MAX_MIB=2048`, `DM_PRESENT_HZ=60` with
  `TOTK_UNCAPPED=0`, `DM_PRESERVE_INVARIANCE=1`, `DM_NVN_GPU_CODE_MAX_MINOR=31`. The application pool stays the retail
  `0xcd500000` and the heap cap 4 GiB (see "memory" below).
- `scripts/symbolize.py` takes the work folder from `XCX_WORK` (the default `games/xcx/XCX_build` does not exist here).
- System fonts: a read-only copy of TotK's verified extraction (`nsw/TOTK_build/totk/extracted/firmware/shared-fonts`,
  the same six fonts any firmware carries) in `XCX_build/extracted/firmware/shared-fonts`; `make prepare` loads them.

Verified (`nsw/XCX_build/logs/stage2/`):

- `make prepare`: 3 modules, 206,670 relocations, main PLT probe at `0x1742240`, 53 RomFS files, fonts loaded; every
  input checked against `assets/expected-v1.0.1.json`. `make runtime` builds `xcx-native` with `-Werror`.
- `xcx-native rewritten/v101 probe`: pass. Three modules mapped (main 926 symbols, subsdk0 10,395, sdk 23,007), 4,000
  calls main PLT -> sdk -> host timer on 4 threads. The first XCX code to run on the Mac.
- `TOTK_HEADLESS=1 TOTK_VERIFY_STARTUP=1 xcx-native rewritten/v101 boot`: the original `nn::init::Start` ran the SDK
  startup, the RomFS (14,331,516,488 bytes) was verified, every constructor finished with state 2 (main 1,998, subsdk0
  45, sdk 87 init_array entries), and the original `nnMain` ran (`[totk] ENTER nnMain`) until its first IPC, `fsp-srv`.

**Memory.** `nninitStartup` reserves a 60 GiB address region and then maps 1 MiB pages into it until
`MapPhysicalMemory` fails (`0x10801` at `0xc7a01000` mapped, i.e. the whole pool minus the images): the game sizes its
own allocator to the pool and never sets a heap (`heap 0`). That is the expected end condition, not an error. It makes
3,200 `AllocateMemoryPages` lines in every boot log.

### 2026-10-23: stage 3, from `nnMain` to the title screen

Method as Bayonetta 3's: boot headless until the game needs a window, then with one; read where the host stops; answer
that one thing; repeat. Runs have a time limit (a `perl` alarm; macOS has no `timeout`). `scripts/symbolize.py` names
sdk frames; the game's own and the SDK's code are read with capstone from the original images.

Answered, in order of appearance:

| What stopped the host | Where | Answer |
|---|---|---|
| `sm: service "fsp-srv"` | `nn::fs::SetAllocator` -> `IsEnabledAccessLog` | `fsp-srv` over IPC (`fs_host.c`) with exactly the handshake: `SetCurrentProcess` (1) and `GetGlobalAccessLogMode` (1005) = 0. A first guess of 1006 was wrong; the host named 1005. Every file system still goes through the overridden functions |
| `fsp-srv` command 51 | `nn::fs::IsSaveDataExisting(Uid)` (one argument) | override by name: the game's own save data of the local account (`fs_host.c`) |
| `std::__throw_system_error` in `system_clock::now()` | sdk `clock_gettime(CLOCK_REALTIME)` | The SDK's startup points the C library's realtime clock at `nn::time::GetStandardUserSystemClockCurrentTimespec`, which asks the time service the host replaces. Both `...StandardUser...` and `...AdjustableUser...CurrentTimespec` are answered from the host clock (`time_host.c`, `TOTK_TIME_OFFSET` honoured). Found by following the function pointer at `sdk+0xb87018` and its one writer (`sdk+0x91154`) |
| null `IApplicationFunctions` in `nn::oe::EnterExitRequestHandlingSection` | | Enter/Leave as no-ops, ported from the TotK host's Breath of the Wild answer (the window handles exit) (`applet_host.c`); with them `ListAllUsers`, `GetLastOpenedUser`, `OpenUser(Uid)` for the one local account (`account.c`), which stage 0 listed |
| segfault in `GetTouchScreenStates<16>` | | override: one state, no touches, returns 1 (`input.c`) |
| `MapAliasStack` failed -> abort in `ThreadManager::CreateThread` | a thread whose 8 KiB stack is a static array in main's `.bss` (`main+0x278c000`) | `svcMapMemory` (the host's `stack_move`) accepts a module's read-write data as source, as Horizon does, besides heap and alias memory (`services.c`) |
| `stencil-plane texture sampling is not implemented` | `nvnTextureBuilderSetDepthStencilMode(STENCIL)` | kept in the texture description (one spare bit of `nvn_texdesc`); the replay's default view of such a texture is the same `X32_Stencil8` view Bayonetta 3's `nvnTextureViewSetDepthStencilMode` makes; the builder and texture getters return it (`hle_nvn.c`, `totk_nvn_ext.c`, `nvn_mtl.m`, `nvn_tex.h`) |
| `sm: service "bsd:s"`, then `"bsd:a"` | `nn::socket::detail::Initialize` | the SDK asks for `bsd:s` and `bsd:a` first and takes `bsd:u` when sm refuses. sm now refuses those two with `ResultNotAllowed` (`0x1015`), as for an application whose npdm does not grant them (`ipc.c`). The TIPC reply must keep its moved-handle slot (handle 0): the SDK's inlined `sm::GetServiceHandle` reads the result after it, and the first try without it read result 0 and a null handle (`0xe401` abort). `bsd:u` stays offline (ENETDOWN) |
| segfault in `nn::oe::GetPseudoDeviceId` | from the title screen, after the first A press | a per-profile random UUID kept in `user-data/pseudo-device.id` (`applet_host.c`) |
| `sm: service "prepo:u"` | `nn::prepo::AddSessionId`, the first menu choice | `prepo:u` over IPC with `GetSystemSessionId` (10400): one random value per start (`system_services.c`); the report itself is kept local by the existing `PlayReport::Save` override |

Shader tools: `build/shader-service/totk_xlate` from `prebuilt/` (SHA-256 checked by `make`), SPIRV-Cross built with the
Makefile's flags from a copy of `nsw/TOTK_build/src/SPIRV-Cross`, which is at the pinned commit `aa217ae` with a clean
tree (read with `git rev-parse` / `status` only; nothing was cloned or checked out).

**Result: the first frame is presented 0.33-0.64 s after start** (`[totk-boot] 0.637 first presented frame`, NVN window
2 images, 1920x1080, format 0x25); frame 6 is black (`docs/screenshots/xcx-stage3-first-frame.png`). A few seconds later
the title scene is drawn: dark clouds over the coast with the White Whale's silhouette and the loading indicator
(`docs/screenshots/xcx-stage3-title.png`, frame 126). About 2,000 draws a frame, 30 fps (present p50 33.3 ms), GPU
about 11 ms a frame on an M1.

Checked at the title (the user asked for the state, not for more):

- **Input: yes.** Keyboard J (A) and Return (+) through `TOTK_INPUT_FILE` lead through two menus: a centred dialog,
  then a menu panel over a blurred view of Mira's cliffs (`docs/screenshots/xcx-stage3-menu-after-input.png`). It ran
  110 s with eight key presses without a stop (`logs/stage3/i3.log`).
- **Audio: yes, as data.** Wwise opens `audren:u` and `audout:u`; AudioOut runs 48 kHz stereo PCM16 into Core Audio.
  `XCX_AUDIO_LEVEL=1` (new diagnostic in `audio_out.c`) logs the peak of each 5 s: 5,528 to 10,253 of 32,767 on the
  title, 17,466 in the window with the key press. Not listened to.
- **Fibers: the SDK's own.** `nn::os` fibers need no host code: `SwitchToFiber` / `DispatchFiberContext` save and load
  callee-saved registers and `sp` in plain arm64 (no `x18`, no SVC), the current fiber is a TLS value read through the
  rewritten `tpidrro_el0` sites (3 in `SwitchToFiber`), and fiber stacks are mapped with `svcMapMemory` through the
  same `StackGuardManager` path as thread stacks. Evidence that they run: the `GetPseudoDeviceId` crash's guest
  backtrace ended in `nn::os::detail::CallFiberFunction` (`sdk+0x143af8`), i.e. the game's code ran on a fiber.

Seen, not handled (stage 4):

- Text is missing everywhere (menus show their frames and highlight, no glyphs), and the log reports
  `【红】带索引的四边形未实现` ("indexed quads not implemented") twice: the likeliest cause.
- The lower half of the title and menu backgrounds is black, and the title's ground is flat-shaded.
- The GPU code version gate (`DM_NVN_GPU_CODE_MAX_MINOR=31`) was not measured for this game.

Pitfalls:

- `TOTK_GPU_ALLOW_SUBMIT=1` is needed for any picture, as for Bayonetta 3.
- A `TOTK_INPUT_FILE` command with a trailing space (`close `) is refused and stops the runtime.
- Two `shot` commands queued while the game is loading are both served by the next presented frame (same frame number).

Logs: `nsw/XCX_build/logs/stage3/`. Captures: `nsw/XCX_build/shots/`. Commits: none; this checkout is not a git repository.


### 2026-10-23: stage 4, indexed quads

Stage 3 left the menus without text and named the likeliest cause: `【红】带索引的四边形未实现` ("indexed quads not
implemented"), i.e. the graphics layer dropped every indexed draw with primitive 7 (quads). Non-indexed quads were
already drawn through a shared 0,1,2,0,2,3 index buffer; the indexed path had no answer.

**Answer** (`third_party/d2r_gfx/gfx/nvn/nvn_mtl.m`, the indexed branch of the draw encoder, line 10108): Metal has no
quads, so each group of 4 indices (a,b,c,d) becomes the triangles a,b,c / a,c,d, written as a 32-bit index list into
the submit's arena (at most 4 MiB a draw, else a red line). All three NVN index sizes are read; the all-ones index of
the source size restarts (a partial quad is dropped), as on the other index paths; base vertex and instancing pass
through unchanged. An index buffer still being written by pending GPU work is not converted (red line). One log line
per vertex shader names the draws that take the path. `DM_EXP_NO_INDEXED_QUADS=1` restores the old drop, for
measurement only.

Verified (`nsw/XCX_build/logs/stage4/`, input files and captures in `nsw/XCX_build/shots/stage4/`, driven by
`nsw/XCX_build/tools/run4.sh` with the same schedule: J at 22 s, Return at 32 s, J at 44 s, captures at 20/30/42/55 s):

- `q2` (fix on): the path is taken by at least 32 vertex shaders (the log stops naming them at 32), first in frame 10;
  every logged draw is one quad, 4 indices (27 of them 16-bit, 5 8-bit) -> 6 triangle indices. No `【红】` line in the
  log. Text renders in the menus; the title's black lower half and flat-shaded ground are gone. At 42 s the run is in
  character creation ("Modify Avatar / Gender Selection") over a lit 3D field; at 55 s on its "Eyes" page.
- `q3off` (`DM_EXP_NO_INDEXED_QUADS=1`, same input): the stage-3 picture: at 42 s a centred dialog with its frame and
  highlight and no text.
- Captures: `docs/screenshots/xcx-stage4-quads-title-before.png` / `-after.png` (20 s, `q3off_a20` / `q2_a20`),
  `docs/screenshots/xcx-stage4-quads-menu-before.png` / `-after.png` (42 s, `q3off_c42` / `q2_c42`).

The missing text, the black lower half and the flat ground had the one cause; which draws behind the lower half are
quads was not traced.

### 2026-10-23: stage 4, character creation to the first battle

Priority set by the user for this part: a correct picture first; audio is left for later, saves only noted. Runs were
driven live: `nsw/XCX_build/tools/live4.sh NAME LIMIT` starts the game with an empty input file that commands are appended
to while it runs (each capture looked at before the next input). The user also played in several of these windows with
a DualSense; the logs say so (`[input] user input (controller)`), and the name entry and the first steps in Primordia were
theirs.

| What stopped the host or broke the picture | Where | Answer |
|---|---|---|
| `sm: service "ngc:u" not implemented` (`logs/stage4/r2.log`) | `nn::ngc::ProfanityFilter::Initialize(void*, unsigned long, bool)` -> `nn::ngc::detail::CreateServiceByHipc`, at the name entry that follows character creation | `runtime/system_services.c` (`ngc_mask`, override table): main imports five `ProfanityFilter` names; `Initialize` and `SetMaskMode` return success, `MaskProfanityWordsInText(int*, char*, uint32)` sets the count to 0 and leaves the text as typed (offline there is no word list). The SDK's constructor and destructor still run. Verified: `logs/stage4/r3.log`, the name "Chino" is accepted and the game goes on to Primordia and auto-saves |
| Every character missing (avatar in character creation, player and Elma in the field; only the blob shadow drawn) | The skinning pass: draws under `nvnCommandBufferSetRasterizerDiscard(true)` (7,550 calls in 1.9 s of play, `hletrace`) whose vertex shader writes the bone-matrix storage buffer (`e2573156`, a `vertex_id` shader; also `326267ec`, `8ece1e30`). The graphics layer skipped every discard draw (TotK's never had an effect), so the 192,000-byte buffer the skinned vertex shaders read (`b2001614` reads matrix `weight index * 48` from it) stayed `f3f3f3f3` and zeros and every skinned vertex went to one point | `third_party/d2r_gfx/gfx/nvn/nvn_mtl.m`: a discard draw whose vertex shader writes a storage buffer (`prog_vs_stores`) is drawn with a pipeline without rasterization (`PSO_RDISCARD`, `nvn_pso_skey.h`; `pso_desc` sets `rasterizationEnabled = NO`, no fragment function, and `vs_fn_void` builds the void-returning variant Metal requires); after each one `draw()` puts a vertex -> vertex/fragment barrier in the encoder (`enc_r_barrier`, new `RS_BARRIER` in `nvn_render_stream.h`). Other discard draws are still skipped |

How the skinning cause was found, in order (so the method can be reused):

- The G-buffer (`texdump` of a gameplay frame, `shots/stage4/td2/t37200.png`, albedo) has the world and no character:
  the characters were not drawn at all, not lost in lighting.
- `passdump 1` (`logs/stage4/r3.log`): a 3,090-vertex depth pre-pass draw with position + `RG16UI` weight index (a
  character mesh) reads storage buffer `0x715dfc13d0` (192,000 bytes) whose CPU view has 4 non-zero words of 48,000.
- `DM_NVN_WATCH_SB=b2001614:0` (`logs/stage4/w1.log`): no CPU write to that buffer in a minute of play, so the GPU must
  fill it; the shader cache's reflection has three vertex shaders with a writable storage buffer, and `hletrace` shows
  the game toggling `SetRasterizerDiscard`; `draw_inner` returned early for every such draw.
- The first attempt (rasterization off, shader unchanged) failed in Metal: "RasterizationEnabled is false but the vertex
  shader's return type is not void" (`logs/stage4/s1.log`); hence `vs_fn_void`.

Verified (`logs/stage4/s2.log`): `rasterizer discard: drawing vertex shader e2573156d116223e (it writes storage
buffers), frame 137`, no `【红】` line, no stop. Continue from the auto-save: the player character and Elma are drawn
and lit, and the first battle (Origin Blatta) shows both characters, the enemy, damage numbers and effects. The GPU time
of the long frames the log reports (`[长帧]`) has a median of 21.6 ms before (`w1`, 85 frames) and 24.5 ms after (`s2`, 211
frames, including the battle); not a like-for-like measurement.

Captures (`docs/screenshots/`): `xcx-stage4-avatar-gameplay-before.png` (`w1_a`, old build) /
`xcx-stage4-avatar-gameplay-after.png` (`s2_a`), same spot after Continue; `xcx-stage4-avatar-creation-before.png`
(`r2_a`, character creation without the avatar); `xcx-stage4-battle.png` (`s2_c`).

Red lines and stub hits: none in any stage-4 run after the quads fix (`r1`, `r2`, `r3`, `w1`, `s2`: 0 `【红】` lines;
the one line containing 红 is the start-up count of the 99 unimplemented NVN names). An unimplemented NVN function stops
the host on its first call, and none did: no stub was hit up to the first battle. The one stop was `ngc:u` above.

Saves: **they write.** The first auto-save after the name entry made `user-data/save/<uid>/sts/game/{gamedataa,
gamedataa.tmb, avatarmakedata}` (880 KiB), and Continue on the next start loads it into Primordia.

Visual defects seen, not yet fixed or not yet checked:

- The opening cutscene's White Whale is a black silhouette with a rim light against the stars
  (`shots/stage4/r1_b_title.png`, `r3_c.png`). Not rechecked since the skinning fix; it may be correct (its dark side) or
  the same cause.
- Character creation was not recaptured after the fix (no after-picture of the avatar yet); a New Game run is needed.
- Not looked at yet: day-time lighting, water, cities (New Los Angeles), Skells, menus beyond character creation.

Pitfalls:

- The live window takes keyboard and controller input from the user; key 2 toggles MetalFX frame interpolation
  (`r1.log`: `mfx_interp = 1`), so a capture can be of a different mode than intended. Check the log for `[input]` lines.
- `texdump` dumps the frame after the command; on a 2D screen (the "LOGIN ID" movie) the G-buffer targets are rightly
  black. Take it in a 3D scene.
- `DM_NVN_GPU_CODE_MAX_MINOR` was not measured for this game.

Logs: `nsw/XCX_build/logs/stage4/`. Captures: `nsw/XCX_build/shots/stage4/`. Commits: none; this checkout is not a git
repository.

### 2026-10-23: stage 4, MetalFX frame interpolation (key 2)

Key 2 ("30+30") made no frame: the statistics line counted every game frame as missing all four inputs
(`[mfx] 至帧 …：插值帧 0 / 游戏帧 M …（画面 M 相机 M 深度 M UI M）`, `logs/stage4/s2.log`). The interpolator
(`third_party/d2r_gfx/gfx/nvn/totk_mfx.m`) is game-independent; what feeds it (`nvn_mtl.m`) recognised TOTK's passes,
shaders and camera block, and none of them match Xenoblade Chronicles X. The XCX inputs are now chosen at build time:
the Makefile compiles the graphics layer with `-DGAME_XCX`, and `nvn_obj.h` (line 201) sets the XCX variants of the
macros the hook-up already used (`MFX_UI_DRAW`, `MFX_CAM_SLOT` / `MFX_CAM_SIZE`) plus two new ones
(`MFX_IS_CANVAS`, `MFX_DEPTH_FMT_OK`). Without the define, the TOTK expressions are as before; both builds compile.

What each input is in XCX, found from the pass dump of a gameplay frame (`logs/stage4/r3.log`, frame 5541) and the shader
cache:

| Input | XCX | How it was found |
|---|---|---|
| Depth | The G-buffer depth, texture 378, 1920x1080 **D32F with stencil** (Metal format 260), depth test LESS (not reversed) | Pass 467423, 7 colour targets + depth: the existing rule ("three or more colour targets and a depth of their size") finds it once the format is allowed. MetalFX takes depth only, so `totk_mfx.m` copies the depth plane into a D32F texture of its own each interpolated frame (texture -> buffer with `MTLBlitOptionDepthFromDepthStencil`, buffer -> texture, in the interpolation's own command buffer) |
| Camera | The 768-byte scene block at **vertex uniform 0** of the G-buffer pass (the `c3` buffer of the vertex shaders), all row-major: view 3x4 at float 0, projection at 12, view-projection at 28, inverse view 3x4 at 44 (camera position at 47 / 51 / 55) | `075ba413` (a G-buffer vertex shader) multiplies the position by `c3[7..10]`; `TOTK_MFX_CAMDUMP` (new diagnostic) logged the whole block for 1,264 frames (`m1.log`). The projection is OpenGL's (clip z -1..1, which the translator maps to Metal's 0..1, as for TOTK), not reversed, finite far (near 0.5 / far 40000 in the field; 0.8 in some scenes), aspect 16:9, vertical field of view 40 degrees, and no jitter (row 0 / 1 z terms 0 in every logged frame). `xcx_mfx_camera` (`nvn_mtl.m` line 9203) moves the block into TOTK's layout (view-projection to 12, projection to 28; near / far / aspect / field of view computed from the projection). The block is not bound for the pass's first draws (sky, stencil), so the XCX path looks on to the first draw that binds it |
| Scene | The presented RGBA8 texture after its first draw: the frame ends with one pass into the swapchain texture whose first draw is the full-screen composite of the scene (vertex shader `d245cc0c`), and every later draw into a presented texture is UI | Passes 467490 / 467501 write the swapchain texture directly; there is no float canvas between the scene and the UI as in TOTK. So the canvas is any presented texture (`mfx_is_swap`, line 3679, from the list `uw_note_present` keeps) and the scene is copied before its second draw (`MFX_UI_DRAW` counts the draws, `canvas_draws`) |
| UI | Every draw into a presented texture after the composite: field HUD (minimap, quest marker and distance, enemy level labels, hint panel), battle HUD (party panel, enemy bar, arts palette, battle dialogue) | A rule instead of a shader list: the composite is one draw, so the list would only restate "everything after it". The UI layer (attachment 7) is attached to every later pass into a presented texture as for TOTK |

The canvas is display-encoded RGBA8 rather than TOTK's linear float, so `totk_mfx.m` interpolates and outputs it in that
encoding (`out_format`, line 138: RGBA8 in, RGBA8 out, no sRGB conversion). The UI layer is blended with the game's own
factors in that same encoding, so MetalFX's composite of it matches the game's.

Verified:

- Interpolated frames: in gameplay every game frame gets one. `m5.log` (key 2 pressed by the input file in the field):
  `插值帧 897 / 游戏帧 900 …；未插：缺输入 2（画面 2 相机 0 深度 0 UI 2）`, the 2 being the frame the mode came on;
  `m4.log` (key 2 pressed by the user): 1,797 of 1,800, the same 2 missing. Misses before that (`m2.log`, 342 by frame
  1200, not growing after) are the title screen's 2D frames and loading screens, where there is no G-buffer.
- Motion vectors: `TOTK_MFX_DUMP` while the camera turns (`m3.log`, 5.2 degrees a game frame). Check (scratch script):
  `prev(x + motion(x))` against `cur(x)` on a grid of the scene copies, mean absolute difference of the RGB sum: no warp
  27.0 / 27.1 / 26.9 / 23.7 / 21.4, warped by the motion 10.5 / 11.2 / 10.7 / 10.5 / 7.7 (dump pairs 10 / 20 / 30 / 60 /
  90), y negated 21.2 / 21.9 / 21.5 / 18.8 / 17.8, both negated 28.3 / 28.1 / 27.3 / 25.2 / 23.0. The background lines up
  with the motion as given, and the sign and y convention TOTK uses hold for XCX (`TOTK_MFX_YFLIP` not needed). The
  camera orbits the player, so the motion spreads (`TOTK_MFX_MVLOG`: median 44 px, p10 -38, p90 105 px a frame).
- The HUD: in the interpolated frame (`docs/screenshots/xcx-stage4-mfx-interpolated.png`, dump pair 20) the minimap,
  hint panel, labels and quest marker are sharp and at the same place as in the game frame that follows it
  (`xcx-stage4-mfx-game-frame.png`); the overlapping level labels top left are in the game frame too (two enemies). Battle
  HUD with interpolation on: `xcx-stage4-mfx-battle-on.png` (`m5_e_battle`). Motion texture: `xcx-stage4-mfx-motion.png`
  (128 + motion in red / green). All dump PNGs of pair 20: `nsw/XCX_build/shots/stage4/mfx20/`; the raw dump folder
  (0.9 GB) was deleted after reading.
- Colours: the interpolated frame has the game frame's tone (the RGBA8 path is not converted twice).
- No `【红】` line in `m1`..`m6`. Camera cuts: the existing rule (8 units or 25 degrees in a game frame) did not fire in
  these runs (`镜头切换 0`); a cut was not provoked, so that is not checked for XCX.

**Cost: on this Mac (MacBook Air, M1, 8-core GPU) the overlay does not reach 30+30.** Same spot, scripted (`m6.log`,
`TOTK_FRAMEGAP=1`, a new diagnostic: interval between game presents every 150 frames): interpolation off, p50 33.2 /
mean 33.2 ms (30.1 game fps) in every window; 30+30, p50 33.4-36.5 / p90 50-68 / mean 37.5-43.1 ms (23.2-26.7 game fps);
off again, back to 30.1. The FPS box shows `29` off and `23+23` to `26+25` on (`xcx-stage4-mfx-field-off.png` /
`-field-on.png`, `m5`), `25+24` in battle. MetalFX GPU time per interpolation (statistics line): p50 12.3-17.2 / p95
15-23 ms. That is MetalFX itself, not the hook-up: TOTK's probe (`games/totk/tests/metalfx_interp/probe.m`, built and run
on this Mac on an idle GPU) measures 11.2-11.7 ms per interpolated 1920x1080 frame (5.7 ms at 1280x720, 19.6 ms at
2560x1440). The interpolator runs at the game's 1920x1080, not the window's size (`frame interpolator: depth / motion
1920x1080 -> 1920x1080`). The game alone takes about 2/3 of the GPU at 30 fps (load line `GPU 95% (68%)`); 11-15 ms more
does not fit in 33 ms, so the game slows to about 24 fps. On this machine key 2 is a loss (fewer real frames); it needs
a faster GPU.

Known limits:

- Motion comes from the camera only. Characters and enemies moving on their own (the player running, Elma, the Blattas)
  ghost in the interpolated frames; so do rain streaks. The G-buffer has an RG16F target (texture 370, cleared to
  0,0,0.5,0.5) that may be the game's own velocity buffer; not looked at.
- The UI layer is this frame's UI over a half-step scene, so labels anchored in the world (enemy levels) are half a frame
  of camera motion ahead of their enemy in the interpolated frame.

Logs: `logs/stage4/m1.log` (scene block dump), `m2` (first frames made, motion log), `m3` (dumps), `m4` (the user's
window), `m5` (scripted field / turn / battle, `tools/sch_mfx.txt`), `m6` (on / off frame gap, `tools/sch_gap.txt`).
Captures: `nsw/XCX_build/shots/stage4/m*_*.png`, `docs/screenshots/xcx-stage4-mfx-*.png`. Code: `Makefile` line 19,
`third_party/d2r_gfx/gfx/nvn/nvn_obj.h` 201, `nvn_mtl.m` 3676-3679, 4301-4305, 9167-9215, 9943, 12541, 12569-12595,
`totk_mfx.m` 12-15, 39, 138-163, 176, 218, 278-310.

### 2026-10-23: stage 5, the app

Goal: a double-clickable `Xenoblade Chronicles X.app` that starts, plays and keeps the player's progress without a
terminal. It follows Bayonetta 3's app design (`make app`): a small launcher bundle that names the work folder in
Info.plist (`XCXWorkFolder`) and `exec`s `<work>/build/xcx-native` from there, so none of the game data (the 14.3 GB
`romfs.bin`, which holds `sts.ard`) is copied or cloned. TotK's self-contained bundle (root `build_app.py`, game data
cloned into the app, Metal cache warmed for the app's own path) is the later publishing step and was not done here.

| What | Where | Why |
|---|---|---|
| The app | `nsw/XCX_build/Xenoblade Chronicles X.app` (`APP ?= $(WORK)/$(APP_NAME)`; it used to be built into the current folder, i.e. this source tree), 2.6 MB on disk: launcher, Info.plist, the icon from the game's control data, ad-hoc signature (`codesign --force --sign -`, `codesign --verify --deep --strict` passes) | Nothing large in it, so no clone is needed; `make install` copies it to /Applications or ~/Applications (now with `APP_NAME`, as `APP` is a path) |
| Saves, account, pseudo device id, pipeline list | `~/Library/Application Support/MacNativeGames/XCX/profile` (`TOTK_PROFILE_DIR`, as Bayonetta 3's app) | On the first start without `profile/account.uid` the launcher **copies** `<work>/user-data/{account.uid, pseudo-device.id, pso_user.tsv, save/}` there (`seed_profile`, `app/launcher.m`) and logs each copy; never overwrites, never touches the originals. Copy rather than pointing the app at `user-data/`: the app keeps its profile where a Mac app keeps one, the terminal runs keep theirs, and a test run can never write into the player's game (or the reverse). The same account id means the same save folder name |
| Shader cache | `<work>/build/shader-cache/rt-totk-native-v4-unverified` (7,663 entries, unchanged location) | The runtime puts it next to the binary (`totk_shader_rt.m` `root_dir()`), and the app runs that same binary, so the app and `make boot` share one cache and the same path for Metal's own cache |
| RomFS verification record, game slot, input file | `~/Library/Application Support/MacNativeGames/XCX/` (`.romfs-verified-v1`, `game-slot/`, `input.txt`) | The first app start hashes the RomFS once (its first frame came at 9.8 s instead of 0.35 s) and records it there |
| Log | `~/Library/Logs/MacNativeGames/xcx.log` (the previous run: `xcx.previous.log`) | |

Launcher defaults (`app/launcher.m`), set so a double-click gives the picture the stage-4 runs had by hand:

- `TOTK_GPU_ALLOW_SUBMIT=1` (the one switch every stage-4 run set), plus Bayonetta 3's isolated GPU paths
  `TOTK_GPU_WIDEN`, `TOTK_GPU_BLOCKRT`, `TOTK_GPU_MIDCLEAR` as before (each one otherwise stops the host the first time
  its path is reached; none was reached in stage 4) and `DM_PRESENT_LINK_FALLBACK=1`.
- `TOTK_GPU_BUDGET_MB` is no longer set to Bayonetta 3's 5000: the runtime's default (40% of memory, 6,553 MB on this
  16 GB Mac, logged as `显存预算 6553 MB`) is what every stage-4 run used.
- The compact HUD: `TOTK_HUD` is unset at launch (never `corners`). MetalFX frame interpolation off at launch
  (`TOTK_MFX` unset; key 2 still toggles it): on this M1 it was a net loss (stage-4 interpolation entry).
- The presets are now this game's: "Original (30 fps, window)" (the default) and "Original (30 fps, full screen)", both
  without MetalFX spatial upscaling, which has not been checked for this game (before: Bayonetta 3's five presets, the
  default one with the 60 fps patch and MetalFX). The MetalFX setting is also off when no choice is saved. The 60 / 120
  fps, fixed-900p, LOD and grain choices stay in the window; their exefs patches do not exist for this game yet, and the
  window says so. Bayonetta 3's warning about its LOD patch is gone.
- `XCX_PLAY=1` (new, for scripted checks): Play at once with the saved settings. Pressing Play by script was not
  possible here: `osascript` has no assistive access on this Mac (`-1719`).

Build (from `games/xcx`; the runtime was rebuilt because the Makefile changed, same sources):

```sh
N=$(cd ../../nsw && pwd)   # absolute path of the folder holding the XCI, the keys and XCX_build
make app WORK=../../nsw/XCX_build PY=$N/XCX_build/venv/bin/python GAME="$N/Xenoblade Chronicles X Definitive Edition.xci" KEYS=$N/prod.keys
```

`GAME` and `KEYS` must be absolute: the icon recipe runs from `scripts/`. Free space before and after: 16 GB.

Verified (`nsw/XCX_build/tools/app5.sh NAME LIMIT`: `open --env XCX_PLAY=1 --env TOTK_FS_LOG=1` on the app, then the
app's own input file, hard time limit; logs `nsw/XCX_build/logs/stage5/`):

- `a1` (first start, 480 s limit): the launcher copied the four profile items (`[launcher] profile: copied ...`), hashed
  the RomFS once, `host save storage: ~/Library/Application Support/MacNativeGames/XCX/profile/save/c88ba527...`, first
  frame at 9.8 s. The user played with a DualSense during this run (`[input] user input (controller)`: Continue, key 2
  through every interpolation mode), so it only shows the app working end to end, not the scripted path; its capture is
  `nsw/XCX_build/shots/stage5/a1_63s_user_continue.png` (Primordia, from the copied save).
- `a2` (420 s limit, scripted): `RomFS unchanged; reused full SHA256 verification record`, first frame at 0.35 s;
  title at 50 s with **Continue** offered and selected (`docs/screenshots/xcx-stage5-app-title.png`); J (A) at 55 s; at
  95 s the player and Elma in Primordia with the field HUD (`docs/screenshots/xcx-stage5-app-continue.png`); `close` at
  115 s, `window closed; graceful guest shutdown pending` and the process gone within a second, as in the stage-4 runs.
  Up to the user's first input (after the 95 s capture) interpolation stayed off and the game ran at 30 fps (frame time
  p50 33.24 ms in every 300-frame window). The 110 s capture was taken after the user switched interpolation on and was
  moved to `nsw/XCX_build/shots/stage5/a2_110s_field_user_interp_on.png`.
- Shader cache reused: 0 `[shader] translated` lines in `a1` and `a2` (the log names the first 8 translations of a run),
  and every one of the 102 long-frame lines of `a2` says `新建管线 0 条 + 着色器库 0 个` (no new pipeline, no new library).
- MetalFX upscaling and output both logged off; GPU budget 6,553 MB; no `【红】` line; no `FATAL`.
- The originals are unchanged: SHA-256 of every file in `<work>/user-data` before and after both runs
  (`logs/stage5/user-data-before.sha256`). In the app's profile only `pso_user.tsv` changed (9 lines appended in `a1`,
  the pipelines of the interpolation modes the user switched through); the save files are byte-identical to the
  originals (no save was made in these runs).

Left for the root `build_app.py` (not done): a self-contained app with the RomFS and code cloned in (APFS
`clonefile`, as TotK's), a bundled shader seed and Metal cache warm-up for the bundle's own binary path, seeding the
player's profile from a work folder that will not exist on another Mac, and the 60 fps / resolution patches the
settings window still lists.


### 2026-10-23: stage 5, GPU time on an M1 (clear sinking)

Goal: less GPU time per frame on the MacBook Air (M1, 8-core GPU) without changing the picture. The game renders
1920x1080 at 30 fps and used about 20 ms of GPU per frame, so MetalFX interpolation (11-17 ms, stage 4) did not fit.

**Benchmark** (`nsw/XCX_build/tools/`, logs `nsw/XCX_build/logs/stage5/`, captures `nsw/XCX_build/shots/stage5/`):

- `bench5.sh NAME SCHEDULE [ENV=...]` runs the game from the work folder like `run4.sh`. Every run gets a fresh copy of
  `user-data` as its profile (`bench5-profile`), so neither the player's saves in `user-data` nor the app's profile are
  ever written. Per-frame timing goes to `NAME.tsv` (`DM_NVN_TSV`, timing rows only); `@gpu_ms` is the frame's summed
  command-buffer GPU time, the number the `计时` line reports as GPU. It runs `build/xcx-native-exp`, never the default
  binary the app launches. `build_exp.sh` builds that binary and puts `build/xcx-native` back to
  `build/xcx-native.default`.
- `sch_bench5.txt`: title (window 30-48 s), Continue (J), the field standing still (96-106 s), the camera turning
  right and left (107-116 s), then R (target) and A: the battle with the Pebble Blatta (124-150 s). `bench5_stats.py`
  gives p50 / p90 / mean per window and counts `[input] user input` lines.
- `ab5.sh NAME FLAG` runs `sch_ab5.txt`, which switches a run-time flag (`flag NAME 0|1`) on and off in the same process:
  6 s windows on the title, 5 s in the field, 4 s in battle. `ab_stats.py` gives each window's GPU median, the mean per
  state and the difference of each "on" window against its two neighbours. Run to run, the same scene varies by
  1-1.5 ms (rain, enemies, the time of day, other load on the Mac; one baseline run, `fb3`, measured 24 ms in the field).
  The windows of one process vary by about 0.3 ms, so every effect below comes from the A/B runs.
  - Pitfall: the title scene's GPU load has its own 6 s cycle. 3 s windows locked onto it and showed effects that
    were not there, so title windows are one whole cycle long and use the mean.
  - Pitfall: `@t_s` counts from the runtime's clock start, which comes 0-2 s after the driver's. `ab_stats.py` fits
    the shift from the submission thread's CPU time, which the flag changes at once.
- `pass_struct.py LOG OFF ON` compares the render passes of two dumped frames (`passdump`). `imgdiff.m`
  (`tools/bin/imgdiff`) gives the mean pixel difference of two captures.
- The user played in several of these windows (`[input] user input`; `s0`, `s2`, `ab6`, `ab7`, `fb1`, `fb2`). Those
  runs' measurements are void and are not used below; `fb1` and `fe1` were also closed early.

**Where the GPU time went** (`flag pass_gpu 2` with `TOTK_PASS_GPU_FILE`: GPU time of each encoder; `p1`, field frame
2781, 90 render encoders, 22.8 ms):

- The G-buffer (seven RGBA8 / RG16F colour targets and a D32S8 depth, 1920x1080) was drawn in five pieces of one
  pass. They are separated by a 1024x1024 depth pass of skinned character meshes, which looks like a per-character
  shadow. The first two pieces cost 3.5 ms each; every piece loads and stores all eight attachments.
- Before that, each of the eight G-buffer targets was cleared in a pass of its own: 0.15-0.30 ms each, 1.6-1.9 ms in
  all. These passes only exist in the translation. The game sets one target, clears it, sets the next... and the
  layer lands each pending clear in a clear-only pass when the targets change. On a tile-based GPU such a pass writes
  the whole target to memory, and the G-buffer pass then reads it all back.
- Measurement-only switches (each short run against a short baseline of the same day):
  - `TOTK_EXP_NOLOAD=1` (every Load becomes DontCare; the picture is wrong) took the frame from about 20 to 15 ms, so
    attachment loads cost about 5 ms.
  - `TOTK_BARRIER_NARROW=2` gave no gain.
  - Dropping every barrier (`TOTK_BARRIER_START=0 TOTK_BARRIER_END=0`, races) made the summed command-buffer time go
    up, not down: overlapping command buffers are counted twice, so this metric cannot size the barriers.
  - The whole `DM_NVN_TBDR=1` suite was 3.5 ms slower (23.6-24.4 ms). Of its rewrites, only the clear-only pass hoist
    and the same-target continuation fired.
  - The rasterizer-discard skinning draws from stage 4 run 56 a frame, each followed by a barrier. A same-process A/B
    without those barriers (`ab3`) showed no difference (field +0.2, battle -0.3 ms), so they are not a cost worth
    removing.
  - First-draw load elision (the TBDR suite's coverage proof alone): the proof never holds for this game's full-screen
    passes (`why=2`: the position is not a plain vertex attribute), so it saved nothing and was removed again.
  - `flag exp_gload 1`, which skips the G-buffer pieces' loads, was a measurement only and makes a wrong picture. The
    user saw its artifacts while playing in that test window (`ab6`). It was dropped and is not in the source.

**Clear sinking** (`third_party/d2r_gfx/gfx/nvn/nvn_mtl.m` 8247-8430, `#ifdef GAME_XCX`; hooks at 1054, 1955, 2359,
4382, 11210, 11237-11238). Neither TotK nor Bayonetta 3 builds any of it.

- What it does: at `SetRenderTargets`, a full clear that is still pending is not landed in a clear-only pass. It moves
  to the next pass that attaches the same texture level / layer, which then starts with a Clear load action instead of
  a Load. When that pass starts, the attachment holds the clear value either way.
- The proof (`csink_scan`): scan this submission forward in replay order, through calls, the replay's own call stack
  and the remaining handles. Until the first draw with the texture attached:
  - no draw or dispatch may read or write a texture whose pool memory overlaps it. Reads and writes are found through
    the program's reflection and the bound texture / image slots; the layer binds only what the reflection declares.
  - no attachment, clear, copy or texture clear may overlap it. Overlap is by memory, so other NVN texture objects on
    the same storage (storage-shared Metal textures) count.
  - every program met must already be resolved.
- Anything not proven keeps its clear-only pass. A sunk clear not taken by the time the replay has passed that draw (a
  skipped draw), or by the end of the submission, is landed then in a clear-only pass of its own, still before any
  access.
- A clear that failed its proof is not scanned again for 30 frames. Skipping a scan only keeps the old pass, so this is
  safe, and it cut the extra CPU time on the submission thread from about 1.5 to about 0.5 ms a frame.
- `XCX_CLEAR_SINK=0` or `flag clear_sink 0` turns it off. Every 900 frames a `[clear-sink]` line counts the tries, the
  moved clears, those taken by their pass and those landed alone, and why the rest were not proven. In `ab5`: 54,000
  moved, all taken by their pass, none landed alone; not proven: about 3,000 for reaching the end of the submission,
  about 1,000 for a read, about 150 for an unresolved program.
- In the frame: 107 -> 94 passes on the title, 92 -> 80 in the field, 101 -> 89 in battle. The first G-buffer piece
  went from 3.5 ms (loading 8 attachments) to 1.4 ms (clearing them), and the clear-only passes are gone (`p2`).

GPU ms per frame, same process, flag off / on (mean of window medians; paired = each "on" window against its
neighbours):

| Run | Title | Field | Battle |
|---|---|---|---|
| `ab4` | 19.55 / 17.62 (paired -1.96) | 20.36 / 17.75 (-2.50, range -1.92..-3.23) | 19.45 / 16.70 (-2.56, range -2.18..-3.30) |
| `ab8` | 22.31 / 19.22 (-2.99) | 21.43 / 19.20 (-2.32, range -1.77..-3.39) | 22.08 / 18.94 (-2.99, range -1.52..-4.22) |
| `ab2` (field, battle; its title windows hit the 6 s cycle) | | 20.20 / 17.50 (-2.64) | 19.92 / 17.20 (-2.69) |

Separate runs of the whole schedule (`bench5.sh`; only windows without user input), GPU p50 / p90 ms:

| | Title | Field | Turn | Battle |
|---|---|---|---|---|
| before (`b3`, `fb2` title, `fb3`) | 19.95 / 21.80, 19.75 / 20.56, 20.26 / 23.56 | 21.46 / 23.12, 24.13 / 31.70 | 21.31 / 23.57, 25.05 / 30.40 | 20.53 / 22.34, 24.51 / 33.56 |
| after (`fe2`, `fe3`) | 17.61 / 19.45, 17.85 / 18.30 | 16.80 / 18.43, 16.78 / 19.07 | 16.25 / 18.54, 15.81 / 17.27 | 16.64 / 18.10, 16.64 / 18.69 |

The game alone now takes about 17 ms of the 33.3 ms frame at 30 fps, where it took about 20 ms. That leaves about
16 ms of headroom, where there was about 13. Frame pacing is unchanged (frame time p50 33.2 ms in every run).

Picture checks:

- Pass structure (`st1`, `tools/pass_struct.py`): a frame dumped with the flag off is rewritten by moving each
  clear-only pass's clears into the next pass that loads the same texture. The result is compared with a frame dumped
  with the flag on: attachments, load actions and clear values per pass.
  - Battle: 89 of 89 passes identical.
  - Field: 78 of 80. The other two are a G-buffer piece and a depth pass that vary from frame to frame in both states.
  - Title: 90 of 93 / 94. The others are double-buffered textures (444 / 445) and the swapchain (1 / 2) alternating,
    plus one extra G-buffer piece.
- Captures of 4 consecutive frames in each state (`st1_*_off_*`, `st1_*_on_*`). The mean pixel difference between
  consecutive frames (rain, animation) is the same in both states: title 0.21 / 0.21, field 1.11 / 0.98, battle
  1.16 / 1.06 (0-255). Side by side: `docs/screenshots/xcx-stage5-perf-clearsink-{title,field,battle}-{off,on}.png`.
- No `【红】` line in any run with clear sinking.
- Not checked: New Game / character creation, cities, Skells, cutscenes, interpolation (key 2) with it on.

**`DM_NVN_GPU_CODE_MAX_MINOR`** (open since stage 2): the game never asks for it. With `DM_NVN_LOG=1`, `g1log` lists
every `nvnDeviceGetInteger` the game makes: 0, 1, 0xa, 0xf, 0x10, 0x11, 0x12, 0x38, 0x51 and 0x5c, never 0x30
(GLSLC max GPU code minor). With 14 instead of 31 (`x4gate14`): the same shaders (0 new translations, 0 new
pipelines), the same picture and GPU time within noise (title 19.96 / field 19.90 against 19.90 / 19.77). The setting
in `system_services.c` is inert for this game.

**Left, with estimates:**

- The G-buffer drawn in pieces around the character-shadow depth pass: after clear sinking, the second piece still loads
  all eight attachments (3.3 ms with 1,830 draws), and the first stores them. Drawing the shadow pass's few draws after
  the G-buffer (or before it) would save one load and one store of about 70 MB, roughly 1-2 ms. The proof needs the
  bone-matrix buffer that the skinning draws write in between, and the per-frame uniform updates (the TotK pass
  deferral refuses those). Not attempted.
- The lighting and post-processing passes (1.6, 0.9, 0.9, 0.9 ms...) are mostly the game's own work. Their full-screen
  first draws cannot be proven to cover the target (above).
- Twelve 64x64 passes (exposure / luminance) cost 0.74 ms, two of them about 0.5 ms with a single draw. Their shaders
  were not looked at.
- About 80 render passes a frame, each starting and ending with a full barrier (the layer's Metal 4 rule). Their fixed
  cost was not separated (see above).

**60 fps or interpolation on this M1:** still no. At about 17 ms of GPU per game frame, 60 fps would need about
16.7 ms with no CPU or present overhead: within reach of one or two more fixes like this one, but not there. 30+30
interpolation needs 17 + 11-17 ms (MetalFX alone, stage 4), i.e. 28-34 ms of the 33.3 ms. The low end of that range
fits, the high end does not; it was not re-measured.

Logs: `nsw/XCX_build/logs/stage5/` (`b*` baselines, `s*` short baselines, `x*` measurement-only switches, `p*` pass
profiles, `ab*` same-process A/B, `st1` pass structure, `fb*` / `fe*` final runs). Commits: none; this checkout is not a
git repository.

### 2026-10-23: local folders moved

The `nsw/` paths in the entries above are the old layout. The personal files (XCI, `prod.keys`, `title.keys`, `fw/`,
`fw.zip`) moved from `nsw/` to `personal/`, and the work folder from `nsw/XCX_build/` to `XCX_build/`, both at the
repository root and ignored by git (`nsw/` is gone; the ignore line stays for old checkouts). Moved with `mv`, nothing
copied or deleted. Since the runtime and the app hold absolute paths of the work folder, these were redone from the new
place:

- `make prepare runtime WORK=../../XCX_build PY=<abs>/XCX_build/venv/bin/python`: `shared_fonts_config.h` held the old
  font paths, so the binary changed (`build/xcx-native` sha256 `fbc19c8e...`, was `fecb7e29...`; same sources, clear
  sinking).
- `make app WORK=../../XCX_build PY=... GAME=<abs>/personal/<XCI> KEYS=<abs>/personal/prod.keys`: Info.plist's
  `XCXWorkFolder` names the new folder.
- The venv's `bin/` scripts and `pyvenv.cfg` had the old path written into them and were pointed at the new one;
  `venv/bin/python` itself worked unchanged.

Checked with `XCX_build/tools/app5.sh` (150 s limit, log `XCX_build/logs/stage5/m1_move.log`): the profile in
Application Support was not seeded again, the RomFS record was reused (no re-hash), the shader cache was reused (0 new
shaders), the save loaded into Primordia, no failure lines, and the profile's ten files are byte-identical after the
run. The run also logged real keyboard input from the user.

### 2026-10-23: one-command build (`build_app.py`, macOS)

Goal: the player's own XCI (or a base NSP with the 1.0.1 update NSP) becomes a self-contained Mac app with one command,
following the original project's root `build_app.py` (TotK / BotW): the game recognised by the IDs inside the files,
every step checked against `assets/expected-v1.0.1.json`, keys never printed, a reusable work folder, APFS clones into
the app, ad-hoc signing. The `--platform` option is there (`macos`; `ios` is reserved and refused).

**What was added or changed.**

- `build_app.py` (repository root): requirements check (Apple silicon, macOS 26, clang / clang++ headers,
  `llvm-objdump`, make / git / codesign, Homebrew `opus` / `libvpx` static libraries, Python 3.14), the work folder's
  venv (`requirements.txt` + `unicorn==2.1.4`, reinstalled only when the list changes), then seven checked steps:
  ExeFS (pinned SHA-256; `main.npdm` also by Nintendo's ACID signature, as upstream), NSO segments
  (`prepare_modules.py`), rewrite (pinned SHA-256), rewrite checks (`structck.py` and `equiv.py`, recorded in
  `analysis/rewrite-checks.json` with the image and checker digests), shared fonts, merged RomFS (SHA-256, size, 53
  files, bytes from base / update), `make prepare`, `make runtime`, `make shader-tools` (translator SHA-256, SPIRV-Cross
  HEAD = pinned commit), `make launcher icon`, then the app. Each step is timed (`logs/build-times.json`).
- `scripts/identify_game.py`: one JSON line per file (NCA title IDs and content types, content metas with versions,
  ticket rights IDs and kind). `build_app.py` refuses another title (named when known: TotK, BotW, Bayonetta 3, the
  other Xenoblades), the update given as the game, a base-only file without `--update`, another base or update
  version, and an NSP whose rights-managed NCAs have neither a common ticket nor a `--title-keys` entry, all before any
  long step.
- NSPs: `extract_code.py` and `merge_romfs.py` take `--update <update.nsp>` and `--title-keys`;
  `extract_exefs.load_title_keys` reads title.keys into memory, and `common_tickets(..., personalized='skip')` passes a
  personalized ticket over when title keys are given. Upstream takes title keys from common tickets only (its hactool
  hook `MNG_TITLE_KEYS` is the other way); here a title.keys entry fills in, a common ticket in the file wins.
- Shared fonts: from the XCI's system update partition (`extract_shared_fonts.py --xci`, which existed but was not
  used) or `--firmware`. `expected-v1.0.1.json` now pins `shared_fonts_sha256`, each name with the known versions: this
  card's system update, the firmware in `personal/fw` the port was first run with, and upstream's TotK reference; another
  valid, NCA-verified font is bound by its own bytes, as upstream does. The README's "copy them from a TotK build" step
  is gone.
- `scripts/app_bundle.py`: the app's name, identifier, Info.plist and the list of files a self-contained app carries,
  shared by `make app` (which now writes its bundle with `app_bundle.py dev`) and `build_app.py`.
- `scripts/prepare_runtime.py` writes its headers and the RomFS index only when their content changes, so `make
  prepare` on an unchanged work folder does not relink the runtime.
- Makefile: `launcher` and `icon` targets; the launcher includes `dmsh_chain.h` and `game_version.h`;
  `TITLE_KEYS=` for the icon of an NSP. Changing the Makefile makes `make` rebuild the graphics objects once.
- `app/launcher.m`: a self-contained mode, used when `Contents/Resources/xcx/build/xcx-native` exists and `XCX_WORK`
  is not set. It runs the game from there, sets `TOTK_SHADER_CACHE` to `~/Library/Application Support/MacNativeGames/
  XCX/shader-cache/rt-<chain>` (upstream's place), `TOTK_SHARED_FONTS` to the fonts in the app and the RomFS record to
  `.../XCX/app-romfs-record` (the record names the image's file identity; with the shared one the development and the
  self-contained app would make each other hash 14 GB in turn), does not seed the profile, and logs which kind of app ran
  and where its RomFS image is. `--check` (run once by the build so macOS's first-run scan happens then). The
  XCXWorkFolder mode is unchanged, except that `TOTK_SLOT_OWNER` / `TOTK_SLOT_PURPOSE` from the environment are kept, so
  a scripted check can run as an agent's session that a game the user starts takes over.

**App layout.** `Contents/Resources/xcx/{build/xcx-native, build/spirv-cross/spirv-cross,
build/shader-service/totk_xlate, rewritten/v101/*.patched.bin, extracted/v101/romfs/runtime-index.bin,
extracted/firmware/shared-fonts/}`, and `extracted/v101/romfs/romfs.bin` a relative link to
`Contents/Helpers/GameData-v101.bundle/Contents/Resources/romfs.bin`. The data bundle is signed once in the work folder
(`build/data-bundles`, stamped by size, mtime and SHA-256) and cloned in, so the app's own signature does not hash 14 GB
again; an installed app with the same data keeps its bundle (inode, so the RomFS record stays valid), and the `.app`
folder is kept while its contents are replaced (upstream's `keep_game_data` / `install_app`). No startup shader seed
exists for this game, so there is no Metal cache warm-up step.

**Checked** (M1 MacBook Air, macOS 26.5.2; disk 52 GB free before):

- Clean build `python3 build_app.py "personal/<XCI>" -k personal/prod.keys --work XCX_build_clean -o
  "XCX_build_clean/Xenoblade Chronicles X.app"`: exit 0 in 433 s. Steps: venv 6.0 s, identify 0.5, ExeFS 0.2, NSO 1.6,
  rewrite 72.7, rewrite checks 72.6 (structck OK, equiv 0 divergent sites, for all three modules), fonts 0.2, RomFS 35.9,
  prepare 0.6, runtime 15.0, shader tools 18.4, launcher and icon 1.2, data bundle 82.4 (signing 14 GB), assemble and
  sign 0.6, register and first check 124.7 (macOS's first scan of the new app). `codesign --verify --strict` passes. The
  three copies of the image (work folder, data bundle, app) share their physical blocks (`F_LOG2PHYS_EXT` at 0, 5 and
  13 GiB): `du` shows 41 GB, the folder takes about 13.8 GiB.
- Second run: 1.7 s, every step reused (the app "current: same files, valid signature").
- The app, opened with `open --env XCX_PLAY=1 --env TOTK_SLOT_OWNER=claude` and scripted input (J at 55 s after the
  first frame, capture at 110 s, close at 115 s; `XCX_build_clean/logs/app-checks/b1.log`): the launcher logged the
  self-contained mode with the RomFS image inside the bundle's data bundle; the RomFS was hashed once (first frame
  9.7 s); the save storage is the profile in Application Support; Continue loaded the save into Primordia
  (`XCX_build_clean/shots/b1_110s_field.png`); the shader cache is the one in Application Support (new: 17 translation
  lines); 0 `【红】`, 0 FATAL; graceful close.
- Moved to a folder outside the work folder (`mv`, same volume) and opened again (`b2_moved.log`): game folder and RomFS
  image in the moved bundle, `RomFS unchanged; reused full SHA256 verification record`, first frame 0.49 s, 0 shaders
  translated, Continue into Primordia (`b2_moved_110s_field.png`); the only work-folder path in the log is the capture's.
  Moved back; the seal still verifies.
- Save files and account in the profile: SHA-256 identical before and after all runs. The development app's RomFS
  record (`.romfs-verified-v1`, 13:15) was not touched by the self-contained app.
- The separate-update path: an update NSP written from the XCI's own update NCAs (with and without its ticket) and a
  scratch title.keys made from that ticket. `extract_code.py` gives the pinned ExeFS hashes with the ticket and with
  title.keys, and stops without either; a full `build_app.py <XCI> --update <NSP without ticket> --title-keys ...` into a
  scratch work folder passed every check (446 s) and was deleted. A real base NSP was not tried (14 GB more disk).
  The player's own title.keys has no entry for this game.
- Refusals, each with nothing written: title.keys as the game ("not an XCI or NSP game file"), the update NSP as the
  game, an NSP without `--update`, an update NSP without ticket or title key, `--update` = the XCI, a non-`.app`
  output, `--platform ios`.
- Developer path: `make prepare runtime app WORK=../../XCX_build_clean ...` with `APP=` a scratch path: nothing
  rebuilt, the development app's Info.plist names the work folder, its seal verifies; opened (`b3_dev.log`) it ran in
  the development mode from the work folder and continued into Primordia, 0 failure lines. The user played during this
  run (two `[input] user input (keyboard)` lines); the saves stayed identical. The dev app's RomFS record was saved before
  and put back after it.
- `XCX_build/` was not touched (no file newer than the start of this work).

**Not done / open.** No startup shader seed or Metal warm-up for this game; a new install translates shaders as they
appear. The game did not ask for the shared fonts in these runs (nor in the earlier ones), so the in-app font path
(`TOTK_SHARED_FONTS`) is checked only by its files' SHA-256 matching the binary's table. A real base NSP is untested. No
iOS build: `--platform ios` needs a device runtime and packaging (`runtime/frontend_ios.m` is here, upstream's
`ios/tools/build_ipa.py` is not).

### 2026-10-23: experimental iPhone / iPad IPA (`build_app.py --platform ios`)

**What.** `--platform ios` now builds an unsigned IPA for sideloading. By default it writes `<game file folder>/Xenoblade
Chronicles X.ipa`. The user asked for it knowing it is experimental: an iPhone cannot translate shaders at run time, and
this port has no up-front translation, so most of the picture is missing. The build prints that warning at its start and
at its end.

**Restored from the original project** (`git show upstream/main:games/totk/ios/...`) into `games/xcx/ios/`:

- `Sources/main.m`: classes renamed `XCX*`. It sets the Mac launcher's runtime switches: handheld mode, the shared
  fonts, the seed, the shader cache in Documents, the profile and the RomFS record in Documents, `TOTK_ROMFS_PATCHES=0`,
  and no `XCX_PATCHES`. The game image is in Documents/GameData. This runtime has no `TOTK_ROMFS_DATA`, so the app copies
  its RomFS index next to the image and points `TOTK_ROMFS` there, and the Mac runtime is unchanged. A `romfs.bin`
  dropped at the top of Documents (Finder file sharing) is moved into GameData once it has the build's size. A partly
  copied image is reported on screen. The runtime has no `runtime_audio_output_restart`, so a weak stand-in only logs.
- `Sources/touch_pad.{h,m}`: unchanged apart from the class name.
- `Sources/XCX.entitlements`: the increased memory limit.
- `Sources/Info.plist`: the template that xcodegen fills.
- `Settings.bundle`: the language picker, cut to the languages this game is believed to have.
- `project.yml`: paths come from `${XCX_*}` variables, so the project and DerivedData go to `<work>/build/ios`, not
  into the source tree. The sources follow the Makefile's list, with `-DGAME_XCX` on the graphics layer.
  `tex/nvn_bctc.metal` and the docs are left out.
- `tools/build_deps.py`: falls back to Unix Makefiles when Ninja is missing, keeps a reuse stamp, and has a Simulator
  mode (libvpx `generic-gnu`).
- `tools/build_ipa.py`: rewritten around the work folder. It exports, embeds, builds the deps and the seed, generates
  the project, then runs `xcodebuild -target XCX -sdk iphoneos`, because `-destination` needs the iOS platform
  component downloaded. The icon is added as CFBundleIcons PNGs, because actool wanted a Simulator runtime matching
  SDK 26.5. The IPA has no game image.
- `tools/compile_seed.py`: an empty seed compiles nothing. Without the Metal toolchain the seed keeps its MSL, which
  the device compiles on first use (`nvn_mtl.m shader_load`).
- `tools/fill_shaders.py`: has no shared list. It translates into `<work>/build/ios-fill`, and the next IPA carries
  those translations.
- `tools/install_device.py`: XCX names, `org.macnativegames.xcx.<team>`, and `--game-data` for the 14.3 GB image.
- `tools/shader_contrib_watch.py`: a stub, because there is no shared list or issue form.
- `tools/gen_embed.py` and `tools/xcode_dir.py`: unchanged.

Bundle id `org.macnativegames.xcx`, the same as the Mac app (another platform, so the two do not clash).
`install_device.py` signs as `.<team>`. Display name "Xenoblade Chronicles X", executable `XCX`.

**Shader seed (the optional extra).** It is done. The build reads the variants already translated in the player's
Library cache, the work folder's `build/shader-cache` and `build/ios-fill`, and any `--ios-seed-cache` folders. It
copies them out in the startup-seed format (`totk_shader_seed.h`: `<variant>_b.metal/_b.json`, per-shader `.variants`,
`seed-manifest.json` with the chain). It leaves out MSL with doubles or unsupported GLSL.std.450 calls. The caches are
only read: their file counts were the same before and after (5455 and 8383).

**Verified.** `python3 build_app.py "personal/Xenoblade Chronicles X Definitive Edition.xci" -k personal/prod.keys --work
XCX_build_clean --platform ios -o XCX_build_clean/xcx.ipa --ios-seed-cache XCX_build/build/shader-cache` finished in
37 s, with steps 1-6 reused and the IPA step 36 s; the first run took a few minutes more for the deps. The IPA (39 MiB):

- `unzip -t` OK, and the archive holds `Payload/XCX.app`.
- Info.plist: `org.macnativegames.xcx`, "Xenoblade Chronicles X", 1.0.1 (65537), `iphoneos`, MinimumOSVersion 26.0,
  file sharing on.
- `XCX` is a Mach-O arm64 executable with LC_BUILD_VERSION platform 2 (iOS), minos 26.0, sdk 26.5. Its segments are
  `__TOTKX` 36.9 MB, `__TOTKmainW` 51 MB, `__TOTKsdkW` 6.4 MB and `__TOTKsubsdk0W` 3.4 MB.
- Ad-hoc signed with `increased-memory-limit`.
- GameData holds the RomFS index, six fonts and a seed of 1456 variants (4209 files, no metallibs: no Metal
  toolchain on this Mac).

The Mac app rebuilt again with `--work XCX_build_clean`. Every step was reused, the app was re-assembled and signed,
`--check` passed, and `codesign --verify --strict` was OK. The Mac runtime and launcher are unchanged, so the game
was not relaunched.

**Not done.**

- The **Simulator**: the graphics layer is Metal 4, and the iPhoneSimulator 26.5 SDK has no
  `MTLGPUFamilyMetal4` and no `newMTL4CommandQueue` (a test compile failed on them). MetalFX is absent there too
  (`totk_mfx.m` does not compile). It would need a Metal 3 back end.
- **Device install**: no device was connected.
- Not checked on a device: memory footprint, input, audio, the RomFS check and the fill round trip.

### 2026-10-23: the build window (`build_app.py --gui`)

**What.** `python3 build_app.py --gui` opens a native SwiftUI window. It builds the Mac app, or the experimental IPA,
from the player's own files without the command line.

**The window** (`games/xcx/builder/`: `BuilderApp.swift`, `BuildModel.swift`, `ContentView.swift`, `TestHook.swift`,
`Info.plist`):

- File pickers for the game file (XCI or base NSP), the 1.0.1 update NSP (shown when the game file is an NSP, which is
  told apart by its PFS0 header, not its name), prod.keys, title.keys (optional), the firmware folder (optional), the
  output (a save panel; the default is `<game folder>/Xenoblade Chronicles X.app`, or `.ipa`), and the work folder
  (under Advanced).
- Mac / iPhone and iPad (experimental), with the experimental warning when iOS is picked.
- A prerequisites panel with every check and a copyable fix for each missing one.
- The legal notice before the first build (own the game, your own keys, never share the build). Acceptance is kept in
  UserDefaults.
- Build, each step with its status and time, a collapsible log, Cancel, and then Open App / Show in Finder. A failure
  names the step and the message, and offers the step's log file.
- The last-used paths and platform are remembered. Only paths are passed. The window never reads the key files.

**Compile on first use.** `build_app.py --gui` hashes the Swift sources, `Info.plist` and `xcrun swiftc --version`,
and compiles with `xcrun swiftc -O -parse-as-library -target arm64-apple-macos26.0` into
`~/Library/Caches/MacNativeGames/xcx-builder/<hash>/XCX Builder.app`. It ad-hoc signs the bundle, removes older
versions, and opens it with `--script <build_app.py> --python <the Python running it>`. Nothing is built in the source
tree and nothing ready-made is shipped. A second `--gui` brings the open window forward.

**Protocol** (`build_app.py`; without these flags the CLI is unchanged):

- `--progress json`: stdout carries one JSON object a line, each with `event` and `time`. The events are `plan`
  (platform, the step names in order), `start` (platform, game, out, work), `step` (step, status `running`, then
  `built` / `reused` / `checked` / `failed` / `cancelled`, with seconds), `done` (platform, out, work, seconds), `error`
  (step, message, log, fixes) and `cancelled` (step). All human output goes to stderr. `inputs` and `requirements` are
  reported as steps but stay out of `logs/build-times.json`.
- SIGTERM in this mode cancels. Each step's tool runs in its own process group, which gets SIGTERM, then SIGKILL after
  10 s. Replacing an installed app or data bundle is a critical section, where a cancel waits until the section ends.
  Exit 130.
- `--check-requirements [--platform ios] [--progress json]` reports every requirement, also past the first missing
  one: `requirement` events (name, ok, message, fixes), then `requirements` (ok). Exit 0 or 1. `prerequisites()` runs
  the same checks in the same order and raises the same messages as before. `BuildError` now carries `fixes` and `log`.

**Checked** (M1 MacBook Air, macOS 26.5.2):

- `xcode-select -p` points at Xcode. The sources also compile with only the command line tools: `DEVELOPER_DIR=
  /Library/Developer/CommandLineTools xcrun swiftc` with no warnings, and `builder_app()` with the same toolchain
  produced an ad-hoc signed bundle. It takes about 5 s per compile on this Mac.
- `--gui` compiles and opens the window. Screenshots are in `XCX_build_clean/shots/builder-*.png`. The window draws
  them itself through the test hook, because this Mac's terminal has no screen recording permission for
  `screencapture`.
- A build through the window (the test hook fills in the XCI, prod.keys, `--work XCX_build_clean` and the output
  `XCX_build_clean/gui-test/Xenoblade Chronicles X.app`). Every work step was reused. The new app folder was assembled
  and signed in 0.6 s, and macOS's first scan of it took 120 s. Run again, everything was reused and it took about 2 s.
  The window ended with Open App and Show in Finder (`builder-3-done.png`, `builder-4-done-log.png`). The gui-test app
  was then deleted: it was an APFS clone, and deleting it freed only a few MB.
- title.keys as the game: the window shows "Stopped at “inputs”" with the message, and nothing is written
  (`builder-5-error.png`).
- Cancel, in a scratch work folder: during a fresh `code: rewrite` (`builder-7-cancelled.png`) and at `code: rewrite
  checks`. Then SIGTERM to `--progress json` while `equiv.py` ran with 9 worker processes: exit 130, 0 workers left,
  the finished rewrite was reused on the next run, and all stdout lines parsed as JSON. The scratch folder was deleted.
- The prerequisites panel with a missing requirement (iOS with `DEVELOPER_DIR` set to the command line tools):
  `builder-10-missing.png`. The iOS warning is in `builder-8-ios.png` and the notice in `builder-9-notice.png`.
- CLI: the normal Mac command on `XCX_build_clean` reused every step. The first rerun re-assembled the app in 0.7 s,
  because the app stamp named the gui-test output. The second rerun was "current", 1.1 s, and the seal verifies. The
  build's output, and the output of five error cases, are the same as the previous `build_app.py` apart from
  timestamps and timings. The only difference is the usage line, which now lists the three new options. `py_compile`
  passes.

**Not done / open.** The file pickers and the Open App button were not clicked by hand: there was no accessibility
permission for UI scripting, and the hook sets the fields directly. No iOS build was run through the window (Xcode
components were being downloaded). The builder has no app icon. Building into a new output folder means macOS scans
that app once (about 2 minutes), as from the command line.

### 2026-10-23: one work folder, `XCX_build/` at the repository root

There were three local folders: the development work folder `XCX_build/` (its own 14 GB extraction, the development
app, test scripts, logs and 958 MB of captures), `XCX_build_clean/` (the work folder of `build_app.py`) and
`XCX_build_v200/` (the update 2.0.0 feasibility study). Now there is one, `XCX_build/` at the repository root, and it is
the default work folder of `build_app.py` and of the build window, wherever the game file is. The app still goes next
to the game file by default (`-o` chooses another place).

- The old `XCX_build/`'s shader cache (`build/shader-cache/rt-totk-native-v4-unverified`, 8,383 files) was merged into
  the self-contained app's per-user cache, same chain: 1,663 files copied, 6,720 already there with the same name and
  kept (6,517 identical; the 203 that differ are 202 `.variants` indexes and `pso_collected.tsv`), so 7,261 files became
  8,924. Its `user-data/pso_user.tsv` was not merged into the profile's: same format, but every one of its lines is
  already in the profile's copy, which began as a copy of it.
- The records worth keeping (`FEASIBILITY.md`, `tools/`, `analysis/`, `logs/`, `inventory.log`, the stage-0 JSON and
  NVN / service lists, the two old save copies, the five captures this changelog names under `shots/stage4` and
  `shots/stage5`, and `FEASIBILITY-v200.md`) went to the user's private files outside git; the rest of the old folder
  was deleted (about 16 GB freed). The references to `XCX_build/shots/...`, `XCX_build/tools/...` and
  `XCX_build/logs/...` in the entries above point to that old folder.
- `XCX_build_clean/` was renamed `XCX_build/`, so the `XCX_build_clean/...` paths above now read `XCX_build/...`. The
  2.0.0 study was folded into it: `rewritten/v200`, `extracted/v200/exefs` and `cache/verify_v200` where the build keeps
  1.0.1's, the rest in `analysis/v200/`. `build_app.py` reads only the `v101` folders, so the `v200` ones are not
  touched by a 1.0.1 build. `extracted/v200` has no `extraction-manifest.json`, so a future 2.0.0 step would extract
  that ExeFS again (seconds).
- Paths written into the renamed folder were pointed at the new name: the venv's `bin/` scripts and `pyvenv.cfg`, the
  generated headers (`build/shared_fonts_config.h`, the iOS `Gen/` files and Xcode project, the iOS dependency build
  trees) and the app stamp. The runtime was relinked because the fonts header changed.
- `build_app.py --work` and the window's work folder default to `<repository root>/XCX_build` (was `XCX_build` next to
  the game file). README, `games/xcx/README.md` and the help text say so.

**Checked:** `python3 build_app.py "personal/<XCI>" -k personal/prod.keys -o "personal/Xenoblade Chronicles X.app"`
without `--work`: every step reused except the runtime (relinked, 7.9 s) and the app (a new output: assembled and signed
in 0.7 s, macOS's first check 118 s), 128 s in all. Run again, everything was reused (1.4 s). `codesign --verify
--strict` passes, the app's `--check` reports 1.0.1, and its only link is the RomFS link inside the bundle. The window's
sources compile. The ten files of the save profile have the same SHA-256 before and after. The game was not started.

### 2026-10-23: tidy-up, `--delete-work`, and the end of the folder consolidation

**Removed.** `scripts/make_res_patch.py` (Bayonetta 3 1.2.0's resolution patch maker), `gfx/nvn/names.txt`,
`gfx/tex/README.zh-CN.md` (and its link), the `nsw/` line of the root `.gitignore`, and `runtime/world_survey.c` /
`.h` (the TotK actor-survey stub; its calls in `input.c` and the sync-wait hook in `hle_nvn.c` went with it).

**Launcher.** The 60 / 120 fps control, fixed 900p, Improved LOD and Remove Film Grain are gone from the settings
window (the preset table, the rows, load / save, the missing-patch note and the launch code): they named exefs patches
that do not exist for this game. `DM_PRESENT_HZ` is now always 60, which is what the "Original (30 fps, ...)" presets
set before. `XCX_PATCHES` is no longer set by the launcher: a value from the environment
(`open --env XCX_PATCHES=<slug>,... <app>`) reaches `runtime/game_patches.c` unchanged, so `make patches` /
`prepare_patches.py` stays a working path for player patches. Settings keys older versions saved (`fps`, `fixed900`,
`lod`, `nograin`) are no longer read; the launcher was started with all four set and opened normally.

**Keys 3 and 4.** Key 4 (TotK's ultrawide toggle) called a stub that returned 0, so its binding, the stub and the
declaration were removed; `runtime_aspect_now` stays (the graphics layer reads it, weakly) and answers 0. Key 3 was
checked: it called `runtime_output_mode_cycle`, also a stub returning 0 (TotK's 2K picture modes need its output-size
patch, which this port does not have), so it did nothing and was removed too, with the unused
`runtime_output_size_current` / `runtime_output_res_toggle` stubs. MetalFX upscaling itself is unaffected: the
launcher's scaler setting turns it on through `TOTK_MFX_UPSCALE` / `TOTK_MFX_OUTPUT`. The shortcut box lists keys 1
and 2 only. Comments that pointed at the missing `aspect_patch.h` or at key 3 now say what holds in this port.

**Scripts.** `extract_exefs.py` and `extract_romfs.py` lost their TotK-only command lines (TotK title checks,
`program_nca`, `record_offset`) and are libraries now; every importer (`merge_romfs`, `identify_game`,
`extract_shared_fonts`, `extract_app_icon`, `extract_code`, `romfs_control`) imports only what is left. The Makefile's
`WORK` and the `--work` defaults of `prepare_runtime.py`, `prepare_patches.py` and `symbolize.py` are the root
`XCX_build`. Provenance comments that read as if this were TotK or Bayonetta 3 (`1.4.3`, "the current TOTK startup",
...) now say they come from the original MacNativeGames TotK code (Makefile, `merge_romfs.py`, `prepare_runtime.py`,
`services.c`, `threads.c`, `opus_codec.c`, `movie_host.c`, `audio_out.c`, `nvn_mtl.m`'s title list, `patch_nso.py`,
`equiv.py`); comments only, log strings unchanged.

**`--delete-work`.** `build_app.py --delete-work` deletes the work folder after the app (or IPA) is built and its final
check passed, never after a failure or a cancel (the deletion runs as a critical section, so a cancel arriving during
it waits). It refuses, before anything is built, the repository root, `personal/`, the home folder, any folder holding
the output, an input file or git-tracked files, and an existing non-empty folder with none of the build's markers; at
the end both markers (`logs/build-times.json`, `extracted/v101/extraction-manifest.json`) must be there. It prints the
files' size and the free space returned, notes that the app's APFS-cloned game data free their space only once the app
is deleted too, emits a `work-deleted` JSON event, and removes the `make` link in `~/Library/Caches` for a work path with
spaces. The builder window has a "Delete the work folder when the build finishes" toggle (off by default, remembered;
`XCX_BUILDER_TEST_DELETE_WORK=1` in test mode).

**Leftovers.** The older duplicate app `XCX_build/Xenoblade Chronicles X.app` (13 GB of APFS clones; the user plays
`personal/`'s) was unregistered and deleted. `XCX_build/build/shader-cache/rt-totk-native-v4-unverified` (6,151 files)
was merged into the per-user cache of the same chain, never overwriting: 6,149 files were already there and
identical, none was missing, and two differed: one `.variants` index and `pso_collected.tsv`. First the per-user
cache's 1,318 `.variants` and its `pso_collected.tsv` were copied to `XCX_build/analysis/cache-backup/`. The index got
the union of both JSON arrays, deduplicated by variant (1 entry added, no conflicting entry), written in the graphics
layer's own format (`totk_shader_rt.m`: compact `NSJSONSerialization` with sorted keys, which orders keys numerically:
all 2,343 existing indexes (1,025 + 1,318) round-trip byte for byte through the merge's writer). `pso_collected.tsv` got the source's
52 lines, none of which it had (334 -> 386 lines). Every index entry of the merged cache (1,319) has its `_b.metal`.
The cache still holds 8,924 files.

**Checked.** `make runtime launcher` builds clean with `-Werror` (the graphics layer recompiled: 21 objects, 14 s).
`py_compile` passes on every changed script and the builder's sources compile with `xcrun swiftc`. Then
`python3 build_app.py "personal/<XCI>" -k personal/prod.keys -o "personal/Xenoblade Chronicles X.app"`: the rewrite
checks ran again (45.6 s, both pass; the checkers' digests changed with the comments in `patch_nso.py` and
`equiv.py`), runtime and launcher were current from the `make` run, the app was assembled again (0.8 s) and checked
(2.5 s), 50.3 s in all; `codesign --verify --strict` passes and `--check` reports 1.0.1. The app was opened with
`XCX_PLAY=1` and scripted input: first frame after 12 s, Continue at 55 s, the field in Primordia at 110 s, closed at
115 s; 0 【红】 / FATAL lines, no shader translated and 0 pipelines built (cache reused), the launcher line reads
`patches none, present 60 Hz`, no `[input] user input`. The settings window could not be captured (no screen
recording permission for `screencapture -l`); the launcher binary no longer holds any of the removed labels.
`--delete-work` was tested on `XCX_build_deltest`, an APFS clone of `XCX_build` (`cp -cRp`, no space used): `--work
personal`, `.`, `~`, `games/xcx`, `games`, `~/Documents` and an output inside the work folder are refused before the
build; a build that failed (empty keys file, at identify) and one cancelled with SIGTERM during `prepare` left the
folder in place; a full build into a scratch app (127 s, macOS's first check 118 s) deleted it (its files took 28.2 GB,
all shared clones, so no space came back), and the scratch app still passed `codesign --verify --strict` and `--check`
before it was deleted. The ten files of the save profile have the same SHA-256 before and after everything.

### 2026-10-23: update 2.0.0 next to 1.0.1

The stage-0 study of 2.0.0 (`XCX_build/analysis/v200/FEASIBILITY-v200.md`, outside git) said go: `sdk`, `subsdk0` and
`rtld` are unchanged, `main` is a rebuild with the same imports, and the port holds no game address. This entry makes the
version a parameter, so a player builds either version, and updating means building again with the newer update.

**Before anything ran**, the save profile was copied (`cp -R`) to `personal/xcx-save-backups/profile-1.0.1-2026-10-23/`
and every one of its 10 files checked by SHA-256 against the original.

**The version table.** `scripts/app_bundle.py` `VERSIONS`: `v101` = 1.0.1 = Patch meta v65536, `v200` = 2.0.0 =
v196608 (the meta version is a release counter, 65536 a release, so an unknown one is named by number and release index,
not by a guessed display version). Everything takes the version from there: the expected file
(`assets/expected-<display>.json`; `expected-v2.0.0.json` is new), `extract_code.py`, `merge_romfs.py` and
`romfs_control.py` (`--version`, `--update`), `identify_game.py` (`game_version`, `display_version` on the Patch meta),
`prepare_runtime.py` / `prepare_patches.py` (`--version`; headers in `build/<v>/`, `analysis/runtime-layout-<v>.json`,
mods in `mods/<display>/`), `symbolize.py` (`XCX_VERSION`), the Makefile (`VERSION ?= v101`, `-DXCX_GAME_V200`;
`build/xcx-native-<v>`, `build/launcher-<v>`), `runtime/game_version.h` (selects 1.0.1 / 2.0.0 and the folder), the
launcher (`"rewritten/" TOTK_GAME_DIR`, the per-version binary in a work folder, `build/xcx-native` inside an app;
`--check` prints `game version 2.0.0 (v200)` and checks the new Info.plist key `XCXGameVersion`), and the iOS tools
(`build_ipa.py --version`, `XCX_VERSION_FLAGS` in `project.yml`, `main.m`'s message). The graphics objects, shader
tools and shader cache stay shared.

**The merge.** `merge_romfs.Patched` accepts the AES-CTR-Ex table ending at the indirect table (2.0.0) as well as at
itself (1.0.1); in the first case one plain AES-CTR row with the section's own generation covers the indirect table.
`index.json` records `version` and `aes_ctr_ex_covers`.

**`build_app.py`.** The version built is the update's: the XCI alone builds 1.0.1; `--update <2.0.0 NSP>` builds 2.0.0
and wins over the update inside the XCI; a base NSP or base-only file needs `--update` (1.0.1 or 2.0.0). Unsupported
versions, an update given as the game file, a base given as `--update` and a base-only file without an update are refused
with messages that name the file and the supported versions. The free-space check now runs after identification (for the
version's own image). When the output holds an app of another version it says so before the long steps: updating keeps
the saves (they are in the profile, not the app); once 2.0.0 has saved, the save may not load in 1.0.1; and it prints
the `cp -R` command that backs the profile up (going back to 1.0.1 warns the other way). App stamps and rewrite-check
records are per version (the old flat 1.0.1 record moves under `v101` by itself). The JSON progress: `plan` lists the
supported versions (the version is not known until the files are read), `start` (now after identify) carries `version`,
`display`, the replaced app's version and the backup command, and `done` carries the version. `--identify` reports what
the files are for the window. The iOS prerequisites now include the iOS platform (Xcode > Settings > Components, by an
available iOS runtime of the SDK's major version).

**The window.** Each chosen file shows what it is (`--identify`: "XCI: base v0 + update 1.0.1", "NSP: update 2.0.0",
or what is wrong with it). The update row is always there: optional for an XCI holding 1.0.1 ("a newer update NSP
(2.0.0) updates the game"), required for an NSP or a file with no update inside. A line says which version is built and
from which update. Over an older app it shows the save warning with **Back Up Saves Now** (a copy to
`profile-<version>-backup-<date>` next to the profile), and Build asks first (**Back Up Saves and Build** / **Build
Without Backup** / **Cancel**); the button reads "Update App to 2.0.0". For iPhone and iPad, an optional **Install on my
iPhone or iPad** section wraps `ios/tools/install_device.py`: device picker (devicectl, by name and model) with
refresh, the signing team or the steps to make an Apple Development certificate, notes on unlocking, Xcode's
"Preparing", the iOS platform component and the free Apple ID's 7 days, a game-data toggle (the IPA's own version, read
from its Info.plist), and progress for device, profile, sign, install and game data part N/M. `install_device.py`
gained `--progress json`, `--list-devices` and `--dry-run` (stops before the profile), and stops with the tool's own
words plus what to do, for example for "may need to be unlocked to recover from previously reported preparation errors".

**Inputs changed during the work.** Midway the user replaced the XCI with `Xenoblade Chronicles X Definitive Edition
Base Game.xci` (14,878,464,512 bytes). It holds the same base and 1.0.1 NCAs at the same offsets and the system update
with the six fonts (`--firmware` not needed). A first 2.0.0 merge that was running when the old file went away was
deleted and redone.

**Verified:**

- 1.0.1 merge with the new rule (stream through `verify_ivfc` to /dev/null; from both XCIs): `12c1bf46…`, 14,331,516,488
  bytes, 874,727 level-5 blocks, 14,279,799,456 / 79,831,976 bytes from base / update: equal to the pins. The table
  covers itself.
- 2.0.0 merge: `31afb6d9…`, 14,331,812,280 bytes, 874,745 blocks, 14,272,515,648 / 87,411,576, the table ends at the
  indirect table. Byte-flip control `romfs_control.py`: 2/2 caught for 1.0.1 and 2/2 for 2.0.0 (update data block
  9785, base block 0; the offsets are the same in both because the first update range is the same data at the same
  place, while the tables differ: 519 / 572 indirect rows, 1 / 36 AES-CTR-Ex rows).
- 2.0.0 build: `build_app.py "personal/<Base Game XCI>" -k personal/prod.keys --update personal/xcx200.nsp -o
  XCX_build/test-v200/...app`, 289 s (merge 34 s, data bundle signed 81 s, macOS's first check 117 s). Every value of
  `expected-v2.0.0.json` matched the build's own output: ExeFS (main `0a9dbf1f…`, npdm `75dc2bc1…`, sdk, subsdk0, rtld),
  build ID `EC4ED46B…`, the three rewrites (`fc092df7…`, `9d629869…`, `407f783c…`; re-derived from scratch by the
  build's rewrite step in a later run, 68 s), structck OK and equiv 0 divergent sites with 300/300 mutations caught per
  module (main 11,944 sites, sdk 15,078, subsdk0 9,787), the RomFS above, the base and update NCA records. `make prepare
  VERSION=v200`: 206,670 relocations, main PLT probe `0x1732500`, 53 files. Info.plist: 2.0.0, `XCXGameVersion` v200.
- 1.0.1 after the change: built again from both XCIs: code, rewrite, checks, fonts and data reused; the runtime relinked
  once for its new name; then 1.2-1.7 s; `--check` prints `ok: game version 1.0.1 (v101)`.
- 2.0.0 runtime: `xcx-native-v200 rewritten/v200 probe` passes (4,000 calls, 4 threads). Headless boot with a scratch
  profile: `game version 2.0.0`, `ENTER nnMain`, save storage mounted, Metal up, and the stop where a window is needed.
- 2.0.0 play (the test app, `open --env XCX_PLAY=1`, scripted J for Continue, 240 s limit): first frame 10 s, title with
  **Ver. 2.0.0** (`XCX_build/shots/v200/02_50s_title.png`), Continue into the field in Primordia
  (`03_110s_field.png`, `04_125s_field.png`), closed at 130 s. 0 【红】 and 0 FATAL lines, no host stop, so no new
  service or import needed an answer. Shader cache 8,924 files before and after: no shader translated. Clear sinking
  works as in 1.0.1 (32,894 clears sunk by frame 2700). No battle was reached in the scripted run.
- Saves: the game read `gamedata01/02/03`, `gamedataa`, `systemdata` and `socialdata`, and wrote nothing in that run;
  all 10 profile files have the same SHA-256 before and after, equal to the backup. So 2.0.0 loads a 1.0.1 save, but
  whether a save 2.0.0 writes still loads in 1.0.1 is **not known**: no save was written to test it.
- Matrix through `build_app.py` (test containers made from the XCI's own NCAs in a scratch folder and deleted afterwards):
  XCI alone -> 1.0.1 (full build); XCI + 2.0.0 NSP -> 2.0.0 (full build); base-only NSP + 2.0.0 NSP -> 2.0.0 (full
  build, the rewrite re-derived; the merge streamed: `31afb6d9…`); base-only NSP + 1.0.1 NSP -> 1.0.1 (full build into the
  1.0.1 test app; merge streamed: `12c1bf46…`); base-only NSP alone, the update NSP as the game file (with and without
  `--update`), the base as `--update`: refused, each with its message; an unsupported version (v131072, simulated in the
  identify report, as no such file exists here): "update version v131072 (release 2) is not supported; this port runs
  1.0.1 (v65536), 2.0.0 (v196608)".
- The window compiles (`xcrun swiftc`). Test-hook captures in `XCX_build/shots/builder-v200/`: XCI + 2.0.0 over the 1.0.1
  test app (versions, "Builds version 2.0.0", the save warning, the update sheet), the base-only file (update required,
  Build disabled), base + 1.0.1 and base + 2.0.0, the update as the game file (flagged, nothing built), the iOS states
  (platform, prerequisites with 11 checks, the install section with the paired iPhone and the team) and the no-certificate
  state (`XCX_BUILDER_TEST_NO_TEAM=1`). `install_device.py --list-devices`, `--dry-run` and two error cases ran with
  `--progress json`. No IPA was built and nothing was installed or signed.
- `py_compile` passes on every changed script. The 2.0.0 test app was unregistered and deleted.

**Not done / open.** Whether 1.0.1 reads a save 2.0.0 has written (needs a save made in 2.0.0, then 1.0.1 run on a copy
of the profile). No battle in 2.0.0. The window's file pickers were not clicked by hand (the hook sets the fields). The
install section's Install button was not pressed. The old `build/xcx-native`, `build/launcher` and the three generated
headers directly in `build/` are 1.0.1 leftovers of the old layout; nothing uses them now.


### 2026-10-23: iPhone startup crash in `nninitStartup` (60 GiB address region), and text entry on iOS

**Crash.** On an iPhone 15 Pro Max (iOS 27.2, free Personal Team), 2.0.0 stopped with SIGSEGV right after
`AllocateAddressRegion size=f00000000 result=1803`. The game's `nninitStartup` asks `nn::os::AllocateAddressRegion` for a
fixed 60 GiB (main 2.0.0 +0x13e3fb0, `mov x0,#0xf00000000`; the region allocator at +0xb9b350 does not check the
result). The SDK's `VammManager` hands regions out of the alias region (GetInfo 2/3 minus 28), after its own ~1 GiB
page-table area (+0x3fe00000), so on the Mac's 64 GiB alias the region is at alias+1 GiB. The iOS layout gave only
16 GiB of alias. The game touches about 7 GiB of the region (Mac logs: highest page at +0x1c2a40000).

**What iOS allows** (new `[totk-mem] VA` probe lines in log.txt): without extended virtual addressing the map ends at
2^39. There is 64 GiB free at 0x70_0000_0000 and about 1.3 GiB in small gaps below it. The largest single reservation is
64 GiB. The profile grants only `increased-memory-limit` (checked in the signed profile).

**Fix (`runtime/services.c`, iOS only).** The alias default is 64 GiB, shrinking in 256 MiB steps down to 61.25 GiB
(the 60 GiB region + VammManager's 1 GiB + slack). Below that, startup stops with a message instead of a null write.
The iOS heap cap is 512 MiB (the game sets no heap). Stack+heap then take 1.25 GiB, and the alias region gets 62.75 GiB:
`alias 0x7050000000+0xfb0000000`. The reservation is PROT_NONE and pages are committed only when mapped, as before. The
Mac path is unchanged.

**Text entry on iOS.** `swkbd_host.c` now calls `runtime_front_text_input` on iOS too. `frontend_ios.m` shows an alert
with one text field (the system keyboard; OK is disabled below the minimum length, and the maximum length is enforced
while typing).

**Verified on the device.** `RETURN nninitStartup`, the constructors, `nnMain`, the opening movies, the title screen,
and character creation. The name was entered through the alert (`keyboard: "Please enter a name." ... -> "<the typed name>"`).
The footprint was about 2.0 GB after 3 minutes, with no jetsam.

### 2026-10-23: iPhone "closes after a few minutes": the test harness, not the game (and a memory readout)

**Report.** On the iPhone 15 Pro Max (iOS 27.2), the app closed after a few minutes of play. Documents/log.txt ended
in the middle of `AllocateMemoryPages` lines with no signal or FATAL line.

**Termination reason.** No JetsamEvent named XCX. The only new one (21:00:47) killed `searchd` at its own limit, and
XCX was not in its process list. The three `XCX.cpu_resource` reports (20:47, 20:52, 21:03) all say "Action taken:
none". Neither run ended in a crash report. Both "closed" sessions were the timed console runs of the previous fix.
Their devicectl output ends with `App terminated due to signal 14.` (`XCX_build/logs/ios/console-fix1.txt`,
`console-fix2.txt`). Signal 14 is SIGALRM: the `perl -e 'alarm N; exec …' xcrun devicectl … --console` wrapper's
alarm went to devicectl, which passed it on to the app. The runs lasted about 2 and 3 minutes, and the player was
playing during them, so the app seemed to close by itself. Neither memory, a watchdog nor the GPU was involved.

**Memory measured on the device** (new readout below; the limit is footprint + available, about 6.1 GB, so
`increased-memory-limit` is in effect; the signing profile carries it). Run of 16 minutes, launched without `--console`, played
by the user (two trips to the background):

| t | footprint | available | Metal allocated | guest mapped |
|---|---|---|---|---|
| 11 s | 1603 MiB | 4540 MiB | 2063 MiB | 2184 MiB |
| 2 min | 1855 | 4288 | 2142 | 2149 |
| 5 min | 2018 | 4125 | 2238 | 2157 |
| 10 min | 2029 | 4114 | 2247 | 2158 |
| 13.7 min | 1913 | 4230 | 2250 | 2171 |
| 16 min | 2118 | 4025 | 2327 | 2190 |

The footprint levels off at about 2.0-2.1 GB, about 4 GB under the limit. The process was still running at the end,
and it was left running for the player. The previous fix's 3-minute run (`[nvn] 上屏` lines) reads 1030 → 2048 MiB, the same
start-up rise, not a leak. The thermal state reaches "serious" (2) within a minute and stays there: the CPU average is
72-93% (the cpu_resource reports).

**Change (`ios/Sources/main.m`, iOS only by file).** `lifecycle_observe()` (called right after log.txt opens) writes
an `[xcx-mem]` line every 10 s: phys_footprint, os_proc_available_memory, the Metal device's currentAllocatedSize
(`dm_mtl_l3_sample`), the guest memory committed (`runtime_guest_committed`) and the thermal state. It writes the same
line on a memory warning, on resign-active, background, foreground and will-terminate, and on a thermal change. It
logs `[xcx] terminated by signal N` for SIGTERM, SIGHUP, SIGINT and SIGALRM before re-raising. A jetsam kill
(SIGKILL) cannot be caught, so a log that stops after an `[xcx-mem]` line with little `available` points to jetsam,
and a log that ends in `terminated by signal 14` points to a timed harness. The Mac runtime is unchanged: `make runtime
VERSION=v200 WORK=../../XCX_build` reports nothing to do.

**For later test runs.** Do not time a run that someone plays with `alarm` around `devicectl --console`. Launch
without `--console` and poll `Documents/log.txt` (`devicectl device copy from`) and `devicectl device info processes`
instead.

Logs: `XCX_build/logs/ios/run-mem1/` (timeline.txt, log.txt), `XCX_build/logs/ios/diag2/` (the reports).

Still open: the high CPU load and the "serious" thermal state (30 fps with long frames); Metal allocations of about
2.25 GB with 300,000 texture re-uploads in 16 minutes (`贴图重传累计`); no reaction to memory warnings yet. None
came, so the texture-copy eviction (`pkg_evict_sweep`, below 600 MB available) never ran.

### 2026-10-23: 60 fps patch (experimental, off by default)

**Where the cap is.** Not in the present path. The game never calls `nvnWindowSetPresentInterval` (its window keeps
interval 1 from the builder; the log line "game sets its present interval" never appears), and with `DM_PRESENT_HZ=120`
it still ran at 33.2 ms a frame (run r2). The game paces itself (static analysis with capstone over the original main,
`XCX_build/analysis/fps/tools`; runtime confirmation below):

- At start-up it calls SetVsyncCount(2) (2.0.0 main+0x13a2fd8, called once, from main+0x13db540 `mov w0, #2`; 1.0.1:
  +0x13b2d18 from +0x13eb280; all 1.0.1 sites are 0xfd40 further on). N lives at main+0x1d943a0.
- Every frame ends in a frame limiter (main+0x13a9a50, reached from the frame end main+0x13d9870 through a virtual call):
  a pure spin on the system tick until `display period (1/60 s) x N x 0.997` has passed since the frame began.
  2 x 16.67 x 0.997 = 33.23 ms, the measured frame time p50 of every 30 fps run. The spin keeps the main thread busy for
  about half of each frame (one reason for the iPhone's CPU load).
- The frame time the game simulates with, GetFrameTime() (main+0x13a250c, 13 callers), is `period x N` (N = 0: x 2), a
  constant: the game assumes every frame lasts N/60 s.

**Is the logic tied to frames?** To the nominal frame time, not to the frame count or the real time:

- With only N = 1 (an experimental one-word patch, run r6) the field ran at 44 fps and the player walked 6.4 m/s against
  8.8 m/s at 30 fps (8.8 x 44 / 60 = 6.45): the game simulated 1/60 s a frame and ran at 0.73x. Walking speed comes from
  the camera position of each frame (new diagnostic `XCX_CAMLOG=1`, below), in steady 1 s windows while W is held.
- GetVsyncCount() (main+0x13a25a4) has 4 callers. main+0x251e0 builds a step of 1/(60/N) but clamps the game's own
  measured frame time (sys+0x226c, main+0x13d6108) to one or two steps. main+0x138a40 and main+0x927e10 use a fixed
  step of 1/(60/N) a frame (and a 30/fps ratio): these run at their nominal rate, so slower than normal while the game
  is below 60 fps with the patch. Which systems they are was not found.
- 77 sites build the float 1/30 (0x3d088889); the 12 read are conversions of 30 fps frame counts into seconds, not
  per-frame increments. Not all were read.
- The time of day is a float at clock object +0x30 (object main+0x1fefc38; GetTime main+0x1e7e34: hour = T/1800 mod
  24, minute = T/30 mod 60). In the test save (chapter 1, Primordia at night) it is frozen at T = 1200 (00:40) in every
  run, with and without the patch, so the clock's speed could not be measured. Two counters of the same object advance at
  the same rate either way (`peek`, below; r10 / r11: 1.061 / 1.074 a second and 69,549 / 69,610 a second).

**The patch** (`runtime/game_patches.c`, slug `60fps`, built in; 2.0.0 and 1.0.1). Two sites and two veneers, each word
checked first (a mismatch stops the start):

| Site (2.0.0 / 1.0.1) | Original | Patched |
|---|---|---|
| vsync count, +0x13db540 / +0x13eb280 | `52800040` mov w0, #2 (then `97ff1ea5` bl SetVsyncCount, checked) | `bl` veneer 1: `adrp x0, page; ldr w0, [x0, #4]; ret` |
| GetFrameTime, +0x13a250c / +0x13b224c | `a9be7bfd` stp x29, x30, [sp, #-0x20]! (next two words checked) | `b` veneer 2: `adrp x16, page; ldr w17, [x16, #8]; cbz w17, 1f; ldr s0, [x16]; ret; 1: stp x29, x30, [sp, #-0x20]!; b GetFrameTime+4` |
| veneers, +0x1735050 / +0x1744d90 (40 bytes) | the zero padding between main's text and its read-only data (checked) | the two veneers |

The rewrite leaves all these words as they are (compared with `rewritten/<v>/main.patched.bin`). The page is the 16 KiB
writable page the loader already reserves after main (TotK's real-time page): +0 the frame time in seconds, +4 N, +8 the
mode. With the patch on: N = 1 (the limiter ends at 16.6 ms) and mode 1, GetFrameTime returns the mean of the last 4
intervals between presents, each held to 1/60..1/20 s (`runtime_frame_step_update`, at every `nvnQueuePresentTexture`;
gaps over 0.25 s start the mean again; "framestep <ms>" in the input file pins it). Below 20 fps the game slows, as the
original does below 30. Every 1800 frames a line reports the mean (`[xcx] 60 fps frame step: ...`).

How it is switched:

- Mac: the launcher's new **Frame rate** row, "30 (original)" (default) / "60 (experimental)", saved as `frame_rate`, not
  part of the presets; 60 adds `60fps` to `XCX_PATCHES`. `XCX_FRAME_RATE=30|60` from the environment wins for one start.
  At 30 the runtime patches nothing (`[xcx] game patches: none`), as before. The present base stays `DM_PRESENT_HZ=60`
  with the game's interval 1, so 60 frames a second are presented at 60 Hz.
- iPhone / iPad: code cannot be written on the device, so `build_ipa.py` now exports main's text with the sites patched
  (`XCX_PATCHES=60fps XCX_FPS60=0`; `export-ios.log`: `main ... patched_words=12`) and the device only checks the words
  ("embedded at build time"). The new Settings entry **Frame rate** (`XCX_FRAME_RATE`, 30 by default) sets
  `XCX_FPS60`; at 30 the page holds N = 2 and mode 0, so the game runs its own limiter and its own GetFrameTime code.
  A launch environment value wins (`devicectl ... -e '{"XCX_FPS60":"1"}'`).
- Terminal: `XCX_PATCHES=60fps`; `XCX_FPS60=0` keeps the sites but runs the original 30 fps (r16: 33.2-33.3 ms p50).

New diagnostics, off by default: `XCX_CAMLOG=1` (`nvn_mtl.m`, `GAME_XCX`): the camera position of each frame from the
scene block, with the host time, `=2` also the whole block once a second; input-file commands `peek <addr> <words>`
and `memsnap <path> <addr> <len> ...` (`input.c`; addresses may be `main+<hex>`), which read memory and write nothing.

**Verified** (MacBook Air M1 8-core GPU, 16 GB; 2.0.0; Continue into Primordia at night; dev runtime from `XCX_build`
on a scratch copy of the profile, logs in the session scratchpad):

| Run | Setting | Field frame rate | Walking (W held, steady 1 s windows) |
|---|---|---|---|
| r1, r5 | off | 30.1 fps, frame p50 33.23 ms, GPU p50 17.8 ms | 8.80 / 8.81 m/s |
| r6 | N = 1 only | 44 fps | 6.26-6.54 m/s (game at 0.73x) |
| r7 | `60fps` | 50.9 fps over the first 1800 frames, then 46.7, 41.2 | 8.70 / 8.87 / 8.87 m/s at 41-46 fps |
| r15 | `60fps` | 51.1, 52.2, 46.8, 43.1 fps (1800-frame means); 30.6-57.3 per 150 frames | 8.80 m/s in the 51 fps window |
| r3 | `60fps`-equivalent (N = 1 only, the user played) | 54.9 fps mean, 45-60 | (void: user input) |

- The M1 is GPU-bound: at 60 fps targets the GPU needs 18-20 ms a frame (one in 17 ms at best), so the field stays at
  about 45-57 fps. The fanless Air also heats up: the submission thread's clock (`翻译细项` line, `平均主频`) fell from
  2.99 GHz in the first runs to 0.9-1.5 GHz after about an hour of runs, and within one run from 2.75 to 1.0 GHz in
  2.5 minutes with the patch on. The later runs (r9-r14) are throttled at both settings (the 30 fps baseline then
  missed 30 too) and are not used above.
- Title screen and menus: no visual breakage at 60 fps (captures of the title, the field, the party menu and battles;
  the HUD, minimap, damage numbers and the battle palette are as at 30). A battle starts and runs; auto-attack timing
  was not measured reliably (the two battles compared started differently).
- Self-contained app (`build_app.py ... --update xcx200.nsp -o XCX_build/test-fps/...app`, 2.2 min): `[launcher] frame
  rate 60 (XCX_FRAME_RATE)`, `patches 60fps`, the patch applied; it stayed on the title (the RomFS was verified once for
  the new app; `TOTK_AUTOLOAD` does not find this game's saves). The player's profile was byte-identical before and
  after (10 files, SHA-256, against `personal/xcx-save-backups/profile-2026-10-23-before-fps`). The test app was deleted.
- 1.0.1: built (`make runtime VERSION=v101`) and booted headless with `XCX_PATCHES=60fps` to `nnMain`:
  `game patch 60fps (1.0.1): on ... vsync count main+0x13eb280, frame time main+0x13b224c`. Not played.
- iPhone 15 Pro Max (iOS 27.2), 2.0.0 IPA rebuilt and installed with `install_device.py` (Documents kept; the save
  folder backed up first to `personal/xcx-save-backups/iphone-2026-10-23-before-fps`), launched with `XCX_FPS60=1`:
  `game patch 60fps (2.0.0): on ... (embedded at build time)`. The user played this session for about 90 s with a
  controller (`[input] user input`), so it is not a scripted measurement: the title ran at 60 fps (frame p50 16.6 ms,
  GPU 8-10 ms), the field at 52-58 fps for about a minute (first 1800 frames: mean 17.4 ms, 57.4 fps), then 36-43 fps
  (frame p50 23-28 ms; next 1800 frames 45.9 fps) as the phone reached thermal state 2 (serious) about 60 s after the
  save loaded; the submission thread went from 3-4 to 11 ms a frame while the GPU stayed at 10-12 ms, so the phone is
  CPU-bound and throttled, not GPU-bound. The footprint was 1.9 GB.
  A second launch (`XCX_FPS60=1`, `TOTK_INPUT_SCRIPT` pressing A at 75 / 95 s; `XCX_build/logs/ios/fps2/`, 8 minutes) was
  also played by the user (`[input] user input` twice), so again not a clean measurement: 1800-frame means 58.8, 51.0,
  50.5, 59.5 (x5, a light scene: GPU 2-3 ms), 45.5, then 50.5-51.2 fps for the last 4 minutes in the field (frame p50
  19.1-19.9 ms, submission 7.0-7.3 ms, GPU 7.6-7.8 ms); thermal state 1 after about 1 minute, 2 (serious) after 7; no
  frame held at 50 ms in that stretch, footprint 1.3-1.8 GB.

**Risks / not done.** The two fixed-step subsystems above run slow below 60 fps; the time of day could not be checked
at this point of the story; cutscenes (in-engine and movies), Skells, cities, swimming and UI animation speed were not
compared; a battle's auto-attack interval was not measured. The game's busy-wait limiter still spins (now for less of
each frame). On the M1 Air and the iPhone the higher frame rate heats the device faster, which brings the frame rate
down again after a few minutes. 1.0.1 was not played with the patch.

### 2026-10-24: `fill_shaders.py` on a device

On an iPhone 15 Pro Max (iOS 27.2), the game skipped the draws whose shaders the IPA did not carry: the player character
was drawn without their outfit. `ios/tools/fill_shaders.py` pulled 201 requests, translated them, compiled device
metallibs and pushed the pack. After a restart the character was drawn dressed. This was the tool's first run against a
device.

- A sideloaded app (here `build_app.py`'s install step with a free Apple ID) has the team in its bundle id. The install
  log prints it (`bundle org.macnativegames.xcx.gvrm33qnkk`). The default `org.macnativegames.xcx` does not match, so
  pass `--bundle-id` (or `XCX_BUNDLE_ID`). `xcrun devicectl list devices` gives the `--device` id.
- Without Apple's Metal Toolchain the tool still works, but the pack has MSL source only, which the device compiles at
  start. `xcodebuild -downloadComponent MetalToolchain` installs it, and `--with-done` rebuilds the packs already sent.

### 2026-10-24: shared shader list

The iPhone cannot translate shaders while it plays, so the IPA used to carry only what the Mac had met. Builds now find
every shader in the player's own game files, and a list of identifiers shared by players says which setups are worth
preparing. Player guide: `docs/sharing-shaders.md`.

- **List:** `assets/shader_list.tsv` holds identifiers only (shader keys, canonical deps, flags), never game data;
  185 rows were seeded from the Mac's caches and the 201 variants of the first device run. `build_app.py` downloads the
  newest one (`scripts/fetch_shader_list.py`: validated, cached, then the cached copy, then the project's; `--offline`
  skips the download).
- **Build step `shaders: prepare`** (`scripts/prepare_shader_seed.py`): the inventory found 12,429 shaders in 6,818 files
  in 18 s; preparing 12,427 took 61.8 s; an unchanged rebuild reuses them in 0.8 s. The IPA carried 13,962 variants and
  grew from 86 to 159 MiB.
- **Sharing:** the game notes new shaders in `shader-list-contribution.txt` (Mac: Application Support; iPhone:
  Documents). The launcher asks at 50 new and then every 500; the builder window offers "Share N new shaders"; with
  `XCX_IOS_DEVICE` set an iOS build copies the phone's file to the Mac (`ios/tools/shader_contrib_watch.py pull`).
- **Workflow** (`.github/workflows/shader-list.yml`, `scripts/process_shader_issue.py`): issue text is read only by the
  script, never run; it may only touch the list, its log and per-issue records. Rules: account at least 7 days old;
  one accepted share per account per UTC day; at most 2,000 new shaders per share; an issue adds only on the day it was
  first added. One command undoes an issue (Run workflow with its number).
- **Bugs fixed along the way:** `compile_seed.py` temp names raced when two compiles ran at once; `build_ipa.py` wrote
  its seed stamp before the compile finished, so a failed compile looked done on the next run.
- Not done: the list's pipelines (phase 2), and a run of the workflow on a live issue.

### 2026-10-24: XCNative folders and bundle ID

The project's own name replaces MacNativeGames in the player's Library and in the bundle ids. Credits and links to the
original MacNativeGames project, and the entries above, are unchanged.

- **Folders:** `~/Library/Application Support/MacNativeGames/XCX` -> `~/Library/Application Support/XCNative/XCX`
  (profile and saves, shader cache, `shader-list-contribution.txt`, `app-romfs-record/`, `game-slot/`, `input.txt`),
  `~/Library/Logs/MacNativeGames` -> `~/Library/Logs/XCNative`, and the caches (`xcx-builder`, `ios-signing`,
  `xcx-work-*`) now in `~/Library/Caches/XCNative`.
- **Migration, once:** the launcher at start (`use_library` in `app/launcher.m`, before the settings window reads the
  data folder) and `build_app.py` before it touches the Library (`app_bundle.migrate_library`) apply the same rules.
  Only the old folder exists: it is renamed to the new place (same volume, nothing copied) and one line is logged.
  Both exist: the new one is used and the old one left untouched, nothing merged or replaced, and that is logged. The
  move fails, or a game process (`xcx-native*`) is running (it writes its saves by the path it started with): the old
  folder stays in use for that run and is logged; the next start tries again. Nothing is deleted. The old caches are
  not moved; they are made again. The builder window shows the old profile path while only that exists. The other
  tools (`contribution.py`, `shader_contrib_watch.py`) use the old folder too while only it exists, so they never
  create an empty new folder that would hide the saves. They resolve the folder at each use. The launcher looks again
  after its settings window closes (a build may have moved the folders meanwhile); a rename that fails because another
  process moved the folder first uses the new one. A broken link at the new path counts as nothing there, for the
  launcher, the Python side and the window alike. `build_app.py` moves only after its arguments are checked (`--help`
  or a wrong one moves nothing). Rebuild or delete apps built before this change: an older app would write to the
  MacNativeGames folder again.
- **Bundle ids:** `org.macnativegames.xcx` -> `org.xcnative.xcx` (Mac app, iOS project, `fill_shaders.py` and
  `shader_contrib_watch.py` defaults), sideloaded `org.xcnative.xcx.<team id, lowercase>` (`install_device.py`), the
  window `org.xcnative.xcx.builder`. The launcher and the window take over their saved settings from the old id while
  the new one has none.
- **iPhone / iPad:** a new bundle id is a new app with an empty sandbox. After installing the new id,
  `install_device.py` (`carry_over`) looks for the old app (`org.macnativegames.xcx.<team>`, then
  `org.macnativegames.xcx`) and copies its `Documents/save`, `shader-cache`, `shader-list-contribution.txt`,
  `shader-requests` and its Settings preferences file to the new app with `devicectl device copy from/to
  --domain-type appDataContainer`; not GameData (`--game-data` pushes it from the Mac). It copies only when the new
  app's `Documents/save` came back empty or plainly not found; any other answer skips with a warning. When both old ids
  are installed, the one with saves is used and the other is named in the log. After the copy it reads a save file
  (`account.uid`, else the first file) back from the new app and compares it. Only then does it write
  `Documents/migrated-from.txt`, so a copy that did not complete or check out is tried again at the next install, with
  a warning that says how to copy `save` by hand (Finder or the Files app). Each item is logged, and a failed copy is a
  warning. The old app and its data are never deleted. The new id counts as one more App ID for a free Apple ID (about
  10 per 7 days), and the new app needs the 14 GB game data again while the old one keeps its copy: check free space,
  and delete the old app only after the new one shows the saves.
- **Checked:** `python3.14 -m unittest discover -s games/xcx/tests` (new `test_library_migration.py`: only old ->
  moved; both -> new used, old untouched; move failure or a running game -> old used; the device carry-over against a
  faked devicectl); the launcher's `move_folder` in a harness on temporary folders (the same four cases, and a fake
  `xcx-native-v101` process detected); `make launcher` with `-Werror` for both versions; the window compiled with
  build_app.py's `swiftc` command; `make runtime`. Not run against the owner's Library or a device.

### 2026-10-25: 60 fps: the timed B-button prompt

**Found** (static analysis of main 2.0.0 with capstone; session notes `fps60-investigation.md`, Bug 2): with the 60 fps
patch the timed B-button prompt (the "Soul Challenge") ran twice as fast. It is a HUD class (constructor main+0x5c56c4,
panes `mc_ShrinkRing`, `mc_JudgeRing`, `mc_Perfect` ...). It reads the ring's lifetime N in 30 fps frames from BDAT
`BTL_BtnChallengeLv` (murmur3 0x52f917eb at main+0x5c5c08; byte column 0x25efa387, rows 1..5) and keeps speed = 30/N
(+0x138[level], copied to +0x120 at the start). The ring (+0x11c) starts at 30.0 and the update (main+0x5c6208, called
every frame from main+0x7877f8) takes speed off it each frame (main+0x5c6280 `ldr s1, [x19, #0x120]`, then `fsub`);
below 0 the prompt fails. The judge on B (main+0x5c64c0, a leaf) checks ring + speed (main+0x5c64fc `ldr s1, [x0,
#0x120]`, then `fadd`): Perfect for 6.9..12, Good for 0..6.9 and 12..15, else Failed. Neither reads GetFrameTime, so the
ring lasted N frames: N/30 s as shipped, N/60 s at 60 fps. The ring picture follows the same value.

**The patch** (`runtime/game_patches.c`, sites 3 and 4 of `60fps`, written by `apply_fps60` with the other two; each word
checked first, a mismatch stops the start):

| Site (2.0.0 / 1.0.1) | Original | Patched |
|---|---|---|
| ring step, +0x5c6280 / +0x5c5870 | `bd412261` ldr s1, [x19, #0x120] (the words before and after checked) | `b` veneer 3 |
| judge, +0x5c64fc / +0x5c5aec | `bd412001` ldr s1, [x0, #0x120] (checked likewise) | `b` veneer 4 |
| veneers 3 and 4, +0x1735080 / +0x1744dc0 (84 bytes, after veneers 1 and 2) | zero padding (checked) | `ldr s1, [xN, #0x120]; adrp x16, page; ldr w17, [x16, #8]; cbz w17, 1f; ldr s2, [x16]; fmul s1, s1, s2; fmov s2, #30.0; fmul s1, s1, s2; 1: b site+4` |

In mode 1 the step becomes speed x frame time x 30, so the ring lasts N/30 s at any frame rate, and the judge's window,
which is in ring units, keeps its length in time. Mode 0 (30 fps, `XCX_FPS60=0`, iOS "30") runs the shipped step.
x16, x17 and s2 are not used by the update or the judge before they are written. 1.0.1: the class's whole code
(main+0x5c56c4..0x5c6560 in 2.0.0) is the same 0xa10 bytes earlier, instruction for instruction except PC-relative
operands (adrp/add/bl), and its update is called from main+0x798008. The frame-counted sound cue of the same class
(+0x114, `subs #1`) still counts frames; at 60 fps it plays earlier.

New log line, after the patch's line: `[xcx] game patch 60fps (2.0.0): timed B-button prompt on (step x frame time x 30);
ring step main+0x5c6280, judge main+0x5c64fc, veneers main+0x1735080..+0x17350d4`. iOS: build_ipa.py's export now
reports `main ... patched_words=32` (was 12).

**Checked:** `scripts/verify_fps60_qte_patch.py` (new; Unicorn on `rewritten/<v>/main.patched.bin`, words parsed from
game_patches.c) for 2.0.0 and 1.0.1: N = 20, 30, 45, 60; shipped at 30 fps the ring runs out after N (or N + 1, a ring of
exactly 0.0) frames; shipped at 60 fps in half the time (negative control); patched in mode 0 equals the shipped code
bit for bit at 30 and 60 fps; patched at 20, 30, 45, 60 and 120 fps the ring runs out within one 30 fps frame plus one
frame of the reference, and a press at any millisecond gets the reference verdict except within one 30 fps frame plus
one frame of a window edge. `--exported` against the text the runtime wrote (`export-ios`, both versions,
`XCX_PATCHES=60fps XCX_FPS60=1`): the 20 words match. `tests/test_fps60_qte_patch.py` (encodings, sites, padding);
`make runtime` for both versions. **Not checked in the game**: the ring's speed and the Perfect/Good window at 60 fps
against 30 still need a play test (start a Soul Challenge at both rates and time the ring).

### 2026-10-25: acquire sync fenced like real NVN (single-frame flicker at 60 fps)

**Found** (owner's A/B play test, 60 fps, New Los Angeles hangar): flickering garbage frames by default, little to none
with `TOTK_ACQ_SYNC=old`, none with `DM_EXP_SUBMIT_WAIT=1`. `nvnWindowAcquireTexture` marked the acquire sync done at
once (a TotK optimisation: the present copy is already ordered on the one Metal queue). Xenoblade X waits on that sync on
the CPU before it rewrites per-frame memory, so it overwrote data an earlier frame's GPU work still read. A GPU-to-GPU
hazard was ruled out: `probe-gpu-order` shows the encoders' queue barriers order submissions (with them removed,
`TOTK_PROBE_NEGATIVE=2`, all 8 trials read stale bytes).

**The fix** (`third_party/d2r_gfx/gfx/nvn/hle_nvn.c`, new `acq_fence.h`): every `nvnQueuePresentTexture` records the
newest submission (Metal fence, or the translation thread's submit token) and the image it showed. By default the
acquire sync waits for the submission of the present that replaced the image on screen, as the hardware does: the
display releases an image only at the flip to the next one, and that flip needs the next frame's GPU work done. With
Xenoblade X's 2 swapchain images this equals `old`, the mode the play test showed free of the flicker. `TOTK_ACQ_SYNC`:
unset = this (`next`); `tex` = the image's own last present, one frame earlier than the hardware (one more frame of
overlap; experimental, a faster mode to try later); `old` = newest submission at the acquire; `now` = the previous
immediate signal. Without a record (first frames, `nvnWindowInitialize` again, another window) the sync takes the
newest submission, never "done at once". The values are submissions already made, so waits end; past 16 presents the
oldest kept (later) fence stands in. New log lines: the mode once at the first acquire (`[nvn] 取图同步：...`); the
300-frame `[nvn] 帧间隔` line adds acquires, fenced acquires and CPU waits on acquire syncs with a timeout (count, of
them timed out, average, longest; polls with timeout 0 are not counted).

**Removed**: the `TOTK_GPU_ORDER` event wait across submissions in `nvn_mtl.m` (added earlier the same day, shown
unnecessary) with its `flag gpu_order`, read hooks and stats. Kept: the diagnostic count of CPU replay reads of
unfinished GPU writes (`g_gw_cpu_stale`, a line after the uniform snapshot stats when non-zero), and `probe-gpu-order`
without the event wait.

**Checked:** `make runtime` (no warning on a changed line); iOS `-fsyntax-only` of `hle_nvn.c` and `nvn_mtl.m`; new
`probe-gpu-acq-sync` (13 checks with real empty submissions: fence per mode, first frames / window re-init / another
window take the newest, ring overflow, completion through `nvnSyncWait`, an unreached fence times out and is counted,
a poll is not); `probe-gpu-order`, `-ubo-snapshot`, `-arg-epoch`, `-ub-rename`, `-copy-alias`, `-dispatch-chain`,
`-vertex-streams` pass; `tests/test_acq_fence.py` and the other unit tests pass. `probe-gfx` crashes in
`dm_nvn_probe_copy_marks` (`pin_scan`), code this change does not touch. **Not checked in the game**: the flicker and
the frame rate at 60 fps need a play test (default; later `TOTK_ACQ_SYNC=tex` as the faster experiment).
