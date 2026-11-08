#include "vs_session.h"
#include <assert.h>
#include <string.h>

static vs4_authority host;
static vs4_client clients[3];
static uint64_t now;
static const uint8_t base[VS4_PROFILE] = {[3]=24,[4]=10,[19]='C',[20]=4};

static void deliver(void *ctx, uint64_t endpoint, const uint8_t *packet, size_t size) {
    (void)ctx;
    assert(vs4_client_receive(&clients[endpoint-1],packet,size,now)==1);
}

static size_t encode(unsigned i, unsigned op, unsigned target, unsigned power,
                     uint8_t packet[VS4_MAX_PACKET]) {
    vs4_command command={.op=op,.target=target};
    if(op==VS4_BEGIN||op==VS4_ADVANCE){command.km=13;command.song=3;}
    if(op==VS4_TUNE_DRAFT||op==VS4_TUNE_READY) {
        memcpy(command.profile,base,sizeof base);
        command.profile[3]=power;
        command.profile[4]=34-power;
    }
    size_t size=vs4_client_command(&clients[i],packet,VS4_MAX_PACKET,&command);
    assert(size);
    return size;
}

static int receive(unsigned i, const uint8_t *packet, size_t size) {
    return vs4_authority_receive(&host,i+1,packet,size,now,deliver,NULL);
}

static int send(unsigned i, unsigned op, unsigned target, unsigned power) {
    uint8_t packet[VS4_MAX_PACKET];
    size_t size=encode(i,op,target,power,packet);
    return receive(i,packet,size);
}

static int accept_ballot(const vs4_state *state, const vs4_command *command, void *ctx) {
    (void)state;(void)command;(void)ctx;
    return 1;
}

static void begin_tune(void) {
    now=200;
    assert(vs4_authority_init(&host,(vs4_nonce){{42}},now,vs4_default_policy()));
    vs4_authority_set_decision_validator(&host,accept_ballot,NULL);
    for(unsigned i=0;i<3;i++) {
        assert(vs4_client_init(&clients[i],i+1,(vs4_nonce){{i+1}},now,vs4_default_policy()));
        uint8_t name[16]={'A'+i},identity[19]={[17]='C',[18]=4},packet[VS4_MAX_PACKET];
        size_t size=vs4_client_join(&clients[i],packet,sizeof packet,name,identity,24,10);
        assert(size&&receive(i,packet,size)==1);
    }
    for(unsigned i=0;i<3;i++)assert(send(i,VS4_ACK,0,0)==1);
    assert(send(0,VS4_BEGIN,VS4_MATCH,0)==1);
    for(unsigned phase=VS4_MATCH;phase<VS4_TUNE;phase++) {
        for(unsigned i=0;i<3;i++)assert(send(i,phase==VS4_MATCH?VS4_PHASE_READY:VS4_CHOICE,phase,0)==1);
        assert(send(0,VS4_ADVANCE,phase+1,0)==1);
    }
    assert(host.state.phase==VS4_TUNE&&clients[0].view.tune_remaining_ms==VS4_TUNE_MS);
    assert(clients[0].view.members[0].choice==UINT16_MAX);
}

static void test_deadline(int late_ready) {
    begin_tune();
    uint8_t stale[VS4_MAX_PACKET],bad[VS4_MAX_PACKET];
    assert(send(0,VS4_TUNE_DRAFT,0,19)==1);
    size_t stale_size=encode(0,VS4_TUNE_DRAFT,0,20,stale);
    assert(send(0,VS4_TUNE_DRAFT,0,21)==1);
    assert(receive(0,stale,stale_size)==0);
    size_t bad_size=encode(0,VS4_TUNE_DRAFT,0,22,bad);
    bad[VS4_HEADER+16+2]=1; /* Factory color differs from registration. */
    assert(receive(0,bad,bad_size)==0);
    assert(send(2,VS4_TUNE_DRAFT,0,18)==1);
    assert(send(2,VS4_TUNE_READY,0,17)==1);
    assert(!clients[0].profile_confirmed&&host.state.tuned==4);
    assert(send(0,VS4_ADVANCE,VS4_LOAD,0)==0);

    now=host.phase_since+5000;
    for(unsigned i=0;i<3;i++)assert(send(i,VS4_ACK,0,0)==1);
    assert(clients[0].view.tune_remaining_ms==5000);
    now=host.phase_since+VS4_TUNE_MS-1;
    vs4_authority_tick(&host,now,deliver,NULL);
    assert(host.state.tuned==4&&clients[0].view.tune_remaining_ms==1);
    now++;
    if(late_ready)assert(send(0,VS4_TUNE_READY,0,23)==0);
    else vs4_authority_tick(&host,now,deliver,NULL);
    const unsigned final_power[]={21,24,17};
    for(unsigned i=0;i<3;i++) {
        assert(clients[i].view.tuned==7&&clients[i].view.tune_remaining_ms==0);
        assert(clients[i].profile_confirmed&&clients[i].own_profile[3]==final_power[i]);
    }
    assert(send(0,VS4_ADVANCE,VS4_LOAD,0)==1);
    for(unsigned i=0;i<3;i++) {
        assert(clients[i].view.tune_remaining_ms==VS4_TUNE_UNKNOWN);
        assert(send(i,VS4_LOAD_READY,0,0)==1);
    }
    assert(host.state.phase==VS4_RUNNING);
    for(unsigned i=0;i<3;i++)assert(vs4_client_native_allowed(&clients[i]));
}

int main(void) {
    test_deadline(0);
    test_deadline(1);
    return 0;
}
