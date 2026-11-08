#!/usr/bin/env python3
"""Compile actual HUD input/layout source in isolation, without generated renderer assets."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
s = (root / 'src/hud.c').read_text()
prefix = s[s.index('typedef struct { float x, y, w, h; } rect;'):s.index('/* ---- drawing ---- */')]
a = prefix.index("/* the projection of the layout")
b = prefix.index("/* the gyro's dead zone", a)
prefix = prefix[:a] + prefix[b:]
layout = s[s.index('static rect group_rect(int group, int gyro) {'):s.index('void hud_draw_layout_mode(')]
with tempfile.TemporaryDirectory(prefix='hud-steering-', dir='/Volumes/CodexWork') as td:
    td = Path(td)
    (td / 'hud_steering_extracted.h').write_text(prefix + '\n' + layout)
    exe = td / 'hud_steering_test'
    subprocess.run(['cc', '-std=gnu11', '-I', str(root / 'src'), '-I', str(td),
                    str(root / 'tests/hud_steering_test.c'), '-lm', '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
