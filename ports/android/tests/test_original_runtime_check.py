import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
if not (ROOT/'tools/original_convert/runtime_check.py').is_file():
    ROOT=Path('/Volumes/MacSave/WMMT3 Phone/Re3DXPlus-github-sync/ports/android')
sys.path.insert(0,str(ROOT/'tools'))
from original_convert import runtime_check as r
import numpy as np


class RuntimeCheckTests(unittest.TestCase):
    def test_real_numeric_and_codecs_are_finite_probes_only(self):
        result=r.validate_runtime()
        self.assertTrue(result['finite_probe_only'])
        self.assertTrue(all(result['numeric'].values()))
        self.assertTrue(all(result['codecs'].values()))

    def test_wrong_release_version_profile_rejected(self):
        with self.assertRaises(r.RuntimeCheckError):r.validate_runtime(expected_versions={})
        with self.assertRaises(r.RuntimeCheckError):r.validate_runtime(expected_versions={'python':'0','numpy':'0','pillow':'0'})

    def test_bad_float32_identity_product_is_rejected(self):
        class BadArray(np.ndarray):
            def __matmul__(self,other):return np.zeros(self.shape,dtype=np.float32)
        class BadNumpy:
            def array(self,*args,**kwargs):return np.array(*args,**kwargs).view(BadArray)
            def __getattr__(self,key):return getattr(np,key)
        with self.assertRaisesRegex(r.RuntimeCheckError,'identity'):r._check_numpy(BadNumpy())

    def test_nonfinite_affine_product_is_rejected(self):
        class BadArray(np.ndarray):
            def __matmul__(self,other):
                if np.array_equal(other,np.eye(4,dtype=np.float32)):
                    return np.array(self,dtype=np.float32)
                return np.full(self.shape,np.nan,dtype=np.float32)
        class BadNumpy:
            def array(self,*args,**kwargs):return np.array(*args,**kwargs).view(BadArray)
            def __getattr__(self,key):return getattr(np,key)
        with self.assertRaisesRegex(r.RuntimeCheckError,'affine'):r._check_numpy(BadNumpy())

    def test_global_game_paths_not_needed(self):
        import builtins
        real=builtins.open
        def no_game(path,*args,**kwargs):
            if isinstance(path,(str,bytes)) and ('wangan' in str(path).lower() or 'wmmt' in str(path).lower()):
                raise AssertionError('Synthetic self-test touched game source')
            return real(path,*args,**kwargs)
        with patch.object(builtins,'open',no_game):self.assertTrue(r.validate_runtime()['numeric']['float32_inverse'])


if __name__=='__main__':unittest.main()
