"""Verified original mileage results screen assets for the optional WCP1 bank."""
import hashlib
import json
import os
from pathlib import Path
import struct
from tempfile import TemporaryDirectory

from .archive import ArchiveSource
from .menu_components import SpriteRenderer, load_anm
from .menu_support import OriginalSupport
from .source import ConversionCancelled, FileTreeSource, MAIN_SHA256, ReviewedReadSet, check_cancel

MILEAGE_PACK = 'mileage-menu.bin'
SOURCE_ANIMATION = 'data/anime/menu_layout_milage.anm'
SPRITE_BASE = 120000
SPRITES = (1557, 5584, 1558, 2823, *range(1224, 1235))
CAPTIONS = ((1439, '今回の走行距離'), (1440, '総走行距離'))
MILEAGE_SOURCE_PINS = (
    ('data/anime/menu_layout_milage.anm', 100392, '98f38619f40def58335c863e78be0c33e80144f21df982d61d049293d7f2ce77'),
    ('data/sprite/font_28.png', 472371, 'f19ea06e8adca5b2c1ebe7b33c54b50fa5a9a0ba9e646c70298f58ba77c13f48'),
    ('data/sprite/font_28_2.png', 615323, 'b3b695360dc5ea03d85450fa8dc209a6b5ad4c95819b69839c9941b4d325c178'),
    ('data/sprite/font_28_3.png', 294515, 'fe218e33c356f2c79cb10ec6a2b62b49d6fa7ec73efff9f2395c52b5fd6f428b'),
    ('data/sprite/menu_p_milage_0.png', 4149, '6733e3a9b37904ba04c6573fbb460af0a1d68f9143aa4b31d9dfe4ba1b37a5b9'),
    ('data/sprite/menu_p_milage_1.png', 3705, 'b2803157ac3847ec36919d6c6fac6396b3c4708015a8267e1f681f4acfa431ed'),
    ('data/sprite/menu_p_milage_2.png', 4138, '0940fb1f57dbe962b16833234dec93fd08c40b8d780c5530879d4f7e3be9ef99'),
    ('data/sprite/menu_p_milage_3.png', 4177, 'cf6f92bbca4b24a0ef1b5975797c2a2083ffebf6261de758d208f91fac4c7717'),
    ('data/sprite/menu_p_milage_4.png', 4046, '80469e1ea598db093d3d68b94afde68371a36770cce3d2cbffae02c42b4eb77c'),
    ('data/sprite/menu_p_milage_5.png', 4033, 'ce36fbf11d99622a65ae4782a5455a99f875f582eaa0efd183471728009e3477'),
    ('data/sprite/menu_p_milage_6.png', 4110, '1fff1f03f996dbb62dfc8bceae98fa63a6a6f075019259848a8581d92be9e091'),
    ('data/sprite/menu_p_milage_7.png', 3836, '68b1abe5a87a31db2a481ae75316de59e40a286b13c6aaeca99f5c4182c8ae4f'),
    ('data/sprite/menu_p_milage_8.png', 4116, '287ab45cc0b3ca24c581c5187a87662918d05948dc239b14c33b5845d2b4b917'),
    ('data/sprite/menu_p_milage_9.png', 4094, 'e8d64ea7a02ed2bccdaa2adb011a24ee61767134cc35edbfb14a3641a9c4dacd'),
    ('data/sprite/menu_p_milage_a.png', 4336, '6deeb84dd727a0816fefd40ed05e538e7ac4c2e63cd53032f1ed4b8994c120fc'),
    ('data/sprite/menu_p_milage_bg.png', 59459, 'd9cda4719d3442c7c09358d7559cb7c4f113035e9bd577402a5c1f433bfdb763'),
    ('data/sprite/menu_p_milage_comma.png', 3444, 'cbbd3dd56caabb3039aeb5427030c42715c4466e05524a6b07aa50a49ec86c3e'),
    ('data/sprite/menu_p_milage_km.png', 4566, '204ced5c1b974c26268cfb0f794a9199223b9525bacfed16a4c6a199715c9685'),
    ('data/sprite/menu_p_milage_title_bar.png', 3192, '58e1d046877585e673e68f15a023e36dc511507df2bba785942c0a720aa26760'),
)

def _readset():
    rows = [*MILEAGE_SOURCE_PINS, ('main', 24855892, MAIN_SHA256)]
    data = json.dumps({'schema': 'wmmt-original-readset-v1', 'main_sha256': MAIN_SHA256,
                       'files': [{'path': name, 'bytes': size, 'sha256': digest}
                                 for name, size, digest in rows]}).encode('utf-8')
    return ReviewedReadSet.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())


def _pack(source, output, *, cancel=None):
    support = OriginalSupport(source.read('main', max_bytes=24855892, cancel=cancel))
    renderer = SpriteRenderer(support, source.read, cancel=cancel)
    sprites = {sid: renderer.sprite(sid, table_size=True) for sid in SPRITES}
    for sid, text in CAPTIONS:
        sprites[sid] = renderer.text(4, text)
    frames, records = load_anm(source.read(SOURCE_ANIMATION, max_bytes=100392, cancel=cancel),
                               cancel=cancel)
    # The port draws the real player model; cabinet password and hardware
    # placeholders never reach the client. Keep all original animation poses.
    poses = []
    for start, count in frames:
        check_cancel(cancel)
        poses.append([row for row in records[start:start + count] if row[0] in sprites])
    with output.open('xb') as stream:
        stream.write(struct.pack('<4sIII', b'WCP1', 1, len(sprites), 1))
        for sid, image in sorted(sprites.items()):
            stream.write(struct.pack('<iHHI', SPRITE_BASE + sid, image.width, image.height, 0))
            stream.write(image.tobytes())
        stream.write(struct.pack('<48sII', b'menu_layout_milage', len(poses), sum(map(len, poses))))
        start = 0
        for pose in poses:
            stream.write(struct.pack('<II', start, len(pose)))
            start += len(pose)
        for pose in poses:
            for row in pose:
                blend = {8: 1, 9: 2}.get(row[15], 0)
                stream.write(struct.pack('<iH6f8h', SPRITE_BASE + row[0], blend, *row[1:7],
                                         *(max(-32768, min(32767, v)) for v in row[7:15])))
        stream.flush()
        os.fsync(stream.fileno())


def convert(root, source_kind, *, cancel=None, progress=None):
    """Publish a verified supplemental bank without changing the base profile."""
    if progress:
        progress('pack-mileage-menu', 0, 1)
    try:
        readset = _readset()
        if source_kind == 'zip':
            source = ArchiveSource(root / 'incoming.zip', readset, cancel=cancel)
        else:
            source = FileTreeSource(root / 'incoming', readset)
        with source, TemporaryDirectory(prefix='mileage-menu-', dir=root) as scratch:
            bank = Path(scratch) / MILEAGE_PACK
            _pack(source, bank, cancel=cancel)
            check_cancel(cancel)
            os.replace(bank, root / MILEAGE_PACK)
        if progress:
            progress('pack-mileage-menu', 1, 1)
        return True
    except ConversionCancelled:
        raise
    except (OSError, ValueError):
        return False
