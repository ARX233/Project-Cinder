#!/usr/bin/env python3
"""Host-only resource validation. Checksums detect damage, not authenticity.
Only explicitly reviewed catalog/metadata inputs define trusted content.
No APK, launcher, or original arcade executable is ever executed.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import hashlib
import io
import json
import os
from pathlib import Path, PurePath, PureWindowsPath
import re
import stat
import struct
import unicodedata
import zipfile
import zlib

BLOCK = 1024 * 1024
MAX_APK = 2 * 1024**3
MAX_MAIN_TOTAL = 3 * 1024**3
MAX_FILE = 512 * 1024**2
MAX_CARD_TOTAL = 110_000_000
MAX_SIDECAR_TOTAL = 256 * 1024**2
MAX_CATALOG = 16 * 1024**2
MAX_DMF = 2 * 1024**2
MAX_INDEX = 64 * 1024
MAIN_COUNT = 1798
HEADER = b'WMMT-SIDECARS-1\n'
KNOWN_BASELINES = frozenset({
    '4f5d55802f46c010a2db383e758ee3917f85c029a956278f5b564f856a7a3e59',
    'a8870bc3f299292af952f456f0c504d231cd858ae7e1b36db3e9096c3d87f7b6',
})
PREPARED_BASELINE = '6d3aae6449c49fcd81a3b44e2747ebb873cca1696783cf76a890c1443ed72643'
PREPARED_DMF_SHA256 = '1be750eaa10e88b0322a32cf2e267d0fbb84066205153d90b722ee963c8c84f4'
TOP4 = ('story-cutin.bin', 'card-pages.bin', 'backfire.wpk', 'backfire.bfx')
CARD_PATHS = frozenset({'manifest.json', 'meters-v2.bin'} |
                       {f'bgm-extra/wm2_{n:02}.m4a' for n in range(1, 24)} |
                       {f'bgm-extra/wmr_{n:02}.m4a' for n in range(1, 13)})
SIDECAR_PATHS = frozenset(TOP4) | frozenset('card-resources/' + p for p in CARD_PATHS)
HASH = re.compile(r'[0-9a-f]{64}\Z')

class ResourceError(ValueError):
    """Invalid input, unsupported format, or exhausted safety budget."""

def require(ok, message):
    if not ok:
        raise ResourceError(message)

def sha256(stream):
    h = hashlib.sha256()
    stream.seek(0)
    for block in iter(lambda: stream.read(BLOCK), b''):
        h.update(block)
    stream.seek(0)
    return h.hexdigest()

def file_sha256(path):
    with open(path, 'rb') as stream:
        return sha256(stream)

def safe_path(name, directory=False):
    require(isinstance(name, str) and 0 < len(name.encode('utf-8')) <= 65535,
            'invalid path length')
    require(not name.startswith('/') and '\\' not in name and ':' not in name,
            'unsafe path')
    require(not any(unicodedata.category(c).startswith('C') for c in name),
            'control or surrogate in path')
    require(unicodedata.normalize('NFC', name) == name, 'non-NFC path')
    path = name[:-1] if directory and name.endswith('/') else name
    require(bool(path) and not path.endswith('/'), 'empty path component')
    for part in path.split('/'):
        require(part not in ('', '.', '..') and not part.endswith((' ', '.')),
                'unsafe path component')
        require(part.casefold() not in ('mods', 'wmmt', '.wmmt-data-manifest',
                                        '.re3dxplus-install-v1') and
                not part.casefold().startswith('.overlay-'), 'reserved path component')
    return path

def path_inventory(names):
    """Check file/directory aliases, including implicit parent directories."""
    spellings, kinds = {}, {}
    for name, directory in names:
        key = safe_path(name, directory)
        parts = key.split('/')
        for n in range(1, len(parts) + 1):
            spelling = '/'.join(parts[:n])
            folded = unicodedata.normalize('NFC', spelling).casefold()
            require(folded not in spellings or spellings[folded] == spelling,
                    'NFC/casefold path collision')
            spellings[folded] = spelling
            kind = directory if n == len(parts) else True
            require(folded not in kinds or kinds[folded] == kind,
                    'file/directory path conflict')
            kinds[folded] = kind

def resource_path(name):
    """A mistaken catalog must not authorize executable/save paths."""
    safe_path(name)
    parts = [p.casefold() for p in name.split('/')]
    base = parts[-1]
    require(not any(p in ('lib', 'lib64', 'meta-inf', 'save', 'saves', 'savedata',
                              'data', 'assets', 'launcher') for p in parts),
            'code, player save, or non-flat resource path')
    require(base not in ('main', 'androidmanifest.xml') and not base.startswith('launcher') and
            not re.fullmatch(r'classes\d*\.dex', base) and
            not base.endswith(('.dex', '.so', '.dll', '.exe', '.apk', '.jar', '.class',
                               '.elf', '.sh', '.bat', '.cmd', '.ps1', '.py', '.lua',
                               '.sav', '.save', '.db', '.sqlite', '.sqlite3')),
            'executable, launcher, or player save forbidden')

def validate_output_shape(path):
    """Pure native-flavour path checks; tests may also pass PureWindowsPath.

    Never reinterpret a Windows path as an absolute POSIX path (or vice versa).
    The caller must explicitly choose a native absolute destination, not an
    implicit cwd/home/temp location. No filesystem reads or writes occur here.
    """
    require(isinstance(path, PurePath) and path.is_absolute() and
            path.name not in ('', '.', '..') and '..' not in path.parts,
            'output must be an explicit absolute path without parent traversal')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in str(path)),
            'control character in output path')
    if isinstance(path, PureWindowsPath):
        require(not path.drive.startswith(('\\\\?\\', '\\\\.\\')),
                'Windows device/extended namespace output paths are unsupported')
        for part in path.parts[1:]:  # Skip the drive or UNC share anchor.
            require(not any(c in '<>:\"|?*' for c in part) and
                    not part.endswith((' ', '.')),
                    'unsafe Windows output component or alternate data stream')
            device = part.split('.')[0].rstrip(' ').upper()
            require(device not in ('CON', 'PRN', 'AUX', 'NUL') and
                    not re.fullmatch(r'(COM|LPT)[1-9\u00b9\u00b2\u00b3]', device),
                    'reserved Windows output device name')
    return path


def is_link_or_reparse(info):
    # Windows junctions/reparse points need rejection even when is_symlink is
    # false. POSIX stat results lack st_file_attributes and simply use mode.
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) &
        getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def check_output_parent(parent, probe=os.lstat):
    """Require every existing parent to be a non-link directory; never mkdir.

    probe injection is for pure Windows-equivalent host tests, not a CLI knob.
    Do not resolve symlinks before checking: that would silently accept aliases.
    """
    for part in reversed((parent, *parent.parents)):
        info = probe(part)
        require(not is_link_or_reparse(info) and stat.S_ISDIR(info.st_mode),
                'output parent chain must be existing non-symlink directories')
    return parent


def new_output(requested):
    path = Path(requested)
    validate_output_shape(path)
    check_output_parent(path.parent)
    require(not os.path.lexists(path), 'output already exists: ' + str(path))
    return path


def external_destination(requested):
    """Compatibility name; no machine-specific output volume restriction."""
    return new_output(requested)


def publish_exclusive(source, destination, expected):
    """Portable no-replace publication without hard links, rename or deletion.

    A failed write leaves only this call's newly created (possibly partial)
    destination for review. The caller must not report success or retry that
    name. O_EXCL/'xb' also refuses existing and dangling symlink destinations.
    """
    target = new_output(destination)  # Recheck the parent and leaf at commit time.
    with regular_input(source, expected.size) as stream, target.open('xb') as out:
        os.chmod(target, 0o600)
        count, digest = 0, hashlib.sha256()
        for block in iter(lambda: stream.read(BLOCK), b''):
            count += len(block)
            require(count <= expected.size, 'publication source byte budget')
            digest.update(block)
            out.write(block)
        require(count == expected.size and digest.hexdigest() == expected.sha256,
                'publication source changed or failed integrity check')
        out.flush()
        os.fsync(out.fileno())
    return target

def private_directory(path):
    path.mkdir(mode=0o700)  # Exclusive; retain failed runs, never delete user data.
    return path

def write_json_exclusive(path, value):
    with open(path, 'x', encoding='utf-8') as out:
        os.chmod(path, 0o600)
        json.dump(value, out, indent=2, sort_keys=True, ensure_ascii=True)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())

@contextmanager
def regular_input(path, max_bytes):
    path = Path(path).absolute()
    selected = path.lstat()
    if is_link_or_reparse(selected):
        raise OSError(errno.ELOOP, 'source symlink/reparse point refused', str(path))
    require(stat.S_ISREG(selected.st_mode) and selected.st_size <= max_bytes,
            'input is not a bounded regular file')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= max_bytes and
                (selected.st_dev, selected.st_ino) == (before.st_dev, before.st_ino),
                'input is not a bounded stable regular file')
        yield stream
        after = os.fstat(stream.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                 before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                 after.st_ctime_ns), 'source changed during inspection')

@dataclass(frozen=True)
class Entry:
    size: int
    sha256: str

@dataclass(frozen=True)
class Manifest:
    zip_sha256: str
    directory: str
    canonical_id: str
    files: dict[str, Entry]

class StrictZip:
    """Bind ordinary ZIP central records to local headers and bounded reads.

    Reject ZIP64/multidisk/encryption/links/special files, overlapping ranges,
    hidden locals, trailing bytes, unknown gaps and Unicode path overrides.
    APK mode permits one structurally valid APK Signing Block before central
    data; this is NOT cryptographic APK signature verification.
    """
    def __init__(self, stream, *, max_bytes, max_entries, max_total, max_file=MAX_FILE,
                 apk=False):
        self.stream, self.zip = stream, None
        stream.seek(0, 2)
        size = stream.tell()
        require(22 <= size <= max_bytes, 'ZIP archive byte budget')
        tail_start = max(0, size - 65557)
        tail = self._at(tail_start, size - tail_start)
        candidates = []
        for n in range(len(tail) - 22, -1, -1):
            if tail[n:n+4] == b'PK\x05\x06' and n + 22 + struct.unpack_from('<H', tail, n+20)[0] == len(tail):
                candidates.append(n)
        require(len(candidates) == 1, 'missing, ambiguous, or trailing ZIP end record')
        end = tail_start + candidates[0]
        _, disk, cd_disk, disk_count, count, cd_size, central, _ = struct.unpack(
            '<4s4H2IH', self._at(end, 22))
        require(disk == cd_disk == 0 and disk_count == count and
                0 < count <= max_entries and count != 65535 and
                cd_size != 0xffffffff and central != 0xffffffff and
                central + cd_size == end and cd_size <= 16 * 1024**2,
                'unsupported ZIP end/central directory')
        central_bytes = self._at(central, cd_size)
        at, total, records, seen = 0, 0, [], set()
        for _ in range(count):
            require(at + 46 <= len(central_bytes), 'truncated central directory')
            c = struct.unpack_from('<4s6H3I5H2I', central_bytes, at)
            (magic, made, needed, flags, method, tm, dt, crc, packed, length,
             n, ex, comment, disk_no, internal, attrs, offset) = c
            require(magic == b'PK\x01\x02' and at + 46 + n + ex + comment <= len(central_bytes),
                    'invalid central directory')
            require(needed <= 20 and flags & ~0x080e == 0 and method in (0, 8) and
                    (method != 0 or flags & 6 == 0) and disk_no == 0 and
                    packed != 0xffffffff and offset != 0xffffffff and
                    length <= max_file and offset < central,
                    'unsupported ZIP member flags, method, or size')
            require(method != 0 or packed == length, 'stored ZIP size mismatch')
            raw_name = central_bytes[at+46:at+46+n]
            try:
                name = raw_name.decode('utf-8' if flags & 0x800 else 'cp437', 'strict')
            except UnicodeError as exc:
                raise ResourceError('invalid ZIP filename encoding') from exc
            directory = name.endswith('/')
            key = safe_path(name, directory)
            require(key not in seen, 'duplicate ZIP path')
            seen.add(key)
            mode = attrs >> 16
            kind = stat.S_IFMT(mode)
            require(kind in (0, stat.S_IFDIR if directory else stat.S_IFREG),
                    'ZIP symlink or special file forbidden')
            require(not directory or length == 0, 'directory contains data')
            require(not attrs & 0x10 or directory, 'directory attribute/name mismatch')
            total += length
            require(total <= max_total, 'ZIP expanded byte budget')
            self._extras(central_bytes[at+46+n:at+46+n+ex])
            records.append((name, raw_name, flags, method, tm, dt, crc, packed, length, offset))
            at += 46 + n + ex + comment
        require(at == cd_size, 'unrecognized central directory data')
        path_inventory((r[0], r[0].endswith('/')) for r in records)
        next_offset = 0
        for name, raw_name, flags, method, tm, dt, crc, packed, length, offset in sorted(records, key=lambda r: r[-1]):
            require(offset == next_offset and offset + 30 <= central,
                    'ZIP hidden, overlapping, or noncontiguous local data')
            magic, needed, lf, lm, lt, ld, lc, lp, ll, n, ex = struct.unpack(
                '<4s5H3I2H', self._at(offset, 30))
            require(magic == b'PK\x03\x04' and needed <= 20 and
                    (lf, lm, lt, ld) == (flags, method, tm, dt) and n == len(raw_name),
                    'ZIP local/central header mismatch')
            require(offset + 30 + n + ex <= central and
                    self._at(offset + 30, n) == raw_name, 'ZIP local/central name mismatch')
            self._extras(self._at(offset + 30 + n, ex), allow_zero_padding=apk)
            descriptor = flags & 8
            require((all(a in (0, b) for a, b in zip((lc, lp, ll), (crc, packed, length)))
                     if descriptor else (lc, lp, ll) == (crc, packed, length)),
                    'ZIP local/central CRC or size mismatch')
            next_offset = offset + 30 + n + ex + packed
            require(next_offset <= central, 'truncated ZIP compressed member')
            if descriptor:
                require(next_offset + 12 <= central, 'truncated ZIP descriptor')
                signature = self._at(next_offset, 4) == b'PK\x07\x08'
                d = next_offset + (4 if signature else 0)
                require(d + 12 <= central and struct.unpack('<3I', self._at(d, 12)) ==
                        (crc, packed, length), 'ZIP descriptor mismatch')
                next_offset = d + 12
        if next_offset != central:
            require(apk, 'unrecognized ZIP local data before central directory')
            self._apk_block(next_offset, central)
        try:
            self.zip = zipfile.ZipFile(stream)
            infos = self.zip.infolist()
            require(len(infos) == count and self.zip.start_dir == central,
                    'ZIP decoder central directory disagreement')
            self.files = {}
            for info, record in zip(infos, records):
                name, _, flags, method, _, _, crc, packed, length, offset = record
                require((info.filename, info.flag_bits, info.compress_type, info.CRC,
                         info.compress_size, info.file_size, info.header_offset) ==
                        (name, flags, method, crc, packed, length, offset),
                        'ZIP decoder member disagreement')
                if not info.is_dir():
                    self.files[name] = info
            for info in infos:
                if info.is_dir():
                    self.consume(info.filename, limit=0)
        except Exception:
            self.close()
            raise

    def _at(self, offset, length):
        self.stream.seek(offset)
        data = self.stream.read(length)
        require(len(data) == length, 'truncated ZIP structure')
        return data

    @staticmethod
    def _extras(data, allow_zero_padding=False):
        at, seen = 0, set()
        while at < len(data):
            # Android zipalign pads native-library LOCAL extras with literal zeros.
            # Permit exactly that bounded padding only for the outer APK, never
            # central records or the nested resource/catalog ZIPs.
            if allow_zero_padding and not any(data[at:]):
                return
            require(at + 4 <= len(data), 'truncated ZIP extra field')
            kind, size = struct.unpack_from('<HH', data, at)
            if allow_zero_padding and kind == size == 0:
                at += 4  # Legacy zipalign zero TLVs can precede its 0xd935 field.
                continue
            require(kind not in seen and at + 4 + size <= len(data), 'duplicate/truncated ZIP extra')
            require(kind not in (1, 0x7075, 0x9901, 0x000f, 0x0017), 'unsupported ZIP extra')
            seen.add(kind)
            at += 4 + size

    def _apk_block(self, start, end):
        require(32 <= end - start <= 16 * 1024**2, 'invalid APK signing gap')
        footer = self._at(end - 24, 24)
        require(footer[8:] == b'APK Sig Block 42', 'unknown APK signing gap')
        size = struct.unpack('<Q', footer[:8])[0]
        block_start = end - size - 8
        padding = block_start - start
        require(0 <= padding <= 4095 and
                (padding == 0 or (block_start % 4096 == 0 and not any(self._at(start, padding)))) and
                size >= 24 and size == struct.unpack('<Q', self._at(block_start, 8))[0],
                'APK signing block size or page-alignment padding mismatch')
        at, seen = block_start + 8, set()
        while at < end - 24:
            require(at + 12 <= end - 24, 'truncated APK signing pair')
            length, key = struct.unpack('<QI', self._at(at, 12))
            require(length >= 4 and at + 8 + length <= end - 24 and key not in seen,
                    'invalid/duplicate APK signing pair')
            seen.add(key)
            at += 8 + length
        require(at == end - 24 and seen, 'empty or malformed APK signing block')

    def consume(self, name, *, limit, output=None, expected=None):
        info = self.zip.getinfo(name)
        require(info.file_size <= limit, 'member byte budget: ' + name)
        if expected is not None:
            require(info.file_size == expected.size, 'resource size mismatch: ' + name)
        # Enforce the declared size during inflation, not only after EOF. A tiny
        # forged declaration must not buy a 512 MiB decompression attempt.
        limit = min(limit, info.file_size)
        h, count, crc = hashlib.sha256(), 0, 0
        local = self._at(info.header_offset, 30)
        n, ex = struct.unpack_from('<HH', local, 26)
        self.stream.seek(info.header_offset + 30 + n + ex)
        remaining = info.compress_size
        decoder = zlib.decompressobj(-15) if info.compress_type == 8 else None
        while remaining:
            packed = self.stream.read(min(BLOCK, remaining))
            require(bool(packed), 'truncated compressed resource: ' + name)
            remaining -= len(packed)
            while packed:
                if decoder is not None:
                    block = decoder.decompress(packed, min(BLOCK, limit - count + 1))
                    require(not decoder.unused_data, 'trailing compressed stream data: ' + name)
                    packed = decoder.unconsumed_tail
                else:
                    block, packed = packed, b''
                count += len(block)
                require(count <= limit, 'expanded member byte budget: ' + name)
                h.update(block)
                crc = zlib.crc32(block, crc)
                if output is not None:
                    output.write(block)
        require(decoder is None or decoder.eof, 'incomplete deflate stream: ' + name)
        require(count == info.file_size and crc == info.CRC, 'resource CRC/length mismatch: ' + name)
        observed = Entry(count, h.hexdigest())
        if expected is not None:
            require(observed == expected, 'resource SHA-256 mismatch: ' + name)
        return observed

    def read(self, name, limit):
        out = io.BytesIO()
        self.consume(name, limit=limit, output=out)
        return out.getvalue()

    def close(self):
        if self.zip is not None:
            self.zip.close()
            self.zip = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

def parse_dmf(data, *, expected_count=MAIN_COUNT):
    require(40 <= len(data) <= MAX_DMF, 'DMF byte budget')
    body = data[:-32]
    require(hashlib.sha256(body).digest() == data[-32:], 'DMF checksum mismatch')
    at = 0
    def take(n):
        nonlocal at
        require(0 <= n <= len(body) - at, 'truncated DMF')
        result = body[at:at+n]
        at += n
        return result
    def integer(fmt):
        return struct.unpack(fmt, take(struct.calcsize(fmt)))[0]
    def text():
        n = integer('>i')
        require(0 < n <= 65535, 'invalid DMF string length')
        try:
            value = take(n).decode('utf-8', 'strict')
        except UnicodeError as exc:
            raise ResourceError('invalid DMF UTF-8') from exc
        require(not any(ord(c) > 0xffff or unicodedata.category(c).startswith('C') for c in value),
                'invalid DMF text character')
        return value
    require(take(8) == b'DMF1\x00\x00\x00\x01', 'unknown DMF version')
    archive_hash, directory, canonical_id = text(), text(), text()
    require(HASH.fullmatch(archive_hash), 'invalid DMF archive SHA-256')
    safe_path(directory)
    require('/' not in directory and canonical_id == 're3dxplus-data-v1', 'DMF identity mismatch')
    count = integer('>i')
    require(count == expected_count, 'unexpected main catalog file count')
    files, previous, total = {}, None, 0
    for _ in range(count):
        name, size, digest = text(), integer('>q'), text()
        resource_path(name)
        require(previous is None or previous < name, 'unsorted/duplicate DMF path')
        require(0 <= size <= MAX_FILE and HASH.fullmatch(digest), 'invalid DMF entry')
        total += size
        require(total <= MAX_MAIN_TOTAL, 'DMF expanded byte budget')
        files[name] = Entry(size, digest)
        previous = name
    require(take(4) == b'END!' and at == len(body), 'DMF incomplete or trailing data')
    path_inventory((p, False) for p in files)
    return Manifest(archive_hash, directory, canonical_id, files)

def load_catalog(stream, *, allow_prepared=False):
    with StrictZip(stream, max_bytes=MAX_CATALOG, max_entries=16,
                   max_total=MAX_CATALOG, max_file=MAX_DMF) as archive:
        require(len(archive.zip.infolist()) == len(archive.files), 'catalog directories forbidden')
        manifests = {}
        for name in archive.files:
            require(re.fullmatch(r'[0-9a-f]{64}\.dmf', name), 'unknown catalog member')
            pin = name[:-4]
            require(pin in KNOWN_BASELINES or (allow_prepared and pin == PREPARED_BASELINE),
                    'unreviewed baseline identity')
            data = archive.read(name, MAX_DMF)
            if pin in KNOWN_BASELINES:
                manifest = parse_dmf(data)
            else:
                require(hashlib.sha256(data).hexdigest() == PREPARED_DMF_SHA256,
                        'prepared resource manifest differs from the reviewed inventory')
                manifest = parse_dmf(data, expected_count=1801)
            require(manifest.zip_sha256 == pin, 'catalog/DMF identity mismatch')
            manifests[pin] = manifest
        require(bool(manifests), 'empty catalog')
        return manifests

def parse_sidecars(data):
    require(0 < len(data) <= MAX_INDEX and data.startswith(HEADER) and data.endswith(b'\n'),
            'invalid sidecar header, newline, or byte budget')
    try:
        text = data.decode('utf-8', 'strict')
    except UnicodeError as exc:
        raise ResourceError('invalid sidecar UTF-8') from exc
    rows = text.split('\n')[1:-1]
    require(0 < len(rows) <= 512, 'sidecar entry budget')
    files, previous, total = {}, None, 0
    for row in rows:
        fields = row.split('\t')
        require(len(fields) == 3, 'invalid sidecar row')
        path, size, digest = fields
        require(path in SIDECAR_PATHS and (previous is None or previous < path),
                'unknown/unsorted/duplicate sidecar path')
        require(re.fullmatch(r'0|[1-9][0-9]{0,9}', size) and HASH.fullmatch(digest),
                'invalid sidecar size/hash')
        length = int(size)
        require(length <= MAX_FILE, 'sidecar file budget')
        total += length
        require(total <= MAX_SIDECAR_TOTAL, 'sidecar total byte budget')
        files[path] = Entry(length, digest)
        previous = path
    require(files.keys() == SIDECAR_PATHS, 'sidecar index must contain all 41 approved paths')
    return files

def encode_sidecars(files):
    data = HEADER + ''.join(f'{p}\t{e.size}\t{e.sha256}\n' for p, e in sorted(files.items())).encode('utf-8')
    require(parse_sidecars(data) == files, 'sidecar metadata roundtrip')
    return data

def copy_member(archive, name, destination, limit, expected=None):
    with open(destination, 'xb') as target:
        os.chmod(destination, 0o600)
        entry = archive.consume(name, limit=limit, output=target, expected=expected)
        target.flush()
        os.fsync(target.fileno())
    return entry

def deterministic_info(path):
    info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.extra = b''
    info.comment = b''
    info._compresslevel = 6
    return info
