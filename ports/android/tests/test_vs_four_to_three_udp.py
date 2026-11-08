"""One process, four swapped contexts; loopback only.
Fake clock/UI/teardown, zero base profile and modeled GO acceptance; no device/APK.
"""
import importlib.util, os, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("hostfixture", ROOT/"tests/test_vs_local_host_recovery_udp.py")
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
profile=f.support.block((ROOT/"src/app.c").read_text(),"static int vs_recovery_profile(")
base_client=f.client_source()
assert base_client.count("[3]") == 10
CLIENT=base_client.replace("[3]","[4]")+r"""
#define VS_PROFILE 21
static void vs_profile(unsigned char *p){memset(p,0,21);}
"""+profile+r"""
double deadline(int i){load(i);double d=VR.advertise_until;save(i);return d;}
void profile_poll(int i,double t){load(i);clock_seconds=t;assert(vs_recovery_profile(profile)==47);net_poll(t,0,"new",profile,47);save(i);}
void check_profile(int i,double t,unsigned flag,unsigned race){load(i);clock_seconds=t;unsigned char out[47];vs_recovery_wire_extension e;assert(vs_recovery_profile(out)==47);assert(vs_recovery_wire_decode(&e,out,47));assert(e.flags==flag&&e.race_id==race&&e.nonce==1001+(unsigned)i);save(i);}
"""
HOST=f.HOST+r"""
#include "vs_recovery_wire.h"
int host_normal(void){if(H.n!=3 || H.owner!=101 || H.p[0].id!=101 || H.p[1].id!=102 || H.p[2].id!=103)return 0;for(int i=0;i<3;i++){vs_recovery_wire_extension e;if(!vs_recovery_wire_decode(&e,H.p[i].profile,H.p[i].profile_len)||e.flags||e.race_id)return 0;}return 1;}
"""
MAIN=r"""
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
#include "net.h"
#include "vs_host.h"
int host_port(void),host_count(void),host_normal(void);void client_open(int,int),client_poll(int,double,int),client_close(int),profile_poll(int,double),check_profile(int,double,unsigned,unsigned);double deadline(int);
int client_begin(int),client_lobby(int),client_observe(int),client_abort(int),client_valid(int,double);unsigned client_race(int);unsigned long long client_serial(int);
static void cycle(double t,int n,int status){for(int i=0;i<n;i++)client_poll(i,t,status);vs_host_poll(t,"host");for(int i=0;i<n;i++)client_poll(i,t,status);}
int main(void){
 assert(!vs_host_open(0,101));assert(vs_host_enable_local());int port=host_port();assert(port>0);
 for(int i=0;i<4;i++)client_open(i,port);
 for(int n=0;n<20&&host_count()<4;n++){cycle(1.+n*.01,4,0);usleep(1000);}
 assert(host_count()==4);cycle(1.3,4,0);assert(vs_host_control_ready());assert(vs_host_arm_round());assert(vs_host_seal_vote());assert(vs_host_local_start(3,17,5,1.3));
 for(int i=0;i<4;i++){client_poll(i,1.4,1);assert(client_begin(i));}
 unsigned race=client_race(0);assert(race);for(int i=1;i<4;i++)assert(client_race(i)==race);vs_host_round_accepted();
 cycle(1.8,4,1);double t=1.8;
 for(int n=0;n<240&&host_count()==4;n++){t+=.1;cycle(t,3,1);}
 assert(t>21.8&&host_count()==3); /* 101, 102 and 103 remain; 104 timed out. */
 for(int n=0;n<20;n++){cycle(t,3,1);if(client_lobby(0)==3&&client_lobby(1)==3&&client_lobby(2)==3)break;t+=.1;}
 unsigned long long serial[3];for(int i=0;i<3;i++){assert(client_lobby(i)==3);serial[i]=client_serial(i);assert(!client_observe(i));}
 double first=t;for(int n=0;n<25;n++){t+=.1;cycle(t,3,1);}assert(t-first>=2.);
 for(int i=0;i<3;i++){assert(client_serial(i)>serial[i]);assert(client_observe(i));assert(client_abort(i));assert(client_valid(i,t));}
 double end=deadline(0);assert(end>t);for(int i=1;i<3;i++)assert(deadline(i)==end);
 for(int i=0;i<3;i++)check_profile(i,t,1,race);
 while(t+.5<end){t+=.5;for(int i=0;i<3;i++)profile_poll(i,t);vs_host_poll(t,"host");for(int i=0;i<3;i++)client_poll(i,t,0);assert(host_count()==3);}
 for(int i=0;i<3;i++){check_profile(i,end-.001,1,race);check_profile(i,end,0,0);}t=end+.5;
 for(int n=0;n<10&&!host_normal();n++){for(int i=0;i<3;i++)profile_poll(i,t);vs_host_poll(t,"host");for(int i=0;i<3;i++)client_poll(i,t,0);t+=.6;}
 assert(host_normal());assert(vs_host_control_ready());assert(vs_host_arm_round());assert(vs_host_seal_vote());assert(vs_host_local_start(3,17,5,t));
 for(int i=0;i<3;i++){int got=0;for(int n=0;n<100&&!got;n++){client_poll(i,t+.01+n*.001,1);got=client_begin(i);}assert(got);}
 unsigned race2=client_race(0);assert(race2==race+1);for(int i=1;i<3;i++)assert(client_race(i)==race2);vs_host_round_accepted();
 printf("PASS 4->3 race %u -> %u; deadline %.3f\n",race,race2,end);for(int i=0;i<4;i++)client_close(i);vs_host_close();return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="four-three-loopback-") as tmp:
 d=Path(tmp)
 for name,src in [("host.c",HOST),("client.c",CLIENT),("main.c",MAIN)]: (d/name).write_text(src)
 subprocess.run([os.environ.get("CC","cc"),"-std=gnu11","-Wall","-Wextra","-Werror","-Wno-unused-function","-Wno-unused-variable","-fsanitize=undefined","-fno-sanitize-recover=all","-I"+str(ROOT/"src"),str(d/"host.c"),str(d/"client.c"),str(d/"main.c"),str(ROOT/"src/vs_recovery.c"),str(ROOT/"src/vs_recovery_wire.c"),str(ROOT/"src/vs_abort_history.c"),"-o",str(d/"test")],check=True,timeout=30)
 subprocess.run([str(d/"test")],check=True,timeout=20)
