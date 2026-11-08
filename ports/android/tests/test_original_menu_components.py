"""Safety/ABI tests. All fixtures and outputs stay in ORIGINAL_2D_TEST_TMP.

No original executable/emulator is ever run. Optional ORIGINAL_MENU_ROOT enables
read-only tests against the explicitly selected original main/data tree.
"""
import ast
import hashlib
import io
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from original_convert.menu_support import OriginalSupport, Sprite, MenuConversionError, dimensions
from original_convert.menu_components import (SpriteRenderer, MenuRecipe, _IGB, _Output,
    crop, decode_image, load_anm, load_cutin_lines, _matmul4, pack_menu_slice, HUD_SPRITES, HUD_CROPS, HUD_ATLAS)
from original_convert.source import ConversionCancelled


def png(width=4, height=4, color=(31, 63, 127, 255)):
    from PIL import Image
    data = io.BytesIO()
    Image.new('RGBA', (width, height), color).save(data, format='PNG')
    return data.getvalue()


def animation(record=None, count=1, frames=((0, 1),)):
    if record is None:
        record = (7, 1., 0., 0., 1., 2., 3., 256, 256, 256, 256, 0, 0, 0, 0, 8)
    return struct.pack('<II', len(frames), count) + b''.join(struct.pack('<II', *f) for f in frames) + struct.pack('<i6f9i', *record)


class MemoryElf:
    def read(self, address, size):
        if address == 0x2000 + 2 * (ord('A') >> 5) and size == 2:
            return struct.pack('<h', 0)
        if address in (0x3000 + 2 * (ord('A') & 31), 0x3000 + 2 * (ord('B') & 31)) and size == 2:
            return struct.pack('<h', 0)
        if address == 0x1000 and size == 4:
            return struct.pack('<I', 7)
        raise ValueError((address, size))


def fake_support():
    obj = object.__new__(OriginalSupport)
    obj.cancel = None
    obj.elf = MemoryElf()
    obj.sprites = {7: Sprite('data/sprite/test.png', 4., 4.)}
    obj.font = lambda font: (3, 2, 3, 4, 2, 2, 4, 0x1000, 0x2000)
    return obj


class FixtureTest(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get('ORIGINAL_2D_TEST_TMP')
        self.assertTrue(parent, 'Set ORIGINAL_2D_TEST_TMP to an isolated new 2D workspace directory')
        self.tmp = tempfile.TemporaryDirectory(dir=parent, prefix='original-menu-test-')
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class BoundsTests(unittest.TestCase):
    def test_main_pin_cannot_be_overridden(self):
        with self.assertRaises(MenuConversionError) as caught:
            OriginalSupport(b'not the original main')
        self.assertEqual(caught.exception.code, 'unsupported_source')

    def test_dimensions(self):
        for width, height in ((0, 1), (1, -1), (4097, 1), (True, 1), (1.2, 4)):
            with self.subTest(width=width, height=height), self.assertRaises(MenuConversionError):
                dimensions(width, height)
        self.assertEqual(dimensions(1024, 1024), (1024, 1024))

    def test_image_and_crop(self):
        image = decode_image(png())
        self.assertEqual(image.mode, 'RGBA')
        self.assertEqual(crop(image, (0, 0, 2, 2)).size, (2, 2))
        with self.assertRaises(MenuConversionError):
            crop(image, (-1, 0, 2, 2))
        with self.assertRaises(MenuConversionError):
            crop(image, (3, 0, 2, 2))
        with self.assertRaises(MenuConversionError):
            decode_image(b'invalid image')

    def test_png_large_dimensions_rejected_before_pixels(self):
        data = bytearray(png())
        struct.pack_into('>II', data, 16, 5000, 5000)
        struct.pack_into('>I', data, 29, zlib.crc32(data[12:29]) & 0xFFFFFFFF)
        with self.assertRaises(MenuConversionError):
            decode_image(bytes(data))

    def test_hud_unique_fixed_names(self):
        names = list(HUD_SPRITES) + [r[0] for r in HUD_ATLAS] + ['title', 'name', 'cons_p_finish_made', 'cons_p_ltime_time'] + [r[0] for r in HUD_CROPS]
        self.assertEqual(len(names), 178)
        self.assertEqual(len(set(names)), 178)
        self.assertTrue(all(len(n.encode('ascii')) < 32 for n in names))

    def test_igb_bad_header_and_counts(self):
        for data in (bytes(48), struct.pack('<12I', 0, 0xFFFFFFFF, 0, 0, 0, 0, 0, 0, 0, 0, 0xFADA, 8)):
            with self.assertRaises(MenuConversionError):
                _IGB(data)

    def test_igb_cancellation(self):
        with self.assertRaises(ConversionCancelled):
            _IGB(bytes(48), lambda: True)


class AnimationTests(unittest.TestCase):
    def test_raw_record_and_blend(self):
        frames, records = load_anm(animation())
        self.assertEqual(frames, ((0, 1),))
        self.assertEqual(records[0][0], 7)
        self.assertEqual(records[0][-1], 8)

    def test_keep_is_bounded(self):
        for keep in (0, -1, 2, True):
            with self.assertRaises(MenuConversionError):
                load_anm(animation(), keep=keep)

    def test_frame_ranges_and_alignment(self):
        for value in (animation(frames=((1, 1),)), animation(count=0), animation()[:-1], bytes(7)):
            with self.assertRaises(MenuConversionError):
                load_anm(value)

    def test_nonfinite_and_unknown_sid(self):
        for index, value in ((1, math.nan), (5, math.inf), (0, 99999), (15, -1)):
            record = [7, 1., 0., 0., 1., 2., 3., 256, 256, 256, 256, 0, 0, 0, 0, 8]
            record[index] = value
            with self.assertRaises(MenuConversionError):
                load_anm(animation(tuple(record)))

    def test_record_budget(self):
        with self.assertRaises(MenuConversionError):
            load_anm(struct.pack('<II', 20001, 1))

    def test_cancel(self):
        with self.assertRaises(ConversionCancelled):
            load_anm(animation(), cancel=lambda: True)


class TextAndAffineTests(unittest.TestCase):
    def test_native_fullwidth_spaces_survive(self):
        data = 'ECUTIN_B\nECUTINSERIAL_ONESHOT 1 0 ECutInStart nsCutinDisp::CHAR_AKIO2 1 ECutInFacePos_Left ECutInWay_Right 原文　保持#space\\n次行 0\n'.encode()
        result = load_cutin_lines(data)
        self.assertEqual(result, (('CHAR_AKIO2', 1, ('原文　保持 space', '次行')),))

    def test_cutin_bad_counts_and_invalid_utf8(self):
        for data in (b'ECUTIN_B', b'\xff', b'ECUTINSERIAL_ONESHOT 1 0 invalid'):
            with self.assertRaises(MenuConversionError):
                load_cutin_lines(data)

    def test_affine_identity_translation_and_nonfinite(self):
        import numpy as np
        left = np.asarray([[1.,2.,3.,1.],[-1.,-2.,-3.,1.]], dtype=np.float32)
        identity = np.eye(4, dtype=np.float32)
        np.testing.assert_array_equal(_matmul4(left, identity), left)
        identity[3,:3] = [7.,11.,13.]
        np.testing.assert_array_equal(_matmul4(left, identity), [[8.,13.,16.,1.],[6.,9.,10.,1.]])
        identity[0,0] = np.inf
        with self.assertRaises(MenuConversionError):
            _matmul4(left, identity)


class SpriteTests(unittest.TestCase):
    def test_font_uses_original_sheet_not_system_font(self):
        names = []
        def read(name, *, max_bytes, cancel=None):
            names.append(name)
            return png(8, 8)
        renderer = SpriteRenderer(fake_support(), read)
        image = renderer.text(0, 'AB')
        self.assertEqual(image.size, (6, 4))
        self.assertEqual(names, ['data/sprite/test.png'])
        self.assertEqual(image.getpixel((0, 0)), (31, 63, 127, 255))

    def test_lines_and_text_budgets(self):
        renderer = SpriteRenderer(fake_support(), lambda *a, **k: png(8, 8))
        self.assertEqual(renderer.lines(0, ('A', '', 'B')).size, (6, 10))
        for value in ('', 'A' * 4097):
            with self.assertRaises(MenuConversionError):
                renderer.text(0, value)
        with self.assertRaises(MenuConversionError):
            renderer.lines(0, ['A'] * 129)
        with self.assertRaises(MenuConversionError):
            renderer.text(0, chr(0x10000))

    def test_readers_must_respect_budget_and_paths(self):
        renderer = SpriteRenderer(fake_support(), lambda *a, **k: b'x' * (32 * 1024 * 1024 + 1))
        with self.assertRaises(MenuConversionError):
            renderer.sprite(7)
        with self.assertRaises(Exception):
            renderer.image('data/../../escape.png')
        with self.assertRaises(MenuConversionError):
            renderer.sprite(8)

    def test_source_change_without_cache_rejected(self):
        images = iter((png(), png(color=(1, 2, 3, 4))))
        renderer = SpriteRenderer(fake_support(), lambda *a, **k: next(images), cache_bytes=0)
        renderer.sprite(7)
        with self.assertRaises(MenuConversionError) as caught:
            renderer.sprite(7)
        self.assertEqual(caught.exception.code, 'source_changed')


class OutputTests(FixtureTest):
    def test_exclusive_existing_unchanged(self):
        target = self.root / 'existing.bin'
        target.write_bytes(b'old')
        with self.assertRaises(FileExistsError):
            with _Output(target) as output:
                output.write(b'new')
        self.assertEqual(target.read_bytes(), b'old')

    def test_symlink_parent_rejected(self):
        actual = self.root / 'actual'
        actual.mkdir()
        link = self.root / 'linked'
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(Exception):
            with _Output(link / 'new.bin'):
                pass
        self.assertFalse((actual / 'new.bin').exists())

    def test_new_partial_retained_on_cancellation(self):
        target = self.root / 'partial.bin'
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            return calls >= 3
        with self.assertRaises(ConversionCancelled):
            with _Output(target, cancel=cancel) as output:
                output.write(b'x' * 150000)
        self.assertEqual(target.stat().st_size, 65536)

    def test_output_budget_and_observed_digest(self):
        target = self.root / 'new.bin'
        with _Output(target, max_bytes=10) as output:
            output.write(b'123')
        self.assertEqual(output.receipt()['observed_sha256'], hashlib.sha256(b'123').hexdigest())
        self.assertFalse(output.receipt()['publication_authority'])
        with _Output(self.root / 'small.bin', max_bytes=1) as output:
            with self.assertRaises(MenuConversionError):
                output.write(b'12')

    def test_real_wmn3_slice_and_compression(self):
        def read(name, **kw):
            return animation() if name.endswith('.anm') else png(8, 8)
        out = self.root / 'menu.partial.bin'
        result = pack_menu_slice(fake_support(), read, out,
                                 MenuRecipe((('fixture', None),), texts=((100000, 0, ('AB',)),)))
        data = out.read_bytes()
        self.assertEqual(data[:4], b'WMN3')
        self.assertEqual(struct.unpack_from('<I', data, 4)[0], 2)
        sid, width, height, size = struct.unpack_from('<iHHI', data, 8)
        self.assertEqual((sid, width, height), (7, 4, 4))
        self.assertEqual(len(zlib.decompress(data[20:20 + size])), 64)
        self.assertFalse(result['complete_menu'])
        self.assertEqual(result['coverage'], 'partial-menu-slice')

    def test_partial_cannot_impersonate_full_menu(self):
        with self.assertRaises(MenuConversionError) as caught:
            pack_menu_slice(fake_support(), lambda *a, **k: b'', self.root / 'menu.bin')
        self.assertEqual(caught.exception.code, 'incomplete_menu')
        self.assertFalse((self.root / 'menu.bin').exists())

    def test_menu_missing_original_sprite_fails_not_fallback(self):
        support = fake_support()
        support.sprites = {}
        with self.assertRaises(MenuConversionError):
            pack_menu_slice(support, lambda *a, **k: animation(), self.root / 'menu.partial.bin', MenuRecipe((('fixture', None),)))
        self.assertFalse((self.root / 'menu.partial.bin').exists())

    def test_duplicate_anims_rejected(self):
        with self.assertRaises(MenuConversionError):
            pack_menu_slice(fake_support(), lambda *a, **k: animation(), self.root / 'menu.partial.bin',
                            MenuRecipe((('fixture', None), ('fixture', None))))


@unittest.skipUnless(os.environ.get('ORIGINAL_MENU_ROOT'), 'Original main opt-in not selected')
class RealStaticSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.support = OriginalSupport.from_main(Path(os.environ['ORIGINAL_MENU_ROOT']) / 'main')

    def test_static_tables_and_namespaces(self):
        self.assertEqual(len(self.support.sprites), 8087)
        self.assertNotIn(2, self.support.sprites)
        self.assertNotIn(3, self.support.sprites)
        self.assertEqual(len(self.support.title_chars()), 1573)
        self.assertEqual(len(self.support.story_select()['sprites']), 244)
        self.assertEqual(len(self.support.tuning()['texts']), 326)
        self.assertEqual(len(self.support.name_chars()), 256)

    def test_wear_story_and_uv_namespaces(self):
        self.assertEqual(len(self.support.dress_sprites()),83)
        self.assertEqual(len(self.support.wheel_set_sprites()),327)
        self.assertEqual(len(self.support.parts_sprite_literals()['provenance']),412)
        self.assertEqual(len(self.support.wear_texts()), 41)
        self.assertEqual(self.support.wear_texts()[18], (4, '取り外し完了！'))
        self.assertEqual(len(self.support.tuning_effects()['texts']), 52)
        self.assertEqual(len(self.support.bgm_texts()), 22)
        self.assertEqual(len(self.support.ten_banners()), 64)
        demo = self.support.story_demo()
        self.assertEqual((demo['tables'],demo['events'],len(demo['animations']),len(demo['texts'])), (127,1062,57,221))
        faces = self.support.cutin_faces()
        self.assertEqual(len(faces['by_char']),66)
        self.assertEqual(faces['by_char'].count(None),1)
        uv = self.support.uv_cells(with_provenance=True)
        self.assertEqual((len(uv['cells']),len(uv['word_sources']),uv['initialized_records']), (276,276,278))
        self.assertEqual(uv['cells'][211], (56,508,48,764,80))
        self.assertEqual(uv['cells'][274], (56,344,212,364,232))
        self.assertLessEqual(uv['operations'],5000)
        self.assertTrue(all(len(row)==5 and all(r['kind'] in ('zero','elf-word') for r in row) for row in uv['word_sources']))

    def test_uv_unknown_form_rejects_without_vm(self):
        original = self.support.elf
        class ChangedShape:
            def code(self, address, size):
                data = original.code(address,size)
                return b'\\x90' + data[1:] if address == 0x8A0AB49 else data
            def __getattr__(self, name):
                return getattr(original,name)
        self.support.elf = ChangedShape()
        try:
            with self.assertRaises(MenuConversionError) as caught:
                self.support.uv_cells()
            self.assertEqual(caught.exception.code,'unsupported_2d_shape')
        finally:
            self.support.elf = original

    def test_meter_dial_sprite_order_regression(self):
        from original_convert.car_tables import build_car_tables
        root = Path(os.environ['ORIGINAL_MENU_ROOT'])
        cars = build_car_tables(root/'main',root/'data/car')
        layouts = self.support.meter_layouts(self.support.pack_order(cars['packs']))
        self.assertEqual(len(layouts),55)
        first = layouts[0]['parts'][0]
        # Native +0x3c is tach (128px); +0x40 is turbo/boost (64px).
        self.assertEqual([p.sprite for p in first],[965,301,300,217])
        r35 = next(c for c in layouts if c['folder']=='nis_R35')
        self.assertEqual([p.sprite for p in r35['parts'][1]],[1033,359,246,247,546,547,549,88,356])

    def test_all_fonts_and_hud_text_glyphs(self):
        self.assertEqual([self.support.font(i)[3] for i in range(11)], [15,20,20,30,32,32,32,40,32,50,100])
        for font, text in ((0, '湾岸の新人'), (1, 'ＧＵＥＳＴ')):
            for char in text:
                sid, _, advance = self.support.glyph(font, char)
                self.assertIn(sid, self.support.sprites)
                self.assertGreater(advance, 0)


if __name__ == '__main__':
    unittest.main()
