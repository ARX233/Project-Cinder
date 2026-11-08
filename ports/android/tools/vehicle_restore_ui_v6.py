#!/usr/bin/env python3
"""Explicit original repaint UI v6. No ELF/Lua execution, no new capability.

Reads a pinned v5 bank+manifest+index, the pinned current compact menu and the
user's original source tree; appends original 11-colour ANMs/swatches/font0 text.
Never modifies input files or the v5 approval profile. Output is observational.
"""
from pathlib import Path
import argparse, hashlib, importlib, json, math, os, re, struct, sys, zlib
SCHEMA='project-cinder-arcade-ui-v6'
INDEX_MAGIC=b'WMMT-ARCADE-UI-6\n'
INDEX_PATH='assets/arcade-ui-v6-index.tsv'
BANK_PATH='assets/ghost-ui.bin'
BASE_MANIFEST_SHA='70654b0e962833ecd279b1c7c1b3cae9845908677e990133d97795d04d2ed6df'
BASE_BANK_SHA='2154d108da43d677c1fbb4b018508638cbc7e7021a9e03623b9194ff775c12e1'
MAIN_SHA='2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
MENU_SHA='c5eff443269e1835a6bffa834e1000cb24516a6a89e8d4c1a2c0874dd462a99c'
TEXT_BASE=116000
ANIMS=(('menu_g_carsel_col_11',1704552,'f9b8366f1132ec6682533e2b72b10cce22514b708d5b8141d54df45259e9682e'),('menu_g_carsel_col_11_arrow',355328,'6dc38af098d98431b2d4aeb0cd13d8f3ff79b1e2c9cf5d82509eaa4e493c4276'))
# Original Target result console's ANMs 0xca and 0xcb.
GHOST_RESULT_ANIMS=(
 ('menu_g_finish_tg_bar',79016,'3815793f092e353dddd616be5ed222af894887e1301efbd7293bcc10541318cf'),
 ('menu_g_finish_tg_moji',22728,'5e0f800b196a188c7fd05c7aac8c76e19615294870296bd0f21b1dcf39812093'),
)
GHOST_RESULT_WIRE=(
 (57472,'8a4d72be0109b59de963b7e4cb97ec0ce2b323246103a2db854c0577045f8c8a'),
 (16700,'f70ec97130f97acb174f7ebb3b0492d39d60b60916dd08b130b35f18c3f94ed6'),
)
GHOST_RESULT_SPRITES=(4713,4714,4715,4716,6216,6568,7497,7689)
GHOST_RESULT_RGBA=180736
RECORD=struct.Struct('<iH6f4h4h')
def need(ok,msg):
 if not ok:raise ValueError(msg)
def sha(b):return hashlib.sha256(b).hexdigest()
def jb(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def pairs(rows):
 d={}
 for k,v in rows:need(k not in d,'duplicate JSON key');d[k]=v
 return d
def read(path,limit):
 p=Path(path);need(p.is_file() and not p.is_symlink(),'regular non-symlink input required');st=p.stat();need(0<st.st_size<=limit,'input size budget');b=p.read_bytes();need(len(b)==st.st_size and (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==(p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns),'input changed');return b
def spec(path,b):return {'path':path,'bytes':len(b),'sha256':sha(b)}
def menu_inventory(b):
 need(len(b)==324123636 and sha(b)==MENU_SHA and b[:4]==b'WMN3','current c5 menu pin')
 n=struct.unpack_from('<I',b,4)[0];need(n==10611,'current sprite count');at=8;ids=set()
 for _ in range(n):
  sid,w,h,z=struct.unpack_from('<iHHI',b,at);need(sid not in ids and 0<w<=2048 and 0<h<=2048,'main sprite');ids.add(sid);at+=12+(z or w*h*4);need(at<=len(b),'main sprite extent')
 na=struct.unpack_from('<I',b,at)[0];need(na==308,'current animation count');at+=4;anims=[]
 for _ in range(na):
  name,nf,nr=struct.unpack_from('<48sII',b,at);need(0<nf<=20000 and nr<=250000,'main animation bounds');anims.append(name.split(b'\0')[0].decode('ascii'));at+=56+8*nf+44*nr;need(at<=len(b),'main animation extent')
 need(at==len(b) and len(set(anims))==na,'main canonical extent');return ids,anims

def palette(s,mc,ct,car_root):
 e=s.elf;mc._decode_models(e)
 pro={0x88DC0C8:b'\x55',0x88DC0E7:b'\x89\xe5',0x88DC0FD:b'\x8b\x45\x08',0x88DC132:b'\x3d\xf6\x00\x00\x00'};at=mc.MODEL_FUNCTION[0];common=[]
 while at<0x88DC1CD:
  if at in pro:at+=len(pro[at])
  else:common.append(mc._store_record(e,at,mc.MODEL_BASE,mc.MODEL_LIMIT));at+=10
 models=[]
 for target in struct.unpack('<247I',e.read(0x940ed98,988)):
  f=dict(common+mc._constant_records(e,target,function_range=mc.MODEL_FUNCTION,store_range=(mc.MODEL_BASE,mc.MODEL_LIMIT),terminal=0x88DC316));models.append([f.get(mc.MODEL_BASE+4*i) for i in range(35)])
 db=mc.from_elf(e,car_root);d=ct._decode_main(e);rows=[]
 for mk,maker in enumerate(db['makers']):
  for cr,car in enumerate(maker['cars']):
   for co,c in enumerate(car['colors']):
    raw=c['model'];cid=ct._model_car(d['model_ranges'],raw,False)
    pm=120 if 120<=raw<=122 else 118 if 118<=raw<=119 else next(r[1] for r in d['model_ranges'] if r[0]==cid)
    v=models[pm];names=[s.cstr(x) if x else '' for x in v[23:33]]
    rows.append({'maker':mk,'car':cr,'factory_color':co,'raw_model':raw,'pack':db['pack_order'].index(c['folder']),'paint':c['paint'],'type':c['type'],'palette_model':pm,'swatches':v[12:22],'names':names,'folder':c['folder']})
 need(len(rows)==247 and len({r['raw_model'] for r in rows})==247,'all selectable raw models uniquely keyed')
 return db,rows

def header(rows,name_ids):
 h=['/* PRIVATE: original main SHA256 '+MAIN_SHA+'. Generated, never hand edit. */','#ifndef BODY_COLOR_ASSETS_PRIVATE_H','#define BODY_COLOR_ASSETS_PRIVATE_H','typedef struct { short maker,car,factory,raw_model,pack,paint,type; int swatch[10],name[10]; } body_color_row;','static const body_color_row BODY_COLOR_ROWS[] = {']
 for r in rows:
  h.append('  { %d,%d,%d,%d,%d,%d,%d, {%s}, {%s} },' % (*[r[k] for k in ('maker','car','factory_color','raw_model','pack','paint','type')],','.join(str(v or 0) for v in r['swatches']),','.join(str(name_ids.get(n,0)) for n in r['names'])))
 h+=['};','#define BODY_COLOR_ROWS_COUNT 247','#endif',''];return '\n'.join(h).encode()

def validate_expected(v):
 need(type(v) is dict and set(v)=={'schema','category','profile_version','format','format_version','files','generator','provenance'},'v6 manifest exact keys')
 need(v['schema']==SCHEMA and v['category']=='ghost-ui' and v['format']=='WCP1' and type(v['profile_version']) is int and v['profile_version']==6 and type(v['format_version']) is int and v['format_version']==1,'explicit v6 profile')
 p=v['provenance'];need(type(p) is dict and set(p)=={'algorithm','publication_authority','availability_policy','source_main_sha256','current_menu_sha256','base_v5_manifest_sha256','base_v5_bank_sha256','sprite_ids','animations','referenced_base_sprite_ids','preserved_v5_sprite_entries_sha256','preserved_v5_animation_tail_sha256','preserved_v5_animation_tail_bytes','original_read_set','appended_sprites','appended_anims','texts','extra_rgba_bytes'},'v6 provenance exact keys');need(p['base_v5_manifest_sha256']==BASE_MANIFEST_SHA and p['base_v5_bank_sha256']==BASE_BANK_SHA and p['source_main_sha256']==MAIN_SHA and p['current_menu_sha256']==MENU_SHA,'v6 independent base/source pins')
 need(p['publication_authority'] is False and p['availability_policy']=='user-approved direct supported original extra colours; not renewal history','v6 authority/policy')
 with_results=type(p['animations']) is list and len(p['animations'])==22
 animations=ANIMS+(GHOST_RESULT_ANIMS if with_results else ())
 count=614+(len(GHOST_RESULT_SPRITES) if with_results else 0)
 need(type(p['sprite_ids']) is list and len(p['sprite_ids'])==count and all(type(i) is int and 0<=i<2147483647 for i in p['sprite_ids']) and len(set(p['sprite_ids']))==count,'exact v6 sprite IDs')
 if with_results:need(p['sprite_ids'][614:]==list(GHOST_RESULT_SPRITES),'exact Ghost result sprite IDs')
 need(type(p['animations']) is list and len(p['animations'])==18+len(animations) and [a['name'] for a in p['animations'][18:]]==[a[0] for a in animations],'exact v6 animations')
 for a in p['animations']:need(set(a)=={'name','frames','records'} and type(a['frames']) is int and 0<a['frames']<=10000 and type(a['records']) is int and 0<=a['records']<=200000,'animation schema')
 need(type(v['files']) is list and len(v['files'])==2 and [f['path'] for f in v['files']]==[BANK_PATH,INDEX_PATH],'reject old/mixed index names')
 for f in v['files']:need(set(f)=={'path','bytes','sha256'} and type(f['bytes']) is int and 0<f['bytes']<=256*1024*1024 and type(f['sha256']) is str and len(f['sha256'])==64,'file schema')
 idx=INDEX_MAGIC+('ghost-ui.bin\t%d\t%s\n'%(v['files'][0]['bytes'],v['files'][0]['sha256'])).encode();need(v['files'][1]==spec(INDEX_PATH,idx),'v6 derived exact index')
 need(p['algorithm']=='3dxplus-cpu-original-repaint-ui-v1' and type(p['extra_rgba_bytes']) is int and p['extra_rgba_bytes']==14429288+(GHOST_RESULT_RGBA if with_results else 0),'finite v6 algorithm/expansion budget')
 need(p['preserved_v5_sprite_entries_sha256']=='6f89629d7bb7467fd27c98839e177d76e6cf860fbe1ff50f4bf38778c175c353' and p['preserved_v5_animation_tail_sha256']=='71b5dca5a9100e496d543924621cd0a7206e587401f60c1b0e710b6ff7ef729a' and type(p['preserved_v5_animation_tail_bytes']) is int and p['preserved_v5_animation_tail_bytes']==3656084,'immutable98/18 base prefix')
 def digest(x):return type(x) is str and re.fullmatch('[0-9a-f]{64}',x) is not None
 need(type(p['referenced_base_sprite_ids']) is list and p['referenced_base_sprite_ids']==sorted(set(p['referenced_base_sprite_ids'])) and all(type(i) is int and 3<i<116000 for i in p['referenced_base_sprite_ids']) and set(p['referenced_base_sprite_ids']).isdisjoint(p['sprite_ids']),'base references exact IDs')
 rs=p['original_read_set'];need(type(rs) is list and 1<=len(rs)<=2048,'source read set budget');last='';source_map={}
 for q in rs:
  need(type(q) is dict and set(q)=={'path','bytes','sha256'} and type(q['path']) is str and re.fullmatch(r'(?:main|data/(?:car|sprite|anime)/[A-Za-z0-9_./-]+)',q['path']) and '..' not in q['path'].split('/') and q['path']>last and type(q['bytes']) is int and 0<q['bytes']<=32*1024**2 and digest(q['sha256']),'source read set record');last=q['path'];source_map[last]=q
 need(source_map.get('main')=={'path':'main','bytes':24855892,'sha256':MAIN_SHA},'main bound into source read set')
 need(source_map.get('data/sprite/font_11.png')=={'path':'data/sprite/font_11.png','bytes':390962,'sha256':'9c716f5cdda88cb60fa156daa0173cbb271b6a526536a0fa55abf89c42b07fbd'},'exact original font0 sheet bound into source read set')
 add=p['appended_sprites'];need(type(add) is list and len(add)==count-98 and [q.get('id') for q in add]==p['sprite_ids'][98:],'exact appended sprite metadata')
 for i,q in enumerate(add):
  need(type(q) is dict and set(q)=={'id','width','height','rgba_sha256','entry_sha256','entry_bytes','origin'} and all(type(q[k]) is int for k in ('id','width','height','entry_bytes')) and 0<q['width']<=2048 and 0<q['height']<=2048 and 12<q['entry_bytes']<=32*1024**2 and digest(q['rgba_sha256']) and digest(q['entry_sha256']),'appended sprite schema');o=q['origin'];need(type(o) is dict,'origin schema')
  if i<421 or i>=516:need(set(o)=={'kind','source'} and o['kind']=='original-sprite' and o['source'] in source_map and 3<q['id']<8091,'original swatch source binding')
  else:need(set(o)=={'kind','text'} and o['kind']=='original-font0' and type(o['text']) is str and 0<len(o['text'])<=64 and q['id']==TEXT_BASE+i-421,'original font0 text namespace')
 need(sum(q['width']*q['height']*4 for q in add)==p['extra_rgba_bytes'],'exact expansion accounting')
 need(type(p['texts']) is list and len(p['texts'])==104 and len({q['text'] for q in p['texts']})==104 and all(set(q)=={'text','id','font'} and type(q['font']) is int and q['font']==0 and type(q['id']) is int and (100002<=q['id']<105000 or TEXT_BASE<=q['id']<TEXT_BASE+95) for q in p['texts']),'exact104 original names')
 need(type(p['appended_anims']) is list and len(p['appended_anims'])==len(animations),'exact original appended animations')
 wire=((1227536,'1bcad1ef313729d898c817f9666adb8041327b87bee196596833b0823ac54d8c'),(259894,'91f5e6af604ee74afbea69ef96e077df079cc7c8f944d9d271f0008ff59b961b'))
 if with_results:wire+=GHOST_RESULT_WIRE
 for q,(name,size,pin),(nsize,npin) in zip(p['appended_anims'],animations,wire):
  path='data/anime/'+name+'.anm';need(q=={'path':path,'bytes':size,'sha256':pin,'normalized_bytes':nsize,'normalized_sha256':npin} and source_map.get(path)=={'path':path,'bytes':size,'sha256':pin},'pinned original and normalized ANM bytes')
 need(type(v['generator']) is dict and set(v['generator'])=={'path','bytes','sha256'} and v['generator']['path']=='tools/vehicle_restore_ui_v6.py' and type(v['generator']['bytes']) is int and 0<v['generator']['bytes']<=1024**2 and digest(v['generator']['sha256']),'generator observation schema')
 return p

def verify(bank,index,expected):
 """Strict explicit-v6 offline verification; old-v5/legacy indexes are rejected."""
 p=validate_expected(expected);need(expected['files']==[spec(BANK_PATH,bank),spec(INDEX_PATH,index)],'v6 bank/index bytes do not match expected');need(index==INDEX_MAGIC+('ghost-ui.bin\t%d\t%s\n'%(len(bank),sha(bank))).encode(),'v6 index exact framing')
 v5=importlib.import_module('ranking_ui_v5')
 try:checked=v5.parse_wire(bank,p['sprite_ids'],p['animations'],p['referenced_base_sprite_ids'])
 except (ValueError,zlib.error,struct.error,UnicodeError) as exc:raise ValueError('invalid v6 WCP1: '+str(exc)) from exc
 cut=checked['sprites'][97]['entry_offset']+checked['sprites'][97]['entry_bytes'];need(cut==482263 and sha(bank[16:cut])==p['preserved_v5_sprite_entries_sha256'],'old98 sprite bytes changed');start=checked['sprite_end'];need(sha(bank[start:start+3656084])==p['preserved_v5_animation_tail_sha256'],'old18 ANM bytes changed')
 for q,ob in zip(p['appended_sprites'],checked['sprites'][98:]):need(all(q[k]==ob[k] for k in ('id','width','height','rgba_sha256','entry_sha256','entry_bytes')),'appended bitmap does not match source observation')
 for q,ob in zip(p['appended_anims'],checked['animation_blocks'][18:]):need(q['normalized_bytes']==ob['bytes'] and q['normalized_sha256']==ob['sha256'],'new ANM normalized bytes changed')
 return checked

def build(a):
 sys.path.insert(0,str(Path(a.tools_root).resolve(strict=True)))
 v5=importlib.import_module('ranking_ui_v5');ms=importlib.import_module('original_convert.menu_support');mc=importlib.import_module('original_convert.menu_car_data');ct=importlib.import_module('original_convert.car_tables');cp=importlib.import_module('original_convert.menu_components')
 manifest_raw=read(a.base_expected,4*1024**2);need(sha(manifest_raw)==BASE_MANIFEST_SHA,'approved base-v5 raw manifest pin');base_expected=json.loads(manifest_raw,object_pairs_hook=pairs);p=v5.validate_expected(base_expected)
 base=read(a.base_bank,256*1024**2);need(len(base)==4138347 and sha(base)==BASE_BANK_SHA,'approved base-v5 bank pin');idx=read(a.base_index,512);need(idx==v5.encode_index(base),'base-v5 exact index');old=v5.parse_wire(base,p['sprite_ids'],p['animations'],p['referenced_base_sprite_ids'])
 existing,main_anims=menu_inventory(read(a.current_menu,400*1024**2));root=Path(a.source_root).resolve(strict=True);reads={}
 def source(name,*,max_bytes=32*1024**2,**ignored):
  path=root/name;need(root in path.resolve(strict=True).parents,'source confinement');b=read(path,max_bytes);ob=spec(name,b);need(name not in reads or reads[name]==ob,'changed original source');reads[name]=ob;return b
 original=source('main');need(sha(original)==MAIN_SHA,'original main pin');s=ms.OriginalSupport(original);db,rows=palette(s,mc,ct,root/'data/car')
 # from_elf reads only bounded data Lua. Bind those exact55 files to the read set.
 for name in db['pack_order']:source('data/car/'+name+'/car.lua',max_bytes=2*1024**2)
 names=sorted({n for r in rows for n in r['names'] if n});extra=[n for n in names if n not in db['texts']];need(len(names)==104 and len(extra)==95,'finite original text family')
 name_ids={n:100002+db['texts'].index(n) for n in names if n in db['texts']};name_ids.update({n:TEXT_BASE+i for i,n in enumerate(extra)})
 animation_chunks=[];anim_specs=[];refs=set();result_refs=set();anim_sources=[]
 with_results=getattr(a,'with_ghost_results',False)
 for name,size,digest in ANIMS+(GHOST_RESULT_ANIMS if with_results else ()):
  need(name not in main_anims and name not in [q['name'] for q in p['animations']],'animation collision');path='data/anime/'+name+'.anm';b=source(path);need(len(b)==size and sha(b)==digest,'original ANM pin');frames,records=cp.load_anm(b);part=struct.pack('<48sII',name.encode(),len(frames),len(records))+b''.join(struct.pack('<II',*f) for f in frames)
  chunks=[];used=refs if name.startswith('menu_g_carsel_') else result_refs
  for q in records:
   sid=q[0] if q[0]>3 else -1;used.add(sid);chunks.append(RECORD.pack(sid,{8:1,9:2}.get(q[15],0),*q[1:7],*(max(-32768,min(32767,int(x))) for x in q[7:15])))
  part+=b''.join(chunks);animation_chunks.append(part);anim_specs.append({'name':name,'frames':len(frames),'records':len(records)});anim_sources.append(dict(spec(path,b),normalized_bytes=len(part),normalized_sha256=sha(part)))
 wanted={i for r in rows for i in r['swatches'] if type(i) is int and i>3}|(refs-{-1});swatches=sorted(wanted-existing-set(p['sprite_ids']));need(len(swatches)==421 and all(i in s.sprites for i in swatches),'exact421missing original swatches')
 renderer=cp.SpriteRenderer(s,source);additions=[];added=[]
 def put(sid,image,origin):
  need(sid not in existing and sid not in p['sprite_ids'],'sprite collision');w,h=image.size;need(0<w<=2048 and 0<h<=2048,'sprite dimension budget');px=image.tobytes();z=zlib.compress(px,6);entry=struct.pack('<iHHI',sid,w,h,len(z))+z;additions.append(entry);added.append({'id':sid,'width':w,'height':h,'rgba_sha256':sha(px),'entry_sha256':sha(entry),'entry_bytes':len(entry),'origin':origin})
 for sid in swatches:put(sid,renderer.sprite(sid,table_size=True),{'kind':'original-sprite','source':s.sprites[sid].path})
 for text in extra:put(name_ids[text],renderer.text(0,text),{'kind':'original-font0','text':text})
 if with_results:
  missing=sorted(result_refs-existing-set(p['sprite_ids'])-set(swatches)-{-1})
  need(tuple(missing)==GHOST_RESULT_SPRITES,'exact Ghost result sprite closure')
  for sid in missing:put(sid,renderer.sprite(sid,table_size=True),{'kind':'original-sprite','source':s.sprites[sid].path})
 ids=p['sprite_ids']+[r['id'] for r in added];animations=p['animations']+anim_specs;base_refs=sorted((set(p['referenced_base_sprite_ids'])|refs|result_refs)-set(ids)-{-1});need(set(base_refs)<=existing,'unresolved animation reference')
 need(all(i in existing or i in ids for i in name_ids.values()),'unresolved name sprite')
 cut=old['sprite_end'];result=struct.pack('<4sIII',b'WCP1',1,len(ids),len(animations))+base[16:cut]+b''.join(additions)+base[cut:]+b''.join(animation_chunks)
 checked=v5.parse_wire(result,ids,animations,base_refs);need(result[16:cut]==base[16:cut] and result[checked['sprite_end']:checked['sprite_end']+len(base)-cut]==base[cut:],'old98sprites/18ANMs preserved byte exact')
 index=INDEX_MAGIC+('ghost-ui.bin\t%d\t%s\n'%(len(result),sha(result))).encode()
 provenance={'algorithm':'3dxplus-cpu-original-repaint-ui-v1','publication_authority':False,'availability_policy':'user-approved direct supported original extra colours; not renewal history','source_main_sha256':MAIN_SHA,'current_menu_sha256':MENU_SHA,'base_v5_manifest_sha256':sha(manifest_raw),'base_v5_bank_sha256':sha(base),'sprite_ids':ids,'animations':animations,'referenced_base_sprite_ids':base_refs,'preserved_v5_sprite_entries_sha256':sha(base[16:cut]),'preserved_v5_animation_tail_sha256':sha(base[cut:]),'preserved_v5_animation_tail_bytes':len(base)-cut,'original_read_set':sorted(reads.values(),key=lambda r:r['path']),'appended_sprites':added,'appended_anims':anim_sources,'texts':[{'text':n,'id':name_ids[n],'font':0} for n in names],'extra_rgba_bytes':sum(r['width']*r['height']*4 for r in added)}
 manifest={'schema':SCHEMA,'category':'ghost-ui','profile_version':6,'format':'WCP1','format_version':1,'files':[spec(BANK_PATH,result),spec(INDEX_PATH,index)],'generator':spec('tools/vehicle_restore_ui_v6.py',Path(__file__).read_bytes()),'provenance':provenance};verify(result,index,manifest)
 out=Path(a.output_directory);need(out.parent.is_dir() and not out.exists(),'fresh output directory required');out.mkdir();(out/'assets').mkdir()
 for path,b in [(BANK_PATH,result),(INDEX_PATH,index),('expected-arcade-ui-v6.json',jb(manifest)),('body_color_assets_private.h',header(rows,name_ids)),('body-color-palette.json',jb(rows)),('receipt.json',jb({'bank':spec(BANK_PATH,result),'sprite_count':len(ids),'animation_count':len(animations),'appended_sprites':len(added),'extra_rgba_bytes':provenance['extra_rgba_bytes'],'old98sprites_18anms_byte_exact':True,'no_seventh_resource':True}))]:
  with (out/path).open('xb') as f:f.write(b);f.flush();os.fsync(f.fileno())
 return manifest
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--tools-root',required=True);p.add_argument('--source-root',required=True);p.add_argument('--current-menu',required=True);p.add_argument('--base-bank',required=True);p.add_argument('--base-expected',required=True);p.add_argument('--base-index',required=True);p.add_argument('--output-directory',required=True);p.add_argument('--with-ghost-results',action='store_true')
 try:v=build(p.parse_args());print(json.dumps({'files':v['files'],'sprites':len(v['provenance']['sprite_ids']),'animations':len(v['provenance']['animations'])},indent=2))
 except (ValueError,OSError,KeyError,TypeError,struct.error) as e:p.exit(2,str(e)+'\n')
