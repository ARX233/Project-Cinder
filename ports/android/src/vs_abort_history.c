#include "vs_abort_history.h"
#include <string.h>

/* Check all structural assumptions before using caller-owned state. */
static int valid(const vs_abort_history *h)
{
    unsigned i, j, k;
    if (h->used > VS_ABORT_HISTORY_KEYS || h->unknown > 1u) return 0;
    for (i = 0; i < h->used; ++i) {
        const vs_abort_entry *e = &h->entries[i];
        if (!e->peer || !e->nonce || !e->race || !e->count ||
            e->count > VS_ABORT_HISTORY_INTERVALS) return 0;
        for (j = 0; j < e->count; ++j) {
            if (e->intervals[j].lo > e->intervals[j].hi) return 0;
            if (j && (uint64_t)e->intervals[j-1].hi + 1u >= e->intervals[j].lo)
                return 0;
        }
        for (k = 0; k < i; ++k)
            if (h->entries[k].peer == e->peer && h->entries[k].nonce == e->nonce &&
                h->entries[k].race == e->race) return 0;
    }
    return 1;
}
void vs_abort_history_reset(vs_abort_history *h)
{
    if (h) memset(h, 0, sizeof(*h));
}
static int ready(vs_abort_history *h, uint64_t p, uint64_t n, uint32_t r)
{
    if (!h) return 0;
    if (h->unknown || !p || !n || !r || !valid(h)) {
        h->unknown = 1;
        return 0;
    }
    return 1;
}
static unsigned locate(const vs_abort_history *h, uint64_t p, uint64_t n, uint32_t r)
{
    unsigned i;
    for (i = 0; i < h->used; ++i)
        if (h->entries[i].peer == p && h->entries[i].nonce == n && h->entries[i].race == r)
            break;
    return i;
}
vs_abort_result vs_abort_history_record(vs_abort_history *h, uint64_t p,
                                       uint64_t n, uint32_t r, uint32_t s)
{
    vs_abort_interval input[VS_ABORT_HISTORY_INTERVALS + 2u], merged[VS_ABORT_HISTORY_INTERVALS + 2u], t;
    unsigned i, j, count, out = 0, idx;
    uint32_t lo = s - UINT32_C(0x7fffffff), hi = s - 1u;
    vs_abort_entry *e;
    if (!ready(h, p, n, r)) return VS_ABORT_UNKNOWN;
    idx = locate(h, p, n, r);
    if (idx == h->used && h->used == VS_ABORT_HISTORY_KEYS) {
        h->unknown = 1; return VS_ABORT_UNKNOWN;
    }
    e = &h->entries[idx];
    count = idx == h->used ? 0u : e->count;
    for (i = 0; i < count; ++i) input[i] = e->intervals[i];
    if (lo <= hi) input[count++] = (vs_abort_interval){lo, hi};
    else {
        input[count++] = (vs_abort_interval){0, hi};
        input[count++] = (vs_abort_interval){lo, UINT32_MAX};
    }
    for (i = 1; i < count; ++i) {
        t = input[i]; j = i;
        while (j && input[j-1].lo > t.lo) { input[j] = input[j-1]; --j; }
        input[j] = t;
    }
    for (i = 0; i < count; ++i) {
        if (out && (uint64_t)input[i].lo <= (uint64_t)merged[out-1].hi + 1u) {
            if (input[i].hi > merged[out-1].hi) merged[out-1].hi = input[i].hi;
        } else merged[out++] = input[i];
    }
    if (out > VS_ABORT_HISTORY_INTERVALS) { h->unknown = 1; return VS_ABORT_UNKNOWN; }
    if (idx == h->used) {
        memset(e, 0, sizeof(*e)); e->peer = p; e->nonce = n; e->race = r; ++h->used;
    }
    e->count = out;
    for (i = 0; i < out; ++i) e->intervals[i] = merged[i];
    if (!valid(h)) { h->unknown = 1; return VS_ABORT_UNKNOWN; }
    return VS_ABORT_MATCH; /* success, not a baseline query */
}
vs_abort_result vs_abort_history_query(vs_abort_history *h, uint64_t p,
                                      uint64_t n, uint32_t r, uint32_t b)
{
    unsigned i, idx;
    if (!ready(h, p, n, r)) return VS_ABORT_UNKNOWN;
    idx = locate(h, p, n, r);
    if (idx == h->used) return VS_ABORT_NO_MATCH;
    for (i = 0; i < h->entries[idx].count; ++i)
        if (b >= h->entries[idx].intervals[i].lo && b <= h->entries[idx].intervals[i].hi)
            return VS_ABORT_MATCH;
    return VS_ABORT_NO_MATCH;
}
