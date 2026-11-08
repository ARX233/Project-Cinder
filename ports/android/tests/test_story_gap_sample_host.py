"""Host test for production story-gap sampling; no device or save access."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class StoryGapSampleTest(unittest.TestCase):
    def test_production_sampling(self):
        text = (ROOT / 'src/car.c').read_text()
        start = text.index('  /* Get2DInfoStory can leave individual output slots unwritten.')
        end = text.index('    /* clRaceThread::finiStory:', start)
        body = text[start:end]
        source = r'''#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "car.h"
static unsigned char buf[64];
static struct { int has_rival; uint32_t info_story; } P;
static int tick, calls;
static void storef(int p,float x){memcpy(buf+p,&x,4);}
static float readf(int p){float x;memcpy(&x,buf+p,4);return x;}
#define VA(p) (buf+(p))
#define WF(p,v) storef((p),(v))
#define MF(p) readf((p))
#define M8(p) (buf[p])
static void f_898287c(void) {}
static int call(void (*f)(void),int n,uint32_t p) {
 (void)f; (void)n; (void)p; calls++;
 if(tick==0){storef(0,1250);storef(4,-3000);storef(8,7);buf[12]=1;}
 if(tick==1){storef(0,NAN);storef(4,INFINITY);}
 if(tick==2)storef(8,-1000);
 return 1;
}
static void sample(car_race *r) {
''' + body + r'''
 }
}
#define CHECK(x) do {if(!(x)){fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(void) {
 car_race r={0}; P.has_rival=1; tick=0; sample(&r);
 CHECK(calls==1 && r.story_gap_valid[0] && r.story_gap_valid[1] && r.story_gap_valid[2]);
 CHECK(fabsf(r.gap-1.25f)<1e-6f && fabsf(r.story_gap[1]+3)<1e-6f);
 CHECK(r.story_on[0]==1 && r.story_on[1]==0); /* gap validity independent of picture */
 tick=1; sample(&r);
 CHECK(calls==2 && !r.story_gap_valid[0] && !r.story_gap_valid[1] && !r.story_gap_valid[2]);
 /* Existing HUD display fields retain prior values, but are invalid for rank. */
 CHECK(fabsf(r.gap-1.25f)<1e-6f && fabsf(r.story_gap[1]+3)<1e-6f && r.story_gap[2]>0 && r.story_on[0]);
 tick=2; sample(&r);
 CHECK(!r.story_gap_valid[0] && !r.story_gap_valid[1] && r.story_gap_valid[2] && r.story_gap[2]==-1);
 P.has_rival=0; sample(&r);
 CHECK(calls==3 && !r.story_gap_valid[0] && !r.story_gap_valid[1] && !r.story_gap_valid[2]);
 puts("PASS story gap written/missing/NaN/Inf/stale/no-rival and picture independence");
 return 0;
}
'''
        work = Path(tempfile.mkdtemp(prefix='story-gap-host-', dir='/Volumes/CodexWork'))
        env = os.environ.copy()
        for key in ('HOME', 'TMPDIR', 'TMP', 'TEMP', 'XDG_CACHE_HOME'):
            env[key] = str(work)
        source_path, executable = work / 'sample.c', work / 'sample'
        source_path.write_text(source)
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'src'),
                        str(source_path), '-lm', '-o', str(executable)], cwd=work, env=env, check=True)
        subprocess.run([str(executable)], cwd=work, env=env, check=True)
        print('Host artifacts:', work)

if __name__ == '__main__':
    unittest.main()
