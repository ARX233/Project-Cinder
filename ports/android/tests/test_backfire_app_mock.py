#!/usr/bin/env python3
"""Compile actual app helpers with synthetic car and renderer dependencies."""
from pathlib import Path
import subprocess, tempfile, struct
ANDROID=Path(__file__).resolve().parents[1]
PRE=r"""
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "backfire.h"
#include "mathx.h"
#define CAR_RIVALS 3
#define CARDB_NPACKS 2
#define NPACKS 3
#define WPK_PASSES 3
#define GL_SRC_ALPHA 1
#define GL_ONE_MINUS_SRC_ALPHA 2
static const char *CARDB_PACKS[]={"x","y"}, *RIVALDB_CHARA[]={"z"};
typedef struct { int fd,two_sided; } wpk_scene;
typedef struct { float range[3]; const unsigned char *object_visible; int n_objects,draws,triangles,new_chunks; } render_params;
typedef struct { unsigned char backfire_pulse; int backfire_type; } car_effect;
typedef struct { struct {int ten_rival;} race; car_effect effect,rival_effect[3]; int rival_shown[3]; float body[16],rival_body[3][16]; } car_state;
static struct { int race_pack,aero_set,n_ten,ten_pack[4],rival_pack[3],vs_race,camera; struct {int aero;} rival_dress[3]; void *rival_model[3]; render_params rp; car_state car; } G;
#ifdef __ANDROID__
#define STORY_ASSEMBLY_MUFFLER 1u
typedef struct {int valid; float body_y; struct {uint32_t flags;} assembly;} story_body_view;
static struct {struct {story_body_view view;} own; story_body_view rival[3];} ASB;
static float story_body_height(int pack,uint32_t flags) {(void)pack;(void)flags;return 0;}
static int app_ghost_arcade_dressed(void) {return 0;}
static wpk_scene *menu_aero(int pack,int set) {(void)pack;(void)set;return NULL;}
#endif
static int groups, blendon, validated, opened; static mat4 captured; static float captured_eye[3]; static uint32_t captured_group;
#ifdef __ANDROID__
static const char *verified_optional_dir;
static int optional_mask;
int android_optional_resource_path(const char *name,char *out,size_t capacity) {
 int bit=!strcmp(name,"backfire.bfx")?1:!strcmp(name,"backfire.wpk")?2:0;
 if(!bit || !(optional_mask&bit)) return 0;
 int n=snprintf(out,capacity,"%s/%s",verified_optional_dir,name);
 return n>=0 && (size_t)n<capacity;
}
#endif
int bfx_wpk_validate(const char *p,const bfx_asset *a) {(void)p;(void)a;validated++;return 1;}
int wpk_load(wpk_scene *s,const char *p) {(void)s;(void)p;opened++;return 0;}
void wpk_free(wpk_scene *s) {(void)s;}
void render_begin(render_params *p) {(void)p;}
void render_blend_pass(int on) {blendon=on;}
void glBlendFunc(int a,int b) {(void)a;(void)b;}
void wpk_draw_group(const wpk_scene *s,const mat4 *vp,const mat4 *m,const float *eye,int pass,render_params *p,uint32_t group) {(void)s;(void)p; assert(blendon); if(pass==2) {groups++;captured=mat4_mul(*vp,*m);memcpy(captured_eye,eye,sizeof captured_eye);captured_group=group;}}
"""
MAIN=r"""
int main(int argc, char **argv) {
 assert(argc==3);
#ifdef __ANDROID__
 verified_optional_dir=argv[2]; optional_mask=0;
 backfire_open(argv[1]); assert(validated==0 && opened==0 && !backfire_ready);
 optional_mask=1; backfire_open(argv[1]); assert(validated==0 && opened==0 && !backfire_ready);
 optional_mask=3;
#endif
 backfire_open(argv[1]); assert(validated==1 && opened==0 && !backfire_ready);
 bfx_mesh mesh[2]={0}; bfx_nozzle noz[3]={0};
 strcpy(mesh[0].variant,"SAMLL_A");mesh[0].group=7;strcpy(mesh[1].variant,"MIDDLE_B");mesh[1].group=9;
 for(int j=0;j<2;j++)for(int f=0;f<17;f++){mat4 m=mat4_identity();m.m[12]=2;memcpy(mesh[j].frame[f],m.m,sizeof m.m);}
 strcpy(noz[0].car,"cars/x|1");strcpy(noz[1].car,"chara/z|37");
 for(int j=0;j<2;j++){strcpy(noz[j].muffler,"MUFFLER1");mat4 m=mat4_identity();m.m[14]=4;memcpy(noz[j].matrix,m.m,sizeof m.m);}
 backfire_asset.mesh=mesh;backfire_asset.nmesh=2;backfire_asset.nozzle=noz;backfire_asset.nnozzle=2;backfire_ready=1;backfire_reset();
 mat4 body=mat4_identity(),vp=mat4_identity();body.m[0]=0;body.m[1]=1;body.m[4]=-1;body.m[5]=0;body.m[12]=10;vp.m[12]=3;memcpy(G.car.body,body.m,sizeof body.m);
 G.race_pack=0;G.car.effect.backfire_pulse=30;G.car.effect.backfire_type=0;backfire_tick();assert(backfire_play.frame[0][0]==0);
 float eye[]={10,2,4};backfire_draw(&vp,eye,0);assert(groups==1&&captured_group==7);assert(fabsf(captured.m[12]-13)<1e-6f&&fabsf(captured.m[13]-1)<1e-6f&&fabsf(captured.m[14]-4)<1e-6f&&fabsf(captured.m[1]-.5f)<1e-6f);assert(fabsf(captured_eye[0]-2)<1e-6f);
#ifdef __ANDROID__
 /* The tuned R32 nozzle from the original body IGB and its -0.6 local height. */
 noz[2]=noz[0];strcpy(noz[2].muffler,"MUFFLER2");
 noz[2].matrix[12]=4.6699f;noz[2].matrix[13]=-.4702f;noz[2].matrix[14]=-22.0637f;
 backfire_asset.nnozzle=3;
 ASB.own.view.valid=1;ASB.own.view.body_y=-.6f;ASB.own.view.assembly.flags=STORY_ASSEMBLY_MUFFLER;
 backfire_tick();assert(backfire_play.frame[0][0]==-1&&backfire_play.frame[0][2]==0);
 groups=0;backfire_draw(&vp,eye,0);
 assert(groups==1&&captured_group==7);
 assert(fabsf(captured.m[12]-14.0702f)<1e-5f&&fabsf(captured.m[13]-5.6699f)<1e-5f&&fabsf(captured.m[14]+22.0637f)<1e-5f);
 assert(!memcmp(G.car.body,body.m,sizeof body.m));
 memset(&ASB.own.view,0,sizeof ASB.own.view);backfire_tick();
 assert(backfire_play.frame[0][0]==0&&backfire_play.frame[0][2]==-1);
#endif
 assert(backfire_play.frame[0][0]==0);G.car.effect.backfire_pulse=0;for(int tick=1;tick<17;tick++){backfire_tick();assert(backfire_play.frame[0][0]==tick);}backfire_tick();assert(backfire_play.frame[0][0]==-1);G.car.effect.backfire_pulse=30;backfire_tick();assert(backfire_play.frame[0][0]==0);
 G.race_pack=1;backfire_tick();assert(backfire_play.frame[0][0]==-1);G.race_pack=0;G.car.effect.backfire_pulse=30;backfire_tick();backfire_reset();assert(backfire_play.frame[0][0]==-1);
 G.rival_pack[0]=2;G.rival_model[0]=(void*)1;G.car.rival_shown[0]=1;memcpy(G.car.rival_body[0],body.m,sizeof body.m);G.car.rival_effect[0].backfire_pulse=30;G.car.rival_effect[0].backfire_type=1;backfire_tick();groups=0;backfire_draw(&vp,eye,0);assert(groups==2&&captured_group==9);puts("app backfire synthetic mock passed");return 0;
}
"""
with tempfile.TemporaryDirectory() as tmp:
 for platform,src in (("android",ANDROID/"src"),("ipad",ANDROID.parent/"ipad"/"src")):
  if platform=="ipad" and not (src/"app.c").is_file(): continue
  text=(src/"app.c").read_text(); start=text.index("/* Published backfire directories"); end=text.index("static void vs_ip_load(void);",start)
  helpers=text[start:end].replace('#include "app_tire_smoke.inc"\n','')
  # Android's tire renderer lives between the backfire helpers; it has its own tests.
  marker='#ifdef __ANDROID__\n/* clTireTrackManager'
  if marker in helpers:
   tire_start=helpers.index(marker); tire_end=helpers.index('static void backfire_open(',tire_start)
   helpers=helpers[:tire_start]+helpers[tire_end:]
  test=Path(tmp)/(platform+".c");test.write_text(PRE+helpers+(MAIN.replace('backfire_draw(&vp,eye,0)', 'backfire_draw(&vp,eye,0,&G.car)') if platform=='android' else MAIN));exe=Path(tmp)/platform
  flags=['-D__ANDROID__'] if platform=='android' else []
  subprocess.run(["cc","-D_XOPEN_SOURCE=700",*flags,"-std=c99","-I",str(src),str(test),str(src/"backfire.c"),"-lm","-o",str(exe)],check=True)
  root=Path(tmp)/(platform+'root'); root.mkdir()
  if platform=='android':
   data=root/'wmmt'; data.mkdir(); side=root/'wmmt-sidecars'; side.mkdir(); digest='a'*64; (side/'backfire-current').write_bytes(digest.encode()); assets=side/('backfire-'+digest); assets.mkdir()
  else:
   data=root; assets=root
  ident=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]
  txt=lambda b: struct.pack('<H',len(b))+b
  fixture=struct.pack('<4sHHIII',b'BFX1',1,0,17,1,0)+struct.pack('<III',1,0,0)+txt(b'SAMLL_A')+txt(b'0')+struct.pack('<272f',*(ident*17))
  (assets/'backfire.bfx').write_bytes(fixture); (assets/'backfire.wpk').write_bytes(b'bad')
  verified=root/'verified-optional'; verified.mkdir()
  (verified/'backfire.bfx').write_bytes(fixture); (verified/'backfire.wpk').write_bytes(b'bad')
  subprocess.run([str(exe),str(data),str(verified)],check=True)
