#!/usr/bin/env python3
"""Explicit TA-ranking APK profile. Legacy nine-reference verifiers stay unchanged.
Requires independent v5 approval AND the reviewed v4 bank, not candidate claims.
Offline byte/format verification; no executable, network or device actions.
"""
import argparse,hashlib,io,json,zipfile,zlib
from pathlib import Path
from types import SimpleNamespace
from resource_pack_common import KNOWN_BASELINES,MAX_CATALOG,MAX_INDEX,TOP4,ResourceError,StrictZip,load_catalog,parse_sidecars,regular_input,require,sha256
from verify_original_convert_apk import runtime_inventory
from verify_resource_free_apk import REQUIRED_FILES,ALLOWED_ASSETS,SIGNER,signature_text,signature_der,expected_digest,MAX_SIGNATURE
from verify_cinder_apk import launcher_inventory,WALLPAPER
from arcade_ui_common import expected_manifest as ui_expected,BANK as UI_BANK
from builtin_data_v2_common import expected_manifest,encode_index,inspect_pack,BANK,INDEX
import ranking_ui_v5 as v5
MAX_APK=128*1024**2;MAX_EXPANDED=256*1024**2

def verify(path,*,runtime,baselines,sidecars,launcher,ghost,dataset,readset,paint_manifest,paint_readset,ranking,ghost_bank):
 approved,data,approval_hash=expected_manifest(dataset,readset,paint_manifest,paint_readset)
 uia,old_ui,uihash=ui_expected(ghost)
 raw=v5.read_regular(ranking,v5.MAX_JSON)
 ra=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=v5.pairs);rankhash=hashlib.sha256(raw).hexdigest()
 v5.validate_expected(ra,base_expected=uia,base_manifest_sha256=uihash)
 require(ra.get('schema')==v5.SCHEMA and ra['provenance']['base_v4']['expected_manifest_sha256']==uihash,'ranking/v4 independent reference mismatch')
 require(ra['provenance']['base_v4']['files']==uia['files'],'ranking claims a different v4 bank')
 base=v5.read_regular(ghost_bank,v5.MAX_BANK)
 require(len(base)==old_ui[UI_BANK].size and hashlib.sha256(base).hexdigest()==old_ui[UI_BANK].sha256,'v4 bank differs from independent approved reference')
 require(len(ra['files'])==2 and [x['path'] for x in ra['files']]==[v5.BANK_PATH,v5.INDEX_PATH],'v5 exact finite namespace')
 ui={}
 for x in ra['files']:
  require(type(x['bytes']) is int and 0<x['bytes']<=v5.MAX_BANK and isinstance(x['sha256'],str),'v5 member bounds')
  v5.pin(x['sha256']);ui[x['path']]=SimpleNamespace(size=x['bytes'],sha256=x['sha256'])
 inventory,ih=runtime_inventory(runtime);art,ah=launcher_inventory(launcher)
 groups=[set(inventory),set(art),set(ui),set(data)]
 require(all(a.isdisjoint(b) for i,a in enumerate(groups)for b in groups[i+1:]),'independent inventories overlap')
 cp=expected_digest(baselines,MAX_CATALOG);ip=expected_digest(sidecars,MAX_INDEX)
 require(cp is not None and ip is not None,'independent old metadata required')
 expected=set(REQUIRED_FILES)|set(ALLOWED_ASSETS)|set().union(*groups);optional={'assets/'+n for n in TOP4};dirs={'META-INF/'}
 for name in expected|optional:
  parts=name.split('/');dirs.update('/'.join(parts[:i])+'/' for i in range(1,len(parts)))
 with regular_input(Path(path).absolute(),MAX_APK) as source:
  original=sha256(source);source.seek(0,2);size=source.tell()
  with StrictZip(source,max_bytes=MAX_APK,max_entries=1024,max_total=MAX_EXPANDED,max_file=MAX_EXPANDED,apk=True) as apk:
   files=set(apk.files);require(expected<=files,'incomplete TA-ranking Cinder APK');signatures={}
   require('assets/ghost-ui-index-v1.tsv' not in files,'ambiguous old/new UI approval generations')
   for info in apk.zip.infolist():
    name=info.filename
    if info.is_dir():require(name in dirs,'unreviewed APK directory: '+name);continue
    require(info.file_size>0,'empty outer APK member')
    if name in expected|optional:continue
    if name=='META-INF/MANIFEST.MF':signatures[name]=None;continue
    match=SIGNER.fullmatch(name);require(match is not None,'unreviewed APK member: '+name);signatures[name]=match.groups()
   if signatures:
    require('META-INF/MANIFEST.MF' in signatures,'missing JAR public manifest');signers={}
    for name,pair in signatures.items():
     if pair is not None:signers.setdefault(pair[0],set()).add(pair[1])
    require(signers and all('SF' in kinds and len(kinds)==2 and len(kinds&{'RSA','DSA','EC'})==1 for kinds in signers.values()),'unpaired JAR signature material')
   old_catalog=apk.read('assets/data-baselines.zip',MAX_CATALOG)
   require(hashlib.sha256(old_catalog).hexdigest()==cp,'old baseline metadata changed')
   require(load_catalog(io.BytesIO(old_catalog)).keys()==KNOWN_BASELINES,'legacy baseline set changed')
   old_index=apk.read('assets/sidecars-index-v1.tsv',MAX_INDEX)
   require(hashlib.sha256(old_index).hexdigest()==ip,'old41 metadata changed')
   old_rows=parse_sidecars(old_index);require(len(old_rows)==41,'old41 count changed')
   require(('assets/backfire.wpk' in files)==('assets/backfire.bfx' in files),'incomplete old backfire pair')
   b=apk.read(BANK,data[BANK].size);idx=apk.read(INDEX,512)
   require(len(b)==data[BANK].size and hashlib.sha256(b).hexdigest()==data[BANK].sha256,'dataset differs from independent expectation')
   require(idx==encode_index(data[BANK]) and len(idx)==data[INDEX].size and hashlib.sha256(idx).hexdigest()==data[INDEX].sha256,'dataset index contradiction')
   stats=inspect_pack(b,paint_manifest,paint_readset)
   ub=apk.read(v5.BANK_PATH,ui[v5.BANK_PATH].size);ux=apk.read(v5.INDEX_PATH,512)
   ui_stats=v5.verify(ub,ux,ra,base=base,base_expected=uia,base_manifest_sha256=uihash)
   require(ui_stats['preservation_compared'],'missing v4 byte-preservation proof')
   for name in sorted(files-set(ALLOWED_ASSETS)-set(ui)-set(data)):
    if name in art:apk.consume(name,limit=art[name].size,expected=art[name])
    elif name in inventory:apk.consume(name,limit=inventory[name].size,expected=inventory[name])
    elif name in optional:apk.consume(name,limit=old_rows[name[7:]].size,expected=old_rows[name[7:]])
    elif name=='META-INF/MANIFEST.MF':signature_text(apk.read(name,MAX_SIGNATURE),b'Manifest-Version: 1.0')
    elif name in signatures:
     sb=apk.read(name,MAX_SIGNATURE)
     if signatures[name][1]=='SF':signature_text(sb,b'Signature-Version: 1.0')
     else:signature_der(sb)
    else:apk.consume(name,limit=MAX_EXPANDED)
  require(sha256(source)==original,'APK changed while verifying')
 return {'profile':'project-cinder-ta-ranking-v1','apk_sha256':original,'bytes':size,'runtime_members':len(inventory),'runtime_inventory_sha256':ih,'launcher_inventory_sha256':ah,'wallpaper_sha256':art[WALLPAPER].sha256,'sidecar_count':len(old_rows),'base_ghost_ui_manifest_sha256':uihash,'ranking_ui_manifest_sha256':rankhash,'dataset_manifest_sha256':approval_hash,'dataset_sha256':data[BANK].sha256,'legacy_profiles_changed':False,'main_resource_embedded':False,'original_main_embedded':False,'signature_android_gpu_verified':False,'ta_global_service_deployed':False,'compiled_defaults_used_as_recordings':False,'ranking_ui':ui_stats,**stats}

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('apk',type=Path)
 for n in ('runtime','baselines','sidecars','launcher','ghost-ui-manifest','builtin-data-manifest','builtin-source-readset','paint-manifest','paint-source-readset','ranking-ui-manifest','ghost-ui-bank'):p.add_argument('--expected-'+n,type=Path,required=True)
 a=p.parse_args(argv)
 try:r=verify(a.apk,runtime=a.expected_runtime,baselines=a.expected_baselines,sidecars=a.expected_sidecars,launcher=a.expected_launcher,ghost=a.expected_ghost_ui_manifest,dataset=a.expected_builtin_data_manifest,readset=a.expected_builtin_source_readset,paint_manifest=a.expected_paint_manifest,paint_readset=a.expected_paint_source_readset,ranking=a.expected_ranking_ui_manifest,ghost_bank=a.expected_ghost_ui_bank)
 except (ResourceError,OSError,ValueError,KeyError,TypeError,RuntimeError,zipfile.BadZipFile,zlib.error) as e:p.exit(2,'TA-ranking APK refused: '+str(e)+'\n')
 print(json.dumps(r,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
