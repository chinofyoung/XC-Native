"""app/xcx_saves.m (save export / import, shared by the Mac launcher and the iPhone app): compiles it with a small
driver and runs export, inspect and import on profiles in a temporary folder; the zips for the refusals are made here
with zipfile. Skipped when no compiler for Objective-C is available."""
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.normpath(os.path.join(HERE, "..", "app"))

DRIVER = r"""
#import "xcx_saves.h"
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc < 5) return 2;
        NSString *op = @(argv[1]), *profile = @(argv[2]), *zip = @(argv[3]), *game = @(argv[4]);
        NSError *err = nil; BOOL ok = NO; NSString *backup = nil, *folder = nil;
        if ([op isEqualToString:@"export"]) ok = xcx_saves_export(profile, zip, game, @"Test Mac", &err);
        else if ([op isEqualToString:@"inspect"]) {
            NSDictionary *m = xcx_saves_inspect(zip, game, &err); ok = m != nil;
            if (ok) printf("device=%s date=%s\n", [m[@"device"] UTF8String], xcx_saves_export_date(m) ? "yes" : "no");
        } else if ([op isEqualToString:@"import"]) ok = xcx_saves_import(profile, zip, game, &backup, &folder, &err);
        else if ([op isEqualToString:@"folder"]) { folder = xcx_saves_folder(profile, NO, &err); ok = folder != nil; }
        else if ([op isEqualToString:@"name"]) { printf("%s\n", xcx_saves_file_name([NSDate dateWithTimeIntervalSince1970:0]).UTF8String); return 0; }
        if (!ok) { printf("refused %ld %s\n", (long)err.code, err.localizedDescription.UTF8String); return 1; }
        printf("ok\nbackup=%s\nfolder=%s\n", backup ? backup.UTF8String : "", folder ? folder.UTF8String : "");
        return 0;
    }
}
"""

SAVES = {"gamedata01": 4096, "gamedata01.tmb": 512, "gamedataa": 4096, "systemdata": 180, "avatarmakedata": 740,
         "socialdata": 900}
# xcx_saves.h XCXSavesError
NO_SAVES, NOT_EXPORT, DAMAGED, NEWER_GAME, NEWER_FORMAT = 1, 2, 3, 4, 5


def account_id(uid):
    """The runtime's save folder name for account.uid (runtime/fs_host.c init): hi, lo as %016llx."""
    lo, hi = struct.unpack("<QQ", uid)
    return f"{hi:016x}{lo:016x}"


def make_profile(root, uid, saves=None):
    os.makedirs(root)
    with open(os.path.join(root, "account.uid"), "wb") as f:
        f.write(uid)
    for name, data in {"pseudo-device.id": b"D" * 16, "pso_user.tsv": b"pipelines\n"}.items():
        with open(os.path.join(root, name), "wb") as f:
            f.write(data)
    game = os.path.join(root, "save", account_id(uid), "sts", "game")
    os.makedirs(game)
    for name, data in (saves or {}).items():
        with open(os.path.join(game, name), "wb") as f:
            f.write(data)
    return game


def tree(root):
    out = {}
    for d, _, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = f.read()
    return out


def export_zip(path, files, manifest=None, extra=(), version="v101", fmt=1, with_manifest=True):
    """A zip as the export writes it; manifest entries from `files` unless given; `extra` (name, data) not listed."""
    if manifest is None:
        manifest = [{"name": n, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()} for n, d in files.items()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if with_manifest:
            z.writestr("xcx-saves.json", json.dumps({"format": fmt, "game_version": version, "device": "Other",
                                                     "exported": "2026-10-28T15:30:00+08:00", "files": manifest}))
        for n, d in list(files.items()) + list(extra):
            z.writestr(n, d)


class XcxSavesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("clang") or shutil.which("cc")
        if not cc or not os.path.exists("/System/Library/Frameworks/Foundation.framework"):
            raise unittest.SkipTest("no Objective-C compiler / Foundation")
        cls.build = tempfile.mkdtemp()
        src, cls.exe = os.path.join(cls.build, "driver.m"), os.path.join(cls.build, "driver")
        with open(src, "w") as f:
            f.write(DRIVER)
        subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-fobjc-arc", "-I", APP, src,
                        os.path.join(APP, "xcx_saves.m"), "-framework", "Foundation", "-lz", "-o", cls.exe], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.build, ignore_errors=True)

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.saves = {n: os.urandom(size) for n, size in SAVES.items()}

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_op(self, op, profile, zip_path, game="v101"):
        r = subprocess.run([self.exe, op, profile, zip_path, game], capture_output=True, text=True)
        return r.returncode, r.stdout

    def refused(self, out, code):
        self.assertTrue(out.startswith(f"refused {code} "), out)

    def p(self, *parts):
        return os.path.join(self.d, *parts)

    def test_file_name(self):
        rc, out = self.run_op("name", "-", "-")
        self.assertRegex(out.strip(), r"^XCX-saves-19[67]\d-\d\d-\d\d-\d{4}\.zip$")

    def test_round_trip(self):
        make_profile(self.p("a"), b"\x01" * 8 + b"\x02" * 8, self.saves)
        rc, out = self.run_op("export", self.p("a"), self.p("s.zip"))
        self.assertEqual(rc, 0, out)
        with zipfile.ZipFile(self.p("s.zip")) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(z.namelist()[0], "xcx-saves.json")
            self.assertEqual(sorted(z.namelist()[1:]), sorted(self.saves))
            m = json.loads(z.read("xcx-saves.json"))
        self.assertEqual((m["format"], m["game_version"], m["game_version_name"], m["device"]), (1, "v101", "1.0.1", "Test Mac"))
        self.assertEqual({f["name"]: f["sha256"] for f in m["files"]}, {n: hashlib.sha256(d).hexdigest() for n, d in self.saves.items()})
        rc, out = self.run_op("inspect", "-", self.p("s.zip"))
        self.assertEqual(out.splitlines()[0], "device=Test Mac date=yes")

        # another device: another account id, older saves of its own, its own per-device files
        uid_b = bytes(range(16))
        old = {"gamedata01": b"old", "gamedata02": b"only here"}
        game_b = make_profile(self.p("b"), uid_b, old)
        rc, out = self.run_op("import", self.p("b"), self.p("s.zip"))
        self.assertEqual(rc, 0, out)
        self.assertEqual(tree(game_b), self.saves)   # gamedata02 is gone: the saves are replaced, not merged
        self.assertTrue(game_b.endswith(account_id(uid_b) + "/sts/game"))
        self.assertIn(f"folder={game_b}", out)
        for name, data in {"account.uid": uid_b, "pseudo-device.id": b"D" * 16, "pso_user.tsv": b"pipelines\n"}.items():
            with open(self.p("b", name), "rb") as f:
                self.assertEqual(f.read(), data, name)
        self.assertEqual(oct(os.stat(os.path.join(game_b, "gamedata01")).st_mode & 0o777), "0o600")
        backup = [l[7:] for l in out.splitlines() if l.startswith("backup=")][0]
        self.assertRegex(os.path.basename(backup), r"^b-1\.0\.1-backup-\d{4}-\d\d-\d\d-\d{6}$")
        self.assertEqual(os.path.dirname(backup), self.d)
        self.assertEqual(tree(os.path.join(backup, "save", account_id(uid_b), "sts", "game")), old)
        self.assertEqual(os.listdir(self.p("b", "temp")), [])   # the old saves swapped out are removed

    def test_no_saves(self):
        rc, out = self.run_op("export", self.p("none"), self.p("s.zip"))
        self.refused(out, NO_SAVES)
        make_profile(self.p("empty"), b"\x05" * 16)
        rc, out = self.run_op("export", self.p("empty"), self.p("s.zip"))
        self.refused(out, NO_SAVES)
        self.assertFalse(os.path.exists(self.p("s.zip")))

    def test_import_without_save_folder(self):
        """No profile yet (the game never started): account.uid is made as the runtime makes it, no backup."""
        export_zip(self.p("s.zip"), self.saves)
        rc, out = self.run_op("import", self.p("new"), self.p("s.zip"))
        self.assertEqual(rc, 0, out)
        with open(self.p("new", "account.uid"), "rb") as f:
            uid = f.read()
        self.assertEqual(len(uid), 16)
        self.assertNotEqual(uid, bytes(16))
        self.assertEqual(oct(os.stat(self.p("new", "account.uid")).st_mode & 0o777), "0o600")
        self.assertEqual(tree(self.p("new", "save", account_id(uid), "sts", "game")), self.saves)
        self.assertIn("backup=\n", out)
        rc, out = self.run_op("folder", self.p("new"), "-")
        self.assertIn(account_id(uid), out)

    def refuse_import(self, zip_path, code, game="v101"):
        game_b = make_profile(self.p("b"), b"\x07" * 16, {"gamedata01": b"keep"})
        before = tree(self.p("b"))
        rc, out = self.run_op("import", self.p("b"), zip_path, game)
        self.assertEqual(rc, 1, out)
        self.refused(out, code)
        self.assertEqual(tree(self.p("b")), before)   # nothing changed, no backup made
        self.assertEqual(sorted(os.listdir(self.d)), sorted(["b", os.path.basename(zip_path)]))
        self.assertTrue(os.path.isdir(game_b))
        return out

    def test_corrupted_hash(self):
        manifest = [{"name": n, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()} for n, d in self.saves.items()]
        manifest[0]["sha256"] = "0" * 64
        export_zip(self.p("s.zip"), self.saves, manifest)
        out = self.refuse_import(self.p("s.zip"), DAMAGED)
        self.assertIn("SHA-256", out)

    def test_corrupted_data(self):
        """A flipped byte in the zip's data: the CRC (or deflate) catches it."""
        with zipfile.ZipFile(self.p("s.zip"), "w", zipfile.ZIP_STORED) as z:
            m = [{"name": "gamedata01", "size": 4, "sha256": hashlib.sha256(b"abcd").hexdigest()}]
            z.writestr("xcx-saves.json", json.dumps({"format": 1, "game_version": "v101", "files": m}))
            z.writestr("gamedata01", b"abcd")
        data = bytearray(open(self.p("s.zip"), "rb").read())
        at = data.index(b"abcd")
        data[at] ^= 1
        open(self.p("s.zip"), "wb").write(bytes(data))
        self.refuse_import(self.p("s.zip"), NOT_EXPORT)

    def test_wrong_version(self):
        export_zip(self.p("s.zip"), self.saves, version="v200")
        out = self.refuse_import(self.p("s.zip"), NEWER_GAME, game="v101")
        self.assertIn("2.0.0", out)
        export_zip(self.p("u.zip"), self.saves, version="v300")
        os.remove(self.p("s.zip"))
        shutil.rmtree(self.p("b"))
        self.refuse_import(self.p("u.zip"), NEWER_GAME, game="v200")

    def test_older_version_into_newer_app(self):
        export_zip(self.p("s.zip"), self.saves, version="v101")
        make_profile(self.p("b"), b"\x07" * 16)
        rc, out = self.run_op("import", self.p("b"), self.p("s.zip"), "v200")
        self.assertEqual(rc, 0, out)

    def test_newer_format(self):
        export_zip(self.p("s.zip"), self.saves, fmt=2)
        self.refuse_import(self.p("s.zip"), NEWER_FORMAT)

    def test_path_traversal_names(self):
        for bad in ["../evil", "/abs", "sub/x", "..", ".hidden", "a\\b", "xcx-saves.json", ""]:
            with self.subTest(bad=bad):
                files = dict(self.saves)
                files[bad or "x"] = b"evil"
                manifest = [{"name": n, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()} for n, d in files.items()]
                if not bad:
                    manifest[-1]["name"] = ""
                export_zip(self.p("s.zip"), files if bad != "xcx-saves.json" else self.saves, manifest)
                self.refuse_import(self.p("s.zip"), DAMAGED)
                shutil.rmtree(self.p("b"))
                os.remove(self.p("s.zip"))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.d), "evil")))

    def test_unlisted_file(self):
        export_zip(self.p("s.zip"), self.saves, extra=[("../../evil", b"x")])
        self.refuse_import(self.p("s.zip"), DAMAGED)

    def test_listed_but_missing(self):
        manifest = [{"name": "gamedata09", "size": 1, "sha256": "0" * 64}]
        export_zip(self.p("s.zip"), {}, manifest)
        self.refuse_import(self.p("s.zip"), DAMAGED)

    def test_missing_json(self):
        export_zip(self.p("s.zip"), self.saves, with_manifest=False)
        out = self.refuse_import(self.p("s.zip"), NOT_EXPORT)
        self.assertIn("xcx-saves.json", out)

    def test_not_a_zip(self):
        with open(self.p("s.zip"), "wb") as f:
            f.write(b"not a zip at all" * 10)
        self.refuse_import(self.p("s.zip"), NOT_EXPORT)

    def test_finder_zip_read(self):
        """A zip made like Finder's Compress (ditto: deflate with data descriptors, a folder entry) is read, and
        refused for having no manifest."""
        if not shutil.which("ditto"):
            self.skipTest("no ditto")
        os.makedirs(self.p("folder"))
        for n, d in self.saves.items():
            with open(self.p("folder", n), "wb") as f:
                f.write(d)
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", self.p("folder"), self.p("s.zip")], check=True)
        shutil.rmtree(self.p("folder"))
        out = self.refuse_import(self.p("s.zip"), NOT_EXPORT)
        self.assertIn("no xcx-saves.json", out)


if __name__ == "__main__":
    unittest.main()
