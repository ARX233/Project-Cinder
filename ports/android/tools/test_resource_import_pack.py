#!/usr/bin/env python3
"""Host tests: only synthetic payload, all fixtures/logs under /Volumes/CodexWork.
Retain each new run for review; never execute/install an APK or original ELF.
Run with python3 -B tools/test_resource_import_pack.py from ports/android.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import patch
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_resource_metadata as builder
import resource_import_pack as packer
import resource_pack_common as common


def digest(data):
    return hashlib.sha256(data).hexdigest()


def zip_bytes(rows, *, compression=zipfile.ZIP_STORED, comment=b''):
    target = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(target, 'w', compression=compression, allowZip64=False) as archive:
            archive.comment = comment
            for path, data in rows:
                archive.writestr(path, data)
    return target.getvalue()


def dmf(files, pin=None, *, directory='legacy-baseline', identity='re3dxplus-data-v1'):
    pin = pin or sorted(common.KNOWN_BASELINES)[0]
    def text(s):
        b = s.encode('utf-8')
        return struct.pack('>i', len(b)) + b
    body = b'DMF1\0\0\0\1' + text(pin) + text(directory) + text(identity) + struct.pack('>i', len(files))
    for path, data in sorted(files.items()):
        body += text(path) + struct.pack('>q', len(data)) + text(digest(data))
    body += b'END!'
    return body + hashlib.sha256(body).digest()


def strict(data, **overrides):
    limits = dict(max_bytes=4_000_000, max_entries=20000, max_total=8_000_000)
    limits.update(overrides)
    return common.StrictZip(io.BytesIO(data), **limits)


class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = Path('/Volumes/CodexWork/android134-resource-free-P8mwiu/resource-tools')
        parent.mkdir(parents=True, exist_ok=True)
        cls.root = Path(tempfile.mkdtemp(prefix='synthetic-host-tests-', dir=parent))
        os.chmod(cls.root, 0o700)
        cls.main = {f'synthetic/resource-{n:04}.bin': f'synthetic-resource-{n}'.encode()
                    for n in range(common.MAIN_COUNT)}
        cls.sidecars = {path: ('synthetic-sidecar:' + path).encode()
                        for path in common.SIDECAR_PATHS}
        cls.card = {p: cls.sidecars['card-resources/' + p] for p in common.CARD_PATHS}
        cls.rows = {p: common.Entry(len(b), digest(b)) for p, b in cls.sidecars.items()}
        cls.metadata = common.encode_sidecars(cls.rows)
        cls.pin = sorted(common.KNOWN_BASELINES)[0]
        cls.catalog_data = zip_bytes([(cls.pin + '.dmf', dmf(cls.main))])
        cls.catalog = cls.root / 'approved-synthetic-catalog.zip'
        cls.catalog.write_bytes(cls.catalog_data)
        cls.index = cls.root / 'approved-synthetic-sidecars.tsv'
        cls.index.write_bytes(cls.metadata)
        cls.apk_data = cls.make_apk()
        cls.apk = cls.root / 'owned-synthetic.apk'
        cls.apk.write_bytes(cls.apk_data)
        print('\nSynthetic fixtures retained: ' + str(cls.root), flush=True)

    @classmethod
    def make_apk(cls, main=None, card=None, extras=(), method=zipfile.ZIP_STORED):
        main_bytes = zip_bytes(sorted((cls.main if main is None else main).items()),
                               compression=method, comment=b'repacked synthetic container')
        card_bytes = zip_bytes(sorted((cls.card if card is None else card).items()))
        assets = [('assets/re3dxplus-data.zip', main_bytes),
                  ('assets/card-resources-v1.zip', card_bytes),
                  ('assets/data-baselines.zip', cls.catalog_data)]
        assets += [('assets/' + p, cls.sidecars[p]) for p in common.TOP4]
        # Deliberately inert placeholders, not executable code or player saves.
        ignored = [(p, b'SYNTHETIC MUST NOT ENTER RESOURCE OUTPUT') for p in
                   ('classes.dex', 'AndroidManifest.xml', 'lib/arm64-v8a/libdummy.so',
                    'META-INF/CERT.SF', 'saves/profile.sav', 'main', 'launcher')]
        return zip_bytes(assets + ignored + list(extras))

    def setUp(self):
        self.work = self.root / self._testMethodName
        self.work.mkdir()

    def write(self, name, data):
        path = self.work / name
        path.write_bytes(data)
        return path

    def reject_pack(self, apk=None, index=None, catalog=None):
        output = self.work / 'rejected.zip'
        sentinel = self.write('user-save.sav', b'USER DATA UNCHANGED')
        with self.assertRaises((common.ResourceError, zipfile.BadZipFile)):
            packer.pack(apk or self.apk, catalog or self.catalog, index or self.index, output)
        self.assertFalse(output.exists())
        self.assertEqual(sentinel.read_bytes(), b'USER DATA UNCHANGED')

    def test_generator_metadata_only_and_receipt(self):
        out = self.work / 'metadata'
        index, receipt = builder.generate(self.apk, digest(self.apk_data), out)
        self.assertEqual(index.read_bytes(), self.metadata)
        self.assertEqual(set(p.name for p in out.iterdir()), {'sidecars-index-v1.tsv', 'receipt.json'})
        evidence = json.loads(receipt.read_text())
        self.assertEqual(evidence['sidecar_count'], 41)
        self.assertEqual(evidence['ios_payload_count_excluding_card_manifest'], 40)
        self.assertFalse(evidence['payload_written'])
        self.assertEqual(len(evidence['assets']), 7)
        self.assertEqual(evidence['metadata_sha256'], digest(self.metadata))

    def test_wrong_approved_apk_pin_is_not_promoted(self):
        out = self.work / 'metadata'
        with self.assertRaisesRegex(common.ResourceError, 'approved SHA'):
            builder.generate(self.apk, '0' * 64, out)
        self.assertFalse(out.exists())

    def test_generator_wrong_asset_pin(self):
        pins = {key: {'size': 1, 'sha256': '0' * 64} for key in builder.ASSET_KEYS}
        path = self.write('wrong-inputs.json', json.dumps(pins).encode())
        with self.assertRaisesRegex(common.ResourceError, 'asset pin mismatch'):
            builder.generate(self.apk, digest(self.apk_data), self.work / 'metadata', path)

    def test_generator_card_java_spec_cross_check(self):
        manifest = self.rows['card-resources/manifest.json']
        source = f'MANIFEST_SIZE={manifest.size}L; MANIFEST_SHA="{manifest.sha256}";\n'
        for path, data in sorted(self.card.items()):
            if path != 'manifest.json':
                source += f'new Spec("{path}", {len(data)}L, "{digest(data)}");\n'
        path = self.write('CardResources.java', source.encode())
        builder.generate(self.apk, digest(self.apk_data), self.work / 'good', card_spec=path)
        wrong = self.write('wrong-spec.java', source.replace(manifest.sha256, '0' * 64).encode())
        with self.assertRaisesRegex(common.ResourceError, 'SHA-256 mismatch'):
            builder.generate(self.apk, digest(self.apk_data), self.work / 'bad', card_spec=wrong)

    def test_flat_resource_pack_and_reproducibility(self):
        first, second = self.work / 'first.zip', self.work / 'second.zip'
        with patch.object(tempfile, 'gettempdir', side_effect=AssertionError('no system temp')):
            receipt = packer.pack(self.apk, self.catalog, self.index, first)
        repacked = self.write('rezipped.apk', self.make_apk(method=zipfile.ZIP_DEFLATED))
        other = packer.pack(repacked, self.catalog, self.index, second)
        self.assertEqual(Path(receipt['staging_directory']).parent, first.parent)
        self.assertEqual(Path(other['staging_directory']).parent, second.parent)
        self.assertIn('CREATE_NEW', receipt['publication'])
        self.assertEqual(receipt['output_sha256'], other['output_sha256'])
        self.assertFalse(receipt['source_main_container_is_reviewed_hash'])
        self.assertEqual(receipt['output_file_count'], 1839)
        self.assertEqual(receipt['matching_reviewed_baselines'], [self.pin])
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(set(archive.namelist()), self.main.keys() | self.sidecars.keys())
            self.assertEqual(archive.namelist(), sorted(archive.namelist()))
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.external_attr >> 16, 0o100644)
                self.assertNotIn(info.filename, ('classes.dex', 'AndroidManifest.xml', 'main', 'launcher'))
                self.assertFalse(info.filename.startswith(('data/', 'lib/', 'META-INF/', 'saves/')))
            self.assertIsNone(archive.testzip())
        self.assertEqual(common.file_sha256(first), receipt['output_sha256'])
        self.assertTrue(Path(str(first) + '.receipt.json').is_file())

    def test_both_known_baselines_are_supported(self):
        pin = sorted(common.KNOWN_BASELINES)[1]
        catalog = self.write('second-approved.zip', zip_bytes([(pin + '.dmf', dmf(self.main, pin))]))
        result = packer.pack(self.apk, catalog, self.index, self.work / 'second-baseline.zip')
        self.assertEqual(result['matching_reviewed_baselines'], [pin])

    def test_wrong_main_hash(self):
        main = dict(self.main)
        key = next(iter(main))
        main[key] = b'X' * len(main[key])  # Same size, wrong hash.
        self.reject_pack(apk=self.write('wrong-main.apk', self.make_apk(main=main)))

    def test_wrong_main_membership(self):
        main = dict(self.main)
        main['unreviewed.bin'] = main.pop(next(iter(main)))
        self.reject_pack(apk=self.write('wrong-member.apk', self.make_apk(main=main)))

    def test_wrong_sidecar_pin(self):
        rows = dict(self.rows)
        rows['backfire.bfx'] = common.Entry(rows['backfire.bfx'].size, '0' * 64)
        self.reject_pack(index=self.write('wrong-pin.tsv', common.encode_sidecars(rows)))

    def test_unknown_nested_card_file(self):
        card = dict(self.card)
        card['unauthorized.bin'] = b'not-approved'
        self.reject_pack(apk=self.write('extra-card.apk', self.make_apk(card=card)))

    def test_duplicate_outer_member(self):
        self.reject_pack(apk=self.write('duplicate.apk', self.make_apk(extras=[('assets/backfire.bfx', b'duplicate')])))

    def test_existing_outputs_and_receipts_preserved(self):
        for name, kind in [('file.zip', 'file'), ('dir.zip', 'dir'), ('link.zip', 'link')]:
            output = self.work / name
            if kind == 'dir':
                output.mkdir()
            elif kind == 'link':
                output.symlink_to(self.work / 'absent-target')
            else:
                output.write_bytes(b'USER OUTPUT')
            with self.assertRaises(common.ResourceError):
                packer.pack(self.apk, self.catalog, self.index, output)
            self.assertTrue(os.path.lexists(output))
            if kind == 'file':
                self.assertEqual(output.read_bytes(), b'USER OUTPUT')
        output = self.work / 'existing-receipt.zip'
        receipt = self.write('existing-receipt.zip.receipt.json', b'USER RECEIPT')
        with self.assertRaises(common.ResourceError):
            packer.pack(self.apk, self.catalog, self.index, output)
        self.assertEqual(receipt.read_bytes(), b'USER RECEIPT')
        self.assertFalse(output.exists())
        metadata = self.work / 'existing-metadata'
        metadata.mkdir()
        with self.assertRaises(common.ResourceError):
            builder.generate(self.apk, digest(self.apk_data), metadata)
        self.assertEqual(list(metadata.iterdir()), [])

    def test_dmf_damage_and_unknown_baseline(self):
        data = dmf(self.main)
        for bad in (data[:-1], data + b'junk', data[:30] + bytes([data[30] ^ 1]) + data[31:]):
            with self.assertRaises(common.ResourceError):
                common.parse_dmf(bad)
        for pin in ('0' * 64, 'A' * 64):
            catalog = zip_bytes([(pin + '.dmf', dmf(self.main, pin))])
            with self.assertRaises(common.ResourceError):
                common.load_catalog(io.BytesIO(catalog))
        with self.assertRaises(common.ResourceError):
            common.parse_dmf(dmf(self.main, identity='invented-trust'))

    def test_dmf_cannot_authorize_code_or_saves(self):
        for unsafe in ('main', 'launcher.bin', 'classes.dex', 'lib/game.so', 'AndroidManifest.xml',
                       'save/profile.bin', 'player.sav', 'x/../../escaped.bin'):
            files = dict(self.main)
            files[unsafe] = files.pop(next(iter(files)))
            with self.subTest(unsafe=unsafe), self.assertRaises(common.ResourceError):
                common.parse_dmf(dmf(files))

    def test_metadata_strict_format_and_limits(self):
        lines = self.metadata.splitlines(keepends=True)
        cases = [self.metadata[:-1], b'wrong\n' + self.metadata, self.metadata.replace(b'\n', b'\r\n'),
                 lines[0] + b''.join(reversed(lines[1:])), self.metadata + lines[1],
                 self.metadata.replace(b'backfire.bfx', b'../backfire.bfx', 1),
                 self.metadata.replace(b'\t' + next(iter(self.rows.values())).sha256.encode(), b'\tNOHASH'),
                 self.metadata.replace(b'\t', b'\t0', 1), self.metadata + b'X' * 65536,
                 lines[0] + lines[1] * 513, lines[0] + b''.join(lines[2:])]
        for n, data in enumerate(cases):
            with self.subTest(n=n), self.assertRaises(common.ResourceError):
                common.parse_sidecars(data)
        self.assertEqual(common.parse_sidecars(self.metadata), self.rows)

    def test_zip_path_duplicate_normalization_and_special_files(self):
        cases = [ [('x', b'a'), ('x', b'b')], [('x', b'a'), ('X', b'b')],
                  [('Dir/a', b'a'), ('dir/b', b'b')], [('x', b'a'), ('x/y', b'b')],
                  [('caf\u00e9', b'a'), ('cafe\u0301', b'b')]]
        cases += [[(path, b'bad')] for path in ('../x', '/x', 'x/./y', 'x//y', 'x\\y',
                   'C:x', 'x\n', 'x.', 'mods/x', '.overlay-fake/x')]
        # ZipFile.writestr truncates NUL itself: patch raw central/local names so
        # the hostile bytes actually reach our reader instead of testing 'x'.
        with self.assertRaises(common.ResourceError):
            strict(zip_bytes([('x?hidden', b'bad')]).replace(b'x?hidden', b'x\0hidden'))
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(common.ResourceError):
                strict(zip_bytes(rows))
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600, stat.S_IFSOCK | 0o600):
            info = zipfile.ZipInfo('unsafe-link')
            info.create_system = 3
            info.external_attr = mode << 16
            with self.subTest(mode=mode), self.assertRaises(common.ResourceError):
                strict(zip_bytes([(info, b'link target')]))

    def test_zip_structural_anomalies_crc_and_budgets(self):
        original = zip_bytes([('safe.bin', b'12345678')])
        cd = original.index(b'PK\x01\x02')
        end = original.index(b'PK\x05\x06')
        corruptions = []
        b = bytearray(original); b[30] ^= 1; corruptions.append(bytes(b))  # Local name.
        b = bytearray(original); struct.pack_into('<I', b, cd+42, 1); corruptions.append(bytes(b))
        b = bytearray(original); struct.pack_into('<H', b, end+8, 2); corruptions.append(bytes(b))
        b = bytearray(original); struct.pack_into('<H', b, cd+8, 1); corruptions.append(bytes(b))
        b = bytearray(original); struct.pack_into('<I', b, cd+20, 0xffffffff); corruptions.append(bytes(b))
        corruptions += [original[:-10], original + b'junk']
        # Gap before central with all end coordinates updated is still invalid.
        b = bytearray(original[:cd] + b'GAP' + original[cd:])
        struct.pack_into('<I', b, end+3+16, cd+3); corruptions.append(bytes(b))
        for n, data in enumerate(corruptions):
            with self.subTest(n=n), self.assertRaises(common.ResourceError):
                strict(data)
        b = bytearray(original); b[30+len('safe.bin')] ^= 1
        with strict(bytes(b)) as archive, self.assertRaises(common.ResourceError):
            archive.consume('safe.bin', limit=8)
        for limits in ({'max_bytes': 22}, {'max_entries': 0}, {'max_total': 7}, {'max_file': 7}):
            with self.subTest(limits=limits), self.assertRaises(common.ResourceError):
                strict(original, **limits)

    def test_deflate_truncation_and_hidden_compressed_bytes(self):
        data = zip_bytes([('safe.bin', b'ABCD' * 3000)], compression=zipfile.ZIP_DEFLATED)
        with strict(data) as archive:
            self.assertEqual(archive.consume('safe.bin', limit=12000).size, 12000)
        cd, end = data.index(b'PK\x01\x02'), data.index(b'PK\x05\x06')
        b = bytearray(data[:cd] + b'HIDDEN' + data[cd:])
        packed = struct.unpack_from('<I', b, 18)[0] + 6
        struct.pack_into('<I', b, 18, packed)
        struct.pack_into('<I', b, cd+6+20, packed)
        struct.pack_into('<I', b, end+6+16, cd+6)
        with strict(bytes(b)) as archive, self.assertRaisesRegex(common.ResourceError, 'trailing compressed'):
            archive.consume('safe.bin', limit=12000)

    def test_apk_signing_block_gap_and_descriptor(self):
        original = zip_bytes([('safe.bin', b'12345678')])
        cd, end = original.index(b'PK\x01\x02'), original.index(b'PK\x05\x06')
        pair = struct.pack('<QI', 4, 0x7109871a)
        size = len(pair) + 24
        block = struct.pack('<Q', size) + pair + struct.pack('<Q', size) + b'APK Sig Block 42'
        b = bytearray(original[:cd] + block + original[cd:])
        struct.pack_into('<I', b, end+len(block)+16, cd+len(block))
        with strict(bytes(b), apk=True) as archive:
            archive.consume('safe.bin', limit=8)
        with self.assertRaises(common.ResourceError):
            strict(bytes(b))
        b[cd+8] ^= 1
        with self.assertRaises(common.ResourceError):
            strict(bytes(b), apk=True)
        # Real apksigner can align the signing block with a bounded all-zero gap.
        padding = b'\0' * ((-cd) % 4096)
        aligned = bytearray(original[:cd] + padding + block + original[cd:])
        struct.pack_into('<I', aligned, end+len(padding)+len(block)+16,
                         cd+len(padding)+len(block))
        with strict(bytes(aligned), apk=True) as archive:
            archive.consume('safe.bin', limit=8)
        aligned[cd] = 1
        with self.assertRaises(common.ResourceError):
            strict(bytes(aligned), apk=True)
        # Valid unseekable writer emits a descriptor; corrupt descriptor is rejected.
        class Unseekable(io.BytesIO):
            def seekable(self): return False
            def seek(self, *args): raise io.UnsupportedOperation()
        out = Unseekable()
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('descriptor.bin', b'synthetic descriptor')
        data = out.getvalue()
        with strict(data) as archive:
            archive.consume('descriptor.bin', limit=100)
        b = bytearray(data); at = b.index(b'PK\x07\x08'); b[at+4] ^= 1
        with self.assertRaises(common.ResourceError):
            strict(bytes(b))

    def test_zip_extra_fields_and_apk_local_padding(self):
        # Zero padding is an outer APK LOCAL-header compatibility rule, not a
        # general escape from duplicate/unknown extra validation.
        common.StrictZip._extras(b'\0' * 8 + struct.pack('<HHH', 0xd935, 2, 4),
                                 allow_zero_padding=True)
        with self.assertRaises(common.ResourceError):
            common.StrictZip._extras(b'\0' * 8 + struct.pack('<HHH', 0xd935, 2, 4))
        for extra in (struct.pack('<HH', 1, 0), struct.pack('<HH', 0x7075, 0),
                      struct.pack('<HH', 0x9901, 0), b'X',
                      struct.pack('<HH', 0x5455, 0) * 2):
            info = zipfile.ZipInfo('safe.bin')
            info.extra = extra
            with self.subTest(extra=extra), self.assertRaises((common.ResourceError, zipfile.BadZipFile)):
                strict(zip_bytes([(info, b'synthetic')]))

    def test_input_symlink_and_explicit_portable_output(self):
        link = self.work / 'apk-link'
        link.symlink_to(self.apk)
        with self.assertRaises(OSError):
            with common.regular_input(link, common.MAX_APK):
                self.fail('symlink opened')
        # Native writes remain entirely on the external test volume. POSIX/Windows
        # paths elsewhere are pure validation inputs, never opened or created.
        valid = (PurePosixPath('/home/player/owned/new-runtime.zip'),
                 PureWindowsPath(r'C:\Users\player\owned\new-runtime.zip'),
                 PureWindowsPath(r'\\server\share\owned\new-runtime.zip'))
        for path in valid:
            with self.subTest(valid=path):
                self.assertEqual(common.validate_output_shape(path), path)
        invalid = (PurePosixPath('relative.zip'), PurePosixPath('/'),
                   PurePosixPath('/home/player/../unexpected.zip'),
                   PureWindowsPath(r'C:relative.zip'), PureWindowsPath(r'\root-relative.zip'),
                   PureWindowsPath(r'C:\owned\..\unexpected.zip'),
                   PureWindowsPath(r'C:\owned\new.zip:stream'),
                   PureWindowsPath(r'C:\owned\CON.zip'), PureWindowsPath(r'C:\owned\NUL'),
                   PureWindowsPath(r'C:\owned\COM1.zip'), PureWindowsPath(r'C:\owned\CON .zip'),
                   PureWindowsPath(r'C:\owned\name.zip.'), PureWindowsPath('C:\\owned\\name.zip '),
                   PureWindowsPath(r'\\.\C:\owned\new.zip'),
                   PureWindowsPath(r'\\?\C:\owned\new.zip'))
        for path in invalid:
            with self.subTest(invalid=path), self.assertRaises(common.ResourceError):
                common.validate_output_shape(path)
        # Simulate Windows directory/reparse metadata without Windows I/O or
        # claiming that any Windows filesystem/device has actually been tested.
        win_parent = PureWindowsPath(r'C:\Users\player\owned')
        seen = []
        def directory_probe(path):
            seen.append(path)
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=0)
        common.check_output_parent(win_parent, directory_probe)
        self.assertEqual(seen, list(reversed((win_parent, *win_parent.parents))))
        for mode, attributes in ((stat.S_IFLNK | 0o777, 0), (stat.S_IFDIR | 0o700, 0x400),
                                 (stat.S_IFREG | 0o600, 0)):
            def bad_probe(path, mode=mode, attributes=attributes):
                return (SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
                        if path == win_parent else directory_probe(path))
            with self.subTest(mode=mode, attributes=attributes), self.assertRaises(common.ResourceError):
                common.check_output_parent(win_parent, bad_probe)
        fresh = self.work / 'explicit-output.zip'
        self.assertEqual(common.new_output(fresh), fresh)
        self.assertEqual(common.external_destination(fresh), fresh)  # Compatibility alias.
        self.assertFalse(fresh.exists())
        for path in (Path('relative.zip'), self.work / '..' / 'unexpected.zip'):
            with self.assertRaises(common.ResourceError):
                common.new_output(path)
        real_parent = self.work / 'existing-parent'
        real_parent.mkdir()
        (real_parent / 'nested').mkdir()
        alias = self.work / 'parent-alias'
        alias.symlink_to(real_parent, target_is_directory=True)
        for path in (alias / 'new.zip', alias / 'nested' / 'new.zip'):
            with self.assertRaises(common.ResourceError):
                common.new_output(path)
        with self.assertRaises(OSError):
            common.new_output(self.work / 'missing-parent' / 'new.zip')
        non_directory = self.write('not-a-directory', b'USER FILE')
        with self.assertRaises(common.ResourceError):
            common.new_output(non_directory / 'new.zip')
        self.assertEqual(non_directory.read_bytes(), b'USER FILE')
        # CREATE_NEW copy works without hard-link/rename/delete support; all
        # targets remain fresh siblings inside this explicit external parent.
        source = self.write('publication-source.bin', b'SYNTHETIC portable publication')
        expected = common.Entry(source.stat().st_size, common.file_sha256(source))
        output = self.work / 'published.bin'
        with patch.object(common.os, 'link', side_effect=AssertionError('no hard links')), \
             patch.object(common.os, 'rename', side_effect=AssertionError('no rename')), \
             patch.object(common.os, 'unlink', side_effect=AssertionError('no deletion')):
            common.publish_exclusive(source, output, expected)
        self.assertEqual(output.read_bytes(), source.read_bytes())
        with self.assertRaises(common.ResourceError):
            common.publish_exclusive(source, output, expected)
        self.assertEqual(output.read_bytes(), b'SYNTHETIC portable publication')
        failed = self.work / 'failed-new-publication.bin'
        with self.assertRaises(common.ResourceError):
            common.publish_exclusive(source, failed, common.Entry(expected.size, '0' * 64))
        self.assertTrue(failed.is_file())  # Failed new objects are retained, never deleted.
        self.assertEqual(source.read_bytes(), b'SYNTHETIC portable publication')

    def test_cli_help_copyright_and_documentation(self):
        tools = Path(__file__).resolve().parent
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(self.work))
        for name in ('resource_import_pack.py', 'build_resource_metadata.py'):
            result = subprocess.run([sys.executable, '-B', str(tools / name), '--help'],
                                    env=env, cwd=self.work, capture_output=True, text=True)
            (self.work / (name + '.help.txt')).write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, '-B', str(tools / 'resource_import_pack.py'),
                                '--from-apk', str(self.apk), '--catalog', str(self.catalog),
                                '--sidecars-index', str(self.index), '--output', str(self.work / 'cli.zip')],
                                env=env, cwd=self.work, capture_output=True, text=True)
        (self.work / 'cli.log').write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('do not redistribute', result.stdout)
        doc = (tools.parent / 'docs/RESOURCE_IMPORT_TOOL.md').read_text()
        self.assertIn('不是原版转换器', doc)
        self.assertIn('版权', doc)
        self.assertIn('classes.dex', doc)
        self.assertIn('IGB', doc)


if __name__ == '__main__':
    unittest.main(verbosity=2)
