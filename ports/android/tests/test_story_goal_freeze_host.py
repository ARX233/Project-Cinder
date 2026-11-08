#!/usr/bin/env python3
"""Compile extracted production goal-freeze logic; never touches device or saves."""
from pathlib import Path
import os, subprocess, tempfile, unittest
SRC = Path(__file__).resolve().parents[1] / 'src/app.c'
WORK = str(Path(os.environ.get('TMPDIR', str(SRC.parents[2] / 'tmp'))).resolve())
Path(WORK).mkdir(parents=True, exist_ok=True)

def segment(s,a,b):
    i=s.index(a); return s[i:s.index(b,i)]

class GoalFreeze(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
    s=SRC.read_text()
    entry=segment(s,'  if (!movie && !G.vs_closed && !G.menu.finish && !G.story_end_started', '  car_input in = {0};')
    sim=segment(s,'  int frozen = G.ten_freeze','  /* the time attack console\'s sounds:')
    trigger=segment(s,'  if (race->over && !G.menu.finish && !movie && !G.story_end_started','#ifdef __ANDROID__\n  int vs_finish_ready = 1;')
    finish=segment(s,'  if (!app_ghost_mode() && race->over && !G.menu.finish && !G.vs_closed && !movie && G.story_end_freeze <= 0 && vs_finish_ready)','    int goal = race->state')
    render=segment(s,'  if (G.ten_freeze > 0 || G.story_end_freeze > 0) hud_negate','  if (!movie && G.movie_in > 0)')
    controls=segment(s,'  if (G.story_end_freeze > 0 || G.story_old_ended)\n    G.hud.camera_pressed', '  /* app_present supplies one exact 60 Hz logic interval')
    pre=r"""
#include <stdio.h>
#include <stdlib.h>
#define CAR_RACE_GOAL 2
#define CAR_RACE_RUN 1
#define MENU_GAME_STORY 3
#define CAR_RIVALS 2
#define TEN_WHITE_HOLD 2
#define TEN_WHITE_FADE 2
#define SND_BEATEN 4
#define MOVIE_FADE 20
/* Legacy Story/VS scenarios retain their historical synthetic mode numbers. */
static int app_ghost_mode(void){return 0;}
typedef struct {int over,won,state,play_state,ten_beaten; float countdown;} car_race;
typedef struct {int shift_up,shift_down;} car_input;
static struct {int ten_freeze,story_end_freeze,story_end_started,story_old_ended,ten_bgm_off,ten_white,n_ten,ten_beaten_on,vs_race,rival,paused,vs_closed,movie_fade; float fps,movie_len,movie_frame; struct {int finish,game;} menu; struct {int camera_pressed,reset_pressed;} hud; int camera; struct {car_race race; float wall_hit; int body,effect,rival_body[2],rival_effect[2],rival_shown[2];} car;} G;
#define CAR_VIEW_ROOF 1
#define CAR_VIEW_BEHIND 0
static int physics,dialogue,goal_at,negates,draws,order,control_actions;
static int network_event,cleared,abort_calls,menu_calls,sound_calls,rev_quiets;
static int capture_at,capture_result,capture_calls,observed_ticks;
static int continuation,suspend_at,suspends,win_events,cut_finished;
static int story_period_suspend(void){
 return continuation && !G.vs_race && !G.n_ten && G.movie_len<=0 && G.menu.game==MENU_GAME_STORY &&
        G.rival>=0 && G.car.race.over && G.car.race.won && G.car.race.play_state==10;
}
static void hud_story_cutin_suspend(void){suspends++;cut_finished=1;}
static int story_carry_capture(void){
 if(!capture_at || physics!=capture_at)return 0;
 capture_calls++; capture_at=0;
 if(capture_result<0)return 0;
 G.story_old_ended=1; return 1;
}
/* This is an app control-flow fixture; HUD FIFO timing is tested separately. */
static int hold_ticks=180,hold_calls,result_seen,inject_late_goal;
static int net_host_closed(void){return network_event==1 && physics>0;}
static int vs_abort_to_lobby(void){abort_calls++; return network_event==2 && physics>0;}
static void car_clear_junction(car_race*r){(void)r;cleared++;}
static void menu_frame(int n,double t){(void)n;(void)t;menu_calls++;}
static void snd_update(void*c,car_input*i,float dt){(void)c;(void)i;(void)dt;sound_calls++;}
static void snd_rev_quiet(void){rev_quiets++;}
static void car_view(int x){(void)x;control_actions++;}
static void car_reset(void*x){(void)x;control_actions++;}
static void hud_story_cutin_step(car_race*r,int h){(void)h;dialogue++;if(r->over)result_seen=1;
 if(r->over&&r->won&&r->play_state==10&&!cut_finished){win_events++;cut_finished=1;}
}
static int hud_story_cutin_goal_hold(car_race*r){if(r!=&G.car.race)abort();hold_calls++;if(r->over&&!result_seen)hud_story_cutin_step(r,0);return hold_ticks;}
static void hud_ten_cutin(car_race*r,int n){(void)r;(void)n;}
static void car_update(void*c,car_input*i){(void)c;(void)i;physics++;
 if(goal_at && physics==goal_at) G.car.race.state=CAR_RACE_GOAL,G.car.race.over=1;
 if(suspend_at && physics==suspend_at) G.car.race.play_state=10,G.car.race.over=G.car.race.won=1;
}
static void backfire_tick(void){}
static void spark_step(int a,int b,void*c){(void)a;(void)b;(void)c;}
static void snd_menu(int x){(void)x;}
static void hud_negate(void*h){(void)h;negates++;order=order*10+1;}
static void hud_demo_draw(void*h){(void)h;}
static void hud_fade(void*h,int c,float x){(void)h;(void)c;(void)x;}
static int fade_grey(int x){return x;}
static void hud_draw(void*h,void*c,car_input*i,float f){(void)h;(void)c;(void)i;(void)f;}
static void menu_finish_warm(int x){(void)x;}
static void menu_finish_draw(void*x){(void)x;order=order*10+2;}
static void hud_story_cutin_draw(void){draws++;order=order*10+3;}
static void frame(int steps,int movie){car_input in={0};car_race*race=&G.car.race; float dt=1.0f/60; double frame_start=0; if((G.paused&&!G.vs_race)||movie)steps=0;
"""
    # Simulate a goal arriving after the extracted loop, before the fallback.
    mid='\nobserved_ticks=executed_physics_ticks;\nif(inject_late_goal){race->state=CAR_RACE_GOAL;race->over=1;inject_late_goal=0;}\n'+trigger+'\nint vs_finish_ready=1;\n'+finish+' G.menu.finish=1; }\n}\n'
    post='\nstatic void controls(void){\n'+controls+'\n}\n'
    post+='\nstatic void draw(int movie){car_input in={0}; __typeof__(G.car)*c=&G.car;\n'+render+'\n}\n'
    post+=r"""
int main(int argc,char**argv){int scenario=argc>1?atoi(argv[1]):0;
 G.menu.game=MENU_GAME_STORY;G.rival=0;G.car.race.state=CAR_RACE_GOAL;G.car.race.over=1;
 if(scenario==1)G.car.race.state=CAR_RACE_RUN;
 if(scenario==2)G.car.race.over=0;
 if(scenario==3)G.menu.game=4;
 if(scenario==4)G.vs_race=1;
 if(scenario==5)G.n_ten=1;
 if(scenario==6){G.car.race.state=CAR_RACE_RUN;G.car.race.over=0;goal_at=1;}
 if(scenario==7)G.rival=-1;
 /* Model a HUD FIFO whose remaining two lines need 299 ticks. */
 if(scenario==13||scenario==14||scenario==15){
   hold_ticks=299;
   if(scenario>=14){G.car.race.state=CAR_RACE_RUN;G.car.race.over=0;}
   if(scenario==14)goal_at=1;
   if(scenario==15)inject_late_goal=1;
   frame(scenario==14?5:1,0);
   printf("%d %d %d %d %d %d\n",G.story_end_started,G.story_end_freeze,G.menu.finish,physics,dialogue,hold_calls);
   G.paused=1;frame(50,0);G.paused=0;
   printf("%d %d %d %d\n",G.story_end_freeze,physics,dialogue,hold_calls);
   frame(scenario>=14?298:297,0);draw(0);
   printf("%d %d %d %d %d %d\n",G.story_end_freeze,G.menu.finish,physics,dialogue,hold_calls,negates);
   frame(1,0);draw(0);frame(1,0);
   printf("%d %d %d %d %d %d\n",G.story_end_freeze,G.menu.finish,physics,dialogue,hold_calls,negates);
   return 0;
 }
 if(scenario==11||scenario==12){G.vs_race=1;G.car.race.state=CAR_RACE_RUN;G.car.race.over=0;goal_at=1;capture_at=1;network_event=scenario-10;frame(5,0);if(capture_calls)abort();if(scenario==11)draw(0);printf("%d %d %d %d %d %d %d %d %d %d\n",physics,dialogue,G.vs_closed,G.menu.finish,G.story_end_started,cleared,abort_calls,menu_calls,sound_calls,order);return 0;}
 if(scenario>=19 && scenario<=21){
  G.car.race.state=CAR_RACE_RUN;G.car.race.over=0;G.car.race.won=0;
  continuation=scenario!=21;suspend_at=1;capture_at=scenario==21?0:1;capture_result=scenario==19?-1:0;
  frame(5,0);printf("%d %d %d %d %d %d\n",physics,dialogue,suspends,win_events,G.story_old_ended,capture_calls);
  frame(5,0);printf("%d %d %d %d %d %d\n",physics,dialogue,suspends,win_events,G.story_old_ended,capture_calls);return 0;
 }
 if(scenario>=16 && scenario<=18){
  G.car.race.state=CAR_RACE_RUN;G.car.race.over=0;
  capture_at=scenario==18?3:1;capture_result=scenario==16?-1:scenario==17?0:1;
  frame(5,0);printf("%d %d %d %d %d\n",physics,dialogue,G.story_old_ended,capture_calls,observed_ticks);
  frame(5,0);printf("%d %d %d %d %d\n",physics,dialogue,G.story_old_ended,capture_calls,observed_ticks);
  G.paused=1;frame(5,0);printf("%d %d %d %d %d\n",physics,dialogue,G.story_old_ended,capture_calls,observed_ticks);return 0;
 }
 if(scenario==8){G.story_end_freeze=10;G.car.race.state=CAR_RACE_RUN;G.car.race.play_state=2;G.hud.camera_pressed=G.hud.reset_pressed=1;controls();printf("%d %d %d\n",control_actions,G.hud.camera_pressed,G.hud.reset_pressed);return 0;}
 if(scenario==9){G.story_end_started=1;G.story_end_freeze=2;frame(20,0);printf("%d %d %d %d\n",G.story_end_freeze,G.menu.finish,physics,dialogue);return 0;}
 if(scenario==22||scenario==23){
  if(scenario==22){G.story_end_started=1;G.story_end_freeze=10;}
  else {G.car.race.state=CAR_RACE_RUN;G.car.race.over=0;goal_at=1;}
  frame(5,0);printf("%d %d\n",rev_quiets,G.story_end_freeze);return 0;
 }
 if(scenario==24){
  G.car.race.state=CAR_RACE_RUN;G.car.race.over=0;capture_at=1;capture_result=0;
  frame(5,0);printf("%d %d\n",rev_quiets,G.story_old_ended);
  frame(5,0);printf("%d %d\n",rev_quiets,G.story_old_ended);
  G.story_old_ended=0;frame(1,0);printf("%d %d\n",rev_quiets,G.story_old_ended);return 0;
 }
 frame(scenario==6?5:1,scenario==10);draw(scenario==10);
 printf("%d %d %d %d %d %d %d %d\n",G.story_end_started,G.story_end_freeze,G.menu.finish,physics,dialogue,negates,draws,order);
 if(!scenario){G.paused=1;frame(40,0);printf("%d %d %d\n",G.story_end_freeze,physics,dialogue);G.paused=0;frame(178,0);draw(0);printf("%d %d %d %d %d\n",G.story_end_freeze,G.menu.finish,physics,dialogue,negates);frame(1,0);draw(0);frame(2,0);printf("%d %d %d %d %d\n",G.story_end_freeze,G.menu.finish,physics,dialogue,negates);}
 return 0;}
"""
    cls.tmp=tempfile.TemporaryDirectory(prefix='story-goal-',dir=WORK)
    c=Path(cls.tmp.name)/'fixture.c';cls.exe=Path(cls.tmp.name)/'fixture';c.write_text(pre+entry+sim+mid+post)
    subprocess.run(['cc','-std=gnu11','-w',str(c),'-o',str(cls.exe)],check=True,env=dict(os.environ,TMPDIR=WORK))
 @classmethod
 def tearDownClass(cls): cls.tmp.cleanup()
 def run_case(self,n):
    return [list(map(int,x.split())) for x in subprocess.check_output([str(self.exe),str(n)],text=True,env=dict(os.environ,TMPDIR=WORK)).splitlines()]
 def test_freeze_and_render(self):
    start,paused,almost,done=self.run_case(0)
    self.assertEqual(start[:5],[1,179,0,0,2]);self.assertEqual(start[5:],[1,1,123])
    self.assertEqual(paused,[179,0,2]);self.assertEqual(almost,[1,0,0,180,2])
    self.assertEqual(done,[0,1,2,183,2])
 def test_exclusions(self):
    for n in (1,2,3,4,5,7,10):
     with self.subTest(scenario=n):self.assertEqual(self.run_case(n)[0][:2],[0,0])
 def test_closed_during_car_update(self):
    self.assertEqual(self.run_case(11)[0],[1,0,1,0,0,1,0,0,0,3])
 @unittest.skipUnless('net_abort_pending' in (SRC.parent / 'net.h').read_text(), 'WV2 abort handshake is unavailable in upstream WV1')
 def test_wv2_abort_during_car_update(self):
    self.assertEqual(self.run_case(12)[0],[1,0,0,0,0,0,1,1,0,0])
 def test_intermediate_win_suppression(self):
     # No bridge: End never ran, but repeated Suspend ticks must not queue Win.
     first, following = self.run_case(19)
     self.assertEqual(first,[5,0,5,0,0,1]);self.assertEqual(following,[10,0,10,0,0,1])
     # End ran even though capture failed: tail and later UI ticks cannot requeue Win.
     first, following = self.run_case(20)
     self.assertEqual(first,[1,4,1,0,1,1]);self.assertEqual(following,[1,9,1,0,1,1])
     # A non-continuous state 10 retains the original result event path.
     first, following = self.run_case(21)
     self.assertEqual(first,[5,5,0,1,0,0]);self.assertEqual(following,[10,10,0,1,0,0])
 def test_carry_capture_and_ui_time(self):
     rejected, continued, paused = self.run_case(16)
     self.assertEqual(rejected,[5,5,0,1,5]);self.assertEqual(continued,[10,10,0,1,5]);self.assertEqual(paused,[10,10,0,1,0])
     for scenario, first_tick in ((17,1),(18,3)):
      with self.subTest(scenario=scenario):
       first, following, paused = self.run_case(scenario)
       self.assertEqual(first,[first_tick,5,1,1,first_tick])
       self.assertEqual(following,[first_tick,10,1,1,0])
       self.assertEqual(paused,[first_tick,10,1,1,0])
 def test_large_batch_expires_once(self):
    self.assertEqual(self.run_case(9)[0],[0,1,0,2])
 def test_extended_two_line_hold(self):
    for scenario, physics, initial_freeze, initial_dialogue, almost_dialogue in ((13,0,298,2,299),(14,1,299,1,299),(15,1,299,2,300)):
     with self.subTest(scenario=scenario):
      start,paused,almost,done=self.run_case(scenario)
      self.assertEqual(start,[1,initial_freeze,0,physics,initial_dialogue,1])
      self.assertEqual(paused,[initial_freeze,physics,initial_dialogue,1])
      self.assertEqual(almost,[1,0,physics,almost_dialogue,1,1])
      self.assertEqual(done,[0,1,physics+1,almost_dialogue+2,1,1])
 def test_rev_loop_quiet_during_and_on_entry_to_freeze(self):
    for scenario in (22, 23):
     with self.subTest(scenario=scenario):
      quiet, remaining = self.run_case(scenario)[0]
      self.assertEqual(quiet, 1)
      self.assertGreater(remaining, 0)
 def test_rev_loop_quiet_for_ended_old_story_sequence(self):
    first, following, restarted = self.run_case(24)
    self.assertEqual(first, [1, 1])
    self.assertEqual(following, [2, 1])
    self.assertEqual(restarted, [2, 0])
 def test_frozen_controls(self):
    self.assertEqual(self.run_case(8)[0],[0,0,0])
 def test_goal_mid_batch(self):
    row=self.run_case(6)[0];self.assertEqual(row[:3],[1,180,0]);self.assertEqual(row[3],1,'physics advanced after goal')
if __name__=='__main__': unittest.main()
