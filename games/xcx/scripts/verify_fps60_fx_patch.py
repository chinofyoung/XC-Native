#!/usr/bin/env python3
"""Run the effect engine's step of main 2.0.0 / 1.0.1 with Unicorn, as shipped and with sites 5 and 6 of the 60 fps patch
(runtime/game_patches.c, apply_fps60 / fps60_fx; CHANGELOG "60 fps: effects, and the item that flies to the player").

The effect engine (the .wiefb effects; among them cmn_102_100.wiefb, the item that flies from a collectible or a treasure
container to the player) steps every effect by a fixed amount a frame, in 30 fps frames. Its update (v200 main+0x2896c0)
takes the game speed (main+0x289728 bl: [[main+0x1dbf108] + 0x254], 1.0, 0 while paused) and stores it as the frame's
step (main+0x289734 stp s0, s0 -> main+0x1d81470 / +0x1d81474); the calc (main+0x286920) keeps a fixed 1.0 for effects
that ignore the game speed (main+0x28695c fmov s0, #1.0 -> s10) and advances each effect's frame counter (+0x174) by its
speed (+0xd4) x the step (s8, or s10 when +0xce is set) at main+0x286d64..0x286da4. These three blocks run here on the
real image, with the host page laid out as the runtime writes it (+0 frame time, +4 vsync count, +8 mode):
- shipped at 30 fps is the reference: an effect of L frames ends after L/30 s;
- shipped at 60 fps is the bug and the negative control: the same number of frames, so half the time;
- patched (mode 1, frame time = 1/fps) at 20, 30, 45, 60 and 120 fps: it ends within one frame of L/30 s, for both kinds
  of effect; paused (game speed 0) an effect that follows the game speed stays where it is;
- patched in mode 0 (30 fps, or XCX_FPS60=0): every step and counter equals the shipped code bit for bit.
The veneer words and the sites are parsed from game_patches.c (fps60_fx_veneer, FPS60_FX_STEP / FPS60_FX_FIXED), and the
veneers go where the runtime puts them (after the prompt's two), so this checks what the runtime writes. With --exported
<dir> (TOTK_EXPORT_IOS's main.x0.bin, as build_ipa.py embeds it) the words there must equal the ones built here.
Needs unicorn (pip install unicorn; XCX_build/venv has it).
usage: verify_fps60_fx_patch.py [--version {v101,v200}] [--work XCX_build] [--exported <dir>]"""
import argparse
import re
import struct
from pathlib import Path

import verify_fps60_qte_patch as q

STEP_ADD, FIXED_FMOV = 0x9111c2d6, 0x1e2e1000          # add x22, x22, #0x470 / fmov s0, #1.0
SPEED_CALL, STEP_STORE = 0x97ffa232, 0x2d0002c0        # bl <game speed> (site 5 - 8) / stp s0, s0, [x22] (site 5 + 4)
HALF_FMOV, HALF_TST = 0x1e2c1001, 0x7200001f           # fmov s1, #0.5 (site 6 + 4) / tst w0, #1 (site 6 + 0xc)
f32 = q.f32


def c_sites(src):
    """{'v200': (step, fixed), 'v101': (step, fixed)} from the FPS60_FX_* defines."""
    m = re.search(r'#if defined\(XCX_GAME_V200\)\n#define FPS60_FX_STEP\s+(0x[0-9a-f]+)ULL.*?\n#define FPS60_FX_FIXED\s+(0x[0-9a-f]+)ULL'
                  r'.*?\n#else\n#define FPS60_FX_STEP\s+(0x[0-9a-f]+)ULL.*?\n#define FPS60_FX_FIXED\s+(0x[0-9a-f]+)ULL', src, re.S)
    if not m:
        raise SystemExit('FPS60_FX_STEP / FPS60_FX_FIXED not found in game_patches.c')
    a = [int(x, 16) for x in m.groups()]
    return {'v200': (a[0], a[1]), 'v101': (a[2], a[3])}


def c_veneer(src):
    """fps60_fx_veneer's 9 words (0 = filled in at run time)."""
    m = re.search(r'static const uint32_t fps60_fx_veneer\[9\] = \{(.*?)\};', src, re.S)
    if not m:
        raise SystemExit('fps60_fx_veneer not found in game_patches.c')
    body = re.sub(r'/\*.*?\*/', '', m.group(1), flags=re.S)
    words = [int(w.rstrip('u'), 16) if w.startswith('0x') else int(w) for w in re.findall(r'0x[0-9a-fA-F]+u?|\b0\b', body)]
    if len(words) != 9:
        raise SystemExit(f'fps60_fx_veneer: {len(words)} words, expected 9')
    return words


def layout(text_end, file_size):
    """apply_fps60: the host page and the effect engine's two veneer slots (v4 step, v5 fixed step), after v0..v3."""
    page, v0, v1, v2, v3 = q.layout(text_end, file_size)
    v4 = v3 + 48
    return page, v4, v4 + 48


def fx_words(template, ven, site, orig, page):
    """fps60_fx: {offset: word} for one veneer and its site."""
    w = list(template)
    w[0] = orig
    w[1] = q.enc_adrp(16, ven + 4, page)
    w[8] = q.enc_branch(ven + 32, site + 4)
    out = {ven + 4 * i: x for i, x in enumerate(w)}
    out[site] = q.enc_branch(site, ven)
    return out


def branch_target(image, at):
    w = struct.unpack_from('<I', image, at)[0]
    assert w & 0x7c000000 == 0x14000000, f'main+{at:#x} is not b/bl'
    off = w & 0x3ffffff
    return at + ((off - (1 << 26) if off & (1 << 25) else off) << 2)


def adrp_add(image, at):
    """The address formed by adrp xN at `at` and add xN, xN, #lo at `at + 4`."""
    a, b = struct.unpack_from('<II', image, at)
    assert a & 0x9f000000 == 0x90000000 and b & 0xff800000 == 0x91000000, f'main+{at:#x} is not adrp + add'
    imm = ((a >> 29) & 3) | (((a >> 5) & 0x7ffff) << 2)
    imm -= 1 << 21 if imm & (1 << 20) else 0
    return ((at >> 12) + imm << 12) + ((b >> 10) & 0xfff)


def main():
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn import arm64_const as A

    p = argparse.ArgumentParser(description='Unicorn check of the 60 fps patch for the effect engine')
    p.add_argument('--version', choices=('v101', 'v200'), default='v200')
    p.add_argument('--work', type=Path, default=q.GAME.parents[1] / 'XCX_build')
    p.add_argument('--exported', type=Path, help='TOTK_EXPORT_IOS output folder holding main.x0.bin')
    a = p.parse_args()
    image = bytearray((a.work / f'rewritten/{a.version}/main.patched.bin').read_bytes())
    text_end, file_size = q.module_layout(a.work, a.version)
    if file_size != len(image):
        raise SystemExit('main.patched.bin and runtime_tables.h disagree')
    src = q.source_text()
    step_site, fixed_site = c_sites(src)[a.version]
    template = c_veneer(src)
    page, v4, v5 = layout(text_end, file_size)
    word = lambda off: struct.unpack_from('<I', image, off)[0]
    shipped = {step_site - 8: SPEED_CALL, step_site: STEP_ADD, step_site + 4: STEP_STORE,
               fixed_site: FIXED_FMOV, fixed_site + 4: HALF_FMOV, fixed_site + 0xc: HALF_TST}
    for off, w in shipped.items():
        if word(off) != w:
            raise SystemExit(f'main+{off:#x} is {word(off):08x}, not the shipped {w:08x}')
    _, v0, _, _, _ = q.layout(text_end, file_size)
    for off in range(v0, v5 + 36, 4):
        if word(off) != 0:
            raise SystemExit(f'main+{off:#x} is not zero padding')
    if v5 + 36 > ((text_end + 0xfff) & ~0xfff):
        raise SystemExit('the veneers reach read-only data')
    patch = {**fx_words(template, v4, step_site, STEP_ADD, page), **fx_words(template, v5, fixed_site, FIXED_FMOV, page)}

    # The data the three blocks read, found from the code itself (the same in both versions, at other addresses).
    speed_fn = branch_target(image, branch_target(image, step_site - 8))     # bl -> b -> the game speed getter
    speed_ptr = adrp_add(image, speed_fn)                                      # [ptr] + 0x254: the game speed
    step_var = adrp_add(image, step_site - 4)                                  # the step and its copy (+4)
    flag_fn = branch_target(image, fixed_site - 4)                             # the engine's half-step flag
    flag_ptr = adrp_add(image, flag_fn)
    calc = fixed_site - 0x3c                                                   # the calc's first word (sub sp, ...)
    counter_start, counter_end = fixed_site + 0x3c8, fixed_site + 0x44c       # constants, then the counter block

    failures = []

    def check(ok, what):
        print(('ok    ' if ok else 'FAIL  ') + what)
        if not ok:
            failures.append(what)

    if a.exported:
        x0 = (a.exported / 'main.x0.bin').read_bytes()
        bad = [off for off, w in patch.items() if struct.unpack_from('<I', x0, off)[0] != w]
        check(not bad, f'exported text (main.x0.bin) holds the {len(patch)} words built here' + (f'; differs at {[hex(b) for b in bad]}' if bad else ''))

    check(word(speed_fn + 0x10) == 0xbd425500 and word(speed_fn + 0x14) == 0xd65f03c0,
          f'game speed getter main+{speed_fn:#x} returns [[main+{speed_ptr:#x}] + 0x254]')
    check(word(flag_fn + 0x10) == 0x394c0508, f'half-step flag main+{flag_fn:#x} reads [[main+{flag_ptr:#x}] + 0x301]')
    check(word(counter_start + 0x40) == 0x39433a68 and word(counter_end - 4) == 0xbd017660,
          f'frame counter block main+{counter_start + 0x40:#x}..+{counter_end:#x} (ldrb w8, [x19, #0xce] .. str s0, [x19, #0x174])')
    patched_image = bytearray(image)
    for off, w in patch.items():
        struct.pack_into('<I', patched_image, off, w)

    SPEED_OBJ, FX, STACK = 0x7000_0000, 0x7000_1000, 0x7100_0000

    class Engine:
        def __init__(self, img, mode, step):
            self.uc = uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
            uc.mem_map(0, page + 0x4000)
            uc.mem_write(0, bytes(img))
            uc.mem_write(page, struct.pack('<fii', f32(step), 1 if mode else 2, mode))
            uc.mem_map(SPEED_OBJ, 0x2000)
            uc.mem_map(STACK - 0x10000, 0x10000)
            uc.mem_write(speed_ptr, struct.pack('<Q', SPEED_OBJ))
            uc.mem_write(flag_ptr, struct.pack('<Q', 0))                      # the engine's own half step: off
            uc.reg_write(A.UC_ARM64_REG_SP, STACK - 0x100)

        def frame(self, speed, kind):
            """One frame of the engine: the step (site 5), the fixed step (site 6), then one effect's counter.
            kind 0: the effect follows the game speed (+0xce = 0); 1: it ignores it (+0xce = 1)."""
            uc = self.uc
            uc.mem_write(SPEED_OBJ + 0x254, struct.pack('<f', f32(speed)))
            uc.emu_start(step_site - 8, step_site + 8, count=64)               # bl speed .. stp s0, s0, [x22]
            s8, copy = struct.unpack('<ff', uc.mem_read(step_var, 8))
            uc.emu_start(fixed_site - 4, fixed_site + 0x18, count=64)          # bl flag .. fcsel s10
            s10 = struct.unpack('<f', uc.reg_read(A.UC_ARM64_REG_D10).to_bytes(16, 'little')[:4])[0]
            uc.mem_write(FX + 0xce, bytes([kind]))
            uc.mem_write(FX + 0xd4, struct.pack('<f', 1.0))                   # the effect's own speed
            uc.reg_write(A.UC_ARM64_REG_X19, FX)
            uc.reg_write(A.UC_ARM64_REG_D8, struct.unpack('<I', struct.pack('<f', s8))[0])
            uc.emu_start(counter_start, counter_end, count=64)
            return s8, copy, s10, struct.unpack('<f', uc.mem_read(FX + 0x174, 4))[0]

    def run(img, mode, fps, length, kind, speed=1.0, limit=None):
        """Frames until the counter reaches `length` (30 fps frames), and every frame's (step, copy, fixed, counter)."""
        eng = Engine(img, mode, f32(1 / fps))
        trace = []
        while len(trace) < (limit or 10 * length + 10):
            trace.append(eng.frame(speed, kind))
            if trace[-1][3] >= length:
                break
        return len(trace), trace

    for kind, name in ((0, 'effect that follows the game speed'), (1, 'effect that ignores the game speed')):
        for length in (8, 15, 30, 45):
            ref = run(image, 0, 30, length, kind)
            check(ref[0] == length, f'{name}, L={length}: shipped at 30 fps it ends on frame {ref[0]} ({ref[0] / 30:.3f} s)')
            ref_t = ref[0] / 30
            bug = run(image, 0, 60, length, kind)
            check(bug[0] == ref[0] and bug[0] / 60 < 0.6 * ref_t,
                  f'{name}, L={length}: shipped at 60 fps (negative control) ends after {bug[0] / 60:.3f} s instead of {ref_t:.3f} s')
            for mode_fps in (30, 60):
                m0 = run(patched_image, 0, mode_fps, length, kind)
                check(m0 == ref, f'{name}, L={length}: patched in mode 0 at {mode_fps} fps equals the shipped code bit for bit')
            for fps in (20, 30, 45, 60, 120):
                got = run(patched_image, 1, fps, length, kind)
                t = got[0] / fps
                check(abs(t - ref_t) <= 1 / fps + 1e-6,
                      f'{name}, L={length}: patched at {fps} fps it ends after {t:.3f} s (reference {ref_t:.3f} s)')
        exact = run(patched_image, 1, 30, 30, kind)
        ref = run(image, 0, 30, 30, kind)
        check(exact[0] == ref[0] and max(abs(x[3] - y[3]) for x, y in zip(exact[1], ref[1])) < 1e-4,
              f'{name}: patched at 1/30 s a frame matches the shipped counter within float rounding')

    # Game speed: paused (0) and half speed, mode 1 at 60 fps and mode 0 against the shipped code.
    for speed in (0.0, 0.5):
        for kind in (0, 1):
            ref = run(image, 0, 30, 1e9, kind, speed, limit=90)
            m0 = run(patched_image, 0, 30, 1e9, kind, speed, limit=90)
            check(m0 == ref, f'game speed {speed}, +0xce={kind}: patched in mode 0 equals the shipped code')
            got = run(patched_image, 1, 60, 1e9, kind, speed, limit=180)
            want = [r[3] for r in ref[1]][-1]                                 # after 90 frames at 30 fps (3 s)
            have = [r[3] for r in got[1]][-1]                                 # after 180 frames at 60 fps (3 s)
            check(abs(have - want) <= 1e-3 + 0.5 * (speed if kind == 0 else 1.0),
                  f'game speed {speed}, +0xce={kind}: after 3 s at 60 fps the counter is {have:.3f} (30 fps shipped: {want:.3f})')
    s = run(patched_image, 1, 60, 30, 0, 1.0, limit=1)[1][0]
    check(s[0] == s[1] and abs(s[0] - 0.5) < 1e-6 and abs(s[2] - 0.5) < 1e-6,
          f'at 60 fps the step and its copy are {s[0]:.6f} / {s[1]:.6f} and the fixed step {s[2]:.6f} (0.5 each)')
    if failures:
        raise SystemExit(f'{len(failures)} check(s) failed')
    print(f'60 fps effect step patch ({a.version}): all checks passed; step main+{step_site:#x}, fixed step main+{fixed_site:#x}, '
          f'veneers main+{v4:#x}..+{v5 + 36:#x}; calc main+{calc:#x}')


if __name__ == '__main__':
    main()
