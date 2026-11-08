#!/usr/bin/env python3
"""Host-only execution of Android vs_off and deadline predicates; no real network."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(source, anchor):
    masked = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                    lambda m: ' ' * len(m.group()), source, flags=re.S)
    start = source.index(anchor)
    opening = masked.index('{', start)
    depth = 1
    for i in range(opening + 1, len(source)):
        depth += (masked[i] == '{') - (masked[i] == '}')
        if not depth:
            return source[start:i + 1]
    raise ValueError('unclosed block: ' + anchor)


class VsOffTimersTest(unittest.TestCase):
    def test_off_resets_timers_and_new_vote(self):
        source = (ROOT / 'src/app.c').read_text(encoding='utf-8')
        off = block(source, 'static void vs_off(void)')
        session_reset = block(source, 'static void vs_session_reset(void)')
        guest = block(source, 'static int vs_day_go_timeout(')
        host = block(source, 'static int vs_host_go_timeout(')
        harness = r"""
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "vs_abort_history.h"
#define __ANDROID__ 1
#define VS_GK_OFF 0
#define MENU_BGM 1
#define MENU_VS_LOBBY 2
typedef struct { int screen; struct { int state, day, hosting, n_found, km, ramp; } vs; int volume; } menu_state;
typedef struct { int connected, me, n, host; } net_lobby;
static struct { menu_state menu; int vs_gk, other_setting; double vs_day_at, vs_day_final_at, vs_day_started; } G;
static struct { int field; } VR;
static vs_abort_history VH;
static double VH_last_time;
static int VH_has_time,VH_abort_unknown;
typedef struct {int waiting;double since,last;} vs_receive_gate;
static vs_receive_gate VG_go,VG_finish;
static int net_open, host_open, nc, hc, scans, gks;
static int net_is_open(void) { return net_open; }
static int vs_host_is_open(void) { return host_open; }
static void net_close(void) { ++nc; net_open = 0; }
static void vs_host_close(void) { ++hc; host_open = 0; }
static void net_scan(int a, int b) { assert(a == 0 && b == 0); ++scans; }
static void gk_stop(void) { ++gks; }
@@SESSION_RESET@@
@@OFF@@
@@GUEST@@
@@HOST@@
static void check(int connected) {
  memset(&G, 0, sizeof G); VR.field = 81;
  nc = hc = scans = gks = 0; net_open = host_open = connected;
  G.menu.screen = MENU_BGM; G.menu.vs.state = MENU_VS_LOBBY; G.menu.vs.day = 1;
  G.menu.vs.hosting = 1; G.menu.vs.n_found = 7; G.menu.vs.km = 29;
  G.menu.vs.ramp = 3; G.menu.volume = 41; G.other_setting = 72;
  G.vs_gk = connected ? 2 : VS_GK_OFF;
  G.vs_day_at = 10; G.vs_day_final_at = 11; G.vs_day_started = 12;
  vs_off();
  assert(G.vs_day_at == 0 && G.vs_day_final_at == 0 && G.vs_day_started == 0);
  assert(nc == 1 && hc == 1 && scans == 1 && gks == connected);
  assert(!G.menu.vs.hosting && !G.menu.vs.n_found && !G.vs_gk && !VR.field);
  assert(G.menu.screen == MENU_BGM && G.menu.vs.state == MENU_VS_LOBBY && G.menu.vs.day == 1);
  assert(G.menu.vs.km == 29 && G.menu.vs.ramp == 3 && G.menu.volume == 41 && G.other_setting == 72);
  /* A later fresh vote starts from its own time, not the old vote's time. */
  G.vs_day_at = 1000; net_lobby lobby = {1, 1, 2, 0};
  assert(!vs_day_go_timeout(&G.menu, &lobby, 1089.99, G.vs_day_at));
  assert(vs_day_go_timeout(&G.menu, &lobby, 1090, G.vs_day_at));
  host_open = 1;
  assert(!vs_host_go_timeout(&G.menu, &lobby, 1089.99, G.vs_day_at));
  assert(vs_host_go_timeout(&G.menu, &lobby, 1090, G.vs_day_at));
  host_open = 0; lobby.me = lobby.host;
  assert(!vs_host_go_timeout(&G.menu, &lobby, 1089.99, G.vs_day_at));
  assert(vs_host_go_timeout(&G.menu, &lobby, 1090, G.vs_day_at));
  lobby.me = 1;
  assert(!vs_host_go_timeout(&G.menu, &lobby, 1090, G.vs_day_at));
  lobby.connected = 0;
  assert(!vs_host_go_timeout(&G.menu, &lobby, 1089.99, G.vs_day_at));
  assert(vs_host_go_timeout(&G.menu, &lobby, 1090, G.vs_day_at));
  lobby.connected = 1; lobby.host = -1;
  assert(!vs_host_go_timeout(&G.menu, &lobby, 1089.99, G.vs_day_at));
  assert(vs_host_go_timeout(&G.menu, &lobby, 1090, G.vs_day_at));
}
int main(void) { check(0); check(1); return 0; }
""".replace('@@SESSION_RESET@@', session_reset).replace('@@OFF@@', off).replace('@@GUEST@@', guest).replace('@@HOST@@', host)
        with tempfile.TemporaryDirectory(prefix='vs-off-timers-') as tmp:
            c_file, exe = Path(tmp) / 'fixture.c', Path(tmp) / 'fixture'
            c_file.write_text(harness, encoding='utf-8')
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-I'+str(ROOT/'src'), str(c_file), str(ROOT/'src/vs_abort_history.c'), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    unittest.main()
