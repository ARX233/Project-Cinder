#!/usr/bin/env python3
"""Compile the complete production native_vk.inc with real Vulkan types.

CPU executor-recording mocks only: this does not claim driver/GPU validation.
No context/VAO/program-shadow/sampler-unit fields exist in the fixture, so
accidental compatibility-state dependencies fail compilation. Every generated
file and compiler cache stays under caller-selected /Volumes/CodexWork.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("TMPDIR", "/Volumes/CodexWork")).resolve()
if not str(OUT).startswith("/Volumes/CodexWork/") and OUT != Path("/Volumes/CodexWork"):
    raise SystemExit("TMPDIR must be inside /Volumes/CodexWork")
SOURCE = (ROOT / "src/vkgl.c").read_text()
NATIVE = (ROOT / "src/native_vk.inc").read_text()
HEADER = (ROOT / "src/native_vk.h").read_text()


def typedef(name):
    end = SOURCE.index("} " + name + ";") + len("} " + name + ";")
    begin = SOURCE.rfind("typedef struct {", 0, end)
    if begin < 0:
        raise ValueError(name)
    return SOURCE[begin:end]


# Preserve the actual executor keys/item schema rather than duplicating them.
formats = re.search(r"static const VkFormat VFMT\[\] = \{.*?\n\};", SOURCE, re.S).group()
schema = "\n".join(typedef(n) for n in ("pkey", "dkey", "vop", "vitem"))
depth_helpers = SOURCE[SOURCE.index("static int is_depth("):SOURCE.index("#define VKGL_SSAO_DEPTH_USAGE")]
replay_start = SOURCE.index('static void replay_blit(')
replay_end = SOURCE.index('\nstatic void replay(', replay_start)
replay_blit = SOURCE[replay_start:replay_end]
usage_start = SOURCE.index('  VkImageUsageFlags att =', SOURCE.index('static vimg *image_new_usage('))
usage_end = SOURCE.index('  ci.initialLayout', usage_start)
usage_helper = '''static VkImageUsageFlags created_usage_explicit(int samples,int sampled,int transient,int lazy,int depth,VkImageUsageFlags requested_usage){
  VkFormat fmt=depth?VK_FORMAT_D24_UNORM_S8_UINT:VK_FORMAT_R8G8B8A8_UNORM;
  int comp=0,layers=1;vimg object={0},*im=&object;VkImageCreateInfo ci={0};D.lazy_type=lazy?0:~0u;
''' + SOURCE[usage_start:usage_end] + '''assert(im->usage==ci.usage);assert(!requested_usage||im->transient==!!(requested_usage&VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT));return im->usage;}
static VkImageUsageFlags created_usage(int samples,int sampled,int transient,int lazy,int depth){return created_usage_explicit(samples,sampled,transient,lazy,depth,0);}
'''
assert 'return image_new_usage(fmt, w, h, levels, layers, samples, sampled, transient, swz, 0);' in SOURCE
assert 'im->usage = ci.imageUsage;' in SOURCE and 'SCREEN.usage = S.n && S.img[0] ? S.img[0]->usage : 0;' in SOURCE
prefix = r'''
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#include "native_vk.h"
#define MAX_ATTR 8
#define MAX_SAMP 8
#define GL_INVALID_OPERATION 0x502
#define IT_DRAW 0
#define IT_CLEAR 1
#define OP_PASS 0
#define OP_BLIT 1
#define GL_COLOR_BUFFER_BIT 0x4000
#define GL_DEPTH_BUFFER_BIT 0x0100
#define GL_STENCIL_BUFFER_BIT 0x0400
#define H(T,n) ((T)(uintptr_t)(n))
typedef struct { VkFormat fmt; VkImageView view; unsigned level_mask; int layers,view_levels,samples; uint64_t serial; VkImage img; VkImageLayout rest; int in_rest,defined,transient; VkImageAspectFlags aspect; VkImageUsageFlags usage; } vimg;
typedef struct { VkBuffer buf; VkDeviceSize size; unsigned char *map; uint64_t serial; } vbufmem;
typedef struct { vbufmem *m; } vbuf;
typedef struct { vimg *im; } vtex;
typedef struct {char name[48]; int code,off;} vuni;
/* Deliberately NO shadow, dirty, ubo cache or sampler-unit members. */
typedef struct {VkShaderModule vs,fs; int block,n_samp,n_uni; uint32_t inputs,uid; int samp_cube[MAX_SAMP]; vuni *uni;} vprog;
'''
mocks = r'''
#define N_VFMT ((int)(sizeof VFMT/sizeof *VFMT))
typedef struct {VkFormat cfmt,dfmt;} Compat;
static Compat compats[2];
static VkFormat vfmt_dev[N_VFMT];
static struct {int w,h;} S={64,48};
static struct {uint64_t serial; unsigned lazy_type; struct {struct {VkDeviceSize minUniformBufferOffsetAlignment;} limits;} props;} D;
typedef struct {int id;} ring;
static struct Frame {ring vtx,ubo;} frame,*F=&frame;
static vprog programs[3]; static vuni uniforms[5];
static vimg images[9],*dummy2d=&images[4],*dummycube=&images[5];
#define SCREEN images[0]
static vbuf buffers[3];static vbufmem backing[3];static unsigned char bufferbytes[3][256];
static vtex textures[4];
static VkSampler dummy_sampler=H(VkSampler,700);
static VkPipelineLayout playout[9];
static vop *ops;static size_t n_ops,cap_ops;static long cur_pass=-1;
static vitem *items;static size_t n_items,cap_items;
static VkBuffer *vbb;static VkDeviceSize *vbo;static uint32_t *vbs;
static size_t n_vb,cap_vb,cap_vbo,cap_vbs;
static uint64_t frame_draws,compat_draw_count;
static unsigned pipeline_calls,descriptor_calls;static int pipeline_fail;
static uint64_t error_base;
#define errors (cinder_vk_error_epoch()-error_base)
static pkey last_key;static dkey last_descriptor;
#define GROW(p,n,c) do {if((n)>=(c)){size_t z=(c)?(c)*2:16;void*q=realloc((p),z*sizeof *(p));assert(q);(p)=q;(c)=z;}}while(0)
#pragma GCC poison set_err /* native failures must not write a compatibility context */
static vprog *prog_get(unsigned id){return id>0&&id<3?&programs[id]:NULL;}
static vbuf *buf_get(unsigned id){return id>0&&id<3?&buffers[id]:NULL;}
static vtex *tex_get(unsigned id){return id>0&&id<4?&textures[id]:NULL;}
static VkFormatFeatureFlags features;
static int fmt_has(VkFormat f,VkFormatFeatureFlags want){(void)f;return (features&want)==want;}
static int fb_target(unsigned id,vop*o){
  memset(o,0,sizeof *o);if(id>5)return 0;
  o->w=64;o->h=48;o->compat=id==1?1:0;o->screen=id==0;
  o->color=id==3?NULL:&images[id==0?0:1];o->depth=id==2?NULL:&images[2];
  if(id>=4){o->color=&images[id==4?7:8];o->depth=&images[6];if(id==5)o->resolve=&images[7];}
  return 1;
}
static void box_vk(const int*b,const vop*o,int*out){memcpy(out,b,4*sizeof(int));if(o->screen)out[1]=o->h-(b[1]+b[3]);}
static VkPipeline pipeline_get(const pkey*k,vprog*p,int*made){assert(p);if(made)*made=1;last_key=*k;++pipeline_calls;return pipeline_fail?VK_NULL_HANDLE:H(VkPipeline,800);}
static VkSampler sampler_for(const vtex*t,int levels){assert(t&&levels>0);return H(VkSampler,701);}
static cinder_vk_sampler last_sampler;static unsigned sampler_calls;static int sampler_fail;
static VkSampler cinder_vk_sampler_get(const cinder_vk_sampler*s,int levels){assert(s&&levels>0);last_sampler=*s;++sampler_calls;return sampler_fail?VK_NULL_HANDLE:H(VkSampler,702);}
static VkDescriptorSet desc_get(const dkey*k){last_descriptor=*k;++descriptor_calls;return H(VkDescriptorSet,900);}
static struct Allocation {unsigned char *data;size_t bytes;VkBuffer handle;} allocations[4096];static size_t n_alloc;
static unsigned char *ring_alloc(ring*r,VkDeviceSize size,VkDeviceSize align,VkBuffer*b,VkDeviceSize*offset){
  (void)r;assert(size&&align&&n_alloc<4096);struct Allocation *a=&allocations[n_alloc++];
  a->data=calloc(1,(size_t)size);assert(a->data);a->bytes=(size_t)size;a->handle=H(VkBuffer,n_alloc+1000);
  *b=a->handle;*offset=0;return a->data;
}
static struct Allocation *allocation(VkBuffer b){for(size_t i=0;i<n_alloc;i++)if(allocations[i].handle==b)return &allocations[i];abort();}
static unsigned gpu_blits,gpu_resolves;static VkImageBlit last_blit;static VkImageResolve last_resolve;
static int acquire(void){return 1;}
static vimg*real(vimg*im){return im;}
static void barrier(VkCommandBuffer c,vimg*im,int a,int b,int d,int e,VkImageLayout old,VkImageLayout next){(void)c;(void)im;(void)a;(void)b;(void)d;(void)e;(void)old;(void)next;}
static void fake_vkCmdBlitImage(VkCommandBuffer c,VkImage s,VkImageLayout sl,VkImage d,VkImageLayout dl,uint32_t n,const VkImageBlit*r,VkFilter filter){(void)c;(void)s;(void)sl;(void)d;(void)dl;(void)filter;assert(n==1);last_blit=*r;++gpu_blits;}
static void fake_vkCmdResolveImage(VkCommandBuffer c,VkImage s,VkImageLayout sl,VkImage d,VkImageLayout dl,uint32_t n,const VkImageResolve*r){(void)c;(void)s;(void)sl;(void)d;(void)dl;assert(n==1);last_resolve=*r;++gpu_resolves;}
#define vkCmdBlitImage fake_vkCmdBlitImage
#define vkCmdResolveImage fake_vkCmdResolveImage
'''
tests = r'''
static float quad[]={0,0,0,0, 1,0,1,0, 1,1,1,1, 0,1,0,1};
static void reset(void){
  for(size_t i=0;i<n_alloc;i++)free(allocations[i].data);n_alloc=0;
  n_ops=n_items=n_vb=0;cur_pass=-1;error_base=cinder_vk_error_epoch();pipeline_calls=descriptor_calls=sampler_calls=0;pipeline_fail=sampler_fail=0;F=&frame;
  memset(programs,0,sizeof programs);memset(images,0,sizeof images);memset(backing,0,sizeof backing);
  memset(&last_key,0,sizeof last_key);memset(&last_descriptor,0,sizeof last_descriptor);
  D.serial=19;D.props.limits.minUniformBufferOffsetAlignment=256;
  memcpy(vfmt_dev,VFMT,sizeof VFMT);
  uniforms[0]=(vuni){"uProj",6,0};uniforms[1]=(vuni){"uMul",4,64};uniforms[2]=(vuni){"uEye",3,80};
  uniforms[3]=(vuni){"uTex",7,1};uniforms[4]=(vuni){"uCube",8,2};
  programs[1]=(vprog){.vs=H(VkShaderModule,1),.fs=H(VkShaderModule,2),.block=96,.n_samp=2,.n_uni=5,.inputs=7,.uid=33,.uni=uniforms};
  programs[1].samp_cube[1]=1;
  programs[2]=(vprog){.vs=H(VkShaderModule,3),.fs=H(VkShaderModule,4),.inputs=1,.uid=34};
  for(int i=0;i<9;i++){images[i].fmt=VK_FORMAT_R8G8B8A8_UNORM;images[i].view=H(VkImageView,20+i);images[i].level_mask=1;images[i].layers=1;images[i].view_levels=1;images[i].samples=1;images[i].img=H(VkImage,100+i);images[i].aspect=VK_IMAGE_ASPECT_COLOR_BIT;images[i].usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT;}
  images[2].fmt=images[6].fmt=VK_FORMAT_D24_UNORM_S8_UINT;images[2].aspect=images[6].aspect=VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT;
  images[3].layers=images[5].layers=6;
  features=VK_FORMAT_FEATURE_BLIT_SRC_BIT|VK_FORMAT_FEATURE_BLIT_DST_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT|VK_FORMAT_FEATURE_TRANSFER_SRC_BIT|VK_FORMAT_FEATURE_TRANSFER_DST_BIT;
  textures[1].im=&images[0];textures[2].im=&images[3];textures[3].im=&images[1];
  for(int i=1;i<3;i++){backing[i].buf=H(VkBuffer,30+i);backing[i].size=sizeof bufferbytes[i];backing[i].map=bufferbytes[i];buffers[i].m=&backing[i];}
  compats[0]=(Compat){VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_D24_UNORM_S8_UINT};compats[1]=compats[0];
  for(int i=0;i<9;i++)playout[i]=H(VkPipelineLayout,40+i);
}
static cinder_vk_draw packet(void){cinder_vk_draw d;assert(cinder_vk_draw_init(&d,1,1,64,48));d.count=3;
  d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=16,.data=quad,.bytes=sizeof quad};
  d.attributes[1]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=16,.offset=8,.data=quad,.bytes=sizeof quad};return d;}
static void defaults_uniforms(void){reset();cinder_vk_draw a,b;memset(&a,0xa5,sizeof a);memset(&b,0x5a,sizeof b);
  assert(cinder_vk_draw_init(&a,1,1,64,48)&&cinder_vk_draw_init(&b,1,1,64,48)&&!memcmp(&a,&b,sizeof a));
  assert(a.uniform_bytes==96&&a.pipeline.color_mask==15&&!a.pipeline.depth_test&&!a.pipeline.blend&&a.attributes[2].value[3]==1);
  assert(!cinder_vk_draw_init(NULL,1,1,64,48)&&!cinder_vk_draw_init(&b,0,1,64,48)&&!cinder_vk_draw_init(&b,1,1,0,48));
  programs[1].block=4097;assert(!cinder_vk_draw_init(&b,1,1,64,48));programs[1].block=96;
  float m[16]={1,2,3},mul[4]={.25f,.5f,.75f,1};assert(cinder_vk_uniform(&a,"uProj",m,sizeof m));assert(cinder_vk_uniform(&a,"uMul",mul,sizeof mul));
  assert(!memcmp(a.uniforms,m,64)&&!memcmp(a.uniforms+64,mul,16));assert(!cinder_vk_uniform(&a,"uMul",mul,12));
  assert(cinder_vk_uniform(&a,"optimized_out",mul,16));assert(!cinder_vk_uniform(&a,"uTex",mul,4));
  assert(cinder_vk_texture(&a,"uTex",3)&&a.textures[0]==3);assert(cinder_vk_texture(&a,"uCube",2)&&a.textures[1]==2);
  assert(!cinder_vk_texture(&a,"uMul",1));assert(cinder_vk_texture(&a,"optimized_out",1));
  uniforms[1].off=95;assert(!cinder_vk_uniform(&a,"uMul",mul,16));uniforms[1].off=64;
  a.uniform_bytes=95;assert(!cinder_vk_uniform(&a,"uMul",mul,16));
  puts("PASS deterministic init; reflection/type/size/bounds; immutable caller-owned uniforms");
}
static void record_and_lifetime(void){reset();cinder_vk_draw d=packet();float mul[4]={.25f,.5f,.75f,1};assert(cinder_vk_uniform(&d,"uMul",mul,16));
  assert(cinder_vk_texture(&d,"uCube",2));d.pipeline.depth_test=1;d.pipeline.depth_write=0;d.pipeline.blend=1;d.pipeline.src_blend=VK_BLEND_FACTOR_SRC_ALPHA;d.pipeline.dst_blend=VK_BLEND_FACTOR_ONE;d.pipeline.color_mask=7;
  d.pipeline.stencil=1;d.pipeline.stencil_compare=VK_COMPARE_OP_EQUAL;d.stencil_reference=9;
  d.attributes[2].value[0]=.7f;assert(cinder_vk_submit(&d));assert(n_ops==1&&n_items==1&&frame_draws>0&&pipeline_calls==1&&descriptor_calls==1);
  assert(last_key.prog==33&&last_key.compat==1&&!last_key.flip&&last_key.blend&&last_key.depth_test&&!last_key.depth_write&&last_key.cmask==7);
  assert(last_key.afmt[0]==2&&last_key.afmt[1]==2&&last_key.afmt[2]==4&&(last_key.inst&4)&&last_key.astride[2]==16);
  assert(items[0].nvb==3&&items[0].sref==9);
}
'''
tests += r'''
static void copies_and_targets(void){reset();cinder_vk_draw d=packet();float mul[4]={.25f,.5f,.75f,1};cinder_vk_uniform(&d,"uMul",mul,16);
  d.attributes[2].value[0]=.7f;d.textures[1]=2;assert(cinder_vk_submit(&d));
  const struct Allocation *v=allocation(vbb[items[0].vb]),*constant=allocation(vbb[items[0].vb+2]),*u=allocation(last_descriptor.ubo);
  assert(v->bytes==40&&constant->bytes==16&&u->bytes==96);assert(!memcmp(u->data+64,mul,16));
  float old=quad[0];quad[0]=9;memset(d.uniforms,0,sizeof d.uniforms);assert(*(float*)v->data==old&&*(float*)(u->data+64)==.25f&&*(float*)constant->data==.7f);quad[0]=old;
  assert(last_descriptor.v[0]==dummy2d->view&&last_descriptor.s[0]==dummy_sampler&&last_descriptor.v[1]==images[3].view&&images[3].serial==D.serial);
  assert(cinder_vk_submit(&d)&&n_ops==1&&ops[0].n==2);d.target=0;d.viewport[1]=3;d.viewport[3]=10;d.scissor[1]=4;d.scissor[3]=11;
  assert(cinder_vk_submit(&d)&&n_ops==2&&items[2].vp[1]==35&&items[2].sc[1]==33&&last_key.flip&&last_key.front_ccw);
  puts("PASS draw packet copies CPU vertices/constants/UBO immediately; target splits and origin transform");
}
static void indices_buffers(void){reset();cinder_vk_draw d=packet();uint16_t idx[3]={2,0,1};d.indexed=1;d.indices=idx;d.index_bytes=sizeof idx;
  assert(cinder_vk_submit(&d)&&items[0].indexed&&items[0].itype==VK_INDEX_TYPE_UINT16);struct Allocation *a=allocation(items[0].ib);assert(a->bytes==6&&!memcmp(a->data,idx,6));
  idx[0]=0;assert(((uint16_t*)a->data)[0]==2);reset();d=packet();d.attributes[0].buffer=1;d.attributes[1].buffer=1;
  uint32_t ix[]={0,1,2};memcpy(bufferbytes[2]+4,ix,sizeof ix);d.indexed=1;d.index_type=VK_INDEX_TYPE_UINT32;d.index_buffer=2;d.index_offset=4;
  assert(cinder_vk_submit(&d)&&items[0].ib==backing[2].buf&&items[0].ibo==4&&items[0].itype==VK_INDEX_TYPE_UINT32);
  assert(backing[1].serial==D.serial&&backing[2].serial==D.serial&&vbb[items[0].vb]==backing[1].buf&&vbo[items[0].vb+1]==8);
  puts("PASS CPU/u16 and resource/u32 indices; resource offsets and retirement serials");
}
#define BAD(expr) do{reset();cinder_vk_draw d=packet();expr;size_t before=n_items;assert(!cinder_vk_submit(&d)&&errors==1&&n_items==before);}while(0)
static void rejection(void){
  BAD(d.program=0);BAD(d.target=99);BAD(d.uniform_bytes=95);BAD(d.viewport[2]=0);BAD(d.viewport[0]=-1);BAD(d.viewport[0]=INT_MAX);BAD(d.scissor[2]=65);
  BAD(d.pipeline.depth_test=1;compats[1].dfmt=VK_FORMAT_UNDEFINED);
  BAD(d.pipeline.stencil=1;compats[1].dfmt=VK_FORMAT_UNDEFINED);
  BAD(d.pipeline.stencil=1;compats[1].dfmt=VK_FORMAT_D16_UNORM);
  BAD(d.pipeline.color_mask=16);BAD(d.pipeline.blend=2);BAD(d.pipeline.topology=VK_PRIMITIVE_TOPOLOGY_PATCH_LIST);BAD(d.count=UINT32_MAX);BAD(d.first=INT_MAX);
  BAD(d.pipeline.topology=(VkPrimitiveTopology)-1);BAD(d.pipeline.src_blend=(VkBlendFactor)-1);BAD(d.pipeline.dst_blend=(VkBlendFactor)-1);
  BAD(d.pipeline.blend_op=(VkBlendOp)-1);BAD(d.pipeline.depth_compare=(VkCompareOp)-1);BAD(d.pipeline.asset_front=(VkFrontFace)-1);
  BAD(d.pipeline.stencil_compare=(VkCompareOp)-1);BAD(d.pipeline.stencil_fail=(VkStencilOp)-1);BAD(d.pipeline.depth_fail=(VkStencilOp)-1);BAD(d.pipeline.depth_pass=(VkStencilOp)-1);
  BAD(d.attributes[0].format=VK_FORMAT_R64_SFLOAT);BAD(d.attributes[0].stride=0);BAD(d.attributes[0].stride=UINT16_MAX+1u);BAD(d.attributes[0].bytes=39);
  BAD(d.attributes[0].offset=SIZE_MAX);BAD(d.attributes[0].data=NULL);BAD(d.attributes[0].buffer=99);BAD(d.attributes[0].buffer=1;backing[1].size=39);
  BAD(d.indexed=2);BAD(d.indexed=1;d.index_type=VK_INDEX_TYPE_UINT8_EXT);BAD(d.indexed=1;d.indices=quad;d.index_bytes=2);BAD(d.indexed=1;d.first=1;d.indices=quad;d.index_bytes=64);
  BAD(d.indexed=1;d.indices=quad;d.index_bytes=64;d.index_offset=1);BAD(d.indexed=1;d.index_buffer=99);BAD(d.indexed=1;d.indices=quad;d.index_bytes=64;((uint16_t*)quad)[0]=65535);quad[0]=0;
  BAD(d.textures[0]=99);BAD(d.textures[0]=2);BAD(d.textures[0]=3);BAD(d.textures[0]=1;d.target=0);BAD(d.textures[1]=1);
  BAD(d.textures[0]=1;images[0].level_mask=0);BAD(pipeline_fail=1);BAD(F=NULL);
  reset();assert(!native_span(SIZE_MAX,SIZE_MAX,1,4,4));assert(!native_span(8,0,SIZE_MAX,4,4));assert(native_span(8,0,2,4,4));
  puts("PASS fail-closed packet/pipeline/span/format/feedback/target validation before recording");
}
static void warm_and_coverage(void){reset();cinder_vk_draw d=packet();d.warm_only=1;size_t old=n_alloc;assert(cinder_vk_submit(&d)&&pipeline_calls==1&&n_alloc==old&&!n_items&&!n_ops);
  d.warm_only=0;assert(cinder_vk_submit(&d));cinder_vk_coverage c;cinder_vk_get_coverage(&c);assert(c.native_draws>0&&c.rejected_packets>0&&c.compatibility_draws==compat_draw_count);
  int w,h;cinder_vk_screen_extent(&w,&h);assert(w==64&&h==48);cinder_vk_screen_extent(NULL,NULL);cinder_vk_get_coverage(NULL);
  reset();assert(cinder_vk_draw_init(&d,2,1,64,48));d.count=3;assert(cinder_vk_submit(&d)&&last_descriptor.range==16&&last_descriptor.n==0);
  puts("PASS explicit prewarm without draw; coverage; zero-block/no-sampler/constant-only program");
}
static void effective_fetch_bounds(void){reset();cinder_vk_draw d=packet();programs[1].inputs=1;
  vfmt_dev[3]=VK_FORMAT_R32G32B32A32_SFLOAT;
  d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32B32_SFLOAT,.stride=16,.data=quad,.bytes=44};
  assert(!cinder_vk_submit(&d)&&!n_items&&errors==1);d.attributes[0].bytes=48;
  assert(cinder_vk_submit(&d)&&last_key.afmt[0]==3&&allocation(vbb[items[0].vb])->bytes==48);
  reset();d=packet();programs[1].inputs=1;vfmt_dev[3]=VK_FORMAT_UNDEFINED;
  d.attributes[0].format=VK_FORMAT_R32G32B32_SFLOAT;assert(!cinder_vk_submit(&d)&&!n_items);
  puts("PASS effective GPU vec3-to-vec4 fetch bounds, padded copy and unsupported-device format rejection");
}
static void explicit_clear(void){
  reset();const float red[4]={1,.2f,.3f,.4f};
  assert(cinder_vk_clear(0,VK_IMAGE_ASPECT_COLOR_BIT|VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT,red,NULL));
  assert(n_ops==1&&n_items==0&&ops[0].clear==(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT)&&!memcmp(ops[0].cc,red,16));
  cinder_vk_draw d=packet();d.target=0;assert(cinder_vk_submit(&d));
  int clip[4]={3,4,10,11};assert(cinder_vk_clear(0,VK_IMAGE_ASPECT_DEPTH_BIT,NULL,clip));
  assert(n_ops==1&&n_items==2&&items[1].kind==IT_CLEAR&&items[1].bits==GL_DEPTH_BUFFER_BIT);
  assert(items[1].sc[0]==3&&items[1].sc[1]==33&&items[1].sc[2]==10&&items[1].sc[3]==11);
  assert(cinder_vk_submit(&d)&&items[2].kind==IT_DRAW&&ops[0].n==3);
  assert(cinder_vk_clear(1,VK_IMAGE_ASPECT_COLOR_BIT,red,clip));assert(n_ops==2&&items[3].sc[1]==4);
  assert(cinder_vk_clear(1,VK_IMAGE_ASPECT_DEPTH_BIT,NULL,NULL)&&items[4].kind==IT_CLEAR); /* do not hoist past partial clear */
  cinder_vk_coverage c;cinder_vk_get_coverage(&c);assert(c.native_clears>=4);
  reset();unsigned err=errors;assert(!cinder_vk_clear(99,VK_IMAGE_ASPECT_DEPTH_BIT,NULL,NULL)&&errors==err+1&&!n_items&&!n_ops);
  assert(!cinder_vk_clear(2,VK_IMAGE_ASPECT_DEPTH_BIT,NULL,NULL)&&!n_items&&!n_ops);
  assert(!cinder_vk_clear(3,VK_IMAGE_ASPECT_COLOR_BIT,red,NULL)&&!n_items&&!n_ops);
  assert(!cinder_vk_clear(0,VK_IMAGE_ASPECT_COLOR_BIT,NULL,NULL)&&!n_items&&!n_ops);
  float nan[4]={NAN,0,0,0};assert(!cinder_vk_clear(0,VK_IMAGE_ASPECT_COLOR_BIT,nan,NULL)&&!n_items&&!n_ops);
  images[2].fmt=VK_FORMAT_D16_UNORM;assert(!cinder_vk_clear(0,VK_IMAGE_ASPECT_STENCIL_BIT,NULL,NULL)&&!n_items&&!n_ops);
  assert(!cinder_vk_clear(0,VK_IMAGE_ASPECT_METADATA_BIT,NULL,NULL)&&!n_items&&!n_ops);
  int bad[4]={INT_MAX,0,2,1};assert(!cinder_vk_clear(0,VK_IMAGE_ASPECT_DEPTH_BIT,NULL,bad)&&!n_items&&!n_ops);
  bad[0]=0;bad[2]=65;assert(!cinder_vk_clear(0,VK_IMAGE_ASPECT_DEPTH_BIT,NULL,bad));
  F=NULL;assert(!cinder_vk_clear(0,VK_IMAGE_ASPECT_DEPTH_BIT,NULL,NULL));
  assert(cinder_vk_clear(99,0,NULL,NULL));
  puts("PASS explicit full/partial clears, draw ordering, screen/offscreen origin, aspect/mask independence and rejection");
}
static void explicit_samplers(void){
  reset();cinder_vk_draw d=packet();
  cinder_vk_sampler sampler={.use_state=1,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_LINEAR,.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,
    .address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.address_v=VK_SAMPLER_ADDRESS_MODE_REPEAT,.anisotropy=1};
  assert(cinder_vk_sampler_state(&d,"uTex",&sampler));assert(!cinder_vk_sampler_state(&d,"uMul",&sampler));
  assert(cinder_vk_sampler_state(&d,"optimized_out",&sampler));assert(!cinder_vk_sampler_state(NULL,"uTex",&sampler));
  assert(cinder_vk_submit(&d)&&sampler_calls==1&&last_descriptor.s[0]==H(VkSampler,702)&&last_sampler.address_v==VK_SAMPLER_ADDRESS_MODE_REPEAT);
  reset();d=packet();d.textures[0]=1;assert(cinder_vk_sampler_state(&d,"uTex",&sampler));assert(cinder_vk_submit(&d)&&sampler_calls==1);
  reset();d=packet();d.samplers[0]=sampler;sampler_fail=1;assert(!cinder_vk_submit(&d)&&!n_items&&errors==1);
  BAD(d.samplers[0]=sampler;d.samplers[0].use_state=2);
  BAD(d.samplers[0]=sampler;d.samplers[0].mipmaps=2);
  BAD(d.samplers[0]=sampler;d.samplers[0].min_filter=(VkFilter)-1);
  BAD(d.samplers[0]=sampler;d.samplers[0].mag_filter=(VkFilter)-1);
  BAD(d.samplers[0]=sampler;d.samplers[0].mipmap_mode=(VkSamplerMipmapMode)-1);
  BAD(d.samplers[0]=sampler;d.samplers[0].address_u=(VkSamplerAddressMode)-1);
  BAD(d.samplers[0]=sampler;d.samplers[0].address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_BORDER);
  BAD(d.samplers[0]=sampler;d.samplers[0].anisotropy=NAN);
  BAD(d.samplers[0]=sampler;d.samplers[0].anisotropy=.5f);
  puts("PASS immutable explicit sampler override, reflected slots, dummy/resource samplers and invalid-state rejection");
}
static cinder_vk_copy_region region(void){return (cinder_vk_copy_region){.source=4,.target=1,.source_rect={0,0,16,12},.target_rect={0,0,16,12},.aspects=VK_IMAGE_ASPECT_COLOR_BIT,.filter=VK_FILTER_NEAREST};}
#define COPY_BAD(change) do {reset();cinder_vk_copy_region r=region();change;assert(!cinder_vk_copy(&r)&&!n_ops&&!n_items&&cur_pass==-1&&errors==1);assert(!images[7].serial&&!images[1].serial);}while(0)
static void explicit_transfers(void){
 reset();cinder_vk_target_desc info;assert(cinder_vk_target_info(0,&info)&&info.width==64&&info.height==48&&info.color_format==VK_FORMAT_R8G8B8A8_UNORM&&info.depth_format==VK_FORMAT_D24_UNORM_S8_UINT&&info.samples==1&&!info.resolves);
 images[8].samples=4;assert(cinder_vk_target_info(5,&info)&&info.samples==4&&info.resolves);assert(!cinder_vk_target_info(99,&info)&&!info.width);assert(!cinder_vk_target_info(0,NULL));
 cinder_vk_copy_region r=region();r.source=0;r.source_rect[0]=r.target_rect[0]=5;r.source_rect[2]=r.target_rect[2]=6;r.source_rect[1]=48;r.source_rect[3]=0;r.target_rect[1]=0;r.target_rect[3]=48;
 cinder_vk_copy_region original=r;assert(cinder_vk_copy(&r)&&n_ops==1&&!n_items&&cur_pass==-1&&!memcmp(&r,&original,sizeof r));
 assert(ops[0].kind==OP_BLIT&&ops[0].src_screen&&!ops[0].dst_screen&&ops[0].s[1]==0&&ops[0].s[3]==48&&ops[0].d[1]==0&&ops[0].d[3]==48);
 assert(images[0].serial==D.serial&&images[1].serial==D.serial);replay_blit(H(VkCommandBuffer,1),&ops[0]);assert(last_blit.srcSubresource.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT&&last_blit.srcOffsets[0].y==0&&last_blit.srcOffsets[1].y==48);
 reset();r=region();r.source=1;r.target=0;r.target_rect[1]=3;r.target_rect[3]=15;assert(cinder_vk_copy(&r)&&ops[0].dst_screen&&ops[0].d[1]==45&&ops[0].d[3]==33);
 reset();r=region();r.aspects|=VK_IMAGE_ASPECT_DEPTH_BIT;assert(cinder_vk_copy(&r)&&n_ops==2&&ops[0].copy_aspects==VK_IMAGE_ASPECT_COLOR_BIT&&ops[1].copy_aspects==VK_IMAGE_ASPECT_DEPTH_BIT);
 replay_blit(H(VkCommandBuffer,1),&ops[1]);assert(last_blit.srcSubresource.aspectMask==VK_IMAGE_ASPECT_DEPTH_BIT&&last_blit.dstSubresource.aspectMask==VK_IMAGE_ASPECT_DEPTH_BIT);
 vop legacy=ops[1];legacy.copy_aspects=0;replay_blit(H(VkCommandBuffer,1),&legacy);assert(last_blit.srcSubresource.aspectMask==(VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT));
 reset();r=region();r.aspects=VK_IMAGE_ASPECT_STENCIL_BIT;assert(cinder_vk_copy(&r));replay_blit(H(VkCommandBuffer,1),&ops[0]);assert(last_blit.srcSubresource.aspectMask==VK_IMAGE_ASPECT_STENCIL_BIT);
 reset();r=region();images[7].samples=images[6].samples=4;features=VK_FORMAT_FEATURE_TRANSFER_SRC_BIT|VK_FORMAT_FEATURE_TRANSFER_DST_BIT;assert(cinder_vk_copy(&r)&&ops[0].resolve_blit);replay_blit(H(VkCommandBuffer,1),&ops[0]);assert(last_resolve.extent.width==16&&last_resolve.extent.height==12&&last_resolve.srcSubresource.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT);
 reset();r=region();r.source=5;images[8].samples=images[6].samples=4;assert(cinder_vk_copy(&r)&&ops[0].src==&images[7]&&!ops[0].resolve_blit); /* MSRT reads its resolved image */
 reset();r=region();cinder_vk_draw d=packet();assert(cinder_vk_submit(&d));r.target=2;r.aspects|=VK_IMAGE_ASPECT_DEPTH_BIT;assert(!cinder_vk_copy(&r)&&n_ops==1&&n_items==1&&cur_pass==0&&!images[7].serial); /* atomic failure */
 COPY_BAD(r.source=99);COPY_BAD(r.target=4);COPY_BAD(r.source=1;r.target=2);COPY_BAD(r.aspects=VK_IMAGE_ASPECT_METADATA_BIT);COPY_BAD(r.filter=(VkFilter)-1);
 COPY_BAD(r.source_rect[0]=-1);COPY_BAD(r.target_rect[2]=INT_MAX);COPY_BAD(r.source_rect[2]=0);
 COPY_BAD(images[7].fmt=VK_FORMAT_R8G8B8A8_UINT);COPY_BAD(images[1].samples=4);COPY_BAD(images[7].samples=0);
 COPY_BAD(features&=~VK_FORMAT_FEATURE_BLIT_SRC_BIT);COPY_BAD(features&=~VK_FORMAT_FEATURE_BLIT_DST_BIT);COPY_BAD(r.filter=VK_FILTER_LINEAR;features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT);
 COPY_BAD(r.aspects=VK_IMAGE_ASPECT_DEPTH_BIT;r.filter=VK_FILTER_LINEAR);COPY_BAD(r.aspects=VK_IMAGE_ASPECT_DEPTH_BIT;images[6].fmt=VK_FORMAT_D16_UNORM);
 COPY_BAD(r.aspects=VK_IMAGE_ASPECT_STENCIL_BIT;images[6].fmt=images[2].fmt=VK_FORMAT_D16_UNORM);
 COPY_BAD(images[7].samples=4;r.target_rect[2]=15);COPY_BAD(images[7].samples=4;r.target_rect[1]=12;r.target_rect[3]=0);COPY_BAD(images[7].samples=4;images[7].fmt=VK_FORMAT_R16G16B16A16_SFLOAT);
 COPY_BAD(r.target=2;r.aspects|=VK_IMAGE_ASPECT_DEPTH_BIT);COPY_BAD(F=NULL);
 COPY_BAD(images[7].samples=4;images[7].usage=created_usage(4,0,1,1,0)); /* actual lazy MSAA RBO */
 COPY_BAD(images[7].samples=4;images[7].usage=created_usage(4,0,1,0,0)); /* actual nonlazy MSAA RBO */
 COPY_BAD(r.source=0;r.target=4;r.aspects=VK_IMAGE_ASPECT_DEPTH_BIT;images[2].usage=created_usage(1,0,1,1,1)); /* lazy screen depth */
 COPY_BAD(r.source=0;images[0].usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT); /* swapchain lacks SRC */
 COPY_BAD(images[1].usage&=~VK_IMAGE_USAGE_TRANSFER_DST_BIT);
 COPY_BAD(images[7].samples=4;features&=~VK_FORMAT_FEATURE_TRANSFER_SRC_BIT);
 COPY_BAD(images[7].samples=4;features&=~VK_FORMAT_FEATURE_TRANSFER_DST_BIT);
 COPY_BAD(r.source=1;r.target=5); /* resolve target would overwrite copy on next MSAA partial draw */
 reset();assert(created_usage(1,0,0,0,0)&VK_IMAGE_USAGE_TRANSFER_SRC_BIT);
 assert((created_usage(1,1,0,0,1)&(VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT))==(VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT));
  VkImageUsageFlags sampled_usage=VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT;
  assert(created_usage_explicit(1,1,0,0,0,sampled_usage)==sampled_usage); /* no inherited COLOR_ATTACHMENT */
  VkImageUsageFlags raw_usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
  assert(created_usage_explicit(4,0,1,1,0,raw_usage)==raw_usage); /* explicit nontransient usage does not inherit lazy allocation */
 assert(cinder_vk_target_info(5,&info)&&info.color_usage==images[8].usage&&info.depth_usage==images[6].usage&&info.resolve_usage==images[7].usage);
 reset();assert(!cinder_vk_copy(NULL));r=region();r.aspects=0;r.source=99;assert(cinder_vk_copy(&r)&&!n_ops);
 puts("PASS explicit transfer/resolve, preflipped screen columns, metadata, format capabilities, atomic admission and precise replay aspects");
}
static void explicit_discard(void){
 reset();const float color[4]={0};const VkImageAspectFlags all=VK_IMAGE_ASPECT_COLOR_BIT|VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT;
 assert(cinder_vk_clear(1,all,color,NULL));assert(cinder_vk_discard(1,all)&&ops[0].discard==(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT)&&cur_pass==-1);
 cinder_vk_draw d=packet();assert(cinder_vk_submit(&d)&&n_ops==2); /* discarded pass cannot be silently joined */
 reset();assert(cinder_vk_clear(1,VK_IMAGE_ASPECT_COLOR_BIT,color,NULL));cinder_vk_copy_region r=region();r.source=1;r.target=0;
 assert(cinder_vk_copy(&r)&&n_ops==2);assert(cinder_vk_discard(1,all)&&!ops[0].discard&&n_ops==2); /* preserve source store needed by recorded copy */
 reset();assert(cinder_vk_discard(2,VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT)&&!n_ops&&!errors); /* absent aspect: legal hint */
 assert(!cinder_vk_discard(99,all));assert(!cinder_vk_discard(0,VK_IMAGE_ASPECT_METADATA_BIT));F=NULL;assert(!cinder_vk_discard(0,all));assert(cinder_vk_discard(99,0));
 cinder_vk_coverage coverage;cinder_vk_get_coverage(&coverage);assert(coverage.native_copies&&coverage.native_discards);
 puts("PASS explicit advisory discard closes matching pass, preserves intervening copy stores and ignores absent attachments without GL state");
}

int main(void){defaults_uniforms();record_and_lifetime();copies_and_targets();indices_buffers();rejection();warm_and_coverage();effective_fetch_bounds();explicit_clear();explicit_samplers();explicit_transfers();explicit_discard();puts("native Vulkan packets: CPU production implementation PASS (NOT GPU validation)");return 0;}
'''

with tempfile.TemporaryDirectory(prefix="native-vk-packets-", dir=OUT) as temp:
    temp = Path(temp)
    env = dict(os.environ, TMPDIR=str(temp), TMP=str(temp), TEMP=str(temp),
               HOME=str(temp), XDG_CACHE_HOME=str(temp), PYTHONDONTWRITEBYTECODE="1")
    fixture = temp / "packets.c"
    fixture.write_text(prefix + "\n" + formats + "\n" + schema + "\n" + depth_helpers + "\n" + mocks + "\n" + NATIVE + "\n" + replay_blit + "\n" + usage_helper + "\n" + tests)
    cc = os.environ.get("CC", "clang")
    flags = ["-I", str(ROOT / "src")]
    # Use real Vulkan SDK headers; no Vulkan implementation is linked or called.
    if sys.platform == "darwin":
        flags += ["-I", "/opt/homebrew/include"]
    exe = temp / "packets"
    # Apple's installed ASan dylib deadlocks before main on this host OS
    # (dyld/malloc initialization). UBSan works; full ASan is opt-in and used
    # by default on Linux. A bounded timeout never turns a hang into a pass.
    sanitizers = os.environ.get("NATIVE_VK_SANITIZERS", "undefined" if sys.platform == "darwin" else "address,undefined")
    cmd = [cc, "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
           "-fsanitize=" + sanitizers, "-fno-omit-frame-pointer", str(fixture), "-o", str(exe)]
    subprocess.run(cmd, cwd=temp, env=env, check=True, timeout=120)
    subprocess.run([str(exe)], cwd=temp, env=env, check=True, timeout=30)
    print("sanitizers", sanitizers)
print("native_vk.inc sha256", hashlib.sha256(NATIVE.encode()).hexdigest())
print("native_vk.h sha256", hashlib.sha256(HEADER.encode()).hexdigest())
