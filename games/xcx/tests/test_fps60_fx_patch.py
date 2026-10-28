"""The 60 fps patch's sites 5 and 6 (runtime/game_patches.c, the effect engine's step): the veneer's words decode to the
intended instructions, the sites of both versions are the same code, and (when the work folder is there) the images hold
the shipped words at the sites and zero padding where the veneers go. scripts/verify_fps60_fx_patch.py runs the code."""
import re
import struct
import sys
import unittest
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'scripts'))
import verify_fps60_fx_patch as fx
import verify_fps60_qte_patch as q
from test_fps60_qte_patch import ldr_s_imm, vfp_expand_imm32

WORK = GAME.parents[1] / 'XCX_build'
SRC = q.source_text()


def fmul_s(word):
    """FMUL Sd, Sn, Sm: (d, n, m) or None."""
    if word & 0xffe0fc00 != 0x1e200800:
        return None
    return word & 31, (word >> 5) & 31, (word >> 16) & 31


class Definition(unittest.TestCase):
    def test_veneer_words(self):
        w = fx.c_veneer(SRC)
        self.assertEqual(w[0], 0); self.assertEqual(w[1], 0); self.assertEqual(w[8], 0)   # filled in by fps60_fx
        self.assertEqual(w[2], 0xb9400a11)                                # ldr w17, [x16, #8]: the mode
        self.assertEqual(w[3] & 0xff00001f, 0x34000011)                   # cbz w17
        self.assertEqual(3 + ((w[3] >> 5) & 0x7ffff), 8)                  # ... to the branch back
        self.assertEqual(ldr_s_imm(w[4]), (1, 16, 0))                     # ldr s1, [x16]: the frame time at +0
        self.assertEqual(fmul_s(w[5]), (0, 0, 1))                         # fmul s0, s0, s1
        self.assertEqual(fmul_s(w[7]), (0, 0, 1))
        self.assertEqual(w[6] & 0xff201fe0, 0x1e201000)                   # fmov s1, #30.0
        self.assertEqual(w[6] & 31, 1)
        self.assertEqual(vfp_expand_imm32((w[6] >> 13) & 0xff), 30.0)

    def test_site_words(self):
        self.assertEqual(fx.STEP_ADD, 0x91000000 | (0x470 << 10) | (22 << 5) | 22)       # add x22, x22, #0x470
        self.assertEqual(fx.FIXED_FMOV & 0xffe01fe0, 0x1e201000)                          # fmov s0, #imm
        self.assertEqual(fx.FIXED_FMOV & 31, 0)
        self.assertEqual(vfp_expand_imm32((fx.FIXED_FMOV >> 13) & 0xff), 1.0)
        self.assertEqual(vfp_expand_imm32((fx.HALF_FMOV >> 13) & 0xff), 0.5)
        self.assertEqual(fx.STEP_STORE, 0x2d0002c0)                                       # stp s0, s0, [x22]
        # the C passes and checks the same words
        self.assertIn('fps60_fx(m, v4, fs, 0x9111c2d6u, page', SRC)
        self.assertIn('fps60_fx(m, v5, ff, 0x1e2e1000u, page', SRC)
        for w in (fx.SPEED_CALL, fx.STEP_STORE, fx.HALF_FMOV, fx.HALF_TST):
            self.assertIn(f'{w:#010x}u', SRC)

    def test_sites_per_version(self):
        s = fx.c_sites(SRC)
        self.assertEqual(s['v200'], (0x289730, 0x28695c))
        self.assertEqual(s['v101'], (0x289290, 0x2864bc))
        for v in s:
            self.assertEqual(s['v200'][0] - s['v101'][0], 0x4a0)
            self.assertEqual(s['v200'][1] - s['v101'][1], 0x4a0)

    def test_layout_and_encoding(self):
        # 2.0.0's main: the prompt's veneers end at +0x17350d4 (test_fps60_qte_patch), the effect engine's follow
        page, v4, v5 = fx.layout(0x1735050, 75790360)
        self.assertEqual((v4, v5), (0x17350e0, 0x1735110))
        self.assertLessEqual(v5 + 36, 0x1736000)                          # the read-only data starts at +0x1736000
        for ven, site, orig in ((v4, 0x289730, fx.STEP_ADD), (v5, 0x28695c, fx.FIXED_FMOV)):
            words = fx.fx_words(fx.c_veneer(SRC), ven, site, orig, page)
            self.assertEqual(len(words), 10)
            self.assertEqual(words[ven], orig)
            back = words[ven + 32]
            self.assertEqual(back >> 26, 0b000101)                        # b, not bl
            delta = (back & 0x3ffffff) << 2
            delta -= 1 << 28 if delta & (1 << 27) else 0
            self.assertEqual(ven + 32 + delta, site + 4)
            self.assertEqual(words[site] >> 26, 0b000101)
            self.assertEqual(site + ((words[site] & 0x3ffffff) << 2), ven)
            adrp = words[ven + 4]
            imm = ((adrp >> 29) & 3) | (((adrp >> 5) & 0x7ffff) << 2)
            self.assertEqual(adrp & 0x9f00001f, 0x90000010)               # adrp x16
            self.assertEqual(((ven + 4) >> 12) + imm, page >> 12)

    def test_apply_fps60_writes_both(self):
        body = re.search(r'static void apply_fps60\(Module \*m\) \{(.*?)\n\}', SRC, re.S).group(1)
        self.assertEqual(body.count('fps60_fx('), 2)
        self.assertIn('v5 + sizeof fps60_fx_veneer > end', body)          # the last veneer is the one checked


@unittest.skipUnless((WORK / 'rewritten/v200/main.patched.bin').is_file() and (WORK / 'build/v200/runtime_tables.h').is_file(),
                     'needs the work folder (XCX_build) with the rewritten images')
class Images(unittest.TestCase):
    def test_shipped_words_and_padding(self):
        for version, (step, fixed) in fx.c_sites(SRC).items():
            path = WORK / f'rewritten/{version}/main.patched.bin'
            if not path.is_file() or not (WORK / f'build/{version}/runtime_tables.h').is_file():
                continue
            with self.subTest(version=version):
                image = path.read_bytes()
                word = lambda off: struct.unpack_from('<I', image, off)[0]
                self.assertEqual(word(step - 8), fx.SPEED_CALL)
                self.assertEqual(word(step), fx.STEP_ADD)
                self.assertEqual(word(step + 4), fx.STEP_STORE)
                self.assertEqual(word(fixed), fx.FIXED_FMOV)
                self.assertEqual(word(fixed + 4), fx.HALF_FMOV)
                self.assertEqual(word(fixed + 0xc), fx.HALF_TST)
                text_end, file_size = q.module_layout(WORK, version)
                self.assertEqual(file_size, len(image))
                page, v0, _, _, _ = q.layout(text_end, file_size)
                _, v4, v5 = fx.layout(text_end, file_size)
                self.assertEqual(image[v0:v5 + 36], bytes(v5 + 36 - v0))


if __name__ == '__main__':
    unittest.main()
