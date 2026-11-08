#!/usr/bin/env python3
"""Real host and extracted loading logic; fake transport/UI, not a device."""
import ast,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1]
tree=ast.parse((R/'tests/test_vs_host_reordered_hello.py').read_text())
base=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='c' for t in n.targets))
s=(R/'src/app.c').read_text();p=s.index('static int vs_others_loaded(');i=s.index('{',p)+1;d=1
while d:d+=(s[i]=='{')-(s[i]=='}');i+=1
function=s[p:i]
pre=r"""
#define MENU_VS_LOADED 70
static net_lobby L;
static struct {net_go vs_go;int vs_seen_loaded;} G;
static struct {unsigned capable,ready_capable;uint64_t peer_nonce[NET_PLAYERS];} VR;
const net_lobby *net_lobby_valid_now(void){return &L;}
/* This pure host matcher fixture supplies a drained valid client snapshot;
 * actual RX_BUDGET/invalid-latest boundaries are tested separately. */
int net_receive_drained(void){return 1;}
int net_lobby_current_valid(void){return 1;}
int net_host_closed(void){return 0;}
int net_is_open(void){return 1;}
int net_race_peer_packet_seen(uint32_t r,int k){(void)r;(void)k;return 0;}
"""+function+r"""
"""
post=r"""
int main(void){
 reset();hello(1,12,0,0,0,0,0,1);assert(vs_host_arm_round()&&vs_host_seal_vote());assert(vs_host_local_start(3,13,4,2));
 assert(!vs_host_loading_lobby_matches(&L,H.race_id));vs_host_round_accepted();L=lobby();G.vs_go.n=2;G.vs_go.pcb=0;G.vs_go.race=H.race_id;G.vs_go.player[0].id=11;G.vs_go.player[1].id=12;
 assert(!vs_host_lobby_matches(&L));assert(vs_host_loading_lobby_matches(&L,H.race_id));
 L.player[1].status=70;assert(!vs_host_loading_lobby_matches(&L,H.race_id));assert(!vs_others_loaded()&&!G.vs_seen_loaded);
 hello(1,12,0,70,0,0,0,1);L=lobby();assert(vs_host_loading_lobby_matches(&L,H.race_id));assert(vs_others_loaded()&&(G.vs_seen_loaded&2));
 assert(!vs_host_loading_lobby_matches(&L,H.race_id+1));H.control_ready=0;G.vs_seen_loaded=0;assert(!vs_host_loading_lobby_matches(&L,H.race_id));assert(!vs_others_loaded()&&!G.vs_seen_loaded);H.control_ready=1;assert(vs_others_loaded());
 L.player[1].id=99;assert(!vs_host_loading_lobby_matches(&L,H.race_id));L=lobby();H.p[1].sequence_suspect=1;assert(!vs_host_loading_lobby_matches(&L,H.race_id));H.p[1].sequence_suspect=0;
 H.p[1].from.peer=9;assert(!vs_host_loading_lobby_matches(&L,H.race_id));H.p[1].from.peer=1;
 /* Nonlocal host keeps existing status-based behavior. */
 H.open=0;G.vs_seen_loaded=0;assert(vs_others_loaded()&&(G.vs_seen_loaded&2));
 /* RFR nonce change is a frozen identity mismatch. */
 reset();hello(1,12,1,0,0,0,2,0);assert(vs_host_arm_round()&&vs_host_seal_vote());assert(vs_host_local_start(3,13,4,2));vs_host_round_accepted();hello(1,12,2,70,0,0,3,0);L=lobby();assert(!vs_host_loading_lobby_matches(&L,H.race_id));
 puts("local loading roster matcher PASS");return 0;}
"""
base=base[:base.index('int main(void){')]+pre+post
with tempfile.TemporaryDirectory(prefix='host-loading-match-') as d:
 c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(base);subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=undefined,float-cast-overflow','-fno-sanitize-recover=all','-D__ANDROID__','-I'+str(R/'src'),str(c),str(R/'src/vs_recovery_wire.c'),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
