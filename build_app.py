#!/usr/bin/env python3
"""Turn your own copy of Xenoblade Chronicles X: Definitive Edition (update 1.0.1 or 2.0.0) into a native Mac app, in one
command (or, experimentally, an unsigned iPhone / iPad IPA with --platform ios).

    python3 build_app.py <game.xci | base.nsp> -k <prod.keys> [--update <update.nsp>] [--firmware <folder>]
                         [-o <output .app | .ipa>] [--work <folder>] [--title-keys <title.keys>] [--platform macos|ios]
                         [--delete-work]

Supported: Xenoblade Chronicles X: Definitive Edition, base 0100453019AA8000 (v0) with its update 0100453019AA8800 in
version 1.0.1 (v65536) or 2.0.0 (v196608) (games/xcx/scripts/app_bundle.py VERSIONS), as
  - one XCI holding the base and the 1.0.1 update (as the game card does): builds 1.0.1, nothing else is needed;
  - the XCI (or a base NSP / base-only XCI) with --update <the 2.0.0 update NSP>: builds 2.0.0 (the update given wins
    over the one inside the XCI; 2.0.0 is cumulative over the base, so 1.0.1 is not needed);
  - a base NSP (or a base-only XCI) with --update <the 1.0.1 update NSP>: builds 1.0.1.
The version built is the update's. The game is recognised by the title IDs and versions inside the files
(games/xcx/scripts/identify_game.py), never by the file name; other titles and other versions are refused with a message
naming what the file is and the versions that are supported.

Updating: build again with the newer update to the same output (-o, or the default next to the game file). The app is
replaced; the saves are not in the app (~/Library/Application Support/XCNative/XCX/profile), so the new version
continues from them. A save that 2.0.0 has loaded and saved may not load in 1.0.1 again: the build says so when it
replaces an older app and prints the command that backs the profile up. Both versions can be built from one work folder
(extracted/<v>, rewritten/<v>, build/<v> stay apart), so going back to 1.0.1 is a rebuild that reuses its steps. NCAs of an NSP are
decrypted with the NSP's common ticket, or, when it has none (or a personalized one), with --title-keys <title.keys>.

Steps, each one checked against games/xcx/assets/expected-<version>.json (1.0.1 or 2.0.0), so a damaged dump or another version stops the
build at the first wrong file (a different dump of the same version is accepted: main.npdm by Nintendo's ACID signature
or, re-signed by a dump tool, once the code modules match; shared fonts by a verified, valid BFTTF structure):
  1. code: the update's ExeFS (games/xcx/scripts/extract_code.py: FS header, hash table and every block verified), the NSO
     segments checked and inventoried (prepare_modules.py), the three code modules rewritten for Apple silicon
     (games/xcx/third_party/d2r/patch_nso.py) and the rewrite checked twice: structure (structck.py) and semantics in
     an emulator with random states and mutation controls (equiv.py)
  2. fonts: the six system shared fonts, from the system update the XCI carries (its update partition) or from
     --firmware <unpacked firmware NCA folder> (needed for an NSP); every NCA level and each font verified
     (extract_shared_fonts.py)
  3. data: the base RomFS and the update's BKTR patch merged into one 14.3 GB image, all six IVFC levels verified
     (merge_romfs.py)
  4. prepare: the runtime's generated tables, RomFS index and fonts config (make prepare VERSION=<v>:
     scripts/prepare_runtime.py)
  5. runtime: the game binary of that version (make runtime VERSION=<v>)
  6. shader tools: the prebuilt shader translator, checked against its SHA-256, and SPIRV-Cross at its pinned commit,
     compiled with clang (make shader-tools); then every shader of the game translated ahead for its usual case and
     the cases the shared shader list names (games/xcx/scripts/prepare_shader_seed.py, docs/sharing-shaders.md; the
     list downloaded from GitHub and cached, or with --offline the cached or the project's one)
  7. app: the launcher and the icon from the game's own control data (make launcher icon), then a self-contained app:
     the code, fonts and RomFS index cloned into it, the RomFS image as a data bundle signed once in the work folder and
     cloned into Contents/Helpers (APFS clones: no extra space on the same volume), ad-hoc signed, registered, and run
     once in its check-only mode so that macOS's first-run scan happens now and not at the player's first start.
The Makefile in games/xcx stays the developer path (make prepare runtime app VERSION=<v>): this script runs the same
targets.

Every intermediate file is in the work folder (default: XCX_build at the repository root, next to this script, wherever
the game file is; the app goes next to the game file); a second run reuses what is already done and correct. The app
needs no work folder once built and may be moved, also to /Applications. --delete-work deletes the work folder after
a successful build (only a folder build_app.py made; never on a failure or a cancel), so a later build starts from
scratch (about 8 minutes). Saves, the shader cache, the RomFS check
record and the log go to the user's Library (~/Library/Application Support/XCNative/XCX,
~/Library/Logs/XCNative/xcx.log), so the signed app stays read-only. Folders from before 2026-10-24
(~/Library/Application Support/MacNativeGames/XCX, ~/Library/Logs/MacNativeGames) are moved there once, by the build
or the app's first start (app_bundle.migrate_library); the old caches are made again. Nothing from the game is in this repository;
everything is made from your files on your Mac. Key values are never printed.

Needs: macOS 26 or later on Apple silicon, the Xcode command line tools (Xcode for llvm-objdump), Homebrew with
    brew install opus libvpx python@3.14
and network access on the first run (the build's Python packages, SPIRV-Cross).
--platform ios (EXPERIMENTAL) makes an unsigned IPA for sideloading instead (default "<game file folder>/Xenoblade
Chronicles X.ipa"): steps 1-6 as above (the Mac runtime exports the patched code for the device), then
games/xcx/ios/tools/build_ipa.py: device Opus / libvpx (CMake, network once), the Xcode project (xcodegen), the build,
and the IPA. It needs Xcode 26 or later with the iOS SDK, xcodegen and CMake (brew install xcodegen cmake). The IPA
carries no game image: the 14.3 GB RomFS is installed once into the app's Documents (ios/tools/install_device.py
--game-data, or Finder's file sharing). A phone cannot translate shaders: the IPA carries the shaders prepared in step 6
and the ones this Mac has translated, and a draw needing a case nobody has shared yet is skipped.

    python3 build_app.py --gui

opens a window that does the same without the command line (games/xcx/builder: a small SwiftUI app, compiled with
xcrun swiftc on first use into ~/Library/Caches/XCNative/xcx-builder, and again when its sources change). The
window runs this script with --progress json: one JSON object a line on stdout (the plan, with the supported versions;
the start, with the version being built and the version of the app it replaces; the steps, each start and end with its
time; the error with the step it stopped at; the output), the human output on stderr; SIGTERM then cancels the
build cleanly (the work folder is resumable). --check-requirements [--platform ios] reports every requirement with
what to do about the missing ones (also with --progress json), for the window's prerequisites panel.
--identify <game> [--update <nsp>] -k <prod.keys> [--out <app>] reports what the files are (base, update version) and
the version of the app at the output, without building (one "identified" event a file with --progress json), for the
window's version labels.
"""
import argparse
import contextlib
import glob
import hashlib
import json
import os
import platform
import plistlib
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
GAME = REPO / 'games/xcx'
sys.path.insert(0, str(GAME / 'scripts'))
import app_bundle   # noqa: E402  standard library only: the app's name, Info.plist and the files it carries
import contribution   # noqa: E402  standard library only: the shaders this Mac's game met that the shared list lacks
import fetch_shader_list   # noqa: E402  standard library only: the newest shared shader list, cached
from shader_list import ShaderList   # noqa: E402

PINS = {v: app_bundle.expected(v) for v in app_bundle.VERSIONS}   # games/xcx/assets/expected-<display>.json
BASE_TITLE = PINS[app_bundle.DEFAULT_VERSION]['title_id']          # 0100453019AA8000 (the same in every version)
UPDATE_TITLE = PINS[app_bundle.DEFAULT_VERSION]['update_title_id']  # 0100453019AA8800
# The version being built, chosen by identify() from the update's Patch meta version (select_version): the work
# folder's version folder (v101 / v200: extracted/<v>, rewritten/<v>, build/<v>), its pins and its display version.
VERSION = None
EXPECTED = None
DISPLAY = None
SUPPORTED = app_bundle.supported()               # '1.0.1 (v65536), 2.0.0 (v196608)'


def select_version(version):
    global VERSION, EXPECTED, DISPLAY
    VERSION, EXPECTED = version, PINS[version]
    DISPLAY = EXPECTED['display_version']
GAME_NAME = 'Xenoblade Chronicles X: Definitive Edition'
# Other games a file may turn out to be, for the message when it is not this one (title IDs of the base games)
OTHER_TITLES = {'0100F2C0115B6000': 'The Legend of Zelda: Tears of the Kingdom',
                '01007EF00011E000': 'The Legend of Zelda: Breath of the Wild', '01004A4010FEA000': 'Bayonetta 3',
                '0100E95004038000': 'Xenoblade Chronicles 2', '0100FF500E34A000': 'Xenoblade Chronicles: Definitive Edition',
                '010074F013262000': 'Xenoblade Chronicles 3'}
WORK_NAME = 'XCX_build'                          # the default work folder: <repository root>/XCX_build
SPIRV_CROSS_COMMIT = 'aa217aeb6c9f0ace7a0ab233b28807edf45eb165'   # the Makefile's SPIRV_CROSS_COMMIT
# The Python packages of the build: games/xcx/requirements.txt, plus unicorn for the rewrite's semantic check (equiv.py)
EXTRA_PACKAGES = ['unicorn==2.1.4']
TOOL_PATHS = ['/opt/homebrew/bin', '/usr/local/bin']
LSREGISTER = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
APP_NAME = app_bundle.APP_NAME
GB = 1 << 30

# Nintendo's public ACID signing key (generation 0): a dump's main.npdm is genuine when this key verifies its ACID
# signature, which is the check the Horizon loader itself makes before it starts a title (Atmosphere
# libraries/libstratosphere/source/fssystem/fssystem_crypto_configuration.cpp). From the original project's build_app.py.
NINTENDO_ACID_MODULUS = bytes.fromhex(
    'DDC8DDF24E6DF0CA9EC75DC77BADFE7D238969B6F206A20288E15591ABCB4D50'
    '2EFC9D9476D64CD8FF10FA5E930AB457AC51C71666F41A54C2C5043D1BFE3020'
    '8AAC6F6FF5C7B668B8C9406B42AD1121E78BE9750186E4489B0A0AF87FE887F2'
    '8201E6A30FE466AE833F4E9F5E0130A400B99AAE5F03CC1860E5EF3B5E1516FE'
    '1C8278B52F477C0666885D35A2672010E76C4368D3E45A682A5AE26D73B03153'
    '1C200944F51A9D22BE12A17711E2A1CD409AA28B609BEFA0D34863A2F8A32C08'
    '56522E6019675AA79FDC3F3F692B316AB7884A148480333C9D44B73F4CE175EA'
    '37EAE81E7C77B7C61AA2F09F1061CD7B5B324C37EFB17168530AED517D3522FD'
)


class BuildError(Exception):
    """A build stops with what is wrong; fixes: commands that put a missing requirement right; log: the step's log."""
    def __init__(self, msg, fixes=(), log=None):
        super().__init__(msg)
        self.fixes, self.log = list(fixes), log


class Cancelled(KeyboardInterrupt):
    """SIGTERM in --progress json mode (the window's Cancel): stops the build like Ctrl-C."""


def say(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


# ---- --progress json (the window, games/xcx/builder) ----
EVENTS = None        # the real stdout, for one JSON object a line, when --progress json; None otherwise
CURRENT = [None]     # the step running now, for the error event
_critical = dict(depth=0, pending=False)


def emit(event, **fields):
    """One progress event (--progress json only); never carries key values, only paths, names and messages."""
    if EVENTS is not None:
        EVENTS.write(json.dumps(dict(event=event, time=round(time.time(), 3), **fields)) + '\n')
        EVENTS.flush()


def progress_json():
    """Events on stdout, everything else (say, tracebacks, child output) on stderr, and SIGTERM as a clean cancel."""
    global EVENTS
    EVENTS = sys.stdout
    sys.stdout = sys.stderr

    def cancel(signum, frame):
        if _critical['depth']:
            _critical['pending'] = True
        else:
            raise Cancelled()
    signal.signal(signal.SIGTERM, cancel)


@contextlib.contextmanager
def critical():
    """A cancel arriving while the installed app is being replaced takes effect after it, not halfway through."""
    _critical['depth'] += 1
    try:
        yield
    finally:
        _critical['depth'] -= 1
    if not _critical['depth'] and _critical['pending']:
        _critical['pending'] = False
        raise Cancelled()


def run(cmd, log, cwd=None, env=None, quiet=True, timeout=None):
    """Run a step with its whole output in log; on failure show the end of it. quiet: a line a minute meanwhile."""
    cmd = [str(c) for c in cmd]
    log.parent.mkdir(parents=True, exist_ok=True)
    done = threading.Event()

    def beat():
        t0 = time.time()
        while not done.wait(60):
            say(f'   ... still running ({(time.time() - t0) / 60:.0f} min)')
    if quiet:
        threading.Thread(target=beat, daemon=True).start()
    try:
        with open(log, 'w') as f:
            if EVENTS is None:
                p = subprocess.run(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=timeout)
            else:   # its own process group, so that a cancel stops make's jobs and the tools' workers too
                p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    p.wait(timeout=timeout)
                except BaseException:
                    stop_group(p)
                    raise
    finally:
        done.set()
    if p.returncode:
        tail = log.read_text(errors='replace').splitlines()[-25:]
        name = Path(cmd[1] if Path(cmd[0]).name.startswith('python') else cmd[0]).name
        raise BuildError(f'{name} failed (exit {p.returncode}); full output: {log}\n' + '\n'.join(tail), log=log)


def stop_group(p):
    """SIGTERM to a step's process group, SIGKILL if it is still there after 10 s."""
    for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, sig)
        try:
            p.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8 << 20):
            h.update(chunk)
    return h.hexdigest()


def check(what, got, want):
    if got != want:
        raise BuildError(f'{what}: SHA-256 {str(got)[:16]}... is not the expected {str(want)[:16]}... '
                         f'(is this {GAME_NAME} {DISPLAY}, and is the dump complete?)')


def version_order(version):
    """Older versions sort first (by the update's Patch meta version)."""
    return app_bundle.VERSIONS[version]['update_version']


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def last_json(log):
    """The tool's report: its last line that is a JSON object."""
    for line in reversed(log.read_text(errors='replace').splitlines()):
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError:
                pass
    return None


# ---- step timing ----
TIMES = []   # (step, seconds, 'built' | 'reused' | 'checked')


@contextlib.contextmanager
def timed(name, record=True):
    """Time one step; the step says whether it did the work (state['built'] = True), reused what was there (False), or
    only checks (a string: how it is reported). record=False: a progress event only, not in the step times."""
    state = dict(built=False)
    t0 = time.time()
    CURRENT[0] = name
    emit('step', step=name, status='running')
    try:
        yield state
    except BaseException as e:
        emit('step', step=name, status='cancelled' if isinstance(e, KeyboardInterrupt) else 'failed',
             seconds=round(time.time() - t0, 1))
        raise
    how = state['built'] if isinstance(state['built'], str) else 'built' if state['built'] else 'reused'
    if record:
        TIMES.append((name, time.time() - t0, how))
    CURRENT[0] = None
    emit('step', step=name, status=how, seconds=round(time.time() - t0, 1))


def say_times(work, total):
    width = max(len(n) for n, _, _ in TIMES)
    say('step times:')
    for name, seconds, how in TIMES:
        say(f'   {name:<{width}}  {seconds:7.1f} s  {how}')
    say(f'   {"total":<{width}}  {total:7.1f} s')
    path = work / 'logs/build-times.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(when=time.strftime('%Y-%m-%d %H:%M:%S'), total_s=round(total, 1),
                                    steps=[dict(step=n, seconds=round(s, 1), result=h) for n, s, h in TIMES]), indent=2) + '\n')


# ---- genuine dumps (from the original project's build_app.py) ----
def _mgf1_sha256(seed, length):
    blocks = b''
    for counter in range((length + 31) // 32):
        blocks += hashlib.sha256(seed + counter.to_bytes(4, 'big')).digest()
    return blocks[:length]


def _pss_sha256_valid(signature, modulus, message):
    """RSA-2048 PSS/SHA-256 (32-byte salt, MGF1-SHA256), the scheme of an ACID block's signature."""
    size = len(modulus)
    if size < 256 or len(signature) != size:
        return False
    modulus_number = int.from_bytes(modulus, 'big')
    number = int.from_bytes(signature, 'big')
    if number >= modulus_number:
        return False
    encoded = pow(number, 0x10001, modulus_number).to_bytes(size, 'big')
    if encoded[-1] != 0xBC:
        return False
    hashed, mask = encoded[size - 33:size - 1], _mgf1_sha256(encoded[size - 33:size - 1], size - 33)
    db = bytes([(encoded[0] ^ mask[0]) & 0x7F]) + bytes(a ^ b for a, b in zip(encoded[1:size - 33], mask[1:]))
    if db[:-33].strip(b'\x00') or db[-33] != 0x01:
        return False
    return hashlib.sha256(b'\x00' * 8 + hashlib.sha256(message).digest() + db[-32:]).digest() == hashed


def npdm_signed(path):
    """True when the npdm's ACID block carries a valid Nintendo signature over its own access control."""
    data = path.read_bytes()
    if len(data) < 0x80 or data[:4] != b'META' or int.from_bytes(data[0x04:0x08], 'little') != 0:
        return False
    acid, acid_size = struct.unpack_from('<II', data, 0x78)
    if acid_size < 0x200 or acid + acid_size > len(data) or data[acid + 0x200:acid + 0x204] != b'ACID':
        return False
    size = struct.unpack_from('<I', data, acid + 0x204)[0]
    if size < 0x100 or acid + 0x100 + size > len(data):
        return False
    return _pss_sha256_valid(data[acid:acid + 0x100], NINTENDO_ACID_MODULUS, data[acid + 0x100:acid + 0x100 + size])


def npdm_program_id(path):
    """The program ID in a well-formed npdm's ACI0 block (16 upper-case hex digits), else None."""
    data = path.read_bytes()
    if len(data) < 0x80 or data[:4] != b'META':
        return None
    aci, aci_size = struct.unpack_from('<II', data, 0x70)
    if aci_size < 0x20 or aci + aci_size > len(data) or data[aci:aci + 4] != b'ACI0':
        return None
    return f'{struct.unpack_from("<Q", data, aci + 0x10)[0]:016X}'


def npdm_kind(path):
    """How a main.npdm that is not the reference dump's file is accepted: 'signed' (Nintendo's ACID signature: another
    genuine dump), 'resigned' (a well-formed npdm of this title whose ACID a dump tool signed again), else None. The game
    never reads main.npdm here and the code modules are checked by hash, so a re-signed one is accepted only alongside
    matching code."""
    if npdm_signed(path):
        return 'signed'
    return 'resigned' if npdm_program_id(path) == BASE_TITLE else None


def exefs_matches(exefs):
    """True when the extracted ExeFS holds the expected code modules and a main.npdm of this version."""
    want = EXPECTED['exefs_sha256']
    for name, digest in want.items():
        if name != 'main.npdm' and (not (exefs / name).is_file() or sha256(exefs / name) != digest):
            return False
    npdm = exefs / 'main.npdm'
    return npdm.is_file() and (sha256(npdm) == want['main.npdm'] or npdm_kind(npdm) is not None)


def bfttf_valid(path):
    """A structurally valid shared font, by the same size check scripts/extract_shared_fonts.py makes."""
    data = path.read_bytes()
    if len(data) < 12:
        return False
    magic, size = struct.unpack_from('>II', data)
    key = magic ^ 0x7f9a0218
    if (size ^ key) + 8 != len(data):
        return False
    return struct.unpack_from('>I', data, 8)[0] ^ key in (0x00010000, 0x4F54544F)


# ---- files ----
_libc = None


def clonefile(src, dst):
    """macOS clonefile(2): an APFS clone of a file or a whole folder (no extra space) in one call. False when it
    cannot: another volume or file system, or dst exists."""
    global _libc
    if _libc is None:
        import ctypes
        _libc = ctypes.CDLL(None, use_errno=True)
        _libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    return _libc.clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0


def clone(src, dst):
    """APFS clone when on the same volume (no extra space), else a copy (cp -c falls back the same way); an existing
    dst is replaced."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if not clonefile(src, dst):
        shutil.copy2(src, dst)


def copy_tree(src, dst):
    """The files of src in dst: one clone of the whole folder when dst does not exist yet, else file by file."""
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if clonefile(src, dst):
            return
    for p in sorted(src.rglob('*')):
        if p.is_file():
            clone(p, dst / p.relative_to(src))


def remove_tree(path):
    """Remove a bundle. Finder can put .DS_Store back while it is being deleted, which makes the last rmdir fail."""
    for _ in range(5):
        try:
            shutil.rmtree(path)
            return
        except OSError as error:
            if error.errno != 66 or not path.exists():
                raise
            time.sleep(0.2)
    shutil.rmtree(path)


def existing(path):
    """The nearest existing folder of path (for the free space of a folder not made yet)."""
    path = path.resolve()
    while not path.exists():
        path = path.parent
    return path


def free_gb(path):
    return shutil.disk_usage(existing(path)).free / GB


def is_within(path, folder):
    """True when path is folder or inside it."""
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def work_markers(work):
    """The files every finished build_app.py run leaves in its work folder: the step times and an ExeFS manifest (of
    the version built, or of any version before the version is known)."""
    versions = [VERSION] if VERSION else list(app_bundle.VERSIONS)
    manifests = [work / f'extracted/{v}/extraction-manifest.json' for v in versions]
    return [work / 'logs/build-times.json', next((m for m in manifests if m.is_file()), manifests[0])]


def delete_work_refusal(work, out, inputs, finished):
    """Why --delete-work must not delete `work` (None: it may). Never the repository root, personal/, the home folder,
    a folder that holds the output, an input file or files tracked by git; and only a work folder build_app.py made:
    finished, both markers (after the build); before it, an existing non-empty folder must hold at least one of them
    (or the build's venv stamp), so a folder of other files is refused before anything runs."""
    work = work.resolve()
    home = Path.home().resolve()
    named = [(REPO, 'the repository root'), (REPO / 'personal', 'personal/'), (home, 'the home folder'),
             (out.resolve(), 'the output'),
             *((p.resolve(), 'an input file or folder') for p in inputs if p is not None)]
    for path, what in named:
        if is_within(path, work):
            return f'{work} is or holds {what}'
    if is_within(work, REPO):
        tracked = subprocess.run(['git', '-C', REPO, 'ls-files', '--', work.relative_to(REPO).as_posix() or '.'],
                                 capture_output=True, text=True)
        if tracked.returncode or tracked.stdout.strip():
            return f'{work} holds files of the repository (git ls-files)'
    markers = work_markers(work)
    if finished:
        missing = [str(m.relative_to(work)) for m in markers if not m.is_file()]
        if missing:
            return f'{work} is not a build_app.py work folder (no {", ".join(missing)})'
    elif work.exists() and any(work.iterdir()) and not any(m.is_file() for m in markers + [work / 'venv/xcx-packages.json']):
        return (f'{work} is not a build_app.py work folder: it already holds files but none of the markers a build leaves '
                f'({", ".join(str(m.relative_to(work)) for m in markers)})')
    return None


def folder_bytes(path):
    """The bytes a folder's files take on disk (allocated blocks), each file counted once."""
    seen, total = set(), 0
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if (st.st_dev, st.st_ino) not in seen:
                seen.add((st.st_dev, st.st_ino))
                total += st.st_blocks * 512
    return total


def delete_work(work, out, inputs, platform_name):
    """--delete-work, after the build and its final check passed: remove the work folder (checked again first)."""
    with timed('delete work folder', record=False) as t:
        reason = delete_work_refusal(work, out, inputs, finished=True)
        if reason:
            raise BuildError(f'--delete-work: not deleting it: {reason}. The {"IPA" if platform_name == "ios" else "app"} '
                             f'is built: {out}')
        size = folder_bytes(work)
        free_before = shutil.disk_usage(existing(work)).free
        say(f'deleting the work folder {work} ({size / GB:.1f} GB of files; --delete-work)')
        if platform_name == 'ios':
            say(f'   it holds the game data the IPA is installed with ({app_bundle.romfs(VERSION)}/romfs.bin, '
                'install_device.py --game-data): a new build makes it again')
        with critical():   # a cancel now waits until the folder is gone, never half a folder
            remove_tree(work)
            link = make_safe_link(work)
            if link.is_symlink():
                link.unlink()
        freed = shutil.disk_usage(existing(work)).free - free_before
        say(f'deleted the work folder: its files took {size / GB:.1f} GB; {max(freed, 0) / GB:.1f} GB of free space came '
            'back now. Files it shared as APFS clones keep their space until the other copy goes too: the app\'s game '
            'data (about 14 GB) come back only once the app is deleted too. A rebuild or update starts from scratch '
            '(about 8 minutes).')
        emit('work-deleted', work=str(work), bytes=size, freed_bytes=max(freed, 0))
        t['built'] = True


def file_stamp(path):
    st = path.stat()
    return [st.st_size, st.st_mtime_ns]


# ---- inputs ----
def input_kind(path):
    """'xci' or 'nsp' by the file's own header (HEAD at 0x100, PFS0 at 0), never by its name."""
    try:
        with path.open('rb') as f:
            head = f.read(0x104)
    except OSError as e:
        raise BuildError(f'cannot read {path}: {e}') from None
    if head[:4] == b'PFS0':
        return 'nsp'
    if head[0x100:0x104] == b'HEAD':
        return 'xci'
    raise BuildError(f'{path.name} is not an XCI or NSP game file (expected the game card image or an NSP of '
                     f'{GAME_NAME}; the file is recognised by its contents, not its name)')


def title_key_rights(path):
    """The rights IDs (upper-case hex) listed in a title.keys file; the keys themselves are not read into anything."""
    rights = set()
    for line in path.read_text(errors='replace').splitlines():
        name = line.split('#', 1)[0].split('=', 1)[0].strip()
        if len(name) == 32 and all(c in '0123456789abcdefABCDEF' for c in name):
            rights.add(name.upper())
    return rights


def source_matches(manifest, source):
    data = read_json(manifest)
    try:
        stat = source.stat()
        return (data['source'] == str(source.resolve()) and data['source_size'] == stat.st_size
                and data['source_mtime_ns'] == stat.st_mtime_ns)
    except (OSError, TypeError, KeyError):
        return False


# ---- requirements ----
SELECT_XCODE = 'sudo xcode-select -s /Applications/Xcode.app/Contents/Developer'


def req_apple_silicon():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise BuildError('needs a Mac with Apple silicon (this is '
                         f'{platform.system()} on {platform.machine()})')


def req_macos():
    release = platform.mac_ver()[0]
    if int(release.split('.')[0] or 0) < 26:
        raise BuildError(f'needs macOS 26 or later; this is macOS {release}')
    return f'macOS {release}'


def req_clang():
    if subprocess.run(['xcrun', '--find', 'clang'], capture_output=True).returncode:
        raise BuildError('the Xcode command line tools are missing: xcode-select --install', ['xcode-select --install'])
    return subprocess.run(['xcode-select', '-p'], capture_output=True, text=True).stdout.strip() or None


def req_cxx():
    cxx = subprocess.run(['xcrun', 'clang++', '-std=c++11', '-x', 'c++', '-fsyntax-only', '-'], input='#include <string>\n',
                         capture_output=True, text=True)
    if cxx.returncode:   # SPIRV-Cross is C++; without the SDK's libc++ headers it fails much later
        raise BuildError('clang++ finds no C++ standard library headers, so the developer tools or their SDK are incomplete. '
                         f'With Xcode: {SELECT_XCODE}; with the command line '
                         'tools only: sudo rm -rf /Library/Developer/CommandLineTools && xcode-select --install. '
                         f'clang++ said: {cxx.stderr.strip()[:300]}',
                         [SELECT_XCODE, 'sudo rm -rf /Library/Developer/CommandLineTools && xcode-select --install'])


def req_objdump():
    if subprocess.run(['xcrun', '--find', 'llvm-objdump'], capture_output=True).returncode:
        raise BuildError('llvm-objdump not found (xcrun --find llvm-objdump): the rewrite check needs it; install Xcode '
                         f'and select it: {SELECT_XCODE}', [SELECT_XCODE])


def req_tools():
    for tool in ('make', 'codesign', 'git', 'rsync'):
        if not shutil.which(tool, path=os.pathsep.join(TOOL_PATHS + ['/usr/bin', '/bin'])):
            raise BuildError(f'{tool} not found: xcode-select --install', ['xcode-select --install'])


def req_homebrew():
    brew = Path('/opt/homebrew/opt')   # the Makefile links these static libraries
    missing = [p for p, lib in (('opus', 'libopus.a'), ('libvpx', 'libvpx.a')) if not (brew / p / 'lib' / lib).is_file()]
    if missing:
        raise BuildError(f'Homebrew packages missing: brew install {" ".join(missing)} (https://brew.sh for Homebrew)',
                         [f'brew install {" ".join(missing)}'])


def req_python():
    py = next((p for p in (shutil.which(n, path=os.pathsep.join(TOOL_PATHS)) for n in ('python3.14', 'python3.15')) if p), None)
    if not py and sys.version_info >= (3, 14):
        py = sys.executable
    if not py:
        raise BuildError('Python 3.14 not found (games/xcx/requirements.txt is pinned for it): brew install python@3.14',
                         ['brew install python@3.14'])
    return Path(py)


# (what is checked, the check, needs the developer tools): a check raises BuildError with what to do, or returns a detail
MAC_REQUIREMENTS = [
    ('Apple silicon', req_apple_silicon, False), ('macOS 26 or later', req_macos, False),
    ('Xcode command line tools', req_clang, False), ('C++ standard library headers', req_cxx, True),
    ('llvm-objdump (Xcode)', req_objdump, True), ('make, codesign, git, rsync', req_tools, True),
    ('Homebrew opus and libvpx', req_homebrew, False), ('Python 3.14', req_python, False),
]


def prerequisites():
    """The Mac's tools, checked at the start with what to do about each one missing (from the original project's)."""
    for _, check_one, _ in MAC_REQUIREMENTS:
        detail = check_one()
    return detail   # req_python's: the Python for the build's venv


def make_safe_link(work):
    return Path.home() / f'{app_bundle.CACHES}/xcx-work-{hashlib.sha256(str(work).encode()).hexdigest()[:12]}'


def make_safe(work):
    """make splits paths at spaces: a work folder whose path has one is passed to make through a link without any."""
    if not any(c in str(work) for c in ' #$:=%\\\'"'):
        return work
    link = make_safe_link(work)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() and link.resolve() == work.resolve():
        return link
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(work)
    return link


def prepare_venv(work, py, logs):
    """<work>/venv with games/xcx/requirements.txt and unicorn; installed again only when the list changes."""
    venv = work / 'venv'
    vpy = venv / 'bin/python'
    req = GAME / 'requirements.txt'
    want = dict(requirements=sha256(req), extra=EXTRA_PACKAGES, python=str(py))
    stamp = venv / 'xcx-packages.json'
    probe = [vpy, '-c', 'import cryptography, lz4.block, capstone, unicorn']
    if vpy.exists() and read_json(stamp) == want and subprocess.run(probe, capture_output=True).returncode == 0:
        return vpy, False
    if not vpy.exists():
        say('Python environment for the build tools')
        run([py, '-m', 'venv', venv], logs / 'venv.log')
    say('installing the build\'s Python packages (games/xcx/requirements.txt, unicorn)')
    try:
        run([vpy, '-m', 'pip', 'install', '-q', '--disable-pip-version-check', '-r', req, *EXTRA_PACKAGES], logs / 'pip.log')
    except BuildError as e:
        raise BuildError(f'the Python packages could not be installed (network access is needed once): {e}') from None
    if subprocess.run(probe, capture_output=True).returncode:
        raise BuildError(f'the Python packages do not import after installing them; see {logs / "pip.log"}')
    stamp.write_text(json.dumps(want))
    return vpy, True


# ---- identification ----
def describe_titles(report):
    titles = sorted({n['title_id'] for n in report.get('ncas', [])} | {m['title_id'] for m in report.get('metas', [])})
    named = [f'{OTHER_TITLES[t]} ({t})' for t in titles if t in OTHER_TITLES]
    # an update (...800) or add-on content of a known game: its base title is the 0x1000 block's start (DLC: one below)
    for t in titles:
        value = int(t, 16)
        base = value & ~0xFFF if value & 0xFFF in (0, 0x800) else (value & ~0xFFF) - 0x1000
        if t not in OTHER_TITLES and f'{base:016X}' in OTHER_TITLES:
            named.append(f'{OTHER_TITLES[f"{base:016X}"]} ({t}, {"update" if value & 0xFFF == 0x800 else "add-on content"})')
    return ', '.join(named) if named else 'title ' + ', '.join(titles) if titles else 'no game content'


def read_reports(vpy, logs, files, keys, log_name='identify.log'):
    """identify_game.py's report of each file (one JSON line each)."""
    log = logs / log_name
    run([vpy, GAME / 'scripts/identify_game.py', *files, '--keys', keys], log, quiet=False)
    reports = [json.loads(line) for line in log.read_text().splitlines() if line.startswith('{')]
    if len(reports) != len(files):
        raise BuildError(f'could not read the game files (see {log})')
    return reports


def own_patches(report):
    return [m for m in report.get('metas', []) if m['type'] == 0x81 and m['title_id'] == UPDATE_TITLE]


def unsupported(name, number):
    return BuildError(f'{name}: update version {app_bundle.describe(number)} is not supported; this port runs '
                      f'{SUPPORTED}. Pass the 1.0.1 or 2.0.0 update NSP with --update.')


def identify(vpy, logs, game, update, keys, title_keys):
    """Check that the files are this game, base v0 and a supported update, before any long step, and choose the version
    to build: the update's (--update wins over the update inside an XCI). Returns the update's source file (the game
    file itself for an XCI holding both) and the version folder (v101 / v200)."""
    reports = read_reports(vpy, logs, [game] + ([update] if update else []), keys)
    for path, r in zip([game] + ([update] if update else []), reports):
        if 'error' in r:
            raise BuildError(f'{path.name}: {r["error"]} (is it {GAME_NAME}, and is -k this Switch\'s prod.keys?)')
    g = reports[0]
    titles = {n['title_id'] for n in g['ncas']}
    if not titles & {BASE_TITLE, UPDATE_TITLE}:
        raise BuildError(f'{game.name} is not {GAME_NAME} ({BASE_TITLE}): it holds {describe_titles(g)}')
    base_metas = [m for m in g['metas'] if m['type'] == 0x80 and m['title_id'] == BASE_TITLE]
    if not base_metas:
        if own_patches(g):
            raise BuildError(f'{game.name} is the update of {GAME_NAME}, not the base game: pass the base game (the XCI '
                             f'or the base NSP) as the game file and this file with --update')
        raise BuildError(f'{game.name} holds no base game of {GAME_NAME} (Application meta {BASE_TITLE}); '
                         f'add-on content and other packages are not supported')
    if base_metas[0]['version'] != 0:
        raise BuildError(f'{game.name}: base game version {base_metas[0]["version"]}; only the original base (v0) is supported')
    inside = own_patches(g)
    if update:
        u = reports[1]
        patches = [m for m in u['metas'] if m['type'] == 0x81]
        if any(m['type'] == 0x80 for m in u['metas']) and not patches:
            raise BuildError(f'--update {update.name} is a base game, not the update: pass the update NSP (1.0.1 or 2.0.0)')
        mine = own_patches(u)
        if not mine:
            raise BuildError(f'--update {update.name} is not the update of {GAME_NAME} ({UPDATE_TITLE}): it holds '
                             f'{describe_titles(u)}')
        source, number = update, mine[0]['version']
    else:
        if not inside:
            raise BuildError(f'{game.name} holds only the base game (v0): pass an update NSP with --update '
                             f'<update.nsp> ({SUPPORTED})')
        source, number = game, inside[0]['version']
    version = app_bundle.by_update_version(number)
    if version is None:
        raise unsupported(source.name, number)
    select_version(version)
    # Rights-managed NCAs need their title key: a common ticket in the same file, else title.keys
    for path, r in zip([game] + ([update] if update else []), reports):
        common = {t['rights_id'] for t in r['tickets'] if t['kind'] == 'common'}
        needed = {n['rights_id'] for n in r['ncas'] if n['rights_managed'] and n['title_id'] in (BASE_TITLE, UPDATE_TITLE)}
        missing = needed - common - (title_key_rights(title_keys) if title_keys else set())
        if missing:
            raise BuildError(f'{path.name} has no common ticket for {len(missing)} of its NCAs'
                             + (' and title.keys has no key for them' if title_keys else
                                ': pass --title-keys <title.keys> (dumped from your own Switch)'))
    note = ''
    if update and inside:
        shown = app_bundle.describe(inside[0]['version'])
        note = (f'; the update given with --update wins over the {shown} update inside {game.name}'
                if inside[0]['version'] != number else '')
        if inside[0]['version'] > number:
            say(f'note: {game.name} holds a newer update ({shown}) than --update {update.name} ({DISPLAY}); building '
                f'{DISPLAY} as asked')
    say(f'{GAME_NAME}: base v0 from {game.name}, update {DISPLAY} from {source.name} (by the IDs inside the files{note}); '
        f'building {DISPLAY}')
    return source, version


# ---- steps ----
class Build:
    def __init__(self, args, work, vpy, logs, env):
        self.game, self.update, self.keys = args.game, args.update, args.keys
        self.title_keys, self.firmware = args.title_keys, args.firmware
        self.work, self.vpy, self.logs, self.env = work, vpy, logs, env
        self.make_work = make_safe(work)
        self.kind = input_kind(self.game)

    def py(self, script, *args, log, env=None, cwd=None):
        run([self.vpy, script, *args], self.logs / log, cwd=cwd or GAME, env=env or self.env)

    def make(self, *targets, log, extra=()):
        jobs = os.cpu_count() or 4
        run(['make', f'-j{jobs}', *targets, f'WORK={self.make_work}', f'PY={self.vpy}', f'VERSION={VERSION}', *extra],
            self.logs / log, cwd=GAME, env=self.env)

    def tk_args(self):
        return ['--title-keys', self.title_keys] if self.title_keys else []

    # 1. code
    def step_code(self, update_source):
        exefs = self.work / f'extracted/{VERSION}/exefs'
        manifest = exefs.parent / 'extraction-manifest.json'
        with timed('code: ExeFS') as t:
            if not (source_matches(manifest, update_source) and exefs_matches(exefs)):
                say(f'1/7 code: extracting and verifying the {DISPLAY} ExeFS')
                if exefs.exists():
                    shutil.rmtree(exefs)
                self.py('scripts/extract_code.py', self.game, '--keys', self.keys, '--output', exefs, '--version', VERSION,
                        *(['--update', self.update] if self.update else []), *self.tk_args(), log='extract_code.log')
                t['built'] = True
            for name, digest in EXPECTED['exefs_sha256'].items():
                if not (exefs / name).is_file():
                    raise BuildError(f'ExeFS {name} is missing; not {GAME_NAME} {DISPLAY}')
                got = sha256(exefs / name)
                if got == digest:
                    continue
                kind = npdm_kind(exefs / name) if name == 'main.npdm' else None
                if kind == 'signed':
                    say(f'1/7 code: main.npdm is a Nintendo-signed {DISPLAY} file from another dump; using it')
                elif kind == 'resigned':
                    say(f'1/7 code: main.npdm of this dump was signed again by a dump tool; the game does not use it and '
                        f'the code modules match {DISPLAY}; using it')
                else:
                    check(f'ExeFS {name}', got, digest)
        with timed('code: NSO segments') as t:
            elf = self.work / f'extracted/{VERSION}/elf'
            if not all((elf / f'{m}-inventory.json').is_file() for m in ('rtld', 'main', 'sdk', 'subsdk0')):
                say('1/7 code: checking the NSO segments of the four code modules')
                self.py('scripts/prepare_modules.py', exefs, '--output', elf, log='prepare_modules.log')
                t['built'] = True
        out = self.work / f'rewritten/{VERSION}'
        out.mkdir(parents=True, exist_ok=True)
        with timed('code: rewrite') as t:
            for name in ('sdk', 'subsdk0', 'main'):
                image = out / f'{name}.patched.bin'
                want = EXPECTED['rewritten_sha256'][f'{name}.patched.bin']
                tables = [out / f'{name}.{k}.tsv' for k in ('fixups', 'gates', 'sites', 'cuts')]
                if image.is_file() and all(p.is_file() for p in tables) and sha256(image) == want:
                    continue
                say(f'1/7 code: rewriting {name} for Apple silicon' + (' (the big one: about a minute)' if name == 'main' else ''))
                self.py('third_party/d2r/patch_nso.py', exefs / name, out, name, log=f'rewrite_{name}.log',
                        env=dict(self.env, DM_RULESET='native', DM_PRIVATE_GATES='0'))
                check(f'rewritten {name}', sha256(image), want)
                t['built'] = True
        with timed('code: rewrite checks') as t:
            self.rewrite_checks(exefs, out, t)

    def rewrite_checks(self, exefs, out, t):
        """structck.py (structure) and equiv.py (semantics, emulator) for each module, as the port was verified with.
        Recorded with the image and checker digests, so a later build with the same rewrite does not repeat them."""
        record_path = self.work / 'analysis/rewrite-checks.json'
        whole = read_json(record_path) or {}
        # one record a version ({version: {module: ...}}); the 1.0.1 record of earlier builds is flat ({module: ...})
        flat = {k: whole.pop(k) for k in ('sdk', 'subsdk0', 'main') if k in whole}
        if flat:
            whole.setdefault('v101', flat)
        record = whole.setdefault(VERSION, {})
        checkers = {n: sha256(GAME / 'third_party/d2r' / n) for n in ('structck.py', 'equiv.py', 'patch_nso.py')}
        llvm = subprocess.run(['xcrun', '--find', 'llvm-objdump'], capture_output=True, text=True).stdout.strip()
        env = dict(self.env, LLVM_BIN=str(Path(llvm).parent), DM_VCACHE=str(self.work / f'cache/verify_{VERSION}'))
        for name in ('sdk', 'subsdk0', 'main'):
            want = dict(image=EXPECTED['rewritten_sha256'][f'{name}.patched.bin'], checkers=checkers, structck='pass', equiv='pass')
            if record.get(name) == want:
                continue
            say(f'1/7 code: checking the rewrite of {name}: structure (structck.py), then semantics (equiv.py)')
            self.py('third_party/d2r/structck.py', out, name, exefs / name, log=f'structck_{name}.log', env=env)
            if f'STRUCT {name} OK' not in (self.logs / f'structck_{name}.log').read_text(errors='replace'):
                raise BuildError(f'structck.py did not report {name} OK; see {self.logs / f"structck_{name}.log"}')
            self.py('third_party/d2r/equiv.py', out, name, exefs / name, '--seed', '1', '--jobs', str(os.cpu_count() or 8),
                    '--tsv', self.logs / f'equiv_{name}.tsv', log=f'equiv_{name}.log', env=env)
            text = (self.logs / f'equiv_{name}.log').read_text(errors='replace')
            if f'EQUIV {name} OK' not in text or '分歧站点=0' not in text:
                raise BuildError(f'equiv.py did not report {name} OK with 0 divergent sites; see {self.logs / f"equiv_{name}.log"}')
            record[name] = want
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.write_text(json.dumps(whole, indent=2) + '\n')
            t['built'] = True
        if flat:   # the flat 1.0.1 record moved under its version
            record_path.write_text(json.dumps(whole, indent=2) + '\n')

    # 2. fonts
    def font_report(self, folder):
        """The six fonts bound into the runtime: the pinned hashes name the fonts of the reference dump's system
        update; a valid font of another firmware version is bound by the SHA-256 of its own bytes."""
        pins = EXPECTED['shared_fonts_sha256']
        manifest = read_json(folder / 'manifest.json') or {}
        rows = manifest.get('fonts') or []
        if manifest.get('status') != 'pass' or [r.get('type') for r in rows] != list(range(6)) \
                or [r.get('name') for r in rows] != list(pins):
            return None
        other = []
        for row, (name, known) in zip(rows, pins.items()):
            path = folder / f'{row["type"]}-{name}.bfttf'
            if not path.is_file() or path.stat().st_size != row['bfttf_bytes'] or not bfttf_valid(path):
                return None
            digest = sha256(path)
            if digest != row['sha256']:
                return None
            if digest not in known:
                other.append(name)
        return other

    def step_fonts(self):
        folder = self.work / 'extracted/firmware/shared-fonts'
        with timed('fonts') as t:
            other = self.font_report(folder)
            if other is None:
                if folder.exists():
                    shutil.rmtree(folder)
                if self.firmware:
                    say(f'2/7 fonts: extracting the six system shared fonts from {self.firmware}')
                    source = ['--firmware', self.firmware]
                else:
                    say('2/7 fonts: extracting the six system shared fonts from the system update in the card image')
                    source = ['--xci', self.game]
                try:
                    self.py('scripts/extract_shared_fonts.py', '--keys', self.keys, *source, '--output', folder,
                            log='shared_fonts.log')
                except BuildError as e:
                    hint = '' if self.firmware else (' The card image may carry no system update with the fonts: pass '
                                                     '--firmware <folder of your firmware\'s NCA files>.')
                    raise BuildError(f'{e}{hint}') from None
                other = self.font_report(folder)
                if other is None:
                    raise BuildError(f'the extracted shared fonts in {folder} do not check out (see {self.logs / "shared_fonts.log"})')
                t['built'] = True
            if other:
                say(f'2/7 fonts: {", ".join(other)} come{"s" if len(other) == 1 else ""} from another firmware version '
                    f'than the pinned ones (verified NCA, valid BFTTF); bound by their own SHA-256')

    # 3. data
    def step_data(self):
        romfs = self.work / f'extracted/{VERSION}/romfs'
        image, index = romfs / 'romfs.bin', romfs / 'index.json'
        want = EXPECTED['romfs']
        with timed('data: RomFS') as t:
            report = read_json(index) or {}
            ok = (report.get('status') == 'pass' and report.get('romfs_sha256') == want['sha256'] and
                  report.get('romfs_size') == want['size'] and len(report.get('files', [])) == want['files'] and
                  image.is_file() and image.stat().st_size == want['size'])
            if ok and report.get('romfs_mtime_ns') not in (None, image.stat().st_mtime_ns):
                say('2/7 data: the RomFS image changed since it was verified; checking its SHA-256 (14.3 GB)')
                ok = sha256(image) == want['sha256']
                if ok:
                    report['romfs_mtime_ns'] = image.stat().st_mtime_ns
                    index.write_text(json.dumps(report, indent=2) + '\n')
            if not ok:
                need = want['size'] / GB + 1
                if free_gb(romfs.parent) < need:
                    raise BuildError(f'needs about {need:.0f} GB free for the merged RomFS in {romfs.parent} '
                                     f'({free_gb(romfs.parent):.1f} GB free)')
                if romfs.exists():
                    shutil.rmtree(romfs)
                say(f'3/7 data: merging the base RomFS and the {DISPLAY} patch into one 14.3 GB image, verifying all six '
                    'IVFC levels (a few minutes)')
                self.py('scripts/merge_romfs.py', self.game, '--keys', self.keys, '--output', romfs, '--version', VERSION,
                        *(['--update', self.update] if self.update else []), *self.tk_args(), log='merge_romfs.log')
                report = read_json(index) or {}
                check('RomFS', report.get('romfs_sha256'), want['sha256'])
                for key, what in (('romfs_size', 'size'), ('bytes_from_base', 'bytes_from_base'),
                                  ('bytes_from_update', 'bytes_from_update')):
                    if report.get(key) != want[what]:
                        raise BuildError(f'RomFS {what}: {report.get(key)} is not the expected {want[what]}')
                if len(report.get('files', [])) != want['files']:
                    raise BuildError(f'RomFS holds {len(report.get("files", []))} files, not the expected {want["files"]}')
                t['built'] = True

    # 4.-6. the Makefile's targets
    def step_prepare(self):
        with timed('prepare') as t:
            build = self.work / app_bundle.generated(VERSION)
            before = {p.name: file_stamp(p) for p in build.glob('*.h')} if build.is_dir() else {}
            say(f'4/7 prepare: the runtime\'s tables, RomFS index and fonts config for {DISPLAY} (make prepare)')
            self.make('prepare', log=f'prepare-{VERSION}.log')
            t['built'] = {p.name: file_stamp(p) for p in build.glob('*.h')} != before

    def step_runtime(self):
        binary = self.work / app_bundle.binary(VERSION)
        with timed('runtime') as t:
            before = file_stamp(binary) if binary.is_file() else None
            say(f'5/7 runtime: the {DISPLAY} game binary (make runtime; a few minutes the first time)')
            self.make('runtime', log=f'runtime-{VERSION}.log')
            t['built'] = file_stamp(binary) != before

    def step_shader_tools(self):
        xlate = self.work / 'build/shader-service/totk_xlate'
        spirv = self.work / 'build/spirv-cross/spirv-cross'
        with timed('shader tools') as t:
            before = [file_stamp(p) if p.is_file() else None for p in (xlate, spirv)]
            say('6/7 shader tools: the prebuilt shader translator (SHA-256 checked) and SPIRV-Cross at its pinned commit '
                '(make shader-tools)')
            self.make('shader-tools', log='shader-tools.log')
            want = (GAME / 'prebuilt/macos-arm64/totk_xlate.sha256').read_text().split()[0]
            check('shader translator (build/shader-service/totk_xlate)', sha256(xlate), want)
            head = subprocess.run(['git', '-C', self.work / 'src/SPIRV-Cross', 'rev-parse', 'HEAD'],
                                  capture_output=True, text=True).stdout.strip()
            if head != SPIRV_CROSS_COMMIT:
                raise BuildError(f'SPIRV-Cross in {self.work / "src/SPIRV-Cross"} is at {head[:12] or "?"}, not the '
                                 f'pinned {SPIRV_CROSS_COMMIT[:12]}; delete that folder and build again')
            t['built'] = [file_stamp(p) for p in (xlate, spirv)] != before

    def step_launcher(self):
        with timed('launcher and icon') as t:
            paths = [self.work / app_bundle.launcher(VERSION), self.work / 'build/AppIcon.icns']
            before = [file_stamp(p) if p.is_file() else None for p in paths]
            self.make('launcher', log=f'launcher-{VERSION}.log')
            if not paths[1].is_file():
                try:   # the game's own icon from its control data; the app goes without one if it cannot be read
                    self.make('icon', log='icon.log', extra=[f'GAME={self.game}', f'KEYS={self.keys}',
                                                             *([f'TITLE_KEYS={self.title_keys}'] if self.title_keys else [])])
                except BuildError as e:
                    say(f'   no app icon, the app gets the default one ({str(e).splitlines()[0]})')
            t['built'] = [file_stamp(p) if p.is_file() else None for p in paths] != before


# ---- the shaders, prepared ahead (games/xcx/scripts/prepare_shader_seed.py, docs/sharing-shaders.md) ----
SHADER_LIST_REPO = fetch_shader_list.REPO_COPY   # games/xcx/assets/shader_list.tsv
SHADER_LIST_ORIGINS = dict(downloaded='downloaded', cached='cached', repo='in the project')
# The runtime's shader cache files (totk_shader_seed.h): a variant's MSL and reflection, and a shader's index of variants
SHADER_CACHE_FILE = re.compile(r'^(?:[0-9a-f]{64}\.variants|[0-9a-f]{64}-[0-9a-f]{12}_b\.(?:metal|json))$')


def shader_chain():
    """The translation chain the runtime names its shader cache folder after (rt-<chain>)."""
    return next(line.split('"')[1] for line in (GAME / 'third_party/d2r_gfx/gfx/nvn/dmsh_chain.h').read_text().splitlines()
                if line.startswith('#define DMSH_CHAIN'))


def mac_shader_cache():
    """The player's shader cache, where the self-contained app keeps what it translates."""
    return app_bundle.data_folder() / f'shader-cache/rt-{shader_chain()}'


def no_download(url, timeout):
    raise OSError('--offline')


def shader_list_for_build(work, offline=False, opener=None):
    """The shared shader list to prepare from: (path, origin, rows). The newest one from GitHub, cached in
    <work>/build/shader-list; else the one an earlier build cached; else the project's (fetch_shader_list.py). offline:
    no download. path is None when there is no list, an empty one or one that cannot be read: the default bind states
    only."""
    path, origin = fetch_shader_list.fetch_list(work / 'build/shader-list', SHADER_LIST_REPO,
                                                **(dict(opener=no_download) if offline else
                                                   dict(opener=opener) if opener else {}))
    try:
        rows = len(ShaderList.load(path).rows()) if Path(path).is_file() else 0
    except (OSError, ValueError) as e:
        say(f'shader list: {path} cannot be read ({e}); preparing the usual case of each shader only')
        return None, origin, 0
    return (Path(path) if rows else None), origin, rows


def pull_ios_contribution():
    """--platform ios with XCX_IOS_DEVICE set: bring the shaders the device met that the list lacks into this Mac's
    contribution file, so the build and the window's share offer count them. Never fails the build: one warning line.
    Returns how many rows it brought."""
    device = os.environ.get('XCX_IOS_DEVICE')
    if not device:
        return 0
    try:
        sys.path.insert(0, str(GAME / 'ios/tools'))
        import shader_contrib_watch
        problems = []
        added = shader_contrib_watch.pull(device, os.environ.get('XCX_BUNDLE_ID') or app_bundle.BUNDLE_ID,
                                          store=contribution.mac_file(), report=problems.append)
        say(f'warning: shaders from the iPhone not pulled: {problems[0]}' if problems
            else f'{added} new shaders from the iPhone (shader-list-contribution.txt)')
        return added
    except Exception as e:   # noqa: BLE001  a device that is away is no reason to stop a build
        say(f'warning: shaders from the iPhone not pulled: {e}')
        return 0


def step_shader_prep(work, logs, py, offline=False):
    """Every shader of the version's RomFS translated for its usual bind state, and for the ones the shared list names
    for it, into <work>/build/shader-prep/rt-<chain> (prepare_shader_seed.py; about a minute the first time, then only
    what changed). The IPA carries them and the Mac's shader cache gets the ones it lacks. Returns that folder, or None
    when the preparation fails: that is not a build failure, the build then carries only the shaders this Mac has
    translated, as before. A translation that failed stays failed (rt-<chain>.translations) until the translator
    changes."""
    prep = work / f'build/shader-prep/rt-{shader_chain()}'
    log = logs / 'shader-prep.log'
    with timed('shaders: prepare') as t:
        path, origin, rows = shader_list_for_build(work, offline)
        say(f'shader list: {SHADER_LIST_ORIGINS[origin]} ({rows} rows)')
        say('6/7 shaders: every shader of the game translated ahead, with the cases the shared list names '
            '(prepare_shader_seed.py; about a minute the first time)')
        try:
            run([py, GAME / 'scripts/prepare_shader_seed.py', '--romfs', work / f'extracted/{VERSION}', '--output', prep,
                 '--translator', work / 'build/shader-service/totk_xlate',
                 '--spirv-cross', work / 'build/spirv-cross/spirv-cross', '--version', VERSION,
                 *(['--list', path] if path else [])], log, cwd=GAME)
        except BuildError as e:
            lines = log.read_text(errors='replace').splitlines() if log.is_file() else []
            errors = [line.removeprefix('ERROR: ') for line in lines if line.startswith('ERROR: ')]
            say(f'shaders: preparation failed ({errors[-1] if errors else str(e).splitlines()[0]}); this build carries '
                f'only the shaders this Mac already translated (full output: {log})')
            t['built'] = 'failed'
            return None
        summary = [line for line in log.read_text(errors='replace').splitlines() if line.startswith('shader prep:')]
        if summary:
            say(f'6/7 {summary[-1]}')
        t['built'] = not (summary and summary[-1].endswith(', reused'))
    return prep if prep.is_dir() else None


def report_contribution(work, device='Mac'):
    """After a build: the rows of this Mac's contribution file (contribution.py) that the list the build used lacks; the
    window offers to share them (event contribution; device fills in the issue form's Device, None leaves it to the
    player). Nothing when there are none or the file cannot be read."""
    path, _, _ = shader_list_for_build(work, offline=True)   # the list the build cached, else the project's
    mac_file = contribution.mac_file()
    try:
        rows = len(contribution.new_rows(mac_file, path))
    except (OSError, ValueError) as e:
        say(f'shader list contribution: {mac_file} cannot be read ({e})')
        return
    if rows:
        say(f'You found {rows} new shaders the shared list does not have yet ({mac_file}): sharing them lets '
            'everyone\'s next build draw these parts of the game (docs/sharing-shaders.md).')
        emit('contribution', rows=rows, file=str(mac_file), url=contribution.issue_url(rows, DISPLAY, device))


def place_new(src, dst):
    """src at dst unless dst exists, never replacing it (the game may write dst meanwhile); True when placed."""
    tmp = dst.with_name(f'{dst.name}.{os.getpid()}.tmp')
    tmp.unlink(missing_ok=True)
    try:   # a failed copy (a full disk) leaves no temp file in the player's cache
        if not clonefile(src, tmp):
            shutil.copy2(src, tmp)
        os.link(tmp, dst)   # fails if dst is there; never replaces it
        return True
    except FileExistsError:
        return False
    finally:
        tmp.unlink(missing_ok=True)


def copy_prepared_shaders(prep, cache, missed=None):
    """Merge the prepared shaders into the Mac's shader cache: for each prepared shader index, the variants the cache's
    index of that shader lacks (by variant name) are added after its own entries, which stay as they are and in their
    order; their files are copied first, never replacing one, then the index is written whole and put in place in one
    step. An index of the cache that cannot be read, or that changes meanwhile (the game running), is left alone (and its
    name appended to missed, when given). Returns the number of variants added."""
    cache.mkdir(parents=True, exist_ok=True)
    new = 0
    for src in sorted(prep.glob('*.variants')):
        if not SHADER_CACHE_FILE.match(src.name):
            continue
        dst = cache / src.name
        try:
            rows = json.loads(src.read_text())
            before = dst.stat().st_mtime_ns if dst.exists() else None
            have = json.loads(dst.read_text()) if before is not None else []
        except (OSError, ValueError):
            if missed is not None:
                missed.append(src.name)
            continue
        if not isinstance(rows, list) or not isinstance(have, list):
            if missed is not None:
                missed.append(src.name)
            continue
        known = {r.get('variant') for r in have if isinstance(r, dict)}
        add = [r for r in rows if isinstance(r, dict) and isinstance(r.get('variant'), str) and r['variant'] not in known
               and SHADER_CACHE_FILE.match(r['variant'] + '_b.metal')
               and all((prep / f"{r['variant']}{end}").is_file() for end in ('_b.metal', '_b.json'))]
        if not add:
            continue
        for r in add:   # the files before the index that names them, as the runtime's seed import writes them
            for end in ('_b.metal', '_b.json'):
                place_new(prep / f"{r['variant']}{end}", cache / f"{r['variant']}{end}")
        tmp = dst.with_name(f'{dst.name}.{os.getpid()}.tmp')
        try:
            tmp.write_text(json.dumps(have + add, sort_keys=True, separators=(',', ':')))
            if (dst.stat().st_mtime_ns if dst.exists() else None) != before:   # the game wrote it meanwhile: its own
                if missed is not None:
                    missed.append(src.name)
                continue
            os.replace(tmp, dst)
            new += len(add)
        finally:
            tmp.unlink(missing_ok=True)   # gone after os.replace; after a failed write, not left in the player's cache
    return new


# ---- the macOS app ----
def data_bundle(work, logs):
    """The RomFS image (14.3 GB) as a bundle of its own, signed once and kept in the work folder (build/data-bundles):
    the app carries a clone of it in Contents/Helpers, and the app's seal records only its signature, so packaging does
    not hash 14 GB each time. The stamp names the image (size, mtime and the SHA-256 the merge verified). From the
    original project's build_app.py."""
    image = work / f'{app_bundle.romfs(VERSION)}/romfs.bin'
    bundle = work / f'build/data-bundles/{app_bundle.data_bundle(VERSION)}'
    stamp = bundle.with_name(bundle.name + '.json')
    st = image.stat()
    want = dict(format=2, size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=(read_json(image.parent / 'index.json') or {}).get('romfs_sha256'))
    if read_json(stamp) == want and (bundle / 'Contents/_CodeSignature/CodeResources').is_file() and \
            (bundle / 'Contents/Resources/romfs.bin').is_file():
        return bundle, False
    say('7/7 app: signing the game data once (a minute or two; later builds reuse it)')
    tmp = bundle.with_name(bundle.name + '.partial')
    if tmp.exists():
        shutil.rmtree(tmp)
    clone(image, tmp / 'Contents/Resources/romfs.bin')
    (tmp / 'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleIdentifier=f'{app_bundle.BUNDLE_ID}.data.{VERSION}', CFBundleName='Game data', CFBundlePackageType='BNDL',
        CFBundleShortVersionString=DISPLAY, CFBundleVersion='1')))
    run(['codesign', '--force', '--sign', '-', tmp], logs / 'sign-data.log')
    run(['codesign', '--verify', '--strict', tmp], logs / 'verify-data.log')   # here, where the 14 GB are hashed anyway
    with critical():
        stamp.unlink(missing_ok=True)
        if bundle.exists():
            shutil.rmtree(bundle)
        tmp.rename(bundle)
        stamp.write_text(json.dumps(want))
    return bundle, True


def app_seal_valid(app):
    """The app's own seal, which records the data bundle's signature (not --deep: that hashes the 14 GB image)."""
    return subprocess.run(['codesign', '--verify', '--strict', app], capture_output=True).returncode == 0


def keep_game_data(new, old):
    """When the app being replaced carries the same signed game data, move its data bundle into the new app in place of
    the fresh clone: the image keeps its file identity, so the runtime's RomFS check record (runtime/romfs.c, keyed by
    it) still matches and the first start after a rebuild does not hash 14 GB again. If the new app's seal does not
    verify then, the clone goes back. From the original project's build_app.py."""
    image = 'Contents/Resources/romfs.bin'
    kept = False
    for bundle in sorted((new / 'Contents/Helpers').glob('GameData-*.bundle')):
        before = old / 'Contents/Helpers' / bundle.name
        if not all((before / rel).is_file() and (before / rel).read_bytes() == (bundle / rel).read_bytes()
                   for rel in ('Contents/_CodeSignature/CodeResources', 'Contents/Info.plist')):
            continue
        if not (before / image).is_file() or (before / image).stat().st_size != (bundle / image).stat().st_size:
            continue
        fresh = new.with_name(f'{new.name}.{bundle.name}.fresh')   # outside the app: anything extra in it fails the seal
        if fresh.exists():
            remove_tree(fresh)
        bundle.rename(fresh)
        try:
            before.rename(bundle)
        except OSError:
            fresh.rename(bundle)
            continue
        if not app_seal_valid(new):
            bundle.rename(before)
            fresh.rename(bundle)
            continue
        remove_tree(fresh)
        kept = True
    return kept


def install_app(new, out):
    """Put the signed app `new` at `out`; the seal is checked before the installed app is touched. The .app folder
    itself stays and takes the new contents (macOS keeps its first-run check of an app with the folder); the replaced
    contents are removed in the background. Returns whether the installed game data was kept."""
    kept = out.exists() and keep_game_data(new, out)
    if not kept and not app_seal_valid(new):
        raise BuildError(f'{new}: the new app\'s signature does not verify (codesign --verify --strict); the installed app is unchanged')
    leftovers = sorted(out.parent.glob(f'{glob.escape(out.name)}.replaced-*'))
    if out.exists():
        old = out.with_name(f'{out.name}.replaced-{os.getpid()}')
        if old.exists():
            remove_tree(old)
        old.mkdir()
        for entry in list(out.iterdir()):
            entry.rename(old / entry.name)
        for entry in list(new.iterdir()):
            entry.rename(out / entry.name)
        new.rmdir()
        leftovers.append(old)
    else:
        new.rename(out)
    for path in leftovers:
        subprocess.Popen(['rm', '-rf', str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    return kept


def game_running(out):
    binary = str((out / app_bundle.GAME_ROOT / app_bundle.APP_BINARY).resolve())
    procs = subprocess.run(['ps', '-axo', 'comm='], capture_output=True, text=True).stdout.splitlines()
    return binary in (p.strip() for p in procs)


def app_inputs(work, bundle_stamp, icon):
    """What the app is made of, for knowing whether an installed app is current: the files cloned into it, the
    launcher, the icon, the data bundle's stamp and the Info.plist."""
    files = list(app_bundle.game_files(VERSION).values()) + [app_bundle.launcher(VERSION)] + sorted(
        f'{app_bundle.SHARED_FONTS}/{p.name}' for p in (work / app_bundle.SHARED_FONTS).iterdir() if p.is_file())
    stamps = {rel: file_stamp(work / rel) for rel in files}
    if icon:
        stamps['build/AppIcon.icns'] = file_stamp(icon)
    return dict(format=2, version=VERSION, files=stamps, data=read_json(bundle_stamp),
                info=app_bundle.info_plist(VERSION, icon=bool(icon)))


def step_app_macos(work, out, logs, prep=None):
    icon = work / 'build/AppIcon.icns'
    icon = icon if icon.is_file() else None
    with timed('app: data bundle') as t:
        bundle, t['built'] = data_bundle(work, logs)
    stamp_path = work / f'build/app-stamp-{VERSION}.json'
    with timed('app: assemble and sign') as t:
        want = dict(app_inputs(work, bundle.with_name(bundle.name + '.json'), icon), out=str(out))
        if read_json(stamp_path) == want and out.is_dir() and app_seal_valid(out):
            say(f'7/7 app: {out} is current (same files, valid signature)')
        else:
            say(f'7/7 app: assembling {out}')
            tmp = out.with_name(out.name + '.partial')
            if tmp.exists():
                remove_tree(tmp)
            app_bundle.write_skeleton(tmp, work / app_bundle.launcher(VERSION), icon,
                                      app_bundle.info_plist(VERSION, icon=bool(icon)))
            root = tmp / app_bundle.GAME_ROOT
            for dest, src in app_bundle.game_files(VERSION).items():
                clone(work / src, root / dest)
            copy_tree(work / app_bundle.SHARED_FONTS, root / app_bundle.SHARED_FONTS)
            copy_tree(bundle, tmp / 'Contents/Helpers' / bundle.name)
            link = root / f'{app_bundle.romfs(VERSION)}/romfs.bin'   # where the game opens it (runtime/romfs.c)
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(os.path.relpath(tmp / 'Contents/Helpers' / bundle.name / 'Contents/Resources/romfs.bin', link.parent))
            run(['codesign', '--force', '--sign', '-', tmp], logs / 'sign-app.log')
            notified = 0
            while out.exists() and game_running(out):   # replacing the files of a running game is not safe
                if time.monotonic() - notified >= 60:
                    say('7/7 app: the new app is ready; waiting for the running game to close before replacing it')
                    notified = time.monotonic()
                time.sleep(2)
            with critical():
                kept = install_app(tmp, out)
                for other in work.glob('build/app-stamp*.json'):   # the app at `out` is this version now
                    if other != stamp_path and (read_json(other) or {}).get('out') == str(out):
                        other.unlink()
                stamp_path.write_text(json.dumps(want))
            if kept:
                say('7/7 app: the game data is unchanged; kept the installed copy, so the first start need not verify it again')
            t['built'] = True
    with timed('app: register and first check') as t:
        t['built'] = 'checked'
        run([LSREGISTER, '-f', out], logs / 'register-app.log')
        say('7/7 app: macOS checks the app once (seconds when this app folder was checked before, longer for a new one)')
        r = subprocess.run([out / 'Contents/MacOS' / app_bundle.EXECUTABLE, '--check'], capture_output=True, text=True,
                           timeout=1800)
        if r.returncode:
            raise BuildError(f'the app does not start: {(r.stdout + r.stderr).strip()}')
        if f'game version {DISPLAY} ' not in r.stdout:
            raise BuildError(f'the app reports another version than {DISPLAY}: {r.stdout.strip()}')
        say(f'7/7 app: {r.stdout.strip()}')
    # The prepared shaders (step_shader_prep) go into the player's shader cache, so the game finds them there instead of
    # translating them as it meets them. The app carries no startup seed: a Mac translates what is still missing while
    # playing. Not compiled into Metal's cache ahead (the original project did that for its seed): Metal compiles and
    # caches each one the first time the game uses it.
    if prep is not None:
        merge_into_mac_cache(prep, out)


def merge_stamp(prep, cache):
    """What a finished merge of prep into cache is known by: the prepared shaders (their seed-manifest.json, which names
    every file) and the cache folder itself (deleted and made again, it is another folder). None when prep has no
    manifest. The game only appends to its indexes, so what was merged once stays merged until either changes."""
    try:
        manifest = hashlib.sha256((prep / 'seed-manifest.json').read_bytes()).hexdigest()
        st = cache.stat()
    except OSError:
        return None
    return dict(format=1, prep=str(prep), manifest=manifest, cache=str(cache), dev=st.st_dev, ino=st.st_ino,
                birth=getattr(st, 'st_birthtime', None))


def merge_into_mac_cache(prep, out):
    """The prepared shaders into the player's shader cache, unless the game is running: it keeps the indexes in memory
    and writes them again, which would drop the merged entries (an app that was current had no wait for it to close).
    A merge that left nothing out is stamped beside the cache (<cache>.prep-merge.json): an unchanged rebuild skips it
    instead of reading every index again."""
    if game_running(out):
        say('shaders: the game is running; prepared shaders go into the Mac cache on the next build')
        return
    cache = mac_shader_cache()
    stamp = cache.with_name(cache.name + '.prep-merge.json')
    if (want := merge_stamp(prep, cache)) is not None and read_json(stamp) == want:
        say('shaders: the Mac cache already has the prepared shaders')
        return
    try:
        missed = []
        new = copy_prepared_shaders(prep, cache, missed)
        say(f'shaders: {new} new prepared shaders for the Mac cache')
        with contextlib.suppress(OSError):   # no stamp: the next build merges again, finding nothing new
            if not missed and (want := merge_stamp(prep, cache)) is not None:
                stamp.write_text(json.dumps(want, indent=1))
            else:
                stamp.unlink(missing_ok=True)
    except OSError as e:   # the app is built: the game translates what is missing as it meets it
        say(f'shaders: the prepared shaders could not be copied into the Mac cache ({e}); the game translates them '
            'as it meets them')


# ---- the iPhone / iPad IPA (experimental) ----
IOS = GAME / 'ios'
IOS_EXPERIMENTAL = ('EXPERIMENTAL: an iPhone or iPad cannot translate shaders while playing. The IPA carries every shader '
                    'of the game prepared for its usual case and the cases players have met and shared (the shared shader '
                    'list), plus what this Mac has translated; a draw that needs a case nobody has shared yet is skipped '
                    'until someone shares it (docs/sharing-shaders.md).')


def req_ios_xcode():
    """An Xcode 26+ with the iOS SDK (also outside /Applications); returns its Developer folder and version."""
    sys.path.insert(0, str(IOS / 'tools'))
    from xcode_dir import developer_dir   # noqa: E402  an Xcode with the iOS SDK, also outside /Applications
    try:
        developer = developer_dir()
    except RuntimeError as e:
        raise BuildError(f'--platform ios: {e}') from None
    env = dict(os.environ, DEVELOPER_DIR=developer)
    r = subprocess.run(['xcodebuild', '-version'], capture_output=True, text=True, env=env)
    version = r.stdout.split()[1] if r.returncode == 0 and len(r.stdout.split()) > 1 else '0'
    if int(version.split('.')[0] or 0) < 26:
        raise BuildError(f'--platform ios needs Xcode 26 or later (found {version} in {developer}); install it from the App Store')
    if subprocess.run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], capture_output=True, env=env).returncode:
        raise BuildError(f'the Xcode in {developer} has no iOS SDK: install the iOS platform in Xcode > Settings > Components',
                         ['xcodebuild -downloadPlatform iOS'])
    return developer, version


def req_ios_tools():
    path = os.pathsep.join(TOOL_PATHS + [os.environ.get('PATH', '')])
    missing = [tool for tool in ('xcodegen', 'cmake') if not shutil.which(tool, path=path)]
    if missing:
        raise BuildError(f'--platform ios needs {" and ".join(missing)}: brew install {" ".join(missing)}',
                         [f'brew install {" ".join(missing)}'])
    return ', '.join(f'{t} {shutil.which(t, path=path)}' for t in ('xcodegen', 'cmake'))


def req_ios_platform():
    """The iOS platform component (Xcode > Settings > Components): installing on a device builds for it (its
    provisioning step names the device as the destination). Detected by an available iOS runtime of the SDK's major
    version (xcrun simctl), which the component installs."""
    developer, _ = req_ios_xcode()
    env = dict(os.environ, DEVELOPER_DIR=developer)
    sdk = subprocess.run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-version'], capture_output=True, text=True, env=env).stdout.strip()
    r = subprocess.run(['xcrun', 'simctl', 'list', 'runtimes', '-j'], capture_output=True, text=True, env=env)
    try:
        runtimes = [x for x in json.loads(r.stdout)['runtimes'] if x.get('platform') == 'iOS' and x.get('isAvailable')]
    except (ValueError, KeyError):
        runtimes = []
    major = sdk.split('.')[0]
    match = [x for x in runtimes if str(x.get('version', '')).split('.')[0] == major]
    if not match:
        raise BuildError(f'the iOS {sdk or "?"} platform is not installed in Xcode: Xcode > Settings > Components > iOS '
                         f'{sdk or ""} (Get), or run the command below; the IPA builds without it, but installing on a '
                         'device needs it', ['xcodebuild -downloadPlatform iOS'])
    return f'iOS {match[-1].get("version")} platform'


IOS_REQUIREMENTS = [('Xcode 26 with the iOS SDK', req_ios_xcode, False), ('xcodegen and CMake', req_ios_tools, False),
                    ('iOS platform (Xcode > Settings > Components)', req_ios_platform, False)]


def prerequisites_ios():
    """The Mac's tools (the Mac runtime exports the device's code), plus Xcode 26+ with the iOS SDK, xcodegen and CMake."""
    py = prerequisites()
    developer, version = req_ios_xcode()
    tools = req_ios_tools()
    try:
        platform_note = req_ios_platform()
    except BuildError as e:   # the IPA builds without it; installing on a device needs it
        platform_note = f'note: {e}'
    say(f'iOS: Xcode {version} ({developer}), {tools}; {platform_note}')
    return py


def check_requirements(platform_name):
    """--check-requirements: every requirement of the platform, also past the first one missing, with what to do."""
    checks = MAC_REQUIREMENTS + (IOS_REQUIREMENTS if platform_name == 'ios' else [])
    results, have_tools = [], True
    for name, check_one, needs_tools in checks:
        row = dict(name=name, ok=True, message='', fixes=[])
        if needs_tools and not have_tools:
            row.update(ok=False, message='not checked: needs the Xcode command line tools first')
        else:
            try:
                detail = check_one()
                if isinstance(detail, tuple):
                    detail = f'Xcode {detail[1]} ({detail[0]})'
                row['message'] = str(detail) if detail else ''
            except BuildError as e:
                row.update(ok=False, message=str(e), fixes=e.fixes)
        if check_one is req_clang and not row['ok']:
            have_tools = False
        results.append(row)
        emit('requirement', **row)
    ok = all(r['ok'] for r in results)
    emit('requirements', ok=ok, platform=platform_name)
    if EVENTS is None:
        for r in results:
            print(f'{"ok     " if r["ok"] else "MISSING"}  {r["name"]}' + (f': {r["message"]}' if r['message'] else ''))
            for fix in r['fixes']:
                print(f'          fix: {fix}')
        print('all requirements are met' if ok else 'some requirements are missing')
    return ok


def ios_seed_caches(work, extra, prep=None):
    """The shader caches whose translated variants the IPA carries (read only; a variant in several is taken from the
    first): this build's prepared shaders (step_shader_prep; None when it failed), the player's (what the
    self-contained app translated), the work folder's own (make boot, the development app), the iPhone's earlier misses
    translated by ios/tools/fill_shaders.py, and any --ios-seed-cache folders."""
    chain = shader_chain()
    folders = ([prep] if prep is not None else []) + [
        mac_shader_cache(), work / f'build/shader-cache/rt-{chain}', work / f'build/ios-fill/rt-{chain}']
    for folder in extra:
        folder = folder.expanduser().resolve()
        folders.append(folder / f'rt-{chain}' if (folder / f'rt-{chain}').is_dir() else folder)
    return [f for f in dict.fromkeys(folders) if f.is_dir()]


def step_ipa(work, out, logs, args=None, prep=None):
    with timed('ipa: device build and package') as t:
        say('7/7 ipa: the device code, Opus and libvpx for iOS, the Xcode project and the IPA '
            '(games/xcx/ios/tools/build_ipa.py; the first time several minutes and network access)')
        caches = ios_seed_caches(work, (args.ios_seed_cache if args else None) or [], prep)
        seed = [a for c in caches for a in ('--seed-cache', c)]
        run([sys.executable, IOS / 'tools/build_ipa.py', '--work', work, '--out', out, '--logs', logs, '--version', VERSION,
             '--app-name', APP_NAME, '--bundle-id', app_bundle.BUNDLE_ID, *seed], logs / 'build-ipa.log',
            env=dict(os.environ, PATH=os.pathsep.join(TOOL_PATHS + [os.environ.get('PATH', '/usr/bin:/bin')])))
        for line in (logs / 'build-ipa.log').read_text(errors='replace').splitlines():
            if line.startswith(('shader seed:', 'IPA ready:', 'app ready:')):
                say(f'7/7 ipa: {line}')
        t['built'] = True


# The platforms: each one checks its own requirements and packages the build. The steps before packaging (code, fonts,
# data, prepare) are shared; the Mac runtime, shader tools and launcher are built for both (the iOS build exports the
# device's code with the Mac runtime, takes its icon from the launcher step, and fill_shaders.py uses the shader tools).
PLATFORMS = {
    'macos': dict(output_suffix='.app', requirements=prerequisites, package=step_app_macos, runtime=True),
    'ios': dict(output_suffix='.ipa', requirements=prerequisites_ios, package=step_ipa, runtime=True),
}
# The steps in order, for --progress json's plan (the names timed() reports); 'inputs' and 'requirements' are not timed
STEPS = ['inputs', 'requirements', 'setup: Python environment', 'identify', 'code: ExeFS', 'code: NSO segments',
         'code: rewrite', 'code: rewrite checks', 'fonts', 'data: RomFS', 'prepare', 'runtime', 'shader tools',
         'shaders: prepare', 'launcher and icon']
PACKAGE_STEPS = dict(macos=['app: data bundle', 'app: assemble and sign', 'app: register and first check'],
                     ios=['ipa: device build and package'])


def parse_args(argv):
    ap = argparse.ArgumentParser(
        description=f'Build a native Mac app from your own {GAME_NAME}, update 1.0.1 or 2.0.0: an XCI holding the base '
                    f'game and the 1.0.1 update, optionally with --update <the 2.0.0 update NSP>, or a base NSP with '
                    f'--update <the 1.0.1 or 2.0.0 update NSP>. The version built is the update\'s; building a newer '
                    f'one to the same app updates it and keeps the saves.',
        epilog='examples: python3 build_app.py "personal/Xenoblade Chronicles X Definitive Edition.xci" -k personal/prod.keys'
               '  (1.0.1);  add --update personal/xcx200.nsp for 2.0.0')
    ap.add_argument('game', type=Path, help='the game file: an XCI holding base v0 and update 1.0.1, or the base game NSP / XCI')
    ap.add_argument('-k', '--keys', type=Path, required=True, help='your prod.keys')
    ap.add_argument('--update', type=Path, help='an update NSP, 1.0.1 or 2.0.0 (with an XCI: only for 2.0.0, which then '
                                                'wins over the 1.0.1 update inside it)')
    ap.add_argument('--firmware', type=Path, help='folder of your firmware\'s NCA files, for the system shared fonts '
                                                   '(needed for an NSP; an XCI carries them in its system update)')
    ap.add_argument('--title-keys', type=Path, help='your title.keys, for NSPs without a common ticket')
    ap.add_argument('-o', '--out', type=Path, help=f'the app or IPA to write (default: "<game file folder>/{APP_NAME}.app", '
                                                   f'or .ipa with --platform ios)')
    ap.add_argument('--work', type=Path, help=f'work folder (default: {WORK_NAME} at the repository root, next to build_app.py)')
    ap.add_argument('--platform', choices=('macos', 'ios'), default='macos',
                    help='macos (default), or ios: an unsigned iPhone / iPad IPA for sideloading (EXPERIMENTAL: a draw '
                         'needing a shader case nobody has shared yet is skipped)')
    ap.add_argument('--delete-work', action='store_true',
                    help='delete the work folder once the app (or IPA) is built and its final check passed (only a work '
                         'folder build_app.py made; never on a failure or a cancel). A later build starts from scratch '
                         '(about 8 minutes); the app\'s game data are APFS clones, so their space returns only when the '
                         'app is deleted too')
    ap.add_argument('--ios-seed-cache', type=Path, action='append',
                    help='iOS: another Mac shader cache folder whose translated variants the IPA carries (read only); repeatable')
    ap.add_argument('--offline', action='store_true',
                    help='do not download the newest shared shader list; use the one cached by an earlier build, or the '
                         'one in the project')
    add_window_options(ap)
    return ap.parse_args(argv)


def add_window_options(ap):
    ap.add_argument('--gui', action='store_true', help='open a window that builds the app without the command line '
                                                       '(compiled from games/xcx/builder on first use)')
    ap.add_argument('--progress', choices=('text', 'json'), default='text',
                    help='json: one JSON object a line on stdout (steps, times, error, output) and the human output on '
                         'stderr, for the window; SIGTERM then cancels cleanly')
    ap.add_argument('--check-requirements', action='store_true',
                    help='check this Mac\'s requirements for --platform (all of them, with what to do) and exit')
    ap.add_argument('--identify', action='store_true',
                    help='only report what the game file and --update are (base, update version) and the version of '
                         'the app at -o, then exit (needs -k; with --progress json: one "identified" event a file)')


def parse_mode(argv):
    """--gui and --check-requirements need no game file: read them (and --progress, --platform) before the full parser."""
    ap = argparse.ArgumentParser(add_help=False)   # no choices here: a wrong value is the full parser's to report
    ap.add_argument('--platform', default='macos')
    ap.add_argument('--progress', default='text')
    ap.add_argument('--gui', action='store_true')
    ap.add_argument('--check-requirements', action='store_true')
    ap.add_argument('--identify', action='store_true')
    mode = ap.parse_known_args(argv)[0]
    if mode.check_requirements and (mode.platform not in PLATFORMS or mode.progress not in ('text', 'json')):
        parse_args(argv)   # reports the wrong value
    return mode


# ---- the window (games/xcx/builder) ----
BUILDER = GAME / 'builder'
BUILDER_CACHE = Path.home() / app_bundle.CACHES / 'xcx-builder'
BUILDER_NAME = 'XCX Builder'


def builder_app():
    """The window's app, compiled with xcrun swiftc (the command line tools are enough; no Xcode project) into the
    per-user cache, in a folder named by the hash of its sources and the compiler, so it is compiled again only when
    one of them changes."""
    swiftc = subprocess.run(['xcrun', '--find', 'swiftc'], capture_output=True, text=True)
    if swiftc.returncode:
        raise BuildError('the window needs swiftc from the Xcode command line tools: xcode-select --install')
    sources = sorted(BUILDER.glob('*.swift'))
    h = hashlib.sha256(subprocess.run(['xcrun', 'swiftc', '--version'], capture_output=True, text=True).stdout.encode())
    for path in sources + [BUILDER / 'Info.plist']:
        h.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    folder = BUILDER_CACHE / h.hexdigest()[:16]
    app = folder / f'{BUILDER_NAME}.app'
    if (app / 'Contents/MacOS/XCXBuilder').is_file():
        return app
    say(f'compiling the window ({len(sources)} Swift files, once; {BUILDER.relative_to(REPO)})')
    tmp = folder.with_name(folder.name + '.partial')
    if tmp.exists():
        shutil.rmtree(tmp)
    binary = tmp / f'{BUILDER_NAME}.app/Contents/MacOS/XCXBuilder'
    binary.parent.mkdir(parents=True)
    log = tmp / 'swiftc.log'
    run(['xcrun', 'swiftc', '-O', '-parse-as-library', '-target', 'arm64-apple-macos26.0', '-module-name', 'XCXBuilder',
         '-o', binary, *sources], log, quiet=False)
    shutil.copy2(BUILDER / 'Info.plist', binary.parent.parent / 'Info.plist')
    run(['codesign', '--force', '--sign', '-', binary.parent.parent.parent], tmp / 'codesign.log', quiet=False)
    for old in BUILDER_CACHE.iterdir():   # earlier versions of the window
        if old.is_dir() and old != tmp:
            shutil.rmtree(old, ignore_errors=True)
    tmp.rename(folder)
    return app


def open_gui():
    """Compile (if needed) and open the window; it runs this script with the Python that runs it now."""
    app = builder_app()
    # The test hook (XCX_BUILDER_TEST_*, games/xcx/builder/TestHook.swift) is passed through for verification only
    env = [a for k, v in os.environ.items() if k.startswith('XCX_BUILDER_TEST_') for a in ('--env', f'{k}={v}')]
    # no -n: a second --gui brings the open window forward instead of starting a second build into the same work folder
    subprocess.run(['open', *env, app, '--args', '--script', str(Path(__file__).resolve()), '--python', sys.executable],
                   check=True)
    say(f'opened {BUILDER_NAME} ({app})')


def use_library():
    """Before the build reads or writes the user's Library (after the arguments are checked, so --help or a wrong one
    moves nothing): the MacNativeGames data and log folders moved to XCNative once (app_bundle.migrate_library). The
    paths in it are resolved at each use (app_bundle.data_folder(), contribution.mac_file())."""
    return app_bundle.migrate_library(log=lambda m: say(f'Library: {m}'))


def main(argv):
    t0 = time.time()
    mode = parse_mode(argv)
    if mode.progress == 'json':
        progress_json()
    if mode.gui:
        return open_gui()
    if mode.check_requirements:
        return 0 if check_requirements(mode.platform) else 1
    args = parse_args(argv)
    use_library()
    if args.identify:
        return identify_only(args)
    # the version is the update's, known once identify has read the files: the plan lists the supported ones, and the
    # start event (after identify) names the one being built
    emit('plan', platform=args.platform, versions=[dict(version=v, display=row['display'],
                                                        update_version=row['update_version'])
                                                   for v, row in app_bundle.VERSIONS.items()],
         steps=STEPS + PACKAGE_STEPS[args.platform] + (['delete work folder'] if args.delete_work else []))
    with timed('inputs', record=False) as t:
        t['built'] = 'checked'
        plat, out, work, kind = check_inputs(args)
    with timed('requirements', record=False) as t:
        t['built'] = 'checked'
        logs = requirements(args, plat, out, work)
    build_all(args, plat, out, work, logs, t0)


def check_inputs(args):
    plat = PLATFORMS[args.platform]
    for name in ('game', 'keys', 'update', 'title_keys'):
        path = getattr(args, name)
        if path is not None:
            path = path.expanduser().resolve()
            if not path.is_file():
                raise BuildError(f'no such file: {path}')
            setattr(args, name, path)
    if args.firmware:
        args.firmware = args.firmware.expanduser().resolve()
        if not args.firmware.is_dir():
            raise BuildError(f'--firmware must be a folder of firmware NCA files: {args.firmware}')
    kind = input_kind(args.game)
    if args.update:
        if args.update == args.game:
            raise BuildError('--update is the game file itself: an XCI that holds the update needs no --update')
        if input_kind(args.update) != 'nsp':
            raise BuildError(f'--update must be an update NSP (1.0.1 or 2.0.0): {args.update.name}')
    # an NSP without --update is named by identify (a base-only NSP needs an update; an update NSP is not the game file)
    out = args.out.expanduser().resolve() if args.out else args.game.parent / f'{APP_NAME}{plat["output_suffix"]}'
    if out.suffix != plat['output_suffix']:
        raise BuildError(f'the {args.platform} output must end in {plat["output_suffix"]}: {out}')
    work = args.work.expanduser().resolve() if args.work else REPO / WORK_NAME
    fonts_cached = (work / 'extracted/firmware/shared-fonts/manifest.json').is_file()
    if kind == 'nsp' and not args.firmware and not fonts_cached:
        raise BuildError('NSPs do not carry the system shared fonts: pass --firmware <folder of your firmware\'s NCA files>')
    if args.delete_work:
        reason = delete_work_refusal(work, out, work_inputs(args), finished=False)
        if reason:
            raise BuildError(f'--delete-work: {reason}; nothing was built. Choose another --work, or build without --delete-work')
    return plat, out, work, kind


def work_inputs(args):
    return [args.game, args.keys, args.update, args.title_keys, args.firmware]


def requirements(args, plat, out, work):
    if args.platform == 'ios':
        say(IOS_EXPERIMENTAL)
    args.python = plat['requirements']()
    logs = work / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    say(f'work folder {work} ({free_gb(work):.0f} GB free on its volume)')
    return logs


def check_space(args, out, work):
    """Free space for the version being built (after identify): its RomFS image, unless already merged."""
    romfs_done = (work / f'{app_bundle.romfs(VERSION)}/romfs.bin').is_file()
    need = 3 if romfs_done else EXPECTED['romfs']['size'] / GB + 3
    if free_gb(work) < need:
        raise BuildError(f'needs about {need:.0f} GB free for the work folder ({free_gb(work):.1f} GB free): the '
                         f'{DISPLAY} RomFS image takes 14.3 GB (each version has its own, in extracted/<version>/romfs); '
                         'the app itself is an APFS clone of it when on the same volume')
    if args.platform == 'macos' and os.stat(existing(out.parent)).st_dev != os.stat(existing(work)).st_dev and \
            free_gb(out.parent) < EXPECTED['romfs']['size'] / GB + 1:
        raise BuildError(f'{out.parent} is on another volume than the work folder, so the app is a full copy there '
                         f'(about 15 GB); it has {free_gb(out.parent):.1f} GB free')


def profile_folder():
    return app_bundle.data_folder() / 'profile'


def has_saves(profile):
    return (profile / 'save').is_dir() and any(p.is_file() for p in (profile / 'save').rglob('*'))


def backup_command(profile, installed):
    """The command that copies the profile (saves) aside, named after the version that wrote it: the installed app's
    when the build replaces it with another version, else just 'saves'."""
    stamp = time.strftime('%Y-%m-%d')
    label = installed[1] if installed and installed[0] != VERSION else 'saves'
    return f'cp -R "{profile}" "{profile.parent / f"profile-{label}-backup-{stamp}"}"'


def update_notice(args, out):
    """What replacing the app at `out` means for the player, said before the long steps: the version it replaces, that
    the saves stay (they are in the user's Library, not in the app), and the one-way save warning for 2.0.0. Returns
    the installed app's version (folder, display) or None."""
    installed = app_bundle.app_version(out) if args.platform == 'macos' and out.is_dir() else None
    profile = profile_folder()
    saves = has_saves(profile)
    command = backup_command(profile, installed)
    if installed and installed[0] != VERSION:
        newer = version_order(VERSION) > version_order(installed[0])
        say(f'{"updating" if newer else "replacing"} the app {out}: {installed[1]} -> {DISPLAY}. The app is replaced; '
            f'the saves are not in it ({profile}), so {DISPLAY} continues from them.')
        if newer and saves:
            say(f'SAVES: once {DISPLAY} has loaded and saved a game, that save may not load in {installed[1]} again. '
                f'To be able to go back, copy the profile before the first start of {DISPLAY}:')
            say(f'   {command}')
        elif not newer and saves:
            say(f'SAVES: the profile may hold saves written by {installed[1]}, which {DISPLAY} may not read. If you made '
                f'a backup of the profile before updating, restore it before playing {DISPLAY} (move the current '
                f'profile aside first).')
    elif installed:
        say(f'rebuilding the {DISPLAY} app {out}; the saves ({profile}) are not touched')
    elif out.exists() and args.platform == 'macos':
        say(f'replacing {out} (its version is not known); the saves ({profile}) are not touched')
    if VERSION != app_bundle.DEFAULT_VERSION and saves and not (installed and installed[0] != VERSION):
        say(f'SAVES: a save that {DISPLAY} has loaded and saved may not load in 1.0.1 again; to keep a way back, copy '
            f'the profile first: {command}')
    return installed, saves, command


def build_all(args, plat, out, work, logs, t0):
    py = args.python
    env = dict(os.environ, PATH=os.pathsep.join(TOOL_PATHS + [os.environ.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')]))
    with timed('setup: Python environment') as t:
        vpy, t['built'] = prepare_venv(work, py, logs)
    with timed('identify') as t:
        update_source, _ = identify(vpy, logs, args.game, args.update, args.keys, args.title_keys)
        check_space(args, out, work)
        installed, saves, command = update_notice(args, out)
        t['built'] = 'checked'
    emit('start', platform=args.platform, game=str(args.game), update=str(args.update) if args.update else None,
         update_source=str(update_source), out=str(out), work=str(work), version=VERSION, display=DISPLAY,
         installed=dict(version=installed[0], display=installed[1]) if installed else None,
         profile=str(profile_folder()), saves=saves, backup_command=command if saves else None)
    build = Build(args, work, vpy, logs, env)
    build.step_code(update_source)
    build.step_fonts()
    build.step_data()
    build.step_prepare()
    build.step_runtime()
    build.step_shader_tools()
    pulled = pull_ios_contribution() if args.platform == 'ios' else 0
    prep = step_shader_prep(work, logs, vpy, args.offline)
    build.step_launcher()
    if args.platform == 'ios':
        step_ipa(work, out, logs, args, prep)
        total = time.time() - t0
        say_times(work, total)
        # the iPhone's rows when this build brought some (the file may hold the Mac's too: then the player picks)
        report_contribution(work, 'iPhone' if pulled else None)   # before the work folder (and its list) may go
        if args.delete_work:
            delete_work(work, out, work_inputs(args), 'ios')
        say(f'done in {total / 60:.1f} min: {out} ({DISPLAY})')
        emit('done', platform='ios', out=str(out), work=str(work), seconds=round(total, 1), version=VERSION, display=DISPLAY)
        say(IOS_EXPERIMENTAL)
        say('The IPA is unsigned: sign and install it with your own Apple ID (python3 games/xcx/ios/tools/install_device.py '
            f'"{out}" --device "<device name>" --game-data "{work / app_bundle.romfs(VERSION) / "romfs.bin"}") or with a '
            'sideloading tool that keeps its entitlements. It holds no game image: install_device.py --game-data copies the '
            '14.3 GB RomFS once into the app\'s Documents/GameData, or drag romfs.bin onto the app in Finder (the device > '
            'Files). Needs iOS / iPadOS 27 (on 26 it closes at start) and an iPhone 14 or newer. The app holds the game code: keep it for your own use, '
            'never share it.')
        return
    plat['package'](work, out, logs, prep=prep)
    total = time.time() - t0
    say_times(work, total)
    report_contribution(work)   # before the work folder (and the list it cached) may go
    if args.delete_work:
        delete_work(work, out, work_inputs(args), 'macos')
    updated = installed and installed[0] != VERSION
    say(f'done in {total / 60:.1f} min: {out} ({DISPLAY}' + (f', was {installed[1]})' if updated else ')'))
    emit('done', platform='macos', out=str(out), work=str(work), seconds=round(total, 1), version=VERSION, display=DISPLAY,
         replaced=dict(version=installed[0], display=installed[1]) if updated else None)
    say('Open it from Finder (it may be moved, also to /Applications). Saves, the shader cache and the log go to '
        '~/Library/Application Support/XCNative/XCX and ~/Library/Logs/XCNative/xcx.log. The first start '
        'verifies the game data once (about 10 s) and keeps a record; shaders are translated as the game meets them '
        'and cached. The app holds the game: keep it for your own use, never share it.')
    if updated and saves and version_order(VERSION) > version_order(installed[0]):
        say(f'Updated from {installed[1]} to {DISPLAY}: the saves continue. Back them up before the first start if you '
            f'may want {installed[1]} again: {command}')


def identify_only(args):
    """--identify: what the files are and the version of the app at the output, for the window (no build)."""
    for name in ('game', 'keys', 'update'):
        path = getattr(args, name)
        if path is not None:
            setattr(args, name, path.expanduser().resolve())
    work = args.work.expanduser().resolve() if args.work else REPO / WORK_NAME
    out = args.out.expanduser().resolve() if args.out else args.game.parent / f'{APP_NAME}.app'
    installed = app_bundle.app_version(out) if out.suffix == '.app' and out.is_dir() else None
    emit('identified', role='output', file=str(out), exists=out.exists(),
         version=installed[0] if installed else None, display=installed[1] if installed else None)
    files = [(role, path) for role, path in (('game', args.game), ('update', args.update)) if path is not None]
    missing = [(role, path) for role, path in files if not path.is_file()]
    for role, path in missing:
        emit('identified', role=role, file=str(path), error='no such file')
    files = [f for f in files if f not in missing]
    if not files:
        return 1 if missing else 0
    if not args.keys or not args.keys.is_file():
        for role, path in files:
            emit('identified', role=role, file=str(path), error='choose prod.keys to read the version')
        return 1
    logs = work / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    vpy, _ = prepare_venv(work, req_python(), logs)
    try:
        reports = read_reports(vpy, logs, [p for _, p in files], args.keys, 'identify-window.log')
    except BuildError as e:
        for role, path in files:
            emit('identified', role=role, file=str(path), error=str(e).splitlines()[0])
        return 1
    for (role, path), r in zip(files, reports):
        if 'error' in r:
            emit('identified', role=role, file=str(path), error=r['error'])
            say(f'{path.name}: {r["error"]}')
            continue
        base = any(m['type'] == 0x80 and m['title_id'] == BASE_TITLE for m in r['metas'])
        patches = own_patches(r)
        number = patches[0]['version'] if patches else None
        version = app_bundle.by_update_version(number) if number is not None else None
        other = None if base or patches else describe_titles(r)
        emit('identified', role=role, file=str(path), container=r['container'], base=base, update_version=number,
             version=version, display=app_bundle.display(version) if version else None,
             supported=number is None or version is not None, other=other)
        say(f'{path.name}: {r["container"].upper()}' + (', base v0' if base else '')
            + (f', update {app_bundle.describe(number)}' + ('' if version else ' (not supported)') if number is not None else '')
            + (f', {other}' if other else ''))
    say(f'{out}: ' + (f'app {installed[1]}' if installed else 'an app of unknown version' if out.exists() else 'not built yet'))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except BuildError as e:
        print(f'\nERROR: {e}', file=sys.stderr)
        emit('error', step=CURRENT[0], message=str(e), log=str(e.log) if e.log else None, fixes=e.fixes)
        sys.exit(1)
    except KeyboardInterrupt:
        emit('cancelled', step=CURRENT[0])
        sys.exit(130)
