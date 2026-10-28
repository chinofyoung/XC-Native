"""runtime/time_host.c (nn::time on the host clock): compiles the file with a small C program and runs it.

Covers: every nn::time function main imports has a host version (an import left to the SDK aborts the game, as
ClaimPeriodicBenefitWithUserSystemClock did after choosing a division), the periodic benefit claim (the SDK's own logic,
sdk 0x42f280 / 0x42f740, on the 0x300-byte context the game keeps in its save), snapshots, spans, calendar arithmetic and
the network clock task. Skipped when no C compiler is available."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.normpath(os.path.join(HERE, "..", "runtime"))
WORK = os.path.normpath(os.path.join(HERE, "..", "..", "..", "XCX_build"))

# nn::time imports of main, 1.0.1 and 2.0.0 alike (main-inventory.json / runtime_tables.h symbol_0, undefined symbols).
MAIN_TIME_IMPORTS = [
    "_ZN2nn4time10InitializeEv",
    "_ZN2nn4time13ClockSnapshot29CreateWithStandardSystemClockEPS1_",
    "_ZN2nn4time13ClockSnapshotC1Ev",
    "_ZN2nn4time13IsInitializedEv",
    "_ZN2nn4time14ToCalendarTimeEPNS0_12CalendarTimeEPNS0_22CalendarAdditionalInfoERKNS0_9PosixTimeE",
    "_ZN2nn4time14ToCalendarTimeEPNS0_12CalendarTimeEPNS0_22CalendarAdditionalInfoERKNS0_9PosixTimeERKNS0_12TimeZoneRuleE",
    "_ZN2nn4time20CalculateSpanBetweenEPNS_8TimeSpanERKNS0_13ClockSnapshotES5_",
    "_ZN2nn4time23StandardUserSystemClock14GetCurrentTimeEPNS0_9PosixTimeE",
    "_ZN2nn4time26StandardNetworkSystemClock14GetCurrentTimeEPNS0_9PosixTimeE",
    "_ZN2nn4time26StandardNetworkSystemClock20IsAccuracySufficientEv",
    "_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTask10InitializeENS_2os14EventClearModeE",
    "_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTask14GetFinishEventEv",
    "_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTask9GetResultEv",
    "_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTask9StartTaskEv",
    "_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTaskC1Ev",
    "_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTaskD1Ev",
    "_ZN2nn4time39ClaimPeriodicBenefitWithUserSystemClockEPNS0_27PeriodicBenefitClaimContextERKNS0_13ClockSnapshotERKNS_8TimeSpanES8_PKNS0_25CheckCalendarTimeCallbackE",
    "_ZN2nn4time8FinalizeEv",
    "_ZN2nn4timemiERKNS0_12CalendarTimeERKNS_8TimeSpanE",
]

C_TEST = r"""
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "runtime.h"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)
#define NS 1000000000LL

_Noreturn void runtime_fail(const char *message) { printf("runtime_fail: %s\n", message); fflush(stdout); exit(3); }

/* nn::os system events, as the SDK functions the async task calls (runtime_symbol) */
static void *ev_created, *ev_signalled, *ev_destroyed; static int ev_mode = -1, ev_ipc = -1, ev_destroys;
static uint32_t os_create(void *ev, int mode, bool ipc) { ev_created = ev; ev_mode = mode; ev_ipc = ipc; return 0; }
static void os_signal(void *ev) { ev_signalled = ev; }
static void os_destroy(void *ev) { ev_destroyed = ev; ev_destroys++; }
void *runtime_symbol(const char *name) {
    if (!strcmp(name, "_ZN2nn2os17CreateSystemEventEPNS0_15SystemEventTypeENS0_14EventClearModeEb")) return (void *)os_create;
    if (!strcmp(name, "_ZN2nn2os17SignalSystemEventEPNS0_15SystemEventTypeE")) return (void *)os_signal;
    if (!strcmp(name, "_ZN2nn2os18DestroySystemEventEPNS0_15SystemEventTypeE")) return (void *)os_destroy;
    return NULL;
}

static void *fn(const char *name) { void *p = runtime_time_override(name); if (!p) { printf("missing %s\n", name); exit(2); } return p; }
#define CLAIM "_ZN2nn4time39ClaimPeriodicBenefitWithUserSystemClockEPNS0_27PeriodicBenefitClaimContextERKNS0_13ClockSnapshotERKNS_8TimeSpanES8_PKNS0_25CheckCalendarTimeCallbackE"
#define CTOR "_ZN2nn4time13ClockSnapshotC1Ev"
#define CREATE "_ZN2nn4time13ClockSnapshot29CreateWithStandardSystemClockEPS1_"
#define SPAN "_ZN2nn4time20CalculateSpanBetweenEPNS_8TimeSpanERKNS0_13ClockSnapshotES5_"
#define DIFF "_ZN2nn4time48CalculateStandardUserSystemClockDifferenceByUserERKNS0_13ClockSnapshotES3_"
#define MINUS "_ZN2nn4timemiERKNS0_12CalendarTimeERKNS_8TimeSpanE"
#define TASK "_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTask"
#define ACCURATE "_ZN2nn4time26StandardNetworkSystemClock20IsAccuracySufficientEv"
#define RULE "_ZN2nn4time14ToCalendarTimeEPNS0_12CalendarTimeEPNS0_22CalendarAdditionalInfoERKNS0_9PosixTimeERKNS0_12TimeZoneRuleE"

/* Byte layout as the SDK reads it (sdk 0x42df40..0x42e0d0 accessors, 0x42e110 operator==). */
enum { S_USER = 0x00, S_NETWORK = 0x20, S_USER_TIME = 0x40, S_NETWORK_TIME = 0x48, S_USER_CAL = 0x50, S_NETWORK_CAL = 0x58,
       S_USER_INFO = 0x60, S_NETWORK_INFO = 0x78, S_STEADY = 0x90, S_LOCATION = 0xa8, S_AUTO = 0xcc, S_TYPE = 0xcd, S_SIZE = 0xd0 };
enum { C_LAST = 0x000, C_RECEIVED = 0x0d0, C_PENALTY = 0x1a0, C_FULL = 0x1b8, C_SIZE = 0x300 };
static void put64(uint8_t *p, int64_t v) { memcpy(p, &v, 8); }
static int64_t get64(const uint8_t *p) { int64_t v; memcpy(&v, p, 8); return v; }
static void put32(uint8_t *p, int32_t v) { memcpy(p, &v, 4); }

typedef struct { uint8_t source; int64_t steady, offset; int utc_hours; const char *location; int y, mo, d, h, mi; int automatic, network_valid; } Snap;
static void snap(uint8_t *s, Snap v) {
    memset(s, 0, S_SIZE);
    int64_t now = v.steady + v.offset;
    put64(s + S_USER, v.offset); put64(s + S_USER + 8, v.steady); memset(s + S_USER + 0x10, v.source, 16);
    put64(s + S_NETWORK, v.offset); put64(s + S_NETWORK + 8, v.steady); memset(s + S_NETWORK + 0x10, v.network_valid ? v.source : 0xee, 16);
    put64(s + S_USER_TIME, now); put64(s + S_NETWORK_TIME, now);
    uint8_t cal[8] = {(uint8_t)v.y, (uint8_t)(v.y >> 8), (uint8_t)v.mo, (uint8_t)v.d, (uint8_t)v.h, (uint8_t)v.mi, 0, 0};
    memcpy(s + S_USER_CAL, cal, 8); memcpy(s + S_NETWORK_CAL, cal, 8);
    put32(s + S_USER_INFO + 0x14, v.utc_hours * 3600); put32(s + S_NETWORK_INFO + 0x14, v.utc_hours * 3600);
    put64(s + S_STEADY, v.steady); memset(s + S_STEADY + 8, v.source, 16);
    snprintf((char *)s + S_LOCATION, 0x24, "%s", v.location);
    s[S_AUTO] = (uint8_t)v.automatic; s[S_TYPE] = 1;
}

/* The game's callback (main 0x13ca20c / 0x13ca2f4): same day, same slot of `period` minutes; always receivable. */
typedef struct Callback Callback;
typedef struct { uint32_t (*same)(const Callback *, const uint8_t *, const uint8_t *); uint32_t (*receivable)(const Callback *, const uint8_t *); } Vtable;
struct Callback { const Vtable *vt; int period, same_calls, receivable_calls, receivable_answer; };
static uint32_t cb_same(const Callback *c, const uint8_t *a, const uint8_t *b) {
    ((Callback *)c)->same_calls++;
    if (memcmp(a, b, 4)) return 0x100;                                   /* bit 0 clear: only bit 0 counts */
    return (a[4] * 60 + a[5]) / c->period == (b[4] * 60 + b[5]) / c->period ? 0xff01 : 0;
}
static uint32_t cb_receivable(const Callback *c, const uint8_t *now) { (void)now; ((Callback *)c)->receivable_calls++; return c->receivable_answer; }
static const Vtable vtable = {cb_same, cb_receivable};

typedef unsigned (*ClaimFn)(uint8_t *, const uint8_t *, const int64_t *, const int64_t *, const Callback *);
static uint8_t ctx[C_SIZE + 16];
static Callback cb = {&vtable, 24 * 60, 0, 0, 1};
static int64_t max_penalty = 24 * 60 * 60 * NS, acceptable = 60 * 60 * NS;
static unsigned claim(Snap v) { uint8_t s[S_SIZE]; snap(s, v); unsigned r = ((ClaimFn)fn(CLAIM))(ctx, s, &max_penalty, &acceptable, &cb);
    CHECK(!memcmp(ctx + C_LAST, s, S_SIZE), "every claim keeps the snapshot as the last one"); return r; }
static int received_day(void) { return ctx[C_RECEIVED + S_USER_CAL + 3]; }
static void fresh_context(void) {
    memset(ctx, 0, C_SIZE); memset(ctx + C_SIZE, 0x5a, 16);
    ((void (*)(uint8_t *))fn(CTOR))(ctx + C_LAST); ((void (*)(uint8_t *))fn(CTOR))(ctx + C_RECEIVED);   /* as main 0x13ca0f4 */
}

static void test_claim(void) {
    fresh_context();
    CHECK(ctx[C_LAST + S_TYPE] == 0 && ctx[C_LAST + S_USER_CAL] == 0xb2 && ctx[C_LAST + S_USER_CAL + 1] == 0x07 && ctx[C_LAST + S_USER_CAL + 2] == 1
          && ctx[C_LAST + S_USER_CAL + 3] == 1 && ctx[C_LAST + S_USER_INFO] == 4 && !strcmp((char *)ctx + C_LAST + S_LOCATION, "UTC")
          && !memcmp(ctx + C_LAST + S_USER_INFO + 8, "UTC", 4), "ClockSnapshot() as the SDK's (1970-01-01, Thursday, UTC, type 0)");
    Snap a = {1, 1000, 1700000000, 9, "Asia/Tokyo", 2026, 10, 1, 10, 0, 1, 1};
    CHECK(claim(a) == 0, "first claim of a new context gives the benefit");
    CHECK(received_day() == 1 && ctx[C_RECEIVED + S_TYPE] == 1, "received snapshot kept");
    a.steady += 3600; a.h = 11;
    CHECK(claim(a) == 1, "same day again: not receivable");
    CHECK(received_day() == 1, "received snapshot unchanged");
    a.steady += 23 * 3600; a.d = 2; a.h = 10;
    CHECK(claim(a) == 0 && received_day() == 2, "next day: benefit");
    /* game restart: the host's steady clock source is new in each process; the network clock covers the gap */
    Snap b = a; b.source = 2; b.steady = 50; b.offset = a.steady + a.offset - 50 + 7200; b.h = 12;
    CHECK(claim(b) == 1, "restart on the same day: not receivable, no penalty");
    CHECK(get64(ctx + C_PENALTY + 8) == 0 && get64(ctx + C_PENALTY + 16) == 0, "restart with valid network clocks clears the penalty");
    b.steady += 86400; b.d = 3;
    CHECK(claim(b) == 0 && received_day() == 3, "restart, next day: benefit");
    /* the Mac's time zone moves one hour west: the local clock went back an hour, a one-hour penalty */
    b.steady += 86400; b.d = 4; b.utc_hours = 8; b.location = "Asia/Shanghai";
    CHECK(claim(b) == 2, "clock moved back by a time zone change: penalty");
    CHECK(get64(ctx + C_PENALTY) == b.steady + 3600 && ctx[C_PENALTY + 8] == 2 && ctx[C_FULL] == 0, "penalty ends one hour later (%lld)", (long long)get64(ctx + C_PENALTY));
    b.steady += 1800;
    CHECK(claim(b) == 2, "still in the penalty");
    b.steady += 1801;
    CHECK(claim(b) == 0 && received_day() == 4, "penalty over: benefit");
    CHECK(get64(ctx + C_PENALTY + 8) == 0, "penalty cleared");
    /* moving east within the acceptable change: nothing */
    b.steady += 60; b.utc_hours = 9; b.location = "Asia/Tokyo";
    CHECK(claim(b) == 1 && get64(ctx + C_PENALTY + 8) == 0, "forward one hour (acceptable): no penalty, same day");
    /* moving east beyond it: the full penalty; afterwards the same-period check is skipped once */
    b.steady += 60; b.utc_hours = 12; b.location = "Pacific/Fiji";
    max_penalty = 600 * NS;
    CHECK(claim(b) == 2 && ctx[C_FULL] == 1 && get64(ctx + C_PENALTY) == b.steady + 600, "forward three hours: full penalty");
    b.steady += 601;
    int calls = cb.same_calls;
    CHECK(claim(b) == 0 && ctx[C_FULL] == 0 && cb.same_calls == calls, "after a full penalty the benefit comes without the same-day check");
    CHECK(claim(b) == 1, "then the same day again: not receivable");
    /* the callback says no */
    b.steady += 86400; b.d = 5; cb.receivable_answer = 0x10;
    CHECK(claim(b) == 1 && received_day() == 4, "callback refuses: not receivable");
    cb.receivable_answer = 1;
    CHECK(claim(b) == 0 && received_day() == 5, "callback accepts: benefit");
    /* steady clock reset without a valid network clock: penalty of the maximum less the time since the last benefit */
    Snap c = b; c.source = 3; c.steady = 10; c.offset = b.steady + b.offset - 10 + 100; c.network_valid = 0;
    CHECK(claim(c) == 2 && get64(ctx + C_PENALTY) == 10 + 500 && ctx[C_PENALTY + 8] == 3 && ctx[C_FULL] == 1,
          "steady clock reset: penalty of 600 s less 100 s elapsed (%lld)", (long long)get64(ctx + C_PENALTY));
    CHECK(!memcmp(ctx + C_SIZE, "\x5a\x5a\x5a\x5a\x5a\x5a\x5a\x5a\x5a\x5a\x5a\x5a\x5a\x5a\x5a\x5a", 16), "nothing written past the 0x300-byte context");
}

static void test_snapshots(void) {
    uint8_t a[S_SIZE], b[S_SIZE];
    CHECK(((unsigned (*)(uint8_t *))fn(CREATE))(a) == 0, "CreateWithStandardSystemClock");
    CHECK(a[S_TYPE] == 1, "snapshot type 1, as the SDK asks the service for (sdk 0x42de80)");
    CHECK(a[S_AUTO] == 1 && !memcmp(a + S_NETWORK + 0x10, a + S_STEADY + 8, 16), "automatic correction on, network clock valid");
    CHECK(a[S_LOCATION] != 0, "location name");
    typedef bool (*SpanFn)(int64_t *, const uint8_t *, const uint8_t *);
    int64_t span = -1;
    Snap x = {7, 100, 1700000000, 0, "UTC", 2026, 1, 1, 0, 0, 1, 1}, y = x; y.steady = 160;
    snap(a, x); snap(b, y);
    CHECK(((SpanFn)fn(SPAN))(&span, a, b) == true && span == 60 * NS, "span on the same steady clock: true, 60 s (%lld)", (long long)span);
    y.source = 8; y.steady = 5; y.offset = 1700000000 + 100 + 3600 - 5; snap(b, y); span = -1;
    CHECK(((SpanFn)fn(SPAN))(&span, a, b) == true && span == 3600 * NS, "span across a restart: network time (%lld)", (long long)span);
    put64(b + S_NETWORK_TIME, 0); span = -1;
    CHECK(((SpanFn)fn(SPAN))(&span, a, b) == false && span == -1, "no common clock: false, output untouched");
    typedef int64_t (*DiffFn)(const uint8_t *, const uint8_t *);
    y = x; y.offset += 300; snap(b, y);
    CHECK(((DiffFn)fn(DIFF))(a, b) == 0, "automatic correction on both: no change by the user");
    b[S_AUTO] = 0;
    CHECK(((DiffFn)fn(DIFF))(a, b) == 300 * NS, "manual clock: the offset change");
}

static void test_calendar(void) {
    typedef uint64_t (*MinusFn)(const uint8_t *, const int64_t *);
    uint8_t c[8] = {0xea, 0x07, 1, 1, 0, 30, 0, 0}; int64_t hour = 3600 * NS, back = -90 * 60 * NS;
    uint64_t r = ((MinusFn)fn(MINUS))(c, &hour); uint8_t o[8]; memcpy(o, &r, 8);
    CHECK(o[0] == 0xe9 && o[1] == 0x07 && o[2] == 12 && o[3] == 31 && o[4] == 23 && o[5] == 30 && o[6] == 0, "2026-01-01 00:30 - 1 h = 2025-12-31 23:30");
    r = ((MinusFn)fn(MINUS))(c, &back); memcpy(o, &r, 8);
    CHECK(o[0] == 0xea && o[2] == 1 && o[3] == 1 && o[4] == 2 && o[5] == 0, "minus a negative span adds");
}

static void test_network(void) {
    CHECK(((uint8_t (*)(void))fn(ACCURATE))() == 1, "network clock (the host clock) is accurate");
    uint8_t t[0x98 + 8]; memset(t, 0xcc, sizeof t);
    ((void (*)(uint8_t *))fn(TASK "C1Ev"))(t);
    int zero = 1; for (int i = 0; i <= 0x90; i++) zero &= t[i] == 0;
    CHECK(zero && t[0x91] == 0xcc, "constructor clears 0x91 bytes, as the SDK's");
    ((void (*)(uint8_t *))fn(TASK "D1Ev"))(t);
    CHECK(ev_destroys == 0, "destroying an uninitialised task touches no event");
    ((void (*)(uint8_t *, int))fn(TASK "10InitializeENS_2os14EventClearModeE"))(t, 0);
    CHECK(ev_created == t + 8 && ev_mode == 0 && ev_ipc == 0 && t[0x90] == 1, "Initialize makes the finish event at +8");
    CHECK(((unsigned (*)(uint8_t *))fn(TASK "9StartTaskEv"))(t) == 0 && ev_signalled == t + 8, "StartTask accepted, finished at once");
    CHECK(((void *(*)(uint8_t *))fn(TASK "14GetFinishEventEv"))(t) == t + 8, "GetFinishEvent");
    unsigned r = ((unsigned (*)(uint8_t *))fn(TASK "9GetResultEv"))(t);
    CHECK(r != 0 && (r & 0x1ff) == 110, "GetResult: network unavailable (%#x)", r);
    ((void (*)(uint8_t *))fn(TASK "D1Ev"))(t);
    ((void (*)(uint8_t *))fn(TASK "D1Ev"))(t);
    CHECK(ev_destroyed == t + 8 && ev_destroys == 1 && t[0x90] == 0, "destructor destroys the event once");
}

int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "cover")) {
        int missing = 0; for (int i = 2; i < argc; i++) if (!runtime_time_override(argv[i])) { printf("missing %s\n", argv[i]); missing++; }
        return missing != 0;
    }
    if (argc > 1 && !strcmp(argv[1], "rule")) {
        uint8_t cal[8], info[0x18], rule[16] = {0}; int64_t t = 0;
        ((unsigned (*)(uint8_t *, uint8_t *, const int64_t *, const uint8_t *))fn(RULE))(cal, info, &t, rule);
        return 0;
    }
    test_claim(); test_snapshots(); test_calendar(); test_network();
    printf(fails ? "%d failures\n" : "ok\n", fails);
    return fails != 0;
}
"""


def main_time_imports(version):
    """Undefined nn::time symbols of main in the work folder's generated tables, or None when they are not there."""
    path = os.path.join(WORK, "build", version, "runtime_tables.h")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    start = text.index("static const Symbol symbol_0[] = {")
    table = text[start:text.index("};", start)]
    return sorted({m.group(1) for m in re.finditer(r'\{"(_ZN2nn4time[^"]*)",\d+ULL,\d+ULL,0,', table)})


class TimeHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc") or shutil.which("clang")
        if not cc:
            raise unittest.SkipTest("no C compiler")
        cls.tmp = tempfile.TemporaryDirectory()
        src, cls.exe = os.path.join(cls.tmp.name, "t.c"), os.path.join(cls.tmp.name, "t")
        with open(src, "w") as f:
            f.write(C_TEST)
        subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-I", RUNTIME,
                        src, os.path.join(RUNTIME, "time_host.c"), "-o", cls.exe], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_exe(self, *args):
        return subprocess.run([self.exe, *args], capture_output=True, text=True)

    def test_behaviour(self):
        r = self.run_exe()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_every_main_import_has_a_host_version(self):
        r = self.run_exe("cover", *MAIN_TIME_IMPORTS)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_imports_of_the_work_folder(self):
        """The list above against the images themselves (both game versions), when the work folder has them."""
        seen = 0
        for version in ("v101", "v200"):
            names = main_time_imports(version)
            if names is None:
                continue
            seen += 1
            self.assertEqual(names, sorted(MAIN_TIME_IMPORTS), version)
            r = self.run_exe("cover", *names)
            self.assertEqual(r.returncode, 0, version + ": " + r.stdout + r.stderr)
        if not seen:
            self.skipTest("no generated tables in " + WORK)

    def test_time_zone_rule_fails_loudly(self):
        r = self.run_exe("rule")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("TimeZoneRule", r.stdout)


if __name__ == "__main__":
    unittest.main()
