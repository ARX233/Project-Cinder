#!/usr/bin/env python3
"""Strict explicit vehicle-restoration/UI-v6 APK metadata profile, offline.

Eleven independent reviewed references are mandatory. This reads the ACTUAL APK,
not a virtual/rewritten v5 candidate. Existing v5/legacy verifiers are untouched.
APK signature crypto, signer identity, JNI/DEX/ELF ABI, FMA/physics-object proofs,
zipalign and Android/GPU execution remain separate release gates.
"""
import argparse,ast,base64,hashlib,io,json,struct,sys,zipfile,zlib
from pathlib import Path
sys.dont_write_bytecode=True
from resource_pack_common import (Entry,KNOWN_BASELINES,MAX_CATALOG,MAX_INDEX,TOP4,
    ResourceError,StrictZip,load_catalog,parse_sidecars,regular_input,require,sha256)
from verify_original_convert_apk import runtime_inventory
from verify_resource_free_apk import (REQUIRED_FILES,ALLOWED_ASSETS,SIGNER,
    signature_text,signature_der,expected_digest,MAX_SIGNATURE)
from verify_cinder_apk import launcher_inventory,WALLPAPER
from builtin_data_v2_common import expected_manifest,encode_index,inspect_pack,BANK,INDEX
import ranking_ui_v5 as v5
import vehicle_restore_ui_v6 as v6

MAX_APK=128*1024**2;MAX_EXPANDED=256*1024**2;MAX_JSON=8*1024**2
UI_MANIFEST_SHA='74234290e7e1d439426ccdfabfc6a6a947edce45400e08dcf9eadd0bf326ca9f'
UI_BANK_SHA='c41db601a49983717b4e5824ef6b65dbe424da1b7e27037901c72edbc70bdb2d'
UI_INDEX_SHA='d848410654e8a4b02c0248d1e10c35b3745938b2e8ec793fe21a23a822682413'
UI_BANK_BYTES=7049324
DATA_SHA='ed2e3cc93e7a6e9e1d77a1c0fcd2fa50084a48ec5409a8b135113e5d8d429da1'
GHOST_PAINT_SHA='603c7d1bbf3c4daea89e683dd7a19457860aff96ec1a2c4b2ee78b3e0a3712e4'
PROFILE_ID='wmmt-main2e-source16-fma2-avc1-135-vehicle-restoration1'
PROFILE_SHA='d33ba32c55d030a367aeb9561d95523ca8841904549a39719c4f05dbdbe586a5'
READSET_SHA='1e3c4a1c461a6073a2ec06464af241ac0d7ee8be9e53f8db96776584a50fc337'
RECIPE_SHA='046aace438697ec54e6f125bb1d186ac0f0c3fbda3529fb985fe8fed8b531597'
PLAYER_PLAN_SHA='6c15a562225a51d5a0ebe2ef44c9004dc9f408fa37b8a945177318ad55ac6b65'
PLAYER_BANK_SHA='afaacb5b1b9a149c8ec78f32a1ff89da1173b9be99193fa0040ff693df498594'
PLAYER_BANK_BYTES=116728834
OLD_UI_INDEXES=frozenset(('assets/ghost-ui-index-v1.tsv','assets/arcade-ui-v5-index.tsv'))
PROFILE_PATH='assets/original-convert/profile.tsv';APP_PATH='assets/chaquopy/app.imy'

def _json(raw):
    return json.loads(raw.decode('utf-8','strict'),object_pairs_hook=v5.pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))

def _canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()

def _read_ref(path,limit):
    with regular_input(Path(path),limit) as source:
        value=source.read(limit+1)
    require(0<len(value)<=limit,'independent reference byte budget')
    return value

def _ui_references(vehicle,base_manifest,base_bank):
    raw=_read_ref(vehicle,MAX_JSON)
    require(hashlib.sha256(raw).hexdigest()==UI_MANIFEST_SHA,'not the reviewed v6 manifest')
    expected=_json(raw);p=v6.validate_expected(expected)
    require(expected['files'][0]=={'path':v6.BANK_PATH,'bytes':UI_BANK_BYTES,'sha256':UI_BANK_SHA} and
        expected['files'][1]['sha256']==UI_INDEX_SHA,'v6 release file pins differ')
    br=_read_ref(base_manifest,MAX_JSON)
    require(hashlib.sha256(br).hexdigest()==v6.BASE_MANIFEST_SHA,'not the independent reviewed base-v5 manifest')
    prior=_json(br);pp=v5.validate_expected(prior)
    base=_read_ref(base_bank,v5.MAX_BANK)
    require(hashlib.sha256(base).hexdigest()==v6.BASE_BANK_SHA and len(base)==4138347,'base-v5 bank differs from reviewed bytes')
    v5.verify(base,v5.encode_index(base),prior)
    parsed=v5.parse_wire(base,pp['sprite_ids'],pp['animations'],pp['referenced_base_sprite_ids'])
    require(p['sprite_ids'][:98]==pp['sprite_ids'] and p['animations'][:18]==pp['animations'],'v6 changes inherited IDs/ANMs')
    require(expected['provenance']['base_v5_manifest_sha256']==hashlib.sha256(br).hexdigest() and
        expected['provenance']['base_v5_bank_sha256']==hashlib.sha256(base).hexdigest(),'v6/base independent references disagree')
    entries={row['path']:Entry(row['bytes'],row['sha256']) for row in expected['files']}
    require(set(entries)=={v6.BANK_PATH,v6.INDEX_PATH},'v6 exact two-file namespace')
    return expected,entries,base,parsed

def _original_profile(profile,app):
    """Inspect signed-runtime metadata bytes without importing any APK Python."""
    require(hashlib.sha256(profile).hexdigest()==PROFILE_SHA,'APK original profile is not vehicle-restoration1')
    lines=profile.decode('utf-8','strict').splitlines()
    require(lines[:4]==['WMMT-ORIGINAL-PROFILE-1','profileId\t'+PROFILE_ID,
        'readsetSha256\t'+READSET_SHA,'recipeSha256\t'+RECIPE_SHA] and lines[-1]=='END','new original profile headers')
    require(sum(x.startswith('src\t') for x in lines)==13991 and sum(x.startswith('out\t')for x in lines)==1800,'new original profile counts')
    with StrictZip(io.BytesIO(app),max_bytes=32*1024**2,max_entries=512,max_total=32*1024**2,max_file=MAX_JSON) as nested:
        require({'original_convert/release_assets.py','original_convert/player_paints.py',
            'original_convert/player_paint_lua.py','original_convert/engine.py','original_convert/maps.py','stage/tex.py'}<=nested.files.keys(),'new original runtime modules missing')
        text=nested.read('original_convert/release_assets.py',MAX_JSON);tree=ast.parse(text,filename='APK/release_assets.py');values={}
        for node in tree.body:
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('PINS','READSET_B64','RECIPE_B64'):
                key=node.targets[0].id;require(key not in values,'duplicate release metadata assignment');values[key]=ast.literal_eval(node.value)
        require(set(values)=={'PINS','READSET_B64','RECIPE_B64'} and values['PINS']=={
            'profile_id':PROFILE_ID,'profile_sha256':PROFILE_SHA,'readset_sha256':READSET_SHA,'recipe_sha256':RECIPE_SHA},'APK Python release pins')
        decoded={}
        for key,pin in (('READSET_B64',READSET_SHA),('RECIPE_B64',RECIPE_SHA)):
            require(type(values[key])is str and len(values[key])<=MAX_JSON,'release compressed metadata budget')
            d=zlib.decompressobj();raw=d.decompress(base64.b64decode(values[key],validate=True),MAX_JSON+1)
            require(len(raw)<=MAX_JSON and d.eof and not d.unused_data and not d.unconsumed_tail and hashlib.sha256(raw).hexdigest()==pin,'APK decoded release metadata mismatch')
            decoded[key]=_json(raw)
        read,recipe=decoded['READSET_B64'],decoded['RECIPE_B64']
        require(len(read['files'])==13991 and len(recipe['outputs'])==1800 and len(recipe['raw'])==1030 and recipe['profile_id']==PROFILE_ID and recipe['route_arrow_order']is True,'new recipe closure/route activation')
        paint=recipe['player_paints'];require(recipe['player_paints_plan_sha256']==PLAYER_PLAN_SHA and
            hashlib.sha256(_canonical(paint)).hexdigest()==PLAYER_PLAN_SHA and paint['bank_sha256']==PLAYER_BANK_SHA and
            paint['bank_bytes']==PLAYER_BANK_BYTES and len(paint['records'])==6080,'new MAIN player bank recipe pin')
        target=[r for r in recipe['outputs']if r['path']=='player-body-paints.bin']
        require(target==[{'path':'player-body-paints.bin','max_bytes':PLAYER_BANK_BYTES,'kind':'fixed','sha256':PLAYER_BANK_SHA}],'new MAIN bank output binding')
        # Complete nested CRC/extent read, not selected-module-only inspection.
        for name in sorted(nested.files):nested.consume(name,limit=MAX_JSON)
    return {'profile_id':PROFILE_ID,'profile_sha256':PROFILE_SHA,'recipe_sha256':RECIPE_SHA,
        'readset_sha256':READSET_SHA,'sources':13991,'outputs':1800,'route_order_active':True,
        'player_bank_is_converted_MAIN_output_not_APK_asset':True}

def verify(path,*,runtime,baselines,sidecars,launcher,dataset,readset,paint_manifest,paint_readset,vehicle,base_ui,base_ui_bank):
    approved,data,approval_hash=expected_manifest(dataset,readset,paint_manifest,paint_readset)
    require(data[BANK].sha256==DATA_SHA and approved['paint_section']['sha256']==GHOST_PAINT_SHA,'builtin WGBANK2/paint authority changed')
    ua,ui,base,base_wire=_ui_references(vehicle,base_ui,base_ui_bank)
    inventory,ih=runtime_inventory(runtime);art,ah=launcher_inventory(launcher)
    require(inventory[PROFILE_PATH].sha256==PROFILE_SHA,'runtime reference is not the separately reviewed new original profile')
    require(not any('player-body-paints.bin'in n.split('/')for n in inventory),'MAIN player bank may not become an APK asset')
    groups=[set(inventory),set(art),set(ui),set(data)]
    require(all(a.isdisjoint(b)for i,a in enumerate(groups)for b in groups[i+1:]),'independent inventories overlap')
    cp=expected_digest(baselines,MAX_CATALOG);ip=expected_digest(sidecars,MAX_INDEX)
    require(cp is not None and ip is not None,'independent old metadata required')
    expected=set(REQUIRED_FILES)|set(ALLOWED_ASSETS)|set().union(*groups);optional={'assets/'+n for n in TOP4};dirs={'META-INF/'}
    for name in expected|optional:
        parts=name.split('/');dirs.update('/'.join(parts[:i])+'/'for i in range(1,len(parts)))
    with regular_input(Path(path).absolute(),MAX_APK) as source:
        original=sha256(source);source.seek(0,2);size=source.tell()
        with StrictZip(source,max_bytes=MAX_APK,max_entries=1024,max_total=MAX_EXPANDED,max_file=MAX_EXPANDED,apk=True) as apk:
            files=set(apk.files);require(expected<=files,'incomplete vehicle-restoration Cinder APK');signatures={}
            require(not OLD_UI_INDEXES&files,'ambiguous legacy/v5/v6 UI approval generations')
            require(not any('player-body-paints.bin'in n.split('/')for n in files),'converted MAIN bank must not be embedded in APK')
            for info in apk.zip.infolist():
                name=info.filename
                if info.is_dir():require(name in dirs,'unreviewed APK directory: '+name);continue
                require(info.file_size>0,'empty outer APK member')
                if name in expected|optional:continue
                if name=='META-INF/MANIFEST.MF':signatures[name]=None;continue
                match=SIGNER.fullmatch(name);require(match is not None,'unreviewed APK member: '+name);signatures[name]=match.groups()
            if signatures:
                require('META-INF/MANIFEST.MF'in signatures,'missing JAR public manifest');signers={}
                for name,pair in signatures.items():
                    if pair is not None:signers.setdefault(pair[0],set()).add(pair[1])
                require(signers and all('SF'in kinds and len(kinds)==2 and len(kinds&{'RSA','DSA','EC'})==1 for kinds in signers.values()),'unpaired JAR signature material')
            old_catalog=apk.read('assets/data-baselines.zip',MAX_CATALOG)
            require(hashlib.sha256(old_catalog).hexdigest()==cp,'old baseline metadata changed')
            require(load_catalog(io.BytesIO(old_catalog)).keys()==KNOWN_BASELINES,'legacy baseline set changed')
            old_index=apk.read('assets/sidecars-index-v1.tsv',MAX_INDEX)
            require(hashlib.sha256(old_index).hexdigest()==ip,'old41 metadata changed');old_rows=parse_sidecars(old_index)
            require(len(old_rows)==41,'old41 count changed')
            require(('assets/backfire.wpk'in files)==('assets/backfire.bfx'in files),'incomplete old backfire pair')
            b=apk.read(BANK,data[BANK].size);idx=apk.read(INDEX,512)
            require(len(b)==data[BANK].size and hashlib.sha256(b).hexdigest()==data[BANK].sha256,'dataset differs from independent expectation')
            require(idx==encode_index(data[BANK]) and len(idx)==data[INDEX].size and hashlib.sha256(idx).hexdigest()==data[INDEX].sha256,'dataset index contradiction')
            stats=inspect_pack(b,paint_manifest,paint_readset)
            require(stats['paint_sha256']==GHOST_PAINT_SHA,'builtin paint content changed')
            ub=apk.read(v6.BANK_PATH,ui[v6.BANK_PATH].size);ux=apk.read(v6.INDEX_PATH,512)
            ui_stats=v6.verify(ub,ux,ua)
            # Actual 98-sprite /18-animation prefix comparison with the complete
            # independently pinned base-v5 bytes, in addition to v6's hash proof.
            cut=base_wire['sprite_end'];require(ub[16:cut]==base[16:cut],'base98 sprite bytes changed')
            start=ui_stats['sprite_end'];require(ub[start:start+len(base)-cut]==base[cut:],'base18 animation bytes changed')
            require(hashlib.sha256(ux).hexdigest()==UI_INDEX_SHA,'v6 index release pin')
            profile=apk.read(PROFILE_PATH,MAX_JSON);app=apk.read(APP_PATH,32*1024**2)
            original_profile=_original_profile(profile,app)
            for name in sorted(files-set(ALLOWED_ASSETS)-set(ui)-set(data)):
                if name in art:apk.consume(name,limit=art[name].size,expected=art[name])
                elif name in inventory:apk.consume(name,limit=inventory[name].size,expected=inventory[name])
                elif name in optional:apk.consume(name,limit=old_rows[name[7:]].size,expected=old_rows[name[7:]])
                elif name=='META-INF/MANIFEST.MF':signature_text(apk.read(name,MAX_SIGNATURE),b'Manifest-Version: 1.0')
                elif name in signatures:
                    sb=apk.read(name,MAX_SIGNATURE)
                    if signatures[name][1]=='SF':signature_text(sb,b'Signature-Version: 1.0')
                    else:signature_der(sb)
                else:apk.consume(name,limit=MAX_EXPANDED)
        require(sha256(source)==original,'APK changed while verifying')
    return {'profile':'project-cinder-vehicle-restoration-v1','apk_sha256':original,'bytes':size,
        'independent_reference_count':11,'actual_complete_APK_inventory_checked':True,
        'runtime_members':len(inventory),'runtime_inventory_sha256':ih,'launcher_inventory_sha256':ah,
        'wallpaper_sha256':art[WALLPAPER].sha256,'sidecar_count':len(old_rows),
        'vehicle_ui_manifest_sha256':UI_MANIFEST_SHA,'base_v5_manifest_sha256':v6.BASE_MANIFEST_SHA,
        'vehicle_ui_bank_sha256':UI_BANK_SHA,'vehicle_ui_index_sha256':UI_INDEX_SHA,
        'vehicle_ui':{'sprites':614,'animations':20,'base98sprites_18anms_actual_byte_equal':True},
        'original_profile':original_profile,'dataset_manifest_sha256':approval_hash,'dataset_sha256':data[BANK].sha256,
        'legacy_verifiers_or_profiles_changed':False,'main_resource_embedded':False,'original_main_embedded':False,
        'crypto_signer_JNI_DEX_ELF_FMA_physics_or_alignment_verified':False,'android_or_GPU_verified':False,
        'ta_global_service_deployed':False,'compiled_defaults_used_as_recordings':False,**stats}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('apk',type=Path)
    for name in ('runtime','baselines','sidecars','launcher','builtin-data-manifest','builtin-source-readset',
            'paint-manifest','paint-source-readset','vehicle-ui-manifest','base-ui-manifest','base-ui-bank'):
        p.add_argument('--expected-'+name,type=Path,required=True)
    a=p.parse_args(argv)
    try:
        result=verify(a.apk,runtime=a.expected_runtime,baselines=a.expected_baselines,sidecars=a.expected_sidecars,
            launcher=a.expected_launcher,dataset=a.expected_builtin_data_manifest,readset=a.expected_builtin_source_readset,
            paint_manifest=a.expected_paint_manifest,paint_readset=a.expected_paint_source_readset,
            vehicle=a.expected_vehicle_ui_manifest,base_ui=a.expected_base_ui_manifest,base_ui_bank=a.expected_base_ui_bank)
    except (ResourceError,OSError,ValueError,KeyError,TypeError,RuntimeError,SyntaxError,RecursionError,struct.error,zipfile.BadZipFile,zlib.error) as exc:
        p.exit(2,'Vehicle-restoration APK refused: '+str(exc)+'\n')
    print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
