"""Real UDP host and clients; fake clock/UI and manually driven cooldown profiles.

GO acceptance and app helpers are modeled by the shared fixture, not a full app.
"""
import importlib.util, os, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'tests/test_vs_local_host_recovery_udp.py'
s=importlib.util.spec_from_file_location('hostfixture',p); f=importlib.util.module_from_spec(s); s.loader.exec_module(f)
extra=r'''
void client_advertise(int i,unsigned race,unsigned seq,unsigned flag,double t,int status){load(i);assert(fixture_advertise(race,seq,flag,0));fixture_poll(t,status);save(i);}
'''
old=' for(int i=0;i<3;i++)client_close(i);vs_host_close();puts("local host timeout recovery: PASS");return 0;}'
new=r'''
  for(int n=0;n<56;n++){t+=.6;for(int i=0;i<2;i++)client_advertise(i,n<51?race:0,9+n,n<51?1:0,t,0);vs_host_poll(t,"host");for(int i=0;i<2;i++)client_poll(i,t,0);assert(host_count()==2);}
  assert(host_count()==2);assert(vs_host_control_ready());assert(vs_host_arm_round());assert(vs_host_seal_vote());assert(vs_host_local_start(3,17,5,t));
  for(int i=0;i<2;i++){int got=0;for(int n=0;n<100&&!got;n++){client_poll(i,t+.1+n*.001,1);got=client_begin(i);}assert(got);}
  unsigned second=client_race(0);assert(second==race+1 && second==client_race(1));vs_host_round_accepted();
  t+=.7;client_advertise(1,race,8,1,t,1);vs_host_poll(t,"host");client_poll(0,t+.01,1);assert(!client_observe(0));
  assert(client_history_isolated(0,race));
  t+=.6;client_advertise(0,race,8,1,t,1);vs_host_poll(t,"host");client_poll(1,t+.01,1);assert(!client_observe(1));assert(client_history_isolated(1,race));
  printf("PASS old race=%u new race=%u old ABORT ignored in new race\n",race,second);
  for(int i=0;i<3;i++)client_close(i);vs_host_close();return 0;}
'''
assert old in f.MAIN
main=f.MAIN.replace('int client_begin(int)', 'void client_advertise(int,unsigned,unsigned,unsigned,double,int);\nint client_begin(int)').replace(old,new)
r=f.R
with tempfile.TemporaryDirectory(prefix='rematch-audit-') as tmp:
 d=Path(tmp)
 for name,src in [('host.c',f.HOST),('client.c',f.client_source()+extra),('main.c',main)]: (d/name).write_text(src)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-fsanitize=undefined','-fno-sanitize-recover=all','-I'+str(r/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(r/'src/vs_recovery.c'),str(r/'src/vs_recovery_wire.c'),str(r/'src/vs_abort_history.c'),'-o',str(d/'test')],check=True,timeout=30)
 subprocess.run([str(d/'test')],check=True,timeout=20)
