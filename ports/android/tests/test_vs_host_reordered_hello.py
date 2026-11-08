#!/usr/bin/env python3
"""Real local host functions, fake GameKit transport; not a device test."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[1]
c=r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "vs_host.c"
#include "vs_recovery_wire.h"
static int flags[100], nf, goals;
static double hello_time=1;
int gk_recv(void*b,int n,int*p){(void)b;(void)n;(void)p;return 0;}
int gk_send(int peer,const void*buf,int n){(void)peer;const unsigned char*b=buf;if(n>=4&&b[3]==GO)goals++;if(n>13&&b[3]==LOBBY){int at=13;for(int i=0;i<b[4];i++){int len=b[at+6+NET_NAME];if(i==1&&len>=42){assert(nf<100);flags[nf++]=b[at+7+NET_NAME+25];}at+=7+NET_NAME+len;}}return n;}
static addr endpoint(int peer){addr a={0};a.gk=1;a.peer=peer;return a;}
static void hello(int peer,int id,unsigned seq,int status,int flag,unsigned race,unsigned nonce,int legacy){unsigned char b[100]={0},base[21]={0},p[42];head(b,HELLO);put32(b+4,id);b[8]=status;memcpy(b+9,"peer",4);if(legacy){b[25]=21;memcpy(b+26,base,21);}else{vs_recovery_wire_extension e={flag,race,nonce,seq};assert(vs_recovery_wire_encode(p,sizeof p,base,sizeof base,&e));b[25]=42;memcpy(b+26,p,42);}addr a=endpoint(peer);got(b,legacy?47:68,&a,hello_time,"host");}
static void reset(void){memset(&H,0,sizeof H);H.fd=-1;H.open=H.local_mode=H.control_ready=1;H.owner=11;nf=goals=0;hello(0,11,0,0,0,0,1,1);}
static net_lobby lobby(void){net_lobby l={0};l.connected=1;l.n=H.n;l.me=l.host=0;for(int i=0;i<H.n;i++){l.player[i].id=H.p[i].id;l.player[i].status=H.p[i].status;memcpy(l.player[i].name,H.p[i].name,NET_NAME);l.player[i].profile_len=H.p[i].profile_len;memcpy(l.player[i].profile,H.p[i].profile,H.p[i].profile_len);}return l;}
static int matches(void){net_lobby l=lobby();return vs_host_lobby_matches(&l);}
int main(void){
 reset();hello(1,12,12,64,0,0,2,0);assert(matches());hello(1,12,11,0,0,0,2,0);assert(H.p[1].status==0&&H.p[1].sequence_suspect&&!matches());assert(vs_host_arm_round()&&!vs_host_seal_vote());hello(1,12,12,0,0,0,2,0);assert(!matches());hello(1,12,10,0,0,0,2,0);assert(!matches());hello(1,12,13,0,0,0,2,0);assert(matches()&&vs_host_seal_vote());
 /* Suspect after seal blocks only the initial GO; newer restores it. */
 hello(1,12,12,0,0,0,2,0);assert(!vs_host_local_start(3,13,4,2));hello(1,12,14,0,0,0,2,0);assert(vs_host_local_start(3,13,4,3));int sent=goals;hello(1,12,13,0,0,0,2,0);assert(vs_host_round_pending());assert(vs_host_local_start(3,13,4,5)&&goals==sent+6);vs_host_round_accepted();H.control_ready=1;assert(vs_host_retry_guests(6,H.race_id)==1);
 reset();hello(1,12,0xffffffffu,0,0,0,2,0);hello(1,12,0,0,0,0,2,0);assert(matches()&&H.p[1].sequence_high==0);hello(1,12,0x80000000u,0,0,0,2,0);assert(!matches());hello(1,12,0,0,0,0,2,0);assert(!matches());hello(1,12,1,0,0,0,2,0);assert(matches());
 reset();hello(1,12,0,0,0,0,2,0);hello(1,12,0,0,0,0,2,0);assert(matches());
 reset();hello(1,12,0,0,0,0,0,1);hello(1,12,0,64,0,0,0,1);assert(matches());
 /* Compatibility tradeoff: stale same-session HELLO still refreshes seen. */
 hello_time=1;reset();hello(1,12,12,64,0,0,2,0);hello_time=5;hello(1,12,11,0,0,0,2,0);assert(H.p[1].seen==5 && H.p[1].sequence_suspect);hello_time=1;
 /* Nonlocal servers retain their existing projection and timing behavior. */
 reset();H.local_mode=0;hello(1,12,12,64,0,0,2,0);hello(1,12,11,0,0,0,2,0);assert(H.p[1].status==0 && !H.p[1].sequence_suspect);
 /* A stale ABORT and the subsequent NORMAL are both relayed unchanged. */
 reset();hello(1,12,12,0,0,0,2,0);nf=0;hello(1,12,11,0,1,77,2,0);hello(1,12,13,0,0,0,2,0);assert(nf>=2&&flags[0]==1&&flags[nf-1]==0&&matches());
 /* Identity change retains the existing sealed-round invalidation behavior. */
 reset();hello(1,12,1,0,0,0,2,0);assert(vs_host_arm_round()&&vs_host_seal_vote());hello(1,12,2,0,0,0,3,0);assert(vs_host_vote_invalid());
 reset();hello(1,12,1,0,0,0,2,0);assert(vs_host_arm_round()&&vs_host_seal_vote());hello(2,12,2,0,0,0,2,0);assert(vs_host_vote_invalid());
 puts("host reordered HELLO guard PASS");return 0;}
"""
with tempfile.TemporaryDirectory(prefix="host-reordered-") as d:
 p=Path(d)/"test.c";p.write_text(c);exe=Path(d)/"test";subprocess.run(["cc","-std=gnu11","-Wall","-Wextra","-Werror","-Wno-unused-function","-fsanitize=undefined,float-cast-overflow","-fno-sanitize-recover=all","-I"+str(R/"src"),str(p),str(R/"src/vs_recovery_wire.c"),"-o",str(exe)],check=True);subprocess.run([str(exe)],check=True)
