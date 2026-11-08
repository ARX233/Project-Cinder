#!/usr/bin/env python3
"""Production scene builders, real WPK/math types, CPU packet golden assertions.
Not a Vulkan driver/GPU test. Generated files stay under /Volumes/CodexWork.
"""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('TMPDIR','/Volumes/CodexWork')).resolve()
if OUT!=Path('/Volumes/CodexWork') and not str(OUT).startswith('/Volumes/CodexWork/'):
    raise SystemExit('TMPDIR must be under /Volumes/CodexWork')
r=(ROOT/'src/render.c').read_text()
n=(ROOT/'src/render_native_scene.inc').read_text()
def function(anchor):
    a=r.index(anchor);i=r.index('{',a);depth=0
    for j in range(i,len(r)):
        if r[j]=='{':depth+=1
        elif r[j]=='}':
            depth-=1
            if not depth:return r[a:j+1]
    raise ValueError(anchor)
helpers='\n'.join(function(a) for a in ('static int wpk_chunk_valid(', 'static float enhance_night(', 'static void enhance_grade(', 'static void lit_begin(', 'static float box_distance(', 'static int box_outside(', 'void render_display_begin('))
prefix=r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "render.h"
#include "native_vk.h"
#define WMMT_NATIVE_VK 1
#define SHADOW_ALPHA .5f
#define OVER_PITCH .30f
static const float over_inv_tan=2.5f;
typedef struct {uint32_t id;} scene_prog;
typedef struct {uint32_t id;} lit_prog;
static scene_prog progs[2]={{10},{11}},gloss_progs[2]={{20},{21}};
static lit_prog lit_progs[6]={{30},{31},{32},{33},{34},{35}};
static uint32_t shadow_prog=40,white_tex=99;
static int enhance_on,ao_on=1,frame_wet=1;
static float frame_k=.9f;
static uint32_t native_frame_texture=66,native_over_texture=55;
typedef struct {uint32_t target;int w,h;} native_scene_view;
static native_scene_view native_scene={17,64,48};
static struct {int w,h;} blur={64,48};
typedef struct {mat4 mvp,mv;float eye[3],l[2][3];unsigned set;int cur;uint32_t env,spec,ao;} lit_draw;
static const char *UNAMES[]={"uMVP","uEye","uFog","uFogColor","uGrade","uUVOff","uWet","uHorizon","uMV","uL0","uL1","uD0","uD1","uAmb","uOver","uOverDir","uPower","uFrameK","uColor"};
static const char *TNAMES[]={"uTex","uEnv","uSpec","uAO","uOverTex","uFrame","uGloss","uCube"};
static int uniform_slot(const char *name){for(int i=0;i<(int)(sizeof UNAMES/sizeof *UNAMES);i++)if(!strcmp(name,UNAMES[i]))return i;assert(0);return -1;}
static float *value(cinder_vk_draw*d,const char*name){return (float*)(void*)(d->uniforms+uniform_slot(name)*64);}
static int cinder_vk_draw_init(cinder_vk_draw*d,uint32_t program,uint32_t target,int w,int h){
  memset(d,0,sizeof *d);d->program=program;d->target=target;d->viewport[2]=d->scissor[2]=w;d->viewport[3]=d->scissor[3]=h;
  d->pipeline.color_mask=15;d->pipeline.depth_compare=VK_COMPARE_OP_LESS_OR_EQUAL;d->pipeline.asset_front=VK_FRONT_FACE_COUNTER_CLOCKWISE;
  d->pipeline.stencil_compare_mask=d->pipeline.stencil_write_mask=255;
  d->index_type=VK_INDEX_TYPE_UINT16;return 1;
}
static int cinder_vk_uniform(cinder_vk_draw*d,const char*name,const void*p,size_t bytes){assert(bytes<=64);memcpy(value(d,name),p,bytes);return 1;}
static int cinder_vk_texture(cinder_vk_draw*d,const char*name,uint32_t tex){for(int i=0;i<8;i++)if(!strcmp(name,TNAMES[i])){d->textures[i]=tex;return 1;}assert(0);return 0;}
static cinder_vk_draw recorded[32];static int count;
static int cinder_vk_submit(const cinder_vk_draw*d){assert(count<32);recorded[count++]=*d;return 1;}
'''
# The public native declarations are external; fixture implementations keep the
# identical signatures rather than introducing conflicting static declarations.
prefix=prefix.replace('static int cinder_vk_', 'int cinder_vk_')
body=r'''
static uint32_t tex[4]={101,102,103,104},cubes[1]={201},ao[4]={301,0,0,0};static uint8_t wet_flags[4]={1,0,0,0},warm[4],tex_warm[4];
static wpk_pool pools[1];static wpk_batch batch[1];static wpk_chunk chunks[1];static wpk_scene scene;static render_params rp;static mat4 vp,model;
static float eye[3]={0,0,0};
static void setup(void){
  memset(&scene,0,sizeof scene);memset(&rp,0,sizeof rp);memset(pools,0,sizeof pools);memset(batch,0,sizeof batch);memset(chunks,0,sizeof chunks);memset(warm,0,sizeof warm);memset(tex_warm,0,sizeof tex_warm);
  count=0;enhance_on=0;ao_on=1;frame_wet=1;frame_k=.9f;native_frame_texture=66;native_over_texture=55;
  native_scene.target=17;native_scene.w=64;native_scene.h=48;blur.w=64;blur.h=48;
  pools[0].vbo=401;pools[0].ibo=402;
  batch[0]=(wpk_batch){.tex=0,.pool=0,.count=6,.ioff=12,.gloss=0xffff,.cube=0xffff,.env=2,.spec=3,.power=.5f};
  chunks[0]=(wpk_chunk){.lo={-.1f,-.1f,-.1f},.hi={.1f,.1f,.1f},.first=0,.n=1,.group=WPK_GROUND};
  scene.stride=24;scene.n_tex=4;scene.n_ao=4;scene.textures=tex;scene.cubes=cubes;scene.ao_tex=ao;scene.tex_wet=wet_flags;
  scene.pools=pools;scene.n_pools=1;scene.batches=batch;scene.n_batch=1;scene.chunks=chunks;scene.n_chunk=1;scene.warm=warm;scene.tex_warm=tex_warm;
  rp.fog_far=100;rp.fog_near=10;rp.grade[0]=.8f;rp.grade[1]=.9f;rp.grade[2]=1;
  rp.fog_color[0]=.2f;rp.fog_color[1]=.3f;rp.fog_color[2]=.4f;rp.range[0]=rp.range[1]=rp.range[2]=100;
  rp.uv_shift[0]=.125f;rp.uv_shift[1]=.25f;rp.time=1;rp.view=mat4_identity();rp.over=.7f;
  rp.light_dir[0][0]=1;rp.light_dir[1][1]=1;
  for(int k=0;k<3;k++){rp.light_diffuse[0][k]=.2f*(k+1);rp.light_diffuse[1][k]=.3f*(k+1);rp.ambient[k]=.1f*(k+1);rp.material_diffuse[k]=.5f;rp.material_ambient[k]=.4f;}
  vp=model=mat4_identity();
}
static void near(float a,float b){assert(fabsf(a-b)<1e-5f);}
static void vector(cinder_vk_draw*d,const char*n,const float*expect,int count_){for(int i=0;i<count_;i++)near(value(d,n)[i],expect[i]);}
static void packets(void){
  setup();cinder_vk_draw d;float h[3]={.01f,.02f,.6f};
  batch[0].flags=(1<<2)|(1<<5)|(3<<8)|(4<<12); /* 2x2, 4 frames, 2fps => frame2 */
  assert(native_scene_packet(&d,&scene,batch,&vp,&model,eye,WPK_OPAQUE,&rp,.35f,h));
  assert(d.program==10&&d.target==17&&d.pipeline.depth_test&&d.pipeline.depth_write&&!d.pipeline.blend&&d.pipeline.cull==VK_CULL_MODE_BACK_BIT);
  assert(d.indexed&&d.index_buffer==402&&d.index_offset==12&&d.count==6);
  assert(d.attributes[0].buffer==401&&d.attributes[0].stride==24&&d.attributes[2].format==VK_FORMAT_R8G8B8A8_UNORM&&d.attributes[2].offset==20);
  vector(&d,"uUVOff",(float[2]){.125f,.75f},2);vector(&d,"uGrade",rp.grade,3);vector(&d,"uFogColor",rp.fog_color,3);vector(&d,"uFog",(float[2]){100,10},2);
  vector(&d,"uHorizon",h,3);near(value(&d,"uWet")[0],.35f);assert(d.textures[0]==101&&d.textures[5]==66);
  batch[0].flags=2;scene.two_sided=1;assert(native_scene_packet(&d,&scene,batch,&vp,&model,eye,WPK_BLEND,&rp,0,h));
  assert(d.pipeline.blend&&!d.pipeline.depth_write&&d.pipeline.cull==VK_CULL_MODE_NONE&&d.pipeline.dst_blend==VK_BLEND_FACTOR_ONE);
  rp.no_depth_test=1;assert(native_scene_packet(&d,&scene,batch,&vp,&model,eye,WPK_BLEND,&rp,0,h));assert(!d.pipeline.depth_test);rp.no_depth_test=0;
  pools[0].nbo=403;batch[0].gloss=1;batch[0].cube=0;batch[0].cutout=1;
  assert(native_scene_packet(&d,&scene,batch,&vp,&model,eye,WPK_CUTOUT,&rp,0,h));assert(d.program==21&&d.textures[6]==102&&d.textures[7]==201&&d.attributes[3].buffer==403&&d.attributes[3].stride==8);
  puts("PASS unlit baseline/fog/grade/atlas UV/wet/history; blend/two-sided; gloss separate normals/cube");
}
static void lighting(void){setup();scene.lit=1;scene.stride=32;model.m[12]=.2f;rp.view.m[13]=.3f;mat4 mvp=mat4_mul(vp,model),mv=mat4_mul(rp.view,model);float h[3]={0};cinder_vk_draw d;
  assert(native_scene_packet(&d,&scene,batch,&mvp,&model,eye,WPK_OPAQUE,&rp,0,h));assert(d.program==30);
  vector(&d,"uMVP",mvp.m,16);vector(&d,"uMV",mv.m,16);vector(&d,"uL0",(float[3]){-1,0,0},3);vector(&d,"uL1",(float[3]){0,-1,0},3);
  vector(&d,"uD0",(float[3]){.1f,.2f,.3f},3);vector(&d,"uAmb",(float[3]){.04f,.08f,.12f},3);assert(d.textures[3]==301&&d.textures[4]==55&&d.attributes[3].offset==24);
  batch[0].prog=WPK_LIT_CAR;enhance_on=1;assert(native_scene_packet(&d,&scene,batch,&mvp,&model,eye,WPK_OPAQUE,&rp,0,h));assert(d.program==32);
  vector(&d,"uD0",rp.light_diffuse[0],3);vector(&d,"uAmb",rp.ambient,3);near(value(&d,"uPower")[0],.44f);near(value(&d,"uFrameK")[0],.9f*1.12f);
  vector(&d,"uOver",(float[2]){.7f,over_inv_tan},2);vector(&d,"uOverDir",(float[2]){sinf(OVER_PITCH),cosf(OVER_PITCH)},2);assert(d.textures[1]==103&&d.textures[2]==104);
  batch[0].prog=WPK_LIT_CAR_BLEND;ao_on=0;native_frame_texture=native_over_texture=0;
  assert(native_scene_packet(&d,&scene,batch,&mvp,&model,eye,WPK_CUTOUT,&rp,0,h));assert(d.program==35&&d.textures[3]==99&&d.textures[4]==99&&d.textures[5]==99);
  puts("PASS FF/car/car-blend lighting/MV/model/material/overDir/power/AO/history fallback");
}
static void visibility_and_wheels(void){setup();native_scene_draw(&scene,&vp,&model,eye,WPK_OPAQUE,&rp,0,0);assert(count==1&&rp.draws==1&&rp.triangles==2&&rp.new_chunks==1&&warm[0]&&tex_warm[0]&&pools[0].warm);
  count=0;native_scene_draw(&scene,&vp,&model,eye,WPK_CUTOUT,&rp,0,0);assert(!count);
  chunks[0].first=UINT32_MAX;native_scene_draw(&scene,&vp,&model,eye,WPK_OPAQUE,&rp,0,0);assert(!count);chunks[0].first=0;
  batch[0].pool=1;native_scene_draw(&scene,&vp,&model,eye,WPK_OPAQUE,&rp,0,0);assert(!count);batch[0].pool=0;
  chunks[0].group=WPK_LAMP_ON;native_scene_draw(&scene,&vp,&model,eye,WPK_OPAQUE,&rp,0,0);assert(!count);rp.lamps_on=1;native_scene_draw(&scene,&vp,&model,eye,WPK_OPAQUE,&rp,0,0);assert(count==1);
  setup();chunks[0].group=WPK_WHEEL;float wheels[4][16]={0},rotation[4]={0};mat4 id=mat4_identity();for(int i=0;i<4;i++)memcpy(wheels[i],id.m,sizeof id.m);wheels[0][13]=.5f;rp.wheels=wheels;rp.wheel_rot=rotation;
  native_scene_draw(&scene,&vp,&model,eye,WPK_OPAQUE,&rp,0,0);assert(count==1);near(value(&recorded[0],"uMVP")[13],.5f);near(value(&recorded[0],"uEye")[1],-.5f);
  count=0;rp.wheel_side=2;native_scene_draw(&scene,&vp,&model,eye,WPK_OPAQUE,&rp,0,0);assert(!count);rp.wheel_side=0;rp.wheel_custom=1;
  native_scene_draw(&scene,&vp,&model,eye,WPK_OPAQUE,&rp,0,0);assert(!count);chunks[0].group=WPK_CTIRE;
  native_scene_draw(&scene,&vp,&model,eye,WPK_OPAQUE,&rp,0,0);assert(count==1);
  puts("PASS production culling/chunk bounds/pass/lamps/wheel posture/side/custom-tire selection");
}
static void shadows(void){setup();chunks[0].group=WPK_SHADOW;const wpk_scene *s[1]={&scene};native_shadow_draw(s,&vp,1,&rp);assert(count==3&&rp.draws==3);
  for(int i=0;i<3;i++){cinder_vk_draw*d=&recorded[i];assert(d->program==40&&d->target==17&&d->pipeline.depth_test&&!d->pipeline.depth_write&&d->pipeline.stencil&&d->index_buffer==402);}
  assert(recorded[0].stencil_reference==1&&recorded[1].stencil_reference==0&&recorded[2].stencil_reference==1);
  assert(recorded[0].pipeline.cull==VK_CULL_MODE_BACK_BIT&&recorded[1].pipeline.cull==VK_CULL_MODE_FRONT_BIT&&recorded[2].pipeline.cull==VK_CULL_MODE_BACK_BIT);
  assert(!recorded[0].pipeline.color_mask&&!recorded[1].pipeline.color_mask&&recorded[2].pipeline.color_mask==15);
  assert(recorded[2].pipeline.depth_compare==VK_COMPARE_OP_ALWAYS&&recorded[2].pipeline.stencil_compare==VK_COMPARE_OP_EQUAL&&recorded[2].pipeline.depth_fail==VK_STENCIL_OP_ZERO&&recorded[2].pipeline.depth_pass==VK_STENCIL_OP_ZERO&&recorded[2].pipeline.blend);
  near(value(&recorded[2],"uColor")[3],SHADOW_ALPHA);puts("PASS three-stage stencil shadow pipeline and indices");
}
static void display_targets(void){setup();native_scene=(native_scene_view){777,64,48};render_display_begin(1920,1080);assert(native_scene.target==0&&native_scene.w==1920&&native_scene.h==1080);render_display_begin(1080,1920);assert(native_scene.target==0&&native_scene.w==1080&&native_scene.h==1920);puts("PASS explicit per-display target and extent reset including rotation");}
int main(void){packets();lighting();visibility_and_wheels();shadows();display_targets();puts("native scene packet goldens: PASS (CPU only, NOT GL/Vulkan pixel equivalence)");return 0;}
'''
with tempfile.TemporaryDirectory(prefix='native-vk-scene-',dir=OUT) as d:
    d=Path(d);p=d/'goldens.c';p.write_text(prefix+'\n'+helpers+'\n'+n+'\n'+body)
    env=dict(os.environ,TMPDIR=str(d),TMP=str(d),TEMP=str(d),HOME=str(d),PYTHONDONTWRITEBYTECODE='1')
    flags=['-I',str(ROOT/'src')]
    if sys.platform=='darwin':flags+=['-I','/opt/homebrew/include']
    cmd=[os.environ.get('CC','clang'),'-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-fsanitize=undefined',*flags,str(p),'-lm','-o',str(d/'goldens')]
    subprocess.run(cmd,env=env,cwd=d,check=True,timeout=120)
    subprocess.run([str(d/'goldens')],env=env,cwd=d,check=True,timeout=30)
print('render_native_scene.inc sha256',hashlib.sha256(n.encode()).hexdigest())
