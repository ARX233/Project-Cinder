#!/usr/bin/env python3
"""Actual native RGBA upload/stream, recoverable allocator and shared UID contracts.
Vulkan/memory/upload queues are mocks; no ctx/GL type or binding API is declared.
Not driver validation, GPU pixels, asynchronous completion or performance proof.
"""
from pathlib import Path
import os,re,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[1]
O=Path(os.environ.get('TMPDIR','/Volumes/CodexWork')).resolve()
assert O==Path('/Volumes/CodexWork') or str(O).startswith('/Volumes/CodexWork/')
S=(R/'src/vkgl.c').read_text(); N=(R/'src/native_vk.inc').read_text(); A=(R/'src/native_vk_objects.inc').read_text()
def fun(source,anchor):
 a=source.index(anchor); b=source.index('{',a)
 mask=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),source,flags=re.S);depth=0
 for i in range(b,len(source)):
  depth+=(mask[i]=='{')-(mask[i]=='}')
  if not depth:return source[a:i+1]
 raise ValueError(anchor)
assert '++D.uid' not in S and '__atomic_add_fetch(&D.uid' not in S
assert '_Atomic uint64_t serial;' in S
assert 'im->uid = ok == 0 ? resource_uid_next() : 0;' in S
assert 'im->uid = resource_uid_next();' in S
assert S.count('p->uid = resource_uid_next()')==3
assert 'cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER);' in fun(S,'void vkgl_thread_loader(')
pre=r'''
#include <assert.h>
#include <limits.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "native_vk.h"
#define H(T,x) ((T)(uintptr_t)(x))
typedef struct {int block;VkDeviceSize off,size;} vmem;
typedef struct {VkBuffer buf;vmem mem;uint8_t*map;VkDeviceSize size;uint64_t serial;} vbufmem;
typedef struct {VkImage img;VkImageView att;VkImageLayout rest;int in_rest,defined;unsigned level_mask,uid;uint64_t serial;int native_upload_pending,native_retire_pending;uint32_t native_target_refs;} vimg;
typedef struct {int used;vimg*im;cinder_vk_sampler native_sampler;} vtex;
typedef struct {size_t n,i;VkDeviceSize used;} ring;
typedef struct {VkCommandPool pool;VkCommandBuffer cmd;ring stage;int tag,open;VkFence fence;} uploader;
static struct {VkDevice dev;VkPhysicalDeviceProperties props;uint32_t uid;_Atomic uint64_t serial;pthread_mutex_t lock;} D={.lock=PTHREAD_MUTEX_INITIALIZER};
static struct {VkDeviceMemory mem;} blocks[1]={{H(VkDeviceMemory,8)}};
static struct {uploader up;} frame,*F=&frame;
static uploader LOADER_UP;
static const VkComponentMapping SWZ_ID={VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY,VK_COMPONENT_SWIZZLE_IDENTITY};
static unsigned errors,commands,barriers,copies,settles,created_images,live_images,freed_images,table_calls,table_fail,retired,flushes;
static int image_fail,ring_fail,ring_bad_buffer,ring_bad_offset,active_upload_tag,begin_fail,lease_fail;
static VkResult wait_result,submit_result,end_result,fence_result,pool_result;
static unsigned wait_calls;
static int native_loader_failed;
static vimg **native_upload_images;static size_t n_native_upload_images,cap_native_upload_images;
static void native_image_upload_complete(void);
static void *lease_realloc(void*p,size_t n){return lease_fail?NULL:realloc(p,n);}
#define realloc lease_realloc
static VkFormatFeatureFlags features;
static uint8_t staging_bytes[1024];static VkDeviceSize staged_size;
static VkBufferImageCopy last_copy;static vtex textures[16];
static int native_reject(void){++errors;return 0;}
static vtex*tex_get(uint32_t id){return id<16&&textures[id].used?&textures[id]:NULL;}
static uint32_t tex_gen(void){++table_calls;if(table_fail)return 0;for(unsigned i=1;i<16;++i)if(!textures[i].used){memset(&textures[i],0,sizeof textures[i]);textures[i].used=1;return i;}return 0;}
static void tex_release(uint32_t id){assert(tex_get(id));textures[id].used=0;}
static int fmt_has(VkFormat format,VkFormatFeatureFlags want){assert(format==VK_FORMAT_R8G8B8A8_UNORM);return (features&want)==want;}
static VkCommandBuffer native_up_cmd(uploader*u){assert(u);if(begin_fail)return VK_NULL_HANDLE;++commands;u->open=1;active_upload_tag=u->tag;return u->cmd;}
static uint8_t*native_ring_alloc(ring*r,VkDeviceSize size,VkDeviceSize align,VkBuffer*buffer,VkDeviceSize*offset){assert(size<=sizeof staging_bytes-r->used&&align==16);staged_size=size;*buffer=ring_bad_buffer?VK_NULL_HANDLE:H(VkBuffer,5);*offset=ring_bad_offset?3:16+r->used;if(ring_fail)return NULL;uint8_t*out=staging_bytes+r->used;++r->i;r->used+=size;return out;}
static void barrier(VkCommandBuffer cmd,const vimg*im,int l,int ls,int a,int as,VkImageLayout from,VkImageLayout to){assert(cmd&&im&&l==0&&ls==1&&a==0&&as==1);assert((from==VK_IMAGE_LAYOUT_UNDEFINED&&to==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL)||(from==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL&&to==VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL));++barriers;}
static void fake_copy(VkCommandBuffer cmd,VkBuffer buffer,VkImage image,VkImageLayout layout,uint32_t n,const VkBufferImageCopy*copy){assert(cmd&&buffer&&image&&layout==VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL&&n==1);last_copy=*copy;++copies;}
#define vkCmdCopyBufferToImage fake_copy
static VkResult submit(VkCommandBuffer*cmd,uint32_t n,VkSemaphore wait,VkSemaphore signal,VkFence fence){assert(cmd&&*cmd&&n==1&&!wait&&!signal&&fence);++flushes;return submit_result;}
static VkResult fake_end(VkCommandBuffer cmd){assert(cmd);return end_result;}
static VkResult fake_wait(VkDevice dev,uint32_t n,const VkFence*f,VkBool32 all,uint64_t timeout){assert(dev&&n==1&&f&&*f&&all&&timeout==UINT64_MAX);++wait_calls;return wait_result;}
static VkResult fake_fence_reset(VkDevice dev,uint32_t n,const VkFence*f){assert(dev&&n==1&&f&&*f);return fence_result;}
static VkResult fake_pool_reset(VkDevice dev,VkCommandPool pool,VkCommandPoolResetFlags flags){assert(dev&&pool&&!flags);return pool_result;}
#define vkEndCommandBuffer fake_end
#define vkWaitForFences fake_wait
#define vkResetFences fake_fence_reset
#define vkResetCommandPool fake_pool_reset
#define VKCHECK(e) ((void)(e))
static void image_free_now(vimg*im){assert(im);++freed_images;--live_images;free(im);}
#define DEAD_IMAGE 1
static struct {vimg*image;uint64_t serial;} dead[32];
static void dead_add(int kind,void*p,uint64_t h,uint64_t serial){assert(kind==DEAD_IMAGE&&p&&!h&&retired<32);dead[retired++]=(typeof(dead[0])){p,serial};}
static unsigned buffer_creates,buffer_destroys,buffer_live,memory_frees,memory_live;static int buffer_fault;static VkDeviceSize requested_size;
static uint8_t memory_map[1024];
static VkResult fake_create_buffer(VkDevice dev,const VkBufferCreateInfo*ci,const VkAllocationCallbacks*a,VkBuffer*out){(void)a;assert(dev&&ci->size&&ci->usage);++buffer_creates;requested_size=ci->size;if(buffer_fault==1)return VK_ERROR_OUT_OF_HOST_MEMORY;*out=H(VkBuffer,100+buffer_creates);++buffer_live;return VK_SUCCESS;}
static void fake_buffer_requirements(VkDevice dev,VkBuffer buffer,VkMemoryRequirements*out){assert(dev&&buffer);*out=(VkMemoryRequirements){.size=requested_size,.alignment=16,.memoryTypeBits=1};}
static int mem_alloc(VkMemoryRequirements r,VkMemoryPropertyFlags want,VkMemoryPropertyFlags pref,int image,vmem*out){assert(r.size==requested_size&&want==(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)&&pref==VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT&&!image);if(buffer_fault==2)return -1;*out=(vmem){0,0,r.size};++memory_live;return 0;}
static VkResult fake_bind_buffer(VkDevice dev,VkBuffer buffer,VkDeviceMemory memory,VkDeviceSize offset){assert(dev&&buffer&&memory&&!offset);return buffer_fault==3?VK_ERROR_MEMORY_MAP_FAILED:VK_SUCCESS;}
static uint8_t*mem_map(const vmem*m){assert(m->block==0&&m->size==requested_size);return buffer_fault==4?NULL:memory_map;}
static void fake_destroy_buffer(VkDevice dev,VkBuffer buffer,const VkAllocationCallbacks*a){(void)a;assert(dev&&buffer&&buffer_live);++buffer_destroys;--buffer_live;}
static void mem_free(vmem*m){assert(m->block==0&&memory_live);++memory_frees;--memory_live;m->block=-1;}
#define vkCreateBuffer fake_create_buffer
#define vkGetBufferMemoryRequirements fake_buffer_requirements
#define vkBindBufferMemory fake_bind_buffer
#define vkDestroyBuffer fake_destroy_buffer
'''
# Execute the exact native-program UID sequence concurrently with the shared one.
x=A.index('  uint32_t uid = __atomic_load_n(&D.uid'); y=A.index('  memcpy(p.key',x)
program_uid='static uint32_t program_uid(void){struct{uint32_t uid;}p;\n'+A[x:y]+'return p.uid;fail:return 0;}\n'
image_stub=r'''
static vimg*image_new(VkFormat format,int w,int h,int levels,int layers,int samples,int sampled,int transient,VkComponentMapping swz){assert(format==VK_FORMAT_R8G8B8A8_UNORM&&w>0&&h>0&&levels==1&&layers==1&&samples==1&&sampled==1&&!transient&&!memcmp(&swz,&SWZ_ID,sizeof swz));++created_images;if(image_fail)return NULL;vimg*im=calloc(1,sizeof *im);assert(im);im->uid=resource_uid_next();if(!im->uid){free(im);return NULL;}im->img=H(VkImage,created_images+10);im->rest=VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;++live_images;return im;}
'''
post=r'''
static cinder_vk_sampler sampler(void){return (cinder_vk_sampler){.use_state=1,.mipmaps=0,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_LINEAR,.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,.address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.anisotropy=1};}
static void reset(void){
 native_image_upload_complete();free(native_upload_images);native_upload_images=NULL;n_native_upload_images=cap_native_upload_images=0;
 for(unsigned i=1;i<16;++i)if(textures[i].used&&textures[i].im)image_free_now(textures[i].im);
 for(unsigned i=0;i<retired;++i)image_free_now(dead[i].image);
 assert(!live_images);memset(textures,0,sizeof textures);retired=errors=commands=barriers=copies=settles=created_images=freed_images=table_calls=table_fail=flushes=0;
 image_fail=ring_fail=ring_bad_buffer=ring_bad_offset=begin_fail=lease_fail=0;wait_result=submit_result=end_result=fence_result=pool_result=VK_SUCCESS;wait_calls=0;native_loader_failed=0;D.dev=H(VkDevice,1);D.props.limits.maxImageDimension2D=4096;D.uid=0;D.serial=19;
 frame.up=(uploader){.pool=H(VkCommandPool,1),.cmd=H(VkCommandBuffer,2),.tag=1,.fence=H(VkFence,5)};LOADER_UP=(uploader){.pool=H(VkCommandPool,3),.cmd=H(VkCommandBuffer,4),.tag=2,.fence=H(VkFence,6)};F=&frame;
 memset(staging_bytes,0xcc,sizeof staging_bytes);features=VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT|VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT|VK_FORMAT_FEATURE_TRANSFER_SRC_BIT|VK_FORMAT_FEATURE_TRANSFER_DST_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
 assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_FRAME));
}
static void upload(void){reset();uint8_t pixels[40];for(unsigned i=0;i<sizeof pixels;++i)pixels[i]=(uint8_t)i;cinder_vk_sampler s=sampler();uint32_t id=cinder_vk_texture_rgba8(2,4,pixels,sizeof pixels,&s);assert(id&&tex_get(id)&&live_images==1&&commands==1&&copies==1&&barriers==2&&staged_size==32&&!memcmp(staging_bytes,pixels,32)&&staging_bytes[32]==0xcc&&active_upload_tag==1);
 assert(last_copy.bufferOffset==16&&!last_copy.bufferRowLength&&!last_copy.bufferImageHeight&&last_copy.imageSubresource.aspectMask==VK_IMAGE_ASPECT_COLOR_BIT&&last_copy.imageSubresource.mipLevel==0&&last_copy.imageSubresource.layerCount==1&&last_copy.imageExtent.width==2&&last_copy.imageExtent.height==4&&last_copy.imageExtent.depth==1);
 vimg*im=tex_get(id)->im;assert(im->level_mask==1&&im->in_rest&&im->defined&&!memcmp(&tex_get(id)->native_sampler,&s,sizeof s));
 cinder_vk_texture_destroy(id);assert(!tex_get(id)&&!freed_images&&retired==1&&dead[0].image==im&&dead[0].serial==19);assert(im->img); /* recorded-use retirement, not immediate destruction */
 cinder_vk_texture_destroy(0);assert(!errors);cinder_vk_texture_destroy(id);assert(errors==1&&retired==1);
 reset();puts("PASS actual RGBA upload spans/bytes/regions/layouts/typed sampler/publication and deferred image retirement");}
#define BAD(change,call) do{reset();uint8_t pixels[32]={0};cinder_vk_sampler s=sampler();(void)pixels;(void)s;change;assert(!(call)&&errors==1&&!table_calls&&!commands&&!copies&&!barriers&&!live_images);}while(0)
static void failures(void){
 BAD((void)0,cinder_vk_texture_rgba8(0,4,pixels,32,&s));BAD((void)0,cinder_vk_texture_rgba8(2,-1,pixels,32,&s));BAD((void)0,cinder_vk_texture_rgba8(4097,1,pixels,SIZE_MAX,&s));
 BAD((void)0,cinder_vk_texture_rgba8(2,4,NULL,32,&s));BAD((void)0,cinder_vk_texture_rgba8(2,4,pixels,31,&s));BAD((void)0,cinder_vk_texture_rgba8(2,4,pixels,32,NULL));
 BAD(s.use_state=0,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(s.mipmaps=1,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(s.min_filter=(VkFilter)-1,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(s.address_u=(VkSamplerAddressMode)-1,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(s.anisotropy=NAN,cinder_vk_texture_rgba8(2,4,pixels,32,&s));
 BAD(D.props.limits.maxImageDimension2D=UINT32_MAX,cinder_vk_texture_rgba8(INT_MAX,INT_MAX,pixels,SIZE_MAX,&s));
 BAD(F=NULL,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(D.dev=VK_NULL_HANDLE,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(frame.up.cmd=VK_NULL_HANDLE,cinder_vk_texture_rgba8(2,4,pixels,32,&s));
 BAD(features&=~VK_FORMAT_FEATURE_TRANSFER_DST_BIT,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(features&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(image_fail=1,cinder_vk_texture_rgba8(2,4,pixels,32,&s));
 BAD(ring_fail=1,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(ring_bad_buffer=1,cinder_vk_texture_rgba8(2,4,pixels,32,&s));BAD(ring_bad_offset=1,cinder_vk_texture_rgba8(2,4,pixels,32,&s));
 reset();uint8_t pixels[32]={0};cinder_vk_sampler s=sampler();table_fail=1;assert(!cinder_vk_texture_rgba8(2,4,pixels,32,&s)&&errors==1&&table_calls==1&&!commands&&!live_images&&freed_images==1);
 reset();begin_fail=1;assert(!cinder_vk_texture_rgba8(2,4,pixels,32,&s)&&errors==1&&table_calls==1&&!commands&&!barriers&&!copies&&!live_images&&!tex_get(1));
 reset();lease_fail=1;assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));assert(!cinder_vk_texture_rgba8(2,4,pixels,32,&s)&&errors==1&&!barriers&&!copies&&!live_images&&!tex_get(1)&&!n_native_upload_images);
 reset();D.uid=UINT32_MAX;assert(!cinder_vk_texture_rgba8(2,4,pixels,32,&s)&&!live_images&&!table_calls&&!commands);reset();puts("PASS invalid descriptors/spans/streams/caps and staged allocation failures never publish or issue image commands");}
static void*upload_worker(void*arg){(void)arg;assert(cinder_vk_upload_stream_get()==CINDER_VK_UPLOAD_FRAME);assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER)&&native_resource_up()==&LOADER_UP);assert(!cinder_vk_upload_stream_set((cinder_vk_upload_stream)-1)&&cinder_vk_upload_stream_get()==CINDER_VK_UPLOAD_LOADER);uint8_t pixels[32]={0};cinder_vk_sampler s=sampler();LOADER_UP.stage.n=5;assert(cinder_vk_texture_rgba8(2,4,pixels,32,&s)&&active_upload_tag==2&&flushes==1);return NULL;}
static void staging_rollback(void){
 for(int fault=0;fault<5;++fault){reset();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));LOADER_UP.stage.i=1;LOADER_UP.stage.used=48;LOADER_UP.stage.n=3;LOADER_UP.open=1;
  uint8_t pixels[32]={0};cinder_vk_sampler s=sampler();memset(staging_bytes,0xed,48);
  switch(fault){case 0:table_fail=1;break;case 1:begin_fail=1;break;case 2:lease_fail=1;break;case 3:ring_bad_buffer=1;break;case 4:ring_bad_offset=1;break;}
  assert(!cinder_vk_texture_rgba8(2,4,pixels,32,&s)&&!copies&&!barriers&&!live_images&&!tex_get(1));
  assert(LOADER_UP.stage.i==1&&LOADER_UP.stage.used==48&&LOADER_UP.stage.n==3);for(unsigned i=0;i<48;++i)assert(staging_bytes[i]==0xed);
  table_fail=begin_fail=lease_fail=ring_bad_buffer=ring_bad_offset=0;assert(cinder_vk_texture_rgba8(2,4,pixels,32,&s));assert(LOADER_UP.stage.used==80&&LOADER_UP.stage.i==2);assert(last_copy.bufferOffset==64);
 }
 reset();puts("PASS convenience texture precommand failures restore staging cursor/prefix and permit retry; retained backing capacity unchanged (mock ring boundary)");
}
static void loader_retirement(void){
 reset();uint8_t pixels[32]={0};cinder_vk_sampler s=sampler();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));uint32_t id=cinder_vk_texture_rgba8(2,4,pixels,32,&s);assert(id&&n_native_upload_images==1);vimg*im=tex_get(id)->im;
 assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_FRAME));cinder_vk_texture_destroy(id);assert(!tex_get(id)&&!retired&&live_images==1&&im->native_upload_pending&&im->native_retire_pending);
 D.serial=22;uint64_t main_done=20;assert(!retired&&!freed_images); /* main serial19 is retired, loader cmd still references image */
 loader_flush();assert(flushes==1&&!n_native_upload_images&&retired==1&&dead[0].image==im&&dead[0].serial>main_done&&!freed_images);
 main_done=22;assert(dead[0].serial<=main_done);image_free_now(dead[0].image);retired=0;assert(!live_images);
 reset();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));id=cinder_vk_texture_rgba8(2,4,pixels,32,&s);im=tex_get(id)->im;cinder_vk_texture_destroy(id);wait_result=VK_TIMEOUT;loader_flush();D.serial=25;
 assert(n_native_upload_images==1&&im->native_upload_pending&&live_images==1&&!retired&&!freed_images&&native_loader_failed); /* unknown loader completion never becomes a main-serial lease */
 unsigned before=commands;assert(!cinder_vk_texture_rgba8(2,4,pixels,32,&s)&&commands==before&&n_native_upload_images==1);
 for(int fault=0;fault<5;++fault){
  reset();assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));LOADER_UP.stage.n=5;
  switch(fault){case 0:end_result=VK_ERROR_OUT_OF_HOST_MEMORY;break;case 1:submit_result=VK_ERROR_DEVICE_LOST;break;case 2:wait_result=VK_ERROR_DEVICE_LOST;break;case 3:fence_result=VK_ERROR_DEVICE_LOST;break;case 4:pool_result=VK_ERROR_DEVICE_LOST;break;}
  assert(!cinder_vk_texture_rgba8(2,4,pixels,32,&s)&&native_loader_failed&&!tex_get(1)&&errors==1&&live_images==1);
  if(fault<3)assert(n_native_upload_images==1&&!retired&&LOADER_UP.stage.used==32&&LOADER_UP.stage.i==1);else assert(!n_native_upload_images&&retired==1);
  if(fault<2)assert(!wait_calls); /* no hang on a fence whose submission failed */
 }
 reset();puts("PASS actual loader create/delete/main-retire counterexample: pinned until successful wait; GPU faults retain leases/block new uploads, no recovery claim");
}
static void streams(void){reset();F=NULL;pthread_t worker;assert(!pthread_create(&worker,NULL,upload_worker,NULL));assert(!pthread_join(worker,NULL));assert(cinder_vk_upload_stream_get()==CINDER_VK_UPLOAD_FRAME&&!native_resource_up());F=&frame;assert(native_resource_up()==&frame.up);reset();puts("PASS thread-local native upload stream, loader upload without main F, flush boundary, invalid selector and no GL context");}
static void allocator(void){reset();buffer_fault=0;unsigned destroy_before=buffer_destroys,free_before=memory_frees;vbufmem*m=bufmem_try_new(32,VK_BUFFER_USAGE_VERTEX_BUFFER_BIT);assert(m&&m->size==32&&m->map==memory_map&&buffer_live==1&&memory_live==1);fake_destroy_buffer(D.dev,m->buf,NULL);mem_free(&m->mem);free(m);assert(buffer_destroys==destroy_before+1&&memory_frees==free_before+1);
 for(int fault=1;fault<=4;++fault){buffer_fault=fault;destroy_before=buffer_destroys;free_before=memory_frees;assert(!bufmem_try_new(32,VK_BUFFER_USAGE_VERTEX_BUFFER_BIT)&&!buffer_live&&!memory_live);assert(buffer_destroys==destroy_before+(fault>1));assert(memory_frees==free_before+(fault>2));}
 buffer_fault=0;D.dev=VK_NULL_HANDLE;unsigned before=buffer_creates;assert(!bufmem_try_new(32,VK_BUFFER_USAGE_VERTEX_BUFFER_BIT)&&buffer_creates==before);reset();puts("PASS actual recoverable mapped-buffer allocator create/memory/bind/map failure cleanup");}
static uint32_t ids[4][2048];static void*uid_worker(void*arg){uintptr_t worker=(uintptr_t)arg;for(unsigned i=0;i<2048;++i)ids[worker][i]=worker%2?program_uid():resource_uid_next();return NULL;}
static void uids(void){reset();pthread_t worker[4];for(uintptr_t i=0;i<4;++i)assert(!pthread_create(&worker[i],NULL,uid_worker,(void*)i));for(unsigned i=0;i<4;++i)assert(!pthread_join(worker[i],NULL));unsigned char seen[8193]={0};for(unsigned i=0;i<4;++i)for(unsigned j=0;j<2048;++j){uint32_t id=ids[i][j];assert(id&&id<8193&&!seen[id]);seen[id]=1;}assert(D.uid==8192);D.uid=UINT32_MAX-1;assert(resource_uid_next()==UINT32_MAX&&!program_uid()&&!resource_uid_next()&&D.uid==UINT32_MAX);reset();puts("PASS real shared image/legacy UID allocator mixed with actual native program CAS: concurrent uniqueness and no wrap");}
int main(void){upload();failures();staging_rollback();loader_retirement();streams();allocator();uids();reset();return 0;}
'''
real=fun(S,'static uint32_t resource_uid_next(')+'\n'+fun(S,'static vbufmem *bufmem_try_new(')+'\n'+fun(N,'static int native_sampler_valid(')+'\n'+fun(S,'static int native_image_upload_hold(')+'\n'+fun(S,'static void image_drop(')+'\n'+fun(S,'static void native_image_upload_complete(')+'\n'+fun(S,'static void ring_reset(')+'\n'+fun(S,'static void loader_flush(')+'\n'
with tempfile.TemporaryDirectory(prefix='native-vk-resources-',dir=O) as d:
 d=Path(d);c=d/'resources.c';c.write_text(pre+real+program_uid+image_stub+(R/'src/native_vk_resources.inc').read_text()+post);binary=d/'resources'
 cmd=['clang','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-missing-field-initializers','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(R/'src')]
 if sys.platform=='darwin':cmd+=['-I','/opt/homebrew/include']
 subprocess.run(cmd+[str(c),'-pthread','-lm','-o',str(binary)],check=True,timeout=120)
 subprocess.run([str(binary)],check=True,timeout=30)
