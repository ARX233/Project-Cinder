#!/usr/bin/env python3
"""Independent, explicit Ghost UI review contract. No APK-derived approvals."""
import hashlib,json,math,re,struct,zlib
from pathlib import Path
from resource_pack_common import Entry,HASH,ResourceError,regular_input,require,safe_path
SCHEMA='project-cinder-ghost-ui-v1'
BANK='assets/ghost-ui.bin'
INDEX='assets/ghost-ui-index-v1.tsv'
HEADER=b'WMMT-GHOST-UI-1\n'
MAX_BANK=256*1024**2
MAX_EXPECTED=64*1024
MAIN_SHA='2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
BASE_MENU_SHA='73f7228574ee5a1d664caa40953920d1580400b00b8526ceaaaf00722ce776e8'
ANIMS=('menu_layout_tg_search_grayout','menu_layout_tg_search_grayout_arrow','menu_layout_tg_seach_ring',
'menu_layout_tg_search_2','menu_layout_tg_seach_ring_2','menu_layout_tg_search_3','menu_layout_tg_seach_ring_3',
'menu_layout_tg_lv','menu_layout_tg_lv_arrow','menu_layout_tg_lv_yourlv','menu_layout_tg_vs_course_new',
'menu_layout_tg_vs_course2','menu_layout_tg_vs_sel','menu_layout_tg_rival','menu_layout_tg_vs')
def pairs(items):
 out={}
 for k,v in items:
  require(k not in out,'duplicate Ghost JSON member');out[k]=v
 return out
def read_json(path):
 require(path is not None,'independent expected Ghost UI manifest required')
 with regular_input(Path(path),MAX_EXPECTED) as f:data=f.read(MAX_EXPECTED+1)
 require(0<len(data)<=MAX_EXPECTED,'Ghost manifest budget')
 return json.loads(data.decode('utf-8','strict'),object_pairs_hook=pairs),hashlib.sha256(data).hexdigest()
def spec(row,path,limit):
 require(isinstance(row,dict) and set(row)=={'path','bytes','sha256'},'Ghost file row fields')
 require(row['path']==path and type(row['bytes']) is int and 0<row['bytes']<=limit and
         isinstance(row['sha256'],str) and HASH.fullmatch(row['sha256']),'Ghost namespace/size/hash')
 return Entry(row['bytes'],row['sha256'])
def encode_index(entry):
 require(16<=entry.size<=MAX_BANK and HASH.fullmatch(entry.sha256),'Ghost bank bounds')
 return HEADER+f'ghost-ui.bin\t{entry.size}\t{entry.sha256}\n'.encode('ascii')
def provenance(p,entry):
 keys={'algorithm','animations','authority','base_menu_sha256','bytes','coverage','format','observed_sha256',
       'original_read_set','publication_authority','referenced_base_sprite_ids','source_main_sha256','sources','sprite_ids','version',
       'animation_count','sprite_count','packer','reproducible_arguments','resource_path'}
 require(isinstance(p,dict) and set(p)==keys,'Ghost provenance fields')
 require(p['algorithm']=='3dxplus-cpu-original-2d-v1' and p['format']=='WCP1' and type(p['version']) is int and p['version']==1 and
         p['source_main_sha256']==MAIN_SHA and p['base_menu_sha256']==BASE_MENU_SHA and
         p['bytes']==entry.size and type(p['bytes']) is int and p['observed_sha256']==entry.sha256 and
         p['publication_authority'] is False and p['coverage']=='original-Ghost-UI-family' and
         p['authority']=='static-original-resource conversion, not catalog approval or runtime equivalence','Ghost provenance identity')
 require(isinstance(p['animations'],list) and len(p['animations'])==len(ANIMS),'Ghost animation count')
 for row,name in zip(p['animations'],ANIMS):
  require(isinstance(row,dict) and set(row)=={'name','frames','records'} and row['name']==name and
          type(row['frames']) is int and 0<row['frames']<=10000 and type(row['records']) is int and
          0<=row['records']<=200000,'Ghost animation schema/order/budget')
 for key in ('sprite_ids','referenced_base_sprite_ids'):
  ids=p[key];require(isinstance(ids,list) and 0<len(ids)<=65535 and all(type(i) is int and 0<=i<=2147483647 for i in ids) and
                    ids==sorted(set(ids)),'Ghost sprite identities')
 require(type(p['animation_count']) is int and p['animation_count']==len(ANIMS) and type(p['sprite_count']) is int and p['sprite_count']==len(p['sprite_ids']) and p['resource_path']=='ghost-ui.bin','Ghost explicit count/path')
 require(isinstance(p['packer'],dict) and set(p['packer'])=={'path','sha256'} and p['packer']['path']=='source/tools/original_convert/ghost_ui.py' and isinstance(p['packer']['sha256'],str) and HASH.fullmatch(p['packer']['sha256']),'Ghost packer provenance')
 args=p['reproducible_arguments']
 require(isinstance(args,dict) and set(args)=={'base_inventory_sha256','main_sha256','output'} and args['main_sha256']==MAIN_SHA and args['output']=='ghost-ui.bin' and isinstance(args['base_inventory_sha256'],str) and HASH.fullmatch(args['base_inventory_sha256']),'Ghost deterministic source arguments')
 require(set(p['sprite_ids']).isdisjoint(p['referenced_base_sprite_ids']),'Ghost overwrites base sprites')
 require(isinstance(p['sources'],list) and len(p['sources'])==len(ANIMS),'Ghost source count')
 reads=p['original_read_set'];require(isinstance(reads,dict) and len(ANIMS)<=len(reads)<=512,'Ghost source read-set')
 for name,row in reads.items():
  safe_path(name)
  require(re.fullmatch(r'data/(?:anime/[A-Za-z0-9_]+\.anm|sprite/[A-Za-z0-9_]+\.png)',name) is not None and
          isinstance(row,dict) and set(row)=={'bytes','sha256'} and type(row['bytes']) is int and
          0<row['bytes']<=16*1024**2 and isinstance(row['sha256'],str) and HASH.fullmatch(row['sha256']),'Ghost source path/type/budget')
 for row,name in zip(p['sources'],ANIMS):
  path='data/anime/'+name+'.anm';e=spec(row,path,16*1024**2)
  require(reads.get(path)=={'bytes':e.size,'sha256':e.sha256},'Ghost ANM/read-set contradiction')
 require({k for k in reads if k.endswith('.anm')}=={'data/anime/'+n+'.anm' for n in ANIMS},'unknown Ghost ANM source')
 return p

def expected_manifest(path):
 obj,pin=read_json(path)
 require(isinstance(obj,dict) and set(obj)=={'schema','category','format','version','files','provenance','generator','reviewed_pack_manifest_sha256'},'Ghost expected schema')
 require(obj['schema']==SCHEMA and obj['category']=='ghost-ui' and obj['format']=='WCP1' and type(obj['version']) is int and obj['version']==1,'Ghost expected identity')
 require(isinstance(obj['files'],list) and len(obj['files'])==2,'Ghost expected file count')
 bank=spec(obj['files'][0],BANK,MAX_BANK);index=spec(obj['files'][1],INDEX,512)
 raw=encode_index(bank)
 require(index==Entry(len(raw),hashlib.sha256(raw).hexdigest()),'Ghost metadata is not exact derived inventory')
 provenance(obj['provenance'],bank)
 generator=spec(obj['generator'],'tools/original_convert/ghost_ui.py',64*1024)
 require(generator.sha256==obj['provenance']['packer']['sha256'],'Ghost generator/provenance hash contradiction')
 require(isinstance(obj['reviewed_pack_manifest_sha256'],str) and HASH.fullmatch(obj['reviewed_pack_manifest_sha256']),'missing independent source-pack approval reference')
 return obj,{BANK:bank,INDEX:index},pin

def inspect_pack(data,expected):
 """Full WCP1 bounds/type/DEFLATE/ID/frames/records check; no pixels rendered."""
 require(isinstance(data,bytes) and 16<=len(data)<=MAX_BANK,'Ghost WCP1 byte budget')
 at=0
 def take(n):
  nonlocal at
  require(type(n) is int and 0<=n<=len(data)-at,'truncated Ghost WCP1')
  value=data[at:at+n];at+=n;return value
 def unpack(fmt):return struct.unpack(fmt,take(struct.calcsize(fmt)))
 magic,version,ns,na=unpack('<4sIII')
 require(magic==b'WCP1' and version==1 and ns==len(expected['sprite_ids']) and na==len(expected['animations']),'Ghost WCP1 version/count')
 expanded=0;ids=[]
 for sid_expected in expected['sprite_ids']:
  sid,w,h,zs=unpack('<iHHI')
  require(sid==sid_expected and 0<w<=2048 and 0<h<=2048,'Ghost WCP1 sprite namespace/dimensions')
  raw=w*h*4;expanded+=raw;require(expanded<=MAX_BANK,'Ghost WCP1 expanded pixels budget')
  if zs:
   require(zs<=raw+((raw+16382)//16383)*5+6,'Ghost WCP1 compressed sprite budget')
   packed=take(zs);d=zlib.decompressobj();pixels=d.decompress(packed,raw+1)
   require(len(pixels)==raw and d.eof and not d.unused_data and not d.unconsumed_tail,'Ghost WCP1 malformed DEFLATE/size')
  else:take(raw)
  ids.append(sid)
 allowed=set(ids)|set(expected['referenced_base_sprite_ids'])|{-1}
 actual=[]
 for reference in expected['animations']:
  name,nf,nr=unpack('<48sII')
  require(b'\0' in name,'Ghost WCP1 unterminated name');end=name.index(0)
  require(not any(name[end:]),'Ghost WCP1 noncanonical name padding')
  name=name[:end].decode('ascii','strict')
  require({'name':name,'frames':nf,'records':nr}==reference,'Ghost WCP1 animation identity/count')
  frames=[unpack('<II') for _ in range(nf)]
  require(all(start<=nr and count<=nr-start for start,count in frames),'Ghost WCP1 frame record bounds')
  for _ in range(nr):
   row=unpack('<iH6f4h4h')
   require(row[0] in allowed and row[1]<=2 and all(math.isfinite(f) for f in row[2:8]),'Ghost WCP1 record type/sprite/value')
  actual.append(reference)
 require(at==len(data),'Ghost WCP1 trailing bytes')
 return {'sprites':len(ids),'animations':len(actual),'expanded_pixel_bytes':expanded}
