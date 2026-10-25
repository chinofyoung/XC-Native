/* TOTK (2026-10-25)：取交换链贴图时同步对象挂的栅栏（hle_nvn.c nvnWindowAcquireTexture，TOTK_ACQ_SYNC）。每次出图记下当时最新的
   提交（栅栏值或翻译线程的提交序号）和出的是哪张；取图时按模式挑一个：把它从屏幕上换下来的下一次出图那一帧（缺省 next，真机
   语义）、或这张贴图上一次出图那一帧（tex，试验）。没有记录时（新窗口、重新初始化、别的窗口）让调用方用最新的提交。纯函数，
   单测 tests/test_acq_fence.py。
   TOTK (2026-10-25): the fence an acquired swapchain image's sync waits for (hle_nvn.c nvnWindowAcquireTexture,
   TOTK_ACQ_SYNC). Every present records the newest submission at that moment (a Metal fence, or the translation thread's
   submit token) and which image it showed; the acquire picks one by mode: the frame of the next present, the one that
   replaced it on screen (next, the default: what real NVN signals, the display releasing the image), or the frame of this
   image's last present (tex, experimental). Without a record (a new window, one initialised again, another window) the
   caller takes the newest submission: earlier frames may still be in flight. Values recorded are submissions already
   made, so a wait on them always ends. Pure functions; tests/test_acq_fence.py. The caller locks. */
#ifndef ACQ_FENCE_H
#define ACQ_FENCE_H
#include <stdint.h>
#include <string.h>

#define ACQ_RING 16   /* presents remembered; older ones are replaced by the oldest kept (later: waits longer, never less) */
enum { ACQ_NOW, ACQ_OLD, ACQ_TEX, ACQ_NEXT };   /* TOTK_ACQ_SYNC=now / old / tex / next (the default) */
typedef struct { const void *win; uint64_t seq, last[4], fence[ACQ_RING]; uint8_t tok[ACQ_RING]; } acq_track;

/* A window initialised again (same storage, new swapchain): nothing it presented before counts. */
static inline void acq_reset(acq_track *a, const void *win) { memset(a, 0, sizeof *a); a->win = win; }
/* A present of image idx (out of range: still a present, it replaces the image on screen) after the submission fence. */
static inline void acq_note_present(acq_track *a, const void *win, int idx, uint64_t fence, int tok) {
    if (a->win != win) acq_reset(a, win);
    uint64_t s = ++a->seq; a->fence[s % ACQ_RING] = fence; a->tok[s % ACQ_RING] = (uint8_t)(tok != 0);
    if (idx >= 0 && idx < 4) a->last[idx] = s;
}
/* 1: wait for *fence (*tok: a translation-thread token); -1: the caller uses the newest submission: no record of this
   image (never presented since the tracker's window was set or reset, another window, an index out of range: earlier
   frames may still be in flight), or it is the newest present, still on screen (next mode). Never "no wait". */
static inline int acq_pick(const acq_track *a, const void *win, int idx, int mode, uint64_t *fence, int *tok) {
    if (a->win != win || idx < 0 || idx >= 4 || !a->last[idx]) return -1;
    uint64_t s = a->last[idx] + (mode == ACQ_NEXT);
    if (s > a->seq) return -1;
    if (a->seq - s >= ACQ_RING) s = a->seq - ACQ_RING + 1;
    *fence = a->fence[s % ACQ_RING]; *tok = a->tok[s % ACQ_RING]; return 1;
}
#endif
