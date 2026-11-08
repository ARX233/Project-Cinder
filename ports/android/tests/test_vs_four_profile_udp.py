"""Real UDP four-client test; fake clock/UI and modeled GO acceptance.

Two peers time out; cooldown profiles use the extracted app helper.
"""
import importlib.util,os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'tests/test_vs_local_host_recovery_udp.py'
s=importlib.util.spec_from_file_location('hostfixture',p);f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
app=(f.R/'src/app.c').read_text()
profile=f.support.block(app,'static int vs_recovery_profile(')
extra=r"""
#include <fcntl.h>
#include <errno.h>
#define VS_PROFILE 21
static void vs_profile(unsigned char*p){memset(p,0,21);}
"""+profile+r"""
double profile_deadline(int i){load(i);double d=VR.advertise_until;save(i);return d;}
void replay_old(int i,unsigned race,double t){load(i);assert(fixture_advertise(race,8,1,0));fixture_poll(t,1);save(i);}
void profile_poll(int i,double t,int status){load(i);clock_seconds=t;assert(vs_recovery_profile(profile)==47);net_poll(t,status,"new",profile,47);save(i);}
unsigned profile_check(int i,double t,unsigned flag,unsigned race){load(i);clock_seconds=t;unsigned char out[47];assert(vs_recovery_profile(out)==47);vs_recovery_wire_extension e;assert(vs_recovery_wire_decode(&e,out,47));assert(e.flags==flag&&e.race_id==race&&e.nonce==1001+(unsigned)i);unsigned result=e.seq;save(i);return result;}
"""
old=' for(int i=0;i<3;i++)client_close(i);vs_host_close();puts("local host timeout recovery: PASS");return 0;}'
new=r"""
  double end=profile_deadline(0);assert(end==profile_deadline(1)&&end>t);for(int i=0;i<2;i++){unsigned a=profile_check(i,t,1,race),b=profile_check(i,t,1,race);assert(b==a+1);}
  while(t+.6<end-.001){t+=.6;for(int i=0;i<2;i++)profile_poll(i,t,0);vs_host_poll(t,"host");for(int i=0;i<2;i++)client_poll(i,t,0);assert(host_count()==2);}
  t=end-.001;for(int i=0;i<2;i++)profile_check(i,t,1,race);
  t=end;for(int i=0;i<2;i++)profile_check(i,t,0,0);
  t+=.6;for(int i=0;i<2;i++)profile_poll(i,t,0);vs_host_poll(t,"host");for(int i=0;i<2;i++)client_poll(i,t,0);
  assert(vs_host_control_ready());assert(vs_host_arm_round());assert(vs_host_seal_vote());assert(vs_host_local_start(3,17,5,t));
  for(int i=0;i<2;i++){int got=0;for(int n=0;n<100&&!got;n++){client_poll(i,t+.1+n*.001,1);got=client_begin(i);}assert(got);}
  unsigned second=client_race(0);assert(second==race+1&&client_race(1)==second);vs_host_round_accepted();
  t+=.7;replay_old(1,race,t);vs_host_poll(t,"host");client_poll(0,t+.01,1);assert(!client_observe(0));
  printf("PASS: 4 initial clients; old race ABORT replay ignored; 2 survivors; actual profile cooldown boundary; old race %u new race %u\n",race,second);
  for(int i=0;i<3;i++)client_close(i);vs_host_close();return 0;}
"""
main=f.MAIN.replace('int client_begin(int)','double profile_deadline(int);void replay_old(int,unsigned,double);void profile_poll(int,double,int);unsigned profile_check(int,double,unsigned,unsigned);\nint client_begin(int)').replace(old,new)
src=f.client_source().replace('[3]','[4]')+extra
main=main.replace('for(int i=0;i<3;i++)','for(int i=0;i<4;i++)').replace('host_count()<3','host_count()<4').replace('host_count()==3','host_count()==4').replace('&&race==client_race(2)', '&&race==client_race(2)&&race==client_race(3)')
with tempfile.TemporaryDirectory(prefix='profile-host-audit-') as tmp:
 d=Path(tmp)
 for name,text in [('host.c',f.HOST),('client.c',src),('main.c',main)]:(d/name).write_text(text)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-fsanitize=undefined','-fno-sanitize-recover=all','-I'+str(f.R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(f.R/'src/vs_recovery.c'),str(f.R/'src/vs_recovery_wire.c'),str(f.R/'src/vs_abort_history.c'),'-o',str(d/'test')],check=True,timeout=30)
 subprocess.run([str(d/'test')],check=True,timeout=20)
