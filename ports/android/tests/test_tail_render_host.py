#!/usr/bin/env python3
"""Extract production renderer and run GLES/Vulkan state mocks; no APK/GPU."""
from pathlib import Path
import subprocess, tempfile, sys, os, ast, re
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
s=(root/'src/render.c').read_text()
# Compare real shader bytes, not the C mock's placeholder strings. The generated
# SPIR-V table is private and is not built by this host test.
def literals(part):
 part=re.sub(r'/\*.*?\*/','',part,flags=re.S)
 return ''.join(ast.literal_eval(q) for q in re.findall(r'"(?:\\.|[^"\\])*"',part))
vs=literals(s.split('static const char *VS =',1)[1].split('#define FS_HEAD',1)[0])
head=literals(s.split('#define FS_HEAD',1)[1].split('#define FS_TAIL',1)[0])
tail=literals(s.split('#define FS_TAIL',1)[1].split('static const char *FS =',1)[0])
assert (root/'tools/vkprogs/78b0a0b2b3c119c2.txt').read_text() == '// attribs: aPos aUV aColor\n//----VS\n'+vs+'\n//----FS\n'+head+tail
assert 'prog_init(&tail_render.program, FS)' in s
def extract(anchor):
 a=s.index(anchor);b=s.index('{',a);depth=0
 for i in range(b,len(s)):
  if s[i]=='{':depth+=1
  elif s[i]=='}':
   depth-=1
   if not depth:return s[a:i+1]
 raise ValueError(anchor)
a=s.index('/* ---- isolated, float-colour tail trail drawing ---- */');b=s.index('#include "render_tire_smoke.inc"',a)
constants='GL_FALSE GL_TRUE GL_ARRAY_BUFFER GL_ELEMENT_ARRAY_BUFFER GL_CURRENT_PROGRAM GL_ARRAY_BUFFER_BINDING GL_VERTEX_ARRAY_BINDING_OES GL_ACTIVE_TEXTURE GL_TEXTURE_BINDING_2D GL_BLEND_SRC_RGB GL_BLEND_DST_RGB GL_BLEND_SRC_ALPHA GL_BLEND_DST_ALPHA GL_BLEND_EQUATION_RGB GL_BLEND_EQUATION_ALPHA GL_DEPTH_FUNC GL_BLEND GL_DEPTH_TEST GL_CULL_FACE GL_STENCIL_TEST GL_DEPTH_WRITEMASK GL_COLOR_WRITEMASK GL_TEXTURE_2D GL_LEQUAL GL_FUNC_ADD GL_SRC_ALPHA GL_ONE GL_FLOAT GL_STREAM_DRAW GL_TRIANGLES'.split()
prefix=r"""
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "render.h"
typedef unsigned GLuint,GLenum;typedef int GLint,GLsizei;typedef unsigned char GLboolean;typedef float GLfloat;typedef ptrdiff_t GLsizeiptr;
#define GL_TEXTURE0 100
#define FRAME_UNIT 6
"""+''.join('#define %s %d\n'%(n,i) for i,n in enumerate(constants))+r"""
typedef struct {GLuint id;GLint mvp,eye,fog,fog_color,tex,uv_off,grade,wet,horizon;} scene_prog;
static scene_prog progs[2]={{.id=1}};static GLuint white_tex=7;static const char *VS="VS",*FS="FS";
typedef struct {int on,size,type,norm,stride;GLuint buffer;uintptr_t ptr;} Attr;
typedef struct {Attr a[4];GLuint ebo;} Vao;
typedef struct {GLuint prog,array,vao,tex[8];int active;GLenum sr,dr,sa,da,er,ea,df;GLboolean blend,depth,cull,stencil,dw,colour[4];int vp[4],sc[4],sc_on,front;float generic[4][4];int err;} State;
typedef struct {float mvp[16],eye[3],fog[2],fc[3],grade[3],uv[2];int sampler;} Uni;
static State state;static Vao vaos[16];static Uni uni[16];
static int calls,compiles,draws,deletes,fail_compile,fail_vao,fail_vbo,unusable,fail_scope,draw_error,history_n;
static uint64_t epoch;static float upload[5000],history[2][5000];static size_t bytes;
static TailTrailVertex verts[2*TAIL_TRAIL_MAX_VERTICES];static size_t expected_n=6;static mat4 vp;static render_params rp;
static GLboolean *cap(GLenum e){switch(e){case GL_BLEND:return &state.blend;case GL_DEPTH_TEST:return &state.depth;case GL_CULL_FACE:return &state.cull;case GL_STENCIL_TEST:return &state.stencil;default:abort();}}
static GLuint gl_compile_program(const char *v,const char *f,const char **attrs,int n){++calls;++compiles;assert(v==VS&&f==FS&&n==3&&!strcmp(attrs[0],"aPos")&&!strcmp(attrs[1],"aUV")&&!strcmp(attrs[2],"aColor"));return fail_compile?0:2;}
static GLint glGetUniformLocation(GLuint p,const char *name){++calls;assert(p==2);const char *names[]={"uMVP","uEye","uFog","uFogColor","uTex","uUVOff","uGrade"};for(int i=0;i<7;++i)if(!strcmp(names[i],name))return i;return -1;}
static void glUseProgram(GLuint p){++calls;state.prog=p;}
static void glUniform1i(GLint l,GLint a){++calls;if(l>=0){assert(l==4);uni[state.prog].sampler=a;}}
static void glUniform1f(GLint l,GLfloat a){++calls;(void)l;(void)a;}
static void glUniform2f(GLint l,GLfloat a,GLfloat b){++calls;float *v=l==2?uni[state.prog].fog:uni[state.prog].uv;assert(l==2||l==5);v[0]=a;v[1]=b;}
static void glUniform3f(GLint l,GLfloat a,GLfloat b,GLfloat c){++calls;float *v=l==1?uni[state.prog].eye:l==3?uni[state.prog].fc:uni[state.prog].grade;assert(l==1||l==3||l==6);v[0]=a;v[1]=b;v[2]=c;}
static void glUniformMatrix4fv(GLint l,GLsizei n,GLboolean t,const GLfloat *v){++calls;assert(l==0&&n==1&&t==GL_FALSE);memcpy(uni[state.prog].mvp,v,64);}
static void glGenVertexArraysOES(GLsizei n,GLuint *out){++calls;assert(n==1);*out=fail_vao?0:10;if(*out)memset(&vaos[*out],0,sizeof vaos[*out]);}
static void glGenBuffers(GLsizei n,GLuint *out){++calls;assert(n==1);*out=fail_vbo?0:11;}
static void glDeleteVertexArraysOES(GLsizei n,const GLuint *p){++calls;++deletes;assert(n==1&&*p==10);memset(&vaos[*p],0,sizeof vaos[*p]);if(state.vao==*p)state.vao=0;}
static void glDeleteBuffers(GLsizei n,const GLuint *p){++calls;++deletes;assert(n==1&&*p==11);if(state.array==*p)state.array=0;}
static void glDeleteProgram(GLuint p){++calls;++deletes;assert(p==2);if(state.prog==p)state.prog=0;}
static void glBindVertexArrayOES(GLuint v){++calls;state.vao=v;}
static void glBindBuffer(GLenum t,GLuint b){++calls;if(t==GL_ARRAY_BUFFER)state.array=b;else{assert(t==GL_ELEMENT_ARRAY_BUFFER);vaos[state.vao].ebo=b;}}
static void glActiveTexture(GLenum u){++calls;assert(u>=GL_TEXTURE0&&u<GL_TEXTURE0+8);state.active=(int)(u-GL_TEXTURE0);}
static void glBindTexture(GLenum t,GLuint p){++calls;assert(t==GL_TEXTURE_2D);state.tex[state.active]=p;}
static void glEnable(GLenum c){++calls;*cap(c)=GL_TRUE;}static void glDisable(GLenum c){++calls;*cap(c)=GL_FALSE;}
static void glDepthFunc(GLenum f){++calls;state.df=f;}static void glDepthMask(GLboolean m){++calls;state.dw=m;}
static void glColorMask(GLboolean r,GLboolean g,GLboolean b,GLboolean a){++calls;state.colour[0]=r;state.colour[1]=g;state.colour[2]=b;state.colour[3]=a;}
static void glBlendEquation(GLenum e){++calls;state.er=state.ea=e;}static void glBlendFunc(GLenum a,GLenum b){++calls;state.sr=state.sa=a;state.dr=state.da=b;}
static void glBufferData(GLenum t,GLsizeiptr n,const void *p,GLenum u){++calls;assert(t==GL_ARRAY_BUFFER&&state.array==11&&u==GL_STREAM_DRAW&&n>0&&(size_t)n<=sizeof upload);bytes=(size_t)n;memcpy(upload,p,bytes);}
static void glEnableVertexAttribArray(GLuint i){++calls;assert(i<3);vaos[state.vao].a[i].on=1;}
static void glVertexAttribPointer(GLuint i,GLint n,GLenum t,GLboolean norm,GLsizei stride,const void *p){++calls;assert(i<3);Attr *a=&vaos[state.vao].a[i];a->size=n;a->type=(int)t;a->norm=norm;a->stride=stride;a->ptr=(uintptr_t)p;a->buffer=state.array;}
#ifndef WMMT_VK
static void glGetIntegerv(GLenum e,GLint *out){++calls;switch(e){
case GL_CURRENT_PROGRAM:*out=(GLint)state.prog;return;case GL_ARRAY_BUFFER_BINDING:*out=(GLint)state.array;return;case GL_VERTEX_ARRAY_BINDING_OES:*out=(GLint)state.vao;return;case GL_ACTIVE_TEXTURE:*out=GL_TEXTURE0+state.active;return;case GL_TEXTURE_BINDING_2D:*out=(GLint)state.tex[state.active];return;
case GL_BLEND_SRC_RGB:*out=(GLint)state.sr;return;case GL_BLEND_DST_RGB:*out=(GLint)state.dr;return;case GL_BLEND_SRC_ALPHA:*out=(GLint)state.sa;return;case GL_BLEND_DST_ALPHA:*out=(GLint)state.da;return;case GL_BLEND_EQUATION_RGB:*out=(GLint)state.er;return;case GL_BLEND_EQUATION_ALPHA:*out=(GLint)state.ea;return;case GL_DEPTH_FUNC:*out=(GLint)state.df;return;default:abort();}}
static GLboolean glIsEnabled(GLenum e){++calls;return *cap(e);}
static void glGetBooleanv(GLenum e,GLboolean *out){++calls;if(e==GL_DEPTH_WRITEMASK)*out=state.dw;else{assert(e==GL_COLOR_WRITEMASK);memcpy(out,state.colour,4);}}
static void glBlendEquationSeparate(GLenum r,GLenum a){++calls;state.er=r;state.ea=a;}
static void glBlendFuncSeparate(GLenum sr,GLenum dr,GLenum sa,GLenum da){++calls;state.sr=sr;state.dr=dr;state.sa=sa;state.da=da;}
#else
static int vkgl_program_usable(GLuint p){++calls;assert(p==2);return !unusable;}
static uint64_t vkgl_error_epoch(void){return epoch;}
typedef struct {State state;Vao vao;Uni uni;GLuint prog;} Snapshot;
static void *vkgl_preview_save(GLuint p){++calls;assert(p==1);if(fail_scope)return NULL;Snapshot *s=malloc(sizeof *s);assert(s);s->state=state;s->vao=vaos[state.vao];s->uni=uni[p];s->prog=p;return s;}
static void vkgl_scope_restore_preserve_error(void *p){++calls;Snapshot *s=p;int pending=state.err;state=s->state;vaos[state.vao]=s->vao;uni[s->prog]=s->uni;if(!state.err)state.err=pending;free(s);}
#endif
static void glDrawArrays(GLenum,GLint,GLsizei);
"""
tests=r"""
static void glDrawArrays(GLenum mode,GLint first,GLsizei n){
++calls;++draws;assert(mode==GL_TRIANGLES&&first==0&&(size_t)n==expected_n);assert(state.prog==2&&state.vao==10&&state.array==11);
assert(state.depth==GL_TRUE&&state.df==GL_LEQUAL&&state.dw==GL_FALSE&&state.cull==GL_FALSE&&state.stencil==GL_FALSE&&state.blend==GL_TRUE);
assert(state.sr==GL_SRC_ALPHA&&state.sa==GL_SRC_ALPHA&&state.dr==GL_ONE&&state.da==GL_ONE&&state.er==GL_FUNC_ADD&&state.ea==GL_FUNC_ADD);
assert(state.colour[0]&&state.colour[1]&&state.colour[2]&&state.colour[3]&&state.active==0&&state.tex[0]==white_tex);assert(bytes==expected_n*sizeof(tail_render_vertex));
const tail_render_vertex *v=(const tail_render_vertex*)upload;for(size_t i=0;i<expected_n;++i){assert(v[i].pos[0]==verts[i].position.x&&v[i].pos[1]==verts[i].position.y&&v[i].pos[2]==verts[i].position.z);assert(v[i].uv[0]==0&&v[i].uv[1]==0&&!memcmp(v[i].rgba,verts[i].rgba,sizeof v[i].rgba));}
for(int i=0;i<3;++i){Attr *a=&vaos[10].a[i];assert(a->on&&a->buffer==11&&a->type==GL_FLOAT&&a->norm==GL_FALSE&&a->stride==sizeof(tail_render_vertex));}
assert(vaos[10].a[0].ptr==offsetof(tail_render_vertex,pos)&&vaos[10].a[1].ptr==offsetof(tail_render_vertex,uv)&&vaos[10].a[2].ptr==offsetof(tail_render_vertex,rgba));
assert(!memcmp(uni[2].mvp,vp.m,64)&&uni[2].sampler==0&&uni[2].grade[0]==1&&uni[2].grade[1]==1&&uni[2].grade[2]==1);assert((uni[2].fog[0]-2e12f)/(uni[2].fog[0]-uni[2].fog[1])>1);
if(history_n<2)memcpy(history[history_n++],upload,bytes);if(draw_error){++epoch;if(!state.err)state.err=902;}
}
static void setup(unsigned vao){render_tail_context_lost();memset(&state,0,sizeof state);memset(vaos,0,sizeof vaos);memset(uni,0,sizeof uni);memset(&rp,0,sizeof rp);memset(&vp,0,sizeof vp);
state.prog=5;state.array=6;state.vao=vao;state.active=4;for(int i=0;i<8;++i)state.tex[i]=40u+(unsigned)i;state.sr=201;state.dr=202;state.sa=203;state.da=204;state.er=205;state.ea=206;state.df=207;state.depth=GL_FALSE;state.cull=GL_TRUE;state.stencil=GL_TRUE;state.blend=GL_FALSE;state.dw=GL_TRUE;state.colour[0]=state.colour[2]=GL_TRUE;state.colour[1]=state.colour[3]=GL_FALSE;
for(int i=0;i<4;++i){state.vp[i]=10+i;state.sc[i]=20+i;for(int j=0;j<4;++j)state.generic[i][j]=(float)(i*4+j);Attr *a=&vaos[vao].a[i];a->on=i%2;a->size=2;a->type=999;a->norm=1;a->stride=12;a->buffer=88;a->ptr=1234+(unsigned)i;vp.m[i*5]=1;}state.sc_on=1;state.front=1000;vaos[vao].ebo=77;memset(&uni[1],0xa5,sizeof uni[1]);memset(&uni[5],0x5a,sizeof uni[5]);
for(unsigned i=0;i<2*TAIL_TRAIL_MAX_VERTICES;++i){verts[i].position=(TailTrailVec3){(float)i,2,3};verts[i].rgba[0]=1;verts[i].rgba[1]=verts[i].rgba[2]=0;verts[i].rgba[3]=i?0.8f:1e-8f;}
calls=compiles=draws=deletes=fail_compile=fail_vao=fail_vbo=unusable=fail_scope=draw_error=history_n=0;epoch=0;white_tex=7;progs[0].id=1;expected_n=6;}
static int call(void){return render_tail_triangles(&vp,verts,expected_n,&rp);}
static void restored(State old,Vao v,Uni baseline,Uni caller){assert(!memcmp(&old,&state,sizeof old)&&!memcmp(&v,&vaos[state.vao],sizeof v)&&!memcmp(&baseline,&uni[1],sizeof baseline)&&!memcmp(&caller,&uni[5],sizeof caller));}
static void test_success(void){for(unsigned vao=0;vao<=3;vao+=3){setup(vao);state.err=901;State old=state;Vao v=vaos[vao];Uni b=uni[1],c=uni[5];assert(call()==1);restored(old,v,b,c);assert(compiles==1&&draws==1&&rp.draws==1&&rp.triangles==2);
verts[0].position.x=99;verts[0].rgba[3]=0.4f;assert(call()==1);restored(old,v,b,c);assert(compiles==1&&draws==2&&rp.draws==2&&rp.triangles==4);const tail_render_vertex *first=(const tail_render_vertex*)history[0];assert(first[0].pos[0]==0&&first[0].rgba[3]==1e-8f&&memcmp(history[0],history[1],bytes));render_tail_release();assert(deletes==3&&!tail_render.failed&&!tail_render.program.id);restored(old,v,b,c);assert(call()==1&&compiles==2);int n=calls;render_tail_context_lost();assert(calls==n&&!tail_render.program.id&&!tail_render.vao&&!tail_render.vbo);assert(call()==1&&compiles==3);}
setup(3);expected_n=2*TAIL_TRAIL_MAX_VERTICES;assert(call()==1&&rp.triangles==(int)(expected_n/3));}
static void test_noop(void){setup(3);assert(!render_tail_triangles(NULL,verts,6,&rp)&&!render_tail_triangles(&vp,NULL,6,&rp)&&!render_tail_triangles(&vp,verts,6,NULL));expected_n=0;assert(!call());expected_n=1;assert(!call());expected_n=2*TAIL_TRAIL_MAX_VERTICES+3;assert(!call());expected_n=6;vp.m[0]=NAN;assert(!call());vp.m[0]=1;verts[0].rgba[3]=NAN;assert(!call());verts[0].rgba[3]=1.1f;assert(!call());verts[0].rgba[3]=0.8f;verts[0].position.x=INFINITY;assert(!call());verts[0].position.x=1e13f;assert(!call());verts[0].position.x=1e12f;vp.m[0]=1e30f;assert(!call());vp.m[0]=1;white_tex=0;assert(!call());white_tex=7;progs[0].id=0;assert(!call());assert(!calls&&!draws&&!rp.draws&&!rp.triangles);}
static void test_init_failure(void){for(int mode=0;mode<3;++mode){setup(3);fail_compile=mode==0;fail_vao=mode==1;fail_vbo=mode==2;State old=state;Vao v=vaos[3];Uni b=uni[1],c=uni[5];assert(!call());restored(old,v,b,c);assert(!draws&&tail_render.failed&&!tail_render.program.id&&!tail_render.vao&&!tail_render.vbo);int n=calls;fail_compile=fail_vao=fail_vbo=0;assert(!call()&&calls==n);render_tail_release();assert(call());}}
static void test_errors(void){
#ifdef WMMT_VK
setup(3);fail_scope=1;State old=state;assert(!call()&&!memcmp(&old,&state,sizeof old)&&!compiles&&!draws&&!tail_render.failed);setup(3);unusable=1;old=state;assert(!call()&&!memcmp(&old,&state,sizeof old)&&tail_render.failed&&!draws);setup(3);epoch=UINT64_MAX;assert(!call()&&!calls);
for(int prior=0;prior<2;++prior){setup(3);state.err=prior?901:0;old=state;Vao v=vaos[3];Uni b=uni[1],c=uni[5];draw_error=1;assert(!call());old.err=prior?901:902;restored(old,v,b,c);assert(epoch==1&&tail_render.failed&&deletes==3&&!rp.draws&&!rp.triangles);}
#else
/* Native GLES cannot non-consumingly inspect error: submission != GPU success. */
setup(3);draw_error=1;State old=state;assert(call()==1);old.err=902;assert(!memcmp(&old,&state,sizeof old));
#endif
}
int main(void){test_success();test_noop();test_init_failure();test_errors();puts("production tail render host state test passed");return 0;}
"""
with tempfile.TemporaryDirectory(prefix='tail-render-host-') as tmp:
 source=Path(tmp)/'fixture.c';source.write_text(prefix+'\n'+extract('static int prog_init(')+'\n'+s[a:b]+'\n'+tests)
 for mode in ('gles','vk'):
  exe=Path(tmp)/mode
  cmd=['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-I',str(root/'src'),str(source),'-lm','-o',str(exe)]
  if mode=='vk':cmd.insert(1,'-DWMMT_VK')
  san=os.environ.get('TAIL_RENDER_SANITIZE')
  if san:cmd[1:1]=['-fsanitize='+('address,undefined' if san=='1' else san),'-fno-omit-frame-pointer']
  subprocess.run(cmd,check=True,timeout=30);subprocess.run([str(exe)],check=True,timeout=30)
print('GLES/Vulkan mock-state only; no APK/device/visual validation.')
