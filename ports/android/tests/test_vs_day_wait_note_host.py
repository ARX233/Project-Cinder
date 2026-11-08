#!/usr/bin/env python3
"""Test the extracted real drawing helper using a fake host HUD."""
from pathlib import Path
import os
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / 'src/menu.c').read_text()
start = source.index('#ifdef __ANDROID__\n/* The peer cooldown note')
end = source.index('\n#endif', start) + len('\n#endif')
helper = source[start:end]
call = '#ifdef __ANDROID__\n    draw_vs_day_wait_note(m, screen_w, screen_h);\n#endif'
assert call in source[source.index('void menu_draw('):]
program = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#define MENU_BGM 7
#define MENU_VS 8
typedef struct { int screen; struct { int day; char note[128]; } vs; } menu_state;
#ifdef __ANDROID__
static int begins, texts, ends;
static float got_x, got_y, got_px, got_w, got_h;
static char got_text[128];
static float hud_ui_text_width(const char *s, float px) { return strlen(s) * 6.0f * px; }
static void hud_ui_begin(float w, float h) { ++begins; got_w=w; got_h=h; }
static void hud_ui_text(const char *s, float x, float y, float px, float r, float g, float b, float a) {
  (void)r; (void)g; (void)b; (void)a;
  ++texts; strcpy(got_text,s); got_x=x; got_y=y; got_px=px;
}
static void hud_ui_end(void) { ++ends; }
#endif
''' + helper + r'''
static void draw(menu_state *m, float screen_w, float screen_h) {
#ifdef __ANDROID__
    draw_vs_day_wait_note(m, screen_w, screen_h);
#else
    (void)m; (void)screen_w; (void)screen_h;
#endif
}
int main(void) {
  menu_state m={0};
  m.screen=MENU_BGM; m.vs.day=1; strcpy(m.vs.note,"WAITING FOR ALL PLAYERS");
  draw(&m,1024,768);
#ifdef __ANDROID__
  assert(begins==1 && texts==1 && ends==1);
  assert(!strcmp(got_text,"WAITING FOR ALL PLAYERS"));
  assert(got_w==1024 && got_h==768);
  assert(fabsf(got_x + hud_ui_text_width(got_text,got_px)*0.5f - 512.0f)<0.001f);
  assert(fabsf(got_y + 3.5f*got_px - 615.0f)<0.001f);
  draw(&m,100,768);
  assert(texts==2 && hud_ui_text_width(got_text,got_px)<=90.001f);
  assert(fabsf(got_x + hud_ui_text_width(got_text,got_px)*0.5f - 50.0f)<0.001f);
  strcpy(m.vs.note,"WAITING FOR ALL PLAYERS!"); draw(&m,1024,768);
  m.vs.note[0]=0; draw(&m,1024,768);
  strcpy(m.vs.note,"WAITING FOR ALL PLAYERS"); m.vs.day=0; draw(&m,1024,768);
  m.vs.day=1; m.screen=MENU_VS; draw(&m,1024,768);
  assert(begins==2 && texts==2 && ends==2);
#endif
  puts("source-extracted wait note fake HUD passed");
  return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='vs-day-note-', dir=os.environ.get('TMPDIR')) as directory:
    path = Path(directory) / 'test.c'
    path.write_text(program)
    for android in (True, False):
        exe = Path(directory) / ('android' if android else 'other')
        cmd = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror']
        if android:
            cmd.append('-D__ANDROID__')
        subprocess.run(cmd + [str(path), '-lm', '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
