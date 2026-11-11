"""Pinned artwork for the original crown result, crown attract and driving-style card."""
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

PACK = 'crown-scenes.bin'
SPRITE_BASE = 140000
ANIMATIONS = (
    'menu_g_crown_bg',
    'menu_g_crown_get_title',
    'menu_g_crown_waku',
    'menu_layout_crown_get_a',
    'menu_layout_crown_get_b',
    'menu_layout_crown_saikyo',
    'menu_layout_crown_saikyo_all',
    'menu_g_crown_atract',
    'menu_g_crown_atract_title',
    'menu_g_cardcheck_5_waku',
    'menu_layout_cardcheck_5',
    'menu_g_cardcheck_5_point',
)
# The original replaces these text placeholders at runtime.
STYLE_PLACEHOLDERS = {1448, 1716, 1717, 1718, 1719, 1720, 2037, 2038}
EXTRA_SPRITES = (0x1db7, 0x196f, *range(0x6ef, 0x6f6), *range(0xadb, 0xae3))
SOURCE_PINS = (
    ('data/anime/menu_g_cardcheck_5_point.anm', 12072, '834ecd8402ace85984bf3e13af13108d8c46f6552193c436f60d0a65ba5cadce'),
    ('data/anime/menu_g_cardcheck_5_waku.anm', 208, '25bc0ebc367800e1ace9b37bb64f697eff33135fd75cfa6247439eb2a2e49d85'),
    ('data/anime/menu_g_crown_atract.anm', 64872, 'eea2cad0206610a3dc6ac83a220919707a311041914ba8db000111b5390da75d'),
    ('data/anime/menu_g_crown_atract_title.anm', 13672, 'c275b90c0e4c62f381248371630402b9543a00c5b4e5158ea1c610bc14bcbfa6'),
    ('data/anime/menu_g_crown_bg.anm', 144, 'a90f42e5383860c868d69fa84dfd8354eb04a2a99dbccd02fc045c7884b09dc9'),
    ('data/anime/menu_g_crown_get_title.anm', 8136, 'bc7af4c6c615ca98dd9366984314782c39e99b6d00fa09949d39eb0ecee29b27'),
    ('data/anime/menu_g_crown_waku.anm', 592, '4311c7d6c0469d58a0714839d049085ae1b91f9a7b0bb051522671dee5951053'),
    ('data/anime/menu_layout_cardcheck_5.anm', 720, 'a81fc10b4490c8ed49d9b27cc240a2a7b06e893d52b5ae49acd8a0e8ea62d3f2'),
    ('data/anime/menu_layout_crown_get_a.anm', 12616, '2995f2ed2eb9ee93a5a168b62f9a0e4644bf6b241d9bf376264d69b6cbcd1b5d'),
    ('data/anime/menu_layout_crown_get_b.anm', 45384, '440b607051210415b095ee7ff0be3265efff020db3ab406016cd156d475b1eaf'),
    ('data/anime/menu_layout_crown_saikyo.anm', 11112, 'cdbb19cf16e2e41b643622166e7c8b32885585da0b925c296a748943f6b2c8e3'),
    ('data/anime/menu_layout_crown_saikyo_all.anm', 15744, 'a2d0b532e4e0f4a3543d898f9c623595737f83139236f7cc649c7b4452b178c0'),
    ('data/sprite/font_28_black_1.png', 630259, '68153bbc2dfe28e69627a6d085994ad93b1c730dbe3dd17168c2d529c92894ed'),
    ('data/sprite/menu_p_card_14_battle_sen.png', 3684, '2113f7237a240256cd4b261742cac1cf3ed5ae04629377005e076b04672fc364'),
    ('data/sprite/menu_p_card_5_graph.png', 88650, 'd7d53a8c7141ea3517ab86f67b4260c044ab28099878bf9e6ff7267876fed273'),
    ('data/sprite/menu_p_card_5_menu.png', 4589, 'caca7930e071411c4db46f99e788dc9336de1e000e81c7f952acd03303196575'),
    ('data/sprite/menu_p_card_5_point_1.png', 3024, '3335cd2e10c36ea957a69ef0861f68b134933a5cede6def397d40330f191aa27'),
    ('data/sprite/menu_p_card_5_point_2.png', 2949, 'd015924c7e757cb14ec952e78364a585edd739a72d16f3c1a90373c64695c7c1'),
    ('data/sprite/menu_p_card_5_point_3.png', 3291, 'c3831a18aac03af01d80ea93de417d2bba4d86600b7a5986b6bc6d8927040f81'),
    ('data/sprite/menu_p_card_5_title.png', 7687, '9a8041b5b3d91df837f5244c3bd03529fc832ff571c0fb465cd85aaab20e9626'),
    ('data/sprite/menu_p_card_waku_1.png', 34641, '2af996167cb492884a65f9e0a219b7bf626eca39c5f4e6e071ea5281857b56b7'),
    ('data/sprite/menu_p_crown_L_C1.png', 84861, '8fed58e3ce85a04803b751b24b860a693734b6cb6e369ed3db8253c6d3e2f58a'),
    ('data/sprite/menu_p_crown_L_fk.png', 60749, '2cbc6e70166c0180b647010e1e905f67b6a830b6c7e39eaf7d142b814ad4aaff'),
    ('data/sprite/menu_p_crown_L_hk.png', 85101, 'c3a033c86411449e3445fc3d51db6a91528e9fa1d2740695f7c4db1a3783156e'),
    ('data/sprite/menu_p_crown_L_ng.png', 88877, 'a4bcd3a1d6ebf8a7a70c5091d52c9745fa7c96d17bc890f24e632210dc6a06fd'),
    ('data/sprite/menu_p_crown_L_os.png', 81838, '7cb42837f25c049742f2d0d5ed77e1a8cfd9dbb0da1210d77167d0192c539ca2'),
    ('data/sprite/menu_p_crown_L_sk.png', 86648, '58946640f43626ac1684b8c786f75b7e58c92796e75cf830873867b04d40ad3c'),
    ('data/sprite/menu_p_crown_L_wg.png', 89671, '75b251fdf1c12d783dd1abe3b6661854113ff0995125bb51f2a0b1bf8a50f3fa'),
    ('data/sprite/menu_p_crown_L_yk.png', 88340, '1c4e8a8f887f7262173be7f80370eada9ec80a52c7def35ffb161e4e8f65c04b'),
    ('data/sprite/menu_p_crown_S_C1.png', 16208, '0bf6b01b52b0a37f5aa2d5aedddc17927e6d4e3e17445cda4d79e1dda1b92029'),
    ('data/sprite/menu_p_crown_S_fk.png', 13016, 'c31883970849062b2fad5fdec57e2770a5d2c58255128aebc674f5325a667644'),
    ('data/sprite/menu_p_crown_S_hk.png', 17058, 'd75125790265acc1482bcbd6a43b678fba79c980fbb9a5e2a1d2b89de6c19d74'),
    ('data/sprite/menu_p_crown_S_ng.png', 17604, 'f7619f54bc42479067fae0fb6322a1db8adc2144c1426abb1216f2314f4642f7'),
    ('data/sprite/menu_p_crown_S_os.png', 15747, '713f7669233f93bdfe6914f111ded3618267e043d3b29aaa9561a383e79cb242'),
    ('data/sprite/menu_p_crown_S_sk.png', 11900, '0d0596549ebbf9e34b689b249d6d4c8e09e621197f003e53ef8fdd6db6fe4156'),
    ('data/sprite/menu_p_crown_S_waku_C1.png', 14804, 'f6e7945460d74aec56636d9f502301adec4bd2f1aacac9e59ba5e2c7eef4e857'),
    ('data/sprite/menu_p_crown_S_waku_fk.png', 12104, '877cff2a884b11fc09c4c16734d1d7c8a4818f6cd2fc48fa12b272f5402d66ea'),
    ('data/sprite/menu_p_crown_S_waku_hk.png', 15803, '6f412a7736a10b7ca8c56e443e6061d2a25f51a2b95b85efe66d6367bd957ffb'),
    ('data/sprite/menu_p_crown_S_waku_ng.png', 16599, '39dd4baa96ce2ed05637887916fe9f6153bf25b0c6ef5f11b05820c71071c2db'),
    ('data/sprite/menu_p_crown_S_waku_os.png', 14399, 'cb0a46aacd6cb2a920615b739cbeb1e0bd331cc6a59e400e95db9a5ef55a8185'),
    ('data/sprite/menu_p_crown_S_waku_sk.png', 11337, 'be77cc2d0d119926e469356594f3492b6179d138973ff7d849bc378d38ffec08'),
    ('data/sprite/menu_p_crown_S_waku_wg.png', 12965, 'e43fc164f31d88a54982a20f21ee46b2488b6bbfcadcd5cadbcc5805e9439db3'),
    ('data/sprite/menu_p_crown_S_waku_yk.png', 14961, '4988f795b7baea47fc6b3ca0cf51169c51d08674ed1d361be82f3a95af48858b'),
    ('data/sprite/menu_p_crown_S_wg.png', 14204, '69eaa6236da23e2a5d9dc3c4b2b2bfcd717a5c36d8b24bf5310c15104f93e37d'),
    ('data/sprite/menu_p_crown_S_yk.png', 17277, '857fbfba604d5e48aba52deecde68bc4b0db6dbfea3c4439543a09fd87ff89a9'),
    ('data/sprite/menu_p_crown_atract_c1.png', 62498, 'ed001430bcb3167c318373950f86ed111682bbb6e8e8d4de53361f50f16d4779'),
    ('data/sprite/menu_p_crown_atract_fk.png', 44136, '92c35817e1c98c44bfda541da88ee3be3528b8a8dfd6c7b310e8d0bfb5aa4ee2'),
    ('data/sprite/menu_p_crown_atract_gray.png', 172977, 'c4c9c02a907467410874e66d8029cc31ed75545be067d2d8e092b98b115aaaf1'),
    ('data/sprite/menu_p_crown_atract_hk.png', 61432, '003444cdd4cafb3fcebfb715ed6fb234391aba232e85bbc89ec7fb2f85d05183'),
    ('data/sprite/menu_p_crown_atract_ng.png', 40538, '126b6e08c82dbf252a461a05afabf572ca56e7d3f744c8dad56f8fd77aec8c9a'),
    ('data/sprite/menu_p_crown_atract_os.png', 43675, '00dbd14761d73fd98c87706c4c63d03ba72f82915ea18827029d2c923fa74f02'),
    ('data/sprite/menu_p_crown_atract_sk.png', 50868, 'fb4bc884f9b039b5366bf6083093b3a2219344ded9a77cf3b5cb0ba1865f52ac'),
    ('data/sprite/menu_p_crown_atract_title_ghost.png', 7059, '041de08371a0c2d3ef6cab6a9c593ebb966dacef899035767d2eb03e993cb697'),
    ('data/sprite/menu_p_crown_atract_title_saikyo.png', 15373, '0a4abfbffa8bc1eddf95a19a51161a20c55ad5c1545f9edd8f69ced11f0e0dbd'),
    ('data/sprite/menu_p_crown_atract_wg.png', 45812, 'ccc0934981eb167e4c98b61d788aba4fec114b167c35002eaf868cbd134f2365'),
    ('data/sprite/menu_p_crown_atract_yk.png', 43597, '9bb9d8e0cd50028fd14ce29015a44ff00d401754823dffdb825a31a366ec5ff8'),
    ('data/sprite/menu_p_crown_bg.png', 3747, '73243779311ca3a8247835943051d25f30e73df8cb9c7f690d82832a64b9e0c7'),
    ('data/sprite/menu_p_crown_mes.png', 40227, '6e37d314001a74eea434e72a7ace2e9f6dfc33cf32d283298377d9ace78dbb49'),
    ('data/sprite/menu_p_crown_mes_C1.png', 26124, '1617b75440ccd21ed3d7170efa956422aadf87aac1dd64a942319f5907c5926e'),
    ('data/sprite/menu_p_crown_mes_all.png', 42185, '73888c0dd3802ea0d8191ba7235b1a767dd96b5ae7b28fd3193d6fb71ad57be7'),
    ('data/sprite/menu_p_crown_mes_fk.tga', 262188, '67200d0abb2b1c34246909a4d40268d3a30d97076132f509da6dcc7b5e9b2bd4'),
    ('data/sprite/menu_p_crown_mes_hk.png', 34982, '9ff7bf1c9bd0ce6bb2cc5aaefcf8aa22e778f146084a573cd2663d463e1537a0'),
    ('data/sprite/menu_p_crown_mes_ng.png', 35575, '24ebac2b41be848ce6ad0a8fd099f50059abc361755d9e124799e660fab14f80'),
    ('data/sprite/menu_p_crown_mes_os.png', 32882, '79e8d327620a2b01df06d065ebf5fcfae0c393cda2c2fa52c00095d1d9804bff'),
    ('data/sprite/menu_p_crown_mes_sk.png', 42060, '7ef6d8abab032dac1f3d128d26b2e4b5b4abe9bbcd8f0637852b06358e303022'),
    ('data/sprite/menu_p_crown_mes_wg.png', 41825, '356b006c1cc6fbb2271cd8d8c8ac3efc02a01ecd59c2ef1a7c58495be8f9d170'),
    ('data/sprite/menu_p_crown_mes_yk.png', 44689, '916d09bfe0b2424b481df4b363d8dfdbd72969d826ae59ab71801debf58065f8'),
    ('data/sprite/menu_p_crown_title.png', 22930, 'c252b5f6fcee25adf4e9ccc0b04c72259363c14ed72453844fca24dbc57a8e3a'),
    ('data/sprite/menu_p_flash.png', 205925, '11b80aeab5e35a6e126fe7bb00c46ae1c373cd2a8823803515c642eccbbbe7bc'),
    ('data/sprite/menu_p_topbar_mes_cardcheck_6.png', 30419, 'a5a2b43cd381430ea1d30901471e72b33e874df4fa6090c522aef911bd87b260'),
)


def _readset():
    rows = [*SOURCE_PINS, ('main', 24855892, MAIN_SHA256)]
    data = json.dumps({'schema': 'wmmt-original-readset-v1', 'main_sha256': MAIN_SHA256,
                       'files': [{'path': path, 'bytes': size, 'sha256': digest}
                                 for path, size, digest in rows]}).encode('utf-8')
    return ReviewedReadSet.parse(data, expected_sha256=hashlib.sha256(data).hexdigest())


def _pack(source, target, cancel, progress):
    support = OriginalSupport(source.read('main', max_bytes=24855892, cancel=cancel), cancel=cancel)
    renderer = SpriteRenderer(support, source.read, cancel=cancel)
    ids, animations = set(EXTRA_SPRITES), []
    total = len(ANIMATIONS)
    for index, name in enumerate(ANIMATIONS, 1):
        path = f'data/anime/{name}.anm'
        frames, records = load_anm(source.read(path, max_bytes=1024 * 1024, cancel=cancel), cancel=cancel)
        start, poses = 0, []
        for offset, count in frames:
            check_cancel(cancel)
            pose = [row for row in records[offset:offset + count] if row[0] >= 0 and
                    (name != 'menu_layout_cardcheck_5' or row[0] not in STYLE_PLACEHOLDERS)]
            ids.update(row[0] for row in pose)
            poses.append((start, pose))
            start += len(pose)
        animations.append((name, poses, start))
        if progress:
            progress('pack-crown-scenes', index, total + 1)

    with target.open('xb') as out:
        out.write(struct.pack('<4sIII', b'WCP1', 1, len(ids) + 1, total))
        for sid in sorted(ids):
            image = renderer.sprite(sid, table_size=True)
            out.write(struct.pack('<iHHI', SPRITE_BASE + sid, *image.size, 0))
            out.write(image.tobytes())
        label = renderer.text(5, '撃墜')
        out.write(struct.pack('<iHHI', 149000, *label.size, 0))
        out.write(label.tobytes())
        for name, poses, records in animations:
            alias = f'cscene_{name}'.encode('ascii')
            out.write(struct.pack('<48sII', alias, len(poses), records))
            for start, pose in poses:
                out.write(struct.pack('<II', start, len(pose)))
            for _, pose in poses:
                for row in pose:
                    blend = {8: 1, 9: 2}.get(row[15], 0)
                    out.write(struct.pack('<iH6f8h', SPRITE_BASE + row[0], blend, *row[1:7],
                                          *(max(-32768, min(32767, x)) for x in row[7:15])))
        out.flush()
        os.fsync(out.fileno())
    if progress:
        progress('pack-crown-scenes', total + 1, total + 1)


def pack(original, target, *, cancel=None, progress=None):
    """Create a new bank from a reviewed original folder or archive."""
    readset = _readset()
    source = (FileTreeSource(original, readset) if original.is_dir()
              else ArchiveSource(original, readset, cancel=cancel))
    with source:
        _pack(source, target, cancel, progress)


def convert(root, source_kind, *, cancel=None, progress=None):
    original = root / ('incoming.zip' if source_kind == 'zip' else 'incoming')
    try:
        with TemporaryDirectory(prefix='crown-scenes-', dir=root) as scratch:
            target = Path(scratch) / PACK
            pack(original, target, cancel=cancel, progress=progress)
            check_cancel(cancel)
            os.replace(target, root / PACK)
        return True
    except ConversionCancelled:
        raise
    except (OSError, ValueError):
        return False


if __name__ == '__main__':
    import argparse
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('original', type=Path)
    cli.add_argument('output', type=Path)
    args = cli.parse_args()
    pack(args.original.absolute(), args.output.absolute())
