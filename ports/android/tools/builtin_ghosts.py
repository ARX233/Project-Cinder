#!/usr/bin/env python3
"""Execution-free recorded Ghost bank producer/validator. Never runs Lua or source code.
All inputs are pinned by separately authored dataset readset, not a candidate APK.
1000 zlib streams are retained on disk; one raw trail at a time is expanded.
"""
import argparse, hashlib, json, os, re, struct, tempfile, zlib
from pathlib import Path
MAGIC=b'WGBANK1\0'; HEADER=128; RECORDS=196; AREAS=8; BLOBS=1000; TRAILS=1267
MAX_BANK=256*1024**2; MAX_RAW=28+4*512+48*8192
MAIN_SHA='2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
PROVENANCE_SHA='45b5c0934c133392bc437400d3e2b43805f87449b3f48674db634e7d26803a52'
EXTRACTION_SHA='3e6b0aee35539b0ac5927adf7912add91576b61085a571807eb150f7a6040e1a'
FIELDS='aero_ aero_mirror_ bonnet_ car_ class_ cool_wild_ crown_ crown_get_date_day_ crown_get_date_hour_ crown_get_date_minute_ crown_get_date_month_ crown_get_date_second_ crown_get_date_year_ crown_win_count_ crown_win_date_day_ crown_win_date_hour_ crown_win_date_minute_ crown_win_date_month_ crown_win_date_second_ crown_win_date_year_ custom_color_ day_ dress_ dress_x_ hour_ minute_ month_ neon_ odo_count_ play_count_ player_win_count_ ramp_ route_ second_ smooth_rough_ title_ trail_size_ trail_sum_ tune_handling_ tune_power_ vinyl_ wheel_ win_count_ wing_ year_'.split()
class BankError(ValueError): pass
def need(ok,msg):
 if not ok: raise BankError(msg)
def digest(b):return hashlib.sha256(b).hexdigest()
def pairs(items):
 d={}
 for k,v in items:need(k not in d,'duplicate JSON key');d[k]=v
 return d
def load(path,limit=16*1024**2):
 b=read_file(path,limit);return json.loads(b.decode('utf-8'),object_pairs_hook=pairs),digest(b)
def read_file(path,limit):
 p=Path(path);need(not p.is_symlink() and p.is_file(),'nonregular input')
 with p.open('rb') as f:b=f.read(limit+1)
 need(len(b)<=limit,'input limit');return b
def safe(s):need(isinstance(s,str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',s)) and all(x not in ('.','..') for x in s.split('/')),'source path');return s
def checked(root,rel,size,sha):
 p=Path(root)/safe(rel);q=Path(root)
 for part in Path(rel).parts:q=q/part;need(not q.is_symlink(),'source symlink')
 b=read_file(p,size);need(len(b)==size and digest(b)==sha,'source pin mismatch: '+rel);return b
def parse_config(b):
 fields={};levels={}
 for line in b.decode('utf-8','strict').splitlines():
  if not line.strip():continue
  if line.startswith('--'):
   m=re.fullmatch(r'-- area ([0-7]) level ([0-9]+)',line)
   if m:levels[int(m[1])]=int(m[2])
   continue
  m=re.fullmatch(r'([A-Za-z][A-Za-z0-9_]*)\s*=\s*(-?[0-9]+)\s*',line)
  need(m is not None,'nonliteral config assignment');key=m[1];n=int(m[2]);need(key not in fields and -(2**31)<=n<2**32,'duplicate/range config scalar');fields[key]=n&0xffffffff
 return fields,levels
def expected_sources(path):
 d,h=load(path);need(d['schema']=='builtin-ghost-source-readset-v1' and d['main_sha256']==MAIN_SHA and d['provenance_sha256']==PROVENANCE_SHA and d['extraction_manifest_sha256']==EXTRACTION_SHA,'dataset source anchors')
 need(len(d['sources'])==RECORDS and d['counts']=={'records':196,'area_slots':1568,'present_trails':1267,'unique_blobs':1000,'logical_raw_bytes':211479748},'dataset counts')
 seen=set();blobs={};refs=0
 for r in d['sources']:
  need(set(r)=={'source','config','trails'} and len(r['trails'])==8,'readset row schema')
  for row in (r['source'],r['config']):
   need(set(row)=={'path','bytes','sha256'} and safe(row['path']) not in seen and type(row['bytes']) is int and 0<row['bytes']<=4*1024**2 and re.fullmatch('[0-9a-f]{64}',row['sha256']),'readset input row');seen.add(row['path'])
  for t in r['trails']:
   if t is None:continue
   need(set(t)=={'path','bytes','sha256','crc32'} and safe(t['path']) not in seen and type(t['bytes']) is int and 28<=t['bytes']<=MAX_RAW and re.fullmatch('[0-9a-f]{64}',t['sha256']) and type(t['crc32']) is int and 0<=t['crc32']<2**32,'trail readset row');seen.add(t['path']);refs+=1
   desc=(t['bytes'],t['crc32']);need(t['sha256'] not in blobs or blobs[t['sha256']]==desc,'contradictory blob');blobs[t['sha256']]=desc
 need(refs==TRAILS and len(blobs)==BLOBS,'readset ref/blob count');return d,h

def pack(provenance,readset,source_root,extract_root,output):
 p,ph=load(provenance);need(ph==PROVENANCE_SHA and p['main_sha256']==MAIN_SHA,'provenance pin')
 approved,rh=expected_sources(readset);records=sorted(p['records'],key=lambda r:tuple(r['metadata'][k] for k in ('id_devel_raw','id1_raw','id2_raw')))
 need(len(records)==RECORDS,'record count');by_source={r['source']['path']:r for r in approved['sources']};unique={};metas=[];ids=set();logical=0
 # Verify every compressed source and every config. No source code is evaluated.
 for r in records:
  ref=by_source.get(r['source_relative_path']);need(ref is not None,'unreviewed source')
  original=checked(source_root,**{'rel':ref['source']['path'],'size':ref['source']['bytes'],'sha':ref['source']['sha256']})
  m=r['metadata'];need(digest(original)==r['compressed_sha256'],'compressed provenance contradiction')
  config=checked(extract_root,ref['config']['path'],ref['config']['bytes'],ref['config']['sha256']);need(digest(config)==m['config_sha256'],'config provenance contradiction')
  decoder=zlib.decompressobj(31);full=decoder.decompress(original,4*1024**2+1)
  need(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail and len(full)==r['decompressed_bytes'] and digest(full)==r['decompressed_sha256'] and full[:len(config)]==config,'gzip/config identity')
  parsed,levels=parse_config(config);globals_=m['global_raw_fields'];want=dict(globals_)
  for a in r['areas']:
   for k,v in a['raw_fields'].items():want['area%d_'%a['area_slot_raw']+k]=v
  need(parsed==want,'literal config/raw metadata contradiction')
  identity=tuple(m[k] for k in ('id_devel_raw','id1_raw','id2_raw'));need(identity not in ids,'duplicate record ID');ids.add(identity)
  need(all(type(n) is int and 0<=n<65536 for n in m['name_codepoints']) and len(m['name_codepoints'])==5,'name uint16')
  head=struct.pack('<III5H2xII32s32sI',*identity,*m['name_codepoints'],m['container_version'],m['original_raw'],bytes.fromhex(r['compressed_sha256']),bytes.fromhex(m['config_sha256']),len(globals_))
  need(34<=len(globals_)<=512,'global count');rows=[]
  for key,value in sorted(globals_.items()):
   need(re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,62}',key) and type(value) is int and 0<=value<2**32,'raw scalar');rows.append(struct.pack('<64sI',key.encode(),value))
  areas=[];need(len(r['areas'])==8,'area count')
  for slot,a in enumerate(r['areas']):
   need(a['area_slot_raw']==slot and set(a['raw_fields'])<=set(FIELDS),'area field schema');raw=a['raw_fields'];mask=sum(1<<i for i,k in enumerate(FIELDS) if k in raw);trail=ref['trails'][slot];sha=None
   if trail is not None:
    data=checked(extract_root,trail['path'],trail['bytes'],trail['sha256']);need(zlib.crc32(data)==trail['crc32'] and len(data)==raw['trail_size_'] and trail['crc32']==raw['trail_sum_'],'trail pin/CRC/metadata')
    ex=a['extraction'];need(ex['sha256']==trail['sha256'] and full[ex['offset']:ex['offset']+len(data)]==data,'trail original gzip slice')
    need(data[:4]==struct.pack('<I',0x70426a),'native magic');sha=trail['sha256'];logical+=len(data)
    stage=struct.unpack_from('<I',data,8+4*struct.unpack_from('<I',data,4)[0])[0];need(stage==ex['header_stage'],'observed native stage contradiction')
    if sha not in unique:unique[sha]=(zlib.compress(data,9),len(data),trail['crc32'],stage)
   else:need(raw.get('trail_size_',0)==0 and not a['has_nonempty_trail'],'empty trail shape')
   need(a.get('level_comment')==levels.get(slot),'source level comment')
   areas.append((mask,[raw.get(k,0) for k in FIELDS],levels.get(slot,-1),sha))
  metas.append((head+b''.join(rows),areas))
 need(len(unique)==BLOBS and logical==211479748,'payload totals')
 ordered=sorted(unique);blobids={sha:i for i,sha in enumerate(ordered)};recorddir=128;blobdir=recorddir+RECORDS*8;metaoff=blobdir+BLOBS*60;metadata=[];dirs=[];at=metaoff
 for prefix,areas in metas:
  data=prefix+b''.join(struct.pack('<Q45IiII',mask,*vals,level,blobids[sha] if sha else 0xffffffff,0) for mask,vals,level,sha in areas)
  dirs.append(struct.pack('<II',at,len(data)));metadata.append(data);at+=len(data)
 dataoff=at;blobrows=[]
 for sha in ordered:
  z,raw,crc,stage=unique[sha];blobrows.append(struct.pack('<QIIIII32s',at,len(z),raw,crc,1,stage,bytes.fromhex(sha)));at+=len(z)
 need(at<=MAX_BANK,'bank budget')
 header=struct.pack('<8s14I32s32s',MAGIC,1,128,RECORDS,AREAS,BLOBS,TRAILS,recorddir,blobdir,metaoff,dataoff,at,68,200,0,bytes.fromhex(MAIN_SHA),bytes.fromhex(rh))
 output=Path(output);need(not output.exists(),'output exists');output.parent.mkdir(parents=True,exist_ok=True)
 with output.open('xb') as out:
  for b in [header,*dirs,*blobrows,*metadata]:out.write(b)
  for sha in ordered:out.write(unique[sha][0])
  out.flush();os.fsync(out.fileno())
 return {'bytes':at,'sha256':digest(output.read_bytes()),'readset_sha256':rh,'records':RECORDS,'present_trails':TRAILS,'unique_blobs':BLOBS,'logical_raw_bytes':logical,'compressed_blob_bytes':at-dataoff,'metadata_bytes':dataoff,'zlib_version':zlib.ZLIB_VERSION}

def inspect(data,readset_sha=None,full=True):
 need(isinstance(data,bytes) and HEADER<=len(data)<=MAX_BANK,'bank size')
 h=struct.unpack_from('<8s14I32s32s',data);need(h[:9]==(MAGIC,1,128,RECORDS,AREAS,BLOBS,TRAILS,128,128+RECORDS*8),'header shape')
 _,_,_,nr,na,nb,nt,rd,bd,mo,do,fs,gs,asz,res,main,rs=h
 need(mo==bd+nb*60 and mo<=do<=fs==len(data) and (gs,asz,res)==(68,200,0) and main.hex()==MAIN_SHA,'header offsets/identity')
 if readset_sha:need(rs.hex()==readset_sha,'readset identity')
 at=mo;ids=[];references=[];raw_total=0
 for i in range(nr):
  off,n=struct.unpack_from('<II',data,rd+i*8);need(off==at and 100+34*68+8*200<=n<=100+512*68+8*200 and n<=do-off,'record bounds')
  devel,id1,id2,*rest=struct.unpack_from('<III5H2xII32s32sI',data,off);names=rest[:5];version,original=rest[5:7];gc=rest[-1]
  identity=(devel,id1,id2);need(not ids or ids[-1]<identity,'record IDs duplicate/order');ids.append(identity)
  need(version==7 and original==0 and 34<=gc<=512 and n==100+gc*68+8*200 and data[off+22:off+24]==b'\0\0','record fixed shape')
  globals_={};last=''
  for j in range(gc):
   key,val=struct.unpack_from('<64sI',data,off+100+j*68);end=key.find(b'\0');need(end>0 and key[end:]==bytes(64-end),'global key padding');key=key[:end].decode('ascii');need(re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,62}',key) and key>last,'global key duplicate/order');last=key;globals_[key]=val
  need(all(globals_.get(k)==v for k,v in zip(['id_devel_','id1_','id2_','ver_','original_'],[*identity,version,original])) and all(globals_.get('name%d_'%j)==v for j,v in enumerate(names)),'global identity contradiction')
  for j in range(8):
   row=struct.unpack_from('<Q45IiII',data,off+100+gc*68+j*200);mask=row[0];vals=row[1:46];level,blob,reserved=row[46:];need(mask>>45==0 and reserved==0 and -1<=level<=100 and all(v==0 or mask&(1<<k) for k,v in enumerate(vals)),'area field shape')
   rawsize=vals[FIELDS.index('trail_size_')];crc=vals[FIELDS.index('trail_sum_')]
   need(mask&(1<<FIELDS.index('trail_size_')) and mask&(1<<FIELDS.index('trail_sum_')),'required trail fields absent')
   if blob==0xffffffff:need(rawsize==0,'absent trail size')
   else:need(blob<nb and 28<=rawsize<=MAX_RAW,'trail ref bounds');references.append((blob,rawsize,crc));raw_total+=rawsize
  at+=n
 need(at==do and len(references)==nt and raw_total==211479748 and len(set(r[0] for r in references))==BLOBS,'metadata/ref closure')
 at=do;last=b'';blobs=[]
 for i in range(nb):
  off,zs,raw,crc,flags,stage,sha=struct.unpack_from('<QIIIII32s',data,bd+i*60);need(off==at and 0<zs<=MAX_RAW+1024 and 28<=raw<=MAX_RAW and zs<=fs-off and flags==1 and 0<stage<2**32 and (not last or last<sha),'blob shape/overlap/hash order');last=sha
  if full:
   z=zlib.decompressobj();b=z.decompress(data[off:off+zs],raw+1);need(len(b)==raw and z.eof and not z.unused_data and not z.unconsumed_tail and digest(b)==sha.hex() and zlib.crc32(b)==crc,'blob integrity')
  if full:need(8+4*struct.unpack_from('<I',b,4)[0]+4<=len(b) and struct.unpack_from('<I',b,8+4*struct.unpack_from('<I',b,4)[0])[0]==stage,'blob observed stage mismatch')
  blobs.append((raw,crc));at+=zs
 need(at==fs and all(blobs[b]==(n,c) for b,n,c in references),'blob/ref contradiction')
 return {'records':nr,'present_trails':nt,'unique_blobs':nb,'logical_raw_bytes':raw_total,'metadata_bytes':do,'compressed_blob_bytes':fs-do,'readset_sha256':rs.hex()}

def main():
 p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True);a=s.add_parser('pack')
 for name in ('provenance','readset','source-root','extract-root','output'):a.add_argument('--'+name,required=True,type=Path)
 a=s.add_parser('inspect');a.add_argument('bank',type=Path);a.add_argument('--readset',required=True,type=Path)
 a=p.parse_args()
 if a.command=='pack':r=pack(a.provenance,a.readset,a.source_root,a.extract_root,a.output)
 else:_,h=expected_sources(a.readset);r=inspect(read_file(a.bank,MAX_BANK),h)
 print(json.dumps(r,sort_keys=True))
if __name__=='__main__':main()
