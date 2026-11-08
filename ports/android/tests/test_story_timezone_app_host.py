"""Compile literal app.c excerpts with a minimal host state, on macOS or Linux.

No generated headers or game assets are needed. This tests extracted persistence
and city decisions, not the whole menu_frame, renderer, or real app initialization.
Run: python3 ports/android/tests/test_story_timezone_app_host.py
"""
from pathlib import Path
import shutil
import os
import subprocess
import tempfile
import unittest

ROOT = Path(os.environ.get('CINDER_TEST_SOURCE_ROOT', str(Path(__file__).resolve().parents[1]))).resolve()


def block(src, start):
    i = src.index(start)
    left = src.index('{', i)
    depth = 0
    for j in range(left, len(src)):
        if src[j] == '{': depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0: return src[i:j + 1]
    raise ValueError(start)


def program(src, header):
    city_path = block(src, 'static void city_path(')
    story_rival = block(src, 'static int story_rival(')
    tzread = src[src.index('  snprintf(path, sizeof path, "%s/timezone", G.save_dir);'):src.index('  G.extras_city = -1;', src.index('  snprintf(path, sizeof path, "%s/timezone", G.save_dir);'))]
    storyread = src[src.index('  G.menu.zone = zone;\n  G.menu.ta_zone = zone;'):src.index('  G.race_model = &G.fd3s;', src.index('  G.menu.zone = zone;\n  G.menu.ta_zone = zone;'))]
    start = src.index('  } else if (G.menu.game == MENU_GAME_STORY) {', src.index('static void menu_frame('))
    end = src.index('  } else if (G.menu.game == MENU_GAME_TEN)', start)
    city = src[start:end].replace('  } else if (G.menu.game == MENU_GAME_STORY) {', '  if (G.menu.game == MENU_GAME_STORY) {', 1) + '\n  }'
    at = src.index('  int story_was_selecting = G.menu.story_day_select && !G.menu.deciding;', src.index('static void menu_frame('))
    end = src.index('  if (old_slot == G.menu.save_slot', at)
    save = src[at:end]
    prefix = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <assert.h>
#include <sys/stat.h>
#include HEADER
static const char *CITY_FILE[] = {"tokyo", "osaka", "nagoya"};
#define STORYCITY_N 2
static const int STORYCITY[] = {1,2};
#define RIVALDB_N 2
#define TEN_FIRST 0
static const struct { int select, race, slot, series; } RIVALDB[] = {{3,0,0,0},{3,1,0,1}};
static struct { menu_state menu; char save_dir[1024], data_dir[1024]; int track_city, story_race, rival_env, hd_maps; } G;
static int same_name(const char *a, const char *b) { return !strcmp(a,b); }
static int action;
int menu_update(menu_state *m, float dt) {
  (void)dt;
  if (action==1) { m->story_zone=m->zone; m->deciding=30; }
  if (action==2) m->story_day_select=0;
  return 0;
}
""".replace('HEADER', '"' + str(header) + '"')
    main = r"""
static void put(const char *dir,const char *file,const char *val) {
  char path[2048]; snprintf(path,sizeof path,"%s/%s",dir,file);
  FILE *f=fopen(path,"w"); assert(f); fputs(val,f); fclose(f);
}
int main(int argc,char **argv) {
 assert(argc==2); snprintf(G.save_dir,sizeof G.save_dir,"%s",argv[1]);
 snprintf(G.data_dir,sizeof G.data_dir,"%s",argv[1]);
 init_read(); assert(G.menu.zone==0 && G.menu.ta_zone==0 && G.menu.story_zone==0);
 put(argv[1],"timezone","1"); init_read(); assert(G.menu.ta_zone==1 && G.menu.story_zone==0);
 put(argv[1],"story_timezone",""); init_read(); assert(G.menu.ta_zone==1 && G.menu.story_zone==0);
 put(argv[1],"story_timezone","x"); init_read(); assert(G.menu.ta_zone==1 && G.menu.story_zone==0);
 put(argv[1],"story_timezone","1"); init_read(); assert(G.menu.ta_zone==1 && G.menu.story_zone==1);
 G.menu.story_day_select=1;G.menu.deciding=0;G.menu.zone=0;action=2;write_decision();
 init_read(); assert(G.menu.story_zone==1 && G.menu.ta_zone==1);
 G.menu.story_day_select=1;G.menu.deciding=0;G.menu.zone=0;action=1;write_decision();
 init_read(); assert(G.menu.story_zone==0 && G.menu.ta_zone==1);
 G.menu.story_day_select=1;G.menu.deciding=0;G.menu.zone=1;action=1;write_decision();
 init_read(); assert(G.menu.story_zone==1 && G.menu.ta_zone==1);
 G.menu.story_day_select=1;G.menu.deciding=0;G.menu.zone=0;action=1;write_decision();
 init_read(); assert(G.menu.story_zone==0 && G.menu.ta_zone==1);
 G.menu.game=MENU_GAME_STORY;G.menu.screen=MENU_BGM;G.menu.story_day_select=1;G.menu.story_pick=3;G.story_race=1;G.rival_env=-1;G.track_city=0;
 G.menu.zone=1; int city=check_city();assert(city==1 && G.menu.zones==1 && G.menu.zone==0);
 put(argv[1],"osaka_night.wpk","");G.menu.zone=1;city=check_city();assert(city==1&&G.menu.zones==2&&G.menu.zone==1);
 G.menu.story_day_select=0;G.menu.screen=MENU_PRE; city=check_city();assert(city==2);
 snprintf(G.save_dir,sizeof G.save_dir,"%s/no-such-dir",argv[1]);init_read();assert(G.menu.ta_zone==0&&G.menu.story_zone==0);
 G.menu.story_day_select=1;G.menu.deciding=0;G.menu.zone=1;action=1;write_decision();
 snprintf(G.save_dir,sizeof G.save_dir,"%s",argv[1]);init_read();assert(G.menu.story_zone==0&&G.menu.ta_zone==1);
 puts("extracted app Story timezone tests passed");return 0;
}
"""
    return prefix + city_path + '\n' + story_rival + '\nstatic void init_read(void) { char path[1200]; int zones=2;\n' + tzread + storyread + '\n}\nstatic int check_city(void) { int city=G.track_city;\n' + city + '\nreturn city; }\nstatic void write_decision(void) { float dt=1.0f/60;\n' + save + '\n(void)go; }\n' + main


class AppStoryTimezone(unittest.TestCase):
    def test_extracted_production_code(self):
        clang = shutil.which('clang')
        if not clang: self.skipTest('clang unavailable')
        with tempfile.TemporaryDirectory(prefix='wmmt-story-app-') as tmp:
            for port in ('android','ipad'):
                with self.subTest(port=port):
                    # This workspace has one shared source tree, not two old
                    # ports/<name> checkouts. Explicit overrides still permit
                    # testing independently supplied platform trees.
                    port_src = Path(os.environ.get('CINDER_TEST_' + port.upper() + '_SRC', str(ROOT / 'src'))).resolve()
                    source = port_src / 'app.c'
                    header = port_src / 'menu.h'
                    cfile = Path(tmp) / (port + '.c')
                    binary = Path(tmp) / port
                    data = Path(tmp) / (port + '-data'); data.mkdir()
                    cfile.write_text(program(source.read_text(), header))
                    subprocess.run([clang, '-std=gnu99', str(cfile), '-o', str(binary)], check=True)
                    subprocess.run([str(binary), str(data)], check=True)

if __name__ == '__main__': unittest.main()
