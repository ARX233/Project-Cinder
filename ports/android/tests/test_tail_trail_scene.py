#!/usr/bin/env python3
"""Real trail/scene source plus extracted app glue; fake car/GPU, no APK/device."""
from pathlib import Path
import os, shutil, subprocess, tempfile
ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'src/app.c').read_text()

def function(anchor):
    assert APP.count(anchor) == 1, anchor
    start = APP.index(anchor); opening = APP.index('{', start); level = 0
    for end in range(opening, len(APP)):
        level += (APP[end] == '{') - (APP[end] == '}')
        if level == 0:
            return APP[start:end+1]
    raise AssertionError(anchor)

DATA = r"""#include "tail_trail_data.h"
static const TailTrailDataRecord tail_trail_data[] = {
 {"testcar",0,{{1,2,-3},{-1,2,-3}},{{0,1,0},{0,1,0}},1},
 {"testcar",1,{{2,3,-4},{-2,3,-4}},{{0,1,0},{0,1,0}},.75f},
 {"ambiguous",0,{{0}},{{0}},1},{"ambiguous",0,{{0}},{{0}},1}};
#define TAIL_TRAIL_DATA_COUNT (sizeof tail_trail_data/sizeof tail_trail_data[0])
"""
PRE = r"""
#include "tail_trail_scene.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#define CAR_RIVALS 3
#define CAR_TEN_RIVALS 32
#define CARDB_NPACKS 1
#define NET_PLAYERS 4
#define CAR_RACE_RUN 0
static const char *CARDB_PACKS[]={"testcar"};
typedef struct {float m[16];} mat4;
typedef struct {int draws,triangles;} render_params;
typedef struct {int placeholder;} wpk_scene;
static wpk_scene model;
typedef struct {uint8_t b[16];} vs4_nonce;
typedef struct {int state,play_state,over,ten_rival;} Race;
typedef struct {Race race;float body[16],cam_view[16],cam_pos[3],rival_body[3][16];int rival_shown[3];} Car;
static struct {int in_menu,paused,vs_closed,vs_wait,vs_race,n_rival,race_pack,aero_set,camera;
 struct {int finish;} menu;uint32_t vs_id;
 struct {vs4_nonce incarnation;uint64_t round,config,membership,term;int n,pcb;struct {uint32_t id;} player[4];} vs_go;
 Car car;int rival_pack[3];struct {int aero;} rival_dress[3];
 int n_ten,ten_pack[CAR_TEN_RIVALS];
 wpk_scene *race_model,*rival_model[3];} G;
static TailTrailScene race_tail_trails;
static struct {vs4_nonce incarnation;uint64_t round,config,membership,term;int camera;} race_tail_scope;
static int draw_calls,allow_aero=1,ghost_dressed;
static int app_ghost_arcade_dressed(void){return ghost_dressed;}
/* Count actual C string comparisons, while retaining strcmp semantics. */
static unsigned key_comparisons;
int strcmp(const char *a,const char *b){key_comparisons++;while(*a&&*a==*b){a++;b++;}return (unsigned char)*a-(unsigned char)*b;}
static wpk_scene *menu_aero(int pack,int set){(void)pack;return allow_aero&&set==1?&model:NULL;}
static int render_tail_triangles(const mat4 *vp,const TailTrailVertex *v,size_t n,render_params *rp){
 assert(vp&&v&&n>=12&&n<=2*TAIL_TRAIL_MAX_VERTICES&&n%3==0);
 for(size_t i=0;i<n;i++){assert(isfinite(v[i].position.x));assert(v[i].rgba[0]==1&&v[i].rgba[1]==0&&v[i].rgba[2]==0&&v[i].rgba[3]>0&&v[i].rgba[3]<=.8f);}
 draw_calls++;rp->draws++;rp->triangles+=(int)n/3;return 1;}
static void identity(float m[16]){memset(m,0,16*sizeof *m);m[0]=m[5]=m[10]=m[15]=1;}
static void setup(void){memset(&G,0,sizeof G);race_tail_reset();draw_calls=0;allow_aero=1;ghost_dressed=0;
 G.vs_race=G.n_rival=2;G.vs_id=102;G.vs_go.round=7;G.vs_go.n=3;G.vs_go.pcb=1;
 for(int i=0;i<3;i++)G.vs_go.player[i].id=101u+(unsigned)i;
 G.car.race.play_state=2;G.race_model=&model;identity(G.car.cam_view);
 identity(G.car.body);G.car.body[0]=G.car.body[10]=-1;G.car.body[14]=-200;
 for(int i=0;i<3;i++){memcpy(G.car.rival_body[i],G.car.body,sizeof G.car.body);G.car.rival_shown[i]=1;G.rival_model[i]=&model;}}
"""
TEST = r"""
static void scene_checks(void){
 TailTrailScene s={0};float m[16],v[16],eye[3]={0};identity(m);identity(v);m[0]=m[10]=-1;m[14]=-200;
 assert(tail_trail_scene_lookup("testcar",0)&&tail_trail_scene_lookup("testcar",1));
 assert(!tail_trail_scene_lookup("testcar",2)&&!tail_trail_scene_lookup("cars/testcar",0)&&!tail_trail_scene_lookup("ambiguous",0));
 assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye));assert(s.slot[0].trail.count==1);
 float width=.4f*(.5f+.5f*200.f/300.f);assert(fabsf(s.slot[0].trail.samples[0].edge[0][0].y-(2+width))<1e-5f);
 m[14]=-201;assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==2);
 m[10]=1;assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==2); /* facing rejection ages */
 m[10]=-1;eye[2]=-86;assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==2);
 eye[2]=429;assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==2);
 eye[2]=0;m[14]=-200;assert(tail_trail_scene_tick(&s,0,2,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==1);
 assert(tail_trail_scene_tick(&s,0,2,1,"testcar",1,0,m,v,eye)&&s.slot[0].trail.count==1);
 assert(!tail_trail_scene_tick(&s,0,2,1,"testcar",2,0,m,v,eye)&&!s.slot[0].trail.count);
 m[12]=-50;assert(tail_trail_scene_tick(&s,0,2,1,"testcar",0,0,m,v,eye));m[12]=60;
 assert(tail_trail_scene_tick(&s,0,2,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==1); /* teleport */
 v[0]=NAN;assert(!tail_trail_scene_tick(&s,0,2,1,"testcar",0,0,m,v,eye)&&!s.slot[0].trail.count);
 identity(v);assert(tail_trail_scene_tick(&s,0,2,1,"testcar",0,0,m,v,eye));
 assert(!tail_trail_scene_tick(&s,4,2,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==1);
 assert(!tail_trail_scene_tick(&s,0,2,0,"testcar",0,0,m,v,eye)&&!s.slot[0].trail.count);
}
static void cache_checks(void){
 TailTrailScene s={0};float m[16],v[16],eye[3]={0};char key[16]="testcar";
 identity(m);identity(v);m[0]=m[10]=-1;m[14]=-200;
 key_comparisons=0;assert(tail_trail_scene_tick(&s,0,1,1,key,0,0,m,v,eye));assert(key_comparisons==3); /* unique full search */
 key_comparisons=0;for(int i=0;i<100;i++)assert(tail_trail_scene_tick(&s,0,1,1,key,0,0,m,v,eye));
 assert(key_comparisons==100); /* one key check, not a full table scan each tick */
 strcpy(key,"ambiguous");assert(!tail_trail_scene_tick(&s,0,1,1,key,0,0,m,v,eye)&&!s.slot[0].record&&!s.slot[0].trail.count);
 strcpy(key,"testcar");assert(tail_trail_scene_tick(&s,0,1,1,key,0,0,m,v,eye));
 assert(tail_trail_scene_tick(&s,0,1,1,key,1,0,m,v,eye)&&s.slot[0].record->body==1&&s.slot[0].trail.count==1);
 assert(!tail_trail_scene_tick(&s,0,1,0,key,1,0,m,v,eye)&&!s.slot[0].record);
}
static void view_checks(void){
 TailTrailScene s={0};float m[16],v[16],eye[3]={0};identity(m);identity(v);m[0]=m[10]=-1;
 m[14]=-110;
 assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye)&&!s.slot[0].trail.count);
 assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,1,m,v,eye)&&s.slot[0].trail.count==1);
 m[14]=-107;
 assert(tail_trail_scene_tick(&s,1,1,1,"testcar",0,1,m,v,eye)&&!s.slot[1].trail.count);
 m[14]=-115;
 assert(tail_trail_scene_tick(&s,1,1,1,"testcar",0,0,m,v,eye)&&!s.slot[1].trail.count);
 m[14]=-630;
 assert(tail_trail_scene_tick(&s,1,1,1,"testcar",0,1,m,v,eye)&&!s.slot[1].trail.count);

 tail_trail_scene_reset(&s);m[14]=-200;
 assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye));
 m[12]=10;v[12]=-10;eye[0]=10;
 assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==2);
 assert(s.slot[0].trail.samples[0].edge[0][0].x==s.slot[0].trail.samples[1].edge[0][0].x);
 v[12]=-12;eye[0]=12;
 assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==3);
 assert(s.slot[0].trail.samples[2].edge[0][0].x==s.slot[0].trail.samples[1].edge[0][0].x-2);
 m[12]+=150;v[12]-=150;eye[0]+=150;
 assert(tail_trail_scene_tick(&s,0,1,1,"testcar",0,0,m,v,eye)&&s.slot[0].trail.count==1);
}
static void app_checks(void){mat4 vp;identity(vp.m);render_params rp={0};
 setup();Car car=G.car;race_tail_tick(0);G.car.body[14]-=1;race_tail_tick(0);car.body[14]-=1;assert(!memcmp(&car,&G.car,sizeof car));
 assert(race_tail_trails.slot[0].trail.slot_id==102);
 assert(race_tail_trails.slot[1].trail.slot_id==101);
 assert(race_tail_trails.slot[2].trail.slot_id==103);assert(!race_tail_trails.slot[3].trail.count);
 TailTrailScene before=race_tail_trails;race_tail_draw(&vp,&rp,0,1);assert(draw_calls==3);
 for(int i=0;i<10;i++)race_tail_draw(&vp,&rp,0,1);assert(draw_calls==33&&!memcmp(&before,&race_tail_trails,sizeof before));
 race_tail_draw(&vp,&rp,0,0);assert(draw_calls==35&&!memcmp(&before,&race_tail_trails,sizeof before)); /* hidden player */
 G.camera=1;race_tail_draw(&vp,&rp,0,0);assert(draw_calls==35); /* view cut before next sample */
 race_tail_tick(0);assert(race_tail_trails.slot[0].trail.count==1&&race_tail_trails.slot[2].trail.count==1);
 G.car.rival_shown[0]=0;race_tail_tick(0);assert(!race_tail_trails.slot[1].trail.count);
 G.car.rival_shown[0]=1;race_tail_tick(0);assert(race_tail_trails.slot[1].trail.count==1);
 G.rival_dress[0].aero=1;race_tail_tick(0);assert(race_tail_trails.slot[1].record->body==1&&race_tail_trails.slot[1].trail.count==1);
 allow_aero=0;race_tail_tick(0);assert(race_tail_trails.slot[1].record->body==0&&race_tail_trails.slot[1].trail.count==1); /* actual fallback body */
 G.vs_go.round=8;race_tail_tick(0);assert(race_tail_trails.slot[0].trail.count==1&&race_tail_trails.slot[2].trail.count==1);
 for(int mode=0;mode<9;mode++){setup();race_tail_tick(0);race_tail_tick(0);assert(race_tail_trails.slot[0].trail.count==2);
  int movie=0;switch(mode){case 0:G.paused=1;break;case 1:G.menu.finish=1;break;case 2:G.vs_closed=1;break;case 3:G.in_menu=1;break;case 4:G.vs_go.n=4;break;case 5:movie=1;break;case 6:G.car.race.over=1;break;case 7:G.vs_id=999;break;case 8:G.vs_wait=1;break;}
  race_tail_draw(&vp,&rp,movie,1);assert(!draw_calls);for(int i=0;i<4;i++)assert(!race_tail_trails.slot[i].trail.count);
 }
 setup();G.vs_race=0;G.n_rival=0;race_tail_tick(0);race_tail_tick(0);
 assert(race_tail_trails.slot[0].trail.slot_id==1&&race_tail_trails.slot[0].trail.count==2);
 assert(!race_tail_trails.slot[1].trail.count); /* time attack */
 G.n_rival=2;race_tail_tick(0);race_tail_tick(0);
 assert(race_tail_trails.slot[1].trail.count==2&&race_tail_trails.slot[2].trail.count==2); /* story */
 G.n_rival=1;ghost_dressed=1;G.rival_dress[0].aero=1;race_tail_tick(0);
 assert(race_tail_trails.slot[1].record->body==1&&!race_tail_trails.slot[2].trail.count); /* ghost */
 ghost_dressed=0;G.n_ten=2;G.rival_pack[0]=-1;race_tail_tick(0);race_tail_tick(0);
 assert(race_tail_trails.slot[1].trail.slot_id==0x100&&race_tail_trails.slot[1].trail.count==2);
 G.car.race.ten_rival=1;race_tail_tick(0);
 assert(race_tail_trails.slot[1].trail.slot_id==0x101&&race_tail_trails.slot[1].trail.count==1);
}
int main(void){scene_checks();cache_checks();view_checks();app_checks();puts("trail scene + actual app glue passed (fake car/GPU)");return 0;}
"""
# setup's call needs the actual reset declaration before its definition.
PRE = PRE.replace('static void setup(void)', 'static void race_tail_reset(void);\nstatic void setup(void)')
anchors=['static void race_tail_reset(void) {','static int race_tail_active(', 'static const char *race_tail_pack(', 'static void race_tail_tick(', 'static void race_tail_draw(']
glue='\n'.join(function(a) for a in anchors)
assert APP.count('    race_tail_tick(movie);')==1
assert APP.index('    race_tail_tick(movie);') > APP.index('    car_update(&G.car, &in);')
assert 'race_tail_reset();' in function('static void player_tracks_reset(')
assert 'race_tail_reset();' in function('void app_suspend(')
mirror=function('static void draw_backmirror(')
assert 'race_tail_draw(' not in mirror and 'race_tail_tick(' not in mirror
assert APP.index('race_tail_draw(&proj, &G.rp, movie, G.camera == 0)') < APP.index('if (blurred) render_blur_end();')
build=(ROOT/'build_android.sh').read_text();assert 'src/tail_trail.c src/tail_trail_scene.c' in build
with tempfile.TemporaryDirectory(prefix='tail-scene-host-') as temp:
    d=Path(temp)
    for name in ('mathx.h','tail_trail.h','tail_trail.c','tail_trail_data.h','tail_trail_scene.h','tail_trail_scene.c'):
        shutil.copyfile(ROOT/'src'/name,d/name)
    (d/'tail_trail_private_data.h').write_text(DATA)
    (d/'fixture.c').write_text(PRE+'\n'+glue+'\n'+TEST)
    exe=d/'fixture'
    command=[os.environ.get('CC','cc'),'-std=c11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(d),str(d/'fixture.c'),str(d/'tail_trail.c'),str(d/'tail_trail_scene.c'),'-lm','-o',str(exe)]
    subprocess.run(command,check=True,timeout=60);subprocess.run([str(exe)],check=True,timeout=15)
    # Absent private metadata remains buildable and must never invent a location.
    empty = d/'source-only'; empty.mkdir()
    for name in ('mathx.h','tail_trail.h','tail_trail.c','tail_trail_data.h','tail_trail_scene.h','tail_trail_scene.c'):
        shutil.copyfile(ROOT/'src'/name,empty/name)
    (empty/'empty.c').write_text('#include "tail_trail_scene.h"\n#include <assert.h>\nint main(void){assert(!tail_trail_scene_lookup("testcar",0));return 0;}\n')
    command=[os.environ.get('CC','cc'),'-std=c11','-Wall','-Wextra','-Werror','-I',str(empty),str(empty/'empty.c'),str(empty/'tail_trail.c'),str(empty/'tail_trail_scene.c'),'-lm','-o',str(exe)]
    subprocess.run(command,check=True,timeout=60);subprocess.run([str(exe)],check=True,timeout=15)
print('source-only no-data lookup passed; not a device/visual test')
