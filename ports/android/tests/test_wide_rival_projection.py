#!/usr/bin/env python3
"""Exercise the actual rival-marker projection expressions on the host.

This checks projection and edge clamping, not GPU rendering or a device display.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
s = (ROOT / 'src/hud.c').read_text()
start = s.index('static void draw_mark(')
end = s.index('static void draw_rival_marks(', start)
body = s[start:end]
def get(pattern):
    m = re.search(pattern, body)
    if not m:
        raise AssertionError('missing projection expression: ' + pattern)
    return m.group(0)
half = get(r'float half_w = [^;]+;')
pos = get(r'float sx = [^;]+;')
clamp = get(r'float mx = 640\.0f - sx, lo = [^;]+;\s*mx = [^;]+;')
source = '''#include <assert.h>\n#include <math.h>\nstatic float edge;\nstatic float anm_edge(void) { return edge; }\n#define R_HALF_W 20.0f\nstatic void check(float e,float x,float expected,float expected_clamped) {\n  edge=e; float y=0;\n''' + half + '\n' + pos + '\n' + clamp + '''\n  assert(fabsf(sx-expected)<0.001f); assert(fabsf(mx-expected_clamped)<0.001f); (void)sy;\n}\nint main(void) {\n  check(0,0,320,320); check(0,1,640,20);\n  check(170.66667f,1,746.66667f,-86.66667f);\n  check(170.66667f,-1,-106.66667f,726.66667f);\n  return 0;\n}\n'''
# Wide viewport has half-width 320 + 170.66667 * (640/1024) = 426.66667.
base = os.environ.get('TMPDIR', '/Volumes/CodexWork')
with tempfile.TemporaryDirectory(prefix='wide-mark-test-', dir=base) as d:
    c, exe = Path(d)/'test.c', Path(d)/'test'
    c.write_text(source)
    subprocess.run(['cc', '-std=c99', '-Wall', '-Werror', str(c), '-lm', '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('Wide and 4:3 rival-marker projection expressions passed')
