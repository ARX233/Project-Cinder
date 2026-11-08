#!/usr/bin/env python3
"""CinderVS4 only: bounded standalone UDP authority. All clients must update.

Default bind is loopback for controlled offline tests. For an intentional LAN
room use --bind 0.0.0.0. No cloud probing, legacy relay or native execution.
Session/source binding is not cryptographic authentication. Embedded host loss
is handled by C clients' frozen-roster majority election, not this process.
"""
import argparse
import dataclasses
import json
import pathlib
import secrets
import selectors
import socket
import struct
import time

MAGIC = b'WVS4'
VERSION = 4
HEADER = struct.Struct('!4sBBHHH16sQQQI16sQQ')
assert HEADER.size == 88
JOIN, STATE, COMMAND, RACE, REJECT, REQUEST_VOTE, VOTE, COMMIT = range(1, 9)
ROOM, MATCH, MAP, TIME, TUNE, LOAD, RUNNING, RESULTS, ABORTING, ROOM_VIEW = range(10)
ACK, BEGIN, PHASE_READY, CHOICE, ADVANCE, TUNE_READY, LOAD_READY, FINISH, DONE, QUIT, CANCEL, TUNE_DRAFT = range(1, 13)
TUNE_MS = 10000
BAD_WIRE, UPDATE_ALL, FULL, BUSY, IDENTITY, STALE, RANGE, PEER_QUIT, CONTROL_SILENT, RACE_SILENT, LOCAL_CANCEL, AUTHORITY_LOST, CLOCK, COUNTER = range(1, 15)
CATALOG_REQUIRED = 15
UPDATE_MESSAGE = 'Update all clients and the room server to WVS4'
NATIVE = 632
MAX_PACKET = 88 + NATIVE
ZERO = bytes(16)
MASK64 = (1 << 64) - 1


def nonce():
    value = secrets.token_bytes(16)
    if value == ZERO:
        raise RuntimeError('OS entropy returned zero nonce; refusing authority')
    return value


@dataclasses.dataclass(frozen=True)
class Packet:
    kind: int
    incarnation: bytes = ZERO
    membership: int = 0
    round: int = 0
    config: int = 0
    id: int = 0
    session: bytes = ZERO
    sequence: int = 1
    term: int = 0
    body: bytes = b''

    def encode(self):
        return HEADER.pack(MAGIC, VERSION, self.kind, 88, len(self.body), 0,
                           self.incarnation, self.membership, self.round, self.config,
                           self.id, self.session, self.sequence, self.term) + self.body


def decode(data):
    if not 88 <= len(data) <= MAX_PACKET:
        raise ValueError('datagram size')
    magic, version, kind, hlen, blen, reserved, inc, member, rnd, cfg, pid, session, seq, term = HEADER.unpack_from(data)
    if (magic, version, hlen, reserved) != (MAGIC, VERSION, 88, 0) or not 1 <= kind <= 8 or not seq or blen != len(data)-88:
        raise ValueError('strict header')
    expected = {JOIN: 40, COMMAND: 40, RACE: NATIVE, REJECT: 1, REQUEST_VOTE: 20, VOTE: 20, COMMIT: 20}
    if kind in expected and blen != expected[kind]:
        raise ValueError('body size')
    if kind == STATE and (blen < 132 or blen > 420 or (blen-36) % 96):
        raise ValueError('state size')
    return Packet(kind, inc, member, rnd, cfg, pid, session, seq, term, data[88:])


@dataclasses.dataclass
class Member:
    id: int
    session: bytes
    address: tuple
    name: bytes
    base_power: int
    base_handling: int
    identity: bytes
    control: int
    live: bool = True
    profile: bytes = bytes(21)
    tune_draft: bytes = bytes(21)
    choice: int = 65535
    race_seen: int = 0
    native_count: int | None = None
    high: dict = dataclasses.field(default_factory=dict)
    advertise: bool = True

    @property
    def budget(self):
        return self.base_power + self.base_handling

    def record(self, choice=None):
        ip = int.from_bytes(socket.inet_aton(self.address[0]), 'big') if self.advertise else 0
        result = struct.pack('!I16s16sBBBB21sHBBIH', self.id, self.session, self.name,
                             self.identity[0], self.identity[1], self.budget, self.live,
                             self.profile, self.choice if choice is None else choice, self.base_power, self.base_handling,
                             ip, self.address[1] if self.advertise else 0) + b'\0' + self.identity + bytes(5)
        assert len(result) == 96
        return result


def valid_identity(identity):
    if len(identity) != 19 or identity[17:] != b'C\4' or identity[9] > 127 or identity[10] > 3 or identity[11] > 1 or identity[12] > 4 or identity[13] > 3 or identity[15] > 12 or identity[16] >= 100:
        return False
    ended = False
    for glyph in identity[3:8]:
        if ended and glyph != 255:
            return False
        ended |= glyph == 255
    return True


def valid_registration(power, handling, identity):
    return 0 <= power <= 24 and 0 <= handling <= 24 and power+handling <= 34 and (max(power,handling) <= 10 if power+handling <= 20 else min(power,handling) >= 10) and valid_identity(identity)


def valid_profile(member, profile):
    return (len(profile) == 21 and profile[19:] == b'C\4' and
            profile[:3]+profile[5:] == member.identity and profile[3] <= 24 and profile[4] <= 24 and
            profile[3]+profile[4] == member.budget and
            ((profile[3], profile[4]) == (member.base_power, member.base_handling) if member.budget <= 20
             else profile[3] >= 10 and profile[4] >= 10))


class Authority:
    def __init__(self, *, incarnation=None, now=0, decision=None, control_ms=6000,
                 race_ms=4500, finish_grace_ms=1500, retry_ms=100, stage_ms=90000, allow_loopback_endpoints=True, catalog=None, require_catalog=True):
        self.incarnation = nonce() if incarnation is None else incarnation
        if len(self.incarnation) != 16 or self.incarnation == ZERO:
            raise ValueError('nonzero OS-random incarnation required')
        self.membership = self.config = self.event = self.term = 1
        self.round = self.aborted_round = 0
        self.phase = ROOM
        self.members = []
        self.tombstones = set()
        self.ready = self.tuned = self.loaded = self.finished = self.done = self.abort_ack = self.state_ack = 0
        self.reason = self.ramp = self.song = self.zone = self.seed = 0
        self.km = 13
        self.sequence = 0
        self.clock = self.phase_since = now
        self.last_broadcast = 0
        self.control_ms, self.race_ms, self.finish_grace_ms = control_ms, race_ms, finish_grace_ms
        self.retry_ms, self.stage_ms = retry_ms, stage_ms
        self.decision = decision
        self.catalog = catalog
        self.require_catalog = require_catalog
        self.failed = False
        self.outputs = []
        self.allow_loopback_endpoints = allow_loopback_endpoints

    def bump(self, field):
        if getattr(self, field) == MASK64:
            self.failed = True
            raise OverflowError('counter exhausted: create fresh authority')
        setattr(self, field, getattr(self, field)+1)

    def new_event(self):
        self.bump('event')
        self.state_ack = 0
        self.phase_since = self.clock

    @property
    def all(self):
        return (1 << len(self.members))-1

    @property
    def live(self):
        return sum(1 << i for i, p in enumerate(self.members) if p.live)

    def send(self, p, kind, body):
        self.bump('sequence')
        data = Packet(kind, self.incarnation, self.membership, self.round, self.config,
                      p.id, p.session, self.sequence, self.term, body).encode()
        self.outputs.append((p.address, data))

    def broadcast(self):
        remaining = max(0, TUNE_MS - (self.clock - self.phase_since)) if self.phase == TUNE else None
        for i, p in enumerate(self.members):
            if p.live:
                body = struct.pack('!QQ16BI', self.event, self.aborted_round, self.phase,
                                   len(self.members), i, 0, self.ready, self.tuned, self.loaded,
                                   self.finished, self.done, self.abort_ack, self.reason, self.state_ack,
                                   self.ramp, self.km, self.song, self.zone, self.seed)
                body += b''.join(q.record(remaining if j == 0 else None) for j, q in enumerate(self.members))
                self.send(p, STATE, body)

    def reject(self, address, packet, reason):
        self.bump('sequence')
        self.outputs.append((address, Packet(REJECT, self.incarnation, id=packet.id,
                            session=packet.session, sequence=self.sequence, term=self.term,
                            body=bytes([reason])).encode()))

    def clear_round(self):
        self.ready = self.tuned = self.loaded = self.finished = self.done = self.abort_ack = 0
        for p in self.members:
            p.profile = p.tune_draft = bytes(21)
            p.choice = 65535
            p.native_count = None

    def compact(self):
        self.members = [p for p in self.members if p.live]
        self.phase = ROOM
        self.reason = 0
        self.clear_round()
        self.bump('membership')
        self.new_event()

    def abort(self, reason):
        if self.phase in (ROOM, ABORTING):
            return
        self.phase, self.reason, self.aborted_round = ABORTING, reason, self.round
        self.abort_ack = 0
        self.new_event()

    def finish_tuning(self):
        if self.phase != TUNE or self.clock - self.phase_since < TUNE_MS or self.tuned == self.all:
            return False
        for i, m in enumerate(self.members):
            if not self.tuned & (1 << i):
                m.profile = (m.tune_draft if valid_profile(m, m.tune_draft) else
                             m.identity[:3] + bytes((m.base_power, m.base_handling)) + m.identity[3:])
        self.tuned = self.all
        return True

    def lost(self, index, reason):
        p = self.members[index]
        if not p.live:
            return
        p.live = False
        if self.phase == ROOM:
            self.compact()
        else:
            self.abort(reason)
            if self.abort_ack & self.live == self.live:
                self.compact()

    def receive(self, data, address, now):
        self.outputs = []
        if self.failed:
            return []
        if now < self.clock:
            self.failed = True
            return []
        self.clock = now
        try:
            p = decode(data)
        except (ValueError, struct.error):
            # Actionable reply, never legacy JOIN/race interpretation.
            if data.startswith((b'WV', b'RFR1', b'RDY1')) or len(data) == NATIVE:
                self.reject(address, Packet(REJECT), UPDATE_ALL)
            return self.outputs
        if p.kind == JOIN:
            self.join(p, address, now)
            return self.outputs
        if p.kind not in (COMMAND, RACE) or (p.incarnation, p.membership, p.round, p.config, p.term) != (self.incarnation, self.membership, self.round, self.config, self.term):
            return []
        index = next((i for i, m in enumerate(self.members) if m.live and (m.id, m.session, m.address) == (p.id, p.session, address)), None)
        if index is None:
            return []
        m = self.members[index]
        if p.sequence <= m.high.get(p.kind, 0):
            return []
        if p.kind == RACE:
            if self.phase != RUNNING or self.finished & (1 << index):
                return []
            count = int.from_bytes(p.body[0x34:0x38], 'little')
            delta = (count-m.native_count) & 0xffffffff if m.native_count is not None else 1
            if m.native_count is not None and delta >= 0x80000000:
                return []
            if m.native_count is None or delta:
                m.native_count, m.race_seen = count, now
            m.high[RACE] = p.sequence
            self.outputs.extend((q.address, data) for q in self.members if q.live and q is not m)
            return self.outputs
        expired = self.finish_tuning()
        if self.command(index, p, now) or expired:
            self.broadcast()
        return self.outputs

    def join(self, p, address, now):
        power, handling = p.body[16:18]
        identity = p.body[18:37]
        if not p.id or p.session == ZERO or p.incarnation != ZERO or p.membership or p.round or p.config or p.term or any(p.body[37:]) or not valid_registration(power, handling, identity):
            self.reject(address, p, RANGE)
            return
        if self.catalog is not None:
            maker, car, color = identity[:3]
            rows = self.catalog["ncolors"]
            if maker >= len(rows) or car >= len(rows[maker]) or color >= rows[maker][car]:
                self.reject(address, p, RANGE)
                return
        for m in self.members:
            if m.id == p.id or m.session == p.session or m.address == address:
                if (m.live and (m.id, m.session, m.address, m.name, m.base_power, m.base_handling, m.identity) ==
                    (p.id, p.session, address, p.body[:16], power, handling, identity) and p.sequence > m.high.get(JOIN, 0)):
                    m.high[JOIN] = p.sequence
                    self.broadcast()
                else:
                    self.reject(address, p, IDENTITY)
                return
        if self.phase != ROOM:
            self.reject(address, p, BUSY)
            return
        if len(self.members) >= 4 or len(self.tombstones) >= 256:
            self.reject(address, p, FULL)
            return
        if p.session in self.tombstones:
            self.reject(address, p, STALE)
            return
        m = Member(p.id, p.session, address, p.body[:16], power, handling, identity, now)
        m.high[JOIN] = p.sequence
        m.advertise = self.allow_loopback_endpoints or not address[0].startswith("127.")
        self.members.append(m)
        self.tombstones.add(p.session)
        self.bump('membership')
        self.new_event()
        self.broadcast()

    def command(self, index, p, now):
        op, target, value, event, ramp, km, song, zone = struct.unpack_from('!BBHQBBBB', p.body)
        profile = p.body[16:37]
        if (not 1 <= op <= TUNE_DRAFT or not event or any(p.body[37:]) or
            (op not in (ADVANCE, BEGIN) and any(p.body[12:16])) or
            (op not in (TUNE_READY, TUNE_DRAFT) and any(profile)) or (op != CHOICE and value) or
            (op not in (ADVANCE, PHASE_READY, CHOICE, BEGIN) and target)):
            return False
        m = self.members[index]
        m.high[COMMAND] = p.sequence
        bit = 1 << index
        if op == QUIT:
            self.lost(index, PEER_QUIT)
            return True
        if op == CANCEL:
            self.abort(LOCAL_CANCEL)
            return True
        if event != self.event:
            return False
        m.control = now
        if op == ACK:
            self.state_ack |= bit
            if self.phase == ABORTING:
                self.abort_ack |= bit
                if self.abort_ack & self.live == self.live:
                    self.compact()
            return True
        if op == BEGIN:
            if self.require_catalog and self.catalog is None:
                self.reject(m.address, p, CATALOG_REQUIRED)
                return False
            if self.phase != ROOM or index or len(self.members) < 2 or self.state_ack != self.all:
                return False
            if target != MATCH or ramp or zone or not 1 <= km <= 100 or song not in (1, *range(3, 23)):
                return False
            self.km, self.song, self.ramp, self.zone = km, song, 0, 0
            self.bump('round'); self.bump('config'); self.clear_round()
            self.seed = secrets.randbits(32)
            self.phase = MATCH; self.new_event()
            return True
        if op in (PHASE_READY, CHOICE):
            if target != self.phase or (op == PHASE_READY and self.phase != MATCH) or (op == CHOICE and (self.phase not in (MAP, TIME) or (value > 1 if self.phase == TIME else value & ~0x87))):
                return False
            if op == CHOICE:
                if self.ready & bit:
                    return m.choice == value
                m.choice = value
            self.ready |= bit
            return True
        if op == ADVANCE:
            if index or not MATCH <= self.phase <= TUNE or target != self.phase+1 or (self.tuned if self.phase == TUNE else self.ready) != self.all:
                return False
            if not 0 <= ramp < 22 or not 1 <= km <= 100 or zone > 1 or song not in (1, *range(3,23)):
                return False
            if self.phase == MATCH and (ramp,km,song,zone) != (self.ramp,self.km,self.song,self.zone):
                return False
            if self.phase in (MAP, TIME) and (self.decision is None or not self.decision(self, (ramp, km, song, zone))):
                return False
            if self.phase >= TIME and (ramp, km) != (self.ramp, self.km):
                return False
            if self.phase >= TUNE and song != self.song:
                return False
            if self.phase == TUNE and zone != self.zone:
                return False
            self.ramp, self.km, self.song, self.zone = ramp, km, song, zone
            self.phase = target; self.ready = 0
            for q in self.members:
                q.choice = 65535
            if self.phase <= TUNE:
                self.bump('config')
            self.new_event()
            return True
        if op in (TUNE_READY, TUNE_DRAFT):
            if self.phase != TUNE or not valid_profile(m, profile):
                return False
            if self.tuned & bit:
                return op == TUNE_READY and m.profile == profile
            if op == TUNE_DRAFT:
                m.tune_draft = profile
                return False
            m.profile = profile; self.tuned |= bit
            return True
        if op == LOAD_READY:
            if self.phase != LOAD or self.tuned != self.all:
                return False
            self.loaded |= bit
            if self.loaded == self.all:
                self.phase = RUNNING
                for q in self.members:
                    q.race_seen = now
                self.new_event()
            return True
        if op == FINISH:
            if self.phase not in (RUNNING, RESULTS):
                return False
            self.finished |= bit
            if self.finished == self.all and self.phase == RUNNING:
                self.phase = RESULTS; self.new_event()
            return True
        if op == DONE:
            if self.phase != RESULTS:
                return False
            self.done |= bit
            if self.done == self.all:
                self.phase = ROOM; self.clear_round(); self.new_event()
            return True
        return False

    def tick(self, now):
        self.outputs = []
        if self.failed or now < self.clock:
            self.failed = True
            return []
        self.clock = now
        # Stable object list, not shifting indices after room compaction.
        for p in list(self.members):
            if p.live and now-p.control >= self.control_ms:
                self.lost(self.members.index(p), CONTROL_SILENT)
        if MATCH <= self.phase <= LOAD and now-self.phase_since >= self.stage_ms:
            self.abort(CONTROL_SILENT)
        if self.phase == RUNNING and any(not self.finished & (1 << i) and now-p.race_seen >= self.race_ms+self.finish_grace_ms for i, p in enumerate(self.members)):
            self.abort(RACE_SILENT)
        if self.members and (self.finish_tuning() or now-self.last_broadcast >= self.retry_ms):
            self.last_broadcast = now
            self.broadcast()
        return self.outputs


def default_decision(authority, config):
    """Reviewed ballot rules; ramp lottery is explicitly a PORT ADAPTATION.
    Area concrete0..7 with80 omakase marker counts normally; ascending ties use
    MATCH-shared seed lowbyte. Day majority ties morning0. Original ramp UI is
    not claimed equivalent: choose its exact area's raw ramp row using seed>>8.
    """
    votes = [p.choice for p in authority.members]
    if authority.ready != authority.all or len(votes) < 2:
        return False
    if authority.phase == TIME:
        return (all(v in (0, 1) for v in votes) and config[:2] == (authority.ramp, authority.km) and config[2] in (1, *range(3,23))
                and config[3] == (1 if votes.count(1) > votes.count(0) else 0))
    if authority.phase == MAP:
        if any(v & ~0x87 or v & 0x7f > 7 for v in votes):
            return False
        tallies = [sum((v & 0x7f) == area for v in votes) for area in range(8)]
        tied = [a for a, count in enumerate(tallies) if count == max(tallies)]
        area = tied[(authority.seed & 255) % len(tied)]
        rows = ((3, 2, 0, 1), (5, 4), (6, 7, 9, 8), (10, 11, 13, 12), (17,), (14,), (15, 16), (18, 19, 20, 21))
        ramp = rows[area][(authority.seed >> 8) % len(rows[area])]
        return config == (ramp, authority.km, authority.song, authority.zone)
    return False


def load_catalog(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate catalog key')
            result[key] = value
        return result
    raw = pathlib.Path(path).read_bytes()
    if len(raw) > 100000:
        raise ValueError('catalog too large')
    catalog = json.loads(raw, object_pairs_hook=unique)
    rows = catalog.get('ncolors')
    if catalog.get('schema') != 'CinderVS4.catalog.v1' or not isinstance(rows, list) or not 1 <= len(rows) <= 16:
        raise ValueError('catalog schema')
    if any(not isinstance(row, list) or not 1 <= len(row) <= 32 or any(type(n) is not int or not 1 <= n <= 8 for n in row) for row in rows):
        raise ValueError('catalog bounds')
    return catalog


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', type=int, nargs='?', default=27015)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--catalog', help='reviewed metadata-only CinderVS4.catalog.v1 JSON; required before BEGIN')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('port must be 0..65535')
    catalog = load_catalog(args.catalog) if args.catalog else None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((args.bind, args.port)); s.setblocking(False)
    selector = selectors.DefaultSelector(); selector.register(s, selectors.EVENT_READ)
    def send_best_effort(packet, destination):
        try:
            s.sendto(packet, destination)
        except OSError:
            # Nonblocking UDP loss is retried by state/command protocol, not a
            # reason to crash the room authority or perform an unbounded send.
            pass
    authority = Authority(now=time.monotonic_ns()//1_000_000, decision=default_decision, allow_loopback_endpoints=args.bind.startswith("127."), catalog=catalog)
    print('CinderVS4 server %s:%d; %s' % (*s.getsockname(), UPDATE_MESSAGE), flush=True)
    print('Catalog gate: '+('reviewed model/color bounds loaded' if catalog else 'STRUCTURAL ONLY; BEGIN blocked: CATALOG_REQUIRED'), flush=True)
    try:
        while not authority.failed:
            selector.select(authority.retry_ms/1000)
            now = time.monotonic_ns()//1_000_000
            for _ in range(64):
                try:
                    data, address = s.recvfrom(MAX_PACKET+1)
                except BlockingIOError:
                    break
                if data == b'WVS4\4\x20\0\0':
                    out = bytearray(48); out[:6] = b'WVS4\4\x21'; out[6] = len(authority.members)
                    out[8:24] = authority.incarnation; out[24:40] = b'CinderVS4 room'.ljust(16, b'\0')
                    out[44] = authority.phase
                    if authority.members:
                        out[40:44] = authority.members[0].id.to_bytes(4, 'big')
                    send_best_effort(out, address)
                    continue
                for destination, packet in authority.receive(data, address, now):
                    send_best_effort(packet, destination)
            for destination, packet in authority.tick(now):
                send_best_effort(packet, destination)
    except KeyboardInterrupt:
        pass
    finally:
        selector.close(); s.close()


if __name__ == '__main__':
    main()
