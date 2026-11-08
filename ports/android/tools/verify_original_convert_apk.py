#!/usr/bin/env python3
"""Strict Android 1.35 code/runtime/metadata-only APK profile (offline).

Requires the independently reviewed runtime packaging allowlist. It does not
weaken or replace the legacy resource-free APK verifier or runtime import rules.
No signature/loadability, Android execution or copyright clearance is inferred.
"""
import argparse,hashlib,io,json
from pathlib import Path
import re,sys,zipfile,zlib
sys.dont_write_bytecode=True
from resource_pack_common import (Entry,HASH,KNOWN_BASELINES,MAX_CATALOG,MAX_INDEX,
 ResourceError,StrictZip,load_catalog,parse_sidecars,regular_input,require,sha256)
from verify_resource_free_apk import (REQUIRED_FILES,ALLOWED_ASSETS,SIGNER,
 signature_text,signature_der,expected_digest,MAX_SIGNATURE)
MAX_APK=256*1024**2;MAX_EXPANDED=512*1024**2

def _pairs(pairs):
 out={}
 for key,value in pairs:
  require(key not in out,'duplicate runtime-allowlist JSON member');out[key]=value
 return out

def runtime_inventory(path):
 with regular_input(Path(path),1024**2) as source:data=source.read(1024**2+1)
 require(len(data)<=1024**2,'runtime allowlist byte limit')
 obj=json.loads(data.decode('utf-8','strict'),object_pairs_hook=_pairs)
 require(isinstance(obj,dict) and set(obj)=={'schema','files'} and obj['schema']=='wmmt-original-runtime-package-v1' and isinstance(obj['files'],list),'runtime allowlist schema')
 require(0<len(obj['files'])<=256,'runtime allowlist count')
 result={};previous=''
 for row in obj['files']:
  require(isinstance(row,dict) and set(row)=={'path','bytes','sha256'},'runtime allowlist row')
  name=row['path'];size=row['bytes'];digest=row['sha256']
  require(isinstance(name,str) and name>previous and name not in result and (name.startswith('assets/chaquopy/') or name.startswith('assets/original-convert/') or name.startswith('lib/arm64-v8a/')),'runtime member namespace/order')
  require(all(part and part not in ('.','..') for part in name.split('/')) and '\\' not in name and ':' not in name and all(32<ord(c)<127 for c in name),'runtime member path')
  require(name not in REQUIRED_FILES and name not in ALLOWED_ASSETS,'runtime may not override baseline APK members')
  require(type(size) is int and 0<size<=128*1024**2 and isinstance(digest,str) and HASH.fullmatch(digest),'runtime member bounds/hash')
  result[name]=Entry(size,digest);previous=name
 required={'assets/chaquopy/app.imy','assets/chaquopy/build.json','assets/original-convert/profile.tsv','lib/arm64-v8a/liboa_native.so','lib/arm64-v8a/liboc_media_overlay.so'}
 require(required<=result.keys(),'runtime package is incomplete')
 return result,hashlib.sha256(data).hexdigest()

def verify(path,*,runtime,baselines,sidecars):
 inventory,inventory_hash=runtime_inventory(runtime)
 catalog_pin=expected_digest(baselines,MAX_CATALOG);index_pin=expected_digest(sidecars,MAX_INDEX)
 require(catalog_pin is not None and index_pin is not None,'independent baseline/sidecar references required')
 expected=set(REQUIRED_FILES)|set(ALLOWED_ASSETS)|set(inventory)
 dirs={'META-INF/'}
 for name in expected:
  parts=name.split('/');dirs.update('/'.join(parts[:i])+'/' for i in range(1,len(parts)))
 with regular_input(Path(path).absolute(),MAX_APK) as source:
  original=sha256(source);source.seek(0,2);size=source.tell()
  with StrictZip(source,max_bytes=MAX_APK,max_entries=1024,max_total=MAX_EXPANDED,max_file=128*1024**2,apk=True) as apk:
   files=set(apk.files);require(expected<=files,'incomplete conversion APK')
   signatures={}
   for info in apk.zip.infolist():
    name=info.filename
    if info.is_dir():require(name in dirs,'unreviewed APK directory: '+name);continue
    require(info.file_size>0,'empty outer APK member')
    if name in expected:continue
    if name=='META-INF/MANIFEST.MF':signatures[name]=None;continue
    match=SIGNER.fullmatch(name);require(match is not None,'unreviewed APK member: '+name);signatures[name]=match.groups()
   if signatures:
    require('META-INF/MANIFEST.MF' in signatures,'missing JAR public manifest');signers={}
    for name,pair in signatures.items():
     if pair is not None:signers.setdefault(pair[0],set()).add(pair[1])
    require(signers and all('SF' in kinds and len(kinds)==2 and len(kinds&{'RSA','DSA','EC'})==1 for kinds in signers.values()),'unpaired JAR signatures')
   raw=apk.read('assets/data-baselines.zip',MAX_CATALOG);require(hashlib.sha256(raw).hexdigest()==catalog_pin,'baseline APK metadata changed')
   catalogs=load_catalog(io.BytesIO(raw));require(catalogs.keys()==KNOWN_BASELINES,'legacy baseline set changed')
   index=apk.read('assets/sidecars-index-v1.tsv',MAX_INDEX);require(hashlib.sha256(index).hexdigest()==index_pin,'sidecar metadata changed');parse_sidecars(index)
   for name in sorted(files-set(ALLOWED_ASSETS)):
    if name in inventory:apk.consume(name,limit=inventory[name].size,expected=inventory[name])
    elif name=='META-INF/MANIFEST.MF':signature_text(apk.read(name,MAX_SIGNATURE),b'Manifest-Version: 1.0')
    elif name in signatures:
     data=apk.read(name,MAX_SIGNATURE)
     if signatures[name][1]=='SF':signature_text(data,b'Signature-Version: 1.0')
     else:signature_der(data)
    else:apk.consume(name,limit=MAX_EXPANDED)
  require(sha256(source)==original,'APK changed during verification')
 return {'apk':str(Path(path).absolute()),'bytes':size,'apk_sha256':original,'profile':'resource-free-original-convert-v1',
         'runtime_members':len(inventory),'runtime_inventory_sha256':inventory_hash,
         'original_profile_sha256':inventory['assets/original-convert/profile.tsv'].sha256,
         'reviewed_references_matched':True,'game_payloads_embedded':False,
         'signature_loadability_or_android_execution_verified':False,'compiled_original_derived_code_not_legally_cleared':True}

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('apk',type=Path)
 p.add_argument('--expected-runtime',required=True,type=Path);p.add_argument('--expected-baselines',required=True);p.add_argument('--expected-sidecars',required=True)
 a=p.parse_args(argv)
 try:result=verify(a.apk,runtime=a.expected_runtime,baselines=a.expected_baselines,sidecars=a.expected_sidecars)
 except (ResourceError,OSError,ValueError,KeyError,zipfile.BadZipFile,RuntimeError,zlib.error) as exc:p.exit(2,'original-convert APK verification refused: '+str(exc)+'\n')
 print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
