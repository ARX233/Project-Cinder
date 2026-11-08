"""Synthetic scene projections plus opt-in full real storypre/TEN comparison.

Artifacts use WMMT_TEST_WORK_ROOT.  Real inputs: WMMT_TEST_ORIGINAL_MAIN;
comparison-only headers: WMMT_TEST_STORYPRE_ORACLE / WMMT_TEST_TENDB_ORACLE.
No target instructions or emulator are executed, and no header constructs data.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
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
from original_convert import menu_scene_sprites as scene
from original_convert.physics_image import Elf32, PhysicsImageError, ConversionCancelled


class SyntheticReader:
    """Sparse, non-executing synthetic byte regions."""
    def __init__(self):
        self.regions = [(base, bytearray(size)) for base, size in (
            (0x857CE00, 0x1000), (0x8633300, 0x300), (0x8835600, 0x100),
            (0x883C2E0, 0x200), (0x88A8810, 0x140),
            (0x93DD8C0, 61 * 8), (0x93DDC00, 24 * 16),
            (0x93FC920, 100 * 16), (0x93FD3E0, 40),
            (0x940D3E0, 44), (0x940D420, 1760), (0x973A5C0, 113 * 0x158))]

    def put(self, address, raw):
        for base, block in self.regions:
            if base <= address and address + len(raw) <= base + len(block):
                block[address - base:address - base + len(raw)] = raw
                return
        raise AssertionError('Fixture write outside synthetic ranges')

    def code(self, address, size):
        for base, block in self.regions:
            if base <= address and address + size <= base + len(block):
                return bytes(block[address - base:address - base + size])
        raise PhysicsImageError('invalid_elf', 'Synthetic address is unmapped')

    read = code


def synthetic_projection():
    elf = SyntheticReader()
    # Only instruction shapes/geometry are mirrored.  Every source table value
    # below is synthetic and unrelated to any original/generated result table.
    for address, encoding in scene.SHAPES:
        elf.put(address, encoding)
    for _name, address, prefix, width, expected in scene.OPERANDS:
        elf.put(address, prefix + expected.to_bytes(width, 'little'))
    for index in range(61):
        model, image = (247, 2001) if index == 0 else ((248, 2002) if index == 1 else (500 + index, 2100 + index))
        if index == 2:
            model, image = 247, 2003  # first match, not last assignment
        elf.put(0x93DD8C0 + index * 8, struct.pack('<2I', model, image))
    for index in range(24):
        row = (0, 3001, 3002, 1) if index == 0 else ((5, 3003, 3004, 3005) if index == 1 else (100 + index, 3100 + index, 3200 + index, 1))
        if index == 2:
            row = (5, 3331, 3332, 1)  # preserve first matching ramp
        elf.put(0x93DDC00 + index * 16, struct.pack('<4I', *row))
    for index in range(100):
        elf.put(0x93FC920 + index * 16, struct.pack('<4I', 1, 1, 4000 + index, 5000 + index))
    for index in range(112):
        ramp = 9999 if index == 110 else 5
        elf.put(0x973A5C0 + index * 0x158, struct.pack('<4I', 247, 248, 9999, ramp))
    elf.put(0x93FD3E0, struct.pack('<10I', *range(6000, 6010)))
    elf.put(0x940D420, struct.pack('<440I', *range(6500, 6940)))
    elf.put(0x940D3E0, struct.pack('<11I', *range(7000, 7011)))
    return elf


def minimal_elf():
    data = bytearray(84)
    off = len(data)
    data += b'\x90\xc3'
    strings = b'\0.shstrtab\0'
    string_offset = len(data)
    data += strings
    shoff = len(data)
    data += bytes(40) + struct.pack('<10I', 1, 3, 0, 0, string_offset, len(strings), 0, 0, 1, 0)
    struct.pack_into('<16sHHIIIIIHHHHHH', data, 0, b'\x7fELF\x01\x01\x01' + bytes(9), 2, 3, 1,
                     0x8048000, 52, shoff, 0, 52, 32, 1, 40, 2, 1)
    struct.pack_into('<8I', data, 52, 1, off, 0x8048000, 0x8048000, 2, 2, 5, 1)
    return bytes(data)


def reference_story(header):
    pattern = r'^  \{ (\d+), (\d+), (\d+), \{ (\d+), (\d+), (\d+) \}, \{ (\d+), (\d+) \}, (\d+) \},'
    rows = [list(map(int, row)) for row in re.findall(pattern, header, re.M)]
    digits = list(map(int, re.search(r'STORYPRE_DIGIT\[10\] = \{ ([^}]*) \}', header).group(1).split(',')))
    values = set(digits)
    for row in rows:
        values.update(row[1:])
    return rows, digits, sorted(value for value in values if value > 1)


class GeometryTests(unittest.TestCase):
    def test_reviewed_geometry_and_finite_dimensions(self):
        g = scene._geometry(synthetic_projection())
        self.assertEqual(g['story_period'], 100)
        self.assertEqual(g['story_stride'], 0x158)
        self.assertEqual(g['car_image_count'], 61)
        self.assertEqual(g['ramp_count'], 24)
        self.assertEqual([g['ten_courses'], g['ten_levels']], [10, 11])

    def test_unknown_opcode_and_unknown_operand_reject(self):
        for address, raw in ((0x857CED4, b'\xe8'), (0x88A881E, struct.pack('<I', 0x6E4)),
                             (0x863354E + 2, b'\x3e')):
            elf = synthetic_projection()
            elf.put(address, raw)
            with self.subTest(address=address), self.assertRaises(scene.MenuSceneSpriteError):
                scene._geometry(elf)

    def test_in_loop_boundary_and_duplicate_episode_special_case(self):
        g = scene._geometry(synthetic_projection())
        expected = {0: 0, 99: 99, 100: 0, 109: 9, 110: 9, 111: 11}
        self.assertEqual({index: scene._in_loop(index, g) for index in expected}, expected)

    def test_shape_and_operand_work_can_cancel(self):
        with self.assertRaises(ConversionCancelled):
            scene._geometry(synthetic_projection(), lambda: True)


class ProjectionTests(unittest.TestCase):
    def test_complete_synthetic_story_and_ten(self):
        result = scene._project(synthetic_projection())
        self.assertEqual(len(result['story_rows']), 112)
        self.assertEqual(len(result['ten_pre']), 10)
        self.assertTrue(all(len(course) == 11 for course in result['ten_pre']))
        self.assertEqual(result['ten_pre'][0][0], [6500, 6501, 6502, 6503])
        self.assertEqual(result['ten_pre'][9][10], [6936, 6937, 6938, 6939])
        self.assertEqual(result['ten_levels'], list(range(7000, 7011)))
        self.assertEqual(result['ten'], list(range(6500, 6940)) + list(range(7000, 7011)))

    def test_story_fields_first_match_and_missing_car_default(self):
        row = scene._project(synthetic_projection())['story_rows'][0]
        self.assertEqual(row, {'select': 0, 'episode': 1, 'picture': 4000, 'title': 5000,
                              'cars': [2001, 2002, 1], 'bg': [3003, 3004], 'info': 3005})

    def test_special_select_and_missing_ramp_fall_back_to_first_row(self):
        row = scene._project(synthetic_projection())['story_rows'][110]
        self.assertEqual(row['episode'], 10)
        self.assertEqual(row['picture'], 4009)
        self.assertEqual(row['title'], 5009)
        self.assertEqual(row['bg'], [3001, 3002])
        self.assertEqual(row['info'], 1)

    def test_sprite_sets_exclude_episode_numbers_and_none_sentinel(self):
        result = scene._project(synthetic_projection())
        self.assertEqual(result['story_pre'], sorted(set(result['story_pre'])))
        self.assertNotIn(1, result['story_pre'])
        self.assertNotIn(112, result['story_pre'])
        self.assertNotIn(3504, result['story_pre'])
        self.assertEqual(result['story_wa'], 3504)
        self.assertTrue(set(range(6000, 6010)) <= set(result['story_pre']))

    def test_premature_select_sentinel_rejects_partial_coverage(self):
        elf = synthetic_projection()
        elf.put(0x973A5C0 + 111 * 0x158, bytes(4))
        with self.assertRaises(scene.MenuSceneSpriteError):
            scene._project(elf)

    def test_missing_select_sentinel_hits_declared_budget(self):
        with patch.object(scene, 'MAX_STORY_SELECTS', 112), self.assertRaises(scene.MenuSceneSpriteError):
            scene._project(synthetic_projection())

    def test_bad_original_sprite_ids_are_not_silently_dropped(self):
        for address, value in ((0x940D420, 0), (0x93FD3E0, 0xFFFFFFFF), (0x93DDC04, 65536)):
            elf = synthetic_projection()
            elf.put(address, struct.pack('<I', value))
            with self.subTest(address=address), self.assertRaises(scene.MenuSceneSpriteError):
                scene._project(elf)

    def test_bool_is_not_a_sprite_identity(self):
        with self.assertRaises(scene.MenuSceneSpriteError):
            scene._sprite(True)

    def test_table_projection_loops_can_cancel(self):
        count = 0
        def cancel():
            nonlocal count
            count += 1
            return count > 100
        with self.assertRaises(ConversionCancelled):
            scene._project(synthetic_projection(), cancel)


class SourceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='scene-sprite-test-', dir=os.environ.get('WMMT_TEST_WORK_ROOT'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.main = self.root / 'main'
        self.main.write_bytes(minimal_elf())

    def test_fixed_pin_and_no_reference_override(self):
        with self.assertRaises(scene.MenuSceneSpriteError) as err:
            scene.required_scene_sprites(self.main)
        self.assertEqual(err.exception.code, 'unsupported_source')
        for kwargs in ({'header': self.main}, {'expected_source_sha256': '0' * 64}):
            with self.assertRaises(TypeError):
                scene.required_scene_sprites(self.main, **kwargs)

    def test_shared_elf_still_requires_pin(self):
        elf = Elf32(minimal_elf())
        with self.assertRaises(scene.MenuSceneSpriteError) as err:
            scene.required_scene_sprites(elf)
        self.assertEqual(err.exception.code, 'unsupported_source')

    def test_invalid_input_type_rejects_before_filesystem(self):
        with self.assertRaises(scene.MenuSceneSpriteError) as err:
            scene.required_scene_sprites(42)
        self.assertEqual(err.exception.code, 'invalid_source')

    def test_source_and_directory_symlinks_reject(self):
        alias = self.root / 'main-alias'
        alias.symlink_to(self.main)
        with self.assertRaises(PhysicsImageError):
            scene.required_scene_sprites(alias)
        directory = self.root / 'dir-alias'
        directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(PhysicsImageError):
            scene.required_scene_sprites(directory / 'main')

    def test_cancel_before_opening_missing_source(self):
        with self.assertRaises(ConversionCancelled):
            scene.required_scene_sprites(self.root / 'missing', lambda: True)

    def test_synthetic_path_wrapper_hashes_and_never_writes_source(self):
        before = self.main.read_bytes()
        digest = hashlib.sha256(before).hexdigest()
        with patch.object(scene, 'SOURCE_SHA256', digest), patch.object(scene, 'from_elf', return_value={'story_pre': [2], 'ten': [3]}):
            result = scene.required_scene_sprites(self.main)
        self.assertEqual(result['source_sha256_after'], digest)
        self.assertEqual(self.main.read_bytes(), before)

    def test_source_change_during_projection_rejects(self):
        digest = hashlib.sha256(self.main.read_bytes()).hexdigest()
        def mutate(_elf, _cancel=None):
            self.main.write_bytes(self.main.read_bytes() + b'\x00')
            return {'story_pre': [2], 'ten': [3]}
        with patch.object(scene, 'SOURCE_SHA256', digest), patch.object(scene, 'from_elf', side_effect=mutate), self.assertRaises(scene.MenuSceneSpriteError) as err:
            scene.required_scene_sprites(self.main)
        self.assertEqual(err.exception.code, 'source_changed')


@unittest.skipUnless(os.environ.get('WMMT_TEST_ORIGINAL_MAIN'), 'User-owned original main not selected')
class OriginalComparisonTests(unittest.TestCase):
    def test_real_projection_and_complete_optional_header_oracles(self):
        main = Path(os.environ['WMMT_TEST_ORIGINAL_MAIN'])
        before = hashlib.sha256(main.read_bytes()).hexdigest()
        result = scene.required_scene_sprites(main)
        self.assertEqual(len(result['story_pre']), 307)
        self.assertEqual(len(result['ten']), 89)
        self.assertEqual(len(result['story_rows']), 112)
        self.assertEqual(result['source_sha256'], before)
        self.assertEqual(result['source_sha256_after'], before)
        story_path = os.environ.get('WMMT_TEST_STORYPRE_ORACLE')
        if story_path:
            # Comparison-only, strictly after original generation.
            rows, digits, values = reference_story(Path(story_path).read_text())
            actual = [[r['episode'], r['picture'], r['title'], *r['cars'], *r['bg'], r['info']] for r in result['story_rows']]
            self.assertEqual(actual, rows)
            self.assertEqual(result['story_digits'], digits)
            self.assertEqual(result['story_pre'], values)
        ten_path = os.environ.get('WMMT_TEST_TENDB_ORACLE')
        if ten_path:
            header = Path(ten_path).read_text()
            block = header.split('TENDB_PRE[10][TENDB_LEVELS][4] = {', 1)[1].split('};', 1)[0]
            numbers = list(map(int, re.findall(r'\d+', block)))
            actual = [v for course in result['ten_pre'] for row in course for v in row]
            self.assertEqual(actual, numbers)
            levels = list(map(int, re.search(r'TENDB_PRE_LV\[TENDB_LEVELS\] = \{ ([^}]*) \}', header).group(1).split(',')))
            self.assertEqual(result['ten_levels'], levels)
            self.assertEqual(result['ten'], sorted(set(numbers + levels)))
        self.assertEqual(hashlib.sha256(main.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
