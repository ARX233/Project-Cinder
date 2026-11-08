"""Two real WV1 net clients, real UDP server and extracted app recovery helpers.
No APK, device, real UI, physics, clock, persistence or full app execution.
"""
import ctypes as c
import os,re,select,shutil,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BOOT=r"""
import socket,runpy,sys
bind,connect=socket.socket.bind,socket.socket.connect
def safe_bind(s,a):
 assert a==('0.0.0.0',0);bind(s,('127.0.0.1',0));print('PORT',s.getsockname()[1],flush=True)
def safe_connect(s,a):
 assert a==('10.255.255.255',1);connect(s,('127.0.0.1',9))
socket.socket.bind,socket.socket.connect=safe_bind,safe_connect
p=sys.argv[1];sys.argv=[p,'0'];runpy.run_path(p,run_name='__main__')
"""
def block(src,anchor):
 masked=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),src,flags=re.S)
 start=src.index(anchor);pos=masked.index('{',start);depth=1;end=pos+1
 while depth:
  if end>=len(src):raise ValueError('unclosed '+anchor)
  depth+=(masked[end]=='{')-(masked[end]=='}');end+=1
 return src[start:end]
FIXTURE=r"""
#include <stdint.h>
#include <stddef.h>
#include <math.h>
#include <string.h>
#include "net.h"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
#define VS_GONE 10.0
/* Fakes: UI, clock, game teardown. No save/physics runs. */
typedef struct {int state,finish,finish_story;} menu_state;
static struct {uint32_t vs_id;net_go vs_go;int vs_race,vs_closed,paused,vs_wait,vs_seen_loaded,in_menu;double vs_abort_note_until;struct {int race;} car;struct {int screen_w,screen_h;} hud;menu_state menu;} G;
typedef struct {vs_recovery recovery;uint64_t nonce,peer_nonce[NET_PLAYERS],host_id;uint32_t seq,peer_seq[NET_PLAYERS],race,last_go;unsigned finished,capable,ready_capable;int all_new,local_finished,echo_confirmed,local_loaded,abort_after_result;double advertise_until,finish_wait_at;unsigned char flag;} vs_recovery_app;
static vs_recovery_app VR;
static vs_abort_history VH;
static double VH_last_time;
static int VH_has_time, VH_abort_unknown;
typedef struct {int waiting;double since,last;} vs_receive_gate;
static vs_receive_gate VG_go,VG_finish;
static double clock_seconds;static int cleared,menu_aborted,menu_closed;
static int race_junction_ui,race_junction_barrier;
static double now_ms(void){return clock_seconds*1000.;}
static int vs_host_is_open(void){return 0;}
static void vs_host_disarm_round(void){}
static void car_clear_junction(void*p){(void)p;cleared++;}
static void junction_ui_reset(void*p){(void)p;}
static void junction_barrier_reset(void*p){(void)p;}
static void snd_quiet(void){}
static void hud_init(void*p,int w,int h){(void)p;(void)w;(void)h;}
static void menu_vs_aborted(menu_state*m,const char*s){(void)s;m->state=2;menu_aborted++;}
static void menu_vs_closed(menu_state*m,const char*s){(void)s;m->state=-1;menu_closed++;}
static void vs_off(void){net_close();}
int gk_send(int p,const void*b,int n){(void)p;(void)b;(void)n;return -1;}
int gk_recv(void*b,int n,int*p){(void)b;(void)n;(void)p;return 0;}
void car_link_deliver(int p,const unsigned char*b,int n){(void)p;(void)b;(void)n;}
@@HISTORY@@
@@BEGIN@@
@@OBSERVE@@
@@ABORT@@
static unsigned char profile[47];
int fixture_open(int port,unsigned id,uint64_t nonce){unsigned char base[21]={0};vs_recovery_wire_extension e={0,0,nonce,7};G.vs_id=id;VR.nonce=nonce;if(!vs_recovery_wire_encode(profile,sizeof profile,base,sizeof base,&e)||!vs_recovery_wire_put_ready(profile,sizeof profile,0))return -2;vs_abort_history_reset(&VH);VH_last_time=0;VH_has_time=VH_abort_unknown=0;int r=net_open("127.0.0.1",port,id);if(!r){net_set_lobby_observer(vs_history_lobby,NULL);net_require_valid_go(1);net_use_strict_lobby(1);}return r;}
void fixture_poll(double now,int status){clock_seconds=now;net_poll(now,status,"new",profile,sizeof profile);}
int fixture_players(void){return net_lobby_valid_now()->n;}
int fixture_begin(void){if(!net_take_go(&G.vs_go))return 0;G.vs_race=1;G.vs_wait=1;G.vs_seen_loaded=3;vs_recovery_begin(&G.vs_go);VR.local_loaded=1;return VR.recovery.initialized;}
unsigned fixture_race(void){return G.vs_go.race;}
unsigned fixture_peer_seq(void){return VR.peer_seq[G.vs_go.pcb?0:1];}
unsigned fixture_history_count(void){return VH.used;}
int fixture_history_peer(void){int k=G.vs_go.pcb?0:1;vs_recovery_wire_extension e;const net_player *p=&G.vs_go.player[k];return vs_recovery_wire_decode(&e,p->profile,p->profile_len) && vs_abort_history_query(&VH,p->id,e.nonce,VR.race,e.seq)==VS_ABORT_MATCH;}
int fixture_advertise(unsigned race,unsigned seq,unsigned flag,int loaded){unsigned char base[21]={0};vs_recovery_wire_extension e={flag,race,VR.nonce,seq};return vs_recovery_wire_encode(profile,sizeof profile,base,sizeof base,&e)&&vs_recovery_wire_put_ready(profile,sizeof profile,loaded);}
int fixture_observe(void){return vs_recovery_observe_now();}
int fixture_abort(void){return vs_abort_to_lobby();}
int fixture_field(int i){switch(i){case 0:return G.vs_race;case 1:return G.in_menu;case 2:return G.menu.state;case 3:return G.vs_wait;case 4:return G.vs_seen_loaded;case 5:return VR.local_loaded;case 6:return VR.flag;case 7:return cleared;case 8:return menu_aborted;case 9:return menu_closed;case 10:return VR.recovery.initialized;case 11:return VR.abort_after_result;default:return 0;}}
double fixture_deadline(void){return VR.advertise_until;}
"""
def source():
 app=(ROOT/'src/app.c').read_text()
 return (FIXTURE.replace('@@HISTORY@@',block(app,'static void vs_history_lobby(')).replace('@@BEGIN@@',block(app,'static void vs_recovery_begin(')).replace('@@OBSERVE@@',block(app,'static int vs_recovery_observe_now(')).replace('@@ABORT@@',block(app,'static int vs_abort_to_lobby(')))
class LoopbackRecovery(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='wv1-recovery-');self.addCleanup(self.tmp.cleanup);d=Path(self.tmp.name)
  (d/'fixture.c').write_text(source());library=d/'base.so'
  subprocess.run([os.environ.get('CC','cc'),'-std=c11','-shared','-fPIC','-I'+str(ROOT/'src'),str(d/'fixture.c'),str(ROOT/'src/net.c'),str(ROOT/'src/vs_recovery_wire.c'),str(ROOT/'src/vs_recovery.c'),str(ROOT/'src/vs_abort_history.c'),'-o',str(library)],check=True,text=True)
  self.clients=[]
  for i in range(2):
   path=d/('client%d.so'%i);shutil.copyfile(library,path);x=c.CDLL(str(path));x.fixture_open.argtypes=[c.c_int,c.c_uint,c.c_uint64];x.fixture_poll.argtypes=[c.c_double,c.c_int];x.fixture_advertise.argtypes=[c.c_uint,c.c_uint,c.c_uint,c.c_int];x.fixture_deadline.restype=c.c_double;self.clients.append(x)
  self.proc=subprocess.Popen([sys.executable,'-u','-c',BOOT,str(ROOT/'tools/vs_server.py')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'});self.addCleanup(self.stop)
  self.assertTrue(select.select([self.proc.stdout],[],[],5)[0]);line=self.proc.stdout.readline().split();self.assertEqual(line[0],'PORT');self.t=1.0
  for i,x in enumerate(self.clients):self.assertEqual(x.fixture_open(int(line[1]),101+i,0x11110000+i),0);self.addCleanup(x.net_close)
 def stop(self):
  if self.proc.poll() is None:
   self.proc.terminate()
   try:self.proc.wait(timeout=3)
   except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=3)
  self.proc.stdout.close();self.proc.stderr.close()
 def spin(self,condition,status=(0,0)):
  deadline=time.monotonic()+4
  while time.monotonic()<deadline:
   self.t+=.05
   for x,s in zip(self.clients,status):x.fixture_poll(self.t,s)
   if condition():return
   time.sleep(.005)
  self.fail('loopback timeout')
 def test_peer_abort_reaches_real_app_helpers(self):
  a,b=self.clients;self.spin(lambda:a.fixture_players()==2 and b.fixture_players()==2);a.net_start(3,17,5);begun=[False,False]
  def got_go():
   for i,x in enumerate(self.clients):
    if not begun[i]:begun[i]=bool(x.fixture_begin())
   return all(begun)
  self.spin(got_go,status=(1,1));race=a.fixture_race();self.assertGreater(race,0);self.assertEqual(race,b.fixture_race());self.assertEqual(a.fixture_peer_seq(),7)
  # Peer has returned to lobby: status=0 and RDY1 loaded=0 during ABORT.
  self.assertEqual(b.fixture_advertise(race,8,1,0),1);seen=[False]
  def observe():
   if a.fixture_observe():seen[0]=True
   return seen[0]
  self.spin(observe,status=(1,0));self.assertEqual(a.fixture_peer_seq(),7);self.assertTrue(a.fixture_history_peer());self.assertEqual(a.fixture_history_count(),1);self.assertEqual(b.fixture_history_count(),0);now=self.t;self.assertEqual(a.fixture_abort(),1)
  self.assertEqual([a.fixture_field(i) for i in range(12)],[0,1,2,0,0,0,1,1,1,0,0,0]);self.assertAlmostEqual(a.fixture_deadline(),now+30.0);self.assertTrue(a.net_is_open());self.assertEqual(a.fixture_abort(),0)
if __name__=='__main__':unittest.main()
