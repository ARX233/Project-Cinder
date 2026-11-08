#!/usr/bin/env python3
"""Compile actual paint and synchronization functions against a minimal host stub."""
from pathlib import Path
import subprocess
import tempfile

src = Path(__file__).resolve().parent.parent / "src"
def function(file, signature):
    text = (src / file).read_text()
    start = text.index(signature)
    opening = text.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]

code = r'''
#include <stdint.h>
#include <assert.h>
typedef struct { uint16_t src,dst; int k; } wpk_paint_swap;
typedef struct wpk_scene { struct wpk_scene *share; uint16_t *share_idx; uint32_t n_tex,n_paints,*textures,*loaded; wpk_paint_swap *paints; } wpk_scene;
''' + "\n".join(function(*args) for args in [
    ("render.c", "int wpk_has_paint("), ("render.c", "void wpk_paint("),
    ("render.c", "void wpk_share_sync("), ("app.c", "static void car_paint_for_draw(")]) + r'''
int main(void) {
 uint32_t bl[]={10,11,12},bt[]={10,11,12},al[]={90,20,21,22},at[]={90,20,21,22};
 wpk_paint_swap bp[]={{1,0,1},{2,0,2}},ap[]={{2,1,1},{3,1,2}};
 uint16_t idx[]={65535,65535,0,65535};
 wpk_scene b={.n_tex=3,.n_paints=2,.textures=bt,.loaded=bl,.paints=bp};
 wpk_scene a={.share=&b,.share_idx=idx,.n_tex=4,.n_paints=2,.textures=at,.loaded=al,.paints=ap};
 for(int pass=0;pass<3;pass++) {
  car_paint_for_draw(&b,&a,1); assert(bt[0]==11&&at[1]==21&&at[2]==11&&at[3]==22);
  uint32_t old=at[1]; at[1]=999; at[1]=old;
  car_paint_for_draw(&b,&a,2); assert(bt[0]==12&&at[1]==22&&at[2]==12&&at[3]==22);
  car_paint_for_draw(&b,0,1); assert(bt[0]==11);
  car_paint_for_draw(&b,&a,0); assert(bt[0]==10&&at[1]==20&&at[2]==10&&at[3]==22);
 }
 a.n_paints=0; car_paint_for_draw(&b,&a,2); assert(at[2]==12);
 a.share=0; a.n_paints=2; car_paint_for_draw(&b,&a,1); assert(at[1]==21);
 al[2]=0; car_paint_for_draw(&b,&a,1); assert(at[1]==20);
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="car-paint-host-") as directory:
    c, exe = Path(directory) / "test.c", Path(directory) / "test"
    c.write_text(code)
    subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("car paint host regression passed")
