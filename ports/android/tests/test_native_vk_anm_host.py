#!/usr/bin/env python3
"""UBSan production ANM draw contracts with real Vulkan types, no GPU claims.

Extract the actual five draw functions plus CPU transforms/wide-piece helpers.
Native fixtures deliberately declare no GL calls, use_prog, VAO or uniform shadow.
The native init/uniform/sampler writers are extracted from native_vk.inc as well;
only resource lookup, screen extent and recording are stubs. The GLES control
compiles the unmodified non-native branches with recording GL functions (not
renamed setter macros), and both modes must emit byte-identical draw goldens.
Generated files/caches stay in caller-selected TMPDIR, outside the source tree.
"""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("TMPDIR", str(ROOT.parent / "tmp"))).resolve()
if OUT == ROOT or ROOT in OUT.parents:
    raise SystemExit("TMPDIR must be outside the source tree")
ANM = (ROOT / "src/anm.c").read_text()
PACKETS = (ROOT / "src/native_vk.inc").read_text()
NATIVE = (ROOT / "src/anm_native_vk.inc").read_text()


def function(source, anchor):
    a = source.index(anchor)
    opening = source.index("{", a)
    depth = 0
    for j in range(opening, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if not depth:
                return source[a:j + 1]
    raise ValueError(anchor)


schema = ANM[ANM.index("typedef struct {"):ANM.index("#ifdef WMMT_NATIVE_VK")]
wide = ANM[ANM.index("enum { WIDE_NONE"):ANM.index("void anm_draw_xf(")]
# wide_dx is for rect queries, not a draw helper; do not leave unused functions.
wide = wide.replace(function(ANM, "static float wide_dx("), "")
functions = "\n".join(function(ANM, s) for s in (
    "void anm_view(", "int anm_wide_drawn(", "static int same_sprite(",
    "int anm_sprite(", "int anm_warm_sprite(", "static void draw_xy_layout(", "void anm_draw_xy(",
    "void anm_draw_sprite(", "void anm_draw_part_col(", "void anm_draw_part(",
    "void anm_fill(", "unsigned int anm_sprite_texture(", "static int read_all(", "int anm_load(",
))
packet_writers = "\n".join(function(PACKETS, s) for s in (
    "static int native_program_valid(", "int cinder_vk_draw_init(",
    "int cinder_vk_uniform(", "int cinder_vk_texture(", "int cinder_vk_sampler_state(",
))
prefix = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "anm.h"
#include "native_vk.h"
#ifdef WMMT_NATIVE_VK
/* NO declarations for any GL function in this mode. */
typedef unsigned int GLuint;
typedef int GLint;
#else
#include "glstub.h"
#define GL_FUNC_REVERSE_SUBTRACT 0x800b
#endif
'''
resources = r'''
typedef struct { char name[48]; int code, off; } vuni;
/* Resource reflection only: deliberately no GL context or mutable program shadow. */
typedef struct { VkShaderModule vs, fs; int block, n_samp, n_uni; uint32_t inputs; vuni *uni; } vprog;
static vuni fields[] = {{"uView",2,0}, {"uMul",4,16}, {"uAdd",4,32}, {"uTex",7,1}};
static vprog program = {.vs=(VkShaderModule)(uintptr_t)1, .fs=(VkShaderModule)(uintptr_t)2,
  .block=48, .n_samp=1, .n_uni=4, .inputs=3, .uni=fields};
static vprog *prog_get(uint32_t p) { return p == A.prog && p ? &program : NULL; }
static int screen_w=1920, screen_h=1080, extent_calls;
void cinder_vk_screen_extent(int *w, int *h) { *w=screen_w; *h=screen_h; ++extent_calls; }
static unsigned uploads, touches, extra_loads, card_loads;
static void load_extra(const char *path) { assert(!strcmp(path,"."));++extra_loads; }
static void load_card_pages(const char *path) { assert(!strcmp(path,"."));++card_loads; }
static void load_ghost_ui(const char *path) { assert(!strcmp(path,".")); }
#ifdef WMMT_NATIVE_VK
uint32_t cinder_vk_program_create(const char *vs,const char *fs,const char **attribs,int n) {
#else
GLuint gl_compile_program(const char *vs,const char *fs,const char **attribs,int n) {
#endif
  assert(n==2 && !strcmp(attribs[0],"aPos") && !strcmp(attribs[1],"aUV"));
  assert(strstr(vs,"1.0 - aPos.y / 384.0") && strstr(vs,"aPos.x * uView.x + uView.y"));
  assert(strstr(fs,"clamp(texture2D(uTex, vUV) * uMul + uAdd, 0.0, 1.0)"));return 37;
}
static GLuint texture(int i) {
  assert(i>=0 && (uint32_t)i<A.nsprites); ++touches; A.used[i]=A.clock;
  if (!A.tex[i]) { A.tex[i]=100u+(unsigned)i; ++uploads; }
  return A.tex[i];
}
static struct Record {cinder_vk_draw d; float pos[8], uv[8];} records[128];
static unsigned nrecords, frame_records, warm_records;
static int frame_active=1, expected_warm, emit=1;
static void record(const cinder_vk_draw *d) {
  assert(nrecords<128 && d->count==4 && !d->indexed && !d->first);
  struct Record *r=&records[nrecords++]; r->d=*d;
  for (int a=0;a<2;++a) {
    const cinder_vk_attribute *v=&d->attributes[a];
    assert(v->format==VK_FORMAT_R32G32_SFLOAT && !v->buffer && v->data && v->stride==16);
    assert(v->offset==(size_t)a*8 && v->bytes==64);
    assert(v->offset+(d->count-1)*v->stride+8<=v->bytes);
    float *out=a?r->uv:r->pos;
    for (unsigned i=0;i<4;++i) memcpy(out+i*2,(const char*)v->data+v->offset+i*v->stride,8);
    /* Do not retain stack pointers as our evidence of the consumed values. */
    r->d.attributes[a].data=NULL;
  }
  if (emit && !expected_warm) {
    printf("DRAW %u %u %d %d %d",d->program,d->textures[0],(int)d->pipeline.src_blend,
           (int)d->pipeline.dst_blend,(int)d->pipeline.blend_op);
    for (int i=0;i<8;++i) printf(" %a",(double)r->pos[i]);
    for (int i=0;i<8;++i) printf(" %a",(double)r->uv[i]);
    for (int i=0;i<12;++i) {float v;memcpy(&v,d->uniforms+i*4,4);printf(" %a",(double)v);}
    putchar('\n');
  }
}
int cinder_vk_submit(const cinder_vk_draw *d) {
  assert(d->target==0 && d->program==A.prog && d->pipeline.color_mask==15);
  assert(d->pipeline.topology==VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP && d->pipeline.blend);
  assert(!d->pipeline.depth_test && !d->pipeline.depth_write && !d->pipeline.stencil && !d->pipeline.cull);
  const int box[4]={0,0,screen_w,screen_h};
  assert(!memcmp(d->viewport,box,sizeof box) && !memcmp(d->scissor,box,sizeof box));
  for (int i=2;i<CINDER_VK_ATTRIBUTES;++i) {
    const cinder_vk_attribute *a=&d->attributes[i];
    assert(a->format==VK_FORMAT_UNDEFINED && !a->buffer && !a->data && !a->bytes);
    assert(a->value[0]==0 && a->value[1]==0 && a->value[2]==0 && a->value[3]==1);
  }
  const cinder_vk_sampler *s=&d->samplers[0];
  assert(s->use_state && !s->mipmaps && s->min_filter==VK_FILTER_LINEAR && s->mag_filter==VK_FILTER_LINEAR);
  assert(s->mipmap_mode==VK_SAMPLER_MIPMAP_MODE_NEAREST && s->address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE &&
         s->address_v==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE && s->anisotropy==1);
  assert(d->warm_only==!!expected_warm);
  assert(d->warm_only || frame_active);
  record(d);
  if(d->warm_only) ++warm_records; else ++frame_records;
  return 1;
}
'''
gles = r'''
#ifndef WMMT_NATIVE_VK
/* Only the GLES control owns mutable GL state. No setter macro substitution. */
static cinder_vk_draw gl_packet;
GLint glGetUniformLocation(GLuint p,const GLchar *n) {
  assert(p==37);return !strcmp(n,"uView")?1:!strcmp(n,"uMul")?2:!strcmp(n,"uAdd")?3:4;
}
void glUseProgram(GLuint p) { assert(cinder_vk_draw_init(&gl_packet,p,0,screen_w,screen_h)); }
void glUniform2f(GLint u,GLfloat a,GLfloat b) {
  assert(u==A.u_view); float v[2]={a,b}; assert(cinder_vk_uniform(&gl_packet,"uView",v,sizeof v));
}
void glUniform4f(GLint u,GLfloat a,GLfloat b,GLfloat c,GLfloat d) {
  assert(u==A.u_mul || u==A.u_add); float v[4]={a,b,c,d};
  assert(cinder_vk_uniform(&gl_packet,u==A.u_mul?"uMul":"uAdd",v,sizeof v));
}
void glUniform1i(GLint u,GLint v) { assert(u==A.u_tex && v==0); }
void glActiveTexture(GLenum u) { assert(u==GL_TEXTURE0); }
void glDisable(GLenum c) { assert(c==GL_DEPTH_TEST || c==GL_CULL_FACE); }
void glEnable(GLenum c) { assert(c==GL_BLEND); gl_packet.pipeline.blend=1; }
void glBlendFunc(GLenum s,GLenum d) {
  assert(s==GL_SRC_ALPHA && (d==GL_ONE || d==GL_ONE_MINUS_SRC_ALPHA));
  gl_packet.pipeline.src_blend=VK_BLEND_FACTOR_SRC_ALPHA;
  gl_packet.pipeline.dst_blend=d==GL_ONE?VK_BLEND_FACTOR_ONE:VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
}
void glBlendEquation(GLenum e) {
  assert(e==GL_FUNC_ADD || e==GL_FUNC_REVERSE_SUBTRACT);
  gl_packet.pipeline.blend_op=e==GL_FUNC_ADD?VK_BLEND_OP_ADD:VK_BLEND_OP_REVERSE_SUBTRACT;
}
void glBindBuffer(GLenum t,GLuint b) { assert(t==GL_ARRAY_BUFFER && !b); }
void glEnableVertexAttribArray(GLuint a) { assert(a<2); }
void glDisableVertexAttribArray(GLuint a) { assert(a==2); }
void glBindTexture(GLenum t,GLuint tex) { assert(t==GL_TEXTURE_2D); assert(cinder_vk_texture(&gl_packet,"uTex",tex)); }
void glVertexAttribPointer(GLuint a,GLint n,GLenum type,GLboolean norm,GLsizei stride,const void *v) {
  assert(a<2 && n==2 && type==GL_FLOAT && norm==GL_FALSE && stride==16);
  gl_packet.attributes[a]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=16,
    .offset=a*8,.data=(const char*)v-a*8,.bytes=64};
}
void glDrawArrays(GLenum mode,GLint first,GLsizei n) {
  assert(mode==GL_TRIANGLE_STRIP && !first && n==4); gl_packet.count=4;
  gl_packet.pipeline.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP;
  record(&gl_packet); ++frame_records;
}
#endif
'''
tests = r'''
static GLuint textures[8]; static uint32_t used[8]; static long offsets[8]; static uint32_t zsizes[8];
static float sizes[8][2]; static int ids[8]; static uint16_t cols[8][2];
static anm_rec recs[8]; static uint32_t frames[2][2]; static anm_anim anim;
static void reset(void) {
  memset(&A,0,sizeof A); memset(textures,0,sizeof textures); memset(used,0,sizeof used);
  memset(recs,0,sizeof recs); memset(frames,0,sizeof frames); memset(&anim,0,sizeof anim);
  memset(records,0,sizeof records); nrecords=frame_records=warm_records=uploads=touches=0;
  extent_calls=0; frame_active=1; expected_warm=0; emit=1; screen_w=1920; screen_h=1080;
  program.block=48; fields[0].code=2; fields[3].code=7;
  for (int i=0;i<8;++i) { textures[i]=100u+(unsigned)i; sizes[i][0]=80; sizes[i][1]=40;
    ids[i]=i+10; cols[i][0]=0; cols[i][1]=80;
    recs[i]=(anm_rec){.sprite=(uint16_t)i,.a=1,.d=1,.mul={256,256,256,256}};
  }
  ids[7]=841;
  A.tex=textures;A.used=used;A.size=sizes;A.ids=ids;A.cols=cols;A.offset=offsets;A.zsize=zsizes;
  A.nsprites=8;A.nanims=1;A.anims=&anim;A.prog=37;A.clock=11;
  A.u_view=1;A.u_mul=2;A.u_add=3;A.u_tex=4;
  anim.nframes=2;anim.nrecs=8;anim.frames=frames;anim.recs=recs;frames[0][1]=1;frames[1][0]=1;frames[1][1]=1;
}
static void near(float a,float b) { assert(fabsf(a-b)<.001f); }
static void vector(const float *a,const float *b,int n) { for(int i=0;i<n;++i)near(a[i],b[i]); }
static float uniform(unsigned record_,unsigned index) {float f;memcpy(&f,records[record_].d.uniforms+index*4,4);return f;}
static void color(unsigned index,const float mul[4],const float add[4]) {
  for (unsigned i=0;i<4;++i) {near(uniform(index,4+i),mul[i]);near(uniform(index,8+i),add[i]);}
}
static void primitives(void) {
  reset();anm_view(160);
  anm_draw_sprite(2,10,20,.75f);assert(nrecords==1 && records[0].d.textures[0]==102);
  vector(records[0].pos,(float[8]){16,32,144,32,16,96,144,96},8);
  vector(records[0].uv,(float[8]){0,0,1,0,0,1,1,1},8);
  color(0,(float[4]){1,1,1,.75f},(float[4]){0});
  near(uniform(0,0),1.0f/672);near(uniform(0,1),160.0f/672-1);
  assert(records[0].d.pipeline.src_blend==VK_BLEND_FACTOR_SRC_ALPHA && records[0].d.pipeline.dst_blend==VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA);
  float src[4]={20,10,60,30},dst[4]={7,9,27,49},mul[4]={.2f,.4f,.6f,-.25f},add[4]={-.1f,.3f,.7f,.5f};
  anm_draw_part_col(2,src,dst,mul,add);assert(nrecords==2);
  vector(records[1].pos,(float[8]){11.2f,14.4f,43.2f,14.4f,11.2f,78.4f,43.2f,78.4f},8);
  vector(records[1].uv,(float[8]){.25f,.25f,.75f,.25f,.25f,.75f,.75f,.75f},8);color(1,mul,add);
  /* Sources and caller colors can die/change immediately after submission. */
  memset(src,0,sizeof src);memset(dst,0,sizeof dst);memset(mul,0,sizeof mul);memset(add,0,sizeof add);
  near(records[1].pos[0],11.2f);near(records[1].uv[0],.25f);near(uniform(1,4),.2f);near(uniform(1,11),.5f);
  src[2]=80;src[3]=40;dst[2]=80;dst[3]=40;anm_draw_part(2,src,dst,.125f);
  assert(nrecords==3);color(2,(float[4]){1,1,1,.125f},(float[4]){0});
  anm_fill(.2f,.3f,.4f,.6f);assert(nrecords==4 && records[3].d.textures[0]==107);
  vector(records[3].pos,(float[8]){-160,0,1184,0,-160,768,1184,768},8);
  vector(records[3].uv,(float[8]){.5f,.5f,.5f,.5f,.5f,.5f,.5f,.5f},8);
  color(3,(float[4]){.2f,.3f,.4f,.6f},(float[4]){0});
  anm_draw_sprite(-1,0,0,1);anm_draw_sprite(8,0,0,1);anm_draw_sprite(0,0,0,0);
  anm_draw_part_col(-1,src,dst,mul,add);anm_draw_part_col(0,src,dst,mul,add);anm_fill(1,1,1,0);
  assert(nrecords==4);
#ifdef WMMT_NATIVE_VK
  assert(extent_calls==4 && frame_records==4 && !warm_records);
#endif
  puts("PASS production sprite/part_col/part/fill geometry, colors, midpoint UVs, bounds and defaults");
}
static void animation(void) {
  reset();frames[0][1]=6;
  recs[0]=(anm_rec){.sprite=0,.a=2,.b=.25f,.c=-.5f,.d=1.5f,.x=30,.y=40,
    .mul={128,256,-64,192},.add={51,-102,153,64}};
  recs[1]=recs[0];recs[1].sprite=1;recs[1].blend=1;
  recs[2]=recs[0];recs[2].sprite=2;recs[2].blend=2;
  recs[3]=recs[0];recs[3].sprite=3;recs[3].mul[3]=0;recs[3].add[3]=0; /* skip */
  recs[4]=recs[0];recs[4].sprite=4;recs[4].mul[3]=0; /* positive added alpha survives */
  recs[5]=recs[0];recs[5].sprite=8; /* invalid */
  ids[6]=ids[0]; sizes[5][0]=20;sizes[5][1]=10;
  anm_swap swaps[3]={{6,5},{5,7},{1,-1}}; /* same-id, once-only, hide */
  anm_draw_xy(0,-4,.5f,7,-9,1.25f,.75f,swaps,3);
  assert(nrecords==3 && touches==3);assert(records[0].d.textures[0]==105 && records[1].d.textures[0]==102 && records[2].d.textures[0]==104);
  /* Explicit golden for swapped 20x10 geometry, including skew and nonuniform scale. */
  vector(records[0].pos,(float[8]){71.2f,33.6f,151.2f,39.6f,61.2f,51.6f,141.2f,57.6f},8);
  color(0,(float[4]){.5f,1,-.25f,.375f},(float[4]){.2f,-.4f,.6f,64.0f/255*.5f});
  assert(records[0].d.pipeline.dst_blend==VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA && records[0].d.pipeline.blend_op==VK_BLEND_OP_ADD);
  assert(records[1].d.pipeline.dst_blend==VK_BLEND_FACTOR_ONE && records[1].d.pipeline.blend_op==VK_BLEND_OP_REVERSE_SUBTRACT);
  near(uniform(2,7),0);near(uniform(2,11),64.0f/255*.5f);
  /* Alpha -> additive -> reverse-subtract -> alpha transitions preserve record order. */
  nrecords=0;frames[0][1]=4;
  for(int i=0;i<4;++i)recs[i]=(anm_rec){.sprite=(uint16_t)i,.blend=(uint16_t)(i==3?0:i),.a=1,.d=1,.mul={256,256,256,256}};
  anm_draw_xy(0,0,1,0,0,1,1,NULL,0);assert(nrecords==4);
  for(int i=0;i<4;++i){assert(records[i].d.textures[0]==100u+(unsigned)i);
    assert(records[i].d.pipeline.dst_blend==(i==1||i==2?VK_BLEND_FACTOR_ONE:VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA));
    assert(records[i].d.pipeline.blend_op==(i==2?VK_BLEND_OP_REVERSE_SUBTRACT:VK_BLEND_OP_ADD));}
  nrecords=0;anm_draw_xy(0,100,1,0,0,1,1,NULL,0);assert(nrecords==1 && records[0].d.textures[0]==101);
  nrecords=0;anm_draw_xy(-1,0,1,0,0,1,1,NULL,0);anm_draw_xy(1,0,1,0,0,1,1,NULL,0);assert(!nrecords);
  puts("PASS production animation CPU matrix/color, same-id swap once/hide, frame clamps, alpha/add/subtract ordering");
}
static void wide_goldens(void) {
  reset();anm_view(160);ids[0]=1574;sizes[0][0]=640;recs[0].mul[3]=128;recs[0].add[3]=51;
  anm_draw_xy(0,0,.5f,0,0,1,1,NULL,0);assert(nrecords==3 && anm_wide_drawn());
  vector(records[0].pos,(float[8]){0,0,1024,0,0,64,1024,64},8);
  near(records[1].pos[0],-160);near(records[1].pos[2],6.4f);near(records[2].pos[0],1024);near(records[2].pos[2],1184);
  near(records[1].uv[0],8.0f/640);near(records[1].uv[2],24.0f/640);
  color(2,(float[4]){1,1,1,.25f},(float[4]){0,0,0,.1f});
  reset();anm_view(160);ids[0]=1748;sizes[0][0]=640;
  anm_draw_xy(0,0,1,0,0,1,1,NULL,0);assert(nrecords==3 && anm_wide_drawn());
  near(records[0].pos[0],-160);near(records[0].pos[2],352);near(records[1].pos[0],352);near(records[1].pos[2],672);
  near(records[2].pos[0],672);near(records[2].pos[2],1184);near(records[1].uv[0],220.0f/640);near(records[1].uv[2],420.0f/640);
  reset();anm_view(160);ids[0]=1908;
  anm_draw_xy(0,0,1,0,0,1,1,NULL,0);assert(nrecords==1);near(records[0].pos[0],160);near(records[0].pos[2],288);
  reset();anm_view(160);sizes[0][0]=640;cols[0][1]=640;recs[0].mul[3]=128;recs[0].add[3]=51;
  anm_draw_xy(0,0,.5f,0,0,1,1,NULL,0);assert(nrecords==49); /* middle, then left/right per fade step */
  near(records[1].pos[0],-80.0f/24);near(records[1].pos[2],0);near(records[2].pos[0],1024);
  for(int i=0;i<24;++i){float f=1-((float)i+.5f)/24;
    for(int side=0;side<2;++side){unsigned p=1u+(unsigned)i*2+(unsigned)side;
      near(uniform(p,7),.25f*f);near(uniform(p,11),.1f*f);near(uniform(p,4),1);
      near(records[p].uv[0],side?636.5f/640:3.5f/640);near(records[p].uv[2],records[p].uv[0]);}}
  /* Non-plain/skewed/swapped pictures must not acquire the full-bleed fade pieces. */
  nrecords=0;anm_draw_xy(0,0,1,1,0,1,1,NULL,0);assert(nrecords==1);
  nrecords=0;recs[0].b=.1f;anm_draw_xy(0,0,1,0,0,1,1,NULL,0);assert(nrecords==1);
  nrecords=0;recs[0].b=0;anm_swap sw={0,1};anm_draw_xy(0,0,1,0,0,1,1,&sw,1);assert(nrecords==1);
  reset();anm_view(160);recs[0].a=8;sizes[0][0]=80;
  anm_draw_xy(0,0,1,0,0,1,1,NULL,0);assert(nrecords==1 && anm_wide_drawn());
  near(records[0].pos[0],-160);near(records[0].pos[2],1184);
  puts("PASS production wide title/bottom/right/full-bleed49/fade/stretch and skew/swap/nonplain gates");
}
static void warm(void) {
  reset();A.tex[2]=0;frame_active=0;expected_warm=1;
  assert(!anm_warm_sprite(-1,1) && !anm_warm_sprite(8,1) && !anm_warm_sprite(2,0) && !nrecords && !uploads);
  assert(anm_warm_sprite(2,1)==1 && uploads==1 && nrecords==1 && A.used[2]==A.clock);
  vector(records[0].pos,(float[8]){0,0,1,0,0,1,1,1},8);
  color(0,(float[4]){1,1,1,0},(float[4]){0});
#ifdef WMMT_NATIVE_VK
  assert(records[0].d.warm_only && warm_records==1 && !frame_records && extent_calls==1);
#else
  assert(!records[0].d.warm_only && frame_records==1); /* GLES control intentionally draws */
#endif
  ++A.clock;assert(!anm_warm_sprite(2,1) && !anm_warm_sprite(2,0) && uploads==1 && nrecords==1 && A.used[2]==A.clock);
  assert(anm_sprite_texture(2)==102);assert(!anm_sprite_texture(-1) && !anm_sprite_texture(8));
  puts("PASS actual warm site uploads once/touches cache, explicit native warm_only without active frame");
}
#ifdef WMMT_NATIVE_VK
static void failures_and_copy(void) {
  reset();emit=0;screen_w=1080;screen_h=1920;
  float v[16]={1,2,0,0,3,4,1,0,5,6,0,1,7,8,1,1},mul[4]={.25f,.5f,.75f,1},add[4]={0};
  assert(anm_native_quad(v,100,mul,add,0,VK_FALSE));assert(nrecords==1 && frame_records==1);
  memset(v,0,sizeof v);memset(mul,0,sizeof mul);assert(records[0].pos[0]==1 && records[0].pos[7]==8);near(uniform(0,4),.25f);
  screen_w=0;assert(!anm_native_quad(v,100,mul,add,0,VK_FALSE) && nrecords==1);screen_w=1080;
  fields[0].code=4;assert(!anm_native_quad(v,100,mul,add,0,VK_FALSE) && nrecords==1);fields[0].code=2;
  fields[3].code=4;assert(!anm_native_quad(v,100,mul,add,0,VK_FALSE) && nrecords==1);fields[3].code=7;
  program.block=4097;anm_draw_sprite(0,0,0,1);assert(nrecords==1);
  puts("PASS real native packet init/writers, rotated extent, bounded immediate CPU copies/constants and fail-closed assembly");
}
#endif
static void load_contract(void) {
  reset();FILE *f=fopen("menu.bin","wb");assert(f);
  uint32_t n=1,id=77,z=0;uint16_t wh[2]={2,2};unsigned char pixels[16]={0};
  assert(fwrite("WMN3",1,4,f)==4 && fwrite(&n,4,1,f)==1 && fwrite(&id,4,1,f)==1 &&
    fwrite(wh,4,1,f)==1 && fwrite(&z,4,1,f)==1 && fwrite(pixels,16,1,f)==1 && fwrite(&z,4,1,f)==1);
  fclose(f);extra_loads=card_loads=0;assert(anm_load(".")==0 && extra_loads==1 && card_loads==1);
  assert(A.nsprites==1 && A.ids[0]==77 && A.size[0][0]==2 && A.prog==37);
  fclose(A.file);free(A.tex);free(A.offset);free(A.zsize);free(A.used);free(A.size);free(A.ids);free(A.cols);free(A.anims);
  puts("PASS actual load/shader attribute/color constants; native compile has no GL query declarations");
}
int main(void) {
  primitives();animation();wide_goldens();warm();load_contract();
#ifdef WMMT_NATIVE_VK
  failures_and_copy();
#endif
  puts("ANM production contracts PASS (CPU only; no driver/pixel proof)");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="native-vk-anm-", dir=OUT) as directory:
    directory = Path(directory)
    env = dict(os.environ, TMPDIR=str(directory), TMP=str(directory), TEMP=str(directory),
               HOME=str(directory), XDG_CACHE_HOME=str(directory), PYTHONDONTWRITEBYTECODE="1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    flags = ["-I", str(ROOT / "src"), "-I", str(ROOT / "test")]
    if sys.platform == "darwin":
        flags += ["-I", "/opt/homebrew/include"]
    source = (prefix + schema + resources + packet_writers + gles + "\n#ifdef WMMT_NATIVE_VK\n"
              + NATIVE + "\n#else\n" + function(ANM, "static void use_prog(") + "\n#endif\n"
              + wide + functions + tests)
    fixture = directory / "anm.c"
    fixture.write_text(source)
    goldens = []
    for mode in ("native", "gles-control"):
        executable = directory / mode
        command = [os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                   "-fsanitize=undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", *flags]
        if mode == "native":
            command += ["-DWMMT_NATIVE_VK=1"]
        command += [str(fixture), "-lm", "-o", str(executable)]
        subprocess.run(command, env=env, cwd=directory, check=True, timeout=120)
        result = subprocess.run([str(executable)], env=env, cwd=directory,
                                capture_output=True, text=True, timeout=30)
        print(mode, result.stdout, result.stderr, sep="\n")
        result.check_returncode()
        goldens.append([line for line in result.stdout.splitlines() if line.startswith("DRAW ")])
    assert goldens[0] and goldens[0] == goldens[1], "native/GLES CPU draw goldens differ"
    print("PASS native/GLES-control byte-identical draw goldens:", len(goldens[0]))
print("anm.c sha256", hashlib.sha256(ANM.encode()).hexdigest())
print("anm_native_vk.inc sha256", hashlib.sha256(NATIVE.encode()).hexdigest())
print("native_vk.inc sha256", hashlib.sha256(PACKETS.encode()).hexdigest())
