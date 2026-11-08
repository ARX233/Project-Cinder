"""Current WV1 Python server: isolated ephemeral loopback contract tests."""
import select
import socket
import struct
import subprocess
import sys
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "tools" / "vs_server.py"
M = b"WV\x01"
# Constrain both the wildcard bind and the discovery connect to loopback.
BOOT = r"""
import socket, runpy, sys
bind, connect = socket.socket.bind, socket.socket.connect
def safe_bind(s, a):
    assert a == ("0.0.0.0", 0)
    bind(s, ("127.0.0.1", 0))
    print("PORT", s.getsockname()[1], flush=True)
def safe_connect(s, a):
    assert a == ("10.255.255.255", 1)
    connect(s, ("127.0.0.1", 9))
socket.socket.bind, socket.socket.connect = safe_bind, safe_connect
path = sys.argv[1]
sys.argv = [path, "0"]
runpy.run_path(path, run_name="__main__")
"""

def hello(pid, status, name, profile):
    return M + b"\x01" + struct.pack("<IB16sB", pid, status, name, len(profile)) + profile

def parse(packet, kind):
    assert packet[:4] == M + bytes([kind])
    if kind == 2:
        count, own, host, ramp, km, rid = struct.unpack_from("<BBBBBI", packet, 4)
        offset, fmt = 13, "<BIB16sB"
    else:
        rid, seed, ramp, km, count, own = struct.unpack_from("<IIBBBB", packet, 4)
        offset, fmt = 16, "<BI16sB"
    players = {}
    for _ in range(count):
        fields = struct.unpack_from(fmt, packet, offset)
        offset += struct.calcsize(fmt)
        length = fields[-1]
        data = packet[offset:offset + length]
        assert len(data) == length
        offset += length
        players[fields[1]] = (fields, data)
    assert offset + (kind == 4) == len(packet)
    return rid, own, players

class PythonServerLoopback(unittest.TestCase):
    def setUp(self):
        self.proc = subprocess.Popen([sys.executable, "-u", "-c", BOOT, str(SERVER)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop)
        self.assertTrue(select.select([self.proc.stdout], [], [], 5)[0])
        line = self.proc.stdout.readline().split()
        self.assertEqual(line[0], "PORT")
        self.addr = ("127.0.0.1", int(line[1]))
    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill(); self.proc.wait(timeout=3)
        self.proc.stdout.close(); self.proc.stderr.close()
    def client(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0)); s.connect(self.addr)
        self.addCleanup(s.close)
        return s
    def recv(self, s):
        s.settimeout(1); return s.recv(4096)
    def quiet(self, s):
        s.settimeout(.15)
        with self.assertRaises(socket.timeout): s.recv(4096)
    def pair(self):
        a,b=self.client(),self.client()
        new=bytes(range(21))+b"RFR1"+struct.pack("<BIQI",0,0,0x123456789abcdef0,7)
        old=bytes(range(21))
        a.send(hello(101,0,b"new",new)); self.assertEqual(parse(self.recv(a),2)[2][101][1],new)
        b.send(hello(202,0,b"old",old))
        for s in (a,b):
            players=parse(self.recv(s),2)[2]
            self.assertEqual(players[101][1],new); self.assertEqual(players[202][1],old)
        return a,b,new,old
    def start(self,a,b):
        a.send(M+b"\x03\x03\x11\x05")
        groups=[[self.recv(s) for _ in range(3)] for s in (a,b)]
        for s,g in zip((a,b),groups):
            self.assertEqual(g,[g[0]]*3); self.quiet(s)
        return [parse(g[0],4) for g in groups]
    def test_profiles_status_go_and_race(self):
        a,b,new,old=self.pair()
        update=bytes(range(21))+b"RFR1"+struct.pack("<BIQI",1,99,0x123456789abcdef0,8)
        a.send(hello(101,2,b"new",update))
        for s in (a,b):
            p=parse(self.recv(s),2)[2]
            self.assertEqual(p[101][0][2],2); self.assertEqual(p[101][1],update); self.assertEqual(p[202][1],old)
        ga,gb=self.start(a,b)
        self.assertEqual(ga[0],gb[0]); self.assertEqual((ga[1],gb[1]),(0,1))
        for g in (ga,gb):
            self.assertEqual(g[2][101][1],update); self.assertEqual(g[2][202][1],old)
        post=bytes(range(21))+b"RFR1"+struct.pack("<BIQI",2,ga[0],0x123456789abcdef0,9)
        a.send(hello(101,1,b"new",post))
        for s in (a,b): self.assertEqual(parse(self.recv(s),2)[2][101][1],post)
        for sender,receiver,pcb in ((a,b,0),(b,a,1)):
            packet=M+b"\x05"+struct.pack("<IB",ga[0],pcb)+bytes(range(256))
            sender.send(packet); self.assertEqual(self.recv(receiver),packet); self.quiet(sender); self.quiet(receiver)
        a.send(M+b"\x05"+b"\x00"*4)
        a.send(M+b"\x05"+struct.pack("<IB",ga[0]+10,0)+b"x")
        self.quiet(b)
    def test_three_profile_generations_are_forwarded_byte_for_byte(self):
        # The server treats both extensions as opaque, including RDY1's byte.
        clients = [self.client() for _ in range(3)]
        base = bytes(range(21))
        recovery = base + b"RFR1" + struct.pack("<BIQI", 0, 0, 0x123456789abcdef0, 7)
        expected = {101: base, 202: recovery, 303: recovery + b"RDY1\x01"}
        self.assertEqual([len(expected[i]) for i in (101, 202, 303)], [21, 42, 47])
        for index, pid in enumerate((101, 202, 303)):
            clients[index].send(hello(pid, 0, b"mixed", expected[pid]))
            for recipient in clients[:index + 1]:
                observed = parse(self.recv(recipient), 2)[2]
                self.assertEqual({k: v[1] for k, v in observed.items()},
                                 {k: expected[k] for k in (101, 202, 303)[:index + 1]})
        # Updated readiness is transmitted to all recipients without interpretation.
        expected[303] = recovery + b"RDY1\x00"
        clients[2].send(hello(303, 2, b"mixed", expected[303]))
        for recipient in clients:
            observed = parse(self.recv(recipient), 2)[2]
            self.assertEqual({k: v[1] for k, v in observed.items()}, expected)
            self.assertEqual(observed[303][0][2], 2)
        clients[0].send(M + b"\x03\x03\x11\x05")
        race_ids = []
        for index, recipient in enumerate(clients):
            packets = [self.recv(recipient) for _ in range(3)]
            self.assertEqual(packets, [packets[0]] * 3)
            rid, own, observed = parse(packets[0], 4)
            race_ids.append(rid)
            self.assertEqual(own, index)
            self.assertEqual({k: v[1] for k, v in observed.items()}, expected)
            self.quiet(recipient)
        self.assertGreater(race_ids[0], 0)
        self.assertEqual(race_ids, [race_ids[0]] * 3)

    def test_drop_and_repeat_are_bounded(self):
        a,b,new,_=self.pair()
        for p in (b"", b"WV\x01", b"XX\x01\x01"+b"x"*30, M+b"\x01"+b"x"*21, M+b"\x03\x01"):
            a.send(p)
        b.send(M+b"\x03\x01\x02\x03")
        self.quiet(a); self.quiet(b)
        for _ in range(5): a.send(hello(101,0,b"new",new))
        for _ in range(5): self.assertEqual(parse(self.recv(a),2)[2][101][1],new)
        self.quiet(a); self.quiet(b)

if __name__ == "__main__": unittest.main()
