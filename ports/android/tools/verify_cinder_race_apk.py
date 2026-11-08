#!/usr/bin/env python3
"""Strict explicit race-restoration/UI-v6 APK metadata profile, offline.

Twelve independent reviewed references are mandatory. This reads the ACTUAL APK,
not a virtual/rewritten v5 candidate. Existing v5/legacy verifiers are untouched.
APK signature crypto, signer identity, JNI/DEX/ELF ABI, FMA/physics-object proofs,
zipalign and Android/GPU execution remain separate release gates.
"""
import argparse,ast,base64,hashlib,io,json,struct,sys,zipfile,zlib
from pathlib import Path
sys.dont_write_bytecode=True
from resource_pack_common import (Entry,KNOWN_BASELINES,PREPARED_BASELINE,MAX_CATALOG,MAX_INDEX,TOP4,
    ResourceError,StrictZip,load_catalog,parse_sidecars,regular_input,require,sha256)
from verify_original_convert_apk import runtime_inventory
from verify_resource_free_apk import (REQUIRED_FILES,ALLOWED_ASSETS,SIGNER,
    signature_text,signature_der,expected_digest,MAX_SIGNATURE)
from verify_cinder_apk import launcher_inventory,WALLPAPER
from builtin_data_v2_common import expected_manifest,encode_index,inspect_pack,BANK,INDEX
import ranking_ui_v5 as v5
import vehicle_restore_ui_v6 as v6
import race_conversion_metadata as race
from race_manifest_identity import identity as manifest_identity

MAX_APK=128*1024**2;MAX_EXPANDED=256*1024**2;MAX_JSON=8*1024**2
UI_MANIFEST_SHA='3749a07c2bff8f777d70990d57b2b2406787c3f746b4966ff1ad8dd9bfdfc7da'
UI_BANK_SHA='9234e227c08f870dedf799db48ee7946ea8f4fd4aeb1a4e82c22d715b3651276'
UI_INDEX_SHA='96a974355bb5b1b4223a7cb44b05506650f6dcda2b2d1e18903ec7c0c0e047f0'
UI_BANK_BYTES=7140095
DATA_SHA='ed2e3cc93e7a6e9e1d77a1c0fcd2fa50084a48ec5409a8b135113e5d8d429da1'
GHOST_PAINT_SHA='603c7d1bbf3c4daea89e683dd7a19457860aff96ec1a2c4b2ee78b3e0a3712e4'
FOLLOWUP_DATA_SHA='137e891159738a2307e20e636a1a54ab4edd9dcb34e21149de8a6c78254fd9b3'
FOLLOWUP_GHOST_PAINT_SHA='6058078340de7af4cb04fe5978c13c6a5f0d7e425ee6582eec62cdb7be450c55'
OLD_UI_INDEXES=frozenset(('assets/ghost-ui-index-v1.tsv','assets/arcade-ui-v5-index.tsv'))
PROFILE_PATH='assets/original-convert/profile.tsv';APP_PATH='assets/chaquopy/app.imy'
RUNTIME_PATHS=frozenset(('assets/chaquopy/app.imy', 'assets/chaquopy/bootstrap-native/arm64-v8a/_bz2.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/_ctypes.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/_datetime.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/_lzma.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/_opcode.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/_random.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/_struct.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/binascii.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/java/chaquopy.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/math.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/mmap.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap-native/arm64-v8a/zlib.cpython-313-aarch64-linux-android.so', 'assets/chaquopy/bootstrap.imy', 'assets/chaquopy/build.json', 'assets/chaquopy/cacert.pem', 'assets/chaquopy/requirements-arm64-v8a.imy', 'assets/chaquopy/requirements-common.imy', 'assets/chaquopy/stdlib-arm64-v8a.imy', 'assets/chaquopy/stdlib-common.imy', 'assets/original-convert/NOTICE.txt', 'assets/original-convert/licenses/Android-cpufeatures-NOTICE.txt', 'assets/original-convert/licenses/Converter-shim-MIT-LICENSE.txt', 'assets/original-convert/licenses/FFmpeg-LGPL-2.1.txt', 'assets/original-convert/licenses/FFmpeg-LICENSE.md', 'assets/original-convert/licenses/NDK-LLVM-NOTICE.txt', 'assets/original-convert/licenses/OpenH264-LICENSE.txt', 'assets/original-convert/licenses/Port-source-MIT-LICENSE.txt', 'assets/original-convert/profile.tsv', 'lib/arm64-v8a/libchaquopy_java.so', 'lib/arm64-v8a/libcrypto_chaquopy.so', 'lib/arm64-v8a/libcrypto_python.so', 'lib/arm64-v8a/liboa_native.so', 'lib/arm64-v8a/liboc_media_overlay.so', 'lib/arm64-v8a/libpython3.13.so', 'lib/arm64-v8a/libpython3.so', 'lib/arm64-v8a/libsqlite3_chaquopy.so', 'lib/arm64-v8a/libsqlite3_python.so', 'lib/arm64-v8a/libssl_chaquopy.so', 'lib/arm64-v8a/libssl_python.so'))

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

def _original_profile(profile,app,conversion):
    return race.inspect(profile,app,conversion)


def verify(path,*,runtime,baselines,sidecars,launcher,dataset,readset,paint_manifest,paint_readset,vehicle,base_ui,base_ui_bank,race_conversion,ghost_followup=False,crown_storage_fix=False,cloud_ghosts=False,cinder_061=False,cinder_062=False,cinder_063=False,cinder_064=False,cinder_065=False,cinder_066=False,cinder_067=False,cinder_068=False,cinder_069=False,cinder_070=False):
    prepared_resources=cinder_065 or cinder_066 or cinder_067 or cinder_068 or cinder_069 or cinder_070
    conversion,conversion_hash=race.load_reference(race_conversion,cinder_061=cinder_061,cinder_062=cinder_062,cinder_063=cinder_063,cinder_064=cinder_064 or prepared_resources)
    approved,data,approval_hash=expected_manifest(dataset,readset,paint_manifest,paint_readset)
    successor=(ghost_followup,crown_storage_fix,cloud_ghosts,cinder_061,cinder_062,cinder_063,cinder_064,cinder_065,cinder_066,cinder_067,cinder_068,cinder_069,cinder_070)
    require(sum(successor)<=1,'choose exactly one successor profile')
    data_pin,paint_pin = (FOLLOWUP_DATA_SHA,FOLLOWUP_GHOST_PAINT_SHA) if any(successor) else (DATA_SHA,GHOST_PAINT_SHA)
    code,version,profile_name = (
        (3,'0.3','project-cinder-race-restoration-v1'),
        (4,'0.4','project-cinder-ghost-followup-v1'),
        (5,'0.5','project-cinder-crown-storage-v1'),
        (6,'0.6','project-cinder-cloud-ghosts-v1'),
        (7,'0.61','project-cinder-0.61'),
        (8,'0.62','project-cinder-0.62'),
        (9,'0.63','project-cinder-0.63'),
        (10,'0.64','project-cinder-0.64'),
        (11,'0.65','project-cinder-0.65'),
        (12,'0.66','project-cinder-0.66'),
        (13,'0.67','project-cinder-0.67'),
        (14,'0.68','project-cinder-0.68'),
        (15,'0.69','project-cinder-0.69'),
        (16,'0.70','project-cinder-0.70'),
    )[sum((i+1)*flag for i,flag in enumerate(successor))]
    require(data[BANK].sha256==data_pin and approved['paint_section']['sha256']==paint_pin,'builtin WGBANK2/paint authority changed')
    ua,ui,base,base_wire=_ui_references(vehicle,base_ui,base_ui_bank)
    inventory,ih=runtime_inventory(runtime);art,ah=launcher_inventory(launcher)
    require(set(inventory)==RUNTIME_PATHS,'successor runtime exact40-member namespace')
    require(inventory['assets/original-convert/licenses/Port-source-MIT-LICENSE.txt'].sha256=='57f40033fb18990abca8d221621b476d7f6cf84b38ce324fd40b13a3b214507b','verbatim distinct port-source attribution required')
    require(inventory[PROFILE_PATH].sha256==conversion['profile_sha256'],'runtime reference is not the separately reviewed new original profile')
    require(inventory['lib/arm64-v8a/liboa_native.so'].sha256==race.AO_IMAGE_SHA256,'runtime must bind the separately cross-built successor AO library')
    require(not any({'player-body-paints.bin','tiresmoke.bin','tiresmoke.wpk','tiresmoke_all.tga'}&set(n.split('/'))for n in inventory),'MAIN player bank may not become an APK asset')
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
            require(not any({'player-body-paints.bin','tiresmoke.bin','tiresmoke.wpk','tiresmoke_all.tga'}&set(n.split('/'))for n in files),'converted MAIN bank must not be embedded in APK')
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
            catalog=apk.read('assets/data-baselines.zip',MAX_CATALOG)
            require(hashlib.sha256(catalog).hexdigest()==cp,'baseline metadata changed')
            baseline_ids=KNOWN_BASELINES|{PREPARED_BASELINE} if prepared_resources else KNOWN_BASELINES
            require(load_catalog(io.BytesIO(catalog),allow_prepared=prepared_resources).keys()==baseline_ids,'reviewed baseline set changed')
            old_index=apk.read('assets/sidecars-index-v1.tsv',MAX_INDEX)
            require(hashlib.sha256(old_index).hexdigest()==ip,'old41 metadata changed');old_rows=parse_sidecars(old_index)
            require(len(old_rows)==41,'old41 count changed')
            require(('assets/backfire.wpk'in files)==('assets/backfire.bfx'in files),'incomplete old backfire pair')
            b=apk.read(BANK,data[BANK].size);idx=apk.read(INDEX,512)
            require(len(b)==data[BANK].size and hashlib.sha256(b).hexdigest()==data[BANK].sha256,'dataset differs from independent expectation')
            require(idx==encode_index(data[BANK]) and len(idx)==data[INDEX].size and hashlib.sha256(idx).hexdigest()==data[INDEX].sha256,'dataset index contradiction')
            stats=inspect_pack(b,paint_manifest,paint_readset)
            require(stats['paint_sha256']==paint_pin,'builtin paint content changed')
            ub=apk.read(v6.BANK_PATH,ui[v6.BANK_PATH].size);ux=apk.read(v6.INDEX_PATH,512)
            ui_stats=v6.verify(ub,ux,ua)
            # Actual 98-sprite /18-animation prefix comparison with the complete
            # independently pinned base-v5 bytes, in addition to v6's hash proof.
            cut=base_wire['sprite_end'];require(ub[16:cut]==base[16:cut],'base98 sprite bytes changed')
            start=ui_stats['sprite_end'];require(ub[start:start+len(base)-cut]==base[cut:],'base18 animation bytes changed')
            require(hashlib.sha256(ux).hexdigest()==UI_INDEX_SHA,'v6 index release pin')
            package=manifest_identity(apk.read('AndroidManifest.xml',1024**2),version_code=code,version_name=version)
            profile=apk.read(PROFILE_PATH,MAX_JSON);app=apk.read(APP_PATH,32*1024**2)
            original_profile=_original_profile(profile,app,conversion)
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
    return {'profile':profile_name,'apk_sha256':original,'bytes':size,
        'independent_reference_count':12,'race_conversion_manifest_sha256':conversion_hash,'actual_complete_APK_inventory_checked':True,
        'runtime_members':len(inventory),'runtime_inventory_sha256':ih,'launcher_inventory_sha256':ah,
        'wallpaper_sha256':art[WALLPAPER].sha256,'sidecar_count':len(old_rows),
        'vehicle_ui_manifest_sha256':UI_MANIFEST_SHA,'base_v5_manifest_sha256':v6.BASE_MANIFEST_SHA,
        'vehicle_ui_bank_sha256':UI_BANK_SHA,'vehicle_ui_index_sha256':UI_INDEX_SHA,
        'vehicle_ui':{'sprites':622,'animations':22,'base98sprites_18anms_actual_byte_equal':True},
        'package':package,'original_profile':original_profile,'dataset_manifest_sha256':approval_hash,'dataset_sha256':data[BANK].sha256,
        'legacy_verifiers_or_profiles_changed':False,'main_resource_embedded':False,'original_main_embedded':False,
        'crypto_signer_JNI_DEX_ELF_FMA_physics_or_alignment_verified':False,'android_or_GPU_verified':False,
        'ta_global_service_deployed':False,'compiled_defaults_used_as_recordings':False,**stats}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('apk',type=Path)
    successor=p.add_mutually_exclusive_group()
    successor.add_argument('--ghost-followup',action='store_true',help='require the signed 0.4 Ghost resource profile')
    successor.add_argument('--crown-storage-fix',action='store_true',help='require the signed 0.5 Crown storage profile')
    successor.add_argument('--cloud-ghosts',action='store_true',help='require the signed 0.6 Cloud Ghosts profile')
    successor.add_argument('--cinder-061',action='store_true',help='require the signed Project Cinder 0.61 profile')
    successor.add_argument('--cinder-062',action='store_true',help='require the signed Project Cinder 0.62 profile')
    successor.add_argument('--cinder-063',action='store_true',help='require the signed Project Cinder 0.63 profile')
    successor.add_argument('--cinder-064',action='store_true',help='require the signed Project Cinder 0.64 profile')
    successor.add_argument('--cinder-065',action='store_true',help='require the signed Project Cinder 0.65 profile and prepared resource catalog')
    successor.add_argument('--cinder-066',action='store_true',help='require the signed Project Cinder 0.66 profile and prepared resource catalog')
    successor.add_argument('--cinder-067',action='store_true',help='require the signed Project Cinder 0.67 profile and prepared resource catalog')
    successor.add_argument('--cinder-068',action='store_true',help='require the signed Project Cinder 0.68 profile and prepared resource catalog')
    successor.add_argument('--cinder-069',action='store_true',help='require the signed Project Cinder 0.69 profile and prepared resource catalog')
    successor.add_argument('--cinder-070',action='store_true',help='require the signed Project Cinder 0.70 profile and prepared resource catalog')
    for name in ('runtime','baselines','sidecars','launcher','builtin-data-manifest','builtin-source-readset',
            'paint-manifest','paint-source-readset','vehicle-ui-manifest','base-ui-manifest','base-ui-bank','race-conversion-manifest'):
        p.add_argument('--expected-'+name,type=Path,required=True)
    a=p.parse_args(argv)
    try:
        result=verify(a.apk,runtime=a.expected_runtime,baselines=a.expected_baselines,sidecars=a.expected_sidecars,
            launcher=a.expected_launcher,dataset=a.expected_builtin_data_manifest,readset=a.expected_builtin_source_readset,
            paint_manifest=a.expected_paint_manifest,paint_readset=a.expected_paint_source_readset,
            vehicle=a.expected_vehicle_ui_manifest,base_ui=a.expected_base_ui_manifest,base_ui_bank=a.expected_base_ui_bank,
            race_conversion=a.expected_race_conversion_manifest,ghost_followup=a.ghost_followup,crown_storage_fix=a.crown_storage_fix,cloud_ghosts=a.cloud_ghosts,cinder_061=a.cinder_061,cinder_062=a.cinder_062,cinder_063=a.cinder_063,cinder_064=a.cinder_064,cinder_065=a.cinder_065,cinder_066=a.cinder_066,cinder_067=a.cinder_067,cinder_068=a.cinder_068,cinder_069=a.cinder_069,cinder_070=a.cinder_070)
    except (ResourceError,OSError,ValueError,KeyError,TypeError,RuntimeError,SyntaxError,RecursionError,struct.error,zipfile.BadZipFile,zlib.error) as exc:
        p.exit(2,'Race-restoration APK refused: '+str(exc)+'\n')
    print(json.dumps(result,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
