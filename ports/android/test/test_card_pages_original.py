#!/usr/bin/env python3
"""Verify packaged originals against local source, base and story packs."""
import struct, sys, zlib
from pathlib import Path
from PIL import Image
P=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(P/'tools'))
import menupack as m
import card_pages_pack as pack
if len(sys.argv) != 5:
    sys.exit('Usage: test_card_pages_original.py ORIGINAL_ROOT BASE_MENU_BIN STORY_CUTIN_BIN CARD_PAGES_BIN')
root, base, story, card_pages = map(Path, sys.argv[1:])
data=card_pages.read_bytes()
baseids,baseanims=pack.inventory(base); storyids,_=pack.inventory(story)
pos=0
def take(n):
    global pos
    x=data[pos:pos+n]; assert len(x)==n; pos+=n; return x
magic,ver,ns,na=struct.unpack('<4sIII',take(16)); assert (magic,ver)==(b'WCP1',1)
elf=m.Elf(str(root/'main')); names=m.sprite_names(elf); added={}; checked=0
replacements=pack.card_page_replacements(names); replacement_checks=0
for _ in range(ns):
    sid,w,h,z=struct.unpack('<iHHI',take(12)); assert sid not in added and sid not in baseids and sid not in storyids
    raw=zlib.decompress(take(z)); assert len(raw)==w*h*4
    if checked<8 or sid in replacements:
        with Image.open(root/names[sid]) as image: image=image.convert('RGBA')
        if image.size!=(w,h): image=image.resize((w,h),Image.Resampling.LANCZOS)
        assert image.tobytes()==raw
        checked+=checked<8
        replacement_checks+=sid in replacements
    added[sid]=raw
anims={}
for _ in range(na):
    name,nf,nr=struct.unpack('<48sII',take(56)); name=name.split(bytes(1))[0].decode(); frames=[struct.unpack('<II',take(8)) for j in range(nf)]
    records=[struct.unpack('<iH6f4h4h',take(46)) for j in range(nr)]
    assert name not in anims; anims[name]=(frames,records)
assert pos==len(data) and checked==8
for file in sorted((root/'data/anime').glob('*cardcheck*.anm')):
    if file.stem in baseanims: continue
    frames,records=m.load_anm(str(file),None); gotframes,got=anims[file.stem]; assert gotframes==frames and len(got)==len(records)
    for old,new in zip(records,got):
        assert new[0]==old[0] and new[1]==m.BLEND.get(old[15],0) and new[2:8]==old[1:7]
        assert new[0] in baseids or new[0] in storyids or new[0] in added
assert all(i in baseids or i in storyids or i in added for i in range(0x1db2,0x1dbb))
assert replacements <= baseids | storyids | added.keys()
for page in [1,2,3,14,4,5,6,7,8]: assert any(f'cardcheck_{page}_' in n or n.endswith(f'cardcheck_{page}') for n in baseanims|set(anims))
print(f'Original animations and nine page titles resolved; 8 RGBA samples and {replacement_checks} runtime replacements matched')
