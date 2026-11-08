#!/usr/bin/env python3
"""Build a finite APK legacy-baseline catalog from explicitly reviewed ZIP pins.

Example (the SHA must already be approved independently, NOT copied from an
observation of an arbitrary installed ZIP):
  JAVA_HOME=/path/to/jdk python3 tools/build_data_baselines.py \
    --baseline REVIEWED_SHA256=/path/to/reviewed.zip \
    --output-dir /Volumes/CodexWork/new-exclusive-output

Uses the real Java DataManifest.fromZip; outputs no Android build or APK.
All generated manifests, classes, Java temporary files and receipts stay in the
new external output directory. The host-only helper is not application code.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

MAX_ITEMS = 16
MAX_DMF = 2 * 1024 * 1024
MAX_CATALOG = 16 * 1024 * 1024


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--baseline', action='append', required=True, metavar='REVIEWED_SHA256=ZIP')
    parser.add_argument('--output-dir', required=True, type=Path, help='new directory under /Volumes/CodexWork')
    parser.add_argument('--java-home', type=Path, default=os.environ.get('JAVA_HOME'))
    args = parser.parse_args()
    if not 1 <= len(args.baseline) <= MAX_ITEMS:
        parser.error('supply 1..16 explicitly reviewed baseline identities')
    pins = {}
    for value in args.baseline:
        expected, separator, source = value.partition('=')
        if not separator or not re.fullmatch('[0-9a-f]{64}', expected) or not source:
            parser.error('--baseline must be lowercase SHA256=PATH')
        if expected in pins:
            parser.error('duplicate baseline SHA-256')
        path = Path(source).resolve(strict=True)
        if not path.is_file():
            parser.error('baseline ZIP must be a regular file')
        # This is equality to an externally supplied reviewed pin, not trust creation.
        if digest(path) != expected:
            parser.error('baseline ZIP does not match explicit reviewed SHA-256: ' + str(path))
        pins[expected] = path
    if args.java_home is None:
        parser.error('set JAVA_HOME or --java-home to an existing JDK')
    jdk = Path(args.java_home).resolve(strict=True)
    for name in ('javac', 'java'):
        if not (jdk / 'bin' / name).is_file():
            parser.error('JDK executable missing: ' + name)
    requested = args.output_dir
    if not requested.is_absolute():
        parser.error('--output-dir must be absolute')
    output = requested.parent.resolve(strict=True) / requested.name
    external = Path('/Volumes/CodexWork').resolve(strict=True)
    if output == external or external not in output.parents:
        parser.error('all generated files must be inside a new /Volumes/CodexWork directory')
    # mkdir is deliberately exclusive. Failed runs are retained for review, not deleted.
    output.mkdir()
    for name in ('classes', 'tmp', 'home', 'manifests'):
        (output / name).mkdir()
    repo = Path(__file__).resolve().parent.parent
    sources = [repo / 'android/java/com/wmmt/port' / name for name in
               ('DataManifest.java', 'DataOverlay.java', 'DataCoordinator.java', 'DataBaselines.java')]
    sources.append(repo / 'tools/DataBaselineCompiler.java')
    env = dict(os.environ)
    env.update(JAVA_HOME=str(jdk), HOME=str(output / 'home'), TMPDIR=str(output / 'tmp'),
               TMP=str(output / 'tmp'), TEMP=str(output / 'tmp'), PYTHONDONTWRITEBYTECODE='1')
    # Do not inherit options that can add agents, system properties or outside outputs.
    for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'JDK_JAVAC_OPTIONS', 'CLASSPATH'):
        env.pop(key, None)
    commands = []

    def run(command):
        command = [str(part) for part in command]
        commands.append(command)
        result = subprocess.run(command, env=env, cwd=output, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, check=False)
        with (output / 'compiler.log').open('a', encoding='utf-8') as log:
            log.write('$ ' + repr(command) + '\n' + result.stdout)
        if result.returncode:
            raise SystemExit('Java baseline helper failed; see ' + str(output / 'compiler.log'))
        print(result.stdout, end='', flush=True)

    run([jdk / 'bin/javac', '-J-Djava.io.tmpdir=' + str(output / 'tmp'), '--release', '8',
         '-d', output / 'classes', *sources])
    java = [jdk / 'bin/java', '-Djava.io.tmpdir=' + str(output / 'tmp'), '-cp', output / 'classes',
            'DataBaselineCompiler']
    entries = []
    total = 0
    for expected, source in sorted(pins.items()):
        dmf = output / 'manifests' / (expected + '.dmf')
        run([*java, '--compile', expected, source, dmf])
        size = dmf.stat().st_size
        total += size
        if size > MAX_DMF or total > MAX_CATALOG:
            raise SystemExit('manifest/catalog size budget exceeded; no catalog published')
        entries.append({'reviewed_zip_sha256': expected, 'source_zip': str(source),
                        'manifest': str(dmf), 'manifest_bytes': size, 'manifest_sha256': digest(dmf)})
    catalog = output / 'data-baselines.zip'
    # Exclusive open also protects against a concurrent accidental replacement.
    with catalog.open('xb') as raw:
        with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=False) as archive:
            for entry in entries:
                info = zipfile.ZipInfo(entry['reviewed_zip_sha256'] + '.dmf', (1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, Path(entry['manifest']).read_bytes())
        raw.flush()
        os.fsync(raw.fileno())
    if catalog.stat().st_size > MAX_CATALOG:
        raise SystemExit('compressed catalog limit exceeded; rejected output retained')
    run([*java, '--check', catalog])
    receipt = {'trust': 'explicit externally reviewed SHA256 pins; not installed-file observations',
               'catalog': str(catalog), 'catalog_sha256': digest(catalog), 'catalog_bytes': catalog.stat().st_size,
               'baselines': entries, 'production_sources': [{'path': str(p), 'sha256': digest(p)} for p in sources],
               'jdk': str(jdk), 'commands': commands, 'apk_built': False, 'device_access': False}
    with (output / 'receipt.json').open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print('Catalog: ' + str(catalog))
    print('Receipt: ' + str(output / 'receipt.json'))


if __name__ == '__main__':
    main()
