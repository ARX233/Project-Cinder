"""Check real private packs and synthetic barrier image validation failures."""
import hashlib, importlib.util, struct, sys, tempfile, zlib
from pathlib import Path
from PIL import Image

spec=importlib.util.spec_from_file_location('junction_pack',Path(__file__).resolve().parents[1]/'tools/junction_pack.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def parse(path):
    b=Path(path).read_bytes(); magic,ver,ns,na=struct.unpack_from('<4sIII',b)
    assert magic==b'WCP1' and ver==1
    pos=16; sprites={}
    for _ in range(ns):
        sid,w,h,n=struct.unpack_from('<iHHI',b,pos);pos+=12
        pixels=zlib.decompress(b[pos:pos+n]);pos+=n
        assert len(pixels)==w*h*4 and sid not in sprites
        sprites[sid]=(w,h,pixels)
    animations=b[pos:]
    for _ in range(na):
        name,nf,nr=struct.unpack_from('<48sII',b,pos); pos+=56+nf*8+nr*46
        assert pos<=len(b)
    assert pos==len(b)
    return b,sprites,animations

def main():
    new,old,root=map(Path,sys.argv[1:4]); b,sprites,anims=parse(new/'junction-pages.wcp'); _,prev,prev_anims=parse(old/'junction-pages.wcp')
    assert hashlib.sha256(b).hexdigest()=='79b1a23f907a3fe23878600591aa0f253c50e6c5ef3bf6c6dea67931831e1d62'
    assert anims==prev_anims and all(sprites[k]==v for k,v in prev.items())
    assert set(sprites)-set(prev)==set(m.BARRIER_SPRITES)
    for sid,(path,wh) in m.BARRIER_SPRITES.items():
        image=m.read_barrier_sprite(sid,path,root/path,wh)
        assert sprites[sid]==(*wh,image.tobytes())
    work=Path(tempfile.mkdtemp(prefix='junction-barrier-test-',dir='/Volumes/CodexWork'))
    path=work/'sample.tga'; png=work/'not-tga.tga'; small=work/'small.tga'
    Image.new('RGB',(256,256),(2,3,4)).save(path,format='TGA')
    Image.new('RGB',(256,256)).save(png,format='PNG')
    Image.new('RGB',(4,4)).save(small,format='TGA')
    sid=0x569; valid,wh=m.BARRIER_SPRITES[sid]
    assert m.read_barrier_sprite(sid,valid,path,wh).getpixel((0,0))==(2,3,4,255)
    for source,image,size in [('wrong/path.tga',path,wh),(valid,png,wh),(valid,small,wh),(valid,path,(2,2))]:
        try: m.read_barrier_sprite(sid,source,image,size)
        except ValueError: pass
        else: raise AssertionError('invalid barrier accepted')
    print('old bytes preserved; 3 original TGA pixels and validation failures verified:',work)
if __name__=='__main__': main()
