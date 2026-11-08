"""Explicit independently reviewed built-in dataset expectation, not APK-derived approval."""
import hashlib,json,re
from pathlib import Path
from resource_pack_common import Entry,require,regular_input
from builtin_ghosts import expected_sources,inspect,MAIN_SHA,PROVENANCE_SHA,EXTRACTION_SHA
BANK='assets/builtin-ghosts.bin';INDEX='assets/builtin-ghosts-index-v1.tsv'
READSET_SHA='43199b4c900dab4c8445ca3842621176efd010dffcf50d54fea86c41ee435b58'
HEADER=b'WMMT-BUILTIN-GHOSTS-1\n';MAX_BANK=256*1024**2
COUNTS={'records':196,'area_slots':1568,'present_trails':1267,'unique_blobs':1000,'logical_raw_bytes':211479748}
def pairs(items):
 out={}
 for k,v in items:require(k not in out,'duplicate dataset expectation key');out[k]=v
 return out
def encode_index(entry):return HEADER+f'builtin-ghosts.bin\t{entry.size}\t{entry.sha256}\n'.encode('ascii')
def expected_manifest(path,readset):
 require(path is not None and readset is not None,'independent dataset expectation and full source readset required')
 with regular_input(Path(path),65536) as f:raw=f.read(65537)
 require(0<len(raw)<=65536,'dataset expectation budget');obj=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs)
 require(set(obj)=={'schema','category','format','version','files','source_pins','counts','producer','reproduction','authority','claims'},'dataset expectation schema')
 require(obj['schema']=='project-cinder-builtin-data-v1' and obj['category']=='recorded-builtin-ghosts' and obj['format']=='WGBANK1' and type(obj['version']) is int and obj['version']==1,'dataset identity')
 require(obj['counts']==COUNTS and obj['source_pins']=={'main_sha256':MAIN_SHA,'provenance_sha256':PROVENANCE_SHA,'extraction_manifest_sha256':EXTRACTION_SHA,'source_readset_sha256':READSET_SHA},'dataset independently fixed source pins/counts')
 _,rh=expected_sources(readset);require(rh==READSET_SHA,'dataset expected source readset differs')
 require(obj['authority']=='source-pinned independent reconstruction; not candidate-derived trust' and obj['claims']=={'original_or_lua_executed':False,'native_geometry_self_approved':False,'compiled_defaults_synthesized_as_trails':False,'android_or_signer_verified':False},'dataset authority boundary')
 require(isinstance(obj['producer'],dict) and set(obj['producer'])=={'path','sha256'} and obj['producer']['path']=='tools/builtin_ghosts.py' and re.fullmatch('[0-9a-f]{64}',obj['producer']['sha256']),'dataset producer identity')
 require(isinstance(obj['files'],list) and len(obj['files'])==2,'dataset files')
 entries={}
 for row,name,limit in zip(obj['files'],(BANK,INDEX),(MAX_BANK,512)):
  require(set(row)=={'path','bytes','sha256'} and row['path']==name and type(row['bytes']) is int and 0<row['bytes']<=limit and re.fullmatch('[0-9a-f]{64}',row['sha256']),'dataset exact file row');entries[name]=Entry(row['bytes'],row['sha256'])
 idx=encode_index(entries[BANK]);require(entries[INDEX]==Entry(len(idx),hashlib.sha256(idx).hexdigest()),'dataset index exact namespace/hash')
 r=obj['reproduction'];require(set(r)=={'two_independent_runs_equal','output_sha256','zlib_version'} and r['two_independent_runs_equal'] is True and r['output_sha256']==entries[BANK].sha256 and r['zlib_version']=='1.2.13','dataset reproducibility commitment')
 return obj,entries,hashlib.sha256(raw).hexdigest()
def inspect_pack(data):return inspect(data,READSET_SHA,full=True)
