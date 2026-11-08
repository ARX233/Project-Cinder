#!/usr/bin/env python3
"""Pack original cardcheck animations, preserving source sprite IDs."""
import argparse, math, struct, zlib, hashlib, zipfile, io
from pathlib import Path
from PIL import Image
import menupack as m

def card_page_replacements(names):
    """Original runtime replacements referenced by CardDisp2/3/4."""
    paths = ('menu_p_card_2_st', 'menu_p_card_2_chara_ramp_')
    ids = {sid for sid, name in names.items()
           if Path(name).name.startswith(paths)}
    ids.update((0x1800, 0x1a51))  # current streak label and hidden portrait
    ids.update(range(0x492, 0x49d))  # coin suffix and defense counters
    ids.update(range(0x11fc, 0x120e))  # earned crown icons and chapter numbers
    return ids

def inventory(path):
    ids, names = set(), set()
    with path.open('rb') as f:
        def read(n):
            b = f.read(n)
            if len(b) != n: raise ValueError(f'truncated {path}')
            return b
        if read(4) != b'WMN3': raise ValueError(f'bad magic {path}')
        n, = struct.unpack('<I', read(4))
        if n > 65535: raise ValueError('too many sprites')
        for _ in range(n):
            sid,w,h,z=struct.unpack('<iHHI',read(12)); ids.add(sid); read(z or w*h*4)
        na,=struct.unpack('<I',read(4))
        if na > 4096: raise ValueError('too many animations')
        for _ in range(na):
            name,nf,nr=struct.unpack('<48sII',read(56)); names.add(name.split(bytes(1))[0].decode('ascii')); read(nf*8+nr*44)
        if f.read(1): raise ValueError('trailing bytes')
    return ids,names

def existing_bank(menu, story_path, original):
    base, base_anims = inventory(menu)
    story, story_anims = inventory(story_path)
    if story_anims or base & story:
        raise ValueError('story conflicts with base')
    data = original.read_bytes()
    if len(data) < 16: raise ValueError('truncated WCP')
    magic, version, count, na = struct.unpack_from('<4sIII', data)
    if magic != b'WCP1' or version != 1: raise ValueError('bad WCP header')
    off = 16; existing = set()
    for _ in range(count):
        if off + 12 > len(data): raise ValueError('truncated WCP sprite')
        sid, w, h, n = struct.unpack_from('<iHHI', data, off); off += 12
        if sid in existing or not w or not h or not n or off + n > len(data): raise ValueError('invalid WCP sprite')
        if len(zlib.decompress(data[off:off+n])) != w*h*4: raise ValueError('bad WCP pixels')
        existing.add(sid); off += n
    anim_offset = off
    animation_names = set()
    for _ in range(na):
        if off+56 > len(data): raise ValueError('truncated WCP animation')
        name, nf, nr = struct.unpack_from('<48sII', data, off); off += 56
        name = name.split(b'\0')[0].decode('ascii')
        if name in animation_names or name in base_anims: raise ValueError('animation collision')
        animation_names.add(name)
        off += nf*8 + nr*struct.calcsize('<iH6f4h4h')
        if off > len(data): raise ValueError('truncated WCP records')
    if off != len(data) or existing & (base | story): raise ValueError('WCP collision or trailing data')
    return base, story, existing, data, count, na, anim_offset

def append_sprites(data, count, na, anim_offset, additions, output):
    if len({sid for sid, _ in additions}) != len(additions): raise ValueError('duplicate addition')
    packed = bytearray()
    for sid, im in sorted(additions):
        raw = im.tobytes(); z = zlib.compress(raw, 9)
        packed += struct.pack('<iHHI', sid, *im.size, len(z)) + z
    out = struct.pack('<4sIII', b'WCP1', 1, count+len(additions), na) + data[16:anim_offset] + packed + data[anim_offset:]
    if len(out)>256*1024*1024: raise ValueError('too big')
    with output.open('xb') as f: f.write(out)
    print(f'added={len(additions)} sprites={count+len(additions)} animations={na} sha256={hashlib.sha256(out).hexdigest()}')

def augment_cardcheck(root, menu, story_path, original, output):
    """Keep a reviewed bank (including its BGM additions) and restore runtime card sprites."""
    base, story, existing, data, count, na, anim_offset = existing_bank(menu, story_path, original)
    elf = m.Elf(str(root/'main')); names = m.sprite_names(elf)
    additions = []
    for sid in sorted(card_page_replacements(names) - base - story - existing):
        with Image.open(root/names[sid]) as src: im = src.convert('RGBA')
        size = tuple(round(v) for v in struct.unpack_from('<2f', elf.d, elf.off(m.TABLE_VA+44*sid+16)))
        if min(size)<=0 or max(size)>2048: raise ValueError(f'invalid card sprite dimensions: {sid}')
        if size != im.size: im = im.resize(size, Image.Resampling.LANCZOS)
        additions.append((sid, im))
    append_sprites(data, count, na, anim_offset, additions, output)

def augment_bgm(root, menu, story_path, original, sidecar, output):
    """Append only missing original BGM sprites; retain all existing WCP records verbatim."""
    base, story, existing, data, count, na, anim_offset = existing_bank(menu, story_path, original)
    elf = m.Elf(str(root/'main')); names = m.sprite_names(elf)
    with zipfile.ZipFile(sidecar) as z:
        entries = [i.filename for i in z.infolist() if i.filename.startswith('bgm-extra/') and not i.is_dir()]
        if len(entries) != len(set(entries)): raise ValueError('duplicate sidecar entry')
        expected = {f'bgm-extra/{prefix}_{i:02}.m4a' for prefix, n in (('wm2',23),('wmr',12)) for i in range(1,n+1)}
        if set(entries) != expected: raise ValueError('sidecar track inventory mismatch')
    additions = []
    for s, prefix, count_expected in ((1, 'wm2', 25), (2, 'wmr', 14)):
        n = elf.u32(m.BGM_COUNTS + 4*s)
        if n != count_expected: raise ValueError('unexpected ELF BGM count')
        for k in range(n):
            song = struct.unpack_from('<i', elf.d, elf.off(m.BGM_SET + 4*(25*s+k)))[0]
            if k == 0:
                if song != 0x6e: raise ValueError('missing RANDOM')
                title = 'RANDOM'
            elif k == n-1:
                if song != -1: raise ValueError('missing NO BGM')
                title = 'NO BGM'
            else:
                if song < 0 or song == 0x6e: raise ValueError('invalid song')
                source = elf.cstr(elf.u32(m.BGM_MUSIC+12*song))
                if Path(source).name != f'{prefix}_{k:02}.wav': raise ValueError(f'source mapping mismatch {source}')
                title = elf.wstr(elf.u32(m.BGM_MUSIC+12*song+8))
                if not title: raise ValueError('empty title')
            sid = m.BGM_TEXT_BASE + 30*s + k
            if sid in base or sid in story or sid in existing: raise ValueError(f'title ID collision {sid}')
            im = m.render_text(elf, names, str(root), 0, title)
            additions.append((sid, im))
    for sid in (0x1641, 0x19ce):
        if sid in story or sid in existing: raise ValueError(f'logo ID collision {sid}')
        if sid in base: continue
        with Image.open(root/names[sid]) as src: im = src.convert('RGBA')
        size = tuple(round(v) for v in struct.unpack_from('<2f', elf.d, elf.off(m.TABLE_VA+44*sid+16)))
        if min(size)<=0 or max(size)>2048: raise ValueError('invalid logo dimensions')
        if size != im.size: im = im.resize(size, Image.Resampling.LANCZOS)
        additions.append((sid, im))
    append_sprites(data, count, na, anim_offset, additions, output)

def main():
    if len(__import__('sys').argv) > 1 and __import__('sys').argv[1] == '--augment-cardcheck':
        p = argparse.ArgumentParser(); p.add_argument('--augment-cardcheck', action='store_true')
        for arg in ('root','menu','story','original','output'): p.add_argument(arg, type=Path)
        a = p.parse_args(); augment_cardcheck(a.root,a.menu,a.story,a.original,a.output); return
    if len(__import__('sys').argv) > 1 and __import__('sys').argv[1] == '--augment-bgm':
        p = argparse.ArgumentParser(); p.add_argument('--augment-bgm', action='store_true')
        for arg in ('root','menu','story','original','sidecar','output'): p.add_argument(arg, type=Path)
        a = p.parse_args(); augment_bgm(a.root,a.menu,a.story,a.original,a.sidecar,a.output); return
    p=argparse.ArgumentParser(); p.add_argument('root',type=Path); p.add_argument('menu',type=Path); p.add_argument('story',type=Path); p.add_argument('output',type=Path); a=p.parse_args()
    base,existing=inventory(a.menu); story,story_anims=inventory(a.story)
    if story_anims or base & story: raise ValueError('story conflicts with base')
    elf=m.Elf(str(a.root/'main')); names=m.sprite_names(elf)
    files=sorted((a.root/'data/anime').glob('*cardcheck*.anm'))
    if len(files)!=44: raise ValueError(f'expected 44 animations; got {len(files)}')
    anims=[]; ids=set()
    for path in files:
        frames,records=m.load_anm(str(path),None)
        if not frames or len(records)>200000 or len(frames)>10000 or any(s+n>len(records) for s,n in frames): raise ValueError(f'invalid animation {path}')
        for r in records:
            if r[0]<0 or r[0]>=m.TABLE_N or r[0] not in names or not all(math.isfinite(v) for v in r[1:7]): raise ValueError(f'invalid record in {path}: {r[0]}')
            ids.add(r[0])
        if path.stem not in existing: anims.append((path.stem,frames,records))
    ids.update(range(0x1db2,0x1dbb))  # page title replacements, original table
    ids.update(card_page_replacements(names))
    sprites=[]; rawbytes=0
    for sid in sorted(ids-base-story):
        with Image.open(a.root/names[sid]) as img: im=img.convert('RGBA')
        size=tuple(round(v) for v in struct.unpack_from('<2f',elf.d,elf.off(m.TABLE_VA+44*sid+16)))
        if min(size)<=0 or max(size)>2048: raise ValueError(f'bad dimensions {sid}: {size}')
        if size!=im.size: im=im.resize(size,Image.Resampling.LANCZOS)
        raw=im.tobytes(); rawbytes+=len(raw); z=zlib.compress(raw,9)
        if zlib.decompress(z)!=raw: raise ValueError('compression failure')
        sprites.append(struct.pack('<iHHI',sid,*size,len(z))+z)
    out=bytearray(struct.pack('<4sIII',b'WCP1',1,len(sprites),len(anims)))
    for sprite in sprites: out+=sprite
    for name,frames,records in anims:
        b=name.encode('ascii')
        if len(b)>=48: raise ValueError('name too long')
        out+=struct.pack('<48sII',b,len(frames),len(records))
        for frame in frames: out+=struct.pack('<II',*frame)
        for r in records: out+=struct.pack('<iH6f4h4h',r[0],m.BLEND.get(r[15],0),*r[1:7],*(max(-32768,min(32767,v)) for v in r[7:15]))
    if len(out)>256*1024*1024: raise ValueError('too big')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('xb') as f: f.write(out)
    print(f'animations={len(files)} base_anims={len(files)-len(anims)} added_anims={len(anims)} referenced_ids={len(ids)} added_sprites={len(sprites)} raw_bytes={rawbytes} bundle_bytes={len(out)}')
if __name__=='__main__': main()
