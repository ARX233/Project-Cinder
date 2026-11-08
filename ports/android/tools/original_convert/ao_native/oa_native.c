/* Safe adapter around the unchanged, trusted project AO algorithm.
 * Compile: -std=c11 -O2 -fwrapv -ffp-contract=off -fno-fast-math -pthread -lm.
 * No original arcade executable/APK/emulator code is used or executed. */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include "oa_native.h"
#include <errno.h>
#include <fcntl.h>
#include <fenv.h>
#include <limits.h>
#include <math.h>
#include <pthread.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#if defined(__FAST_MATH__)
#error "AO requires -fno-fast-math"
#endif
_Static_assert(sizeof(float)==4 && sizeof(int)==4 && sizeof(long)>=8, "AO needs 32-bit IEEE float/int and 64-bit long");
typedef union block block;
union block {
  max_align_t alignment;
  struct { block *prev, *next; size_t bytes; } h;
};
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static struct {
  jmp_buf failure;
  oa_limits lim;
  const oa_cancel *cancel;
  oa_result result;
  block *blocks;
  uint64_t heap, live, work, math_since_poll;
  struct timespec wall_start, cpu_start;
  uint8_t *source;
  size_t source_size;
  int out_fd;
  FILE *input, *output;
  fenv_t saved_env;
  int env_saved;
} job;

static uint64_t ms_since(clockid_t clock, const struct timespec *start) {
  struct timespec now;
  if (clock_gettime(clock, &now)) return UINT64_MAX;
  int64_t ns=(int64_t)(now.tv_sec-start->tv_sec)*INT64_C(1000000000)+(now.tv_nsec-start->tv_nsec);
  return ns < 0 ? 0 : (uint64_t)ns/1000000;
}
static void fail(int status, const char *message) {
  job.result.status=status;
  job.result.system_errno=(status==OA_IO || status==OA_NO_MEMORY) ? errno : 0;
  snprintf(job.result.message,sizeof job.result.message,"%s",message);
  longjmp(job.failure,1);
}
static void poll_now(void) {
  if (job.cancel && job.cancel->poll && job.cancel->poll(job.cancel->user)) fail(OA_CANCELLED,"cancelled");
  if (job.work>job.lim.max_work_units) fail(OA_LIMIT,"work unit quota");
  if (ms_since(CLOCK_MONOTONIC,&job.wall_start)>=job.lim.max_wall_ms) fail(OA_LIMIT,"wall time quota");
  if (ms_since(CLOCK_THREAD_CPUTIME_ID,&job.cpu_start)>=job.lim.max_cpu_ms) fail(OA_LIMIT,"CPU time quota");
}
static void unit(void) {
  if (job.work==UINT64_MAX) fail(OA_LIMIT,"work counter overflow");
  ++job.work;
  if (++job.math_since_poll>=1024 || job.work>job.lim.max_work_units) {
    job.math_since_poll=0;
    poll_now();
  }
}
static void *tracked_malloc(size_t n) {
  poll_now();
  if (!n) n=1;
  if (n>SIZE_MAX-sizeof(block) || (uint64_t)n+sizeof(block)>job.lim.max_heap_bytes-job.heap)
    fail(OA_LIMIT,"heap byte quota");
  block *p=malloc(sizeof(block)+n);
  if (!p) fail(OA_NO_MEMORY,"malloc failed");
  p->h.bytes=sizeof(block)+n; p->h.prev=NULL; p->h.next=job.blocks;
  if (job.blocks) job.blocks->h.prev=p;
  job.blocks=p;
  job.heap+=p->h.bytes; ++job.live;
  if (job.heap>job.result.heap_peak_bytes) job.result.heap_peak_bytes=job.heap;
  return p+1;
}
static void tracked_free(void *v) {
  if (!v) return;
  block *p=(block*)v-1;
  if (p->h.prev) p->h.prev->h.next=p->h.next; else job.blocks=p->h.next;
  if (p->h.next) p->h.next->h.prev=p->h.prev;
  job.heap-=p->h.bytes; --job.live;
  free(p);
}
static void *tracked_calloc(size_t n,size_t sz) {
  if (sz && n>SIZE_MAX/sz) fail(OA_LIMIT,"calloc size overflow");
  size_t bytes=n*sz; void *p=tracked_malloc(bytes); memset(p,0,bytes); return p;
}
static void *tracked_realloc(void *v,size_t n) {
  if (!v) return tracked_malloc(n);
  poll_now();
  if (!n) { tracked_free(v); return NULL; }
  block *p=(block*)v-1;
  uint64_t without=job.heap-p->h.bytes;
  if (n>SIZE_MAX-sizeof(block) || (uint64_t)n+sizeof(block)>job.lim.max_heap_bytes-without)
    fail(OA_LIMIT,"realloc heap byte quota");
  block *q=realloc(p,n+sizeof(block));
  if (!q) fail(OA_NO_MEMORY,"realloc failed");
  if (q->h.prev) q->h.prev->h.next=q; else job.blocks=q;
  if (q->h.next) q->h.next->h.prev=q;
  q->h.bytes=n+sizeof(block); job.heap=without+q->h.bytes;
  if (job.heap>job.result.heap_peak_bytes) job.result.heap_peak_bytes=job.heap;
  return q+1;
}
/* libc's two FILE objects and qsort implementation may have small private
 * allocations outside this ledger. All algorithm/input/parser allocations are
 * tracked; max_triangles/max_source bound those libc operations independently. */
static FILE *controlled_fopen(const char *name,const char *mode) {
  poll_now();
  if (!strcmp(name,"oa-input") && !strcmp(mode,"rb") && !job.input) {
    job.input=fmemopen(job.source,job.source_size,"rb");
    if (!job.input) fail(OA_IO,"fmemopen input failed");
    setvbuf(job.input,NULL,_IONBF,0);
    return job.input;
  }
  if (!strcmp(name,"oa-output") && !strcmp(mode,"wb") && !job.output) {
    int fd=dup(job.out_fd);
    if (fd<0) fail(OA_IO,"dup output failed");
    job.output=fdopen(fd,"wb"); /* fdopen never opens/truncates a path. */
    if (!job.output) { int e=errno; close(fd); errno=e; fail(OA_IO,"fdopen output failed"); }
    setvbuf(job.output,NULL,_IONBF,0);
    if (fseek(job.output,0,SEEK_SET)) fail(OA_IO,"seek output failed");
    return job.output;
  }
  fail(OA_INTERNAL,"unexpected legacy fopen"); return NULL;
}
static int controlled_fclose(FILE *f) {
  poll_now();
  if (f==job.input) job.input=NULL;
  else if (f==job.output) job.output=NULL;
  else fail(OA_INTERNAL,"unexpected legacy fclose");
  if (fclose(f)) fail(OA_IO,"close/flush failed");
  poll_now(); return 0;
}
static size_t controlled_fread(void *p,size_t sz,size_t n,FILE *f) {
  poll_now(); size_t result=fread(p,sz,n,f);
  if (result!=n) fail(OA_IO,"short input read");
  poll_now(); return result;
}
static size_t controlled_fwrite(const void *p,size_t sz,size_t n,FILE *f) {
  poll_now();
  if (f!=job.output || (sz && n>SIZE_MAX/sz)) fail(OA_INTERNAL,"unexpected legacy fwrite");
  size_t bytes=sz*n;
  if (bytes>job.lim.max_output_bytes-job.result.output_bytes) fail(OA_LIMIT,"output byte quota");
  size_t result=fwrite(p,sz,n,f);
  job.result.output_bytes+=(uint64_t)result*sz;
  if (result!=n) fail(OA_IO,"short output write");
  poll_now(); return result;
}
static void controlled_qsort(void *base,size_t n,size_t sz,int (*cmp)(const void*,const void*)) {
  poll_now();
  if (n>job.lim.max_triangles) fail(OA_LIMIT,"sort triangle quota");
  qsort(base,n,sz,cmp);
  poll_now();
}
/* Instrument sqrt AND BVH box min/max: cancellation does not have to wait for
 * 1024 sqrt calls when a single ray visits many nodes. Arithmetic is unchanged. */
static float checked_sqrtf(float x) { unit(); return sqrtf(x); }
static float checked_fminf(float a,float b) { unit(); return fminf(a,b); }
static float checked_fmaxf(float a,float b) { unit(); return fmaxf(a,b); }
static float checked_powf(float a,float b) { unit(); return powf(a,b); }
static long checked_lrintf(float x) { if (!isfinite(x)) fail(OA_BAD_WPK,"nonfinite AO result"); unit(); return lrintf(x); }

static int quiet_printf(const char *format,...) { (void)format; return 0; }
static int quiet_fprintf(FILE *stream,const char *format,...) { (void)stream; (void)format; return 0; }
static int oa_legacy_main(int argc,char **argv);
#define main oa_legacy_main
#define malloc tracked_malloc
#define calloc tracked_calloc
#define realloc tracked_realloc
#define free tracked_free
#define fopen controlled_fopen
#define fclose controlled_fclose
#define fread controlled_fread
#define fwrite controlled_fwrite
#define qsort controlled_qsort
#define sqrtf checked_sqrtf
#define fminf checked_fminf
#define fmaxf checked_fmaxf
#define powf checked_powf
#define lrintf checked_lrintf
#define printf quiet_printf
#define fprintf quiet_fprintf
#define perror(...) ((void)0)
#include "../../stage/bake_ao.c"
#undef main
#undef malloc
#undef calloc
#undef realloc
#undef free
#undef fopen
#undef fclose
#undef fread
#undef fwrite
#undef qsort
#undef sqrtf
#undef fminf
#undef fmaxf
#undef powf
#undef lrintf
#undef printf
#undef fprintf
#undef perror

static uint16_t u16(size_t p) { return (uint16_t)(job.source[p]|((uint16_t)job.source[p+1]<<8)); }
static uint32_t u32(size_t p) {
  return (uint32_t)job.source[p]|((uint32_t)job.source[p+1]<<8)|((uint32_t)job.source[p+2]<<16)|((uint32_t)job.source[p+3]<<24);
}
static float f32(size_t p) { uint32_t x=u32(p); float f; memcpy(&f,&x,4); return f; }
static uint64_t range_end(uint32_t off,uint64_t bytes) {
  if (off>job.source_size || bytes>job.source_size-off) fail(OA_BAD_WPK,"WPK range outside source");
  return (uint64_t)off+bytes;
}
static int texture_index(uint16_t t,uint32_t nt) { return t==UINT16_MAX || t<nt; }
/* Independently validate every byte the legacy reader can address, before it is
 * entered. Tables must be ordered/disjoint, every batch has exactly one chunk.
 * Vertex/index/texture ranges are four-byte aligned (indices two-byte), within
 * the payload, and all nonempty payload regions must be mutually disjoint.
 * A zero texture data_size is an intentional inherited-texture reference for
 * aero packs, NOT a zero-sized texture: dimensions still must be nonzero. */
typedef struct region { uint32_t first; uint64_t end; } region;
static int region_cmp(const void *a,const void *b) {
  const region *x=a,*y=b; return x->first<y->first ? -1 : x->first>y->first;
}
static void validate(void) {
  const uint8_t *d=job.source;
  if (job.source_size<32 || memcmp(d,"WPK3",4)) fail(OA_BAD_WPK,"not a complete WPK3 header");
  uint32_t nt=u32(4),nc=u32(8),nb=u32(12),to=u32(20),co=u32(24),bo=u32(28);
  if (nt>job.lim.max_textures || nc>job.lim.max_chunks || nb>job.lim.max_batches)
    fail(OA_LIMIT,"WPK table count quota");
  if (!isfinite(f32(16)) || f32(16)<0) fail(OA_BAD_WPK,"bad WPK chunk size");
  uint64_t te=range_end(to,64ull*nt),ce=range_end(co,36ull*nc),be=range_end(bo,28ull*nb);
  if (to<32 || (to&3) || (co&3) || (bo&3) || co<te || bo<ce) fail(OA_BAD_WPK,"overlapping/misaligned WPK tables");
  uint8_t *owned=tracked_calloc(nb,1);
  size_t capacity=(size_t)nt+2*(size_t)nb;
  region *regions=tracked_malloc((capacity ? capacity : 1)*sizeof(region)); size_t nr=0;
  for (uint32_t c=0;c<nc;++c) {
    unit(); size_t r=(size_t)co+36ull*c;
    for (int k=0;k<6;++k) if (!isfinite(f32(r+4*k)) || fabsf(f32(r+4*k))>1e8f) fail(OA_BAD_WPK,"nonfinite/extreme chunk bounds");
    for (int k=0;k<3;++k) if (f32(r+4*k)>f32(r+12+4*k)) fail(OA_BAD_WPK,"reversed chunk bounds");
    uint32_t first=u32(r+24),n=u32(r+28),g=u32(r+32);
    if (first>nb || n>nb-first || g>UINT16_MAX) fail(OA_BAD_WPK,"bad chunk batch ownership/group");
    for (uint32_t i=first;i<first+n;++i) { unit(); if (owned[i]++) fail(OA_BAD_WPK,"duplicate batch ownership"); }
  }
  for (uint32_t t=0;t<nt;++t) {
    unit(); size_t r=(size_t)to+64ull*t;
    uint16_t w=u16(r+48),h=u16(r+50); uint32_t fmt=u32(r+52),off=u32(r+56),bytes=u32(r+60);
    if (!memchr(d+r,0,48)) fail(OA_BAD_WPK,"unterminated texture name");
    if (!w || !h || w>job.lim.max_texture_dimension || h>job.lim.max_texture_dimension || fmt>2)
      fail(OA_BAD_WPK,"bad texture dimensions/format");
    uint64_t end=range_end(off,bytes);
    if (bytes && (bytes!=2ull*w*h || off<be || (off&3))) fail(OA_BAD_WPK,"bad texture payload");
    if (bytes) regions[nr++]=(region){off,end};
  }
  uint64_t triangles=0;
  for (uint32_t b=0;b<nb;++b) {
    unit(); size_t r=(size_t)bo+28ull*b;
    uint32_t vo=u32(r+4),nv=u32(r+8),io=u32(r+12),ni=u32(r+16);
    if (!owned[b] || !texture_index(u16(r),nt) || d[r+20]>2 || d[r+21] || !texture_index(u16(r+22),nt) || !texture_index(u16(r+24),nt))
      fail(OA_BAD_WPK,"unowned batch or invalid material");
    if (nv>65536 || ni%3 || (ni && !nv)) fail(OA_BAD_WPK,"bad vertex/index count");
    uint64_t ve=range_end(vo,32ull*nv),ie=range_end(io,2ull*ni);
    if ((nv && (vo<be || (vo&3))) || (ni && (io<be || (io&1)))) fail(OA_BAD_WPK,"bad geometry range/alignment");
    if (nv) regions[nr++]=(region){vo,ve}; if (ni) regions[nr++]=(region){io,ie};
    triangles+=ni/3;
    if (triangles>job.lim.max_triangles) fail(OA_LIMIT,"triangle quota");
    for (uint32_t v=0;v<nv;++v) {
      unit(); size_t p=(size_t)vo+32ull*v;
      for (int k=0;k<5;++k) {
        float x=f32(p+4*k);
        if (!isfinite(x) || fabsf(x)>(k<3 ? 1e8f : 1e6f)) fail(OA_BAD_WPK,"nonfinite/extreme vertex position/UV");
      }
      /* normal components are packed signed int16, hence always finite. */
    }
    for (uint32_t i=0;i<ni;++i) { unit(); if (u16((size_t)io+2ull*i)>=nv) fail(OA_BAD_WPK,"index exceeds batch vertex count"); }
  }
  poll_now(); qsort(regions,nr,sizeof(region),region_cmp); poll_now();
  for (size_t i=1;i<nr;++i) { unit(); if (regions[i].first<regions[i-1].end) fail(OA_BAD_WPK,"overlapping payload regions"); }
  /* Same page-selection predicate as trusted algorithm, computed independently
   * solely to enforce max_maps and predict exact output quota before baking. */
  int8_t *pages=tracked_calloc(nt,1);
  for (uint32_t b=0;b<nb;++b) {
    unit(); size_t r=(size_t)bo+28ull*b; uint16_t t=u16(r);
    if (t<nt && d[r+20]==1 && !(u16(r+2)&3)) {
      int shadow=0;
      for (uint32_t c=0;c<nc;++c) { unit(); size_t cr=(size_t)co+36ull*c;
        if (b>=u32(cr+24) && b-u32(cr+24)<u32(cr+28)) { shadow=u32(cr+32)==0xffff; break; }
      }
      if (!shadow) pages[t]=1;
    }
  }
  for (uint32_t b=0;b<nb;++b) {
    unit(); size_t r=(size_t)bo+28ull*b; uint16_t t=u16(r); if (t>=nt || pages[t]<=0 || (u16(r+2)&3)) continue;
    if (d[r+20]!=1) {
      int unlit_story=0;
      for (uint32_t c=0;c<nc;++c) { unit(); size_t cr=(size_t)co+36ull*c;
        if (b>=u32(cr+24) && b-u32(cr+24)<u32(cr+28)) {
          uint32_t g=u32(cr+32); unlit_story=g>=0x180 && g<0x18a; break;
        }
      }
      if (unlit_story) continue;
    }
    for (uint32_t v=0;v<u32(r+8);++v) { unit(); size_t p=u32(r+4)+32ull*v;
      float u=f32(p+12),vv=f32(p+16); if (u<-.01f || u>1.01f || vv<-.01f || vv>1.01f) pages[t]=-1;
    }
  }
  uint64_t output=8; uint32_t maps=0;
  for (uint32_t t=0;t<nt;++t) { unit(); if (pages[t]>0) {
    ++maps; uint32_t w=u16((size_t)to+64ull*t+48),h=u16((size_t)to+64ull*t+50);
    while (w>job.lim.size || h>job.lim.size) { w=w>1?w/2:1; h=h>1?h/2:1; }
    output+=52+(uint64_t)w*h;
  } }
  if (maps>job.lim.max_maps) fail(OA_LIMIT,"AO map quota");
  if (output>job.lim.max_output_bytes) fail(OA_LIMIT,"predicted output byte quota");
  job.result.maps=maps; job.result.triangles=(uint32_t)triangles;
  tracked_free(pages); tracked_free(regions); tracked_free(owned); poll_now();
}
OA_API void oa_default_limits(oa_limits *l) {
  if (!l) return;
  *l=(oa_limits){sizeof *l,OA_ABI_VERSION,64ull<<20,256ull<<20,32ull<<20,
    UINT64_C(1000000000000),600000,600000,4096,16384,65536,200000,256,8192,256,96};
}
static int immediate(oa_result *r,int status,const char *message) {
  uint32_t size=r->struct_size;
  memset(r,0,sizeof *r); r->struct_size=size; r->abi_version=OA_ABI_VERSION; r->status=status;
  snprintf(r->message,sizeof r->message,"%s",message); return status;
}
static void reset_legacy(void) { file=NULL; file_size=0; cen=NULL; axis_sort=0; rng_state=0; }
OA_API int oa_bake_fd(int source_fd,int out_fd,const oa_limits *limits,const oa_cancel *cancel,oa_result *result) {
  if (!result || result->struct_size!=sizeof *result) return OA_INVALID_ARGUMENT;
  if (!limits || limits->struct_size!=sizeof *limits || limits->abi_version!=OA_ABI_VERSION ||
      (cancel && cancel->struct_size!=sizeof *cancel)) return immediate(result,OA_INVALID_ARGUMENT,"ABI struct size/version mismatch");
  oa_limits l=*limits;
  if (!l.max_source_bytes || l.max_source_bytes>(64ull<<20) || !l.max_heap_bytes || l.max_heap_bytes>(1ull<<30) ||
      !l.max_output_bytes || !l.max_work_units || !l.max_wall_ms || !l.max_cpu_ms ||
      !l.max_textures || l.max_textures>4096 || !l.max_chunks || l.max_chunks>16384 ||
      !l.max_batches || l.max_batches>65536 || !l.max_triangles || l.max_triangles>200000 ||
      !l.max_maps || l.max_maps>4096 || !l.max_texture_dimension || l.max_texture_dimension>8192 || l.size!=256 || l.rays!=96)
    return immediate(result,OA_INVALID_ARGUMENT,"invalid limits or unsupported AO recipe");
  const uint16_t endian=1;
  if (*(const uint8_t*)&endian!=1) return immediate(result,OA_INVALID_ARGUMENT,"little endian required");
  if (pthread_mutex_trylock(&lock)) return immediate(result,OA_BUSY,"AO backend already in use");
  memset(&job,0,sizeof job); reset_legacy(); job.lim=l; job.cancel=cancel; job.out_fd=out_fd;
  job.result.struct_size=sizeof job.result; job.result.abi_version=OA_ABI_VERSION;
  int clocks_ok=!clock_gettime(CLOCK_MONOTONIC,&job.wall_start) && !clock_gettime(CLOCK_THREAD_CPUTIME_ID,&job.cpu_start);
  if (!setjmp(job.failure)) {
    if (!clocks_ok) fail(OA_INTERNAL,"clock unavailable");
    poll_now();
    struct stat s,o; int sf=fcntl(source_fd,F_GETFL),of=fcntl(out_fd,F_GETFL);
    if (sf<0 || of<0 || fstat(source_fd,&s) || fstat(out_fd,&o) || !S_ISREG(s.st_mode) || !S_ISREG(o.st_mode) ||
        (sf&O_ACCMODE)==O_WRONLY || (of&O_ACCMODE)==O_RDONLY || (of&O_APPEND) ||
        (s.st_dev==o.st_dev && s.st_ino==o.st_ino) || o.st_size ||
        lseek(source_fd,0,SEEK_CUR)<0 || lseek(out_fd,0,SEEK_CUR)<0)
      fail(OA_BAD_FD,"FDs must be distinct regular/seekable files and output empty/writable/nonappend");
    if (s.st_size<32) fail(OA_BAD_WPK,"truncated WPK header");
    if ((uint64_t)s.st_size>l.max_source_bytes) fail(OA_LIMIT,"source byte quota");
    job.source_size=(size_t)s.st_size; job.result.source_bytes=job.source_size;
    job.source=tracked_malloc(job.source_size);
    size_t at=0;
    while (at<job.source_size) {
      poll_now(); size_t want=job.source_size-at; if (want>(1u<<20)) want=1u<<20;
      ssize_t n=pread(source_fd,job.source+at,want,(off_t)at);
      if (n<0 && errno==EINTR) continue;
      if (n<=0) fail(OA_IO,"pread source failed/shortened");
      at+=(size_t)n;
    }
    struct stat after;
    if (fstat(source_fd,&after) || after.st_size!=s.st_size) fail(OA_IO,"source changed during snapshot");
    validate();
    if (fegetenv(&job.saved_env)) fail(OA_INTERNAL,"floating environment unavailable");
    job.env_saved=1;
    if (fesetround(FE_TONEAREST)) fail(OA_INTERNAL,"floating rounding mode unavailable");
    char *args[]={"oa-bake","oa-input","oa-output","256","96",NULL};
    if (oa_legacy_main(5,args)) fail(OA_INTERNAL,"trusted AO algorithm failed");
    poll_now();
    job.result.status=OA_OK; snprintf(job.result.message,sizeof job.result.message,"ok");
  }
  /* No callback or throwing wrapper during cleanup; leaked legacy base/bs/page
   * allocations and every failure path are reclaimed by the same ledger. */
  if (job.input) { fclose(job.input); job.input=NULL; }
  if (job.output) { if (fclose(job.output) && job.result.status==OA_OK) { job.result.status=OA_IO; job.result.system_errno=errno; snprintf(job.result.message,sizeof job.result.message,"cleanup flush failed"); } job.output=NULL; }
  while (job.blocks) tracked_free(job.blocks+1);
  if (job.env_saved && fesetenv(&job.saved_env) && job.result.status==OA_OK) {
    job.result.status=OA_INTERNAL;
    snprintf(job.result.message,sizeof job.result.message,"floating environment restore failed");
  }
  reset_legacy();
  struct stat final;
  if (!fstat(out_fd,&final) && final.st_size>=0) job.result.output_bytes=(uint64_t)final.st_size;
  job.result.work_units=job.work; job.result.allocations_live=job.live;
  job.result.elapsed_wall_ms=ms_since(CLOCK_MONOTONIC,&job.wall_start);
  job.result.elapsed_cpu_ms=ms_since(CLOCK_THREAD_CPUTIME_ID,&job.cpu_start);
  *result=job.result;
  int status=job.result.status;
  job.source=NULL; job.cancel=NULL;
  pthread_mutex_unlock(&lock);
  return status;
}
