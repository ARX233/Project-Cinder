#!/usr/bin/env python3
"""Execute production loading hook and observer with deterministic network stubs."""
import ctypes as C
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def block(src, anchor):
    masked = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', lambda m: ' ' * len(m.group()), src, flags=re.S)
    start = src.index(anchor)
    pos = masked.index('{', start)
    end, depth = pos + 1, 1
    while depth:
        if end >= len(src): raise ValueError(anchor)
        depth += (masked[end] == '{') - (masked[end] == '}')
        end += 1
    return src[start:end]

FIXTURE = r"""
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "net.h"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
#define __ANDROID__ 1
#define VS_GONE 10.0
#define MENU_VS 1
#define MENU_VS_MATCH 2
#define MENU_BGM 3
#define MENU_VS_LOADING 4
#define MENU_VS_OFF 0
#define VS_GK_JOIN 9
#define VS_PROFILE 21
typedef struct {int screen,finish; struct {int state,day,n;} vs;} menu_state;
@@VR@@
static vs_abort_history VH;
static int VH_abort_unknown, VH_has_time;
static double VH_last_time;
static struct {unsigned vs_id; int vs_gk,vs_seen_loaded; net_go vs_go;} G;
static int socket_open,closed,host_open,ready,sticky,abort_result;
static uint32_t host_race,retry_race;
static int requests,aborts,retries,attempts,polls,network_polls,after;
static double clock_ms,retry_time,silence;
static net_lobby lobby;
int net_is_open(void){return socket_open;}
int net_host_closed(void){return closed;}
static int vs_host_is_open(void){return host_open;}
static int vs_host_control_ready(void){return ready;}
static int vs_host_loading_abort(uint32_t race){return sticky && race==host_race;}
static void vs_host_retry_guests(double t,uint32_t race){++attempts;retry_time=t;retry_race=race;if(race==host_race)++retries;}
vs_recovery_result vs_recovery_request_abort(vs_recovery *r){++requests;r->reason=1;return VS_RECOVERY_EMIT_ABORT;}
static int vs_abort_to_lobby(void){++aborts;return abort_result;}
static double now_ms(void){return clock_ms;}
const net_lobby *net_lobby_valid_now(void){return &lobby;}
double net_lobby_valid_silence(double t){(void)t;return silence;}
uint64_t net_lobby_observations(void){return 0;}
vs_recovery_result vs_recovery_observe(vs_recovery *r,uint64_t race,uint64_t serial,int64_t ms,const uint64_t *ids,size_t n){(void)r;(void)race;(void)serial;(void)ms;(void)ids;(void)n;return 0;}
static void vs_host_poll(double t,const char *n){(void)t;(void)n;++polls;}
static int vs_host_round_invalid(void){return 0;}
static int vs_host_vote_invalid(void){return 0;}
static int vs_host_round_pending(void){return 0;}
static void vs_off(void){}
static void menu_vs_closed(menu_state *m,const char *s){(void)m;(void)s;}
static void vs_search(double t,const char *n){(void)t;(void)n;}
void net_require_valid_go(int x){(void)x;}
static int vs_recovery_profile(unsigned char *p){(void)p;return 0;}
static int menu_vs_status(menu_state *m){(void)m;return 0;}
void net_poll(double t,int s,const char *n,const unsigned char *p,int z){(void)t;(void)s;(void)n;(void)p;(void)z;++network_polls;}
@@OBSERVE@@
@@HOOK@@
static menu_state menu;
void reset(void){vs_abort_history_reset(&VH);VH_abort_unknown=0;memset(&menu,0,sizeof menu);memset(&VR,0,sizeof VR);memset(&lobby,0,sizeof lobby);memset(&G,0,sizeof G);socket_open=host_open=ready=abort_result=1;closed=sticky=0;host_race=42;VR.race=42;VR.recovery.initialized=1;VR.recovery.last_time_ms=1000;clock_ms=2000;silence=0;menu.screen=MENU_VS;menu.vs.state=MENU_VS_LOADING;lobby.connected=1;lobby.n=1;lobby.me=0;requests=aborts=retries=attempts=polls=network_polls=after=0;retry_time=0;retry_race=0;}
void set(int k,int v){switch(k){case 0:menu.screen=v;break;case 1:menu.vs.state=v;break;case 2:menu.finish=v;break;case 3:VR.recovery.initialized=v;break;case 4:host_open=v;break;case 5:ready=v;break;case 6:sticky=v;break;case 7:VR.race=v;break;case 8:closed=v;break;case 9:socket_open=v;break;case 10:lobby.connected=v;break;case 11:clock_ms=v;break;case 12:abort_result=v;break;case 13:silence=v;break;case 14:host_race=v;break;}}
void history_case(int poison){unsigned char base[21]={0};vs_recovery_wire_extension e={0,0,101,10};G.vs_go.n=2;G.vs_go.pcb=0;G.vs_id=11;G.vs_go.player[1].id=12;vs_recovery_wire_encode(G.vs_go.player[1].profile,sizeof G.vs_go.player[1].profile,base,sizeof base,&e);G.vs_go.player[1].profile_len=42;if(poison) VH.unknown=1;else vs_abort_history_record(&VH,12,101,42,11);}
void run(void){menu_state *m=&menu;double now=clock_ms/1000.;const char *name="fixture";@@POLL@@ ++after;}
int get(int k){switch(k){case 0:return requests;case 1:return aborts;case 2:return retries;case 3:return attempts;case 4:return polls;case 5:return network_polls;case 6:return after;case 7:return retry_race;default:return (int)(retry_time*1000);}}
"""

def fixture_source():
    app = (ROOT/'src/app.c').read_text()
    start = app.index('  if (vs_host_is_open()) vs_host_poll(now, name);', app.index('static void vs_menu('))
    end = app.index('  if (net_host_closed()) {', app.index('  if (vs_host_loading_service(m, now)) return;', start))
    return (FIXTURE.replace('@@VR@@', app[app.index('typedef struct {\n  vs_recovery recovery;'):app.index('static vs_abort_history VH;')])
            .replace('@@OBSERVE@@', block(app, 'static int vs_recovery_observe_now(void)'))
            .replace('@@HOOK@@', block(app, 'static int vs_host_loading_service('))
            .replace('@@POLL@@', app[start:end]))

class LoadingRetry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='vs-loading-retry-')
        source = Path(cls.tmp.name)/'fixture.c'; lib = Path(cls.tmp.name)/'fixture.so'
        source.write_text(fixture_source())
        subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=undefined','-shared','-fPIC','-I',str(ROOT/'src'),str(source),str(ROOT/'src/vs_abort_history.c'),str(ROOT/'src/vs_recovery_wire.c'),'-o',str(lib)], check=True)
        cls.lib=C.CDLL(str(lib)); cls.lib.set.argtypes=[C.c_int,C.c_int]; cls.lib.get.argtypes=[C.c_int]; cls.lib.get.restype=C.c_int
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def setUp(self): self.lib.reset()
    def run_case(self,*settings):
        for key,value in settings: self.lib.set(key,value)
        self.lib.run()
        return [self.lib.get(i) for i in range(9)]
    def test_loading(self):
        self.assertEqual(self.run_case(),[0,0,1,1,1,1,1,42,2000])
        self.lib.reset(); self.assertEqual(self.run_case((0,2))[2],1)
    def test_ineligible(self):
        for setting in [(0,3),(1,1),(2,1),(3,0),(4,0),(5,0),(7,0),(8,1),(9,0)]:
            with self.subTest(setting=setting):
                self.lib.reset(); self.assertEqual(self.run_case(setting)[3],0)
    def test_abort_priority(self):
        for ready in (0,1):
            self.lib.reset(); self.assertEqual(self.run_case((6,1),(5,ready))[:7],[1,1,0,0,1,1,0])
        self.lib.reset(); self.assertEqual(self.run_case((6,1),(12,0))[:4],[1,1,0,0])
    def test_wrong_race(self):
        r=self.run_case((6,1),(14,43)); self.assertEqual(r[:4],[0,0,0,1]); self.assertEqual(r[7],42)
    def test_history_aborts_before_retry(self):
        for poison in (0, 1):
            with self.subTest(poison=poison):
                self.lib.reset(); self.lib.history_case(poison)
                self.assertEqual(self.run_case()[:7],[1,1,0,0,1,1,0])
    def test_real_observer_aborts_before_retry(self):
        for settings in [((10,0),(11,11000)),((13,11),),((11,500),)]:
            with self.subTest(settings=settings):
                self.lib.reset(); self.assertEqual(self.run_case(*settings)[:7],[1,1,0,0,1,1,0])

if __name__=='__main__': unittest.main()
