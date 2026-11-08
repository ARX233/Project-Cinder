#!/usr/bin/env python3
"""Deterministic offline APK135 owned-Python-runtime packaging (no conversion).

Only frozen, hash-pinned AAR/AO/media/profile inputs are accepted. App code comes
from an explicit reviewed .py allowlist under --repo, never an original-data root.
No Gradle, network, Python target import/execution, native load, device or original
program execution. New output only; failures retain owned partials, never delete.
"""
from __future__ import annotations
import argparse
import ast
import base64
import copy
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import unicodedata
import zipfile
import zlib

SCHEMA='wmmt-original-runtime-package-v1'
PINS={
 'aar':'0ef6423721b8a5fb32709316b33554b1fe0b66b4ae817af9c28e89699f2f91c0',
 'ao':'b730592c4e68407c281bc02c1863d3a4b12406dfa3af144b0c5c92d8e058b7a9',
 'media':'2e88baa7d461622f43a66b181a141d5c8f7f8bdb131e60940575e642f27888aa',
 'profile':'dd5ba7761175b83652ff304f40fdc20fbb93d26d2aa5cb883e914ae9ff825f20'}
MAIN_SHA='2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
EXPECTED_SOURCE_COUNT=13994
EXPECTED_OUTPUT_COUNT=1801
EXPECTED_CLASS_COUNT=33
EXPECTED_BASE_ELF_COUNT=96
EXPECTED_RUNTIME={'python':'3.13.16','numpy':'1.26.2','pillow':'11.0.0'}
MAX_INPUT_BYTES=256*1024*1024
MAX_MEMBER_BYTES=64*1024*1024
MAX_ARCHIVE_BYTES=512*1024*1024
MAX_ZIP_ENTRIES=20000
MAX_SOURCE_BYTES=8*1024*1024
MAX_APP_BYTES=32*1024*1024
HASH=re.compile(r'[0-9a-f]{64}\Z')
SHA1=re.compile(r'[0-9a-f]{40}\Z')
CONVERTER_MODULES=(
 '__init__','engine','source','archive','validation','physics_image','car_tables',
 'chara_colors','cars','wheels','maps','extras','ao','media','media_validate',
 'runtime_check','menu_support','menu_car_data','menu_components',
 'menu_scene_sprites','menu_recipe','full_menu','release_assets','player_paints','player_paint_lua','smoke')
NATIVE_MODULES=('media_ctypes','media_overlay_ctypes')
STAGE_MODULES=('igb','tex','scene','pack','lualite','pack_cars','pack_vinyl',
               'pack_lights','pack_neon','pack_mini','pack_tire_track','story_part_groups')
SOURCE_PATHS=tuple(sorted(
 ['tools/original_convert/'+n+'.py' for n in CONVERTER_MODULES]+
 ['tools/original_convert/native_backend/'+n+'.py' for n in NATIVE_MODULES]+
 ['tools/stage/'+n+'.py' for n in STAGE_MODULES]))
LICENSE_PATHS=tuple(('tools/original_convert/native_backend/licenses/'+name,'assets/original-convert/licenses/'+name) for name in ('FFmpeg-LGPL-2.1.txt','FFmpeg-LICENSE.md','OpenH264-LICENSE.txt','NDK-LLVM-NOTICE.txt','Android-cpufeatures-NOTICE.txt'))+(('tools/original_convert/native_backend/LICENSE','assets/original-convert/licenses/Converter-shim-MIT-LICENSE.txt'),)
LICENSE_PATHS += (('LICENSE','assets/original-convert/licenses/Port-source-MIT-LICENSE.txt'),)
GENERATED={'original_convert/native_backend/__init__.py':b'"""Packaged native converter bindings."""\n',
           'stage/__init__.py':b'"""Reviewed signed-asset stage algorithms."""\n'}
REQUIRED_JNI=frozenset(('libchaquopy_java.so','libcrypto_chaquopy.so','libcrypto_python.so',
 'libpython3.13.so','libpython3.so','libsqlite3_chaquopy.so','libsqlite3_python.so',
 'libssl_chaquopy.so','libssl_python.so'))
BOOTSTRAP_NATIVE=frozenset(n+'.cpython-313-aarch64-linux-android.so' for n in
 ('_bz2','_ctypes','_datetime','_lzma','_opcode','_random','_struct','binascii','math','mmap','zlib'))|{'java/chaquopy.so'}
IMYS=frozenset(('app.imy','bootstrap.imy','requirements-arm64-v8a.imy','requirements-common.imy',
                'stdlib-arm64-v8a.imy','stdlib-common.imy'))
SYSTEM_NEEDED=frozenset(('libc.so','libm.so','libdl.so','liblog.so','libandroid.so','libz.so',
 'libjnigraphics.so','libEGL.so','libGLESv2.so','libOpenSLES.so','libmediandk.so','libvulkan.so'))
NOTICE=b'''APK135 original conversion runtime: third-party notice index (not game data)\n\nThis package contains Chaquopy 17.2 / CPython 3.13, NumPy 1.26.2, Pillow 11.0.0,\nFreeType 2.15.0 and their runtime dependencies from the frozen owned-runtime AAR.\nTheir original LICENSE/LICENSES/dist-info notices remain byte-for-byte in the\nunchanged bootstrap/requirements/stdlib IMY archives. Licenses are mixed; this\npackage is NOT claimed to be entirely MIT. Consult those upstream license files.\n\nThe media converter uses FFmpeg 9.0.2 under LGPL-2.1-or-later and OpenH264 under\nits BSD license. Full media/LLVM/Android/shim license texts are included under\nassets/original-convert/licenses. Corresponding media source and build/relinking\nmaterials must accompany distribution as the maintainer's separate OSS source /\nrelinking archive. This packaging operation does not construct or verify that\narchive: the release must provide it separately. This notice and included texts\ndo not falsely assert that source/relinking obligations are already completed.\n\nOnly reviewed converter Python code and release hash/size metadata are included.\nOriginal game main, sprites, fonts, WAV/movie content, WPK/AO or runtime resource\narchives are not inputs to this packaging tool and are not bundled by it.\n'''

class PackagingError(ValueError):pass

def _need(ok,message):
 if not ok:raise PackagingError(message)
def _sha(data):return hashlib.sha256(data).hexdigest()
def _json(data):
 def unique(pairs):
  out={}
  for k,v in pairs:
   _need(k not in out,'duplicate JSON member');out[k]=v
  return out
 try:return json.loads(data.decode('utf-8','strict'),object_pairs_hook=unique,
  parse_constant=lambda x:(_ for _ in ()).throw(PackagingError('nonfinite JSON')))
 except (UnicodeError,ValueError,RecursionError) as e:raise PackagingError('invalid JSON') from e
def _canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode()
def _safe(name):
 _need(isinstance(name,str) and 0<len(name)<=4096 and name==unicodedata.normalize('NFC',name),'noncanonical path')
 _need('\\' not in name and ':' not in name and not any(unicodedata.category(c).startswith('C') for c in name),'unsafe path character')
 _need(all(p and p not in ('.','..') and p[-1] not in ' .' for p in name.split('/')),'unsafe path component')
 return name
def _chain(path):
 _need(path.is_absolute() and '..' not in path.parts,'absolute nontraversing path required')
 for p in (*reversed(path.parents),path):
  s=os.lstat(p);_need(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode),'directory chain contains symlink/non-directory')
 return path
def _read(path,limit=MAX_INPUT_BYTES):
 path=Path(path);_chain(path.parent)
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  a=os.fstat(fd);_need(stat.S_ISREG(a.st_mode) and 0<a.st_size<=limit,'input regular-file/size constraint')
  chunks=[];left=a.st_size
  while left:
   b=os.read(fd,min(left,1024*1024));_need(b,'input shortened');chunks.append(b);left-=len(b)
  _need(not os.read(fd,1),'input grew');b=os.fstat(fd)
  _need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns,b.st_ctime_ns),'input changed while reading')
  return b''.join(chunks)
 finally:os.close(fd)
def _pinned(path,key):
 data=_read(path,8*1024*1024 if key=='profile' else MAX_INPUT_BYTES)
 _need(_sha(data)==PINS[key],key+' SHA-256 pin mismatch');return data

def safe_zip(data,label):
 _need(len(data)<=MAX_INPUT_BYTES,label+' compressed budget')
 try:
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   infos=z.infolist();_need(len(infos)<=MAX_ZIP_ENTRIES,label+' entry-count budget')
   names=set();folded=set();total=0;result={};directories=set()
   for i in infos:
    _need(i.orig_filename==i.filename,label+' NUL filename')
    directory=i.is_dir();name=i.filename[:-1] if directory else i.filename;_safe(name)
    _need(name not in names and name.casefold() not in folded,label+' duplicate/case-aliased member')
    names.add(name);folded.add(name.casefold())
    mode=i.external_attr>>16;kind=stat.S_IFMT(mode)
    _need(kind in (0,stat.S_IFDIR if directory else stat.S_IFREG),label+' linked/special member')
    _need(not i.flag_bits&1,label+' encrypted member')
    _need(0<=i.file_size<=MAX_MEMBER_BYTES,label+' member byte budget');total+=i.file_size
    _need(total<=MAX_ARCHIVE_BYTES,label+' uncompressed budget')
    if directory:directories.add(name);continue
    raw=z.read(i);_need(len(raw)==i.file_size,label+' short member');result[name]=raw
   for name in names:
    prefix=name
    while '/' in prefix:
     prefix=prefix.rsplit('/',1)[0];_need(prefix not in result,label+' file/directory collision')
   return result
 except (zipfile.BadZipFile,RuntimeError,NotImplementedError,OSError) as e:raise PackagingError(label+' invalid ZIP') from e

def deterministic_zip(files):
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for name in sorted(files):
   _safe(name);i=zipfile.ZipInfo(name,(1980,1,1,0,0,0));i.create_system=3;i.external_attr=0o100644<<16;i.compress_type=zipfile.ZIP_DEFLATED
   z.writestr(i,files[name],compresslevel=9)
 return out.getvalue()

def parse_profile(data):
 _need(len(data)<=8*1024*1024 and data.endswith(b'\n') and b'\r' not in data and b'\0' not in data,'profile encoding/budget')
 try:lines=data.decode('utf-8','strict').splitlines()
 except UnicodeError as e:raise PackagingError('profile UTF-8') from e
 _need(lines[0]=='WMMT-ORIGINAL-PROFILE-1' and lines[-1]=='END','profile boundary')
 header={};src={};out={};fold_src=set();fold_out=set();last_src=last_out='';phase='header'
 for line in lines[1:-1]:
  fields=line.split('\t');tag=fields[0]
  if tag in ('profileId','readsetSha256','recipeSha256'):
   _need(phase=='header' and len(fields)==2 and tag not in header,'profile header');header[tag]=fields[1];continue
  if tag=='src':
   _need(phase!='out' and len(fields)==4,'profile source row');phase='src';_,name,size,digest=fields
   _safe(name);_need(name=='main' or name.startswith('data/'),'profile source namespace')
   _need(name>last_src and name.casefold() not in fold_src,'unsorted/aliased profile source')
   _need(size.isdecimal() and int(size)<=512*1024*1024 and HASH.fullmatch(digest),'profile source size/hash')
   src[name]={'bytes':int(size),'sha256':digest};fold_src.add(name.casefold());last_src=name
  elif tag=='out':
   _need(len(fields)==5,'profile output row');phase='out';_,name,size,digest,kind=fields;_safe(name)
   _need(name!='main' and not name.startswith('data/') and name>last_out and name.casefold() not in fold_out,'profile output namespace/order')
   _need(size.isdecimal() and int(size)<=512*1024*1024 and kind in ('fixed','ao','m4a','mp4'),'profile output size/kind')
   _need(bool(HASH.fullmatch(digest)) or (digest=='-' and kind in ('ao','m4a','mp4')),'profile output SHA')
   out[name]={'max_bytes':int(size),'sha256':None if digest=='-' else digest,'kind':kind};fold_out.add(name.casefold());last_out=name
  else:raise PackagingError('unknown profile row')
 _need(set(header)=={'profileId','readsetSha256','recipeSha256'} and HASH.fullmatch(header['readsetSha256']) and HASH.fullmatch(header['recipeSha256']),'profile pins missing')
 _need(len(src)==EXPECTED_SOURCE_COUNT and len(out)==EXPECTED_OUTPUT_COUNT,'incomplete source/output profile')
 _need(src.get('main',{}).get('sha256')==MAIN_SHA,'profile main pin')
 return header,src,out

def _metadata_release(source,profile):
 tree=ast.parse(source,filename='original_convert/release_assets.py');values={}
 for node in tree.body:
  if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('READSET_B64','RECIPE_B64','PINS'):
   try:values[node.targets[0].id]=ast.literal_eval(node.value)
   except (ValueError,TypeError,RecursionError) as e:raise PackagingError('nonliteral release metadata') from e
 _need(set(values)=={'READSET_B64','RECIPE_B64','PINS'},'release_assets metadata missing')
 header,src,out=profile;pins=values['PINS']
 _need(pins=={'profile_id':header['profileId'],'readset_sha256':header['readsetSha256'],'recipe_sha256':header['recipeSha256'],'profile_sha256':PINS['profile']},'release_assets/profile pin mismatch')
 decoded={}
 for key,var in (('readset','READSET_B64'),('recipe','RECIPE_B64')):
  _need(isinstance(values[var],str) and len(values[var])<=8*1024*1024,'release metadata compressed budget')
  try:
   decoder=zlib.decompressobj();raw=decoder.decompress(base64.b64decode(values[var],validate=True),8*1024*1024+1)
   _need(len(raw)<=8*1024*1024 and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,'release metadata expansion budget/trailing data')
  except (ValueError,zlib.error) as e:raise PackagingError('release metadata encoding') from e
  _need(_sha(raw)==pins[key+'_sha256'],'release decoded pin');decoded[key]=_json(raw)
 readset=decoded['readset'];recipe=decoded['recipe']
 _need(isinstance(readset,dict) and set(readset)=={'schema','main_sha256','files'} and readset['schema']=='wmmt-original-readset-v1' and readset['main_sha256']==MAIN_SHA,'release readset schema')
 _need(isinstance(readset['files'],list) and len(readset['files'])==EXPECTED_SOURCE_COUNT,'release source inventory incomplete')
 _need(readset['files']==[{'path':n,**v} for n,v in src.items()],'release source rows vs profile mismatch')
 _need(isinstance(recipe,dict) and set(recipe)=={'schema','profile_id','runtime','native','raw','wheels','cars','extras','media','outputs','route_arrow_order','player_paints','player_paints_plan_sha256','smoke','smoke_plan_sha256'} and recipe['schema']=='wmmt-original-race-recipe-v1' and recipe['profile_id']==header['profileId'],'release recipe incomplete')
 _need(recipe['native']=={'liboa_native.so':PINS['ao'],'liboc_media_overlay.so':PINS['media']},'release native pins mismatch')
 _need(recipe['runtime']==EXPECTED_RUNTIME,'release runtime version mismatch')
 _need(isinstance(recipe['outputs'],list) and len(recipe['outputs'])==EXPECTED_OUTPUT_COUNT,'release outputs incomplete')
 observed={}
 for row in recipe['outputs']:
  _need(isinstance(row,dict) and {'path','max_bytes','sha256','kind'}<=set(row)<= {'path','max_bytes','sha256','kind','ao_layout'},'release output metadata shape')
  _need(row['path'] not in observed,'duplicate release output');observed[row['path']]={k:row[k] for k in ('max_bytes','sha256','kind')}
 _need(observed==out,'release outputs vs profile mismatch')
 _need(recipe['route_arrow_order'] is True,'release original route image order missing')
 paint=recipe['player_paints'];paint_raw=(json.dumps(paint,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
 _need(_sha(paint_raw)==recipe['player_paints_plan_sha256'],'release player paint plan pin mismatch')
 _need(isinstance(paint,dict) and set(paint)=={'schema','bank_bytes','bank_sha256','readset_sha256','main_sha256','records','source_files','absences'} and paint['schema']=='WPPAINT1-plan-v1' and paint['main_sha256']==MAIN_SHA,'release player paint schema')
 _need(len(paint['records'])==6080 and len(paint['source_files'])==1000,'release player paint inventory')
 for row in paint['source_files']:
  _need(src.get(row['path'])=={'bytes':row['bytes'],'sha256':row['sha256']},'release player paint dependency closure')
 _need(not set(paint['absences'])&set(src),'release player paint absence changed')
 _need(out.get('player-body-paints.bin')=={'max_bytes':paint['bank_bytes'],'sha256':paint['bank_sha256'],'kind':'fixed'},'release player output closure')
 smoke=recipe['smoke'];smoke_raw=_canonical(smoke)
 _need(_sha(smoke_raw)==recipe['smoke_plan_sha256']=='0681855bb9ebb49e5a0ce55662cfcfb0d9e9b1f8695a64422dd52e1bc8c62e96','release smoke plan pin')
 for row in smoke['source_files']:
  _need(src.get(row['path'])=={'bytes':row['bytes'],'sha256':row['sha256']},'release smoke source closure')
 _need(out.get('tiresmoke.bin')=={'max_bytes':262160,'sha256':'5a0a2d31d64583fc2dd7a8cda2bc81f9bdf80ae07cdad3981d0409ea11748e92','kind':'fixed'},'release smoke MAIN output')
 _need(recipe['cars'].get('story_assembly') is True,'release story assembly geometry flag')
 height=recipe['cars']['story_height']
 _need(_sha(_canonical(height))=='1fcd89261ea91e8d383cb90a57f840019b245384e4506ba12ac0ef7b0bbbaba7','release height plan pin')
 for row in height['source_files']:
  _need(src.get(row['path'])=={'bytes':row['bytes'],'sha256':row['sha256']},'release height source closure')
 return {'profile_id':pins['profile_id'],'readset_sha256':pins['readset_sha256'],'recipe_sha256':pins['recipe_sha256'],'sources':len(src),'outputs':len(out)}

def source_plan(repo):
 repo=_chain(Path(repo));files={};inventory=[];trees={};source_bytes=0;ast_nodes=0
 for relative in SOURCE_PATHS:
  raw=_read(repo/relative,MAX_SOURCE_BYTES);source_bytes+=len(raw)
  _need(source_bytes<=MAX_APP_BYTES,'app source total budget')
  try:tree=ast.parse(raw,filename=relative,feature_version=(3,13))
  except (SyntaxError,ValueError,UnicodeError,RecursionError) as e:raise PackagingError('invalid reviewed Python 3.13 source '+relative) from e
  nodes=sum(1 for node in ast.walk(tree));ast_nodes+=nodes
  _need(nodes<=200000 and ast_nodes<=500000,'reviewed source AST node budget')
  dest=relative.removeprefix('tools/');_need(dest.endswith('.py'),'source allowlist suffix');files[dest]=raw;trees[dest]=tree
  inventory.append({'source':relative,'app_path':dest,'bytes':len(raw),'sha256':_sha(raw)})
 known_stage=set(STAGE_MODULES);known_converter=set(CONVERTER_MODULES)-{'__init__'}
 external=set(sys.stdlib_module_names)|{'numpy','PIL','__future__'};closure=[]
 def check(module,current,kind):
  root=module.split('.')[0]
  if module=='stage':_need('stage/__init__.py' in GENERATED,'signed stage package is missing')
  elif module.startswith('original_convert.'):
   tail=module.removeprefix('original_convert.')
   target='original_convert/'+tail.replace('.','/')+'.py'
   if target not in files and target not in GENERATED:target='original_convert/'+tail.replace('.','/')+'/__init__.py'
   _need(target in files or target in GENERATED,'missing/unreviewed local import '+module)
  elif root in known_stage:_need(root+'.py' in {Path(p).name for p in files if p.startswith('stage/')},'missing stage helper '+root)
  elif root=='media_ctypes' and current=='original_convert/native_backend/media_overlay_ctypes.py':pass
  else:_need(root in external,'unreviewed/unknown imported module '+module+' in '+current)
  closure.append({'source':current,'module':module,'kind':kind})
 for current,tree in trees.items():
  package=current.rsplit('/',1)[0].split('/')
  for node in ast.walk(tree):
   if isinstance(node,ast.Import):
    for alias in node.names:check(alias.name,current,'import')
   elif isinstance(node,ast.ImportFrom):
    if node.level:
     _need(current.startswith('original_convert/'),'unexpected relative stage import')
     base=package[:len(package)-node.level+1];prefix='.'.join(base+([node.module] if node.module else []))
     if node.module:check(prefix,current,'relative-from')
     else:
      for alias in node.names:check(prefix+'.'+alias.name,current,'relative-module')
    elif node.module:check(node.module,current,'from')
   elif isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='import_module':
    if node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):check(node.args[0].value,current,'literal-import_module')
    else:_need(node.args and isinstance(node.args[0],ast.Name) and node.args[0].id=='__name__','unresolved dynamic import_module')
 for dest,raw in GENERATED.items():files[dest]=raw;inventory.append({'source':'generated-reviewed-empty-package','app_path':dest,'bytes':len(raw),'sha256':_sha(raw)})
 _need(sum(map(len,files.values()))<=MAX_APP_BYTES,'app source total budget')
 return files,sorted(inventory,key=lambda x:x['app_path']),closure

def license_plan(repo):
 files={};inventory=[]
 for source,destination in LICENSE_PATHS:
  raw=_read(Path(repo)/source,2*1024*1024)
  try:text=raw.decode('utf-8','strict')
  except UnicodeError as e:raise PackagingError('public license is not UTF-8 text') from e
  _need(text.strip() and '\0' not in text,'invalid public license text')
  files[destination]=raw;inventory.append({'source':source,'path':destination,'bytes':len(raw),'sha256':_sha(raw),'verbatim':True})
 return files,inventory

def elf_metadata(data,label):
 _need(len(data)>=64 and data[:7]==b'\x7fELF\x02\x01\x01',label+' not ELF64 LE')
 e=struct.unpack_from('<HHIQQQIHHHHHH',data,16);_need(e[0]==3 and e[1]==183,label+' not AArch64 shared ELF')
 off,ents,count=e[4],e[8],e[9];_need(ents==56 and 0<count<=512 and off+ents*count<=len(data),label+' bad program headers')
 loads=[];dynamic=[]
 for n in range(count):
  typ,flags,pos,va,pa,fs,ms,align=struct.unpack_from('<IIQQQQQQ',data,off+56*n)
  _need(pos<=len(data) and fs<=len(data)-pos and fs<=ms,label+' segment range')
  if typ==1:
   _need(align>=16384 and align&(align-1)==0 and (va-pos)%align==0,label+' PT_LOAD not 16KiB compatible');loads.append((pos,va,fs,align))
  if typ==2:dynamic.append((pos,fs))
 _need(loads,label+' no LOAD segments');needed=[];soname=None
 for pos,size in dynamic:
  tags={};terminated=False
  for at in range(pos,pos+size-15,16):
   tag,value=struct.unpack_from('<qQ',data,at)
   if tag==0:terminated=True;break
   tags.setdefault(tag,[]).append(value)
  _need(terminated,label+' dynamic table unterminated')
  if 1 not in tags and 14 not in tags:continue
  _need(len(tags.get(5,[]))==len(tags.get(10,[]))==1,label+' missing/ambiguous dynamic strings')
  va=tags[5][0];sz=tags[10][0];candidates=[p+(va-v) for p,v,s,a in loads if v<=va and va-v+sz<=s]
  _need(len(candidates)==1 and sz<=MAX_MEMBER_BYTES,label+' dynamic string range');raw=data[candidates[0]:candidates[0]+sz]
  def string(v):
   _need(v<len(raw),label+' dynamic name offset');end=raw.find(b'\0',v);_need(end>=v,label+' dynamic name terminator')
   try:name=raw[v:end].decode('ascii')
   except UnicodeError as e:raise PackagingError(label+' non-ASCII native name') from e
   _need(re.fullmatch(r'[A-Za-z0-9_.+\-]+',name),label+' unsafe native dependency');return name
  needed.extend(string(v) for v in tags.get(1,[]))
  if 14 in tags:_need(len(tags[14])==1,label+' ambiguous SONAME');soname=string(tags[14][0])
 return {'path':label,'bytes':len(data),'sha256':_sha(data),'LOAD_alignments':[a for p,v,s,a in loads],'needed':needed,'soname':soname}

def deduplicate_jars(raw_jars):
 seen={};outputs={};classes=[];removed=[]
 for outname,raw in raw_jars:
  members=safe_zip(raw,outname);kept={}
  for path,data in members.items():
   if path.endswith('.class'):
    _need(data[:4]==b'\xca\xfe\xba\xbe','bad Java class header')
    if path in seen:
     _need(seen[path]==_sha(data),'conflicting duplicate Java class '+path);removed.append({'jar':outname,'class':path});continue
    seen[path]=_sha(data);classes.append(path)
   _need(not (path.startswith('META-INF/') and path.upper().endswith(('.SF','.RSA','.DSA','.EC'))),'signed JAR cannot be rewritten')
   kept[path]=data
  outputs[outname]=deterministic_zip(kept)
 _need(len(classes)==EXPECTED_CLASS_COUNT,'unexpected deduplicated Java class count')
 return outputs,{'unique_classes':len(classes),'classes':sorted(classes),'removed_identical_duplicates':removed}

def _require_apfs(parent):
 # Darwin LP64 statfs layout from the public SDK sys/mount.h. Only the trusted
 # system filesystem API is called; no input native library is ever loaded.
 _need(sys.platform=='darwin' and struct.calcsize('P')==8,'current kit requires 64-bit macOS/APFS output')
 class StatFS(ctypes.Structure):
  _fields_=[('bsize',ctypes.c_uint32),('iosize',ctypes.c_int32)]+[(n,ctypes.c_uint64) for n in ('blocks','bfree','bavail','files','ffree')]+[('fsid',ctypes.c_int32*2),('owner',ctypes.c_uint32),('type',ctypes.c_uint32),('flags',ctypes.c_uint32),('subtype',ctypes.c_uint32),('fstypename',ctypes.c_char*16),('mntonname',ctypes.c_char*1024),('mntfromname',ctypes.c_char*1024),('flags_ext',ctypes.c_uint32),('reserved',ctypes.c_uint32*7)]
 _need(ctypes.sizeof(StatFS)==2168,'unsupported Darwin statfs ABI')
 libc=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True);fn=libc.statfs
 fn.argtypes=[ctypes.c_char_p,ctypes.POINTER(StatFS)];fn.restype=ctypes.c_int
 value=StatFS();_need(fn(os.fsencode(parent),ctypes.byref(value))==0,'statfs failed')
 _need(bytes(value.fstypename).split(b'\0',1)[0]==b'apfs','output filesystem must be APFS')

def _write_new(root,name,data):
 _safe(name);parts=name.split('/');fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
 try:
  for part in parts[:-1]:
   try:os.mkdir(part,0o700,dir_fd=fd)
   except FileExistsError:pass
   child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=child
  out=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
  try:
   view=memoryview(data)
   while view:n=os.write(out,view);_need(n>0,'short output write');view=view[n:]
  finally:os.close(out)
 finally:os.close(fd)

def build_runtime(*,aar,ao_lib,media_lib,profile,repo,out):
 """Return packaging summary; all package bytes deterministic, output never reused."""
 out=Path(out);_need(out.is_absolute() and '..' not in out.parts,'--out must be absolute')
 _need(not os.path.lexists(out),'--out already exists (no overwrite)');_chain(out.parent);_require_apfs(out.parent)
 inputs={'aar':_pinned(aar,'aar'),'ao':_pinned(ao_lib,'ao'),'media':_pinned(media_lib,'media'),'profile':_pinned(profile,'profile')}
 profile_info=parse_profile(inputs['profile']);sources,source_inventory,closure=source_plan(Path(repo))
 release=_metadata_release(sources['original_convert/release_assets.py'],profile_info)
 public_licenses,public_license_inventory=license_plan(repo)
 outer=safe_zip(inputs['aar'],'frozen AAR');assets={};jars=[];native=[];license_inventory=[]
 allowed_meta={'R.txt','AndroidManifest.xml','proguard.txt','META-INF/com/android/build/gradle/aar-metadata.properties'}
 runtime_assets=IMYS|{'build.json','cacert.pem'}|{'bootstrap-native/arm64-v8a/'+x for x in BOOTSTRAP_NATIVE}
 jni=set()
 for name,data in outer.items():
  if name.startswith('assets/chaquopy/'):
   relative=name.removeprefix('assets/chaquopy/');_need(relative in runtime_assets,'unknown AAR runtime asset/native path '+name);assets[name]=data
  elif name.startswith('jni/arm64-v8a/'):
   base=name.removeprefix('jni/arm64-v8a/');_need(base in REQUIRED_JNI,'unknown AAR native path '+name);jni.add(base);assets['lib/arm64-v8a/'+base]=data
  elif name=='classes.jar':jars.append(('jars/runtime-classes.jar',data))
  elif name=='libs/chaquopy_java-17.2.0.jar':jars.append(('jars/chaquopy-java-17.2.0.jar',data))
  else:_need(name in allowed_meta,'unknown AAR member '+name)
 _need(jni==REQUIRED_JNI and len(jars)==2 and set(n.removeprefix('assets/chaquopy/') for n in assets if n.startswith('assets/chaquopy/'))==runtime_assets,'incomplete frozen runtime AAR')
 build=_json(assets['assets/chaquopy/build.json']);old_build=copy.deepcopy(build)
 _need(isinstance(build,dict) and build.get('python_version')=='3.13' and isinstance(build.get('assets'),dict) and isinstance(build.get('extract_packages'),list),'unsupported Chaquopy build schema')
 expected={n.removeprefix('assets/chaquopy/'):d for n,d in assets.items() if n.startswith('assets/chaquopy/') and not n.endswith('/build.json')}
 _need(set(build['assets'])==set(expected),'Chaquopy asset inventory differs from build.json')
 for name,data in expected.items():_need(SHA1.fullmatch(build['assets'][name]) and hashlib.sha1(data).hexdigest()==build['assets'][name],'Chaquopy source asset SHA1 mismatch '+name)
 # Validate all frozen archives before replacing app.imy. Never copy kit_smoke.
 for name in sorted(IMYS):
  nested=safe_zip(assets['assets/chaquopy/'+name],name)
  for path,data in nested.items():
   lower=path.lower()
   if any(x in lower for x in ('license','licence','copying','notice')):license_inventory.append({'archive':name,'path':path,'bytes':len(data),'sha256':_sha(data)})
   native_name=bool(re.fullmatch(r'[A-Za-z0-9_.+\-]+\.so(?:\.[0-9]+)*',Path(path).name))
   if data.startswith(b'\x7fELF') or native_name:
    _need(name!='app.imy' and native_name,'unexpected native path in IMY');native.append(elf_metadata(data,'assets/chaquopy/'+name+'!'+path))
 for path,data in assets.items():
  if data.startswith(b'\x7fELF') or path.endswith('.so'):native.append(elf_metadata(data,path))
 _need(len(native)==EXPECTED_BASE_ELF_COUNT,'unexpected frozen AAR ELF inventory count')
 _need(license_inventory,'missing frozen runtime license metadata')
 app=deterministic_zip(sources);_need(len(app)<=MAX_APP_BYTES,'app ZIP budget')
 assets['assets/chaquopy/app.imy']=app;build['assets']['app.imy']=hashlib.sha1(app).hexdigest();build['extract_packages']=['original_convert','stage']
 preserved=copy.deepcopy(build);preserved['assets']['app.imy']=old_build['assets']['app.imy'];preserved['extract_packages']=old_build['extract_packages']
 _need(preserved==old_build,'unexpected build.json change')
 assets['assets/chaquopy/build.json']=(json.dumps(build,indent=4,sort_keys=True)+'\n').encode()
 for key,name in (('ao','liboa_native.so'),('media','liboc_media_overlay.so')):
  path='lib/arm64-v8a/'+name;_need(path not in assets,'native name collision');assets[path]=inputs[key];native.append(elf_metadata(inputs[key],path))
 available={Path(n['path'].split('!',1)[-1]).name for n in native}|{n['soname'] for n in native if n['soname']}
 unresolved=[{'path':n['path'],'needed':v} for n in native for v in n['needed'] if v not in available and v not in SYSTEM_NEEDED]
 _need(not unresolved,'unresolved native NEEDED '+str(unresolved[:4]))
 jar_outputs,class_info=deduplicate_jars(jars)
 assets['assets/original-convert/profile.tsv']=inputs['profile'];assets['assets/original-convert/NOTICE.txt']=NOTICE
 assets.update(public_licenses)
 allowlist={'schema':SCHEMA,'files':[{'path':p,'bytes':len(d),'sha256':_sha(d)} for p,d in sorted(assets.items())]}
 source_proof={'schema':'wmmt-original-runtime-source-inventory-v1','sources':source_inventory,'public_license_sources':public_license_inventory,'import_closure':closure,'packaged_app_members':sorted(sources),'release':release,'target_sources_executed':False,'original_data_inputs':False}
 native_proof={'schema':'wmmt-original-runtime-native-inventory-v1','ELFs':native,'count':len(native),'unresolved_needed':unresolved,'static_closure_only':True,'android_execution_verified':False}
 summary={'schema':'wmmt-original-runtime-build-summary-v1','out':str(out),'profile_sha256':PINS['profile'],'input_pins':PINS.copy(),'app_imy_sha256':_sha(app),'app_imy_sha1':hashlib.sha1(app).hexdigest(),'app_source_count':len(sources),'java_unique_classes':class_info['unique_classes'],'java_classpath':[str(out/n) for n in sorted(jar_outputs)],'native_ELF_count':len(native),'public_license_files':len(public_license_inventory),'source_relinking_archive_built':False,'allowlist':str(out/'packaging-allowlist.json'),'allowlist_sha256':_sha(_canonical(allowlist)),'extract_packages':['original_convert','stage'],'stage_extraction_note':'Parent must import the signed top-level stage package before path/is_file-based helper checks; extract_packages materializes Python on top-level package import.','runtime_code_executed':False,'original_code_executed':False,'android_execution_verified':False,'activated':False}
 summary['java_cp']=os.pathsep.join(summary['java_classpath'])
 # No output is created until all inputs, source closure, profiles, ZIPs/classes,
 # ELF alignment and static NEEDED closure have passed. Never delete on failure.
 out.mkdir(mode=0o700)
 for name,data in sorted({**assets,**jar_outputs}.items()):_write_new(out,name,data)
 proofs={'packaging-allowlist.json':allowlist,'source-inventory.json':source_proof,'proof/native-inventory.json':native_proof,'proof/java-classes.json':class_info,'proof/license-inventory.json':{'retained_runtime_notices':license_inventory,'runtime_IMY_bytes_preserved_except_app':True,'notice_is_not_full_media_license_compliance':True,'public_native_licenses':public_license_inventory,'separate_OSS_source_relinking_archive_required':True},'proof/build.json-delta.json':{'changes':['assets.app.imy SHA1','extract_packages'],'before':old_build,'after':build},'summary.json':summary}
 for name,value in proofs.items():_write_new(out,name,_canonical(value))
 return summary

def main(argv=None):
 ap=argparse.ArgumentParser(description=__doc__)
 for name in ('aar','ao-lib','media-lib','profile','repo','out'):ap.add_argument('--'+name,required=True,type=Path)
 a=ap.parse_args(argv)
 try:result=build_runtime(aar=a.aar,ao_lib=a.ao_lib,media_lib=a.media_lib,profile=a.profile,repo=a.repo,out=a.out)
 except (PackagingError,OSError) as e:print('runtime packaging rejected: '+str(e),file=sys.stderr);return 2
 print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
