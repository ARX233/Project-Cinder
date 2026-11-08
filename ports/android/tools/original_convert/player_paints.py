"""APK-pinned WPPAINT1 conversion into a fresh OwnedOutput MAIN resource.
No CLI authority, external path, Original executable/Lua execution or in-place
upgrade. The caller obtains plan bytes and expected plan SHA from its approved
release recipe, not from a runtime file or user receipt.
"""
from dataclasses import dataclass, field
import hashlib
import io
import json
import struct
import zlib
from PIL import Image
from .source import (VerifiedSnapshot, FileTreeSource, OwnedOutput, SourceEntry,
                     OriginalInputError, MAIN_SHA256, check_cancel, source_path,
                     _unique_object)
from .player_paint_lua import LuaData

_DEST='player-body-paints.bin'
_TOKEN=object()
_BODIES=('normal','aero_a','aero_b','aero_c')
def _need(ok,message):
 if not ok:raise OriginalInputError(message)
def _canon(v):return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()+b'\n'
@dataclass(frozen=True)
class PlayerPaintPlan:
 data: bytes
 sha256: str
 _seal: object=field(repr=False,compare=False)

def parse_plan(data,*,expected_sha256):
 _need(type(data) is bytes and 1<=len(data)<=5*1024*1024 and hashlib.sha256(data).hexdigest()==expected_sha256,'Player paint plan is not APK-pinned')
 try:v=json.loads(data.decode('utf8','strict'),object_pairs_hook=_unique_object,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
 except (ValueError,UnicodeError,RecursionError) as e:raise OriginalInputError('Invalid player paint plan') from e
 _need(_canon(v)==data and set(v)=={'schema','bank_bytes','bank_sha256','readset_sha256','main_sha256','records','source_files','absences'} and v['schema']=='WPPAINT1-plan-v1' and v['main_sha256']==MAIN_SHA256,'Unsupported player paint plan')
 _need(type(v['bank_bytes']) is int and 128<=v['bank_bytes']<=128*1024*1024 and isinstance(v['records'],list) and len(v['records'])==6080 and isinstance(v['source_files'],list) and len(v['source_files'])==1000,'Player paint profile bounds')
 for field in ('bank_sha256','readset_sha256'):
  _need(type(v[field]) is str and len(v[field])==64 and all(c in '0123456789abcdef' for c in v[field]),'Invalid paint profile hash')
 previous=''
 for r in v['source_files']:
  _need(set(r)=={'path','bytes','sha256'},'Invalid paint dependency')
  source_path(r['path']);_need(r['path']>previous and type(r['bytes']) is int and 0<r['bytes']<=128*1024*1024,'Paint dependency order/size');previous=r['path']
 _need(v['absences']==['data/car/gem_964_38RS/normal/color/38rs_body02_spec.tga'],'Unreviewed missing original paint source')
 return PlayerPaintPlan(data,expected_sha256,_TOKEN)

def convert(snapshot,output,plan,*,cancel=None,progress=None):
 _need(type(snapshot) is VerifiedSnapshot and type(output) is OwnedOutput and type(plan) is PlayerPaintPlan and plan._seal is _TOKEN and hashlib.sha256(plan.data).hexdigest()==plan.sha256,'Paint conversion requires verified snapshot/owned output/pinned plan')
 with FileTreeSource(snapshot.root,snapshot.readset) as reader:
  return _convert(snapshot,output,plan,reader,cancel=cancel,progress=progress)

def _convert(snapshot,output,plan,reader,*,cancel=None,progress=None):
 v=json.loads(plan.data)
 # Verify complete source closure BEFORE image decoding. Plan/source SHA values
 # were approved in the APK recipe; they are never learned from these files.
 for n,row in enumerate(v['source_files']):
  check_cancel(cancel);e=snapshot.readset.files.get(row['path'])
  _need(e is not None and e.size==row['bytes'] and e.sha256==row['sha256'],'Paint dependency not in approved snapshot: '+row['path'])
  for _ in reader.chunks(row['path'],cancel=cancel):pass
  if progress:progress('player-paint-verify',n+1,len(v['source_files']))
 # Explicit approved absence is retained; do not adopt newly supplied source or
 # infer a fallback. These keys stay unavailable in this profile.
 for name in v['absences']:
  _need(name not in snapshot.readset.files and not (snapshot.root/name).exists(),'Reviewed player paint absence changed')
 rows=v['records'];records=[];seen={};unique=[];offset=128+320*len(rows);cars={};last=(-1,-1,-1,-1)
 for r in rows:
  check_cancel(cancel)
  pack,color,aero,page=(r[k] for k in ('pack','custom_color','aero','page'))
  _need(all(type(k) is int for k in (pack,color,aero,page)) and 0<=pack<55 and pack not in (0,25,54) and 1<=color<=10 and 0<=aero<=3 and 1<=page<=3 and (pack,color,aero,page)>last,'Invalid/unsorted player key');last=(pack,color,aero,page)
  lua=r['lua_path'];source_path(lua);source_path(r['source_path'])
  if lua not in cars:
   raw=reader.read(lua,max_bytes=1024*1024,cancel=cancel)
   _need(hashlib.sha256(raw).hexdigest()==r['lua_sha256'],'Player Lua pin')
   try:cars[lua]=LuaData(raw).parse()
   except (ValueError,IndexError,RecursionError,UnicodeError) as e:raise OriginalInputError('Unsupported data-only player Lua') from e
  car=cars[lua];body=_BODIES[aero]
  base=car['BaseTexture'].get(body) or car['BaseTexture']['normal'];custom=car['BodyCustomColorTexture'].get(body) or car['BodyCustomColorTexture']['normal']
  _need(car['BodyIGB'].get(body) and base['page'+str(page)].rsplit('/',1)[-1].rsplit('.',1)[0]==r['material'] and custom[color-1]['page'+str(page)]==r['source_path'],'Player Lua/material plan disagreement')
  _need(1<=r['width']<=2048 and 1<=r['height']<=2048 and r['raw_size']==r['width']*r['height']*4 and 0<r['compressed_size']<=r['raw_size']+65536,'Player image bounds')
  digest=r['rgba_sha256']
  if digest not in seen:seen[digest]=offset;unique.append(r);offset+=r['compressed_size']
  _need(r['compressed_offset']==seen[digest],'Paint dedup offset disagreement')
  rec=bytearray(320);struct.pack_into('<HBBBBHHHIIIQ',rec,0,pack,color,aero,page,r['alpha_present'],r['width'],r['height'],0,r['raw_size'],r['compressed_size'],r['crc32'],seen[digest])
  for at,field in ((32,'rgba_sha256'),(64,'source_sha256'),(96,'lua_sha256')):rec[at:at+32]=bytes.fromhex(r[field])
  for at,field,cap in ((128,'material',48),(176,'source_path',128)):
   b=r[field].encode('ascii');_need(0<len(b)<cap,'Paint string bound');rec[at:at+len(b)]=b
  records.append(rec)
 _need(offset==v['bank_bytes'],'Paint final byte count')
 header=bytearray(128);struct.pack_into('<8sIIIIIIQQQ',header,0,b'WPPAINT1',1,128,320,len(rows),2048,1,128,128+320*len(rows),offset)
 header[56:88]=bytes.fromhex(v['readset_sha256']);header[88:120]=bytes.fromhex(MAIN_SHA256);struct.pack_into('<II',header,120,1,1)
 target=output.target(_DEST);h=hashlib.sha256();written=0
 with target.open('xb') as out:
  def write(b):
   nonlocal written
   check_cancel(cancel);out.write(b);h.update(b);written+=len(b)
  write(header)
  for rec in records:write(rec)
  # One original selected image + compressed result at a time. Never preload the
  # complete 116MB bank or the 9.6GB logical palette. No resize/quantization.
  for n,r in enumerate(unique):
   source=reader.read(r['source_path'],max_bytes=32*1024*1024,cancel=cancel)
   _need(hashlib.sha256(source).hexdigest()==r['source_sha256'],'Player source image hash')
   with Image.open(io.BytesIO(source)) as im:
    _need(im.format in ('TGA','PNG','DDS') and im.size==(r['width'],r['height']),'Player original image shape')
    raw=im.convert('RGBA').transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
   _need(hashlib.sha256(raw).hexdigest()==r['rgba_sha256'] and zlib.crc32(raw)==r['crc32'] and int(min(raw[3::4])<255)==r['alpha_present'],'Player original RGBA disagreement')
   compressed=zlib.compress(raw,9);_need(len(compressed)==r['compressed_size'],'Player paint compression profile mismatch');write(compressed)
   if progress:progress('player-paint-convert',n+1,len(unique))
  out.flush()
 _need(written==v['bank_bytes'] and h.hexdigest()==v['bank_sha256'],'Player output differs from APK-pinned bank; output remains inactive')
 entry=SourceEntry(written,h.hexdigest());output.files[_DEST]=entry;return entry
