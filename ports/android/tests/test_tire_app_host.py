"""Android app adapter host test; GL is captured, not a real context or GPU."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASSET = os.environ.get('TIRE_TRACK_WPK')  # caller-generated private original-derived WPK
NAMES = ('player_tracks_reset', 'player_tracks_asset_valid', 'player_tracks_open',
         'player_track_radius', 'player_tracks_tick', 'player_tracks_vertex', 'player_tracks_draw')


def extract(source, name):
    m = re.search(r'\bstatic\s+(?:void|int|float)\s+' + name + r'\s*\([^;{}]*\)\s*\{', source)
    if not m:
        raise AssertionError('missing function ' + name)
    i, depth, state = m.end()-1, 0, 'code'
    while i < len(source):
        c, n = source[i], source[i+1:i+2]
        if state == 'code':
            if c == '/' and n == '*': state = 'block'; i += 1
            elif c == '/' and n == '/': state = 'line'; i += 1
            elif c in ('"', "'"): state = c
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if not depth: return source[m.start():i+1]
        elif state == 'block' and c == '*' and n == '/': state='code'; i += 1
        elif state == 'line' and c == '\n': state='code'
        elif state in ('"', "'"):
            if c == '\\': i += 1
            elif c == state: state = 'code'
        i += 1
    raise AssertionError('unclosed function ' + name)

STUB = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <zlib.h>
#include "tire_track.h"
#include "car.h"
#define CHECK(x) do {if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
#define CARDB_NPACKS 3
static const char *CARDB_PACKS[]={"sub_RC2","toy_SW20","other"};
static struct {int race_pack;} G;
typedef struct {float m[16];} mat4;
typedef struct {float pos[3],uv[2]; uint8_t rgba[4];} render_vertex;
typedef struct {int unused;} render_params;
typedef struct {int fd,n_tex; uint32_t *textures,*loaded;} wpk_scene;
static TireTrack player_tracks; static wpk_scene track_scene; static uint32_t track_texture;
/* This fixture owns only tire geometry. The shared race-reset dependency is
 * captured here; actual tail clearing is checked in test_tail_trail_scene.py. */
static int race_tail_resets;
static void race_tail_reset(void){race_tail_resets++;}
static uint32_t textures[1],loaded[1]; static int loads,frees,detached,mode,pending; static uint64_t epoch;
int vkgl_error_pending(void){return pending;} uint64_t vkgl_error_epoch(void){return epoch;}
static int wpk_load(wpk_scene *s,const char *path) {
  (void)path; loads++; CHECK(s->fd==-1); if(mode==1)return -1;
  s->n_tex=1; s->textures=textures;s->loaded=loaded; textures[0]=42;loaded[0]=42;
  if(mode==2) {pending=1;epoch++;} if(mode==3)epoch++;
  if(mode==4)loaded[0]=0;return 0;
}
static void wpk_free(wpk_scene *s) { frees++; detached=(s->loaded && !s->loaded[0]);s->textures=NULL;s->loaded=NULL; }
static int draws,quad_count,baseline; static uint32_t capture_texture;
static render_vertex captured[4*TIRE_TRACK_WHEELS*(TIRE_TRACK_PAIRS-1)];
static void render_blend_pass(int x){CHECK(x==0);baseline++;}
static void render_tire_tracks(const mat4 *v,const render_vertex *p,int n,uint32_t t,render_params *rp){CHECK(v&&rp&&n>0);draws++;quad_count=n;capture_texture=t;memcpy(captured,p,(size_t)n*4*sizeof(*p));}
"""
MAIN = r"""
int main(int argc,char **argv) {
 CHECK(argc==3);
 char path[1100]; snprintf(path,sizeof path,"%s/tiretrack.wpk",argv[1]);CHECK(player_tracks_asset_valid(path));
 snprintf(path,sizeof path,"%s/tiretrack.wpk",argv[2]);CHECK(!player_tracks_asset_valid(path));
 player_tracks_open(argv[2]);CHECK(!track_texture&&!loads);
 player_tracks_open("/this-path-does-not-exist-07377");CHECK(!track_texture&&!loads);
 pending=1;epoch=7; player_tracks_open(argv[1]); CHECK(!track_texture&&!loads&&pending&&epoch==7);
 pending=0; epoch=UINT64_MAX;player_tracks_open(argv[1]);CHECK(!loads&&!track_texture&&epoch==UINT64_MAX);
 epoch=11;mode=2;player_tracks_open(argv[1]);CHECK(loads==1&&frees==1&&!track_texture&&pending&&epoch==12&&!detached);
 pending=0;mode=3;player_tracks_open(argv[1]);CHECK(loads==2&&frees==2&&!track_texture&&!pending&&epoch==13&&!detached);
 mode=4;player_tracks_open(argv[1]);CHECK(loads==3&&frees==3&&!track_texture);
 mode=0;player_tracks_open(argv[1]);CHECK(loads==4&&frees==4&&track_texture==42&&detached&&player_tracks.enabled);
 car_state car;memset(&car,0,sizeof car);mat4 vp={{0}};render_params rp={0};
 for(int i=0;i<4;i++){car.track_matrix[i][0]=1;car.track_matrix[i][5]=1;car.track_matrix[i][10]=1;car.track_matrix[i][15]=1;car.track_matrix[i][12]=(float)(i*10);car.track_matrix[i][13]=10;car.track_alpha[i]=(float)(i+1)*0.2f;}
 G.race_pack=0;CHECK(player_track_radius()==2);player_tracks_tick(&car);
 for(int i=0;i<4;i++){const TireTrackPair *p=tire_track_pair(&player_tracks,i,0);CHECK(p&&p->vertex[0].y==8&&fabsf(p->vertex[0].alpha-car.track_alpha[i])<0.0001f&&p->vertex[0].x==10*i-1&&p->vertex[1].x==10*i+1);}
 G.race_pack=1;CHECK(player_track_radius()==2.5f);G.race_pack=2;CHECK(player_track_radius()==3);G.race_pack=-1;CHECK(player_track_radius()==3);
 for(int i=0;i<4;i++) car.track_matrix[i][14]=4;
 G.race_pack=0;player_tracks_tick(&car);player_tracks_draw(&vp,&rp);CHECK(draws==1&&baseline==1&&quad_count==4&&capture_texture==42);
 CHECK(captured[0].pos[0]==1&&captured[1].pos[0]==-1&&captured[2].pos[0]==-1&&captured[3].pos[0]==1);
 CHECK(captured[0].pos[2]==0&&captured[2].pos[2]==4&&captured[0].uv[0]==0&&captured[1].uv[0]==1&&captured[0].rgba[3]==(uint8_t)(car.track_alpha[0]*255));
 player_tracks_reset();for(int i=0;i<4;i++)car.track_alpha[i]=0;player_tracks_tick(&car);player_tracks_tick(&car);player_tracks_draw(&vp,&rp);CHECK(draws==1);
 player_tracks_reset();for(int i=0;i<4;i++)car.track_alpha[i]=1;player_tracks_tick(&car);car.track_matrix[0][0]=NAN;player_tracks_tick(&car);car.track_matrix[0][0]=1;player_tracks_tick(&car);CHECK(tire_track_pair(&player_tracks,0,1)->strip_start);player_tracks_draw(&vp,&rp);CHECK(draws==2&&quad_count==6);
 player_tracks_reset();for(int j=0;j<20;j++){car.track_matrix[0][12]=(float)j;player_tracks_tick(&car);}CHECK(player_tracks.wheel[0].count==15&&tire_track_pair(&player_tracks,0,0)->vertex[0].x==4);player_tracks_reset();CHECK(player_tracks.enabled&&player_tracks.wheel[0].count==0);
 CHECK(race_tail_resets>0);
 puts("tire app host contract: PASS");return 0;
}
"""

class TireAppHostTest(unittest.TestCase):
    def test_app_adapter(self):
        if not ASSET:
            self.skipTest('set TIRE_TRACK_WPK to the locally generated original-derived WPK')
        source = (ROOT/'src/app.c').read_text()
        self.assertRegex(source, r'if\s*\(!movie\)\s*player_tracks_tick\(&G\.car\)')
        self.assertRegex(source, r'if\s*\(!movie\s*&&\s*!G\.vs_closed\)\s*player_tracks_draw\(&vp,\s*&G\.rp\)')
        work = Path(tempfile.mkdtemp(prefix='tire-app-host-', dir='/Volumes/CodexWork'))
        env = os.environ.copy()
        for key in ('HOME','TMPDIR','TMP','TEMP','XDG_CACHE_HOME'): env[key]=str(work)
        good=work/'good'; bad=work/'bad'; good.mkdir(); bad.mkdir()
        original=Path(ASSET).read_bytes(); (good/'tiretrack.wpk').write_bytes(original)
        damaged=bytearray(original); damaged[0] ^= 1; (bad/'tiretrack.wpk').write_bytes(damaged)
        c=work/'test.c'; c.write_text(STUB+'\n'+'\n'.join(extract(source,n) for n in NAMES)+'\n'+MAIN)
        subprocess.run(['cc','-std=c99','-D__ANDROID__','-DWMMT_VK','-Wall','-Wextra','-Werror','-I',str(ROOT/'src'),str(c),'-lm','-lz','-o',str(work/'test')],cwd=work,env=env,check=True)
        subprocess.run([str(work/'test'),str(good),str(bad)],cwd=work,env=env,check=True)
        print('Host artifacts:',work,flush=True)

if __name__=='__main__': unittest.main()
