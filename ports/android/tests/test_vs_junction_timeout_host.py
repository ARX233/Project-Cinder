#!/usr/bin/env python3
"""Host-only source-slice fixture. Fake clock, net, UI boundary and physics; not an APP."""
from pathlib import Path
import os, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
test=(root/'tests/test_app_recovery.py').read_text()
# Reuse its source extraction and fake recovery boundaries, without running its tests.
ns={'__file__':str(root/'tests/test_app_recovery.py')}
exec(test[:test.index("post=r'''")],ns)
pre=ns['pre']; funcs=ns['func']; app=ns['s']; take=ns['take']
ui=(root/'src/junction_ui.c').read_text(); barrier=(root/'src/junction_barrier.c').read_text(); car=(root/'src/car.c').read_text()
def slice_between(s,a,b): return s[s.index(a):s.index(b,s.index(a))]
pre=pre.replace('#include "net.h"','#include "net.h"\n#include "junction_ui.h"\n#include "junction_barrier.h"\ntypedef struct { int jct_select_valid,jct_state,jct_left_area,jct_right_area; float jct_distance; int jct_line_valid; float jct_line[3][3]; } car_race;')
assert pre.count('struct { int race; } car;') == 1
pre=pre.replace('struct { int race; } car;', 'struct { car_race race; } car;')
pre=pre.replace('static int race_junction_ui,race_junction_barrier;', 'static junction_ui race_junction_ui; static junction_barrier race_junction_barrier;')
assert pre.count('static void car_clear_junction(int*x){(void)x;}') == 1
pre=pre.replace('static void car_clear_junction(int*x){(void)x;}','void car_clear_junction(car_race *x);')
pre=pre.replace('static void junction_ui_reset(int*x){(void)x;}','')
pre=pre.replace('static void junction_barrier_reset(int*x){(void)x;}','')
realcar=slice_between(car,'void car_clear_junction(car_race *r) {','\n/* VA checks')
realui=slice_between(ui,'static uint32_t le32(', '\nstatic int pair(')
realbarrier=slice_between(barrier,'void junction_barrier_reset(', '\n/* Rectangle')
# The actual post-physics app guard, embedded in a deliberately small host loop.
guard=app[app.index('    if (G.vs_race && vs_recovery_observe_now() && vs_abort_to_lobby()) { menu_frame(0, frame_start); return; }'):]
guard=guard[:guard.index('\n')]
post=r'''
static int commits, physics_ticks, menu_frames;
static double frame_start;
static void menu_frame(int dt,double t){(void)dt;(void)t;menu_frames++;}
static void packet(net_player *p,uint64_t nonce,uint32_t race,uint32_t seq,int flag){unsigned char base[21]={0};vs_recovery_wire_extension e={flag,race,nonce,seq};assert(vs_recovery_wire_encode(p->profile,sizeof p->profile,base,sizeof base,&e));p->profile_len=42;}
static void setup(void){vs_abort_history_reset(&VH);VH_has_time=VH_abort_unknown=0;VH_last_time=0;memset(&G,0,sizeof G);memset(&VR,0,sizeof VR);memset(&L,0,sizeof L);G.vs_id=11;G.vs_go.n=3;G.vs_go.pcb=0;G.vs_go.race=77;L.connected=1;L.n=3;L.me=0;L.host=0;for(int i=0;i<3;i++){G.vs_go.player[i].id=L.player[i].id=11+i;packet(&G.vs_go.player[i],100+i,0,10,0);L.player[i]=G.vs_go.player[i];}VR.nonce=100;serial=0;ms=1000;silence=0;host=1;closed=off=abandoned=menu_abort=menu_close=disarmed=0;vs_recovery_begin(&G.vs_go);assert(VR.all_new);G.vs_race=1;}
static void fake_physics_frame(void){physics_ticks++;
@@GUARD@@
 commits++; /* surrogate for code after the actual early-return guard */
}
int main(void){
 unsigned char table[384]={0}; junction_barrier_point a={{-3,0,0}}, b={{3,0,0}}, m={{0,0,0}};
 for(int phase=0;phase<4;phase++){
  setup();commits=physics_ticks=menu_frames=0;
  memset(&race_junction_ui,0,sizeof race_junction_ui);assert(junction_ui_init(&race_junction_ui,table,sizeof table));junction_barrier_reset(&race_junction_barrier);
  junction_ui_tick(&race_junction_ui,1,0,0,2,0,0);assert(junction_barrier_tick(&race_junction_barrier,1,0,0,&a,&b,&m,2));
  if(phase==1)for(int i=0;i<20;i++)junction_ui_tick(&race_junction_ui,1,0,0,2,0,0);
  if(phase==2){junction_ui_tick(&race_junction_ui,2,0,0,2,0,0);assert(junction_barrier_tick(&race_junction_barrier,2,0,0,0,0,0,2));}
  if(phase==3){junction_ui_tick(&race_junction_ui,3,0,0,2,0,0);assert(junction_barrier_tick(&race_junction_barrier,3,0,0,0,0,0,2));}
  G.car.race.jct_select_valid=1;G.car.race.jct_state=1;G.car.race.jct_line_valid=1;G.car.race.jct_line[0][0]=3;
  L.player[1]=L.player[2];L.n=2;serial=1;ms=2000;assert(!vs_recovery_observe_now());ms=5000;assert(!vs_recovery_observe_now());serial=2;
  fake_physics_frame();assert(physics_ticks==1&&!commits&&menu_frames==1);assert(G.in_menu&&!G.vs_race&&abandoned==1&&menu_abort==1&&!off&&disarmed==1);assert(!G.car.race.jct_select_valid&&!G.car.race.jct_state&&!G.car.race.jct_line_valid&&!G.car.race.jct_line[0][0]);assert(!race_junction_ui.active&&!race_junction_ui.visible&&race_junction_ui.initialized);assert(!race_junction_barrier.ready&&!race_junction_barrier.manager_state);
  memset(&race_junction_ui,0,sizeof race_junction_ui);assert(junction_ui_init(&race_junction_ui,table,sizeof table));junction_barrier_reset(&race_junction_barrier);junction_ui_tick(&race_junction_ui,1,0,0,2,0,0);assert(race_junction_ui.active&&junction_barrier_tick(&race_junction_barrier,1,0,0,&a,&b,&m,2));
 }
 puts("host slices: missing-player timeout/keep and junction teardown/reinit passed; simulated phases are not network READY or actual selection protocol");return 0;
}
'''.replace('@@GUARD@@',guard)
# Discard unrelated extracted vote path; it relies on extra fake menu functions.
funcs=funcs[:funcs.index('\nstatic void vote_path(')]
source=pre+realcar+realui+realbarrier+funcs+post
with tempfile.TemporaryDirectory(prefix='jct-timeout-',dir=os.environ.get('TMPDIR')) as d:
 c=Path(d)/'fixture.c';exe=Path(d)/'fixture';c.write_text(source)
 subprocess.run(['cc','-std=c11','-fsanitize=undefined,float-cast-overflow','-fno-sanitize-recover=all','-Wall','-Wextra','-Wno-unused-function','-Werror','-D__ANDROID__','-I'+str(root/'src'),str(c),str(root/'src/vs_recovery.c'),str(root/'src/vs_recovery_wire.c'),str(root/'src/vs_abort_history.c'),'-lm','-o',str(exe)],check=True,timeout=30)
 subprocess.run([str(exe)],check=True,timeout=10)
