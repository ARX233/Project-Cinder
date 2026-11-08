#!/usr/bin/env python3
"""Compile real vkgl context/state/query functions with minimal host types."""
from pathlib import Path
import subprocess
import tempfile

s = (Path(__file__).resolve().parents[1] / 'src/vkgl.c').read_text()
def extract(anchor):
    a = s.index(anchor); b = s.index('{', a); depth = 0
    for i in range(b, len(s)):
        if s[i] == '{': depth += 1
        elif s[i] == '}':
            depth -= 1
            if not depth: return s[a:i+1]
    raise ValueError(anchor)
a = s.index('typedef struct {', s.index("/* ---- a thread's GL state"))
b = s.index('} vctx;', a) + len('} vctx;')
names = ['static void ctx_init(', 'static int *cap_of(', 'void vkgl_glEnable(',
         'void vkgl_glDisable(', 'void vkgl_glDepthFunc(', 'void vkgl_glDepthMask(',
         'void vkgl_glColorMask(', 'void vkgl_glScissor(', 'void vkgl_glViewport(',
         'void vkgl_glBlendEquation(', 'void vkgl_glBlendFunc(', 'void vkgl_glCullFace(', 'void vkgl_glFrontFace(',
         'void vkgl_glActiveTexture(', 'void vkgl_glBindTexture(', 'void vkgl_glBindBuffer(',
         'void vkgl_glBindVertexArrayOES(', 'void vkgl_glGetIntegerv(', 'void vkgl_glGetBooleanv(',
         'void *vkgl_preview_save(', 'void vkgl_preview_restore(', 'void vkgl_scope_restore_preserve_error(',
         'uint64_t vkgl_error_epoch(', 'GLenum vkgl_glGetError(']
values = {'GL_FALSE':0,'GL_TRUE':1,'GL_ZERO':0,'GL_ONE':1,'GL_NO_ERROR':0,
 'GL_LESS':0x201,'GL_GREATER':0x204,'GL_ALWAYS':0x207,'GL_KEEP':0x1e00,
 'GL_BACK':0x405,'GL_CCW':0x901,'GL_FUNC_ADD':0x8006,'GL_BLEND':0xbe2,
 'GL_DEPTH_TEST':0xb71,'GL_SCISSOR_TEST':0xc11,'GL_CULL_FACE':0xb44,
 'GL_STENCIL_TEST':0xb90,'GL_FRAMEBUFFER_BINDING':0x8ca6,'GL_ACTIVE_TEXTURE':0x84e0,
 'GL_TEXTURE0':0x84c0,'GL_VIEWPORT':0xba2,'GL_SCISSOR_BOX':0xc10,'GL_DEPTH_FUNC':0xb74,
 'GL_MAX_SAMPLES_':0x8d57,'GL_BLEND_SRC_RGB':0x80c9,'GL_BLEND_SRC_ALPHA':0x80cb,
 'GL_BLEND_DST_RGB':0x80c8,'GL_BLEND_DST_ALPHA':0x80ca,'GL_CURRENT_PROGRAM':0x8b8d,
 'GL_ARRAY_BUFFER_BINDING':0x8894,'GL_DEPTH_BITS':0xd56,'GL_STENCIL_BITS':0xd57,
 'GL_RED_BITS':0xd52,'GL_GREEN_BITS':0xd53,'GL_BLUE_BITS':0xd54,'GL_ALPHA_BITS':0xd55,
 'GL_MAX_TEXTURE_SIZE':0xd33,'GL_MAX_TEXTURE_IMAGE_UNITS':0x8872,
 'GL_DEPTH_WRITEMASK':0xb72,'GL_COLOR_WRITEMASK':0xc23,
 'GL_BLEND_EQUATION_RGB':0x8009,'GL_BLEND_EQUATION_ALPHA':0x883d,
 'GL_FUNC_SUBTRACT':0x800a,'GL_FUNC_REVERSE_SUBTRACT':0x800b,
 'GL_CULL_FACE_MODE':0xb45,'GL_FRONT_FACE':0xb46,'GL_FRONT':0x404,'GL_CW':0x900,
 'GL_TEXTURE_BINDING_2D':0x8069,'GL_TEXTURE_BINDING_CUBE_MAP':0x8514,
 'GL_TEXTURE_2D':0xde1,'GL_TEXTURE_CUBE_MAP':0x8513,'GL_ELEMENT_ARRAY_BUFFER_BINDING':0x8895,
 'GL_ARRAY_BUFFER':0x8892,'GL_ELEMENT_ARRAY_BUFFER':0x8893,
 'GL_INVALID_ENUM':0x500,'GL_INVALID_OPERATION':0x502,'GL_SRC_ALPHA':0x302,'GL_ONE_MINUS_SRC_ALPHA':0x303}
pre = """#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
static int fail_calloc, fail_malloc;
static void *test_calloc(size_t n, size_t s) { return fail_calloc ? NULL : calloc(n,s); }
static void *test_malloc(size_t n) { return fail_malloc ? NULL : malloc(n); }
#define calloc test_calloc
#define malloc test_malloc
typedef unsigned GLenum, GLuint; typedef int GLint, GLsizei; typedef unsigned char GLboolean; typedef float GLfloat;
#define MAX_UNITS 8
#define MAX_ATTR 16
#define MAX_SAMP 8
typedef struct { int used; GLuint ebo; } vvao;
typedef struct { GLenum target; } vtex;
static vvao vaos[3]; static vtex textures[8];
static vvao *vao_get(GLuint n) { return n < 3 && vaos[n].used ? &vaos[n] : 0; }
static vtex *tex_get(GLuint n) { return n && n < 8 ? &textures[n] : 0; }
""" + ''.join('#define %s %d\n' % x for x in values.items()) + s[a:b] + """
static vctx main_ctx, loader_ctx; static _Thread_local vctx *cur_tls;
static uint64_t main_error_epoch, loader_error_epoch;
typedef struct { unsigned char *shadow; int block, samp_unit[MAX_SAMP], dirty; } vprog;
static unsigned char shadowbytes[4]; static vprog prog={shadowbytes,4,{0},0};
static vprog *prog_get(GLuint id) { return id==1 ? &prog : NULL; }
typedef struct { vctx state; vvao vao; GLuint program; unsigned char *shadow; int size; int samplers[MAX_SAMP]; } vkgl_preview_snapshot;
static struct { int max_samples; struct { struct { unsigned maxImageDimension2D; } limits; } props; } D;
""" + extract('static vctx *ctx(void)') + '\n' + extract('static void set_err(') + '\n' + extract('static vvao *cur_vao(') + '\n'
test = r"""
static void check(GLenum p, int expected) { GLboolean b=99; vkgl_glGetBooleanv(p,&b); assert(b==expected); }
static void query(GLenum p, int expected) { GLint v=-1; vkgl_glGetIntegerv(p,&v); assert(v==expected); }
static void depth(int expected) { query(GL_DEPTH_FUNC,expected); }
static void test_scope_restore(void) {
 for (int old=0; old<2; ++old) for (int fresh=0; fresh<2; ++fresh) {
  ctx_init(&main_ctx,0); cur_tls=0; main_error_epoch=0;
  main_ctx.unit=3; main_ctx.vao0.ebo=17; shadowbytes[0]=42; prog.samp_unit[0]=2; prog.dirty=0;
  if (old) set_err(GL_INVALID_ENUM);
  void *s=vkgl_preview_save(1); assert(s);
  main_ctx.unit=7; main_ctx.vao0.ebo=29; shadowbytes[0]=13; prog.samp_unit[0]=5;
  if (fresh) set_err(GL_INVALID_OPERATION);
  uint64_t epoch=(uint64_t)(old+fresh); vkgl_scope_restore_preserve_error(s);
  assert(main_ctx.unit==3 && main_ctx.vao0.ebo==17);
  assert(shadowbytes[0]==42 && prog.samp_unit[0]==2 && prog.dirty==1);
  assert(vkgl_error_epoch()==epoch);
  assert(vkgl_glGetError()==(old ? GL_INVALID_ENUM : fresh ? GL_INVALID_OPERATION : GL_NO_ERROR));
  assert(vkgl_glGetError()==GL_NO_ERROR && vkgl_error_epoch()==epoch);
 }
 set_err(GL_INVALID_ENUM); void *s=vkgl_preview_save(1); assert(s);
 assert(vkgl_glGetError()==GL_INVALID_ENUM); set_err(GL_INVALID_OPERATION);
 uint64_t epoch=vkgl_error_epoch(); vkgl_scope_restore_preserve_error(s);
 assert(vkgl_glGetError()==GL_INVALID_ENUM && vkgl_error_epoch()==epoch);
 main_ctx.unit=6; main_ctx.vao0.ebo=8; shadowbytes[0]=33; prog.samp_unit[0]=7; prog.dirty=0;
 set_err(GL_INVALID_OPERATION); vctx before=main_ctx; epoch=vkgl_error_epoch();
 fail_calloc=1; assert(!vkgl_preview_save(1)); fail_calloc=0;
 fail_malloc=1; assert(!vkgl_preview_save(1)); fail_malloc=0;
 assert(!vkgl_preview_save(99)); vkgl_scope_restore_preserve_error(NULL);
 assert(!memcmp(&before,&main_ctx,sizeof before) && vkgl_error_epoch()==epoch);
 assert(shadowbytes[0]==33 && prog.samp_unit[0]==7 && prog.dirty==0);
 ctx_init(&main_ctx,0); main_error_epoch=0;
}
int main(void) {
 test_scope_restore();
 ctx_init(&main_ctx,0); ctx_init(&loader_ctx,1);
 check(GL_SCISSOR_TEST,0); check(GL_DEPTH_TEST,0); depth(GL_LESS); check(GL_DEPTH_WRITEMASK,1);
 vkgl_glEnable(GL_SCISSOR_TEST); vkgl_glEnable(GL_DEPTH_TEST); vkgl_glDepthFunc(GL_GREATER);
 check(GL_SCISSOR_TEST,1); check(GL_DEPTH_TEST,1); depth(GL_GREATER);
 vkgl_glDisable(GL_SCISSOR_TEST); check(GL_SCISSOR_TEST,0); check(GL_DEPTH_TEST,1);
 cur_tls=&loader_ctx; check(GL_SCISSOR_TEST,0); check(GL_DEPTH_TEST,0); depth(GL_LESS);
 vkgl_glEnable(GL_SCISSOR_TEST); vkgl_glDisable(GL_DEPTH_TEST); vkgl_glDepthFunc(GL_ALWAYS);
 cur_tls=0; check(GL_SCISSOR_TEST,0); check(GL_DEPTH_TEST,1); depth(GL_GREATER);
 vkgl_glDisable(GL_DEPTH_TEST); check(GL_DEPTH_TEST,0);
 cur_tls=&loader_ctx; check(GL_SCISSOR_TEST,1); check(GL_DEPTH_TEST,0); depth(GL_ALWAYS);
 vkgl_glDisable(GL_SCISSOR_TEST); check(GL_SCISSOR_TEST,0);
 vkgl_glDepthMask(0); check(GL_DEPTH_WRITEMASK,0); vkgl_glDepthMask(4); check(GL_DEPTH_WRITEMASK,1);
 GLboolean m[4]={9,9,9,9}; vkgl_glColorMask(1,0,1,0); vkgl_glGetBooleanv(GL_COLOR_WRITEMASK,m);
 assert(m[0]==1 && m[1]==0 && m[2]==1 && m[3]==0);
 GLint box[4]; vkgl_glScissor(1,2,3,4); vkgl_glGetIntegerv(GL_SCISSOR_BOX,box);
 assert(box[0]==1 && box[1]==2 && box[2]==3 && box[3]==4);
 vkgl_glViewport(5,6,7,8); vkgl_glGetIntegerv(GL_VIEWPORT,box);
 assert(box[0]==5 && box[1]==6 && box[2]==7 && box[3]==8);
 cur_tls=0;
 check(GL_BLEND,0); check(GL_CULL_FACE,0); query(GL_BLEND_EQUATION_RGB,GL_FUNC_ADD);
 query(GL_BLEND_EQUATION_ALPHA,GL_FUNC_ADD); query(GL_CULL_FACE_MODE,GL_BACK); query(GL_FRONT_FACE,GL_CCW);
 vkgl_glEnable(GL_BLEND); vkgl_glEnable(GL_CULL_FACE); vkgl_glBlendEquation(GL_FUNC_SUBTRACT);
 vkgl_glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA); vkgl_glCullFace(GL_FRONT); vkgl_glFrontFace(GL_CW);
 check(GL_BLEND,1); check(GL_CULL_FACE,1); query(GL_BLEND_EQUATION_RGB,GL_FUNC_SUBTRACT);
 query(GL_BLEND_EQUATION_ALPHA,GL_FUNC_SUBTRACT); query(GL_CULL_FACE_MODE,GL_FRONT); query(GL_FRONT_FACE,GL_CW);
 query(GL_BLEND_SRC_RGB,GL_SRC_ALPHA); query(GL_BLEND_SRC_ALPHA,GL_SRC_ALPHA);
 query(GL_BLEND_DST_RGB,GL_ONE_MINUS_SRC_ALPHA); query(GL_BLEND_DST_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
 vkgl_glActiveTexture(GL_TEXTURE0+1); vkgl_glBindTexture(GL_TEXTURE_2D,1); vkgl_glBindTexture(GL_TEXTURE_CUBE_MAP,2);
 query(GL_ACTIVE_TEXTURE,GL_TEXTURE0+1); query(GL_TEXTURE_BINDING_2D,1); query(GL_TEXTURE_BINDING_CUBE_MAP,2);
 vkgl_glActiveTexture(GL_TEXTURE0+2); vkgl_glBindTexture(GL_TEXTURE_2D,3); query(GL_TEXTURE_BINDING_2D,3); query(GL_TEXTURE_BINDING_CUBE_MAP,0);
 vkgl_glActiveTexture(GL_TEXTURE0+1); query(GL_TEXTURE_BINDING_2D,1); query(GL_TEXTURE_BINDING_CUBE_MAP,2);
 vaos[1].used=1; vaos[2].used=1; vkgl_glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,41);
 vkgl_glBindVertexArrayOES(1); vkgl_glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,42);
 vkgl_glBindVertexArrayOES(2); vkgl_glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,43); query(GL_ELEMENT_ARRAY_BUFFER_BINDING,43);
 vkgl_glBindVertexArrayOES(1); query(GL_ELEMENT_ARRAY_BUFFER_BINDING,42);
 vkgl_glBindVertexArrayOES(0); query(GL_ELEMENT_ARRAY_BUFFER_BINDING,41);
 cur_tls=&loader_ctx; check(GL_BLEND,0); check(GL_CULL_FACE,0); query(GL_BLEND_EQUATION_RGB,GL_FUNC_ADD);
 query(GL_CULL_FACE_MODE,GL_BACK); query(GL_FRONT_FACE,GL_CCW); query(GL_TEXTURE_BINDING_2D,0); query(GL_ELEMENT_ARRAY_BUFFER_BINDING,0);
 vkgl_glEnable(GL_BLEND); vkgl_glBlendEquation(GL_FUNC_REVERSE_SUBTRACT); vkgl_glCullFace(GL_BACK); vkgl_glFrontFace(GL_CCW);
 vkgl_glActiveTexture(GL_TEXTURE0+1); vkgl_glBindTexture(GL_TEXTURE_2D,4); vkgl_glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,44);
 query(GL_BLEND_EQUATION_ALPHA,GL_FUNC_REVERSE_SUBTRACT); query(GL_TEXTURE_BINDING_2D,4); query(GL_ELEMENT_ARRAY_BUFFER_BINDING,44);
 cur_tls=0; check(GL_BLEND,1); check(GL_CULL_FACE,1); query(GL_BLEND_EQUATION_RGB,GL_FUNC_SUBTRACT);
 query(GL_CULL_FACE_MODE,GL_FRONT); query(GL_FRONT_FACE,GL_CW); query(GL_TEXTURE_BINDING_2D,1); query(GL_ELEMENT_ARRAY_BUFFER_BINDING,41);
 vkgl_glDisable(GL_BLEND); vkgl_glDisable(GL_CULL_FACE); check(GL_BLEND,0); check(GL_CULL_FACE,0);
 GLint v=7; vkgl_glGetIntegerv(0xdead,&v); assert(v==0); check(0xdead,0); assert(ctx()->err==0);
 puts("vkgl state query host test passed"); return 0;
}
"""
with tempfile.TemporaryDirectory(prefix='vkgl-state-query-') as tmp:
    cfile=Path(tmp)/'test.c'; exe=Path(tmp)/'test'
    cfile.write_text(pre+'\n'+'\n'.join(extract(n) for n in names)+'\n'+test)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(cfile),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
