#!/usr/bin/env python3
"""Production renderer constructors against direct catalog API recorders.
Exact VS/FS/attribute bytes are compared with GLES, and with the saved baseline
when present. No generated SPIR-V, GPU, compiler or uniform shadow is simulated.
Native failure/readiness/cleanup are CPU control-flow proof, not device proof.
"""
from pathlib import Path
import importlib.util, os, re, subprocess, sys, tempfile
R = Path(__file__).resolve().parents[1]
O = Path(os.environ.get('TMPDIR', R.parent/'tmp')).resolve()
assert O == Path('/Volumes/CodexWork') or str(O).startswith('/Volumes/CodexWork/')
S = (R/'src/render.c').read_text()
BASE = Path(os.environ.get('CINDER_RENDER_BASELINE', R.parent/'round5-baseline/src/render.c'))

def fun(s, anchor):
    a = s.index(anchor); b = s.index('{', a)
    mask = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', lambda m: ' '*len(m.group()), s, flags=re.S)
    depth = 0
    for i in range(b, len(s)):
        depth += (mask[i]=='{')-(mask[i]=='}')
        if not depth: return s[a:i+1]+'\n'
    raise ValueError(anchor)

PRE = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t GLuint, GLenum, GLbitfield; typedef int GLint, GLsizei;
typedef float GLfloat; typedef char GLchar; typedef unsigned char GLubyte, GLboolean;
enum {GL_TEXTURE_2D=1,GL_TEXTURE_CUBE_MAP,GL_RGBA,GL_RGB,GL_UNSIGNED_BYTE,GL_NEAREST,GL_LINEAR,
 GL_TEXTURE_MIN_FILTER,GL_TEXTURE_MAG_FILTER,GL_TEXTURE_WRAP_S,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE,
 GL_ACTIVE_TEXTURE,GL_FRAMEBUFFER,GL_FRAMEBUFFER_BINDING,GL_RENDERBUFFER,GL_COLOR_ATTACHMENT0,
 GL_DEPTH_ATTACHMENT,GL_DEPTH_COMPONENT16,GL_FRAMEBUFFER_COMPLETE,GL_EXTENSIONS,GL_TEXTURE0,
 GL_CURRENT_PROGRAM,GL_ARRAY_BUFFER,GL_FLOAT,GL_TRIANGLES,GL_FALSE=0};
#include "render.h"
#include "native_vk.h"
void render_tire_smoke_context_lost(void) {}
static unsigned creates, destroys, native_calls, gl_calls, uniform_calls, query_calls;
static unsigned fail_create, notready_create, white_fail, target_fail, last_created;
static unsigned char live[8192], ready[8192];
static unsigned next_program=1;
static int emit=1;
static void hex(const char*s){for(;*s;++s)printf("%02x",(unsigned char)*s);putchar(' ');}
static GLuint record_program(const char*v,const char*f,const char**a,int n){
 ++creates;assert(v&&f&&a&&n>0&&n<=8);
 if(emit){printf("P %d ",n);hex(v);hex(f);for(int i=0;i<n;++i)hex(a[i]);putchar('\n');}
 if(creates==fail_create)return 0;
 GLuint id=next_program++;assert(id<8192);live[id]=1;ready[id]=creates!=notready_create;last_created=id;return id;
}
static void drop(GLuint p){if(!p)return;assert(p<8192&&live[p]);live[p]=ready[p]=0;++destroys;}
static unsigned living(void){unsigned n=0;for(unsigned i=1;i<next_program;++i)n+=live[i];return n;}
#ifdef WMMT_NATIVE_VK
uint32_t cinder_vk_program_create(const char*v,const char*f,const char**a,int n){++native_calls;return record_program(v,f,a,n);}
int cinder_vk_program_ready(uint32_t p){++query_calls;return p<8192&&live[p]&&ready[p];}
void cinder_vk_program_destroy(uint32_t p){drop(p);}
#pragma GCC poison gl_compile_program glGetUniformLocation glUseProgram glDeleteProgram glUniform1i glUniform1f glUniform2f glUniform3f glUniform4f glUniform3fv glUniform4fv glUniformMatrix4fv vkgl_program_usable GL_CURRENT_PROGRAM glGetProgramiv glGetProgramInfoLog glGetUniformfv glGetUniformiv
#else
GLuint gl_compile_program(const char*v,const char*f,const char**a,int n){++gl_calls;return record_program(v,f,a,n);}
GLint glGetUniformLocation(GLuint p,const GLchar*n){assert(p&&n);++uniform_calls;return 1;}
void glUseProgram(GLuint p){assert(!p||live[p]);++uniform_calls;}
void glDeleteProgram(GLuint p){drop(p);}
void glUniform1i(GLint l,GLint x){(void)l;(void)x;++uniform_calls;}
void glUniform1f(GLint l,GLfloat x){(void)l;(void)x;++uniform_calls;}
void glUniform2f(GLint l,GLfloat x,GLfloat y){(void)l;(void)x;(void)y;++uniform_calls;}
int vkgl_program_usable(GLuint p){return live[p]&&ready[p];}
#endif
void glGetIntegerv(GLenum p,GLint*out){if(p==0x8d57)*out=4;else *out=0;}
const GLubyte*glGetString(GLenum p){assert(p==GL_EXTENSIONS);return(const GLubyte*)"";}
void glActiveTexture(GLenum p){(void)p;}
void glBindTexture(GLenum t,GLuint p){(void)t;(void)p;}
void glGenTextures(GLsizei n,GLuint*p){while(n--)*p++=500;}
void glTexImage2D(GLenum t,GLint l,GLint f,GLsizei w,GLsizei h,GLint b,GLenum fmt,GLenum ty,const void*p){(void)t;(void)l;(void)f;(void)w;(void)h;(void)b;(void)fmt;(void)ty;(void)p;}
void glTexParameteri(GLenum t,GLenum p,GLint x){(void)t;(void)p;(void)x;}
void glGenRenderbuffers(GLsizei n,GLuint*p){while(n--)*p++=501;}
void glBindRenderbuffer(GLenum t,GLuint p){(void)t;(void)p;}
void glRenderbufferStorage(GLenum t,GLenum f,GLsizei w,GLsizei h){(void)t;(void)f;(void)w;(void)h;}
void glGenFramebuffers(GLsizei n,GLuint*p){while(n--)*p++=502;}
void glBindFramebuffer(GLenum t,GLuint p){(void)t;(void)p;}
void glFramebufferTexture2D(GLenum t,GLenum a,GLenum ty,GLuint p,GLint l){(void)t;(void)a;(void)ty;(void)p;(void)l;}
void glFramebufferRenderbuffer(GLenum t,GLenum a,GLenum ty,GLuint p){(void)t;(void)a;(void)ty;(void)p;}
GLenum glCheckFramebufferStatus(GLenum t){(void)t;return target_fail?0:GL_FRAMEBUFFER_COMPLETE;}
void glGenVertexArraysOES(GLsizei n,GLuint*p){while(n--)*p++=503;}
void glGenBuffers(GLsizei n,GLuint*p){while(n--)*p++=504;}
void glDeleteVertexArraysOES(GLsizei n,const GLuint*p){(void)n;(void)p;}
void glDeleteBuffers(GLsizei n,const GLuint*p){(void)n;(void)p;}
void glEnableVertexAttribArray(GLuint x){(void)x;}
void glBindBuffer(GLenum t,GLuint p){(void)t;(void)p;}
void glVertexAttribPointer(GLuint a,GLint b,GLenum c,GLboolean d,GLsizei e,const void*f){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;}
void glDrawArrays(GLenum t,GLint a,GLsizei n){(void)t;(void)a;(void)n;}
uint32_t cinder_vk_texture_rgba8(int w,int h,const void*p,size_t n,const cinder_vk_sampler*s){assert(w==1&&h==1&&p&&n==4&&s->use_state);return white_fail?0:500;}
void cinder_vk_screen_extent(int*w,int*h){*w=640;*h=480;}
static unsigned warm_calls;
static int native_warm_cube(uint32_t p,uint32_t c,const float*v,size_t n){assert(c&&v&&n==36);if(!cinder_vk_program_ready(p))return 0;++warm_calls;return 1;}
static void blit_stub(GLint a,GLint b,GLint c,GLint d,GLint e,GLint f,GLint g,GLint h,GLbitfield i,GLenum j){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)h;(void)i;(void)j;}
static void storage_stub(GLenum a,GLsizei b,GLenum c,GLsizei d,GLsizei e){(void)a;(void)b;(void)c;(void)d;(void)e;}
typedef struct {uint32_t target;int w,h;} native_scene_view;
static native_scene_view native_warm_view;
static uint32_t native_loader_program;
static int native_samples_cap=4;
int cinder_vk_sample_limit(void){return native_samples_cap;}
static int native_simple_target(int w,int h,cinder_vk_storage_format cf,cinder_vk_storage_format df,GLuint*t,GLuint*d,GLuint*f){assert(w==256&&h==256&&cf==CINDER_VK_STORAGE_RGBA8&&df==CINDER_VK_STORAGE_DEPTH16);if(target_fail)return 0;*t=500;*d=501;*f=502;return 1;}
void cinder_vk_target_destroy(uint32_t t){(void)t;}
void cinder_vk_texture_destroy(uint32_t t){(void)t;}
void cinder_vk_attachment_destroy(uint32_t t){(void)t;}
'''

def production(s):
    # Full original declarations and shader literals; constructors themselves are
    # extracted verbatim. No hand-maintained copy of a shader or variant head.
    a=s.index('/* Same shading as the arcade'); b=s.index('#if defined(WMMT_EGL) && !defined(WMMT_NATIVE_VK)\nPFN',a)
    text=s[a:b]
    # frame_sampler refers to this field before its definition in the real top block.
    text='#ifdef WMMT_NATIVE_VK\nstatic uint32_t native_frame_texture;\n#endif\n'+text
    for anchor in ['static GLuint native_program_create(', 'static void native_program_release(', 'static void native_render_programs_release(']:
        if anchor in s:text+='\n#ifdef WMMT_NATIVE_VK\n'+fun(s,anchor)+'#endif\n'
    for anchor in ['static int prog_init(', 'static int lit_init(', 'static int gloss_init(']:text+=fun(s,anchor)
    a=s.index('/* ---- isolated, float-colour tail trail drawing ---- */');b=s.index('#ifndef WMMT_VK\ntypedef struct {',a)
    text+=s[a:b]
    text+=fun(s,'int render_init(')
    a=s.index('#define HQ_LEVELS 4');b=s.index('/* a target\'s texture in hq.fmt',a)
    if '#include "render_native_targets.inc"' in s[a:b]:b=s.rfind('#ifdef WMMT_NATIVE_VK',a,b)
    text+=s[a:b]+'\nstatic int msrt_off;\n'
    # Resource API is the declared stub boundary here; the complete graph has its
    # own fault/ownership test. Do not transplant legacy GL allocations into native.
    text+='\n#ifdef WMMT_NATIVE_VK\nstatic int native_graph_dirty;\nstatic void hq_free(void){frame_history_valid=0;frame_sampler_off();native_graph_dirty=0;}\n#endif\n'
    if 'static void native_hq_programs_release(' in s:text+='#ifdef WMMT_NATIVE_VK\n'+fun(s,'static void native_hq_programs_release(')+'#endif\n'
    for anchor in ['int render_hq(', 'void render_ssao(']:text+=fun(s,anchor)
    a=s.index('#define OVER_SIZE 256');b=s.index('static int over_init(',a);text+=s[a:b]+fun(s,'static int over_init(')
    text+=fun(s,'static void warm_cube(')
    a=s.index('static const char *WARM_VS =');b=s.index('void render_warm_begin(',a);text+=s[a:b]+fun(s,'void render_warm_begin(')
    return text

BODY = r'''
static void success(void){
 assert(!render_init());assert(creates==13&&lit_progs[2*WPK_LIT_CAR].id==lit_progs[2*WPK_LIT_CAR+1].id);
 hq.blit=blit_stub;hq.storage_ms=storage_stub;
 assert(render_hq(4,.4f));assert(creates==22&&frame_env&&hq.on);
 render_ssao(.6f);assert(creates==24&&hq.ssao==.6f);render_ssao(.7f);assert(creates==24&&hq.ssao==.7f);
 assert(!over_init()&&over.state==1);assert(creates==25);
 warm_cube(70);assert(creates==26);warm_cube(70);assert(creates==26);
 render_warm_begin();assert(creates==27);render_warm_begin();assert(creates==27);
 assert(tail_render_prepare()&&creates==28);assert(tail_render_prepare()&&creates==28);
#ifdef WMMT_NATIVE_VK
 assert(native_calls==28&&!gl_calls&&!uniform_calls&&query_calls&&warm_calls==2);
 scene_prog p={.id=777,.mvp=-9};lit_prog l={.id=777,.mvp=-9};
 assert(!prog_init(&p,FS)&&!p.mvp&&!p.eye&&!p.wet);drop(p.id);
 assert(!lit_init(&l,0,0)&&!l.mvp&&!l.over&&!l.frame_k);drop(l.id);
 assert(!gloss_init(&p,0)&&!p.mvp&&!p.wet);drop(p.id);
#else
 assert(gl_calls==28&&!native_calls&&uniform_calls);
#endif
}
#ifdef WMMT_NATIVE_VK
static void cleanup(void){
 native_render_programs_release();native_hq_programs_release();
 native_program_release(&hq.ao_prog);native_program_release(&hq.ao_blur_prog);native_program_release(&over.prog);
 render_tail_release();
 /* Warm statics are intentionally persistent. Mark them unready at their API
  * boundary below to exercise the production invalidation path on next entry. */
}
static void failures(void){
 emit=0;cleanup();for(unsigned i=1;i<next_program;++i)if(live[i])ready[i]=0;
 fail_create=creates+1;render_warm_begin();fail_create=creates+1;warm_cube(70);fail_create=0;assert(!living());
 /* render_init is a new-context entry: never destroy stale names there. */
 progs[0].id=7000;gloss_progs[1].id=7001;lit_progs[5].id=7002;blur_progs[2]=7003;shadow_prog=7004;
 fail_create=creates+1;assert(render_init()==-1&&!living());fail_create=0;
 for(unsigned mode=0;mode<2;++mode)for(unsigned nth=1;nth<=13;++nth){
   fail_create=notready_create=0;if(mode)notready_create=creates+nth;else fail_create=creates+nth;
   assert(render_init()==-1);assert(!living());
 }
 fail_create=notready_create=0;white_fail=1;assert(render_init()==-1&&!living());white_fail=0;
 assert(!render_init());unsigned base=living();assert(base==13);
 for(unsigned mode=0;mode<2;++mode)for(unsigned nth=1;nth<=6;++nth){
   fail_create=notready_create=0;if(mode)notready_create=creates+nth;else fail_create=creates+nth;
   assert(!render_hq(4,.4f)&&!hq.on&&living()==base);
   assert(!hq.down_prog[0]&&!hq.down_prog[1]&&!hq.up_prog&&!blur_progs[3]&&!blur_progs[4]&&!blur_progs[5]);
 }
 fail_create=notready_create=0;assert(render_hq(4,.4f));base=living();
 /* WET and FRAME_ENV are optional replacements: a failed new object retains
  * the old READY program rather than publishing an unusable name. */
 for(unsigned mode=0;mode<2;++mode)for(unsigned nth=7;nth<=9;++nth){
   GLuint previous= nth==7?progs[0].id:nth==8?progs[1].id:lit_progs[2*WPK_LIT_CAR].id;
   fail_create=notready_create=0;if(mode)notready_create=creates+nth;else fail_create=creates+nth;
   assert(render_hq(4,.4f)&&living()==base);
   GLuint retained= nth==7?progs[0].id:nth==8?progs[1].id:lit_progs[2*WPK_LIT_CAR].id;
   assert(previous==retained&&cinder_vk_program_ready(retained));if(nth==9)assert(!frame_env);
 }
 for(unsigned mode=0;mode<2;++mode)for(unsigned nth=1;nth<=2;++nth){
   fail_create=notready_create=0;if(mode)notready_create=creates+nth;else fail_create=creates+nth;
   render_ssao(.5f);assert(!hq.ssao&&!hq.ao_prog&&!hq.ao_blur_prog&&living()==base);
 }
 fail_create=notready_create=0;render_ssao(.5f);GLuint old=hq.ao_prog;ready[old]=0;unsigned before=creates;
 render_ssao(.7f);assert(hq.ssao==.7f&&creates==before+2&&!live[old]);
 old=tail_render.program.id;render_tail_release();fail_create=creates+1;
 assert(!tail_render_prepare()&&tail_render.failed&&!tail_render.program.id);before=creates;
 assert(!tail_render_prepare()&&creates==before);render_tail_release();fail_create=0;
 assert(tail_render_prepare());old=tail_render.program.id;ready[old]=0;before=creates;
 assert(tail_render_prepare()&&creates==before+1&&!live[old]);render_tail_release();
 // Persistent loader/cube names must consult readiness, not cached nonzero IDs.
 render_warm_begin();old=native_loader_program;assert(cinder_vk_program_ready(old));ready[old]=0;before=creates;
 render_warm_begin();assert(creates==before+1&&!live[old]&&native_loader_program!=old);
 ready[native_loader_program]=0;fail_create=creates+1;render_warm_begin();assert(!native_loader_program);fail_create=0;
 render_warm_begin();assert(cinder_vk_program_ready(native_loader_program));
 warm_cube(70);old=last_created;ready[old]=0;before=creates;warm_cube(70);assert(creates==before+1&&!live[old]);
 ready[last_created]=0;fail_create=creates+1;before=warm_calls;warm_cube(70);assert(warm_calls==before);fail_create=0;
 before=creates;unsigned old_warms=warm_calls;warm_cube(70);assert(creates==before+1&&warm_calls==old_warms+1);
 native_program_release(&over.prog);over.state=0;target_fail=1;base=living();assert(over_init()==-1&&!over.prog&&living()==base);target_fail=0;
 fail_create=creates+1;assert(over_init()==-1&&!over.prog&&living()==base);fail_create=0;
 assert(!over_init()&&cinder_vk_program_ready(over.prog));
 native_samples_cap=8;
 const int requested[]={1,3,4,8,99},expected[]={1,2,4,8,8};
 for(unsigned i=0;i<5;++i){assert(render_hq(requested[i],.4f)&&hq.samples==expected[i]&&hq.samples0==expected[i]&&hq.msrt);}
 native_samples_cap=0;before=creates;assert(!render_hq(4,.4f)&&!hq.on&&creates==before);native_samples_cap=4;
 cleanup();for(unsigned i=1;i<next_program;++i)if(live[i])drop(i);assert(!living());
 assert(!gl_calls&&!uniform_calls);fprintf(stderr,"native create/ready failure, partial cleanup, shared alias and stale-cache controls: PASS\n");
}
#endif
int main(void){success();
#ifdef WMMT_NATIVE_VK
 failures();
#endif
 return 0;}
'''

with tempfile.TemporaryDirectory(prefix='native-render-programs-', dir=O) as td:
    td=Path(td); outputs={}
    modes=[('gles',S,False,False),('vkcompat',S,False,True),('native',S,True,True)]
    if BASE.exists():modes.append(('baseline-gles',BASE.read_text(),False,False))
    for name,source,native,compat in modes:
        c=td/(name+'.c');exe=td/name;c.write_text(PRE+production(source)+BODY)
        cmd=['clang','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(R/'src')]
        if native:cmd+=['-DWMMT_NATIVE_VK']
        if compat:cmd+=['-DWMMT_VK']
        if sys.platform=='darwin':cmd+=['-I','/opt/homebrew/include']
        subprocess.run(cmd+[str(c),'-lm','-o',str(exe)],check=True,timeout=120)
        run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
        if run.returncode:print(run.stderr,file=sys.stderr)
        run.check_returncode();outputs[name]=run.stdout
    # Extra standalone constructor probes are appended only in native.
    rows=outputs['gles'].splitlines();assert len(rows)==28
    assert outputs['vkcompat']==outputs['gles']
    assert outputs['native'].splitlines()[:28]==rows
    if 'baseline-gles' in outputs:assert outputs['baseline-gles']==outputs['gles']
    spec=importlib.util.spec_from_file_location('vkglsl',R/'tools/vkglsl.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    keys=[]
    for row in rows:
        fields=row.split();assert fields[0]=='P';n=int(fields[1]);vs,fs,*attrs=[bytes.fromhex(x).decode() for x in fields[2:]];assert len(attrs)==n
        key=module.key(vs,fs,attrs);keys.append(f'{key:016x}')
        dump=R/'tools/vkprogs'/f'{key:016x}.txt'
        assert dump.read_text()=='// attribs: '+' '.join(attrs)+'\n//----VS\n'+vs+'\n//----FS\n'+fs,(dump,key)
    print('PASS 28 exact production VS/FS/attribute rows and catalog keys: FF/cutout/gloss, blur6, shadow, lit5 + FRAME_ENV, WET2, down/up, SSAO pair, overhead, cube/loader warm, tail')
    print('PASS native direct-API only: zero GL program/uniform authoring; failed create/ready, partial cleanup, shared car alias, stale SSAO/tail/warm caches, no uniform state (UBSan CPU recorder)')
    print('keys:',','.join(keys))
