#!/usr/bin/env python3
"""Whole production HUD menu geometry/hit contracts on GLES and NativeVulkan.

No GPU/device/resource reads: both backends' real primitives are recorded on CPU.
An optional CINDER_HUD_BASELINE directory provides unchanged hud.c/native .inc for
byte-exact zero-edge command comparison. Private headers are compile inputs only.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(os.environ.get("TMPDIR", str(ROOT.parent / "tmp"))).resolve()
if TMP == ROOT or ROOT in TMP.parents:
    raise SystemExit("TMPDIR must be outside the source tree")
TMP.mkdir(exist_ok=True)
PRIVATE = Path(os.environ["CINDER_PRIVATE_SRC"]).resolve() if os.environ.get("CINDER_PRIVATE_SRC") else None
BASELINE = Path(os.environ["CINDER_HUD_BASELINE"]).resolve() if os.environ.get("CINDER_HUD_BASELINE") else None

PREFIX = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "glstub.h"
/* Public declaration-only glstub omits two constants used by the unused
 * legacy negate path; give that complete production translation unit names. */
#define GL_ONE_MINUS_DST_COLOR 0x0307
#define GL_ZERO 0
#define WMMT_GL_H
#if TEST_NATIVE
#define WMMT_NATIVE_VK 1
#else
GLuint gl_compile_program(const char *,const char *,const char **,int);
#endif
#include HUD_SOURCE

typedef struct {int topology,count;float xy[132],projection[16],rgba[4];} command;
static command commands[128],zero[128];
static int command_n,zero_n;
static uint64_t zero_digest=1469598103934665603ULL;
static void near(float a,float b){assert(fabsf(a-b)<.002f);}
static void reset_capture(void){command_n=0;memset(commands,0,sizeof commands);}
static void record(int topology,int count,const float *xy,const float *projection,const float *rgba){
  assert(command_n<128&&count<=66&&count>0);
  command *c=&commands[command_n++];c->topology=topology;c->count=count;
  memcpy(c->xy,xy,(size_t)count*2*sizeof(float));
  memcpy(c->projection,projection,sizeof c->projection);memcpy(c->rgba,rgba,sizeof c->rgba);
}
#if TEST_NATIVE
void cinder_vk_screen_extent(int *w,int *h){*w=1920;*h=1080;}
int cinder_vk_draw_init(cinder_vk_draw *d,uint32_t p,uint32_t t,int w,int h){
  assert(p&&t==0&&w>0&&h>0);memset(d,0,sizeof *d);d->program=p;d->target=t;return 1;
}
int cinder_vk_uniform(cinder_vk_draw *d,const char *name,const void *p,size_t n){
  size_t off=!strcmp(name,"uProj")?0:64;assert((off==0&&n==64)||(off==64&&n==16&&!strcmp(name,"uColor")));
  memcpy(d->uniforms+off,p,n);return 1;
}
int cinder_vk_submit(const cinder_vk_draw *d){
  assert(d->program==prog&&d->target==0&&!d->indexed&&!d->pipeline.depth_test&&!d->pipeline.depth_write);
  const cinder_vk_attribute *a=&d->attributes[0];assert(a->format==VK_FORMAT_R32G32_SFLOAT&&a->stride==8&&a->data&&a->bytes>=d->count*8);
  float projection[16],rgba[4];memcpy(projection,d->uniforms,64);memcpy(rgba,d->uniforms+64,16);
  int topology=d->pipeline.topology==VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP?0:
    d->pipeline.topology==VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST?1:2;
  assert(topology!=2||d->pipeline.topology==VK_PRIMITIVE_TOPOLOGY_TRIANGLE_FAN);
  record(topology,(int)d->count,a->data,projection,rgba);return 1;
}
#else
static const float *vertices;
static float projection_[16],rgba_[4];
void glUseProgram(GLuint p){assert(p==prog);}
void glUniformMatrix4fv(GLint u,GLsizei n,GLboolean transpose,const GLfloat *p){(void)u;assert(n==1&&!transpose);memcpy(projection_,p,64);}
void glUniform4f(GLint u,GLfloat r,GLfloat g,GLfloat b,GLfloat a){(void)u;rgba_[0]=r;rgba_[1]=g;rgba_[2]=b;rgba_[3]=a;}
void glDisable(GLenum e){(void)e;}
void glEnable(GLenum e){(void)e;}
void glBlendFunc(GLenum a,GLenum b){assert(a==GL_SRC_ALPHA&&b==GL_ONE_MINUS_SRC_ALPHA);}
void glBindBuffer(GLenum e,GLuint b){(void)e;assert(!b);}
void glDisableVertexAttribArray(GLuint a){(void)a;}
void glEnableVertexAttribArray(GLuint a){assert(!a);}
void glVertexAttribPointer(GLuint a,GLint size,GLenum type,GLboolean norm,GLsizei stride,const void *p){assert(!a&&size==2&&type==GL_FLOAT&&!norm&&!stride);vertices=p;}
void glDrawArrays(GLenum mode,GLint first,GLsizei n){assert(!first);int t=mode==GL_TRIANGLE_STRIP?0:mode==GL_TRIANGLES?1:2;assert(t!=2||mode==GL_TRIANGLE_FAN);record(t,n,vertices,projection_,rgba_);}
#endif
static void draw_case(int op,int held){
  if(op==0)hud_draw_menu_option(1024,768,held);
  else if(op==1)hud_draw_menu_dress(1024,768,held);
  else if(op==2)hud_draw_menu_hidden(1024,768,held);
  else if(op==3||op==4)hud_draw_menu_erase(1024,768,held,op==4);
  else hud_draw_menu_keys(1024,768,held,op==5||op==6,op==5||op==7);
}
static float expected_shift(int op,int draw,float edge){
  if(op==2||op==8)return 0;
  if(op<=4||op==7)return edge;
  /* Actual production draw order: left panel, right panel, their chevrons,
   * then the return panel and glyph. Every panel has three primitives. */
  return draw<3||draw==6?-edge:edge;
}
static void compare_wide(int op,float edge){
  assert(command_n==zero_n);
  mat4 projection=screen_ortho(1024,768);
  for(int i=0;i<command_n;++i){
    const command *a=&zero[i],*b=&commands[i];float dx=expected_shift(op,i,edge);
    assert(a->topology==b->topology&&a->count==b->count&&!memcmp(a->rgba,b->rgba,sizeof a->rgba));
    for(int j=0;j<16;++j)near(b->projection[j],projection.m[j]);
    for(int j=0;j<a->count;++j){near(b->xy[j*2],a->xy[j*2]+dx);near(b->xy[j*2+1],a->xy[j*2+1]);}
  }
}
static void hit_contract(float edge){
  const rect base[5]={MENU_LEFT,MENU_RIGHT,MENU_BACK,MENU_OPTION,MENU_HIDDEN};
  const int answer[5]={-1,1,HUD_MENU_BACK,HUD_MENU_OPTION,HUD_MENU_HIDDEN};
  for(int i=0;i<5;++i){
    rect r=base[i];r.x+=i==0?-edge:i<4?edge:0;
    assert(hud_menu_key(r.x+r.w*.5f,r.y+r.h*.5f)==answer[i]);
    float slop=i<2?14:0;
    assert(hud_menu_key(r.x-slop,r.y+r.h*.5f)==answer[i]);
    assert(hud_menu_key(r.x+r.w+slop,r.y+r.h*.5f)==answer[i]);
    assert(hud_menu_key(r.x-slop-.25f,r.y+r.h*.5f)!=answer[i]);
    assert(hud_menu_key(r.x+r.w+slop+.25f,r.y+r.h*.5f)!=answer[i]);
    assert(hud_menu_key(r.x+r.w*.5f,r.y-slop)==answer[i]);
    assert(hud_menu_key(r.x+r.w*.5f,r.y+r.h+slop)==answer[i]);
    assert(hud_menu_key(r.x+r.w*.5f,r.y-slop-.25f)!=answer[i]);
    assert(hud_menu_key(r.x+r.w*.5f,r.y+r.h+slop+.25f)!=answer[i]);
    if(edge>160&&i<4)assert(hud_menu_key(base[i].x+base[i].w*.5f,base[i].y+base[i].h*.5f)==0);
  }
}
static void menu_matrix(void){
  const int helds[]={-1,0,1,HUD_MENU_BACK,HUD_MENU_OPTION,HUD_MENU_HIDDEN};
  const float sizes[][2]={{1024,768},{1920,1080},{2160,1080},{2340,1080},{2400,1080},{1920,882}};
  for(int op=0;op<9;++op)for(unsigned h=0;h<sizeof helds/sizeof *helds;++h){
    hud_wide(0,1);reset_capture();draw_case(op,helds[h]);zero_n=command_n;memcpy(zero,commands,sizeof zero);
    for(size_t i=0;i<(size_t)command_n*sizeof(command);++i)zero_digest=(zero_digest^((const unsigned char *)commands)[i])*1099511628211ULL;
#if EXPECT_WIDE
    for(unsigned s=0;s<sizeof sizes/sizeof *sizes;++s){
      float edge=(sizes[s][0]*768/sizes[s][1]-1024)*.5f;
      hud_wide(edge,edge>0?1.2f:1);reset_capture();draw_case(op,helds[h]);compare_wide(op,edge);hit_contract(edge);
    }
#endif
  }
  printf("ZERO_DIGEST %llu\n",(unsigned long long)zero_digest);
  (void)sizes;
}
#if EXPECT_WIDE
static void draw_race_keys(const hud_state *h,int all_keys){
#if TEST_NATIVE
  hud_native_draw_keys(hud_native_paint_for(screen_ortho(h->screen_w,h->screen_h)),h,0,all_keys);
#else
  draw_keys(h,0,all_keys);
#endif
}
static void vs_pause(void){
  hud_state h;
  hud_wide(323.918365f,1.2f);
  hud_init(&h,1920,882);
  rect pause=key(PAUSE,KEY_TOP),camera=key(CAMERA,KEY_TOP);
  hud_touch(&h,&h,TOUCH_BEGAN,pause.x+pause.w/2,pause.y+pause.h/2);
  assert(h.pause_pressed==1);
  reset_capture();draw_race_keys(&h,0);
  int pause_draws=command_n;
  assert(pause_draws>0);
  reset_capture();draw_race_keys(&h,1);
  int offline_draws=command_n;

  h.pause_pressed=0;
  h.pause_disabled=1;
  hud_touch(&h,&h,TOUCH_BEGAN,pause.x+pause.w/2,pause.y+pause.h/2);
  hud_touch(&h,&h,TOUCH_BEGAN,camera.x+camera.w/2,camera.y+camera.h/2);
  assert(!h.pause_pressed && h.camera_pressed==1);
  reset_capture();draw_race_keys(&h,0);
  assert(command_n==0);
  reset_capture();draw_race_keys(&h,1);
  assert(command_n>0 && offline_draws-command_n==pause_draws);
  puts("PASS online VS omits pause draws and ignores pause taps");
}
static void automatic_reset(void){
  for(int i=0;i<3;++i)hud_layout_set(i,1.1f+i*.1f,17+i,-9-i);
  hud_shift_layout_set(1,.8f,-27,13);
  for(int i=0;i<HUD_RACE_GROUPS;++i)hud_race_layout_set(i,1.2f,31+i,-21-i);
  float saved[3][3],race[HUD_RACE_GROUPS][3];
  for(int i=0;i<3;++i){saved[i][0]=USER_K[i];saved[i][1]=USER_DX[i];saved[i][2]=USER_DY[i];}
  for(int i=0;i<HUD_RACE_GROUPS;++i){race[i][0]=race_k[i];race[i][1]=race_dx[i];race[i][2]=race_dy[i];}
  const float edges[]={0,170.666672f,341.333344f,0,323.918365f,0};
  for(int pass=0;pass<4;++pass)for(unsigned e=0;e<sizeof edges/sizeof *edges;++e){
    float edge=edges[e],k=edge>0?1.2f:1;
    hud_wide(edge,k);
    near(CLUSTER_X,948+edge);near(CLUSTER_Y,286);near(INFO_Y,505);near(PILL_UP,0);near(MAP_UP,0);
    near(SHIFT_X,62-edge);near(SHIFT_Y,530-82*(k-1));near(TA_X,-edge);
    const float xs[3]={edge>0?386:236,edge>0?454:296,edge>0?250:116};
    const rect top[3]={PAUSE,RESET,CAMERA};
    for(int i=0;i<3;++i){near(top[i].x,xs[i]);near(top[i].y,12);near(top[i].w,48);near(top[i].h,48);}
    hud_state controls={0};
    rect former_gearbox=key((rect){edge>0?318:176,12,48,48},KEY_TOP);
    hud_touch(&controls,&controls,TOUCH_BEGAN,former_gearbox.x+former_gearbox.w/2,former_gearbox.y+former_gearbox.h/2);
    assert(!controls.camera_pressed && !controls.pause_pressed && !controls.reset_pressed);
    if(edge>0){
      if(pass&1){hud_lift_parts(32,42,40,40,25);near(CLUSTER_Y,254);near(INFO_Y,463);near(PILL_UP,40);near(MAP_UP,40);near(SHIFT_Y,530-82*(k-1)-25);}
      else {hud_lift(28,40);near(CLUSTER_Y,258);near(INFO_Y,477);near(PILL_UP,28);near(MAP_UP,40);near(SHIFT_Y,530-82*(k-1)-40);near(PAUSE.x,236);near(RESET.x,296);near(CAMERA.x,116);}
    }
    for(int i=0;i<3;++i){near(USER_K[i],saved[i][0]);near(USER_DX[i],saved[i][1]);near(USER_DY[i],saved[i][2]);}
    for(int i=0;i<HUD_RACE_GROUPS;++i){near(race_k[i],race[i][0]);near(race_dx[i],race[i][1]);near(race_dy[i],race[i][2]);}
    assert(shift_separate);near(shift_k,.8f);near(shift_dx,-27);near(shift_dy,13);
    hit_contract(edge); /* no KEY_K or saved player transform leaks into menus */
  }
  puts("PASS automatic width/lift baselines and wide-to-4:3 restoration; saved race/key/shift transforms unchanged");
}
#endif
int main(void){prog=1;menu_matrix();
#if EXPECT_WIDE
  automatic_reset();puts("PASS six viewport ratios: every real menu button/glyph vertex and shared hit/slop");
  vs_pause();
#endif
  return 0;
}
'''


def run(source_dir, native, changed, temporary):
    source = temporary / f"menu-{native}-{changed}.c"
    source.write_text(PREFIX)
    binary = source.with_suffix("")
    flags = ["-I", str(ROOT / "src"), "-I", str(ROOT / "test")]
    if PRIVATE is not None:
        flags += ["-I", str(PRIVATE)]
    flags += ["-I", "/opt/homebrew/include"] if sys.platform == "darwin" else []
    gc = ["-Wl,-dead_strip"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
    command = [os.environ.get("CC", "clang"), "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
               "-Werror", "-Wno-unused-function", "-Wno-unused-parameter", "-fsanitize=undefined", "-fno-sanitize-recover=all",
               "-ffunction-sections", "-fdata-sections", *gc, *flags,
               f'-DHUD_SOURCE="{source_dir / "hud.c"}"', f"-DTEST_NATIVE={native}",
               f"-DEXPECT_WIDE={changed}", str(source), "-lm", "-lz", "-o", str(binary)]
    env = dict(os.environ, TMPDIR=str(TMP), TMP=str(TMP), TEMP=str(TMP),
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1", PYTHONDONTWRITEBYTECODE="1")
    subprocess.run(command, check=True, cwd=temporary, env=env, timeout=120)
    result = subprocess.run([str(binary)], check=True, cwd=temporary, env=env,
                            text=True, stdout=subprocess.PIPE, timeout=30)
    print(f"{'NativeVulkan' if native else 'GLES'} {'updated' if changed else 'baseline'}\n{result.stdout}", end="")
    return re.search(r"ZERO_DIGEST (\d+)", result.stdout).group(1)


with tempfile.TemporaryDirectory(prefix="menu-wide-keys-", dir=TMP) as directory:
    directory = Path(directory)
    digests = [run(ROOT / "src", native, 1, directory) for native in (0, 1)]
    if BASELINE is not None:
        digests += [run(BASELINE, native, 0, directory) for native in (0, 1)]
    assert len(set(digests)) == 1, "zero-edge full command stream differs between source/backend/baseline"
    print("PASS exact zero-edge command digest", digests[0], "(both backends" + (" + unchanged baseline)" if BASELINE else ")"))
for name in ("hud.c", "hud_native_vk.inc"):
    print(name, "sha256", hashlib.sha256((ROOT / "src" / name).read_bytes()).hexdigest())
