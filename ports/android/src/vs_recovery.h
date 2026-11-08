#ifndef VS_RECOVERY_H
#define VS_RECOVERY_H
#include <stddef.h>
#include <stdint.h>

/* Best effort only: caller serials identify distinct observations, not network
 * packets. Without server sequence numbers repeated UDP packets cannot be
 * reliably deduplicated. The app must keep polling; this does not interrupt a
 * CPU loop stuck inside a single physical call. No network, save or winner
 * decisions are made here. Times and grace are monotonic milliseconds. */
#define VS_RECOVERY_MAX_MEMBERS 256

typedef enum { VS_RECOVERY_NO_ABORT = 0, VS_RECOVERY_ABORT_MISSING,
               VS_RECOVERY_ABORT_LOCAL } vs_recovery_reason;
typedef enum { VS_RECOVERY_INVALID = -1, VS_RECOVERY_IGNORED = 0,
               VS_RECOVERY_ACCEPTED = 1, VS_RECOVERY_EMIT_ABORT = 2
} vs_recovery_result;
typedef struct {
    uint64_t id;
    int64_t missing_since_ms;
    unsigned missing_observations;
} vs_recovery_member;
typedef struct {
    vs_recovery_member members[VS_RECOVERY_MAX_MEMBERS];
    size_t count;
    uint64_t local_id, race_id, last_serial;
    int64_t grace_ms, last_time_ms;
    vs_recovery_reason reason;
    uint64_t missing_id;
    int initialized, acknowledged;
} vs_recovery;

/* Init clears all state even on failure. IDs must be unique, nonzero, and
 * include local_id. Reset completely isolates subsequent races. */
void vs_recovery_reset(vs_recovery *state);
int vs_recovery_init(vs_recovery *state, const uint64_t *ids, size_t count,
                     uint64_t local_id, uint64_t race_id,
                     int64_t now_ms, int64_t grace_ms);
/* Full lobby snapshot: unique nonzero IDs including local. Serial must be
 * nonzero and strictly increase. Old race and repeated serial are ignored.
 * A missing original member triggers only after >=2 accepted snapshots and
 * elapsed >= grace. Without a fresh snapshot no timeout is evaluated. */
vs_recovery_result vs_recovery_observe(vs_recovery *state, uint64_t race_id,
                                       uint64_t snapshot_serial, int64_t now_ms,
                                       const uint64_t *ids, size_t count);
/* Abort is irreversible until reset, and emits at most once. */
vs_recovery_result vs_recovery_request_abort(vs_recovery *state);
/* Records app handling of an abort, idempotently. */
void vs_recovery_acknowledge(vs_recovery *state);
#endif
