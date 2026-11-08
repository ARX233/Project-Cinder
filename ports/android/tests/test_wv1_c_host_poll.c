/* No real network. cc -std=c11 -Wall -Wextra -Werror -fsanitize=undefined ports/android/tests/test_wv1_c_host_poll.c -o /tmp/test_wv1_c_host_poll && /tmp/test_wv1_c_host_poll */
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <fcntl.h>
#include <unistd.h>
static int fake_socket(int,int,int), fake_setsockopt(int,int,int,const void *,socklen_t), fake_bind(int,const struct sockaddr *,socklen_t), fake_close(int), fake_fcntl(int,int,...);
static ssize_t fake_recvfrom(int,void *,size_t,int,struct sockaddr *,socklen_t *), fake_sendto(int,const void *,size_t,int,const struct sockaddr *,socklen_t);
#define socket fake_socket
#define setsockopt fake_setsockopt
#define bind fake_bind
#define close fake_close
#define fcntl fake_fcntl
#define recvfrom fake_recvfrom
#define sendto fake_sendto
#include "../src/vs_host.c"
#undef socket
#undef setsockopt
#undef bind
#undef close
#undef fcntl
#undef recvfrom
#undef sendto
typedef struct { unsigned char b[64]; int len, peer; } input;
static input udp[1024], gkq[1024];
static int un,ui,gn,gi,udp_forever,gk_forever,ucalls,gcalls;
static int sent_udp[10],sent_gk[10],closed,fail_get,fail_set,get_calls,set_calls;
static int fake_socket(int a,int b,int c) { (void)a;(void)b;(void)c;return 123; }
static int fake_setsockopt(int f,int l,int o,const void *v,socklen_t n) { (void)f;(void)l;(void)o;(void)v;(void)n;return 0; }
static int fake_bind(int f,const struct sockaddr *a,socklen_t n) { (void)f;(void)a;(void)n;return 0; }
static int fake_close(int f) { assert(f==123);++closed;return 0; }
static int fake_fcntl(int f,int cmd,...) {
  assert(f==123);
  if(cmd==F_GETFL) { ++get_calls;return fail_get ? -1 : 0; }
  assert(cmd==F_SETFL);++set_calls;
  va_list ap;va_start(ap,cmd);int flags=va_arg(ap,int);va_end(ap);
  assert(flags & O_NONBLOCK);return fail_set ? -1 : 0;
}
static ssize_t fake_recvfrom(int f,void *b,size_t max,int flags,struct sockaddr *a,socklen_t *al) {
  assert(f==123 && flags==0);++ucalls;
  input bad={{0},1,1};input *p=ui<un ? &udp[ui++] : udp_forever ? &bad : NULL;
  if(!p) return -1;
  assert((size_t)p->len<=max && *al>=sizeof(struct sockaddr_in));
  struct sockaddr_in *in=(struct sockaddr_in *)a;memset(in,0,sizeof *in);
  in->sin_family=AF_INET;in->sin_addr.s_addr=htonl(0x7f000001);in->sin_port=htons((unsigned short)(40000+p->peer));
  *al=sizeof *in;memcpy(b,p->b,(size_t)p->len);return p->len;
}
int gk_recv(void *b,int max,int *peer) {
  ++gcalls;input bad={{0},1,1};input *p=gi<gn ? &gkq[gi++] : gk_forever ? &bad : NULL;
  if(!p) return 0;
  assert(p->len<=max);*peer=p->peer;memcpy(b,p->b,(size_t)p->len);return p->len;
}
static ssize_t fake_sendto(int f,const void *b,size_t n,int flags,const struct sockaddr *a,socklen_t al) {
  (void)a;(void)al;assert(f==123 && flags==0 && n>=4);const unsigned char *p=b;
  assert(p[0]=='W' && p[1]=='V' && p[2]==1 && p[3]<10);++sent_udp[p[3]];return (ssize_t)n;
}
int gk_send(int peer,const void *b,int n) { const unsigned char *p=b;assert(peer==2 && n>=4 && p[3]<10);++sent_gk[p[3]];return n; }
static input hello(int peer,uint32_t id) { input p={{0},26,peer};head(p.b,HELLO);put32(p.b+4,id);p.b[9]='A';return p; }
static void clear_queues(void) { un=ui=gn=gi=udp_forever=gk_forever=ucalls=gcalls=0; }
int main(void) {
  fail_get=1;assert(vs_host_open(1,1)==-1);assert(closed==1 && get_calls==1 && set_calls==0 && !H.open);
  fail_get=0;fail_set=1;assert(vs_host_open(1,1)==-1);assert(closed==2 && get_calls==2 && set_calls==1 && !H.open);
  fail_set=0;assert(vs_host_open(1,1)==0);assert(H.open && get_calls==3 && set_calls==2);
  udp_forever=gk_forever=1;H.n=1;H.p[0].id=7;H.p[0].seen=1;
  vs_host_poll(8,"test");assert(ucalls==512 && gcalls==512 && H.n==0);
  clear_queues();
  for(int i=0;i<512;++i) { udp[un++]=(input){{0},1,1};gkq[gn++]=(input){{0},1,2}; }
  udp[un++]=hello(1,1);gkq[gn++]=hello(2,2);
  vs_host_poll(9,"test");assert(ui==512 && gi==512 && H.n==0);
  vs_host_poll(10,"test");assert(ui==513 && gi==513 && H.n==2 && H.p[0].id==1 && H.p[1].id==2);
  clear_queues();memset(sent_udp,0,sizeof sent_udp);memset(sent_gk,0,sizeof sent_gk);
  udp[un++]=(input){{'W','V',1,START,2,17,7},7,1};
  vs_host_poll(11,"test");assert(H.race_id==1 && sent_udp[GO]==3 && sent_gk[GO]==3);
  clear_queues();gkq[gn++]=(input){{'W','V',1,RACE,1,0,0,0,0x80},9,2};
  vs_host_poll(12,"test");assert(sent_udp[RACE]==1 && sent_gk[RACE]==0);
  clear_queues();vs_host_poll(31,"test");assert(H.n==1 && H.p[0].id==2);
  vs_host_poll(33,"test");assert(H.n==0);
  vs_host_close();assert(closed==3);puts("WV1 host poll bounds and fcntl failures: PASS (no network)");return 0;
}
