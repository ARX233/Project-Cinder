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
        fps = menu[menu.index('#define OPT_FPS_Y'):menu.index('#endif', menu.index('static void option_fps_step('))]
        traffic = menu[menu.index('static const float FOOTER_BUTTON[4]'):menu.index('static int traffic_tap(')]
        code = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "menu.h"
#include "menu_mode_layout.h"
static struct { menu_state menu; char save_dir[1024]; int options_global; } G;
typedef struct { int lv; } st_states;
#define FADE 1
#define SND_SELECT 1
#define SND_CURSOR 2
static void snd_menu(int x) { (void)x; }
static void st_states_of(menu_state *m, st_states *s) { (void)m; s->lv=0; }
static const float CH_KEY[4]={205,407.5f,230,35}, CH_PREV[4]={143,407.5f,52,35}, CH_NEXT[4]={445,407.5f,52,35};
static void hud_ui_begin(float w, float h) { (void)w; (void)h; }
static void hud_ui_end(void) {}
static void hud_ui_button(float x, float y, float w, float h, int held) {
  (void)held;
  assert(fabsf(x + w/2 - 512.0f) < 0.001f);
  assert(fabsf(y + h/2 - MENU_FOOTER_CENTER*1.6f) < 0.001f);
  assert(y >= MENU_FOOTER_TOP*1.6f && y+h <= 768.0f);
}
static float hud_ui_text_width(const char *s, float px) { return (6*strlen(s)-1)*px; }
static float hud_ui_text(const char *s, float x, float y, float px, float r, float g, float b, float a) {
  (void)r; (void)g; (void)b; (void)a;
  const float w=hud_ui_text_width(s,px);
  assert(fabsf(x+w/2-512.0f)<0.001f);
  assert(fabsf(y+3.5f*px-MENU_FOOTER_CENTER*1.6f)<0.001f);
  return x+w;
}
''' + traffic + '\n'.join(function(menu, m) for m in ('static int ch_hit(', 'static void chapters_page(', 'static int chapters_tap(', 'static int traffic_tap(', 'static void draw_footer_button(', 'static void draw_traffic(')) + '\n' + fps + function(app, 'static int options_save(void) {') + r'''
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
  draw_traffic(&G.menu, 1024, 768);
  G.menu.tap_x=250; assert(!traffic_tap(&G.menu) && !G.menu.ta_traffic);
  G.menu.tap_y=MENU_FOOTER_CENTER;
  assert(traffic_tap(&G.menu) && G.menu.ta_traffic && G.menu.options_dirty && !G.menu.garage_changed);
  draw_traffic(&G.menu, 1024, 768);
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
  G.menu.tap_y=MENU_FOOTER_CENTER;
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

    def test_page_geometry_and_touch(self):
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc:
            self.skipTest('C compiler unavailable')
        menu = (SRC / 'menu.c').read_text()
        fps = menu[menu.index('#define OPT_FPS_Y'):menu.index('#endif', menu.index('static void option_fps_step('))]
        stubs = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "menu.h"
#include "hud.h"
enum { SND_CURSOR, SND_SELECT, T_TOPBAR_MES, OPT_TEXT, O_TITLE };
static struct { int bg, line, bottom; } ID;
static void snd_menu(int effect) {(void)effect;}
static void layout_enter(menu_state *m) {m->screen = MENU_LAYOUT;}
static void layout_clamp(menu_state *m, int i) {(void)m; (void)i;}
static void layout_apply(menu_state *m) {(void)m;}
static void draw_back(int id, int frame, float a) {(void)id; (void)frame; (void)a;}
static void draw_topbar(int f, float a, const anm_swap *s) {(void)f; (void)a; (void)s;}
static void draw_bottombar(int f, float a) {(void)f; (void)a;}
void anm_draw(int id, int frame, float a) {(void)id; (void)frame; (void)a;}
int anm_frames(int id) {(void)id; return 60;}
int anm_sprite(int id) {return id;}
typedef struct {float x,y,w,h;} box;
static box buttons[32];
static int count;
void hud_ui_begin(float w,float h) {(void)w; (void)h; count=0;}
void hud_ui_end(void) {}
void hud_ui_rect(float x,float y,float w,float h,float r,float g,float b,float a) {
  (void)x;(void)y;(void)w;(void)h;(void)r;(void)g;(void)b;(void)a;
}
void hud_ui_button(float x,float y,float w,float h,int held) {
  (void)held;
  assert(x>=80 && x+w<=944 && y>=154 && y+h<639);
  for(int i=0;i<count;++i) {
    box b=buttons[i];
    assert(x+w<=b.x || b.x+b.w<=x || y+h<=b.y || b.y+b.h<=y);
  }
  assert(count<32); buttons[count++]=(box){x,y,w,h};
}
float hud_ui_text_width(const char *s,float px) {return 6*px*strlen(s);}
float hud_ui_text(const char *s,float x,float y,float px,float r,float g,float b,float a) {
  (void)r;(void)g;(void)b;(void)a;
  assert(x>=80 && x+hud_ui_text_width(s,px)<=944 && y>=154 && y+7*px<639);
  return x+hud_ui_text_width(s,px);
}
'''
        checks = r'''
static void tap(menu_state *m,int button) {
  box b=buttons[button];
  m->tap_x=(b.x+b.w*.5f)/OPTION_SCALE;
  m->tap_y=(b.y+b.h*.5f)/OPTION_SCALE;
  option_step(m,1,0);
}
int main(void) {
  menu_state m={.screen=MENU_OPTION,.gyro_sens=5,.gyro=HUD_STEER_GYRO,.hq_rows=1};
  draw_option(&m,0,0,1024,768); assert(count==19);
  tap(&m,15); assert(m.gyro_sens==10 && m.garage_changed && !m.options_dirty);
  tap(&m,2); assert(m.gyro==HUD_STEER_KEYS);
  tap(&m,18); assert(m.screen==MENU_LAYOUT);
  m.screen=MENU_OPTION;
  tap(&m,1); assert(m.opt_page==OPTION_GRAPHICS);
  draw_option(&m,0,0,1024,768); assert(count==26);
  tap(&m,2); assert(m.over_on && !m.frame_rate_limit);
  tap(&m,20); assert(m.aa4);
  tap(&m,25); assert(m.frame_rate_limit==120 && m.options_dirty);
  option_step(&m,0,-1); assert(m.opt_page==OPTION_CONTROLS);
  option_step(&m,0,-1); assert(m.opt_page==OPTION_CONTROLS);
  m.hq_rows=0; m.res_row=1;
  option_step(&m,0,1); draw_option(&m,0,0,1024,768); assert(count==16);
  tap(&m,15); assert(m.hires);
  return 0;
}
'''
        code = stubs + function(menu, 'static void option_set(') + '\n' + fps + (SRC / 'menu_option_pages.inc').read_text() + checks
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'test.c'
            binary = Path(tmp) / 'test'
            source.write_text(code)
            subprocess.run([cc, '-std=gnu11', '-I', str(SRC), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
