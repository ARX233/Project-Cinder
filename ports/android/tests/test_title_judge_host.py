"""Test real extracted title_judge with fake tables and list provider, not game assets."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
FIXTURE = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "title.h"
typedef struct { int bng, color, flags; } titledb_model;
static const titledb_model TITLEDB_MODELS[256] = {{0}};
/* Clang's 0xaaaa pattern is a valid fake ID, detecting missing initialization. */
#define TITLEDB_N 60000
#define NAMEDB_N 1
static const int NAMEDB_WCHAR[1] = { 65 };
static int supplied[3], fail, calls;
int car_title_list(const unsigned char *data, int n, int out[3]) {
    assert(data && n == 0x3b8 + 12 + 4 * 6);
    ++calls;
    if (fail) return 0; /* no output is written */
    memcpy(out, supplied, sizeof supplied);
    return 1;
}
'''
MAIN = r'''
static void check(int failure, int a, int b, int c, int current,
                  int count, int x, int y, int z) {
    title_play p = {0};
    int out[3] = { 123456, 234567, 345678 };
    fail = failure; supplied[0] = a; supplied[1] = b; supplied[2] = c;
    int before = calls;
    int actual = title_judge(&p, current, out);
    assert(calls == before + 1);
    assert(actual == count && out[0] == x && out[1] == y && out[2] == z);
}
int main(void) {
    check(1, 0, 0, 0, 0, 0, 0, 0, 0);
    check(0, 1, 2, 3, 0, 3, 1, 2, 3);
    check(0, 42, 42, 60000, 0, 1, 42, 0, 0);
    check(0, 0, -1, 5, 0, 1, 5, 0, 0);
    check(0, 7, 8, 7, 7, 1, 8, 0, 0);
    check(0, 0x10009, 9, 10, 10, 1, 9, 0, 0);
    check(0, 11, 12, 13, 12, 2, 11, 13, 0);
    puts("title_judge host checks passed");
    return 0;
}
'''

class TitleJudgeHost(unittest.TestCase):
    def test_real_function(self):
        source = (SRC / "title.c").read_text(encoding="utf-8")
        start = source.index("static const int TEN_SLOT[10]")
        end = source.index("\nint title_glyphs(", start)
        code = FIXTURE + "\n" + source[start:end] + "\n" + MAIN
        with tempfile.TemporaryDirectory(prefix="title-judge-host-") as tmp:
            cfile, binary = Path(tmp) / "test.c", Path(tmp) / "test"
            cfile.write_text(code, encoding="utf-8")
            subprocess.run([os.environ.get("CC", "clang"), "-std=c11", "-Wall",
                            "-Wextra", "-Werror", "-ftrivial-auto-var-init=pattern",
                            "-I", str(SRC), str(cfile), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

if __name__ == "__main__":
    unittest.main()
