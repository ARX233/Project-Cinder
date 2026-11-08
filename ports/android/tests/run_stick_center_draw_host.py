from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[1]; s=(root/'src/menu.c').read_text()
a=s.index('enum { LAY_PAGE,'); b=s.index('static void layout_text_mid',a); c=s.index('\n#else',b)
with tempfile.TemporaryDirectory() as d:
 p=Path(d); (p/'hud_custom_editor_under_test.inc').write_text(s[a:b]); (p/'draw.inc').write_text(s[b:c])
 wrapper=r"""
#define main prior_main
#include "hud_custom_editor_test.c"
#undef main
static struct { int bg; } ID;
static char texts[100][128]; static int ntexts, buttons[LAY_BUTTONS];
static void draw_back(int a,int b,int c) {(void)a;(void)b;(void)c;}
void anm_fill(float a,float b,float c,float d) {(void)a;(void)b;(void)c;(void)d;}
void hud_draw_race_layout(float a,float b,int c){(void)a;(void)b;(void)c;}
void hud_draw_layout_mode(float a,float b,int c,int d){(void)a;(void)b;(void)c;(void)d;}
void hud_ui_begin(float a,float b){(void)a;(void)b;} void hud_ui_end(void){}
void hud_ui_rect(float a,float b,float c,float d,float e,float f,float g,float h){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)h;}
void hud_ui_button(float x,float y,float w,float h,int held){(void)held;for(int i=0;i<LAY_BUTTONS;i++)if(x==LAY_BUTTON[i][0] && y==LAY_BUTTON[i][1] && w==LAY_BUTTON[i][2] && h==LAY_BUTTON[i][3])buttons[i]++;}
float hud_ui_text_width(const char *s,float px){return (float)strlen(s)*6*px;}
float hud_ui_text(const char *s,float x,float y,float px,float r,float g,float b,float a){(void)x;(void)y;(void)px;(void)r;(void)g;(void)b;(void)a;if(ntexts<100){snprintf(texts[ntexts],sizeof texts[ntexts],"%s",s);ntexts++;}return 0;}
#include "draw.inc"
static int has(const char *s){for(int i=0;i<ntexts;i++)if(!strcmp(texts[i],s))return 1;return 0;}
static void reset(void){ntexts=0;memset(buttons,0,sizeof buttons);}
int main(void){menu_state m;memset(&m,0,sizeof m);hud_custom_default(&m.custom_layout);for(int i=0;i<3;i++)m.key_k[i]=100; m.gyro=HUD_STEER_STICK;m.lay_sel=HUD_KEYS_LEFT;
 draw_layout(&m,0,1024,768);assert(has("BUTTON OPACITY 100 PCT") && buttons[LAY_OPACITY_MINUS] && buttons[LAY_OPACITY_PLUS]);
 assert(has("FLOAT - TAP FOR STATIC") && has("DEADZONE 8 PCT") && buttons[LAY_CENTER] && buttons[LAY_DEAD_MINUS] && buttons[LAY_DEAD_PLUS]);
 assert(LAY_BUTTON[LAY_CENTER][1]>=LAY_BUTTON[LAY_DONE][1]+LAY_BUTTON[LAY_DONE][3]);
 reset();m.stick_center_mode=HUD_STICK_FIXED;draw_layout(&m,0,1024,768);assert(has("STATIC - TAP FOR FLOAT") && buttons[LAY_CENTER]);
 reset();m.lay_sel=HUD_KEYS_RIGHT;draw_layout(&m,0,1024,768);assert(!buttons[LAY_CENTER] && !buttons[LAY_DEAD_MINUS] && !buttons[LAY_DEAD_PLUS]);
 reset();m.lay_sel=HUD_KEYS_LEFT;m.gyro=HUD_STEER_WHEEL;draw_layout(&m,0,1024,768);assert(!buttons[LAY_CENTER] && !buttons[LAY_DEAD_MINUS]);
 reset();m.gyro=HUD_STEER_STICK;m.lay_page=1;draw_layout(&m,0,1024,768);assert(!buttons[LAY_CENTER] && !buttons[LAY_DEAD_MINUS] && !buttons[LAY_OPACITY_MINUS]);puts("stick center rendered labels and controls passed");}
"""
 (p/'test.c').write_text(wrapper)
 subprocess.run(['cc','-std=gnu11','-I',str(p),'-I',str(root/'test'),'-I',str(root/'src'),str(p/'test.c'),'-lm','-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True)
