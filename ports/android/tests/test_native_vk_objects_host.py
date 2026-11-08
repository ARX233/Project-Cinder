#!/usr/bin/env python3
"""UBSan CPU contracts for the actual explicit native buffer/program include.

Only Vulkan/table/allocation effects are mocked. The production key/reflection,
program packet helpers and buffer busy/retirement code are extracted unchanged;
all shipped reflection rows are checked. No GL/context/VAO/unit declarations
exist, and no Vulkan loader, compiler tool or runtime shader acquisition is used.
This proves host contracts, not GPU/driver pixels or asynchronous GPU execution.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = "/Volumes/CodexWork" if sys.platform == "darwin" else tempfile.gettempdir()
OUT = Path(os.environ.get("TMPDIR", DEFAULT_OUT)).resolve()
# Never place canonical-checkout fixture outputs on the exFAT source volume.
if sys.platform == "darwin" and OUT != Path("/Volumes/CodexWork") and not str(OUT).startswith("/Volumes/CodexWork/"):
    OUT = Path("/Volumes/CodexWork")
OUT.mkdir(parents=True, exist_ok=True)
SOURCE = (ROOT / "src/vkgl.c").read_text()
NATIVE = (ROOT / "src/native_vk.inc").read_text()
OBJECTS = (ROOT / "src/native_vk_objects.inc").read_text()
SPV_PATH = ROOT / "src/vkgl_spv.c"
if not SPV_PATH.is_file() and os.environ.get("CINDER_PRIVATE_SRC"):
    SPV_PATH = Path(os.environ["CINDER_PRIVATE_SRC"]) / "vkgl_spv.c"
if not SPV_PATH.is_file():
    raise SystemExit("Reviewed generated SPIR-V catalog required; set CINDER_PRIVATE_SRC to its source directory (no placeholder/skip permitted)")
SPV = SPV_PATH.read_text()
VKGL_HEADER = (ROOT / "src/vkgl.h").read_text()


def typedef(text, name):
    end = text.index("} " + name + ";") + len("} " + name + ";")
    begin = text.rfind("typedef struct {", 0, end)
    assert begin >= 0, name
    return text[begin:end]


def function(text, start):
    begin = text.index(start)
    end = text.index("\n}", begin) + 2
    return text[begin:end]


# Keep only low-level helpers. No facade or compatibility context is declared.
for forbidden in (r"\bvkgl_\w+\s*\(", r"\b(?:ctx|cur_vao|cur_up|bound_buf|bound_tex)\s*\(",
                  r"\b(?:getenv|system|fopen|read_words|dump_program)\s*\(", r"\bsamp_unit\b"):
    assert not re.search(forbidden, OBJECTS), forbidden
assert "bufmem_try_new(" in OBJECTS and "bufmem_new(" not in OBJECTS
schema = "\n".join(typedef(SOURCE, n) for n in ("vbufmem", "vbuf", "vuni", "vprog"))
# vmem is opaque allocation bookkeeping in this fixture; no GL types needed.
schema = schema.replace("  int samp_unit[MAX_SAMP];\n", "")
spv_schema = typedef(VKGL_HEADER, "vkgl_spv")
key_reflect = "\n".join(function(SOURCE, s) for s in (
    "static uint64_t prog_key(", "static VkShaderModule shader_module(", "static int prog_reflect("))
retirement_schema = SOURCE[SOURCE.index("enum { DEAD_IMAGE"):SOURCE.index("static void fb_cache_forget(")]
retirement = "\n".join(function(SOURCE, s) for s in (
    "static void dead_add(", "static void bufmem_drop(", "static void dead_free("))
busy = SOURCE[SOURCE.index("static int bufmem_busy("):SOURCE.index("\n\nvoid vkgl_glBufferData(")]
packet_helpers = NATIVE[NATIVE.index("static int native_program_valid("):NATIVE.index("/* Only formats already supported")]
shipped = SPV.replace('#include "vkgl.h"', "").replace("VKGL_N_SPV", "SHIPPED_N_SPV").replace("VKGL_SPV", "SHIPPED_SPV")

prefix = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <limits.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#include "native_vk.h"
#define MAX_ATTR 8
#define MAX_SAMP 8
#define UBO_RANGE 4096
#define BUF_USAGE (VK_BUFFER_USAGE_VERTEX_BUFFER_BIT|VK_BUFFER_USAGE_INDEX_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_SRC_BIT)
#define H(T,n) ((T)(uintptr_t)(n))
typedef struct {int block; VkDeviceSize off,size;} vmem;
static int platform_native_profile = 1;
static struct {VkDevice dev;uint32_t uid;uint64_t serial,done;pthread_mutex_t lock;} D;
static unsigned rejects,buffer_allocs,buffer_alloc_failures,buffer_frees,buffer_gens,program_gens;
static unsigned module_calls,module_destroys,live_modules,command_calls;
static int allocation_failure,buffer_table_failure,program_table_failure,module_failure;
#define VKCHECK(x) do {VkResult r_=(x);(void)r_;} while(0)
#define GROW(p,n,c) do {if((n)>=(c)){size_t cap_=(c)?2*(c):16;void*q_=realloc((p),cap_*sizeof *(p));assert(q_);(p)=q_;(c)=cap_;}}while(0)
static void logf_(const char *fmt,...){(void)fmt;}
static void*xcalloc(size_t n,size_t size){void*p=calloc(n?n:1,size);assert(p);return p;}
static int native_reject(void){++rejects;return 0;}
static uint64_t done_serial(void){return D.done;}
static void image_free_now(void *p){(void)p;abort();}
static void mock_DestroyImageView(VkDevice d,VkImageView v,const VkAllocationCallbacks*a){(void)d;(void)v;(void)a;abort();}
static void mock_DestroyFramebuffer(VkDevice d,VkFramebuffer f,const VkAllocationCallbacks*a){(void)d;(void)f;(void)a;abort();}
#define vkDestroyImageView mock_DestroyImageView
#define vkDestroyFramebuffer mock_DestroyFramebuffer
static unsigned char module_live[1024];
static VkResult mock_CreateShaderModule(VkDevice d,const VkShaderModuleCreateInfo*c,const VkAllocationCallbacks*a,VkShaderModule*out){
  (void)a;assert(d==D.dev&&c->codeSize>=20&&!(c->codeSize%4)&&c->pCode[0]==0x07230203u);
  unsigned n=++module_calls;assert(n<sizeof module_live);if(module_failure==(int)n)return VK_ERROR_OUT_OF_DEVICE_MEMORY;
  module_live[n]=1;++live_modules;*out=H(VkShaderModule,n);return VK_SUCCESS;
}
static void mock_DestroyShaderModule(VkDevice d,VkShaderModule m,const VkAllocationCallbacks*a){
  (void)a;assert(d==D.dev);size_t n=(size_t)(uintptr_t)m;assert(n<sizeof module_live&&module_live[n]);
  module_live[n]=0;++module_destroys;--live_modules;
}
#define vkCreateShaderModule mock_CreateShaderModule
#define vkDestroyShaderModule mock_DestroyShaderModule
'''
mocks = r'''
#define CAP 64
static vbuf buffers[CAP];static vprog programs[CAP];
static vbuf*buf_get(uint32_t id){return id&&id<CAP&&buffers[id].used?&buffers[id]:NULL;}
static vprog*prog_get(uint32_t id){return id&&id<CAP&&programs[id].used?&programs[id]:NULL;}
static uint32_t buf_gen(void){++buffer_gens;if(buffer_table_failure)return 0;for(unsigned i=1;i<CAP;i++)if(!buffers[i].used){buffers[i]=(vbuf){.used=1};return i;}return 0;}
static uint32_t prog_gen(void){++program_gens;if(program_table_failure)return 0;for(unsigned i=1;i<CAP;i++)if(!programs[i].used){programs[i]=(vprog){.used=1};return i;}return 0;}
static void buf_release(uint32_t id){vbuf*b=buf_get(id);assert(b);b->used=0;}
static void prog_release(uint32_t id){vprog*p=prog_get(id);assert(p);p->used=0;}
static struct Allocation {vbufmem*m;unsigned char*bytes;int live;} allocations[1024];
static vbufmem*bufmem_try_new(VkDeviceSize bytes,VkBufferUsageFlags usage){
  assert(bytes&&bytes<=PTRDIFF_MAX&&usage==BUF_USAGE);++buffer_allocs;
  if(allocation_failure==1){++buffer_alloc_failures;return NULL;}
  assert(buffer_allocs<1024);vbufmem*m=xcalloc(1,sizeof *m);unsigned char*p=xcalloc((size_t)bytes,1);
  *m=(vbufmem){.buf=H(VkBuffer,buffer_allocs),.size=bytes,.map=p};
  allocations[buffer_allocs]=(struct Allocation){m,p,1};
  if(allocation_failure==2)m->map=NULL;
  if(allocation_failure==3)m->buf=VK_NULL_HANDLE;
  if(allocation_failure==4)++m->size;
  return m;
}
static void bufmem_free(vbufmem*m){
  assert(m);for(unsigned i=1;i<=buffer_allocs;i++)if(allocations[i].m==m&&allocations[i].live){
    allocations[i].live=0;free(allocations[i].bytes);free(m);++buffer_frees;return;
  }abort();
}
static int backing_live(const vbufmem*m){for(unsigned i=1;i<=buffer_allocs;i++)if(allocations[i].m==m&&allocations[i].live)return 1;return 0;}
static vkgl_spv VKGL_SPV[1];static const int VKGL_N_SPV=1;
static const uint32_t valid_words[]={0x07230203,0x10000,0,1,0};
'''
tests = r'''
static const char *attributes[]={"aPos","aUV"};
static char reflection[2048];
static void reset(void){
  assert(!live_modules);for(unsigned i=1;i<CAP;i++)assert(!buffers[i].used&&!programs[i].used);
  dead_free(UINT64_MAX);assert(!n_dead);assert(buffer_allocs==buffer_frees+buffer_alloc_failures);
  memset(allocations,0,sizeof allocations);memset(module_live,0,sizeof module_live);
  rejects=buffer_allocs=buffer_alloc_failures=buffer_frees=buffer_gens=program_gens=module_calls=module_destroys=command_calls=0;
  allocation_failure=buffer_table_failure=program_table_failure=module_failure=0;
  D.dev=H(VkDevice,1);D.serial=19;D.done=17;
}
static uint32_t create_program(void){return cinder_vk_program_create("vertex","fragment",attributes,2);}
static void entry(const char*tail,int alternate){
  snprintf(reflection,sizeof reflection,"%016llx %s",(unsigned long long)prog_key("vertex","fragment",attributes,2),tail);
  VKGL_SPV[0]=(vkgl_spv){reflection,valid_words,5,valid_words,5,alternate?valid_words:NULL,alternate?5:0,alternate?valid_words:NULL,alternate?5:0};
}
static void buffer_creation(void){
  reset();unsigned char data[]={1,2,3,4,5,6,7,8};
  uint32_t id=cinder_vk_buffer_create(sizeof data,data);assert(id&&buffer_gens==1&&buffer_allocs==1);
  vbufmem*m=buf_get(id)->m;assert(m->size==sizeof data&&!memcmp(m->map,data,sizeof data));
  data[0]=99;assert(m->map[0]==1); /* copied, never borrowed */
  uint16_t index;memcpy(&index,m->map+2,2);assert(index==0x0403); /* bounded index inspection */
  cinder_vk_buffer_destroy(id);assert(!buf_get(id)&&n_dead==1&&backing_live(m));
  dead_free(18);assert(backing_live(m));dead_free(19);assert(!backing_live(m));
  id=cinder_vk_buffer_create(1,NULL);assert(id&&buf_get(id)->m->size==1&&buf_get(id)->m->map[0]==0);
  cinder_vk_buffer_destroy(id);dead_free(19);
  unsigned before=buffer_allocs,gens=buffer_gens;
  assert(!cinder_vk_buffer_create(0,NULL));assert(!cinder_vk_buffer_create(0,data));
  assert(!cinder_vk_buffer_create(SIZE_MAX,data));assert(!cinder_vk_buffer_create((size_t)PTRDIFF_MAX+1,NULL));
  D.dev=VK_NULL_HANDLE;assert(!cinder_vk_buffer_create(8,data));D.dev=H(VkDevice,1);
  assert(buffer_allocs==before&&buffer_gens==gens&&!command_calls);
  for(int fail=1;fail<=4;fail++){allocation_failure=fail;assert(!cinder_vk_buffer_create(8,data));assert(buffer_gens==gens);}
  /* Null-return allocations have no object to free. */
  assert(buffer_frees+buffer_alloc_failures==buffer_allocs);
  allocation_failure=0;buffer_table_failure=1;assert(!cinder_vk_buffer_create(8,data));
  assert(buffer_frees+buffer_alloc_failures==buffer_allocs);
  buffer_table_failure=0;assert(!command_calls);
  puts("PASS buffer create exact bounds, copied map/index bytes, NULL zero fill, failures never published");
}
static void buffer_updates(void){
  reset();const unsigned char source[]={0,1,2,3,4,5,6,7};const unsigned char patch[]={40,41,42};
  uint32_t id=cinder_vk_buffer_create(sizeof source,source);vbufmem*m=buf_get(id)->m;
  assert(cinder_vk_buffer_update(id,2,sizeof patch,patch));assert(buf_get(id)->m==m&&!n_dead);
  const unsigned char expected[]={0,1,40,41,42,5,6,7};assert(!memcmp(m->map,expected,8));
  assert(cinder_vk_buffer_update(id,1,4,m->map));const unsigned char overlap[]={0,0,1,40,41,5,6,7};assert(!memcmp(m->map,overlap,8));
  unsigned allocs=buffer_allocs;size_t retired=n_dead;unsigned char copy[8];memcpy(copy,m->map,8);
  assert(cinder_vk_buffer_update(id,8,0,NULL));assert(cinder_vk_buffer_update(id,0,0,NULL));
  assert(!cinder_vk_buffer_update(id,9,0,NULL));assert(!cinder_vk_buffer_update(id,7,2,patch));
  assert(!cinder_vk_buffer_update(id,SIZE_MAX,1,patch));assert(!cinder_vk_buffer_update(id,1,SIZE_MAX,patch));
  assert(!cinder_vk_buffer_update(id,0,1,NULL));assert(!cinder_vk_buffer_update(0,0,0,NULL));
  assert(!cinder_vk_buffer_update(UINT32_MAX,0,0,NULL));assert(!cinder_vk_buffer_update(CAP-1,0,0,NULL));
  assert(!command_calls&&buffer_allocs==allocs&&n_dead==retired&&!memcmp(copy,m->map,8));
  D.dev=VK_NULL_HANDLE;assert(!cinder_vk_buffer_update(id,0,1,patch));D.dev=H(VkDevice,1);
  unsigned char*map=m->map;m->map=NULL;assert(!cinder_vk_buffer_update(id,0,0,NULL));m->map=map;
  VkDeviceSize size=m->size;m->size=(VkDeviceSize)PTRDIFF_MAX+1;assert(!cinder_vk_buffer_update(id,0,1,patch));m->size=size;
  m->serial=D.serial; /* an already recorded draw owns m */
  assert(cinder_vk_buffer_update(id,8,0,NULL)&&buf_get(id)->m==m&&buffer_allocs==allocs);
  for(int fail=1;fail<=4;fail++){
    allocation_failure=fail;assert(!cinder_vk_buffer_update(id,3,2,patch));
    assert(buf_get(id)->m==m&&!memcmp(copy,m->map,8)&&n_dead==retired);
  }
  allocation_failure=0;
  assert(cinder_vk_buffer_update(id,4,3,m->map+1));vbufmem*n=buf_get(id)->m;
  assert(n!=m&&backing_live(m)&&n_dead==retired+1&&!memcmp(copy,m->map,8));
  const unsigned char cow[]={0,0,1,40,0,1,40,7};assert(!memcmp(n->map,cow,8));
  dead_free(18);assert(backing_live(m));D.done=19;dead_free(19);assert(!backing_live(m));
  /* Even done==current must COW: commands recorded in current frame are not submitted yet. */
  n->serial=D.serial;assert(cinder_vk_buffer_update(id,0,1,patch));vbufmem*third=buf_get(id)->m;assert(third!=n);
  D.serial=20;third->serial=25;assert(cinder_vk_buffer_update(id,1,1,patch));vbufmem*last=buf_get(id)->m;
  assert(n_dead==2&&dead[1].serial==25);dead_free(24);assert(!backing_live(n)&&backing_live(third));
  cinder_vk_buffer_destroy(id);assert(!buf_get(id)&&backing_live(last));
  cinder_vk_buffer_destroy(id);cinder_vk_buffer_destroy(0);cinder_vk_buffer_destroy(UINT32_MAX);
  dead_free(24);assert(!backing_live(last)&&backing_live(third));dead_free(25);assert(!backing_live(third));
  assert(!cinder_vk_buffer_update(id,0,0,NULL)&&!command_calls);
  /* Table IDs can be recycled without ever changing an older backing's bytes. */
  id=cinder_vk_buffer_create(8,source);vbufmem*held=buf_get(id)->m;held->serial=30;cinder_vk_buffer_destroy(id);
  uint32_t reused=cinder_vk_buffer_create(8,NULL);assert(reused==id&&buf_get(reused)->m!=held&&backing_live(held));
  assert(!memcmp(held->map,source,8));cinder_vk_buffer_destroy(reused);dead_free(29);assert(backing_live(held));dead_free(30);
  puts("PASS explicit update spans/no-op/overlap; COW preserves current and in-flight backing until retirement");
}
static void valid_programs(void){
  reset();entry("96 3 uProj:6:0 uMul:4:64 uAdd:4:80 uTex:7:1 uCube:8:2",1);
  uint32_t id=create_program();assert(id&&module_calls==4&&live_modules==4&&program_gens==1);
  vprog*p=prog_get(id);uint32_t uid=p->uid;assert(uid&&!p->shadow&&!p->dirty&&p->n_uni==5&&p->n_samp==2&&p->samp_cube[1]);
  assert(cinder_vk_program_ready(id)&&!cinder_vk_program_ready(0)&&!cinder_vk_program_ready(UINT32_MAX));
  cinder_vk_draw d;assert(cinder_vk_draw_init(&d,id,0,64,48)&&d.uniform_bytes==96);float m[16]={1},color[4]={1,2,3,4};
  assert(cinder_vk_uniform(&d,"uProj",m,sizeof m)&&cinder_vk_uniform(&d,"uMul",color,sizeof color));
  assert(cinder_vk_texture(&d,"uTex",19)&&cinder_vk_texture(&d,"uCube",20)&&d.textures[0]==19&&d.textures[1]==20);
  assert(!p->shadow); /* readiness and UI packet setters never require a GL uniform shadow */
  cinder_vk_program_destroy(id);assert(!prog_get(id)&&!cinder_vk_program_ready(id)&&!live_modules&&module_destroys==4);
  cinder_vk_program_destroy(id);cinder_vk_program_destroy(0);cinder_vk_program_destroy(UINT32_MAX);assert(module_destroys==4);
  id=create_program();assert(id&&prog_get(id)->uid>uid); /* cache identity survives a recycled table ID */
  cinder_vk_program_destroy(id);
  entry("0 0",0);id=create_program();assert(id&&cinder_vk_program_ready(id)&&!prog_get(id)->shadow);
  assert(cinder_vk_draw_init(&d,id,0,64,48)&&!d.uniform_bytes);cinder_vk_program_destroy(id);
  entry("32 1 uVec:3:0 uFloat:1:12 uInt:5:16 uTex:7:1",0);id=create_program();assert(id);cinder_vk_program_destroy(id);
  /* Every shipped row passes the stricter immutable schema, without shader tools. */
  for(int i=0;i<SHIPPED_N_SPV;i++){char key[17];memcpy(key,SHIPPED_SPV[i].refl,16);key[16]=0;
    assert(native_object_reflection(SHIPPED_SPV[i].refl,key));assert(native_object_spirv(SHIPPED_SPV[i].vs,SHIPPED_SPV[i].n_vs));
    assert(native_object_spirv(SHIPPED_SPV[i].fs,SHIPPED_SPV[i].n_fs));vprog tmp={0};assert(!prog_reflect(&tmp,SHIPPED_SPV[i].refl));
    assert(native_object_uniforms(&tmp));native_object_program_free(&tmp);
  }
  assert(!command_calls);puts("PASS actual prog_key/reflection, shipped layouts, shadow-free UI readiness/setters, immutable cache UID and destroy");
}
static void invalid_programs(void){
  reset();entry("16 1 uFloat:1:0",0);unsigned calls=module_calls,gens=program_gens;const char*bad[]={NULL};
  assert(!cinder_vk_program_create(NULL,"fragment",attributes,2));assert(!cinder_vk_program_create("vertex",NULL,attributes,2));
  assert(!cinder_vk_program_create("","fragment",attributes,2));assert(!cinder_vk_program_create("vertex","",attributes,2));
  assert(!cinder_vk_program_create("vertex","fragment",NULL,1));assert(!cinder_vk_program_create("vertex","fragment",bad,1));
  bad[0]="";assert(!cinder_vk_program_create("vertex","fragment",bad,1));
  const char*duplicate[]={"aPos","aPos"};assert(!cinder_vk_program_create("vertex","fragment",duplicate,2));
  assert(!cinder_vk_program_create("vertex","fragment",attributes,-1));assert(!cinder_vk_program_create("vertex","fragment",attributes,9));
  assert(!cinder_vk_program_create("missing","fragment",attributes,2));
  D.dev=VK_NULL_HANDLE;assert(!create_program());D.dev=H(VkDevice,1);
  assert(module_calls==calls&&program_gens==gens);
  VKGL_SPV[0].refl=NULL;assert(!create_program());VKGL_SPV[0].refl="short";assert(!create_program());
  const char*invalid[]={"", "-1 0", "4097 0", "1 0", "16", "16 -1", "16 256", "16 9999999999999999999999999", "999999999999999999999999 1",
    "16 1 nonsense", "16 1 :1:0", "16 1 x:0:0", "16 1 x:9:0", "16 1 x:1:-1", "16 1 x:1:9999999999999999999999999", "16 1 x:1:16",
    "16 1 x:6:0", "16 1 x:2:4", "16 1 x:1:0:3", "16 1 x:7:0", "16 1 x:8:2", "16 1 x:7:9", "16 1 x:7:1 y:7:1",
    "16 1 x:1:0 x:1:4", "16 1 x:3:0 y:1:8", "16 1 abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUV:1:0",
    "16 1 x:1:0\t", "16 1 0bad:1:0", "16 1 x:1:0 y:7:1 z:8:3"};
  for(size_t i=0;i<sizeof invalid/sizeof *invalid;i++){entry(invalid[i],0);assert(!create_program());assert(module_calls==calls&&program_gens==gens&&!live_modules);}
  entry("16 1 x:1:0",0);VKGL_SPV[0].vs=NULL;assert(!create_program());
  entry("16 1 x:1:0",0);VKGL_SPV[0].n_vs=-1;assert(!create_program());
  entry("16 1 x:1:0",0);VKGL_SPV[0].n_fs=4;assert(!create_program());
  uint32_t corrupt[5]={0};entry("16 1 x:1:0",0);VKGL_SPV[0].fs=corrupt;assert(!create_program());
  entry("16 1 x:1:0",1);VKGL_SPV[0].n_fs2=0;assert(!create_program());
  entry("16 1 x:1:0",1);VKGL_SPV[0].vs2=NULL;assert(!create_program());
  assert(module_calls==calls&&program_gens==gens&&!command_calls);
  /* No attribs is legal input (still must match a precompiled table key). */
  snprintf(reflection,sizeof reflection,"%016llx 0 0",(unsigned long long)prog_key("vertex","fragment",NULL,0));
  entry("0 0",0);snprintf(reflection,sizeof reflection,"%016llx 0 0",(unsigned long long)prog_key("vertex","fragment",NULL,0));
  uint32_t id=cinder_vk_program_create("vertex","fragment",NULL,0);assert(id);cinder_vk_program_destroy(id);
  puts("PASS missing/invalid source keys, strict reflection/type/alignment/range/schema and SPIR-V pair admission");
}
static void module_failures(void){
  for(int fail=1;fail<=4;fail++){
    reset();entry("16 1 uFloat:1:0 uTex:7:1",1);module_failure=fail;
    assert(!create_program());assert(!live_modules&&module_calls==(unsigned)fail&&module_destroys==(unsigned)fail-1&&!program_gens);
  }
  reset();entry("16 1 uFloat:1:0",1);program_table_failure=1;
  assert(!create_program()&&module_calls==4&&module_destroys==4&&!live_modules&&program_gens==1);
  program_table_failure=0;D.uid=UINT32_MAX;unsigned gens=program_gens;
  assert(!create_program()&&D.uid==UINT32_MAX&&!live_modules&&program_gens==gens);
  assert(!command_calls);puts("PASS every partial base/highp module failure, table exhaustion, UID-wrap fail-closed and cleanup");
}
int main(void){pthread_mutex_init(&D.lock,NULL);buffer_creation();buffer_updates();valid_programs();invalid_programs();module_failures();reset();free(dead);pthread_mutex_destroy(&D.lock);puts("native Vulkan objects: production implementation CPU PASS (NOT GPU validation)");return 0;}
'''

with tempfile.TemporaryDirectory(prefix="native-vk-objects-", dir=OUT) as temp:
    temp = Path(temp)
    env = dict(os.environ, TMPDIR=str(temp), TMP=str(temp), TEMP=str(temp),
               HOME=str(temp), XDG_CACHE_HOME=str(temp), PYTHONDONTWRITEBYTECODE="1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    fixture = temp / "objects.c"
    fixture.write_text(prefix + "\n" + schema + "\n" + spv_schema + "\n" + mocks + "\n" +
                       retirement_schema + "\n" + retirement + "\n" + busy + "\n" + key_reflect + "\n" +
                       packet_helpers + "\n" + shipped + '\n#include "native_vk_objects.inc"\n' + tests)
    flags = ["-I", str(ROOT / "src")]
    if sys.platform == "darwin":
        flags += ["-I", "/opt/homebrew/include"]
    sanitizers = os.environ.get("NATIVE_VK_SANITIZERS", "undefined" if sys.platform == "darwin" else "address,undefined")
    command = [os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers", *flags,
               "-fsanitize=" + sanitizers, "-fno-omit-frame-pointer", "-pthread", str(fixture), "-o", str(temp / "objects")]
    subprocess.run(command, cwd=temp, env=env, check=True, timeout=120)
    subprocess.run([str(temp / "objects")], cwd=temp, env=env, check=True, timeout=30)
    print("sanitizers", sanitizers)
print("native_vk_objects.inc sha256", hashlib.sha256(OBJECTS.encode()).hexdigest())
print("native_vk_objects fixture sha256", hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
