#!/usr/bin/env python3
"""Real net.c + extracted app recovery on synthetic WV1 datagrams.

No socket, host, Android lifecycle, UI, rendering, or reward persistence is run.
The clock, transport and non-recovery game boundaries are test stubs.
Run: python3 tests/test_vs_missing_snapshot_host.py
"""
from pathlib import Path
import subprocess, tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'src/app.c').read_text()
def take(marker):
 p=s.index(marker); i=s.index('{',p)+1; depth=1
 while depth:
  depth+=(s[i]=='{')-(s[i]=='}'); i+=1
 return s[p:i]+'\n'
helpers=''.join(take(x) for x in ('static void vs_recovery_begin(', 'static int vs_recovery_observe_now(', 'static int vs_abort_to_lobby('))
c=r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "net.c"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
typedef struct {int waiting; double since,last;} vs_receive_gate;
static vs_receive_gate VG_go,VG_finish;
static vs_abort_history VH;
static int VH_abort_unknown,VH_has_time;
static double VH_last_time;
#define VS_GONE 10.0
static double ms;
static double now_ms(void){return ms;}
typedef struct {vs_recovery recovery;uint64_t nonce,peer_nonce[NET_PLAYERS],host_id;uint32_t seq,peer_seq[NET_PLAYERS],race,last_go;unsigned finished,capable,ready_capable;int all_new,local_finished,echo_confirmed,local_loaded,abort_after_result;double advertise_until,finish_wait_at;unsigned char flag;} vs_recovery_app;
static vs_recovery_app VR;
static struct {uint32_t vs_id;net_go vs_go;int vs_race,vs_closed,paused,vs_wait,vs_seen_loaded,in_menu;double vs_abort_note_until;struct {int x,finish,finish_story;} menu;struct {int screen_w,screen_h;} hud;struct {car_race race;} car;} G;
static int race_junction_ui,race_junction_barrier,menu_abort,menu_close,off_count,disarmed;
int gk_send(int peer,const void*b,int n){(void)peer;(void)b;(void)n;return 0;}
int gk_recv(void*b,int n,int*peer){(void)b;(void)n;(void)peer;return 0;}
void car_link_deliver(int p,const unsigned char*b,int n){(void)p;(void)b;(void)n;}
void car_clear_junction(car_race*r){(void)r;}
static int vs_host_is_open(void){return 0;}
static void vs_host_disarm_round(void){++disarmed;}
static void junction_ui_reset(int*x){(void)x;}
static void junction_barrier_reset(int*x){(void)x;}
static void snd_quiet(void){}
static void hud_init(void*x,int w,int h){(void)x;(void)w;(void)h;}
static void menu_vs_aborted(void*m,const char*n){(void)m;(void)n;menu_abort++;}
static void menu_vs_closed(void*m,const char*n){(void)m;(void)n;menu_close++;}
static void vs_off(void){off_count++;memset(&VR,0,sizeof VR);}
'''+helpers+r'''
static int go_packet(unsigned char*b,unsigned race){head(b,GO);put32(b+4,race);put32(b+8,123);b[12]=0;b[13]=13;b[14]=2;b[15]=0;int at=16;for(int i=0;i<2;i++){b[at++]=i;put32(b+at,11+i);at+=4;memset(b+at,65+i,NET_NAME);at+=NET_NAME;b[at++]=0;}b[at++]=3;return at;}
static int lobby_packet(unsigned char*b,int invalid){head(b,LOBBY);b[4]=2;b[5]=0;b[6]=0;b[7]=0;b[8]=13;put32(b+9,1);int at=13;for(int i=0;i<2;i++){b[at++]=invalid?0:i;put32(b+at,11+i);at+=4;b[at++]=1;memset(b+at,65+i,NET_NAME);at+=NET_NAME;b[at++]=0;}return at;}
static void setup(void){unsigned char b[2048];memset(&G,0,sizeof G);memset(&VR,0,sizeof VR);vs_abort_history_reset(&VH);VH_abort_unknown=VH_has_time=0;VH_last_time=0;memset(&VG_go,0,sizeof VG_go);memset(&VG_finish,0,sizeof VG_finish);menu_abort=menu_close=off_count=disarmed=0;assert(net_open_gk(11)==0);G.vs_id=11;ms=1000;int n=go_packet(b,1);got(b,n,1);assert(net_take_go(&G.vs_go));G.vs_race=1;vs_recovery_begin(&G.vs_go);assert(VR.recovery.initialized&&VR.recovery.last_time_ms==1000&&!net_lobby_observations());}
static void inject_lobby(double seconds,int invalid){unsigned char b[2048];int n=lobby_packet(b,invalid);got(b,n,seconds);}
static void inject_go(double seconds){unsigned char b[2048];int n=go_packet(b,2);got(b,n,seconds);}
static void inject_race(double seconds){unsigned char b[2048];head(b,RACE);put32(b+4,1);b[8]=1;memset(b+9,0,CAR_LINK_PACKET);got(b,9+CAR_LINK_PACKET,seconds);}
int main(void){
 setup();ms=10999;assert(!vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_NO_ABORT);
 ms=11000;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);assert(vs_abort_to_lobby());assert(menu_close==1&&off_count==1&&!menu_abort&&G.in_menu&&!G.vs_race&&!disarmed);
 setup();ms=10999;inject_lobby(10.999,0);assert(net_lobby_observations()==1);assert(!vs_recovery_observe_now()&&VR.recovery.last_serial==1&&VR.recovery.last_time_ms==10999);ms=11000;assert(!vs_recovery_observe_now());
 /* A current strict snapshot is accepted, then missing-roster grace works. */
 unsigned char b[2048];int n=lobby_packet(b,0);b[4]=1; /* trim second player; me+host slot zero */
 n=13+1+4+1+NET_NAME+1;got(b,n,11.1);ms=11100;assert(!vs_recovery_observe_now());got(b,n,13.1);ms=13100;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_MISSING);
 /* GO and permissively parsed but strict-invalid lobby cannot refresh. */
 setup();inject_lobby(9,1);assert(net_lobby_now()->connected&&!net_lobby_observations()&&!net_lobby_valid_now()->connected);inject_go(10);assert(net_silence(10)==0&&!net_lobby_observations());ms=10999;assert(!vs_recovery_observe_now());ms=11000;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);
 /* After valid data, GO/RACE/invalid LOBBY do not refresh strict timestamp. */
 setup();inject_lobby(2,0);ms=2000;assert(!vs_recovery_observe_now()&&net_lobby_observations()==1);inject_go(11);inject_race(11.5);inject_lobby(11.9,1);assert(net_lobby_observations()==1&&net_lobby_valid_silence(12)==10);ms=12000;assert(!vs_recovery_observe_now());ms=12001;assert(vs_recovery_observe_now()&&VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL);
 /* Immediate loss, with and without a previously validated lobby. */
 setup();N.gk=0;N.fd=-1;ms=1001;assert(vs_recovery_observe_now());assert(vs_abort_to_lobby()&&menu_close==1&&off_count==1&&!G.vs_race);
 setup();inject_lobby(1.1,0);N.gk=0;N.fd=-1;ms=1100;assert(vs_recovery_observe_now());assert(vs_abort_to_lobby()&&menu_close==1&&off_count==1&&!G.vs_race);
 puts("real net + app observe missing/invalid/stale lobby: PASS (synthetic WV1)");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='vs-missing-snapshot-') as d:
 d=Path(d);(d/'test.c').write_text(c)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=undefined,float-cast-overflow','-D__ANDROID__','-I'+str(root/'src'),str(d/'test.c'),str(root/'src/vs_recovery.c'),str(root/'src/vs_recovery_wire.c'),str(root/'src/vs_abort_history.c'),'-o',str(d/'test')],check=True)
 subprocess.run([str(d/'test')],check=True)
