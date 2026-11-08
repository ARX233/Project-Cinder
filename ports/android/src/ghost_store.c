#if defined(__linux__) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE 1
#endif
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#ifndef _DARWIN_C_SOURCE
#define _DARWIN_C_SOURCE 1
#endif
#include "ghost_store.h"

#include <errno.h>
#include <fcntl.h>
#include <float.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#include <zlib.h>

#if !defined(O_NOFOLLOW) || !defined(O_DIRECTORY) || !defined(AT_SYMLINK_NOFOLLOW)
#error "ghost_store requires no-follow directory-relative POSIX I/O"
#endif
#if FLT_RADIX != 2 || FLT_MANT_DIG != 24 || FLT_MAX_EXP != 128
#error "ghost_store v1 requires IEEE754 binary32 float"
#endif
typedef char ghost_store_float32_required[sizeof(float) == 4 ? 1 : -1];
typedef char ghost_store_unsigned32_required[UINT_MAX >= UINT32_MAX ? 1 : -1];

#define CROWN_HEADER_BYTES 248u
static const unsigned char crown_magic[8] = {'W','3','G','C','R','O','W','N'};
static const unsigned char store_magic[8] = {'W','3','G','L','O','C','A','L'};
#define STORE_PATH_MAX 4096u
#define STORE_COMPONENT_MAX 255u

static uint32_t get32(const unsigned char *p) {
  return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t get64(const unsigned char *p) {
  return (uint64_t)get32(p) | (uint64_t)get32(p + 4) << 32;
}
static void put32(unsigned char *p, uint32_t value) {
  for (unsigned i = 0; i < 4; ++i) p[i] = (unsigned char)(value >> (8u * i));
}
static void put64(unsigned char *p, uint64_t value) {
  put32(p, (uint32_t)value); put32(p + 4, (uint32_t)(value >> 32));
}
static uint32_t float_word(float value) {
  uint32_t word; memcpy(&word, &value, sizeof word); return word;
}
static float word_float(uint32_t word) {
  float value; memcpy(&value, &word, sizeof value); return value;
}
static int physics_id_valid(const char *text) {
  if (!text) return 0;
  for (unsigned i = 0; i < 64; ++i)
    if (!((text[i] >= '0' && text[i] <= '9') || (text[i] >= 'a' && text[i] <= 'f'))) return 0;
  return text[64] == '\0';
}

/* Basic container/sample syntax is deliberately NOT the strict/native area
 * policy. No sample is executed; actual road, route and native readiness remain
 * the caller's ghost_format_validate + car_ghost_prepare responsibility. */
static ghost_store_result basic_trail(const ghost_store_record *record,int profile) {
  if (!record->trail || record->trail_bytes < 28u || record->trail_bytes > GHOST_MAX_BYTES)
    return GHOST_STORE_LENGTH;
  const unsigned char *data = record->trail;
  if (get32(data) != GHOST_NATIVE_VERSION) return GHOST_STORE_VERSION;
  uint32_t areas = get32(data + 4);
  if (!areas || areas > GHOST_MAX_AREAS) return GHOST_STORE_TRAIL;
  size_t header = 8u + (size_t)areas * 4u;
  if (record->trail_bytes < header + 20u) return GHOST_STORE_LENGTH;
  uint32_t stage = get32(data + header), step = get32(data + header + 8u);
  uint32_t samples = get32(data + header + 12u);
  uint32_t max_ticks=profile && record->ramp>CAR_GHOST_TA_RAMP_BASE && stage==GHOST_LONG_TA_STAGE ?
    GHOST_LONG_TA_MAX_TICKS:GHOST_MAX_TICKS;
  if (stage != record->race_field[0] || !step || step > 60u || samples < 2u ||
      samples > GHOST_MAX_SAMPLES || (uint64_t)(samples - 1u) * step > max_ticks)
    return GHOST_STORE_TRAIL;
  if (record->trail_bytes != header + 20u + (size_t)samples * GHOST_SAMPLE_BYTES)
    return GHOST_STORE_LENGTH;
  for (uint32_t i = 0; !profile && i < areas; ++i)
    for (uint32_t j = 0; j < i; ++j)
      if (get32(data + 8u + 4u * i) == get32(data + 8u + 4u * j)) return GHOST_STORE_TRAIL;
  uint32_t sum = 0;
  for (size_t i = 0; i < record->trail_bytes - 4u; ++i) sum += data[i];
  if (sum != get32(data + record->trail_bytes - 4u)) return GHOST_STORE_CHECKSUM;
  /* Syntax-only decoding catches corrupt/non-finite sample words without
   * inventing an allow-all native area policy. Table membership here means
   * membership in the blob itself, NOT acceptance by the actual native road. */
  size_t sample_bytes = (size_t)samples * GHOST_SAMPLE_BYTES;
  unsigned char *decoded = malloc(sample_bytes);
  if (!decoded) return GHOST_STORE_MEMORY;
  unsigned char previous = 0;
  for (size_t i = 0; i < sample_bytes; ++i) {
    previous = (unsigned char)(previous + data[header + 16u + i]);
    decoded[i] = previous;
  }
  ghost_store_result result = GHOST_STORE_OK;
  for (uint32_t i = 0; i < samples && result == GHOST_STORE_OK; ++i) {
    unsigned char sample[GHOST_SAMPLE_BYTES];
    for (size_t column = 0; column < GHOST_SAMPLE_BYTES; ++column)
      sample[column] = decoded[column * samples + i];
    static const unsigned offsets[] = {0, 4, 8, 12, 32, 36, 40};
    for (size_t k = 0; k < sizeof offsets / sizeof *offsets; ++k) {
      float value = word_float(get32(sample + offsets[k]));
      if (!isfinite(value) || fabsf(value) > 1.0e9f) result = GHOST_STORE_TRAIL;
    }
    if (get32(sample + 24) != 4u) result = GHOST_STORE_TRAIL;
    int found = 0;
    for (uint32_t area = 0; area < areas; ++area)
      if (get32(sample + 28) == get32(data + 8u + 4u * area)) found = 1;
    if (!found) result = GHOST_STORE_TRAIL;
  }
  free(decoded);
  return result;
}

static ghost_store_result metadata(const ghost_store_record *record,int profile) {
  if (!record) return GHOST_STORE_ARGUMENT;
  if (!physics_id_valid(record->physics_sha256)) return GHOST_STORE_PHYSICS;
  if (!record->ramp || record->ramp > (unsigned)(profile?CAR_GHOST_TA_RAMP_BASE+CAR_COURSES:CAR_LINK_RAMPS) || record->route > INT32_MAX ||
      record->recorded_at > UINT64_C(253402300799)) return GHOST_STORE_METADATA;
  for (unsigned i = 0; i < 6; ++i)
    if (i != 3u && i != 4u && record->race_field[i] > INT32_MAX) return GHOST_STORE_METADATA;
  float start = word_float(record->race_field[3]), goal = word_float(record->race_field[4]);
  if (!record->race_field[0] || !isfinite(start) || !isfinite(goal) || start < 0 ||
      !(start < goal) || goal > 1.0e9f) return GHOST_STORE_METADATA;
  const car_spec *car = &record->owner;
  /* Only public car.h tune bounds; no guessed maximum private ECarType. */
  if ((uint64_t)car->type > UINT32_MAX || car->gears < 1 || car->gears > 16 ||
      car->spokes < 0 || car->spokes > 65535 || car->power < 0 || car->handling < 0 ||
      car->power > CAR_TUNE_MAX || car->handling > CAR_TUNE_MAX ||
      car->power + car->handling > CAR_TUNE_TOTAL) return GHOST_STORE_METADATA;
  for (unsigned i = 0; i < 6; ++i)
    if (!isfinite(car->tyres[i]) || fabsf(car->tyres[i]) > 1.0e6f) return GHOST_STORE_METADATA;
  if (car->tyres[1] < 1.0f || car->tyres[4] < 1.0f) return GHOST_STORE_METADATA;
  return GHOST_STORE_OK;
}

/* Pin every absolute-path component with O_NOFOLLOW. No directory enumeration,
 * mkdir, saved-file search or arbitrary uploaded leaf name is ever performed. */
static ghost_store_result open_directory(const char *path, int *output) {
  if (!path || path[0] != '/') return GHOST_STORE_UNSAFE_PATH;
  size_t length = strnlen(path, STORE_PATH_MAX + 1u);
  if (!length || length > STORE_PATH_MAX) return GHOST_STORE_UNSAFE_PATH;
  /* Android allows traversal of /data without allowing it to be opened for
   * reading. Only the final directory needs a descriptor for flock and fsync. */
#if defined(O_PATH)
  const int parent_access = O_PATH;
#elif defined(O_SEARCH)
  const int parent_access = O_SEARCH;
#else
  const int parent_access = O_RDONLY;
#endif
  const int directory_flags = O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW;
  int current = open("/", (length > 1 ? parent_access : O_RDONLY) | directory_flags);
  if (current < 0) return GHOST_STORE_IO;
  size_t at = 1;
  while (at < length) {
    size_t start = at;
    while (at < length && path[at] != '/') ++at;
    size_t n = at - start;
    if (!n || n > STORE_COMPONENT_MAX || (n == 1 && path[start] == '.') ||
        (n == 2 && path[start] == '.' && path[start + 1] == '.')) {
      close(current); return GHOST_STORE_UNSAFE_PATH;
    }
    char component[STORE_COMPONENT_MAX + 1u];
    memcpy(component, path + start, n); component[n] = '\0';
    int access = at + 1u < length ? parent_access : O_RDONLY;
    int next = openat(current, component, access | directory_flags);
    int error = errno;
    close(current);
    if (next < 0) return (error == ELOOP || error == ENOTDIR) ? GHOST_STORE_UNSAFE_PATH : GHOST_STORE_IO;
    current = next;
    if (at < length) ++at; /* One trailing slash is harmless; empty interior components are not. */
  }
  *output = current;
  return GHOST_STORE_OK;
}

static ghost_store_result regular_file(int fd, struct stat *st) {
  if (fstat(fd, st) < 0) return GHOST_STORE_IO;
  if (!S_ISREG(st->st_mode) || st->st_nlink != 1) return GHOST_STORE_UNSAFE_PATH;
  return GHOST_STORE_OK;
}
static int read_exact(int fd, unsigned char *data, size_t bytes) {
  size_t used = 0;
  while (used < bytes) {
    ssize_t count = read(fd, data + used, bytes - used);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) return 0;
    used += (size_t)count;
  }
  return 1;
}
static int write_exact(int fd, const unsigned char *data, size_t bytes) {
  size_t used = 0;
  while (used < bytes) {
    ssize_t count = write(fd, data + used, bytes - used);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) return 0;
    used += (size_t)count;
  }
  return 1;
}
static int sync_file(int fd) {
  int result;
  do result = fsync(fd); while (result < 0 && errno == EINTR);
  return result;
}
static uint32_t envelope_crc(const unsigned char *data, size_t bytes) {
  static const unsigned char zero[4]={0};
  uLong value=crc32(crc32(0L,Z_NULL,0),data,24);
  value=crc32(value,zero,sizeof zero);
  return (uint32_t)crc32(value,data+28,(uInt)(bytes-28));
}

static void encode_header(unsigned char *data, const ghost_store_record *record, size_t bytes) {
  memset(data, 0, GHOST_STORE_HEADER_BYTES);
  memcpy(data, store_magic, sizeof store_magic);
  put32(data + 8, GHOST_STORE_ENVELOPE_VERSION); put32(data + 12, GHOST_STORE_HEADER_BYTES);
  put32(data + 16, (uint32_t)record->trail_bytes); put32(data + 20, (uint32_t)bytes);
  put32(data + 32, record->ramp); put32(data + 36, record->route);
  for (unsigned i = 0; i < 6; ++i) put32(data + 40u + 4u * i, record->race_field[i]);
  put32(data + 64, (uint32_t)record->owner.type); put32(data + 68, (uint32_t)record->owner.gears);
  for (unsigned i = 0; i < 6; ++i) put32(data + 72u + 4u * i, float_word(record->owner.tyres[i]));
  put32(data + 96, (uint32_t)record->owner.spokes);
  put32(data + 100, (uint32_t)record->owner.power); put32(data + 104, (uint32_t)record->owner.handling);
  memcpy(data + 108, record->physics_sha256, 64); put64(data + 172, record->recorded_at);
}

static int crown_profile_valid(const ghost_crown_record *c) {
  if (!c->name[0] || c->raw_model>=247u ||
      c->raw_ramp>=CAR_GHOST_TA_RAMP_BASE+CAR_COURSES ||
      (c->raw_ramp>=CAR_GHOST_TA_RAMP_BASE ?
        (c->race.ramp!=c->raw_ramp+1u || c->race.route) : c->race.ramp>CAR_LINK_RAMPS) ||
      c->custom_color>10u ||
      c->aero>3u || c->mirror>4u || c->wing>8u || c->bonnet>4u ||
      (c->wheel>=113u && c->wheel!=143u) || c->neon>64u || c->vinyl>255u ||
      c->title>65535u || c->class_id>255u) return 0;
  int ended=0;
  for (unsigned i=0;i<5;++i) {
    uint16_t ch=c->name[i];
    if ((ended && ch) || (ch>=0xd800u && ch<=0xdfffu)) return 0;
    if (!ch) ended=1;
  }
  return 1;
}

static void encode_crown(unsigned char *data,const ghost_crown_record *c) {
  memcpy(data,crown_magic,8);
  put32(data+12,CROWN_HEADER_BYTES);
  memset(data+184,0,CROWN_HEADER_BYTES-184u);
  const uint32_t profile[]={c->raw_model,c->raw_ramp,c->custom_color,c->aero,c->mirror,
    c->wing,c->bonnet,c->wheel,c->neon,c->vinyl,c->title,c->class_id};
  for (unsigned i=0;i<sizeof profile/sizeof *profile;++i) put32(data+184+4*i,profile[i]);
  for (unsigned i=0;i<5;++i) {
    data[232+2*i]=(unsigned char)c->name[i];
    data[233+2*i]=(unsigned char)(c->name[i]>>8);
  }
}

static int decode_crown(const unsigned char *data,ghost_crown_record *c) {
  uint32_t *profile[]={&c->raw_model,&c->raw_ramp,&c->custom_color,&c->aero,&c->mirror,
    &c->wing,&c->bonnet,&c->wheel,&c->neon,&c->vinyl,&c->title,&c->class_id};
  for (unsigned i=0;i<sizeof profile/sizeof *profile;++i) *profile[i]=get32(data+184+4*i);
  for (unsigned i=0;i<5;++i) c->name[i]=(uint16_t)(data[232+2*i]|(uint16_t)data[233+2*i]<<8);
  for (unsigned i=242;i<CROWN_HEADER_BYTES;++i) if (data[i]) return 0;
  c->revision=(uint64_t)get32(data+24)+1u;
  return crown_profile_valid(c);
}

static ghost_store_result decode(unsigned char *data, size_t bytes,
                                  const char *physics,ghost_store_record *record,ghost_crown_record *crown) {
  size_t header=crown?CROWN_HEADER_BYTES:GHOST_STORE_HEADER_BYTES;
  if (memcmp(data,crown?crown_magic:store_magic,8)) return GHOST_STORE_VERSION;
  if (get32(data + 8) != GHOST_STORE_ENVELOPE_VERSION) return GHOST_STORE_VERSION;
  uint32_t payload = get32(data + 16);
  if (get32(data + 12) != header || payload > GHOST_MAX_BYTES ||
      payload < 28u || get32(data + 20) != bytes ||
      (size_t)payload + header != bytes) return GHOST_STORE_LENGTH;
  if (get32(data + 28) || get32(data + 180)) return GHOST_STORE_VERSION;
  if (get32(data + 24) != envelope_crc(data, bytes)) return GHOST_STORE_CHECKSUM;
  for (unsigned offset = 68; offset <= 104; offset += 4) {
    if (offset >= 72 && offset <= 92) continue;
    if (get32(data + offset) > INT_MAX) return GHOST_STORE_METADATA;
  }
  record->ramp = get32(data + 32); record->route = get32(data + 36);
  for (unsigned i = 0; i < 6; ++i) record->race_field[i] = get32(data + 40u + 4u * i);
  record->owner.type = get32(data + 64); record->owner.gears = (int)get32(data + 68);
  for (unsigned i = 0; i < 6; ++i) record->owner.tyres[i] = word_float(get32(data + 72u + 4u * i));
  record->owner.spokes = (int)get32(data + 96);
  record->owner.power = (int)get32(data + 100); record->owner.handling = (int)get32(data + 104);
  memcpy(record->physics_sha256, data + 108, 64); record->physics_sha256[64] = '\0';
  record->recorded_at = get64(data + 172);
  ghost_store_result result = metadata(record,crown!=NULL);
  if (result != GHOST_STORE_OK) return result;
  if (memcmp(physics, record->physics_sha256, 65)) return GHOST_STORE_PHYSICS;
  if (crown) {
    crown->race=*record;
    if(!decode_crown(data,crown))return GHOST_STORE_METADATA;
  }
  record->trail = data + header; record->trail_bytes = payload;
  result = basic_trail(record,crown!=NULL);
  record->trail = NULL;
  return result;
}

static ghost_store_result load(const char *save_dir,const char *expected,const char *leaf,
                               ghost_store_record *out,ghost_crown_record *crown) {
  size_t header=crown?CROWN_HEADER_BYTES:GHOST_STORE_HEADER_BYTES;
  if (!out || out->trail || !physics_id_valid(expected)) return GHOST_STORE_ARGUMENT;
  int directory = -1;
  ghost_store_result result = open_directory(save_dir, &directory);
  if (result != GHOST_STORE_OK) return result;
  int fd = openat(directory, leaf, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
  int error = errno;
  close(directory);
  if (fd < 0) return error == ENOENT ? GHOST_STORE_NOT_FOUND :
      (error == ELOOP ? GHOST_STORE_UNSAFE_PATH : GHOST_STORE_IO);
  struct stat st;
  result = regular_file(fd, &st);
  if (result == GHOST_STORE_OK && (st.st_size < (off_t)header ||
      st.st_size > (off_t)(header+GHOST_MAX_BYTES))) result = GHOST_STORE_LENGTH;
  unsigned char *data = NULL;
  if (result == GHOST_STORE_OK) {
    data = malloc((size_t)st.st_size);
    if (!data) result = GHOST_STORE_MEMORY;
  }
  if (result == GHOST_STORE_OK && !read_exact(fd, data, (size_t)st.st_size)) result = GHOST_STORE_LENGTH;
  if (result == GHOST_STORE_OK) {
    unsigned char extra;
    ssize_t count;
    do count = read(fd, &extra, 1); while (count < 0 && errno == EINTR);
    if (count != 0) result = count < 0 ? GHOST_STORE_IO : GHOST_STORE_LENGTH;
  }
  if (close(fd) < 0 && result == GHOST_STORE_OK) result = GHOST_STORE_IO;
  ghost_store_record decoded = {0};
  if (result == GHOST_STORE_OK) result = decode(data, (size_t)st.st_size, expected, &decoded,crown);
  if (result == GHOST_STORE_OK) {
    decoded.trail = malloc(decoded.trail_bytes);
    if (!decoded.trail) result = GHOST_STORE_MEMORY;
    else memcpy(decoded.trail, data + header, decoded.trail_bytes);
  }
  free(data);
  if (result == GHOST_STORE_OK) *out = decoded;
  return result;
}

/* Refuse links/special files, and preserve an unsupported newer envelope rather
 * than overwriting it as a side effect of trying to use an older implementation. */
static ghost_store_result check_target(int directory,const char *leaf,int crown,uint64_t revision) {
  int fd = openat(directory, leaf, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
  if (fd < 0) return errno == ENOENT ? (crown&&revision?GHOST_STORE_STALE:GHOST_STORE_OK) :
      (errno == ELOOP ? GHOST_STORE_UNSAFE_PATH : GHOST_STORE_IO);
  struct stat st;
  ghost_store_result result = regular_file(fd, &st);
  unsigned char prefix[GHOST_STORE_HEADER_BYTES];
  size_t prefix_bytes = result == GHOST_STORE_OK && st.st_size >= (off_t)sizeof prefix ? sizeof prefix : 12u;
  if (result == GHOST_STORE_OK && st.st_size >= (off_t)prefix_bytes) {
    if (!read_exact(fd, prefix, prefix_bytes)) result = GHOST_STORE_IO;
    else if (!crown && !memcmp(prefix, store_magic, 8) &&
        (get32(prefix + 8) != GHOST_STORE_ENVELOPE_VERSION ||
         (prefix_bytes == sizeof prefix &&
          (get32(prefix + 12) != GHOST_STORE_HEADER_BYTES || get32(prefix + 28) || get32(prefix + 180)))))
      result = GHOST_STORE_VERSION;
    else if (crown && (prefix_bytes<sizeof prefix || memcmp(prefix,crown_magic,8) ||
                       get32(prefix+8)!=GHOST_STORE_ENVELOPE_VERSION || get32(prefix+12)!=CROWN_HEADER_BYTES))
      result=GHOST_STORE_VERSION;
    else if (crown && (uint64_t)get32(prefix+24)+1u!=revision)
      result=GHOST_STORE_STALE;
  } else if (result==GHOST_STORE_OK && crown) result=GHOST_STORE_VERSION;
  if (close(fd) < 0 && result == GHOST_STORE_OK) result = GHOST_STORE_IO;
  return result;
}

static int same_owned_temp(int directory, const char *name, const struct stat *owned) {
  struct stat current;
  return fstatat(directory, name, &current, AT_SYMLINK_NOFOLLOW) == 0 &&
      S_ISREG(current.st_mode) && current.st_nlink == 1 &&
      current.st_dev == owned->st_dev && current.st_ino == owned->st_ino;
}

static ghost_store_result encode(const ghost_store_record *record,const ghost_crown_record *crown,
                                 unsigned char **out,size_t *length) {
  if (crown && !crown_profile_valid(crown)) return GHOST_STORE_METADATA;
  ghost_store_result result=metadata(record,crown!=NULL);
  if (result!=GHOST_STORE_OK) return result;
  result=basic_trail(record,crown!=NULL);
  if (result!=GHOST_STORE_OK) return result;
  size_t header=crown?CROWN_HEADER_BYTES:GHOST_STORE_HEADER_BYTES;
  size_t bytes=header+record->trail_bytes;
  unsigned char *data = malloc(bytes);
  if (!data) return GHOST_STORE_MEMORY;
  encode_header(data, record, bytes);
  if (crown) encode_crown(data,crown);
  memcpy(data+header,record->trail,record->trail_bytes);
  put32(data + 24, envelope_crc(data, bytes));
  *out=data;*length=bytes;
  return GHOST_STORE_OK;
}

ghost_store_result ghost_profile_pack(const ghost_crown_record *record,unsigned char **out,size_t *length) {
  if (!record || !out || !length) return GHOST_STORE_ARGUMENT;
  *out=NULL;*length=0;
  return encode(&record->race,record,out,length);
}

ghost_store_result ghost_profile_unpack(unsigned char *data,size_t length,const char *physics,ghost_crown_record *out) {
  if (!out || out->race.trail || !data || !physics_id_valid(physics)) return GHOST_STORE_ARGUMENT;
  if (length<CROWN_HEADER_BYTES || length>CROWN_HEADER_BYTES+GHOST_MAX_BYTES) return GHOST_STORE_LENGTH;
  ghost_crown_record profile={0};
  ghost_store_result result=decode(data,length,physics,&profile.race,&profile);
  if (result!=GHOST_STORE_OK) return result;
  profile.race.trail=malloc(profile.race.trail_bytes);
  if (!profile.race.trail) return GHOST_STORE_MEMORY;
  memcpy(profile.race.trail,data+CROWN_HEADER_BYTES,profile.race.trail_bytes);
  *out=profile;
  return GHOST_STORE_OK;
}

static ghost_store_result save(const char *save_dir,const char *leaf,const ghost_store_record *record,
                               const ghost_crown_record *crown,uint64_t revision) {
  unsigned char *data=NULL;
  size_t bytes=0;
  ghost_store_result result=encode(record,crown,&data,&bytes);
  if (result!=GHOST_STORE_OK) return result;
  int directory = -1;
  result = open_directory(save_dir, &directory);
  if (result != GHOST_STORE_OK) { free(data); return result; }
  if (crown) {
    int locked;
    do locked=flock(directory,LOCK_EX); while (locked<0 && errno==EINTR);
    if (locked!=0) {close(directory);free(data);return GHOST_STORE_IO;}
  }
  result = check_target(directory,leaf,crown!=NULL,revision);
  if (result != GHOST_STORE_OK) { close(directory); free(data); return result; }
  char temporary[96] = {0};
  int fd = -1;
  for (unsigned attempt = 0; attempt < 128u; ++attempt) {
    int length = snprintf(temporary, sizeof temporary, "%s.tmp.%ld.%lld.%u",
                          leaf, (long)getpid(), (long long)time(NULL), attempt);
    if (length < 0 || (size_t)length >= sizeof temporary) break;
    fd = openat(directory, temporary, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd >= 0 || errno != EEXIST) break;
  }
  if (fd < 0) { close(directory); free(data); return GHOST_STORE_IO; }
  /* This exact leaf was exclusively created above inside the verified pinned
   * absolute directory. Its inode is checked again before rename or cleanup. */
  struct stat owned;
  int owned_valid = fstat(fd, &owned) == 0 && S_ISREG(owned.st_mode) && owned.st_nlink == 1;
  if (!owned_valid || !write_exact(fd, data, bytes) || sync_file(fd) < 0) result = GHOST_STORE_IO;
  if (close(fd) < 0 && result == GHOST_STORE_OK) result = GHOST_STORE_IO;
  free(data);
  if (result == GHOST_STORE_OK) result = check_target(directory,leaf,crown!=NULL,revision);
  if (result == GHOST_STORE_OK && !same_owned_temp(directory, temporary, &owned))
    result = GHOST_STORE_UNSAFE_PATH;
  if (result == GHOST_STORE_OK && renameat(directory, temporary, directory, leaf) < 0)
    result = GHOST_STORE_IO;
  if (result != GHOST_STORE_OK) {
    /* directory fd + this function's exclusively-owned, bounded constant-prefix
     * temporary name are the verified cleanup target; no other file is deleted. */
    if (!owned_valid || !same_owned_temp(directory, temporary, &owned)) result = GHOST_STORE_UNSAFE_PATH;
    else if (unlinkat(directory, temporary, 0) < 0) result = GHOST_STORE_IO;
  } else if (sync_file(directory) < 0) result = GHOST_STORE_COMMITTED_UNSYNCED;
  close(directory);
  return result;
}

ghost_store_result ghost_store_load(const char *save_dir,const char *expected,ghost_store_record *out) {
  return load(save_dir,expected,GHOST_STORE_BASENAME,out,NULL);
}
ghost_store_result ghost_store_save(const char *save_dir,const ghost_store_record *record) {
  return save(save_dir,GHOST_STORE_BASENAME,record,NULL,0);
}
ghost_store_result ghost_crown_load(const char *save_dir,unsigned area,const char *physics,ghost_crown_record *out) {
  if (!out || out->race.trail || area>=GHOST_CROWN_AREAS) return GHOST_STORE_ARGUMENT;
  char leaf[]="ghost_crown_0";
  leaf[sizeof leaf-2]=(char)('0'+area);
  ghost_crown_record record={0};
  ghost_store_result result=load(save_dir,physics,leaf,&record.race,&record);
  if (result==GHOST_STORE_OK && record.raw_ramp>=CAR_LINK_RAMPS) {
    ghost_crown_free(&record);
    return GHOST_STORE_METADATA;
  }
  if (result==GHOST_STORE_OK) *out=record;
  return result;
}
ghost_store_result ghost_crown_save(const char *save_dir,unsigned area,const ghost_crown_record *record,uint64_t revision) {
  if (!record || area>=GHOST_CROWN_AREAS) return GHOST_STORE_ARGUMENT;
  if (record->raw_ramp>=CAR_LINK_RAMPS) return GHOST_STORE_METADATA;
  char leaf[]="ghost_crown_0";
  leaf[sizeof leaf-2]=(char)('0'+area);
  return save(save_dir,leaf,&record->race,record,revision);
}
ghost_store_result ghost_replay_load(const char *save_dir,unsigned area,unsigned slot,
                                     const char *physics,ghost_crown_record *out) {
  if (!out || out->race.trail || area>=GHOST_CROWN_AREAS || slot>=GHOST_LOCAL_REPLAYS_PER_AREA)
    return GHOST_STORE_ARGUMENT;
  char leaf[32];
  snprintf(leaf,sizeof leaf,"ghost_replay_%u_%u",area,slot);
  ghost_crown_record record={0};
  ghost_store_result result=load(save_dir,physics,leaf,&record.race,&record);
  if (result==GHOST_STORE_OK) *out=record;
  return result;
}
ghost_store_result ghost_replay_save(const char *save_dir,unsigned area,unsigned slot,
                                     const ghost_crown_record *record,uint64_t revision) {
  if (!record || area>=GHOST_CROWN_AREAS || slot>=GHOST_LOCAL_REPLAYS_PER_AREA)
    return GHOST_STORE_ARGUMENT;
  char leaf[32];
  snprintf(leaf,sizeof leaf,"ghost_replay_%u_%u",area,slot);
  return save(save_dir,leaf,&record->race,record,revision);
}
void ghost_crown_free(ghost_crown_record *record) {
  if (!record) return;
  ghost_store_free(&record->race);
  memset(record,0,sizeof *record);
}

void ghost_store_free(ghost_store_record *record) {
  if (!record) return;
  free(record->trail);
  memset(record, 0, sizeof *record);
}
int ghost_store_contains_map(const ghost_store_record *record, uint32_t ramp, uint32_t route) {
  return record && record->trail && record->trail_bytes >= 28u &&
      record->trail_bytes <= GHOST_MAX_BYTES && record->ramp == ramp && record->route == route;
}
ghost_store_result ghost_store_validate_native(const ghost_store_record *record,
                                               const ghost_format_policy *policy) {
  ghost_store_result result = metadata(record,0);
  if (result != GHOST_STORE_OK) return result;
  if (!policy || !policy->area_allowed || policy->stage != record->race_field[0]) return GHOST_STORE_ARGUMENT;
  result = basic_trail(record,0);
  if (result != GHOST_STORE_OK) return result;
  ghost_format_info info;
  return ghost_format_validate(record->trail, record->trail_bytes, policy, &info) == GHOST_FORMAT_OK ?
      GHOST_STORE_OK : GHOST_STORE_TRAIL;
}
const char *ghost_store_error(ghost_store_result result) {
  static const char *const messages[] = {
    "ok", "local ghost not found", "invalid argument", "local ghost I/O failure",
    "allocation failed", "unsupported local/native version", "invalid bounded exact length",
    "corruption checksum mismatch (not authentication)", "physics identity mismatch or invalid identity",
    "invalid local metadata", "invalid native trail syntax", "unsafe local sidecar path",
    "committed; directory durability not confirmed", "local crown was replaced after this challenge started"
  };
  return (unsigned)result < sizeof messages / sizeof *messages ? messages[result] : "unknown local ghost error";
}
