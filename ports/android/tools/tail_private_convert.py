#!/usr/bin/env python3
"""Convert reviewed candidate JSON to private tail_trail_private_data.h.

Review schema: {"schema":"wmmt-tail-review","version":1,"main_sha256":SHA,
 "entries":[{"pack":NAME,"car_id":N,"body_id":N,"igb_sha256":SHA,
 "width_scale":FLOAT}]}.
The caller must independently review the pack/car/body/IGB relationship; the
hash binds that assertion but does not prove it. Candidates must come from a
trusted extractor. This tool does not read IGBs or discover assets/save files.
Use private stable directories: directory-FD/O_NOFOLLOW walking blocks symlink
substitution, but is not a sandbox against concurrent renames, file mutation,
hardlinks, or hostile filesystem operations. Output is exclusively created.
"""
import argparse
import hashlib
import json
import math
import os
import re
import stat
import struct
import sys

APPROVED = frozenset({'2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'})
BASE = 0x9770f20
SHA = re.compile(r'[0-9a-f]{64}\Z')
PACK = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_-]{0,63}\Z', re.ASCII)
MAX = 64 * 1024 * 1024

def parent(path):
    if not isinstance(path, str) or not path.startswith('/') or '\0' in path:
        raise ValueError('absolute path required')
    parts = path.split('/')[1:]
    if any(x in ('', '.', '..') for x in parts):
        raise ValueError('invalid path component')
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
        raise ValueError('secure path flags unavailable')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise

def read_file(path):
    d, n = parent(path)
    try:
        fd = os.open(n, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=d)
    finally:
        os.close(d)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX:
            raise ValueError('invalid input file')
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, min(1048576, MAX + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX:
                raise ValueError('input too large')
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or total != before.st_size:
            raise ValueError('input changed during read')
        return b''.join(chunks)
    finally:
        os.close(fd)

def pairs(items):
    result = {}
    for k, v in items:
        if k in result:
            raise ValueError('duplicate JSON key')
        result[k] = v
    return result

def parse(data):
    def reject(_):
        raise ValueError('nonfinite JSON')
    return json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=reject)

def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError('unexpected object schema')

def num(v):
    if type(v) not in (float, int) or not math.isfinite(v):
        raise ValueError('finite number required')
    v = float(v)
    if abs(v) > 3.4028234663852886e38:
        raise ValueError('float overflow')
    return v

def identity(car, body):
    if type(car) is not int or not 0 <= car <= 106 or type(body) is not int or not 0 <= body <= 3:
        raise ValueError('invalid car/body')
    return car, body

def widths(data, ids):
    if len(data) < 52 or data[:4] != b'\x7fELF' or data[5:7] != b'\x01\x01':
        raise ValueError('invalid little endian ELF')
    if data[4] == 1:
        phoff = struct.unpack_from('<I', data, 28)[0]
        entsize, count = struct.unpack_from('<HH', data, 42)
        need, fmt = 32, '<IIIIIIII'
    elif data[4] == 2 and len(data) >= 64:
        phoff = struct.unpack_from('<Q', data, 32)[0]
        entsize, count = struct.unpack_from('<HH', data, 54)
        need, fmt = 56, '<IIQQQQQQ'
    else:
        raise ValueError('unsupported ELF class')
    if entsize < need or not count or count == 65535 or phoff + entsize * count > len(data):
        raise ValueError('invalid program headers')
    segments = []
    for i in range(count):
        r = struct.unpack_from(fmt, data, phoff + i * entsize)
        if r[0] != 1:
            continue
        if data[4] == 1:
            _, off, va, _, filesz, memsz, _, _ = r
        else:
            _, _, off, va, _, filesz, memsz, _ = r
        if filesz > memsz or off + filesz > len(data):
            raise ValueError('invalid PT_LOAD')
        segments.append((off, va, filesz))
    result = {}
    for car in ids:
        addr = BASE + car * 4
        offsets = [off + addr - va for off, va, size in segments if va <= addr and addr + 4 <= va + size]
        if len(offsets) != 1:
            raise ValueError('width VA not uniquely file-backed')
        v = struct.unpack_from('<f', data, offsets[0])[0]
        if not math.isfinite(v) or not 0 < v <= 100:
            raise ValueError('unreasonable width')
        result[car] = v
    return result

def convert(candidate, review, elf, approved=APPROVED):
    keys(candidate, ('schema','version','matrix_layout','space','records'))
    if (candidate['schema'], candidate['version'], candidate['matrix_layout'], candidate['space']) != ('wmmt-tail-anchors',1,'row-major-row-vector','scene-root-parent; ancestors identity') or type(candidate['version']) is not int:
        raise ValueError('unsupported candidate schema')
    keys(review, ('schema','version','main_sha256','entries'))
    digest = review['main_sha256']
    if review['schema'] != 'wmmt-tail-review' or type(review['version']) is not int or review['version'] != 1:
        raise ValueError('unsupported review schema')
    if not isinstance(digest, str) or not SHA.fullmatch(digest) or digest not in approved or hashlib.sha256(elf).hexdigest() != digest:
        raise ValueError('main not explicitly approved or digest mismatch')
    records, entries = candidate['records'], review['entries']
    if not isinstance(records, list) or not isinstance(entries, list) or not records or len(records) != len(entries) or len(records) > 428:
        raise ValueError('invalid record count')
    candidates = {}
    for rec in records:
        keys(rec, ('car_id','body_id','source_sha256','anchors'))
        k = identity(rec['car_id'], rec['body_id'])
        sha = rec['source_sha256']
        if k in candidates or not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise ValueError('duplicate candidate or bad SHA')
        keys(rec['anchors'], ('TAIL_L1','TAIL_R1'))
        mats, paths = [], []
        for side in ('TAIL_L1','TAIL_R1'):
            a = rec['anchors'][side]
            keys(a, ('matrix','instance_path'))
            path, m = a['instance_path'], a['matrix']
            if not isinstance(path, list) or len(path) > 256 or any(type(x) is not int or not 0 <= x <= 65535 for x in path):
                raise ValueError('invalid instance path')
            if not isinstance(m, list) or len(m) != 16:
                raise ValueError('expected 16 matrix elements')
            m = list(map(num, m))
            if (m[3],m[7],m[11],m[15]) != (0.,0.,0.,1.) or not any(m[4:7]):
                raise ValueError('invalid affine matrix or axis')
            mats.append(m); paths.append(path)
        if paths[0] == paths[1]:
            raise ValueError('duplicate light instance')
        candidates[k] = (sha, mats)
    rows, seen_k, seen_p = [], set(), set()
    for e in entries:
        keys(e, ('pack','car_id','body_id','igb_sha256','width_scale'))
        k = identity(e['car_id'], e['body_id'])
        pack = e['pack']
        if not isinstance(pack, str) or not PACK.fullmatch(pack) or (pack, k[1]) in seen_p or k in seen_k or k not in candidates:
            raise ValueError('unsafe or duplicate mapping')
        seen_p.add((pack,k[1])); seen_k.add(k)
        sha, mats = candidates[k]
        if not isinstance(e['igb_sha256'], str) or not SHA.fullmatch(e['igb_sha256']) or e['igb_sha256'] != sha:
            raise ValueError('IGB SHA mismatch')
        rows.append((pack,k,mats,num(e['width_scale'])))
    original = widths(elf, {k[0] for _,k,_,_ in rows})
    for _, k, _, width in rows:
        if width != original[k[0]]:
            raise ValueError('width differs from original float')
    def f(v): return format(v, '.17e') + 'f'
    def vec(v): return '{' + ', '.join(map(f,v)) + '}'
    out = ['/* Private data; mapping requires independent review. */', '#ifndef TAIL_TRAIL_PRIVATE_DATA_H', '#define TAIL_TRAIL_PRIVATE_DATA_H', '#include "tail_trail_data.h"', 'static const TailTrailDataRecord tail_trail_data[] = {']
    for pack, (_, body), mats, width in sorted(rows):
        out.append('    {"%s", %du, {%s}, {%s}, %s},' % (pack,body,', '.join(vec(m[12:15]) for m in mats),', '.join(vec(m[4:7]) for m in mats),f(width)))
    out += ['};','#define TAIL_TRAIL_DATA_COUNT (sizeof(tail_trail_data)/sizeof(tail_trail_data[0]))','#endif','']
    return '\n'.join(out).encode('ascii')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('candidate'); p.add_argument('review'); p.add_argument('main_elf'); p.add_argument('output')
    a = p.parse_args()
    if not a.candidate.endswith('.json') or not a.review.endswith('.json') or not a.output.endswith('/tail_trail_private_data.h'):
        raise ValueError('expected JSON inputs and tail_trail_private_data.h output')
    payload = convert(parse(read_file(a.candidate)),parse(read_file(a.review)),read_file(a.main_elf))
    d,n = parent(a.output)
    try:
        fd = os.open(n, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=d)
        with os.fdopen(fd, 'wb') as out:
            out.write(payload)
    finally:
        os.close(d)

if __name__ == '__main__':
    try:
        main()
    except (ValueError,OSError,UnicodeError,struct.error,OverflowError,RecursionError) as exc:
        print('tail conversion failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
