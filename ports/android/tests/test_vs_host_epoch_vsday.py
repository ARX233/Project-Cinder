#!/usr/bin/env python3
"""Real host/net + extracted production vs_day retry, isolated memory transport.

No sockets are opened: system socket operations are replaced before including
vs_host.c; gk send/recv form in-memory queues. Actual host APIs are not mocked.
Menu type, profile construction, menu status, clock, UI and transport are fake.
The full vs_menu/GO acceptance block and Android runtime are NOT exercised.
Run: python3 tests/test_vs_host_epoch_vsday.py
"""
from pathlib import Path
import subprocess, tempfile
R=Path(__file__).resolve().parents[1]
s=(R/'src/app.c').read_text()
def take(m):
 p=s.index(m);i=s.index('{',p)+1;d=1
 while d:
  d+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[p:i]+'\n'
f=''.join(take(m) for m in ('static int vs_peer_cooldown(', 'static int vs_own_profile_matches(',  'static int vs_own_lobby_ready(', 'static int vs_same_build(', 'static void vs_day('))
host=r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
extern int from_client(void*,int,struct sockaddr_in*);
extern void to_client(const void*,int,int);
static int mock_socket(int domain,int type,int protocol){assert(domain==AF_INET&&type==SOCK_DGRAM&&protocol==0);return 123;}
static int mock_setsockopt(int fd,int level,int opt,const void*v,socklen_t n){(void)v;assert(fd==123&&level==SOL_SOCKET&&opt==SO_REUSEADDR&&n==sizeof(int));return 0;}
static int mock_bind(int fd,const struct sockaddr*a,socklen_t n){(void)a;assert(fd==123&&n==sizeof(struct sockaddr_in));return 0;}
static int mock_fcntl(int fd,int cmd,...){assert(fd==123&&(cmd==F_GETFL||cmd==F_SETFL));return 0;}
static int mock_close(int fd){assert(fd==123);return 0;}
static ssize_t mock_recvfrom(int fd,void*b,size_t n,int flags,struct sockaddr*a,socklen_t*l){assert(fd==123&&!flags&&*l==sizeof(struct sockaddr_in));return from_client(b,(int)n,(struct sockaddr_in*)a);}
static ssize_t mock_sendto(int fd,const void*b,size_t n,int flags,const struct sockaddr*a,socklen_t l){assert(fd==123&&!flags&&l==sizeof(struct sockaddr_in));to_client(b,(int)n,ntohs(((const struct sockaddr_in*)a)->sin_port));return (ssize_t)n;}
#define socket mock_socket
#define setsockopt mock_setsockopt
#define bind mock_bind
#define fcntl mock_fcntl
#define close mock_close
#define recvfrom mock_recvfrom
#define sendto mock_sendto
#include "vs_host.c"
'''
client=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "net.c"
#include "vs_host.h"
#include "vs_recovery_wire.h"
#include <math.h>
#define VS_GONE 10.0
#define VS_PROFILE 21
#define VS_PROFILE_BUILD 19
#define VS_BUILD_NAMESPACE 'W'
#define VS_BUILD_REVISION 168
#define MENU_BGM 1
#define MENU_VS_DAY_FINAL 68
#define MENU_VS_LOADED 70
#define VS_AREA_LATE 5
#define VS_REVEAL 1.6
typedef struct {int screen,zone,zones,song;struct {int day,n,me,host,day_final,day_timer,day_voted,other_day[4],other_zone[4],ramp,km;} vs;} menu_state;
static struct {uint32_t vs_id;double vs_day_at,vs_day_started,vs_day_final_at,vs_wait_note_until;int vs_song;} G;
extern int active;extern void enqueue(const void*,int,int);extern int dequeue(void*,int,int);
int gk_send(int peer,const void*b,int n){(void)peer;enqueue(b,n,active);return 0;}
int gk_recv(void*b,int n,int*peer){*peer=0;return dequeue(b,n,active);}
void car_link_deliver(int p,const unsigned char*b,int n){(void)p;(void)b;(void)n;}
static void vs_profile(unsigned char*p){memset(p,7,21);p[19]='W';p[20]=168;}
static int menu_vs_status(const menu_state*m){return m->vs.day_final>=0 ? 68+m->vs.day_final : 66+m->zone;}
static void vs_off(void){assert(!"unexpected vs_off");}
static void menu_vs_closed(menu_state*m,const char*n){(void)m;(void)n;assert(!"unexpected close");}
'''+f+r'''
static __typeof__(N) saved[2];static menu_state M;static net_go received[2];
static void load(int i){active=i;N=saved[i];}
static void save(int i){saved[i]=N;}
void client_init(int i){active=i;memset(&N,0,sizeof N);N.fd=-1;assert(net_open_gk(11+i)==0);net_use_strict_lobby(1);net_require_valid_go(1);save(i);}
void client_poll(int i,double now){unsigned char p[21];vs_profile(p);load(i);net_poll(now,i==0 ? menu_vs_status(&M) : 66,"player",p,21);save(i);}
void menu_init(void){memset(&M,0,sizeof M);memset(&G,0,sizeof G);G.vs_id=11;M.screen=MENU_BGM;M.zones=2;M.vs.day=1;M.vs.n=2;M.vs.me=M.vs.host=0;M.vs.day_final=-1;M.vs.day_voted=1;M.vs.ramp=1;M.vs.km=13;M.song=4;}
void real_day(double now){load(0);const net_lobby*l=net_lobby_now();
 /* Model vs_menu projection of peer day votes from real parsed lobby. */
 assert(l->connected&&l->n==2&&l->me==0&&l->host==0);
 for(int i=0;i<l->n;i++){int st=l->player[i].status;M.vs.other_day[i]=st>=64&&st<66?0:st>=66&&st<70?1:-1;M.vs.other_zone[i]=(st-64)&1;}
 vs_day(&M,l,now);save(0);}
int day_final(void){return M.vs.day_final;}
int take_go(int i,uint32_t*r,uint32_t*seed){net_go g;load(i);int ok=net_take_go(&g);if(ok){received[i]=g;*r=g.race;*seed=g.seed;}save(i);return ok;}
void check_frozen_owner(void){assert(received[0].n==2&&received[1].n==2&&received[0].pcb==0&&received[1].pcb==1);assert(received[0].player[0].profile_len==21&&received[0].player[1].profile_len==21);assert(vs_host_go_matches(&received[0]));assert(!vs_host_go_matches(&received[1]));}
'''
main=r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <arpa/inet.h>
#include "vs_host.h"
int active;
struct packet {unsigned char data[2048];int n,id;};
static struct packet up[128],down[2][128],first[2];static int un,dn[2],drop_owner,go_count[2],first_set[2];
void enqueue(const void*b,int n,int id){assert(id>=0&&id<2&&n>0&&n<=2048&&un<128);up[un].id=id;up[un].n=n;memcpy(up[un++].data,b,n);}
int from_client(void*b,int n,struct sockaddr_in*a){if(!un){errno=EAGAIN;return -1;}struct packet p=up[0];memmove(up,up+1,--un*sizeof *up);assert(p.n<=n);memcpy(b,p.data,p.n);memset(a,0,sizeof *a);a->sin_family=AF_INET;a->sin_addr.s_addr=htonl(0x7f000001);a->sin_port=htons(41000+p.id);return p.n;}
void to_client(const void*b,int n,int port){int id=port-41000;assert(id>=0&&id<2&&n>0&&n<=2048);const unsigned char*p=b;
 if(n>=16&&p[3]==4){go_count[id]++;if(!first_set[id]){first_set[id]=1;first[id].n=n;memcpy(first[id].data,b,n);}else assert(first[id].n==n&&!memcmp(first[id].data,b,n));if(id==0&&drop_owner)return;}
 assert(dn[id]<128);down[id][dn[id]].n=n;memcpy(down[id][dn[id]++].data,b,n);
}
int dequeue(void*b,int max,int id){if(!dn[id])return 0;struct packet p=down[id][0];memmove(down[id],down[id]+1,--dn[id]*sizeof p);assert(p.n<=max);memcpy(b,p.data,p.n);return p.n;}
void client_init(int);void client_poll(int,double);void menu_init(void);void real_day(double);int day_final(void);int take_go(int,uint32_t*,uint32_t*);void check_frozen_owner(void);
int main(void){uint32_t r1=0,r2=0,s1=0,s2=0;
 assert(vs_host_open(0,11)==0);assert(vs_host_enable_local());assert(!vs_host_control_ready());
 menu_init();client_init(0);client_init(1);client_poll(0,1);client_poll(1,1);vs_host_poll(1,"test");assert(vs_host_control_ready());
 client_poll(0,1.1);client_poll(1,1.1);assert(vs_host_arm_round());assert(!vs_host_round_pending());
 /* Host and parsed normal/strict lobbies agree; production vs_day counts
    both votes and calls the real seal API, never called manually here. */
 real_day(1.1);assert(day_final()==0&&!vs_host_round_pending()&&!vs_host_vote_invalid());
 /* Owner's final vote status changes: deliver it to host and poll the
    resulting lobby back to both clients before the start frame. */
 client_poll(0,1.2);client_poll(1,1.2);vs_host_poll(1.2,"test");assert(vs_host_control_ready());
 client_poll(0,1.3);client_poll(1,1.3);vs_host_poll(1.3,"test");assert(vs_host_control_ready());
 drop_owner=1;real_day(2.699);assert(!vs_host_round_pending()&&go_count[0]==0);
 vs_host_poll(2.701,"test");assert(vs_host_control_ready());real_day(2.701);assert(vs_host_round_pending()&&vs_host_round_race()==1&&go_count[0]==3&&go_count[1]==3);
 client_poll(0,2.701);client_poll(1,2.701);assert(!take_go(0,&r1,&s1));assert(take_go(1,&r1,&s1)&&r1==1);
 vs_host_poll(2.701,"test");assert(vs_host_control_ready());
 vs_host_poll(4.700,"test");assert(vs_host_control_ready());real_day(4.700);assert(go_count[0]==3&&go_count[1]==3);
 drop_owner=0;vs_host_poll(4.702,"test");assert(vs_host_control_ready());real_day(4.702);assert(vs_host_round_pending()&&vs_host_round_race()==1&&go_count[0]==6&&go_count[1]==6);
 client_poll(0,4.702);assert(take_go(0,&r2,&s2)&&r2==r1&&s2==s1);
 check_frozen_owner();assert(!vs_host_round_invalid());vs_host_round_accepted();assert(!vs_host_round_pending());
 vs_host_close();puts("production vs_day + host local epoch retry: PASS (memory I/O, full app GO block untested)");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='host-epoch-build-') as d:
 d=Path(d)
 for name,text in [('host.c',host),('client.c',client),('main.c',main)]: (d/name).write_text(text)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined,float-cast-overflow','-D__ANDROID__','-I'+str(R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(R/'src/vs_recovery_wire.c'),'-o',str(d/'test')],check=True)
 subprocess.run([str(d/'test')],check=True)
