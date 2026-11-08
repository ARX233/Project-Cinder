/* Synthetic WV1 receive test. Compile from repository root:
 * cc -std=c11 -Iports/android/src ports/android/test/net_recovery_compat_test.c -o /tmp/net_recovery_compat_test */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <stdarg.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/select.h>
static int test_fcntl(int fd, int cmd, ...);
static int test_close(int fd);
static ssize_t test_recvfrom(int fd, void *buf, size_t len, int flags, struct sockaddr *src, socklen_t *addrlen);
#define fcntl test_fcntl
#define close test_close
#define recvfrom test_recvfrom
#include "../src/net.c" /* saturation and packet parsing without a production test API */
#undef fcntl
#undef close
#undef recvfrom
static int fail_fcntl, failed_fd, closed_fd;
static int test_fcntl(int fd, int cmd, ...) {
  if (cmd == fail_fcntl) { failed_fd = fd; return -1; }
  if (cmd == F_SETFL) { va_list ap; va_start(ap, cmd); int flags = va_arg(ap, int); va_end(ap); return fcntl(fd, cmd, flags); }
  return fcntl(fd, cmd);
}
static int test_close(int fd) { closed_fd = fd; return close(fd); }
static int scan_fake, scan_infinite, scan_remaining, scan_reads;
static ssize_t test_recvfrom(int fd, void *buf, size_t len, int flags, struct sockaddr *src, socklen_t *addrlen) {
  if (!scan_fake) return recvfrom(fd, buf, len, flags, src, addrlen);
  if (!scan_infinite && !scan_remaining) return -1;
  if (!scan_infinite) --scan_remaining;
  ++scan_reads;
  assert(len >= 25 && *addrlen >= sizeof(struct sockaddr_in));
  unsigned char *b = buf; memset(b, 0, 25); head(b, OFFER); b[4]=1;
  put32(b + 21, scan_reads <= 512 ? 1 : 2);
  struct sockaddr_in *a = (struct sockaddr_in *)src; memset(a, 0, sizeof *a);
  a->sin_family=AF_INET; a->sin_addr.s_addr=htonl(INADDR_LOOPBACK); *addrlen=sizeof *a;
  return 25;
}
static unsigned char incoming[2][2048];
static int incoming_len[2], incoming_count, delivered, sent_race, sent_bye, sent_hello;
static unsigned char last_race_wire[9 + CAR_LINK_PACKET];
static int last_race_len;
static int flood_remaining, flood_infinite, flood_reads, flood_packet_len;
static unsigned char flood_packet[256];
int gk_send(int peer, const void *data, int len) {
  const unsigned char *p = data; (void)peer;
  if (p[3] == RACE) { ++sent_race; assert(len <= (int)sizeof last_race_wire); memcpy(last_race_wire,p,len); last_race_len=len; }
  if (p[3] == BYE) ++sent_bye;
  if (p[3] == HELLO) ++sent_hello;
  return len;
}
int gk_recv(void *data, int max, int *peer) {
  if (flood_infinite || flood_remaining) {
    if (!flood_infinite) --flood_remaining;
    ++flood_reads; int n = flood_packet_len ? flood_packet_len : 4;
    assert(max >= n); memcpy(data, flood_packet_len ? flood_packet : (const unsigned char *)"bad!", n); *peer = -1; return n;
  }
  if (!incoming_count) return 0;
  int n = incoming_len[0]; assert(n <= max); memcpy(data, incoming[0], n);
  if (--incoming_count) { memcpy(incoming[0], incoming[1], incoming_len[1]); incoming_len[0] = incoming_len[1]; }
  *peer = -1; return n;
}
void car_link_deliver(int pcb, const unsigned char *p, int len) {
  assert(pcb == 0 && len == CAR_LINK_PACKET && p[0] == 0x5a); ++delivered;
}
static void queue(const unsigned char *p, int n) { assert(incoming_count < 2); memcpy(incoming[incoming_count],p,n); incoming_len[incoming_count++]=n; }
static int lobby(unsigned char *b, int n) {
  memset(b,0,256); head(b,LOBBY); b[4]=n; b[5]=0; b[6]=0;
  int at=13;
  for (int i=0;i<n;i++) { b[at++]=i; put32(b+at,10+i); at+=4; b[at++]=0; at+=16; b[at++]=0; }
  return at;
}
static int go(unsigned char *b, unsigned id) {
  memset(b,0,256); head(b,GO); put32(b+4,id); b[14]=1; b[15]=0;
  b[16]=0; put32(b+17,10); return 38;
}
static int race(unsigned char *b, unsigned id, unsigned count) {
  memset(b,0,256); head(b,RACE); put32(b+4,id); b[9]=0x5a;
  put32(b+9+PACKET_COUNT,count); return 9+CAR_LINK_PACKET;
}
static void poll(void) { net_poll(1,0,"test",NULL,0); }
/* Complete two-player GO with either wire slot order and optional song. */
static int go_two(unsigned char *b, uint32_t rid, int reversed, int song) {
  memset(b,0,256); head(b,GO); put32(b+4,rid); b[14]=2; b[15]=0;
  int at=16;
  for (int i=0;i<2;i++) { int slot=reversed ? 1-i : i; b[at++]=slot; put32(b+at,10+slot); at+=4; at+=16; b[at++]=0; }
  if (song >= 0) b[at++]=(unsigned char)song;
  return at;
}
static void strict_go_test(void) {
  unsigned char b[256], bad[256]; net_go g; int n;
  assert(net_open_gk(10)==0); net_require_valid_go(1);
  n=go_two(b,100,1,7); queue(b,n); poll(); net_require_valid_go(1);
  assert(N.go_new && N.go.race==100 && N.go.song==7 && N.go.player[0].id==10 && N.go.player[1].id==11);
  /* Every malformed candidate arrives after a valid pending GO, in the same drain. */
  for (int kind=0;kind<10;kind++) {
    int m=go_two(bad,101,0,0);
    switch(kind) {
      case 0: put32(bad+4,0); break;
      case 1: bad[14]=0; break;
      case 2: bad[14]=5; break;
      case 3: bad[15]=2; break;
      case 4: bad[38]=0; break; /* repeated slot */
      case 5: bad[38]=2; break; /* outside advertised range */
      case 6: put32(bad+17,0); break;
      case 7: put32(bad+39,10); break;
      case 8: put32(bad+17,99); break;
      case 9: --m; --m; break; /* profile length byte absent */
    }
    queue(bad,m); poll(); net_require_valid_go(1);
    assert(N.go_new && N.go.race==100 && N.go.song==7);
  }
  assert(net_take_go(&g) && g.race==100);
  n=race(b,100,1); queue(b,n); poll(); assert(net_race_peer_packet_seen(100,0));
  net_require_valid_go(1); net_require_valid_go(1); assert(N.race==100 && N.rx_new[0] && net_race_peer_packet_seen(100,0));
  n=go_two(bad,102,0,-1); bad[38]=0; queue(bad,n);
  n=go_two(b,103,0,-1); queue(b,n); poll(); assert(net_take_go(&g) && g.race==103 && g.song==0);
  /* >64 byte profile is permitted only in full, with song and trailing extension. */
  n=go(b,104); b[37]=65; memset(b+38,0x5a,65); b[103]=9; b[104]=0xcc;
  queue(b,102); poll(); assert(!net_take_go(&g));
  queue(b,105); poll(); assert(net_take_go(&g) && g.race==104 && g.song==9 && g.player[0].profile_len==64 && g.player[0].profile[63]==0x5a);
  net_require_valid_go(0); n=go(b,105); b[14]=0; queue(b,16); poll(); assert(net_take_go(&g) && g.n==0);
  n=go_two(b,107,0,-1); b[14]=5;
  for (int i=2;i<4;i++) { b[n++]=i; put32(b+n,10+i); n+=4; memset(b+n,0,17); n+=17; }
  queue(b,n); poll(); assert(net_take_go(&g) && g.race==107 && g.n==4);
  net_close(); assert(net_open_gk(10)==0); n=go(b,106); b[14]=0; queue(b,16); poll(); assert(net_take_go(&g) && g.n==0); net_close();
}
static void active_pcb_test(int strict) {
  unsigned char b[256], packet[CAR_LINK_PACKET]={0}; net_go g; int n;
  assert(net_open_gk(11)==0); net_require_valid_go(strict);
  n=go_two(b,201,0,-1); b[15]=1; queue(b,n); poll(); assert(net_take_go(&g) && g.pcb==1);
  net_race_send(packet,sizeof packet); assert(get32(last_race_wire+4)==201 && last_race_wire[8]==1);
  n=go_two(b,202,0,-1); put32(b+17,11); put32(b+39,10); queue(b,n); poll(); assert(N.go_new && N.go.pcb==0);
  net_race_send(packet,sizeof packet); assert(get32(last_race_wire+4)==201 && last_race_wire[8]==1);
  n=go_two(b,203,0,-1); b[15]=1; queue(b,n-1); poll(); assert(N.go_new && N.go.race==202);
  net_race_send(packet,sizeof packet); assert(get32(last_race_wire+4)==201 && last_race_wire[8]==1);
  assert(net_take_go(&g) && g.race==202 && g.pcb==0);
  net_race_send(packet,sizeof packet); assert(get32(last_race_wire+4)==202 && last_race_wire[8]==0);
  int before=sent_race; net_race_send(packet,-1); net_race_send(NULL,1); net_race_send(packet,CAR_LINK_PACKET+1); assert(sent_race==before);
  net_race_send(NULL,0); assert(sent_race==before+1 && last_race_len==9 && get32(last_race_wire+4)==202 && last_race_wire[8]==0);
  net_abandon_race(); assert(N.race_pcb==0); int count=sent_race; net_race_send(packet,sizeof packet); assert(sent_race==count);
  net_close();
}
static void strict_go_udp_test(void) {
  int fd=socket(AF_INET,SOCK_DGRAM,0); assert(fd>=0);
  struct sockaddr_in server={0},client={0}; socklen_t al=sizeof server;
  server.sin_family=AF_INET; server.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
  assert(bind(fd,(struct sockaddr *)&server,sizeof server)==0 && getsockname(fd,(struct sockaddr *)&server,&al)==0);
  assert(net_open("127.0.0.1",ntohs(server.sin_port),10)==0 && !N.require_valid_go); net_require_valid_go(1); poll();
  unsigned char b[256]; al=sizeof client; assert(recvfrom(fd,b,sizeof b,0,(struct sockaddr *)&client,&al)>0);
  int n=go_two(b,120,0,4); assert(sendto(fd,b,n,0,(struct sockaddr *)&client,sizeof client)==n);
  n=go_two(b,121,0,4); b[38]=0; assert(sendto(fd,b,n,0,(struct sockaddr *)&client,sizeof client)==n);
  struct timeval tv={0,20000}; select(0,NULL,NULL,NULL,&tv);
  poll(); net_require_valid_go(1); net_go g; assert(net_take_go(&g) && g.race==120 && g.song==4);
  net_close(); close(fd);
}
static void sequence_emit(uint32_t id) {
  unsigned char b[256]; int n=go(b,id); queue(b,n); poll();
}
static int sequence_only_test(void) {
  net_go g; int failures=0;
#define CHECK_SEQUENCE(label, expr) do { int ok=!!(expr); printf("%s: %s\n",label,ok?"PASS":"FAIL"); if (!ok) ++failures; } while (0)
  assert(net_open_gk(10)==0); net_require_valid_go(1);
  sequence_emit(10); assert(net_take_go(&g)); sequence_emit(11); assert(net_take_go(&g));
  sequence_emit(10); CHECK_SEQUENCE("strict late 10 after active 11", !N.go_new); net_close();
  const uint32_t old[] = {10, 11, UINT32_C(0x8000000c)};
  const char *labels[] = {"pending 12 then old 10", "pending 12 then active 11", "pending 12 then half-range"};
  for (int i=0;i<3;i++) {
    assert(net_open_gk(10)==0); net_require_valid_go(1);
    sequence_emit(10); assert(net_take_go(&g)); sequence_emit(11); assert(net_take_go(&g));
    sequence_emit(12); assert(N.go_new && N.go.race==12);
    unsigned char b[256]; int n=go(b,old[i]); queue(b,n); net_poll(5,0,"test",NULL,0);
    CHECK_SEQUENCE(labels[i],N.race==11 && N.go_new && N.go.race==12 && N.last_heard==1); net_close();
  }
  assert(net_open_gk(10)==0); net_require_valid_go(1);
  sequence_emit(UINT32_MAX); assert(net_take_go(&g)); sequence_emit(1);
  CHECK_SEQUENCE("wrap UINT_MAX to 1",N.go_new && N.go.race==1);
  assert(net_take_go(&g)); sequence_emit(UINT32_C(0x80000001));
  CHECK_SEQUENCE("active 1 then half-range",!N.go_new); net_close();
  assert(net_open_gk(10)==0); net_require_valid_go(1);
  sequence_emit(10); assert(net_take_go(&g)); sequence_emit(12); assert(N.go_new);
  unsigned char invalid[256]; int invalid_n=go(invalid,100); invalid[37]=1;
  queue(invalid,invalid_n); net_poll(8,0,"test",NULL,0);
  CHECK_SEQUENCE("malformed newer leaves pending/time intact",N.race==10 && N.go_new && N.go.race==12 && N.last_heard==1);
  sequence_emit(13); CHECK_SEQUENCE("valid after malformed advances pending",N.go_new && N.go.race==13); net_close();
  assert(net_open_gk(10)==0);
  sequence_emit(10); assert(net_take_go(&g)); sequence_emit(11); assert(net_take_go(&g));
  sequence_emit(12); sequence_emit(10);
  CHECK_SEQUENCE("default retains historical overwrite",N.go_new && N.go.race==10);
  net_close();
#undef CHECK_SEQUENCE
  return failures ? 1 : 0;
}
int main(int argc, char **argv) {
  if (argc==2 && !strcmp(argv[1],"--sequence-only")) return sequence_only_test();
  unsigned char b[256]; int n; net_go g;
  assert(!net_is_open() && !net_lobby_valid_now()->connected && net_lobby_observations()==0);
  assert(net_open_gk(10)==0); poll(); assert(sent_hello==1 && !net_lobby_valid_now()->connected);
  n=lobby(b,2); b[5]=2; queue(b,n); poll();
  assert(net_lobby_now()->connected && !net_lobby_valid_now()->connected && net_lobby_observations()==0);
  n=lobby(b,2); queue(b,n); b[5]=2; put32(b+14,99); queue(b,n); poll();
  assert(net_lobby_observations()==1 && net_lobby_now()->me==2 && net_lobby_now()->player[0].id==99);
  assert(net_lobby_valid_now()->connected && net_lobby_valid_now()->me==0 && net_lobby_valid_now()->player[0].id==10);
  n=lobby(b,2);
  queue(b,n); poll(); assert(net_lobby_observations()==2);
  queue(b,n-1); poll(); assert(net_lobby_observations()==2);
  b[5]=2; queue(b,n); poll(); assert(net_lobby_observations()==2); b[5]=0;
  b[13+23]=0; queue(b,n); poll(); assert(net_lobby_observations()==2);
  n=lobby(b,2); put32(b+13+23+1,10); queue(b,n); poll(); assert(net_lobby_observations()==2);
  n=lobby(b,2); b[13]=2; queue(b,n); poll(); assert(net_lobby_observations()==2);
  n=lobby(b,2); b[4]=5; queue(b,n); poll(); assert(net_lobby_observations()==2);
  n=go(b,9); queue(b,n); poll(); net_abandon_race(); assert(!net_take_go(&g));
  queue(b,n); poll(); assert(!net_take_go(&g));
  assert(!net_race_peer_packet_seen(0,0) && !net_race_peer_packet_seen(11,0));
  n=go(b,11); queue(b,n); poll(); assert(net_take_go(&g) && g.race==11);
  assert(!net_race_peer_packet_seen(11,-1) && !net_race_peer_packet_seen(11,CAR_LINK_MACHINES));
  net_poll(1,1,"test",NULL,0); assert(!net_race_peer_packet_seen(11,0));
  n=race(b,11,1); queue(b,9); poll(); queue(b,n-1); poll();
  b[0]='X'; queue(b,n); poll(); b[0]='W';
  b[8]=CAR_LINK_MACHINES; queue(b,n); poll(); b[8]=0;
  put32(b+4,12); queue(b,n); poll(); put32(b+4,11);
  assert(!net_race_peer_packet_seen(11,0));
  queue(b,n); net_race_receive(); assert(delivered==1 && net_race_peer_packet_seen(11,0));
  assert(!net_race_peer_packet_seen(0,0) && !net_race_peer_packet_seen(12,0));
  queue(b,n); put32(b+4,9); queue(b,n); poll(); assert(net_race_peer_packet_seen(11,0) && !net_race_peer_packet_seen(9,0));
  n=race(b,11,2); queue(b,n); poll(); net_abandon_race();
  assert(!net_race_peer_packet_seen(11,0));
  assert(net_is_open() && net_lobby_now()->connected && sent_bye==0 && N.id==10);
  assert(net_lobby_valid_now()->connected && net_lobby_valid_now()->player[0].id==10 && net_lobby_observations()==2);
  net_race_receive(); assert(delivered==1);
  net_race_send(b,CAR_LINK_PACKET); assert(sent_race==0);
  n=race(b,11,3); queue(b,n); net_race_receive(); assert(delivered==1);
  n=go(b,11); queue(b,n); poll(); assert(!net_take_go(&g));
  n=go(b,12); queue(b,n); poll(); assert(net_take_go(&g) && g.race==12);
  assert(!net_race_peer_packet_seen(11,0) && !net_race_peer_packet_seen(12,0));
  n=race(b,12,1); queue(b,n); net_race_receive(); assert(delivered==2 && net_race_peer_packet_seen(12,0));
  N.lobby_observations=UINT64_MAX; n=lobby(b,1); put32(b+14,88); queue(b,n); poll();
  assert(net_lobby_observations()==UINT64_MAX && net_lobby_now()->player[0].id==88 && net_lobby_valid_now()->player[0].id==10);
  net_close(); assert(!net_is_open() && !net_race_peer_packet_seen(12,0) && net_lobby_observations()==0 && !net_lobby_now()->connected && !net_lobby_valid_now()->connected && sent_bye==1);
  assert(net_open_gk(10)==0 && net_lobby_observations()==0 && !net_lobby_valid_now()->connected);
  /* Permuted wire records are indexed by slot in the strict snapshot, unlike the legacy view. */
  n=lobby(b,2); unsigned char tmp[23]; memcpy(tmp,b+13,23); memcpy(b+13,b+36,23); memcpy(b+36,tmp,23);
  queue(b,n); put32(b+37,99); queue(b,n); poll();
  assert(net_lobby_observations()==1 && net_lobby_valid_now()->player[net_lobby_valid_now()->me].id==10);
  assert(net_lobby_valid_now()->player[1].id==11 && net_lobby_now()->player[1].id==99);
  /* Complete oversized legacy profile is clamped; an incomplete one never advances. */
  n=lobby(b,1); b[35]=65; memset(b+36,0x5a,65); queue(b,n+65); poll();
  assert(net_lobby_observations()==2 && net_lobby_valid_now()->player[0].profile_len==64 && net_lobby_valid_now()->player[0].profile[63]==0x5a);
  b[35]=66; queue(b,n+65); poll(); assert(net_lobby_observations()==2);
  net_close();
  /* Both fcntl failure branches close the just-created UDP descriptor. */
  fail_fcntl=F_GETFL; failed_fd=closed_fd=-1;
  assert(net_open("127.0.0.1",27015,10)==-1 && failed_fd>=0 && closed_fd==failed_fd && fcntl(failed_fd,F_GETFD)==-1 && !net_is_open());
  fail_fcntl=F_SETFL; failed_fd=closed_fd=-1;
  assert(net_open("127.0.0.1",27015,10)==-1 && failed_fd>=0 && closed_fd==failed_fd && fcntl(failed_fd,F_GETFD)==-1 && !net_is_open());
  fail_fcntl=0;
  assert(net_open_gk(10)==0);
  flood_infinite=1; flood_reads=0; poll(); assert(flood_reads==512 && net_is_open());
  flood_reads=0; net_race_receive(); assert(flood_reads==512 && net_is_open());
  flood_infinite=0; flood_remaining=513; flood_reads=0;
  n=go(b,41); queue(b,n); poll(); assert(flood_reads==512 && !net_take_go(&g));
  poll(); assert(flood_reads==513 && net_take_go(&g) && g.race==41);
  n=race(b,41,1); queue(b,n); net_race_receive(); assert(net_race_peer_packet_seen(41,0));
  /* A >budget sequence of valid lobbies followed by GO is retained in order. */
  flood_packet_len=lobby(flood_packet,1); flood_remaining=513; flood_reads=0;
  n=go(b,42); queue(b,n); poll(); assert(flood_reads==512 && net_lobby_observations()==512 && !net_take_go(&g));
  poll(); assert(flood_reads==513 && net_lobby_observations()==513 && net_take_go(&g) && g.race==42);
  assert(!net_race_peer_packet_seen(41,0) && !net_race_peer_packet_seen(42,0));
  n=race(b,42,1); queue(b,n); net_race_receive(); assert(net_race_peer_packet_seen(42,0));
  net_close(); assert(!net_race_peer_packet_seen(41,0));
  flood_infinite=1; flood_reads=0; poll(); net_race_receive(); assert(flood_reads==0); flood_infinite=0;
  /* Discovery setup failures never leave a blocking descriptor installed. */
  fail_fcntl=F_GETFL; failed_fd=closed_fd=-1; net_scan(1,1);
  assert(S.fd==-1 && failed_fd>=0 && closed_fd==failed_fd && fcntl(failed_fd,F_GETFD)==-1);
  fail_fcntl=F_SETFL; failed_fd=closed_fd=-1; net_scan(1,1);
  assert(S.fd==-1 && failed_fd>=0 && closed_fd==failed_fd && fcntl(failed_fd,F_GETFD)==-1);
  fail_fcntl=0; scan_fake=1; scan_infinite=1; scan_reads=0;
  net_scan(1,1); assert(S.fd>=0 && scan_reads==512);
  net_found found[NET_FOUND]; assert(net_found_list(found,NET_FOUND)==1 && found[0].id==1);
  net_scan(1.1,1); assert(scan_reads==1024);
  net_scan(1.2,0); assert(S.fd==-1 && net_found_list(found,NET_FOUND)==0);
  scan_infinite=0; scan_remaining=513; scan_reads=0;
  net_scan(2,1); assert(scan_reads==512 && scan_remaining==1);
  assert(net_found_list(found,NET_FOUND)==1 && found[0].id==1);
  net_scan(2.1,1); assert(scan_reads==513 && scan_remaining==0);
  assert(net_found_list(found,NET_FOUND)==2 && found[1].id==2);
  int scan_fd=S.fd; net_scan(2.2,0); assert(S.fd==-1 && closed_fd==scan_fd && net_found_list(found,NET_FOUND)==0);
  scan_fake=0;
  /* Zero-ID peers retain the historical view but cannot publish a strict snapshot. */
  assert(net_open_gk(10)==0);
  n=lobby(b,2); queue(b,n); put32(b+37,0); queue(b,n); poll();
  assert(net_lobby_observations()==1 && net_lobby_now()->player[1].id==0);
  assert(net_lobby_valid_now()->player[0].id==10 && net_lobby_valid_now()->player[1].id==11);
  n=lobby(b,2); put32(b+37,10); queue(b,n); poll(); assert(net_lobby_observations()==1);
  n=lobby(b,2); queue(b,n-1); poll(); assert(net_lobby_observations()==1);
  queue(b,n); poll(); assert(net_lobby_observations()==2 && net_lobby_valid_now()->player[1].id==11);
  net_close();
  /* An explicitly zero local ID cannot produce a strict valid snapshot either. */
  assert(net_open_gk(0)==0); n=lobby(b,1); put32(b+14,0); queue(b,n); poll();
  assert(net_lobby_now()->connected && net_lobby_now()->player[0].id==0);
  assert(net_lobby_observations()==0 && !net_lobby_valid_now()->connected);
  net_close();
  /* Strict-snapshot age is independent of generic server traffic. */
  assert(isinf(net_lobby_valid_silence(10)));
  assert(net_open_gk(10)==0 && isinf(net_lobby_valid_silence(10)));
  n=lobby(b,1); queue(b,n); net_poll(10,0,"test",NULL,0);
  assert(net_lobby_valid_silence(12)==2 && isinf(net_lobby_valid_silence(9)));
  assert(isinf(net_lobby_valid_silence(NAN)) && isinf(net_lobby_valid_silence(INFINITY)));
  n=go(b,80); queue(b,n); net_poll(20,0,"test",NULL,0);
  assert(net_silence(20)==0 && net_lobby_valid_silence(20)==10 && net_take_go(&g));
  n=race(b,80,1); queue(b,n); net_poll(21,1,"test",NULL,0);
  assert(net_silence(21)==0 && net_lobby_valid_silence(21)==11);
  n=lobby(b,2); put32(b+37,0); queue(b,n); net_poll(22,0,"test",NULL,0);
  assert(net_silence(22)==0 && net_lobby_valid_silence(22)==12);
  n=lobby(b,1); queue(b,n); net_poll(23,0,"test",NULL,0); assert(net_lobby_valid_silence(23)==0);
  queue(b,n); net_poll(24,0,"test",NULL,0); assert(net_lobby_valid_silence(25)==1);
  N.lobby_observations=UINT64_MAX; queue(b,n); net_poll(26,0,"test",NULL,0);
  assert(net_lobby_valid_silence(26)==2); /* frozen snapshot must not acquire a new timestamp */
  net_close(); assert(isinf(net_lobby_valid_silence(26)));
  assert(net_open_gk(10)==0 && isinf(net_lobby_valid_silence(26)));
  n=lobby(b,1); queue(b,n); net_poll(NAN,0,"test",NULL,0); assert(isinf(net_lobby_valid_silence(30)));
  queue(b,n); net_poll(30,0,"test",NULL,0); assert(net_lobby_valid_silence(31)==1);
  net_close();
  strict_go_test(); strict_go_udp_test(); active_pcb_test(0); active_pcb_test(1);
  puts("WV1 recovery compatibility passed"); return 0;
}
