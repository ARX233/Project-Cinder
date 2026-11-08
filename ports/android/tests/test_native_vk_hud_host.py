#!/usr/bin/env python3
"""UBSan contracts of the complete production hud.c and native packet builders.

No extracted/reimplemented HUD draw functions, GL context, GPU or device. The
fixture only provides resource handles, outside HUD owners and a packet recorder.
All draw/state/query GL names are poisoned when compiling the native HUD path.
Generated files stay in external TMPDIR. Canonical sources lacking private
headers require CINDER_PRIVATE_SRC pointing to the reviewed generated headers.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(os.environ.get("TMPDIR", "/Volumes/CodexWork")).resolve()
if TMP != Path("/Volumes/CodexWork") and not str(TMP).startswith("/Volumes/CodexWork/"):
    raise SystemExit("TMPDIR must be inside /Volumes/CodexWork")
TMP.mkdir(exist_ok=True)
PARENT = TMP
PRIVATE = Path(os.environ["CINDER_PRIVATE_SRC"]).resolve() if os.environ.get("CINDER_PRIVATE_SRC") else None
if not (ROOT / "src/racing_lamp_data.h").is_file() and (PRIVATE is None or not (PRIVATE / "racing_lamp_data.h").is_file()):
    raise SystemExit("CINDER_PRIVATE_SRC must name the reviewed private-header directory (racing_lamp_data.h missing)")
HUD = (ROOT / "src/hud.c").read_text()
NATIVE = (ROOT / "src/hud_native_vk.inc").read_text()
assert len(re.findall(r"\bglDraw(?:Arrays|Elements)\s*\(", HUD)) == 11
assert not re.search(r"\b(?:gl[A-Z]\w*|vkgl_\w*)\s*\(", NATIVE)

PREFIX = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "glstub.h"
#define WMMT_GL_H
#define WMMT_NATIVE_VK 1
/* Even unused GL-state/draw/resource dependencies fail compilation, not just
 * an assert in one exercised branch. Native resources use explicit APIs. */
#pragma GCC poison gl_compile_program glGenTextures glBindTexture glTexParameteri glTexImage2D glDeleteTextures glGenBuffers glBindBuffer glBufferData glDeleteBuffers glGetError
#pragma GCC poison glDrawArrays glDrawElements glGetIntegerv glGetBooleanv glGetUniformfv glGetUniformiv glGetVertexAttribiv glGetVertexAttribPointerv glIsEnabled glGetUniformLocation
#pragma GCC poison glUseProgram glUniform1i glUniform1f glUniform2f glUniform3fv glUniform4f glUniform4fv glUniformMatrix4fv glActiveTexture glEnable glDisable glBlendFunc glBlendEquation glBlendEquationSeparate glBlendFuncSeparate glDepthFunc glDepthMask glViewport glScissor glClear glVertexAttribPointer glVertexAttrib4f glEnableVertexAttribArray glDisableVertexAttribArray glBindVertexArrayOES
#pragma GCC poison vkgl_preview_save vkgl_preview_restore vkgl_scope_save vkgl_scope_restore
#include "hud.c"

static int width=1920,height=1080,submit_fail,clear_fail,draw_n,clear_n,warm_n,recording=1;
static unsigned resource_calls,anm_calls,mark_calls;
static int mark_crown, missing_console_crown, crown_crop;
enum { TEST_RIVAL = 12, TEST_RIVAL_PH = 13 };
static struct {
  int count, anim, frame, nswap;
  float x,y,zoom;
  anm_swap swap[24];
} rival_draw;
static int rival_glyph[8], rival_glyphs;
typedef struct {cinder_vk_draw d; float vertex[160]; size_t cpu_bytes; uint64_t digest;} capture;
static capture captures[4096];
static int clear_rect[4],sequence,clear_order,first_road_order;
static VkImageAspectFlags clear_aspects;
static uint32_t clear_target;
void cinder_vk_screen_extent(int *w,int *h){*w=width;*h=height;}
int cinder_vk_draw_init(cinder_vk_draw *d,uint32_t program,uint32_t target,int w,int h){
  if(!program||w<=0||h<=0)return 0;
  memset(d,0,sizeof *d); d->program=program;d->target=target;d->uniform_bytes=128;
  d->viewport[2]=d->scissor[2]=w;d->viewport[3]=d->scissor[3]=h;
  /* Poison init pipeline/constant defaults: production explicitly sets them. */
  memset(&d->pipeline,0x55,sizeof d->pipeline);
  memset(d->attributes,0x33,sizeof d->attributes);
  d->index_type=VK_INDEX_TYPE_UINT16;
  return 1;
}
int cinder_vk_uniform(cinder_vk_draw *d,const char *name,const void *p,size_t n){
  size_t off;
  if(!strcmp(name,"uProj")||!strcmp(name,"uMVP")){off=0;assert(n==64);}
  else if(!strcmp(name,"uColor")||!strcmp(name,"uMul")){off=64;assert(n==16);}
  else {assert(!strcmp(name,"uAdd"));off=80;assert(n==16);}
  memcpy(d->uniforms+off,p,n);return 1;
}
int cinder_vk_texture(cinder_vk_draw *d,const char *name,uint32_t tex){assert(!strcmp(name,"uTex"));d->textures[0]=tex;return 1;}
int cinder_vk_sampler_state(cinder_vk_draw*d,const char*name,const cinder_vk_sampler*s){assert(!strcmp(name,"uTex"));d->samplers[0]=*s;return 1;}
static size_t format_size(VkFormat f){switch(f){case VK_FORMAT_R32G32_SFLOAT:return 8;case VK_FORMAT_R32G32B32_SFLOAT:return 12;case VK_FORMAT_R8G8B8A8_UNORM:return 4;default:assert(0);return 0;}}
static float uf(const cinder_vk_draw *d,size_t float_index){float v;memcpy(&v,d->uniforms+float_index*4,4);return v;}
static void near(float x,float y){assert(fabsf(x-y)<0.0001f);}
static void full_box(const cinder_vk_draw *d){assert(d->target==0&&d->viewport[0]==0&&d->viewport[1]==0&&d->viewport[2]==width&&d->viewport[3]==height&&!memcmp(d->viewport,d->scissor,sizeof d->viewport));}
static void white(const cinder_vk_attribute *a){assert(a->format==VK_FORMAT_UNDEFINED&&a->buffer==0&&a->data==NULL&&a->offset==0&&a->bytes==0);for(int i=0;i<4;++i)near(a->value[i],1);}
int cinder_vk_submit(const cinder_vk_draw *d){
  if(submit_fail)return 0;
  assert(d->program&&d->target==0&&d->count&&d->first==0);
  assert(d->viewport[0]>=0&&d->viewport[1]>=0&&d->viewport[2]>0&&d->viewport[3]>0);
  assert(d->scissor[0]>=0&&d->scissor[1]>=0&&d->scissor[0]+d->scissor[2]<=width&&d->scissor[1]+d->scissor[3]<=height);
  const cinder_vk_pipeline *p=&d->pipeline;
  assert(p->blend&&p->blend_op==VK_BLEND_OP_ADD&&p->color_mask==15&&p->cull==VK_CULL_MODE_NONE&&p->asset_front==VK_FRONT_FACE_COUNTER_CLOCKWISE);
  assert(p->depth_compare==VK_COMPARE_OP_LESS_OR_EQUAL&&!p->stencil&&p->stencil_compare==VK_COMPARE_OP_ALWAYS&&p->stencil_fail==VK_STENCIL_OP_KEEP&&p->depth_fail==VK_STENCIL_OP_KEEP&&p->depth_pass==VK_STENCIL_OP_KEEP&&p->stencil_compare_mask==255&&p->stencil_write_mask==255);
  for(int i=1;i<CINDER_VK_SAMPLERS;++i)assert(d->textures[i]==0);
  if(d->textures[0]){const cinder_vk_sampler*s=&d->samplers[0];assert(s->use_state&&!s->mipmaps&&s->min_filter==VK_FILTER_LINEAR&&s->mag_filter==VK_FILTER_LINEAR&&s->mipmap_mode==VK_SAMPLER_MIPMAP_MODE_NEAREST&&s->address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->address_v==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->anisotropy==1);}
  if(d->warm_only){assert(!recording);++warm_n;}else assert(recording);
  assert(draw_n<4096);capture *c=&captures[draw_n++];memset(c,0,sizeof *c);c->d=*d;
  if(d->program==NAVI.prog&&d->indexed&&!first_road_order)first_road_order=++sequence;else ++sequence;
  uint32_t top=d->indexed?2:d->count-1;
  c->digest=1469598103934665603ULL;
  for(int i=0;i<CINDER_VK_ATTRIBUTES;++i){const cinder_vk_attribute *a=&d->attributes[i];
    if(a->format==VK_FORMAT_UNDEFINED){white(a);continue;}
    size_t n=(size_t)top*a->stride+format_size(a->format);
    if(a->buffer){assert(a->buffer==201&&a->offset+n<=1024);continue;}
    assert(a->data&&a->stride&&a->offset<=a->bytes&&n<=a->bytes-a->offset);
    const unsigned char *bytes=(const unsigned char *)a->data+a->offset;
    for(size_t j=0;j<n;++j)c->digest=(c->digest^bytes[j])*1099511628211ULL;
    if(i==0){c->cpu_bytes=n;memcpy(c->vertex,bytes,n<sizeof c->vertex?n:sizeof c->vertex);}
  }
  if(d->indexed){assert(d->index_buffer==202&&d->index_type==VK_INDEX_TYPE_UINT16&&d->index_offset%2==0&&d->index_offset+(size_t)d->count*2<=128);}
  return 1;
}
int cinder_vk_clear(uint32_t target,VkImageAspectFlags aspects,const float color[4],const int rect_[4]){
  if(clear_fail)return 0;
  assert(recording&&rect_&&color==NULL);clear_target=target;clear_aspects=aspects;
  memcpy(clear_rect,rect_,sizeof clear_rect);++clear_n;clear_order=++sequence;return 1;
}
/* Resource API fakes, never a draw-state context. */
uint32_t cinder_vk_program_create(const char *v,const char *f,const char **a,int n){(void)v;(void)f;(void)a;return (uint32_t)n;}
uint32_t cinder_vk_texture_rgba8(int w,int h,const void *p,size_t n,const cinder_vk_sampler *s){(void)w;(void)h;(void)p;(void)n;(void)s;return 1000+resource_calls++;}
void cinder_vk_texture_destroy(uint32_t id){(void)id;}
uint32_t cinder_vk_buffer_create(size_t n,const void *p){(void)n;(void)p;return 2000+resource_calls++;}
void cinder_vk_buffer_destroy(uint32_t id){(void)id;}
/* anm owns its separate packets. Track the live HUD's delegation, not fake its
 * sprite placement inside HUD or add a GL bridge around anm calls. */
int anm_find(const char *s){
  if(!strcmp(s,"cons_g_R"))return 10;
  if(!strcmp(s,"cons_g_R_tg"))return 11;
  if(!strcmp(s,"cons_g_rival"))return TEST_RIVAL;
  if(!strcmp(s,"cons_g_rival_ph"))return TEST_RIVAL_PH;
  return -1;
}
int anm_sprite(int s){return s==missing_console_crown?-1:s;}
int anm_frames(int s){(void)s;return 1000;}
float anm_edge(void){return EDGE;}
void anm_preload(int a){(void)a;}
int anm_warm_sprite(int a,int b){(void)a;(void)b;return 1;}
int anm_sprites(int a,int *b,int c){(void)a;(void)b;(void)c;return 0;}
float anm_sprite_width(int a){(void)a;return 32;}
int anm_sprite_rect(int a,int b,int c,float d[4]){
  (void)b;
  if((a!=TEST_RIVAL&&a!=TEST_RIVAL_PH)||(c!=T_VS_NAME&&c!=T_VS_TITLE))return 0;
  memcpy(d,(float[]){1,2,3,4},sizeof(float)*4);
  return 1;
}
int anm_sprite_xf(int a,int b,int c,float d[6],float e[4],float f[4]){
  (void)b;
  if(a!=11||c!=T_R_CROWN)return 0;
  memcpy(d,(float[]){-32,-107,.5f,0,0,.5f},sizeof(float)*6);
  memcpy(e,(float[]){1,1,1,1},sizeof(float)*4);memset(f,0,sizeof(float)*4);
  return 1;
}
void anm_draw(int a,int b,float c){(void)a;(void)b;(void)c;++anm_calls;}
void anm_draw_ex(int a,int b,float c,float d,float e,const anm_swap *f,int g){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;++anm_calls;}
void anm_draw_xf(int a,int b,float c,float d,float e,float f,const anm_swap *g,int h){
  (void)c;
  ++anm_calls;
  if(a==10||a==11)++mark_calls;
  if(a==11)for(int i=0;i<h;++i)if(g[i].from==T_R_CROWN)mark_crown=g[i].to;
  if(a==TEST_RIVAL||a==TEST_RIVAL_PH){
    assert(h>=0&&(size_t)h<=sizeof rival_draw.swap/sizeof rival_draw.swap[0]);
    ++rival_draw.count;rival_draw.anim=a;rival_draw.frame=b;rival_draw.x=d;rival_draw.y=e;rival_draw.zoom=f;rival_draw.nswap=h;
    memcpy(rival_draw.swap,g,(size_t)h*sizeof *g);
  }
}
void anm_draw_part(int a,const float b[4],const float c[4],float d){
  (void)b;(void)c;(void)d;++anm_calls;
  if(rival_draw.count&&rival_glyphs<(int)(sizeof rival_glyph/sizeof rival_glyph[0]))rival_glyph[rival_glyphs++]=a;
}
void anm_draw_part_col(int a,const float b[4],const float c[4],const float d[4],const float e[4]){
  (void)c;(void)d;(void)e;++anm_calls;
  if(a==1738){assert(b[0]==0&&b[1]==0&&b[2]==128&&b[3]==62);++crown_crop;}
}
void anm_draw_sprite(int a,float b,float c,float d){(void)a;(void)b;(void)c;(void)d;++anm_calls;}
int title_glyphs(int id,const unsigned short **g){
  static const unsigned short test_title[]={42};
  if(id!=12345)return 0;
  *g=test_title;
  return 1;
}
int title_glyph_half(int g){(void)g;return 0;}
float car_kmh(const car_state *c){return c->speed*3.6f;}
int car_link_observation_fresh(int p,double t){(void)p;(void)t;return 1;}
void snd_menu(int s){(void)s;}
void snd_effect(const char *s,float v){(void)s;(void)v;}
static void reset(void){draw_n=clear_n=warm_n=sequence=clear_order=first_road_order=0;submit_fail=clear_fail=0;recording=1;rival_draw.count=rival_glyphs=0;}
static void matrix(const cinder_vk_draw *d,mat4 m){for(int i=0;i<16;++i)near(uf(d,(size_t)i),m.m[i]);}
'''

TESTS = r'''
static void primitives(void){
  reset();hud_native_paint p=hud_native_paint_for(screen_ortho(1024,768));p.mul=(hud_native_rgba){.2f,.3f,.4f,.5f};
  hud_native_fill_rect(p,1,2,3,4);hud_native_ring(p,20,30,4,8);hud_native_triangle(p,0,0,1,0,0,1);
  hud_native_fill_rrect(p,(rect){0,0,40,30},8);hud_native_stroke_rrect(p,(rect){0,0,40,30},8,2);hud_native_chevron(p,20,30,4,1,0);
  assert(draw_n==6);const uint32_t counts[6]={4,66,3,30,58,3};
  for(int i=0;i<6;++i){cinder_vk_draw *d=&captures[i].d;full_box(d);assert(d->program==prog&&d->count==counts[i]&&!d->indexed&&!d->index_buffer&&!d->pipeline.depth_test&&!d->pipeline.depth_write&&!d->textures[0]);matrix(d,p.projection);for(int j=0;j<4;++j)near(uf(d,16+j),((float[]){.2f,.3f,.4f,.5f})[j]);}
  assert(captures[0].vertex[0]==1&&captures[0].vertex[1]==2&&captures[0].vertex[6]==4&&captures[0].vertex[7]==6);
  reset();hud_sprite sp={88,20,10};p.add=(hud_native_rgba){.1f,.2f,.3f,0};p.additive=1;
  hud_native_draw_k(p,&sp,50,60,90,2);assert(draw_n==1);cinder_vk_draw*d=&captures[0].d;full_box(d);assert(d->program==tex_prog&&d->textures[0]==88&&d->pipeline.dst_blend==VK_BLEND_FACTOR_ONE&&d->count==4&&d->attributes[1].offset==8&&d->attributes[0].bytes==64);white(&d->attributes[2]);near(captures[0].vertex[0],60);near(captures[0].vertex[1],40);near(uf(d,20),.1f);
  puts("PASS all six solid source sites plus sprite source: topology/count/bounded spans/UBO/constant white");
}
static void navi(void){
  static navi_mesh meshes[4]={{-1,0,1,3,3,3},{-1,0,0,0,0,3},{8,0,0,6,6,3},{8,1,0,9,9,3}};
  NAVI.n=4;NAVI.mesh=meshes;NAVI.vbo=201;NAVI.ibo=202;NAVI.tex[0]=301;NAVI.tex[1]=302;
  navi_city=navi_requested=0;NAVI.next=NAVI_UNSET;
  hud_state h={.screen_w=1024,.screen_h=768};car_race r={.area=8,.next_area=9,.map_x=100,.map_z=200,.map_angle=.3f};
  reset();hud_native_navi(&h,&r);assert(clear_n==1&&draw_n==4&&clear_target==0&&clear_aspects==VK_IMAGE_ASPECT_DEPTH_BIT&&clear_order<first_road_order);
  assert(!memcmp(clear_rect,(int[]){35,476,182,127},sizeof clear_rect));
  assert(captures[0].d.index_offset==0&&captures[1].d.index_offset==18&&captures[2].d.index_offset==6);
  for(int i=0;i<3;++i){cinder_vk_draw*d=&captures[i].d;assert(d->indexed&&d->index_buffer==202&&d->textures[0]==301&&d->pipeline.depth_test&&d->pipeline.depth_write==(i<2));assert(!memcmp(d->viewport,clear_rect,sizeof clear_rect)&&!memcmp(d->scissor,clear_rect,sizeof clear_rect));assert(d->attributes[2].format==VK_FORMAT_R8G8B8A8_UNORM&&d->attributes[1].offset==d->attributes[0].offset+12&&d->attributes[2].offset==d->attributes[0].offset+20);}
  cinder_vk_draw*icon=&captures[3].d;assert(!icon->indexed&&!icon->index_buffer&&!icon->pipeline.depth_test&&!icon->pipeline.depth_write&&icon->textures[0]==302&&icon->attributes[0].stride==20&&icon->attributes[1].offset==12);white(&icon->attributes[2]);
  mat4 base;memcpy(base.m,captures[0].d.uniforms,sizeof base.m);
  /* Left clipping retains world->pixel placement; scissor equals actual viewport. */
  hud_race_layout_set(HUD_RACE_MAP,1,-70,0);reset();hud_native_navi(&h,&r);assert(clear_n==1&&draw_n==4&&clear_rect[0]==0);
  float desired_x=floorf((tx(17)-70)*1.875f+.5f),desired_width=182;
  float expected=desired_x+(base.m[12]*.5f+.5f)*desired_width;
  float actual=clear_rect[0]+(uf(&captures[0].d,12)*.5f+.5f)*clear_rect[2];near(expected,actual);
  for(int i=0;i<4;++i)assert(!memcmp(captures[i].d.viewport,clear_rect,sizeof clear_rect)&&!memcmp(captures[i].d.scissor,clear_rect,sizeof clear_rect));
  const float shifts[4][2]={{-70,0},{1000,0},{0,-400},{0,400}};
  for(int edge=0;edge<4;++edge){
    hud_race_layout_set(HUD_RACE_MAP,1,shifts[edge][0],shifts[edge][1]);reset();hud_native_navi(&h,&r);assert(clear_n==1&&draw_n==4);
    float dx=floorf((tx(17)+shifts[edge][0])*1.875f+.5f),dy=floorf((768-(ty(285)+shifts[edge][1])-82*HUD_K)*1.40625f+.5f);
    float ex=dx+(base.m[12]*.5f+.5f)*182,ey=dy+(base.m[13]*.5f+.5f)*127;
    float ax=clear_rect[0]+(uf(&captures[0].d,12)*.5f+.5f)*clear_rect[2],ay=clear_rect[1]+(uf(&captures[0].d,13)*.5f+.5f)*clear_rect[3];near(ex,ax);near(ey,ay);
    for(int i=0;i<4;++i)assert(!memcmp(captures[i].d.viewport,clear_rect,sizeof clear_rect)&&!memcmp(captures[i].d.scissor,clear_rect,sizeof clear_rect));
  }
  hud_race_layout_set(HUD_RACE_MAP,1,-5000,0);reset();hud_native_navi(&h,&r);assert(!clear_n&&!draw_n);
  hud_race_layout_set(HUD_RACE_MAP,1,0,0);reset();clear_fail=1;hud_native_navi(&h,&r);assert(!draw_n);
  reset();navi_requested=1;hud_native_navi(&h,&r);assert(!draw_n&&!clear_n);navi_requested=0;
  NAVI.n=0;
  puts("PASS navi local depth-only clear/order, both indexed layers, lit filtering, viewport/scissor/crop, independent white arrow");
}
static void preview(void){
  /* Cached real production preview_load avoids disk but is still actually called. */
  preview_pack=0;preview_style=0;preview_ok=1;
  int n=METERDB[0].n[0];assert(n>0&&n<=METERDB_MAX_PARTS);
  for(int i=0;i<n;++i){preview_meter[i]=(hud_sprite){(GLuint)(400+i),64,64};preview_alpha[i]=(preview_alpha_bounds){0,0,64,64,1};}
  reset();hud_ui_begin(800,600);hud_ui_rect(1,2,3,4,.1f,.2f,.3f,.4f);
  unsigned before=resource_calls;assert(hud_meter_preview(0,0,100,120,200,160,.35f));assert(draw_n==n&&resource_calls==before&&ui_n==1);
  for(int i=0;i<n;++i){cinder_vk_draw*d=&captures[i].d;full_box(d);matrix(d,screen_ortho(1024,768));near(uf(d,19),.35f);for(int j=20;j<24;++j)near(uf(d,j),0);white(&d->attributes[2]);assert(!d->pipeline.depth_test&&!d->pipeline.depth_write&&d->textures[0]==(uint32_t)(400+i));assert(d->pipeline.dst_blend==(METERDB[0].parts[0][i].add?VK_BLEND_FACTOR_ONE:VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA));}
  hud_ui_end();assert(draw_n==n+1);matrix(&captures[n].d,screen_ortho(800,600));near(uf(&captures[n].d,16),.1f);near(uf(&captures[n].d,19),.4f);
  assert(!hud_meter_preview(0,0,0,0,0,1,1));assert(!hud_meter_preview(0,0,0,0,1,1,0));assert(!hud_meter_preview(-1,0,0,0,1,1,1));
  puts("PASS production meter preview cached selection/alpha/constant white, no snapshot or foreign paint, pending UI independent");
}
static void meters(void){
  int pack=-1,zone=-1,part=-1;
  for(int c=0;c<METER_CARS&&pack<0;++c)for(int z=0;z<MP_ZONES&&pack<0;++z)for(int i=0;i<METERDB_V2[c].n[z];++i)
    if(METERDB_V2[c].parts[z][i].add){pack=c;zone=z;part=i;break;}
  assert(pack>=0);meter_car=&METERDB[pack];meter_v2_active=1;meter_night=zone;
  memset(METER,0,sizeof METER);METER[part]=(hud_sprite){700,64,32};racing_lamp_slot=part;racing_lamp_on=(hud_sprite){701,64,32};
  car_state c={.rev_rate=.9f,.rev_lamp_frame=2};hud_native_paint paint=hud_native_paint_for(screen_ortho(1024,768)),saved=paint;
  hud_race_layout_set(HUD_RACE_METER,1.3f,25,-10);paint=hud_native_group(paint,HUD_RACE_METER);
  reset();hud_native_draw_meters(paint,&c);assert(draw_n==1&&captures[0].d.textures[0]==701&&captures[0].d.pipeline.dst_blend==VK_BLEND_FACTOR_ONE);matrix(&captures[0].d,paint.projection);
  c.rev_lamp_frame=1;reset();hud_native_draw_meters(paint,&c);assert(draw_n==1&&captures[0].d.textures[0]==700);
  hud_native_draw_k(saved,&METER[part],0,0,0,1);assert(draw_n==2&&captures[1].d.pipeline.dst_blend==VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA);matrix(&captures[1].d,saved.projection);
  hud_race_layout_set(HUD_RACE_METER,1,0,0);meter_car=NULL;meter_v2_active=0;racing_lamp_slot=-1;racing_lamp_on=(hud_sprite){0};
  puts("PASS real meter table additive part/60Hz lamp selection/group projection cannot leak into following sprite");
}
static void warm(void){
  memset(SPR,0,sizeof SPR);memset(METER,0,sizeof METER);memset(spr_warm,0,sizeof spr_warm);memset(meter_warm,0,sizeof meter_warm);memset(navi_warm,0,sizeof navi_warm);
  SPR[0].tex=501;METER[0].tex=502;NAVI.tex[0]=503;NAVI.tex[1]=0;
  reset();recording=0;assert(hud_warm(1024,768,1)==2&&warm_n==1&&draw_n==1);assert(meter_warm[0]&&!spr_warm[0]);
  assert(hud_warm(1024,768,8)==0&&warm_n==3&&draw_n==3);assert(hud_warm(1024,768,8)==0&&draw_n==3);
  spr_warm[0]=0;submit_fail=1;assert(hud_warm(1024,768,1)==1&&!spr_warm[0]);
  reset();recording=0;width=0;assert(hud_warm(1024,768,1)==1&&!spr_warm[0]);width=1920;
  puts("PASS warm source uses warm_only outside frame recording, bounded budget/retry/extent rejection");
}
static void ui_and_controls(void){
  reset();hud_ui_begin(1024,768);for(int i=0;i<UI_QUADS+1;++i)hud_ui_rect(i,2,3,4,.2f,.4f,.6f,.8f);hud_ui_end();assert(draw_n==2&&captures[0].d.count==UI_QUADS*6&&captures[1].d.count==6);
  reset();hud_draw_menu_option(1024,768,1);assert(draw_n==20);reset();hud_draw_menu_dress(1024,768,0);assert(draw_n==15);reset();hud_draw_menu_hidden(1024,768,1);assert(draw_n==3);reset();hud_draw_menu_erase(1024,768,0,1);assert(draw_n==11);reset();hud_draw_menu_keys(1024,768,-1,1,1);assert(draw_n==15);
  for(int mode=0;mode<HUD_STEER_MODES;++mode){reset();hud_draw_layout_mode(1024,768,mode,HUD_KEYS_LEFT);assert(draw_n>20);for(int i=0;i<draw_n;++i)full_box(&captures[i].d);}
  hud_state h={.screen_w=1024,.screen_h=768};reset();hud_negate(&h);assert(draw_n==1&&captures[0].d.pipeline.src_blend==VK_BLEND_FACTOR_ONE_MINUS_DST_COLOR&&captures[0].d.pipeline.dst_blend==VK_BLEND_FACTOR_ZERO);
  hud_fade(&h,.3f,2);assert(draw_n==2);near(uf(&captures[1].d,19),1);assert(captures[1].d.pipeline.src_blend==VK_BLEND_FACTOR_SRC_ALPHA&&captures[1].d.pipeline.dst_blend==VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA);
  puts("PASS UI batched source/overflow and all standalone controls, all steering modes, negate/fade pipeline independence");
}
static void live_hud_clocks(void){
  memset(SPR,0,sizeof SPR);memset(METER,0,sizeof METER);meter_car=NULL;
  car_state c={0};car_input in={0};hud_state h={.screen_w=1024,.screen_h=768};c.race.state=CAR_RACE_RUN;c.race.sign=1;c.race.play_state=2;c.race.remain=100;c.race.time_left=10;
  c.rival_shown[0]=1;c.race.gap=-50;c.rival_body[0][15]=1;
  mat4 m=mat4_identity();m.m[5]=.01f;hud_rival_view(m.m,m.m);hud_set_story(1);hud_set_ten(-1);
  SPR[SPR_SIGN]=(hud_sprite){601,64,64};SPR[SPR_TILL_GOAL]=(hud_sprite){602,64,64};
  reset();hud_visual_tick(&c);assert(sign_t==1);int sign_before=sign_t;typeof(mark_state) before;memcpy(before,mark_state,sizeof before);unsigned marks=mark_calls;
  hud_draw(&h,&c,&in,60);hud_draw(&h,&c,&in,60);assert(sign_t==sign_before&&!memcmp(before,mark_state,sizeof before)&&mark_calls>marks);
  hud_visual_tick(&c);assert(sign_t==2);
  hud_set_ten(0);c.race.ten_sw_name=1;c.race.ten_rival=2;c.race.ten_beaten=0;hud_visual_tick(&c);assert(banner_frame==1);int frame=banner_frame;hud_draw(&h,&c,&in,60);hud_draw(&h,&c,&in,60);assert(banner_frame==frame);
  puts("PASS whole production hud_draw delegates marks/anm and preserves fixed 60Hz sign/mark/banner clocks across repeated draws");
}
static void expect_swap(int from,int to){
  for(int i=0;i<rival_draw.nswap;++i)if(rival_draw.swap[i].from==from){assert(rival_draw.swap[i].to==to);return;}
  assert(0);
}
static void ghost_card(void){
  car_state c={0};car_input in={0};hud_state h={.screen_w=1920,.screen_h=882};
  float edge=(h.screen_w*768.0f/h.screen_h-1024.0f)*.5f;
  hud_wide(edge,1);
  c.race.state=CAR_RACE_RUN;c.race.play_state=1;
  hud_set_story(1);hud_set_ten(-1);
  hud_vs_box b={.name={1,2,-1,-1,-1},.title=12345,.plate=8123,.hp=740,.grade=2,.power=19,.handling=15};
  hud_set_ghost_card(&b,-1);
  reset();hud_draw(&h,&c,&in,60);assert(!rival_draw.count);
  b.plate=9000;b.name[0]=8;
  hud_set_ghost_gap(12000);
  reset();hud_draw(&h,&c,&in,60);
  assert(!c.rival_shown[0]&&rival_draw.count==1&&rival_draw.anim==TEST_RIVAL&&rival_draw.frame==6);
  near(rival_draw.x,(1024+edge-65*HUD_K)/1.6f);near(rival_draw.y,(TA_Y+60*HUD_K)/1.6f);near(rival_draw.zoom,HUD_K/1.6f);
  expect_swap(T_VS_CAR,8123);expect_swap(T_VS_D0+2,uv(UV_VS_D0+7));expect_swap(T_VS_D0+1,uv(UV_VS_D0+4));
  expect_swap(T_VS_D0,uv(UV_VS_D0));expect_swap(T_VS_GRADE,uv(VS_GRADE_UV[2]));
  expect_swap(T_CPU_DIGIT0,uv(UV_CPU_DIGIT0+1));expect_swap(T_CPU_DIGIT0+1,uv(UV_CPU_DIGIT0+2));expect_swap(T_CPU_DIGIT0+2,-1);
  assert(rival_glyphs==3&&rival_glyph[0]==PLATE_NAME_GLYPH+1&&rival_glyph[1]==PLATE_NAME_GLYPH+2&&rival_glyph[2]==PLATE_TITLE_GLYPH+42);
  c.race.play_state=2;hud_set_ghost_gap(-999.99f);
  reset();hud_draw(&h,&c,&in,60);assert(rival_draw.count==1&&rival_draw.frame==4);
  expect_swap(T_CPU_DIGIT0,uv(UV_CPU_DIGIT0));expect_swap(T_CPU_DIGIT0+1,-1);
  hud_set_ghost_gap(-12599);reset();hud_draw(&h,&c,&in,60);assert(rival_draw.count==1&&rival_draw.frame==3);
  expect_swap(T_CPU_DIGIT0,uv(UV_CPU_DIGIT0+1));expect_swap(T_CPU_DIGIT0+1,uv(UV_CPU_DIGIT0+2));
  b.steps=1;hud_set_ghost_card(&b,-1);hud_set_ghost_gap(3e12f);
  reset();hud_draw(&h,&c,&in,60);assert(rival_draw.count==1&&rival_draw.anim==TEST_RIVAL_PH&&rival_draw.frame==9);
  for(int i=0;i<5;++i)expect_swap(T_CPU_DIGIT0+i,uv(UV_CPU_DIGIT0+9));
  expect_swap(T_VS_D0+2,uv(UV_VS_D0+1));expect_swap(T_VS_D0+1,uv(UV_VS_D0+9));
  expect_swap(T_VS_D0,uv(UV_VS_D0+1));expect_swap(T_VS_D3,uv(UV_VS_D0+5));
  c.race.play_state=7;reset();hud_draw(&h,&c,&in,60);assert(!rival_draw.count);
  c.race.play_state=2;hud_set_ghost_gap(NAN);reset();hud_draw(&h,&c,&in,60);assert(!rival_draw.count);
  hud_set_story(0);hud_set_ghost_gap(1000);reset();hud_draw(&h,&c,&in,60);assert(!rival_draw.count);
  hud_set_vs(&b,1);c.race.vs_on[0]=1;c.race.vs_gap[0]=-12;
  reset();hud_draw(&h,&c,&in,60);assert(rival_draw.count==1&&rival_draw.anim==TEST_RIVAL_PH&&rival_draw.frame==3);
  hud_set_vs(NULL,0);hud_wide(0,1);
  puts("PASS original Ghost top-right card: frozen name/title/car, both tune styles, signed native whole-meter frames, offscreen rival, state/session reset and independent VS");
}
static void ghost_crown_mark(void){
  car_state car={0};car.rival_shown[0]=1;
  mat4 view=mat4_identity();view.m[5]=.01f;
  hud_rival_view(view.m,view.m);
  hud_set_story(1);hud_set_ten(-1);
  hud_vs_box card={.name={1,2,-1,-1,-1}};
  hud_set_ghost_card(&card,7);hud_set_ghost_gap(0);draw_rival_marks(&car,0);
  assert(mark_crown==1667&&!crown_crop);
  missing_console_crown=1667;draw_rival_marks(&car,0);
  assert(mark_crown==-1&&crown_crop==1);
  hud_set_ghost_card(&card,-1);hud_set_ghost_gap(0);draw_rival_marks(&car,0);
  assert(mark_crown==-1&&crown_crop==1);
  hud_set_story(0);missing_console_crown=0;
  puts("PASS crown name marker selects the course console sprite, crops the original menu fallback and clears on ordinary races");
}
int main(void){assert(hud_gl_init()==0);assert(prog&&tex_prog&&NAVI.prog);primitives();navi();preview();meters();warm();ui_and_controls();live_hud_clocks();ghost_card();ghost_crown_mark();puts("native HUD host contracts PASS (CPU packets; not Vulkan pixel/GPU equivalence)");return 0;}
'''

with tempfile.TemporaryDirectory(prefix="round1-hud-host-", dir=PARENT) as directory:
    directory = Path(directory)
    source = directory / "hud_contract.c"
    source.write_text(PREFIX + TESTS)
    env = dict(os.environ, TMPDIR=str(TMP), TMP=str(TMP), TEMP=str(TMP),
               PYTHONDONTWRITEBYTECODE="1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    flags = ["-I", str(ROOT / "src"), "-I", str(ROOT / "test")]
    if PRIVATE is not None:
        flags += ["-I", str(PRIVATE)]
    if sys.platform == "darwin":
        flags += ["-I", "/opt/homebrew/include"]
    command = [os.environ.get("CC", "clang"), "-std=gnu11", "-O1", "-g",
               "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
               "-fno-sanitize-recover=all", *flags, str(source), "-lm", "-lz",
               "-o", str(directory / "hud_contract")]
    subprocess.run(command, check=True, cwd=directory, env=env, timeout=120)
    subprocess.run([str(directory / "hud_contract")], check=True, cwd=directory, env=env, timeout=30)
print("hud.c sha256", hashlib.sha256(HUD.encode()).hexdigest())
print("hud_native_vk.inc sha256", hashlib.sha256(NATIVE.encode()).hexdigest())
