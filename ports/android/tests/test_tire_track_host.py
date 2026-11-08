"""Pure CPU contract test; run python3 -B test_tire_track_host.py.

All generated files and tool environment are isolated under /Volumes/CodexWork.
No device, network, Android build, or build script is involved.
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

HEADER = pathlib.Path(__file__).resolve().parents[1] / "src" / "tire_track.h"
C = r"""
#include "tire_track.h"
#include <assert.h>
#include <math.h>
#define EQ(a,b) (fabs((double)(a)-(double)(b)) < 0.0001)
int main(void) {
    TireTrack t; const TireTrackPair *p; int i;
    float m[16] = {1,2,3,0, 0,1,0,0, 0,0,1,0, 10,20,30,1};
    tire_track_init(&t);
    assert(!t.enabled && !t.wheel[0].count);
    assert(!tire_track_append(&t,0,m,0.7f,4,2));
    tire_track_enable(&t,1);
    assert(tire_track_append(&t,0,m,0.7f,4,2));
    p=tire_track_pair(&t,0,0);
    assert(p && p->strip_start && EQ(p->vertex[0].x,8) && EQ(p->vertex[0].y,14) && EQ(p->vertex[0].z,24));
    assert(EQ(p->vertex[1].x,12) && EQ(p->vertex[1].y,22) && EQ(p->vertex[1].z,36));
    assert(p->vertex[0].u==1 && p->vertex[1].u==0 && p->vertex[0].v==0);
    m[12]=13; assert(tire_track_append(&t,0,m,0.1f,4,2));
    assert(tire_track_pair(&t,0,1)->vertex[0].v==0);
    m[12]=16; m[13]=24; assert(tire_track_append(&t,0,m,0,4,2));
    p=tire_track_pair(&t,0,2); assert(EQ(p->vertex[0].v,5*0.208333328366) && p->vertex[0].alpha==0);
    assert(EQ(tire_track_pair(&t,0,0)->vertex[0].alpha,0.7));
    assert(tire_track_append(&t,1,m,0.4f,4,2));
    assert(t.wheel[1].count==1 && t.wheel[1].v==0 && t.wheel[0].count==3);
    for (i=0;i<20;i++) { m[12]=(float)i; assert(tire_track_append(&t,0,m,0.5f,4,2)); }
    assert(t.wheel[0].count==15 && t.wheel[1].count==1);
    assert(EQ(tire_track_pair(&t,0,0)->vertex[0].x,3));
    assert(EQ(tire_track_pair(&t,0,14)->vertex[0].x,17));
    assert(t.wheel[0].v>1.0f);
    m[5]=NAN; assert(!tire_track_append(&t,0,m,0.5f,4,2)); m[5]=1;
    m[12]=900000; assert(tire_track_append(&t,0,m,0.5f,4,2));
    p=tire_track_pair(&t,0,14); assert(p->strip_start && p->vertex[0].v==0);
    assert(!tire_track_append(&t,0,m,INFINITY,4,2));
    assert(!tire_track_append(&t,0,m,0.5f,NAN,2));
    assert(!tire_track_append(&t,0,m,0.5f,4,INFINITY));
    assert(!tire_track_append(&t,0,m,-0.1f,4,2));
    assert(!tire_track_append(&t,0,m,0.5f,1000001,2));
    assert(!tire_track_append(&t,0,0,0.5f,4,2));
    assert(!tire_track_append(&t,4,m,0.5f,4,2));
    tire_track_reset(&t); assert(t.enabled && !t.wheel[0].count && !t.wheel[1].count);
    assert(tire_track_append(&t,0,m,0,4,2));
    tire_track_enable(&t,1); assert(t.enabled && !t.wheel[0].count);
    tire_track_enable(&t,0); assert(!t.enabled && !t.wheel[0].count);
    return 0;
}
"""

class TireTrackHostTest(unittest.TestCase):
    def test_geometry(self):
        root = tempfile.mkdtemp(prefix="tire-track-host-", dir="/Volumes/CodexWork")
        env = os.environ.copy()
        for key in ("HOME", "TMP", "TMPDIR", "TEMP", "XDG_CACHE_HOME"):
            env[key] = root
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        src = pathlib.Path(root) / "test.c"
        exe = pathlib.Path(root) / "test"
        src.write_text(C, encoding="utf-8")
        subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(HEADER.parent), str(src), "-lm", "-o", str(exe)], env=env, cwd=root, check=True)
        subprocess.run([str(exe)], env=env, cwd=root, check=True)

if __name__ == "__main__":
    unittest.main()
