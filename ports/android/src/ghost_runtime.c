#include "ghost_runtime.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  unsigned char *input, *output;
  size_t input_size, input_at, output_size;
  int active, started, record, input_open, output_open, output_closed, output_failed;
  ghost_format_policy policy;
  ghost_format_info input_info;
} ghost_stream_state;
static ghost_stream_state S;

static void write_le32(unsigned char *p, uint32_t word) {
  for (unsigned b = 0; b < 4; ++b) p[b] = (unsigned char)(word >> (8u * b));
}
static float sample_float(const unsigned char *p) {
  uint32_t word = (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
  float value;
  memcpy(&value, &word, sizeof value);
  return value;
}
void ghost_runtime_extend_crown(float goal_mm, uint32_t ticks) {
  if (!S.input || S.started) return;
  const ghost_format_info *info = &S.input_info;
  const uint32_t count = info->samples, step = info->sample_step;
  /* A recording that already reaches 30 m past the line has a usable runout. */
  if (!isfinite(goal_mm) || info->last_odometer < goal_mm || info->last_odometer - goal_mm >= 30000.0f) return;
  uint32_t extra = ticks / step;
  uint32_t limit = S.policy.max_samples ? S.policy.max_samples : GHOST_MAX_SAMPLES;
  uint32_t tick_limit = S.policy.max_ticks ? S.policy.max_ticks : GHOST_MAX_TICKS;
  if (limit > 1u + tick_limit / step) limit = 1u + tick_limit / step;
  if (extra > limit - count) extra = limit - count;
  if (!extra) return;

  const size_t payload = info->payload_offset;
  const unsigned char *from = S.input + payload;
  unsigned char last[GHOST_SAMPLE_BYTES], previous[GHOST_SAMPLE_BYTES], value = 0;
  for (uint32_t col = 0; col < GHOST_SAMPLE_BYTES; ++col) {
    for (uint32_t i = 0; i + 1u < count; ++i) value += *from++;
    previous[col] = value;
    value += *from++;
    last[col] = value;
  }
  /* Odometer and native velocity are in mm and mm/s. Keep the recorded lane,
   * pose and road reference, but clear the collision cues on the added samples. */
  float seconds = (float)step / 60.0f;
  float maximum = 125000.0f * seconds; /* 450 km/h cap for extrapolated motion */
  float delta = info->last_odometer - sample_float(previous);
  if (delta <= 0.0f || delta > maximum) delta = sample_float(last + 12) * seconds;
  if (delta <= 0.0f || delta > maximum) return;
  memset(last + 36, 0, GHOST_SAMPLE_BYTES - 36);
  size_t bytes = S.input_size + (size_t)extra * GHOST_SAMPLE_BYTES;
  unsigned char *extended = malloc(bytes);
  if (!extended) return;
  memcpy(extended, S.input, payload);
  write_le32(extended + payload - 4, count + extra);
  unsigned char *to = extended + payload, old_value = 0, new_value = 0;
  from = S.input + payload;
  for (uint32_t col = 0; col < GHOST_SAMPLE_BYTES; ++col) {
    for (uint32_t i = 0; i < count; ++i) {
      old_value += *from++;
      *to++ = (unsigned char)(old_value - new_value);
      new_value = old_value;
    }
    for (uint32_t i = 1; i <= extra; ++i) {
      if (col < 4) {
        float odo = info->last_odometer + delta * (float)i;
        uint32_t bits;
        memcpy(&bits, &odo, sizeof bits);
        value = (unsigned char)(bits >> (8u * col));
      } else value = last[col];
      *to++ = (unsigned char)(value - new_value);
      new_value = value;
    }
  }
  uint32_t checksum = 0;
  for (size_t i = 0; i < bytes - 4u; ++i) checksum += extended[i];
  write_le32(to, checksum);
  ghost_format_info checked;
  if (ghost_format_validate(extended, bytes, &S.policy, &checked) == GHOST_FORMAT_OK) {
    free(S.input);
    S.input = extended;
    S.input_size = bytes;
    S.input_info = checked;
  } else free(extended);
}

void ghost_runtime_clear(void) {
  free(S.input);
  free(S.output);
  memset(&S, 0, sizeof S);
}
ghost_format_result ghost_runtime_prepare(const void *data, size_t size,
                                          const ghost_format_policy *policy) {
  ghost_runtime_clear();
  ghost_format_info info;
  ghost_format_result result = ghost_format_validate(data, size, policy, &info);
  if (result != GHOST_FORMAT_OK) return result;
  S.input = malloc(size);
  if (!S.input) return GHOST_FORMAT_MEMORY;
  memcpy(S.input, data, size);
  S.input_size = size;
  S.input_info = info;
  S.policy = *policy;
  return GHOST_FORMAT_OK;
}
static int start(int record) {
  if (S.active || S.started) return 0;
  if (record) {
    S.output = malloc(GHOST_MAX_BYTES);
    if (!S.output) return 0;
  }
  S.active = S.started = 1;
  S.record = !!record;
  return 1;
}
int ghost_runtime_begin(int record) {
  return S.input && (record == 0 || record == 1) && start(record);
}
int ghost_runtime_begin_qualification(const ghost_format_policy *policy) {
  ghost_format_policy copy;
  if (policy) copy = *policy; else memset(&copy, 0, sizeof copy);
  ghost_runtime_clear();
  if (!policy || !copy.area_allowed || copy.max_samples > GHOST_MAX_SAMPLES) return 0;
  S.policy = copy;
  return start(1);
}
void ghost_runtime_stop(void) {
  S.active = S.record = S.input_open = S.output_open = 0;
}
void ghost_runtime_discard_recording(void) {
  free(S.output);
  S.output = NULL;
  S.output_size = 0;
  S.record = S.output_open = S.output_closed = S.output_failed = 0;
}
int ghost_runtime_active(void) { return S.active; }
int ghost_runtime_recording(void) { return S.active && S.record; }
const ghost_format_info *ghost_runtime_input_info(void) { return S.input ? &S.input_info : NULL; }
int ghost_runtime_input_area(uint32_t index, uint32_t *area) {
  if (area) *area = 0;
  if (!area || !S.input || index >= S.input_info.areas) return 0;
  const unsigned char *p = S.input + 8u + 4u * index;
  *area = (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
  return 1;
}
int ghost_runtime_is_handle(uint32_t handle) {
  return handle == GHOST_INPUT_HANDLE || handle == GHOST_OUTPUT_HANDLE;
}
uint32_t ghost_runtime_open(int output) {
  if (!S.active) return 0;
  if (output) {
    if (!S.record || !S.output || S.output_open || S.output_closed || S.output_failed) return 0;
    S.output_size = 0;
    S.output_open = 1;
    return GHOST_OUTPUT_HANDLE;
  }
  if (!S.input || S.input_open) return 0;
  S.input_at = 0;
  S.input_open = 1;
  return GHOST_INPUT_HANDLE;
}
size_t ghost_runtime_read(uint32_t handle, void *output, size_t size, size_t count) {
  if (handle != GHOST_INPUT_HANDLE || !S.active || !S.input_open || !output || !size || !count ||
      count > SIZE_MAX / size) return 0;
  size_t available = (S.input_size - S.input_at) / size;
  if (count > available) count = available;
  size_t bytes = size * count;
  memcpy(output, S.input + S.input_at, bytes);
  S.input_at += bytes;
  return count;
}
size_t ghost_runtime_write(uint32_t handle, const void *input, size_t size, size_t count) {
  if (handle != GHOST_OUTPUT_HANDLE || !S.active || !S.record || !S.output_open ||
      S.output_failed || !input || !size || !count) return 0;
  if (count > SIZE_MAX / size || size * count > GHOST_MAX_BYTES - S.output_size) {
    S.output_failed = 1;
    return 0;
  }
  size_t bytes = size * count;
  memcpy(S.output + S.output_size, input, bytes);
  S.output_size += bytes;
  return count;
}
void ghost_runtime_close(uint32_t handle) {
  if (handle == GHOST_INPUT_HANDLE) S.input_open = 0;
  if (handle == GHOST_OUTPUT_HANDLE && S.output_open) {
    S.output_open = 0;
    S.output_closed = 1;
  }
}
int ghost_runtime_eof(uint32_t handle) {
  return handle != GHOST_INPUT_HANDLE || !S.input_open || S.input_at == S.input_size;
}
int ghost_runtime_export(void *output, size_t capacity, size_t *bytes, ghost_format_info *info) {
  if (bytes) *bytes = 0;
  if (info) memset(info, 0, sizeof *info);
  if (!bytes || !S.output || !S.output_closed || S.output_open || S.output_failed) return 0;
  ghost_format_info checked;
  if (ghost_format_validate(S.output, S.output_size, &S.policy, &checked) != GHOST_FORMAT_OK) return 0;
  *bytes = S.output_size;
  if (output && capacity < S.output_size) return 0;
  if (output) memcpy(output, S.output, S.output_size);
  if (info) *info = checked;
  return 1;
}
