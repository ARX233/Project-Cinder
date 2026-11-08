#!/usr/bin/env python3
"""Production native post + begin/end/history, UBSan, no GL draw/uniform snapshots.
Allocation/resource metadata is stubbed; draw packets and fallback control are real.
Not GPU pixels, asynchronous completion or driver validation.
"""
from pathlib import Path
import os, re, subprocess, sys, tempfile
R = Path(__file__).resolve().parents[1]
O = Path(os.environ.get('TMPDIR', R.parent / 'tmp')).resolve()
assert str(O).startswith('/Volumes/CodexWork/')
S = (R / 'src/render.c').read_text()
def fun(anchor):
    start=S.index(anchor); brace=S.index('{',start)
    mask=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),S,flags=re.S)
    depth=0
    for i in range(brace,len(S)):
        depth+=(mask[i]=='{')-(mask[i]=='}')
        if not depth:return S[start:i+1]
    raise ValueError(anchor)
pre=r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#define WMMT_NATIVE_VK 1
#define WMMT_VK 1
#include "native_vk.h"
typedef unsigned GLuint; typedef int GLint; typedef unsigned GLenum;
#define GL_NO_ERROR 0
#define HQ_LEVELS 4
#define HQ_LEVELS_N 8
typedef struct {uint32_t target; int w,h;} native_scene_view;
static native_scene_view native_scene;
static uint32_t native_frame_texture;
static float native_post_clear_color[4];
static uint32_t white_tex=7;
static struct {GLuint fbo,tex,depth; int w,h,deep; GLint screen; int out_w,out_h; float amount,sharp;} blur;
static GLuint blur_progs[6]={101,102,103,104,105,106};
static struct {
 int on,samples,fmt,msrt,single_frame,single_ready,single_attempted,ssao_ok,view_set,level,opt_ao,opt_paint,opt_wet,ao_on,aw,ah;
 float bloom,ssao,view[4],scale; GLuint rt_tex,rt_fbo,rt_depth,ms_fbo,tex[4],fbo[4],ao_tex[2],ao_fbo[2],z_tex;
 int w[4],h[4]; GLuint down_prog[2],up_prog,ao_prog,ao_blur_prog,single_fbo[2]; void *invalidate;
} hq;
static const struct {int ao,env;} HQ_LEVEL[8]={{1,1},{0,1},{0,1},{0,1},{0,1},{0,1},{0,1},{0,0}};
static int frame_env=1,sharp_deep;
static VkImageUsageFlags source_usage,target_usage;
static int freed_hq,allocated_targets;
static GLuint next_resource=200,resource_bound;
static int frame_history_valid,frame_recording_trusted,frame_wet;
static float frame_k;
static uint64_t frame_start_epoch,frame_history_epoch;
static uint64_t epoch; static int pending,error_once,bad_target,fail_submit,fail_copy,fail_clear,fail_discard;
static int count,copies,discards,clears,init_count,depth16;
static uint32_t clear_target;
static VkImageAspectFlags clear_aspects;
static cinder_vk_copy_region copied,copy_query;
static unsigned copy_queries;
static int copy_no_blit,source_samples=1;
static cinder_vk_draw packets[128];
static float positions[128][40];
static uint32_t discarded_target;
static VkImageAspectFlags discarded_aspects;
struct constants {float texel[2],view[4],strength,threshold,sharp,bloom;};
int cinder_vk_error_pending(void){return pending;}
uint64_t cinder_vk_error_epoch(void){return epoch;}
#pragma GCC poison glGetError glGetString glGetIntegerv
int cinder_vk_target_info(uint32_t id,cinder_vk_target_desc*out){
 if(id==(uint32_t)bad_target)return 0;
 if(id==hq.ao_fbo[0]||id==hq.ao_fbo[1]) *out=(cinder_vk_target_desc){.width=hq.aw,.height=hq.ah,.color_format=VK_FORMAT_R8G8B8A8_UNORM,.samples=VK_SAMPLE_COUNT_1_BIT};
 else *out=(cinder_vk_target_desc){.width=id?blur.w:blur.out_w,.height=id?blur.h:blur.out_h,.color_format=VK_FORMAT_R8G8B8A8_UNORM,.depth_format=depth16?VK_FORMAT_D16_UNORM:VK_FORMAT_D24_UNORM_S8_UINT,.samples=id==hq.ms_fbo?(VkSampleCountFlagBits)source_samples:VK_SAMPLE_COUNT_1_BIT,.color_usage=id==hq.ms_fbo?source_usage:target_usage};return 1;
}
int cinder_vk_draw_init(cinder_vk_draw*d,uint32_t p,uint32_t target,int w,int h){
 ++init_count;if(!p||w<=0||h<=0)return 0;
 memset(d,0,sizeof *d);d->program=p;d->target=target;
 d->viewport[2]=d->scissor[2]=w;d->viewport[3]=d->scissor[3]=h;
 for(int i=0;i<8;++i)d->attributes[i].value[3]=1;
 return 1;
}
int cinder_vk_uniform(cinder_vk_draw*d,const char*n,const void*v,size_t b){
 size_t o=0,z=0;
 #define SLOT(nm,f) if(!strcmp(n,nm)){o=offsetof(struct constants,f);z=sizeof(((struct constants*)0)->f);}
 SLOT("uTexel",texel) else SLOT("uView",view) else SLOT("uK",strength) else SLOT("uThresh",threshold) else SLOT("uSharp",sharp) else SLOT("uBloomK",bloom) else assert(0);
 #undef SLOT
 assert(b==z);memcpy(d->uniforms+o,v,b);d->uniform_bytes=sizeof(struct constants);return 1;
}
static int slot(const char*n){if(!strcmp(n,"uTex"))return 0;if(!strcmp(n,"uBloom"))return 1;assert(!strcmp(n,"uAO"));return 2;}
int cinder_vk_texture(cinder_vk_draw*d,const char*n,uint32_t t){assert(t);d->textures[slot(n)]=t;return 1;}
int cinder_vk_sampler_state(cinder_vk_draw*d,const char*n,const cinder_vk_sampler*s){d->samplers[slot(n)]=*s;return 1;}
int cinder_vk_submit(const cinder_vk_draw*d){
 assert(!d->warm_only&&!d->pipeline.depth_test&&!d->pipeline.depth_write&&!d->pipeline.stencil&&!d->pipeline.cull&&d->pipeline.color_mask==15);
 assert(d->pipeline.blend_op==VK_BLEND_OP_ADD&&d->pipeline.src_blend==VK_BLEND_FACTOR_ONE);
 assert(d->viewport[0]==0&&d->viewport[1]==0&&d->scissor[0]==0&&d->scissor[1]==0&&d->viewport[2]==d->scissor[2]&&d->viewport[3]==d->scissor[3]);
 size_t top=d->count-1;
 if(d->indexed){assert(d->index_type==VK_INDEX_TYPE_UINT16&&d->index_bytes==d->count*2);top=0;for(uint32_t i=0;i<d->count;++i){uint16_t x;memcpy(&x,(const char*)d->indices+i*2,2);if(x>top)top=x;}}
 int attrs=d->indexed?3:1;
 for(int i=0;i<attrs;++i){const cinder_vk_attribute*a=&d->attributes[i];size_t width=i==2?4:8;assert(!a->buffer&&a->data&&a->stride&&a->offset+top*a->stride+width<=a->bytes);}
 assert(count<128);packets[count]=*d;assert(d->attributes[0].bytes<=sizeof positions[0]);memcpy(positions[count],d->attributes[0].data,d->attributes[0].bytes);
 ++count;return count!=fail_submit;
}
int cinder_vk_copy_ready(const cinder_vk_copy_region*c){
 ++copy_queries;copy_query=*c;
 assert(c->source==hq.ms_fbo&&c->target==blur.fbo&&c->aspects==VK_IMAGE_ASPECT_COLOR_BIT&&c->filter==VK_FILTER_NEAREST);
 assert(!c->source_rect[0]&&!c->source_rect[1]&&!c->target_rect[0]&&!c->target_rect[1]);
 assert(c->source_rect[2]==blur.w&&c->source_rect[3]==blur.h&&c->target_rect[2]==blur.w&&c->target_rect[3]==blur.h);
 return source_samples>1 || !copy_no_blit;
}
int cinder_vk_copy(const cinder_vk_copy_region*c){++copies;copied=*c;return !fail_copy;}
int cinder_vk_discard(uint32_t t,VkImageAspectFlags a){++discards;discarded_target=t;discarded_aspects=a;return !fail_discard;}
int cinder_vk_clear(uint32_t t,VkImageAspectFlags a,const float*c,const int*r){
 ++clears;clear_target=t;clear_aspects=a;assert(a==(depth16?3u:7u)&&!r&&!memcmp(c,native_post_clear_color,4*sizeof(float)));return !fail_clear;
}
void cinder_vk_screen_extent(int*w,int*h){*w=1280;*h=720;}
static void frame_sampler(GLuint);
static void frame_sampler_off(void);
#pragma GCC poison glGenTextures glTexImage2D glBindTexture glGenRenderbuffers glBindRenderbuffer glRenderbufferStorage glGenFramebuffers glBindFramebuffer glFramebufferTexture2D glFramebufferRenderbuffer glCheckFramebufferStatus glDeleteTextures glDeleteFramebuffers glDeleteRenderbuffers
static int native_graph_samples,native_graph_fmt,native_graph_dirty;
int cinder_vk_target_ready(uint32_t t){return t&&t!=(uint32_t)bad_target;}
static int native_blur_allocate(int w,int h,int deep,int on,int fmt,int samples,int msrt){
 /* Explicit stub boundary: graph transactions are exercised separately. */
 (void)samples;(void)msrt;assert(!on);blur.tex=next_resource++;blur.depth=next_resource++;blur.fbo=next_resource++;++allocated_targets;blur.w=w;blur.h=h;blur.deep=deep;hq.fmt=fmt;hq.on=on;return 1;
}
static void hq_free(void){++freed_hq;frame_history_valid=0;frame_sampler_off();hq.single_ready=hq.single_attempted=hq.single_frame=0;}
static void vk_single_targets(int w,int h){(void)w;(void)h;hq.single_attempted=1;}
'''
real='\n'.join(fun(x) for x in ['static void frame_sampler(', 'static void frame_sampler_off('])+'\n'+(R/'src/render_native_post.inc').read_text()+'\n'+'\n'.join(fun(x) for x in ['static int hq_resolve_bloom(', 'static int render_blur_begin_inner(', 'int render_blur_begin(', 'void render_blur_end('])
post=r'''
static struct constants uniform_at(int i){struct constants c;memcpy(&c,packets[i].uniforms,sizeof c);return c;}
static void reset(void){
 memset(&hq,0,sizeof hq);memset(&blur,0,sizeof blur);memset(packets,0,sizeof packets);
 hq.on=1;hq.ssao_ok=hq.single_ready=hq.single_frame=hq.view_set=hq.opt_ao=hq.opt_paint=hq.opt_wet=1;hq.scale=.5f;hq.aw=320;hq.ah=240;hq.ssao=1.25f;hq.bloom=.2f;
 hq.view[0]=.5f;hq.view[1]=10000;hq.view[2]=.75f;hq.view[3]=.5f;
 hq.down_prog[0]=11;hq.down_prog[1]=12;hq.up_prog=13;hq.ao_prog=14;hq.ao_blur_prog=15;
 hq.ao_fbo[0]=31;hq.ao_fbo[1]=32;hq.ao_tex[0]=41;hq.ao_tex[1]=42;hq.z_tex=43;
 hq.rt_tex=51;hq.rt_fbo=61;hq.ms_fbo=62;hq.single_fbo[0]=63;hq.single_fbo[1]=64;
 for(int i=0;i<4;++i){hq.w[i]=320>>i;hq.h[i]=240>>i;hq.fbo[i]=71+i;hq.tex[i]=81+i;}
 blur.fbo=91;blur.tex=92;blur.w=640;blur.h=480;blur.screen=0;blur.out_w=1280;blur.out_h=960;blur.deep=2;blur.sharp=.6f;blur.amount=.5f;
 native_scene=(native_scene_view){0,1280,960};native_bloom_ready=0;
 frame_history_valid=0;frame_recording_trusted=1;epoch=frame_start_epoch=frame_history_epoch=0;
 pending=error_once=fail_submit=fail_copy=fail_clear=fail_discard=count=copies=discards=clears=init_count=depth16=0;bad_target=-1;
 copy_queries=0;copy_no_blit=0;source_samples=1;memset(&copy_query,0,sizeof copy_query);
 memset(native_post_clear_color,0,sizeof native_post_clear_color);
 source_usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT;target_usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT;freed_hq=allocated_targets=0;next_resource=200;
}
static void check_chain(void){
 assert(count==9&&hq.ao_on&&native_bloom_ready&&!copies&&!discards);
 assert(packets[0].program==14&&packets[0].target==31&&packets[0].textures[0]==43);
 struct constants a=uniform_at(0);assert(a.texel[0]==1.0f/640&&a.view[1]==10000&&a.strength==1.25f);
 assert(packets[1].program==15&&packets[1].target==32&&packets[1].textures[0]==41&&uniform_at(1).texel[0]==1.0f/320);
 for(int i=0;i<2;++i)assert(packets[i].samplers[0].min_filter==VK_FILTER_NEAREST);
 for(int i=0;i<4;++i){cinder_vk_draw*d=&packets[2+i];assert(d->program==(i?11u:12u)&&d->target==hq.fbo[i]&&d->textures[0]==(i?hq.tex[i-1]:blur.tex));assert(d->viewport[2]==hq.w[i]&&!d->pipeline.blend&&d->pipeline.dst_blend==VK_BLEND_FACTOR_ZERO);assert(uniform_at(2+i).threshold==(i?0.0f:.75f));}
 for(int i=3;i>0;--i){cinder_vk_draw*d=&packets[9-i];assert(d->program==13&&d->target==hq.fbo[i-1]&&d->textures[0]==hq.tex[i]&&d->pipeline.blend&&d->pipeline.dst_blend==VK_BLEND_FACTOR_ONE);assert(uniform_at(9-i).texel[1]==1.0f/hq.h[i]);}
 for(int i=2;i<9;++i){cinder_vk_sampler*s=&packets[i].samplers[0];assert(s->use_state&&!s->mipmaps&&s->min_filter==VK_FILTER_LINEAR&&s->mag_filter==VK_FILTER_LINEAR&&s->address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->anisotropy==1);}
}
int main(void){
 reset();assert(hq_resolve_bloom());check_chain();
 reset();depth16=1;native_scene.target=64;render_scene_clear(.125f,.25f,.5f,1);assert(clears==1&&clear_target==64&&clear_aspects==3&&native_post_clear_color[3]==1);
 render_blur_end();assert(clears==2&&clear_target==0&&clear_aspects==3&&frame_history_valid&&native_post_clear_color[0]==.125f);
 reset();fail_clear=1;render_scene_clear(.1f,.2f,.3f,1);assert(!frame_recording_trusted&&!frame_history_valid);
 reset();assert(render_blur_begin(.5f,1280,960));assert(native_frame_texture==white_tex&&frame_k==0);render_blur_end();
 assert(frame_history_valid&&frame_history_epoch==0&&clears==1&&count==11&&blur.tex==51&&blur.fbo==61&&hq.rt_tex==92&&hq.single_fbo[0]==64);
 assert(packets[2].textures[0]==51);assert(packets[9].program==106&&packets[10].program==105&&packets[9].target==0&&packets[9].viewport[2]==1280);
 assert(packets[9].textures[0]==51&&packets[9].textures[1]==81&&packets[9].textures[2]==42&&packets[9].count==6&&packets[10].count==12);
 assert(uniform_at(9).sharp==.6f&&uniform_at(9).bloom==.2f&&uniform_at(9).texel[1]==1.0f/480);
 assert(positions[9][2]==(positions[9][0]+1)*.5f&&positions[10][4]==1&&positions[10][9]==0);
 assert(render_blur_begin(.5f,1280,960)&&native_frame_texture==51&&frame_k==.9f);hq.view_set=1;count=0;render_blur_end();assert(frame_history_valid&&blur.tex==92&&hq.rt_tex==51&&count==11);
 reset();hq.single_frame=0;hq.bloom=0;assert(hq_resolve_bloom());assert(copies==1&&discards==1&&copied.source==62&&copied.target==91&&copied.source_rect[2]==640&&copied.target_rect[3]==480&&copied.aspects==VK_IMAGE_ASPECT_COLOR_BIT&&copied.filter==VK_FILTER_NEAREST&&discarded_target==62&&discarded_aspects==7&&!hq.ao_on);
 reset();hq.single_frame=0;fail_copy=1;assert(!hq_resolve_bloom()&&!native_bloom_ready&&!count&&!discards);
 reset();fail_submit=1;render_blur_end();assert(!frame_history_valid&&!hq.ao_on&&!hq.single_ready&&count==10&&packets[8].textures[2]==white_tex);
 reset();fail_submit=4;render_blur_end();assert(!frame_history_valid&&!native_bloom_ready&&count==6&&uniform_at(4).bloom==0&&packets[4].textures[1]==blur.tex);
 reset();bad_target=31;render_blur_end();assert(!hq.single_ready&&!hq.ao_on&&!frame_history_valid&&count==9);
 reset();fail_submit=10;render_blur_end();assert(!frame_history_valid&&count==11);
 reset();fail_clear=1;render_blur_end();assert(!frame_history_valid);
 reset();pending=1;render_blur_end();assert(!frame_history_valid);
 reset();epoch=1;render_blur_end();assert(!frame_history_valid);
 reset();epoch=UINT64_MAX;render_blur_end();assert(!frame_history_valid);
 reset();hq.on=0;render_blur_end();assert(!frame_history_valid&&count==2&&packets[0].program==103&&packets[1].program==102&&!packets[0].textures[1]);
 reset();hq.bloom=0;hq.view_set=0;blur.sharp=0;render_blur_end();assert(count==2&&packets[0].program==104&&packets[0].textures[2]==white_tex);
 reset();blur.w=0;assert(!hq_resolve_bloom()&&!count);
 /* Execute the real pre-scene admission + recursive non-HQ allocation path. */
 reset();hq.ssao=0;hq.single_ready=hq.single_frame=0;source_usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
 assert(!native_hq_copy_ready());assert(render_blur_begin(.5f,1280,960));
 assert(!hq.on&&freed_hq==1&&allocated_targets==1&&native_scene.target==blur.fbo&&blur.fbo!=91&&resource_bound==0&&!frame_history_valid&&!copies);
 render_blur_end();assert(count==2&&!copies&&packets[0].textures[0]==blur.tex&&packets[0].program==103&&!frame_history_valid);
 reset();hq.ssao=0;blur.sharp=0;hq.single_ready=hq.single_frame=0;source_usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
 assert(!render_blur_begin(0,1280,960)&&!hq.on&&native_scene.target==0&&!allocated_targets&&!count&&!copies);
 reset();hq.ssao=0;hq.single_ready=hq.single_frame=0;target_usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
 assert(!native_hq_copy_ready());assert(render_blur_begin(.5f,1280,960)&&!hq.on&&freed_hq==1&&native_scene.target==blur.fbo);
 reset();source_usage=0;assert(render_blur_begin(.5f,1280,960)&&hq.on&&hq.single_frame&&!freed_hq&&!allocated_targets&&native_scene.target==64);
 reset();hq.ssao=0;hq.single_frame=hq.single_ready=0;hq.msrt=1;source_usage=0;
 assert(render_blur_begin(.5f,1280,960)&&hq.on&&!freed_hq&&native_scene.target==61);
 reset();hq.ssao=0;hq.single_ready=hq.single_frame=0;assert(native_hq_copy_ready());
 assert(render_blur_begin(.5f,1280,960)&&hq.on&&!freed_hq&&native_scene.target==62);render_blur_end();assert(copies==1&&count==9);
 reset();hq.ssao=0;hq.single_ready=hq.single_frame=0;source_samples=1;copy_no_blit=1;
 assert(!native_hq_copy_ready()&&!copies&&!count&&epoch==0);
 assert(render_blur_begin(.5f,1280,960)&&!hq.on&&freed_hq==1&&native_scene.target==blur.fbo&&!copies&&!count&&!frame_history_valid);
 render_blur_end();assert(!copies&&count==2&&packets[0].textures[0]==blur.tex&&packets[0].program==103);
 reset();hq.ssao=0;hq.single_ready=hq.single_frame=0;source_samples=4;copy_no_blit=1;
 assert(native_hq_copy_ready()&&copy_queries==1&&epoch==0&&!copies&&!count);
 assert(render_blur_begin(.5f,1280,960)&&hq.on&&native_scene.target==hq.ms_fbo&&!copies&&!count);render_blur_end();
 assert(copies==1&&count==9&&!memcmp(&copy_query,&copied,sizeof copied));
 puts("production native post: AO/history, 4 down + 3 LOAD/add up, explicit target/uniform/samplers, RCAS, first/second and failed pass; sample1 noBLIT pre-scene fallback, raw4 resolve admitted, exact readiness/copy region: PASS (UBSan CPU recorder only)");
}
'''
with tempfile.TemporaryDirectory(prefix='native-vk-post-',dir=O) as td:
    td=Path(td); source=td/'test.c'; source.write_text(pre+real+post)
    cmd=['clang','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(R/'src')]
    if sys.platform=='darwin':cmd+=['-I','/opt/homebrew/include']
    exe=td/'test';subprocess.run(cmd+[str(source),'-lm','-o',str(exe)],check=True,timeout=120)
    subprocess.run([str(exe)],check=True,timeout=30)
