#!/usr/bin/env python3
"""Source-verified WGBANK2 bank/index/expectation/pin producer. No APK input.
Requires independent target readset and independently approved paint expectation,
full paint source readset and second real producer output. Does not sign/install.
"""
import argparse,hashlib,json,os
from pathlib import Path
from builtin_ghosts import expected_sources,MAIN_SHA,PROVENANCE_SHA,EXTRACTION_SHA,read_file,digest,need
from builtin_ghosts_v2 import extend,paint_expected,BASE_SHA,MAX_PAINT
from builtin_data_v2_common import expected_manifest,COUNTS,READSET_SHA,BANK,INDEX,encode_index
from resource_pack_common import Entry,new_output,private_directory,write_json_exclusive

def build(base_bank,source_readset,paint_bank,reproduced_paint_bank,paint_manifest,paint_readset,output_dir):
 _,target_hash=expected_sources(source_readset);need(target_hash==READSET_SHA,'target readset source pin')
 e,rs,source_files,eh,rh=paint_expected(paint_manifest,paint_readset,recheck=True)
 need(Path(paint_bank).resolve()!=Path(reproduced_paint_bank).resolve(),'distinct second paint producer output required')
 first=read_file(paint_bank,MAX_PAINT);second=read_file(reproduced_paint_bank,MAX_PAINT);need(first==second and len(first)==e['bytes'] and digest(first)==e['sha256'],'paint producer reproduction mismatch');del first,second
 out=new_output(output_dir);private_directory(out);private_directory(out/'assets');private_directory(out/'generated')
 r=extend(base_bank,paint_bank,paint_manifest,paint_readset,out/BANK,source_pixels=True)
 again=extend(base_bank,reproduced_paint_bank,paint_manifest,paint_readset,out/'reproduced-builtin-ghosts.bin',source_pixels=True);need(r['sha256']==again['sha256'] and r['bytes']==again['bytes'],'V2 byte reproducibility mismatch')
 entry=Entry(r['bytes'],r['sha256']);index=encode_index(entry)
 with (out/INDEX).open('xb') as f:f.write(index);f.flush();os.fsync(f.fileno())
 producer=Path(__file__).with_name('builtin_ghosts_v2.py')
 obj={'schema':'project-cinder-builtin-data-v2','category':'recorded-builtin-ghosts-with-original-custom-paints','format':'WGBANK2','version':2,
 'files':[{'path':BANK,'bytes':entry.size,'sha256':entry.sha256},{'path':INDEX,'bytes':len(index),'sha256':digest(index)}],
 'source_pins':{'main_sha256':MAIN_SHA,'provenance_sha256':PROVENANCE_SHA,'extraction_manifest_sha256':EXTRACTION_SHA,'source_readset_sha256':READSET_SHA,'base_target_bank_sha256':BASE_SHA,'paint_manifest_sha256':eh,'paint_source_readset_sha256':e['source_readset_sha256'],'paint_source_readset_file_sha256':rh},'counts':COUNTS,
 'producer':{'path':'tools/builtin_ghosts_v2.py','sha256':digest(producer.read_bytes())},
 'reproduction':{'target_two_runs_equal':True,'paint_two_runs_equal':True,'v2_two_runs_equal':True,'output_sha256':entry.sha256},
 'authority':'source-pinned independent reconstruction; not candidate-derived trust',
 'claims':{'original_or_lua_executed':False,'native_geometry_self_approved':False,'compiled_defaults_synthesized_as_trails':False,'android_or_signer_verified':False,'main_wpk_changed':False,'paint_quantized_or_rescaled':False},
 'paint_section':{'format':'WGPAINT1','descriptor_offset':r['paint_descriptor_offset'],'payload_offset':r['paint_offset'],'bytes':e['bytes'],'sha256':e['sha256'],'profiles':148,'keys':e['unique_keys'],'pages':e['page_records'],'source_images':e['unique_source_images']}}
 write_json_exclusive(out/'expected-builtin-data-v2.json',obj);expected_manifest(out/'expected-builtin-data-v2.json',source_readset,paint_manifest,paint_readset)
 raw=bytes.fromhex(entry.sha256);lines=[','.join('0x%02x'%v for v in raw[i:i+16]) for i in (0,16)]
 header='/* Final reviewed WGBANK2 source dataset, not runtime candidate approval. */\n#ifndef GHOST_CATALOG_PIN_H\n#define GHOST_CATALOG_PIN_H\n#include <stdint.h>\nstatic const uint8_t GHOST_CATALOG_APPROVED_SHA256[32]={\n '+lines[0]+',\n '+lines[1]+'};\n#endif\n'
 with (out/'generated/ghost_catalog_pin.h').open('x') as f:f.write(header);f.flush();os.fsync(f.fileno())
 receipt={**r,'schema':'project-cinder-builtin-data-v2-receipt','expected_manifest_sha256':digest((out/'expected-builtin-data-v2.json').read_bytes()),'index_sha256':digest(index),'producer_sha256':obj['producer']['sha256'],'original_or_lua_executed':False,'source_or_main_wpk_changed':False,'apk_or_signer_or_gpu_verified':False,'target_two_runs_equal':True,'paint_two_runs_equal':True,'v2_two_runs_equal':True}
 write_json_exclusive(out/'receipt.json',receipt);return receipt

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('base-bank','source-readset','paint-bank','reproduced-paint-bank','paint-manifest','paint-readset','output-dir'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();print(json.dumps(build(a.base_bank,a.source_readset,a.paint_bank,a.reproduced_paint_bank,a.paint_manifest,a.paint_readset,a.output_dir),sort_keys=True))
if __name__=='__main__':main()
