import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'tools/original_convert/wheels.py').is_file():
    ROOT=Path('/Volumes/MacSave/WMMT3 Phone/Re3DXPlus-github-sync/ports/android')
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/stage')]
from original_convert import wheels as w
from original_convert.source import OriginalInputError


def encoded(tasks=None,**updates):
    row={'path':'wheels/rsm_high.wpk','kind':'menu','name':'rsm_high','texture_set':0,'bytes':1666024,
         'sha256':'efdb6691fcbe68917e9ac0a7299ea75ddf925376192983622450dc68e0afc349'}
    row.update(updates)
    return json.dumps({'schema':'wmmt-original-wheels-v1','tasks':[row] if tasks is None else tasks},separators=(',',':')).encode()


def parse(data):return w.parse_plan(data,expected_sha256=hashlib.sha256(data).hexdigest())


class WheelTests(unittest.TestCase):
    def test_plan_bindings_and_pin(self):
        tasks=parse(encoded());self.assertEqual(tasks[0].name,'rsm_high')
        with self.assertRaises(OriginalInputError):w.parse_plan(encoded(),expected_sha256='0'*64)
        with self.assertRaises(OriginalInputError):w.parse_plan(encoded(),expected_sha256=None)

    def test_invalid_names_paths_counts_and_types(self):
        for updates in [{'path':'wheels/../rsm_high.wpk'},{'name':'../rsm_high'}, {'texture_set':True},
                        {'bytes':True},{'bytes':0},{'bytes':128*1024*1024},{'sha256':'A'*64},
                        {'kind':'external'},{'name':'different'}, {'texture_set':1}]:
            with self.subTest(updates=updates),self.assertRaises(OriginalInputError):parse(encoded(**updates))
        with self.assertRaises(OriginalInputError):parse(encoded(tasks=[]))
        row=json.loads(encoded())['tasks'][0]
        with self.assertRaises(OriginalInputError):parse(encoded(tasks=[row,row]))

    def test_duplicate_schema_member_rejected(self):
        data=b'{"schema":"wmmt-original-wheels-v1","schema":"wmmt-original-wheels-v1","tasks":[]}'
        with self.assertRaises(OriginalInputError):parse(data)

    def test_cannot_use_external_tree_or_publish(self):
        with self.assertRaises(OriginalInputError):w.convert_wheels('/external/source','/external/output',parse(encoded()))
        self.assertFalse(hasattr(w,'publish'))
        self.assertFalse(hasattr(w,'Ready'))

    def load_pack_car_fresh(self):
        spec=importlib.util.spec_from_file_location('pack_car_test_'+str(id(self)),ROOT/'tools/stage/pack_cars.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def test_wheel_import_does_not_read_generated_brake_table(self):
        module=self.load_pack_car_fresh()
        self.assertIsNone(module.BRAKE_LAMPS)
        self.assertIsNone(module.CAR_IDS)
        self.assertTrue(callable(module.pack_menu_wheel))
        self.assertTrue(callable(module.pack_wheel))

    def test_explicit_car_support_schema(self):
        module=self.load_pack_car_fresh()
        db={'cars':{'car_A':5},'lamps':{'5 0':['car_A',31,0]}}
        module.configure_brake_lamps(db)
        self.assertEqual(module.brake_lamp('CAR_A','normal'),('data/car/brakelamp/brakelamp_car_A.igb',(31,0)))
        for bad in [{},{'cars':{},'lamps':{},'external':'input'},
                    {'cars':{'x':True},'lamps':{}},
                    {'cars':{},'lamps':{'1 0':['../x',0,0]}},
                    {'cars':{},'lamps':{'1 0':['x',32,0]}},
                    {'cars':{},'lamps':{'1 0':['x',False,0]}}]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):module.configure_brake_lamps(bad)


if __name__=='__main__':unittest.main()
