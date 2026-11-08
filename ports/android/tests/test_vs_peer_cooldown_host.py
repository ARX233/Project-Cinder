#!/usr/bin/env python3
"""Peer cooldown: real app helper/day/START and host, fake snapshots.

Conservatively wait on reordered slots: the historical visible lobby follows wire
order while strict uses slots, and voting indexes the visible projection.
"""
from pathlib import Path
import subprocess, tempfile
R=Path(__file__).resolve().parents[1]
s=(R/'src/app.c').read_text()
def take(marker):
 p=s.index(marker); q=s.index('{',p); n=1; i=q+1
 while n:
  n+=(s[i]=='{')-(s[i]=='}'); i+=1
 return s[p:i]+'\n'
a=s.index('  if (m->vs.start) {',s.index('static void vs_menu(void)'))
b=s.index('\n  net_go go;',a)
pre=r"""
#include <assert.h>
#include <math.h>
#include <string.h>
#include "vs_host.c"
#include "vs_recovery_wire.h"
#define VS_GONE 10.0
#define VS_AREA_LATE 3.0
#define VS_REVEAL 1.6
#define MENU_BGM 1
#define MENU_VS 2
#define MENU_VS_LOBBY 2
#define MENU_VS_DAY_FINAL 10
#define MENU_VS_LOADED 20
struct vote {int day,n,day_final,day_timer,me,day_voted,other_day[NET_PLAYERS],other_zone[NET_PLAYERS],ramp,km;int start,state,area_go,racing[NET_PLAYERS],mismatch[NET_PLAYERS];};
typedef struct {int screen,zone,zones,song;struct vote vs;} menu_state;
static struct {double vs_day_at,vs_day_final_at,vs_day_started,vs_wait_note_until;int vs_song;} G;
static struct {int flag;double advertise_until;} VR;
static net_lobby strict;
static double silence;
static int current_valid=1;
int net_lobby_current_valid(void){return current_valid;}
const net_lobby *net_lobby_valid_now(void){return &strict;}
double net_lobby_valid_silence(double now){(void)now;return silence;}
static void vs_off(void){assert(!"unexpected close");}
static void menu_vs_closed(menu_state*m,const char*x){(void)m;(void)x;assert(!"unexpected close");}
static int vs_same_build(const net_player*p){(void)p;return 1;}
static int vs_own_lobby_ready(const net_lobby*l,const menu_state*m){(void)l;(void)m;return 1;}
static int remote_starts;
void net_start(int a,int b,int c){(void)a;(void)b;(void)c;++remote_starts;}
int gk_send(int p,const void*b,int n){(void)p;(void)b;return n;}
int gk_recv(void*b,int n,int*p){(void)b;(void)n;(void)p;return 0;}
"""
post=r"""
static void setflag(int flag){unsigned char base[21]={0};vs_recovery_wire_extension e={flag,flag?77:0,1002,10};assert(vs_recovery_wire_encode(strict.player[1].profile,NET_PROFILE,base,21,&e));strict.player[1].profile_len=42;memcpy(H.p[1].profile,strict.player[1].profile,42);H.p[1].profile_len=42;}
int main(void){
 memset(&H,0,sizeof H);H.fd=-1;H.open=H.local_mode=H.control_ready=1;H.owner=1;H.n=2;
 strict.connected=1;strict.n=2;strict.me=strict.host=0;
 for(int i=0;i<2;i++){H.p[i].id=strict.player[i].id=i+1;H.p[i].from.a.sin_family=AF_INET;H.p[i].from.a.sin_addr.s_addr=htonl(0x7f000001);H.p[i].from.a.sin_port=htons(1000+i);H.p[i].profile_len=strict.player[i].profile_len=21;}
 setflag(1);assert(vs_host_lobby_matches(&strict));assert(vs_peer_cooldown(&strict,&strict,10));
 menu_state state={0},*m=&state;const net_lobby*l=&strict;double now=10;m->screen=MENU_VS;m->vs.state=MENU_VS_LOBBY;m->vs.start=1;
"""+s[a:b]+r"""
 assert(!m->vs.area_go&&G.vs_wait_note_until==12);
 setflag(0);H.control_ready=0;m->vs.start=1;
"""+s[a:b]+r"""
 assert(!m->vs.area_go&&G.vs_wait_note_until==12);H.control_ready=1;H.p[1].status=64;m->vs.start=1;
"""+s[a:b]+r"""
 assert(!m->vs.area_go&&G.vs_wait_note_until==12);H.p[1].status=0;m->vs.start=1;
"""+s[a:b]+r"""
 assert(m->vs.area_go);m->vs.area_go=0;setflag(1);
 assert(vs_host_arm_round());memset(m,0,sizeof *m);m->screen=MENU_BGM;m->zones=1;m->vs.day=1;m->vs.n=2;m->vs.day_final=-1;m->vs.day_voted=1;m->vs.other_day[1]=-1;
 G.vs_day_at=10;vs_day(m,l,11);assert(m->vs.day_final==-1&&!H.vote_sealed&&G.vs_day_at==10);
 silence=11;assert(vs_peer_cooldown(l,l,11));silence=NAN;assert(vs_peer_cooldown(l,l,11));silence=0;
 setflag(0);current_valid=0;assert(vs_peer_cooldown(l,l,12));vs_day(m,l,12);assert(m->vs.day_final==-1&&!H.vote_sealed);current_valid=1;assert(!vs_peer_cooldown(l,l,12));net_lobby changed=*l;changed.player[1].status++;assert(vs_peer_cooldown(l,&changed,12));changed=*l;changed.player[1].profile[0]^=1;assert(vs_peer_cooldown(l,&changed,12));net_lobby ordered=*l;ordered.n=3;ordered.player[2]=ordered.player[1];ordered.player[2].id=3;changed=ordered;net_player swap=changed.player[1];changed.player[1]=changed.player[2];changed.player[2]=swap;assert(vs_peer_cooldown(&ordered,&changed,12));vs_day(m,l,12);assert(m->vs.day_final==0&&H.vote_sealed);
 setflag(1);vs_day(m,l,14);assert(!H.started);setflag(0);
 vs_day(m,l,100);assert(!H.started);G.vs_day_at=20;vs_day(m,l,99.999);assert(H.started);
 setflag(1);vs_day(m,l,102.1);assert(H.started && G.vs_day_started==102.1);
 strict.player[1].profile_len=21;assert(!vs_peer_cooldown(l,l,100));strict.player[1].profile_len=42;strict.player[1].profile[25]=9;assert(!vs_peer_cooldown(l,l,100));
 strict.connected=0;assert(vs_peer_cooldown(l,l,100));strict.connected=1;
 H.open=0;memset(&G,0,sizeof G);memset(m,0,sizeof *m);m->screen=MENU_BGM;m->zones=1;m->vs.day=1;m->vs.n=2;m->vs.day_final=-1;m->vs.day_voted=1;m->vs.other_day[1]=-1;setflag(1);
 vs_day(m,l,10);assert(m->vs.day_final==-1 && !remote_starts);setflag(0);vs_day(m,l,11);assert(m->vs.day_final==0);
 setflag(1);vs_day(m,l,13);assert(!remote_starts && !G.vs_day_started);setflag(0);vs_day(m,l,14);assert(remote_starts==1 && G.vs_day_started==14);
 setflag(1);vs_day(m,l,16);assert(remote_starts==2 && G.vs_day_started==16);
 puts("peer cooldown host PASS");return 0;}
"""
with tempfile.TemporaryDirectory(prefix='peer-cooldown-') as tmp:
 p=Path(tmp)/'test.c';p.write_text(pre+take('static int vs_peer_cooldown(')+take('static void vs_day(')+post)
 exe=Path(tmp)/'test';subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=undefined,float-cast-overflow','-fno-sanitize-recover=all','-D__ANDROID__','-I'+str(R/'src'),str(p),str(R/'src/vs_recovery_wire.c'),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
