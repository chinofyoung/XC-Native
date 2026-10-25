"""usnap_split.h (the uniform snapshot cut around unfinished GPU writes): compiles a small C program against the header
and runs it. Skipped when no C compiler is available."""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
NVN = os.path.normpath(os.path.join(HERE, "..", "third_party", "d2r_gfx", "gfx", "nvn"))

C_TEST = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "usnap_split.h"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static int cmp(const void *x, const void *y) { const usnap_gw *a = x, *b = y; return a->lo < b->lo ? -1 : a->lo > b->lo; }

/* cuts [lo, hi) around w (sorted here); returns the piece count, pieces in out[2k], out[2k+1] */
static int cut(usnap_gw *w, int n, uint64_t lo, uint64_t hi, uint64_t *out, uint64_t *live) {
    qsort(w, (size_t)n, sizeof *w, cmp);
    uint64_t maxlen = 0; for (int i = 0; i < n; i++) if (w[i].hi - w[i].lo > maxlen) maxlen = w[i].hi - w[i].lo;
    usnap_cut c; usnap_cut_init(&c, w, n, usnap_gw_first(w, n, lo, maxlen), lo, hi);
    int k = 0; uint64_t a, b;
    while (usnap_cut_next(&c, &a, &b)) { out[2 * k] = a; out[2 * k + 1] = b; k++; }
    *live = c.live; return k;
}
static void expect(const char *what, usnap_gw *w, int n, uint64_t lo, uint64_t hi, const uint64_t *want, int nwant, uint64_t want_live) {
    uint64_t got[64], live; int k = cut(w, n, lo, hi, got, &live);
    int ok = k == nwant && live == want_live;
    for (int i = 0; ok && i < 2 * k; i++) ok = got[i] == want[i];
    CHECK(ok, "%s: %d pieces, live %llu (want %d, %llu)", what, k, (unsigned long long)live, nwant, (unsigned long long)want_live);
}

int main(void) {
    { usnap_gw w[1] = {{0, 0, 0, 0}}; uint64_t want[] = {100, 200}; expect("no writes", w, 0, 100, 200, want, 1, 0); }
    { usnap_gw w[] = {{0, 50, 1, 0}, {300, 400, 1, 0}}; uint64_t want[] = {100, 200}; expect("no overlap", w, 2, 100, 200, want, 1, 0); }
    { usnap_gw w[] = {{50, 100, 1, 0}, {200, 250, 1, 0}}; uint64_t want[] = {100, 200}; expect("adjacent outside, both ends", w, 2, 100, 200, want, 1, 0); }
    { usnap_gw w[] = {{100, 200, 1, 0}}; expect("full overlap, exact", w, 1, 100, 200, NULL, 0, 100); }
    { usnap_gw w[] = {{0, 1000, 1, 0}}; expect("full overlap, wider", w, 1, 100, 200, NULL, 0, 100); }
    { usnap_gw w[] = {{50, 130, 1, 0}}; uint64_t want[] = {130, 200}; expect("partial overlap at the start", w, 1, 100, 200, want, 1, 30); }
    { usnap_gw w[] = {{170, 260, 1, 0}}; uint64_t want[] = {100, 170}; expect("partial overlap at the end", w, 1, 100, 200, want, 1, 30); }
    { usnap_gw w[] = {{50, 130, 1, 0}, {170, 260, 1, 0}}; uint64_t want[] = {130, 170}; expect("partial overlaps at both ends", w, 2, 100, 200, want, 1, 60); }
    { usnap_gw w[] = {{120, 130, 1, 0}}; uint64_t want[] = {100, 120, 130, 200}; expect("inside", w, 1, 100, 200, want, 2, 10); }
    { usnap_gw w[] = {{180, 190, 1, 0}, {110, 120, 1, 0}, {140, 150, 1, 0}}; uint64_t want[] = {100, 110, 120, 140, 150, 180, 190, 200};
      expect("several writes inside (unsorted input)", w, 3, 100, 200, want, 4, 30); }
    { usnap_gw w[] = {{110, 120, 1, 0}, {120, 130, 1, 0}}; uint64_t want[] = {100, 110, 130, 200}; expect("adjacent writes", w, 2, 100, 200, want, 2, 20); }
    { usnap_gw w[] = {{110, 150, 1, 0}, {120, 130, 1, 0}, {140, 160, 1, 0}}; uint64_t want[] = {100, 110, 160, 200}; expect("nested and overlapping writes", w, 3, 100, 200, want, 2, 50); }
    { usnap_gw w[] = {{0, 150, 1, 0}, {10, 20, 1, 0}, {160, 170, 1, 0}}; uint64_t want[] = {150, 160, 170, 200}; expect("long write from below, short one nested in it", w, 3, 100, 200, want, 2, 60); }
    { usnap_gw w[] = {{100, 101, 1, 0}, {199, 200, 1, 0}}; uint64_t want[] = {101, 199}; expect("one byte at each end", w, 2, 100, 200, want, 1, 2); }
    /* writes with a guessed extent: a range one overlaps is read live whole (no cut); exact writes beside it still cut */
    {
        usnap_gw w[] = {{110, 120, 1, 0}, {300, 304, 1, 1}, {500, 600, 1, 1}, {700, 700, 1, 1}};   /* sorted by lo */
        uint64_t maxlen = 100;
        CHECK(!usnap_gw_inexact_hit(w, 4, usnap_gw_first(w, 4, 100, maxlen), 100, 200), "exact write only: no inexact hit");
        CHECK(usnap_gw_inexact_hit(w, 4, usnap_gw_first(w, 4, 250, maxlen), 250, 400), "inexact write inside the range");
        CHECK(usnap_gw_inexact_hit(w, 4, usnap_gw_first(w, 4, 550, maxlen), 550, 650), "inexact write from below the range");
        CHECK(usnap_gw_inexact_hit(w, 4, usnap_gw_first(w, 4, 450, maxlen), 450, 501), "inexact write at the range end");
        CHECK(!usnap_gw_inexact_hit(w, 4, usnap_gw_first(w, 4, 304, maxlen), 304, 400), "inexact write ending at the range start (adjacent)");
        CHECK(!usnap_gw_inexact_hit(w, 4, usnap_gw_first(w, 4, 200, maxlen), 200, 300), "inexact write starting at the range end (adjacent)");
        CHECK(!usnap_gw_inexact_hit(w, 4, usnap_gw_first(w, 4, 650, maxlen), 650, 750), "empty inexact write");
        CHECK(usnap_gw_inexact_hit(w, 4, usnap_gw_first(w, 4, 100, maxlen), 100, 400), "exact and inexact writes in one range: inexact wins");
    }
    /* random cases against a byte map */
    srand(12345);
    for (int t = 0; t < 20000; t++) {
        enum { R = 256 }; usnap_gw w[12]; int n = rand() % 12; uint8_t map[R]; memset(map, 0, sizeof map);
        uint64_t lo = (uint64_t)(rand() % R), hi = lo + (uint64_t)(rand() % (R - lo + 1));
        for (int i = 0; i < n; i++) { uint64_t a = (uint64_t)(rand() % R), b = a + (uint64_t)(rand() % 40); if (b > R) b = R; w[i] = (usnap_gw){a, b, 1, 0}; for (uint64_t x = a; x < b; x++) map[x] = 1; }
        uint64_t got[64], live; int k = cut(w, n, lo, hi, got, &live);
        uint8_t seen[R]; memset(seen, 0, sizeof seen); uint64_t prev = lo; int ok = 1; uint64_t want_live = 0;
        for (int i = 0; i < k; i++) {
            if (got[2 * i] >= got[2 * i + 1] || got[2 * i] < prev || got[2 * i + 1] > hi) ok = 0;   // non-empty, sorted, disjoint, inside
            if (i && got[2 * i] == got[2 * i - 1]) ok = 0;                                          // never two touching pieces
            for (uint64_t x = got[2 * i]; x < got[2 * i + 1] && x < R; x++) seen[x] = 1;
            prev = got[2 * i + 1];
        }
        for (uint64_t x = lo; x < hi; x++) { if (seen[x] == map[x]) ok = 0; want_live += map[x]; }   // every byte: copied xor written
        if (live != want_live) ok = 0;
        CHECK(ok, "random case %d (range %llu-%llu, %d writes, %d pieces)", t, (unsigned long long)lo, (unsigned long long)hi, n, k);
        if (!ok) break;
    }
    if (!fails) printf("usnap_split: all passed\n");
    return fails != 0;
}
"""


def _compiler():
    for cc in (["xcrun", "clang"], ["clang"], ["cc"]):
        if shutil.which(cc[0]):
            return cc
    return None


class UsnapSplitTest(unittest.TestCase):
    def test_cut_around_gpu_writes(self):
        cc = _compiler()
        if not cc:
            self.skipTest("no C compiler")
        with tempfile.TemporaryDirectory() as d:
            src, exe = os.path.join(d, "t.c"), os.path.join(d, "t")
            with open(src, "w") as f:
                f.write(C_TEST)
            r = subprocess.run(cc + ["-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", NVN, src, "-o", exe],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run([exe], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("all passed", r.stdout)


if __name__ == "__main__":
    unittest.main()
