#!/usr/bin/env python3
"""Recorded production UI resource contracts (UBSan, no device/GPU claims).

Resource functions and state declarations are selected verbatim from anm.c/hud.c;
no replacement uploader, parser, cache or lifetime logic is used. Every GL call
name from both production files and the declaration stub is poisoned in native
mode, including unreachable draw/state/query/upload/program calls. Reference
modes run the unchanged GLES/VKcompat resource branches against a GL recorder.
The separate draw suites retain all 72 ANM goldens and complete HUD packets.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(os.environ.get("TMPDIR", str(ROOT.parent / "tmp"))).resolve()
if TMP == ROOT or ROOT in TMP.parents:
    raise SystemExit("TMPDIR must be outside source")
PRIVATE = Path(os.environ["CINDER_PRIVATE_SRC"]).resolve() if os.environ.get("CINDER_PRIVATE_SRC") else ROOT / "src"
if not (PRIVATE / "racing_lamp_data.h").is_file():
    raise SystemExit("CINDER_PRIVATE_SRC must name reviewed generated headers")
ANM = (ROOT / "src/anm.c").read_text()
HUD = (ROOT / "src/hud.c").read_text()
GL = (ROOT / "test/glstub.h").read_text()


def function(source, anchor):
    a = source.index(anchor)
    start = source.index("{", a)
    depth = 0
    for end in range(start, len(source)):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if not depth:
                return source[a:end + 1] + "\n"
    raise ValueError(anchor)


def functions(source, anchors):
    return "\n".join(function(source, anchor) for anchor in anchors)


POISON = sorted(set(re.findall(r"\b(?:gl[A-Z]\w*|gl_compile_program|vkgl_\w*)\s*\(", ANM + HUD + GL)))
POISON = " ".join(re.sub(r"\s*\($", "", name) for name in POISON)
PREFIX = r'''
#include <assert.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#define RACING_LAMP_TEST 1
#include "glstub.h"
#include "native_vk.h"
#ifdef WMMT_NATIVE_VK
#include "ui_native_vk_resources.inc"
'''+"#pragma GCC poison " + POISON + r'''
#endif
static unsigned texture_n,buffer_n,program_n,deleted_tex_n,deleted_buffer_n;
static unsigned fail_tex,fail_buffer,fail_program;
static uint32_t deleted_tex[512],deleted_buffer[512];
typedef struct {uint32_t id; int w,h;size_t bytes;unsigned char data[16384];} texture_record;
typedef struct {uint32_t id;size_t bytes;unsigned char data[4096];} buffer_record;
static texture_record textures[256];static buffer_record buffers[32];
static unsigned error_reads;static GLenum sticky_error;
static uint64_t hash(const void*p,size_t n){const unsigned char*b=p;uint64_t h=1469598103934665603ULL;for(size_t i=0;i<n;++i)h=(h^b[i])*1099511628211ULL;return h;}
static void reset_records(void){texture_n=buffer_n=program_n=deleted_tex_n=deleted_buffer_n=0;fail_tex=fail_buffer=fail_program=error_reads=0;sticky_error=0;memset(textures,0,sizeof textures);memset(buffers,0,sizeof buffers);}
static void texture_bytes(unsigned index,const void *px,int w,int h){assert(index<texture_n);texture_record*r=&textures[index];assert(r->w==w&&r->h==h&&r->bytes==(size_t)w*h*4&&!memcmp(r->data,px,r->bytes));printf("GOLD TEX %d %d %zu %016llx\n",w,h,r->bytes,(unsigned long long)hash(px,r->bytes));}
static void buffer_bytes(unsigned index,const void *data,size_t n){assert(index<buffer_n);buffer_record*r=&buffers[index];assert(r->bytes==n&&!memcmp(r->data,data,n));printf("GOLD BUF %zu %016llx\n",n,(unsigned long long)hash(data,n));}
static uint32_t record_texture(int w,int h,const void*p,size_t n){assert(texture_n<256&&p&&w>0&&h>0&&n==(size_t)w*h*4&&n<=sizeof textures[0].data);texture_record*r=&textures[texture_n++];r->w=w;r->h=h;r->bytes=n;memcpy(r->data,p,n);r->id=texture_n==fail_tex?0:100+texture_n;return r->id;}
static uint32_t record_buffer(size_t n,const void*p){assert(buffer_n<32&&p&&n&&n<=sizeof buffers[0].data);buffer_record*r=&buffers[buffer_n++];r->bytes=n;memcpy(r->data,p,n);r->id=buffer_n==fail_buffer?0:200+buffer_n;return r->id;}
static uint32_t record_program(const char*vs,const char*fs,const char**a,int n){++program_n;assert(vs&&fs&&n>=1&&n<=3&&!strcmp(a[0],"aPos"));if(n>1)assert(!strcmp(a[1],"aUV"));if(n>2)assert(!strcmp(a[2],"aColor"));assert(strstr(vs,"gl_Position")&&strstr(fs,"gl_FragColor"));printf("GOLD PROG %d %016llx %016llx",n,(unsigned long long)hash(vs,strlen(vs)),(unsigned long long)hash(fs,strlen(fs)));for(int i=0;i<n;++i)printf(" %s",a[i]);putchar('\n');return fail_program==program_n?0:1000+program_n;}
#ifdef WMMT_NATIVE_VK
uint32_t cinder_vk_texture_rgba8(int w,int h,const void*p,size_t n,const cinder_vk_sampler*s){assert(s&&s->use_state==VK_TRUE&&s->mipmaps==VK_FALSE&&s->min_filter==VK_FILTER_LINEAR&&s->mag_filter==VK_FILTER_LINEAR&&s->mipmap_mode==VK_SAMPLER_MIPMAP_MODE_NEAREST&&s->address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->address_v==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->anisotropy==1);return record_texture(w,h,p,n);}
void cinder_vk_texture_destroy(uint32_t id){assert(id&&deleted_tex_n<512);deleted_tex[deleted_tex_n++]=id;}
uint32_t cinder_vk_buffer_create(size_t n,const void*p){return record_buffer(n,p);}
void cinder_vk_buffer_destroy(uint32_t id){assert(id&&deleted_buffer_n<512);deleted_buffer[deleted_buffer_n++]=id;}
uint32_t cinder_vk_program_create(const char*v,const char*f,const char**a,int n){return record_program(v,f,a,n);}
#else
static GLuint bound_tex,bound_buffer;static int tex_params[4];
GLuint gl_compile_program(const char*v,const char*f,const char**a,int n){return record_program(v,f,a,n);}
GLint glGetUniformLocation(GLuint p,const GLchar*n){assert(p&&n);return 1;}
void glGenTextures(GLsizei n,GLuint*p){assert(n==1);*p=101+texture_n;}
void glBindTexture(GLenum t,GLuint id){assert(t==GL_TEXTURE_2D);bound_tex=id;memset(tex_params,0,sizeof tex_params);}
void glTexParameteri(GLenum t,GLenum key,GLint value){assert(t==GL_TEXTURE_2D&&bound_tex);int k=key==GL_TEXTURE_MIN_FILTER?0:key==GL_TEXTURE_MAG_FILTER?1:key==GL_TEXTURE_WRAP_S?2:key==GL_TEXTURE_WRAP_T?3:-1;assert(k>=0&&value==(k<2?GL_LINEAR:GL_CLAMP_TO_EDGE));tex_params[k]=1;}
void glTexImage2D(GLenum t,GLint level,GLint internal,GLsizei w,GLsizei h,GLint border,GLenum format,GLenum type,const void*p){assert(t==GL_TEXTURE_2D&&level==0&&internal==GL_RGBA&&!border&&format==GL_RGBA&&type==GL_UNSIGNED_BYTE&&bound_tex);for(int i=0;i<4;++i)assert(tex_params[i]);assert(record_texture(w,h,p,(size_t)w*h*4)==bound_tex);}
void glDeleteTextures(GLsizei n,const GLuint*p){for(int i=0;i<n;++i)if(p[i])deleted_tex[deleted_tex_n++]=p[i];}
void glGenBuffers(GLsizei n,GLuint*p){assert(n==1);*p=201+buffer_n;}
void glBindBuffer(GLenum t,GLuint id){assert(t==GL_ARRAY_BUFFER||t==GL_ELEMENT_ARRAY_BUFFER);bound_buffer=id;}
void glBufferData(GLenum t,GLsizeiptr n,const void*p,GLenum u){assert((t==GL_ARRAY_BUFFER||t==GL_ELEMENT_ARRAY_BUFFER)&&u==GL_STATIC_DRAW&&bound_buffer);assert(record_buffer((size_t)n,p)==bound_buffer);}
void glDeleteBuffers(GLsizei n,const GLuint*p){for(int i=0;i<n;++i)if(p[i])deleted_buffer[deleted_buffer_n++]=p[i];}
GLenum glGetError(void){++error_reads;GLenum e=sticky_error;sticky_error=0;return e;}
#endif
static void out(FILE*f,const void*p,size_t n){assert(fwrite(p,1,n,f)==n);}
'''

ANM_SOURCE = ANM[ANM.index("typedef struct {"):ANM.index("#ifdef WMMT_NATIVE_VK")]
ANM_SOURCE += '#include "anm.h"\n#include "time_texture.h"\nstatic int read_all(FILE *, void *, size_t);\n#include "ghost_ui_loader.inc"\n'
ANM_SOURCE += functions(ANM, (
    "static int read_all(", "static void load_extra(", "static void load_card_pages(",
    "int anm_load(", "static GLuint texture(", "unsigned int anm_sprite_texture(", "void anm_trim(",
))
ANM_TESTS = r'''
static const unsigned char raw[16]={1,2,3,0,5,6,7,255,9,10,11,0,13,14,15,255};
static void sprite_file(FILE*f,int id,unsigned w,unsigned h,const unsigned char*px,int zipped){uint16_t wh[2]={(uint16_t)w,(uint16_t)h};uint32_t zs=0;unsigned char z[32768];uLongf n=sizeof z;if(zipped){assert(compress(z,&n,px,(uLong)w*h*4)==Z_OK);zs=(uint32_t)n;}out(f,&id,4);out(f,wh,4);out(f,&zs,4);out(f,zipped?z:px,zipped?zs:(size_t)w*h*4);}
static void release_anm(void){if(A.file)fclose(A.file);if(A.extra_file)fclose(A.extra_file);if(A.card_file)fclose(A.card_file);if(A.ghost_file)fclose(A.ghost_file);for(uint32_t i=0;i<A.nanims;++i){free(A.anims[i].frames);free(A.anims[i].recs);}free(A.tex);free(A.offset);free(A.zsize);free(A.used);free(A.size);free(A.ids);free(A.cols);free(A.anims);memset(&A,0,sizeof A);}
static void make_menu(void){FILE*f=fopen("menu.bin","wb");assert(f);uint32_t n=3,z=0;out(f,"WMN3",4);out(f,&n,4);sprite_file(f,77,2,2,raw,0);sprite_file(f,78,2,2,raw,1);unsigned char px[8192]={0};sprite_file(f,1573,64,32,px,1);out(f,&z,4);fclose(f);f=fopen("story-cutin.bin","wb");assert(f);n=1;out(f,"WMN3",4);out(f,&n,4);sprite_file(f,79,1,2,raw,0);out(f,&z,4);fclose(f);f=fopen("card-pages.bin","wb");assert(f);uint32_t v=1;out(f,"WCP1",4);out(f,&v,4);out(f,&n,4);out(f,&n,4);sprite_file(f,80,2,1,raw,1);char name[48]="resource-card";out(f,name,48);out(f,&n,4);out(f,&n,4);out(f,&z,4);out(f,&n,4);int32_t id=80;uint16_t blend=0;float xf[6]={1,0,0,1,0,0};int16_t mul[8]={256,256,256,256,0,0,0,0};out(f,&id,4);out(f,&blend,2);out(f,xf,24);out(f,mul,16);fclose(f);}
int main(void){reset_records();make_menu();assert(!anm_load(".")&&A.prog==1001&&A.nsprites==5&&A.base_sprites==3&&A.story_end==4&&A.nanims==1);A.edge=100;A.clock=17;
for(int i=0;i<5;++i)assert(anm_sprite_texture(i));assert(texture_n==5);texture_bytes(0,raw,2,2);texture_bytes(1,raw,2,2);unsigned char expected[8192]={0};time_texture_fix(1573,64,32,expected);texture_bytes(2,expected,64,32);texture_bytes(3,raw,1,2);texture_bytes(4,raw,2,1);assert(A.cols[0][0]==1&&A.cols[0][1]==2&&A.used[0]==17);assert(!anm_sprite_texture(-1)&&!anm_sprite_texture(5));A.clock=60;GLuint first=A.tex[0];assert(anm_sprite_texture(0)==first&&texture_n==5&&A.used[0]==60);A.clock=119;anm_trim();assert(A.clock==120&&!deleted_tex_n);A.clock=179;anm_trim();assert(A.clock==180&&!deleted_tex_n);A.clock=239;anm_trim();assert(A.clock==240&&deleted_tex_n==4&&A.tex[0]==first);A.clock=299;anm_trim();assert(A.clock==300&&deleted_tex_n==5&&!A.tex[0]);assert(anm_sprite_texture(0)&&texture_n==6);texture_bytes(5,raw,2,2);puts("PASS ANM actual raw/zlib/optional/card/time-fixed bytes, opacity cache, reuse and 60/180 trim");
#ifdef WMMT_NATIVE_VK
cinder_vk_texture_destroy(A.tex[0]);A.tex[0]=0;fail_tex=texture_n+1;assert(!anm_sprite_texture(0)&&!A.tex[0]);fail_tex=0;assert(anm_sprite_texture(0)&&texture_n==8);A.tex[1]=0;long offset=A.offset[1];A.offset[1]=LONG_MAX;unsigned before=texture_n;assert(!anm_sprite_texture(1)&&texture_n==before&&!A.tex[1]);A.offset[1]=offset;uint32_t packed=A.zsize[1];A.zsize[1]=2;assert(!anm_sprite_texture(1)&&texture_n==before&&!A.tex[1]);A.zsize[1]=packed;
assert(!ui_native_texture_rgba8(0,1,raw)&&!ui_native_texture_rgba8(1,0,raw)&&!ui_native_texture_rgba8(UINT_MAX,1,raw)&&!ui_native_texture_rgba8(1,1,NULL)&&texture_n==before);assert(!error_reads);release_anm();fail_program=program_n+1;assert(anm_load(".")==-1&&!A.prog&&!A.tex&&!A.nsprites);puts("PASS native upload/program failure never cached, retries and invalid bounded helper inputs, no GL error queries");
#else
release_anm();puts("PASS unchanged legacy GL linear/clamp RGBA8 upload and resource deletion control");
#endif
return 0;}
'''

HUD_SOURCE = r'''
#include "hud.h"
#include "racing_lamp_data.h"
#include "meterdb.h"
#include "meterdb_v2.h"
#include "meter_pack.h"
'''
HUD_SOURCE += HUD[HUD.index("static int navi_gl_init(void);"):HUD.index("#ifdef WMMT_NATIVE_VK\nstatic void hud_native_draw_layout_mode")]
HUD_SOURCE += HUD[HUD.index("#ifndef WMMT_NATIVE_VK\nstatic GLint u_proj"):HUD.index("int hud_gl_init(void)")]
HUD_SOURCE += function(HUD, "int hud_gl_init(")
HUD_SOURCE += HUD[HUD.index("enum {\n  SPR_SHIFT4"):HUD.index("static const float HUD_K")]
HUD_SOURCE += HUD[HUD.index("static GLuint upload("):HUD.index("/* Sprite centred")]
HUD_SOURCE += function(HUD, "static int preview_load(")
HUD_SOURCE += HUD[HUD.index("#define NAVI_VERT"):HUD.index("static int navi_gl_init(void) {")]
HUD_SOURCE += functions(HUD, ("static int navi_gl_init(void) {", "static void navi_clear(void) {", "static int navi_load(const char *path) {", "static void navi_select(int city, int force) {", "void hud_set_city("))
HUD_TESTS = r'''
static const unsigned char px[16]={1,2,3,0,5,6,7,255,9,10,11,0,13,14,15,255};
static unsigned char vb[144],ib[12];
static void make_navi(const char*path){FILE*f=fopen(path,"wb");assert(f);unsigned head[5]={2,2,1,2,2};out(f,"WNV1",4);out(f,head,20);out(f,px,16);out(f,px,8);for(int m=0;m<2;++m){short area=(short)(m+8);unsigned char mode[2]={(unsigned char)m,0};unsigned counts[2]={3,3};out(f,&area,2);out(f,mode,2);out(f,counts,8);for(unsigned i=0;i<72;++i)vb[m*72+i]=(unsigned char)(m*80+i);for(unsigned i=0;i<6;++i)ib[m*6+i]=(unsigned char)(i%2?0:i/2);out(f,vb+m*72,72);out(f,ib+m*6,6);}fclose(f);}
static void make_meter(const char*path,int extended){FILE*f=fopen(path,"wb");assert(f);unsigned zones=extended?6:2;unsigned h[5]={1,MP_CARS,MP_ZONES,MP_PARTS,1};if(extended){out(f,"WMS2",4);out(f,h,20);}else{out(f,"WMT1",4);unsigned a[2]={MP_CARS,1};out(f,a,8);}for(int c=0;c<MP_CARS;++c)for(unsigned z=0;z<zones;++z)for(int i=0;i<MP_PARTS;++i){int count=extended?METERDB_V2[c].n[z]:METERDB[c].n[z];uint16_t index=i<count?0:65535;out(f,&index,2);}unsigned table[3]={2,2,(extended?24:12)+MP_CARS*zones*MP_PARTS*2+12};out(f,table,12);out(f,px,16);fclose(f);}
static void hud_resources(void){make_meter("meters.bin",0);make_meter("meters-v2.bin",1);make_navi("navi.bin");make_navi("navi_oosaka.bin");FILE*f=fopen("hud.bin","wb");assert(f);out(f,"WHD1",4);unsigned n=1,wh[2]={2,2};char name[32]="sprite";out(f,&n,4);out(f,name,32);out(f,wh,8);out(f,px,16);fclose(f);assert(!hud_load("."));assert(NAVI.n==2&&NAVI.vbo&&NAVI.ibo&&NAVI.tex[0]&&NAVI.tex[1]&&navi_city==0&&navi_requested==0&&SPR[0].tex);texture_bytes(0,px,2,2);texture_bytes(1,px,1,2);texture_bytes(2,px,2,2);buffer_bytes(0,vb,sizeof vb);buffer_bytes(1,ib,sizeof ib);assert(NAVI.mesh[1].vert==3&&NAVI.mesh[1].index==3&&NAVI.mesh[1].n_index==3);
unsigned before=texture_n;hud_set_meter(0);hud_set_car(0,0);int count=METERDB[0].n[0];assert(count>0&&texture_n==before+(unsigned)count);for(int i=0;i<count;++i){assert(METER[i].tex);texture_bytes(before+i,px,2,2);}before=texture_n;hud_set_car(0,0);assert(texture_n==before);unsigned deleted=deleted_tex_n;hud_set_car(0,1);assert(deleted_tex_n==deleted+(unsigned)count);assert(meter_night==1);GLuint race=METER[0].tex;before=texture_n;assert(preview_load(0,0));assert(METER[0].tex==race&&texture_n==before+(unsigned)count);for(int i=0;i<count;++i){texture_bytes(before+i,px,2,2);assert(preview_alpha[i].visible&&preview_alpha[i].l==1&&preview_alpha[i].r==2&&preview_alpha[i].t==0&&preview_alpha[i].b==2);}before=texture_n;assert(preview_load(0,0)&&texture_n==before);deleted=deleted_tex_n;preview_clear();assert(deleted_tex_n==deleted+(unsigned)count&&preview_pack==-1&&preview_style==-1&&!preview_ok&&!preview_meter[0].tex&&!preview_alpha[0].visible&&METER[0].tex==race);hud_set_car(-1,0);assert(!meter_car&&!METER[0].tex&&!racing_lamp_on.tex&&racing_lamp_slot==-1);
GLuint old_vbo=NAVI.vbo;before=buffer_n;hud_set_city(0);assert(buffer_n==before);navi_warm[0]=navi_warm[1]=1;hud_set_city(1);assert(navi_city==1&&NAVI.vbo!=old_vbo&&deleted_buffer_n==2&&!navi_warm[0]&&!navi_warm[1]);buffer_bytes(before,vb,sizeof vb);buffer_bytes(before+1,ib,sizeof ib);navi_clear();assert(!NAVI.mesh&&!NAVI.n&&!NAVI.tex[0]&&!NAVI.vbo&&NAVI.next==NAVI_UNSET&&navi_city==-1&&deleted_buffer_n==4);puts("PASS HUD actual sprite/meter/preview/nav resource bytes, independent owners/cache keys, city swap/free/reset");}
static void lamp(void){unsigned char off[16384],on[16384];assert(lamp_inflate(off,lamp_off_m,sizeof lamp_off_m)&&lamp_inflate(on,lamp_on_m,sizeof lamp_on_m));METER[0]=(hud_sprite){999,64,64};unsigned before=texture_n;lamp_prepare(off,64,64,2,0);assert(racing_lamp_slot==0&&racing_lamp_on.tex&&texture_n==before+1);texture_bytes(before,on,64,64);unsigned deleted=deleted_tex_n;hud_set_car(-1,0);assert(deleted_tex_n==deleted+2&&!racing_lamp_on.tex&&racing_lamp_slot==-1);METER[0]=(hud_sprite){999,64,64};off[0]^=1;before=texture_n;lamp_prepare(off,64,64,2,0);assert(texture_n==before&&!racing_lamp_on.tex);METER[0]=(hud_sprite){0};puts("PASS actual lamp validates off pixels, uploads exact decoded on pixels and frees on car reset");}
#ifdef WMMT_NATIVE_VK
static void failures(void){unsigned before=texture_n;assert(!upload(px,0,2)&&texture_n==before);fail_tex=texture_n+1;assert(!upload(px,2,2));fail_tex=0;
const unsigned invalid[3][5]={{0,1,1,1,1},{1,UINT_MAX,1,1,1},{INT_MAX,INT_MAX,INT_MAX,INT_MAX,1}};for(int i=0;i<3;++i){FILE*f=fopen("bad-navi.bin","wb");assert(f);out(f,"WNV1",4);out(f,invalid[i],20);out(f,px,8);fclose(f);before=texture_n;unsigned bb=buffer_n;assert(!navi_load("bad-navi.bin")&&texture_n==before&&buffer_n==bb&&!NAVI.mesh&&!NAVI.n);}
cinder_vk_texture_destroy(SPR[0].tex);SPR[0]=(hud_sprite){0};fail_tex=texture_n+3;assert(!hud_load(".")&&!SPR[0].tex&&!SPR[0].w&&!SPR[0].h);fail_tex=0;navi_clear();
for(unsigned fail=1;fail<=4;++fail){navi_city=-1;NAVI.n=0;NAVI.mesh=NULL;NAVI.vbo=NAVI.ibo=NAVI.tex[0]=NAVI.tex[1]=0;unsigned bt=texture_n,bb=buffer_n,dt=deleted_tex_n,db=deleted_buffer_n;if(fail<=2)fail_buffer=bb+fail;else fail_tex=bt+fail-2;hud_set_city(0);assert(navi_city==-1&&!NAVI.n&&!NAVI.mesh&&!NAVI.vbo&&!NAVI.ibo&&!NAVI.tex[0]&&!NAVI.tex[1]);assert(deleted_tex_n==dt+(fail<=2?2:1)&&deleted_buffer_n==db+(fail<=2?1:2));fail_buffer=fail_tex=0;}
hud_set_city(0);GLuint kept=NAVI.vbo,kept_tex=NAVI.tex[0];int kept_n=NAVI.n;unsigned dt=deleted_tex_n,db=deleted_buffer_n;fail_tex=texture_n+2;hud_set_city(1);assert(navi_city==0&&navi_requested==1&&NAVI.vbo==kept&&NAVI.tex[0]==kept_tex&&NAVI.n==kept_n&&deleted_tex_n==dt+1&&deleted_buffer_n==db+2);fail_tex=0;navi_clear();
preview_clear();fail_tex=texture_n+2;unsigned count=(unsigned)METERDB[0].n[0];assert(count>1);dt=deleted_tex_n;assert(!preview_load(0,0)&&preview_pack==0&&preview_style==0&&!preview_ok&&!preview_meter[0].tex&&deleted_tex_n==dt+1);before=texture_n;fail_tex=0;assert(!preview_load(0,0)&&texture_n==before);preview_clear();assert(preview_load(0,0));preview_clear();
hud_set_meter(1);meter_car=NULL;fail_tex=texture_n+2;dt=deleted_tex_n;hud_set_car(0,0);assert(!meter_extra.sprites&&!meter_v2_active&&meter_car==&METERDB[0]&&METER[0].tex&&deleted_tex_n==dt+1);fail_tex=0;hud_set_car(-1,0);
unsigned char off[16384];assert(lamp_inflate(off,lamp_off_n,sizeof lamp_off_n));METER[0]=(hud_sprite){999,64,64};fail_tex=texture_n+1;lamp_prepare(off,64,64,3,0);assert(!racing_lamp_on.tex&&racing_lamp_slot==-1&&METER[0].tex==999);fail_tex=0;METER[0]=(hud_sprite){0};assert(!error_reads);
for(unsigned i=1;i<=3;++i){prog=tex_prog=NAVI.prog=0;fail_program=program_n+i;unsigned old=program_n;assert(hud_gl_init()==-1&&program_n==old+i);assert(i!=1||!prog);assert(i!=2||!tex_prog);assert(i!=3||!NAVI.prog);}fail_program=0;puts("PASS native texture/buffer/program failures; nav partial cleanup/old-city preservation; preview failed-key cache/retry; v2 fallback/lamp fail-closed");}
#else
static void legacy_errors(void){sticky_error=777;unsigned old=error_reads;METER[0]=(hud_sprite){999,64,64};unsigned char off[16384];assert(lamp_inflate(off,lamp_off_m,sizeof lamp_off_m));lamp_prepare(off,64,64,2,0);assert(racing_lamp_on.tex&&error_reads>=old+3);hud_set_car(-1,0);sticky_error=888;old=error_reads;assert(navi_load("navi.bin")&&error_reads>=old+3);navi_clear();puts("PASS legacy-only sticky GL error draining remains unchanged, no native fake-success query");}
#endif
int main(void){reset_records();assert(!hud_gl_init()&&program_n==3&&prog==1001&&tex_prog==1002&&NAVI.prog==1003);hud_resources();lamp();
#ifdef WMMT_NATIVE_VK
failures();
#else
legacy_errors();
#endif
mp_clear(&meter_legacy);mp_clear(&meter_extra);return 0;}
'''

with tempfile.TemporaryDirectory(prefix="native-ui-resources-", dir=TMP) as work:
    work = Path(work)
    env = dict(os.environ, TMPDIR=str(work), TMP=str(work), TEMP=str(work),
               HOME=str(work), XDG_CACHE_HOME=str(work), PYTHONDONTWRITEBYTECODE="1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    include = ["-I", str(ROOT / "src"), "-I", str(ROOT / "test"), "-I", str(PRIVATE)]
    if sys.platform == "darwin":
        include += ["-I", "/opt/homebrew/include"]
    for name, production, tests in (("anm", ANM_SOURCE, ANM_TESTS), ("hud", HUD_SOURCE, HUD_TESTS)):
        source = work / (name + ".c")
        source.write_text(PREFIX + production + tests)
        goldens = []
        for mode in ("native", "gles-control", "vkcompat-control"):
            directory = work / (name + "-" + mode)
            directory.mkdir()
            executable = directory / "test"
            command = [os.environ.get("CC", "clang"), "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                       "-Wno-unused-function", "-Wno-unused-variable", "-fsanitize=undefined", "-fno-sanitize-recover=all", *include]
            if mode == "native":
                command += ["-DWMMT_NATIVE_VK=1"]
            elif mode == "vkcompat-control":
                command += ["-DWMMT_VK=1"]
            command += [str(source), "-lm", "-lz", "-o", str(executable)]
            subprocess.run(command, cwd=directory, env=env, check=True, timeout=120)
            result = subprocess.run([str(executable)], cwd=directory, env=env, capture_output=True, text=True, timeout=30)
            print(name, mode, result.stdout, result.stderr, sep="\n")
            result.check_returncode()
            # Program failure calls intentionally occur only after success controls.
            lines = [line for line in result.stdout.splitlines() if line.startswith("GOLD ")]
            if mode == "native":
                success_end = result.stdout.index("PASS actual lamp") if name == "hud" else result.stdout.index("PASS ANM")
                lines = [line for line in result.stdout[:success_end].splitlines() if line.startswith("GOLD ")]
            goldens.append(lines)
        assert goldens[0] == goldens[1] == goldens[2], (name, "native/legacy production resource bytes differ")
        print("PASS native/GLES/VKcompat exact success resource goldens", name, len(goldens[0]))
for name in ("src/anm.c", "src/hud.c", "src/ui_native_vk_resources.inc"):
    print(name, "sha256", hashlib.sha256((ROOT / name).read_bytes()).hexdigest())
