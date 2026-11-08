#!/usr/bin/env python3
"""UBSan CPU contracts for the production wide_sides source region.

Compiles the actual contiguous app.c region plus app_native_sides.inc, not a
reimplementation. Native GL draw/query/error/uniform/VAO/program entrypoints are
poisoned; explicit native program/target/storage ownership is recorded independently.
There is no native GL target-resource allocator bridge. GLES and
VKcompat production paths supply independent draw/copy goldens. Not GPU pixels,
driver capability, Android runtime, or original game-physics evidence.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(os.environ.get("TMPDIR", ROOT.parent / "tmp")).resolve()
TMP.mkdir(parents=True, exist_ok=True)
APP = (ROOT / "src/app.c").read_text()
START = "typedef void (*blit_fn)"
END = "\n/* Every frozen GO member"
REGION = APP[APP.index(START):APP.index(END)]
# Shader and geometry stay in the shared production code, not in a test oracle.
assert REGION.count("static void wide_sides(") == 1
assert REGION.count("sides_native_draw(") == 1

PREFIX = r'''
#include <assert.h>
#include <float.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define RACING_LAMP_TEST 1
#include "glstub.h"
#include "native_vk.h"
#define GL_FRAMEBUFFER 0x8D40
#define GL_FRAMEBUFFER_BINDING 0x8CA6
#define GL_COLOR_ATTACHMENT0 0x8CE0
static struct { int fb_w, fb_h; float edge; } G;
GLuint gl_compile_program(const char *,const char *,const char **,int);
void glGenFramebuffers(GLsizei,GLuint *);
void glDeleteFramebuffers(GLsizei,const GLuint *);
void glBindFramebuffer(GLenum,GLuint);
void glFramebufferTexture2D(GLenum,GLenum,GLenum,GLuint,GLint);
void glCopyTexSubImage2D(GLenum,GLint,GLint,GLint,GLint,GLint,GLsizei,GLsizei);
void *eglGetProcAddress(const char *);
#ifdef WMMT_NATIVE_VK
#pragma GCC poison glGetIntegerv glGetBooleanv glGetFloatv glGetUniformLocation glGetUniformfv glGetUniformiv glGetError
#pragma GCC poison glUseProgram glUniform1i glUniform1f glUniform2f glUniform3fv glUniform4f glUniform4fv glUniformMatrix4fv glActiveTexture
#pragma GCC poison glEnable glDisable glDepthFunc glDepthMask glBlendFunc glBlendEquation glViewport glScissor glClear
#pragma GCC poison glVertexAttribPointer glVertexAttrib4f glEnableVertexAttribArray glDisableVertexAttribArray glBindBuffer glBindVertexArrayOES
#pragma GCC poison glDrawArrays glDrawElements glCopyTexSubImage2D eglGetProcAddress cinder_vk_texture_sampler gl_compile_program
#pragma GCC poison glGenTextures glDeleteTextures glBindTexture glTexImage2D glTexParameteri glGenFramebuffers glDeleteFramebuffers glBindFramebuffer glFramebufferTexture2D
#endif
'''

RECORDER = r'''
static unsigned next_id=10, bound_tex=88, draw_fb=91, read_fb=91, attached[4096];
static int tex_w[4096],tex_h[4096],tex_fmt[4096];
static unsigned alloc_n,image_n,del_tex_n,del_fb_n,attach_n,compile_n,egl_n,query_n,error_reads,draw_n,copy_n;
static int compile_fail,no_blit,init_fail,uniform_fail,texture_fail,sampler_fail,submit_fail;
static int program_notready,storage_fail,target_create_fail,target_ready_fail;static unsigned ready_n,destroy_program_n,storage_calls,target_calls;
static uint64_t copy_fail_mask,error_epoch;
static unsigned sticky_error;
static const float *attrib[3];
static float current_dy;
static cinder_vk_copy_region copies[64];
static struct {cinder_vk_draw d;float v[20];float dy;} draws[64];
static const char *program_vs,*program_fs;

static void failed(void){++error_epoch;if(!sticky_error)sticky_error=0x0502;}
static void reset(void){
 memset(&SIDES,0,sizeof SIDES);memset(attached,0,sizeof attached);
 memset(tex_w,0,sizeof tex_w);memset(tex_h,0,sizeof tex_h);memset(tex_fmt,0,sizeof tex_fmt);
 next_id=10;bound_tex=88;draw_fb=read_fb=91;
 alloc_n=image_n=del_tex_n=del_fb_n=attach_n=compile_n=egl_n=query_n=error_reads=draw_n=copy_n=0;
 compile_fail=no_blit=init_fail=uniform_fail=texture_fail=sampler_fail=submit_fail=0;
 program_notready=storage_fail=target_create_fail=target_ready_fail=0;ready_n=destroy_program_n=storage_calls=target_calls=0;
 copy_fail_mask=error_epoch=sticky_error=0;G.fb_w=1920;G.fb_h=1080;G.edge=128;
 memset(draws,0,sizeof draws);memset(copies,0,sizeof copies);
}
static void closef(float x,float y){assert(fabsf(x-y)<0.000002f);}
static GLuint record_program(const char *vs,const char *fs,const char **a,int n){
 ++compile_n;assert(n==3&&!strcmp(a[0],"aPos")&&!strcmp(a[1],"aUV")&&!strcmp(a[2],"aShade"));
 program_vs=vs;program_fs=fs;return compile_fail?0:7;
}
#ifdef WMMT_NATIVE_VK
uint32_t cinder_vk_program_create(const char*vs,const char*fs,const char**a,int n){return record_program(vs,fs,a,n);}
int cinder_vk_program_ready(uint32_t id){++ready_n;return id==7&&!program_notready;}
void cinder_vk_program_destroy(uint32_t id){assert(id==7);++destroy_program_n;}
#else
GLuint gl_compile_program(const char *vs,const char *fs,const char **a,int n){return record_program(vs,fs,a,n);}
#endif
#ifndef WMMT_NATIVE_VK
void glGenTextures(GLsizei n,GLuint *p){assert(n==1);*p=next_id++;++alloc_n;}
void glDeleteTextures(GLsizei n,const GLuint *p){assert(n==1&&*p);++del_tex_n;}
void glBindTexture(GLenum t,GLuint id){assert(t==GL_TEXTURE_2D);bound_tex=id;}
void glTexImage2D(GLenum t,GLint level,GLint internal,GLsizei w,GLsizei h,GLint border,GLenum fmt,GLenum type,const void *data){
 assert(t==GL_TEXTURE_2D&&!level&&!border&&!data&&type==GL_UNSIGNED_BYTE&&bound_tex<4096);
#ifdef __ANDROID__
 assert(w==G.fb_w&&h==G.fb_h&&(internal==0x8051||internal==0x8058)&&fmt==(internal==0x8051?GL_RGB:GL_RGBA));
#else
 assert(w==2&&h==G.fb_h&&internal==GL_RGB&&fmt==GL_RGB);
#endif
 tex_w[bound_tex]=w;tex_h[bound_tex]=h;tex_fmt[bound_tex]=internal;++image_n;
}
void glTexParameteri(GLenum target,GLenum name,GLint value){
 assert(target==GL_TEXTURE_2D);
 assert(((name==GL_TEXTURE_MIN_FILTER||name==GL_TEXTURE_MAG_FILTER)&&value==GL_LINEAR)||
        ((name==GL_TEXTURE_WRAP_S||name==GL_TEXTURE_WRAP_T)&&value==GL_CLAMP_TO_EDGE));
}
void glGenFramebuffers(GLsizei n,GLuint *p){assert(n==1);*p=next_id++;}
void glDeleteFramebuffers(GLsizei n,const GLuint *p){assert(n==1&&*p);++del_fb_n;}
void glBindFramebuffer(GLenum target,GLuint id){
 if(target==GL_FRAMEBUFFER)draw_fb=read_fb=id;else {assert(target==0x8CA8);read_fb=id;}
}
void glFramebufferTexture2D(GLenum target,GLenum attachment,GLenum t,GLuint texture,GLint level){
 assert(target==GL_FRAMEBUFFER&&attachment==GL_COLOR_ATTACHMENT0&&t==GL_TEXTURE_2D&&!level);
 assert(draw_fb==SIDES.fb&&draw_fb&&texture==SIDES.tex);attached[draw_fb]=texture;++attach_n;
}
#else
uint32_t cinder_vk_texture_storage(const cinder_vk_storage_desc*d){++storage_calls;assert(d&&d->width==G.fb_w&&d->height==G.fb_h&&d->samples==1&&d->format==CINDER_VK_STORAGE_RGBA8&&!d->transfer_src&&d->transfer_dst&&!d->transient);assert(d->sampler.use_state&&d->sampler.min_filter==VK_FILTER_LINEAR&&d->sampler.mag_filter==VK_FILTER_LINEAR&&!d->sampler.mipmaps&&d->sampler.mipmap_mode==VK_SAMPLER_MIPMAP_MODE_NEAREST&&d->sampler.address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&d->sampler.address_v==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&d->sampler.anisotropy==1);if(storage_fail)return 0;uint32_t id=next_id++;tex_w[id]=d->width;tex_h[id]=d->height;tex_fmt[id]=0x8058;++alloc_n;++image_n;return id;}
void cinder_vk_texture_destroy(uint32_t id){assert(id&&tex_w[id]&&tex_h[id]);tex_w[id]=tex_h[id]=0;++del_tex_n;}
uint32_t cinder_vk_target_create(const cinder_vk_target_create_desc*d){++target_calls;assert(d&&d->color.kind==CINDER_VK_IMAGE_TEXTURE&&d->color.id&&tex_w[d->color.id]&&!d->depth_stencil.id&&d->depth_stencil.kind==CINDER_VK_IMAGE_NONE&&!d->resolve_samples);if(target_create_fail)return 0;uint32_t id=next_id++;attached[id]=d->color.id;++attach_n;return id;}
int cinder_vk_target_ready(uint32_t id){assert(id&&attached[id]);return !target_ready_fail;}
void cinder_vk_target_destroy(uint32_t id){assert(id&&attached[id]);attached[id]=0;++del_fb_n;}
#endif
static int record_copy(const cinder_vk_copy_region *r){
 assert(copy_n<64);copies[copy_n]=*r;int ok=!(copy_fail_mask&(UINT64_C(1)<<copy_n));++copy_n;
 if(!ok)failed();return ok;
}
int cinder_vk_copy(const cinder_vk_copy_region *r){
 assert(!r->source&&r->target==SIDES.fb&&r->target&&attached[r->target]==SIDES.tex);
 assert(tex_w[SIDES.tex]==G.fb_w&&tex_h[SIDES.tex]==G.fb_h);
 return record_copy(r);
}
int cinder_vk_draw_init(cinder_vk_draw *d,uint32_t p,uint32_t target,int w,int h){
 if(init_fail||!p||w<=0||h<=0)return 0;
 memset(d,0,sizeof *d);d->program=p;d->target=target;d->uniform_bytes=16;
 d->viewport[2]=d->scissor[2]=w;d->viewport[3]=d->scissor[3]=h;
 memset(&d->pipeline,0x55,sizeof d->pipeline);memset(d->attributes,0x66,sizeof d->attributes);
 d->index_type=VK_INDEX_TYPE_UINT16;return 1;
}
int cinder_vk_uniform(cinder_vk_draw *d,const char *n,const void *p,size_t bytes){
 assert(!strcmp(n,"uDy")&&bytes==4);if(uniform_fail)return 0;memcpy(d->uniforms,p,bytes);return 1;
}
int cinder_vk_texture(cinder_vk_draw *d,const char *n,uint32_t texture){
 assert(!strcmp(n,"uTex"));if(texture_fail)return 0;d->textures[0]=texture;return 1;
}
int cinder_vk_sampler_state(cinder_vk_draw *d,const char *n,const cinder_vk_sampler *s){
 assert(!strcmp(n,"uTex"));if(sampler_fail)return 0;d->samplers[0]=*s;return 1;
}
int cinder_vk_submit(const cinder_vk_draw *d){
 if(submit_fail){failed();return 0;}
 assert(draw_n<64&&d->program==SIDES.prog&&!d->target&&!d->indexed&&!d->first&&d->count==4&&!d->warm_only);
 assert(!d->index_buffer&&!d->index_offset&&!d->indices&&!d->index_bytes);
 assert(!memcmp(d->viewport,(int[]){0,0,G.fb_w,G.fb_h},sizeof d->viewport));
 assert(!memcmp(d->scissor,d->viewport,sizeof d->viewport));
 const cinder_vk_pipeline *p=&d->pipeline;
 assert(p->topology==VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP&&!p->blend&&p->src_blend==VK_BLEND_FACTOR_ONE&&p->dst_blend==VK_BLEND_FACTOR_ZERO&&p->blend_op==VK_BLEND_OP_ADD&&p->color_mask==15);
 assert(!p->depth_test&&!p->depth_write&&p->depth_compare==VK_COMPARE_OP_LESS_OR_EQUAL&&!p->cull&&p->asset_front==VK_FRONT_FACE_COUNTER_CLOCKWISE);
 assert(!p->stencil&&p->stencil_compare==VK_COMPARE_OP_ALWAYS&&p->stencil_fail==VK_STENCIL_OP_KEEP&&p->depth_fail==VK_STENCIL_OP_KEEP&&p->depth_pass==VK_STENCIL_OP_KEEP&&p->stencil_compare_mask==255&&p->stencil_write_mask==255);
 for(int i=0;i<3;++i){const cinder_vk_attribute *a=&d->attributes[i];assert(a->format==(i<2?VK_FORMAT_R32G32_SFLOAT:VK_FORMAT_R32_SFLOAT)&&a->stride==20&&!a->buffer&&a->offset==(size_t)(i*8)&&a->data&&a->bytes==80);assert(a->offset+3*a->stride+(i<2?8:4)<=a->bytes);assert(a->data==d->attributes[0].data);}
 for(int i=3;i<CINDER_VK_ATTRIBUTES;++i){const cinder_vk_attribute *a=&d->attributes[i];assert(a->format==VK_FORMAT_UNDEFINED&&!a->buffer&&!a->offset&&!a->data&&!a->bytes&&!a->stride);for(int j=0;j<4;++j)assert(a->value[j]==1);}
 assert(d->textures[0]==SIDES.tex);for(int i=1;i<CINDER_VK_SAMPLERS;++i)assert(!d->textures[i]);
 const cinder_vk_sampler *s=&d->samplers[0];assert(s->use_state&&!s->mipmaps&&s->min_filter==VK_FILTER_LINEAR&&s->mag_filter==VK_FILTER_LINEAR&&s->mipmap_mode==VK_SAMPLER_MIPMAP_MODE_NEAREST&&s->address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->address_v==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->anisotropy==1);
 draws[draw_n].d=*d;memcpy(draws[draw_n].v,d->attributes[0].data,80);memcpy(&draws[draw_n].dy,d->uniforms,4);++draw_n;return 1;
}
#ifndef WMMT_NATIVE_VK
GLenum glGetError(void){++error_reads;GLenum e=sticky_error;sticky_error=0;return e;}
void glGetIntegerv(GLenum name,GLint *v){assert(name==GL_FRAMEBUFFER_BINDING);++query_n;*v=(GLint)draw_fb;}
GLint glGetUniformLocation(GLuint p,const char *n){assert(p==7);return !strcmp(n,"uTex")?1:!strcmp(n,"uDy")?2:-1;}
void glUseProgram(GLuint p){assert(p==7);}
void glUniform1i(GLint u,GLint v){assert(u==1&&!v);}
void glUniform1f(GLint u,GLfloat v){assert(u==2);current_dy=v;}
void glActiveTexture(GLenum unit){assert(unit==GL_TEXTURE0);}
void glDisable(GLenum feature){assert(feature==GL_DEPTH_TEST||feature==GL_CULL_FACE||feature==GL_BLEND);}
void glBindBuffer(GLenum target,GLuint id){assert(target==GL_ARRAY_BUFFER&&!id);}
void glEnableVertexAttribArray(GLuint index){assert(index<3);}
void glDisableVertexAttribArray(GLuint index){assert(index==2);}
void glVertexAttribPointer(GLuint index,GLint size,GLenum type,GLboolean norm,GLsizei stride,const void *data){assert(index<3&&size==(index<2?2:1)&&type==GL_FLOAT&&!norm&&stride==20);attrib[index]=data;}
void glViewport(GLint x,GLint y,GLsizei w,GLsizei h){assert(!x&&!y&&w==G.fb_w&&h==G.fb_h);}
void glDrawArrays(GLenum mode,GLint first,GLsizei n){assert(mode==GL_TRIANGLE_STRIP&&!first&&n==4&&draw_n<64&&attrib[1]==attrib[0]+2&&attrib[2]==attrib[0]+4);memcpy(draws[draw_n].v,attrib[0],80);draws[draw_n++].dy=current_dy;}
static void legacy_blit(GLint x0,GLint y0,GLint x1,GLint y1,GLint a0,GLint b0,GLint a1,GLint b1,GLbitfield mask,GLenum filter){
 assert(mask==GL_COLOR_BUFFER_BIT&&filter==GL_NEAREST&&draw_fb==SIDES.fb&&attached[draw_fb]==SIDES.tex);
 cinder_vk_copy_region r={.source=read_fb,.target=draw_fb,.source_rect={x0,y0,x1,y1},.target_rect={a0,b0,a1,b1},.aspects=VK_IMAGE_ASPECT_COLOR_BIT,.filter=VK_FILTER_NEAREST};record_copy(&r);
}
void *eglGetProcAddress(const char *name){assert(!strcmp(name,"glBlitFramebuffer"));++egl_n;return no_blit?NULL:(void*)legacy_blit;}
void glCopyTexSubImage2D(GLenum t,GLint level,GLint x,GLint y,GLint sx,GLint sy,GLsizei w,GLsizei h){
 assert(t==GL_TEXTURE_2D&&!level&&!y&&!sy&&w==1&&h==G.fb_h);
 cinder_vk_copy_region r={.source=draw_fb,.target=SIDES.tex,.source_rect={sx,0,sx+1,h},.target_rect={x,0,x+1,h},.aspects=VK_IMAGE_ASPECT_COLOR_BIT,.filter=VK_FILTER_NEAREST};record_copy(&r);
}
#endif
'''

TESTS = r'''
static uint64_t digest=UINT64_C(1469598103934665603);
static void hashbytes(const void *p,size_t n){const unsigned char *b=p;for(size_t i=0;i<n;++i)digest=(digest^b[i])*UINT64_C(1099511628211);}
static void geometry(int x0){
 assert(draw_n==2&&copy_n==2);int xl=x0+1,xr=G.fb_w-x0-2;
 float e=2.0f*x0/G.fb_w,ul=(xl+.5f)/G.fb_w,ur=(xr+.5f)/G.fb_w;
#ifndef __ANDROID__
 ul=.25f;ur=.75f;
#endif
#ifdef WMMT_VK
 float v0=1,v1=0;
#else
 float v0=0,v1=1;
#endif
 const float expect[2][20]={
  {-1,-1,ul,v0,.55f,-1+e,-1,ul,v0,1,-1,1,ul,v1,.55f,-1+e,1,ul,v1,1},
  {1-e,-1,ur,v0,1,1,-1,ur,v0,.55f,1-e,1,ur,v1,1,1,1,ur,v1,.55f}};
 for(int s=0;s<2;++s){for(int i=0;i<20;++i)closef(draws[s].v[i],expect[s][i]);closef(draws[s].dy,1.5f/G.fb_h);hashbytes(draws[s].v,80);hashbytes(&draws[s].dy,4);}
 for(int s=0;s<2;++s){int x=s?xr:xl;const cinder_vk_copy_region *r=&copies[s];
#ifdef WMMT_VK
  assert(!memcmp(r->source_rect,(int[]){x,G.fb_h,x+1,0},sizeof r->source_rect));
#else
  assert(!memcmp(r->source_rect,(int[]){x,0,x+1,G.fb_h},sizeof r->source_rect));
#endif
#ifdef __ANDROID__
  assert(!memcmp(r->target_rect,(int[]){x,0,x+1,G.fb_h},sizeof r->target_rect));
#else
  assert(!memcmp(r->target_rect,(int[]){s,0,s+1,G.fb_h},sizeof r->target_rect));
#endif
  assert(r->aspects==VK_IMAGE_ASPECT_COLOR_BIT&&r->filter==VK_FILTER_NEAREST);
#ifdef WMMT_NATIVE_VK
  assert(!r->source);
#else
  assert(r->source==91);
#endif
  hashbytes(r->source_rect,sizeof r->source_rect);hashbytes(r->target_rect,sizeof r->target_rect);
 }
 assert(strstr(program_vs,"vShade = aShade")&&strstr(program_fs,"vUV + 2.0 * d")&&strstr(program_fs,"vUV - 2.0 * d")&&strstr(program_fs,"* 0.4")&&strstr(program_fs,"* 0.2")&&strstr(program_fs,"* 0.1")&&strstr(program_fs,"vec4(c * vShade, 1.0)"));
}
static void goldens(void){
 const int sizes[][3]={{1920,1080,128},{2560,1080,360},{2400,1080,290},{1280,720,170},{800,600,50},{8,768,2},{100,768,48}};
 for(unsigned i=0;i<sizeof sizes/sizeof sizes[0];++i){reset();G.fb_w=sizes[i][0];G.fb_h=sizes[i][1];G.edge=(float)sizes[i][2];wide_sides();geometry((int)(G.edge*G.fb_h/768.0f+.5f));assert(!SIDES.off&&alloc_n==1&&compile_n==1);
#ifdef WMMT_NATIVE_VK
  assert(attach_n==1&&!query_n&&!egl_n&&!error_reads&&draw_fb==91&&read_fb==91&&bound_tex==88); /* direct target/storage ownership never mutates a GL binding */
#else
  assert(query_n==1&&error_reads>=2);
#ifdef __ANDROID__
  assert(egl_n==1&&attach_n==1);
#endif
#endif
 }
 printf("CPU_GOLDEN %016llx\n",(unsigned long long)digest);
 puts("PASS seven production two-strip draw/copy goldens, column source-Y and shared five-tap shading/UBO");
}
static void fallbacks(void){
 reset();compile_fail=1;wide_sides();assert(SIDES.off&&!alloc_n&&!copy_n&&!draw_n);wide_sides();assert(compile_n==1);
#ifndef WMMT_NATIVE_VK
#ifdef __ANDROID__
 reset();no_blit=1;wide_sides();assert(SIDES.off&&!compile_n&&!copy_n&&!draw_n&&egl_n==1);
#endif
#endif
 reset();copy_fail_mask=1;wide_sides();assert(!SIDES.off&&image_n==2&&copy_n==4&&draw_n==2);
#ifdef __ANDROID__
 assert(SIDES.fmt==1&&del_fb_n==1&&del_tex_n==1&&alloc_n==2);
#else
 assert(!del_tex_n&&alloc_n==1);
#endif
 unsigned saved_tex=SIDES.tex;copy_fail_mask=0;copy_n=draw_n=0;wide_sides();assert(image_n==2&&SIDES.tex==saved_tex&&draw_n==2&&copy_n==2);
 G.fb_w=2340;G.fb_h=1081;copy_n=draw_n=0;wide_sides();assert(image_n==3&&copy_n==2&&draw_n==2&&SIDES.w==2340&&SIDES.h==1081);
#ifdef __ANDROID__
 assert(SIDES.fmt==1&&del_fb_n==2&&del_tex_n==2&&SIDES.tex!=saved_tex&&alloc_n==3);
#else
 assert(SIDES.tex==saved_tex&&alloc_n==1);
#endif
 reset();copy_fail_mask=UINT64_MAX;wide_sides();assert(SIDES.off&&image_n==2&&copy_n==4&&!draw_n);unsigned saved=copy_n;wide_sides();assert(copy_n==saved&&image_n==2);
 reset();copy_fail_mask=2;wide_sides();assert(!SIDES.off&&copy_n==4&&draw_n==2); /* right column failed */
 reset();copy_fail_mask=5;wide_sides();assert(SIDES.off&&copy_n==4&&!draw_n);
#ifdef WMMT_NATIVE_VK
 reset();program_notready=1;wide_sides();assert(SIDES.off&&!SIDES.prog&&compile_n==1&&destroy_program_n==1&&ready_n==1&&!alloc_n&&!copy_n&&!draw_n);
 reset();wide_sides();assert(compile_n==1&&ready_n==1&&!destroy_program_n);wide_sides();assert(compile_n==1&&ready_n==2);program_notready=1;wide_sides();assert(SIDES.off&&!SIDES.prog&&compile_n==2&&destroy_program_n==2&&ready_n==4);
 for(int fault=0;fault<3;++fault){reset();if(fault==0)storage_fail=1;else if(fault==1)target_create_fail=1;else target_ready_fail=1;wide_sides();assert(SIDES.off&&!SIDES.tex&&!SIDES.fb&&!SIDES.w&&!SIDES.h&&!copy_n&&!draw_n&&storage_calls==2);if(fault==0)assert(!alloc_n&&!image_n&&!target_calls);else assert(alloc_n==2&&image_n==2&&target_calls==2&&del_tex_n==2);if(fault==2)assert(del_fb_n==2);else assert(!del_fb_n);}
#endif
 puts("PASS program/blit absence, left/right copy refusal, RGB/RGBA retry, resize reuse/reallocation, permanent off");
}
static void bounds(void){
 const float edges[]={-100,0,1,10000};for(unsigned i=0;i<sizeof edges/sizeof edges[0];++i){reset();G.edge=edges[i];wide_sides();assert(!copy_n&&!draw_n&&!alloc_n&&!compile_n);}
 reset();G.fb_w=100;G.fb_h=768;G.edge=49;wide_sides();assert(!copy_n&&!draw_n);
#ifdef WMMT_NATIVE_VK
 const float invalid[]={NAN,INFINITY,-INFINITY,FLT_MAX};for(unsigned i=0;i<sizeof invalid/sizeof invalid[0];++i){reset();G.edge=invalid[i];wide_sides();assert(!copy_n&&!draw_n&&!compile_n);}
 const int sizes[][2]={{0,1080},{1920,0},{-1,1080},{1920,-1},{7,768},{INT_MAX,INT_MAX}};
 for(unsigned i=0;i<sizeof sizes/sizeof sizes[0];++i){reset();G.fb_w=sizes[i][0];G.fb_h=sizes[i][1];G.edge=i==5?FLT_MAX:128;wide_sides();assert(!copy_n&&!draw_n&&!compile_n);}
 reset();assert(!sides_native_copy(0,1920,1080,2,1900));assert(!sides_native_copy(1,0,1080,2,3));assert(!sides_native_copy(1,1920,0,2,3));assert(!sides_native_copy(1,1920,1080,-1,3));assert(!sides_native_copy(1,1920,1080,2,1920));assert(!sides_native_copy(1,1920,1080,INT_MAX,3));assert(!copy_n);
 float v[20]={0};assert(!sides_native_draw(0,1,1920,1080,v));assert(!sides_native_draw(7,0,1920,1080,v));assert(!sides_native_draw(7,1,1920,1080,NULL));assert(!sides_native_draw(7,1,1920,0,v));assert(!draw_n);
#endif
 puts("PASS side bounds/rounded edge boundary; native empty/nonfinite/overflow inputs rejected under UBSan");
}
static void epochs(void){
#ifdef WMMT_NATIVE_VK
 reset();sticky_error=0x0500;error_epoch=23;wide_sides();assert(sticky_error==0x0500&&error_epoch==23&&!error_reads&&copy_n==2&&draw_n==2&&alloc_n==1);
 reset();sticky_error=0x0500;error_epoch=23;copy_fail_mask=1;wide_sides();assert(sticky_error==0x0500&&error_epoch==24&&!error_reads&&copy_n==4&&draw_n==2&&!SIDES.off);
 reset();sticky_error=0x0500;error_epoch=23;copy_fail_mask=UINT64_MAX;wide_sides();assert(sticky_error==0x0500&&error_epoch==27&&!error_reads&&SIDES.off&&!draw_n);
 for(int i=0;i<5;++i){reset();switch(i){case 0:init_fail=1;break;case 1:uniform_fail=1;break;case 2:texture_fail=1;break;case 3:sampler_fail=1;break;case 4:submit_fail=1;break;}wide_sides();assert(!draw_n&&copy_n==2&&!SIDES.off);}
 puts("PASS native never drains old sticky errors; command failures alone trigger retry/off; packet failure fails closed");
#else
 reset();sticky_error=0x0500;error_epoch=23;wide_sides();assert(!sticky_error&&error_epoch==23&&error_reads>=3&&draw_n==2);
 puts("PASS legacy sticky-error-drain control intentionally retained (not inherited by native)");
#endif
}
int main(void){goldens();fallbacks();bounds();epochs();return 0;}
'''


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=120, **kw).stdout


with tempfile.TemporaryDirectory(prefix="native-vk-sides-", dir=TMP) as work:
    work = Path(work)
    (work / "EGL").mkdir()
    (work / "EGL/egl.h").write_text("/* No EGL context or dynamic loader in the CPU fixture. */\n")
    common = ["clang", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-variable",
              "-fsanitize=undefined", "-fno-sanitize-recover=all", "-I", str(work),
              "-I", str(ROOT / "test"), "-I", str(ROOT / "src"), "-I", "/opt/homebrew/include"]
    outputs = {}
    modes = {"native": ["-D__ANDROID__", "-DWMMT_VK", "-DWMMT_NATIVE_VK"],
             "vk-compat": ["-D__ANDROID__", "-DWMMT_VK"], "gles": ["-D__ANDROID__"], "ios-control": []}
    for mode, flags in modes.items():
        source = work / (mode + ".c")
        source.write_text(PREFIX + REGION + RECORDER + TESTS)
        binary = work / mode
        try:
            run(common + flags + [str(source), "-lm", "-o", str(binary)])
            outputs[mode] = run([str(binary)])
        except subprocess.CalledProcessError as exc:
            print(exc.stdout, end="")
            raise
        print(mode + ":\n" + outputs[mode], end="")
    native = re.search(r"CPU_GOLDEN (\w+)", outputs["native"])[1]
    compat = re.search(r"CPU_GOLDEN (\w+)", outputs["vk-compat"])[1]
    assert native == compat, (native, compat)
    print("PASS native/VKcompat byte-identical vertices/uDy/copy-endpoint CPU golden digest:", native)
    # Optional exact baseline preservation check for owner handoff, not a fixture
    # dependency: canonical checkouts need no external snapshots to run goldens.
    if os.environ.get("CINDER_SIDES_BASELINE"):
        before = Path(os.environ["CINDER_SIDES_BASELINE"]).read_text()
        base_region = before[before.index(START):before.index(END)]
        for mode in ("gles", "vk-compat", "ios-control"):
            tokens = []
            for label, region in (("before", base_region), ("after", REGION)):
                source = work / (mode + "-" + label + "-tokens.c")
                source.write_text(PREFIX + region)
                text = run(common[:1] + ["-E", "-P"] + modes[mode] +
                           ["-I", str(work), "-I", str(ROOT / "test"), "-I", str(ROOT / "src"),
                            "-I", "/opt/homebrew/include", str(source)])
                tokens.append(re.findall(r'"(?:\\.|[^"\\])*"|\w+|[^\s]', text))
            assert tokens[0] == tokens[1], mode + " control tokens changed"
        assert before[:before.index(START)] == APP[:APP.index(START)]
        assert before[before.index(END):] == APP[APP.index(END):]
        print("PASS GLES/VKcompat/iOS preprocessed tokens and ALL app bytes outside owned region unchanged")
