#ifndef USNAP_SPLIT_H
#define USNAP_SPLIT_H
/* uniform 提交时快照：把一段合并后的 uniform 区间按「GPU 尚未写完的区间」切开，只有 GPU 写的字节读内存，其余照常拷贝。
   纯 C、无分配，nvn_mtl.m 的 usnap_take 每次提交对几百段调用；games/xcx/tests/test_usnap_split.py 编译并测试它。
   Uniform snapshot at the submit call: cut one merged uniform range around the ranges GPU work not finished yet writes, so
   only the GPU-written bytes are read from memory and the rest is still copied. Pure C, no allocation: usnap_take in
   nvn_mtl.m runs it on a few hundred ranges per submission; games/xcx/tests/test_usnap_split.py compiles and tests it. */
#include <stdint.h>

/* a GPU write [lo, hi) of the submission with this fence; inexact: the extent is a guess (a storage-buffer pointer read from
   a uniform block, a binding without a size), the GPU may write past hi, so a range it overlaps is not cut but read live whole */
typedef struct { uint64_t lo, hi, fence; uint32_t inexact; } usnap_gw;

/* First index whose write can reach lo: w sorted by lo, maxlen = longest write in w (so any write overlapping [lo, ...)
   starts at or after lo - maxlen). */
static inline int usnap_gw_first(const usnap_gw *w, int n, uint64_t lo, uint64_t maxlen) {
    uint64_t from = lo > maxlen ? lo - maxlen : 0; int a = 0, b = n;
    while (a < b) { int m = (a + b) >> 1; if (w[m].lo < from) a = m + 1; else b = m; }
    return a;
}

/* 1 when a write of w[first..n) with a guessed extent overlaps [lo, hi): the caller reads the whole range live (no cut). */
static inline int usnap_gw_inexact_hit(const usnap_gw *w, int n, int first, uint64_t lo, uint64_t hi) {
    for (int j = first; j < n && w[j].lo < hi; j++) if (w[j].inexact && w[j].hi > lo && w[j].hi > w[j].lo) return 1;
    return 0;
}

/* Iterator over the pieces of [lo, hi) no write of w[first..n) touches, in address order. The writes are sorted by lo and
   may overlap, nest or abut each other (cur = end of everything covered so far, so overlaps and adjacency need no merge).
   live = bytes of [lo, hi) covered by writes, final once usnap_cut_next returned 0. */
typedef struct { const usnap_gw *w; int j, n; uint64_t cur, hi, live; } usnap_cut;
static inline void usnap_cut_init(usnap_cut *c, const usnap_gw *w, int n, int first, uint64_t lo, uint64_t hi) {
    c->w = w; c->j = first; c->n = n; c->cur = lo; c->hi = hi; c->live = 0;
}
static inline int usnap_cut_next(usnap_cut *c, uint64_t *plo, uint64_t *phi) {
    while (c->cur < c->hi) {
        if (c->j < c->n && c->w[c->j].lo < c->hi) {
            const usnap_gw *g = &c->w[c->j++];
            if (g->hi <= c->cur || g->hi <= g->lo) continue;   // wholly below what is already covered / cut, or empty
            uint64_t e = g->hi < c->hi ? g->hi : c->hi;
            if (g->lo > c->cur) { *plo = c->cur; *phi = g->lo; c->live += e - g->lo; c->cur = g->hi; return 1; }
            c->live += e - c->cur; c->cur = g->hi; continue;
        }
        *plo = c->cur; *phi = c->hi; c->cur = c->hi; return 1;
    }
    return 0;
}
#endif
