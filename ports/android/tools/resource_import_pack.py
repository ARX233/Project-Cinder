#!/usr/bin/env python3
"""Offline extraction for an APK you own and are entitled to use.

Copyright: provide your own lawful local source; do not redistribute extracted
payload. No downloads, APK installation, game/launcher execution, save import,
or original arcade IGB-to-WPK conversion. This is NOT an original-game converter.
Supply builder-reviewed --catalog and --sidecars-index, never player-created pins.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import io
import os
from pathlib import Path
import platform
import sys
import uuid
import zipfile
import zlib

sys.dont_write_bytecode = True
from resource_pack_common import (CARD_PATHS, MAX_APK, MAX_CARD_TOTAL, MAX_CATALOG,
    MAX_FILE, MAX_INDEX, MAX_MAIN_TOTAL, MAX_SIDECAR_TOTAL, SIDECAR_PATHS, TOP4,
    Entry, ResourceError, StrictZip, copy_member, deterministic_info, new_output,
    file_sha256, load_catalog, parse_sidecars, path_inventory, private_directory,
    publish_exclusive, regular_input, require, sha256, write_json_exclusive)


def _pack(apk_path, catalog_path, sidecars_path, staged, output, receipt_path):
    with regular_input(catalog_path, MAX_CATALOG) as source:
        catalog_hash = sha256(source)
        manifests = load_catalog(source)
        require(sha256(source) == catalog_hash, 'catalog changed during parsing')
    with regular_input(sidecars_path, MAX_INDEX) as source:
        sidecars_hash = sha256(source)
        sidecars = parse_sidecars(source.read())
        require(sha256(source) == sidecars_hash, 'sidecar metadata changed during parsing')
    with regular_input(apk_path, MAX_APK) as source:
        source_hash = sha256(source)
        source_size = os.fstat(source.fileno()).st_size
        with StrictZip(source, max_bytes=MAX_APK, max_entries=20000,
                       max_total=3 * 1024**3, max_file=MAX_APK, apk=True) as apk:
            needed = {'assets/re3dxplus-data.zip', 'assets/card-resources-v1.zip'} | {'assets/' + p for p in TOP4}
            require(needed <= apk.files.keys(), 'source APK is missing runtime resource assets')
            assets = {}
            main_path, card_path = staged / 'main-resources.zip', staged / 'card-resources.zip'
            assets['assets/re3dxplus-data.zip'] = copy_member(
                apk, 'assets/re3dxplus-data.zip', main_path, MAX_APK)
            assets['assets/card-resources-v1.zip'] = copy_member(
                apk, 'assets/card-resources-v1.zip', card_path, MAX_CARD_TOTAL)
            with regular_input(main_path, MAX_APK) as main_source, regular_input(card_path, MAX_CARD_TOTAL) as card_source:
                with StrictZip(main_source, max_bytes=MAX_APK, max_entries=20000,
                               max_total=MAX_MAIN_TOTAL) as main, StrictZip(
                                   card_source, max_bytes=MAX_CARD_TOTAL, max_entries=64,
                                   max_total=MAX_CARD_TOTAL) as card:
                    require(card.files.keys() == CARD_PATHS and len(card.zip.infolist()) == 37,
                            'card archive must contain exactly 37 approved files')
                    candidates = {h: m for h, m in manifests.items() if m.files.keys() == main.files.keys() and
                                  all(main.files[p].file_size == e.size for p, e in m.files.items())}
                    require(bool(candidates), 'main paths/sizes do not match an approved baseline')
                    for path in sorted(main.files):
                        observed = main.consume(path, limit=MAX_FILE)
                        candidates = {h: m for h, m in candidates.items() if m.files[path] == observed}
                        require(bool(candidates), 'main resource differs from all approved baselines: ' + path)
                    # A different ZIP container is fine ONLY after every member matches.
                    matched = sorted(candidates)
                    manifest = candidates[matched[0]]
                    for path in card.files:
                        card.consume(path, limit=MAX_FILE, expected=sidecars['card-resources/' + path])
                    for path in TOP4:
                        assets['assets/' + path] = apk.consume('assets/' + path, limit=MAX_FILE,
                                                               expected=sidecars[path])
                    all_files = dict(manifest.files)
                    require(not all_files.keys() & SIDECAR_PATHS, 'main/sidecar resource collision')
                    all_files.update(sidecars)
                    path_inventory((path, False) for path in all_files)
                    stage_zip = staged / 'verified-resources.zip'
                    with stage_zip.open('xb') as raw:
                        os.chmod(stage_zip, 0o600)
                        with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED,
                                             compresslevel=6, allowZip64=False) as packed:
                            for path in sorted(all_files):
                                if path in manifest.files:
                                    archive, name = main, path
                                elif path.startswith('card-resources/'):
                                    archive, name = card, path[len('card-resources/'):]
                                else:
                                    archive, name = apk, 'assets/' + path
                                with packed.open(deterministic_info(path), 'w') as target:
                                    archive.consume(name, limit=MAX_FILE, output=target, expected=all_files[path])
                        raw.flush()
                        os.fsync(raw.fileno())
                    require(stage_zip.stat().st_size <= MAX_APK, 'output ZIP exceeds Android archive byte budget')
                    # Verify produced local/central records, CRCs, membership and hashes.
                    with regular_input(stage_zip, MAX_APK) as built_source, StrictZip(
                            built_source, max_bytes=MAX_APK, max_entries=20000,
                            max_total=MAX_MAIN_TOTAL + MAX_SIDECAR_TOTAL) as built:
                        require(built.files.keys() == all_files.keys(), 'output membership mismatch')
                        for path, expected in all_files.items():
                            built.consume(path, limit=MAX_FILE, expected=expected)
                    main_sha = assets['assets/re3dxplus-data.zip'].sha256
                    require(sha256(main_source) == main_sha and
                            sha256(card_source) == assets['assets/card-resources-v1.zip'].sha256,
                            'private resource staging input changed')
            require(sha256(source) == source_hash, 'source APK changed during packing')
    # Exit all source guards before publication. No source names are extraction targets.
    receipt = {'schema': 'WMMT-RESOURCE-PACK-RECEIPT-1',
               'source_apk': str(Path(apk_path).absolute()), 'source_apk_bytes': source_size,
               'source_apk_sha256': source_hash,
               'trust': 'explicit builder-reviewed catalog and sidecar metadata; no player-derived trust',
               'catalog': str(Path(catalog_path).absolute()), 'catalog_sha256': catalog_hash,
               'sidecars_index': str(Path(sidecars_path).absolute()), 'sidecars_index_sha256': sidecars_hash,
               'source_assets': {p: asdict(e) for p, e in sorted(assets.items())},
               'matching_reviewed_baselines': matched,
               'source_main_zip_sha256': main_sha,
               'source_main_container_is_reviewed_hash': main_sha in matched,
               'main_acceptance': 'complete path, byte-length and SHA-256 entry map; never container hash alone',
               'main_file_count': len(manifest.files), 'sidecar_file_count_including_card_manifest': len(sidecars),
               'output': str(output), 'output_bytes': stage_zip.stat().st_size,
               'output_sha256': file_sha256(stage_zip), 'output_file_count': len(all_files),
               'output_files': {p: asdict(e) for p, e in sorted(all_files.items())},
               'reproducibility': {'mtime': '1980-01-01T00:00:00', 'mode': '0100644',
                                   'order': 'sorted Unicode paths', 'compression': 'DEFLATE level 6',
                                   'python': platform.python_version(), 'zlib': zlib.ZLIB_RUNTIME_VERSION},
               'staging_directory': str(staged),
               'copyright': 'private lawful local use only; do not redistribute derived game payload',
               'original_arcade_converter': False, 'apk_code_executed': False,
               'device_access': False, 'downloads': False,
               'publication': 'two exclusive CREATE_NEW copies; failure may retain partial new files; only a zero CLI exit confirms both files published'}
    staged_receipt = staged / 'receipt.json'
    write_json_exclusive(staged_receipt, receipt)
    # Portable CREATE_NEW/'xb': no hard-link filesystem requirement, rename,
    # overwrite or unlink. The two-file publication is not atomic; failed writes
    # can leave this run's partial new files. A retry needs fresh output names.
    publish_exclusive(stage_zip, output, Entry(receipt['output_bytes'], receipt['output_sha256']))
    publish_exclusive(staged_receipt, receipt_path,
                      Entry(staged_receipt.stat().st_size, file_sha256(staged_receipt)))
    return receipt


def pack(apk_path, catalog_path, sidecars_path, output_path):
    output = new_output(output_path)
    require(output.suffix.lower() == '.zip', '--output must be a new .zip path')
    receipt = new_output(str(output) + '.receipt.json')
    staged = private_directory(output.parent / ('.' + output.name + '.work-' + uuid.uuid4().hex))
    try:
        return _pack(apk_path, catalog_path, sidecars_path, staged, output, receipt)
    except Exception as exc:
        # Only create a new file in our exact newly created private workspace.
        write_json_exclusive(staged / 'failure.json', {'status': 'failed', 'error': str(exc),
                             'output_may_be_partially_published': os.path.lexists(output),
                             'user_data_removed': False})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--from-apk', type=Path, required=True, help='local APK you own and are entitled to use')
    parser.add_argument('--catalog', type=Path, required=True, help='explicit builder-reviewed DMF1 catalog ZIP')
    parser.add_argument('--sidecars-index', type=Path, required=True, help='explicit builder-reviewed sidecars-index-v1.tsv')
    parser.add_argument('--output', type=Path, required=True, help='new explicit absolute .zip; existing non-link parent also owns this run\'s work directory')
    args = parser.parse_args(argv)
    try:
        receipt = pack(args.from_apk, args.catalog, args.sidecars_index, args.output)
    except (ResourceError, OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        parser.exit(2, 'resource import refused: ' + str(exc) + '\n')
    print('Verified resource-only ZIP: ' + str(args.output))
    print('Private receipt: ' + str(args.output) + '.receipt.json')
    print('SHA-256: ' + receipt['output_sha256'])
    print('Private lawful use only; do not redistribute game-derived payload.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
