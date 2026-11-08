"""Host-only partial integration; no APK or device. Fake UI, clock and physics.
Exercises real host/net/recovery and real menu abort/status. Does not test
next-round START, WAIT rendering, vs_day, or GO.
"""
import importlib.util, os, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('local_fixture',ROOT/'tests/test_vs_local_host_recovery_udp.py')
local=importlib.util.module_from_spec(spec);spec.loader.exec_module(local)
menu=(ROOT/'src/menu.c').read_text()
source=local.client_source()
assert source.count('typedef struct {int state,finish,finish_story;} menu_state;') == 1
source=source.replace('typedef struct {int state,finish,finish_story;} menu_state;', '#include "menu.h"\n#include <stdio.h>\nstatic void go(menu_state *m,int screen){m->screen=screen;}')
assert source.count('static void menu_vs_aborted(menu_state*m,const char*s){(void)s;m->state=2;menu_aborted++;}') == 1
source=source.replace('static void menu_vs_aborted(menu_state*m,const char*s){(void)s;m->state=2;menu_aborted++;}',local.support.block(menu,'void menu_vs_aborted(')+'\n'+local.support.block(menu,'int menu_vs_status('))
source=source.replace('static void menu_vs_closed(', 'void menu_vs_closed(').replace('m->state=-1;', 'm->vs.state=-1;').replace('G.menu.state','G.menu.vs.state')
source+=r"""
void client_old_bgm(int i){load(i);G.menu.screen=MENU_BGM;G.menu.vs.state=MENU_VS_LOBBY;G.menu.vs.day=1;G.menu.vs.day_voted=1;G.menu.vs.day_final=-1;G.menu.zone=0;save(i);}
int client_real_status(int i){load(i);int s=menu_vs_status(&G.menu);save(i);return s;}
int client_returned(int i){load(i);int ok=G.menu.screen==MENU_VS && G.menu.vs.state==MENU_VS_LOBBY && !G.menu.vs.day && menu_vs_status(&G.menu)==0 && G.menu.vs.day_final==-1 && G.menu.vs.area_final==-1;save(i);return ok;}
"""
main=local.MAIN.replace('int main(void){','void client_old_bgm(int);int client_real_status(int),client_returned(int);\nint main(void){')
assert main.count('unsigned long long serial[2]') == 1
main=main.replace('unsigned long long serial[2]', 'client_old_bgm(1);assert(client_real_status(1)!=0);printf("slow peer old BGM status=%d\\n",client_real_status(1));\n  unsigned long long serial[2]')
assert main.count('for(int n=0;n<10;n++){t+=.6;') == 1
main=main.replace('for(int n=0;n<10;n++){t+=.6;', 'assert(client_returned(0)&&client_returned(1));printf("both real menu_vs_aborted: lobby status=%d,%d\\n",client_real_status(0),client_real_status(1));\n  for(int n=0;n<10;n++){t+=.6;')
with tempfile.TemporaryDirectory(prefix='real-menu-timeout-') as tmp:
 d=Path(tmp)
 for n,s in [('host.c',local.HOST),('client.c',source),('main.c',main)]: (d/n).write_text(s)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-fsanitize=undefined','-fno-sanitize-recover=all','-I'+str(ROOT/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(ROOT/'src/vs_recovery.c'),str(ROOT/'src/vs_recovery_wire.c'),str(ROOT/'src/vs_abort_history.c'),'-o',str(d/'test')],check=True,timeout=30)
 subprocess.run([str(d/'test')],check=True,timeout=15)
