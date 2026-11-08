import copy
import hashlib
import os
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest
import tail_private_convert as t

def fixture():
    elf = bytearray(0x200 + 428)
    elf[:7] = b'\x7fELF\x01\x01\x01'
    struct.pack_into('<I', elf, 28, 52)
    struct.pack_into('<HH', elf, 42, 32, 1)
    struct.pack_into('<IIIIIIII', elf, 52, 1, 0x200, t.BASE, 0, 428, 428, 4, 4)
    struct.pack_into('<f', elf, 0x204, 1.25)
    m = [1,0,0,0, 0,1,0,0, 0,0,1,0, 3,4,5,1]
    c = {'schema':'wmmt-tail-anchors','version':1,'matrix_layout':'row-major-row-vector','space':'scene-root-parent; ancestors identity','records':[{'car_id':1,'body_id':2,'source_sha256':'a'*64,'anchors':{'TAIL_L1':{'matrix':m,'instance_path':[0]},'TAIL_R1':{'matrix':m[:],'instance_path':[1]}}}]}
    r = {'schema':'wmmt-tail-review','version':1,'main_sha256':hashlib.sha256(elf).hexdigest(),'entries':[{'pack':'CAR_1','car_id':1,'body_id':2,'igb_sha256':'a'*64,'width_scale':1.25}]}
    return c,r,bytes(elf)

class Tests(unittest.TestCase):
    def setUp(self): self.c,self.r,self.e=fixture()
    def convert(self): return t.convert(self.c,self.r,self.e,{self.r['main_sha256']})
    def test_valid(self):
        s=self.convert().decode()
        for part in ('{"CAR_1", 2u','3.00000000000000000e+00f','1.25000000000000000e+00f','TAIL_TRAIL_DATA_COUNT'): self.assertIn(part,s)
    def test_compile_generated_header(self):
        # Compile against the real production format, without game data.
        source_dir = Path(__file__).resolve().parent.parent / 'src'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'tail_trail_private_data.h').write_bytes(self.convert())
            (root / 'check.c').write_text('''\
#include "tail_trail_private_data.h"
#include <string.h>
int main(void) {
    const TailTrailDataRecord *r = &tail_trail_data[0];
    return TAIL_TRAIL_DATA_COUNT != 1 || strcmp(r->pack, "CAR_1") ||
        r->body != 2 || r->center[0].x != 3.0f ||
        r->center[1].y != 4.0f || r->center[0].z != 5.0f ||
        r->axis[0].x != 0.0f || r->axis[0].y != 1.0f ||
        r->axis[1].z != 0.0f || r->width_scale != 1.25f;
}
''', encoding='utf-8')
            executable = root / 'check'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(source_dir), str(root / 'check.c'),
                            '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True)
    def test_approval(self):
        with self.assertRaises(ValueError): t.convert(self.c,self.r,self.e)
    def test_mapping(self):
        for key,value in [('width_scale',1.2),('igb_sha256','b'*64),('car_id',2),('pack','../bad'),('body_id',4)]:
            old=self.r['entries'][0][key]; self.r['entries'][0][key]=value
            with self.assertRaises(ValueError): self.convert()
            self.r['entries'][0][key]=old
        self.e += b'x'
        with self.assertRaises(ValueError): self.convert()
    def test_matrix_duplicate(self):
        for v in (float('nan'),float('inf'),2):
            self.c['records'][0]['anchors']['TAIL_L1']['matrix'][3]=v
            with self.assertRaises(ValueError): self.convert()
        self.c['records'][0]['anchors']['TAIL_L1']['matrix'][3]=0
        self.c['records'].append(copy.deepcopy(self.c['records'][0])); self.r['entries'].append(copy.deepcopy(self.r['entries'][0]))
        with self.assertRaises(ValueError): self.convert()
    def test_invalid_elf(self):
        for e in (self.e[:60],b'not ELF',self.e[:0x200]):
            with self.assertRaises((ValueError,struct.error)): t.widths(e,{1})
    def test_paths(self):
        with self.assertRaises(ValueError): t.parse(b'{"x":1,"x":2}')
        with self.assertRaises(ValueError): t.parent('/tmp/../etc/passwd')
        with tempfile.TemporaryDirectory() as tmp:
            path=os.path.join(tmp,'f'); open(path,'wb').close()
            link=os.path.join(tmp,'link'); os.symlink(path,link)
            with self.assertRaises(OSError): t.read_file(link)
            os.symlink(tmp,os.path.join(tmp,'d'))
            with self.assertRaises(OSError): t.read_file(os.path.join(tmp,'d','f'))
if __name__=='__main__': unittest.main()
