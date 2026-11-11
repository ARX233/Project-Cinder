#!/usr/bin/env python3
"""Offline card-pages integrity and transactional tests, no device required."""
import os, pathlib, platform, struct, subprocess, tempfile, zlib
P=pathlib.Path(__file__).resolve().parents[1]
HARNESS=r"""
#include <assert.h>
#include <string.h>
#define GL_FUNC_REVERSE_SUBTRACT 0x800B
#define GL_FUNC_ADD 0x8006
void glBlendEquation(unsigned int);
#include "anm.c"
static unsigned char uploaded[4];
void glGenTextures(GLsizei n,GLuint *p) { (void)n; *p=1; }
void glBindTexture(GLenum a,GLuint b) { (void)a;(void)b; }
void glTexParameteri(GLenum a,GLenum b,GLint c) { (void)a;(void)b;(void)c; }
void glTexImage2D(GLenum a,GLint b,GLint c,GLsizei w,GLsizei h,GLint d,GLenum e,GLenum f,const void *px) {
  (void)a;(void)b;(void)c;(void)d;(void)e;(void)f; assert(w==1 && h==1); memcpy(uploaded,px,4);
}
int main(int argc,char **argv) {
  (void)argc; A.nsprites=2; A.base_sprites=1; A.story_end=2;
  A.tex=calloc(2,sizeof *A.tex); A.offset=calloc(2,sizeof *A.offset); A.zsize=calloc(2,sizeof *A.zsize); A.used=calloc(2,sizeof *A.used); A.size=calloc(2,sizeof *A.size); A.ids=calloc(2,sizeof *A.ids); A.cols=calloc(2,sizeof *A.cols);
  A.ids[0]=17; A.ids[1]=23; A.size[0][0]=13; A.size[1][0]=14;
  A.file=tmpfile(); A.extra_file=tmpfile(); FILE *base=A.file,*story=A.extra_file; fwrite("BASE",1,4,base); fwrite("STOR",1,4,story); fflush(base); fflush(story);
  A.card_file=load_sprite_animations(argv[1], "card-pages.bin");
  assert(A.ids[0]==17 && A.ids[1]==23 && A.size[0][0]==13 && A.size[1][0]==14 && A.file==base && A.extra_file==story);
  if (!strcmp(argv[2],"valid")) {
    assert(A.nsprites==3 && A.nanims==1 && A.card_file && A.ids[2]==42);
    assert(anm_find("menu_layout_cardcheck_2")==0 && anm_frames(0)==1);
    assert(A.anims[0].recs[0].sprite==0 && A.anims[0].recs[1].sprite==1 && A.anims[0].recs[2].sprite==2);
    A.size[0][0]=A.size[0][1]=A.size[1][0]=A.size[1][1]=1;
    assert(texture(0) && !memcmp(uploaded,"BASE",4));
    assert(texture(1) && !memcmp(uploaded,"STOR",4));
    assert(texture(2) && !memcmp(uploaded,"abcd",4));
  } else assert(A.nsprites==2 && A.nanims==0 && !A.card_file);
  return 0;
}
"""
def pack(sid=42,payload=None,frame=(0,3),ref=(17,23,42),name=b'menu_layout_cardcheck_2'):
    z=zlib.compress(b'abcd') if payload is None else payload
    out=b'WCP1'+struct.pack('<IIIiHHI',1,1,1,sid,1,1,len(z))+z
    out+=struct.pack('<48sIIII',name,1,3,*frame)
    for i in ref: out+=struct.pack('<iH6f4h4h',i,0,1,0,0,1,0,0,256,256,256,256,0,0,0,0)
    return out

def main():
    with tempfile.TemporaryDirectory(prefix='card-pages-test-') as d:
        d=pathlib.Path(d); src=d/'test.c'; src.write_text(HARNESS); exe=d/'test'
        link='-Wl,-dead_strip' if platform.system()=='Darwin' else '-Wl,--gc-sections'
        subprocess.run([os.environ.get('CC','cc'),'-U__APPLE__','-std=c99','-ffunction-sections','-fdata-sections','-I',str(P/'src'),'-I',str(P/'test'),str(src),link,'-lz','-lm','-o',str(exe)],check=True)
        android=d/'android-test'
        subprocess.run([os.environ.get('CC','cc'),'-U__APPLE__','-D__ANDROID__','-std=c99','-ffunction-sections','-fdata-sections','-I',str(P/'src'),'-I',str(P/'test'),str(src),link,'-lz','-lm','-o',str(android)],check=True)
        path=d/'card-pages.bin'; good=pack()
        cases=[(good,True),(pack(sid=17),False),(pack(sid=23),False),(pack(payload=b'bad'),False),(pack(payload=zlib.compress(b'abcd')+b'x'),False),(good[:-1],False),(good+b'x',False),(pack(frame=(2,2)),False),(pack(ref=(17,23,99)),False),(b'WCP1'+struct.pack('<III',2,1,1),False)]
        for data,valid in cases:
            path.write_bytes(data); subprocess.run([str(exe),str(d),'valid' if valid else 'invalid'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        legacy=d/'wmmt'; legacy.mkdir(); side=d/'wmmt-sidecars'; side.mkdir()
        (legacy/'card-pages.bin').write_bytes(good)
        subprocess.run([str(android),str(legacy),'valid'],check=True)
        (side/'card-pages.bin').write_bytes(b'bad')
        subprocess.run([str(android),str(legacy),'invalid'],check=True)
        (side/'card-pages.bin').write_bytes(good)
        (legacy/'card-pages.bin').write_bytes(b'bad')
        subprocess.run([str(android),str(legacy),'valid'],check=True)
    print(f'{len(cases)} transactional and ID mapping checks and 3 Android path checks passed')
if __name__=='__main__': main()
