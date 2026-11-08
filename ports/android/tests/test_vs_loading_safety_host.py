#!/usr/bin/env python3
"""Android loading safety: real net receive budget and extracted app branches.

No rendering, APK, phone, materials, or native arcade execution. Transport/UI
boundaries are explicit fakes. Generated C/binaries/logs stay in a new external
output directory (default /Volumes/CodexWork; override WMMT_TEST_OUTPUT_ROOT).
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def c_block(source, anchor):
    masked = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                    lambda match: ' ' * len(match.group()), source, flags=re.S)
    start = source.index(anchor)
    opening = masked.index('{', start)
    depth = 1
    for index in range(opening + 1, len(masked)):
        depth += (masked[index] == '{') - (masked[index] == '}')
        if not depth:
            return source[start:index + 1] + '\n'
    raise ValueError('unclosed source block: ' + anchor)


class LoadingSafetyHostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'src/app.c').read_text(encoding='utf-8')
        cls.menu_source = (ROOT / 'src/menu.c').read_text(encoding='utf-8')
        cls.predicate = c_block(cls.source, 'static int vs_others_loaded(void)')
        begin = cls.source.index('  G.menu.vs.wait_others = vs_waiting;')
        end = cls.source.index('  if (vs_ready) go = 1;', begin) + len('  if (vs_ready) go = 1;')
        cls.ready_block = cls.source[begin:end]
        base = Path(os.environ.get('WMMT_TEST_OUTPUT_ROOT', '/Volumes/CodexWork')).resolve()
        if not base.is_dir() or not str(base).startswith('/Volumes/'):
            raise RuntimeError('WMMT_TEST_OUTPUT_ROOT must be an existing external /Volumes directory')
        cls.output = Path(tempfile.mkdtemp(prefix='vs-loading-safety-', dir=base)).resolve()
        if cls.output.parent != base:
            raise RuntimeError('unexpected host-test output directory')
        print('loading safety output:', cls.output, flush=True)

    def compile_run(self, name, fixture, dependencies):
        c_path = self.output / (name + '.c')
        executable = self.output / name
        # Exclusive-create also works on external filesystems without link/rename support.
        with c_path.open('x', encoding='utf-8') as handle:
            handle.write(fixture)
        env = dict(os.environ, TMPDIR=str(self.output), PYTHONDONTWRITEBYTECODE='1')
        command = ['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-D__ANDROID__',
                   '-fsanitize=undefined', '-fno-sanitize-recover=all',
                   '-I' + str(ROOT / 'src'), str(c_path)]
        command += [str(ROOT / 'src' / item) for item in dependencies]
        command += ['-o', str(executable)]
        compiled = subprocess.run(command, text=True, capture_output=True, timeout=30, env=env)
        with (self.output / (name + '.compile.log')).open('x', encoding='utf-8') as handle:
            handle.write(' '.join(command) + '\n' + compiled.stdout + compiled.stderr)
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        ran = subprocess.run([str(executable)], text=True, capture_output=True, timeout=10, env=env)
        with (self.output / (name + '.run.log')).open('x', encoding='utf-8') as handle:
            handle.write(ran.stdout + ran.stderr)
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        print(ran.stdout, end='', flush=True)

    def test_real_receive_budget_and_loading_ready_block(self):
        fixture = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "net.h"
#include "car.h"
#include "vs_recovery_wire.h"
static unsigned char queued_bytes[520][2048];
static int lengths[520], queued, cursor;
int gk_recv(void *out, int capacity, int *peer) {
  *peer = -1;
  if (cursor == queued) return 0;
  int size = lengths[cursor]; assert(size <= capacity);
  memcpy(out, queued_bytes[cursor++], (size_t)size); return size;
}
int gk_send(int peer, const void *bytes, int length) {
  (void)peer; (void)bytes; (void)length; return 0;
}
void car_link_deliver(int pcb, const unsigned char *bytes, int length) {
  (void)pcb; (void)bytes; (void)length;
}
"""
        fixture += '#include "' + str(ROOT / 'src/net.c') + '"\n'
        fixture += r"""
#define MENU_VS_LOADED 90
#define VS_LOADING_MIN 30
static struct {
  net_go vs_go; int vs_seen_loaded;
  struct { int ready, t; struct { int wait_others; } vs; } menu;
} G;
static struct { unsigned capable, ready_capable; uint64_t peer_nonce[NET_PLAYERS]; } VR;
/* This fixture is a remote guest, not a local-host readiness simulation. */
static int vs_host_is_open(void) { return 0; }
static int vs_host_loading_lobby_matches(const net_lobby *l, uint32_t race) {
  (void)l; (void)race; assert(0 && "unexpected local-host boundary"); return 0;
}
""" + self.predicate + r"""
static int actual_ready_path(void) {
  int vs = 1, go = 0;
  int vs_waiting = vs && G.menu.ready && !vs_others_loaded();
""" + self.ready_block + r"""
  return go;
}
static void enqueue(const unsigned char *bytes, int length) {
  assert(queued < 520); assert(length <= 2048);
  memcpy(queued_bytes[queued], bytes, (size_t)length); lengths[queued++] = length;
}
static void enqueue_loaded_lobby(void) {
  unsigned char bytes[256] = {0}; head(bytes, LOBBY);
  bytes[4] = 2; bytes[5] = 0; bytes[6] = 1;
  int at = 13;
  for (int k = 0; k < 2; ++k) {
    bytes[at] = (unsigned char)k; put32(bytes + at + 1, k ? 22 : 11);
    bytes[at + 5] = MENU_VS_LOADED;
    bytes[at + 6 + NET_NAME] = 21; /* actual old profile length */
    at += 7 + NET_NAME + 21;
  }
  enqueue(bytes, at);
}
static void reset(void) {
  net_close(); queued = cursor = 0;
  assert(net_open_gk(11) == 0); net_use_strict_lobby(1); net_require_valid_go(1);
  memset(&G, 0, sizeof G); memset(&VR, 0, sizeof VR);
  G.vs_go.n = 2; G.vs_go.pcb = 0; G.vs_go.race = 77;
  G.vs_go.player[0].id = 11; G.vs_go.player[1].id = 22;
  G.menu.ready = 1; G.menu.t = VS_LOADING_MIN;
}
int main(void) {
  reset(); enqueue_loaded_lobby();
  const unsigned char junk[4] = {'W','V',1,99};
  for (int k = 0; k < RX_BUDGET - 1; ++k) enqueue(junk, sizeof junk);
  const unsigned char closed[8] = {'W','V',1,9,0,0,0,0}; enqueue(closed, sizeof closed);
  net_poll(1.0, 1, "LOCAL", NULL, 0);
  /* The CLOSED packet is already in the fake transport queue, not in transit. */
  assert(cursor == RX_BUDGET && queued - cursor == 1);
  assert(net_lobby_current_valid() && !net_receive_drained() && !net_host_closed());
  assert(!vs_others_loaded() && !actual_ready_path());
  assert(!(G.vs_seen_loaded & 2));
  net_poll(1.1, 1, "LOCAL", NULL, 0);
  assert(cursor == queued && net_receive_drained() && net_host_closed());
  assert(!vs_others_loaded() && !actual_ready_path());
  /* A drained, current valid old-client roster still starts normally. */
  reset(); enqueue_loaded_lobby(); net_poll(2.0, 1, "LOCAL", NULL, 0);
  assert(net_receive_drained() && net_lobby_current_valid() && !net_host_closed());
  assert(vs_others_loaded() && actual_ready_path() && (G.vs_seen_loaded & 2));
  /* Last-valid snapshot remains populated, but an invalid latest lobby blocks entry. */
  const unsigned char bad_lobby[4] = {'W','V',1,2}; enqueue(bad_lobby, sizeof bad_lobby);
  net_poll(2.1, 1, "LOCAL", NULL, 0);
  assert(net_receive_drained() && !net_lobby_current_valid());
  assert(net_lobby_valid_now()->connected && net_lobby_valid_now()->n == 2);
  assert(!vs_others_loaded() && !actual_ready_path());
  enqueue_loaded_lobby(); net_poll(2.2, 1, "LOCAL", NULL, 0);
  assert(net_receive_drained() && net_lobby_current_valid());
  assert(vs_others_loaded() && actual_ready_path());
  puts("PASS: actual net RX_BUDGET + predicate/ready block: busy, CLOSED, invalid latest, and legacy success");
  net_close(); return 0;
}
"""
        self.compile_run('loading_receive_gate', fixture, ['vs_recovery_wire.c'])

    def test_rfr_without_ready_checks_nonce_and_legacy_still_loads(self):
        start = self.source.index('typedef struct {\n  vs_recovery recovery;')
        end = self.source.index('static vs_recovery_app VR;', start) + len('static vs_recovery_app VR;')
        fixture = r"""
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "net.h"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
#define VS_GONE 10.0
#define MENU_VS_LOADED 90
static struct { uint32_t vs_id; net_go vs_go; int vs_seen_loaded; } G;
static net_lobby lobby; static uint64_t serial;
static vs_abort_history VH;
static int VH_has_time, VH_abort_unknown; static double VH_last_time;
typedef struct { int waiting; double since, last; } vs_receive_gate;
static vs_receive_gate VG_go, VG_finish;
static double now_ms(void) { return 100.0; }
const net_lobby *net_lobby_valid_now(void) { return &lobby; }
uint64_t net_lobby_observations(void) { return serial; }
int net_is_open(void) { return 1; }
int net_receive_drained(void) { return 1; }
int net_lobby_current_valid(void) { return 1; }
int net_host_closed(void) { return 0; }
double net_lobby_valid_silence(double now) { (void)now; return 0; }
int net_race_peer_packet_seen(uint32_t race, int pcb) { (void)race; (void)pcb; return 0; }
static int vs_host_is_open(void) { return 0; }
static int vs_host_loading_lobby_matches(const net_lobby *l, uint32_t race) {
  (void)l; (void)race; assert(0 && "unexpected local-host boundary"); return 0;
}
""" + self.source[start:end] + '\n'
        for anchor in ('static void vs_recovery_begin(', 'static int vs_recovery_observe_now('):
            fixture += c_block(self.source, anchor)
        fixture += self.predicate + r"""
static void profile(net_player *p, uint64_t nonce, uint32_t seq, uint32_t race, int ready, int loaded) {
  unsigned char base[21] = {0};
  vs_recovery_wire_extension e = {VS_RECOVERY_WIRE_NORMAL, race, nonce, seq};
  assert(vs_recovery_wire_encode(p->profile, sizeof p->profile, base, sizeof base, &e));
  p->profile_len = 42;
  if (ready) { assert(vs_recovery_wire_put_ready(p->profile, sizeof p->profile, loaded)); p->profile_len = 47; }
}
static void setup(int length) {
  memset(&G, 0, sizeof G); memset(&VR, 0, sizeof VR); memset(&lobby, 0, sizeof lobby);
  vs_abort_history_reset(&VH); VH_has_time = VH_abort_unknown = 0; VH_last_time = 0;
  memset(&VG_go, 0, sizeof VG_go); memset(&VG_finish, 0, sizeof VG_finish); serial = 0;
  G.vs_id = 11; G.vs_go.n = 2; G.vs_go.pcb = 0; G.vs_go.race = 123;
  G.vs_go.player[0].id = 11; G.vs_go.player[1].id = 22;
  profile(&G.vs_go.player[0], 100, 10, 0, 0, 0);
  if (length >= 42) profile(&G.vs_go.player[1], 99, 10, 0, length == 47, 0);
  else G.vs_go.player[1].profile_len = 21;
  lobby.connected = 1; lobby.n = 2; lobby.me = 0; lobby.host = 1;
  lobby.player[0] = G.vs_go.player[0]; lobby.player[1] = G.vs_go.player[1];
  vs_recovery_begin(&G.vs_go); assert(VR.recovery.initialized);
}
static void observe(void) { ++serial; assert(!vs_recovery_observe_now()); }
int main(void) {
  setup(42); assert((VR.capable & 2) && !(VR.ready_capable & 2) && VR.peer_nonce[1] == 99);
  profile(&lobby.player[1], 101, 11, 123, 0, 0); lobby.player[1].status = MENU_VS_LOADED;
  observe(); assert(VR.recovery.members[1].missing_observations == 1);
  assert(VR.recovery.reason == VS_RECOVERY_NO_ABORT); /* missing-session grace has not elapsed */
  assert(!vs_others_loaded() && !(G.vs_seen_loaded & 2));
  /* The same 42-byte capability without RDY1 may still use legacy loaded status. */
  profile(&lobby.player[1], 99, 11, 123, 0, 0); observe();
  assert(!VR.recovery.members[1].missing_observations);
  assert(vs_others_loaded() && (G.vs_seen_loaded & 2));
  /* Presence identity is rechecked even after its loaded observation latched. */
  profile(&lobby.player[1], 101, 12, 123, 0, 0); observe();
  assert(!vs_others_loaded());
  setup(21); assert(!(VR.capable & 2) && !(VR.ready_capable & 2));
  lobby.player[1].status = MENU_VS_LOADED; observe();
  assert(vs_others_loaded() && (G.vs_seen_loaded & 2));
  /* RDY1 peers still require an accepted newer loaded extension, not status alone. */
  setup(47); assert((VR.capable & 2) && (VR.ready_capable & 2));
  profile(&lobby.player[1], 99, 10, 123, 1, 1); lobby.player[1].status = MENU_VS_LOADED;
  observe(); assert(!vs_others_loaded() && !(G.vs_seen_loaded & 2));
  profile(&lobby.player[1], 99, 11, 123, 1, 1); observe();
  assert(vs_others_loaded() && (G.vs_seen_loaded & 2));
  puts("PASS: frozen RFR1 nonce identity; 42-byte and old 21-byte loading compatibility; RDY1 freshness");
  return 0;
}
"""
        self.compile_run('loading_session_identity', fixture,
                         ['vs_recovery.c', 'vs_recovery_wire.c', 'vs_abort_history.c'])

    def test_actual_car_start_error_branch_requests_abort_or_closes(self):
        failure = c_block(self.source, 'if (car_start(&G.car, course, G.menu.manual, &spec) != 0)')
        loading_helper = c_block(self.menu_source, 'void menu_vs_loading(')
        fixture = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "vs_recovery.h"
#define MENU_VS 1
#define MENU_VS_AREA 2
#define MENU_VS_MATCH 3
#define MENU_BGM 4
#define MENU_VS_OFF 0
#define MENU_VS_LOBBY 2
#define MENU_VS_LOADING 3
typedef struct {
  int screen, course, manual;
  struct { int state, day, loaded, wait_others, match_played; } vs;
} menu_state;
static struct { int car; menu_state menu; } G;
static struct { vs_recovery recovery; int local_loaded, flag; uint32_t race; } VR;
static int abort_calls, abort_handled, abort_reason, abandon_calls, disarm_calls;
static int offs, closes, story_failed, carry_cancelled, refuse_abort;
static void go(menu_state *m, int screen) { m->screen = screen; }
static int car_start(void *car, int course, int manual, const void *spec) {
  (void)car; (void)course; (void)manual; (void)spec; return -1;
}
static void story_carry_cancel(void) { ++carry_cancelled; }
static void story_race_start_failed(void) { ++story_failed; }
/* UI/net effects are fake; the production branch must first transition the
 * real vs_recovery state to ABORT, including when request returns IGNORED. */
static int vs_abort_to_lobby(void) {
  ++abort_calls;
  if (refuse_abort || !VR.recovery.initialized || VR.recovery.reason == VS_RECOVERY_NO_ABORT) return 0;
  ++abort_handled; abort_reason = VR.recovery.reason; ++abandon_calls; ++disarm_calls;
  VR.local_loaded = 0; VR.flag = 1; G.menu.vs.state = MENU_VS_LOBBY;
  vs_recovery_reset(&VR.recovery); return 1;
}
static void vs_off(void) { ++offs; memset(&VR, 0, sizeof VR); }
void menu_vs_closed(menu_state *m, const char *note) {
  assert(note && *note); ++closes; m->vs.state = MENU_VS_OFF; m->screen = MENU_VS;
}
""" + loading_helper + '\n'
        fixture += 'static void actual_error_branch(int vs) { int course = 0, spec = 0;\n' + failure + '\n}\n'
        fixture += r"""
static void setup(int initialize) {
  memset(&G, 0, sizeof G); memset(&VR, 0, sizeof VR);
  abort_calls = abort_handled = abort_reason = abandon_calls = disarm_calls = 0;
  offs = closes = story_failed = carry_cancelled = refuse_abort = 0;
  if (initialize) { uint64_t ids[2] = {11, 22}; assert(vs_recovery_init(&VR.recovery, ids, 2, 11, 77, 1000, 2000)); }
  VR.local_loaded = 1; VR.race = 77;
  G.menu.screen = MENU_VS; menu_vs_loading(&G.menu); G.menu.vs.loaded = 1;
}
int main(void) {
  setup(1); actual_error_branch(1);
  assert(carry_cancelled == 1 && !story_failed);
  assert(abort_calls == 1 && abort_handled == 1 && abort_reason == VS_RECOVERY_ABORT_LOCAL);
  assert(abandon_calls == 1 && disarm_calls == 1 && !offs && !closes);
  assert(G.menu.vs.state == MENU_VS_LOBBY && !VR.local_loaded && VR.flag == 1);
  setup(1); assert(vs_recovery_request_abort(&VR.recovery) == VS_RECOVERY_EMIT_ABORT);
  actual_error_branch(1); /* second request is IGNORED, but recovery must still be handled */
  assert(abort_calls == 1 && abort_handled == 1 && abandon_calls == 1 && !offs && !closes);
  setup(0); actual_error_branch(1);
  assert(!abort_handled && offs == 1 && closes == 1 && G.menu.vs.state == MENU_VS_OFF && !VR.local_loaded);
  setup(1); refuse_abort = 1; actual_error_branch(1);
  assert(abort_calls == 1 && !abort_handled && offs == 1 && closes == 1 && !VR.local_loaded);
  setup(1); actual_error_branch(0);
  assert(carry_cancelled == 1 && story_failed == 1 && !abort_calls && !offs && !closes);
  assert(VR.recovery.reason == VS_RECOVERY_NO_ABORT);
  puts("PASS: actual car_start error branch: real recovery ABORT, pre-latched ABORT, unavailable recovery closes, non-VS unchanged");
  return 0;
}
"""
        self.compile_run('loading_start_failure', fixture, ['vs_recovery.c'])


if __name__ == '__main__':
    unittest.main()
