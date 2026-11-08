#if defined(__linux__) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE 1
#endif
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#ifndef _DARWIN_C_SOURCE
#define _DARWIN_C_SOURCE 1
#endif
#include "ta_rank.h"
#include <errno.h>
#include <fcntl.h>
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#if !defined(O_NOFOLLOW) || !defined(O_DIRECTORY) || !defined(AT_SYMLINK_NOFOLLOW)
#error "ta_rank requires POSIX directory-relative no-follow I/O"
#endif
#if FLT_RADIX != 2 || FLT_MANT_DIG != 24 || FLT_MAX_EXP != 128
#error "ta_rank requires IEEE754 binary32"
#endif
#if defined(__FAST_MATH__) || (defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__)
#error "ta_rank requires strict floating-point finite checks; disable fast-math"
#endif
_Static_assert(sizeof(float)==4, "binary32 required");
#define GROUPS (TA_RANK_COURSES * TA_RANK_TRAFFIC_KINDS)
#define HEADER 128u
#define ROW_BYTES 196u
#define MAX_DATE UINT64_C(253402300799999)
static const unsigned char magic[8]={'W','3','T','A','R','A','N','K'};
static const uint32_t stages[15]={363,364,365,366,367,0,369,0,376,371,372,0,374,375,377};
typedef struct {
  uint8_t rules[32], physics[32];
  uint64_t generation, sequence;
  uint32_t count[GROUPS];
  ta_rank_record rows[GROUPS][TA_RANK_TOP];
} model;
struct ta_rank_context {
  model m;
  int directory, existed, dirty;
  struct stat expected;
  char basename[160];
};
static uint32_t get32(const unsigned char *p) {return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t get64(const unsigned char *p) {return get32(p)|(uint64_t)get32(p+4)<<32;}
static void put32(unsigned char *p,uint32_t x) {for(unsigned i=0;i<4;i++)p[i]=(unsigned char)(x>>(8*i));}
static void put64(unsigned char *p,uint64_t x) {put32(p,(uint32_t)x);put32(p+4,(uint32_t)(x>>32));}
static float real32(uint32_t x) {float f;memcpy(&f,&x,4);return f;}
static int nonzero(const uint8_t *p,size_t n) {uint8_t x=0;for(size_t i=0;i<n;i++)x|=p[i];return x!=0;}
int ta_rank_course_enabled(uint32_t c) {return c<15 && stages[c]!=0;}
int ta_rank_time_ms(uint32_t bits,uint32_t *out) {
  if(out)*out=0;
  float seconds=real32(bits);
  if(!out || !isfinite(seconds))return 0;
  /* Force the original single-precision multiply before conversion. Avoid UB
   * for huge/negative inputs; clamp results would be noncompetitive sentinels. */
  volatile float scaled=seconds*1000.0f;
  if(!isfinite(scaled)||scaled<1.0f||scaled>=(float)TA_RANK_TIME_SENTINEL)return 0;
  uint32_t ms=(uint32_t)scaled;
  if(!ms || ms>=TA_RANK_TIME_SENTINEL)return 0;
  *out=ms;return 1;
}
static int valid_cohort_attempt(const uint8_t rules[32],const uint8_t physics[32],const ta_rank_attempt *a,uint32_t *ms) {
  if(!a || !ta_rank_course_enabled(a->partition.course_id)||a->partition.traffic>1 ||
     memcmp(rules,a->partition.rules_sha256,32)||memcmp(physics,a->partition.physics_sha256,32)||
     !nonzero(a->owner,16)||!nonzero(a->attempt,16)||a->completed_at_ms>MAX_DATE ||
     a->native_game_mode!=6 || a->frontend_game_mode!=2 || a->native_result_state!=8 || a->eligible!=1 ||
     a->checkpoint_count>7 || !ta_rank_time_ms(a->native_elapsed_bits,ms))return 0;
  float total=real32(a->native_elapsed_bits),previous=0;
  for(unsigned i=0;i<7;i++) {
    if(i>=a->checkpoint_count){if(a->checkpoint_bits[i])return 0;continue;}
    float t=real32(a->checkpoint_bits[i]);
    if(!isfinite(t)||t<previous||t>total||t<0)return 0;
    previous=t;
  }
  float start=real32(a->race_field[3]),goal=real32(a->race_field[4]);
  if(a->race_field[0]!=stages[a->partition.course_id]||a->race_field[1]!=0||a->race_field[2]>=75||a->race_field[5]!=0 ||
     !isfinite(start)||!isfinite(goal)||start<0||goal<=start||goal>1.0e9f)return 0;
  const ta_rank_metadata *d=&a->metadata;
  if(d->model_id>=247||(d->model_id>=224&&d->model_id<=231)||d->car_type>=45 ||
     d->class_id>=47||!d->title_id||d->title_id>=5200 ||
     d->power>24||d->handling>24||d->original_id_valid>1||d->original_devel>255 ||
     (!d->original_id_valid&&(d->original_id1||d->original_id2||d->original_devel)))return 0;
  int pad=0;
  for(unsigned i=0;i<5;i++) {
    uint32_t c=d->name[i];
    if(c>0x10ffff || (c>=0xd800&&c<=0xdfff) || (pad&&c))return 0;
    if(!c)pad=1;
  }
  return 1;
}
static int valid_attempt(const model *m,const ta_rank_attempt *a,uint32_t *ms) {
  return valid_cohort_attempt(m->rules,m->physics,a,ms);
}
/* Fixed explicit LE row encoding also makes equality independent of C padding. */
static void encode_row(unsigned char *p,const ta_rank_record *r) {
  const ta_rank_attempt *a=&r->attempt;
  put32(p,a->partition.course_id);put32(p+4,a->partition.traffic);
  memcpy(p+8,a->owner,16);memcpy(p+24,a->attempt,16);put64(p+40,a->completed_at_ms);
  put32(p+48,a->native_elapsed_bits);put32(p+52,a->checkpoint_count);
  for(unsigned i=0;i<7;i++)put32(p+56+4*i,a->checkpoint_bits[i]);
  for(unsigned i=0;i<6;i++)put32(p+84+4*i,a->race_field[i]);
  put32(p+108,a->native_game_mode);put32(p+112,a->frontend_game_mode);
  put32(p+116,a->native_result_state);put32(p+120,a->eligible);
  const ta_rank_metadata *d=&a->metadata;
  for(unsigned i=0;i<5;i++)put32(p+124+4*i,d->name[i]);
  put32(p+144,d->title_id);put32(p+148,d->class_id);put32(p+152,d->model_id);
  put32(p+156,d->car_type);put32(p+160,d->power);put32(p+164,d->handling);
  put32(p+168,d->original_id_valid);put32(p+172,d->original_id1);
  put32(p+176,d->original_id2);put32(p+180,d->original_devel);
  put32(p+184,r->score_ms);put64(p+188,r->sequence);
}
static void decode_cohort_row(ta_rank_record *r,const unsigned char *p,const uint8_t rules[32],const uint8_t physics[32]) {
  memset(r,0,sizeof *r);ta_rank_attempt *a=&r->attempt;
  memcpy(a->partition.rules_sha256,rules,32);memcpy(a->partition.physics_sha256,physics,32);
  a->partition.course_id=get32(p);a->partition.traffic=get32(p+4);
  memcpy(a->owner,p+8,16);memcpy(a->attempt,p+24,16);a->completed_at_ms=get64(p+40);
  a->native_elapsed_bits=get32(p+48);a->checkpoint_count=get32(p+52);
  for(unsigned i=0;i<7;i++)a->checkpoint_bits[i]=get32(p+56+4*i);
  for(unsigned i=0;i<6;i++)a->race_field[i]=get32(p+84+4*i);
  a->native_game_mode=get32(p+108);a->frontend_game_mode=get32(p+112);
  a->native_result_state=get32(p+116);a->eligible=get32(p+120);
  ta_rank_metadata *d=&a->metadata;
  for(unsigned i=0;i<5;i++)d->name[i]=get32(p+124+4*i);
  d->title_id=get32(p+144);d->class_id=get32(p+148);d->model_id=get32(p+152);
  d->car_type=get32(p+156);d->power=get32(p+160);d->handling=get32(p+164);
  d->original_id_valid=get32(p+168);d->original_id1=get32(p+172);
  d->original_id2=get32(p+176);d->original_devel=get32(p+180);
  r->score_ms=get32(p+184);r->sequence=get64(p+188);
}
static void decode_row(ta_rank_record *r,const unsigned char *p,const model *m) {
  decode_cohort_row(r,p,m->rules,m->physics);
}

/* CTA1 is a portable proposal. Original card serials and local ranking
 * position/sequence never leave the device. */
int ta_rank_community_encode(const ta_rank_attempt *a, uint8_t out[TA_RANK_COMMUNITY_ROW_BYTES]) {
  uint32_t ms;
  if (!a || !out || !valid_cohort_attempt(a->partition.rules_sha256,a->partition.physics_sha256,a,&ms)) return 0;
  unsigned char row[ROW_BYTES];
  ta_rank_record r = {.attempt=*a};
  encode_row(row,&r);
  memcpy(out,"CTA1",4);
  memcpy(out+4,a->partition.rules_sha256,32);
  memcpy(out+36,a->partition.physics_sha256,32);
  memcpy(out+68,row,168);
  return 1;
}

int ta_rank_community_board(const void *bytes, size_t size, const ta_rank_partition *part, ta_rank_view *out) {
  const uint8_t *p = bytes;
  if (!p || !part || !out || size<8 || memcmp(p,"CTB1",4)) return 0;
  uint32_t count = get32(p+4);
  if (count>TA_RANK_DISPLAY || size!=8+count*TA_RANK_COMMUNITY_ROW_BYTES) return 0;
  ta_rank_view next = {.partition=*part,.generation=1,.real_count=count,.row_count=count,
                       .source_kind=TA_RANK_SOURCE_COMMUNITY_UNVERIFIED};
  p+=8;
  for (uint32_t i=0;i<count;++i,p+=TA_RANK_COMMUNITY_ROW_BYTES) {
    if (memcmp(p,"CTA1",4) || memcmp(p+4,part->rules_sha256,32) || memcmp(p+36,part->physics_sha256,32)) return 0;
    unsigned char row[ROW_BYTES]={0};
    memcpy(row,p+68,168);
    ta_rank_row *r=&next.rows[i];
    decode_cohort_row(&r->record,row,part->rules_sha256,part->physics_sha256);
    const ta_rank_attempt *a=&r->record.attempt;
    if (a->partition.course_id!=part->course_id || a->partition.traffic!=part->traffic ||
        !valid_cohort_attempt(part->rules_sha256,part->physics_sha256,a,&r->record.score_ms) ||
        (i && r->record.score_ms<next.rows[i-1].display_ms)) return 0;
    r->source_kind=next.source_kind;
    r->display_ms=r->record.score_ms;
    r->position=i+1;
    r->default_index=UINT32_MAX;
  }
  *out=next;
  return 1;
}
static int equal_attempt(const ta_rank_attempt *a,const ta_rank_attempt *b) {
  ta_rank_record x={.attempt=*a},y={.attempt=*b};unsigned char px[ROW_BYTES],py[ROW_BYTES];
  encode_row(px,&x);encode_row(py,&y);
  return !memcmp(px,py,ROW_BYTES)&&!memcmp(&a->partition,&b->partition,sizeof a->partition);
}
static int before(const ta_rank_record *a,const ta_rank_record *b) {
  if(a->score_ms!=b->score_ms)return a->score_ms<b->score_ms;
  if(a->attempt.completed_at_ms!=b->attempt.completed_at_ms)return a->attempt.completed_at_ms>b->attempt.completed_at_ms;
  return a->sequence>b->sequence;
}
static ta_rank_status submit(model *m,const ta_rank_attempt *a,ta_rank_submission *out) {
  if(out)memset(out,0,sizeof *out);
  uint32_t ms=0;
  if(!valid_attempt(m,a,&ms))return TA_RANK_INVALID;
  if(out){out->score_ms=ms;out->generation=m->generation;}
  unsigned g=a->partition.course_id*2+a->partition.traffic,n=m->count[g];
  for(unsigned h=0;h<GROUPS;h++)for(unsigned i=0;i<m->count[h];i++) {
    if(!memcmp(m->rows[h][i].attempt.attempt,a->attempt,16)) {
      if(!equal_attempt(a,&m->rows[h][i].attempt))return TA_RANK_ATTEMPT_CONFLICT;
      if(out)out->position=i+1;
      return TA_RANK_DUPLICATE;
    }
  }
  unsigned own=n;
  for(unsigned i=0;i<n;i++)if(!memcmp(m->rows[g][i].attempt.owner,a->owner,16)){own=i;break;}
  if(own<n && ms>=m->rows[g][own].score_ms){if(out)out->position=own+1;return TA_RANK_NO_CHANGE;}
  if(m->sequence==UINT64_MAX||m->generation==UINT64_MAX)return TA_RANK_EXHAUSTED;
  ta_rank_record next={.attempt=*a,.score_ms=ms,.sequence=m->sequence+1};
  unsigned pos=0;
  while(pos<n && before(&m->rows[g][pos],&next))pos++;
  if(own==n && pos>=TA_RANK_TOP)return TA_RANK_NO_CHANGE;
  if(own<n){memmove(&m->rows[g][own],&m->rows[g][own+1],(n-own-1)*sizeof next);n--;}
  pos=0;while(pos<n&&before(&m->rows[g][pos],&next))pos++;
  unsigned length=n<TA_RANK_TOP?n:TA_RANK_TOP-1;
  memmove(&m->rows[g][pos+1],&m->rows[g][pos],(length-pos)*sizeof next);
  m->rows[g][pos]=next;m->count[g]=n<TA_RANK_TOP?n+1:n;
  m->sequence++;m->generation++;
  if(out){out->position=pos+1;out->generation=m->generation;}
  return TA_RANK_OK;
}
ta_rank_context *ta_rank_create(const uint8_t rules[32],const uint8_t physics[32]) {
  if(!rules||!physics||!nonzero(rules,32)||!nonzero(physics,32))return NULL;
  ta_rank_context *c=calloc(1,sizeof *c);if(!c)return NULL;
  memcpy(c->m.rules,rules,32);memcpy(c->m.physics,physics,32);c->m.generation=1;c->directory=-1;
  static const char hex[]="0123456789abcdef";
  char rh[65],ph[65];for(unsigned i=0;i<32;i++) {
    rh[2*i]=hex[rules[i]>>4];rh[2*i+1]=hex[rules[i]&15];
    ph[2*i]=hex[physics[i]>>4];ph[2*i+1]=hex[physics[i]&15];
  }rh[64]=ph[64]=0;
  (void)snprintf(c->basename,sizeof c->basename,"ta-ranking-v1-%s-%s.ctr",rh,ph);return c;
}
void ta_rank_store_close(ta_rank_context *c) {if(c&&c->directory>=0){close(c->directory);c->directory=-1;}if(c)c->dirty=0;}
void ta_rank_destroy(ta_rank_context *c){if(c){ta_rank_store_close(c);free(c);}}
ta_rank_status ta_rank_submit_local(ta_rank_context *c,const ta_rank_attempt *a,ta_rank_submission *s) {
  if(!c)return TA_RANK_INVALID;
  ta_rank_status r=submit(&c->m,a,s);if(r==TA_RANK_OK)c->dirty=1;return r;
}
ta_rank_status ta_rank_get_local(const ta_rank_context *c,uint32_t course,uint32_t traffic,uint32_t pos,ta_rank_record *r) {
  if(!c||!r||!ta_rank_course_enabled(course)||traffic>1||!pos||pos>100)return TA_RANK_INVALID;
  unsigned g=course*2+traffic;if(pos>c->m.count[g])return TA_RANK_NOT_FOUND;
  *r=c->m.rows[g][pos-1];return TA_RANK_OK;
}
ta_rank_status ta_rank_view_local(const ta_rank_context *c,uint32_t course,uint32_t traffic,int defaults,ta_rank_view *v) {
  if(!c||!v||!ta_rank_course_enabled(course)||traffic>1)return TA_RANK_INVALID;
  memset(v,0,sizeof *v);memcpy(v->partition.rules_sha256,c->m.rules,32);memcpy(v->partition.physics_sha256,c->m.physics,32);
  v->partition.course_id=course;v->partition.traffic=traffic;v->generation=c->m.generation;
  unsigned g=course*2+traffic;v->real_count=c->m.count[g];
  v->source_kind=TA_RANK_SOURCE_LOCAL_UNVERIFIED;
  v->row_count=defaults?10:(v->real_count<10?v->real_count:10);
  for(unsigned i=0;i<v->row_count;i++) {
    ta_rank_row *r=&v->rows[i];r->position=i+1;
    if(i<v->real_count){r->source_kind=TA_RANK_SOURCE_LOCAL_UNVERIFIED;r->record=c->m.rows[g][i];r->display_ms=r->record.score_ms;r->default_index=UINT32_MAX;}
    else {r->source_kind=TA_RANK_SOURCE_FACTORY_DEFAULT;r->display_ms=TA_RANK_FACTORY_DISPLAY_MS;r->default_index=i-v->real_count;}
  }return TA_RANK_OK;
}
static uint32_t checksum(const unsigned char *p,size_t n) {
  uint32_t crc=UINT32_MAX;
  for(size_t i=0;i<n;i++){unsigned char b=(i>=28&&i<32)?0:p[i];crc^=b;for(unsigned k=0;k<8;k++)crc=(crc>>1)^(0xedb88320u & (0u-(crc&1u)));}
  return ~crc;
}
static ta_rank_status encode_model(const model *m,unsigned char **output,size_t *bytes) {
  unsigned count=0;for(unsigned g=0;g<GROUPS;g++)count+=m->count[g];
  *bytes=HEADER+(size_t)count*ROW_BYTES;unsigned char *p=calloc(1,*bytes);if(!p)return TA_RANK_MEMORY;
  memcpy(p,magic,8);put32(p+8,1);put32(p+12,HEADER);put32(p+16,ROW_BYTES);put32(p+20,count);put32(p+24,(uint32_t)*bytes);
  memcpy(p+32,m->rules,32);memcpy(p+64,m->physics,32);put64(p+96,m->generation);put64(p+104,m->sequence);
  unsigned at=0;for(unsigned g=0;g<GROUPS;g++)for(unsigned i=0;i<m->count[g];i++)encode_row(p+HEADER+ROW_BYTES*at++,&m->rows[g][i]);
  put32(p+28,checksum(p,*bytes));*output=p;return TA_RANK_OK;
}
static ta_rank_status decode_model(model *m,const unsigned char *p,size_t n) {
  if(n<HEADER)return TA_RANK_CORRUPT;
  if(memcmp(p,magic,8)||get32(p+8)!=1||get32(p+12)!=HEADER||get32(p+16)!=ROW_BYTES ||
     memcmp(p+32,m->rules,32)||memcmp(p+64,m->physics,32))return TA_RANK_FOREIGN;
  uint32_t count=get32(p+20);
  if(count>GROUPS*TA_RANK_TOP||get32(p+24)!=n||n!=HEADER+(size_t)count*ROW_BYTES ||
     get32(p+28)!=checksum(p,n)||!get64(p+96))return TA_RANK_CORRUPT;
  for(unsigned i=112;i<HEADER;i++)if(p[i])return TA_RANK_FOREIGN;
  m->generation=get64(p+96);m->sequence=get64(p+104);
  for(unsigned k=0;k<count;k++) {
    ta_rank_record r;decode_row(&r,p+HEADER+k*ROW_BYTES,m);uint32_t ms;
    if(!valid_attempt(m,&r.attempt,&ms)||r.score_ms!=ms||!r.sequence||r.sequence>m->sequence)return TA_RANK_CORRUPT;
    unsigned g=r.attempt.partition.course_id*2+r.attempt.partition.traffic,i=m->count[g];
    if(i>=100 || (i&&!before(&m->rows[g][i-1],&r)))return TA_RANK_CORRUPT;
    for(unsigned h=0;h<GROUPS;h++)for(unsigned j=0;j<m->count[h];j++) {
      const ta_rank_record *old=&m->rows[h][j];
      if(old->sequence==r.sequence||!memcmp(old->attempt.attempt,r.attempt.attempt,16)||
         (h==g&&!memcmp(old->attempt.owner,r.attempt.owner,16)))return TA_RANK_CORRUPT;
    }
    m->rows[g][i]=r;m->count[g]++;
  }
  return TA_RANK_OK;
}
static int same_stat(const struct stat *a,const struct stat *b) {
#if defined(__APPLE__)
#define MT(x) (x)->st_mtimespec
#define CT(x) (x)->st_ctimespec
#else
#define MT(x) (x)->st_mtim
#define CT(x) (x)->st_ctim
#endif
  return a->st_dev==b->st_dev&&a->st_ino==b->st_ino&&a->st_nlink==b->st_nlink&&a->st_size==b->st_size&&
    MT(a).tv_sec==MT(b).tv_sec&&MT(a).tv_nsec==MT(b).tv_nsec&&CT(a).tv_sec==CT(b).tv_sec&&CT(a).tv_nsec==CT(b).tv_nsec;
#undef MT
#undef CT
}
static ta_rank_status regular(const struct stat *s) {
  return S_ISREG(s->st_mode)&&s->st_nlink==1&&s->st_uid==geteuid()&&!(s->st_mode&0022)?TA_RANK_OK:TA_RANK_UNSAFE_PATH;
}
static ta_rank_status directory_open(const char *path,int *out) {
  if(!path||path[0]!='/')return TA_RANK_UNSAFE_PATH;
  size_t n=strnlen(path,4097);if(!n||n>4096)return TA_RANK_UNSAFE_PATH;
  /* Android's /data ancestors allow traversal without directory reads.
   * Only the private leaf needs a readable descriptor for fsync. */
#if defined(O_PATH)
  const int parent_access=O_PATH;
#elif defined(O_SEARCH)
  const int parent_access=O_SEARCH;
#else
  const int parent_access=O_RDONLY;
#endif
  const int flags=O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW;
  int fd=open("/",(n>1?parent_access:O_RDONLY)|flags);if(fd<0)return TA_RANK_IO;
  size_t at=1;
  while(at<n) {
    size_t begin=at;while(at<n&&path[at]!='/')at++;size_t length=at-begin;
    if(!length||length>255||(length==1&&path[begin]=='.')||(length==2&&path[begin]=='.'&&path[begin+1]=='.')){close(fd);return TA_RANK_UNSAFE_PATH;}
    char part[256];memcpy(part,path+begin,length);part[length]=0;
    int access=at+1<n?parent_access:O_RDONLY;
    int next=openat(fd,part,access|flags);int error=errno;close(fd);
    if(next<0)return error==ELOOP||error==ENOTDIR?TA_RANK_UNSAFE_PATH:TA_RANK_IO;
    fd=next;if(at<n)at++;
  }
  struct stat s;if(fstat(fd,&s)<0){close(fd);return TA_RANK_IO;}
  if(s.st_uid!=geteuid()||(s.st_mode&0022)){close(fd);return TA_RANK_UNSAFE_PATH;}
  *out=fd;return TA_RANK_OK;
}
static int read_all(int fd,unsigned char *p,size_t n) {
  while(n){ssize_t k=read(fd,p,n);if(k<0&&errno==EINTR)continue;if(k<=0)return 0;p+=k;n-=(size_t)k;}return 1;
}
static int write_all(int fd,const unsigned char *p,size_t n) {
  while(n){ssize_t k=write(fd,p,n);if(k<0&&errno==EINTR)continue;if(k<=0)return 0;p+=k;n-=(size_t)k;}return 1;
}
static int sync_fd(int fd){int r;do r=fsync(fd);while(r<0&&errno==EINTR);return r;}
static ta_rank_status target_current(int directory,const char *basename,int existed,const struct stat *expected) {
  struct stat s;
  if(fstatat(directory,basename,&s,AT_SYMLINK_NOFOLLOW)<0)return errno==ENOENT?(existed?TA_RANK_STALE:TA_RANK_OK):TA_RANK_IO;
  ta_rank_status r=regular(&s);if(r!=TA_RANK_OK)return r;
  return existed&&same_stat(&s,expected)?TA_RANK_OK:TA_RANK_STALE;
}
static ta_rank_status current_target(ta_rank_context *c) {
  return target_current(c->directory,c->basename,c->existed,&c->expected);
}
ta_rank_status ta_rank_store_open(ta_rank_context *c,const char *path) {
  if(!c)return TA_RANK_INVALID;
  ta_rank_store_close(c);int directory=-1;
  ta_rank_status r=directory_open(path,&directory);if(r!=TA_RANK_OK)return r;
  int fd=openat(directory,c->basename,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
  int error=errno;
  if(fd<0&&error!=ENOENT){close(directory);return error==ELOOP?TA_RANK_UNSAFE_PATH:TA_RANK_IO;}
  model *candidate=calloc(1,sizeof *candidate);if(!candidate){if(fd>=0)close(fd);close(directory);return TA_RANK_MEMORY;}
  memcpy(candidate->rules,c->m.rules,32);memcpy(candidate->physics,c->m.physics,32);candidate->generation=1;
  struct stat before_read={0},after_read={0};unsigned char *data=NULL;
  int existed=fd>=0;
  if(existed) {
    if(fstat(fd,&before_read)<0)r=TA_RANK_IO;else r=regular(&before_read);
    if(r==TA_RANK_OK&&(before_read.st_size<HEADER||before_read.st_size>TA_RANK_STORE_MAX_BYTES))r=TA_RANK_CORRUPT;
    if(r==TA_RANK_OK){data=malloc((size_t)before_read.st_size);if(!data)r=TA_RANK_MEMORY;}
    if(r==TA_RANK_OK&&!read_all(fd,data,(size_t)before_read.st_size))r=TA_RANK_IO;
    if(r==TA_RANK_OK){unsigned char extra;ssize_t k;do k=read(fd,&extra,1);while(k<0&&errno==EINTR);if(k!=0)r=TA_RANK_STALE;}
    if(r==TA_RANK_OK&&(fstat(fd,&after_read)<0||!same_stat(&before_read,&after_read)))r=TA_RANK_STALE;
    if(close(fd)<0&&r==TA_RANK_OK)r=TA_RANK_IO;
    if(r==TA_RANK_OK)r=decode_model(candidate,data,(size_t)before_read.st_size);
  }
  free(data);
  if(r==TA_RANK_OK){
    /* Check the named leaf before publishing a successfully read candidate.
     * This remains a single-owner check, not atomic CAS against hostile writers. */
    struct stat named;
    if(fstatat(directory,c->basename,&named,AT_SYMLINK_NOFOLLOW)<0) {
      if(errno!=ENOENT)r=TA_RANK_IO;else if(existed)r=TA_RANK_STALE;
    } else if(regular(&named)!=TA_RANK_OK)r=TA_RANK_UNSAFE_PATH;
    else if(!existed||!same_stat(&named,&before_read))r=TA_RANK_STALE;
  }
  if(r==TA_RANK_OK){
    uint64_t generation=candidate->generation>c->m.generation?candidate->generation:c->m.generation;
    if(generation==UINT64_MAX)r=TA_RANK_EXHAUSTED;
    else {candidate->generation=generation+1;c->m=*candidate;c->directory=directory;c->existed=existed;c->expected=before_read;c->dirty=0;}
  }
  free(candidate);if(r!=TA_RANK_OK){close(directory);return r;}
  return existed?TA_RANK_OK:TA_RANK_NOT_FOUND;
}
static int temp_owned(int directory,const char *name,const struct stat *owned) {
  struct stat s;return fstatat(directory,name,&s,AT_SYMLINK_NOFOLLOW)==0&&regular(&s)==TA_RANK_OK&&s.st_dev==owned->st_dev&&s.st_ino==owned->st_ino;
}
ta_rank_status ta_rank_commit_local(ta_rank_context *c,const ta_rank_attempt *a,ta_rank_submission *out) {
  if(out)memset(out,0,sizeof *out);
  if(!c||c->directory<0)return TA_RANK_INVALID;
  if(c->dirty)return TA_RANK_STALE;
  ta_rank_status r=current_target(c);if(r!=TA_RANK_OK)return r;
  model *candidate=malloc(sizeof *candidate);if(!candidate)return TA_RANK_MEMORY;*candidate=c->m;
  ta_rank_submission next={0};r=submit(candidate,a,&next);
  if(r!=TA_RANK_OK){free(candidate);if(out)*out=next;return r;}
  unsigned char *data=NULL;size_t bytes=0;r=encode_model(candidate,&data,&bytes);
  char temporary[224]={0};int fd=-1;struct stat owned={0};int own=0;
  static uint64_t serial;
  if(r==TA_RANK_OK) {
    for(unsigned tries=0;tries<128;tries++) {
      if(serial==UINT64_MAX){r=TA_RANK_EXHAUSTED;break;}
      int n=snprintf(temporary,sizeof temporary,"%s.tmp.%ld.%llu",c->basename,(long)getpid(),(unsigned long long)++serial);
      if(n<0||(size_t)n>=sizeof temporary){r=TA_RANK_IO;break;}
      fd=openat(c->directory,temporary,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0600);
      if(fd>=0||errno!=EEXIST)break;
    }
    if(fd<0&&r==TA_RANK_OK)r=TA_RANK_IO;
  }
  if(fd>=0) {
    own=fstat(fd,&owned)==0&&regular(&owned)==TA_RANK_OK;
    if(!own||!write_all(fd,data,bytes)||sync_fd(fd)<0)r=TA_RANK_IO;
    if(close(fd)<0&&r==TA_RANK_OK)r=TA_RANK_IO;
  }
  free(data);
  if(r==TA_RANK_OK)r=current_target(c);
  if(r==TA_RANK_OK&&!temp_owned(c->directory,temporary,&owned))r=TA_RANK_UNSAFE_PATH;
  if(r==TA_RANK_OK&&renameat(c->directory,temporary,c->directory,c->basename)<0)r=TA_RANK_IO;
  if(r==TA_RANK_OK) {
    /* Once rename commits, never report rollback even if a later stat/fsync fails. */
    c->m=*candidate;c->existed=1;c->dirty=0;
    if(fstatat(c->directory,c->basename,&c->expected,AT_SYMLINK_NOFOLLOW)<0||regular(&c->expected)!=TA_RANK_OK||sync_fd(c->directory)<0)r=TA_RANK_COMMITTED_UNSYNCED;
    if(out)*out=next;
  } else if(own&&temp_owned(c->directory,temporary,&owned)) {
    /* Only this exclusively-created, inode-rechecked private leaf is removed. */
    if(unlinkat(c->directory,temporary,0)<0)r=TA_RANK_IO;
  }
  free(candidate);return r;
}
const char *ta_rank_error(ta_rank_status s) {
  static const char *const names[]={"ok","unchanged","duplicate","not_found","invalid","attempt_conflict","foreign","corrupt","unsafe_path","io","memory","stale","exhausted","committed_unsynced"};
  return (unsigned)s<sizeof names/sizeof names[0]?names[s]:"unknown";
}

/* Independent future-upload candidates. NEVER a ranking, receipt or authority. */
#include "ta_rank_outbox.h"
static const unsigned char pending_magic[8]={'W','3','T','A','Q','U','E','1'};
#define PENDING_BYTES (HEADER+TA_RANK_OUTBOX_CAPACITY*ROW_BYTES)
typedef struct {
  uint8_t rules[32],physics[32];
  uint64_t generation,sequence;
  uint32_t count;
  ta_rank_record cells[TA_RANK_OUTBOX_CAPACITY]; /* score/sequence are local bookkeeping */
} pending_model;
struct ta_rank_outbox {
  pending_model m;
  int directory,existed;
  struct stat expected;
  char basename[160];
};
static int same_pending_cell(const ta_rank_attempt *a,const ta_rank_attempt *b) {
  return a->partition.course_id==b->partition.course_id && a->partition.traffic==b->partition.traffic && !memcmp(a->owner,b->owner,16);
}
static ta_rank_status pending_submit(pending_model *m,const ta_rank_attempt *a) {
  uint32_t ms;
  if(!valid_cohort_attempt(m->rules,m->physics,a,&ms))return TA_RANK_INVALID;
  unsigned cell=m->count;
  for(unsigned i=0;i<m->count;i++) {
    const ta_rank_record *r=&m->cells[i];
    if(!memcmp(r->attempt.attempt,a->attempt,16))return equal_attempt(a,&r->attempt)?TA_RANK_DUPLICATE:TA_RANK_ATTEMPT_CONFLICT;
    if(same_pending_cell(a,&r->attempt))cell=i;
  }
  if(cell<m->count && ms>=m->cells[cell].score_ms)return TA_RANK_NO_CHANGE;
  if(cell==m->count && m->count>=TA_RANK_OUTBOX_CAPACITY)return TA_RANK_OUTBOX_FULL;
  if(m->sequence==UINT64_MAX||m->generation==UINT64_MAX)return TA_RANK_EXHAUSTED;
  m->sequence++;m->generation++;
  m->cells[cell]=(ta_rank_record){.attempt=*a,.score_ms=ms,.sequence=m->sequence};
  if(cell==m->count)m->count++;
  return TA_RANK_OK;
}
static ta_rank_status pending_encode(const pending_model *m,unsigned char **out,size_t *bytes) {
  *bytes=HEADER+(size_t)m->count*ROW_BYTES;
  unsigned char *p=calloc(1,*bytes);if(!p)return TA_RANK_MEMORY;
  memcpy(p,pending_magic,8);put32(p+8,1);put32(p+12,HEADER);put32(p+16,ROW_BYTES);
  put32(p+20,m->count);put32(p+24,(uint32_t)*bytes);
  memcpy(p+32,m->rules,32);memcpy(p+64,m->physics,32);put64(p+96,m->generation);put64(p+104,m->sequence);
  for(unsigned i=0;i<m->count;i++)encode_row(p+HEADER+i*ROW_BYTES,&m->cells[i]);
  put32(p+28,checksum(p,*bytes));*out=p;return TA_RANK_OK;
}
static ta_rank_status pending_decode(pending_model *m,const unsigned char *p,size_t n) {
  if(n<HEADER)return TA_RANK_CORRUPT;
  if(memcmp(p,pending_magic,8)||get32(p+8)!=1||get32(p+12)!=HEADER||get32(p+16)!=ROW_BYTES ||
     memcmp(p+32,m->rules,32)||memcmp(p+64,m->physics,32))return TA_RANK_FOREIGN;
  uint32_t count=get32(p+20);
  if(count>TA_RANK_OUTBOX_CAPACITY||get32(p+24)!=n||n!=HEADER+(size_t)count*ROW_BYTES||
     get32(p+28)!=checksum(p,n)||!get64(p+96))return TA_RANK_CORRUPT;
  for(unsigned i=112;i<HEADER;i++)if(p[i])return TA_RANK_FOREIGN;
  m->generation=get64(p+96);m->sequence=get64(p+104);
  for(unsigned i=0;i<count;i++) {
    ta_rank_record r;uint32_t ms;
    decode_cohort_row(&r,p+HEADER+i*ROW_BYTES,m->rules,m->physics);
    if(!valid_cohort_attempt(m->rules,m->physics,&r.attempt,&ms)||r.score_ms!=ms||!r.sequence||r.sequence>m->sequence)return TA_RANK_CORRUPT;
    for(unsigned j=0;j<i;j++)if(m->cells[j].sequence==r.sequence ||
       !memcmp(m->cells[j].attempt.attempt,r.attempt.attempt,16)||same_pending_cell(&m->cells[j].attempt,&r.attempt))return TA_RANK_CORRUPT;
    m->cells[i]=r;
  }
  m->count=count;return TA_RANK_OK;
}
ta_rank_outbox *ta_rank_outbox_create(const uint8_t rules[32],const uint8_t physics[32]) {
  if(!rules||!physics||!nonzero(rules,32)||!nonzero(physics,32))return NULL;
  ta_rank_outbox *q=calloc(1,sizeof *q);if(!q)return NULL;
  memcpy(q->m.rules,rules,32);memcpy(q->m.physics,physics,32);q->m.generation=1;q->directory=-1;
  static const char hex[]="0123456789abcdef";char rh[65],ph[65];
  for(unsigned i=0;i<32;i++) {rh[2*i]=hex[rules[i]>>4];rh[2*i+1]=hex[rules[i]&15];ph[2*i]=hex[physics[i]>>4];ph[2*i+1]=hex[physics[i]&15];}
  rh[64]=ph[64]=0;(void)snprintf(q->basename,sizeof q->basename,"ta-pending-v1-%s-%s.ctq",rh,ph);return q;
}
static void pending_close(ta_rank_outbox *q) {if(q->directory>=0){close(q->directory);q->directory=-1;}}
void ta_rank_outbox_destroy(ta_rank_outbox *q) {if(q){pending_close(q);free(q);}}
uint32_t ta_rank_outbox_count(const ta_rank_outbox *q) {return q?q->m.count:0;}
uint64_t ta_rank_outbox_generation(const ta_rank_outbox *q) {return q?q->m.generation:0;}
ta_rank_status ta_rank_outbox_copy(const ta_rank_outbox *q,uint32_t index,ta_rank_attempt *a,uint64_t *generation) {
  if(!q||!a)return TA_RANK_INVALID;
  if(index>=q->m.count)return TA_RANK_NOT_FOUND;
  *a=q->m.cells[index].attempt;if(generation)*generation=q->m.generation;return TA_RANK_OK;
}
ta_rank_status ta_rank_outbox_open(ta_rank_outbox *q,const char *path) {
  if(!q)return TA_RANK_INVALID;
  pending_close(q);int directory=-1;
  ta_rank_status r=directory_open(path,&directory);if(r!=TA_RANK_OK)return r;
  int fd=openat(directory,q->basename,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC),error=errno;
  if(fd<0&&error!=ENOENT){close(directory);return error==ELOOP?TA_RANK_UNSAFE_PATH:TA_RANK_IO;}
  pending_model *candidate=calloc(1,sizeof *candidate);if(!candidate){if(fd>=0)close(fd);close(directory);return TA_RANK_MEMORY;}
  memcpy(candidate->rules,q->m.rules,32);memcpy(candidate->physics,q->m.physics,32);candidate->generation=1;
  int existed=fd>=0;struct stat first={0},last={0};unsigned char *data=NULL;
  if(existed) {
    if(fstat(fd,&first)<0)r=TA_RANK_IO;else r=regular(&first);
    if(r==TA_RANK_OK&&(first.st_size<HEADER||first.st_size>PENDING_BYTES))r=TA_RANK_CORRUPT;
    if(r==TA_RANK_OK){data=malloc((size_t)first.st_size);if(!data)r=TA_RANK_MEMORY;}
    if(r==TA_RANK_OK&&!read_all(fd,data,(size_t)first.st_size))r=TA_RANK_IO;
    if(r==TA_RANK_OK){unsigned char extra;ssize_t k;do k=read(fd,&extra,1);while(k<0&&errno==EINTR);if(k!=0)r=TA_RANK_STALE;}
    if(r==TA_RANK_OK&&(fstat(fd,&last)<0||!same_stat(&first,&last)))r=TA_RANK_STALE;
    if(close(fd)<0&&r==TA_RANK_OK)r=TA_RANK_IO;
    if(r==TA_RANK_OK)r=pending_decode(candidate,data,(size_t)first.st_size);
  }
  free(data);
  if(r==TA_RANK_OK)r=target_current(directory,q->basename,existed,&first);
  if(r==TA_RANK_OK) {
    uint64_t gen=candidate->generation>q->m.generation?candidate->generation:q->m.generation;
    if(gen==UINT64_MAX)r=TA_RANK_EXHAUSTED;
    else {candidate->generation=gen+1;q->m=*candidate;q->directory=directory;q->existed=existed;q->expected=first;}
  }
  free(candidate);if(r!=TA_RANK_OK){close(directory);return r;}
  return existed?TA_RANK_OK:TA_RANK_NOT_FOUND;
}
static ta_rank_status pending_publish(ta_rank_outbox *q,const pending_model *candidate) {
  unsigned char *data=NULL;size_t bytes=0;
  ta_rank_status r=pending_encode(candidate,&data,&bytes);
  char temporary[224]={0};struct stat owned={0};int fd=-1,own=0;static uint64_t serial;
  if(r==TA_RANK_OK) {
    for(unsigned tries=0;tries<128;tries++) {
      if(serial==UINT64_MAX){r=TA_RANK_EXHAUSTED;break;}
      int n=snprintf(temporary,sizeof temporary,"%s.tmp.%ld.%llu",q->basename,(long)getpid(),(unsigned long long)++serial);
      if(n<0||(size_t)n>=sizeof temporary){r=TA_RANK_IO;break;}
      fd=openat(q->directory,temporary,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0600);
      if(fd>=0||errno!=EEXIST)break;
    }
    if(fd<0&&r==TA_RANK_OK)r=TA_RANK_IO;
  }
  if(fd>=0) {
    own=fstat(fd,&owned)==0&&regular(&owned)==TA_RANK_OK;
    if(!own||!write_all(fd,data,bytes)||sync_fd(fd)<0)r=TA_RANK_IO;
    if(close(fd)<0&&r==TA_RANK_OK)r=TA_RANK_IO;
  }
  free(data);
  if(r==TA_RANK_OK)r=target_current(q->directory,q->basename,q->existed,&q->expected);
  if(r==TA_RANK_OK&&!temp_owned(q->directory,temporary,&owned))r=TA_RANK_UNSAFE_PATH;
  if(r==TA_RANK_OK&&renameat(q->directory,temporary,q->directory,q->basename)<0)r=TA_RANK_IO;
  if(r==TA_RANK_OK) {
    q->m=*candidate;q->existed=1;
    if(fstatat(q->directory,q->basename,&q->expected,AT_SYMLINK_NOFOLLOW)<0||regular(&q->expected)!=TA_RANK_OK||sync_fd(q->directory)<0)r=TA_RANK_COMMITTED_UNSYNCED;
  } else if(own&&temp_owned(q->directory,temporary,&owned)) {
    if(unlinkat(q->directory,temporary,0)<0)r=TA_RANK_IO;
  }
  return r;
}
ta_rank_status ta_rank_outbox_enqueue(ta_rank_outbox *q,const ta_rank_attempt *a) {
  if(!q||q->directory<0)return TA_RANK_INVALID;
  ta_rank_status r=target_current(q->directory,q->basename,q->existed,&q->expected);if(r!=TA_RANK_OK)return r;
  pending_model *candidate=malloc(sizeof *candidate);if(!candidate)return TA_RANK_MEMORY;*candidate=q->m;
  r=pending_submit(candidate,a);
  if(r==TA_RANK_OK)r=pending_publish(q,candidate);
  free(candidate);return r;
}
ta_rank_status ta_rank_outbox_ack(ta_rank_outbox *q,const uint8_t attempt[16]) {
  if(!q||q->directory<0||!attempt)return TA_RANK_INVALID;
  uint32_t i=0;
  while(i<q->m.count && memcmp(q->m.cells[i].attempt.attempt,attempt,16))++i;
  if(i==q->m.count)return TA_RANK_NOT_FOUND;
  if(q->m.generation==UINT64_MAX)return TA_RANK_EXHAUSTED;
  pending_model *candidate=malloc(sizeof *candidate);if(!candidate)return TA_RANK_MEMORY;*candidate=q->m;
  --candidate->count;
  memmove(candidate->cells+i,candidate->cells+i+1,(candidate->count-i)*sizeof candidate->cells[0]);
  ++candidate->generation;
  ta_rank_status r=pending_publish(q,candidate);
  free(candidate);return r;
}
const char *ta_rank_outbox_error(ta_rank_status status) {
  return status==TA_RANK_OUTBOX_FULL?"pending_queue_full_preserved":ta_rank_error(status);
}
