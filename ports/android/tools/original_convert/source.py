"""Bounded read-only source lane for original-resource conversion.

The expected read-set digest must come from the signed app recipe, never from a
player-supplied receipt or a digest computed by the importer itself. This module
cannot publish resources or manufacture a ResourceStore.Ready.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
import unicodedata
import uuid

MAIN_SHA256 = '2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
MAX_READSET_BYTES = 4 * 1024 * 1024
MAX_FILES = 16384
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024 * 1024
BLOCK = 128 * 1024
HASH = re.compile(r'[0-9a-f]{64}\Z')


class OriginalInputError(IOError):
    pass


class ConversionCancelled(OriginalInputError):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel():
        raise ConversionCancelled('Original resource conversion cancelled')


def source_path(name):
    if not isinstance(name, str) or not name or len(name) > 4096:
        raise OriginalInputError('Invalid original path length')
    if name != unicodedata.normalize('NFC', name) or '\\' in name or ':' in name:
        raise OriginalInputError('Noncanonical original path')
    parts = name.split('/')
    if len(parts) > 64 or any(not p or p in ('.', '..') or p[-1] in ' .' for p in parts):
        raise OriginalInputError('Unsafe original path components')
    if any(unicodedata.category(c).startswith('C') for c in name):
        raise OriginalInputError('Control character in original path')
    if name != 'main' and not name.startswith('data/'):
        raise OriginalInputError('Original read-set may contain only main and data/')
    return name


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise OriginalInputError('Duplicate JSON member')
        out[key] = value
    return out


@dataclass(frozen=True)
class SourceEntry:
    size: int
    sha256: str


@dataclass(frozen=True)
class ReviewedReadSet:
    files: object
    sha256: str
    total_bytes: int

    @classmethod
    def parse(cls, data, *, expected_sha256):
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_READSET_BYTES:
            raise OriginalInputError('Original read-set size budget')
        if not isinstance(expected_sha256, str) or not HASH.fullmatch(expected_sha256):
            raise OriginalInputError('A signed recipe read-set pin is required')
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected_sha256:
            raise OriginalInputError('Original read-set pin mismatch')
        try:
            obj = json.loads(data.decode('utf-8', 'strict'), object_pairs_hook=_unique_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(OriginalInputError('Nonfinite JSON')))
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise OriginalInputError('Invalid original read-set JSON') from exc
        if (not isinstance(obj, dict) or set(obj) != {'schema', 'main_sha256', 'files'} or
                obj['schema'] != 'wmmt-original-readset-v1' or obj['main_sha256'] != MAIN_SHA256 or
                not isinstance(obj['files'], list) or not 1 <= len(obj['files']) <= MAX_FILES):
            raise OriginalInputError('Unsupported original read-set schema')
        entries, folded, total, previous = {}, set(), 0, ''
        for row in obj['files']:
            if not isinstance(row, dict) or set(row) != {'path', 'bytes', 'sha256'}:
                raise OriginalInputError('Invalid original read-set entry')
            name = source_path(row['path'])
            size, value = row['bytes'], row['sha256']
            if (name <= previous or name.casefold() in folded or type(size) is not int or
                    not 0 <= size <= MAX_FILE_BYTES or not isinstance(value, str) or not HASH.fullmatch(value)):
                raise OriginalInputError('Duplicate, unsorted or invalid original entry')
            total += size
            if total > MAX_TOTAL_BYTES:
                raise OriginalInputError('Original read-set total byte budget')
            entries[name] = SourceEntry(size, value)
            folded.add(name.casefold())
            previous = name
        if 'main' not in entries or entries['main'].sha256 != MAIN_SHA256:
            raise OriginalInputError('Read-set does not bind the reviewed main image')
        for name in entries:
            prefix = name
            while '/' in prefix:
                prefix = prefix.rsplit('/', 1)[0]
                if prefix.casefold() in folded:
                    raise OriginalInputError('File/directory path conflict')
        return cls(MappingProxyType(entries), digest, total)


def _directory(path):
    p = Path(path)
    if not p.is_absolute() or '..' in p.parts:
        raise OriginalInputError('An explicit absolute existing directory is required')
    for q in [*reversed(p.parents), p]:
        mode = os.lstat(q).st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise OriginalInputError('Directory chain contains link or nondirectory')
    return p


def _identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


class FileTreeSource:
    """No walk, discovery, source writes, dynamic import or original code execution."""
    def __init__(self, root, readset):
        if not isinstance(readset, ReviewedReadSet):
            raise OriginalInputError('Reviewed read-set required')
        self.root = _directory(root)
        self.readset = readset
        self._root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
            os.close(self._root_fd)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _open(self, name):
        if self.closed:
            raise OriginalInputError('Original source is closed')
        source_path(name)
        if name not in self.readset.files:
            raise OriginalInputError('Source is not authorized by this recipe')
        parts, directory = name.split('/'), os.dup(self._root_fd)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != self.readset.files[name].size:
            os.close(fd)
            raise OriginalInputError('Original member is missing, nonregular or has wrong length')
        return fd, info

    def chunks(self, name, *, cancel=None, progress=None):
        """A consumer must exhaust this iterator before accepting any output."""
        check_cancel(cancel)
        fd, before = self._open(name)
        count, digest = 0, hashlib.sha256()
        expected = self.readset.files[name]
        try:
            while True:
                check_cancel(cancel)
                block = os.read(fd, min(BLOCK, expected.size - count + 1))
                if not block:
                    break
                count += len(block)
                if count > expected.size:
                    raise OriginalInputError('Original member grew during read')
                digest.update(block)
                if progress:
                    progress('read-original', count, expected.size)
                yield block
            check_cancel(cancel)
            if (count != expected.size or digest.hexdigest() != expected.sha256 or
                    _identity(before) != _identity(os.fstat(fd))):
                raise OriginalInputError('Original member changed or failed SHA-256')
        finally:
            os.close(fd)

    def read(self, name, *, max_bytes, cancel=None, progress=None):
        if name not in self.readset.files or self.readset.files[name].size > max_bytes:
            raise OriginalInputError('Original buffered-read budget')
        return b''.join(self.chunks(name, cancel=cancel, progress=progress))


class OwnedOutput:
    """New private-job output tree only; never adopts or deletes existing trees."""
    def __init__(self, parent):
        parent = _directory(parent)
        self.root = parent / ('original-convert-' + uuid.uuid4().hex)
        os.mkdir(self.root, 0o700)
        self.files = {}

    def target(self, name):
        # Runtime names are separately constrained here, not original-source names.
        if not isinstance(name, str) or name == 'main' or name.startswith('data/'):
            raise OriginalInputError('Invalid runtime destination')
        source_path('data/' + name)
        p = self.root
        for part in name.split('/')[:-1]:
            p = p / part
            if not os.path.lexists(p):
                os.mkdir(p, 0o700)
            if not stat.S_ISDIR(os.lstat(p).st_mode):
                raise OriginalInputError('Output parent replaced or linked')
        result = self.root / name
        if os.path.lexists(result):
            raise OriginalInputError('Output already exists')
        return result

    def copy_from(self, source, original_name, runtime_name, *, cancel=None, progress=None):
        check_cancel(cancel)
        target = self.target(runtime_name)
        with target.open('xb') as out:
            for block in source.chunks(original_name, cancel=cancel, progress=progress):
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        entry = source.readset.files[original_name]
        self.files[runtime_name] = entry
        return entry


_SNAPSHOT_TOKEN = object()


class VerifiedSnapshot:
    """Only produced by a complete read-set copy, never from an external receipt.

    This is an execution input, not a release output signature or a ready dataset.
    Android brokers may implement the same contract with SAF readers and owned FDs.
    """
    __slots__ = ('root', 'readset', 'bytes')

    def __init__(self, root, readset, total, token=None):
        if token is not _SNAPSHOT_TOKEN:
            raise OriginalInputError('A snapshot must be created from verified source reads')
        self.root, self.readset, self.bytes = root, readset, total

    @classmethod
    def create(cls, source, parent, *, cancel=None, progress=None):
        check_cancel(cancel)
        if not isinstance(source, FileTreeSource):
            raise OriginalInputError('A bounded original source is required')
        readset = source.readset
        if readset.files.get('main', SourceEntry(0, '')).sha256 != MAIN_SHA256:
            raise OriginalInputError('Snapshot does not bind the reviewed original main')
        parent = _directory(parent)
        space = os.statvfs(parent)
        if space.f_bavail * space.f_frsize < readset.total_bytes + 64 * 1024 * 1024:
            raise OriginalInputError('Insufficient space for the original source snapshot')
        root = parent / ('original-source-' + uuid.uuid4().hex)
        os.mkdir(root, 0o700)
        copied = 0
        names = ['main'] + sorted(n for n in readset.files if n != 'main')
        for index, name in enumerate(names):
            check_cancel(cancel)
            current = root
            for component in name.split('/')[:-1]:
                current = current / component
                if not os.path.lexists(current):
                    os.mkdir(current, 0o700)
                if not stat.S_ISDIR(os.lstat(current).st_mode):
                    raise OriginalInputError('Snapshot parent replaced or linked')
            target = root / name
            with target.open('xb') as out:
                for block in source.chunks(name, cancel=cancel):
                    out.write(block)
                    copied += len(block)
                out.flush()
            # No executable bit, original-main loading, dynamic imports, or copies
            # of unlisted source files. A crash leaves this unsealed job inactive.
            os.chmod(target, 0o400)
            if progress:
                progress('snapshot-original', index + 1, len(names))
        check_cancel(cancel)
        if copied != readset.total_bytes:
            raise OriginalInputError('Incomplete original source snapshot')
        return cls(root, readset, copied, _SNAPSHOT_TOKEN)
