#!/usr/bin/env python3
"""Extract real app GO branch and recovery helpers; all UI/net/clock are fakes.

Not an Android process, real UDP, actual menu implementation, or persistence test.
Run: python3 tests/test_vs_init_failure_host.py
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
s = (root / 'src/app.c').read_text()
def take(marker):
    start=s.index(marker); brace=s.index('{',start); depth=1; i=brace+1
    while depth:
        depth+=(s[i]=='{')-(s[i]=='}'); i+=1
    return s[start:i]+'\n'
helpers=take('static int vs_receive_gate_check(')+''.join(take(m) for m in (
    'static int vs_recovery_profile(', 'static int vs_recovery_roster_valid(',
    'static int vs_recovery_accept_go(', 'static void vs_recovery_begin(',
    'static int vs_own_profile_matches(', 'static int vs_same_build('))
# Preserve actual statements, ordering and returns up to the first loading call.
a=s.index('  net_go go;\n  int may_take_go = 1;',s.index('static void vs_menu(void)'))
b=s.index('    menu_vs_loading(m);',a)+len('    menu_vs_loading(m);')
branch=s[a:b]+'\n  }\n'
v=s.index('#ifdef __ANDROID__\n    if (VR.flag == VS_RECOVERY_WIRE_ABORT',s.index('static void vs_menu(void)'))
w=s.index('\n  }\n  double silent =',v)
vote=s[v:w]
pre=r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "net.h"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
#define VS_PROFILE 21
#define VS_PROFILE_BUILD 19
#define VS_BUILD_NAMESPACE 'W'
#define VS_BUILD_REVISION 168
#define VS_GONE 10.0
#define MENU_VS_LOBBY 2
#define MENU_VS_OFF 0
/* Model of the fields touched by extracted code, NOT the real menu structure. */
typedef struct {int zone,zones; struct {int state,n,area_go,day,start;char note[128];} vs;} menu_state;
typedef struct {vs_recovery recovery; uint64_t nonce,peer_nonce[NET_PLAYERS],host_id;uint32_t seq,peer_seq[NET_PLAYERS],race,last_go;unsigned finished,capable,ready_capable;int all_new,local_finished,echo_confirmed,local_loaded,abort_after_result;double advertise_until,finish_wait_at;unsigned char flag;} vs_recovery_app;
static vs_recovery_app VR;
static vs_abort_history VH;
static double VH_last_time;
static int VH_has_time;
/* Inject only non-clock init failure, otherwise call the real implementation. */
static int fake_init_failure;
static int fixture_recovery_init(vs_recovery *s,const uint64_t *ids,size_t n,uint64_t local,uint64_t race,int64_t now,int64_t grace){
 if(fake_init_failure){vs_recovery_reset(s);return 0;}
 return vs_recovery_init(s,ids,n,local,race,now,grace);
}
#define vs_recovery_init fixture_recovery_init
static struct {uint32_t vs_id;net_go vs_go;int vs_wait,vs_seen_loaded;double vs_day_at,vs_abort_note_until;} G;
static net_lobby L;static net_go incoming;static int new_go,open_room,host_closed,local_host,off_count,abort_count,close_count,abandon_count,loading_count,song_count,save_count,area_count,day_count;
typedef struct { int waiting; double since, last; } vs_receive_gate;
static vs_receive_gate VG_go, VG_finish;
static double sample_ms,gate_ms,silence,valid_silence;
static int first_gate_sample;
static int pending, control_ready, accepted_count, retain_pending;
static int go_matches, match_calls;
/* Deliberate observer/UI stubs: exercise GO ordering, not real peer detection. */
static int fake_observe_abort, observe_calls, fake_abort_calls;
static int vs_recovery_observe_now(void){observe_calls++;assert(VR.recovery.initialized&&G.vs_go.race==incoming.race&&!G.vs_wait&&!G.vs_seen_loaded);G.vs_seen_loaded=5;return fake_observe_abort;}
static int vs_abort_to_lobby(void){fake_abort_calls++;return 1;}
static int vs_host_control_ready(void){return control_ready;}
static int vs_host_round_pending(void){return pending;}
static int vs_host_go_matches(const net_go *go){assert(go->race==incoming.race);match_calls++;return go_matches;}
static void vs_host_round_accepted(void){accepted_count++;if(!retain_pending)pending=0;}
/* Gate and initialization are separate samples; permit a later failure. */
static double now_ms(void){if(first_gate_sample){first_gate_sample=0;return gate_ms;}return sample_ms;}
static int lobby_current_valid=1;
int net_lobby_current_valid(void){return lobby_current_valid;}
int net_go_pending(void){return new_go;}
int net_receive_drained(void){return 1;}
static void vs_profile(unsigned char*p){memset(p,7,21);p[19]='W';p[20]=168;}
static int fake_open(const char*p,int f){(void)p;(void)f;return -1;}
#define open fake_open
const net_lobby *net_lobby_valid_now(void){return &L;}
int net_is_open(void){return open_room;}
int net_host_closed(void){return host_closed;}
static int vs_host_is_open(void){return local_host;}
double net_silence(double now){(void)now;return silence;}
double net_lobby_valid_silence(double now){(void)now;return valid_silence < 0 ? HUGE_VAL : valid_silence;}
int net_take_go(net_go*g){if(!new_go)return 0;new_go=0;*g=incoming;return 1;}
void net_abandon_race(void){abandon_count++;}
static void vs_off(void){off_count++;open_room=0;memset(&VR,0,sizeof VR);}
static void menu_vs_aborted(menu_state*m,const char*note){assert(!strcmp(note,"RECOVERY UNAVAILABLE - BACK IN ROOM"));abort_count++;m->vs.state=MENU_VS_LOBBY;m->vs.area_go=m->vs.day=m->vs.start=0;}
static const char *closed_note;
static void menu_vs_closed(menu_state*m,const char*note){closed_note=note;close_count++;m->vs.state=MENU_VS_OFF;}
static void menu_vs_song(menu_state*m,int s){(void)m;(void)s;song_count++;}
static void menu_vs_loading(menu_state*m){(void)m;loading_count++;}
static void vs_area(menu_state*m,const net_lobby*l,double n){(void)m;(void)l;(void)n;area_count++;}
static void vs_day(menu_state*m,const net_lobby*l,double n){(void)m;(void)l;(void)n;day_count++;}
'''
post=r'''
static void make_profile(net_player*p,uint64_t nonce,int legacy){unsigned char base[21];vs_profile(base);if(legacy){memcpy(p->profile,base,21);p->profile_len=21;return;}vs_recovery_wire_extension e={0,0,nonce,10};assert(vs_recovery_wire_encode(p->profile,sizeof p->profile,base,21,&e));assert(vs_recovery_wire_put_ready(p->profile,sizeof p->profile,0));p->profile_len=47;}
static void setup(int legacy, int zero_nonce){
 memset(&VR,0,sizeof VR);memset(&G,0,sizeof G);memset(&L,0,sizeof L);memset(&incoming,0,sizeof incoming);memset(&VG_go,0,sizeof VG_go);memset(&VG_finish,0,sizeof VG_finish);
 open_room=1;host_closed=local_host=off_count=abort_count=close_count=abandon_count=loading_count=song_count=save_count=area_count=day_count=0;silence=valid_silence=1;sample_ms=1000;
 memset(&VH,0,sizeof VH);VH_last_time=0;VH_has_time=0;fake_init_failure=0;gate_ms=1000;lobby_current_valid=1;
 pending=accepted_count=retain_pending=match_calls=0;fake_observe_abort=observe_calls=fake_abort_calls=0;control_ready=go_matches=1;closed_note=NULL;
 G.vs_id=11;G.vs_wait=50;G.vs_seen_loaded=3;G.vs_day_at=5;VR.nonce=zero_nonce?0:100;
 incoming.race=77;incoming.n=2;incoming.pcb=0;incoming.ramp=128;incoming.song=3;
 for(int i=0;i<2;i++){incoming.player[i].id=11+i;make_profile(&incoming.player[i],100+i, (i==0&&zero_nonce)||(i==1&&legacy));}
 L.connected=1;L.n=2;L.host=1;L.me=0;for(int i=0;i<2;i++)L.player[i]=incoming.player[i];new_go=1;
}
static menu_state menu(void){menu_state m={0};m.zone=9;m.zones=2;m.vs.state=MENU_VS_LOBBY;m.vs.area_go=m.vs.day=m.vs.start=1;return m;}
int main(void){unsigned char b[47];vs_recovery_wire_extension e;
 for(int legacy=0;legacy<2;legacy++){setup(legacy,0);menu_state m=menu();run_go(&m,1);assert(loading_count==1&&!abandon_count&&!abort_count&&VR.recovery.initialized);assert(VR.all_new==!legacy);assert(m.zone==1&&song_count==1);}
 /* Invalid latest lobby must defer GO without consuming it, then recover. */
 for(int legacy=0;legacy<2;legacy++){setup(legacy,0);menu_state m=menu();lobby_current_valid=0;run_go(&m,1);assert(new_go&&!loading_count&&!close_count);lobby_current_valid=1;gate_ms=sample_ms=1500;run_go(&m,1.5);assert(!new_go&&loading_count==1&&!close_count&&VR.recovery.initialized);}
 for(int legacy=0;legacy<2;legacy++){setup(legacy,0);menu_state m=menu();lobby_current_valid=0;run_go(&m,1);assert(new_go&&!loading_count&&!close_count);gate_ms=3000;run_go(&m,3);assert(!loading_count&&close_count==1&&off_count==1&&!strcmp(closed_note,"LOBBY UNVERIFIED - RECONNECT"));}
 const double bad_gate[]={-1,NAN,INFINITY};
 for(unsigned i=0;i<sizeof bad_gate/sizeof bad_gate[0];i++){setup(0,0);menu_state m=menu();lobby_current_valid=0;gate_ms=bad_gate[i];run_go(&m,1);assert(close_count==1&&!loading_count&&!strcmp(closed_note,"LOBBY UNVERIFIED - RECONNECT"));}
 /* Owner bypasses an invalid client echo only after host control and frozen GO checks. */
 for(int legacy=0;legacy<2;legacy++){setup(legacy,0);menu_state m=menu();local_host=1;pending=1;lobby_current_valid=0;run_go(&m,1);assert(!new_go&&match_calls==1&&accepted_count==1&&!pending&&loading_count==1&&!close_count&&VR.recovery.initialized);}
 for(int legacy=0;legacy<2;legacy++){setup(legacy,0);menu_state m=menu();local_host=1;pending=1;lobby_current_valid=0;go_matches=0;run_go(&m,1);assert(match_calls==1&&off_count==1&&close_count==1&&!strcmp(closed_note,"UNEXPECTED GO - RECONNECT")&&!loading_count&&!accepted_count);}
 setup(0,0);{menu_state m=menu();local_host=1;pending=1;lobby_current_valid=0;control_ready=0;run_go(&m,1);assert(new_go&&!loading_count&&!match_calls&&!accepted_count&&!close_count);}
 /* Non-clock failure is deliberately injected via the init wrapper. */
 setup(0,0);menu_state m=menu();fake_init_failure=1;run_go(&m,10);
 assert(abandon_count==1&&abort_count==1&&!off_count&&!close_count&&!loading_count&&!song_count&&!save_count&&m.zone==9&&open_room);
 assert(!G.vs_wait&&!G.vs_seen_loaded&&!G.vs_day_at&&VR.flag==VS_RECOVERY_WIRE_ABORT&&VR.race==77&&VR.advertise_until==40);
 sample_ms=10000;assert(vs_recovery_profile(b)==47);assert(vs_recovery_wire_decode(&e,b,47)&&e.flags==VS_RECOVERY_WIRE_ABORT&&e.race_id==77&&e.nonce==100);
 vote_path(&m,&L,39.999);assert(!m.vs.area_go&&!m.vs.day&&!m.vs.start&&!area_count&&!day_count);
 new_go=1;run_go(&m,39);assert(abandon_count==2&&!loading_count&&!song_count&&m.zone==9);
 incoming.race=78;new_go=1;run_go(&m,39);assert(abandon_count==3&&!loading_count&&!song_count&&m.zone==9);
 sample_ms=39999;assert(vs_recovery_profile(b)==47&&vs_recovery_wire_decode(&e,b,47)&&e.flags==VS_RECOVERY_WIRE_ABORT);
 sample_ms=40000;assert(vs_recovery_profile(b)==47&&vs_recovery_wire_decode(&e,b,47)&&e.flags==VS_RECOVERY_WIRE_NORMAL);vote_path(&m,&L,40);assert(area_count==1&&day_count==1);
 setup(0,0);m=menu();fake_init_failure=1;host_closed=1;run_go(&m,10);assert(abandon_count==1&&off_count==1&&close_count==1&&!abort_count&&!loading_count&&!song_count&&m.zone==9&&!open_room&&!save_count);
 setup(0,0);m=menu();fake_init_failure=1;valid_silence=11;run_go(&m,10);assert(abandon_count==1&&off_count==1&&close_count==1&&!abort_count&&!loading_count);
 /* Recent GO/RACE is modeled by silence=0; it must not refresh the valid LOBBY clock. */
 setup(0,0);m=menu();fake_init_failure=1;silence=0;valid_silence=10.001;run_go(&m,10);assert(abandon_count==1&&close_count==1&&!abort_count&&!loading_count&&!open_room);
 setup(0,0);m=menu();fake_init_failure=1;L.host=2;run_go(&m,10);assert(close_count==1&&!abort_count);
 /* Actual clock regression between drained GO gate and begin closes. */
 setup(0,0);m=menu();gate_ms=2100;sample_ms=2050;run_go(&m,10);
 assert(VH.unknown&&abandon_count==1&&close_count==1&&off_count==1&&!strcmp(closed_note,"RECOVERY STATE UNKNOWN - RECONNECT")&&!abort_count&&!open_room&&!loading_count&&!song_count&&!save_count&&!observe_calls);
 setup(0,0);m=menu();gate_ms=2100;sample_ms=-1;run_go(&m,10);
 assert(VH.unknown&&close_count==1&&!strcmp(closed_note,"RECOVERY STATE UNKNOWN - RECONNECT")&&!open_room&&!loading_count);
 for(int i=0;i<2;i++){setup(0,0);m=menu();gate_ms=2100;sample_ms=i?2101:2100;run_go(&m,10);assert(!VH.unknown&&loading_count==1&&!close_count&&VR.recovery.initialized);}
 /* Pending owner init failure closes instead of retaining the room. */
 setup(0,0);m=menu();fake_init_failure=1;local_host=1;pending=1;valid_silence=99;run_go(&m,10);
 assert(abandon_count==1&&off_count==1&&close_count==1&&!strcmp(closed_note,"RECOVERY UNAVAILABLE - RECONNECT")&&!abort_count&&!open_room&&!loading_count&&!song_count&&!save_count&&!accepted_count&&m.zone==9);
 /* A matching race ID is insufficient when the host's frozen GO does not match. */
 setup(0,0);m=menu();local_host=1;pending=1;go_matches=0;run_go(&m,10);
 assert(match_calls==1&&off_count==1&&close_count==1&&!strcmp(closed_note,"UNEXPECTED GO - RECONNECT")&&!open_room&&!loading_count&&!song_count&&!save_count&&!accepted_count&&m.zone==9);
 /* The host-only comparison cannot reject a remote or legacy GO. */
 for(int legacy=0;legacy<2;legacy++){setup(legacy,0);m=menu();go_matches=0;run_go(&m,10);assert(!match_calls&&loading_count==1&&!off_count&&!close_count&&VR.recovery.initialized);}
 /* A matching initialized host round is accepted before loading. */
 setup(0,0);m=menu();local_host=1;pending=1;run_go(&m,10);
 assert(accepted_count==1&&!pending&&loading_count==1&&song_count==1&&!off_count&&!close_count&&!abandon_count&&VR.recovery.initialized&&observe_calls==1&&!fake_abort_calls&&G.vs_seen_loaded==5&&!G.vs_wait);
 /* Stubbed latest-lobby observer reports an already visible peer ABORT. */
 setup(0,0);m=menu();local_host=1;pending=1;fake_observe_abort=1;run_go(&m,10);
 assert(observe_calls==1&&fake_abort_calls==1&&!accepted_count&&!loading_count&&!song_count&&!save_count&&pending&&m.zone==9);
 /* Frozen GO itself contains a same-race peer ABORT: real wire parser and
    recovery request run, while abort-to-lobby is a reporting stub. */
 setup(0,0);m=menu();local_host=1;pending=1;
 {unsigned char base[21];vs_profile(base);vs_recovery_wire_extension e={VS_RECOVERY_WIRE_ABORT,77,101,10};
 assert(vs_recovery_wire_encode(incoming.player[1].profile,sizeof incoming.player[1].profile,base,21,&e));
 assert(vs_recovery_wire_put_ready(incoming.player[1].profile,sizeof incoming.player[1].profile,0));}
 run_go(&m,10);
 assert(fake_abort_calls==1&&!observe_calls&&!accepted_count&&!loading_count&&!song_count&&!save_count&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL&&pending&&m.zone==9);
 /* A different race's frozen ABORT is not this race's cancellation. */
 setup(0,0);m=menu();local_host=1;pending=1;
 {unsigned char base[21];vs_profile(base);vs_recovery_wire_extension e={VS_RECOVERY_WIRE_ABORT,78,101,10};
 assert(vs_recovery_wire_encode(incoming.player[1].profile,sizeof incoming.player[1].profile,base,21,&e));
 assert(vs_recovery_wire_put_ready(incoming.player[1].profile,sizeof incoming.player[1].profile,0));}
 run_go(&m,10);
 assert(!fake_abort_calls&&observe_calls==1&&accepted_count==1&&loading_count==1&&G.vs_seen_loaded==5);
 /* An unready host defers consumption; failed acceptance cannot load. */
 setup(0,0);m=menu();local_host=1;pending=1;control_ready=0;run_go(&m,10);
 assert(new_go&&!accepted_count&&!loading_count&&!off_count&&!close_count);
 setup(0,0);m=menu();local_host=1;pending=1;retain_pending=1;run_go(&m,10);
 assert(accepted_count==1&&abandon_count==1&&off_count==1&&close_count==1&&!strcmp(closed_note,"HOST ROUND CHANGED - RECONNECT")&&!loading_count&&!song_count&&!save_count);
 setup(0,0);m=menu();fake_init_failure=1;valid_silence=-.001;run_go(&m,10);assert(close_count==1&&!abort_count);
 setup(0,0);m=menu();fake_init_failure=1;run_go(&m,-.001);assert(close_count==1&&!abort_count); /* actual negative first sample cannot keep room */
 /* Distinct frame and initialization samples are a deliberate clock stub;
    no production clock or save path is executed by this fixture. */
 const double invalid_times[]={NAN,INFINITY,0x1p63};
 for(unsigned i=0;i<sizeof invalid_times/sizeof invalid_times[0];i++){
   setup(0,0);m=menu();sample_ms=invalid_times[i];run_go(&m,10);
   assert(abandon_count==1&&!abort_count&&close_count==1&&!strcmp(closed_note,"RECOVERY STATE UNKNOWN - RECONNECT")&&!open_room&&!loading_count&&!song_count&&!save_count&&m.zone==9&&!VR.recovery.initialized);
   setup(0,0);m=menu();sample_ms=invalid_times[i];host_closed=1;run_go(&m,10);
   assert(abandon_count==1&&close_count==1&&!abort_count&&!open_room&&!loading_count&&!song_count&&!save_count&&m.zone==9&&!VR.recovery.initialized);
 }
 setup(0,1);m=menu();fake_init_failure=1;run_go(&m,10);assert(abort_count==1&&!loading_count&&VR.flag==VS_RECOVERY_WIRE_ABORT);sample_ms=10000;memset(b,0,sizeof b);assert(vs_recovery_profile(b)==21&&!vs_recovery_wire_decode(&e,b,21));
 puts("GO init-failure branch with extracted app helpers: PASS (stub UI/net/clock, no persistence)");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='vs-init-failure-') as d:
    d=Path(d); c=d/'test.c'; exe=d/'test'
    c.write_text(pre+helpers+'\nstatic void run_go(menu_state*m,double now){\nfirst_gate_sample=1;\n'+branch+'}\nstatic void vote_path(menu_state*m,const net_lobby*l,double now){\n'+vote+'\n}\n'+post)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined,float-cast-overflow','-D__ANDROID__','-I'+str(root/'src'),str(c),str(root/'src/vs_recovery.c'),str(root/'src/vs_recovery_wire.c'),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
