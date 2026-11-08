/* Real net.c, fake GameKit datagram queue; no network or recovery-wire dependency. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <poll.h>
static ssize_t fake_recv(int fd, void *b, size_t len, int flags);
static ssize_t fake_recvfrom(int fd,void *b,size_t len,int flags,struct sockaddr *a,socklen_t *al);
#define recv fake_recv
#define recvfrom fake_recvfrom
#include "../src/net.c"
#undef recv
#undef recvfrom
typedef struct { unsigned char b[128]; int len; } packet;
static packet queue[600];
static int qn, qi, gk_error, udp_result, udp_errno, udp_calls, udp_zeros, real_udp;
static ssize_t fake_recv(int fd, void *b, size_t len, int flags) {
  if (real_udp) return recv(fd,b,len,flags);
  ++udp_calls;
  if (udp_zeros > 0) { --udp_zeros; return 0; }
  if (qi < qn) {
    packet *p=&queue[qi++]; assert((size_t)p->len<=len); memcpy(b,p->b,(size_t)p->len); return p->len;
  }
  errno = udp_errno; return udp_result;
}
static int scan_zeros, scan_offer, scan_reads;
static ssize_t fake_recvfrom(int fd,void *b,size_t len,int flags,struct sockaddr *a,socklen_t *al) {
  if (real_udp) return recvfrom(fd,b,len,flags,a,al);
  assert(fd==123 && flags==0 && len>=9+NET_NAME && *al>=sizeof(struct sockaddr_in));
  ++scan_reads;
  if (scan_zeros>0) { --scan_zeros; return 0; }
  if (scan_offer) {
    --scan_offer; unsigned char *p=b; memset(p,0,9+NET_NAME); head(p,OFFER); p[4]=1;
    memcpy(p+5,"test",4); put32(p+5+NET_NAME,42);
    struct sockaddr_in *in=(struct sockaddr_in *)a; memset(in,0,sizeof *in);
    in->sin_family=AF_INET; in->sin_addr.s_addr=htonl(INADDR_LOOPBACK); *al=sizeof *in;
    return 9+NET_NAME;
  }
  errno=EAGAIN; return -1;
}
static net_lobby copies[600];
static double times[600];
static int calls;
int gk_send(int peer, const void *b, int len) { (void)peer; (void)b; return len; }
int gk_recv(void *b, int max, int *peer) {
  if (qi == qn) return gk_error;
  packet *p = &queue[qi++]; assert(p->len <= max); *peer = 0;
  memcpy(b, p->b, (size_t)p->len); return p->len;
}
void car_link_deliver(int pcb, const unsigned char *b, int len) { (void)pcb; (void)b; (void)len; }
static void observe(const net_lobby *l, double now, void *ctx) {
  assert(ctx == &calls && calls < 600); copies[calls] = *l; times[calls++] = now;
}
static packet lobby(unsigned char marker) {
  packet p = {{0}, 0}; head(p.b, LOBBY); p.b[4]=2; p.b[5]=0; p.b[6]=1;
  int at=13;
  /* Deliberately reverse record order to test slot projection. */
  for (int i=1;i>=0;--i) {
    p.b[at++]=(unsigned char)i; put32(p.b+at,(uint32_t)(10+i)); at+=4;
    p.b[at++]=0; memset(p.b+at, 'A'+i, NET_NAME); at+=NET_NAME;
    p.b[at++]=1; p.b[at++]=marker;
  }
  p.len=at; return p;
}
static int wait_readable(int fd) {
  for (int i=0;i<10;++i) {
    struct pollfd p={fd,POLLIN,0}; int n=poll(&p,1,100);
    if (n>0) return !!(p.revents & POLLIN);
    if (n<0 && errno!=EINTR) return 0;
  }
  return 0;
}
static void clearq(void) { qn=qi=0; }
static packet go_packet(uint32_t race) {
  packet p={{0},0}; head(p.b,GO); put32(p.b+4,race);
  p.b[14]=1; p.b[15]=0; int at=16;
  p.b[at++]=0; put32(p.b+at,10); at+=4;
  memset(p.b+at,'A',NET_NAME); at+=NET_NAME; p.b[at++]=0; p.len=at;
  return p;
}
static void test_drained(void) {
  net_go go;
  assert(!net_receive_drained() && !net_go_pending());
  assert(!net_open_gk(10)); assert(!net_receive_drained());
  net_set_lobby_observer(observe,&calls); calls=0; clearq();
  for(int i=0;i<511;++i) queue[qn++]=lobby(0);
  queue[qn++]=go_packet(1); queue[qn++]=lobby(0xa1);
  net_poll(9,0,NULL,NULL,0);
  assert(qi==512 && calls==511 && !net_receive_drained() && net_go_pending());
  assert(copies[510].player[0].profile[0]==0);
  net_race_receive();
  assert(qi==513 && calls==512 && net_receive_drained() && net_go_pending());
  assert(copies[511].player[0].profile[0]==0xa1);
  assert(net_take_go(&go) && go.race==1 && !net_go_pending());
  clearq(); queue[qn++]=go_packet(2); net_poll(10,0,NULL,NULL,0);
  assert(net_go_pending() && net_receive_drained()); net_abandon_race(); assert(!net_go_pending());
  clearq(); calls=0; for(int i=0;i<512;++i) queue[qn++]=lobby(0);
  net_race_receive(); assert(qi==512 && calls==512 && !net_receive_drained());
  net_race_receive(); assert(net_receive_drained());
  gk_error=-2; net_poll(11,0,NULL,NULL,0); assert(!net_receive_drained());
  gk_error=0; net_poll(11,0,NULL,NULL,0); assert(net_receive_drained());
  clearq(); queue[qn++]=go_packet(3); net_poll(12,0,NULL,NULL,0); assert(net_go_pending());
  net_close(); assert(!net_receive_drained() && !net_go_pending());
  assert(!net_open_gk(10)); assert(!net_receive_drained() && !net_go_pending()); net_close();
  /* Fake UDP descriptor: do not close or send on it. */
  N.fd=123; N.gk=0; N.id=10; udp_result=-1; udp_errno=EAGAIN;
  net_race_receive(); assert(net_receive_drained() && udp_calls==1);
  udp_errno=EWOULDBLOCK; net_race_receive(); assert(net_receive_drained());
  udp_errno=EINTR; net_race_receive(); assert(!net_receive_drained());
  udp_errno=EIO; net_race_receive(); assert(!net_receive_drained());
  udp_result=-1; udp_errno=EAGAIN; udp_zeros=1; udp_calls=0;
  clearq(); queue[qn++]=lobby(0xa1); net_set_lobby_observer(observe,&calls); calls=0;
  net_race_receive(); assert(udp_calls==3 && qi==1 && calls==1 && net_receive_drained());
  udp_zeros=512; udp_calls=0;
  clearq(); queue[qn++]=lobby(0xa1); calls=0;
  net_race_receive(); assert(udp_calls==512 && qi==0 && !net_receive_drained());
  net_race_receive(); assert(udp_calls==514 && qi==1 && calls==1 && net_receive_drained());
  N.fd=-1; net_close(); assert(!net_receive_drained());
  /* Actual loopback datagrams: zero, then a valid lobby, then EAGAIN. */
  int r=socket(AF_INET,SOCK_DGRAM,0), s=socket(AF_INET,SOCK_DGRAM,0); assert(r>=0 && s>=0);
  struct sockaddr_in a={0}; a.sin_family=AF_INET; a.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  assert(bind(r,(struct sockaddr *)&a,sizeof a)==0); socklen_t al=sizeof a;
  assert(getsockname(r,(struct sockaddr *)&a,&al)==0);
  assert(fcntl(r,F_SETFL,fcntl(r,F_GETFL,0)|O_NONBLOCK)==0);
  packet actual=lobby(0xa1);
  assert(sendto(s,"",0,0,(struct sockaddr *)&a,al)==0);
  assert(sendto(s,actual.b,(size_t)actual.len,0,(struct sockaddr *)&a,al)==actual.len);
  real_udp=1; N.fd=r; N.id=10; calls=0; net_set_lobby_observer(observe,&calls);
  for (int i=0;i<2 && !calls;++i) {
    assert(wait_readable(r)); net_race_receive();
  }
  assert(calls==1 && copies[0].player[0].profile[0]==0xa1 && net_receive_drained());
  net_close(); close(s); real_udp=0;
}
static packet legacy_lobby(void) {
  packet p={{0},0}; head(p.b,LOBBY); p.b[4]=2; p.b[5]=0; p.b[6]=1; int at=13;
  for (int i=1;i>=0;--i) {
    p.b[at++]=(unsigned char)i; put32(p.b+at,(uint32_t)(10+i)); at+=4;
    p.b[at++]=0; memset(p.b+at,'A'+i,NET_NAME); at+=NET_NAME;
    p.b[at++]=21; memset(p.b+at,0x30+i,21); at+=21;
  }
  p.len=at; return p;
}
static void test_strict_projection(void) {
  assert(!net_open_gk(10)); assert(!net_lobby_current_valid()); clearq(); queue[qn++]=lobby(1);
  net_poll(20,0,NULL,NULL,0);
  assert(net_lobby_now()->player[0].id==11 && net_lobby_now()->player[1].id==10 && !net_lobby_current_valid());
  net_use_strict_lobby(1); assert(net_lobby_now()->player[0].id==11 && !net_lobby_current_valid());
  clearq(); queue[qn++]=legacy_lobby(); net_poll(21,0,NULL,NULL,0);
  assert(net_lobby_now()->player[0].id==10 && net_lobby_now()->player[1].id==11);
  assert(net_lobby_now()->player[0].profile_len==21 && net_lobby_now()->player[0].profile[20]==0x30);
  packet p=lobby(2); p.b[37]=1; clearq(); queue[qn++]=p; net_poll(22,0,NULL,NULL,0);
  assert(net_lobby_now()->player[0].id==11 && net_lobby_now()->player[1].id==10);
  p=lobby(2); put32(p.b+38,12); clearq(); queue[qn++]=p; net_poll(23,0,NULL,NULL,0);
  assert(net_lobby_now()->player[0].id==11 && net_lobby_now()->player[1].id==12);
  p=lobby(3); unsigned char tmp[24]; memcpy(tmp,p.b+13,24); memcpy(p.b+13,p.b+37,24); memcpy(p.b+37,tmp,24);
  clearq(); queue[qn++]=p; net_poll(24,0,NULL,NULL,0);
  assert(net_lobby_now()->player[0].id==10 && net_lobby_now()->player[1].id==11 && net_lobby_current_valid());
  net_use_strict_lobby(1); assert(net_lobby_current_valid());
  net_lobby prev=*net_lobby_now(); p.b[37]=0; clearq(); queue[qn++]=p; net_poll(24.1,0,NULL,NULL,0);
  assert(!net_lobby_current_valid() && !memcmp(&prev,net_lobby_now(),sizeof prev));
  p.len=4; clearq(); queue[qn++]=p; net_poll(24.2,0,NULL,NULL,0); assert(!net_lobby_current_valid());
  clearq(); queue[qn++]=lobby(3); net_poll(24.3,0,NULL,NULL,0); assert(net_lobby_current_valid());
  p=lobby(3); --p.len; clearq(); queue[qn++]=p; net_poll(24.4,0,NULL,NULL,0); assert(!net_lobby_current_valid());
  clearq(); queue[qn++]=p; queue[qn++]=lobby(3); net_poll(24.5,0,NULL,NULL,0); assert(net_lobby_current_valid());
  clearq(); queue[qn++]=lobby(3); queue[qn++]=p; net_poll(24.6,0,NULL,NULL,0); assert(!net_lobby_current_valid());
  clearq(); queue[qn++]=lobby(3); net_poll(24.7,0,NULL,NULL,0); assert(net_lobby_current_valid());
  p=go_packet(17); clearq(); queue[qn++]=p; net_poll(24.8,0,NULL,NULL,0); assert(net_lobby_current_valid());
  N.lobby_observations=UINT64_MAX; net_lobby saved=N.valid_lobby_snapshot; double oldtime=N.valid_lobby_time;
  calls=0; net_set_lobby_observer(observe,&calls); clearq(); queue[qn++]=lobby(4); net_poll(25,0,NULL,NULL,0);
  assert(calls==1 && copies[0].player[0].id==10 && net_lobby_now()->player[0].profile[0]==4 && net_lobby_current_valid());
  assert(!memcmp(&saved,&N.valid_lobby_snapshot,sizeof saved) && oldtime==N.valid_lobby_time);
  net_set_lobby_observer(NULL,NULL); clearq(); queue[qn++]=lobby(5); net_poll(26,0,NULL,NULL,0);
  assert(net_lobby_now()->player[0].id==10 && net_lobby_now()->player[0].profile[0]==5 && net_lobby_current_valid());
  assert(!memcmp(&saved,&N.valid_lobby_snapshot,sizeof saved) && oldtime==N.valid_lobby_time);
  net_use_strict_lobby(0); assert(net_lobby_now()->player[0].id==10 && !net_lobby_current_valid());
  clearq(); queue[qn++]=lobby(6); net_poll(27,0,NULL,NULL,0); assert(net_lobby_now()->player[0].id==11 && !net_lobby_current_valid());
  net_use_strict_lobby(1); assert(!net_lobby_current_valid());
  clearq(); queue[qn++]=lobby(6); net_poll(27.5,0,NULL,NULL,0); assert(net_lobby_current_valid());
  net_close(); assert(!N.use_strict_lobby && !net_lobby_current_valid());
  net_use_strict_lobby(1); net_close(); assert(!N.use_strict_lobby);
  net_use_strict_lobby(1); assert(!net_open_gk(10)); assert(!N.use_strict_lobby);
  clearq(); queue[qn++]=lobby(7); net_poll(28,0,NULL,NULL,0); assert(net_lobby_now()->player[0].id==11);
  net_close();
}
static void test_scan_zero(void) {
  memset(&S,0,sizeof S); S.fd=123; S.last=5;
  scan_zeros=1; scan_offer=1; scan_reads=0; net_scan(5,1);
  assert(scan_reads==3 && S.n==1 && S.found[0].id==42);
  memset(&S,0,sizeof S); S.fd=123; S.last=6;
  scan_zeros=512; scan_offer=1; scan_reads=0; net_scan(6,1);
  assert(scan_reads==512 && scan_offer==1 && S.n==0);
  net_scan(6,1); assert(scan_reads==514 && S.n==1 && S.found[0].id==42);
  S.fd=-1;
}
int main(void) {
  net_set_lobby_observer(observe, &calls); net_close(); assert(!N.lobby_observer);
  net_set_lobby_observer(observe, &calls); assert(!net_open_gk(10)); assert(!N.lobby_observer);
  queue[qn++]=lobby(1); net_poll(1,0,NULL,NULL,0); assert(calls==0 && net_lobby_observations()==1);
  net_set_lobby_observer(observe, &calls); clearq();
  /* ABORT/NORMAL are payload markers, preserving the order in a single drain. */
  queue[qn++]=lobby(0xa1); queue[qn++]=lobby(0x00);
  net_poll(2,0,NULL,NULL,0); assert(calls==2 && times[0]==2 && times[1]==2);
  assert(copies[0].player[0].id==10 && copies[0].player[1].id==11);
  assert(copies[0].player[0].profile[0]==0xa1 && copies[1].player[0].profile[0]==0);
  clearq(); packet p=lobby(3); p.b[37]=1; queue[qn++]=p; /* duplicate slot */
  p=lobby(3); put32(p.b+38,11); queue[qn++]=p; /* duplicate id */
  p=lobby(3); put32(p.b+38,12); queue[qn++]=p; /* wrong self */
  p=lobby(3); --p.len; queue[qn++]=p; /* truncated */
  net_poll(3,0,NULL,NULL,0); assert(calls==2);
  clearq(); N.lobby_observations=UINT64_MAX; net_lobby saved=N.valid_lobby_snapshot;
  double saved_time=N.valid_lobby_time; queue[qn++]=lobby(4); queue[qn++]=lobby(5);
  net_race_receive(); assert(calls==4 && times[2]==3 && times[3]==3);
  assert(copies[2].player[0].profile[0]==4 && copies[3].player[0].profile[0]==5);
  assert(net_lobby_observations()==UINT64_MAX && !memcmp(&saved,&N.valid_lobby_snapshot,sizeof saved));
  assert(saved_time==N.valid_lobby_time);
  clearq(); calls=0; for(int i=0;i<513;++i) queue[qn++]=lobby((unsigned char)i);
  net_poll(4,0,NULL,NULL,0); assert(qi==512 && calls==512);
  net_race_receive(); assert(qi==513 && calls==513 && times[512]==4);
  assert(copies[0].player[0].profile[0]==0 && copies[511].player[0].profile[0]==255 && copies[512].player[0].profile[0]==0);
  net_set_lobby_observer(NULL, &calls); assert(!N.lobby_observer_ctx);
  clearq(); queue[qn++]=lobby(7); net_poll(5,0,NULL,NULL,0); assert(calls==513);
  net_set_lobby_observer(observe,&calls); net_close(); assert(!N.lobby_observer && !N.lobby_observer_ctx);
  assert(!net_open_gk(10)); clearq(); queue[qn++]=lobby(8); net_poll(6,0,NULL,NULL,0); assert(calls==513);
  net_close(); test_drained(); test_scan_zero(); test_strict_projection(); puts("strict lobby observer and receive drain tests passed"); return 0;
}
