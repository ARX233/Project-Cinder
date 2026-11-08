#!/usr/bin/env python3
"""Actual immutable-image include + actual constructor/view/ring/lease/flush helpers.
Only Vulkan, memory and bounded public table boundaries are mocked; no GL/context,
VAO or texture-unit declarations. CPU sanitizer evidence, NOT GPU pixels/driver proof.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('CINDER_TEST_OUT', os.environ.get('TMPDIR', tempfile.gettempdir()))).resolve() / 'round4-images'
OUT.mkdir(parents=True, exist_ok=True)
CORE = (ROOT / 'src/vkgl.c').read_text()
NATIVE = (ROOT / 'src/native_vk.inc').read_text()
IMAGE = (ROOT / 'src/native_vk_images.inc').read_text()
assert not re.search(r'\b(?:ctx|cur_up|bound_tex|tex_format|image_settle|tex_view|vkgl_\w+)\s*\(', IMAGE)
assert 'GLenum' not in IMAGE and 'COLOR_ATTACHMENT' not in IMAGE


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


def schema(name):
    end = CORE.index('} ' + name + ';') + len('} ' + name + ';')
    start = CORE.rfind('typedef struct', 0, end)
    return CORE[start:end] + '\n'


prefix = r'''
#include <assert.h>
#include <limits.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "native_vk.h"
static int platform_native_profile = 1;
#define H(T,x) ((T)(uintptr_t)(x))
#define USAGE (VK_IMAGE_USAGE_SAMPLED_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT)
typedef struct { int block; VkDeviceSize off,size; } vmem;
'''
state = r'''
typedef struct {int used;vimg*im;cinder_vk_sampler native_sampler;}vtex;
static struct {VkDevice dev;VkPhysicalDevice pd;VkPhysicalDeviceProperties props;int aniso,astc;float max_aniso;
 VkFormat f4444,f5551;VkComponentMapping sw4444,sw5551;int conv5551;uint32_t lazy_type,uid;
 _Atomic uint64_t serial;pthread_mutex_t lock;}D={.lock=PTHREAD_MUTEX_INITIALIZER};
static struct{uploader up;} frame,*F=&frame;
static uploader LOADER_UP;
static const VkComponentMapping SWZ_ID={VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY};
static struct{VkDeviceMemory mem;uint8_t*map;VkDeviceSize size;int live;}blocks[1024];
static struct{VkDeviceSize size;int block,live;}buffers[1024];
static struct{int live;VkImageViewCreateInfo ci;}views[1024];
static struct{int live;VkImageCreateInfo ci;}images[1024];
static unsigned nm,nb,nv,ni,live_memory,live_buffers,live_views,live_images;
static unsigned errors,table_calls,commands,barriers,copies,begins,flushes,waits,queries,format_queries;
static int require_lease;
static unsigned calloc_calls,realloc_calls,calloc_fail_at,realloc_fail_at,stage_attempts,stage_fail_at;
static int image_fault,view_fail_at,view_null_at,buffer_fault,begin_fail,table_fail,lease_fail,native_loader_failed;
static VkResult end_result,submit_result,wait_result,fence_result,pool_result,query_result;
static VkFormatFeatureFlags features;
static VkImageFormatProperties caps;
static VkImageCreateFlags queried_flags;
static VkFormat queried_format;
static vtex textures[32];
static vimg **native_upload_images;static size_t n_native_upload_images,cap_native_upload_images;
static unsigned retired;static vimg*dead_images[64];static uint64_t dead_serials[64];
static void native_image_upload_complete(void);
static void logf_(const char*format,...){(void)format;}
#define VKCHECK(x) ((void)(x))
#define DEAD_IMAGE 1
static int native_reject(void){++errors;return 0;}
static vtex*tex_get(uint32_t id){return id<32&&textures[id].used?&textures[id]:NULL;}
static uint32_t tex_gen(void){++table_calls;if(table_fail)return 0;for(unsigned i=1;i<32;++i)if(!textures[i].used){textures[i]=(vtex){.used=1};return i;}return 0;}
static void tex_release(uint32_t id){assert(tex_get(id));textures[id]=(vtex){0};}
static void dead_add(int kind,void*p,uint64_t h,uint64_t serial){assert(kind==DEAD_IMAGE&&p&&!h&&retired<64);dead_images[retired]=p;dead_serials[retired++]=serial;}
static void fb_cache_forget(VkImageView view){assert(view);}
static void*test_calloc(size_t n,size_t size){if(++calloc_calls==calloc_fail_at)return NULL;return calloc(n,size);}
static void*test_realloc(void*p,size_t size){if(lease_fail||++realloc_calls==realloc_fail_at)return NULL;return realloc(p,size);}
static int mem_alloc(VkMemoryRequirements r,VkMemoryPropertyFlags want,VkMemoryPropertyFlags pref,int image,vmem*out){
 (void)pref;assert(r.size&&r.size<=1<<20&&nm+1<1024);
 if((image&&image_fault==2)||(!image&&buffer_fault==2))return -1;
 unsigned id=++nm;blocks[id].mem=H(VkDeviceMemory,id);blocks[id].size=r.size;blocks[id].live=1;
 blocks[id].map=image?NULL:malloc((size_t)r.size);assert(image||blocks[id].map);if(!image){assert(want==(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT));memset(blocks[id].map,0xcd,(size_t)r.size);}
 ++live_memory;*out=(vmem){(int)id,0,r.size};return 0;
}
static void mem_free(vmem*m){assert(m->block>0&&blocks[m->block].live);blocks[m->block].live=0;free(blocks[m->block].map);blocks[m->block].map=NULL;--live_memory;m->block=-1;}
static uint8_t*mem_map(const vmem*m){return buffer_fault==4?NULL:blocks[m->block].map;}
static VkResult fake_create_image(VkDevice dev,const VkImageCreateInfo*ci,const VkAllocationCallbacks*a,VkImage*out){
 (void)a;assert(dev&&ci->usage==USAGE&&ci->samples==VK_SAMPLE_COUNT_1_BIT&&ci->initialLayout==VK_IMAGE_LAYOUT_UNDEFINED);
 assert(queries&&queried_format==ci->format&&queried_flags==ci->flags);++ni;if(image_fault==1)return VK_ERROR_OUT_OF_HOST_MEMORY;
 images[ni].live=1;images[ni].ci=*ci;*out=H(VkImage,ni);++live_images;return VK_SUCCESS;
}
static void fake_image_requirements(VkDevice dev,VkImage image,VkMemoryRequirements*out){assert(dev&&images[(uintptr_t)image].live);*out=(VkMemoryRequirements){256,16,1};}
static VkResult fake_bind_image(VkDevice dev,VkImage image,VkDeviceMemory memory,VkDeviceSize offset){assert(dev&&image&&memory&&!offset);return image_fault==3?VK_ERROR_MEMORY_MAP_FAILED:VK_SUCCESS;}
static void fake_destroy_image(VkDevice dev,VkImage image,const VkAllocationCallbacks*a){(void)a;assert(dev&&images[(uintptr_t)image].live);images[(uintptr_t)image].live=0;--live_images;}
static VkResult fake_view(VkDevice dev,const VkImageViewCreateInfo*ci,const VkAllocationCallbacks*a,VkImageView*out){
 (void)a;assert(dev&&ci->subresourceRange.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT&&ci->subresourceRange.baseMipLevel==0&&ci->subresourceRange.baseArrayLayer==0);
 unsigned id=++nv;views[id].ci=*ci;if((int)id==view_fail_at)return VK_ERROR_OUT_OF_HOST_MEMORY;if((int)id==view_null_at)return VK_SUCCESS;
 views[id].live=1;++live_views;*out=H(VkImageView,id);return VK_SUCCESS;
}
static void fake_destroy_view(VkDevice dev,VkImageView view,const VkAllocationCallbacks*a){(void)a;assert(dev&&views[(uintptr_t)view].live);views[(uintptr_t)view].live=0;--live_views;}
static VkResult fake_create_buffer(VkDevice dev,const VkBufferCreateInfo*ci,const VkAllocationCallbacks*a,VkBuffer*out){
 (void)a;assert(dev&&ci->usage==(VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT));++stage_attempts;
 if(stage_attempts==stage_fail_at||buffer_fault==1)return VK_ERROR_OUT_OF_HOST_MEMORY;
 unsigned id=++nb;assert(id<1024&&ci->size<=1<<20);buffers[id].size=ci->size;buffers[id].live=1;*out=H(VkBuffer,id);++live_buffers;return VK_SUCCESS;
}
static void fake_buffer_requirements(VkDevice dev,VkBuffer b,VkMemoryRequirements*out){assert(dev&&b);*out=(VkMemoryRequirements){buffers[(uintptr_t)b].size,16,1};}
static VkResult fake_bind_buffer(VkDevice dev,VkBuffer b,VkDeviceMemory memory,VkDeviceSize offset){assert(dev&&b&&memory&&!offset);buffers[(uintptr_t)b].block=(int)(uintptr_t)memory;return buffer_fault==3?VK_ERROR_MEMORY_MAP_FAILED:VK_SUCCESS;}
static void fake_destroy_buffer(VkDevice dev,VkBuffer b,const VkAllocationCallbacks*a){(void)a;assert(dev&&buffers[(uintptr_t)b].live);buffers[(uintptr_t)b].live=0;--live_buffers;}
static void fake_format(VkPhysicalDevice pd,VkFormat format,VkFormatProperties*out){assert(pd&&format);++format_queries;*out=(VkFormatProperties){.optimalTilingFeatures=features};}
static VkResult fake_query(VkPhysicalDevice pd,VkFormat format,VkImageType type,VkImageTiling tiling,VkImageUsageFlags usage,VkImageCreateFlags flags,VkImageFormatProperties*out){
 assert(pd&&type==VK_IMAGE_TYPE_2D&&tiling==VK_IMAGE_TILING_OPTIMAL&&usage==USAGE);++queries;queried_flags=flags;queried_format=format;*out=caps;return query_result;
}
static uint8_t*scrub;static size_t scrub_bytes;
static VkResult fake_begin(VkCommandBuffer cmd,const VkCommandBufferBeginInfo*info){assert(cmd&&info->flags==VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT);++begins;if(begin_fail)return VK_ERROR_INITIALIZATION_FAILED;if(scrub)memset(scrub,0xee,scrub_bytes);++commands;return VK_SUCCESS;}
static VkImageMemoryBarrier last_barrier;
static void fake_barrier(VkCommandBuffer cmd,VkPipelineStageFlags src,VkPipelineStageFlags dst,VkDependencyFlags flags,uint32_t nm_,const VkMemoryBarrier*mb,uint32_t nb_,const VkBufferMemoryBarrier*bb,uint32_t n,const VkImageMemoryBarrier*b){
 assert(cmd&&src==VK_PIPELINE_STAGE_ALL_COMMANDS_BIT&&dst==src&&!flags&&!nm_&&!mb&&!nb_&&!bb&&n==1);assert(b->subresourceRange.levelCount==1&&b->subresourceRange.layerCount==1);
 assert(b->subresourceRange.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT);assert((b->oldLayout==VK_IMAGE_LAYOUT_UNDEFINED&&b->newLayout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL)||(b->oldLayout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL&&b->newLayout==VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL));
 for(unsigned i=1;i<32;++i)if(textures[i].im)assert(textures[i].im->img!=b->image);
 if(require_lease){size_t matches=0;for(size_t i=0;i<n_native_upload_images;++i)if(native_upload_images[i]->img==b->image){assert(native_upload_images[i]->native_upload_pending&&!native_upload_images[i]->defined);++matches;}assert(matches==1);}
 assert(b->oldLayout==(barriers%2?VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL:VK_IMAGE_LAYOUT_UNDEFINED));assert(copies==(barriers+1)/2);
 last_barrier=*b;++barriers;
}
static struct {VkBufferImageCopy region;uint8_t bytes[8192];size_t size;} captured[186];
static void fake_copy(VkCommandBuffer cmd,VkBuffer buffer,VkImage image,VkImageLayout layout,uint32_t n,const VkBufferImageCopy*p){
 assert(cmd&&buffer&&image&&layout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL&&n==1&&copies<186);
 const VkImageCreateInfo*ci=&images[(uintptr_t)image].ci;unsigned block=ci->format==VK_FORMAT_ASTC_4x4_UNORM_BLOCK?4:ci->format==VK_FORMAT_ASTC_6x6_UNORM_BLOCK?6:ci->format==VK_FORMAT_ASTC_8x8_UNORM_BLOCK?8:0;
 size_t bpp=ci->format==VK_FORMAT_R8G8B8A8_UNORM?4:ci->format==VK_FORMAT_R8_UNORM?1:2;
 size_t size=block?((p->imageExtent.width+block-1)/block)*((p->imageExtent.height+block-1)/block)*16:(size_t)p->imageExtent.width*p->imageExtent.height*bpp;
 assert(size<=sizeof captured[0].bytes&&!p->bufferRowLength&&!p->bufferImageHeight&&p->imageExtent.depth==1&&!p->imageOffset.x&&!p->imageOffset.y&&!p->imageOffset.z);
 assert(p->imageSubresource.mipLevel==last_barrier.subresourceRange.baseMipLevel&&p->imageSubresource.baseArrayLayer==last_barrier.subresourceRange.baseArrayLayer&&p->imageSubresource.layerCount==1&&p->bufferOffset%16==0);
 assert(p->bufferOffset+size<=buffers[(uintptr_t)buffer].size);captured[copies].region=*p;captured[copies].size=size;
 memcpy(captured[copies].bytes,blocks[buffers[(uintptr_t)buffer].block].map+(size_t)p->bufferOffset,size);++copies;
}
static VkResult submit(VkCommandBuffer*cmd,uint32_t n,VkSemaphore wait,VkSemaphore signal,VkFence fence){assert(cmd&&*cmd&&n==1&&!wait&&!signal&&fence);++flushes;return submit_result;}
static VkResult fake_end(VkCommandBuffer cmd){assert(cmd);return end_result;}
static VkResult fake_wait(VkDevice dev,uint32_t n,const VkFence*f,VkBool32 all,uint64_t timeout){assert(dev&&n==1&&f&&*f&&all&&timeout==UINT64_MAX);++waits;return wait_result;}
static VkResult fake_fence_reset(VkDevice dev,uint32_t n,const VkFence*f){assert(dev&&n==1&&f&&*f);return fence_result;}
static VkResult fake_pool_reset(VkDevice dev,VkCommandPool pool,VkCommandPoolResetFlags flags){assert(dev&&pool&&!flags);return pool_result;}
#define calloc test_calloc
#define realloc test_realloc
#define vkCreateImage fake_create_image
#define vkGetImageMemoryRequirements fake_image_requirements
#define vkBindImageMemory fake_bind_image
#define vkDestroyImage fake_destroy_image
#define vkCreateImageView fake_view
#define vkDestroyImageView fake_destroy_view
#define vkCreateBuffer fake_create_buffer
#define vkGetBufferMemoryRequirements fake_buffer_requirements
#define vkBindBufferMemory fake_bind_buffer
#define vkDestroyBuffer fake_destroy_buffer
#define vkGetPhysicalDeviceFormatProperties fake_format
#define vkGetPhysicalDeviceImageFormatProperties fake_query
#define vkBeginCommandBuffer fake_begin
#define vkCmdPipelineBarrier fake_barrier
#define vkCmdCopyBufferToImage fake_copy
#define vkEndCommandBuffer fake_end
#define vkWaitForFences fake_wait
#define vkResetFences fake_fence_reset
#define vkResetCommandPool fake_pool_reset
'''

anchors = [
    'static uint32_t resource_uid_next(', 'static int is_depth(', 'static int has_stencil(',
    'static VkResult view_try(', 'static vimg *image_new_usage(', 'static vimg *image_new(',
    'static void image_free_now(', 'static vbufmem *bufmem_try_new(', 'static void bufmem_free(',
    'static VkFormatProperties fmt_props(', 'static int fmt_has(', 'static int full_levels(',
    'static int native_image_upload_hold(', 'static void image_drop(',
    'static void native_image_upload_complete(', 'static void ring_reset(',
    'static void loader_flush(', 'static void barrier(',
]
actual = ''.join(fun(CORE, a) for a in anchors) + fun(NATIVE, 'static int native_sampler_valid(')

tests = r'''
static cinder_vk_sampler sampler(void){return(cinder_vk_sampler){.use_state=1,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_LINEAR,.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_LINEAR,.address_u=VK_SAMPLER_ADDRESS_MODE_REPEAT,.address_v=VK_SAMPLER_ADDRESS_MODE_REPEAT,.anisotropy=4};}
static cinder_vk_texture_desc make_desc(cinder_vk_texture_subresource*s,cinder_vk_texture_format f,int w,int h,int levels,int layers){return(cinder_vk_texture_desc){w,h,levels,layers,f,sampler(),s,(size_t)levels*layers};}
static void free_ring(ring*r){for(size_t i=0;i<r->n;++i)bufmem_free(r->b[i]);free(r->b);*r=(ring){0};}
static void reset(void){
 F=&frame;native_image_upload_complete();for(unsigned i=1;i<32;++i)if(textures[i].im){image_free_now(textures[i].im);textures[i]=(vtex){0};}
 for(unsigned i=0;i<retired;++i)image_free_now(dead_images[i]);retired=0;free_ring(&frame.up.stage);free_ring(&LOADER_UP.stage);
 free(native_upload_images);native_upload_images=NULL;n_native_upload_images=cap_native_upload_images=0;
 assert(!live_memory&&!live_images&&!live_buffers&&!live_views);memset(textures,0,sizeof textures);memset(blocks,0,sizeof blocks);memset(buffers,0,sizeof buffers);memset(views,0,sizeof views);memset(images,0,sizeof images);
 nm=nb=nv=ni=errors=table_calls=commands=barriers=copies=begins=flushes=waits=queries=format_queries=0;
 calloc_calls=realloc_calls=calloc_fail_at=realloc_fail_at=stage_attempts=stage_fail_at=0;image_fault=view_fail_at=view_null_at=buffer_fault=begin_fail=table_fail=lease_fail=native_loader_failed=0;
 end_result=submit_result=wait_result=fence_result=pool_result=query_result=VK_SUCCESS;
 D.dev=H(VkDevice,1);D.pd=H(VkPhysicalDevice,2);D.props.limits.maxImageDimension2D=4096;D.props.limits.maxImageDimensionCube=4096;D.f4444=VK_FORMAT_R4G4B4A4_UNORM_PACK16;D.f5551=VK_FORMAT_R5G5B5A1_UNORM_PACK16;D.sw4444=D.sw5551=SWZ_ID;D.conv5551=0;D.astc=D.aniso=1;D.max_aniso=16;D.lazy_type=~0u;D.uid=0;D.serial=19;
 caps=(VkImageFormatProperties){.maxExtent={4096,4096,1},.maxMipLevels=31,.maxArrayLayers=6,.sampleCounts=VK_SAMPLE_COUNT_1_BIT,.maxResourceSize=UINT64_MAX};
 features=VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT|VK_FORMAT_FEATURE_TRANSFER_SRC_BIT|VK_FORMAT_FEATURE_TRANSFER_DST_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
 frame.up=(uploader){.pool=H(VkCommandPool,1),.cmd=H(VkCommandBuffer,2),.fence=H(VkFence,5)};LOADER_UP=(uploader){.pool=H(VkCommandPool,3),.cmd=H(VkCommandBuffer,4),.fence=H(VkFence,6)};
 frame.up.stage.chunk=LOADER_UP.stage.chunk=256;frame.up.stage.usage=LOADER_UP.stage.usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT;
 scrub=NULL;scrub_bytes=0;require_lease=0;assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_FRAME));
}
static void verify_image(uint32_t id,int levels,int layers,VkFormat format){
 assert(id&&tex_get(id)&&tex_get(id)->im);vimg*im=tex_get(id)->im;assert(im->fmt==format&&im->levels==levels&&im->layers==layers&&im->view_levels==levels&&im->level_mask==((1u<<levels)-1)&&im->in_rest&&im->defined&&im->usage==USAGE&&!im->att);
 assert(live_views==1&&live_images==1&&views[(uintptr_t)im->view].ci.subresourceRange.levelCount==(uint32_t)levels&&views[(uintptr_t)im->view].ci.subresourceRange.layerCount==(uint32_t)layers);
 assert(views[(uintptr_t)im->view].ci.viewType==(layers==6?VK_IMAGE_VIEW_TYPE_CUBE:VK_IMAGE_VIEW_TYPE_2D));assert(copies==(unsigned)(levels*layers)&&barriers==2*copies&&!errors);
}
static void formats(void){
 const VkFormat expected[]={VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_R5G6B5_UNORM_PACK16,VK_FORMAT_R4G4B4A4_UNORM_PACK16,VK_FORMAT_R5G5B5A1_UNORM_PACK16,VK_FORMAT_R8_UNORM,VK_FORMAT_R8G8_UNORM,VK_FORMAT_R8_UNORM,VK_FORMAT_ASTC_4x4_UNORM_BLOCK,VK_FORMAT_ASTC_6x6_UNORM_BLOCK,VK_FORMAT_ASTC_8x8_UNORM_BLOCK};
 for(int f=0;f<11;++f){reset();unsigned bpp=f==0?4:f==1?3:f==5||f==7?1:2;int compressed=f>=8;unsigned bw=f==8?4:f==9?6:8;int w=compressed?(int)bw+1:3,h=compressed?(int)bw+2:2;
 size_t row=compressed?32:(size_t)w*bpp,rows=compressed?2:(size_t)h,stride=row+3,span=(rows-1)*stride+row;uint8_t*source=malloc(span+1);assert(source);for(size_t i=0;i<span+1;++i)source[i]=(uint8_t)(i*7+3);
 uint8_t expected_bytes[512];size_t written=0;for(size_t y=0;y<rows;++y)for(size_t x=0;x<row;++x){expected_bytes[written++]=source[1+y*stride+x];if(f==1&&x%3==2)expected_bytes[written++]=255;}
 cinder_vk_texture_subresource s={0,0,source+1,span,stride};cinder_vk_texture_desc d=make_desc(&s,(cinder_vk_texture_format)f,w,h,1,1);scrub=source;scrub_bytes=span+1;
 uint32_t id=cinder_vk_texture_create(&d);free(source);scrub=NULL;verify_image(id,1,1,expected[f]);assert(captured[0].size==written&&!memcmp(captured[0].bytes,expected_bytes,written));
 VkComponentMapping sw=tex_get(id)->im->swz;if(f==1)assert(sw.a==VK_COMPONENT_SWIZZLE_ONE);if(f==5||f==6)assert(sw.r==VK_COMPONENT_SWIZZLE_R&&sw.g==sw.r&&sw.b==sw.r&&sw.a==(f==5?VK_COMPONENT_SWIZZLE_ONE:VK_COMPONENT_SWIZZLE_G));if(f==7)assert(sw.r==VK_COMPONENT_SWIZZLE_ZERO&&sw.g==sw.r&&sw.b==sw.r&&sw.a==VK_COMPONENT_SWIZZLE_R);
 }
 reset();uint8_t raw[12]={0};uint16_t values[]={0x0001,0xf801,0x07c0,0xffff};for(int i=0;i<4;++i)memcpy(raw+1+(i/2)*5+(i%2)*2,&values[i],2);
 D.f5551=VK_FORMAT_A1R5G5B5_UNORM_PACK16;D.conv5551=1;cinder_vk_texture_subresource s={0,0,raw+1,9,5};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGBA5551,2,2,1,1);uint32_t id=cinder_vk_texture_create(&d);verify_image(id,1,1,D.f5551);
 for(int i=0;i<4;++i){uint16_t value;memcpy(&value,captured[0].bytes+2*i,2);assert(value==(uint16_t)((values[i]>>1)|((values[i]&1u)<<15)));}
 for(int f=3;f<=4;++f){reset();VkComponentMapping sw={VK_COMPONENT_SWIZZLE_B,VK_COMPONENT_SWIZZLE_G,VK_COMPONENT_SWIZZLE_R,VK_COMPONENT_SWIZZLE_A};if(f==3){D.f4444=VK_FORMAT_B4G4R4A4_UNORM_PACK16;D.sw4444=sw;}else{D.f5551=VK_FORMAT_B5G5R5A1_UNORM_PACK16;D.sw5551=sw;}d=make_desc(&s,(cinder_vk_texture_format)f,2,2,1,1);id=cinder_vk_texture_create(&d);assert(id&&!memcmp(&tex_get(id)->im->swz,&sw,sizeof sw));}
 reset();puts("PASS all 11 formats: exact tight staging/no tail-pad reads, odd stride+unaligned 5551 rotation, packed device fallback and L/LA/A swizzles; CPU input scrubbed before begin");
}
static void mipchains(void){
 for(int cube=0;cube<2;++cube){reset();uint8_t data[6][3][128];cinder_vk_texture_subresource s[18];int layers=cube?6:1;size_t count=(size_t)layers*3;
 for(size_t i=0;i<count;++i){unsigned face=(unsigned)(i/3),level=(unsigned)(i%3);size_t bytes=(size_t)(4>>level)*(4>>level)*2;memset(data[face][level],(int)(face*17+level),bytes);s[count-1-i]=(cinder_vk_texture_subresource){level,face,data[face][level],bytes,0};}
 cinder_vk_texture_desc d=make_desc(s,CINDER_VK_TEX_RGB565,4,4,3,layers);d.sampler.mipmaps=1;scrub=(uint8_t*)data;scrub_bytes=sizeof data;uint32_t id=cinder_vk_texture_create(&d);scrub=NULL;verify_image(id,3,layers,VK_FORMAT_R5G6B5_UNORM_PACK16);assert(nv==2&&!views[1].live);
 for(size_t i=0;i<count;++i){unsigned face=(unsigned)(i/3),level=(unsigned)(i%3);assert(captured[i].region.imageSubresource.mipLevel==level&&captured[i].region.imageSubresource.baseArrayLayer==face&&captured[i].region.imageExtent.width==(4u>>level)&&captured[i].bytes[0]==face*17+level);}
 }
 reset();uint8_t narrow[4]={1,2,3,4};cinder_vk_texture_subresource narrow_s[3]={{0,0,narrow,4,0},{1,0,narrow,2,0},{2,0,narrow,1,0}};cinder_vk_texture_desc narrow_d=make_desc(narrow_s,CINDER_VK_TEX_L8,1,4,3,1);verify_image(cinder_vk_texture_create(&narrow_d),3,1,VK_FORMAT_R8_UNORM);for(int level=0;level<3;++level)assert(captured[level].region.imageExtent.width==1&&captured[level].region.imageExtent.height==(4u>>level));
 for(int f=8;f<11;++f){reset();uint8_t data[16]={0};cinder_vk_texture_subresource s={0,0,data,16,0};cinder_vk_texture_desc d=make_desc(&s,(cinder_vk_texture_format)f,1,1,1,1);assert(cinder_vk_texture_create(&d)&&captured[0].size==16&&captured[0].region.imageExtent.width==1);}
 reset();uint16_t single=0;cinder_vk_texture_subresource single_s={0,0,&single,2,0};cinder_vk_texture_desc single_d=make_desc(&single_s,CINDER_VK_TEX_RGB565,1,1,1,1);single_d.sampler.mipmaps=1;verify_image(cinder_vk_texture_create(&single_d),1,1,VK_FORMAT_R5G6B5_UNORM_PACK16);
 reset();puts("PASS RGB565 full mipchain/cube6 unordered inputs, full sampled views and immediate old-view cleanup; nomip complete multilevel + mip-enabled 1x1; ASTC 4/6/8 tiny/nonsquare extents");
}
#define BAD(change) do{reset();uint8_t data[64]={0};cinder_vk_texture_subresource s[2]={{0,0,data,16,0},{1,0,data,4,0}};cinder_vk_texture_desc d=make_desc(s,CINDER_VK_TEX_RGBA8,2,2,1,1);change;assert(!cinder_vk_texture_create(&d)&&errors==1&&!ni&&!nb&&!table_calls&&!begins&&!barriers&&!copies&&!live_images);}while(0)
static void invalid(void){
 reset();assert(!cinder_vk_texture_create(NULL)&&errors==1&&!ni);
 BAD(d.width=0);BAD(d.height=-1);BAD(d.levels=0);BAD(d.levels=32);BAD(d.levels=3);BAD(d.layers=2);BAD(d.layers=6;d.width=1;d.subresource_count=6);
 BAD(d.subresources=NULL);BAD(d.subresource_count=0);BAD(d.subresource_count=2);BAD(d.levels=2;d.subresource_count=2;s[1].level=0);BAD(s[0].level=1);BAD(s[0].layer=1);BAD(s[0].data=NULL);BAD(s[0].bytes=15);BAD(s[0].row_stride=7);BAD(s[0].row_stride=SIZE_MAX);BAD(s[0].data=(void*)(UINTPTR_MAX-2));
 BAD(d.format=(cinder_vk_texture_format)-1);BAD(d.format=(cinder_vk_texture_format)11);BAD(d.sampler.use_state=0);BAD(d.sampler.use_state=2);BAD(d.sampler.anisotropy=NAN);BAD(d.sampler.min_filter=(VkFilter)-1);BAD(d.sampler.mipmaps=2);BAD(d.sampler.address_v=(VkSamplerAddressMode)-1);
 BAD(d.width=INT_MAX;d.height=INT_MAX;s[0].bytes=SIZE_MAX);BAD(D.dev=VK_NULL_HANDLE);BAD(D.pd=VK_NULL_HANDLE);BAD(F=NULL);BAD(frame.up.pool=VK_NULL_HANDLE);BAD(D.props.limits.maxImageDimension2D=1);
 BAD(features&=~VK_FORMAT_FEATURE_TRANSFER_SRC_BIT);BAD(features&=~VK_FORMAT_FEATURE_TRANSFER_DST_BIT);BAD(features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT);BAD(features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT);
 BAD(caps.maxExtent.width=1);BAD(caps.maxExtent.height=1);BAD(caps.maxExtent.depth=0);BAD(caps.maxMipLevels=0);BAD(caps.maxArrayLayers=0);BAD(caps.sampleCounts=VK_SAMPLE_COUNT_4_BIT);BAD(caps.maxResourceSize=15);BAD(query_result=VK_ERROR_FORMAT_NOT_SUPPORTED);
 BAD(D.astc=0;d.format=CINDER_VK_TEX_ASTC_4x4);BAD(D.f4444=VK_FORMAT_UNDEFINED;d.format=CINDER_VK_TEX_RGBA4444);
 reset();uint8_t data[64]={0};cinder_vk_texture_subresource s={0,0,data,16,0};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGBA8,2,2,1,1);d.sampler.min_filter=d.sampler.mag_filter=VK_FILTER_NEAREST;features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;assert(cinder_vk_texture_create(&d));
 reset();s.row_stride=9;s.bytes=17;d=make_desc(&s,CINDER_VK_TEX_RGBA8,2,2,1,1);assert(cinder_vk_texture_create(&d));reset();s.bytes=16;assert(!cinder_vk_texture_create(&d)&&!ni); /* no assumed final row padding */
 for(int fault=0;fault<4;++fault){reset();cinder_vk_texture_subresource cube[12];for(int i=0;i<12;++i)cube[i]=(cinder_vk_texture_subresource){(uint32_t)(i%2),(uint32_t)(i/2),data,(size_t)(i%2?4:16),0};d=make_desc(cube,CINDER_VK_TEX_RGBA8,2,2,2,6);if(fault==0)D.props.limits.maxImageDimensionCube=1;if(fault==1)caps.maxArrayLayers=5;if(fault==2)caps.maxMipLevels=1;if(fault==3)query_result=VK_ERROR_FORMAT_NOT_SUPPORTED;assert(!cinder_vk_texture_create(&d)&&!ni&&!nb&&!table_calls&&!begins&&!barriers);if(fault)assert(queried_flags==VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT);}
 reset();s=(cinder_vk_texture_subresource){0,0,data,16,0};d=make_desc(&s,CINDER_VK_TEX_RGBA8,2,2,1,1);d.sampler.min_filter=d.sampler.mag_filter=VK_FILTER_NEAREST;d.sampler.mipmaps=1;features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;assert(!cinder_vk_texture_create(&d)&&!ni);
 reset();puts("PASS malformed/NULL/duplicate/missing/out-of-range/overflow/row spans and feature+image capability negatives (cube flags/limits, mip-linear) reject before allocation/commands/table");
}
static void allocation_failures(void){
 for(int fault=0;fault<15;++fault){reset();uint8_t data[16]={0};cinder_vk_texture_subresource s[2]={{0,0,data,16,0},{1,0,data,4,0}};cinder_vk_texture_desc d=make_desc(s,CINDER_VK_TEX_RGBA8,2,2,2,1);
 switch(fault){case 0:calloc_fail_at=1;break;case 1:image_fault=1;break;case 2:image_fault=2;break;case 3:image_fault=3;break;case 4:view_fail_at=1;break;case 5:view_fail_at=2;break;case 6:view_null_at=2;break;case 7:buffer_fault=1;break;case 8:buffer_fault=2;break;case 9:buffer_fault=3;break;case 10:buffer_fault=4;break;case 11:realloc_fail_at=1;break;case 12:table_fail=1;break;case 13:begin_fail=1;break;case 14:calloc_fail_at=2;break;}
 assert(!cinder_vk_texture_create(&d)&&errors==1&&!barriers&&!copies&&!live_images&&!live_views&&!tex_get(1));}
 reset();uint8_t data[32]={0};cinder_vk_texture_subresource s[2]={{0,0,data,32,0},{1,0,data,8,0}};cinder_vk_texture_desc d=make_desc(s,CINDER_VK_TEX_RGB565,4,4,2,1);frame.up.stage.chunk=1;stage_fail_at=2;assert(!cinder_vk_texture_create(&d)&&stage_attempts==2&&!table_calls&&!begins&&!barriers&&!copies&&!live_images);
 reset();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));lease_fail=1;LOADER_UP.stage.cap=64;LOADER_UP.stage.b=calloc(64,sizeof *LOADER_UP.stage.b);assert(LOADER_UP.stage.b);assert(!cinder_vk_texture_create(&d)&&errors==1&&begins==1&&!barriers&&!copies&&!live_images&&!n_native_upload_images&&!tex_get(1));
 reset();D.uid=UINT32_MAX;assert(!cinder_vk_texture_create(&d)&&!live_images&&!live_views&&ni==1&&!table_calls&&!begins);
 reset();puts("PASS actual constructor/view/staging/bind/map/realloc/begin/lease/table exhaustion faults: no image commands/publication; full cleanup; second staging-span failure before commands");
}
static void precommand_transactions(void){
 for(int fault=0;fault<5;++fault){
  reset();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));require_lease=1;LOADER_UP.stage.chunk=32;
  uint8_t prefix_data[2]={0x5a,0x7b};uint32_t prefix_id=0;vimg*prefix_image=NULL;VkBuffer prefix_buffer;VkDeviceSize prefix_offset;uint8_t*prefix;
  if(fault==1||fault==4){prefix=native_ring_alloc(&LOADER_UP.stage,2,16,&prefix_buffer,&prefix_offset);assert(prefix);memcpy(prefix,prefix_data,2);}
  else {cinder_vk_texture_subresource slice={0,0,prefix_data,2,0};cinder_vk_texture_desc first=make_desc(&slice,CINDER_VK_TEX_RGB565,1,1,1,1);prefix_id=cinder_vk_texture_create(&first);assert(prefix_id&&n_native_upload_images==1);prefix_image=tex_get(prefix_id)->im;prefix=LOADER_UP.stage.b[0]->map;}
  ring*r=&LOADER_UP.stage;size_t start_i=r->i,start_n=r->n;VkDeviceSize start_used=r->used;unsigned start_copies=copies,start_barriers=barriers;size_t prefix_leases=n_native_upload_images;
  uint8_t pixels[32];memset(pixels,0x31,sizeof pixels);cinder_vk_texture_subresource slices[2]={{0,0,pixels,32,0},{1,0,pixels,8,0}};cinder_vk_texture_desc d=make_desc(slices,CINDER_VK_TEX_RGB565,4,4,2,1);
  if(fault==0||fault==4)stage_fail_at=stage_attempts+2;
  if(fault==1)begin_fail=1;
  if(fault==2){cap_native_upload_images=n_native_upload_images;lease_fail=1;}
  if(fault==3)table_fail=1;
  assert(!cinder_vk_texture_create(&d)&&!native_loader_failed&&copies==start_copies&&barriers==start_barriers&&r->i==start_i&&r->used==start_used&&r->n>start_n&&!memcmp(prefix,prefix_data,2));
  assert(n_native_upload_images==prefix_leases&&(!prefix_id||tex_get(prefix_id)->im==prefix_image));if(prefix_image)assert(prefix_image->native_upload_pending&&!prefix_image->native_retire_pending);
  if(fault==4){assert(!LOADER_UP.open&&!n_native_upload_images);loader_flush();assert(!flushes&&r->i==start_i&&r->used==start_used);}
  size_t retained_n=r->n;unsigned retained_buffers=nb;
  for(int retry=0;retry<4;++retry){if(fault==0||fault==4)stage_fail_at=stage_attempts+1;assert(!cinder_vk_texture_create(&d)&&r->i==start_i&&r->used==start_used&&r->n==retained_n&&nb==retained_buffers&&copies==start_copies&&barriers==start_barriers&&!memcmp(prefix,prefix_data,2)&&n_native_upload_images==prefix_leases);}
  stage_fail_at=0;begin_fail=lease_fail=table_fail=0;uint32_t id=cinder_vk_texture_create(&d);assert(id&&id!=prefix_id&&copies==start_copies+2&&barriers==start_barriers+4&&r->i==2&&r->used==8&&r->n==3&&!memcmp(prefix,prefix_data,2)&&n_native_upload_images==prefix_leases+1);
  assert(!memcmp(captured[start_copies].bytes,pixels,32)&&!memcmp(captured[start_copies+1].bytes,pixels,8));if(fault==0||fault==4)assert(nb==retained_buffers+1);else assert(nb==retained_buffers);
 }
 reset();puts("PASS pre-command staging transactions: second-span OOM/table/begin/lease failures restore only i/used; closed-loader no-op flush/repeated failures/retry reuse retained backings and preserve existing bytes/public pending image leases");
}
static void capabilities(void){
 reset();for(int f=0;f<11;++f)assert(cinder_vk_texture_format_supported((cinder_vk_texture_format)f));assert(!cinder_vk_texture_format_supported((cinder_vk_texture_format)-1));assert(!errors&&!ni&&!nb&&!table_calls&&!begins&&!barriers);assert(cinder_vk_anisotropy_limit()==16);
 D.aniso=0;assert(cinder_vk_anisotropy_limit()==1);D.aniso=1;D.max_aniso=NAN;assert(cinder_vk_anisotropy_limit()==1);D.max_aniso=INFINITY;assert(cinder_vk_anisotropy_limit()==1);D.max_aniso=.5f;assert(cinder_vk_anisotropy_limit()==1);D.max_aniso=8;assert(cinder_vk_anisotropy_limit()==8);
 D.astc=0;assert(!cinder_vk_texture_format_supported(CINDER_VK_TEX_ASTC_4x4));D.astc=1;features&=~VK_FORMAT_FEATURE_TRANSFER_SRC_BIT;assert(!cinder_vk_texture_format_supported(CINDER_VK_TEX_RGBA8));features|=VK_FORMAT_FEATURE_TRANSFER_SRC_BIT;query_result=VK_ERROR_FORMAT_NOT_SUPPORTED;assert(!cinder_vk_texture_format_supported(CINDER_VK_TEX_RGBA8));query_result=VK_SUCCESS;caps.sampleCounts=0;assert(!cinder_vk_texture_format_supported(CINDER_VK_TEX_RGBA8));caps.sampleCounts=1;caps.maxExtent.width=0;assert(!cinder_vk_texture_format_supported(CINDER_VK_TEX_RGBA8));assert(!errors&&!ni&&!table_calls&&!begins);
 reset();puts("PASS capability-only all-format/ASTC/usage/image-property queries and enabled finite anisotropy limits: no GL state, allocation or commands");
}
static void loader(void){
 reset();uint8_t data[32]={0};cinder_vk_texture_subresource s[2]={{0,0,data,32,0},{1,0,data,8,0}};cinder_vk_texture_desc d=make_desc(s,CINDER_VK_TEX_RGB565,4,4,2,1);
 assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));require_lease=1;F=NULL;uint32_t id=cinder_vk_texture_create(&d);assert(id&&n_native_upload_images==1&&tex_get(id)->im->native_upload_pending);vimg*im=tex_get(id)->im;
 cinder_vk_texture_destroy(id);assert(!tex_get(id)&&!retired&&live_images==1&&im->native_retire_pending);D.serial=27;assert(!retired);loader_flush();assert(!native_loader_failed&&!n_native_upload_images&&retired==1&&dead_images[0]==im&&dead_serials[0]==27&&live_images==1);
 for(int fault=0;fault<5;++fault){reset();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));require_lease=1;LOADER_UP.stage.chunk=1;
 /* A cube mipchain makes six+ separate buffers: auto-flush happens only after every command and one lease. */
 cinder_vk_texture_subresource cube[6];for(int i=0;i<6;++i)cube[i]=(cinder_vk_texture_subresource){0,(uint32_t)i,data,2,0};d=make_desc(cube,CINDER_VK_TEX_RGB565,1,1,1,6);
 switch(fault){case 0:end_result=VK_ERROR_DEVICE_LOST;break;case 1:submit_result=VK_ERROR_DEVICE_LOST;break;case 2:wait_result=VK_TIMEOUT;break;case 3:fence_result=VK_ERROR_DEVICE_LOST;break;case 4:pool_result=VK_ERROR_DEVICE_LOST;break;}
 assert(!cinder_vk_texture_create(&d)&&native_loader_failed&&!tex_get(1)&&errors==1&&live_images==1&&copies==6&&barriers==12);
 if(fault<3)assert(n_native_upload_images==1&&!retired&&native_upload_images[0]->native_retire_pending);else assert(!n_native_upload_images&&retired==1);if(fault<2)assert(!waits);
 /* Command-referenced spans must not be rolled back even on end/submit/wait
  * failure; the poisoned loader rejects retries without reusing these bytes. */
 assert(LOADER_UP.stage.n==6&&LOADER_UP.stage.i==5&&LOADER_UP.stage.used==2);uint8_t recorded[2];memcpy(recorded,data,2);memset(data,0xee,sizeof data);
 unsigned before=begins,before_stages=stage_attempts;assert(!cinder_vk_texture_create(&d)&&begins==before&&stage_attempts==before_stages&&live_images==1&&LOADER_UP.stage.n==6&&LOADER_UP.stage.i==5&&LOADER_UP.stage.used==2);
 for(size_t i=0;i<LOADER_UP.stage.n;++i)assert(!memcmp(LOADER_UP.stage.b[i]->map,recorded,2));
 }
 reset();puts("PASS actual single loader lease per multi-subresource object, delete/main-serial race pinning and end/submit/wait/reset auto-flush failures retaining unknown references/blocking new uploads");
}
int main(void){setvbuf(stdout,NULL,_IONBF,0);formats();mipchains();invalid();allocation_failures();precommand_transactions();capabilities();loader();reset();puts("native Vulkan immutable images: production CPU sanitizer PASS (NOT GPU pixels/validation)");return 0;}
'''

fixture = (prefix + ''.join(schema(n) for n in ('vbufmem', 'vimg', 'ring', 'uploader')) + state + actual +
           '\n#include "native_vk_upload.inc"\n#include "native_vk_resources.inc"\n#include "native_vk_images.inc"\n' + tests)
assert not re.search(r'\b(?:GLenum|GLuint|GLint|vctx|vvao)\b', fixture)
with tempfile.TemporaryDirectory(prefix='images-', dir=OUT) as directory:
    directory = Path(directory)
    (directory / 'images.c').write_text(fixture)
    flags = ['-I', str(ROOT / 'src')]
    if sys.platform == 'darwin':
        flags += ['-I', '/opt/homebrew/include']
    sanitizer = os.environ.get('NATIVE_VK_SANITIZERS', 'undefined' if sys.platform == 'darwin' else 'address,undefined')
    command = [os.environ.get('CC', 'clang'), '-std=gnu11', '-Wall', '-Wextra', '-Werror',
               '-Wno-missing-field-initializers', '-fsanitize=' + sanitizer, '-fno-sanitize-recover=all',
               '-fno-omit-frame-pointer', *flags, str(directory / 'images.c'), '-pthread', '-lm', '-o', str(directory / 'images')]
    subprocess.run(command, cwd=directory, check=True, timeout=120)
    subprocess.run([str(directory / 'images')], cwd=directory, check=True,
                   timeout=int(os.environ.get('NATIVE_VK_TEST_TIMEOUT', '30')))
    print('sanitizers', sanitizer)
for path in ('src/native_vk_images.inc', 'tests/test_native_vk_images_host.py', 'src/native_vk.h', 'src/vkgl.c',
             'src/native_vk_resources.inc', 'src/native_vk_upload.inc', 'src/native_vk.inc'):
    print(path, hashlib.sha256((ROOT / path).read_bytes()).hexdigest())
