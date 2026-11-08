/* Frozen API v1 -- approved by parent for isolated implementation.
 * Pure local TA ranking + separate private sidecar. No RC, RNG, old PB, network,
 * global auth or native/machine "Official" authority. All APIs game-thread-only.
 */
#ifndef CINDER_TA_RANK_H
#define CINDER_TA_RANK_H
#include <stddef.h>
#include <stdint.h>

#define TA_RANK_API_VERSION 1u
#define TA_RANK_COURSES 15u
#define TA_RANK_TRAFFIC_KINDS 2u
#define TA_RANK_TOP 100u
#define TA_RANK_DISPLAY 10u
#define TA_RANK_CHECKPOINTS 7u
#define TA_RANK_TIME_SENTINEL 0xfffffu
#define TA_RANK_MAX_SCORE_MS 0xffffeu
#define TA_RANK_FACTORY_DISPLAY_MS 1199999u
#define TA_RANK_STORE_MAX_BYTES (2u * 1024u * 1024u)
#define TA_RANK_COMMUNITY_ROW_BYTES 236u

/* All hashes/identities are fixed bytes, not NUL strings or JSON numbers.
 * course_id is original nsTaData id, NOT UI/save index, ta-slot or ERamp.
 * traffic partitions are an explicit port policy, NOT invented stock classes.
 */
typedef struct {
  uint8_t rules_sha256[32], physics_sha256[32];
  uint32_t course_id; /* enabled 0..14 excluding 5,7,11 */
  uint32_t traffic;   /* exact frozen TA traffic: 0 or 1 */
} ta_rank_partition;

/* Caller freezes actual metadata, never a template's GUEST/stock/tune values.
 * name is five bounded Unicode scalars (0 pads a short name), not glyph IDs.
 * original_id_valid=0 means no original owner identity claimed; the opaque
 * owner[16] below is a distinct local/authenticated-player identity plane.
 */
typedef struct {
  uint32_t name[5];
  uint32_t title_id, class_id;
  uint32_t model_id; /* emCarModelID, actual selected body/color */
  uint32_t car_type; /* ECarType, actual physics type */
  uint32_t power, handling; /* effective native config, 0..24 each */
  uint32_t original_id_valid, original_id1, original_id2, original_devel;
} ta_rank_metadata;

typedef struct {
  ta_rank_partition partition;
  uint8_t owner[16]; /* nonzero stable local card/auth identity, NEVER MT RNG */
  uint8_t attempt[16]; /* nonzero immutable per-run id, NEVER user provided path */
  uint64_t completed_at_ms; /* local calendar metadata; NOT elapsed authority */
  uint32_t native_elapsed_bits; /* exact IEEE754 binary32 S2DInfoRace+8 seconds */
  uint32_t checkpoint_count;
  /* Raw cumulative elapsed at PRE-GOAL checkpoint ends: split[1]..split[count].
   * Never include split[0], durations or a manufactured goal sample. */
  uint32_t checkpoint_bits[TA_RANK_CHECKPOINTS];
  uint32_t race_field[6]; /* actual SConfigRaceField words, including float bits */
  uint32_t native_game_mode; /* must be 6 */
  uint32_t frontend_game_mode; /* must be 2=real TA; qualification Ghost is NOT TA */
  uint32_t native_result_state; /* must be 8, not GoalWait7 */
  uint32_t eligible; /* caller checked normal TA/no movie/cancel/debug/etc.; not auth */
  ta_rank_metadata metadata;
} ta_rank_attempt;

enum {
  TA_RANK_SOURCE_LOCAL_UNVERIFIED=1,
  TA_RANK_SOURCE_SERVER_VERIFIED=2, /* reserved; local APIs can NEVER mint this */
  TA_RANK_SOURCE_FACTORY_DEFAULT=3, /* display-only, no owner/attempt/score */
  TA_RANK_SOURCE_COMMUNITY_UNVERIFIED=4
};
typedef struct {
  ta_rank_attempt attempt;
  uint32_t score_ms; /* 1..1048574; no 0/sentinel/factory value */
  uint64_t sequence; /* persisted monotonic tie key; reject exhaustion */
} ta_rank_record;

typedef struct {
  uint32_t source_kind;
  uint32_t position; /* positional 1..100, no shared competition ranks */
  uint32_t display_ms; /* real score or factory display1199999 */
  uint32_t default_index; /* 0..9 only for factory rows; otherwise UINT32_MAX */
  ta_rank_record record; /* zero for default rows; no template stats fabricated */
} ta_rank_row;

typedef struct {
  ta_rank_partition partition;
  uint64_t generation; /* local model generation, NOT server revision */
  uint32_t real_count; /* complete retained competitive list length: 0..100 */
  uint32_t row_count; /* requested bounded rows, defaults fill only to ten */
  uint32_t source_kind; /* LOCAL_UNVERIFIED from current public producer */
  ta_rank_row rows[TA_RANK_DISPLAY];
} ta_rank_view;

int ta_rank_community_encode(const ta_rank_attempt *attempt, uint8_t output[TA_RANK_COMMUNITY_ROW_BYTES]);
int ta_rank_community_board(const void *bytes, size_t size, const ta_rank_partition *partition, ta_rank_view *out);

typedef struct ta_rank_context ta_rank_context;
typedef enum {
  TA_RANK_OK=0,
  TA_RANK_NO_CHANGE, /* same owner equal/slower; no write/generation change */
  TA_RANK_DUPLICATE, /* exact retained attempt already present */
  TA_RANK_NOT_FOUND, /* missing private file; empty writable model bound */
  TA_RANK_INVALID,
  TA_RANK_ATTEMPT_CONFLICT,
  TA_RANK_FOREIGN, /* incompatible cohort/version; existing bytes preserved */
  TA_RANK_CORRUPT, /* existing bytes preserved; no replacement allowed */
  TA_RANK_UNSAFE_PATH,
  TA_RANK_IO,
  TA_RANK_MEMORY,
  TA_RANK_STALE, /* inode/size/mtime/ctime changed since trusted open/load */
  TA_RANK_EXHAUSTED,
  /* Rename committed but parent-directory fsync failed: model updated to new
   * bytes; caller MUST NOT claim old file was retained or retry an old commit. */
  TA_RANK_COMMITTED_UNSYNCED
} ta_rank_status;

typedef struct {
  uint32_t position; /* 0 if not retained/no insertion */
  uint32_t score_ms;
  uint64_t generation;
} ta_rank_submission;

/* Parent rule gate: original finite-f32 *1000f, trunc toward zero and clamp
 * 20 bits; only 1..0xffffe is competitive. NaN/Inf fail rather than UB. */
int ta_rank_time_ms(uint32_t elapsed_bits, uint32_t *score_ms);
int ta_rank_course_enabled(uint32_t course_id);

/* One rules/physics cohort per context; up to 15*2*100 bounded real rows.
 * No default entries enter the competitive model. create/destroy do no I/O.
 */
ta_rank_context *ta_rank_create(const uint8_t rules_sha256[32],
                                const uint8_t physics_sha256[32]);
void ta_rank_destroy(ta_rank_context *context);

/* Pure ranking operation. Same owner keeps strictly faster only. Sort score
 * ascending, timestamp descending, sequence descending (latest exact key first).
 * Attempt conflict/idempotency is guaranteed only for RETAINED rows; this bounded
 * local board is NOT a durable all-attempt anti-replay ledger. */
ta_rank_status ta_rank_submit_local(ta_rank_context *context,
                                    const ta_rank_attempt *attempt,
                                    ta_rank_submission *submission);

/* Copy a stable top-ten presentation snapshot; no allocation/native/RNG/I/O.
 * Real rows first, then display defaults until ten if include_defaults!=0.
 * All real rows from these APIs remain LOCAL_UNVERIFIED regardless of metadata.
 */
ta_rank_status ta_rank_view_local(const ta_rank_context *context,
                                 uint32_t course_id, uint32_t traffic,
                                 int include_defaults, ta_rank_view *view);
/* Optional exact retained row copy, position1..100; no synthesized defaults. */
ta_rank_status ta_rank_get_local(const ta_rank_context *context,
                                uint32_t course_id, uint32_t traffic,
                                uint32_t position, ta_rank_record *record);

/* Bind trusted absolute directory by no-symlink component walk. Exact basename
 * ta-ranking-v1-<rules64hex>-<physics64hex>.ctr only; bounded LE+CRC, not structs.
 * New file/valid load establishes expected inode/stat token. Corrupt, foreign,
 * unsafe, changed or unsupported file never authorizes an overwrite.
 * No directory creation, source/old-PB access, uploaded paths or polling.
 */
ta_rank_status ta_rank_store_open(ta_rank_context *context, const char *save_dir);
/* Validate on a detached candidate; only publish candidate model after atomic
 * file publication. Before-rename failure rolls back model+old file. Commit
 * requires successful store_open(OK/NOT_FOUND), and no pure submit since then.
 * O_EXCL temp -> write -> fsync -> close -> identity recheck -> renameat -> dir
 * fsync. Foreign/corrupt old bytes are never repaired or deleted automatically.
 */
ta_rank_status ta_rank_commit_local(ta_rank_context *context,
                                    const ta_rank_attempt *attempt,
                                    ta_rank_submission *submission);
void ta_rank_store_close(ta_rank_context *context);
const char *ta_rank_error(ta_rank_status status);

/* Future TA server protocol lives separately. No C API consumes arbitrary
 * client/server "verified" booleans or grants SERVER_VERIFIED in this version.
 * A later authenticated receipt/snapshot verifier needs explicit approval.
 */
#endif
