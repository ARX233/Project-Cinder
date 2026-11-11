#!/usr/bin/env python3
"""Exercise the carryover generator without distributing original physics."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('carry_patch', ROOT / 'tools/recomp/story_carryover_patch.py')
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
SAMPLE = (b'#include "rc_runtime.h"\n'
          b'void f_8997bc8(void) {\n  RC_ENTRY(0x8997bc8u);\n}\n'
          b'void f_8997edc(void) {\n  RC_ENTRY(0x8997edcu);\n}\n')


class CarryoverPatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='carry-patch-')
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.c'
        self.source.write_bytes(SAMPLE)
        self.dest = self.root / 'private.c'
        self.digest = hashlib.sha256(SAMPLE).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, source, dest):
        with patch.object(MOD, 'ROOT', self.root), patch.object(MOD, 'EXPECTED', self.digest), \
             patch('sys.argv', ['story_carryover_patch.py', str(source), str(dest)]), \
             patch('sys.stdout', new_callable=io.StringIO):
            MOD.main()

    def test_exact_bridge_and_no_overwrite(self):
        self.run_main(self.source, self.dest)
        out = self.dest.read_bytes()
        self.assertIn(b'rc_story_carry_bridge = 0x53544331u', out)
        self.assertIn(b'rc_story_carry_save(); return;', out)
        self.assertIn(b'rc_story_carry_load(); return;', out)
        self.assertNotIn(b'mock_save', out)
        with self.assertRaises(FileExistsError):
            self.run_main(self.source, self.dest)
        self.assertEqual(self.dest.read_bytes(), out)
        self.assertEqual(self.source.read_bytes(), SAMPLE)

    def test_wrong_hash_and_outside_root_rejected(self):
        self.source.write_bytes(SAMPLE + b'changed')
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.run_main(self.source, self.dest)
        self.assertFalse(self.dest.exists())
        self.source.write_bytes(SAMPLE)
        with self.assertRaisesRegex(ValueError, 'under'):
            self.run_main(self.source, self.root.parent / 'unsafe-output.c')

    def test_wrong_source_shape_and_nonprivate_parent_rejected(self):
        self.source.write_bytes(SAMPLE.replace(b'f_8997edc', b'f_8997edd'))
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.run_main(self.source, self.dest)
        self.source.write_bytes(SAMPLE)
        os.chmod(self.root, 0o755)
        try:
            with self.assertRaisesRegex(ValueError, 'private'):
                self.run_main(self.source, self.dest)
        finally:
            os.chmod(self.root, 0o700)


if __name__ == '__main__':
    unittest.main()
