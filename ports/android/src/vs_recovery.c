#include "vs_recovery.h"
#include <string.h>

static int valid_ids(const uint64_t *ids, size_t n, uint64_t local)
{
    size_t i, j;
    int found = 0;
    if (!ids || !n || n > VS_RECOVERY_MAX_MEMBERS || !local) return 0;
    for (i = 0; i < n; ++i) {
        if (!ids[i]) return 0;
        if (ids[i] == local) found = 1;
        for (j = 0; j < i; ++j) if (ids[i] == ids[j]) return 0;
    }
    return found;
}

void vs_recovery_reset(vs_recovery *s)
{
    if (s) memset(s, 0, sizeof(*s));
}

int vs_recovery_init(vs_recovery *s, const uint64_t *ids, size_t n,
                     uint64_t local, uint64_t race, int64_t now, int64_t grace)
{
    size_t i;
    if (!s) return 0;
    vs_recovery_reset(s);
    if (!race || now < 0 || grace < 0 || !valid_ids(ids, n, local)) return 0;
    s->count = n; s->local_id = local; s->race_id = race;
    s->last_time_ms = now; s->grace_ms = grace; s->initialized = 1;
    for (i = 0; i < n; ++i) s->members[i].id = ids[i];
    return 1;
}

vs_recovery_result vs_recovery_observe(vs_recovery *s, uint64_t race,
                                       uint64_t serial, int64_t now,
                                       const uint64_t *ids, size_t n)
{
    size_t i, j;
    if (!s || !s->initialized) return VS_RECOVERY_INVALID;
    if (s->reason != VS_RECOVERY_NO_ABORT || race != s->race_id)
        return VS_RECOVERY_IGNORED;
    if (!serial || now < 0 || now < s->last_time_ms ||
        !valid_ids(ids, n, s->local_id)) return VS_RECOVERY_INVALID;
    if (serial <= s->last_serial) return VS_RECOVERY_IGNORED;
    s->last_serial = serial; s->last_time_ms = now;
    for (i = 0; i < s->count; ++i) {
        vs_recovery_member *m = &s->members[i];
        for (j = 0; j < n && ids[j] != m->id; ++j) {}
        if (j < n) {
            m->missing_since_ms = 0; m->missing_observations = 0;
        } else if (!m->missing_observations) {
            m->missing_since_ms = now; m->missing_observations = 1;
        } else {
            /* Saturate: only 0, 1 and >=2 matter. */
            m->missing_observations = 2;
            if (now - m->missing_since_ms >= s->grace_ms) {
                s->reason = VS_RECOVERY_ABORT_MISSING; s->missing_id = m->id;
                return VS_RECOVERY_EMIT_ABORT;
            }
        }
    }
    return VS_RECOVERY_ACCEPTED;
}

vs_recovery_result vs_recovery_request_abort(vs_recovery *s)
{
    if (!s || !s->initialized) return VS_RECOVERY_INVALID;
    if (s->reason != VS_RECOVERY_NO_ABORT) return VS_RECOVERY_IGNORED;
    s->reason = VS_RECOVERY_ABORT_LOCAL;
    return VS_RECOVERY_EMIT_ABORT;
}

void vs_recovery_acknowledge(vs_recovery *s)
{
    if (s && s->initialized && s->reason != VS_RECOVERY_NO_ABORT)
        s->acknowledged = 1;
}
