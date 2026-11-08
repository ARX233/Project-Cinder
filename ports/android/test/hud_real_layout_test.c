#define WMMT_HUD_CUSTOM_TEST 1
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "menu.h"
#include "app.h"
#include "sound.h"
#define GL_ONE_MINUS_DST_COLOR 0x0307
#define GL_ZERO 0
#define MENU_OPTION HUD_INTERNAL_MENU_OPTION
#include "hud.c"
#undef MENU_OPTION
static void go(menu_state *m,int screen) { m->screen=screen; }
#include "real_editor.inc"
void snd_menu(int x) {(void)x;}
static void press(menu_state *m,int b) {const float *r=LAY_BUTTON[b]; float x=r[0]+r[2]/2,y=r[1]+r[3]/2; layout_touch(m,(void*)1,TOUCH_BEGAN,x,y);layout_touch(m,(void*)1,TOUCH_ENDED,x,y);layout_step(m,0);}
int main(void) {
 menu_state m; memset(&m,0,sizeof m); for(int i=0;i<3;i++)m.key_k[i]=100; hud_custom_default(&m.custom_layout); m.gyro=HUD_STEER_STICK; hud_wide(0,1); layout_enter(&m);
 m.lay_sel=HUD_KEYS_LEFT; press(&m,LAY_DEAD_PLUS); assert(m.custom_layout.stick_deadzone_percent==9 && fabsf(stick_dead-.09f)<.00001f); hud_state stick; hud_init(&stick,1024,768); hud_set_steer_mode(&stick,HUD_STEER_STICK); hud_touch(&stick,(void*)1,TOUCH_BEGAN,100,500); hud_touch(&stick,(void*)1,TOUCH_MOVED,108,500); assert(fabsf(stick.steer_v)<.0001f); hud_touch(&stick,(void*)1,TOUCH_MOVED,118,500); assert(stick.steer_v>0); hud_touch(&stick,(void*)1,TOUCH_CANCELLED,0,0);
 m.lay_sel=HUD_EDIT_SHIFT; press(&m,LAY_BIGGER); assert(shift_separate && m.custom_layout.shift_separate && shift_k>1.09f); press(&m,LAY_RESET); assert(!shift_separate);
 for(int mode=0;mode<HUD_STEER_MODES;mode++){ m.gyro=mode; layout_apply(&m); rect r=shift_key(mode==HUD_STEER_GYRO?G_SHIFT_UP:SHIFT_UP); float x=r.x+r.w/2,y=r.y+r.h/2; assert(hud_layout_hit_mode(mode,x,y)==HUD_EDIT_SHIFT_UP); layout_touch(&m,(void*)1,TOUCH_BEGAN,x,y); assert(m.lay_sel==HUD_EDIT_SHIFT_UP && m.lay_drag); layout_touch(&m,(void*)2,TOUCH_MOVED,x-30,y-20); assert(!m.custom_layout.separate_buttons); layout_touch(&m,(void*)1,TOUCH_MOVED,x-30,y-20); assert(m.custom_layout.separate_buttons==1); layout_touch(&m,(void*)1,TOUCH_CANCELLED,x-30,y-20); assert(!m.custom_layout.separate_buttons); }
 m.gyro=HUD_STEER_KEYS; layout_apply(&m); rect sr=shift_key(SHIFT_UP); float sx=sr.x+sr.w/2,sy=sr.y+sr.h/2; layout_touch(&m,(void*)1,TOUCH_BEGAN,sx,sy); layout_touch(&m,(void*)1,TOUCH_ENDED,sx-40,sy-15); assert(m.custom_layout.separate_buttons==1 && !shift_separate); hud_state h; hud_init(&h,1024,768); hud_set_steer_mode(&h,HUD_STEER_KEYS); sr=control_key(SHIFT_UP,HUD_EDIT_SHIFT_UP); hud_touch(&h,(void*)1,TOUCH_BEGAN,sr.x+sr.w/2,sr.y+sr.h/2); assert(h.shift_up);
 press(&m,LAY_PAGE); assert(m.lay_page); rect map=race_placed(HUD_RACE_MAP,1,0,0); float mx=map.x+map.w/2,my=map.y+map.h/2; assert(hud_race_layout_hit(mx,my)==HUD_RACE_MAP); layout_touch(&m,(void*)1,TOUCH_BEGAN,mx,my); assert(m.lay_drag && m.lay_sel==HUD_RACE_MAP); layout_touch(&m,(void*)1,TOUCH_ENDED,mx,my); assert(m.custom_layout.map.dx==0 && m.custom_layout.map.dy==0); m.lay_sel=HUD_RACE_TIME; layout_touch(&m,(void*)1,TOUCH_BEGAN,500,470); assert(m.lay_drag); layout_touch(&m,(void*)1,TOUCH_ENDED,470,470); assert(m.custom_layout.timer.dx!=0 && race_dx[HUD_RACE_TIME]==m.custom_layout.timer.dx); press(&m,LAY_RESET); assert(m.custom_layout.timer.dx==0 && race_dx[HUD_RACE_TIME]==0); rect t=race_time_region(0); assert(hud_race_layout_hit(t.x+t.w/2,t.y+t.h/2)==HUD_RACE_TIME);
 puts("PASS real menu layout + production HUD geometry and touch (no GPU)"); return 0;
}
