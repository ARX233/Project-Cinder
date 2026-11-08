import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'tools/original_convert/extras.py').is_file():
    ROOT=Path('/Volumes/MacSave/WMMT3 Phone/Re3DXPlus-github-sync/ports/android')
sys.path.insert(0,str(ROOT/'tools'))
from original_convert import extras as e
from original_convert.source import OriginalInputError


def data():
    names=[*e._FIXED,*('vinyl/car_%02d.vpk'%i for i in range(55))]
    return {'schema':'wmmt-original-extras-v1','files':[{'path':n,'bytes':100,'sha256':'a'*64} for n in sorted(names)]}


def parse(obj):
    b=json.dumps(obj,separators=(',',':')).encode()
    return e.parse_plan(b,expected_sha256=hashlib.sha256(b).hexdigest())


class ExtrasTests(unittest.TestCase):
    def test_complete_named_plan(self):
        plan=parse(data());self.assertEqual(len(plan.files),66)
        self.assertEqual(sum(n.startswith('vinyl/') for n,_ in plan.files),55)
        with self.assertRaises(OriginalInputError):e.parse_plan(b'{}',expected_sha256='0'*64)
        with self.assertRaises(OriginalInputError):e.parse_plan(b'{}',expected_sha256=None)

    def test_incomplete_unknown_duplicate_and_unsafe_paths(self):
        obj=data();obj['files'].pop()
        with self.assertRaises(OriginalInputError):parse(obj)
        for name in ['vinyl/../a.vpk','wmmt/save','main','data/main','traffic/unknown.wpk']:
            obj=data();obj['files'][0]['path']=name
            with self.subTest(name=name),self.assertRaises(OriginalInputError):parse(obj)
        obj=data();obj['files'][1]=obj['files'][0]
        with self.assertRaises(OriginalInputError):parse(obj)

    def test_row_schema_and_numeric_limits(self):
        for key,value in [('bytes',True),('bytes',0),('bytes',65*1024*1024),('sha256','A'*64),('path',None)]:
            obj=data();obj['files'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(OriginalInputError):parse(obj)
        obj=data();obj['files'][0]['external']='receipt'
        with self.assertRaises(OriginalInputError):parse(obj)

    def test_external_receipt_or_paths_never_publish(self):
        with self.assertRaises(OriginalInputError):e.convert_extras('/untrusted/source','/old/data',parse(data()),scratch_parent='/old/data')
        self.assertFalse(hasattr(e,'Ready'));self.assertFalse(hasattr(e,'publish'))


if __name__=='__main__':unittest.main()
