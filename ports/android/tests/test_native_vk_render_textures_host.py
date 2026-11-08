#!/usr/bin/env python3
"""Production native sampled scene producers vs unchanged GLES byte/sampler goldens.
Vulkan creation and GL storage are recorders, not GPU rendering/driver proof.
"""
from pathlib import Path
import os,re,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[1];O=Path(os.environ.get('TMPDIR','/Volumes/CodexWork')).resolve()
assert O==Path('/Volumes/CodexWork') or str(O).startswith('/Volumes/CodexWork/')
S=(R/'src/render.c').read_text()
def fun(text,anchor):
 a=text.index(anchor);b=text.index('{',a);mask=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),text,flags=re.S);n=0
 for i in range(b,len(text)):
  n+=(mask[i]=='{')-(mask[i]=='}')
  if not n:return text[a:i+1]
 raise ValueError(anchor)
a=S.index('typedef struct {\n  char name[48];');b=S.index('} wpk_tex;',a)+len('} wpk_tex;');tex=S[a:b]
pre=r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include "native_vk.h"
typedef unsigned GLenum,GLuint;typedef int GLint,GLsizei;
#define O_RDONLY 0
static int fixture_open(const char*path,int flags){assert(path&&!flags);return 1;}
static int fixture_close(int fd){assert(fd==1);return 0;}
#define open fixture_open
#define close fixture_close
#define GL_TEXTURE_2D 0x0de1
#define GL_TEXTURE_CUBE_MAP 0x8513
#define GL_TEXTURE_CUBE_MAP_POSITIVE_X 0x8515
#define GL_UNSIGNED_BYTE 0x1401
#define GL_UNSIGNED_SHORT_5_6_5 0x8363
#define GL_UNSIGNED_SHORT_4_4_4_4 0x8033
#define GL_UNSIGNED_SHORT_5_5_5_1 0x8034
#define GL_RGB 0x1907
#define GL_RGBA 0x1908
#define GL_LUMINANCE 0x1909
#define GL_UNPACK_ALIGNMENT 0x0cf5
#define GL_NEAREST 0x2600
#define GL_LINEAR 0x2601
#define GL_LINEAR_MIPMAP_NEAREST 0x2701
#define GL_LINEAR_MIPMAP_LINEAR 0x2703
#define GL_REPEAT 0x2901
#define GL_CLAMP_TO_EDGE 0x812f
#define GL_TEXTURE_MIN_FILTER 0x2801
#define GL_TEXTURE_MAG_FILTER 0x2800
#define GL_TEXTURE_WRAP_S 0x2802
#define GL_TEXTURE_WRAP_T 0x2803
#define GL_TEXTURE_MAX_ANISOTROPY_EXT 0x84fe
#define TEX_HALF_MIN 64
#define WPK_ASTC 3
static int tex_half;static float aniso=1;
typedef struct{uint32_t level,layer;int w,h;size_t bytes;uint64_t hash;} slice_record;
typedef struct{int width,height,levels,layers,format;unsigned count;cinder_vk_sampler sampler;slice_record slices[186];} image_record;
static image_record images[16];static unsigned image_count,current,factory_calls;static int factory_fail,read_fail,scratch_fail,malloc_fail,read_calls;
static unsigned char file_bytes[300000];static size_t file_size;
static uint64_t hash_bytes(const void*p,size_t n){const uint8_t*b=p;uint64_t h=1469598103934665603ull;for(size_t i=0;i<n;++i)h=(h^b[i])*1099511628211ull;return h;}
static void*fixture_malloc(size_t n){return malloc_fail?NULL:malloc(n);}
static void*fixture_realloc(void*p,size_t n){return scratch_fail?NULL:realloc(p,n);}
static image_record*new_image(void){assert(image_count<15);image_record*r=&images[++image_count];memset(r,0,sizeof *r);r->layers=1;r->sampler=(cinder_vk_sampler){.use_state=1,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_LINEAR,.address_u=VK_SAMPLER_ADDRESS_MODE_REPEAT,.address_v=VK_SAMPLER_ADDRESS_MODE_REPEAT,.anisotropy=1};return r;}
static void capture(image_record*r,uint32_t level,uint32_t layer,int w,int h,const void*p,size_t n){assert(p&&r->count<186&&level<31&&layer<6);r->slices[r->count++]=(slice_record){level,layer,w,h,n,hash_bytes(p,n)};if(!level&&!layer)r->width=w,r->height=h;if((int)level>=r->levels)r->levels=(int)level+1;}
uint32_t cinder_vk_texture_create(const cinder_vk_texture_desc*d){++factory_calls;if(factory_fail)return 0;image_record*r=new_image();r->format=d->format;r->width=d->width;r->height=d->height;r->levels=d->levels;r->layers=d->layers;r->sampler=d->sampler;assert(d->subresource_count==(size_t)d->levels*d->layers);
 for(size_t i=0;i<d->subresource_count;++i){const cinder_vk_texture_subresource*s=&d->subresources[i];assert(!s->row_stride&&s->level<(uint32_t)d->levels&&s->layer<(uint32_t)d->layers);int w=d->width>>s->level,h=d->height>>s->level;if(!w)w=1;if(!h)h=1;capture(r,s->level,s->layer,w,h,s->data,s->bytes);}return image_count;}
uint32_t cinder_vk_texture_rgba8(int w,int h,const void*p,size_t bytes,const cinder_vk_sampler*s){cinder_vk_texture_subresource data={0,0,p,bytes,0};cinder_vk_texture_desc d={.width=w,.height=h,.levels=1,.layers=1,.format=CINDER_VK_TEX_RGBA8,.sampler=*s,.subresources=&data,.subresource_count=1};return cinder_vk_texture_create(&d);}
static uint32_t white_tex;
#ifndef NATIVE
static void glGenTextures(GLsizei n,GLuint*out){while(n--){new_image();*out++=image_count;}}
static void glBindTexture(GLenum target,GLuint id){assert(target==GL_TEXTURE_2D||target==GL_TEXTURE_CUBE_MAP);current=id;if(id&&target==GL_TEXTURE_CUBE_MAP)images[id].layers=6;}
static void glPixelStorei(GLenum name,GLint value){assert(name==GL_UNPACK_ALIGNMENT&&(value==1||value==2));}
static void glTexImage2D(GLenum target,GLint level,GLint internal,GLsizei w,GLsizei h,GLint border,GLenum format,GLenum type,const void*p){(void)internal;assert(current&&!border&&w>0&&h>0);image_record*r=&images[current];size_t bpp=2;
 if(format==GL_RGBA&&type==GL_UNSIGNED_BYTE){r->format=CINDER_VK_TEX_RGBA8;bpp=4;}else if(format==GL_RGB&&type==GL_UNSIGNED_SHORT_5_6_5)r->format=CINDER_VK_TEX_RGB565;else if(format==GL_RGBA&&type==GL_UNSIGNED_SHORT_4_4_4_4)r->format=CINDER_VK_TEX_RGBA4444;else if(format==GL_RGBA&&type==GL_UNSIGNED_SHORT_5_5_5_1)r->format=CINDER_VK_TEX_RGBA5551;else {assert(format==GL_LUMINANCE&&type==GL_UNSIGNED_BYTE);r->format=CINDER_VK_TEX_L8;bpp=1;}
 unsigned layer=target==GL_TEXTURE_2D?0:target-GL_TEXTURE_CUBE_MAP_POSITIVE_X;capture(r,(uint32_t)level,layer,w,h,p,(size_t)w*h*bpp);}
static void glCompressedTexImage2D(GLenum target,GLint level,GLenum format,GLsizei w,GLsizei h,GLint border,GLsizei bytes,const void*p){assert(current&&target==GL_TEXTURE_2D&&!border&&bytes>0);image_record*r=&images[current];r->format=format==0x93b0?CINDER_VK_TEX_ASTC_4x4:format==0x93b4?CINDER_VK_TEX_ASTC_6x6:CINDER_VK_TEX_ASTC_8x8;capture(r,(uint32_t)level,0,w,h,p,(size_t)bytes);}
static void glTexParameteri(GLenum target,GLenum name,GLint value){assert(current&&(target==GL_TEXTURE_2D||target==GL_TEXTURE_CUBE_MAP));cinder_vk_sampler*s=&images[current].sampler;
 if(name==GL_TEXTURE_MIN_FILTER){s->min_filter=value==GL_NEAREST?VK_FILTER_NEAREST:VK_FILTER_LINEAR;s->mipmaps=value==GL_LINEAR_MIPMAP_NEAREST||value==GL_LINEAR_MIPMAP_LINEAR;s->mipmap_mode=value==GL_LINEAR_MIPMAP_LINEAR?VK_SAMPLER_MIPMAP_MODE_LINEAR:VK_SAMPLER_MIPMAP_MODE_NEAREST;}
 else if(name==GL_TEXTURE_MAG_FILTER)s->mag_filter=value==GL_NEAREST?VK_FILTER_NEAREST:VK_FILTER_LINEAR;
 else if(name==GL_TEXTURE_WRAP_S)s->address_u=value==GL_REPEAT?VK_SAMPLER_ADDRESS_MODE_REPEAT:VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
 else{assert(name==GL_TEXTURE_WRAP_T);s->address_v=value==GL_REPEAT?VK_SAMPLER_ADDRESS_MODE_REPEAT:VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;}}
static void glTexParameterf(GLenum target,GLenum name,float value){assert(current&&target==GL_TEXTURE_2D&&name==GL_TEXTURE_MAX_ANISOTROPY_EXT);images[current].sampler.anisotropy=floorf(value+.5f);}
#else
#pragma GCC poison glGenTextures glBindTexture glPixelStorei glTexImage2D glCompressedTexImage2D glTexParameteri glTexParameterf
#endif
#define malloc fixture_malloc
#define realloc fixture_realloc
'''
model=r'''
typedef struct{int fd;char*path;void*tex_tbl,*cube_tbl;uint32_t n_tex,n_cube,n_ao;uint32_t *loaded,*textures,*cubes,*ao_tex;unsigned char *tex_warm,*ao_file,*scratch;size_t ao_size,scratch_size;} wpk_scene;
static int read_at(int fd,void*out,size_t bytes,off_t offset){++read_calls;if(fd<0||read_fail==read_calls||offset<0||(uint64_t)offset>file_size||bytes>file_size-(size_t)offset)return -1;memcpy(out,file_bytes+(size_t)offset,bytes);return 0;}
'''
harness=r'''
static void reset(void){memset(images,0,sizeof images);image_count=current=factory_calls=0;factory_fail=read_fail=scratch_fail=malloc_fail=read_calls=0;for(size_t i=0;i<sizeof file_bytes;++i)file_bytes[i]=(uint8_t)(i*37u+i/7u);file_size=sizeof file_bytes;}
static void dump(const char*label,size_t done){printf("%s %zu %u",label,done,image_count);for(unsigned k=1;k<=image_count;++k){const image_record*r=&images[k];printf(" |%d,%d,%d,%d,%d,%u,%u,%u,%u,%u,%g",r->format,r->width,r->height,r->levels,r->layers,r->sampler.min_filter,r->sampler.mag_filter,r->sampler.mipmaps,r->sampler.mipmap_mode,r->sampler.address_u,r->sampler.anisotropy);printf(",%u",r->sampler.address_v);for(unsigned i=0;i<r->count;++i){const slice_record*s=&r->slices[i];printf(";%u,%u,%d,%d,%zu,%016llx",s->level,s->layer,s->w,s->h,s->bytes,(unsigned long long)s->hash);}}puts("");}
static wpk_scene scene(wpk_tex*t,uint32_t*ids,uint32_t*live,unsigned char*warm){return(wpk_scene){.fd=1,.path="fixture.wpk",.tex_tbl=t,.n_tex=1,.loaded=ids,.textures=live,.tex_warm=warm};}
static void paints(void){const int wh[][2]={{1,1},{1,8},{8,1},{4,8},{64,64}};uint8_t over[3*2*4],alpha[3*2],rgb[3]={22,148,230};for(unsigned i=0;i<sizeof over;++i)over[i]=(uint8_t)(i*31);for(unsigned i=0;i<sizeof alpha;++i)alpha[i]=(uint8_t)(i*47);
 for(unsigned k=0;k<5;++k)for(int half=0;half<2;++half)for(int solid=0;solid<2;++solid){reset();tex_half=half;aniso=3.25f;int w=wh[k][0],h=wh[k][1];wpk_tex t={.w=(uint16_t)w,.h=(uint16_t)h,.fmt=0,.off=17,.size=(uint32_t)(w*h*2)};wpk_scene scene={.path="paint.wpk",.tex_tbl=&t,.n_tex=1};uint32_t id=wpk_texture_over(&scene,0,solid?alpha:over,3,2,solid?rgb:NULL);assert(id==1);char label[40];snprintf(label,sizeof label,"paint-%u-%d-%d",k,half,solid);dump(label,0);}}
static void white(void){reset();assert(!white_probe()&&white_tex==1);dump("white",0);
#ifdef NATIVE
 reset();factory_fail=1;assert(white_probe()==-1&&!white_tex&&!image_count);
#endif
}
static void packed(void){const int wh[][2]={{1,1},{1,8},{8,1},{4,8},{7,5},{64,64},{128,64}};const float filtering[]={1,1.5f,3.25f};
 for(unsigned f=0;f<3;++f)for(unsigned a=0;a<3;++a)for(unsigned k=0;k<7;++k)for(int half=0;half<2;++half){reset();tex_half=half;aniso=filtering[a];wpk_tex t={.w=(uint16_t)wh[k][0],.h=(uint16_t)wh[k][1],.fmt=f,.off=7,.size=(uint32_t)(wh[k][0]*wh[k][1]*2+8)};uint32_t ids[1]={0},live[1]={0};unsigned char warm[1]={1};wpk_scene s=scene(&t,ids,live,warm);size_t done=tex_upload(&s,0);assert(done==t.size&&ids[0]==1&&live[0]==1&&!warm[0]);char label[64];snprintf(label,sizeof label,"packed-%u-%u-%u-%d",f,a,k,half);dump(label,done);free(s.scratch);}}
static void astc_cases(void){const int wh[][2]={{1,1},{4,8},{16,16},{7,5}};const unsigned block[]={4,6,8};
 for(unsigned k=0;k<3;++k)for(unsigned size=0;size<4;++size)for(unsigned alpha=0;alpha<2;++alpha){reset();tex_half=1;aniso=3.25f;int w=wh[size][0],h=wh[size][1],pot=is_pot(w)&&is_pot(h);size_t bytes=0;for(int lw=w,lh=h;;){bytes+=(size_t)((lw+(int)block[k]-1)/(int)block[k])*((lh+(int)block[k]-1)/(int)block[k])*16;if(!pot||(lw==1&&lh==1))break;lw=lw>1?lw/2:1;lh=lh>1?lh/2:1;}
 wpk_tex t={.w=(uint16_t)w,.h=(uint16_t)h,.fmt=WPK_ASTC+2*k+alpha,.off=3,.size=(uint32_t)bytes+8};uint32_t ids[1]={0},live[1]={0};unsigned char warm[1]={1};wpk_scene s=scene(&t,ids,live,warm);size_t done=tex_upload(&s,0);assert(done==t.size&&ids[0]&&live[0]==ids[0]&&!warm[0]);char label[64];snprintf(label,sizeof label,"astc-%u-%u-%u",k,size,alpha);dump(label,done);free(s.scratch);}}
static void cubes(void){for(unsigned f=0;f<3;++f)for(unsigned n=1;n<=8;n*=8){reset();aniso=8;uint8_t table[72]={0};size_t total=0;for(unsigned side=0;side<6;++side){uint16_t w=(uint16_t)n,fmt=(uint16_t)f;uint32_t off=side*1000+17,bytes=n*n*2+side;memcpy(table+side*12,&w,2);memcpy(table+side*12+2,&fmt,2);memcpy(table+side*12+4,&off,4);memcpy(table+side*12+8,&bytes,4);total+=bytes;}uint32_t cube[1]={0};wpk_scene s={.fd=1,.path="cube.wpk",.cube_tbl=table,.n_cube=1,.cubes=cube};size_t done=cube_upload(&s,0);assert(done==total&&cube[0]==1);char label[40];snprintf(label,sizeof label,"cube-%u-%u",f,n);dump(label,done);free(s.scratch);}}
static void aos(void){const int wh[][2]={{1,1},{1,8},{8,1},{4,8},{64,64}};for(unsigned k=0;k<5;++k){reset();aniso=8;int w=wh[k][0],h=wh[k][1];size_t size=8+52+(size_t)w*h;uint8_t*blob=malloc(size);assert(blob);memset(blob,0,size);memcpy(blob,"WAO1",4);uint32_t maps=1;memcpy(blob+4,&maps,4);memcpy(blob+8,"ao",2);uint16_t dims[2]={(uint16_t)w,(uint16_t)h};memcpy(blob+56,dims,4);for(size_t i=0;i<(size_t)w*h;++i)blob[60+i]=(uint8_t)(i*31);wpk_tex t={.name="ao"};wpk_scene s={.tex_tbl=&t,.n_tex=1,.ao_file=blob,.ao_size=size};size_t done=ao_upload(&s);assert(done==(size_t)w*h+1&&s.n_ao==1&&s.ao_tex[0]&&!s.ao_file);char label[32];snprintf(label,sizeof label,"ao-%u",k);dump(label,done);free(s.ao_tex);}}
#ifdef NATIVE
static void negative(void){
 reset();wpk_tex t={.w=4,.h=4,.fmt=0,.off=0,.size=32};uint32_t ids[1]={99},live[1]={98};unsigned char warm[1]={1};wpk_scene s=scene(&t,ids,live,warm);factory_fail=1;assert(!tex_upload(&s,0)&&ids[0]==99&&live[0]==98&&warm[0]&&factory_calls==1&&!image_count);free(s.scratch);
 for(unsigned k=0;k<3;++k){reset();ids[0]=live[0]=0;warm[0]=1;s=scene(&t,ids,live,warm);if(k==0)read_fail=1;else if(k==1)malloc_fail=1;else t.size=31;assert(!tex_upload(&s,0)&&!ids[0]&&!live[0]&&warm[0]&&!factory_calls&&!image_count);free(s.scratch);t.size=32;}
 reset();t.fmt=WPK_ASTC;t.w=t.h=8;t.size=16;s=scene(&t,ids,live,warm);assert(!tex_upload(&s,0)&&!factory_calls&&!read_calls);free(s.scratch);
 reset();uint8_t table[72]={0};uint32_t cube[1]={77};for(unsigned f=0;f<6;++f){uint16_t n=4,fmt=0;uint32_t bytes=32;memcpy(table+12*f,&n,2);memcpy(table+12*f+2,&fmt,2);memcpy(table+12*f+8,&bytes,4);}s=(wpk_scene){.fd=1,.path="badcube",.cube_tbl=table,.n_cube=1,.cubes=cube};read_fail=4;assert(!cube_upload(&s,0)&&cube[0]==77&&!factory_calls);free(s.scratch);
 uint16_t bad=8;memcpy(table+12*3,&bad,2);reset();s.scratch=NULL;s.scratch_size=0;assert(!cube_upload(&s,0)&&cube[0]==77&&!factory_calls&&!read_calls);free(s.scratch);
 reset();uint16_t pixels[16]={0};assert(!native_scene_packed_texture(pixels,sizeof pixels,4,4,7,0,1));assert(!native_scene_packed_texture(pixels,31,4,4,0,0,1));assert(!factory_calls);
 fprintf(stderr,"native resource producer negative validation/failure/nonpublication PASS\n");}
#endif
int main(void){packed();astc_cases();cubes();aos();paints();white();
#ifdef NATIVE
 negative();
#endif
 return 0;}
'''
actual=fun(S,'static int is_pot(')+'\n'+fun(S,'static void *scratch(')+'\n'+re.search(r'static const uint8_t TEX_BITS\[3\]\[4\] = .*?;',S).group()+'\n'+fun(S,'static void mip_down(')+'\n'
actual+=fun(S,'static int wpk_read_packed_texture(')+'\n'
legacy='\n'.join(fun(S,x) for x in ['static GLint mip_filter(','static void tex_aniso(','static size_t cube_upload(','static size_t ao_upload(','static size_t astc_upload(','static size_t tex_upload('])
legacy='static const struct { GLenum gl; int b; } ASTC[3] = { { 0x93B0, 4 }, { 0x93B4, 6 }, { 0x93B7, 8 } };\n'+legacy
native=(R/'src/render_native_textures.inc').read_text()+'\n#define tex_upload native_wpk_tex_upload\n#define cube_upload native_wpk_cube_upload\n#define ao_upload native_wpk_ao_upload\n'
paint_function=fun(S,'uint32_t wpk_texture_over(')+'\n'
white_start=S.index('  const cinder_vk_sampler white_sampler =')
white_else=S.index('#else',white_start)
white_end=S.index('#endif',white_else)
white_probes='static int white_probe(void){static const uint8_t px[4]={255,255,255,255};\n#ifdef NATIVE\n'+S[white_start:white_else]+'#else\n'+S[white_else+len('#else'):white_end]+'#endif\nreturn 0;\n#ifdef NATIVE\nnative_bad:return -1;\n#endif\n}\n'
with tempfile.TemporaryDirectory(prefix='native-scene-textures-',dir=O) as d:
 d=Path(d);outputs={}
 for mode,code in [('legacy',legacy),('native',native)]:
  c=d/(mode+'.c');c.write_text(pre+tex+model+actual+code+paint_function+white_probes+harness);exe=d/mode
  cmd=['clang','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-missing-field-initializers','-Wno-unused-function','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(R/'src')]
  if mode=='native':cmd+=['-DNATIVE=1','-DWMMT_NATIVE_VK=1']
  if sys.platform=='darwin':cmd+=['-I','/opt/homebrew/include']
  subprocess.run(cmd+[str(c),'-lm','-o',str(exe)],check=True,timeout=120)
  p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
  if p.returncode:print(mode,p.stderr,file=sys.stderr)
  p.check_returncode();outputs[mode]=p.stdout
 assert outputs['legacy']==outputs['native'],'native scene texture byte/sampler goldens changed'
 print('PASS',len(outputs['native'].splitlines()),'exact production native/GLES packed mip/half/aniso, ASTC/cube/AO, paint and white resource goldens')
 print('PASS native file/allocation/factory/format/cube/span failures never publish resource ownership (CPU mocks, not GPU proof)')
