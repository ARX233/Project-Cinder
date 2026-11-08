"""Host-only synthetic DXT1 and stock-wheel isolation tests."""
import ast, io, pathlib, random, struct, types, unittest
import numpy as np
from PIL import Image

source = pathlib.Path(__file__).resolve().parents[1] / "tools/stage/pack_cars.py"
tree = ast.parse(source.read_text())
nodes = [n for n in tree.body if (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "STOCK_WHEEL_BGR" for t in n.targets)) or (isinstance(n, ast.FunctionDef) and n.name == "fix_stock_wheel_bgr")]
pack = types.SimpleNamespace(WHEEL=0x100, TEX_UPSCALED=None)
ns = {"np": np, "pack": pack}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), ns)
fix = ns["fix_stock_wheel_bgr"]

def decode(c0, c1, bits):
    h = struct.pack("<4s7I44x", b"DDS ", 124, 0x81007, 4, 4, 8, 0, 1) + struct.pack("<2I4s5I", 32, 4, b"DXT1", 0, 0, 0, 0, 0) + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
    return list(Image.open(io.BytesIO(h + struct.pack("<HHI", c0, c1, bits))).convert("RGBA").getdata())

class Tests(unittest.TestCase):
    def tearDown(self): pack.TEX_UPSCALED = None
    def test_dxt_palette_order_and_transparency(self):
        rng = random.Random(114)
        pairs = [(0xf800, 0x1f), (0x1f, 0xf800), (0x1234, 0x1234)] + [(rng.randrange(65536), rng.randrange(65536)) for _ in range(2000)]
        for a,b in pairs:
            swap = lambda c: (c & 31) << 11 | (c & 0x7e0) | c >> 11
            x,y = swap(a),swap(b); bits = 0xe4e4e4e4; new = bits
            if (a > b) != (x > y):
                x,y = y,x; lut = (1,0,3,2) if a > b else (1,0,2,3)
                new = sum(lut[(bits >> (2*i)) & 3] << (2*i) for i in range(16))
            self.assertEqual([(b,g,r,alpha) for r,g,b,alpha in decode(a,b,bits)], decode(x,y,new))
    def test_target_and_non_target(self):
        data = struct.pack("<3H", 0xf800, 0x1f, 0x7e0)
        variants = [("sub_GC8", "sub_GC8_wheel", "gc8"), ("sub_GC8_RA", "sub_GC8_wheel", "gc8"), ("sub_GDB", "sub_GDB_wheel", "gdb"), ("sub_GDB_specC", "sub_GDB_wheel", "gdb"), ("sub_GDBF", "sub_GDBF_wheel", "gdbf")]
        for folder,wheel,key in variants:
            name = "F:/wheels/"+key+"_wheel01_mid.dds"
            tex = {name:(3,1,0,data), "tyre.dds":(3,1,0,data)}
            mesh = [(pack.WHEEL,name,0,None,None,None)]
            fix(folder,"car",{"name":wheel},tex,mesh)
            self.assertEqual(tex[name][3],struct.pack("<3H", 0x1f,0xf800,0x7e0))
            self.assertEqual(tex["tyre.dds"][3],data)
            for f,k in [("sub_GRB","car"),(folder,"characar")]:
                tex = {name:(3,1,0,data)}; fix(f,k,{"name":wheel},tex,mesh); self.assertEqual(tex[name][3],data)
    def test_fail_closed(self):
        name="gc8_wheel01_mid.dds"; data=struct.pack("<H",0xf800); wheel={"name":"sub_GC8_wheel"}
        mesh=[(pack.WHEEL,name,0,None,None,None)]
        for record in [(1,1,1,data),(1,1,2,data),(1,1,0,b""),(0,1,0,b"")]:
            tex={name:record}
            with self.assertRaises(ValueError): fix("sub_gc8","car",wheel,tex,mesh)
            self.assertEqual(tex[name],record)
        for bad in [[(0,name,0,None,None,None)],[(pack.WHEEL,name,0,None,None,(1,name,None,0))]]:
            tex={name:(1,1,0,data)}
            with self.assertRaises(ValueError): fix("sub_gc8","car",wheel,tex,bad)
            self.assertEqual(tex[name][3],data)
        pack.TEX_UPSCALED="/fake"; tex={name:(1,1,0,data)}
        with self.assertRaises(ValueError): fix("sub_gc8","car",wheel,tex,mesh)
        self.assertEqual(tex[name][3],data)

if __name__ == "__main__": unittest.main()
