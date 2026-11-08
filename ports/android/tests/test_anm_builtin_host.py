#!/usr/bin/env python3
"""Real built-in ANM upload/draw/trim, legacy goldens first, CPU recorders only.

No edits to old fixtures/production. Native mode declares no GL API. GLES mocks
separate upload binding from draw-program binding and retain blend-equation state.
The only pixel input is this project's self-owned compiled VS Mode artwork.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("TMPDIR", str(ROOT.parent.parent / "tmp"))).resolve()
if OUT == ROOT or ROOT in OUT.parents:
    raise SystemExit("TMPDIR must be outside source")
OUT.mkdir(parents=True, exist_ok=True)
legacy = ROOT / "tests/test_native_vk_anm_host.py"
ns = {"__file__": str(legacy), "__name__": "builtin_fixture_definitions"}
exec(compile(legacy.read_text().split("\nwith tempfile.TemporaryDirectory(", 1)[0], str(legacy), "exec"), ns)
ANM, function = ns["ANM"], ns["function"]
inc = (ROOT / "src/ui_vs_mode.inc").read_text()
body = inc.split("ANM_VS_MODE_Z[] = {", 1)[1].split("};", 1)[0]
compressed = bytes(int(s, 16) for s in re.findall(r"0x([0-9a-fA-F]{2})", body))
pixels = zlib.decompress(compressed)
EXPECTED = "fd2bb9264b574080df477fd9749d2621457e4b63cfff873a8f3b9cd1fa0a7937"
assert len(pixels) == 256*256*4 and hashlib.sha256(pixels).hexdigest() == EXPECTED
fnv = 1469598103934665603
for byte in pixels:
    fnv = ((fnv ^ byte) * 1099511628211) & ((1 << 64)-1)

prefix = ns["prefix"].replace('#include "glstub.h"', '#define glGetString legacy_glGetString\n#include "glstub.h"\n#undef glGetString')
prefix += '\n#include <float.h>\n#include <limits.h>\n#include <zlib.h>\n#include "ui_vs_mode.inc"\n'
uploads = r'''
static unsigned builtin_attempts, builtin_uploads, builtin_deletes;
static unsigned builtin_allocs, builtin_frees, builtin_live;
static int fail_alloc, fail_zlib, short_zlib, fail_upload, have_context=1;
static uint64_t pixels_hash(const void *p,size_t n){
  const unsigned char *s=p;uint64_t h=UINT64_C(1469598103934665603);
  for(size_t i=0;i<n;i++)h=(h^s[i])*UINT64_C(1099511628211);return h;
}
static void check_pixels(const void *p,size_t n){assert(p&&n==256u*256u*4u);assert(pixels_hash(p,n)==EXPECTED_FNV);}
static void *builtin_test_malloc(size_t n){++builtin_allocs;if(fail_alloc)return NULL;void*p=malloc(n);if(p)++builtin_live;return p;}
static void builtin_test_free(void*p){if(p){assert(builtin_live);--builtin_live;++builtin_frees;}free(p);}
static int builtin_test_uncompress(Bytef*d,uLongf*n,const Bytef*s,uLong len){
  if(fail_zlib)return Z_DATA_ERROR;int result=uncompress(d,n,s,len);if(short_zlib&&result==Z_OK)--*n;return result;
}
#ifdef WMMT_NATIVE_VK
uint32_t cinder_vk_texture_rgba8(int w,int h,const void*p,size_t n,const cinder_vk_sampler*s){
  assert(w==256&&h==256);check_pixels(p,n);assert(s&&s->use_state&&!s->mipmaps);
  assert(s->min_filter==VK_FILTER_LINEAR&&s->mag_filter==VK_FILTER_LINEAR&&s->anisotropy==1);
  assert(s->address_u==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE&&s->address_v==VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE);
  ++builtin_attempts;if(fail_upload)return 0;++builtin_uploads;return 9001;
}
void cinder_vk_texture_destroy(uint32_t t){assert(t==9001);++builtin_deletes;}
#else
static int upload_stage;
static GLuint upload_texture;
static unsigned upload_parameters;
static VkBlendOp persistent_equation=VK_BLEND_OP_ADD;
const unsigned char *glGetString(GLenum n){assert(n==GL_VERSION);return have_context?(const unsigned char*)"host recorder":NULL;}
void glGenTextures(GLsizei n,GLuint*t){assert(n==1&&t);++builtin_attempts;upload_stage=1;upload_parameters=0;*t=fail_upload?0:9001;}
void glTexParameteri(GLenum target,GLenum name,GLint value){
  assert(upload_stage&&target==GL_TEXTURE_2D);
  assert(((name==GL_TEXTURE_MIN_FILTER||name==GL_TEXTURE_MAG_FILTER)&&value==GL_LINEAR)||
         ((name==GL_TEXTURE_WRAP_S||name==GL_TEXTURE_WRAP_T)&&value==GL_CLAMP_TO_EDGE));
  upload_parameters|=name==GL_TEXTURE_MIN_FILTER?1u:name==GL_TEXTURE_MAG_FILTER?2u:name==GL_TEXTURE_WRAP_S?4u:8u;
}
void glTexImage2D(GLenum target,GLint level,GLint internal,GLsizei w,GLsizei h,GLint border,GLenum format,GLenum type,const void*p){
 assert(upload_stage&&target==GL_TEXTURE_2D&&!level&&internal==GL_RGBA&&w==256&&h==256&&!border&&format==GL_RGBA&&type==GL_UNSIGNED_BYTE);
 assert(upload_parameters==15);check_pixels(p,256u*256u*4u);if(upload_texture)++builtin_uploads;upload_stage=0;
}
void glDeleteTextures(GLsizei n,const GLuint*t){assert(n==1&&*t==9001);++builtin_deletes;}
#endif
'''.replace("EXPECTED_FNV", "UINT64_C(" + str(fnv) + ")")

gles = ns["gles"].replace(
    'void glUseProgram(GLuint p) { assert(cinder_vk_draw_init(&gl_packet,p,0,screen_w,screen_h)); }',
    'void glUseProgram(GLuint p) { assert(cinder_vk_draw_init(&gl_packet,p,0,screen_w,screen_h)); gl_packet.pipeline.blend_op=persistent_equation; }')
gles = gles.replace(
    'gl_packet.pipeline.blend_op=e==GL_FUNC_ADD?VK_BLEND_OP_ADD:VK_BLEND_OP_REVERSE_SUBTRACT;',
    'persistent_equation=e==GL_FUNC_ADD?VK_BLEND_OP_ADD:VK_BLEND_OP_REVERSE_SUBTRACT; gl_packet.pipeline.blend_op=persistent_equation;')
gles = gles.replace(
    'void glBindTexture(GLenum t,GLuint tex) { assert(t==GL_TEXTURE_2D); assert(cinder_vk_texture(&gl_packet,"uTex",tex)); }',
    'void glBindTexture(GLenum t,GLuint tex) { assert(t==GL_TEXTURE_2D); if(upload_stage){upload_texture=tex;return;} assert(cinder_vk_texture(&gl_packet,"uTex",tex)); }')

assert 'gl_packet.pipeline.blend_op=persistent_equation;' in gles
assert 'persistent_equation=e==GL_FUNC_ADD?' in gles
assert 'if(upload_stage){upload_texture=tex;return;}' in gles

builtin = '\n#define malloc builtin_test_malloc\n#define free builtin_test_free\n#define uncompress builtin_test_uncompress\n'
builtin += function(ANM, "static GLuint builtin_texture(")
builtin += '\n#undef malloc\n#undef free\n#undef uncompress\n'
builtin += function(ANM, "void anm_draw_builtin(") + '\n' + function(ANM, "void anm_trim(")
legacy_tests = "\n#define main original_anm_contract_main\n" + ns["tests"] + "\n#undef main\n"
checks = r'''
static void builtin_reset(void){
 reset();A.nsprites=0;A.clock=0;emit=0;builtin_attempts=builtin_uploads=builtin_deletes=0;
 builtin_allocs=builtin_frees=builtin_live=0;fail_alloc=fail_zlib=short_zlib=fail_upload=0;have_context=1;
#ifndef WMMT_NATIVE_VK
 upload_stage=0;upload_texture=0;persistent_equation=VK_BLEND_OP_ADD;
#endif
}
static void failure_contract(void){
 builtin_reset();A.prog=0;anm_draw_builtin(0,1,2,3,4,1);assert(!nrecords&&!builtin_attempts&&!builtin_allocs);
 builtin_reset();fail_alloc=1;anm_draw_builtin(0,1,2,3,4,1);assert(!nrecords&&!builtin_attempts&&!builtin_live);
 fail_alloc=0;fail_zlib=1;anm_draw_builtin(0,1,2,3,4,1);assert(!nrecords&&!builtin_attempts&&!builtin_live);
 fail_zlib=0;short_zlib=1;anm_draw_builtin(0,1,2,3,4,1);assert(!nrecords&&!builtin_attempts&&!builtin_live);
 short_zlib=0;fail_upload=1;anm_draw_builtin(0,1,2,3,4,1);assert(!nrecords&&builtin_attempts==1&&!A.builtin_tex[0]&&!builtin_live);
 fail_upload=0;anm_draw_builtin(0,1,2,3,4,1);assert(nrecords==1&&builtin_attempts==2&&builtin_uploads==1&&!builtin_live);
#ifndef WMMT_NATIVE_VK
 builtin_reset();have_context=0;anm_draw_builtin(0,1,2,3,4,1);assert(!nrecords&&!builtin_attempts&&!builtin_allocs);
 have_context=1;anm_draw_builtin(0,1,2,3,4,1);assert(nrecords==1&&builtin_uploads==1);
#endif
 puts("PASS built-in program/context/allocator/zlib/length/upload failure gates and successful retry; no live pixels retained");
}
static void invalid_geometry(void){
 builtin_reset();
 anm_draw_builtin(-1,0,0,1,1,1);anm_draw_builtin(1,0,0,1,1,1);
 const float invalid[]={NAN,INFINITY,-INFINITY};
 for(unsigned i=0;i<3;i++){
  float f=invalid[i];anm_draw_builtin(0,f,0,1,1,1);anm_draw_builtin(0,0,f,1,1,1);
  anm_draw_builtin(0,0,0,f,1,1);anm_draw_builtin(0,0,0,1,f,1);anm_draw_builtin(0,0,0,1,1,f);
 }
 anm_draw_builtin(0,0,0,0,1,1);anm_draw_builtin(0,0,0,-1,1,1);anm_draw_builtin(0,0,0,1,0,1);anm_draw_builtin(0,0,0,1,-1,1);
 anm_draw_builtin(0,0,0,1,1,0);anm_draw_builtin(0,0,0,1,1,-1);
 anm_draw_builtin(0,FLT_MAX,0,1,1,1);anm_draw_builtin(0,0,-FLT_MAX,1,1,1);
 anm_draw_builtin(0,0,0,FLT_MAX,1,1);anm_draw_builtin(0,0,0,1,FLT_MAX,1);
 anm_draw_builtin(0,FLT_MAX*.75f,0,FLT_MAX*.75f,1,1);
 assert(!nrecords&&!builtin_attempts&&!builtin_allocs&&!A.builtin_tex[0]);
 puts("PASS invalid id, NaN/Inf, nonpositive dimensions/alpha, finite sum/display-scale overflow are no-ops before upload");
}
static void geometry_and_cache(void){
 const int extents[][2]={{1024,768},{1920,1080},{2160,1080},{2340,1080},{2400,1080},{1920,882}};
 builtin_reset();emit=1;
 for(unsigned size=0;size<sizeof(extents)/sizeof(extents[0]);size++){
  screen_w=extents[size][0];screen_h=extents[size][1];
  float edge=fmaxf(0,((float)screen_w*768.0f/(float)screen_h-1024.0f)*.5f);anm_view(edge);
  float x=16-edge/1.6f,y=96,w=192,h=192;
  for(int a=0;a<2;a++){
   nrecords=0;
#ifndef WMMT_NATIVE_VK
   glBlendEquation(GL_FUNC_REVERSE_SUBTRACT); /* live GL state is not reset by use_prog */
#endif
   anm_draw_builtin(0,x,y,w,h,a?2.0f:.375f);assert(nrecords==1&&builtin_uploads==1&&builtin_attempts==1);
   vector(records[0].pos,(float[8]){x*1.6f,y*1.6f,(x+w)*1.6f,y*1.6f,x*1.6f,(y+h)*1.6f,(x+w)*1.6f,(y+h)*1.6f},8);
   vector(records[0].uv,(float[8]){0,0,1,0,0,1,1,1},8);color(0,(float[4]){1,1,1,a?1:.375f},(float[4]){0});
   near(uniform(0,0),1.0f/(512+edge));near(uniform(0,1),edge/(512+edge)-1);
   assert(records[0].d.pipeline.src_blend==VK_BLEND_FACTOR_SRC_ALPHA&&records[0].d.pipeline.dst_blend==VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA&&records[0].d.pipeline.blend_op==VK_BLEND_OP_ADD);
  }
 }
 assert(!builtin_live);emit=0;
 /* Existing trim runs on a 60-tick sweep: age180 survives; first age>180 sweep is240. */
 for(int i=0;i<180;i++)anm_trim();assert(A.clock==180&&A.builtin_tex[0]&&builtin_deletes==0);
 for(int i=0;i<59;i++)anm_trim();assert(A.builtin_tex[0]&&builtin_deletes==0);
 anm_trim();assert(A.clock==240&&!A.builtin_tex[0]&&builtin_deletes==1);
 nrecords=0;anm_draw_builtin(0,0,0,96,96,1);assert(nrecords==1&&builtin_uploads==2&&A.builtin_used[0]==240);
 for(int i=0;i<179;i++)anm_trim();anm_draw_builtin(0,0,0,96,96,1);assert(A.builtin_used[0]==419);
 for(int i=0;i<121;i++)anm_trim();assert(A.clock==540&&A.builtin_tex[0]&&builtin_deletes==1);
 puts("PASS built-in natural quad/UV/alpha clamp/uView across six aspects, explicit alpha-add blend, upload-once, touch-cache and sweep trim/reupload");
}
int main(void){
 assert(original_anm_contract_main()==0); /* preserve every old action/assert/golden first */
 failure_contract();invalid_geometry();geometry_and_cache();
 puts("BUILTIN ANM contracts PASS (CPU upload/driver recorders; no GPU/pixel proof)");return 0;
}
'''
source = (prefix + ns["schema"] + ns["resources"] + ns["packet_writers"] + uploads + gles +
          '\n#ifdef WMMT_NATIVE_VK\n' + ns["NATIVE"] +
          function((ROOT / "src/ui_native_vk_resources.inc").read_text(), "static uint32_t ui_native_texture_rgba8(") +
          '\n#else\n' + function(ANM, "static void use_prog(") + '\n#endif\n' +
          ns["wide"] + ns["functions"] + builtin + legacy_tests + checks)

with tempfile.TemporaryDirectory(prefix="anm-builtin-", dir=OUT) as directory:
    directory = Path(directory)
    fixture = directory / "builtin.c"
    fixture.write_text(source)
    goldens = []
    for mode, macros in (("native", ["-DWMMT_NATIVE_VK=1"]), ("gles", []), ("vkcompat", ["-DWMMT_VK=1"])):
        binary = directory / mode
        flags = ["-I", str(ROOT / "src"), "-I", str(ROOT / "test")]
        if sys.platform == "darwin":
            flags += ["-I", "/opt/homebrew/include"]
        command = [os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                   "-fsanitize=undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                   *flags, *macros, str(fixture), "-lm", "-lz", "-o", str(binary)]
        env = dict(os.environ, TMPDIR=str(directory), TMP=str(directory), TEMP=str(directory),
                   HOME=str(directory), XDG_CACHE_HOME=str(directory), PYTHONDONTWRITEBYTECODE="1",
                   UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        subprocess.run(command, env=env, cwd=directory, check=True, timeout=120)
        result = subprocess.run([str(binary)], env=env, cwd=directory, text=True, capture_output=True, timeout=30)
        if result.returncode:
            print(result.stdout, result.stderr)
        result.check_returncode()
        for line in result.stdout.splitlines():
            if not line.startswith("DRAW "):
                print(mode, line)
        goldens.append([line for line in result.stdout.splitlines() if line.startswith("DRAW ")])
    assert goldens[0] and goldens[0] == goldens[1] == goldens[2], "native/GLES/VKcompat golden mismatch"
    print("PASS exact legacy + built-in draw goldens", len(goldens[0]), "across all three modes")
print("Self-owned VS Mode RGBA SHA256", EXPECTED, "bytes", len(pixels))
