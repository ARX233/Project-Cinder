"""Real net parser and extracted app GO branch; fake UI, clock and host packets."""
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
pre += '\nstatic int VH_abort_unknown;\n'
# Use real net queue/drain state, not the init-failure fixture's fakes.
pre=pre.replace('static int lobby_current_valid=1;\nint net_lobby_current_valid(void){return lobby_current_valid;}\n', '').replace('int net_go_pending(void){return new_go;}\n', '').replace('int net_receive_drained(void){return 1;}\n', '')
helpers=''.join(take(m) for m in ('static int vs_receive_gate_check(', 'static void vs_history_lobby(', 'static int vs_recovery_roster_valid(','static int vs_recovery_accept_go(','static void vs_recovery_begin(','static int vs_recovery_observe_now(','static int vs_own_profile_matches(','static int vs_same_build('))
a=app.index('  net_go go;\n  int may_take_go = 1;',app.index('static void vs_menu(void)')); b=app.index('    menu_vs_loading(m);',a)+len('    menu_vs_loading(m);'); branch=app[a:b]+'\n  }\n'
start=pre.index('const net_lobby *net_lobby_valid_now(void)'); end=pre.index('static void vs_off(void)',start)
import re
pre=re.sub(r'static int vs_recovery_observe_now\(void\)\{[^\n]*\}\n','',pre)
pre=re.sub(r'static int vs_abort_to_lobby\(void\)\{[^\n]*\}\n','',pre)
start=pre.index('const net_lobby *net_lobby_valid_now(void)'); end=pre.index('static void vs_off(void)',start)
pre=pre[:start]+r"""
static int vs_host_is_open(void){return local_host;}
static int vs_abort_to_lobby(void){if (!VR.recovery.initialized || VR.recovery.reason == VS_RECOVERY_NO_ABORT) return 0; abort_count++; net_abandon_race(); vs_recovery_reset(&VR.recovery); return 1;}
static unsigned char packet[2048]; static int packet_len;
int gk_send(int peer,const void *data,int len){(void)peer;(void)data;return len;}
int gk_recv(void *out,int max,int *peer){(void)peer;assert(packet_len<=max);int n=packet_len;memcpy(out,packet,n);packet_len=0;return n;}
void car_link_deliver(int p,const unsigned char*b,int n){(void)p;(void)b;(void)n;}
"""+pre[end:]
post=r"""
static void p32(unsigned char*p,uint32_t x){p[0]=x;p[1]=x>>8;p[2]=x>>16;p[3]=x>>24;}
static void makeprof(unsigned char *p,uint64_t nonce,uint32_t seq,int flag,uint32_t race,int loaded){unsigned char base[21];vs_profile(base);vs_recovery_wire_extension e={flag,race,nonce,seq};assert(vs_recovery_wire_encode(p,47,base,21,&e));assert(vs_recovery_wire_put_ready(p,47,loaded));}
static void push(int go,int mode){unsigned char h[47],g[47];int flag=(!go && mode>=1 && mode<=4)||(go && mode==6);uint64_t nonce=(!go && mode==3)?999:111;uint32_t seq=(!go && mode==4)?7:(!go && mode!=0)?8:7;uint32_t race=flag?((!go && mode==2)?78:77):(!go && mode==5)?77:0;makeprof(h,nonce,seq,flag,race,!go && mode==5);makeprof(g,222,7,0,0,0);unsigned char *p=packet;*p++='W';*p++='V';*p++=1;*p++=go?4:2;
 if(go){p32(p,77);p+=4;p32(p,123);p+=4;*p++=0;*p++=10;*p++=2;*p++=1;}else{*p++=2;*p++=1;*p++=0;memset(p,0,6);p+=6;}
 for(int i=0;i<2;i++){*p++=i;p32(p,11+i);p+=4;if(!go)*p++=0;memset(p,0,16);p+=16;*p++=47;memcpy(p,i?g:h,47);p+=47;}if(go)*p++=0;packet_len=(int)(p-packet);}
int main(int argc,char**argv){assert(argc==2);int mode=argv[1][0]-'0';G.vs_id=12;VR.nonce=222;sample_ms=1000;control_ready=go_matches=1;menu_state m={0};m.vs.state=MENU_VS_LOBBY;m.zones=2;assert(net_open_gk(12)==0);net_set_lobby_observer(vs_history_lobby,NULL);net_use_strict_lobby(1);net_require_valid_go(1);
 push(0,0);net_poll(1,0,"guest",NULL,0);assert(net_lobby_observations()==1);assert(!VR.recovery.initialized);
 push(0,mode);net_poll(1.1,0,"guest",NULL,0);assert(net_lobby_observations()==2);assert(!VR.recovery.initialized);sample_ms=1100;assert(!vs_recovery_observe_now());
 if(mode==7){push(0,1);net_poll(1.11,0,"guest",NULL,0);push(0,0);net_poll(1.12,0,"guest",NULL,0);}
 if(mode>=8){push(0,0);packet_len=4;net_poll(1.15,0,"guest",NULL,0);assert(!net_lobby_current_valid());push(1,0);net_poll(1.2,0,"guest",NULL,0);assert(net_go_pending()&&!net_lobby_current_valid());sample_ms=1200;run_go(&m,1.2);assert(net_go_pending()&&!loading_count&&!close_count);if(mode==8){push(0,0);net_poll(1.5,0,"guest",NULL,0);assert(net_lobby_current_valid());sample_ms=1500;run_go(&m,1.5);assert(loading_count==1&&!close_count&&!net_go_pending());}else{sample_ms=3200;run_go(&m,3.2);assert(close_count==1&&!loading_count&&!strcmp(closed_note,"LOBBY UNVERIFIED - RECONNECT"));}printf("PASS invalid-lobby mode=%d\n",mode);net_close();return 0;}
 push(1,mode);net_poll(1.2,0,"guest",NULL,0);sample_ms=1200;run_go(&m,1.2);
 if(mode==1||mode==6||mode==7){assert(!loading_count&&abort_count==1&&!VR.recovery.initialized);}else{assert(loading_count==1&&!abort_count&&VR.recovery.initialized);if(mode==5)assert(G.vs_seen_loaded==1);}
 printf("PASS mode=%d loading=%d abort=%d seen_loaded=%d\n",mode,loading_count,abort_count,G.vs_seen_loaded);net_close();return 0;}
"""
with tempfile.TemporaryDirectory(prefix='late-go-',dir=os.environ.get('TMPDIR')) as tmp:
 c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'; c.write_text(pre+helpers+'static void run_go(menu_state*m,double now){\n'+branch+'}\n'+post)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-variable','-Wno-unused-function','-fsanitize=undefined,float-cast-overflow','-fno-sanitize-recover=all','-D__ANDROID__','-I'+str(root/'src'),str(c),str(root/'src/net.c'),str(root/'src/vs_recovery.c'),str(root/'src/vs_recovery_wire.c'),str(root/'src/vs_abort_history.c'),'-lm','-o',str(exe)],check=True)
 for mode in range(10): subprocess.run([str(exe),str(mode)],check=True)
