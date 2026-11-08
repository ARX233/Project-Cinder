/* UDP zero datagrams count toward the host's bounded receive budget. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <poll.h>
static ssize_t fake_recvfrom(int,void *,size_t,int,struct sockaddr *,socklen_t *);
#define recvfrom fake_recvfrom
#include "../src/vs_host.c"
#undef recvfrom
static int zeros, packets, reads, err=EAGAIN, gk_result, real_udp;
static ssize_t fake_recvfrom(int fd,void *b,size_t cap,int flags,struct sockaddr *a,socklen_t *al) {
  if(real_udp) return recvfrom(fd,b,cap,flags,a,al);
  ++reads; assert(cap>=26 && *al>=sizeof(struct sockaddr_in));
  if(zeros) { --zeros; return 0; }
  if(packets) {
    --packets; unsigned char *p=b; memset(p,0,26); head(p,HELLO); put32(p+4,9); p[9]='X';
    struct sockaddr_in *in=(struct sockaddr_in *)a; memset(in,0,sizeof *in);
    in->sin_family=AF_INET; in->sin_addr.s_addr=htonl(INADDR_LOOPBACK); in->sin_port=htons(12345);
    *al=sizeof *in; return 26;
  }
  errno=err; return -1;
}
int gk_send(int peer,const void *b,int n) { (void)peer;(void)b;return n; }
int gk_recv(void *b,int max,int *peer) { (void)b;(void)max;(void)peer;return gk_result; }
static int wait_readable(int fd) {
  for (int i=0;i<10;++i) {
    struct pollfd p={fd,POLLIN,0}; int n=poll(&p,1,100);
    if (n>0) return !!(p.revents & POLLIN);
    if (n<0 && errno!=EINTR) return 0;
  }
  return 0;
}
static void reset(int local) { memset(&H,0,sizeof H); H.fd=123; H.open=1; H.local_mode=local; }
int main(void) {
  reset(1); zeros=1; packets=1; reads=0; vs_host_poll(1,"test");
  assert(reads==3 && H.n==1 && H.p[0].id==9 && H.control_ready);
  reset(1); zeros=512; packets=1; reads=0; vs_host_poll(2,"test");
  assert(reads==512 && packets==1 && !H.control_ready && H.n==0);
  vs_host_poll(3,"test"); assert(reads==514 && H.n==1 && H.control_ready);
  err=EINTR; vs_host_poll(4,"test"); assert(!H.control_ready);
  err=EIO; vs_host_poll(4,"test"); assert(!H.control_ready);
  err=EAGAIN; H.gk=1; gk_result=-2; vs_host_poll(4,"test"); assert(!H.control_ready);
  gk_result=0; vs_host_poll(4,"test"); assert(H.control_ready);
  reset(0); zeros=1; packets=1; reads=0; vs_host_poll(5,"test"); assert(H.n==1 && reads==3);
  /* An unconfirmed queue grants exactly two seconds of timeout grace. */
  reset(1); H.n=1; H.p[0].id=9; H.p[0].seen=1;
  zeros=512; vs_host_poll(30,"test"); assert(H.n==1 && H.saturation_state==1);
  zeros=512; vs_host_poll(31.999,"test"); assert(H.n==1 && H.saturation_state==1);
  zeros=512; vs_host_poll(32,"test"); assert(H.n==0 && H.saturation_state==2);
  /* An explicitly empty queue resets the grace timer before the next burst. */
  reset(1); H.n=1; H.p[0].id=9; H.p[0].seen=1;
  zeros=512; vs_host_poll(30,"test"); assert(H.n==1 && H.saturation_state==1);
  zeros=0; vs_host_poll(31,"test"); assert(H.control_ready && H.saturation_state==0);
  H.n=1; H.p[0].id=9; H.p[0].seen=1; /* normal timeout runs on the empty poll */
  zeros=512; vs_host_poll(31.5,"test"); assert(H.n==1 && H.saturation_state==1 && H.saturation_since==31.5);
  zeros=512; vs_host_poll(33.499,"test"); assert(H.n==1 && H.saturation_state==1);
  zeros=512; vs_host_poll(33.5,"test"); assert(H.n==0 && H.saturation_state==2);
  /* Actual loopback: empty datagram followed by a valid HELLO. */
  int r=socket(AF_INET,SOCK_DGRAM,0), s=socket(AF_INET,SOCK_DGRAM,0); assert(r>=0 && s>=0);
  struct sockaddr_in a={0}; a.sin_family=AF_INET; a.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  assert(bind(r,(struct sockaddr *)&a,sizeof a)==0); socklen_t al=sizeof a;
  assert(getsockname(r,(struct sockaddr *)&a,&al)==0);
  assert(fcntl(r,F_SETFL,fcntl(r,F_GETFL,0)|O_NONBLOCK)==0);
  unsigned char hello[26]={0}; head(hello,HELLO); put32(hello+4,9); hello[9]='X';
  assert(sendto(s,"",0,0,(struct sockaddr *)&a,al)==0);
  assert(sendto(s,hello,sizeof hello,0,(struct sockaddr *)&a,al)==sizeof hello);
  real_udp=1; memset(&H,0,sizeof H); H.fd=r; H.open=1; H.local_mode=1;
  for (int i=0;i<2 && !H.n;++i) {
    assert(wait_readable(r)); vs_host_poll(6,"test");
  }
  assert(H.n==1 && H.p[0].id==9 && H.control_ready);
  close(r); close(s); puts("host zero datagram tests passed"); return 0;
}
