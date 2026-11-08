#!/usr/bin/env python3
"""WV2 client over actual loopback UDP; temporary files must stay under CodexWork."""
import ctypes as C, importlib.util, os, pathlib, select, shutil, socket, struct, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE=pathlib.Path('/Volumes/CodexWork')
spec=importlib.util.spec_from_file_location('wv2_server', ROOT/'tools/vs_server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)

class Player(C.Structure):
    _fields_=[('id',C.c_uint32),('status',C.c_int),('name',C.c_char*17),('profile',C.c_ubyte*64),('profile_len',C.c_int)]
class Lobby(C.Structure):
    _fields_=[('connected',C.c_int),('n',C.c_int),('me',C.c_int),('host',C.c_int),('player',Player*4)]
class Go(C.Structure):
    _fields_=[('race',C.c_uint64),('generation',C.c_uint64),('seed',C.c_uint32),('ramp',C.c_int),('km',C.c_int),('n',C.c_int),('pcb',C.c_int),('player',Player*4),('song',C.c_int)]

def run():
  with tempfile.TemporaryDirectory(prefix='wv2-fixture-',dir=BASE) as d:
    env=dict(os.environ,TMPDIR=d)
    lib=pathlib.Path(d)/'base.dylib'
    src=pathlib.Path(d)/'net.c';src.write_text((ROOT/'src/net.c').read_text())
    subprocess.run(['cc','-dynamiclib','-Isrc',str(src),'tests/wv2_client_stubs.c','-o',str(lib)],cwd=ROOT,env=env,check=True)
    clients=[]
    for i in range(3):
      path=pathlib.Path(d)/('client%d.dylib'%i);shutil.copyfile(lib,path);x=C.CDLL(str(path))
      x.net_open.argtypes=[C.c_char_p,C.c_int,C.c_uint32];x.net_poll.argtypes=[C.c_double,C.c_int,C.c_char_p,C.c_void_p,C.c_int]
      x.net_lobby_now.restype=C.POINTER(Lobby);x.net_take_go.argtypes=[C.POINTER(Go)];x.net_abort_pending.argtypes=[C.POINTER(C.c_uint64),C.POINTER(C.c_uint64)];x.net_abort_ack.argtypes=[C.c_uint64,C.c_uint64];x.net_race_send.argtypes=[C.c_void_p,C.c_int];clients.append(x)
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.setblocking(False);port=sock.getsockname()[1];s=server.Server(sock)
    t=100.0
    def step(count=1,live=None):
      nonlocal t
      live=clients if live is None else live
      for _ in range(count):
        t+=.1
        for x in live:x.net_poll(t,0,b'client',None,0)
        select.select([sock],[],[],0.002)
        while True:
          try:data,addr=sock.recvfrom(4096)
          except BlockingIOError:break
          s.got(data,addr,t)
        s.poll(t)
    for i,x in enumerate(clients):assert x.net_open(b'127.0.0.1',port,100+i)==0;step(8,clients[:i+1])
    step(12);assert all(x.net_lobby_now().contents.n==3 and x.net_room_ready() for x in clients)
    clients[0].net_start(2,13,4);assert not clients[0].net_room_ready()
    clients[0].net_start(2,13,4);step(12);assert not any(x.net_room_ready() for x in clients)
    gs=[]
    for x in clients:
      g=Go();assert x.net_take_go(C.byref(g))==1;gs.append(g)
    assert len({(g.race,g.generation,g.seed) for g in gs})==1
    step(8)
    assert not any(x.net_host_closed() for x in clients)
    packet=(C.c_ubyte*0x278)();packet[0x34]=1;clients[1].net_race_send(packet,len(packet));step(2);clients[0].net_race_receive();assert clients[0].test_fresh(1)==1, (s.race, [(g.pcb,g.race,g.generation) for g in gs], clients[0].test_deliveries(1))
    clients[1].net_race_send(packet,len(packet));step(2);clients[0].net_race_receive();assert clients[0].test_deliveries(1)==2 and clients[0].test_fresh_count(1)==1
    # Out-of-order sequence and wrong race/room must not reach car link.
    payload=bytearray(0x278)
    r=s.header(server.RACE)+struct.pack('<QQB',gs[0].generation,gs[0].race,1)+payload
    sock.sendto(r,s.players[0].addr)
    sock.sendto(r[:4]+b'Y'*16+r[20:],s.players[0].addr)
    sock.sendto(s.header(server.RACE)+struct.pack('<QQB',gs[0].generation,gs[0].race+99,1)+payload,s.players[0].addr)
    sock.sendto(b'WV\x01\x04'+b'\0'*100,s.players[0].addr)
    step(2);clients[0].net_race_receive();assert clients[0].test_deliveries(1)==2
    old_go=s.players[0].go
    original_send=s.send
    dropped=[]
    def drop_abort(p,data):
      if data[3]==server.ABORT and len(dropped)<4:
        dropped.append(data);return
      original_send(p,data)
    s.send=drop_abort
    clients[2].net_close();step(12,clients[:2]);assert s.aborted==gs[0].race and len(dropped)>=2
    # Replay exact old GO and an old-room GO from the genuine server endpoint.
    sock.sendto(old_go,s.players[0].addr)
    sock.sendto(old_go[:4]+b'X'*16+old_go[20:],s.players[0].addr)
    step(4,clients[:2]);stale=Go();assert not clients[0].net_take_go(C.byref(stale))
    s.send=original_send
    for x in clients[:2]:
      gen=C.c_uint64();race=C.c_uint64();assert x.net_abort_pending(C.byref(gen),C.byref(race));assert race.value==gs[0].race;assert not x.net_abort_ack(gen.value+1,race.value)
      assert s.players[clients.index(x)].ack<gen.value
    step(12,clients[:2]);assert all(p.ack<s.generation for p in s.players) and not any(x.net_room_ready() for x in clients[:2])
    for x in clients[:2]:
      gen=C.c_uint64();race=C.c_uint64();assert x.net_abort_pending(C.byref(gen),C.byref(race));assert x.net_abort_ack(gen.value,race.value)
    step(12,clients[:2]);assert all(p.ack==s.generation for p in s.players)
    # A fresh open admits a different join nonce and ignores historical abort.
    assert clients[2].net_open(b'127.0.0.1',port,102)==0;step(12)
    assert len(s.players)==3 and len(s.used_joins)==4 and not clients[2].net_abort_pending(None,None)
    clients[2].net_close();step(8,clients[:2]);assert len(s.players)==2
    clients[0].net_start(3,14,5);step(12,clients[:2]);gs2=[]
    for x in clients[:2]:
      g=Go();assert x.net_take_go(C.byref(g));gs2.append(g)
    assert gs2[0].race>gs[0].race
    assert clients[0].net_race_done();step(12,clients[:2]);assert s.race and not any(x.net_room_ready() for x in clients[:2])
    assert clients[1].net_race_done();step(12,clients[:2]);assert not s.race and all(x.net_room_ready() for x in clients[:2])
    assert all(p.ack==s.generation for p in s.players)
    clients[0].net_close();step(8,clients[1:2]);assert clients[1].net_host_closed() and not clients[1].net_room_ready()
    clients[1].net_close();sock.close()
    print('WV2 client/Python host: join, start, race duplicate, abort teardown ACK, DONE, second race, CLOSED passed')
    # Lose every GO and every ABORT for the owner: the active LOBBY alone
    # establishes that this join observed the race; the idle LOBBY recovers it.
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.setblocking(False);port=sock.getsockname()[1];s=server.Server(sock)
    for i,x in enumerate(clients):assert x.net_open(b'127.0.0.1',port,300+i)==0;step(8,clients[:i+1])
    step(12);owner=s.players[0];original_send=s.send;loss=[]
    def drop_control(p,data):
      if p is owner and data[3] in (server.GO,server.ABORT):loss.append(data[3]);return
      original_send(p,data)
    s.send=drop_control
    clients[0].net_start(1,13,3);step(14)
    oldrace=s.race;oldgen=s.generation;g=Go();assert oldrace and server.GO in loss and not clients[0].net_take_go(C.byref(g))
    clients[2].net_close();step(12,clients[:2])
    gen=C.c_uint64();race=C.c_uint64();assert server.ABORT in loss and clients[0].net_abort_pending(C.byref(gen),C.byref(race))
    assert race.value==oldrace and gen.value>oldgen and owner.ack<gen.value
    step(12,clients[:2]);assert owner.ack<gen.value
    assert clients[0].net_abort_ack(gen.value,race.value);step(8,clients[:2]);assert owner.ack==gen.value
    for x in clients[:2]:x.net_close()
    sock.close()
    print('WV2 dropped all GO and ABORT: active/idle LOBBY creates pending until teardown ACK')
    # A member sees no welcome, active LOBBY, GO, or ABORT at all: only its
    # join-echoed phase-2 LOBBY can distinguish its debt from historical abort.
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.bind(('127.0.0.1',0));sock.setblocking(False);port=sock.getsockname()[1];s=server.Server(sock)
    original_send=s.send;loss=[];phase2_packets=[]
    def drop_victim(p,data):
      if getattr(p,'id',None)==401 and (data[3] in (server.GO,server.ABORT) or (data[3]==server.LOBBY and data[60]!=2)):
        loss.append((data[3],data[60] if data[3]==server.LOBBY else None));return
      if getattr(p,'id',None)==401 and data[3]==server.LOBBY and data[60]==2:phase2_packets.append(data)
      original_send(p,data)
    s.send=drop_victim
    for i,x in enumerate(clients):assert x.net_open(b'127.0.0.1',port,400+i)==0;step(8,clients[:i+1])
    step(12);victim=s.players[1];assert not clients[1].net_lobby_now().contents.connected
    clients[0].net_start(1,13,3);step(14);oldrace=s.race;assert oldrace and (server.LOBBY,1) in loss and any(k==server.GO for k,_ in loss)
    clients[2].net_close();step(14,clients[:2]);gen=C.c_uint64();race=C.c_uint64()
    assert any(k==server.ABORT for k,_ in loss) and clients[1].net_abort_pending(C.byref(gen),C.byref(race)) and race.value==oldrace
    assert victim.ack<gen.value;step(12,clients[:2]);assert victim.ack<gen.value
    assert clients[1].net_abort_ack(gen.value,race.value);step(8,clients[:2]);assert victim.ack==gen.value
    assert phase2_packets;sock.sendto(phase2_packets[0],victim.addr);step(4,clients[:2]);assert not clients[1].net_abort_pending(None,None)
    for x in clients[:2]:x.net_close()
    sock.close()
    print('WV2 phase 2: loss of first LOBBY, all active LOBBY, GO, ABORT requires teardown ACK')
    # Build an unchanged C host source against a private copy of net.h with an
    # ephemeral test port. Never bind the application's shared port 27015.
    probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);probe.bind(('127.0.0.1',0));port=probe.getsockname()[1];probe.close()
    for filename in ('vs_host.c','vs_host.h','gk.h'):
      shutil.copyfile(ROOT/'src'/filename,pathlib.Path(d)/filename)
    (pathlib.Path(d)/'net.h').write_text((ROOT/'src/net.h').read_text().replace('#define NET_PORT 27015','#define NET_PORT %d'%port))
    hostlib=pathlib.Path(d)/'host.dylib'
    subprocess.run(['cc','-dynamiclib','-I'+d,str(pathlib.Path(d)/'vs_host.c'),str(ROOT/'tests/wv2_client_stubs.c'),'-o',str(hostlib)],cwd=ROOT,env=env,check=True)
    host=C.CDLL(str(hostlib));host.vs_host_poll.argtypes=[C.c_double,C.c_char_p];assert host.vs_host_open(0,201)==0
    cc=[]
    for i in range(2):
      path=pathlib.Path(d)/('cclient%d.dylib'%i);shutil.copyfile(lib,path);x=C.CDLL(str(path));x.net_open.argtypes=[C.c_char_p,C.c_int,C.c_uint32];x.net_poll.argtypes=[C.c_double,C.c_int,C.c_char_p,C.c_void_p,C.c_int];x.net_lobby_now.restype=C.POINTER(Lobby);x.net_take_go.argtypes=[C.POINTER(Go)];cc.append(x)
    def cstep(count):
      nonlocal t
      for _ in range(count):
        t+=.1
        for x in cc:x.net_poll(t,0,b'C client',None,0)
        host.vs_host_poll(t,b'C host')
    assert cc[0].net_open(b'127.0.0.1',port,201)==0;cstep(8)
    assert cc[1].net_open(b'127.0.0.1',port,202)==0;cstep(15)
    assert all(x.net_lobby_now().contents.n==2 for x in cc)
    cc[0].net_start(1,13,3);cstep(12)
    cg=[]
    for x in cc:
      g=Go();assert x.net_take_go(C.byref(g));cg.append(g)
    assert cg[0].race==cg[1].race and cg[0].seed==cg[1].seed
    cc[1].net_close();cstep(10);gen=C.c_uint64();race=C.c_uint64();assert cc[0].net_abort_pending(C.byref(gen),C.byref(race)) and race.value==cg[0].race
    cc[0].net_close();host.vs_host_close()
    print('WV2 client/C host: real UDP join, start, abort passed')
    # Silence is a timeout, not a diagnosis of old protocol or confirmed closure.
    blackhole=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);blackhole.bind(('127.0.0.1',0));port=blackhole.getsockname()[1]
    assert cc[0].net_open(b'127.0.0.1',port,201)==0
    cc[0].net_poll(300.,0,b'client',None,0);cc[0].net_poll(306.1,0,b'client',None,0)
    assert cc[0].net_host_closed() and not cc[0].net_lobby_now().contents.connected
    cc[0].net_close();blackhole.close()
    print('WV2 unanswered endpoint: timeout reported without version inference')
if __name__=='__main__':run()
