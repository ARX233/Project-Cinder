#!/usr/bin/env python3
"""Bind an independently reviewed original-source Ghost bank to isolated metadata.
No APK input, environment approval, source art synthesis, device or signing calls.
"""
import argparse,hashlib,json,os,sys,zlib
from pathlib import Path
from resource_pack_common import Entry,ResourceError,new_output,private_directory,regular_input,require,publish_exclusive,write_json_exclusive
from arcade_ui_common import BANK,INDEX,SCHEMA,MAX_BANK,read_json,spec,provenance,encode_index,inspect_pack,expected_manifest

def build(pack,reviewed_pack_manifest,reviewed_provenance,generator,output):
 approval,approval_sha=read_json(reviewed_pack_manifest)
 require(isinstance(approval,dict) and set(approval)=={'files'} and isinstance(approval['files'],list) and len(approval['files'])==1,'independent pack manifest schema/count')
 row=approval['files'][0]
 require(isinstance(row,dict) and set(row)=={'path','size','sha256'},'independent pack row schema')
 entry=spec({'path':row['path'],'bytes':row['size'],'sha256':row['sha256']},'ghost-ui.bin',MAX_BANK)
 p,p_sha=read_json(reviewed_provenance);provenance(p,entry)
 with regular_input(Path(generator),64*1024) as source:gdata=source.read()
 with regular_input(Path(pack),MAX_BANK) as source:data=source.read(MAX_BANK+1)
 require(Entry(len(data),hashlib.sha256(data).hexdigest())==entry,'Ghost pack differs from independently reviewed expectation')
 stats=inspect_pack(data,p);index=encode_index(entry)
 expected={'schema':SCHEMA,'category':'ghost-ui','format':'WCP1','version':1,
  'files':[{'path':BANK,'bytes':entry.size,'sha256':entry.sha256},{'path':INDEX,'bytes':len(index),'sha256':hashlib.sha256(index).hexdigest()}],
  'provenance':p,'generator':{'path':'tools/original_convert/ghost_ui.py','bytes':len(gdata),'sha256':hashlib.sha256(gdata).hexdigest()},
  'reviewed_pack_manifest_sha256':approval_sha}
 out=new_output(output);private_directory(out);private_directory(out/'assets')
 with (out/INDEX).open('xb') as f:f.write(index);f.flush();os.fsync(f.fileno())
 publish_exclusive(Path(pack),out/BANK,entry)
 write_json_exclusive(out/'expected-ghost-ui-v4.json',expected)
 expected_manifest(out/'expected-ghost-ui-v4.json')
 receipt={'schema':'project-cinder-ghost-ui-metadata-receipt-v4','reviewed_pack_manifest_sha256':approval_sha,
          'reviewed_provenance_sha256':p_sha,'generator_sha256':expected['generator']['sha256'],
          'pack_sha256':entry.sha256,'pack_bytes':entry.size,'metadata_sha256':hashlib.sha256(index).hexdigest(),
          'source_main_sha256':p['source_main_sha256'],'base_menu_sha256':p['base_menu_sha256'],**stats,
          'approval_origin':'explicit separately authored original-source manifest; not candidate APK',
          'main_resource_copied':False,'legacy_metadata_changed':False,'application_code_executed':False}
 write_json_exclusive(out/'receipt.json',receipt)
 return receipt

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('pack','reviewed-pack-manifest','reviewed-provenance','generator','output-dir'):p.add_argument('--'+name,required=True,type=Path)
 a=p.parse_args(argv)
 try:r=build(a.pack,a.reviewed_pack_manifest,a.reviewed_provenance,a.generator,a.output_dir)
 except (ResourceError,OSError,ValueError,KeyError,TypeError,RuntimeError,zlib.error) as e:p.exit(2,'Ghost metadata refused: '+str(e)+'\n')
 print(json.dumps(r,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
