"""Real loopback host/net and sliced junction teardown; fake physics/UI/clock."""
from pathlib import Path
import os
ROOT=Path(__file__).resolve().parents[1]
f=ROOT/"tests/test_vs_four_three_slots_udp.py"
n={"__file__":str(f)}
t=f.read_text();exec(t[:t.index("with tempfile.TemporaryDirectory()")],n);s=n["s"]
def inject(c):
 def rep(a,b):
  nonlocal c
  assert c.count(a)==1,(a,c.count(a));c=c.replace(a,b)
 def part(name,a,b):
  x=(ROOT/"src"/name).read_text();return x[x.index(a):x.index(b,x.index(a))]
 car=part("car.c","void car_clear_junction(car_race *r) {","\n/* VA checks").replace("car_clear_junction","fixture_car_clear_junction")
 ui=part("junction_ui.c","static uint32_t le32(","\nstatic int pair(")
 bar=part("junction_barrier.c","void junction_barrier_reset(","\n/* Rectangle")
 rep('#include "vs_recovery.h"','#include "junction_ui.h"\n#include "junction_barrier.h"\n#include "vs_recovery.h"')
 rep('struct {int race;} car;','struct {car_race race;} car;')
 rep('static int race_junction_ui,race_junction_barrier;','static junction_ui race_junction_ui;static junction_barrier race_junction_barrier;')
 rep('static void fixture_car_clear_junction(void*p){(void)p;cleared++;}','static int real_clear_calls;\n'+car.replace('{','{real_clear_calls++;',1))
 rep('static void junction_ui_reset(void*p){(void)p;}',ui)
 rep('static void junction_barrier_reset(void*p){(void)p;}',bar)
 rep('static __typeof__(N) ns[4];','static junction_ui uis[4];static junction_barrier bars[4];static int commits[4],frames[4],menus[4];\nstatic __typeof__(N) ns[4];')
 rep('static void load(int i){active=i;','static void load(int i){race_junction_ui=uis[i];race_junction_barrier=bars[i];active=i;')
 rep('static void save(int i){ns[i]=N;','static void save(int i){uis[i]=race_junction_ui;bars[i]=race_junction_barrier;ns[i]=N;')
 c+=r"""
void setup_junction(int i){load(i);static unsigned char table[384];junction_barrier_point a={{-3,0,0}},b={{3,0,0}},m={{0,0,0}};memset(&race_junction_ui,0,sizeof race_junction_ui);assert(junction_ui_init(&race_junction_ui,table,sizeof table));junction_barrier_reset(&race_junction_barrier);junction_ui_tick(&race_junction_ui,1,0,0,2,0,0);assert(junction_barrier_tick(&race_junction_barrier,1,0,0,&a,&b,&m,2));G.car.race.jct_select_valid=1;G.car.race.jct_state=i+1;G.car.race.jct_line_valid=1;G.car.race.jct_line[0][0]=i+3;save(i);}
void check_live(int i){load(i);assert(G.car.race.jct_select_valid&&G.car.race.jct_state==i+1&&G.car.race.jct_line[0][0]==i+3);assert(race_junction_ui.active&&race_junction_barrier.ready);save(i);}
void frame_abort(int i){load(i);int before=real_clear_calls;frames[i]++;if(G.vs_race&&vs_recovery_observe_now()&&vs_abort_to_lobby())menus[i]++;else commits[i]++;assert(real_clear_calls==before+1);assert(frames[i]==1&&menus[i]==1&&!commits[i]);assert(G.in_menu&&!G.vs_race&&net_is_open());assert(!G.car.race.jct_select_valid&&!G.car.race.jct_state&&!G.car.race.jct_line_valid&&!G.car.race.jct_line[0][0]);assert(!race_junction_ui.active&&!race_junction_ui.visible&&race_junction_ui.initialized);assert(!race_junction_barrier.ready&&!race_junction_barrier.manager_state);save(i);printf("real teardown assertions client=%d\n",i);}
"""
 return c
assert s.count('HOST=f.HOST+') == 1
s=s.replace('HOST=f.HOST+','CLIENT=inject(CLIENT)\nHOST=f.HOST+',1)
assert 'if (G.vs_race && vs_recovery_observe_now() && vs_abort_to_lobby()) { menu_frame(0, frame_start); return; }' in (ROOT/'src/app.c').read_text()
hook='''\nfor anchor in ("int main(void){", "unsigned race=client_race(0);", "assert(client_observe(i));assert(client_abort(i));assert(client_valid(i,t));"):\n assert MAIN.count(anchor)==1, anchor\nMAIN=MAIN.replace("int main(void){", "void setup_junction(int),check_live(int),frame_abort(int); int main(void){")\nMAIN=MAIN.replace("unsigned race=client_race(0);", "for(int i=0;i<4;i++)setup_junction(i);for(int i=0;i<4;i++)check_live(i); unsigned race=client_race(0);")\nMAIN=MAIN.replace("assert(client_observe(i));assert(client_abort(i));assert(client_valid(i,t));", "check_live(i);frame_abort(i);for(int j=i+1;j<4;j++)if(j!=DEAD)check_live(j);check_live(DEAD);assert(client_valid(i,t));")\n'''
assert s.count('with tempfile.TemporaryDirectory(prefix=') == 1
s=s.replace('with tempfile.TemporaryDirectory(prefix=',hook+'\nwith tempfile.TemporaryDirectory(prefix=',1)
for slot in (1,2):
 print('DROP SLOT',slot,flush=True);os.environ['DROP_SLOT']=str(slot)
 exec(compile(s,str(ROOT/'tests/test_vs_four_to_three_udp.py'),'exec'),{'__file__':str(ROOT/'tests/test_vs_four_to_three_udp.py'),'inject':inject})
