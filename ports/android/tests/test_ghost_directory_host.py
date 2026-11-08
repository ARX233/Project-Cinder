#!/usr/bin/env python3
"""Offline full-production-menu host checks; not GPU, Android, or native-play proof.

ANM hit geometry is measured from original source records and source sprite sizes,
not manufactured rectangles. Catalogue names/IDs and difficulty/model/ramp inputs
come from real extracted records and the separately audited Native lane. All
fixtures/binaries/logs are generated beneath the caller's W/tmp (never source).
No device, network, installation, source import side effects, or original writes.
"""
from pathlib import Path
import hashlib, json, os, struct, subprocess, sys, tempfile
LOCAL=Path(__file__).resolve().parents[1]  # source tree, isolated lane or merged canonical
W=LOCAL.parent.parent.parent if LOCAL.parent.parent.name=='lanes' else LOCAL.parent
SOURCE=W/'source'
UI_SRC=LOCAL/'src';UI_TESTS=LOCAL/'tests'
FALLBACK=Path(os.environ.get('CINDER_PRIVATE_SRC','/Volumes/CodexWork/cinder-native-hrr-20261104-LN9S0i/source/src'))
PRIVATE=Path(os.environ.get('CINDER_GHOST_PRIVATE_HEADERS','/Volumes/CodexWork/cinder-smoke-vs-story-20261107-940tm01n/generated'))
PRIVATE_FLAGS=['-I',str(PRIVATE/'ta-ranking'),'-I',str(PRIVATE/'vehicle-restore')]
MAIN=Path(os.environ.get('CINDER_ORIGINAL_MAIN','/Volumes/MacSave/WMMT3 Phone/Fulldata/Wangan Midnight 3DX+[banwu]/Wangan Midnight 3DX+/main'))
META=Path(os.environ.get('CINDER_GHOST_METADATA','/Volumes/CodexWork/cinder-builtin-ghost-20261106-yz1jxof0/lanes/resources/all_targets_metadata_only.json'))
NATIVE=Path(os.environ.get('CINDER_GHOST_NATIVE_ANALYSIS',str(W/'lanes/native/analysis')))
raw=MAIN.read_bytes();digest=hashlib.sha256(raw).hexdigest()
assert digest=='2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
# Execution-free ELF address mapping (file-backed alloc sections only).
shoff=struct.unpack_from('<I',raw,32)[0];ents,n=struct.unpack_from('<HH',raw,46)
sections=[struct.unpack_from('<10I',raw,shoff+i*ents) for i in range(n)]
def read(va,size):
 for s in sections:
  if s[1]!=8 and s[2]&2 and s[3]<=va and va+size<=s[3]+s[5]:
   o=s[4]+va-s[3];return raw[o:o+size]
 raise ValueError(hex(va))
def u32(a):return struct.unpack('<I',read(a,4))[0]
def cstr(a):return read(a,256).split(b'\0',1)[0].decode('utf-8')
# Original ANM paths, independently resolved from the source's table.
anm_paths={Path(cstr(u32(0x954fb60+8*i))).stem:cstr(u32(0x954fb60+8*i)) for i in range(829)}
names=['menu_layout_tg_search_grayout','menu_layout_tg_search_grayout_arrow','menu_layout_tg_seach_ring',
 'menu_layout_tg_search_2','menu_layout_tg_seach_ring_2','menu_layout_tg_lv','menu_layout_tg_lv_arrow',
 'menu_layout_tg_lv_yourlv','menu_layout_tg_vs_course','menu_layout_tg_vs_sel','menu_layout_tg_rival',
 'menu_layout_yn_card_1_gold','menu_layout_yn_ring','menu_g_name_number','menu_g_name_katakana',
 'menu_g_name_hiragana','menu_g_name_capital','menu_g_name_small','menu_g_name_end',
 'menu_layout_name_select','menu_g_name_name_back','menu_g_name_line','menu_use_name','menu_g_topbar_bar',
 'menu_g_finish_win','menu_g_finish_lose']
# menu_use_name's real source basename differs across existing generated recipes.
names=[v for v in names if v in anm_paths]
rect_ids={453,1896,1898,925,1570,1571,950,898,4283,6241,5586,6777,6584,6776,6583,6582,6240,5588,4733,3869,3229,4172,6635,0x1e68,0x1cdc,446,899,4646,4648,4650,4652,4659,4654,4655,4661}
rect_ids.update({6673,6985,6986,*range(6726,6736)})
width={};height={}
for sid in range(4,8091):
 width[sid],height[sid]=struct.unpack('<2f',read(0x9551560+44*sid+16,8))
work=Path(tempfile.mkdtemp(prefix='ui-directory-',dir=W/'tmp')).resolve()
assert work.is_relative_to((W/'tmp').resolve())
def cf(v):
 text=format(v,'.9g')
 return text+('' if '.' in text or 'e' in text else '.0')+'f'
lines=['typedef struct { int anim,frame,sprite;float r[4]; } fixture_rect;','static const fixture_rect FIX_RECT[]={']
observations=[]
for ai,name in enumerate(names):
 path=MAIN.parent/anm_paths[name];data=path.read_bytes();nf,mr=struct.unpack_from('<II',data);base=8+8*nf
 assert 0<nf<=20000 and (len(data)-base)%64==0
 records=[struct.unpack_from('<i6f9i',data,i) for i in range(base,len(data),64)]
 for f in range(nf):
  first,count=struct.unpack_from('<II',data,8+8*f);assert count<=mr and first+count<=len(records)
  seen=set()
  for rec in records[first:first+count]:
   sid,a,b,c,d,x,y,*col=rec
   if sid not in rect_ids or sid in seen:continue
   seen.add(sid);w,h=width[sid],height[sid]
   points=[(x+a*xx+c*yy,y+b*xx+d*yy) for xx,yy in [(0,0),(w,0),(0,h),(w,h)]]
   r=[min(q[0] for q in points),min(q[1] for q in points),max(q[0] for q in points),max(q[1] for q in points)]
   lines.append('{%d,%d,%d,{%s}},'%(ai,f,sid,','.join(cf(v) for v in r)))
 observations.append(dict(name=name,frames=nf,source=str(path),sha256=hashlib.sha256(data).hexdigest()))
lines+=['};','static const struct {const char*name;int frames;} FIX_ANM[]={']
lines += ['{%s,%d},'%(json.dumps(v['name']),v['frames']) for v in observations]
lines+=['};','static const struct {int id;float w,h;} FIX_SPRITE[]={']
lines += ['{%d,%s,%s},'%(sid,cf(width[sid]),cf(height[sid])) for sid in sorted(width) if width[sid]>0 and height[sid]>0]
lines+=['};']
meta=json.loads(META.read_text());catalog=meta['records'];assert len(catalog)==196
bindings=json.loads((NATIVE/'all_bindings.json').read_text());assert bindings['summary']['rows']==1267 and bindings['summary']['issues']==0
models={r['raw_model_id']:r for r in json.loads((NATIVE/'model_map.json').read_text())['rows']}
ramps={r['raw_ramp']:r['record'][2] for r in json.loads((NATIVE/'ramp_tables.json').read_text())}
actual_path=Path(os.environ.get('CINDER_GHOST_NATIVE_FIXTURE',str(NATIVE/'native_menu_bindings.json')))
actual=json.loads(actual_path.read_text());assert actual['schema']=='actual-native-builtin-world-fixture-v1' and len(actual['rows'])==1267
actual_by_key={}
for r in actual['rows']:
 assert r['native_target_valid']==1 and r['native_ticks']>=241 and r['collision_registrations']>=241
 key=(r['record_index'],r['area']);assert key not in actual_by_key;actual_by_key[key]=r
byid={}
for r in bindings['rows']:
 assert r['header_stage']==r['native_stage'] and r['ordered_stage_sequence'] and not r['missing_native_areas']
 key=(r['source_id'],r['slot']);assert key not in byid;byid[key]=r
lines+=['static menu_ghost_directory_row REAL_ROWS[196]={']
level_counts=[0]*10
for index,row in enumerate(catalog):
 md=row['metadata'];name=md['name_codepoints'];assert len(name)==5
 sid=f"{md['id_devel_raw']}-{md['id1_raw']}-{md['id2_raw']}"
 areas=[]
 for area in range(8):
  r=byid.get((sid,area))
  if r is None:areas.append('{.level=-1,.pack=-1,.paint=-1,.power=-1,.handling=-1}');continue
  total=min(r['power']+r['handling'],35);level=u32(0x932a280+12*total)
  if level==8 and r['wins']>=300:level=9
  b=actual_by_key[(index,area)];model=models[r['model']]
  assert (b['id_devel'],b['id1'],b['id2'])==(md['id_devel_raw'],md['id1_raw'],md['id2_raw']) and b['name_codepoints']==name
  assert b['source_id']==((index+1)<<32)|(area+1)
  assert b['target_level']==level and b['model']==r['model'] and b['ramp']==ramps[r['raw_ramp']] and b['raw_route']==r['raw_route']
  assert b['power']==r['power'] and b['handling']==r['handling'] and b['pack']==model['pack'] and b['base_paint']==model['paint']
  assert b['race_field'][0]==r['native_stage']
  level_counts[b['target_level']]+=1
  areas.append('{.level=%d,.native_available=1,.ramp=%d,.route=%d,.pack=%d,.paint=%d,.raw_model=%d,.power=%d,.handling=%d}'%(b['target_level'],b['ramp'],b['raw_route'],b['pack'],b['paint'],b['model'],b['power'],b['handling']))
 lines.append('{.record_index=%d,.id_devel=%d,.id1=%d,.id2=%d,.name={%s},.areas={%s}},'%(index,md['id_devel_raw'],md['id1_raw'],md['id2_raw'],','.join(str(v) for v in name),','.join(areas)))
lines+=['};']
fixture=work/'fixture.h';fixture.write_text('\n'.join(lines)+'\n')
manifest=dict(main_sha256=digest,records=196,profiles=1267,levels=level_counts,animations=observations,
 fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
 metadata_sha256=hashlib.sha256(META.read_bytes()).hexdigest(),
 native_binding_audit_sha256=hashlib.sha256((NATIVE/'all_bindings.json').read_bytes()).hexdigest(),
 native_actual_fixture_sha256=hashlib.sha256(actual_path.read_bytes()).hexdigest(),native_bank_sha256=actual['bank_sha256'],
 authority='host menu state/draw-call/actual-ANM geometry only; separate Native-lane proof is not a host-menu result')
(work/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
for backend,flags in ([] if os.environ.get('CINDER_UI_FIXTURES_ONLY')=='1' else [('gles',[]),('vkcompat',['-DWMMT_VK=1']),('nativevk',['-DWMMT_NATIVE_VK=1'])]):
 exe=work/backend
 command=[os.environ.get('CC','clang'),'-std=gnu11','-O1','-g','-U__APPLE__','-Wall','-Wextra','-Wno-unused-function','-Wno-unused-parameter',
  '-DWMMT_PRE_RACE_TEST=1','-DWMMT_BGM_TEST=1','-DWMMT_GL_H=1','-include',str(SOURCE/'test/glstub.h'),*flags,
  *PRIVATE_FLAGS,'-I',str(UI_SRC),'-I',str(SOURCE/'src'),'-I',str(SOURCE/'test'),'-I',str(FALLBACK),'-I',str(work),
  '-DPORT_MENU='+json.dumps(str(UI_SRC/'menu.c')),'-ffunction-sections','-fdata-sections',
  '-fsanitize=undefined','-fno-sanitize-recover=all',str(UI_TESTS/'ghost_directory_host.c'),
  str(SOURCE/'src/pre_race_tune.c'),str(SOURCE/'src/story_assembly.c'),'-Wl,-dead_strip','-Wl,-undefined,dynamic_lookup','-lm','-o',str(exe)]
 subprocess.run(command,check=True,cwd=work,timeout=120)
 result=subprocess.run([str(exe)],check=True,cwd=work,capture_output=True,text=True,timeout=120,
  env=dict(os.environ,UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1',CINDER_UI_TRACE='1' if backend=='gles' else '0'))
 (work/(backend+'.log')).write_text(result.stdout+result.stderr)
 print(backend,result.stdout.strip())
print('ARTIFACTS',work)
