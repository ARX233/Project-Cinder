#!/usr/bin/env python3
"""BUILD-HOST ONLY. Fetch exact official public sources into a new work directory.
No use by APK/runtime. Pins are observed TLS-download SHA-256, not signed checksums.
Existing dependency files/directories are never overwritten. Requires Python 3.12+.
"""
import argparse, hashlib, json, os, pathlib, tarfile, urllib.request
PINS=[('ffmpeg-9.0.2.tar.xz','https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz','8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e',['ffmpeg-9.0.2']),('openh264-v2.6.0.tar.gz','https://github.com/cisco/openh264/archive/refs/tags/v2.6.0.tar.gz','558544ad358283a7ab2930d69a9ceddf913f4a51ee9bf1bfb9e377322af81a69',['openh264-host','openh264-android'])]
p=argparse.ArgumentParser();p.add_argument('--work',required=True);a=p.parse_args();w=pathlib.Path(a.work).resolve();w.mkdir(exist_ok=False)
for n in ['home','tmp','cache','deps','logs','proof']:(w/n).mkdir()
os.environ.update(HOME=str(w/'home'),TMPDIR=str(w/'tmp'),XDG_CACHE_HOME=str(w/'cache'))
for name,url,pin,targets in PINS:
    carrier=w/'deps'/name;h=hashlib.sha256();size=0
    with urllib.request.urlopen(url,timeout=120) as response,carrier.open('xb') as out:
        while block:=response.read(1024*1024):
            size+=len(block)
            if size>128*1024**2:raise ValueError('source carrier byte budget')
            out.write(block);h.update(block)
    if h.hexdigest()!=pin:raise ValueError('source hash mismatch; untrusted partial retained, no extraction')
    for target in targets:
        dest=w/'deps'/target;dest.mkdir()
        with tarfile.open(carrier) as tf:
            # Remove the one archive root; retain only directories/regular files.
            members=[]
            for entry in tf:
                parts=pathlib.PurePosixPath(entry.name).parts
                if len(parts)<2:continue
                if not(entry.isdir() or entry.isfile()):raise ValueError('non-regular upstream archive entry')
                entry.name=str(pathlib.PurePosixPath(*parts[1:]));members.append(entry)
            tf.extractall(dest,members=members,filter='data')
with (w/'logs/dependency-pins.json').open('x') as f:json.dump(PINS,f,indent=2)
print(w)
