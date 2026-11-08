#include "vs_session.h"
#include <string.h>
#include <limits.h>
static uint16_t u16(const uint8_t *p) { return (uint16_t)((uint16_t)p[0]<<8|p[1]); }
static uint32_t u32(const uint8_t *p) { return (uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3]; }
static uint64_t u64(const uint8_t *p) { return (uint64_t)u32(p)<<32|u32(p+4); }
static void p16(uint8_t *p,uint16_t x) { p[0]=(uint8_t)(x>>8);p[1]=(uint8_t)x; }
static void p32(uint8_t *p,uint32_t x) { p[0]=(uint8_t)(x>>24);p[1]=(uint8_t)(x>>16);p[2]=(uint8_t)(x>>8);p[3]=(uint8_t)x; }
static void p64(uint8_t *p,uint64_t x) { p32(p,(uint32_t)(x>>32));p32(p+4,(uint32_t)x); }
static int zero(const uint8_t *p,size_t n) { uint8_t x=0;for(size_t i=0;i<n;i++)x|=p[i];return !x; }
int vs4_nonce_equal(vs4_nonce a,vs4_nonce b) { return !memcmp(a.b,b.b,16); }
int vs4_nonce_nonzero(vs4_nonce a) { return !zero(a.b,16); }
vs4_policy vs4_default_policy(void) { vs4_policy p={6000,4500,1500,100,1000,90000};return p; }
static int policy_valid(vs4_policy p) { return p.control_ms&&p.race_ms&&p.finish_grace_ms<=60000&&p.retry_ms&&p.retry_ms<=p.control_ms&&p.soft_ms&&p.soft_ms<p.race_ms&&p.stage_ms; }
int vs4_decode(vs4_packet *out,const uint8_t *b,size_t n) {
    if(!out||!b||n<VS4_HEADER||n>VS4_MAX_PACKET||memcmp(b,"WVS4",4)||b[4]!=4||b[5]<1||b[5]>8||u16(b+6)!=VS4_HEADER||u16(b+8)!=n-VS4_HEADER||!zero(b+10,2))return 0;
    vs4_packet p;memset(&p,0,sizeof p);p.kind=b[5];p.length=u16(b+8);p.body=b+VS4_HEADER;
    memcpy(p.incarnation.b,b+12,16);p.membership=u64(b+28);p.round=u64(b+36);p.config=u64(b+44);
    p.id=u32(b+52);memcpy(p.session.b,b+56,16);p.sequence=u64(b+72);p.term=u64(b+80);
    if(!p.sequence)return 0;
    if((p.kind==VS4_JOIN&&p.length!=40)||(p.kind==VS4_COMMAND&&p.length!=40)||(p.kind==VS4_RACE&&p.length!=VS4_NATIVE)||(p.kind==VS4_REJECT&&p.length!=1)||(p.kind==VS4_STATE&&(p.length<VS4_STATE_BASE+VS4_MEMBER||p.length>VS4_STATE_BASE+VS4_PLAYERS*VS4_MEMBER))||(p.kind>=VS4_REQUEST_VOTE&&p.length!=20))return 0;
    *out=p;return 1;
}
size_t vs4_encode(uint8_t *b,size_t cap,const vs4_packet *p) {
    if(!b||!p||!p->sequence||p->kind<1||p->kind>8||cap<VS4_HEADER+p->length||VS4_HEADER+p->length>VS4_MAX_PACKET||(!p->body&&p->length))return 0;
    memset(b,0,VS4_HEADER);memcpy(b,"WVS4",4);b[4]=4;b[5]=p->kind;p16(b+6,VS4_HEADER);p16(b+8,p->length);
    memcpy(b+12,p->incarnation.b,16);p64(b+28,p->membership);p64(b+36,p->round);p64(b+44,p->config);p32(b+52,p->id);memcpy(b+56,p->session.b,16);p64(b+72,p->sequence);p64(b+80,p->term);
    if(p->length)memcpy(b+VS4_HEADER,p->body,p->length);return VS4_HEADER+p->length;
}
static int budget_valid(unsigned p,unsigned h){unsigned total=p+h;return p<=24&&h<=24&&total<=34&&(total<=20?(p<=10&&h<=10):(p>=10&&h>=10));}
static int identity_valid(const uint8_t *p){if(!p||p[17]!='C'||p[18]!=4||p[9]>127||p[10]>3||p[11]>1||p[12]>4||p[13]>3||p[15]>12||p[16]>=100)return 0;int ended=0;for(unsigned i=3;i<8;i++){if(ended&&p[i]!=255)return 0;if(p[i]==255)ended=1;}return 1;}
int vs4_registration_valid(const uint8_t *p){if(!p||!budget_valid(p[3],p[4]))return 0;uint8_t identity[19];memcpy(identity,p,3);memcpy(identity+3,p+5,16);return identity_valid(identity);}
int vs4_profile_valid(const vs4_member *m,const uint8_t *p) {
    /* Profile schema1 is exact21, not a legacy fallback. Build bytes are carried
     * as appearance/schema data; integration validates actual car/cosmetic IDs. */
    if(!m||!p||!vs4_registration_valid(p)||p[19]!='C'||p[20]!=4||p[0]!=m->maker||p[1]!=m->car||p[3]>24||p[4]>24||(unsigned)p[3]+p[4]!=m->budget||m->budget>34)return 0;
    if(m->budget<=20?(p[3]!=m->base_power||p[4]!=m->base_handling):(p[3]<10||p[4]<10))return 0;
    uint8_t identity[19];memcpy(identity,p,3);memcpy(identity+3,p+5,16);return !memcmp(identity,m->identity,19);
}
static int state_valid(const vs4_state *s) {
    if(!s||!vs4_nonce_nonzero(s->incarnation)||!s->membership||!s->term||!s->config||!s->event||s->phase>VS4_ROOM_VIEW||!s->n||s->n>4||s->me>=s->n||s->owner>=s->n||s->ramp>=22||s->km<1||s->km>100||s->zone>1)return 0;
    unsigned all=(1u<<s->n)-1, masks=s->ready|s->tuned|s->loaded|s->finished|s->done|s->abort_ack|s->state_ack;
    if(masks&~all)return 0;
    if(s->phase!=VS4_ROOM&&!s->round)return 0;
    if(s->phase==VS4_TUNE&&s->tune_remaining_ms>VS4_TUNE_MS&&s->tune_remaining_ms!=VS4_TUNE_UNKNOWN)return 0;
    if(s->phase>=VS4_MATCH&&s->phase<=VS4_RESULTS&&(s->song<1||s->song>22||s->song==2))return 0;
    if(s->phase==VS4_ABORTING&&(!s->aborted_round||!s->reason))return 0;
    if(s->phase==VS4_ROOM&&(s->ready||s->tuned||s->loaded||s->finished||s->done||s->abort_ack))return 0;
    if(s->phase>=VS4_LOAD&&s->phase<=VS4_RESULTS&&s->tuned!=all)return 0;
    if(s->phase>=VS4_RUNNING&&s->phase<=VS4_RESULTS&&s->loaded!=all)return 0;
    if(s->phase==VS4_RESULTS&&s->finished!=all)return 0;
    if((s->loaded&~s->tuned)||(s->done&~s->finished))return 0;
    for(unsigned i=0;i<s->n;i++) {
        const vs4_member *m=&s->members[i];
        if(!m->id||!vs4_nonce_nonzero(m->session)||m->live>1||m->identity[0]!=m->maker||m->identity[1]!=m->car||m->identity[17]!='C'||m->identity[18]!=4||m->budget>34||!identity_valid(m->identity)||!budget_valid(m->base_power,m->base_handling)||(unsigned)m->base_power+m->base_handling!=m->budget)return 0;
        if(s->phase!=VS4_ABORTING&&!m->live)return 0;
        if((s->phase==VS4_MAP||s->phase==VS4_TIME)&&(s->ready&(1u<<i))&&(m->choice==65535||(s->phase==VS4_TIME?m->choice>1:(m->choice&~0x87u))))return 0;
        if((s->tuned&(1u<<i))&&!vs4_profile_valid(m,m->profile))return 0;
        if(!(s->tuned&(1u<<i))&&!zero(m->profile,VS4_PROFILE))return 0;
        for(unsigned j=0;j<i;j++)if(m->id==s->members[j].id||vs4_nonce_equal(m->session,s->members[j].session))return 0;
    }
    return 1;
}
int vs4_state_decode(vs4_state *out,const vs4_packet *p) {
    if(!out||!p||p->kind!=VS4_STATE||p->length<VS4_STATE_BASE)return 0;
    const uint8_t *b=p->body;vs4_state s;memset(&s,0,sizeof s);
    s.incarnation=p->incarnation;s.membership=p->membership;s.round=p->round;s.config=p->config;s.term=p->term;s.event=u64(b);s.aborted_round=u64(b+8);
    s.phase=b[16];s.n=b[17];s.me=b[18];s.owner=b[19];s.ready=b[20];s.tuned=b[21];s.loaded=b[22];s.finished=b[23];s.done=b[24];s.abort_ack=b[25];s.reason=b[26];s.state_ack=b[27];s.ramp=b[28];s.km=b[29];s.song=b[30];s.zone=b[31];s.seed=u32(b+32);
    if(s.n>4||p->length!=VS4_STATE_BASE+s.n*VS4_MEMBER)return 0;
    s.tune_remaining_ms=VS4_TUNE_UNKNOWN;
    for(unsigned i=0;i<s.n;i++) {
        b=p->body+VS4_STATE_BASE+i*VS4_MEMBER;vs4_member *m=&s.members[i];m->id=u32(b);memcpy(m->session.b,b+4,16);memcpy(m->name,b+20,16);m->maker=b[36];m->car=b[37];m->budget=b[38];m->live=b[39];memcpy(m->profile,b+40,21);m->choice=u16(b+61);m->base_power=b[63];m->base_handling=b[64];m->ipv4=u32(b+65);m->port=u16(b+69);memcpy(m->identity,b+72,19);if(b[71]||!zero(b+91,5))return 0;
        if(s.phase==VS4_TUNE&&!i){s.tune_remaining_ms=m->choice;m->choice=UINT16_MAX;}
    }
    if(!state_valid(&s)||p->id!=s.members[s.me].id||!vs4_nonce_equal(p->session,s.members[s.me].session))return 0;
    *out=s;return 1;
}
size_t vs4_state_encode(uint8_t *b,size_t cap,const vs4_state *s) {
    if(!s)return 0;size_t n=VS4_STATE_BASE+s->n*VS4_MEMBER;if(!b||cap<n||!state_valid(s))return 0;
    memset(b,0,n);p64(b,s->event);p64(b+8,s->aborted_round);b[16]=s->phase;b[17]=s->n;b[18]=s->me;b[19]=s->owner;b[20]=s->ready;b[21]=s->tuned;b[22]=s->loaded;b[23]=s->finished;b[24]=s->done;b[25]=s->abort_ack;b[26]=s->reason;b[27]=s->state_ack;b[28]=s->ramp;b[29]=s->km;b[30]=s->song;b[31]=s->zone;p32(b+32,s->seed);
    for(unsigned i=0;i<s->n;i++) { uint8_t *q=b+VS4_STATE_BASE+i*VS4_MEMBER;const vs4_member *m=&s->members[i];p32(q,m->id);memcpy(q+4,m->session.b,16);memcpy(q+20,m->name,16);q[36]=m->maker;q[37]=m->car;q[38]=m->budget;q[39]=m->live;memcpy(q+40,m->profile,21);p16(q+61,s->phase==VS4_TUNE&&!i?s->tune_remaining_ms:m->choice);q[63]=m->base_power;q[64]=m->base_handling;p32(q+65,m->ipv4);p16(q+69,m->port);memcpy(q+72,m->identity,19); }
    return n;
}
void vs4_command_encode(uint8_t *b,const vs4_command *c) { memset(b,0,40);b[0]=c->op;b[1]=c->target;p16(b+2,c->value);p64(b+4,c->event);b[12]=c->ramp;b[13]=c->km;b[14]=c->song;b[15]=c->zone;memcpy(b+16,c->profile,21); }
int vs4_command_decode(vs4_command *out,const vs4_packet *p) {
    if(!out||!p||p->kind!=VS4_COMMAND||p->length!=40)return 0;
    const uint8_t *b=p->body;vs4_command c;memset(&c,0,sizeof c);c.op=b[0];c.target=b[1];c.value=u16(b+2);c.event=u64(b+4);c.ramp=b[12];c.km=b[13];c.song=b[14];c.zone=b[15];memcpy(c.profile,b+16,21);
    if(c.op<1||c.op>VS4_TUNE_DRAFT||!c.event||!zero(b+37,3))return 0;
    if(c.op!=VS4_ADVANCE&&c.op!=VS4_BEGIN&&!zero(b+12,4))return 0;
    if(c.op!=VS4_TUNE_READY&&c.op!=VS4_TUNE_DRAFT&&!zero(b+16,21))return 0;
    if(c.op!=VS4_CHOICE&&c.value)return 0;
    if(c.op!=VS4_ADVANCE&&c.op!=VS4_PHASE_READY&&c.op!=VS4_CHOICE&&c.op!=VS4_BEGIN&&c.target)return 0;
    *out=c;return 1;
}
static int scope(const vs4_state *s,const vs4_packet *p) { return vs4_nonce_equal(s->incarnation,p->incarnation)&&s->membership==p->membership&&s->round==p->round&&s->config==p->config&&s->term==p->term; }
static void client_stop(vs4_client *c,uint8_t reason) { if(!c->stop)c->teardown=0;c->stop=1;if(!c->reason)c->reason=reason; }
int vs4_client_init(vs4_client *c,uint32_t id,vs4_nonce nonce,uint64_t now,vs4_policy p) {
    if(!c)return 0;memset(c,0,sizeof *c);if(!id||!vs4_nonce_nonzero(nonce)||!policy_valid(p))return 0;
    c->id=id;c->session=nonce;c->clock=c->heard=now;c->policy=p;c->view.tune_remaining_ms=VS4_TUNE_UNKNOWN;return 1;
}
void vs4_client_cancel(vs4_client *c) { if(c)client_stop(c,VS4_LOCAL_CANCEL); }
void vs4_client_teardown_done(vs4_client *c) { if(c&&c->stop)c->teardown=1; }
int vs4_client_native_allowed(const vs4_client *c) { return c&&c->joined&&!c->stop&&!c->authority_lost&&c->view.phase==VS4_RUNNING&&!c->paused&&c->local_finished_round!=c->view.round; }
int vs4_client_receive(vs4_client *c,const uint8_t *b,size_t n,uint64_t now) {
    if(!c)return -1;if(now<c->clock){client_stop(c,VS4_CLOCK);return -1;}c->clock=now;
    vs4_packet p;if(!vs4_decode(&p,b,n)) { if(b&&n>=3&&(!memcmp(b,"WV",2)||!memcmp(b,"RFR",3)||!memcmp(b,"RDY",3))){c->reason=VS4_UPDATE_ALL;}return -1; }
    if(p.kind==VS4_REJECT) { if(((p.id==c->id&&vs4_nonce_equal(p.session,c->session))||(!p.id&&!vs4_nonce_nonzero(p.session)&&p.body[0]==VS4_UPDATE_ALL))&&p.body[0]>=1&&p.body[0]<=15)c->reason=p.body[0];return 0; }
    if(p.kind==VS4_STATE) {
        vs4_state s;if(!vs4_state_decode(&s,&p))return -1;
        if(p.id!=c->id||!vs4_nonce_equal(p.session,c->session))return 0;
        if(c->authority_lost)return 0; /* explicit reconnect init required */
        if(!c->joined) { if(s.phase!=VS4_ROOM&&s.phase!=VS4_ROOM_VIEW)return 0;c->reason=0; }
        else {
            if(s.term!=c->view.term||!vs4_nonce_equal(s.incarnation,c->view.incarnation)||p.sequence<=c->state_seq||s.event<c->view.event||s.membership<c->view.membership||s.round<c->view.round||s.config<c->view.config)return 0;
            if(s.event==c->view.event&&(s.phase!=c->view.phase||s.membership!=c->view.membership||s.round!=c->view.round||s.config!=c->view.config))return -1;
            /* A skipped abort/normal-complete event cannot authorize a later GO. */
            if(s.round>c->view.round&&c->view.phase!=VS4_ROOM)return 0;
            if(s.phase>=VS4_MATCH&&s.phase<=VS4_RESULTS&&c->view.phase!=VS4_ROOM) {
                if(s.n!=c->view.n)return -1;
                for(unsigned i=0;i<s.n;i++)if(s.members[i].id!=c->view.members[i].id||!vs4_nonce_equal(s.members[i].session,c->view.members[i].session))return -1;
            }
        }
        if(s.phase==VS4_RUNNING&&(c->local_loaded_round!=s.round||c->local_loaded_config!=s.config||!c->profile_confirmed||memcmp(c->own_profile,s.members[s.me].profile,21)))return 0;
        int fresh_round=s.round!=c->view.round;
        int tuning=s.phase==VS4_TUNE||s.phase==VS4_LOAD;
        if(tuning&&!fresh_round) {
            if(c->view.tuned&~s.tuned)return -1;
            for(unsigned i=0;i<s.n;i++)
                if((c->view.tuned&(1u<<i))&&memcmp(c->view.members[i].profile,s.members[i].profile,VS4_PROFILE))return -1;
        }
        if(s.phase!=c->view.phase||s.event!=c->view.event)c->phase_since=now;
        if(fresh_round) { memset(c->race_seq,0,sizeof c->race_seq);c->native_seen=0;c->local_loaded_round=c->local_finished_round=0;c->local_loaded_config=0;c->profile_confirmed=0; }
        if(tuning&&(s.tuned&(1u<<s.me))) {
            /* The authority also confirms a draft/default when READY never arrived. */
            memcpy(c->own_profile,s.members[s.me].profile,VS4_PROFILE);c->profile_confirmed=1;
        }
        if(s.phase==VS4_RUNNING&&c->view.phase!=VS4_RUNNING)for(unsigned i=0;i<s.n;i++)c->race_heard[i]=now;
        if(s.phase==VS4_ABORTING) { if(!c->stop)client_stop(c,s.reason); }
        if(s.phase==VS4_ROOM&&c->stop) {
            if(!c->teardown)return 0;
            c->stop=c->teardown=0;c->reason=0;c->profile_confirmed=0;
        }
        c->view=s;c->joined=1;c->state_seq=p.sequence;c->heard=now;return 1;
    }
    if(p.kind==VS4_RACE&&c->joined&&!c->stop&&c->view.phase==VS4_RUNNING&&scope(&c->view,&p)) {
        for(unsigned i=0;i<c->view.n;i++)if(c->view.members[i].id==p.id&&vs4_nonce_equal(c->view.members[i].session,p.session)&&i!=c->view.me) {
            uint32_t count=(uint32_t)p.body[0x34]|(uint32_t)p.body[0x35]<<8|(uint32_t)p.body[0x36]<<16|(uint32_t)p.body[0x37]<<24;uint32_t delta=count-c->native_count[i];
            if(p.sequence<=c->race_seq[i]||(c->view.finished&(1u<<i))||((c->native_seen&(1u<<i))&&(!delta||delta>=UINT32_C(0x80000000))))return 0;c->native_seen|=(uint8_t)(1u<<i);c->native_count[i]=count;c->race_seq[i]=p.sequence;c->race_heard[i]=now;return 1;
        }
    }
    return 0;
}
void vs4_client_tick(vs4_client *c,uint64_t now) {
    if(!c)return;if(now<c->clock){client_stop(c,VS4_CLOCK);return;}c->clock=now;
    if(!c->joined||c->authority_lost)return;
    c->paused=0;
    if(c->view.phase>=VS4_MATCH&&c->view.phase<=VS4_LOAD&&now-c->phase_since>=c->policy.stage_ms){client_stop(c,VS4_CONTROL_SILENT);return;}
    if(c->view.phase==VS4_RUNNING)for(unsigned i=0;i<c->view.n;i++)if(i!=c->view.me&&!(c->view.finished&(1u<<i))&&now-c->race_heard[i]>=c->policy.soft_ms)c->paused=1;
    if(now-c->heard>=c->policy.control_ms) { client_stop(c,VS4_AUTHORITY_LOST);c->authority_lost=1;c->view.phase=VS4_ROOM_VIEW;return; }
    if(c->view.phase==VS4_RUNNING&&!c->stop)for(unsigned i=0;i<c->view.n;i++)if(i!=c->view.me&&!(c->view.finished&(1u<<i))&&now-c->race_heard[i]>=c->policy.race_ms+c->policy.finish_grace_ms){client_stop(c,VS4_RACE_SILENT);return;}
}
static size_t client_packet(vs4_client *c,uint8_t *out,size_t cap,uint8_t kind,const uint8_t *body,uint16_t len) {
    if(!c||c->tx_seq==UINT64_MAX){if(c)client_stop(c,VS4_COUNTER);return 0;}
    vs4_packet p;memset(&p,0,sizeof p);p.kind=kind;p.id=c->id;p.session=c->session;p.sequence=++c->tx_seq;p.body=body;p.length=len;
    if(kind!=VS4_JOIN){p.incarnation=c->view.incarnation;p.membership=c->view.membership;p.round=c->view.round;p.config=c->view.config;p.term=c->view.term;}
    return vs4_encode(out,cap,&p);
}
size_t vs4_client_join(vs4_client *c,uint8_t *out,size_t cap,const uint8_t name[16],const uint8_t identity[19],uint8_t power,uint8_t handling) {
    if(!c||c->joined||c->stop||power>24||handling>24||(unsigned)power+handling>34||!name||!identity||identity[17]!='C'||identity[18]!=4)return 0;uint8_t b[40]={0};memcpy(b,name,16);b[16]=power;b[17]=handling;memcpy(b+18,identity,19);return client_packet(c,out,cap,VS4_JOIN,b,40);
}
size_t vs4_client_command(vs4_client *c,uint8_t *out,size_t cap,const vs4_command *in) {
    if(!c||!in||!c->joined||c->authority_lost)return 0;vs4_command cmd=*in;cmd.event=c->view.event;
    if((cmd.op==VS4_ACK&&c->stop&&!c->teardown)||(c->stop&&cmd.op!=VS4_ACK&&cmd.op!=VS4_QUIT&&cmd.op!=VS4_CANCEL))return 0;
    if(cmd.op==VS4_TUNE_DRAFT||cmd.op==VS4_TUNE_READY) {
        if(c->view.phase!=VS4_TUNE||!vs4_profile_valid(&c->view.members[c->view.me],cmd.profile))return 0;
        if((c->view.tuned&(1u<<c->view.me))&&(cmd.op==VS4_TUNE_DRAFT||memcmp(cmd.profile,c->view.members[c->view.me].profile,21)))return 0;
    }
    if(cmd.op==VS4_LOAD_READY) { if(c->view.phase!=VS4_LOAD||!c->profile_confirmed||memcmp(c->own_profile,c->view.members[c->view.me].profile,21))return 0;c->local_loaded_round=c->view.round;c->local_loaded_config=c->view.config; }
    if(cmd.op==VS4_FINISH) { if(c->view.phase!=VS4_RUNNING)return 0;c->local_finished_round=c->view.round; }
    if(cmd.op==VS4_CANCEL||cmd.op==VS4_QUIT)client_stop(c,VS4_LOCAL_CANCEL);
    uint8_t body[40];vs4_command_encode(body,&cmd);return client_packet(c,out,cap,VS4_COMMAND,body,40);
}
size_t vs4_client_race(vs4_client *c,uint8_t *out,size_t cap,const uint8_t *native) { if(!c||!c->joined||c->stop||c->authority_lost||c->view.phase!=VS4_RUNNING||c->local_finished_round==c->view.round||!native)return 0;return client_packet(c,out,cap,VS4_RACE,native,VS4_NATIVE); }

/* ---------- authority ---------- */
static unsigned allmask(const vs4_state *s) { return (1u<<s->n)-1; }
static unsigned livemask(const vs4_state *s) { unsigned m=0;for(unsigned i=0;i<s->n;i++)if(s->members[i].live)m|=1u<<i;return m; }
static int bump(vs4_authority *a,uint64_t *v) { if(*v==UINT64_MAX){a->failed=VS4_COUNTER;return 0;}++*v;return 1; }
static int event(vs4_authority *a) { if(!bump(a,&a->state.event))return 0;a->state.state_ack=0;return 1; }
static uint16_t tune_remaining(const vs4_authority *a) {
    if(a->state.phase!=VS4_TUNE)return VS4_TUNE_UNKNOWN;
    uint64_t elapsed=a->clock-a->phase_since;
    return elapsed<VS4_TUNE_MS?(uint16_t)(VS4_TUNE_MS-elapsed):0;
}
static int finish_tuning(vs4_authority *a) {
    vs4_state *s=&a->state;
    if(s->phase!=VS4_TUNE||tune_remaining(a)||s->tuned==allmask(s))return 0;
    for(unsigned i=0;i<s->n;i++)if(!(s->tuned&(1u<<i))) {
        vs4_member *m=&s->members[i];
        if(vs4_profile_valid(m,a->tune_draft[i]))memcpy(m->profile,a->tune_draft[i],VS4_PROFILE);
        else if(!vs4_member_registration(m,m->profile)){a->failed=VS4_BAD_WIRE;return 0;}
    }
    s->tuned=(uint8_t)allmask(s);
    return 1;
}
static void broadcast(vs4_authority *a,vs4_emit_fn emit,void *ctx) {
    a->state.tune_remaining_ms=tune_remaining(a);
    if(!emit||a->failed)return;uint8_t body[VS4_STATE_BASE+4*VS4_MEMBER],out[VS4_MAX_PACKET];
    for(unsigned i=0;i<a->state.n;i++)if(a->state.members[i].live) {
        a->state.me=(uint8_t)i;size_t len=vs4_state_encode(body,sizeof body,&a->state);if(!len){a->failed=VS4_BAD_WIRE;return;}
        vs4_packet p;memset(&p,0,sizeof p);p.kind=VS4_STATE;p.incarnation=a->state.incarnation;p.membership=a->state.membership;p.round=a->state.round;p.config=a->state.config;p.term=a->state.term;p.id=a->state.members[i].id;p.session=a->state.members[i].session;if(!bump(a,&a->send_seq))return;p.sequence=a->send_seq;p.body=body;p.length=(uint16_t)len;size_t n=vs4_encode(out,sizeof out,&p);if(n)emit(ctx,a->endpoint[i],out,n);
    }
}
static void reject(vs4_authority *a,uint64_t ep,const vs4_packet *in,uint8_t reason,vs4_emit_fn emit,void *ctx) {
    if(!emit||!in||!in->id||!vs4_nonce_nonzero(in->session)||a->failed)return;
    uint8_t out[VS4_MAX_PACKET];vs4_packet p=*in;p.kind=VS4_REJECT;p.incarnation=a->state.incarnation;p.body=&reason;p.length=1;if(!bump(a,&a->send_seq))return;p.sequence=a->send_seq;size_t n=vs4_encode(out,sizeof out,&p);if(n)emit(ctx,ep,out,n);
}
static void clear_round(vs4_authority *a) { vs4_state *s=&a->state;a->native_seen=0;s->ready=s->tuned=s->loaded=s->finished=s->done=s->abort_ack=0;memset(a->tune_draft,0,sizeof a->tune_draft);for(unsigned i=0;i<s->n;i++){memset(s->members[i].profile,0,21);s->members[i].choice=UINT16_MAX;} }
static void compact(vs4_authority *a) {
    vs4_state *s=&a->state;unsigned j=0;for(unsigned i=0;i<s->n;i++)if(s->members[i].live){if(i!=j){s->members[j]=s->members[i];a->endpoint[j]=a->endpoint[i];a->control[j]=a->control[i];a->race_seen[j]=a->race_seen[i];memcpy(a->high[j],a->high[i],sizeof a->high[j]);}j++;}
    s->n=(uint8_t)j;s->owner=0;s->me=0;s->phase=(a->migration_quorum&&!a->migration_approved)?VS4_ROOM_VIEW:VS4_ROOM;clear_round(a);s->reason=0;bump(a,&s->membership);event(a);
}
static void abort_round(vs4_authority *a,uint8_t reason) { if(a->state.phase==VS4_ROOM||a->state.phase==VS4_ABORTING)return;a->state.phase=VS4_ABORTING;a->state.reason=reason;a->state.aborted_round=a->state.round;a->state.abort_ack=0;event(a); }
static void lost(vs4_authority *a,unsigned i,uint8_t reason) {
    if(!a->state.members[i].live)return;a->state.members[i].live=0;
    if(a->state.phase==VS4_ROOM||a->state.phase==VS4_ROOM_VIEW)compact(a);else {abort_round(a,reason);if((a->state.abort_ack&livemask(&a->state))==livemask(&a->state))compact(a);}
}
int vs4_authority_init(vs4_authority *a,vs4_nonce inc,uint64_t now,vs4_policy p) {
    if(!a)return 0;memset(a,0,sizeof *a);if(!vs4_nonce_nonzero(inc)||!policy_valid(p))return 0;a->state.incarnation=inc;a->state.membership=a->state.config=a->state.event=a->state.term=1;a->state.km=13;a->state.tune_remaining_ms=VS4_TUNE_UNKNOWN;a->policy=p;a->clock=now;return 1;
}
int vs4_authority_set_seed(vs4_authority *a,uint32_t seed) { if(!a||a->failed||a->state.phase!=VS4_ROOM)return 0;a->state.seed=seed;return 1; }
static int join(vs4_authority *a,uint64_t ep,const vs4_packet *p,uint64_t now,vs4_emit_fn emit,void *ctx) {
    if(!p->id||!vs4_nonce_nonzero(p->session)||vs4_nonce_nonzero(p->incarnation)||p->membership||p->round||p->config||p->term||!budget_valid(p->body[16],p->body[17])||!identity_valid(p->body+18)||p->body[35]!='C'||p->body[36]!=4||!zero(p->body+37,3)){reject(a,ep,p,VS4_RANGE,emit,ctx);return 0;}
    uint8_t registration[21];memcpy(registration,p->body+18,3);registration[3]=p->body[16];registration[4]=p->body[17];memcpy(registration+5,p->body+21,16);if(a->registration_validator&&!a->registration_validator(registration,a->registration_ctx)){reject(a,ep,p,VS4_RANGE,emit,ctx);return 0;}
    for(unsigned i=0;i<a->state.n;i++)if(a->state.members[i].id==p->id||a->endpoint[i]==ep||vs4_nonce_equal(a->state.members[i].session,p->session)) {
        if(a->state.members[i].id==p->id&&a->endpoint[i]==ep&&vs4_nonce_equal(a->state.members[i].session,p->session)&&a->state.members[i].live&&p->sequence>a->high[i][VS4_JOIN]&&!memcmp(a->state.members[i].name,p->body,16)&&!memcmp(a->state.members[i].identity,p->body+18,19)&&a->state.members[i].base_power==p->body[16]&&a->state.members[i].base_handling==p->body[17]) { a->high[i][VS4_JOIN]=p->sequence;/* JOIN retry never keeps an active roster alive. */broadcast(a,emit,ctx);return 1; }
        reject(a,ep,p,VS4_IDENTITY,emit,ctx);return 0;
    }
    if(a->state.phase!=VS4_ROOM&&a->state.phase!=VS4_ROOM_VIEW){reject(a,ep,p,VS4_BUSY,emit,ctx);return 0;}
    if(a->state.n==4||a->tombstone_count==VS4_TOMBSTONES){reject(a,ep,p,VS4_FULL,emit,ctx);return 0;}
    for(unsigned i=0;i<a->tombstone_count;i++)if(vs4_nonce_equal(a->tombstones[i],p->session)){reject(a,ep,p,VS4_STALE,emit,ctx);return 0;}
    if(a->migration_quorum&&!a->migration_approved){if(!a->state.n&&p->id!=a->recovery_owner){reject(a,ep,p,VS4_BUSY,emit,ctx);return 0;}int original=-1;for(unsigned j=0;j<a->original_n;j++)if(a->original[j].id==p->id&&(((uint64_t)a->original[j].ipv4<<16)|a->original[j].port)==ep){original=(int)j;break;}if(original<0){reject(a,ep,p,VS4_IDENTITY,emit,ctx);return 0;}a->migration_seen++;}
    unsigned i=a->state.n++;vs4_member *m=&a->state.members[i];memset(m,0,sizeof *m);m->id=p->id;m->session=p->session;m->choice=UINT16_MAX;memcpy(m->name,p->body,16);m->maker=p->body[18];m->car=p->body[19];m->base_power=p->body[16];m->base_handling=p->body[17];m->budget=(uint8_t)(p->body[16]+p->body[17]);memcpy(m->identity,p->body+18,19);m->ipv4=(uint32_t)(ep>>16);m->port=(uint16_t)ep;if(!a->allow_loopback_endpoints&&(m->ipv4>>24)==127){m->ipv4=0;m->port=0;}m->live=1;a->endpoint[i]=ep;a->control[i]=now;memset(a->high[i],0,sizeof a->high[i]);a->high[i][VS4_JOIN]=p->sequence;a->tombstones[a->tombstone_count++]=p->session;bump(a,&a->state.membership);event(a);broadcast(a,emit,ctx);return 1;
}
static int command(vs4_authority *a,unsigned i,const vs4_packet *p,uint64_t now) {
    vs4_command c;if(!vs4_command_decode(&c,p))return -1;vs4_state *s=&a->state;unsigned bit=1u<<i,all=allmask(s);
    /* Valid current-session quit/cancel are safe even across phase-event churn,
     * but NEVER across round/config/membership fences. */
    if(c.op==VS4_QUIT){lost(a,i,VS4_PEER_QUIT);return 1;}
    if(c.op==VS4_CANCEL){abort_round(a,VS4_LOCAL_CANCEL);return 1;}
    if(c.event!=s->event)return 0;
    a->control[i]=now;
    switch(c.op) {
    case VS4_ACK:s->state_ack|=(uint8_t)bit;if(s->phase==VS4_ROOM_VIEW&&a->migration_quorum&&s->n>=a->migration_quorum&&s->state_ack==all){a->migration_approved=1;s->phase=VS4_ROOM;event(a);}if(s->phase==VS4_ABORTING){s->abort_ack|=(uint8_t)bit;if((s->abort_ack&livemask(s))==livemask(s))compact(a);}return 1;
    case VS4_BEGIN:if(a->catalog_required&&!a->registration_validator)return 0;if(s->phase!=VS4_ROOM||i!=s->owner||s->n<2||s->state_ack!=all||(a->migration_quorum&&!a->migration_approved))return 0;if(c.target!=VS4_MATCH||c.ramp||c.zone||c.km<1||c.km>100||c.song<1||c.song>22||c.song==2)return 0;if(a->seed_source&&!a->seed_source(&s->seed,a->seed_ctx)){a->failed=VS4_COUNTER;return 0;}if(!bump(a,&s->round)||!bump(a,&s->config))return 0;clear_round(a);s->km=c.km;s->song=c.song;s->ramp=s->zone=0;s->phase=VS4_MATCH;event(a);return 1;
    case VS4_PHASE_READY:if(s->phase!=VS4_MATCH||c.target!=VS4_MATCH)return 0;s->ready|=(uint8_t)bit;return 1;
    case VS4_CHOICE:if((s->phase!=VS4_MAP&&s->phase!=VS4_TIME)||c.target!=s->phase||(s->phase==VS4_TIME?c.value>1:(c.value&~0x87u)))return 0;if(s->ready&bit)return s->members[i].choice==c.value;s->members[i].choice=c.value;s->ready|=(uint8_t)bit;return 1;
    case VS4_ADVANCE:
        if(i!=s->owner||s->phase<VS4_MATCH||s->phase>VS4_TUNE||c.target!=s->phase+1)return 0;
        if((s->phase==VS4_TUNE?s->tuned:s->ready)!=all)return 0;
        if(c.ramp>=22||c.km<1||c.km>100||c.zone>1||c.song<1||c.song>22||c.song==2)return 0;
        if(s->phase==VS4_MATCH&&(c.ramp!=s->ramp||c.km!=s->km||c.song!=s->song||c.zone!=s->zone))return 0;
        if((s->phase==VS4_MAP||s->phase==VS4_TIME)&&(!a->decision||!a->decision(s,&c,a->decision_ctx)))return 0;
        if(s->phase>=VS4_TIME&&(c.ramp!=s->ramp||c.km!=s->km))return 0;
        if(s->phase>=VS4_TUNE&&c.song!=s->song)return 0;
        if(s->phase==VS4_TUNE&&c.zone!=s->zone)return 0;
        s->ramp=c.ramp;s->km=c.km;s->song=c.song;s->zone=c.zone;s->phase=c.target;s->ready=0;for(unsigned j=0;j<s->n;j++)s->members[j].choice=UINT16_MAX;
        if(s->phase<=VS4_TUNE&&!bump(a,&s->config))return 0;event(a);return 1;
    case VS4_TUNE_READY:
        if(s->phase!=VS4_TUNE||!vs4_profile_valid(&s->members[i],c.profile))return 0;
        if(s->tuned&bit)return !memcmp(s->members[i].profile,c.profile,21);
        memcpy(s->members[i].profile,c.profile,21);s->tuned|=(uint8_t)bit;return 1;
    case VS4_TUNE_DRAFT:
        if(s->phase!=VS4_TUNE||(s->tuned&bit)||!vs4_profile_valid(&s->members[i],c.profile))return 0;
        memcpy(a->tune_draft[i],c.profile,VS4_PROFILE);return 1;
    case VS4_LOAD_READY:
        if(s->phase!=VS4_LOAD||s->tuned!=all)return 0;s->loaded|=(uint8_t)bit;
        if(s->loaded==all){s->phase=VS4_RUNNING;for(unsigned j=0;j<s->n;j++)a->race_seen[j]=now;event(a);}return 1;
    case VS4_FINISH:if(s->phase!=VS4_RUNNING&&s->phase!=VS4_RESULTS)return 0;s->finished|=(uint8_t)bit;if(s->finished==all&&s->phase==VS4_RUNNING){s->phase=VS4_RESULTS;event(a);}return 1;
    case VS4_DONE:if(s->phase!=VS4_RESULTS)return 0;s->done|=(uint8_t)bit;if(s->done==all){s->phase=VS4_ROOM;clear_round(a);event(a);}return 1;
    default:return 0;
    }
}
int vs4_authority_receive(vs4_authority *a,uint64_t ep,const uint8_t *b,size_t n,uint64_t now,vs4_emit_fn emit,void *ctx) {
    if(!a||!ep||a->failed)return -1;if(now<a->clock){a->failed=VS4_CLOCK;return -1;}a->clock=now;
    vs4_packet p;if(!vs4_decode(&p,b,n))return -1;
    if(p.kind==VS4_JOIN)return join(a,ep,&p,now,emit,ctx);
    if((p.kind!=VS4_COMMAND&&p.kind!=VS4_RACE)||!scope(&a->state,&p))return 0;
    int who=-1;for(unsigned i=0;i<a->state.n;i++)if(a->state.members[i].live&&a->endpoint[i]==ep&&a->state.members[i].id==p.id&&vs4_nonce_equal(a->state.members[i].session,p.session)){who=(int)i;break;}
    if(who<0||p.sequence<=a->high[who][p.kind])return 0;
    if(p.kind==VS4_COMMAND) {
        a->high[who][p.kind]=p.sequence;
        int expired=finish_tuning(a);if(a->failed)return -1;
        uint64_t oldevent=a->state.event;int r=command(a,(unsigned)who,&p,now);if(a->state.event!=oldevent)a->phase_since=now;
        if((r>0&&p.body[0]!=VS4_TUNE_DRAFT)||expired)broadcast(a,emit,ctx);return r;
    }
    if(p.kind==VS4_RACE&&a->state.phase==VS4_RUNNING&&!(a->state.finished&(1u<<who))) {
        uint32_t count=(uint32_t)p.body[0x34]|(uint32_t)p.body[0x35]<<8|(uint32_t)p.body[0x36]<<16|(uint32_t)p.body[0x37]<<24,delta=count-a->native_count[who];
        if((a->native_seen&(1u<<who))&&delta>=UINT32_C(0x80000000))return 0;
        if(!(a->native_seen&(1u<<who))||delta){a->race_seen[who]=now;a->native_count[who]=count;}a->native_seen|=(uint8_t)(1u<<who);a->high[who][p.kind]=p.sequence;
        for(unsigned i=0;i<a->state.n;i++)if(i!=(unsigned)who&&a->state.members[i].live&&emit)emit(ctx,a->endpoint[i],b,n);
        return 1;
    }
    return 0;
}
void vs4_authority_tick(vs4_authority *a,uint64_t now,vs4_emit_fn emit,void *ctx) {
    if(!a||a->failed)return;if(now<a->clock){a->failed=VS4_CLOCK;return;}a->clock=now;
    for(unsigned i=0;i<a->state.n;) {
        if(a->state.members[i].live&&now-a->control[i]>=a->policy.control_ms){unsigned before=a->state.n;lost(a,i,VS4_CONTROL_SILENT);if(a->state.n<before)continue;}
        i++;
    }
    if(a->state.phase>=VS4_MATCH&&a->state.phase<=VS4_LOAD&&now-a->phase_since>=a->policy.stage_ms)abort_round(a,VS4_CONTROL_SILENT);
    if(a->state.phase==VS4_RUNNING)for(unsigned i=0;i<a->state.n;i++)if(!(a->state.finished&(1u<<i))&&now-a->race_seen[i]>=a->policy.race_ms+a->policy.finish_grace_ms){abort_round(a,VS4_RACE_SILENT);break;}
    if(finish_tuning(a)||now-a->last_broadcast>=a->policy.retry_ms){a->last_broadcast=now;if(a->state.n)broadcast(a,emit,ctx);}
}

void vs4_authority_set_decision_validator(vs4_authority *a,vs4_decision_fn f,void *ctx){if(a){a->decision=f;a->decision_ctx=ctx;}}
int vs4_authority_recover(vs4_authority *a,const vs4_state *f,vs4_nonce inc,uint64_t term,uint64_t now,vs4_policy p){
    if(!f||f->n<2||f->n>4||term<=f->term||vs4_nonce_equal(inc,f->incarnation)||!vs4_authority_init(a,inc,now,p))return 0;
    a->state.term=term;a->state.phase=VS4_ROOM_VIEW;a->state.round=f->round;a->state.config=f->config;
    a->original_n=f->n;a->recovery_owner=f->members[(term-1)%f->n].id;memcpy(a->original,f->members,sizeof a->original);a->migration_quorum=(uint8_t)(f->n/2+1);return 1;
}

void vs4_authority_set_seed_source(vs4_authority *a,vs4_seed_fn f,void *ctx){if(a){a->seed_source=f;a->seed_ctx=ctx;}}

void vs4_authority_set_registration_validator(vs4_authority *a,vs4_registration_fn f,void *ctx){if(a){a->registration_validator=f;a->registration_ctx=ctx;}}

int vs4_member_registration(const vs4_member *m,uint8_t *out){if(!m||!out)return 0;uint8_t p[21];memcpy(p,m->identity,3);p[3]=m->base_power;p[4]=m->base_handling;memcpy(p+5,m->identity+3,16);if(!vs4_registration_valid(p))return 0;memcpy(out,p,21);return 1;}
