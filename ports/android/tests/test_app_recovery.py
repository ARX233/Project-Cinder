#!/usr/bin/env python3
"""Compile actual app recovery functions with fake game/net boundaries."""
from pathlib import Path
import os, subprocess, tempfile
root=Path(__file__).resolve().parents[1]; s=(root/'src/app.c').read_text()
menu=s[s.index('static void vs_menu(void)'):]
go_guard='if (m->vs.state == MENU_VS_LOBBY && may_take_go && net_take_go(&go))'
assert menu.index(go_guard) < menu.index('if (vs_day_go_timeout(m, net_lobby_valid_now(), now, G.vs_day_at))')
assert 'RACE CANCELLED - WAIT %d S' in s and 'LEGACY PLAYER - AUTO RETURN NOT GUARANTEED' in s
def take(marker):
 p=s.index(marker); start=s.index('{',p); n=1;i=start+1
 while n:
  n+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[p:i]+'\n'
func=''.join(take(x) for x in ('static int vs_remote_timed_out(', 'static int vs_recovery_profile(', 'static int vs_recovery_roster_valid(', 'static int vs_recovery_accept_go(', 'static void vs_recovery_begin(', 'static int vs_recovery_finish_ready(', 'static int vs_recovery_observe_now(', 'static int vs_abort_to_lobby('))
vote_begin=s.index('#ifdef __ANDROID__\n    if (VR.flag == VS_RECOVERY_WIRE_ABORT',s.index('static void vs_menu(void)'))
vote_end=s.index('\n    }',s.index('      vs_day(m, l, now);',vote_begin))+len('\n    }')
vote=s[vote_begin:vote_end]
pre=r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "net.h"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
#define VS_PROFILE 21
#define VS_GONE 10.0
#define VS_FINISH_WAIT_SECONDS 180.0
#define MENU_VS_LOBBY 2
#define VS_GK_OFF 0
typedef struct { vs_recovery recovery; uint64_t nonce,peer_nonce[NET_PLAYERS],host_id; uint32_t seq,peer_seq[NET_PLAYERS],race,last_go; unsigned finished,capable,ready_capable; int all_new,local_finished,echo_confirmed,local_loaded,abort_after_result; double advertise_until,finish_wait_at; unsigned char flag; } vs_recovery_app;
static vs_recovery_app VR;
static vs_abort_history VH;
static double VH_last_time;
static int VH_has_time, VH_abort_unknown;
static struct {uint32_t vs_id; net_go vs_go; int vs_race,vs_closed,paused,vs_wait,vs_seen_loaded,in_menu; double vs_abort_note_until; struct { int finish,finish_story; struct { int state; } vs; } menu; struct { int screen_w,screen_h; } hud; struct { int race; } car;} G;
static int race_junction_ui,race_junction_barrier;
static net_lobby L;static uint64_t serial;static double ms,silence;static int closed,host,off,abandoned,menu_abort,menu_close,disarmed;
static double now_ms(void){return ms;}
static void vs_profile(unsigned char *p){memset(p,7,21);}
const net_lobby *net_lobby_valid_now(void){return &L;}
uint64_t net_lobby_observations(void){return serial;}
int net_is_open(void){return 1;}
int net_host_closed(void){return closed;}
static int vs_host_is_open(void){return host;}
static void vs_host_disarm_round(void){++disarmed;}
double net_silence(double x){(void)x;return silence;}
double net_lobby_valid_silence(double x){(void)x;return silence < 0 ? 1e9 : silence;}
void net_abandon_race(void){++abandoned;}
static void car_clear_junction(int*x){(void)x;}
static void junction_ui_reset(int*x){(void)x;}
static void junction_barrier_reset(int*x){(void)x;}
static void snd_quiet(void){}
static void hud_init(void*x,int w,int h){(void)x;(void)w;(void)h;}
static void menu_vs_aborted(void*x,const char*y){(void)x;(void)y;++menu_abort;}
static void menu_vs_closed(void*x,const char*y){(void)x;(void)y;++menu_close;}
static void vs_off(void){++off;memset(&VR,0,sizeof VR);}
typedef struct { struct { int area_go,day,start; } vs; } vote_menu;
static int area_calls,day_calls;
static void vs_area(vote_menu*m,const net_lobby*l,double n){(void)m;(void)l;(void)n;++area_calls;}
static void vs_day(vote_menu*m,const net_lobby*l,double n){(void)m;(void)l;(void)n;++day_calls;}
'''
pre += s[s.index('typedef struct { int waiting; double since, last; } vs_receive_gate;'):s.index('/* -1 invalid/regressing clock or timeout;')]
func = take('static void vs_history_lobby(') + func
func += '\nstatic void vote_path(vote_menu *m,const net_lobby *l,double now) {\n'+vote+'\n}\n'
post=r'''
static void packet(net_player *p, uint64_t nonce,uint32_t race,uint32_t seq,int flag){unsigned char base[21]={0};vs_recovery_wire_extension e={flag,race,nonce,seq};assert(vs_recovery_wire_encode(p->profile,sizeof p->profile,base,sizeof base,&e));p->profile_len=42;}
static void setup(void){vs_abort_history_reset(&VH);VH_has_time=VH_abort_unknown=0;VH_last_time=0;memset(&G,0,sizeof G);memset(&VR,0,sizeof VR);memset(&L,0,sizeof L);G.vs_id=11;G.vs_go.n=3;G.vs_go.pcb=0;G.vs_go.race=77;L.connected=1;L.n=3;L.me=0;L.host=0;for(int i=0;i<3;i++){G.vs_go.player[i].id=L.player[i].id=11+i;packet(&G.vs_go.player[i],100+i,0,10,0);L.player[i]=G.vs_go.player[i];}VR.nonce=100;serial=0;ms=1000;host=1;closed=off=abandoned=menu_abort=menu_close=disarmed=0;vs_recovery_begin(&G.vs_go);assert(VR.all_new);}
int main(void){unsigned char b[VS_RECOVERY_READY_SIZE];setup();assert(vs_recovery_roster_valid(&G.vs_go));assert(vs_recovery_accept_go(77));assert(!vs_recovery_accept_go(77));assert(!vs_recovery_accept_go(76));assert(vs_recovery_accept_go(78));G.vs_go.player[1].id=11;assert(!vs_recovery_roster_valid(&G.vs_go));G.vs_go.player[1].id=12;packet(&G.vs_go.player[0],999,0,10,0);assert(!vs_recovery_roster_valid(&G.vs_go));G.vs_go.player[0].profile_len=21;assert(vs_recovery_roster_valid(&G.vs_go));VR.echo_confirmed=1;assert(!vs_recovery_roster_valid(&G.vs_go));setup();host=0;silence=11;assert(vs_remote_timed_out(2));L.connected=0;assert(!vs_remote_timed_out(2));L.connected=1;host=1;assert(!vs_remote_timed_out(2));silence=0;setup();assert(vs_recovery_profile(b)==47);vs_recovery_wire_extension e;assert(vs_recovery_wire_decode(&e,b,47)&&e.race_id==77&&e.nonce==100);
serial=1;packet(&L.player[1],101,77,11,VS_RECOVERY_WIRE_ABORT);assert(vs_recovery_observe_now());assert(vs_abort_to_lobby());assert(abandoned==1&&menu_abort==1&&!off&&VR.flag==1&&VR.race==77&&G.in_menu&&disarmed==1);
setup();serial=1;packet(&L.player[1],999,77,11,1);assert(!vs_recovery_observe_now());serial=2;packet(&L.player[1],101,76,12,1);assert(!vs_recovery_observe_now());serial=3;packet(&L.player[1],101,77,10,1);assert(!vs_recovery_observe_now());
setup();L.player[1]=L.player[2];L.n=2;serial=1;ms=2000;assert(!vs_recovery_observe_now());ms=5000;assert(!vs_recovery_observe_now());serial=2;assert(vs_recovery_observe_now());assert(vs_abort_to_lobby()&&menu_abort==1&&!off);
setup();VR.host_id=12;L.player[1]=L.player[2];L.me=0;L.host=0;L.n=2;serial=1;ms=2000;assert(!vs_recovery_observe_now());serial=2;ms=5000;assert(vs_recovery_observe_now());assert(vs_abort_to_lobby()&&off==1&&menu_close==1);
setup();host=0;silence=11;serial=1;packet(&L.player[1],101,77,11,VS_RECOVERY_WIRE_ABORT);assert(vs_recovery_observe_now());assert(vs_abort_to_lobby()&&off==1&&menu_close==1&&!menu_abort&&!disarmed);silence=0;
setup();assert(vs_recovery_finish_ready()==0 && VR.flag==VS_RECOVERY_WIRE_FINISHED);serial=1;packet(&L.player[1],101,77,11,2);packet(&L.player[2],102,77,11,2);assert(!vs_recovery_observe_now());assert(vs_recovery_finish_ready()==1);
setup();assert(vs_recovery_finish_ready()==0);ms=181000;assert(vs_recovery_finish_ready()==-1&&vs_abort_to_lobby());
setup();VR.all_new=0;assert(vs_recovery_finish_ready()==1);
/* Begin and abort must clear both independent receive gates. */
setup();VG_go.waiting=VG_finish.waiting=1;vs_recovery_begin(&G.vs_go);assert(!VG_go.waiting&&!VG_finish.waiting);VG_go.waiting=VG_finish.waiting=1;vs_recovery_request_abort(&VR.recovery);assert(vs_abort_to_lobby());assert(!VG_go.waiting&&!VG_finish.waiting);
/* A validated callback records a transient ABORT even if the latest snapshot changes. */
setup();packet(&L.player[1],101,77,11,VS_RECOVERY_WIRE_ABORT);vs_history_lobby(&L,1.0,0);packet(&L.player[1],101,77,12,0);serial=1;assert(vs_recovery_observe_now());assert(vs_abort_to_lobby()&&menu_abort==1&&!off);
/* Last valid lobby predates GO in wall order but has a later clock sample.
 * No new lobby callback, no peer abort, and the fake valid-silence is fresh:
 * the regression must be detected independently of recovery.last_time_ms. */
setup();silence=0;serial=1;vs_history_lobby(&L,2.0,0);ms=1500;
vs_recovery_begin(&G.vs_go);assert(!VR.recovery.initialized&&VH.unknown);
/* Independently, a clock regression after successful begin is caught by
 * the actual observer and forces the abort helper to close, not keep. */
setup();silence=0;serial=1;vs_history_lobby(&L,2.0,0);ms=2000;
vs_recovery_begin(&G.vs_go);assert(VR.recovery.initialized&&VR.recovery.last_time_ms==2000&&!VH.unknown);
ms=1500;assert(vs_recovery_observe_now()&&VH.unknown&&VH_abort_unknown);
assert(vs_abort_to_lobby()&&off==1&&menu_close==1&&!menu_abort);
/* Equal and advancing samples must not be treated as regression. */
for(int i=0;i<2;i++){setup();silence=0;serial=1;vs_history_lobby(&L,2.0,0);ms=i?2001:2000;
vs_recovery_begin(&G.vs_go);assert(VR.recovery.initialized&&VR.recovery.last_time_ms==(int64_t)ms);
assert(!vs_recovery_observe_now()&&!VH.unknown&&!VH_abort_unknown&&!off&&!menu_close);}
/* Invalid history/clock requires reconnect, rather than retaining the room. */
setup();vs_history_lobby(&L,2.0,0);vs_history_lobby(&L,1.0,0);assert(VH.unknown&&vs_recovery_observe_now()&&VH_abort_unknown);assert(vs_abort_to_lobby()&&off&&menu_close);
setup();ms=-1;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);assert(vs_abort_to_lobby()&&off&&menu_close);
setup();ms=999;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);
setup();ms=NAN;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);
setup();ms=INFINITY;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);assert(vs_abort_to_lobby()&&off&&menu_close);
setup();ms=0x1p63;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);
setup();host=0;silence=11;serial=0;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);assert(vs_abort_to_lobby()&&off&&menu_close);silence=0;
setup();L.connected=0;serial=0;ms=10999;assert(!vs_recovery_observe_now());ms=11000;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);assert(vs_abort_to_lobby()&&off&&menu_close);
setup();for(int i=0;i<3;i++){assert(vs_recovery_wire_put_ready(G.vs_go.player[i].profile,64,0));G.vs_go.player[i].profile_len=47;}vs_recovery_begin(&G.vs_go);assert(VR.ready_capable==7);packet(&L.player[1],101,77,10,0);assert(vs_recovery_wire_put_ready(L.player[1].profile,64,1));L.player[1].profile_len=47;serial=1;assert(!vs_recovery_observe_now() && !(G.vs_seen_loaded&2));packet(&L.player[1],101,77,11,0);assert(vs_recovery_wire_put_ready(L.player[1].profile,64,1));L.player[1].profile_len=47;serial=2;assert(!vs_recovery_observe_now() && (G.vs_seen_loaded&2));
setup();vote_menu vm={0};vm.vs.area_go=vm.vs.day=vm.vs.start=1;VR.flag=1;VR.advertise_until=30;vote_path(&vm,&L,10);assert(!vm.vs.area_go&&!vm.vs.day&&!vm.vs.start&&!area_calls&&!day_calls);vote_path(&vm,&L,30);assert(area_calls==1&&day_calls==1);
puts("app recovery extracted runtime passed");return 0;}
'''
# A separate fixture exercises the actual vs_day; vote_path above intentionally
# retains its fake vs_day so the cooldown test remains focused on dispatch.
day_pre=r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include "net.h"
#define MENU_BGM 1
#define MENU_VS_DAY_FINAL 10
#define MENU_VS_LOADED 20
#define VS_AREA_LATE 0
#define VS_REVEAL 1
struct vote {int day,n,day_final,day_timer,me,day_voted,other_day[NET_PLAYERS],other_zone[NET_PLAYERS],ramp,km;};
typedef struct {int screen,zone,zones,song;struct vote vs;} menu_state;
static struct {double vs_day_at,vs_day_final_at,vs_day_started,vs_wait_note_until;int vs_song;} G;
static net_lobby strict_lobby;
static int is_host=1,control=1,match_visible=1,match_strict=1,seal_ok=1,pending,seal_calls,start_calls,net_start_calls,off_calls,closed_calls;
static int vs_host_is_open(void){return is_host;}
static int vs_host_control_ready(void){return control;}
static int vs_host_lobby_matches(const net_lobby*l){return l==&strict_lobby?match_strict:match_visible;}
const net_lobby *net_lobby_valid_now(void){return &strict_lobby;}
static int vs_host_seal_vote(void){++seal_calls;return seal_ok;}
static int vs_host_round_pending(void){return pending;}
static int vs_host_local_start(int a,int b,int c,double d){(void)a;(void)b;(void)c;(void)d;++start_calls;return 1;}
static void vs_off(void){++off_calls;}
static void menu_vs_closed(menu_state*m,const char*s){(void)m;(void)s;++closed_calls;}
static int vs_same_build(const net_player*p){(void)p;return 1;}
static int vs_own_lobby_ready(const net_lobby*l,menu_state*m){(void)l;(void)m;return 1;}
/* This fixture does not model peer profiles; dedicated cooldown tests do. */
static int vs_peer_cooldown(const net_lobby*l,const net_lobby*v,double now){(void)l;(void)v;(void)now;return 0;}
void net_start(int a,int b,int c){(void)a;(void)b;(void)c;++net_start_calls;}
'''
day_post=r'''
int main(void){
 menu_state m={0};net_lobby l={0};m.screen=MENU_BGM;m.zones=1;m.vs.day=1;m.vs.n=1;m.vs.day_final=-1;m.vs.day_voted=1;l.n=1;
 match_visible=0;vs_day(&m,&l,10);assert(m.vs.day_final==-1&&!seal_calls);
 match_visible=1;match_strict=0;vs_day(&m,&l,11);assert(m.vs.day_final==-1&&!seal_calls);
 match_strict=1;control=0;vs_day(&m,&l,12);assert(m.vs.day_final==-1&&!seal_calls);
 control=1;vs_day(&m,&l,13);assert(m.vs.day_final==0&&seal_calls==1&&!off_calls);
 match_strict=0;vs_day(&m,&l,15);assert(!start_calls);
 match_strict=1;vs_day(&m,&l,16);assert(start_calls==1);
 m.vs.day_final=-1;seal_ok=0;vs_day(&m,&l,17);assert(seal_calls==2&&off_calls==1&&closed_calls==1&&m.vs.day_final==-1);
 /* Independent eligible START attempts: the resend timer must not mask the deadline. */
 m.vs.day_final=0;G.vs_day_at=10;G.vs_day_final_at=10;G.vs_day_started=0;start_calls=0;
 vs_day(&m,&l,99.999);assert(start_calls==1);
 G.vs_day_started=0;vs_day(&m,&l,100.0);assert(start_calls==1&&G.vs_day_started==0);
 is_host=0;G.vs_day_started=0;vs_day(&m,&l,99.999);assert(net_start_calls==1);
 G.vs_day_started=0;vs_day(&m,&l,100.0);assert(net_start_calls==1&&G.vs_day_started==0);
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='app-recovery-',dir='/Volumes/CodexWork') as td:
 os.environ['TMPDIR']=td;c=Path(td)/'test.c';c.write_text(pre+func+post);exe=Path(td)/'test'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-D__ANDROID__','-I'+str(root/'src'),str(c),str(root/'src/vs_recovery.c'),str(root/'src/vs_recovery_wire.c'),str(root/'src/vs_abort_history.c'),'-o',str(exe)],check=True,env=os.environ)
 subprocess.run([str(exe)],check=True,env=os.environ)
 c.write_text(day_pre+take('static void vs_day(')+day_post)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-D__ANDROID__','-I'+str(root/'src'),str(c),'-o',str(exe)],check=True,env=os.environ)
 subprocess.run([str(exe)],check=True,env=os.environ)
