#!/usr/bin/env python3
"""Generate private junction resources; no writes to input files or the source tree.
Requires Pillow and Unicorn, and the existing tools/recomp/x86emu.py.
Output is a standalone WCP1; merging/loading it is a separate integration step.
"""
import argparse, hashlib, os, struct, sys, zlib
from pathlib import Path
from PIL import Image

SHA = "2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6"
ANIMS = ("cons_g_bunki_flash", "cons_g_bunki_mes_next", "cons_g_bunki_mes_select", "cons_g_bunki_select")
UV_BASE=102000
# Original ELF sprite-table paths and dimensions, verified against the TGA files.
BARRIER_SPRITES = {
    0x569: ('data/sprite/divergence_frame.tga', (256, 256)),
    0x7d5: ('data/sprite/divergence_arrow01.tga', (512, 512)),
    0x7d6: ('data/sprite/divergence_arrow02.tga', (512, 512)),
}

def read_barrier_sprite(sid, source_name, path, table_size):
    """Validate the exact ELF mapping and image format before decoding pixels."""
    expected_path, expected_size = BARRIER_SPRITES[sid]
    if source_name != expected_path:
        raise ValueError(f'barrier sprite path mismatch {sid:x}: {source_name}')
    if table_size != expected_size:
        raise ValueError(f'barrier ELF dimensions mismatch {sid:x}')
    with Image.open(path) as image:
        if image.format != 'TGA' or image.size != expected_size:
            raise ValueError(f'barrier sprite format or dimensions mismatch {sid:x}')
        return image.convert('RGBA')

def write_table_header(path, table):
    """Write a private byte-exact C initializer without overwriting any file."""
    if len(table) != 384:
        raise ValueError('table must contain exactly 384 bytes')
    path = Path(path)
    parent = path.parent.resolve(strict=True)
    allowed = Path('/Volumes/CodexWork').resolve(strict=True)
    if parent != allowed and allowed not in parent.parents:
        raise ValueError('header must be below /Volumes/CodexWork')
    if path.name in ('', '.', '..'):
        raise ValueError('invalid header filename')
    rows = [', '.join('0x%02x' % byte for byte in table[i:i+12]) for i in range(0, len(table), 12)]
    text = ('/* Private original-game data; do not commit. Generated from verified ELF. */\n'
            '#ifndef JUNCTION_TABLE_PRIVATE_H\n#define JUNCTION_TABLE_PRIVATE_H\n'
            'static const unsigned char junction_table_private[384] = {\n  ' +
            ',\n  '.join(rows) + '\n};\n#endif\n').encode('ascii')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(parent / path.name, flags, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(text)
    return hashlib.sha256(text).hexdigest()

def main():
    p=argparse.ArgumentParser(); p.add_argument("root",type=Path); p.add_argument("output",type=Path)
    p.add_argument('--table-header', type=Path, help='optional new private C header under /Volumes/CodexWork')
    a=p.parse_args(); root=a.root.resolve(strict=True); output=a.output.resolve()
    allowed=Path('/Volumes/CodexWork').resolve()
    if output==allowed or allowed not in output.parents or output.exists(): raise ValueError('output must be a fresh directory below /Volumes/CodexWork')
    exe=root/'main'; data=exe.read_bytes()
    if hashlib.sha256(data).hexdigest()!=SHA: raise ValueError('wrong ELF')
    po=struct.unpack_from('<I',data,28)[0]; size,num=struct.unpack_from('<HH',data,42)
    seg=[struct.unpack_from('<8I',data,po+i*size) for i in range(num)]
    def off(va, length=1):
        matches=[o+va-v for t,o,v,_,fs,*rest in seg if t==1 and v<=va and va+length<=v+fs]
        if len(matches)!=1: raise ValueError('unmapped or ambiguous ELF address')
        return matches[0]
    def u32(va): return struct.unpack_from('<I',data,off(va,4))[0]
    def name(sid):
        if sid<0 or sid>=0x1f9b: raise ValueError('invalid sprite id')
        o=off(u32(0x9551560+44*sid)); end=data.index(b'\0',o); n=data[o:end].decode('ascii')
        q=(root/n).resolve(strict=True)
        if root not in q.parents: raise ValueError('sprite escapes root')
        return q,n
    expected={0x144e:'menu_p_bunki_area_C1_in.png',0x179d:'menu_p_bunki_area_C1_out.png',0xdc4:'menu_p_bunki_L_waku_1.png',0xdc6:'menu_p_bunki_R_waku_1.png',0x1450:'menu_p_bunki_mes_select.png'}
    for sid,n in expected.items():
        if name(sid)[0].name!=n: raise ValueError(f'sprite name mismatch {sid:x}: {name(sid)[1]}')
    table=data[off(0x9332e20,384):off(0x9332e20,384)+384]
    rows=[struct.unpack_from('<6i',table,24*i) for i in range(16)]
    used={246,248,249,250,251,252} | {r[j] for r in rows for j in (2,5)}
    if any(n<0 or n>=276 for n in used): raise ValueError('bad UV index')
    # Run the original constructor through the existing emulator without importing uvtab.py,
    # whose module-level side effect writes a fixed repository path.
    os.environ['WMMT_MAIN']=str(exe)
    sys.path.insert(0,str(Path(__file__).resolve().parent/'recomp'))
    import x86emu
    emu=x86emu.Emu(trace_unknown=False); emu.call(0x8a10cc8)
    raw=bytes(emu.rd(0x9803c80,276*36))
    anims=[]; ids=set()
    for an in ANIMS:
        b=(root/'data/anime'/f'{an}.anm').read_bytes(); nf=struct.unpack_from('<I',b)[0]
        if not 0<nf<=10000: raise ValueError('invalid frames')
        frames=[struct.unpack_from('<II',b,8+8*i) for i in range(nf)]
        count=max(s+n for s,n in frames); base=8+8*nf
        if count>200000 or base+64*count>len(b): raise ValueError('invalid records')
        records=[struct.unpack_from('<i6f4i4ii',b,base+64*k) for k in range(count)]
        ids.update(r[0] for r in records); anims.append((an,frames,records))
    ids.update(BARRIER_SPRITES)
    sprites=[]
    for sid in sorted(ids):
        path,source_name=name(sid)
        wh=tuple(round(x) for x in struct.unpack_from('<2f',data,off(0x9551560+44*sid+16,8)))
        if min(wh)<=0 or max(wh)>2048: raise ValueError('invalid sprite size')
        if sid in BARRIER_SPRITES:
            im=read_barrier_sprite(sid,source_name,path,wh)
        else:
            with Image.open(path) as image: im=image.convert('RGBA')
        if im.size!=wh: im=im.resize(wh,Image.Resampling.LANCZOS)
        sprites.append((sid,im))
    for i in sorted(used):
        sid,u0,v0,u1,v1=struct.unpack_from('<I4f',raw,36*i); path,_=name(sid)
        with Image.open(path) as image: im=image.convert('RGBA')
        box=tuple(round(x*d) for x,d in zip((u0,v0,u1,v1),(im.width,im.height,im.width,im.height)))
        if not (0<=box[0]<box[2]<=im.width and 0<=box[1]<box[3]<=im.height): raise ValueError(f'invalid UV {i}')
        sprites.append((UV_BASE+i,im.crop(box)))
    out=bytearray(struct.pack('<4sIII',b'WCP1',1,len(sprites),len(anims)))
    for sid,im in sprites:
        rawpix=im.tobytes(); z=zlib.compress(rawpix,9)
        out+=struct.pack('<iHHI',sid,*im.size,len(z))+z
    for an,frames,records in anims:
        out+=struct.pack('<48sII',an.encode(),len(frames),len(records))
        for f in frames: out+=struct.pack('<II',*f)
        for r in records:
            out+=struct.pack('<iH6f4h4h',r[0],{8:1,9:2}.get(r[15],0),*r[1:7],*(max(-32768,min(32767,x)) for x in r[7:15]))
    output.mkdir(parents=True,exist_ok=False)
    for n,b in [('junction-table.bin',table),('junction-pages.wcp',out)]:
        with (output/n).open('xb') as f: f.write(b)
        print(n,len(b),hashlib.sha256(b).hexdigest())
    if a.table_header is not None:
        digest = write_table_header(a.table_header, table)
        print('private header', a.table_header, 'sha256', digest)
if __name__=='__main__': main()
