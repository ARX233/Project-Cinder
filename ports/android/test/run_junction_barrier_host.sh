#!/bin/sh
set -eu
# All compiler outputs and temporary files stay in a fresh external directory.
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
out=$(mktemp -d /Volumes/CodexWork/junction-barrier.XXXXXXXX)
export TMPDIR="$out"
"${CC:-cc}" -std=c99 -U__APPLE__ -I "$root/test" -Wall -Wextra -Werror -pedantic "$root/src/junction_barrier.c" "$root/test/junction_barrier_test.c" -lm -o "$out/junction_barrier_test"
"$out/junction_barrier_test"
printf 'Output directory: %s\n' "$out"
