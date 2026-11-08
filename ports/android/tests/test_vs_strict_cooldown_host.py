"""Real net parser and app cooldown helper; simulated GK receive queue."""
from pathlib import Path
import os,subprocess,tempfile
R=Path(__file__).resolve().parents[1]
s=(R/"src/app.c").read_text();p=s.index("static int vs_peer_cooldown(");i=s.index("{",p)+1;d=1
while d:
 d+=(s[i]=="{")-(s[i]=="}");i+=1
helper=s[p:i]
pre=r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "net.c"
#include "vs_recovery_wire.h"
#define VS_GONE 10.0
static unsigned char queued[1024];static int qlen;
int gk_recv(void*b,int n,int*peer){*peer=0;if(!qlen)return 0;assert(n>=qlen);memcpy(b,queued,qlen);int len=qlen;qlen=0;return len;}
int gk_send(int peer,const void*b,int n){(void)peer;(void)b;return n;}
void car_link_deliver(int p,const unsigned char*b,int n){(void)p;(void)b;(void)n;}
"""
post=r"""
static void setup(int strict){assert(!net_open_gk(11));net_use_strict_lobby(strict);}
/* Slot identity and wire order are independent; mode 1 duplicates a slot. */
static void deliver(int reordered,int abort,int mode,double now){
 unsigned char b[1024]={0},profile[42],base[21]={0};head(b,LOBBY);b[4]=3;b[5]=0;b[6]=0;int at=13;
 for(int i=0;i<3;i++){
  int slot=reordered?(i==0?0:i==1?2:1):i;
  b[at++]=(unsigned char)((mode==1&&i==2)?1:slot);put32(b+at,(unsigned)(11+slot+(mode==2&&slot==0?88:0)));at+=4;b[at++]=0;memset(b+at,'A'+slot,NET_NAME);at+=NET_NAME;
  if(slot==1&&abort){vs_recovery_wire_extension e={VS_RECOVERY_WIRE_ABORT,77,1001,9};assert(vs_recovery_wire_encode(profile,sizeof profile,base,sizeof base,&e));b[at++]=42;memcpy(b+at,profile,42);at+=42;}else{b[at++]=21;memcpy(b+at,base,21);at+=21;}
 }
 memcpy(queued,b,at);qlen=at;net_poll(now,0,"fake",base,21);assert(!qlen);
}
static int wait_now(double t){return vs_peer_cooldown(net_lobby_valid_now(),net_lobby_now(),t);}
int main(void){
 setup(1);deliver(1,0,0,1);assert(net_lobby_now()->player[1].id==12&&net_lobby_valid_now()->player[1].id==12);assert(!wait_now(1));puts("strict reordered legacy: permit");
 deliver(1,1,0,2);assert(wait_now(2));puts("strict reordered ABORT: wait");
 setup(0);deliver(1,0,0,3);assert(net_lobby_now()->player[1].id==13&&net_lobby_valid_now()->player[1].id==12);assert(wait_now(3));puts("raw reordered: wait");
 setup(1);deliver(0,0,0,4);assert(!wait_now(4));unsigned long long before=net_lobby_observations();deliver(0,0,1,5);assert(net_lobby_observations()==before);assert(!net_lobby_current_valid()&&wait_now(5));puts("duplicate slot after valid: wait");deliver(0,0,0,5.1);assert(net_lobby_current_valid()&&!wait_now(5.1));puts("valid lobby restores readiness");head(queued,LOBBY);qlen=4;net_poll(5.2,0,"fake",NULL,0);assert(!net_lobby_current_valid()&&wait_now(5.2));deliver(0,0,0,5.3);assert(net_lobby_current_valid()&&!wait_now(5.3));puts("truncated lobby waits and recovers");head(queued,HELLO);qlen=4;net_poll(5.4,0,"fake",NULL,0);assert(net_lobby_current_valid()&&!wait_now(5.4));puts("non-lobby leaves valid unchanged");
 setup(1);deliver(0,0,0,6);assert(!wait_now(6));before=net_lobby_observations();deliver(0,0,2,7);assert(net_lobby_observations()==before);printf("wrong self after valid: wait=%d\n",wait_now(7));assert(wait_now(7));
 return 0;}
"""
with tempfile.TemporaryDirectory(prefix="strict-lobby-",dir=os.environ.get('TMPDIR')) as tmp:
 c=Path(tmp)/"fixture.c";c.write_text(pre+helper+post);exe=Path(tmp)/"fixture";subprocess.run(["cc","-std=gnu11","-Wall","-Wextra","-Werror","-Wno-unused-function","-fsanitize=undefined,float-cast-overflow","-fno-sanitize-recover=all","-I"+str(R/"src"),str(c),str(R/"src/vs_recovery_wire.c"),"-o",str(exe)],check=True);subprocess.run([str(exe)],check=True)
