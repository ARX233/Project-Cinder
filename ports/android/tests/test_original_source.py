import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().with_name('source.py')
if not MODULE.is_file():
    MODULE = Path(__file__).resolve().parents[1] / 'tools/original_convert/source.py'
spec = importlib.util.spec_from_file_location('original_source_under_test', MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
WORK = Path('/Volumes/CodexWork/android135-original-convert-l809giqy')


def catalog(extra=(), **changes):
    rows = [{'path': 'main', 'bytes': 1, 'sha256': m.MAIN_SHA256}, *extra]
    obj = {'schema': 'wmmt-original-readset-v1', 'main_sha256': m.MAIN_SHA256,
           'files': sorted(rows, key=lambda row: row['path'])}
    obj.update(changes)
    return json.dumps(obj, separators=(',', ':')).encode()


def entry(name, data):
    return {'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='source-tests-', dir=WORK/'fixtures'))

    def new_tree(self):
        p = Path(tempfile.mkdtemp(prefix='case-', dir=self.root))
        (p/'data').mkdir()
        (p/'main').write_bytes(b'x')
        return p

    def parse(self, data):
        return m.ReviewedReadSet.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())

    def test_reviewed_metadata_pin_and_immutable_entries(self):
        data = catalog([entry('data/a', b'abc')])
        valid = self.parse(data)
        self.assertEqual(valid.total_bytes, 4)
        with self.assertRaises(TypeError): valid.files['data/b'] = m.SourceEntry(1, '0'*64)
        with self.assertRaises(m.OriginalInputError):m.ReviewedReadSet.parse(data, expected_sha256='0'*64)
        with self.assertRaises(m.OriginalInputError):m.ReviewedReadSet.parse(data, expected_sha256=None)

    def test_json_duplicates_and_schema_are_rejected(self):
        cases = [b'{"schema":1,"schema":2}', catalog(schema='future'), catalog(main_sha256='0'*64),
                 catalog(files=[]), b'{"schema":NaN}', catalog([{'path':'data/a','bytes':True,'sha256':'0'*64}])]
        for data in cases:
            with self.subTest(data=data[:100]), self.assertRaises(m.OriginalInputError):self.parse(data)

    def test_paths_aliases_and_file_parent_conflicts(self):
        for p in ['../a', '/data/a', 'data/a/../b', 'data//a', 'data/a\\b', 'data/a:', 'data/a.',
                  'data/a ', 'data/'+('/x'*65), 'save/player', 'data/e\u0301', 'data/a\x00']:
            with self.subTest(path=p), self.assertRaises(m.OriginalInputError):self.parse(catalog([entry(p,b'')]))
        for rows in [[entry('data/A',b'a'),entry('data/a',b'a')],
                     [entry('data/p',b'a'),entry('data/p/c',b'a')]]:
            with self.assertRaises(m.OriginalInputError):self.parse(catalog(rows))

    def test_read_exact_authorized_member_and_main_is_not_faked(self):
        p=self.new_tree();(p/'data/a').write_bytes(b'abc')
        with m.FileTreeSource(p,self.parse(catalog([entry('data/a',b'abc')]))) as source:
            self.assertEqual(source.read('data/a', max_bytes=3),b'abc')
            with self.assertRaises(m.OriginalInputError):source.read('data/a',max_bytes=2)
            with self.assertRaises(m.OriginalInputError):source.read('data/not-authorized',max_bytes=10)
            with self.assertRaises(m.OriginalInputError):source.read('main',max_bytes=100)
        with self.assertRaises(m.OriginalInputError):list(source.chunks('data/a'))

    def test_symlink_leaf_parent_and_fifo_are_not_read(self):
        p=self.new_tree();(p/'else').write_bytes(b'abc');(p/'data/a').symlink_to(p/'else')
        rs=self.parse(catalog([entry('data/a',b'abc')]))
        with m.FileTreeSource(p,rs) as source:
            with self.assertRaises(OSError):source.read('data/a',max_bytes=3)
        q=self.new_tree();(q/'outside').mkdir();(q/'outside/a').write_bytes(b'abc');(q/'data/link').symlink_to(q/'outside',target_is_directory=True)
        with m.FileTreeSource(q,self.parse(catalog([entry('data/link/a',b'abc')]))) as source:
            with self.assertRaises(OSError):source.read('data/link/a',max_bytes=3)
        f=self.new_tree();os.mkfifo(f/'data/fifo')
        with m.FileTreeSource(f,self.parse(catalog([entry('data/fifo',b'')]))) as source:
            with self.assertRaises(m.OriginalInputError):source.read('data/fifo',max_bytes=0)

    def test_corrupt_same_size_mutation_and_cancellation(self):
        p=self.new_tree();(p/'data/a').write_bytes(b'xyz')
        with m.FileTreeSource(p,self.parse(catalog([entry('data/a',b'abc')]))) as source:
            with self.assertRaises(m.OriginalInputError):source.read('data/a',max_bytes=3)
        (p/'data/a').write_bytes(b'abc')
        with m.FileTreeSource(p,self.parse(catalog([entry('data/a',b'abc')]))) as source:
            with self.assertRaises(m.ConversionCancelled):source.read('data/a',max_bytes=3,cancel=lambda:True)
            def mutate(*_): (p/'data/a').write_bytes(b'abc')
            with self.assertRaises(m.OriginalInputError):source.read('data/a',max_bytes=3,progress=mutate)

    def test_owned_output_never_overwrites_or_publishes(self):
        p=self.new_tree();(p/'data/a').write_bytes(b'abc');owned=m.OwnedOutput(self.root)
        with m.FileTreeSource(p,self.parse(catalog([entry('data/a',b'abc')]))) as source:
            self.assertEqual(owned.copy_from(source,'data/a','sound/a').size,3)
            with self.assertRaises(m.OriginalInputError):owned.copy_from(source,'data/a','sound/a')
            with self.assertRaises(m.OriginalInputError):owned.copy_from(source,'data/a','../a')
        self.assertEqual((owned.root/'sound/a').read_bytes(),b'abc')
        self.assertFalse((owned.root/'selection').exists())
        self.assertFalse(hasattr(owned,'publish'))
        self.assertEqual(set(owned.files),{'sound/a'})

    def test_failed_copy_has_no_success_record_and_retains_only_new_partial(self):
        p=self.new_tree();(p/'data/a').write_bytes(b'bad');owned=m.OwnedOutput(self.root)
        with m.FileTreeSource(p,self.parse(catalog([entry('data/a',b'abc')]))) as source:
            with self.assertRaises(m.OriginalInputError):owned.copy_from(source,'data/a','sound/a')
        self.assertFalse(owned.files)
        self.assertTrue((owned.root/'sound/a').is_file())
        self.assertEqual((p/'data/a').read_bytes(),b'bad')

    def test_external_snapshot_receipt_cannot_construct_verified_input(self):
        with self.assertRaises(m.OriginalInputError):m.VerifiedSnapshot(self.root, None, 0)

    def test_snapshot_bad_main_does_not_copy_other_files_or_become_ready(self):
        p=self.new_tree();(p/'data/a').write_bytes(b'abc')
        before=set(self.root.iterdir())
        with m.FileTreeSource(p,self.parse(catalog([entry('data/a',b'abc')]))) as source:
            with self.assertRaises(m.OriginalInputError):m.VerifiedSnapshot.create(source,self.root)
        made=set(self.root.iterdir())-before
        self.assertEqual(len(made),1)
        job=next(iter(made))
        self.assertTrue(job.name.startswith('original-source-'))
        self.assertFalse((job/'data/a').exists())
        self.assertFalse((job/'selection').exists())
        self.assertEqual((p/'main').read_bytes(),b'x')

    def test_snapshot_cancel_or_low_space_precedes_creation(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        p=self.new_tree();before=set(self.root.iterdir())
        with m.FileTreeSource(p,self.parse(catalog())) as source:
            with self.assertRaises(m.ConversionCancelled):m.VerifiedSnapshot.create(source,self.root,cancel=lambda:True)
            with patch.object(m.os,'statvfs',return_value=SimpleNamespace(f_bavail=0,f_frsize=4096)):
                with self.assertRaises(m.OriginalInputError):m.VerifiedSnapshot.create(source,self.root)
        self.assertEqual(set(self.root.iterdir()),before)


if __name__=='__main__':unittest.main()
