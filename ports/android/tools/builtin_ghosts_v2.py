#!/usr/bin/env python3
"""WGBANK2: unchanged source-pinned target bank plus bounded complete WGPAINT1.
No source or Lua execution. Explicit independent component expectation/readset
required. Source checking/pixel reconstruction is opt-in producer-only, never APK
candidate-derived authority; native uses streaming section callbacks.
"""
import argparse,hashlib,io,json,os,re,struct,zlib
from pathlib import Path
from builtin_ghosts import BankError,need,load,read_file,digest,inspect as inspect_v1,MAIN_SHA,MAX_BANK
BASE_SHA='2a301f797490d7bc460aa71916587c424186254c43872c0882bf3c3fe7616e7a'
TARGET_READSET_SHA='43199b4c900dab4c8445ca3842621176efd010dffcf50d54fea86c41ee435b58'
MAX_PAINT=128*1024**2;MAX_IMAGE=16*1024**2;ORIGINAL=Path('/Volumes/MacSave/WMMT3 Phone/Fulldata/Wangan Midnight 3DX+[banwu]/Wangan Midnight 3DX+')
def canonical(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
def safe_path(s):
 need(isinstance(s,str) and len(s)<128 and re.fullmatch(r'data/car/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+',s) and all(p not in ('.','..','') for p in s.split('/')),'paint source path');return s
def paint_expected(path,readset,*,recheck=False):
 e,eh=load(path,65536);need(set(e)=={'schema','format','bytes','sha256','source_readset_sha256','source_readset_file_sha256','profiles_covered','unique_keys','page_records','unique_source_images','source_main_sha256','coverage_sha256'},'paint external expectation schema')
 need(e['schema']=='project-cinder-ghost-paint-expectation-v1' and e['format']=='WGPAINT1' and type(e['bytes']) is int and 128<=e['bytes']<=MAX_PAINT and e['source_main_sha256']==MAIN_SHA and e['profiles_covered']==148 and 0<e['unique_keys']<=148 and 0<e['page_records']<=1024 and 0<e['unique_source_images']<=e['page_records'],'paint expected identity/counts')
 for k in ('sha256','source_readset_sha256','source_readset_file_sha256','coverage_sha256'):need(isinstance(e[k],str) and re.fullmatch('[0-9a-f]{64}',e[k]),'paint source hash')
 rs,rh=load(readset,8*1024**2);need(rh==e['source_readset_file_sha256'] and digest(canonical(rs))==e['source_readset_sha256'],'paint readset identity')
 need(set(rs)=={'schema','files','recipe'} and rs['schema']=='WGPAINT1-source-read-set-v1' and rs['recipe']['main_sha256']==MAIN_SHA and 1<=len(rs['files'])<=2048,'paint readset shape')
 files={};previous=''
 for r in rs['files']:
  need(set(r)=={'path','bytes','sha256'} and isinstance(r['path'],str) and r['path']>previous and Path(r['path']).is_absolute() and type(r['bytes']) is int and 0<r['bytes']<=32*1024**2 and re.fullmatch('[0-9a-f]{64}',r['sha256']),'paint readset rows');previous=r['path'];files[r['path']]=r
  if recheck:
   raw=read_file(r['path'],r['bytes']);need(len(raw)==r['bytes'] and digest(raw)==r['sha256'],'paint original readset changed: '+r['path'])
 return e,rs,files,eh,rh

def inspect_paint(data,expected,source_files,*,source_pixels=False):
 need(isinstance(data,bytes) and 128<=len(data)<=MAX_PAINT and len(data)==expected['bytes'] and digest(data)==expected['sha256'],'paint complete section SHA/length')
 h=struct.unpack_from('<8s6I3Q',data);magic,version,hs,stride,count,maxdim,codec,table,body,total=h
 need((magic,version,hs,stride,maxdim,codec,table,total)==(b'WGPAINT1',1,128,320,2048,1,128,len(data)) and count==expected['page_records'] and 0<count<=1024 and body==128+320*count and body<=total,'paint header')
 need(data[56:88].hex()==expected['source_readset_sha256'] and data[88:120].hex()==MAIN_SHA and struct.unpack_from('<II',data,120)==(1,0),'paint header source/flags')
 previous=None;at=body;groups={};sources=set();maxraw=0
 for i in range(count):
  p=128+320*i;pack,color,aero,page,alpha,w,height,res,raw,zs,crc,off=struct.unpack_from('<HBBBBHHHIIIQ',data,p)
  key=(pack,color,aero,page);need((previous is None or previous<key) and pack<55 and 1<=color<=10 and 0<=aero<=3 and 1<=page<=3 and alpha in (0,1) and 1<=w<=2048 and 1<=height<=2048 and res==0 and raw==w*height*4 and raw<=MAX_IMAGE and 0<zs<=MAX_IMAGE+1024 and off==at and zs<=total-off,'paint record key/dimensions/overlap');previous=key
  def text(a,n):
   v=data[p+a:p+a+n];end=v.find(b'\0');need(end>0 and v[end:]==bytes(n-end),'paint string padding');return v[:end].decode('ascii','strict')
  material=text(128,48);path=safe_path(text(176,128));need(re.fullmatch('[A-Za-z0-9_.-]{1,47}',material) and material not in ('.','..') and data[p+304:p+320]==bytes(16),'paint material/reserved')
  source_sha=data[p+64:p+96].hex();lua_sha=data[p+96:p+128].hex();image_path=str(ORIGINAL/path);lua_path=str(ORIGINAL/('/'.join(path.split('/')[:3])+'/car.lua'))
  need(image_path in source_files and source_files[image_path]['sha256']==source_sha and lua_path in source_files and source_files[lua_path]['sha256']==lua_sha,'paint original image/Lua source binding')
  d=zlib.decompressobj();pixels=d.decompress(data[off:off+zs],raw+1);need(len(pixels)==raw and d.eof and not d.unused_data and not d.unconsumed_tail and digest(pixels)==data[p+32:p+64].hex() and zlib.crc32(pixels)==crc and int(min(pixels[3::4])<255)==alpha,'paint exact zlib/RGBA/SHA/CRC/alpha')
  if source_pixels:
   from PIL import Image
   source=read_file(image_path,32*1024**2);need(digest(source)==source_sha,'original paint image changed')
   if path.endswith('.igb'):
    # Explicit original no-op, NOT a missing-texture fallback or guessed alias:
    # GC8 aeroA Lua BaseTexture2 names absent A01; actual IGB retains A03 DDS.
    need((pack,color,aero,page,path,material,w,height) in ((35,1,1,2,'data/car/sub_GC8/aeroA/body.igb','gc8_body02_colA03',256,256),(35,2,1,2,'data/car/sub_GC8/aeroA/body.igb','gc8_body02_colA03',256,256)) and source_sha=='bc19183efa11c7c3da00ef2491239dd36c13a6db108c5983e993e0e7fcfe25aa','unreviewed embedded paint rule')
    import sys
    stage=str(Path(__file__).parent/'stage')
    if stage not in sys.path:sys.path.insert(0,stage)
    from igb import IGB
    import tex
    f=IGB(image_path);need(f.buf==source,'IGB snapshot changed')
    images={}
    for image in f.of_type('igImage'):
     if image[22] is not None:
      name=f.string(image[22]).replace('\\','/').rsplit('/',1)[-1].rsplit('.',1)[0];need(name not in images,'ambiguous original igImage');images[name]=image
    need('gc8_body02_colA01' not in images and material in images,'original no-replacement material proof')
    image=images[material];memory=f.ref(image[13]);need(image.index==166 and image[11].i32==15 and memory is not None and bytes(memory.mem)==source[50032:115568] and digest(bytes(memory.mem))=='5bd8a6da3cd3db2f15bf18d57b516c93ad47d8f33a8b40485f908147e67904aa','original DDS object/span/hash')
    original=tex.to_pil(image,memory.mem).convert('RGBA').tobytes();need(digest(original)=='1609a6530c4ee2077ba21d2c8e14ae39e05f29ecc20eb3f1366bb3bdf35a7028' and original==pixels,'embedded DDS exact original RGBA/UV rows')
   else:
    with Image.open(io.BytesIO(source)) as image:
     need(image.format in ('TGA','PNG','DDS') and image.size==(w,height),'original paint image shape');original=image.convert('RGBA').transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes();need(original==pixels,'paint pixels differ from full original RGBA/UV rows')
  groups.setdefault((pack,color,aero),[]).append((page,raw));sources.add(path);at+=zs
 need(at==len(data) and len(groups)==expected['unique_keys'] and len(sources)==expected['unique_source_images'] and all(v[0][0]==1 and len(v)<=3 for v in groups.values()),'paint complete key/page closure')
 return {'paint_profiles':expected['profiles_covered'],'paint_keys':len(groups),'paint_pages':count,'paint_source_images':len(sources),'paint_section_bytes':len(data),'paint_max_selected_rgba_bytes':max(sum(raw for page,raw in v) for v in groups.values())}

def extend(base_bank,paint_bank,paint_manifest,paint_readset,output,*,source_pixels=True):
 base=read_file(base_bank,MAX_BANK);need(digest(base)==BASE_SHA,'base target bank is not independently source-pinned V1 proof');inspect_v1(base,TARGET_READSET_SHA,full=True)
 e,rs,files,eh,rh=paint_expected(paint_manifest,paint_readset,recheck=source_pixels);paint=read_file(paint_bank,MAX_PAINT);stats=inspect_paint(paint,e,files,source_pixels=source_pixels)
 need(len(base)+64+len(paint)<=MAX_BANK,'WGBANK2 file budget');head=bytearray(base);head[:8]=b'WGBANK2\0';struct.pack_into('<I',head,8,2);struct.pack_into('<I',head,48,len(base)+64+len(paint));struct.pack_into('<I',head,60,len(base));directory=struct.pack('<8sIIQQ32s',b'WGPSEC1\0',1,0,len(base)+64,len(paint),bytes.fromhex(e['sha256']))
 out=Path(output);need(not out.exists(),'output already exists');out.parent.mkdir(parents=True,exist_ok=True)
 with out.open('xb') as f:
  for b in (head,directory,paint):f.write(b)
  f.flush();os.fsync(f.fileno())
 return {'bytes':out.stat().st_size,'sha256':digest(out.read_bytes()),'paint_descriptor_offset':len(base),'paint_offset':len(base)+64,'paint_sha256':e['sha256'],'paint_manifest_sha256':eh,'paint_source_readset_sha256':e['source_readset_sha256'],'paint_source_readset_file_sha256':rh,**stats}

def inspect(data,paint_manifest,paint_readset,*,full=True):
 need(isinstance(data,bytes) and 128<=len(data)<=MAX_BANK and data[:8]==b'WGBANK2\0' and struct.unpack_from('<I',data,8)[0]==2 and struct.unpack_from('<I',data,48)[0]==len(data),'WGBANK2 header')
 directory=struct.unpack_from('<I',data,60)[0];need(61696<=directory<=len(data)-64,'WGBANK2 section directory range')
 magic,v,flags,off,n,sha=struct.unpack_from('<8sIIQQ32s',data,directory);need((magic,v,flags,off)==(b'WGPSEC1\0',1,0,directory+64) and 128<=n<=MAX_PAINT and n==len(data)-off,'WGBANK2 section bounds/overlap')
 e,rs,files,eh,rh=paint_expected(paint_manifest,paint_readset);need(n==e['bytes'] and sha.hex()==e['sha256'],'WGBANK2 external section expectation')
 base=bytearray(data[:directory]);base[:8]=b'WGBANK1\0';struct.pack_into('<I',base,8,1);struct.pack_into('<I',base,48,directory);struct.pack_into('<I',base,60,0);need(digest(base)==BASE_SHA,'recorded metadata/trails differ from pinned source bank')
 stats=inspect_v1(bytes(base),TARGET_READSET_SHA,full=full);stats.update(inspect_paint(data[off:],e,files));return {**stats,'bank_version':2,'paint_sha256':e['sha256'],'paint_descriptor_offset':directory,'paint_offset':off,'paint_manifest_sha256':eh,'paint_source_readset_file_sha256':rh}

def main():
 p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True);a=s.add_parser('extend')
 for n in ('base-bank','paint-bank','paint-manifest','paint-readset','output'):a.add_argument('--'+n,type=Path,required=True)
 a=s.add_parser('inspect');a.add_argument('bank',type=Path)
 for n in ('paint-manifest','paint-readset'):a.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args()
 if a.command=='extend':r=extend(a.base_bank,a.paint_bank,a.paint_manifest,a.paint_readset,a.output)
 else:r=inspect(read_file(a.bank,MAX_BANK),a.paint_manifest,a.paint_readset)
 print(json.dumps(r,sort_keys=True))
if __name__=='__main__':main()
