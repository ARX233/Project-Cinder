"""Experimental actual host, net and extracted GO branch; fake UI and I/O."""
from pathlib import Path
import ast, subprocess, tempfile
R=Path(__file__).resolve().parents[1]
s=(R/'src/app.c').read_text()
tree=ast.parse((R/'tests/test_vs_host_epoch_vsday.py').read_text()); ns={'R':R,'s':s}
for n in tree.body:
 if isinstance(n,ast.FunctionDef) and n.name=='take': exec(compile(ast.Module(body=[n],type_ignores=[]),'fixture','exec'),ns)
 if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('f','host','client','main') for t in n.targets): exec(compile(ast.Module(body=[n],type_ignores=[]),'fixture','exec'),ns)
take=ns['take']; host,client,main=(ns[k] for k in ('host','client','main'))
host += '\nvoid assert_host_legacy(void){assert(H.open && H.n==2 && H.p[1].id==12 && H.p[1].profile_len==21 && H.frozen_n==2 && H.frozen[1].id==12 && H.frozen[1].profile_len==21); }\n'
assert client.count('static void vs_off(void){assert(!"unexpected vs_off");}') == 1
client=client.replace('static void vs_off(void){assert(!"unexpected vs_off");}', 'static void vs_off(void){vs_host_close();net_close();}')
client=client.replace('static void menu_vs_closed(menu_state*m,const char*n){(void)m;(void)n;assert(!"unexpected close");}', 'static int close_count;static void menu_vs_closed(menu_state*m,const char*n){(void)m;assert(!strcmp(n,"UNEXPECTED GO - RECONNECT"));close_count++;}')
client=client.replace('int day,n,me,host,day_final','int state,area_go,start,day,n,me,host,day_final').replace('other_zone[4],ramp,km;', 'other_zone[4],ramp,km;char note[128];')
client=client.replace('uint32_t vs_id;double', 'uint32_t vs_id;net_go vs_go;int vs_wait,vs_seen_loaded;double vs_abort_note_until;double')
pre="""
#include "vs_recovery.h"
#include "vs_abort_history.h"
#define MENU_VS_LOBBY 2
#define MENU_VS_OFF 0
typedef struct {vs_recovery recovery; uint64_t nonce,peer_nonce[NET_PLAYERS],host_id;uint32_t seq,peer_seq[NET_PLAYERS],race,last_go;unsigned finished,capable,ready_capable;int all_new,local_finished,echo_confirmed,local_loaded,abort_after_result;double advertise_until,finish_wait_at;unsigned char flag;} vs_recovery_app;
static vs_recovery_app VR;static vs_abort_history VH;static double VH_last_time;static int VH_has_time,VH_abort_unknown;
typedef struct {int waiting;double since,last;} vs_receive_gate;static vs_receive_gate VG_go,VG_finish;
static double now_ms(void){return 4702.;}
extern int mode; extern void assert_host_legacy(void); static int loading_count;
static void menu_vs_aborted(menu_state*m,const char*n){(void)m;(void)n;assert(0);}
static void menu_vs_song(menu_state*m,int s){(void)m;(void)s;}
static void menu_vs_loading(menu_state*m){(void)m;loading_count++;}
static int vs_abort_to_lobby(void){assert(0);return 0;}
"""
helpers=''.join(take(m) for m in ('static int vs_receive_gate_check(', 'static void vs_history_lobby(', 'static int vs_recovery_roster_valid(', 'static int vs_recovery_accept_go(', 'static void vs_recovery_begin(', 'static int vs_recovery_observe_now('))
a=s.index('  net_go go;\n  int may_take_go = 1;',s.index('static void vs_menu(void)'));b=s.index('    menu_vs_loading(m);',a)+len('    menu_vs_loading(m);');branch=s[a:b]+'\n  }\n'
needle='static __typeof__(N) saved[2];static menu_state M;static net_go received[2];'
assert client.count(needle) == 1
client=client.replace(needle,pre+helpers+'\nstatic void run_go(menu_state *m,double now){\n'+branch+'}\n'+needle)
assert client.count('net_use_strict_lobby(1);net_require_valid_go(1);save(i);') == 1
client=client.replace('net_use_strict_lobby(1);net_require_valid_go(1);save(i);','net_use_strict_lobby(1);net_require_valid_go(1);if(i==0)net_set_lobby_observer(vs_history_lobby,NULL);save(i);')
assert client.count('void check_frozen_owner(void)') == 1
client=client.replace('void check_frozen_owner(void)', 'void run_owner_go(void){load(0);M.vs.state=MENU_VS_LOBBY;assert(vs_host_is_open()&&vs_host_control_ready()&&vs_host_round_pending()&&net_go_pending()&&!net_lobby_current_valid()&&net_receive_drained());assert_host_legacy();run_go(&M,4.702);if(mode){assert(!loading_count&&close_count==1&&!vs_host_is_open());}else{assert(loading_count==1&&VR.recovery.initialized&&!VR.all_new&&vs_host_is_open()&&!vs_host_round_pending());assert_host_legacy();}save(0);}\nvoid check_frozen_owner(void)')
assert main.count('assert(dn[id]<128);down[id][dn[id]].n=n;') == 1
main=main.replace('assert(dn[id]<128);down[id][dn[id]].n=n;',"if(id==0&&n>=16&&p[3]==4&&!drop_owner&&go_count[0]==4){const unsigned char bad[4]={'W','V',1,2};assert(dn[0]<128);down[0][dn[0]].n=4;memcpy(down[0][dn[0]++].data,bad,4);}\n assert(dn[id]<128);down[id][dn[id]].n=n;")
main=main.replace('int active;', 'int active,mode;')
main=main.replace('int main(void){uint32_t', 'int main(int argc,char**argv){assert(argc==2);mode=argv[1][0]-\'0\';uint32_t')
assert main.count('memcpy(down[id][dn[id]++].data,b,n);') == 1
main=main.replace('memcpy(down[id][dn[id]++].data,b,n);', 'memcpy(down[id][dn[id]].data,b,n);if(mode && id==0 && n>=16 && p[3]==4 && !drop_owner)down[id][dn[id]].data[8]^=1;dn[id]++;')
main=main.replace('production vs_day + host local epoch retry: PASS (memory I/O, full app GO block untested)', 'PASS real host/net and app GO branch (fake clock, UI and memory transport)')
main=main.replace('void client_init(int);','void run_owner_go(void);void client_init(int);')
main=main.replace('client_poll(0,4.702);assert(take_go(0,&r2,&s2)&&r2==r1&&s2==s1);\n check_frozen_owner();assert(!vs_host_round_invalid());vs_host_round_accepted();assert(!vs_host_round_pending());','client_poll(0,4.702);run_owner_go();(void)r2;(void)s2;')
assert 'client_poll(0,4.702);run_owner_go();' in main and 'check_frozen_owner();assert' not in main
with tempfile.TemporaryDirectory(prefix='host-go-branch-') as tmp:
 d=Path(tmp)
 for name,text in [('host.c',host),('client.c',client),('main.c',main)]: (d/name).write_text(text)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-fsanitize=undefined,float-cast-overflow','-fno-sanitize-recover=all','-D__ANDROID__','-I'+str(R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(R/'src/vs_recovery.c'),str(R/'src/vs_recovery_wire.c'),str(R/'src/vs_abort_history.c'),'-lm','-o',str(d/'test')],check=True,timeout=30)
 for mode in ('0','1'): subprocess.run([str(d/'test'),mode],check=True,timeout=10)
