#include "vs_host.h"
#include "vs_socket.h"
#include "vs_vote_policy.h"
#include "vs_vote_policy_adapter.inc"
#include <arpa/inet.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
static int seed_source(uint32_t *out,void *ctx){(void)ctx;vs4_nonce n;if(!vs4_entropy(&n))return 0;*out=(uint32_t)n.b[0]<<24|(uint32_t)n.b[1]<<16|(uint32_t)n.b[2]<<8|n.b[3];return 1;}
static struct { int fd,open,adopted,port;vs4_authority core;vs4_decision_fn decision;void *decision_ctx;vs4_registration_fn registration;void *registration_ctx;char name[17]; } H={.fd=-1};
static int bound_port(int fd) {
    struct sockaddr_in address;
    socklen_t size=sizeof address;
    return getsockname(fd,(struct sockaddr *)&address,&size)==0 ? ntohs(address.sin_port) : 0;
}
void vs_host_set_decision_validator(vs4_decision_fn f,void *ctx){H.decision=f;H.decision_ctx=ctx;if(H.open)vs4_authority_set_decision_validator(&H.core,f?f:vs4_vote_decision,ctx);}
void vs_host_set_registration_validator(vs4_registration_fn f,void *ctx){H.registration=f;H.registration_ctx=ctx;if(H.open)vs4_authority_set_registration_validator(&H.core,f,ctx);}
int vs_host_open_on(int port,const char *ip) {
    vs_host_close();
    vs4_nonce inc;
    if(!vs4_entropy(&inc))return -1;
    int fd=vs4_udp_open(port,ip);
    if(fd<0)return -1;
    H.fd=fd;
    H.open=1;
    H.port=port?port:bound_port(fd);
    if(!vs4_authority_init(&H.core,inc,vs4_now_ms(),vs4_default_policy())){
        vs_host_close();
        return -1;
    }
    H.core.catalog_required=1;
    H.core.allow_loopback_endpoints=ip&&!strncmp(ip,"127.",4);
    vs4_authority_set_decision_validator(&H.core,H.decision?H.decision:vs4_vote_decision,H.decision_ctx);
    vs4_authority_set_seed_source(&H.core,seed_source,0);
    vs4_authority_set_registration_validator(&H.core,H.registration,H.registration_ctx);
    return 0;
}
int vs_host_open(int port){return vs_host_open_on(port,"0.0.0.0");}
void vs_host_close(void){if(H.fd>=0&&!H.adopted)close(H.fd);H.fd=-1;H.open=H.adopted=H.port=0;memset(&H.core,0,sizeof H.core);}
int vs_host_is_open(void){return H.open;}
int vs_host_port(void){return H.port;}
const vs4_state *vs_host_state(void){return &H.core.state;}
int vs_host_adopt(int fd,const vs4_state *f,vs4_nonce inc,uint64_t term,uint64_t now) {
    if(fd<0||H.open||!f||f->n<2||f->n>4||f->me>=f->n)return -1;
    if(!vs4_authority_recover(&H.core,f,inc,term,now,vs4_default_policy()))return -1;
    H.fd=fd;
    H.open=H.adopted=1;
    H.port=bound_port(fd);
    H.core.catalog_required=1;
    H.core.allow_loopback_endpoints=(f->members[f->me].ipv4>>24)==127;
    vs4_authority_set_decision_validator(&H.core,H.decision?H.decision:vs4_vote_decision,H.decision_ctx);
    vs4_authority_set_seed_source(&H.core,seed_source,0);
    vs4_authority_set_registration_validator(&H.core,H.registration,H.registration_ctx);
    return 0;
}
int vs_host_ingest(uint64_t ep,const unsigned char *b,size_t n,uint64_t now){if(!H.open)return 0;
    if(vs4_discovery_request(b,n)){uint8_t out[48];vs4_discovery_offer(out,&H.core.state,H.name);vs4_udp_emit(&H.fd,ep,out,48);return 1;}
    vs4_packet p;if(!vs4_decode(&p,b,n)){
        /* No legacy parsing, mutation or relay. New clients can display this
         * rejection; old clients may ignore unknown versions. */
        if(n&&((n>=2&&!memcmp(b,"WV",2))||(n>=4&&(!memcmp(b,"RFR1",4)||!memcmp(b,"RDY1",4)))||n==VS4_NATIVE)){
            uint8_t reason=VS4_UPDATE_ALL,out[VS4_MAX_PACKET];memset(&p,0,sizeof p);p.kind=VS4_REJECT;p.incarnation=H.core.state.incarnation;p.term=H.core.state.term;p.sequence=1;p.length=1;p.body=&reason;size_t z=vs4_encode(out,sizeof out,&p);vs4_udp_emit(&H.fd,ep,out,z);
        }return -1;
    }
    if(p.kind!=VS4_JOIN&&p.kind!=VS4_COMMAND&&p.kind!=VS4_RACE)return 0;
    if(p.kind==VS4_COMMAND&&p.body[0]==VS4_BEGIN&&!H.registration){uint8_t reason=VS4_CATALOG_REQUIRED,out[VS4_MAX_PACKET];p.kind=VS4_REJECT;p.body=&reason;p.length=1;p.incarnation=H.core.state.incarnation;if(H.core.send_seq==UINT64_MAX){H.core.failed=VS4_COUNTER;return -1;}p.sequence=++H.core.send_seq;size_t z=vs4_encode(out,sizeof out,&p);vs4_udp_emit(&H.fd,ep,out,z);return 0;}
    return vs4_authority_receive(&H.core,ep,b,n,now,vs4_udp_emit,&H.fd);
}
void vs_host_poll(uint64_t now,const char *name){if(!H.open)return;if(name){size_t n=strlen(name);if(n>16)n=16;memset(H.name,0,17);memcpy(H.name,name,n);}
    if(!H.adopted)for(unsigned i=0;i<VS4_RX_BUDGET;i++){uint8_t b[VS4_MAX_PACKET];uint64_t ep;int empty;int n=vs4_udp_receive(H.fd,b,sizeof b,&ep,&empty);if(n<0){if(empty||n==-1)break;continue;}vs_host_ingest(ep,b,(size_t)n,now);}
    vs4_authority_tick(&H.core,now,vs4_udp_emit,&H.fd);
}
