import hashlib
import importlib.util
import os
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("story_defaults_extract", HERE / "tools/story_defaults_extract.py")
x = importlib.util.module_from_spec(spec)
spec.loader.exec_module(x)
ELF = Path("/Volumes/MacSave/WMMT3 Phone/Fulldata/Wangan Midnight 3DX+[banwu]/Wangan Midnight 3DX+/main")
CSV = Path("/Volumes/CodexWork/wmmt3dx-story-defaults-2e659115.csv")

class IndexTests(unittest.TestCase):
 def test_first_and_later_loop(self):
  for n in range(100):
   self.assertEqual(x.story_index(0,n),n)
   self.assertEqual(x.story_index(1,n),100+n if n<10 else n)
   self.assertEqual(x.story_index(3,n),100+n if n<10 else n)
   self.assertEqual(x.story_index(2,n),110 if n==9 else 100+n if n<10 else n)
  self.assertEqual(x.story_index(2,10),10) # episode 11 is unchanged
 def test_bounds(self):
  for loop,n in [(-1,0),(0,-1),(0,100),(0,111)]:
   with self.assertRaises(x.Invalid): x.story_index(loop,n)
 def test_wrong_sha(self):
  with self.assertRaises(x.Invalid): x.Elf(b"bad")
 def test_missing_assets(self):
  with self.assertRaises(x.Invalid): x.parse_menu("")
 def test_unmapped_and_duplicate_filenames(self):
  text=(HERE / "src/menu.c").read_text(); groups=x.parse_menu(text)
  self.assertEqual([len(g) for g in groups],[22,25,14])
  with self.assertRaises(x.Invalid): x.parse_menu(text.replace('"wm2_02"','"wm2_01"',1))

@unittest.skipUnless(ELF.is_file(), "original ELF not available")
class OriginalTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.data=ELF.read_bytes(); cls.digest=hashlib.sha256(cls.data).hexdigest()
  cls.elf=x.Elf(cls.data); cls.groups=x.parse_menu((HERE / "src/menu.c").read_text()); cls.rows=x.extract(cls.elf,cls.groups)
 def test_read_only_sha(self):
  self.assertEqual(self.digest,x.SHA256)
  self.assertEqual(hashlib.sha256(ELF.read_bytes()).hexdigest(),self.digest)
 def test_111_rows_three_groups_and_csv(self):
  self.assertEqual(len(self.rows),111)
  for day,lines,ids,fallback in self.rows:
   self.assertIn(day,(0,1));self.assertEqual(len(lines),3)
   for g,line in enumerate(lines): self.assertTrue(0<line<len(self.groups[g])-1)
  if CSV.is_file(): x.check_csv(self.rows,CSV)
 def test_fallback_episodes_one_and_eight(self):
  for index in (0,7):
   for g in range(3):
    first=self.elf.i32(x.STORY+index*0x158+0x54+4*g)
    second=self.elf.i32(x.STORY+index*0x158+0x54+4*(15+g))
    self.assertEqual(self.rows[index][2][g],first if first!=-1 else second)
    self.assertEqual(self.rows[index][3][g],first==-1)
 def test_missing_song_fails_closed(self):
  groups=[list(g) for g in self.groups]; groups[1][1]="not_present"
  with self.assertRaises(x.Invalid): x.extract(self.elf,groups)
 def test_file_backed_boundaries(self):
  with self.assertRaises(x.Invalid): self.elf.read(0,4)
  with self.assertRaises(x.Invalid): self.elf.read(0xffffffff,2)

if __name__=="__main__": unittest.main()
