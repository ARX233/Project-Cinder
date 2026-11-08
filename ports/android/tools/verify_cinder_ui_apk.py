#!/usr/bin/env python3
"""Opt-in original Ghost UI APK profile, offline and execution-free.
Requires an independent source-provenance-backed expected Ghost manifest. The
legacy Cinder verifier/common allowlists are intentionally not changed. Neither
GHOST_UI_BIN nor candidate APK digests can authorize any resource.
"""
import argparse,hashlib,io,json,sys,zipfile,zlib
from pathlib import Path
from resource_pack_common import (KNOWN_BASELINES,MAX_CATALOG,MAX_INDEX,TOP4,ResourceError,StrictZip,
 load_catalog,parse_sidecars,regular_input,require,sha256)
from verify_original_convert_apk import runtime_inventory,MAX_APK,MAX_EXPANDED
from verify_resource_free_apk import REQUIRED_FILES,ALLOWED_ASSETS,SIGNER,signature_text,signature_der,expected_digest,MAX_SIGNATURE
from verify_cinder_apk import launcher_inventory,WALLPAPER
from ghost_ui_common import BANK,INDEX,MAX_BANK,expected_manifest,encode_index,inspect_pack

def verify(path,*,runtime,baselines,sidecars,launcher,ghost):
 # Fail before opening candidate bytes if the independent approval is absent/invalid.
 approved,ui,approval_hash=expected_manifest(ghost)
 inventory,inventory_hash=runtime_inventory(runtime);art,art_hash=launcher_inventory(launcher)
 require(inventory.keys().isdisjoint(art) and inventory.keys().isdisjoint(ui) and art.keys().isdisjoint(ui),'independent inventories overlap')
 catalog_pin=expected_digest(baselines,MAX_CATALOG);index_pin=expected_digest(sidecars,MAX_INDEX)
 require(catalog_pin is not None and index_pin is not None,'independent legacy metadata references required')
 expected=set(REQUIRED_FILES)|set(ALLOWED_ASSETS)|set(inventory)|set(art)|set(ui)
 # Existing optional payloads are permitted ONLY at their four old exact paths,
 # with SHA/length from the unchanged independently reviewed 41-row metadata.
 optional={'assets/'+n for n in TOP4};dirs={'META-INF/'}
 for name in expected|optional:
  parts=name.split('/');dirs.update('/'.join(parts[:i])+'/' for i in range(1,len(parts)))
 with regular_input(Path(path).absolute(),MAX_APK) as source:
  original=sha256(source);source.seek(0,2);size=source.tell()
  with StrictZip(source,max_bytes=MAX_APK,max_entries=1024,max_total=MAX_EXPANDED+MAX_BANK,
                 max_file=MAX_BANK,apk=True) as apk:
   files=set(apk.files);require(expected<=files,'incomplete Ghost UI Cinder APK')
   require(sum(i.file_size for n,i in apk.files.items() if n not in ui)<=MAX_EXPANDED,'legacy APK expanded byte budget')
   signatures={}
   for info in apk.zip.infolist():
    name=info.filename
    if info.is_dir():require(name in dirs,'unreviewed APK directory: '+name);continue
    require(info.file_size>0,'empty outer APK member')
    require(name==BANK or info.file_size<=128*1024**2,'legacy APK member byte budget')
    if name in expected|optional:continue
    if name=='META-INF/MANIFEST.MF':signatures[name]=None;continue
    match=SIGNER.fullmatch(name);require(match is not None,'unreviewed APK member: '+name)
    signatures[name]=match.groups()
   if signatures:
    require('META-INF/MANIFEST.MF' in signatures,'missing JAR public manifest');signers={}
    for name,pair in signatures.items():
     if pair is not None:signers.setdefault(pair[0],set()).add(pair[1])
    require(signers and all('SF' in kinds and len(kinds)==2 and len(kinds&{'RSA','DSA','EC'})==1 for kinds in signers.values()),'unpaired JAR signatures')
   raw=apk.read('assets/data-baselines.zip',MAX_CATALOG)
   require(hashlib.sha256(raw).hexdigest()==catalog_pin,'baseline APK metadata changed')
   catalogs=load_catalog(io.BytesIO(raw));require(catalogs.keys()==KNOWN_BASELINES,'legacy baseline set changed')
   old_index=apk.read('assets/sidecars-index-v1.tsv',MAX_INDEX)
   require(hashlib.sha256(old_index).hexdigest()==index_pin,'legacy sidecar metadata changed')
   old_rows=parse_sidecars(old_index)
   bank=apk.read(BANK,ui[BANK].size)
   require(len(bank)==ui[BANK].size and hashlib.sha256(bank).hexdigest()==ui[BANK].sha256,'Ghost bank differs from explicit expected manifest')
   new_index=apk.read(INDEX,512)
   require(new_index==encode_index(ui[BANK]) and len(new_index)==ui[INDEX].size and hashlib.sha256(new_index).hexdigest()==ui[INDEX].sha256,'Ghost metadata exact digest/namespace mismatch')
   stats=inspect_pack(bank,approved['provenance'])
   require(('assets/backfire.wpk' in files)==('assets/backfire.bfx' in files),'incomplete legacy backfire pair')
   for name in sorted(files-set(ALLOWED_ASSETS)-set(ui)):
    if name in art:apk.consume(name,limit=art[name].size,expected=art[name])
    elif name in inventory:apk.consume(name,limit=inventory[name].size,expected=inventory[name])
    elif name in optional:apk.consume(name,limit=old_rows[name[7:]].size,expected=old_rows[name[7:]])
    elif name=='META-INF/MANIFEST.MF':signature_text(apk.read(name,MAX_SIGNATURE),b'Manifest-Version: 1.0')
    elif name in signatures:
     data=apk.read(name,MAX_SIGNATURE)
     if signatures[name][1]=='SF':signature_text(data,b'Signature-Version: 1.0')
     else:signature_der(data)
    else:apk.consume(name,limit=MAX_EXPANDED)
  require(sha256(source)==original,'APK changed during verification')
 return {'apk':str(Path(path).absolute()),'bytes':size,'apk_sha256':original,'profile':'project-cinder-ghost-ui-v1',
         'runtime_members':len(inventory),'runtime_inventory_sha256':inventory_hash,'launcher_members':len(art),
         'launcher_inventory_sha256':art_hash,'wallpaper_sha256':art[WALLPAPER].sha256,
         'baseline_ids':sorted(catalogs),'sidecar_count':len(old_rows),'ghost_ui_manifest_sha256':approval_hash,
         'ghost_ui_sha256':ui[BANK].sha256,'ghost_ui_bytes':ui[BANK].size,'ghost_ui_metadata_sha256':ui[INDEX].sha256,
         'legacy_optional_members':sorted(files&optional),**stats,'reviewed_references_matched':True,
         'main_resource_embedded':False,'old_profile_relaxed':False,'source_art_fabricated':False,
         'signature_loadability_or_android_execution_verified':False,'package_version_signer_and_adaptive_semantics_verified':False}

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('apk',type=Path)
 for name in ('runtime','baselines','sidecars','launcher','ghost-ui-manifest'):p.add_argument('--expected-'+name,required=True,type=Path)
 a=p.parse_args(argv)
 try:r=verify(a.apk,runtime=a.expected_runtime,baselines=a.expected_baselines,sidecars=a.expected_sidecars,launcher=a.expected_launcher,ghost=a.expected_ghost_ui_manifest)
 except (ResourceError,OSError,ValueError,KeyError,TypeError,RuntimeError,zipfile.BadZipFile,zlib.error) as e:p.exit(2,'Ghost UI APK verification refused: '+str(e)+'\n')
 print(json.dumps(r,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
