#!/usr/bin/env python3
"""Compile junction production slices with synthetic dependencies, no private assets."""
from pathlib import Path
import re, subprocess, tempfile
SRC = Path(__file__).resolve().parents[1] / 'src'
app, car = (SRC/'app.c').read_text(), (SRC/'car.c').read_text()
barrier = (SRC/'junction_barrier.c').read_text()
def section(s, a, b):
    assert s.count(a)==1, a
    i=s.index(a); return s[i:s.index(b,i)]
init=section(app,'      memset(&race_junction_ui, 0, sizeof race_junction_ui);','#endif')
tick=section(app,'    car_update(&G.car, &in);','#if defined(__ANDROID__) && defined(WMMT_DEBUG_LOG)')
draw=section(app,'  if (!movie && !G.vs_closed && !G.menu.finish && !G.story_end_freeze &&','#endif')
reader=section(car,'void car_clear_junction(car_race *r) {','\n/* The time attack')
barrier_logic=section(barrier,'void junction_barrier_reset(junction_barrier *b)', '\n/* Rectangle')
scene=section(app,'  if (!movie && !G.vs_closed && !G.menu.finish && c->race.state == CAR_RACE_RUN &&','#endif')
assert app.index('SEG_END(SEG_OPAQUE + pass);') < app.index(scene) < app.index("/* the headlights' pools")
# Verify all three explicit teardown paths include a barrier reset.
for a,b in [('static int vs_abort_to_lobby(void) {','hud_init(&G.hud'),
            ('if (r == MENU_LEAVE) {','menu_vs_closed(&G.menu, "YOU LEFT THE GAME")'),
            ('if (G.menu.finish && menu_finish_update','if (!net_race_done())')]:
    assert 'junction_barrier_reset(&race_junction_barrier);' in section(app,a,b)
closed_entry=section(app,'    if (!G.vs_closed &&\n        (net_host_closed()', '    if (!G.vs_closed && vs_abort_to_lobby())')
assert 'car_clear_junction(&G.car.race);' in closed_entry and 'junction_barrier_reset(&race_junction_barrier);' in closed_entry
frame=section(app,'  int movie = G.movie_len > 0;','    car_update(&G.car, &in);')
for p in (r'if\s*\(!G\.vs_closed\)\s*\{',r'if\s*\(G\.paused\s*&&\s*!G\.vs_race\)\s*steps\s*=\s*0',r'if\s*\(movie\).*?steps\s*=\s*0',r'if\s*\(G\.ten_freeze\s*>\s*0\).*?steps\s*=\s*0',r'else if\s*\(G\.story_end_freeze\s*>\s*0\).*?steps\s*=\s*0',r'for\s*\(int i = 0; i < physics_steps; \+\+i\)\s*\{'):
    assert re.search(p,frame,re.S),p
pre=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <assert.h>
#define __ANDROID__ 1
#define RC_MEM_BASE 0x1000u
#define RC_MEM_SIZE 0x2000u
#define MACHINE_PTR 0x1000u
#define f_8982f4c 1
#define f_8983cd8 2
static unsigned char mem[RC_MEM_SIZE], *rc_mem=mem;
#define VA(x) (mem + ((x)-RC_MEM_BASE))
static uint32_t fake_jct;
static uint32_t *m32(uint32_t x) { if(x==0x98028f0u) return &fake_jct; return (uint32_t*)VA(x); }
#define M32(x) (*m32(x))
#define MF(x) (*(float*)VA(x))
typedef struct { int jct_select_valid,jct_state,jct_left_area,jct_right_area; float jct_distance; int jct_line_valid; float jct_line[3][3]; int state; } car_race;
typedef struct { car_race race; float cam_pos[3]; } car_state;
typedef struct { float v[3]; } junction_barrier_point;
typedef struct { junction_barrier_point start,end; int kind,display_state; } junction_barrier_side;
typedef struct { junction_barrier_side left,right; int ready,manager_state; } junction_barrier;
typedef struct { float m[16]; } mat4;
typedef struct { int unused; } render_params;
static struct { int ready; uint32_t jct_select,jct_decide_line; } P;
static int getter, line_getter; static uint32_t state,left,right; static float dist, raw_line[3][3];
static uint32_t call(int f,int n,uint32_t p,...) { (void)n; if(f==f_8982f4c) { M32(p)=state; M32(p+4)=left; M32(p+8)=right; MF(p+12)=dist; return getter; } if(line_getter) memcpy(VA(p),raw_line,sizeof raw_line); return line_getter; }
'''
mock=r'''
#define CAR_RACE_RUN 1
#define GL_FUNC_ADD 42
typedef struct { int live; } junction_ui;
static junction_ui race_junction_ui; static unsigned char junction_table_private[384];
static junction_barrier race_junction_barrier;
static struct { car_state car; struct { int finish; } menu; int vs_race,vs_closed,story_end_freeze; render_params rp; } G;
/* The extracted tick now also samples the player's tire effect. This fixture
 * tests the junction; the tire integration has its own production-slice test. */
static int movie;
static void player_tracks_tick(const car_state *c) { assert(c==&G.car); }
static int init_ok,init_count,updates,ticks,resets,draws,blend,order,got_state,got_left,got_right; static float got_dist;
static int junction_ui_init(junction_ui *u,const unsigned char *p,size_t n) { assert(p==junction_table_private && n==384 && !u->live); ++init_count; if(init_ok) u->live=1; return init_ok; }
static void junction_ui_tick(junction_ui *u,int s,int l,int r,float d,int a,int b) { assert(u==&race_junction_ui && !a && !b && order==1); order=2; ++ticks; got_state=s;got_left=l;got_right=r;got_dist=d; }
static void junction_ui_reset(junction_ui *u) { assert(u==&race_junction_ui); order=2; ++resets; }
static int barrier_ticks,barrier_resets,scene_phase,scene_draws;
static void junction_barrier_reset(junction_barrier *b) { ++barrier_resets; real_barrier_reset(b); }
static int junction_barrier_tick(junction_barrier *b,int s,int l,int r,const junction_barrier_point *a,const junction_barrier_point *c,const junction_barrier_point *m,float d) {
 assert(b==&race_junction_barrier && order==2 && !l && !r); ++barrier_ticks; return real_barrier_tick(b,s,l,r,a,c,m,d);
}
static void render_begin(render_params *p) { assert(p==&G.rp); scene_phase=1; }
static void junction_barrier_draw(junction_barrier *b,mat4 *vp,const float *eye,float scale,render_params *p) {
 assert(scene_phase==1 && b==&race_junction_barrier && vp && eye==G.car.cam_pos && scale==1.0f && p==&G.rp); scene_phase=2; ++scene_draws;
}
static void render_blend_pass(int n) { assert(scene_phase==2 && n==0); scene_phase=3; }
static void junction_ui_draw(junction_ui *u) { assert(u==&race_junction_ui && blend==GL_FUNC_ADD); ++draws; }
static void glBlendEquation(int x) { blend=x; }
static int in, closed_event, abort_event, arrive_at, pending_closed, pending_abort;
static int menu_calls, abort_calls, completed_loop;
static double frame_start;
/* Inject a simulated packet inside a selected car_update, not before the frame. */
static void car_update(car_state *c,int *p) {
 (void)p; ++updates; order=1; read_junction(&c->race);
 if (updates==arrive_at) { pending_closed=closed_event; pending_abort=abort_event; }
}
static int net_host_closed(void) { return pending_closed; }
static int vs_abort_to_lobby(void) { ++abort_calls; if (!pending_abort) return 0; car_clear_junction(&G.car.race); junction_ui_reset(&race_junction_ui); junction_barrier_reset(&race_junction_barrier); return 1; }
static void menu_frame(int dt,double start) { assert(dt==0 && start==frame_start); ++menu_calls; }
static void race_init(void) {
'''
main=r'''
int main(void) {
 P.ready=1; P.jct_select=0x1100; P.jct_decide_line=0x1200; M32(MACHINE_PTR)=0x1400;
 init_ok=1; race_init(); assert(init_count==1 && race_junction_ui.live);
 init_ok=0; race_init(); assert(init_count==2 && !race_junction_ui.live);
 init_ok=1; race_init(); G.car.race.state=CAR_RACE_RUN;
 getter=1; left=5; right=6; dist=12.5f;
 for(int s=0;s<3;s++) { state=s; step(); assert(order==2 && ticks==s+1 && got_state==s && got_left==5 && got_right==6 && got_dist==12.5f); }
 state=0; step(); assert(got_state==0 && ticks==4 && updates==4); draw(0); assert(draws==1);
 getter=0; step(); assert(resets==1 && !G.car.race.jct_select_valid && !G.car.race.jct_state && !G.car.race.jct_distance); draw(0); assert(draws==1);
 getter=1; state=1; step(); assert(ticks==5); draw(1); assert(draws==1);
 G.vs_closed=1; draw(0); assert(draws==1); G.vs_closed=0;
 G.menu.finish=1; draw(0); assert(draws==1); G.menu.finish=0;
 G.story_end_freeze=1; draw(0); assert(draws==1); G.story_end_freeze=0;
 G.car.race.state=2; draw(0); assert(draws==1); G.car.race.state=CAR_RACE_RUN;
 race_init(); assert(init_count==4 && race_junction_ui.live); draw(0); assert(draws==2);
 state=4; step(); assert(resets==2); state=1; left=75; step(); assert(resets==3);
 left=5; dist=NAN; step(); assert(resets==4); dist=1; P.ready=0; step(); assert(resets==5);
 /* An abort received during car_update must return before either UI hook,
  * including when the raw getter failed; earlier ticks remain accounted for. */
 P.ready=1; getter=1; state=1; G.vs_race=1;
 float initial[3][3]={{1,2,3},{7,8,9},{4,5,6}}; memcpy(raw_line,initial,sizeof initial); line_getter=1;
 step(); assert(race_junction_barrier.ready);
 int u=updates, t=ticks, r=resets, done=completed_loop, ac=abort_calls;
 arrive_at=u+3; abort_event=1; step_many(5);
 assert(updates==u+3 && ticks==t+2 && resets==r+1 && order==2 && !race_junction_barrier.ready);
 assert(menu_calls==1 && completed_loop==done && abort_calls==ac+3);
 assert(!G.car.race.jct_select_valid);
 pending_abort=abort_event=0; race_init();
 u=updates; t=ticks; r=resets; done=completed_loop;
 getter=0; arrive_at=u+1; abort_event=1; step_many(3);
 assert(updates==u+1 && ticks==t && resets==r+1 && menu_calls==2 && completed_loop==done && !race_junction_barrier.ready);
 pending_abort=abort_event=0; getter=1; race_init();
 /* CLOSED takes precedence over simultaneous ABORT and breaks the loop. */
 u=updates; t=ticks; r=resets; done=completed_loop; ac=abort_calls;
 arrive_at=u+2; closed_event=abort_event=1; step_many(4);
 assert(updates==u+2 && ticks==t+1 && resets==r+1 && G.vs_closed==1 && !race_junction_barrier.ready);
 assert(!G.car.race.jct_select_valid && menu_calls==2 && abort_calls==ac+1 && completed_loop==done+1);
 int d=draws; draw(0); assert(draws==d);
 /* A new race can tick and draw again after leaving the closed lobby. */
 pending_closed=pending_abort=closed_event=abort_event=0; G.vs_closed=0; race_init();
 u=updates; t=ticks; arrive_at=0; step_many(2); assert(updates==u+2 && ticks==t+2); draw(0); assert(draws==d+1);
 /* Network event stubs cannot stop an offline race. */
 G.vs_race=0; pending_closed=pending_abort=1; u=updates; t=ticks; ac=abort_calls;
 step_many(2); assert(updates==u+2 && ticks==t+2 && abort_calls==ac && !G.vs_closed && menu_calls==2);
 /* Three engine vectors pass unchanged to the real barrier state machine. */
 pending_closed=pending_abort=0; G.vs_race=0; getter=1; state=1; line_getter=1;
 float points[3][3]={{1,2,3},{7,8,9},{4,5,6}}; memcpy(raw_line,points,sizeof points);
 race_init(); assert(!race_junction_barrier.ready); int bt=barrier_ticks; step();
 assert(barrier_ticks==bt+1 && race_junction_barrier.ready && race_junction_barrier.manager_state==1);
 assert(!memcmp(race_junction_barrier.left.start.v,points[0],sizeof points[0]));
 assert(!memcmp(race_junction_barrier.left.end.v,points[2],sizeof points[2]));
 assert(!memcmp(race_junction_barrier.right.end.v,points[1],sizeof points[1]));
 line_getter=0; state=2; step(); assert(race_junction_barrier.ready && race_junction_barrier.manager_state==2);
 state=3; step(); assert(race_junction_barrier.ready && race_junction_barrier.manager_state==3);
 int sd=scene_draws; scene_draw(0); assert(scene_draws==sd+1 && scene_phase==3);
 scene_draw(1); assert(scene_draws==sd+1 && !scene_phase);
 G.vs_closed=1; scene_draw(0); assert(scene_draws==sd+1 && !scene_phase); G.vs_closed=0;
 G.menu.finish=1; scene_draw(0); assert(scene_draws==sd+1); G.menu.finish=0;
 G.car.race.state=2; scene_draw(0); assert(scene_draws==sd+1); G.car.race.state=CAR_RACE_RUN;
 getter=0; int br=barrier_resets; step(); assert(barrier_resets==br+1 && !race_junction_barrier.ready);
 scene_draw(0); assert(scene_draws==sd+1 && !scene_phase);
 getter=1; state=1; line_getter=1; step(); assert(race_junction_barrier.ready);
 race_init(); assert(!race_junction_barrier.ready); /* re-entry / rematch */
 car_clear_junction(NULL); puts("junction app/car slices passed"); return 0;
}
'''
source=pre+reader+'\n#define junction_barrier_reset real_barrier_reset\n#define junction_barrier_tick real_barrier_tick\n'+barrier_logic+'\n#undef junction_barrier_reset\n#undef junction_barrier_tick\n'+mock+init+'\n}\nstatic void step_many(int steps) {\nint executed_physics_ticks=0;\nfor (int i=0; i<steps; ++i) {\n'+tick+'\n}\n(void)executed_physics_ticks;\n++completed_loop;\n}\nstatic void step(void) { step_many(1); }\nstatic void draw(int movie) { car_state *c=&G.car;\n'+draw+'\n}\nstatic void scene_draw(int movie) { car_state *c=&G.car; mat4 vp={{0}}; scene_phase=0;\n'+scene+'\n}\n'+main
with tempfile.TemporaryDirectory(prefix='junction-host-',dir='/Volumes/CodexWork') as d:
    c=Path(d)/'test.c'; exe=Path(d)/'test'; c.write_text(source)
    subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror',str(c),'-lm','-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
