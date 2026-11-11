"""Convert original Ghost entry art and the rival-only Le Mans wheel."""
import hashlib
import json
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory

from .archive import ArchiveSource
from .menu_components import decode_image
from .source import ConversionCancelled, FileTreeSource, MAIN_SHA256, ReviewedReadSet, check_cancel

PACK = 'ghost-match.bin'
WHEEL_PACK = 'ghost-wheel-lman.wpk'
WHEEL_NAME = 'gem_lman_wheel'
WHEEL_LIST = 'data/wheel_list.lua'
WHEEL_SOURCES = (
    (WHEEL_LIST, 80736, 'c6608087e03605b958853d4c4a2be0e954536c0cf0251ed5db24f53dc8180f2f'),
    ('data/changewheel/gem_lman/lman_mid.igb', 306825, '31df4c9e831196bc685cdd882053707a1f0e9c2f55c6f1426da6f92f134d1798'),
    ('data/changewheel/gem_lman/lman_mid_col1.tga', 786476, '780ed1904457a6fb483745736eb4a681671c1755373f92fc545174131e3b454f'),
)
SPRITE_BASE = 130000
SPRITES = (
    (1773, 'data/sprite/menu_p_crown_L_C1.png', 84861, '8fed58e3ce85a04803b751b24b860a693734b6cb6e369ed3db8253c6d3e2f58a'),
    (1775, 'data/sprite/menu_p_crown_L_fk.png', 60749, '2cbc6e70166c0180b647010e1e905f67b6a830b6c7e39eaf7d142b814ad4aaff'),
    (1776, 'data/sprite/menu_p_crown_L_hk.png', 85101, 'c3a033c86411449e3445fc3d51db6a91528e9fa1d2740695f7c4db1a3783156e'),
    (1777, 'data/sprite/menu_p_crown_L_ng.png', 88877, 'a4bcd3a1d6ebf8a7a70c5091d52c9745fa7c96d17bc890f24e632210dc6a06fd'),
    (1778, 'data/sprite/menu_p_crown_L_os.png', 81838, '7cb42837f25c049742f2d0d5ed77e1a8cfd9dbb0da1210d77167d0192c539ca2'),
    (1779, 'data/sprite/menu_p_crown_L_sk.png', 86648, '58946640f43626ac1684b8c786f75b7e58c92796e75cf830873867b04d40ad3c'),
    (1780, 'data/sprite/menu_p_crown_L_wg.png', 89671, '75b251fdf1c12d783dd1abe3b6661854113ff0995125bb51f2a0b1bf8a50f3fa'),
    (1781, 'data/sprite/menu_p_crown_L_yk.png', 88340, '1c4e8a8f887f7262173be7f80370eada9ec80a52c7def35ffb161e4e8f65c04b'),
    (3142, 'data/sprite/menu_p_car1_waku_w_2.png', 4043, 'ed42cf68ca42bf590cf2a7525a584ce807b8bc3159e800fea55928a77f2415c6'),
    (6601, 'data/sprite/menu_p_pre_tg_rival_great.png', 11811, '40fdd4ef933278508b4a3720e707983f01fae1e4e324c5e053beca7e5c7a4c39'),
)

def _readset(rows):
    rows = [*rows, ('main', 24855892, MAIN_SHA256)]
    data = json.dumps({'schema': 'wmmt-original-readset-v1', 'main_sha256': MAIN_SHA256,
                       'files': [{'path': path, 'bytes': size, 'sha256': digest}
                                 for path, size, digest in sorted(rows)]}).encode('utf-8')
    return ReviewedReadSet.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())


def _open_source(root, source_kind, readset, cancel):
    if source_kind == 'zip':
        return ArchiveSource(root / 'incoming.zip', readset, cancel=cancel)
    return FileTreeSource(root / 'incoming', readset)


def convert(root, source_kind, *, cancel=None, progress=None):
    """The core job already verifies main. Recheck the exact original PNGs here."""
    if progress:
        progress('pack-ghost-match', 0, len(SPRITES))
    try:
        readset = _readset((path, size, digest) for _, path, size, digest in SPRITES)
        source = _open_source(root, source_kind, readset, cancel)
        with source, TemporaryDirectory(prefix='ghost-match-', dir=root) as scratch:
            bank = Path(scratch) / PACK
            with bank.open('xb') as stream:
                stream.write(struct.pack('<4sIII', b'WCP1', 1, len(SPRITES), 0))
                for index, (sid, path, size, _) in enumerate(SPRITES, 1):
                    image = decode_image(source.read(path, max_bytes=size, cancel=cancel))
                    stream.write(struct.pack('<iHHI', SPRITE_BASE + sid, *image.size, 0))
                    stream.write(image.tobytes())
                    if progress:
                        progress('pack-ghost-match', index, len(SPRITES))
                stream.flush()
                os.fsync(stream.fileno())
            check_cancel(cancel)
            os.replace(bank, root / PACK)
        return True
    except ConversionCancelled:
        raise
    except (OSError, ValueError):
        return False


def convert_lemans_wheel(root, source_kind, *, cancel=None, progress=None):
    """Build the original model 98 with texture set 0, separate from the core profile."""
    if progress:
        progress('pack-ghost-wheel', 0, 1)
    try:
        import lualite
        import pack_cars

        readset = _readset(WHEEL_SOURCES)
        with _open_source(root, source_kind, readset, cancel) as source, \
                TemporaryDirectory(prefix='ghost-wheel-', dir=root) as scratch:
            scratch = Path(scratch)
            for path, size, _ in WHEEL_SOURCES:
                target = scratch / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(path, max_bytes=size, cancel=cancel))
            wheels = lualite.load(str(scratch / WHEEL_LIST), {'AbsPath': 'data/'})['WheelList']
            wheel = next(row for row in wheels if row.get('name') == WHEEL_NAME)
            target = scratch / WHEEL_PACK
            check_cancel(cancel)
            pack_cars.pack_wheel(str(scratch), wheel, 0, str(target))
            with target.open('rb+') as stream:
                os.fsync(stream.fileno())
            check_cancel(cancel)
            os.replace(target, root / WHEEL_PACK)
        if progress:
            progress('pack-ghost-wheel', 1, 1)
        return True
    except ConversionCancelled:
        raise
    except (OSError, ValueError):
        return False
