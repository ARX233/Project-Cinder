#include "net.h"
#include "vs_host.h"
#include "vs_election.h"
#include "vs_socket.h"
#include <arpa/inet.h>
#include <math.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
static struct {
    int fd,drained,config_new,rejoining,hosted,cached_native;uint64_t authority,last_tx,now,config_event;
    uint8_t name[16],registration[21],race[4][VS4_NATIVE],race_new[4],last_native[VS4_NATIVE];
    vs4_client client;vs4_election election,previous_certificate;int previous_certificate_valid;vs4_state frozen;
    vs4_command pending;int pending_valid;uint64_t pending_round,pending_config;
    vs4_nonce expected_incarnation;uint64_t expected_term;
    vs4_decision_fn decision;void *decision_ctx;vs4_registration_fn registration_validator;void *registration_ctx;
} N={.fd=-1};
static void send_packet(const uint8_t *b,size_t n){if(N.fd>=0&&n)vs4_udp_emit(&N.fd,N.authority,b,n);}
static void join(void){uint8_t identity[19],out[VS4_MAX_PACKET];memcpy(identity,N.registration,3);memcpy(identity+3,N.registration+5,16);size_t n=vs4_client_join(&N.client,out,sizeof out,N.name,identity,N.registration[3],N.registration[4]);send_packet(out,n);}
static int done(const vs4_command *c){const vs4_state *s=&N.client.view;unsigned bit=1u<<s->me;switch(c->op){case VS4_BEGIN:return s->phase!=VS4_ROOM;case VS4_PHASE_READY:return s->phase!=c->target||(s->ready&bit);case VS4_CHOICE:return s->phase!=c->target||((s->ready&bit)&&s->members[s->me].choice==c->value);case VS4_ADVANCE:return s->phase>=c->target;case VS4_TUNE_READY:return (s->tuned&bit)!=0;case VS4_LOAD_READY:return (s->loaded&bit)!=0;case VS4_FINISH:return (s->finished&bit)!=0;case VS4_DONE:return s->phase==VS4_ROOM;case VS4_CANCEL:return s->phase==VS4_ABORTING;default:return 0;}}
static int command_send(const vs4_command *c){uint8_t b[VS4_MAX_PACKET];size_t n=vs4_client_command(&N.client,b,sizeof b,c);send_packet(b,n);return n!=0;}
int net_open(const char *host,int port,uint32_t id,const char name[16],const unsigned char registration[21]){
    net_close();if(!host||!name||!registration||!vs4_registration_valid(registration)||(N.registration_validator&&!N.registration_validator(registration,N.registration_ctx))||port<1||port>65535)return -1;
    struct sockaddr_in a;memset(&a,0,sizeof a);a.sin_family=AF_INET;a.sin_port=htons((uint16_t)port);if(inet_pton(AF_INET,host,&a.sin_addr)!=1)return -1;vs4_nonce nonce;if(!vs4_entropy(&nonce))return -1;
    int loop=(ntohl(a.sin_addr.s_addr)>>24)==127;int fd=vs4_udp_open(0,loop?"127.0.0.1":"0.0.0.0");if(fd<0)return -1;N.fd=fd;N.authority=vs4_endpoint(&a);N.now=vs4_now_ms();if(!vs4_client_init(&N.client,id,nonce,N.now,vs4_default_policy())){net_close();return -1;}memcpy(N.name,name,16);memcpy(N.registration,registration,21);N.last_tx=0;return 0;
}
void net_close(void){if(N.fd>=0){if(N.client.joined){vs4_command c;memset(&c,0,sizeof c);c.op=VS4_QUIT;command_send(&c);}if(N.hosted)vs_host_close();close(N.fd);}vs4_decision_fn f=N.decision;void *ctx=N.decision_ctx;vs4_registration_fn validator=N.registration_validator;void *registration_ctx=N.registration_ctx;memset(&N,0,sizeof N);N.fd=-1;N.decision=f;N.decision_ctx=ctx;N.registration_validator=validator;N.registration_ctx=registration_ctx;}
int net_is_open(void){return N.fd>=0;}
const vs4_client *net_session(void){return &N.client;}
const vs4_state *net_state(void){return &N.client.view;}
void net_set_decision_validator(vs4_decision_fn f,void *ctx){N.decision=f;N.decision_ctx=ctx;vs_host_set_decision_validator(f,ctx);}
void net_set_registration_validator(vs4_registration_fn f,void *ctx){N.registration_validator=f;N.registration_ctx=ctx;vs_host_set_registration_validator(f,ctx);}
int net_receive_drained(void){return N.fd>=0&&N.drained;}
static const vs4_state *local_authority(void){if(!vs_host_is_open()||!N.client.joined)return NULL;const vs4_state *s=vs_host_state();if(!vs4_nonce_equal(s->incarnation,N.client.view.incarnation))return NULL;if(N.hosted||(((uint32_t)(N.authority>>16)>>24)==127&&(int)(N.authority&65535u)==vs_host_port()))return s;return NULL;}
static void latch_local_abort(void){const vs4_state *s=local_authority();if(s&&s->phase==VS4_ABORTING&&s->round==N.client.view.round&&N.client.view.phase>=VS4_MATCH&&N.client.view.phase<=VS4_RESULTS&&!N.client.stop){vs4_client_cancel(&N.client);N.client.reason=s->reason;N.pending_valid=N.cached_native=N.config_new=0;memset(N.race_new,0,sizeof N.race_new);}}
int net_native_allowed(void){if(N.fd<0||!N.drained||!vs4_client_native_allowed(&N.client))return 0;const vs4_state *s=local_authority();return !s||(s->phase==VS4_RUNNING&&s->round==N.client.view.round&&s->config==N.client.view.config);}
const char *net_error_message(void){switch(N.client.reason){case VS4_UPDATE_ALL:return VS4_UPDATE_MESSAGE;case VS4_CATALOG_REQUIRED:return "Room server needs a reviewed CinderVS4 car catalog before starting";case VS4_AUTHORITY_LOST:return "Host lost: recovering shared room; no race until original-roster quorum rejoins";case VS4_RACE_SILENT:return "Race transport stopped: round cancelled for all participants";case VS4_FULL:return "Room full or session admission capacity reached; create a new room";case VS4_BUSY:return "Room is finishing/cancelling a round; wait and rejoin";case VS4_IDENTITY:return "Session identity changed: reconnect with a fresh session";case VS4_RANGE:return "Invalid car/tuning profile; update all clients";case VS4_CLOCK:return "Monotonic clock fault: leave and rejoin the room";default:return N.client.stop?"Round cancelled; returning to shared room":"";}}
int net_command(const vs4_command *cmd){if(N.fd<0||!cmd||cmd->op==VS4_TUNE_DRAFT||!N.client.joined||N.client.authority_lost)return 0;if(N.pending_valid&&!done(&N.pending))return 0;N.pending=*cmd;N.pending.event=N.client.view.event;N.pending_round=N.client.view.round;N.pending_config=N.client.view.config;N.pending_valid=1;if(!command_send(&N.pending)){N.pending_valid=0;return 0;}return 1;}
static int op(unsigned op){vs4_command c;memset(&c,0,sizeof c);c.op=(uint8_t)op;return net_command(&c);}
int net_tune_ready(const unsigned char p[21]){if(!p)return 0;vs4_command c;memset(&c,0,sizeof c);c.op=VS4_TUNE_READY;memcpy(c.profile,p,21);return net_command(&c);}
int net_tune_draft(const unsigned char p[21]){
    if(N.fd<0||!p||!N.client.joined||(N.pending_valid&&N.pending.op==VS4_TUNE_READY))return 0;
    vs4_command c={.op=VS4_TUNE_DRAFT};
    memcpy(c.profile,p,21);
    return command_send(&c);
}
int net_load_ready(void){return op(VS4_LOAD_READY);}int net_finish(void){return op(VS4_FINISH);}int net_done(void){return op(VS4_DONE);}
void net_cancel(void){if(N.fd<0)return;N.pending_valid=0;vs4_client_cancel(&N.client);(void)op(VS4_CANCEL);}
void net_teardown_done(void){vs4_client_teardown_done(&N.client);}
void net_race_send(const unsigned char *p,int len){if(N.fd<0||len!=VS4_NATIVE||!p||!N.client.joined||N.client.stop||N.client.view.phase!=VS4_RUNNING)return;memcpy(N.last_native,p,VS4_NATIVE);N.cached_native=1;uint8_t out[VS4_MAX_PACKET];size_t n=vs4_client_race(&N.client,out,sizeof out,p);send_packet(out,n);}
int net_take_race(int pcb,unsigned char out[VS4_NATIVE]){if(pcb<0||pcb>=4||!out||!net_native_allowed()||!N.race_new[pcb])return 0;memcpy(out,N.race[pcb],VS4_NATIVE);N.race_new[pcb]=0;return 1;}
int net_take_config(vs4_state *out){if(!out||!N.config_new||N.client.stop)return 0;*out=N.client.view;N.config_new=0;return 1;}
static void migration(uint64_t now){
    if(!N.election.committed||N.rejoining||!N.client.stop||!N.client.teardown)return;
    unsigned candidate=N.election.candidate;uint64_t endpoint=vs4_member_endpoint(&N.election.frozen.members[candidate]);if(!endpoint)return;
    if(candidate==N.election.me){vs_host_set_decision_validator(N.decision,N.decision_ctx);if(vs_host_adopt(N.fd,&N.election.frozen,N.election.proposal,N.election.term,now))return;N.rejoining=2;N.hosted=1;}else N.rejoining=1;
    /* No stale session/epoch reused after reconnect. Keep old election identity
     * solely in sealed certificate state for bounded vote/commit retries. */
    vs4_nonce nonce;if(!vs4_entropy(&nonce)){N.client.reason=VS4_COUNTER;return;}uint32_t id=N.client.id;vs4_client_init(&N.client,id,nonce,now,vs4_default_policy());N.expected_incarnation=N.election.proposal;N.expected_term=N.election.term;N.authority=endpoint;N.pending_valid=0;N.config_new=0;memset(N.race_new,0,sizeof N.race_new);join();N.last_tx=now;
}
void net_poll(uint64_t now){if(N.fd<0)return;N.now=now;N.drained=0;
    for(unsigned work=0;work<VS4_RX_BUDGET;work++){
        uint8_t b[VS4_MAX_PACKET];uint64_t source;int empty,n=vs4_udp_receive(N.fd,b,sizeof b,&source,&empty);if(n<0){if(empty)N.drained=1;if(n==-2)continue;break;}
        vs4_packet p;int valid=vs4_decode(&p,b,(size_t)n);
        if(valid&&p.kind>=VS4_REQUEST_VOTE){if(N.previous_certificate_valid&&vs4_nonce_equal(p.incarnation,N.previous_certificate.frozen.incarnation))vs4_election_receive(&N.previous_certificate,source,b,(size_t)n,now,vs4_udp_emit,&N.fd);else vs4_election_receive(&N.election,source,b,(size_t)n,now,vs4_udp_emit,&N.fd);continue;}
        if(N.hosted&&valid&&(p.kind==VS4_JOIN||p.kind==VS4_COMMAND||(p.kind==VS4_RACE&&(source!=N.authority||(p.id==N.client.id&&vs4_nonce_equal(p.session,N.client.session)))))){vs_host_ingest(source,b,(size_t)n,now);continue;}
        if(source!=N.authority)continue;
        if(valid&&p.kind==VS4_STATE&&N.rejoining&&(!vs4_nonce_equal(p.incarnation,N.expected_incarnation)||p.term!=N.expected_term))continue;
        uint8_t previous=N.client.view.phase;int accepted=vs4_client_receive(&N.client,b,(size_t)n,now);
        if(accepted&&valid&&p.kind==VS4_RACE){for(unsigned i=0;i<N.client.view.n;i++)if(N.client.view.members[i].id==p.id){memcpy(N.race[i],p.body,VS4_NATIVE);N.race_new[i]=1;}}
        if(accepted&&valid&&p.kind==VS4_STATE){
            const vs4_state *s=&N.client.view;
            if(s->phase==VS4_MATCH&&(previous!=VS4_MATCH||s->round!=N.frozen.round)){if(N.election.committed){N.previous_certificate=N.election;N.previous_certificate_valid=1;}N.frozen=*s;N.rejoining=0;vs4_election_init(&N.election,s,s->me,now);}
            vs4_election_lease(&N.election,now,N.client.policy.control_ms);
            if(s->phase==VS4_LOAD&&N.config_event!=s->event){N.config_event=s->event;N.config_new=1;}
            if(N.pending_valid&&(done(&N.pending)||s->round!=N.pending_round||s->config!=N.pending_config))N.pending_valid=0;
        }
    }
    latch_local_abort();
    vs4_client_tick(&N.client,now);
    if(N.client.stop){N.cached_native=0;N.config_new=0;memset(N.race_new,0,sizeof N.race_new);}
    /* A local race-plane timeout must become shared terminal cancellation. */
    if(N.client.stop&&!N.client.authority_lost&&N.client.view.phase!=VS4_ABORTING&&N.client.view.phase!=VS4_ROOM){N.pending_valid=0;vs4_command c;memset(&c,0,sizeof c);c.op=VS4_CANCEL;N.pending=c;N.pending_valid=1;N.pending_round=N.client.view.round;N.pending_config=N.client.view.config;}
    if(N.client.authority_lost&&N.election.enabled){vs4_nonce nonce;memset(&nonce,0,sizeof nonce);if(N.election.me==N.election.candidate&&!vs4_nonce_nonzero(N.election.proposal))vs4_entropy(&nonce);vs4_election_tick(&N.election,now,nonce,vs4_udp_emit,&N.fd);migration(now);}
    /* Retain one bounded previous sealed certificate across subsequent rounds.
     * A late reachable old peer can learn the elected incarnation and freshly
     * handshake at the next ROOM; no stale certificate authorizes a current GO. */
    if(N.rejoining&&N.election.committed){vs4_nonce zero={{0}};vs4_election_tick(&N.election,now,zero,vs4_udp_emit,&N.fd);}
    if(N.previous_certificate_valid){vs4_nonce zero={{0}};vs4_election_tick(&N.previous_certificate,now,zero,vs4_udp_emit,&N.fd);}
    if(now-N.last_tx>=N.client.policy.retry_ms){N.last_tx=now;if(!N.client.joined)join();else {vs4_command ack;memset(&ack,0,sizeof ack);ack.op=VS4_ACK;command_send(&ack);if(N.pending_valid)command_send(&N.pending);if(N.cached_native&&N.client.view.phase==VS4_RUNNING&&N.client.paused){uint8_t out[VS4_MAX_PACKET];size_t n=vs4_client_race(&N.client,out,sizeof out,N.last_native);send_packet(out,n);}}}
    if(N.hosted)vs_host_poll(now,"Recovered CinderVS4 room");
    latch_local_abort();
}
/* Strict discovery is isolated from active VS profiles/packets and Ghost. */
static struct {int fd,n,bad;double last;net_found found[NET_FOUND];uint64_t target;} S={.fd=-1};
void net_scan_target(const char *ip,int port){S.target=0;if(!ip||port<1||port>65535)return;struct sockaddr_in a;memset(&a,0,sizeof a);a.sin_family=AF_INET;a.sin_port=htons((uint16_t)port);if(inet_pton(AF_INET,ip,&a.sin_addr)==1)S.target=vs4_endpoint(&a);}
void net_scan(double now,int on){if(!on){if(S.fd>=0)close(S.fd);S.fd=-1;S.n=S.bad=0;S.last=0;return;}if(!isfinite(now)||now<0)return;if(S.fd<0){S.fd=vs4_udp_open(0,"0.0.0.0");if(S.fd<0)return;int one=1;setsockopt(S.fd,SOL_SOCKET,SO_BROADCAST,&one,sizeof one);S.last=-1e9;}
    for(unsigned i=0;i<VS4_RX_BUDGET;i++){uint8_t b[VS4_MAX_PACKET];uint64_t ep;int empty,n=vs4_udp_receive(S.fd,b,sizeof b,&ep,&empty);if(n<0){if(n==-2)continue;break;}if(n!=48||memcmp(b,"WVS4",4)||b[4]!=4||b[5]!=33||b[6]>4||b[7]||b[44]>VS4_ABORTING||b[45]||b[46]||b[47]){if(n>=3&&!memcmp(b,"WV",2))S.bad=1;continue;}vs4_nonce inc;memcpy(inc.b,b+8,16);if(!vs4_nonce_nonzero(inc))continue;int k=0;while(k<S.n&&!vs4_nonce_equal(S.found[k].incarnation,inc))k++;if(k==S.n){if(S.n==NET_FOUND)continue;S.n++;}net_found *f=&S.found[k];memset(f,0,sizeof *f);struct sockaddr_in a=vs4_sockaddr(ep);inet_ntop(AF_INET,&a.sin_addr,f->ip,sizeof f->ip);memcpy(f->name,b+24,16);f->incarnation=inc;f->n=b[6];f->seen=now;f->id=(uint32_t)b[40]<<24|(uint32_t)b[41]<<16|(uint32_t)b[42]<<8|b[43];}
    for(int i=S.n-1;i>=0;i--)if(now<S.found[i].seen||now-S.found[i].seen>4){memmove(&S.found[i],&S.found[i+1],sizeof S.found[0]*(size_t)(S.n-i-1));S.n--;}
    if(now-S.last<1)return;S.last=now;static const uint8_t request[8]={'W','V','S','4',4,32,0,0};uint64_t ep=S.target?S.target:((uint64_t)UINT32_MAX<<16)|NET_PORT;vs4_udp_emit(&S.fd,ep,request,8);if(!S.target)vs4_udp_emit(&S.fd,((uint64_t)UINT32_C(0x7f000001)<<16)|NET_PORT,request,8);
}
int net_found_list(net_found *out,int max){if(!out||max<0)return 0;int n=S.n<max?S.n:max;memcpy(out,S.found,(size_t)n*sizeof *out);return n;}
int net_scan_incompatible(void){return S.bad;}
