#!/usr/bin/env python3
"""Actual renderer calls/packet controls, not GPU pixels or Vulkan conformance.

Runs complete renderer translation units with GL/native API recorders and the real
native packet initializer. Strict Android poison/token/object auditing is separate.
All generated inputs/results live in CINDER_TEST_OUT, TMPDIR or tempfile's default.
"""
from pathlib import Path
import hashlib, json, os, re, shutil, subprocess, sys, tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('CINDER_TEST_OUT', os.environ.get('TMPDIR', tempfile.gettempdir()))).resolve()
OUT.mkdir(parents=True, exist_ok=True)
BASE = Path(os.environ.get('CINDER_RENDER_BASELINE', ROOT.parent / 'round7-baseline/src/render.c')).resolve()
NDK = Path(os.environ.get('CINDER_NDK', '/Users/arx/Library/Android/sdk/ndk/28.0.13004108'))
SYS = NDK / 'toolchains/llvm/prebuilt/darwin-x86_64/sysroot/usr/include'
SOURCE = (ROOT / 'src/render.c').read_text()
BASELINE = BASE.read_text()

def function(source, name):
    """Select an actual definition, never an earlier declaration or call."""
    mask = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: ' ' * len(m.group()), source, flags=re.S)
    match = re.search(r'(?m)^[\w \t*]+\b' + re.escape(name) + r'\([^;{}]*\)\s*\{', mask)
    assert match, name
    start = match.start(); brace = mask.index('{', start); depth = 0
    for pos in range(brace, len(mask)):
        depth += (mask[pos] == '{') - (mask[pos] == '}')
        if depth == 0:
            return source[start:pos + 1] + '\n'
    raise AssertionError(name)

PRE = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define __ANDROID__ 1
#define GL_GLEXT_PROTOTYPES 1
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#define WMMT_GL_H 1
#include "native_vk.h"
GLuint gl_compile_program(const char*,const char*,const char**,int);
static unsigned gl_calls, native_calls, draws, info_calls, clear_calls;
static int fail_info, fail_clear, fail_draw, missing_target;
static VkFormat depth_format=VK_FORMAT_D24_UNORM_S8_UINT;
static VkFormat color_format=VK_FORMAT_R8G8B8A8_UNORM;
static VkImageAspectFlags last_aspects;
static uint32_t last_clear_target;
static uint32_t expected_target=17;
static const char *tag;
static cinder_vk_pipeline gs;
static uint32_t gstencil_ref;
static int gviewport[4]={0,0,64,48};
static uint64_t hash(const void*p,size_t n){const unsigned char*b=p;uint64_t h=1469598103934665603ull;while(n--)h=(h^*b++)*1099511628211ull;return h;}
static void pipeline(const cinder_vk_pipeline*p,uint32_t ref){
 printf("P %s %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u %u\n",tag,
 p->depth_test,p->depth_test&&p->depth_write,p->depth_compare,p->cull,p->asset_front,p->blend,
 p->blend?p->src_blend:0,p->blend?p->dst_blend:0,p->blend?p->blend_op:0,p->color_mask,p->stencil,
 p->stencil?p->stencil_compare:0,p->stencil?p->stencil_fail:0,p->stencil?p->depth_fail:0,p->stencil?p->depth_pass:0,p->stencil?ref:0,p->stencil?p->stencil_compare_mask:0,p->stencil?p->stencil_write_mask:0,p->topology);
}
static void glrecord(GLenum t){++draws;gs.topology=t==GL_TRIANGLE_STRIP?VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP:VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;pipeline(&gs,gstencil_ref);}
static void state(const char*n,unsigned v){printf("G %s %s %u\n",tag,n,v);}
void glActiveTexture(GLenum v){++gl_calls;state("ActiveTexture",v);(void)v;}
void glEnable(GLenum v){++gl_calls;state("Enable",v);if(v==GL_DEPTH_TEST)gs.depth_test=1;else if(v==GL_CULL_FACE)gs.cull=VK_CULL_MODE_BACK_BIT;else if(v==GL_BLEND)gs.blend=1;else if(v==GL_STENCIL_TEST)gs.stencil=1;}
void glDisable(GLenum v){++gl_calls;state("Disable",v);if(v==GL_DEPTH_TEST)gs.depth_test=0;else if(v==GL_CULL_FACE)gs.cull=0;else if(v==GL_BLEND)gs.blend=0;else if(v==GL_STENCIL_TEST)gs.stencil=0;}
void glDepthFunc(GLenum v){++gl_calls;state("DepthFunc",v);gs.depth_compare=v==GL_ALWAYS?VK_COMPARE_OP_ALWAYS:VK_COMPARE_OP_LESS_OR_EQUAL;}
void glDepthMask(GLboolean v){++gl_calls;state("DepthMask",v);gs.depth_write=v;}
void glCullFace(GLenum v){++gl_calls;state("CullFace",v);gs.cull=v==GL_FRONT?VK_CULL_MODE_FRONT_BIT:VK_CULL_MODE_BACK_BIT;}
void glFrontFace(GLenum v){++gl_calls;state("FrontFace",v);gs.asset_front=v==GL_CCW?VK_FRONT_FACE_COUNTER_CLOCKWISE:VK_FRONT_FACE_CLOCKWISE;}
void glBlendFunc(GLenum a,GLenum b){++gl_calls;gs.src_blend=a==GL_SRC_ALPHA?VK_BLEND_FACTOR_SRC_ALPHA:a==GL_SRC_COLOR?VK_BLEND_FACTOR_SRC_COLOR:VK_BLEND_FACTOR_ONE;gs.dst_blend=b==GL_ONE?VK_BLEND_FACTOR_ONE:b==GL_ZERO?VK_BLEND_FACTOR_ZERO:VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;}
void glBlendEquation(GLenum v){++gl_calls;assert(v==GL_FUNC_ADD);gs.blend_op=VK_BLEND_OP_ADD;}
void glColorMask(GLboolean a,GLboolean b,GLboolean c,GLboolean d){++gl_calls;gs.color_mask=a|(b<<1)|(c<<2)|(d<<3);}
void glStencilFunc(GLenum f,GLint ref,GLuint mask){++gl_calls;gs.stencil_compare=f==GL_EQUAL?VK_COMPARE_OP_EQUAL:VK_COMPARE_OP_ALWAYS;gstencil_ref=ref;gs.stencil_compare_mask=mask;}
void glStencilMask(GLuint mask){++gl_calls;gs.stencil_write_mask=mask;}
static VkStencilOp sop(GLenum v){return v==GL_ZERO?VK_STENCIL_OP_ZERO:v==GL_REPLACE?VK_STENCIL_OP_REPLACE:VK_STENCIL_OP_KEEP;}
void glStencilOp(GLenum f,GLenum df,GLenum dp){++gl_calls;gs.stencil_fail=sop(f);gs.depth_fail=sop(df);gs.depth_pass=sop(dp);}
void glDrawElements(GLenum t,GLsizei n,GLenum ty,const void*p){++gl_calls;(void)t;(void)n;(void)ty;(void)p;glrecord(t);}
void glDrawArrays(GLenum t,GLint f,GLsizei n){++gl_calls;(void)t;(void)f;(void)n;glrecord(t);}
void glViewport(GLint x,GLint y,GLsizei w,GLsizei h){++gl_calls;gviewport[0]=x;gviewport[1]=y;gviewport[2]=w;gviewport[3]=h;}
void glGetIntegerv(GLenum v,GLint*out){++gl_calls;if(v==GL_VIEWPORT)memcpy(out,gviewport,sizeof gviewport);else *out=0;}
void glGetBooleanv(GLenum v,GLboolean*out){++gl_calls;if(v==GL_COLOR_WRITEMASK){for(int i=0;i<4;++i)out[i]=(gs.color_mask>>i)&1;}else *out=v==GL_DEPTH_WRITEMASK?gs.depth_write:0;}
GLboolean glIsEnabled(GLenum v){++gl_calls;return v==GL_DEPTH_TEST?gs.depth_test:v==GL_BLEND?gs.blend:v==GL_STENCIL_TEST?gs.stencil:gs.cull!=0;}
GLenum glCheckFramebufferStatus(GLenum t){++gl_calls;(void)t;return GL_FRAMEBUFFER_COMPLETE;}
static unsigned next_id=700;
void glGenVertexArraysOES(GLsizei n,GLuint*p){++gl_calls;while(n--)*p++=++next_id;}
void glGenBuffers(GLsizei n,GLuint*p){++gl_calls;while(n--)*p++=++next_id;}
void glGenTextures(GLsizei n,GLuint*p){++gl_calls;while(n--)*p++=++next_id;}
void glGenFramebuffers(GLsizei n,GLuint*p){++gl_calls;while(n--)*p++=++next_id;}
void glGenRenderbuffers(GLsizei n,GLuint*p){++gl_calls;while(n--)*p++=++next_id;}
#ifdef WMMT_NATIVE_VK
/* The production initializer reads only this program metadata, not GL state. */
typedef struct{int vs,fs,block,n_samp;unsigned inputs;} vprog;
static vprog program={1,1,CINDER_VK_UNIFORM_BYTES,CINDER_VK_SAMPLERS,7};
static vprog*prog_get(uint32_t p){return p?&program:NULL;}
'''
POST_INIT = r'''
static const char *unames[]={"uMVP","uEye","uFog","uFogColor","uGrade","uUVOff","uWet","uHorizon","uMV","uL0","uL1","uD0","uD1","uAmb","uOver","uOverDir","uPower","uFrameK","uColor","uCut","uTexel","uView","uK","uThresh","uSharp","uBloomK"};
static const char *tnames[]={"uTex","uEnv","uSpec","uAO","uOverTex","uFrame","uGloss","uCube","uBloom"};
int cinder_vk_uniform(cinder_vk_draw*d,const char*n,const void*p,size_t z){++native_calls;assert(z<=64);for(unsigned i=0;i<sizeof unames/sizeof*unames;++i)if(!strcmp(n,unames[i])){memcpy(d->uniforms+64*i,p,z);return 1;}assert(0);return 0;}
int cinder_vk_texture(cinder_vk_draw*d,const char*n,uint32_t t){++native_calls;for(unsigned i=0;i<sizeof tnames/sizeof*tnames;++i)if(!strcmp(n,tnames[i])){d->textures[i%8]=t;return 1;}assert(0);return 0;}
int cinder_vk_sampler_state(cinder_vk_draw*d,const char*n,const cinder_vk_sampler*s){++native_calls;(void)n;d->samplers[0]=*s;return 1;}
int cinder_vk_texture_sampler(uint32_t t,cinder_vk_sampler*s){++native_calls;(void)t;*s=(cinder_vk_sampler){.use_state=1,.mipmaps=1,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_LINEAR,.anisotropy=4};return 1;}
int cinder_vk_submit(const cinder_vk_draw*in){++native_calls;if(fail_draw)return 0;++draws;pipeline(&in->pipeline,in->stencil_reference);
 cinder_vk_draw d=*in;uint64_t data[9]={0};for(int i=0;i<8;++i){if(d.attributes[i].data&&d.attributes[i].bytes)data[i]=hash(d.attributes[i].data,d.attributes[i].bytes);d.attributes[i].data=NULL;}
 if(d.indices&&d.index_bytes)data[8]=hash(d.indices,d.index_bytes);d.indices=NULL;
 printf("D %s %016llx %016llx\n",tag,(unsigned long long)hash(&d,sizeof d),(unsigned long long)hash(data,sizeof data));return 1;}
int cinder_vk_target_info(uint32_t t,cinder_vk_target_desc*out){++native_calls;++info_calls;assert(t==expected_target);if(fail_info||missing_target)return 0;*out=(cinder_vk_target_desc){.width=64,.height=48,.color_format=color_format,.depth_format=depth_format,.samples=1};return 1;}
int cinder_vk_clear(uint32_t t,VkImageAspectFlags a,const float*c,const int*r){++native_calls;++clear_calls;last_aspects=a;last_clear_target=t;assert(t==expected_target&&!r&&c);printf("C %s %u %u %016llx\n",tag,t,a,(unsigned long long)hash(c,4*sizeof *c));return !fail_clear;}
int cinder_vk_program_ready(uint32_t p){++native_calls;return p!=0;}
int cinder_vk_target_ready(uint32_t p){++native_calls;return p!=0;}
void cinder_vk_screen_extent(int*w,int*h){++native_calls;*w=64;*h=48;}
uint64_t cinder_vk_error_epoch(void){return 0;}
int cinder_vk_error_pending(void){return 0;}
#endif
'''
BODY = r'''
static wpk_pool pool;
static wpk_batch batch;
static wpk_chunk chunk;
static wpk_scene scene;
static render_params params;
static uint32_t texture[4]={101,102,103,104},cube[1]={201},ao[4]={301,0,0,0};
static unsigned char warm[1],tex_warm[4],wet[4];
static mat4 identity;
static float eye[3]={0,0,0};
static void setup(void){
 memset(&scene,0,sizeof scene);memset(&params,0,sizeof params);memset(&pool,0,sizeof pool);memset(&chunk,0,sizeof chunk);memset(warm,0,sizeof warm);memset(tex_warm,0,sizeof tex_warm);
 identity=mat4_identity();pool.vbo=401;pool.ibo=402;pool.vao=403;batch=(wpk_batch){.tex=0,.pool=0,.count=6,.ioff=12,.gloss=0xffff,.cube=0xffff,.env=2,.spec=3,.power=.5f};
 chunk=(wpk_chunk){.lo={-.1f,-.1f,-.1f},.hi={.1f,.1f,.1f},.first=0,.n=1,.group=WPK_GROUND};
 scene.stride=24;scene.n_tex=4;scene.n_cube=1;scene.n_ao=4;scene.textures=texture;scene.cubes=cube;scene.ao_tex=ao;scene.tex_wet=wet;scene.pools=&pool;scene.n_pools=1;scene.batches=&batch;scene.n_batch=1;scene.chunks=&chunk;scene.n_chunk=1;scene.warm=warm;scene.tex_warm=tex_warm;
 params.fog_far=100;params.fog_near=10;params.range[0]=params.range[1]=params.range[2]=100;params.view=identity;
 for(int i=0;i<2;++i){progs[i].id=10+i;gloss_progs[i].id=20+i;}for(int i=0;i<6;++i)lit_progs[i].id=30+i;shadow_prog=40;white_tex=99;
 gs=(cinder_vk_pipeline){.depth_write=1,.depth_compare=VK_COMPARE_OP_LESS_OR_EQUAL,.asset_front=VK_FRONT_FACE_COUNTER_CLOCKWISE,.color_mask=15,.blend_op=VK_BLEND_OP_ADD,.stencil_compare_mask=255,.stencil_write_mask=255};
#ifdef WMMT_NATIVE_VK
 native_scene=(native_scene_view){17,64,48};native_frame_texture=66;native_over_texture=55;
#endif
 render_begin(&params);render_blend_pass(0);
}
static void scenes(void){
 const char*names[]={"opaque","cutout","alpha","additive","double-sided","sky","FF","car","glass","preview-overlay"};
 for(int k=0;k<10;++k){tag=names[k];setup();int pass=k==1?WPK_CUTOUT:(k==2||k==3||k==8||k==9)?WPK_BLEND:WPK_OPAQUE;
  batch.cutout=k==1;batch.flags=(pass==WPK_BLEND)?(k==3?2:1):0;scene.two_sided=k==4||k==5;scene.solid=k==5;
  if(k>=6&&k<=8){scene.lit=1;scene.stride=32;batch.prog=k-6;}params.no_depth_test=k==9;
#ifndef WMMT_NATIVE_VK
  if(k==9)glDisable(GL_DEPTH_TEST);
#endif
  render_blend_pass(pass==WPK_BLEND);wpk_draw(&scene,&identity,&identity,eye,pass,&params);
 }
 tag="shadow";setup();chunk.group=WPK_SHADOW;const wpk_scene*s[1]={&scene};render_shadows(s,&identity,1,&params);
 tag="overhead";setup();over.state=1;over.prog=41;over.fbo=expected_target=17;over.tex=204;over.depth=205;
 chunk.lo[1]=batch.lo[1]=14;chunk.hi[1]=batch.hi[1]=80;batch.lo[0]=chunk.lo[0]=-30;batch.hi[0]=chunk.hi[0]=30;batch.lo[2]=chunk.lo[2]=10;batch.hi[2]=chunk.hi[2]=50;
 assert(render_overhead(s,1,&identity,&params)==1);
 tag="backmirror";setup();bm.w=200;bm.tex=401;render_backmirror_draw(&identity,0,0,10,5);
 tag="sprites";setup();render_vertex v[4]={0};render_sprites(&identity,v,1,17,&params);
 tag="add-color";setup();render_sprites_by_colour(&identity,v,1,17,&params);
 tag="tracks";setup();render_tire_tracks(&identity,v,1,17,&params);
 tag="tail";setup();tail_render.program.id=10;tail_render.vao=403;tail_render.vbo=401;TailTrailVertex tail[3]={0};for(int i=0;i<3;++i)tail[i].rgba[3]=.5f;assert(render_tail_triangles(&identity,tail,3,&params));
 tag="HQ";setup();memset(&hq,0,sizeof hq);blur.w=64;blur.h=48;blur.tex=101;hq.on=hq.msrt=1;hq.bloom=.2f;hq.down_prog[0]=41;hq.down_prog[1]=42;hq.up_prog=43;
 for(int i=0;i<4;++i){hq.w[i]=32>>i;hq.h[i]=24>>i;hq.fbo[i]=51+i;hq.tex[i]=61+i;}assert(hq_resolve_bloom());
#ifdef WMMT_NATIVE_VK
 tag="warm";setup();native_warm_view=native_scene;assert(native_warm_material(&scene,&batch,texture[0],&params));
 tag="warm-double-sided";scene.two_sided=1;assert(native_warm_material(&scene,&batch,texture[0],&params));
 tag="warm-blend";batch.flags=1;assert(native_warm_material(&scene,&batch,texture[0],&params));
 tag="warm-overlay";params.no_depth_test=1;assert(native_warm_material(&scene,&batch,texture[0],&params));
 tag="warm-cube";assert(native_warm_cube(41,201,(float[9]){0},9*sizeof(float)));
 tag="loader";assert(native_loader_triangle(41,101,native_scene,401,402,1));
 tag="post";native_post_pass pp={.program=41,.target=17,.texture=101,.w=64,.h=48,.filter=VK_FILTER_LINEAR};assert(native_hq_pass(&pp));
 tag="post-add";pp.additive=1;assert(native_hq_pass(&pp));
 tag="composite";hq.on=0;blur.w=64;blur.h=48;blur.out_w=64;blur.out_h=48;blur.tex=101;blur.screen=17;blur_progs[0]=41;blur_progs[1]=42;assert(native_final_composite((float[40]){0},40*sizeof(float),(uint16_t[12]){0},0));
#endif
 printf("COUNTS %u %u %u\n",gl_calls,native_calls,draws);
}
#ifdef WMMT_NATIVE_VK
static void failure_cleanup(void){
 tag="failure-cleanup";setup();unsigned gi=gl_calls;
 tail_render.program.id=10;tail_render.vao=403;tail_render.vbo=401;render_tail_release();
 assert(render_init()==-1); /* actual catalog-create failure + release path */
 assert(over_init()==-1); /* actual optional program-create failure */
 assert(gl_calls==gi);
 puts("PASS actual native render_init/tail-release/overhead-create failure cleanup makes zero GL calls");
}
#endif
#ifdef HAS_DEPTH_HELPER
static void depth_clear(void){
 float bg[4]={.1f,.2f,.3f,.4f};
 VkFormat formats[]={VK_FORMAT_D16_UNORM,VK_FORMAT_D24_UNORM_S8_UINT,VK_FORMAT_D32_SFLOAT,VK_FORMAT_S8_UINT,VK_FORMAT_UNDEFINED,VK_FORMAT_D16_UNORM_S8_UINT,VK_FORMAT_D32_SFLOAT_S8_UINT};
 for(unsigned i=0;i<sizeof formats/sizeof*formats;++i){
  memcpy(native_post_clear_color,bg,sizeof bg);native_scene=(native_scene_view){17,64,48};expected_target=17;depth_format=formats[i];frame_history_valid=frame_recording_trusted=1;unsigned before=clear_calls,gi=gl_calls,ni=info_calls;
  tag="depth-only";render_scene_depth_clear();assert(info_calls==ni+1&&gl_calls==gi&&!memcmp(native_post_clear_color,bg,sizeof bg));
  assert(native_scene.target==17&&native_scene.w==64&&native_scene.h==48&&frame_recording_trusted&&frame_history_valid);
  assert(clear_calls==before+(formats[i]!=VK_FORMAT_S8_UINT&&formats[i]!=VK_FORMAT_UNDEFINED));
  if(clear_calls!=before)assert(last_aspects==VK_IMAGE_ASPECT_DEPTH_BIT&&last_clear_target==17);
 }
 depth_format=VK_FORMAT_D16_UNORM;tag="depth-default";native_scene.target=expected_target=0;render_scene_depth_clear();
 native_scene.target=expected_target=17;
 for(int k=0;k<3;++k){frame_history_valid=frame_recording_trusted=1;fail_info=k==0;missing_target=k==1;fail_clear=k==2;unsigned before=clear_calls,gi=gl_calls;tag="depth-failure";render_scene_depth_clear();assert(!frame_history_valid&&!frame_recording_trusted&&gl_calls==gi&&!memcmp(native_post_clear_color,bg,sizeof bg));assert(clear_calls==before+(k==2));}
 fail_info=missing_target=fail_clear=0;
 tag="main-clear";frame_recording_trusted=1;frame_history_valid=1;depth_format=VK_FORMAT_D24_UNORM_S8_UINT;render_scene_clear(.8f,.7f,.6f,1);assert(native_post_clear_color[0]==.8f&&frame_history_valid&&frame_recording_trusted&&last_aspects==(VK_IMAGE_ASPECT_COLOR_BIT|VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT));
 tag="display-clear";expected_target=0;
 for(unsigned i=0;i<sizeof formats/sizeof*formats;++i){depth_format=formats[i];unsigned gi=gl_calls,ni=info_calls;render_display_clear(.2f,.3f,.4f,1);VkImageAspectFlags a=VK_IMAGE_ASPECT_COLOR_BIT;if(formats[i]!=VK_FORMAT_S8_UINT&&formats[i]!=VK_FORMAT_UNDEFINED)a|=VK_IMAGE_ASPECT_DEPTH_BIT;assert(last_aspects==a&&last_clear_target==0&&native_scene.target==17&&gl_calls==gi&&info_calls==ni+1&&frame_history_valid&&frame_recording_trusted&&native_post_clear_color[0]==.2f);}
 color_format=VK_FORMAT_UNDEFINED;depth_format=VK_FORMAT_D16_UNORM;render_display_clear(1,0,0,1);assert(last_aspects==VK_IMAGE_ASPECT_DEPTH_BIT);
 depth_format=VK_FORMAT_S8_UINT;unsigned before=clear_calls;render_display_clear(1,0,0,1);assert(clear_calls==before&&frame_history_valid&&frame_recording_trusted);color_format=VK_FORMAT_R8G8B8A8_UNORM;
 for(int k=0;k<3;++k){frame_history_valid=frame_recording_trusted=1;fail_info=k==0;missing_target=k==1;fail_clear=k==2;before=clear_calls;unsigned gi=gl_calls;render_display_clear(0,1,0,1);assert(!frame_history_valid&&!frame_recording_trusted&&gl_calls==gi&&native_scene.target==17&&clear_calls==before+(k==2));}fail_info=missing_target=fail_clear=0;
 puts("PASS display default-target actual C/D only, never S; no-depth/color-depth/stencil-only, metadata/missing/record failure invalidates trust/history; scene clear retains actual stencil");
 puts("PASS depth-only D16/D24S8/D32/S8/noDepth/D16S8/D32S8/default/missing/info-failure/record-failure: no stale history, no background mutation");
}
#endif
int main(void){scenes();
#ifdef WMMT_NATIVE_VK
 failure_cleanup();
#endif
#ifdef HAS_DEPTH_HELPER
 depth_clear();
#endif
 return 0;}
'''

def run():
    with tempfile.TemporaryDirectory(prefix='native-render-state-', dir=OUT) as temp:
        temp=Path(temp)
        # Isolate Khronos headers so adding the NDK sysroot cannot replace host libc.
        for sub in ['GLES2', 'KHR']:
            shutil.copytree(SYS / sub, temp / 'include' / sub)
        all_sources=SOURCE+'\n'+'\n'.join(p.read_text() for p in (ROOT/'src').glob('render_native_*.inc'))
        used=set(re.findall(r'\bgl[A-Z]\w*\s*(?=\()',all_sources))
        headers='\n'.join((temp/'include/GLES2'/n).read_text() for n in ['gl2.h','gl2ext.h'])
        custom=set(re.findall(r'\b(gl\w+)\([^;{}]*\)\s*\{',PRE))
        stubs=[]
        for result,name,args in re.findall(r'GL_APICALL\s+(.+?)\s*GL_APIENTRY\s+(gl\w+)\s*\(([^;]*?)\);',headers):
            if name not in used or name in custom: continue
            body='++gl_calls;'+('return 0;' if result.strip()!='void' else '')
            stubs.append(result+' '+name+'('+args+'){'+body+'}\n')
        api=(ROOT/'src/native_vk.h').read_text()
        custom_native=set(re.findall(r'\b(cinder_vk_\w+)\([^;{}]*\)\s*\{',POST_INIT))|{'cinder_vk_draw_init'}
        for result,name,args in re.findall(r'(?m)^([\w ]+?)\s+(cinder_vk_\w+)\(([^;]*?)\);',api):
            if name in custom_native: continue
            body='++native_calls;'+('return 0;' if result.strip()!='void' else '')
            stubs.append('#ifdef WMMT_NATIVE_VK\n'+result+' '+name+'('+args+'){'+body+'}\n#endif\n')
        init_source=(ROOT/'src/native_vk.inc').read_text()
        init=function(init_source,'native_program_valid')+function(init_source,'cinder_vk_draw_init')
        init_baseline=BASE.parent/'native_vk.inc'
        if init_baseline.exists():
            old=init_baseline.read_text()
            assert init==function(old,'native_program_valid')+function(old,'cinder_vk_draw_init'),'packet initializer changed outside renderer scope'
        results={}
        for label,source in [('baseline',BASELINE),('current',SOURCE)]:
            for mode in ['gles','native']:
                # Baseline owned includes come from the baseline when available;
                # missing historical includes are byte-identical immutable inputs.
                text=PRE+init+POST_INIT+'\n'+''.join(stubs)+'\n'+source+'\n'+BODY
                f=temp/(label+'-'+mode+'.c');f.write_text(text);exe=f.with_suffix('')
                cmd=[os.environ.get('CC','clang'),'-std=gnu11','-O1','-U__APPLE__','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function','-Wno-unused-variable','-Wno-missing-field-initializers','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(temp/'include'),'-I',str(ROOT/'src')]
                if sys.platform=='darwin':cmd+=['-I','/opt/homebrew/include']
                if label=='baseline':cmd[1:1]=['-I',str(BASE.parent)]
                if mode=='native':cmd+=['-DWMMT_NATIVE_VK','-DWMMT_VK','-include',str(ROOT/'src/native_vk.h')]
                if mode=='native' and 'void render_scene_depth_clear(' in (ROOT/'src/render_native_post.inc').read_text() and label=='current':cmd+=['-DHAS_DEPTH_HELPER']
                subprocess.run(cmd+[str(f),'-lm','-o',str(exe)],check=True,timeout=120)
                p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
                assert not p.returncode,(label,mode,p.returncode,p.stdout,p.stderr)
                results[label+'-'+mode]=p.stdout
        def packets(key):return [x for x in results[key].splitlines() if x.startswith(('P ','D '))]
        assert packets('baseline-native')==packets('current-native'),'native packet drift'
        assert packets('baseline-gles')==packets('current-gles'),'legacy state drift'
        gl_p=[x for x in packets('current-gles') if x.startswith('P ')]
        native_p=[x for x in packets('current-native') if x.startswith('P ')]
        assert gl_p==native_p[:len(gl_p)],(gl_p,native_p[:len(gl_p)])
        counts={k:[int(v) for v in next(x for x in out.splitlines() if x.startswith('COUNTS ')).split()[1:]] for k,out in results.items()}
        assert counts['baseline-gles']==counts['current-gles']==[1083,0,26]
        assert counts['baseline-native']==[177,366,35]
        assert len(gl_p)==26 and len(packets('current-native'))==70
        state_events={k:[x for x in out.split('COUNTS ')[0].splitlines() if x.startswith('G ')] for k,out in results.items()}
        assert {x.split()[2] for x in state_events['baseline-native']}=={'ActiveTexture','CullFace','DepthFunc','DepthMask','Disable','Enable','FrontFace'}
        assert state_events['baseline-gles']==state_events['current-gles']
        # A baseline-only run before implementation is deliberately supported.
        if 'void render_scene_depth_clear(' in (ROOT/'src/render_native_post.inc').read_text():
            assert counts['current-native']==[0,366,35] and not state_events['current-native'],counts
        else: assert counts['current-native']==counts['baseline-native']
        included={}
        for name in sorted(set(re.findall(r'#include "(render_native_[^"]+)"',SOURCE))):
            historical=BASE.parent/name
            baseline_path=historical if historical.exists() else ROOT/'src'/name
            included[name]={'baseline_path':str(baseline_path),'baseline_sha256':hashlib.sha256(baseline_path.read_bytes()).hexdigest(),'current_sha256':hashlib.sha256((ROOT/'src'/name).read_bytes()).hexdigest(),'historical_snapshot':historical.exists()}
        report={'authority':'complete renderer TU/API recorders + actual packet initializer, UBSan; no GPU/pixels','baseline':str(BASE),'baseline_sha256':hashlib.sha256(BASELINE.encode()).hexdigest(),'current_sha256':hashlib.sha256(SOURCE.encode()).hexdigest(),'initializer_sha256':hashlib.sha256(init.encode()).hexdigest(),'includes':included,'counts':counts,'native_packet_records':len(packets('current-native')),'GL_native_matching_state_records':len(gl_p),'state_events':state_events,'outputs':results}
        (OUT/'render-state-results.json').write_text(json.dumps(report,indent=2)+'\n')
        print('PASS complete renderer baseline/current native packet bytes + bounded CPU span hashes; legacy/current actual GL state; GL/native state records:',len(gl_p))
        print('actual call counts (GL/native/draws):',counts)
        for line in results['current-native'].splitlines():
            if line.startswith('PASS '):print(line)

if __name__=='__main__': run()
