#define WMMT_HUD_CUSTOM_TEST 1
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../src/hud.h"
#ifndef HUD_EDIT_SHIFT
#define HUD_EDIT_SHIFT 3
#endif
void hud_set_stick_deadzone_percent(int);
void hud_shift_layout_set(int,float,float,float);
#include <math.h>
#include "../src/menu.h"
#include "../src/app.h"
#include "../src/sound.h"
static void go(menu_state *m, int screen) { m->screen=screen; }
#include "hud_custom_editor_under_test.inc"
static int hit_key, hit_race, last_dead, last_separate;
void hud_layout_set(int g,float k,float x,float y) {(void)g;(void)k;(void)x;(void)y;}
void hud_set_stick_deadzone_percent(int n) {last_dead=n;}
void hud_shift_layout_set(int s,float k,float x,float y) {last_separate=s;(void)k;(void)x;(void)y;}
static int last_opacity;
void hud_set_button_opacity_percent(int n) {last_opacity=n;}
void hud_button_layout_set(int g,int s,float k,float x,float y) {(void)g;(void)s;(void)k;(void)x;(void)y;}
void hud_race_layout_set(int g,float k,float x,float y) {(void)g;(void)k;(void)x;(void)y;}
void hud_layout_clamp_mode(int g,int m,float k,float *x,float *y) {(void)g;(void)m;(void)k;(void)x;(void)y;}
static int force_identity_clamp, clamp_calls;
void hud_race_layout_clamp(int g,float k,float *x,float *y) {
  (void)g; (void)k; (void)y; ++clamp_calls;
  if (force_identity_clamp && *x<20) *x=20;
}
static float max_scale=1.6f;
float hud_race_layout_max_scale(int g) {(void)g; return max_scale;}
int hud_layout_hit_mode(int mode,float x,float y) {(void)mode;(void)x;(void)y;return hit_key;}
int hud_race_layout_hit(float x,float y) {(void)x;(void)y;return hit_race;}
int hud_menu_key(float x,float y) {(void)x;(void)y;return 0;}
void snd_menu(int x) {(void)x;}
static void press(menu_state *m,int b) {
  const float *r=LAY_BUTTON[b]; float x=r[0]+r[2]/2,y=r[1]+r[3]/2;
  layout_touch(m,(void*)1,TOUCH_BEGAN,x,y); layout_touch(m,(void*)1,TOUCH_ENDED,x,y); layout_step(m,0);
}
int main(void) {
  menu_state m; memset(&m,0,sizeof m); hud_custom_default(&m.custom_layout);
  for(int g=0;g<3;g++) m.key_k[g]=100;
  m.screen=MENU_LAYOUT; m.gyro=HUD_STEER_STICK; m.lay_sel=HUD_KEYS_LEFT;
  press(&m,LAY_DEAD_PLUS); assert(m.custom_layout.stick_deadzone_percent==9 && m.custom_layout_dirty && last_dead==9);
  m.key_k[HUD_KEYS_RIGHT]=120; m.key_dx[HUD_KEYS_RIGHT]=27; m.key_dy[HUD_KEYS_RIGHT]=-13;
  m.lay_sel=HUD_EDIT_SHIFT; press(&m,LAY_BIGGER);
  assert(m.custom_layout.shift_separate && m.custom_layout.shift.k==130 && m.custom_layout.shift.dx==27 && m.custom_layout.shift.dy==-13 && last_separate);
  press(&m,LAY_RESET); assert(!m.custom_layout.shift_separate && m.custom_layout.shift.k==120);
  hit_key=HUD_EDIT_SHIFT; layout_touch(&m,(void*)1,TOUCH_BEGAN,40,600); layout_touch(&m,(void*)1,TOUCH_MOVED,80,600); assert(m.custom_layout.shift_separate); layout_touch(&m,(void*)1,TOUCH_CANCELLED,80,600); assert(!m.custom_layout.shift_separate);
  m.lay_sel=HUD_EDIT_SHIFT_UP;
  press(&m,LAY_SMALLER);
  assert(m.custom_layout.separate_buttons==1 && m.custom_layout.button[0].k==110 &&
         m.custom_layout.button[0].dx==27 && !m.custom_layout.shift_separate);
  m.lay_sel=HUD_EDIT_SHIFT_DOWN;
  press(&m,LAY_BIGGER);
  assert(m.custom_layout.separate_buttons==3 && m.custom_layout.button[1].k==130 &&
         m.custom_layout.button[0].k==110);
  hit_key=HUD_EDIT_PAUSE; layout_touch(&m,(void*)1,TOUCH_BEGAN,100,20);
  layout_touch(&m,(void*)1,TOUCH_ENDED,125,30);
  assert(m.custom_layout.separate_buttons==7 && m.custom_layout.button[2].dx==25);
  m.lay_sel=HUD_EDIT_CAMERA; press(&m,LAY_BIGGER);
  assert(m.custom_layout.separate_buttons==15 && m.custom_layout.button[3].k==110);
  press(&m,LAY_RESET);
  assert(m.custom_layout.separate_buttons==7 && m.custom_layout.button[3].k==100);
  press(&m,LAY_OPACITY_MINUS);
  assert(m.custom_layout.button_opacity_percent==90 && last_opacity==90);
  press(&m,LAY_RESET_ALL);
  assert(m.custom_layout.button_opacity_percent==100 && last_opacity==100 && !m.custom_layout.separate_buttons);
  press(&m,LAY_PAGE); assert(m.lay_page && m.lay_sel==HUD_RACE_MAP);
  hit_race=HUD_RACE_METER; layout_touch(&m,(void*)1,TOUCH_BEGAN,40,600); layout_touch(&m,(void*)2,TOUCH_MOVED,140,600); assert(m.custom_layout.meter.dx==0); layout_touch(&m,(void*)1,TOUCH_ENDED,90,600); assert(m.custom_layout.meter.dx==50);
  press(&m,LAY_BIGGER); assert(m.custom_layout.meter.k==110);
  press(&m,LAY_RESET); assert(m.custom_layout.meter.k==100 && m.custom_layout.meter.dx==0);
  m.custom_layout.map.dx=22; m.custom_layout.rank.dy=33; press(&m,LAY_RESET_ALL); assert(!m.custom_layout.map.dx && !m.custom_layout.rank.dy);
  m.custom_layout_dirty=0; m.lay_sel=HUD_RACE_MAP; m.custom_layout.map.dx=400;
  layout_touch(&m,(void*)1,TOUCH_BEGAN,500,470); layout_touch(&m,(void*)1,TOUCH_MOVED,460,470);
  layout_touch(&m,(void*)1,TOUCH_CANCELLED,460,470); assert(m.custom_layout.map.dx==400 && !m.custom_layout_dirty);
  layout_touch(&m,(void*)1,TOUCH_BEGAN,500,470); layout_touch(&m,(void*)1,TOUCH_ENDED,460,470);
  assert(m.custom_layout.map.dx==360 && m.custom_layout_dirty==CUSTOM_DIRTY_MAP);
  m.custom_layout.map.k=100; max_scale=1.05f; press(&m,LAY_BIGGER); assert(m.custom_layout.map.k==100);
  /* Identity bounds deliberately stick out: tapping must not invoke clamp or save. */
  m.custom_layout_dirty=0; m.custom_layout.map=(HudCustomTransform){100,0,0};
  hit_race=HUD_RACE_MAP; force_identity_clamp=1; int before=clamp_calls;
  layout_touch(&m,(void*)1,TOUCH_BEGAN,40,600); layout_touch(&m,(void*)1,TOUCH_ENDED,40,600);
  assert(clamp_calls==before && !m.custom_layout_dirty && m.custom_layout.map.k==100 && !m.custom_layout.map.dx && !m.custom_layout.map.dy);
  layout_touch(&m,(void*)1,TOUCH_BEGAN,500,470); layout_touch(&m,(void*)1,TOUCH_ENDED,500,470);
  assert(clamp_calls==before && !m.custom_layout_dirty && !m.custom_layout.map.dx);
  layout_touch(&m,(void*)1,TOUCH_BEGAN,40,600); layout_touch(&m,(void*)1,TOUCH_MOVED,50,600);
  assert(m.custom_layout.map.dx==20);
  layout_touch(&m,(void*)1,TOUCH_MOVED,40,600); layout_touch(&m,(void*)1,TOUCH_ENDED,40,600);
  assert(!m.custom_layout_dirty && !m.custom_layout.map.dx && !m.custom_layout.map.dy && m.custom_layout.map.k==100);
  force_identity_clamp=0;
  m.custom_layout_dirty=0; layout_touch(&m,(void*)1,TOUCH_BEGAN,500,250); layout_touch(&m,(void*)1,TOUCH_ENDED,500,250);
  assert(m.lay_tap); layout_touch(&m,(void*)2,TOUCH_BEGAN,40,600); assert(!m.lay_touch);
  layout_touch(&m,(void*)1,TOUCH_CANCELLED,500,250); layout_step(&m,0);
  layout_touch(&m,(void*)2,TOUCH_MOVED,60,600); layout_touch(&m,(void*)2,TOUCH_CANCELLED,60,600); assert(!m.custom_layout_dirty);
  layout_touch(&m,(void*)1,TOUCH_BEGAN,500,520); layout_touch(&m,(void*)1,TOUCH_ENDED,500,520);
  layout_touch(&m,(void*)2,TOUCH_BEGAN,40,600); assert(!m.lay_touch); layout_step(&m,0); assert(m.screen==MENU_OPTION);
  puts("custom layout editor ok"); return 0;
}
