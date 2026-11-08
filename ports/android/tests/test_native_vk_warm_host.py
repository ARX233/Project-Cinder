#!/usr/bin/env python3
"""Compile production warm/loader/selftest control paths with UBSan.
Resource uploads/timing are stubs; packets/layout/material choices are real source.
No GL draw, GL uniform, GL query, GL attribute or GL enable API is declared.
"""
from pathlib import Path
import os,re,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[1]; O=Path(os.environ.get('TMPDIR',R.parent/'tmp')).resolve()
assert str(O).startswith('/Volumes/CodexWork/')
S=(R/'src/render.c').read_text()
def fun(anchor,source=S):
    a=source.index(anchor);b=source.index('{',a)
    mask=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),source,flags=re.S);n=0
    for i in range(b,len(source)):
        n+=(mask[i]=='{')-(mask[i]=='}')
        if not n:return source[a:i+1]
    raise ValueError(anchor)
pre=r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#define __ANDROID__ 1
#define WMMT_NATIVE_VK 1
#include "render.h"
#include "native_vk.h"
typedef uint32_t GLuint;typedef int GLint,GLsizei;typedef unsigned GLenum;
#define GL_RENDERBUFFER 1
#define GL_RGB565 2
#define GL_FRAMEBUFFER 3
#define GL_COLOR_ATTACHMENT0 4
#define GL_ARRAY_BUFFER 5
#define GL_STATIC_DRAW 6
#define GL_EXTENSIONS 7
#define GL_TEXTURE_2D 8
#define GL_COMPRESSED_RGB_PVRTC_4BPPV1_IMG 9
#define GL_TEXTURE_MIN_FILTER 10
#define GL_TEXTURE_MAG_FILTER 11
#define GL_LINEAR 12
#define GL_ELEMENT_ARRAY_BUFFER 13
#define GL_VERTEX_ARRAY_BINDING 14
#define OVER_PITCH .61f
static struct {uint32_t id;} progs[2]={{101},{102}},gloss_progs[2]={{103},{104}},lit_progs[6]={ {105},{106},{107},{107},{109},{110} };
static uint32_t white_tex=7;
static int ao_on=1;
typedef struct {uint32_t target;int w,h;} native_scene_view;
static native_scene_view native_scene={19,640,480};
enum {WARM_NEW_POOL,WARM_NEW_TEX,WARM_OLD,WARM_KINDS};
static struct {int n[WARM_KINDS];double ms[WARM_KINDS],max[WARM_KINDS];} warm_cost;
static unsigned initialized,submitted,warmed,drawn,reject,finish_count;
static cinder_vk_draw packets[512];
static unsigned char vc[512][128];
struct values {float mvp[16],mv[16],eye[3],fog[2],fog_color[3],grade[3],uv[2],wet,horizon[3],l0[3],l1[3],d0[3],d1[3],amb[3],power,over[2],over_dir[2],frame_k;};
static unsigned next_id=200;
static size_t buffer_size[512];
static uint16_t buffer_indices[512][3];
static uint32_t selftest_target;
static unsigned compile_count;
uint32_t cinder_vk_program_create(const char*v,const char*f,const char**attrs,int n){assert(v&&f&&attrs&&n);++compile_count;return 111;}
int cinder_vk_program_ready(uint32_t p){return p==111;}
void cinder_vk_program_destroy(uint32_t p){assert(p==111);}
#pragma GCC poison gl_compile_program glGetUniformLocation glUseProgram glDeleteProgram
void cinder_vk_screen_extent(int*w,int*h){*w=1280;*h=720;}
int cinder_vk_draw_init(cinder_vk_draw*d,uint32_t p,uint32_t t,int w,int h){
 ++initialized;if(!p||w<=0||h<=0)return 0;memset(d,0,sizeof*d);d->program=p;d->target=t;d->viewport[2]=d->scissor[2]=w;d->viewport[3]=d->scissor[3]=h;
 for(int i=0;i<8;++i)d->attributes[i].value[3]=1;return 1;
}
int cinder_vk_uniform(cinder_vk_draw*d,const char*n,const void*v,size_t b){size_t o=0,z=0;
#define SLOT(nm,f) if(!strcmp(n,nm)){o=offsetof(struct values,f);z=sizeof(((struct values*)0)->f);}
 SLOT("uMVP",mvp) else SLOT("uMV",mv) else SLOT("uEye",eye) else SLOT("uFog",fog) else SLOT("uFogColor",fog_color) else SLOT("uGrade",grade) else SLOT("uUVOff",uv) else SLOT("uWet",wet) else SLOT("uHorizon",horizon) else SLOT("uL0",l0) else SLOT("uL1",l1) else SLOT("uD0",d0) else SLOT("uD1",d1) else SLOT("uAmb",amb) else SLOT("uPower",power) else SLOT("uOver",over) else SLOT("uOverDir",over_dir) else SLOT("uFrameK",frame_k) else assert(0);
#undef SLOT
 assert(b==z);memcpy(d->uniforms+o,v,b);d->uniform_bytes=sizeof(struct values);return 1;
}
static int slot(const char*n){static const char*names[]={"uTex","uFrame","uGloss","uCube","uAO","uOverTex","uEnv","uSpec"};for(int i=0;i<8;++i)if(!strcmp(n,names[i]))return i;assert(0);return 0;}
int cinder_vk_texture(cinder_vk_draw*d,const char*n,uint32_t t){if(!t)return 0;d->textures[slot(n)]=t;return 1;}
int cinder_vk_submit(const cinder_vk_draw*d){
 ++submitted;if(reject)return 0;
 assert(submitted<512&&d->count>0&&d->count<=3&&d->pipeline.topology==VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST);
 assert(d->pipeline.color_mask==15&&!d->pipeline.stencil&&d->pipeline.blend_op==VK_BLEND_OP_ADD&&d->scissor[2]==1&&d->scissor[3]==1);
 size_t top=d->count-1;
 if(d->indexed){assert(d->index_type==VK_INDEX_TYPE_UINT16&&d->index_buffer&&d->index_offset+d->count*2<=buffer_size[d->index_buffer]);top=2;}
 for(int i=0;i<4;++i){const cinder_vk_attribute*a=&d->attributes[i];if(a->format==VK_FORMAT_UNDEFINED)continue;
  size_t width=i==0?12:i==1?8:i==2?4:6;
  assert(a->stride);if(a->buffer){assert(a->buffer<512&&a->offset+top*a->stride+width<=buffer_size[a->buffer]);}
  else assert(a->data&&a->offset+top*a->stride+width<=a->bytes);
 }
 packets[submitted]=*d;
 if(!d->attributes[0].buffer){assert(d->attributes[0].bytes<=sizeof vc[0]);memcpy(vc[submitted],d->attributes[0].data,d->attributes[0].bytes);}
 if(d->warm_only)++warmed;else {++drawn;assert(d->target==selftest_target&&d->viewport[2]==1&&d->viewport[3]==1);}
 return 1;
}
int cinder_vk_finish(void){++finish_count;return 1;}
uint32_t cinder_vk_attachment_create(const cinder_vk_storage_desc*d){assert(d&&d->width==1&&d->height==1&&d->format==CINDER_VK_STORAGE_RGB565&&d->samples==1);return next_id++;}
uint32_t cinder_vk_target_create(const cinder_vk_target_create_desc*d){assert(d&&d->color.kind==CINDER_VK_IMAGE_ATTACHMENT&&d->color.id&&!d->depth_stencil.id);selftest_target=next_id++;return selftest_target;}
int cinder_vk_target_ready(uint32_t t){return t&&t==selftest_target;}
int cinder_vk_target_info(uint32_t t,cinder_vk_target_desc*out){assert(t==selftest_target);*out=(cinder_vk_target_desc){.width=1,.height=1,.color_format=VK_FORMAT_R5G6B5_UNORM_PACK16,.samples=VK_SAMPLE_COUNT_1_BIT};return 1;}
void cinder_vk_target_destroy(uint32_t t){(void)t;}
void cinder_vk_attachment_destroy(uint32_t t){(void)t;}
void cinder_vk_texture_destroy(uint32_t t){(void)t;}
uint32_t cinder_vk_buffer_create(size_t n,const void*p){GLuint b=next_id++;assert(b<512&&p&&n);buffer_size[b]=n;if(n==9000*2)memcpy(buffer_indices[b],p,6);return b;}
void cinder_vk_buffer_destroy(uint32_t b){(void)b;}
#pragma GCC poison glGenBuffers glBindBuffer glBufferData glBufferSubData glDeleteBuffers glGenVertexArraysOES glBindVertexArrayOES glDeleteVertexArraysOES glVertexAttribPointer glEnableVertexAttribArray glDisableVertexAttribArray
#pragma GCC poison glFinish glGenTextures glDeleteTextures glBindTexture glCompressedTexImage2D glTexParameteri glGetString glGetError glGenRenderbuffers glBindRenderbuffer glRenderbufferStorage glGenFramebuffers glBindFramebuffer glFramebufferRenderbuffer glDeleteRenderbuffers glDeleteFramebuffers
static GLuint st_texture(int size,int mips,double*api,double*cpu){assert(size==256||size==512);assert(mips>=0&&mips<=2);*api=1;*cpu=mips==2?.5:0;return next_id++;}
'''
real=fun('static GLuint native_program_create(')+'\n'+fun('static void native_program_release(')+'\n'+fun('static void native_mesh(', (R/'src/render_native_scene.inc').read_text())+'\n'+(R/'src/render_native_warm.inc').read_text()+'\n'
real+='\n'.join(fun(x) for x in ['static double warm_clock(', 'static int wpk_chunk_valid(', 'static float box_distance(', 'static void warm_cube(', 'static int native_warm_draw(', 'void wpk_warm_stats(', 'static int chunk_in_reach(', 'static int warm_batches(', 'int wpk_prewarm(', 'int wpk_warm_near(', 'int wpk_cold_near('])
# Shader literals retained exactly; reflection/compiler is the explicitly stubbed resource boundary.
real+='\n'+S[S.index('static const char *WARM_VS ='):S.index('void render_warm_begin(')]+'\n'
targets=(R/'src/render_native_targets.inc').read_text()
real+='\n'+fun('static GLuint native_target_attachment(',targets)+fun('static GLuint native_target_compose(',targets)
real+='\n'.join(fun(x) for x in ['void render_warm_begin(', 'int wpk_warm(', 'void render_warm_texture(', 'int wpk_warm_paints(', 'static double st_ms(', 'static double st_draw(', 'void render_selftest('])
post=r'''
static struct values values_at(unsigned n){struct values v;memcpy(&v,packets[n].uniforms,sizeof v);return v;}
int main(void){
 wpk_pool pool={.vbo=1,.ibo=2,.nbo=3};buffer_size[1]=3*32;buffer_size[2]=6;buffer_size[3]=24;
 wpk_batch batch={.tex=0,.count=3,.env=0xffff,.spec=0xffff,.gloss=0xffff,.cube=0xffff,.power=.4f};
 uint32_t tex[4]={21,22,23,24},cube[1]={25},ao[1]={26};unsigned char tw[4]={0},cw[1]={0},warm[2]={0};
 wpk_chunk chunks[2]={ {.first=UINT32_MAX,.n=2}, {.first=0,.n=1} };
 wpk_scene s={.n_tex=4,.textures=tex,.loaded=tex,.n_pools=1,.pools=&pool,.stride=24,.tex_warm=tw,.n_cube=1,.cubes=cube,.cube_warm=cw,.n_ao=1,.ao_tex=ao,.n_chunk=2,.n_batch=1,.batches=&batch,.chunks=chunks,.warm=warm,.warm_chunk=-1,.next_batch=1};
 render_warm_begin();assert(compile_count==1&&submitted==0);render_warm_begin();assert(compile_count==1);
 render_warm_texture(21);assert(submitted==1&&warmed==1&&!drawn&&!finish_count&&packets[1].warm_only&&packets[1].program==111&&packets[1].target==0&&packets[1].textures[0]==21);
 warm_cube(25);assert(submitted==2&&warmed==2&&packets[2].textures[3]==25&&packets[2].attributes[0].bytes==36);
 assert(wpk_warm(&s,1)==1&&warm[0]&&warm[1]&&tw[0]&&pool.warm);assert(packets[3].program==101&&packets[3].pipeline.depth_test&&packets[3].pipeline.depth_write&&packets[3].pipeline.cull==VK_CULL_MODE_BACK_BIT);
 struct values v=values_at(3);assert(v.mvp[0]==1&&v.mvp[15]==1&&v.grade[1]==1&&v.fog[0]==1e30f&&v.wet==0&&v.frame_k==0&&packets[3].textures[1]==white_tex);
 batch.cutout=1;assert(native_warm_draw(&s,&batch,21,0,NULL));assert(packets[4].program==102);
 batch.flags=1;assert(native_warm_draw(&s,&batch,21,0,NULL));assert(packets[5].program==101&&packets[5].pipeline.blend&&!packets[5].pipeline.depth_write&&packets[5].pipeline.src_blend==VK_BLEND_FACTOR_SRC_ALPHA&&packets[5].pipeline.dst_blend==VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA);
 batch.flags=2;assert(native_warm_draw(&s,&batch,21,0,NULL));assert(packets[6].pipeline.dst_blend==VK_BLEND_FACTOR_ONE);
 batch.flags=0;batch.gloss=1;batch.cube=0;assert(native_warm_draw(&s,&batch,21,0,NULL));assert(packets[7].program==104&&packets[7].textures[2]==22&&packets[7].textures[3]==25&&tw[1]&&cw[0]);
 render_params params={.no_gloss=1,.no_depth_test=1};assert(native_warm_draw(&s,&batch,21,0,&params));assert(packets[8].program==102&&!packets[8].pipeline.depth_test&&!packets[8].textures[3]);
 s.lit=1;s.stride=32;batch.gloss=batch.cube=0xffff;batch.env=1;batch.spec=2;batch.cutout=0;
 for(int prog=0;prog<3;++prog){batch.prog=prog;assert(native_warm_draw(&s,&batch,21,0,NULL));cinder_vk_draw*d=&packets[submitted];assert(d->program==lit_progs[2*prog].id&&d->textures[4]==26&&d->textures[5]==white_tex&&d->textures[1]==white_tex&&d->attributes[3].buffer==3);if(prog)assert(d->textures[6]==22&&d->textures[7]==23);assert(values_at(submitted).power==.4f);}
 unsigned before=submitted;batch.pool=2;assert(!native_warm_draw(&s,&batch,21,0,NULL)&&submitted==before);batch.pool=0;batch.prog=99;assert(!native_warm_draw(&s,&batch,21,0,NULL));batch.prog=0;batch.env=9;assert(!native_warm_draw(&s,&batch,21,0,NULL));batch.env=1;
 assert(!native_warm_draw(&s,&batch,21,7,NULL));s.lit=0;batch.gloss=4;batch.cube=0;assert(!native_warm_draw(&s,&batch,21,0,NULL));batch.gloss=1;batch.cube=1;assert(!native_warm_draw(&s,&batch,21,0,NULL));batch.gloss=batch.cube=0xffff;
 reject=1;pool.warm=0;tw[0]=0;assert(!native_warm_draw(&s,&batch,21,0,NULL)&&!pool.warm&&!tw[0]);reject=0;
 warm[1]=0;s.warm_chunk=-1;reject=1;assert(wpk_warm(&s,1)==0&&!warm[1]&&s.warm_batch==0);reject=0;
 mat4 identity=mat4_identity();assert(wpk_prewarm(&s,&identity,NULL,0,1,NULL)==1);assert(packets[submitted].target==19&&packets[submitted].viewport[2]==640);
 wpk_paint_swap paints[2]={ {.src=UINT16_MAX,.dst=0}, {.src=3,.dst=0} };s.paints=paints;s.n_paints=2;assert(wpk_warm_paints(&s,1)==1&&tw[3]&&packets[submitted].textures[0]==24);
 assert(wpk_cold_near(&s,NULL,0,NULL)==0);
 before=drawn;selftest_target=123;double a=st_draw(1,21,123),b=st_draw(1,21,123);assert(a>=0&&b>=0&&drawn==before+2&&!packets[submitted].warm_only&&packets[submitted].program==111&&packets[submitted].target==123);
 reject=1;assert(st_draw(1,21,123)==-1);reject=0;
 unsigned old_drawn=drawn,old_warmed=warmed;char out[4096];render_selftest(out,sizeof out);
 assert(drawn==old_drawn+15&&warmed==old_warmed&&strstr(out,"batch 4000 verts")&&strstr(out,"512 nomip"));
 assert(packets[submitted].indexed&&packets[submitted].count==3&&packets[submitted].index_buffer&&packets[submitted].attributes[0].buffer&&!packets[submitted].warm_only);
 assert(!memcmp(buffer_indices[packets[submitted].index_buffer],(uint16_t[3]){0,1,2},6));
 char stats[512];wpk_warm_stats(stats,sizeof stats);assert(strstr(stats,"first draws:")&&!warm_cost.n[0]);
 puts("production native warm: material variants, warm_only vs actual selftest draws, bounded buffers/chunks/paint, failed retry: PASS (UBSan CPU recorder, resource/timing stubs)");
}
'''
with tempfile.TemporaryDirectory(prefix='native-vk-warm-',dir=O) as td:
    td=Path(td);src=td/'test.c';src.write_text(pre+real+post);exe=td/'test'
    cmd=['clang','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(R/'src')]
    if sys.platform=='darwin':cmd+=['-I','/opt/homebrew/include']
    subprocess.run(cmd+[str(src),'-lm','-o',str(exe)],check=True,timeout=120)
    subprocess.run([str(exe)],check=True,timeout=30)
