"""Exercise actual option persistence and menu helpers without Android or assets."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / 'src'

def function(text, marker):
    start = text.index(marker)
    left = text.index('{', start)
    depth = 0
    for pos in range(left, len(text)):
        if text[pos] == '{': depth += 1
        elif text[pos] == '}':
            depth -= 1
            if depth == 0: return text[start:pos + 1]
    raise ValueError(marker)

class SteeringOptionsHost(unittest.TestCase):
    def test_actual_options(self):
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc: self.skipTest('C compiler unavailable')
        app = (SRC / 'app.c').read_text()
        menu = (SRC / 'menu.c').read_text()
        load = function(app, 'static int options_load(void) {')
        save = function(app, 'static int options_save(void) {')
        self.assertIn('hud_set_steer_mode(&G.hud, G.menu.gyro)', app)
        self.assertIn('return G.menu.gyro == HUD_STEER_GYRO', app)
        for name in ('hud_layout_hit_mode(', 'hud_layout_clamp_mode(', 'hud_draw_layout_mode('):
            self.assertIn(name, menu)
        self.assertEqual(app.count('menu_story_cut_loop(G.menu.st_div, G.menu.story_test)'), 2)
        self.assertIn('PLACE %d OF %d', menu)
        fixture = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include "menu.h"
#include "timing60.h"
static struct { menu_state menu; char save_dir[1024]; int options_global; } G;
''' + load + '\n' + save + r'''
int main(int argc, char **argv) {
  assert(argc == 2); snprintf(G.save_dir, sizeof G.save_dir, "%s", argv[1]);
  G.menu.gyro_sens=5;
  const int caps[] = {0, 60, 90, 120};
  for (int mode=0; mode<4; mode++) {
    G.menu.gyro=mode; G.menu.frame_rate_limit=caps[mode];
    assert(options_save()); G.menu.gyro=-1; G.menu.frame_rate_limit=-1;
    assert(options_load() && G.menu.gyro==mode && G.menu.frame_rate_limit==caps[mode]);
  }
  char path[1100]; snprintf(path,sizeof path,"%s/option",argv[1]);
  const int bad[] = {-1,4,99};
  for (int i=0;i<3;i++) {
    FILE *f=fopen(path,"w"); assert(f); fprintf(f,"option %d 5 1\n",bad[i]); fclose(f);
    G.menu.gyro=3; G.menu.frame_rate_limit=120;
    assert(options_load() && G.menu.gyro==0 && G.menu.frame_rate_limit==0);
  }
  FILE *old=fopen(path,"w"); assert(old);
  fputs("option 0 5 1 1 0 1 1 1 1 0 1 1 1 0 0 0\n90\n",old); fclose(old);
  assert(options_load() && G.menu.frame_rate_limit==0);
  FILE *invalid=fopen(path,"w"); assert(invalid);
  fputs("option 0 5 1 1 0 1 1 1 1 0 1 1 1 0 0 0 240\n",invalid); fclose(invalid);
  assert(options_load() && G.menu.frame_rate_limit==0);
  for (int i=0;i<4;i++) {
    assert(menu_steer_hit(300+i*84,152)==i);
    assert(menu_steer_hit(383.99f+i*84,152)==i);
  }
  assert(menu_steer_hit(299.9f,152)==-1 && menu_steer_hit(636,152)==-1);
  assert(menu_steer_hit(500,137)==2 && menu_steer_hit(500,167)==-1);
  assert(menu_story_cut_loop(0,6)==1 && menu_story_cut_loop(5,1)==0);
  assert(menu_story_cut_loop(10,0)==2 && menu_story_cut_loop(10,11)==2);
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / 'test.c'; exe = Path(tmp) / 'test'
            c.write_text(fixture)
            subprocess.run([cc, '-std=gnu11', '-I', str(SRC), str(c), '-o', str(exe)], check=True)
            subprocess.run([str(exe), tmp], check=True)

    def test_versus_finish_rank(self):
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc: self.skipTest('C compiler unavailable')
        menu = (SRC / 'menu.c').read_text()
        draw = function(menu, 'void menu_finish_draw(const menu_state *m) {')
        source = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "menu.h"
#define TIMEUP_FADE 1
#define TIMEUP_LEN 1
#define STORY_FADE 1
#define RES_OUT_FADE 1
#define ST_LOSE_LEN 5
static struct { int win, lose, finish[1]; } ID;
static char shown[100];
static void anm_fill(float a,float b,float c,float d) {(void)a;(void)b;(void)c;(void)d;}
static void anm_draw(int a,int b,float c) {(void)a;(void)b;(void)c;}
static int anm_frames(int a) {(void)a; return 5;}
static void draw_st_result(const menu_state *m,int t) {(void)m;(void)t;}
static void draw_ten_result(void) {}
static void draw_result(const menu_state *m,int t) {(void)m;(void)t;}
static void hud_ui_begin(float x,float y) {(void)x;(void)y;}
static void hud_ui_end(void) {}
static float hud_ui_text_width(const char *s,float px) {(void)s;(void)px;return 10;}
static void hud_ui_text(const char *s,float x,float y,float px,float r,float g,float b,float a) {
 (void)x;(void)y;(void)px;(void)r;(void)g;(void)b;(void)a; snprintf(shown,sizeof shown,"%s",s);
}
''' + draw + r'''
int main(void) {
 menu_state m={0}; m.finish=2; m.finish_goal=1; m.finish_story=5; m.vs.last_n=4;
 for(int i=1;i<=4;i++) {char expected[40]; m.vs.last_place=i; shown[0]=0;
  menu_finish_draw(&m); snprintf(expected,sizeof expected,"PLACE %d OF 4",i); assert(!strcmp(shown,expected));}
 m.finish_story=6; m.vs.last_place=2; shown[0]=0; menu_finish_draw(&m); assert(!strcmp(shown,"PLACE 2 OF 4"));
 m.vs.last_place=5; shown[0]=0; menu_finish_draw(&m); assert(!shown[0]);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / 'rank.c'; exe = Path(tmp) / 'rank'; c.write_text(source)
            subprocess.run([cc, '-std=gnu11', '-I', str(SRC), str(c), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

if __name__ == '__main__': unittest.main()
