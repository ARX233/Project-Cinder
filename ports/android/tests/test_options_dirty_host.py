"""Exercise real toggle handlers and app persistence dispatch on a host compiler."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_steering_options_host import SRC, function


class OptionsDirtyHost(unittest.TestCase):
    def test_toggle_and_retry_without_garage_save(self):
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc:
            self.skipTest('C compiler unavailable')
        app = (SRC / 'app.c').read_text()
        menu = (SRC / 'menu.c').read_text()
        start = app.index('  if (G.menu.garage_changed) {', app.index('  story_new_card_commit();'))
        end = app.index('  if (go && app_ghost_mode()', start)
        dispatch = app[start:end]
        fps = menu[menu.index('#define OPT_FPS_Y'):menu.index('static void draw_option_fps(')]
        code = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "menu.h"
static struct { menu_state menu; char save_dir[1024]; int options_global; } G;
typedef struct { int lv; } st_states;
#define FADE 1
#define SND_SELECT 1
#define SND_CURSOR 2
static void snd_menu(int x) { (void)x; }
static void st_states_of(menu_state *m, st_states *s) { (void)m; s->lv=0; }
static const float CH_KEY[4]={205,407.5f,230,35}, CH_PREV[4]={143,407.5f,52,35}, CH_NEXT[4]={445,407.5f,52,35};
''' + '\n'.join(function(menu, m) for m in ('static int ch_hit(', 'static void chapters_page(', 'static int chapters_tap(', 'static int traffic_tap(')) + '\n' + fps + function(app, 'static int options_save(void) {') + r'''
static int garages;
static void hq_apply(void) {}
static void garage_save(void) { garages++; }
static void dispatch(void) {
''' + dispatch + r'''
}
static void set_option(const char *path, const char *text) {
  FILE *f=fopen(path,"wb"); assert(f); assert(fputs(text,f)>=0); assert(!fclose(f));
}
int main(int argc,char **argv) {
  assert(argc==2); snprintf(G.save_dir,sizeof G.save_dir,"%s",argv[1]);
  char path[1100]; snprintf(path,sizeof path,"%s/option",argv[1]);
  const char *old="option 0 5 1\nunknown tail\nkey_layout arbitrary\n";
  set_option(path,old); G.menu.gyro_sens=5;
  G.menu.tap_x=250; G.menu.tap_y=410;
  assert(chapters_tap(&G.menu) && G.menu.story_test==1 && G.menu.options_dirty && !G.menu.garage_changed);
  dispatch(); assert(!G.menu.options_dirty && !garages);
  FILE *f=fopen(path,"rb"); assert(f); char buf[256]={0}; assert(fread(buf,1,sizeof buf-1,f)>0); fclose(f);
  assert(strstr(buf,"\nunknown tail\nkey_layout arbitrary\n"));
  G.menu.tap_x=450; assert(chapters_tap(&G.menu) && G.menu.story_test==2 && G.menu.options_dirty); dispatch(); assert(!garages);
  G.menu.tap_x=250; assert(traffic_tap(&G.menu) && G.menu.ta_traffic && G.menu.options_dirty && !G.menu.garage_changed);
  f=fopen(path,"wb"); assert(f); for(int i=0;i<65537;i++) assert(fputc('X',f)!=EOF); assert(!fclose(f));
  dispatch(); assert(G.menu.options_dirty && !garages);
  set_option(path,old); dispatch(); assert(!G.menu.options_dirty && !garages);
  memset(buf,0,sizeof buf); f=fopen(path,"rb"); assert(f); assert(fread(buf,1,sizeof buf-1,f)>0); fclose(f);
  int v[16]; assert(sscanf(buf,"option %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d",&v[0],&v[1],&v[2],&v[3],&v[4],&v[5],&v[6],&v[7],&v[8],&v[9],&v[10],&v[11],&v[12],&v[13],&v[14],&v[15])==16);
  assert(v[14]==2 && v[15]==1 && strstr(buf,"\nunknown tail\nkey_layout arbitrary\n"));
  const int caps[] = {60, 90, 120, 0};
  for (int i=0; i<4; ++i) {
    G.menu.tap_x=OPT_FPS_X+((i+1)%4)*OPT_FPS_STEP+2;
    G.menu.tap_y=OPT_FPS_Y;
    option_fps_step(&G.menu);
    assert(G.menu.frame_rate_limit==caps[i] && G.menu.options_dirty && !G.menu.garage_changed);
    dispatch(); assert(!G.menu.options_dirty && !garages);
    option_fps_step(&G.menu); assert(!G.menu.options_dirty);
  }
  G.menu.tap_x=OPT_FPS_X+OPT_FPS_STEP+2; G.menu.tap_y=OPT_FPS_Y-11;
  option_fps_step(&G.menu); assert(!G.menu.frame_rate_limit && !G.menu.options_dirty);
  G.menu.tap_x=250; G.menu.tap_y=410;
  assert(chapters_tap(&G.menu) && !G.menu.story_test); dispatch(); assert(!garages);
  assert(traffic_tap(&G.menu) && !G.menu.ta_traffic); dispatch(); assert(!garages);
  G.menu.garage_changed=1; dispatch(); assert(garages==1 && !G.menu.garage_changed);
  return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'test.c'
            binary = Path(tmp) / 'test'
            source.write_text(code)
            subprocess.run([cc, '-std=gnu11', '-I', str(SRC), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary), tmp], check=True)


if __name__ == '__main__':
    unittest.main()
