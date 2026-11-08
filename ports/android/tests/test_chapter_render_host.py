"""Run the production story-render branch and chapter hit handlers with stubs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
WORK = Path("/Volumes/CodexWork")

def block(text, marker):
    start = text.index(marker)
    brace = text.index("{", start)
    depth = 0
    for i in range(brace, len(text)):
        depth += (text[i] == "{") - (text[i] == "}")
        if not depth:
            return text[start:i + 1]
    raise ValueError(marker)

class ChapterRenderHost(unittest.TestCase):
    def test_render_and_click(self):
        cc = shutil.which("clang") or shutil.which("cc")
        if not cc or not WORK.is_dir():
            self.skipTest("host compiler or /Volumes/CodexWork unavailable")
        text = (SRC / "menu.c").read_text()
        start = text.index("static const float CH_KEY[4]")
        constants = text[start:text.index("static int ch_hit(", start)]
        markers = ["static int st_div_of(", "static int st_loop(", "static int st_division(",
                   "static int st_cleared(", "static void st_states_of(", "static int ch_hit(",
                   "static void chapters_page(", "static int chapters_tap(", "static void draw_chapters("]
        fragments = "\n".join(block(text, marker) for marker in markers)
        draw = text.index("void menu_draw(")
        branch = block(text[draw:], "if (m->screen == MENU_ST_LEVEL || m->screen == MENU_ST_RIVAL)")
        c = r'''#include "menu.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define FADE 20
#define FLASH_LEN 20
#define SND_SELECT 1
#define SND_CURSOR 2
typedef struct { int level[4], ep[4][5], lv, slot; } st_states;
static int buttons,begins,ends,levels,rivals,sounds;
static char label[100];
static void snd_menu(int n) { sounds=n; }
static void hud_ui_begin(float w,float h) { assert(w==1024 && h==768); begins++; }
static void hud_ui_end(void) { ends++; }
static float hud_ui_text_width(const char *s,float p) { return strlen(s)*p; }
static void hud_ui_button(float x,float y,float w,float h,int a) { (void)x;(void)y;(void)w;(void)h;(void)a; buttons++; }
static void hud_ui_text(const char *s,float x,float y,float p,float r,float g,float b,float a) { (void)x;(void)y;(void)p;(void)r;(void)g;(void)b;(void)a; if(strlen(s)>1) snprintf(label,sizeof label,"%s",s); }
static void draw_st_level(const menu_state *m,float c,float f,int b) { (void)m;(void)c;(void)f;(void)b; levels++; }
static void draw_st_rival(const menu_state *m,float c,float f,int b) { (void)m;(void)c;(void)f;(void)b; rivals++; }
static void hud_draw_menu_keys(float w,float h,int a,int b,int c) { (void)w;(void)h;(void)a;(void)b;(void)c; }
static void anm_fill(float r,float g,float b,float a) { (void)r;(void)g;(void)b;(void)a; }
''' + constants + fragments + r'''
static int render(const menu_state *m) {
 float clock=0,fade=1,screen_w=1024,screen_h=768; int bars=0;
''' + branch.replace("return;", "return 1;") + r'''
 return 0;
}
static int tap(menu_state *m,float x,float y) { m->tap_x=x; m->tap_y=y; return chapters_tap(m); }
int main(void) {
 menu_state m={0}; m.screen=MENU_ST_LEVEL; m.from=-1; m.card_t=FADE; m.st_div=7; m.st_bits=0x1234;
 assert(render(&m)==1 && begins==1 && ends==1 && buttons==1 && levels==1);
 assert(!strcmp(label,"UNLOCK ALL CHAPTERS"));
 assert(!tap(&m,204.99f,410) && !m.story_test);
 assert(tap(&m,205,401.5f) && m.story_test==8 && m.options_dirty && sounds==SND_SELECT);
 buttons=0; assert(render(&m)==1 && buttons==3 && !strcmp(label,"2ND CHAPTERS 41-60"));
 assert(tap(&m,445,410) && m.story_test==9 && sounds==SND_CURSOR);
 assert(tap(&m,445,410) && m.story_test==10);
 sounds=0; assert(tap(&m,445,410) && m.story_test==10 && !sounds);
 assert(tap(&m,143,410) && m.story_test==9);
 m.story_test=1; sounds=0; assert(tap(&m,143,410) && m.story_test==1 && !sounds);
 assert(tap(&m,205,410) && !m.story_test && m.st_div==7 && m.st_bits==0x1234);
 int n=begins; m.screen=MENU_ST_RIVAL; assert(render(&m)==1 && begins==n && rivals==1);
 m.screen=MENU_ST_LEVEL; m.from=0; assert(render(&m)==1 && begins==n);
 m.from=-1; m.deciding=1; assert(render(&m)==1 && begins==n);
 m.screen=MENU_ST_RIVAL; m.deciding=0; assert(render(&m)==1 && begins==n);
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="wmmt-chapter-", dir=WORK) as tmp:
            source, binary = Path(tmp)/"test.c", Path(tmp)/"test"
            source.write_text(c)
            env = {**os.environ, "TMPDIR": tmp}
            subprocess.run([cc, "-std=c99", "-I", str(SRC), str(source), "-o", str(binary)], cwd=tmp, env=env, check=True)
            subprocess.run([str(binary)], cwd=tmp, env=env, check=True, timeout=30)

if __name__ == "__main__":
    unittest.main()
