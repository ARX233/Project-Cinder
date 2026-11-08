#!/usr/bin/env python3
"""ROUND9 actual pipeline functions + full native submit, controlled CPU API results.
No GPU/device, private assets or general concurrency/recovery proof.
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
def core_path(s):
    p = Path(s).expanduser().resolve()
    return p / ('src/vkgl.c' if (p / 'src/vkgl.c').is_file() else 'vkgl.c') if p.is_dir() else p
SOURCE_PATH = core_path(os.environ.get('CINDER_PIPELINE_SOURCE', str(ROOT / 'src/vkgl.c')))
BASE_PATH = core_path(os.environ.get('CINDER_PIPELINE_BASELINE', str(ROOT / '../round9-baseline/src/vkgl.c')))
out_value = os.environ.get('CINDER_TEST_OUT') or os.environ.get('TMPDIR')
if not out_value:
    raise SystemExit('set external CINDER_TEST_OUT or TMPDIR')
OUT_ROOT = Path(out_value).expanduser().resolve()
if not (str(OUT_ROOT) == '/Volumes/CodexWork' or str(OUT_ROOT).startswith('/Volumes/CodexWork/')):
    raise SystemExit('external APFS /Volumes/CodexWork output root required')
OUT_ROOT.mkdir(parents=True, exist_ok=True)
OUT = OUT_ROOT / 'round9-pipeline'; OUT.mkdir(parents=True, exist_ok=True)
SOURCE_BYTES, BASE_BYTES = SOURCE_PATH.read_bytes(), BASE_PATH.read_bytes()
SOURCE, BASE = SOURCE_BYTES.decode(), BASE_BYTES.decode()
NATIVE_BYTES = (BASE_PATH.parent / 'native_vk.inc').read_bytes(); NATIVE = NATIVE_BYTES.decode()
SELF_BYTES = Path(__file__).read_bytes()
ANCHORS = ('static VkPipeline pipeline_make(', 'static VkPipeline pipeline_get(')

def function(s, anchor):
    a = s.index(anchor); end = re.search(r'^}\s*$', s[a:], re.M)
    assert end, anchor
    return s[a:a + end.end()].rstrip() + '\n'

def struct(s, name):
    b = s.index('} ' + name + ';') + len('} ' + name + ';')
    return s[s.rfind('typedef struct', 0, b):b] + '\n'

def macro(s, name):
    a = s.index('#define ' + name); out = ''
    for line in s[a:].splitlines(True):
        out += line
        if not line.rstrip('\r\n').endswith('\\'):
            break
    return out

protected_names = ('static void loader_flush(void) {', 'static void image_free_now(', 'static VkDescriptorSet desc_alloc(',
                   'static VkResult backend_pipeline_create(', 'static int backend_present(void) {')
protected = {a: function(SOURCE, a) for a in protected_names}
assert all(v == function(BASE, k) for k, v in protected.items())
assert macro(SOURCE, 'VKCHECK') == macro(BASE, 'VKCHECK')
for name in ('native_vk.inc', 'native_vk_platform.inc', 'native_vk_present.inc'):
    # Default Main may differ only through independently owned core sampler work.
    p = SOURCE_PATH.parent / name
    if p.is_file():
        assert p.read_bytes() == (BASE_PATH.parent / name).read_bytes(), name
old = {a: function(BASE, a) for a in ANCHORS}; new = {a: function(SOURCE, a) for a in ANCHORS}
red_only = os.environ.get('CINDER_PIPELINE_CAPTURE_RED') == '1'

prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <limits.h>
#include <math.h>
#include <pthread.h>
#include "native_vk.h"
#define H(T,n) ((T)(uintptr_t)(n))
#define MAX_ATTR 8
#define MAX_SAMP 8
typedef uint32_t GLuint,GLenum;
typedef struct{int block;VkDeviceSize off;}vmem;
'''
state = r'''
static struct {VkDevice dev;VkPipelineCache pcache;pthread_mutex_t plock;VkPhysicalDeviceProperties props;uint64_t serial;}D={.plock=PTHREAD_MUTEX_INITIALIZER};
static int platform_native_profile,native_loader_failed;
static pent*pipes;static size_t n_pipes,cap_pipes;
static compat_t compats[4];static VkPipelineLayout playout[MAX_SAMP+1];
static uint64_t native_reject_count,native_draw_count;static unsigned frame_draws;
static vprog program;
static vop *ops;static size_t n_ops,cap_ops;static long cur_pass=-1;
static vitem *items;static size_t n_items,cap_items;
static VkBuffer*vbb;static VkDeviceSize*vbo;static uint32_t*vbs;static size_t n_vb,cap_vb,cap_vbo,cap_vbs;
enum{OP_PASS,OP_BLIT,IT_DRAW=0,IT_CLEAR};
typedef struct{int dummy;}ring;
typedef struct{ring vtx,ubo;}vframe;static vframe frame,*F;
static vimg dummy_images[2],*dummy2d=&dummy_images[0],*dummycube=&dummy_images[1];static VkSampler dummy_sampler;
static unsigned api_calls,destroys,destroy_null,bad_destroy,created_count,ring_calls,sampler_calls,desc_calls,binds,bad_binds,initial_nonnull;
static size_t first_cache,first_cap,first_items;static unsigned first_bad,first_rings,first_desc,first_samplers;
static void snapshot_first(void){first_cache=n_pipes;first_cap=cap_pipes;first_items=n_items;first_rings=ring_calls;first_desc=desc_calls;first_samplers=sampler_calls;for(size_t i=0;i<cap_pipes;++i)first_bad+=pipes[i].used&&!pipes[i].p;}
static unsigned owned[4096],freed[4096];static uint64_t ci_hash=1469598103934665603ull;
static VkResult results[8];static int outputs[8],n_results;
static VkPipeline result_a,result_b;static int made_a,made_b,return_a,return_b;
static pthread_mutex_t mock_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t race_lock=PTHREAD_MUTEX_INITIALIZER;static pthread_cond_t race_cond=PTHREAD_COND_INITIALIZER;
static pthread_t thread_a;static int racing,race_ready,race_done,race_alt,race_fail,race_same,race_partial,stress;
static pkey race_key;
static void logf_(const char*fmt,...){(void)fmt;}
static void*xcalloc(size_t n,size_t s){void*p=calloc(n,s);assert(p);return p;}
static void hash_u(uint64_t n){for(int i=0;i<8;++i){ci_hash=(ci_hash^(unsigned char)n)*1099511628211ull;n>>=8;}}
static VKAPI_ATTR VkResult VKAPI_CALL mockCreateGraphicsPipelines(VkDevice dev,VkPipelineCache cache,uint32_t count,const VkGraphicsPipelineCreateInfo*c,const VkAllocationCallbacks*a,VkPipeline*out){assert(dev==D.dev&&cache==D.pcache&&count==1&&!a&&c->stageCount==2&&c->pStages&&c->layout&&c->renderPass);pthread_mutex_lock(&mock_lock);unsigned call=++api_calls;assert(call<3500);if(*out)++initial_nonnull;int role=racing&&!pthread_equal(pthread_self(),thread_a);VkResult r=call<=(unsigned)n_results?results[call-1]:VK_SUCCESS;int output=call<=(unsigned)n_results?outputs[call-1]:1;if(racing){if(role){r=race_alt&&c->pStages[0].module==H(VkShaderModule,1)?VK_ERROR_OUT_OF_DEVICE_MEMORY:VK_SUCCESS;output=r==VK_SUCCESS;}else{r=race_fail&&c->pStages[0].module==H(VkShaderModule,1)?VK_ERROR_OUT_OF_DEVICE_MEMORY:VK_SUCCESS;output=r==VK_SUCCESS||race_partial;}}if(stress){r=c->pStages[0].module==H(VkShaderModule,1)?VK_ERROR_OUT_OF_DEVICE_MEMORY:VK_SUCCESS;output=r==VK_SUCCESS;}hash_u((uint64_t)(uintptr_t)c->pStages[0].module);hash_u((uint64_t)(uintptr_t)c->pStages[1].module);hash_u((uint64_t)(uintptr_t)c->layout);hash_u(c->pInputAssemblyState->topology);hash_u(c->pRasterizationState->cullMode);hash_u(c->pRasterizationState->frontFace);hash_u(c->pMultisampleState->rasterizationSamples);hash_u(c->pDepthStencilState->depthTestEnable);hash_u(c->pDepthStencilState->depthWriteEnable);hash_u(c->pColorBlendState->attachmentCount);if(c->pColorBlendState->attachmentCount){const VkPipelineColorBlendAttachmentState*b=c->pColorBlendState->pAttachments;hash_u(b->blendEnable);hash_u(b->srcColorBlendFactor);hash_u(b->dstColorBlendFactor);hash_u(b->colorBlendOp);hash_u(b->colorWriteMask);}float flip=0;memcpy(&flip,c->pStages[0].pSpecializationInfo->pData,4);hash_u(flip<0);hash_u(c->pVertexInputState->vertexAttributeDescriptionCount);for(uint32_t i=0;i<c->pVertexInputState->vertexBindingDescriptionCount;++i){hash_u(c->pVertexInputState->pVertexBindingDescriptions[i].stride);hash_u(c->pVertexInputState->pVertexBindingDescriptions[i].inputRate);hash_u(c->pVertexInputState->pVertexAttributeDescriptions[i].format);}if(output>0){unsigned value=race_same?900:500+call;*out=H(VkPipeline,value);++owned[value];++created_count;}else if(!output)*out=VK_NULL_HANDLE;pthread_mutex_unlock(&mock_lock);return r;}
static VKAPI_ATTR void VKAPI_CALL mockDestroyPipeline(VkDevice dev,VkPipeline p,const VkAllocationCallbacks*a){assert(dev==D.dev&&!a);pthread_mutex_lock(&mock_lock);if(!p){++destroy_null;}else{unsigned h=(unsigned)(uintptr_t)p;if(h>=4096||freed[h]>=owned[h])++bad_destroy;else{++freed[h];++destroys;}}pthread_mutex_unlock(&mock_lock);}
#define vkCreateGraphicsPipelines mockCreateGraphicsPipelines
#define vkDestroyPipeline mockDestroyPipeline
static VkResult backend_pipeline_create(const VkGraphicsPipelineCreateInfo*,VkPipeline*);
static vprog*prog_get(uint32_t id){return id==1?&program:NULL;}
static vbuf*buf_get(uint32_t id){(void)id;return NULL;}
static vtex*tex_get(uint32_t id){(void)id;return NULL;}
static int fb_target(uint32_t id,vop*t){if(id)return 0;memset(t,0,sizeof *t);t->compat=0;t->screen=1;t->w=t->h=64;return 1;}
static unsigned char ring_data[65536];
static void*ring_alloc(ring*r,VkDeviceSize n,VkDeviceSize a,VkBuffer*b,VkDeviceSize*off){assert(r&&n<=sizeof ring_data&&a);++ring_calls;*b=H(VkBuffer,20);*off=0;return ring_data;}
static VkDescriptorSet desc_get(const dkey*k){assert(k->n>=0&&k->n<=8&&k->ubo);++desc_calls;return H(VkDescriptorSet,21);}
static VkSampler cinder_vk_sampler_get(const cinder_vk_sampler*s,int levels){assert(s&&levels);++sampler_calls;return H(VkSampler,22);}
static VkSampler sampler_for(const vtex*t,int levels){assert(t&&levels);return H(VkSampler,23);}
static void box_vk(const int*b,const vop*o,int*out){assert(o);memcpy(out,b,4*sizeof(int));}
static VKAPI_ATTR void VKAPI_CALL mockCmdBindPipeline(VkCommandBuffer cmd,VkPipelineBindPoint point,VkPipeline p){assert(cmd&&point==VK_PIPELINE_BIND_POINT_GRAPHICS);++binds;if(!p)++bad_binds;}
#define vkCmdBindPipeline mockCmdBindPipeline
static void simulate_bind_recorded(void);
static void observe(const char*tag){unsigned bad=0,live=0;for(size_t i=0;i<cap_pipes;++i)bad+=pipes[i].used&&!pipes[i].p;for(int i=0;i<4096;++i)live+=owned[i]-freed[i];printf("OBS tag=%s api=%u created=%u destroyed=%u destroy_null=%u bad_destroy=%u live=%u cache=%zu cap=%zu bad_cache=%u alt=%d made_a=%d made_b=%d result_a=%llu result_b=%llu ret_a=%d ret_b=%d rejects=%llu pending=%d items=%zu draws=%llu rings=%u samplers=%u desc=%u binds=%u bad_binds=%u ci=%llu uid=%u initial_nonnull=%u first_cache=%zu first_cap=%zu first_bad=%u first_items=%zu first_rings=%u first_desc=%u first_samplers=%u\n",tag,api_calls,created_count,destroys,destroy_null,bad_destroy,live,n_pipes,cap_pipes,bad,program.alt,made_a,made_b,(unsigned long long)(uintptr_t)result_a,(unsigned long long)(uintptr_t)result_b,return_a,return_b,(unsigned long long)native_reject_count,cinder_vk_error_pending(),n_items,(unsigned long long)native_draw_count,ring_calls,sampler_calls,desc_calls,binds,bad_binds,(unsigned long long)ci_hash,program.uid,initial_nonnull,first_cache,first_cap,first_bad,first_items,first_rings,first_desc,first_samplers);}
'''

native_functions = ('static int native_reject(void) {', 'uint64_t cinder_vk_error_epoch(void) {', 'static int native_program_valid(',
                    'int cinder_vk_draw_init(', 'static int native_format(', 'static int native_span(', 'static int native_box_valid(',
                    'static vop *native_open_target(', 'static void native_key(', 'static int native_sampler_valid(', 'static int native_pipeline_valid(', 'int cinder_vk_submit(')

hooks = r'''
static VkResult backend_pipeline_create(const VkGraphicsPipelineCreateInfo*c,VkPipeline*p){VkResult r=real_backend_pipeline_create(c,p);if(racing&&pthread_equal(pthread_self(),thread_a)){pthread_mutex_lock(&race_lock);if(!race_ready){race_ready=1;pthread_cond_broadcast(&race_cond);while(!race_done)pthread_cond_wait(&race_cond,&race_lock);}pthread_mutex_unlock(&race_lock);}return r;}
static pkey key(void){pkey k={0};k.prog=program.uid;k.compat=0;k.topo=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;k.cmask=15;k.depth_test=k.depth_write=1;k.dfunc=VK_COMPARE_OP_LESS_OR_EQUAL;k.front_ccw=1;k.bsrc=VK_BLEND_FACTOR_SRC_ALPHA;k.bdst=VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;k.afmt[0]=4;k.astride[0]=16;return k;}
static void seed(const pkey*k,VkPipeline p){cap_pipes=8;pipes=xcalloc(cap_pipes,sizeof *pipes);size_t i=hash_bytes(k,sizeof *k)&7;pipes[i]=(pent){*k,p,1};n_pipes=1;}
static void*other_owner(void*unused){(void)unused;pthread_mutex_lock(&race_lock);while(!race_ready)pthread_cond_wait(&race_cond,&race_lock);pthread_mutex_unlock(&race_lock);result_b=pipeline_get(&race_key,&program,&made_b);pthread_mutex_lock(&race_lock);race_done=1;pthread_cond_broadcast(&race_cond);pthread_mutex_unlock(&race_lock);return NULL;}
static void*stress_owner(void*arg){unsigned owner=(unsigned)(uintptr_t)arg;for(unsigned i=0;i<64;++i){pkey k=key();k.astride[0]=(uint16_t)(16+owner*64+i);int made=0;assert(pipeline_get(&k,&program,&made));}return NULL;}
static void init(void){D.dev=H(VkDevice,1);D.pcache=H(VkPipelineCache,2);D.serial=1;D.props.limits.minUniformBufferOffsetAlignment=16;program=(vprog){.used=1,.uid=42,.vs=H(VkShaderModule,1),.fs=H(VkShaderModule,2)};strcpy(program.key,"fixture-program");compats[0]=(compat_t){VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_D24_UNORM_S8_UINT,1,0,H(VkRenderPass,3)};for(int i=0;i<=8;++i)playout[i]=H(VkPipelineLayout,100+i);for(int i=0;i<N_VFMT;++i)vfmt_dev[i]=VFMT[i];F=&frame;dummy2d->view=H(VkImageView,30);dummycube->view=H(VkImageView,31);dummy_sampler=H(VkSampler,32);thread_a=pthread_self();}
int main(int argc,char**argv){assert(argc==3);platform_native_profile=atoi(argv[1]);init();const char*c=argv[2];pkey k=key();if(strstr(c,"alt")){program.vs2=H(VkShaderModule,3);program.fs2=H(VkShaderModule,4);}if(!strcmp(c,"initial-alt"))program.alt=1;
 if(!strcmp(c,"atomic-stress")){stress=1;program.vs2=H(VkShaderModule,3);program.fs2=H(VkShaderModule,4);pthread_t a,b;assert(!pthread_create(&a,NULL,stress_owner,(void*)(uintptr_t)0));assert(!pthread_create(&b,NULL,stress_owner,(void*)(uintptr_t)1));assert(!pthread_join(a,NULL)&&!pthread_join(b,NULL));assert(n_pipes==128&&program.alt==1&&!bad_destroy);observe(c);return 0;}
 if(!strcmp(c,"native-retry-warm")||!strcmp(c,"native-retry-draw")||!strcmp(c,"native-sampler")){cinder_vk_draw d;assert(cinder_vk_draw_init(&d,1,0,64,64));d.count=3;if(strcmp(c,"native-sampler")){results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=0;n_results=1;d.warm_only=!strcmp(c,"native-retry-warm");if(d.warm_only)F=NULL;return_a=cinder_vk_submit(&d);snapshot_first();return_b=cinder_vk_submit(&d);if(d.warm_only){d.warm_only=0;F=&frame;cinder_vk_submit(&d);}}else{program.n_samp=1;program.block=16;d.uniform_bytes=16;d.samplers[0]=(cinder_vk_sampler){.use_state=1,.anisotropy=1};return_a=cinder_vk_submit(&d);}simulate_bind_recorded();observe(c);return 0;}
 if(!strncmp(c,"race-",5)){racing=1;race_fail=strcmp(c,"race-created")!=0&&strcmp(c,"race-same")!=0;race_alt=!strcmp(c,"race-alt");race_same=!strcmp(c,"race-same")||!strcmp(c,"race-partial-same");race_partial=!strcmp(c,"race-partial-same");race_key=k;if(race_alt)race_key.flip=1;pthread_t b;assert(!pthread_create(&b,NULL,other_owner,NULL));result_a=pipeline_get(&k,&program,&made_a);assert(!pthread_join(b,NULL));observe(c);return 0;}
 if(!strcmp(c,"growth")){for(int i=0;i<600;++i){k.astride[0]=(uint16_t)(16+i);int made=0;assert(pipeline_get(&k,&program,&made));}observe(c);return 0;}
 if(!strcmp(c,"null-row")||!strcmp(c,"null-row-retry"))seed(&k,VK_NULL_HANDLE);
 if(!strcmp(c,"vertex-math")){program.inputs=3;k.afmt[1]=3;k.astride[1]=24;k.inst=2;k.blend=1;k.flip=1;k.cull=VK_CULL_MODE_BACK_BIT;k.stencil=1;k.sfunc=VK_COMPARE_OP_ALWAYS;k.smask=k.swmask=255;}
 if(!strcmp(c,"valid-hit")){seed(&k,H(VkPipeline,901));++owned[901];++created_count;made_a=7;}
 if(!strcmp(c,"fail-growth")){cap_pipes=2;pipes=xcalloc(2,sizeof *pipes);pkey other=k;other.flip=1;size_t i=hash_bytes(&other,sizeof other)&1;pipes[i]=(pent){other,H(VkPipeline,901),1};n_pipes=1;++owned[901];++created_count;results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=0;n_results=1;}
 if(!strcmp(c,"made-preserve-fail")){made_a=7;results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=0;n_results=1;}
 if(!strcmp(c,"error-untouched")){results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=-1;n_results=1;}
 if(!strcmp(c,"alt-partial-success")){results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=1;n_results=1;}
 if(!strcmp(c,"device-lost-alt")||!strcmp(c,"device-lost-partial-alt")){results[0]=VK_ERROR_DEVICE_LOST;outputs[0]=!strcmp(c,"device-lost-partial-alt");n_results=1;}
 if(!strcmp(c,"alt-device-lost")){results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=0;results[1]=VK_ERROR_DEVICE_LOST;outputs[1]=1;n_results=2;}
 if(!strcmp(c,"alt-error-untouched")){results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=1;results[1]=VK_ERROR_OUT_OF_HOST_MEMORY;outputs[1]=-1;n_results=2;}
 if(!strcmp(c,"forced-alt-fail")){results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=0;n_results=1;}
 if(!strcmp(c,"error-value")||!strcmp(c,"alt-error-value")){results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=1;results[1]=VK_ERROR_OUT_OF_HOST_MEMORY;outputs[1]=1;n_results=strstr(c,"alt")?2:1;}
 else if(!strcmp(c,"retry")||!strcmp(c,"alt-success")||!strcmp(c,"alt-fail")||!strcmp(c,"alt-null")||!strcmp(c,"null-row-retry")){results[0]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[0]=0;n_results=1;if(!strcmp(c,"alt-fail")){results[1]=VK_ERROR_OUT_OF_DEVICE_MEMORY;outputs[1]=0;n_results=2;}if(!strcmp(c,"alt-null")){results[1]=VK_SUCCESS;outputs[1]=0;n_results=2;}}
 else if(!strcmp(c,"success-null")||!strcmp(c,"primary-null-alt")){results[0]=VK_SUCCESS;outputs[0]=0;n_results=1;}
 if(!strcmp(c,"forced-alt")||!strcmp(c,"forced-alt-fail"))assert(!setenv("VKGL_TEST_ALT","1",1));
 result_a=pipeline_get(&k,&program,&made_a);snapshot_first();if(!strcmp(c,"retry")||!strcmp(c,"null-row-retry")||!strcmp(c,"normal")||!strcmp(c,"fail-growth"))result_b=pipeline_get(&k,&program,&made_b);observe(c);return 0;}
'''

def fixture(text):
    array_a = BASE.index('static const VkFormat VFMT[] ='); array_b = BASE.index('};', array_a) + 2
    types = ''.join(struct(BASE, n) for n in ('vimg', 'vbufmem', 'vbuf', 'vtex', 'vuni', 'vprog', 'compat_t', 'pkey', 'pent', 'vop', 'vitem', 'dkey'))
    real_backend = function(text, 'static VkResult backend_pipeline_create(').replace('backend_pipeline_create(', 'real_backend_pipeline_create(', 1)
    bind_line = next(l for l in text.splitlines() if 'vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, lp = it->pipe)' in l)
    bind = 'static void simulate_bind_recorded(void){VkCommandBuffer cmd=H(VkCommandBuffer,7);VkPipeline lp=VK_NULL_HANDLE;for(size_t i=0;i<n_items;++i){vitem*it=&items[i];if(it->kind!=IT_DRAW)continue;if(!it->pipe)++bad_binds;\n' + bind_line + '\n}}\n'
    return (prefix + types + BASE[array_a:array_b] + '\n#define N_VFMT (int)(sizeof VFMT/sizeof *VFMT)\nstatic VkFormat vfmt_dev[N_VFMT];\n' +
            state + macro(BASE, 'GROW') + function(BASE, 'static int has_stencil(') + function(BASE, 'static uint64_t hash_bytes(') +
            real_backend + '\n'.join(function(text, a) for a in ANCHORS) +
            '\n'.join(function(NATIVE, a) for a in native_functions) + function(text, 'int cinder_vk_error_pending(void) {') + bind + hooks)

def obs(stdout):
    lines = [l for l in stdout.splitlines() if l.startswith('OBS ')]; assert len(lines)==1, stdout
    return {k: v if k=='tag' else int(v) for k,v in (x.split('=',1) for x in lines[0].split()[1:])}

cases = ('normal','retry','success-null','error-value','alt-success','alt-fail','alt-error-value','alt-null','primary-null-alt','initial-alt','forced-alt',
         'null-row','null-row-retry','race-created','race-failed','race-alt','growth','native-retry-warm','native-retry-draw','native-sampler',
         'race-same','race-partial-same','device-lost-alt','device-lost-partial-alt','alt-partial-success','alt-device-lost','error-untouched',
         'made-preserve-fail','valid-hit','fail-growth','forced-alt-fail','alt-error-untouched','vertex-math')
records=[]
with tempfile.TemporaryDirectory(prefix='pipeline-',dir=OUT) as temp:
    work=Path(temp);(work/'tmp').mkdir();env=dict(os.environ,TMPDIR=str(work/'tmp'),TMP=str(work/'tmp'),TEMP=str(work/'tmp'),UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    env.pop('VKGL_TEST_ALT',None);env.pop('VKGL_DEBUG',None)
    includes=['-I',str(BASE_PATH.parent)] + (['-I','/opt/homebrew/include'] if sys.platform=='darwin' else [])
    for label,text in [('baseline',BASE)]+([] if red_only else [('current',SOURCE)]):
        c=work/(label+'.c');c.write_text(fixture(text));exe=work/label
        cmd=[os.environ.get('CC','clang'),'-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-missing-field-initializers','-fsanitize=undefined','-fno-sanitize-recover=all',*includes,str(c),'-pthread','-o',str(exe)]
        subprocess.run(cmd,env=env,check=True,timeout=120)
        for profile in (0,1):
            for case in cases:
                p=subprocess.run([str(exe),str(profile),case],env=env,capture_output=True,text=True,timeout=15)
                assert p.returncode==0,(label,profile,case,p.returncode,p.stdout,p.stderr)
                records.append({'source':label,'profile':profile,'case':case,'observation':obs(p.stdout),'stdout':p.stdout})
    atomic_stress=None
    if not red_only:
        stress_run=subprocess.run([str(work/'current'),'1','atomic-stress'],env=env,capture_output=True,text=True,timeout=30)
        assert stress_run.returncode==0,(stress_run.returncode,stress_run.stdout,stress_run.stderr)
        atomic_stress=obs(stress_run.stdout)
        assert atomic_stress['cache']==128 and atomic_stress['alt']==1 and not atomic_stress['bad_destroy'] and not atomic_stress['bad_cache'] and not atomic_stress['initial_nonnull']
    rows={(r['source'],r['profile'],r['case']):r for r in records}
    for c in ('retry','native-retry-warm','native-retry-draw'):
        o=rows['baseline',1,c]['observation'];assert o['api']==1 and o['bad_cache']==1
    assert rows['baseline',1,'success-null']['observation']['made_a']==1
    assert rows['baseline',1,'alt-null']['observation']['alt']==1
    assert rows['baseline',1,'error-value']['observation']['destroyed']==0
    if not red_only:
        for case in cases:
            assert rows['baseline',0,case]['stdout']==rows['current',0,case]['stdout'],('Legacy changed',case)
            o=rows['current',1,case]['observation'];assert not o['bad_destroy'] and not o['bad_binds'] and o['uid']==42 and not o['initial_nonnull']
            if case in ('normal','alt-success','initial-alt','forced-alt','growth','native-sampler','vertex-math'):
                assert o['ci']==rows['baseline',1,case]['observation']['ci'], ('Native fixed-state math changed',case)
            if case=='normal':assert o['api']==1 and o['cache']==1 and o['made_a']==1 and o['made_b']==0
            elif case=='retry':assert o['api']==2 and o['cache']==1 and not o['made_a'] and o['made_b']==1 and not o['bad_cache'] and o['first_cache']==o['first_cap']==o['first_bad']==0
            elif case in ('success-null','alt-fail','alt-error-value','alt-null','error-value','error-untouched','forced-alt-fail','alt-error-untouched','alt-device-lost','device-lost-alt','device-lost-partial-alt'):
                assert o['result_a']==0 and o['cache']==0 and o['made_a']==0 and o['alt']==0 and o['bad_cache']==0
                if case=='error-value':assert o['destroyed']==1
                if case=='alt-error-value':assert o['destroyed']==2
                if case in ('alt-error-untouched','alt-device-lost','device-lost-partial-alt'):assert o['destroyed']==1
                if case in ('device-lost-alt','device-lost-partial-alt'):assert o['api']==1
            elif case in ('alt-success','primary-null-alt','forced-alt','alt-partial-success'):
                assert o['result_a'] and o['alt']==1 and o['cache']==1 and o['made_a']==1
                if case=='alt-partial-success':assert o['created']==2 and o['destroyed']==1 and o['live']==1
            elif case=='initial-alt':assert o['api']==1 and o['alt']==1 and o['result_a']
            elif case=='made-preserve-fail':assert o['result_a']==0 and o['made_a']==7 and o['cache']==0
            elif case=='valid-hit':assert o['result_a']==901 and o['made_a']==7 and o['api']==0 and o['cache']==1 and o['destroyed']==0
            elif case=='fail-growth':assert o['first_cap']==2 and o['first_cache']==1 and o['first_bad']==0 and o['made_a']==0 and o['made_b']==1 and o['api']==2 and o['cache']==2 and o['cap']==4 and not o['bad_cache']
            elif case=='vertex-math':assert o['result_a'] and o['api']==1 and o['cache']==1
            elif case in ('null-row','null-row-retry'):assert o['cache']==1 and not o['bad_cache'] and o['result_a' if case=='null-row' else 'result_b']
            elif case in ('race-created','race-failed','race-same','race-partial-same'):
                assert o['cache']==1 and o['result_a']==o['result_b'] and o['result_a'] and not o['made_a'] and o['made_b']==1
                assert o['destroyed']==(0 if case=='race-failed' else 1) and o['destroy_null']==0
                if case in ('race-same','race-partial-same'):assert o['created']==2 and o['live']==1 and o['result_a']==900
            elif case=='race-alt':assert o['cache']==2 and o['api']==4 and o['alt']==1 and o['result_a'] and o['result_b']
            elif case=='growth':assert o['api']==600 and o['cache']==600 and o['cap']==2048 and not o['bad_cache']
            elif case in ('native-retry-warm','native-retry-draw'):
                assert o['ret_a']==0 and o['ret_b']==1 and o['api']==2 and o['rejects']==1 and not o['pending'] and o['items'] and o['binds'] and not o['bad_cache'] and o['first_cache']==o['first_cap']==o['first_bad']==o['first_items']==o['first_rings']==o['first_desc']==o['first_samplers']==0
            elif case=='native-sampler':assert o['ret_a']==1 and o['samplers']==1 and o['rings']==1 and o['desc']==1 and o['items']==1
    tsan={'status':'not-requested'}
    if os.environ.get('CINDER_PIPELINE_TSAN')=='1' and not red_only:
        tsan_exe=work/'current-tsan'
        tsan_cmd=[os.environ.get('CC','clang'),'-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-missing-field-initializers','-fsanitize=thread',*includes,str(work/'current.c'),'-pthread','-o',str(tsan_exe)]
        tc=subprocess.run(tsan_cmd,env=env,capture_output=True,text=True,timeout=120)
        tsan_log=tc.stdout+tc.stderr
        if tc.returncode:
            tsan={'status':'unavailable-compile','exit_code':tc.returncode}
        else:
            te=dict(env,TSAN_OPTIONS='halt_on_error=1:exitcode=66')
            probe=subprocess.run([str(tsan_exe),'1','normal'],env=te,capture_output=True,text=True,timeout=30)
            tsan_log+=probe.stdout+probe.stderr
            if probe.returncode:
                assert 'data race' not in probe.stderr.lower(), probe.stderr
                tsan={'status':'unavailable-runtime','exit_code':probe.returncode,'stderr':probe.stderr}
            else:
                checked=[]
                for case in ('race-created','race-failed','race-alt','race-same','race-partial-same','atomic-stress'):
                    tp=subprocess.run([str(tsan_exe),'1',case],env=te,capture_output=True,text=True,timeout=30)
                    tsan_log+=tp.stdout+tp.stderr
                    assert tp.returncode==0 and 'WARNING: ThreadSanitizer' not in tp.stderr,(case,tp.returncode,tp.stdout,tp.stderr)
                    checked.append(case)
                tsan={'status':'pass-controlled','cases':checked}
        (OUT/'tsan.log').write_text(tsan_log)
    ndk_results=[]
    if os.environ.get('CINDER_PIPELINE_NDK_CC') and not red_only:
        dependency_root=SOURCE_PATH.parent if (SOURCE_PATH.parent/'native_vk.inc').is_file() else BASE_PATH.parent
        for mode,flags in [('compat',[]),('compat-egl',['-DWMMT_EGL']),('native',['-DWMMT_NATIVE_VK']),('native-egl',['-DWMMT_NATIVE_VK','-DWMMT_EGL'])]:
            command=[os.environ['CINDER_PIPELINE_NDK_CC'],'-c',str(SOURCE_PATH),'-o',str(work/(mode+'.o')),'-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter','-Wno-missing-field-initializers','-DWMMT_VK',*flags,'-I',str(dependency_root),'-I',str(ROOT/'src')]
            p=subprocess.run(command,env=env,capture_output=True,text=True,timeout=120);(OUT/(mode+'-ndk.log')).write_text(p.stdout+p.stderr);assert p.returncode==0,(mode,p.stderr);ndk_results.append({'mode':mode,'command':command,'exit_code':p.returncode})
    restored=SOURCE
    for a in ANCHORS:
        restored=restored.replace(new[a],old[a],1)
        if not red_only:assert new[a].endswith(old[a].split('{',1)[1]),('Legacy body changed',a)
    if os.environ.get('CINDER_PIPELINE_REQUIRE_ONLY_TWO')=='1':assert restored==BASE
    report={'status':'old_red_verified' if red_only else 'pass','source':str(SOURCE_PATH),'source_sha256':hashlib.sha256(SOURCE_BYTES).hexdigest(),
            'baseline':str(BASE_PATH),'baseline_sha256':hashlib.sha256(BASE_BYTES).hexdigest(),'test_sha256':hashlib.sha256(SELF_BYTES).hexdigest(),
            'functions':{a:{'before':hashlib.sha256(old[a].encode()).hexdigest(),'after':hashlib.sha256(new[a].encode()).hexdigest()} for a in ANCHORS},
            'protected':{a:hashlib.sha256(v.encode()).hexdigest() for a,v in protected.items()},'vkcheck_sha256':hashlib.sha256(macro(SOURCE,'VKCHECK').encode()).hexdigest(),
            'native_inc_sha256':hashlib.sha256(NATIVE_BYTES).hexdigest(),'only_two_restore_baseline':restored==BASE,'records':records,'atomic_stress_ubsan':atomic_stress,'ndk':ndk_results,'tsan':tsan,
            'limits':['Controlled CPU Vulkan API outputs, not GPU/driver/device proof','Real pipeline-create lock wrapper runs; barrier instrumentation is after it releases the lock','Race proof is bounded interleaving only; no arbitrary concurrency/lifetime guarantee','UBSan; no implicit TSan claim','Count1 error+nonNULL is ownership stress using defined failed-call cleanup rule, not normal mixed-batch conformance']}
    (OUT/('red.json' if red_only else 'validation.json')).write_text(json.dumps(report,indent=2)+'\n')
print('PASS actual old NULL-cache/partial-output RED' if red_only else 'PASS actual pipelines, native submit retry, partial cleanup, cache and controlled race contracts')
