/* WV2 state regression; compile with UBSan outside the source tree. No network. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../src/net.c"
static unsigned char sent[2048], delivered_packet[CAR_LINK_PACKET];
static int sent_len, delivered, last_pcb;
static int fresh[CAR_LINK_MACHINES], fresh_updates[CAR_LINK_MACHINES];
void car_link_fresh(int pcb,int active) {fresh[pcb]=active;fresh_updates[pcb]+=!!active;}
int gk_send(int peer,const void *b,int len){(void)peer;assert(len>=0 && len<=(int)sizeof sent);memcpy(sent,b,(size_t)len);sent_len=len;return 0;}
int gk_recv(void *b,int max,int *peer){(void)b;(void)max;(void)peer;return 0;}
void car_link_deliver(int pcb,const unsigned char *packet,int len){assert(packet && len==CAR_LINK_PACKET);memcpy(delivered_packet,packet,(size_t)len);delivered++;last_pcb=pcb;}
static void test_head(unsigned char *b,int kind) {head(b,kind);memset(b+4,0x42,16);}
static int lobby(unsigned char *b) {
  test_head(b,LOBBY);memcpy(b+20,N.join,16);put64(b+36,1);put64(b+44,0);put64(b+52,0);
  b[60]=0;b[61]=2;b[62]=0;b[63]=0;b[64]=0;b[65]=13;int at=66;
  for(int i=0;i<2;i++){b[at++]=(unsigned char)i;put32(b+at,10u+(unsigned)i);at+=4;b[at++]=0;memset(b+at,'A'+i,16);at+=16;b[at++]=0;}return at;
}
static int make_go(unsigned char *b,uint64_t gen,uint64_t race,int me) {
  test_head(b,GO);put64(b+20,gen);put64(b+28,race);put32(b+36,99);b[40]=128;b[41]=13;b[42]=2;b[43]=(unsigned char)me;int at=44;
  for(int i=0;i<2;i++){b[at++]=(unsigned char)i;put32(b+at,10u+(unsigned)i);at+=4;memset(b+at,'A'+i,NET_NAME);at+=NET_NAME;b[at++]=0;}b[at++]=3;return at;
}
static int make_race(unsigned char *b,uint64_t gen,uint64_t race,int pcb,uint32_t count){
  test_head(b,RACE);put64(b+20,gen);put64(b+28,race);b[36]=(unsigned char)pcb;memset(b+37,0,CAR_LINK_PACKET);put32(b+37+PACKET_COUNT,count);
  for(int k=0;k<40;k++)b[37+0x3c+k]=(unsigned char)(k*7+1);return 37+CAR_LINK_PACKET;
}
int main(void){
  unsigned char b[2048],packet[CAR_LINK_PACKET]={0};net_go go;assert(!net_open_gk(10));
  int n=lobby(b);for(int k=0;k<n;k++){got(b,k,1);assert(!N.lobby.connected);}got(b,n,1);assert(N.lobby.connected && net_room_ready());
  n=make_go(b,2,1,0);for(int k=0;k<n;k++){got(b,k,1);assert(!N.go_new);}
  b[2]=1;got(b,n,1);assert(!N.go_new);b[2]=2;
  b[42]=5;got(b,n,1);assert(!N.go_new);b[42]=2;
  b[43]=2;got(b,n,1);assert(!N.go_new);b[43]=0;
  b[44+22]=0;got(b,n,1);assert(!N.go_new);b[44+22]=1;
  got(b,n,1);assert(net_take_go(&go));assert(go.n==2 && go.pcb==0 && go.race==1 && go.generation==2);
  sent_len=0;net_race_send(packet,-1);assert(!sent_len);net_race_send(NULL,1);assert(!sent_len);net_race_send(packet,CAR_LINK_PACKET);
  assert(sent_len==37+CAR_LINK_PACKET && sent[2]==2 && sent[3]==RACE && get64(sent+20)==2 && get64(sent+28)==1 && sent[36]==0 && !memcmp(sent+37,packet,CAR_LINK_PACKET));
  n=make_race(b,2,1,1,0xffffffffu);got(b,n-1,2);assert(!N.rx_new[1]);got(b,n,2);net_race_receive();
  assert(delivered==1 && last_pcb==1 && fresh[1] && fresh_updates[1]==1 && !memcmp(delivered_packet,b+37,CAR_LINK_PACKET));
  got(b,n,2.5);net_race_receive();assert(delivered==2 && fresh_updates[1]==1);
  put32(b+37+PACKET_COUNT,0);got(b,n,3);net_race_receive();assert(delivered==3 && fresh_updates[1]==2);
  put32(b+37+PACKET_COUNT,0xffffffffu);got(b,n,4);net_race_receive();assert(delivered==3);
  b[36]=0;got(b,n,5);b[36]=2;got(b,n,5);net_race_receive();assert(delivered==3);
  n=make_go(b,4,2,1);got(b,n,6);assert(!N.go_new); /* old active race cannot be replaced */
  n=make_race(b,2,1,1,1);got(b,n,7);net_race_receive();assert(delivered==4 && last_pcb==1);
  test_head(b,ABORT);put64(b+20,3);put64(b+28,1);got(b,36,8);uint64_t gen,race;assert(net_abort_pending(&gen,&race) && gen==3 && race==1 && !fresh[1]);
  assert(!net_room_ready());assert(net_abort_ack(gen,race));
  test_head(b,CLOSED);got(b,20,9);assert(!net_host_closed());put64(b+20,3);put32(b+28,10);got(b,32,9);assert(net_host_closed());
  net_found found;assert(net_found_list(&found,-1)==0 && net_found_list(NULL,1)==0);net_close();puts("WV2 synthetic net state tests passed");return 0;
}
