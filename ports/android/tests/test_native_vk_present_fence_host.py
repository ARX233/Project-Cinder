#!/usr/bin/env python3
"""Actual optional maintenance1 negotiation and PRESENT resource-retirement tests.
Strict host UBSan and official NDK types; Vulkan/OS/allocation effects are mocks,
not scanout, display timing, hardware completion or whole-library GL elimination.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('CINDER_TEST_OUT', os.environ.get('TMPDIR', tempfile.gettempdir()))).resolve() / 'native-present-fence'
assert ROOT != OUT and ROOT not in OUT.parents, 'artifacts must stay outside source'
OUT.mkdir(parents=True, exist_ok=True)
base = os.environ.get('CINDER_PRESENT_BASELINE') or os.environ.get('CINDER_ANDROID_BASELINE') or os.environ.get('CINDER_PLATFORM_BASELINE')
assert base, 'set CINDER_PRESENT_BASELINE (or Android/platform baseline) to the Round8 file/tree'
BASELINE = Path(base).resolve()
if BASELINE.is_dir():
    BASELINE = BASELINE / ('src/main_android.c' if (BASELINE / 'src/main_android.c').exists() else 'main_android.c')
BASE_BYTES = BASELINE.read_bytes()
INPUT_NAMES = ('src/vkgl.c','src/native_vk.h','src/native_vk_platform.inc','src/native_vk_present.inc','src/main_android.c',
               'src/native_vk.inc','src/native_vk_upload.inc','src/native_vk_resources.inc','tests/test_native_vk_present_fence_host.py')
INPUTS = {n:(ROOT/n).read_bytes() for n in INPUT_NAMES}
CORE = INPUTS['src/vkgl.c'].decode(); PLATFORM=INPUTS['src/native_vk_platform.inc'].decode(); PRESENT=INPUTS['src/native_vk_present.inc'].decode()
H=lambda b:hashlib.sha256(b).hexdigest()
def fun(source,anchor):
    a=source.index(anchor); b=source.index('{',a)
    mask=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),source,flags=re.S)
    depth=0
    for k in range(b,len(source)):
        depth+=(mask[k]=='{')-(mask[k]=='}')
        if not depth:return source[a:k+1]+'\n'
    raise AssertionError(anchor)

anchors = ('static void dead_add(', 'static void dead_free(', 'static void image_drop(', 'static int native_image_upload_hold(', 'static int native_target_image_hold(', 'static void native_target_image_release(', 'static void native_image_upload_complete(', 'static VkRenderPass rp_make(', 'static int compat_id(', 'static int native_compat_id(', 'static VkRenderPass rp_get(', 'static void ring_reset(', 'static void uploader_init(', 'static VkResult submit(', 'static void barrier(', 'static void image_upload_record(', 'static VkSemaphore backend_render_semaphore(void)', 'static int acquire(void)', 'static void frame_begin(void)', 'static void flush(int final', 'static void flush_wait(void)', 'int cinder_vk_flush(void)', 'int cinder_vk_finish(void)', 'int cinder_vk_error_pending(void)', 'static int backend_present(void)', 'static void screen_free(void)', 'static int backend_surface(', 'static void backend_release_surface(void)', 'static VkResult backend_pipeline_create(', 'static void backend_pipeline_cache_file(', 'static void backend_pipeline_cache_save(void)', 'static int has_ext(', 'static vimg *backend_dummy_image(', 'static int backend_create(', 'static int is_depth(', 'static VkResult view_try(')

shared={a:fun(CORE,a) for a in anchors}
selected='\n'.join(shared.values())+PRESENT+PLATFORM
for token in ('ctx','cur_up','main_ctx','loader_ctx','cur_vao','GLenum','GLuint','GLfloat','GLboolean','GL_EXTENSIONS','glGetString','glBindFramebuffer','vkgl_create','vkgl_present','vkgl_surface','vkgl_release_surface'):
    assert not re.search(r'\b'+token+r'\b',re.sub(r'/\*.*?\*/|//[^\n]*','',selected,flags=re.S)),token
assert 'get_features(D.pd, &features)' in PRESENT and 'vkGetPhysicalDeviceFeatures2KHR' in PRESENT
assert 'vkGetPhysicalDeviceFeatures2(' not in selected

prefix = r'''

#include <assert.h>
#include <limits.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>
#include "native_vk.h"
#define FRAMES 2
#define MAX_SAMP 8
#define H(T,n) ((T)(uintptr_t)(n))
#define SW(R,G,B,A) ((VkComponentMapping){VK_COMPONENT_SWIZZLE_##R,VK_COMPONENT_SWIZZLE_##G,VK_COMPONENT_SWIZZLE_##B,VK_COMPONENT_SWIZZLE_##A})
#define SWZ_ID SW(IDENTITY,IDENTITY,IDENTITY,IDENTITY)

enum { I_SURFACE=1, I_PROPS=2, I_CAPS=4, I_EXT=8, I_KHR=16, D_SWAP=1, D_EXT=2, D_KHR=4 };
static unsigned inst_ads=31,dev_ads=7,instance_enum_calls,features_calls,proc_calls,instance_create_calls,device_create_calls;
static unsigned inst_enum_fault,dev_enum_fault,missing_proc,feature_value=1,optional_instance_failure,optional_device_failure;
static uint32_t physical_api=VK_API_VERSION_1_0;
static char enabled_instance[16][VK_MAX_EXTENSION_NAME_SIZE],enabled_device[8][VK_MAX_EXTENSION_NAME_SIZE];
static uint32_t enabled_instance_count,enabled_device_count;
static int model_strict,model_device_feature,phase_present_pool,per_result_missing,per_result_override;
static VkResult model_per_result;
static unsigned present_fence_creates,present_fence_destroys,present_waits,present_resets,fail_present_fence_at,fail_present_fence_mode;
static unsigned fail_present_wait_at,fail_present_reset_at,destructions,view_new_calls,view_try_calls,view_failure_mode;
static unsigned pool_alloc_fail,abort_expected,abort_image,abort_destructions,abort_waits,abort_resets;
static const VkResult missing_result=(VkResult)INT32_MIN;static VkResult present_wait_error=VK_TIMEOUT;static uintptr_t abort_fence;
typedef struct {unsigned created,kind,pending,signaled,waited,destroyed;uintptr_t semaphore;}model_fence;
static model_fence mf[8192];
typedef struct {char op;uintptr_t object;}model_event;static model_event events[8192];static unsigned event_count;
static void event(char op,uintptr_t object){assert(event_count<8192);events[event_count++]=(model_event){op,object};}
static int name_in(char names[][VK_MAX_EXTENSION_NAME_SIZE],uint32_t n,const char*name){for(uint32_t i=0;i<n;++i)if(!strcmp(names[i],name))return 1;return 0;}
static unsigned model_pending(void){unsigned n=0;for(unsigned i=0;i<8192;++i)n+=mf[i].created&&mf[i].kind&&mf[i].pending;return n;}
static void must_retire(void){if(model_strict)assert(!model_pending()&&"PRESENT fence completion required, not submit-fence/device-idle");}
static void guarded_abort(void);
static void*model_calloc(size_t n,size_t size){if(pool_alloc_fail&&n==3){pool_alloc_fail=0;return NULL;}return calloc(n,size);}

static int platform_native_profile,platform_created,platform_create_attempted,native_frame_claimed;
static uint64_t native_reject_count;
static _Atomic int native_loader_failed;
static struct {VkInstance inst;VkPhysicalDevice pd;VkDevice dev;VkQueue q;uint32_t qfam;
 VkPhysicalDeviceProperties props;VkPhysicalDeviceMemoryProperties mp;int aniso,astc,swapchain_ext;float max_aniso;int max_samples;
 pthread_mutex_t lock,qlock,plock;VkPipelineCache pcache;char pcache_path[512];VkFormat f4444,f5551,f11,fd24,fs16;
 VkComponentMapping sw4444,sw5551;int conv5551;uint32_t lazy_type,uid;uint64_t serial,done;}D;
typedef struct {VkBuffer buf;uint8_t*map;VkDeviceSize size;}vbufmem;
typedef struct {int block;}vmem;
typedef struct {VkImage img;VkImageView att,view;vmem mem;VkFormat fmt;int w,h,levels,layers,samples;
 VkImageAspectFlags aspect;VkImageUsageFlags usage;VkComponentMapping swz;VkImageLayout rest;uint32_t uid;
 int swapchain,implicit,in_rest,defined,level_mask;uint64_t serial;int native_upload_pending,native_retire_pending;uint32_t native_target_refs;}vimg;
enum{DEAD_IMAGE,DEAD_BUFMEM,DEAD_VIEW,DEAD_FB};typedef struct{int kind;void*p;uint64_t h,serial;}dead_t;
static dead_t*dead;static size_t n_dead,cap_dead;static vimg**native_upload_images;static size_t n_native_upload_images,cap_native_upload_images;
#define GROW(p,n,cap) do{if((n)>=(cap)){size_t c_=(cap)?(size_t)(cap)*2:64;void*q_=realloc((p),c_*sizeof*(p));assert(q_);(p)=q_;(cap)=c_;}}while(0)
typedef struct {vbufmem**b;size_t n,cap,i;VkDeviceSize used,chunk;VkBufferUsageFlags usage;}ring;
typedef struct {VkCommandPool pool;VkCommandBuffer cmd;int open;VkFence fence;ring stage;}uploader;
typedef struct {VkCommandPool pool;VkCommandBuffer cmd;int open;uploader up;VkFence fence;int submitted;VkSemaphore acquire,render_done;
 ring ubo,vtx;VkDescriptorPool*dpool;size_t n_dpool,cap_dpool,dpool_i;}vframe;
static vframe FR[FRAMES],*F;static uploader LOADER_UP;
static VkDescriptorSetLayout dsl[MAX_SAMP+1];static VkPipelineLayout playout[MAX_SAMP+1];
static vimg *dummy2d,*dummycube;static VkSampler dummy_sampler;
static struct {VkSurfaceKHR surface;VkSwapchainKHR chain;vimg**img;uint32_t n,cur;int acquired,headless,w,h;VkFormat fmt;
 vimg*ms,*depth;int samples,compat;}S={.compat=-1};
static vimg SCREEN;
enum{OP_PASS};typedef struct{int kind,screen,w,h,compat;vimg*color,*depth,*resolve;}vop;
static size_t n_ops,n_items,n_vb;static int S_waited,S_out_of_date;
static VkSemaphore*native_present_wait;static uint32_t native_present_count;
static unsigned semaphore_state[4096],acquire_image[4096],sem_create_calls,sem_destroy_calls,sem_destroyed[4096],fail_sem_at,swap_n=2,next_acquire;
static unsigned idle_calls;

static unsigned seq,wait_seq,destroy_seq,copy_count,submit_count,acquire_count,present_count,instance_destroyed,surface_destroyed[1024],chain_destroyed,live_images,view_destroys;
typedef struct{VkFormat cfmt,dfmt;int samples,resolve;VkRenderPass rp;}compat_t;static compat_t compats[64];static int n_compats;
typedef struct{int compat;uint8_t cload,cstore,dload,dstore,sload,sstore,cundef,dundef;VkImageLayout crest,drest,rrest;VkRenderPass rp;}rp_t;
static rp_t*rps;static size_t n_rps,cap_rps;
static int render_fault,render_initial_null,render_create_calls;

static unsigned fail_view_at;static int fault,image_calls,fail_image_at,fail_stage,fail_begin,wait_fault,present_result,acquire_result,cap_zero,cap_variable;
static unsigned next_handle=10;
static void logf_(const char*fmt,...){(void)fmt;}
#define VKCHECK(x) do{VkResult r_=(x);if(r_!=VK_SUCCESS)logf_("failure");}while(0)
#define PLATFORM_CHECK(x) do{VkResult r_=(x);if(r_!=VK_SUCCESS&&platform_native_profile)abort();}while(0)
static void*xcalloc(size_t n,size_t s){void*p=calloc(n?n:1,s);assert(p);return p;}
static int same(const char*a,const char*b){return !strcmp(a,b);}
static uint32_t resource_uid_next(void){return ++D.uid;}
static uint64_t done_serial(void){return D.done;}
static void close_pass(void){}
static void replay(VkCommandBuffer c,int final){assert(c==F->cmd);(void)final;}
static void loader_flush(void){assert(0&&"loader boundary not used by platform frame tests");}
static void fb_cache_forget(VkImageView v){assert(v);must_retire();event('B',(uintptr_t)v);++seq;}
static void image_free_now(vimg*im){assert(im&&live_images);assert(!im->swapchain);--live_images;free(im);}
static vimg*image_new(VkFormat fmt,int w,int h,int levels,int layers,int samples,int sampled,int transient,VkComponentMapping swz){
 (void)sampled;(void)transient;if(++image_calls==fail_image_at)return NULL;vimg*im=calloc(1,sizeof*im);assert(im);++live_images;
 im->img=H(VkImage,++next_handle);im->att=H(VkImageView,++next_handle);im->view=H(VkImageView,++next_handle);im->mem.block=-1;
 im->fmt=fmt;im->w=w;im->h=h;im->levels=levels;im->layers=layers;im->samples=samples;im->swz=swz;im->uid=resource_uid_next();
 im->aspect=fmt==VK_FORMAT_D24_UNORM_S8_UINT?(VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT):VK_IMAGE_ASPECT_COLOR_BIT;
 im->usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;im->rest=VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;return im;}
static VkImageView view_new(const vimg*im,int sampled,int levels){assert(im->swapchain&&!sampled&&levels==1);++view_new_calls;return H(VkImageView,++next_handle);}
static vbufmem*bufmem_try_new(VkDeviceSize bytes,VkBufferUsageFlags usage){assert(usage);if(fail_stage)return NULL;vbufmem*b=calloc(1,sizeof*b);assert(b);b->buf=H(VkBuffer,++next_handle);b->map=calloc(1,(size_t)bytes);b->size=bytes;assert(b->map);return b;}
static void bufmem_free(vbufmem*b){free(b->map);free(b);}
static VkFormatProperties fmt_props(VkFormat fmt){assert(fmt);return (VkFormatProperties){.optimalTilingFeatures=~0u,.bufferFeatures=~0u};}
static int fmt_has(VkFormat fmt,VkFormatFeatureFlags flags){return (fmt_props(fmt).optimalTilingFeatures&flags)==flags;}
static uint32_t mem_type(uint32_t bits,VkMemoryPropertyFlags want,VkMemoryPropertyFlags pref){(void)bits;(void)want;(void)pref;return ~0u;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateInstance(const VkInstanceCreateInfo*i,const VkAllocationCallbacks*a,VkInstance*out){(void)a;++instance_create_calls;assert(i->pApplicationInfo->apiVersion==VK_API_VERSION_1_0&&i->enabledExtensionCount<=16);enabled_instance_count=i->enabledExtensionCount;
 for(uint32_t k=0;k<enabled_instance_count;++k){strcpy(enabled_instance[k],i->ppEnabledExtensionNames[k]);for(uint32_t j=0;j<k;++j)assert(strcmp(enabled_instance[j],enabled_instance[k]));}
 if(optional_instance_failure==1)return VK_ERROR_EXTENSION_NOT_PRESENT;if(optional_instance_failure==2)return VK_SUCCESS;*out=H(VkInstance,1);return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyInstance(VkInstance i,const VkAllocationCallbacks*a){(void)a;assert(i==D.inst);++instance_destroyed;}
VKAPI_ATTR VkResult VKAPI_CALL vkEnumeratePhysicalDevices(VkInstance i,uint32_t*n,VkPhysicalDevice*p){assert(i);*n=fault==21?0:(!p&&fault==29)?1025:(p&&fault==27)?0:(p&&fault==28)?2:1;if(p&&*n)*p=H(VkPhysicalDevice,2);if((!p&&fault==24)||(p&&fault==25))return VK_ERROR_INITIALIZATION_FAILED;if(p&&fault==26)return VK_INCOMPLETE;return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice d,uint32_t*n,VkQueueFamilyProperties*q){assert(d);*n=fault==47?0:(q&&fault==46)?2:1;if(q)*q=(VkQueueFamilyProperties){.queueFlags=fault==22?0:VK_QUEUE_GRAPHICS_BIT};}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceProperties(VkPhysicalDevice d,VkPhysicalDeviceProperties*p){assert(d);memset(p,0,sizeof*p);strcpy(p->deviceName,"mock-native");p->apiVersion=physical_api;p->limits.maxImageDimension2D=4096;p->limits.maxSamplerAnisotropy=4;p->limits.framebufferColorSampleCounts=p->limits.framebufferDepthSampleCounts=5;}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice d,VkPhysicalDeviceMemoryProperties*p){assert(d);memset(p,0,sizeof*p);}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceFeatures(VkPhysicalDevice d,VkPhysicalDeviceFeatures*p){assert(d);memset(p,0,sizeof*p);}
VKAPI_ATTR VkResult VKAPI_CALL vkEnumerateDeviceExtensionProperties(VkPhysicalDevice d,const char*l,uint32_t*n,VkExtensionProperties*p){(void)l;assert(d);const char*names[3];unsigned count=0;if(dev_ads&D_SWAP)names[count++]=VK_KHR_SWAPCHAIN_EXTENSION_NAME;if(dev_ads&D_EXT)names[count++]="VK_EXT_swapchain_maintenance1";if(dev_ads&D_KHR)names[count++]="VK_KHR_swapchain_maintenance1";uint32_t cap=p?*n:0;if(p)for(uint32_t k=0;k<count&&k<cap;++k)strcpy(p[k].extensionName,names[k]);*n=(dev_enum_fault==3)?0:(p&&dev_enum_fault==4)?cap+1:count;if((!p&&dev_enum_fault==1)||(p&&dev_enum_fault==2))return VK_ERROR_INITIALIZATION_FAILED;return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateDevice(VkPhysicalDevice d,const VkDeviceCreateInfo*i,const VkAllocationCallbacks*a,VkDevice*out){(void)a;assert(d&&i->queueCreateInfoCount==1&&i->enabledExtensionCount<=8&&i->pEnabledFeatures);++device_create_calls;enabled_device_count=i->enabledExtensionCount;for(uint32_t k=0;k<enabled_device_count;++k)strcpy(enabled_device[k],i->ppEnabledExtensionNames[k]);model_device_feature=i->pNext!=NULL;
 if(i->pNext){const VkPhysicalDeviceSwapchainMaintenance1FeaturesEXT*f=i->pNext;assert(f->sType==VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SWAPCHAIN_MAINTENANCE_1_FEATURES_EXT&&!f->pNext&&f->swapchainMaintenance1==VK_TRUE);assert(name_in(enabled_instance,enabled_instance_count,"VK_KHR_get_physical_device_properties2")&&name_in(enabled_instance,enabled_instance_count,"VK_KHR_get_surface_capabilities2"));int ext=name_in(enabled_device,enabled_device_count,"VK_EXT_swapchain_maintenance1"),khr=name_in(enabled_device,enabled_device_count,"VK_KHR_swapchain_maintenance1");assert(ext!=khr);assert(name_in(enabled_instance,enabled_instance_count,ext?"VK_EXT_surface_maintenance1":"VK_KHR_surface_maintenance1"));}
 if(optional_device_failure==1)return VK_ERROR_FEATURE_NOT_PRESENT;if(optional_device_failure==2)return VK_SUCCESS;model_strict=model_device_feature;*out=H(VkDevice,3);return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkGetDeviceQueue(VkDevice d,uint32_t q,uint32_t i,VkQueue*out){assert(d&&!q&&!i);*out=H(VkQueue,4);}
#define MAKE_FN(name,Info,Handle) VKAPI_ATTR VkResult VKAPI_CALL name(VkDevice d,const Info*i,const VkAllocationCallbacks*a,Handle*out){(void)a;assert(d&&i);*out=H(Handle,++next_handle);return VK_SUCCESS;}
MAKE_FN(vkCreatePipelineCache,VkPipelineCacheCreateInfo,VkPipelineCache)
MAKE_FN(vkCreateDescriptorSetLayout,VkDescriptorSetLayoutCreateInfo,VkDescriptorSetLayout)
MAKE_FN(vkCreatePipelineLayout,VkPipelineLayoutCreateInfo,VkPipelineLayout)
MAKE_FN(vkCreateCommandPool,VkCommandPoolCreateInfo,VkCommandPool)
VKAPI_ATTR VkResult VKAPI_CALL vkCreateFence(VkDevice d,const VkFenceCreateInfo*i,const VkAllocationCallbacks*a,VkFence*out){(void)a;assert(d&&i);if(phase_present_pool){assert(!i->flags);++present_fence_creates;if(present_fence_creates==fail_present_fence_at){if(fail_present_fence_mode==2)return VK_SUCCESS;if(fail_present_fence_mode==3)*out=H(VkFence,8000);return VK_ERROR_OUT_OF_HOST_MEMORY;}}
 *out=H(VkFence,++next_handle);assert(next_handle<8192);mf[next_handle]=(model_fence){.created=1,.kind=(unsigned)phase_present_pool,.signaled=!!(i->flags&VK_FENCE_CREATE_SIGNALED_BIT)};return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyFence(VkDevice d,VkFence fence,const VkAllocationCallbacks*a){(void)a;uintptr_t f=(uintptr_t)fence;assert(d&&f<8192&&mf[f].created&&mf[f].kind&&!mf[f].pending&&!mf[f].destroyed);mf[f].destroyed=1;++present_fence_destroys;++destructions;event('Z',f);}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateSemaphore(VkDevice d,const VkSemaphoreCreateInfo*i,const VkAllocationCallbacks*a,VkSemaphore*out){(void)a;assert(d&&i);if(++sem_create_calls==fail_sem_at)return VK_ERROR_OUT_OF_HOST_MEMORY;*out=H(VkSemaphore,++next_handle);return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroySemaphore(VkDevice d,VkSemaphore sem,const VkAllocationCallbacks*a){(void)a;assert(d&&sem&&!sem_destroyed[(uintptr_t)sem]&&wait_seq);must_retire();++sem_destroyed[(uintptr_t)sem];++sem_destroy_calls;++destructions;event('S',(uintptr_t)sem);semaphore_state[(uintptr_t)sem]=0;}

MAKE_FN(vkCreateSampler,VkSamplerCreateInfo,VkSampler)
VKAPI_ATTR VkResult VKAPI_CALL vkAllocateCommandBuffers(VkDevice d,const VkCommandBufferAllocateInfo*i,VkCommandBuffer*out){assert(d&&i->commandBufferCount==1);*out=H(VkCommandBuffer,++next_handle);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkBeginCommandBuffer(VkCommandBuffer c,const VkCommandBufferBeginInfo*i){assert(c&&i->flags==VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT);return fail_begin?VK_ERROR_OUT_OF_HOST_MEMORY:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkEndCommandBuffer(VkCommandBuffer c){assert(c);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkQueueSubmit(VkQueue q,uint32_t n,const VkSubmitInfo*i,VkFence f){assert(q&&n==1&&f&&i->commandBufferCount>=1);++submit_count;if(fault==30)return VK_ERROR_DEVICE_LOST;
 if(i->waitSemaphoreCount){unsigned image=acquire_image[(uintptr_t)*i->pWaitSemaphores];assert(image&&image<=native_present_count);acquire_image[(uintptr_t)*i->pWaitSemaphores]=0;semaphore_state[(uintptr_t)native_present_wait[image-1]]=0;}
 if(i->signalSemaphoreCount){uintptr_t sem=(uintptr_t)*i->pSignalSemaphores;assert(!semaphore_state[sem]&&"RED per-frame semaphore signaled while prior WSI present pending");semaphore_state[sem]=1;}return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkWaitForFences(VkDevice d,uint32_t n,const VkFence*f,VkBool32 all,uint64_t timeout){assert(d&&n==1&&*f&&all&&timeout==UINT64_MAX);uintptr_t id=(uintptr_t)*f;assert(id<8192&&mf[id].created&&!mf[id].destroyed);if(mf[id].kind){++present_waits;assert(mf[id].pending==1&&"must not wait a new/unassociated/unknown PRESENT fence");if(present_waits==fail_present_wait_at){event('w',id);return present_wait_error;}mf[id].pending=0;mf[id].signaled=1;mf[id].waited=1;semaphore_state[mf[id].semaphore]=0;event('W',id);}else{mf[id].signaled=1;event('F',id);}return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkResetFences(VkDevice d,uint32_t n,const VkFence*f){assert(d&&n==1&&*f);uintptr_t id=(uintptr_t)*f;assert(id<8192&&mf[id].created&&!mf[id].destroyed);if(mf[id].kind){++present_resets;assert(mf[id].signaled&&mf[id].waited&&!mf[id].pending);if(present_resets==fail_present_reset_at){event('r',id);return VK_ERROR_DEVICE_LOST;}event('R',id);}mf[id].signaled=0;return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkResetCommandPool(VkDevice d,VkCommandPool p,VkCommandPoolResetFlags flags){assert(d&&p&&!flags);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkResetDescriptorPool(VkDevice d,VkDescriptorPool p,VkDescriptorPoolResetFlags flags){assert(d&&p&&!flags);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkDeviceWaitIdle(VkDevice d){assert(d);wait_seq=++seq;++idle_calls;event('I',0);/* Never completes model PRESENT fences. */return wait_fault?VK_ERROR_DEVICE_LOST:VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyImageView(VkDevice d,VkImageView v,const VkAllocationCallbacks*a){(void)a;assert(d);if(!v)return;must_retire();++view_destroys;++destructions;event('V',(uintptr_t)v);destroy_seq=++seq;assert(wait_seq&&destroy_seq>wait_seq);}
VKAPI_ATTR void VKAPI_CALL vkDestroyFramebuffer(VkDevice d,VkFramebuffer fb,const VkAllocationCallbacks*a){(void)a;assert(d&&fb);}
VKAPI_ATTR void VKAPI_CALL vkDestroySwapchainKHR(VkDevice d,VkSwapchainKHR c,const VkAllocationCallbacks*a){(void)a;assert(d&&c);must_retire();++chain_destroyed;++destructions;event('C',(uintptr_t)c);}
VKAPI_ATTR void VKAPI_CALL vkDestroySurfaceKHR(VkInstance i,VkSurfaceKHR s,const VkAllocationCallbacks*a){(void)a;assert(i&&s&&(uintptr_t)s<1024);assert(!surface_destroyed[(uintptr_t)s]);if(s==S.surface)must_retire();++surface_destroyed[(uintptr_t)s];++destructions;event('U',(uintptr_t)s);}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPhysicalDeviceSurfaceSupportKHR(VkPhysicalDevice p,uint32_t q,VkSurfaceKHR s,VkBool32*ok){assert(p&&!q&&s);*ok=fault==1?VK_FALSE:VK_TRUE;return fault==2?VK_ERROR_SURFACE_LOST_KHR:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPhysicalDeviceSurfaceCapabilitiesKHR(VkPhysicalDevice p,VkSurfaceKHR s,VkSurfaceCapabilitiesKHR*c){assert(p&&s);if(fault==3)return VK_ERROR_SURFACE_LOST_KHR;*c=(VkSurfaceCapabilitiesKHR){.minImageCount=2,.maxImageCount=3,.currentExtent={cap_variable?UINT32_MAX:cap_zero?0:640,cap_variable?UINT32_MAX:cap_zero?0:480},.minImageExtent={16,16},.maxImageExtent={2048,2048},.supportedUsageFlags=fault==14?0:VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT,.supportedCompositeAlpha=VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR};return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPhysicalDeviceSurfaceFormatsKHR(VkPhysicalDevice p,VkSurfaceKHR s,uint32_t*n,VkSurfaceFormatKHR*f){assert(p&&s);uint32_t cap=f?*n:0;*n=fault==4?0:(f&&fault==60)?cap+1:1;if(f&&cap)*f=(VkSurfaceFormatKHR){VK_FORMAT_R8G8B8A8_UNORM,VK_COLOR_SPACE_SRGB_NONLINEAR_KHR};return fault==5?VK_ERROR_SURFACE_LOST_KHR:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateSwapchainKHR(VkDevice d,const VkSwapchainCreateInfoKHR*i,const VkAllocationCallbacks*a,VkSwapchainKHR*c){(void)a;assert(d&&i->surface&&i->imageExtent.width&&i->imageExtent.height);if(fault==6)return VK_ERROR_INITIALIZATION_FAILED;*c=H(VkSwapchainKHR,++next_handle);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkGetSwapchainImagesKHR(VkDevice d,VkSwapchainKHR c,uint32_t*n,VkImage*i){assert(d&&c);uint32_t cap=i?*n:0;*n=fault==7?0:(i&&fault==61)?cap+1:swap_n;if(i)for(uint32_t k=0;k<*n&&k<cap;++k)i[k]=H(VkImage,++next_handle);return fault==8?VK_ERROR_SURFACE_LOST_KHR:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkAcquireNextImageKHR(VkDevice d,VkSwapchainKHR c,uint64_t timeout,VkSemaphore sem,VkFence f,uint32_t*i){assert(d&&c&&timeout==UINT64_MAX&&sem&&!f);++acquire_count;*i=next_acquire;assert(next_acquire<swap_n);if(acquire_result==VK_SUCCESS||acquire_result==VK_SUBOPTIMAL_KHR)acquire_image[(uintptr_t)sem]=next_acquire+1;return (VkResult)acquire_result;}
VKAPI_ATTR VkResult VKAPI_CALL vkQueuePresentKHR(VkQueue q,const VkPresentInfoKHR*i){assert(q&&i->waitSemaphoreCount==1&&i->swapchainCount==1&&*i->pSwapchains==S.chain);uintptr_t sem=(uintptr_t)*i->pWaitSemaphores;assert(semaphore_state[sem]==1);++present_count;
 if(model_strict){assert(i->pNext&&i->pResults&&*i->pResults==missing_result);const VkSwapchainPresentFenceInfoEXT*p=i->pNext;assert(p->sType==VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_FENCE_INFO_EXT&&p->swapchainCount==1&&!p->pNext);uintptr_t id=(uintptr_t)*p->pFences;assert(id<8192&&mf[id].created&&mf[id].kind&&!mf[id].destroyed&&!mf[id].pending&&!mf[id].signaled);if(!per_result_missing)*i->pResults=per_result_override?model_per_result:(VkResult)present_result;
 if(present_result==VK_ERROR_OUT_OF_HOST_MEMORY||present_result==VK_ERROR_OUT_OF_DEVICE_MEMORY){event('o',id);return (VkResult)present_result;}
 mf[id].pending=(present_result==VK_ERROR_DEVICE_LOST)?2:1;mf[id].semaphore=sem;event('P',id);
 }else{assert(!i->pNext&&!i->pResults);event('p',sem);}semaphore_state[sem]=2;return (VkResult)present_result;}
VKAPI_ATTR void VKAPI_CALL vkCmdPipelineBarrier(VkCommandBuffer c,VkPipelineStageFlags s,VkPipelineStageFlags d,VkDependencyFlags flags,uint32_t nm,const VkMemoryBarrier*m,uint32_t nb,const VkBufferMemoryBarrier*b,uint32_t ni,const VkImageMemoryBarrier*i){(void)m;(void)b;assert(c&&s&&d&&!flags&&!nm&&!nb&&ni==1&&i->image);}
VKAPI_ATTR void VKAPI_CALL vkCmdCopyBufferToImage(VkCommandBuffer c,VkBuffer b,VkImage i,VkImageLayout l,uint32_t n,const VkBufferImageCopy*r){assert(c&&b&&i&&l==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL&&n==1&&r->imageExtent.width==1&&r->imageExtent.height==1);vbufmem*stage=NULL;for(size_t k=0;k<F->up.stage.n;++k)if(F->up.stage.b[k]->buf==b)stage=F->up.stage.b[k];assert(stage&&r->bufferOffset+4<=stage->size);assert(!memcmp(stage->map+r->bufferOffset,"\0\0\0\377",4));++copy_count;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateGraphicsPipelines(VkDevice d,VkPipelineCache cache,uint32_t n,const VkGraphicsPipelineCreateInfo*i,const VkAllocationCallbacks*a,VkPipeline*out){(void)a;assert(d&&cache&&n==1&&i);int lock=pthread_mutex_trylock(&D.plock);assert(lock==EBUSY);*out=H(VkPipeline,++next_handle);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateRenderPass(VkDevice d,const VkRenderPassCreateInfo*i,const VkAllocationCallbacks*a,VkRenderPass*out){(void)a;assert(d&&i&&i->subpassCount==1);++render_create_calls;if(render_fault){render_initial_null=*out==VK_NULL_HANDLE;if(render_fault==52)*out=H(VkRenderPass,999);return render_fault==51?VK_SUCCESS:VK_ERROR_OUT_OF_HOST_MEMORY;}*out=H(VkRenderPass,++next_handle);return VK_SUCCESS;}
#define abort guarded_abort
VKAPI_ATTR VkResult VKAPI_CALL vkMergePipelineCaches(VkDevice d,VkPipelineCache c,uint32_t n,const VkPipelineCache*p){assert(d&&c&&n==1&&*p);assert(pthread_mutex_trylock(&D.plock)==EBUSY);return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyPipelineCache(VkDevice d,VkPipelineCache c,const VkAllocationCallbacks*a){(void)a;assert(d&&c);}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPipelineCacheData(VkDevice d,VkPipelineCache c,size_t*n,void*p){assert(d&&c);assert(pthread_mutex_trylock(&D.plock)==EBUSY);*n=4;if(p)memcpy(p,"R7PC",4);return VK_SUCCESS;}

VKAPI_ATTR VkResult VKAPI_CALL vkEnumerateInstanceExtensionProperties(const char*layer,uint32_t*n,VkExtensionProperties*p){assert(!layer);++instance_enum_calls;const char*names[5];unsigned count=0;if(inst_ads&I_SURFACE)names[count++]="VK_KHR_surface";if(inst_ads&I_PROPS)names[count++]="VK_KHR_get_physical_device_properties2";if(inst_ads&I_CAPS)names[count++]="VK_KHR_get_surface_capabilities2";if(inst_ads&I_EXT)names[count++]="VK_EXT_surface_maintenance1";if(inst_ads&I_KHR)names[count++]="VK_KHR_surface_maintenance1";uint32_t cap=p?*n:0;if(p)for(uint32_t i=0;i<count&&i<cap;++i)strcpy(p[i].extensionName,names[i]);*n=inst_enum_fault==3?0:(p&&inst_enum_fault==4)?cap+1:count;if((!p&&inst_enum_fault==1)||(p&&inst_enum_fault==2))return VK_ERROR_INITIALIZATION_FAILED;if(p&&inst_enum_fault==5)return VK_INCOMPLETE;return VK_SUCCESS;}
static void VKAPI_CALL model_features2(VkPhysicalDevice p,VkPhysicalDeviceFeatures2*f){assert(p&&f&&f->sType==VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2_KHR&&f->pNext);assert(name_in(enabled_instance,enabled_instance_count,"VK_KHR_get_physical_device_properties2"));VkPhysicalDeviceSwapchainMaintenance1FeaturesEXT*m=f->pNext;assert(m->sType==VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SWAPCHAIN_MAINTENANCE_1_FEATURES_EXT&&!m->pNext&&!m->swapchainMaintenance1);m->swapchainMaintenance1=feature_value;++features_calls;}
VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(VkInstance instance,const char*name){assert(instance&&!strcmp(name,"vkGetPhysicalDeviceFeatures2KHR"));assert(name_in(enabled_instance,enabled_instance_count,"VK_KHR_get_physical_device_properties2"));++proc_calls;return missing_proc?NULL:(PFN_vkVoidFunction)model_features2;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateImageView(VkDevice d,const VkImageViewCreateInfo*i,const VkAllocationCallbacks*a,VkImageView*out){(void)a;assert(d&&i&&i->image&&*out==VK_NULL_HANDLE);++view_try_calls;if(view_try_calls==fail_view_at){if(view_failure_mode==2)return VK_SUCCESS;if(view_failure_mode==3)*out=H(VkImageView,8001);return VK_ERROR_OUT_OF_DEVICE_MEMORY;}*out=H(VkImageView,++next_handle);return VK_SUCCESS;}
#define calloc model_calloc

#pragma GCC poison ctx cur_up main_ctx loader_ctx cur_vao GLenum GLuint GLfloat GLboolean GL_EXTENSIONS glGetString glBindFramebuffer vkgl_create vkgl_present vkgl_surface vkgl_release_surface

'''
production_frames=int(re.search(r'^#define FRAMES (\d+)$',CORE,re.M).group(1)); assert production_frames==2
prefix=prefix.replace('#define FRAMES 2','#define FRAMES '+str(production_frames))
support=fun(INPUTS['src/native_vk.inc'].decode(),'static int native_reject(void)')+fun(INPUTS['src/native_vk.inc'].decode(),'uint64_t cinder_vk_error_epoch(void)')
support+='static __thread cinder_vk_upload_stream native_upload_stream;\n'
support+=fun(INPUTS['src/native_vk_resources.inc'].decode(),'int cinder_vk_upload_stream_set(')+fun(INPUTS['src/native_vk_resources.inc'].decode(),'cinder_vk_upload_stream cinder_vk_upload_stream_get(')
support+=INPUTS['src/native_vk_upload.inc'].decode()
a=CORE.index('static const VkFormat VFMT[]'); b=CORE.index('/* a vertex attribute',a);support+=CORE[a:b]
prototypes='\n'.join(v[:v.index('{')].strip()+';' for v in shared.values())+'\n'

cases = r'''
static void guarded_abort(void){
 if(abort_expected){int ok=destructions==abort_destructions&&native_present_fences&&abort_image<native_present_fence_count;
  native_present_fence_state state=native_present_fences[abort_image].state;
  if(abort_expected==1)ok=ok&&state==NATIVE_PRESENT_PENDING&&mf[abort_fence].pending==1&&present_waits>abort_waits&&present_resets==abort_resets;
  else if(abort_expected==2)ok=ok&&state==NATIVE_PRESENT_COMPLETE&&!mf[abort_fence].pending&&present_waits==abort_waits+1&&present_resets==abort_resets+1;
  else if(abort_expected==3)ok=ok&&state==NATIVE_PRESENT_IDLE&&!mf[abort_fence].pending&&present_waits==abort_waits&&present_resets==abort_resets;
  else if(abort_expected==4)ok=ok&&state==NATIVE_PRESENT_UNKNOWN&&mf[abort_fence].pending&&present_waits==abort_waits&&present_resets==abort_resets;
  else if(abort_expected==5)ok=ok&&state==NATIVE_PRESENT_PENDING&&!native_present_fences[abort_image].fence&&mf[abort_fence].pending&&present_waits==abort_waits;
  else ok=0;
  _exit(ok?77:78);
 }
 raise(SIGABRT);_exit(79);
}
static void arm(unsigned expect,unsigned image){abort_expected=expect;abort_image=image;abort_fence=(uintptr_t)native_present_fences[image].fence;abort_destructions=destructions;abort_waits=present_waits;abort_resets=present_resets;}
static int surface(unsigned id){phase_present_pool=1;int result=cinder_vk_platform_surface(H(VkSurfaceKHR,id),640,480);phase_present_pool=0;return result;}
static void no_surface(void){assert(!S.n&&!S.img&&!S.chain&&!S.surface&&!S.w&&!S.h&&!native_present_wait&&!native_present_count&&!native_present_fences&&!native_present_fence_count&&!native_frame_claimed);assert(cinder_vk_platform_retirement_mode()==CINDER_VK_RETIREMENT_UNAVAILABLE);}
static void one_present(unsigned image,VkResult result){next_acquire=image;acquire_result=VK_SUCCESS;present_result=result;assert(cinder_vk_platform_frame_ready());unsigned ac=acquire_count,p=present_count;assert(cinder_vk_platform_frame_ready()&&acquire_count==ac);int r=cinder_vk_platform_present();assert(present_count==p+1&&!native_frame_claimed&&!S.acquired);assert((result==VK_SUCCESS&&r==0)||(result==VK_SUBOPTIMAL_KHR&&r==1)||(result==VK_ERROR_OUT_OF_DATE_KHR&&r==1)||(result==VK_ERROR_SURFACE_LOST_KHR&&r==-1));}
static void release_order(unsigned from,unsigned expected_waits){if(!from)from=event_count;unsigned old_wait=present_waits;cinder_vk_platform_release_surface();assert(present_waits==old_wait+expected_waits);unsigned last_wait=0,first_destroy=UINT_MAX;for(unsigned i=from;i<event_count;++i){if(events[i].op=='W')last_wait=i+1;if(strchr("VCSUZB",events[i].op)&&first_destroy==UINT_MAX)first_destroy=i+1;}if(expected_waits)assert(last_wait&&first_destroy>last_wait);no_surface();}
static void lifecycle(cinder_vk_retirement_mode expected){
 swap_n=3;unsigned before=event_count,created=present_fence_creates,waits=present_waits,resets=present_resets;assert(!surface(100));assert(cinder_vk_platform_retirement_mode()==expected);assert(!view_new_calls&&view_try_calls>=3);
 if(model_strict){assert(present_fence_creates==created+3&&native_present_fence_count==3);for(unsigned i=0;i<3;++i){assert(native_present_fences[i].fence&&native_present_fences[i].state==NATIVE_PRESENT_IDLE);assert(!mf[(uintptr_t)native_present_fences[i].fence].signaled);}assert(present_waits==waits&&present_resets==resets);}
 else assert(present_fence_creates==created&&!native_present_fences&&!native_present_fence_count);
 unsigned idle=idle_calls;one_present(0,VK_SUCCESS);one_present(1,VK_SUCCESS);one_present(2,VK_SUCCESS);assert(idle_calls==idle);if(model_strict)assert(model_pending()==3&&present_waits==waits&&"submission-fence waits did not complete PRESENT ownership");
 release_order(before,model_strict?3:0);
 if(!model_strict){puts("PASS actual unsupported fallback: per-image semaphores, no PRESENT fences/waits or explicit resource-fence proof; no per-frame idle");return;}
 assert(!surface(101));one_present(0,VK_SUCCESS);waits=present_waits;resets=present_resets;idle=idle_calls;next_acquire=0;assert(cinder_vk_platform_frame_ready());assert(present_waits==waits+1&&present_resets==resets+1&&idle_calls==idle&&native_present_fences[0].state==NATIVE_PRESENT_IDLE);unsigned ac=acquire_count;assert(cinder_vk_platform_frame_ready()&&acquire_count==ac&&present_waits==waits+1&&present_resets==resets+1);assert(!cinder_vk_platform_present());release_order(0,1);
 const VkResult results[]={VK_SUBOPTIMAL_KHR,VK_ERROR_OUT_OF_DATE_KHR,VK_ERROR_SURFACE_LOST_KHR};
 for(unsigned i=0;i<3;++i){assert(!surface(110+i));one_present(1,results[i]);assert(cinder_vk_platform_surface_stale()&&native_present_fences[1].state==NATIVE_PRESENT_PENDING&&model_pending()==1);before=event_count;release_order(before,1);}
 assert(!surface(114));acquire_result=VK_SUBOPTIMAL_KHR;present_result=VK_SUCCESS;next_acquire=0;assert(cinder_vk_platform_frame_ready()&&native_frame_claimed);assert(cinder_vk_platform_present()==1&&native_present_fences[0].state==NATIVE_PRESENT_PENDING&&cinder_vk_platform_surface_stale());release_order(0,1);acquire_result=VK_SUCCESS;
 for(unsigned i=0;i<2;++i){assert(!surface(120+i));acquire_result=i?VK_ERROR_SURFACE_LOST_KHR:VK_ERROR_OUT_OF_DATE_KHR;waits=present_waits;assert(!cinder_vk_platform_frame_ready()&&!native_frame_claimed&&!model_pending());release_order(0,0);assert(present_waits==waits);}acquire_result=VK_SUCCESS;present_result=VK_SUCCESS;
 assert(!surface(130));one_present(0,VK_SUCCESS);waits=present_waits;unsigned destroys=destructions;assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));cinder_vk_platform_release_surface();assert(cinder_vk_platform_retirement_mode()==CINDER_VK_RETIREMENT_UNAVAILABLE&&present_waits==waits&&destructions==destroys&&model_pending()==1);assert(cinder_vk_platform_surface(H(VkSurfaceKHR,131),640,480)==-1&&surface_destroyed[131]&&model_pending()==1&&S.surface==H(VkSurfaceKHR,130));assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_FRAME));next_acquire=1;assert(cinder_vk_platform_frame_ready());VkDevice dev=D.dev;D.dev=VK_NULL_HANDLE;assert(!cinder_vk_platform_frame_ready()&&cinder_vk_platform_present()==-1&&native_frame_claimed&&cinder_vk_platform_retirement_mode()==CINDER_VK_RETIREMENT_UNAVAILABLE);cinder_vk_platform_release_surface();assert(S.surface==H(VkSurfaceKHR,130)&&model_pending()==1);D.dev=dev;typeof(F) frame=F;F=NULL;assert(cinder_vk_platform_present()==-1&&native_frame_claimed&&cinder_vk_platform_retirement_mode()==CINDER_VK_RETIREMENT_UNAVAILABLE);F=frame;assert(cinder_vk_platform_surface(S.surface,640,480)==-1&&native_frame_claimed&&!surface_destroyed[130]);assert(!cinder_vk_platform_present()&&model_pending()==2);release_order(0,2);
 puts("PASS actual strict frame/WSI: image-owned pNext fences, submit fence not authority, pending wait/reset before same-image reuse, OUTDATED/LOST enqueued, no-pending acquire failure, role/device/F/claim/alias guards, wait-all before every WSI destruction");
}
static void construction_failures(void){
 for(unsigned mode=1;mode<=3;++mode)for(unsigned n=1;n<=3;++n){unsigned created=present_fence_creates,destroyed=present_fence_destroys,sems=sem_create_calls,sem_destroyed_before=sem_destroy_calls,waits=present_waits,resets=present_resets;fail_present_fence_at=created+n;fail_present_fence_mode=mode;unsigned id=200+mode*10+n;assert(surface(id)==-1&&surface_destroyed[id]);assert(present_fence_creates==created+n&&present_fence_destroys==destroyed+n-1&&sem_create_calls==sems+3&&sem_destroy_calls==sem_destroyed_before+3&&present_waits==waits&&present_resets==resets);no_surface();}fail_present_fence_at=fail_present_fence_mode=0;
 pool_alloc_fail=1;unsigned waits=present_waits,fences=present_fence_creates;assert(surface(250)==-1&&!pool_alloc_fail&&surface_destroyed[250]&&present_fence_creates==fences&&present_waits==waits);no_surface();
 for(unsigned n=1;n<=3;++n){unsigned sems=sem_create_calls,sd=sem_destroy_calls;waits=present_waits;fences=present_fence_creates;fail_sem_at=sems+n;assert(surface(260+n)==-1&&surface_destroyed[260+n]&&sem_destroy_calls==sd+n-1&&present_fence_creates==fences&&present_waits==waits);no_surface();}fail_sem_at=0;
 for(unsigned mode=1;mode<=3;++mode)for(unsigned n=1;n<=3;++n){fail_view_at=view_try_calls+n;view_failure_mode=mode;unsigned views=view_destroys;waits=present_waits;fences=present_fence_creates;unsigned id=300+mode*10+n;assert(surface(id)==-1&&surface_destroyed[id]&&view_destroys==views+n-1&&present_fence_creates==fences&&present_waits==waits&&!view_new_calls);no_surface();}fail_view_at=view_failure_mode=0;
 for(unsigned i=0;i<2;++i){fault=60+(int)i;waits=present_waits;fences=present_fence_creates;assert(surface(350+i)==-1&&surface_destroyed[350+i]&&present_waits==waits&&present_fence_creates==fences);no_surface();}fault=0;
 fail_image_at=image_calls+2;assert(surface(360)==-1&&surface_destroyed[360]);fail_image_at=0;no_surface();
 assert(!surface(370));waits=present_waits;release_order(0,0);assert(present_waits==waits);
 phase_present_pool=1;fences=present_fence_creates;assert(!cinder_vk_platform_surface(VK_NULL_HANDLE,64,32));phase_present_pool=0;assert(cinder_vk_platform_retirement_mode()==CINDER_VK_RETIREMENT_HEADLESS&&present_fence_creates==fences&&!native_present_fences&&!native_present_wait);assert(cinder_vk_platform_frame_ready());unsigned presents=present_count;assert(!cinder_vk_platform_present()&&present_count==presents);release_order(0,0);
 puts("PASS actual partial constructor rollback: each of 3 fence/semaphore failures, fence successNULL/errornonnull, checked actual view_try 1..3 error/NULL/nonNULL with legacy view_new unused, metadata allocation/count growth, no waits/resets of new unsignaled fences, headless allocates none");
}
static void fatal_failures(void){fflush(NULL);for(unsigned scenario=0;scenario<9;++scenario){pid_t pid=fork();assert(pid>=0);if(!pid){assert(!surface(600+scenario));present_result=VK_SUCCESS;acquire_result=VK_SUCCESS;if(scenario<=2||scenario==8){one_present(0,VK_SUCCESS);if(scenario==0){one_present(1,VK_SUCCESS);one_present(2,VK_SUCCESS);arm(1,1);fail_present_wait_at=present_waits+2;cinder_vk_platform_release_surface();}else if(scenario==1){arm(1,0);present_wait_error=VK_ERROR_DEVICE_LOST;fail_present_wait_at=present_waits+1;cinder_vk_platform_release_surface();}else if(scenario==2){arm(2,0);fail_present_reset_at=present_resets+1;next_acquire=0;cinder_vk_platform_frame_ready();}else{arm(5,0);native_present_fences[0].fence=VK_NULL_HANDLE;cinder_vk_platform_release_surface();}}else{next_acquire=0;assert(cinder_vk_platform_frame_ready());if(scenario==3||scenario==4){arm(3,0);present_result=scenario==3?VK_ERROR_OUT_OF_HOST_MEMORY:VK_ERROR_OUT_OF_DEVICE_MEMORY;}else{arm(4,0);if(scenario==5)present_result=VK_ERROR_DEVICE_LOST;else if(scenario==6)per_result_missing=1;else per_result_override=1,model_per_result=VK_SUBOPTIMAL_KHR;}cinder_vk_platform_present();}_exit(80);}int status;assert(waitpid(pid,&status,0)==pid&&WIFEXITED(status)&&WEXITSTATUS(status)==77);}puts("PASS actual fatal ownership boundaries: PRESENT wait timeout/deviceLost free-none, completed wait then reset failure stays known-complete, OOM unassociated, deviceLost/missing/inconsistent pResults unknown, pending NULL fence never waited/freed; nine child exit77 witnesses");}
static unsigned compat_initializer_calls;
static const char*compat_initializer(void){++compat_initializer_calls;return "compat-mock";}
int main(int argc,char**argv){assert(argc==2);const char*which=argv[1];cinder_vk_retirement_mode expected=CINDER_VK_RETIREMENT_EXT_PRESENT_FENCE;int failure=0,headless=0,dedup=0;
 if(!strcmp(which,"ext"))inst_ads=15,dev_ads=3;
 else if(!strcmp(which,"khr"))inst_ads=23,dev_ads=5,expected=CINDER_VK_RETIREMENT_KHR_PRESENT_FENCE;
 else if(!strcmp(which,"both-ext"))dev_ads=3;
 else if(!strcmp(which,"both-khr"))dev_ads=5,expected=CINDER_VK_RETIREMENT_KHR_PRESENT_FENCE;
 else if(!strcmp(which,"both")){}
 else if(!strcmp(which,"mismatch-ext"))inst_ads=15,dev_ads=5,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"mismatch-khr"))inst_ads=23,dev_ads=3,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"no-maint-instance"))inst_ads=7,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"no-maint-device"))dev_ads=1,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"no-props2"))inst_ads&=~I_PROPS,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"physical11-no-props2"))inst_ads&=~I_PROPS,physical_api=VK_API_VERSION_1_1,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"no-caps2"))inst_ads&=~I_CAPS,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"missing-proc"))missing_proc=1,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"feature-false"))feature_value=0,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"feature-noncanonical"))feature_value=2,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strncmp(which,"instance-enum-",14))inst_enum_fault=(unsigned)atoi(which+14),expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strncmp(which,"device-enum-",12))dev_enum_fault=(unsigned)atoi(which+12),failure=1;
 else if(!strcmp(which,"deduplicated"))dedup=1;
 else if(!strcmp(which,"no-surface-request"))headless=2,expected=CINDER_VK_RETIREMENT_IDLE_FALLBACK;
 else if(!strcmp(which,"instance-success-null"))optional_instance_failure=2,failure=1;
 else if(!strcmp(which,"device-success-null"))optional_device_failure=2,failure=1;
 else if(!strcmp(which,"instance-create-failure"))optional_instance_failure=1,failure=1;
 else if(!strcmp(which,"device-create-failure"))optional_device_failure=1,failure=1;
 else if(!strcmp(which,"headless"))inst_ads=15,dev_ads=3,headless=1;
 else if(!strcmp(which,"compat")){const char*ext[]={"VK_KHR_surface","VK_KHR_android_surface"};assert(!backend_create(ext,2,compat_initializer));assert(!platform_native_profile&&!instance_enum_calls&&!proc_calls&&!features_calls&&!model_device_feature&&enabled_instance_count==2&&enabled_device_count==1&&compat_initializer_calls==1&&!native_present_fences);puts("PASS actual profile0 backend create: optional discovery/query/feature/fences bypassed, base instance/device contract preserved");return 0;}
 else assert(0&&"unknown test variant");
 const char*ext[]={"VK_KHR_surface","VK_KHR_android_surface","VK_KHR_get_physical_device_properties2","VK_KHR_get_surface_capabilities2","VK_EXT_surface_maintenance1","VK_KHR_surface_maintenance1"};int ext_count=headless==2?0:dedup?6:2;assert(cinder_vk_platform_retirement_mode()==CINDER_VK_RETIREMENT_UNAVAILABLE);int created=cinder_vk_platform_create(ext_count?ext:NULL,ext_count);assert(instance_create_calls==1);
 if(failure){assert(created==-1&&!platform_created&&!D.inst&&!D.dev&&!copy_count&&cinder_vk_platform_retirement_mode()==CINDER_VK_RETIREMENT_UNAVAILABLE);assert(instance_destroyed==(unsigned)!optional_instance_failure);unsigned ic=instance_create_calls,dc=device_create_calls;assert(cinder_vk_platform_create(ext,2)==-1&&instance_create_calls==ic&&device_create_calls==dc);puts("PASS actual advertised-create/enumeration failure: unavailable, exact instance cleanup, one-shot NO retry, no device/feature/fallback publication");return 0;}
 assert(!created&&platform_created&&platform_native_profile&&copy_count==7&&submit_count==1&&!F->up.open&&!F->up.stage.used&&cinder_vk_platform_retirement_mode()==CINDER_VK_RETIREMENT_UNAVAILABLE);assert(native_retirement.enabled_device==expected&&model_device_feature==(expected!=CINDER_VK_RETIREMENT_IDLE_FALLBACK)&&enabled_device_count==(uint32_t)(model_device_feature?2:headless==2?0:1));if(dedup)assert(enabled_instance_count==6);if(headless==2)assert(!instance_enum_calls&&!proc_calls&&!features_calls&&!enabled_instance_count);
 if((inst_ads&I_PROPS)==0||inst_enum_fault||!(inst_ads&(I_EXT|I_KHR))||dev_ads==D_SWAP)assert(!proc_calls&&!features_calls);
 if(missing_proc)assert(proc_calls==1&&!features_calls);if(feature_value!=VK_TRUE)assert(proc_calls==1&&features_calls==1);
 if(headless!=2&&!inst_enum_fault&&(inst_ads&(I_PROPS|I_CAPS|I_SURFACE))==(I_PROPS|I_CAPS|I_SURFACE)){if(inst_ads&I_EXT)assert(name_in(enabled_instance,enabled_instance_count,"VK_EXT_surface_maintenance1"));if(inst_ads&I_KHR)assert(name_in(enabled_instance,enabled_instance_count,"VK_KHR_surface_maintenance1"));}
 if(headless){unsigned fences=present_fence_creates;phase_present_pool=1;assert(!cinder_vk_platform_surface(VK_NULL_HANDLE,64,32));phase_present_pool=0;assert(cinder_vk_platform_retirement_mode()==CINDER_VK_RETIREMENT_HEADLESS&&present_fence_creates==fences&&!native_present_fences&&!native_present_wait);assert(cinder_vk_platform_frame_ready()&&!cinder_vk_platform_present()&&!present_count);release_order(0,0);puts("PASS actual negotiated device headless surface: no WSI fence/semaphore allocation or presentation");}
 else{lifecycle(expected);if(!strcmp(which,"ext")||!strcmp(which,"khr")){construction_failures();fatal_failures();}}
 printf("PASS actual negotiation variant %s mode=%d API1.0 exact enabled instance/device extensions and feature pNext\n",which,(int)expected);return 0;
}
'''

ndk = Path(os.environ.get('CINDER_NDK_BIN', '/Users/arx/Library/Android/sdk/ndk/28.0.13004108/toolchains/llvm/prebuilt/darwin-x86_64/bin')).resolve()
header_root = ndk.parent / 'sysroot/usr/include/vulkan'
assert header_root.is_dir(), 'set CINDER_NDK_BIN to installed NDK toolchain bin'
rows=[]
def command(args,label,cwd=None):
    p=subprocess.run([str(a) for a in args],capture_output=True,text=True,cwd=cwd)
    (OUT/(label+'.log')).write_text(p.stdout+p.stderr)
    if p.returncode: print(p.stdout+p.stderr,flush=True)
    assert p.returncode==0,(label,p.returncode)
    return p.stdout
with tempfile.TemporaryDirectory(prefix='present-fence-',dir=OUT) as tmp:
    work=Path(tmp);shutil.copytree(header_root,work/'include/vulkan');shutil.copytree(header_root.parent/'vk_video',work/'include/vk_video')
    c=OUT/'actual-present-fence.c';c.write_text(prefix+'\n'+prototypes+support+'\n'+PRESENT+'\n'+'\n'.join(shared.values())+'\n'+PLATFORM+cases)
    exe=OUT/'actual-present-fence'
    command([os.environ.get('CC','clang'),'-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter','-Wno-missing-field-initializers','-fsanitize=undefined','-fno-sanitize-recover=all','-g','-pthread','-I'+str(work/'include'),'-I'+str(ROOT/'src'),c,'-o',exe],'compile-actual')
    variants=['ext','khr','both-ext','both-khr','both','mismatch-ext','mismatch-khr','no-maint-instance','no-maint-device','no-props2','physical11-no-props2','no-caps2','missing-proc','feature-false','feature-noncanonical']+[f'instance-enum-{n}' for n in (1,2,3,4,5)]+[f'device-enum-{n}' for n in (1,2,3,4)]+['instance-create-failure','device-create-failure','instance-success-null','device-success-null','deduplicated','no-surface-request','headless','compat']
    for variant in variants:
        stdout=command([exe,variant],'actual-'+variant,cwd=work);print(stdout,end='');rows.append({'variant':variant,'exit_code':0,'stdout':stdout})
    cc=ndk/'aarch64-linux-android28-clang'; nm=ndk/'llvm-nm'
    common=['-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter','-Wno-missing-field-initializers','-O2','-fPIC','-DRC_FPT=double','-I'+str(ROOT/'src')]
    modes=[('gles',['-DWMMT_EGL']),('compat',['-DWMMT_EGL','-DWMMT_VK']),('compat-no-egl',['-DWMMT_VK']),('native',['-DWMMT_EGL','-DWMMT_VK','-DWMMT_NATIVE_VK'])]
    for name,defines in modes:
        command([cc,*common,*defines,'-c',ROOT/'src/vkgl.c','-o',OUT/(name+'-core.o')],name+'-core-compile')
        current=OUT/(name+'-android.o')
        p=subprocess.run([str(cc),*common,*defines,'-x','c','-c','-','-o',str(current)],input=INPUTS['src/main_android.c'],capture_output=True)
        (OUT/(name+'-android-compile.log')).write_bytes(p.stdout+p.stderr);assert p.returncode==0,(name,p.stderr.decode())
        if name!='native':
            old=OUT/(name+'-baseline.o');p=subprocess.run([str(cc),*common,*defines,'-x','c','-c','-','-o',str(old)],input=BASE_BYTES,capture_output=True);(OUT/(name+'-baseline-compile.log')).write_bytes(p.stdout+p.stderr);assert p.returncode==0,p.stderr.decode();assert old.read_bytes()==current.read_bytes(),name
            tokens=[]
            for text in (BASE_BYTES,INPUTS['src/main_android.c']):
                p=subprocess.run([str(cc),*common,*defines,'-E','-P','-x','c','-'],input=text,capture_output=True);assert p.returncode==0,p.stderr.decode();tokens.append(p.stdout)
            assert tokens[0]==tokens[1],name;rows.append({'legacy_android':name,'full_tokens_equal':True,'full_O2_objects_equal':True})
        else:
            imports=command([nm,'--undefined-only',current],'native-android-imports');assert not re.search(r'\b_?(?:gl[A-Z]\w*|vkgl_\w*|egl\w*|.*(?:GetProcAddress|ExtensionString).*)\b',imports),imports;rows.append({'native_android_zero_gl_vkgl_egl_extension_imports':True})
for n,data in INPUTS.items():assert (ROOT/n).read_bytes()==data,'source changed during proof: '+n
result={'status':'pass','source_sha256':{n:H(data) for n,data in INPUTS.items()},'baseline':{'path':str(BASELINE),'sha256':H(BASE_BYTES)},'official_NDK_vulkan_core_sha256':H((header_root/'vulkan_core.h').read_bytes()),'production_frames':production_frames,'results':rows,'actual_production_function_sha256':{a:H(t.encode()) for a,t in shared.items()},'mocked_boundaries':['Vulkan driver/queue/presentation-engine effects','device/image/buffer allocation and replay effects','compatibility initializer (profile0 selection only)','OS abort intercepted only at explicit checked fatal boundaries'],'gpu_runtime_verified':False,'display_or_scanout_completion_claimed':False,'unsupported_explicit_present_fence_authority':False}
(OUT/'results.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS actual negotiation/present-retirement chains, source poison, strict UBSan, full 4mode Core/Android NDK, 3 full legacy tokens/O2 controls; results:',OUT/'results.json')
