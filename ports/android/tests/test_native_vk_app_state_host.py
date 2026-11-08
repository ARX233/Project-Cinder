#!/usr/bin/env python3
"""ROUND7 actual app functions/fragments, narrow state-routing/log recorders.
No Game/GL context or GPU model. Renderer clear/packet implementations are tested
separately by their owner; this fixture verifies actual app calls and arguments.
All generated files require CINDER_TEST_OUT or TMPDIR on external CodexWork APFS.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
selected_out = os.environ.get('CINDER_TEST_OUT') or os.environ.get('TMPDIR')
if not selected_out:
    raise SystemExit('set CINDER_TEST_OUT or TMPDIR to an external /Volumes/CodexWork directory')
OUT_ROOT = Path(selected_out).expanduser().resolve()
if not (str(OUT_ROOT) == '/Volumes/CodexWork' or str(OUT_ROOT).startswith('/Volumes/CodexWork/')):
    raise SystemExit('CINDER_TEST_OUT/TMPDIR must be on /Volumes/CodexWork')
OUT_ROOT.mkdir(parents=True, exist_ok=True)
OUT = OUT_ROOT / 'round7-app-state'
OUT.mkdir(parents=True, exist_ok=True)
BASELINE = Path(os.environ.get('CINDER_APP_BASELINE', str(ROOT / '../round7-baseline/src/app.c'))).resolve()
APP_BYTES = (ROOT / 'src/app.c').read_bytes()
BASE_BYTES = BASELINE.read_bytes()
APP, BASE = APP_BYTES.decode(), BASE_BYTES.decode()
SELF_BYTES = Path(__file__).read_bytes()
fragments = []


def span(text, start, end, label, baseline=False, include_end=False):
    a = text.index(start)
    b = text.index(end, a) + (len(end) if include_end else 0)
    result = text[a:b]
    fragments.append({'label': label, 'baseline': baseline, 'start_line': text.count('\n', 0, a) + 1,
                      'end_line': text.count('\n', 0, max(a, b - 1)) + 1,
                      'start_byte': len(text[:a].encode()), 'end_byte': len(text[:b].encode()),
                      'sha256': hashlib.sha256(result.encode()).hexdigest()})
    return result


def function(text, anchor, label, baseline=False):
    a = text.index(anchor)
    ending = re.search(r'^}\s*$', text[a:], re.M)
    assert ending, anchor
    b = a + ending.end()
    result = text[a:b].rstrip() + '\n'
    fragments.append({'label': label, 'baseline': baseline, 'start_line': text.count('\n', 0, a) + 1,
                      'end_line': text.count('\n', 0, max(a, b - 1)) + 1,
                      'start_byte': len(text[:a].encode()), 'end_byte': len(text[:b].encode()),
                      'sha256': hashlib.sha256(text[a:b].encode()).hexdigest(),
                      'compiled_body_sha256': hashlib.sha256(result.encode()).hexdigest()})
    return result


def depth_sites(text, baseline=False):
    if baseline:
        pattern = r'^[ \t]*glClear\(GL_DEPTH_BUFFER_BIT\);[ \t]*$'
    else:
        pattern = r'#ifdef WMMT_NATIVE_VK\n[ \t]*render_scene_depth_clear\(\);\n#else\n[ \t]*glClear\(GL_DEPTH_BUFFER_BIT\);\n#endif'
    matches = list(re.finditer(pattern, text, re.M))
    assert len(matches) == 4, ('four scoped depth-clear sites expected', len(matches))
    wrappers = []
    for i, match in enumerate(matches):
        result = match.group()
        fragments.append({'label': 'depth-site-' + str(i), 'baseline': baseline,
                          'start_line': text.count('\n', 0, match.start()) + 1,
                          'end_line': text.count('\n', 0, match.end()) + 1,
                          'start_byte': len(text[:match.start()].encode()), 'end_byte': len(text[:match.end()].encode()),
                          'sha256': hashlib.sha256(result.encode()).hexdigest()})
        wrappers.append('static void depth_site_' + str(i) + '(void){\n' + result + '\n}\n')
    return ''.join(wrappers)


def production(text, baseline=False):
    value = function(text, 'static void mini_draw(void *ctx, float fade) {', 'whole-mini', baseline)
    value += function(text, 'static void menu_present(double frame_start) {', 'whole-menu-present', baseline)
    value += function(text, 'static void backfire_draw(const mat4 *vp, const float *eye, int movie, const car_state *c) {', 'whole-backfire', baseline)
    value += depth_sites(text, baseline)
    race = span(text, '  int blurred = render_blur_begin(', "  /* the arcade's own camera:", 'race-target-clear', baseline)
    value += 'static void race_setup(const car_state*c){\n' + race + '\n(void)blurred;\n}\n'
    perf = span(text, '  static int gpu_sampled = -1000;', '  if (G.paused && !G.vs_closed)', 'perf-sample', baseline)
    value += 'static void perf_sample(float dt,double t1,const car_state*c){\n' + perf + '}\n'
    diag = span(text, '  static int frame;\n  if (frame < 10 || frame % 150 == 0)', '  frame++;', 'frame-diagnostic', baseline, True)
    value += 'static void frame_diagnostic(float dt,const car_state*c){\n' + diag + '}\n'
    if baseline:
        version = span(text, '  fprintf(stderr, "GL %s | %s', '  return 0;\n}', 'menu-ready-log', True)
        hud = span(text, '    glBlendEquation(GL_FUNC_ADD);', '    junction_ui_draw(&race_junction_ui);', 'hud-blend-tail', True, True)
        display = ''  # No new renderer API is called by the old app branch.
    else:
        version = span(text, '#ifdef WMMT_NATIVE_VK\n  uint32_t api_version', '  return 0;\n}', 'menu-ready-log')
        hud = span(text, '#ifndef WMMT_NATIVE_VK\n    glBlendEquation(GL_FUNC_ADD);', '    junction_ui_draw(&race_junction_ui);', 'hud-blend-tail', False, True)
        display = span(text, '#ifdef WMMT_NATIVE_VK\n  render_display_begin(G.fb_w, G.fb_h);', '#endif', 'display-begin', False, True)
    value += 'static void ready_log(void){\n' + version + '}\n'
    value += 'static void hud_tail(void){\n' + hud + '}\n'
    value += 'static void display_start(void){\n' + display + '\n}\n'
    return value


CURRENT = production(APP)
REFERENCE = production(BASE, True)
prefix = r'''
#include <assert.h>
#include <math.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define CAR_RIVALS 2
#define WPK_PASSES 3
#define WPK_BLEND 2
#define MINI_OBJECTS 8
#define MINI_MAP 0
#define MINI_COURSE 1
#define MINI_FRAMES 2
#define MINI_MOVE 8
#define MINI_VS_CARDS 1
#define MINI_TEN_CARDS 1
#define MINI_TA_CARDS 1
#define MENU_TEN_COURSE 2
#define MENU_VS_AREA 3
#define C 1
#define D 2
#define S 4
typedef struct {float m[16];}mat4;
typedef struct {int n_batch;unsigned n_tex,n_chunk;}wpk_scene;
typedef struct {int sel,screen;struct{int item;}vs;int sharp_on;}menu_state;
typedef struct {int token;}menu_scene;
typedef struct {float fog_far,fog_near,fog_color[3],range[3],uv_shift[2];const unsigned char*object_visible;int n_objects,no_depth_test,draws,triangles,new_chunks;}render_params;
typedef struct {int on,macula,gradation,runlight;float eye[3],at[3],uv[2],run[2][3];}mini_course;
static const mini_course MINI_VS[1]={{1,2,3,4,{1,2,3},{4,5,6},{.25f,.5f},{{1,2,3},{4,5,6}}}};
static const mini_course MINI_TEN[1]={{1,2,3,4,{2,3,4},{5,6,7},{.25f,.5f},{{1,2,3},{4,5,6}}}};
static const mini_course MINI_TA[1]={{1,2,3,4,{3,4,5},{6,7,8},{.25f,.5f},{{1,2,3},{4,5,6}}}};
typedef struct {float body[16],rival_body[CAR_RIVALS][16];int rival_shown[CAR_RIVALS];float pos[3],cam_pos[3],cam_blur;int n_traffic;}car_state;
static struct {int fb_w,fb_h,phone,camera,loader,race_frames,over_draws,sharp_rest;float edge,race_time;menu_state menu;struct{float screen_w,screen_h;}hud;wpk_scene mini,track;const mini_course*mini_shown;float mini_from[2][3];int mini_move,mini_frame;unsigned char mini_visible[MINI_OBJECTS];render_params rp;wpk_scene*rival_model[CAR_RIVALS];FILE*perf;}G;
static int race_junction_ui;
static int backfire_ready,has3d,photo_bg,wide_drawn,blur_active,finish_ok;
static unsigned clear_calls,menu_calls,wide_calls,load_calls,begin_calls,blend_calls,wpk_calls,finish_calls,error_reads,epoch_reads,pending_reads,device_reads,api_reads,viewport_calls,blend_restores,hud_calls;
static uint64_t native_epoch;
static int native_pending;
static const char*device_name;
static uint32_t device_api;
static unsigned old_gl_error;
static int old_binding,old_view_w,old_view_h,legacy_depth=1,selected_target,selected_w,selected_h,display_w,display_h;
static float framebuffer_colour[4],background_colour[4],depth_value;static int stencil_value;
static char norm[16384],raw[16384],logs[32768];static size_t nn,nr,nl;
static double clock_ms;
static void append(char*b,size_t*n,size_t cap,const char*fmt,...){va_list a;va_start(a,fmt);int k=vsnprintf(b+*n,cap-*n,fmt,a);va_end(a);assert(k>=0&&(size_t)k<cap-*n);*n+=(size_t)k;}
static int test_fprintf(FILE*file,const char*fmt,...){(void)file;va_list a;va_start(a,fmt);int k=vsnprintf(logs+nl,sizeof logs-nl,fmt,a);va_end(a);assert(k>=0&&(size_t)k<sizeof logs-nl);nl+=(size_t)k;return k;}
#define fprintf test_fprintf
static mat4 mat4_identity(void){mat4 m={{0}};m.m[0]=m.m[5]=m.m[10]=m.m[15]=1;return m;}
static mat4 mat4_mul(mat4 a,mat4 b){mat4 c={{0}};for(int i=0;i<4;++i)for(int j=0;j<4;++j)for(int k=0;k<4;++k)c.m[4*i+j]+=a.m[4*i+k]*b.m[4*k+j];return c;}
static mat4 mat4_perspective(float f,float a,float n,float z){assert(isfinite(f)&&a>0&&n>0&&z>n);return mat4_identity();}
static mat4 mat4_look_at(const float*e,const float*a,const float*u){assert(e&&a&&u);return mat4_identity();}
static void eye_in(const mat4*m,const float*p,float*out){assert(m);memcpy(out,p,3*sizeof(float));}
static void record_clear(int target,int w,int h,int mask,const float*colour){++clear_calls;if(mask&C){assert(colour);memcpy(framebuffer_colour,colour,4*sizeof(float));}if(mask&D)depth_value=1;if(mask&S)stencil_value=0;append(norm,&nn,sizeof norm,"clear:%d:%dx%d:%d;",target,w,h,mask);}
static void render_display_begin(int w,int h){display_w=selected_w=w;display_h=selected_h=h;selected_target=0;}
static void render_display_clear(float r,float g,float b,float a){float colour[4]={r,g,b,a};record_clear(0,display_w,display_h,C|D,colour);}
static void render_scene_clear(float r,float g,float b,float a){float colour[4]={r,g,b,a};memcpy(background_colour,colour,sizeof colour);record_clear(selected_target,selected_w,selected_h,C|D|S,colour);}
static void render_scene_depth_clear(void){record_clear(selected_target,selected_w,selected_h,D,NULL);}
static int render_blur_begin(float amount,int w,int h){append(norm,&nn,sizeof norm,"blur:%.2f:%dx%d;",amount,w,h);selected_target=blur_active?42:0;selected_w=blur_active?w/2:w;selected_h=blur_active?h/2:h;
#ifndef WMMT_NATIVE_VK
 old_binding=selected_target;
#endif
 return blur_active;}
static void render_blur_size(int*w,int*h){*w=selected_w;*h=selected_h;}
static void render_begin(const render_params*p){++begin_calls;append(norm,&nn,sizeof norm,"begin:%d;",p->no_depth_test);
#ifndef WMMT_NATIVE_VK
 legacy_depth=1;
#endif
}
static void render_blend_pass(int on){++blend_calls;append(norm,&nn,sizeof norm,"blend:%d;",on);}
static void wpk_draw(wpk_scene*s,const mat4*vp,const mat4*m,const float*eye,int pass,render_params*p){assert(s&&vp&&m&&eye);++wpk_calls;unsigned mask=0;for(int i=0;p->object_visible&&i<p->n_objects;++i)if(p->object_visible[i])mask|=1u<<i;
#ifdef WMMT_NATIVE_VK
 int depth=!p->no_depth_test;
#else
 int depth=legacy_depth;
#endif
 append(norm,&nn,sizeof norm,"draw:%d:dep%d:vis%u:uv%.2f;",pass,depth,mask,p->uv_shift[0]);++p->draws;p->triangles+=2;++p->new_chunks;}
static void backfire_draw_car(int slot,const float*body,const mat4*vp,const float*eye,render_params*p){assert(body&&vp&&eye&&!p->object_visible&&!p->n_objects&&p->range[0]==1e9f&&p->range[1]==1e9f&&p->range[2]==1e9f);append(norm,&nn,sizeof norm,"backfire:%d:dep%d;",slot,p->no_depth_test);++p->draws;p->triangles+=2;++p->new_chunks;}
static void menu_draw3d(void*ctx){assert(ctx);}
static void mini_draw(void*ctx,float fade);
static int menu_scene3d(const menu_state*m,menu_scene*s){assert(m==&G.menu);s->token=3;return has3d;}
static void menu_draw(const menu_state*m,float w,float h,void(*draw3d)(void*),void*ctx,void(*mini)(void*,float)){assert(m==&G.menu&&w==G.hud.screen_w&&h==G.hud.screen_h&&ctx&&mini==mini_draw);++menu_calls;append(norm,&nn,sizeof norm,"menu:%d;",draw3d!=NULL);}
static int menu_photo_bg(void){return photo_bg;}
static int anm_wide_drawn(void){return wide_drawn;}
static void wide_sides(void){++wide_calls;append(norm,&nn,sizeof norm,"wide;");}
static void load_step(double start){++load_calls;append(norm,&nn,sizeof norm,"load:%.1f;",start);}
static void junction_ui_draw(int*p){assert(p==&race_junction_ui);++hud_calls;append(norm,&nn,sizeof norm,"hud;");}
static double now_ms(void){clock_ms+=1;return clock_ms;}
static float car_kmh(const car_state*c){assert(c);return 72;}
static int cinder_vk_finish(void){++finish_calls;return finish_ok;}
static uint64_t cinder_vk_error_epoch(void){++epoch_reads;return native_epoch;}
static int cinder_vk_error_pending(void){++pending_reads;return native_pending;}
static const char*cinder_vk_device_name(void){++device_reads;return device_name;}
static uint32_t cinder_vk_device_api_version(void){++api_reads;return device_api;}
#ifdef WMMT_NATIVE_VK
#pragma GCC poison glClear glClearColor glViewport glDepthMask glEnable glDisable glBlendFunc glBlendEquation glGetError glGetString glFinish glFlush glGetIntegerv glBindFramebuffer vkgl_glClear vkgl_glClearColor vkgl_glViewport vkgl_glDepthMask vkgl_glEnable vkgl_glDisable vkgl_glBlendFunc vkgl_glBlendEquation vkgl_glGetError vkgl_glGetString vkgl_glFinish vkgl_glFlush vkgl_glGetIntegerv vkgl_glBindFramebuffer
#else
#define GL_COLOR_BUFFER_BIT C
#define GL_DEPTH_BUFFER_BIT D
#define GL_STENCIL_BUFFER_BIT S
#define GL_TRUE 1
#define GL_DEPTH_TEST 1
#define GL_SRC_ALPHA 2
#define GL_ONE_MINUS_SRC_ALPHA 3
#define GL_FUNC_ADD 4
#define GL_RENDERER 5
#define GL_VERSION 6
static float gl_clear_colour[4];
static void glViewport(int x,int y,int w,int h){assert(!x&&!y);++viewport_calls;old_view_w=w;old_view_h=h;append(raw,&nr,sizeof raw,"view:%dx%d;",w,h);}
static void glClearColor(float r,float g,float b,float a){gl_clear_colour[0]=r;gl_clear_colour[1]=g;gl_clear_colour[2]=b;gl_clear_colour[3]=a;memcpy(background_colour,gl_clear_colour,sizeof gl_clear_colour);append(raw,&nr,sizeof raw,"colour:%.2f:%.2f:%.2f:%.2f;",r,g,b,a);}
static void glClear(int mask){append(raw,&nr,sizeof raw,"clear:%d;",mask);record_clear(old_binding,old_view_w,old_view_h,mask,gl_clear_colour);}
static void glDepthMask(int on){assert(on==GL_TRUE);append(raw,&nr,sizeof raw,"depthmask;");}
static void glDisable(int what){assert(what==GL_DEPTH_TEST);legacy_depth=0;append(raw,&nr,sizeof raw,"dep0;");}
static void glEnable(int what){assert(what==GL_DEPTH_TEST);legacy_depth=1;append(raw,&nr,sizeof raw,"dep1;");}
static void glBlendFunc(int s,int d){assert(s==GL_SRC_ALPHA&&d==GL_ONE_MINUS_SRC_ALPHA);++blend_restores;append(raw,&nr,sizeof raw,"blendrestore;");}
static void glBlendEquation(int what){assert(what==GL_FUNC_ADD);append(raw,&nr,sizeof raw,"equationadd;");}
static void glFinish(void){++finish_calls;}
static unsigned glGetError(void){++error_reads;unsigned old=old_gl_error;old_gl_error=0;return old;}
static const unsigned char*glGetString(int what){return(const unsigned char*)(what==GL_RENDERER?"legacy-device":"legacy-version");}
#endif
'''

tests = r'''
static void reset(void){memset(&G,0,sizeof G);G.fb_w=800;G.fb_h=600;G.hud.screen_w=640;G.hud.screen_h=480;G.mini.n_batch=1;G.track.n_tex=7;G.track.n_batch=11;G.track.n_chunk=13;G.rp.fog_color[0]=.1f;G.rp.fog_color[1]=.2f;G.rp.fog_color[2]=.3f;G.rp.range[0]=8;G.rp.range[1]=9;G.rp.range[2]=10;G.rp.object_visible=G.mini_visible;G.rp.n_objects=MINI_OBJECTS;G.rp.draws=4;G.rp.triangles=5;G.rp.new_chunks=6;backfire_ready=has3d=photo_bg=wide_drawn=blur_active=0;finish_ok=1;clear_calls=menu_calls=wide_calls=load_calls=begin_calls=blend_calls=wpk_calls=finish_calls=error_reads=epoch_reads=pending_reads=device_reads=api_reads=viewport_calls=blend_restores=hud_calls=0;native_epoch=UINT64_C(0x123456789abcdef0);native_pending=1;device_name="fixture-device";device_api=VK_MAKE_VERSION(1,2,3);old_gl_error=0x0502;old_binding=selected_target=0;old_view_w=selected_w=display_w=800;old_view_h=selected_h=display_h=600;legacy_depth=1;for(int i=0;i<4;++i)framebuffer_colour[i]=background_colour[i]=.75f;depth_value=.3f;stencil_value=23;nn=nr=nl=0;norm[0]=raw[0]=logs[0]=0;clock_ms=100;}
static void gold(const char*name){printf("GOLD %s %s\n",name,norm);
#ifndef WMMT_NATIVE_VK
 printf("RAW %s %s\n",name,raw);
#endif
}
static void legacy_log(const char*name){printf("LEGACY_%s ",name);for(size_t i=0;i<nl;++i)printf("%02x",(unsigned char)logs[i]);puts("");}
static void menu_cases(void){for(int flags=0;flags<16;++flags){reset();has3d=flags&1;G.edge=(flags&2)?5:0;photo_bg=flags&4;G.loader=flags&8;display_start();menu_present(3.5);assert(clear_calls==1&&menu_calls==1&&load_calls==!G.loader&&wide_calls==(G.edge>0&&!photo_bg)&&framebuffer_colour[0]==0&&framebuffer_colour[3]==1&&depth_value==1&&stencil_value==23);char label[32];snprintf(label,sizeof label,"menu%d",flags);gold(label);}
#ifdef WMMT_NATIVE_VK
 reset();old_binding=77;old_view_w=3;old_view_h=9;display_start();menu_present(1);assert(strstr(norm,"clear:0:800x600:3;")&&!viewport_calls&&old_binding==77&&old_view_w==3&&old_view_h==9);
#endif
 puts("PASS actual menu_present: display colour+depth only, no stencil, preserved callback/loading/side conditions; native routing ignores poisoned old binding/viewport");}
static void depth_cases(void){void(*sites[])(void)={depth_site_0,depth_site_1,depth_site_2,depth_site_3};for(int target=0;target<3;++target)for(int i=0;i<4;++i){reset();selected_target=old_binding=target==0?0:target==1?42:91;selected_w=old_view_w=target==2?200:400;selected_h=old_view_h=target==2?72:300;
#ifdef WMMT_NATIVE_VK
 old_binding=777;old_view_w=3;old_view_h=9;
#endif
 float before[4],bg[4];memcpy(before,framebuffer_colour,sizeof before);memcpy(bg,background_colour,sizeof bg);sites[i]();assert(clear_calls==1&&depth_value==1&&stencil_value==23&&!memcmp(before,framebuffer_colour,sizeof before)&&!memcmp(bg,background_colour,sizeof bg));char label[32];snprintf(label,sizeof label,"depth%d-%d",target,i);gold(label);}puts("PASS four actual depth-site fragments: current display/blur/backmirror target and extent, depth-only with colour/stencil/background untouched");}
static void race_cases(void){car_state c={.cam_blur=.5f};for(int on=0;on<2;++on){reset();blur_active=on;display_start();race_setup(&c);assert(clear_calls==1&&stencil_value==0&&depth_value==1&&framebuffer_colour[0]==.1f&&framebuffer_colour[1]==.2f&&framebuffer_colour[2]==.3f&&background_colour[0]==.1f);char label[20];snprintf(label,sizeof label,"race%d",on);gold(label);
#ifdef WMMT_NATIVE_VK
 assert(!viewport_calls);
#else
 assert(viewport_calls==1);
#endif
 }puts("PASS actual race target/clear fragment: blur/current-target extent route precedes colour+depth+stencil clear; native does not read or set legacy viewport");}
static void mini_cases(void){for(int screen=1;screen<=3;++screen){reset();G.menu.screen=screen;G.mini_frame=1;mini_draw(&G.menu,.5f);assert(clear_calls==1&&wpk_calls==5&&begin_calls==1&&depth_value==1&&stencil_value==23);assert(strstr(norm,"draw:0:dep1:")&&strstr(norm,"draw:2:dep0:vis8:uv0.50;")&&strstr(norm,"draw:2:dep0:vis16:uv0.00;"));render_params ordinary={0};render_begin(&ordinary);mat4 id=mat4_identity();float eye[3]={0};wpk_draw(&G.mini,&id,&id,eye,0,&ordinary);assert(!ordinary.no_depth_test&&strstr(norm,"draw:0:dep1:vis0:uv0.00;"));char label[20];snprintf(label,sizeof label,"mini%d",screen);gold(label);}
 reset();G.mini.n_batch=0;mini_draw(&G.menu,1);assert(!clear_calls&&!wpk_calls);reset();G.menu.sel=-1;mini_draw(&G.menu,1);assert(!clear_calls&&!wpk_calls);puts("PASS whole mini_draw: three card routes, both no-depth overlays use local explicit rp override, fresh ordinary rp restores independent depth intent, early guards unchanged");}
static void backfire_cases(void){reset();mat4 vp=mat4_identity();float eye[3]={0};car_state c={0};backfire_draw(&vp,eye,0,&c);assert(!begin_calls);backfire_ready=1;backfire_draw(&vp,eye,1,&c);assert(!begin_calls);G.camera=0;c.rival_shown[0]=1;G.rival_model[0]=&G.track;backfire_draw(&vp,eye,0,&c);assert(begin_calls==2&&blend_calls==2&&G.rp.draws==6&&G.rp.triangles==9&&G.rp.new_chunks==8&&G.rp.n_objects==MINI_OBJECTS&&G.rp.range[0]==8&&!G.rp.no_depth_test);gold("backfire");hud_tail();assert(hud_calls==1);gold("hud");puts("PASS whole backfire_draw and HUD tail: explicit begin/blend-pass and private draw parameters preserve counters/caller rp; no native dependency on trailing GL blend/equation restore");}
static void diagnostics(void){reset();car_state c={.pos={1,2,3},.cam_pos={4,5,6},.n_traffic=7,.cam_blur=.25f};for(int i=0;i<12;++i)frame_diagnostic(.016f,&c);
#ifdef WMMT_NATIVE_VK
 assert(old_gl_error==0x0502&&!error_reads&&epoch_reads==10&&pending_reads==10&&strstr(logs,"native epoch 1311768467463790320 pending 1"));native_epoch=UINT64_MAX;for(int i=12;i<=150;++i)frame_diagnostic(.016f,&c);assert(epoch_reads==11&&pending_reads==11&&strstr(logs,"native epoch 18446744073709551615 pending 1"));native_epoch=42;native_pending=0;for(int i=151;i<=300;++i)frame_diagnostic(.016f,&c);assert(epoch_reads==12&&pending_reads==12&&strstr(logs,"native epoch 42 pending 0")&&old_gl_error==0x0502);
#else
 assert(old_gl_error==0&&error_reads==10);legacy_log("DIAG");
#endif
 reset();G.perf=(FILE*)(uintptr_t)1;finish_ok=0;G.race_frames=0;perf_sample(.04f,0,&c);
#ifdef WMMT_NATIVE_VK
 assert(finish_calls==1&&strstr(logs,"unavailable (completion unconfirmed)")&&!strstr(logs,"host sample:")&&!strstr(logs,"GPU"));
#endif
 nn=nr=nl=0;norm[0]=raw[0]=logs[0]=0;finish_ok=1;G.race_frames=300;perf_sample(.04f,0,&c);assert(finish_calls==2);
#ifdef WMMT_NATIVE_VK
 assert(strstr(logs,"native submit/wait host sample:")&&!strstr(logs,"gpu sample:")&&!strstr(logs,"the GPU"));
#else
 legacy_log("PERF");
#endif
 reset();ready_log();
#ifdef WMMT_NATIVE_VK
 assert(device_reads==1&&api_reads==1&&!error_reads&&strstr(logs,"native Vulkan fixture-device | 1.2.3")&&!strstr(logs,"GL legacy"));nl=0;logs[0]=0;device_api=0;device_name="unavailable";ready_log();assert(strstr(logs,"unavailable")&&strstr(logs,"0.0.0")&&device_reads==2&&api_reads==2&&old_gl_error==0x0502);
#else
 legacy_log("DEVICE");
#endif
 puts("PASS actual diagnostics fragments: native finish0 unavailable/finish1 host-submit-wait label, 64-bit non-consuming epoch/pending cadence and native device/unavailable version logging without GL queries");}
int main(void){menu_cases();depth_cases();race_cases();mini_cases();backfire_cases();diagnostics();return 0;}
'''

results = []
with tempfile.TemporaryDirectory(prefix='app-state-', dir=OUT) as work:
    work = Path(work)
    (work / 'tmp').mkdir()
    env = dict(os.environ, TMPDIR=str(work / 'tmp'), TMP=str(work / 'tmp'), TEMP=str(work / 'tmp'),
               PYTHONDONTWRITEBYTECODE='1', UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    include = ['-I', '/opt/homebrew/include'] if sys.platform == 'darwin' else []
    cc = os.environ.get('CC', 'clang')
    for name, body, defines in (
        ('native', CURRENT, ['-DWMMT_NATIVE_VK=1', '-DWMMT_VK=1']),
        ('gles', CURRENT, []), ('vkcompat', CURRENT, ['-DWMMT_VK=1']),
        ('baseline-gles', REFERENCE, []), ('baseline-vkcompat', REFERENCE, ['-DWMMT_VK=1'])):
        c = work / (name + '.c')
        c.write_text(prefix + body + tests)
        exe = work / name
        command = [cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-variable',
                   '-Wno-missing-field-initializers', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                   *include, *defines, str(c), '-lm', '-o', str(exe)]
        subprocess.run(command, env=env, check=True, timeout=120)
        p = subprocess.run([str(exe)], env=env, text=True, capture_output=True, timeout=30)
        (OUT / (name + '.log')).write_text(p.stdout + p.stderr)
        print(name, p.returncode)
        if p.returncode:
            print(p.stdout); print(p.stderr, file=sys.stderr)
        p.check_returncode()
        results.append({'name': name, 'exit_code': p.returncode, 'defines': defines,
                        'fixture_sha256': hashlib.sha256((prefix + body + tests).encode()).hexdigest(), 'stdout': p.stdout})
    goldens = {r['name']: [l for l in r['stdout'].splitlines() if l.startswith('GOLD ')] for r in results}
    assert all(lines == goldens['native'] for lines in goldens.values()), 'normalized actual routing/action goldens differ'
    legacy_logs = {r['name']: [l for l in r['stdout'].splitlines() if l.startswith(('LEGACY_', 'RAW '))] for r in results if r['name'] != 'native'}
    assert legacy_logs['gles'] == legacy_logs['vkcompat'] == legacy_logs['baseline-gles'] == legacy_logs['baseline-vkcompat']
    # Token controls cover all extracted complete functions/fragments after the
    # selected legacy preprocessing, not only regex presence/absence checks.
    token_controls = {}
    for mode, defs in (('gles', []), ('vkcompat', ['-DWMMT_VK=1'])):
        values = []
        for label, body in (('current', CURRENT), ('baseline', REFERENCE)):
            f = work / (label + '-' + mode + '-tokens.c')
            f.write_text(body)
            t = subprocess.run([cc, '-E', '-P', '-x', 'c', *defs, str(f)], env=env, check=True, text=True, capture_output=True, timeout=30).stdout
            # Added display_start is intentionally empty in legacy current/base.
            values.append(re.findall(r'\w+|[^\s]', t))
        assert values[0] == values[1], ('legacy fragment tokens changed', mode)
        token_controls[mode] = True
    print('PASS native/GLES/VKcompat/baseline normalized action controls; exact selected legacy tokens and diagnostic log controls')

report = {'status': 'pass', 'source_sha256': {'src/app.c': hashlib.sha256(APP_BYTES).hexdigest(),
          'tests/test_native_vk_app_state_host.py': hashlib.sha256(SELF_BYTES).hexdigest()},
          'baseline': {'path': str(BASELINE), 'sha256': hashlib.sha256(BASE_BYTES).hexdigest()},
          'output_root': str(OUT_ROOT), 'fragments': fragments, 'results': results,
          'golden_cases_per_mode': len(goldens['native']), 'legacy_token_controls': token_controls,
          'legacy_raw_actions_and_full_log_controls': True, 'native_diagnostic_calls': 301, 'native_diagnostic_log_events': 12,
          'authority': 'three actual whole app functions plus ranged actual call/log fragments; renderer/WPK/math/log/sync metadata recorders',
          'limits': ['No GL context or Game model', 'Renderer clear/packet helpers mocked at app API boundary; owner tests actual implementations',
                     'No GPU/driver/fence/pixel/performance proof', 'UBSan only, no ASan/TSan or concurrency/recovery claim']}
(OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
