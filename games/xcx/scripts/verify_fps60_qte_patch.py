#!/usr/bin/env python3
"""Run the timed B-button prompt (the "Soul Challenge") of main 2.0.0 / 1.0.1 with Unicorn, as shipped and with sites 3
and 4 of the 60 fps patch (runtime/game_patches.c, apply_fps60 / fps60_qte; CHANGELOG "60 fps: the timed B-button prompt").

The prompt's ring starts at 30.0 (+0x11c) and every frame loses speed = 30/N (+0x120; N = its lifetime in 30 fps frames,
from BDAT BTL_BtnChallengeLv). The ring block of the update (v200 main+0x5c626c..0x5c628c) and the Perfect/Good judge
(main+0x5c64c0, a leaf: Perfect 2 if 6.9 <= ring + speed <= 12, Good 1 if 0..6.9 or 12..15, else Failed 0 at +0x110)
run on the real image with the host page laid out as the runtime writes it (+0 frame time, +4 vsync count, +8 mode).
- shipped at 30 fps is the reference: the ring runs out after N frames (N/30 s);
- shipped at 60 fps is the bug and the negative control: half the time;
- patched (mode 1, frame time = 1/fps) at 20, 30, 45, 60 and 120 fps: the ring runs out within one frame of N/30 s, and a
  press at a given real time gets the reference verdict, except within one 30 fps frame plus one frame of a window edge;
- patched in mode 0 (30 fps, or XCX_FPS60=0): the ring and every verdict equal the shipped code bit for bit.
The veneer words and the sites are parsed from game_patches.c (fps60_qte_veneer, FPS60_QTE_RING / FPS60_QTE_JUDGE), and
the veneers go where the runtime puts them (after the two veneers of sites 1 and 2, from main's text end), so this checks
what the runtime writes. With --exported <dir> (TOTK_EXPORT_IOS's main.x0.bin, the text the runtime patched, as build_ipa.py
embeds it) the words there must equal the ones built here.
Needs unicorn (pip install unicorn; XCX_build/venv has it).
usage: verify_fps60_qte_patch.py [--version {v101,v200}] [--work XCX_build] [--exported <dir>]"""
import argparse
import re
import struct
import sys
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
SOURCE = GAME / 'runtime/game_patches.c'
RING_LOAD, JUDGE_LOAD = 0xbd412261, 0xbd412001          # ldr s1, [x19, #0x120] / ldr s1, [x0, #0x120]
PERFECT, GOOD, FAILED = 2, 1, 0


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def enc_adrp(rd, site, target):
    """game_patches.c enc_adrp: offsets in main (its base is page aligned)."""
    pages = (target >> 12) - (site >> 12)
    assert -(1 << 20) <= pages < (1 << 20), 'host page outside ADRP range'
    imm = pages & 0x1fffff
    return 0x90000000 | ((imm & 3) << 29) | ((imm >> 2) << 5) | (rd & 31)


def enc_branch(site, target, link=False):
    """game_patches.c enc_branch."""
    delta = target - site
    assert not delta & 3 and -(1 << 27) <= delta < (1 << 27), 'branch outside range'
    return (0x94000000 if link else 0x14000000) | ((delta >> 2) & 0x3ffffff)


def source_text(path=SOURCE):
    return Path(path).read_text()


def c_sites(src):
    """{'v200': (ring, judge), 'v101': (ring, judge)} from the FPS60_QTE_* defines."""
    m = re.search(r'#if defined\(XCX_GAME_V200\)\n#define FPS60_QTE_RING\s+(0x[0-9a-f]+)ULL.*?\n#define FPS60_QTE_JUDGE\s+(0x[0-9a-f]+)ULL'
                  r'.*?\n#else\n#define FPS60_QTE_RING\s+(0x[0-9a-f]+)ULL.*?\n#define FPS60_QTE_JUDGE\s+(0x[0-9a-f]+)ULL', src, re.S)
    if not m:
        raise SystemExit('FPS60_QTE_RING / FPS60_QTE_JUDGE not found in game_patches.c')
    a = [int(x, 16) for x in m.groups()]
    return {'v200': (a[0], a[1]), 'v101': (a[2], a[3])}


def c_veneer(src):
    """fps60_qte_veneer's 9 words (0 = filled in at run time)."""
    m = re.search(r'static const uint32_t fps60_qte_veneer\[9\] = \{(.*?)\};', src, re.S)
    if not m:
        raise SystemExit('fps60_qte_veneer not found in game_patches.c')
    body = re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S)
    words = [int(w.rstrip('u'), 16) if w.startswith('0x') else int(w) for w in re.findall(r'0x[0-9a-fA-F]+u?|\b0\b', body)]
    if len(words) != 9:
        raise SystemExit(f'fps60_qte_veneer: {len(words)} words, expected 9')
    return words


def layout(text_end, file_size):
    """apply_fps60: the host page and the four veneer slots (v0 vsync, v1 frame time, v2 ring step, v3 judge)."""
    page = (file_size + 0x3fff) & ~0x3fff
    v0 = (text_end + 15) & ~15
    v1 = v0 + 16
    v2 = v1 + 32
    v3 = v2 + 48
    return page, v0, v1, v2, v3


def qte_words(template, ven, site, load, page):
    """fps60_qte: {offset: word} for one veneer and its site."""
    w = list(template)
    w[0] = load
    w[1] = enc_adrp(16, ven + 4, page)
    w[8] = enc_branch(ven + 32, site + 4)
    out = {ven + 4 * i: x for i, x in enumerate(w)}
    out[site] = enc_branch(site, ven)
    return out


def module_layout(work, version):
    """main's text_end and file_size from the generated runtime_tables.h."""
    tables = (work / f'build/{version}/runtime_tables.h').read_text()
    m = re.search(r'\{\.name="main",[^}]*?\.file_size=(\d+)ULL,\.text_end=(\d+)ULL', tables)
    if not m:
        raise SystemExit(f'main not found in {work}/build/{version}/runtime_tables.h (make prepare VERSION={version})')
    return int(m.group(2)), int(m.group(1))


def main():
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn import arm64_const as A

    p = argparse.ArgumentParser(description='Unicorn check of the 60 fps patch for the timed B-button prompt')
    p.add_argument('--version', choices=('v101', 'v200'), default='v200')
    p.add_argument('--work', type=Path, default=GAME.parents[1] / 'XCX_build')
    p.add_argument('--exported', type=Path, help='TOTK_EXPORT_IOS output folder holding main.x0.bin')
    a = p.parse_args()
    image = bytearray((a.work / f'rewritten/{a.version}/main.patched.bin').read_bytes())
    text_end, file_size = module_layout(a.work, a.version)
    if file_size != len(image):
        raise SystemExit('main.patched.bin and runtime_tables.h disagree')
    src = source_text()
    ring, judge = c_sites(src)[a.version]
    template = c_veneer(src)
    page, v0, v1, v2, v3 = layout(text_end, file_size)
    word = lambda off: struct.unpack_from('<I', image, off)[0]
    shipped = {ring - 0x14: 0xbd411e60, ring: RING_LOAD, ring + 4: 0x1e213800,
               judge - 0xc: 0xbd411c00, judge: JUDGE_LOAD, judge + 4: 0x1e212800}
    for off, w in shipped.items():
        if word(off) != w:
            raise SystemExit(f'main+{off:#x} is {word(off):08x}, not the shipped {w:08x}')
    patch = {**qte_words(template, v2, ring, RING_LOAD, page), **qte_words(template, v3, judge, JUDGE_LOAD, page)}
    for off in range(v0, v3 + 36, 4):
        if word(off) != 0:
            raise SystemExit(f'main+{off:#x} is not zero padding')
    if v3 + 36 > ((text_end + 0xfff) & ~0xfff):
        raise SystemExit('the veneers reach read-only data')

    failures = []

    def check(ok, what):
        print(('ok    ' if ok else 'FAIL  ') + what)
        if not ok:
            failures.append(what)

    if a.exported:
        x0 = (a.exported / 'main.x0.bin').read_bytes()
        bad = [off for off, w in patch.items() if struct.unpack_from('<I', x0, off)[0] != w]
        check(not bad, f'exported text (main.x0.bin) holds the {len(patch)} words built here' + (f'; differs at {[hex(b) for b in bad]}' if bad else ''))

    judge_fn = judge - 0x3c                                 # sub w9, w1, #0x201
    check(word(judge_fn) == 0x51080429, f'judge function at main+{judge_fn:#x}')
    OBJ, STOP = 0x7000_0000, 0x7100_0000
    patched_image = bytearray(image)
    for off, w in patch.items():
        struct.pack_into('<I', patched_image, off, w)

    class Prompt:
        def __init__(self, img, mode, step, speed):
            self.uc = uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
            uc.mem_map(0, page + 0x4000)
            uc.mem_write(0, bytes(img[:text_end + 0x1000]))   # text and the veneers: all the blocks touch
            uc.mem_write(page, struct.pack('<fii', f32(step), 1 if mode else 2, mode))
            uc.mem_map(OBJ, 0x1000)
            uc.mem_map(STOP, 0x1000)
            uc.mem_write(STOP, struct.pack('<I', 0xd503201f))
            uc.mem_write(OBJ + 0x110, struct.pack('<i', -1))  # no verdict yet (the update's tbz w8, #31)
            uc.mem_write(OBJ + 0x11c, struct.pack('<ff', 30.0, f32(speed)))

        def ring(self):
            return struct.unpack('<f', self.uc.mem_read(OBJ + 0x11c, 4))[0]

        def frame(self):
            """The update's ring block: ring -= step (from the ring load to its store)."""
            self.uc.reg_write(A.UC_ARM64_REG_X19, OBJ)
            self.uc.emu_start(ring - 0x14, ring + 0x10, count=64)
            return self.ring()

        def press(self):
            """The judge as the update calls it (w1 = 0x202); leaves the object as it was."""
            before = bytes(self.uc.mem_read(OBJ, 0x200))
            self.uc.reg_write(A.UC_ARM64_REG_X0, OBJ)
            self.uc.reg_write(A.UC_ARM64_REG_W1, 0x202)
            self.uc.reg_write(A.UC_ARM64_REG_LR, STOP)
            self.uc.emu_start(judge_fn, STOP, count=64)
            verdict = struct.unpack('<i', self.uc.mem_read(OBJ + 0x110, 4))[0]
            self.uc.mem_write(OBJ, before)
            return verdict

    def run(img, mode, fps, n, step=None):
        """Frames until the ring is below 0, the ring after each frame, and the verdict of a press on each frame."""
        pr = Prompt(img, mode, f32(1 / fps) if step is None else step, f32(30.0 / n))
        rings, verdicts = [], []
        while len(rings) < 10 * n:
            r = pr.frame()
            if r < 0:
                break
            rings.append(r)
            verdicts.append(pr.press())
        return len(rings) + 1, rings, verdicts

    def verdict_at(result, fps, t):
        """The verdict of a press at real time t: on the frame that ends at or after t (Failed once the ring ran out)."""
        _, _, verdicts = result
        k = max(0, int(-(-t * fps // 1)) - 1)
        return verdicts[k] if k < len(verdicts) else FAILED

    for n in (20, 30, 45, 60):
        ref = run(image, 0, 30, n)
        # A ring that lands on exactly 0.0 lives one frame more (the update fails it below 0), so N or N + 1 frames.
        check(ref[0] in (n, n + 1), f'N={n}: shipped at 30 fps the ring runs out on frame {ref[0]} ({ref[0] / 30:.3f} s)')
        ref_t = ref[0] / 30
        bug = run(image, 0, 60, n)                          # the shipped code knows no frame rate: same frames
        check(bug[0] == ref[0] and bug[0] / 60 < 0.6 * ref_t,
              f'N={n}: shipped at 60 fps (negative control) runs out after {bug[0] / 60:.3f} s instead of {ref_t:.3f} s')
        for mode_fps in (30, 60):
            m0 = run(patched_image, 0, mode_fps, n)
            check(m0 == ref, f'N={n}: patched in mode 0 at {mode_fps} fps equals the shipped code (rings and verdicts, bit for bit)')
        # the window edges as time: where the reference verdict changes, and where its ring runs out (then Failed)
        edges = [k / 30 for k in range(1, len(ref[2])) if ref[2][k] != ref[2][k - 1]] + [len(ref[2]) / 30]
        for fps in (20, 30, 45, 60, 120):
            got = run(patched_image, 1, fps, n)
            t = got[0] / fps
            ok_time = abs(t - ref_t) <= 1 / 30 + 1 / fps + 1e-6
            wrong = []
            for i in range(int(n / 30 * 1000)):              # every millisecond of the prompt
                tt = i / 1000
                if any(abs(tt - e) <= 1 / 30 + 1 / fps for e in edges):
                    continue
                if verdict_at(got, fps, tt) != verdict_at(ref, 30, tt):
                    wrong.append(tt)
            check(ok_time and not wrong, f'N={n}: patched at {fps} fps the ring runs out after {t:.3f} s (reference {ref_t:.3f} s), '
                  f'{len(wrong)} presses judged differently away from the window edges')
        exact = run(patched_image, 1, 30, n)
        same = exact[2] == ref[2][:len(exact[2])] and abs(exact[0] - ref[0]) <= 1   # only the 0.0 frame may go
        check(same and max(abs(x - y) for x, y in zip(exact[1], ref[1])) < 1e-4,
              f'N={n}: patched at 1/30 s a frame matches the shipped ring within float rounding, verdicts equal '
              f'(ring out on frame {exact[0]}, shipped {ref[0]})')
    if failures:
        raise SystemExit(f'{len(failures)} check(s) failed')
    print(f'60 fps prompt timer patch ({a.version}): all checks passed; ring step main+{ring:#x}, judge main+{judge:#x}, '
          f'veneers main+{v2:#x}..+{v3 + 36:#x}')


if __name__ == '__main__':
    main()
