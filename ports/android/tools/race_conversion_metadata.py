"""Independent race conversion metadata contract; no converter/target imports.
Reference is a reviewed side-input, never learned from candidate APK bytes.
"""
import ast
import base64
import hashlib
import io
import json
import re
import unicodedata
import zlib
from resource_pack_common import StrictZip, regular_input, require

ID = 'wmmt-main2e-source16-fma2-avc1-135-race-restoration1'
MAIN = '2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
PRIOR_PROFILE = 'd33ba32c55d030a367aeb9561d95523ca8841904549a39719c4f05dbdbe586a5'
PLAYER_PLAN = '6c15a562225a51d5a0ebe2ef44c9004dc9f408fa37b8a945177318ad55ac6b65'
PLAYER_BANK = 'afaacb5b1b9a149c8ec78f32a1ff89da1173b9be99193fa0040ff693df498594'
SMOKE_SHA = '5a0a2d31d64583fc2dd7a8cda2bc81f9bdf80ae07cdad3981d0409ea11748e92'
SMOKE_PIXEL = 'b5efd85e0bad26dfc6c48a59a19a0fd9e02c1206af6646d4f427df0535f6e108'
SMOKE_SOURCES = [
    {'path':'data/effect_config.lua','bytes':2602,'sha256':'b372fd1da5c8368a6cd0b405b0b80a8d99f57f00f15d4ec9bb94299820b811ca'},
    {'path':'data/sprite/tiresmoke_all.tga','bytes':262188,'sha256':'6c0683e00b69404c3bab8eba22f4f89e93312fa02343e2f47c016bb900fe18f2'},
]
HEIGHT_SOURCE = {'path':'data/car_height.lua','bytes':5875,'sha256':'8892314496a325c6b5b9be0ee619461e91028f45aba0000966ad77938ac574a4'}
HEIGHT_PLAN_SHA256 = '1fcd89261ea91e8d383cb90a57f840019b245384e4506ba12ac0ef7b0bbbaba7'
HEIGHT_HEADER_SHA256 = '4155db364fe9fe361fd5607e282db291324c7a64661b96b87aa1eb13dc42e697'
AO_IMAGE_SHA256 = 'b730592c4e68407c281bc02c1863d3a4b12406dfa3af144b0c5c92d8e058b7a9'
MAX_JSON = 8*1024**2
HASH = re.compile(r'[0-9a-f]{64}\Z')
# Frozen only after parent relays the final story resource delta and source APIs.
REVIEWED_MANIFEST_SHA256 = 'faf0509235412fd74c1df98e3bbbc6c8ffbdc9bc34f8d574461bdff52a64876f'
REVIEWED_MANIFEST_061_SHA256 = '8932df7bfa8cbb7c9ef43f9349722fa02db0461e9b22d37c5715ddc0adc91332'
REVIEWED_MANIFEST_062_SHA256 = 'a620e6b590ec24df5579763d3b63d3bf9b7eb00b1fd7472926ed707b1561fa08'
REVIEWED_MANIFEST_063_SHA256 = '4800b07ad27319250243e30c2eb5eb6bedee6f18c8e92ee22e110b36ee7b3bf4'
REVIEWED_MANIFEST_064_SHA256 = 'abce2d8e4a8224934281f702f4f05213741165a2d1accd74b6a0f69bcf1151aa'


def H(raw): return hashlib.sha256(raw).hexdigest()
def canonical(v): return (json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
def pairs(rows):
    out = {}
    for key,value in rows:
        require(key not in out, 'duplicate JSON member');out[key]=value
    return out
def decode(raw):
    require(type(raw)is bytes and 0<len(raw)<=MAX_JSON,'metadata budget')
    v=json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    require(canonical(v)==raw,'noncanonical JSON');return v

def roster(rows,fields,*,source=False):
    require(type(rows)is list and 0<len(rows)<=16384,'roster count')
    result={};folded=set();last=''
    for row in rows:
        require(type(row)is dict and set(row)==set(fields),'roster row shape')
        name=row['path']
        require(type(name)is str and name>last and len(name)<=4096 and
            name==unicodedata.normalize('NFC',name) and '\\'not in name and ':'not in name and
            not any(unicodedata.category(c).startswith('C')for c in name)and
            all(p and p not in ('.','..')and p[-1]not in ' .'for p in name.split('/')),'unsafe/unsorted path')
        require(name.casefold()not in folded,'case-aliased path')
        if source:require(name=='main'or name.startswith('data/'),'source namespace')
        size=row.get('bytes',row.get('max_bytes'));digest=row['sha256']
        require(type(size)is int and 0<=size<=512*1024**2,'row byte bound')
        require(type(digest)is str and HASH.fullmatch(digest)or digest is None and row.get('kind')in('ao','m4a','mp4'),'row hash authority')
        result[name]=row;folded.add(name.casefold());last=name
    for name in result:
        parts=name.split('/');require(not any('/'.join(parts[:i]).casefold()in folded for i in range(1,len(parts))),'file/directory alias')
    return result

def smoke_plan():
    return {'schema':'TSM1-original-image708-plan-v1','source_files':SMOKE_SOURCES,
        'image_id':708,'width':256,'height':256,'pixel_format':'bottom-up-straight-RGBA8',
        'pixel_bytes':262144,'pixel_sha256':SMOKE_PIXEL,'pixel_crc32':1929019831,
        'output':{'path':'tiresmoke.bin','bytes':262160,'sha256':SMOKE_SHA}}

def load_reference(path, *, cinder_061=False, cinder_062=False, cinder_063=False, cinder_064=False):
    require(sum((cinder_061, cinder_062, cinder_063, cinder_064))<=1, 'choose one reviewed race conversion manifest')
    expected = (
        REVIEWED_MANIFEST_064_SHA256 if cinder_064 else
        REVIEWED_MANIFEST_063_SHA256 if cinder_063 else
        REVIEWED_MANIFEST_062_SHA256 if cinder_062 else
        REVIEWED_MANIFEST_061_SHA256 if cinder_061 else
        REVIEWED_MANIFEST_SHA256
    )
    require(expected is not None,'race manifest not frozen; parent story delta required')
    with regular_input(path,MAX_JSON)as source:raw=source.read(MAX_JSON+1)
    require(H(raw)==expected,'not the independent reviewed race conversion manifest')
    v=decode(raw)
    require(set(v)=={'schema','profile_id','profile_sha256','readset_sha256','recipe_sha256',
        'source_count','output_count','raw_count','previous_profile_sha256','app_sources',
        'smoke_plan_sha256','story_delta_sha256','story_height_plan_sha256','story_height_header_sha256'}and v['schema']=='project-cinder-race-conversion-v1'and
        v['profile_id']==ID and v['previous_profile_sha256']==PRIOR_PROFILE and v['raw_count']==1030,
        'race conversion manifest schema')
    for key in ('profile_sha256','readset_sha256','recipe_sha256','smoke_plan_sha256','story_delta_sha256','story_height_plan_sha256','story_height_header_sha256'):
        require(type(v[key])is str and HASH.fullmatch(v[key]),'manifest pin syntax')
    require(type(v['source_count'])is int and v['source_count']==13994 and
        type(v['output_count'])is int and v['output_count']==1801,'manifest exact successor inventory')
    require(v['story_height_plan_sha256']==HEIGHT_PLAN_SHA256 and v['story_height_header_sha256']==HEIGHT_HEADER_SHA256,'reviewed height source/table authority')
    app=roster(v['app_sources'],('path','bytes','sha256'))
    require('original_convert/smoke.py'in app and all(n.endswith('.py')and n.startswith(('original_convert/','stage/'))for n in app),'code-only source closure')
    return v,H(raw)

def inspect(profile,app,reference):
    pins={k:reference[k]for k in ('profile_id','profile_sha256','readset_sha256','recipe_sha256')}
    require(H(profile)==pins['profile_sha256'],'APK successor original profile pin')
    with StrictZip(io.BytesIO(app),max_bytes=32*1024**2,max_entries=512,max_total=32*1024**2,max_file=MAX_JSON)as nested:
        expected=roster(reference['app_sources'],('path','bytes','sha256'))
        require(set(nested.files)==set(expected),'nested exact reviewed code-only source inventory')
        text=nested.read('original_convert/release_assets.py',MAX_JSON);values={}
        for node in ast.parse(text,filename='APK/release_assets.py').body:
            if isinstance(node,ast.Assign)and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)and node.targets[0].id in ('PINS','READSET_B64','RECIPE_B64'):
                name=node.targets[0].id;require(name not in values,'duplicate release metadata assignment');values[name]=ast.literal_eval(node.value)
        require(set(values)=={'PINS','READSET_B64','RECIPE_B64'}and values['PINS']==pins,'APK Python release pins')
        decoded={}
        for name,key in (('readset','READSET_B64'),('recipe','RECIPE_B64')):
            require(type(values[key])is str and len(values[key])<=MAX_JSON,'compressed metadata budget')
            d=zlib.decompressobj();raw=d.decompress(base64.b64decode(values[key],validate=True),MAX_JSON+1)
            require(len(raw)<=MAX_JSON and d.eof and not d.unused_data and not d.unconsumed_tail and H(raw)==pins[name+'_sha256'],'decoded metadata extent/pin')
            decoded[name]=decode(raw)
        read,recipe=decoded['readset'],decoded['recipe']
        require(set(read)=={'schema','main_sha256','files'}and read['schema']=='wmmt-original-readset-v1'and read['main_sha256']==MAIN,'readset schema')
        src=roster(read['files'],('path','bytes','sha256'),source=True)
        require(len(src)==reference['source_count']and src['main']=={'path':'main','bytes':24855892,'sha256':MAIN},'exact source count/main')
        require(set(recipe)=={'schema','profile_id','runtime','native','raw','wheels','cars','extras','media','outputs','route_arrow_order','player_paints','player_paints_plan_sha256','smoke','smoke_plan_sha256'}and
            recipe['schema']=='wmmt-original-race-recipe-v1'and recipe['profile_id']==ID,'successor recipe schema')
        outputs={};last=''
        for r in recipe['outputs']:
            require(type(r)is dict and {'path','max_bytes','sha256','kind'}<=set(r)<={'path','max_bytes','sha256','kind','ao_layout'},'output shape')
            outputs[r['path']]=r
        roster([{k:r[k]for k in ('path','max_bytes','sha256','kind')}for r in recipe['outputs']],('path','max_bytes','sha256','kind'))
        require(len(outputs)==reference['output_count']and len(recipe['raw'])==reference['raw_count']and recipe['route_arrow_order']is True,'exact output/raw/route closure')
        require(recipe['smoke']==smoke_plan()and recipe['smoke_plan_sha256']==reference['smoke_plan_sha256']==H(canonical(smoke_plan())),'lossless smoke literal plan')
        for r in SMOKE_SOURCES:require(src.get(r['path'])==r,'smoke source closure')
        require(src.get(HEIGHT_SOURCE['path'])==HEIGHT_SOURCE,'height source closure')
        height=recipe['cars'].get('story_height')
        require(recipe['cars'].get('story_assembly')is True and type(height)is dict and
            H(canonical(height))==HEIGHT_PLAN_SHA256==reference['story_height_plan_sha256'] and
            height['source_files']==[HEIGHT_SOURCE]and height['compiled_header_sha256']==HEIGHT_HEADER_SHA256==reference['story_height_header_sha256']and
            len(height['rows'])==55,'explicit original height/assembly plan')
        require(recipe['native']=={'liboa_native.so':AO_IMAGE_SHA256,'liboc_media_overlay.so':'2e88baa7d461622f43a66b181a141d5c8f7f8bdb131e60940575e642f27888aa'},'strict successor native converter pins')
        require(outputs.get('tiresmoke.bin')=={'path':'tiresmoke.bin','max_bytes':262160,'sha256':SMOKE_SHA,'kind':'fixed'},'smoke MAIN binding')
        p=recipe['player_paints']
        require(recipe['player_paints_plan_sha256']==PLAYER_PLAN==H(canonical(p))and p['bank_sha256']==PLAYER_BANK and p['bank_bytes']==116728834,'sorted player paint bank must be preserved')
        require(outputs.get('player-body-paints.bin')=={'path':'player-body-paints.bin','max_bytes':116728834,'sha256':PLAYER_BANK,'kind':'fixed'},'player MAIN binding')
        lines=['WMMT-ORIGINAL-PROFILE-1','profileId\t'+ID,'readsetSha256\t'+pins['readset_sha256'],'recipeSha256\t'+pins['recipe_sha256']]
        lines+=['src\t%s\t%d\t%s'%(r['path'],r['bytes'],r['sha256'])for r in read['files']]
        lines+=['out\t%s\t%d\t%s\t%s'%(r['path'],r['max_bytes'],r['sha256']or'-',r['kind'])for r in recipe['outputs']]
        require(('\n'.join(lines+['END',''])).encode()==profile,'exact JSON/profile TSV closure')
        for name,row in expected.items():
            blob=nested.read(name,MAX_JSON);require(len(blob)==row['bytes']and H(blob)==row['sha256'],'nested source bytes differ: '+name)
    return {**pins,'sources':len(src),'outputs':len(outputs),'raw':len(recipe['raw']),
        'nested_python_source_files':len(expected),'lossless_smoke_MAIN_only':True,'sorted_player_bank_preserved':True}
