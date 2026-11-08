#!/usr/bin/env python3
"""Compile live hud.c function bodies against host fakes; never touches devices or source."""
import pathlib, re, subprocess, tempfile, os, sys
srcdir = pathlib.Path(os.environ.get('HUD_SRC', str(pathlib.Path(__file__).resolve().parents[1] / 'src')))
snap = pathlib.Path(os.environ.get('HUD_GENERATED', str(srcdir)))
s = (srcdir / 'hud.c').read_text()
def fn(name):
    m = re.search(r'(?m)^(?:static\s+)?[^\n;{}]*\b' + re.escape(name) + r'\([^;{}]*\)\s*\{', s)
    if not m: raise RuntimeError('production function not found: '+name)
    i = m.end(); depth = 1
    while depth:
        if i >= len(s): raise RuntimeError('unbalanced: '+name)
        if s[i]=='{': depth += 1
        if s[i]=='}': depth -= 1
        i += 1
    return s[m.start():i]+'\n'
names=['screen_ortho','inside','race_meter_bounds','race_bounds','hud_race_layout_set','race_pivot','race_place_rect','race_placed','race_time_region','hud_race_layout_hit','hud_race_layout_max_scale','hud_race_layout_clamp','race_map_rect','race_meter_glyph','race_anm','race_rank_anm','race_time_anm','race_view_begin','race_view_end','hud_draw_race_layout','draw_navi']
prefix=r'''
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>
#include "mathx.h"
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
typedef struct {float x,y,w,h;} rect;
typedef struct {int tex; float w,h;} hud_sprite;
typedef struct {float x,y,a0,a1;} meterdb_part;
typedef struct {int n[6]; meterdb_part parts[6][4];} meterdb;
#define METERDB_MAX_PARTS 4
static meterdb METERDB[1], METERDB_V2[1], *meter_car;
static int meter_night, meter_v2_active;
static hud_sprite METER[4], SPR[40], racing_lamp_on;
static int racing_lamp_slot = -1;
#define SPR_PLATE 0
#define SPR_MAP_WAKU 1
#define SPR_MAP_NAME 2
#define CAR_COURSES 10
#define SPR_MAP_TEXT 12
static float INFO_Y=505;
enum { HUD_RACE_MAP,HUD_RACE_RANK,HUD_RACE_TIME,HUD_RACE_METER,HUD_RACE_GROUPS };
typedef struct {float screen_w,screen_h;} hud_state;
typedef struct {int next_area,area; float map_angle,map_x,map_z;} car_race;
typedef struct {int blend,area,on,vert,n_index,index;} navi_mesh;
static struct {int n,next,lit[3],prog,u_mvp,u_tex,tex[2],vbo,ibo; navi_mesh *mesh;} NAVI;
static int navi_city=0,navi_requested=0;
#define NAVI_UNSET -1
#define NAVI_VERT 24
#define NAVI_ICON 10
static const float NAVI_ICON_UV[4][2]={{0,0},{1,0},{0,1},{1,1}};
static int navi_lit(int a) { (void)a; return 0; }
static float EDGE, TA_X, MAP_UP, CLUSTER_X=948, CLUSTER_Y=286;
static const float TA_Y=26, HUD_K=1.1f;
static float tx(float x){return TA_X+x*HUD_K;} static float ty(float y){return TA_Y+y*HUD_K;}
static float race_k[HUD_RACE_GROUPS]={1,1,1,1},race_dx[HUD_RACE_GROUPS],race_dy[HUD_RACE_GROUPS];
typedef int GLint; typedef int GLsizei; typedef unsigned int GLuint, GLenum; typedef unsigned char GLboolean;
#define GL_VIEWPORT 1
#define GL_SCISSOR_TEST 2
#define GL_DEPTH_TEST 3
#define GL_TRUE 1
#define GL_FALSE 0
#define GL_DEPTH_BUFFER_BIT 4
#define GL_LEQUAL 5
#define GL_TEXTURE_2D 6
#define GL_ARRAY_BUFFER 7
#define GL_ELEMENT_ARRAY_BUFFER 8
#define GL_FLOAT 9
#define GL_UNSIGNED_BYTE 10
#define GL_TRIANGLES 11
#define GL_UNSIGNED_SHORT 12
#define GL_TRIANGLE_STRIP 13
#define GL_SCISSOR_BOX 14
#define GL_DEPTH_FUNC 15
#define GL_DEPTH_WRITEMASK 16
static int vp[4],scissor[4],scissor_on,depth_on,depth_mask=1,depth_func=77,scissor_at_clear[4],viewport_at_clear[4],clear_count;
static int tex_prog=17,u_tproj=19, matrix_count; static mat4 uploaded[20];
static void glGetIntegerv(int p,int *v){if(p==GL_VIEWPORT)memcpy(v,vp,sizeof vp);else if(p==GL_SCISSOR_BOX)memcpy(v,scissor,sizeof scissor);else if(p==GL_DEPTH_FUNC)*v=depth_func;}
static void glGetBooleanv(int p,GLboolean *v){*v=(GLboolean)(p==GL_SCISSOR_TEST?scissor_on:p==GL_DEPTH_TEST?depth_on:depth_mask);}
static void glViewport(int x,int y,int w,int h){vp[0]=x;vp[1]=y;vp[2]=w;vp[3]=h;}
static void glScissor(int x,int y,int w,int h){scissor[0]=x;scissor[1]=y;scissor[2]=w;scissor[3]=h;}
static void glEnable(int v){if(v==GL_SCISSOR_TEST)scissor_on=1;if(v==GL_DEPTH_TEST)depth_on=1;}
static void glDisable(int v){if(v==GL_SCISSOR_TEST)scissor_on=0;if(v==GL_DEPTH_TEST)depth_on=0;}
static void glDepthMask(int v){depth_mask=v;}
static void glClear(int v){(void)v;++clear_count;memcpy(scissor_at_clear,scissor,sizeof scissor);memcpy(viewport_at_clear,vp,sizeof vp);}
static void glDepthFunc(int v){depth_func=v;}
static void glUseProgram(int v){(void)v;}
static void glUniformMatrix4fv(int a,int b,int c,const float *m){(void)a;(void)b;(void)c;if(matrix_count<20)memcpy(uploaded[matrix_count++].m,m,64);}
static void glUniform1i(int a,int b){(void)a;(void)b;}
static void glBindTexture(int a,int b){(void)a;(void)b;}
static void glBindBuffer(int a,int b){(void)a;(void)b;}
static void glEnableVertexAttribArray(int a){(void)a;} static void glDisableVertexAttribArray(int a){(void)a;}
static void glVertexAttribPointer(int a,int b,int c,int d,int e,const void*f){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;}
static void glVertexAttrib4f(int a,float b,float c,float d,float e){(void)a;(void)b;(void)c;(void)d;(void)e;}
static void glDrawElements(int a,int b,int c,const void*d){(void)a;(void)b;(void)c;(void)d;}
static void glDrawArrays(int a,int b,int c){(void)a;(void)b;(void)c;}
typedef struct { int active; mat4 original; } race_view;
static rect preview[32]; static int preview_n;
static void hud_ui_begin(float w,float h){(void)w;(void)h;preview_n=0;}
static void hud_ui_end(void){}
static void hud_ui_rect(float x,float y,float w,float h,float r,float g,float b,float a){(void)r;(void)g;(void)b;(void)a;preview[preview_n++]=(rect){x,y,w,h};}
static float hud_ui_text(const char*s,float x,float y,float k,float r,float g,float b,float a){(void)s;(void)y;(void)k;(void)r;(void)g;(void)b;(void)a;return x;}
'''
header = (srcdir / 'hud.h').read_text()
enum = re.search(r'enum\s*\{\s*HUD_RACE_MAP\b[^}]*\}\s*;', header)
if not enum: raise RuntimeError('HUD_RACE enum not found in live hud.h')
prefix = prefix.replace('enum { HUD_RACE_MAP,HUD_RACE_RANK,HUD_RACE_TIME,HUD_RACE_METER,HUD_RACE_GROUPS };', enum.group())
body='\n'.join(fn(n) for n in names)
# Guard ownership and ordering in the actual interleaved rendering paths.
assert 'race_rank_anm' not in fn('draw_info_box')
assert 'race_rank_anm' not in fn('draw_rival_card')
assert 'race_rank_anm' in fn('draw_vs_place')
ten = fn('draw_ten')
assert ten.index('race_rank_anm') < ten.index('anm_draw_xf(men') < ten.index('race_time_anm') < ten.index('anm_draw_xf(split') < ten.index('draw_rival_info')
ta = fn('draw_ta')
assert ta.index('race_view_end(time)') < ta.index('draw_records()') < ta.index('draw_sign')
assert 'race_view' not in fn('draw_finish_remaining')
test=r'''
static int fails, checks;
#define CHECK(c) do {++checks;if(!(c)){++fails;fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#c);}}while(0)
static int near(float a,float b){return fabsf(a-b)<0.0002f;}
static float px(mat4 m,float x,float y){return m.m[0]*x+m.m[4]*y+m.m[12];}
static float py(mat4 m,float x,float y){return m.m[1]*x+m.m[5]*y+m.m[13];}
int main(void){
 /* Default touch targets and the two preview boxes match their hit regions. */
 hud_state h={1024,768};
 CHECK(hud_race_layout_hit(50,350)==HUD_RACE_MAP);
 CHECK(hud_race_layout_hit(20,50)==HUD_RACE_RANK);
 CHECK(hud_race_layout_hit(30,150)==HUD_RACE_TIME);
 CHECK(hud_race_layout_hit(30,440)==HUD_RACE_TIME);
 CHECK(hud_race_layout_hit(940,286)==HUD_RACE_METER);
 CHECK(hud_race_layout_hit(30,295)==-1);
 hud_draw_race_layout(1024,768,-1);
 CHECK(preview_n==25);
 rect upper=race_time_region(0), lower=race_time_region(1);
 CHECK(near(preview[10].x,upper.x)&&near(preview[10].y,upper.y)&&near(preview[10].w,upper.w)&&near(preview[10].h,upper.h));
 CHECK(near(preview[15].x,lower.x)&&near(preview[15].y,lower.y)&&near(preview[15].w,lower.w)&&near(preview[15].h,lower.h));
 /* Non-identity inverse hit tests and map priority where groups overlap. */
 hud_race_layout_set(HUD_RACE_TIME,1.3f,200,20);
 float ax=TA_X+(40-TA_X)*1.3f+200,ay=TA_Y+(150-TA_Y)*1.3f+20;
 CHECK(hud_race_layout_hit(ax,ay)==HUD_RACE_TIME);
 hud_draw_race_layout(1024,768,-1);rect expected=race_place_rect(HUD_RACE_TIME,upper,1.3f,200,20);
 CHECK(near(preview[10].x,expected.x)&&near(preview[10].y,expected.y)&&near(preview[10].w,expected.w)&&near(preview[10].h,expected.h));
 hud_race_layout_set(HUD_RACE_MAP,1.2f,200,-120);
 rect overlap=race_placed(HUD_RACE_MAP,1.2f,200,-120);
 /* The map center is inside the moved/scaled time block. */
 CHECK(hud_race_layout_hit(overlap.x+overlap.w/2,overlap.y+overlap.h/2)==HUD_RACE_MAP);
 hud_race_layout_set(HUD_RACE_MAP,1,0,0);hud_race_layout_set(HUD_RACE_TIME,1,0,0);
 EDGE=160; TA_X=-160; CLUSTER_X=1108;
 for(int g=0;g<4;g++){
  hud_race_layout_set(g,1,0,0); rect r=race_bounds(g),q=race_placed(g,1,0,0);
  CHECK(near(r.x,q.x)&&near(r.y,q.y)&&near(r.w,q.w)&&near(r.h,q.h));
  matrix_count=0; race_view v=race_view_begin(g,&h); race_view_end(v); CHECK(!v.active&&matrix_count==0);
  hud_race_layout_set(g,1.3f,23,-17); matrix_count=0;v=race_view_begin(g,&h);CHECK(v.active&&matrix_count==1);
  float x=r.x+13,y=r.y+29,cx,cy;race_pivot(g,&cx,&cy);mat4 orig=screen_ortho(h.screen_w,h.screen_h);
  CHECK(near(px(uploaded[0],x,y),px(orig,cx+(x-cx)*1.3f+23,cy+(y-cy)*1.3f-17)));
  CHECK(near(py(uploaded[0],x,y),py(orig,cx+(x-cx)*1.3f+23,cy+(y-cy)*1.3f-17)));
  race_view_end(v);CHECK(matrix_count==2&&memcmp(uploaded[1].m,orig.m,sizeof orig.m)==0);
  float dx=9999,dy=9999;hud_race_layout_clamp(g,1.3f,&dx,&dy);q=race_placed(g,1.3f,dx,dy);CHECK(q.x+q.w<=1024+EDGE+0.001f&&q.y+q.h<=768.001f);
  dx=dy=-9999;hud_race_layout_clamp(g,1.3f,&dx,&dy);q=race_placed(g,1.3f,dx,dy);CHECK(q.x>=-EDGE-0.001f&&q.y>=-0.001f);
  hud_race_layout_set(g,1,0,0);
 }
 hud_race_layout_set(HUD_RACE_RANK,1.2f,16,-8);float x=50,y=90,z=.7f; rect r=race_bounds(HUD_RACE_RANK);
 race_rank_anm(&x,&y,&z);CHECK(near(x,(TA_X+(80-TA_X)*1.2f+16)/1.6f));CHECK(near(y,(TA_Y+(144-TA_Y)*1.2f-8)/1.6f));CHECK(near(z,.84f));
 hud_race_layout_set(HUD_RACE_METER,1.2f,16,-8);float d[4]={500,100,510,120};r=race_bounds(HUD_RACE_METER);race_meter_glyph(d);CHECK(near(d[0],(CLUSTER_X+(800-CLUSTER_X)*1.2f+16)/1.6f));CHECK(near(d[3],(CLUSTER_Y+(192-CLUSTER_Y)*1.2f-8)/1.6f));
 hud_race_layout_set(HUD_RACE_MAP,1.3f,23,-17); float mx=tx(17),my=ty(285)-MAP_UP,mw=88*HUD_K,mh=82*HUD_K;race_map_rect(&mx,&my,&mw,&mh);
 navi_mesh mesh={0,-1,0,0,0,0};NAVI.n=1;NAVI.mesh=&mesh;NAVI.next=NAVI_UNSET; car_race car={0};int before[4]={10,20,1344,768};memcpy(vp,before,sizeof vp);
 int wx=10+(int)((mx+EDGE)*1344/(1024+2*EDGE)+.5f),wy=20+(int)((768-my-mh)+.5f),ww=(int)(mw+.5f),wh=(int)(mh+.5f);
 scissor_on=1;scissor[0]=wx+10;scissor[1]=wy+10;scissor[2]=20;scissor[3]=20;depth_on=1;depth_mask=0;depth_func=77;
 draw_navi(&h,&car);
 CHECK(viewport_at_clear[0]==wx&&viewport_at_clear[1]==wy&&viewport_at_clear[2]==ww&&viewport_at_clear[3]==wh);
 CHECK(scissor_at_clear[0]==wx+10&&scissor_at_clear[1]==wy+10&&scissor_at_clear[2]==20&&scissor_at_clear[3]==20); CHECK(memcmp(vp,before,sizeof vp)==0);
 CHECK(scissor_on==1); CHECK(scissor[0]==wx+10&&scissor[1]==wy+10&&scissor[2]==20&&scissor[3]==20); CHECK(depth_on==1&&depth_mask==0&&depth_func==77);
 scissor_on=0;
 /* At each extreme, the actual GL clipping window must remain inside the display. */
 for(int i=0;i<4;i++) { float dx=(i&1)?9999:-9999,dy=(i&2)?9999:-9999;hud_race_layout_clamp(HUD_RACE_MAP,1.6f,&dx,&dy);hud_race_layout_set(HUD_RACE_MAP,1.6f,dx,dy);memcpy(vp,before,sizeof vp);draw_navi(&h,&car); CHECK(viewport_at_clear[0]>=before[0]&&viewport_at_clear[1]>=before[1]&&viewport_at_clear[0]+viewport_at_clear[2]<=before[0]+before[2]&&viewport_at_clear[1]+viewport_at_clear[3]<=before[1]+before[3]);CHECK(memcmp(viewport_at_clear,scissor_at_clear,sizeof vp)==0); }
 /* Group independence and invalid input. */
 for(int g=0;g<4;g++)hud_race_layout_set(g,1,0,0);
 for(int g=0;g<4;g++) { hud_race_layout_set(g,1.2f,35,-20); for(int j=0;j<4;j++) if(j!=g) CHECK(race_k[j]==1 && race_dx[j]==0 && race_dy[j]==0); hud_race_layout_set(g,1,0,0); }
 hud_race_layout_set(0,NAN,1,1);CHECK(race_k[0]==1 && race_dx[0]==0);
 /* Plate and real parts, including the full needle rotation envelope. */
 SPR[SPR_PLATE]=(hud_sprite){1,200,64}; meter_car=&METERDB[0];
 METERDB[0].n[0]=2;METERDB[0].parts[0][0]=(meterdb_part){560,228,0,0};METER[0]=(hud_sprite){1,200,80};
 METERDB[0].parts[0][1]=(meterdb_part){500,280,0,1};METER[1]=(hud_sprite){1,120,30};
 /* Changing resource/vehicle dimensions must not move any transformed point. */
 hud_race_layout_set(HUD_RACE_METER,1.25f,9,-11); float d1[4]={500,200,520,220},d2[4]={500,200,520,220};
 race_meter_glyph(d1);SPR[SPR_PLATE].w=350;METER[0].w=400;race_meter_glyph(d2);
 CHECK(memcmp(d1,d2,sizeof d1)==0);hud_race_layout_set(HUD_RACE_METER,1,0,0);SPR[SPR_PLATE].w=200;METER[0].w=200;
 r=race_meter_bounds();float rad=hypotf(120*1.1f/2,30*1.1f/2);
 CHECK(r.y<=CLUSTER_Y-44 && r.y+r.h>=INFO_Y+64*1.1f);
 CHECK(r.x<=CLUSTER_X+(500-560)*1.1f-rad+.001f); CHECK(r.x+r.w>=CLUSTER_X+110-.001f);
 r=race_bounds(HUD_RACE_MAP); CHECK(r.y<=ty(285)-MAP_UP && r.y+r.h>=ty(367)-MAP_UP-.001f);
 METER[0].w=5000; CHECK(near(hud_race_layout_max_scale(HUD_RACE_METER),.6f));
 float odx=999,ody=999;hud_race_layout_clamp(HUD_RACE_METER,.6f,&odx,&ody);
 r=race_placed(HUD_RACE_METER,.6f,odx,ody);CHECK(near(r.x+r.w/2,512));
 /* Disabled depth/scissor and arbitrary depth function are restored. */
 meter_car=NULL;hud_race_layout_set(HUD_RACE_MAP,1,0,0);memcpy(vp,before,sizeof vp);scissor_on=0;depth_on=0;depth_mask=0;depth_func=71;matrix_count=0;draw_navi(&h,&car);
 CHECK(!scissor_on && !depth_on && !depth_mask && depth_func==71); mat4 ref=uploaded[0];
 /* Crop at the left edge; the same world point retains its pixel location. */
 hud_race_layout_set(HUD_RACE_MAP,1,-80,0);memcpy(vp,before,sizeof vp);matrix_count=0;clear_count=0;draw_navi(&h,&car);
 CHECK(clear_count==1 && viewport_at_clear[0]==before[0]);
 float desiredx=10+floorf((tx(17)-80+EDGE)*1344/(1024+2*EDGE)+.5f),desiredw=floorf(88*1.1f+.5f);
 float refpx=desiredx+(ref.m[12]*.5f+.5f)*desiredw;
 float actualpx=viewport_at_clear[0]+(uploaded[0].m[12]*.5f+.5f)*viewport_at_clear[2];
 CHECK(near(refpx,actualpx));CHECK(!scissor_on && !depth_on && depth_func==71);
 /* An empty inherited scissor leaves all GL state untouched. */
 hud_race_layout_set(HUD_RACE_MAP,1,0,0);memcpy(vp,before,sizeof vp);scissor_on=1;scissor[0]=900;scissor[1]=0;scissor[2]=1;scissor[3]=1;clear_count=0;draw_navi(&h,&car);
 CHECK(clear_count==0 && scissor_on && scissor[0]==900 && !depth_on && depth_func==71 && memcmp(vp,before,sizeof vp)==0);
 printf("%d checks, %d failed\n",checks,fails);return fails?1:0;
}
'''
with tempfile.TemporaryDirectory(prefix='race-layout-host-') as d:
    f=pathlib.Path(d)/'test.c'; f.write_text(prefix+body+test)
    cmd=[os.environ.get('CC','cc'),'-std=c11','-O0','-I',str(snap),str(f),'-lm','-o',str(pathlib.Path(d)/'test')]
    print('compiling extracted live hud.c with snapshot mathx.h',flush=True)
    subprocess.run(cmd,check=True)
    sys.exit(subprocess.run([str(pathlib.Path(d)/'test')]).returncode)
