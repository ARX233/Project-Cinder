#!/usr/bin/env python3
"""Compile actual Android app/menu WV2 slices with real UDP clients; no device/assets.

The fixture stubs rendering and game teardown; this does not execute full app_frame,
Android rendering, real game physics, persistence, or physical devices.
"""
import ctypes as C
import importlib.util
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORK = Path('/Volumes/CodexWork')
spec = importlib.util.spec_from_file_location('wv2_support', ROOT/'tests/test_wv2_client_integration.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)

# Match balanced C blocks; comments/strings cannot affect brace balancing.
def block(src, anchor):
    import re
    masked = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                    lambda m: ' '*len(m.group()), src, flags=re.S)
    start = src.index(anchor)
    pos = masked.index('{', start)
    depth = 1
    end = pos + 1
    while depth:
        if end >= len(src): raise ValueError('unclosed block: '+anchor)
        depth += (masked[end] == '{') - (masked[end] == '}')
        end += 1
    return src[start:end]

FIXTURE = r"""
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "net.h"
#define VS_PROFILE 64
#define MENU_VS_OFF 0
#define MENU_VS_LOBBY 2
#define MENU_VS 7
#define CAR_RACE_RUN 1
#define VS_GONE 10.0
#define MENU_LEAVE 1
typedef struct { int state,start,area_go,day,connect,join,loaded,wait_others;
 int match_t,match_n,match_me,match_played,area_final,day_final,voted,vote,day_voted;
 int n,hosting; char note[128]; } vs_state;
typedef struct { vs_state vs; int finish_story,finish; struct {int open;} pause;
 int screen,t,bars,tap,key,key_held,back,leaving; } menu_state;
static struct { int vs_race,vs_closed,paused,pre_wait,in_menu,vs_wait,vs_seen_loaded; net_go vs_go; double vs_abort_note_until,vs_wait_note_until;
 struct {struct {int state; float countdown;} race;} car;
 struct {int screen_w,screen_h;} hud; menu_state menu; void *perf; } G;
static int clears,menus,off_count,finish_result,ack_clean,ticks,commits;
static double clock_now;
static void go(menu_state *m,int screen) {m->screen=screen;}
static void snd_quiet(void){}
static void car_clear_junction(void *p){(void)p;++clears;}
static void hud_init(void *p,int w,int h){(void)p;(void)w;(void)h;}
static double now_ms(void){return clock_now*1000.;}
static void vs_name(char *p,size_t n){snprintf(p,n,"fixture");}
static void vs_profile(unsigned char *p){memset(p,0,VS_PROFILE);}
static int vs_host_is_open(void){return 0;}
static void vs_host_poll(double t,const char *n){(void)t;(void)n;}
static void menu_frame(float d,double f){(void)d;(void)f;++menus;}
static int menu_vs_status(menu_state *m){(void)m;return 0;}
static void vs_off(void){++off_count;net_close();}
static int menu_finish_update(menu_state *m,float d){(void)m;(void)d;return finish_result;}
@@MENU@@
static int checked_ack(uint64_t generation,uint64_t race) {
  ack_clean = !G.vs_race && G.in_menu && !G.menu.finish && !G.menu.vs.loaded &&
              !G.menu.vs.match_n && clears && !G.vs_go.race && !G.vs_wait && !G.vs_seen_loaded;
  return net_abort_ack(generation,race);
}
#define net_abort_ack checked_ack
@@ABORT@@
#undef net_abort_ack
void fixture_reset(int race) {memset(&G,0,sizeof G);G.vs_race=race;G.menu.vs.state=MENU_VS_LOBBY;G.menu.vs.hosting=1;G.car.race.state=CAR_RACE_RUN;G.menu.finish=1;G.menu.pause.open=1;G.menu.vs.loaded=1;G.menu.vs.match_n=3;G.vs_go.race=42;G.vs_wait=9;G.vs_seen_loaded=7;ack_clean=0;ticks=commits=0;}
void fixture_menu_poll(double now) {clock_now=now;menu_state *m=&G.menu;char name[NET_NAME+1]="fixture";unsigned char profile[VS_PROFILE]={0};@@MENU_POLL@@}
void fixture_race_poll(double now) {clock_now=now;double frame_start=0;@@RACE_POLL@@}
void fixture_finish(int result) {float dt=0;double frame_start=0;finish_result=result;@@FINISH@@}
void fixture_midtick(void) { double frame_start=0; for (int i=0;i<2;i++) {
  ++ticks; net_race_receive();
  @@MIDTICK@@
  ++commits;
} }
int fixture_start_vote(double now) {
  menu_state *m=&G.menu; const net_lobby *l=net_lobby_now();
  m->vs.start=1; m->vs.area_go=0; m->screen=MENU_VS;
  @@START_GATE@@
  return m->vs.area_go;
}
int fixture_ack_clean(void){return ack_clean;}
int fixture_ticks(void){return ticks;}
int fixture_commits(void){return commits;}
int fixture_field(int i){switch(i){case 0:return G.vs_race;case 1:return G.in_menu;case 2:return G.menu.vs.state;case 3:return G.menu.finish;case 4:return G.menu.vs.loaded;case 5:return G.menu.vs.match_n;case 6:return G.menu.vs.hosting;case 7:return clears;case 8:return off_count;case 9:return G.vs_closed;default:return menus;}}
"""

def fixture_source():
    app = (ROOT/'src/app.c').read_text()
    menu = (ROOT/'src/menu.c').read_text()
    race = block(app[app.index('void app_frame(float dt) {'):], 'if (G.vs_race && net_is_open()) {')
    finish = block(app, 'if (G.menu.finish && menu_finish_update(&G.menu, dt) == MENU_LEAVE) {')
    mid = app.index('    car_update(&G.car, &in);', app.index('void app_frame(float dt) {'))
    mid_start = app.index('    if (G.vs_race && net_host_closed())', mid)
    mid_code = (block(app[mid_start:], 'if (G.vs_race && net_host_closed())') + '\n' +
                block(app[mid_start:], 'if (G.vs_race && vs_abort_to_lobby())'))
    start = app.index('  net_poll(now, menu_vs_status(m), name, profile, VS_PROFILE);')
    end = app.index('  const net_lobby *l = net_lobby_now();', start)
    return (FIXTURE.replace('@@MENU@@', block(menu, 'void menu_vs_aborted('))
            .replace('@@ABORT@@', block(app, 'static int vs_abort_to_lobby('))
            .replace('@@MENU_POLL@@', app[start:end]).replace('@@RACE_POLL@@', race)
            .replace('@@FINISH@@', finish).replace('@@MIDTICK@@', mid_code)
            .replace('@@START_GATE@@', block(app, 'if (m->vs.start) {')))

class AppHost(unittest.TestCase):
    def test_three_real_clients(self):
        if not WORK.is_dir(): self.skipTest('CodexWork unavailable')
        with tempfile.TemporaryDirectory(prefix='wv2-app-', dir=WORK) as tmp:
            tmp = Path(tmp); env = dict(os.environ, TMPDIR=str(tmp))
            (tmp/'fixture.c').write_text(fixture_source())
            lib = tmp/'base.dylib'
            subprocess.run(['cc','-dynamiclib','-I'+str(ROOT/'src'),str(tmp/'fixture.c'),
                            str(ROOT/'src/net.c'),str(ROOT/'tests/wv2_client_stubs.c'),'-o',str(lib)],
                           cwd=ROOT, env=env, check=True)
            clients=[]
            for i in range(3):
                path=tmp/f'client{i}.dylib';shutil.copyfile(lib,path);x=C.CDLL(str(path))
                x.net_open.argtypes=[C.c_char_p,C.c_int,C.c_uint32]
                x.net_poll.argtypes=[C.c_double,C.c_int,C.c_char_p,C.c_void_p,C.c_int]
                x.fixture_menu_poll.argtypes=[C.c_double];x.fixture_race_poll.argtypes=[C.c_double]
                x.fixture_start_vote.argtypes=[C.c_double]
                x.net_take_go.argtypes=[C.POINTER(support.Go)]
                x.net_abort_pending.argtypes=[C.POINTER(C.c_uint64),C.POINTER(C.c_uint64)]
                x.net_lobby_now.restype=C.POINTER(support.Lobby)
                clients.append(x)
            sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.addCleanup(sock.close)
            sock.bind(('127.0.0.1',0));sock.setblocking(False)
            srv=support.server.Server(sock); t=100.0
            def step(n=1,live=None, app=False):
                nonlocal t
                live=clients if live is None else live
                for _ in range(n):
                    t+=.1
                    for x in live:
                        if app:x.fixture_menu_poll(t)
                        else:x.net_poll(t,0,b'fixture',None,0)
                    select.select([sock],[],[],.001)
                    while True:
                        try: data,addr=sock.recvfrom(4096)
                        except BlockingIOError:break
                        srv.got(data,addr,t)
                    srv.poll(t)
            for i,x in enumerate(clients):
                self.assertEqual(x.net_open(b'127.0.0.1',sock.getsockname()[1],100+i),0)
                step(8,clients[:i+1])
            step(12);self.assertTrue(all(x.net_lobby_now().contents.n==3 for x in clients))
            clients[0].net_start(2,13,4);step(12)
            gos=[]
            for x in clients:
                g=support.Go();self.assertEqual(x.net_take_go(C.byref(g)),1);gos.append(g)
                x.fixture_reset(1)
            step(8)
            old_go=srv.players[0].go
            send=srv.send; dropped=[]
            def loss(p,data):
                if data[3]==support.server.ABORT and len(dropped)<3:
                    dropped.append(data);return
                send(p,data)
            srv.send=loss
            clients[2].net_close();step(8,clients[:1]);self.assertTrue(dropped)
            sock.sendto(old_go,srv.players[0].addr)
            srv.send=send;step(12,clients[:1],app=True)
            # Client 1 has not polled: net_race_receive inside car_update sees ABORT.
            clients[1].fixture_midtick()
            self.assertEqual(clients[1].fixture_ticks(),1)
            self.assertEqual(clients[1].fixture_commits(),0)
            for x in clients[:2]:
                self.assertEqual([x.fixture_field(i) for i in range(7)],[0,1,2,0,0,0,1])
                self.assertTrue(x.net_is_open());self.assertGreater(x.fixture_field(7),0);self.assertEqual(x.fixture_ack_clean(),1)
                g=support.Go();self.assertEqual(x.net_take_go(C.byref(g)),0)
            step(12,clients[:2]);self.assertTrue(all(p.ack==srv.generation for p in srv.players))
            # New race: no DONE while result screen remains, DONE only on leave.
            clients[0].net_start(3,14,5);step(12,clients[:2])
            for x in clients[:2]:
                g=support.Go();self.assertEqual(x.net_take_go(C.byref(g)),1);x.fixture_reset(1)
                x.fixture_finish(0)
            step(10,clients[:2]);self.assertNotEqual(srv.race,0)
            # Host finishes first; the other participant remains on results.
            # Execute the exact vs_menu start-button block with the real net client.
            clients[0].fixture_finish(1)
            self.assertEqual(clients[0].fixture_field(0),0)
            self.assertEqual(clients[0].fixture_field(1),1)
            step(12,clients[:2])
            self.assertNotEqual(srv.race,0)
            self.assertEqual(clients[0].net_room_ready(),0)
            self.assertEqual(clients[0].fixture_start_vote(t),0)
            clients[1].fixture_finish(1)
            step(12,clients[:2]);self.assertEqual(srv.race,0)
            self.assertEqual(clients[0].net_room_ready(),1)
            self.assertEqual(clients[0].fixture_start_vote(t),1)
            clients[0].net_close();step(10,clients[1:2],app=True)
            self.assertEqual(clients[1].net_is_open(),0);self.assertGreater(clients[1].fixture_field(8),0)
            clients[1].net_close()
            # A survivor misses every GO and every active LOBBY. Phase-2 abort
            # must still force application teardown before the next ACK.
            srv=support.server.Server(sock)
            for i,x in enumerate(clients):
                self.assertEqual(x.net_open(b'127.0.0.1',sock.getsockname()[1],200+i),0)
                step(8,clients[:i+1])
            step(12)
            target=srv.players[1].addr; send=srv.send
            def hide_start(p,data):
                if p.addr==target and (data[3]==support.server.GO or
                    (data[3]==support.server.LOBBY and len(data)>60 and data[60]==1)):
                    return
                send(p,data)
            srv.send=hide_start
            clients[1].fixture_reset(0)
            clients[0].net_start(2,13,4);step(12)
            self.assertEqual(clients[1].net_take_go(C.byref(support.Go())),0)
            clients[2].net_close();step(14,clients[:2],app=True)
            self.assertEqual(clients[1].fixture_ack_clean(),1)
            self.assertEqual(clients[1].fixture_field(1),1)
            step(12,clients[:2]);self.assertTrue(all(p.ack==srv.generation for p in srv.players))
            # Start again, then deliver CLOSED only from inside car_update's
            # network receive. The extracted post-update guard must break before
            # either result commit or another physics tick.
            srv.send=send
            self.assertEqual(clients[2].net_open(b'127.0.0.1',sock.getsockname()[1],302),0)
            step(15)
            clients[0].net_start(1,13,4);step(12)
            for x in clients:
                self.assertEqual(x.net_take_go(C.byref(support.Go())),1)
                x.fixture_reset(1)
            clients[0].net_close()
            step(4,clients[2:3])
            clients[1].fixture_midtick()
            self.assertEqual(clients[1].fixture_ticks(),1)
            self.assertEqual(clients[1].fixture_commits(),0)
            self.assertEqual(clients[1].fixture_field(9),1)
            self.assertEqual(clients[1].fixture_ack_clean(),0)
            for x in clients[1:]: x.net_close()

if __name__ == '__main__': unittest.main()
