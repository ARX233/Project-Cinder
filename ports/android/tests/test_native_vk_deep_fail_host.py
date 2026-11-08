#!/usr/bin/env python3
"""Controlled actual helper/caller failures, not GPU/driver or OOM recovery proof.
CINDER_DEEP_SOURCE accepts a core file or source tree; default is main core.
Artifacts require external CINDER_TEST_OUT/TMPDIR. Baseline is explicitly overridable.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def core_path(value):
    p = Path(value).expanduser().resolve()
    if p.is_dir():
        p = p / ('src/vkgl.c' if (p / 'src/vkgl.c').is_file() else 'vkgl.c')
    return p

SOURCE_PATH = core_path(os.environ.get('CINDER_DEEP_SOURCE', str(ROOT / 'src/vkgl.c')))
BASE_PATH = core_path(os.environ.get('CINDER_DEEP_BASELINE', str(ROOT / '../round8-baseline/src/vkgl.c')))
out_value = os.environ.get('CINDER_TEST_OUT') or os.environ.get('TMPDIR')
if not out_value:
    raise SystemExit('set external APFS CINDER_TEST_OUT or TMPDIR')
OUT_ROOT = Path(out_value).expanduser().resolve()
if not (str(OUT_ROOT) == '/Volumes/CodexWork' or str(OUT_ROOT).startswith('/Volumes/CodexWork/')):
    raise SystemExit('artifacts must be under /Volumes/CodexWork')
OUT_ROOT.mkdir(parents=True, exist_ok=True)
OUT = OUT_ROOT / 'round8-deep'
OUT.mkdir(parents=True, exist_ok=True)
SOURCE_BYTES, BASE_BYTES = SOURCE_PATH.read_bytes(), BASE_PATH.read_bytes()
SOURCE, BASE = SOURCE_BYTES.decode(), BASE_BYTES.decode()
OBJECT_BYTES = (ROOT / 'src/native_vk_objects.inc').read_bytes()
OBJECTS = OBJECT_BYTES.decode()
SELF_BYTES = Path(__file__).read_bytes()
ANCHORS = ('static VkImageView view_new(', 'static VkShaderModule shader_module(',
           'static VkFramebuffer fb_get(', 'static VkDescriptorSet desc_alloc(')


def function(text, anchor):
    a = text.index(anchor)
    ending = re.search(r'^}\s*$', text[a:], re.M)
    assert ending, anchor
    return text[a:a + ending.end()].rstrip() + '\n'


def struct(text, name):
    b = text.index('} ' + name + ';') + len('} ' + name + ';')
    a = text.rfind('typedef struct', 0, b)
    return text[a:b] + '\n'


def macro(text, name):
    m = re.search(r'^#define ' + name + r'\b[^\n]*(?:\\\n[^\n]*)*', text, re.M)
    assert m, name
    # Explicit line walk preserves backslash-newline macro bytes.
    lines = text[m.start():].splitlines(keepends=True)
    result = ''
    for line in lines:
        result += line
        if not line.rstrip('\r\n').endswith('\\'):
            break
    return result


protected = {name: function(SOURCE, name) for name in ('static void loader_flush(void) {', 'static void image_free_now(')}
assert macro(SOURCE, 'VKCHECK') == macro(BASE, 'VKCHECK')
assert protected['static void loader_flush(void) {'] == function(BASE, 'static void loader_flush(void) {')
assert protected['static void image_free_now('] == function(BASE, 'static void image_free_now(')
old = {a: function(BASE, a) for a in ANCHORS}
new = {a: function(SOURCE, a) for a in ANCHORS}
red_only = os.environ.get('CINDER_DEEP_CAPTURE_RED') == '1'
rollover_red = os.environ.get('CINDER_DEEP_CAPTURE_ROLLOVER_RED') == '1'

prefix = r'''
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define MAX_SAMP 8
#define DCACHE 8192
#define H(T,n) ((T)(uintptr_t)(n))
typedef uint32_t GLuint;
typedef struct {int block;}vmem;
'''
state = r'''
static struct {VkDevice dev;pthread_mutex_t lock;uint64_t serial,done;uint32_t uid;VkPhysicalDeviceProperties props;}D={.lock=PTHREAD_MUTEX_INITIALIZER};
static int platform_native_profile;
typedef struct {VkDescriptorPool*dpool;size_t n_dpool,cap_dpool,dpool_i;VkCommandPool pool;VkFence fence;int submitted;struct{VkCommandPool pool;int stage;}up;}vframe;
static vframe frame,*F=&frame;
static fbent*fbs;static size_t n_fbs,cap_fbs;
static struct{VkRenderPass rp;}compats[64];static int n_compats=2;
static dent dcache[DCACHE];static VkDescriptorSetLayout dsl[MAX_SAMP+1];
static unsigned view_calls,module_calls,fb_calls,pool_calls,alloc_calls,update_calls,begin_calls,bad_begin,bad_writes,dead_calls,destroy_modules,unknown_destroys,prog_gen_calls,rejects,logs;
static unsigned fail_stage,output_mode,seen_fbs,seen_pools,kind;static VkResult create_result,alloc_result,alloc_sequence[8];static unsigned n_sequence;
static unsigned max_driver_calls=24;static VkImageView last_dead;static uint64_t last_dead_serial;
static VkImageViewCreateInfo last_view;static VkFramebufferCreateInfo last_fb;
static VkDescriptorImageInfo last_image;static VkDescriptorSet last_set;
static unsigned pool_sets[1024],pool_samplers[1024],capacity_violations,wait_calls,descriptor_resets;
static int bad_pool_used;static const uint32_t words[5]={0x07230203u,0x10000u,0,1,0};
static void observe(const char*tag){unsigned cached=0;for(unsigned i=0;i<DCACHE;++i)cached+=dcache[i].serial==D.serial;int lock_free=pthread_mutex_trylock(&D.lock)==0;if(lock_free)pthread_mutex_unlock(&D.lock);printf("OBS tag=%s views=%u modules=%u fbs=%zu fb_calls=%u seen_fbs=%u pools=%zu pool_i=%zu pool_calls=%u seen_pools=%u alloc=%u updates=%u begins=%u bad_begin=%u bad_writes=%u cached=%u gen=%u uid=%u rejects=%u dead=%u destroyed=%u unknown_destroy=%u bad_pool=%d lock_free=%d capacity_violations=%u waits=%u resets=%u serial=%llu\n",tag,view_calls,module_calls,n_fbs,fb_calls,seen_fbs,F->n_dpool,F->dpool_i,pool_calls,seen_pools,alloc_calls,update_calls,begin_calls,bad_begin,bad_writes,cached,prog_gen_calls,D.uid,rejects,dead_calls,destroy_modules,unknown_destroys,bad_pool_used,lock_free,capacity_violations,wait_calls,descriptor_resets,(unsigned long long)D.serial);fflush(stdout);}
static _Noreturn void deep_abort(void){observe("fatal");_Exit(77);}
#define abort deep_abort
static void logf_(const char*fmt,...){(void)fmt;++logs;}
static uint64_t hash_bytes(const void*p,size_t n){const unsigned char*b=p;uint64_t h=1469598103934665603ull;while(n--)h=(h^*b++)*1099511628211ull;return h;}
static void dead_add(int k,void*p,uint64_t h,uint64_t serial){assert(k==2&&!p);++dead_calls;last_dead=H(VkImageView,h);last_dead_serial=serial;}
#define DEAD_VIEW 2
static VkResult result_for(unsigned call){return call==fail_stage?create_result:VK_SUCCESS;}
static void output_handle(void*out,size_t size,unsigned call,unsigned base,VkResult r){if(r!=VK_SUCCESS&&output_mode==0)return;uintptr_t value=r!=VK_SUCCESS?(output_mode==1?0:90000u):((call==fail_stage&&output_mode==1&&kind!=5)?0:base+call);assert(size==sizeof(VkImageView));memcpy(out,&value,size);}
static VKAPI_ATTR VkResult VKAPI_CALL mockCreateImageView(VkDevice d,const VkImageViewCreateInfo*c,const VkAllocationCallbacks*a,VkImageView*out){assert(d==D.dev&&!a&&c->sType==VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO);last_view=*c;VkResult r=result_for(++view_calls);output_handle(out,sizeof *out,view_calls,100,r);return r;}
static VKAPI_ATTR VkResult VKAPI_CALL mockCreateShaderModule(VkDevice d,const VkShaderModuleCreateInfo*c,const VkAllocationCallbacks*a,VkShaderModule*out){assert(d==D.dev&&!a&&c->pCode==words&&c->codeSize==sizeof words);VkResult r=result_for(++module_calls);output_handle(out,sizeof *out,module_calls,200,r);return r;}
static VKAPI_ATTR VkResult VKAPI_CALL mockCreateFramebuffer(VkDevice d,const VkFramebufferCreateInfo*c,const VkAllocationCallbacks*a,VkFramebuffer*out){assert(d==D.dev&&!a&&c->layers==1&&c->renderPass);last_fb=*c;seen_fbs=(unsigned)n_fbs;VkResult r=result_for(++fb_calls);output_handle(out,sizeof *out,fb_calls,300,r);return r;}
static VKAPI_ATTR VkResult VKAPI_CALL mockCreateDescriptorPool(VkDevice d,const VkDescriptorPoolCreateInfo*c,const VkAllocationCallbacks*a,VkDescriptorPool*out){assert(d==D.dev&&!a&&c->maxSets==1024&&c->poolSizeCount==2&&c->pPoolSizes[0].descriptorCount==1024&&c->pPoolSizes[1].descriptorCount==4096);seen_pools=(unsigned)F->n_dpool;VkResult r=result_for(++pool_calls);output_handle(out,sizeof *out,pool_calls,400,r);return r;}
static VKAPI_ATTR VkResult VKAPI_CALL mockAllocateDescriptorSets(VkDevice d,const VkDescriptorSetAllocateInfo*c,VkDescriptorSet*out){assert(d==D.dev&&c->descriptorSetCount==1&&c->pSetLayouts&&*c->pSetLayouts);if(!c->descriptorPool||c->descriptorPool==H(VkDescriptorPool,90000))++bad_pool_used;if(++alloc_calls>max_driver_calls){observe("driver-budget");_Exit(88);}unsigned pi=(unsigned)(uintptr_t)c->descriptorPool;unsigned samplers=(unsigned)(uintptr_t)*c->pSetLayouts-20;if(kind==6){assert(pi<1024&&samplers<=MAX_SAMP);if(pool_sets[pi]>=1024||samplers>4096-pool_samplers[pi]){++capacity_violations;observe("capacity-violation");_Exit(89);}}VkResult r=alloc_calls<=n_sequence?alloc_sequence[alloc_calls-1]:alloc_result;if(r==VK_SUCCESS){*out=output_mode==1&&kind==5?VK_NULL_HANDLE:H(VkDescriptorSet,500+alloc_calls);if(kind==6&&*out){++pool_sets[pi];pool_samplers[pi]+=samplers;}}else if(output_mode==2)*out=H(VkDescriptorSet,90000);return r;}
static VKAPI_ATTR void VKAPI_CALL mockUpdateDescriptorSets(VkDevice d,uint32_t n,const VkWriteDescriptorSet*w,uint32_t nc,const VkCopyDescriptorSet*c){assert(d==D.dev&&!nc&&!c);++update_calls;for(uint32_t i=0;i<n;++i){last_set=w[i].dstSet;if(!last_set)++bad_writes;if(w[i].descriptorType==VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER){last_image=*w[i].pImageInfo;if(!last_image.imageView||last_image.imageView==H(VkImageView,90000))++bad_writes;}}}
static VKAPI_ATTR void VKAPI_CALL mockCmdBeginRenderPass(VkCommandBuffer cmd,const VkRenderPassBeginInfo*b,VkSubpassContents s){assert(cmd&&s==VK_SUBPASS_CONTENTS_INLINE);++begin_calls;if(!b->framebuffer||b->framebuffer==H(VkFramebuffer,90000))++bad_begin;}
static VKAPI_ATTR void VKAPI_CALL mockDestroyShaderModule(VkDevice d,VkShaderModule m,const VkAllocationCallbacks*a){assert(d==D.dev&&!a);++destroy_modules;if(m==H(VkShaderModule,90000))++unknown_destroys;}
#define vkCreateImageView mockCreateImageView
#define vkCreateShaderModule mockCreateShaderModule
#define vkCreateFramebuffer mockCreateFramebuffer
#define vkCreateDescriptorPool mockCreateDescriptorPool
#define vkAllocateDescriptorSets mockAllocateDescriptorSets
#define vkUpdateDescriptorSets mockUpdateDescriptorSets
#define vkCmdBeginRenderPass mockCmdBeginRenderPass
#define vkDestroyShaderModule mockDestroyShaderModule
static void flush(int final,int present){assert(!final&&!present);}
static void ring_reset(void*p){assert(p);}
static VKAPI_ATTR VkResult VKAPI_CALL mockWaitForFences(VkDevice d,uint32_t n,const VkFence*f,VkBool32 all,uint64_t timeout){assert(d==D.dev&&n==1&&f&&all==VK_TRUE&&timeout==UINT64_MAX);++wait_calls;return VK_SUCCESS;}
static VKAPI_ATTR VkResult VKAPI_CALL mockResetFences(VkDevice d,uint32_t n,const VkFence*f){assert(d==D.dev&&n==1&&f);return VK_SUCCESS;}
static VKAPI_ATTR VkResult VKAPI_CALL mockResetCommandPool(VkDevice d,VkCommandPool pool,VkCommandPoolResetFlags flags){assert(d==D.dev&&pool&&!flags);return VK_SUCCESS;}
static VKAPI_ATTR VkResult VKAPI_CALL mockResetDescriptorPool(VkDevice d,VkDescriptorPool pool,VkDescriptorPoolResetFlags flags){assert(d==D.dev&&pool&&!flags);unsigned pi=(unsigned)(uintptr_t)pool;assert(pi<1024);pool_sets[pi]=pool_samplers[pi]=0;++descriptor_resets;return VK_SUCCESS;}
#define vkWaitForFences mockWaitForFences
#define vkResetFences mockResetFences
#define vkResetCommandPool mockResetCommandPool
#define vkResetDescriptorPool mockResetDescriptorPool
/* Actual native constructor, with only reflection/table boundaries mocked. */
typedef struct{int used;VkShaderModule vs,fs,vs2,fs2;void*uni,*shadow;int dirty;uint32_t uid;char key[17];}vprog;
typedef struct{const char*refl;const uint32_t*vs,*fs,*vs2,*fs2;int n_vs,n_fs,n_vs2,n_fs2;}vkgl_spv;
#define VKGL_N_SPV 1
#define CINDER_VK_ATTRIBUTES 8
static vkgl_spv VKGL_SPV[1]={{"0000000000001234",words,words,words,words,5,5,5,5}};
static vprog table[2];
static uint64_t prog_key(const char*v,const char*f,const char**a,int n){(void)v;(void)f;(void)a;(void)n;return 0x1234;}
static int native_object_reflection(const char*r,const char*k){return !strcmp(r,k);}
static int native_object_spirv(const uint32_t*w,int n){return w==words&&n==5;}
static int native_object_uniforms(const vprog*p){return p->uni!=NULL;}
static int prog_reflect(vprog*p,const char*r){(void)r;p->uni=calloc(1,4);p->shadow=calloc(1,4);return p->uni&&p->shadow?0:-1;}
static uint32_t prog_gen(void){++prog_gen_calls;return 1;}
static vprog*prog_get(uint32_t id){assert(id==1);return &table[id];}
static int native_reject(void){++rejects;return 0;}
'''

# Real replay-boundary code, not a hand-built NULL-consumer assertion.
replay_start = BASE.index('  VkImageView v[3];', BASE.index('static void replay_pass('))
replay_end_marker = '  vkCmdBeginRenderPass(cmd, &bi, VK_SUBPASS_CONTENTS_INLINE);'
replay_end = BASE.index(replay_end_marker, replay_start) + len(replay_end_marker)
replay = 'static void replay_boundary(const vop*o){vimg*col=o->color,*dep=o->depth,*res=o->resolve;VkRenderPass rp=H(VkRenderPass,11);VkCommandBuffer cmd=H(VkCommandBuffer,12);\n' + BASE[replay_start:replay_end] + '\n}\n'
constructor = function(OBJECTS, 'static void native_object_program_free(') + function(OBJECTS, 'uint32_t cinder_vk_program_create(')
common = (function(BASE, 'static int is_depth(') + '\nstatic const VkComponentMapping SWZ_ID={0,0,0,0};\n' +
          function(BASE, 'static VkResult view_try('))
callers = function(BASE, 'static void tex_view(') + function(BASE, 'static VkDescriptorSet desc_get(')

tests = r'''
static void init(void){assert(n_compats==2);D.dev=H(VkDevice,1);D.serial=41;D.uid=19;D.props.apiVersion=VK_API_VERSION_1_1;F->pool=H(VkCommandPool,2);F->up.pool=H(VkCommandPool,3);F->fence=H(VkFence,4);fbs=calloc(64,sizeof *fbs);cap_fbs=64;F->dpool=calloc(64,sizeof *F->dpool);F->cap_dpool=64;for(int i=0;i<9;++i)dsl[i]=H(VkDescriptorSetLayout,20+i);for(int i=0;i<64;++i)compats[i].rp=H(VkRenderPass,11+i);fail_stage=1;create_result=VK_SUCCESS;alloc_result=VK_SUCCESS;output_mode=3;}
static vimg image(void){return(vimg){.img=H(VkImage,7),.view=H(VkImageView,8),.att=H(VkImageView,9),.fmt=VK_FORMAT_D24_UNORM_S8_UINT,.aspect=VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT,.swz={VK_COMPONENT_SWIZZLE_R,VK_COMPONENT_SWIZZLE_G,VK_COMPONENT_SWIZZLE_B,VK_COMPONENT_SWIZZLE_A},.w=16,.h=16,.levels=3,.layers=1,.samples=1,.view_levels=1,.level_mask=7,.rest=VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};}
static VkDescriptorSet sample(VkImageView v){dkey k={.n=1,.range=64};k.v[0]=v;k.s[0]=H(VkSampler,6);return desc_get(&k);}
static void render_twice(void){vimg im=image();vop o={.compat=0,.w=16,.h=16,.color=&im};replay_boundary(&o);replay_boundary(&o);}
static void normal(void){vimg im=image();im.layers=6;VkImageView v=view_new(&im,1,3);assert(v&&last_view.viewType==VK_IMAGE_VIEW_TYPE_CUBE&&last_view.subresourceRange.layerCount==6&&last_view.subresourceRange.levelCount==3&&last_view.subresourceRange.aspectMask==VK_IMAGE_ASPECT_DEPTH_BIT&&last_view.components.r==VK_COMPONENT_SWIZZLE_R);v=view_new(&im,0,1);assert(v&&last_view.viewType==VK_IMAGE_VIEW_TYPE_2D&&last_view.subresourceRange.layerCount==1&&last_view.subresourceRange.aspectMask==(VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT));im.layers=1;tex_view(&im);assert(im.view&&im.view_levels==3&&dead_calls==1&&last_dead==H(VkImageView,8)&&last_dead_serial==D.serial);VkDescriptorSet s=sample(im.view);assert(s&&update_calls==1&&last_image.imageView==im.view&&last_image.imageLayout==VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);assert(sample(im.view)==s&&update_calls==1);assert(sample(H(VkImageView,777))&&update_calls==2);render_twice();assert(n_fbs==1&&fb_calls==1&&begin_calls==2&&!bad_begin&&last_fb.renderPass==compats[0].rp&&last_fb.width==16&&last_fb.height==16);VkImageView views[3]={H(VkImageView,1),H(VkImageView,2),H(VkImageView,3)};for(int i=0;i<6;++i)assert(fb_get(i%2,views,3,32+i,24));assert(n_fbs==7&&fb_calls==7);assert(cinder_vk_program_create("v","f",NULL,0)==1&&table[1].used&&module_calls==4&&D.uid==20);observe("normal");}
int main(int argc,char**argv){assert(argc==3);platform_native_profile=atoi(argv[1]);init();const char*c=argv[2];if(!strcmp(c,"normal")){normal();return 0;}
 if(!strcmp(c,"cache-keys")){cap_fbs=1;VkImageView v[3]={H(VkImageView,1),H(VkImageView,2),H(VkImageView,3)},alias[3];memcpy(alias,v,sizeof v);VkFramebuffer first=fb_get(0,v,3,16,16);assert(first&&fb_get(0,alias,3,16,16)==first&&fb_calls==1);v[2]=H(VkImageView,9);assert(fb_get(0,v,3,16,16)!=first);v[0]=H(VkImageView,10);assert(fb_get(0,v,3,16,16)!=first);assert(fb_get(0,alias,3,16,16)==first&&fb_calls==3&&fbs[0].v[0]==alias[0]&&fbs[0].v[2]==alias[2]);assert(fb_get(1,alias,3,16,16));assert(fb_get(0,alias,3,17,16));assert(fb_get(0,alias,3,16,17));assert(n_fbs==6&&cap_fbs>=8&&fb_calls==6);observe("cache-keys");return 0;}
 if(!strcmp(c,"existing-pool")){F->n_dpool=2;F->dpool_i=1;F->dpool[0]=H(VkDescriptorPool,17);F->dpool[1]=H(VkDescriptorPool,18);assert(sample(H(VkImageView,8))&&pool_calls==0&&alloc_calls==1&&update_calls==1);observe("existing-pool");return 0;}
 if(!strncmp(c,"budget-",7)){kind=6;D.props.apiVersion=VK_API_VERSION_1_0;max_driver_calls=2000;if(!strcmp(c,"budget-ubo")){for(int i=0;i<1025;++i)assert(desc_alloc(0));}else if(!strcmp(c,"budget-mixed")){for(int i=0;i<511;++i)assert(desc_alloc(8));assert(desc_alloc(4)&&desc_alloc(4)&&desc_alloc(1));}else{for(int i=0;i<512;++i)assert(desc_alloc(8));if(!strcmp(c,"budget-finish"))flush_wait();if(!strcmp(c,"budget-newserial")){D.serial+=2;descriptor_reset_boundary();for(int i=0;i<512;++i)assert(desc_alloc(8));}else assert(desc_alloc(8));}observe("budget-returned");return 0;}
 if(!strncmp(c,"vk10-",5)){kind=5;D.props.apiVersion=VK_API_VERSION_1_0;if(!strcmp(c,"vk10-ambiguous-soft")){alloc_sequence[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;alloc_sequence[1]=VK_SUCCESS;n_sequence=2;}else if(!strcmp(c,"vk10-ambiguous-continuous"))alloc_result=VK_ERROR_OUT_OF_DEVICE_MEMORY;else if(!strcmp(c,"vk10-lost"))alloc_result=VK_ERROR_DEVICE_LOST;else assert(0);sample(H(VkImageView,8));observe("vk10-returned");return 0;}
 if(!strncmp(c,"view-",5)){kind=1;create_result=!strcmp(c,"view-null")?VK_SUCCESS:VK_ERROR_OUT_OF_DEVICE_MEMORY;output_mode=!strcmp(c,"view-error-value")?2:!strcmp(c,"view-null")?1:0;vimg im=image();tex_view(&im);sample(im.view);observe("returned");return 0;}
 if(!strncmp(c,"shader",6)){kind=2;fail_stage=(unsigned)(c[6]-'0');create_result=strstr(c,"null")?VK_SUCCESS:VK_ERROR_OUT_OF_DEVICE_MEMORY;output_mode=strstr(c,"value")?2:strstr(c,"null")?1:0;uint32_t id=cinder_vk_program_create("v","f",NULL,0);printf("PROGRAM id=%u used=%d\n",id,table[1].used);observe("returned");return 0;}
 if(!strncmp(c,"fb-",3)){kind=3;create_result=!strcmp(c,"fb-null")?VK_SUCCESS:VK_ERROR_OUT_OF_DEVICE_MEMORY;output_mode=!strcmp(c,"fb-error-value")?2:!strcmp(c,"fb-null")?1:0;if(!strcmp(c,"fb-bad-hit")){create_result=VK_SUCCESS;fbent*e=&fbs[n_fbs++];e->compat=0;e->w=e->h=16;e->v[0]=H(VkImageView,9);e->fb=VK_NULL_HANDLE;}render_twice();observe("returned");return 0;}
 if(!strncmp(c,"pool-",5)){kind=4;create_result=!strcmp(c,"pool-null")?VK_SUCCESS:VK_ERROR_OUT_OF_HOST_MEMORY;output_mode=!strcmp(c,"pool-error-value")?2:!strcmp(c,"pool-null")?1:0;if(!strcmp(c,"pool-partial")){fail_stage=2;alloc_sequence[0]=VK_ERROR_OUT_OF_POOL_MEMORY;n_sequence=1;}sample(H(VkImageView,8));observe("returned");return 0;}
 if(!strncmp(c,"alloc-",6)){kind=5;if(!strcmp(c,"alloc-soft-success")){alloc_sequence[0]=VK_ERROR_OUT_OF_POOL_MEMORY;alloc_sequence[1]=VK_ERROR_FRAGMENTED_POOL;alloc_sequence[2]=VK_SUCCESS;n_sequence=3;}else if(!strcmp(c,"alloc-continuous"))alloc_result=VK_ERROR_OUT_OF_POOL_MEMORY;else if(!strcmp(c,"alloc-fragmented"))alloc_result=VK_ERROR_FRAGMENTED_POOL;else if(!strcmp(c,"alloc-lost"))alloc_result=VK_ERROR_DEVICE_LOST;else if(!strcmp(c,"alloc-null"))output_mode=1;else if(!strcmp(c,"alloc-host"))alloc_result=VK_ERROR_OUT_OF_HOST_MEMORY;else{alloc_result=VK_ERROR_OUT_OF_DEVICE_MEMORY;if(!strcmp(c,"alloc-oom-value"))output_mode=2;}sample(H(VkImageView,8));observe("returned");return 0;}
 assert(0);}
'''


def fixture(text):
    bodies = '\n'.join(function(text, a) for a in ANCHORS)
    reset_start = text.index('  for (size_t i = 0; i < F->n_dpool; ++i) PLATFORM_CHECK(vkResetDescriptorPool', text.index('static void frame_begin(void) {'))
    reset_marker = '  F->dpool_i = 0;'
    reset_end = text.index(reset_marker, reset_start) + len(reset_marker)
    reset_boundary = 'static void descriptor_reset_boundary(void){\n' + text[reset_start:reset_end] + '\n}\n'
    return (prefix + struct(BASE, 'vimg') + struct(BASE, 'fbent') + struct(BASE, 'dkey') + struct(BASE, 'dent') +
            struct(BASE, 'vop') + state + macro(BASE, 'VKCHECK') + macro(BASE, 'PLATFORM_CHECK') + macro(BASE, 'GROW') + common + bodies + constructor + callers + replay + function(text, 'static void flush_wait(void) {') + reset_boundary + tests)


def parse_observation(stdout):
    lines = [s for s in stdout.splitlines() if s.startswith('OBS ')]
    assert len(lines) == 1, stdout
    return {a: (b if a == 'tag' else int(b)) for a, b in (s.split('=', 1) for s in lines[0].split()[1:])}


cases = ['normal', 'cache-keys', 'existing-pool', 'alloc-fragmented', 'alloc-host', 'alloc-oom-value', 'view-error-empty', 'view-error-value', 'view-null', 'fb-error-empty', 'fb-error-value', 'fb-null', 'fb-bad-hit',
         'pool-error-empty', 'pool-error-value', 'pool-null', 'pool-partial', 'alloc-soft-success', 'alloc-continuous', 'alloc-oom', 'alloc-lost', 'alloc-null']
cases += ['shader' + str(i) + '-' + suffix for i in range(1, 5) for suffix in ('error-empty', 'error-value', 'null')]
cases += ['budget-samplers', 'budget-ubo', 'budget-mixed', 'budget-finish', 'budget-newserial',
          'vk10-ambiguous-soft', 'vk10-ambiguous-continuous', 'vk10-lost']
records = []
with tempfile.TemporaryDirectory(prefix='deep-', dir=OUT) as work:
    work = Path(work); (work / 'tmp').mkdir()
    env = dict(os.environ, TMPDIR=str(work / 'tmp'), TMP=str(work / 'tmp'), TEMP=str(work / 'tmp'), UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    include = ['-I', '/opt/homebrew/include'] if sys.platform == 'darwin' else []
    executables = {}
    for label, source in [('baseline', BASE)] + ([] if red_only else [('current', SOURCE)]):
        c = work / (label + '.c'); c.write_text(fixture(source)); exe = work / label
        cmd = [os.environ.get('CC', 'clang'), '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
               '-Wno-missing-field-initializers', '-fsanitize=undefined', '-fno-sanitize-recover=all', *include, str(c), '-pthread', '-o', str(exe)]
        subprocess.run(cmd, env=env, check=True, timeout=120); executables[label] = exe
        for profile in (0, 1):
            for case in cases:
                p = subprocess.run([str(exe), str(profile), case], env=env, capture_output=True, text=True, timeout=10)
                assert p.returncode in (0, 77, 88, 89), (label, profile, case, p.returncode, p.stdout, p.stderr)
                obs = parse_observation(p.stdout)
                records.append({'source': label, 'profile': profile, 'case': case, 'exit_code': p.returncode, 'observation': obs, 'stdout': p.stdout})
    lookup = {(r['source'], r['profile'], r['case']): r for r in records}
    # Actual controlled OLD RED: initialized outputs/cache slots, not uninitialized guesses.
    assert lookup['baseline', 1, 'view-error-empty']['observation']['bad_writes'] == 1
    assert lookup['baseline', 1, 'fb-error-empty']['observation']['bad_begin'] == 2
    assert lookup['baseline', 1, 'fb-error-empty']['observation']['fbs'] == 1
    assert lookup['baseline', 1, 'shader1-error-value']['observation']['gen'] == 1
    assert lookup['baseline', 1, 'pool-error-empty']['observation']['bad_pool'] == 1
    assert lookup['baseline', 1, 'alloc-null']['observation']['bad_writes'] == 1
    assert lookup['baseline', 1, 'alloc-oom']['exit_code'] == 88
    assert lookup['baseline', 1, 'alloc-continuous']['exit_code'] == 88
    if rollover_red:
        for case, calls in [('budget-samplers', 513), ('budget-ubo', 1025), ('budget-mixed', 514), ('budget-finish', 513)]:
            r = lookup['current', 1, case]
            assert r['exit_code'] == 89 and r['observation']['alloc'] == calls and r['observation']['pools'] == 1
        assert lookup['current', 1, 'vk10-ambiguous-soft']['exit_code'] == 77
    if not red_only and not rollover_red:
        for case in cases:
            a, b = lookup['baseline', 0, case], lookup['current', 0, case]
            assert (a['exit_code'], a['observation'], a['stdout']) == (b['exit_code'], b['observation'], b['stdout']), ('legacy behavior changed', case)
            r = lookup['current', 1, case]; o = r['observation']
            if case.startswith('budget-'):
                expected_allocs = 1025 if case == 'budget-ubo' else 1024 if case == 'budget-newserial' else 514 if case == 'budget-mixed' else 513
                assert r['exit_code'] == 0 and o['capacity_violations'] == 0 and o['alloc'] == expected_allocs
                assert o['pools'] == (1 if case == 'budget-newserial' else 2)
                if case == 'budget-finish':
                    assert o['waits'] == 1 and o['resets'] == 0 and o['serial'] == 41
                if case == 'budget-newserial':
                    assert o['resets'] == 1 and o['serial'] == 43
            elif case == 'vk10-ambiguous-soft':
                assert r['exit_code'] == 0 and o['alloc'] == 2 and o['pools'] == 2 and o['updates'] == 1
            elif case in ('vk10-ambiguous-continuous', 'vk10-lost'):
                assert r['exit_code'] == 77 and o['alloc'] == (1 if case == 'vk10-lost' else 8) and o['cached'] == 0 and o['updates'] == 0
            elif case == 'normal':
                assert r['exit_code'] == 0 and o['seen_fbs'] == 6 and o['unknown_destroy'] == 0
            elif case == 'cache-keys':
                assert r['exit_code'] == 0 and o['fbs'] == 6 and o['fb_calls'] == 6
            elif case == 'existing-pool':
                assert r['exit_code'] == 0 and o['pools'] == 2 and o['pool_calls'] == 0 and o['alloc'] == 1 and o['cached'] == 1
            elif case.startswith('shader'):
                stage = int(case[6]); assert r['exit_code'] == 0 and o['gen'] == 0 and o['uid'] == 19 and o['rejects'] == 1 and o['destroyed'] == stage - 1 and o['unknown_destroy'] == 0
            elif case == 'alloc-soft-success':
                assert r['exit_code'] == 0 and o['alloc'] == 3 and o['pools'] == 3 and o['updates'] == 1 and o['cached'] == 1
            else:
                assert r['exit_code'] == 77 and o['updates'] == 0 and o['begins'] == 0 and o['cached'] == 0 and o['unknown_destroy'] == 0, case
                if case.startswith('fb-'):
                    assert o['fbs'] == (1 if case == 'fb-bad-hit' else 0) and o['seen_fbs'] == 0 and o['lock_free'] == 1
                if case.startswith('pool-'):
                    assert o['pools'] == (1 if case == 'pool-partial' else 0) and o['alloc'] == (1 if case == 'pool-partial' else 0)
                if case in ('alloc-oom', 'alloc-host', 'alloc-oom-value', 'alloc-lost', 'alloc-null'):
                    assert o['alloc'] == 1 and o['pools'] == 1
                if case in ('alloc-continuous', 'alloc-fragmented'):
                    assert o['alloc'] == 8 and o['pools'] == 8
    ndk_results = []
    dependency_root = SOURCE_PATH.parent if (SOURCE_PATH.parent / 'native_vk_platform.inc').is_file() else BASE_PATH.parent
    ndk = os.environ.get('CINDER_DEEP_NDK_CC')
    if ndk and not red_only and not rollover_red:
        for name, flags in [('compat', []), ('compat-egl', ['-DWMMT_EGL']), ('native', ['-DWMMT_NATIVE_VK']), ('native-egl', ['-DWMMT_NATIVE_VK', '-DWMMT_EGL'])]:
            cmd = [ndk, '-c', str(SOURCE_PATH), '-o', str(work / (name + '.o')), '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-parameter', '-Wno-missing-field-initializers', '-DWMMT_VK', *flags, '-I', str(dependency_root), '-I', str(ROOT / 'src')]
            p = subprocess.run(cmd, env=env, text=True, capture_output=True, timeout=120); (OUT / (name + '-ndk.log')).write_text(p.stdout + p.stderr); assert p.returncode == 0, (name, p.stderr)
            ndk_results.append({'mode': name, 'exit_code': p.returncode, 'command': cmd})
    restored = SOURCE
    for anchor in ANCHORS:
        restored = restored.replace(new[anchor], old[anchor], 1)
        if not red_only:
            assert new[anchor].endswith(old[anchor].split('{', 1)[1]), ('Legacy function body changed', anchor)
    only_four = restored == BASE
    if os.environ.get('CINDER_DEEP_REQUIRE_ONLY_FOUR') == '1':
        assert only_four, 'isolated source changed outside four authorized functions'
    report = {'status': 'old_red_verified' if red_only else 'rollover_red_verified' if rollover_red else 'pass', 'source': str(SOURCE_PATH), 'source_sha256': hashlib.sha256(SOURCE_BYTES).hexdigest(),
              'baseline': str(BASE_PATH), 'baseline_sha256': hashlib.sha256(BASE_BYTES).hexdigest(), 'test_sha256': hashlib.sha256(SELF_BYTES).hexdigest(),
              'native_objects_sha256': hashlib.sha256(OBJECT_BYTES).hexdigest(),
              'functions': {a: {'before': hashlib.sha256(old[a].encode()).hexdigest(), 'after': hashlib.sha256(new[a].encode()).hexdigest()} for a in ANCHORS},
              'vkcheck_sha256': hashlib.sha256(macro(SOURCE, 'VKCHECK').encode()).hexdigest(),
              'loader_flush_sha256': hashlib.sha256(protected['static void loader_flush(void) {'].encode()).hexdigest(),
              'image_free_now_sha256': hashlib.sha256(protected['static void image_free_now('].encode()).hexdigest(),
              'records': records, 'ndk': ndk_results, 'ndk_dependency_root': str(dependency_root),
              'only_four_functions_differ_from_baseline': only_four, 'legacy_body_suffixes_byte_exact': not red_only,
              'descriptor_attempt_budget': 8,
              'limits': ['Official Vulkan types; controlled CPU API outputs only', 'Abort is observed as subprocess exit77, never GPU execution', 'Old progressless mocks stop at driver call25 with exit88',
                         'No GPU/driver/device/lifetime-completion proof', 'UBSan only; no ASan/TSan/concurrency or general recovery claim']}
    (OUT / ('red.json' if red_only else 'rollover-red.json' if rollover_red else 'validation.json')).write_text(json.dumps(report, indent=2) + '\n')
print('PASS controlled actual old RED witnesses' if red_only else 'PASS controlled actual v1 Vulkan1.0 rollover RED' if rollover_red else 'PASS actual new/old deep helpers, Native publication/fatal/rollback/rollover contracts and unchanged Legacy controls')
