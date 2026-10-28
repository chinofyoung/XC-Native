/* nn::time for the functions main imports, backed by the host clock and time zone.
   User and network system clocks both follow the (NTP-synchronised) host wall clock; the steady clock
   counts seconds of host continuous time with one source id per process. ClockSnapshot uses the public
   0xD0-byte layout because game code may read its fields through inline accessors.
   Every nn::time function main imports must be here (tests/test_time_host.py checks both game versions): the SDK's own
   versions ask the time service through a global the host never sets, and abort (sdk 0x62f290) when it is null. */
#include "runtime.h"
#include <mach/mach_time.h>
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef struct { int64_t value; uint8_t source[16]; } SteadyClockTimePoint;
typedef struct { int64_t offset; SteadyClockTimePoint point; } SystemClockContext;
typedef struct { int16_t year; int8_t month, day, hour, minute, second, pad; } CalendarTime;
typedef struct { int32_t day_of_week, day_of_year; char name[8]; uint8_t dst, pad[3]; int32_t utc_offset; } CalendarAdditionalInfo;
typedef struct {
    SystemClockContext user, network; int64_t user_time, network_time;
    CalendarTime user_calendar, network_calendar; CalendarAdditionalInfo user_info, network_info;
    SteadyClockTimePoint steady; char location[0x24]; uint8_t automatic_correction, type, pad[2];
} ClockSnapshot;
_Static_assert(sizeof(SteadyClockTimePoint) == 0x18 && sizeof(CalendarTime) == 8 && sizeof(CalendarAdditionalInfo) == 0x18, "nn::time types");
_Static_assert(sizeof(ClockSnapshot) == 0xd0, "nn::time::ClockSnapshot");

/* PeriodicBenefitClaimContext (0x300 bytes): main keeps it in its save (main 0x13ca0d4: zeroed, both snapshots constructed).
   Layout as the SDK's claim reads it (sdk 0x42f280, 0x42f740, HasPenaltyInfo 0x42f230). */
typedef struct {
    ClockSnapshot last;                 /* 0x000 the previous claim's snapshot (type 0: the context is new) */
    ClockSnapshot received;             /* 0x0d0 the snapshot of the last claim that gave the benefit */
    SteadyClockTimePoint penalty_end;   /* 0x1a0 no benefit before this steady time; source 0: no penalty */
    uint8_t full_penalty;               /* 0x1b8 the last penalty was the full length: the next benefit skips the same-period check */
    uint8_t reserved[0x147];
} PeriodicBenefitClaimContext;
_Static_assert(sizeof(PeriodicBenefitClaimContext) == 0x300, "nn::time::PeriodicBenefitClaimContext");
/* nn::time::CheckCalendarTimeCallback: a game object; main's (vtable main 0x1d10370) compares the day and a slot of N
   minutes, and always answers receivable. Only bit 0 of the answers counts, as in the SDK (tbnz / eor #1). */
typedef struct CheckCalendarTimeCallback CheckCalendarTimeCallback;
typedef struct {
    uint32_t (*same_period)(const CheckCalendarTimeCallback *self, const CalendarTime *received, const CalendarTime *now);
    uint32_t (*receivable)(const CheckCalendarTimeCallback *self, const CalendarTime *now);
} CheckCalendarTimeCallbackVtable;
struct CheckCalendarTimeCallback { const CheckCalendarTimeCallbackVtable *vt; };
enum { CLAIM_RECEIVED = 0, CLAIM_NOT_RECEIVABLE = 1, CLAIM_PENALTY = 2 };   /* main 0x13ca180: 3 and above count as 1 */

#define R_INVALID 0x74u          /* time module 116: invalid argument family */
#define NS 1000000000LL
static uint8_t source_id[16];
static int initialized;
static pthread_once_t once = PTHREAD_ONCE_INIT;
static void make_source(void) { arc4random_buf(source_id, sizeof source_id); }

static int64_t steady_seconds(void) {
    mach_timebase_info_data_t tb; mach_timebase_info(&tb);
    return (int64_t)((__uint128_t)mach_continuous_time() * tb.numer / tb.denom / 1000000000u);
}
static SteadyClockTimePoint steady_now(void) { pthread_once(&once, make_source); SteadyClockTimePoint p = {steady_seconds(), {0}}; memcpy(p.source, source_id, 16); return p; }
static int64_t time_offset(void) {
    static long off = -1; if (off < 0) { const char *e = getenv("TOTK_TIME_OFFSET"); off = e ? atol(e) : 0; if (off < 0) off = 0; }   /* diagnostic: shift the clock the game sees (seconds) */
    return off;
}
static int64_t posix_now(void) { return (int64_t)time(NULL) + time_offset(); }

static unsigned initialize(void) { initialized = 1; pthread_once(&once, make_source); return 0; }
static unsigned finalize(void) { initialized = 0; return 0; }
static unsigned char is_initialized(void) { return (unsigned char)initialized; }
static unsigned user_time(int64_t *out) { if (!out) return R_INVALID; *out = posix_now(); return 0; }
/* The C library's realtime clock (Xenoblade Chronicles X: std::chrono::system_clock::now): the SDK's startup points
   clock_gettime(CLOCK_REALTIME) at this function, which would otherwise ask the time service the host replaces. */
static unsigned user_timespec(struct timespec *out) {
    if (!out) return R_INVALID; struct timespec t; clock_gettime(CLOCK_REALTIME, &t);
    out->tv_sec = t.tv_sec + time_offset(); out->tv_nsec = t.tv_nsec; return 0;
}
/* StandardSteadyClock::now() returns the chrono-style time_point: the int64 seconds value only, 0 without a source
   (sdk+0x3d1d88 returns it in x0; returning the 0x18-byte struct made the host write through the caller's stale x8). */
static int64_t steady_clock_now(void) { return steady_now().value; }

static void fill_calendar(CalendarTime *c, CalendarAdditionalInfo *info, int64_t posix, int local) {
    time_t t = (time_t)posix; struct tm tm;
    if (!(local ? localtime_r(&t, &tm) : gmtime_r(&t, &tm))) runtime_fail("calendar conversion");
    *c = (CalendarTime){(int16_t)(tm.tm_year + 1900), (int8_t)(tm.tm_mon + 1), (int8_t)tm.tm_mday, (int8_t)tm.tm_hour, (int8_t)tm.tm_min, (int8_t)tm.tm_sec, 0};
    if (info) {
        memset(info, 0, sizeof *info);
        info->day_of_week = tm.tm_wday; info->day_of_year = tm.tm_yday;
        snprintf(info->name, sizeof info->name, "%s", local && tm.tm_zone ? tm.tm_zone : "UTC");
        info->dst = local && tm.tm_isdst > 0; info->utc_offset = local ? (int32_t)tm.tm_gmtoff : 0;
    }
}
static unsigned to_calendar(CalendarTime *c, CalendarAdditionalInfo *info, const int64_t *posix) {
    if (!c || !posix) return R_INVALID; fill_calendar(c, info, *posix, 1); return 0;
}
static CalendarTime to_calendar_utc(const int64_t *posix) { CalendarTime c; fill_calendar(&c, NULL, posix ? *posix : 0, 0); return c; }
static int64_t to_posix_utc(const CalendarTime *c) {
    struct tm tm = {0}; tm.tm_year = c->year - 1900; tm.tm_mon = c->month - 1; tm.tm_mday = c->day; tm.tm_hour = c->hour; tm.tm_min = c->minute; tm.tm_sec = c->second;
    return (int64_t)timegm(&tm);
}

static void location_name(char out[0x24]) {
    memset(out, 0, 0x24); char link[512]; ssize_t n = readlink("/etc/localtime", link, sizeof link - 1);
    if (n > 0) { link[n] = 0; const char *z = strstr(link, "zoneinfo/"); snprintf(out, 0x24, "%s", z ? z + 9 : "UTC"); }
    else snprintf(out, 0x24, "UTC");
}
/* ClockSnapshot(): the SDK's constructor (sdk 0x42dd9c): 1970-01-01 00:00 on both calendars (a Thursday), "UTC", type 0. */
static void snapshot_init(ClockSnapshot *s) {
    memset(s, 0, sizeof *s);
    s->user_calendar = s->network_calendar = (CalendarTime){1970, 1, 1, 0, 0, 0, 0};
    s->user_info.day_of_week = s->network_info.day_of_week = 4;
    memcpy(s->user_info.name, "UTC", 3); memcpy(s->network_info.name, "UTC", 3); memcpy(s->location, "UTC", 3);
}
static unsigned snapshot_create(ClockSnapshot *s) {
    if (!s) return R_INVALID;
    SteadyClockTimePoint steady = steady_now(); int64_t now = posix_now();
    memset(s, 0, sizeof *s);
    s->user = (SystemClockContext){now - steady.value, steady}; s->network = s->user;
    s->user_time = now; s->network_time = now;
    fill_calendar(&s->user_calendar, &s->user_info, now, 1); fill_calendar(&s->network_calendar, &s->network_info, now, 1);
    s->steady = steady; location_name(s->location); s->automatic_correction = 1;
    s->type = 1;   /* the SDK asks the service for a snapshot of type 1 (sdk 0x42de80); type 0 marks a constructed, empty one */
    return 0;
}
static int same_source(const uint8_t a[16], const uint8_t b[16]) { return !memcmp(a, b, 16); }
/* CalculateSpanBetween returns bool (sdk 0x42d5c8 cset eq; main 0x13cc080 tests bit 0): the steady clock when both
   snapshots share its source, else the network clock when both have a network time (a game restart here, since the
   host's steady clock source is new in each process). */
static bool span_between(int64_t *out_ns, const ClockSnapshot *a, const ClockSnapshot *b) {
    if (!out_ns || !a || !b) return false;
    if (same_source(a->steady.source, b->steady.source)) { *out_ns = (b->steady.value - a->steady.value) * NS; return true; }
    if (!a->network_time || !b->network_time) return false;
    *out_ns = (b->network_time - a->network_time) * NS; return true;
}
/* Change of the user clock offset between snapshots made by the user, as a TimeSpan. With automatic correction on in
   both, the user cannot have set the clock: 0 (the time service's rule; the host's snapshots always have it on). */
static int64_t user_difference(const ClockSnapshot *a, const ClockSnapshot *b) {
    if (!same_source(a->user.point.source, b->user.point.source) || (a->automatic_correction && b->automatic_correction)) return 0;
    return (b->user.offset - a->user.offset) * NS;
}
/* operator-(CalendarTime, TimeSpan) (sdk 0x42db50): in UTC, whole seconds (the span truncated toward zero). */
static CalendarTime calendar_minus(const CalendarTime *c, const int64_t *span) {
    if (!c || !span) runtime_fail("nn::time::operator-(CalendarTime, TimeSpan) argument");
    int64_t posix = to_posix_utc(c) - *span / NS; return to_calendar_utc(&posix);
}
/* ToCalendarTime with a TimeZoneRule: the host cannot read the SDK's rule blob, and main never loads a rule (it does not
   import LoadTimeZoneRule; its only caller, main 0xbe8ce0, is reached with a null rule and takes the other overload). */
static unsigned to_calendar_rule(CalendarTime *c, CalendarAdditionalInfo *info, const int64_t *posix, const void *rule) {
    (void)c; (void)info; (void)posix; (void)rule;
    runtime_fail("nn::time::ToCalendarTime with a TimeZoneRule: not on the host (main loads no TimeZoneRule)");
}
/* StandardNetworkSystemClock::IsAccuracySufficient: the network clock here is the NTP-synchronised host clock, the same
   one its GetCurrentTime and now() answer with (main 0x4e80d4 then reads that time). */
static uint8_t network_accurate(void) { return 1; }

/* ---------- ClaimPeriodicBenefitWithUserSystemClock: the SDK's logic (sdk 0x42f280 and 0x42f740), with the host clocks ----------
   max_penalty: the longest penalty and the benefit period's guard after a steady clock reset; acceptable: how far the
   user's local clock may move forward without a penalty. main passes N minutes and M seconds (main 0x13ca114). */
static void clear_penalty(PeriodicBenefitClaimContext *c) { memset(&c->penalty_end, 0, sizeof c->penalty_end); }
static int network_valid(const ClockSnapshot *s) { return s->automatic_correction && same_source(s->network.point.source, s->steady.source); }
static int same_location(const ClockSnapshot *a, const ClockSnapshot *b) { return !strncmp(a->location, b->location, sizeof a->location); }
static SteadyClockTimePoint later(SteadyClockTimePoint a, SteadyClockTimePoint b) { return a.value > b.value ? a : b; }
/* The time service's "automatic correction setting changed at" (no host change: none in this boot) and "device location
   changed at" (the host only sees the change in this snapshot). A point of another source is ignored by the claim. */
static SteadyClockTimePoint automatic_correction_updated(void) { return (SteadyClockTimePoint){0}; }
static SteadyClockTimePoint location_updated(const ClockSnapshot *now) { return now->steady; }

/* Same steady clock as the previous claim: a penalty when the local clock moved by the user (or the time zone) since then. */
static void penalty_for_clock_change(PeriodicBenefitClaimContext *c, const ClockSnapshot *now, int64_t max_penalty, int64_t acceptable) {
    int64_t change = user_difference(&c->last, now), penalty;
    if (!same_location(&c->last, now)) change += ((int64_t)now->user_info.utc_offset - c->last.user_info.utc_offset) * NS;
    if (!change) return;
    if (change >= 1) { if (change <= acceptable) return; penalty = max_penalty; }
    else { int64_t back = (int64_t)(((uint64_t)0 - (uint64_t)change) / NS * NS); penalty = back < max_penalty ? back : max_penalty; }
    if (!penalty) return;
    if (penalty == max_penalty) c->full_penalty = 1;
    /* the penalty runs from when the change happened, as best known */
    int network = network_valid(now), have = !network; SteadyClockTimePoint base = {0};
    if (!network) base = now->user.point;
    if ((c->last.automatic_correction & 1) != (now->automatic_correction & 1)) {
        SteadyClockTimePoint t = automatic_correction_updated();
        if (same_source(t.source, now->steady.source)) { base = network ? t : later(base, t); have = 1; }
    }
    if (!same_location(&c->last, now)) {
        SteadyClockTimePoint t = location_updated(now);
        if (same_source(t.source, now->steady.source)) { base = have ? later(base, t) : t; have = 1; }
    }
    if (!have) base = now->user.point;
    SteadyClockTimePoint end = base; end.value += penalty / NS;
    if (!same_source(c->penalty_end.source, end.source) || c->penalty_end.value <= end.value) c->penalty_end = end;   /* keep a later one */
}
static unsigned claim_result(PeriodicBenefitClaimContext *c, const ClockSnapshot *now, const CheckCalendarTimeCallback *cb) {
    static const uint8_t no_source[16];
    if (c->last.type && !same_source(c->penalty_end.source, no_source)) {
        int64_t remaining;
        if (same_source(now->steady.source, c->penalty_end.source)
            && !__builtin_sub_overflow(c->penalty_end.value, now->steady.value, &remaining) && remaining > 0) {
            c->last = *now; return CLAIM_PENALTY;
        }
        clear_penalty(c);
    }
    int known = c->last.type != 0;
    CalendarTime today = now->user_calendar;
    int receivable = cb->vt->receivable(cb, &today) & 1;
    if (known && !c->full_penalty) {
        CalendarTime received = c->received.user_calendar, current = now->user_calendar;
        if (cb->vt->same_period(cb, &received, &current) & 1) return CLAIM_NOT_RECEIVABLE;
    }
    if (!receivable) return CLAIM_NOT_RECEIVABLE;
    c->last = *now; c->received = *now; c->full_penalty = 0;
    return CLAIM_RECEIVED;
}
static unsigned claim_periodic_benefit(PeriodicBenefitClaimContext *c, const ClockSnapshot *now, const int64_t *max_penalty,
                                       const int64_t *acceptable, const CheckCalendarTimeCallback *cb) {
    if (!c || !now || !max_penalty || !acceptable || !cb || !cb->vt) runtime_fail("ClaimPeriodicBenefitWithUserSystemClock argument");
    if (!c->last.type) {                                        /* a new context */
        snapshot_init(&c->received);
        memset(&c->penalty_end, 0, sizeof *c - offsetof(PeriodicBenefitClaimContext, penalty_end));
    } else if (!same_source(c->last.steady.source, now->steady.source)) {
        /* the steady clock changed (here: every game start): no penalty if both network clocks can be trusted */
        if ((network_valid(&c->last) && network_valid(now)) || !c->received.type) clear_penalty(c);
        else {
            int64_t penalty = *max_penalty, elapsed = 0;
            if (span_between(&elapsed, &c->received, now) && elapsed >= 0) penalty -= elapsed;
            c->penalty_end = now->steady; c->penalty_end.value += penalty / NS; c->full_penalty = 1;
        }
    } else penalty_for_clock_change(c, now, *max_penalty, *acceptable);
    unsigned result = claim_result(c, now, cb);
    c->last = *now;
    return result;
}

/* ---------- AsyncEnsureNetworkClockAvailabilityTask (main 0xc945f0, the online layer's network clock check) ----------
   The SDK's object: its finish event at +8, an "initialised" byte at +0x90 (sdk 0x42d824, 0x434b98). Offline, the task is
   accepted and finishes at once with "network unavailable" (the nifm result runtime/system_services.c answers with);
   main then reports its own error ("Failed AsyncEnsureNetworkClockAvailabilityTask. GetResult()") and stays offline. */
#define TASK_EVENT 0x08
#define TASK_INITIALIZED 0x90
#define NETWORK_UNAVAILABLE (110u | 300u << 9)
static void *sdk_function(const char *name) { void *f = runtime_symbol(name); if (!f) runtime_fail(name); return f; }
static uint8_t *task_object(void *task) { if (!task) runtime_fail("AsyncEnsureNetworkClockAvailabilityTask object"); return task; }
static void task_construct(void *task) { memset(task_object(task), 0, TASK_INITIALIZED + 1); }
static void task_destroy(void *task) {
    uint8_t *t = task_object(task); if (!t[TASK_INITIALIZED]) return;
    ((void (*)(void *))sdk_function("_ZN2nn2os18DestroySystemEventEPNS0_15SystemEventTypeE"))(t + TASK_EVENT);
    t[TASK_INITIALIZED] = 0;
}
static void task_initialize(void *task, int clear_mode) {
    uint8_t *t = task_object(task); if (t[TASK_INITIALIZED]) return;
    unsigned r = ((unsigned (*)(void *, int, bool))sdk_function("_ZN2nn2os17CreateSystemEventEPNS0_15SystemEventTypeENS0_14EventClearModeEb"))(t + TASK_EVENT, clear_mode, false);
    if (r) runtime_fail("AsyncEnsureNetworkClockAvailabilityTask event");
    t[TASK_INITIALIZED] = 1;
}
static unsigned task_start(void *task) {
    uint8_t *t = task_object(task); if (!t[TASK_INITIALIZED]) runtime_fail("AsyncEnsureNetworkClockAvailabilityTask::StartTask before Initialize");
    ((void (*)(void *))sdk_function("_ZN2nn2os17SignalSystemEventEPNS0_15SystemEventTypeE"))(t + TASK_EVENT);
    return 0;
}
static unsigned task_result(void *task) { task_object(task); return NETWORK_UNAVAILABLE; }
static void *task_finish_event(void *task) { return task_object(task) + TASK_EVENT; }

void *runtime_time_override(const char *name) {
    static const struct { const char *name; void *fn; } map[] = {
        {"_ZN2nn4time10InitializeEv", initialize}, {"_ZN2nn4time8FinalizeEv", finalize}, {"_ZN2nn4time13IsInitializedEv", is_initialized},
        {"_ZN2nn4time23StandardUserSystemClock14GetCurrentTimeEPNS0_9PosixTimeE", user_time},
        {"_ZN2nn4time26StandardNetworkSystemClock14GetCurrentTimeEPNS0_9PosixTimeE", user_time},
        {"_ZN2nn4time41GetStandardUserSystemClockCurrentTimespecEP8timespec", user_timespec},
        {"_ZN2nn4time43GetAdjustableUserSystemClockCurrentTimespecEP8timespec", user_timespec},
        {"_ZN2nn4time19StandardSteadyClock3nowEv", steady_clock_now},
        {"_ZN2nn4time14ToCalendarTimeEPNS0_12CalendarTimeEPNS0_22CalendarAdditionalInfoERKNS0_9PosixTimeE", to_calendar},
        {"_ZN2nn4time19ToCalendarTimeInUtcERKNS0_9PosixTimeE", to_calendar_utc},
        {"_ZN2nn4time18ToPosixTimeFromUtcERKNS0_12CalendarTimeE", to_posix_utc},
        {"_ZN2nn4time13ClockSnapshotC1Ev", snapshot_init},
        {"_ZN2nn4time13ClockSnapshot29CreateWithStandardSystemClockEPS1_", snapshot_create},
        {"_ZN2nn4time20CalculateSpanBetweenEPNS_8TimeSpanERKNS0_13ClockSnapshotES5_", span_between},
        {"_ZN2nn4time48CalculateStandardUserSystemClockDifferenceByUserERKNS0_13ClockSnapshotES3_", user_difference},
        {"_ZN2nn4time14ToCalendarTimeEPNS0_12CalendarTimeEPNS0_22CalendarAdditionalInfoERKNS0_9PosixTimeERKNS0_12TimeZoneRuleE", to_calendar_rule},
        {"_ZN2nn4timemiERKNS0_12CalendarTimeERKNS_8TimeSpanE", calendar_minus},
        {"_ZN2nn4time26StandardNetworkSystemClock20IsAccuracySufficientEv", network_accurate},
        {"_ZN2nn4time39ClaimPeriodicBenefitWithUserSystemClockEPNS0_27PeriodicBenefitClaimContextERKNS0_13ClockSnapshotERKNS_8TimeSpanES8_PKNS0_25CheckCalendarTimeCallbackE", claim_periodic_benefit},
        {"_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTaskC1Ev", task_construct},
        {"_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTaskD1Ev", task_destroy},
        {"_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTask10InitializeENS_2os14EventClearModeE", task_initialize},
        {"_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTask9StartTaskEv", task_start},
        {"_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTask9GetResultEv", task_result},
        {"_ZN2nn4time39AsyncEnsureNetworkClockAvailabilityTask14GetFinishEventEv", task_finish_event},
    };
    for (size_t i = 0; i < sizeof map / sizeof *map; i++) if (!strcmp(name, map[i].name)) return map[i].fn;
    return NULL;
}
