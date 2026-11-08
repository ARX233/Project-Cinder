"""Guarded character wheel color rules: synthetic safety and opt-in sources.

Synthetic files stay under WMMT_TEST_WORK_ROOT. Real factory checks additionally
select WMMT_TEST_ORIGINAL_MAIN / WMMT_TEST_ORIGINAL_ROOT; no gold is needed by
this test module or by the production module.
"""
from dataclasses import FrozenInstanceError, replace
import hashlib
import os
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / 'tools'
if not TOOLS.is_dir():
    TOOLS = Path(os.environ['WMMT_TEST_TOOLS'])
sys.path.insert(0, str(TOOLS))
from original_convert import chara_colors as colors
from original_convert.physics_image import PhysicsImageError, ConversionCancelled


sha = lambda raw: hashlib.sha256(raw).hexdigest()


def fixture(fmt=1):
    before = struct.pack('<4H', *( [0xF800, 0x001F, 0x07E0, 0xFFFF] if fmt == 0 else [0xF00A, 0x00F5, 0x0F03, 0xABCD]))
    after = struct.pack('<4H', *( [0x001F, 0xF800, 0x07E0, 0xFFFF] if fmt == 0 else [0x00FA, 0xF005, 0x0F03, 0xCBAD]))
    image = colors.ImageRule('fixture_diffuse.dds', 12, 14 if fmt == 0 else 15, 100, 4, 1, fmt,
                             sha(before), sha(after), '1' * 64, (('TIRE_W1_FL', 'WHEEL_FL'),))
    rule = colors._mint_rule('toy_fixture', 'toy_fixture', {'model': 247, 'car': 56}, 'dummy_wheel',
                            [{'path': 'data/characar/toy_fixture/tire.igb', 'sha256': '2' * 64, 'bytes': 128}], [image])
    textures = {image.name: (4, 1, fmt, before), 'fixture_spec.dds': (4, 1, fmt, before)}
    meshes = [(colors.WHEEL, image.name, 0, None, None, (2, 'env.dds', 'fixture_spec.dds', 0))]
    return rule, textures, meshes, before, after


def apply(rule, textures, meshes, *, folder='toy_fixture', kind='characar', wheel=None):
    return colors.apply_chara_wheel_colors(folder, kind, {'name': 'dummy_wheel'} if wheel is None else wheel,
                                           textures, meshes, rule)


class PackedSemanticsTests(unittest.TestCase):
    def test_rgb565_exact_red_blue_and_green_bits(self):
        rule, textures, meshes, before, after = fixture(0)
        self.assertEqual(colors._swap_packed(before, 0), after)
        result = apply(rule, textures, meshes)
        self.assertTrue(result['applied'])
        self.assertEqual(textures[rule.images[0].name][3], after)
        self.assertEqual(textures['fixture_spec.dds'][3], before)

    def test_rgba4444_exact_red_blue_green_and_alpha(self):
        rule, textures, meshes, before, after = fixture(1)
        self.assertEqual(colors._swap_packed(before, 1), after)
        apply(rule, textures, meshes)
        self.assertEqual(textures[rule.images[0].name][3], after)
        for a, b in zip(struct.unpack('<4H', before), struct.unpack('<4H', after)):
            self.assertEqual(a & 0x0F0F, b & 0x0F0F)

    def test_randomized_involution_and_preserved_non_swapped_fields(self):
        rng = random.Random(134)
        raw = struct.pack('<2000H', *(rng.randrange(65536) for _ in range(2000)))
        for fmt, mask in ((0, 0x07E0), (1, 0x0F0F)):
            changed = colors._swap_packed(raw, fmt)
            self.assertEqual(colors._swap_packed(changed, fmt), raw)
            self.assertTrue(all(a & mask == b & mask for a, b in zip(struct.unpack('<2000H', raw), struct.unpack('<2000H', changed))))

    def test_unknown_encoding_and_partial_pixels_reject(self):
        for raw, fmt in ((b'\x00', 1), (bytes(2), 2), (bytearray(2), 1)):
            with self.assertRaises(colors.CharaColorError):
                colors._swap_packed(raw, fmt)

    def test_source_rgba_quantization_matches_packed_semantics(self):
        from PIL import Image
        for rgba, fmt in (((240, 32, 16, 255), 0), ((240, 32, 16, 160), 1)):
            image = Image.new('RGBA', (128, 128), rgba)
            before = colors._encode_source_rgba(image)
            r, g, b, a = image.split()
            after = colors._encode_source_rgba(Image.merge('RGBA', (b, g, r, a)))
            self.assertEqual(before[2], fmt)
            self.assertEqual(colors._swap_packed(before[3], fmt), after[3])

    def test_unreviewed_size_and_rgba5551_source_lanes_reject(self):
        from PIL import Image
        for size, rgba in (((4, 4), (255, 0, 0, 255)), ((128, 128), (255, 0, 0, 0))):
            with self.assertRaises(colors.CharaColorError):
                colors._encode_source_rgba(Image.new('RGBA', size, rgba))


class HookGuardsTests(unittest.TestCase):
    def test_stock_and_aero_kind_are_strict_noops(self):
        for kind in ('car', 'othercar', 'wheel'):
            rule, textures, meshes, before, after = fixture()
            original = dict(textures)
            self.assertEqual(apply(None, textures, meshes, kind=kind), {'applied': False, 'images': []})
            self.assertEqual(textures, original)

    def test_missing_plain_dict_or_foreign_issuer_rules_reject(self):
        for invalid in (None, {}, 'patched-table'):
            rule, textures, meshes, before, after = fixture()
            original = dict(textures)
            with self.assertRaises(colors.CharaColorError):
                apply(invalid, textures, meshes)
            self.assertEqual(textures, original)
        rule, textures, meshes, _, _ = fixture()
        with self.assertRaises(colors.CharaColorError):
            apply(replace(rule, _seal=object()), textures, meshes)

    def test_rules_are_immutable_and_commit_all_identity_fields(self):
        rule, textures, meshes, _, _ = fixture()
        with self.assertRaises(FrozenInstanceError):
            rule.folder = 'another'
        for invalid in (replace(rule, model=999), replace(rule, car=999), replace(rule, source_main_sha256='0' * 64)):
            with self.assertRaises(colors.CharaColorError):
                apply(invalid, textures, meshes)

    def test_wrong_folder_or_wheel_name_rejects_without_mutation(self):
        for kwargs in ({'folder': 'other_folder'}, {'wheel': {'name': 'custom_wheel'}}):
            rule, textures, meshes, _, _ = fixture()
            original = dict(textures)
            with self.assertRaises(colors.CharaColorError):
                apply(rule, textures, meshes, **kwargs)
            self.assertEqual(textures, original)

    def test_nonwheel_reuse_missing_refs_and_out_of_range_corner_reject(self):
        for groups in ((0,), (colors.WHEEL + 4,), (colors.WHEEL, 0), ()):
            rule, textures, meshes, _, _ = fixture()
            selected = [(group, rule.images[0].name, 0, None, None, None) for group in groups]
            original = dict(textures)
            with self.assertRaises(colors.CharaColorError):
                apply(rule, textures, selected)
            self.assertEqual(textures, original)

    def test_env_and_specular_reuse_reject_even_on_other_mesh(self):
        for slot in (1, 2):
            rule, textures, meshes, _, _ = fixture()
            material = [2, None, None, 0]
            material[slot] = rule.images[0].name
            selected = meshes + [(0, 'unrelated.dds', 0, None, None, tuple(material))]
            original = dict(textures)
            with self.assertRaises(colors.CharaColorError):
                apply(rule, textures, selected)
            self.assertEqual(textures, original)

    def test_missing_image_wrong_size_format_length_or_pixels_reject(self):
        rule, textures, meshes, before, after = fixture()
        for bad in (None, (8, 1, 1, before), (4, 1, 0, before), (4, 1, 1, before[:-2]), (4, 1, 1, after)):
            changed = dict(textures)
            if bad is None:
                del changed[rule.images[0].name]
            else:
                changed[rule.images[0].name] = bad
            original = dict(changed)
            with self.assertRaises(colors.CharaColorError):
                apply(rule, changed, meshes)
            self.assertEqual(changed, original)

    def test_malformed_mesh_and_material_shapes_reject_transactionally(self):
        for bad in ([(colors.WHEEL, 'fixture_diffuse.dds')], [(colors.WHEEL, 'fixture_diffuse.dds', 0, None, None, (1,))]):
            rule, textures, meshes, _, _ = fixture()
            original = dict(textures)
            with self.assertRaises(colors.CharaColorError):
                apply(rule, textures, bad)
            self.assertEqual(textures, original)

    def test_already_converted_texture_cannot_be_applied_twice(self):
        rule, textures, meshes, _, _ = fixture()
        apply(rule, textures, meshes)
        once = dict(textures)
        with self.assertRaises(colors.CharaColorError):
            apply(rule, textures, meshes)
        self.assertEqual(textures, once)


class FactoryGuardsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='chara-color-test-', dir=os.environ.get('WMMT_TEST_WORK_ROOT'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.main = self.root / 'main'
        self.main.write_bytes(b'not-the-reviewed-original-main' * 3)

    def test_bad_pin_rejects_before_loading_igb_parser(self):
        with patch.object(colors, '_stage_scene') as loader, self.assertRaises(colors.CharaColorError) as err:
            colors.derive_chara_wheel_rules(self.main, self.root, ['toy_fixture'])
        self.assertEqual(err.exception.code, 'unsupported_source')
        loader.assert_not_called()

    def test_selection_bound_case_collision_and_traversal_reject(self):
        for folders in ([], ['../escape'], ['foo/bar'], ['same', 'SAME'], ['x' + str(n) for n in range(65)]):
            with self.subTest(folders=folders), self.assertRaises(colors.CharaColorError):
                colors.derive_chara_wheel_rules(self.main, self.root, folders)

    def test_missing_source_cancellation(self):
        with self.assertRaises(ConversionCancelled):
            colors.derive_chara_wheel_rules(self.root / 'absent', self.root, ['toy_fixture'], cancel=lambda: True)

    def test_main_symlink_rejects(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.main)
        with self.assertRaises(PhysicsImageError):
            colors.derive_chara_wheel_rules(alias, self.root, ['toy_fixture'])

    def test_no_old_reference_or_source_pin_override_parameters(self):
        for kwargs in ({'gold_wpk': self.main}, {'expected_source_sha256': '0' * 64}):
            with self.assertRaises(TypeError):
                colors.derive_chara_wheel_rules(self.main, self.root, ['toy_fixture'], **kwargs)

    def test_wheel_path_prefix_accepts_original_corner_names_only_by_role(self):
        for path in (('TIRE_FL', 'WHEEL_L'), ('WHEEL_FL',), ('TIRE_RR', 'WHEEL_RR')):
            self.assertTrue(colors._wheel_path(path))
        for path in ((), ('TIRE_W1_FL',), ('BODY', 'RIM')):
            self.assertFalse(colors._wheel_path(path))


@unittest.skipUnless(os.environ.get('WMMT_TEST_ORIGINAL_MAIN') and os.environ.get('WMMT_TEST_ORIGINAL_ROOT'),
                     'User-owned original sources not selected')
class OriginalRulesTests(unittest.TestCase):
    def test_two_real_source_rules_and_main_before_after_hash(self):
        main = Path(os.environ['WMMT_TEST_ORIGINAL_MAIN'])
        before = sha(main.read_bytes())
        rules = colors.derive_chara_wheel_rules(main, os.environ['WMMT_TEST_ORIGINAL_ROOT'],
                        ['nis_BCNR33_Kuroki', 'gem_964_38RS_Shima1st'])
        for rule in rules.values():
            self.assertEqual(rule.source_main_sha256, colors.SOURCE_SHA256)
            self.assertEqual(len(rule.images), 1)
            self.assertEqual(rule.images[0].component_order, 100)
            self.assertEqual(rule.images[0].source_format, 15)
            self.assertEqual(rule.images[0].wpk_format, 1)
            self.assertEqual((rule.images[0].width, rule.images[0].height), (128, 128))
            self.assertEqual(len(rule.source_receipts), 2)
        self.assertEqual(sha(main.read_bytes()), before)
        self.assertEqual(before, colors.SOURCE_SHA256)


if __name__ == '__main__':
    unittest.main(verbosity=2)
