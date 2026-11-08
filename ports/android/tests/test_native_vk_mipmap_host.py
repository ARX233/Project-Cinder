#!/usr/bin/env python3
"""Actual native GPU mip include and shared constructor/view/free/cache/upload helpers.
Vulkan, memory and bounded public tables are mocks. Blits are NOT executed: GPU
output bytes remain unknown. No GL context or ASan/TSan/concurrency claim.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('CINDER_TEST_OUT', os.environ.get('TMPDIR', tempfile.gettempdir()))).resolve() / 'round6-mipmap'
OUT.mkdir(parents=True, exist_ok=True)
CORE = (ROOT / 'src/vkgl.c').read_text()
NATIVE = (ROOT / 'src/native_vk.inc').read_text()
MIP = (ROOT / 'src/native_vk_mipmap.inc').read_text()
assert not re.search(r'\b(?:ctx|cur_up|bound_tex|tex_format|image_settle|tex_view|vkgl_\w+)\s*\(', MIP)
assert 'GLenum' not in MIP and 'COLOR_ATTACHMENT' not in MIP


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
static unsigned blits,events,fb_destroys;
static VkCommandBuffer active_cmd;
static VkImageLayout layouts[1024][31];static uint32_t content[1024];
static struct {char kind;unsigned level;VkImageLayout from,to;} event[8192];
static fbent fbs[8];static size_t n_fbs;
static void fb_cache_forget(VkImageView view);
static void fake_destroy_fb(VkDevice dev,VkFramebuffer fb,const VkAllocationCallbacks*a){(void)a;assert(dev&&fb);++fb_destroys;}
#define vkDestroyFramebuffer fake_destroy_fb

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
static VkResult fake_begin(VkCommandBuffer cmd,const VkCommandBufferBeginInfo*info){assert(cmd&&info->flags==VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT);++begins;if(begin_fail)return VK_ERROR_INITIALIZATION_FAILED;if(scrub)memset(scrub,0xee,scrub_bytes);++commands;active_cmd=cmd;return VK_SUCCESS;}
static VkImageMemoryBarrier last_barrier;
static void recording_check(VkCommandBuffer cmd,VkImage image){
 assert(cmd&&cmd==active_cmd&&images[(uintptr_t)image].live);
 const VkImageCreateInfo*ci=&images[(uintptr_t)image].ci;unsigned ready=0;
 for(unsigned i=1;i<=nv;++i)if(views[i].live&&views[i].ci.image==image){assert(views[i].ci.subresourceRange.levelCount==ci->mipLevels);++ready;}
 assert(ready==1);
 for(unsigned i=1;i<32;++i)if(textures[i].im)assert(textures[i].im->img!=image);
 if(require_lease){size_t matches=0;for(size_t i=0;i<n_native_upload_images;++i)if(native_upload_images[i]->img==image){assert(native_upload_images[i]->native_upload_pending&&!native_upload_images[i]->defined&&!native_upload_images[i]->in_rest&&!native_upload_images[i]->level_mask);++matches;}assert(matches==1);}
}
static void fake_barrier(VkCommandBuffer cmd,VkPipelineStageFlags src,VkPipelineStageFlags dst,VkDependencyFlags flags,uint32_t nm_,const VkMemoryBarrier*mb,uint32_t nb_,const VkBufferMemoryBarrier*bb,uint32_t n,const VkImageMemoryBarrier*b){
 recording_check(cmd,b->image);assert(src==VK_PIPELINE_STAGE_ALL_COMMANDS_BIT&&dst==src&&!flags&&!nm_&&!mb&&!nb_&&!bb&&n==1);
 const VkImageSubresourceRange*r=&b->subresourceRange;unsigned level=r->baseMipLevel;uintptr_t id=(uintptr_t)b->image;
 assert(level<images[id].ci.mipLevels&&r->levelCount==1&&r->layerCount==1&&!r->baseArrayLayer&&r->aspectMask==VK_IMAGE_ASPECT_COLOR_BIT);
 assert(b->srcQueueFamilyIndex==VK_QUEUE_FAMILY_IGNORED&&b->dstQueueFamilyIndex==VK_QUEUE_FAMILY_IGNORED);
 assert(layouts[id][level]==b->oldLayout);
 assert((b->oldLayout==VK_IMAGE_LAYOUT_UNDEFINED&&b->newLayout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL)||
        (b->oldLayout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL&&(b->newLayout==VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL||b->newLayout==VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL))||
        (b->oldLayout==VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL&&b->newLayout==VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL));
 if(b->oldLayout!=VK_IMAGE_LAYOUT_UNDEFINED)assert(content[id]&(1u<<level));
 layouts[id][level]=b->newLayout;assert(events<8192);event[events++]=(typeof(event[0])){'B',level,b->oldLayout,b->newLayout};
 last_barrier=*b;++barriers;
}
static struct {VkBufferImageCopy region;uint8_t bytes[8192];size_t size;} captured[186];
static void fake_copy(VkCommandBuffer cmd,VkBuffer buffer,VkImage image,VkImageLayout layout,uint32_t n,const VkBufferImageCopy*p){
 recording_check(cmd,image);assert(cmd&&buffer&&image&&layout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL&&n==1&&copies<186);
 const VkImageCreateInfo*ci=&images[(uintptr_t)image].ci;unsigned block=ci->format==VK_FORMAT_ASTC_4x4_UNORM_BLOCK?4:ci->format==VK_FORMAT_ASTC_6x6_UNORM_BLOCK?6:ci->format==VK_FORMAT_ASTC_8x8_UNORM_BLOCK?8:0;
 size_t bpp=ci->format==VK_FORMAT_R8G8B8A8_UNORM?4:ci->format==VK_FORMAT_R8_UNORM?1:2;
 size_t size=block?((p->imageExtent.width+block-1)/block)*((p->imageExtent.height+block-1)/block)*16:(size_t)p->imageExtent.width*p->imageExtent.height*bpp;
 assert(size<=sizeof captured[0].bytes&&!p->bufferRowLength&&!p->bufferImageHeight&&p->imageExtent.depth==1&&!p->imageOffset.x&&!p->imageOffset.y&&!p->imageOffset.z);
 assert(p->imageSubresource.mipLevel==last_barrier.subresourceRange.baseMipLevel&&p->imageSubresource.baseArrayLayer==last_barrier.subresourceRange.baseArrayLayer&&p->imageSubresource.layerCount==1&&p->bufferOffset%16==0);
 assert(p->bufferOffset+size<=buffers[(uintptr_t)buffer].size);captured[copies].region=*p;captured[copies].size=size;
 memcpy(captured[copies].bytes,blocks[buffers[(uintptr_t)buffer].block].map+(size_t)p->bufferOffset,size);
 assert(!p->imageSubresource.mipLevel&&!p->imageSubresource.baseArrayLayer&&!(content[(uintptr_t)image]&1));
 content[(uintptr_t)image]|=1;event[events++]=(typeof(event[0])){'C',0,0,0};++copies;
}
static void fake_blit(VkCommandBuffer cmd,VkImage src,VkImageLayout sl,VkImage dst,VkImageLayout dl,uint32_t n,const VkImageBlit*b,VkFilter filter){
 recording_check(cmd,src);assert(src==dst&&sl==VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL&&dl==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL&&n==1&&filter==VK_FILTER_LINEAR);
 unsigned previous=b->srcSubresource.mipLevel,level=b->dstSubresource.mipLevel;uintptr_t id=(uintptr_t)src;const VkImageCreateInfo*ci=&images[id].ci;
 assert(level==previous+1&&level<ci->mipLevels&&b->srcSubresource.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT&&b->dstSubresource.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT);
 assert(!b->srcSubresource.baseArrayLayer&&!b->dstSubresource.baseArrayLayer&&b->srcSubresource.layerCount==1&&b->dstSubresource.layerCount==1);
 assert(layouts[id][previous]==sl&&layouts[id][level]==dl&&(content[id]&(1u<<previous))&&!(content[id]&(1u<<level)));
 unsigned w=ci->extent.width>>previous,h=ci->extent.height>>previous;if(!w)w=1;if(!h)h=1;
 assert(!b->srcOffsets[0].x&&!b->srcOffsets[0].y&&!b->srcOffsets[0].z&&!b->dstOffsets[0].x&&!b->dstOffsets[0].y&&!b->dstOffsets[0].z);
 assert(b->srcOffsets[1].x==(int)w&&b->srcOffsets[1].y==(int)h&&b->srcOffsets[1].z==1);
 assert(b->dstOffsets[1].x==(int)(w>1?w/2:1)&&b->dstOffsets[1].y==(int)(h>1?h/2:1)&&b->dstOffsets[1].z==1);
 /* The mock validates command structure only: it NEVER computes output pixels. */
 content[id]|=1u<<level;event[events++]=(typeof(event[0])){'L',level,0,0};++blits;
}
#define vkCmdBlitImage fake_blit
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
    'static void fb_cache_forget(VkImageView view) {', 'static void image_free_now(',
    'static vbufmem *bufmem_try_new(', 'static void bufmem_free(',
    'static VkFormatProperties fmt_props(', 'static int fmt_has(', 'static int full_levels(',
    'static int native_image_upload_hold(', 'static void image_drop(',
    'static void native_image_upload_complete(', 'static void ring_reset(',
    'static void loader_flush(', 'static void barrier(',
]
actual = ''.join(fun(CORE, a) for a in anchors) + fun(NATIVE, 'static int native_sampler_valid(')

tests = r'''
static cinder_vk_sampler sampler(void){return(cinder_vk_sampler){.use_state=1,.mipmaps=1,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_LINEAR,.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_LINEAR,.address_u=VK_SAMPLER_ADDRESS_MODE_REPEAT,.address_v=VK_SAMPLER_ADDRESS_MODE_REPEAT,.anisotropy=4};}
static cinder_vk_texture_desc make_desc(cinder_vk_texture_subresource*s,cinder_vk_texture_format f,int w,int h){return(cinder_vk_texture_desc){w,h,full_levels(w,h),1,f,sampler(),s,1};}
static void free_ring(ring*r){for(size_t i=0;i<r->n;++i)bufmem_free(r->b[i]);free(r->b);*r=(ring){0};}
static void reset(void){
 F=&frame;native_image_upload_complete();for(unsigned i=1;i<32;++i)if(textures[i].im){image_free_now(textures[i].im);textures[i]=(vtex){0};}
 for(unsigned i=0;i<retired;++i)image_free_now(dead_images[i]);retired=0;free_ring(&frame.up.stage);free_ring(&LOADER_UP.stage);
 free(native_upload_images);native_upload_images=NULL;n_native_upload_images=cap_native_upload_images=0;
 assert(!live_memory&&!live_images&&!live_buffers&&!live_views&&!n_fbs);memset(textures,0,sizeof textures);memset(blocks,0,sizeof blocks);memset(buffers,0,sizeof buffers);memset(views,0,sizeof views);memset(images,0,sizeof images);memset(layouts,0,sizeof layouts);memset(content,0,sizeof content);
 nm=nb=nv=ni=errors=table_calls=commands=barriers=copies=begins=flushes=waits=queries=format_queries=blits=events=fb_destroys=0;active_cmd=VK_NULL_HANDLE;
 calloc_calls=realloc_calls=calloc_fail_at=realloc_fail_at=stage_attempts=stage_fail_at=0;image_fault=view_fail_at=view_null_at=buffer_fault=begin_fail=table_fail=lease_fail=native_loader_failed=0;
 end_result=submit_result=wait_result=fence_result=pool_result=query_result=VK_SUCCESS;
 D.dev=H(VkDevice,1);D.pd=H(VkPhysicalDevice,2);D.props.limits.maxImageDimension2D=4096;D.props.limits.maxImageDimensionCube=4096;D.f4444=VK_FORMAT_R4G4B4A4_UNORM_PACK16;D.f5551=VK_FORMAT_R5G5B5A1_UNORM_PACK16;D.sw4444=D.sw5551=SWZ_ID;D.conv5551=0;D.astc=D.aniso=1;D.max_aniso=16;D.lazy_type=~0u;D.uid=0;D.serial=19;
 caps=(VkImageFormatProperties){.maxExtent={4096,4096,1},.maxMipLevels=31,.maxArrayLayers=6,.sampleCounts=VK_SAMPLE_COUNT_1_BIT,.maxResourceSize=UINT64_MAX};
 features=VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT|VK_FORMAT_FEATURE_TRANSFER_SRC_BIT|VK_FORMAT_FEATURE_TRANSFER_DST_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT|VK_FORMAT_FEATURE_BLIT_SRC_BIT|VK_FORMAT_FEATURE_BLIT_DST_BIT;
 frame.up=(uploader){.pool=H(VkCommandPool,1),.cmd=H(VkCommandBuffer,2),.fence=H(VkFence,5)};LOADER_UP=(uploader){.pool=H(VkCommandPool,3),.cmd=H(VkCommandBuffer,4),.fence=H(VkFence,6)};
 frame.up.stage.chunk=LOADER_UP.stage.chunk=256;frame.up.stage.usage=LOADER_UP.stage.usage=VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT;
 scrub=NULL;scrub_bytes=0;require_lease=0;assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_FRAME));
}
static void event_is(unsigned i,char kind,unsigned level,VkImageLayout from,VkImageLayout to){assert(i<events&&event[i].kind==kind&&event[i].level==level);if(kind=='B')assert(event[i].from==from&&event[i].to==to);}
static void sequence(unsigned start,int levels){
 unsigned i=start;event_is(i++,'B',0,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);event_is(i++,'C',0,0,0);
 for(int l=1;l<levels;++l){event_is(i++,'B',(unsigned)l-1,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);event_is(i++,'B',(unsigned)l,VK_IMAGE_LAYOUT_UNDEFINED,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);event_is(i++,'L',(unsigned)l,0,0);event_is(i++,'B',(unsigned)l-1,VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);}
 event_is(i++,'B',(unsigned)levels-1,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);assert(i==events);
}
static void verify_image(uint32_t id,const cinder_vk_texture_desc*d,VkFormat format){
 assert(id&&tex_get(id)&&tex_get(id)->im);vimg*im=tex_get(id)->im;assert(im->fmt==format&&im->levels==d->levels&&im->layers==1&&im->view_levels==d->levels&&im->level_mask==((1u<<d->levels)-1)&&im->in_rest&&im->defined&&im->usage==USAGE&&!im->att&&im->uid);
 assert(live_views==1&&live_images==1&&views[(uintptr_t)im->view].ci.subresourceRange.levelCount==(uint32_t)d->levels&&views[(uintptr_t)im->view].ci.subresourceRange.layerCount==1&&views[(uintptr_t)im->view].ci.viewType==VK_IMAGE_VIEW_TYPE_2D);
 assert(copies==1&&blits==(unsigned)d->levels-1&&barriers==2+3*blits&&!errors&&!queried_flags&&queried_format==format);
 assert(!memcmp(&tex_get(id)->native_sampler,&d->sampler,sizeof d->sampler));for(int l=0;l<d->levels;++l)assert(layouts[(uintptr_t)im->img][l]==im->rest);assert(content[(uintptr_t)im->img]==im->level_mask);sequence(0,d->levels);
}
static void formats(void){
 const VkFormat expected[]={VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_R5G6B5_UNORM_PACK16,VK_FORMAT_R4G4B4A4_UNORM_PACK16,VK_FORMAT_R5G5B5A1_UNORM_PACK16,VK_FORMAT_R8_UNORM,VK_FORMAT_R8G8_UNORM,VK_FORMAT_R8_UNORM};
 for(int f=0;f<8;++f){reset();unsigned bpp=f==0?4:f==1?3:f==5||f==7?1:2;int w=3,h=5;
 size_t row=(size_t)w*bpp,stride=row+3,span=(size_t)(h-1)*stride+row;uint8_t*source=malloc(span+1);assert(source);for(size_t i=0;i<span+1;++i)source[i]=(uint8_t)(i*7+3);
 uint8_t expected_bytes[256];size_t written=0;for(int y=0;y<h;++y)for(size_t x=0;x<row;++x){expected_bytes[written++]=source[1+(size_t)y*stride+x];if(f==1&&x%3==2)expected_bytes[written++]=255;}
 cinder_vk_texture_subresource s={0,0,source+1,span,stride};cinder_vk_texture_desc d=make_desc(&s,(cinder_vk_texture_format)f,w,h);scrub=source;scrub_bytes=span+1;
 uint32_t id=cinder_vk_texture_generate_mips(&d);free(source);scrub=NULL;verify_image(id,&d,expected[f]);assert(captured[0].size==written&&!memcmp(captured[0].bytes,expected_bytes,written));assert(nv==2&&!views[1].live);
 VkComponentMapping sw=tex_get(id)->im->swz;if(f==1)assert(sw.a==VK_COMPONENT_SWIZZLE_ONE);if(f==5||f==6)assert(sw.r==VK_COMPONENT_SWIZZLE_R&&sw.g==sw.r&&sw.b==sw.r&&sw.a==(f==5?VK_COMPONENT_SWIZZLE_ONE:VK_COMPONENT_SWIZZLE_G));if(f==7)assert(sw.r==VK_COMPONENT_SWIZZLE_ZERO&&sw.g==sw.r&&sw.b==sw.r&&sw.a==VK_COMPONENT_SWIZZLE_R);
 }
 reset();uint8_t raw[12]={0};uint16_t values[]={0x0001,0xf801,0x07c0,0xffff};for(int i=0;i<4;++i)memcpy(raw+1+(i/2)*5+(i%2)*2,&values[i],2);
 D.f5551=VK_FORMAT_A1R5G5B5_UNORM_PACK16;D.conv5551=1;cinder_vk_texture_subresource s={0,0,raw+1,9,5};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGBA5551,2,2);uint32_t id=cinder_vk_texture_generate_mips(&d);verify_image(id,&d,D.f5551);
 for(int i=0;i<4;++i){uint16_t value;memcpy(&value,captured[0].bytes+2*i,2);assert(value==(uint16_t)((values[i]>>1)|((values[i]&1u)<<15)));}
 for(int f=3;f<=4;++f){reset();VkComponentMapping sw={VK_COMPONENT_SWIZZLE_B,VK_COMPONENT_SWIZZLE_G,VK_COMPONENT_SWIZZLE_R,VK_COMPONENT_SWIZZLE_A};if(f==3){D.f4444=VK_FORMAT_B4G4R4A4_UNORM_PACK16;D.sw4444=sw;}else{D.f5551=VK_FORMAT_B5G5R5A1_UNORM_PACK16;D.sw5551=sw;}d=make_desc(&s,(cinder_vk_texture_format)f,2,2);id=cinder_vk_texture_generate_mips(&d);assert(id&&!memcmp(&tex_get(id)->im->swz,&sw,sizeof sw)&&queried_format==tex_get(id)->im->fmt);}
 reset();puts("PASS all 8 formats: exact staged base bytes, padded/unaligned rows, RGB alpha/5551 rotation, device packed format/swizzle; caller data scrubbed before begin");
}
static void dimensions(void){
 static const int shapes[][2]={{1,1},{1,9},{9,1},{7,5},{2,2},{16,8},{31,1},{1,31},{17,9}};
 for(unsigned i=0;i<sizeof shapes/sizeof shapes[0];++i){reset();uint8_t data[1024]={0};cinder_vk_texture_subresource s={0,0,data,sizeof data,0};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_L8,shapes[i][0],shapes[i][1]);d.sampler.mipmaps=i%2;verify_image(cinder_vk_texture_generate_mips(&d),&d,VK_FORMAT_R8_UNORM);assert(captured[0].size==(size_t)d.width*d.height);}
 reset();uint8_t one=3;cinder_vk_texture_subresource s={0,0,&one,1,0};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_L8,1,1);features&=~(VK_FORMAT_FEATURE_BLIT_SRC_BIT|VK_FORMAT_FEATURE_BLIT_DST_BIT);verify_image(cinder_vk_texture_generate_mips(&d),&d,VK_FORMAT_R8_UNORM);
 reset();d.sampler.min_filter=d.sampler.mag_filter=VK_FILTER_NEAREST;d.sampler.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST;features&=~(VK_FORMAT_FEATURE_BLIT_SRC_BIT|VK_FORMAT_FEATURE_BLIT_DST_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT);verify_image(cinder_vk_texture_generate_mips(&d),&d,VK_FORMAT_R8_UNORM);
 reset();puts("PASS full sampled view, exact barrier/copy/blit order and extents: 1xN/Nx1/NPOT; mip-enabled 1x1 no blit requirements; nomip multilevel retained");
}
#define BAD(change) do{reset();uint8_t data[64]={0};cinder_vk_texture_subresource s={0,0,data,16,0};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGBA8,2,2);change;assert(!cinder_vk_texture_generate_mips(&d)&&errors==1&&!ni&&!nb&&!table_calls&&!begins&&!barriers&&!copies&&!blits&&!live_images);}while(0)
static void invalid(void){
 reset();assert(!cinder_vk_texture_generate_mips(NULL)&&errors==1&&!ni);
 BAD(d.width=0);BAD(d.width=-1);BAD(d.height=0);BAD(d.height=-1);BAD(d.levels=0);BAD(d.levels=1);BAD(d.levels=3);BAD(d.levels=32);BAD(d.layers=0);BAD(d.layers=2);BAD(d.layers=6);
 BAD(d.subresources=NULL);BAD(d.subresource_count=0);BAD(d.subresource_count=2);BAD(s.level=1);BAD(s.layer=1);BAD(s.data=NULL);BAD(s.bytes=15);BAD(s.row_stride=7);BAD(s.row_stride=SIZE_MAX);BAD(s.row_stride=PTRDIFF_MAX);BAD(s.data=(void*)(UINTPTR_MAX-2));
 BAD(d.format=(cinder_vk_texture_format)-1);BAD(d.format=(cinder_vk_texture_format)11);BAD(d.format=CINDER_VK_TEX_ASTC_4x4);BAD(d.format=CINDER_VK_TEX_ASTC_6x6);BAD(d.format=CINDER_VK_TEX_ASTC_8x8);BAD(d.sampler.use_state=0);BAD(d.sampler.use_state=2);BAD(d.sampler.anisotropy=NAN);BAD(d.sampler.anisotropy=INFINITY);BAD(d.sampler.min_filter=(VkFilter)-1);BAD(d.sampler.mipmaps=2);BAD(d.sampler.address_v=(VkSamplerAddressMode)-1);
 BAD(d.width=INT_MAX;d.height=INT_MAX;d.levels=31;s.bytes=SIZE_MAX);BAD(D.dev=VK_NULL_HANDLE);BAD(D.pd=VK_NULL_HANDLE);BAD(F=NULL);BAD(frame.up.pool=VK_NULL_HANDLE);BAD(frame.up.cmd=VK_NULL_HANDLE);BAD(D.props.limits.maxImageDimension2D=1);
 BAD(features&=~VK_FORMAT_FEATURE_TRANSFER_SRC_BIT);BAD(features&=~VK_FORMAT_FEATURE_TRANSFER_DST_BIT);BAD(features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT);BAD(features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT);BAD(features&=~VK_FORMAT_FEATURE_BLIT_SRC_BIT);BAD(features&=~VK_FORMAT_FEATURE_BLIT_DST_BIT);
 BAD(d.sampler.min_filter=d.sampler.mag_filter=VK_FILTER_NEAREST;d.sampler.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST;features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT);
 BAD(caps.maxExtent.width=1);BAD(caps.maxExtent.height=1);BAD(caps.maxExtent.depth=0);BAD(caps.maxMipLevels=1);BAD(caps.maxArrayLayers=0);BAD(caps.sampleCounts=VK_SAMPLE_COUNT_4_BIT);BAD(caps.maxResourceSize=19);BAD(query_result=VK_ERROR_FORMAT_NOT_SUPPORTED);
 BAD(D.f4444=VK_FORMAT_UNDEFINED;d.format=CINDER_VK_TEX_RGBA4444);BAD(D.f5551=VK_FORMAT_UNDEFINED;d.format=CINDER_VK_TEX_RGBA5551);
 BAD(assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));native_loader_failed=1;F=NULL);
 reset();uint8_t data[17]={0};cinder_vk_texture_subresource s={0,0,data,17,9};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGBA8,2,2);assert(cinder_vk_texture_generate_mips(&d));reset();s.bytes=16;assert(!cinder_vk_texture_generate_mips(&d)&&!ni);
 for(int which=0;which<2;++which){reset();uint8_t one=0;s=(cinder_vk_texture_subresource){0,0,&one,1,0};d=make_desc(&s,CINDER_VK_TEX_L8,1,1);if(which)d.sampler.min_filter=d.sampler.mag_filter=VK_FILTER_NEAREST;features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;assert(!cinder_vk_texture_generate_mips(&d)&&!ni);}
 reset();puts("PASS invalid descriptor/span/overflow/stream/format/sampler/capabilities before allocation or commands; exact image flags/usage/sample1/full output size; 1x1 sampler linear features still enforced");
}
static void allocation_failures(void){
 for(int fault=0;fault<16;++fault){reset();uint8_t data[16]={0};cinder_vk_texture_subresource s={0,0,data,16,0};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGBA8,2,2);
 switch(fault){case 0:calloc_fail_at=1;break;case 1:image_fault=1;break;case 2:image_fault=2;break;case 3:image_fault=3;break;case 4:view_fail_at=1;break;case 5:view_fail_at=2;break;case 6:view_null_at=2;break;case 7:buffer_fault=1;break;case 8:buffer_fault=2;break;case 9:buffer_fault=3;break;case 10:buffer_fault=4;break;case 11:realloc_fail_at=1;break;case 12:table_fail=1;break;case 13:begin_fail=1;break;case 14:calloc_fail_at=2;break;case 15:view_null_at=1;break;}
 assert(!cinder_vk_texture_generate_mips(&d)&&errors==1&&!barriers&&!copies&&!blits&&!live_images&&!live_views&&!tex_get(1));assert(!frame.up.stage.i&&!frame.up.stage.used);}
 reset();uint8_t data[16]={0};cinder_vk_texture_subresource s={0,0,data,16,0};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGBA8,2,2);
 assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));LOADER_UP.stage.b=calloc(64,sizeof *LOADER_UP.stage.b);LOADER_UP.stage.cap=64;lease_fail=1;assert(!cinder_vk_texture_generate_mips(&d)&&errors==1&&begins==1&&!barriers&&!copies&&!blits&&!live_images&&!n_native_upload_images&&!tex_get(1)&&!LOADER_UP.stage.used);
 reset();D.uid=UINT32_MAX;assert(!cinder_vk_texture_generate_mips(&d)&&!live_images&&!live_views&&ni==1&&!table_calls&&!begins);
 reset();puts("PASS constructor/create/memory/bind/view/stage/table/begin/lease/UID faults: no image commands/publication, full cleanup and cursor rollback");
}
static void precommand_transactions(void){
 for(int fault=0;fault<4;++fault){reset();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));require_lease=1;LOADER_UP.stage.chunk=16;
 uint8_t prefix_data[2]={0x5a,0x7b};uint32_t prefix_id=0;vimg*prefix_image=NULL;VkBuffer prefix_buffer;VkDeviceSize prefix_offset;uint8_t*prefix;
 if(fault==1){prefix=native_ring_alloc(&LOADER_UP.stage,2,16,&prefix_buffer,&prefix_offset);assert(prefix);memcpy(prefix,prefix_data,2);}else{cinder_vk_texture_subresource slice={0,0,prefix_data,2,0};cinder_vk_texture_desc first=make_desc(&slice,CINDER_VK_TEX_RGB565,1,1);prefix_id=cinder_vk_texture_generate_mips(&first);assert(prefix_id&&n_native_upload_images==1);prefix_image=tex_get(prefix_id)->im;prefix=LOADER_UP.stage.b[0]->map;}
 ring*r=&LOADER_UP.stage;size_t start_i=r->i,start_n=r->n;VkDeviceSize start_used=r->used;unsigned start_copies=copies,start_barriers=barriers,start_blits=blits;size_t prefix_leases=n_native_upload_images;
 uint8_t pixels[32];memset(pixels,0x31,sizeof pixels);cinder_vk_texture_subresource s={0,0,pixels,32,0};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGB565,4,4);
 if(fault==0)stage_fail_at=stage_attempts+1;if(fault==1)begin_fail=1;if(fault==2){cap_native_upload_images=n_native_upload_images;lease_fail=1;}if(fault==3)table_fail=1;
 for(int retry=0;retry<4;++retry){if(fault==0)stage_fail_at=stage_attempts+1;assert(!cinder_vk_texture_generate_mips(&d)&&!native_loader_failed&&copies==start_copies&&barriers==start_barriers&&blits==start_blits&&r->i==start_i&&r->used==start_used&&!memcmp(prefix,prefix_data,2));assert(n_native_upload_images==prefix_leases&&(!prefix_id||tex_get(prefix_id)->im==prefix_image));if(prefix_image)assert(prefix_image->native_upload_pending&&!prefix_image->native_retire_pending);if(fault==1&&retry==0)assert(r->n>start_n);if(fault==1){assert(!LOADER_UP.open);loader_flush();assert(!flushes&&r->i==start_i&&r->used==start_used);}}
 size_t retained_n=r->n;unsigned retained_buffers=nb;stage_fail_at=0;begin_fail=lease_fail=table_fail=0;uint32_t id=cinder_vk_texture_generate_mips(&d);assert(id&&id!=prefix_id&&copies==start_copies+1&&blits==start_blits+2&&r->i==1&&r->used==32&&r->n==2&&!memcmp(prefix,prefix_data,2)&&n_native_upload_images==prefix_leases+1);
 assert(!memcmp(captured[start_copies].bytes,pixels,32));if(fault==0)assert(retained_n==1&&nb==retained_buffers+1);else assert(retained_n==2&&nb==retained_buffers);
 }
 reset();puts("PASS exact staging i/used transaction with actual ring: stage/table/begin/lease repeated failures, prefix/pending handle/lease retention, closed-loader no-op flush, retained-capacity retry reuse");
}
static void loader(void){
 reset();uint8_t data[32];memset(data,0x5b,sizeof data);cinder_vk_texture_subresource s={0,0,data,32,0};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGB565,4,4);
 assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));require_lease=1;F=NULL;uint32_t id=cinder_vk_texture_generate_mips(&d);assert(id&&n_native_upload_images==1&&tex_get(id)->im->native_upload_pending&&active_cmd==LOADER_UP.cmd);vimg*im=tex_get(id)->im;
 cinder_vk_texture_destroy(id);assert(!tex_get(id)&&!retired&&live_images==1&&im->native_retire_pending);D.serial=27;assert(!retired);loader_flush();assert(!native_loader_failed&&!n_native_upload_images&&retired==1&&dead_images[0]==im&&dead_serials[0]==27&&live_images==1&&!LOADER_UP.stage.used);
 for(int fault=-2;fault<5;++fault){reset();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));require_lease=1;LOADER_UP.stage.chunk=1;F=NULL;
 for(int i=0;i<(fault==-2?3:4);++i){VkBuffer b;VkDeviceSize off;uint8_t*p=native_ring_alloc(&LOADER_UP.stage,1,16,&b,&off);assert(p);*p=(uint8_t)(0xa0+i);}size_t prefix_n=LOADER_UP.stage.n;
 switch(fault){case 0:end_result=VK_ERROR_DEVICE_LOST;break;case 1:submit_result=VK_ERROR_DEVICE_LOST;break;case 2:wait_result=VK_TIMEOUT;break;case 3:fence_result=VK_ERROR_DEVICE_LOST;break;case 4:pool_result=VK_ERROR_DEVICE_LOST;break;}
 id=cinder_vk_texture_generate_mips(&d);if(fault<0){assert(id&&!native_loader_failed&&LOADER_UP.stage.n==prefix_n+1);if(fault==-2){assert(!flushes&&n_native_upload_images==1&&LOADER_UP.stage.used==32);}else assert(flushes==1&&!n_native_upload_images&&!LOADER_UP.stage.used);continue;}
 assert(!id&&native_loader_failed&&!tex_get(1)&&errors==1&&live_images==1&&copies==1&&blits==2&&barriers==8);
 if(fault<3)assert(n_native_upload_images==1&&!retired&&native_upload_images[0]->native_retire_pending);else assert(!n_native_upload_images&&retired==1);if(fault<2)assert(!waits);
 assert(LOADER_UP.stage.n==5&&LOADER_UP.stage.i==4&&LOADER_UP.stage.used==32);unsigned before=begins,before_stages=stage_attempts;uint8_t recorded[32];memcpy(recorded,data,32);memset(data,0xee,32);
 assert(!cinder_vk_texture_generate_mips(&d)&&begins==before&&stage_attempts==before_stages&&live_images==1&&LOADER_UP.stage.i==4&&LOADER_UP.stage.used==32&&!memcmp(LOADER_UP.stage.b[4]->map,recorded,32));for(size_t i=0;i<4;++i)assert(LOADER_UP.stage.b[i]->map[0]==0xa0+i);
 }
 reset();puts("PASS FRAME requires F; LOADER without F uses one lease/full blit chain; public delete waits actual loader completion; >4 auto-flush faults never rewind referenced stage/reject new uploads; end-submit-wait faults retain unknown lease, successful-wait reset faults safely release lease but retain stage");
}
static void retirement(void){
 reset();uint8_t data[16]={0};cinder_vk_texture_subresource s={0,0,data,sizeof data,0};cinder_vk_texture_desc d=make_desc(&s,CINDER_VK_TEX_RGBA8,2,2);uint32_t id=cinder_vk_texture_generate_mips(&d);vimg*im=tex_get(id)->im;assert(active_cmd==frame.up.cmd&&im->uid==1);im->serial=24;cinder_vk_texture_destroy(id);assert(!tex_get(id)&&retired==1&&dead_images[0]==im&&dead_serials[0]==24&&live_images==1&&live_views==1);image_free_now(im);retired=0;assert(!live_images&&!live_views);
 id=cinder_vk_texture_generate_mips(&d);assert(id==1&&tex_get(id)->im->uid==2);cinder_vk_texture_destroy(id);assert(!memcmp(&textures[id].native_sampler,&(cinder_vk_sampler){0},sizeof(cinder_vk_sampler)));
 /* Mips are sampled-only; no attachment/cache entry can be created. The actual
  * cache forget helper is linked and an unrelated key remains untouched. */
 n_fbs=1;fbs[0]=(fbent){.v={H(VkImageView,999)},.fb=H(VkFramebuffer,900)};fb_cache_forget(H(VkImageView,998));assert(n_fbs==1&&!fb_destroys);fb_cache_forget(H(VkImageView,999));assert(!n_fbs&&fb_destroys==1);
 reset();puts("PASS real shared serial retirement/public handle reuse/private UID/sampler cleanup and actual cache forget helper; sampled-only mip images have no attachment view/cache key");
}
int main(void){setvbuf(stdout,NULL,_IONBF,0);formats();dimensions();invalid();allocation_failures();precommand_transactions();loader();retirement();reset();puts("native Vulkan mip commands: UBSan host PASS; GPU byte output UNKNOWN (mock blit never executes driver)");return 0;}
'''

fixture = (prefix + ''.join(schema(n) for n in ('vbufmem', 'vimg', 'ring', 'uploader', 'fbent')) + state + actual +
           '\n#include "native_vk_upload.inc"\n#include "native_vk_resources.inc"\n#include "native_vk_images.inc"\n#include "native_vk_mipmap.inc"\n' + tests)
assert not re.search(r'\b(?:GLenum|GLuint|GLint|vctx|vvao)\b', fixture)
with tempfile.TemporaryDirectory(prefix='mipmap-', dir=OUT) as directory:
    directory = Path(directory)
    (directory / 'mipmap.c').write_text(fixture)
    flags = ['-I', str(ROOT / 'src')]
    if sys.platform == 'darwin':
        flags += ['-I', '/opt/homebrew/include']
    command = [os.environ.get('CC', 'clang'), '-std=gnu11', '-Wall', '-Wextra', '-Werror',
               '-Wno-missing-field-initializers', '-fsanitize=undefined', '-fno-sanitize-recover=all',
               '-fno-omit-frame-pointer', *flags, str(directory / 'mipmap.c'), '-pthread', '-lm', '-o', str(directory / 'mipmap')]
    subprocess.run(command, cwd=directory, check=True, timeout=120)
    subprocess.run([str(directory / 'mipmap')], cwd=directory, check=True,
                   timeout=int(os.environ.get('NATIVE_VK_TEST_TIMEOUT', '30')))
    print('sanitizers undefined; GPU byte output unknown; ASan/TSan not claimed')
for path in ('src/native_vk_mipmap.inc', 'tests/test_native_vk_mipmap_host.py', 'src/native_vk.h', 'src/vkgl.c',
             'src/native_vk_images.inc', 'src/native_vk_resources.inc', 'src/native_vk_upload.inc', 'src/native_vk.inc'):
    print(path, hashlib.sha256((ROOT / path).read_bytes()).hexdigest())

