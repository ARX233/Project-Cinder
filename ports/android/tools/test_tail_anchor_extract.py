import math
import struct
import unittest
import tempfile
from pathlib import Path
from unittest import mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "stage"))
from igb import Field, Obj
import tail_anchor_extract as t


def field(n, typ="ObjectRef"):
    return Field(typ, 0, 4, struct.pack("<i", n))

def matrix(values):
    return Field("Matrix44f", 8, 64, struct.pack("<16f", *values))

class Fixture:
    version = 8
    slot_offset = 0
    externals = {}
    names = ["TAIL_L1", "TAIL_R1"]
    def __init__(self):
        self.objects = []
        self.info = self.node("igSceneInfo")
        root = self.node("igAttrSet")
        a = self.node("igTransform"); a.fields[2] = field(0, "String"); a.fields[8] = matrix(t.IDENTITY)
        b = self.node("igTransform"); b.fields[2] = field(1, "String"); b.fields[8] = matrix(t.IDENTITY)
        self.info.fields[5] = field(root.index)
        self.connect(root, [a,b])
        self.root,self.a,self.b = root,a,b
    def node(self, typ):
        o=Obj(len(self.objects), typ); self.objects.append(o)
        if typ in t.TYPES:
            o.fields[2]=field(-1, 'String'); o.fields[7]=field(-1)
        if typ == 'igTransform': o.fields[11]=field(-1)
        return o
    def connect(self, parent, nodes):
        lst=self.node("igNodeList"); mem=self.node("igMemoryBlock")
        mem.mem=struct.pack("<%di"%len(nodes), *(n.index for n in nodes))
        lst.fields[2]=field(len(nodes), "Int"); lst.fields[4]=field(mem.index, "MemoryRef"); parent.fields[7]=field(lst.index)
    def of_type(self, typ):
        return [o for o in self.objects if o.type == typ]

class TailAnchorTests(unittest.TestCase):
    def test_static_full_matrix_and_path(self):
        f=Fixture(); values=list(t.IDENTITY); values[12:15]=[2,3,4]; f.a.fields[8]=matrix(values)
        result=t.extract_scene(f)
        self.assertEqual(result["TAIL_L1"]["matrix"], values)
        self.assertEqual(result["TAIL_R1"]["instance_path"], [1])
    def test_identity_parent(self):
        f=Fixture(); parent=f.node("igTransform"); parent.fields[8]=matrix(t.IDENTITY)
        f.connect(parent,[f.a]); f.connect(f.root,[parent,f.b])
        self.assertEqual(t.extract_scene(f)["TAIL_L1"]["instance_path"], [0,0])
        values=list(t.IDENTITY); values[12]=2; parent.fields[8]=matrix(values)
        with self.assertRaisesRegex(ValueError, "ancestor"): t.extract_scene(f)
    def test_duplicate_instance_missing_animation_unknown_cycle(self):
        f=Fixture(); f.connect(f.root,[f.a,f.a,f.b])
        with self.assertRaisesRegex(ValueError, "ambiguous"): t.extract_scene(f)
        f=Fixture(); f.connect(f.root,[f.a])
        with self.assertRaisesRegex(ValueError, "missing"): t.extract_scene(f)
        f=Fixture(); f.a.fields[10]=field(0)
        with self.assertRaisesRegex(ValueError, "animated"): t.extract_scene(f)
        f=Fixture(); f.root.type="Unknown"
        with self.assertRaisesRegex(ValueError, "unsupported"): t.extract_scene(f)
        f=Fixture(); f.connect(f.a,[f.root])
        with self.assertRaisesRegex(ValueError, "cyclic"): t.extract_scene(f)
    def test_nonfinite_and_invalid_reference(self):
        f=Fixture(); m=list(t.IDENTITY); m[2]=math.nan; f.a.fields[8]=matrix(m)
        with self.assertRaisesRegex(ValueError, "non-finite"): t.extract_scene(f)
        f=Fixture(); f.info.fields[5]=field(9999)
        with self.assertRaisesRegex(ValueError, "invalid"): t.extract_scene(f)

    def test_reject_wrong_field_types(self):
        for location, slot in [('info', 5), ('a', 2), ('root', 7), ('list', 2), ('list', 4), ('a', 11)]:
            with self.subTest(location=location, slot=slot):
                f=Fixture()
                obj = f.objects[struct.unpack('<i', f.root[7].raw)[0]] if location == 'list' else getattr(f, location)
                if obj[slot] is None:
                    obj.fields[slot] = field(-1)
                old = obj[slot]
                obj.fields[slot] = Field('Fake', slot, old.size, old.raw)
                with self.assertRaises(ValueError): t.extract_scene(f)
        f=Fixture(); f.a.fields[10]=field(-1)
        with self.assertRaisesRegex(ValueError, 'slot 10'): t.extract_scene(f)
        f=Fixture(); f.a.fields[11]=field(-1)
        self.assertIn('TAIL_L1', t.extract_scene(f))

    def test_reject_forged_matrix_field_type(self):
        f=Fixture(); f.a.fields[8]=Field('Int', 8, 64, struct.pack('<16f', *t.IDENTITY))
        with self.assertRaisesRegex(ValueError, 'invalid matrix'): t.extract_scene(f)

    def test_paths_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); manifest=root/'mapping.json'; output=root/'result.json'
            manifest.write_text('{"entries": []}')
            output.write_text('original')
            with self.assertRaises(ValueError): t.checked_path('relative', True)
            with self.assertRaises(ValueError): t.checked_path(str(root/'..'/'elsewhere'), False)
            link=root/'link'; link.symlink_to(manifest)
            with self.assertRaises(ValueError): t.checked_path(str(link), True)
            with mock.patch.object(t, 'convert', return_value={'test': 1}), mock.patch('sys.argv', ['tool',str(manifest),str(output)]):
                with self.assertRaises(FileExistsError): t.main()
            self.assertEqual(output.read_text(), 'original')

if __name__ == "__main__": unittest.main()
