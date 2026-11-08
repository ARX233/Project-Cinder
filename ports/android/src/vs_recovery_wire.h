#ifndef VS_RECOVERY_WIRE_H
#define VS_RECOVERY_WIRE_H
#include <stddef.h>
#include <stdint.h>

/* WV1 profile: first 21 bytes opaque; bytes 21..41 contain RFR1. */
#define VS_RECOVERY_WIRE_BASE_SIZE 21u
#define VS_RECOVERY_WIRE_SIZE 42u
/* Optional tail: RFR1 stays byte-for-byte unchanged, old decoders ignore it. */
#define VS_RECOVERY_READY_SIZE 47u
#define VS_RECOVERY_WIRE_NORMAL 0u
#define VS_RECOVERY_WIRE_ABORT 1u
#define VS_RECOVERY_WIRE_FINISHED 2u

typedef struct vs_recovery_wire_extension {
    uint8_t flags;
    uint32_t race_id;
    uint64_t nonce;
    uint32_t seq;
} vs_recovery_wire_extension;

/* Return 1 on success, 0 on invalid input or insufficient capacity.
 * base_len >= 21, out_capacity >= 42. Output must not overlap either input.
 * On failure output is untouched. NORMAL race=0 is valid before GO;
 * ABORT/FINISHED require nonzero race. The caller supplies a nonzero random
 * room-session nonce and refreshes it on every room entry. */
int vs_recovery_wire_encode(uint8_t *out, size_t out_capacity,
                            const uint8_t *base, size_t base_len,
                            const vs_recovery_wire_extension *extension);

/* Return 1 for a valid extension, 0 otherwise (including legacy profiles).
 * Trailing bytes are allowed. Output and profile must not overlap. Output is
 * untouched on failure. NORMAL race=0 cannot match a frozen nonzero GO race. */
int vs_recovery_wire_decode(vs_recovery_wire_extension *out,
                            const uint8_t *profile, size_t profile_len);

/* Optional RDY1 tail at 42..46. The RFR1 prefix must already be valid.
 * put_ready mutates only the tail on success; loaded must be 0 or 1.
 * read_ready returns 1 only for a valid RFR1+RDY1 and writes 0/1 to loaded;
 * on failure output is untouched. Capability alone is not evidence of loading. */
int vs_recovery_wire_put_ready(uint8_t *profile, size_t capacity, int loaded);
int vs_recovery_wire_read_ready(const uint8_t *profile, size_t length, int *loaded);

/* RFC 1982: 0 < (candidate-last) mod 2^32 < 2^31. Half-range is rejected. */
int vs_recovery_wire_seq_newer(uint32_t candidate, uint32_t last);

/* Caller selects the frozen GO member and supplies that member's GO snapshot
 * nonce and last accepted sequence (initially the GO snapshot seq). Return 1
 * only for valid flags, matching nonzero nonce/race and a newer sequence.
 * NORMAL is progress too. Update last only on success; duplicates/replays
 * must not refresh timeouts. This cannot prove membership; caller must select
 * the frozen member. Nonce isolates sessions, it is not authentication. If
 * the server restarts and reuses race IDs within the same room session, the
 * same nonce+race cannot distinguish the old race. Half-range sequence checks
 * provide only bounded replay protection, not security authentication. */
int vs_recovery_wire_accept_peer(const vs_recovery_wire_extension *peer,
                                 uint64_t snapshot_nonce, uint32_t race_id,
                                 uint32_t last_accepted_seq);
#endif
