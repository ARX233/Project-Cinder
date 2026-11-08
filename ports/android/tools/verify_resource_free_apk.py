#!/usr/bin/env python3
"""Verify the exact resource-free APK packaging profile without executing code.

Bare APK argument checks structure, CRCs and complete canonical inventories.
Optional --expected-baselines/--expected-sidecars accept a reviewed reference
file or a lowercase SHA-256; builders should supply BOTH. A checksum or DMF name
is not authenticity. This is NOT APK signature/loadability verification or
copyright/legal clearance of the compiled original-derived native code.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile
import zlib

sys.dont_write_bytecode = True
from resource_pack_common import (HASH, KNOWN_BASELINES, MAX_CATALOG, MAX_INDEX,
    ResourceError, StrictZip, load_catalog, parse_sidecars, regular_input, require,
    sha256)

MAX_APK = 64 * 1024**2
MAX_EXPANDED = 128 * 1024**2
MAX_SIGNATURE = 1024 * 1024
ALLOWED_ASSETS = frozenset({'assets/data-baselines.zip', 'assets/sidecars-index-v1.tsv'})
REQUIRED_FILES = frozenset({'AndroidManifest.xml', 'resources.arsc', 'classes.dex',
    'lib/arm64-v8a/libwmmt.so', 'res/mipmap/icon.png'})
ALLOWED_DIRECTORIES = frozenset({'assets/', 'lib/', 'lib/arm64-v8a/',
                               'res/', 'res/mipmap/', 'META-INF/'})
SIGNER = re.compile(r'META-INF/([A-Za-z0-9_-]{1,8})\.(SF|RSA|DSA|EC)\Z')


def expected_digest(value, limit):
    if value is None:
        return None
    literal = str(value)
    if HASH.fullmatch(literal):
        return literal
    with regular_input(Path(value), limit) as source:
        return sha256(source)


def signature_text(data, first):
    """Bound the public JAR signature text profile, not its cryptographic proof."""
    require(0 < len(data) <= MAX_SIGNATURE and data.startswith(first + b'\r\n'),
            'invalid public signature text header')
    require(data.endswith(b'\r\n\r\n') and b'\0' not in data,
            'invalid public signature text termination')
    # JAR manifests are CRLF records with continuation lines. Current reviewed
    # paths and digest/header fields are ASCII; never admit arbitrary blobs here.
    require(not any(c > 126 or (c < 32 and c not in (10, 13)) for c in data),
            'non-text public signature material')
    for line in data.split(b'\r\n'):
        require(len(line) <= 72 and (not line or line.startswith(b' ') or b': ' in line),
                'invalid public signature text line')


def signature_der(data):
    """Require a bounded complete DER ContentInfo SignedData public container.

    This only checks the outer ASN.1 envelope/OID, not signatures, certificate
    identity, or the complete ASN.1 semantics; use apksigner for that separately.
    """
    require(13 <= len(data) <= MAX_SIGNATURE and data[0] == 0x30,
            'invalid public signature DER container')
    at, first = 2, data[1]
    if first < 128:
        length = first
    else:
        n = first & 127
        require(1 <= n <= 4 and 2 + n <= len(data) and data[2] != 0,
                'invalid DER length')
        length = int.from_bytes(data[2:2+n], 'big')
        require(length >= 128 and length.bit_length() > 8 * (n - 1),
                'noncanonical DER length')
        at += n
    require(at + length == len(data) and
            data[at:at+11] == bytes.fromhex('06092a864886f70d010702'),
            'signature DER is not complete PKCS7 SignedData')


def verify(path, expected_baselines=None, expected_sidecars=None):
    path = Path(path).absolute()
    expected_catalog = expected_digest(expected_baselines, MAX_CATALOG)
    expected_index = expected_digest(expected_sidecars, MAX_INDEX)
    with regular_input(path, MAX_APK) as source:
        source_hash = sha256(source)
        source.seek(0, 2)
        source_size = source.tell()
        with StrictZip(source, max_bytes=MAX_APK, max_entries=512,
                       max_total=MAX_EXPANDED, max_file=MAX_EXPANDED, apk=True) as apk:
            files = set(apk.files)
            require(REQUIRED_FILES <= files, 'APK missing required manifest/resources/classes/native/icon member')
            signatures = {}
            for info in apk.zip.infolist():
                name = info.filename
                if info.is_dir():
                    require(name in ALLOWED_DIRECTORIES, 'unreviewed APK directory: ' + name)
                    continue
                require(info.file_size > 0, 'empty APK member: ' + name)
                if name in REQUIRED_FILES or name in ALLOWED_ASSETS:
                    continue
                if name == 'META-INF/MANIFEST.MF':
                    signatures[name] = None
                    continue
                match = SIGNER.fullmatch(name)
                require(match is not None, 'unreviewed APK member: ' + name)
                signatures[name] = match.groups()
            assets = {name for name in files if name.startswith('assets/')}
            require(assets == ALLOWED_ASSETS, 'APK must contain exactly the two inventory metadata assets')
            if signatures:
                require('META-INF/MANIFEST.MF' in signatures, 'public JAR signatures require MANIFEST.MF')
                signers = {}
                for name, pair in signatures.items():
                    if pair is not None:
                        signers.setdefault(pair[0], set()).add(pair[1])
                require(bool(signers) and all('SF' in kinds and len(kinds) == 2 and
                        len(kinds & {'RSA', 'DSA', 'EC'}) == 1 for kinds in signers.values()),
                        'public signature SF/block members must pair by signer basename')
            raw_catalog = apk.read('assets/data-baselines.zip', 1024 * 1024)
            catalog_hash = hashlib.sha256(raw_catalog).hexdigest()
            require(expected_catalog is None or expected_catalog == catalog_hash,
                    'baseline catalog differs from independently reviewed reference')
            baselines = load_catalog(io.BytesIO(raw_catalog))
            require(baselines.keys() == KNOWN_BASELINES, 'APK requires both reviewed old4f/currenta887 inventories')
            raw_index = apk.read('assets/sidecars-index-v1.tsv', MAX_INDEX)
            index_hash = hashlib.sha256(raw_index).hexdigest()
            require(expected_index is None or expected_index == index_hash,
                    'sidecar index differs from independently reviewed reference')
            sidecars = parse_sidecars(raw_index)
            # Every admitted member, including opaque code/resources, gets complete
            # structure, expanded-size, deflate EOF and CRC checks. Nothing runs.
            for name in sorted(files - ALLOWED_ASSETS):
                if name == 'META-INF/MANIFEST.MF':
                    signature_text(apk.read(name, MAX_SIGNATURE), b'Manifest-Version: 1.0')
                elif name in signatures:
                    data = apk.read(name, MAX_SIGNATURE)
                    if signatures[name][1] == 'SF':
                        signature_text(data, b'Signature-Version: 1.0')
                    else:
                        signature_der(data)
                else:
                    apk.consume(name, limit=MAX_EXPANDED)
        require(sha256(source) == source_hash, 'APK changed during verification')
    return {'apk': str(path), 'bytes': source_size, 'apk_sha256': source_hash,
            'assets': sorted(assets), 'required_members': sorted(REQUIRED_FILES),
            'baseline_ids': sorted(baselines), 'sidecar_count': len(sidecars),
            'baselines_sha256': catalog_hash, 'sidecars_sha256': index_hash,
            'reviewed_references_matched': expected_catalog is not None and expected_index is not None,
            'metadata_authenticity': ('both independent reference pins matched' if
                expected_catalog is not None and expected_index is not None else
                'canonical structure only; independent metadata review still required'),
            'external_game_payloads': False,
            'compiled_original_derived_code_not_legally_cleared': True,
            'apk_signature_or_loadability_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--expected-baselines', metavar='FILE_OR_SHA256',
                        help='independently reviewed catalog reference file or lowercase SHA-256')
    parser.add_argument('--expected-sidecars', metavar='FILE_OR_SHA256',
                        help='independently reviewed sidecar index reference file or lowercase SHA-256')
    args = parser.parse_args(argv)
    try:
        result = verify(args.apk, args.expected_baselines, args.expected_sidecars)
    except (ResourceError, OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        parser.exit(2, 'resource-free APK verification refused: ' + str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
