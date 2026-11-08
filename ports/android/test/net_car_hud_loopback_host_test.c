/* Partial integration: actual upstream net.c socket and Android car.c delivery;
 * actual hud.c hud_finish_result gets a TEST-CONSTRUCTED car_race snapshot,
 * not physics output. Build from repository root (macOS):
 * clang -U__APPLE__ -DGL_ONE_MINUS_DST_COLOR=0x0307 -DGL_ZERO=0 -std=gnu11 \
 * -ffunction-sections -fdata-sections -Iports/android/src -Iports/android/test \
 * -I<generated-header-directory> ports/android/test/net_car_hud_loopback_host_test.c \
 * src/net.c ports/android/src/hud.c -Wl,-dead_strip -lm -lz \
 * -o /Volumes/CodexWork/net_car_hud_loopback_host_test
 * Generated racing_lamp_data.h and other asset headers are build prerequisites.
 */
#include <time.h>
static double fake_now;
static int fake_clock(clockid_t id, struct timespec *t) {
  (void)id; t->tv_sec=(time_t)fake_now;
  t->tv_nsec=(long)((fake_now-(double)t->tv_sec)*1000000000.0); return 0;
}
#define clock_gettime fake_clock
#include "../src/car.c"
#undef clock_gettime
#include "../src/net.h"
#include "../src/hud.h"
#include <arpa/inet.h>
#include <assert.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <unistd.h>
uint8_t *rc_mem;
uint32_t rc_link_rx;
uint8_t *rc_va_slow(uint32_t a) { (void)a; abort(); }
int gk_send(int p,const void *b,int n) { (void)p;(void)b;(void)n;return -1; }
int gk_recv(void *b,int n,int *p) { (void)b;(void)n;(void)p;return 0; }
static void put32(unsigned char *p,uint32_t x) { for(int i=0;i<4;i++) p[i]=(unsigned char)(x>>(8*i)); }
static void send_packet(int fd,const struct sockaddr_in *client,const unsigned char *p,size_t n) {
  assert(sendto(fd,p,n,0,(const struct sockaddr *)client,sizeof *client)==(ssize_t)n);
  struct timeval tv={0,10000}; select(0,NULL,NULL,NULL,&tv);
}
int main(void) {
  int fd=socket(AF_INET,SOCK_DGRAM,0); assert(fd>=0);
  struct sockaddr_in server={0},client={0}; socklen_t n=sizeof server;
  server.sin_family=AF_INET; server.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  assert(bind(fd,(struct sockaddr *)&server,sizeof server)==0);
  assert(getsockname(fd,(struct sockaddr *)&server,&n)==0);
  assert(net_open("127.0.0.1",ntohs(server.sin_port),111)==0);
  net_poll(100,0,"test",NULL,0);
  unsigned char in[256]; n=sizeof client;
  assert(recvfrom(fd,in,sizeof in,0,(struct sockaddr *)&client,&n)>0);
  unsigned char go[16]={'W','V',1,4}; put32(go+4,77);
  send_packet(fd,&client,go,sizeof go); net_poll(100.01,0,"test",NULL,0);
  net_go g; assert(net_take_go(&g) && g.race==77);
  rc_mem=calloc(1,0x4000); assert(rc_mem); rc_link_rx=RC_MEM_BASE;
  P.ready=1; P.vs_race=1; P.vs_pcb=0; P.vs[0].pcb=1;
  unsigned char race[9+CAR_LINK_PACKET]={'W','V',1,5}; put32(race+4,77); race[8]=1;
  put32(race+9+0x34,1); fake_now=100;
  send_packet(fd,&client,race,sizeof race); net_race_receive();
  assert(P.vs_received[1]==100 && !memcmp(VA(rc_link_rx+LINK_BUF),race+9,CAR_LINK_PACKET));
  /* Constructed snapshot: does not claim physics consumed the packet. */
  car_race r={0}; r.play_state=2; r.remain_valid=1; r.remain=600;
  r.vs_fresh[0]=car_link_time_fresh(fake_now,P.vs_received[1]); r.vs_gap[0]=0;
  int trailing=-1; assert(hud_finish_result(&r,0,1,0,0,1,NULL,&trailing)==600 && !trailing);
  r.remain=600.01f; assert(hud_finish_result(&r,0,1,0,0,1,NULL,&trailing)==-1);
  fake_now=100.75; send_packet(fd,&client,race,sizeof race); net_race_receive();
  assert(P.vs_received[1]==100);
  fake_now=101.01; assert(!car_link_observation_fresh(1,100));
  r.remain=600; r.vs_fresh[0]=car_link_time_fresh(fake_now,P.vs_received[1]);
  assert(hud_finish_result(&r,0,1,0,0,1,NULL,&trailing)==-1);
  put32(race+9+0x34,2); send_packet(fd,&client,race,sizeof race); net_race_receive();
  assert(P.vs_received[1]>101 && car_link_observation_fresh(1,P.vs_received[1]));
  r.vs_fresh[0]=car_link_time_fresh(fake_now,P.vs_received[1]);
  assert(hud_finish_result(&r,0,1,0,0,1,NULL,&trailing)==600);
  net_close(); close(fd); free(rc_mem); puts("partial loopback net/car + constructed HUD snapshot: PASS"); return 0;
}
