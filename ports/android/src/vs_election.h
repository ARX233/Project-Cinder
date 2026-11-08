#ifndef VS4_ELECTION_H
#define VS4_ELECTION_H
#include "vs_session.h"
/* Benign LAN fault protocol, NOT authenticated consensus. Exact frozen endpoints
 * and session IDs are checked. Unreachable full mesh remains ROOM_VIEW.
 * Frozen roster majority floor(n/2)+1 includes original lost host in denominator.
 * Candidate order follows original PCB order, skipping no names implicitly.
 * New terms cannot be voted until prior granted vote lease expires. Once commit
 * is accepted, election is sealed until fresh authority lease fails. */
typedef struct {
    vs4_state frozen; uint64_t lease_until, term, voted_term, tx_seq, retry_at;
    uint64_t term_until, vote_lease_until, high[VS4_PLAYERS][3];
    uint8_t me, candidate, votes, committed, enabled, voted_candidate;
    vs4_nonce proposal, voted_incarnation;
} vs4_election;
int vs4_election_init(vs4_election *,const vs4_state *,unsigned me,uint64_t now);
void vs4_election_lease(vs4_election *,uint64_t now,uint64_t lease_ms);
/* Call only after core authority_lost. entropy_nonce must be fresh on each term
 * for local candidate; noncandidate argument is ignored. */
void vs4_election_tick(vs4_election *,uint64_t now,vs4_nonce entropy_nonce,vs4_emit_fn,void *);
int vs4_election_receive(vs4_election *,uint64_t source,const uint8_t *,size_t,uint64_t now,vs4_emit_fn,void *);
uint64_t vs4_member_endpoint(const vs4_member *);
#endif
