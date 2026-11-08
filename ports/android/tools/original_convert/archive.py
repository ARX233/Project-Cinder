"""Read-only ZIP transport for signed-recipe original entry bytes.

This is NOT a ZIP extractor, reviewed container fingerprint, or Ready factory.
All central/local metadata is checked, including unused members; unused payloads
are never inflated or CRC-checked. Only exhausted selected reads establish entry
SHA-256/length/CRC acceptance. Yielded chunks are provisional until exhaustion,
just like FileTreeSource, and may only be staged in a new private partial tree.

Supported: single-disk, non-self-extracting store/deflate ZIP, including ordinary
ZIP64 sizes/offsets and descriptors. ZIP64 extensible end records, preambles,
trailing junk, unsupported flags, central directories over 64 MiB, and more than
65536 explicit/implicit namespace nodes fail closed.
The caller owns the cached ZIP and any snapshot partials; this module never
creates, deletes, overwrites, publishes, or executes a file.
"""
import hashlib
import os
from pathlib import Path
import stat
import struct
import unicodedata
import zipfile

from .source import (BLOCK, MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES,
                     FileTreeSource, OriginalInputError, ReviewedReadSet,
                     _identity, check_cancel, source_path)

MAX_ARCHIVE_BYTES = 8 * 1024 * 1024 * 1024
# Full arcade distributions include directories and files outside the pinned read-set.
MAX_ARCHIVE_ENTRIES = 32768
MAX_CENTRAL_BYTES = 64 * 1024 * 1024
MAX_DEPTH = 64
MAX_NAME_BYTES = 16384
MAX_NAMESPACE_NODES = MAX_FILES * 4
_DEFLATE_ERROR = zipfile.zlib.error if zipfile.zlib is not None else RuntimeError
_ALLOWED_FLAGS = 0x080e  # UTF-8, data descriptor, deflate options; never encryption.


def _require(condition, message):
    if not condition:
        raise OriginalInputError(message)


def _path(name, directory):
    _require(isinstance(name, str) and 0 < len(name) <= 4096,
             'Invalid archive path length')
    _require('\x00' not in name and '\\' not in name and ':' not in name and
             name == unicodedata.normalize('NFC', name), 'Noncanonical archive path')
    value = name[:-1] if directory else name
    parts = value.split('/')
    _require(len(parts) <= MAX_DEPTH and all(p and p not in ('.', '..') and
             p[-1] not in ' .' for p in parts), 'Unsafe archive path components')
    _require(not any(unicodedata.category(c).startswith('C') for c in name),
             'Control character in archive path')
    return value, parts


def _extra(raw):
    fields, offset = {}, 0
    while offset < len(raw):
        _require(len(raw) - offset >= 4, 'Truncated archive extra field')
        tag, size = struct.unpack_from('<HH', raw, offset)
        offset += 4
        _require(size <= len(raw) - offset and tag not in fields,
                 'Invalid or duplicate archive extra field')
        fields[tag] = raw[offset:offset + size]
        offset += size
    return fields


def _member_extra(fields, raw_name, name):
    _require(0x9901 not in fields, 'AES archive metadata is not supported')
    # Some ZIP writers carry an alternate Unicode name. Never permit it to
    # contradict the exact name actually used for source authorization.
    if 0x7075 in fields:
        value = fields[0x7075]
        _require(len(value) >= 5 and value[0] == 1 and
                 struct.unpack_from('<L', value, 1)[0] == zipfile.crc32(raw_name),
                 'Invalid Unicode archive path extra field')
        _require(value[5:].decode('utf-8', 'strict') == name,
                 'Conflicting Unicode archive path extra field')


def _zip64(fields, values, sentinels, widths):
    needed = sum(width for value, sentinel, width in zip(values, sentinels, widths)
                 if value == sentinel)
    if not needed:
        _require(1 not in fields or not fields[1], 'Unneeded ZIP64 metadata')
        return values
    raw = fields.get(1, b'')
    _require(len(raw) == needed, 'Missing or inconsistent ZIP64 metadata')
    result, offset = [], 0
    for value, sentinel, width in zip(values, sentinels, widths):
        if value == sentinel:
            value = int.from_bytes(raw[offset:offset + width], 'little')
            offset += width
        result.append(value)
    return result


def _open_cached(path):
    """Open once through directory FDs; never follow any path component."""
    path = Path(path)
    _require(path.is_absolute() and '..' not in path.parts,
             'An explicit absolute cached ZIP path is required')
    # Traversal through Android system directories doesn't require read access.
    walk_flags = getattr(os, 'O_PATH', os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(path.anchor, walk_flags)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, walk_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
    finally:
        os.close(directory)
    try:
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode), 'Cached ZIP is not a regular file')
        _require(22 <= info.st_size <= MAX_ARCHIVE_BYTES, 'Cached ZIP size budget')
        return path, os.fdopen(fd, 'rb'), info
    except BaseException:
        os.close(fd)
        raise


class _BoundedReader:
    """Keep ZipFile's second EOCD/central parse inside the prechecked FD budget.

    fstat checks alone at constructor end would reject mutation too late if a
    changed end record first induced ZipFile to allocate an oversized directory.
    """
    def __init__(self, source):
        self.source = source

    def tell(self):
        self.source._unchanged()
        return self.source._file.tell()

    def seek(self, offset, whence=0):
        self.source._unchanged()
        _require(whence in (0, 1, 2), 'Unsupported archive seek mode')
        base = 0 if whence == 0 else (self.tell() if whence == 1 else self.source._before.st_size)
        position = base + offset
        _require(0 <= position <= self.source._before.st_size, 'ZIP reader seek outside checked container')
        return self.source._file.seek(position)

    def read(self, size=-1):
        self.source._unchanged()
        if size < 0:
            size = self.source._before.st_size - self.tell()
        _require(0 <= size <= MAX_CENTRAL_BYTES, 'ZIP reader metadata allocation budget')
        data = self.source._file.read(size)
        self.source._unchanged()
        return data

    def seekable(self):
        return True


class ArchiveSource(FileTreeSource):
    """FileTreeSource-compatible entry reader, with no tree initializer or writes.

    readset must already have been parsed against the APK-signed recipe pin;
    an observed container digest or external result receipt is not such a pin.
    Construction checks metadata, not payload correctness or reviewed main SHA.
    VerifiedSnapshot.create performs main-first, complete-readset acceptance.
    """
    def __init__(self, cached_zip_path, readset, *, cancel=None, progress=None):
        _require(isinstance(readset, ReviewedReadSet), 'Reviewed read-set required')
        check_cancel(cancel)
        self.closed, self._file, self._zip = False, None, None
        self.readset, self._cancel, self._progress = readset, cancel, progress
        self._members = {}
        try:
            self.root, self._file, self._before = _open_cached(cached_zip_path)
            records, central_start = self._inventory()
            self._headers(records, central_start)
            self._zip = zipfile.ZipFile(_BoundedReader(self), 'r', allowZip64=True)
            infos = self._zip.infolist()
            _require(self._zip.start_dir == central_start and len(infos) == len(records),
                     'Self-extracting or inconsistent archive offsets')
            for record, info in zip(records, infos):
                _require((info.orig_filename, info.header_offset, info.file_size,
                          info.compress_size, info.CRC, info.compress_type, info.flag_bits) ==
                         (record['name'], record['offset'], record['size'], record['compressed'],
                          record['crc'], record['method'], record['flags']),
                         'ZIP library and checked inventory disagree')
                record['info'] = info
            self._select(records)
            self.inventory_entries = len(records)
            # Honest scope, not a claim that unused full-game payloads were verified.
            self.coverage = ('complete central/local metadata; selected payloads only on '
                             'successful iterator exhaustion; unused payload CRC/SHA unchecked')
            self._unchanged()
        except BaseException as exc:
            self.close()
            if isinstance(exc, (zipfile.BadZipFile, NotImplementedError, UnicodeError,
                                struct.error, EOFError)):
                raise OriginalInputError('Invalid original ZIP metadata') from exc
            raise

    def _check(self, cancel=None):
        check_cancel(self._cancel)
        if cancel is not self._cancel:
            check_cancel(cancel)
        _require(not self.closed, 'Original archive source is closed')

    def _unchanged(self):
        _require(not self.closed and self._file is not None,
                 'Original archive source is closed')
        _require(_identity(self._before) == _identity(os.fstat(self._file.fileno())),
                 'Cached ZIP container changed')

    def _at(self, offset, size):
        _require(0 <= offset <= self._before.st_size and
                 0 <= size <= self._before.st_size - offset, 'Archive byte range outside container')
        data = os.pread(self._file.fileno(), size, offset)
        _require(len(data) == size, 'Truncated cached ZIP')
        return data

    def _inventory(self):
        size = self._before.st_size
        start = max(0, size - 65557)
        tail = self._at(start, size - start)
        index = tail.rfind(b'PK\x05\x06')
        _require(index >= 0 and len(tail) - index >= 22, 'Missing ZIP end record')
        end = start + index
        (_, disk, central_disk, disk_count, count, length, offset, comment) = struct.unpack(
            '<4s4H2LH', tail[index:index + 22])
        _require(end + 22 + comment == size, 'ZIP trailing data or invalid end record')
        _require(disk == central_disk == 0 and disk_count == count,
                 'Multidisk archive is not supported')
        central_end = end
        locator = self._at(end - 20, 20) if end >= 20 else b''
        sentinel = count == 0xffff or length == 0xffffffff or offset == 0xffffffff
        if locator.startswith(b'PK\x06\x07'):
            _, z_disk, z_offset, disks = struct.unpack('<4sLQL', locator)
            _require(z_disk == 0 and disks == 1, 'Multidisk ZIP64 is not supported')
            data = self._at(z_offset, 56)
            (signature, z_size, made, version, z_disk, z_central_disk,
             z_disk_count, z_count, z_length, z_start) = struct.unpack('<4sQ2H2L4Q', data)
            _require(signature == b'PK\x06\x06' and z_size == 44 and
                     z_offset + 56 == end - 20 and version <= 45,
                     'Unsupported ZIP64 end record or preamble')
            _require(z_disk == z_central_disk == 0 and z_disk_count == z_count,
                     'Multidisk ZIP64 is not supported')
            _require((count == 0xffff or count == z_count) and
                     (length == 0xffffffff or length == z_length) and
                     (offset == 0xffffffff or offset == z_start), 'Inconsistent ZIP64 end records')
            count, length, offset, central_end = z_count, z_length, z_start, z_offset
        else:
            _require(not sentinel, 'Missing ZIP64 locator')
        _require(1 <= count <= MAX_ARCHIVE_ENTRIES,
                 f'Archive entry count {count} exceeds supported range 1..{MAX_ARCHIVE_ENTRIES}')
        _require(0 < length <= MAX_CENTRAL_BYTES and 0 <= offset and
                 offset + length == central_end, 'Archive central directory budget or range')
        records, namespace, explicit, total, position = [], {}, set(), 0, offset
        for index in range(count):
            self._check()
            _require(position + 46 <= central_end, 'Truncated central directory')
            fixed = struct.unpack('<4s6H3L5H2L', self._at(position, 46))
            (signature, made, version, flags, method, _, _, crc, compressed, uncompressed,
             name_length, extra_length, comment_length, disk, _, external, local_offset) = fixed
            _require(signature == b'PK\x01\x02' and version <= 45,
                     'Invalid or unsupported central header')
            _require(method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) and
                     (method != zipfile.ZIP_DEFLATED or zipfile.zlib is not None),
                     'Unsupported archive compression method or missing stdlib deflate')
            _require(not flags & ~_ALLOWED_FLAGS and (method != 0 or not flags & 6),
                     'Encrypted or unsupported archive flags')
            end_position = position + 46 + name_length + extra_length + comment_length
            _require(0 < name_length <= MAX_NAME_BYTES and end_position <= central_end,
                     'Archive metadata name budget or range')
            raw_name = self._at(position + 46, name_length)
            _require(b'\x00' not in raw_name, 'NUL in archive name')
            name = raw_name.decode('utf-8' if flags & 0x800 else 'cp437', 'strict')
            directory = name.endswith('/')
            value, parts = _path(name, directory)
            _require(value.casefold() not in explicit, 'Duplicate archive member or directory')
            explicit.add(value.casefold())
            for depth in range(1, len(parts) + 1):
                ancestor = '/'.join(parts[:depth])
                is_directory = depth < len(parts) or directory
                folded = ancestor.casefold()
                previous = namespace.get(folded)
                _require(previous is None or previous == (ancestor, is_directory),
                         'Archive Unicode casefold or file/directory alias')
                _require(previous is not None or len(namespace) < MAX_NAMESPACE_NODES,
                         'Archive namespace node budget')
                namespace[folded] = (ancestor, is_directory)
            kind = stat.S_IFMT(external >> 16)
            _require(kind in (0, stat.S_IFDIR if directory else stat.S_IFREG) and
                     (directory or not external & 0x10), 'Nonregular archive member')
            fields = _extra(self._at(position + 46 + name_length, extra_length))
            _member_extra(fields, raw_name, name)
            uncompressed, compressed, local_offset, disk = _zip64(
                fields, [uncompressed, compressed, local_offset, disk],
                [0xffffffff, 0xffffffff, 0xffffffff, 0xffff], [8, 8, 8, 4])
            _require(disk == 0, 'Multidisk archive member')
            _require(uncompressed <= MAX_FILE_BYTES and compressed <= MAX_ARCHIVE_BYTES,
                     'Archive declared member size budget')
            total += uncompressed
            _require(total <= MAX_TOTAL_BYTES, 'Archive declared total size budget')
            _require(0 <= local_offset and local_offset + 30 <= offset and
                     compressed <= offset - local_offset - 30, 'Archive local range touches central directory')
            _require(method != 0 or compressed == uncompressed, 'Stored member length mismatch')
            _require(not directory or (uncompressed == 0 and crc == 0), 'Nonempty directory member')
            records.append(dict(name=name, raw_name=raw_name, directory=directory, size=uncompressed,
                                compressed=compressed, offset=local_offset, crc=crc, flags=flags,
                                method=method))
            position = end_position
            if self._progress:
                self._progress('archive-inventory', index + 1, count)
        _require(position == central_end, 'Central count/size mismatch or extra records')
        return records, offset

    def _descriptor(self, position, record, wide, central_start):
        width = 20 if wide else 12
        _require(position + width <= central_start, 'Truncated archive descriptor')
        first = self._at(position, 4)
        signed = first == b'PK\x07\x08'
        if signed:
            position += 4
        _require(position + width <= central_start, 'Descriptor touches central directory')
        values = struct.unpack('<LQQ' if wide else '<LLL', self._at(position, width))
        _require(values == (record['crc'], record['compressed'], record['size']),
                 'Archive descriptor does not match central metadata')
        return position + width

    def _headers(self, records, central_start):
        ranges = []
        for index, record in enumerate(records):
            self._check()
            (signature, version, flags, method, _, _, crc, compressed, uncompressed,
             name_length, extra_length) = struct.unpack('<4s5H3L2H', self._at(record['offset'], 30))
            _require(signature == b'PK\x03\x04' and version <= 45 and
                     flags == record['flags'] and method == record['method'],
                     'Local/central compression, flags or signature mismatch')
            data_start = record['offset'] + 30 + name_length + extra_length
            _require(name_length == len(record['raw_name']) and data_start <= central_start,
                     'Local archive name/extra range mismatch')
            _require(self._at(record['offset'] + 30, name_length) == record['raw_name'],
                     'Local/central archive name mismatch')
            fields = _extra(self._at(record['offset'] + 30 + name_length, extra_length))
            _member_extra(fields, record['raw_name'], record['name'])
            wide = uncompressed == 0xffffffff or compressed == 0xffffffff
            uncompressed, compressed = _zip64(fields, [uncompressed, compressed],
                                             [0xffffffff, 0xffffffff], [8, 8])
            if flags & 8:
                _require(crc in (0, record['crc']) and uncompressed in (0, record['size']) and
                         compressed in (0, record['compressed']), 'Inconsistent descriptor local header')
            else:
                _require((crc, compressed, uncompressed) ==
                         (record['crc'], record['compressed'], record['size']),
                         'Local/central CRC or length mismatch')
            data_end = data_start + record['compressed']
            _require(data_end <= central_start, 'Archive payload touches central directory')
            end = self._descriptor(data_end, record, wide, central_start) if flags & 8 else data_end
            record['data_start'] = data_start
            ranges.append((record['offset'], end))
            if self._progress:
                self._progress('archive-headers', index + 1, len(records))
        ranges.sort()
        _require(ranges[0][0] == 0, 'Self-extracting archive preamble is not supported')
        _require(all(left[1] <= right[0] for left, right in zip(ranges, ranges[1:])),
                 'Overlapping archive local member ranges')

    def _select(self, records):
        files = {r['name']: r for r in records if not r['directory']}
        _require(not any(name.casefold() in ('androidmanifest.xml', 'assets/re3dxplus-data.zip')
                         for name in files), 'APK is not an original resource ZIP')
        candidates = []
        for name in files:
            self._check()
            if name == 'main' or name.endswith('/main'):
                prefix = name[:-4]
                if all(prefix + path in files for path in self.readset.files):
                    candidates.append(prefix)
        _require(len(candidates) == 1, 'Missing or ambiguous original archive root')
        self.prefix = candidates[0]
        for name, expected in self.readset.files.items():
            source_path(name)
            record = files[self.prefix + name]
            _require(record['size'] == expected.size, 'Selected original member has wrong length')
            self._members[name] = record

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                if self._zip is not None:
                    self._zip.close()
            finally:
                if self._file is not None:
                    self._file.close()

    def chunks(self, name, *, cancel=None, progress=None):
        """Provisional bounded blocks; accept only after complete SHA/CRC exhaustion.

        Raw deflate is deliberately bounded independently of central file_size:
        ZipExtFile alone clips excess inflated bytes to its declared length.
        The stdlib zipfile decompressor supplies max-length raw deflate; no
        flush/unbounded decompression or allocation by a declared member size.
        """
        self._check(cancel)
        self._unchanged()
        source_path(name)
        _require(name in self._members, 'Source is not authorized by this recipe')
        record, expected = self._members[name], self.readset.files[name]
        progress = self._progress if progress is None else progress
        count, crc, digest = 0, 0, hashlib.sha256()
        try:
            # Independently exercise ZipFile's selected local-header and overlap
            # checks, without its size-clipping payload reader being the authority.
            with self._zip.open(record['info'], 'r'):
                pass
            decompressor = zipfile._get_decompressor(record['method'])
            offset, remaining = record['data_start'], record['compressed']
            data = b''
            while remaining or data or (decompressor is not None and not decompressor.eof):
                self._check(cancel)
                if not data and remaining:
                    data = self._at(offset, min(BLOCK, remaining))
                    offset += len(data)
                    remaining -= len(data)
                limit = min(BLOCK, expected.size - count + 1)
                if decompressor is None:
                    block, data = data[:limit], data[limit:]
                else:
                    previous = len(data)
                    # Bounded empty-input drain handles zlib output buffered at a
                    # block boundary. flush() would not impose an output ceiling.
                    block = decompressor.decompress(data, limit)
                    data = decompressor.unconsumed_tail
                    _require(not decompressor.unused_data and not (decompressor.eof and remaining),
                             'Extra data after deflate stream')
                    _require(block or len(data) < previous or remaining or decompressor.eof,
                             'Incomplete or stalled deflate stream')
                count += len(block)
                _require(count <= expected.size and count <= MAX_FILE_BYTES,
                         'Original inflated member exceeded actual byte budget')
                if block:
                    crc = zipfile.crc32(block, crc)
                    digest.update(block)
                    if progress:
                        progress('read-original', count, expected.size)
                    yield block
            self._check(cancel)
            _require(decompressor is None or decompressor.eof, 'Incomplete deflate stream')
            _require(count == expected.size and crc == record['crc'] and
                     digest.hexdigest() == expected.sha256, 'Original member failed length, CRC or SHA-256')
            self._unchanged()
        except (zipfile.BadZipFile, _DEFLATE_ERROR, EOFError, struct.error) as exc:
            raise OriginalInputError('Invalid original ZIP payload') from exc
