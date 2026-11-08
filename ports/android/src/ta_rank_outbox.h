/* Separate durable upload candidates, never a board or server authority. */
#ifndef CINDER_TA_RANK_OUTBOX_H
#define CINDER_TA_RANK_OUTBOX_H
#include "ta_rank.h"
#define TA_RANK_OUTBOX_CAPACITY 256u
#define TA_RANK_OUTBOX_FULL ((ta_rank_status)100)
typedef struct ta_rank_outbox ta_rank_outbox;
/* Fixed cohort bytes, no I/O; IDs remain opaque local identities, NOT auth. */
ta_rank_outbox *ta_rank_outbox_create(const uint8_t rules_sha256[32],
                                      const uint8_t physics_sha256[32]);
void ta_rank_outbox_destroy(ta_rank_outbox *outbox);
/* Trusted absolute app-private directory; exact basename
 * ta-pending-v1-<rules64hex>-<physics64hex>.ctq. Same single-owner/no-follow,
 * regular-file, stat-ns, explicit LE/CRC and atomic publication rules as board.
 * OK/NOT_FOUND binds writable state; corrupt/foreign data is never overwritten.
 */
ta_rank_status ta_rank_outbox_open(ta_rank_outbox *outbox, const char *save_dir);
/* Durable enqueue independent of local top100 admission. Each owner/course/
 * traffic cell retains only strictly faster pending. Exact retained attempt
 * repeats => DUPLICATE; same attempt with changed data => ATTEMPT_CONFLICT.
 * Full new cell => OUTBOX_FULL; no eviction, mutation, write or pretend sync.
 * Pre-rename failure rolls back old model+bytes. COMMITTED_UNSYNCED means the
 * new candidate IS published; parent must disclose uncertain durability.
 */
ta_rank_status ta_rank_outbox_enqueue(ta_rank_outbox *outbox,
                                     const ta_rank_attempt *attempt);
uint32_t ta_rank_outbox_count(const ta_rank_outbox *outbox);
uint64_t ta_rank_outbox_generation(const ta_rank_outbox *outbox);
/* Index0..count-1, copied stable attempt and optional model generation. All
 * entries are LOCAL_UNVERIFIED future proposals, not SERVER_VERIFIED rows.
 * No credential, uploaded path, rank or verified flag is stored in an attempt.
 */
ta_rank_status ta_rank_outbox_copy(const ta_rank_outbox *outbox, uint32_t index,
                                  ta_rank_attempt *attempt, uint64_t *generation);
/* Only call after an authenticated server acknowledges this exact submission.
 * A faster replacement queued during upload has another ID and remains intact. */
ta_rank_status ta_rank_outbox_ack(ta_rank_outbox *outbox,const uint8_t attempt[16]);
const char *ta_rank_outbox_error(ta_rank_status status);
#endif
