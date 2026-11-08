import hashlib,json,os
from pathlib import Path
import struct,sys,tempfile,unittest,uuid
ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'tools/original_convert/engine.py').is_file():ROOT=Path('/Volumes/MacSave/WMMT3 Phone/Re3DXPlus-github-sync/ports/android')
sys.path.insert(0,str(ROOT/'tools'))
from original_convert import engine,validation
from original_convert.source import OriginalInputError,OwnedOutput,SourceEntry,MAIN_SHA256

def encoded(obj):return (json.dumps(obj,sort_keys=True,separators=(',',':'))+'\n').encode()
def digest(b):return hashlib.sha256(b).hexdigest()
def bundle_fixture():
    readset=encoded({'schema':'wmmt-original-readset-v1','main_sha256':MAIN_SHA256,'files':[
        {'path':'data/a','bytes':1,'sha256':digest(b'a')},{'path':'main','bytes':24855892,'sha256':MAIN_SHA256}]})
    targets=[{'path':f'f{n:04d}','max_bytes':1,'sha256':digest(b'a'),'kind':'fixed'} for n in range(1798)]
    recipe=encoded({'schema':engine.PROFILE_SCHEMA,'profile_id':'test-main2e','runtime':{},
         'native':{'liboa_native.so':'d'*64,'liboc_media_overlay.so':'e'*64},
         'raw':[{'path':f'f{n:04d}','source':'data/a'} for n in range(1029)],
         'wheels':{},'cars':{},'extras':{},'media':{},'outputs':targets})
    return {'readset':readset,'recipe':recipe,'readset_sha256':digest(readset),'recipe_sha256':digest(recipe),
            'profile_sha256':'c'*64,'profile_id':'test-main2e'}

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='engine-',dir=os.environ.get('WMMT_TEST_WORK_ROOT','/Volumes/CodexWork/android135-original-convert-l809giqy/tmp'))
        self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.bundle=bundle_fixture()
    def job(self):
        root=self.root/'re3dxplus-original-jobs'/str(uuid.uuid4());root.mkdir(parents=True)
        (root/'outputs').mkdir();(root/'snapshots').mkdir()
        job={'schema':engine.SCHEMA,'job_id':root.name,'nonce':'a'*64,'source_kind':'zip','source_path':'incoming.zip'}
        for key in ('profile_id','profile_sha256','readset_sha256','recipe_sha256'):job[key]=self.bundle[key]
        (root/'job.json').write_bytes(encoded(job))
        (root/'owner.tsv').write_text('WMMT-ORIGINAL-JOB-1\njob\t%s\nnonce\t%s\nprofile\t%s\nEND\n'%(root.name,job['nonce'],job['profile_sha256']))
        return root,job
    def test_private_job_binding(self):
        root,job=self.job();self.assertEqual(engine.validate_job(root,self.bundle),(root,job))
        for field,value in [('nonce','bad'),('job_id',str(uuid.uuid4())),('source_path','../../olddata'),('profile_sha256','b'*64),('schema','player-receipt')]:
            altered=dict(job);altered[field]=value;(root/'job.json').write_bytes(encoded(altered))
            with self.subTest(field=field),self.assertRaises(OriginalInputError):engine.validate_job(root,self.bundle)
        (root/'job.json').write_bytes(encoded(job));(root/'completion.tsv').write_text('partial')
        with self.assertRaises(OriginalInputError):engine.validate_job(root,self.bundle)
    def test_private_metadata_symlink_and_fifo(self):
        target=self.root/'target';target.write_bytes(b'a');link=self.root/'link';link.symlink_to(target)
        with self.assertRaises(OSError):engine._small(link,16)
        fifo=self.root/'pipe';os.mkfifo(fifo)
        with self.assertRaises(OriginalInputError):engine._small(fifo,16)
        with self.assertRaises(OriginalInputError):engine._small(target,0)
    def test_signed_recipe_closure(self):
        rs,recipe,targets=engine.parse_recipe(self.bundle);self.assertEqual(len(targets),1798);self.assertEqual(len(recipe['raw']),1029)
        for mutation in ('missing','alias','raw-digest','unknown-generated','pin'):
            bundle=dict(self.bundle);obj=json.loads(bundle['recipe'])
            if mutation=='missing':obj['outputs'].pop()
            elif mutation=='alias':obj['outputs'][1]['path']=obj['outputs'][0]['path']
            elif mutation=='raw-digest':obj['outputs'][0]['sha256']='b'*64
            elif mutation=='unknown-generated':obj['outputs'][0]['sha256']=None
            if mutation!='pin':bundle['recipe']=encoded(obj);bundle['recipe_sha256']=digest(bundle['recipe'])
            else:bundle['recipe_sha256']='b'*64
            with self.subTest(mutation=mutation),self.assertRaises(OriginalInputError):engine.parse_recipe(bundle)
    def test_complete_ownership_and_mutation_detection(self):
        output=OwnedOutput(self.root);_,_,targets=engine.parse_recipe(self.bundle)
        for name in targets:
            output.target(name).write_bytes(b'a');output.files[name]=SourceEntry(1,digest(b'a'))
        rows=validation.verify_owned_outputs(output,targets);self.assertEqual(len(rows),1798)
        (output.root/'f0010').write_bytes(b'b')
        with self.assertRaises(OriginalInputError):validation.verify_owned_outputs(output,targets)
        (output.root/'f0010').write_bytes(b'a');(output.root/'unknown').write_text('not-a-job-output')
        with self.assertRaises(OriginalInputError):validation.verify_owned_outputs(output,targets)
    def test_partial_never_completion(self):
        output=OwnedOutput(self.root)
        with self.assertRaises(OriginalInputError):validation.completion_bytes({},output,[])
        with self.assertRaises(OriginalInputError):validation.verify_owned_outputs(output,{})
    def test_ao_structure_and_layout(self):
        path=self.root/'a.ao';name=b'body'.ljust(48,b'\0')
        path.write_bytes(b'WAO1'+struct.pack('<I',1)+name+struct.pack('<HH',256,256)+b'\xff'*65536)
        fd=os.open(path,os.O_RDONLY)
        try:
            expected=[{'name_hex':name.hex(),'width':256,'height':256}]
            self.assertEqual(validation.validate_ao_fd(fd,expected)['maps'],1)
            with self.assertRaises(OriginalInputError):validation.validate_ao_fd(fd,[])
        finally:os.close(fd)
        with path.open('ab') as f:f.write(b'tail')
        fd=os.open(path,os.O_RDONLY)
        try:
            with self.assertRaises(OriginalInputError):validation.validate_ao_fd(fd,expected)
        finally:os.close(fd)
    def test_signed_helper_origin_is_fixed(self):
        before=list(sys.path)
        try:
            engine._ensure_signed_helpers()
            import stage
            self.assertEqual(Path(stage.__file__).absolute(),ROOT/'tools/stage/__init__.py')
            self.assertIn(str(ROOT/'tools/stage'),sys.path)
            self.assertNotIn(str(self.root),sys.path)
        finally:sys.path[:]=before
    def test_foreign_stage_module_rejected(self):
        import types
        from unittest.mock import patch
        with patch.dict(sys.modules,{'stage':types.SimpleNamespace(__file__=str(self.root/'__init__.py'))}):
            with self.assertRaisesRegex(OriginalInputError,'outside the signed'):engine._ensure_signed_helpers()
    def test_completion_is_distinct_from_legacy_dmf(self):
        output=OwnedOutput(self.root);root,job=self.job()
        rows=[{'path':f'f{n:04d}','bytes':1,'sha256':digest(b'a')} for n in range(1798)]
        raw=validation.completion_bytes(job,output,rows)
        self.assertTrue(raw.startswith(b'WMMT-ORIGINAL-COMPLETION-1\n'));self.assertTrue(raw.endswith(b'END\n'))
        self.assertNotIn(b'DMF1',raw);self.assertNotIn(b'Ready',raw)
        self.assertFalse((root/'completion.tsv').exists())

if __name__=='__main__':unittest.main()
