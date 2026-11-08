#!/usr/bin/env python3
"""Actual whole junction TU -> actual sprite/effect wrappers -> packet oracle.
CPU/NDK authority only; no GPU/display proof. Baseline and external output are explicit.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('CINDER_TEST_OUT',os.environ.get('TMPDIR',tempfile.gettempdir()))).resolve()/'native-junction'
assert ROOT!=OUT and ROOT not in OUT.parents,'external artifacts required'
OUT.mkdir(parents=True,exist_ok=True)
base=os.environ.get('CINDER_JUNCTION_BASELINE')
assert base,'set CINDER_JUNCTION_BASELINE to saved Round9 junction_barrier.c or its tree'
BASE=Path(base).resolve()
if BASE.is_dir():BASE=BASE/('src/junction_barrier.c' if (BASE/'src/junction_barrier.c').exists() else 'junction_barrier.c')
BASE_BYTES=BASE.read_bytes();BASE_TEXT=BASE_BYTES.decode()
NAMES=('src/junction_barrier.c','src/junction_barrier.h','src/anm.c','src/anm.h','src/render.c','src/render.h','src/render_native_effects.inc','src/native_vk.inc','src/native_vk.h','src/native_vk_platform.inc','src/ui_native_vk_resources.inc','src/gl.h','src/vkgl.h','src/mathx.h','src/app.c','tests/test_native_vk_junction_host.py')
INPUTS={n:(ROOT/n).read_bytes() for n in NAMES};H=lambda b:hashlib.sha256(b).hexdigest()
JUNCTION=INPUTS['src/junction_barrier.c'].decode();RENDER=INPUTS['src/render.c'].decode();ANM=INPUTS['src/anm.c'].decode();NATIVE=INPUTS['src/native_vk.inc'].decode()
def fun(text,anchor):
 a=text.index(anchor);b=text.index('{',a);mask=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),text,flags=re.S);depth=0
 for k in range(b,len(text)):
  depth+=(mask[k]=='{')-(mask[k]=='}')
  if not depth:return text[a:k+1]+'\n'
 raise AssertionError(anchor)
old_draw=fun(BASE_TEXT,'int junction_barrier_draw(');new_draw=fun(JUNCTION,'int junction_barrier_draw(')
restored=JUNCTION.replace('#ifdef WMMT_NATIVE_VK\n#include "native_vk.h"\n#endif\n','',1).replace(new_draw,old_draw,1)
assert restored==BASE_TEXT,'only draw + conditional public native header may change'
app=INPUTS['src/app.c'].decode();start=app.index('  if (!movie && !G.vs_closed && !G.menu.finish && c->race.state == CAR_RACE_RUN &&')
caller=app[start:app.index('#endif',start)]
assert 'c->race.jct_select_valid' in caller and 'render_begin(&G.rp)' in caller and 'junction_barrier_draw(' in caller
assert app.rfind('#ifdef __ANDROID__',0,start)>app.rfind('#endif',0,start)
assert 'WMMT_NATIVE_VK' not in caller and app.index('SEG_END(SEG_OPAQUE + pass);')<start<app.index("/* the headlights' pools")
assert 'cinder_vk_platform_frame_ready' not in new_draw and 'cinder_vk_error_epoch' not in new_draw
sprite=fun(RENDER,'static void sprites(');by_colour=fun(RENDER,'void render_sprites_by_colour(')
native_sprite=sprite[sprite.index('#ifdef WMMT_NATIVE_VK'):sprite.index('#else')]
assert '++p->draws' in native_sprite and not re.search(r'p->(?!draws\b)\w+\s*(?:\+\+|--|[+*/-]?=)',native_sprite)
assert 'no_depth_test' not in sprite[sprite.index('#else'):]
metadata=fun(INPUTS['src/native_vk_platform.inc'].decode(),'uint32_t cinder_vk_device_api_version(void)')+fun(NATIVE,'void cinder_vk_screen_extent(')
packet_functions=''.join(fun(NATIVE,a)for a in ('static int native_program_valid(','int cinder_vk_draw_init(','int cinder_vk_uniform(','int cinder_vk_texture(','static int native_span(','static int native_box_valid(','static int native_pipeline_valid('))
texture_functions=''.join(fun(ANM,a)for a in ('static GLuint texture(','unsigned int anm_sprite_texture(','int anm_sprite('))
aliases=re.findall(r'^#define\s+(gl\w+)\s+(vkgl_\w+)\s*$',INPUTS['src/vkgl.h'].decode(),re.M)
assert {a for a,b in aliases}==set(re.findall(r'^#define\s+(gl\w+)\b',INPUTS['src/vkgl.h'].decode(),re.M)) and len(aliases)>50
poison_names=sorted({a for a,b in aliases}|{b for a,b in aliases}|{'ctx','cur_up','cur_vao','main_ctx','loader_ctx','key_state','set_err','shadow','samp_unit','gl_compile_program','cinder_vk_platform_frame_ready','acquire','vkAcquireNextImageKHR'})
poison='#include "vkgl.h"\n#define WMMT_GL_H\n#include "native_vk.h"\n#include "junction_barrier.h"\n#include "anm.h"\n'+''.join('#undef '+a+'\n'for a,b in aliases)+'#pragma GCC poison '+' '.join(poison_names)+'\n'

prefix=r'''
#include <assert.h>
#include <float.h>
#include <limits.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#include "vkgl.h"
#define WMMT_GL_H
#include "native_vk.h"
#include "junction_barrier.h"
#include "anm.h"
static unsigned get_calls,active_calls,equation_calls,depth_calls,attrib_calls,all_gl_calls,upload_calls,submit_calls,record_count;
static int version_available=1,target_valid=1,frame_available=1,submit_allowed=1,program_valid=1;
static int platform_created=1;static struct{VkDevice dev;VkPhysicalDeviceProperties props;}D;
static struct{int w,h;}S={1280,720};
static struct{GLuint*tex;long*offset;uint32_t*zsize,*used,clock;FILE*file,*extra_file,*card_file;uint32_t base_sprites,story_end;float(*size)[2];int*ids;uint16_t(*cols)[2];uint32_t nsprites;float edge;}A;
static int read_all(FILE*f,void*p,size_t n){return fread(p,1,n,f)==n;}
static void time_texture_fix(int id,int w,int h,unsigned char*px){assert(id==0x569&&w==2&&h==2&&px);}
typedef struct{const char*name;int code,off;}vuni;
typedef struct{VkShaderModule vs,fs;int block,n_samp,n_uni;uint32_t inputs;vuni uni[12];}vprog;
static vprog reflection={.vs=(VkShaderModule)(uintptr_t)1,.fs=(VkShaderModule)(uintptr_t)2,.block=144,.n_samp=1,.n_uni=9,.inputs=7,
 .uni={{"uMVP",6,0},{"uEye",3,64},{"uFog",2,76},{"uUVOff",2,84},{"uGrade",3,92},{"uWet",1,104},{"uHorizon",3,108},{"uFogColor",3,120},{"uTex",7,1}}};
static vprog*prog_get(uint32_t id){return program_valid&&id==41?&reflection:NULL;}
typedef struct{uint32_t target;int w,h;}native_scene_view;static native_scene_view native_scene={23,1280,720};
typedef struct{GLuint id;GLint mvp,eye,fog,uv_off,grade;}scene_prog;static scene_prog progs[1]={{41,1,2,3,4,5}};
#ifdef WMMT_NATIVE_VK
static uint32_t white_tex=11;
#else
static int enhance_on;
#endif
static void enhance_grade(const render_params*p,int kind,float*out){(void)p;(void)kind;out[0]=out[1]=out[2]=1;}
typedef struct{uint32_t target,program,texture,count;int viewport[4],scissor[4];uint32_t topology,depth_test,depth_write,depth_compare,blend,src,dst,blend_op,cull,front,color_mask,index_type;uint32_t formats[3],strides[3],offsets[3];float mvp[16],eye[3],fog[2],uv[2],grade[3];render_vertex v[8];uint16_t idx[12];}effective_packet;
static effective_packet captured;static FILE*golden;static int expected_depth=1;
static struct{GLenum active,equation,src,dst,depth_compare,front;int depth_test,depth_write,blend,cull;GLuint program,texture,buffer,element,framebuffer;int viewport[4],scissor[4];float mvp[16],eye[3],fog[2],uv[2],grade[3];struct{int enabled,size;GLenum type;GLboolean normalized;GLsizei stride;const void*pointer;}attr[3];}g;
static void seed(void){get_calls=active_calls=equation_calls=depth_calls=attrib_calls=all_gl_calls=upload_calls=submit_calls=record_count=0;memset(&captured,0,sizeof captured);memset(&g,0,sizeof g);g.active=GL_TEXTURE0+5;g.equation=GL_FUNC_SUBTRACT;g.depth_compare=GL_LEQUAL;g.front=GL_CCW;g.depth_write=1;g.cull=1;g.buffer=91;g.element=92;g.framebuffer=23;g.viewport[2]=g.scissor[2]=1280;g.viewport[3]=g.scissor[3]=720;}
const GLubyte*glGetString(GLenum name){++get_calls;++all_gl_calls;assert(name==GL_VERSION);return version_available?(const GLubyte*)"mock":NULL;}
void glActiveTexture(GLenum v){++all_gl_calls;++active_calls;g.active=v;}
void glBlendEquation(GLenum v){++all_gl_calls;++equation_calls;g.equation=v;}
void glEnable(GLenum v){++all_gl_calls;if(v==GL_DEPTH_TEST)++depth_calls,g.depth_test=1;else if(v==GL_BLEND)g.blend=1;else if(v==GL_CULL_FACE)g.cull=1;else assert(0);}
void glDisable(GLenum v){++all_gl_calls;assert(v==GL_CULL_FACE);g.cull=0;}
void glEnableVertexAttribArray(GLuint i){++all_gl_calls;++attrib_calls;assert(i<3);g.attr[i].enabled=1;}
void glUseProgram(GLuint id){++all_gl_calls;g.program=id;}
void glUniformMatrix4fv(GLint location,GLsizei count,GLboolean transpose,const GLfloat*v){++all_gl_calls;assert(location==1&&count==1&&!transpose);memcpy(g.mvp,v,sizeof g.mvp);}
void glUniform3f(GLint location,GLfloat a,GLfloat b,GLfloat c){++all_gl_calls;float*v=location==2?g.eye:g.grade;assert(location==2||location==5);v[0]=a;v[1]=b;v[2]=c;}
void glUniform3fv(GLint location,GLsizei n,const GLfloat*v){++all_gl_calls;assert(location==5&&n==1);memcpy(g.grade,v,sizeof g.grade);}
void glUniform2f(GLint location,GLfloat a,GLfloat b){++all_gl_calls;float*v=location==3?g.fog:g.uv;assert(location==3||location==4);v[0]=a;v[1]=b;}
void glBlendFunc(GLenum src,GLenum dst){++all_gl_calls;g.src=src;g.dst=dst;}
void glDepthMask(GLboolean on){++all_gl_calls;g.depth_write=on;}
void glBindTexture(GLenum target,GLuint tex){++all_gl_calls;assert(target==GL_TEXTURE_2D&&g.active==GL_TEXTURE0);g.texture=tex;}
void glBindBuffer(GLenum target,GLuint buffer){++all_gl_calls;if(target==GL_ARRAY_BUFFER)g.buffer=buffer;else{assert(target==GL_ELEMENT_ARRAY_BUFFER);g.element=buffer;}}
void glVertexAttribPointer(GLuint a,GLint n,GLenum type,GLboolean norm,GLsizei stride,const void*p){++all_gl_calls;assert(a<3&&!g.buffer);g.attr[a].size=n;g.attr[a].type=type;g.attr[a].normalized=norm;g.attr[a].stride=stride;g.attr[a].pointer=p;}
void glGenTextures(GLsizei n,GLuint*out){++all_gl_calls;assert(n==1);*out=37;}
void glTexParameteri(GLenum target,GLenum name,GLint value){++all_gl_calls;assert(target==GL_TEXTURE_2D);assert(((name==GL_TEXTURE_MIN_FILTER||name==GL_TEXTURE_MAG_FILTER)&&value==GL_LINEAR)||((name==GL_TEXTURE_WRAP_S||name==GL_TEXTURE_WRAP_T)&&value==GL_CLAMP_TO_EDGE));}
void glTexImage2D(GLenum target,GLint level,GLint internal,GLsizei w,GLsizei h,GLint border,GLenum format,GLenum type,const void*p){++all_gl_calls;assert(target==GL_TEXTURE_2D&&!level&&internal==GL_RGBA&&w==2&&h==2&&!border&&format==GL_RGBA&&type==GL_UNSIGNED_BYTE&&p);++upload_calls;}
void glDrawElements(GLenum mode,GLsizei count,GLenum type,const void*indices){++all_gl_calls;assert(mode==GL_TRIANGLES&&count==12&&type==GL_UNSIGNED_SHORT&&!g.buffer&&!g.element&&g.texture==37&&g.program==41);effective_packet*d=&captured;memset(d,0,sizeof*d);d->target=g.framebuffer;d->program=g.program;d->texture=g.texture;d->count=(uint32_t)count;memcpy(d->viewport,g.viewport,sizeof d->viewport);memcpy(d->scissor,g.scissor,sizeof d->scissor);d->topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;d->depth_test=g.depth_test;d->depth_write=g.depth_write;assert(g.depth_compare==GL_LEQUAL&&g.equation==GL_FUNC_ADD&&g.src==GL_SRC_COLOR&&g.dst==GL_ONE&&g.front==GL_CCW);d->depth_compare=VK_COMPARE_OP_LESS_OR_EQUAL;d->blend=g.blend;d->src=VK_BLEND_FACTOR_SRC_COLOR;d->dst=VK_BLEND_FACTOR_ONE;d->blend_op=VK_BLEND_OP_ADD;d->cull=g.cull?VK_CULL_MODE_BACK_BIT:VK_CULL_MODE_NONE;d->front=VK_FRONT_FACE_COUNTER_CLOCKWISE;d->color_mask=15;d->index_type=VK_INDEX_TYPE_UINT16;for(unsigned i=0;i<3;++i){assert(g.attr[i].enabled&&g.attr[i].stride==sizeof(render_vertex));d->formats[i]=i==0?VK_FORMAT_R32G32B32_SFLOAT:i==1?VK_FORMAT_R32G32_SFLOAT:VK_FORMAT_R8G8B8A8_UNORM;d->strides[i]=sizeof(render_vertex);d->offsets[i]=i==0?0:i==1?12:20;assert(g.attr[i].size==(i==0?3:i==1?2:4)&&g.attr[i].type==(i==2?GL_UNSIGNED_BYTE:GL_FLOAT)&&g.attr[i].normalized==(i==2?GL_TRUE:GL_FALSE));}assert((const unsigned char*)g.attr[1].pointer==(const unsigned char*)g.attr[0].pointer+12&&(const unsigned char*)g.attr[2].pointer==(const unsigned char*)g.attr[0].pointer+20);memcpy(d->v,g.attr[0].pointer,sizeof d->v);memcpy(d->idx,indices,sizeof d->idx);memcpy(d->mvp,g.mvp,sizeof d->mvp);memcpy(d->eye,g.eye,sizeof d->eye);memcpy(d->fog,g.fog,sizeof d->fog);memcpy(d->uv,g.uv,sizeof d->uv);memcpy(d->grade,g.grade,sizeof d->grade);++record_count;}
uint32_t cinder_vk_texture_rgba8(int w,int h,const void*p,size_t bytes,const cinder_vk_sampler*s){assert(w==2&&h==2&&bytes==16&&p&&s&&s->use_state&&!s->mipmaps&&s->min_filter==VK_FILTER_LINEAR&&s->mag_filter==VK_FILTER_LINEAR&&s->mipmap_mode==VK_SAMPLER_MIPMAP_MODE_NEAREST&&s->address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->address_v==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->anisotropy==1);++upload_calls;return 37;}
int cinder_vk_texture_sampler(uint32_t texture,cinder_vk_sampler*s){(void)texture;(void)s;assert(0&&"junction must not mutate/override immutable ANM sampler");return 0;}
int cinder_vk_sampler_state(cinder_vk_draw*d,const char*n,const cinder_vk_sampler*s){(void)d;(void)n;(void)s;assert(0&&"tire-only sampler path unreachable");return 0;}
'''

oracle=r'''
int cinder_vk_submit(const cinder_vk_draw*d){++submit_calls;assert(d&&native_pipeline_valid(&d->pipeline)&&native_box_valid(d->viewport)&&native_box_valid(d->scissor));if(!target_valid||!frame_available||!submit_allowed)return 0;assert((d->target==23||d->target==0)&&d->program==41&&d->count==12&&d->indexed&&!d->first&&!d->warm_only&&!d->index_buffer&&d->index_type==VK_INDEX_TYPE_UINT16&&!d->index_offset&&d->index_bytes==24&&d->indices);effective_packet*p=&captured;memset(p,0,sizeof*p);p->target=d->target;p->program=d->program;p->texture=d->textures[0];p->count=d->count;assert(p->texture==37&&!d->samplers[0].use_state);memcpy(p->viewport,d->viewport,sizeof p->viewport);memcpy(p->scissor,d->scissor,sizeof p->scissor);p->topology=d->pipeline.topology;p->depth_test=d->pipeline.depth_test;p->depth_write=d->pipeline.depth_write;p->depth_compare=d->pipeline.depth_compare;p->blend=d->pipeline.blend;p->src=d->pipeline.src_blend;p->dst=d->pipeline.dst_blend;p->blend_op=d->pipeline.blend_op;p->cull=d->pipeline.cull;p->front=d->pipeline.asset_front;p->color_mask=d->pipeline.color_mask;p->index_type=d->index_type;assert(!d->pipeline.stencil&&d->pipeline.stencil_compare==VK_COMPARE_OP_ALWAYS&&d->pipeline.stencil_fail==VK_STENCIL_OP_KEEP&&d->pipeline.depth_fail==VK_STENCIL_OP_KEEP&&d->pipeline.depth_pass==VK_STENCIL_OP_KEEP&&d->pipeline.stencil_compare_mask==255&&d->pipeline.stencil_write_mask==255);for(unsigned i=0;i<3;++i){const cinder_vk_attribute*a=&d->attributes[i];assert(!a->buffer&&a->data&&a->bytes==sizeof p->v&&a->stride==sizeof(render_vertex)&&a->offset==(i==0?0:i==1?12:20)&&native_span(a->bytes,a->offset,8,a->stride,i==0?12:i==1?8:4));p->formats[i]=a->format;p->strides[i]=a->stride;p->offsets[i]=a->offset;assert(a->data==d->attributes[0].data);}for(unsigned i=3;i<CINDER_VK_ATTRIBUTES;++i)assert(!d->attributes[i].format&&!d->attributes[i].buffer&&!d->attributes[i].data&&d->attributes[i].value[3]==1);memcpy(p->v,d->attributes[0].data,sizeof p->v);memcpy(p->idx,d->indices,sizeof p->idx);memcpy(p->mvp,d->uniforms,sizeof p->mvp);memcpy(p->eye,d->uniforms+64,sizeof p->eye);memcpy(p->fog,d->uniforms+76,sizeof p->fog);memcpy(p->uv,d->uniforms+84,sizeof p->uv);memcpy(p->grade,d->uniforms+92,sizeof p->grade);++record_count;return 1;}
'''

cases=r'''
static GLuint textures[3];static long offsets[3];static uint32_t zsizes[3],used[3];static float sizes[3][2];static int ids[3];static uint16_t cols[3][2];
static void setup(void){memset(&A,0,sizeof A);memset(textures,0,sizeof textures);memset(offsets,0,sizeof offsets);memset(zsizes,0,sizeof zsizes);memset(used,0,sizeof used);memset(cols,0,sizeof cols);A.tex=textures;A.offset=offsets;A.zsize=zsizes;A.used=used;A.size=sizes;A.ids=ids;A.cols=cols;A.nsprites=A.base_sprites=3;A.clock=53;ids[0]=12;ids[1]=0x569;ids[2]=90;sizes[1][0]=sizes[1][1]=2;textures[1]=37;D.dev=(VkDevice)(uintptr_t)1;D.props.apiVersion=VK_API_VERSION_1_0;platform_created=1;version_available=target_valid=frame_available=submit_allowed=program_valid=1;native_scene=(native_scene_view){23,1280,720};S.w=1280;S.h=720;seed();}
static junction_barrier barrier(int state,int tie){junction_barrier b={0};junction_barrier_point a={{0,2,10}},m={{4,3,20}},z={{14,4,50}};if(tie){a=(junction_barrier_point){{-8,0,0}};m=(junction_barrier_point){{0,0,0}};z=(junction_barrier_point){{8,0,0}};}assert(junction_barrier_tick(&b,1,7,9,&a,&z,&m,123));if(state!=1)assert(junction_barrier_tick(&b,state,700,900,NULL,NULL,NULL,321));assert(b.left.kind==7&&b.right.kind==9);return b;}
static render_params params(int no_depth){render_params p={0};p.no_depth_test=no_depth;p.draws=5;p.triangles=17;p.new_chunks=3;p.time=2.5f;p.wet=0.7f;p.fog_far=1234;p.fog_near=50;p.grade[0]=1.2f;p.grade[1]=1.3f;p.grade[2]=1.4f;return p;}
static mat4 matrix(void){mat4 m=mat4_identity();m.m[0]=0.5f;m.m[5]=0.75f;m.m[12]=0.125f;return m;}
static void check(const junction_barrier*b,const mat4*m,const float eye[3],float scale,int first_right,int no_depth){junction_barrier old=*b;mat4 old_m=*m;float old_eye[3];memcpy(old_eye,eye,sizeof old_eye);render_params p=params(no_depth),old_p=p;typeof(g)old_g=g;unsigned clock=A.clock;assert(junction_barrier_draw(b,m,eye,scale,&p)==2&&record_count==1&&p.draws==6);p.draws=old_p.draws;assert(!memcmp(&p,&old_p,sizeof p)&&!memcmp(b,&old,sizeof old)&&!memcmp(m,&old_m,sizeof old_m)&&!memcmp(eye,old_eye,sizeof old_eye)&&A.clock==clock&&used[1]==clock);p.draws=6;expected_depth=1;
#ifdef WMMT_NATIVE_VK
#ifdef CINDER_OLD_NATIVE
 (void)old_g;assert(get_calls==1&&active_calls==1&&equation_calls==1&&depth_calls==1&&attrib_calls==3&&all_gl_calls==7);expected_depth=!no_depth;
#else
 assert(!all_gl_calls&&!memcmp(&g,&old_g,sizeof g));
#endif
#else
 (void)old_g;assert(get_calls==2&&active_calls==1&&equation_calls==1&&depth_calls==1&&attrib_calls==3&&g.cull&&g.blend&&!g.depth_write);
#endif
 assert(captured.depth_test==(uint32_t)expected_depth&&!captured.depth_write&&captured.depth_compare==VK_COMPARE_OP_LESS_OR_EQUAL&&captured.blend&&captured.src==VK_BLEND_FACTOR_SRC_COLOR&&captured.dst==VK_BLEND_FACTOR_ONE&&captured.blend_op==VK_BLEND_OP_ADD&&!captured.cull&&captured.front==VK_FRONT_FACE_COUNTER_CLOCKWISE&&captured.color_mask==15);assert(!memcmp(captured.mvp,m->m,sizeof m->m));static const uint16_t idx[]={0,1,2,0,2,3,4,5,6,4,6,7};assert(!memcmp(captured.idx,idx,sizeof idx));const junction_barrier_side*sides[2]={first_right?&b->right:&b->left,first_right?&b->left:&b->right};for(int q=0;q<2;++q){const junction_barrier_side*s=sides[q];const render_vertex*v=captured.v+4*q;float u=(s==&b->right?0.5f:0)+(s->display_state==3?0.25f:0);assert(v[0].pos[0]==s->start.v[0]&&v[0].pos[1]==s->start.v[1]+85.0f*scale&&v[0].pos[2]==s->start.v[2]&&v[1].pos[0]==s->end.v[0]&&v[1].pos[1]==s->end.v[1]+85.0f*scale&&v[2].pos[1]==s->end.v[1]&&v[3].pos[1]==s->start.v[1]);assert(v[0].uv[0]==u&&v[1].uv[0]==u+0.25f&&v[2].uv[0]==u+0.25f&&v[3].uv[0]==u&&v[0].uv[1]==1&&v[1].uv[1]==1&&!v[2].uv[1]&&!v[3].uv[1]);for(int i=0;i<4;++i)for(int c=0;c<4;++c)assert(v[i].rgba[c]==255);}assert(fwrite(&captured,sizeof captured,1,golden)==1);}
static void bad_inputs(void){for(int k=0;k<16;++k){setup();junction_barrier b=barrier(1,0),old=b;mat4 m=matrix(),old_m=m;float eye[3]={0};render_params p=params(1),old_p=p;float scale=1;const junction_barrier*bp=&b;const mat4*mp=&m;const float*ep=eye;render_params*pp=&p;switch(k){case 0:bp=NULL;break;case 1:b.ready=0;old=b;break;case 2:mp=NULL;break;case 3:ep=NULL;break;case 4:pp=NULL;break;case 5:scale=NAN;break;case 6:scale=INFINITY;break;case 7:scale=0;break;case 8:scale=-1;break;case 9:scale=FLT_MAX;break;case 10:m.m[8]=NAN;old_m=m;break;case 11:eye[1]=INFINITY;break;case 12:b.left.end.v[0]=b.left.start.v[0];b.left.end.v[2]=b.left.start.v[2];old=b;break;case 13:b.right.start.v[0]=INFINITY;old=b;break;case 14:b.left.start.v[1]=FLT_MAX;old=b;break;case 15:scale=FLT_MIN;break;}assert(!junction_barrier_draw(bp,mp,ep,scale,pp)&&!record_count&&!all_gl_calls&&!submit_calls&&!upload_calls&&!used[1]&&!memcmp(&b,&old,sizeof b)&&!memcmp(&m,&old_m,sizeof m)&&!memcmp(&p,&old_p,sizeof p));}puts("PASS actual whole junction invalid arguments/geometry/height overflow/precision: no draw/resource/params/tick mutation");}
static void missing(void){for(int k=0;k<3;++k){setup();junction_barrier b=barrier(1,0);mat4 m=matrix();float eye[3]={0};render_params p=params(1),old=p;if(k==0)version_available=0,platform_created=0;else if(k==1)ids[1]=0;else textures[1]=0;assert(!junction_barrier_draw(&b,&m,eye,1,&p)&&!record_count&&!submit_calls&&!memcmp(&p,&old,sizeof p));
#if defined(WMMT_NATIVE_VK)&&!defined(CINDER_OLD_NATIVE)
assert(!all_gl_calls);
#endif
}puts("PASS unavailable/no-sprite/no-texture early exits do not fabricate a draw");}
static void backend_failures(void){
#if defined(WMMT_NATIVE_VK)&&!defined(CINDER_OLD_NATIVE)
 for(int k=0;k<7;++k){setup();junction_barrier b=barrier(1,0);mat4 m=matrix();float eye[3]={0};render_params p=params(1),old=p;if(k==0)D.dev=VK_NULL_HANDLE;else if(k==1)platform_created=0;else if(k==2)program_valid=0;else if(k==3)target_valid=0;else if(k==4)frame_available=0;else if(k==5)submit_allowed=0;else native_scene.w=0,native_scene.h=0,S.w=0,S.h=0;int result=junction_barrier_draw(&b,&m,eye,1,&p);assert(result==((k<2)?0:2)&&!record_count&&!all_gl_calls&&!memcmp(&p,&old,sizeof p));}puts("PASS actual pure device metadata is not a frame claim: unavailable rejects early; actual wrapper/program/extent and recording target/F failures record nothing, no acquire/GL, draws unchanged");
#endif
}
int main(int argc,char**argv){assert(argc==2);golden=fopen(argv[1],"wb");assert(golden);for(int state=1;state<=3;++state)for(int far_eye=0;far_eye<2;++far_eye)for(int small=0;small<2;++small)for(int nd=0;nd<2;++nd){setup();junction_barrier b=barrier(state,0);mat4 m=matrix();float eye[3]={0};if(far_eye)eye[0]=20,eye[2]=100;check(&b,&m,eye,small?0.25f:1.0f,!far_eye,nd);}for(int nd=0;nd<2;++nd){setup();junction_barrier b=barrier(1,1);mat4 m=matrix();float eye[3]={0};check(&b,&m,eye,1,0,nd);}for(int nd=0;nd<2;++nd){setup();native_scene=(native_scene_view){0,0,0};g.framebuffer=0;junction_barrier b=barrier(1,0);mat4 m=matrix();float eye[3]={0};check(&b,&m,eye,1,1,nd);assert(captured.target==0);}puts("PASS actual CPU spans: 28 draw2 cases, explicit/screen-fallback targets, both far-first orders and stable tie, all state UV bands, height85*nToWorld, white RGBA, exact VP/indices, input immutability");bad_inputs();missing();backend_failures();setup();textures[1]=0;unsigned char pixels[16];for(unsigned i=0;i<sizeof pixels;++i)pixels[i]=(unsigned char)(17*i);A.file=tmpfile();assert(A.file&&fwrite(pixels,sizeof pixels,1,A.file)==1);junction_barrier b=barrier(2,0);mat4 m=matrix();float eye[3]={0};render_params p=params(1);assert(junction_barrier_draw(&b,&m,eye,1,&p)==2&&upload_calls==1&&record_count==1&&textures[1]==37&&A.clock==53&&used[1]==53);fclose(A.file);assert(fclose(golden)==0);
#ifdef CINDER_OLD_NATIVE
puts("CONTROLLED RED old actual whole Native junction + actual Native sprite wrapper: 7 GL shim calls; incoming no_depth_test1 produces depth OFF despite legacy depth-enable intent");
#else
puts("PASS actual ANM native immutable or legacy unit0 texture path and sprite wrapper effective blend/depth/cull/attribute packet");
#endif
return 0;}
'''

ndk=Path(os.environ.get('CINDER_NDK_BIN','/Users/arx/Library/Android/sdk/ndk/28.0.13004108/toolchains/llvm/prebuilt/darwin-x86_64/bin')).resolve();ndkinc=ndk.parent/'sysroot/usr/include'
rows=[]
def run(args,label,input=None,expect=0):
 p=subprocess.run([str(a)for a in args],input=input,capture_output=True)
 (OUT/(label+'.log')).write_bytes(p.stdout+p.stderr)
 if p.returncode!=expect and expect==0:print((p.stdout+p.stderr).decode(errors='replace'),flush=True)
 assert (p.returncode==0 if expect==0 else p.returncode!=0),(label,p.returncode)
 return p
with tempfile.TemporaryDirectory(prefix='junction-',dir=OUT)as temp:
 work=Path(temp);inc=work/'include';inc.mkdir()
 for name in ('GLES2','EGL','KHR','vulkan','vk_video'):shutil.copytree(ndkinc/name,inc/name)
 pheader=OUT/'poison.h';pheader.write_text(poison)
 common=[os.environ.get('CC','clang'),'-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter','-Wno-missing-field-initializers','-fsanitize=undefined','-fno-sanitize-recover=all','-I'+str(inc),'-I'+str(ROOT/'src')]
 for label,defines,source in [('legacy',['-DWMMT_VK'],BASE_TEXT),('old-native',['-DWMMT_VK','-DWMMT_NATIVE_VK','-DCINDER_OLD_NATIVE'],BASE_TEXT),('native',['-DWMMT_VK','-DWMMT_NATIVE_VK'],JUNCTION),('native-closure-poison',['-DWMMT_VK','-DWMMT_NATIVE_VK'],JUNCTION)]:
  c=OUT/(label+'-actual.c');c.write_text(prefix+'\n'+(poison if label=='native-closure-poison' else '')+'\n'+metadata+'\n'+packet_functions+'\n'+oracle+'\n'+INPUTS['src/ui_native_vk_resources.inc'].decode()+'\n'+texture_functions+'\n'+INPUTS['src/render_native_effects.inc'].decode()+'\n'+sprite+by_colour+'\n'+source+'\n'+cases);exe=OUT/(label+'-actual');run([*common,*defines,c,'-lm','-lz','-o',exe],label+'-compile');p=run([exe,OUT/(label+'-packets.bin')],label+'-run');print(p.stdout.decode(),end='');rows.append({'actual_host':label,'exit_code':0,'packet_sha256':H((OUT/(label+'-packets.bin')).read_bytes())})
 assert (OUT/'legacy-packets.bin').read_bytes()==(OUT/'native-packets.bin').read_bytes()==(OUT/'native-closure-poison-packets.bin').read_bytes(),'native effective packets differ from actual Legacy sprite wrapper or poisoned actual closure'
 assert (OUT/'old-native-packets.bin').read_bytes()!=(OUT/'legacy-packets.bin').read_bytes(),'expected real oldNative noDepth1 mismatch disappeared'
 old=run([*common,'-DWMMT_VK','-DWMMT_NATIVE_VK','-include',pheader,'-fsyntax-only','-x','c','-'],'baseline-native-poison',BASE_BYTES,expect=1);assert b'poisoned' in old.stderr
 run([*common,'-DWMMT_VK','-DWMMT_NATIVE_VK','-include',pheader,'-fsyntax-only','-x','c','-'],'native-whole-poison',INPUTS['src/junction_barrier.c'])
 cc=ndk/'aarch64-linux-android28-clang';nm=ndk/'llvm-nm';flags=['-std=gnu11','-O2','-fPIC','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-parameter','-Wno-missing-field-initializers','-I'+str(ROOT/'src')]
 modes=[('gles',['-DWMMT_EGL']),('compat',['-DWMMT_EGL','-DWMMT_VK']),('compat-no-egl',['-DWMMT_VK']),('native',['-DWMMT_EGL','-DWMMT_VK','-DWMMT_NATIVE_VK']),('native-no-egl',['-DWMMT_VK','-DWMMT_NATIVE_VK'])]
 for label,defines in modes:
  current=OUT/(label+'.o');run([cc,*flags,*defines,'-x','c','-','-c','-o',current],label+'-ndk',INPUTS['src/junction_barrier.c']);row={'mode':label,'full_ndk_O2_compile':True,'object_sha256':H(current.read_bytes())}
  if 'native' not in label:
   before=OUT/(label+'-baseline.o');run([cc,*flags,*defines,'-x','c','-','-c','-o',before],label+'-baseline-ndk',BASE_BYTES);assert before.read_bytes()==current.read_bytes(),label;tokens=[]
   for text in (BASE_BYTES,INPUTS['src/junction_barrier.c']):tokens.append(re.findall(rb'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\w+|[^\s]',run([cc,*flags,*defines,'-E','-P','-x','c','-'],label+'-cpp',text).stdout))
   assert tokens[0]==tokens[1],label;row['whole_legacy_tokens_equal']=row['whole_legacy_O2_object_equal']=True
  else:
   imports=run([nm,'--undefined-only',current],label+'-imports').stdout.decode();assert not re.search(r'\b_?(?:gl[A-Z]\w*|vkgl_\w*|egl\w*)\b',imports),imports;assert 'cinder_vk_device_api_version' in imports and 'cinder_vk_platform_frame_ready' not in imports;po=OUT/(label+'-poison.o');run([cc,*flags,*defines,'-include',pheader,'-x','c','-','-c','-o',po],label+'-poison-ndk',INPUTS['src/junction_barrier.c']);assert current.read_bytes()==po.read_bytes(),label;row['zero_GL_vkgl_EGL_imports']=row['raw_actual_alias_context_poison_object_equal']=True
  rows.append(row)
for n,data in INPUTS.items():assert (ROOT/n).read_bytes()==data,'source changed during proof: '+n
result={'status':'pass','source_sha256':{n:H(b)for n,b in INPUTS.items()},'baseline':{'path':str(BASE),'sha256':H(BASE_BYTES)},'scope_only_draw_and_conditional_native_include':True,'actual_caller_android_race_branch_reachable':True,'actual_production_functions_sha256':{'junction_barrier_draw':H(new_draw.encode()),'sprites':H(sprite.encode()),'render_sprites_by_colour':H(by_colour.encode()),'cinder_vk_device_api_version':H(fun(INPUTS['src/native_vk_platform.inc'].decode(),'uint32_t cinder_vk_device_api_version(void)').encode()),'cinder_vk_screen_extent':H(fun(NATIVE,'void cinder_vk_screen_extent(').encode())},'results':rows,'effective_native_vs_actual_legacy_packet_bytes_equal':True,'old_native_shim_and_no_depth_mismatch_controlled_red':True,'poisoned_identifiers':poison_names,'mocked_boundaries':['GL effects captured at actual API arguments','shader/ANM resource metadata and low-level upload handle publication','typed submit target/F/record validity and byte capture, not actual GPU execution'],'device_getter_is_not_frame_claim_or_GPU_completion':True,'no_acquire_in_junction':True,'hardware_GPU_display_verified':False}
(OUT/'results.json').write_text(json.dumps(result,indent=2)+'\n');print('PASS actual junction CPU/RHI/ANM chains, controlled old RED, 28 Legacy-equal packets, strict UBSan, all five NDK modes/3legacy whole controls/Native imports+poison:',OUT/'results.json')
