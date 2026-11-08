#!/usr/bin/env python3
"""Actual view/constructor/sampler try boundaries; CPU/API/ownership, not GPU proof.
Native binding and expanded-view blocks are exact source slices, not full entrypoint
execution. Whole actual factory, cache, view helper and descriptor writer execute.
"""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('CINDER_TEST_OUT',os.environ.get('TMPDIR',tempfile.gettempdir()))).resolve()/'native-handle-try'
assert ROOT!=OUT and ROOT not in OUT.parents
OUT.mkdir(parents=True,exist_ok=True)
b=os.environ.get('CINDER_TRY_BASELINE');assert b,'set CINDER_TRY_BASELINE to Round9 Core file/tree'
BASE=Path(b).resolve()
if BASE.is_dir():BASE=BASE/('src/vkgl.c' if (BASE/'src/vkgl.c').is_file() else 'vkgl.c')
BASELINE=BASE.read_text();CURRENT=(ROOT/'src/vkgl.c').read_text()
NATIVE=(ROOT/'src/native_vk.inc').read_text();IMAGES=(ROOT/'src/native_vk_images.inc').read_text();MIP=(ROOT/'src/native_vk_mipmap.inc').read_text();PLATFORM=(ROOT/'src/native_vk_platform.inc').read_text()
H=lambda x:hashlib.sha256(x.encode()).hexdigest()
def fun(s,anchor):
 a=s.index(anchor);o=s.index('{',a);mask=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),s,flags=re.S);depth=0
 for i in range(o,len(s)):
  depth+=(mask[i]=='{')-(mask[i]=='}')
  if not depth:return s[a:i+1]+'\n'
 raise AssertionError(anchor)
def typedef(s,name):
 z=s.index('} '+name+';')+len('} '+name+';');matches=list(re.finditer(r'typedef struct(?:\s+[A-Za-z_]\w*)?\s*\{',s[:z]));assert matches;return s[matches[-1].start():z]+'\n'
sampler_start=CURRENT.index('typedef struct {',CURRENT.index('/* ---- samplers, by the texture'))
sampler_type=CURRENT[sampler_start:CURRENT.index('/* The cache/driver boundary',sampler_start)]
image_block=fun(IMAGES,'  if (im->view_levels != desc->levels)')
mip_block=fun(MIP,'  if (im->view_levels != base->levels)')
a=NATIVE.index('  for (int i = 0; i < p->n_samp; ++i) {',NATIVE.index('  dkey dk;'));z=NATIVE.index('  /* Open by explicit attachments',a)
bind_block=NATIVE[a:z]
for anchor in ['static void image_free_now(', 'static vimg *image_new_usage(', 'static VkDescriptorSet desc_get(']:assert fun(CURRENT,anchor)==fun(BASELINE,anchor),('protected actual caller changed',anchor)
prefix=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include "native_vk.h"
#define H(T,n) ((T)(uintptr_t)(n))
#define MAX_SAMP 8
#define DCACHE 1024
#define GROW(p,n,c) do{if((n)>=(c)){size_t cap=(c)?(c)*2:16;void*q=realloc((p),cap*sizeof *(p));assert(q);(p)=q;(c)=cap;}}while(0)
#define VKGL_SSAO_DEPTH_USAGE (VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT)
static int platform_native_profile,platform_created=1,native_upload_stream=CINDER_VK_UPLOAD_FRAME;
static struct {VkDevice dev;VkPipelineCache pcache;char pcache_path[1024];uint32_t lazy_type;uint64_t serial;int aniso;float max_aniso;pthread_mutex_t lock,plock;}D={.dev=H(VkDevice,1),.lazy_type=~0u,.serial=1,.aniso=1,.max_aniso=8,.lock=PTHREAD_MUTEX_INITIALIZER,.plock=PTHREAD_MUTEX_INITIALIZER};
static unsigned created_views[4096],created_images[4096],created_samplers[4096];
static int view_calls,sampler_calls,bad_destroy,good_destroy,image_destroy,mem_frees,rejects,updates,bad_updates,fb_forget;
static int fault_view_at,view_fault,sampler_fault;static unsigned seq=100;static uint32_t uid=10;
static int cache_calls,cache_created,cache_destroys,cache_merges,cache_bad_merge,cache_alias,cache_fault,cache_refs[32];
#define logf_(...) ((void)0)
'''
mocks=r'''
static struct{VkDeviceMemory mem;}blocks[1]={{H(VkDeviceMemory,7)}};
static uint32_t resource_uid_next(void){return ++uid;}
static int mem_alloc(VkMemoryRequirements r,VkMemoryPropertyFlags w,VkMemoryPropertyFlags p,int image,vmem*m){(void)w;(void)p;assert(image);*m=(vmem){.block=0,.off=0,.size=r.size};return 0;}
static void mem_free(vmem*m){assert(m->block==0);m->block=-1;++mem_frees;}
static void fb_cache_forget(VkImageView v){assert(v);++fb_forget;}
static int native_reject(void){++rejects;return 0;}
static uint64_t hash_bytes(const void*p,size_t n){const unsigned char*b=p;uint64_t h=5381;while(n--)h=h*33+*b++;return h;}
static VkDescriptorSet desc_alloc(int n){assert(n>=0&&n<=MAX_SAMP);return H(VkDescriptorSet,41);}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateImage(VkDevice d,const VkImageCreateInfo*i,const VkAllocationCallbacks*a,VkImage*out){(void)a;assert(d&&i->extent.width);*out=H(VkImage,++seq);created_images[seq]=1;return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkGetImageMemoryRequirements(VkDevice d,VkImage im,VkMemoryRequirements*r){assert(d&&created_images[(uintptr_t)im]);*r=(VkMemoryRequirements){.size=4096,.alignment=16,.memoryTypeBits=1};}
VKAPI_ATTR VkResult VKAPI_CALL vkBindImageMemory(VkDevice d,VkImage im,VkDeviceMemory m,VkDeviceSize o){assert(d&&created_images[(uintptr_t)im]&&m&&!o);return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyImage(VkDevice d,VkImage im,const VkAllocationCallbacks*a){(void)a;assert(d&&created_images[(uintptr_t)im]);created_images[(uintptr_t)im]=0;++image_destroy;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateImageView(VkDevice d,const VkImageViewCreateInfo*i,const VkAllocationCallbacks*a,VkImageView*out){(void)a;assert(d&&i->image&&i->subresourceRange.levelCount);++view_calls;
 if(fault_view_at==view_calls){if(view_fault==2)*out=H(VkImageView,3901);else *out=VK_NULL_HANDLE;return view_fault==3?VK_SUCCESS:VK_ERROR_OUT_OF_HOST_MEMORY;}
 *out=H(VkImageView,++seq);created_views[seq]=1;return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyImageView(VkDevice d,VkImageView v,const VkAllocationCallbacks*a){(void)a;assert(d&&v);uintptr_t k=(uintptr_t)v;assert(k<4096);if(!created_views[k]){++bad_destroy;return;}created_views[k]=0;++good_destroy;}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateSampler(VkDevice d,const VkSamplerCreateInfo*i,const VkAllocationCallbacks*a,VkSampler*out){(void)a;assert(d&&i->maxLod>=0);++sampler_calls;
 if(sampler_fault){*out=sampler_fault==2?H(VkSampler,3902):VK_NULL_HANDLE;return sampler_fault==3?VK_SUCCESS:VK_ERROR_OUT_OF_HOST_MEMORY;}
 *out=H(VkSampler,++seq);created_samplers[seq]=1;return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkUpdateDescriptorSets(VkDevice d,uint32_t n,const VkWriteDescriptorSet*w,uint32_t c,const VkCopyDescriptorSet*p){(void)p;assert(d&&n&&!c);++updates;for(unsigned j=0;j<n;++j)if(w[j].descriptorType==VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER){assert(w[j].pImageInfo->imageView);uintptr_t s=(uintptr_t)w[j].pImageInfo->sampler;if(s>=4096||!created_samplers[s])++bad_updates;}}
'''
cache_mocks=r'''
VKAPI_ATTR VkResult VKAPI_CALL vkCreatePipelineCache(VkDevice d,const VkPipelineCacheCreateInfo*i,const VkAllocationCallbacks*a,VkPipelineCache*out){(void)a;assert(d&&i);++cache_calls;
 if(i->initialDataSize){assert(i->initialDataSize==sizeof(VkPipelineCacheHeaderVersionOne)&&i->pInitialData);const VkPipelineCacheHeaderVersionOne*h=i->pInitialData;assert(h->headerSize==sizeof(*h)&&h->headerVersion==VK_PIPELINE_CACHE_HEADER_VERSION_ONE&&h->vendorID==0x1234&&h->deviceID==0x5678);}
 if(cache_fault){*out=cache_fault==1?H(VkPipelineCache,30):VK_NULL_HANDLE;return cache_fault==2?VK_SUCCESS:VK_ERROR_OUT_OF_HOST_MEMORY;}
 unsigned k=(!cache_created||cache_alias)?7:8;++cache_refs[k];++cache_created;*out=H(VkPipelineCache,k);return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkGetPipelineCacheData(VkDevice d,VkPipelineCache pc,size_t*n,void*data){assert(d&&pc&&n&&cache_refs[(uintptr_t)pc]);if(!data){*n=sizeof(VkPipelineCacheHeaderVersionOne);return VK_SUCCESS;}assert(*n>=sizeof(VkPipelineCacheHeaderVersionOne));VkPipelineCacheHeaderVersionOne h={.headerSize=sizeof(h),.headerVersion=VK_PIPELINE_CACHE_HEADER_VERSION_ONE,.vendorID=0x1234,.deviceID=0x5678};memcpy(data,&h,sizeof h);*n=sizeof h;return VK_SUCCESS;}
VKAPI_ATTR VkResult VKAPI_CALL vkMergePipelineCaches(VkDevice d,VkPipelineCache dst,uint32_t count,const VkPipelineCache*src){assert(d&&count==1&&src);++cache_merges;uintptr_t k=(uintptr_t)dst,j=(uintptr_t)*src;if(!k||!j||k==j||k>=32||j>=32||!cache_refs[k]||!cache_refs[j])++cache_bad_merge;return VK_SUCCESS;}
VKAPI_ATTR void VKAPI_CALL vkDestroyPipelineCache(VkDevice d,VkPipelineCache pc,const VkAllocationCallbacks*a){(void)a;assert(d);if(!pc)return;uintptr_t k=(uintptr_t)pc;if(k>=32||!cache_refs[k]){++bad_destroy;return;}--cache_refs[k];++cache_destroys;}
'''
support=r'''
typedef struct{vimg*im;}vtex;
typedef struct{int n_samp;int samp_cube[MAX_SAMP];}vprog;
static vimg dummy_image={.view=H(VkImageView,80)};static vimg*dummy2d=&dummy_image,*dummycube=&dummy_image;static VkSampler dummy_sampler;
static VkSampler sampler_for(const vtex*t,int levels){(void)t;(void)levels;return dummy_sampler;}
'''
post=r'''
static cinder_vk_sampler sampler(void){return(cinder_vk_sampler){.use_state=1,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_LINEAR,.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_LINEAR,.address_u=VK_SAMPLER_ADDRESS_MODE_REPEAT,.address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.anisotropy=1};}
static vimg* factory(void){return image_new_usage(VK_FORMAT_R8G8B8A8_UNORM,8,8,3,1,1,1,0,SWZ_ID,0);}
static void release(vimg*im){if(im)image_free_now(im);}
int main(int argc,char**argv){assert(argc==3);int c=atoi(argv[1]);platform_native_profile=atoi(argv[2]);created_samplers[42]=1;dummy_sampler=H(VkSampler,42);
 int first=-1,second=-1;size_t before=0;vimg*im=NULL;cinder_vk_sampler state=sampler();vprog p={.n_samp=1};cinder_vk_draw d={0};d.samplers[0]=state;vtex*textures[MAX_SAMP]={0};
 if(c<=5){if(c){fault_view_at=(c==3||c==5)?2:1;view_fault=(c==1)?1:((c==4||c==5)?3:2);}im=factory();first=!!im;release(im);}
 else if(c==6||c==7||c==8){im=factory();assert(im);fault_view_at=view_calls+1;view_fault=c==8?0:2;if(c==8)fault_view_at=0;first=c==7?expanded_mip(im,3):expanded_image(im,3);if(first)release(im);}
 else if(c==9){im=factory();assert(im);VkImageView v=VK_NULL_HANDLE;fault_view_at=view_calls+1;view_fault=2;VkResult r=view_try(im,1,3,&v);first=r==VK_ERROR_OUT_OF_HOST_MEMORY;second=!!v;release(im);}
 else if(c>=15){VkPipelineCacheCreateInfo init={.sType=VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO};if(c!=17)assert(vkCreatePipelineCache(D.dev,&init,NULL,&D.pcache)==VK_SUCCESS);cache_alias=c==16;cache_fault=c==18?1:c==19?2:0;
  char path[128];snprintf(path,sizeof(path),"cache-%d-%d.bin",c,platform_native_profile);if(c!=23){FILE*f=fopen(path,"wb");assert(f);VkPipelineCache origin=D.pcache;int temporary=!origin;if(temporary)assert(vkCreatePipelineCache(D.dev,&init,NULL,&origin)==VK_SUCCESS);size_t bytes=0;assert(vkGetPipelineCacheData(D.dev,origin,&bytes,NULL)==VK_SUCCESS);void*data=malloc(bytes);assert(data&&vkGetPipelineCacheData(D.dev,origin,&bytes,data)==VK_SUCCESS);assert(fwrite(data,1,bytes,f)==bytes);free(data);assert(!fclose(f));if(temporary)vkDestroyPipelineCache(D.dev,origin,NULL);}
  if(c==20)platform_created=0;if(c==21)native_upload_stream=CINDER_VK_UPLOAD_LOADER;VkPipelineCache prior=D.pcache;cinder_vk_platform_pipeline_cache_file(c==22?"":path);first=!!D.pcache;second=D.pcache==prior;
 }
 else{if(c==10){VkSampler x=cinder_vk_sampler_get(&state,3);first=!!x;second=cinder_vk_sampler_get(&state,9)==x;}
  else{if(c==14){GROW(samps,n_samps,cap_samps);state.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST;samps[n_samps++]=(samp_t){state,1,VK_NULL_HANDLE};}
   sampler_fault=c==11?1:c==12?2:c==13?3:0;before=n_samps;first=actual_binding(&d,&p,textures);sampler_fault=0;second=actual_binding(&d,&p,textures);}}
 int views_live=0,images_live=0,cache_live=0;for(unsigned k=0;k<4096;++k){views_live+=created_views[k]!=0;images_live+=created_images[k]!=0;}for(unsigned k=0;k<32;++k)cache_live+=cache_refs[k];
 printf("{\"case\":%d,\"first\":%d,\"second\":%d,\"view_calls\":%d,\"sampler_calls\":%d,\"bad_destroy\":%d,\"good_destroy\":%d,\"image_destroy\":%d,\"mem_frees\":%d,\"rejects\":%d,\"updates\":%d,\"bad_updates\":%d,\"cache\":%zu,\"cache_before\":%zu,\"views_live\":%d,\"images_live\":%d,\"cache_calls\":%d,\"cache_creations\":%d,\"cache_destroys\":%d,\"cache_merges\":%d,\"cache_bad_merge\":%d,\"cache_live\":%d}\n",c,first,second,view_calls,sampler_calls,bad_destroy,good_destroy,image_destroy,mem_frees,rejects,updates,bad_updates,n_samps,before,views_live,images_live,cache_calls,cache_created,cache_destroys,cache_merges,cache_bad_merge,cache_live);free(samps);return 0;}
'''
records=[]
for label,source in [('baseline',BASELINE),('current',CURRENT)]:
 schema=typedef(source,'vmem')+typedef(source,'vimg')+typedef(source,'dkey')+typedef(source,'dent')+'static dent dcache[DCACHE];\n'
 helpers=''.join(fun(source,a) for a in ['static int is_depth(', 'static int has_stencil(', 'static VkResult view_try(', 'static vimg *image_new_usage(', 'static void image_free_now(', 'static VkSampler cinder_vk_sampler_get(', 'static VkDescriptorSet desc_get(', 'static void backend_pipeline_cache_file('])+fun(PLATFORM,'void cinder_vk_platform_pipeline_cache_file(')
 # Keep the static official identity swizzle, otherwise no fake enum values.
 swz=source[source.index('static const VkComponentMapping SWZ_ID'):source.index('\n\n',source.index('static const VkComponentMapping SWZ_ID'))]
 text=prefix+schema+sampler_type+swz+'\n'+mocks+cache_mocks+'\n#pragma GCC poison ctx cur_up main_ctx loader_ctx cur_vao GLenum GLuint GLfloat GLboolean glGetString glBindFramebuffer vkgl_create vkgl_present\n'+helpers+support
 text+='static int expanded_image(vimg *im,int levels){struct{int levels;}ds={levels};const typeof(ds)*desc=&ds;'+image_block+'return 1;}\n'
 text+='static int expanded_mip(vimg *im,int levels){struct{int levels;}bs={levels};const typeof(bs)*base=&bs;'+mip_block+'return 1;}\n'
 text+='static int actual_binding(const cinder_vk_draw*d,vprog*p,vtex**textures){dkey dk={.n=p->n_samp,.ubo=H(VkBuffer,50),.range=16};'+bind_block+'return !!desc_get(&dk);}\n'+post
 cfile=OUT/(label+'.c');cfile.write_text(text);exe=OUT/label
 cmd=[os.environ.get('CC','clang'),'-std=gnu11','-Wall','-Wextra','-Werror','-Wno-missing-field-initializers','-Wno-unused-function','-I',str(ROOT/'src'),'-fsanitize=undefined','-fno-sanitize-recover=all','-pthread',str(cfile),'-o',str(exe)]
 if sys.platform=='darwin':cmd[1:1]=['-I','/opt/homebrew/include']
 with (OUT/(label+'-compile.log')).open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
 for profile in [0,1]:
  for case in range(24):
   p=subprocess.run([str(exe),str(case),str(profile)],cwd=OUT,capture_output=True,text=True,timeout=20);assert p.returncode==0,(label,profile,case,p.returncode,p.stdout,p.stderr)
   records.append({'source':label,'profile':profile,'case':case,'observation':json.loads(p.stdout)})
rows={(x['source'],x['profile'],x['case']):x['observation'] for x in records}
for case in range(24):assert rows['baseline',0,case]==rows['current',0,case],('legacy changed',case)
if not os.environ.get('CINDER_TRY_RECORD_OLD'):
 for case in range(24):
  q=rows['current',1,case];assert q['bad_destroy']==q['bad_updates']==q['views_live']==q['images_live']==q['cache_bad_merge']==0,case
 for case in [2,3,6,7]:assert rows['baseline',1,case]['bad_destroy']>0,('missing old ownership RED',case)
 assert rows['baseline',1,12]['bad_updates']>0
 assert rows['baseline',1,13]['second']==0 and rows['baseline',1,13]['sampler_calls']==1
 assert rows['current',1,13]['second']==1 and rows['current',1,13]['sampler_calls']==2
 assert rows['current',1,14]['first']==1 and rows['current',1,14]['sampler_calls']==1
 for case in [11,12,13]:assert rows['current',1,case]['first']==0 and rows['current',1,case]['second']==1 and rows['current',1,case]['cache']==1
 if not os.environ.get('CINDER_TRY_RECORD_OLD'):
  assert rows['baseline',1,16]['cache_bad_merge']==1
  q=rows['current',1,16];assert q['cache_creations']==2 and q['cache_destroys']==1 and q['cache_live']==1 and q['cache_merges']==0
  assert rows['current',1,15]['cache_merges']==1 and rows['current',1,17]['cache_merges']==0
  q=rows['current',1,19];assert q['first']==q['second']==q['cache_live']==1 and q['cache_destroys']==0
result={'status':'old-counterexamples-recorded' if os.environ.get('CINDER_TRY_RECORD_OLD') else 'pass','core_sha256':H(CURRENT),'baseline_sha256':H(BASELINE),'test_sha256':H(Path(__file__).read_text()),'protected_caller_bodies_equal_baseline':True,'actual_native_binding_block_sha256':H(bind_block),'actual_image_expanded_view_block_sha256':H(image_block),'actual_mipmap_expanded_view_block_sha256':H(mip_block),'records':records,'authority':'strict UBSan/API ownership mocks; actual helpers/full factory/descriptors, exact Native binding/view blocks; not full Native draw/texture entrypoint or GPU'}
result.update(actual_native_cache_file_wrapper_sha256=H(fun(PLATFORM,'void cinder_vk_platform_pipeline_cache_file(')),baseline_cache_file_body_sha256=H(fun(BASELINE,'static void backend_pipeline_cache_file(')),current_cache_file_body_sha256=H(fun(CURRENT,'static void backend_pipeline_cache_file(')))
(OUT/'results.json').write_text(json.dumps(result,indent=2)+'\n');print('Actual view/constructor/sampler/binding/descriptor/cache-file boundaries:',result['status'],len(records),'observations; 24 exact Legacy controls')
