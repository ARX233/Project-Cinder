#!/usr/bin/env python3
"""Generate metadata ONLY from an independently approved APK SHA-256.

Never approve a player's directory or arbitrary observed APK by hashing it.
No APK code is executed; no game payload is written by this generator.
Choose a new explicit absolute output directory with an existing non-link parent.
No implicit cwd/home/system-temp output, uploads or target execution.
"""
from __future__ import annotations
import argparse
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile
import zlib

sys.dont_write_bytecode = True
from resource_pack_common import (CARD_PATHS, Entry, HASH, MAX_APK, MAX_CARD_TOTAL,
    MAX_CATALOG, MAX_FILE, TOP4, ResourceError, StrictZip, encode_sidecars,
    new_output, file_sha256, private_directory, regular_input, require,
    sha256, write_json_exclusive)

ASSET_KEYS = {'GAME_DATA_ZIP': 'assets/re3dxplus-data.zip',
              'GAME_DATA_BASELINES_ZIP': 'assets/data-baselines.zip',
              'CARD_RESOURCES': 'assets/card-resources-v1.zip',
              'STORY_CUTIN_BIN': 'assets/story-cutin.bin',
              'CARD_PAGES_BIN': 'assets/card-pages.bin',
              'BACKFIRE_WPK': 'assets/backfire.wpk',
              'BACKFIRE_BFX': 'assets/backfire.bfx'}


def reviewed_inputs(path):
    with regular_input(path, 64 * 1024) as source:
        return json.loads(source.read().decode('utf-8')), sha256(source)


def card_specs(path):
    with regular_input(path, 64 * 1024) as source:
        data = source.read().decode('utf-8')
        source_hash = sha256(source)
    manifest_size = re.search(r'\bMANIFEST_SIZE\s*=\s*(\d+)L', data)
    manifest_sha = re.search(r'\bMANIFEST_SHA\s*=\s*"([0-9a-f]{64})"', data)
    require(manifest_size and manifest_sha, 'missing reviewed card manifest spec')
    specs = {'manifest.json': Entry(int(manifest_size[1]), manifest_sha[1])}
    for path, size, digest in re.findall(
            r'new Spec\("([^"]+)",\s*(\d+)L,\s*"([0-9a-f]{64})"\)', data):
        require(path not in specs, 'duplicate card spec')
        specs[path] = Entry(int(size), digest)
    require(specs.keys() == CARD_PATHS, 'reviewed card spec path mismatch')
    return specs, source_hash


def generate(apk_path, approved_sha256, output_dir, resource_inputs=None, card_spec=None):
    require(HASH.fullmatch(approved_sha256), 'approved APK SHA-256 must be 64 lowercase hex')
    output = new_output(output_dir)
    pins, pins_hash = reviewed_inputs(resource_inputs) if resource_inputs else (None, None)
    specs, spec_hash = card_specs(card_spec) if card_spec else (None, None)
    with regular_input(apk_path, MAX_APK) as source:
        source_size = os.fstat(source.fileno()).st_size
        observed_apk = sha256(source)
        require(observed_apk == approved_sha256, 'APK differs from explicit independently approved SHA-256')
        with StrictZip(source, max_bytes=MAX_APK, max_entries=20000,
                       max_total=3 * 1024**3, max_file=MAX_APK, apk=True) as apk:
            require(set(ASSET_KEYS.values()) <= apk.files.keys(), 'approved APK resource assets missing')
            assets = {}
            for key, name in ASSET_KEYS.items():
                entry = apk.consume(name, limit=MAX_APK if key == 'GAME_DATA_ZIP' else
                                    MAX_CARD_TOTAL if key == 'CARD_RESOURCES' else
                                    MAX_CATALOG if key == 'GAME_DATA_BASELINES_ZIP' else MAX_FILE)
                if pins is not None:
                    pin = pins.get(key)
                    require(isinstance(pin, dict) and pin.get('size') == entry.size and
                            pin.get('sha256') == entry.sha256, 'reviewed asset pin mismatch: ' + key)
                assets[name] = {'bytes': entry.size, 'sha256': entry.sha256}
            rows = {name: Entry(assets['assets/' + name]['bytes'],
                                assets['assets/' + name]['sha256']) for name in TOP4}
            # This bounded in-memory nested ZIP is not an extracted payload directory.
            card_bytes = apk.read('assets/card-resources-v1.zip', MAX_CARD_TOTAL)
            with StrictZip(io.BytesIO(card_bytes), max_bytes=MAX_CARD_TOTAL, max_entries=64,
                           max_total=MAX_CARD_TOTAL) as card:
                require(card.files.keys() == CARD_PATHS and
                        len(card.zip.infolist()) == len(CARD_PATHS), 'card archive must contain exactly 37 files')
                for path in sorted(card.files):
                    entry = card.consume(path, limit=MAX_FILE,
                                         expected=specs[path] if specs else None)
                    rows['card-resources/' + path] = entry
            metadata = encode_sidecars(rows)
        require(sha256(source) == approved_sha256, 'approved APK changed during metadata generation')
    # No output directory exists until every resource and pin has verified.
    private_directory(output)
    index = output / 'sidecars-index-v1.tsv'
    with index.open('xb') as target:
        target.write(metadata)
        target.flush()
        os.fsync(target.fileno())
    receipt = {'schema': 'WMMT-SIDECARS-RECEIPT-1',
               'trust': 'caller-supplied independently approved complete APK SHA-256; not player-directory trust',
               'source_apk': str(Path(apk_path).absolute()), 'source_apk_sha256': approved_sha256,
               'source_apk_bytes': source_size,
               'assets': assets,
               'sidecars': {p: {'bytes': e.size, 'sha256': e.sha256} for p, e in sorted(rows.items())},
               'sidecar_count': len(rows), 'card_file_count_including_manifest': len(CARD_PATHS),
               'ios_payload_count_excluding_card_manifest': len(rows) - 1,
               'metadata': str(index), 'metadata_bytes': len(metadata),
               'metadata_sha256': file_sha256(index),
               'reviewed_resource_inputs_sha256': pins_hash, 'reviewed_card_spec_sha256': spec_hash,
               'apk_code_executed': False, 'payload_written': False,
               'apk_signature_verification': 'not performed; external SHA approval is the trust boundary'}
    write_json_exclusive(output / 'receipt.json', receipt)
    return index, output / 'receipt.json'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-apk', type=Path, required=True)
    parser.add_argument('--approved-apk-sha256', required=True,
                        help='independently reviewed pin, NOT a pin invented from this run')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='new explicit absolute directory; parent must already exist and contain no symlink/junction')
    parser.add_argument('--resource-inputs', type=Path, help='optional independently reviewed android-resource-inputs.json')
    parser.add_argument('--card-spec', type=Path, help='optional reviewed CardResources.java for read-only spec cross-check')
    args = parser.parse_args(argv)
    try:
        index, receipt = generate(args.from_apk, args.approved_apk_sha256,
                                  args.output_dir, args.resource_inputs, args.card_spec)
    except (ResourceError, OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        parser.exit(2, 'metadata generation refused: ' + str(exc) + '\n')
    print('Metadata: ' + str(index))
    print('Private receipt: ' + str(receipt))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
