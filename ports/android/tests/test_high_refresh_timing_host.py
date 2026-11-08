#!/usr/bin/env python3
"""Production scheduler + real app race branches, with explicit RC/network/GPU stubs.
No APK, device, private game assets or physics-equivalence claim. All artifacts
remain in the caller's CINDER_TEST_OUT (default: reviewed APFS session folder).
"""
from pathlib import Path
import os, re, subprocess, tempfile, unittest
ROOT = Path(__file__).resolve().parents[1]
# Temporary artifacts belong to this invocation, never to a historical evidence workspace.
OUT = Path(os.environ.get('TMPDIR') or os.environ.get('CINDER_TEST_OUT') or str(ROOT.parent / 'tmp')).resolve()
OUT.mkdir(parents=True, exist_ok=True)


def function(source, anchor):
    a = source.index(anchor)
    b = source.index('{', a)
    masked = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', lambda m: ' '*len(m.group()), source, flags=re.S)
    depth = 0
    for i in range(b, len(source)):
        depth += (masked[i] == '{') - (masked[i] == '}')
        if depth == 0:
            return source[a:i+1]
    raise AssertionError(anchor)


PRE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include "timing60.h"
#include "presentation60.h"
#include "hud.h"
#include "menu.h"
#define CHECK(x) do { if(!(x)) {fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);} } while(0)
#define VS_CLOSED_NOTICE 180
#define VS_RECOVERY_READY_SIZE 47
#define NET_NAME 20
#define TEN_WHITE_HOLD 20
#define TEN_WHITE_FADE 10
#define SND_BEATEN 5
#define SHARP_REST 10
static struct {
  car_state car; hud_state hud; menu_state menu;
  int in_menu,vs_race,vs_closed,vs_wait,paused,race_frames,camera;
  int story_end_started,story_end_freeze,story_old_ended,n_ten,rival,story_race,story_cut_pending;
  int period_in,movie_in,ten_freeze,ten_white,ten_bgm_off,ten_beaten_on;
  int ao_test; float movie_len,movie_frame,fps; double frame_start; FILE *perf;
} G;
static struct { struct {int initialized;} recovery; int local_finished,all_new; } VR;
static struct {int waiting;} VG_finish;
static int race_junction_ui,race_junction_barrier;
static timing60_sim android_sim,app_clock;
static int app_tick_only,app_history_valid;
static car_state app_previous,app_display_car;
static car_input app_display_input;
static float app_display_dt;
static int physics,draws,menu_ticks,pause_ticks,finish_ticks,polls,movie_ticks,dialogue,shifts,tracks,tails;
static int closed,network_open=1,abort_now,leave_pause,resume_pause,leave_finish,close_at,abort_at;
/* This fixture runs the original four-mode scheduler contexts only. A new
 * Ghost failure is forbidden rather than silently accepted by a permissive fake. */
static int app_ghost_mode(void) {return 0;}
/* Fixture boundaries only: no Ghost projection fault or TA ranking/sidecar execution. */
static struct {int draw_fault;} ACP;
static unsigned rank_observer_boundary_calls;
static void app_ta_rank_tick(void){++rank_observer_boundary_calls;}
static void app_ta_rank_invalidate(void){++rank_observer_boundary_calls;}
static void app_ghost_fail(const char *note) {(void)note;abort();}
static double clock_ms;
static float last_x,last_cam; static int smooth_frames;
static double now_ms(void) {return clock_ms;}
static void menu_present(double t) {(void)t;++draws;}
static void menu_frame(float dt,double t) {(void)t; CHECK(dt==0||fabsf(dt-1.0f/60)<1e-8);++menu_ticks;}
static void app_draw_frame(float dt,const car_input *in,int ticks,double ms,const car_state *c) {
 (void)dt;(void)in;(void)ticks;(void)ms;++draws;++G.race_frames;
 if(c->body[12]!=last_x)++smooth_frames;last_x=c->body[12];last_cam=c->cam_pos[0];
 CHECK(fabsf(c->cam_view[12]+c->cam_pos[0])<0.0001f);
}
static void app_timing_reset(void);
#define anm_trim() ((void)0)
#define wpk_ao(...) ((void)0)
#define perf_menu(...) ((void)0)
#define vs_recovery_request_abort(...) ((void)0)
#define vs_recovery_observe_now() (abort_now || (abort_at && physics>=abort_at))
static int vs_abort_to_lobby(void) {G.in_menu=1;G.vs_race=0;return 1;}
#define net_is_open() (network_open)
#define vs_recovery_profile(p) (47)
#define vs_name(...) ((void)0)
#define vs_host_is_open() (0)
#define vs_host_poll(...) ((void)0)
#define net_poll(...) (++polls)
#define vs_host_loading_abort(...) (0)
#define net_host_closed() (closed || (close_at && physics>=close_at))
#define vs_remote_timed_out(...) (0)
#define junction_ui_reset(...) ((void)0)
#define junction_barrier_reset(...) ((void)0)
#define junction_ui_tick(...) ((void)0)
#define junction_barrier_tick(...) ((void)0)
#define vs_off() (G.vs_race=0)
#define snd_quiet() ((void)0)
#define menu_vs_closed(...) ((void)0)
#define menu_pause_open(...) ((void)0)
#define story_carry_cancel() ((void)0)
#define vs_recovery_reset(...) ((void)0)
#define vs_host_disarm_round() ((void)0)
#define hud_options() ((void)0)
#define car_view(...) ((void)0)
#define car_reset(...) ((void)0)
#define car_set_manual(...) ((void)0)
#define garage_save() ((void)0)
#define hud_demo_step() (0)
#define movie_close() (G.movie_len=0)
#define player_tracks_tick(...) (++tracks)
#define race_tail_tick(...) (++tails)
#define backfire_tick() ((void)0)
#define spark_step(...) ((void)0)
#define hud_ten_cutin(...) ((void)0)
#define story_period_suspend() (0)
#define hud_story_cutin_suspend() ((void)0)
#define story_carry_capture() (0)
#define net_receive_drained() (1)
#define net_lobby_current_valid() (1)
#define snd_update(...) ((void)0)
#define snd_rev_quiet() ((void)0)
#define android_story_bgm_pause() ((void)0)
#define snd_menu(...) ((void)0)
typedef struct {float v[3];} junction_barrier_point;
void car_clear_junction(car_race *r) {r->jct_select_valid=0;}
void hud_init(hud_state *h,float w,float ht) {memset(h,0,sizeof *h);h->screen_w=w;h->screen_h=ht;}
int menu_pause_update(menu_state *m,float dt) {(void)m;(void)dt;++pause_ticks;return leave_pause?MENU_LEAVE:resume_pause?MENU_RESUME:0;}
int menu_finish_update(menu_state *m,float dt) {(void)m;(void)dt;++finish_ticks;return leave_finish?MENU_LEAVE:0;}
void car_update(car_state *c,const car_input *in) {++physics;shifts+=in->shift_up;c->body[12]+=1;c->pos[0]+=1;c->cam_pos[0]+=1;c->cam_view[12]=-c->cam_pos[0];c->race.total+=1.0f/60;}
int car_movie_update(car_state *c,float f) {(void)f;++movie_ticks;c->body[12]+=1;c->cam_pos[0]+=1;c->cam_view[12]=-c->cam_pos[0];return 1;}
void hud_story_cutin_step(const car_race *r,int h) {(void)r;(void)h;++dialogue;}
int hud_story_cutin_goal_hold(const car_race *r) {(void)r;return 180;}
#define GYRO_DEAD 0.03f
#define WHEEL_LOCK 2.0f
'''

MAIN = r'''
static void ident(float *m) {memset(m,0,64);m[0]=m[5]=m[10]=m[15]=1;}
static void reset(void) {
 memset(&G,0,sizeof G);memset(&VR,0,sizeof VR);memset(&VG_finish,0,sizeof VG_finish);
 physics=draws=menu_ticks=pause_ticks=finish_ticks=polls=movie_ticks=dialogue=shifts=tracks=tails=0;
 closed=abort_now=leave_pause=resume_pause=leave_finish=close_at=abort_at=0;network_open=1;
 smooth_frames=0;last_x=last_cam=0;G.rival=-1;G.race_frames=3;G.car.race.state=CAR_RACE_RUN;
 ident(G.car.body);ident(G.car.cam_view);G.car.cam_fov=1;G.car.cam_near=1;
 for(int i=0;i<4;++i)ident(G.car.tyre[i]);
 app_timing_reset();timing60_sim_reset(&android_sim);
}
static void run_rate(int hz,int jitter) {
 for(int i=0;i<hz*10;++i) {
  double dt=(1.0+(jitter ? ((i%2)?0.35:-0.35):0))/hz;
  clock_ms+=dt*1000;app_present((float)dt);
 }
}
static void matrix_tests(void) {
 car_state a={0},b={0},out;ident(a.body);ident(b.body);ident(a.cam_view);ident(b.cam_view);
 b.body[12]=10;b.pos[0]=10;b.cam_pos[0]=10;b.cam_view[12]=-10;a.cam_near=b.cam_near=1;a.cam_fov=b.cam_fov=1;
 for(int i=0;i<4;++i){ident(a.tyre[i]);ident(b.tyre[i]);}a.tyre_rot[0]=3.1f;b.tyre_rot[0]=-3.1f;
 a.rival_shown[0]=b.rival_shown[0]=1;ident(a.rival_body[0]);ident(b.rival_body[0]);b.rival_body[0][12]=20;
 a.n_traffic=b.n_traffic=1;ident(a.traffic[0].body);ident(b.traffic[0].body);b.traffic[0].body[12]=30;
 car_state saved=b;presentation60_car(&out,&a,&b,.5f,1);
 CHECK(out.body[12]==5&&out.cam_pos[0]==5&&out.cam_view[12]==-5&&out.rival_body[0][12]==10&&out.traffic[0].body[12]==15);
 CHECK(fabsf(out.tyre_rot[0]-3.14159265f)<.001f);CHECK(!memcmp(&saved,&b,sizeof b));
 /* Camera-space translation jumps at a distant map origin must not disable
  * ordinary rotational interpolation. */
 a.cam_pos[0]=151331;b.cam_pos[0]=151332;a.cam_view[12]=-151331;
 b.cam_view[0]=b.cam_view[10]=cosf(.02f);b.cam_view[2]=-sinf(.02f);b.cam_view[8]=sinf(.02f);
 b.cam_view[12]=-b.cam_view[0]*b.cam_pos[0];b.cam_view[14]=-b.cam_view[2]*b.cam_pos[0];
 presentation60_car(&out,&a,&b,.5f,1);CHECK(fabsf(out.cam_view[2]+sinf(.01f))<.00001f);
 CHECK(fabsf(out.cam_pos[0]-151331.5f)<.01f);
 b.cam_pos[0]+=1000;presentation60_car(&out,&a,&b,.5f,1);CHECK(out.cam_pos[0]==b.cam_pos[0]);
 presentation60_car(&out,&a,&b,.5f,0);CHECK(!memcmp(&out,&b,sizeof b));
 b.body[12]=1000;presentation60_car(&out,&a,&b,.5f,1);CHECK(out.body[12]==1000);
 b.body[12]=10;for(int k=0;k<3;++k){b.body[k]=-a.body[k];b.body[4+k]=-a.body[4+k];}
 presentation60_car(&out,&a,&b,.5f,1);CHECK(isfinite(out.body[0])&&out.body[0]==b.body[0]);
}
int main(void) {
 const int rates[]={60,90,120,144};
 for(int r=0;r<4;++r)for(int j=0;j<2;++j) {
  reset();run_rate(rates[r],j);CHECK(physics==600&&tracks==600&&tails==600);CHECK(draws==rates[r]*10);
  CHECK(fabsf(G.car.race.total-10)<.001f);if(rates[r]>=120)CHECK(smooth_frames>900);
  printf("%d Hz jitter=%d: logic=%d render=%d changing=%d\n",rates[r],j,physics,draws,smooth_frames);
  reset();G.in_menu=1;run_rate(rates[r],j);CHECK(menu_ticks==600&&physics==0);
  reset();G.paused=1;run_rate(rates[r],j);CHECK(physics==0&&pause_ticks==600);
  reset();G.paused=1;G.vs_race=1;run_rate(rates[r],j);CHECK(physics==600&&pause_ticks==600&&polls==600);
  reset();G.menu.finish=1;run_rate(rates[r],j);CHECK(physics==600&&finish_ticks==600);
  reset();G.movie_len=10000;run_rate(rates[r],j);CHECK(physics==0&&movie_ticks==600&&G.movie_frame==600);
  reset();G.story_end_freeze=180;run_rate(rates[r],j);CHECK(dialogue>=180&&physics==420);
  reset();G.vs_race=1;G.vs_closed=1;run_rate(rates[r],j);CHECK(physics==0&&G.in_menu&&G.vs_closed==0);
 }
 reset();app_present(1.0f/120);CHECK(!physics);G.hud.shift_up=1;app_present(1.0f/120);CHECK(physics==1&&shifts==1);app_present(0.05f);CHECK(physics==4&&shifts==1);
 car_state saved=G.car;app_present(0);CHECK(!memcmp(&saved,&G.car,sizeof saved));
 reset();app_present(1.0f/120);app_timing_reset();app_present(1.0f/120);CHECK(!physics);app_present(1.0f/120);CHECK(physics==1);
 app_present(NAN);app_present(-1);CHECK(physics==1);app_present(5);CHECK(physics==7);app_present(0);CHECK(physics==7);
 reset();G.vs_race=1;close_at=1;app_present(.1f);CHECK(physics==1&&G.vs_closed&&tracks==0);app_present(.1f);CHECK(physics==1);
 reset();G.vs_race=1;abort_at=1;app_present(.1f);CHECK(physics==1&&G.in_menu&&tracks==0);
 reset();G.paused=1;resume_pause=1;app_present(1.0f/60);CHECK(!G.paused&&physics==0);app_present(1.0f/60);CHECK(physics==1);
 reset();G.paused=1;leave_pause=1;app_present(1.0f/60);CHECK(G.in_menu&&physics==0);
 reset();G.menu.finish=1;leave_finish=1;app_present(1.0f/60);CHECK(G.in_menu&&physics==0);
 matrix_tests();
 timing60_display_pacer p={0};CHECK(timing60_display_deadline(&p,1000000000,144)==1000000000);CHECK(p.period==8333333);
 timing60_display_started(&p,1000000000);CHECK(p.next==1008333333);
 timing60_display_reset(&p);CHECK(timing60_display_deadline(&p,2000000000,NAN)==2000000000&&p.period==16666667);
 CHECK(timing60_display_rate(0)==60&&timing60_display_rate(90)==90&&timing60_display_rate(240)==120);
 puts("production fixed logic + presentation branches: PASS (mock RC/network/GPU)");return 0;
}
'''

class HighRefresh(unittest.TestCase):
    def test_display_cap_and_fixed_logic_clock(self):
        code = r'''
#include <assert.h>
#include "timing60.h"
int main(void) {
  assert(timing60_limited_display_rate(120,60)==60 && timing60_limited_display_rate(120,90)==90);
  assert(timing60_limited_display_rate(60,120)==60 && timing60_limited_display_rate(90,0)==90);
  assert(timing60_limited_display_rate(120,240)==120 && timing60_limited_display_rate(NAN,90)==60);
  timing60_display_pacer pacer={0};
  int64_t start=3000000000LL;
  assert(timing60_display_deadline(&pacer,start,timing60_limited_display_rate(120,90))==start);
  assert(pacer.period==11111111); timing60_display_started(&pacer,start);
  assert(pacer.next==start+11111111);
  assert(timing60_display_deadline(&pacer,pacer.next,timing60_limited_display_rate(120,60))==start+11111111);
  assert(pacer.period==16666667);
  timing60_sim sim={0};
  int ticks=0;
  for (int cap=60; cap<=120; cap+=30) {
    double fps=timing60_limited_display_rate(120,cap);
    for (int frame=0; frame<fps; ++frame) ticks+=timing60_sim_steps(&sim,1.0/fps);
  }
  assert(ticks==180);
}
'''
        with tempfile.TemporaryDirectory(prefix='display-cap-', dir=OUT) as d:
            src=Path(d)/'cap.c'; exe=Path(d)/'cap'
            src.write_text(code)
            subprocess.run(['cc','-std=c11','-I',str(ROOT/'src'),str(src),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_production_scheduler_and_app_branches(self):
        s=(ROOT/'src/app.c').read_text()
        tick=function(s,'void app_frame(float dt) {')
        # Compile the unchanged real network/pause/input/movie/freeze/physics/abort
        # branches. Result persistence and the actual GPU renderer are isolated;
        # their guards are covered by existing dedicated production fixtures.
        tick=tick[:tick.index("  /* the time attack console's sounds:")]+'''\n  }\n  app_display_input=in;\n}\n'''
        code=PRE+function((ROOT/'src/hud.c').read_text(),'void hud_input_dt(')+'\n'+tick+'\n'+function(s,'void app_timing_reset(void) {').replace('void app_timing_reset','static void app_timing_reset')+'\n'+function(s,'void app_present(float dt) {')+'\n'+MAIN
        OUT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='hrr-app-',dir=OUT) as d:
            c=Path(d)/'app.c';exe=Path(d)/'app';c.write_text(code)
            subprocess.run(['cc','-std=gnu11','-D__ANDROID__','-Wall','-Wextra','-Werror','-Wno-unused-variable','-Wno-unused-but-set-variable','-Wno-unused-function','-Wno-unused-parameter','-fsanitize=undefined','-fno-sanitize-recover=undefined','-I',str(ROOT/'src'),str(c),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_production_hud_tick_and_repeat_draw(self):
        hud=(ROOT/'src/hud.c').read_text()
        code=r'''
#include <stdio.h>
#include <stdlib.h>
#include "car.h"
#include "timing60.h"
#define CHECK(x) do {if(!(x))exit(1);}while(0)
#define HUD_SIGNS 14
#define BANNER_FRAMES 115
#define CAR_RACE_RUN 0
#define SPR_SIGN 0
static int sign_shown,sign_t,ten_level=0,ten_disp=1;
static int banner_rival=-1,banner_round,banner_chara,banner_frame,banner_on;
static int ten_round=-1,ten_round_wait;
static float extend_at;
static const int TEN_CHARA[10][10]={{0}};
static int ticks,sprites;
static void draw_rival_marks(const car_state *c,int advance){(void)c;CHECK(advance==1);++ticks;}
static void tint(float a,float b,float c,float d){(void)a;(void)b;(void)c;(void)d;}
static void sprite_k(int a,float b,float c,int d,float e){(void)a;(void)b;(void)c;(void)d;(void)e;++sprites;}
'''
        for anchor in ('int hud_sign_blinks(', 'static void ten_disp_update(', 'static void draw_sign(', 'void hud_visual_tick('):
            code+='\n'+function(hud,anchor)
        code+=r'''
int main(void){
 car_state c={0};c.race.state=CAR_RACE_RUN;c.race.sign=1;c.race.ten_sw_name=1;
 for(int hz=60;hz<=144;hz+=(hz==60?30:hz==90?30:24)){
  sign_shown=sign_t=ticks=sprites=banner_frame=banner_on=0;banner_rival=-1;
  timing60_sim timer={0};
  for(int i=0;i<hz*10;++i){int n=timing60_sim_steps(&timer,1.0/hz);while(n--)hud_visual_tick(&c);draw_sign(&c.race);}
  CHECK(ticks==600&&sign_t==0&&banner_frame==115&&sprites==hz*10);
  int before=sign_t;for(int i=0;i<100;++i)draw_sign(&c.race);CHECK(sign_t==before&&banner_frame==115);
 }
 puts("production HUD 60Hz clocks + repeat draw: PASS");return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='hrr-hud-',dir=OUT) as d:
            p=Path(d)/'hud.c';p.write_text(code);exe=Path(d)/'hud'
            subprocess.run(['cc','-std=gnu11','-D__ANDROID__','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=undefined','-I',str(ROOT/'src'),str(p),'-lm','-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

    def test_draw_clock_ownership(self):
        app=(ROOT/'src/app.c').read_text();hud=(ROOT/'src/hud.c').read_text();menu=(ROOT/'src/menu.c').read_text()
        for anchor in ('static void draw_sign(', 'static void draw_ten_banner(', 'static void draw_ten('):
            body=function(hud,anchor)
            self.assertNotIn('sign_t++',body);self.assertNotIn('++banner_frame',body);self.assertNotIn('++ten_round_wait',body)
        self.assertNotIn('clock++',function(menu,'void menu_draw('))
        self.assertNotIn('G.mini_frame++',function(app,'static void mini_draw('))
        self.assertNotIn('--G.mini_move',function(app,'static void mini_draw('))
        self.assertIn('hud_visual_tick(&G.car)',function(app,'void app_frame('))
        main=(ROOT/'src/main_android.c').read_text()
        self.assertIn('    app_present(dt);',main)
        self.assertNotIn('timing60_deadline(&pacer',main)
        self.assertIn('app_timing_reset();',function(app,'void app_suspend('))

    def test_android_refresh_selection(self):
        java=(ROOT/'android/java/com/wmmt/port/MainActivity.java').read_text()
        method=function(java,'static float chooseRefreshRate(')
        main='''class RefreshHost {\n'''+method+'''\nstatic void check(boolean p){if(!p)throw new AssertionError();}
public static void main(String[] x){
  float[] all = {60,90,120,144};
  check(chooseRefreshRate(all,0)==120);
  check(chooseRefreshRate(all,60)==60);
  check(chooseRefreshRate(all,90)==90);
  check(chooseRefreshRate(all,120)==120);
  check(chooseRefreshRate(new float[]{60,120},90)==120);
  check(chooseRefreshRate(new float[]{90,120},60)==120);
  check(chooseRefreshRate(new float[]{60,90},120)==90);
  check(chooseRefreshRate(new float[]{60},90)==60);
  check(chooseRefreshRate(new float[]{144,240,Float.NaN,Float.POSITIVE_INFINITY},0)==60);
  check(chooseRefreshRate(new float[]{59.94f,119.88f,120.01f},0)==119.88f);
  check(chooseRefreshRate(new float[]{59.94f,90,120},60)==59.94f);
  check(chooseRefreshRate(new float[]{},120)==60);
  System.out.println("Android automatic and 60/90/120 refresh selection: PASS");
}}
'''
        with tempfile.TemporaryDirectory(prefix='hrr-java-',dir=OUT) as d:
            p=Path(d)/'RefreshHost.java';p.write_text(main)
            subprocess.run(['javac','-d',d,str(p)],check=True);subprocess.run(['java','-cp',d,'RefreshHost'],check=True)

if __name__=='__main__': unittest.main()
