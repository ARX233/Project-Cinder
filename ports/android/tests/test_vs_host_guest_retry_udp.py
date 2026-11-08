#!/usr/bin/env python3
"""Real loopback UDP GO retry; app orchestration modeled, not full vs_day."""
from pathlib import Path
import subprocess, tempfile
R = Path(__file__).resolve().parents[1]
host = r"""
#include <assert.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
static int port, dropping=1, counts[4], dropped[4];
static int bind0(int fd,const struct sockaddr *a,socklen_t n) {
 (void)a; assert(n==sizeof(struct sockaddr_in)); struct sockaddr_in x={0};
 x.sin_family=AF_INET; x.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
 int r=bind(fd,(const struct sockaddr*)&x,sizeof x);
 if(!r){socklen_t l=sizeof x;assert(getsockname(fd,(struct sockaddr*)&x,&l)==0);port=ntohs(x.sin_port);assert(port);}
 return r;
}
static ssize_t send_drop(int fd,const void *v,size_t n,int f,const struct sockaddr *a,socklen_t l){
 const unsigned char *b=v;
 if(n>=16&&b[0]=='W'&&b[1]=='V'&&b[3]==4){int k=b[15];assert(k>=0&&k<4);counts[k]++;if(dropping&&k>0){dropped[k]++;return (ssize_t)n;}}
 return sendto(fd,v,n,f,a,l);
}
#define bind bind0
#define sendto send_drop
#include "vs_host.c"
#undef bind
#undef sendto
int host_port(void){return port;} void allow_go(void){dropping=0;}
int go_count(int k){return counts[k];} int drop_count(int k){return dropped[k];}
int host_players(void){return H.n;}
int host_guest_ready(void){return H.retry_ready[1];}
unsigned host_guest_seq(int i){return H.retry_seq[i];}
int host_retry_waiting(int i){return H.retry_eligible[i]&&!H.retry_ready[i];}
void reset_counts(void){memset(counts,0,sizeof counts);memset(dropped,0,sizeof dropped);dropping=1;}
"""
client = r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "net.c"
#include "vs_recovery_wire.h"
static __typeof__(N) clients[3];
static int legacy_last=1;
void all_rfr(void){legacy_last=0;}
static void load(int i){assert(i>=0&&i<3);N=clients[i];}
static void save(int i){clients[i]=N;}
void client_open(int i,int port){memset(&N,0,sizeof N);N.fd=-1;assert(net_open("127.0.0.1",port,(uint32_t)(11+i))==0);net_require_valid_go(1);save(i);}
void client_poll(int i,double t,int ready,uint32_t race){
 unsigned char base[21]={0},p[47];int len=21;base[19]='W';base[20]=168;
 if(i!=2||!legacy_last){vs_recovery_wire_extension e={0,race,(uint64_t)(100+i),(uint32_t)(ready?2:1)};
 assert(vs_recovery_wire_encode(p,sizeof p,base,sizeof base,&e));assert(vs_recovery_wire_put_ready(p,sizeof p,ready));len=47;}
 else memcpy(p,base,21);
 load(i);net_poll(t,ready?1:66,"player",p,len);save(i);
}
void client_signal(int i,double t,uint32_t race,unsigned flags,unsigned seq){
 unsigned char base[21]={0},p[47];base[19]='W';base[20]=168;
 vs_recovery_wire_extension e={(uint8_t)flags,race,(uint64_t)(100+i),seq};
 assert(vs_recovery_wire_encode(p,sizeof p,base,sizeof base,&e));assert(vs_recovery_wire_put_ready(p,sizeof p,0));
 load(i);net_poll(t,1,"player",p,47);save(i);
}
int client_lobby_normal(int i,int member,unsigned seq){
 load(i);const net_lobby *l=net_lobby_now();vs_recovery_wire_extension e;
 int ok=l->connected&&l->n==3&&vs_recovery_wire_decode(&e,l->player[member].profile,(size_t)l->player[member].profile_len)&&e.flags==0&&e.seq==seq;
 save(i);return ok;
}
int client_take(int i,net_go *g){load(i);int r=net_take_go(g);save(i);return r;}
void client_close(int i){load(i);net_close();save(i);}
"""
main = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include "net.h"
#include "vs_host.h"
#include "vs_recovery.h"
int host_port(void);void allow_go(void);int go_count(int);int drop_count(int);int host_players(void);int host_guest_ready(void);
void client_open(int,int);void client_poll(int,double,int,uint32_t);int client_take(int,net_go*);void client_close(int);
void reset_counts(void);void all_rfr(void);unsigned host_guest_seq(int);int host_retry_waiting(int);
void client_signal(int,double,uint32_t,unsigned,unsigned);int client_lobby_normal(int,int,unsigned);
int gk_send(int p,const void*b,int n){(void)p;(void)b;(void)n;assert(0);return -1;}
int gk_recv(void*b,int n,int*p){(void)b;(void)n;(void)p;assert(0);return 0;}
void car_link_deliver(int p,const unsigned char*b,int n){(void)p;(void)b;(void)n;}
int main(void){
 assert(vs_host_open(0,11)==0);assert(vs_host_enable_local());int port=host_port();assert(port>0);
 for(int i=0;i<3;i++)client_open(i,port);
 for(int i=0;i<3;i++)client_poll(i,1,0,0);
 for(int j=0;j<200&&host_players()<3;j++){vs_host_poll(1,"host");usleep(1000);}
 assert(host_players()==3&&vs_host_control_ready());
 for(int i=0;i<3;i++)client_poll(i,1.1,0,0);
 assert(vs_host_arm_round());assert(vs_host_seal_vote());assert(vs_host_local_start(1,13,4,1.2));
 assert(go_count(0)==3&&go_count(1)==3&&go_count(2)==3);
 assert(drop_count(0)==0&&drop_count(1)==3&&drop_count(2)==3);
 net_go owner,guest,tmp;client_poll(0,1.2,0,0);client_poll(1,1.2,0,0);client_poll(2,1.2,0,0);
 int owner_got=0;for(int j=0;j<200&&!owner_got;j++){client_poll(0,1.2,0,0);owner_got=client_take(0,&owner);if(!owner_got)usleep(1000);}
 assert(owner_got);assert(vs_host_go_matches(&owner));assert(!client_take(1,&tmp));assert(!client_take(2,&tmp));
 vs_host_round_accepted();assert(!vs_host_round_pending());allow_go();
 vs_host_poll(3.19,"host");assert(vs_host_control_ready());assert(vs_host_retry_guests(3.19,owner.race)==0);
 vs_host_poll(3.21,"host");assert(vs_host_control_ready());assert(vs_host_retry_guests(3.21,owner.race)==1);
 assert(go_count(0)==3&&go_count(1)==6&&go_count(2)==3);
 int got=0;for(int j=0;j<200&&!got;j++){client_poll(1,3.21,0,0);got=client_take(1,&guest);if(!got)usleep(1000);}
 assert(got&&guest.pcb==1&&guest.race==owner.race&&guest.seed==owner.seed);
 client_poll(2,3.21,0,0);assert(!client_take(2,&tmp));
 client_poll(1,3.8,1,owner.race);
 for(int j=0;j<200&&!host_guest_ready();j++){vs_host_poll(3.8,"host");usleep(1000);}
 assert(host_guest_ready()&&vs_host_control_ready());
 vs_host_poll(5.22,"host");assert(vs_host_control_ready());assert(vs_host_retry_guests(5.22,owner.race)==0);
 assert(go_count(0)==3&&go_count(1)==6&&go_count(2)==3);
 for(int i=0;i<3;i++){client_close(i);}vs_host_close();
 /* Independent room: both guests support RFR, neither advertises ready. */
 reset_counts();all_rfr();assert(vs_host_open(0,11)==0);assert(vs_host_enable_local());port=host_port();
 for(int i=0;i<3;i++){client_open(i,port);client_poll(i,10,0,0);}
 for(int j=0;j<200&&host_players()<3;j++){vs_host_poll(10,"host");usleep(1000);}
 assert(host_players()==3&&vs_host_control_ready());
 for(int i=0;i<3;i++)client_poll(i,10.1,0,0);
 assert(vs_host_arm_round());assert(vs_host_seal_vote());assert(vs_host_local_start(1,13,4,10.2));
 owner_got=0;for(int j=0;j<200&&!owner_got;j++){client_poll(0,10.2,0,0);owner_got=client_take(0,&owner);if(!owner_got)usleep(1000);}
 assert(owner_got&&vs_host_go_matches(&owner));vs_host_round_accepted();allow_go();
 assert(go_count(1)==3&&go_count(2)==3&&host_retry_waiting(1)&&host_retry_waiting(2));
 /* Two ordered UDP HELLOs from same endpoint, no intervening host poll. */
 client_signal(1,11.0,owner.race,1,2);
 client_signal(1,11.6,owner.race,0,3);
 for(int j=0;j<200&&host_guest_seq(1)!=3;j++){vs_host_poll(11.6,"host");usleep(1000);}
 assert(host_guest_seq(1)==3&&vs_host_control_ready());
 assert(vs_host_loading_abort(owner.race));
 /* The parsed lobby has the later NORMAL even while host abort remains sticky. */
 for(int j=0;j<200&&!client_lobby_normal(0,1,3);j++){client_poll(0,11.6,0,0);usleep(1000);}
 assert(client_lobby_normal(0,1,3));assert(vs_host_loading_abort(owner.race));
 vs_host_poll(12.3,"host");assert(vs_host_control_ready());
 assert(vs_host_retry_guests(12.3,owner.race)==0);assert(go_count(1)==3&&go_count(2)==3);
 for(int i=0;i<3;i++){client_close(i);}vs_host_close();
 vs_recovery state;vs_recovery_reset(&state);assert(!state.initialized);
 puts("loopback UDP guest retry: PASS (app acceptance modeled)");return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='vs-guest-udp-') as t:
 d=Path(t)
 for name,code in [('host.c',host),('client.c',client),('main.c',main)]: (d/name).write_text(code)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined,float-cast-overflow','-D__ANDROID__','-I'+str(R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(R/'src/vs_recovery_wire.c'),str(R/'src/vs_recovery.c'),'-o',str(d/'test')],check=True,timeout=30)
 subprocess.run([str(d/'test')],check=True,timeout=10)
