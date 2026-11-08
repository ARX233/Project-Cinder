#!/usr/bin/env python3
"""Host-only source-extraction experiment. Fake UI and network; no real save."""
from pathlib import Path
import os, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'tests/test_app_recovery.py').read_text()
s=s.replace("root=Path(__file__).resolve().parents[1]",f"root=Path({str(root)!r})")
s=s.replace('int all_new,local_finished,echo_confirmed,local_loaded;', 'int all_new,local_finished,echo_confirmed,local_loaded,abort_after_result;')
s=s.replace('struct { struct { int state; } vs; } menu;', 'struct { struct { int state; } vs; int finish,finish_story; } menu;')
s=s.replace('static int race_junction_ui,race_junction_barrier;', 'static int race_junction_ui,race_junction_barrier; static char note[128];')
s=s.replace('static void menu_vs_aborted(void*x,const char*y){(void)x;(void)y;++menu_abort;}', 'static void menu_vs_aborted(void*x,const char*y){(void)x;snprintf(note,sizeof note,"%s",y);G.menu.finish=G.menu.finish_story=0;++menu_abort;}')
s=s.replace('static void menu_vs_closed(void*x,const char*y){(void)x;(void)y;++menu_close;}', 'static void menu_vs_closed(void*x,const char*y){(void)x;snprintf(note,sizeof note,"%s",y);G.menu.finish=G.menu.finish_story=0;++menu_close;}')
needle='setup();assert(vs_recovery_finish_ready()==0);ms=181000;'
extra='''for(int mode=0;mode<4;mode++){ setup(); G.vs_race=1; G.menu.finish=mode!=0; G.menu.finish_story=mode==1?5:mode==2?6:mode==3?1:0; serial=1; packet(&L.player[1],101,77,11,1); assert(vs_recovery_observe_now() && vs_abort_to_lobby()); assert(VR.abort_after_result==(mode==1||mode==2)); assert((strstr(note,"LOCAL RESULT PROCESSED")!=0)==(mode==1||mode==2)); assert(!G.menu.finish && abandoned==1); } puts("fake UI: pre-result/story and VS 5/6 markers, retained room passed");
 setup(); G.vs_race=1;G.menu.finish=1;G.menu.finish_story=5;host=0;silence=11;serial=1;assert(vs_recovery_observe_now()&&vs_abort_to_lobby());assert(strstr(note,"LOCAL RESULT PROCESSED")&&off==1&&!VR.abort_after_result);silence=0; puts("fake UI: disconnect snapshot survives VR reset");
 setup(); G.vs_race=1;G.menu.finish=1;G.menu.finish_story=6;ms=-1;assert(vs_recovery_observe_now()&&vs_abort_to_lobby());assert(strstr(note,"LOCAL RESULT PROCESSED")&&strstr(note,"CLOCK ERROR"));puts("fake UI: clock failure snapshot passed");
 setup(); VR.abort_after_result=1;vs_recovery_begin(&G.vs_go);assert(!VR.abort_after_result);VR.abort_after_result=1;VR.advertise_until=1;ms=1000;assert(vs_recovery_profile(b)>0&&!VR.abort_after_result);puts("new GO and advertisement expiry reset passed");
 '''
assert needle in s
s=s.replace(needle,extra+needle)
with tempfile.TemporaryDirectory(prefix='abort-note-',dir=os.environ.get('TMPDIR')) as d:
 p=Path(d)/'experiment.py';p.write_text(s)
 subprocess.run(['python3',str(p)],check=True,env={**os.environ,'TMPDIR':d,'PYTHONDONTWRITEBYTECODE':'1'})

source=(root/'src/app.c').read_text()
x=source.index('int remaining = (int)(VR.advertise_until - now + 0.999);')
a=source.rfind('  if (VR.flag == VS_RECOVERY_WIRE_ABORT',0,x)
b=source.index(' else if (l->connected',x)
assert a >= 0
fragment=source[a:b]
t='''#include <assert.h>
#include <stdio.h>
#include <string.h>
#define VS_RECOVERY_WIRE_ABORT 1
static struct {int flag,abort_after_result;double advertise_until;} VR;
typedef struct {struct {char note[128];} vs;} M;
static void check(M*m,double now){
'''+fragment+'''
}
int main(void){M m={0};VR.flag=1;VR.advertise_until=30;VR.abort_after_result=0;check(&m,0);assert(!strcmp(m.vs.note,"RACE CANCELLED - WAIT 30 S"));VR.abort_after_result=1;check(&m,0);assert(!strcmp(m.vs.note,"LOCAL RESULT PROCESSED - WAIT 30 S"));check(&m,29.5);assert(!strcmp(m.vs.note,"LOCAL RESULT PROCESSED - WAIT 1 S"));puts("source-extracted cooldown choice passed; fake UI");}
'''
with tempfile.TemporaryDirectory(prefix='note-branch-',dir=os.environ.get('TMPDIR')) as d:
 p=Path(d)/'test.c';p.write_text(t);exe=Path(d)/'test'
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p),'-o',str(exe)],check=True,env={**os.environ,'TMPDIR':d})
 subprocess.run([str(exe)],check=True)
