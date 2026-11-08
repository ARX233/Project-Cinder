"""Cinder-only strict launcher/APK profile tests; all APK contents are inert.

Opaque SYNTHETIC manifest/resources/PNG/native/DEX/IMY bytes are never executed.
Trusted metadata fixtures are authored independently, not by scanning an APK.
Only each test's imported module gets a synthetic wallpaper-pin patch; production
code/constant/reference validators are never rewritten. No device/game/source ZIP.
All generated files remain in an isolated external APFS test workspace.
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

REPO=Path(os.environ.get('CINDER_APK_TEST_REPO',Path(__file__).resolve().parents[1]))
sys.path[:0]=[str(REPO/'tools'),str(REPO/'tests')]
sys.dont_write_bytecode=True
import resource_pack_common as common
import test_original_apk_profile as original_fixtures
import verify_original_convert_apk as original_gate
SOURCE=Path(os.environ.get('CINDER_APK_VERIFIER_SOURCE',REPO/'tools/verify_cinder_apk.py'))
spec=importlib.util.spec_from_file_location('cinder_gate_under_test',SOURCE)
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
sha=lambda data:hashlib.sha256(data).hexdigest()
REFUSED=(common.ResourceError,zipfile.BadZipFile,OSError,ValueError,KeyError,RuntimeError,TypeError)
UNSET=object()


class CinderApkProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent=Path(os.environ.get('CINDER_APK_TEST_ROOT','/Volumes/CodexWork/cinder-01-20261104-SKQkSw/verifier-tests')).resolve()
        if not parent.is_absolute() or not parent.is_dir():
            raise unittest.SkipTest('Select an existing APFS CINDER_APK_TEST_ROOT')
        # Reuse the existing, independently authored 1798-row/2-catalog/41-sidecar
        # fixtures and seven explicitly non-executable runtime placeholders.
        with patch.dict(os.environ,{'WMMT_APK_PROFILE_TEST_ROOT':str(parent)}):
            original_fixtures.OriginalApkProfileTests.setUpClass.__func__(cls)
        cls.approved_wallpaper=b'SYNTHETIC USER-PHOTO SUBSTITUTE - TEST PIN ONLY - NOT JPEG'
        cls.launcher_bodies={
            'AndroidManifest.xml':cls.required['AndroidManifest.xml'],
            'resources.arsc':cls.required['resources.arsc'],
            gate.WALLPAPER:cls.approved_wallpaper,
            'res/mipmap/icon.png':cls.required['res/mipmap/icon.png'],
            'res/mipmap-anydpi-v26/icon.xml':b'SYNTHETIC COMPILED ADAPTIVE XML - NOT ANDROID LOADABLE',
            'res/drawable-nodpi-v4/cinder_icon_foreground.png':b'SYNTHETIC REVIEWED FOREGROUND PNG - NEVER DECODED'}
        cls.source_pins={str(p):sha(p.read_bytes()) for p in
            (REPO/'tools/verify_original_convert_apk.py',REPO/'tools/verify_resource_free_apk.py',REPO/'tests/test_original_apk_profile.py',REPO/'tools/resource_pack_common.py')}

    @classmethod
    def tearDownClass(cls):
        for name,pin in cls.source_pins.items():
            if sha(Path(name).read_bytes())!=pin:raise AssertionError('Existing source changed: '+name)

    write=original_fixtures.OriginalApkProfileTests.write
    next_file=original_fixtures.OriginalApkProfileTests.next_file
    inventory=original_fixtures.OriginalApkProfileTests.inventory
    encode_inventory=original_fixtures.OriginalApkProfileTests.encode_inventory
    manifest=original_fixtures.OriginalApkProfileTests.manifest

    def setUp(self):
        self.work=self.root/self._testMethodName;self.work.mkdir();self.number=0
        self.runtime_ref=self.write('reviewed-runtime.json',self.encode_inventory())
        self.catalog_ref=self.write('reviewed-baselines.zip',self.catalog)
        self.index_ref=self.write('reviewed-sidecars.tsv',self.index)
        self.launcher_ref=self.write('reviewed-resource-only-launcher.json',self.encode_launcher())
        self.pin_patch=patch.multiple(gate,WALLPAPER_BYTES=len(self.approved_wallpaper),WALLPAPER_SHA256=sha(self.approved_wallpaper))
        self.pin_patch.start();self.addCleanup(self.pin_patch.stop)

    def launcher_rows(self,bodies=None):
        return {'schema':gate.LAUNCHER_SCHEMA,'files':[
            {'path':n,'bytes':len(v),'sha256':sha(v)} for n,v in sorted((self.launcher_bodies if bodies is None else bodies).items())]}
    def encode_launcher(self,obj=None):
        return json.dumps(self.launcher_rows() if obj is None else obj,sort_keys=True,separators=(',',':')).encode()+b'\n'
    def launch_manifest(self,obj):return self.next_file('json',self.encode_launcher(obj))
    def apk(self,*,remove=(),replace=None,extra=(),runtime=None,catalog=None,index=None):
        bodies={**self.required,**(self.runtime if runtime is None else runtime),**self.launcher_bodies,
            'assets/data-baselines.zip':self.catalog if catalog is None else catalog,
            'assets/sidecars-index-v1.tsv':self.index if index is None else index}
        for name in remove:bodies.pop(name)
        if replace:bodies.update(replace)
        return self.next_file('apk',original_fixtures.zipped(list(bodies.items())+list(extra)))
    def verify(self,apk=None,*,runtime=UNSET,baselines=UNSET,sidecars=UNSET,launcher=UNSET):
        return gate.verify(self.apk() if apk is None else apk,
            runtime=self.runtime_ref if runtime is UNSET else runtime,
            baselines=self.catalog_ref if baselines is UNSET else baselines,
            sidecars=self.index_ref if sidecars is UNSET else sidecars,
            launcher=self.launcher_ref if launcher is UNSET else launcher)
    def refuses(self,apk=None,**kwargs):
        with self.assertRaises(REFUSED):self.verify(apk,**kwargs)

    def test_positive_independent_synthetic_resource_and_runtime_references(self):
        result=self.verify()
        self.assertEqual(result['profile'],'project-cinder-original-convert-v1')
        self.assertEqual(result['launcher_members'],6);self.assertEqual(result['runtime_members'],7)
        self.assertEqual(result['launcher_inventory_sha256'],sha(self.launcher_ref.read_bytes()))
        self.assertEqual(result['runtime_inventory_sha256'],sha(self.runtime_ref.read_bytes()))
        self.assertEqual(result['sidecar_count'],41);self.assertEqual(set(result['baseline_ids']),common.KNOWN_BASELINES)
        self.assertTrue(result['user_approved_wallpaper_pin_matched']);self.assertTrue(result['reviewed_references_matched'])
        for name in ('game_payloads_embedded','signature_loadability_or_android_execution_verified','package_version_signer_and_adaptive_semantics_verified'):
            self.assertFalse(result[name])
        self.assertTrue(result['compiled_original_derived_code_not_legally_cleared'])

    def test_all_four_independent_reference_arguments_required(self):
        with self.assertRaises(TypeError):gate.verify(self.apk())
        for key in ('runtime','baselines','sidecars','launcher'):
            with self.subTest(reference=key):self.refuses(**{key:None})

    def test_each_launcher_member_missing_rejected(self):
        for name in self.launcher_bodies:
            with self.subTest(member=name):self.refuses(self.apk(remove=[name]))

    def test_each_launcher_body_exact_hash_not_only_zip_crc(self):
        for name,data in self.launcher_bodies.items():
            with self.subTest(member=name):self.refuses(self.apk(replace={name:bytes([data[0]^1])+data[1:]}))

    def test_each_launcher_body_size_and_nonempty(self):
        for name,data in self.launcher_bodies.items():
            with self.subTest(member=name,empty=True):self.refuses(self.apk(replace={name:b''}))
            with self.subTest(member=name,extra=True):self.refuses(self.apk(replace={name:data+b'x'}))

    def test_production_wallpaper_pin_is_fixed_and_synthetic_input_refused(self):
        self.pin_patch.stop()
        self.assertEqual(gate.WALLPAPER_BYTES,396873)
        self.assertEqual(gate.WALLPAPER_SHA256,'2fcfa2aeeae006fc3cd10a9eafd73c577ca3657312ac9fbfb063a3bddf46054e')
        self.refuses()

    def test_reapproved_different_photo_cannot_override_user_pin(self):
        for key,value in (('sha256','0'*64),('bytes',len(self.approved_wallpaper)+1)):
            obj=self.launcher_rows()
            next(row for row in obj['files'] if row['path']==gate.WALLPAPER)[key]=value
            with self.subTest(field=key):self.refuses(launcher=self.launch_manifest(obj))

    def test_launcher_schema_and_exact_row_keys(self):
        for obj in ({},{'schema':'other','files':[]},{'schema':gate.LAUNCHER_SCHEMA,'files':[]},
                    {**self.launcher_rows(),'player_approval':True}):
            with self.assertRaises(REFUSED):gate.launcher_inventory(self.launch_manifest(obj))
        for key,value in (('bytes',True),('bytes',0),('bytes',-1),('bytes',128*1024**2),
                          ('sha256','A'*64),('sha256','notsha'),('path',None),('extra','notapproved')):
            obj=self.launcher_rows();obj['files'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(REFUSED):gate.launcher_inventory(self.launch_manifest(obj))

    def test_launcher_duplicates_order_and_duplicate_json_fields(self):
        for obj in ({**self.launcher_rows(),'files':list(reversed(self.launcher_rows()['files']))},
                    {**self.launcher_rows(),'files':[self.launcher_rows()['files'][0],*self.launcher_rows()['files']]}):
            with self.assertRaises(REFUSED):gate.launcher_inventory(self.launch_manifest(obj))
        raw=self.encode_launcher()
        for bad in (raw.replace(b'"schema":',b'"schema":"duplicate","schema":',1),
                    raw.replace(b'"bytes":',b'"bytes":1,"bytes":',1)):
            with self.assertRaises(REFUSED):gate.launcher_inventory(self.next_file('json',bad))

    def test_launcher_namespace_is_not_a_blanket_asset_res_lib_permission(self):
        names=('classes.dex','lib/arm64-v8a/libwmmt.so','assets/data-baselines.zip','assets/chaquopy/app.imy',
               'assets/original-convert/extra-photo.jpg','res/raw/main','res/layout/icon.xml',
               'res/drawable-nodpi-v4/unreviewed.png','res/mipmap/icon2.png',
               'res/mipmap-anydpi-v26/other.xml','res/mipmap-anydpi-v25/icon.xml',
               '../outside','/res/mipmap/icon.png','res//mipmap/icon.png','res/./mipmap/icon.png',
               'res/mipmap/../icon.png','res\\mipmap\\icon.png','res/mipmap/icon:payload.png','res/mipmap/icon\t.png')
        for name in names:
            bodies=dict(self.launcher_bodies);bodies[name]=b'SYNTHETIC UNAPPROVED'
            with self.subTest(member=name),self.assertRaises(REFUSED):gate.launcher_inventory(self.launch_manifest(self.launcher_rows(bodies)))

    def test_all_required_launcher_metadata_rows_present(self):
        for name in self.launcher_bodies:
            bodies=dict(self.launcher_bodies);bodies.pop(name)
            with self.subTest(member=name),self.assertRaises(REFUSED):gate.launcher_inventory(self.launch_manifest(self.launcher_rows(bodies)))

    def test_aapt_qualifier_variants_are_specific_and_reference_bound(self):
        bodies=dict(self.launcher_bodies)
        data=bodies.pop('res/drawable-nodpi-v4/cinder_icon_foreground.png')
        bodies['res/drawable-nodpi/cinder_icon_foreground.png']=data
        result,_=gate.launcher_manifest(self.launch_manifest(self.launcher_rows(bodies)))
        self.assertIn('res/drawable-nodpi/cinder_icon_foreground.png',result)
        self.refuses(launcher=self.launch_manifest(self.launcher_rows(bodies)))

    def test_two_foreground_aliases_rejected_and_resource_count_bounded(self):
        bodies=dict(self.launcher_bodies);bodies['res/drawable-nodpi/cinder_icon_foreground.png']=b'SYNTHETIC SECOND'
        with self.assertRaises(REFUSED):gate.launcher_inventory(self.launch_manifest(self.launcher_rows(bodies)))
        bodies=dict(self.launcher_bodies)
        for version in range(27,41):bodies[f'res/mipmap-anydpi-v{version}/icon.xml']=b'SYNTHETIC VARIANT'
        with self.assertRaises(REFUSED):gate.launcher_inventory(self.launch_manifest(self.launcher_rows(bodies)))

    def test_launcher_manifest_file_count_byte_and_leaf_budgets(self):
        with self.assertRaises(REFUSED):gate.launcher_inventory(self.next_file('json',b' '*(gate.MAX_LAUNCHER_MANIFEST+1)))
        with self.assertRaises(REFUSED):gate.launcher_inventory(self.work)
        obj=self.launcher_rows();obj['files']*=6
        with self.assertRaises(REFUSED):gate.launcher_inventory(self.launch_manifest(obj))

    def test_runtime_launcher_overlap_rejected_not_override(self):
        bodies={**self.runtime,gate.WALLPAPER:self.approved_wallpaper}
        obj={'schema':'wmmt-original-runtime-package-v1','files':[{'path':n,'bytes':len(v),'sha256':sha(v)} for n,v in sorted(bodies.items())]}
        self.refuses(runtime=self.manifest(obj))

    def test_missing_changed_or_extra_runtime_code_is_still_refused(self):
        for name,data in self.runtime.items():
            with self.subTest(member=name,kind='missing'):self.refuses(self.apk(remove=[name]))
            with self.subTest(member=name,kind='changed'):self.refuses(self.apk(replace={name:data+b'x'}))
        self.refuses(self.apk(extra=[('lib/arm64-v8a/unapproved.so',b'SYNTHETIC EXTRA')]))

    def test_both_baselines_and_full_sidecar_index_still_exact(self):
        self.refuses(baselines='0'*64);self.refuses(sidecars='0'*64)
        catalog=original_fixtures.zipped([self.manifests[0]])
        self.refuses(self.apk(catalog=catalog),baselines=sha(catalog))
        catalog=original_fixtures.zipped(self.manifests+[('game.zip',b'SYNTHETIC HIDDEN')])
        self.refuses(self.apk(catalog=catalog),baselines=sha(catalog))
        index=b''.join(self.index.splitlines(keepends=True)[:-1])
        self.refuses(self.apk(index=index),sidecars=sha(index))

    def test_unknown_outer_game_resources_and_empty_directories_refused(self):
        for name in ('assets/game.zip','assets/original-convert/unapproved-game.zip','res/raw/main',
                     'res/mipmap/new-icon.png','classes2.dex','META-INF/hidden.dat',
                     'res/drawable-unused/','assets/unused/'):
            with self.subTest(member=name):self.refuses(self.apk(extra=[(name,b'' if name.endswith('/') else b'SYNTHETIC EXTRA')]))
        expected=set(self.required)|set(self.runtime)|set(self.launcher_bodies)|set(gate.ALLOWED_ASSETS)
        parents={'META-INF/'}
        for name in expected:
            parts=name.split('/');parents.update('/'.join(parts[:n])+'/' for n in range(1,len(parts)))
        self.verify(self.apk(extra=[(name,b'') for name in sorted(parents)]))

    def test_duplicate_symlink_special_and_trailing_zip_refused(self):
        self.refuses(self.apk(extra=[(gate.WALLPAPER,self.approved_wallpaper)]))
        for mode in (stat.S_IFLNK|0o777,stat.S_IFIFO|0o600):
            info=zipfile.ZipInfo(gate.WALLPAPER);info.create_system=3;info.external_attr=mode<<16
            self.refuses(self.apk(remove=[gate.WALLPAPER],extra=[(info,b'../target')]))
        self.refuses(self.next_file('apk',self.apk().read_bytes()+b'UNAPPROVED TAIL'))

    def test_apk_and_reference_leaf_symlinks_refused(self):
        apk=self.apk()
        for name,target,key in (('apk-link',apk,None),('launcher-link',self.launcher_ref,'launcher'),
                                ('runtime-link',self.runtime_ref,'runtime'),('baseline-link',self.catalog_ref,'baselines'),('sidecar-link',self.index_ref,'sidecars')):
            link=self.work/name;link.symlink_to(target)
            with self.subTest(member=name):
                if key is None:self.refuses(link)
                else:self.refuses(apk,**{key:link})

    def test_jar_public_container_checks_are_preserved_not_crypto_claims(self):
        valid=[('META-INF/MANIFEST.MF',b'Manifest-Version: 1.0\r\n\r\n'),
               ('META-INF/CINDER.SF',b'Signature-Version: 1.0\r\n\r\n'),
               ('META-INF/CINDER.RSA',bytes.fromhex('300b06092a864886f70d010702'))]
        result=self.verify(self.apk(extra=valid));self.assertFalse(result['signature_loadability_or_android_execution_verified'])
        for extra in (valid[:1],valid[:2],valid[1:],[(n,b'bad') for n,_ in valid]):self.refuses(self.apk(extra=extra))

    def test_base_original_profile_not_relaxed_for_cinder_resources(self):
        with self.assertRaises(REFUSED):original_gate.verify(self.apk(),runtime=self.runtime_ref,baselines=self.catalog_ref,sidecars=self.index_ref)

    def test_cli_requires_each_reference_and_rejects_unapproved_photo_without_traceback(self):
        apk=self.apk();args=[str(apk),'--expected-runtime',str(self.runtime_ref),'--expected-baselines',str(self.catalog_ref),
            '--expected-sidecars',str(self.index_ref),'--expected-launcher',str(self.launcher_ref)]
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(REPO/'tools'))
        for index in (1,3,5,7):
            selected=args[:index]+args[index+2:]
            result=subprocess.run([sys.executable,'-B',str(SOURCE),*selected],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,2);self.assertNotIn('Traceback',result.stderr)
        # This new process intentionally has the immutable production photo pin,
        # so this SYNTHETIC photo must be rejected, never treated as user-approved.
        result=subprocess.run([sys.executable,'-B',str(SOURCE),*args],capture_output=True,text=True,env=env)
        self.assertEqual(result.returncode,2);self.assertNotIn('Traceback',result.stderr)
        output=io.StringIO()
        with contextlib.redirect_stdout(output):self.assertEqual(gate.main(args),0)
        self.assertEqual(json.loads(output.getvalue())['profile'],'project-cinder-original-convert-v1')

if __name__=='__main__':unittest.main(verbosity=2)
