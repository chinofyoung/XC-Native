#!/usr/bin/env python3
"""Sign the unsigned Xenoblade Chronicles X IPA with your own Xcode team and install it on a connected iPhone / iPad.

Restored from the original project's games/totk/ios/tools/install_device.py and adapted for this port (EXPERIMENTAL; used
to install the IPA on an iPhone 15 Pro Max with a free Apple ID, 2026-10-23).

A free (Personal Team) Apple ID signs for 7 days, a paid membership for a year: run this again to renew. Reinstalling
with the same team and bundle identifier keeps the saves and the shader cache (they are in the app's Documents).
Until 2026-10-24 the identifier was org.macnativegames.xcx(.<team>); iOS treats the new org.xcnative.xcx.<team> as
another app with empty Documents, so the first install of it copies the old app's saves, shader cache, shader list
contribution, shader requests and Settings choices over (carry_over; not GameData, which --game-data copies). The old
app and its data stay on the device: delete the old app yourself once the new one has your saves.

  python3 games/xcx/ios/tools/install_device.py "Xenoblade Chronicles X.ipa" --device "<device name>" \
      --game-data <work folder>/extracted/<v101 | v200>/romfs/romfs.bin

The IPA carries no 14.3 GB game image: --game-data copies it once into the app's Documents/GameData in 1 GiB parts
(devicectl drops the connection on one file that size); a later install skips it while the device holds the same image
(romfs.sha256 there).

Xcode needs your Apple ID (Xcode > Settings > Accounts) with an Apple Development certificate (Manage Certificates >
+ > Apple Development), and the iOS platform (Xcode > Settings > Components). The provisioning profile comes from a
throwaway Xcode project built with the same bundle identifier and entitlements (-allowProvisioningUpdates registers the
device and the App ID). The device must be unlocked, and Xcode's Devices window may need to finish "Preparing" it first.

  --list-devices   only list the paired iPhones / iPads and the Apple Development teams, then exit
  --dry-run        check the IPA, team, device and game data, then stop before the profile and signing
  --progress json  one JSON object a line on stdout (devices, teams, step running / done / failed, part N/M of the
                   game data, error with what to do, done), the human output on stderr; the build window uses it
"""
import argparse, hashlib, json, os, plistlib, re, shutil, subprocess, sys, tempfile, zipfile
from datetime import timezone
from pathlib import Path

ENTITLEMENT = 'com.apple.developer.kernel.increased-memory-limit'
CACHE = Path.home()/'Library/Caches/XCNative/ios-signing'
BUNDLE_PREFIX = 'org.xcnative.xcx'          # + .<team id, lowercase>
OLD_BUNDLE_PREFIX = 'org.macnativegames.xcx'  # until 2026-10-24

EVENTS = None   # the real stdout with --progress json
STEP = [None]


class Fail(Exception):
    """A stop with what is wrong and, when known, what to do (hint)."""
    def __init__(self, msg, hint=None):
        super().__init__(msg); self.hint = hint


def emit(event, **fields):
    if EVENTS is not None:
        EVENTS.write(json.dumps(dict(event=event, **fields)) + '\n'); EVENTS.flush()


def say(msg): print(msg, flush=True)


def step(name):
    if STEP[0]: emit('step', step=STEP[0], status='done')
    STEP[0] = name; emit('step', step=name, status='running')


UNLOCK = ('Unlock the iPhone / iPad and keep it unlocked. If Xcode is preparing the device (Xcode > Window > Devices and '
          'Simulators shows "Preparing"), wait until it has finished, then try again.')


MAX_APPS = ('A free Apple ID can have at most 3 sideloaded apps on a device. Remove one you do not need, or use a paid '
            'developer account. Deleting an app on the iPhone deletes its saves and data, so do not delete an older '
            'Xenoblade Chronicles X install to make room: this tool installs over it.')


def explain(text):
    """What to do for the failures devicectl and xcodebuild are known to report."""
    low = text.lower()
    if '0xe8008021' in low or '-402620383' in low or 'maximum number of apps' in low: return MAX_APPS
    if 'unlock' in low or 'preparation error' in low or 'passcode' in low or 'locked' in low: return UNLOCK
    if 'developer mode' in low: return 'Turn on Developer Mode on the device: Settings > Privacy & Security > Developer Mode, then restart it.'
    if 'no account' in low or 'no signing certificate' in low or 'no profiles for' in low:
        return 'Add your Apple ID in Xcode > Settings > Accounts, then Manage Certificates > + > Apple Development.'
    if 'platform' in low and ('not installed' in low or 'download' in low):
        return 'Install the iOS platform in Xcode > Settings > Components (or: xcodebuild -downloadPlatform iOS).'
    return None


def run(cmd, **kw):
    """Run a tool; on failure stop with its own words (the last lines of its output) and what to do."""
    kw.setdefault('capture_output', True)
    r = subprocess.run([str(x) for x in cmd], text=True, **kw)
    if r.returncode:
        text = ((r.stdout or '') + (r.stderr or '')).strip()
        tail = '\n'.join([l for l in text.splitlines() if l.strip()][-8:])
        raise Fail(f'{Path(str(cmd[0])).name} {" ".join(str(c) for c in cmd[1:3])} failed: {tail}', explain(text))
    return r
def out(cmd): return run(cmd).stdout

def teams():
    pems = out(['security','find-certificate','-a','-c','Apple Development','-p'])
    found = set()
    for pem in re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', pems, re.S):
        subject = subprocess.run(['openssl','x509','-noout','-subject'], input=pem, capture_output=True, text=True).stdout
        if m := re.search(r'OU\s*=\s*([A-Z0-9]{10})', subject): found.add(m.group(1))
    return sorted(found)

def devices():
    with tempfile.NamedTemporaryFile(suffix='.json') as f:
        run(['xcrun','devicectl','list','devices','--json-output',f.name], capture_output=True)
        return [d for d in json.load(open(f.name))['result']['devices']
                if d.get('hardwareProperties',{}).get('platform') == 'iOS']

def describe(d):
    hp, dp, cp = d.get('hardwareProperties', {}), d.get('deviceProperties', {}), d.get('connectionProperties', {})
    return dict(name=dp.get('name'), model=hp.get('marketingName') or hp.get('productType'), identifier=d.get('identifier'),
                udid=hp.get('udid'), os=dp.get('osVersionNumber'), pairing=cp.get('pairingState'),
                tunnel=cp.get('tunnelState'), developer_mode=dp.get('developerModeStatus'))

def pick_device(name):
    devs = devices()
    match = [d for d in devs if name in (d['deviceProperties'].get('name'), d['identifier'], d['hardwareProperties'].get('udid'))] if name else devs
    if len(match) != 1:
        listed = '\n'.join(f"  {d['deviceProperties'].get('name')} ({d['hardwareProperties'].get('marketingName')})" for d in devs)
        if not devs: raise Fail('no paired iPhone / iPad found', 'Connect it with a cable, unlock it and tap Trust on it.')
        raise Fail(f'no device named {name!r}' if name else 'several devices are paired', f'choose the device with --device <name>:\n{listed}')
    return match[0]

def profile(team, bundle_id, udid):
    """Build an empty app with the game's bundle identifier and entitlements; Xcode makes the profile for it."""
    proj = CACHE/bundle_id; proj.mkdir(parents=True, exist_ok=True)
    (proj/'main.m').write_text('int main(void) { return 0; }\n')
    (proj/'XCX.entitlements').write_bytes(plistlib.dumps({ENTITLEMENT: True}))
    (proj/'project.yml').write_text(f'''name: XCXSigning
options: {{deploymentTarget: {{iOS: "26.0"}}}}
targets:
  XCX:
    type: application
    platform: iOS
    sources: [main.m]
    settings:
      GENERATE_INFOPLIST_FILE: YES
      PRODUCT_BUNDLE_IDENTIFIER: {bundle_id}
      DEVELOPMENT_TEAM: {team}
      CODE_SIGN_STYLE: Automatic
      CODE_SIGN_ENTITLEMENTS: XCX.entitlements
''')
    run(['xcodegen','generate','--quiet'], cwd=proj)
    derived = proj/'derived'
    log = proj/'xcodebuild.log'
    with log.open('w') as f:
        r = subprocess.run(['xcodebuild','-project','XCXSigning.xcodeproj','-scheme','XCX','-configuration','Debug',
                            '-destination',f'id={udid}','-derivedDataPath',str(derived),
                            '-allowProvisioningUpdates','-allowProvisioningDeviceRegistration','build'],
                           cwd=proj, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode:
        text = log.read_text(errors='replace')
        errors = [l for l in text.splitlines() if 'error:' in l]
        raise Fail('Xcode could not make a provisioning profile:\n' + '\n'.join(errors[-8:]) + f'\nfull log: {log}', explain(text))
    app = derived/'Build/Products/Debug-iphoneos/XCX.app'
    return app/'embedded.mobileprovision', app

def identity_of(signed_app):
    """The SHA-1 of the certificate Xcode signed the empty app with: the same identity signs the game."""
    with tempfile.TemporaryDirectory() as d:
        run(['codesign','-d','--extract-certificates='+d+'/cert','-v',signed_app], capture_output=True)
        der = Path(d+'/cert0').read_bytes()
    return hashlib.sha1(der).hexdigest().upper()

PART = 1 << 30
def device_files(dev, bundle_id, sub):
    """{name: size} of the app's Documents/<sub> on the device, {} when there is none."""
    with tempfile.NamedTemporaryFile(suffix='.json') as f:
        r = subprocess.run(['xcrun','devicectl','device','info','files','--device',dev,'--domain-type','appDataContainer',
                            '--domain-identifier',bundle_id,'--subdirectory',sub,'--json-output',f.name], capture_output=True)
        if r.returncode: return {}
        files = json.load(open(f.name)).get('result', {}).get('files', [])
    return {Path(x.get('relativePath', x.get('name', ''))).name: x.get('metadata', {}).get('size', 0) for x in files}   # devicectl's JSON

def push_game_data(dev, bundle_id, image):
    """The RomFS image into Documents/GameData as romfs.bin.000, .001, ... (ios/Sources/main.m reads it there), then
    romfs.sha256 naming it, so the next install skips it."""
    sha = json.loads((image.parent/'index.json').read_text())['romfs_sha256']
    size = image.stat().st_size; parts = (size + PART - 1) // PART
    have = device_files(dev, bundle_id, 'Documents/GameData')
    if have.get('romfs.sha256') == 64 + 1 and all(f'romfs.bin.{i:03d}' in have for i in range(parts)):
        with tempfile.TemporaryDirectory() as d:
            got = Path(d)/'romfs.sha256'
            r = subprocess.run(['xcrun','devicectl','device','copy','from','--device',dev,'--domain-type','appDataContainer',
                                '--domain-identifier',bundle_id,'--source','Documents/GameData/romfs.sha256','--destination',got], capture_output=True)
            if r.returncode == 0 and got.read_text().strip() == sha:
                print('game data: the device already has this image'); emit('part', part=parts, parts=parts, skipped=True); return
    print(f'game data: copying {size / 2**30:.1f} GiB in {parts} parts (once; later installs keep it)')
    with tempfile.TemporaryDirectory() as d, open(image, 'rb') as src:
        def copy(local, name):
            run(['xcrun','devicectl','device','copy','to','--device',dev,'--domain-type','appDataContainer','--domain-identifier',
                 bundle_id,'--source',local,'--destination',f'Documents/GameData/{name}'], capture_output=True)
        (Path(d)/'romfs.sha256').write_text('stale\n'); copy(Path(d)/'romfs.sha256', 'romfs.sha256')   # until every part is there
        for i in range(parts):
            part = Path(d)/f'romfs.bin.{i:03d}'
            part.write_bytes(src.read(PART)); copy(part, part.name); part.unlink()
            print(f'  part {i + 1}/{parts}', flush=True); emit('part', part=i + 1, parts=parts)
        (Path(d)/'romfs.sha256').write_text(sha + '\n'); copy(Path(d)/'romfs.sha256', 'romfs.sha256')

# What the app keeps in its Documents (ios/Sources/main.m) that a reinstall under a new identifier would lose: the saves
# (TOTK_PROFILE_DIR), the shader cache, the shader list contribution, the shader requests (fill_shaders.py). Not
# GameData: --game-data copies it from the Mac. The Settings app's choices (language, frame rate) are the app's
# preferences file, named after its identifier.
CARRY = ('Documents/save', 'Documents/shader-cache', 'Documents/shader-list-contribution.txt', 'Documents/shader-requests')
CARRIED = 'Documents/migrated-from.txt'   # written last: the copy is done once
# not copied over what the new app already has (an install that retries: the player may have changed Settings there)
KEEP_NEW = ('Documents/shader-cache', 'Documents/shader-list-contribution.txt')


def old_bundle_ids(bundle_id):
    """The identifiers the same app had until 2026-10-24: org.xcnative.xcx.<team> -> org.macnativegames.xcx.<team>, then
    org.macnativegames.xcx. Another identifier (--bundle-id): none."""
    if bundle_id != BUNDLE_PREFIX and not bundle_id.startswith(BUNDLE_PREFIX + '.'):
        return []
    return list(dict.fromkeys([OLD_BUNDLE_PREFIX + bundle_id[len(BUNDLE_PREFIX):], OLD_BUNDLE_PREFIX]))


def app_installed(dev, bundle_id):
    """True when the device (identifier) holds an app with this identifier. `devicectl device info apps` listed nothing on
    a real phone, so ask for the app's Documents folder instead: it fails for an app that is not there (and for every app
    while the phone is locked, which then counts as not installed)."""
    try:
        r = subprocess.run(['xcrun','devicectl','device','info','files','--device',dev,'--domain-type','appDataContainer',
                            '--domain-identifier',bundle_id,'--subdirectory','Documents'], capture_output=True, text=True)
    except OSError:
        return False
    return r.returncode == 0


def choose_bundle_id(team, given, installed):
    """(bundle id, the old identifier it reuses or None). --bundle-id is used as it is. Otherwise org.xcnative.xcx.<team>;
    when that is not on the device but the app is there under an old identifier, that one, so the install goes over it
    (saves and game data stay, no extra app slot). `installed(bundle_id)` says whether the device has it."""
    if given: return given, None
    new = f'{BUNDLE_PREFIX}.{team.lower()}'
    if installed(new): return new, None
    for old in old_bundle_ids(new):
        if installed(old): return old, old
    return new, None


def container_copy(direction, dev, bundle_id, source, destination):
    """devicectl device copy from / to an app's data container; what subprocess.run returns (never raises for a
    failed copy)."""
    return subprocess.run(['xcrun','devicectl','device','copy',direction,'--device',dev,'--domain-type','appDataContainer',
                           '--domain-identifier',bundle_id,'--source',str(source),'--destination',str(destination)],
                          capture_output=True, text=True)


def has_files(path):
    path = Path(path)
    return path.is_file() or (path.is_dir() and any(p.is_file() for p in path.rglob('*')))


NOT_FOUND = ('not found', 'could not be found', 'no such file', 'does not exist', "doesn't exist", 'not exist')


def not_found(r):
    """A devicectl copy that failed only because the item is not there."""
    text = f'{r.stderr or ""}\n{r.stdout or ""}'.lower()
    return any(k in text for k in NOT_FOUND)


def last_line(r):
    lines = (r.stderr or r.stdout or '').strip().splitlines()
    return lines[-1].strip() if lines else 'devicectl failed'


def save_by_hand(old, new):
    return (f'Copy the saves by hand: in Finder select the device > Files, drag the "save" folder out of the app '
            f'installed as {old} onto the Mac, then drag it onto the app installed as {new} (both are named '
            '"Xenoblade Chronicles X"; the old one is the one with the saves). Or on the device, Files > On My iPhone: '
            'copy save from the old app\'s folder into the new one\'s. Keep the old app until the new one shows the saves.')


def carry_over(dev, bundle_id, report=None):
    """After installing `bundle_id`: when the device still has the app under an old identifier (old_bundle_ids), copy its
    saves, shader cache, contribution, requests and Settings choices (CARRY) to the new app. Only when the new app's
    save folder is known to be empty (copied and empty, or plainly not there); any other answer skips it. When both old
    identifiers are installed, the one with saves is used. The saves are checked after the copy (a file read back from
    the new app); only then is CARRIED written, so a copy that did not complete is tried again at the next install.
    Nothing on the device is deleted. Best effort: a failure is a warning (report, default: printed), never a stop.
    Returns the old identifier and the items copied, or None."""
    report = report or (lambda m: say(f'warning: {m}'))
    olds = old_bundle_ids(bundle_id)
    if not olds:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix='xcx-carry-') as tmp:
            tmp = Path(tmp)
            if container_copy('from', dev, bundle_id, CARRIED, tmp/'carried').returncode == 0 and (tmp/'carried').is_file():
                return None   # done at an earlier install
            mine = tmp/'mine'
            r = container_copy('from', dev, bundle_id, 'Documents/save', mine)
            if r.returncode == 0 and has_files(mine):
                say(f'saves: {bundle_id} has saves of its own, so nothing is copied from the old identifier')
                return None
            if r.returncode and not not_found(r):
                report(f'could not tell whether {bundle_id} has saves ({last_line(r)}), so nothing is copied from the '
                       f'old identifier. {save_by_hand(" / ".join(olds), bundle_id)}')
                return None
            found = {}   # old id -> [(item, destination, local copy)]
            for old in olds:
                items = [(item, item) for item in CARRY] + [(f'Library/Preferences/{old}.plist',
                                                             f'Library/Preferences/{bundle_id}.plist')]
                got = []
                for i, (item, dest) in enumerate(items):
                    local = tmp/old/f'{i}-{Path(item).name}'
                    local.parent.mkdir(parents=True, exist_ok=True)
                    if container_copy('from', dev, old, item, local).returncode == 0 and has_files(local):
                        got.append((item, dest, local))
                if got:
                    found[old] = got
            if not found:
                return None   # not installed there, or nothing to carry
            with_saves = [old for old in found if any(item == 'Documents/save' for item, _, _ in found[old])]
            old = (with_saves or list(found))[0]
            for other in found:
                if other != old:
                    say(f'{other} is on the device too; its data is not copied (it has '
                        f'{"saves as well" if other in with_saves else "no saves"})')
            got = found[old]
            say(f'{old} is still on the device: copying its data to {bundle_id} (the old app keeps its own)')
            copied, save_local = [], None
            for n, (item, dest, local) in enumerate(got):
                if item in KEEP_NEW or item.startswith('Library/Preferences/'):   # a retry: what the new app already has (its own Settings choices) is kept
                    have = tmp/'have'/str(n)
                    have.parent.mkdir(exist_ok=True)
                    if container_copy('from', dev, bundle_id, dest, have).returncode == 0 and has_files(have):
                        say(f'  kept {dest}: {bundle_id} has it already')
                        continue
                r = container_copy('to', dev, bundle_id, local, dest)
                if r.returncode:
                    report(f'{item} not copied from {old}: {last_line(r)}')
                else:
                    copied.append(item)
                    say(f'  copied {item}')
                    if item == 'Documents/save':
                        save_local = local
            if save_local is None:
                if old in with_saves:
                    report(f'the saves were not copied. {save_by_hand(old, bundle_id)}')
                return old, copied   # no marker: the next install tries again
            # read one save file back from the new app: account.uid, else the first file of the copy
            probe = 'account.uid' if (save_local/'account.uid').is_file() else \
                next((p.relative_to(save_local).as_posix() for p in sorted(save_local.rglob('*')) if p.is_file()), None)
            if probe is None:   # the old app's save is not a folder of files
                report(f'the copied saves could not be checked on {bundle_id} (the old save is not a folder of files). '
                       f'{save_by_hand(old, bundle_id)}')
                return old, copied   # no marker
            back = tmp/'check'/Path(probe).name
            back.parent.mkdir()
            r = container_copy('from', dev, bundle_id, f'Documents/save/{probe}', back)
            if r.returncode or not back.is_file() or back.read_bytes() != (save_local/probe).read_bytes():
                report(f'the copied saves could not be checked on {bundle_id} (save/{probe} '
                       f'{"differs" if back.is_file() else "is missing"}). {save_by_hand(old, bundle_id)}')
                return old, copied   # no marker: the next install tries again
            say(f'  checked save/{probe} on {bundle_id}')
            note = tmp/'migrated-from.txt'
            note.write_text(f'{old}\n' + ''.join(f'{item}\n' for item in copied))
            if container_copy('to', dev, bundle_id, note, CARRIED).returncode:
                report(f'{CARRIED} not written (a later install still copies nothing once this app has saves)')
            say(f'copied {len(copied)} of {len(got)} items from {old}; delete the old app yourself once this one '
                'shows your saves')
            return old, copied
    except (OSError, ValueError, subprocess.SubprocessError) as e:   # ValueError includes UnicodeDecodeError
        report(f'the data of the app under the old identifier was not copied: {e}')
    return None


def main():
    global EVENTS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ipa', type=Path, nargs='?', help='the unsigned IPA (or .app folder) from build_app.py --platform ios')
    ap.add_argument('--device', help='device name (as in Finder) or identifier; needed when several are paired')
    ap.add_argument('--team', help='Apple team ID (default: the only team with an Apple Development certificate)')
    ap.add_argument('--bundle-id', help=f'default: {BUNDLE_PREFIX}.<team>, so it is free to register on your team')
    ap.add_argument('--game-data', type=Path, help='<work folder>/extracted/<v101 | v200>/romfs/romfs.bin (the version the IPA was built for; index.json beside it): copied once to Documents/GameData')
    ap.add_argument('--list-devices', action='store_true', help='list the paired devices and the Apple Development teams, then exit')
    ap.add_argument('--dry-run', action='store_true', help='check everything up to signing, then stop (nothing is signed or installed)')
    ap.add_argument('--progress', choices=('text', 'json'), default='text')
    a = ap.parse_args()
    if a.progress == 'json':
        EVENTS = sys.stdout; sys.stdout = sys.stderr
    try:
        install(a)
    except Fail as e:
        print(f'\nERROR: {e}' + (f'\nwhat to do: {e.hint}' if e.hint else ''), file=sys.stderr)
        emit('error', step=STEP[0], message=str(e), hint=e.hint); sys.exit(1)
    except KeyboardInterrupt:
        emit('cancelled', step=STEP[0]); sys.exit(130)

NO_TEAM = ('No Apple Development certificate on this Mac. In Xcode: Settings > Accounts > add your Apple ID, then select '
           'it > Manage Certificates > + > Apple Development.')

def install(a):
    step('device')
    found = teams()
    emit('teams', teams=found)
    devs = devices()
    emit('devices', devices=[describe(d) for d in devs])
    if a.list_devices:
        for d in devs: say(f"device: {d['deviceProperties'].get('name')} ({d['hardwareProperties'].get('marketingName')})")
        say(f"teams: {', '.join(found) if found else 'none (' + NO_TEAM + ')'}")
        emit('step', step='device', status='done'); emit('done', listed=True); return
    if not a.ipa: raise Fail('no IPA given', 'build it first: python3 build_app.py ... --platform ios')
    if not a.ipa.exists(): raise Fail(f'no such IPA: {a.ipa}')
    if a.game_data and not (a.game_data.is_file() and (a.game_data.parent / 'index.json').is_file()):
        raise Fail(f'--game-data must be a merged romfs.bin with its index.json beside it: {a.game_data}')
    if a.team: team = a.team
    elif len(found) == 1: team = found[0]
    elif found: raise Fail(f'several teams: {", ".join(found)}', 'choose one with --team')
    else: raise Fail('no Apple Development certificate', NO_TEAM)
    dev = pick_device(a.device)
    udid = dev['hardwareProperties']['udid']
    bundle_id, reused = choose_bundle_id(team, a.bundle_id, lambda b: app_installed(dev['identifier'], b))
    if reused:
        say(f'the app is already on this device as {reused}: installing over it (keeps its saves and game data, uses no '
            f'extra app slot)')
    say(f"team {team}, bundle {bundle_id}, device {dev['deviceProperties'].get('name')} ({udid})")
    emit('plan', team=team, bundle_id=bundle_id, device=describe(dev),
         steps=['device', 'profile', 'sign', 'install'] + (['game data'] if a.game_data else []))
    if a.dry_run:
        say('dry run: stopping before the provisioning profile; nothing was signed or installed')
        emit('step', step='device', status='done'); emit('done', dry_run=True); return

    step('profile')
    say('provisioning profile: asking Xcode')
    prov, signed = profile(team, bundle_id, udid)
    info = plistlib.loads(out(['security','cms','-D','-i',prov]).encode())
    ents = info['Entitlements']
    if not ents.get(ENTITLEMENT):
        say(f'warning: your team cannot grant {ENTITLEMENT}; iOS may close the game when it runs out of memory')
    expires = info['ExpirationDate'].replace(tzinfo=timezone.utc).astimezone()  # plistlib returns naive UTC
    say(f"provisioning profile valid until {expires:%Y-%m-%d %H:%M} local time (run this again before then; a free Apple ID's lasts 7 days)")
    emit('profile', expires=expires.isoformat())

    step('sign')
    # Unpack once per IPA; later runs only re-sign.
    work = a.ipa.with_suffix('.signed'); stamp = work/'.ipa-mtime'
    app = work/'Payload/XCX.app'
    if a.ipa.is_dir():   # an unsigned .app (build_app.py -o X.app): cloned, nothing to unpack
        say(f'cloning {a.ipa.name}')
        shutil.rmtree(work, ignore_errors=True); app.parent.mkdir(parents=True)
        import ctypes   # one APFS clone of the whole folder, as build_app.py copy_tree
        libc = ctypes.CDLL(None); libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        if libc.clonefile(os.fsencode(a.ipa), os.fsencode(app), 0) and subprocess.run(['/bin/cp', '-cR', a.ipa, app]).returncode:
            raise Fail(f'cannot copy {a.ipa}')
    elif not stamp.is_file() or stamp.read_text() != str(a.ipa.stat().st_mtime_ns):
        say(f'unpacking {a.ipa.name}')
        shutil.rmtree(work, ignore_errors=True); work.mkdir()
        run(['ditto','-x','-k',a.ipa,work])
        stamp.write_text(str(a.ipa.stat().st_mtime_ns))
    plist = app/'Info.plist'
    infoplist = plistlib.loads(plist.read_bytes()); infoplist['CFBundleIdentifier'] = bundle_id
    plist.write_bytes(plistlib.dumps(infoplist, fmt=plistlib.FMT_BINARY))
    shutil.copy2(prov, app/'embedded.mobileprovision')
    entfile = work/'entitlements.plist'
    entfile.write_bytes(plistlib.dumps({k: ents[k] for k in ('application-identifier','com.apple.developer.team-identifier',
                                                                'get-task-allow', ENTITLEMENT) if k in ents}))
    say('signing')
    run(['codesign','--force','--sign',identity_of(signed),'--entitlements',entfile,'--generate-entitlement-der',app])
    step('install')
    say('installing (a few minutes over the cable)')
    run(['xcrun','devicectl','device','install','app','--device',dev['identifier'],app])
    carry_over(dev['identifier'], bundle_id)
    if a.game_data:
        step('game data')
        push_game_data(dev['identifier'], bundle_id, a.game_data)
    emit('step', step=STEP[0], status='done')
    say('installed. First time on this device: Settings > General > VPN & Device Management > trust your Apple ID.')
    emit('done', expires=expires.isoformat())

if __name__ == '__main__': main()
