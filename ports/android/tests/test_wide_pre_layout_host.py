#!/usr/bin/env python3
"""CPU-only PRE anchoring regression; real production ANM/GLES/native packets.

No assets, device, GPU, generated private tables or workspace-specific paths.
Reuse the existing native ANM fixture's definitions without executing its driver;
its legacy main/actions/assertions/goldens remain intact and run first. Menu
composition functions and anchor tables are extracted verbatim. Only resource
lookup inputs (STORYPRE/TENDB/BGM/course identity) are explicit synthetic data.
All generated files/logs go to TMPDIR outside the source tree. Optionally set
WIDE_PRE_RESULT to an external JSON result path (never inside the source tree).
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("TMPDIR", str(ROOT.parent / "tmp"))).resolve()
if OUT == ROOT or ROOT in OUT.parents:
    raise SystemExit("TMPDIR must be outside the source tree")
OUT.mkdir(parents=True, exist_ok=True)
legacy = ROOT / "tests/test_native_vk_anm_host.py"
ns = {"__file__": str(legacy), "__name__": "wide_pre_fixture_definitions"}
exec(compile(legacy.read_text().split("\nwith tempfile.TemporaryDirectory(", 1)[0],
             str(legacy), "exec"), ns)
ANM, function = ns["ANM"], ns["function"]
MENU = (ROOT / "src/menu.c").read_text()

# These are synthetic test facts, not extracted or redistributed resource tables.
episodes = (1, 2, 99, 100, 200)
story_rows = []
for i, episode in enumerate(episodes):
    for cars in (0, 1, 3):
        story_rows.append("{%d,%d,%d,{%d,%d},{%s}}" % (
            episode, 9000 + i, 9100 + i, 9200 + i, 9300 + i,
            ",".join(str(9400 + k) if k < cars else "0" for k in range(3))))
ten_rows = []
for course in range(3):
    ten_rows.append("{" + ",".join("{%d,%d,%d,%d}" % (
        9600 + course * 10 + level, 9700 + course * 10 + level,
        (4751, 3301)[level % 2], 9800 + course * 10 + level)
        for level in range(10)) + "}")
menu_inputs = r'''
#include "menu.h"
#define BGM_LINES 22
#define BGM_TEXT 101000
#define T_BGM_FONT 0xbaf
#define LOADING_PRE_DX -409.0f
static struct { int pre_st, pre_ta, pre_or, pre_sound, pre_sound_st, loading, pre_bg; } ID = {0,1,2,3,4,5,6};
typedef struct { int episode, picture, title, bg[2], cars[3]; } storypre_select;
#define STORYPRE_N 15
static const storypre_select STORYPRE[STORYPRE_N] = {STORY_ROWS};
static const int STORYPRE_DIGIT[10] = {9500,9501,9502,9503,9504,9505,9506,9507,9508,9509};
static const int TENDB_PRE[3][10][4] = {TEN_ROWS};
static const int TENDB_PRE_LV[10] = {9900,9901,9902,9903,9904,9905,9906,9907,9908,9909};
static const struct { int lines, logo; } CARD_BGM_SETS[3] = {{22,0x1643},{25,0x1641},{14,0x19ce}};
/* Resource selection boundaries only; the PRE composition itself is production. */
static int car_course_id(int course) { assert(course>=0 && course<15); return course; }
static int card_bgm_set(const menu_state *m) { return m->vs.state != MENU_VS_OFF ? 0 : m->bgm_source; }
static float WIDE_ZOOM = 1.0f;
static int photo_bg;
'''.replace("STORY_ROWS", ",\n".join(story_rows)).replace("TEN_ROWS", ",\n".join(ten_rows))
menu_functions = (function(MENU, "void menu_wide(") + "\n" +
                  function(MENU, "static void draw_photo_bg(") + "\n" +
                  function(MENU, "static int card_bgm_play_line(") + "\n" +
                  MENU[MENU.index("static const int PRE_BG[2][15]"):
                       MENU.index("/* ---- the story's level and rival select")])

new_tests = r'''
/* The two backends execute this exact harness; all drawing is real extracted code. */
#define FIX_SPRITES 512
#define FIX_ANIMS 7
#define FIX_FRAMES 100
#define FIX_RECS 1600
static GLuint fixture_tex[FIX_SPRITES];
static uint32_t fixture_used[FIX_SPRITES];
static long fixture_offsets[FIX_SPRITES];
static uint32_t fixture_zsizes[FIX_SPRITES];
static float fixture_sizes[FIX_SPRITES][2];
static int fixture_ids[FIX_SPRITES];
static uint16_t fixture_cols[FIX_SPRITES][2];
static anm_anim fixture_anims[FIX_ANIMS];
static uint32_t fixture_frames[FIX_ANIMS][FIX_FRAMES][2];
static anm_rec fixture_recs[FIX_ANIMS][FIX_RECS];
static unsigned cases, packet_checks, vertex_checks, api_cases, menu_cases, loading_cases, density_cases;
static struct Record reference[128], saved[128];
static unsigned nreference;
static int expect_id[128], expect_side[128];
static unsigned nexpect;
static uint64_t trace = UINT64_C(1469598103934665603);
static void hash_bytes(const void *data,size_t n) {
  const unsigned char *p=data;
  for(size_t i=0;i<n;++i) { trace^=p[i]; trace*=UINT64_C(1099511628211); }
}
static void hash_records(void) {
  hash_bytes(&nrecords,sizeof nrecords);
  for(unsigned i=0;i<nrecords;++i) {
    const struct Record *r=&records[i];
    hash_bytes(r->pos,sizeof r->pos); hash_bytes(r->uv,sizeof r->uv);
    hash_bytes(r->d.uniforms,48); hash_bytes(r->d.textures,sizeof r->d.textures);
    hash_bytes(&r->d.pipeline,sizeof r->d.pipeline);
    hash_bytes(r->d.viewport,sizeof r->d.viewport); hash_bytes(r->d.scissor,sizeof r->d.scissor);
  }
}
static void take_reference(void) {
  nreference=nrecords; memcpy(reference,records,nrecords*sizeof records[0]); nrecords=0;
}
static void packet_equal(const struct Record *a,const struct Record *b,int normalize_view) {
  cinder_vk_draw da=a->d,db=b->d;
  if(normalize_view) {
    memset(da.uniforms,0,8); memset(db.uniforms,0,8);
    memset(da.viewport,0,sizeof da.viewport); memset(db.viewport,0,sizeof db.viewport);
    memset(da.scissor,0,sizeof da.scissor); memset(db.scissor,0,sizeof db.scissor);
  }
  /* Compare every semantic packet field, never indeterminate C struct padding. */
#define SAME(field) assert(da.field==db.field)
  SAME(program);SAME(target);SAME(stencil_reference);SAME(uniform_bytes);SAME(count);SAME(first);
  SAME(indexed);SAME(warm_only);SAME(index_type);SAME(index_buffer);SAME(index_offset);SAME(indices);SAME(index_bytes);
#undef SAME
  assert(!memcmp(da.viewport,db.viewport,sizeof da.viewport));assert(!memcmp(da.scissor,db.scissor,sizeof da.scissor));
  assert(!memcmp(&da.pipeline,&db.pipeline,sizeof da.pipeline));
  assert(!memcmp(da.textures,db.textures,sizeof da.textures));assert(!memcmp(da.samplers,db.samplers,sizeof da.samplers));
  assert(!memcmp(da.uniforms,db.uniforms,sizeof da.uniforms));
  for(unsigned k=0;k<CINDER_VK_ATTRIBUTES;++k) {
    const cinder_vk_attribute *x=&da.attributes[k],*y=&db.attributes[k];
    assert(x->format==y->format && x->stride==y->stride && x->buffer==y->buffer && x->offset==y->offset &&
      x->data==y->data && x->bytes==y->bytes && !memcmp(x->value,y->value,sizeof x->value));
  }
  assert(!memcmp(a->uv,b->uv,sizeof a->uv)); ++packet_checks;
}
static void translated(const struct Record *a,const struct Record *b,float x,float y) {
  packet_equal(a,b,1);
  for(int k=0;k<4;++k) {
    near(b->pos[2*k],a->pos[2*k]+x); near(b->pos[2*k+1],a->pos[2*k+1]+y);
    ++vertex_checks;
  }
  /* The entire within-quad affine, including skew/rotation, is unchanged. */
  for(int k=1;k<4;++k) {
    near(b->pos[2*k]-b->pos[0],a->pos[2*k]-a->pos[0]);
    near(b->pos[2*k+1]-b->pos[1],a->pos[2*k+1]-a->pos[1]);
  }
}
static void exact_reference(void) {
  assert(nrecords==nreference);
  for(unsigned i=0;i<nrecords;++i) { packet_equal(&reference[i],&records[i],0);
    assert(!memcmp(reference[i].pos,records[i].pos,sizeof records[i].pos)); }
}
static int put_sprite(int id,float w,float h,int duplicate) {
  int old=anm_sprite(id); if(!duplicate && old>=0) return old;
  assert(A.nsprites<FIX_SPRITES); int i=(int)A.nsprites++;
  fixture_ids[i]=id; fixture_sizes[i][0]=w;fixture_sizes[i][1]=h;
  fixture_cols[i][0]=0;fixture_cols[i][1]=(uint16_t)w;
  fixture_tex[i]=100u+(unsigned)i;return i;
}
static anm_rec make_rec(int sprite,int k,int frame) {
  const float matrix[5][4]={{1,0,0,1},{.75f,.25f,-.125f,1.25f},{0,1,-1,0},{-1,0,0,.5f},{1.6f,0,0,.8f}};
  const float *v=matrix[k%5];
  return (anm_rec){.sprite=(uint16_t)sprite,.blend=(uint16_t)(k%3),
    .a=v[0],.b=v[1],.c=v[2],.d=v[3],.x=23.0f+7*k+frame*.75f,.y=11.0f+3*k-frame*.25f,
    .mul={128,256,192,192},.add={32,-16,64,0}};
}
static void make_anim(int a,const int *own_ids,int n,int nframes) {
  fixture_anims[a].nframes=(uint32_t)nframes; fixture_anims[a].nrecs=(uint32_t)(n*nframes);
  fixture_anims[a].frames=fixture_frames[a]; fixture_anims[a].recs=fixture_recs[a];
  for(int f=0;f<nframes;++f) {
    fixture_frames[a][f][0]=(uint32_t)(f*n); fixture_frames[a][f][1]=(uint32_t)n;
    for(int k=0;k<n;++k) {
      int sprite=put_sprite(own_ids[k],32.0f+8*(k%7),16.0f+4*(k%5),k==n-1 && a!=ID.pre_bg && a!=ID.loading);
      fixture_recs[a][f*n+k]=make_rec(sprite,k,f);
    }
  }
}
static void fixture_reset(void) {
  reset(); emit=0;
  memset(fixture_tex,0,sizeof fixture_tex);memset(fixture_used,0,sizeof fixture_used);
  memset(fixture_anims,0,sizeof fixture_anims);memset(fixture_frames,0,sizeof fixture_frames);
  memset(fixture_recs,0,sizeof fixture_recs);
  A.tex=fixture_tex;A.used=fixture_used;A.offset=fixture_offsets;A.zsize=fixture_zsizes;
  A.size=fixture_sizes;A.ids=fixture_ids;A.cols=fixture_cols;A.anims=fixture_anims;
  A.nsprites=0;A.nanims=FIX_ANIMS;
  const int st[]={0x1295,0x1e10,0x1d1d,0x1e0d,0xdb0,0x1d1e,0x1e0e,0x1d1f,0x1e0f,
    0x1d20,0x1d21,3947,45001,0x1295};
  const int ta[]={2909,0x1b9a,0x15ed,45001,2909};
  const int ten[]={0xb5c,0x1b9a,0x1870,0x15ed,0x61b,0x186f,45001,0x186f};
  const int snd[]={0x75d,0x1a96,0xbaf,0x75c,45001,0xbaf};
  const int load[]={0xfdc,45001}; const int bg[]={0xb2f};
  make_anim(ID.pre_st,st,14,1);make_anim(ID.pre_ta,ta,5,1);make_anim(ID.pre_or,ten,8,1);
  make_anim(ID.pre_sound,snd,6,30);make_anim(ID.pre_sound_st,snd,6,30);
  make_anim(ID.loading,load,2,16);make_anim(ID.pre_bg,bg,1,1);
  /* One whole song-panel picture is deliberately eligible for old fade extrusion.
   * A nonzero semantic move MUST supersede that, not split/stretch it again. */
  for(int a=ID.pre_sound;a<=ID.pre_sound_st;++a) for(int f=0;f<30;++f) {
    anm_rec *r=&fixture_recs[a][f*6];r->a=r->d=1;r->b=r->c=0;r->x=0;
  }
  int panel=anm_sprite(0x75d);fixture_sizes[panel][0]=640;fixture_cols[panel][1]=640;
  for(int s=0;s<STORYPRE_N;++s) {
    const storypre_select *p=&STORYPRE[s];
    put_sprite(p->picture,512,512,0);put_sprite(p->title,256,64,0);
    put_sprite(p->bg[0],640,480,0);put_sprite(p->bg[1],640,480,0);
    for(int k=0;k<3;++k) if(p->cars[k]>1) put_sprite(p->cars[k],96+16*k,48,0);
  }
  for(int k=0;k<10;++k) {put_sprite(STORYPRE_DIGIT[k],12+2*k,20,0);put_sprite(TENDB_PRE_LV[k],24+2*k,24,0);}
  for(int c=0;c<3;++c)for(int l=0;l<10;++l)for(int k=0;k<4;++k)
    put_sprite(TENDB_PRE[c][l][k],k==0?640:80,k==0?480:32,0);
  for(int z=0;z<2;++z)for(int k=0;k<15;++k)put_sprite(PRE_BG[z][k],640,480,0);
  for(int k=0;k<15;++k)put_sprite(PRE_NAME[k],100+4*k,24,0);
  for(int z=0;z<2;++z)put_sprite(PRE_TIME[z],64,24,0);
  put_sprite(S_PRE_TITLE_VS,160,40,0);
  for(int set=0;set<3;++set) {put_sprite(CARD_BGM_SETS[set].logo,64+16*set,32,0);
    for(int line=0;line<CARD_BGM_SETS[set].lines;++line)put_sprite(BGM_TEXT+30*set+line,128+line,24,0);}
  anm_rec *r=&fixture_recs[ID.pre_bg][0];*r=make_rec(anm_sprite(T_PRE_BG),0,0);
  r->a=r->d=1;r->b=r->c=0;r->x=r->y=0;r->blend=0;
  /* Overshoot data is synthetic, but its authored x/affine must survive each frame. */
  for(int f=0;f<16;++f) {r=&fixture_recs[ID.loading][f*2];r->x=480.0f+(f<10?40.0f-6*f:f<15?-20.0f+5*(f-10):0);}
  WIDE_ZOOM=1;photo_bg=0;
}
static float set_extent(int w,int h) {
  screen_w=w;screen_h=h;float edge=fmaxf(0,(768.0f*(float)w/(float)h-1024.0f)*.5f);
  anm_view(edge);menu_wide(edge);return edge;
}
static void expect(int id,int side) {
  if(id<0 || anm_sprite(id)<0)return;
  assert(nexpect<128);expect_id[nexpect]=id;expect_side[nexpect++]=side;
}
static void expected_menu(const menu_state *m,int vs,float fade) {
  nexpect=0;if(fade<=0)return;
  int story=!vs && m->game==MENU_GAME_STORY && m->story_sel>=0 && m->story_sel<STORYPRE_N && ID.pre_st>=0;
  int ten=!vs && m->game==MENU_GAME_TEN && ID.pre_or>=0;
  if(story) {
    const storypre_select *s=&STORYPRE[m->story_sel];
    expect(s->bg[m->zone!=0],0);expect(s->title,-1);expect(s->picture,1);
    if(s->cars[0]>1)expect(s->cars[0],1);if(s->cars[1]>1)expect(s->cars[1],1);if(s->cars[2]>1)expect(s->cars[2],1);
    expect(45001,0);expect(s->title,-1);
    char digits[8];snprintf(digits,sizeof digits,"%d",s->episode);
    for(unsigned i=0;i<strlen(digits);++i)expect(STORYPRE_DIGIT[digits[i]-'0'],-1);
    expect(45001,0);
  } else if(ten) {
    const int *p=TENDB_PRE[m->ten_course][m->ten_level];
    expect(p[0],0);expect(0xb5c,-1);expect(p[1],-1);expect(p[3],1);expect(p[2],-1);
    expect(0x61b,-1);expect(TENDB_PRE_LV[m->ten_level],-1);expect(45001,0);expect(TENDB_PRE_LV[m->ten_level],-1);
  } else {
    expect(PRE_BG[m->zone][m->course],0);expect(vs?S_PRE_TITLE_VS:2909,-1);
    expect(PRE_NAME[m->course],-1);expect(PRE_TIME[m->zone],-1);expect(45001,0);expect(vs?S_PRE_TITLE_VS:2909,-1);
  }
  int set=m->vs.state!=MENU_VS_OFF?0:m->bgm_source;
  int song=m->song;if(set==0 && song>20)song=1+(song-1)%20;
  int line=song>0 && song<CARD_BGM_SETS[set].lines-1?song:CARD_BGM_SETS[set].lines-1;
  expect(0x75d,1);if(line<CARD_BGM_SETS[set].lines-1)expect(CARD_BGM_SETS[set].logo,1);
  expect(BGM_TEXT+30*set+line,1);expect(0x75c,1);expect(45001,0);expect(BGM_TEXT+30*set+line,1);
}
static void check_menu(menu_state *m,int vs,float fade,int w,int h) {
  set_extent(w,h);anm_view(0);menu_wide(0);nrecords=0;
  if(vs)draw_pre_as(m,fade,1);else draw_pre(m,fade);
  expected_menu(m,vs,fade);assert(nrecords==nexpect);
  for(unsigned i=0;i<nrecords;++i) assert(A.ids[records[i].d.textures[0]-100]==expect_id[i]);
  take_reference();float edge=set_extent(w,h);photo_bg=0;
  if(vs)draw_pre_as(m,fade,1);else draw_pre(m,fade);
  assert(photo_bg==1 && nrecords==nreference);
  for(unsigned i=0;i<nrecords;++i) {
    if(i==0) { /* Actual unchanged cover equation; background is NOT a translated panel. */
      packet_equal(&reference[i],&records[i],1);float zoom=(1024+2*edge)/1024;
      for(int k=0;k<4;++k) {near(records[i].pos[k*2],512*(1-zoom)+zoom*reference[i].pos[k*2]);
        near(records[i].pos[k*2+1],384*(1-zoom)+zoom*reference[i].pos[k*2+1]);++vertex_checks;}
    } else translated(&reference[i],&records[i],edge*expect_side[i],0);
  }
  hash_records();++cases;++menu_cases;
}
static const int extents[][2]={{1024,768},{1920,1080},{2160,1080},{2340,1080},{2400,1080},
  {1920,882},{1280,720},{3840,2160},{2048,1536}};
static void menu_matrix(void) {
  fixture_reset();const float fades[]={0,.375f,1};const int times[]={0,15,29,99};
  const int bgms[][2]={{0,1},{0,-1},{0,22},{1,24},{2,12}};
  for(unsigned e=0;e<sizeof extents/sizeof extents[0];++e) {
    for(int st=0;st<STORYPRE_N;++st)for(int z=0;z<2;++z)for(unsigned f=0;f<3;++f)
      for(unsigned t=0;t<4;++t)for(unsigned b=0;b<5;++b) {
        menu_state m={0};m.game=MENU_GAME_STORY;m.story_sel=st;m.zone=z;m.t=times[t];
        m.bgm_source=bgms[b][0];m.song=bgms[b][1];
        check_menu(&m,0,fades[f],extents[e][0],extents[e][1]);
      }
    for(int mode=0;mode<3;++mode)for(int c=0;c<(mode==0?3:15);++c)for(int l=0;l<(mode==0?10:1);++l)
      for(int z=0;z<2;++z)for(unsigned f=0;f<3;++f)for(unsigned t=0;t<4;++t)for(unsigned b=0;b<5;++b) {
        menu_state m={0};m.game=mode==0?MENU_GAME_TEN:MENU_GAME_TA;m.course=c;m.ten_course=c;
        m.ten_level=l;m.zone=z;m.t=times[t];m.bgm_source=bgms[b][0];m.song=bgms[b][1];
        if(mode==2)m.vs.state=MENU_VS_LOBBY;
        check_menu(&m,mode==2,fades[f],extents[e][0],extents[e][1]);
      }
  }
  /* Missing menu resources select the production TA/sound fallback; no policy state escapes. */
  for(int missing=0;missing<3;++missing) {
    menu_state m={0};m.game=missing==1?MENU_GAME_TEN:MENU_GAME_STORY;m.song=-1;
    int st=ID.pre_st,ten=ID.pre_or,sound=ID.pre_sound_st;
    if(missing==0)ID.pre_st=-1;if(missing==1)ID.pre_or=-1;if(missing==2)ID.pre_sound_st=-1;
    check_menu(&m,0,.5f,1920,882);ID.pre_st=st;ID.pre_or=ten;ID.pre_sound_st=sound;
  }
}
static void loading_matrix(void) {
  fixture_reset();const int frames_[]={0,10,14,15,99};const float fades[]={0,.375f,1};
  for(unsigned e=0;e<sizeof extents/sizeof extents[0];++e)for(unsigned f=0;f<5;++f)for(unsigned a=0;a<3;++a) {
    set_extent(extents[e][0],extents[e][1]);anm_view(0);menu_wide(0);nrecords=0;
    draw_pre_loading(frames_[f],fades[a]);take_reference();float edge=set_extent(extents[e][0],extents[e][1]);
    draw_pre_loading(frames_[f],fades[a]);assert(nrecords==nreference);
    assert(nrecords==(fades[a]>0?2u:0u));
    for(unsigned i=0;i<nrecords;++i)translated(&reference[i],&records[i],i==0?-edge:0,0);
    hash_records();++cases;++loading_cases;
    /* Ordinary loading elsewhere must retain its authored placement. */
    nrecords=0;anm_draw_ex(ID.loading,frames_[f],fades[a],LOADING_PRE_DX,0,NULL,0);take_reference();
    anm_draw_ex(ID.loading,frames_[f],fades[a],LOADING_PRE_DX,0,NULL,0);exact_reference();
    ++cases;++loading_cases;
  }
}
static void api_matrix(void) {
  const float matrix[][4]={{1,0,0,1},{2,.25f,-.5f,1.5f},{0,1,-1,0},{-1,0,0,.5f},{.6f,-.8f,.8f,.6f}};
  for(unsigned e=0;e<sizeof extents/sizeof extents[0];++e)for(unsigned m=0;m<5;++m)for(int sc=0;sc<2;++sc) {
    reset();emit=0;set_extent(extents[e][0],extents[e][1]);frames[0][1]=3;
    recs[0]=make_rec(6,0,0);recs[0].a=matrix[m][0];recs[0].b=matrix[m][1];recs[0].c=matrix[m][2];recs[0].d=matrix[m][3];
    recs[1]=recs[0];recs[1].sprite=1;recs[2]=recs[0];recs[2].sprite=0;ids[6]=ids[0];
    sizes[5][0]=20;sizes[5][1]=10;
    anm_swap sw[]={{0,5},{5,7},{1,-1}};float sx=sc?1.25f:1,sy=sc?.75f:1;
    draw_xy_layout(0,0,.625f,7,-9,sx,sy,sw,3,NULL,0);assert(nrecords==2);take_reference();
    float edge=A.edge>0?A.edge:13.0f;
    anm_layout_move moves[]={{0,-edge/SCALE,7.25f},{5,200,300}};
    draw_xy_layout(0,0,.625f,7,-9,sx,sy,sw,3,moves,2);assert(nrecords==2);
    for(unsigned i=0;i<2;++i) {assert(records[i].d.textures[0]==105);translated(&reference[i],&records[i],-edge,7.25f*SCALE);}
    hash_records();++cases;++api_cases;
    /* Matching the replacement instead of the ORIGINAL must never apply. */
    nrecords=0;anm_draw_layout(0,0,.625f,7,-9,sw,3,moves+1,1);take_reference();
    anm_draw_ex(0,0,.625f,7,-9,sw,3);exact_reference();++cases;++api_cases;
    /* Missing original / absent moves / zero rules / invalid finite offsets are identities. */
    const anm_layout_move identities[]={{-1,50,60},{0,0,0},{0,NAN,4},{0,INFINITY,0}};
    for(unsigned k=0;k<4;++k) {nrecords=0;anm_draw_ex(0,0,.625f,7,-9,sw,3);take_reference();
      anm_draw_layout(0,0,.625f,7,-9,sw,3,identities+k,1);exact_reference();++cases;++api_cases;}
    nrecords=0;anm_draw_ex(0,0,.625f,7,-9,sw,3);take_reference();
    anm_draw_layout(0,0,.625f,7,-9,sw,3,NULL,4);exact_reference();++cases;++api_cases;
    nrecords=0;anm_draw_layout(0,0,.625f,7,-9,sw,3,moves,0);exact_reference();++cases;++api_cases;
    nrecords=0;anm_draw_layout(0,0,.625f,7,-9,sw,3,moves,-1);exact_reference();++cases;++api_cases;
    /* First rule wins, repeated own IDs/records are NOT deduplicated. */
    anm_layout_move first[]={{0,2,3},{6,90,100}};nrecords=0;
    anm_draw_layout(0,0,.625f,7,-9,sw,3,first,2);assert(nrecords==2);
    for(unsigned i=0;i<2;++i)translated(&reference[i],&records[i],2*SCALE,3*SCALE);
    ++cases;++api_cases;
  }
  const int kinds[]={1574,1748,1908,45000};
  for(unsigned e=0;e<sizeof extents/sizeof extents[0];++e)for(unsigned k=0;k<4;++k) {
    reset();emit=0;set_extent(extents[e][0],extents[e][1]);ids[0]=kinds[k];sizes[0][0]=640;cols[0][1]=640;
    nrecords=0;anm_draw_ex(0,0,1,0,0,NULL,0);take_reference();anm_layout_move zero={0,0,0};
    anm_draw_layout(0,0,1,0,0,NULL,0,&zero,1);exact_reference();++cases;++api_cases;
    nrecords=0;anm_draw_layout(0,0,1,0,0,NULL,0,NULL,0);exact_reference();++cases;++api_cases;
    nrecords=0;anm_layout_move moved={0,-15,8};anm_draw_layout(0,0,1,0,0,NULL,0,&moved,1);assert(nrecords==1);
    /* Compare to authored full rectangle, not old implicitly extruded pieces. */
    struct Record target=records[0];anm_view(0);nrecords=0;anm_draw_ex(0,0,1,0,0,NULL,0);assert(nrecords==1);
    translated(&records[0],&target,-15*SCALE,8*SCALE);++cases;++api_cases;
    /* No policy leaks into the next unrelated anonymous draw. */
    set_extent(extents[e][0],extents[e][1]);nrecords=0;anm_draw_ex(0,0,1,0,0,NULL,0);exact_reference();++cases;++api_cases;
  }
  fixture_reset();const pre_anchor left[]={{0xfdc,-1}};
  nrecords=0;draw_pre_layout(ID.loading,10,1,LOADING_PRE_DX,NULL,0,left,1);take_reference();
  /* Explicitly exercise the helper's absent/oversized policy legacy route. */
  for(int k=0;k<3;++k) {nrecords=0;
    draw_pre_layout(ID.loading,10,1,LOADING_PRE_DX,NULL,0,k==0?NULL:left,k==1?0:k==2?17:1);
    exact_reference();++cases;++api_cases;}
}
static void density_contract(void) {
  fixture_reset();menu_state m={0};m.game=MENU_GAME_STORY;m.story_sel=14;m.song=1;m.t=15;
  const int pairs[][4]={{1920,1080,3840,2160},{1024,768,2048,1536},{1920,882,3840,1764}};
  for(unsigned p=0;p<3;++p) {
    set_extent(pairs[p][0],pairs[p][1]);nrecords=0;draw_pre(&m,.5f);unsigned n=nrecords;
    memcpy(saved,records,n*sizeof records[0]);set_extent(pairs[p][2],pairs[p][3]);nrecords=0;draw_pre(&m,.5f);assert(nrecords==n);
    for(unsigned i=0;i<n;++i) {packet_equal(&saved[i],&records[i],1);assert(!memcmp(saved[i].pos,records[i].pos,sizeof records[i].pos));}
    ++cases;++density_cases;
  }
}
int main(void) {
  assert(legacy_contract_main()==0); /* Unmodified old actions/asserts/goldens. */
  menu_matrix();loading_matrix();api_matrix();density_contract();
  printf("PRE_RESULT {\"cases\":%u,\"menu_cases\":%u,\"loading_cases\":%u,\"api_cases\":%u,\"density_cases\":%u,"
    "\"packet_checks\":%u,\"vertex_checks\":%u,\"trace\":\"%016llx\"}\n",
    cases,menu_cases,loading_cases,api_cases,density_cases,packet_checks,vertex_checks,(unsigned long long)trace);
  puts("PASS CPU PRE translation/order/UV/color/affine/identity/legacy contracts; NOT GPU/pixel/phone proof");return 0;
}
'''


def build_source():
    wrappers = "\n".join(function(ANM, anchor) for anchor in (
        "float anm_edge(", "int anm_frames(", "void anm_draw(", "void anm_draw_ex(",
        "void anm_draw_xf(", "void anm_draw_layout("))
    return (ns["prefix"] + ns["schema"] + ns["resources"] + ns["packet_writers"] + ns["gles"]
            + "\n#ifdef WMMT_NATIVE_VK\n" + ns["NATIVE"] + "\n#else\n"
            + function(ANM, "static void use_prog(") + "\n#endif\n" + ns["wide"]
            + ns["functions"] + wrappers
            + ns["tests"].replace("int main(void)", "int legacy_contract_main(void)")
            + menu_inputs + menu_functions + new_tests)


def run():
    source = build_source()
    results, goldens = {}, []
    with tempfile.TemporaryDirectory(prefix="wide-pre-layout-", dir=OUT) as temp:
        directory = Path(temp)
        env = dict(os.environ, TMPDIR=str(directory), TMP=str(directory), TEMP=str(directory),
                   HOME=str(directory), XDG_CACHE_HOME=str(directory), PYTHONDONTWRITEBYTECODE="1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        fixture = directory / "wide-pre.c"
        fixture.write_text(source)
        flags = ["-I", str(ROOT / "src"), "-I", str(ROOT / "test")]
        if sys.platform == "darwin":
            flags += ["-I", "/opt/homebrew/include"]
        for mode in ("native", "gles-control"):
            executable = directory / mode
            command = [os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                       "-fsanitize=undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", *flags]
            if mode == "native":
                command += ["-DWMMT_NATIVE_VK=1"]
            command += [str(fixture), "-lm", "-o", str(executable)]
            subprocess.run(command, env=env, cwd=directory, check=True, timeout=120)
            result = subprocess.run([str(executable)], env=env, cwd=directory,
                                    capture_output=True, text=True, timeout=120)
            log = OUT / ("wide-pre-layout-" + mode + ".log")
            log.write_text(result.stdout + result.stderr)
            if result.returncode:
                print(result.stdout, result.stderr, sep="\n", file=sys.stderr)
                result.check_returncode()
            goldens.append([line for line in result.stdout.splitlines() if line.startswith("DRAW ")])
            line = next(line for line in result.stdout.splitlines() if line.startswith("PRE_RESULT "))
            results[mode] = json.loads(line.split(" ", 1)[1])
            print(mode, line)
        assert goldens[0] and goldens[0] == goldens[1], "legacy native/GLES draw goldens differ"
        assert results["native"] == results["gles-control"], "new native/GLES packet traces differ"
    tracked = [ROOT / "src/anm.c", ROOT / "src/anm.h", ROOT / "src/menu.c",
               ROOT / "src/anm_native_vk.inc", ROOT / "src/native_vk.inc", legacy, Path(__file__)]
    report = {"status": "pass", "authority": "synthetic CPU production-function replay; no GPU/device/pixel proof",
              "legacy_draw_goldens": len(goldens[0]), "modes": results,
              "extents": [[1024, 768], [1920, 1080], [2160, 1080], [2340, 1080], [2400, 1080],
                          [1920, 882], [1280, 720], [3840, 2160], [2048, 1536]],
              "fixture_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}}
    result_path = Path(os.environ.get("WIDE_PRE_RESULT", str(OUT / "wide-pre-layout-result.json"))).resolve()
    if result_path == ROOT or ROOT in result_path.parents:
        raise SystemExit("WIDE_PRE_RESULT must be outside the source tree")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(report, indent=2) + "\n")
    print("PASS legacy exact draw goldens", len(goldens[0]), "and PRE matrices; result", result_path)


if __name__ == "__main__":
    run()
