#!/usr/bin/env python3
"""Extract production guards/helper; real net and recovery, fake UI/GK/physics.
UDP silence is not socket closure; this fixture does not test timeout policy.
"""
from pathlib import Path
import subprocess, tempfile, unittest
ROOT = Path(__file__).resolve().parents[1]

def block(s, marker):
    a=s.index(marker); i=s.index('{',a)+1; n=1
    while n:
        n+=(s[i]=='{')-(s[i]=='}'); i+=1
    return s[a:i]

PRE = r"""
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "net.h"
#include "vs_recovery.h"
#include "vs_recovery_wire.h"
#include "vs_abort_history.h"
typedef struct {int waiting; double since,last;} vs_receive_gate;
static vs_receive_gate VG_go,VG_finish;
static vs_abort_history VH;
static int VH_abort_unknown;
#define VS_GONE 10.0
#define MENU_VS_OFF 0
#define MENU_VS_LOADING 3
#define VS_GK_JOIN 2
static struct {vs_recovery recovery; uint64_t host_id,peer_nonce[NET_PLAYERS]; unsigned capable; unsigned char flag; int local_loaded,abort_after_result; double advertise_until;} VR;
typedef struct {int finish,finish_story;struct {int state,n;} vs;} menu_state;
static struct {net_go vs_go; int vs_race,vs_closed,paused,vs_wait,vs_seen_loaded,in_menu,vs_gk; double vs_abort_note_until; menu_state menu; struct {int race;} car; struct {int screen_w,screen_h;} hud;} G;
static int race_junction_ui,race_junction_barrier,closed_menu,abort_menu,off_count,menu_frames,physics,score,disarmed;
static double now_ms(void){return 1000.;}
static int vs_host_is_open(void){return 0;}
static void vs_host_disarm_round(void){++disarmed;}
static void vs_off(void){++off_count;net_close();memset(&VR,0,sizeof VR);}
static void car_clear_junction(int*x){(void)x;}
static void junction_ui_reset(int*x){(void)x;}
static void junction_barrier_reset(int*x){(void)x;}
static void snd_quiet(void){}
static void hud_init(void*x,int w,int h){(void)x;(void)w;(void)h;}
static void menu_vs_aborted(menu_state*x,const char*y){(void)x;(void)y;++abort_menu;}
static void menu_vs_closed(menu_state*x,const char*y){(void)y;x->vs.state=MENU_VS_OFF;++closed_menu;}
static void menu_frame(float d,double f){(void)d;(void)f;++menu_frames;}
int gk_send(int peer,const void*data,int len){(void)peer;(void)data;return len;}
int gk_recv(void*data,int max,int*peer){(void)data;(void)max;(void)peer;return 0;}
void car_link_deliver(int pcb,const unsigned char*p,int len){(void)pcb;(void)p;(void)len;}
"""
POST = r"""
static void loading(void){menu_state*m=&G.menu; @@LOADING@@ ++physics; ++score;}
static void race_frame(int steps){double frame_start=0; @@RACE@@ for(int i=0;i<steps;i++)++physics; ++score;}
/* The counters after the guard are sentinels, not real physics or scoring. */
static void setup(int legacy){
 net_close();memset(&G,0,sizeof G);memset(&VR,0,sizeof VR);vs_abort_history_reset(&VH);VH_abort_unknown=0;memset(&VG_go,0,sizeof VG_go);memset(&VG_finish,0,sizeof VG_finish);
 closed_menu=abort_menu=off_count=menu_frames=physics=score=disarmed=0;
 uint64_t ids[]={11,12};assert(vs_recovery_init(&VR.recovery,ids,2,11,77,1000,2000));
 G.vs_go.n=2;G.vs_go.pcb=0;G.vs_go.race=77;G.vs_go.player[0].id=11;G.vs_go.player[1].id=12;
 VR.capable=legacy?0:3;G.vs_race=1;G.menu.vs.state=MENU_VS_LOADING;
 assert(net_open_gk(11)==0 && net_is_open());
}
static void check_abort(void){assert(G.in_menu&&!G.vs_race&&G.menu.vs.state==MENU_VS_OFF);assert(closed_menu==1&&!abort_menu&&off_count==1&&!disarmed);assert(!physics&&!score&&!net_is_open());}
int main(void){
 for(int legacy=0;legacy<2;legacy++){
  setup(legacy);net_close();assert(!net_is_open());loading();check_abort();
  setup(legacy);net_close();race_frame(0);check_abort();assert(menu_frames==1);
  setup(legacy);loading();assert(!G.in_menu&&!closed_menu&&physics==1&&score==1);
  setup(legacy);race_frame(0);assert(!G.in_menu&&!closed_menu&&!physics&&score==1);
 }
 setup(1);net_close();G.vs_race=0;race_frame(0);assert(!closed_menu&&!G.in_menu&&score==1);
 setup(1);net_close();G.menu.vs.state=MENU_VS_OFF;loading();assert(!closed_menu&&!G.in_menu&&!physics&&!score);
 setup(1);net_close();vs_recovery_reset(&VR.recovery);race_frame(0);assert(!closed_menu&&!G.in_menu&&score==1);
 net_close();return 0;
}
"""
class Guards(unittest.TestCase):
 def test_guards(self):
  s=(ROOT/'src/app.c').read_text();menu=s[s.index('static void vs_menu(void)'):];frame=s[s.index('void app_frame(float dt)'):]
  loading=block(menu,'if (!net_is_open()) {');race=block(frame,'if (G.vs_race && !net_is_open() && VR.recovery.initialized) {')
  helper=block(s,'static int vs_abort_to_lobby(void)')
  self.assertLess(frame.index(race),frame.index('if (G.vs_race && net_is_open())'))
  source=PRE+'\n'+helper+'\n'+POST.replace('@@LOADING@@',loading).replace('@@RACE@@',race)
  with tempfile.TemporaryDirectory(prefix='closed-socket-guard-') as d:
   p=Path(d);(p/'fixture.c').write_text(source)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-D__ANDROID__','-I'+str(ROOT/'src'),str(p/'fixture.c'),str(ROOT/'src/net.c'),str(ROOT/'src/vs_recovery.c'),str(ROOT/'src/vs_recovery_wire.c'),str(ROOT/'src/vs_abort_history.c'),'-o',str(p/'fixture')],check=True)
   subprocess.run([str(p/'fixture')],check=True)
if __name__=='__main__':unittest.main()
