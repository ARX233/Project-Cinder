#!/usr/bin/env python3
"""Strict Project Cinder 0.1 APK packaging profile, offline and execution-free.

Requires four independent maintainer references: the unchanged original-runtime
allowlist, both legacy metadata references, and the reviewed resource-only launcher
allowlist. Never manufacture trusted references by scanning the candidate APK.
This does not replace/weaken either previous APK profile. SDK tools must separately
verify package/version, signing identity, adaptive-resource semantics and alignment.
No APK crypto-signature/loadability, Android execution or legal clearance inferred.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile
import zlib
sys.dont_write_bytecode=True
from resource_pack_common import (Entry,HASH,KNOWN_BASELINES,MAX_CATALOG,MAX_INDEX,
 ResourceError,StrictZip,load_catalog,parse_sidecars,regular_input,require,sha256)
from verify_original_convert_apk import runtime_inventory,MAX_APK,MAX_EXPANDED
from verify_resource_free_apk import (REQUIRED_FILES,ALLOWED_ASSETS,SIGNER,
 signature_text,signature_der,expected_digest,MAX_SIGNATURE)

LAUNCHER_SCHEMA='project-cinder-launcher-resources-v1'
MAX_LAUNCHER_MANIFEST=512*1024
MAX_LAUNCHER_ROWS=32
MAX_LAUNCHER_TOTAL=64*1024**2
WALLPAPER='assets/original-convert/launcher-wallpaper.jpg'
WALLPAPER_BYTES=396873
WALLPAPER_SHA256='2fcfa2aeeae006fc3cd10a9eafd73c577ca3657312ac9fbfb063a3bddf46054e'
LEGACY_ICON='res/mipmap/icon.png'
# Only these reviewed icon basenames/kinds are permitted. AAPT's versioned
# drawable qualifiers may normalize nodpi to nodpi-v4. This is not a res/ prefix
# permission: all other names and resource types remain forbidden.
ADAPTIVE_ICON=re.compile(r'res/mipmap-anydpi-v(?:2[6-9]|[3-9][0-9])/icon\.xml\Z')
FOREGROUND_ICON=re.compile(r'res/drawable(?:-nodpi)?(?:-v[1-9][0-9]{0,2})?/cinder_icon_foreground\.png\Z')


def _pairs(pairs):
 out={}
 for key,value in pairs:
  require(key not in out,'duplicate launcher-allowlist JSON member');out[key]=value
 return out


def launcher_inventory(path):
 """Read bounded independently reviewed launcher metadata, never APK-derived."""
 with regular_input(Path(path),MAX_LAUNCHER_MANIFEST) as source:
  data=source.read(MAX_LAUNCHER_MANIFEST+1)
 require(0<len(data)<=MAX_LAUNCHER_MANIFEST,'launcher allowlist byte limit')
 obj=json.loads(data.decode('utf-8','strict'),object_pairs_hook=_pairs)
 require(isinstance(obj,dict) and set(obj)=={'schema','files'} and
         obj['schema']==LAUNCHER_SCHEMA and isinstance(obj['files'],list),'launcher allowlist schema')
 require(0<len(obj['files'])<=MAX_LAUNCHER_ROWS,'launcher allowlist count')
 result={};previous='';total=0;res_count=0;adaptive=0;foreground=0
 for row in obj['files']:
  require(isinstance(row,dict) and set(row)=={'path','bytes','sha256'},'launcher allowlist row')
  name=row['path'];size=row['bytes'];digest=row['sha256']
  require(isinstance(name,str) and name>previous and name not in result and
          all(32<ord(c)<127 for c in name) and '\\' not in name and ':' not in name and
          all(p and p not in ('.','..') for p in name.split('/')),'launcher member path/order')
  is_adaptive=ADAPTIVE_ICON.fullmatch(name) is not None
  is_foreground=FOREGROUND_ICON.fullmatch(name) is not None
  require(name in {'AndroidManifest.xml','resources.arsc',WALLPAPER,LEGACY_ICON} or
          is_adaptive or is_foreground,'unreviewed launcher member namespace: '+name)
  limit=(16*1024**2 if name=='resources.arsc' else
         1024**2 if name=='AndroidManifest.xml' or is_adaptive else 8*1024**2)
  require(type(size) is int and 0<size<=limit and isinstance(digest,str) and
          HASH.fullmatch(digest),'launcher member bounds/hash')
  if name==WALLPAPER:
   require(size==WALLPAPER_BYTES and digest==WALLPAPER_SHA256,'wallpaper differs from user-approved photo')
  total+=size;require(total<=MAX_LAUNCHER_TOTAL,'launcher expanded byte limit')
  res_count+=name.startswith('res/');adaptive+=is_adaptive;foreground+=is_foreground
  result[name]=Entry(size,digest);previous=name
 require({'AndroidManifest.xml','resources.arsc',WALLPAPER,LEGACY_ICON}<=result.keys(),
         'launcher package is incomplete')
 require(0<res_count and res_count+2<16 and adaptive>=1 and foreground==1,
         'launcher requires a small reviewed resource APK, legacy/adaptive icon and one foreground PNG')
 return result,hashlib.sha256(data).hexdigest()


# Explicit name for callers authoring/validating the independent reference.
launcher_manifest=launcher_inventory


def verify(path,*,runtime,baselines,sidecars,launcher):
 inventory,inventory_hash=runtime_inventory(runtime)
 art,art_hash=launcher_inventory(launcher)
 require(inventory.keys().isdisjoint(art),'runtime/launcher inventories overlap')
 catalog_pin=expected_digest(baselines,MAX_CATALOG);index_pin=expected_digest(sidecars,MAX_INDEX)
 require(catalog_pin is not None and index_pin is not None,'independent baseline/sidecar references required')
 expected=set(REQUIRED_FILES)|set(ALLOWED_ASSETS)|set(inventory)|set(art)
 dirs={'META-INF/'}
 for name in expected:
  parts=name.split('/');dirs.update('/'.join(parts[:i])+'/' for i in range(1,len(parts)))
 with regular_input(Path(path).absolute(),MAX_APK) as source:
  original=sha256(source);source.seek(0,2);size=source.tell()
  with StrictZip(source,max_bytes=MAX_APK,max_entries=1024,max_total=MAX_EXPANDED,
                 max_file=128*1024**2,apk=True) as apk:
   files=set(apk.files);require(expected<=files,'incomplete Cinder conversion APK')
   signatures={}
   for info in apk.zip.infolist():
    name=info.filename
    if info.is_dir():require(name in dirs,'unreviewed APK directory: '+name);continue
    require(info.file_size>0,'empty outer APK member')
    if name in expected:continue
    if name=='META-INF/MANIFEST.MF':signatures[name]=None;continue
    match=SIGNER.fullmatch(name);require(match is not None,'unreviewed APK member: '+name)
    signatures[name]=match.groups()
   if signatures:
    require('META-INF/MANIFEST.MF' in signatures,'missing JAR public manifest');signers={}
    for name,pair in signatures.items():
     if pair is not None:signers.setdefault(pair[0],set()).add(pair[1])
    require(signers and all('SF' in kinds and len(kinds)==2 and
            len(kinds&{'RSA','DSA','EC'})==1 for kinds in signers.values()),'unpaired JAR signatures')
   raw=apk.read('assets/data-baselines.zip',MAX_CATALOG)
   require(hashlib.sha256(raw).hexdigest()==catalog_pin,'baseline APK metadata changed')
   catalogs=load_catalog(io.BytesIO(raw),allow_prepared=True)
   require(KNOWN_BASELINES<=catalogs.keys(),'missing legacy baseline')
   index=apk.read('assets/sidecars-index-v1.tsv',MAX_INDEX)
   require(hashlib.sha256(index).hexdigest()==index_pin,'sidecar metadata changed');sidecar_rows=parse_sidecars(index)
   for name in sorted(files-set(ALLOWED_ASSETS)):
    if name in art:apk.consume(name,limit=art[name].size,expected=art[name])
    elif name in inventory:apk.consume(name,limit=inventory[name].size,expected=inventory[name])
    elif name=='META-INF/MANIFEST.MF':signature_text(apk.read(name,MAX_SIGNATURE),b'Manifest-Version: 1.0')
    elif name in signatures:
     data=apk.read(name,MAX_SIGNATURE)
     if signatures[name][1]=='SF':signature_text(data,b'Signature-Version: 1.0')
     else:signature_der(data)
    else:apk.consume(name,limit=MAX_EXPANDED)
  require(sha256(source)==original,'APK changed during verification')
 return {'apk':str(Path(path).absolute()),'bytes':size,'apk_sha256':original,
         'profile':'project-cinder-original-convert-v1','project':'Project Cinder 0.1',
         'runtime_members':len(inventory),'runtime_inventory_sha256':inventory_hash,
         'launcher_members':len(art),'launcher_inventory_sha256':art_hash,
         'wallpaper_sha256':art[WALLPAPER].sha256,'user_approved_wallpaper_pin_matched':True,
         'original_profile_sha256':inventory['assets/original-convert/profile.tsv'].sha256,
         'baseline_ids':sorted(catalogs),'sidecar_count':len(sidecar_rows),
         'reviewed_references_matched':True,'game_payloads_embedded':False,
         'signature_loadability_or_android_execution_verified':False,
         'package_version_signer_and_adaptive_semantics_verified':False,
         'compiled_original_derived_code_not_legally_cleared':True}


def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('apk',type=Path)
 p.add_argument('--expected-runtime',required=True,type=Path)
 p.add_argument('--expected-baselines',required=True);p.add_argument('--expected-sidecars',required=True)
 p.add_argument('--expected-launcher',required=True,type=Path)
 a=p.parse_args(argv)
 try:result=verify(a.apk,runtime=a.expected_runtime,baselines=a.expected_baselines,
                   sidecars=a.expected_sidecars,launcher=a.expected_launcher)
 except (ResourceError,OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,RuntimeError,zlib.error) as exc:
  p.exit(2,'Cinder APK verification refused: '+str(exc)+'\n')
 print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
