/* WVS4 pure bounded session core. No native/game/RNG dependency.
 * Parent adapters own sockets, endpoint binding, entropy and pre-native stop hooks.
 * Session/endpoint binding is NOT cryptographic authentication. */
#ifndef VS4_SESSION_H
#define VS4_SESSION_H
#include <stddef.h>
#include <stdint.h>
#define VS4_VERSION 4
#define VS4_PLAYERS 4
#define VS4_HEADER 88u
#define VS4_PROFILE 21u
#define VS4_NATIVE 632u
#define VS4_MEMBER 96u
#define VS4_STATE_BASE 36u
#define VS4_COMMAND_BODY 40u
#define VS4_MAX_PACKET (VS4_HEADER + VS4_NATIVE)
#define VS4_RX_BUDGET 64u
#define VS4_TOMBSTONES 256u
#define VS4_TUNE_MS 10000u
#define VS4_TUNE_UNKNOWN UINT16_MAX
#define VS4_UPDATE_MESSAGE "Update all clients and the room server to WVS4"
typedef enum { VS4_JOIN=1, VS4_STATE, VS4_COMMAND, VS4_RACE, VS4_REJECT, VS4_REQUEST_VOTE, VS4_VOTE, VS4_COMMIT } vs4_kind;
typedef enum { VS4_ROOM, VS4_MATCH, VS4_MAP, VS4_TIME, VS4_TUNE, VS4_LOAD,
               VS4_RUNNING, VS4_RESULTS, VS4_ABORTING, VS4_ROOM_VIEW } vs4_phase;
typedef enum { VS4_ACK=1, VS4_BEGIN, VS4_PHASE_READY, VS4_CHOICE, VS4_ADVANCE,
               VS4_TUNE_READY, VS4_LOAD_READY, VS4_FINISH, VS4_DONE,
               VS4_QUIT, VS4_CANCEL, VS4_TUNE_DRAFT } vs4_op;
typedef enum { VS4_OK=0, VS4_BAD_WIRE=1, VS4_UPDATE_ALL=2, VS4_FULL=3,
               VS4_BUSY=4, VS4_IDENTITY=5, VS4_STALE=6, VS4_RANGE=7,
               VS4_PEER_QUIT=8, VS4_CONTROL_SILENT=9, VS4_RACE_SILENT=10,
               VS4_LOCAL_CANCEL=11, VS4_AUTHORITY_LOST=12, VS4_CLOCK=13,
               VS4_COUNTER=14, VS4_CATALOG_REQUIRED=15 } vs4_reason;
typedef struct { uint8_t b[16]; } vs4_nonce;
typedef struct {
    uint8_t kind; vs4_nonce incarnation; uint64_t membership, round, config, term;
    uint32_t id; vs4_nonce session; uint64_t sequence;
    const uint8_t *body; uint16_t length;
} vs4_packet;
typedef struct {
    uint32_t id; vs4_nonce session; uint8_t name[16];
    uint8_t maker, car, budget, live, profile[VS4_PROFILE]; uint16_t choice;
    uint8_t base_power, base_handling, identity[19]; uint32_t ipv4; uint16_t port;
} vs4_member;
typedef struct {
    vs4_nonce incarnation; uint64_t membership, round, config, term, event, aborted_round;
    uint8_t phase, n, me, owner, ready, tuned, loaded, finished, done, abort_ack;
    uint8_t reason, state_ack, ramp, km, song, zone; uint32_t seed;
    uint16_t tune_remaining_ms; /* TUNE only; first member's otherwise-unused wire choice */
    vs4_member members[VS4_PLAYERS];
} vs4_state;
typedef struct {
    uint8_t op, target; uint16_t value; uint64_t event;
    uint8_t ramp, km, song, zone, profile[VS4_PROFILE];
} vs4_command;
typedef struct { uint64_t control_ms, race_ms, finish_grace_ms, retry_ms, soft_ms, stage_ms; } vs4_policy;
/* Strict decode/encode: exact datagram/body sizes, endian, zero reserved fields.
 * Decoders leave output unchanged on failure. Validation never reads native data. */
int vs4_decode(vs4_packet *, const uint8_t *, size_t);
size_t vs4_encode(uint8_t *, size_t, const vs4_packet *);
int vs4_state_decode(vs4_state *, const vs4_packet *);
size_t vs4_state_encode(uint8_t *, size_t, const vs4_state *);
int vs4_command_decode(vs4_command *, const vs4_packet *);
void vs4_command_encode(uint8_t out[VS4_COMMAND_BODY], const vs4_command *);
int vs4_profile_valid(const vs4_member *, const uint8_t profile[VS4_PROFILE]);
/* Structural identity/cosmetic bounds plus original-reachable permanent budget.
 * Exact model/color catalog validation remains a parent/build-catalog hook. */
int vs4_registration_valid(const uint8_t profile[VS4_PROFILE]);
int vs4_member_registration(const vs4_member *,uint8_t out[VS4_PROFILE]);
int vs4_nonce_equal(vs4_nonce, vs4_nonce);
int vs4_nonce_nonzero(vs4_nonce);
vs4_policy vs4_default_policy(void);

typedef struct {
    vs4_state view; vs4_nonce session; uint32_t id; vs4_policy policy;
    uint64_t tx_seq, state_seq, race_seq[VS4_PLAYERS];
    uint32_t native_count[VS4_PLAYERS]; uint8_t native_seen;
    uint64_t heard, race_heard[VS4_PLAYERS], clock, phase_since, local_loaded_round;
    uint64_t local_loaded_config, local_finished_round;
    uint8_t joined, stop, teardown, authority_lost, reason, profile_confirmed, paused;
    uint8_t own_profile[VS4_PROFILE];
} vs4_client;
/* session MUST come from successful OS entropy, unique each fresh open/reconnect. */
int vs4_client_init(vs4_client *, uint32_t id, vs4_nonce session, uint64_t now, vs4_policy);
/* Input must already come from the socket's selected exact authority endpoint.
 * Accept returns1, stale/irrelevant0, malformed -1; reject UPDATE sets reason. */
int vs4_client_receive(vs4_client *, const uint8_t *, size_t, uint64_t now);
void vs4_client_tick(vs4_client *, uint64_t now);
void vs4_client_cancel(vs4_client *); /* sticky before network delivery */
void vs4_client_teardown_done(vs4_client *); /* abort ACK only after actual teardown */
int vs4_client_native_allowed(const vs4_client *);
size_t vs4_client_join(vs4_client *, uint8_t *, size_t, const uint8_t name[16],
                       const uint8_t identity[19], uint8_t base_power, uint8_t base_handling);
size_t vs4_client_command(vs4_client *, uint8_t *, size_t, const vs4_command *);
size_t vs4_client_race(vs4_client *, uint8_t *, size_t, const uint8_t native[VS4_NATIVE]);

/* Pure authority. Endpoint tokens are assigned by transport adapter from exact
 * sockaddr / GameKit peer; never chosen from packet content. Emit is synchronous.
 * Majority election is a separate source-bound vs_election module; no GO until
 * original-roster quorum has freshly handshaken with the new incarnation/term. */
typedef void (*vs4_emit_fn)(void *ctx, uint64_t endpoint, const uint8_t *, size_t);
typedef int (*vs4_decision_fn)(const vs4_state *, const vs4_command *, void *);
typedef int (*vs4_seed_fn)(uint32_t *,void *);
typedef int (*vs4_registration_fn)(const uint8_t profile[VS4_PROFILE],void *);
typedef struct {
    vs4_decision_fn decision; void *decision_ctx;vs4_seed_fn seed_source;void *seed_ctx;vs4_registration_fn registration_validator;void *registration_ctx;
    vs4_state state; vs4_policy policy; uint64_t endpoint[VS4_PLAYERS];
    uint64_t control[VS4_PLAYERS], race_seen[VS4_PLAYERS], high[VS4_PLAYERS][6];
    uint8_t tune_draft[VS4_PLAYERS][VS4_PROFILE];
    uint64_t send_seq, clock, last_broadcast;
    vs4_nonce tombstones[VS4_TOMBSTONES]; unsigned tombstone_count;
    uint8_t failed, native_seen, allow_loopback_endpoints, catalog_required; uint32_t native_count[VS4_PLAYERS]; uint64_t phase_since;
    uint8_t migration_quorum, migration_seen, migration_approved; vs4_member original[VS4_PLAYERS]; uint8_t original_n;uint32_t recovery_owner;
} vs4_authority;
int vs4_authority_init(vs4_authority *, vs4_nonce incarnation, uint64_t now, vs4_policy);
int vs4_authority_receive(vs4_authority *, uint64_t endpoint, const uint8_t *, size_t,
                          uint64_t now, vs4_emit_fn, void *ctx);
void vs4_authority_tick(vs4_authority *, uint64_t now, vs4_emit_fn, void *ctx);
/* Seed is supplied once per BEGIN by adapter/policy, not drawn from native RNG.
 * This deterministic setter is for coordinator decisions before ROUND begins. */
int vs4_authority_set_seed(vs4_authority *, uint32_t seed);
/* Recovered authority remains admission/BEGIN locked until original-roster quorum
 * have freshly handshaken from the frozen source endpoint. */
int vs4_authority_recover(vs4_authority *, const vs4_state *frozen, vs4_nonce new_incarnation,
                           uint64_t new_term, uint64_t now, vs4_policy);
/* Coordinator vote policy hook: return nonzero only for legal voted config.
 * Validator is mandatory for ADVANCE leaving MAP or TIME; no host-personal fallback. */
void vs4_authority_set_decision_validator(vs4_authority *, vs4_decision_fn, void *);
void vs4_authority_set_seed_source(vs4_authority *,vs4_seed_fn,void *);
void vs4_authority_set_registration_validator(vs4_authority *,vs4_registration_fn,void *);
#endif
