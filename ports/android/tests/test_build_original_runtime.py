"""Security/closure tests for the offline original-runtime packager.

Synthetic ZIPs/ELFs only; no Python converter import/execution, native library
load, device or network. Every fixture/output lives in an external APFS root.
Set ORIGINAL_RUNTIME_BUILDER_SOURCE while reviewing before parent xb publication.
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib

SOURCE=Path(os.environ.get('ORIGINAL_RUNTIME_BUILDER_SOURCE',Path(__file__).resolve().parents[1]/'tools/build_original_runtime.py'))
spec=importlib.util.spec_from_file_location('original_runtime_builder_under_test',SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
EXTERNAL=Path(os.environ.get('ORIGINAL_RUNTIME_TEST_ROOT',Path(tempfile.gettempdir()).resolve()/'wmmt-original-runtime-tests')).resolve()
EXTERNAL.mkdir(parents=True,exist_ok=True)

def sha(b):return hashlib.sha256(b).hexdigest()
def zipbytes(files):return m.deterministic_zip(files)
def remove_fixture(path,root):
 path=Path(path);root=Path(root).resolve()
 assert path.resolve().is_relative_to(root) and root.is_relative_to(EXTERNAL.resolve()), 'unverified fixture deletion target'
 path.unlink()
def elf(tag=b'x',alignment=16384,needed=None):
 if needed:
  size=384;phnum=2
 else:size=128;phnum=1
 data=bytearray(size);data[:16]=b'\x7fELF\x02\x01\x01'+bytes(9)
 struct.pack_into('<HHIQQQIHHHHHH',data,16,3,183,1,0,64,0,0,64,56,phnum,0,0,0)
 struct.pack_into('<IIQQQQQQ',data,64,1,5,0,0,0,size,size,alignment)
 if needed:
  struct.pack_into('<IIQQQQQQ',data,120,2,6,176,176,0,64,64,8)
  name=needed.encode()+b'\0';data[320:320+len(name)]=name
  for i,pair in enumerate(((1,0),(5,320),(10,len(name)),(0,0))):struct.pack_into('<qQ',data,176+16*i,*pair)
 else:data[-8:]=(tag*8)[:8]
 return bytes(data)

class Fixture:
 def __init__(self,root,*,ao=None,media=None,duplicate=None):
  self.root=root;self.repo=root/'repo';self.repo.mkdir();self.ao=ao or elf(b'a');self.media=media or elf(b'm')
  self.profile_header={'profileId':'synthetic-reviewed','readsetSha256':'','recipeSha256':''}
  readset={'schema':'wmmt-original-readset-v1','main_sha256':m.MAIN_SHA,'files':[{'path':'data/a','bytes':1,'sha256':'1'*64},{'path':'main','bytes':2,'sha256':m.MAIN_SHA}]}
  outputs=[{'path':'cars/a.ao','max_bytes':8,'sha256':None,'kind':'ao','ao_layout':[]},{'path':'cars/a.wpk','max_bytes':8,'sha256':'2'*64,'kind':'fixed'}]
  recipe={'schema':'wmmt-original-recipe-v1','profile_id':'synthetic-reviewed','runtime':m.EXPECTED_RUNTIME.copy(),'native':{'liboa_native.so':sha(self.ao),'liboc_media_overlay.so':sha(self.media)},'raw':[],'wheels':{},'cars':{},'extras':{},'media':{},'outputs':outputs}
  rs=m._canonical(readset);rp=m._canonical(recipe)
  self.profile=('WMMT-ORIGINAL-PROFILE-1\nprofileId\tsynthetic-reviewed\nreadsetSha256\t'+sha(rs)+'\nrecipeSha256\t'+sha(rp)+'\nsrc\tdata/a\t1\t'+'1'*64+'\nsrc\tmain\t2\t'+m.MAIN_SHA+'\nout\tcars/a.ao\t8\t-\tao\nout\tcars/a.wpk\t8\t'+'2'*64+'\tfixed\nEND\n').encode()
  self.pins={'aar':'','ao':sha(self.ao),'media':sha(self.media),'profile':sha(self.profile)}
  for relative in m.SOURCE_PATHS:
   p=self.repo/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'"""Synthetic reviewed source, never executed."""\n')
  release="import base64,zlib\nREADSET_B64=%r\nRECIPE_B64=%r\nPINS=%r\ndef load_bundle():\n raise RuntimeError('must not execute')\n"%(base64.b64encode(zlib.compress(rs)).decode(),base64.b64encode(zlib.compress(rp)).decode(),{'profile_id':'synthetic-reviewed','readset_sha256':sha(rs),'recipe_sha256':sha(rp),'profile_sha256':sha(self.profile)})
  (self.repo/'tools/original_convert/release_assets.py').write_text(release)
  for source,destination in m.LICENSE_PATHS:
   path=self.repo/source;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('Synthetic public license text: '+path.name+'\n')
  assets={n:zipbytes({'LICENSE.txt':b'original test license'}) for n in m.IMYS}
  assets['app.imy']=zipbytes({'kit_smoke.py':b'raise RuntimeError("must never be copied")'})
  assets['cacert.pem']=b'synthetic certificate'
  build={'assets':{n:hashlib.sha1(v).hexdigest() for n,v in assets.items()},'extract_packages':[],'python_version':'3.13','unknown_preserved_field':{'wheel':'keep-me'}}
  assets['build.json']=json.dumps(build).encode()
  owned={'owned/A.class':b'\xca\xfe\xba\xbeA'};deps={'chaquo/B.class':b'\xca\xfe\xba\xbeB','chaquo/C.class':b'\xca\xfe\xba\xbeC'}
  if duplicate:deps['owned/A.class']=owned['owned/A.class'] if duplicate=='same' else b'\xca\xfe\xba\xbeDIFFERENT'
  self.aar_members={**{'assets/chaquopy/'+k:v for k,v in assets.items()},'classes.jar':zipbytes(owned),'libs/chaquopy_java-17.2.0.jar':zipbytes(deps),'jni/arm64-v8a/libpython3.13.so':elf(b'p'),'AndroidManifest.xml':b'<manifest/>'}
  self.save_aar()
  for name,raw in (('ao.so',self.ao),('media.so',self.media),('profile.tsv',self.profile)):(root/name).write_bytes(raw)
 def save_aar(self):
  data=zipbytes(self.aar_members);(self.root/'runtime.aar').write_bytes(data);self.pins['aar']=sha(data)
 @contextlib.contextmanager
 def patched(self):
  with mock.patch.dict(m.PINS,self.pins,clear=True),mock.patch.object(m,'EXPECTED_SOURCE_COUNT',2),mock.patch.object(m,'EXPECTED_OUTPUT_COUNT',2),mock.patch.object(m,'EXPECTED_CLASS_COUNT',3),mock.patch.object(m,'EXPECTED_BASE_ELF_COUNT',1),mock.patch.object(m,'REQUIRED_JNI',frozenset({'libpython3.13.so'})),mock.patch.object(m,'BOOTSTRAP_NATIVE',frozenset()),mock.patch.object(m,'_require_apfs',lambda parent:None):yield
 def run(self,name='out'):
  with self.patched():return m.build_runtime(aar=self.root/'runtime.aar',ao_lib=self.root/'ao.so',media_lib=self.root/'media.so',profile=self.root/'profile.tsv',repo=self.repo,out=self.root/name)

class OriginalRuntimePackagingTests(unittest.TestCase):
 def fixture(self,**kw):
  root=Path(tempfile.mkdtemp(prefix='case-',dir=EXTERNAL));return Fixture(root,**kw)
 def test_deterministic_package_and_manifest(self):
  f=self.fixture();a=f.run('out-a');b=f.run('out-b');oa=f.root/'out-a';ob=f.root/'out-b'
  al=json.loads((oa/'packaging-allowlist.json').read_text());self.assertEqual(al['schema'],m.SCHEMA);self.assertEqual(al,json.loads((ob/'packaging-allowlist.json').read_text()))
  for row in al['files']:
   self.assertTrue(row['path'].startswith(('assets/','lib/')));data=(oa/row['path']).read_bytes();self.assertEqual((len(data),sha(data)),(row['bytes'],row['sha256']))
  self.assertFalse(any(x['path'].startswith(('jars/','proof/')) for x in al['files']))
  self.assertEqual(a['java_unique_classes'],3);self.assertEqual(len(a['java_classpath']),2)
  with zipfile.ZipFile(oa/'assets/chaquopy/app.imy') as z:
   self.assertEqual(set(z.namelist()),{p.removeprefix('tools/') for p in m.SOURCE_PATHS}|set(m.GENERATED))
   self.assertNotIn('kit_smoke.py',z.namelist());self.assertIn('stage/pack_cars.py',z.namelist());self.assertIn('stage/__init__.py',z.namelist())
  build=json.loads((oa/'assets/chaquopy/build.json').read_text());self.assertEqual(build['extract_packages'],['original_convert','stage']);self.assertEqual(build['unknown_preserved_field'],{'wheel':'keep-me'})
  self.assertEqual(build['assets']['app.imy'],hashlib.sha1((oa/'assets/chaquopy/app.imy').read_bytes()).hexdigest())
  self.assertTrue((oa/'proof/license-inventory.json').exists())
 def test_bad_pin_and_existing_output_are_fail_closed(self):
  f=self.fixture();f.pins['ao']='0'*64
  with self.assertRaisesRegex(m.PackagingError,'pin mismatch'):f.run()
  self.assertFalse((f.root/'out').exists())
  f=self.fixture();(f.root/'out').mkdir();(f.root/'out/keep').write_bytes(b'keep')
  with self.assertRaisesRegex(m.PackagingError,'already exists'):f.run()
  self.assertEqual((f.root/'out/keep').read_bytes(),b'keep')
 def test_missing_required_runtime_sources_fail(self):
  for name in ('engine','cars','media','release_assets'):
   f=self.fixture();remove_fixture(f.repo/f'tools/original_convert/{name}.py',f.root)
   with self.assertRaises((OSError,m.PackagingError)):f.run()
   self.assertFalse((f.root/'out').exists())
 def test_missing_stage_helper_and_unreviewed_import(self):
  f=self.fixture();remove_fixture(f.repo/'tools/stage/pack_vinyl.py',f.root)
  with self.assertRaises((OSError,m.PackagingError)):f.run()
  f=self.fixture();(f.repo/'tools/original_convert/extras.py').write_text('import pack_unreviewed\n')
  with self.assertRaisesRegex(m.PackagingError,'unreviewed'):f.run()
 def test_never_collect_unrelated_original_material_or_buildtools(self):
  f=self.fixture()
  for path in ('tools/original_convert/main','tools/original_convert/raw.tga','tools/original_convert/native_backend/build_native.py','tools/stage/generated_original_data.h','tools/stage/wrong.json'):
   p=f.repo/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'not reviewed')
  f.run()
  with zipfile.ZipFile(f.root/'out/assets/chaquopy/app.imy') as z:self.assertTrue(all(n.endswith('.py') for n in z.namelist()));self.assertFalse(any('build_native' in n for n in z.namelist()))
 def test_java_identical_duplicate_removed_conflict_rejected(self):
  f=self.fixture(duplicate='same');f.run();j=json.loads((f.root/'out/proof/java-classes.json').read_text());self.assertEqual(len(j['removed_identical_duplicates']),1)
  names=[]
  for p in (f.root/'out/jars').iterdir():
   with zipfile.ZipFile(p) as z:names.extend(n for n in z.namelist() if n.endswith('.class'))
  self.assertEqual(len(names),len(set(names)))
  f=self.fixture(duplicate='different')
  with self.assertRaisesRegex(m.PackagingError,'conflicting duplicate'):f.run()
 def test_unknown_native_path_missing_lib_and_alignment(self):
  for path in ('jni/x86_64/libbad.so','jni/arm64-v8a/libbad.so','assets/chaquopy/unknown-native.so','assets/data/sprite/a.tga'):
   f=self.fixture();f.aar_members[path]=elf();f.save_aar()
   with self.assertRaises(m.PackagingError):f.run()
  f=self.fixture();del f.aar_members['jni/arm64-v8a/libpython3.13.so'];f.save_aar()
  with self.assertRaisesRegex(m.PackagingError,'incomplete'):f.run()
  f=self.fixture(ao=elf(alignment=4096))
  with self.assertRaisesRegex(m.PackagingError,'16KiB'):f.run()
 def test_needed_closure_fails_unknown_dependency(self):
  f=self.fixture(ao=elf(needed='libnot_packaged.so'))
  with self.assertRaisesRegex(m.PackagingError,'unresolved native'):f.run()
 def test_profile_and_release_metadata_must_bind(self):
  f=self.fixture();p=f.repo/'tools/original_convert/release_assets.py';p.write_text(p.read_text().replace('synthetic-reviewed','wrong'))
  with self.assertRaisesRegex(m.PackagingError,'pin mismatch'):f.run()
  f=self.fixture();f.aar_members['assets/chaquopy/build.json']=b'{"assets":{},"python_version":"3.13","extract_packages":[]}' ;f.save_aar()
  with self.assertRaisesRegex(m.PackagingError,'asset inventory'):f.run()
 def test_zip_traversal_duplicate_symlink_and_budgets(self):
  for name in ('../escape','/abs','C:/escape','a\\b','a/./b','a//b'):
   b=io.BytesIO()
   with zipfile.ZipFile(b,'w') as z:z.writestr(name,b'x')
   with self.assertRaises(m.PackagingError):m.safe_zip(b.getvalue(),'test')
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('a',b'x');z.writestr('a',b'x')
  with self.assertRaises(m.PackagingError):m.safe_zip(b.getvalue(),'test')
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:
   i=zipfile.ZipInfo('linked');i.create_system=3;i.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(i,b'elsewhere')
  with self.assertRaises(m.PackagingError):m.safe_zip(b.getvalue(),'test')
  with mock.patch.object(m,'MAX_MEMBER_BYTES',1):
   with self.assertRaises(m.PackagingError):m.safe_zip(zipbytes({'big':b'xx'}),'test')
 def test_symlink_sources_rejected_and_no_target_execution(self):
  f=self.fixture();p=f.repo/'tools/stage/pack.py';remove_fixture(p,f.root);p.symlink_to(f.root/'ao.so')
  with self.assertRaises((OSError,m.PackagingError)):f.run()
  f=self.fixture();(f.repo/'tools/original_convert/engine.py').write_text('raise RuntimeError("never execute")\n')
  f.run() # ast.parse only, no import or eval.
 def test_fixed_public_license_whitelist_is_verbatim_and_required(self):
  f=self.fixture();f.run()
  for source,destination in m.LICENSE_PATHS:self.assertEqual((f.repo/source).read_bytes(),(f.root/'out'/destination).read_bytes())
  names=json.loads((f.root/'out/packaging-allowlist.json').read_text())['files']
  self.assertEqual(sum(row['path'].startswith('assets/original-convert/licenses/') for row in names),len(m.LICENSE_PATHS))
  f=self.fixture();remove_fixture(f.repo/m.LICENSE_PATHS[0][0],f.root)
  with self.assertRaises((OSError,m.PackagingError)):f.run()
  self.assertFalse((f.root/'out').exists())
 def test_exclusive_leaf_write_never_overwrites(self):
  root=Path(tempfile.mkdtemp(prefix='exclusive-',dir=EXTERNAL));m._write_new(root,'assets/keep',b'original')
  with self.assertRaises(FileExistsError):m._write_new(root,'assets/keep',b'changed')
  self.assertEqual((root/'assets/keep').read_bytes(),b'original')
 def test_apfs_output_query_real_host(self):
  if os.uname().sysname!='Darwin':self.skipTest('Darwin-only filesystem ABI')
  m._require_apfs(EXTERNAL)

if __name__=='__main__':unittest.main()
