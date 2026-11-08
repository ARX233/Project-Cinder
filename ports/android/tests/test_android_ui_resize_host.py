#!/usr/bin/env python3
"""Production UI/input resize contracts; host CPU only, no GPU/device claims.

Extract app_wide/app_viewport, Android touch handling, start_game and the actual
post-ready game-loop admission slice. Platform/resource operations are recorders.
Exercise GLES, VK compatibility and Native preprocessing independently. Artifacts
are written only below --output (or an external temporary directory).
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def function(text, anchor):
    start = text.index(anchor)
    opening = text.index("{", start)
    depth = 0
    for i in range(opening, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError(anchor)


def build_source():
    android = (ROOT / "src/main_android.c").read_text()
    app = (ROOT / "src/app.c").read_text()
    loop = function(android, "static void *game(")
    # Preserve actual surface/frame admission, rather than model it in the test.
    start = loop.index("    pthread_mutex_unlock(&A.mx);\n#ifdef WMMT_NATIVE_VK\n    if (!frame_ready)")
    end = loop.index("    audio_service(away, now_s());", start)
    admission = loop[start:end]
    assert admission.index("if (!frame_ready)") < admission.index("if (A.fb_w <= 0")
    assert admission.index("if (failed)") < admission.index("ui_viewport_sync(&nt")
    assert loop.index("ui_viewport_sync(&nt") < loop.index("touch_deliver(tv, nt")
    assert loop.index("cinder_vk_platform_frame_ready()") < loop.index("ui_viewport_sync(&nt")
    callback = function(android, "JNIEXPORT void JNICALL JFN(nativeSurface)")
    assert "app_viewport(" not in callback and "ui_viewport_sync(" not in callback
    assert callback.index("pthread_mutex_lock(&A.mx)") < callback.index("A.window_changed = 1") < callback.index("pthread_mutex_unlock(&A.mx)")
    selected = "\n".join(function(android, a) for a in (
        "static void touch_enqueue(", "static int touch_take(",
        "static void touch_cancel_all(", "static void touch_reconcile_snapshot(",
        "static void touch_deliver(", "static int ui_viewport_sync(",
        "static int start_game(",
    ))
    app_functions = "\n".join(function(app, a) for a in (
        "void app_wide(", "int app_viewport(",
    ))
    prefix = r'''
#include <assert.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define TOUCH_MAX 256
#define EGL_NO_CONTEXT NULL
typedef struct {int id,phase;float x,y;} touch_ev;
static struct {
  int fb_w,fb_h,started,have_surface,vk_up,n_touch,touch_desync;
  float touch_k,touch_edge;
  pthread_mutex_t mx;
  touch_ev touches[TOUCH_MAX];
  char save_dir[32],data_dir[32],sidecar_dir[32],ta_store_dir[32],ghost_crown_dir[32];
  void *fail,*load_ctx;
} A={.mx=PTHREAD_MUTEX_INITIALIZER};
typedef struct touch_active {
  int id;float x,y;struct touch_active *next;
} touch_active;
static touch_active *touch_active_head;
static int touch_strict;
static struct {int fb_w,fb_h,console,phone;float edge;} G;
static struct {int id,phase;float x,y;} events[1024];
static int event_n,init_n,wide_n,save_n,console_n,extra_n,audio_n,thread_n,call_n;
static float anm_edge,hud_edge,menu_edge,key_scale,cluster,plate,pill,map_up,gate;
/* These stand for user-selected saved transforms: automatic resize must not write them. */
static float user_saved[6]={.8f,7,-9,1.3f,22,-31};
static void unlocked(void){assert(pthread_mutex_trylock(&A.mx)==0);pthread_mutex_unlock(&A.mx);}
static void near_(float a,float b){assert(fabsf(a-b)<.002f);}
static void anm_view(float e){unlocked();anm_edge=e;++wide_n;}
static void hud_wide(float e,float k){unlocked();hud_edge=e;key_scale=k;cluster=plate=pill=map_up=gate=0;}
static void menu_wide(float e){unlocked();menu_edge=e;}
static void hud_lift_parts(float c,float p,float pi,float m,float g){cluster=c;plate=p;pill=pi;map_up=m;gate=g;}
static void hud_lift(float c,float l){hud_lift_parts(c,c,c,l,l);}
static void app_touch(void *id,int phase,float x,float y){
  unlocked();assert(event_n<1024);events[event_n].id=(int)(intptr_t)id-1;
  events[event_n].phase=phase;events[event_n].x=x;events[event_n].y=y;++event_n;
}
static void app_save_dir(const char *p){unlocked();assert(!strcmp(p,"save"));++save_n;}
static void app_ta_rank_save_dir(const char *p){assert(p==A.ta_store_dir);}
static void app_ghost_crown_save_dir(const char *p){assert(p==A.ghost_crown_dir);}
static void sync_frame_rate_limit(void){unlocked();}
static void app_console(void){unlocked();G.console=1;++console_n;}
static void *android_card_resources_dir(char *p,size_t n){(void)p;(void)n;return NULL;}
static void hud_set_extra_directory(const char *p){unlocked();assert(!p);++extra_n;}
static int app_init(const char *p,int w,int h,float sw,float sh){
  unlocked();assert(!strcmp(p,"data")&&w==A.fb_w&&h==A.fb_h&&sw==1024&&sh==768);
  assert(G.fb_w==w&&G.fb_h==h);++init_n;return 0;
}
static void call_str(void *p,const char *s){(void)p;(void)s;++call_n;}
static const char *app_error(void){return "fixture";}
static int audio_retry;
static double now_s(void){return 1;}
static void snd_retry_begin(int *p,double now){(void)p;(void)now;++audio_n;}
static void snd_retry_stability(int *p,double now,int stable){(void)p;(void)now;(void)stable;}
static void *loader(void *p){return p;}
static int thread_create(pthread_t *t,const pthread_attr_t *a,void *(*fn)(void *),void *p){
  (void)t;(void)a;(void)fn;(void)p;++thread_n;return 1;
}
#define pthread_create thread_create
#define SURFACE_UP A.have_surface
static void timing60_display_reset(int *p){*p=0;}
static int sleep_(unsigned n){assert(n==10000||n==100000);return 0;}
#define usleep sleep_
'''
    driver = r'''
static int admit(int *n,int *desync,int ready) {
  int nt=*n,touch_desync=*desync,frame_ready=ready,failed=0,pacer=0,accepted=0;
  double last=9;(void)frame_ready;(void)pacer;(void)last;
  pthread_mutex_lock(&A.mx);
  do {
''' + admission + r'''
    accepted=1;
  } while(0);
  *n=nt;*desync=touch_desync;return accepted;
}
static void enqueue(int id,int phase,float x,float y){
  pthread_mutex_lock(&A.mx);touch_enqueue((touch_ev){id,phase,x,y});pthread_mutex_unlock(&A.mx);
}
static int take(touch_ev *out,int *desync){pthread_mutex_lock(&A.mx);int n=touch_take(out,desync);pthread_mutex_unlock(&A.mx);return n;}
static void delivered(touch_ev *in,int n,int desync){touch_reconcile_snapshot(&n,&desync);touch_deliver(in,n,desync);}
static void no_resources_restarted(void){assert(init_n==1&&save_n==1&&console_n==1&&extra_n==1&&audio_n==1&&call_n==0);}
static void api_invalid(void){
  struct {int w,h;float e,k;} bad[]={{0,1080,0,1},{1920,0,0,1},{-1,768,0,1},{1024,-1,0,1},
    {1024,768,NAN,1},{1024,768,INFINITY,1},{1024,768,-1,1},{1024,768,0,0},{1024,768,0,NAN}};
  G.fb_w=111;G.fb_h=222;G.edge=3;
  for(unsigned i=0;i<sizeof bad/sizeof *bad;++i){
    int before=wide_n;assert(!app_viewport(bad[i].w,bad[i].h,bad[i].e,bad[i].k));
    assert(G.fb_w==111&&G.fb_h==222&&G.edge==3&&wide_n==before);
  }
}
int main(void){
  api_invalid();strcpy(A.save_dir,"save");strcpy(A.data_dir,"data");A.vk_up=A.have_surface=1;A.load_ctx=(void*)1;
  int n=1,desync=0;A.fb_w=0;A.fb_h=1080;
  assert(!admit(&n,&desync,1)&&!A.started&&!init_n&&!save_n&&!console_n);
  A.fb_w=1920;A.fb_h=1080;
  assert(admit(&n,&desync,1)&&A.started&&n==1&&!desync);no_resources_restarted();
  near_(A.touch_k,768.f/1080);near_(A.touch_edge,170.66667f);assert(!G.phone&&G.console);
  touch_ev snap[TOUCH_MAX];int count;
  enqueue(7,0,960,540);count=take(snap,&desync);delivered(snap,count,desync);
  assert(event_n==1&&events[0].phase==0);near_(events[0].x,512);near_(events[0].y,384);
  /* Pending pre-resize events include a new DOWN: neither this snapshot nor the
   * producer queue can acquire in a changed coordinate system. */
  enqueue(7,1,1000,550);enqueue(9,0,300,600);count=take(snap,&desync);
  enqueue(10,0,700,600);A.fb_w=2340;A.fb_h=1080;
  assert(admit(&count,&desync,1)&&count==0&&desync==1&&A.touch_desync==1&&!A.n_touch);
  assert(event_n==2&&events[1].id==7&&events[1].phase==3);near_(events[1].x,512);near_(events[1].y,384);
  near_(A.touch_edge,320);assert(!touch_active_head&&touch_strict);
  enqueue(11,0,100,100);assert(!A.n_touch); /* poison rejects until consumed */
  delivered(snap,count,desync);int before=event_n;
  enqueue(7,1,1200,500);enqueue(9,2,300,600);count=take(snap,&desync);delivered(snap,count,desync);
  assert(event_n==before); /* old MOVE/UP cannot reactivate captures */
  enqueue(9,0,1170,540);count=take(snap,&desync);delivered(snap,count,desync);
  assert(event_n==before+1);near_(events[event_n-1].x,512);near_(events[event_n-1].y,384);
  enqueue(9,2,1170,540);count=take(snap,&desync);delivered(snap,count,desync);
  /* Native ready admission may reject a frame, but must not publish a mapping. */
#ifdef WMMT_NATIVE_VK
  A.fb_w=2400;int old=wide_n;n=0;desync=0;assert(!admit(&n,&desync,0)&&wide_n==old);near_(A.touch_edge,320);
#endif
  /* Invalid actual extents do not enter initialization or claim fresh UI geometry. */
  const int invalid[][2]={{0,1080},{1920,0},{-5,768},{1024,-10}};
  for(unsigned i=0;i<sizeof invalid/sizeof *invalid;++i){
    A.fb_w=invalid[i][0];A.fb_h=invalid[i][1];int old=wide_n;float k=A.touch_k,e=A.touch_edge;
    n=4;desync=0;assert(!admit(&n,&desync,1));assert(wide_n==old&&A.touch_k==k&&A.touch_edge==e);no_resources_restarted();
  }
  const int sizes[][2]={{1920,1080},{2160,1080},{2340,1080},{2400,1080},{1920,882},{1024,768},{1280,720},{2400,1080},{1024,768}};
  float saved[6];memcpy(saved,user_saved,sizeof saved);
  for(unsigned i=0;i<sizeof sizes/sizeof *sizes;++i){
    A.fb_w=sizes[i][0];A.fb_h=sizes[i][1];n=2;desync=0;
    assert(admit(&n,&desync,1));float k=768.f/A.fb_h,e=(A.fb_w*k-1024)*.5f;if(e<1)e=0;
    near_(A.touch_k,k);near_(A.touch_edge,e);near_(G.edge,e);near_(anm_edge,e);near_(hud_edge,e);near_(menu_edge,e);
    assert(G.fb_w==A.fb_w&&G.fb_h==A.fb_h);near_(key_scale,e>0?1.2f:1.f);
    near_(cluster,e>0?28:0);near_(plate,e>0?28:0);near_(pill,e>0?28:0);near_(map_up,e>0?40:0);near_(gate,e>0?40:0);
    assert(!memcmp(saved,user_saved,sizeof saved));no_resources_restarted();
    count=take(snap,&desync);delivered(snap,count,desync);
    /* Roundtrip raw points through the actual touch delivery API, across each edge. */
    const float x[]={0,36,512,988,1024},y[]={0,46,384,712,768};
    for(unsigned p=0;p<5;++p){
      float lx=x[p]+(p==0?-e:p==4?e:0),rx=(lx+e)/k,ry=y[p]/k;
      int was=event_n;enqueue(40+(int)p,0,rx,ry);count=take(snap,&desync);delivered(snap,count,desync);
      assert(event_n==was+1);near_(events[was].x,lx);near_(events[was].y,y[p]);
      enqueue(40+(int)p,2,rx,ry);count=take(snap,&desync);delivered(snap,count,desync);
    }
    int wide_before=wide_n,event_before=event_n;n=3;desync=0;assert(admit(&n,&desync,1));
    assert(n==3&&!desync&&wide_n==wide_before&&event_n==event_before); /* same extent is a no-op */
    printf("MATRIX %dx%d k=%.9g edge=%.9g resources=%d saved=unchanged\n",A.fb_w,A.fb_h,k,e,init_n);
  }
  /* Original overflow/poison and strict DOWN semantics remain intact. */
  for(int i=0;i<TOUCH_MAX+1;++i)enqueue(100+i,1,0,0);
  assert(A.touch_desync&&!A.n_touch);count=take(snap,&desync);assert(!count&&desync);delivered(snap,count,desync);
  puts("PASS production app geometry + Android touch/resize/admission slices; CPU recorders only");return 0;
}
'''
    return prefix + app_functions + selected + driver


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    source = out / "android-ui-resize.c"
    source.write_text(build_source())
    results = []
    for name, flags in (("gles", []), ("vkcompat", ["-DWMMT_VK"]),
                        ("native", ["-DWMMT_VK", "-DWMMT_NATIVE_VK"])):
        binary = out / ("android-ui-resize-" + name)
        command = [os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                   "-fsanitize=undefined", "-fno-sanitize-recover=all", *flags,
                   str(source), "-pthread", "-lm", "-o", str(binary)]
        compiled = subprocess.run(command, text=True, capture_output=True)
        (out / (name + "-compile.log")).write_text(compiled.stdout + compiled.stderr)
        if compiled.returncode:
            raise RuntimeError(f"{name} compilation failed: {compiled.stderr}")
        executed = subprocess.run([str(binary)], text=True, capture_output=True)
        (out / (name + "-run.log")).write_text(executed.stdout + executed.stderr)
        if executed.returncode:
            raise RuntimeError(f"{name} checks failed ({executed.returncode}): {executed.stdout}{executed.stderr}")
        print(name + ": " + executed.stdout.strip())
        results.append({"mode": name, "compile_exit": compiled.returncode,
                        "run_exit": executed.returncode, "command": command})
    report = {"coverage": "production CPU functions plus exact post-ready loop admission slice; no GPU/device/whole-app claim",
              "sources": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (ROOT / "src/main_android.c", ROOT / "src/app.c", ROOT / "src/app.h")},
              "results": results}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output:
        target = args.output.resolve()
        if target == ROOT or ROOT in target.parents:
            parser.error("--output must be outside the production source tree")
        run(target)
    else:
        scratch = Path(os.environ.get("TMPDIR", str(ROOT.parent / "tmp"))).resolve()
        if scratch == ROOT or ROOT in scratch.parents:
            parser.error("TMPDIR must be outside the production source tree")
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="android-ui-resize-", dir=scratch) as temp:
            run(Path(temp))
