/* Source-level WV1 C host test: no socket is opened, bound or contacted.
 * cc -std=c11 -Wall -Wextra -Werror -fsanitize=undefined \
 * ports/android/tests/test_wv1_c_host_profile.c -o /tmp/test_wv1_c_host_profile && /tmp/test_wv1_c_host_profile
 * Tests opaque wire bytes, not legacy client parsing, authentication, or replay defense. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <netinet/in.h>
static ssize_t mock_sendto(int, const void *, size_t, int, const struct sockaddr *, socklen_t);
#define sendto mock_sendto
#include "../src/vs_host.c"
#undef sendto
int gk_send(int peer, const void *b, int len) { (void)peer; (void)b; (void)len; assert(!"unexpected GameKit send"); return -1; }
int gk_recv(void *b, int max, int *peer) { (void)b; (void)max; (void)peer; assert(!"unexpected GameKit receive"); return 0; }
typedef struct { unsigned char bytes[2048]; size_t len; unsigned short port; } packet;
static packet sent[128]; static int nsent;
static ssize_t mock_sendto(int fd, const void *buf, size_t len, int flags, const struct sockaddr *to, socklen_t tolen) {
  const struct sockaddr_in *a = (const struct sockaddr_in *)to;
  assert(fd == 123 && flags == 0 && tolen == sizeof *a && a->sin_family == AF_INET);
  assert(nsent < 128 && len <= sizeof sent[0].bytes);
  sent[nsent].port = ntohs(a->sin_port); sent[nsent].len = len;
  memcpy(sent[nsent++].bytes, buf, len); return (ssize_t)len;
}
typedef struct { uint32_t id; unsigned char name[NET_NAME], profile[47]; int len; addr from; } fixture;
static fixture f[5];
static void init_fixture(int i, int len) {
  f[i].id = 0x12340000u + (uint32_t)i; f[i].len = len;
  for (int j = 0; j < NET_NAME; ++j) f[i].name[j] = (unsigned char)(0x31 + i * 17 + j);
  for (int j = 0; j < len; ++j) f[i].profile[j] = (unsigned char)(i * 53 + j * 29);
  if (len >= 42) {
    memcpy(f[i].profile + 21, "RFR1", 4);
    f[i].profile[25] = 0; /* NORMAL, with nonzero opaque nonce */
    memset(f[i].profile + 26, 0, 16); f[i].profile[30] = (unsigned char)(i + 1);
    f[i].profile[38] = (unsigned char)(i + 7);
  }
  if (len == 47) { memcpy(f[i].profile + 42, "RDY1", 4); f[i].profile[46] = 1; }
  f[i].from.a.sin_family = AF_INET; f[i].from.a.sin_addr.s_addr = htonl(0x7f000001u);
  f[i].from.a.sin_port = htons((unsigned short)(41000 + i));
}
static int make_hello(unsigned char *b, int i) {
  head(b, HELLO); put32(b + 4, f[i].id); b[8] = 0;
  memcpy(b + 9, f[i].name, NET_NAME); b[25] = (unsigned char)f[i].len;
  memcpy(b + 26, f[i].profile, (size_t)f[i].len); return 26 + f[i].len;
}
static void inject(const unsigned char *b, int n, int i) { got(b, n, &f[i].from, 1.0, "test"); }
static void verify_lobby(int n, int recipient, const packet *p) {
  unsigned char expected[1024] = {'W','V',1,LOBBY};
  expected[4] = (unsigned char)n; expected[5] = (unsigned char)recipient; expected[8] = 13;
  int at = 13;
  for (int i = 0; i < n; ++i) {
    expected[at] = (unsigned char)i; put32(expected + at + 1, f[i].id);
    memcpy(expected + at + 6, f[i].name, NET_NAME); expected[at + 6 + NET_NAME] = (unsigned char)f[i].len;
    memcpy(expected + at + 7 + NET_NAME, f[i].profile, (size_t)f[i].len); at += 7 + NET_NAME + f[i].len;
  }
  assert(p->port == 41000 + recipient && p->len == (size_t)at && memcmp(p->bytes, expected, (size_t)at) == 0);
}
static void verify_go(int n, int recipient, const packet *p, uint32_t seed) {
  unsigned char expected[1024] = {'W','V',1,GO}; put32(expected + 4, 1); put32(expected + 8, seed);
  expected[12] = 2; expected[13] = 17; expected[14] = (unsigned char)n; expected[15] = (unsigned char)recipient;
  int at = 16;
  for (int i = 0; i < n; ++i) {
    expected[at] = (unsigned char)i; put32(expected + at + 1, f[i].id);
    memcpy(expected + at + 5, f[i].name, NET_NAME); expected[at + 5 + NET_NAME] = (unsigned char)f[i].len;
    memcpy(expected + at + 6 + NET_NAME, f[i].profile, (size_t)f[i].len); at += 6 + NET_NAME + f[i].len;
  }
  expected[at++] = 7;
  assert(p->port == 41000 + recipient && p->len == (size_t)at && memcmp(p->bytes, expected, (size_t)at) == 0);
}
int main(void) {
  const int lengths[] = {21, 42, 47, 47, 47}; unsigned char b[256];
  for (int i = 0; i < 5; ++i) init_fixture(i, lengths[i]);
  /* vs_host_open is deliberately never called. */
  memset(&H, 0, sizeof H); H.fd = 123; H.owner = f[0].id; H.km = 13;
  for (int i = 0; i < 4; ++i) {
    int len = make_hello(b, i); nsent = 0; inject(b, len - 1, i);
    assert(H.n == i && nsent == 0); inject(b, len, i);
    assert(H.n == i + 1 && nsent == i + 1);
    for (int j = 0; j <= i; ++j) verify_lobby(i + 1, j, &sent[j]);
    nsent = 0; inject(b, len, i); assert(H.n == i + 1 && nsent == 1); verify_lobby(i + 1, i, &sent[0]);
  }
  nsent = 0; int len = make_hello(b, 4); inject(b, len, 4); assert(H.n == 4 && nsent == 0);
  f[1].profile[41] ^= 0xff; len = make_hello(b, 1); inject(b, len, 1);
  assert(H.n == 4 && nsent == 4); for (int j = 0; j < 4; ++j) verify_lobby(4, j, &sent[j]);
  /* A persistent loaded marker is an ordinary profile update to this host. */
  nsent = 0; f[2].profile[46] = 0; len = make_hello(b, 2); inject(b, len, 2);
  assert(H.n == 4 && nsent == 4); for (int j = 0; j < 4; ++j) verify_lobby(4, j, &sent[j]);
  nsent = 0; f[2].profile[46] = 1; len = make_hello(b, 2); inject(b, len, 2);
  assert(H.n == 4 && nsent == 4); for (int j = 0; j < 4; ++j) verify_lobby(4, j, &sent[j]);
  unsigned char start[] = {'W','V',1,START,2,17,7}; nsent = 0; inject(start, sizeof start, 0);
  assert(nsent == 12 && H.race_id == 1); uint32_t seed = get32(sent[0].bytes + 8);
  for (int j = 0; j < 4; ++j) for (int t = 0; t < 3; ++t) verify_go(4, j, &sent[j * 3 + t], seed);
  unsigned char race[] = {'W','V',1,RACE,1,0,0,0,0x80,0,0xff,0x42,0x00}; nsent = 0; inject(race, sizeof race, 1);
  assert(nsent == 3); int ports[] = {41000, 41002, 41003};
  for (int j = 0; j < 3; ++j) assert(sent[j].port == ports[j] && sent[j].len == sizeof race && memcmp(sent[j].bytes, race, sizeof race) == 0);
  puts("WV1 C host mixed legacy/new profile relay: PASS (in-memory mock; no network)"); return 0;
}
