"""Real local host/three WV1 clients; fake clock/UI/teardown, not full app."""
import importlib.util,os,subprocess,tempfile,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('wv1_fixture',R/'tests/test_vs_recovery_wv1_loopback.py')
support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
HOST=r"""
#include <assert.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
static int port;
static int bind_loopback(int fd,const struct sockaddr*a,socklen_t n){(void)a;assert(n==sizeof(struct sockaddr_in));struct sockaddr_in x={0};x.sin_family=AF_INET;x.sin_addr.s_addr=htonl(INADDR_LOOPBACK);int r=bind(fd,(const struct sockaddr*)&x,sizeof x);if(!r){socklen_t l=sizeof x;assert(!getsockname(fd,(struct sockaddr*)&x,&l));port=ntohs(x.sin_port);}return r;}
#define bind bind_loopback
#include "vs_host.c"
#undef bind
int host_port(void){return port;}
int host_count(void){return H.n;}
"""
EXTRA=r"""
#include <assert.h>
static __typeof__(N) ns[3];static __typeof__(G) gs[3];static __typeof__(VR) vrs[3];static vs_abort_history histories[3];static double history_times[3];static int history_has_times[3],history_unknowns[3];static vs_receive_gate go_gates[3],finish_gates[3];static unsigned char profiles[3][47];static int active;
static void load(int i){active=i;N=ns[i];G=gs[i];VR=vrs[i];VH=histories[i];VH_last_time=history_times[i];VH_has_time=history_has_times[i];VH_abort_unknown=history_unknowns[i];VG_go=go_gates[i];VG_finish=finish_gates[i];memcpy(profile,profiles[i],sizeof profile);}
static void save(int i){ns[i]=N;gs[i]=G;vrs[i]=VR;histories[i]=VH;history_times[i]=VH_last_time;history_has_times[i]=VH_has_time;history_unknowns[i]=VH_abort_unknown;go_gates[i]=VG_go;finish_gates[i]=VG_finish;memcpy(profiles[i],profile,sizeof profile);}
void client_open(int i,int port){memset(&N,0,sizeof N);N.fd=-1;memset(&G,0,sizeof G);memset(&VR,0,sizeof VR);assert(fixture_open(port,101+i,1001+i)==0);save(i);}
void client_poll(int i,double t,int status){load(i);fixture_poll(t,status);save(i);}
int client_begin(int i){load(i);int r=fixture_begin();save(i);return r;}
int client_lobby(int i){load(i);int r=net_lobby_valid_now()->n;save(i);return r;}
unsigned long long client_serial(int i){load(i);uint64_t r=net_lobby_observations();save(i);return r;}
int client_observe(int i){load(i);int r=fixture_observe();save(i);return r;}
int client_abort(int i){load(i);int r=fixture_abort();save(i);return r;}
int client_valid(int i,double now){load(i);int r=net_is_open()&&G.in_menu&&!G.vs_race&&G.menu.state==2&&!VR.local_loaded&&VR.flag==1&&VR.race==G.vs_go.race&&VR.nonce==1001+(unsigned)i&&fabs(VR.advertise_until-(now+30.))<1e-8;save(i);return r;}
unsigned client_race(int i){load(i);unsigned r=G.vs_go.race;save(i);return r;}
int client_history_isolated(int i,unsigned race){load(i);int other=1-i;int r=VH.used==1&&!VH.unknown && vs_abort_history_query(&VH,101+other,1001+other,race,7)==VS_ABORT_MATCH && vs_abort_history_query(&VH,101+i,1001+i,race,7)==VS_ABORT_NO_MATCH;save(i);return r;}
void client_signal(int i,double t){unsigned char base[21]={0},p[47];load(i);vs_recovery_wire_extension e={VR.flag,VR.race,VR.nonce,8};assert(vs_recovery_wire_encode(p,sizeof p,base,sizeof base,&e));assert(vs_recovery_wire_put_ready(p,sizeof p,VR.local_loaded));clock_seconds=t;net_poll(t,0,"new",p,47);save(i);}
int client_seen_abort(int i,int k,unsigned race){load(i);const net_lobby*l=net_lobby_valid_now();vs_recovery_wire_extension e;int ok=l->n==2&&vs_recovery_wire_decode(&e,l->player[k].profile,l->player[k].profile_len)&&e.flags==1&&e.race_id==race&&e.nonce==1001+(unsigned)k&&e.seq==8;int ready=-1;ok=ok&&vs_recovery_wire_read_ready(l->player[k].profile,l->player[k].profile_len,&ready)&&!ready;save(i);return ok;}
void client_close(int i){load(i);net_close();save(i);}
"""
MAIN=r"""
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
#include "net.h"
#include "vs_host.h"
int host_port(void),host_count(void);void client_open(int,int),client_poll(int,double,int),client_close(int),client_signal(int,double);
int client_begin(int),client_lobby(int),client_observe(int),client_abort(int),client_valid(int,double),client_seen_abort(int,int,unsigned),client_history_isolated(int,unsigned);unsigned client_race(int);unsigned long long client_serial(int);
int main(void){
 assert(!vs_host_open(0,101));assert(vs_host_enable_local());int port=host_port();assert(port>0);
 for(int i=0;i<3;i++){client_open(i,port);client_poll(i,1.,0);vs_host_poll(1.,"host");}
 for(int n=0;n<100&&host_count()<3;n++){usleep(1000);vs_host_poll(1.,"host");}
 for(int i=0;i<3;i++)client_poll(i,1.1,0);
 assert(host_count()==3);assert(vs_host_control_ready());assert(vs_host_arm_round());assert(vs_host_seal_vote());assert(vs_host_local_start(3,17,5,1.1));
 for(int i=0;i<3;i++){client_poll(i,1.2,1);assert(client_begin(i));}
 unsigned race=client_race(0);assert(race&&race==client_race(1)&&race==client_race(2));vs_host_round_accepted();
 for(int i=0;i<3;i++)client_poll(i,1.8,1);vs_host_poll(1.8,"host");
 for(int n=1;n<=230;n++){double t=1.8+n*.1;for(int i=0;i<2;i++)client_poll(i,t,1);vs_host_poll(t,"host");for(int i=0;i<2;i++)client_poll(i,t,1);if(host_count()==2)break;}
 assert(host_count()==2);
 double t=22.1; /* last peer seen at 1.8, timeout strictly >20 */
 /* Establish first fresh missing roster observations. */
 for(int n=0;n<10;n++){t+=.1;for(int i=0;i<2;i++)client_poll(i,t,1);vs_host_poll(t,"host");for(int i=0;i<2;i++)client_poll(i,t,1);if(client_lobby(0)==2&&client_lobby(1)==2)break;}
 assert(client_lobby(0)==2&&client_lobby(1)==2);
 unsigned long long serial[2]={client_serial(0),client_serial(1)};for(int i=0;i<2;i++)assert(!client_observe(i));
 for(int n=0;n<25;n++){t+=.1;for(int i=0;i<2;i++)client_poll(i,t,1);vs_host_poll(t,"host");for(int i=0;i<2;i++)client_poll(i,t,1);}
 for(int i=0;i<2;i++){assert(client_serial(i)>serial[i]);assert(client_observe(i));assert(client_abort(i));assert(client_valid(i,t));}
 for(int n=0;n<10;n++){t+=.6;for(int i=0;i<2;i++)client_signal(i,t);vs_host_poll(t,"host");for(int i=0;i<2;i++)client_poll(i,t,0);if(client_seen_abort(0,1,race)&&client_seen_abort(1,0,race))break;}
 assert(client_seen_abort(0,1,race)&&client_seen_abort(1,0,race));
 assert(client_history_isolated(0,race)&&client_history_isolated(1,race));
 for(int i=0;i<3;i++)client_close(i);vs_host_close();puts("local host timeout recovery: PASS");return 0;}
"""
def client_source():
 s=support.source().replace('#include "net.h"','#include "net.c"\n#include "vs_host.h"')
 s=s.replace('static int vs_host_is_open(void){return 0;}','static int active;\n#define vs_host_is_open() (active==0 && real_host_open())\nstatic int real_host_open(void){return vs_host_is_open();}')
 # define wrapper before macro so it calls the actual host function
 s=s.replace('static int active;\n#define vs_host_is_open() (active==0 && real_host_open())\nstatic int real_host_open(void){return vs_host_is_open();}','static int active;\nstatic int real_host_open(void){return vs_host_is_open();}\n#define vs_host_is_open() (active==0 && real_host_open())')
 s=s.replace('static void vs_host_disarm_round(void){}','')
 s=s.replace('car_clear_junction','fixture_car_clear_junction')
 return s+EXTRA.replace('static int active;','')
class LocalHostRecovery(unittest.TestCase):
 def test_real_host_timeout(self):
  with tempfile.TemporaryDirectory(prefix='vs-local-host-') as tmp:
   d=Path(tmp)
   for name,src in [('host.c',HOST),('client.c',client_source()),('main.c',MAIN)]:(d/name).write_text(src)
   subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-I'+str(R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(R/'src/vs_recovery.c'),str(R/'src/vs_recovery_wire.c'),str(R/'src/vs_abort_history.c'),'-o',str(d/'test')],check=True,timeout=30)
   subprocess.run([str(d/'test')],check=True,timeout=15)
if __name__=='__main__':unittest.main()
