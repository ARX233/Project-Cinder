#!/usr/bin/env python3
"""Candidate simulation only; not an integrated app or real host/API test."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_vs_no_go_host import c_block
ROOT = Path(__file__).resolve().parents[1]
PRE = r"""
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define __ANDROID__ 1
#define MENU_BGM 1
#define MENU_VS_DAY_FINAL 50
#define MENU_VS_LOADED 70
#define VS_AREA_LATE 3.0
#define VS_REVEAL 1.6
typedef struct {int status,same,profile_len;} net_player;
typedef struct {int me,host,n;net_player player[4];} net_lobby;
typedef struct {int screen,zone,zones,song;struct {int day,n,me,day_final,day_timer,day_voted,other_day[4],other_zone[4],ramp,km;} vs;} menu_state;
static struct {double vs_day_at,vs_day_started,vs_day_final_at,vs_wait_note_until;int vs_song;} G;
static int local,armed,pending,accepted,closed,starts,sends,ready,net_starts,ramp,km,song;
static int vs_same_build(const net_player *p){return p->same;}
static int vs_own_lobby_ready(const net_lobby *l,const menu_state *m){(void)l;(void)m;return ready;}
static void net_start(int r,int k,int s){(void)r;(void)k;(void)s;net_starts++;}
static int vs_host_is_open(void){return local;}
/* Entire cache is a fake, not the real host serialization. */
static int vs_host_local_start(int r,int k,int s,double now){(void)now;starts++;if(!armed||accepted)return 0;if(!pending){ramp=r;km=k;song=s;pending=1;}sends++;return 1;}
"""
POST = r"""
/* Candidate lifecycle, not production code. */
static void event(int changed,int cancel,int invalid,int good,double now){
 if(pending&&(changed||cancel||invalid)){closed++;local=armed=pending=0;G.vs_day_at=G.vs_day_started=0;return;}
 if(good&&pending){accepted=1;pending=armed=0;return;}
 if(pending&&now>=G.vs_day_at+90){closed++;local=armed=pending=0;G.vs_day_at=G.vs_day_started=0;}
}
static void setup(menu_state *m,net_lobby *l,int n,int old){
 memset(&G,0,sizeof G);memset(m,0,sizeof *m);memset(l,0,sizeof *l);local=armed=ready=1;pending=accepted=closed=starts=sends=net_starts=0;
 m->screen=MENU_BGM;m->zones=2;m->song=3;m->vs.day=1;m->vs.n=n;m->vs.ramp=7;m->vs.km=13;m->vs.day_final=1;l->n=n;G.vs_day_at=10;G.vs_day_final_at=10;
 for(int i=0;i<n;i++){l->player[i].same=1;l->player[i].profile_len=(old&(1<<i))?21:47;}
}
int main(void){menu_state m;net_lobby l;
 for(int n=2;n<=4;n++)for(int old=0;old<(1<<n);old++){
  setup(&m,&l,n,old);vs_day(&m,&l,11.59);assert(!starts);vs_day(&m,&l,12);assert(starts==1&&sends==1&&ramp==135&&km==13&&song==2);
  vs_day(&m,&l,14);assert(starts==2&&sends==2&&ramp==135&&km==13&&song==2);
  event(0,0,0,1,100);assert(accepted&&!closed&&!pending&&!armed);
 }
 setup(&m,&l,2,1);ready=0;vs_day(&m,&l,12);assert(!starts&&G.vs_wait_note_until==14);
 setup(&m,&l,2,1);l.player[1].same=0;vs_day(&m,&l,12);assert(!starts);
 for(int i=0;i<3;i++){setup(&m,&l,2,0);vs_day(&m,&l,12);event(i==0,i==1,i==2,0,13);assert(closed==1&&!pending&&!armed&&!G.vs_day_at&&!G.vs_day_started);}
 setup(&m,&l,2,0);vs_day(&m,&l,12);event(0,0,0,0,99.99);assert(!closed);event(0,0,0,0,100);assert(closed==1&&!G.vs_day_at);
 setup(&m,&l,2,0);l.me=1;vs_day(&m,&l,12);assert(!starts&&!net_starts);
 setup(&m,&l,2,0);local=0;vs_day(&m,&l,12);assert(net_starts==1&&!starts);return 0;
}
"""
class LocalVoteCandidate(unittest.TestCase):
 def test_extracted_vote(self):
  block=c_block((ROOT/'src/app.c').read_text(encoding='utf8'),'static void vs_day(menu_state *m, const net_lobby *l, double now)')
  old='net_start(m->vs.ramp | m->vs.day_final << 7, m->vs.km, G.vs_song + 2);'
  if 'vs_host_local_start(' in block:
   self.skipTest('local start already present; candidate substitution no longer applicable; needs real integration fixture')
  if block.count(old)!=1:self.skipTest('production vote changed; review candidate adapter')
  new='if (vs_host_is_open()) vs_host_local_start(m->vs.ramp | m->vs.day_final << 7, m->vs.km, G.vs_song + 2, now); else '+old
  with tempfile.TemporaryDirectory(prefix='local-vote-candidate-') as t:
   c=Path(t)/'test.c';exe=Path(t)/'test';c.write_text(PRE+block.replace(old,new)+POST,encoding='utf8')
   subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
   subprocess.run([str(exe)],check=True)
if __name__=='__main__':unittest.main()
