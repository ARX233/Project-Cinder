#!/usr/bin/env python3
"""Compile production carry/movie functions with isolated host stubs, not a device test."""
from pathlib import Path
import os, subprocess, tempfile

src = (Path(__file__).resolve().parents[1] / 'src/app.c').read_text()
def function(name):
    i = src.index(name); left = src.index('{', i); depth = 0
    for j in range(left, len(src)):
        depth += (src[j] == '{') - (src[j] == '}')
        if not depth:
            return src[i:j + 1]
    raise ValueError(name)
funcs = '\n'.join(function(x) for x in (
    'static int story_next_race(', 'static int story_period_suspend(', 'static void story_carry_cancel(',
    'static int story_carry_capture(', 'static void story_carry_arm(',
    'static void story_carry_rearm(', 'static void story_carry_finish(',
    'static void story_race_start_failed(', 'static int movie_open(',
    'static void movie_close('))
menu_start = src.index('static void menu_frame(float dt, double frame_start) {')
# The renderer is now menu_present(), so the next glViewport is no longer the
# end of the menu's context guard. Compile the exact production statement this
# fixture exercises, without importing unrelated load/VS/Ghost/renderer state.
guard_start = src.index('  if (G.story_carry_token &&', menu_start)
guard_end = src.index('story_carry_cancel();', guard_start) + len('story_carry_cancel();')
menu_guard = src[guard_start:guard_end]
funcs += '\nstatic void check_menu_context(void) {\n' + menu_guard + '\n}'
# The initial Init must arm only after the actual loaded-rival array is set,
# and cannot carry across an unrelated or failed start.
rivals_at = src.index('    if (!ghost) car_set_rivals(rv,')
startup_start = src.rfind('    load_sync(NULL);', menu_start, rivals_at)
assert startup_start >= 0
startup = src[startup_start:src.index('      spark_reset(); backfire_reset();', rivals_at)]
assert startup.index('car_set_rivals(rv,') < startup.index('story_carry_arm(rv,') < startup.index('car_start(&G.car,')
assert 'ten || vs || !story_slots_valid' in startup and 'story_carry_cancel();' in startup
assert 'G.story_old_ended = 0;' in startup and 'story_race_start_failed();' in startup
rows_start = src.index('    for (int i = 0; i < n_rival; ++i) {\n      int k = G.n_rival, pack = rival_look(')
# Preserve the whole original rival-loading for-block; the newly adjacent
# Ghost model setup is a separate branch, not part of this Story fixture.
rows_loop = function('    for (int i = 0; i < n_rival; ++i) {\n      int k = G.n_rival, pack = rival_look(')
funcs += '\nstatic int check_loaded_rows(int *rows, int n_rival) { car_rival rv[CAR_RIVALS]; int story_slots_valid=1; G.n_rival=0;\n' + rows_loop + '\nreturn story_slots_valid; }\n'
pre = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#define CAR_RIVALS 3
#define RACE_ROWS 3
#define RIVALDB_N 4
#define STORYMOVIE_N 1
#define MENU_GAME_STORY 3
#define MENU_PRE 8
#define MOVIE_FADE 20
typedef struct { unsigned type; float tyres[6]; int spokes, character, level, losses, series; } car_rival;
typedef struct { int unused; } car_spec;
typedef struct { int select,race,slot,character,type,series; } rival_row;
static const rival_row RIVALDB[RIVALDB_N]={{0,0,0,39,34,24},{0,1,0,39,34,25},{1,0,0,50,8,50},{0,1,1,39,34,25}};
typedef rival_row rivaldb_rival;
static const float CARDB_TYRES[1][7]={{1,2,3,4,5,6,7}};
typedef struct {int select,race,movie,fade,demo,cars[3];} storymovie;
static const storymovie STORYMOVIE[STORYMOVIE_N]={{0,1,25,1,7,{34,0,0}}};
typedef struct { int over,won,play_state; float time_left; } car_race;
typedef struct { car_race race; } car_state;
static struct {
 uint64_t story_carry_serial,story_carry_token;
 int story_carry_select,story_carry_period,story_carry_series,story_carry_attempted,story_old_ended,story_race_slots_valid;
 int vs_race,n_ten,rival,story_race,story_cut_pending,in_menu,paused,n_rival;
 int race_nrv,race_course,rival_pack[3],movie_paint[3],rival_paint[3],movie_fade,movie_in,race_frames,time_shown;
 float movie_len,movie_frame,top_kmh;
 car_rival race_rv[3];car_spec race_spec;car_state car;
 void *movie_model[3],*rival_model[3];
 struct {int game,screen,story_pick,pre_quiet,manual,finish,finish_story;} menu;
 struct {int screen_w,screen_h;} hud;
} G;
static int capture_result, captures,arms,loads,finals,cancels,start_calls,fail_start,next_loaded;
static int movie_starts,movie_ends,movie_updates,demo_starts,demo_ends,menu_opens;
static float movie_length;
static int car_story_carry_capture(uint64_t t,int s){assert(t&&s==24);captures++;return capture_result;}
static int car_story_carry_arm(uint64_t t,int s){assert(t&&s==25);arms++;return 1;}
static int car_story_carry_loaded(uint64_t t){assert(t);return loads;}
static int car_story_carry_finalize(uint64_t t){assert(t&&loads);finals++;return 1;}
static void car_story_carry_cancel(void){cancels++;loads=0;}
static void car_set_rivals(const car_rival*r,int n){assert(r&&n==G.race_nrv);}
static int car_start(car_state*c,int course,int manual,const car_spec*spec){assert(c==&G.car&&course==G.race_course&&manual==G.menu.manual&&spec==&G.race_spec);start_calls++;if(fail_start)return -1;loads=next_loaded;return 0;}
static float car_movie_start(car_state*c,int id,const car_spec*p,const car_rival*r,int n){assert(c==&G.car&&id==25&&p==&G.race_spec&&r&&n==3);movie_starts++;loads=0;return movie_length;}
static void car_movie_end(void){movie_ends++;}
static int car_movie_update(car_state*c,float f){assert(c==&G.car&&f==0);movie_updates++;return 1;}
static void hud_demo_start(int d){assert(d==7);demo_starts++;}
static void hud_demo_end(void){demo_ends++;}
static void hud_init(void*p,int w,int h){(void)p;(void)w;(void)h;}
static void menu_open(void*p){(void)p;menu_opens++;}
static void spark_reset(void){}
static void backfire_reset(void){}
static int skip_row=-1;
static int rival_look(int row,int *paint){*paint=0;return row==skip_row?-1:0;}
static int rival_base(int row,int *paint){(void)row;*paint=0;return 0;}
static void pack_load_now(int pack,int paint){(void)pack;(void)paint;}
static int menu_story_loop(void *m){(void)m;return 0;}
static int menu_story_losses(void *m){(void)m;return 0;}
'''
main = r'''
static void reset(void){
 memset(&G,0,sizeof G);captures=arms=loads=finals=cancels=start_calls=fail_start=0;
 movie_starts=movie_ends=movie_updates=demo_starts=demo_ends=menu_opens=0;
 capture_result=1;next_loaded=1;movie_length=320;skip_row=-1;
 G.menu.game=MENU_GAME_STORY;G.menu.story_pick=0;G.rival=0;G.story_race=0;
 G.car.race.over=G.car.race.won=1;G.car.race.play_state=10;
 G.race_nrv=1;G.n_rival=1;G.story_race_slots_valid=1;
 G.race_rv[0]=(car_rival){.type=34,.character=39,.series=24};
}
static void advance(void){
 G.menu.screen=MENU_PRE;G.menu.pre_quiet=G.story_cut_pending=1;G.story_race=1;G.rival=1;
 G.race_rv[0].series=25;
}
int main(void){
 reset();assert(story_carry_capture()==1&&captures==1&&G.story_old_ended&&G.story_carry_token);
 assert(!story_carry_capture()&&captures==1);advance();story_carry_arm(G.race_rv,1);assert(arms==1);
 assert(!car_start(&G.car,G.race_course,G.menu.manual,&G.race_spec));
 /* No movie: the initial accepted Init is final. */
 assert(movie_open(0,0,0,0)==0);story_carry_finish();assert(finals==1&&!G.story_carry_token);
 /* A real movie resets loaded; final Init must load again before finalizing. */
 reset();assert(story_carry_capture());advance();story_carry_arm(G.race_rv,1);
 assert(!car_start(&G.car,G.race_course,G.menu.manual,&G.race_spec));
 int rows[1]={1};assert(movie_open(0,1,rows,1)==0&&G.movie_len==320&&loads==0&&G.story_carry_token);
 movie_close();assert(finals==1&&arms==2&&start_calls==2&&!G.story_carry_token&&!G.story_old_ended);
 movie_close();assert(finals==1&&start_calls==2&&movie_ends==1);
 /* Missing trails immediately restore through a second Init. */
 reset();assert(story_carry_capture());advance();story_carry_arm(G.race_rv,1);
 assert(!car_start(&G.car,G.race_course,G.menu.manual,&G.race_spec));movie_length=0;
 assert(movie_open(0,1,rows,1)==0&&start_calls==2&&movie_ends==1&&G.movie_len==0);
 story_carry_finish();assert(finals==1&&!G.story_carry_token);
 /* A valid Init that did not consume carry uses ordinary fallback. */
 reset();assert(story_carry_capture());advance();story_carry_arm(G.race_rv,1);
 next_loaded=0;assert(!car_start(&G.car,G.race_course,G.menu.manual,&G.race_spec));
 story_carry_finish();assert(finals==0&&cancels==1&&!G.story_carry_token&&!G.in_menu);
 /* Failed final Init leaves no old sequence or retained token in gameplay. */
 reset();assert(story_carry_capture());advance();story_carry_arm(G.race_rv,1);
 assert(!car_start(&G.car,G.race_course,G.menu.manual,&G.race_spec));
 assert(movie_open(0,1,rows,1)==0);fail_start=1;movie_close();
 assert(G.in_menu&&G.story_old_ended&&!G.story_carry_token&&menu_opens==1&&!finals);
 /* Failed missing-trail Init is returned to caller for the same safe path. */
 reset();assert(story_carry_capture());advance();story_carry_arm(G.race_rv,1);
 movie_length=0;fail_start=1;assert(movie_open(0,1,rows,1)<0);story_race_start_failed();
 assert(G.in_menu&&G.story_old_ended&&!G.story_carry_token&&menu_opens==1);
 /* Distinct token, wrong context or compressed rival are never restored. */
 reset();assert(story_carry_capture());advance();G.menu.pre_quiet=0;story_carry_arm(G.race_rv,1);
 assert(!G.story_carry_token&&arms==0&&cancels==1);
 reset();assert(story_carry_capture());advance();G.race_rv[0].character=40;story_carry_arm(G.race_rv,1);
 assert(!G.story_carry_token&&arms==0&&cancels==1);
 reset();G.story_race_slots_valid=0;assert(!story_carry_capture()&&captures==0&&cancels==1);
 /* Use the actual loading loop, including skipped and compressed rows. */
 reset();int good_rows[1]={0};assert(check_loaded_rows(good_rows,1));
 reset();int bad_slots[2]={0,2};assert(!check_loaded_rows(bad_slots,2));
 reset();int duplicate[2]={0,3};assert(!check_loaded_rows(duplicate,2));
 reset();skip_row=0;assert(!check_loaded_rows(duplicate,2));
 /* Automatic quiet period keeps the token; a menu departure cannot. */
 reset();assert(story_carry_capture());advance();check_menu_context();assert(G.story_carry_token&&cancels==0);
 G.menu.screen=0;check_menu_context();assert(!G.story_carry_token&&cancels==1);
 reset();assert(story_carry_capture());advance();G.menu.story_pick=1;check_menu_context();
 assert(!G.story_carry_token&&cancels==1);
 /* Only a winning, continuous story Suspend may suppress the Win event. */
 reset();assert(story_period_suspend());
 reset();G.menu.game=1;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 reset();G.car.race.won=0;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 reset();G.car.race.over=0;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 reset();G.car.race.play_state=8;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 reset();G.story_race=1;G.rival=1;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 reset();G.menu.story_pick=1;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 reset();G.rival=-1;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 reset();G.vs_race=1;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 reset();G.n_ten=1;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 reset();G.movie_len=2;assert(!story_period_suspend()&&!story_carry_capture()&&!captures);
 /* -1 means End never ran; Win stays suppressed for the same continuation. */
 reset();capture_result=-1;assert(!story_carry_capture()&&!G.story_old_ended&&!G.story_carry_token&&story_period_suspend());
 reset();capture_result=0;assert(story_carry_capture()&&G.story_old_ended&&!G.story_carry_token);
 puts("production app carry/movie fragments passed");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='story-carry-app-') as d:
    env = dict(os.environ, TMPDIR=d, TMP=d, TEMP=d, HOME=d, XDG_CACHE_HOME=d)
    c, exe = Path(d)/'fixture.c', Path(d)/'fixture'
    c.write_text(pre + funcs + main)
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True,env=env,cwd=d)
    subprocess.run([str(exe)],check=True,env=env,cwd=d)
