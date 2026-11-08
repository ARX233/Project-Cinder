#include "ghost_format.h"
#if defined(__FAST_MATH__)
#error "Ghost boundary validation requires -fno-fast-math (finite checks must remain real)."
#endif

#include <math.h>
#include <stdlib.h>
#include <string.h>

_Static_assert(sizeof(float) == 4, "native Ghost format requires binary32 storage");

static uint32_t le32(const unsigned char *p) {
  return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static float float32(const unsigned char *p) {
  uint32_t word = le32(p);
  float value;
  memcpy(&value, &word, sizeof value);
  return value;
}
static int contains_area(const unsigned char *data, uint32_t count, uint32_t area) {
  for (uint32_t i = 0; i < count; ++i)
    if (le32(data + 8u + 4u * i) == area) return 1;
  return 0;
}

ghost_format_result ghost_format_validate(const void *input, size_t size,
                                          const ghost_format_policy *policy,
                                          ghost_format_info *info) {
  if (info) memset(info, 0, sizeof *info);
  if (!input || !policy || !policy->area_allowed || !info) return GHOST_FORMAT_ARGUMENT;
  const unsigned char *data = input;
  if (size < 28u || size > GHOST_MAX_BYTES) return GHOST_FORMAT_LENGTH;
  if (le32(data) != GHOST_NATIVE_VERSION) return GHOST_FORMAT_VERSION;
  uint32_t areas = le32(data + 4);
  if (!areas || areas > GHOST_MAX_AREAS) return GHOST_FORMAT_LIMIT;
  size_t header = 8u + 4u * (size_t)areas;
  if (size < header + 20u) return GHOST_FORMAT_LENGTH;
  uint32_t stage = le32(data + header), seed = le32(data + header + 4u);
  uint32_t step = le32(data + header + 8u), count = le32(data + header + 12u);
  uint32_t limit = policy->max_samples ? policy->max_samples : GHOST_MAX_SAMPLES;
  uint32_t ticks = policy->max_ticks ? policy->max_ticks : GHOST_MAX_TICKS;
  uint32_t max_ticks = policy->stage == GHOST_LONG_TA_STAGE ? GHOST_LONG_TA_MAX_TICKS : GHOST_MAX_TICKS;
  if (limit > GHOST_MAX_SAMPLES || count < 2u || count > limit || !step || step > 60u ||
      ticks > max_ticks || (uint64_t)(count - 1u) * step > ticks) return GHOST_FORMAT_LIMIT;
  size_t payload = header + 16u, sample_bytes = (size_t)count * GHOST_SAMPLE_BYTES;
  if (size != payload + sample_bytes + 4u) return GHOST_FORMAT_LENGTH;
  if (stage != policy->stage) return GHOST_FORMAT_STAGE;
  uint32_t sum = 0;
  for (size_t i = 0; i < size - 4u; ++i) sum += data[i];
  if (sum != le32(data + size - 4u)) return GHOST_FORMAT_CHECKSUM;
  uint32_t ordered[GHOST_MAX_AREAS];
  for (uint32_t i = 0; i < areas; ++i) {
    uint32_t area = ordered[i] = le32(data + 8u + 4u * i);
    if (!policy->area_allowed(area, policy->context)) return GHOST_FORMAT_AREA;
    if (!policy->area_sequence_allowed)
      for (uint32_t j = 0; j < i; ++j)
        if (area == ordered[j]) return GHOST_FORMAT_AREA;
  }
  if (policy->area_sequence_allowed &&
      !policy->area_sequence_allowed(ordered, areas, policy->context)) return GHOST_FORMAT_AREA;
  /* Original Save transposes all sample byte columns, then differences the
   * ENTIRE byte stream backwards (not independently within each column).
   * Load prefix-sums that stream before transposing back. */
  unsigned char *decoded = malloc(sample_bytes);
  if (!decoded) return GHOST_FORMAT_MEMORY;
  unsigned char previous = 0;
  for (size_t i = 0; i < sample_bytes; ++i) {
    previous = (unsigned char)(previous + data[payload + i]);
    decoded[i] = previous;
  }
  ghost_format_result result = GHOST_FORMAT_OK;
  float first = 0, last = 0;
  for (uint32_t i = 0; i < count; ++i) {
    unsigned char sample[GHOST_SAMPLE_BYTES];
    for (size_t column = 0; column < GHOST_SAMPLE_BYTES; ++column)
      sample[column] = decoded[column * count + i];
    static const unsigned float_offsets[] = {0, 4, 8, 12, 32, 36, 40};
    for (size_t k = 0; k < sizeof float_offsets / sizeof *float_offsets; ++k) {
      float value = float32(sample + float_offsets[k]);
      if (!isfinite(value) || fabsf(value) > 1.0e9f) result = GHOST_FORMAT_SAMPLE;
    }
    /* The reviewed CMachine getter initializes the native short-rotation
     * descriptor to kind 4. Other variants are unsupported, not guessed. */
    if (le32(sample + 24) != 4u) result = GHOST_FORMAT_SAMPLE;
    if (!contains_area(data, areas, le32(sample + 28))) result = GHOST_FORMAT_AREA;
    float odo = float32(sample);
    if (!i) first = odo;
    last = odo;
    if (result != GHOST_FORMAT_OK) break;
  }
  free(decoded);
  if (result != GHOST_FORMAT_OK) return result;
  *info = (ghost_format_info){GHOST_NATIVE_VERSION, stage, seed, step, count, areas,
                              size, payload, first, last};
  return GHOST_FORMAT_OK;
}

const char *ghost_format_error(ghost_format_result result) {
  static const char *const names[] = {
    "ok", "invalid argument", "unsupported native version", "invalid exact length",
    "native trail limit", "checksum mismatch", "stage mismatch", "unknown or duplicate area",
    "invalid native sample", "allocation failed"
  };
  return (unsigned)result < sizeof names / sizeof *names ? names[result] : "unknown error";
}
