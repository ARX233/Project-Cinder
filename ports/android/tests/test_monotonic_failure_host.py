#!/usr/bin/env python3
"""Test real non-Apple clock and recovery begin on host, plus existing GO test.

Not proof the whole app works when clocks fail; the Apple path is untested.
UI and networking in the separate real GO-branch test are fakes.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'src/app.c').read_text()


def take(marker):
    start = source.index(marker)
    brace = source.index('{', start)
    depth, i = 1, brace + 1
    while depth:
        depth += (source[i] == '{') - (source[i] == '}')
        i += 1
    return source[start:i] + '\n'


pre = r'''#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include "net.h"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
static int fail_clock, calls;
static time_t seconds;
static long nanoseconds;
static int fake_clock_gettime(clockid_t id, struct timespec *out) {
    assert(id == CLOCK_MONOTONIC);
    ++calls;
    if (fail_clock) return -1; /* Deliberately do not touch *out. */
    out->tv_sec = seconds; out->tv_nsec = nanoseconds;
    return 0;
}
#define clock_gettime fake_clock_gettime
/* Select the non-Apple app branch after including host system headers. */
#undef __APPLE__
'''
mid = r'''#include <string.h>
typedef struct { int waiting; double since, last; } vs_receive_gate;
static vs_receive_gate VG_go, VG_finish;
typedef struct {
    vs_recovery recovery;
    uint64_t peer_nonce[NET_PLAYERS], host_id;
    uint32_t peer_seq[NET_PLAYERS], race;
    unsigned finished, capable, ready_capable;
    int local_finished, local_loaded, all_new, abort_after_result;
    double advertise_until, finish_wait_at;
    unsigned char flag;
} recovery_app;
static recovery_app VR;
static vs_abort_history VH;
static double VH_last_time;
static int VH_has_time;
static struct { uint32_t vs_id; } G;
static net_lobby lobby;
const net_lobby *net_lobby_valid_now(void) { return &lobby; }
'''
post = r'''int main(void) {
    fail_clock = 1;
    for (int i = 0; i < 1000; ++i) assert(now_ms() == -1.0);
    assert(calls == 1000);
    fail_clock = 0; seconds = 123; nanoseconds = 456789000;
    assert(fabs(now_ms() - 123456.789) < 1e-8);
    seconds = 0; nanoseconds = 1;
    assert(fabs(now_ms() - 0.000001) < 1e-15);
    /* Successful reads are converted as supplied, not validated. */
    seconds = -2; nanoseconds = 500000000;
    assert(now_ms() == -1500.0);
    seconds = 0; nanoseconds = -1000000;
    assert(now_ms() == -1.0);

    net_go go = {0};
    go.n = 2; go.pcb = 0; go.race = 77;
    go.player[0].id = 11; go.player[1].id = 12;
    G.vs_id = 11;
    lobby.connected = 1; lobby.n = 2; lobby.host = 0;
    lobby.player[0].id = 11; lobby.player[1].id = 12;
    seconds = 1; nanoseconds = 0;
    vs_recovery_begin(&go);
    assert(VR.recovery.initialized && VR.recovery.last_time_ms == 1000);
    fail_clock = 1;
    int before = calls;
    vs_recovery_begin(&go);
    assert(calls == before + 1);
    assert(!VR.recovery.initialized && !VR.all_new && VR.race == 77);
    puts("real now_ms and vs_recovery_begin, fake clock: PASS");
    return 0;
}
'''
# Preserve the real vs_menu prefix, including screen gate and Android guard.
a = source.index('static void vs_menu(void) {')
b = source.index('  if (m->vs.connect) {', a)
menu_prefix = source[a:b] + '  ++continued;\n}\n'
menu_pre = r'''#include <string.h>
#define __ANDROID__ 1
#define MENU_VS 1
#define MENU_VS_AREA 2
#define MENU_VS_MATCH 3
#define MENU_VS_STAR 4
#define MENU_BGM 5
#define MENU_VS_OFF 0
#define VS_GK_OFF 0
typedef struct { int screen; struct { int day, n_found, state, n, input; char note[128]; } vs; } menu_state;
static struct { menu_state menu; int vs_gk; double vs_day_at; } G;
static int off_count, closed_count, continued, net_opened, host_opened;
static int special;
static double test_now_ms(void) {
    if (special == 1) return NAN;
    if (special == 2) return INFINITY;
    return now_ms();
}
#define now_ms test_now_ms
static void vs_name(char *name, size_t n) { if (n) name[0] = 0; }
int net_is_open(void) { return net_opened; }
static int vs_host_is_open(void) { return host_opened; }
static void vs_off(void) { ++off_count; net_opened = host_opened = 0; G.vs_gk = VS_GK_OFF; }
static void menu_vs_closed(menu_state *m, const char *message) {
    assert(strcmp(message, "CLOCK ERROR - RECONNECT") == 0); ++closed_count;
    m->screen = MENU_VS; m->vs.state = MENU_VS_OFF; m->vs.input = 0;
}
'''
menu_post = r'''static void setup(int screen, int day) {
    memset(&G, 0, sizeof G); G.menu.screen = screen; G.menu.vs.day = day;
    G.menu.vs.state = 1;
    off_count = closed_count = continued = net_opened = host_opened = 0;
    special = fail_clock = 0; seconds = 12; nanoseconds = 0;
}
int main(void) {
    const int screens[] = {MENU_VS, MENU_VS_AREA, MENU_VS_MATCH, MENU_VS_STAR, MENU_BGM};
    for (unsigned i = 0; i < sizeof screens / sizeof screens[0]; ++i) {
        int screen = screens[i];
        setup(screen, screen == MENU_BGM); vs_menu();
        assert(continued == 1 && !off_count && !closed_count);
        setup(screen, screen == MENU_BGM); fail_clock = 1; vs_menu();
        assert(!continued && off_count == 1 && closed_count == 1);
        setup(screen, screen == MENU_BGM); seconds = -1; vs_menu();
        assert(!continued && off_count == 1 && closed_count == 1);
        for (int invalid = 1; invalid <= 2; ++invalid) {
            setup(screen, screen == MENU_BGM); special = invalid; vs_menu();
            assert(!continued && off_count == 1 && closed_count == 1);
        }
    }
    /* A positive sample preceding the BGM vote start fails closed. */
    setup(MENU_BGM, 1); G.vs_day_at = 13; vs_menu();
    assert(!continued && off_count == 1 && closed_count == 1);
    /* A continuing fault after closure must not reset the user's input. */
    G.menu.vs.input = 42; G.menu.vs.n = 9; fail_clock = 1; vs_menu();
    assert(!continued && off_count == 2 && closed_count == 1);
    assert(G.menu.vs.input == 42 && G.menu.vs.n == 0);
    assert(strcmp(G.menu.vs.note, "CLOCK ERROR - RECONNECT") == 0);
    setup(MENU_BGM, 1); G.vs_day_at = 12; vs_menu();
    assert(continued == 1 && !off_count && !closed_count);
    setup(MENU_BGM, 1); G.vs_day_at = 11; vs_menu();
    assert(continued == 1 && !off_count && !closed_count);
    /* An unset start or a non-BGM screen must not trigger rollback protection. */
    setup(MENU_BGM, 1); G.vs_day_at = 0; vs_menu();
    assert(continued == 1 && !off_count && !closed_count);
    setup(MENU_VS, 0); G.vs_day_at = 13; vs_menu();
    assert(continued == 1 && !off_count && !closed_count);
    setup(MENU_BGM, 0); G.vs_day_at = 13; vs_menu();
    assert(!continued && !off_count && !closed_count);
    /* The first failure closes an active screen; repeated failure leaves input intact. */
    setup(MENU_VS, 0); fail_clock = 1; vs_menu();
    assert(off_count == 1 && closed_count == 1 && !continued);
    G.menu.vs.input = 42; G.menu.vs.n = 9;
    vs_menu();
    assert(off_count == 2 && closed_count == 1 && !continued);
    assert(G.menu.vs.input == 42 && G.menu.vs.n == 0);
    assert(strcmp(G.menu.vs.note, "CLOCK ERROR - RECONNECT") == 0);
    /* An OFF VS screen with an active connection must still be closed. */
    setup(MENU_VS, 0); G.menu.vs.state = MENU_VS_OFF; net_opened = 1;
    fail_clock = 1; vs_menu();
    assert(off_count == 1 && closed_count == 1 && !continued);
    /* Non-VS and BGM without a VS day use the preceding screen gate. */
    const int ordinary[] = {99, MENU_BGM};
    for (unsigned i = 0; i < sizeof ordinary / sizeof ordinary[0]; ++i) {
        setup(ordinary[i], 0); fail_clock = 1; vs_menu();
        assert(!continued && !off_count && !closed_count);
        setup(ordinary[i], 0); fail_clock = 1; net_opened = 1; vs_menu();
        assert(!continued && off_count == 1 && !closed_count);
    }
    puts("real vs_menu screen gate and Android clock guard: PASS (stub UI/net)");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='monotonic-failure-') as tmp:
    c = Path(tmp) / 'fixture.c'
    exe = Path(tmp) / 'fixture'
    c.write_text(pre + take('static double now_ms(void)') + mid +
                 take('static void vs_recovery_begin(') + post)
    subprocess.run(['cc', '-std=c11', '-D_POSIX_C_SOURCE=200809L',
                    '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
                    '-fno-sanitize-recover=undefined', '-I' + str(root / 'src'),
                    str(c), str(root / 'src/vs_recovery.c'),
                    str(root / 'src/vs_recovery_wire.c'), '-lm', '-o', str(exe)], check=True)
    env = dict(os.environ, UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    subprocess.run([str(exe)], check=True, env=env)
    c.write_text(pre + take('static double now_ms(void)') + menu_pre +
                 menu_prefix + menu_post)
    subprocess.run(['cc', '-std=c11', '-D_POSIX_C_SOURCE=200809L',
                    '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
                    '-fno-sanitize-recover=undefined', '-I' + str(root / 'src'),
                    str(c), '-lm', '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, env=env)
    # The existing extracted GO branch asserts -1 prevents loading and save.
    subprocess.run([sys.executable, str(root / 'tests/test_vs_init_failure_host.py')],
                   check=True, env=env)
