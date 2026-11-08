"""Real host/net and extracted GO receive gate; fake transport and UI, not full app."""
from pathlib import Path
import ast, subprocess, tempfile
R=Path(__file__).resolve().parents[1]
s=(R/'src/app.c').read_text()
tree=ast.parse((R/'tests/test_vs_host_epoch_vsday.py').read_text())
ns={'R':R,'s':s}
for node in tree.body:
 if isinstance(node,ast.FunctionDef) and node.name=='take': exec(compile(ast.Module(body=[node],type_ignores=[]),'fixture','exec'),ns)
 if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('f','host','client','main') for t in node.targets): exec(compile(ast.Module(body=[node],type_ignores=[]),'fixture','exec'),ns)
host,client,main=(ns[k] for k in ('host','client','main'))
client=client.replace('int screen,zone,zones,song;', 'int screen,zone,zones,song;')
assert client.count('int day,n,me,host,day_final') == 1
client=client.replace('int day,n,me,host,day_final', 'int state,day,n,me,host,day_final')
needle='static __typeof__(N) saved[2];static menu_state M;static net_go received[2];'
start=s.index('  net_go go;\n  int may_take_go = 1;',s.index('static void vs_menu('))
end=s.index('  if (m->vs.state == MENU_VS_LOBBY && may_take_go && net_take_go(&go))',start)
gate=s[start:end]
assert client.count(needle) == 1
client=client.replace(needle,needle+'\n#define MENU_VS_LOBBY 7\ntypedef struct {int waiting;double since,last;} vs_receive_gate;\nstatic vs_receive_gate VG_go;\nstatic double now_ms(void){return 4702.;}\n'+ns['take']('static int vs_receive_gate_check(')+'\nstatic int gate_passed; static void gate_check(void){menu_state *m=&M;\n'+gate+'\n(void)go; gate_passed=may_take_go;}\n')
assert client.count('int ok=net_take_go(&g);') == 1
client=client.replace('int ok=net_take_go(&g);','if(i==0&&net_go_pending()){M.vs.state=MENU_VS_LOBBY;assert(!net_lobby_current_valid());assert(net_receive_drained());assert(vs_host_control_ready());assert(vs_host_round_pending());gate_check();assert(gate_passed);}int ok=net_take_go(&g);')
assert main.count('assert(dn[id]<128);down[id][dn[id]].n=n;') == 1
main=main.replace('assert(dn[id]<128);down[id][dn[id]].n=n;', "if(id==0&&n>=16&&p[3]==4&&!drop_owner&&go_count[0]==4){const unsigned char bad[4]={'W','V',1,2}; assert(dn[0]<128);down[0][dn[0]].n=4;memcpy(down[0][dn[0]++].data,bad,4);}\n  assert(dn[id]<128);down[id][dn[id]].n=n;")
assert client.count('assert(vs_host_go_matches(&received[0]));') == 1
client=client.replace('assert(vs_host_go_matches(&received[0]));','assert(vs_host_is_open()); assert(vs_host_go_matches(&received[0])); net_go tampered=received[0]; tampered.seed ^= 1; assert(!vs_host_go_matches(&tampered));')
main=main.replace('production vs_day + host local epoch retry: PASS (memory I/O, full app GO block untested)','production receive gate + real host exact GO matcher: PASS (full app GO block untested)')
with tempfile.TemporaryDirectory(prefix='host-gate-',dir='/tmp') as d:
 d=Path(d)
 for name,text in [('host.c',host),('client.c',client),('main.c',main)]: (d/name).write_text(text)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined,float-cast-overflow','-D__ANDROID__','-I'+str(R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(R/'src/vs_recovery_wire.c'),'-o',str(d/'test')],check=True,timeout=30)
 subprocess.run([str(d/'test')],check=True,timeout=10)
