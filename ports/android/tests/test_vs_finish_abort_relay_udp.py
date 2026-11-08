"""Limited first-round FINISHED/ABORT relay checks with real UDP and app slices.
Four cases use independent hosts and a pre-physics app-frame slice.
Clock, UI, physical state and result effects are fakes; later-round isolation is untested.
"""
from pathlib import Path
import importlib.util,os,subprocess,tempfile
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('h',R/'tests/test_vs_local_host_recovery_udp.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
app=(R/'src/app.c').read_text()
def rep(s,a,b):
 assert s.count(a)==1,(a,s.count(a));return s.replace(a,b)
def block(a):
 assert app.count(a)==1;return h.support.block(app,a)
s=h.support.source()
for a in ('#include "net.h"','static int vs_host_is_open(void){return 0;}','static void vs_host_disarm_round(void){}'):
 assert s.count(a)==1,(a,s.count(a))
assert s.count('car_clear_junction')>0
client=h.client_source()
host=h.HOST+r'''
#include "vs_recovery_wire.h"
int host_profile(unsigned race,unsigned seq,unsigned nonce){vs_recovery_wire_extension e;for(int j=0;j<H.n;j++)if(H.p[j].id==102 && vs_recovery_wire_decode(&e,H.p[j].profile,H.p[j].profile_len)&&e.flags==1&&e.race_id==race&&e.seq==seq&&e.nonce==nonce)return 1;return 0;}
int host_clean(void){if(H.abort_latched)return 0;for(int i=0;i<NET_PLAYERS;i++)if(H.retry_ready[i])return 0;return 1;}
'''
extra='\n#define VS_FINISH_WAIT_SECONDS 180.0\n'+block('static int vs_receive_gate_check(')+'\n'+block('static int vs_recovery_finish_ready(')+'\n'
client=rep(client,'static unsigned char profile[47];',extra+'static unsigned char profile[47];')
a='  int vs_finish_ready = 1;';start=app.index(a,app.index('static void vs_menu(void)'));end=app.index('\n#else',start);finish=app[start:end]
condition='  if (race->over && !G.menu.finish && !G.vs_closed && !movie && G.story_end_freeze <= 0 && vs_finish_ready) {'
assert app.count(condition)==1
client=rep(client,'int vs_race,vs_closed,paused,vs_wait,vs_seen_loaded,in_menu;','int vs_race,vs_closed,paused,vs_wait,vs_seen_loaded,in_menu,story_end_freeze;')
client+='\ntypedef struct {int over;} fake_race; static double frame_start; static int saves,scores,titles,frame_returns; static void menu_frame(int a,double b){(void)a;(void)b;frame_returns++;save(active);}\n'
client+='static void finish_once(fake_race *race){int movie=0;\n'+finish+'\n'+condition+' saves++; scores++; titles++; }\n}\n'
guard='    if (vs_recovery_observe_now() && vs_abort_to_lobby()) { menu_frame(0, frame_start); return; }'
assert app.count(guard)==1
client+='static void frame_after_net(int i,double t){load(i);clock_seconds=t;fake_race r={1};\n'+guard+'\nfinish_once(&r);save(i);}\n'
client+=r"""
void finish_check(int i,double t){load(i);clock_seconds=t;fake_race r={1};finish_once(&r);save(i);}
int waiting(int i){load(i);int v=VR.local_finished&&VR.flag==VS_RECOVERY_WIRE_FINISHED&&!saves&&!scores&&!titles;save(i);return v;}
void peer_profile(int i,double t,unsigned race,unsigned seq,unsigned nonce){load(i);unsigned char p[47],base[21]={0};vs_recovery_wire_extension e={1,race,nonce,seq};assert(vs_recovery_wire_encode(p,47,base,21,&e));assert(vs_recovery_wire_put_ready(p,47,0));clock_seconds=t;double last=N.last_hello;net_poll(t,0,"peer",p,47);assert(N.last_hello==t && last<t);memcpy(profile,p,47);save(i);}
int seen_profile(int i,unsigned race,unsigned seq,unsigned nonce){load(i);const net_lobby*l=net_lobby_valid_now();vs_recovery_wire_extension e;int ok=net_lobby_current_valid()&&l->n==2&&vs_recovery_wire_decode(&e,l->player[1].profile,l->player[1].profile_len)&&e.flags==1&&e.race_id==race&&e.seq==seq&&e.nonce==nonce;save(i);return ok;}
int clean_abort(int i){load(i);int ok=net_receive_drained()&&net_is_open()&&G.in_menu&&!G.vs_race&&G.menu.state==2&&!saves&&!scores&&!titles;save(i);return ok;}
int frame_check(int i,double t){frame_after_net(i,t);return frame_returns;}
"""
main=r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include "net.h"
#include "vs_host.h"
int host_profile(unsigned,unsigned,unsigned),host_clean(void),seen_profile(int,unsigned,unsigned,unsigned);int host_port(void),host_count(void),client_begin(int),frame_check(int,double),waiting(int),clean_abort(int);unsigned client_race(int);void client_open(int,int),client_poll(int,double,int),client_close(int),finish_check(int,double),peer_profile(int,double,unsigned,unsigned,unsigned);
int main(int argc,char **argv){assert(argc==2);int k=atoi(argv[1]);assert(k>=0&&k<4);assert(!vs_host_open(0,101));assert(vs_host_enable_local());int port=host_port();assert(port>0);for(int i=0;i<2;i++)client_open(i,port);double t=1;
for(int n=0;n<40&&host_count()<2;n++){for(int i=0;i<2;i++)client_poll(i,t,0);vs_host_poll(t,"host");t+=.1;}assert(host_count()==2);for(int i=0;i<2;i++)client_poll(i,t,0);assert(vs_host_control_ready());assert(vs_host_arm_round());assert(vs_host_seal_vote());assert(vs_host_local_start(3,17,5,t));
for(int i=0;i<2;i++){int begun=0;for(int n=0;n<1000;n++){client_poll(i,t+.1,1);if(client_begin(i)){begun=1;break;}usleep(1000);}assert(begun);}unsigned race=client_race(0);assert(race&&race==client_race(1));vs_host_round_accepted();t+=.2;for(int i=0;i<2;i++)client_poll(i,t,1);vs_host_poll(t,"host");for(int i=0;i<2;i++)client_poll(i,t,1);finish_check(0,t);assert(waiting(0));
unsigned races[]={race+1,race,race,race},nonces[]={1002,9999,1002,1002},seq[]={8,8,7,8};assert(host_clean());t+=.6;peer_profile(1,t,races[k],seq[k],nonces[k]);int arrived=0;for(int n=0;n<1000;n++){vs_host_poll(t,"host");if(host_profile(races[k],seq[k],nonces[k])){arrived=1;break;}usleep(1000);}if(!arrived){fprintf(stderr,"host did not retain control %d\n",k);return 2;}if(k<3)assert(host_clean());int seen=0;for(int n=0;n<1000;n++){client_poll(0,t,1);if(seen_profile(0,races[k],seq[k],nonces[k])){seen=1;break;}usleep(1000);}if(!seen){fprintf(stderr,"owner current valid snapshot missing control %d\n",k);return 3;}int observed=frame_check(0,t);if(k<3){assert(!observed);assert(waiting(0));assert(host_clean());}else{assert(observed==1);assert(clean_abort(0));}
printf("PASS case=%d host parsed, owner current valid snapshot, observe=%d; no result effects\n",k,observed);for(int i=0;i<2;i++)client_close(i);vs_host_close();}
"""
with tempfile.TemporaryDirectory(prefix='finish-abort-') as tmp:
 d=Path(tmp)
 for name,text in [('host.c',host),('client.c',client),('main.c',main)]:(d/name).write_text(text)
 cmd=[os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-fsanitize=undefined,float-cast-overflow','-fno-sanitize-recover=all','-I'+str(R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(R/'src/vs_recovery.c'),str(R/'src/vs_recovery_wire.c'),str(R/'src/vs_abort_history.c'),'-lm','-o',str(d/'test')]
 subprocess.run(cmd,check=True,timeout=30)
 for case in range(4):subprocess.run([str(d/'test'),str(case)],check=True,timeout=15)
