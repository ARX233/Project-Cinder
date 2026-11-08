#!/usr/bin/env python3
"""Real shared Vulkan sampler cache + legacy translation, mocked vkCreateSampler.
No driver/pixel/FPS claim. Outputs confined to caller-selected external TMPDIR.
"""
from pathlib import Path
import os, subprocess, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('TMPDIR','/Volumes/CodexWork')).resolve()
assert OUT==Path('/Volumes/CodexWork') or str(OUT).startswith('/Volumes/CodexWork/')
s=(ROOT/'src/vkgl.c').read_text()
a=s.index('typedef struct {',s.index('/* ---- samplers, by the texture'))
b=s.index('/* ---- the GL calls: textures ---- */',a)
real=s[a:b]
pre=r'''
#include <assert.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "native_vk.h"
static int platform_native_profile = 1;
typedef unsigned GLenum;
#define GL_NEAREST 0x2600
#define GL_LINEAR 0x2601
#define GL_NEAREST_MIPMAP_NEAREST 0x2700
#define GL_LINEAR_MIPMAP_NEAREST 0x2701
#define GL_NEAREST_MIPMAP_LINEAR 0x2702
#define GL_LINEAR_MIPMAP_LINEAR 0x2703
#define GL_REPEAT 0x2901
#define GL_CLAMP_TO_EDGE 0x812f
#define GL_MIRRORED_REPEAT 0x8370
typedef struct {GLenum min,mag,wrap_s,wrap_t;float aniso;void*im;cinder_vk_sampler native_sampler;} vtex;
static vtex textures[2];static vtex*tex_get(uint32_t id){return id==1?&textures[1]:NULL;}
static struct {int aniso;float max_aniso;VkDevice dev;pthread_mutex_t lock;} D={.aniso=1,.max_aniso=16,.lock=PTHREAD_MUTEX_INITIALIZER};
#define GROW(p,n,c) do {if((n)>=(c)){size_t z=(c)?(c)*2:16;void*q=realloc((p),z*sizeof *(p));assert(q);(p)=q;(c)=z;}}while(0)
static unsigned calls,fail,logs;static VkSamplerCreateInfo last;
#define logf_(...) (++logs)
static VkResult fake_vkCreateSampler(VkDevice dev,const VkSamplerCreateInfo*in,const VkAllocationCallbacks*a,VkSampler*out){
  (void)dev;(void)a;last=*in;++calls;if(fail)return VK_ERROR_OUT_OF_HOST_MEMORY;
  *out=(VkSampler)(uintptr_t)(calls+100);return VK_SUCCESS;
}
#define vkCreateSampler fake_vkCreateSampler
'''
post=r'''
int main(void){
  vtex t={0};VkSampler s=sampler_for(&t,4);assert(s&&calls==1&&n_samps==1);
  assert(last.minFilter==VK_FILTER_NEAREST&&last.magFilter==VK_FILTER_LINEAR&&last.mipmapMode==VK_SAMPLER_MIPMAP_MODE_LINEAR);
  assert(last.addressModeU==VK_SAMPLER_ADDRESS_MODE_REPEAT&&last.addressModeV==VK_SAMPLER_ADDRESS_MODE_REPEAT&&last.maxLod==4&&!last.anisotropyEnable);
  assert(sampler_for(&t,4)==s&&calls==1);
  const GLenum mins[]={GL_NEAREST,GL_LINEAR,GL_NEAREST_MIPMAP_NEAREST,GL_LINEAR_MIPMAP_NEAREST,GL_NEAREST_MIPMAP_LINEAR,GL_LINEAR_MIPMAP_LINEAR};
  const VkFilter filters[]={VK_FILTER_NEAREST,VK_FILTER_LINEAR,VK_FILTER_NEAREST,VK_FILTER_LINEAR,VK_FILTER_NEAREST,VK_FILTER_LINEAR};
  for(int i=0;i<6;++i){
    t=(vtex){.min=mins[i],.mag=GL_NEAREST,.wrap_s=GL_CLAMP_TO_EDGE,.wrap_t=GL_MIRRORED_REPEAT,.aniso=32};
    assert(sampler_for(&t,5));assert(last.minFilter==filters[i]&&last.magFilter==VK_FILTER_NEAREST);
    assert(last.addressModeU==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&last.addressModeV==VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT);
    assert(last.maxLod==(i<2?.25f:5));assert(last.anisotropyEnable==(i>=2));assert(last.maxAnisotropy==(i<2?1:16));
    assert(last.mipmapMode==(i>=4?VK_SAMPLER_MIPMAP_MODE_LINEAR:VK_SAMPLER_MIPMAP_MODE_NEAREST));
  }
  cinder_vk_sampler native={.use_state=1,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_LINEAR,.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,
    .address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.address_v=VK_SAMPLER_ADDRESS_MODE_REPEAT,.anisotropy=1};
  unsigned n=calls;s=cinder_vk_sampler_get(&native,9);assert(s&&calls==n+1&&last.maxLod==.25f);
  assert(cinder_vk_sampler_get(&native,3)==s&&calls==n+1); /* no-mip LOD canonicalized */
  native.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_LINEAR;
  assert(cinder_vk_sampler_get(&native,9)==s&&calls==n+1); /* noMip cannot mix L0/L1 */
  assert(last.mipmapMode==VK_SAMPLER_MIPMAP_MODE_NEAREST&&native.mipmap_mode==VK_SAMPLER_MIPMAP_MODE_LINEAR);
  native.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST;
  t=(vtex){.min=GL_LINEAR,.mag=GL_LINEAR,.wrap_s=GL_CLAMP_TO_EDGE,.wrap_t=GL_REPEAT};
  assert(sampler_for(&t,12)==s&&calls==n+1); /* shared cache, not GL mutation */
  assert(native.anisotropy==1&&native.mipmaps==0);
  cinder_vk_sampler uploaded;assert(!cinder_vk_texture_sampler(99,&uploaded));assert(!cinder_vk_texture_sampler(1,&uploaded));
  textures[1]=t;textures[1].im=(void*)1;assert(cinder_vk_texture_sampler(1,&uploaded));
  assert(uploaded.use_state&&uploaded.min_filter==VK_FILTER_LINEAR&&uploaded.address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&uploaded.address_v==VK_SAMPLER_ADDRESS_MODE_REPEAT&&!uploaded.mipmaps);
  uploaded.address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;assert(textures[1].wrap_t==GL_REPEAT);assert(!cinder_vk_texture_sampler(1,NULL));
  textures[1].native_sampler=native;textures[1].native_sampler.address_u=VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT;
  textures[1].native_sampler.address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;textures[1].min=GL_NEAREST;textures[1].wrap_s=GL_REPEAT;
  assert(cinder_vk_texture_sampler(1,&uploaded)&&uploaded.min_filter==VK_FILTER_LINEAR&&uploaded.address_u==VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT);
  assert(sampler_for(&textures[1],1));assert(last.addressModeU==VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT&&last.addressModeV==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&last.minFilter==VK_FILTER_LINEAR);
  uploaded.address_u=VK_SAMPLER_ADDRESS_MODE_REPEAT;assert(textures[1].native_sampler.address_u==VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT&&textures[1].wrap_s==GL_REPEAT);
  native.mipmaps=1;native.anisotropy=20;D.aniso=0;
  assert(cinder_vk_sampler_get(&native,7));assert(!last.anisotropyEnable&&last.maxAnisotropy==1&&last.maxLod==7);
  D.aniso=1;D.max_aniso=8;assert(cinder_vk_sampler_get(&native,7));assert(last.maxAnisotropy==8);
  native.address_v=VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT;fail=1;n=(unsigned)n_samps;
  assert(!cinder_vk_sampler_get(&native,3)&&n_samps==n&&logs==1);fail=0;
  assert(cinder_vk_sampler_get(&native,3)&&n_samps==n+1); /* failure not cached */
  free(samps);puts("shared Vulkan sampler cache + six legacy filters + explicit state + failure: PASS (CPU mocks)");
}
'''
with tempfile.TemporaryDirectory(prefix='native-vk-sampler-',dir=OUT) as d:
    d=Path(d); c=d/'test.c';c.write_text(pre+real+post);exe=d/'test'
    cmd=['clang','-std=c11','-Wall','-Wextra','-Werror','-Wno-missing-field-initializers','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(ROOT/'src')]
    if sys.platform=='darwin':cmd+=['-I','/opt/homebrew/include']
    cmd += [str(c),'-lm','-pthread','-o',str(exe)]
    subprocess.run(cmd,check=True,timeout=120);subprocess.run([str(exe)],check=True,timeout=30)
