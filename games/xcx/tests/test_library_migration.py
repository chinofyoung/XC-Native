"""The MacNativeGames -> XCNative move of 2026-10-24: the Library folders (scripts/app_bundle.py migrate_library, run by
build_app.py; app/launcher.m does the same) and an iPhone's data under the old bundle id (ios/tools/install_device.py
carry_over). Temporary folders and a faked devicectl only: the real Library and devices are never touched."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME/'scripts'))
sys.path.insert(0, str(GAME/'ios/tools'))
import app_bundle
import install_device

NOT_RUNNING = lambda: False   # noqa: E731


def put(path, text='x'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.new, self.old = self.home/app_bundle.DATA, self.home/app_bundle.OLD_DATA
        self.logs, self.old_logs = self.home/app_bundle.LOGS, self.home/app_bundle.OLD_LOGS
        self.notes = []

    def tearDown(self):
        self.tmp.cleanup()

    def migrate(self, running=NOT_RUNNING):
        return app_bundle.migrate_library(self.home, self.notes.append, running)

    def test_paths(self):
        self.assertEqual(app_bundle.DATA, 'Library/Application Support/XCNative/XCX')
        self.assertEqual(app_bundle.OLD_DATA, 'Library/Application Support/MacNativeGames/XCX')
        self.assertEqual(app_bundle.PROFILE, 'Library/Application Support/XCNative/XCX/profile')
        self.assertEqual((app_bundle.LOGS, app_bundle.OLD_LOGS), ('Library/Logs/XCNative', 'Library/Logs/MacNativeGames'))
        self.assertEqual(app_bundle.CACHES, 'Library/Caches/XCNative')
        self.assertEqual((app_bundle.BUNDLE_ID, app_bundle.OLD_BUNDLE_ID), ('org.xcnative.xcx', 'org.macnativegames.xcx'))

    def test_only_old_is_moved(self):
        put(self.old/'profile/save/slot0', 'save')
        put(self.old/'shader-list-contribution.txt', 'rows')
        put(self.old_logs/'xcx.log', 'log')
        put(self.home/'Library/Application Support/MacNativeGames/TOTK/keep')   # another game's folder stays
        self.assertEqual(self.migrate(), self.new)
        self.assertEqual((self.new/'profile/save/slot0').read_text(), 'save')
        self.assertEqual((self.new/'shader-list-contribution.txt').read_text(), 'rows')
        self.assertEqual((self.logs/'xcx.log').read_text(), 'log')
        self.assertFalse(self.old.exists())
        self.assertFalse(self.old_logs.exists())
        self.assertTrue((self.home/'Library/Application Support/MacNativeGames/TOTK/keep').is_file())
        self.assertEqual(len(self.notes), 2)
        self.assertTrue(all(n.startswith('moved ') for n in self.notes))
        self.assertEqual(app_bundle.data_folder(self.home), self.new)
        self.assertEqual(self.migrate(), self.new)   # once: nothing more to do
        self.assertEqual(len(self.notes), 2)

    def test_both_present_new_is_used_old_untouched(self):
        put(self.old/'profile/save/slot0', 'old save')
        put(self.new/'profile/save/slot0', 'new save')
        self.assertEqual(self.migrate(), self.new)
        self.assertEqual((self.old/'profile/save/slot0').read_text(), 'old save')
        self.assertEqual((self.new/'profile/save/slot0').read_text(), 'new save')
        self.assertEqual(sorted(p.name for p in self.new.rglob('*')), ['profile', 'save', 'slot0'])   # nothing merged
        self.assertEqual(len(self.notes), 1)
        self.assertIn('left in place', self.notes[0])
        self.assertEqual(app_bundle.data_folder(self.home), self.new)

    def test_move_failure_uses_old(self):
        put(self.old/'profile/save/slot0', 'save')
        with mock.patch.object(app_bundle.os, 'rename', side_effect=OSError(18, 'Cross-device link')):
            self.assertEqual(self.migrate(), self.old)
        self.assertEqual((self.old/'profile/save/slot0').read_text(), 'save')
        self.assertFalse(self.new.exists())
        self.assertIn('could not move', self.notes[0])
        self.assertEqual(app_bundle.data_folder(self.home), self.old)   # the build and the tools keep using it

    def test_lost_race_uses_new(self):
        put(self.old/'profile/save/slot0', 'save')

        real_rename = app_bundle.os.rename

        def moved_meanwhile(old, new):   # another process moved it first, then this rename fails
            real_rename(old, new)
            raise FileNotFoundError(2, 'No such file or directory')
        with mock.patch.object(app_bundle.os, 'rename', side_effect=moved_meanwhile):
            self.assertEqual(app_bundle.move_folder(self.new, self.old, self.notes.append, NOT_RUNNING), self.new)
        self.assertEqual((self.new/'profile/save/slot0').read_text(), 'save')
        self.assertIn('meanwhile', self.notes[0])

    def test_broken_link_counts_as_nothing(self):
        self.new.parent.mkdir(parents=True)
        self.new.symlink_to(self.home/'gone')
        self.assertEqual(app_bundle.data_folder(self.home), self.new)          # neither there: the new path
        put(self.old/'profile/save/slot0', 'save')
        self.assertEqual(app_bundle.data_folder(self.home), self.old)          # as the launcher and the window see it
        self.assertEqual(self.migrate(), self.old)                             # rename onto the link fails: old kept
        self.assertEqual((self.old/'profile/save/slot0').read_text(), 'save')
        self.assertIn('could not move', self.notes[0])

    def test_running_game_is_not_moved_under(self):
        put(self.old/'profile/save/slot0', 'save')
        self.assertEqual(self.migrate(running=lambda: True), self.old)
        self.assertTrue((self.old/'profile/save/slot0').is_file())
        self.assertFalse(self.new.exists())
        self.assertIn('while the game runs', self.notes[0])

    def test_neither_present(self):
        self.assertEqual(self.migrate(), self.new)
        self.assertFalse(self.new.exists())   # made by whoever writes there first
        self.assertEqual(self.notes, [])
        self.assertEqual(app_bundle.data_folder(self.home), self.new)


class BuildUsesLibrary(unittest.TestCase):
    """build_app.py main(): the folders are moved only after the arguments are checked."""
    def setUp(self):
        sys.path.insert(0, str(GAME.parents[1]))
        import build_app
        self.build_app = build_app

    def main(self, argv):
        with mock.patch.object(app_bundle, 'migrate_library', return_value=Path('/nowhere')) as migrate, \
                mock.patch.object(self.build_app, 'identify_only', return_value=0) as identify, \
                mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            try:
                self.build_app.main(argv)
            except SystemExit:
                pass
        return migrate.call_count, identify.call_count

    def test_help_and_wrong_arguments_move_nothing(self):
        self.assertEqual(self.main(['--help']), (0, 0))
        self.assertEqual(self.main(['--bogus']), (0, 0))
        self.assertEqual(self.main(['game.xci']), (0, 0))   # -k is required

    def test_checked_arguments_move_first(self):
        self.assertEqual(self.main(['game.xci', '-k', 'prod.keys', '--identify']), (1, 1))


class FakeDevice:
    """devicectl device copy from / to between app containers kept in folders: {bundle id: folder}. An app that is not
    installed, or a source that is not there, fails as devicectl does. `fail_to` makes copies to those paths fail."""
    def __init__(self, root, apps, fail_to=(), fail_from=(), corrupt_back=False):
        self.root, self.apps, self.fail_to, self.calls = Path(root), set(apps), set(fail_to), []
        self.fail_from, self.corrupt_back = set(fail_from), corrupt_back
        for app in self.apps:
            (self.root/app).mkdir(parents=True, exist_ok=True)

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        assert cmd[:4] == ['xcrun', 'devicectl', 'device', 'copy'] and cmd[cmd.index('--domain-type') + 1] == 'appDataContainer'
        direction, app = cmd[4], cmd[cmd.index('--domain-identifier') + 1]
        src, dst = cmd[cmd.index('--source') + 1], cmd[cmd.index('--destination') + 1]
        fail = subprocess.CompletedProcess(cmd, 1, '', 'ERROR: The item could not be found')
        if app not in self.apps:
            return fail
        if direction == 'from':
            if (app, src) in self.fail_from:
                return subprocess.CompletedProcess(cmd, 1, '', 'ERROR: The connection was interrupted')
            item, local = self.root/app/src, Path(dst)
        else:
            if dst in self.fail_to:
                return fail
            item, local = Path(src), self.root/app/dst
        if not item.exists():
            return fail
        local.parent.mkdir(parents=True, exist_ok=True)
        if item.is_dir():
            shutil.copytree(item, local, dirs_exist_ok=True)   # the folder's contents at the destination
        else:
            local.write_bytes(item.read_bytes())
        if self.corrupt_back and direction == 'from' and src.startswith('Documents/save/'):
            local.write_bytes(b'garbled')
        return subprocess.CompletedProcess(cmd, 0, '', '')

    def file(self, app, path):
        return self.root/app/path


NEW, OLD_TEAM, OLD = 'org.xcnative.xcx.abcde12345', 'org.macnativegames.xcx.abcde12345', 'org.macnativegames.xcx'


class ChooseBundleId(unittest.TestCase):
    TEAM = 'ABCDE12345'

    def choose(self, given, apps):
        asked = []
        def installed(b):
            asked.append(b)
            return b in apps
        return install_device.choose_bundle_id(self.TEAM, given, installed), asked

    def test_new_installed_keeps_new(self):
        self.assertEqual(self.choose(None, {NEW, OLD_TEAM})[0], (NEW, None))

    def test_only_old_team_id(self):
        self.assertEqual(self.choose(None, {OLD_TEAM, OLD})[0], (OLD_TEAM, OLD_TEAM))

    def test_only_bare_old_id(self):
        self.assertEqual(self.choose(None, {OLD})[0], (OLD, OLD))

    def test_none_installed(self):
        self.assertEqual(self.choose(None, set())[0], (NEW, None))

    def test_explicit_id_is_not_probed(self):
        result, asked = self.choose('com.example.mine', {OLD})
        self.assertEqual(result, ('com.example.mine', None))
        self.assertEqual(asked, [])

    def test_app_installed_follows_return_code(self):
        calls = []
        def fake(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0 if cmd[cmd.index('--domain-identifier') + 1] == NEW else 1, '', 'x')
        with mock.patch.object(install_device.subprocess, 'run', fake):
            self.assertTrue(install_device.app_installed('dev-1', NEW))
            self.assertFalse(install_device.app_installed('dev-1', OLD))
        self.assertEqual(calls[0][:8], ['xcrun', 'devicectl', 'device', 'info', 'files', '--device', 'dev-1', '--domain-type'])
        self.assertEqual(calls[0][-2:], ['--subdirectory', 'Documents'])


class MaxApps(unittest.TestCase):
    REAL = ('ERROR: Failed to install the app on the device. (MIInstallerErrorDomain error 13.)\n'
            'NSLocalizedDescription = ApplicationVerificationFailed, LibMISErrorNumber = -402620383')

    def test_real_error_text(self):
        hint = install_device.explain(self.REAL)
        self.assertIn('at most 3 sideloaded apps', hint)
        self.assertIn('do not delete an older Xenoblade Chronicles X install', hint)

    def test_other_spellings(self):
        for text in ('error 0xE8008021', 'Maximum Number of Apps reached'):
            self.assertIn('at most 3', install_device.explain(text))

    def test_unrelated_text_is_not_max_apps(self):
        self.assertNotIn('at most 3', install_device.explain('Developer Mode is off') or '')


class CarryOver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.warnings, self.said = [], []
        self.patches = [mock.patch.object(install_device, 'say', self.said.append)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def device(self, apps, **kw):
        dev = FakeDevice(Path(self.tmp.name)/'device', apps, **kw)
        self.patches.append(mock.patch.object(install_device.subprocess, 'run', dev.run))
        self.patches[-1].start()
        return dev

    def old_app(self, dev, app):
        put(dev.file(app, 'Documents/save/account.uid'), 'uid')
        put(dev.file(app, 'Documents/save/save/slot0'), 'save')
        put(dev.file(app, 'Documents/shader-cache/rt-x/a.variants'), 'cache')
        put(dev.file(app, 'Documents/shader-list-contribution.txt'), 'rows')
        put(dev.file(app, 'Documents/shader-requests/r1.json'), 'req')
        put(dev.file(app, 'Documents/GameData/romfs.bin.000'), 'image')
        put(dev.file(app, f'Library/Preferences/{app}.plist'), 'prefs')

    def carry(self):
        return install_device.carry_over('DEV', NEW, report=self.warnings.append)

    def test_old_bundle_ids(self):
        self.assertEqual(install_device.old_bundle_ids(NEW), [OLD_TEAM, OLD])
        self.assertEqual(install_device.old_bundle_ids('org.xcnative.xcx'), [OLD])
        self.assertEqual(install_device.old_bundle_ids('com.someone.else'), [])

    def test_copies_from_team_app_and_keeps_it(self):
        dev = self.device([NEW, OLD_TEAM])
        self.old_app(dev, OLD_TEAM)
        old, copied = self.carry()
        self.assertEqual(old, OLD_TEAM)
        self.assertEqual(copied, list(install_device.CARRY) + [f'Library/Preferences/{OLD_TEAM}.plist'])
        self.assertEqual(dev.file(NEW, 'Documents/save/save/slot0').read_text(), 'save')
        self.assertEqual(dev.file(NEW, 'Documents/save/account.uid').read_text(), 'uid')
        self.assertEqual(dev.file(NEW, 'Documents/shader-cache/rt-x/a.variants').read_text(), 'cache')
        self.assertEqual(dev.file(NEW, 'Documents/shader-list-contribution.txt').read_text(), 'rows')
        self.assertEqual(dev.file(NEW, 'Documents/shader-requests/r1.json').read_text(), 'req')
        self.assertEqual(dev.file(NEW, f'Library/Preferences/{NEW}.plist').read_text(), 'prefs')
        self.assertFalse(dev.file(NEW, 'Documents/GameData').exists())   # --game-data's job
        self.assertTrue(dev.file(NEW, install_device.CARRIED).read_text().startswith(OLD_TEAM + '\n'))
        self.assertTrue(dev.file(OLD_TEAM, 'Documents/save/save/slot0').is_file())   # the old app keeps its data
        self.assertEqual(self.warnings, [])
        self.assertIsNone(self.carry())   # once

    def test_falls_back_to_plain_old_id(self):
        dev = self.device([NEW, OLD])
        self.old_app(dev, OLD)
        old, copied = self.carry()
        self.assertEqual(old, OLD)
        self.assertEqual(dev.file(NEW, 'Documents/save/save/slot0').read_text(), 'save')
        self.assertEqual(dev.file(NEW, f'Library/Preferences/{NEW}.plist').read_text(), 'prefs')

    def test_new_app_with_saves_is_left_alone(self):
        dev = self.device([NEW, OLD_TEAM])
        self.old_app(dev, OLD_TEAM)
        put(dev.file(NEW, 'Documents/save/save/slot0'), 'new save')
        self.assertIsNone(self.carry())
        self.assertEqual(dev.file(NEW, 'Documents/save/save/slot0').read_text(), 'new save')
        self.assertFalse(dev.file(NEW, 'Documents/shader-list-contribution.txt').exists())
        self.assertFalse(any(c[4] == 'to' for c in dev.calls))

    def test_no_old_app(self):
        dev = self.device([NEW])
        self.assertIsNone(self.carry())
        self.assertFalse(any(c[4] == 'to' for c in dev.calls))
        self.assertEqual(self.warnings, [])

    def test_custom_bundle_id_is_not_migrated(self):
        dev = self.device(['com.someone.else', OLD])
        self.old_app(dev, OLD)
        self.assertIsNone(install_device.carry_over('DEV', 'com.someone.else', report=self.warnings.append))
        self.assertEqual(dev.calls, [])

    def test_failed_copy_is_a_warning(self):
        dev = self.device([NEW, OLD_TEAM], fail_to={'Documents/shader-cache'})
        self.old_app(dev, OLD_TEAM)
        old, copied = self.carry()
        self.assertNotIn('Documents/shader-cache', copied)
        self.assertEqual(dev.file(NEW, 'Documents/save/save/slot0').read_text(), 'save')
        self.assertEqual(len(self.warnings), 1)
        self.assertIn('Documents/shader-cache not copied', self.warnings[0])

    def test_save_check_failure_writes_no_marker(self):
        dev = self.device([NEW, OLD_TEAM], corrupt_back=True)
        self.old_app(dev, OLD_TEAM)
        old, copied = self.carry()
        self.assertIn('Documents/save', copied)
        self.assertFalse(dev.file(NEW, install_device.CARRIED).exists())   # tried again at the next install
        self.assertEqual(len(self.warnings), 1)
        self.assertIn('could not be checked', self.warnings[0])
        self.assertIn('Finder', self.warnings[0])

    def test_save_not_copied_writes_no_marker(self):
        dev = self.device([NEW, OLD_TEAM], fail_to={'Documents/save'})
        self.old_app(dev, OLD_TEAM)
        old, copied = self.carry()
        self.assertNotIn('Documents/save', copied)
        self.assertFalse(dev.file(NEW, install_device.CARRIED).exists())
        self.assertTrue(any('saves were not copied' in w and 'Finder' in w for w in self.warnings))

    def test_no_saves_on_old_app_writes_no_marker(self):
        dev = self.device([NEW, OLD_TEAM])
        put(dev.file(OLD_TEAM, 'Documents/shader-list-contribution.txt'), 'rows')
        old, copied = self.carry()
        self.assertEqual(copied, ['Documents/shader-list-contribution.txt'])
        self.assertFalse(dev.file(NEW, install_device.CARRIED).exists())

    def test_unclear_save_answer_skips(self):
        dev = self.device([NEW, OLD_TEAM], fail_from={(NEW, 'Documents/save')})
        self.old_app(dev, OLD_TEAM)
        self.assertIsNone(self.carry())
        self.assertFalse(any(c[4] == 'to' for c in dev.calls))
        self.assertEqual(len(self.warnings), 1)
        self.assertIn('could not tell', self.warnings[0])

    def test_empty_new_save_folder_proceeds(self):
        dev = self.device([NEW, OLD_TEAM])
        self.old_app(dev, OLD_TEAM)
        dev.file(NEW, 'Documents/save').mkdir(parents=True)   # the new app started once, without game data
        old, copied = self.carry()
        self.assertEqual(dev.file(NEW, 'Documents/save/save/slot0').read_text(), 'save')
        self.assertTrue(dev.file(NEW, install_device.CARRIED).is_file())

    def test_both_old_ids_prefers_the_one_with_saves(self):
        dev = self.device([NEW, OLD_TEAM, OLD])
        put(dev.file(OLD_TEAM, 'Documents/shader-list-contribution.txt'), 'team rows')   # no saves
        self.old_app(dev, OLD)
        old, copied = self.carry()
        self.assertEqual(old, OLD)
        self.assertEqual(dev.file(NEW, 'Documents/shader-list-contribution.txt').read_text(), 'rows')
        self.assertTrue(any(OLD_TEAM in m and 'too' in m for m in self.said))

    def test_old_save_that_is_a_file_is_a_failed_check(self):
        dev = self.device([NEW, OLD_TEAM])
        put(dev.file(OLD_TEAM, 'Documents/save'), 'not a folder')
        old, copied = self.carry()   # no StopIteration: the install goes on
        self.assertFalse(dev.file(NEW, install_device.CARRIED).exists())
        self.assertTrue(any('could not be checked' in w for w in self.warnings))

    def test_retry_keeps_what_the_new_app_has(self):
        dev = self.device([NEW, OLD_TEAM], corrupt_back=True)   # first install: the check fails, no marker
        self.old_app(dev, OLD_TEAM)
        self.carry()
        self.assertFalse(dev.file(NEW, install_device.CARRIED).exists())
        put(dev.file(NEW, f'Library/Preferences/{NEW}.plist'), 'changed in the new app')
        put(dev.file(NEW, 'Documents/shader-list-contribution.txt'), 'new rows')
        put(dev.file(NEW, 'Documents/shader-cache/rt-x/a.variants'), 'new cache')
        shutil.rmtree(dev.file(NEW, 'Documents/save'))   # the copy that did not check out, removed by hand
        dev.corrupt_back = False
        old, copied = self.carry()   # the retry
        self.assertEqual(dev.file(NEW, f'Library/Preferences/{NEW}.plist').read_text(), 'changed in the new app')
        self.assertEqual(dev.file(NEW, 'Documents/shader-list-contribution.txt').read_text(), 'new rows')
        self.assertEqual(dev.file(NEW, 'Documents/shader-cache/rt-x/a.variants').read_text(), 'new cache')
        self.assertNotIn('Documents/shader-cache', copied)
        self.assertEqual(dev.file(NEW, 'Documents/save/save/slot0').read_text(), 'save')
        self.assertTrue(dev.file(NEW, install_device.CARRIED).is_file())

    def test_unreadable_text_is_a_warning(self):
        with mock.patch.object(install_device, 'container_copy', side_effect=UnicodeDecodeError('utf-8', b'', 0, 1, 'x')):
            self.assertIsNone(self.carry())
        self.assertEqual(len(self.warnings), 1)

    def test_devicectl_missing_is_a_warning(self):
        with mock.patch.object(install_device.subprocess, 'run', side_effect=OSError('no xcrun')):
            self.assertIsNone(self.carry())
        self.assertEqual(len(self.warnings), 1)


if __name__ == '__main__':
    unittest.main()
