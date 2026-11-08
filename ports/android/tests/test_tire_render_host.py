#!/usr/bin/env python3
"""Compile the exact Android tire renderer with a recording GL stub.

This is a host contract test, not verification of an actual GL context or GPU.
Build products and temporary files remain in a unique /Volumes/CodexWork directory.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def extract_function(source):
    match = re.search(r'\bvoid\s+render_tire_tracks\s*\([^;{}]*\)\s*\{', source)
    if not match:
        raise AssertionError('render_tire_tracks definition missing')
    # Balance braces while ignoring C comments and string/character literals.
    i, depth, state = match.end() - 1, 0, 'code'
    start = match.start()
    while i < len(source):
        c, nxt = source[i], source[i + 1:i + 2]
        if state == 'code':
            if c == '/' and nxt == '*': state = 'block'; i += 1
            elif c == '/' and nxt == '/': state = 'line'; i += 1
            elif c in ('"', "'"): state = c
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if not depth: return source[start:i + 1]
        elif state == 'block' and c == '*' and nxt == '/': state = 'code'; i += 1
        elif state == 'line' and c == '\n': state = 'code'
        elif state in ('"', "'"):
            if c == '\\': i += 1
            elif c == state: state = 'code'
        i += 1
    raise AssertionError('unterminated renderer definition')

STUB = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
typedef unsigned int GLenum; typedef unsigned int GLuint; typedef int GLint; typedef int GLsizei; typedef unsigned char GLboolean;
enum { GL_FALSE=0, GL_TRUE=1, GL_COLOR_WRITEMASK=2, GL_DEPTH_WRITEMASK, GL_TEXTURE0, GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE, GL_REPEAT, GL_DEPTH_TEST, GL_CULL_FACE, GL_BLEND, GL_FUNC_ADD, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ARRAY_BUFFER, GL_ELEMENT_ARRAY_BUFFER, GL_FLOAT, GL_UNSIGNED_BYTE, GL_UNSIGNED_SHORT, GL_TRIANGLES };
typedef struct { float m[16]; } mat4;
/* Exact render_vertex declaration is extracted from render.h below. */
__VERTEX__
#define RENDER_MAX_SPRITES __MAX__
typedef struct { GLuint id; GLint mvp,eye,fog,fog_color,tex,uv_off,grade,wet,horizon; } scene_prog;
typedef struct {float fog_far,fog_near,grade[3]; int draws,triangles;} render_params;
static scene_prog progs[2]; static GLuint white_tex=77; static int enhance_on;
static void enhance_grade(render_params *p, int x, float *g) { (void)x; memcpy(g,p->grade,3*sizeof(float)); }
#define CHECK(x) do {if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}} while(0)
static int calls, depth, blend, cull, active, program, sampler=-1, texture, wraps, wrapt, equation, sfactor, dfactor, draw_count, draw_mode, draw_type;
static int arraybuf=-1, elementbuf=-1, enables[3], asize[3], atype[3], anorm[3], astride[3];
static const void *aptr[3]; static uint16_t indices[12], last_indices[6];
static GLboolean mask[4]={0,1,0,1}, dw=1, mask_draw[4], dw_draw;
static int depth_draw,blend_draw,cull_draw,texture_draw;
static void glGetBooleanv(GLenum n, GLboolean *v){calls++; if(n==GL_COLOR_WRITEMASK) memcpy(v,mask,4); else {CHECK(n==GL_DEPTH_WRITEMASK); *v=dw;}}
static void glUseProgram(GLuint x){calls++;program=x;}
static void glUniformMatrix4fv(GLint a, GLsizei b, GLboolean c,const float *d){calls++;CHECK(a==11&&b==1&&c==0&&d);}
static void glUniform3f(GLint a,float b,float c,float d){calls++;(void)a;(void)b;(void)c;(void)d;}
static void glUniform2f(GLint a,float b,float c){calls++;(void)a;(void)b;(void)c;}
static void glUniform1i(GLint a,int b){calls++; CHECK(a==15);sampler=b;}
static void glUniform1f(GLint a,float b){calls++;(void)a;(void)b;}
static void glUniform3fv(GLint a,GLsizei b,const float *c){calls++;(void)a;(void)b;(void)c;}
static void glActiveTexture(GLenum a){calls++;active=a;}
static void glBindTexture(GLenum a,GLuint b){calls++;CHECK(a==GL_TEXTURE_2D);texture=b;}
static void glTexParameteri(GLenum a,GLenum b,GLint c){calls++;CHECK(a==GL_TEXTURE_2D);if(b==GL_TEXTURE_WRAP_S) wraps=c; else {CHECK(b==GL_TEXTURE_WRAP_T);wrapt=c;}}
static void glEnable(GLenum a){calls++;if(a==GL_DEPTH_TEST)depth=1;else if(a==GL_BLEND)blend=1;else {CHECK(a==GL_CULL_FACE);cull=1;}}
static void glDisable(GLenum a){calls++;if(a==GL_DEPTH_TEST)depth=0;else if(a==GL_BLEND)blend=0;else {CHECK(a==GL_CULL_FACE);cull=0;}}
static void glDepthMask(GLboolean a){calls++;dw=a;}
static void glColorMask(GLboolean a,GLboolean b,GLboolean c,GLboolean d){calls++;mask[0]=a;mask[1]=b;mask[2]=c;mask[3]=d;}
static void glBlendEquation(GLenum a){calls++;equation=a;}
static void glBlendFunc(GLenum a,GLenum b){calls++;sfactor=a;dfactor=b;}
static void glBindBuffer(GLenum a,GLuint b){calls++;if(a==GL_ARRAY_BUFFER)arraybuf=b;else {CHECK(a==GL_ELEMENT_ARRAY_BUFFER);elementbuf=b;}}
static void glEnableVertexAttribArray(GLuint a){calls++;CHECK(a<3);enables[a]++;}
static void glVertexAttribPointer(GLuint a,GLint b,GLenum c,GLboolean d,GLsizei e,const void *f){calls++;CHECK(a<3);asize[a]=b;atype[a]=c;anorm[a]=d;astride[a]=e;aptr[a]=f;}
static void glDrawElements(GLenum a,GLsizei b,GLenum c,const void *d){calls++;draw_mode=a;draw_count=b;draw_type=c;depth_draw=depth;blend_draw=blend;cull_draw=cull;texture_draw=texture;dw_draw=dw;memcpy(mask_draw,mask,4);memcpy(indices,d,12*sizeof(uint16_t));memcpy(last_indices,(const uint16_t*)d+b-6,6*sizeof(uint16_t));}
"""
MAIN = r"""
int main(void) {
  mat4 vp={{0}}; render_vertex v[8]={{0}}; render_params p={.fog_far=3,.fog_near=2,.grade={1,1,1},.draws=7,.triangles=9};
  progs[0]=(scene_prog){.id=123,.mvp=11,.tex=15,.wet=16};
  render_tire_tracks(NULL,v,2,42,&p); render_tire_tracks(&vp,NULL,2,42,&p); render_tire_tracks(&vp,v,2,42,NULL); render_tire_tracks(&vp,v,2,0,&p); render_tire_tracks(&vp,v,0,42,&p); render_tire_tracks(&vp,v,-1,42,&p);
  CHECK(calls==0&&p.draws==7&&p.triangles==9);
  render_tire_tracks(&vp,v,2,42,&p);
  const uint16_t expected[12]={0,1,2,0,2,3,4,5,6,4,6,7};
  CHECK(draw_mode==GL_TRIANGLES&&draw_count==12&&draw_type==GL_UNSIGNED_SHORT&&!memcmp(indices,expected,sizeof expected));
  CHECK(program==123&&sampler==0&&active==GL_TEXTURE0&&texture_draw==42&&texture==(int)white_tex);
  CHECK(wraps==GL_CLAMP_TO_EDGE&&wrapt==GL_REPEAT&&equation==GL_FUNC_ADD&&sfactor==GL_SRC_ALPHA&&dfactor==GL_ONE_MINUS_SRC_ALPHA);
  CHECK(depth_draw&&blend_draw&&!cull_draw&&!dw_draw&&mask_draw[0]&&mask_draw[1]&&mask_draw[2]&&!mask_draw[3]);
  CHECK(!mask[0]&&mask[1]&&!mask[2]&&mask[3]&&dw==1&&!blend&&cull);
  CHECK(arraybuf==0&&elementbuf==0&&enables[0]&&enables[1]&&enables[2]);
  CHECK(asize[0]==3&&atype[0]==GL_FLOAT&&!anorm[0]&&astride[0]==sizeof *v&&aptr[0]==v->pos);
  CHECK(asize[1]==2&&atype[1]==GL_FLOAT&&!anorm[1]&&astride[1]==sizeof *v&&aptr[1]==v->uv);
  CHECK(asize[2]==4&&atype[2]==GL_UNSIGNED_BYTE&&anorm[2]&&astride[2]==sizeof *v&&aptr[2]==v->rgba);
  CHECK(p.draws==8&&p.triangles==13);
  dw=0; render_tire_tracks(&vp,v,RENDER_MAX_SPRITES+37,42,&p);
  CHECK(draw_count==6*RENDER_MAX_SPRITES&&!dw&&p.draws==9&&p.triangles==13+2*RENDER_MAX_SPRITES);
  unsigned b=4*(RENDER_MAX_SPRITES-1); CHECK(last_indices[0]==b&&last_indices[1]==b+1&&last_indices[2]==b+2&&last_indices[3]==b&&last_indices[4]==b+2&&last_indices[5]==b+3);
  puts("tire render host contract: PASS"); return 0;
}
"""

class TireRenderHostTest(unittest.TestCase):
    def test_renderer_contract(self):
        src = (ROOT / 'src/render.c').read_text()
        header = (ROOT / 'src/render.h').read_text()
        vertex = re.search(r'typedef\s+struct\s*\{\s*float\s+pos\[3\],\s*uv\[2\];\s*uint8_t\s+rgba\[4\];\s*\}\s*render_vertex\s*;', header)
        maximum = re.search(r'^#define\s+RENDER_MAX_SPRITES\s+(\d+)\s*$', header, re.M)
        self.assertIsNotNone(vertex, 'real vertex layout missing')
        self.assertIsNotNone(maximum, 'sprite limit missing')
        self.assertRegex(header, r'void\s+render_tire_tracks\s*\(')
        self.assertRegex(src, r'#ifdef\s+__ANDROID__\s*/\*[\s\S]*?\*/\s*void\s+render_tire_tracks\s*\(')
        work = Path(tempfile.mkdtemp(prefix='tire-render-host-', dir='/Volumes/CodexWork'))
        env = os.environ.copy()
        for key in ('HOME','TMPDIR','TMP','TEMP','XDG_CACHE_HOME'):
            env[key] = str(work)
        text = STUB.replace('__VERTEX__',vertex.group()).replace('__MAX__',maximum.group(1))
        (work / 'test.c').write_text(text + '\n' + extract_function(src) + '\n' + MAIN)
        subprocess.run(['cc','-std=c99','-D__ANDROID__','-Wall','-Wextra','-Werror',str(work/'test.c'),'-o',str(work/'test')], cwd=work, env=env, check=True)
        subprocess.run([str(work/'test')], cwd=work, env=env, check=True)
        print('Host artifacts:', work, flush=True)

if __name__ == '__main__':
    unittest.main()
