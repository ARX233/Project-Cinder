#include "rc_runtime.h"
#include "../ghost_runtime.h"
#ifdef WMMT_DEBUG_LOG
#include "../debug_log.h"
#endif

#include <stdio.h>
#include <stdlib.h>

rc_cpu_t rc_cpu;
fpt rc_fst[8];
int rc_ftop, rc_fc0, rc_fc2, rc_fc3;
uint8_t *rc_mem;
uint8_t rc_low[0x10000];
uint32_t rc_heap_next = RC_HEAP_BASE;
uint32_t rc_rand_seed;
void (*rc_on_hook)(uint32_t at);
int (*rc_on_other_setup)(uint32_t slot, uint32_t car_type);
void (*rc_on_other_free)(uint32_t slot);
uint32_t rc_link_pcb, rc_link_tx, rc_link_rx;
void (*rc_on_link_receive)(void);
void (*rc_on_link_send)(void);
#ifdef RC_TRACE
FILE *rc_trace;
#endif

void rc_fail(const char *msg) {
  fprintf(stderr, "rc: %s\n", msg);
#ifdef WMMT_DEBUG_LOG
  debug_log_before_abort(0); /* best-effort only; never log arbitrary text */
#endif
  abort();
}

void rc_fail_addr(const char *msg, uint32_t a) {
  fprintf(stderr, "rc: %s %#x\n", msg, a);
#ifdef WMMT_DEBUG_LOG
  debug_log_before_abort(a); /* emulated address, not a host pointer */
#endif
  abort();
}

uint8_t *rc_va_slow(uint32_t a) {
  if (a < sizeof rc_low) return rc_low + a;
  rc_fail_addr("bad address", a);
}

void rc_unknown(const char *name) {
  fprintf(stderr, "rc: unimplemented import %s\n", name);
}

uint32_t rc_alloc(uint32_t n) {
  uint32_t p = (rc_heap_next + 15) & ~15u;
  if (n == 0) n = 1;
  if (p + n - RC_HEAP_BASE > RC_HEAP_SIZE) rc_fail("heap exhausted");
  rc_heap_next = p + n;
  memset(VA(p), 0, n);
  return p;
}

void rc_reset_heap(void) { rc_heap_next = RC_HEAP_BASE; }

const char *rc_config_dir;
static int rc_space_c(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f'; }
static FILE *rc_files[4];

uint32_t rc_fopen(uint32_t path) {
  /* data/carconfig (the loaders) and data/rtmovie (the realtime movies), under rc_config_dir */
  static const char *const prefix[] = { "data/carconfig/", "data/rtmovie/" };
  const char *p = (const char *)VA(path), *rest = NULL;
  for (int k = 0; k < 2 && !rest; ++k) {
    int i = 0;
    while (prefix[k][i] && p[i] == prefix[k][i]) i++;
    if (!prefix[k][i]) rest = p + 5; /* past "data/" */
  }
  if (!rest || !rc_config_dir) return 0;
  char full[1200];
  snprintf(full, sizeof full, "%s/%s", rc_config_dir, rest);
  for (uint32_t k = 0; k < 4; ++k)
    if (!rc_files[k]) {
      rc_files[k] = fopen(full, "rb");
      if (getenv("RC_TRACE_FILES")) fprintf(stderr, "rc_fopen %s: %s\n", full, rc_files[k] ? "ok" : "missing");
      return rc_files[k] ? k + 1 : 0;
    }
  return 0;
}

static FILE *rc_file(uint32_t f) { return f >= 1 && f <= 4 ? rc_files[f - 1] : NULL; }

static int ghost_span(uint32_t address, size_t length) {
  return rc_mem && address >= RC_MEM_BASE && length <= RC_MEM_SIZE &&
         address - RC_MEM_BASE <= RC_MEM_SIZE - length;
}
static int ghost_literal(uint32_t address, const char *literal) {
  size_t length = strlen(literal) + 1u;
  return ghost_span(address, length) && !memcmp(VA(address), literal, length);
}
uint32_t rc_ghost_fopen(uint32_t path, uint32_t mode) {
  if (ghost_literal(path, GHOST_INPUT_TOKEN)) {
    if (!ghost_literal(mode, "rb") && !ghost_literal(mode, "r")) return 0;
    return ghost_runtime_open(0);
  }
  if (ghost_literal(path, GHOST_OUTPUT_TOKEN)) {
    if (!ghost_literal(mode, "wb") && !ghost_literal(mode, "w")) return 0;
    return ghost_runtime_open(1);
  }
  /* Not a Ghost capability: preserve the exact original read-only bridge. */
  return rc_fopen(path);
}
uint32_t rc_ghost_fread(uint32_t buf, uint32_t size, uint32_t n, uint32_t f) {
  if (!ghost_runtime_is_handle(f)) return rc_fread(buf, size, n, f);
  if (!size || !n || (uint64_t)size * n > RC_MEM_SIZE ||
      !ghost_span(buf, (size_t)size * n)) return 0;
  return (uint32_t)ghost_runtime_read(f, VA(buf), size, n);
}
uint32_t rc_ghost_fwrite(uint32_t buf, uint32_t size, uint32_t n, uint32_t f) {
  /* No ordinary FILE handle can ever be written through this bridge. */
  if (f != GHOST_OUTPUT_HANDLE || !size || !n || (uint64_t)size * n > RC_MEM_SIZE ||
      !ghost_span(buf, (size_t)size * n)) return 0;
  return (uint32_t)ghost_runtime_write(f, VA(buf), size, n);
}
void rc_ghost_fclose(uint32_t f) {
  if (ghost_runtime_is_handle(f)) ghost_runtime_close(f); else rc_fclose(f);
}
uint32_t rc_ghost_feof(uint32_t f) {
  return ghost_runtime_is_handle(f) ? (uint32_t)ghost_runtime_eof(f) : rc_feof(f);
}
int rc_ghost_recording_enabled(void) { return ghost_runtime_recording(); }

uint32_t rc_fread(uint32_t buf, uint32_t size, uint32_t n, uint32_t f) {
  FILE *fp = rc_file(f);
  if (!fp || !size || !n) return 0;
  return (uint32_t)fread(VA(buf), size, n, fp);
}

uint32_t rc_feof(uint32_t f) {
  FILE *fp = rc_file(f);
  return !fp || feof(fp) ? 1 : 0;
}

uint32_t rc_fscanf(uint32_t f, uint32_t fmt, uint32_t args) {
  FILE *fp = rc_file(f);
  const char *q = (const char *)VA(fmt);
  uint32_t n = 0;
  if (!fp) return 0xffffffffu;
  while (*q) {
    if (rc_space_c(*q)) {
      if (fscanf(fp, " ") < 0) return n ? n : 0xffffffffu;
      q++;
      continue;
    }
    if (*q != '%') {
      int c = fgetc(fp);
      if (c != *q) {
        if (c != EOF) ungetc(c, fp);
        break;
      }
      q++;
      continue;
    }
    char conv = q[1];
    uint32_t dst = M32(args + 4 * n);
    int r;
    q += 2;
    if (conv == 'd') {
      int v;
      r = fscanf(fp, "%d", &v);
      if (r == 1) W32(dst, (uint32_t)v);
    } else if (conv == 'f') {
      float v;
      r = fscanf(fp, "%f", &v);
      if (r == 1) WF(dst, v);
    } else if (conv == 's') {
      char w[512];
      r = fscanf(fp, "%511s", w);
      if (r == 1) strcpy((char *)VA(dst), w);
    } else if (conv == 'c') {
      int c = fgetc(fp);
      r = c == EOF ? EOF : 1;
      if (r == 1) *(uint8_t *)VA(dst) = (uint8_t)c;
    } else {
      rc_fail("fscanf conversion");
    }
    if (r != 1) return n ? n : r == EOF ? 0xffffffffu : 0;
    n++;
  }
  return n;
}

uint32_t rc_sprintf(uint32_t buf, uint32_t fmt, uint32_t args) {
  /* the movies' file names: %d (with flags and width), %s, %f */
  const char *q = (const char *)VA(fmt);
  char out[1024], spec[16];
  size_t o = 0;
  while (*q && o < sizeof out - 64) {
    if (*q != '%') {
      out[o++] = *q++;
      continue;
    }
    size_t k = 0;
    spec[k++] = *q++;
    while (((*q >= '0' && *q <= '9') || *q == '.' || *q == '-' || *q == '+' || *q == ' ') && k < sizeof spec - 2)
      spec[k++] = *q++;
    char conv = *q++;
    spec[k++] = conv;
    spec[k] = 0;
    if (conv == 'd' || conv == 'i' || conv == 'x' || conv == 'u' || conv == 'c') {
      o += (size_t)snprintf(out + o, sizeof out - o, spec, (int)M32(args));
      args += 4;
    } else if (conv == 's') {
      o += (size_t)snprintf(out + o, sizeof out - o, spec, (const char *)VA(M32(args)));
      args += 4;
    } else if (conv == 'f') {
      double v;
      memcpy(&v, VA(args), 8);
      o += (size_t)snprintf(out + o, sizeof out - o, spec, v);
      args += 8;
    } else if (conv == '%') {
      out[o++] = '%';
    } else {
      rc_fail("sprintf conversion");
    }
    if (o > sizeof out - 64) o = sizeof out - 64;
  }
  out[o] = 0;
  memcpy(VA(buf), out, o + 1);
  return (uint32_t)o;
}

uint32_t rc_fgets(uint32_t buf, uint32_t n, uint32_t f) {
  if (f < 1 || f > 4 || !rc_files[f - 1]) return 0;
  return fgets((char *)VA(buf), (int)n, rc_files[f - 1]) ? buf : 0;
}

void rc_fclose(uint32_t f) {
  if (f < 1 || f > 4 || !rc_files[f - 1]) return;
  fclose(rc_files[f - 1]);
  rc_files[f - 1] = NULL;
}

uint32_t rc_strstr(uint32_t s, uint32_t find) {
  const char *h = (const char *)VA(s), *n = (const char *)VA(find);
  for (uint32_t i = 0; h[i]; ++i) {
    uint32_t k = 0;
    while (n[k] && h[i + k] == n[k]) k++;
    if (!n[k]) return s + i;
  }
  return n[0] ? 0 : s;
}

uint32_t rc_strcat(uint32_t dst, uint32_t src) {
  char *d = (char *)VA(dst);
  const char *p = (const char *)VA(src);
  while (*d) d++;
  while ((*d++ = *p++)) {}
  return dst;
}

static int rc_space(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' || c == '\f'; }

uint32_t rc_sscanf(uint32_t s, uint32_t fmt, uint32_t args) {
  const char *p = (const char *)VA(s), *f = (const char *)VA(fmt);
  uint32_t n = 0;
  while (*f) {
    if (*f != '%') {
      if (rc_space(*f)) {
        while (rc_space(*p)) p++;
      } else if (*p++ != *f) {
        break;
      }
      f++;
      continue;
    }
    char conv = f[1];
    f += 2;
    while (rc_space(*p)) p++;
    if (!*p) return n ? n : 0xffffffffu; /* EOF before the first conversion */
    uint32_t dst = M32(args + 4 * n);
    int used = 0;
    if (conv == 'd') {
      int v;
      if (sscanf(p, "%d%n", &v, &used) != 1) break;
      W32(dst, (uint32_t)v);
    } else if (conv == 'f') {
      float v;
      if (sscanf(p, "%f%n", &v, &used) != 1) break;
      WF(dst, v);
    } else if (conv == 's') {
      char *d = (char *)VA(dst);
      while (p[used] && !rc_space(p[used])) d[used] = p[used], used++;
      d[used] = 0;
    } else {
      rc_fail("sscanf conversion");
    }
    p += used;
    n++;
  }
  return n;
}

int rc_strcmp(const char *a, const char *b) {
  while (*a && *a == *b) a++, b++;
  return (unsigned char)*a - (unsigned char)*b;
}

/* std::wstring::compare(const wchar_t *) of libstdc++'s wstring (its characters at the pointer
 * it holds, their count 12 bytes before them; 4-byte wchar_t) */
uint32_t rc_wcompare(uint32_t str, uint32_t s) {
  uint32_t p = M32(str), n = M32(p - 12), on = 0;
  while (M32(s + 4 * on)) on++;
  for (uint32_t i = 0; i < n && i < on; ++i) {
    int32_t a = (int32_t)M32(p + 4 * i), b = (int32_t)M32(s + 4 * i);
    if (a != b) return a < b ? (uint32_t)-1 : 1u;
  }
  return (uint32_t)((int32_t)n - (int32_t)on);
}

uint32_t rc_rand(void) {
  if (!rc_rand_seed) return 12345;
  rc_rand_seed = rc_rand_seed * 1103515245u + 12345u;
  return (rc_rand_seed >> 16) & 0x7fff;
}

int rc_load_image(const char *path) {
  uint32_t n = RC_IMG_END - RC_IMG_BASE;
  FILE *f = fopen(path, "rb");
  if (!f) return -1;
  /* Stage the 6,588,744-byte image before touching the published memory. */
  uint8_t *image = malloc(n);
  if (!image) { fclose(f); return -1; }
  size_t got = fread(image, 1, n, f);
  int failed = got != n || ferror(f);
  fclose(f);
  if (failed) { free(image); return -1; }
  if (!rc_mem) {
    uint8_t *mem = calloc(1, RC_MEM_SIZE);
    if (!mem) { free(image); return -1; }
    memcpy(mem + (RC_IMG_BASE - RC_MEM_BASE), image, n);
    rc_mem = mem;
  } else {
    memcpy(rc_mem + (RC_IMG_BASE - RC_MEM_BASE), image, n);
  }
  free(image);
  return 0;
}
