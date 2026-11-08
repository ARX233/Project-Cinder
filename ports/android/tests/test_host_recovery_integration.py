#!/usr/bin/env python3
"""No sockets: real WV1 host/net and extracted app helpers, fake game boundaries.
Not an Android UI, full app execution, authenticated network, or rewards test.
Run: python3 ports/android/tests/test_host_recovery_integration.py
"""
from pathlib import Path
import subprocess, tempfile
R=Path(__file__).resolve().parents[1]
s=(R/'src/app.c').read_text()
def take(m):
 p=s.index(m); start=s.index('{',p); depth=1; i=start+1
 while depth:
  depth+=(s[i]=='{')-(s[i]=='}'); i+=1
 return s[p:i]+'\n'
helpers=''.join(take(m) for m in ('static int vs_day_go_timeout(', 'static int vs_recovery_profile(', 'static void vs_recovery_begin(', 'static int vs_recovery_finish_ready(', 'static int vs_recovery_observe_now(', 'static int vs_abort_to_lobby(', 'static int vs_others_loaded('))
host=r'''
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <string.h>
extern int host_recv(void*,int,struct sockaddr_in*);
extern void host_send(const void*,int,int);
static ssize_t fake_recvfrom(int f,void*b,size_t n,int flags,struct sockaddr*a,socklen_t*l){(void)f;(void)flags;(void)l;return host_recv(b,(int)n,(struct sockaddr_in*)a);}
static ssize_t fake_sendto(int f,const void*b,size_t n,int flags,const struct sockaddr*a,socklen_t l){(void)f;(void)flags;(void)l;host_send(b,(int)n,ntohs(((const struct sockaddr_in*)a)->sin_port));return (ssize_t)n;}
#define recvfrom fake_recvfrom
#define sendto fake_sendto
#include "vs_host.c"
void setup_host(void){memset(&H,0,sizeof H);H.fd=123;H.open=1;H.owner=11;H.km=13;}
int host_count(void){return H.n;}
'''
client=r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "net.c"
#include "vs_recovery.h"
extern void vs_host_disarm_round(void);
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
typedef struct {int waiting; double since,last;} vs_receive_gate;
static vs_receive_gate VG_go,VG_finish;
static vs_abort_history VH;
static int VH_abort_unknown,VH_has_time;
static double VH_last_time;
#define VS_PROFILE 21
#define VS_GONE 10.0
#define VS_FINISH_WAIT_SECONDS 180.0
#define MENU_VS_LOADED 70
#define MENU_BGM 1
#define MENU_VS_LOBBY 2
typedef struct {int screen;struct {int day,state;} vs;} menu_state;
extern int active,host_owner,legacy_mask;
extern double clock_now;
extern void enqueue_host(const void*,int,int);
extern int dequeue_client(void*,int,int);
int gk_send(int peer,const void*b,int n){(void)peer;enqueue_host(b,n,active);return 0;}
int gk_recv(void*b,int n,int*peer){*peer=0;return dequeue_client(b,n,active);}
void car_link_deliver(int pcb,const unsigned char*p,int n){(void)pcb;(void)p;(void)n;}
static double now_ms(void){return clock_now*1000;}
static void vs_profile(unsigned char*p){memset(p,7,21);}
typedef struct {vs_recovery recovery;uint64_t nonce,peer_nonce[NET_PLAYERS],host_id;uint32_t seq,peer_seq[NET_PLAYERS],race,last_go;unsigned finished,capable,ready_capable;int all_new,local_finished,echo_confirmed,local_loaded,abort_after_result;double advertise_until,finish_wait_at;unsigned char flag;} vs_recovery_app;
static vs_recovery_app VR;
static struct {uint32_t vs_id;net_go vs_go;int vs_race,vs_closed,paused,vs_wait,vs_seen_loaded,in_menu;double vs_abort_note_until;struct {int dummy,finish,finish_story;} menu;struct {int screen_w,screen_h;} hud;struct {car_race race;} car;} G;
static int race_junction_ui,race_junction_barrier;
static int vs_host_is_open(void){return active==host_owner;}
/* This in-memory H runs legacy/nonlocal START, not local-mode frozen GO.
 * Model the loading matcher as permissive here; this fixture does not test it. */
static int vs_host_loading_lobby_matches(const net_lobby *l,uint32_t race){(void)l;(void)race;return 1;}
void car_clear_junction(car_race*x){(void)x;}
static void junction_ui_reset(int*x){(void)x;}
static void junction_barrier_reset(int*x){(void)x;}
static void snd_quiet(void){}
static void hud_init(void*x,int w,int h){(void)x;(void)w;(void)h;}
static void menu_vs_aborted(void*x,const char*y){(void)x;(void)y;}
static void menu_vs_closed(void*x,const char*y){(void)x;(void)y;}
static void vs_off(void){memset(&VR,0,sizeof VR);}
'''+helpers+r'''
static __typeof__(N) ns[4];static __typeof__(G) gs[4];static vs_recovery_app vrs[4];
static vs_abort_history histories[4];static int history_unknowns[4],history_has_time[4];static double history_last_time[4];static vs_receive_gate go_gates[4],finish_gates[4];
static void load(int i){active=i;N=ns[i];G=gs[i];VR=vrs[i];VH=histories[i];VH_abort_unknown=history_unknowns[i];VH_has_time=history_has_time[i];VH_last_time=history_last_time[i];VG_go=go_gates[i];VG_finish=finish_gates[i];}
static void save(int i){ns[i]=N;gs[i]=G;vrs[i]=VR;histories[i]=VH;history_unknowns[i]=VH_abort_unknown;history_has_time[i]=VH_has_time;history_last_time[i]=VH_last_time;go_gates[i]=VG_go;finish_gates[i]=VG_finish;}
/* Production Android net startup enables strict lobby validation. Keep this
 * manual transport fixture on that same contract, not a permissive cache. */
void client_init(int i){active=i;memset(&N,0,sizeof N);N.fd=-1;N.gk=1;N.id=11+i;N.last_hello=-1e9;net_use_strict_lobby(1);memset(&G,0,sizeof G);memset(&VR,0,sizeof VR);G.vs_id=11+i;VR.nonce=100+i;vs_abort_history_reset(&VH);VH_abort_unknown=VH_has_time=0;VH_last_time=0;memset(&VG_go,0,sizeof VG_go);memset(&VG_finish,0,sizeof VG_finish);save(i);}
void client_poll(int i,int status){unsigned char p[47];load(i);int n=vs_recovery_profile(p);if (legacy_mask & (1<<i)) n=21;net_poll(clock_now,status,"player",p,n);save(i);}
void client_start(int i){load(i);net_start(1,13,1);save(i);}
void client_go(int i){load(i);assert(net_take_go(&G.vs_go));assert(G.vs_go.n>=2);G.vs_race=1;vs_recovery_begin(&G.vs_go);save(i);}
int client_observe(int i){load(i);int a=vs_recovery_observe_now();if(a)assert(vs_abort_to_lobby());save(i);return a;}
int client_in_room(int i,int count){load(i);int ok=N.valid_lobby_snapshot.connected && N.valid_lobby_snapshot.n==count && net_is_open() && G.in_menu && !G.vs_race && VR.flag==VS_RECOVERY_WIRE_ABORT;save(i);return ok;}
int client_loaded(int i){load(i);int a=vs_others_loaded();save(i);return a;}
void client_set_loaded(int i){load(i);VR.local_loaded=1;save(i);}
int client_finish(int i){load(i);int a=vs_recovery_finish_ready();save(i);return a;}
void client_spoof(int i,int flag,int oldrace,int oldnonce){
 unsigned char p[47],base[21];vs_recovery_wire_extension e;load(i);
 assert(vs_recovery_profile(p)==47);memcpy(base,p,21);assert(vs_recovery_wire_decode(&e,p,47));
 e.flags=flag;e.race_id=oldrace?G.vs_go.race-1:G.vs_go.race;if(oldnonce)e.nonce+=200;
 assert(vs_recovery_wire_encode(p,sizeof p,base,sizeof base,&e));assert(vs_recovery_wire_put_ready(p,sizeof p,0));
 net_poll(clock_now,1,"player",p,47);save(i);
}
int no_go_timeout(int i,double elapsed){load(i);menu_state m={MENU_BGM,{1,MENU_VS_LOBBY}};int r=vs_day_go_timeout(&m,net_lobby_valid_now(),100+elapsed,100);save(i);return r;}
int loading_tick(int i){load(i);int waiting=!vs_others_loaded();G.vs_wait=waiting?G.vs_wait+1:0;int r=0;if(waiting && G.vs_wait>=3600 && vs_recovery_request_abort(&VR.recovery)==VS_RECOVERY_EMIT_ABORT)r=vs_abort_to_lobby();save(i);return r;}
void client_race(int i){unsigned char p[CAR_LINK_PACKET]={0};load(i);net_race_send(p,sizeof p);save(i);}
void client_strict(int i){load(i);net_require_valid_go(1);save(i);}
void client_pending(int i){load(i);assert(N.go_new && N.go.race==2 && N.go.pcb==0 && N.go.player[0].id==12 && N.race==1 && N.race_pcb==1);save(i);}
void client_taken(int i){load(i);net_go g;assert(net_take_go(&g)&&g.race==2&&g.pcb==0&&g.player[0].id==12&&N.race==2&&N.race_pcb==0);save(i);}
int client_closed(int i){load(i);int x=G.in_menu && !G.vs_race && !VR.recovery.initialized && VR.flag==0;save(i);return x;}
void client_abort_wire(int i){unsigned char p[47];vs_recovery_wire_extension e;load(i);assert(vs_recovery_profile(p)==47);assert(vs_recovery_wire_decode(&e,p,47));assert(e.flags==VS_RECOVERY_WIRE_ABORT && e.race_id==1 && e.nonce==(uint64_t)(100+i));save(i);}
/* Profile advertisement expiry only, not the menu's start gate. */
void client_expiry(int i){unsigned char p[47];vs_recovery_wire_extension e;load(i);double expiry=VR.advertise_until;assert(expiry>0);clock_now=expiry-0.001;assert(vs_recovery_profile(p)==47 && vs_recovery_wire_decode(&e,p,47) && e.flags==VS_RECOVERY_WIRE_ABORT && e.race_id==1);clock_now=expiry;assert(vs_recovery_profile(p)==47 && vs_recovery_wire_decode(&e,p,47) && e.flags==VS_RECOVERY_WIRE_NORMAL && e.race_id==0);save(i);}
'''
main=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <arpa/inet.h>
#include <sys/socket.h>
int active,host_owner=0,legacy_mask,drop_client=-1,truncate_race,reorder_guest_go;double clock_now;
static int race_sends,last_race_pcb;static unsigned last_race_id;
struct packet {unsigned char data[2048];int len,id;};
static struct packet up[4096],down[4][4096];static int un,dn[4];
void enqueue_host(const void*b,int n,int id){const unsigned char*q=b;if(id==1&&n>=9&&q[3]==5){race_sends++;last_race_id=(unsigned)q[4]|(unsigned)q[5]<<8|(unsigned)q[6]<<16|(unsigned)q[7]<<24;last_race_pcb=q[8];}assert(un<4096 && n<=2048);up[un].id=id;up[un].len=n;memcpy(up[un++].data,b,n);}
int host_recv(void*b,int max,struct sockaddr_in*a){if(!un)return 0;struct packet p=up[0];memmove(up,up+1,(--un)*sizeof *up);assert(p.len<=max);memcpy(b,p.data,p.len);memset(a,0,sizeof *a);a->sin_family=AF_INET;a->sin_port=htons(41000+p.id);a->sin_addr.s_addr=htonl(0x7f000001);return p.len;}
void host_send(const void*b,int n,int port){int id=port-41000;assert(id>=0&&id<4&&dn[id]<4096&&n<=2048);if(id==drop_client)return;if(truncate_race && n>=4 && ((const unsigned char*)b)[3]==5)n=9;struct packet*p=&down[id][dn[id]++];p->len=n;memcpy(p->data,b,n);
 /* Test-only deterministic transformation of the real host's race-2 GO:
    its two original records remain intact but the PCB labels are swapped. */
 if(reorder_guest_go&&id==1&&n>=16&&p->data[3]==4&&p->data[4]==2){
   assert(p->data[14]==2&&p->data[15]==1);int first=16;int second=first+22+p->data[first+21];
   assert(second+22<=n&&p->data[first]==0&&p->data[second]==1);
   p->data[15]=0;p->data[first]=1;p->data[second]=0;
 }
}
int dequeue_client(void*b,int max,int id){if(!dn[id])return 0;struct packet p=down[id][0];memmove(down[id],down[id]+1,(--dn[id])*sizeof p);assert(p.len<=max);memcpy(b,p.data,p.len);return p.len;}
void setup_host(void);void vs_host_poll(double,const char*);int host_count(void);
void client_abort_wire(int);void client_expiry(int);
void client_init(int);void client_poll(int,int);void client_start(int);void client_go(int);int client_observe(int);int client_in_room(int,int);int client_loaded(int);void client_set_loaded(int);int client_finish(int);void client_race(int);int client_closed(int);void client_spoof(int,int,int,int);int no_go_timeout(int,double);int loading_tick(int);void client_strict(int);void client_pending(int);void client_taken(int);
static void pump(int n,int mask,int status){for(int i=0;i<n;i++)if(mask&(1<<i))client_poll(i,status);vs_host_poll(clock_now,"host");for(int i=0;i<n;i++)if(mask&(1<<i))client_poll(i,status);vs_host_poll(clock_now,"host");}
int main(void){
 setup_host();for(int i=0;i<3;i++)client_init(i);
 clock_now=1;pump(3,7,0);assert(host_count()==3);client_start(0);vs_host_poll(clock_now,"host");pump(3,7,0);
 for(int i=0;i<3;i++)client_go(i);
 assert(!client_loaded(0));for(int i=0;i<3;i++)client_set_loaded(i);clock_now=2;pump(3,7,1);for(int i=0;i<3;i++)client_observe(i);assert(client_loaded(0));
 assert(client_finish(0)==0);assert(client_finish(1)==0);
 for(int t=3;t<=28;t++){
   clock_now=t;drop_client=(t>=22 && t<=26)?1:-1;
   pump(3,3,1);for(int i=0;i<2;i++)client_observe(i);
   if(t==26){assert(client_in_room(0,2));assert(!client_in_room(1,2));}
 }
 drop_client=-1;
 assert(host_count()==2);clock_now=29;pump(3,3,0);for(int i=0;i<2;i++)client_observe(i);
 assert(client_in_room(0,2)&&client_in_room(1,2));
 /* A 21-byte old client advertises status 1: only an actual complete race
    packet proves it started after missing the short status-70 interval. */
 un=0;memset(dn,0,sizeof dn);legacy_mask=2;setup_host();for(int i=0;i<2;i++)client_init(i);
 clock_now=100;pump(2,3,0);client_start(0);vs_host_poll(clock_now,"host");pump(2,3,0);
 for(int i=0;i<2;i++)client_go(i);
 clock_now=101;pump(2,3,1);client_observe(0);assert(!client_loaded(0));
 truncate_race=1;client_race(1);vs_host_poll(clock_now,"host");client_poll(0,1);assert(!client_loaded(0));truncate_race=0;client_race(1);vs_host_poll(clock_now,"host");client_poll(0,1);assert(client_loaded(0));
 assert(client_finish(0)==1); /* legacy policy is intentionally not new-only gating */
 /* Legacy owner is a live ordinary host; only the new survivor's recovery
    is asserted, not any return behavior on the old build. */
 un=0;memset(dn,0,sizeof dn);legacy_mask=1;setup_host();for(int i=0;i<3;i++)client_init(i);
 clock_now=120;pump(3,7,0);client_start(0);vs_host_poll(clock_now,"host");pump(3,7,0);for(int i=0;i<3;i++)client_go(i);
 for(int t=121;t<=146;t++){clock_now=t;pump(3,3,1);client_observe(1);}
 clock_now=147;pump(3,3,0);client_observe(1);assert(host_count()==2&&client_in_room(1,2));
 /* A client misses GO: exercise the actual 90-second predicate against
    host-produced lobby; timeout action in vs_menu is not executed here. */
 un=0;memset(dn,0,sizeof dn);legacy_mask=0;setup_host();for(int i=0;i<2;i++)client_init(i);
 clock_now=148;pump(2,3,0);assert(!no_go_timeout(1,89.999));assert(no_go_timeout(1,90));assert(!no_go_timeout(0,90));
 /* Old race/nonce FINISHED and ABORT are delivered through the actual host
    relay. These are deterministic forged profile replays, not authentication. */
 un=0;memset(dn,0,sizeof dn);setup_host();for(int i=0;i<2;i++)client_init(i);
 clock_now=149;pump(2,3,0);client_start(0);vs_host_poll(clock_now,"host");pump(2,3,0);
 client_start(0);vs_host_poll(clock_now,"host");pump(2,3,0);for(int i=0;i<2;i++)client_go(i);
 assert(client_finish(0)==0);
 for(int flag=1;flag<=2;flag++)for(int kind=0;kind<2;kind++){
   clock_now+=1;client_spoof(1,flag,kind==0,kind==1);vs_host_poll(clock_now,"host");client_poll(0,1);
   assert(!client_observe(0));assert(client_finish(0)==0);
 }
 /* Model only the menu's frame counter/branch around real loading helper and
    recovery primitives. 3600 ticks correspond to 60 seconds at 60 Hz. */
 for(int i=0;i<3599;i++)assert(!loading_tick(0));assert(loading_tick(0));assert(client_in_room(0,2));
 /* Four new clients: lost snapshots do not prematurely grant a finish.
    Fresh repeated announcements eventually reach the lagging client. */
 un=0;memset(dn,0,sizeof dn);legacy_mask=0;setup_host();for(int i=0;i<4;i++)client_init(i);
 clock_now=150;pump(4,15,0);client_start(0);vs_host_poll(clock_now,"host");pump(4,15,0);for(int i=0;i<4;i++)client_go(i);
 drop_client=0;for(int i=0;i<4;i++)assert(client_finish(i)==0);
 for(int t=151;t<=153;t++){clock_now=t;pump(4,15,1);for(int i=0;i<4;i++)client_observe(i);}
 assert(client_finish(0)==0);drop_client=-1;
 for(int t=154;t<=156;t++){clock_now=t;pump(4,15,1);for(int i=0;i<4;i++)client_observe(i);}
 for(int i=0;i<4;i++)assert(client_finish(i)==1);
 /* Losing the owner is different from losing an ordinary member: no kept room. */
 un=0;memset(dn,0,sizeof dn);legacy_mask=0;setup_host();for(int i=0;i<3;i++)client_init(i);
 clock_now=200;pump(3,7,0);client_start(0);vs_host_poll(clock_now,"host");pump(3,7,0);for(int i=0;i<3;i++)client_go(i);
 for(int t=201;t<=228;t++){clock_now=t;pump(3,6,1);for(int i=1;i<3;i++)client_observe(i);}
 assert(host_count()==2);assert(client_closed(1)&&client_closed(2));
 /* Actual host emits race 1, both real clients take it. Change only the
    guest's race-2 GO PCB labels in the fake transport; strict parsing must
    accept it while the race-1 transmit identity remains pinned until take. */
 un=0;memset(dn,0,sizeof dn);legacy_mask=0;drop_client=-1;setup_host();for(int i=0;i<2;i++){client_init(i);client_strict(i);}
 clock_now=300;pump(2,3,0);client_start(0);vs_host_poll(clock_now,"host");pump(2,3,0);client_go(0);client_go(1);
 race_sends=0;client_race(1);assert(race_sends==1&&last_race_id==1&&last_race_pcb==1);
 reorder_guest_go=1;client_start(0);vs_host_poll(clock_now,"host");client_poll(1,1);client_pending(1);
 client_race(1);assert(race_sends==2&&last_race_id==1&&last_race_pcb==1);
 client_taken(1);client_race(1);assert(race_sends==3&&last_race_id==2&&last_race_pcb==0);reorder_guest_go=0;
 /* 2/3/4 current clients, in-memory transport: final status-1 heartbeat at
    t=400, no expiry at exactly 20s, expiry at 21s. This does not execute
    the actual menu/UI, score/save commit, or UDP socket transport. */
 for(int count=2; count<=4; count++) {
    un=0;memset(dn,0,sizeof dn);legacy_mask=0;drop_client=-1;setup_host();
    for(int i=0;i<count;i++)client_init(i);
    clock_now=400;pump(count,(1<<count)-1,0);assert(host_count()==count);
    client_start(0);vs_host_poll(clock_now,"host");pump(count,(1<<count)-1,0);
    for(int i=0;i<count;i++)client_go(i);
    pump(count,(1<<count)-1,1);
    int alive=(1<<(count-1))-1;
    for(int t=401;t<=435;t++) {clock_now=t;pump(count,alive,1);for(int i=0;i<count-1;i++)client_observe(i);if(t==420)assert(host_count()==count);if(t==421)assert(host_count()==count-1);}
    assert(host_count()==count-1);
    clock_now=436;pump(count,alive,0);for(int i=0;i<count-1;i++)client_observe(i);
    for(int i=0;i<count-1;i++){assert(client_in_room(i,count-1));client_abort_wire(i);}
    for(int i=0;i<count-1;i++)client_expiry(i);
    printf("racing timeout + same-race abort cooldown: peers=%d survivors=%d\n",count,count-1);
 }
 puts("WV1 host/net + extracted app recovery/loaded helpers: in-memory scenarios PASS");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='wv1-integration-') as d:
 d=Path(d)
 for name,text in [('host.c',host),('client.c',client),('main.c',main)]: (d/name).write_text(text)
 exe=d/'test'
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-fsanitize=undefined','-D__ANDROID__','-I'+str(R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(R/'src/vs_recovery.c'),str(R/'src/vs_recovery_wire.c'),str(R/'src/vs_abort_history.c'),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
