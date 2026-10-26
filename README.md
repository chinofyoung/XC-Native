# Xenoblade Chronicles X: Definitive Edition, native on Apple silicon

An early, work-in-progress native Mac port of your own copy of **Xenoblade Chronicles X: Definitive Edition**, update
**1.0.1 or 2.0.0**.
The port lives in [`games/xcx`](games/xcx).

Landing page: <https://chinofyoung.github.io/XC-Native-Site/>

This repository is a fork of [MacNativeGames](https://github.com/ly05010419/MacNativeGames). It builds on that project's
native ports of Tears of the Kingdom, Breath of the Wild and Bayonetta 3 and on their shared runtime, and is released
under the same MIT license. This fork holds only the Xenoblade Chronicles X port; the other games are in the original
repository.

## What it is

It is not an emulator. The game's own ARM64 code runs directly on Apple silicon:

- The code modules are rewritten ahead of time, only where macOS requires it, then loaded and relocated.
- The Switch system services the game asks for are answered by a small host.
- The game's NVN graphics calls are rebuilt on Metal. Its Maxwell shaders are translated to Metal shaders the first time
  they are used.

No CPU is emulated: there is no interpreter, JIT or dynamic binary translation. The port started from Bayonetta 3's
port in the original repository, and `games/xcx` keeps its own copy of the runtime, rewriter, graphics layer and scripts.
Besides `games/xcx`, the repository holds only the vendored Ryujinx shader translator sources (`vendor/ryujinx`) that
the prebuilt shader translator is built from.

## Legal

**You must own the game.** Use this project only with a copy of Xenoblade Chronicles X: Definitive Edition that you
bought, and with the keys dumped from your own Nintendo Switch. We do not help anyone obtain keys or game files.

This is an independent, non-commercial project. It is not affiliated with, endorsed by, or sponsored by Nintendo or
Monolith Soft. Nintendo, Nintendo Switch and Xenoblade Chronicles are trademarks of Nintendo.

The repository contains no game content and distributes none: no game program, art, text, audio, shaders, keys or
saves. Everything the game needs is made on your own Mac from your own files. What the repository does hold is the code
of the port and the information needed to check your files (the hashes in
[`games/xcx/assets/expected-v1.0.1.json`](games/xcx/assets/expected-v1.0.1.json) and
[`expected-v2.0.0.json`](games/xcx/assets/expected-v2.0.0.json)).

The app and the work folder you build hold or use the game, so they are for your own use only. **Never share the built
app, the work folder or anything in it.**

## Status

Early. The game reaches the title screen, character creation and gameplay in Primordia:

- Characters are drawn and lit, in the field and in battle (the first battle was played).
- The field and battle HUD and menu text are drawn.
- Audio plays (the game's Wwise output through Core Audio).
- The opening cutscene's White Whale renders correctly.
- Saves write, and Continue loads them.
- A controller (a DualSense was used) and the Mac keyboard both work.
- `python3 build_app.py` turns your XCI into a self-contained, double-clickable app with a settings window, in one
  command (`make app` builds a development app for work on the port).

Only those areas have been checked so far. Tested on a MacBook Air with M1 (8-core GPU, 16 GB), where the game runs at
its own 30 fps and uses about 17 ms of GPU time per frame.

| Stage | Goal | State |
|---|---|---|
| 0 | Feasibility | done |
| 1 | Code and data out of your dump, code rewritten for Apple silicon | done |
| 2 | The runtime boots the game to its `nnMain` | done |
| 3 | First frame and the title screen | done |
| 4 | Picture, audio, input, saves | in progress |
| 5 | Performance, shaders, the app | in progress |

The full work log, with what was found, what was changed and how each step was checked, is in
[`games/xcx/CHANGELOG.md`](games/xcx/CHANGELOG.md).

## Requirements

- A Mac with Apple silicon and **macOS 26** or later.
- Xcode (for `clang`, `llvm-objdump` and the Metal frameworks), or at least the Xcode command line tools plus Xcode's
  `llvm-objdump`.
- [Homebrew](https://brew.sh) with `opus`, `libvpx` and Python 3.14: `brew install opus libvpx python@3.14`.
- `git` (part of the command line tools): the build fetches SPIRV-Cross at a pinned commit. The first build also needs
  network access for the build's Python packages ([`games/xcx/requirements.txt`](games/xcx/requirements.txt), plus
  `unicorn` for the rewrite check `equiv.py`; Unicorn only checks the rewritten code and is not part of the port).
- Your game, base `0100453019AA8000` (v0) with its update `0100453019AA8800` in version **1.0.1** (v65536) or
  **2.0.0** (v196608), as
  - one **XCI** holding the base and 1.0.1, as the game card does: builds 1.0.1;
  - that XCI plus the **2.0.0 update NSP** (`--update`): builds 2.0.0 (the update you give wins over the one inside the
    XCI; 2.0.0 contains everything 1.0.1 changed, so 1.0.1 is not needed);
  - or a base **NSP** (or a base-only XCI) plus the 1.0.1 or 2.0.0 update NSP. NSPs are decrypted with their common
    ticket; for an NSP without one, pass your `title.keys` (`--title-keys`).
  The version built is always the update's. Other versions are refused with a message naming the supported ones.
- Your `prod.keys`.
- The six Switch system fonts (`shared-fonts`). The game's own partitions do not carry them, but the XCI's system update
  does, and the build takes them from there. For NSPs, pass your firmware's NCA files with `--firmware <folder>`.
- About 16 GB free for the work folder (the merged game data alone is 14.3 GB). On the same volume the app costs no
  extra space: its game data are APFS clones of the work folder's.

## Build and run

The examples keep the XCI and `prod.keys` in `personal/` at the repository root, where git ignores them. Any other
place works; keep game files, work folders and apps out of the repository's tracked files.

There is one work folder, `XCX_build/` at the repository root (next to `build_app.py`, ignored by git). It is the
default of `build_app.py`, of the window and of the developer commands below, wherever the game file is, so every build
reuses the same steps. The app goes next to the game file unless `-o` says otherwise.

### Versions, updating and your saves

1.0.1 and 2.0.0 can both be built from the same work folder: each version keeps its own `extracted/<v>`,
`rewritten/<v>`, `build/<v>/` headers, `build/xcx-native-<v>` and game data bundle (`v101`, `v200`), so building
either one again reuses its steps. The second version's game data takes another 14.3 GB.

**To update**, build again with the newer update to the same app (the same `-o`, or the default next to the game file):

```sh
python3 build_app.py "personal/<game>.xci" -k personal/prod.keys --update personal/<2.0.0 update>.nsp
```

The app is replaced. **Your saves are not in the app** (they are in
`~/Library/Application Support/XCNative/XCX/profile`), so 2.0.0 continues from them; a 1.0.1 save loads in
2.0.0. **The other direction is not guaranteed:** once 2.0.0 has saved, that save may not load in 1.0.1 again. The build
says when it replaces an older app and prints the command that copies the profile aside, for example
`cp -R ".../XCX/profile" ".../XCX/profile-1.0.1-backup-<date>"`; the window offers **Back Up Saves** before it builds.
To go back to 1.0.1, rebuild without `--update` and put that backup back in place of `profile`. The app records its
version (`CFBundleShortVersionString`, `XCXGameVersion` in its Info.plist; `--check` prints it). Exefs mods are per
version (`mods/1.0.1/`, `mods/2.0.0/`): main's build ID differs.

### The window (easiest)

From the repository root:

```sh
python3 build_app.py --gui
```

This opens **Xenoblade Chronicles X Builder**, a small native window:

- Choose your game file (the XCI, or a base NSP), your `prod.keys`, and optionally an update NSP, `title.keys` and
  a firmware folder. Each file shows what it is, read from inside it (for example "XCI: base v0 + update 1.0.1",
  "NSP: update 2.0.0"), and the window says which version the build makes. The update is optional for an XCI that holds
  1.0.1: choosing the **2.0.0 update NSP** there **updates the game**. For a base NSP, or a file with no update inside,
  the update is required. A file of the wrong kind (an update chosen as the game file, another game, an unsupported
  version) is flagged and the build stays disabled.
- When the output already holds an app of another version, the window says what replacing it means for the saves, and
  building asks first (**Back Up Saves and Build**, **Build Without Backup**, **Cancel**).
- The output defaults to `Xenoblade Chronicles X.app` next to the game file. Pick *iPhone and iPad (experimental)* to
  build the IPA instead (see below). *Advanced* chooses another work folder than `XCX_build/` at the repository root.
- The *Prerequisites* panel checks this Mac and lists anything missing, with the command that installs it.
- *Delete the work folder when the build finishes* (off by default, remembered) runs the build with `--delete-work`
  (see below): a rebuild or update then starts from scratch, about 8 minutes.
- **Build App** shows each step with its time and the log. **Cancel** stops cleanly, and the next build continues from
  the last finished step. At the end, **Open App** or **Show in Finder**. If the build stops, the window names the step
  and the file.

The window remembers your choices. It never shows or logs key values. The first time, `--gui` compiles the window from
[`games/xcx/builder`](games/xcx/builder) with `xcrun swiftc` into `~/Library/Caches/XCNative/xcx-builder` (a few
seconds). The Xcode command line tools are enough, and nothing ready-made is downloaded. The window runs the same
`build_app.py` as the command below.

### One command

From the repository root:

```sh
python3 build_app.py "personal/Xenoblade Chronicles X Definitive Edition.xci" -k personal/prod.keys
```

This uses the work folder `XCX_build/` at the repository root and makes the app `personal/Xenoblade Chronicles X.app`
(next to the game file); `--work <folder>` and `-o <path>.app` choose other places.

For 2.0.0, add the update: `--update "personal/<2.0.0 update>.nsp"` (see [Versions](#versions-updating-and-your-saves)).
For NSPs: `python3 build_app.py <base.nsp> -k prod.keys --update <1.0.1 or 2.0.0 update.nsp> --firmware <firmware folder>`
(add `--title-keys title.keys` for NSPs without a common ticket; the firmware folder is needed for the system fonts
unless an earlier build already extracted them into the work folder).

- `python3 build_app.py --help` lists every option. `python3 build_app.py --check-requirements` (add `--platform ios`
  for the IPA) checks this Mac without building anything and prints a fix for anything missing.
- The build checks the Mac first (macOS version, Apple silicon, the developer tools, Homebrew's `opus` and `libvpx`,
  Python 3.14), then recognises the game by the title IDs and versions inside the files, never by their names: another
  game, the update given as the game, a base-only file without `--update`, or another version stops it with a message.
- Every step is checked against the version's `games/xcx/assets/expected-<version>.json` (1.0.1 or 2.0.0), so a
  damaged dump stops at the first wrong file: the code (every ExeFS block verified), the rewrite for Apple silicon
  and its two checks (structure, and semantics in an emulator), the system fonts, the merged RomFS (all six IVFC levels),
  the shader translator's SHA-256 and SPIRV-Cross's pinned commit. Key values are never printed.
- Each step is timed. A second run reuses what is already done and correct and takes seconds.
- The app is **self-contained**: the code, fonts and game data are inside it (the 14.3 GB RomFS as APFS clones, so no
  extra space on the same volume), it is ad-hoc signed, and it can be moved, also to `/Applications`. The work folder
  can be deleted afterwards; keep it to rebuild in seconds.
- `--delete-work` deletes the work folder once the app (or IPA) is built and its final check passed, never after a
  failure or a cancel. It deletes only a folder `build_app.py` made (its `logs/build-times.json` and
  `extracted/<v>/extraction-manifest.json`), and never the repository root, `personal/`, your home folder, a folder
  holding the output, an input file or tracked files; anything else is refused before the build starts. It prints what
  it frees. The app's game data are APFS clones of the work folder's, so that space (about 14 GB) comes back only once
  the app is deleted too. The next build or update starts from scratch (about 8 minutes).

The shader translator comes ready-made (`games/xcx/prebuilt/macos-arm64/totk_xlate`, checked against its SHA-256), so
the build needs no .NET. Its sources are in `games/xcx/tools/totk_xlate` and `vendor/ryujinx`; see
[`games/xcx/prebuilt/macos-arm64/README.md`](games/xcx/prebuilt/macos-arm64/README.md) for how to rebuild it.

### Play

Double-click `Xenoblade Chronicles X.app` in Finder, or `open` it. A settings window comes first; **Play** starts the
game.

- The default preset is "Original (30 fps, window)"; "Original (30 fps, full screen)" is the other one. Both run the
  game's own 30 fps and dynamic resolution without MetalFX upscaling.
- The window also chooses the monitor, window or full screen, the window size, the full-screen output resolution, the
  scaler (MetalFX or plain), an interface mod and the FPS overlay. There is no frame-rate or internal-resolution
  setting: the code patches they would need do not exist for this game.
- The first start checks the whole RomFS once (the first frame takes about 10 s); later starts reuse that record.
- Shaders are translated the first time the game meets them and kept in the shader cache, so the first minutes of a new
  install stutter more than later ones.

### Developer build (make)

`build_app.py` runs the targets of [`games/xcx/Makefile`](games/xcx/Makefile) (`prepare`, `runtime`, `shader-tools`,
`launcher`, `icon`). For work on the port they can be run by hand, from `games/xcx`, after the extraction steps. They
use the same `XCX_build/` as `build_app.py`, which already holds everything up to `make prepare`.

```sh
cd games/xcx
python3.14 -m venv ../../XCX_build/venv
../../XCX_build/venv/bin/pip install -r requirements.txt unicorn
PY=../../XCX_build/venv/bin/python
WORK=../../XCX_build
XCI="../../personal/Xenoblade Chronicles X Definitive Edition.xci"
KEYS=../../personal/prod.keys
$PY scripts/extract_code.py "$XCI" --keys $KEYS --output $WORK/extracted/v101/exefs
$PY scripts/merge_romfs.py "$XCI" --keys $KEYS --output $WORK/extracted/v101/romfs
for m in sdk subsdk0 main; do
  DM_RULESET=native DM_PRIVATE_GATES=0 $PY third_party/d2r/patch_nso.py $WORK/extracted/v101/exefs/$m $WORK/rewritten/v101 $m
done
$PY scripts/prepare_modules.py $WORK/extracted/v101/exefs --output $WORK/extracted/v101/elf
$PY scripts/extract_shared_fonts.py --keys $KEYS --xci "$XCI" --output $WORK/extracted/firmware/shared-fonts
make prepare WORK=$WORK PY=$PY   # tables, RomFS index, fonts; every input checked against assets/expected-v1.0.1.json
make app WORK=$WORK PY=$PY GAME="$PWD/$XCI" KEYS="$PWD/$KEYS"
```

These are the 1.0.1 steps. For 2.0.0, use `v200` in the paths, give the scripts `--update <2.0.0 update.nsp>
--version v200`, and pass `VERSION=v200` to every `make` target (`VERSION ?= v101`); the outputs go to
`build/v200/`, `build/xcx-native-v200` and `build/launcher-v200`.

The extraction scripts take `--update <update.nsp>` (and `--title-keys`) for a base NSP; `extract_shared_fonts.py`
takes `--firmware <folder>` instead of `--xci`. The rewrite checks are in [`games/xcx/README.md`](games/xcx/README.md).

`make app` builds a **development app** (about 3 MB) at `$WORK/Xenoblade Chronicles X.app`: it does not contain the
game but runs `build/xcx-native-<v>` from the work folder its Info.plist names, so the work folder must stay where it is.
`GAME` and `KEYS` must be absolute paths; they are used only for the app's icon. `make install WORK=$WORK` copies it to
`/Applications` or `~/Applications`. The game can also be run from a terminal in the work folder: `make boot WORK=$WORK`
from `games/xcx`, which writes its log to `$WORK/logs/boot.log`. See [`games/xcx/README.md`](games/xcx/README.md) for
the switches a terminal run needs.

### iPhone and iPad (experimental)

`--platform ios` builds an unsigned IPA for sideloading. **It is experimental.** An
iPhone or iPad cannot translate the game's shaders while it plays (there is no translator process on iOS), so the build
translates them ahead of time: every shader it finds in your own game files, plus the ones players have shared (see
[Sharing shaders](#sharing-shaders)), plus what your Mac translated while you played the Mac app. The first iOS build
after this took about 28 minutes once (it compiles the shaders for the phone; later builds reuse them). It runs at a
smooth 30 fps on an iPhone 15 Pro Max in the first area, with the full picture there. A shader nobody has met yet is
still skipped on the phone until it is shared or filled in (below); nothing past the first area has been tested on iPhone.
The iOS Simulator cannot run it: the graphics layer uses Metal 4, which the Simulator SDK does not have.

Requirements:

- Everything the Mac build needs (above), plus Xcode 26 or later with the iOS SDK, and `brew install xcodegen cmake`.
  The first build downloads and compiles Opus and libvpx for iOS, so it needs network access.
- **iOS / iPadOS 27** on an iPhone 14 or newer (A15 or later), or an iPad with an A15 chip or later. Checked on an
  iPhone 15 Pro Max and an iPhone 17 Pro Max on iOS 27; iPad and older iPhones are untested. On iOS 26 the app closes
  right after opening: the game needs one continuous block of about 61 GB of memory addresses below 512 GB (address
  space, not RAM), and iOS 26 gives an app at most 51 GB in one piece there (its `log.txt` ends with
  `FAIL: reserve guest stack, heap and alias regions`). iOS 27 gives apps the room. Update to iOS 27; no reinstall
  needed.
- Optional: Xcode's Metal toolchain (`xcodebuild -downloadComponent MetalToolchain`). With it the build compiles the
  carried shaders for the device. Without it they stay Metal source, and the device compiles each one the first time it
  is used.

Build (steps 1-6 are the Mac build's and reuse the same work folder):

```sh
python3 build_app.py "<game folder>/Xenoblade Chronicles X Definitive Edition.xci" -k <prod.keys> --platform ios
```

This writes `Xenoblade Chronicles X.ipa` next to the game file (`-o` picks another `.ipa` path); add `--update <2.0.0
update.nsp>` for 2.0.0, as for the Mac. The IPA is about
159 MB (86 MB before the shared list), because it holds the game code, the RomFS index, the system fonts and the
shaders, but not the 14.3 GB game image. `--ios-seed-cache <folder>` adds another Mac shader cache to carry. By default the build carries the
cache in `~/Library/Application Support/XCNative/XCX/shader-cache` and the work folder's own caches.

**In the window:** pick *iPhone and iPad (experimental)*. The output becomes an `.ipa`, and the prerequisites add Xcode
with the iOS SDK, xcodegen and CMake, and the iOS platform (Xcode › Settings › Components). **Build IPA** builds it.
The optional *Install on my iPhone or iPad* section below it then:

- lists the paired devices by name and model (connect with a cable, unlock, tap Trust; the refresh button looks again);
- shows your signing team, or, when there is no Apple Development certificate, the steps to make one (Xcode › Settings
  › Accounts › add your Apple ID › Manage Certificates › + › Apple Development);
- copies the game data of the IPA's own version (on by default), and shows each step (device, profile, sign, install,
  game data part N of M) and any error in the tool's own words, with what to do. Keep the device unlocked; if Xcode's
  Devices window shows it as *Preparing*, let that finish first ("may need to be unlocked to recover from previously
  reported preparation errors" means exactly this).

Install it with your own Apple ID or a sideloading tool:

- With Xcode and a cable (what the window runs): add your Apple ID in Xcode › Settings › Accounts (a free Personal Team
  works), connect and trust the device, then run
  `python3 games/xcx/ios/tools/install_device.py "Xenoblade Chronicles X.ipa" --device "<device name>" --game-data <work folder>/extracted/<v101 | v200>/romfs/romfs.bin`
  (the version the IPA was built for). `--list-devices` only lists devices and teams, `--dry-run` checks everything
  and stops before signing, and `--progress json` gives one JSON event a line.
  It signs the app as `org.xcnative.xcx.<team>`, installs it, and copies the game image once into the app's
  Documents/GameData in 1 GiB parts. Later installs skip the copy while the device holds the same image. A free Apple ID
  signs for 7 days and a paid membership for a year. Run the command again to renew; your saves are kept. On first use,
  trust your Apple ID under Settings › General › VPN & Device Management.
  If the device already has the app under the old name (`org.macnativegames.xcx.<team>` or `org.macnativegames.xcx`),
  the install goes over it under that name: its saves and game data stay and no extra app slot is used (a probe of the
  app's Documents finds it; a locked phone hides it, so keep the phone unlocked). A free Apple ID allows 3 sideloaded
  apps at a time; with 3 already, installing a new app fails with "maximum number of apps".
  Until 2026-10-24 the app was `org.macnativegames.xcx.<team>`. When this tool does not find that old app (or
  `--bundle-id` is given), iOS treats the new id as another app, so it appears next to the old one with empty Documents. The first install of the new id copies the old app's saves, shader cache,
  shader list contribution, shader requests and Settings choices over (not the game data, which `--game-data` copies),
  unless the new app already has saves. It reads one save file back from the new app before it counts the copy as
  done; if that fails it says how to copy the `save` folder by hand in Finder or the Files app, and the next install
  tries again. The old app and its data are left alone. Another sideloading tool does not copy anything; move the
  files in Finder (the device › Files) if you need them.
  The new ID counts as one more App ID for a free Apple ID (the limit is about 10 per 7 days). The new app needs the
  14 GB game data again (`--game-data`) while the old app keeps its own copy, so check the device's free space first,
  and delete the old app only after the new one shows your saves.
- With another sideloading tool: install the IPA and keep its entitlement (`increased-memory-limit`). Then get the game
  data onto the device: in Finder, select the device, open Files, and drag
  `<work folder>/extracted/<v101 | v200>/romfs/romfs.bin` onto Xenoblade Chronicles X. The app moves it into its GameData folder
  on the next start. If the game starts before the copy is complete, it says so and waits for the next start.

The game data stays in the app's Documents when you reinstall or update the app. It is excluded from iCloud backups. The
first start hashes it once against the build's checksum and keeps a record. Saves and the shader cache are also in
Documents. The log is `log.txt` there, which you can read in the Files app (On My iPhone › Xenoblade Chronicles X).

Shaders the device misses are listed in `shader-list-contribution.txt` and saved as requests in Documents. Share the
file (see [Sharing shaders](#sharing-shaders)); to fix the gaps before the list has them, with the
device connected, `python3 games/xcx/ios/tools/fill_shaders.py --work <work folder> --device <id>` translates them on
the Mac and sends them to the device, and later IPA builds carry them too. The game merges them on its next start. On
an iPhone 15 Pro Max it filled in the clothes of the player character. `xcrun devicectl list devices` gives the device
id. A sideloaded app has the team in its bundle id (the install log prints it, e.g. `org.xcnative.xcx.gvrm33qnkk`):
pass it as `--bundle-id` (or `XCX_BUNDLE_ID`). Without Apple's Metal Toolchain the tool sends MSL source only, which the
device compiles at start; `xcodebuild -downloadComponent MetalToolchain` installs it, and `--with-done` rebuilds the
packs already sent.

## Sharing shaders

The game notes the shaders it meets that the shared list does not have yet (identifiers only, never game data), and the
launcher and the builder window offer to send them as a GitHub issue. A robot adds them to the list, and every player's
next build prepares them, which matters most on iPhone and iPad. Builds download the newest list on their own; `--offline`
skips that. The guide for players, with file locations, is
[docs/sharing-shaders.md](https://github.com/chinofyoung/XC-Native/blob/main/docs/sharing-shaders.md).

## Controls

Controllers that macOS recognizes are given to the game as one Switch controller; a DualSense was used in testing.
The Mac keyboard uses physical key positions of a US layout:

| Key | Switch | | Key | Switch |
|---|---|---|---|---|
| W A S D | left stick | | arrow keys | right stick |
| J | A | | K, Space | B |
| I | X | | U | Y |
| Q / E | L / R | | Option / Shift | ZL / ZR |
| F T H G | d-pad left / up / right / down | | Z / C | left / right stick press |
| Return | + | | Tab, Esc | − |

Extra keys:

- **1** shows or hides the on-screen overlay.
- **2** cycles MetalFX frame interpolation: off, 30+30, half the refresh rate, unlimited. It works, but on an M1 it costs
  more than it gains: with 30+30 the game itself drops to about 23-27 fps. It is off at start.
- Keys **3** and **4** do nothing: Tears of the Kingdom's picture-mode and ultrawide keys are not part of this port.

## Where things are

- Saves, account and pseudo device id: `~/Library/Application Support/XCNative/XCX/profile`, for both kinds of
  app. On its first start a development app copies them from `$WORK/user-data` (the profile of terminal runs) if that
  exists, so it continues from the same save. The originals are not changed, and after that the two are separate.
- Shader cache: the app's in `~/Library/Application Support/XCNative/XCX/shader-cache/`, so the signed app stays
  read-only; a development app's in `$WORK/build/shader-cache/`, shared with terminal runs.
- RomFS check record and the input file for diagnostic commands: `~/Library/Application Support/XCNative/XCX/`
  (the app's record in its `app-romfs-record/` folder).
- Log: `~/Library/Logs/XCNative/xcx.log` (the run before: `xcx.previous.log`). Terminal runs with `make boot`:
  `$WORK/logs/boot.log`.
- Until 2026-10-24 these folders were `~/Library/Application Support/MacNativeGames/XCX` and
  `~/Library/Logs/MacNativeGames`. The next build or app start moves them to the new place once (a rename, nothing is
  copied). If both exist, the new one is used and the old one is left as it is. If the move fails, or the game is
  running, the old folder stays in use and the next start tries again. The log says what happened (`[launcher]
  library:` lines). Old caches in `~/Library/Caches/MacNativeGames` are not moved; you can delete that folder.
  Rebuild or delete apps built before this change: an older app would write to the MacNativeGames folder again.

## Known issues and what has not been checked

- **Not checked yet:** cities (New Los Angeles), Skells, cutscenes, day-time lighting, water, menus beyond character
  creation, and a New Game through character creation with the current build.
- Frame interpolation (key 2): besides its cost on an M1, characters and enemies moving on their own and rain streaks
  ghost in the generated frames, and labels attached to enemies are half a frame ahead. Camera cuts have not been tested.
- MetalFX spatial upscaling has not been checked with this game and is off in the presets.
- No online features: the network is offline. The name filter accepts any name.
- About a hundred NVN functions the game imports are not implemented. One that is called stops the game with its name in
  the log; none was reached up to the first battle.
- The Mac app has no Metal cache warm-up yet (the original project ships one for Tears of the Kingdom): a shader the
  build did not prepare is translated the first time it is drawn.
- The NSP path (a base NSP with an update NSP) has been checked with an update NSP only; the port was played from the
  XCI.
- The iPhone / iPad build (`--platform ios`) is experimental; it runs at a smooth 30 fps on an iPhone 15 Pro Max in the
  first area, with the full picture there. A shader neither found in your game files nor on the shared list is skipped,
  and nothing past the first area has been tested on iPhone; see [iPhone and iPad](#iphone-and-ipad-experimental).

## How it works

The general method is described for Tears of the Kingdom in the original
[MacNativeGames](https://github.com/ly05010419/MacNativeGames) repository (`docs/how-it-works.md` there); the same
architecture applies here. What was changed for this game, and why, is in
[`games/xcx/CHANGELOG.md`](games/xcx/CHANGELOG.md) and [`games/xcx/README.md`](games/xcx/README.md).

## Acknowledgements

- **[MacNativeGames](https://github.com/ly05010419/MacNativeGames)** (MIT): the runtime, rewriter, graphics layer and
  app this port is built from.
- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT) developed this way of running Switch games natively.
- **Ryujinx** (MIT): its shader translator (`vendor/ryujinx`), compiled ahead of time into
  `games/xcx/prebuilt/macos-arm64/totk_xlate`.
- **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)** (Apache-2.0), fetched at a pinned commit and compiled
  during the build.
- **libopus** and **libvpx** (BSD) from Homebrew: audio and the game's movies.

## License

MIT (see [LICENSE](LICENSE)). Third-party code keeps its own license: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Contributions: [CONTRIBUTING.md](CONTRIBUTING.md).
