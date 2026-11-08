#!/usr/bin/env python3
"""Production five-slot layout + ghost UI request/navigation contracts, CPU only.

Extract production functions verbatim; record their public drawing calls using
synthetic sprite sizes. No private frame tables/assets, network, device or GPU.
The full menu state machine is separately syntax checked when private generated
headers are available; this fixture explicitly selects its home/ghost slices.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(os.environ.get("TMPDIR", str(ROOT.parent.parent / "tmp"))).resolve()
if TMP == ROOT or ROOT in TMP.parents:
    raise SystemExit("TMPDIR must be outside source")
TMP.mkdir(parents=True, exist_ok=True)
TEXT = (ROOT / "src/menu.c").read_text()


def function(anchor):
    start = TEXT.index(anchor)
    opening = TEXT.index("{", start)
    depth = 0
    for p in range(opening, len(TEXT)):
        if TEXT[p] == "{":
            depth += 1
        elif TEXT[p] == "}":
            depth -= 1
            if not depth:
                return TEXT[start:p+1]
    raise AssertionError(anchor)


PREFIX = r'''
#include <assert.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "menu.h"
#include "anm.h"
#include "menu_mode_layout.h"
#ifndef ANM_BUILTIN_VS_MODE
#define ANM_BUILTIN_VS_MODE 0
#endif
void anm_draw_builtin(int,float,float,float,float,float);
#define MOVE_MODE 4
#define MOVE_COURSE 10
#define DECIDE_MODE 10
#define DECIDE_COURSE 15
#define FADE 20
#define LOADING_POP 20
#define TWO_PI 6.283185307179586f
#define TEN_COURSES 10
#define N_COURSES 12
#define CARDB_MAKERS 7 /* synthetic maker-count input; no private car database */
#define SET_CAR_X0 150.0f
#define SET_CAR_X1 490.0f
#define SET_CAR_Y0 150.0f
#define SET_CAR_Y1 250.0f
#define LAY_BUTTONS 4
#define HUD_MENU_BACK 2
#define HUD_MENU_OPTION 3
#define HUD_MENU_HIDDEN 4
enum {TOUCH_BEGAN, TOUCH_MOVED, TOUCH_ENDED, TOUCH_CANCELLED};
enum {SND_CURSOR, SND_SELECT, SND_CANCEL};
static float edge640;
static int network_calls, calls, route;
static struct {int bg,line,bottom;} ID={1,2,3};
typedef struct {int kind,id;float x,y,w,h,a;} packet;
static packet packets[128];
static void record(int kind,int id,float x,float y,float w,float h,float a){
  assert(calls<128);packets[calls++]=(packet){kind,id,x,y,w,h,a};
}
float anm_edge(void){return edge640*1.6f;}
int anm_sprite(int id){return id;}
float anm_sprite_width(int id){return id>=3223&&id<=3226?1024:id>=2316&&id<=2319?512:id>0?256:0;}
float anm_sprite_height(int id){return id>=3223&&id<=3226?512:id>=2316&&id<=2319?64:id>0?256:0;}
void anm_draw_sprite(int id,float x,float y,float a){record(1,id,x,y,anm_sprite_width(id),anm_sprite_height(id),a);}
void anm_draw_part(int id,const float src[4],const float dst[4],float a){
  assert(isfinite(src[0])&&isfinite(src[1])&&src[2]>src[0]&&src[3]>src[1]);record(2,id,dst[0],dst[1],dst[2]-dst[0],dst[3]-dst[1],a);
}
void anm_draw_builtin(int id,float x,float y,float w,float h,float a){record(3,id,x,y,w,h,a);}
void anm_draw(int a,int frame,float alpha){assert(frame>=0&&frame<600);record(4,a,0,0,0,0,alpha);}
void anm_fill(float r,float g,float b,float a){(void)r;(void)g;(void)b;(void)a;}
static void draw_back(int a,int f,float alpha){anm_draw(a,f,alpha);}
static void draw_topbar(int f,float a,const anm_swap*s){(void)f;(void)a;(void)s;}
static void draw_pre_loading(int f,float a){assert(f>=1&&f<=20);record(4,999,0,0,0,0,a);}
int anm_find(const char*n){return strstr(n,"search_grayout_arrow")?12:strstr(n,"search_grayout")?11:strstr(n,"seach_ring")?13:strstr(n,"yn_card")?14:15;}
int anm_frames(int a){return a==11?400:a==13?360:600;}
int anm_sprite_rect(int a,int f,int s,float r[4]){
 (void)a;(void)f;int k=s==453||s==0x1e68?0:s==1896||s==0x1cdc?1:s==1898?2:s==925?3:-1;
 if(k<0)return 0;r[0]=k?262+114*(k-1):11;r[1]=k?168:104;r[2]=r[0]+(k?128:256);r[3]=r[1]+(k?128:256);return 1;
}
void anm_draw_ex(int a,int f,float alpha,float dx,float dy,const anm_swap*s,int n){(void)dx;(void)dy;(void)s;(void)n;anm_draw(a,f,alpha);}
void hud_draw_menu_option(float w,float h,int hld){(void)w;(void)h;(void)hld;}
void hud_ui_begin(float w,float h){(void)w;(void)h;}
void hud_ui_end(void){}
float hud_ui_text_width(const char *s,float px){return (float)(strlen(s)*6)*px;}
float hud_ui_text(const char*s,float x,float y,float px,float r,float g,float b,float a){
 (void)r;(void)g;(void)b;assert(isfinite(x)&&isfinite(y)&&px>0);return x+hud_ui_text_width(s,px)+a*0;
}
void hud_ui_button(float x,float y,float w,float h,int held){record(5,held,x/1.6f,y/1.6f,w/1.6f,h/1.6f,1);}
void hud_ui_rect(float x,float y,float w,float h,float r,float g,float b,float a){(void)r;(void)g;(void)b;record(6,0,x/1.6f,y/1.6f,w/1.6f,h/1.6f,a);}
void hud_draw_menu_keys(float w,float h,int held,int keys,int back){(void)w;(void)h;(void)held;(void)keys;(void)back;}
int hud_menu_key(float x,float y){
  float edge=edge640*1.6f;
  if(y>=634&&y<=726&&x>=22-edge&&x<=226-edge)return -1;
  if(y>=634&&y<=726&&x>=798+edge&&x<=1002+edge)return 1;
  if(y>=46&&y<=106&&x>=722+edge&&x<=806+edge)return HUD_MENU_BACK;
  if(y>=46&&y<=106&&x>=622+edge&&x<=706+edge)return HUD_MENU_OPTION;
  return 0;
}
void snd_menu(int which){(void)which;}
void pre_race_tune_clear(pre_race_tune*t){memset(t,0,sizeof *t);}
int pre_race_tune_confirm(pre_race_tune*t){t->state=2;return 1;}
static int ncars(const menu_state*m){(void)m;return 1;}
static int in_attract(const menu_state*m){return m->screen<=MENU_PROLOGUE;}
int menu_booting(const menu_state*m){(void)m;return 0;}
static int pre_tune_context(const menu_state*m){(void)m;return 0;}
static void layout_touch(menu_state*m,void*i,int p,float x,float y){(void)m;(void)i;(void)p;(void)x;(void)y;}
static int vs_hit(const menu_state*m,float x,float y){(void)m;(void)x;(void)y;return -1;}
static int all_parts_shown(const menu_state*m){(void)m;return 0;}
static int vs_omakase_shown(const menu_state*m){(void)m;return 0;}
static void vs_omakase(menu_state*m){(void)m;}
static void st_level_enter(menu_state*m){m->screen=MENU_ST_LEVEL;route=1;}
static void ten_course_enter(menu_state*m){m->screen=MENU_TEN_COURSE;route=2;}
int net_open(void){++network_calls;return 0;}
void net_scan(double now,int on){(void)now;(void)on;++network_calls;}
void net_poll(void){++network_calls;}
void net_start(void){++network_calls;}
int gk_browse(const char*n){(void)n;++network_calls;return 0;}
static void go(menu_state*,int);
'''

# Home descriptors are exact production source, not duplicated fixture mappings.
desc = TEXT[TEXT.index("#define GAME_SLOTS "):TEXT.index("static int game_slot(")]
anchors = (
    "static int game_slot(", "static int game_rects(", "static int game_hit(",
    "static void go(menu_state *m, int screen) {", "static void car_select_enter(",
    "static void ghost_invalidate(", "void menu_ghost_open(", "void menu_ghost_set_availability(",
    "int menu_ghost_set_map(", "static int ghost_action_enabled(", "int menu_ghost_action_available(", "int menu_ghost_request(",
    "int menu_ghost_take_action(", "int menu_ghost_complete(", "int menu_ghost_begin_pre(",
    "int menu_ghost_preparing(", "void menu_ghost_race_finished(",
    "static int ghost_hit(", "static void ghost_touch(", "static void ghost_step(",
    "void menu_touch(", "static float course_dx(", "static int tap_dir(",
    "static void game_sprite(", "static void game_text(", "static void draw_game_modes(",
    "static void draw_ghost_hub(", "static void draw_ghost_pre(",
)
selected = "\n".join(function(a) for a in ("static void game_picture(", "static void game_mode_label(") if a in TEXT) + "\n" + "\n".join(function(a) for a in anchors)
step = function("static void step(menu_state *m) {")
home = step[step.index("  int ten = m->screen == MENU_TEN_COURSE;"):].rsplit("}", 1)[0]
ghost_start = step.index("  if (m->screen == MENU_GHOST) {")
ghost_end = step.index("  if (m->screen == MENU_VS &&", ghost_start)
# Actual home/ghost step slices, with the original per-tick input consumption.
selected += "\nstatic void selected_step(menu_state *m){\n ++m->t; int tap=m->tap,key=m->key,back=m->back; m->tap=m->key=m->back=m->option=0;\n"
selected += step[ghost_start:ghost_end]
selected += " if(m->deciding){--m->deciding;return;}\n" + home + "\n}\n"
update = function("int menu_update(menu_state *m, float dt) {")
start = update.index("      } else if (m->screen == MENU_GAME) {")
end = update.index("      } else if (m->screen == MENU_VS_SEL) {", start)
decision = update[start:end].split("{",1)[1]
selected += "\nstatic void decide_home(menu_state *m){do {\n" + decision + "\n}while(0);}\n"
# Check the integration branch itself exists before exercising its implementation.
assert "draw_game_modes(m, fade, screen_w, screen_h);" in function("void menu_draw(")
assert "draw_ghost_hub(m, clock, bars, screen_w, screen_h);" in function("void menu_draw(")
assert "MENU_GAME ||" not in function("static int layout_frame(")

MAIN = r'''
static void near(float a,float b){assert(fabsf(a-b)<.004f);}
static void reset(menu_state*m,int sel){memset(m,0,sizeof *m);m->screen=MENU_GAME;m->game=MENU_GAME_STORY;m->sel=sel;m->from=-1;calls=0;}
static void click(menu_state*m,void*id,float x,float y){menu_touch(m,id,TOUCH_BEGAN,x*1.6f,y*1.6f);menu_touch(m,id,TOUCH_ENDED,x*1.6f,y*1.6f);}
static void check_draw(menu_state*m){
 menu_mode_rect rect[5];assert(game_rects(m,rect));calls=0;draw_game_modes(m,1,1024,768);
 int count=0,built=0;
 for(int i=0;i<calls;i++){
  packet*p=&packets[i];
  if((p->kind==2&&(p->id==2825||p->id==2824||p->id==2826||p->id==2827))||p->kind==3){
   int k=p->kind==3?game_slot(MENU_GAME_VS):game_slot(p->id==2825?MENU_GAME_STORY:p->id==2824?MENU_GAME_TEN:p->id==2826?MENU_GAME_TA:MENU_GAME_GHOST);
   near(p->x,rect[k].x);near(p->y,rect[k].y);near(p->w,rect[k].w);near(p->h,rect[k].h);
   near(p->w,p->h);++count;built+=p->kind==3;
  }
  if(p->kind==1&&p->id>=3223&&p->id<=3226)assert(p->id==GAME_MODE[m->sel].picture);
  if(GAME_MODE[m->sel].game==MENU_GAME_VS)assert(p->id!=3226&&p->id!=2319);
  assert(p->id!=2319); /* no unimplemented upgrade-parts label in any home slot */
 }
 assert(count==5&&built==1);
}
int main(void){
 assert(MENU_GAME_STORY==0&&MENU_GAME_TEN==1&&MENU_GAME_TA==2&&MENU_GAME_VS==3&&MENU_GAME_GHOST==4);
 assert(MENU_GHOST>MENU_LAYOUT&&GAME_SLOTS==5);
 const float edges[]={0,106.66667f,160,200,213.3333f,202.44898f};
 menu_state m;unsigned cases=0;
 for(unsigned e=0;e<sizeof(edges)/sizeof(edges[0]);++e){edge640=edges[e];
  for(int sel=0;sel<5;sel++){
   reset(&m,sel);menu_mode_rect r[5];assert(game_rects(&m,r));near(r[0].x,76);near(r[4].x+r[4].w,564);
   for(int t=0;t<60;t++){m.t=t;check_draw(&m);++cases;}
   for(int t=0;t<10;t++){m.t=t;m.deciding=30-t;check_draw(&m);++cases;}m.deciding=0;
   for(int k=0;k<5;k++){
    m.tap_x=r[k].x+r[k].w/2;m.tap_y=165;assert(game_hit(&m)==k);
    near(r[k].w,k==sel?128:76);near(r[k].h,r[k].w);
   }
   m.tap_x=r[sel].x+r[sel].w/2;m.tap_y=400;m.tap=1;selected_step(&m);assert(!m.deciding);
   m.tap_x=r[sel].x+r[sel].w/2;m.tap_y=165;m.tap=1;selected_step(&m);assert(m.deciding==30);m.deciding=0;
   for(int d=-1;d<=1;d+=2){reset(&m,sel);m.key=d;selected_step(&m);
    int target=sel+d;if(target<0||target>4){assert(m.sel==sel&&m.from==-1);continue;}
    assert(m.sel==target&&m.from==sel&&m.t==0);
    for(int tick=0;tick<=4;tick++){m.t=tick;check_draw(&m);++cases;}
    m.t=3;selected_step(&m);assert(m.from==-1&&m.t==0);
   }
  }
 }
 edge640=0;
 for(int s=0;s<5;s++){reset(&m,s);decide_home(&m);assert(m.game==GAME_MODE[s].game);
  assert(m.screen==(GAME_MODE[s].game==MENU_GAME_STORY?MENU_ST_LEVEL:GAME_MODE[s].game==MENU_GAME_VS?MENU_VS_SEL:GAME_MODE[s].game==MENU_GAME_TEN?MENU_TEN_COURSE:GAME_MODE[s].game==MENU_GAME_TA?MENU_MODE:MENU_GHOST));}
 reset(&m,INT_MAX);m.key=1;selected_step(&m);assert(m.sel==INT_MAX);decide_home(&m);assert(m.screen==MENU_GAME&&m.sel==0);
 menu_mode_rect r[5];assert(!menu_mode_layout(-1,-1,0,0,r));assert(!menu_mode_layout(4,0,0,0,r));
 reset(&m,4);m.vs.connect=m.vs.join=m.vs.start=m.vs.day=m.vs.area_go=1;m.vs.state=MENU_VS_RACE;menu_ghost_open(&m);
 assert(m.game==4&&m.screen==MENU_GHOST&&!m.vs.connect&&!m.vs.join&&!m.vs.start&&!m.vs.day&&!m.vs.area_go&&m.vs.state==MENU_VS_OFF);
 assert(!m.ghost.local_available&&!m.ghost.cloud_configured&&!m.ghost.king_available);
 assert(m.ghost.ramp==1&&m.ghost.route==0);
 assert(!menu_ghost_set_map(&m,0,0)&&!menu_ghost_set_map(&m,23,0)&&!menu_ghost_set_map(&m,1,-1));
 for(int ramp=1;ramp<=22;ramp++)assert(menu_ghost_set_map(&m,ramp,0));
 assert(menu_ghost_set_map(&m,1,0));
 assert(menu_ghost_action_available(&m,MENU_GHOST_RECORD_LOCAL));
 for(int a=2;a<=5;a++)assert(!menu_ghost_request(&m,a));
 unsigned id=99;assert(menu_ghost_take_action(&m,&id)==0&&id==0);
 /* Original root never aliases a local file to an original directory. */
 click(&m,(void*)9,100,160);assert(!m.ghost.pending_action&&strstr(m.ghost.note,"DIRECTORY"));
 click(&m,(void*)9,415,45);assert(m.ghost.ui.page==GHOST_UI_SEARCH&&!m.ghost.pending_action);
 /* True release-hit, cancel, drag off and another finger cannot queue. */
 menu_touch(&m,(void*)1,TOUCH_BEGAN,100*1.6f,160*1.6f);assert(m.ghost.touch==(void*)1&&!m.ghost.pending_action);
 menu_touch(&m,(void*)2,TOUCH_ENDED,100*1.6f,160*1.6f);assert(!m.ghost.pending_action);
 menu_touch(&m,(void*)1,TOUCH_CANCELLED,100*1.6f,160*1.6f);assert(!m.ghost.touch);
 menu_touch(&m,(void*)1,TOUCH_BEGAN,100*1.6f,160*1.6f);menu_touch(&m,(void*)1,TOUCH_MOVED,20,20);menu_touch(&m,(void*)1,TOUCH_ENDED,20,20);assert(!m.ghost.pending_action);
 assert(menu_ghost_request(&m,MENU_GHOST_RECORD_LOCAL));
 assert(!menu_ghost_complete(&m,m.ghost.active_request,1,0)); /* not taken yet */
 assert(menu_ghost_take_action(&m,&id)==MENU_GHOST_RECORD_LOCAL&&id);unsigned old=id;
 assert(m.ghost.request_ramp==1&&m.ghost.request_route==0&&!menu_ghost_set_map(&m,2,0));
 assert(menu_ghost_take_action(&m,&id)==0&&id==0);assert(!menu_ghost_request(&m,1));
 assert(!menu_ghost_complete(&m,old+1,1,0));assert(menu_ghost_complete(&m,old,1,0));assert(!menu_ghost_complete(&m,old,1,0));
 menu_ghost_set_availability(&m,1,1,1);
 assert(menu_ghost_set_map(&m,2,0)&&!m.ghost.local_available&&!m.ghost.king_available);
 menu_ghost_set_availability(&m,1,1,1);
 for(int a=1;a<=4;a++){assert(menu_ghost_request(&m,a));assert(menu_ghost_take_action(&m,&id)==a);assert(menu_ghost_complete(&m,id,1,0));}
 assert(menu_ghost_request(&m,MENU_GHOST_CHALLENGE_LOCAL));menu_ghost_set_availability(&m,0,1,1);
 assert(!menu_ghost_take_action(&m,&id)&&!m.ghost.active_request&&m.ghost.status==MENU_GHOST_ERROR);
 menu_ghost_set_availability(&m,1,1,1);
 menu_ghost_race_finished(&m,MENU_GHOST_RESULT_WIN,0);assert(!m.ghost.claim_eligible&&!menu_ghost_request(&m,5));assert(strstr(m.ghost.note,"PRACTICE"));
 menu_ghost_race_finished(&m,MENU_GHOST_RESULT_LOSE,1);assert(!m.ghost.claim_eligible);
 menu_ghost_race_finished(&m,MENU_GHOST_RESULT_WIN,1);assert(m.ghost.claim_eligible);assert(strstr(m.ghost.note,"PENDING SERVER"));
 assert(menu_ghost_request(&m,5));assert(menu_ghost_take_action(&m,&id)==5);assert(menu_ghost_complete(&m,id,1,0));assert(!m.ghost.claim_eligible&&strstr(m.ghost.note,"PENDING SERVER"));
 assert(menu_ghost_request(&m,1));assert(menu_ghost_take_action(&m,&id)==1);old=id;
 m.back=1;selected_step(&m);if(m.screen==MENU_GHOST){m.back=1;selected_step(&m);}assert(m.screen==MENU_GAME&&m.sel==game_slot(MENU_GAME_GHOST)&&!m.ghost.active_request&&!m.ghost.claim_eligible);assert(!menu_ghost_complete(&m,old,1,0));
 menu_ghost_open(&m);assert(!menu_ghost_complete(&m,old,1,0));
 /* Current hub button drawing is the same geometry used by actual release hit. */
 calls=0;draw_ghost_hub(&m,0,0,1024,768);
 for(int i=0;i<calls;i++)if(packets[i].kind==5){packet*p=&packets[i];assert(ghost_hit(&m,p->x+p->w/2,p->y+p->h/2)>0);}
 assert(!menu_ghost_begin_pre(&m));
 assert(menu_ghost_request(&m,MENU_GHOST_FETCH_KING));assert(menu_ghost_take_action(&m,&id)==MENU_GHOST_FETCH_KING);
 assert(menu_ghost_complete(&m,id,1,0)&&!menu_ghost_begin_pre(&m));
 assert(menu_ghost_request(&m,MENU_GHOST_RECORD_LOCAL));assert(menu_ghost_take_action(&m,&id)==MENU_GHOST_RECORD_LOCAL);
 assert(menu_ghost_complete(&m,id,1,0)&&menu_ghost_begin_pre(&m));
 assert(m.screen==MENU_GHOST_PRE&&!m.ready&&menu_ghost_preparing(&m)&&!menu_ghost_begin_pre(&m));
 assert(!menu_ghost_set_map(&m,1,0)&&!menu_ghost_request(&m,1));
 for(int t=0;t<=600;t+=20){m.t=t;calls=0;draw_ghost_pre(&m,0,1024,768);assert(calls>0);}
 menu_ghost_open(&m);assert(!menu_ghost_preparing(&m)&&!m.ghost.prepared_request&&!m.ghost.completed_request);
 m.ghost.request_serial=UINT_MAX;assert(!menu_ghost_request(&m,1));
 assert(network_calls==0);printf("PASS %u five-mode draw/transition cases; ghost once/stale/cancel/claim/real-touch contracts; network=0\n",cases);
 return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="ghost-menu-", dir=TMP) as directory:
    path = Path(directory)
    src = path / "test.c"
    src.write_text(PREFIX + desc + selected + MAIN)
    for label, flags in (("GLES", []), ("VKcompat", ["-DWMMT_VK=1"]), ("NativeVulkan", ["-DWMMT_NATIVE_VK=1"])):
        exe = path / label
        command = [os.environ.get("CC", "clang"), "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-function", "-Wno-unused-parameter", "-fsanitize=undefined", "-fno-sanitize-recover=all",
                   "-DWMMT_PRE_RACE_TEST=1", *flags, "-I", str(ROOT / "src"), str(src), "-lm", "-o", str(exe)]
        subprocess.run(command, check=True, cwd=path, timeout=120)
        result = subprocess.run([str(exe)], check=True, cwd=path, text=True, stdout=subprocess.PIPE, timeout=30,
                                env=dict(os.environ, UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"))
        print(label, result.stdout.strip())
    if os.environ.get("CINDER_PRIVATE_SRC"):
        private = Path(os.environ["CINDER_PRIVATE_SRC"]).resolve()
        if not (private / "cardb.h").is_file():
            raise SystemExit("CINDER_PRIVATE_SRC must contain reviewed generated cardb.h")
        gc = ["-Wl,-dead_strip", "-Wl,-undefined,dynamic_lookup"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
        for label, flags in (("GLES", []), ("VKcompat", ["-DWMMT_VK=1"]), ("NativeVulkan", ["-DWMMT_NATIVE_VK=1"])):
            exe = path / (label + "-complete-menu")
            command = [os.environ.get("CC", "clang"), "-std=gnu11", "-O1", "-g", "-U__APPLE__",
                       "-DWMMT_PRE_RACE_TEST=1", "-DWMMT_BGM_TEST=1", "-DWMMT_GL_H=1",
                       "-include", str(ROOT / "test/glstub.h"), *flags,
                       "-I", str(ROOT / "src"), "-I", str(ROOT / "test"), "-I", str(private),
                       '-DPORT_MENU="' + str(ROOT / "src/menu.c") + '"',
                       "-ffunction-sections", "-fdata-sections", "-fsanitize=undefined", "-fno-sanitize-recover=all",
                       str(ROOT / "tests/ghost_menu_real_host.c"), str(ROOT / "src/pre_race_tune.c"),
                       *gc, "-lm", "-o", str(exe)]
            subprocess.run(command, check=True, cwd=path, timeout=120)
            subprocess.run([str(exe)], check=True, cwd=path, timeout=30,
                           env=dict(os.environ, UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"))
            print(label, "complete production menu integration PASS")
