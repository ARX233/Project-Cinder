#include "vs_election.h"
#include <string.h>
uint64_t vs4_member_endpoint(const vs4_member *m){return m?((uint64_t)m->ipv4<<16)|m->port:0;}
static unsigned bits(unsigned m){unsigned n=0;while(m){n+=m&1u;m>>=1;}return n;}
int vs4_election_init(vs4_election *e,const vs4_state *s,unsigned me,uint64_t now){
    if(!e||!s||s->n<2||s->n>4||me>=s->n||!s->term||s->term==UINT64_MAX)return 0;
    memset(e,0,sizeof *e);e->frozen=*s;e->me=(uint8_t)me;e->term=s->term+1;e->candidate=(uint8_t)((e->term-1)%s->n);e->lease_until=now+6000;e->term_until=e->lease_until+6000;e->enabled=1;return 1;
}
void vs4_election_lease(vs4_election *e,uint64_t now,uint64_t lease){if(e&&e->enabled&&!e->committed){e->lease_until=now+lease;e->term_until=e->lease_until+6000;}}
static void emit(vs4_election *e,unsigned kind,vs4_emit_fn send,void *ctx){
    if(!send||!vs4_nonce_nonzero(e->proposal)||e->tx_seq==UINT64_MAX)return;
    uint8_t body[20]={0},out[VS4_MAX_PACKET];body[0]=e->candidate;if(kind==VS4_COMMIT)body[1]=e->votes;memcpy(body+4,e->proposal.b,16);
    vs4_packet p;memset(&p,0,sizeof p);p.kind=(uint8_t)kind;p.incarnation=e->frozen.incarnation;p.membership=e->frozen.membership;p.round=e->frozen.round;p.config=e->frozen.config;p.term=e->term;p.id=e->frozen.members[e->me].id;p.session=e->frozen.members[e->me].session;p.sequence=++e->tx_seq;p.body=body;p.length=20;
    size_t n=vs4_encode(out,sizeof out,&p);for(unsigned i=0;i<e->frozen.n;i++)if(i!=e->me&&vs4_member_endpoint(&e->frozen.members[i]))send(ctx,vs4_member_endpoint(&e->frozen.members[i]),out,n);
}
static void vote(vs4_election *e,uint64_t now,vs4_emit_fn send,void *ctx){
    if(e->voted_term==e->term){if(e->voted_candidate==e->candidate&&vs4_nonce_equal(e->voted_incarnation,e->proposal))emit(e,VS4_VOTE,send,ctx);return;}
    if(now<e->vote_lease_until||!vs4_nonce_nonzero(e->proposal))return;
    e->voted_term=e->term;e->voted_candidate=e->candidate;e->voted_incarnation=e->proposal;e->vote_lease_until=now+6000;e->votes|=(uint8_t)(1u<<e->me);emit(e,VS4_VOTE,send,ctx);
}
void vs4_election_tick(vs4_election *e,uint64_t now,vs4_nonce nonce,vs4_emit_fn send,void *ctx){
    if(!e||!e->enabled||now<e->lease_until)return;
    if(e->committed){if(now>=e->retry_at){if(e->voted_term==e->term)emit(e,VS4_VOTE,send,ctx);if(e->me==e->candidate)emit(e,VS4_COMMIT,send,ctx);e->retry_at=now+100;}return;}
    if(now>=e->term_until&&now>=e->vote_lease_until){if(e->term==UINT64_MAX){e->enabled=0;return;}e->term++;e->candidate=(uint8_t)((e->term-1)%e->frozen.n);memset(e->proposal.b,0,16);e->votes=0;memset(e->high,0,sizeof e->high);e->term_until=now+6000;e->retry_at=0;}
    if(e->me==e->candidate&&!vs4_nonce_nonzero(e->proposal)&&vs4_nonce_nonzero(nonce)&&!vs4_nonce_equal(nonce,e->frozen.incarnation))e->proposal=nonce;
    if(now<e->retry_at)return;e->retry_at=now+100;
    if(e->me==e->candidate){emit(e,VS4_REQUEST_VOTE,send,ctx);vote(e,now,send,ctx);if(bits(e->votes)>e->frozen.n/2){e->committed=1;emit(e,VS4_COMMIT,send,ctx);}}
    else if(vs4_nonce_nonzero(e->proposal))vote(e,now,send,ctx);
}
int vs4_election_receive(vs4_election *e,uint64_t source,const uint8_t *b,size_t n,uint64_t now,vs4_emit_fn send,void *ctx){
    if(!e||!e->enabled||now<e->lease_until)return 0;vs4_packet p;if(!vs4_decode(&p,b,n)||p.kind<VS4_REQUEST_VOTE||p.kind>VS4_COMMIT)return 0;
    if(!vs4_nonce_equal(p.incarnation,e->frozen.incarnation)||p.membership!=e->frozen.membership||p.round!=e->frozen.round||p.config!=e->frozen.config||p.term<e->term||p.body[2]||p.body[3])return 0;
    int who=-1;for(unsigned i=0;i<e->frozen.n;i++)if(vs4_member_endpoint(&e->frozen.members[i])==source&&p.id==e->frozen.members[i].id&&vs4_nonce_equal(p.session,e->frozen.members[i].session)){who=(int)i;break;}if(who<0)return 0;
    unsigned candidate=(unsigned)((p.term-1)%e->frozen.n);if(p.body[0]!=candidate||((p.kind==VS4_REQUEST_VOTE||p.kind==VS4_COMMIT)&&(unsigned)who!=candidate))return 0;
    vs4_nonce proposal;memcpy(proposal.b,p.body+4,16);if(!vs4_nonce_nonzero(proposal)||vs4_nonce_equal(proposal,e->frozen.incarnation))return 0;
    if(e->committed)return p.term==e->term&&candidate==e->candidate&&vs4_nonce_equal(proposal,e->proposal);
    if(p.term>e->term){if(now<e->vote_lease_until)return 0;e->term=p.term;e->candidate=(uint8_t)candidate;e->proposal=proposal;e->votes=0;memset(e->high,0,sizeof e->high);e->term_until=now+6000;}
    if(p.sequence<=e->high[who][p.kind-VS4_REQUEST_VOTE])return 0;
    if(vs4_nonce_nonzero(e->proposal)&&!vs4_nonce_equal(proposal,e->proposal))return 0;
    e->proposal=proposal;e->high[who][p.kind-VS4_REQUEST_VOTE]=p.sequence;
    if(p.kind==VS4_REQUEST_VOTE){if(p.body[1])return 0;vote(e,now,send,ctx);return 1;}
    if(p.kind==VS4_VOTE){if(p.body[1])return 0;e->votes|=(uint8_t)(1u<<who);if(e->me==e->candidate&&bits(e->votes)>e->frozen.n/2){e->committed=1;emit(e,VS4_COMMIT,send,ctx);}return 1;}
    /* COMMIT alone cannot invent votes: every voter multicasts its vote and
     * retries; receiver must itself have observed the matching majority. */
    unsigned mask=p.body[1],all=(1u<<e->frozen.n)-1;if(mask&~all||bits(mask)<=e->frozen.n/2||(mask&e->votes)!=mask||e->voted_term!=e->term||!vs4_nonce_equal(e->voted_incarnation,proposal))return 0;
    e->committed=1;return 1;
}
