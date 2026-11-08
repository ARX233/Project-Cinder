"""Real host/net UDP, sliced app finish/recovery; fake clock, UI, physics, scores."""
from pathlib import Path
import importlib.util, subprocess, tempfile, os
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'tests/test_vs_local_host_recovery_udp.py'
spec=importlib.util.spec_from_file_location('fixture',p);f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
app=(ROOT/'src/app.c').read_text()
for anchor in ('if (G.vs_race && vs_recovery_observe_now() && vs_abort_to_lobby()) { menu_frame(0, frame_start); return; }','((VR.local_finished && VR.all_new) || (VG_finish.waiting && G.car.race.over))) steps = 0;','int decision = vs_recovery_finish_ready();'):
 assert app.count(anchor)==1,anchor
base=f.client_source();assert base.count('[3]')==10
client=base.replace('[3]','[4]')
client+='\n#define VS_PROFILE 21\n#define VS_FINISH_WAIT_SECONDS 180.0\nstatic void vs_profile(unsigned char*p){memset(p,0,21);}\n'
for anchor in ('static int vs_recovery_profile(', 'static int vs_receive_gate_check(', 'static int vs_recovery_finish_ready('):
 client+=f.support.block(app,anchor)+'\n'
client+=r"""
static int finished_calls[4], scores[4], aborts[4], initial_fd[4];static uint64_t missing_serial[4];
void wait_frame(int i,double t){load(i);clock_seconds=t;assert(VR.local_finished&&VR.all_new&&G.vs_race);assert(!vs_recovery_observe_now());assert(vs_receive_gate_check(&VG_finish,t,net_receive_drained()&&net_lobby_current_valid())==1);int result=vs_recovery_finish_ready();if(result>0)scores[i]++;assert(result==0);save(i);}
void frame_poll(int i,double t){load(i);clock_seconds=t;unsigned char out[47];assert(vs_recovery_profile(out)==47);net_poll(t,1,"new",out,47);save(i);}
void finish_frame(int i,double t){load(i);clock_seconds=t;assert(net_is_open()&&G.vs_race&&!G.menu.finish);assert(!vs_recovery_observe_now());int gate=vs_receive_gate_check(&VG_finish,t,net_receive_drained()&&net_lobby_current_valid());assert(gate==1);int r=vs_recovery_finish_ready();finished_calls[i]++;if(r>0)scores[i]++;assert(r==0&&VR.local_finished&&VR.flag==VS_RECOVERY_WIRE_FINISHED&&VR.all_new);save(i);}
void record_fd(int i){load(i);initial_fd[i]=N.fd;assert(N.fd>=0);save(i);}
static int matching_peer_abort(void){for(int k=0;k<G.vs_go.n;k++){vs_recovery_wire_extension e;const net_player *p=&G.vs_go.player[k];if(p->id==G.vs_id||!vs_recovery_wire_decode(&e,p->profile,p->profile_len))continue;if(vs_abort_history_query(&VH,p->id,e.nonce,G.vs_go.race,e.seq)==VS_ABORT_MATCH)return 1;}return 0;}
void check_first_missing(int i,double t,unsigned dead){load(i);clock_seconds=t;assert(VR.local_finished&&VR.flag==VS_RECOVERY_WIRE_FINISHED);assert(net_lobby_valid_now()->n==3);assert(!vs_recovery_observe_now());int k=0;while(k<(int)VR.recovery.count&&VR.recovery.members[k].id!=dead)k++;assert(k<(int)VR.recovery.count);assert(VR.recovery.members[k].missing_observations==1);missing_serial[i]=VR.recovery.last_serial;assert(missing_serial[i]);save(i);}
int tick_after_missing(int i,double t,unsigned dead){load(i);clock_seconds=t;assert(VR.local_finished&&G.vs_race);int r=vs_recovery_observe_now();if(r){int k=0;while(k<(int)VR.recovery.count&&VR.recovery.members[k].id!=dead)k++;assert(k<(int)VR.recovery.count&&VR.recovery.members[k].missing_observations>=1);assert((int64_t)(t*1000)-VR.recovery.members[k].missing_since_ms>=2000);if(VR.recovery.reason==VS_RECOVERY_ABORT_MISSING){assert(VR.recovery.missing_id==dead&&VR.recovery.last_serial>missing_serial[i]);assert(VR.recovery.members[k].missing_observations>=2);}else{assert(VR.recovery.reason==VS_RECOVERY_ABORT_LOCAL&&!VH.unknown&&matching_peer_abort());}assert(vs_abort_to_lobby());aborts[i]++;}else {int gate=vs_receive_gate_check(&VG_finish,t,net_receive_drained()&&net_lobby_current_valid());assert(gate==1);int result=vs_recovery_finish_ready();if(result>0)scores[i]++;assert(result==0);}save(i);return r;}
void check_done(int i,double t){load(i);const net_lobby*l=net_lobby_valid_now();assert(aborts[i]==1&&finished_calls[i]==1&&!scores[i]);assert(N.fd==initial_fd[i]&&net_is_open()&&G.in_menu&&!G.vs_race);assert(l->connected&&l->n==3&&l->host==0&&l->player[0].id==101&&l->player[1].id==102&&l->player[2].id==103);assert(VR.flag==VS_RECOVERY_WIRE_ABORT&&VR.advertise_until>t);save(i);}
"""
host=f.HOST+r'''
#include "vs_recovery_wire.h"
int host_finished_profiles(void){if(H.n!=4)return 0;for(int i=0;i<4;i++){vs_recovery_wire_extension e;if(H.p[i].id!=101u+(unsigned)i || !vs_recovery_wire_decode(&e,H.p[i].profile,H.p[i].profile_len) || e.flags!=(i<3?VS_RECOVERY_WIRE_FINISHED:VS_RECOVERY_WIRE_NORMAL) || e.nonce!=1001u+(unsigned)i || e.seq<=7)return 0;}return 1;}
'''
main=r"""
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
#include "vs_host.h"
int host_port(void),host_count(void),client_begin(int),host_finished_profiles(void);void client_open(int,int),client_close(int),record_fd(int),frame_poll(int,double),finish_frame(int,double),wait_frame(int,double),check_first_missing(int,double,unsigned),check_done(int,double);int tick_after_missing(int,double,unsigned);
static void cycle(double t,int count){for(int i=0;i<count;i++)frame_poll(i,t);vs_host_poll(t,"host");for(int i=0;i<count;i++)frame_poll(i,t);}
int main(void){assert(!vs_host_open(0,101));assert(vs_host_enable_local());int port=host_port();for(int i=0;i<4;i++){client_open(i,port);record_fd(i);}for(int i=0;i<1000&&host_count()<4;i++){cycle(1+i*.0001,4);usleep(1000);}assert(host_count()==4);cycle(1.3,4);assert(vs_host_control_ready()&&vs_host_arm_round()&&vs_host_seal_vote()&&vs_host_local_start(3,17,5,1.3));for(int i=0;i<4;i++){int begun=0;for(int n=0;n<1000&&!begun;n++){frame_poll(i,1.4);begun=client_begin(i);if(!begun)usleep(1000);}assert(begun);}vs_host_round_accepted();cycle(1.8,4);finish_frame(0,1.8);cycle(2.4,4);finish_frame(1,2.4);cycle(3.0,4);finish_frame(2,3.0);double t=3.6;for(int n=0;n<1000&&!host_finished_profiles();n++){cycle(t,4);t+=.01;usleep(1000);}assert(host_finished_profiles());double timeout=t+22.;while(host_count()==4&&t<timeout){for(int i=0;i<3;i++)wait_frame(i,t);t+=.1;cycle(t,3);}assert(host_count()==3);cycle(t+.1,3);t+=.1;for(int i=0;i<3;i++)check_first_missing(i,t,104);int done[3]={0};for(int n=0;n<50&&(!done[0]||!done[1]||!done[2]);n++){t+=.1;cycle(t,3);for(int i=0;i<3;i++)if(!done[i])done[i]=tick_after_missing(i,t,104);}for(int i=0;i<3;i++){assert(done[i]);check_done(i,t);}printf("PASS FINISHED 4->3 fresh missing, room and sockets\n");for(int i=0;i<4;i++)client_close(i);vs_host_close();return 0;}
"""
with tempfile.TemporaryDirectory(prefix='finished-four-three-') as tmp:
 d=Path(tmp)
 for name,src in [('host.c',host),('client.c',client),('main.c',main)]:(d/name).write_text(src)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable','-fsanitize=undefined','-fno-sanitize-recover=all','-I'+str(ROOT/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(ROOT/'src/vs_recovery.c'),str(ROOT/'src/vs_recovery_wire.c'),str(ROOT/'src/vs_abort_history.c'),'-o',str(d/'test')],check=True,timeout=30)
 subprocess.run([str(d/'test')],check=True,timeout=20)
