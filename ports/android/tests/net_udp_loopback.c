/* WV2 UDP loopback regression; compile with UBSan outside the source tree. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/time.h>
#include <sys/select.h>
#include "../src/net.c"
static int delivered,last_pcb,fresh[4],fresh_updates[4];
static unsigned char last_packet[CAR_LINK_PACKET];
void car_link_fresh(int pcb,int active){fresh[pcb]=active;fresh_updates[pcb]+=!!active;}
int gk_send(int peer,const void *b,int len){(void)peer;(void)b;(void)len;return 0;}
int gk_recv(void *b,int max,int *peer){(void)b;(void)max;(void)peer;return 0;}
void car_link_deliver(int pcb,const unsigned char *b,int len){assert(b && len==CAR_LINK_PACKET);memcpy(last_packet,b,CAR_LINK_PACKET);delivered++;last_pcb=pcb;}
static void test_head(unsigned char *b,int kind){head(b,kind);memset(b+4,0x42,16);}
static int lobby_packet(unsigned char *b,const unsigned char join[16]){
  test_head(b,LOBBY);memcpy(b+20,join,16);put64(b+36,1);put64(b+44,0);put64(b+52,0);b[60]=0;b[61]=2;b[62]=0;b[63]=0;b[64]=0;b[65]=13;int at=66;
  for(int k=0;k<2;k++){b[at++]=(unsigned char)k;put32(b+at,10u+(unsigned)k);at+=4;b[at++]=0;memset(b+at,'A'+k,16);at+=16;b[at++]=0;}return at;
}
static int go_packet(unsigned char *b,uint64_t gen,uint64_t race,int local){
  test_head(b,GO);put64(b+20,gen);put64(b+28,race);put32(b+36,0x12345678);b[40]=134;b[41]=13;b[42]=2;b[43]=(unsigned char)local;int at=44;
  for(int k=0;k<2;k++){b[at++]=(unsigned char)k;put32(b+at,10u+(unsigned)k);at+=4;memset(b+at,'A'+k,16);at+=16;b[at++]=0;}b[at++]=4;return at;
}
static int race_packet(unsigned char *b,uint64_t gen,uint64_t race,int pcb,uint32_t count){
  test_head(b,RACE);put64(b+20,gen);put64(b+28,race);b[36]=(unsigned char)pcb;memset(b+37,0,CAR_LINK_PACKET);put32(b+37+PACKET_COUNT,count);
  for(int k=0;k<40;k++)b[37+0x3c+k]=(unsigned char)(k*7+1);return 37+CAR_LINK_PACKET;
}
static void send_packet(int fd,const struct sockaddr_in *dst,const unsigned char *b,int n){
  assert(sendto(fd,b,(size_t)n,0,(const struct sockaddr *)dst,sizeof *dst)==n);fd_set ready;FD_ZERO(&ready);FD_SET(N.fd,&ready);struct timeval timeout={2,0};assert(select(N.fd+1,&ready,NULL,NULL,&timeout)==1);
}
int main(void){
  int fd=socket(AF_INET,SOCK_DGRAM,0);assert(fd>=0);struct timeval timeout={2,0};assert(!setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof timeout));
  struct sockaddr_in addr={0},peer={0};addr.sin_family=AF_INET;addr.sin_addr.s_addr=htonl(INADDR_LOOPBACK);assert(!bind(fd,(const struct sockaddr *)&addr,sizeof addr));socklen_t sz=sizeof addr;assert(!getsockname(fd,(struct sockaddr *)&addr,&sz));
  assert(!net_open("127.0.0.1",ntohs(addr.sin_port),10));net_poll(1,0,"LOCAL",NULL,0);
  unsigned char b[2048],join[16];sz=sizeof peer;int n=(int)recvfrom(fd,b,sizeof b,0,(struct sockaddr *)&peer,&sz);
  assert(n==74 && b[0]=='W' && b[1]=='V' && b[2]==2 && b[3]==HELLO && !memcmp(b+4,zero,16) && get32(b+20)==10 && memcmp(b+24,zero,16));memcpy(join,b+24,16);
  n=lobby_packet(b,join);send_packet(fd,&peer,b,n);net_poll(1.1,0,"LOCAL",NULL,0);assert(net_room_ready());
  n=go_packet(b,2,1,0);send_packet(fd,&peer,b,n-1);net_poll(1.2,0,"LOCAL",NULL,0);net_go g;assert(!net_take_go(&g));
  b[2]=1;send_packet(fd,&peer,b,n);net_poll(1.21,0,"LOCAL",NULL,0);assert(!net_take_go(&g));b[2]=2;
  send_packet(fd,&peer,b,n);net_poll(1.22,0,"LOCAL",NULL,0);assert(net_take_go(&g));assert(g.ramp==134 && g.km==13 && g.song==4 && g.n==2 && g.pcb==0 && g.generation==2 && g.race==1);
  n=race_packet(b,2,1,1,0xffffffffu);send_packet(fd,&peer,b,n);net_race_receive();assert(delivered==1 && last_pcb==1 && !memcmp(last_packet,b+37,CAR_LINK_PACKET) && fresh_updates[1]==1);
  send_packet(fd,&peer,b,n);net_race_receive();assert(delivered==2 && fresh_updates[1]==1);
  put32(b+37+PACKET_COUNT,0);send_packet(fd,&peer,b,n);net_race_receive();assert(delivered==3 && fresh_updates[1]==2);
  put32(b+37+PACKET_COUNT,0xffffffffu);send_packet(fd,&peer,b,n);net_race_receive();assert(delivered==3);
  b[36]=0;send_packet(fd,&peer,b,n);net_race_receive();b[36]=2;send_packet(fd,&peer,b,n);net_race_receive();assert(delivered==3);
  while(recv(fd,b,sizeof b,MSG_DONTWAIT)>0){} /* discard any periodic HELLO */
  unsigned char data[CAR_LINK_PACKET];for(int i=0;i<CAR_LINK_PACKET;i++)data[i]=(unsigned char)(i*7+3);net_race_send(data,CAR_LINK_PACKET);
  n=(int)recv(fd,b,sizeof b,0);assert(n==37+CAR_LINK_PACKET && b[2]==2 && b[3]==RACE && get64(b+20)==2 && get64(b+28)==1 && b[36]==0 && !memcmp(b+37,data,CAR_LINK_PACKET));
  n=go_packet(b,4,2,1);send_packet(fd,&peer,b,n);net_poll(1.3,0,"LOCAL",NULL,0);assert(!net_take_go(&g));
  n=race_packet(b,2,1,1,1);send_packet(fd,&peer,b,n);net_race_receive();assert(delivered==4 && last_pcb==1);
  net_close();close(fd);puts("WV2 UDP loopback net tests passed");return 0;
}
