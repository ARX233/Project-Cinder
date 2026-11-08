#!/usr/bin/env python3
"""Full-production menu typed-default contracts using actual Native fixture.
No Native/target execution/RNG in these host tests. Actual engine proof is external.
"""
from pathlib import Path
import hashlib,json,os,runpy,subprocess
HERE=Path(__file__).resolve().parent
old=os.environ.get('CINDER_UI_FIXTURES_ONLY');os.environ['CINDER_UI_FIXTURES_ONLY']='1'
try: ctx=runpy.run_path(str(HERE/'test_ghost_directory_host.py'))
finally:
 if old is None:os.environ.pop('CINDER_UI_FIXTURES_ONLY',None)
 else:os.environ['CINDER_UI_FIXTURES_ONLY']=old
work,SOURCE,UI_SRC,FALLBACK,NATIVE,PRIVATE_FLAGS=[ctx[k] for k in ['work','SOURCE','UI_SRC','FALLBACK','NATIVE','PRIVATE_FLAGS']]
path=Path(os.environ.get('CINDER_GHOST_DEFAULT_FIXTURE',str(NATIVE/'native_default_bindings.json')))
raw=path.read_bytes();data=json.loads(raw)
assert data['schema']=='actual-native-original-default-fixture-v1'
assert data['original_elf_sha256']==ctx['digest'] and data['metadata_count']==120 and data['manager_eligible_count']==109 and data['selection_count']==872
meta=data['metadata'];maps=data['selections'];assert len(meta)==120 and len(maps)==872
# Native's real enumeration test snapshots rc_mem, RNG and heap after initialization.
zero_log=NATIVE.parent/'tests/default-probe-v7.log'
assert 'ENUM120 eligible109 skipped11: ZERO RNG/image/heap mutation after initial metadata load' in zero_log.read_text()
assert sum(r['manager_eligible'] for r in meta)==109
eligible=[r['index'] for r in meta if r['manager_eligible']]
policy=json.loads((NATIVE/'default_manager_eligibility.json').read_text());assert eligible==policy['eligible_indices']
lines=['/* Actual Native getter/select outputs; generated offline, not mock data. */',
 'enum {DEFAULT_NATIVE_AVAILABLE=1, DEFAULT_ENUM_ZERO_RNG=1};',
 'static const unsigned char DEFAULT_ELIGIBLE[120]={'+','.join(str(r['manager_eligible']) for r in meta)+'};',
 'static const uint64_t DEFAULT_SOURCE_IDS[120]={'+','.join('UINT64_C(%d)'%r['car']['source_id'] for r in meta)+'};',
 'static menu_ghost_directory_row UI_DEFAULT_FIX_ROWS[120]={']
levels=[0]*10
for i,r in enumerate(meta):
 assert r['index']==i and r['manager_eligible'] in [0,1]
 name=r['name_codepoints'];assert name==r['name'] and len(name)==5 and all(type(v)is int and 0<=v<=65535 and not 0xd800<=v<=0xdfff for v in name)
 c=r['car'];assert all(c[k]==-1 for k in ['raw_ramp','ramp','raw_route','city','render_course']) and c['route_count']==0 and c['race_field']==[0]*6
 assert c['source_id']==((1<<63)|(i+1)) and 0<=c['target_level']<=9 and c['pack']>=0 and c['paint']>=0
 if r['manager_eligible']:levels[c['target_level']]+=1
 a='{.level=%d,.native_available=%d,.ramp=-1,.route=-1,.pack=%d,.paint=%d,.raw_model=%d,.power=%d,.handling=%d,.title=%d}'%(c['target_level'],r['manager_eligible'],c['pack'],c['paint'],r['raw_model_id'],c['rival']['power'],c['rival']['handling'],r['title'])
 style=',.base_paint=%d,.custom_color=%d,.aero=%d,.vinyl=%d,.bonnet=%d,.mirror=%d,.wing=%d,.wheel=%d,.neon=%d'%(c['base_paint'],r['raw_custom_color'],r['raw_aero'],r['raw_vinyl'],r['raw_bonnet'],r['raw_mirror'],r['raw_wing'],0 if r['raw_wheel']==143 else r['raw_wheel']+1,r['raw_neon'])
 lines.append('{.record_index=%d,.id_devel=%d,.id1=%d,.id2=%d,.name={%s},.areas={%s},.source_kind=MENU_GHOST_SOURCE_DEFAULT},'%(i,r['id_devel'],r['id1'],r['id2'],','.join(str(v) for v in name),','.join(a[:-1]+style+',.default_crown=%d}'%(r['crown_area']==area) for area in range(8))))
lines+=['};','typedef struct {unsigned index,area;int ramp,route;uint64_t source_id,token,cookie;uint32_t field[6];} default_map_fixture;',
 'static const default_map_fixture DEFAULT_MAPS[]={']
seen=set();cookies=set()
for r in maps:
 i,area=r['index'],r['area'];assert (i,area) not in seen and i in eligible and 0<=area<8;seen.add((i,area))
 c=r['car'];m=meta[i]['car'];assert r['native_default_ai_valid']==1 and r['native_target_valid']==0 and r['native_ticks']>=241
 assert c['source_id']==m['source_id'] and c['source_id']>2**53 and r['session_token']>2**53 and r['choice_cookie']>0 and r['choice_cookie'] not in cookies;cookies.add(r['choice_cookie'])
 assert 1<=c['ramp']<=22 and 0<=c['raw_route']<c['route_count'] and 0<=c['raw_ramp']<22 and c['race_field'][0]>0
 assert all(c[k]==m[k] for k in ['pack','paint','target_level','target_rank','base_paint','custom_color']) and c['rival']==m['rival']
 lines.append('{%d,%d,%d,%d,UINT64_C(%d),UINT64_C(%d),UINT64_C(%d),{%s}},'%(i,area,c['ramp'],c['raw_route'],c['source_id'],r['session_token'],r['choice_cookie'],','.join(str(v)+'u' for v in c['race_field'])))
assert seen=={(i,a) for i in eligible for a in range(8)}
lines+=['};'];fixture=work/'default_fixture.h';fixture.write_text('\n'.join(lines)+'\n')
source=(UI_SRC/'menu.c').read_text();assert all(s not in source for s in ['car_ghost_default_record(', 'car_ghost_default_select(', 'car_ghost_default_prepare(', 'car_ghost_default_info(', 'getRandomRamp(', 'getRandomRoute('])
manifest=dict(original_main_sha256=ctx['digest'],native_fixture_sha256=hashlib.sha256(raw).hexdigest(),native_fixture=str(path),
 native_v7_source_sha256=data['native_v7_source_sha256'],compiled_table_sha256=data['compiled_table_sha256'],
 native_zero_rng_log_sha256=hashlib.sha256(zero_log.read_bytes()).hexdigest(),metadata=120,eligible=109,disabled_placeholders=11,late_maps=872,levels=levels,
 menu_sha256=hashlib.sha256((UI_SRC/'menu.c').read_bytes()).hexdigest(),header_sha256=hashlib.sha256((UI_SRC/'menu.h').read_bytes()).hexdigest(),
 fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),authority='UI host callback/selection contracts only; actual Native provenance is independently produced, no native-win/GPU/device claim')
(work/'default-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
for backend,flags in [('gles',[]),('vkcompat',['-DWMMT_VK=1']),('nativevk',['-DWMMT_NATIVE_VK=1'])]:
 exe=work/('default-'+backend)
 command=[os.environ.get('CC','clang'),'-std=gnu11','-O1','-g','-U__APPLE__','-Wall','-Wextra','-Wno-unused-function','-Wno-unused-parameter',
  '-DWMMT_PRE_RACE_TEST=1','-DWMMT_BGM_TEST=1','-DWMMT_GL_H=1','-include',str(SOURCE/'test/glstub.h'),*flags,
  *PRIVATE_FLAGS,'-I',str(UI_SRC),'-I',str(SOURCE/'src'),'-I',str(SOURCE/'test'),'-I',str(FALLBACK),'-I',str(work),
  '-DPORT_MENU='+json.dumps(str(UI_SRC/'menu.c')),'-ffunction-sections','-fdata-sections','-fsanitize=undefined','-fno-sanitize-recover=all',
  str(HERE/'ghost_default_directory_host.c'),str(SOURCE/'src/pre_race_tune.c'),str(SOURCE/'src/story_assembly.c'),'-Wl,-dead_strip','-Wl,-undefined,dynamic_lookup','-lm','-o',str(exe)]
 subprocess.run(command,check=True,cwd=work,timeout=120)
 result=subprocess.run([str(exe)],check=True,cwd=work,capture_output=True,text=True,timeout=120,
  env=dict(os.environ,UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1',CINDER_UI_TRACE='1' if backend=='gles' else '0'))
 (work/('default-'+backend+'.log')).write_text(result.stdout+result.stderr)
 print(backend,result.stdout.strip())
print('DEFAULT_ARTIFACTS',work)
