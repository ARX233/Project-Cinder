#!/usr/bin/env python3
"""Compile real native upload helpers under UBSan with allocation/begin faults.

No GL/context declarations or Vulkan implementation is linked. The production
legacy ring implementation is a positive-trace oracle, never a fault-path mock.
The actual native include executes checked realloc and bufmem_try_new boundary
failures; this does not claim GPU/driver/submitted-device-loss recovery.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("TMPDIR", str(ROOT.parent / "round3-objects"))).resolve()
if sys.platform == "darwin" and not str(OUT).startswith("/Volumes/"):
    OUT = ROOT.parent / "round3-objects"
OUT.mkdir(parents=True, exist_ok=True)
SOURCE = (ROOT / "src/vkgl.c").read_text()
UPLOAD = (ROOT / "src/native_vk_upload.inc").read_text()
assert not re.search(r"\b(?:abort|GROW|ctx|cur_up|vkgl_\w+)\s*\(", UPLOAD)
assert "bufmem_try_new(" in UPLOAD and "bufmem_new(" not in UPLOAD


def typedef(name):
    end = SOURCE.index("} " + name + ";") + len("} " + name + ";")
    begin = SOURCE.rfind("typedef struct {", 0, end)
    assert begin >= 0
    return SOURCE[begin:end]


def function(start):
    begin = SOURCE.index(start)
    return SOURCE[begin:SOURCE.index("\n}", begin) + 2]


schema = "\n".join(typedef(n) for n in ("vbufmem", "ring", "uploader"))
legacy = function("static uint8_t *ring_alloc(").replace("ring_alloc(", "legacy_ring_alloc(")
reset_ring = function("static void ring_reset(")
prefix = r'''
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define H(T,n) ((T)(uintptr_t)(n))
typedef struct {int block;VkDeviceSize off,size;}vmem;
'''
mocks = r'''
static unsigned buffer_attempts,buffer_live,buffer_frees,realloc_calls,begin_calls;
static int buffer_fail,realloc_fail,begin_fail;
static struct {vbufmem*m;uint8_t*map;int live;} allocated[16384];
static vbufmem *bufmem_try_new(VkDeviceSize size,VkBufferUsageFlags usage){
  assert(size&&size<=PTRDIFF_MAX);unsigned i=++buffer_attempts;assert(i<16384);
  if(buffer_fail==1||size>(1u<<20))return NULL;
  vbufmem*m=calloc(1,sizeof *m);uint8_t*map=calloc((size_t)size,1);assert(m&&map);
  *m=(vbufmem){.buf=H(VkBuffer,i),.map=map,.size=size};allocated[i].m=m;allocated[i].map=map;allocated[i].live=1;++buffer_live;
  assert(usage==(VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT));
  if(buffer_fail==2)m->map=NULL;if(buffer_fail==3)m->buf=VK_NULL_HANDLE;if(buffer_fail==4)++m->size;
  return m;
}
static void bufmem_free(vbufmem*m){
  assert(m);for(unsigned i=1;i<=buffer_attempts;i++)if(allocated[i].m==m&&allocated[i].live){
    allocated[i].live=0;free(allocated[i].map);free(m);--buffer_live;++buffer_frees;return;
  }assert(0);
}
static vbufmem*bufmem_new(VkDeviceSize n,VkBufferUsageFlags usage){vbufmem*m=bufmem_try_new(n,usage);assert(m);return m;}
static void*checked_test_realloc(void*p,size_t n){++realloc_calls;if(realloc_fail)return NULL;return realloc(p,n);}
static VkResult checked_test_begin(VkCommandBuffer c,const VkCommandBufferBeginInfo*b){
  assert(c&&b&&b->sType==VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO&&b->flags==VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT);
  ++begin_calls;return begin_fail?VK_ERROR_INITIALIZATION_FAILED:VK_SUCCESS;
}
#define realloc checked_test_realloc
#define vkBeginCommandBuffer checked_test_begin
#define GROW(p,n,c) do{if((n)>=(c)){size_t z_=(c)?(c)*2:64;void*q_=realloc((p),z_*sizeof *(p));assert(q_);(p)=q_;(c)=z_;}}while(0)
'''
tests = r'''
static ring make_ring(void){return (ring){.chunk=64,.usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT};}
static void free_ring(ring*r){for(size_t i=0;i<r->n;i++)bufmem_free(r->b[i]);free(r->b);*r=(ring){0};}
static void equal_trace(ring*n,ring*l,VkDeviceSize bytes,VkDeviceSize align){
  VkBuffer nb=VK_NULL_HANDLE,lb=VK_NULL_HANDLE;VkDeviceSize no=UINT64_MAX,lo=UINT64_MAX;
  uint8_t*np=native_ring_alloc(n,bytes,align,&nb,&no),*lp=legacy_ring_alloc(l,bytes,align,&lb,&lo);
  assert(np&&lp&&no==lo&&no%align==0);assert(n->i==l->i&&n->n==l->n&&n->cap==l->cap&&n->used==l->used);
  assert(nb==n->b[n->i]->buf&&lb==l->b[l->i]->buf);assert(np==n->b[n->i]->map+no&&lp==l->b[l->i]->map+lo);
  for(size_t i=0;i<n->n;i++)assert(n->b[i]->size==l->b[i]->size);
  memset(np,0x5a,(size_t)bytes);memset(lp,0x5a,(size_t)bytes);
}
static void legacy_traces(void){
  ring n=make_ring(),l=make_ring();
  const VkDeviceSize sizes[]={1,2,13,30,3,128,1,64,4,11,17,8};
  const VkDeviceSize align[]={1,2,16,8,3,16,64,1,7,3,4,16};
  for(int round=0;round<3;round++){
    ring_reset(&n);ring_reset(&l);
    for(size_t i=0;i<sizeof sizes/sizeof *sizes;i++)equal_trace(&n,&l,sizes[i],align[i]);
  }
  uint32_t state=31;
  for(int i=0;i<2000;i++){
    state=state*1664525u+1013904223u;VkDeviceSize size=1+(state%128);
    state=state*1664525u+1013904223u;VkDeviceSize alignment=1+(state%33);
    equal_trace(&n,&l,size,alignment);
    if(i%137==0){ring_reset(&n);ring_reset(&l);}
  }
  free_ring(&n);free_ring(&l);assert(!buffer_live);
  puts("PASS production legacy/native traces: exact size/offset/alignment/cursors/capacity/backing reuse (2012+ requests)");
}
static void assert_unchanged(const ring*r,const ring*before,VkBuffer b,VkDeviceSize o,unsigned live){
  assert(!memcmp(r,before,sizeof *r)&&b==H(VkBuffer,123456)&&o==777&&buffer_live==live);
}
static void allocation_faults(void){
  ring r=make_ring();VkBuffer b;VkDeviceSize o;
  for(int fail=1;fail<=4;fail++){
    ring before=r;unsigned live=buffer_live,rc=realloc_calls;b=H(VkBuffer,123456);o=777;buffer_fail=fail;
    assert(!native_ring_alloc(&r,5,16,&b,&o));assert_unchanged(&r,&before,b,o,live);assert(realloc_calls==rc);
  }
  buffer_fail=0;realloc_fail=1;ring before=r;unsigned live=buffer_live,frees=buffer_frees;b=H(VkBuffer,123456);o=777;
  assert(!native_ring_alloc(&r,5,16,&b,&o));assert_unchanged(&r,&before,b,o,live);assert(buffer_frees==frees+1);
  realloc_fail=0;assert(native_ring_alloc(&r,64,1,&b,&o));assert(r.i==0&&r.used==64&&r.n==1);
  /* Simulate a full one-slot table; growth must preserve old backing/map/cursor on failure. */
  r.cap=1;uint8_t*old=r.b[0]->map;memset(old,0x32,64);
  for(int fail=1;fail<=4;fail++){
    before=r;live=buffer_live;buffer_fail=fail;b=H(VkBuffer,123456);o=777;
    assert(!native_ring_alloc(&r,8,16,&b,&o));assert_unchanged(&r,&before,b,o,live);assert(r.b[0]->map==old&&old[63]==0x32);
  }
  buffer_fail=0;realloc_fail=1;before=r;live=buffer_live;frees=buffer_frees;b=H(VkBuffer,123456);o=777;
  assert(!native_ring_alloc(&r,8,16,&b,&o));assert_unchanged(&r,&before,b,o,live);assert(buffer_frees==frees+1&&old[0]==0x32);
  realloc_fail=0;assert(native_ring_alloc(&r,8,16,&b,&o));assert(r.n==2&&r.i==1&&r.used==8&&r.cap==2&&o==0);
  /* Space in existing table must not invoke realloc. */
  ring_reset(&r);unsigned rc=realloc_calls,attempts=buffer_attempts;
  assert(native_ring_alloc(&r,2,3,&b,&o)&&o==0);assert(native_ring_alloc(&r,2,3,&b,&o)&&o==3);
  assert(realloc_calls==rc&&buffer_attempts==attempts);free_ring(&r);assert(!buffer_live);
  puts("PASS actual native realloc/try-buffer faults: no backing/cursor/output publication, partial backing freed, retry succeeds");
}
static void invalid_requests(void){
  ring r=make_ring();VkBuffer b;VkDeviceSize o;
  assert(!native_ring_alloc(NULL,1,1,&b,&o));assert(!native_ring_alloc(&r,1,1,NULL,&o));assert(!native_ring_alloc(&r,1,1,&b,NULL));
  const VkDeviceSize sizes[]={0,(VkDeviceSize)PTRDIFF_MAX+1,UINT64_MAX};
  for(size_t i=0;i<sizeof sizes/sizeof *sizes;i++){
    ring before=r;unsigned live=buffer_live,attempts=buffer_attempts;b=H(VkBuffer,123456);o=777;
    assert(!native_ring_alloc(&r,sizes[i],1,&b,&o));assert_unchanged(&r,&before,b,o,live);assert(buffer_attempts==attempts);
  }
  ring before=r;unsigned live=buffer_live,attempts=buffer_attempts;b=H(VkBuffer,123456);o=777;
  assert(!native_ring_alloc(&r,1,0,&b,&o));assert_unchanged(&r,&before,b,o,live);assert(buffer_attempts==attempts);
  r.chunk=(VkDeviceSize)PTRDIFF_MAX+1;before=r;
  assert(!native_ring_alloc(&r,1,1,&b,&o));assert_unchanged(&r,&before,b,o,live);assert(buffer_attempts==attempts);r.chunk=64;
  r.i=1;before=r;assert(!native_ring_alloc(&r,1,1,&b,&o));assert_unchanged(&r,&before,b,o,live);r.i=0;
  r.n=1;before=r;assert(!native_ring_alloc(&r,1,1,&b,&o));assert_unchanged(&r,&before,b,o,live);r.n=0;
  r.cap=SIZE_MAX;before=r;assert(!native_ring_alloc(&r,1,1,&b,&o));assert_unchanged(&r,&before,b,o,live);r.cap=0;
  /* Exhausted synthetic table: doubling its byte count must fail before any dereference/allocation. */
  vbufmem*scratch[1]={0};ring huge=make_ring();huge.b=scratch;huge.i=huge.n=huge.cap=SIZE_MAX/sizeof *huge.b;
  ring huge_before=huge;assert(!native_ring_alloc(&huge,1,1,&b,&o));assert_unchanged(&huge,&huge_before,b,o,live);assert(buffer_attempts==attempts);
  r.used=UINT64_MAX;before=r;assert(!native_ring_alloc(&r,1,1,&b,&o));assert_unchanged(&r,&before,b,o,live);r.used=0;
  assert(native_ring_alloc(&r,1,1,&b,&o));
  /* General huge alignment rounds beyond this backing instead of wrapping to overwrite byte zero. */
  assert(native_ring_alloc(&r,1,UINT64_MAX,&b,&o)&&r.i==1&&o==0);
  before=r;live=buffer_live;uint8_t*map=r.b[1]->map;r.b[1]->map=NULL;
  ring invalid=r;b=H(VkBuffer,123456);o=777;
  assert(!native_ring_alloc(&r,1,1,&b,&o));assert_unchanged(&r,&invalid,b,o,live);r.b[1]->map=map;
  r.used=r.b[1]->size+1;invalid=r;assert(!native_ring_alloc(&r,1,1,&b,&o));assert_unchanged(&r,&invalid,b,o,live);r=before;
  free_ring(&r);assert(!buffer_live);
  puts("PASS size/align/counter/table/map bounds and overflow-safe rounding; invalid requests issue no allocation");
}
static void begin_faults(void){
  uploader u={0};unsigned calls=begin_calls;
  assert(!native_up_cmd(NULL)&&!native_up_cmd(&u)&&begin_calls==calls);
  u.pool=H(VkCommandPool,1);assert(!native_up_cmd(&u)&&begin_calls==calls);
  u.pool=VK_NULL_HANDLE;u.cmd=H(VkCommandBuffer,2);assert(!native_up_cmd(&u)&&begin_calls==calls);
  u.pool=H(VkCommandPool,1);begin_fail=1;assert(!native_up_cmd(&u)&&!u.open&&begin_calls==calls+1);
  assert(!native_up_cmd(&u)&&!u.open&&begin_calls==calls+2);
  begin_fail=0;assert(native_up_cmd(&u)==u.cmd&&u.open&&begin_calls==calls+3);
  begin_fail=1;assert(native_up_cmd(&u)==u.cmd&&u.open&&begin_calls==calls+3);
  u.open=0;assert(!native_up_cmd(&u)&&!u.open&&begin_calls==calls+4);begin_fail=0;
  puts("PASS actual checked begin failure never publishes open/cmd; valid/open uploader preserves one-begin behavior");
}
int main(void){legacy_traces();allocation_faults();invalid_requests();begin_faults();assert(!buffer_live);puts("native Vulkan upload helpers: production CPU UBSan PASS (NOT GPU validation)");return 0;}
'''

with tempfile.TemporaryDirectory(prefix="native-vk-upload-", dir=OUT) as directory:
    directory = Path(directory)
    env = dict(os.environ, TMPDIR=str(directory), TMP=str(directory), TEMP=str(directory),
               HOME=str(directory), XDG_CACHE_HOME=str(directory), PYTHONDONTWRITEBYTECODE="1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    fixture = directory / "upload.c"
    fixture.write_text(prefix + "\n" + schema + "\n" + mocks + "\n" + legacy + "\n" + reset_ring +
                       '\n#include "native_vk_upload.inc"\n' + tests)
    flags = ["-I", str(ROOT / "src")]
    if sys.platform == "darwin":
        flags += ["-I", "/opt/homebrew/include"]
    sanitizers = os.environ.get("NATIVE_VK_SANITIZERS", "undefined" if sys.platform == "darwin" else "address,undefined")
    cmd = [os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers",
           *flags, "-fsanitize=" + sanitizers, "-fno-omit-frame-pointer", str(fixture), "-o", str(directory / "upload")]
    subprocess.run(cmd, cwd=directory, env=env, check=True, timeout=120)
    subprocess.run([str(directory / "upload")], cwd=directory, env=env, check=True, timeout=30)
    print("sanitizers", sanitizers)
print("native_vk_upload.inc sha256", hashlib.sha256(UPLOAD.encode()).hexdigest())
print("upload host fixture sha256", hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
