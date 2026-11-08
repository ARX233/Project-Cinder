#!/usr/bin/env python3
"""Tests for tools/recomp/guard_sections.py and the generated physics it protects.

Two layers:
  * a synthetic C fragment that always runs (structure, failure modes, idempotence);
  * when the private generated src/phys/phys_rc.c is present (WMMT_PHYS_RC or the local
    control-layout project), the real Junction::MoveToPrev is patched, extracted and run
    against a fake emulated memory: index 0 stays put instead of reading array[-1], while
    index 1 and 2 still step back one area.  The Loop variant's wrapping is asserted to be
    byte-identical after patching.

Never touches the private project: the source is copied to a temporary directory.
"""
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUARD = ROOT / "ports/android/tools/recomp/guard_sections.py"
ITOA = ROOT / "ports/ipad/tools/recomp/guard_sections.py"
REAL = Path(os.environ.get("WMMT_PHYS_RC", ROOT.parent / "control-layout-v12/android/project/src/phys/phys_rc.c"))

SYNTH = """/* _ZN2yt22CAreaProcessorJunction10MoveToPrevERNS_18SAreaProcessorInfoE */
void f_89f8d9c(void) {
  /* Minimal synthetic markers for testing the patcher's pattern checks. */
  --ecx;  /* 89f8da5: dec ecx */
  eax = items[ecx];  /* 89f8daf: mov eax, dword ptr [eax + ecx*4] */
}
"""


def guard(path):
    return subprocess.run([sys.executable, str(GUARD), str(path)], capture_output=True, text=True)


def test_synthetic(tmp):
    src = tmp / "synth.c"
    src.write_text(SYNTH, encoding="utf-8")
    r = guard(src)
    assert r.returncode == 0, r.stderr
    once = src.read_text(encoding="utf-8")
    assert "PORT GUARD" in once and once.count("if (ecx == 0)") == 1
    r2 = guard(src)
    assert r2.returncode == 0 and "already guarded" in r2.stdout
    assert src.read_text(encoding="utf-8") == once
    # no matching function: must fail loudly, not silently pass
    other = tmp / "other.c"
    other.write_text("void f_1(void) {\n}\n", encoding="utf-8")
    assert guard(other).returncode == 2
    # truncated body: must fail
    bad = tmp / "bad.c"
    bad.write_text(SYNTH.replace("/* 89f8da5: dec ecx */", ""), encoding="utf-8")
    assert guard(bad).returncode == 2
    assert guard(bad).stderr


def function_text(text, signature):
    i = text.index(signature)
    j = text.find("\n}\n", i)
    assert j > 0
    return text[i:j + 3]


HARNESS = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uint32_t eax, ecx, edx, ebx, esp, ebp, esi, edi; } rc_cpu_t;
rc_cpu_t rc_cpu;
#define RC_ENTRY(a) ((void)0)
#define RC_FLAGS int CF = 0, ZF = 0, SF = 0, OF = 0, PF = 0; (void)CF; (void)ZF; (void)SF; (void)OF; (void)PF
#define RC_T(a) ((void)0)
static void rc_fail(const char *m) __attribute__((noreturn));
static void rc_fail(const char *m) { fprintf(stderr, "rc_fail: %s\n", m); exit(3); }

#define MEM_BASE 0x092f0000u
#define MEM_SIZE 0x00b50000u
static uint8_t mem[MEM_SIZE];
static uint32_t off(uint32_t a) {
  uint32_t o = a - MEM_BASE;
  if (o >= MEM_SIZE) { fprintf(stderr, "BADADDR %#x\n", a); exit(4); }
  return o;
}
static uint32_t M32(uint32_t a) { uint32_t v; memcpy(&v, mem + off(a), 4); return v; }
static void W32(uint32_t a, uint32_t v) { memcpy(mem + off(a), &v, 4); }
static float __attribute__((unused)) MF(uint32_t a) { float v; memcpy(&v, mem + off(a), 4); return v; }
static int parity(uint32_t r) {
  r &= 0xff; r ^= r >> 4; r ^= r >> 2; r ^= r >> 1; return !(r & 1);
}

__FUNC__

#define INFO 0x09940300u
#define PROC 0x09940200u
#define ARRAY 0x09940100u

static void setup(void) {
  memset(mem, 0, sizeof mem);
  W32(INFO, 0x11111111u);      /* area: sentinel */
  W32(INFO + 4, 0);            /* index */
  W32(PROC + 4, ARRAY);        /* this->array */
  W32(ARRAY - 4, 0x433e4e4au); /* array[-1]: the value seen in the crash */
  W32(ARRAY + 0, 0x092f2000u);
  W32(ARRAY + 4, 0x092f3000u);
  W32(ARRAY + 8, 0x092f4000u);
}

static void run(uint32_t index) {
  setup();
  W32(INFO + 4, index);
  uint32_t sp = 0x09e30000u;    /* emulated stack */
  W32(sp, 0u);                  /* return address */
  W32(sp + 4, PROC);
  W32(sp + 8, INFO);
  rc_cpu.esp = sp;
  rc_cpu.ebp = 0;
  f_89f8d9c();
  printf("in=%u index=%u area=%#x esp=%#x\n", index, M32(INFO + 4), M32(INFO), rc_cpu.esp);
  if (index == 0) {
    if (M32(INFO + 4) != 0 || M32(INFO) != 0x11111111u) { puts("FAIL index0 moved"); exit(1); }
    if (rc_cpu.esp != sp + 4) { puts("FAIL index0 stack"); exit(1); }
  } else {
    if (M32(INFO + 4) != index - 1) { puts("FAIL index"); exit(1); }
    if (M32(INFO) != 0x092f2000u + 0x1000u * (index - 1)) { puts("FAIL area"); exit(1); }
  }
}

int main(void) { run(0); run(1); run(2); puts("PASS guard"); return 0; }
"""


def run_real(tmp):
    if not REAL.is_file():
        print("skip: no private generated phys_rc.c at %s" % REAL)
        return
    work = tmp / "real"
    work.mkdir()
    patched = work / "phys_rc.c"
    shutil.copyfile(REAL, patched)
    original = shutil.copyfile(REAL, work / "orig.c")
    assert guard(patched).returncode == 0
    assert guard(patched).returncode == 0  # idempotent
    orig_text = Path(original).read_text(encoding="utf-8")
    new_text = patched.read_text(encoding="utf-8")
    loop = "void f_89f8cc0(void) {"
    assert function_text(orig_text, loop) == function_text(new_text, loop), "Loop MoveToPrev changed"
    body = function_text(new_text, "void f_89f8d9c(void) {")
    harness = work / "h.c"
    harness.write_text(HARNESS.replace("__FUNC__", body), encoding="utf-8")
    exe = work / "h"
    cc = ["cc", "-std=c11", "-O0", "-Wall", "-Wextra", "-Werror", str(harness), "-o", str(exe)]
    r = subprocess.run(cc, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    assert r.returncode == 0, (r.returncode, r.stdout[-2000:], r.stderr[-2000:])
    print(r.stdout.strip())


def main():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_synthetic(tmp)
        print("synthetic guard tests passed")
        run_real(tmp)


if __name__ == "__main__":
    main()
