#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "../src/hud.c"
static int near(float a,float b){return fabsf(a-b)<0.002f;}
static void same(rect a,rect b){assert(near(a.x,b.x)&&near(a.y,b.y)&&near(a.w,b.w)&&near(a.h,b.h));}

static void ta_checkpoint(void) {
  const float best[] = {0, 10, 30, 60};
  car_race race = {.state=CAR_RACE_RUN, .play_state=2, .sections=3};
  hud_set_course(0);
  hud_set_record_splits(3, best);
  assert(!hud_ta_checkpoint(&race));
  race.section=1; race.split[1]=11.125f; race.total=11.15f;
  assert(hud_ta_checkpoint(&race) && ta_delta_sign==1 && ta_delta_ms==1125);
  assert(!hud_ta_checkpoint(&race));
  race.section=2; race.split[2]=30.625f; race.total=30.65f;
  assert(hud_ta_checkpoint(&race) && ta_delta_sign==-1 && ta_delta_ms==500);
  race.section=3;
  assert(!hud_ta_checkpoint(&race));
  hud_set_course(0);
  race.section=1;
  assert(hud_ta_checkpoint(&race) && !ta_delta_sign);
}

int main(void){
 ta_checkpoint();
 void *a=(void*)1,*b=(void*)2; hud_state h; car_input in={0};
 hud_wide(140,1.2f); hud_layout_set(HUD_KEYS_RIGHT,1.15f,17,-9);
 for(int m=0;m<HUD_STEER_MODES;m++){
  rect base=m==HUD_STEER_GYRO?G_SHIFT_UP:SHIFT_UP;
  hud_shift_layout_set(0,.8f,-90,20); same(shift_key(base),key(base,KEY_RIGHT));
  rect r=shift_key(base); assert(hud_layout_hit_mode(m,r.x+r.w/2,r.y+r.h/2)==HUD_EDIT_SHIFT_UP);
  hud_init(&h,1500,900); hud_set_steer_mode(&h,m); hud_touch(&h,a,TOUCH_BEGAN,r.x+r.w/2,r.y+r.h/2); assert(h.shift_up==1);
 }
 hud_shift_layout_set(1,.8f,-200,-80);
 for(int m=0;m<HUD_STEER_MODES;m++){
  rect base=m==HUD_STEER_GYRO?G_SHIFT_UP:SHIFT_UP; rect r=shift_key(base);
  same(r,place(base,KEY_RIGHT,.8f,-200,-80)); assert(hud_layout_hit_mode(m,r.x+r.w/2,r.y+r.h/2)==HUD_EDIT_SHIFT_UP);
  hud_init(&h,1500,900); hud_set_steer_mode(&h,m); rect t=key(THROTTLE,KEY_RIGHT);
  hud_touch(&h,b,TOUCH_BEGAN,t.x+t.w/2,t.y+t.h/2); hud_touch(&h,a,TOUCH_BEGAN,r.x+r.w/2,r.y+r.h/2);
  assert(h.throttle_touch==b && h.shift_up==1); hud_touch(&h,a,TOUCH_CANCELLED,0,0); hud_input(&h,&in); assert(in.throttle==1 && in.shift_up);
  hud_touch(&h,b,TOUCH_CANCELLED,0,0); hud_input(&h,&in); assert(!in.throttle);
 }
 hud_button_layout_set(HUD_EDIT_SHIFT_UP,1,.75f,-300,-50);
 hud_button_layout_set(HUD_EDIT_SHIFT_DOWN,1,.85f,-200,-150);
 hud_button_layout_set(HUD_EDIT_PAUSE,1,1,80,75);
 hud_button_layout_set(HUD_EDIT_CAMERA,1,.75f,-100,95);
 const rect buttons[] = {SHIFT_UP, SHIFT_DOWN, PAUSE, CAMERA};
 for(int i=0;i<4;i++) {
  int group=HUD_EDIT_SHIFT_UP+i;
  rect r=control_key(buttons[i],group);
  assert(hud_layout_hit_mode(HUD_STEER_KEYS,r.x+r.w/2,r.y+r.h/2)==group);
  hud_init(&h,1500,900);
  hud_touch(&h,a,TOUCH_BEGAN,r.x+r.w/2,r.y+r.h/2);
  assert(h.shift_up==(i==0) && h.shift_down==(i==1) && h.pause_pressed==(i==2) && h.camera_pressed==(i==3));
  h.pause_disabled=1; h.pause_pressed=0;
  if(i==2) {
   hud_touch(&h,a,TOUCH_BEGAN,r.x+r.w/2,r.y+r.h/2);
   assert(!h.pause_pressed);
  }
 }
 for(int g=HUD_EDIT_SHIFT_UP;g<HUD_EDIT_GROUPS;g++)hud_button_layout_set(g,0,1,0,0);
 hud_init(&h,1500,900);
 rect passing=key(PAUSE,KEY_TOP);
 float px=passing.x+passing.w/2,py=passing.y+passing.h/2;
 hud_touch(&h,a,TOUCH_BEGAN,px,py); hud_input(&h,&in);
 assert(h.pause_pressed==1 && !in.passing);
 h.pause_disabled=h.passing_available=1; h.pause_pressed=0;
 hud_touch(&h,a,TOUCH_BEGAN,px,py); hud_input(&h,&in);
 assert(in.passing && !h.pause_pressed);
 hud_touch(&h,a,TOUCH_MOVED,px,py); hud_input(&h,&in);
 assert(!in.passing && !h.pause_pressed);
 hud_set_button_opacity_percent(30); assert(near(button_opacity,.3f));
 hud_set_button_opacity_percent(0); assert(!button_opacity);
 hud_set_button_opacity_percent(110); assert(near(button_opacity,1));
 float x=9999,y=-9999; hud_layout_clamp_mode(HUD_EDIT_SHIFT,HUD_STEER_GYRO,1,&x,&y);
 rect cr=place(group_rect_mode(HUD_EDIT_SHIFT,HUD_STEER_GYRO),KEY_RIGHT,1,x,y);
 assert(cr.x>=-EDGE-.01f && cr.x+cr.w<=1024+EDGE+.01f && cr.y>=-.01f && cr.y+cr.h<=768.01f);
 hud_wide(0,1); hud_layout_set(HUD_KEYS_LEFT,1,0,0);
 for(int d=-1;d<=51;d++){
  hud_set_stick_deadzone_percent(d); int p=d<0?0:d>50?50:d;
  hud_init(&h,1024,768); hud_set_steer_mode(&h,HUD_STEER_STICK);
  hud_touch(&h,a,TOUCH_BEGAN,100,500); hud_touch(&h,b,TOUCH_BEGAN,150,500);
  hud_touch(&h,a,TOUCH_MOVED,100+90*p/100.f,500); assert(fabsf(h.steer_v)<.0001f);
  hud_touch(&h,a,TOUCH_MOVED,190,500); assert(near(h.steer_v,1));
  hud_touch(&h,a,TOUCH_MOVED,10,500); assert(near(h.steer_v,-1));
  hud_touch(&h,a,TOUCH_CANCELLED,0,0); assert(!h.steer_touch && !h.steer_v);
 }
 hud_set_steer_mode(&h,HUD_STEER_GYRO); h.tilt=.5f; h.full=.5f; hud_input(&h,&in); assert(near(in.steer,1));
 puts("production HUD control tests passed"); return 0;
}
