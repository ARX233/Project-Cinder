#ifndef VS_ABORT_HISTORY_H
#define VS_ABORT_HISTORY_H
#include <stdint.h>
/* Not authentication: caller validates the structure and claimed identity of
 * each ABORT before recording it. Only local observations are retained; network loss is unknown.
 * NO_MATCH says nothing about packets not observed locally. No clock, heap,
 * retained pointers or locking; caller serializes access and resets per session. */
#define VS_ABORT_HISTORY_KEYS 64u
#define VS_ABORT_HISTORY_INTERVALS 8u
typedef enum { VS_ABORT_NO_MATCH, VS_ABORT_MATCH, VS_ABORT_UNKNOWN } vs_abort_result;
typedef struct { uint32_t lo, hi; } vs_abort_interval;
typedef struct {
    uint64_t peer, nonce;
    uint32_t race;
    unsigned count;
    vs_abort_interval intervals[VS_ABORT_HISTORY_INTERVALS];
} vs_abort_entry;
typedef struct {
    unsigned used, unknown;
    vs_abort_entry entries[VS_ABORT_HISTORY_KEYS];
} vs_abort_history;
void vs_abort_history_reset(vs_abort_history *history);
/* seq may be zero. Invalid identity or internal capacity/invariant failure
 * poisons the session until reset. NULL yields UNKNOWN without mutation. */
vs_abort_result vs_abort_history_record(vs_abort_history *history, uint64_t peer,
                                       uint64_t nonce, uint32_t race, uint32_t seq);
vs_abort_result vs_abort_history_query(vs_abort_history *history, uint64_t peer,
                                      uint64_t nonce, uint32_t race, uint32_t baseline);
#endif
