/* Independent LOCAL ghost sidecar. No garage/records/options/keys mutation.
 * CRC32 detects corruption only: not authentication, anti-cheat or cloud rank.
 * load is NOT native-ready: after car_init, car_ghost_prepare must validate the
 * actual ramp/route/stage/area and decoded original samples before native load.
 */
#ifndef GHOST_STORE_H
#define GHOST_STORE_H

#include "car.h"
#include "ghost_format.h"
#include <stddef.h>
#include <stdint.h>

#define GHOST_STORE_BASENAME "ghost_local_v1"
#define GHOST_STORE_ENVELOPE_VERSION 1u
#define GHOST_STORE_HEADER_BYTES 184u
#define GHOST_STORE_MAX_BYTES (GHOST_STORE_HEADER_BYTES + GHOST_MAX_BYTES)

typedef struct {
  uint32_t ramp, route; /* ERamp 1..22, or the shared-only exact TA selector. */
  uint32_t race_field[6]; /* reviewed native words, NOT invented from a TA course */
  car_spec owner; /* renderer maps owner.type to its current CARDB, never a private pack id */
  char physics_sha256[65]; /* exactly 64 lowercase hex characters and terminating NUL */
  uint64_t recorded_at; /* Unix seconds; 0 unknown, maximum 9999-12-31T23:59:59Z */
  unsigned char *trail; /* load owns a new allocation; save borrows without taking ownership */
  size_t trail_bytes;
} ghost_store_record;

/* Local per-area crown. The profile and sampled trail are one atomic record,
 * separate from the legacy practice slot and any server-side title. */
#define GHOST_CROWN_AREAS 8u
#define GHOST_LOCAL_REPLAYS_PER_AREA 4u
typedef struct {
  ghost_store_record race;
  uint32_t raw_model, raw_ramp, custom_color, aero, mirror, wing, bonnet, wheel, neon, vinyl, title, class_id;
  uint16_t name[5];
  uint64_t revision; /* loaded checksum plus one; zero expects an absent crown */
} ghost_crown_record;

typedef enum {
  GHOST_STORE_OK = 0,
  GHOST_STORE_NOT_FOUND,
  GHOST_STORE_ARGUMENT,
  GHOST_STORE_IO,
  GHOST_STORE_MEMORY,
  GHOST_STORE_VERSION,
  GHOST_STORE_LENGTH,
  GHOST_STORE_CHECKSUM,
  GHOST_STORE_PHYSICS,
  GHOST_STORE_METADATA,
  GHOST_STORE_TRAIL,
  GHOST_STORE_UNSAFE_PATH,
  /* Rename already committed, but directory fsync failed: warning, NOT an
   * unchanged-old-file failure. Caller may reload the committed record. */
  GHOST_STORE_COMMITTED_UNSYNCED,
  GHOST_STORE_STALE
} ghost_store_result;

/* save_dir is trusted app configuration: absolute, no . or .. components,
 * no symlink in any component. Only BASENAME and exclusively created temp files
 * in this pinned directory are accessed. Never accept an uploaded file path.
 * out must be zero-initialized or freed; any failure leaves it unchanged.
 * expected_physics_sha256 must be the current trusted car_ghost_physics_id(). */
ghost_store_result ghost_store_load(const char *save_dir,
                                    const char *expected_physics_sha256,
                                    ghost_store_record *out);
/* Validates all local metadata and basic bounded 070426a container syntax first.
 * A successful explicit save replaces this one sidecar only. Unsupported newer
 * envelope versions are preserved. Failures BEFORE atomic rename preserve old
 * bytes. 0600 exclusive temp -> write -> fsync -> close -> rename -> dir fsync.
 * No directory creation, traversal/enumeration, legacy save access or native code.
 * Caller must not concurrently mutate record or its borrowed trail. */
ghost_store_result ghost_store_save(const char *save_dir,
                                    const ghost_store_record *record);
ghost_store_result ghost_crown_load(const char *save_dir, unsigned area, const char *physics,
                                   ghost_crown_record *out);
ghost_store_result ghost_crown_save(const char *save_dir, unsigned area,
                                   const ghost_crown_record *record, uint64_t expected_revision);
/* Ordinary player recordings are stored separately from all crown files.
 * Slots are bounded per area, and replacement uses the same revision check. */
ghost_store_result ghost_replay_load(const char *save_dir, unsigned area, unsigned slot,
                                    const char *physics, ghost_crown_record *out);
ghost_store_result ghost_replay_save(const char *save_dir, unsigned area, unsigned slot,
                                    const ghost_crown_record *record, uint64_t expected_revision);
void ghost_crown_free(ghost_crown_record *record);
/* Portable replay profile uses the same wire bytes as a crown. Cloud uploads
 * are ordinary recordings and carry no authority to assign a crown. */
ghost_store_result ghost_profile_pack(const ghost_crown_record *record,unsigned char **out,size_t *length);
ghost_store_result ghost_profile_unpack(unsigned char *data,size_t length,const char *physics,ghost_crown_record *out);
void ghost_store_free(ghost_store_record *record);
/* Only map equality on a loaded/owned record. It conveys no native readiness. */
int ghost_store_contains_map(const ghost_store_record *record,
                             uint32_t ramp, uint32_t route);
/* Optional strict execution-free validation with a REAL caller-supplied native
 * area policy; rejects NULL/mismatched policy rather than making an allow-all.
 * car_ghost_prepare remains mandatory for actual native binding and loading. */
ghost_store_result ghost_store_validate_native(const ghost_store_record *record,
                                               const ghost_format_policy *policy);
const char *ghost_store_error(ghost_store_result result);

/* Wire v1: 184-byte explicit little-endian header, no struct/pointer/padding dump.
 * 0 magic[8]="W3GLOCAL"; 8 version u32; 12 header bytes u32; 16 trail bytes u32;
 * 20 total bytes u32; 24 CRC32 u32; 28 reserved u32=0; 32 ramp; 36 route;
 * 40 race_field[6]; 64 owner.type; 68 gears; 72 tyres[6] IEEE754 binary32;
 * 96 spokes; 100 power; 104 handling; 108 physics SHA ASCII[64];
 * 172 recorded_at u64; 180 reserved u32=0; 184 original opaque 070426a bytes.
 * CRC32 covers the ENTIRE header (CRC slot zeroed) plus exact trail payload.
 * All remaining u32 fields explicitly serialized. No cloud authority fields.
 */
#endif
