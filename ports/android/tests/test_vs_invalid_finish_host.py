"""Real net and extracted finish gate; fake transport, UI, clock and commit."""
from pathlib import Path
import ast, os, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
app=(root/'src/app.c').read_text()
tree=ast.parse((root/'tests/test_vs_init_failure_host.py').read_text())
pre=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='pre' for t in n.targets))
def take(m):
 start=app.index(m); i=app.index('{',start)+1; depth=1
 while depth:
  depth+=(app[i]=='{')-(app[i]=='}'); i+=1
 return app[start:i]+'\n'
pre=pre.replace('double vs_day_at,vs_abort_note_until;', 'double vs_day_at,vs_day_final_at,vs_day_started,vs_abort_note_until;')
if 'vs_receive_gate VG_go' not in pre:
 pre += '\ntypedef struct { int waiting; double since,last; } vs_receive_gate; static vs_receive_gate VG_go,VG_finish;\n'
pre += '\n#define VS_FINISH_WAIT_SECONDS 180.0\n#include "vs_abort_history.h"\nstatic vs_abort_history VH; static double VH_last_time; static int VH_has_time,VH_abort_unknown;\n'
pre='#include <stdlib.h>\n'+pre
pre=pre.replace('uint32_t vs_id;net_go vs_go;', 'int vs_race; struct {int finish;} menu; uint32_t vs_id;net_go vs_go;')
helpers=''.join(take(m) for m in ('static int vs_recovery_finish_ready(', 'static int vs_receive_gate_check(', 'static void vs_history_lobby(', 'static void vs_session_reset(', 'static int vs_session_open_gk(', 'static int vs_recovery_roster_valid(','static int vs_recovery_accept_go(','static void vs_recovery_begin(','static int vs_recovery_observe_now(','static int vs_own_profile_matches(','static int vs_same_build('))
a=app.index('  net_go go;\n  int may_take_go = 1;',app.index('static void vs_menu(void)')); b=app.index('    menu_vs_loading(m);',a)+len('    menu_vs_loading(m);'); branch=app[a:b]+'\n  }\n'
start=pre.index('const net_lobby *net_lobby_valid_now(void)'); end=pre.index('static void vs_off(void)',start)
import re
pre=re.sub(r'int net_(?:go_pending|receive_drained|lobby_current_valid)\(void\)\{[^\n]*\}\n', '', pre)
pre=re.sub(r'static int vs_recovery_observe_now\(void\)\{[^\n]*\}\n','',pre)
pre=re.sub(r'static int vs_abort_to_lobby\(void\)\{[^\n]*\}\n','',pre)
start=pre.index('const net_lobby *net_lobby_valid_now(void)'); end=pre.index('static void vs_off(void)',start)
pre=pre[:start]+r"""
static int vs_host_is_open(void){return local_host;}
static int vs_abort_to_lobby(void){if (!VR.recovery.initialized || VR.recovery.reason == VS_RECOVERY_NO_ABORT) return 0; abort_count++; net_abandon_race(); vs_recovery_reset(&VR.recovery); return 1;}
static unsigned char packet[1024][2048]; static int packet_len[1024], qread, qwrite;
int gk_send(int peer,const void *data,int len){(void)peer;(void)data;return len;}
int gk_recv(void *out,int max,int *peer){if(qread==qwrite)return 0; *peer=42;int n=packet_len[qread];assert(n<=max);memcpy(out,packet[qread++],n);return n;}
void car_link_deliver(int p,const unsigned char*b,int n){(void)p;(void)b;(void)n;}
"""+pre[end:]
a_finish=app.index('  int vs_finish_ready = 1;',app.index('static void vs_menu(void)'))
b_finish=app.index('\n#else',a_finish)
finish=app[a_finish:b_finish]
finish_stub="\nstatic double frame_start; static void menu_frame(int x,double y){(void)x;(void)y;} typedef struct {int over;} fake_race; static int commit_count;\n"
finish_wrapper="\nstatic void run_finish(fake_race *race){\n"+finish+"\nif (vs_finish_ready && race->over && !G.menu.finish) {commit_count++;G.menu.finish=1;}}\n"
post=r"""
static void p32(unsigned char*p,uint32_t x){p[0]=x;p[1]=x>>8;p[2]=x>>16;p[3]=x>>24;}
static void makeprof(unsigned char *p,uint64_t nonce,uint32_t seq,int flag,uint32_t race,int loaded){unsigned char base[21];vs_profile(base);vs_recovery_wire_extension e={flag,race,nonce,seq};assert(vs_recovery_wire_encode(p,47,base,21,&e));assert(vs_recovery_wire_put_ready(p,47,loaded));}
static void push(int go,int mode){unsigned char h[47],g[47];int flag=(!go && mode>=1 && mode<=6);uint64_t nonce=(!go && mode==3)?999:111;uint32_t seq=(!go && mode==4)?7:(!go && mode!=0)?8:7;uint32_t race=flag?((!go && mode==2)?78:77):(!go && mode==5)?77:0;makeprof(h,nonce,seq,flag,race,!go && mode==5);makeprof(g,(!go && mode==6)?333:222,7,0,0,0);assert(qwrite<1024);unsigned char *p=packet[qwrite];*p++='W';*p++='V';*p++=1;*p++=go?4:2;
 if(go){p32(p,77);p+=4;p32(p,123);p+=4;*p++=0;*p++=10;*p++=2;*p++=1;}else{*p++=2;*p++=1;*p++=0;memset(p,0,6);p+=6;}
 for(int i=0;i<2;i++){*p++=i;p32(p,(!go && mode==5 && !i)?13:11+i);p+=4;if(!go)*p++=0;memset(p,0,16);p+=16;*p++=47;memcpy(p,i?g:h,47);p+=47;}if(go)*p++=0;packet_len[qwrite]=(int)(p-packet[qwrite]);++qwrite;}
static void malformed(int kind){push(0,0);if(kind==0)packet[qwrite-1][83]=0;else packet_len[qwrite-1]=4;}
static void legacy_go(void){unsigned char *p=packet[qwrite-1];assert(p[37]==47);p[37]=21;memmove(p+59,p+85,packet_len[qwrite-1]-85);packet_len[qwrite-1]-=26;}
int main(int argc,char**argv){assert(argc==4);int legacy=atoi(argv[1]),kind=atoi(argv[2]),timeout=atoi(argv[3]);G.vs_id=12;VR.nonce=222;sample_ms=1000;control_ready=go_matches=1;menu_state m={0};m.vs.state=MENU_VS_LOBBY;m.zones=2;assert(net_open_gk(12)==0);net_use_strict_lobby(1);net_set_lobby_observer(vs_history_lobby,NULL);net_require_valid_go(1);push(0,0);push(1,0);if(legacy)legacy_go();net_poll(1,0,"guest",NULL,0);run_go(&m,1);assert(loading_count==1&&VR.recovery.initialized);assert(VR.all_new==!legacy);G.vs_race=1;fake_race race={1};VR.local_finished=1;VR.finished|=1u<<G.vs_go.pcb;VR.finish_wait_at=1;
 push(0,0);if(!legacy)makeprof(packet[qwrite-1]+36,111,8,2,77,0);malformed(kind);net_poll(1.1,0,"guest",NULL,0);sample_ms=1100;assert(net_receive_drained()&&!net_lobby_current_valid());assert(net_lobby_valid_silence(1.1)==0);assert(!vs_recovery_observe_now());if(!legacy)assert((VR.finished&3)==3);run_finish(&race);assert(commit_count==0&&!abort_count);
 if(timeout){sample_ms=3100;run_finish(&race);assert(!commit_count&&abort_count==1);}else{push(0,0);net_poll(1.2,0,"guest",NULL,0);sample_ms=1200;assert(net_lobby_current_valid());assert(!vs_recovery_observe_now());run_finish(&race);assert(commit_count==1&&!abort_count);run_finish(&race);assert(commit_count==1);}
 printf("legacy=%d malformed=%d timeout=%d commits=%d aborts=%d\n",legacy,kind,timeout,commit_count,abort_count);net_close();return 0;}

"""
with tempfile.TemporaryDirectory(prefix='late-go-',dir=os.environ.get('TMPDIR')) as tmp:
 c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'; c.write_text(pre+helpers+finish_stub+finish_wrapper+'static void run_go(menu_state*m,double now){\n'+branch+'}\n'+post)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-fsanitize=undefined,float-cast-overflow','-fno-sanitize-recover=all','-D__ANDROID__','-I'+str(root/'src'),str(c),str(root/'src/net.c'),str(root/'src/vs_recovery.c'),str(root/'src/vs_recovery_wire.c'),str(root/'src/vs_abort_history.c'),'-lm','-o',str(exe)],check=True,timeout=30)
 for legacy in range(2):
  for kind in range(2):
   for timeout in range(2): subprocess.run([str(exe),str(legacy),str(kind),str(timeout)],check=True,timeout=10)
