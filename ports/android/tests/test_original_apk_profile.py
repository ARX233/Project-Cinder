"""Offline original-converter APK packaging-profile safety tests.

All code/native/PNG placeholders are inert SYNTHETIC opaque bytes, never loaded
or executed. ZIP/DMF/TSV fixtures are independently authored metadata: the tests
never extract an APK to manufacture its trusted references. No original main,
resource conversion, game payload, device or Android execution is involved.
Generated fixtures and CLI logs remain under WMMT_APK_PROFILE_TEST_ROOT (APFS).
"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

REPO=Path(__file__).resolve().parents[1]
if not (REPO/'tools/verify_original_convert_apk.py').is_file():
    REPO=Path(os.environ['WMMT_APK_PROFILE_TEST_REPO'])
TOOLS=REPO/'tools'
sys.path.insert(0,str(TOOLS))
sys.dont_write_bytecode=True
import resource_pack_common as common
import verify_original_convert_apk as gate
import verify_resource_free_apk as legacy_gate
from test_resource_free_apk import dmf, zipped

sha=lambda data:hashlib.sha256(data).hexdigest()
REFUSED=(common.ResourceError,zipfile.BadZipFile,OSError,ValueError,KeyError,RuntimeError)
UNSET=object()


class OriginalApkProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent=Path(os.environ.get('WMMT_APK_PROFILE_TEST_ROOT',
            '/Volumes/CodexWork/android135-original-convert-l809giqy/apk-profile-tests'))
        if not parent.is_absolute() or not parent.is_dir():
            raise unittest.SkipTest('Select an existing APFS WMMT_APK_PROFILE_TEST_ROOT for synthetic APK fixtures')
        cls.root=Path(tempfile.mkdtemp(prefix='original-apk-profile-',dir=parent))
        os.chmod(cls.root,0o700)
        cls.resource_metadata={f'synthetic/resource-{n:04}.bin':f'SYNTHETIC metadata row {n}'.encode() for n in range(1798)}
        cls.manifests=[(pin+'.dmf',dmf(cls.resource_metadata,pin)) for pin in sorted(common.KNOWN_BASELINES)]
        cls.catalog=zipped(cls.manifests)
        cls.index=common.encode_sidecars({name:common.Entry(1,sha(b'X')) for name in common.SIDECAR_PATHS})
        cls.required={name:('SYNTHETIC LEGACY OPAQUE MEMBER - NEVER EXECUTED: '+name).encode() for name in gate.REQUIRED_FILES}
        names=('assets/chaquopy/app.imy','assets/chaquopy/build.json','assets/chaquopy/requirements-common.imy',
               'assets/original-convert/profile.tsv','lib/arm64-v8a/liboa_native.so',
               'lib/arm64-v8a/liboc_media_overlay.so','lib/arm64-v8a/libpython3.13.so')
        cls.runtime={name:('SYNTHETIC INDEPENDENTLY REVIEWED RUNTIME PLACEHOLDER - NOT EXECUTABLE: '+name).encode() for name in names}
        print('\nSynthetic original-APK profile fixtures retained: '+str(cls.root),flush=True)

    def setUp(self):
        self.work=self.root/self._testMethodName;self.work.mkdir();self.number=0
        self.manifest_path=self.write('reviewed-runtime.json',self.encode_inventory())
        self.catalog_ref=self.write('reviewed-baselines.zip',self.catalog)
        self.index_ref=self.write('reviewed-sidecars.tsv',self.index)

    def write(self,name,data):
        path=self.work/name
        with path.open('xb') as out:out.write(data)
        return path

    def next_file(self,suffix,data):
        self.number+=1
        return self.write(f'fixture-{self.number}.{suffix}',data)

    def inventory(self):
        return {'schema':'wmmt-original-runtime-package-v1','files':[
            {'path':name,'bytes':len(data),'sha256':sha(data)} for name,data in sorted(self.runtime.items())]}

    def encode_inventory(self,obj=None):
        return json.dumps(self.inventory() if obj is None else obj,sort_keys=True,separators=(',',':')).encode()+b'\n'

    def manifest(self,obj):return self.next_file('json',self.encode_inventory(obj))

    def apk(self,*,runtime=None,catalog=None,index=None,remove=(),extra=(),replace=None):
        files={**self.required,**(self.runtime if runtime is None else runtime),
               'assets/data-baselines.zip':self.catalog if catalog is None else catalog,
               'assets/sidecars-index-v1.tsv':self.index if index is None else index}
        for name in remove:files.pop(name)
        if replace:files.update(replace)
        return self.next_file('apk',zipped(list(files.items())+list(extra)))

    def verify(self,apk=None,*,runtime=UNSET,baselines=UNSET,sidecars=UNSET):
        return gate.verify(self.apk() if apk is None else apk,
            runtime=self.manifest_path if runtime is UNSET else runtime,
            baselines=self.catalog_ref if baselines is UNSET else baselines,
            sidecars=self.index_ref if sidecars is UNSET else sidecars)

    def refuses(self,apk=None,**kwargs):
        with self.assertRaises(REFUSED):self.verify(apk,**kwargs)

    def test_complete_synthetic_runtime_and_independent_reference_files(self):
        result=self.verify()
        self.assertEqual(result['profile'],'resource-free-original-convert-v1')
        self.assertEqual(result['runtime_members'],len(self.runtime))
        self.assertEqual(result['runtime_inventory_sha256'],sha(self.manifest_path.read_bytes()))
        self.assertEqual(result['original_profile_sha256'],sha(self.runtime['assets/original-convert/profile.tsv']))
        self.assertTrue(result['reviewed_references_matched']);self.assertFalse(result['game_payloads_embedded'])
        self.assertFalse(result['signature_loadability_or_android_execution_verified'])
        self.assertTrue(result['compiled_original_derived_code_not_legally_cleared'])

    def test_reference_hash_file_and_mixed_forms(self):
        apk=self.apk()
        for baselines,sidecars in ((sha(self.catalog),sha(self.index)),(self.catalog_ref,sha(self.index)),(sha(self.catalog),self.index_ref)):
            self.assertTrue(self.verify(apk,baselines=baselines,sidecars=sidecars)['reviewed_references_matched'])

    def test_all_three_references_are_required(self):
        apk=self.apk()
        with self.assertRaises(TypeError):gate.verify(apk)
        for kwargs in ({'runtime':None},{'baselines':None},{'sidecars':None}):
            with self.assertRaises((TypeError,*REFUSED)):self.verify(apk,**kwargs)

    def test_wrong_reviewed_baselines_and_sidecars_fail_closed(self):
        apk=self.apk()
        for kwargs in ({'baselines':'0'*64},{'sidecars':'0'*64},
                       {'baselines':self.write('wrong-reference.zip',b'not-reviewed-metadata')},
                       {'sidecars':self.write('wrong-reference.tsv',b'wrong-sidecar-index')}):
            self.refuses(apk,**kwargs)

    def test_each_runtime_member_missing_is_rejected(self):
        for name in self.runtime:
            with self.subTest(name=name):self.refuses(self.apk(remove=[name]))

    def test_each_runtime_member_hash_is_consumed_not_just_crc(self):
        for name,data in self.runtime.items():
            changed=bytes([data[0]^1])+data[1:]
            with self.subTest(name=name):self.refuses(self.apk(replace={name:changed}))

    def test_runtime_member_size_and_nonempty_are_required(self):
        for name in self.runtime:
            with self.subTest(name=name,kind='empty'):self.refuses(self.apk(replace={name:b''}))
            with self.subTest(name=name,kind='length'):self.refuses(self.apk(replace={name:self.runtime[name]+b'X'}))

    def test_legacy_members_and_metadata_remain_required(self):
        for name in gate.REQUIRED_FILES|gate.ALLOWED_ASSETS:
            with self.subTest(name=name):self.refuses(self.apk(remove=[name]))
        for name in gate.REQUIRED_FILES:
            with self.subTest(empty=name):self.refuses(self.apk(replace={name:b''}))

    def test_unknown_game_code_catalog_and_runtime_extras_are_rejected(self):
        for name in ('assets/game.zip','assets/WMN3/cars/a.wpk','assets/catalog-run-assets.zip',
                     'assets/original-convert/unapproved-game.zip','assets/chaquopy/unapproved.imy',
                     'lib/arm64-v8a/unapproved.so','lib/x86/libpython.so','classes2.dex',
                     'res/raw/main','META-INF/hidden.dat'):
            with self.subTest(name=name):self.refuses(self.apk(extra=[(name,b'SYNTHETIC UNAPPROVED EXTRA')]))

    def test_runtime_allowlist_schema_fields_and_required_members(self):
        for obj in ({}, {'schema':'unknown','files':[]}, {'schema':'wmmt-original-runtime-package-v1','files':[]},
                    {**self.inventory(),'player_receipt':True}):
            with self.assertRaises(REFUSED):gate.runtime_inventory(self.manifest(obj))
        for required in ('assets/chaquopy/app.imy','assets/chaquopy/build.json','assets/original-convert/profile.tsv',
                         'lib/arm64-v8a/liboa_native.so','lib/arm64-v8a/liboc_media_overlay.so'):
            obj=self.inventory();obj['files']=[row for row in obj['files'] if row['path']!=required]
            with self.subTest(name=required),self.assertRaises(REFUSED):gate.runtime_inventory(self.manifest(obj))

    def test_runtime_allowlist_bad_types_hashes_and_size_bounds(self):
        for key,value in (('bytes',True),('bytes',0),('bytes',-1),('bytes',128*1024**2+1),
                          ('sha256','A'*64),('sha256','not-a-hash'),('path',None),('extra','unreviewed')):
            obj=self.inventory();obj['files'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(REFUSED):gate.runtime_inventory(self.manifest(obj))

    def test_runtime_allowlist_duplicate_rows_order_and_json_members(self):
        obj=self.inventory();obj['files'].insert(0,dict(obj['files'][0]))
        with self.assertRaises(REFUSED):gate.runtime_inventory(self.manifest(obj))
        obj=self.inventory();obj['files'].reverse()
        with self.assertRaises(REFUSED):gate.runtime_inventory(self.manifest(obj))
        raw=self.encode_inventory()
        for bad in (raw.replace(b'"schema":',b'"schema":"duplicate","schema":',1),
                    raw.replace(b'"bytes":',b'"bytes":1,"bytes":',1)):
            with self.assertRaises(REFUSED):gate.runtime_inventory(self.next_file('json',bad))

    def test_runtime_allowlist_namespaces_traversal_controls_and_legacy_override(self):
        for name in ('assets/game.zip','assets/chaquopy/../evil.imy','assets/chaquopy//evil.imy',
                     'assets/chaquopy\\evil.imy','assets/chaquopy/evil:payload','assets/chaquopy/tab\tname',
                     '/assets/chaquopy/app.imy','lib/x86/libpython.so',*gate.REQUIRED_FILES,*gate.ALLOWED_ASSETS):
            obj=self.inventory();obj['files'].append({'path':name,'bytes':1,'sha256':sha(b'X')});obj['files'].sort(key=lambda r:r['path'])
            with self.subTest(name=name),self.assertRaises(REFUSED):gate.runtime_inventory(self.manifest(obj))

    def test_runtime_allowlist_count_byte_and_regular_file_budgets(self):
        obj=self.inventory();obj['files'] += [{'path':f'assets/chaquopy/z{n:03}.imy','bytes':1,'sha256':sha(b'X')} for n in range(257)]
        obj['files'].sort(key=lambda r:r['path'])
        with self.assertRaises(REFUSED):gate.runtime_inventory(self.manifest(obj))
        with self.assertRaises(REFUSED):gate.runtime_inventory(self.next_file('json',b' '*(1024**2+1)))
        with self.assertRaises(REFUSED):gate.runtime_inventory(self.work)

    def test_approved_parent_directories_are_not_blanket_prefix_permissions(self):
        names=set(self.required)|set(self.runtime)|set(gate.ALLOWED_ASSETS);parents={'META-INF/'}
        for name in names:
            parts=name.split('/');parents.update('/'.join(parts[:i])+'/' for i in range(1,len(parts)))
        self.verify(self.apk(extra=[(name,b'') for name in sorted(parents)]))
        for name in ('assets/chaquopy/unreviewed/','assets/original-convert/unused/','res/raw/','META-INF/hidden/'):
            with self.subTest(name=name):self.refuses(self.apk(extra=[(name,b'')]))

    def test_outer_duplicates_casefold_and_file_directory_shadow_are_rejected(self):
        for name in ('assets/chaquopy/app.imy','assets/chaquopy/APP.IMY','assets/chaquopy/app.imy/','../outside','res\\raw\\evil'):
            data=b'' if name.endswith('/') else b'SYNTHETIC DUPLICATE'
            with self.subTest(name=name):self.refuses(self.apk(extra=[(name,data)]))

    def test_zip_symlink_and_special_file_modes_are_rejected(self):
        name='assets/chaquopy/app.imy'
        for mode in (stat.S_IFLNK|0o777,stat.S_IFIFO|0o600,stat.S_IFCHR|0o600):
            info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=mode<<16
            with self.subTest(mode=mode):self.refuses(self.apk(remove=[name],extra=[(info,b'../unapproved')]))

    def test_apk_and_all_reference_leaf_symlinks_are_rejected(self):
        apk=self.apk()
        for name,target,kw in (('apk-link',apk,None),('runtime-link',self.manifest_path,'runtime'),
                               ('catalog-link',self.catalog_ref,'baselines'),('sidecars-link',self.index_ref,'sidecars')):
            link=self.work/name;link.symlink_to(target)
            with self.subTest(name=name):
                if kw is None:self.refuses(link)
                else:self.refuses(apk,**{kw:link})

    def test_nested_catalog_payload_directory_and_duplicate_are_rejected_even_when_pinned(self):
        for rows in (self.manifests+[('game.zip',b'SYNTHETIC HIDDEN PAYLOAD')],
                     self.manifests+[('empty/',b'')],self.manifests+[self.manifests[0]]):
            catalog=zipped(rows);self.refuses(self.apk(catalog=catalog),baselines=sha(catalog))

    def test_old_baseline_set_and_dmf_identity_cannot_be_relaxed(self):
        unknown='0'*64
        for rows in ([self.manifests[0]],[(unknown+'.dmf',dmf(self.resource_metadata,unknown)),self.manifests[1]]):
            catalog=zipped(rows);self.refuses(self.apk(catalog=catalog),baselines=sha(catalog))
        pin=self.manifests[0][0]
        catalog=zipped([(pin,dmf(self.resource_metadata,self.manifests[1][0][:-4])),self.manifests[1]])
        self.refuses(self.apk(catalog=catalog),baselines=sha(catalog))

    def test_rehashed_dmf_cannot_authorize_executable_or_save_resource_names(self):
        for name in ('main','classes.dex','saves/garage1','lib/game.so'):
            resources=dict(self.resource_metadata);resources.pop(next(iter(resources)));resources[name]=b'SYNTHETIC ROW ONLY'
            rows=[(pin+'.dmf',dmf(resources,pin)) for pin in sorted(common.KNOWN_BASELINES)];catalog=zipped(rows)
            with self.subTest(name=name):self.refuses(self.apk(catalog=catalog),baselines=sha(catalog))

    def test_sidecar_shape_is_checked_even_with_matching_reference_pin(self):
        lines=self.index.splitlines(keepends=True)
        for index in (b'WMMT-SIDECARS-1\n',self.index.replace(b'backfire.bfx',b'../../save',1),
                      lines[0]+b''.join(reversed(lines[1:])),self.index+b'extra-payload\n'):
            self.refuses(self.apk(index=index),sidecars=sha(index))

    def test_zip_crc_local_name_damage_truncation_and_trailing_are_rejected(self):
        raw=self.apk().read_bytes();info=zipfile.ZipFile(io.BytesIO(raw)).getinfo('assets/chaquopy/app.imy')
        n,extra=struct.unpack_from('<HH',raw,info.header_offset+26)
        bad=bytearray(raw);bad[info.header_offset+30+n+extra]^=1
        self.refuses(self.next_file('apk',bytes(bad)))
        bad=bytearray(raw);bad[info.header_offset+30]^=1
        self.refuses(self.next_file('apk',bytes(bad)))
        for bad in (raw+b'junk',raw[:-22]):self.refuses(self.next_file('apk',bad))

    def test_outer_archive_entry_and_expansion_budgets(self):
        apk=self.apk()
        with patch.object(gate,'MAX_APK',22):self.refuses(apk)
        with patch.object(gate,'MAX_EXPANDED',16):self.refuses(apk)
        extras=[(f'assets/chaquopy/d{n:04}/',b'') for n in range(1025)]
        self.refuses(self.apk(extra=extras))

    def test_public_signature_envelope_retains_explicit_non_authenticity_claim(self):
        oid=bytes.fromhex('06092a864886f70d010702')
        public=[('META-INF/MANIFEST.MF',b'Manifest-Version: 1.0\r\n\r\n'),
                ('META-INF/WMMT.SF',b'Signature-Version: 1.0\r\n\r\n'),
                ('META-INF/WMMT.RSA',b'\x30\x0d'+oid+b'\xa0\x00')]
        self.assertFalse(self.verify(self.apk(extra=public))['signature_loadability_or_android_execution_verified'])
        for rows in (public[:1],public[1:],public[:-1],public[:-1]+[('META-INF/WMMT.RSA',b'not DER')],
                     public+[('META-INF/WMMT.DSA',public[-1][1])]):self.refuses(self.apk(extra=rows))

    def test_legacy_verifier_stays_stricter_without_runtime_allowlist(self):
        apk=self.apk()
        with self.assertRaises(common.ResourceError):legacy_gate.verify(apk,self.catalog_ref,self.index_ref)
        legacy_apk=self.apk(runtime={})
        self.assertTrue(legacy_gate.verify(legacy_apk,self.catalog_ref,self.index_ref)['reviewed_references_matched'])
        self.refuses(legacy_apk)

    def test_cli_requires_three_reference_flags_and_reports_refusal(self):
        apk=self.apk();script=TOOLS/'verify_original_convert_apk.py'
        reference_args=['--expected-runtime',str(self.manifest_path),'--expected-baselines',sha(self.catalog),'--expected-sidecars',sha(self.index)]
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(self.work))
        for removed in (0,2,4):
            args=reference_args[:removed]+reference_args[removed+2:]
            result=subprocess.run([sys.executable,'-B',str(script),str(apk),*args],cwd=self.work,env=env,text=True,capture_output=True)
            self.write(f'cli-missing-{removed}.log',(result.stdout+result.stderr).encode());self.assertEqual(result.returncode,2)
        result=subprocess.run([sys.executable,'-B',str(script),str(apk),*reference_args],cwd=self.work,env=env,text=True,capture_output=True)
        self.write('cli-positive.log',(result.stdout+result.stderr).encode());self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(json.loads(result.stdout)['signature_loadability_or_android_execution_verified'])
        bad=self.apk(extra=[('assets/game.zip',b'SYNTHETIC UNAPPROVED')])
        result=subprocess.run([sys.executable,'-B',str(script),str(bad),*reference_args],cwd=self.work,env=env,text=True,capture_output=True)
        self.write('cli-refused.log',(result.stdout+result.stderr).encode());self.assertEqual(result.returncode,2)
        self.assertIn('verification refused',result.stderr);self.assertNotIn('Traceback',result.stderr)


if __name__=='__main__':unittest.main(verbosity=2)
