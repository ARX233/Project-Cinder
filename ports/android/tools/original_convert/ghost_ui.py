"""Original 3DX+ Ghost UI family, separate opt-in WCP1 v1 component.

No asset payload or imported game code is embedded here. The caller supplies
SHA-pinned OriginalSupport, a bounded original-resource reader and the reviewed
base sprite/animation identities. Returned digests are observations, not trust.
The legacy complete WMN3 recipe and its 308-animation identity are unchanged.
"""
import hashlib
import struct
import zlib
from .menu_support import OriginalSupport,need
from .menu_components import SpriteRenderer,load_anm,_Output

GHOST_UI_ANIMS = (
    'menu_layout_tg_search_grayout', 'menu_layout_tg_search_grayout_arrow',
    'menu_layout_tg_seach_ring',
    'menu_layout_tg_search_2', 'menu_layout_tg_seach_ring_2',
    'menu_layout_tg_search_3', 'menu_layout_tg_seach_ring_3',
    'menu_layout_tg_lv', 'menu_layout_tg_lv_arrow', 'menu_layout_tg_lv_yourlv',
    'menu_layout_tg_vs_course',  # ANM 0x2b0: actual eight-card strip, not the NEW marker
    'menu_layout_tg_vs_course_new', 'menu_layout_tg_vs_course2',
    'menu_g_name_number',  # original numeric search page; garage name pages stay unchanged
    'menu_layout_tg_vs_sel', 'menu_layout_tg_rival', 'menu_layout_tg_vs',
)
# Constructor/setImageReplace and original 0x9408340 prompt table. Not invented art.
GHOST_UI_EXTRA = (0x1ab7,0x1beb,6357,6358,6370,6359,0x767,0x136b,0x136c,
    5893,6640,6839,6352,7146,7373)
# clSpinBox level ctor 0x88503c8 table 0x9408520, ten rows / three sprite IDs.
# Column0 replaces template4172, columns1/2 template6635 (ordinary/R35). 1 = none.
GHOST_UI_LEVEL_IMAGES = ((915,3374,6326),(916,3375,6327),(917,3377,6328),
    (918,3378,6329),(919,3380,6331),(920,3382,6334),(921,3384,6336),
    (922,3386,6338),(923,2951,2951),(2513,1,1))


def pack_ghost_ui(read, support, base_sprite_ids, base_animation_names, output_path, *, cancel=None):
    need(isinstance(support,OriginalSupport),'Pinned OriginalSupport required')
    base=set(base_sprite_ids);base_anims=set(base_animation_names)
    need(all(type(s) is int and s>=0 for s in base),'Invalid base sprite identities')
    renderer=SpriteRenderer(support,read,cancel=cancel)
    # Verify the constructor table against the caller's pinned source. Never
    # substitute port labels, infer level from class, or alter the legacy recipe.
    native_levels=tuple(tuple(support.ints(0x9408520+12*i,3)) for i in range(10))
    need(native_levels==GHOST_UI_LEVEL_IMAGES,'Original Ghost level-image table mismatch')
    anims=[];used=set(GHOST_UI_EXTRA);sources=[]
    used.update(s for row in native_levels for s in row if s>3)
    for name in GHOST_UI_ANIMS:
        path='data/anime/'+name+'.anm';data=read(path,max_bytes=16*1024*1024,cancel=cancel)
        frames,records=load_anm(data,cancel=cancel)
        used.update(r[0] for r in records if r[0]>3)
        sources.append(dict(path=path,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        if name not in base_anims:anims.append((name,frames,records))
    need(anims,'No missing Ghost animations; do not replace an existing namespace')
    additions=sorted(used-base);need(len(additions)+len(base)<65536,'Sprite namespace budget')
    with _Output(output_path,cancel=cancel,max_bytes=256*1024*1024) as output:
        output.write(struct.pack('<4sIII',b'WCP1',1,len(additions),len(anims)))
        for sid in additions:
            image=renderer.sprite(sid,table_size=True);w,h=image.size
            need(w<=2048 and h<=2048,'Ghost sprite size unsupported')
            raw=image.tobytes();pixels=zlib.compress(raw,6)
            output.write(struct.pack('<iHHI',sid,w,h,len(pixels))+pixels)
        for name,frames,records in anims:
            output.write(struct.pack('<48sII',name.encode('ascii'),len(frames),len(records)))
            for frame in frames:output.write(struct.pack('<II',*frame))
            for r in records:
                sid=r[0] if r[0]>3 else -1
                output.write(struct.pack('<iH6f4h4h',sid,{8:1,9:2}.get(r[15],0),*r[1:7],
                                         *(max(-32768,min(32767,v)) for v in r[7:15])))
    receipt=output.receipt(format='WCP1',version=1,coverage='original-Ghost-UI-family',
        animations=[dict(name=n,frames=len(f),records=len(r)) for n,f,r in anims],
        sprite_ids=additions,referenced_base_sprite_ids=sorted(used&base),sources=sources,
        source_main_sha256='2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6',
        authority='static-original-resource conversion, not catalog approval or runtime equivalence')
    return receipt
