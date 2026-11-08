#!/usr/bin/env python3
"""Compile actual native effects helpers and public sprite/tire/tail functions.
Mock packet recording only, with NO GL functions declared; not GPU/FPS evidence.
"""
from pathlib import Path
import os,re,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[1];O=Path(os.environ.get('TMPDIR','/Volumes/CodexWork')).resolve()
assert O==Path('/Volumes/CodexWork') or str(O).startswith('/Volumes/CodexWork/')
s=(R/'src/render.c').read_text()
def fun(anchor):
 a=s.index(anchor);b=s.index('{',a);mask=re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',lambda m:' '*len(m.group()),s,flags=re.S);n=0
 for i in range(b,len(s)):
  n+=(mask[i]=='{')-(mask[i]=='}')
  if n==0:return s[a:i+1]
 raise ValueError(anchor)
pre=r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define WMMT_NATIVE_VK 1
#define __ANDROID__ 1
#include "render.h"
#include "native_vk.h"
typedef unsigned GLenum;
#define GL_SRC_ALPHA 0x302
#define GL_SRC_COLOR 0x300
typedef struct {uint32_t target;int w,h;} native_scene_view;
static native_scene_view native_scene={9,100,80};
static struct {uint32_t id;} progs[2]={{123},{124}};
static uint32_t white_tex=7;
typedef struct {float pos[3],uv[2],rgba[4];} tail_render_vertex;
static struct {int failed;} tail_render;
static struct {float mvp[16],eye[3],color[3],fog[2],uv[2],grade[3],wet,horizon[3];} layout;
static unsigned initialized,submitted,reject;static cinder_vk_draw recorded;
static unsigned char vertex_copy[4*RENDER_MAX_SPRITES*sizeof(render_vertex)+2*TAIL_TRAIL_MAX_VERTICES*sizeof(tail_render_vertex)];
static size_t copied;static uint32_t utex,uframe;
static cinder_vk_sampler upload_sampler={.use_state=1,.mipmaps=1,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_NEAREST,.mipmap_mode=VK_SAMPLER_MIPMAP_MODE_LINEAR,
 .address_u=VK_SAMPLER_ADDRESS_MODE_REPEAT,.address_v=VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT,.anisotropy=4};
void cinder_vk_screen_extent(int*w,int*h){*w=320;*h=240;}
int cinder_vk_draw_init(cinder_vk_draw*d,uint32_t prog,uint32_t target,int w,int h){
 assert(prog==123&&w>0&&h>0);++initialized;memset(d,0,sizeof*d);d->program=prog;d->target=target;d->viewport[2]=d->scissor[2]=w;d->viewport[3]=d->scissor[3]=h;
 d->pipeline.color_mask=15;d->pipeline.depth_compare=VK_COMPARE_OP_LESS_OR_EQUAL;d->pipeline.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;d->index_type=VK_INDEX_TYPE_UINT16;
 for(int i=0;i<8;++i)d->attributes[i].value[3]=1;return 1;
}
int cinder_vk_uniform(cinder_vk_draw*d,const char*name,const void*value,size_t bytes){
 size_t offset=0,need=0;
#define SLOT(n,f) if(!strcmp(name,n)){offset=offsetof(__typeof__(layout),f);need=sizeof layout.f;}
 SLOT("uMVP",mvp) else SLOT("uEye",eye) else SLOT("uFogColor",color) else SLOT("uFog",fog) else SLOT("uUVOff",uv) else SLOT("uGrade",grade) else SLOT("uWet",wet) else SLOT("uHorizon",horizon) else assert(0);
#undef SLOT
 assert(need==bytes);memcpy(d->uniforms+offset,value,bytes);return 1;
}
int cinder_vk_texture(cinder_vk_draw*d,const char*name,uint32_t tex){if(!strcmp(name,"uTex")){d->textures[0]=tex;utex=tex;}else{assert(!strcmp(name,"uFrame"));d->textures[1]=tex;uframe=tex;}return 1;}
int cinder_vk_texture_sampler(uint32_t tex,cinder_vk_sampler*out){assert(tex==17);*out=upload_sampler;return 1;}
int cinder_vk_sampler_state(cinder_vk_draw*d,const char*name,const cinder_vk_sampler*state){assert(!strcmp(name,"uTex"));d->samplers[0]=*state;return 1;}
int cinder_vk_submit(const cinder_vk_draw*d){
 ++submitted;if(reject)return 0;recorded=*d;size_t top=d->count-1;
 if(d->indexed){assert(d->indices&&d->index_bytes==(size_t)d->count*2&&d->count%6==0);top=0;for(uint32_t i=0;i<d->count;++i){uint16_t ix;memcpy(&ix,(const char*)d->indices+i*2,2);if(ix>top)top=ix;}}
 for(int i=0;i<3;++i){const cinder_vk_attribute*a=&d->attributes[i];assert(!a->buffer&&a->data&&a->stride);size_t size=i==0?12:i==1?8:a->format==VK_FORMAT_R32G32B32A32_SFLOAT?16:4;assert(a->offset+top*a->stride+size<=a->bytes);}
 copied=d->attributes[0].bytes;assert(copied<=sizeof vertex_copy);memcpy(vertex_copy,d->attributes[0].data,copied);memcpy(&layout,d->uniforms,sizeof layout);return 1;
}
'''
real=(R/'src/render_native_effects.inc').read_text()+'\n'+'\n'.join(fun(x) for x in ['static void sprites(', 'void render_sprites(', 'void render_sprites_by_colour(', 'int render_tail_triangles(', 'void render_tire_tracks('])
post=r'''
static void common(void){assert(recorded.program==123&&recorded.target==9&&recorded.viewport[2]==100&&recorded.scissor[3]==80);assert(!recorded.pipeline.depth_write&&!recorded.pipeline.stencil&&!recorded.pipeline.cull);assert(utex&&uframe==white_tex);assert(layout.grade[0]==1&&layout.grade[1]==1&&layout.grade[2]==1&&layout.wet==0&&layout.uv[0]==0&&layout.eye[0]==0);}
int main(void){
 mat4 vp=mat4_identity();render_params p={0};render_vertex v[8]={0};for(int i=0;i<8;++i){v[i].pos[0]=(float)i;v[i].rgba[0]=231;}
 render_sprites(&vp,v,2,17,&p);assert(submitted==1&&p.draws==1&&recorded.count==12&&recorded.indexed&&copied==sizeof v);common();
 assert(recorded.pipeline.depth_test&&recorded.pipeline.blend&&recorded.pipeline.src_blend==VK_BLEND_FACTOR_SRC_ALPHA&&recorded.pipeline.dst_blend==VK_BLEND_FACTOR_ONE&&recorded.pipeline.color_mask==15);
 v[0].rgba[0]=0;assert(((render_vertex*)vertex_copy)[0].rgba[0]==231);
 p.no_depth_test=1;render_sprites_by_colour(&vp,v,1,17,&p);assert(submitted==2&&!recorded.pipeline.depth_test&&recorded.pipeline.src_blend==VK_BLEND_FACTOR_SRC_COLOR);
 unsigned before=submitted;render_sprites(&vp,v,0,17,&p);assert(submitted==before);
 render_tire_tracks(&vp,v,2,17,&p);assert(submitted==3&&p.triangles==4);common();assert(recorded.pipeline.depth_test&&recorded.pipeline.color_mask==7&&recorded.pipeline.src_blend==VK_BLEND_FACTOR_SRC_ALPHA&&recorded.pipeline.dst_blend==VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA);
 assert(recorded.samplers[0].use_state&&recorded.samplers[0].mipmaps&&recorded.samplers[0].mag_filter==VK_FILTER_NEAREST&&recorded.samplers[0].anisotropy==4&&recorded.samplers[0].mipmap_mode==VK_SAMPLER_MIPMAP_MODE_LINEAR);
 assert(recorded.samplers[0].address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&recorded.samplers[0].address_v==VK_SAMPLER_ADDRESS_MODE_REPEAT);
 assert(upload_sampler.address_u==VK_SAMPLER_ADDRESS_MODE_REPEAT&&upload_sampler.address_v==VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT);
 before=submitted;render_tire_tracks(&vp,v,2,0,&p);assert(submitted==before);reject=1;int draws=p.draws,tris=p.triangles;render_tire_tracks(&vp,v,2,17,&p);assert(p.draws==draws&&p.triangles==tris);reject=0;
 TailTrailVertex tail[3]={0};for(int i=0;i<3;++i){tail[i].position.x=i;for(int k=0;k<4;++k)tail[i].rgba[k]=.1234567f;}
 assert(render_tail_triangles(&vp,tail,3,&p));common();assert(!recorded.indexed&&recorded.count==3&&recorded.attributes[2].format==VK_FORMAT_R32G32B32A32_SFLOAT&&copied==3*sizeof(tail_render_vertex));
 assert(((tail_render_vertex*)vertex_copy)[0].rgba[0]==.1234567f&&layout.fog[0]==1e30f&&layout.fog[1]==1e29f&&p.triangles==tris+1);
 before=submitted;tail[0].rgba[0]=NAN;assert(!render_tail_triangles(&vp,tail,3,&p)&&submitted==before);tail[0].rgba[0]=-.01f;assert(!render_tail_triangles(&vp,tail,3,&p));tail[0].rgba[0]=.5f;
 assert(!render_tail_triangles(&vp,tail,2,&p));vp.m[0]=NAN;assert(!render_tail_triangles(&vp,tail,3,&p));vp=mat4_identity();
 reject=1;assert(!render_tail_triangles(&vp,tail,3,&p)&&tail_render.failed);reject=0;tail_render.failed=0;
 native_scene=(native_scene_view){0};assert(render_tail_triangles(&vp,tail,3,&p));assert(recorded.target==0&&recorded.viewport[2]==320&&recorded.viewport[3]==240);
 puts("production sprite/add-color, bounded tire RGB/sampler override, float tail + failure + viewport: PASS (CPU packets, no GL state)");
}
'''
with tempfile.TemporaryDirectory(prefix='native-vk-effects-',dir=O) as d:
 d=Path(d);f=d/'test.c';f.write_text(pre+real+post);exe=d/'test';cmd=['clang','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(R/'src')]
 if sys.platform=='darwin':cmd+=['-I','/opt/homebrew/include']
 cmd += [str(f),'-lm','-o',str(exe)];subprocess.run(cmd,check=True,timeout=120);subprocess.run([str(exe)],check=True,timeout=30)
