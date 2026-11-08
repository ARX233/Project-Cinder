"""Explicit final WGBANK2 expectation: target readset plus separate paint authority.
No candidate can mint either expectation, and no environment path is approval.
"""
import hashlib,json,re
from pathlib import Path
from resource_pack_common import Entry,require,regular_input
from builtin_ghosts import expected_sources,MAIN_SHA,PROVENANCE_SHA,EXTRACTION_SHA
from builtin_ghosts_v2 import BASE_SHA,paint_expected,inspect
from builtin_data_common import BANK,INDEX,READSET_SHA,HEADER,MAX_BANK,COUNTS,encode_index,pairs

def expected_manifest(path,readset,paint_manifest,paint_readset):
 require(all(x is not None for x in (path,readset,paint_manifest,paint_readset)),'independent V2 dataset, target readset, paint expectation and paint readset required')
 with regular_input(Path(path),65536) as f:raw=f.read(65537)
 require(0<len(raw)<=65536,'V2 expectation budget');obj=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs)
 require(set(obj)=={'schema','category','format','version','files','source_pins','counts','producer','reproduction','authority','claims','paint_section'},'V2 expectation schema')
 require(obj['schema']=='project-cinder-builtin-data-v2' and obj['category']=='recorded-builtin-ghosts-with-original-custom-paints' and obj['format']=='WGBANK2' and type(obj['version']) is int and obj['version']==2 and obj['counts']==COUNTS,'V2 dataset identity/counts')
 e,rs,files,eh,rh=paint_expected(paint_manifest,paint_readset);_,th=expected_sources(readset);require(th==READSET_SHA,'target readset changed')
 require(obj['source_pins']=={'main_sha256':MAIN_SHA,'provenance_sha256':PROVENANCE_SHA,'extraction_manifest_sha256':EXTRACTION_SHA,'source_readset_sha256':READSET_SHA,'base_target_bank_sha256':BASE_SHA,'paint_manifest_sha256':eh,'paint_source_readset_sha256':e['source_readset_sha256'],'paint_source_readset_file_sha256':rh},'V2 independent source pins')
 require(obj['paint_section']=={'format':'WGPAINT1','descriptor_offset':45691305,'payload_offset':45691369,'bytes':e['bytes'],'sha256':e['sha256'],'profiles':148,'keys':e['unique_keys'],'pages':e['page_records'],'source_images':e['unique_source_images']},'V2 paint section independent descriptor')
 require(obj['authority']=='source-pinned independent reconstruction; not candidate-derived trust' and obj['claims']=={'original_or_lua_executed':False,'native_geometry_self_approved':False,'compiled_defaults_synthesized_as_trails':False,'android_or_signer_verified':False,'main_wpk_changed':False,'paint_quantized_or_rescaled':False} and all(type(v) is bool for v in obj['claims'].values()),'V2 authority boundary')
 require(isinstance(obj['producer'],dict) and set(obj['producer'])=={'path','sha256'} and obj['producer']['path']=='tools/builtin_ghosts_v2.py' and re.fullmatch('[0-9a-f]{64}',obj['producer']['sha256']),'V2 producer identity')
 require(isinstance(obj['files'],list) and len(obj['files'])==2,'V2 dataset files');entries={}
 for row,name,limit in zip(obj['files'],(BANK,INDEX),(MAX_BANK,512)):
  require(set(row)=={'path','bytes','sha256'} and row['path']==name and type(row['bytes']) is int and 0<row['bytes']<=limit and re.fullmatch('[0-9a-f]{64}',row['sha256']),'V2 exact file row');entries[name]=Entry(row['bytes'],row['sha256'])
 require(entries[BANK].size==45691369+e['bytes'],'V2 bank exact size');idx=encode_index(entries[BANK]);require(entries[INDEX]==Entry(len(idx),hashlib.sha256(idx).hexdigest()),'V2 index exact namespace/hash')
 r=obj['reproduction'];require(set(r)=={'target_two_runs_equal','paint_two_runs_equal','v2_two_runs_equal','output_sha256'} and all(r[k] is True for k in ('target_two_runs_equal','paint_two_runs_equal','v2_two_runs_equal')) and r['output_sha256']==entries[BANK].sha256,'V2 reproduction commitment')
 return obj,entries,hashlib.sha256(raw).hexdigest()
def inspect_pack(data,paint_manifest,paint_readset):return inspect(data,paint_manifest,paint_readset,full=True)
