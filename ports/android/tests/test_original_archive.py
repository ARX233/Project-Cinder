"""Synthetic ZIP safety tests; no game execution, device or converted-output input.

Optional ORIGINAL_ARCHIVE_MAIN opts into a read-only main SHA/snapshot proof.
Production hashes are never overridden. The synthetic main intentionally cannot
pass main SHA; individual data members exercise the actual reader independently.
All fixture/snapshot/cache output must stay on the external work volume.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

MODULE = Path(__file__).resolve().with_name('archive.py')
if not MODULE.is_file():
    MODULE = Path(__file__).resolve().parents[1] / 'tools/original_convert/archive.py'
PACKAGE = 'original_archive_under_test'
spec = importlib.util.spec_from_file_location(PACKAGE, MODULE.with_name('__init__.py'),
                                               submodule_search_locations=[str(MODULE.parent)])
package = importlib.util.module_from_spec(spec)
sys.modules[PACKAGE] = package
spec.loader.exec_module(package)
spec = importlib.util.spec_from_file_location(PACKAGE + '.archive', MODULE)
a = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = a
spec.loader.exec_module(a)
m = sys.modules[PACKAGE + '.source']
WORK = Path('/Volumes/CodexWork/android135-original-convert-l809giqy')


def readset(payload=b'abc', *, name='data/a', main_size=1, expected=None):
    rows = [{'path': 'main', 'bytes': main_size, 'sha256': m.MAIN_SHA256},
            {'path': name, 'bytes': len(payload),
             'sha256': expected or hashlib.sha256(payload).hexdigest()}]
    data = json.dumps({'schema': 'wmmt-original-readset-v1', 'main_sha256': m.MAIN_SHA256,
                       'files': sorted(rows, key=lambda row: row['path'])},
                      separators=(',', ':')).encode()
    # Test-local synthetic recipe pin; never an input-container fingerprint.
    return m.ReviewedReadSet.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())


def locations(raw):
    end = raw.rfind(b'PK\x05\x06')
    offset = struct.unpack_from('<L', raw, end + 16)[0]
    count = struct.unpack_from('<H', raw, end + 10)[0]
    result = {}
    for _ in range(count):
        n, x, c = struct.unpack_from('<3H', raw, offset + 28)
        name = bytes(raw[offset + 46:offset + 46 + n]).decode('utf-8')
        result[name] = (struct.unpack_from('<L', raw, offset + 42)[0], offset)
        offset += 46 + n + x + c
    return result, end


class NoSeek(io.BytesIO):
    def seek(self, *_):
        raise OSError('nonseekable test writer')


class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = Path(os.environ.get('ORIGINAL_ARCHIVE_TEST_WORK', WORK))
        # Exclusive new directory; never adopts/deletes an existing fixture tree.
        cls.root = Path(tempfile.mkdtemp(prefix='archive-tests-', dir=parent))

    def new_path(self, name='input.zip'):
        return Path(tempfile.mkdtemp(prefix='case-', dir=self.root)) / name

    def zip(self, payload=b'abc', *, prefix='', method=zipfile.ZIP_STORED,
            extras=(), include_main=True, include_data=True, descriptor=False,
            force_zip64=False):
        p = self.new_path()
        target = NoSeek() if descriptor else io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(target, 'w', compression=method) as z:
                if include_main:
                    z.writestr(prefix + 'main', b'x')
                if include_data:
                    info = zipfile.ZipInfo(prefix + 'data/a')
                    info.compress_type = method
                    if force_zip64:
                        with z.open(info, 'w', force_zip64=True) as out:
                            out.write(payload)
                    else:
                        z.writestr(info, payload)
                for name, data in extras:
                    z.writestr(name, data)
        p.write_bytes(target.getvalue())
        return p

    def mutate(self, p, name='data/a', *, local=(), central=()):
        raw = bytearray(p.read_bytes())
        indexes, _ = locations(raw)
        start, center = indexes[name]
        for offset, format_, value in local:
            struct.pack_into(format_, raw, start + offset, value)
        for offset, format_, value in central:
            struct.pack_into(format_, raw, center + offset, value)
        p.write_bytes(raw)

    def rejects(self, p, rs=None):
        with self.assertRaises((m.OriginalInputError, OSError)):
            with a.ArchiveSource(p, rs or readset()):
                pass

    def test_inheritance_read_budget_store_deflate_and_exact_prefix(self):
        for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            for prefix in ('', 'wrapper/', 'one/two/three/'):
                with self.subTest(method=method, prefix=prefix):
                    payload = b'abc' * (m.BLOCK + 5)
                    p = self.zip(payload, prefix=prefix, method=method,
                                 extras=[(prefix + 'unrelated', b'not copied')])
                    events = []
                    with a.ArchiveSource(p, readset(payload), progress=lambda *v: events.append(v)) as source:
                        self.assertIsInstance(source, m.FileTreeSource)
                        self.assertEqual(source.root, p)
                        self.assertEqual(source.prefix, prefix)
                        blocks = list(source.chunks('data/a'))
                        self.assertTrue(all(0 < len(b) <= m.BLOCK for b in blocks))
                        self.assertEqual(b''.join(blocks), payload)
                        self.assertEqual(source.read('data/a', max_bytes=len(payload)), payload)
                        with self.assertRaises(m.OriginalInputError):
                            source.read('data/a', max_bytes=len(payload) - 1)
                        with self.assertRaises(m.OriginalInputError):
                            list(source.chunks('unrelated'))
                        with self.assertRaises(m.OriginalInputError):
                            list(source.chunks('data/not-authorized'))
                        self.assertIn('unused payload CRC/SHA unchecked', source.coverage)
                    self.assertIn('archive-inventory', {v[0] for v in events})
                    self.assertIn('read-original', {v[0] for v in events})
                    with self.assertRaises(m.OriginalInputError):
                        source.read('data/a', max_bytes=len(payload))

    def test_apk_wrappers_are_rejected_even_with_the_full_original_readset(self):
        for member in ('AndroidManifest.xml', 'assets/re3dxplus-data.zip'):
            with self.subTest(member=member):
                fixture = self.zip(extras=((member, b'apk wrapper'),))
                with self.assertRaisesRegex(m.OriginalInputError, 'APK'):
                    a.ArchiveSource(fixture, readset())

    def test_empty_and_block_boundary_streams(self):
        for size in (0, 1, m.BLOCK - 1, m.BLOCK, m.BLOCK + 1, m.BLOCK * 2):
            payload = b'q' * size
            with a.ArchiveSource(self.zip(payload, method=8), readset(payload)) as source:
                self.assertEqual(source.read('data/a', max_bytes=size), payload)

    def test_missing_mandatory_wrong_size_case_and_ambiguous_roots(self):
        self.rejects(self.zip(include_main=False))
        self.rejects(self.zip(include_data=False))
        self.rejects(self.zip(b'ab'))
        self.rejects(self.zip(include_data=False, extras=[('data/A', b'abc')]))
        self.rejects(self.zip(extras=[('other/main', b'x'), ('other/data/a', b'abc')]))
        # A partial wrapper is not a competing full read-set root.
        with a.ArchiveSource(self.zip(extras=[('other/main', b'x')]), readset()) as source:
            self.assertEqual(source.prefix, '')

    def test_all_inventory_paths_and_unicode_aliases_are_checked(self):
        unsafe = ['../main', '/unsafe', 'a/../b', 'a//b', 'a/./b', 'a\\b', 'a:b',
                  'a.', 'a ', 'a/e\u0301', 'a/\x01', 'a/\u200b', '/main',
                  'a/' * 64 + 'leaf', 'x' * 4097]
        for name in unsafe:
            with self.subTest(name=repr(name)):
                self.rejects(self.zip(extras=[(name, b'')]))
        aliases = [[('duplicate', b''), ('duplicate', b'')],
                   [('directory/', b''), ('directory/', b'')],
                   [('data/A', b'')], [('dir', b''), ('dir/child', b'')],
                   [('dir/', b''), ('dir', b'')], [('Case/a', b''), ('case/b', b'')],
                   [('unused/\u00df', b''), ('unused/ss', b'')]]
        for extras in aliases:
            with self.subTest(extras=extras):
                self.rejects(self.zip(extras=extras))
        # A NUL must be tested as raw metadata: ZipInfo itself truncates NULs.
        p = self.zip(extras=[('unused0', b'')])
        raw = bytearray(p.read_bytes()); indexes, _ = locations(raw)
        local, central = indexes['unused0']
        raw[local + 30 + 6] = raw[central + 46 + 6] = 0
        p.write_bytes(raw); self.rejects(p)

    def test_unsafe_wrapper_is_not_root_discovery(self):
        for prefix in ('../', '/absolute/', 'C:/', 'bad\\/', 'e\u0301/', 'a/' * 64):
            with self.subTest(prefix=prefix):
                self.rejects(self.zip(prefix=prefix))

    def test_symlink_fifo_socket_device_and_directory_attributes(self):
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK, stat.S_IFCHR, stat.S_IFBLK):
            p = self.zip(extras=[('unused', b'')])
            self.mutate(p, 'unused', central=[(38, '<L', (kind | 0o600) << 16)])
            self.rejects(p)
        p = self.zip(extras=[('unused', b'')])
        self.mutate(p, 'unused', central=[(38, '<L', (stat.S_IFDIR << 16) | 0x10)])
        self.rejects(p)
        # An explicit directory and implicit children are normal, not duplicates.
        with a.ArchiveSource(self.zip(extras=[('data/', b'')]), readset()) as source:
            self.assertEqual(source.read('data/a', max_bytes=3), b'abc')

    def test_unsupported_encryption_flags_methods_and_multidisk(self):
        for flags in (1, 0x40, 0x2000, 0x10, 0x1000, 2):
            p = self.zip(extras=[('unused', b'')])
            self.mutate(p, 'unused', local=[(6, '<H', flags)], central=[(8, '<H', flags)])
            self.rejects(p)
        for method in (1, 9, 12, 14, 99):
            p = self.zip(extras=[('unused', b'')])
            self.mutate(p, 'unused', local=[(8, '<H', method)], central=[(10, '<H', method)])
            self.rejects(p)
        p = self.zip(); raw = bytearray(p.read_bytes()); _, end = locations(raw)
        struct.pack_into('<H', raw, end + 4, 1); p.write_bytes(raw); self.rejects(p)
        p = self.zip(); self.mutate(p, central=[(34, '<H', 1)]); self.rejects(p)

    def test_local_central_name_flags_method_crc_and_size_consistency(self):
        for local in ([(6, '<H', 8)], [(8, '<H', 8)], [(14, '<L', 123)], [(22, '<L', 9)]):
            p = self.zip(); self.mutate(p, local=local); self.rejects(p)
        p = self.zip(); raw = bytearray(p.read_bytes()); indexes, _ = locations(raw)
        raw[indexes['data/a'][0] + 30] = ord('e'); p.write_bytes(raw); self.rejects(p)
        # Metadata of unused entries is also checked without inflating them.
        p = self.zip(extras=[('unused', b'')]); raw = bytearray(p.read_bytes()); indexes, _ = locations(raw)
        raw[indexes['unused'][0] + 30] = ord('X'); p.write_bytes(raw); self.rejects(p)

    def test_overlaps_central_ranges_self_extracting_and_trailing_data(self):
        p = self.zip()
        # main claims a payload extending across the next local header.
        raw = bytearray(p.read_bytes()); indexes, _ = locations(raw)
        local, central = indexes['main']
        for base, offsets in ((local, (18, 22)), (central, (20, 24))):
            for offset in offsets: struct.pack_into('<L', raw, base + offset, 35)
        p.write_bytes(raw); self.rejects(p)
        p = self.zip(); self.mutate(p, local=[(18, '<L', 9999), (22, '<L', 9999)],
                                    central=[(20, '<L', 9999), (24, '<L', 9999)])
        self.rejects(p)
        p = self.zip(); p.write_bytes(b'EXECUTABLE-PREAMBLE' + p.read_bytes()); self.rejects(p)
        p = self.zip(); p.write_bytes(p.read_bytes() + b'junk'); self.rejects(p)

    def test_bad_crc_and_hash_fail_only_when_iterator_is_exhausted(self):
        for mode in ('crc', 'sha'):
            payload = b'q' * (m.BLOCK * 3)
            p = self.zip(payload)
            if mode == 'crc':
                self.mutate(p, local=[(14, '<L', 7)], central=[(16, '<L', 7)])
                rs = readset(payload)
            else:
                rs = readset(payload, expected='0' * 64)
            with a.ArchiveSource(p, rs) as source:
                stream = source.chunks('data/a')
                self.assertEqual(len(next(stream)), m.BLOCK)
                with self.assertRaises(m.OriginalInputError): list(stream)
                # Early close neither accepts the remaining payload nor leaks FDs.
                early = source.chunks('data/a'); next(early); early.close()

    def test_unused_payload_is_not_decompressed_or_crc_checked(self):
        p = self.zip(method=8, extras=[('unused', b'invalid deflate soon')])
        raw = bytearray(p.read_bytes()); indexes, _ = locations(raw)
        local, central = indexes['unused']; n, x = struct.unpack_from('<HH', raw, local + 26)
        compressed = struct.unpack_from('<L', raw, central + 20)[0]
        raw[local + 30 + n + x:local + 30 + n + x + compressed] = b'\xff' * compressed
        p.write_bytes(raw)
        with a.ArchiveSource(p, readset()) as source:
            self.assertEqual(source.read('data/a', max_bytes=3), b'abc')
            self.assertEqual(source.inventory_entries, 3)

    def test_declared_and_actual_zipbomb_bounds_are_independent(self):
        for method in (0, 8):
            payload = b'a' * (m.BLOCK * 16)
            p = self.zip(payload, method=method)
            # Pretend the stream's first 3 bytes are the entire authorized file.
            crc = zipfile.crc32(b'aaa')
            local = [(14, '<L', crc), (22, '<L', 3)]
            central = [(16, '<L', crc), (24, '<L', 3)]
            self.mutate(p, local=local, central=central)
            if method == 0:
                self.rejects(p)  # store lengths must agree before reading
            else:
                with a.ArchiveSource(p, readset(b'aaa')) as source:
                    yielded = []
                    with self.assertRaises(m.OriginalInputError):
                        for block in source.chunks('data/a'): yielded.append(block)
                    self.assertLessEqual(sum(map(len, yielded)), 3)
        # Even a short excess output whose CRC/SHA prefix match cannot be clipped.
        p = self.zip(b'aaaa', method=8); crc = zipfile.crc32(b'aaa')
        self.mutate(p, local=[(14, '<L', crc), (22, '<L', 3)],
                    central=[(16, '<L', crc), (24, '<L', 3)])
        with a.ArchiveSource(p, readset(b'aaa')) as source:
            with self.assertRaises(m.OriginalInputError): source.read('data/a', max_bytes=3)

    def test_incomplete_deflate_and_extra_compressed_bytes_are_rejected(self):
        p = self.zip(b'a' * 10000, method=8)
        raw = bytearray(p.read_bytes()); indexes, _ = locations(raw)
        local, central = indexes['data/a']; size = struct.unpack_from('<L', raw, central + 20)[0]
        self.mutate(p, local=[(18, '<L', size - 1)], central=[(20, '<L', size - 1)])
        with a.ArchiveSource(p, readset(b'a' * 10000)) as source:
            with self.assertRaises(m.OriginalInputError): list(source.chunks('data/a'))
        # Include one byte of legal gap in compressed size; stream EOF precedes it.
        p = self.zip(method=8); raw = bytearray(p.read_bytes()); indexes, end = locations(raw)
        local, central = indexes['data/a']; size = struct.unpack_from('<L', raw, central + 20)[0]
        central_start = struct.unpack_from('<L', raw, end + 16)[0]
        raw[central_start:central_start] = b'J'
        indexes, end = locations_for_gap(raw, central_start + 1)
        local, central = indexes['data/a']
        struct.pack_into('<L', raw, local + 18, size + 1)
        struct.pack_into('<L', raw, central + 20, size + 1)
        struct.pack_into('<L', raw, end + 16, central_start + 1)
        p.write_bytes(raw)
        with a.ArchiveSource(p, readset()) as source:
            with self.assertRaises(m.OriginalInputError): list(source.chunks('data/a'))

    def test_random_deflate_payloads_and_bounded_pending_output(self):
        for size in (17, m.BLOCK, m.BLOCK + 37, m.BLOCK * 3 + 1):
            payload = os.urandom(size)
            with self.subTest(size=size), a.ArchiveSource(self.zip(payload, method=8), readset(payload)) as source:
                self.assertEqual(source.read('data/a', max_bytes=size), payload)

    def test_alternate_unicode_path_and_aes_extra_metadata_fail_closed(self):
        for extra in (struct.pack('<HH', 0x9901, 0),
                      struct.pack('<HH', 0x7075, 1) + b'\x01',
                      struct.pack('<HHBL', 0x7075, 12, 1, zipfile.crc32(b'unused')) + b'../evil',
                      struct.pack('<HHHH', 1, 0, 1, 0), b'\x01\x00\xff\xff'):
            info = zipfile.ZipInfo('unused'); info.extra = extra
            self.rejects(self.zip(extras=[(info, b'')]))
        name = b'unused'
        info = zipfile.ZipInfo(name.decode())
        info.extra = struct.pack('<HHBL', 0x7075, 5 + len(name), 1, zipfile.crc32(name)) + name
        with a.ArchiveSource(self.zip(extras=[(info, b'')]), readset()) as source:
            self.assertEqual(source.read('data/a', max_bytes=3), b'abc')

    def test_malformed_central_count_and_declared_unused_budgets(self):
        p = self.zip(); raw = bytearray(p.read_bytes()); _, end = locations(raw)
        struct.pack_into('<HH', raw, end + 8, 3, 3); p.write_bytes(raw); self.rejects(p)
        p = self.zip(extras=[('unused', b'')])
        self.mutate(p, 'unused', central=[(24, '<L', a.MAX_FILE_BYTES + 1)])
        self.rejects(p)
        p = self.zip(extras=[('unused', b'')])
        self.mutate(p, 'unused', central=[(6, '<H', 63)])
        self.rejects(p)
        p = self.zip(extras=[('unused', b'')])
        with patch.object(a, 'MAX_NAMESPACE_NODES', 2): self.rejects(p)

    def test_readset_type_and_tree_initializer_are_not_bypassed(self):
        p = self.zip()
        with self.assertRaises(m.OriginalInputError): a.ArchiveSource(p, {})
        with patch.object(m.FileTreeSource, '__init__', side_effect=AssertionError('tree initializer called')):
            with a.ArchiveSource(p, readset()) as source:
                self.assertEqual(source.read('data/a', max_bytes=3), b'abc')

    def test_selected_corrupt_deflate_has_controlled_error(self):
        p = self.zip(method=8); raw = bytearray(p.read_bytes()); indexes, _ = locations(raw)
        local, central = indexes['data/a']; n, x = struct.unpack_from('<HH', raw, local + 26)
        size = struct.unpack_from('<L', raw, central + 20)[0]
        raw[local + 30 + n + x:local + 30 + n + x + size] = b'\xff' * size
        p.write_bytes(raw)
        with a.ArchiveSource(p, readset()) as source:
            with self.assertRaises(m.OriginalInputError): list(source.chunks('data/a'))

    def test_constructor_failure_closes_owned_fd_even_if_zipfile_rejects(self):
        p = self.zip(); before = len(os.listdir('/dev/fd'))
        with patch.object(a.zipfile, 'ZipFile', side_effect=zipfile.BadZipFile('test rejection')):
            for _ in range(10): self.rejects(p)
        self.assertLessEqual(len(os.listdir('/dev/fd')), before + 1)

    def test_zipfile_second_parse_cannot_bypass_metadata_read_budget(self):
        p = self.zip()
        with a.ArchiveSource(p, readset()) as source:
            reader = source._zip.fp
            with self.assertRaises(m.OriginalInputError): reader.read(a.MAX_CENTRAL_BYTES + 1)
            with self.assertRaises(m.OriginalInputError): reader.seek(source._before.st_size + 1)
            with self.assertRaises(m.OriginalInputError): reader.seek(-1)
            with self.assertRaises(m.OriginalInputError): reader.seek(0, 9)
            self.assertEqual(source.read('data/a', max_bytes=3), b'abc')
        real_zipfile = a.zipfile.ZipFile
        class RacingZipFile(real_zipfile):
            def __init__(self, file, *args, **kwargs):
                with p.open('ab') as out: out.write(b'changed between metadata passes')
                super().__init__(file, *args, **kwargs)
        with patch.object(a.zipfile, 'ZipFile', RacingZipFile): self.rejects(p)

    def test_original_path_replacement_never_reopens_replacement(self):
        p = self.zip()
        with a.ArchiveSource(p, readset()) as source:
            held = p.with_name('held.zip')
            # Both verified absolute paths are newly owned test fixtures.
            self.assertEqual(p.resolve(), p)
            self.assertEqual(held.resolve(), held)
            os.rename(p, held)
            replacement = self.zip(b'xyz')
            p.write_bytes(replacement.read_bytes())
            try:
                result = source.read('data/a', max_bytes=3)
            except m.OriginalInputError:
                pass  # A rename may change the original inode's ctime.
            else:
                self.assertEqual(result, b'abc')

    def test_zip64_local_and_descriptor_small_fixtures(self):
        for method in (0, 8):
            for descriptor in (False, True):
                with a.ArchiveSource(self.zip(method=method, descriptor=descriptor,
                                              force_zip64=True), readset()) as source:
                    self.assertEqual(source.read('data/a', max_bytes=3), b'abc')
        p = self.new_path(); p.write_bytes(full_zip64())
        with a.ArchiveSource(p, readset()) as source:
            self.assertEqual(source.read('data/a', max_bytes=3), b'abc')
        raw = bytearray(p.read_bytes()); locator = raw.rfind(b'PK\x06\x07')
        struct.pack_into('<L', raw, locator + 16, 2); p.write_bytes(raw); self.rejects(p)

    def test_unsigned_descriptor_and_zip64_extension_support_boundary(self):
        p = self.zip(method=8, descriptor=True)
        raw = bytearray(p.read_bytes()); indexes, end = locations(raw)
        local, central = indexes['data/a']; n, x = struct.unpack_from('<HH', raw, local + 26)
        compressed = struct.unpack_from('<L', raw, central + 20)[0]
        descriptor = local + 30 + n + x + compressed
        self.assertEqual(raw[descriptor:descriptor + 4], b'PK\x07\x08')
        central_start = struct.unpack_from('<L', raw, end + 16)[0]
        raw = raw[:descriptor] + raw[descriptor + 4:]
        end = raw.rfind(b'PK\x05\x06'); struct.pack_into('<L', raw, end + 16, central_start - 4)
        p.write_bytes(raw)
        with a.ArchiveSource(p, readset()) as source:
            self.assertEqual(source.read('data/a', max_bytes=3), b'abc')
        p = self.new_path(); raw = bytearray(full_zip64()); z_end = raw.index(b'PK\x06\x06')
        struct.pack_into('<Q', raw, z_end + 4, 45); p.write_bytes(raw); self.rejects(p)

    def test_descriptor_corruption_is_metadata_rejection(self):
        p = self.zip(method=8, descriptor=True)
        raw = bytearray(p.read_bytes()); descriptor = raw.index(b'PK\x07\x08')
        struct.pack_into('<L', raw, descriptor + 4, 123); p.write_bytes(raw); self.rejects(p)

    def test_container_mutation_at_start_during_and_after_final_yield(self):
        payload = b'p' * (m.BLOCK * 2)
        for stage in ('before', 'progress', 'final-yield'):
            p = self.zip(payload, method=8)
            def mutate(*_):
                with p.open('ab') as out: out.write(b'changed')
            with a.ArchiveSource(p, readset(payload)) as source:
                if stage == 'before':
                    mutate()
                    with self.assertRaises(m.OriginalInputError): list(source.chunks('data/a'))
                elif stage == 'progress':
                    with self.assertRaises(m.OriginalInputError):
                        source.read('data/a', max_bytes=len(payload), progress=mutate)
                else:
                    stream = source.chunks('data/a')
                    self.assertEqual(len(next(stream)), m.BLOCK)
                    self.assertEqual(len(next(stream)), m.BLOCK)
                    mutate()
                    with self.assertRaises(m.OriginalInputError): next(stream)

    def test_cached_file_chain_nofollow_fifo_directory_and_no_path_reopen(self):
        p = self.zip(); alias = p.with_name('link.zip'); alias.symlink_to(p); self.rejects(alias)
        directory = p.parent / 'link-parent'; directory.symlink_to(p.parent, target_is_directory=True)
        self.rejects(directory / p.name)
        fifo = p.parent / 'fifo'; os.mkfifo(fifo); self.rejects(fifo)
        self.rejects(p.parent)
        self.rejects(Path('relative.zip'))
        self.rejects(p.parent / '..' / p.parent.name / p.name)
        with a.ArchiveSource(p, readset()) as source:
            source.root = p.parent / 'does-not-exist.zip'
            self.assertEqual(source.read('data/a', max_bytes=3), b'abc')
            fd = source._file.fileno()
        with self.assertRaises(OSError): os.fstat(fd)
        source.close()

    def test_archive_can_have_more_entries_than_the_required_readset_limit(self):
        p = self.zip(extras=((f'unused/file-{i:05d}', b'') for i in range(m.MAX_FILES)))
        with a.ArchiveSource(p, readset()) as source:
            self.assertEqual(source.inventory_entries, m.MAX_FILES + 2)
            self.assertEqual(source.read('data/a', max_bytes=3), b'abc')

    def test_search_only_ancestors_allow_archive_and_readable_final_parent(self):
        physics = importlib.import_module(PACKAGE + '.physics_image')
        p = self.zip()
        real_open = os.open
        native_search_flag = getattr(os, 'O_PATH', 0)
        search_flag = native_search_flag or 1 << 29

        def open_with_restricted_ancestors(path, flags, *args, **kwargs):
            if flags & os.O_DIRECTORY and path != '.' and not flags & search_flag:
                raise PermissionError(13, 'Ancestor directory allows search only', path)
            if not native_search_flag:
                flags &= ~search_flag
            return real_open(path, flags, *args, **kwargs)

        with patch.object(os, 'O_PATH', search_flag, create=True), \
                patch.object(os, 'open', side_effect=open_with_restricted_ancestors):
            with a.ArchiveSource(p, readset()) as source:
                self.assertEqual(source.read('data/a', max_bytes=3), b'abc')
            with physics._parent_fd(p) as (directory, name):
                self.assertIn(name, os.listdir(directory))

    def test_budget_checks_precede_zipfile_inventory_allocation(self):
        p = self.zip(extras=[('unused', b'x')])
        for constant, value in [('MAX_ARCHIVE_ENTRIES', 2), ('MAX_CENTRAL_BYTES', 1),
                                ('MAX_FILE_BYTES', 2), ('MAX_TOTAL_BYTES', 4),
                                ('MAX_ARCHIVE_BYTES', 22), ('MAX_DEPTH', 1)]:
            with self.subTest(constant=constant), patch.object(a, constant, value):
                self.rejects(p)
        with patch.object(a, 'MAX_ARCHIVE_ENTRIES', 1), patch.object(a.zipfile, 'ZipFile') as unchecked:
            self.rejects(p)
            unchecked.assert_not_called()
        # Real production 8 GiB cap, using sparse file only in the private fixture tree.
        huge = self.new_path('sparse.zip')
        with huge.open('xb') as out: out.truncate(a.MAX_ARCHIVE_BYTES + 1)
        self.rejects(huge)

    def test_cancellation_constructor_callbacks_and_read(self):
        p = self.zip(b'a' * (m.BLOCK * 3), method=8)
        with self.assertRaises(m.ConversionCancelled):
            a.ArchiveSource(p, readset(), cancel=lambda: True)
        cancelled = [False]
        with self.assertRaises(m.ConversionCancelled):
            a.ArchiveSource(p, readset(b'a' * (m.BLOCK * 3)), cancel=lambda: cancelled[0],
                            progress=lambda *_: cancelled.__setitem__(0, True))
        cancelled[0] = False
        with a.ArchiveSource(p, readset(b'a' * (m.BLOCK * 3)), cancel=lambda: cancelled[0]) as source:
            with self.assertRaises(m.ConversionCancelled):
                source.read('data/a', max_bytes=m.BLOCK * 3, cancel=lambda: True)
            stream = source.chunks('data/a', progress=lambda *_: cancelled.__setitem__(0, True))
            next(stream)
            with self.assertRaises(m.ConversionCancelled): next(stream)

    def test_fd_cleanup_repeated_failures_early_generators_and_close_mid_read(self):
        p = self.zip(b'a' * (m.BLOCK * 3))
        count = lambda: len(os.listdir('/dev/fd'))
        before = count()
        for _ in range(20):
            self.rejects(p, readset(b'ab'))
            with a.ArchiveSource(p, readset(b'a' * (m.BLOCK * 3))) as source:
                stream = source.chunks('data/a'); next(stream); stream.close()
            with a.ArchiveSource(p, readset(b'a' * (m.BLOCK * 3))) as source:
                stream = source.chunks('data/a'); next(stream); source.close()
                with self.assertRaises(m.OriginalInputError): next(stream)
        self.assertLessEqual(count(), before + 1)

    def test_verified_snapshot_bad_main_stops_before_other_members(self):
        p = self.zip()
        parent = Path(tempfile.mkdtemp(prefix='snapshot-', dir=self.root))
        with a.ArchiveSource(p, readset()) as source:
            with self.assertRaises(m.OriginalInputError): m.VerifiedSnapshot.create(source, parent)
        jobs = list(parent.iterdir()); self.assertEqual(len(jobs), 1)
        self.assertTrue((jobs[0] / 'main').is_file())
        self.assertFalse((jobs[0] / 'data').exists())
        self.assertFalse((jobs[0] / 'selection').exists())
        self.assertFalse(hasattr(source, 'publish'))
        with self.assertRaises(m.OriginalInputError): m.VerifiedSnapshot(parent, readset(), 4)

    @unittest.skipUnless(os.environ.get('ORIGINAL_ARCHIVE_MAIN'), 'authorized main opt-in not provided')
    def test_optin_authorized_main_verified_snapshot(self):
        original = Path(os.environ['ORIGINAL_ARCHIVE_MAIN'])
        # Bytes only: no loading, interpretation, execution, original-data writes.
        payload = original.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), m.MAIN_SHA256)
        p = self.zip(prefix='one/two/', method=8)
        with zipfile.ZipFile(p, 'w', compression=8) as z:
            z.writestr('one/two/main', payload)
            z.writestr('one/two/data/a', b'abc')
            z.writestr('one/two/unused', b'not a snapshot member')
        parent = Path(tempfile.mkdtemp(prefix='verified-', dir=self.root))
        with a.ArchiveSource(p, readset(main_size=len(payload))) as source:
            snapshot = m.VerifiedSnapshot.create(source, parent)
        self.assertEqual(snapshot.bytes, len(payload) + 3)
        self.assertEqual(hashlib.sha256((snapshot.root / 'main').read_bytes()).hexdigest(), m.MAIN_SHA256)
        self.assertEqual((snapshot.root / 'data/a').read_bytes(), b'abc')
        self.assertFalse((snapshot.root / 'unused').exists())
        self.assertFalse((snapshot.root / 'selection').exists())
        self.assertEqual(stat.S_IMODE((snapshot.root / 'main').stat().st_mode), 0o400)


def locations_for_gap(raw, offset):
    end = raw.rfind(b'PK\x05\x06')
    copy = bytearray(raw)
    struct.pack_into('<L', copy, end + 16, offset)
    return locations(copy)


def full_zip64():
    """Small real ZIP64 central/end metadata, without allocating huge members."""
    output, central = bytearray(), bytearray()
    for name, payload in [(b'main', b'x'), (b'data/a', b'abc')]:
        crc, offset = zipfile.crc32(payload), len(output)
        extra = struct.pack('<HHQQ', 1, 16, len(payload), len(payload))
        output += struct.pack('<4s5H3L2H', b'PK\x03\x04', 45, 0, 0, 0, 0, crc,
                              0xffffffff, 0xffffffff, len(name), len(extra)) + name + extra + payload
        extra = struct.pack('<HHQQQ', 1, 24, len(payload), len(payload), offset)
        central += struct.pack('<4s6H3L5H2L', b'PK\x01\x02', 45, 45, 0, 0, 0, 0, crc,
                               0xffffffff, 0xffffffff, len(name), len(extra), 0, 0, 0, 0,
                               0xffffffff) + name + extra
    start = len(output); output += central; z_end = len(output)
    output += struct.pack('<4sQ2H2L4Q', b'PK\x06\x06', 44, 45, 45, 0, 0, 2, 2, len(central), start)
    output += struct.pack('<4sLQL', b'PK\x06\x07', 0, z_end, 1)
    output += struct.pack('<4s4H2LH', b'PK\x05\x06', 0, 0, 0xffff, 0xffff, 0xffffffff, 0xffffffff, 0)
    return bytes(output)


if __name__ == '__main__':
    unittest.main()
