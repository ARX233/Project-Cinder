#!/usr/bin/env python3
"""Extract real note selection and drawing code; exercise with host-only fakes."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
app = (root / 'src/app.c').read_text()
menu = (root / 'src/menu.c').read_text()
a = app.index('  const char *quiet = "NO RESPONSE - CHECK NETWORK OR GAME VERSION";')
b = app.index('\n  if (m->vs.start)', a)
selection = app[a:b]
a = menu.index('#ifdef __ANDROID__\n/* The peer cooldown note')
b = menu.index('\n#endif', a) + len('\n#endif')
helper = menu[a:b]
assert '#ifdef __ANDROID__\n    draw_vs_day_wait_note(m, screen_w, screen_h);\n#endif' in menu[menu.index('void menu_draw('):]
program = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#define __ANDROID__ 1
#define MENU_BGM 1
#define MENU_VS_CONNECTING 2
#define MENU_VS_LOBBY 3
#define VS_SILENT 5.0
#define VS_RECOVERY_WIRE_ABORT 7
typedef struct { int screen; struct { int day,state; char note[128]; } vs; } menu_state;
typedef struct { int valid, profile_len; unsigned char profile[1]; } player;
typedef struct { int connected,n,me; player player[4]; } lobby;
typedef struct { int unused; } vs_recovery_wire_extension;
static struct { double vs_no_go_note_until,vs_abort_note_until,vs_wait_note_until; } G;
static struct { int flag,abort_after_result,echo_confirmed; double advertise_until; } VR;
static int vs_recovery_wire_decode(vs_recovery_wire_extension *ext,const unsigned char *p,size_t n) {
  (void)ext; return n && p[0];
}
static int draws;
static char shown[128];
static float hud_ui_text_width(const char *s,float px) { return (float)strlen(s)*6*px; }
static void hud_ui_begin(float w,float h) { (void)w;(void)h; }
static void hud_ui_text(const char *s,float x,float y,float px,float r,float g,float b,float alpha) {
  (void)x;(void)y;(void)px;(void)r;(void)g;(void)b;(void)alpha; ++draws; strcpy(shown,s);
}
static void hud_ui_end(void) {}
''' + helper + r'''
static void select_note(menu_state *m, const lobby *l, double now, double silent) {
''' + selection + r'''
}
static void expect(menu_state *m,lobby *l,double now,double silent,const char *wanted) {
  select_note(m,l,now,silent); assert(strcmp(m->vs.note,wanted)==0);
}
int main(void) {
  menu_state m={0}; lobby l={0}; double now=10;
  m.screen=MENU_BGM; m.vs.day=1; m.vs.state=MENU_VS_LOBBY;
  l.connected=1; l.n=2; l.me=0;
  l.player[0].profile_len=l.player[1].profile_len=1;
  l.player[0].profile[0]=l.player[1].profile[0]=1;
  G.vs_wait_note_until=12;
  VR.echo_confirmed=0;
  expect(&m,&l,now,0,"WAITING FOR ALL PLAYERS");
  draw_vs_day_wait_note(&m,1024,768);
  assert(draws==1 && !strcmp(shown,"WAITING FOR ALL PLAYERS"));
  expect(&m,&l,12,0,"LEGACY SERVER - AUTO RETURN NOT GUARANTEED");
  draw_vs_day_wait_note(&m,1024,768); assert(draws==1);
  VR.echo_confirmed=1; l.player[1].profile[0]=0;
  expect(&m,&l,now,0,"WAITING FOR ALL PLAYERS");
  draw_vs_day_wait_note(&m,1024,768); assert(draws==2);
  expect(&m,&l,12,0,"LEGACY PLAYER - AUTO RETURN NOT GUARANTEED");
  draw_vs_day_wait_note(&m,1024,768); assert(draws==2);
  VR.flag=VS_RECOVERY_WIRE_ABORT; VR.advertise_until=20;
  expect(&m,&l,now,0,"RACE CANCELLED - WAIT 10 S");
  VR.abort_after_result=1;
  expect(&m,&l,now,0,"LOCAL RESULT PROCESSED - WAIT 10 S");
  VR.flag=0; VR.abort_after_result=0;
  G.vs_no_go_note_until=11; G.vs_abort_note_until=11;
  expect(&m,&l,now,0,"NO RACE START - BACK IN ROOM");
  G.vs_no_go_note_until=0;
  expect(&m,&l,now,0,"PLAYER LEFT - BACK IN ROOM");
  expect(&m,&l,now,6,"NO RESPONSE - CHECK NETWORK OR GAME VERSION");
  l.connected=0; m.vs.state=MENU_VS_CONNECTING;
  expect(&m,&l,now,0,"CONNECTING...");
  expect(&m,&l,now,6,"NO RESPONSE - CHECK NETWORK OR GAME VERSION");
  l.connected=1; m.vs.state=MENU_VS_LOBBY; G.vs_abort_note_until=0;
  l.player[1].profile[0]=1;
  expect(&m,&l,12,0,"");
  draw_vs_day_wait_note(&m,1024,768); assert(draws==2);
  puts("note priority and fake HUD integration passed");
  return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='vs-note-priority-', dir=os.environ.get('TMPDIR')) as directory:
    path = Path(directory) / 'test.c'
    exe = Path(directory) / 'test'
    path.write_text(program)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
                    '-fno-sanitize-recover=undefined', str(path), '-lm', '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
