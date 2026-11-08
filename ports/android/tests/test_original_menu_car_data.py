"""Static menu-car decoder safety tests; optional original/ABI comparison.

Use WMMT_TEST_WORK_ROOT for all synthetic artifacts.  Real tests additionally
select WMMT_TEST_ORIGINAL_MAIN, WMMT_TEST_CAR_DIRECTORY, and optionally
WMMT_TEST_CARDB_ORACLE.  The oracle is opened only after production derivation.
No target code, constructor, Lua program, Unicorn, or old APK is executed.
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
from original_convert import menu_car_data as menu
from original_convert.physics_image import Elf32, PhysicsImageError, ConversionCancelled


class SyntheticReader:
    """Fixed synthetic byte regions: data decoding only, never a CPU emulator."""
    def __init__(self, *ranges):
        self.regions = [(base, bytearray(size)) for base, size in ranges]

    def put(self, address, data):
        for base, raw in self.regions:
            if base <= address and address + len(data) <= base + len(raw):
                raw[address - base:address - base + len(data)] = data
                return
        raise AssertionError('Synthetic write outside fixture')

    def code(self, address, size):
        for base, raw in self.regions:
            if base <= address and address + size <= base + len(raw):
                return bytes(raw[address - base:address - base + size])
        raise PhysicsImageError('invalid_elf', 'Synthetic unmapped address')

    read = code


def c7(address, value):
    return b'\xc7\x05' + struct.pack('<II', address, value)


def direct_join(address, target):
    return b'\xe9' + struct.pack('<i', target - address - 5)


def synthetic_model_switch():
    elf = SyntheticReader((menu.MODEL_FUNCTION[0], menu.MODEL_FUNCTION[1] - menu.MODEL_FUNCTION[0]), (0x940ED98, 247 * 4))
    shapes = {0x88DC0C8: b'\x55', 0x88DC0E7: b'\x89\xe5', 0x88DC0FD: b'\x8b\x45\x08',
              0x88DC132: b'\x3d\xf6\x00\x00\x00'}
    fields = [0, 0, 0, 123, 0, 456, 789, 3826, 0, 987, 0, 654]
    coordinate, record = menu.MODEL_FUNCTION[0], 0
    while coordinate < 0x88DC1CD:
        if coordinate in shapes:
            data = shapes[coordinate]
        else:
            slot = record % 12
            data = c7(menu.MODEL_BASE + slot * 4, fields[slot])
            record += 1
        elf.put(coordinate, data)
        coordinate += len(data)
    assert coordinate == 0x88DC1CD
    elf.put(0x88DC1CD, b'\x77\x07')
    elf.put(0x88DC1CF, b'\xff\x24\x85' + struct.pack('<I', 0x940ED98))
    elf.put(0x88DC316, b'\xc9\xb8' + struct.pack('<I', menu.MODEL_BASE) + b'\xc3')
    targets = []
    for index in range(247):
        address = 0x88DC400 + index * 16
        targets.append(address)
        elf.put(address, c7(menu.MODEL_BASE + 12, 1000 + index))
        elf.put(address + 10, direct_join(address + 10, 0x88DC316))
    elf.put(0x940ED98, struct.pack('<247I', *targets))
    return elf


def minimal_elf():
    payload = bytearray(52 + 32)
    code_offset = len(payload)
    payload += b'\x90\xc3'
    strings_offset = len(payload)
    strings = b'\0.shstrtab\0'
    payload += strings
    shoff = len(payload)
    payload += bytes(40) + struct.pack('<10I', 1, 3, 0, 0, strings_offset, len(strings), 0, 0, 1, 0)
    struct.pack_into('<16sHHIIIIIHHHHHH', payload, 0, b'\x7fELF\x01\x01\x01' + bytes(9), 2, 3, 1,
                     0x8048000, 52, shoff, 0, 52, 32, 1, 40, 2, 1)
    struct.pack_into('<8I', payload, 52, 1, code_offset, 0x8048000, 0x8048000, 2, 2, 5, 1)
    return bytes(payload)


def compare_cardb(test, result, header):
    """Comparison-only C initializer reader; never used by production code."""
    order = re.findall(r'"([^"]+)"', header.split('CARDB_PACKS[', 1)[1].split('};', 1)[0])
    test.assertEqual(result['pack_order'], order)
    expected = []
    for line in header.splitlines():
        if re.match(r'\s*\{ "', line):
            expected.append(json.loads(line.strip().rstrip(',').replace('{', '[').replace('}', ']')))
    actual = []
    for maker in result['makers']:
        for car in maker['cars']:
            colors = [[c['swatch'], c['text'], order.index(c['folder']), c['paint'], c['type'], c['gears']]
                      for c in car['colors']]
            actual.append([car['label'], car['logo'], car['drive'], car['speed'], car['bglogo'],
                           car['plate'], car['hp'], len(colors), colors])
    test.assertEqual(actual, expected)
    test.assertEqual(len(actual), 48)


class ConstantGraphTests(unittest.TestCase):
    def setUp(self):
        self.elf = SyntheticReader((0x1000, 0x200))

    def records(self, start=0x1000, **kwargs):
        return menu._constant_records(self.elf, start, function_range=kwargs.get('function_range', (0x1000, 0x1200)),
                   store_range=(0x2000, 0x2040), terminal=0x1180, cancel=kwargs.get('cancel'))

    def test_constant_assignment_join_and_override_are_data(self):
        self.elf.put(0x1000, c7(0x2000, 7) + direct_join(0x100A, 0x1100))
        self.elf.put(0x1100, c7(0x2000, 9) + c7(0x2004, 11) + direct_join(0x1114, 0x1180))
        self.assertEqual(dict(self.records()), {0x2000: 9, 0x2004: 11})

    def test_no_cpu_execution_semantics_are_accepted(self):
        for data in (b'\xe8' + bytes(4), b'\xff\xe0', b'\x75\x00', b'\x89\x00', b'\x90'):
            self.elf.put(0x1000, data)
            with self.subTest(data=data), self.assertRaises(menu.MenuCarDataError):
                self.records()

    def test_cycles_and_out_of_function_edges_reject(self):
        for target in (0x1000, 0x1300):
            self.elf.put(0x1000, direct_join(0x1000, target))
            with self.assertRaises(menu.MenuCarDataError):
                self.records()

    def test_records_cannot_escape_result_struct(self):
        for target in (0x1FFC, 0x2040, 0x2001):
            self.elf.put(0x1000, c7(target, 1))
            with self.assertRaises(menu.MenuCarDataError):
                self.records()

    def test_entire_encoding_must_fit_function_bounds(self):
        self.elf.put(0x1000, c7(0x2000, 1))
        with self.assertRaises(menu.MenuCarDataError):
            self.records(function_range=(0x1000, 0x1009))
        self.elf.put(0x1000, direct_join(0x1000, 0x1180))
        with self.assertRaises(menu.MenuCarDataError):
            self.records(function_range=(0x1000, 0x1004))

    def test_bounded_graph_can_cancel(self):
        with self.assertRaises(ConversionCancelled):
            self.records(cancel=lambda: True)


class ModelAndMakerTests(unittest.TestCase):
    def test_all_247_synthetic_case_records(self):
        result, provenance = menu._decode_models(synthetic_model_switch())
        self.assertEqual(len(result), 247)
        self.assertEqual(result[0][3], 1000)
        self.assertEqual(result[246][3], 1246)
        self.assertTrue(all(row[7] == 3826 and row[5] == 456 for row in result))
        self.assertEqual(provenance['model_case_count'], 247)

    def test_duplicate_dispatch_case_identity_rejects(self):
        elf = synthetic_model_switch()
        elf.put(0x940ED98 + 4, elf.read(0x940ED98, 4))
        with self.assertRaises(menu.MenuCarDataError):
            menu._decode_models(elf)

    def test_model_unknown_opcode_and_wrong_return_pointer_reject(self):
        elf = synthetic_model_switch()
        elf.put(0x88DC400, b'\xe8')
        with self.assertRaises(menu.MenuCarDataError):
            menu._decode_models(elf)
        elf = synthetic_model_switch()
        elf.put(0x88DC318, struct.pack('<I', menu.MODEL_BASE + 4))
        with self.assertRaises(menu.MenuCarDataError):
            menu._decode_models(elf)

    def test_model_gear_sprite_is_not_guessed(self):
        elf = synthetic_model_switch()
        # Override a case's gear field with an unsupported original sprite code.
        elf.put(0x88DC400, c7(menu.MODEL_BASE + 7 * 4, 123))
        with self.assertRaises(menu.MenuCarDataError):
            menu._decode_models(elf)

    def test_maker_record_count_padding_and_identity(self):
        fields = {menu.MAKER_BASE: 2}
        fields.update({menu.MAKER_BASE + i * 4: (i if i <= 2 else 0xFFFFFFFF) for i in range(1, 13)})
        self.assertEqual(menu._maker_values(fields), [1, 2])
        for address, value in ((menu.MAKER_BASE, 13), (menu.MAKER_BASE + 12, 3), (menu.MAKER_BASE + 8, 1)):
            changed = dict(fields)
            changed[address] = value
            with self.assertRaises(menu.MenuCarDataError):
                menu._maker_values(changed)

    def test_public_shared_elf_helpers_reject_wrong_pin(self):
        elf = Elf32(minimal_elf())
        for function in (menu.decode_car_model_data, menu.decode_maker_lists):
            with self.assertRaises(menu.MenuCarDataError) as error:
                function(elf)
            self.assertEqual(error.exception.code, 'unsupported_source')
        with self.assertRaises(menu.MenuCarDataError):
            menu.from_elf(elf, '/unopened/source')

    def test_model_decode_cancellation(self):
        with self.assertRaises(ConversionCancelled):
            menu._decode_models(synthetic_model_switch(), lambda: True)


class SourceOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='menu-car-test-', dir=os.environ.get('WMMT_TEST_WORK_ROOT'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.main = self.root / 'main'
        self.main.write_bytes(minimal_elf())
        self.output = self.root / 'cars.json'

    def synthetic_io(self, **kwargs):
        with ExitStack() as stack:
            stack.enter_context(patch.object(menu, 'SOURCE_SHA256', hashlib.sha256(self.main.read_bytes()).hexdigest()))
            stack.enter_context(patch.object(menu, 'from_elf', return_value={'makers': [], 'texts': [], 'packs': {}, 'pack_order': []}))
            return menu.write_menu_car_data(self.main, self.root, self.output, **kwargs)

    def test_unknown_source_pin_rejected_without_output(self):
        with self.assertRaises(menu.MenuCarDataError) as error:
            menu.write_menu_car_data(self.main, self.root, self.output)
        self.assertEqual(error.exception.code, 'unsupported_source')
        self.assertFalse(self.output.exists())

    def test_no_old_table_or_source_pin_override_api(self):
        for kwargs in ({'cars_json': self.main}, {'cardb_header': self.main}, {'expected_source_sha256': '0' * 64}):
            with self.assertRaises(TypeError):
                menu.build_menu_car_data(self.main, self.root, **kwargs)

    def test_invalid_elf_does_not_create_output(self):
        self.main.write_bytes(b'broken ELF')
        with self.assertRaises(PhysicsImageError):
            self.synthetic_io()
        self.assertFalse(self.output.exists())

    def test_existing_and_broken_symlink_outputs_are_not_overwritten(self):
        self.output.write_bytes(b'preserve synthetic existing result')
        with self.assertRaises(menu.MenuCarDataError) as error:
            self.synthetic_io()
        self.assertEqual(error.exception.code, 'output_exists')
        self.assertEqual(self.output.read_bytes(), b'preserve synthetic existing result')
        link = self.root / 'broken.json'
        link.symlink_to(self.root / 'absent')
        with self.assertRaises(menu.MenuCarDataError):
            menu.write_menu_car_data(self.main, self.root, link)

    def test_source_and_output_directory_symlink_reject(self):
        source = self.root / 'source-link'
        source.symlink_to(self.main)
        with self.assertRaises(menu.MenuCarDataError):
            menu.write_menu_car_data(source, self.root, self.output)
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(PhysicsImageError):
            menu.write_menu_car_data(self.main, self.root, alias / 'new.json')

    def test_synthetic_output_roundtrip_and_pre_post_hash(self):
        before = self.main.read_bytes()
        result = self.synthetic_io()
        self.assertEqual(json.loads(self.output.read_text()), result)
        self.assertEqual(result['source_sha256_after'], hashlib.sha256(before).hexdigest())
        self.assertEqual(self.main.read_bytes(), before)

    def test_cancel_before_read_and_before_write(self):
        with self.assertRaises(ConversionCancelled):
            self.synthetic_io(cancel=lambda: True)
        self.assertFalse(self.output.exists())
        cancelled = False
        def progress(phase, done, total):
            nonlocal cancelled
            if phase == 'recheck_source':
                cancelled = True
        with self.assertRaises(ConversionCancelled):
            self.synthetic_io(cancel=lambda: cancelled, progress=progress)
        self.assertFalse(self.output.exists())

    def test_concurrent_output_is_retained(self):
        def progress(phase, done, total):
            if phase == 'recheck_source':
                self.output.write_bytes(b'concurrent synthetic result')
        with self.assertRaises(menu.MenuCarDataError) as error:
            self.synthetic_io(progress=progress)
        self.assertEqual(error.exception.code, 'output_exists')
        self.assertEqual(self.output.read_bytes(), b'concurrent synthetic result')


@unittest.skipUnless(os.environ.get('WMMT_TEST_ORIGINAL_MAIN') and os.environ.get('WMMT_TEST_CAR_DIRECTORY'),
                     'Real user-owned main/car source not selected')
class OriginalTests(unittest.TestCase):
    def test_complete_original_menu_and_optional_frozen_abi(self):
        main = Path(os.environ['WMMT_TEST_ORIGINAL_MAIN'])
        before = hashlib.sha256(main.read_bytes()).hexdigest()
        result = menu.build_menu_car_data(main, os.environ['WMMT_TEST_CAR_DIRECTORY'])
        self.assertEqual([len(m['cars']) for m in result['makers']], [3, 6, 7, 12, 6, 6, 8])
        self.assertEqual(len(result['texts']), 156)
        self.assertEqual(len(result['pack_order']), 55)
        self.assertEqual(list(result['packs']), result['pack_order'])
        self.assertEqual(sum(result['packs'].values()), 247)
        self.assertEqual([r['car'] for r in result['provenance']['hidden_selectors']], [44, 45, 36, 43, 52, 51, 50, 54])
        self.assertEqual(len(result['provenance']['lua_sources']), 55)
        for maker in result['makers']:
            for car in maker['cars']:
                for color in car['colors']:
                    self.assertEqual(color['name'], result['texts'][color['text'] - menu.TEXT_FIRST])
        oracle = os.environ.get('WMMT_TEST_CARDB_ORACLE')
        if oracle:
            compare_cardb(self, result, Path(oracle).read_text())
        self.assertEqual(hashlib.sha256(main.read_bytes()).hexdigest(), before)
        self.assertEqual(result['source_sha256'], result['source_sha256_after'])
        self.assertEqual(before, menu.SOURCE_SHA256)


if __name__ == '__main__':
    unittest.main(verbosity=2)
