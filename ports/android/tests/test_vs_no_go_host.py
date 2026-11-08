#!/usr/bin/env python3
"""Run real Android no-GO source slices with host fakes, not real networking."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def c_block(source, anchor):
    # Mask comments and strings without changing character offsets.
    masked = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                    lambda m: ' ' * len(m.group()), source, flags=re.S)
    start = source.index(anchor)
    opening = masked.index('{', start)
    depth = 1
    for pos in range(opening + 1, len(masked)):
        depth += (masked[pos] == '{') - (masked[pos] == '}')
        if not depth:
            return source[start:pos + 1]
    raise ValueError('unclosed block: ' + anchor)


class NoGoHostTest(unittest.TestCase):
    def test_real_policy_and_fallback(self):
        source = (ROOT / 'src/app.c').read_text(encoding='utf-8')
        receive_gate = c_block(source, 'static int vs_receive_gate_check(')
        policy = c_block(source, 'static int vs_day_go_timeout(')
        host_policy = c_block(source, 'static int vs_host_go_timeout(')
        menu = c_block(source, 'static void vs_menu(void)')
        go_pos = menu.index('net_take_go(&go)')
        fallback_pos = menu.index('if (vs_day_go_timeout(')
        host_pos = menu.index('if (vs_host_go_timeout(')
        self.assertLess(go_pos, host_pos)
        self.assertLess(host_pos, fallback_pos)
        go_condition = 'if (m->vs.state == MENU_VS_LOBBY && may_take_go && net_take_go(&go))'
        gate_start = menu.index('int may_take_go = 1;', 0, go_pos)
        gate_end = menu.index(go_condition, gate_start) + len(go_condition)
        go_gate = menu[gate_start:gate_end]
        self.assertIn('vs_host_control_ready()', go_gate)
        self.assertIn('menu_vs_loading(m)', menu[go_pos:fallback_pos])
        # Exercise the original gate and loading call; intervening GO validation is
        # stubbed as successful, not a full vs_menu / real packet test.
        start = menu.rfind('#ifdef __ANDROID__', go_pos, fallback_pos)
        self.assertGreater(start, go_pos)
        end = menu.index('#endif', fallback_pos) + len('#endif')
        fallback = menu[start:end]
        self.assertIn('net_abandon_race()', fallback)
        self.assertIn('G.vs_day_at = 0', fallback)
        harness = r"""
#include <assert.h>
#include <string.h>
#include <math.h>
#define __ANDROID__ 1
#define VS_GONE 10.0
#define MENU_BGM 1
#define MENU_VS_LOBBY 2
#define MENU_VS_LOADING 3
#define MENU_VS_OFF 4
#define MENU_SEARCH 5
typedef struct { int screen; struct { int day, state; } vs; } menu_state;
typedef struct { int connected, me, n, host; } net_lobby;
static struct { double vs_day_at, vs_no_go_note_until; } G;
static net_lobby lobby;
static int opened, local_host, host_closed, control_ready, abandons, aborts, offs, closes, byes;
static double valid_at, ordinary_at;
static net_lobby *net_lobby_valid_now(void) { return &lobby; }
static int net_is_open(void) { return opened; }
static int vs_host_is_open(void) { return local_host; }
static int vs_host_control_ready(void) { return control_ready; }
static int net_host_closed(void) { return host_closed; }
/* Deliberately fake the net API contract; ordinary packets do not refresh valid_at. */
static double net_lobby_valid_silence(double now) {
  return valid_at <= 0 || now < valid_at ? INFINITY : now - valid_at;
}
static void net_abandon_race(void) { ++abandons; }
static void menu_vs_aborted(menu_state *m, const char *s) {
  assert(!strcmp(s, "NO RACE START - BACK IN ROOM")); ++aborts; m->vs.state = MENU_VS_LOBBY;
}
static void vs_off(void) { ++offs; ++byes; }
static void menu_vs_closed(menu_state *m, const char *s) {
  assert(!strcmp(s, "RACE START FAILED - RECONNECT") || !strcmp(s, "HOST LEFT OR CONNECTION LOST"));
  ++closes; m->screen = MENU_SEARCH; m->vs.state = MENU_VS_OFF;
}
typedef struct { int unused; } net_go;
typedef struct { int waiting; double since, last; } vs_receive_gate;
static vs_receive_gate VG_go;
static double clock_ms;
static int pending_go, go_taken;
static double now_ms(void) { return clock_ms; }
static int net_go_pending(void) { return pending_go; }
/* This timeout fixture assumes the current strict lobby is valid. */
static int net_lobby_current_valid(void) { return 1; }
static int net_receive_drained(void) { return 1; }
@@RECEIVE_GATE@@
static int net_take_go(net_go *go) { (void)go; ++go_taken; return pending_go; }
static void menu_vs_loading(menu_state *m) { m->vs.state = MENU_VS_LOADING; }
@@POLICY@@
@@HOST_POLICY@@
static void go_then_fallback(menu_state *m, double now) {
  net_go go;
  clock_ms = now * 1000;
  @@GO_GATE@@ { menu_vs_loading(m); } /* successful validation fake */
  @@FALLBACK@@
}
static void fallback_step(menu_state *m, double now) {
@@FALLBACK@@
}
static void reset(menu_state *m) {
  memset(&VG_go, 0, sizeof VG_go);
  memset(m, 0, sizeof *m); m->screen = MENU_BGM; m->vs.day = 1; m->vs.state = MENU_VS_LOBBY;
  lobby = (net_lobby){1, 1, 2, 0}; G.vs_day_at = 10; G.vs_no_go_note_until = 0;
  opened = 1; local_host = host_closed = abandons = aborts = offs = closes = byes = 0;
  valid_at = 95; ordinary_at = 99; pending_go = go_taken = 0; control_ready = 1;
}
static void unchanged(menu_state *m, double now) {
  fallback_step(m, now);
  assert(!abandons && !aborts && !offs && !closes && !byes);
  assert(G.vs_day_at == 10 && G.vs_no_go_note_until == 0);
}
static void unknown_deadline(menu_state *m) {
  assert(!vs_host_go_timeout(m, &lobby, 99.99, G.vs_day_at));
  go_then_fallback(m, 99.99);
  assert(!offs && !closes && !aborts && !abandons && G.vs_day_at == 10);
  assert(vs_host_go_timeout(m, &lobby, 100, G.vs_day_at));
  go_then_fallback(m, 100);
  assert(offs == 1 && closes == 1 && !aborts && !abandons);
  assert(m->screen == MENU_SEARCH && m->vs.state == MENU_VS_OFF && !G.vs_day_at);
}
int main(void) {
  menu_state m;
  reset(&m); fallback_step(&m, 100);
  assert(abandons == 1 && aborts == 1 && !offs && !closes && !byes);
  assert(m.vs.state == MENU_VS_LOBBY && G.vs_day_at == 0 && G.vs_no_go_note_until == 105);
  /* Fresh ordinary traffic cannot mask an expired valid lobby. */
  reset(&m); valid_at = 89.99; ordinary_at = 99.99; assert(100 - ordinary_at < 1);
  fallback_step(&m, 100);
  assert(abandons == 1 && !aborts && offs == 1 && closes == 1 && m.screen == MENU_SEARCH && !G.vs_day_at);
  /* Exactly ten seconds is still within the inclusive valid-lobby threshold. */
  reset(&m); valid_at = 90; fallback_step(&m, 100);
  assert(aborts == 1 && !offs && !closes && !byes);
  /* Missing lobby timestamp or time moving behind it is unavailable (+infinity). */
  reset(&m); valid_at = 0; fallback_step(&m, 100);
  assert(abandons == 1 && offs == 1 && closes == 1 && !aborts);
  reset(&m); valid_at = 101; fallback_step(&m, 100);
  assert(abandons == 1 && offs == 1 && closes == 1 && !aborts);
  reset(&m); opened = 0; fallback_step(&m, 100);
  assert(abandons == 1 && !aborts && offs == 1 && closes == 1 && m.screen == MENU_SEARCH && !G.vs_day_at);
  reset(&m); host_closed = 1; fallback_step(&m, 100);
  assert(abandons == 1 && !aborts && offs == 1 && closes == 1 && m.screen == MENU_SEARCH && !G.vs_day_at);
  reset(&m); m.screen = MENU_SEARCH; unchanged(&m, 100);
  reset(&m); m.vs.day = 0; unchanged(&m, 100);
  reset(&m); unchanged(&m, 9);
  reset(&m); unchanged(&m, 99.99);
  reset(&m); m.vs.state = MENU_VS_LOADING; unchanged(&m, 100);
  /* A valid GO accepted exactly on the deadline reaches LOADING first. */
  reset(&m); pending_go = 1; go_then_fallback(&m, 100);
  assert(go_taken == 1 && m.vs.state == MENU_VS_LOADING);
  assert(!abandons && !aborts && !offs && !closes && G.vs_day_at == 10);
  reset(&m); go_then_fallback(&m, 100);
  assert(go_taken == 1 && abandons == 1 && aborts == 1);
  reset(&m); G.vs_day_at = 0; fallback_step(&m, 100); assert(!abandons && !offs);
  /* Local owner: no GO at 89.99s, then closes at exactly 90s. */
  reset(&m); local_host = 1; lobby.me = lobby.host;
  go_then_fallback(&m, 99.99);
  assert(go_taken == 1 && !offs && !closes && !abandons && G.vs_day_at == 10);
  go_then_fallback(&m, 100);
  assert(go_taken == 2 && offs == 1 && closes == 1 && !abandons && !aborts);
  assert(m.screen == MENU_SEARCH && G.vs_day_at == 0);
  /* Real GO gate and loading transition are ordered before extracted timeout. */
  reset(&m); local_host = 1; lobby.me = lobby.host; pending_go = 1;
  assert(100 == G.vs_day_at + 90); go_then_fallback(&m, 100);
  assert(go_taken == 1 && m.vs.state == MENU_VS_LOADING);
  assert(!offs && !closes && !abandons && !aborts && G.vs_day_at == 10);
  /* Local host: an exhausted poll cannot consume even an available GO. */
  reset(&m); local_host = 1; lobby.me = lobby.host; pending_go = 1; control_ready = 0;
  go_then_fallback(&m, 99.99);
  assert(go_taken == 0 && pending_go == 1 && m.vs.state == MENU_VS_LOBBY && !offs && !closes);
  go_then_fallback(&m, 100);
  assert(go_taken == 0 && pending_go == 1 && offs == 1 && closes == 1);
  assert(!aborts && !abandons && m.screen == MENU_SEARCH && !G.vs_day_at);
  /* Once the poll is ready, the original GO gate wins at the deadline. */
  reset(&m); local_host = 1; lobby.me = lobby.host; pending_go = 1; control_ready = 0;
  go_then_fallback(&m, 99.99); control_ready = 1; go_then_fallback(&m, 100);
  assert(go_taken == 1 && m.vs.state == MENU_VS_LOADING && !offs && !closes);
  /* A remote host does not consult the local poll budget. */
  reset(&m); pending_go = 1; control_ready = 0; go_then_fallback(&m, 100);
  assert(go_taken == 1 && m.vs.state == MENU_VS_LOADING && !offs && !closes);
  /* A strict external-service logical host has the same deadline. */
  reset(&m); lobby.me = lobby.host; assert(!local_host);
  go_then_fallback(&m, 99.99);
  assert(go_taken == 1 && !offs && !closes && !abandons && G.vs_day_at == 10);
  go_then_fallback(&m, 100);
  assert(go_taken == 2 && offs == 1 && closes == 1 && !abandons && !aborts && !G.vs_day_at);
  reset(&m); lobby.me = lobby.host; pending_go = 1;
  go_then_fallback(&m, 100);
  assert(go_taken == 1 && m.vs.state == MENU_VS_LOADING && !offs && !closes);
  /* A normal guest follows guest fallback rather than the owner branch. */
  reset(&m); assert(!vs_host_go_timeout(&m, &lobby, 100, G.vs_day_at));
  go_then_fallback(&m, 100);
  assert(go_taken == 1 && abandons == 1 && aborts == 1 && !offs && !closes);
  /* Unknown role closes at deadline, never pretending to retain the room. */
  reset(&m); lobby.connected = 0; lobby.me = lobby.host; unknown_deadline(&m);
  reset(&m); lobby.me = lobby.host = -1; unknown_deadline(&m);
  reset(&m); lobby.me = lobby.host = lobby.n; unknown_deadline(&m);
  reset(&m); lobby.n = 0; lobby.me = lobby.host = 0; unknown_deadline(&m);
  reset(&m); lobby.me = -1; unknown_deadline(&m);
  reset(&m); lobby.host = lobby.n; unknown_deadline(&m);
  reset(&m); lobby.connected = 0; pending_go = 1; go_then_fallback(&m, 100);
  assert(m.vs.state == MENU_VS_LOADING && !offs && !closes && !aborts);
  return 0;
}
""".replace('@@RECEIVE_GATE@@', receive_gate).replace('@@POLICY@@', policy).replace('@@HOST_POLICY@@', host_policy).replace('@@FALLBACK@@', fallback).replace('@@GO_GATE@@', go_gate)
        with tempfile.TemporaryDirectory(prefix='vs-no-go-') as tmp:
            c_file = Path(tmp) / 'fixture.c'
            binary = Path(tmp) / 'fixture'
            c_file.write_text(harness, encoding='utf-8')
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=undefined', '-fno-sanitize-recover=undefined',
                            str(c_file), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
