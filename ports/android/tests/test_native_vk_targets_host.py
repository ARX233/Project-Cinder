#!/usr/bin/env python3
"""Actual native target include + constructor/view/lifetime/fb-target helper subsets.
Vulkan/memory/bounded tables only are mocked: no GL/context/VAO/unit declarations.
This is CPU fault/ownership evidence, NOT physical GPU pixels or device recovery.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('CINDER_TEST_OUT', os.environ.get('TMPDIR', tempfile.gettempdir()))).resolve() / 'round5-targets'
OUT.mkdir(parents=True, exist_ok=True)
CORE = (ROOT / 'src/vkgl.c').read_text()
NATIVE = (ROOT / 'src/native_vk.inc').read_text()
TARGETS = (ROOT / 'src/native_vk_targets.inc').read_text()
assert not re.search(r'\b(?:ctx|cur_up|bound_tex|tex_format|image_settle|tex_view|vkgl_\w+)\s*\(', TARGETS)
assert not re.search(r'\b(?:GLenum|GLuint|GLint|GL_\w+|vctx|vvao)\b', TARGETS)


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
    return CORE[start:end].replace('GLuint', 'uint32_t') + '\n'


prefix = r'''
#include <assert.h>
#include <limits.h>
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "native_vk.h"
#define H(T,x) ((T)(uintptr_t)(x))
typedef struct { int block; VkDeviceSize off,size; } vmem;
'''
state = r'''
typedef struct { int used; vimg *im; cinder_vk_sampler native_sampler; } vtex;
static int platform_native_profile = 1;
static struct { VkDevice dev; VkPhysicalDevice pd; VkPhysicalDeviceProperties props;
 VkFormat f11,fd24; uint32_t lazy_type,uid; _Atomic uint64_t serial; pthread_mutex_t lock; } D={.lock=PTHREAD_MUTEX_INITIALIZER};
static const VkComponentMapping SWZ_ID={VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY};
static struct { VkDeviceMemory mem; int live; } blocks[1024];
static struct { VkImageCreateInfo ci; int live; } images[1024];
static struct { VkImageViewCreateInfo ci; int live; } views[2048];
static unsigned nm,ni,nv,live_memory,live_images,live_views,errors,queries,format_queries;
static fbent fbs[64];static size_t n_fbs,cap_fbs=64;
static struct {VkImageView views[3];uint32_t count;uint64_t last_use;int live;}framebuffers[128];
static unsigned framebuffer_calls,live_framebuffers,framebuffer_destroys;static uint64_t completed_serial;
#define GROW(p,n,c) do{assert((n)<64);(void)(p);(void)(c);}while(0)
static unsigned table_calls,tex_calls,rbo_calls,fbo_calls;
static unsigned calloc_calls,calloc_fail_at;
static int image_fault,view_fail_at,view_null_at,tex_fail,rbo_fail,fbo_fail,table_get_fail;
static unsigned lazy_requests,local_requests,other_requests;
static VkImageUsageFlags queried_usage;
static VkFormat queried_format;
static VkFormatFeatureFlags features;
static VkImageFormatProperties caps;
static VkResult query_result;
static unsigned query_fail_at;
static vtex textures[128]; static vrbo attachments[128]; static vfbo targets[128];
static vimg **native_upload_images;static size_t n_native_upload_images,cap_native_upload_images;
static struct {vimg *im;uint64_t serial;} dead_images[256];static unsigned retired;
static void native_image_upload_complete(void);
static void logf_(const char *format,...){(void)format;}
static int native_reject(void){++errors;return 0;}
#define DEAD_IMAGE 1
static void dead_add(int kind,void*p,uint64_t h,uint64_t serial){
 assert(kind==DEAD_IMAGE&&p&&!h&&retired<256);for(unsigned i=0;i<retired;++i)assert(dead_images[i].im!=p);
 dead_images[retired].im=p;dead_images[retired++].serial=serial;
}
static void fb_cache_forget(VkImageView view);
static vtex*tex_get(uint32_t id){return id<128&&textures[id].used?&textures[id]:NULL;}
static vrbo*rbo_get(uint32_t id){return id<128&&attachments[id].used?&attachments[id]:NULL;}
static vfbo*fbo_get(uint32_t id){return id<128&&targets[id].used?&targets[id]:NULL;}
static uint32_t tex_gen(void){++table_calls;++tex_calls;if(tex_fail)return 0;for(unsigned i=1;i<128;++i)if(!textures[i].used){textures[i]=(vtex){.used=1};if(table_get_fail)textures[i].used=0;return i;}return 0;}
static uint32_t rbo_gen(void){++table_calls;++rbo_calls;if(rbo_fail)return 0;for(unsigned i=1;i<128;++i)if(!attachments[i].used){attachments[i]=(vrbo){.used=1};if(table_get_fail)attachments[i].used=0;return i;}return 0;}
static uint32_t fbo_gen(void){++table_calls;++fbo_calls;if(fbo_fail)return 0;for(unsigned i=1;i<128;++i)if(!targets[i].used){targets[i]=(vfbo){.used=1};if(table_get_fail)targets[i].used=0;return i;}return 0;}
static void tex_release(uint32_t id){if(tex_get(id))textures[id]=(vtex){0};}
static void rbo_release(uint32_t id){if(rbo_get(id))attachments[id]=(vrbo){0};}
static void fbo_release(uint32_t id){if(fbo_get(id))targets[id]=(vfbo){0};}
static void*test_calloc(size_t n,size_t size){if(++calloc_calls==calloc_fail_at)return NULL;return calloc(n,size);}
static int mem_alloc(VkMemoryRequirements r,VkMemoryPropertyFlags want,VkMemoryPropertyFlags pref,int image,vmem*out){
 assert(image&&r.size&&!pref);if(want==VK_MEMORY_PROPERTY_LAZILY_ALLOCATED_BIT){++lazy_requests;if(D.lazy_type==~0u)return -1;}else if(want==VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)++local_requests;else{assert(!want);++other_requests;}
 if(image_fault==2)return -1;unsigned id=++nm;assert(id<1024);blocks[id].mem=H(VkDeviceMemory,id);blocks[id].live=1;++live_memory;*out=(vmem){(int)id,0,r.size};return 0;
}
static void mem_free(vmem*m){assert(m->block>0&&blocks[m->block].live);blocks[m->block].live=0;--live_memory;m->block=-1;}
static VkResult fake_create_image(VkDevice dev,const VkImageCreateInfo*ci,const VkAllocationCallbacks*a,VkImage*out){
 (void)a;assert(dev&&ci->imageType==VK_IMAGE_TYPE_2D&&ci->tiling==VK_IMAGE_TILING_OPTIMAL&&!ci->flags&&ci->extent.depth==1&&ci->mipLevels==1&&ci->arrayLayers==1&&ci->initialLayout==VK_IMAGE_LAYOUT_UNDEFINED);
 assert(queries&&queried_usage==ci->usage&&queried_format==ci->format);unsigned id=++ni;assert(id<1024);images[id].ci=*ci;if(image_fault==1)return VK_ERROR_OUT_OF_HOST_MEMORY;if(image_fault==4)return VK_SUCCESS;images[id].live=1;++live_images;*out=H(VkImage,id);return VK_SUCCESS;
}
static void fake_requirements(VkDevice dev,VkImage image,VkMemoryRequirements*out){assert(dev&&images[(uintptr_t)image].live);*out=(VkMemoryRequirements){256,16,1};}
static VkResult fake_bind(VkDevice dev,VkImage image,VkDeviceMemory memory,VkDeviceSize offset){assert(dev&&image&&memory&&!offset);return image_fault==3?VK_ERROR_MEMORY_MAP_FAILED:VK_SUCCESS;}
static void fake_destroy_image(VkDevice dev,VkImage image,const VkAllocationCallbacks*a){(void)a;assert(dev&&images[(uintptr_t)image].live);images[(uintptr_t)image].live=0;--live_images;}
static VkResult fake_view(VkDevice dev,const VkImageViewCreateInfo*ci,const VkAllocationCallbacks*a,VkImageView*out){
 (void)a;assert(dev&&ci->image&&ci->viewType==VK_IMAGE_VIEW_TYPE_2D&&ci->subresourceRange.baseMipLevel==0&&ci->subresourceRange.baseArrayLayer==0&&ci->subresourceRange.levelCount==1&&ci->subresourceRange.layerCount==1);
 assert(!memcmp(&ci->components,&SWZ_ID,sizeof SWZ_ID));unsigned id=++nv;assert(id<2048);views[id].ci=*ci;if((int)id==view_fail_at)return VK_ERROR_OUT_OF_HOST_MEMORY;if((int)id==view_null_at)return VK_SUCCESS;views[id].live=1;++live_views;*out=H(VkImageView,id);return VK_SUCCESS;
}
static void fake_destroy_view(VkDevice dev,VkImageView view,const VkAllocationCallbacks*a){(void)a;assert(dev&&views[(uintptr_t)view].live);for(unsigned i=1;i<=framebuffer_calls;++i)if(framebuffers[i].live)for(unsigned j=0;j<framebuffers[i].count;++j)assert(framebuffers[i].views[j]!=view);views[(uintptr_t)view].live=0;--live_views;}
static VkResult fake_framebuffer(VkDevice dev,const VkFramebufferCreateInfo*ci,const VkAllocationCallbacks*a,VkFramebuffer*out){(void)a;assert(dev&&ci->renderPass&&ci->attachmentCount>0&&ci->attachmentCount<=3&&ci->width&&ci->height&&ci->layers==1);unsigned id=++framebuffer_calls;assert(id<128);framebuffers[id].live=1;framebuffers[id].count=ci->attachmentCount;memcpy(framebuffers[id].views,ci->pAttachments,ci->attachmentCount*sizeof *ci->pAttachments);for(unsigned i=0;i<ci->attachmentCount;++i)assert(views[(uintptr_t)ci->pAttachments[i]].live);++live_framebuffers;*out=H(VkFramebuffer,id);return VK_SUCCESS;}
static void fake_destroy_framebuffer(VkDevice dev,VkFramebuffer fb,const VkAllocationCallbacks*a){(void)a;assert(dev&&framebuffers[(uintptr_t)fb].live&&framebuffers[(uintptr_t)fb].last_use<=completed_serial);framebuffers[(uintptr_t)fb].live=0;--live_framebuffers;++framebuffer_destroys;}
static void fake_format(VkPhysicalDevice pd,VkFormat format,VkFormatProperties*out){assert(pd&&format);++format_queries;*out=(VkFormatProperties){.optimalTilingFeatures=features};}
static VkResult fake_query(VkPhysicalDevice pd,VkFormat format,VkImageType type,VkImageTiling tiling,VkImageUsageFlags usage,VkImageCreateFlags flags,VkImageFormatProperties*out){
 assert(pd&&format&&type==VK_IMAGE_TYPE_2D&&tiling==VK_IMAGE_TILING_OPTIMAL&&!flags);++queries;queried_format=format;queried_usage=usage;*out=caps;return queries==query_fail_at?VK_ERROR_FORMAT_NOT_SUPPORTED:query_result;
}
#define calloc test_calloc
#define vkCreateImage fake_create_image
#define vkGetImageMemoryRequirements fake_requirements
#define vkBindImageMemory fake_bind
#define vkDestroyImage fake_destroy_image
#define vkCreateImageView fake_view
#define vkDestroyImageView fake_destroy_view
#define vkCreateFramebuffer fake_framebuffer
#define vkDestroyFramebuffer fake_destroy_framebuffer
#define vkGetPhysicalDeviceFormatProperties fake_format
#define vkGetPhysicalDeviceImageFormatProperties fake_query
static compat_t compats[64];static int n_compats;static unsigned renderpass_calls;
static struct {VkAttachmentDescription attachments[3];uint32_t count,color,depth,resolve;} pass_metadata[64];
enum { OP_PASS, OP_BLIT };
static VkResult fake_renderpass(VkDevice dev,const VkRenderPassCreateInfo*ci,const VkAllocationCallbacks*a,VkRenderPass*out){
 (void)a;assert(dev&&ci->attachmentCount>0&&ci->attachmentCount<=3&&ci->subpassCount==1&&ci->dependencyCount==2&&renderpass_calls<64);unsigned id=renderpass_calls++;pass_metadata[id].count=ci->attachmentCount;memcpy(pass_metadata[id].attachments,ci->pAttachments,ci->attachmentCount*sizeof *ci->pAttachments);const VkSubpassDescription*s=ci->pSubpasses;assert(s->pipelineBindPoint==VK_PIPELINE_BIND_POINT_GRAPHICS&&s->colorAttachmentCount<=1);pass_metadata[id].color=s->colorAttachmentCount? s->pColorAttachments->attachment+1:0;pass_metadata[id].depth=s->pDepthStencilAttachment?s->pDepthStencilAttachment->attachment+1:0;pass_metadata[id].resolve=s->pResolveAttachments?s->pResolveAttachments->attachment+1:0;*out=H(VkRenderPass,id+1);return VK_SUCCESS;
}
#define vkCreateRenderPass fake_renderpass
#define VKCHECK(expr) assert((expr)==VK_SUCCESS)
'''

anchors = ['static uint32_t resource_uid_next(', 'static int is_depth(', 'static int has_stencil(',
           'static VkResult view_try(', 'static vimg *image_new_usage(', 'static void image_free_now(',
           'static VkFormatProperties fmt_props(', 'static int fmt_has(', 'static int native_image_upload_hold(',
           'static void image_drop(', 'static int native_target_image_hold(',
           'static void native_target_image_release(', 'static void native_image_upload_complete(']
actual = ''.join(fun(CORE, a) for a in ('static void fb_cache_forget(VkImageView view)', 'static VkFramebuffer fb_get('))
actual += ''.join(fun(CORE, a) for a in anchors) + fun(NATIVE, 'static int native_sampler_valid(')
# Parent owns the strict snapshot helper; extract it unchanged. The tiny table
# wrapper below only substitutes its public integer ID lookup for the legacy arm.
actual += ''.join(fun(CORE, a) for a in ('static VkRenderPass rp_make(', 'static int compat_id(', 'static int native_compat_id(', 'static int native_fb_target('))
actual += r'''
static int fb_target(uint32_t id,vop*pass){memset(pass,0,sizeof *pass);vfbo*f=fbo_get(id);return f&&f->native&&native_fb_target(f,pass);}
'''

# The destructor is the exact native resource implementation, not a custom mock.
actual += fun((ROOT / 'src/native_vk_resources.inc').read_text(), 'void cinder_vk_texture_destroy(')
actual += fun(NATIVE, 'int cinder_vk_target_info(')

tests = r'''
static void collect(uint64_t upto){completed_serial=upto;unsigned keep=0;for(unsigned i=0;i<retired;++i){if(dead_images[i].serial<=upto)image_free_now(dead_images[i].im);else dead_images[keep++]=dead_images[i];}retired=keep;}
static cinder_vk_sampler sampler(void){return(cinder_vk_sampler){.use_state=1,.min_filter=VK_FILTER_NEAREST,.mag_filter=VK_FILTER_LINEAR,.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,.address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.address_v=VK_SAMPLER_ADDRESS_MODE_REPEAT,.anisotropy=1};}
static cinder_vk_storage_desc storage(cinder_vk_storage_format format,int samples){return(cinder_vk_storage_desc){.width=17,.height=9,.samples=samples,.format=format,.transfer_src=1,.transfer_dst=1,.sampler=sampler()};}
static cinder_vk_image_ref texture_ref(uint32_t id){return(cinder_vk_image_ref){CINDER_VK_IMAGE_TEXTURE,id};}
static cinder_vk_image_ref attachment_ref(uint32_t id){return(cinder_vk_image_ref){CINDER_VK_IMAGE_ATTACHMENT,id};}
static cinder_vk_target_create_desc target_desc(cinder_vk_image_ref c,cinder_vk_image_ref d,int samples){return(cinder_vk_target_create_desc){c,d,samples};}
static void reset(void){
 for(unsigned i=1;i<128;++i)if(targets[i].used)cinder_vk_target_destroy(i);
 for(unsigned i=1;i<128;++i){if(textures[i].used)cinder_vk_texture_destroy(i);if(attachments[i].used)cinder_vk_attachment_destroy(i);}
 native_image_upload_complete();collect(UINT64_MAX);free(native_upload_images);native_upload_images=NULL;n_native_upload_images=cap_native_upload_images=0;
 assert(!live_images&&!live_views&&!live_memory&&!retired&&!live_framebuffers&&!n_fbs);memset(framebuffers,0,sizeof framebuffers);framebuffer_calls=framebuffer_destroys=0;completed_serial=0;memset(textures,0,sizeof textures);memset(attachments,0,sizeof attachments);memset(targets,0,sizeof targets);memset(images,0,sizeof images);memset(views,0,sizeof views);memset(blocks,0,sizeof blocks);
 nm=ni=nv=errors=queries=format_queries=table_calls=tex_calls=rbo_calls=fbo_calls=calloc_calls=calloc_fail_at=0;
 image_fault=view_fail_at=view_null_at=tex_fail=rbo_fail=fbo_fail=table_get_fail=0;lazy_requests=local_requests=other_requests=0;query_fail_at=0;renderpass_calls=0;n_compats=0;memset(compats,0,sizeof compats);memset(pass_metadata,0,sizeof pass_metadata);
 D.dev=H(VkDevice,1);D.pd=H(VkPhysicalDevice,2);D.f11=VK_FORMAT_B10G11R11_UFLOAT_PACK32;D.fd24=VK_FORMAT_D24_UNORM_S8_UINT;D.lazy_type=~0u;D.uid=0;D.serial=19;
 D.props.limits.maxImageDimension2D=D.props.limits.maxFramebufferWidth=D.props.limits.maxFramebufferHeight=4096;D.props.limits.maxFramebufferLayers=256;
 D.props.limits.framebufferColorSampleCounts=D.props.limits.framebufferDepthSampleCounts=D.props.limits.framebufferStencilSampleCounts=15;
 caps=(VkImageFormatProperties){.maxExtent={4096,4096,1},.maxMipLevels=1,.maxArrayLayers=1,.sampleCounts=15,.maxResourceSize=UINT64_MAX};query_result=VK_SUCCESS;
 features=VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT|VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT|VK_FORMAT_FEATURE_TRANSFER_SRC_BIT|VK_FORMAT_FEATURE_TRANSFER_DST_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
}
static void verify(vimg*im,cinder_vk_storage_desc*d,VkFormat format,int sampled){
 assert(im&&im->fmt==format&&im->w==d->width&&im->h==d->height&&im->samples==d->samples&&im->levels==1&&im->layers==1&&im->sampled==sampled&&im->transient==(int)d->transient&&im->uid);
 assert(im->att&&(!sampled||im->view)&&!im->defined&&!im->in_rest&&!im->level_mask&&!im->native_upload_pending&&!im->native_target_refs&&!im->native_retire_pending);
 VkImageUsageFlags usage=is_depth(format)?VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT:VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;if(sampled)usage|=VK_IMAGE_USAGE_SAMPLED_BIT;if(d->transfer_src)usage|=VK_IMAGE_USAGE_TRANSFER_SRC_BIT;if(d->transfer_dst)usage|=VK_IMAGE_USAGE_TRANSFER_DST_BIT;if(d->transient)usage|=VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT;
 assert(im->usage==usage&&images[(uintptr_t)im->img].ci.usage==usage&&images[(uintptr_t)im->img].ci.samples==(VkSampleCountFlagBits)d->samples&&!memcmp(&im->swz,&SWZ_ID,sizeof SWZ_ID));
 assert(im->aspect==(is_depth(format)?VK_IMAGE_ASPECT_DEPTH_BIT|(has_stencil(format)?VK_IMAGE_ASPECT_STENCIL_BIT:0):VK_IMAGE_ASPECT_COLOR_BIT));assert(views[(uintptr_t)im->att].ci.subresourceRange.aspectMask==im->aspect);
 if(sampled){assert(im->view_levels==1&&views[(uintptr_t)im->view].ci.subresourceRange.aspectMask==(is_depth(format)?VK_IMAGE_ASPECT_DEPTH_BIT:VK_IMAGE_ASPECT_COLOR_BIT));assert(im->rest==VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);}else assert(!im->view&&!im->view_levels&&im->rest==(is_depth(format)?VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL:VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL));
}
static void verify_metadata(uint32_t id){
 vop p;assert(fb_target(id,&p));cinder_vk_target_desc info;assert(cinder_vk_target_info(id,&info));assert(info.width==p.w&&info.height==p.h&&info.color_format==(p.color?p.color->fmt:VK_FORMAT_UNDEFINED)&&info.depth_format==(p.depth?p.depth->fmt:VK_FORMAT_UNDEFINED)&&info.samples==(VkSampleCountFlagBits)(p.color?p.color->samples:p.depth->samples)&&info.resolves==(VkBool32)(p.resolve!=NULL)&&info.color_usage==(p.color?p.color->usage:0)&&info.depth_usage==(p.depth?p.depth->usage:0)&&info.resolve_usage==(p.resolve?p.resolve->usage:0));
 assert(p.compat>=0&&p.compat<n_compats&&compats[p.compat].rp);unsigned rp=(unsigned)(uintptr_t)compats[p.compat].rp-1;assert(rp<renderpass_calls);assert(pass_metadata[rp].count==(unsigned)((p.color!=NULL)+(p.depth!=NULL)+(p.resolve!=NULL)));unsigned slot=0;if(p.color){assert(pass_metadata[rp].color==slot+1&&pass_metadata[rp].attachments[slot].format==p.color->fmt&&pass_metadata[rp].attachments[slot].samples==info.samples);++slot;}else assert(!pass_metadata[rp].color);if(p.depth){assert(pass_metadata[rp].depth==slot+1&&pass_metadata[rp].attachments[slot].format==p.depth->fmt&&pass_metadata[rp].attachments[slot].samples==info.samples);++slot;}else assert(!pass_metadata[rp].depth);if(p.resolve){assert(pass_metadata[rp].resolve==slot+1&&pass_metadata[rp].attachments[slot].format==p.resolve->fmt&&pass_metadata[rp].attachments[slot].samples==VK_SAMPLE_COUNT_1_BIT&&pass_metadata[rp].attachments[slot].storeOp==VK_ATTACHMENT_STORE_OP_STORE);}else assert(!pass_metadata[rp].resolve);
}
static void formats(void){
 VkFormat formats[]={VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_R5G6B5_UNORM_PACK16,VK_FORMAT_R16G16B16A16_SFLOAT,VK_FORMAT_B10G11R11_UFLOAT_PACK32,VK_FORMAT_D16_UNORM,VK_FORMAT_D24_UNORM_S8_UINT};
 for(int kind=0;kind<2;++kind)for(int f=0;f<6;++f){reset();cinder_vk_storage_desc d=storage((cinder_vk_storage_format)f,1);uint32_t id=kind?cinder_vk_attachment_create(&d):cinder_vk_texture_storage(&d);assert(id&&!errors&&table_calls==1&&queries==1);verify(kind?rbo_get(id)->im:tex_get(id)->im,&d,formats[f],!kind);assert(live_views==(kind?1u:2u));if(!kind)assert(!memcmp(&tex_get(id)->native_sampler,&d.sampler,sizeof d.sampler));}
 for(int f=0;f<2;++f){reset();D.f11=VK_FORMAT_R16G16B16A16_SFLOAT;D.fd24=VK_FORMAT_D32_SFLOAT_S8_UINT;cinder_vk_storage_desc d=storage(f?CINDER_VK_STORAGE_DEPTH24_STENCIL8:CINDER_VK_STORAGE_R11G11B10F,1);uint32_t id=cinder_vk_texture_storage(&d);verify(tex_get(id)->im,&d,f?D.fd24:D.f11,1);}
 for(int sample=1;sample<=8;sample*=2)for(int transient=0;transient<2;++transient){reset();cinder_vk_storage_desc d=storage(CINDER_VK_STORAGE_DEPTH16,sample);d.transient=(VkBool32)transient;if(transient)d.transfer_src=d.transfer_dst=0;memset(&d.sampler,0xff,sizeof d.sampler);uint32_t id=cinder_vk_attachment_create(&d);assert(id&&!errors);verify(rbo_get(id)->im,&d,VK_FORMAT_D16_UNORM,0);if(transient){assert(lazy_requests==1&&local_requests==1&&!other_requests&&rbo_get(id)->im->transient);}}
 reset();D.lazy_type=2;cinder_vk_storage_desc d=storage(CINDER_VK_STORAGE_RGBA8,4);d.transient=1;d.transfer_src=d.transfer_dst=0;uint32_t id=cinder_vk_attachment_create(&d);verify(rbo_get(id)->im,&d,VK_FORMAT_R8G8B8A8_UNORM,0);assert(lazy_requests==1&&!local_requests&&!other_requests);
 for(int kind=0;kind<2;++kind)for(unsigned transfers=0;transfers<4;++transfers){reset();d=storage(CINDER_VK_STORAGE_RGB565,kind?4:1);d.transfer_src=transfers&1;d.transfer_dst=(transfers>>1)&1;uint32_t handle=kind?cinder_vk_attachment_create(&d):cinder_vk_texture_storage(&d);assert(handle);verify(kind?rbo_get(handle)->im:tex_get(handle)->im,&d,VK_FORMAT_R5G6B5_UNORM_PACK16,!kind);}
 reset();for(int i=0;i<20;++i){d=storage((cinder_vk_storage_format)(i%6),1);assert(cinder_vk_texture_storage(&d)==(unsigned)i+1&&cinder_vk_attachment_create(&d)==(unsigned)i+1);}assert(live_images==40&&tex_calls==20&&rbo_calls==20);
 reset();puts("PASS six exact storage formats + immutable HDR/depth fallbacks, full typed sampler, actual usage/identity views/depth aspect/undefined defaults, independent texture+attachment arrays, exact1/2/4/8 and transient noLazy device-local fallback");
}
#define BAD(change) do{reset();cinder_vk_storage_desc d=storage(CINDER_VK_STORAGE_RGBA8,1);change;assert(!cinder_vk_texture_storage(&d)&&errors==1&&!ni&&!table_calls&&!live_images);}while(0)
#define BAD_ATT(change) do{reset();cinder_vk_storage_desc d=storage(CINDER_VK_STORAGE_RGBA8,4);change;assert(!cinder_vk_attachment_create(&d)&&errors==1&&!ni&&!table_calls&&!live_images);}while(0)
static void invalid_storage(void){
 reset();assert(!cinder_vk_texture_storage(NULL)&&!cinder_vk_attachment_create(NULL)&&errors==2&&!ni);
 BAD(d.width=0);BAD(d.height=-1);BAD(d.width=INT_MAX);BAD(d.samples=0);BAD(d.samples=2);BAD(d.samples=3);BAD(d.samples=16);BAD(d.transient=1);BAD(d.transient=2);BAD(d.transfer_src=2);BAD(d.transfer_dst=2);BAD(d.format=(cinder_vk_storage_format)-1);BAD(d.format=(cinder_vk_storage_format)6);BAD(D.f11=VK_FORMAT_UNDEFINED;d.format=CINDER_VK_STORAGE_R11G11B10F);BAD(D.fd24=VK_FORMAT_D16_UNORM;d.format=CINDER_VK_STORAGE_DEPTH24_STENCIL8);
 BAD(d.sampler.use_state=0);BAD(d.sampler.use_state=2);BAD(d.sampler.mipmaps=1);BAD(d.sampler.min_filter=(VkFilter)-1);BAD(d.sampler.mag_filter=(VkFilter)2);BAD(d.sampler.mipmap_mode=(VkSamplerMipmapMode)-1);BAD(d.sampler.address_u=(VkSamplerAddressMode)-1);BAD(d.sampler.address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_BORDER);BAD(d.sampler.anisotropy=NAN);BAD(d.sampler.anisotropy=INFINITY);BAD(d.sampler.anisotropy=.5f);
 BAD(D.dev=VK_NULL_HANDLE);BAD(D.pd=VK_NULL_HANDLE);BAD(D.props.limits.maxImageDimension2D=16);BAD(D.props.limits.maxFramebufferWidth=16);BAD(D.props.limits.maxFramebufferHeight=8);BAD(D.props.limits.maxFramebufferLayers=0);
 BAD(features&=~VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT);BAD(features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT);BAD(features&=~VK_FORMAT_FEATURE_TRANSFER_SRC_BIT);BAD(features&=~VK_FORMAT_FEATURE_TRANSFER_DST_BIT);BAD(features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT);
 BAD(caps.maxExtent.width=16);BAD(caps.maxExtent.height=8);BAD(caps.maxExtent.depth=0);BAD(caps.maxMipLevels=0);BAD(caps.maxArrayLayers=0);BAD(caps.sampleCounts=VK_SAMPLE_COUNT_2_BIT);BAD(caps.maxResourceSize=17*9*4-1);BAD(query_result=VK_ERROR_FORMAT_NOT_SUPPORTED);
 BAD_ATT(d.samples=3);BAD_ATT(d.samples=0);BAD_ATT(d.samples=16);BAD_ATT(caps.sampleCounts&=~VK_SAMPLE_COUNT_4_BIT);BAD_ATT(D.props.limits.framebufferColorSampleCounts&=~VK_SAMPLE_COUNT_4_BIT);BAD_ATT(d.transient=1);BAD_ATT(d.format=CINDER_VK_STORAGE_DEPTH16;features&=~VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT);BAD_ATT(d.format=CINDER_VK_STORAGE_DEPTH24_STENCIL8;D.props.limits.framebufferStencilSampleCounts=1);BAD_ATT(d.format=CINDER_VK_STORAGE_DEPTH16;D.props.limits.framebufferDepthSampleCounts=1);BAD_ATT(D.props.limits.maxImageDimension2D=D.props.limits.maxFramebufferWidth=D.props.limits.maxFramebufferHeight=UINT32_MAX;caps.maxExtent.width=caps.maxExtent.height=UINT32_MAX;d.width=d.height=INT_MAX);
 reset();cinder_vk_storage_desc d=storage(CINDER_VK_STORAGE_RGB565,1);d.sampler.min_filter=d.sampler.mag_filter=VK_FILTER_NEAREST;features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;assert(cinder_vk_texture_storage(&d));
 reset();d=storage(CINDER_VK_STORAGE_RGBA8,8);d.transfer_src=d.transfer_dst=0;features=VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT;assert(cinder_vk_attachment_create(&d));
 reset();assert(cinder_vk_sample_limit()==8);D.props.limits.framebufferStencilSampleCounts=7;assert(cinder_vk_sample_limit()==4);D.props.limits.framebufferColorSampleCounts=3;assert(cinder_vk_sample_limit()==2);D.props.limits.framebufferDepthSampleCounts=1;assert(cinder_vk_sample_limit()==1);D.dev=VK_NULL_HANDLE;assert(!cinder_vk_sample_limit());D.dev=H(VkDevice,1);D.props.limits.framebufferStencilSampleCounts=0;assert(!cinder_vk_sample_limit());
 reset();puts("PASS malformed descriptors/nonmip sampler/role/boolean/dimension/sample/format-feature/exact-image capability negatives before allocation or publication; omitted transfers need no transfer feature, capability-only common sample limit");
}
static void allocation_failures(void){
 for(int kind=0;kind<2;++kind)for(int fault=0;fault<14;++fault){reset();cinder_vk_storage_desc d=storage(CINDER_VK_STORAGE_RGBA8,1);switch(fault){case 0:calloc_fail_at=1;break;case 1:image_fault=1;break;case 2:image_fault=2;break;case 3:image_fault=3;break;case 4:view_fail_at=1;break;case 5:view_null_at=1;break;case 6:view_fail_at=kind?1:2;break;case 7:view_null_at=kind?1:2;break;case 8:tex_fail=rbo_fail=1;break;case 9:table_get_fail=1;break;case 10:D.uid=UINT32_MAX;break;case 11:caps.maxResourceSize=0;break;case 12:query_result=VK_ERROR_FORMAT_NOT_SUPPORTED;break;case 13:image_fault=4;break;}
  assert(!(kind?cinder_vk_attachment_create(&d):cinder_vk_texture_storage(&d))&&errors==1&&!live_images&&!live_views&&!live_memory&&!tex_get(1)&&!rbo_get(1));}
 reset();cinder_vk_texture_destroy(0);cinder_vk_attachment_destroy(0);cinder_vk_target_destroy(0);assert(!errors);cinder_vk_texture_destroy(99);cinder_vk_attachment_destroy(99);cinder_vk_target_destroy(99);assert(errors==3);
 reset();puts("PASS actual constructor calloc/create/allocate/bind/view/null-view/UID and table admission failures fully clean partial images/views/memory, invalid/zero destruction, no dummy IDs");
}
static void composition(void){
 for(int kind=0;kind<2;++kind)for(int mask=1;mask<4;++mask){reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_RGBA8,1),dd=storage(CINDER_VK_STORAGE_DEPTH24_STENCIL8,1);uint32_t c=0,d=0;if(mask&1)c=kind?cinder_vk_attachment_create(&cd):cinder_vk_texture_storage(&cd);if(mask&2)d=kind?cinder_vk_attachment_create(&dd):cinder_vk_texture_storage(&dd);
 cinder_vk_target_create_desc td=target_desc(c?(kind?attachment_ref(c):texture_ref(c)):(cinder_vk_image_ref){0},d?(kind?attachment_ref(d):texture_ref(d)):(cinder_vk_image_ref){0},0);uint32_t id=cinder_vk_target_create(&td);assert(id&&cinder_vk_target_ready(id)&&!cinder_vk_target_ready(0));verify_metadata(id);vfbo*f=fbo_get(id);vop p;assert(fb_target(id,&p)&&p.w==17&&p.h==9&&p.compat>=0&&!p.resolve&&!p.screen);assert(f->native&&f->native_color==p.color&&f->native_depth==p.depth&&f->color.kind==(int)td.color.kind&&f->depth.kind==(int)td.depth_stencil.kind);if(d)assert(f->stencil.name==d&&f->stencil.kind==(int)td.depth_stencil.kind);if(c)assert(p.color->native_target_refs==1);if(d)assert(p.depth->native_target_refs==1);}
 for(int samples=2;samples<=8;samples*=2){reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_R11G11B10F,1),dd=storage(CINDER_VK_STORAGE_DEPTH16,samples);uint32_t c=cinder_vk_texture_storage(&cd),d=cinder_vk_attachment_create(&dd);cinder_vk_target_create_desc td=target_desc(texture_ref(c),attachment_ref(d),samples);unsigned before=ni;uint32_t id=cinder_vk_target_create(&td);assert(id&&ni==before+1);verify_metadata(id);vfbo*f=fbo_get(id);assert(f->ms&&f->ms->implicit&&f->ms->samples==samples&&f->ms->transient&&!f->ms->sampled&&!f->ms->view&&f->ms->usage==(VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT)&&f->color.samples==samples);vop p;assert(fb_target(id,&p)&&p.color==f->ms&&p.resolve==tex_get(c)->im&&p.depth==rbo_get(d)->im);for(int i=0;i<4;++i)assert(cinder_vk_target_ready(id));assert(ni==before+1);cinder_vk_target_destroy(id);assert(tex_get(c)&&rbo_get(d)&&retired==1);}
 reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_RGBA8,4),dd=storage(CINDER_VK_STORAGE_DEPTH16,4);uint32_t c=cinder_vk_attachment_create(&cd),d=cinder_vk_attachment_create(&dd);cinder_vk_target_create_desc td=target_desc(attachment_ref(c),attachment_ref(d),1);uint32_t id=cinder_vk_target_create(&td);vop p;assert(id&&fb_target(id,&p)&&p.color==rbo_get(c)->im&&p.depth==rbo_get(d)->im&&!p.resolve&&(p.color->usage&VK_IMAGE_USAGE_TRANSFER_SRC_BIT)&&p.color->samples==4);
 reset();puts("PASS depth-only/color-only/color+depth texture or attachment composition, metadata/stencil and exact extent/sample, eager2/4/8 MSRT/no draw-time allocation, raw-MSAA transferSRC legal allocation");
}
static void target_failures(void){
 for(int fault=0;fault<31;++fault){reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_RGBA8,1),dd=storage(CINDER_VK_STORAGE_DEPTH16,1);uint32_t c=cinder_vk_texture_storage(&cd),d=cinder_vk_attachment_create(&dd);vimg*ci=tex_get(c)->im,*di=rbo_get(d)->im;cinder_vk_target_create_desc td=target_desc(texture_ref(c),attachment_ref(d),0);unsigned before=ni,views_before=live_views;
  VkImageView save_view=ci->att;switch(fault){case 0:td.color.kind=(cinder_vk_image_kind)-1;break;case 1:td.color.kind=(cinder_vk_image_kind)3;break;case 2:td.color.id=0;break;case 3:td.color.id=127;break;case 4:td.color.kind=CINDER_VK_IMAGE_NONE;break;case 5:td.color=(cinder_vk_image_ref){0};td.depth_stencil=(cinder_vk_image_ref){0};break;case 6:td.depth_stencil.kind=CINDER_VK_IMAGE_TEXTURE;td.depth_stencil.id=c;break;case 7:td.color=attachment_ref(d);break;case 8:di->w++;break;case 9:di->h++;break;case 10:di->samples=2;break;case 11:ci->att=VK_NULL_HANDLE;break;case 12:ci->usage&=~VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;break;case 13:ci->levels=2;break;case 14:ci->layers=6;break;case 15:ci->native_upload_pending=1;break;case 16:ci->native_retire_pending=1;break;case 17:ci->aspect=VK_IMAGE_ASPECT_DEPTH_BIT;break;case 18:td.resolve_samples=3;break;case 19:td.resolve_samples=-1;break;case 20:td.resolve_samples=16;break;case 21:td.resolve_samples=4;break;case 22:td.color=(cinder_vk_image_ref){0};td.resolve_samples=4;break;case 23:di->img=VK_NULL_HANDLE;break;case 24:ci->native_target_refs=UINT32_MAX;break;case 25:di->native_target_refs=UINT32_MAX;break;case 26:fbo_fail=1;break;case 27:table_get_fail=1;break;case 28:n_compats=64;break;case 29:ci->uid=0;break;case 30:di->usage&=~VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT;break;}
  VkImage saved_image=H(VkImage,2);assert(!cinder_vk_target_create(&td)&&errors==1&&!fbo_get(1)&&ni==before&&live_views==views_before&&live_images==2&&tex_get(c)&&rbo_get(d));if(fault!=24)assert(!ci->native_target_refs);if(fault!=25)assert(!di->native_target_refs);
  ci->native_upload_pending=ci->native_retire_pending=0;ci->native_target_refs=di->native_target_refs=0;ci->att=save_view;if(fault==23)di->img=saved_image;
 }
 for(int fault=0;fault<10;++fault){reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_RGBA8,1),dd=storage(CINDER_VK_STORAGE_DEPTH16,4);uint32_t c=cinder_vk_texture_storage(&cd),d=cinder_vk_attachment_create(&dd);vimg*ci=tex_get(c)->im,*di=rbo_get(d)->im;cinder_vk_target_create_desc td=target_desc(texture_ref(c),attachment_ref(d),4);unsigned before=ni,views_before=live_views;
 switch(fault){case 0:query_fail_at=queries+1;break;case 1:caps.sampleCounts=1;break;case 2:calloc_fail_at=calloc_calls+1;break;case 3:image_fault=1;break;case 4:image_fault=2;break;case 5:image_fault=3;break;case 6:view_fail_at=(int)nv+1;break;case 7:view_null_at=(int)nv+1;break;case 8:fbo_fail=1;break;case 9:n_compats=64;break;}
 assert(!cinder_vk_target_create(&td)&&errors==1&&live_images==2&&live_views==views_before&&live_memory==2&&!ci->native_target_refs&&!di->native_target_refs&&!fbo_get(1)&&!retired&&tex_get(c)&&rbo_get(d));assert(ni==before+(fault<3?0:1));}
 reset();assert(!cinder_vk_target_create(NULL)&&errors==1&&!ni);
 reset();puts("PASS wrong role/kind/NONE-ID/missing-image/usage/view/extent/sample/aspect/pending-loader/retired/overflow refs reject; second-hold/table/compat/MS capability+image/view failures rollback all borrowed refs and unpublished MS storage");
}
static void strong_lifetime(void){
 reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_RGBA8,1),dd=storage(CINDER_VK_STORAGE_DEPTH24_STENCIL8,1);uint32_t c=cinder_vk_texture_storage(&cd),d=cinder_vk_attachment_create(&dd);vimg*ci=tex_get(c)->im,*di=rbo_get(d)->im;cinder_vk_target_create_desc td=target_desc(texture_ref(c),attachment_ref(d),0);uint32_t a=cinder_vk_target_create(&td),b=cinder_vk_target_create(&td);assert(a&&b&&ci->native_target_refs==2&&di->native_target_refs==2);ci->serial=27;di->serial=29;
 cinder_vk_texture_destroy(c);cinder_vk_attachment_destroy(d);assert(ci->native_retire_pending&&di->native_retire_pending&&!retired);uint32_t c2=cinder_vk_texture_storage(&cd),d2=cinder_vk_attachment_create(&dd);assert(c2==c&&d2==d&&tex_get(c)->im!=ci&&rbo_get(d)->im!=di);vop p;assert(fb_target(a,&p)&&p.color==ci&&p.depth==di&&fb_target(b,&p)&&p.color==ci&&p.depth==di);assert(cinder_vk_target_ready(a)&&cinder_vk_target_ready(b));collect(UINT64_MAX);assert(live_images==4);
 cinder_vk_target_destroy(a);assert(ci->native_target_refs==1&&di->native_target_refs==1&&!retired);cinder_vk_target_destroy(b);assert(retired==2&&live_images==4);collect(26);assert(live_images==4);collect(27);assert(live_images==3);collect(28);assert(live_images==3);collect(29);assert(live_images==2&&tex_get(c)&&rbo_get(d));
 reset();c=cinder_vk_texture_storage(&cd);d=cinder_vk_attachment_create(&dd);ci=tex_get(c)->im;di=rbo_get(d)->im;td=target_desc(texture_ref(c),attachment_ref(d),0);a=cinder_vk_target_create(&td);cinder_vk_target_destroy(a);assert(!ci->native_target_refs&&!di->native_target_refs&&!ci->native_retire_pending&&!di->native_retire_pending&&!retired&&tex_get(c)&&rbo_get(d));cinder_vk_attachment_destroy(d);assert(retired==1);cinder_vk_texture_destroy(c);assert(retired==2);collect(19);assert(!live_images);
 reset();c=cinder_vk_texture_storage(&cd);d=cinder_vk_attachment_create(&dd);uint32_t other=cinder_vk_texture_storage(&cd);di=rbo_get(d)->im;td=target_desc(texture_ref(c),attachment_ref(d),0);a=cinder_vk_target_create(&td);td.color=texture_ref(other);b=cinder_vk_target_create(&td);assert(di->native_target_refs==2);cinder_vk_attachment_destroy(d);cinder_vk_target_destroy(a);assert(di->native_target_refs==1&&!retired);cinder_vk_target_destroy(b);assert(retired==1&&tex_get(c)&&tex_get(other));collect(19);assert(live_images==2);
 reset();cd=storage(CINDER_VK_STORAGE_RGBA8,4);dd=storage(CINDER_VK_STORAGE_DEPTH16,4);c=cinder_vk_attachment_create(&cd);d=cinder_vk_attachment_create(&dd);ci=rbo_get(c)->im;di=rbo_get(d)->im;td=target_desc(attachment_ref(c),attachment_ref(d),0);a=cinder_vk_target_create(&td);cinder_vk_attachment_destroy(c);cinder_vk_attachment_destroy(d);c=cinder_vk_attachment_create(&cd);d=cinder_vk_attachment_create(&dd);assert(fb_target(a,&p)&&p.color==ci&&p.depth==di);cinder_vk_target_destroy(a);assert(retired==2);collect(19);assert(live_images==2);
 reset();puts("PASS strong snapshot lifetime: delete/reuse texture+attachment IDs cannot alias, multiple targets/shared depth/raw-MSAA retain originals, target-before/after public deletion, serial-delayed exactly-once retirement without deleting borrowed handles");
}
static void loader_target_lifetime(void){
 for(int complete_first=0;complete_first<2;++complete_first){reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_RGBA8,1);uint32_t c=cinder_vk_texture_storage(&cd);vimg*im=tex_get(c)->im;cinder_vk_target_create_desc td=target_desc(texture_ref(c),(cinder_vk_image_ref){0},0);uint32_t a=cinder_vk_target_create(&td),b=cinder_vk_target_create(&td);assert(a&&b&&native_image_upload_hold(im)&&im->native_target_refs==2&&im->native_upload_pending);assert(!cinder_vk_target_create(&td));cinder_vk_texture_destroy(c);assert(im->native_retire_pending&&!retired);im->serial=51;D.serial=43;
 if(complete_first){native_image_upload_complete();assert(!im->native_upload_pending&&!retired&&im->native_target_refs==2);cinder_vk_target_destroy(a);cinder_vk_target_destroy(b);}else{cinder_vk_target_destroy(a);assert(im->native_target_refs==1&&!retired);cinder_vk_target_destroy(b);assert(!im->native_target_refs&&!retired&&im->native_upload_pending);native_image_upload_complete();}
 assert(retired==1&&!n_native_upload_images&&dead_images[0].serial==51);collect(50);assert(live_images==1);collect(51);assert(!live_images&&!live_views&&!live_memory);}
 reset();puts("PASS actual loader+target refs combine: upload completion before/after final target release, pending handoff admission rejects, public deletion cannot retire either lease, max frame/image serial retirement exactly once");
}
static VkFramebuffer cache_target(uint32_t target,int width,int height,uint64_t last_use){vop p;assert(fb_target(target,&p));VkImageView v[3];int n=0;if(p.color)v[n++]=p.color->att;if(p.depth)v[n++]=p.depth->att;if(p.resolve)v[n++]=p.resolve->att;VkFramebuffer fb=fb_get(p.compat,v,n,width,height);assert(fb&&framebuffers[(uintptr_t)fb].live);framebuffers[(uintptr_t)fb].last_use=last_use;return fb;}
static void framebuffer_lifetime(void){
 reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_RGBA8,1),dd=storage(CINDER_VK_STORAGE_DEPTH24_STENCIL8,1);uint32_t c=cinder_vk_texture_storage(&cd),d=cinder_vk_attachment_create(&dd);vimg*ci=tex_get(c)->im,*di=rbo_get(d)->im;cinder_vk_target_create_desc td=target_desc(texture_ref(c),attachment_ref(d),0);uint32_t a=cinder_vk_target_create(&td),b=cinder_vk_target_create(&td);td.color=(cinder_vk_image_ref){0};uint32_t depth_only=cinder_vk_target_create(&td);assert(a&&b&&depth_only);VkFramebuffer first=cache_target(a,17,9,51);assert(cache_target(b,17,9,51)==first&&framebuffer_calls==1);assert(cache_target(b,16,8,51)!=first);cache_target(depth_only,17,9,53);assert(n_fbs==3&&live_framebuffers==3);ci->serial=51;di->serial=53;D.serial=44;completed_serial=42;
 cinder_vk_texture_destroy(c);cinder_vk_attachment_destroy(d);assert(cinder_vk_texture_storage(&cd)==c&&cinder_vk_attachment_create(&dd)==d);assert(ci!=tex_get(c)->im&&di!=rbo_get(d)->im&&live_framebuffers==3&&!framebuffer_destroys);assert(cache_target(a,17,9,51)==first);cinder_vk_target_destroy(a);cinder_vk_target_destroy(b);assert(!ci->native_target_refs&&di->native_target_refs==1&&retired==1&&n_fbs==3&&!framebuffer_destroys);collect(50);assert(live_framebuffers==3&&live_images==4);collect(51);assert(live_framebuffers==1&&n_fbs==1&&framebuffer_destroys==2&&live_images==3);cinder_vk_target_destroy(depth_only);assert(retired==1&&live_framebuffers==1);collect(52);assert(live_framebuffers==1&&live_images==3);collect(53);assert(!live_framebuffers&&!n_fbs&&framebuffer_destroys==3&&live_images==2);
 for(int complete_first=0;complete_first<2;++complete_first){reset();c=cinder_vk_texture_storage(&cd);ci=tex_get(c)->im;td=target_desc(texture_ref(c),(cinder_vk_image_ref){0},0);a=cinder_vk_target_create(&td);cache_target(a,17,9,61);ci->serial=61;D.serial=60;completed_serial=59;assert(native_image_upload_hold(ci));cinder_vk_texture_destroy(c);if(complete_first){native_image_upload_complete();assert(!retired&&live_framebuffers==1);cinder_vk_target_destroy(a);}else{cinder_vk_target_destroy(a);assert(!retired&&live_framebuffers==1);native_image_upload_complete();}assert(retired==1&&live_framebuffers==1&&!framebuffer_destroys);collect(60);assert(live_framebuffers==1);collect(61);assert(!live_framebuffers&&!n_fbs&&!live_images&&framebuffer_destroys==1);}
 reset();c=cinder_vk_texture_storage(&cd);ci=tex_get(c)->im;int compat=native_compat_id(ci->fmt,VK_FORMAT_UNDEFINED,1,0);VkFramebuffer direct=fb_get(compat,&ci->att,1,17,9);framebuffers[(uintptr_t)direct].last_use=81;ci->serial=81;D.serial=80;completed_serial=79;tex_get(c)->im=NULL;tex_release(c);image_drop(ci);assert(retired==1&&live_framebuffers==1&&!framebuffer_destroys);collect(80);assert(live_framebuffers==1);collect(81);assert(!live_framebuffers&&!live_images&&framebuffer_destroys==1);
 reset();puts("PASS actual fb_get/cache forget: shared targets + multi-entry color/depth and public-ID reuse retain cached framebuffer until final target/loader AND safe serial; forget destroys framebuffer before attachment views/image, direct shared image_drop too; real cache mutex paths complete without deadlock");
}
static void ready_corruption(void){
 for(int fault=0;fault<50;++fault){reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_RGBA8,1),dd=storage(CINDER_VK_STORAGE_DEPTH16,4);uint32_t c=cinder_vk_texture_storage(&cd),d=cinder_vk_attachment_create(&dd);cinder_vk_target_create_desc td=target_desc(texture_ref(c),attachment_ref(d),4);uint32_t id=cinder_vk_target_create(&td);assert(id);vfbo*f=fbo_get(id),saved=*f;vimg*ms=f->ms,*ci=f->native_color,*di=f->native_depth;vimg old_ms=*ms,old_ci=*ci,old_di=*di;unsigned before=ni;
 switch(fault){case 0:f->ms=NULL;break;case 1:ms->w++;break;case 2:ms->h++;break;case 3:ms->samples=2;break;case 4:ms->usage&=~VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;break;case 5:ms->implicit=0;break;case 6:ms->transient=0;break;case 7:ms->sampled=1;break;case 8:ms->levels=2;break;case 9:ms->layers=2;break;case 10:ms->aspect=VK_IMAGE_ASPECT_DEPTH_BIT;break;case 11:ms->fmt=VK_FORMAT_R5G6B5_UNORM_PACK16;break;case 12:ms->img=VK_NULL_HANDLE;break;case 13:ms->uid=0;break;case 14:ms->att=VK_NULL_HANDLE;break;case 15:ms->usage|=VK_IMAGE_USAGE_TRANSFER_SRC_BIT;break;case 16:f->color.samples=1;break;case 17:f->color.kind=2;break;case 18:f->native=0;break;case 19:f->native_color=NULL;break;case 20:ci->img=VK_NULL_HANDLE;break;case 21:ci->uid=0;break;case 22:ci->att=VK_NULL_HANDLE;break;case 23:ci->view=VK_NULL_HANDLE;break;case 24:ci->usage&=~VK_IMAGE_USAGE_SAMPLED_BIT;break;case 25:ci->usage&=~VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;break;case 26:ci->aspect=VK_IMAGE_ASPECT_DEPTH_BIT;break;case 27:ci->levels=2;break;case 28:ci->layers=2;break;case 29:ci->samples=2;break;case 30:ci->native_target_refs=0;break;case 31:ci->native_upload_pending=1;break;case 32:di->uid=0;break;case 33:di->img=VK_NULL_HANDLE;break;case 34:di->att=VK_NULL_HANDLE;break;case 35:di->aspect=VK_IMAGE_ASPECT_COLOR_BIT;break;case 36:di->levels=2;break;case 37:di->layers=2;break;case 38:di->samples=1;break;case 39:f->depth.kind=1;break;case 40:di->native_target_refs=0;break;case 41:di->native_upload_pending=1;break;case 42:f->native_depth=NULL;break;case 43:f->depth.kind=0;break;case 44:ci->sampled=0;break;case 45:di->sampled=1;break;case 46:f->color.samples=3;break;case 47:ci->fmt=VK_FORMAT_D16_UNORM;break;case 48:di->fmt=VK_FORMAT_R8G8B8A8_UNORM;break;case 49:ci->w=0;break;}
 assert(!cinder_vk_target_ready(id)&&ni==before);*f=saved;*ms=old_ms;*ci=old_ci;*di=old_di;
 }
 for(int fault=0;fault<3;++fault){reset();cinder_vk_storage_desc dd=storage(CINDER_VK_STORAGE_DEPTH24_STENCIL8,1);uint32_t d=cinder_vk_texture_storage(&dd);cinder_vk_target_create_desc td=target_desc((cinder_vk_image_ref){0},texture_ref(d),0);uint32_t id=cinder_vk_target_create(&td);assert(id);vimg*di=tex_get(d)->im,old=*di;unsigned before=ni;if(fault==0)di->view=VK_NULL_HANDLE;if(fault==1)di->usage&=~VK_IMAGE_USAGE_SAMPLED_BIT;if(fault==2)di->samples=2;assert(!cinder_vk_target_ready(id)&&ni==before);*di=old;}
 reset();cinder_vk_storage_desc cd=storage(CINDER_VK_STORAGE_RGBA8,1);uint32_t c=cinder_vk_texture_storage(&cd);cinder_vk_target_create_desc td=target_desc(texture_ref(c),(cinder_vk_image_ref){0},0);uint32_t a=cinder_vk_target_create(&td);assert(a&&n_compats==1&&renderpass_calls==1);n_compats=64;uint32_t b=cinder_vk_target_create(&td);assert(b&&b!=a&&n_compats==64&&renderpass_calls==1&&tex_get(c)->im->native_target_refs==2);cd.format=CINDER_VK_STORAGE_RGB565;c=cinder_vk_texture_storage(&cd);td.color=texture_ref(c);assert(!cinder_vk_target_create(&td)&&n_compats==64&&renderpass_calls==1&&!tex_get(c)->im->native_target_refs&&cinder_vk_target_ready(a)&&cinder_vk_target_ready(b));
 reset();puts("PASS 53 native readiness corruptions failclosed with no lazy allocation; actual compatibility cache accepts existing exact key at capacity but rejects new kinds without aliasing0");
}
int main(void){setvbuf(stdout,NULL,_IONBF,0);formats();invalid_storage();allocation_failures();composition();target_failures();strong_lifetime();loader_target_lifetime();framebuffer_lifetime();ready_corruption();reset();puts("native Vulkan storage+targets: production CPU sanitizer PASS (NOT GPU pixels/validation)");return 0;}
'''

fixture = prefix + ''.join(schema(n) for n in ('vimg', 'vrbo', 'vatt', 'vfbo', 'vop', 'compat_t', 'rp_t', 'fbent')) + state + actual + '\n#include "native_vk_targets.inc"\n' + tests
assert not re.search(r'\b(?:GLenum|GLuint|GLint|GL_\w+|vctx|vvao)\b', fixture)
with tempfile.TemporaryDirectory(prefix='targets-', dir=OUT) as directory:
    directory = Path(directory)
    (directory / 'targets.c').write_text(fixture)
    flags = ['-I', str(ROOT / 'src')]
    if sys.platform == 'darwin':
        flags += ['-I', '/opt/homebrew/include']
    sanitizer = os.environ.get('NATIVE_VK_SANITIZERS', 'undefined' if sys.platform == 'darwin' else 'address,undefined')
    command = [os.environ.get('CC', 'clang'), '-std=gnu11', '-Wall', '-Wextra', '-Werror',
               '-Wno-missing-field-initializers', '-fsanitize=' + sanitizer, '-fno-sanitize-recover=all',
               '-fno-omit-frame-pointer', *flags, str(directory / 'targets.c'), '-pthread', '-lm', '-o', str(directory / 'targets')]
    subprocess.run(command, cwd=directory, check=True, timeout=120)
    subprocess.run([str(directory / 'targets')], cwd=directory, check=True,
                   timeout=int(os.environ.get('NATIVE_VK_TEST_TIMEOUT', '30')))
    print('sanitizers', sanitizer)
for path in ('src/native_vk_targets.inc', 'tests/test_native_vk_targets_host.py', 'src/native_vk.h', 'src/vkgl.c',
             'src/native_vk_resources.inc', 'src/native_vk.inc'):
    print(path, hashlib.sha256((ROOT / path).read_bytes()).hexdigest())
