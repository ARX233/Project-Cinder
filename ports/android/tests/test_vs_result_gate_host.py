#!/usr/bin/env python3
"""Compile actual result gate and VS branch; UI/storage are finite fakes."""
from pathlib import Path
import os, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
app=(root/'src/app.c').read_text(); menu=(root/'src/menu.c').read_text()
def function(s,marker):
 p=s.index(marker); j=s.index('{',p)+1; depth=1
 while depth:
  depth+=(s[j]=='{')-(s[j]=='}'); j+=1
 return s[p:j]+'\n'
helper=''.join(function(app,x) for x in ('static int vs_receive_gate_check(', 'static void vs_recovery_begin(', 'static int vs_recovery_finish_ready(', 'static int vs_recovery_observe_now('))
stars=function(menu,'int menu_vs_stars(')
a=app.index('#ifdef __ANDROID__\n  int vs_finish_ready = 1;',app.index("/* the card's mileage */"))
b=app.index('    } else if (G.rival >= 0 && G.menu.game == MENU_GAME_STORY)',a)
gate=app[a:b]+'\n    }\n  }\n'
pre=r"""
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "vs_abort_history.h"
#include "net.h"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#define VS_FINISH_WAIT_SECONDS 180.0
#define VS_GONE 10.0
#define CAR_RACE_GOAL 1
#define TITLE_VS 1
typedef struct {int finish,maker,car,star_from,star_delta,garage_changed; int vs_wins_car[1][1],vs_stars_car[1][1],vs_count_car[1][1];} menu_state;
typedef int menu_result;
typedef struct {int over,state,vs_place;float total;} car_race;
static struct {vs_recovery recovery;uint64_t peer_nonce[NET_PLAYERS],host_id;uint32_t peer_seq[NET_PLAYERS],race;int local_finished,local_loaded,all_new,abort_after_result;unsigned finished,capable,ready_capable;unsigned char flag;double finish_wait_at,advertise_until;} VR;
static struct {int vs_race,vs_closed,story_end_freeze,race_course,vs_seen_loaded;uint32_t vs_id;net_go vs_go;menu_state menu;} G;
typedef struct {int waiting;double since,last;} vs_receive_gate;
static vs_receive_gate VG_go,VG_finish;
static vs_abort_history VH; static int VH_abort_unknown, VH_has_time; static double VH_last_time;
static double ms;static int saves,mileage_saves,result_saves,titles,aborts;
/* This is the unchanged legacy VS result contract, not a Ghost race. */
static int app_ghost_mode(void){return 0;}
static int drained=1,current_valid=1;
static net_lobby L;static uint64_t serial;
static double samples[2];static int sample_count,sample_index;
static double now_ms(void){return sample_index<sample_count ? samples[sample_index++] : ms;}
static void frame_samples(double gate,double finish){samples[0]=gate;samples[1]=finish;sample_count=2;sample_index=0;}
const net_lobby *net_lobby_valid_now(void){return &L;}
uint64_t net_lobby_observations(void){return serial;}
int net_is_open(void){return 1;}
int net_receive_drained(void){return drained;}
int net_lobby_current_valid(void){return current_valid;}
double net_lobby_valid_silence(double t){(void)t;return 0;}
static int vs_abort_to_lobby(void){aborts++;G.vs_race=0;G.menu.finish=1;return 1;}
static void menu_frame(int x,double y){(void)x;(void)y;}
static void garage_save(void){saves++;if(G.menu.finish)result_saves++;else mileage_saves++;}
static void menu_finish_open(menu_state*m,int g,void*p){(void)g;(void)p;m->finish=1;}
static void menu_finish_vs(menu_state*m,int p,int n){(void)m;(void)p;(void)n;}
static void title_race_over(int k,int w,car_race*r,int c,int x){(void)k;(void)w;(void)r;(void)c;(void)x;titles++;}
"""
post=r"""
static void setup(int legacy){uint64_t ids[3]={1,2,3};G=(typeof(G)){0};VR=(typeof(VR)){0};VH=(vs_abort_history){0};VH_abort_unknown=0;VH_has_time=0;VH_last_time=0;VG_go=(vs_receive_gate){0};VG_finish=(vs_receive_gate){0};saves=mileage_saves=result_saves=titles=aborts=0;sample_count=sample_index=0;drained=current_valid=1;ms=1000;G.vs_race=2;G.vs_go.n=3;G.vs_go.pcb=0;assert(vs_recovery_init(&VR.recovery,ids,3,1,77,1000,2000));VR.all_new=!legacy;}
static void empty(void){assert(!G.menu.vs_wins_car[0][0]&&!G.menu.vs_stars_car[0][0]&&!G.menu.vs_count_car[0][0]&&!saves&&!titles);}
static void committed(void){assert(G.menu.vs_wins_car[0][0]==1&&G.menu.vs_stars_car[0][0]==2&&G.menu.vs_count_car[0][0]==1&&saves==2&&mileage_saves==1&&result_saves==1&&titles==1);}
static void packet(net_player *p,uint64_t nonce,uint32_t seq,int flag){
 unsigned char base[21]={0};vs_recovery_wire_extension e={flag,77,nonce,seq};
 assert(vs_recovery_wire_encode(p->profile,sizeof p->profile,base,sizeof base,&e));p->profile_len=42;
}
/* Characterization only: asynchronous late ABORT cannot roll back an already
 * completed local commit. This is not an atomicity or safety guarantee. */
static void late_abort(car_race *r){
 setup(0);L=(net_lobby){0};serial=0;G.vs_id=1;G.vs_go.race=77;
 L.connected=1;L.n=3;L.me=0;L.host=0;
 for(int i=0;i<3;i++){G.vs_go.player[i].id=(uint64_t)i+1;packet(&G.vs_go.player[i],100+i,10,VS_RECOVERY_WIRE_NORMAL);L.player[i]=G.vs_go.player[i];}
 vs_recovery_begin(&G.vs_go);assert(VR.all_new&&VR.recovery.initialized);
 result_frame(r);empty();
 packet(&L.player[1],101,11,VS_RECOVERY_WIRE_FINISHED);
 packet(&L.player[2],102,11,VS_RECOVERY_WIRE_FINISHED);serial++;
 assert(!vs_recovery_observe_now());assert((VR.finished&6)==6);
 result_frame(r);committed();
 packet(&L.player[1],101,12,VS_RECOVERY_WIRE_ABORT);serial++;
 assert(vs_recovery_observe_now());assert(VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);
 committed();result_frame(r);committed();
}
int main(void){car_race r={1,CAR_RACE_GOAL,1,12};
late_abort(&r);
/* Latest lobby validity and queue drain share one bounded finish gate. */
for(int legacy=0;legacy<=1;legacy++) {
 setup(legacy);VR.finished=6;current_valid=0;result_frame(&r);empty();
 ms=2900;current_valid=1;result_frame(&r);committed();result_frame(&r);committed();
 setup(legacy);VR.finished=6;current_valid=0;result_frame(&r);empty();
 ms=3000;result_frame(&r);assert(aborts==1);empty();
 /* Alternation must not restart the 2-second deadline. */
 setup(legacy);VR.finished=6;current_valid=0;result_frame(&r);empty();
 ms=2000;current_valid=1;drained=0;result_frame(&r);empty();
 ms=2900;drained=1;result_frame(&r);committed();result_frame(&r);committed();
 setup(legacy);VR.finished=6;current_valid=0;result_frame(&r);empty();
 ms=2000;current_valid=1;drained=0;result_frame(&r);empty();
 ms=3000;drained=1;current_valid=0;result_frame(&r);assert(aborts==1);empty();
}
/* Most recent observation at 2000ms, gate at 2100ms, result sample
 * 2050ms: a locally ready result must abort before any commit. */
setup(0);VR.recovery.last_time_ms=2000;VH_has_time=1;VH_last_time=2.0;VR.finished=6;
frame_samples(2100,2050);result_frame(&r);assert(sample_index==2&&aborts==1&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);empty();
for(int i=0;i<2;i++) {
 setup(0);VR.recovery.last_time_ms=2000;VH_has_time=1;VH_last_time=2.0;VR.finished=6;
 frame_samples(2100,i?2150:2100);result_frame(&r);assert(sample_index==2&&!aborts);committed();
}
/* A drained gate must retain last time even on consecutive pending frames. */
setup(0);VR.recovery.last_time_ms=2000;VH_has_time=1;VH_last_time=2.0;
frame_samples(2100,2100);result_frame(&r);empty();assert(VG_finish.last>2.09);
frame_samples(2150,2150);result_frame(&r);empty();assert(VG_finish.last>2.14);
VR.finished=6;frame_samples(2140,2140);result_frame(&r);
assert(sample_index==1&&aborts==1&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);empty();
setup(0);result_frame(&r);empty();VR.finished|=2;result_frame(&r);empty();VR.finished|=4;result_frame(&r);committed();result_frame(&r);committed();
setup(0);result_frame(&r);empty();ms=181000;result_frame(&r);assert(aborts==1);empty();
/* Invalid clock is fatal both before and during a wait, including when
 * all remote FINISHED bits have since arrived; legacy must also fail closed. */
for(int legacy=0;legacy<=1;legacy++) for(int i=0;i<3;i++) {
 setup(legacy);ms=i==0?NAN:i==1?INFINITY:-1;result_frame(&r);
 assert(aborts==1&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);empty();
}
for(int i=0;i<4;i++) {
 setup(0);result_frame(&r);empty();VR.finished|=6;
 ms=i==0?NAN:i==1?INFINITY:i==2?-1:999;
 result_frame(&r);assert(aborts==1&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);empty();
}
setup(1);result_frame(&r);committed();result_frame(&r);committed();
setup(0);G.menu.vs_stars_car[0][0]=2001;r.vs_place=3;VR.finished=6;result_frame(&r);assert(!G.menu.vs_wins_car[0][0]&&G.menu.vs_stars_car[0][0]==2000&&G.menu.star_delta==-1&&saves==2);result_frame(&r);assert(saves==2&&G.menu.vs_count_car[0][0]==1);
puts("extracted VS result gate passed");}
"""
with tempfile.TemporaryDirectory(prefix='vs-result-host-') as td:
 c=Path(td)/'test.c'; exe=Path(td)/'test'
 c.write_text(pre+stars+helper+'\nstatic void result_frame(car_race *race){int movie=0;double frame_start=0;\n'+gate+'\n}\n'+post)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Wextra','-Wno-unused-variable','-Werror','-fsanitize=undefined,float-cast-overflow','-fno-sanitize-recover=all','-D__ANDROID__','-I'+str(root/'src'),str(c),str(root/'src/vs_recovery.c'),str(root/'src/vs_recovery_wire.c'),str(root/'src/vs_abort_history.c'),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
