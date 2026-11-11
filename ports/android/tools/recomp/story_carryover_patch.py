#!/usr/bin/env python3
"""Generate a private experimental physics C file, never modify the input.

Output requires the memory-only story carryover callbacks in car.c. The bridge
marker prevents a legacy unpatched physics image from entering CSeq::End.
"""
import argparse
import hashlib
import os
from pathlib import Path
import stat

EXPECTED = "8b5885738fb46c23ce71fb89fa70f25d1a201fd2e5d76ed79d9627a9c17c0170"
ROOT = Path("/Volumes/CodexWork")
INCLUDE = b'#include "rc_runtime.h"'
DECLS = (INCLUDE + b"\nextern void rc_story_carry_save(void);\n"
         b"extern void rc_story_carry_load(void);\n"
         b"const volatile uint32_t rc_story_carry_bridge = 0x53544331u;")
HOOKS = ((b"8997bc8", b"rc_story_carry_save"), (b"8997edc", b"rc_story_carry_load"))


def patch(source):
    if hashlib.sha256(source).hexdigest() != EXPECTED:
        raise ValueError("unexpected input hash")
    if source.count(INCLUDE) != 1:
        raise ValueError("unexpected include count")
    result = source.replace(INCLUDE, DECLS, 1)
    for address, callback in HOOKS:
        old = b"void f_" + address + b"(void) {\n  RC_ENTRY(0x" + address + b"u);"
        new = b"void f_" + address + b"(void) {\n  " + callback + b"(); return;\n  RC_ENTRY(0x" + address + b"u);"
        if result.count(old) != 1:
            raise ValueError("unexpected entry count")
        result = result.replace(old, new, 1)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if ROOT.resolve(strict=True) != ROOT:
        raise ValueError("unexpected private root")
    source = args.input.resolve(strict=True)
    parent = args.output.parent.resolve(strict=True)
    if not source.is_relative_to(ROOT) or not parent.is_relative_to(ROOT):
        raise ValueError("input and output must be under /Volumes/CodexWork")
    if stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise ValueError("output directory must be private (0700)")
    if not source.is_file():
        raise ValueError("input is not a regular file")
    result = patch(source.read_bytes())
    dirfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(args.output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
        with os.fdopen(fd, "wb") as out:
            out.write(result)
    finally:
        os.close(dirfd)
    print("private output created")


if __name__ == "__main__":
    main()
