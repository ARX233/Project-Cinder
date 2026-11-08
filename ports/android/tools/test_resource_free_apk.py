#!/usr/bin/env python3
"""Synthetic packaging-gate tests; no APK/ELF execution and no device access.
Only metadata (never actual payload) is read for the optional real-metadata case.
Every generated fixture/log stays in a new /Volumes/CodexWork run directory.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

sys.dont_write_bytecode = True
import resource_pack_common as common
import verify_resource_free_apk as gate


def sha(data):
    return hashlib.sha256(data).hexdigest()


def zipped(rows):
    out = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as z:
            for name, data in rows:
                z.writestr(name, data)
    return out.getvalue()


def dmf(files, pin):
    def text(s):
        b = s.encode('utf-8')
        return struct.pack('>i', len(b)) + b
    body = b'DMF1\0\0\0\1' + text(pin) + text('legacy-baseline') + text('re3dxplus-data-v1')
    body += struct.pack('>i', len(files))
    for name, data in sorted(files.items()):
        body += text(name) + struct.pack('>q', len(data)) + text(sha(data))
    body += b'END!'
    return body + hashlib.sha256(body).digest()


class ResourceFreeApkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='resource-free-apk-tests-', dir='/Volumes/CodexWork'))
        os.chmod(cls.root, 0o700)
        cls.main = {f'synthetic/resource-{i:04}.bin': f'synthetic main {i}'.encode()
                    for i in range(1798)}
        cls.manifests = [(pin + '.dmf', dmf(cls.main, pin)) for pin in sorted(common.KNOWN_BASELINES)]
        cls.catalog = zipped(cls.manifests)
        cls.index = common.encode_sidecars({p: common.Entry(1, sha(b'X')) for p in common.SIDECAR_PATHS})
        # Opaque inert code placeholders. This is a packaging test, not a loadable APK.
        cls.required = {'AndroidManifest.xml': b'SYNTHETIC Android binary XML placeholder',
                        'resources.arsc': b'SYNTHETIC resource table placeholder',
                        'classes.dex': b'SYNTHETIC bytecode placeholder - never executed',
                        'lib/arm64-v8a/libwmmt.so': b'SYNTHETIC native placeholder - never executed',
                        'res/mipmap/icon.png': b'SYNTHETIC PNG placeholder'}
        print('\nPackaging-gate fixtures retained: ' + str(cls.root), flush=True)

    def setUp(self):
        self.work = self.root / self._testMethodName
        self.work.mkdir()
        self.number = 0

    def write(self, name, data):
        path = self.work / name
        with path.open('xb') as out:
            out.write(data)
        return path

    def apk(self, *, catalog=None, index=None, remove=(), extra=(), empty=None):
        files = dict(self.required)
        files['assets/data-baselines.zip'] = self.catalog if catalog is None else catalog
        files['assets/sidecars-index-v1.tsv'] = self.index if index is None else index
        for name in remove:
            files.pop(name)
        if empty:
            files[empty] = b''
        self.number += 1
        return self.write(f'synthetic-{self.number}.apk', zipped(list(files.items()) + list(extra)))

    def refuses(self, **kwargs):
        with self.assertRaises((common.ResourceError, zipfile.BadZipFile, OSError)):
            gate.verify(self.apk(**kwargs))

    def test_canonical_two_metadata_assets_positive(self):
        result = gate.verify(self.apk())
        self.assertEqual(result['assets'], sorted(gate.ALLOWED_ASSETS))
        self.assertEqual(result['baseline_ids'], sorted(common.KNOWN_BASELINES))
        self.assertEqual(result['sidecar_count'], 41)
        self.assertFalse(result['external_game_payloads'])
        self.assertFalse(result['reviewed_references_matched'])
        self.assertIn('structure only', result['metadata_authenticity'])
        self.assertTrue(result['compiled_original_derived_code_not_legally_cleared'])
        self.assertFalse(result['apk_signature_or_loadability_verified'])

    def test_expected_files_and_hashes(self):
        apk = self.apk()
        catalog = self.write('reviewed-catalog.zip', self.catalog)
        index = self.write('reviewed-sidecars.tsv', self.index)
        for a, b in ((catalog, index), (sha(self.catalog), sha(self.index)), (catalog, sha(self.index))):
            result = gate.verify(apk, a, b)
            self.assertTrue(result['reviewed_references_matched'])
        for a, b in (('0' * 64, sha(self.index)), (sha(self.catalog), '0' * 64)):
            with self.assertRaisesRegex(common.ResourceError, 'independently reviewed reference'):
                gate.verify(apk, a, b)
        wrong = self.write('unreviewed.tsv', b'wrong reference')
        with self.assertRaises(common.ResourceError):
            gate.verify(apk, catalog, wrong)

    def test_every_required_member_is_mandatory_and_nonempty(self):
        for name in gate.REQUIRED_FILES:
            with self.subTest(missing=name):
                self.refuses(remove=(name,))
            with self.subTest(empty=name):
                self.refuses(empty=name)
        for name in gate.ALLOWED_ASSETS:
            with self.subTest(missing=name):
                self.refuses(remove=(name,))

    def test_no_resource_or_meta_inf_prefix_escape(self):
        for name in ('res/raw/unreviewed.dat', 'res/raw/game.wpk', 'res/raw/hidden.txt',
                     'res/mipmap-v4/icon.png', 'res/drawable/icon.png', 'res/mipmap/extra.png',
                     'META-INF/hidden.dat', 'META-INF/private.key', 'META-INF/CERT.PEM',
                     'META-INF/services/evil', 'assets/game.dat', 'classes2.dex',
                     'lib/arm64-v8a/other.so', 'lib/x86/libwmmt.so', 'main', 'saves/garage1'):
            with self.subTest(name=name):
                self.refuses(extra=[(name, b'SYNTHETIC UNREVIEWED DATA')])
        self.refuses(extra=[('res/raw/', b'')])

    def test_original_falsepass_minimal_catalog_and_traversal_tsv(self):
        catalog = zipped([('0' * 64 + '.dmf', b'DMF1THIS IS NOT A VALID INVENTORY')])
        index = b'WMMT-SIDECARS-1\n' + (b'../../wmmt/garage1\t1\t' + b'0' * 64 + b'\n') * 41
        self.refuses(catalog=catalog, index=index,
                     extra=[('res/raw/unreviewed.dat', b'SYNTHETIC HIDDEN PAYLOAD')])
        # No prefix-based shortcut: even with all required opaque APK members,
        # these original metadata false-pass components must fail independently.
        self.refuses(catalog=catalog)
        self.refuses(index=index)

    def test_bad_dmf_checksum_end_trailing_and_unknown_identity(self):
        pin, valid = self.manifests[0]
        for data in (b'DMF1only', valid[:-1], valid + b'junk', valid[:40] + bytes([valid[40] ^ 1]) + valid[41:]):
            self.refuses(catalog=zipped([(pin, data), self.manifests[1]]))
        body = valid[:-36] + b'BAD!'
        self.refuses(catalog=zipped([(pin, body + hashlib.sha256(body).digest()), self.manifests[1]]))
        unknown = '0' * 64
        self.refuses(catalog=zipped([(unknown + '.dmf', dmf(self.main, unknown)), self.manifests[1]]))
        self.refuses(catalog=zipped([self.manifests[0]]))  # Both approved versions required.
        self.refuses(catalog=zipped(self.manifests + [('payload.dat', b'not metadata')]))
        self.refuses(catalog=zipped(self.manifests + [self.manifests[0]]))

    def test_sidecar_duplicate_unsafe_unsorted_unknown_and_format(self):
        lines = self.index.splitlines(keepends=True)
        cases = [lines[0] + lines[1] + b''.join(lines[1:-1]),
                 lines[0] + b''.join(reversed(lines[1:])),
                 self.index.replace(b'backfire.bfx', b'../../wmmt/garage1', 1),
                 self.index.replace(b'backfire.bfx', b'not-approved.bin', 1),
                 self.index.replace(b'\t1\t', b'\t01\t', 1),
                 self.index.replace(b'\t' + sha(b'X').encode(), b'\t' + sha(b'X').upper().encode(), 1),
                 self.index.replace(b'\n', b'\r\n'), self.index[:-1], self.index + b'X' * 65536,
                 lines[0] + b''.join(lines[2:])]
        for n, index in enumerate(cases):
            with self.subTest(n=n):
                self.refuses(index=index)

    def test_outer_duplicate_casefold_traversal_and_symlink(self):
        for name in ('classes.dex', 'CLASSES.DEX', '../escaped', 'res/mipmap/../evil', 'res\\raw\\evil'):
            with self.subTest(name=name):
                self.refuses(extra=[(name, b'SYNTHETIC')])
        info = zipfile.ZipInfo('META-INF/EVIL.SF')
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        self.refuses(extra=[(info, b'../user-file')])
        link = self.work / 'source-link.apk'
        link.symlink_to(self.apk())
        with self.assertRaises(OSError):
            gate.verify(link)

    def test_outer_central_crc_and_trailing_damage(self):
        source = self.apk().read_bytes()
        for label, data in [('trailing', source + b'junk'), ('truncated', source[:-22])]:
            with self.subTest(label=label), self.assertRaises(common.ResourceError):
                gate.verify(self.write(label + '.apk', data))
        info = zipfile.ZipFile(io.BytesIO(source)).getinfo('classes.dex')
        damaged = bytearray(source)
        name, extra = struct.unpack_from('<HH', damaged, info.header_offset + 26)
        damaged[info.header_offset + 30 + name + extra] ^= 1
        with self.assertRaisesRegex(common.ResourceError, 'CRC'):
            gate.verify(self.write('bad-crc.apk', bytes(damaged)))
        damaged = bytearray(source)
        damaged[info.header_offset + 30] ^= 1
        with self.assertRaisesRegex(common.ResourceError, 'name mismatch'):
            gate.verify(self.write('bad-central.apk', bytes(damaged)))

    def test_public_signature_profile(self):
        oid = bytes.fromhex('06092a864886f70d010702')
        public = [('META-INF/MANIFEST.MF', b'Manifest-Version: 1.0\r\n\r\n'),
                  ('META-INF/WMMT.SF', b'Signature-Version: 1.0\r\n\r\n'),
                  ('META-INF/WMMT.RSA', b'\x30\x0d' + oid + b'\xa0\x00')]
        self.assertFalse(gate.verify(self.apk(extra=public))['apk_signature_or_loadability_verified'])
        for rows in (public[:1], public[1:], public[:-1],
                     public[:-1] + [('META-INF/WMMT.RSA', b'NOT PUBLIC DER')],
                     public + [('META-INF/WMMT.DSA', public[-1][1])],
                     [(public[0][0], b'Manifest-Version: 1.0\n\n')] + public[1:]):
            self.refuses(extra=rows)

    def test_legal_parent_directory_entries_allowed_only(self):
        parents = [('assets/', b''), ('lib/', b''), ('lib/arm64-v8a/', b''),
                   ('res/', b''), ('res/mipmap/', b'')]
        gate.verify(self.apk(extra=parents))
        self.refuses(extra=[('unexpected-empty-directory/', b'')])

    def test_budgets_and_reference_symlinks(self):
        apk = self.apk()
        with patch.object(gate, 'MAX_APK', 22), self.assertRaises(common.ResourceError):
            gate.verify(apk)
        with patch.object(gate, 'MAX_EXPANDED', 16), self.assertRaises(common.ResourceError):
            gate.verify(apk)
        reference = self.write('actual-reference.tsv', self.index)
        link = self.work / 'reference-link.tsv'
        link.symlink_to(reference)
        with self.assertRaises(OSError):
            gate.verify(apk, None, link)

    def test_cli_compatibility_and_reference_flags(self):
        tools = Path(__file__).resolve().parent
        apk = self.apk()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(self.work))
        for n, args in enumerate(([str(apk)], [str(apk), '--expected-baselines', sha(self.catalog),
                                                '--expected-sidecars', sha(self.index)])):
            result = subprocess.run([sys.executable, '-B', str(tools / 'verify_resource_free_apk.py'), *args],
                                    cwd=self.work, env=env, text=True, capture_output=True)
            self.write(f'cli-{n}.log', (result.stdout + result.stderr).encode())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['reviewed_references_matched'], n == 1)
        result = subprocess.run([sys.executable, '-B', str(tools / 'verify_resource_free_apk.py'),
                                str(apk), '--expected-sidecars', '0' * 64],
                                cwd=self.work, env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('verification refused', result.stderr)

    def test_real_reviewed_metadata_positive_without_game_payload(self):
        catalog = Path('/Volumes/CodexWork/android-upgrade-fix-20261102-GWHSt8/catalog-current/data-baselines.zip')
        index = Path('/Volumes/CodexWork/android134-resource-free-P8mwiu/resource-tools/metadata-approved-133/sidecars-index-v1.tsv')
        if not catalog.is_file() or not index.is_file():
            self.skipTest('private reviewed metadata fixture is not available; no payload needed')
        self.assertEqual(common.file_sha256(catalog), '858dcd225e620479bd6fa8b19837e6c96aa48aeac62e246a2ecb81a83737946d')
        self.assertEqual(common.file_sha256(index), '41cdc2c0c4a034959a9c2fca01ae3020f29a12df02aee3413347516362848439')
        result = gate.verify(self.apk(catalog=catalog.read_bytes(), index=index.read_bytes()), catalog, index)
        self.assertEqual(result['sidecar_count'], 41)
        self.assertTrue(result['reviewed_references_matched'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
