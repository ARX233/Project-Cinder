/* CinderVS4 embedded UDP authority; caller-thread bounded polling. */
#ifndef VS_HOST_H
#define VS_HOST_H
#include "vs_session.h"
/* Bind LAN authority. port0 requests ephemeral port (fixture-friendly).
 * Fresh128-bit OS-random incarnation; no entropy fallback. */
int vs_host_open(int port);
int vs_host_open_on(int port,const char *bind_ipv4); /* loopback fixture option */
void vs_host_close(void);
int vs_host_is_open(void);
int vs_host_port(void);
void vs_host_poll(uint64_t now_ms,const char *name);
const vs4_state *vs_host_state(void);
void vs_host_set_decision_validator(vs4_decision_fn,void *ctx);
void vs_host_set_registration_validator(vs4_registration_fn,void *ctx);
/* Same-source-endpoint migration: adopted socket stays net-owned. No close on
 * vs_host_close; no implicit migration without verified election certificate. */
int vs_host_adopt(int fd,const vs4_state *frozen,vs4_nonce incarnation,uint64_t term,uint64_t now_ms);
/* Internal transport entry: net owns recvfrom on adopted socket. */
int vs_host_ingest(uint64_t endpoint,const unsigned char *,size_t,uint64_t now_ms);
#endif
