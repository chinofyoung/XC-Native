"""acq_fence.h (the fence an acquired swapchain image's sync waits for, TOTK_ACQ_SYNC): compiles a small C program
against the header and runs it. Skipped when no C compiler is available."""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
NVN = os.path.normpath(os.path.join(HERE, "..", "third_party", "d2r_gfx", "gfx", "nvn"))

C_TEST = r"""
#include <stdio.h>
#include "acq_fence.h"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static int pick(const acq_track *a, const void *w, int idx, int mode, uint64_t *v, int *tok) { *v = 12345; *tok = 7; return acq_pick(a, w, idx, mode, v, tok); }

int main(void) {
    static acq_track a; static int wa, wb; int tok; uint64_t v;
    acq_reset(&a, &wa);
    /* never presented: the newest submission (earlier frames may be in flight) */
    for (int m = ACQ_TEX; m <= ACQ_NEXT; m++) CHECK(pick(&a, &wa, 0, m, &v, &tok) == -1, "never presented, mode %d", m);
    /* two images, round robin: frame k presents image (k-1) % 2 after fence 10*k */
    for (int k = 1; k <= 4; k++) acq_note_present(&a, &wa, (k - 1) % 2, 10u * k, 0);
    /* image 0 last presented at frame 3, replaced by frame 4; image 1 last presented at frame 4 (on screen) */
    CHECK(pick(&a, &wa, 0, ACQ_TEX, &v, &tok) == 1 && v == 30 && tok == 0, "image 0, own last present: %llu", (unsigned long long)v);
    CHECK(pick(&a, &wa, 0, ACQ_NEXT, &v, &tok) == 1 && v == 40, "image 0, the present that replaced it: %llu", (unsigned long long)v);
    CHECK(pick(&a, &wa, 1, ACQ_TEX, &v, &tok) == 1 && v == 40, "image 1, own last present: %llu", (unsigned long long)v);
    CHECK(pick(&a, &wa, 1, ACQ_NEXT, &v, &tok) == -1, "image 1 is on screen: caller takes the newest");
    /* three images: frames still overlap by two */
    acq_reset(&a, &wa);
    for (int k = 1; k <= 6; k++) acq_note_present(&a, &wa, (k - 1) % 3, 100u + k, k == 5);
    CHECK(pick(&a, &wa, 0, ACQ_TEX, &v, &tok) == 1 && v == 104 && tok == 0, "3 images, image 0 own: %llu", (unsigned long long)v);
    CHECK(pick(&a, &wa, 0, ACQ_NEXT, &v, &tok) == 1 && v == 105 && tok == 1, "3 images, image 0 replaced by frame 5 (a token): %llu tok %d", (unsigned long long)v, tok);
    CHECK(pick(&a, &wa, 2, ACQ_TEX, &v, &tok) == 1 && v == 106, "3 images, image 2 own: %llu", (unsigned long long)v);
    /* out of range index: the newest; an out-of-range present still counts as a present (replaces the image on screen) */
    CHECK(pick(&a, &wa, 4, ACQ_TEX, &v, &tok) == -1 && pick(&a, &wa, -1, ACQ_NEXT, &v, &tok) == -1, "index out of range");
    acq_note_present(&a, &wa, 9, 200, 0);
    CHECK(pick(&a, &wa, 2, ACQ_NEXT, &v, &tok) == 1 && v == 200, "out-of-range present replaces image 2: %llu", (unsigned long long)v);
    /* another window, a window initialised again: no record, the newest */
    CHECK(pick(&a, &wb, 0, ACQ_TEX, &v, &tok) == -1 && pick(&a, &wb, 0, ACQ_NEXT, &v, &tok) == -1, "another window");
    acq_note_present(&a, &wb, 0, 300, 0);   /* a present of another window starts over */
    CHECK(pick(&a, &wa, 0, ACQ_TEX, &v, &tok) == -1 && pick(&a, &wb, 0, ACQ_TEX, &v, &tok) == 1 && v == 300, "switch of windows");
    acq_reset(&a, &wb);
    CHECK(pick(&a, &wb, 0, ACQ_TEX, &v, &tok) == -1 && pick(&a, &wb, 0, ACQ_NEXT, &v, &tok) == -1, "window initialised again");
    /* past the ring: the oldest kept fence (later, so waits longer, never less) */
    acq_reset(&a, &wa);
    acq_note_present(&a, &wa, 0, 1000, 0);
    for (int k = 1; k <= ACQ_RING + 4; k++) acq_note_present(&a, &wa, 1, 1000u + k, 0);
    CHECK(pick(&a, &wa, 0, ACQ_TEX, &v, &tok) == 1 && v == 1000u + 5, "past the ring, own: %llu", (unsigned long long)v);
    CHECK(pick(&a, &wa, 0, ACQ_NEXT, &v, &tok) == 1 && v == 1000u + 5, "past the ring, next: %llu", (unsigned long long)v);
    /* exactly at the ring's edge: still the real entry */
    acq_reset(&a, &wa);
    acq_note_present(&a, &wa, 0, 2000, 0);
    for (int k = 1; k < ACQ_RING; k++) acq_note_present(&a, &wa, 1, 2000u + k, 0);
    CHECK(pick(&a, &wa, 0, ACQ_TEX, &v, &tok) == 1 && v == 2000, "ring edge, own: %llu", (unsigned long long)v);
    CHECK(pick(&a, &wa, 0, ACQ_NEXT, &v, &tok) == 1 && v == 2001, "ring edge, next: %llu", (unsigned long long)v);
    printf(fails ? "%d failures\n" : "ok\n", fails);
    return fails != 0;
}
"""


class AcqFenceTest(unittest.TestCase):
    def test_header(self):
        cc = shutil.which("cc") or shutil.which("clang")
        if not cc:
            self.skipTest("no C compiler")
        with tempfile.TemporaryDirectory() as d:
            src, exe = os.path.join(d, "t.c"), os.path.join(d, "t")
            with open(src, "w") as f:
                f.write(C_TEST)
            subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", NVN, src, "-o", exe], check=True)
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
