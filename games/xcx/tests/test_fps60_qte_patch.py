"""The 60 fps patch's sites 3 and 4 (runtime/game_patches.c, the timed B-button prompt): the veneer's words decode to the
intended instructions, the sites of both versions are the same code, and (when the work folder is there) the images hold
the shipped words at the sites and zero padding where the veneers go. scripts/verify_fps60_qte_patch.py runs the code."""
import re
import struct
import sys
import unittest
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'scripts'))
import verify_fps60_qte_patch as q

WORK = GAME.parents[1] / 'XCX_build'
SRC = q.source_text()


def ldr_s_imm(word):
    """LDR St, [Xn, #imm] (unsigned offset): (t, n, imm) or None."""
    if word & 0xffc00000 != 0xbd400000:
        return None
    return word & 31, (word >> 5) & 31, ((word >> 10) & 0xfff) * 4


def vfp_expand_imm32(imm8):
    """VFPExpandImm for single precision."""
    sign, b6 = imm8 >> 7, (imm8 >> 6) & 1
    exp = ((1 - b6) << 7) | ((0x1f if b6 else 0) << 2) | ((imm8 >> 4) & 3)
    bits = (sign << 31) | (exp << 23) | ((imm8 & 0xf) << 19)
    return struct.unpack('<f', struct.pack('<I', bits))[0]


class Definition(unittest.TestCase):
    def test_veneer_words(self):
        w = q.c_veneer(SRC)
        self.assertEqual(w[0], 0); self.assertEqual(w[1], 0); self.assertEqual(w[8], 0)   # filled in by fps60_qte
        self.assertEqual(w[2], 0xb9400a11)                                # ldr w17, [x16, #8]: the mode, as GetFrameTime's veneer
        self.assertEqual(w[3] & 0xff00001f, 0x34000011)                   # cbz w17
        self.assertEqual(3 + ((w[3] >> 5) & 0x7ffff), 8)                  # ... to the branch back
        self.assertEqual(ldr_s_imm(w[4]), (2, 16, 0))                     # ldr s2, [x16]: the frame time at +0
        for i in (5, 7):                                                  # fmul s1, s1, s2
            self.assertEqual(w[i] & 0xff20fc00, 0x1e200800)
            self.assertEqual((w[i] & 31, (w[i] >> 5) & 31, (w[i] >> 16) & 31), (1, 1, 2))
        self.assertEqual(w[6] & 0xff201fe0, 0x1e201000)                   # fmov s2, #imm
        self.assertEqual(w[6] & 31, 2)
        self.assertEqual(vfp_expand_imm32((w[6] >> 13) & 0xff), 30.0)

    def test_site_loads(self):
        self.assertEqual(ldr_s_imm(q.RING_LOAD), (1, 19, 0x120))
        self.assertEqual(ldr_s_imm(q.JUDGE_LOAD), (1, 0, 0x120))
        # the C passes the same words
        self.assertIn('fps60_qte(m, v2, qr, 0xbd412261u, page', SRC)
        self.assertIn('fps60_qte(m, v3, qj, 0xbd412001u, page', SRC)

    def test_sites_per_version(self):
        s = q.c_sites(SRC)
        self.assertEqual(s['v200'], (0x5c6280, 0x5c64fc))
        self.assertEqual(s['v101'], (0x5c5870, 0x5c5aec))
        for ring, judge in s.values():
            self.assertEqual(judge - ring, 0x27c)
        self.assertEqual(s['v200'][0] - s['v101'][0], 0xa10)

    def test_layout_and_encoding(self):
        # 2.0.0's main (runtime_tables.h): veneers 1 and 2 at +0x1735050 / +0x1735060 (CHANGELOG), the prompt's after them
        page, v0, v1, v2, v3 = q.layout(0x1735050, 75790360)
        self.assertEqual((v0, v1, v2, v3), (0x1735050, 0x1735060, 0x1735080, 0x17350b0))
        self.assertEqual(v3 + 36, 0x17350d4)
        self.assertLessEqual(v3 + 36, 0x1736000)                          # the read-only data starts at +0x1736000
        words = q.qte_words(q.c_veneer(SRC), v2, 0x5c6280, q.RING_LOAD, page)
        self.assertEqual(len(words), 10)
        self.assertEqual(words[v2], q.RING_LOAD)
        back = words[v2 + 32]
        self.assertEqual(back >> 26, 0b000101)                            # b, not bl: the judge is a leaf
        delta = (back & 0x3ffffff) << 2
        delta -= 1 << 28 if delta & (1 << 27) else 0
        self.assertEqual(v2 + 32 + delta, 0x5c6284)
        site = words[0x5c6280]
        self.assertEqual(0x5c6280 + ((site & 0x3ffffff) << 2), v2)
        adrp = words[v2 + 4]
        imm = ((adrp >> 29) & 3) | (((adrp >> 5) & 0x7ffff) << 2)
        self.assertEqual(adrp & 0x9f00001f, 0x90000010)                   # adrp x16
        self.assertEqual(((v2 + 4) >> 12) + imm, page >> 12)

    def test_ios_build_exports_the_patch(self):
        build_ipa = (GAME / 'ios/tools/build_ipa.py').read_text()
        self.assertRegex(build_ipa, r"env\['XCX_PATCHES'\] = '60fps'")
        # the prompt's sites are written by apply_fps60, the function the export runs
        body = re.search(r'static void apply_fps60\(Module \*m\) \{(.*?)\n\}', SRC, re.S).group(1)
        self.assertEqual(body.count('fps60_qte('), 2)


@unittest.skipUnless((WORK / 'rewritten/v200/main.patched.bin').is_file() and (WORK / 'build/v200/runtime_tables.h').is_file(),
                     'needs the work folder (XCX_build) with the rewritten images')
class Images(unittest.TestCase):
    def test_shipped_words_and_padding(self):
        for version, (ring, judge) in q.c_sites(SRC).items():
            path = WORK / f'rewritten/{version}/main.patched.bin'
            if not path.is_file() or not (WORK / f'build/{version}/runtime_tables.h').is_file():
                continue
            with self.subTest(version=version):
                image = path.read_bytes()
                word = lambda off: struct.unpack_from('<I', image, off)[0]
                self.assertEqual(word(ring), q.RING_LOAD)
                self.assertEqual(word(judge), q.JUDGE_LOAD)
                self.assertEqual(word(ring - 0x14), 0xbd411e60)          # ldr s0, [x19, #0x11c]
                self.assertEqual(word(ring + 4), 0x1e213800)             # fsub s0, s0, s1
                self.assertEqual(word(judge - 0xc), 0xbd411c00)          # ldr s0, [x0, #0x11c]
                self.assertEqual(word(judge + 4), 0x1e212800)            # fadd s0, s0, s1
                self.assertEqual(word(judge - 0x3c), 0x51080429)         # the judge's first word
                text_end, file_size = q.module_layout(WORK, version)
                self.assertEqual(file_size, len(image))
                page, v0, v1, v2, v3 = q.layout(text_end, file_size)
                self.assertEqual(image[v0:v3 + 36], bytes(v3 + 36 - v0))


if __name__ == '__main__':
    unittest.main()
