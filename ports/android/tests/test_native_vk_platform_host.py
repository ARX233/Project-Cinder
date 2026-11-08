#!/usr/bin/env python3
"""Actual shared Vulkan platform functions and native Android routing, with OS/Vk mocks.
UBSan is CPU/mock authority, NOT live Android/GPU/async-fence/pixel proof.
Artifacts stay outside source; baseline may be overridden explicitly.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('CINDER_TEST_OUT', os.environ.get('TMPDIR', tempfile.gettempdir()))).resolve() / 'round7-platform'
assert ROOT != OUT and ROOT not in OUT.parents, 'artifacts must be outside source'
OUT.mkdir(parents=True, exist_ok=True)
base = Path(os.environ.get('CINDER_ANDROID_BASELINE', os.environ.get('CINDER_PLATFORM_BASELINE', str(ROOT.parent / 'round7-baseline/src/main_android.c')))).resolve()
if base.is_dir():
    base = base / 'src/main_android.c'
INPUT_NAMES = ('src/vkgl.c', 'src/native_vk_platform.inc', 'src/native_vk.h', 'src/main_android.c',
               'src/native_vk_upload.inc', 'src/native_vk_resources.inc', 'src/native_vk.inc',
               'tests/test_native_vk_platform_host.py')
INPUTS = {n: (ROOT / n).read_bytes() for n in INPUT_NAMES}
CORE, PLATFORM, ANDROID = (INPUTS[n].decode() for n in ('src/vkgl.c', 'src/native_vk_platform.inc', 'src/main_android.c'))
BASE = base.read_bytes()
H = lambda b: hashlib.sha256(b).hexdigest()


def fun(source, anchor):
    a = source.index(anchor)
    b = source.index('{', a)
    mask = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: ' ' * len(m.group()), source, flags=re.S)
    depth = 0
    for i in range(b, len(source)):
        depth += (mask[i] == '{') - (mask[i] == '}')
        if not depth:
            return source[a:i+1] + '\n'
    raise AssertionError(anchor)


anchors = ('static void dead_add(', 'static void dead_free(', 'static void image_drop(',
           'static int native_image_upload_hold(', 'static int native_target_image_hold(',
           'static void native_target_image_release(', 'static void native_image_upload_complete(',
           'static VkRenderPass rp_make(', 'static int compat_id(', 'static int native_compat_id(', 'static VkRenderPass rp_get(',
           'static void ring_reset(', 'static void uploader_init(', 'static VkResult submit(',
           'static void barrier(', 'static void image_upload_record(', 'static VkSemaphore backend_render_semaphore(void)', 'static int acquire(void)',
           'static void frame_begin(void)', 'static void flush(int final', 'static void flush_wait(void)',
           'int cinder_vk_flush(void)', 'int cinder_vk_finish(void)', 'int cinder_vk_error_pending(void)',
           'static int backend_present(void)', 'static void screen_free(void)',
           'static int backend_surface(', 'static void backend_release_surface(void)',
           'static VkResult backend_pipeline_create(', 'static void backend_pipeline_cache_file(', 'static void backend_pipeline_cache_save(void)',
           'static int has_ext(', 'static vimg *backend_dummy_image(', 'static int backend_create(')
shared = {a: fun(CORE, a) for a in anchors}
# This closure is extracted from production bodies, not a renamed facade model.
selected = '\n'.join(shared.values()) + PLATFORM
for forbidden in ('ctx', 'cur_up', 'main_ctx', 'loader_ctx', 'cur_vao', 'GLenum', 'GLuint', 'GLfloat', 'GLboolean',
                  'GL_EXTENSIONS', 'glGetString', 'glBindFramebuffer', 'vkgl_create', 'vkgl_present',
                  'vkgl_surface', 'vkgl_release_surface'):
    assert not re.search(r'\b' + forbidden + r'\b', re.sub(r'/\*.*?\*/|//[^\n]*', '', selected, flags=re.S)), forbidden
assert 'compat_init ? compat_init() : D.props.deviceName' in shared['static int backend_create(']
assert 'backend_create(extensions, count, NULL)' in PLATFORM
assert 'image_upload_record' in shared['static vimg *backend_dummy_image(']
assert 'native_up_cmd' in shared['static vimg *backend_dummy_image(']
assert 'image_settle(' not in shared['static vimg *backend_dummy_image(']

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
static int render_fault,render_abort_armed,render_expected_compats,render_initial_null,render_create_calls;static size_t render_expected_rps;
static void guarded_abort(void){if(render_abort_armed)_exit(n_compats==render_expected_compats&&n_rps==render_expected_rps&&render_initial_null&&render_create_calls==1?77:78);abort();}
static int fault,image_calls,fail_image_at,view_calls,fail_view_at,fail_stage,fail_begin,wait_fault,present_result,acquire_result,cap_zero,cap_variable;
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
static void fb_cache_forget(VkImageView v){assert(v);++seq;}
static void image_free_now(vimg*im){assert(im&&live_images);assert(!im->swapchain);--live_images;free(im);}
static vimg*image_new(VkFormat fmt,int w,int h,int levels,int layers,int samples,int sampled,int transient,VkComponentMapping swz){
 (void)sampled;(void)transient;if(++image_calls==fail_image_at)return NULL;vimg*im=calloc(1,sizeof*im);assert(im);++live_images;
 im->img=H(VkImage,++next_handle);im->att=H(VkImageView,++next_handle);im->view=H(VkImageView,++next_handle);im->mem.block=-1;
 im->fmt=fmt;im->w=w;im->h=h;im->levels=levels;im->layers=layers;im->samples=samples;im->swz=swz;im->uid=resource_uid_next();
 im->aspect=fmt==VK_FORMAT_D24_UNORM_S8_UINT?(VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT):VK_IMAGE_ASPECT_COLOR_BIT;
 im->usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;im->rest=VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;return im;}
static VkImageView view_new(const vimg*im,int sampled,int levels){assert(im->swapchain&&!sampled&&levels==1);return ++view_calls==fail_view_at?VK_NULL_HANDLE:H(VkImageView,++next_handle);}
static vbufmem*bufmem_try_new(VkDeviceSize bytes,VkBufferUsageFlags usage){assert(usage);if(fail_stage)return NULL;vbufmem*b=calloc(1,sizeof*b);assert(b);b->buf=H(VkBuffer,++next_handle);b->map=calloc(1,(size_t)bytes);b->size=bytes;assert(b->map);return b;}
static void bufmem_free(vbufmem*b){free(b->map);free(b);}
static VkFormatProperties fmt_props(VkFormat fmt){assert(fmt);return (VkFormatProperties){.optimalTilingFeatures=~0u,.bufferFeatures=~0u};}
static int fmt_has(VkFormat fmt,VkFormatFeatureFlags flags){return (fmt_props(fmt).optimalTilingFeatures&flags)==flags;}
static uint32_t mem_type(uint32_t bits,VkMemoryPropertyFlags want,VkMemoryPropertyFlags pref){(void)bits;(void)want;(void)pref;return ~0u;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateInstance(const VkInstanceCreateInfo*i,const VkAllocationCallbacks*a,VkInstance*out){(void)a;assert(i->pApplicationInfo->apiVersion==VK_API_VERSION_1_0);if(fault==20)return VK_ERROR_INCOMPATIBLE_DRIVER;*out=H(VkInstance,1);return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyInstance(VkInstance i,const VkAllocationCallbacks*a){(void)a;assert(i==D.inst);++instance_destroyed;}
VKAPI_ATTR VkResult VKAPI_CALL vkEnumeratePhysicalDevices(VkInstance i,uint32_t*n,VkPhysicalDevice*p){assert(i);*n=fault==21?0:(!p&&fault==29)?1025:(p&&fault==27)?0:(p&&fault==28)?2:1;if(p&&*n)*p=H(VkPhysicalDevice,2);if((!p&&fault==24)||(p&&fault==25))return VK_ERROR_INITIALIZATION_FAILED;if(p&&fault==26)return VK_INCOMPLETE;return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceQueueFamilyProperties(VkPhysicalDevice d,uint32_t*n,VkQueueFamilyProperties*q){assert(d);*n=fault==47?0:(q&&fault==46)?2:1;if(q)*q=(VkQueueFamilyProperties){.queueFlags=fault==22?0:VK_QUEUE_GRAPHICS_BIT};}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceProperties(VkPhysicalDevice d,VkPhysicalDeviceProperties*p){assert(d);memset(p,0,sizeof*p);strcpy(p->deviceName,"mock-native");p->apiVersion=VK_API_VERSION_1_1;p->limits.maxImageDimension2D=4096;p->limits.maxSamplerAnisotropy=4;p->limits.framebufferColorSampleCounts=p->limits.framebufferDepthSampleCounts=5;}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceMemoryProperties(VkPhysicalDevice d,VkPhysicalDeviceMemoryProperties*p){assert(d);memset(p,0,sizeof*p);}
VKAPI_ATTR void VKAPI_CALL vkGetPhysicalDeviceFeatures(VkPhysicalDevice d,VkPhysicalDeviceFeatures*p){assert(d);memset(p,0,sizeof*p);}
VKAPI_ATTR VkResult VKAPI_CALL vkEnumerateDeviceExtensionProperties(VkPhysicalDevice d,const char*l,uint32_t*n,VkExtensionProperties*p){(void)l;assert(d);*n=fault==44?0:(!p&&fault==45)?65537:(p&&fault==43)?2:1;if(p&&*n)strcpy(p->extensionName,VK_KHR_SWAPCHAIN_EXTENSION_NAME);if((!p&&fault==40)||(p&&fault==41))return VK_ERROR_INITIALIZATION_FAILED;if(p&&fault==42)return VK_INCOMPLETE;return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateDevice(VkPhysicalDevice d,const VkDeviceCreateInfo*i,const VkAllocationCallbacks*a,VkDevice*out){(void)a;assert(d&&i->queueCreateInfoCount==1);if(fault==23)return VK_ERROR_INITIALIZATION_FAILED;*out=H(VkDevice,3);return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkGetDeviceQueue(VkDevice d,uint32_t q,uint32_t i,VkQueue*out){assert(d&&!q&&!i);*out=H(VkQueue,4);}
#define MAKE_FN(name,Info,Handle) VKAPI_ATTR VkResult VKAPI_CALL name(VkDevice d,const Info*i,const VkAllocationCallbacks*a,Handle*out){(void)a;assert(d&&i);*out=H(Handle,++next_handle);return VK_SUCCESS;}
MAKE_FN(vkCreatePipelineCache,VkPipelineCacheCreateInfo,VkPipelineCache)
MAKE_FN(vkCreateDescriptorSetLayout,VkDescriptorSetLayoutCreateInfo,VkDescriptorSetLayout)
MAKE_FN(vkCreatePipelineLayout,VkPipelineLayoutCreateInfo,VkPipelineLayout)
MAKE_FN(vkCreateCommandPool,VkCommandPoolCreateInfo,VkCommandPool)
MAKE_FN(vkCreateFence,VkFenceCreateInfo,VkFence)
VKAPI_ATTR VkResult VKAPI_CALL vkCreateSemaphore(VkDevice d,const VkSemaphoreCreateInfo*i,const VkAllocationCallbacks*a,VkSemaphore*out){(void)a;assert(d&&i);if(++sem_create_calls==fail_sem_at)return VK_ERROR_OUT_OF_HOST_MEMORY;*out=H(VkSemaphore,++next_handle);return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroySemaphore(VkDevice d,VkSemaphore sem,const VkAllocationCallbacks*a){(void)a;assert(d&&sem&&!sem_destroyed[(uintptr_t)sem]&&wait_seq);++sem_destroyed[(uintptr_t)sem];++sem_destroy_calls;semaphore_state[(uintptr_t)sem]=0;}

MAKE_FN(vkCreateSampler,VkSamplerCreateInfo,VkSampler)
VKAPI_ATTR VkResult VKAPI_CALL vkAllocateCommandBuffers(VkDevice d,const VkCommandBufferAllocateInfo*i,VkCommandBuffer*out){assert(d&&i->commandBufferCount==1);*out=H(VkCommandBuffer,++next_handle);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkBeginCommandBuffer(VkCommandBuffer c,const VkCommandBufferBeginInfo*i){assert(c&&i->flags==VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT);return fail_begin?VK_ERROR_OUT_OF_HOST_MEMORY:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkEndCommandBuffer(VkCommandBuffer c){assert(c);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkQueueSubmit(VkQueue q,uint32_t n,const VkSubmitInfo*i,VkFence f){assert(q&&n==1&&f&&i->commandBufferCount>=1);++submit_count;if(fault==30)return VK_ERROR_DEVICE_LOST;
 if(i->waitSemaphoreCount){unsigned image=acquire_image[(uintptr_t)*i->pWaitSemaphores];assert(image&&image<=native_present_count);acquire_image[(uintptr_t)*i->pWaitSemaphores]=0;semaphore_state[(uintptr_t)native_present_wait[image-1]]=0;}
 if(i->signalSemaphoreCount){uintptr_t sem=(uintptr_t)*i->pSignalSemaphores;assert(!semaphore_state[sem]&&"RED per-frame semaphore signaled while prior WSI present pending");semaphore_state[sem]=1;}return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkWaitForFences(VkDevice d,uint32_t n,const VkFence*f,VkBool32 all,uint64_t timeout){assert(d&&n==1&&*f&&all&&timeout==UINT64_MAX);return wait_fault?VK_ERROR_DEVICE_LOST:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkResetFences(VkDevice d,uint32_t n,const VkFence*f){assert(d&&n==1&&*f);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkResetCommandPool(VkDevice d,VkCommandPool p,VkCommandPoolResetFlags flags){assert(d&&p&&!flags);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkResetDescriptorPool(VkDevice d,VkDescriptorPool p,VkDescriptorPoolResetFlags flags){assert(d&&p&&!flags);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkDeviceWaitIdle(VkDevice d){assert(d);wait_seq=++seq;++idle_calls;return wait_fault?VK_ERROR_DEVICE_LOST:VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyImageView(VkDevice d,VkImageView v,const VkAllocationCallbacks*a){(void)a;assert(d);if(!v)return;/* Vulkan destroy accepts null handles. */++view_destroys;destroy_seq=++seq;assert(wait_seq&&destroy_seq>wait_seq);}
VKAPI_ATTR void VKAPI_CALL vkDestroyFramebuffer(VkDevice d,VkFramebuffer fb,const VkAllocationCallbacks*a){(void)a;assert(d&&fb);}
VKAPI_ATTR void VKAPI_CALL vkDestroySwapchainKHR(VkDevice d,VkSwapchainKHR c,const VkAllocationCallbacks*a){(void)a;assert(d&&c);++chain_destroyed;}
VKAPI_ATTR void VKAPI_CALL vkDestroySurfaceKHR(VkInstance i,VkSurfaceKHR s,const VkAllocationCallbacks*a){(void)a;assert(i&&s&&(uintptr_t)s<1024);assert(!surface_destroyed[(uintptr_t)s]);++surface_destroyed[(uintptr_t)s];}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPhysicalDeviceSurfaceSupportKHR(VkPhysicalDevice p,uint32_t q,VkSurfaceKHR s,VkBool32*ok){assert(p&&!q&&s);*ok=fault==1?VK_FALSE:VK_TRUE;return fault==2?VK_ERROR_SURFACE_LOST_KHR:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPhysicalDeviceSurfaceCapabilitiesKHR(VkPhysicalDevice p,VkSurfaceKHR s,VkSurfaceCapabilitiesKHR*c){assert(p&&s);if(fault==3)return VK_ERROR_SURFACE_LOST_KHR;*c=(VkSurfaceCapabilitiesKHR){.minImageCount=2,.maxImageCount=3,.currentExtent={cap_variable?UINT32_MAX:cap_zero?0:640,cap_variable?UINT32_MAX:cap_zero?0:480},.minImageExtent={16,16},.maxImageExtent={2048,2048},.supportedUsageFlags=fault==14?0:VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT,.supportedCompositeAlpha=VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR};return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPhysicalDeviceSurfaceFormatsKHR(VkPhysicalDevice p,VkSurfaceKHR s,uint32_t*n,VkSurfaceFormatKHR*f){assert(p&&s);*n=fault==4?0:1;if(f)*f=(VkSurfaceFormatKHR){VK_FORMAT_R8G8B8A8_UNORM,VK_COLOR_SPACE_SRGB_NONLINEAR_KHR};return fault==5?VK_ERROR_SURFACE_LOST_KHR:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateSwapchainKHR(VkDevice d,const VkSwapchainCreateInfoKHR*i,const VkAllocationCallbacks*a,VkSwapchainKHR*c){(void)a;assert(d&&i->surface&&i->imageExtent.width&&i->imageExtent.height);if(fault==6)return VK_ERROR_INITIALIZATION_FAILED;*c=H(VkSwapchainKHR,++next_handle);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkGetSwapchainImagesKHR(VkDevice d,VkSwapchainKHR c,uint32_t*n,VkImage*i){assert(d&&c);*n=fault==7?0:swap_n;if(i)for(uint32_t k=0;k<*n;++k)i[k]=H(VkImage,++next_handle);return fault==8?VK_ERROR_SURFACE_LOST_KHR:VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkAcquireNextImageKHR(VkDevice d,VkSwapchainKHR c,uint64_t timeout,VkSemaphore sem,VkFence f,uint32_t*i){assert(d&&c&&timeout==UINT64_MAX&&sem&&!f);++acquire_count;*i=next_acquire;assert(next_acquire<swap_n);if(acquire_result==VK_SUCCESS||acquire_result==VK_SUBOPTIMAL_KHR)acquire_image[(uintptr_t)sem]=next_acquire+1;return (VkResult)acquire_result;}
VKAPI_ATTR VkResult VKAPI_CALL vkQueuePresentKHR(VkQueue q,const VkPresentInfoKHR*i){assert(q&&i->waitSemaphoreCount==1&&i->swapchainCount==1&&*i->pSwapchains==S.chain);uintptr_t sem=(uintptr_t)*i->pWaitSemaphores;assert(semaphore_state[sem]==1);semaphore_state[sem]=2;++present_count;return (VkResult)present_result;}
VKAPI_ATTR void VKAPI_CALL vkCmdPipelineBarrier(VkCommandBuffer c,VkPipelineStageFlags s,VkPipelineStageFlags d,VkDependencyFlags flags,uint32_t nm,const VkMemoryBarrier*m,uint32_t nb,const VkBufferMemoryBarrier*b,uint32_t ni,const VkImageMemoryBarrier*i){(void)m;(void)b;assert(c&&s&&d&&!flags&&!nm&&!nb&&ni==1&&i->image);}
VKAPI_ATTR void VKAPI_CALL vkCmdCopyBufferToImage(VkCommandBuffer c,VkBuffer b,VkImage i,VkImageLayout l,uint32_t n,const VkBufferImageCopy*r){assert(c&&b&&i&&l==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL&&n==1&&r->imageExtent.width==1&&r->imageExtent.height==1);vbufmem*stage=NULL;for(size_t k=0;k<F->up.stage.n;++k)if(F->up.stage.b[k]->buf==b)stage=F->up.stage.b[k];assert(stage&&r->bufferOffset+4<=stage->size);assert(!memcmp(stage->map+r->bufferOffset,"\0\0\0\377",4));++copy_count;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateGraphicsPipelines(VkDevice d,VkPipelineCache cache,uint32_t n,const VkGraphicsPipelineCreateInfo*i,const VkAllocationCallbacks*a,VkPipeline*out){(void)a;assert(d&&cache&&n==1&&i);int lock=pthread_mutex_trylock(&D.plock);assert(lock==EBUSY);*out=H(VkPipeline,++next_handle);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateRenderPass(VkDevice d,const VkRenderPassCreateInfo*i,const VkAllocationCallbacks*a,VkRenderPass*out){(void)a;assert(d&&i&&i->subpassCount==1);++render_create_calls;if(render_fault){render_initial_null=*out==VK_NULL_HANDLE;if(render_fault==52)*out=H(VkRenderPass,999);return render_fault==51?VK_SUCCESS:VK_ERROR_OUT_OF_HOST_MEMORY;}*out=H(VkRenderPass,++next_handle);return VK_SUCCESS;}
#define abort guarded_abort
VKAPI_ATTR VkResult VKAPI_CALL vkMergePipelineCaches(VkDevice d,VkPipelineCache c,uint32_t n,const VkPipelineCache*p){assert(d&&c&&n==1&&*p);assert(pthread_mutex_trylock(&D.plock)==EBUSY);return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyPipelineCache(VkDevice d,VkPipelineCache c,const VkAllocationCallbacks*a){(void)a;assert(d&&c);}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPipelineCacheData(VkDevice d,VkPipelineCache c,size_t*n,void*p){assert(d&&c);assert(pthread_mutex_trylock(&D.plock)==EBUSY);*n=4;if(p)memcpy(p,"R7PC",4);return VK_SUCCESS;}
#pragma GCC poison ctx cur_up main_ctx loader_ctx cur_vao GLenum GLuint GLfloat GLboolean GL_EXTENSIONS glGetString glBindFramebuffer vkgl_create vkgl_present vkgl_surface vkgl_release_surface
'''

# Round8 adds an optional maintenance1 boundary. This original Round7 model
# deliberately selects the unsupported/fallback path; the new present-fence
# fixture executes the actual negotiation/fence helpers. Old actions/assertions
# remain unchanged, including actual Core acquire/submit/present/retirement.
prefix += r'''
static struct { cinder_vk_retirement_mode enabled_device; } native_retirement = { CINDER_VK_RETIREMENT_IDLE_FALLBACK };
static const char **native_present_instance_prepare(VkInstanceCreateInfo *info){(void)info;return NULL;}
static void native_present_instance_created(VkResult result){(void)result;}
static const char *native_present_device_prepare(const VkExtensionProperties *extensions,uint32_t count,VkPhysicalDeviceSwapchainMaintenance1FeaturesEXT *feature){(void)extensions;(void)count;(void)feature;return NULL;}
static void native_present_device_created(VkResult result){(void)result;}
static int native_present_fences_enabled(void){return 0;}
static int native_present_fences_create(uint32_t count){(void)count;return 1;}
static int native_present_fences_ready(void){return 1;}
static void native_present_fences_destroy(void){}
static void native_present_image_reuse(uint32_t image){(void)image;}
static void native_present_retire_all(void){}
static int native_present_attach(VkPresentInfoKHR *present,VkSwapchainPresentFenceInfoEXT *info,VkResult *result){(void)present;(void)info;(void)result;return 0;}
static void native_present_result(VkResult overall,VkResult per_swapchain){(void)overall;(void)per_swapchain;}
static VkResult view_try(const vimg *im,int sampled,int levels,VkImageView *view){*view=view_new(im,sampled,levels);return *view?VK_SUCCESS:VK_ERROR_OUT_OF_HOST_MEMORY;}
'''
production_frames = int(re.search(r'^#define FRAMES (\d+)$', CORE, re.M).group(1))
prefix = prefix.replace('#define FRAMES 2', '#define FRAMES ' + str(production_frames))
support = fun(INPUTS['src/native_vk.inc'].decode(), 'static int native_reject(void)') + fun(INPUTS['src/native_vk.inc'].decode(), 'uint64_t cinder_vk_error_epoch(void)')
support += 'static __thread cinder_vk_upload_stream native_upload_stream;\n'
support += fun(INPUTS['src/native_vk_resources.inc'].decode(), 'int cinder_vk_upload_stream_set(')
support += fun(INPUTS['src/native_vk_resources.inc'].decode(), 'cinder_vk_upload_stream cinder_vk_upload_stream_get(')
support += INPUTS['src/native_vk_upload.inc'].decode()
a = CORE.index('static const VkFormat VFMT[]')
b = CORE.index('/* a vertex attribute', a)
support += CORE[a:b]
# Declarations match production order; definitions remain exact extracted bodies.
prototypes = '\n'.join(text[:text.index('{')].strip() + ';' for text in shared.values()) + '\n'

cases = r'''
static void no_surface(void){assert(!S.n&&!S.img&&!S.chain&&!S.surface&&!S.w&&!S.h&&!native_frame_claimed&&!S.acquired&&!native_present_wait&&!native_present_count&&!cinder_vk_platform_frame_ready());}
static void successful_start(void){const char*ext[]={VK_KHR_SURFACE_EXTENSION_NAME};assert(!strcmp(cinder_vk_device_name(),"unavailable")&&!cinder_vk_device_api_version());assert(!cinder_vk_platform_create(ext,1));assert(platform_created&&platform_native_profile&&F&&copy_count==7&&submit_count==1&&!F->up.open&&!F->up.stage.used&&!F->submitted);assert(dummy2d->defined&&dummycube->defined&&dummy2d->serial==1&&dummycube->serial==1&&!native_frame_claimed);assert(!strcmp(cinder_vk_device_name(),"mock-native")&&cinder_vk_device_api_version()==VK_API_VERSION_1_1);assert(cinder_vk_platform_instance()==D.inst&&cinder_vk_platform_create(ext,1)==-1);puts("PASS actual shared create: NULL compatibility initializer, real 1+6 black uploads, completed fence before platform publication, typed device info");}
static void surfaces(void){
 for(int f=1;f<=14;++f){if(f>=9&&f<=12)continue;fault=f;if(f==13){memset(compats,0,sizeof compats);n_compats=64;}VkSurfaceKHR s=H(VkSurfaceKHR,100+f);assert(cinder_vk_platform_surface(s,640,480)==-1);assert(surface_destroyed[100+f]==1);no_surface();if(f==13)n_compats=0;}fault=0;
 for(int v=1;v<=2;++v){fail_view_at=view_calls+v;VkSurfaceKHR s=H(VkSurfaceKHR,130+v);assert(cinder_vk_platform_surface(s,640,480)==-1&&surface_destroyed[130+v]);no_surface();}fail_view_at=0;
 fail_image_at=image_calls+2;assert(cinder_vk_platform_surface(H(VkSurfaceKHR,140),640,480)==-1&&surface_destroyed[140]);no_surface();fail_image_at=0;
 cap_zero=1;assert(cinder_vk_platform_surface(H(VkSurfaceKHR,141),640,480)==-1&&surface_destroyed[141]);no_surface();cap_zero=0;
 assert(cinder_vk_platform_surface(H(VkSurfaceKHR,142),0,480)==-1&&surface_destroyed[142]);no_surface();
 assert(cinder_vk_platform_surface(H(VkSurfaceKHR,143),640,-1)==-1&&surface_destroyed[143]);no_surface();
 cap_variable=1;assert(!cinder_vk_platform_surface(H(VkSurfaceKHR,144),1,3000)&&S.w==16&&S.h==2048);cap_variable=0;cinder_vk_platform_release_surface();no_surface();
 assert(!cinder_vk_platform_surface(H(VkSurfaceKHR,145),640,480)&&S.n==2&&S.depth&&S.w==640&&S.h==480&&S.compat>=0&&!S.acquired);
 assert(cinder_vk_platform_frame_ready()&&native_frame_claimed&&S.acquired);unsigned old_acquire=acquire_count;assert(cinder_vk_platform_frame_ready()&&acquire_count==old_acquire);
 VkDevice device=D.dev;D.dev=VK_NULL_HANDLE;assert(!cinder_vk_platform_frame_ready()&&cinder_vk_platform_present()==-1&&native_frame_claimed&&S.acquired&&acquire_count==old_acquire);cinder_vk_platform_release_surface();assert(native_frame_claimed&&S.surface==H(VkSurfaceKHR,145));assert(!strcmp(cinder_vk_device_name(),"unavailable")&&!cinder_vk_device_api_version()&&!cinder_vk_platform_instance());char old_path[512];memcpy(old_path,D.pcache_path,sizeof old_path);cinder_vk_platform_pipeline_cache_file("not-opened");cinder_vk_platform_pipeline_cache_save();assert(!memcmp(old_path,D.pcache_path,sizeof old_path));assert(cinder_vk_platform_surface(H(VkSurfaceKHR,147),640,480)==-1&&surface_destroyed[147]&&native_frame_claimed&&!surface_destroyed[145]);D.dev=device;
 uint64_t epoch=cinder_vk_error_epoch();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));cinder_vk_platform_release_surface();assert(native_frame_claimed&&S.acquired&&S.surface==H(VkSurfaceKHR,145)&&cinder_vk_error_epoch()==epoch+1);
 assert(cinder_vk_platform_surface(H(VkSurfaceKHR,145),640,480)==-1&&!surface_destroyed[145]&&native_frame_claimed);
 assert(cinder_vk_platform_surface(H(VkSurfaceKHR,146),640,480)==-1&&surface_destroyed[146]&&native_frame_claimed&&!surface_destroyed[145]);
 assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_FRAME));unsigned submitted=submit_count;cinder_vk_platform_release_surface();assert(submit_count==submitted+1&&surface_destroyed[145]);no_surface();
 assert(!cinder_vk_platform_surface(VK_NULL_HANDLE,32,16)&&S.headless&&S.n==1&&S.w==32&&S.h==16&&cinder_vk_platform_frame_ready());assert(!cinder_vk_platform_present());cinder_vk_platform_release_surface();no_surface();
 puts("PASS actual surface support/capability/format/chain/images/views/depth faults consume once, cleanup after idle, zero dimensions unavailable, clamp variable extent, role/alias preserve live claim, acquired release consumes semaphore, real headless image");
}
static void presentation(void){
 assert(!cinder_vk_platform_surface(H(VkSurfaceKHR,160),640,480));assert(cinder_vk_platform_present()==-1);unsigned before=present_count;
 acquire_result=VK_ERROR_OUT_OF_DATE_KHR;assert(!cinder_vk_platform_frame_ready()&&present_count==before&&!native_frame_claimed&&cinder_vk_platform_surface_stale());
 acquire_result=VK_ERROR_SURFACE_LOST_KHR;assert(!cinder_vk_platform_frame_ready()&&cinder_vk_platform_surface_stale());
 unsigned old_acquires=acquire_count;native_loader_failed=1;assert(!cinder_vk_platform_frame_ready()&&!cinder_vk_platform_surface_stale()&&acquire_count==old_acquires);native_loader_failed=0;
 uint64_t saved_epoch=native_reject_count;native_reject_count=UINT64_MAX;assert(!cinder_vk_platform_frame_ready()&&!cinder_vk_platform_surface_stale()&&acquire_count==old_acquires);native_reject_count=saved_epoch;acquire_result=VK_SUCCESS;
 assert(cinder_vk_platform_frame_ready());unsigned old=present_count;assert(cinder_vk_platform_present()==1&&present_count==old+1&&!native_frame_claimed);old=present_count;assert(cinder_vk_platform_present()==-1&&present_count==old);
 assert(cinder_vk_platform_surface_stale()&&!cinder_vk_platform_frame_ready());assert(!cinder_vk_platform_surface(H(VkSurfaceKHR,161),640,480));
 assert(cinder_vk_platform_frame_ready());present_result=VK_SUBOPTIMAL_KHR;assert(cinder_vk_platform_present()==1);present_result=VK_SUCCESS;
 assert(cinder_vk_platform_surface_stale());assert(!cinder_vk_platform_surface(H(VkSurfaceKHR,162),640,480));
 acquire_result=VK_SUBOPTIMAL_KHR;assert(cinder_vk_platform_frame_ready()&&cinder_vk_platform_present()==1);acquire_result=VK_SUCCESS;
 assert(cinder_vk_platform_surface_stale());assert(!cinder_vk_platform_surface(H(VkSurfaceKHR,163),640,480));
 assert(cinder_vk_platform_frame_ready());present_result=VK_ERROR_SURFACE_LOST_KHR;assert(cinder_vk_platform_present()==-1);present_result=VK_SUCCESS;
 assert(cinder_vk_platform_surface_stale());assert(!cinder_vk_platform_surface(H(VkSurfaceKHR,164),640,480));
 assert(cinder_vk_platform_frame_ready());vframe*saved=F;F=NULL;old=present_count;assert(cinder_vk_platform_present()==-1&&native_frame_claimed&&present_count==old);F=saved;
 assert(!cinder_vk_platform_present()&&!native_frame_claimed&&D.serial>1&&D.done<D.serial);
 cinder_vk_platform_release_surface();assert(cinder_vk_platform_present()==-1);no_surface();
 puts("PASS actual acquire/present/flush/frame_begin: one claimed present only, no-F rejection, out-of-date/suboptimal/surface-loss recreation, current frame serial and deferred dead watermark");
}
static void dummy_faults(void){size_t i=F->up.stage.i;VkDeviceSize used=F->up.stage.used;unsigned live=live_images,copies=copy_count;
 fail_stage=1;ring saved=F->up.stage;memset(&F->up.stage,0,sizeof F->up.stage);F->up.stage.chunk=64;F->up.stage.usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
 assert(!backend_dummy_image(&F->up,6)&&live_images==live&&copy_count==copies&&!F->up.stage.used&&!F->up.open);F->up.stage=saved;fail_stage=0;
 fail_begin=1;assert(!backend_dummy_image(&F->up,6)&&live_images==live&&copy_count==copies&&F->up.stage.i==i&&F->up.stage.used==used);fail_begin=0;
 puts("PASS actual fallback allocation/ring/begin failures publish no fabricated image or command; precommand cursor preserved");
}
static void wsi_lifetimes(void){swap_n=3;assert(!cinder_vk_platform_surface(H(VkSurfaceKHR,170),640,480));assert(native_present_count==3);unsigned idle_before=idle_calls;
 fflush(NULL);pid_t red=fork();assert(red>=0);if(!red){freopen("/dev/null","w",stderr);platform_native_profile=0;for(unsigned k=0;k<3;++k){next_acquire=k;assert(cinder_vk_platform_frame_ready());cinder_vk_platform_present();}_exit(92);}int status;assert(waitpid(red,&status,0)==red&&WIFSIGNALED(status)&&WTERMSIG(status)==SIGABRT);
 for(unsigned k=0;k<3;++k){next_acquire=k;assert(cinder_vk_platform_frame_ready());assert(!cinder_vk_platform_present());assert(semaphore_state[(uintptr_t)native_present_wait[k]]==2);}
 /* Frame slot/fence reused, but image0's WSI wait is still pending. */
 assert(semaphore_state[(uintptr_t)native_present_wait[0]]==2&&idle_calls==idle_before);
 next_acquire=0;assert(cinder_vk_platform_frame_ready()&&semaphore_state[(uintptr_t)native_present_wait[0]]==2);assert(!cinder_vk_platform_present()&&semaphore_state[(uintptr_t)native_present_wait[0]]==2&&idle_calls==idle_before);
 next_acquire=0;cinder_vk_platform_release_surface();no_surface();
 for(unsigned k=1;k<=3;++k){fail_sem_at=sem_create_calls+k;unsigned destroyed=sem_destroy_calls;assert(cinder_vk_platform_surface(H(VkSurfaceKHR,190+k),640,480)==-1);assert(sem_destroy_calls==destroyed+k-1&&surface_destroyed[190+k]);no_surface();}fail_sem_at=0;swap_n=2;
 puts("PASS WSI controlled RED old per-frame selector aborts at third frame with 2 frame slots/3 images; actual per-image signal+present selector succeeds, frame fence never clears pending WSI, same-image acquire+submit wait permits reuse, no per-frame device-idle; 3 semaphore-allocation faults rollback exact owners");}
static void actual_retirement(void){
 for(int order=0;order<2;++order){unsigned live=live_images;vimg*im=image_new(VK_FORMAT_R8G8B8A8_UNORM,1,1,1,1,1,0,0,SWZ_ID);assert(im&&native_target_image_hold(im)&&native_image_upload_hold(im));im->serial=D.serial+2;uint64_t retirement=im->serial;image_drop(im);assert(im->native_retire_pending&&!n_dead);
 if(order==0){native_target_image_release(im);dead_free(UINT64_MAX);assert(live_images==live+1&&!n_dead&&im->native_upload_pending);native_image_upload_complete();}
 else{native_image_upload_complete();dead_free(UINT64_MAX);assert(live_images==live+1&&!n_dead&&im->native_target_refs);native_target_image_release(im);}
 assert(n_dead==1&&live_images==live+1);dead_free(retirement-1);assert(n_dead==1&&live_images==live+1);dead_free(retirement);assert(!n_dead&&live_images==live);}
 unsigned live=live_images;vimg*im=image_new(VK_FORMAT_R8G8B8A8_UNORM,1,1,1,1,1,0,0,SWZ_ID);im->serial=D.serial+2;uint64_t retirement=im->serial;image_drop(im);
 while(D.serial<retirement+2){++D.serial;frame_begin();if(D.serial<retirement+2)assert(live_images==live+1&&n_dead==1);}
 assert(!n_dead&&live_images==live&&D.done>=retirement);
 puts("PASS actual dead_add/dead_free/image_drop and target/upload holds: either lease completion order gates retirement, explicit serial boundary gates destruction, actual frame_begin only retires after completed-frame watermark (Vulkan/free effects mocked)");}
static void renderpass_publication(void){fflush(NULL);for(int route=0;route<2;++route)for(int f=50;f<=52;++f){pid_t pid=fork();assert(pid>=0);if(!pid){render_abort_armed=1;render_fault=f;render_create_calls=render_initial_null=0;memset(compats,0,sizeof compats);n_compats=route?1:0;n_rps=0;render_expected_compats=n_compats;render_expected_rps=0;if(route){compats[0]=(compat_t){VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_D24_UNORM_S8_UINT,1,0,VK_NULL_HANDLE};rp_t o={.compat=0,.crest=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,.drest=VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL};rp_get(&o);}else native_compat_id(VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_D24_UNORM_S8_UINT,1,0);_exit(79);}int status;assert(waitpid(pid,&status,0)==pid&&WIFEXITED(status)&&WEXITSTATUS(status)==77);}puts("PASS actual rp_make/compat_id/native_compat_id/rp_get chains: error untouched-out, error nonnull-out, success NULL all hit explicit native abort before either cache count publishes; initial output NULL observed; six child exit77 boundary witnesses");}
static void fatal_policy(void){fflush(NULL);for(int kind=0;kind<6;++kind){pid_t pid=fork();assert(pid>=0);if(!pid){freopen("/dev/null","w",stderr);if(kind==0){wait_fault=1;cinder_vk_finish();}else if(kind==1){fault=30;cinder_vk_finish();}else{assert(!cinder_vk_platform_surface(H(VkSurfaceKHR,180+kind),640,480));if(kind==2||kind==4){acquire_result=kind==2?VK_ERROR_DEVICE_LOST:VK_ERROR_OUT_OF_HOST_MEMORY;cinder_vk_platform_frame_ready();}else{assert(cinder_vk_platform_frame_ready());present_result=kind==3?VK_ERROR_DEVICE_LOST:VK_ERROR_OUT_OF_HOST_MEMORY;cinder_vk_platform_present();}}_exit(91);}int status;assert(waitpid(pid,&status,0)==pid&&WIFSIGNALED(status)&&WTERMSIG(status)==SIGABRT);}puts("PASS explicit fatal native main wait/submit/acquire/present device-loss policy (child abort witnesses); no recovery claim");}
int main(int argc,char**argv){if(argc>1){fault=atoi(argv[1]);const char*ext[]={VK_KHR_SURFACE_EXTENSION_NAME};assert(cinder_vk_platform_create(ext,1)==-1&&!platform_created&&!D.inst&&!D.dev);assert(instance_destroyed==(unsigned)(fault!=20));assert(cinder_vk_platform_create(ext,1)==-1&&instance_destroyed==(unsigned)(fault!=20));puts("PASS actual early unavailable create/count/partial enumeration cleans instance once and remains one-shot");return 0;}
 successful_start();surfaces();presentation();dummy_faults();wsi_lifetimes();actual_retirement();renderpass_publication();fatal_policy();
 VkGraphicsPipelineCreateInfo ci={VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};VkPipeline pipeline=VK_NULL_HANDLE;assert(backend_pipeline_create(&ci,&pipeline)==VK_SUCCESS&&pipeline);assert(!pthread_mutex_trylock(&D.plock));assert(!pthread_mutex_unlock(&D.plock));
 char path[1024];assert(getcwd(path,sizeof path));strcat(path,"/cache.bin");cinder_vk_platform_pipeline_cache_file(path);cinder_vk_platform_pipeline_cache_save();FILE*f=fopen(path,"rb");char bytes[4];assert(f&&fread(bytes,1,4,f)==4&&!memcmp(bytes,"R7PC",4));fclose(f);cinder_vk_platform_pipeline_cache_file(path);puts("PASS actual cache read/merge/atomic .new rename path; mock cache bytes only");return 0;}
'''

android_prefix = r'''
#define WMMT_VK 1
#define WMMT_NATIVE_VK 1
#define VK_USE_PLATFORM_ANDROID_KHR 1
#include <assert.h>
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <setjmp.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "native_vk.h"
#include "timing60.h"
#define TOUCH_MAX 256
#ifndef TIMER_ABSTIME
#define TIMER_ABSTIME 1 /* Android clock flag, absent in macOS host headers */
#endif
#define H(T,n) ((T)(uintptr_t)(n))
typedef struct {int id,phase;float x,y;}touch_ev;
typedef struct {int pending,attempts;}snd_retry;typedef int aaudio_result_t;
struct ANativeWindow {int w,h;};typedef struct ANativeWindow ANativeWindow;
static struct {pthread_mutex_t mx;pthread_cond_t cv;ANativeWindow*window;int window_changed,paused,started,vk_up,have_surface;
 VkSurfaceKHR vk_surface;int fb_w,fb_h;float touch_k,touch_edge;char save_dir[512],data_dir[512],sidecar_dir[512];void*fail,*audio;
 touch_ev touches[TOUCH_MAX];int n_touch,touch_desync,press_start,movie_done_ev,memory_warning,tilt_new,wants_tilt,movie;float tilt;
 _Atomic int refresh_millihz;}A={.mx=PTHREAD_MUTEX_INITIALIZER,.cv=PTHREAD_COND_INITIALIZER};
static snd_retry audio_retry;static jmp_buf stop;
static int create_fail,surface_fail,os_fail,role_fail,ready_mode,stale,iterations,max_iterations,callback_mode,callback_lock_ok;
static unsigned creates,surface_calls,releases,os_calls,cache_calls,app_calls,present_calls,discard_calls,event_calls,loader_calls,stream_calls,unready_sleeps;
static char trace[512],cache_path[600];static size_t trace_n;static int64_t nanos;
static void mark(char c){assert(trace_n+1<sizeof trace);trace[trace_n++]=c;trace[trace_n]=0;}
int cinder_vk_platform_create(const char*const*e,int n){assert(n==2&&e&&!strcmp(e[0],VK_KHR_SURFACE_EXTENSION_NAME));++creates;return create_fail?-1:0;}
VkInstance cinder_vk_platform_instance(void){return H(VkInstance,1);}
void cinder_vk_platform_pipeline_cache_file(const char*p){++cache_calls;strcpy(cache_path,p);}
void cinder_vk_platform_pipeline_cache_save(void){mark('k');}
void cinder_vk_platform_release_surface(void){++releases;}
int cinder_vk_platform_surface(VkSurfaceKHR s,int w,int h){assert(s==H(VkSurfaceKHR,90)&&w==640&&h==480);++surface_calls;stale=0;return surface_fail?-1:0;}
void cinder_vk_screen_extent(int*w,int*h){*w=640;*h=480;}
int cinder_vk_platform_frame_ready(void){int lock=pthread_mutex_trylock(&A.mx);assert(!lock);++callback_lock_ok;if(callback_mode==1)A.paused=1;else if(callback_mode==2)A.window_changed=1;pthread_mutex_unlock(&A.mx);return ready_mode;}
int cinder_vk_platform_surface_stale(void){return stale;}
int cinder_vk_platform_present(void){++present_calls;mark('s');return 0;}
int cinder_vk_discard(uint32_t target,VkImageAspectFlags aspects){assert(!target&&aspects==(VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT));++discard_calls;mark('x');return 1;}
int cinder_vk_upload_stream_set(cinder_vk_upload_stream stream){assert(stream==CINDER_VK_UPLOAD_LOADER);++stream_calls;return !role_fail;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateAndroidSurfaceKHR(VkInstance i,const VkAndroidSurfaceCreateInfoKHR*c,const VkAllocationCallbacks*a,VkSurfaceKHR*out){(void)a;assert(i&&c->window==A.window);++os_calls;if(os_fail)return VK_ERROR_SURFACE_LOST_KHR;*out=H(VkSurfaceKHR,90);return VK_SUCCESS;}
static int ANativeWindow_getWidth(ANativeWindow*w){return w->w;}static int ANativeWindow_getHeight(ANativeWindow*w){return w->h;}
static void*env_here(void){return NULL;}static void call_str(void*m,const char*s){(void)m;assert(!strcmp(s,"no native Vulkan on this phone"));mark('e');}
static double now_s(void){nanos+=1000000;return nanos*1e-9;}static void app_loader(void){++loader_calls;}
static void app_save_dir(const char*p){assert(!strcmp(p,"/mock/save"));}static void app_console(void){}static void app_wide(float e,float s){(void)e;(void)s;}
static int app_viewport(int w,int h,float e,float s){assert(w>0&&h>0);app_wide(e,s);return 1;}
static int android_card_resources_dir(char*out,size_t n){(void)out;(void)n;return 0;}static void hud_set_extra_directory(const char*p){assert(!p);}
static int app_init(const char*p,int w,int h,float sw,float sh){assert(!strcmp(p,"/mock/data")&&w==640&&h==480&&sw==1024&&sh==768);return 0;}
static const char*app_error(void){return "unused";}static void snd_retry_begin(snd_retry*r,double n){(void)r;(void)n;}
static void snd_retry_stability(snd_retry*r,double n,int started){(void)r;(void)n;assert(!started);}
static void audio_service(int away,double n){(void)away;(void)n;mark('a');}static aaudio_result_t AAudioStream_requestPause(void*p){assert(p);return 0;}static int AAudioStream_getState(void*p){assert(p);return 0;}
static void app_suspend(int away){mark(away?'b':'u');}static void app_timing_reset(void){mark('z');}
static void app_memory_warning(void){++event_calls;mark('w');}static void app_movie_done(void){++event_calls;mark('d');}static void app_press_start(void){++event_calls;mark('p');}
static void touch_cancel_all(void){mark('c');}static void touch_reconcile_snapshot(int*n,int*d){(void)n;*d=0;mark('r');}
static void touch_deliver(touch_ev*t,int n,int d){assert(n==1&&!d&&t[0].id==7);mark('t');}static int app_wants_tilt(void){mark('i');return 1;}
static void app_tilt(float f){assert(f==0.5f);++event_calls;mark('j');}static void app_present(float dt){assert(dt==0);++app_calls;mark('v');}
static void sync_movie(void){mark('m');}static void app_frame_done(double ms){assert(ms>=0);mark('f');longjmp(stop,1);}
static int mock_clock_gettime(clockid_t id,struct timespec*t){assert(id==CLOCK_MONOTONIC);nanos+=16666667;t->tv_sec=nanos/1000000000;t->tv_nsec=nanos%1000000000;return 0;}
static int mock_clock_nanosleep(clockid_t id,int f,const struct timespec*t,struct timespec*r){(void)t;(void)r;assert(id==CLOCK_MONOTONIC&&f==TIMER_ABSTIME);if(++iterations>max_iterations)longjmp(stop,1);return 0;}
static int mock_cond_wait(pthread_cond_t*c,pthread_mutex_t*m){assert(c==&A.cv&&m==&A.mx);A.paused=0;return 0;}
static int mock_thread_create(pthread_t*t,const pthread_attr_t*a,void*(*fn)(void*),void*arg){(void)t;(void)a;assert(fn&&arg==NULL);return 1;}
static int mock_usleep(useconds_t duration){assert(duration==10000||duration==100000);if(duration==10000)++unready_sleeps;return 0;}
#define usleep mock_usleep
#define clock_gettime mock_clock_gettime
#define clock_nanosleep mock_clock_nanosleep
#define pthread_cond_wait mock_cond_wait
#define pthread_create mock_thread_create
#define SURFACE_UP A.have_surface
#pragma GCC poison ctx cur_up main_ctx loader_ctx GLuint GLenum glBindFramebuffer glGetString eglGetProcAddress vkgl_create vkgl_surface vkgl_present vkDestroySurfaceKHR
'''
android_functions = ''.join(fun(ANDROID, a) for a in ('static int touch_take(', 'static int egl_init(void)', 'static void *loader(', 'static void take_window(void)', 'static int ui_viewport_sync(', 'static int start_game(void)', 'static void *game('))
android_cases = r'''
static ANativeWindow window={640,480};
static void reset(void){assert(!pthread_mutex_destroy(&A.mx));memset(&A,0,sizeof A);assert(!pthread_mutex_init(&A.mx,NULL));strcpy(A.save_dir,"/mock/save");strcpy(A.data_dir,"/mock/data");A.window=&window;A.fb_w=640;A.fb_h=480;A.have_surface=1;A.started=1;
 A.press_start=A.movie_done_ev=A.memory_warning=A.tilt_new=1;A.tilt=0.5f;A.n_touch=1;A.touches[0]=(touch_ev){.id=7};create_fail=surface_fail=os_fail=role_fail=ready_mode=stale=iterations=callback_mode=callback_lock_ok=0;max_iterations=2;
 creates=surface_calls=releases=os_calls=cache_calls=app_calls=present_calls=discard_calls=event_calls=loader_calls=stream_calls=unready_sleeps=0;trace_n=0;trace[0]=0;nanos=0;}
static void queued(void){assert(A.press_start&&A.movie_done_ev&&A.memory_warning&&A.tilt_new&&A.n_touch==1&&!app_calls&&!present_calls&&!discard_calls&&!event_calls);}
int main(void){reset();assert(!egl_init()&&A.vk_up&&creates==1&&cache_calls==1&&!strcmp(cache_path,"/mock/save/vk_pipelines.bin"));loader(NULL);assert(stream_calls==1&&loader_calls==1);role_fail=1;loader(NULL);assert(stream_calls==2&&loader_calls==1);assert(!start_game());
 reset();create_fail=1;assert(game(NULL)==NULL&&!strcmp(trace,"e")&&!app_calls&&!unready_sleeps);
 reset();A.have_surface=0;os_fail=1;take_window();assert(os_calls==1&&!surface_calls&&!releases&&!A.have_surface&&!A.vk_surface);
 reset();A.have_surface=0;surface_fail=1;take_window();assert(os_calls==1&&surface_calls==1&&!releases&&!A.have_surface&&!A.vk_surface&&!A.fb_w&&!A.fb_h);
 reset();A.have_surface=0;take_window();assert(A.have_surface&&A.fb_w==640&&A.fb_h==480&&surface_calls==1);A.window=NULL;take_window();assert(releases==1&&!A.have_surface&&!A.fb_w&&!A.fb_h);
 puts("PASS actual Native Android startup/cache identity, explicit loader role, OS-create failure has no transferred handle, backend-surface failure has one transferred owner, release/window absence clears dimensions");
 reset();if(!setjmp(stop))game(NULL);queued();assert(iterations==3&&callback_lock_ok==2&&!surface_calls&&!releases&&!A.window_changed&&unready_sleeps==2);
 puts("PASS actual Android root two pending/non-WSI admission failures: paced no render/recreate, touch/start/movie/warning/tilt events retained");
 reset();stale=1;if(!setjmp(stop))game(NULL);queued();assert(releases==1&&surface_calls==1&&!A.window_changed&&unready_sleeps==2);
 puts("PASS actual Android root WSI stale causes exactly one rebuild, subsequent non-WSI rejection does not loop recreation or consume events");
 for(int cb=1;cb<=2;++cb){reset();ready_mode=1;callback_mode=cb;max_iterations=1;if(!setjmp(stop))game(NULL);queued();assert(callback_lock_ok==1&&(A.paused||A.window_changed)&&unready_sleeps==1);}
 puts("PASS callbacks acquire A.mx during WSI wait, pause/replacement recheck prevents old-surface render and event consumption");
 reset();ready_mode=1;if(!setjmp(stop))game(NULL);assert(app_calls==1&&present_calls==1&&discard_calls==1&&event_calls==4&&!A.n_touch&&!A.press_start&&!A.movie_done_ev&&!A.memory_warning&&!A.tilt_new);assert(!strcmp(trace,"awdprtijrvmxsf")&&!unready_sleeps);
 puts("PASS actual ready Android root audio/events/touch/tilt/render/movie/native discard/present/frame_done order; one acquired display frame");return 0;}
'''

results = []
cc = os.environ.get('CC', 'clang')
flags = [cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-parameter', '-Wno-missing-field-initializers',
         '-fsanitize=undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-I', str(ROOT / 'src')]
if Path('/opt/homebrew/include/vulkan/vulkan.h').exists():
    flags += ['-I', '/opt/homebrew/include']
with tempfile.TemporaryDirectory(prefix='platform-', dir=OUT) as tmp:
    work = Path(tmp)
    text = prefix + support + prototypes + '\n'.join(shared.values()) + PLATFORM + cases
    source, binary = work / 'actual-platform.c', work / 'actual-platform'
    source.write_text(text)
    subprocess.run([*flags, str(source), '-pthread', '-o', str(binary)], check=True, timeout=120)
    for extra in [()] + [(str(f),) for f in (20,21,22,23,24,25,26,27,28,29,40,41,42,43,44,45,46,47)]:
        run = subprocess.run([str(binary), *extra], cwd=work, capture_output=True, text=True, timeout=45)
        (OUT / ('actual-platform-' + ('main' if not extra else extra[0]) + '.log')).write_text(run.stdout + run.stderr)
        print(run.stdout + run.stderr, end='')
        assert run.returncode == 0, ('actual platform fixture failed', run.returncode)
        results.append({'fixture': 'actual-platform', 'arguments': list(extra), 'exit_code': run.returncode, 'stdout': run.stdout})
    (OUT / 'actual-platform.c').write_text(text)
    android_text = android_prefix + android_functions + android_cases
    android_source, android_binary = work / 'actual-android.c', work / 'actual-android'
    android_source.write_text(android_text)
    subprocess.run([*flags, str(android_source), '-pthread', '-o', str(android_binary)], check=True, timeout=120)
    run = subprocess.run([str(android_binary)], cwd=work, capture_output=True, text=True, timeout=45)
    (OUT / 'actual-android.log').write_text(run.stdout + run.stderr)
    (OUT / 'actual-android.c').write_text(android_text)
    print(run.stdout + run.stderr, end='')
    assert run.returncode == 0, ('actual Android fixture failed', run.returncode)
    results.append({'fixture': 'actual-android', 'exit_code': run.returncode, 'stdout': run.stdout})
    ndk = Path(os.environ.get('CINDER_NDK_BIN', '/Users/arx/Library/Android/sdk/ndk/28.0.13004108/toolchains/llvm/prebuilt/darwin-x86_64/bin'))
    android_cc, nm = ndk / 'aarch64-linux-android28-clang', ndk / 'llvm-nm'
    audit = []
    for mode, defines in (('gles', ['-DWMMT_EGL']), ('vkcompat', ['-DWMMT_EGL', '-DWMMT_VK']),
                          ('vkcompat-noegl', ['-DWMMT_VK']), ('native', ['-DWMMT_EGL', '-DWMMT_VK', '-DWMMT_NATIVE_VK'])):
        command = [str(android_cc), '-std=gnu11', '-O2', '-fPIC', '-Wall', '-Wextra', '-Werror',
                   '-Wno-unused-function', '-Wno-unused-parameter', '-Wno-missing-field-initializers',
                   '-DRC_FPT=double', '-mcpu=cortex-a73', '-I', str(ROOT / 'src'), *defines, '-x', 'c']
        tokens, objects = {}, {}
        for label, data in [('current', INPUTS['src/main_android.c'])] + ([] if mode == 'native' else [('baseline', BASE)]):
            token = subprocess.run([*command, '-E', '-P', '-'], input=data, check=True, capture_output=True, timeout=60).stdout
            tokens[label] = H(b'\0'.join(re.findall(rb'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\w+|[^\s]', token)))
            obj = work / (mode + '-' + label + '.o')
            subprocess.run([*command, '-c', '-', '-o', str(obj)], input=data, check=True, capture_output=True, timeout=60)
            objects[label] = H(obj.read_bytes())
            if mode == 'native':
                imports = subprocess.check_output([str(nm), '--undefined-only', str(obj)], text=True)
                assert not re.search(r'\b(?:vkgl_\w+|gl[A-Z]\w*|eglGetProcAddress)\b', imports), imports
                (OUT / 'native-android-imports.txt').write_text(imports)
        if mode != 'native':
            assert tokens['current'] == tokens['baseline'] and objects['current'] == objects['baseline'], mode
        if mode in ('gles', 'vkcompat', 'vkcompat-noegl', 'native'):
            obj = work / ('core-' + mode + '.o')
            subprocess.run([*command, '-c', str(ROOT / 'src/vkgl.c'), '-o', str(obj)], check=True, capture_output=True, timeout=120)
        audit.append({'mode': mode, 'tokens': tokens, 'objects': objects, 'full_android_compile': True,
                      'full_core_compile': True, 'legacy_exact': mode != 'native'})
    print('PASS strict NDK full Android all modes + full Vk core compat/native; 3 legacy complete token/O2-object controls exact; native Android zero GL/vkgl/extension imports')
for name, data in INPUTS.items():
    assert (ROOT / name).read_bytes() == data, 'source changed while testing: ' + name
report = {'status': 'pass', 'source_sha256': {n: H(b) for n, b in INPUTS.items()},
          'baseline': {'path': str(base), 'sha256': H(BASE)}, 'results': results, 'ndk_audit': audit,
          'selected_actual_function_sha256': {n: H(b.encode()) for n, b in shared.items()},
          'sanitizer': 'undefined', 'gpu_runtime_verified': False, 'android_runtime_verified': False,
          'mocked_boundaries': ['image allocation/view (actual render-pass and compatibility/cache publication chain tested)', 'replay operation encoding',
                                'image destruction effects (actual retirement queue/leases/watermark tested)', 'Vulkan/OS calls',
                                'loader_flush boundary; actual lease lifecycle remains in existing loader/image suites'],
          'limits': ['process-lifetime device; no destroy/recreate/device-lost recovery', 'one frame owner/designated loader, not arbitrary public-table concurrency',
                     'not whole-library GL-free: compatibility exports and shared replay GL-bit bookkeeping remain',
                     'surface release uses common unextended-WSI device-idle fallback; this does not prove presentation-engine resource retirement (maintenance1 present fences not negotiated)',
                     'mock semaphore destruction after idle validates exact CPU ownership only, not strict WSI/GPU teardown completion']}
(OUT / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS source freeze and explicit mocked/live authority limits:', OUT / 'results.json')
