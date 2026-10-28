"""The iPhone app's start screen (ios/Sources/main.m): it builds the shared saves core, and test launches skip it."""
import re
import unittest
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
MAIN = (GAME/'ios/Sources/main.m').read_text()
PROJECT = (GAME/'ios/project.yml').read_text()


class Project(unittest.TestCase):
    def test_builds_the_saves_core(self):
        self.assertIn('- path: ${XCX_SRC}/app/xcx_saves.m', PROJECT)
        self.assertTrue((GAME/'app/xcx_saves.m').is_file())

    def test_finds_the_header(self):
        self.assertIn('"\\"${XCX_SRC}/app\\""', PROJECT)
        self.assertIn('#import "xcx_saves.h"', MAIN)

    def test_links_zlib(self):
        self.assertIn('- sdk: libz.tbd', PROJECT)


class SkipForTestLaunches(unittest.TestCase):
    SWITCHES = ('XCX_SKIP_START_SCREEN', 'TOTK_INPUT_SCRIPT', 'TOTK_AUTOLOAD', 'XC_SHADER_CACHE', 'TOTK_SHADER_CACHE')

    def test_switches_are_read(self):
        listed = re.search(r'for \(NSString \*name in @\[(.*?)\]\)', MAIN[MAIN.index('XCX_SKIP_START_SCREEN') - 200:]).group(1)
        for name in self.SWITCHES:
            self.assertIn(f'@"{name}"', listed)

    def test_read_before_the_app_sets_or_clears_them(self):
        """The app sets TOTK_SHADER_CACHE and clears TOTK_AUTOLOAD itself: the launch's values must be read first."""
        read = MAIN.index('g_skip_start_screen = YES')
        self.assertLess(read, MAIN.index('setenv("TOTK_SHADER_CACHE"'))
        self.assertLess(read, MAIN.index('unsetenv("TOTK_AUTOLOAD")'))

    def test_scene_starts_the_game_when_skipped(self):
        self.assertIn('g_skip_start_screen ? [XCXGameController new] : [XCXStartController new]', MAIN)


class StartScreen(unittest.TestCase):
    def test_buttons(self):
        for title in ('@"Play"', '@"Export Saves"', '@"Import Saves"'):
            self.assertIn(title, MAIN)

    def test_saves_use_the_profile_and_game_version(self):
        self.assertIn('g_profile = [docs stringByAppendingPathComponent:@"save"]', MAIN)
        for call in ('xcx_saves_export(g_profile', 'xcx_saves_inspect(zip, @TOTK_GAME_DIR', 'xcx_saves_import(g_profile'):
            self.assertIn(call, MAIN)


if __name__ == '__main__':
    unittest.main()
