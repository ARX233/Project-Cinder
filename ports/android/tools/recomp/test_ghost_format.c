/* Public synthetic fixtures only: no original frame tables, trails or assets. */
#include "../../src/ghost_format.h"
#include "../../src/ghost_runtime.h"
#include "../../src/phys/rc_runtime.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void put32(unsigned char *p, uint32_t v) {
  p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8);
  p[2] = (unsigned char)(v >> 16); p[3] = (unsigned char)(v >> 24);
}
static void putf(unsigned char *p, float v) { uint32_t w; memcpy(&w, &v, 4); put32(p, w); }
static void checksum(unsigned char *p, size_t n) {
  uint32_t sum = 0; for (size_t i = 0; i < n - 4; ++i) sum += p[i]; put32(p + n - 4, sum);
}
static size_t fixture(unsigned char *p, int bad_float, int bad_area, int bad_rotation) {
  unsigned char rows[2][48] = {{0}};
  memset(p, 0, 128);
  put32(p, GHOST_NATIVE_VERSION); put32(p + 4, 1); put32(p + 8, 7);
  put32(p + 12, 123); put32(p + 16, 42); put32(p + 20, 3); put32(p + 24, 2);
  for (int i = 0; i < 2; ++i) {
    putf(rows[i], (float)(1000 + i * 2000));
    putf(rows[i] + 4, 125); putf(rows[i] + 12, 25000);
    put32(rows[i] + 24, bad_rotation ? 5u : 4u);
    put32(rows[i] + 28, bad_area ? 8u : 7u);
  }
  if (bad_float) put32(rows[1], UINT32_C(0x7fc00000));
  for (size_t col = 0; col < 48; ++col)
    for (size_t i = 0; i < 2; ++i) p[28 + col * 2 + i] = rows[i][col];
  for (size_t i = 95; i; --i) p[28 + i] = (unsigned char)(p[28 + i] - p[28 + i - 1]);
  checksum(p, 128);
  return 128;
}
static int area(uint32_t id, void *ctx) { (void)ctx; return id == 7; }

static void crown_runout(const unsigned char *original, size_t n, const ghost_format_policy *policy) {
  enum { EXTRA = 30, SAMPLES = 2 + EXTRA };
  unsigned char playback[128 + EXTRA * GHOST_SAMPLE_BYTES];
  assert(ghost_runtime_prepare(original, n, policy) == GHOST_FORMAT_OK);
  ghost_runtime_extend_crown(3000.0f, 90);
  assert(ghost_runtime_begin(0) && ghost_runtime_open(0) == GHOST_INPUT_HANDLE);
  assert(ghost_runtime_read(GHOST_INPUT_HANDLE, playback, 1, sizeof playback) == sizeof playback);
  ghost_format_info info;
  assert(ghost_format_validate(playback, sizeof playback, policy, &info) == GHOST_FORMAT_OK);
  assert(info.samples == SAMPLES && info.first_odometer == 1000.0f && info.last_odometer == 63000.0f);
  unsigned char old_byte = 0, new_byte = 0;
  for (size_t col = 0; col < GHOST_SAMPLE_BYTES; ++col) {
    for (size_t i = 0; i < SAMPLES; ++i) {
      new_byte += playback[info.payload_offset + col * SAMPLES + i];
      if (i < 2) {
        old_byte += original[info.payload_offset + col * 2 + i];
        assert(new_byte == old_byte);
      }
    }
  }
  ghost_runtime_clear();
  assert(ghost_runtime_prepare(original, n, policy) == GHOST_FORMAT_OK);
  ghost_runtime_extend_crown(-30000.0f, 90); /* already has a tail */
  assert(ghost_runtime_input_info()->samples == 2);
  ghost_runtime_clear();
}

int main(void) {
  unsigned char p[256], original[128], readback[128], exported[128];
  ghost_format_info info;
  ghost_format_policy policy = {.stage=123, .area_allowed=area};
  size_t n = fixture(p, 0, 0, 0), size = 0;
  memcpy(original, p, n);
  assert(ghost_format_validate(p, n, &policy, &info) == GHOST_FORMAT_OK);
  assert(info.samples == 2 && info.sample_step == 3 && info.first_odometer == 1000 && info.last_odometer == 3000);
  crown_runout(original, n, &policy);
  assert(ghost_format_validate(NULL, n, &policy, &info) == GHOST_FORMAT_ARGUMENT && info.samples == 0);
  assert(ghost_format_validate(p, n - 1, &policy, &info) == GHOST_FORMAT_LENGTH);
  assert(ghost_format_validate(p, n + 1, &policy, &info) == GHOST_FORMAT_LENGTH);
  p[0] ^= 1; assert(ghost_format_validate(p, n, &policy, &info) == GHOST_FORMAT_VERSION); p[0] ^= 1;
  p[40] ^= 1; assert(ghost_format_validate(p, n, &policy, &info) == GHOST_FORMAT_CHECKSUM); p[40] ^= 1;
  put32(p + 20, 0); checksum(p, n); assert(ghost_format_validate(p, n, &policy, &info) == GHOST_FORMAT_LIMIT);
  fixture(p, 0, 0, 0); put32(p + 24, UINT32_MAX); checksum(p, n);
  assert(ghost_format_validate(p, n, &policy, &info) == GHOST_FORMAT_LIMIT);
  fixture(p, 1, 0, 0); assert(ghost_format_validate(p, n, &policy, &info) == GHOST_FORMAT_SAMPLE);
  fixture(p, 0, 1, 0); assert(ghost_format_validate(p, n, &policy, &info) == GHOST_FORMAT_AREA);
  fixture(p, 0, 0, 1); assert(ghost_format_validate(p, n, &policy, &info) == GHOST_FORMAT_SAMPLE);
  fixture(p, 0, 0, 0); policy.stage = 124;
  assert(ghost_format_validate(p, n, &policy, &info) == GHOST_FORMAT_STAGE); policy.stage = 123;
  unsigned char duplicate[132];
  memcpy(duplicate,p,8); put32(duplicate+4,2); put32(duplicate+8,7); put32(duplicate+12,7);
  memcpy(duplicate+16,p+12,116); checksum(duplicate,sizeof duplicate);
  assert(ghost_format_validate(duplicate,sizeof duplicate,&policy,&info)==GHOST_FORMAT_AREA);
  assert(!ghost_runtime_recording() && !ghost_runtime_open(0) && !ghost_runtime_open(1));
  assert(ghost_runtime_prepare(p, n, &policy) == GHOST_FORMAT_OK);
  p[0] ^= 1; /* runtime must own a validated immutable copy */
  assert(!ghost_runtime_begin(-1) && !ghost_runtime_recording());
  assert(ghost_runtime_begin(0) && !ghost_runtime_recording());
  assert(ghost_runtime_open(0) == GHOST_INPUT_HANDLE);
  assert(ghost_runtime_read(GHOST_INPUT_HANDLE, readback, 1, 128) == 128);
  assert(!memcmp(readback, original, 128) && ghost_runtime_eof(GHOST_INPUT_HANDLE));
  assert(!ghost_runtime_open(1)); ghost_runtime_close(GHOST_INPUT_HANDLE);
  ghost_runtime_stop(); assert(!ghost_runtime_begin(1));
  fixture(p, 0, 0, 0); assert(ghost_runtime_prepare(p, n, &policy) == GHOST_FORMAT_OK);
  assert(ghost_runtime_begin(1) && ghost_runtime_recording());
  assert(ghost_runtime_open(1) == GHOST_OUTPUT_HANDLE);
  assert(ghost_runtime_write(GHOST_OUTPUT_HANDLE, original, 1, 128) == 128);
  assert(!ghost_runtime_export(exported, 128, &size, &info));
  ghost_runtime_close(GHOST_OUTPUT_HANDLE); ghost_runtime_stop();
  assert(ghost_runtime_export(NULL, 0, &size, &info) && size == 128);
  assert(!ghost_runtime_export(exported, 127, &size, &info) && size == 128);
  assert(ghost_runtime_export(exported, 128, &size, &info) && !memcmp(exported, original, 128));
  assert(ghost_runtime_begin_qualification(&policy) && ghost_runtime_recording());
  assert(ghost_runtime_open(1) == GHOST_OUTPUT_HANDLE);
  assert(!ghost_runtime_write(GHOST_OUTPUT_HANDLE, p, SIZE_MAX, 2));
  ghost_runtime_close(GHOST_OUTPUT_HANDLE); ghost_runtime_stop();
  assert(!ghost_runtime_export(exported, 128, &size, &info));
  ghost_runtime_clear();
  /* Private PLT bridge cannot write ordinary handles, arbitrary paths, ranges,
   * or a Ghost capability with the wrong fopen mode. */
  rc_mem = calloc(1, RC_MEM_SIZE); assert(rc_mem);
  uint32_t token = RC_HEAP_BASE, mode = token + 64, buf = token + 128;
  memcpy(VA(token), GHOST_OUTPUT_TOKEN, sizeof GHOST_OUTPUT_TOKEN);
  memcpy(VA(mode), "wb", 3);
  assert(ghost_runtime_begin_qualification(&policy));
  memcpy(VA(mode), "rb", 3);
  assert(!rc_ghost_fopen(token, mode));
  memcpy(VA(mode), "wb", 3);
  assert(rc_ghost_fopen(token, mode) == GHOST_OUTPUT_HANDLE);
  assert(!rc_ghost_fread(buf,1,128,GHOST_OUTPUT_HANDLE));
  memcpy(VA(buf), original, 128);
  assert(!rc_ghost_fwrite(buf, 1, 128, 1));
  assert(!rc_ghost_fwrite(RC_STACK_TOP - 1, 1, 128, GHOST_OUTPUT_HANDLE));
  assert(rc_ghost_fwrite(buf, 1, 128, GHOST_OUTPUT_HANDLE) == 128);
  rc_ghost_fclose(GHOST_OUTPUT_HANDLE); ghost_runtime_stop();
  assert(ghost_runtime_export(exported, 128, &size, &info));
  ghost_runtime_clear();
  fixture(p,0,0,0);
  assert(ghost_runtime_prepare(p,n,&policy)==GHOST_FORMAT_OK);
  p[0]=0;
  assert(ghost_runtime_prepare(p,n,&policy)==GHOST_FORMAT_VERSION);
  assert(!ghost_runtime_input_info()&&!ghost_runtime_begin(0)&&!ghost_runtime_open(0));
  fixture(p,0,0,0);
  assert(ghost_runtime_prepare(p,n,&policy)==GHOST_FORMAT_OK&&ghost_runtime_begin(1));
  assert(ghost_runtime_recording());
  assert(!ghost_runtime_begin_qualification(NULL));
  assert(!ghost_runtime_recording()&&!ghost_runtime_input_info());
  ghost_runtime_clear(); free(rc_mem); rc_mem = NULL;
  puts("ghost synthetic format/runtime/opaque bridge tests: PASS");
  return 0;
}
