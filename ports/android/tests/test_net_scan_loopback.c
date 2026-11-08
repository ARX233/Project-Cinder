/* Real UDP net_scan fixture; all actual transmissions loopback only. */
#include <assert.h>
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
static ssize_t scan_sendto(int,const void *,size_t,int,const struct sockaddr *,socklen_t);
static ssize_t scan_recvfrom(int,void *,size_t,int,struct sockaddr *,socklen_t *);
#define sendto scan_sendto
#define recvfrom scan_recvfrom
#include "../src/net.c"
#undef sendto
#undef recvfrom
static int hostfd, blocked, forwarded, reads, inject_eintr, remaining;
static struct sockaddr_in hostaddr, scanaddr;
static unsigned char offer[9+NET_NAME];
static void wait_ready(int fd);
static void local_send(const void *p,size_t n,const struct sockaddr_in *to) {
  assert(to->sin_addr.s_addr==htonl(INADDR_LOOPBACK));
  assert(sendto(hostfd,p,n,0,(const struct sockaddr *)to,sizeof *to)==(ssize_t)n);
}
static ssize_t scan_sendto(int fd,const void *b,size_t n,int flags,const struct sockaddr *a,socklen_t al) {
  assert(a && al>=sizeof(struct sockaddr_in));
  const struct sockaddr_in *in=(const struct sockaddr_in *)a;
  assert(in->sin_family==AF_INET);
  if(in->sin_addr.s_addr==htonl(INADDR_BROADCAST)) { ++blocked; return (ssize_t)n; }
  assert(in->sin_addr.s_addr==htonl(INADDR_LOOPBACK)); ++forwarded;
  return sendto(fd,b,n,flags,(const struct sockaddr *)&hostaddr,sizeof hostaddr);
}
static ssize_t scan_recvfrom(int fd,void *b,size_t n,int flags,struct sockaddr *a,socklen_t *al) {
  ++reads;
  if(inject_eintr) { inject_eintr=0; errno=EINTR; return -1; }
  ssize_t r=recvfrom(fd,b,n,flags,a,al);
  if(r==0 && remaining>0) {
    if(--remaining) local_send("",0,&scanaddr);
    else local_send(offer,sizeof offer,&scanaddr);
    wait_ready(fd);
  }
  return r;
}
int gk_send(int p,const void *b,int n) {(void)p;(void)b;return n;}
int gk_recv(void *b,int n,int *p) {(void)b;(void)n;(void)p;return 0;}
void car_link_deliver(int p,const unsigned char *b,int n) {(void)p;(void)b;(void)n;}
static void wait_ready(int fd) {
  struct pollfd p={fd,POLLIN,0};
  for (int i=0;i<10;++i) {
    int r=poll(&p,1,100);
    if (r==1) { assert(p.revents&POLLIN); return; }
    assert(r==0 || (r<0 && errno==EINTR));
  }
  assert(!"loopback readiness deadline exceeded");
}
int main(void) {
  hostfd=socket(AF_INET,SOCK_DGRAM,0); assert(hostfd>=0);
  memset(&hostaddr,0,sizeof hostaddr); hostaddr.sin_family=AF_INET;
  hostaddr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  assert(bind(hostfd,(struct sockaddr *)&hostaddr,sizeof hostaddr)==0);
  socklen_t al=sizeof hostaddr; assert(getsockname(hostfd,(struct sockaddr *)&hostaddr,&al)==0);
  head(offer,OFFER); offer[4]=2; memcpy(offer+5,"Fixture",7); put32(offer+5+NET_NAME,42);
  net_scan(1,1); assert(blocked==1 && forwarded==1);
  unsigned char request[64]; al=sizeof scanaddr; wait_ready(hostfd);
  assert(recvfrom(hostfd,request,sizeof request,0,(struct sockaddr *)&scanaddr,&al)==4);
  assert(!memcmp(request,"WV\1\7",4)); assert(scanaddr.sin_addr.s_addr==htonl(INADDR_LOOPBACK));
  remaining=1; local_send("",0,&scanaddr); wait_ready(S.fd);
  reads=0; net_scan(1,1); net_found f[NET_FOUND];
  assert(reads==3 && net_found_list(f,NET_FOUND)==1);
  assert(f[0].id==42 && f[0].n==2 && !strcmp(f[0].name,"Fixture") && !strcmp(f[0].ip,"127.0.0.1") && f[0].seen==1);
  /* Real loopback replenishment avoids receive queue overflow. */
  S.n=0; remaining=512; local_send("",0,&scanaddr); wait_ready(S.fd);
  reads=0; net_scan(1,1); assert(reads==512 && remaining==0 && S.n==0);
  wait_ready(S.fd); reads=0; net_scan(1,1); assert(reads==2 && S.n==1 && S.found[0].id==42);
  /* Inject EINTR; actual queued OFFER must survive to next call. */
  S.n=0; local_send(offer,sizeof offer,&scanaddr); wait_ready(S.fd);
  inject_eintr=1; reads=0; net_scan(1,1); assert(reads==1 && S.n==0);
  wait_ready(S.fd); reads=0; net_scan(1,1); assert(reads==2 && S.n==1 && S.found[0].id==42);
  assert(blocked==1 && forwarded==1); net_scan(0,0); close(hostfd);
  puts("scan loopback: zero/OFFER, 512 budget, EINTR preserved; broadcast suppressed"); return 0;
}
