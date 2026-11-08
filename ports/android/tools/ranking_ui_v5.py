#!/usr/bin/env python3
"""Explicit opt-in Arcade UI v5: preserve reviewed v4 bytes, append15 sprites and the original R35 Step layout.

Caller selects all local inputs. No original/Lua execution, networking, GPU, asset
mutation, generated fonts, JNI change or implicit approval. Expected output is an
observational candidate until independently reviewed by the parent/release owner.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
import zlib

SCHEMA = 'project-cinder-arcade-ui-v5'
INDEX_MAGIC = b'WMMT-ARCADE-UI-5\n'
INDEX_PATH = 'assets/arcade-ui-v5-index.tsv'
BANK_PATH = 'assets/ghost-ui.bin'
MAIN_SHA = '2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
CURRENT_MENU_SHA = 'c5eff443269e1835a6bffa834e1000cb24516a6a89e8d4c1a2c0874dd462a99c'
CURRENT_MENU_BYTES = 324123636
MAX_BANK = 256 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
MAX_SOURCE = 32 * 1024 * 1024
RECORD = struct.Struct('<iH6f4h4h')
BASE_ANIMS = (
 'menu_layout_tg_search_grayout', 'menu_layout_tg_search_grayout_arrow',
 'menu_layout_tg_seach_ring', 'menu_layout_tg_search_2', 'menu_layout_tg_seach_ring_2',
 'menu_layout_tg_search_3', 'menu_layout_tg_seach_ring_3', 'menu_layout_tg_lv',
 'menu_layout_tg_lv_arrow', 'menu_layout_tg_lv_yourlv', 'menu_layout_tg_vs_course',
 'menu_layout_tg_vs_course_new', 'menu_layout_tg_vs_course2', 'menu_g_name_number',
 'menu_layout_tg_vs_sel', 'menu_layout_tg_rival', 'menu_layout_tg_vs')
STEP_NAME='menu_layout_ranking_ph'
STEP_SOURCE_PATH='data/anime/menu_layout_ranking_ph.anm'
STEP_BYTES=60256
STEP_SHA='20241b2e2f3f2458f6ffd563663e2db4f9c9eb3af0e0b585b928ba14df97ce24'
STEP_IDS=(1408,2656,3335,3351,3353,3354,3355,5679,5680,6794,6795,7308,7450,7517,7518,7519,7520,7521,7522,7523,7524,7525,7527,7528,7529,7530)
STEP_SPEC={'name':STEP_NAME,'frames':50,'records':1300}
ANIMS=BASE_ANIMS+(STEP_NAME,)
ADDITIONS = (
 (2719, 'menu_p_car_bariki_d.png', 32, 16),
 (2720, 'menu_p_car_bariki_g.png', 32, 16),
 (3145, 'menu_p_car_bariki_dg.png', 32, 16),
 (3146, 'menu_p_car_bariki_hg.png', 32, 16),
 (3346, 'menu_p_ranking_rankA.png', 16, 32),
 (3347, 'menu_p_ranking_rankB.png', 16, 32),
 (3348, 'menu_p_ranking_rankC.png', 16, 32),
 (3350, 'menu_p_ranking_rankS.png', 16, 32),
 (7631, 'cons_p_rival_car_GDB_name_0012.png', 128, 32),
 (7792, 'cons_p_rival_car_CE9A_name_0012.png', 128, 32),
 (7793, 'cons_p_rival_car_CP9A5_name_001.png', 128, 32),
 (7899, 'cons_p_rival_car_BNR34_name_0012.png', 128, 32),
 (7902, 'cons_p_rival_car_CT9A8_name_0012.png', 128, 32),
 (5679, 'menu_p_ranking_bariki_h.png',32,16),
 (5680, 'menu_p_ranking_bariki_p.png',32,16))
APPENDED_IDS = tuple(row[0] for row in ADDITIONS)

# Reviewed immutable source fingerprints, not embedded resource/font bytes.
SOURCE_PINS = {
 'data/sprite/cons_p_rival_car_BNR34_name_0012.png': (6083, '3c3951043fa2561a55b84147980a3e93ae0c69f296977ea8c7f864beec6806df'),
 'data/sprite/cons_p_rival_car_CE9A_name_0012.png': (6082, '6764dbd8d2302226157d946be6c9694a74d4fd7f98cfbfed4670b4cb4baa53b1'),
 'data/sprite/cons_p_rival_car_CP9A5_name_001.png': (4928, '66d322bc2bcb679408c98407a5095b086aa07ba03b15a607295fbb8abdce667e'),
 'data/sprite/cons_p_rival_car_CT9A8_name_0012.png': (5778, '5cf518f5d224b77751e0651ea2746dd0896f940be29aa3a8ce463eacaf0feac6'),
 'data/sprite/cons_p_rival_car_GDB_name_0012.png': (6420, '495660ffc853c815818099bc117093318d2e01e49f1191bd308b83370fe33f4f'),
 'data/sprite/menu_p_car_bariki_d.png': (3122, 'e04af128c087a551e0b0cc9bac3e1727254cde0d6deb0df3c4f8cfecfdd1fc5a'),
 'data/sprite/menu_p_car_bariki_dg.png': (3357, 'b85b66a5a2e4777198aebfe3fae508681f5d1adf6aac6de63b8c5a667adb21db'),
 'data/sprite/menu_p_car_bariki_g.png': (3246, '2a6e1a1556f761903e1311da34197d9fecd8b390328675157e6ba8b1f3d7caf3'),
 'data/sprite/menu_p_car_bariki_hg.png': (3490, '9dee8ce9c68fa1b9cd881260a7b548aa0574d3e17b698ffb8ee4befebb68896e'),
 'data/sprite/menu_p_ranking_rankA.png': (3436, '565cff790aee6ea15976d00417d68642ea8f9f7a709db3c834352e016fd1a010'),
 'data/sprite/menu_p_ranking_rankB.png': (3313, '7de31afe3fe1c0256659ecf6a193db436cf7557b96f9abb52cb4fd4898a28213'),
 'data/sprite/menu_p_ranking_rankC.png': (3417, '3900cb6f4aedb1aaedb0074ff2917f70bae7d07afcf40c21f3bdf73b8d6859b4'),
 'data/sprite/menu_p_ranking_rankS.png': (3457, '9a1b2b72969eaa50657ed6a1bd7ca353dcc949d288ae992d48037b1c4c6b1889'),
 STEP_SOURCE_PATH:(83672,'e3e62185376c24bc3c1b4a2abed572d2cb56f34ac6781ad0ddb012c68174cdb7'),
 'data/sprite/menu_p_ranking_bariki_h.png':(3264,'a45b7194eb8835b9ba42f78d182c0f329b13867f8eaed3a7961f24026bef6b6b'),
 'data/sprite/menu_p_ranking_bariki_p.png':(3153,'1263f98c258ce65e739366df1634a41d4f34be215a27fbc53a8ba0a02df04afd'),
 'main': (24855892, '2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'),
}
SOURCE_RGBA = {
 2719: '53f022232b28ff1cb50900c45ada6f8be62a6ea7b2f349f4686a82b260833b16',
 2720: '1c628b282c867bad2effa399839562e18c52a58093b432fa91ce4c6b870e878d',
 3145: 'd7dcc6d6b91c10120047bc2199204bfb77f8d7ed30aba6f3931e5fea6d040c1d',
 3146: '493f4c16198fda56f315f8fa897b6a8c463a3ea1c68a4b87395c7fe9685dc89a',
 3346: '9bedeb48e86c89800abd4d5db60c01e4f64529bd91bcdd66552a353ce651c1a3',
 3347: '0cda5d275330dd47160f715ed3eec18c03e095d2e4dbd4e559bf1a952a256912',
 3348: '34de5904d5c4c078d87ea8c632ad8b28b2439129e93bb77e1fd7ca40e5ce94ab',
 3350: 'aa9e597cb5f3d91f32dc529fc281402c4f0d0cc320132f27fa808a65ec7963d3',
 7631: 'f587639b9cd78da92c02a969891536278f648484a26494b60e3c7057cd12800c',
 7792: 'b747597bd106e2e25fa5cea4a15d2b9f40519d610877dafb88093bbfd989ea73',
 7793: '6dc51d5857340bdee758331110e8d446874a5269a58ad8d6017195b24620cf5e',
 7899: '7af20cf716546ec119aa8631ef2967d4076acd4c7f8f561c8f2b50c77f912b1e',
 7902: 'c6081d2a0066da774f9a415459499a7ed0283eca4df9c6328ac9028fb632c417',
 5679:'d6ba1ec39cda1399dc7f2bbebaed61404de2c8d6aa3d140b0f8f0b3a1c0097c2',
 5680:'39c251b338efd4e2e7114bd153a50fede595cecdec1abb52a0d34e69cee7d347',
}

class Invalid(ValueError):
 pass

def require(condition, message):
 if not condition:
  raise Invalid(message)

def sha(data):
 return hashlib.sha256(data).hexdigest()

def pin(value):
 require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None, 'invalid SHA256 pin')
 return value

def read_regular(path, limit):
 """No-follow final component, stable regular-file bytes, bounded allocation."""
 path = Path(path)
 fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
 try:
  before = os.fstat(fd)
  require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
          0 <= before.st_size <= limit, 'input type/link-count/size budget')
  with os.fdopen(fd, 'rb', closefd=False) as stream:
   data = stream.read(limit + 1)
  after = os.fstat(fd)
  require(len(data) == before.st_size and
          (before.st_dev, before.st_ino, before.st_nlink, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
          (after.st_dev, after.st_ino, after.st_nlink, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
          'input changed while reading')
  return data
 finally:
  os.close(fd)

def pairs(items):
 out = {}
 for key, value in items:
  require(key not in out, 'duplicate JSON key')
  out[key] = value
 return out

def read_json(path, expected_sha):
 data = read_regular(path, MAX_JSON)
 require(sha(data) == pin(expected_sha), 'JSON differs from explicit independent input pin')
 return json.loads(data.decode('utf-8', 'strict'), object_pairs_hook=pairs), data

def exact_int(value, low, high, message):
 require(type(value) is int and low <= value <= high, message)
 return value

def decode_pixels(payload, width, height, compressed):
 raw = width * height * 4
 if not compressed:
  require(len(payload) == raw, 'raw pixel size')
  return payload
 require(len(payload) <= raw + ((raw + 16382) // 16383) * 5 + 6, 'compressed pixel budget')
 decoder = zlib.decompressobj()
 pixels = decoder.decompress(payload, raw + 1)
 require(len(pixels) == raw and decoder.eof and not decoder.unused_data and
         not decoder.unconsumed_tail, 'invalid DEFLATE extent/pixel count')
 return pixels

def parse_wire(data, expected_ids, expected_anims, referenced_base_ids):
 """Full WCP1 validation. Order is explicit, not implicitly globally sorted."""
 require(isinstance(data, bytes) and 16 <= len(data) <= MAX_BANK, 'bank byte budget')
 at = 0
 def take(count):
  nonlocal at
  require(type(count) is int and 0 <= count <= len(data) - at, 'truncated WCP1')
  value = data[at:at + count]; at += count
  return value
 def unpack(fmt):
  return struct.unpack(fmt, take(struct.calcsize(fmt)))
 magic, version, ns, na = unpack('<4sIII')
 require(magic == b'WCP1' and version == 1 and ns == len(expected_ids) and
         na == len(expected_anims), 'wire magic/version/count')
 require(len(set(expected_ids)) == ns and all(type(i) is int and i >= 0 for i in expected_ids), 'duplicate/invalid sprite IDs')
 sprites = []
 expanded = 0
 for expected in expected_ids:
  begin = at
  sid, w, h, zs = unpack('<iHHI')
  require(sid == expected and 0 < w <= 2048 and 0 < h <= 2048, 'sprite identity/dimensions')
  expanded += w * h * 4
  require(expanded <= MAX_BANK, 'expanded pixel budget')
  payload = take(zs or w * h * 4)
  pixels = decode_pixels(payload, w, h, bool(zs))
  sprites.append({'id': sid, 'width': w, 'height': h, 'zlib_bytes': zs,
                  'entry_offset': begin, 'entry_bytes': at - begin,
                  'entry_sha256': sha(data[begin:at]), 'rgba_sha256': sha(pixels)})
 sprite_end = at
 allowed = set(expected_ids) | set(referenced_base_ids) | {-1}
 seen = set();animation_blocks=[]
 for expected in expected_anims:
  animation_begin=at
  name_raw, nf, nr = unpack('<48sII')
  require(b'\0' in name_raw and name_raw[0] != 0, 'animation name terminator')
  end = name_raw.index(0)
  require(not any(name_raw[end:]), 'noncanonical animation name padding')
  name = name_raw[:end].decode('ascii', 'strict')
  require(name not in seen and {'name': name, 'frames': nf, 'records': nr} == expected, 'animation identity/count')
  seen.add(name)
  require(0 < nf <= 10000 and nr <= 200000, 'animation bounds')
  frames = take(8 * nf)
  for offset in range(0, len(frames), 8):
   start, count = struct.unpack_from('<II', frames, offset)
   require(start <= nr and count <= nr - start, 'frame bounds')
  records = take(RECORD.size * nr)
  for offset in range(0, len(records), RECORD.size):
   row = RECORD.unpack_from(records, offset)
   require(row[0] in allowed and row[1] <= 2 and all(math.isfinite(v) for v in row[2:8]), 'record reference/blend/finite transform')
  animation_blocks.append({'name':name,'offset':animation_begin,'bytes':at-animation_begin,'sha256':sha(data[animation_begin:at])})
 require(at == len(data), 'trailing bank bytes')
 return {'sprites': sprites, 'sprite_end': sprite_end, 'expanded_rgba_bytes': expanded,'animation_blocks':animation_blocks,
         'sprite_entries_sha256': sha(data[16:sprite_end]),
         'animation_tail_sha256': sha(data[sprite_end:]), 'animation_tail_bytes': len(data) - sprite_end}

def file_spec(path, data):
 return {'path': path, 'bytes': len(data), 'sha256': sha(data)}

def encode_index(bank):
 return INDEX_MAGIC + ('ghost-ui.bin\t%d\t%s\n' % (len(bank), sha(bank))).encode('ascii')

def check_v4(expected, bank, index):
 require(expected.get('schema') == 'project-cinder-ghost-ui-v4' and
         expected.get('category') == 'ghost-ui' and expected.get('format') == 'WCP1' and
         expected.get('version') == 1, 'not explicit reviewed UI v4')
 require(expected.get('files') == [file_spec(BANK_PATH, bank), file_spec('assets/ghost-ui-index-v1.tsv', index)], 'v4 files differ from reviewed expectations')
 require(index == b'WMMT-GHOST-UI-1\n' + ('ghost-ui.bin\t%d\t%s\n' % (len(bank), sha(bank))).encode('ascii'), 'v4 index bytes')
 p = expected['provenance']
 require(p['source_main_sha256'] == MAIN_SHA and p['publication_authority'] is False and
         p['sprite_count'] == 83 and p['animation_count'] == 17 and len(p['sprite_ids']) == 83 and
         p['sprite_ids'] == sorted(set(p['sprite_ids'])) and
         tuple(a['name'] for a in p['animations']) == BASE_ANIMS and
         set(p['sprite_ids']).isdisjoint(p['referenced_base_sprite_ids']), 'v4 identity/order/provenance')
 return parse_wire(bank, p['sprite_ids'], p['animations'], p['referenced_base_sprite_ids'])

def normalize_step(raw,load_anm):
 require(file_spec(STEP_SOURCE_PATH,raw)=={'path':STEP_SOURCE_PATH,'bytes':SOURCE_PINS[STEP_SOURCE_PATH][0],'sha256':SOURCE_PINS[STEP_SOURCE_PATH][1]},'original Step source pin')
 frames,records=load_anm(raw)
 require(len(frames)==50 and len(records)==1300,'original Step extent')
 out=struct.pack('<48sII',STEP_NAME.encode('ascii'),50,1300)+b''.join(struct.pack('<II',*q) for q in frames)
 for q in records:
  out+=RECORD.pack(q[0] if q[0]>3 else -1,{8:1,9:2}.get(q[15],0),*q[1:7],*(max(-32768,min(32767,int(v)))for v in q[7:15]))
 require(len(out)==STEP_BYTES and sha(out)==STEP_SHA,'original Step normalized fingerprint')
 return out

def append_bank(base,old,additions,step_animation=None):
 """Preserve old83 sprite entries and old17 animation prefix verbatim."""
 require(len(additions)==15 and tuple(row[0] for row in additions)==APPENDED_IDS,'exact15 append order')
 require(type(step_animation) is bytes and len(step_animation)==STEP_BYTES and sha(step_animation)==STEP_SHA,'exact original R35 Step block')
 chunks=[];observations=[]
 for (sid,width,height,pixels),spec in zip(additions,ADDITIONS):
  require((sid,width,height)==(spec[0],spec[2],spec[3]) and len(pixels)==width*height*4,'new sourcebitmap dimensions/extent')
  payload=zlib.compress(pixels,6);entry=struct.pack('<iHHI',sid,width,height,len(payload))+payload
  chunks.append(entry);observations.append({'id':sid,'width':width,'height':height,'rgba_sha256':sha(pixels),'entry_sha256':sha(entry),'entry_bytes':len(entry)})
 cut=old['sprite_end'];prefix=cut+sum(map(len,chunks))
 result=struct.pack('<4sIII',b'WCP1',1,98,18)+base[16:cut]+b''.join(chunks)+base[cut:]+step_animation
 require(result[16:cut]==base[16:cut] and result[prefix:prefix+len(base)-cut]==base[cut:],'v4 byte preservation')
 return result,observations

def write_new(path, data):
 with Path(path).open('xb') as stream:
  stream.write(data); stream.flush(); os.fsync(stream.fileno())

def json_bytes(value):
 return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')

# Inserted into the public standalone helper; not an independently imported module.
def _schema_object(value, keys, message):
 require(type(value) is dict and set(value) == set(keys), message)

def _schema_spec(row, path, low, high, message):
 _schema_object(row, ('path', 'bytes', 'sha256'), message + ' fields')
 require(type(row['path']) is str and row['path'] == path, message + ' path')
 exact_int(row['bytes'], low, high, message + ' size')
 pin(row['sha256'])
 return row

def validate_expected(expected, *, base_expected=None, base_manifest_sha256=None):
 """Complete finite v5 approval schema, independent of opening an APK.

 Fingerprints identify the reviewed immutable17-file/15-bitmap resource family.
 They are not a signature/authentication claim, nor embedded source image bytes.
 A generator row describes the independently reviewed historical producer; it
 need not identify this running verifier's current file after later hardening.
 """
 _schema_object(expected, ('schema','category','profile_version','format','format_version',
                          'files','generator','provenance'), 'v5 expected fields')
 require(expected['schema'] == SCHEMA and expected['category'] == 'ghost-ui' and
         expected['format'] == 'WCP1', 'v5 expected identity')
 exact_int(expected['profile_version'], 5, 5, 'v5 profile version type/value')
 exact_int(expected['format_version'], 1, 1, 'v5 wire version type/value')
 require(type(expected['files']) is list and len(expected['files']) == 2, 'v5 exact file count')
 bank = _schema_spec(expected['files'][0], BANK_PATH, 16, MAX_BANK, 'v5 bank')
 index = _schema_spec(expected['files'][1], INDEX_PATH, 1, 512, 'v5 index')
 index_bytes = INDEX_MAGIC + ('ghost-ui.bin\t%d\t%s\n' % (bank['bytes'],bank['sha256'])).encode('ascii')
 require(index == file_spec(INDEX_PATH,index_bytes), 'v5 exact derived index')
 _schema_spec(expected['generator'],'tools/ranking_ui_v5.py',1,256*1024,'v5 generator')
 p = expected['provenance']
 keys = ('algorithm','authority','publication_authority','source_main_sha256','current_converter_menu',
         'base_v4','current_menu_metadata_sha256','sprite_count','animation_count','sprite_ids',
         'appended_sprite_ids','referenced_base_sprite_ids','animations','preserved_v4_sprite_entries_sha256',
         'preserved_v4_animation_tail_sha256','preserved_v4_animation_tail_bytes','original_read_set',
         'appended_sourcebitmaps','extra_rgba_bytes','no_fonts_or_portraits','wire_version','appended_animation')
 _schema_object(p, keys, 'v5 exact provenance fields')
 require(p['algorithm'] == '3dxplus-cpu-original-ranking-extension-v1' and
         p['authority'] == 'static-sourcebitmap preservation; not APK approval or runtime equivalence' and
         p['publication_authority'] is False and p['no_fonts_or_portraits'] is True and
         p['source_main_sha256'] == MAIN_SHA, 'v5 static source authority')
 for key, value in (('sprite_count',98),('animation_count',18),('extra_rgba_bytes',102400),('wire_version',1)):
  exact_int(p[key],value,value,'v5 '+key+' type/value')
 menu = p['current_converter_menu']
 _schema_object(menu,('sha256','bytes','sprite_count','animation_count'),'v5 current menu fields')
 require(menu['sha256'] == CURRENT_MENU_SHA, 'v5 current c5eff menu pin')
 for key,value in (('bytes',CURRENT_MENU_BYTES),('sprite_count',10611),('animation_count',308)):
  exact_int(menu[key],value,value,'v5 current menu '+key)
 pin(p['current_menu_metadata_sha256'])
 b = p['base_v4']
 _schema_object(b,('schema','expected_manifest_sha256','files','sprite_count','animation_count'),'v5 base-v4 fields')
 require(b['schema'] == 'project-cinder-ghost-ui-v4','v5 base-v4 schema')
 pin(b['expected_manifest_sha256'])
 if base_manifest_sha256 is not None:
  require(b['expected_manifest_sha256'] == pin(base_manifest_sha256),'v5 independent base-v4 manifest pin')
 exact_int(b['sprite_count'],83,83,'v5 base-v4 sprite count')
 exact_int(b['animation_count'],17,17,'v5 base-v4 animation count')
 require(type(b['files']) is list and len(b['files']) == 2,'v5 base-v4 file count')
 bs = _schema_spec(b['files'][0],BANK_PATH,16,MAX_BANK,'v5 base-v4 bank')
 bi = _schema_spec(b['files'][1],'assets/ghost-ui-index-v1.tsv',1,512,'v5 base-v4 index')
 old_index = b'WMMT-GHOST-UI-1\n' + ('ghost-ui.bin\t%d\t%s\n' % (bs['bytes'],bs['sha256'])).encode('ascii')
 require(bi == file_spec('assets/ghost-ui-index-v1.tsv',old_index),'v5 exact base-v4 index')
 ids = p['sprite_ids'];refs = p['referenced_base_sprite_ids']
 require(type(ids) is list and len(ids) == 98 and type(refs) is list and 0 < len(refs) <= 65535,
         'v5 sprite/base-reference lists')
 for value in ids+refs:exact_int(value,0,2147483647,'v5 original sprite ID type/value')
 require(len(set(ids)) == 98 and ids[:83] == sorted(set(ids[:83])) and
         ids[83:] == list(APPENDED_IDS) and refs == sorted(set(refs)) and
         set(ids).isdisjoint(refs),'v5 explicit append/reference order')
 require(type(p['appended_sprite_ids']) is list and len(p['appended_sprite_ids']) == 15,
         'v5 appended ID list')
 for value in p['appended_sprite_ids']:exact_int(value,0,2147483647,'v5 appended ID type')
 require(p['appended_sprite_ids'] == list(APPENDED_IDS),'v5 exact appended ID order')
 animations = p['animations']
 require(type(animations) is list and len(animations) == 18,'v5 finite animation list')
 for row,name in zip(animations,ANIMS):
  _schema_object(row,('name','frames','records'),'v5 animation fields')
  require(row['name'] == name,'v5 original animation identity/order')
  exact_int(row['frames'],1,10000,'v5 animation frame type/budget')
  exact_int(row['records'],0,200000,'v5 animation record type/budget')
 for key in ('preserved_v4_sprite_entries_sha256','preserved_v4_animation_tail_sha256'):pin(p[key])
 exact_int(p['preserved_v4_animation_tail_bytes'],1,MAX_BANK,'v5 preserved animation byte count')
 reads = p['original_read_set']
 require(type(reads) is list and len(reads) == 17,'v5 exact original17-file read-set')
 require(all(type(row) is dict and set(row) == {'path','bytes','sha256'} for row in reads),
         'v5 read-set row fields')
 require([row['path'] for row in reads] == sorted(SOURCE_PINS),'v5 exact sorted original source paths')
 source_by_path = {}
 for row in reads:
  size,digest = SOURCE_PINS[row['path']]
  _schema_spec(row,row['path'],size,size,'v5 pinned original source')
  require(row['sha256'] == digest,'v5 pinned original source SHA256')
  source_by_path[row['path']] = row
 bitmaps = p['appended_sourcebitmaps']
 require(type(bitmaps) is list and len(bitmaps) == 15,'v5 exact15 bitmap observations')
 for row,(sid,filename,w,h) in zip(bitmaps,ADDITIONS):
  _schema_object(row,('id','width','height','rgba_sha256','entry_sha256','entry_bytes','source'),
                 'v5 bitmap observation fields')
  for key,value in (('id',sid),('width',w),('height',h)):
   exact_int(row[key],value,value,'v5 bitmap '+key+' type/value')
  raw = w*h*4
  exact_int(row['entry_bytes'],13,12+raw+((raw+16382)//16383)*5+6,'v5 bitmap entry extent')
  pin(row['entry_sha256']);pin(row['rgba_sha256'])
  require(row['rgba_sha256'] == SOURCE_RGBA[sid],'v5 exact original RGBA fingerprint')
  path = 'data/sprite/'+filename
  _schema_spec(row['source'],path,SOURCE_PINS[path][0],SOURCE_PINS[path][0],'v5 bitmap source')
  require(row['source'] == source_by_path[path],'v5 bitmap/source read-set contradiction')
 step=p['appended_animation']
 _schema_object(step,('name','frames','records','source','normalized_bytes','normalized_sha256'),'v5 Step observation fields')
 require({k:step[k] for k in ('name','frames','records')}==STEP_SPEC and animations[-1]==STEP_SPEC,'v5 Step identity')
 exact_int(step['frames'],50,50,'v5 Step frame type/value');exact_int(step['records'],1300,1300,'v5 Step record type/value')
 exact_int(step['normalized_bytes'],STEP_BYTES,STEP_BYTES,'v5 Step normalized bytes')
 require(step['normalized_sha256']==STEP_SHA and step['source']==source_by_path[STEP_SOURCE_PATH],'v5 exact Step/source fingerprint')
 if base_expected is not None:
  require(type(base_expected) is dict and b['schema'] == base_expected['schema'] and
          b['files'] == base_expected['files'],'v5 independent base-v4 files/schema')
  old = base_expected['provenance']
  require(ids[:83] == old['sprite_ids'] and animations[:17] == old['animations'] and
          refs == sorted(set(old['referenced_base_sprite_ids'])|(set(STEP_IDS)-set(ids))),'v5 independent old83/17/reference identity')
 return p


def build(args):
 expected, expected_raw = read_json(args.base_expected, args.expected_v4_manifest_sha256)
 menu, menu_raw = read_json(args.current_menu_metadata, args.expected_current_menu_metadata_sha256)
 bank = read_regular(args.base_bank, MAX_BANK)
 index = read_regular(args.base_index, 512)
 old = check_v4(expected, bank, index)
 mp = menu['menu']
 require(mp['sha256'] == CURRENT_MENU_SHA and mp['bytes'] == CURRENT_MENU_BYTES and
         mp['sprite_count'] == 10611 and mp['animation_count'] == 308, 'not current converter menu identity')
 existing = {int(k) for k in menu['sprites']}
 require(len(existing) == 10611 and set(APPENDED_IDS).isdisjoint(existing) and
         set(APPENDED_IDS).isdisjoint(expected['provenance']['sprite_ids']), 'appended IDs overwrite existing resources')
 tools = Path(args.tools_root).resolve(strict=True)
 require((tools / 'original_convert/menu_support.py').is_file(), 'caller-selected trusted converter tools root missing')
 sys.path.insert(0, str(tools))
 support_mod = importlib.import_module('original_convert.menu_support')
 component_mod = importlib.import_module('original_convert.menu_components')
 root = Path(args.source_root).resolve(strict=True)
 reads = {}
 allowed = {'main',STEP_SOURCE_PATH} | {'data/sprite/' + row[1] for row in ADDITIONS}
 def read(name, *, max_bytes=MAX_SOURCE, **_ignored):
  require(name in allowed, 'unreviewed original read path')
  path = root / name
  require(root in path.resolve(strict=True).parents, 'original path escape')
  data = read_regular(path, min(max_bytes, MAX_SOURCE))
  observation = file_spec(name, data)
  require(name not in reads or reads[name] == observation, 'original changed between reads')
  reads[name] = observation
  return data
 raw_main = read('main')
 require(sha(raw_main) == MAIN_SHA, 'original main SHA256')
 support = support_mod.OriginalSupport(raw_main)
 renderer = component_mod.SpriteRenderer(support, read)
 additions = []
 for sid, filename, width, height in ADDITIONS:
  sprite = support.sprites[sid]
  require(sprite.path == 'data/sprite/' + filename and
          (sprite.width, sprite.height) == (width, height), 'original ID/path/table dimensions')
  image = renderer.sprite(sid, table_size=True)
  require(image.mode == 'RGBA' and image.size == (width, height), 'decoded original dimensions/mode')
  additions.append((sid, width, height, image.tobytes()))
 step_raw=read(STEP_SOURCE_PATH);step=normalize_step(step_raw,component_mod.load_anm)
 result, added = append_bank(bank, old, additions,step)
 ids = expected['provenance']['sprite_ids'] + list(APPENDED_IDS)
 animations=expected['provenance']['animations']+[dict(STEP_SPEC)]
 refs=sorted(set(expected['provenance']['referenced_base_sprite_ids'])|(set(STEP_IDS)-set(ids)))
 require(set(STEP_IDS)<=existing|set(ids),'Step references absent from current menu/new bank')
 checked = parse_wire(result, ids, animations, refs)
 for row, source in zip(added, ADDITIONS):
  row['source'] = reads['data/sprite/' + source[1]]
 require(checked['sprites'][:83] == old['sprites'], 'old83 sprite metadata/offsets changed')
 require(sha(result[checked['sprite_end']:checked['sprite_end']+old['animation_tail_bytes']]) == old['animation_tail_sha256'], 'old17 animation prefix changed')
 new_index = encode_index(result)
 generator = read_regular(__file__, 256 * 1024)
 p = {'algorithm': '3dxplus-cpu-original-ranking-extension-v1',
      'authority': 'static-sourcebitmap preservation; not APK approval or runtime equivalence',
      'publication_authority': False, 'source_main_sha256': MAIN_SHA,
      'current_converter_menu': {k: mp[k] for k in ('sha256', 'bytes', 'sprite_count', 'animation_count')},
      'base_v4': {'schema': expected['schema'], 'expected_manifest_sha256': sha(expected_raw),
                  'files': expected['files'], 'sprite_count': 83, 'animation_count': 17},
      'current_menu_metadata_sha256': sha(menu_raw), 'sprite_count': 98, 'animation_count': 18,
      'sprite_ids': ids, 'appended_sprite_ids': list(APPENDED_IDS),
      'referenced_base_sprite_ids': refs,
      'animations': animations,
       'appended_animation': dict(STEP_SPEC,source=reads[STEP_SOURCE_PATH],normalized_bytes=STEP_BYTES,normalized_sha256=STEP_SHA),
      'preserved_v4_sprite_entries_sha256': old['sprite_entries_sha256'],
      'preserved_v4_animation_tail_sha256': old['animation_tail_sha256'],
      'preserved_v4_animation_tail_bytes': old['animation_tail_bytes'],
      'original_read_set': sorted(reads.values(), key=lambda row: row['path']),
      'appended_sourcebitmaps': added, 'extra_rgba_bytes': sum(w*h*4 for _, w, h, _ in additions),
      'no_fonts_or_portraits': True, 'wire_version': 1}
 manifest = {'schema': SCHEMA, 'category': 'ghost-ui', 'profile_version': 5,
             'format': 'WCP1', 'format_version': 1,
             'files': [file_spec(BANK_PATH, result), file_spec(INDEX_PATH, new_index)],
             'generator': file_spec('tools/ranking_ui_v5.py', generator), 'provenance': p}
 verify(result, new_index, manifest, base=bank, base_expected=expected, base_manifest_sha256=sha(expected_raw))
 out = Path(args.output_directory)
 require(out.parent.is_dir() and not out.exists(), 'output must be a new directory under an existing parent')
 out.mkdir(exist_ok=False)
 (out / 'assets').mkdir()
 write_new(out / BANK_PATH, result)
 write_new(out / INDEX_PATH, new_index)
 write_new(out / 'expected-arcade-ui-v5.json', json_bytes(manifest))
 receipt = {'schema': 'arcade-ui-v5-build-observation-v1', 'bank': file_spec(BANK_PATH, result),
            'index': file_spec(INDEX_PATH, new_index), 'expected_manifest_sha256': sha(json_bytes(manifest)),
            'sprites': 98, 'animations': 18, 'extra_rgba_bytes': p['extra_rgba_bytes'],
            'old83_sprite_bytes_identical': True, 'old17_animation_bytes_identical': True,
            'publication_authority': False, 'GPU_used': False, 'original_or_lua_executed': False}
 write_new(out / 'receipt.json', json_bytes(receipt))
 return receipt

def verify(bank, index, expected, *, base=None, base_expected=None, base_manifest_sha256=None):
 validate_expected(expected,base_expected=base_expected,base_manifest_sha256=base_manifest_sha256)
 require(set(expected) == {'schema', 'category', 'profile_version', 'format', 'format_version', 'files', 'generator', 'provenance'} and
         expected['schema'] == SCHEMA and expected['category'] == 'ghost-ui' and
         expected['profile_version'] == 5 and expected['format'] == 'WCP1' and expected['format_version'] == 1, 'explicit v5 schema')
 require(expected['files'] == [file_spec(BANK_PATH, bank), file_spec(INDEX_PATH, index)] and index == encode_index(bank), 'v5 bank/index pin')
 p = expected['provenance']
 require(p['source_main_sha256'] == MAIN_SHA and p['publication_authority'] is False and
         p['sprite_count'] == 98 and p['animation_count'] == 18 and
         p['appended_sprite_ids'] == list(APPENDED_IDS) and len(p['sprite_ids']) == 98 and
         p['sprite_ids'][83:] == list(APPENDED_IDS) and
         tuple(row['name'] for row in p['animations']) == ANIMS and p['extra_rgba_bytes'] == 102400,
         'v5 finite source/ID/count contract')
 checked = parse_wire(bank, p['sprite_ids'], p['animations'], p['referenced_base_sprite_ids'])
 require(len(p['appended_sourcebitmaps']) == 15, 'v5 appended observations')
 for row, original, spec in zip(checked['sprites'][83:], p['appended_sourcebitmaps'], ADDITIONS):
  sid, filename, w, h = spec
  require(row['id'] == original['id'] == sid and row['width'] == original['width'] == w and
          row['height'] == original['height'] == h and row['rgba_sha256'] == original['rgba_sha256'] and
          row['entry_sha256'] == original['entry_sha256'] and row['entry_bytes'] == original['entry_bytes'] and
          original['source']['path'] == 'data/sprite/' + filename, 'v5 appended sourcebitmap mismatch')
 if base is not None:
  require(base_expected is not None, 'base expected manifest required for preservation verification')
  base_index = b'WMMT-GHOST-UI-1\n' + ('ghost-ui.bin\t%d\t%s\n' % (len(base), sha(base))).encode('ascii')
  old = check_v4(base_expected, base, base_index)
  require(p['sprite_ids'][:83] == base_expected['provenance']['sprite_ids'] and
          p['animations'][:17] == base_expected['provenance']['animations'] and
          bank[16:old['sprite_end']] == base[16:old['sprite_end']] and
          bank[checked['sprite_end']:checked['sprite_end']+old['animation_tail_bytes']] == base[old['sprite_end']:] and
          p['preserved_v4_sprite_entries_sha256'] == old['sprite_entries_sha256'] and
          p['preserved_v4_animation_tail_sha256'] == old['animation_tail_sha256'] and
          p['preserved_v4_animation_tail_bytes'] == old['animation_tail_bytes'], 'v4 byte preservation failed')
 require(checked['animation_blocks'][-1]['bytes']==STEP_BYTES and checked['animation_blocks'][-1]['sha256']==STEP_SHA,'v5 exact serialized original Step ANM')
 return {'sprites': 98, 'animations': 18, 'expanded_rgba_bytes': checked['expanded_rgba_bytes'],
         'preservation_compared': base is not None, 'publication_authority': False}

def main():
 parser = argparse.ArgumentParser(description=__doc__)
 commands = parser.add_subparsers(dest='command', required=True)
 builder = commands.add_parser('build')
 for name in ('source-root', 'tools-root', 'base-bank', 'base-index', 'base-expected',
              'current-menu-metadata', 'output-directory'):
  builder.add_argument('--' + name, type=Path, required=True)
 builder.add_argument('--expected-v4-manifest-sha256', required=True)
 builder.add_argument('--expected-current-menu-metadata-sha256', required=True)
 checker = commands.add_parser('verify')
 for name in ('bank', 'index', 'expected', 'base-bank', 'base-expected'):
  checker.add_argument('--' + name, type=Path, required=True)
 checker.add_argument('--expected-manifest-sha256', required=True)
 checker.add_argument('--expected-v4-manifest-sha256', required=True)
 args = parser.parse_args()
 if args.command == 'build':
  result = build(args)
 else:
  expected, _ = read_json(args.expected, args.expected_manifest_sha256)
  base_expected, base_raw = read_json(args.base_expected, args.expected_v4_manifest_sha256)
  result = verify(read_regular(args.bank, MAX_BANK), read_regular(args.index, 512), expected,
                  base=read_regular(args.base_bank, MAX_BANK), base_expected=base_expected,
                  base_manifest_sha256=sha(base_raw))
 print(json.dumps(result, sort_keys=True))

if __name__ == '__main__':
 main()
