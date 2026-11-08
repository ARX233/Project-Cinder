#!/usr/bin/env python3
"""Production renderer resource graph + begin/backmirror/overhead/selftest controls.
Direct API metadata/strong-ownership recorders, per-constructor fault injection and
UBSan; actual backend Vulkan constructors are separately covered by
 test_native_vk_targets_host.py. No GPU pixels, physical timing or driver proof.
"""
from pathlib import Path
import os, re, subprocess, sys, tempfile
R=Path(__file__).resolve().parents[1]
O=Path(os.environ.get('TMPDIR',R.parent/'tmp')).resolve()
S=(R/'src/render.c').read_text()
T=(R/'src/render_native_targets.inc').read_text()
P=(R/'src/render_native_post.inc').read_text()
def fun(anchor,s=S):
 a=s.index(anchor);b=s.index('{',a)
 m=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda x:' '*len(x.group()),s,flags=re.S);n=0
 for i in range(b,len(s)):
  n+=(m[i]=='{')-(m[i]=='}')
  if not n:return s[a:i+1]+'\n'
 raise AssertionError(anchor)
pre=r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#define WMMT_NATIVE_VK 1
#define WMMT_VK 1
#include "native_vk.h"
typedef uint32_t GLuint, GLenum, GLbitfield; typedef int GLint,GLsizei;
typedef struct {uint32_t target;int w,h;} native_scene_view;
static native_scene_view native_scene;
static int frame_history_valid,frame_recording_trusted,frame_env=1,frame_wet;
static float frame_k,aniso=1,over_inv_tan;
static uint64_t frame_start_epoch,frame_history_epoch;
static GLuint white_tex=9999,native_frame_texture,native_loader_program;
static int native_bloom_ready;
static uint64_t epoch;
static unsigned calls,fail_at,all_fail,format_mask,hdr_fallback,finish_fail,clear_fail,buffer_fail,upload_fail,mip_fail;
static unsigned nt,na,nf,nb,ntlive,nalive,nflive,nblive,generated,uploads,drawn,finishes,compiles;
static int record_upload,copy_no_blit;
static unsigned copy_queries;
static struct {int live; cinder_vk_storage_desc d; VkFormat fmt; unsigned refs;} textures[4096],attachments[4096];
static struct {int live;cinder_vk_target_create_desc d;cinder_vk_target_desc info;} targets[4096];
static int buffers[4096];
static int step(void){++calls;if(all_fail || calls==fail_at){++epoch;return 0;}return 1;}
uint64_t cinder_vk_error_epoch(void){return epoch;}
int cinder_vk_error_pending(void){return 0;}
int cinder_vk_finish(void){++finishes;return !finish_fail;}
int cinder_vk_flush(void){return !finish_fail;}
int cinder_vk_sample_limit(void){return 8;}
static VkFormat format(cinder_vk_storage_format f){static const VkFormat a[]={VK_FORMAT_R8G8B8A8_UNORM,VK_FORMAT_R5G6B5_UNORM_PACK16,VK_FORMAT_R16G16B16A16_SFLOAT,VK_FORMAT_B10G11R11_UFLOAT_PACK32,VK_FORMAT_D16_UNORM,VK_FORMAT_D24_UNORM_S8_UINT};return f==CINDER_VK_STORAGE_R11G11B10F && hdr_fallback?VK_FORMAT_R16G16B16A16_SFLOAT:a[f];}
uint32_t cinder_vk_texture_storage(const cinder_vk_storage_desc*d){
 assert(d&&d->width>0&&d->height>0&&d->samples==1&&!d->transient&&d->sampler.use_state&&!d->sampler.mipmaps);
 if(!step())return 0;if(format_mask&(1u<<d->format)){++epoch;return 0;}
 unsigned i=++nt;assert(i<4096);textures[i].live=1;textures[i].d=*d;textures[i].fmt=format(d->format);++ntlive;return i;
}
uint32_t cinder_vk_attachment_create(const cinder_vk_storage_desc*d){
 assert(d&&d->width>0&&d->height>0&&(d->samples==1||d->samples==2||d->samples==4||d->samples==8));
 assert(!d->transient||(!d->transfer_src&&!d->transfer_dst));
 if(!step())return 0;if(format_mask&(1u<<d->format)){++epoch;return 0;}
 unsigned i=++na;assert(i<4096);attachments[i].live=1;attachments[i].d=*d;attachments[i].fmt=format(d->format);++nalive;return i;
}
static VkFormat image(cinder_vk_image_ref r,int*w,int*h,int*s,VkImageUsageFlags*u){
 assert(r.kind==CINDER_VK_IMAGE_TEXTURE||r.kind==CINDER_VK_IMAGE_ATTACHMENT);
 cinder_vk_storage_desc*d;VkFormat f;
 if(r.kind==CINDER_VK_IMAGE_TEXTURE){assert(r.id<4096&&textures[r.id].live);d=&textures[r.id].d;f=textures[r.id].fmt;*u=VK_IMAGE_USAGE_SAMPLED_BIT;}
 else{assert(r.id<4096&&attachments[r.id].live);d=&attachments[r.id].d;f=attachments[r.id].fmt;*u=0;}
 *w=d->width;*h=d->height;*s=d->samples;
 *u|=d->format>=CINDER_VK_STORAGE_DEPTH16?VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT:VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
 if(d->transfer_src)*u|=VK_IMAGE_USAGE_TRANSFER_SRC_BIT;if(d->transfer_dst)*u|=VK_IMAGE_USAGE_TRANSFER_DST_BIT;if(d->transient)*u|=VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT;
 return f;
}
static void ref(cinder_vk_image_ref r,int delta){if(!r.id)return;if(r.kind==CINDER_VK_IMAGE_TEXTURE)textures[r.id].refs+=delta;else attachments[r.id].refs+=delta;}
uint32_t cinder_vk_target_create(const cinder_vk_target_create_desc*d){
 assert(d&&(d->color.id||d->depth_stencil.id));if(!step())return 0;
 cinder_vk_target_desc out={0};int cw=0,ch=0,cs=0,dw=0,dh=0,ds=0;
 if(d->color.id)out.color_format=image(d->color,&cw,&ch,&cs,&out.color_usage);
 if(d->depth_stencil.id)out.depth_format=image(d->depth_stencil,&dw,&dh,&ds,&out.depth_usage);
 if(cw&&dw)assert(cw==dw&&ch==dh);
 out.width=cw?cw:dw;out.height=ch?ch:dh;out.samples=(VkSampleCountFlagBits)(cs?cs:ds);
 if(d->resolve_samples>1){assert(d->color.kind==CINDER_VK_IMAGE_TEXTURE&&cs==1&&ds==d->resolve_samples);out.resolve_usage=out.color_usage;out.color_usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT;out.resolves=1;out.samples=(VkSampleCountFlagBits)d->resolve_samples;}
 else if(cw&&dw)assert(cs==ds);
 unsigned i=++nf;assert(i<4096);targets[i].live=1;targets[i].d=*d;targets[i].info=out;ref(d->color,1);ref(d->depth_stencil,1);++nflive;return i;
}
int cinder_vk_target_ready(uint32_t f){return step()&&f&&f<4096&&targets[f].live;}
int cinder_vk_target_info(uint32_t f,cinder_vk_target_desc*out){if(!step()||!f||f>=4096||!targets[f].live)return 0;*out=targets[f].info;return 1;}
int cinder_vk_copy_ready(const cinder_vk_copy_region*c){
 ++copy_queries;assert(c&&c->source&&c->target&&targets[c->source].live&&targets[c->target].live);
 const cinder_vk_target_desc*s=&targets[c->source].info,*t=&targets[c->target].info;
 assert(c->aspects==VK_IMAGE_ASPECT_COLOR_BIT&&c->filter==VK_FILTER_NEAREST);
 assert(!c->source_rect[0]&&!c->source_rect[1]&&!c->target_rect[0]&&!c->target_rect[1]);
 assert(c->source_rect[2]==s->width&&c->source_rect[3]==s->height&&c->target_rect[2]==t->width&&c->target_rect[3]==t->height);
 /* Frontend API recorder only. Backend preflight authority is tested separately. */
 return s->samples>VK_SAMPLE_COUNT_1_BIT || !copy_no_blit;
}
void cinder_vk_target_destroy(uint32_t f){if(!f)return;assert(f<4096&&targets[f].live);ref(targets[f].d.color,-1);ref(targets[f].d.depth_stencil,-1);targets[f].live=0;--nflive;}
void cinder_vk_texture_destroy(uint32_t t){if(!t)return;assert(t<4096&&textures[t].live&&!textures[t].refs);textures[t].live=0;--ntlive;}
void cinder_vk_attachment_destroy(uint32_t t){if(!t)return;assert(t<4096&&attachments[t].live&&!attachments[t].refs);attachments[t].live=0;--nalive;}
uint32_t cinder_vk_buffer_create(size_t n,const void*p){assert(n&&p);if(buffer_fail)return 0;unsigned i=++nb;assert(i<4096);buffers[i]=1;++nblive;return i;}
void cinder_vk_buffer_destroy(uint32_t b){if(!b)return;assert(b<4096&&buffers[b]);buffers[b]=0;--nblive;}
static uint64_t hash(const void*p,size_t n){const unsigned char*b=p;uint64_t h=1469598103934665603ull;while(n--)h=(h^*b++)*1099511628211ull;return h;}
static uint32_t upload(const cinder_vk_texture_desc*d,int gen){
 assert(d&&d->format==CINDER_VK_TEX_RGB565&&d->layers==1&&d->subresources&&d->sampler.use_state&&d->sampler.anisotropy==1);
 assert(d->subresource_count==(gen?1u:(size_t)d->levels));
 if(gen){assert(d->levels>1&&d->sampler.mipmaps);++generated;if(mip_fail)return 0;}else{++uploads;if(upload_fail)return 0;}
 for(size_t i=0;i<d->subresource_count;++i){const cinder_vk_texture_subresource*q=&d->subresources[i];int w=d->width>>i;assert(q->level==i&&!q->layer&&q->bytes==(size_t)w*w*2&&!q->row_stride);if(record_upload)printf("T %d %d %zu %016llx\n",d->width,gen,i,(unsigned long long)hash(q->data,q->bytes));}
 cinder_vk_storage_desc sd={.width=d->width,.height=d->height,.samples=1,.format=CINDER_VK_STORAGE_RGB565,.sampler=d->sampler};sd.sampler.mipmaps=0;return cinder_vk_texture_storage(&sd);
}
uint32_t cinder_vk_texture_create(const cinder_vk_texture_desc*d){return upload(d,0);}
uint32_t cinder_vk_texture_generate_mips(const cinder_vk_texture_desc*d){return upload(d,1);}
int cinder_vk_clear(uint32_t f,VkImageAspectFlags a,const float*c,const int*r){assert(f&&f<4096&&targets[f].live&&a&&c&&!r);return !clear_fail;}
int cinder_vk_discard(uint32_t f,VkImageAspectFlags a){assert(f&&targets[f].live&&a);return 1;}
static GLuint native_program_create(const char*v,const char*f,const char**a,int n){assert(v&&f&&a&&n);++compiles;return 77;}
static void native_program_release(GLuint*p){*p=0;}
int cinder_vk_program_ready(uint32_t p){return p==77;}
static void render_warm_begin(void){native_loader_program=77;}
static int native_loader_triangle(uint32_t p,uint32_t t,native_scene_view v,uint32_t vb,uint32_t ib,int client){assert(p==77&&t&&v.target&&targets[v.target].live&&v.w==1&&v.h==1&&vb&&buffers[vb]&&!client);if(ib)assert(buffers[ib]);++drawn;return 1;}
#pragma GCC poison glGenTextures glDeleteTextures glTexImage2D glGenerateMipmap glBindTexture glGenFramebuffers glDeleteFramebuffers glBindFramebuffer glFramebufferTexture2D glFramebufferRenderbuffer glCheckFramebufferStatus glGenRenderbuffers glDeleteRenderbuffers glBindRenderbuffer glRenderbufferStorage glGetError glGetString glGetIntegerv glGetFloatv glFinish glFlush
'''
blur=S[S.index('static struct {\n  GLuint fbo, tex, depth;'):S.index('} blur;')+len('} blur;')]
hq=S[S.index('typedef void (*hq_blit_fn)'):S.index('static int hq_said;')]
level=S[S.index('static const struct { float scale;'):S.index('\n};',S.index('static const struct { float scale;'))+3]
over=S[S.index('#define OVER_SIZE'):S.index('} over;')+len('} over;')]
bm=S[S.index('static struct {\n  GLuint fbo, tex, depth;',S.index('/* ---- the back mirror')):S.index('} bm;')+len('} bm;')]
actual=blur+'\n#define HQ_LEVELS 4\n#define HQ_LEVELS_N 8\n'+hq+'\n'+level+'\n'+fun('static void frame_sampler(')+fun('static void frame_sampler_off(')+T+'\n'+fun('static int native_hq_copy_ready(',P)+'\nstatic int sharp_deep;\n'+fun('static int render_blur_begin_inner(')+fun('int render_blur_begin(')+fun('int render_hq_level(')+'\n'+over+fun('static int over_init(')+'\n'+bm+fun('int render_backmirror_begin(')+fun('void render_backmirror_end(')
textures=(R/'src/render_native_textures.inc').read_text()
actual+=S[S.index('static const uint8_t TEX_BITS'):S.index(';',S.index('static const uint8_t TEX_BITS'))+1]+fun('static int is_pot(')+fun('static void mip_down(')+fun('static cinder_vk_sampler native_scene_sampler(',textures)+fun('static int native_scene_levels(',textures)
actual+=fun('static double st_ms(')+fun('static double st_draw(')+fun('static GLuint st_texture(')+fun('void render_selftest(')
post=r'''
static void empty(void){assert(!ntlive&&!nalive&&!nflive&&!nblive);}
static void reset(void){
 hq_free();if(bm.fbo){cinder_vk_target_destroy(bm.fbo);cinder_vk_texture_destroy(bm.tex);cinder_vk_attachment_destroy(bm.depth);}memset(&bm,0,sizeof bm);
 if(over.fbo){cinder_vk_target_destroy(over.fbo);cinder_vk_texture_destroy(over.tex);cinder_vk_attachment_destroy(over.depth);}memset(&over,0,sizeof over);empty();
 memset(&hq,0,sizeof hq);memset(&blur,0,sizeof blur);memset(textures,0,sizeof textures);memset(attachments,0,sizeof attachments);memset(targets,0,sizeof targets);
 nt=na=nf=nb=calls=fail_at=all_fail=format_mask=hdr_fallback=finish_fail=clear_fail=buffer_fail=upload_fail=mip_fail=generated=uploads=drawn=finishes=compiles=0;
 hq.on=1;hq.samples=hq.samples0=4;hq.msrt=1;hq.scale=1;hq.opt_ao=hq.opt_paint=hq.opt_wet=1;hq.ao_prog=hq.ao_blur_prog=77;hq.ssao=1;
 copy_no_blit=0;copy_queries=0;
 native_scene=(native_scene_view){0,1280,720};native_loader_program=77;native_graph_samples=native_graph_fmt=0;epoch=frame_start_epoch=frame_history_epoch=0;frame_recording_trusted=1;frame_history_valid=0;
}
static void check_graph(int w,int h,int fmt,int samples,int msrt){
 assert(blur.w==w&&blur.h==h&&hq.fmt==fmt&&hq.msrt==msrt);
 cinder_vk_target_desc a=targets[blur.fbo].info;
 assert(a.width==w&&a.height==h&&a.color_format==format(native_hq_format(fmt)));
 assert(textures[blur.tex].d.transfer_src&&textures[blur.tex].d.transfer_dst);
 if(msrt){assert(targets[hq.rt_fbo].info.samples==(VkSampleCountFlagBits)samples&&attachments[hq.rt_depth].d.samples==samples&&!attachments[hq.rt_depth].d.transfer_src);if(samples>1)assert(a.resolves&&a.resolve_usage&VK_IMAGE_USAGE_SAMPLED_BIT);}
 else {assert(a.samples==VK_SAMPLE_COUNT_1_BIT&&!a.resolves&&native_hq_copy_ready());assert(attachments[hq.ms_color].d.transfer_src&&!attachments[hq.ms_color].d.transient);}
 for(int i=0,lw=w,lh=h;i<4;++i){lw=lw/2>1?lw/2:1;lh=lh/2>1?lh/2:1;assert(hq.w[i]==lw&&hq.h[i]==lh&&targets[hq.fbo[i]].info.width==lw&&targets[hq.fbo[i]].info.height==lh);assert(textures[hq.tex[i]].fmt==a.color_format&&!textures[hq.tex[i]].d.transfer_src);}
}
static void formats(void){
 for(int mode=0;mode<2;++mode)for(int fmt=0;fmt<3;++fmt)for(int s=1;s<=8;s*=2){reset();assert(native_blur_allocate(641,479,2,1,fmt,s,mode));check_graph(641,479,fmt,s,mode);vk_single_targets(641,479);assert(hq.single_ready&&hq.ssao_ok&&hq.single_attempted&&hq.aw==320&&hq.ah==239);for(int i=0;i<2;++i){assert(targets[hq.single_fbo[i]].info.samples==1&&!targets[hq.single_fbo[i]].info.resolves&&targets[hq.single_fbo[i]].d.depth_stencil.id==hq.z_tex);assert(textures[hq.ao_tex[i]].d.sampler.min_filter==(i?VK_FILTER_LINEAR:VK_FILTER_NEAREST));}hq_free();empty();}
 reset();hdr_fallback=1;assert(native_blur_allocate(17,9,2,1,0,4,1));check_graph(17,9,0,4,1);hq_free();empty();
 puts("PASS 3 HDR formats, actual preferred-format fallback, sample1/2/4/8 raw/MSRT, transfer and transient usage, legal single-depth scene/nearest+linear AO, exact halving");
}
static void faults(void){
 unsigned tested=0;
 for(int mode=0;mode<2;++mode){reset();assert(native_blur_allocate(64,48,2,1,0,4,mode));unsigned steps=calls;
  for(unsigned f=1;f<=steps;++f){reset();assert(native_blur_allocate(64,48,2,1,0,4,mode));GLuint old=blur.fbo,ot=blur.tex;unsigned tl=ntlive,al=nalive,fl=nflive;calls=0;fail_at=f;int ok=native_blur_allocate(80,60,2,1,0,4,mode);fail_at=0;if(!ok){assert(blur.fbo==old&&blur.tex==ot&&blur.w==64&&blur.h==48&&ntlive==tl&&nalive==al&&nflive==fl&&targets[old].live);}else assert(!targets[old].live&&blur.w==80);hq_free();empty();++tested;}
 }
 for(int mode=0;mode<2;++mode){reset();assert(native_blur_allocate(64,48,2,1,0,4,mode));calls=0;vk_single_targets(64,48);unsigned steps=calls;
  for(unsigned f=1;f<=steps;++f){reset();assert(native_blur_allocate(64,48,2,1,0,4,mode));GLuint old=blur.fbo,rt=hq.rt_fbo;unsigned tl=ntlive,al=nalive,fl=nflive;calls=0;fail_at=f;vk_single_targets(64,48);fail_at=0;assert(hq.single_attempted&&!hq.single_ready&&!hq.ssao_ok&&!hq.z_tex&&blur.fbo==old&&hq.rt_fbo==rt&&ntlive==tl&&nalive==al&&nflive==fl);hq_free();empty();++tested;}
 }
 printf("PASS %u all-step storage/target/ready/info faults: mandatory transaction preserves old, MSRT raw fallback, optional SSAO no partial publication; target-before-public-resource cleanup\n",tested);
}
static void begins(void){
 reset();hq.ssao=0;assert(render_blur_begin(.5f,1280,720));check_graph(1280,720,0,4,1);GLuint old=blur.fbo;unsigned before=calls;assert(render_blur_begin(.5f,1280,720)&&blur.fbo==old&&calls==before+1); /* readiness only */
 native_scene=(native_scene_view){0,1280,720};assert(render_hq_level(4)==4&&native_graph_dirty&&blur.w==1280);all_fail=1;assert(!render_blur_begin(.5f,1280,720)&&blur.fbo==old&&blur.w==1280&&blur.h==720&&native_graph_dirty);all_fail=0;assert(render_blur_begin(.5f,1280,720)&&!native_graph_dirty);check_graph(1074,604,0,2,1);assert(!targets[old].live);
 reset();format_mask=1u<<CINDER_VK_STORAGE_R11G11B10F;assert(render_blur_begin(.5f,640,480));check_graph(640,480,1,4,1);assert(frame_recording_trusted&&frame_start_epoch==epoch);
 reset();format_mask=(1u<<CINDER_VK_STORAGE_R11G11B10F)|(1u<<CINDER_VK_STORAGE_RGBA16F);assert(render_blur_begin(.5f,640,480));check_graph(640,480,2,4,1);
 reset();sharp_deep=0;format_mask=13;assert(render_blur_begin(.5f,640,480)&&!hq.on&&blur.deep==0&&textures[blur.tex].fmt==VK_FORMAT_R5G6B5_UNORM_PACK16&&!hq.z_tex&&!hq.single_ready&&!hq.ao_fbo[0]);
 native_scene=(native_scene_view){blur.fbo,640,480};hq_free();assert(!native_scene.target&&!blur.fbo&&!frame_history_valid&&!hq.msrt&&!hq.single_ready&&!hq.ssao_ok);empty();
 reset();format_mask=15;assert(!render_blur_begin(.5f,640,480)&&!blur.fbo&&!frame_history_valid&&native_scene.target==0);format_mask=0;assert(render_blur_begin(.5f,640,480));
 old=blur.fbo;unsigned tl=ntlive,al=nalive,fl=nflive;all_fail=1;assert(!render_blur_begin(.5f,800,600)&&blur.fbo==old&&targets[old].live&&ntlive==tl&&nalive==al&&nflive==fl&&!frame_history_valid&&native_scene.target==0);all_fail=0;assert(render_blur_begin(.5f,800,600)&&!targets[old].live);
 reset();hq.msrt=0;assert(render_blur_begin(.5f,640,480)&&hq.single_frame&&native_scene.target==hq.single_fbo[1]);
 reset();hq.on=0;sharp_deep=0;assert(render_blur_begin(.5f,640,480)&&blur.deep==0&&textures[blur.tex].fmt==VK_FORMAT_R5G6B5_UNORM_PACK16);sharp_deep=1;assert(render_blur_begin(.5f,640,480)&&blur.deep==1&&textures[blur.tex].fmt==VK_FORMAT_R8G8B8A8_UNORM);
 reset();hq.msrt=0;hq.ssao=0;assert(render_blur_begin(.5f,640,480));assert(native_hq_copy_ready());targets[hq.ms_fbo].info.color_usage&=~VK_IMAGE_USAGE_TRANSFER_SRC_BIT;assert(!native_hq_copy_ready());
 reset();hq.msrt=0;hq.ssao=0;hq.samples=hq.samples0=1;copy_no_blit=1;
 assert(render_blur_begin(.5f,640,480)&&!hq.on&&native_scene.target==blur.fbo&&!frame_history_valid&&copy_queries==1);
 reset();hq.msrt=0;hq.ssao=0;hq.samples=hq.samples0=4;copy_no_blit=1;
 assert(render_blur_begin(.5f,640,480)&&hq.on&&native_scene.target==hq.ms_fbo&&copy_queries==1);
 uint64_t old_epoch=epoch;unsigned old_calls=calls;assert(native_hq_copy_ready()&&epoch==old_epoch&&calls==old_calls+2&&copy_queries==2);
 reset();puts("PASS actual begin allocation/cache/scale/sample/format fallback and full allocation failure/retry preserve old; depth options, explicit scene selection, full copy query: sample1/noBLIT early fallback vs raw4/noBLIT resolve admitted");
}
static void extras(void){
 reset();assert(!over_init()&&over.state==1&&over.tex&&over.depth&&over.fbo&&targets[over.fbo].info.depth_format==VK_FORMAT_D16_UNORM);reset();
 for(unsigned f=1;f<=5;++f){reset();calls=0;fail_at=f;assert(over_init()==-1&&over.state==-1&&!over.prog&&!over.tex&&!over.depth&&!over.fbo);fail_at=0;empty();}
 reset();float c[3]={.2f,.3f,.4f};assert(!render_backmirror_begin(200,72,c)&&native_scene.target==bm.fbo);render_backmirror_end();assert(native_scene.target==0);GLuint old=bm.fbo;
 for(unsigned f=1;f<=5;++f){calls=0;fail_at=f;assert(render_backmirror_begin(240,80,c)==-1&&bm.fbo==old&&bm.w==200&&targets[old].live);fail_at=0;}
 assert(!render_backmirror_begin(240,80,c)&&bm.fbo!=old&&!targets[old].live);render_backmirror_end();reset();
 puts("PASS actual overhead create/fail cleanup and backmirror complete composition/resize/fail-preserve/restore");
}
static void selftest(void){
 reset();record_upload=1;
 for(int size=256;size<=512;size*=2)for(int m=0;m<3;++m){double api,cpu;GLuint t=st_texture(size,m,&api,&cpu);assert(t&&api>=0&&cpu>=0);cinder_vk_texture_destroy(t);}record_upload=0;assert(generated==2&&uploads==4);empty();
 double a,c;finish_fail=1;assert(!st_texture(256,1,&a,&c)&&a<0&&c<0&&!drawn);finish_fail=0;mip_fail=1;assert(!st_texture(256,1,&a,&c)&&a<0&&c<0);mip_fail=0;
 char out[4096];render_selftest(out,sizeof out);assert(strstr(out,"host wall ms")&&strstr(out,"pvrtc unavailable")&&strstr(out,"batch 4000"));empty();unsigned nd=drawn;buffer_fail=1;render_selftest(out,sizeof out);assert(strstr(out,"unavailable")&&drawn==nd);buffer_fail=0;finish_fail=1;render_selftest(out,sizeof out);assert(strstr(out,"unavailable")&&drawn==nd);finish_fail=0;
 upload_fail=mip_fail=1;render_selftest(out,sizeof out);assert(strstr(out,"256 genmip unavailable")&&strstr(out,"batch unavailable"));empty();upload_fail=mip_fail=0;
 for(unsigned f=1;f<=4;++f){calls=0;fail_at=f;render_selftest(out,sizeof out);assert(strstr(out,"unavailable"));fail_at=0;empty();}
 puts("PASS native selftest 1x1 attachment target, typed RGB565 base/CPU mip chain/GPU-mip API branches; absence/finish failure cannot draw client0 or claim successful timings; PVRTC unavailable");
}
int main(void){formats();faults();begins();extras();selftest();reset();return 0;}
'''
with tempfile.TemporaryDirectory(prefix='native-render-targets-',dir=O) as td:
 td=Path(td);c=td/'test.c';c.write_text(pre+actual+post)
 cmd=['clang','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(R/'src')]
 if sys.platform=='darwin':cmd+=['-I','/opt/homebrew/include']
 exe=td/'test';subprocess.run(cmd+[str(c),'-lm','-o',str(exe)],check=True,timeout=120)
 result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=60);print(result.stdout,end='');print(result.stderr,end='',file=sys.stderr);assert not result.returncode,result.returncode
 baseline=Path(os.environ.get('CINDER_RENDER_BASELINE',R.parent/'round6-baseline/src/render.c')).read_text()
 legacy_pre=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/time.h>
typedef unsigned GLuint;typedef int GLint;
enum {GL_TEXTURE_2D,GL_UNPACK_ALIGNMENT,GL_RGB,GL_UNSIGNED_SHORT_5_6_5,GL_TEXTURE_MIN_FILTER,GL_TEXTURE_MAG_FILTER,GL_LINEAR};
static int base;
static uint64_t hash(const void*p,size_t n){const unsigned char*b=p;uint64_t h=1469598103934665603ull;while(n--)h=(h^*b++)*1099511628211ull;return h;}
static void glFinish(void){}
static void glGenTextures(int n,GLuint*p){assert(n==1);*p=1;}
static void glBindTexture(unsigned a,GLuint b){(void)a;(void)b;}
static void glPixelStorei(unsigned a,int b){(void)a;(void)b;}
static void glGenerateMipmap(unsigned a){(void)a;assert(0);}
static void glTexParameteri(unsigned a,unsigned b,int c){(void)a;(void)b;(void)c;}
static int mip_filter(void){return 1;}
static void glTexImage2D(unsigned t,int level,int in,int w,int h,int b,unsigned f,unsigned ty,const void*p){(void)t;(void)in;(void)b;(void)f;(void)ty;if(!level)base=w;printf("T %d 0 %d %016llx\n",base,level,(unsigned long long)hash(p,(size_t)w*h*2));}
'''
 bits=baseline[baseline.index('static const uint8_t TEX_BITS'):baseline.index(';',baseline.index('static const uint8_t TEX_BITS'))+1]
 # Saved Round7 has two definitions: select GLES, not the first/native body.
 # The CPU mip comparison and all existing action/hash assertions stay exact.
 legacy_texture=baseline
 if '#else\nstatic GLuint st_texture(' in baseline:
  legacy_texture=baseline[baseline.index('#else\nstatic GLuint st_texture(')+len('#else\n'):]
 legacy=legacy_pre+bits+fun('static void mip_down(',baseline)+fun('static double st_ms(',baseline)+fun('static GLuint st_texture(',legacy_texture)+r'''
int main(void){for(int size=256;size<=512;size*=2)for(int m=0;m<=2;m+=2){double a,c;assert(st_texture(size,m,&a,&c));}return 0;}
'''
 c=td/'legacy.c';c.write_text(legacy);exe=td/'legacy'
 subprocess.run(cmd+[str(c),'-lm','-o',str(exe)],check=True,timeout=120)
 control=subprocess.check_output([str(exe)],text=True,timeout=30).splitlines()
 native=[x for x in result.stdout.splitlines() if x.startswith('T ') and x.split()[2]=='0']
 assert native==control,(native,control)
 print('PASS 21 exact baseline GLES RGB565 source/CPU mip byte hashes (256/512, base/no-mip/CPU-chain); GPU-mip API receives base only')
 legacy_target_pre=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t GLuint,GLenum,GLbitfield;typedef int GLint,GLsizei;
enum {GL_RGB=1,GL_RGBA,GL_UNSIGNED_BYTE,GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_TEXTURE_MAG_FILTER,GL_LINEAR,GL_TEXTURE_WRAP_S,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE,GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_RENDERBUFFER,GL_DEPTH_ATTACHMENT,GL_STENCIL_ATTACHMENT,GL_FRAMEBUFFER_COMPLETE,GL_NEAREST,GL_DEPTH24_STENCIL8_OES=0x88f0};
static unsigned nt,nr,nf,bt,br,bf,checks;static int frame_history_valid;
static struct {int w,h,f,live;} ts[64],rs[64];
static struct {unsigned c,d,s,ck,dk,sk;int samples,live;} fs[64];
static void frame_sampler_off(void){}
static void glGenTextures(int n,GLuint*p){while(n--){*p=++nt;assert(nt<64);ts[*p++].live=1;}}
static void glGenRenderbuffers(int n,GLuint*p){while(n--){*p=++nr;assert(nr<64);rs[*p++].live=1;}}
static void glGenFramebuffers(int n,GLuint*p){while(n--){*p=++nf;assert(nf<64);fs[*p++].live=1;}}
static void glDeleteTextures(int n,const GLuint*p){while(n--){assert(ts[*p].live);ts[*p++].live=0;}}
static void glDeleteRenderbuffers(int n,const GLuint*p){while(n--){assert(rs[*p].live);rs[*p++].live=0;}}
static void glDeleteFramebuffers(int n,const GLuint*p){while(n--){assert(fs[*p].live);fs[*p++].live=0;}}
static void glBindTexture(GLenum t,GLuint p){assert(t==GL_TEXTURE_2D&&p<64);bt=p;}
static void glBindRenderbuffer(GLenum t,GLuint p){assert(t==GL_RENDERBUFFER&&p<64);br=p;}
static void glBindFramebuffer(GLenum t,GLuint p){assert(t==GL_FRAMEBUFFER&&p<64);bf=p;}
static void glTexImage2D(GLenum t,int l,int in,int w,int h,int b,GLenum f,GLenum ty,const void*p){(void)f;(void)ty;assert(t==GL_TEXTURE_2D&&bt&&w>0&&h>0&&!l&&!b&&!p);ts[bt].w=w;ts[bt].h=h;ts[bt].f=in;}
static void glTexParameteri(GLenum t,GLenum n,int v){assert(t==GL_TEXTURE_2D&&bt);(void)n;(void)v;}
static void put(GLenum a,GLuint p,unsigned kind){assert(bf&&p);if(a==GL_COLOR_ATTACHMENT0){fs[bf].c=p;fs[bf].ck=kind;}else if(a==GL_DEPTH_ATTACHMENT||a==0x821a){fs[bf].d=p;fs[bf].dk=kind;if(a==0x821a){fs[bf].s=p;fs[bf].sk=kind;}}else{assert(a==GL_STENCIL_ATTACHMENT);fs[bf].s=p;fs[bf].sk=kind;}}
static void glFramebufferTexture2D(GLenum t,GLenum a,GLenum tt,GLuint p,int l){assert(t==GL_FRAMEBUFFER&&tt==GL_TEXTURE_2D&&!l);put(a,p,1);}
static void glFramebufferRenderbuffer(GLenum t,GLenum a,GLenum tt,GLuint p){assert(t==GL_FRAMEBUFFER&&tt==GL_RENDERBUFFER);put(a,p,2);}
static void storage(GLenum t,GLsizei samples,GLenum f,GLsizei w,GLsizei h){assert(t==GL_RENDERBUFFER&&br&&samples==4);rs[br].w=w;rs[br].h=h;rs[br].f=f;}
static void tex_ms(GLenum t,GLenum a,GLenum tt,GLuint p,GLint l,GLsizei s){glFramebufferTexture2D(t,a,tt,p,l);assert(s==4);fs[bf].samples=s;}
static GLenum glCheckFramebufferStatus(GLenum t){assert(t==GL_FRAMEBUFFER&&bf&&fs[bf].live&&(fs[bf].c||fs[bf].d));++checks;return GL_FRAMEBUFFER_COMPLETE;}
static uint64_t hash(const void*p,size_t n){const unsigned char*b=p;uint64_t h=1469598103934665603ull;while(n--)h=(h^*b++)*1099511628211ull;return h;}
'''
 legacy_target_body=r'''
int main(void){
#ifdef CURRENT_GLES
 int modes=3;
#else
 int modes=2;
#endif
 for(int mode=0;mode<modes;++mode)for(int fmt=0;fmt<3;++fmt){
 memset(&hq,0,sizeof hq);memset(&blur,0,sizeof blur);memset(ts,0,sizeof ts);memset(rs,0,sizeof rs);memset(fs,0,sizeof fs);nt=nr=nf=bt=br=bf=checks=0;
 hq.on=1;hq.fmt=fmt;hq.samples=4;hq.msrt=mode==1;hq.storage_ms=hq.storage_ms_ext=storage;hq.tex_ms=tex_ms;
 hq.ssao=1;hq.opt_ao=mode!=1;hq.ao_prog=1;
#ifdef CURRENT_GLES
 hq.msrt_available=mode!=0;
#endif
 blur.tex=hq_texture(640,480);glGenRenderbuffers(1,&blur.depth);glBindRenderbuffer(GL_RENDERBUFFER,blur.depth);storage(GL_RENDERBUFFER,4,GL_DEPTH24_STENCIL8_OES,640,480);blur.fbo=hq_fbo(blur.tex);
 assert(hq_targets(640,480,0));assert(mode==1?(hq.rt_tex&&hq.rt_fbo&&hq.rt_depth):(hq.ms_color&&hq.ms_depth&&hq.ms_fbo&&hq.ssao_ok));
 for(int i=0,lw=640,lh=480;i<4;++i){lw/=2;lh/=2;assert(hq.w[i]==lw&&hq.h[i]==lh&&ts[hq.tex[i]].w==lw&&ts[hq.tex[i]].h==lh&&fs[hq.fbo[i]].c==hq.tex[i]);}
 if(mode<2)
  printf("G %d %d %u %u %u %u %016llx %016llx %016llx\n",mode,fmt,nt,nr,nf,checks,(unsigned long long)hash(ts,sizeof ts),(unsigned long long)hash(rs,sizeof rs),(unsigned long long)hash(fs,sizeof fs));
 else {
  assert(!hq.msrt&&fs[hq.z_fbo].d==hq.z_tex&&ts[hq.z_tex].f==rs[hq.ms_depth].f);
  hq.opt_ao=0;
  assert(hq_targets(640,480,0)&&hq.msrt&&!hq.ssao_ok);
 }
 hq_free();glDeleteFramebuffers(1,&blur.fbo);glDeleteTextures(1,&blur.tex);glDeleteRenderbuffers(1,&blur.depth);
 }return 0;}
'''
 outputs=[]
 for label,source in [('baseline',baseline),('current',S)]:
  constants=source[source.index('#define GL_RGBA16F_'):source.index('/* a target\'s texture in hq.fmt')]
  if '#include "render_native_targets.inc"' in constants:constants=constants[:constants.rfind('#ifdef WMMT_NATIVE_VK')]
  funcs=''.join(fun(x,source) for x in ['static void hq_tex_image(', 'static GLuint hq_texture(', 'static GLuint hq_fbo(', 'static void hq_free(', 'static GLuint z_texture(', 'static void ssao_targets(', 'static int msrt_targets(', 'static int hq_targets('])
  state=source[source.index('typedef void (*hq_blit_fn)'):source.index('static int hq_said;')]
  c=td/(label+'-targets.c');exe=td/(label+'-targets');c.write_text(legacy_target_pre+blur+'\n#define HQ_LEVELS 4\n#define HQ_LEVELS_N 8\n'+state+constants+funcs+legacy_target_body)
  subprocess.run(cmd+(['-DCURRENT_GLES'] if label=='current' else [])+[str(c),'-lm','-o',str(exe)],check=True,timeout=120)
  q=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30);assert not q.returncode,q.stderr;outputs.append(q.stdout)
 assert outputs[0]==outputs[1]
 print('PASS actual GLES baseline/current HQ raw-MSAA/MSRT graph constructors across all3 formats: complete texture/attachment/target metadata hashes identical')
 print('PASS GLES with MSRT available uses matching depth targets and retains MSAA for SSAO; turning AO off restores MSRT')
print('Renderer frontend resource/target controls PASS; backend target Vulkan proof remains separately scoped.')
