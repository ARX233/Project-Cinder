"""Car plan/snapshot/output safety tests, with no target-code execution.

Synthetic source roots, authenticated snapshots and outputs are external, under
WMMT_TEST_WORK_ROOT. A fake packaged decoder exercises only orchestration; real
265-car production conversion is independently recorded by the maintainer probe.
"""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'tools/original_convert/cars.py').is_file():
    ROOT=Path(os.environ['WMMT_TEST_REPO'])
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/stage')]
from original_convert import cars as c, source
from original_convert.source import OriginalInputError, ConversionCancelled
import lualite

sha=lambda raw:hashlib.sha256(raw).hexdigest()
WPK=struct.pack('<4sIIIfIII',b'WPK3',0,0,0,0.0,32,32,32)
MAIN=b'Synthetic non-executable source main fixture. '*4
STOCK=['gem_%02d'%i for i in range(3)]+['car_%02d'%i for i in range(3,54)]+['maz_GG3P_school']
CHARA=['chara_%02d'%i for i in range(51)]


def body_map():
    return {name:('normal','aero_a') if name.startswith('gem_') else c.BODIES for name in STOCK}


def plan_object(payload=WPK, absent=()):
    tasks=[]
    for folder,bodies in body_map().items():
        for body in bodies:
            tasks.append({'path':'cars/'+folder+c._SUFFIX[body]+'.wpk','folder':folder,'kind':'car','body':body,
                          'bytes':len(payload),'sha256':sha(payload)})
    tasks.extend({'path':'chara/'+folder+'.wpk','folder':folder,'kind':'characar','body':'normal',
                  'bytes':len(payload),'sha256':sha(payload)} for folder in CHARA)
    return {'schema':'wmmt-original-cars-v1','tasks':sorted(tasks,key=lambda row:row['path']),
            'absent_optional_sources':sorted(absent)}


def parse(value):
    raw=c._canonical(value)
    return c.parse_plan(raw,expected_sha256=sha(raw))


class PlanTests(unittest.TestCase):
    def test_complete_canonical_profile(self):
        plan=parse(plan_object())
        self.assertEqual(len(plan.tasks),265)
        self.assertEqual(sum(t.kind=='car' and t.body=='normal' for t in plan.tasks),55)
        self.assertEqual(sum(t.kind=='characar' for t in plan.tasks),51)
        self.assertFalse(hasattr(plan.tasks[0],'npaint'))

    def test_wrong_pin_bytes_and_noncanonical_serialization(self):
        raw=c._canonical(plan_object())
        for value,pin in ((raw,'0'*64),(raw,None),(raw.decode(),sha(raw)),(raw[:-1],sha(raw[:-1]))):
            with self.assertRaises(OriginalInputError):c.parse_plan(value,expected_sha256=pin)
        alternate=json.dumps(plan_object(),indent=2).encode()
        with self.assertRaises(OriginalInputError):c.parse_plan(alternate,expected_sha256=sha(alternate))

    def test_incomplete_counts_and_missing_normal_shadow(self):
        obj=plan_object();obj['tasks'].pop()
        with self.assertRaises(OriginalInputError):parse(obj)
        obj=plan_object();row=next(r for r in obj['tasks'] if r['kind']=='car' and r['body']=='normal')
        row['body']='aero_b';row['path']='cars/'+row['folder']+'_aeroB.wpk';obj['tasks'].sort(key=lambda r:r['path'])
        with self.assertRaises(OriginalInputError):parse(obj)

    def test_type_hash_range_and_forbidden_npaint_fields(self):
        for key,value in (('bytes',True),('bytes',31),('bytes',129*1024*1024),('folder','../bad'),
                          ('body',[]),('kind','othercar'),('sha256','A'*64),('path',None),('npaint',99)):
            obj=plan_object();obj['tasks'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(OriginalInputError):parse(obj)

    def test_path_binding_sort_duplicate_and_casefold_reject(self):
        for name in ('cars/../escape.wpk','chara/bad.wpk','data/evil.wpk','main','cars/x.wpk/file.wpk'):
            obj=plan_object();obj['tasks'][0]['path']=name
            with self.assertRaises(OriginalInputError):parse(obj)
        obj=plan_object();obj['tasks'][1]=dict(obj['tasks'][0])
        with self.assertRaises(OriginalInputError):parse(obj)
        obj=plan_object();obj['tasks'].reverse()
        with self.assertRaises(OriginalInputError):parse(obj)
        obj=plan_object();row=dict(obj['tasks'][0]);row['folder']=row['folder'].upper();row['path']=row['path'].upper().replace('CARS/','cars/').replace('.WPK','.wpk');obj['tasks'][1]=row;obj['tasks'].sort(key=lambda r:r['path'])
        with self.assertRaises(OriginalInputError):parse(obj)

    def test_optional_absence_safety_sort_duplicates_and_shadow(self):
        for absent in (['../escape'],['main'],['data/a','data/a'],['data/B','data/b'],['data/a','data/a/b'],['data/x/../a'],['data/x\\a'],['data/a\x00']):
            with self.subTest(absent=absent),self.assertRaises(OriginalInputError):parse(plan_object(absent=absent))
        obj=plan_object(absent=['data/a','data/b']);obj['absent_optional_sources'].reverse()
        with self.assertRaises(OriginalInputError):parse(obj)

    def test_duplicate_json_members_and_nonfinite_numbers_reject(self):
        raw=c._canonical(plan_object())
        bad=raw.replace(b'"schema":',b'"schema":"duplicate","schema":',1)
        with self.assertRaises(OriginalInputError):c.parse_plan(bad,expected_sha256=sha(bad))
        for token in (b'NaN',b'Infinity',b'1e999'):
            bad=raw.replace(b'"bytes":32',b'"bytes":'+token,1)
            with self.assertRaises(OriginalInputError):c.parse_plan(bad,expected_sha256=sha(bad))

    def test_authenticated_lua_double_separator_is_canonical_but_traversal_is_not(self):
        self.assertEqual(c._reference('data/car/foo//normal/shadow.igb'), 'data/car/foo/normal/shadow.igb')
        for value in ('/data/a', 'data/car/../a', 'data/./a', 'data/a\\\\b', 'main'):
            with self.assertRaises(OriginalInputError):c._reference(value)

    def test_external_roots_receipts_and_raw_task_tuples_are_not_inputs(self):
        plan=parse(plan_object())
        for snapshot,output,tasks in (('/original','/old',plan),({}, {},plan),('/original','/old',plan.tasks)):
            with self.assertRaises(OriginalInputError):c.convert_cars(snapshot,output,tasks)
        self.assertFalse(hasattr(c,'Ready'));self.assertFalse(hasattr(c,'publish'))


class ProductionBoundaryTests(unittest.TestCase):
    def setUp(self):
        parent=Path(os.environ['WMMT_TEST_WORK_ROOT']).resolve()
        self.temp=tempfile.TemporaryDirectory(prefix='cars-unit-',dir=parent)
        self.root=Path(self.temp.name)
        def cleanup():
            self.assertTrue(self.root.resolve().is_relative_to(parent));self.temp.cleanup()
        self.addCleanup(cleanup)
        self.original=self.root/'original';self.original.mkdir()
        self.cache=self.root/'cache';self.cache.mkdir()
        self.output_parent=self.root/'outputs';self.output_parent.mkdir()
        self.files={'main':MAIN,'data/wheel_list.lua':b'WheelList = {{name="dummy_wheel",igb_files={"data/wheel/dummy.igb"}}}',
                    'data/wheel/dummy.igb':b'own synthetic shared wheel'}
        self.configs={}
        self.bodies=body_map()
        for kind,folders in (('car',STOCK),('characar',CHARA)):
            for folder in folders:
                prefix=f'data/{kind}/{folder}/'
                bodies=self.bodies[folder] if kind=='car' else ('normal',)
                body_lua=','.join(body+'="'+prefix+body+'.igb"' for body in bodies)
                paint='{{page1="'+prefix+'paint.tga"}}'
                if folder=='maz_GG3P_school':
                    paint='{' + ','.join('{page1="'+prefix+('paint.tga' if i==0 else 'unused_%d.tga'%i)+'"}' for i in range(6)) + '}'
                text=('BodyIGB={'+body_lua+'}\nTireStatus={file={"'+prefix+'tire.igb"},wheel_name="dummy_wheel"}\n'
                      'BaseTexture={normal={page1="base.tga"}}\nBodyColorTexture={normal='+paint+'}\nShadowIGB={}\n')
                self.files[prefix+'car.lua']=text.encode()
                for body in bodies:self.files[prefix+body+'.igb']=('synthetic body '+body).encode()
                self.files[prefix+'tire.igb']=b'synthetic original tire'
                self.files[prefix+'paint.tga']=b'synthetic original paint'
        for name,data in self.files.items():
            path=self.original/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(source,'MAIN_SHA256',sha(MAIN)))
        self.stack.enter_context(patch.object(c,'MAIN_SHA256',sha(MAIN)))
        self.calls=[];self.old_fix_calls=[];self.rules_calls=[]
        self.pack=SimpleNamespace(TEX_ASTC=0,TEX_EXPORT=None,TEX_UPSCALED=None)
        self.initial_brakes=object();self.initial_ids=object()
        def old_fix(*args):self.old_fix_calls.append(args[:2])
        self.old_fix=old_fix
        self.car_module=SimpleNamespace(pack=self.pack,MAX_TEX=512,fix_stock_wheel_bgr=old_fix,
                                        BRAKE_LAMPS=self.initial_brakes,CAR_IDS=self.initial_ids)
        def configure(db):self.car_module.BRAKE_LAMPS=db;self.car_module.CAR_IDS={'bound':True}
        self.car_module.configure_brake_lamps=configure
        def pack_car(root,folder,paints,wheels,out,kind='car',body='normal'):
            self.calls.append((root,folder,paints,kind,body))
            if body!='normal':self.assertTrue((Path(out).parent/(folder+'.wpk')).is_file())
            self.car_module.fix_stock_wheel_bgr(folder,kind,{'name':'dummy_wheel'},{},[])
            with self.pack.open(out,'wb') as f:f.write(WPK)
        self.fake_packer=pack_car;self.car_module.pack_car=pack_car
        self.stack.enter_context(patch.object(c,'_modules',return_value=(self.car_module,lualite)))
        self.stack.enter_context(patch.dict(os.environ,{k:v for k,v in os.environ.items() if not k.startswith('WPK_') and k!='WMMT_MAIN'},clear=True))
        def support(*args,**kwargs):
            return {'packs':{n:1 for n in STOCK},'bodies':self.bodies,
                    'character_models':{n:{'model':247+i,'car':56+i} for i,n in enumerate(CHARA)},
                    'brake_lamps':{'cars':{n:i for i,n in enumerate(STOCK+CHARA)},'lamps':{}},
                    'provenance':{'lua_sources':{n+'/car.lua':{'bytes':len(self.files['data/car/'+n+'/car.lua']),'sha256':sha(self.files['data/car/'+n+'/car.lua'])} for n in STOCK}}}
        self.stack.enter_context(patch.object(c,'build_car_tables',side_effect=support))
        def derive(main,root,folders,**kwargs):
            self.rules_calls.append(list(folders));result={}
            for folder in folders:
                receipts=[{'path':'data/characar/'+folder+'/'+leaf,'bytes':len(self.files['data/characar/'+folder+'/'+leaf]),'sha256':sha(self.files['data/characar/'+folder+'/'+leaf])} for leaf in ('car.lua','tire.igb')]
                result[folder]=SimpleNamespace(rule_id=sha(folder.encode()),receipt=lambda receipts=receipts:{'source_receipts':receipts})
            return result
        self.derive=derive
        self.stack.enter_context(patch.object(c,'derive_chara_wheel_rules',side_effect=derive))
        self.stack.enter_context(patch.object(c,'apply_chara_wheel_colors',return_value={'applied':True}))
        self.runtime=self.stack.enter_context(patch('original_convert.runtime_check.validate_runtime',return_value={'finite_probe_only':True}))

    def snapshot(self,omit=()):
        rows=[{'path':name,'bytes':len(data),'sha256':sha(data)} for name,data in sorted(self.files.items()) if name not in omit]
        raw=c._canonical({'schema':'wmmt-original-readset-v1','main_sha256':sha(MAIN),'files':rows})
        readset=source.ReviewedReadSet.parse(raw,expected_sha256=sha(raw))
        with source.FileTreeSource(self.original,readset) as tree:
            return source.VerifiedSnapshot.create(tree,self.cache)

    def output(self):return source.OwnedOutput(self.output_parent)

    def assert_restored(self):
        self.assertIs(self.car_module.fix_stock_wheel_bgr,self.old_fix)
        self.assertIs(self.car_module.BRAKE_LAMPS,self.initial_brakes)
        self.assertIs(self.car_module.CAR_IDS,self.initial_ids)
        self.assertFalse(hasattr(self.pack,'open'))
        self.assertTrue(c._LOCK.acquire(False));c._LOCK.release()

    def test_complete_synthetic_api_265_and_school_one_paint(self):
        snap=self.snapshot();output=self.output();progress=[]
        receipt=c.convert_cars(snap,output,parse(plan_object()),progress=lambda *args:progress.append(args))
        self.assertEqual(len(output.files),265);self.assertEqual(len(receipt['files']),265)
        self.assertFalse(receipt['complete_dataset']);self.assertFalse(receipt['activated'])
        self.assertEqual(receipt['coverage'],'complete-component')
        self.assertEqual(len(self.calls),265);self.assertEqual(len(self.old_fix_calls),265)
        self.assertTrue(all(row[2]==1 for row in self.calls if row[1]=='maz_GG3P_school'))
        self.assertTrue(all(row[0]==str(snap.root) for row in self.calls))
        self.assertEqual(progress[-1],('convert-cars',265,265));self.assert_restored()

    def test_missing_mandatory_readset_member_fails_before_any_decoder(self):
        name='data/characar/chara_00/tire.igb';snap=self.snapshot(omit=[name]);output=self.output()
        with self.assertRaises(OriginalInputError):c.convert_cars(snap,output,parse(plan_object()))
        self.assertFalse(self.calls);self.assertFalse(self.rules_calls);self.runtime.assert_not_called();self.assertFalse(output.files);self.assert_restored()

    def test_unknown_missing_optional_fails_before_decode(self):
        name='data/car/gem_00/paint.tga';snap=self.snapshot(omit=[name])
        with self.assertRaises(OriginalInputError):c.convert_cars(snap,self.output(),parse(plan_object()))
        self.assertFalse(self.rules_calls);self.runtime.assert_not_called();self.assert_restored()

    def test_explicit_absence_ignores_unlisted_original_extra(self):
        name='data/car/gem_00/paint.tga';snap=self.snapshot(omit=[name])
        self.assertTrue((self.original/name).is_file());self.assertFalse((snap.root/name).exists())
        receipt=c.convert_cars(snap,self.output(),parse(plan_object(absent=[name])))
        self.assertEqual(receipt['optional_absences'][0]['path'],name);self.assert_restored()

    def test_absence_conflict_unknown_and_broken_link_reject_before_decode(self):
        name='data/car/gem_00/paint.tga'
        for absent in ([name],['data/unknown/nope.tga']):
            snap=self.snapshot()
            with self.assertRaises(OriginalInputError):c.convert_cars(snap,self.output(),parse(plan_object(absent=absent)))
        snap=self.snapshot(omit=[name]);target=snap.root/name
        target.symlink_to(snap.root/'missing')
        with self.assertRaises(OriginalInputError):c.convert_cars(snap,self.output(),parse(plan_object(absent=[name])))
        self.assertFalse(self.calls);self.runtime.assert_not_called();self.assert_restored()

    def test_partial_source_or_derived_body_closure_never_decodes(self):
        self.bodies=dict(self.bodies);self.bodies['car_03']=('normal','aero_a','aero_b')
        with self.assertRaises(OriginalInputError):c.convert_cars(self.snapshot(),self.output(),parse(plan_object()))
        self.assertFalse(self.rules_calls);self.runtime.assert_not_called();self.assert_restored()

    def test_original_metadata_receipt_keys_include_car_lua_suffix(self):
        support=c.build_car_tables.side_effect
        def wrong_keys(*args,**kwargs):
            table=support(*args,**kwargs)
            table['provenance']['lua_sources']={name.removesuffix('/car.lua'):row for name,row in table['provenance']['lua_sources'].items()}
            return table
        with patch.object(c,'build_car_tables',side_effect=wrong_keys),self.assertRaises(OriginalInputError):
            c.convert_cars(self.snapshot(),self.output(),parse(plan_object()))
        self.assertFalse(self.rules_calls);self.runtime.assert_not_called();self.assert_restored()

    def test_existing_owned_target_is_not_overwritten(self):
        output=self.output();name=parse(plan_object()).tasks[0].path;path=output.target(name);path.write_bytes(b'existing')
        with self.assertRaises(OriginalInputError):c.convert_cars(self.snapshot(),output,parse(plan_object()))
        self.assertEqual(path.read_bytes(),b'existing');self.assertFalse(self.calls);self.assert_restored()

    def test_exclusive_writer_rejects_raced_target_and_preserves_bytes(self):
        def race(root,folder,paints,wheels,out,**kw):
            self.assertFalse(Path(out).exists());Path(out).write_bytes(b'concurrent')
            self.fake_packer(root,folder,paints,wheels,out,**kw)
        self.car_module.pack_car=race;output=self.output()
        with self.assertRaises(OriginalInputError):c.convert_cars(self.snapshot(),output,parse(plan_object()))
        self.assertFalse(output.files);self.assert_restored()
        self.assertEqual((output.root/parse(plan_object()).tasks[0].path).read_bytes(),b'concurrent')

    def test_cancel_before_start_and_from_progress_restore_all_globals(self):
        snap=self.snapshot()
        with self.assertRaises(ConversionCancelled):c.convert_cars(snap,self.output(),parse(plan_object()),cancel=lambda:True)
        cancelled=False
        def progress(*args):
            nonlocal cancelled
            cancelled=True
        with self.assertRaises(ConversionCancelled):c.convert_cars(snap,self.output(),parse(plan_object()),cancel=lambda:cancelled,progress=progress)
        self.assertEqual(len(self.calls),1);self.assert_restored()

    def test_decode_exception_and_existing_pack_open_are_restored(self):
        marker=object();self.pack.open=marker
        self.car_module.pack_car=lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('synthetic decode failure'))
        with self.assertRaisesRegex(RuntimeError,'synthetic decode failure'):c.convert_cars(self.snapshot(),self.output(),parse(plan_object()))
        self.assertIs(self.pack.open,marker);delattr(self.pack,'open');self.assert_restored()

    def test_nonblocking_lock(self):
        snap=self.snapshot();output=self.output();plan=parse(plan_object());self.assertTrue(c._LOCK.acquire(False))
        try:
            with self.assertRaises(OriginalInputError):c.convert_cars(snap,output,plan)
        finally:c._LOCK.release()
        self.assertFalse(self.calls);self.assert_restored()

    def test_environment_overrides_and_bad_pack_globals_reject(self):
        snap=self.snapshot();plan=parse(plan_object())
        for key in ('WPK_TEX_ASTC','WPK_TEX_EXPORT','WPK_TEX_UPSCALED','WPK_ASTCENC','WPK_TEX_UPSCALED_MAX','WMMT_MAIN'):
            with patch.dict(os.environ,{key:'0'}),self.assertRaises(OriginalInputError):c.convert_cars(snap,self.output(),plan)
        for key in ('TEX_ASTC','TEX_EXPORT','TEX_UPSCALED'):
            setattr(self.pack,key,'forbidden')
            with self.assertRaises(OriginalInputError):c.convert_cars(snap,self.output(),plan)
            setattr(self.pack,key,None)
        self.assertFalse(self.calls);self.assert_restored()

    def test_known_runtime_png_probe_failure_prevents_rule_decode(self):
        self.runtime.side_effect=RuntimeError('PNG codec self-test failed')
        with self.assertRaisesRegex(RuntimeError,'PNG codec'):c.convert_cars(self.snapshot(),self.output(),parse(plan_object()))
        self.assertFalse(self.calls);self.assertFalse(self.rules_calls);self.assert_restored()

    def test_png_cannot_be_registered_as_wpk_even_with_matching_plan_hash(self):
        png=b'\x89PNG\r\n\x1a\n'+bytes(24)
        def pack_png(root,folder,paints,wheels,out,**kw):
            with self.pack.open(out,'wb') as f:f.write(png)
        self.car_module.pack_car=pack_png;output=self.output()
        with self.assertRaises(OriginalInputError):c.convert_cars(self.snapshot(),output,parse(plan_object(payload=png)))
        self.assertFalse(output.files);self.assert_restored()

    def test_rule_receipts_must_match_authenticated_input_before_packing(self):
        original=self.derive
        def wrong(*args,**kwargs):
            rules=original(*args,**kwargs)
            first=next(iter(rules));rules[first]=SimpleNamespace(rule_id='x',receipt=lambda:{'source_receipts':[{'path':'data/unbound.igb','bytes':1,'sha256':'a'*64}]})
            return rules
        with patch.object(c,'derive_chara_wheel_rules',side_effect=wrong),self.assertRaises(OriginalInputError):c.convert_cars(self.snapshot(),self.output(),parse(plan_object()))
        self.assertFalse(self.calls);self.assert_restored()

    def test_changed_plan_commitment_rejects_and_no_external_snapshot_adoption(self):
        snap=self.snapshot();output=self.output();plan=parse(plan_object())
        with self.assertRaises(OriginalInputError):c.convert_cars(snap,output,replace(plan,sha256='0'*64))
        with self.assertRaises(OriginalInputError):c.convert_cars(snap,output,plan.tasks)
        with self.assertRaises(OriginalInputError):source.VerifiedSnapshot(snap.root,snap.readset,snap.bytes)
        self.assertFalse(self.calls);self.assert_restored()


if __name__=='__main__':unittest.main(verbosity=2)
