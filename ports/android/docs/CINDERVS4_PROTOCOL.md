# CinderVS4 wire / state / authority contract

All players and the room server must update together. Magic `WVS4`, version `4`. No WV1/WV2/WV3, raw632, RFR1, RDY1, old build-marker, truncated profile, or trailing-byte fallback. A recognized incompatible frame gets reason2, **Update all clients and the room server to WVS4**. Old executables may ignore a new rejection; no claim that they can be made to display it.

## Ownership / threat / execution boundary

This is a lane-only implementation proposal. The parent alone merges source/canonical trees and app/menu hooks. It executes no Original object/ELF/Lua, changes no native physics object or RNG, and never calls a game routine. CPU C fixtures and loopback UDP are allowed. Device, ADB, GPU, cloud, deployment and original-code execution remain paused.

Endpoint + participant ID + fresh session nonce are bound exactly. This is benign-LAN fault/session separation, **not cryptographic authentication, confidentiality, anti-spoof security, or Byzantine consensus**. No keys/TLS were introduced. An on-path sender is outside this protocol's security claim. UDP/NAT/full-mesh failure and permanent partitions cannot guarantee universal delivery or global agreement.

## Exact wire schema

Every integer below is **network/big endian** except the unchanged native payload's existing little-endian frame counter. Datagram length is exact; all reserved bytes are zero; buffers are fixed.

### Session header: 88 bytes

| Offset | Field |
|---|---|
|0|magic[4] = WVS4|
|4|version:u8 = 4|
|5|kind:u8|
|6|header_length:u16 = 88|
|8|body_length:u16 = exact datagram length minus88|
|10|reserved:u16 = 0|
|12|authority incarnation[16]|
|28|membership generation:u64|
|36|round epoch:u64|
|44|configuration generation:u64|
|52|participant ID:u32|
|56|client session nonce[16]|
|72|transport sequence:u64, nonzero, no wrap|
|80|authority/election term:u64|

OS entropy supplies nonzero128-bit authority/session/candidate nonces; failure **fails closed**, never a fixed/time/native-RNG fallback. Every reconnect creates a fresh client session. Normal traffic needs the exact incarnation/term/membership/round/config tuple and exact selected source endpoint. Counters do not wrap; exhaustion fails closed. A valid new endpoint/session cannot replace a registered member during an active round.

Kinds: JOIN1, STATE2, COMMAND3, RACE4, REJECT5, REQUEST_VOTE6, VOTE7, COMMIT8.

### JOIN: 40 bytes

Header incarnation, term and all generations are zero. Header carries new participant ID/session/sequence. Body: name[16], permanent base_power:u8, base_handling:u8, immutable identity[19], reserved[3]. Identity is the21-byte baseline registration with bytes3/4 removed: profile[0:3] + profile[5:21]. It includes factory color, glyphs, title, dress, marker `'C',4`—no custom palette synchronization.

The baseline is validated at room admission. Native final profile remains zero until tuning is confirmed or finalized by the deadline. Lobby renderers reconstruct baseline via `vs4_member_registration`.

Existing-session JOIN retry must match ID/session/source/name/baseline exactly and use a newer transport sequence. It does not keep an active participant alive. Retain at most256 admitted session tombstones per incarnation; refuse more admissions until room recreation. Across a process restart a delayed zero-incarnation JOIN may occupy a provisional slot until its control deadline, but cannot authorize GO without that session's fresh state/tune/load ACKs. No persistent tombstone/across-restart delivery guarantee is claimed.

### STATE: 36 + 96*n bytes, n=1..4

Body fixed prefix: event:u64, aborted_round:u64; phase,n,myPCB,ownerPCB,phase_ready_mask,tuned_mask,loaded_mask,finished_mask,done_mask,abort_ACK_mask,reason,state_ACK_mask,ramp,km,song,zone (16 u8); shared seed:u32.

Member record96 bytes: id:u32, session[16], name[16], maker:u8, car:u8, permanent budget:u8, live:u8, confirmed profile[21], phase choice:u16, base_power:u8, base_handling:u8, observed/advertised IPv4:u32, port:u16, reserved:u8, immutable identity[19], reserved[5]. PCB is the record index, never an untrusted claimed race field.

During TUNE, member 0's unused phase-choice slot carries the authority's remaining milliseconds, 0–10000 inclusive. The client exposes this as `tune_remaining_ms` and decodes the member's phase choice as `UINT16_MAX`. A server without deadline support sends `UINT16_MAX` in this slot. Other phases retain the existing choice encoding.

STATE header ID/session echo the specific recipient. Until this fresh-session echo arrives, no authority can be bound from GO-like state or abort alone. The authority increments its event on phase/config/roster transitions; STATE transport sequence orders snapshots within an event. ACK masks grow without creating ACK-of-ACK event loops. Initial response loss cannot bypass initial state ACK barriers. Active native race configuration is a full immutable LOAD snapshot, not a sparse GO hint.

### COMMAND: 40 bytes

op:u8, target_phase:u8, value:u16, acknowledged_event:u64, ramp:u8, km:u8, song:u8, zone:u8, profile[21], reserved[3]. Unused fields must be zero.

Ops: ACK1, BEGIN2, PHASE_READY3, CHOICE4, ADVANCE5, TUNE_READY6, LOAD_READY7, FINISH8, DONE9, QUIT10, CANCEL11, TUNE_DRAFT12. Commands retry with newer transport sequences but the same semantic operation; phase/event/config fences make retries idempotent. QUIT/CANCEL may cross event changes only within the exact current room/round/config/membership scope. Stale-round leave/cancel cannot cancel a subsequent round.

PHASE_READY is legal **only MATCH**. MAP/TIME require explicit CHOICE for each participant. Every phase advance resets all choices to UINT16_MAX. A confirmed choice is immutable for that phase: exact duplicate accepted; a changed choice rejected. No generic ready or old MAP0/1 value can become a day vote.

### RACE: exactly632 bytes

Payload is the unmodified native SLxPacket. Relay only from a frozen live registered endpoint/session/PCB in exact RUNNING scope. Wrapper transport sequence rejects replay/reorder. Existing native counter at offset0x34 is read little-endian and must progress in bounded RFC1982 order to refresh race freshness; duplicates may be relayed to recover lost last images but **never refresh native progress**. No native finish flag/content determines membership, completion or rewards.

### Election: exactly20 bytes

candidate_original_PCB:u8, observed_vote_mask:u8 (COMMIT only), reserved:u16, proposed_new_incarnation[16]. Header binds original frozen MATCH incarnation/membership/round/config/session and the strictly newer election term. Vote/request masks/reserved fields are exact. COMMIT alone cannot invent votes: a receiver must itself have observed matching source/session-bound votes from the original-roster majority.

### REJECT: reason:u8

1 malformed,2 update-all,3 capacity,4 busy,5 identity,6 stale,7 range,8 peer-quit,9 control-silent,10 race-silent,11 local-cancel,12 authority-lost,13 clock,14 counter,15 catalog-required. A selected authority may send sessionless reason2 to diagnose unsupported framing. Rejections never authorize native execution or refresh race progress.

### Discovery: separate exact8 /48-byte envelope

Request: `WVS4`,4,32,0,0. Offer48: `WVS4`,4,33,n,0,incarnation[16],room_name[16],owner_id:u32,phase:u8,reserved[3]. Source address identifies the offered endpoint. Old offers set an incompatibility notice, never trigger a legacy JOIN. Session profiles are not sent by discovery. Real LAN hosting does not advertise a127.* owner endpoint as reachable: it is zero/unavailable; exposing loopback endpoints is restricted to explicit127-only fixtures.

## State machine and safety

ROOM0 → MATCH1 → MAP2 → TIME3 → TUNE4 → LOAD5 → RUNNING6 → RESULTS7 → ROOM. ABORTING8 is terminal for the current round. ROOM_VIEW9 means recovering/unconfirmed authority; it is a real room/recovery view but cannot start a round.

MATCH acknowledges the frozen roster before opening the map vote. A player who confirms tune waits while the remaining players choose. The car introduction uses the finalized LOAD roster and plays before the client initializes the race.

BEGIN: owner only,2..4 current members, all ACK the same room event, catalog gate installed. Freeze roster, permanent registration budget, one OS-random shared seed/tie byte and a new round/config generation once. BEGIN validates preview song, km1..100, target MATCH, ramp0/zone0. Exact retries do not redraw the seed. MATCH completion copies frozen preview config; MAP commits reviewed ballots/ramp policy; TIME commits the majority day result and **final legal BGM** (R1: song1 or3..22, never unresolved RANDOM2). Ramp/km stay immutable. TUNE→LOAD locks final song, zone and entire tuned roster.

Area: confirmed concrete0..7, optional0x80 omakase presentation still counts as a concrete vote; ascending tied areas use shared seed lowbyte modulo tie count. Day: majority, ties morning0. Start-ramp choice from the exact original area's raw ramp row using seed>>8 is an **explicit port adaptation**, not a claim that the original ramp-select UI/lottery was fully recovered. Wire ramp is raw0..21, not native ERamp1..22. No native RNG is touched.

Tune: original-reachable permanent totals0..34; until20 each axis0..10, after20 each axis10..24. ≤20 must submit unchanged base P/H with no redistribution UI. >20 can allocate power10..total-10, handling remainder, each≤24. Both TUNE_READY and TUNE_DRAFT retain exactly the same immutable19 identity bytes and total. TUNE_READY locks a profile immediately. TUNE_DRAFT records a private candidate with newer command sequence and leaves the player eligible to make further changes. At 10 seconds the authority locks each outstanding player's latest valid draft, or their registered base profile if no valid draft arrived. Late changes cannot replace a locked profile. All frozen members need an authority-locked profile in the same config before LOAD and must send LOAD_READY for that immutable config before authoritative RUNNING. App native initialization occurs inside LOAD before its LOAD_READY, but no native race tick is allowed before RUNNING.

Any registered frozen member QUIT, control silence, race silence, local cancellation or loading failure in MATCH through RESULTS cancels the round; never shrink an active race to solo. ABORT is sticky/retried/durable in state. App stops native before its next tick after observing stop; clears pending data/config; performs actual teardown; then calls teardown_done. Only then can it ACK abort. All surviving live members must ACK teardown before the same hostalive authority compacts back to ROOM. Repeated/stale abort/GO/ready/finish cannot affect a new epoch.

FINISH is explicit and current-session/current-round/config bound; stop native snapshots locally, retry FINISH until authoritative finish state. A FINISHED peer still owes control heartbeats and final DONE; crossing a native finish line or receiving an old native finish image is not member loss. All FINISH yields authoritative RESULTS. DONE is sent only after local result UI and teardown. All DONE yields normal ROOM without abort. Departure before that shared completion still cancels presentation/returns everyone to room, even if FINISHED or DONE. Parent keeps already-processed valid results at the authoritative RESULTS boundary; this core makes no persistent reward/atomic rollback claim.

## Timers and work budgets (new port policy, not Original facts)

* RX budget64 datagrams per caller poll. Empty/oversized datagrams consume budget. MSG_TRUNC cannot masquerade as an exact valid prefix. Deadlines still run under saturation; drained=false is not an indefinite timeout extension.
* `net_native_allowed` requires a drained receive observation, the pure client native gate, and matching local-authority RUNNING/round/config when self-hosting. A local authority's ABORT blocks Native immediately even while its UDP self-STATE is queued; adopted polling also latches that stop before returning. App calls poll/stop checks before every native tick. A currently hung native call cannot be interrupted by this module.
* Native race progress quiet≥1000ms: soft pause. A cached native image may be resent under fresh wrapper sequence; duplicate native count does not reset freshness.
* Hard race abort:4500ms +1500ms finish-transition grace =6000ms without native progress for an unfinished frozen peer. Lobby/control heartbeats cannot reset this plane.
* Control/authority lease:6000ms. FINISHED peers still require it. Any pre-race phase has a finite90000ms completion deadline.
* TUNE deadline:10000ms from the authoritative TIME→TUNE transition. Repeated snapshots carry the remaining time. The control lease still applies while tuning.
* Reliable command/state/vote retry:100ms. All reliability requires live polling and eventual datagram delivery. No sleeps/background native thread.

## Actual host-loss election / recovery

An embedded room server dies with its hosting process. No claim of retaining that same active authority. Each survivor independently soft-pauses then latches stop/ROOM_VIEW at lease expiry; disconnected players cannot receive abort. Preserve the original frozen roster, sessions and reachable endpoints.

After old authority lease expiry, deterministic candidate for term t is original PCB `(t-1)%original_n` (initial authority term1, first recovery candidate PCB1). Each session casts at most one vote per term/incarnation proposal and does not grant a later term during its6000ms vote lease. Require **floor(original_n/2)+1** observed votes, retaining the lost host in the denominator. Candidate/request/vote source endpoints and frozen sessions must match; no127 owner endpoint is invented and no NAT connectivity is assumed.

After certificate, actual local native teardown must complete before reconnect. Candidate adopts its existing bound UDP socket as new authority; all survivors retain source endpoints but use **fresh session nonces** and the elected fresh incarnation/term. The elected coordinator must rejoin first. New authority remains ROOM_VIEW and restricts provisional admission to original source-bound members until an original-majority has newly handshaken and ACKed the same membership event. Only then is active ROOM committed; next BEGIN still needs all current member ACKs, tune and load barriers. Later members join normally only after that authority quorum was established.

One bounded previous sealed migration certificate remains retried alongside the next frozen round until close or a newer migration replaces it. This helps a late reachable peer learn the elected incarnation and perform a fresh handshake at the next ROOM; it never authorizes an old GO or bypasses current quorum. Arbitrarily old history/multiterm partitions still require explicit manual fresh join; no unbounded recovery guarantee is claimed.

N4+host loss+3 survivors can form3 votes; N3+host loss+2 can form2. N2+one survivor cannot start; N4+only2 survivors cannot silently declare a new shared authority. They stay ROOM_VIEW/noGO across terms. An explicit leave/new-room action may create a separate room ID; it is not represented as recovered consensus. Full-mesh/NAT failures may also remain ROOM_VIEW. No global certainty under permanent partitions, malicious spoofing, unbounded scheduling/clock/network assumptions, or stopped processes is invented; tests establish the finite benign-LAN cases only.

## Catalog / app integration boundary

Core validates exact schema, legal permanent allocation, immutable appearance, markerC4 and known dress ranges. It has no generated car catalog dependency. Product app must install `net_set_registration_validator` / actual CARDB callback on embedded and recovered authorities, and independently validate every frozen LOAD roster against actual CARDB before Native setup. Product hosting without that closure rejects BEGIN as CATALOG_REQUIRED.

Standalone Python defaults to structural-only ROOM admission but **blocks BEGIN without `--catalog`**. The reviewed metadata-only JSON validates exact maker/car/color bounds; no candidate-learned catalog. The numeric export helper compiles only the explicitly reviewed generated const header, not Original objects/ELF/Lua; its provenance is pinned separately. No raw generated header is copied into public source.
