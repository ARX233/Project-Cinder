"""Convert the original final-distance HUD without requiring the legacy card bank."""
import hashlib
import json
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory

from PIL import Image

from .archive import ArchiveSource
from .menu_components import SpriteRenderer, crop, load_anm
from .menu_support import OriginalSupport
from .source import ConversionCancelled, FileTreeSource, MAIN_SHA256, ReviewedReadSet, check_cancel

FINISH_PACK = 'finish-menu.bin'
ANIMS = ('cons_g_last_000m', 'cons_g_last_saigo', 'cons_g_last_tonikaku')
DIGIT_FIRST = 0x268
METRE = 0x272
SOURCE_PINS = (
    ('data/anime/cons_g_last_000m.anm', 37032, 'd4c4dd94aae0c965c3d98e3d06dd8c6543aadced1a71706cdf322024299d3937'),
    ('data/anime/cons_g_last_saigo.anm', 8232, '10bf2126e10a037068d4650831e1a02c23da9c62e7204aaa72f0393cff93ebb3'),
    ('data/anime/cons_g_last_tonikaku.anm', 12072, '032ce768c040d09fc7e00922dc8758e98e9f5887cc313af07d63dc59cbb30e8d'),
    ('data/sprite/cons_p_01.png', 434263, '23e530d8b6306c6135dc1c91c1d6134f5c91a7f12b54f96603eca1bec2a3f00d'),
    ('data/sprite/cons_p_finish_made.png', 3607, '22b42f64d6ca3b209ab485def94867ca18c87195f09095d12ae9e79baa21c34e'),
    ('data/sprite/cons_p_finish_rival.png', 2761, '8ac9082082c54d6d74dc213f8d17f7a525a6fe35d9315590245c3d5edaed7d00'),
    ('data/sprite/cons_p_finish_saigo.png', 7533, '10d4b7d5e9ccf77ae2422cf6bb2dbc6f3c9ba59ab98205116bf006683e827af3'),
    ('data/sprite/cons_p_finish_tonikaku.png', 6525, '0b05141db5187ecc93ad71df2ca072583f976d6b0087ad576ff86113b4012b63'),
    ('data/sprite/cons_p_last_0_template.png', 2872, '27fd4a5d79a83b708584503978d15d52ab753e3c15b17676972d16128e52ca6c'),
    ('data/sprite/cons_p_last_1_template.png', 2872, '27fd4a5d79a83b708584503978d15d52ab753e3c15b17676972d16128e52ca6c'),
    ('data/sprite/cons_p_last_2_template.png', 2872, '27fd4a5d79a83b708584503978d15d52ab753e3c15b17676972d16128e52ca6c'),
    ('data/sprite/cons_p_last_m.png', 3613, 'c2193f52f59a5a473f80216b14825f9d60ca57b1ad2147f4dbc5408a34d4274c'),
    ('data/sprite/cons_p_last_m_template.png', 242, 'b9d795a35e3971223a7315b664c3bb9887b3c945da9eb446e48bf4c5b9ac7483'),
)

def _readset():
    rows = [*SOURCE_PINS, ('main', 24855892, MAIN_SHA256)]
    data = json.dumps({'schema': 'wmmt-original-readset-v1', 'main_sha256': MAIN_SHA256,
                       'files': [{'path': path, 'bytes': size, 'sha256': digest}
                                 for path, size, digest in rows]}).encode('utf-8')
    return ReviewedReadSet.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())


def _pack(source, bank, cancel):
    support = OriginalSupport(source.read('main', max_bytes=24855892, cancel=cancel), cancel=cancel)
    renderer = SpriteRenderer(support, source.read, cancel=cancel)
    animations = {}
    art = {METRE}
    for name in ANIMS:
        frames, records = load_anm(source.read(f'data/anime/{name}.anm', max_bytes=65536, cancel=cancel),
                                   cancel=cancel)
        art.update(row[0] for row in records)
        animations[name] = frames, records
    sprites = {sid: renderer.sprite(sid, table_size=True) for sid in art}
    metre = sprites[METRE]
    for y in range(metre.height):
        for x in range(metre.width):
            if x not in (0, metre.width - 1) and y not in (0, metre.height - 1):
                continue
            red, green, blue, alpha = metre.getpixel((x, y))
            if red > 180 and green == blue == 0 and alpha == 255:
                metre.putpixel((x, y), (0, 0, 0, 0))

    # The supplied original has ten identical placeholder PNGs for these IDs.
    # Use the same original console atlas digits as the verified prepared pack.
    cells = support.uv_cells()
    for digit in range(10):
        sid, x0, y0, x1, y1 = cells[153 + digit]
        sheet = renderer.sprite(sid)
        x, right = (round(v * sheet.width / 1024) for v in (x0, x1))
        y, bottom = (round(v * sheet.height / 1024) for v in (y0, y1))
        image = crop(sheet, (x, y, right - x, bottom - y))
        sprites[DIGIT_FIRST + digit] = image.resize(sprites[METRE].size, Image.Resampling.LANCZOS)

    with bank.open('xb') as stream:
        stream.write(struct.pack('<4sIII', b'WCP1', 1, len(sprites), len(animations)))
        for sid, image in sorted(sprites.items()):
            stream.write(struct.pack('<iHHI', sid, image.width, image.height, 0))
            stream.write(image.tobytes())
        for name, (frames, records) in animations.items():
            stream.write(struct.pack('<48sII', name.encode('ascii'), len(frames), len(records)))
            for frame in frames:
                stream.write(struct.pack('<II', *frame))
            for row in records:
                blend = {8: 1, 9: 2}.get(row[15], 0)
                stream.write(struct.pack('<iH6f8h', row[0], blend, *row[1:7],
                                         *(max(-32768, min(32767, v)) for v in row[7:15])))
        stream.flush()
        os.fsync(stream.fileno())


def convert(root, source_kind, *, cancel=None, progress=None):
    if progress:
        progress('pack-finish-menu', 0, 1)
    try:
        readset = _readset()
        source = (ArchiveSource(root / 'incoming.zip', readset, cancel=cancel)
                  if source_kind == 'zip' else FileTreeSource(root / 'incoming', readset))
        with source, TemporaryDirectory(prefix='finish-menu-', dir=root) as scratch:
            bank = Path(scratch) / FINISH_PACK
            _pack(source, bank, cancel)
            check_cancel(cancel)
            os.replace(bank, root / FINISH_PACK)
        if progress:
            progress('pack-finish-menu', 1, 1)
        return True
    except ConversionCancelled:
        raise
    except (OSError, ValueError):
        return False
