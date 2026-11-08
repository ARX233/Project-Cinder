"""Compile the actual vs_others_loaded body against a minimal network fixture.

This does not exercise menu_frame, UDP, rendering, race or finish handling.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "src/app.c").read_text()
start = source.index("static int vs_others_loaded(void) {")
end = source.index("\n}\n", start) + 2
function = source[start:end]
fixture = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "net.h"
#define MENU_VS_LOADED 90
static struct { net_go vs_go; int vs_seen_loaded; } G;
static net_lobby lobby;
static int opened = 1;
static const net_lobby *net_lobby_valid_now(void) { return &lobby; }
static int net_is_open(void) { return opened; }
""".replace("static const net_lobby *net_lobby_valid_now", "const net_lobby *net_lobby_valid_now").replace("static int net_is_open", "int net_is_open")
fixture += function + r"""
int main(void) {
  G.vs_go.n=2; G.vs_go.pcb=0;
  G.vs_go.player[0].id=11; G.vs_go.player[1].id=22;
  lobby.connected=1; lobby.n=1; lobby.player[0].id=11;
  assert(!vs_others_loaded());
  lobby.n=2; lobby.player[1].id=22; lobby.player[1].status=0;
  assert(!vs_others_loaded());
  lobby.player[1].status=MENU_VS_LOADED;
  assert(vs_others_loaded());
  lobby.player[1].status=1;
  assert(vs_others_loaded());
  lobby.n=1;
  assert(!vs_others_loaded());
  lobby.n=2; G.vs_go.player[1].id=11;
  assert(!vs_others_loaded());
  G.vs_go.player[1].id=22; opened=0;
  assert(!vs_others_loaded());
  puts("production loading predicate OK");
  return 0;
}
"""
with tempfile.TemporaryDirectory() as d:
    c = Path(d) / "test.c"
    exe = Path(d) / "test"
    c.write_text(fixture)
    subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined", "-fno-sanitize-recover=undefined", "-I", str(root / "src"), str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)

# Exercise Android's real capability freeze and observation path, not just the
# predicate. GO's RDY1 bit announces capability; only a fresh matching lobby
# observation may latch readiness.
def app_function(name):
    begin = source.index(f"static " + ("void" if name == "vs_recovery_begin" else "int") + f" {name}(")
    return source[begin:source.index("\n}\n", begin) + 2]


android_fixture = r"""
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "net.h"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
#define __ANDROID__ 1
#define MENU_VS_LOADED 70
#define VS_GONE 10.0
static struct { net_go vs_go; int vs_seen_loaded; uint32_t vs_id; } G;
static net_lobby lobby;
static int opened = 1;
static uint64_t serial;
static vs_abort_history VH;
static int VH_has_time, VH_abort_unknown;
static double VH_last_time;
typedef struct { int waiting; double since, last; } vs_receive_gate;
static vs_receive_gate VG_go, VG_finish;
/* This fixture is a guest only; reaching the host boundary is a test error. */
static int vs_host_is_open(void) { return 0; }
static int vs_host_loading_lobby_matches(const net_lobby *l, uint32_t race) { (void)l; (void)race; assert(0 && "nonhost fixture"); return 0; }
/* Model net.c's current-race / per-PCB receive evidence, not a universal
 * yes/no stub: tests can expose a wrong race or a different sender slot. */
static uint32_t packet_race;
static unsigned packet_pcbs;
const net_lobby *net_lobby_valid_now(void) { return &lobby; }
int net_is_open(void) { return opened; }
/* Readiness/identity fixture: receive freshness is a known-good fake boundary.
 * Real budget exhaustion and invalid-latest cases live in loading_safety_host. */
int net_receive_drained(void) { return 1; }
int net_lobby_current_valid(void) { return 1; }
int net_host_closed(void) { return 0; }
int net_race_peer_packet_seen(uint32_t race, int pcb) {
  return opened && race != 0 && race == packet_race && pcb >= 0 &&
         pcb < NET_PLAYERS && !!(packet_pcbs & (1u << pcb));
}
uint64_t net_lobby_observations(void) { return serial; }
double net_lobby_valid_silence(double now) { (void)now; return 0.0; }
static double now_ms(void) { return 100.0; }
"""
struct_start = source.index("typedef struct {\n  vs_recovery recovery;")
struct_end = source.index("static vs_recovery_app VR;", struct_start) + len("static vs_recovery_app VR;")
android_fixture += source[struct_start:struct_end] + "\n"
android_fixture += app_function("vs_recovery_begin") + "\n"
android_fixture += app_function("vs_recovery_observe_now") + "\n"
android_fixture += function + r"""
static void profile(net_player *p, uint64_t nonce, uint32_t seq, int ready, int loaded) {
  unsigned char base[VS_RECOVERY_WIRE_BASE_SIZE] = {0};
  vs_recovery_wire_extension e = { VS_RECOVERY_WIRE_NORMAL, 123, nonce, seq };
  assert(vs_recovery_wire_encode(p->profile, sizeof p->profile, base, sizeof base, &e));
  p->profile_len = VS_RECOVERY_WIRE_SIZE;
  if (ready) {
    assert(vs_recovery_wire_put_ready(p->profile, sizeof p->profile, loaded));
    p->profile_len = VS_RECOVERY_READY_SIZE;
  }
}
static void setup(int capable) {
  memset(&G, 0, sizeof G); memset(&VR, 0, sizeof VR);
  memset(&lobby, 0, sizeof lobby); vs_abort_history_reset(&VH); VH_has_time = VH_abort_unknown = 0; VH_last_time = 0; serial = 0; opened = 1;
  packet_race = 0; packet_pcbs = 0;
  G.vs_id = 11; G.vs_go.race = 123; G.vs_go.n = 2; G.vs_go.pcb = 0;
  G.vs_go.player[0].id = 11; G.vs_go.player[1].id = 22;
  if (capable) profile(&G.vs_go.player[1], 99, 10, 1, 1);
  lobby.connected = 1; lobby.n = 2;
  lobby.player[0].id = 11; lobby.player[1].id = 22;
  lobby.player[1] = G.vs_go.player[1];
  vs_recovery_begin(&G.vs_go);
  assert(VR.recovery.initialized);
  assert(!!(VR.ready_capable & 2u) == !!capable);
  assert(!(G.vs_seen_loaded & 2));
}
static void observe(void) { ++serial; assert(!vs_recovery_observe_now()); }
int main(void) {
  setup(1);
  /* Even a matching race packet cannot replace RDY1 observation or nonce. */
  packet_race = 123; packet_pcbs = 1u << 1;
  lobby.player[1].status = 1;
  assert(!vs_others_loaded()); assert(!(G.vs_seen_loaded & 2));
  profile(&lobby.player[1], 100, 11, 1, 1);
  assert(!vs_others_loaded()); assert(!(G.vs_seen_loaded & 2));
  lobby.player[1].profile_len = 0;
  assert(!vs_others_loaded()); assert(!(G.vs_seen_loaded & 2));
  profile(&lobby.player[1], 99, 10, 1, 1);
  /* A GO loaded bit or status 70, even with matching nonce, is insufficient. */
  lobby.player[1].status = MENU_VS_LOADED;
  assert(!vs_others_loaded());
  observe(); /* GO sequence is not newer. */
  assert(!vs_others_loaded());
  profile(&lobby.player[1], 99, 11, 1, 0);
  observe(); assert(!vs_others_loaded());
  /* A bare legacy status 70 cannot impersonate a frozen RDY1 peer. */
  lobby.player[1].profile_len = 0;
  observe(); assert(!vs_others_loaded()); assert(!(G.vs_seen_loaded & 2));
  profile(&lobby.player[1], 100, 12, 1, 1);
  observe(); assert(!vs_others_loaded()); assert(!(G.vs_seen_loaded & 2));
  profile(&lobby.player[1], 99, 12, 1, 1);
  assert(!vs_others_loaded()); /* the predicate itself must not latch */
  observe(); assert(G.vs_seen_loaded & 2); assert(vs_others_loaded());
  lobby.player[1].status = 1; assert(vs_others_loaded());
  profile(&lobby.player[1], 100, 13, 1, 1);
  assert(!vs_others_loaded()); /* a new session cannot use the old latch */
  profile(&lobby.player[1], 99, 13, 1, 0);
  assert(vs_others_loaded()); /* latch survives status/profile readiness changes */
  lobby.n = 1; assert(!vs_others_loaded());
  lobby.n = 2; G.vs_go.player[1].id = 11; assert(!vs_others_loaded());
  G.vs_go.player[1].id = 22; lobby.connected = 0; assert(!vs_others_loaded());
  lobby.connected = 1; opened = 0; assert(!vs_others_loaded());
  setup(0);
  lobby.player[1].status = 0; assert(!vs_others_loaded());
  lobby.player[1].status = MENU_VS_LOADED; assert(vs_others_loaded());
  lobby.player[1].status = 1; assert(vs_others_loaded());
  lobby.n = 1; assert(!vs_others_loaded());
  lobby.n = 2; G.vs_go.player[1].id = 11; assert(!vs_others_loaded());
  G.vs_go.player[1].id = 22; lobby.connected = 0; assert(!vs_others_loaded());
  /* Legacy status 1 requires a packet for the current race and frozen PCB. */
  setup(0);
  lobby.player[1].status = 1;
  assert(!vs_others_loaded()); assert(!(G.vs_seen_loaded & 2));
  packet_race = 124; packet_pcbs = 1u << 1;
  assert(!vs_others_loaded()); assert(!(G.vs_seen_loaded & 2));
  packet_race = 123; packet_pcbs = 1u << 0;
  assert(!vs_others_loaded()); assert(!(G.vs_seen_loaded & 2));
  packet_pcbs = 1u << 1;
  lobby.player[1].status = 0;
  assert(!vs_others_loaded()); assert(!(G.vs_seen_loaded & 2));
  /* Lobby index differs from PCB: the frozen roster determines the lookup. */
  { net_player tmp = lobby.player[0]; lobby.player[0] = lobby.player[1]; lobby.player[1] = tmp; }
  lobby.player[0].status = 1;
  assert(vs_others_loaded()); assert(G.vs_seen_loaded & 2);
  packet_pcbs = 0; lobby.player[0].status = 0;
  assert(vs_others_loaded()); /* observation latches independently of later packets */
  lobby.player[0].id = 0; assert(!vs_others_loaded()); /* presence still required */
  lobby.player[0].id = 22; assert(vs_others_loaded());
  lobby.connected = 0; assert(!vs_others_loaded());
  /* The real history query must detect a matching prior peer ABORT. */
  setup(1); assert(vs_abort_history_record(&VH, 22, 99, 123, 11) == VS_ABORT_MATCH);
  assert(vs_recovery_observe_now());
  puts("Android production loading predicate OK");
  return 0;
}
"""
with tempfile.TemporaryDirectory() as d:
    c = Path(d) / "android_test.c"
    exe = Path(d) / "android_test"
    c.write_text(android_fixture)
    subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined", "-fno-sanitize-recover=undefined",
                    "-I", str(root / "src"), str(c),
                    str(root / "src/vs_recovery.c"),
                    str(root / "src/vs_recovery_wire.c"), str(root / "src/vs_abort_history.c"), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
