/* Strict, execution-free validation of the original 070426a sampled trail.
 * This is a native trail container, not an input replay or a heap snapshot.
 * Cloud ownership, signature and championship authority belong to the caller. */
#ifndef GHOST_FORMAT_H
#define GHOST_FORMAT_H

#include <stddef.h>
#include <stdint.h>

#define GHOST_NATIVE_VERSION UINT32_C(0x070426a)
#define GHOST_SAMPLE_BYTES 48u
#define GHOST_MAX_SAMPLES 8192u
#define GHOST_MAX_AREAS 512u
#define GHOST_MAX_TICKS 36000u
#define GHOST_LONG_TA_STAGE 374u /* full Shuto Tokyo 60 km native stage */
#define GHOST_LONG_TA_MAX_TICKS 72000u
#define GHOST_MAX_BYTES (28u + 4u * GHOST_MAX_AREAS + GHOST_SAMPLE_BYTES * GHOST_MAX_SAMPLES)

typedef enum {
  GHOST_FORMAT_OK = 0,
  GHOST_FORMAT_ARGUMENT,
  GHOST_FORMAT_VERSION,
  GHOST_FORMAT_LENGTH,
  GHOST_FORMAT_LIMIT,
  GHOST_FORMAT_CHECKSUM,
  GHOST_FORMAT_STAGE,
  GHOST_FORMAT_AREA,
  GHOST_FORMAT_SAMPLE,
  GHOST_FORMAT_MEMORY
} ghost_format_result;

typedef struct {
  /* Required: equality to a reviewed native stage; no wildcard stage. */
  uint32_t stage;
  /* Required: reject any area which is not in the current native area's table.
   * The callback receives identifiers only, never untrusted pointers. */
  int (*area_allowed)(uint32_t area, void *context);
  void *context;
  /* Zero selects the hard safety cap above, not an unbounded limit. */
  uint32_t max_samples;
  /* Optional reviewed native ordered-road binding. Without it, the remote
   * route-0 contract still requires unique IDs. A supplied callback must check
   * the complete sequence against the actual loaded stage, not the blob itself.
   * Repeated native loop IDs are permitted ONLY when this callback approves. */
  int (*area_sequence_allowed)(const uint32_t *areas, uint32_t count, void *context);
  /* Only the reviewed long Time Attack field may use the longer cap. */
  uint32_t max_ticks;
} ghost_format_policy;

typedef struct {
  uint32_t version, stage, seed, sample_step, samples, areas;
  size_t bytes, payload_offset;
  float first_odometer, last_odometer;
} ghost_format_info;

/* Validates exact length, byte-sum, count/step, decoded finite values and all
 * area references before any native code sees the bytes. Output is zero on failure.
 * The original transposed/delta payload is copied for decoding, never modified. */
ghost_format_result ghost_format_validate(const void *data, size_t size,
                                          const ghost_format_policy *policy,
                                          ghost_format_info *info);
const char *ghost_format_error(ghost_format_result result);

#endif
