#ifndef VS4_SOCKET_H
#define VS4_SOCKET_H
#include "vs_session.h"
#include <netinet/in.h>
int vs4_entropy(vs4_nonce *);
int vs4_udp_open(int port,const char *bind_ip);
uint64_t vs4_endpoint(const struct sockaddr_in *);
struct sockaddr_in vs4_sockaddr(uint64_t endpoint);
uint64_t vs4_now_ms(void);
void vs4_udp_emit(void *fd_ptr,uint64_t endpoint,const uint8_t *,size_t);
int vs4_udp_receive(int fd,uint8_t *,size_t,uint64_t *source,int *empty);
/* Strict standalone discovery envelope, separate from active session framing. */
#define VS4_DISCOVER_SIZE 8u
#define VS4_OFFER_SIZE 48u
int vs4_discovery_request(const uint8_t *,size_t);
void vs4_discovery_offer(uint8_t out[48],const vs4_state *,const char *name);
#endif
