/* cd ports/android; cc -std=c11 -Wall -Wextra -Werror test/rc_load_image_host_test.c -o /tmp/rc-image-test && /tmp/rc-image-test */
#define _DARWIN_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static int fail_malloc, fail_calloc, fake_error, opens, closes, live;
#define GUARD 32u
static void *guard_alloc(size_t n, int clear) {
  unsigned char *p = malloc(n + 2 * GUARD + sizeof(size_t)); assert(p);
  memcpy(p, &n, sizeof n); memset(p + sizeof n, 0xa7, GUARD);
  memset(p + sizeof n + GUARD, clear ? 0 : 0xc4, n);
  memset(p + sizeof n + GUARD + n, 0xa7, GUARD); ++live;
  return p + sizeof n + GUARD;
}
static void guard_free(void *v) {
  if (!v) return;
  unsigned char *p = (unsigned char *)v - GUARD - sizeof(size_t);
  size_t n; memcpy(&n, p, sizeof n);
  for (size_t i = 0; i < GUARD; ++i) {
    assert(p[sizeof n + i] == 0xa7); assert(p[sizeof n + GUARD + n + i] == 0xa7);
  }
  --live; free(p);
}
static void *mock_malloc(size_t n) { return fail_malloc ? NULL : guard_alloc(n, 0); }
static void *mock_calloc(size_t n, size_t s) { return fail_calloc ? NULL : guard_alloc(n * s, 1); }
static FILE *mock_fopen(const char *p, const char *m) { FILE *f = fopen(p, m); if (f) ++opens; return f; }
static int mock_fclose(FILE *f) { ++closes; return fclose(f); }
static int mock_ferror(FILE *f) { return fake_error || ferror(f); }
#define malloc mock_malloc
#define calloc mock_calloc
#define free guard_free
#define fopen mock_fopen
#define fclose mock_fclose
#define ferror mock_ferror
#include "../src/phys/rc_runtime.c"
#undef malloc
#undef calloc
#undef free
#undef fopen
#undef fclose
#undef ferror
static void create_image(const char *path, size_t n) {
  FILE *f = fopen(path, "wb"); assert(f);
  for (size_t i = 0; i < n; ++i) assert(fputc((int)((i * 17u + 5u) & 255u), f) != EOF);
  assert(fclose(f) == 0);
}
static void check_image(void) {
  const size_t offset = RC_IMG_BASE - RC_MEM_BASE, n = RC_IMG_END - RC_IMG_BASE;
  for (size_t i = 0; i < n; ++i) assert(rc_mem[offset + i] == (unsigned char)((i * 17u + 5u) & 255u));
}
static void unchanged(const char *path, uint8_t *old, const uint8_t *snapshot) {
  assert(rc_load_image(path) == -1); assert(rc_mem == old);
  if (old) assert(memcmp(old, snapshot, RC_MEM_SIZE) == 0);
  assert(opens == closes && live == (old != NULL));
  assert(rc_heap_next == 0x12345678u && rc_rand_seed == 0x87654321u);
  for (size_t i = 0; i < sizeof rc_low; ++i) assert(rc_low[i] == 0x71);
}
int main(void) {
  char dir[] = "/tmp/rc-image-test-XXXXXX", full[256], shortfile[256], missing[256];
  assert(mkdtemp(dir));
  assert(snprintf(full, sizeof full, "%s/full", dir) > 0);
  assert(snprintf(shortfile, sizeof shortfile, "%s/short", dir) > 0);
  assert(snprintf(missing, sizeof missing, "%s/missing", dir) > 0);
  size_t n = RC_IMG_END - RC_IMG_BASE, off = RC_IMG_BASE - RC_MEM_BASE;
  create_image(full, n + 23); create_image(shortfile, n - 1);
  memset(rc_low, 0x71, sizeof rc_low); rc_heap_next = 0x12345678u; rc_rand_seed = 0x87654321u;
  unchanged(missing, NULL, NULL); unchanged(shortfile, NULL, NULL);
  /* car_title_list uses this same guard: a failed first attempt must retry. */
  assert(!rc_mem && rc_load_image(shortfile) == -1 && !rc_mem);
  assert(opens == closes && live == 0);
  fail_malloc = 1; unchanged(full, NULL, NULL); fail_malloc = 0;
  fail_calloc = 1; unchanged(full, NULL, NULL); fail_calloc = 0;
  fake_error = 1; unchanged(full, NULL, NULL); fake_error = 0;
  assert(rc_load_image(full) == 0 && rc_mem && live == 1 && opens == closes); check_image();
  for (size_t i = 0; i < off; ++i) assert(rc_mem[i] == 0);
  for (size_t i = off + n; i < RC_MEM_SIZE; ++i) assert(rc_mem[i] == 0);
  memset(rc_mem, 0x53, off);
  memset(rc_mem + off + n, 0x53, RC_MEM_SIZE - off - n);
  for (size_t i = 0; i < n; ++i) rc_mem[off + i] ^= 0xff;
  uint8_t *old = rc_mem, *snapshot = malloc(RC_MEM_SIZE); assert(snapshot); memcpy(snapshot, old, RC_MEM_SIZE);
  unchanged(missing, old, snapshot); unchanged(shortfile, old, snapshot);
  fail_malloc = 1; unchanged(full, old, snapshot); fail_malloc = 0;
  fake_error = 1; unchanged(full, old, snapshot); fake_error = 0;
  fail_calloc = 1; /* Existing image must not allocate a backing buffer. */
  assert(rc_load_image(full) == 0 && rc_mem == old && opens == closes && live == 1);
  fail_calloc = 0; check_image();
  assert(memcmp(old, snapshot, off) == 0);
  assert(memcmp(old + off + n, snapshot + off + n, RC_MEM_SIZE - off - n) == 0);
  assert(rc_heap_next == 0x12345678u && rc_rand_seed == 0x87654321u);
  for (size_t i = 0; i < sizeof rc_low; ++i) assert(rc_low[i] == 0x71);
  free(snapshot); guard_free(rc_mem); rc_mem = NULL; assert(!live);
  assert(unlink(full) == 0 && unlink(shortfile) == 0 && rmdir(dir) == 0);
  puts("rc_load_image host tests passed"); return 0;
}
