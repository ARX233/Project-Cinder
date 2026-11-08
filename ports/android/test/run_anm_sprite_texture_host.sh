#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
out=$(mktemp -d /Volumes/CodexWork/anm-texture-test.XXXXXXXX)
export TMPDIR="$out"
# The test never uses the proprietary replacement; provide a no-op test fixture.
printf '%s\n' 'static void time_texture_fix(int i,int w,int h,unsigned char *p) {(void)i;(void)w;(void)h;(void)p;}' > "$out/time_texture.h"
"${CC:-clang}" -std=c99 -U__APPLE__ -DGL_FUNC_REVERSE_SUBTRACT=0x800b -ffunction-sections -fdata-sections -Wl,-dead_strip -I "$out" -I "$root/test" "$root/test/anm_sprite_texture_test.c" -lz -lm -o "$out/test"
"$out/test"
printf 'Output: %s\n' "$out"
