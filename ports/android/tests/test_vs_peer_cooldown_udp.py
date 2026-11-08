"""Read-only loopback probe: fake UI/clock/base profile; manually seeded abort deadlines.
Extracts real vs_day, vs_peer_cooldown and vs_recovery_profile; not a full app/device test.
All state, source snapshots and binaries stay outside the repository.
"""
import ast, pathlib, subprocess, tempfile, os
R=pathlib.Path(__file__).resolve().parents[1]
def literals(path,name):
 t=ast.parse(path.read_text())
 for n in t.body:
  if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id==name for x in n.targets):
   v=n.value
   if isinstance(v,ast.Constant): return v.value
   if isinstance(v,ast.BinOp): return v.left.left.value,v.right.value
 raise ValueError(name)
s=(R/'src/app.c').read_text()
def take(a):
 p=s.index(a);i=s.index('{',p)+1;d=1
 while d:
  d+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[p:i]+'\n'
source=R/'tests/test_vs_host_epoch_vsday.py'
host=literals(R/'tests/test_vs_local_host_recovery_udp.py','HOST')+'\nint host_sealed(void){return H.vote_sealed;}\n'
pre,post=literals(source,'client')
pre=pre.replace('extern int active;extern void enqueue(const void*,int,int);extern int dequeue(void*,int,int);\nint gk_send(int peer,const void*b,int n){(void)peer;enqueue(b,n,active);return 0;}\nint gk_recv(void*b,int n,int*peer){*peer=0;return dequeue(b,n,active);}', 'int gk_send(int peer,const void*b,int n){(void)peer;(void)b;(void)n;return 0;}\nint gk_recv(void*b,int n,int*peer){(void)b;(void)n;(void)peer;return 0;}')
pre=pre.replace('#include <math.h>','#include <math.h>\n#include <fcntl.h>\n#include <errno.h>\n#include <unistd.h>\n#include "vs_abort_history.h"')
pre=pre.replace('static void vs_off(void)', '''static double clock_seconds; static double now_ms(void){return 1000*clock_seconds;}
static struct {uint64_t nonce;unsigned seq,race;int local_loaded,abort_after_result;double advertise_until;unsigned char flag;} VR;
static void vs_off(void)''')
f=take('static int vs_recovery_profile(')+''.join(take(m) for m in ('static int vs_peer_cooldown(', 'static int vs_own_profile_matches(', 'static int vs_own_lobby_ready(', 'static int vs_same_build(', 'static void vs_day('))
client=pre+f+r'''
static __typeof__(N) saved[3];static __typeof__(VR) vrs[3];static vs_abort_history VH, histories[3];static menu_state M;static net_go go_result[3];
static void load(int i){N=saved[i];VR=vrs[i];VH=histories[i];} static void save(int i){saved[i]=N;vrs[i]=VR;histories[i]=VH;}
void clear_go(void){memset(go_result,0,sizeof go_result);}
void client_init(int i,int port){memset(&N,0,sizeof N);N.fd=-1;memset(&VR,0,sizeof VR);VR.nonce=1001+i;assert(!net_open("127.0.0.1",port,11+i));net_use_strict_lobby(1);net_require_valid_go(1);save(i);}
void client_poll(int i,double t){unsigned char p[47];load(i);clock_seconds=t;int len=i==2?21:vs_recovery_profile(p);if(i==2)vs_profile(p);int st=i==0?menu_vs_status(&M):66;net_poll(t,st,"client",p,len);save(i);}
void client_close(int i){load(i);net_close();save(i);}
int valid(int i){load(i);int r=net_lobby_current_valid()&&net_lobby_valid_now()->n==3;save(i);return r;}
int peerflag(int i,int peer){load(i);const net_lobby*l=net_lobby_valid_now();vs_recovery_wire_extension e;int r=-1;for(int k=0;k<l->n;k++)if(l->player[k].id==(unsigned)(11+peer))r=vs_recovery_wire_decode(&e,l->player[k].profile,l->player[k].profile_len)?e.flags:99;save(i);return r;}
int ownflag(int i){load(i);int r=VR.flag;save(i);return r;}
void setabort(int i,double until,unsigned race){load(i);VR.flag=VS_RECOVERY_WIRE_ABORT;VR.race=race;VR.advertise_until=until;save(i);}
void menu_init(void){memset(&M,0,sizeof M);memset(&G,0,sizeof G);G.vs_id=11;M.screen=MENU_BGM;M.zones=2;M.vs.day=1;M.vs.n=3;M.vs.me=M.vs.host=0;M.vs.day_final=-1;M.vs.day_voted=1;M.vs.ramp=1;M.vs.km=13;M.song=4;}
void day(double now){load(0);const net_lobby*l=net_lobby_now();assert(l->connected&&l->n==3&&l->me==0&&l->host==0);for(int i=0;i<l->n;i++){int st=l->player[i].status;M.vs.other_day[i]=st>=64&&st<66?0:st>=66&&st<70?1:-1;M.vs.other_zone[i]=(st-64)&1;}vs_day(&M,l,now);save(0);}
int final(void){return M.vs.day_final;}int cooldown(double t){load(0);int r=vs_peer_cooldown(net_lobby_valid_now(),net_lobby_now(),t);save(0);return r;}
int takego(int i){load(i);int r=net_take_go(&go_result[i]);save(i);return r;}
unsigned race(int i){return go_result[i].race;}
'''
main=r'''
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
#include "vs_host.h"
int host_port(void),host_count(void),host_sealed(void);void clear_go(void);void client_init(int,int),client_poll(int,double),client_close(int),menu_init(void),day(double),setabort(int,double,unsigned);int valid(int),peerflag(int,int),ownflag(int),final(void),cooldown(double),takego(int);unsigned race(int);
static double t=1;
static void tick(void){t+=.1;for(int i=0;i<3;i++)client_poll(i,t);vs_host_poll(t,"host");for(int i=0;i<3;i++)client_poll(i,t);usleep(1000);}
static void sync_clients(void){for(int n=0;n<200;n++){tick();if(host_count()==3&&valid(0)&&valid(1)&&valid(2)&&vs_host_control_ready())return;}assert(!"lobby timeout");}
int main(void){assert(!vs_host_open(0,11));assert(vs_host_enable_local());menu_init();for(int i=0;i<3;i++)client_init(i,host_port());sync_clients();assert(vs_host_arm_round());day(t);assert(final()>=0);for(int i=0;i<40;i++)tick();day(t);assert(vs_host_round_pending());for(int n=0;n<100;n++){tick();for(int i=0;i<3;i++)if(!race(i))takego(i);if(race(0)&&race(1)&&race(2))break;}assert(race(0)==1&&race(1)==1&&race(2)==1);vs_host_round_accepted();puts("race1 start/go all clients: PASS");
/* Precisely seed survivor recovery fields; no claim about actual abort teardown. */
menu_init();assert(vs_host_arm_round());double until=t+4;setabort(0,until,1);setabort(1,until+20,1);
for(int n=0;n<80;n++){tick();if(peerflag(0,1)==1&&peerflag(0,2)==99)break;}assert(peerflag(0,1)==1&&peerflag(0,2)==99);assert(valid(0));printf("ABORT guest + legacy21 observed; cooldown=%d\n",cooldown(t));
while(t<until+1){tick();}assert(ownflag(0)==0&&ownflag(1)==1);for(int n=0;n<20;n++)tick();assert(peerflag(0,1)==1&&peerflag(0,2)==99&&valid(0)&&vs_host_control_ready());assert(cooldown(t));for(int n=0;n<15;n++){day(t);tick();}assert(final()==-1&&!host_sealed()&&!vs_host_round_pending());printf("host NORMAL guest ABORT at %.1f: no seal/START PASS\n",t);
while(t<until+20+2){tick();}assert(ownflag(1)==0);for(int n=0;n<20&&peerflag(0,1)!=0;n++)tick();assert(peerflag(0,1)==0&&peerflag(0,2)==99&&valid(0)&&!cooldown(t));for(int n=0;n<50&&final()<0;n++){day(t);tick();}assert(final()>=0);for(int n=0;n<60&&!vs_host_round_pending();n++){tick();day(t);}assert(vs_host_round_pending()&&host_sealed()&&vs_host_round_race()==2);clear_go();for(int n=0;n<100;n++){tick();for(int i=0;i<3;i++)if(!race(i))takego(i);if(race(0)&&race(1)&&race(2))break;}assert(race(0)==2&&race(1)==2&&race(2)==2);for(int i=0;i<3;i++)client_close(i);vs_host_close();puts("guest NORMAL, legacy21: real vs_day seal and START race2 PASS");return 0;}
'''
with tempfile.TemporaryDirectory(prefix='vs-cooldown-probe-') as x:
 d=pathlib.Path(x)
 for n,v in [('host.c',host),('client.c',client),('main.c',main)]:(d/n).write_text(v)
 subprocess.run(['cc','-std=gnu11','-D__ANDROID__','-fsanitize=undefined,float-cast-overflow','-I'+str(R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(R/'src/vs_recovery_wire.c'),'-o',str(d/'test')],check=True,timeout=12)
 subprocess.run([str(d/'test')],check=True,timeout=15)
