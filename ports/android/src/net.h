/* CinderVS4-only UDP adapter. No WV1/raw/profile extension compatibility. */
#ifndef NET_H
#define NET_H
#include "vs_session.h"
#define NET_PORT 27015
#define NET_PLAYERS VS4_PLAYERS
#define NET_NAME 16
#define NET_PROFILE VS4_PROFILE
#define NET_FOUND 4
typedef vs4_member net_player;
typedef struct { char ip[16], name[17]; uint32_t id; int n; double seen; vs4_nonce incarnation; } net_found;
/* Fresh OS entropy is mandatory. registration is exact21, marker'C',4,
 * baseline P/H and immutable car/name/title/dress. Binding socket remains the
 * same across source-bound election; reconnect uses a fresh session nonce. */
int net_open(const char *host,int port,uint32_t id,const char name[16],const unsigned char registration[21]);
void net_close(void);
int net_is_open(void);
/* Time is monotonic milliseconds, not historical double seconds. Bounded64 RX.
 * Retry JOIN/ACK/pending command every100ms. Abort is sticky; ACK after teardown.
 * No background thread or native execution. */
void net_poll(uint64_t now_ms);
const vs4_client *net_session(void);
const vs4_state *net_state(void);
int net_command(const vs4_command *command);
int net_tune_ready(const unsigned char profile[21]);
/* Best-effort current tune. Never displaces a reliable READY. */
int net_tune_draft(const unsigned char profile[21]);
int net_load_ready(void);
int net_finish(void);
int net_done(void);
void net_cancel(void);
void net_teardown_done(void);
int net_native_allowed(void);
int net_receive_drained(void);
const char *net_error_message(void);
void net_race_send(const unsigned char *packet,int exact_len);
int net_take_race(int pcb,unsigned char out[VS4_NATIVE]);
/* Policy hooks are parent/original-flow supplied; no host-personal vote fallback.
 * Every embedded/recovered authority receives this validator. */
void net_set_decision_validator(vs4_decision_fn,void *ctx);
void net_set_registration_validator(vs4_registration_fn,void *ctx);
/* Returns1 once for a new accepted LOAD configuration; snapshot borrowed until
 * next poll. Finalized profiles and registered base_power/handling are separate. */
int net_take_config(vs4_state *out);
/* Discovery keeps its historical seconds clock for UI call convenience. Strict
 * WVS4 replies only; incompatible legacy offers produce update notice only. */
void net_scan(double now_seconds,int on);
int net_found_list(net_found *out,int max);
int net_scan_incompatible(void);
/* Test/desktop harness only: override advertised discovery destination; no
 * deployment is performed by tests. Port0 disables extra target. */
void net_scan_target(const char *ipv4,int port);
#endif
