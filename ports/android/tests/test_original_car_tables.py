"""Synthetic-only by default; optional original+frozen-ABI comparison is read-only.

Set WMMT_TEST_WORK_ROOT to an external scratch directory.  Set
WMMT_TEST_ORIGINAL_MAIN and WMMT_TEST_CAR_DIRECTORY for real source coverage;
WMMT_TEST_CARDB_ORACLE optionally compares only AFTER production derivation.
No test executes main/constructors/Unicorn or uses an old table as output.
"""
from contextlib import contextmanager
import hashlib
import importlib.util
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
if (REPO / 'tools' / 'original_convert').is_dir():
    sys.path.insert(0, str(REPO / 'tools'))
else:
    # Standalone external staging tests can select the repository tools explicitly.
    sys.path.insert(0, os.environ['WMMT_TEST_TOOLS'])
from original_convert.physics_image import Elf32, PhysicsImageError, ConversionCancelled
MODULE = REPO / 'tools' / 'original_convert' / 'car_tables.py'
if not MODULE.is_file():
    MODULE = Path(__file__).with_name('car_tables.py')
spec = importlib.util.spec_from_file_location('original_convert.car_tables', MODULE)
tables = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tables
spec.loader.exec_module(tables)


def synthetic_elf(loads):
    out = bytearray(52 + len(loads) * 32)
    ph = []
    for va, data, flags in loads:
        off = len(out)
        out += data
        ph.append((1, off, va, va, len(data), len(data), flags, 1))
    names, noff = b'\0.shstrtab\0', len(out)
    out += names
    shoff = len(out)
    out += bytes(40) + struct.pack('<10I', 1, 3, 0, 0, noff, len(names), 0, 0, 1, 0)
    struct.pack_into('<16sHHIIIIIHHHHHH', out, 0, b'\x7fELF\x01\x01\x01' + bytes(9),
                     2, 3, 1, loads[0][0], 52, shoff, 0, 52, 32, len(loads), 40, 2, 1)
    for index, row in enumerate(ph):
        struct.pack_into('<8I', out, 52 + index * 32, *row)
    return bytes(out)


def synthetic_main():
    """Synthetic data at reviewed coordinates, with zero original game bytes."""
    code_base, data_base = 0x893D000, 0x9417000
    code, data = bytearray(0x3000), bytearray(0x16000)
    def put(va, value):
        target, base = (code, code_base) if va < data_base else (data, data_base)
        target[va - base:va - base + len(value)] = value
    def u32(v):
        return struct.pack('<I', v)
    next_string = 0x9421000
    def string(s):
        nonlocal next_string
        at = next_string
        encoded = s.encode() + b'\0'
        put(at, encoded)
        next_string += len(encoded)
        return at
    put(0x893D76D, b'\x8b\x04\xc5' + u32(0x9417720))
    put(0x893D764, b'\x83\xf8\x38')
    put(0x893D704, b'\x39\x0c\xc5' + u32(0x9417724))
    put(0x893DF90, b'\x8d\x84\xb8' + u32(0x9419EA0))
    put(0x893DFA6, b'\x83\xff\x79')
    put(0x893DF8D, b'\xc1\xe0\x04')
    put(0x893DF97, b'\x3b\x50\x04\x7c\x09\x3b\x50\x08')
    put(0x893DE40, b'\xc1\xe0\x04\x8b\x84\xb8')
    put(0x893DE12, b'\x8b\x42\x04\x3b\x42\x0c')
    put(0x893DE1E, b'\x8b\x4a\x08\x3b\x4a\x10')
    for fn, offset in ((0x893ED30, 8), (0x893F0B0, 28)):
        for va, prefix, value, width in ((fn + 1, b'\xba', 0x941A820, 4),
             (fn + 0x2A, b'\x8d\x9a', 180, 4), (fn + 0x11A, b'\x83\xff', 118, 1),
             (fn + 0x12D, b'\x39\xb0', 0x941A824, 4),
             (fn + 0x139, b'\x39\xb0', 0x941A850, 4),
             (fn + 0x17A, b'\x83\x3c\x95', 0x941A820 + offset, 4)):
            put(va, prefix + value.to_bytes(width, 'little'))
        put(fn + 0x181, b'\x01\x0f\x94\xc0')
        put(fn + 0x162, b'\x8d\x04\x8d\x00\x00\x00\x00\x89\xca\xc1\xe2\x04\x29\xc2\x31\xc0\x29\xca')
    for va, prefix, value, width in ((0x893F431, b'\xba', 0x941FB20, 4),
         (0x893F43D, b'\xbb', 0x941FB28, 4), (0x893F4C9, b'\x81\xfe', 288, 4),
         (0x893F472, b'\x83\xc2', 12, 1)):
        put(va, prefix + value.to_bytes(width, 'little'))
    put(0x893F448, b'\x3b\x3a')
    put(0x893F44C, b'\x8b\x45\x0c\x3b\x42\x04')
    put(0x893F4E0, b'\x8b\x03')
    for car in range(56):
        put(0x9417720 + car * 8, struct.pack('<2I', string(f'car_{car}'), car))
    ranges = [(0, 0, 0, 0, 1), (1, 0, 1, 0, 1)]
    ranges += [(car, car, car, car, car) for car in range(2, 56)]
    ranges += [(car, 100 + car - 56, 100 + car - 56, 100 + car - 56, 100 + car - 56) for car in range(56, 120)]
    ranges.append((1, 0, 1, 0, 1))
    assert len(ranges) == 121
    for i, row in enumerate(ranges):
        put(0x9419EA0 + i * 20, struct.pack('<5i', *row))
    for i in range(64):
        put(0x9419888 + i * 24, struct.pack('<6I', string(f'chara_{i}'), 100 + i, 0, 56 + i, 0, 0))
    for car in range(118):
        row = [car]
        for body in range(4):
            row += [body] + [1, 0, 1, 0, 1] + [0, 1, 0, 1, 0]
        put(0x941A820 + car * 180, struct.pack('<45i', *row))
    cases = [(car, body) for car in range(56) for body in range(4)] + [(car, 0) for car in range(56, 120)]
    for i, (car, body) in enumerate(cases):
        put(0x941FB20 + i * 12, struct.pack('<3I', car, body,
            string(tables.LAMP_PREFIX + f'synthetic_{car}_{body}.igb')))
    return synthetic_elf([(code_base, bytes(code), 5), (data_base, bytes(data), 4)])


def fake_lua(paints=1):
    rows = ','.join('{ page1=AbsPath .. "paint' + str(i) + '.tga" }' for i in range(paints))
    return 'AbsPath="data/car/synthetic/"\nBodyIGB={normal=AbsPath.."body.igb",aero_a=AbsPath.."a.igb"}\nBodyColorTexture={normal={' + rows + '}}\n'


class LuaDataTests(unittest.TestCase):
    def test_data_only_parse_utf8_comments_arrays_and_concat(self):
        env = tables._Lua('-- 日本語\n--[[block]]\na="x/" b={normal={{page1=a.."a.tga",n=-1.2e2}}, [2]=true}').parse()
        self.assertEqual(env['b']['normal'][0]['page1'], 'x/a.tga')
        self.assertEqual(env['b']['normal'][0]['n'], -120)
        self.assertIs(env['b'][2], True)

    def test_original_named_duplicate_fields_follow_last_value(self):
        self.assertEqual(tables._Lua('a={normal={1},normal={}}').parse()['a']['normal'], {})

    def test_strings_are_only_data(self):
        env = tables._Lua('a="os.execute(unsafe)"').parse()
        self.assertEqual(env['a'], 'os.execute(unsafe)')

    def test_reject_calls_executable_syntax_and_unknown_semantics(self):
        for text in ('os.execute("touch anything")', 'a=function() end', 'while true do end',
                     'a=unknown', 'a=1+2', 'a="x"..nil', 'a={ [true]=1 }', 'a={ [1]=2, 3 }'):
            with self.subTest(text=text), self.assertRaises(tables.CarTableError):
                tables._Lua(text).parse()

    def test_reject_truncation_and_nonfinite_numbers(self):
        for text in ('a={', 'a={b=}', 'a="bad', 'a=(1', 'a=1e999', '--[[ unclosed\na=1',
                     'a=' + '9' * 200, 'a={x=1 y=2}'):
            with self.subTest(text=text), self.assertRaises(tables.CarTableError):
                tables._Lua(text).parse()

    def test_depth_tokens_bytes_and_cancel_are_bounded(self):
        with self.assertRaises(tables.CarTableError):
            tables._Lua('a=' + '{' * 45 + '0' + '}' * 45).parse()
        with patch.object(tables, 'MAX_LUA_TOKENS', 4), self.assertRaises(tables.CarTableError):
            tables._Lua('a={1,2,3}').parse()
        with patch.object(tables, 'MAX_LUA_BYTES', 5), self.assertRaises(tables.CarTableError):
            tables._Lua('a="long"').parse()
        with self.assertRaises(ConversionCancelled):
            tables._Lua('a=1', lambda: True)

    def test_paint_count_needs_texture_records(self):
        self.assertEqual(tables._paint_count(tables._Lua(fake_lua(3)).parse()), 3)
        for obj in ({}, {'BodyColorTexture': {}}, {'BodyColorTexture': {'normal': [{}]}}):
            with self.assertRaises(tables.CarTableError):
                tables._paint_count(obj)


class StaticTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob = synthetic_main()

    def test_synthetic_full_static_tables(self):
        result = tables._decode_main(Elf32(self.blob))
        self.assertEqual(len(result['nicknames']), 56)
        self.assertEqual(len(result['character_models']), 64)
        self.assertEqual(len(result['brake_lamps']['cars']), 120)
        self.assertEqual(len(result['brake_lamps']['lamps']), 288)
        self.assertEqual(result['brake_lamps']['lamps']['0 0'], ['synthetic_0_0', 21, 10])
        self.assertEqual(result['brake_lamps']['lamps']['119 0'], ['synthetic_119_0', 0, 0])
        self.assertEqual(result['brake_lamps']['cars']['chara_0'], 56)

    def test_variant_first_match_and_base_false_lookup(self):
        rows = [(9, 4, 4, 2, 6), (8, 2, 6, 2, 6)]
        self.assertEqual(tables._model_car(rows, 4, True), 9)
        self.assertEqual(tables._model_car(rows, 4, False), 8)
        with self.assertRaises(tables.CarTableError):
            tables._model_car(rows, 100)

    def test_owners_deduplicate_ranges_and_resolve_missing_variant(self):
        decoded = tables._decode_main(Elf32(self.blob))
        names = {f'car_{i}': f'car_{i}' for i in range(1, 56)}
        owners = tables._pack_model_owners(decoded, names)
        self.assertEqual(owners['car_1'], [0, 1])
        self.assertEqual(len(owners), 55)
        self.assertEqual(owners['car_55'], [55])

    def test_missing_base_does_not_fallback_to_frozen_output(self):
        decoded = tables._decode_main(Elf32(self.blob))
        with self.assertRaises(tables.CarTableError):
            tables._pack_model_owners(decoded, {})

    def test_wing_masks_are_first_body_match_and_exact_one(self):
        row = [3] + [0, 1, 2, 0, 1, -1, 0, 1, 0, 1, 0] + [0] * 33
        self.assertEqual(tables._wing_mask(row, 0, 0), 9)
        self.assertEqual(tables._wing_mask(row, 0, 5), 10)
        self.assertEqual(tables._wing_mask(row, 2, 0), 0)

    def test_bad_instruction_shape_rejects(self):
        elf = Elf32(self.blob)
        with self.assertRaises(tables.CarTableError):
            tables._shape(elf, 0x893D76D, b'\xc7')

    def test_static_strings_must_be_bounded_and_valid_utf8(self):
        for data in (b'no terminator', b'\xff\x00'):
            elf = Elf32(synthetic_elf([(0x8048000, data, 5)]))
            with self.assertRaises(tables.CarTableError):
                tables._cstring(elf, 0x8048000)

    def test_corrupt_table_geometry_is_not_guessed(self):
        elf = Elf32(self.blob)
        seg = elf._segment(0x893F4CB, 4)
        damaged = bytearray(self.blob)
        struct.pack_into('<I', damaged, seg.offset + 0x893F4CB - seg.address, 10000)
        with self.assertRaises(tables.CarTableError):
            tables._decode_main(Elf32(bytes(damaged)))

    def test_cancel_static_table_loops(self):
        count = 0
        def cancel():
            nonlocal count
            count += 1
            return count > 15
        with self.assertRaises(ConversionCancelled):
            tables._decode_main(Elf32(self.blob), cancel)


class SourceAndOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='car-table-test-', dir=os.environ.get('WMMT_TEST_WORK_ROOT'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.main = self.root / 'main'
        self.main.write_bytes(synthetic_main())
        self.car = self.root / 'car'
        self.car.mkdir()
        for index in range(1, 56):
            folder = self.car / f'car_{index}'
            folder.mkdir()
            (folder / 'car.lua').write_text(fake_lua(2 if index == 1 else 1))
        self.output = self.root / 'tables.json'

    @contextmanager
    def accept_synthetic(self):
        with patch.object(tables, 'SOURCE_SHA256', hashlib.sha256(self.main.read_bytes()).hexdigest()):
            yield

    def test_main_pin_has_no_public_override(self):
        with self.assertRaises(tables.CarTableError) as err:
            tables.build_car_tables(self.main, self.car)
        self.assertEqual(err.exception.code, 'unsupported_source')
        with self.assertRaises(TypeError):
            tables.build_car_tables(self.main, self.car, expected_source_sha256='0' * 64)

    def test_malformed_elf_rejected_even_under_synthetic_pin(self):
        data = bytearray(self.main.read_bytes())
        data[0] = 0
        self.main.write_bytes(data)
        with self.accept_synthetic(), self.assertRaises(PhysicsImageError):
            tables.write_car_tables(self.main, self.car, self.output)
        self.assertFalse(self.output.exists())

    def test_synthetic_main_and_lua_integration(self):
        with self.accept_synthetic():
            result = tables.build_car_tables(self.main, self.car)
        self.assertEqual(result['packs']['car_1'], 2)
        self.assertEqual(len(result['packs']), 55)
        self.assertEqual(len(result['provenance']['lua_sources']), 55)
        self.assertEqual(result['source_sha256'], result['source_sha256_after'])
        self.assertEqual(result['provenance']['absent_variants'], ['car_0'])

    def test_paints_come_from_main_not_excess_lua_textures(self):
        (self.car / 'car_2' / 'car.lua').write_text(fake_lua(6))
        with self.accept_synthetic():
            result = tables.build_car_tables(self.main, self.car)
        self.assertEqual(result['packs']['car_2'], 1)

    def test_insufficient_lua_paints_rejects(self):
        (self.car / 'car_1' / 'car.lua').write_text(fake_lua(1))
        with self.accept_synthetic(), self.assertRaises(tables.CarTableError):
            tables.build_car_tables(self.main, self.car)

    def test_case_preserved_directory_names(self):
        # Create a complete separate synthetic tree with one actual-cased folder.
        root = self.root / 'case-car'
        root.mkdir()
        for i in range(1, 56):
            f = root / ('CAR_2' if i == 2 else f'car_{i}')
            f.mkdir()
            (f / 'car.lua').write_text(fake_lua(2 if i == 1 else 1))
        with self.accept_synthetic():
            result = tables.build_car_tables(self.main, root)
        self.assertIn('CAR_2', result['packs'])

    def test_reject_symlink_lua_and_directory_chain(self):
        other = self.root / 'other.lua'
        other.write_text(fake_lua())
        # Replace only a freshly-created synthetic fixture via a verified path.
        target = self.car / 'car_2' / 'car.lua'
        self.assertEqual(target.resolve(), self.root / 'car' / 'car_2' / 'car.lua')
        target.unlink()
        target.symlink_to(other)
        with self.accept_synthetic(), self.assertRaises(PhysicsImageError):
            tables.build_car_tables(self.main, self.car)
        alias = self.root / 'alias-car'
        alias.symlink_to(self.car, target_is_directory=True)
        with self.accept_synthetic(), self.assertRaises(PhysicsImageError):
            tables.build_car_tables(self.main, alias)

    def test_invalid_utf8_lua_rejects(self):
        (self.car / 'car_2' / 'car.lua').write_bytes(b'\xff')
        with self.accept_synthetic(), self.assertRaises(tables.CarTableError) as err:
            tables.build_car_tables(self.main, self.car)
        self.assertEqual(err.exception.code, 'invalid_lua')

    def test_output_is_exclusive_and_roundtrips(self):
        with self.accept_synthetic():
            result = tables.write_car_tables(self.main, self.car, self.output)
        self.assertEqual(json.loads(self.output.read_text()), result)
        before = self.output.read_bytes()
        with self.assertRaises(tables.CarTableError) as err:
            tables.write_car_tables(self.main, self.car, self.output)
        self.assertEqual(err.exception.code, 'output_exists')
        self.assertEqual(self.output.read_bytes(), before)

    def test_cancel_before_output_and_during_lua_progress(self):
        with self.assertRaises(ConversionCancelled):
            tables.write_car_tables(self.main, self.car, self.output, cancel=lambda: True)
        self.assertFalse(self.output.exists())
        cancelled = False
        def progress(phase, done, total):
            nonlocal cancelled
            if phase == 'car_lua_paints':
                cancelled = True
        with self.accept_synthetic(), self.assertRaises(ConversionCancelled):
            tables.write_car_tables(self.main, self.car, self.output, cancel=lambda: cancelled, progress=progress)
        self.assertFalse(self.output.exists())


@unittest.skipUnless(os.environ.get('WMMT_TEST_ORIGINAL_MAIN') and os.environ.get('WMMT_TEST_CAR_DIRECTORY'),
                     'Real original main/car inputs not selected')
class OriginalComparisonTests(unittest.TestCase):
    def test_original_support_fields_and_optional_frozen_abi_oracle(self):
        main = Path(os.environ['WMMT_TEST_ORIGINAL_MAIN'])
        before = hashlib.sha256(main.read_bytes()).hexdigest()
        result = tables.build_car_tables(main, os.environ['WMMT_TEST_CAR_DIRECTORY'])
        self.assertEqual(len(result['packs']), 55)
        self.assertEqual(sum(len(bs) for bs in result['bodies'].values()), 214)
        self.assertEqual(result['packs']['maz_GG3P_school'], 1)
        self.assertEqual(len(result['brake_lamps']['cars']), 120)
        self.assertEqual(len(result['brake_lamps']['lamps']), 288)
        self.assertEqual(result['brake_lamps']['lamps']['10 0'][1:], [31, 2])
        self.assertEqual(result['brake_lamps']['lamps']['7 3'][1:], [1, 31])
        oracle_path = os.environ.get('WMMT_TEST_CARDB_ORACLE')
        if oracle_path:
            # Comparison only: no production API accepts this header or parsed map.
            oracle = Path(oracle_path).read_text()
            names = re.findall(r'"([^"]+)"', oracle.split('CARDB_PACKS[', 1)[1].split('};', 1)[0])
            expected = {name: 0 for name in names}
            pattern = r'\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\}'
            for row in re.findall(pattern, oracle):
                _, _, pack, paint, _, _ = map(int, row)
                expected[names[pack]] = max(expected[names[pack]], paint + 1)
            self.assertEqual(result['packs'], expected)
        self.assertEqual(hashlib.sha256(main.read_bytes()).hexdigest(), before)
        self.assertEqual(before, tables.SOURCE_SHA256)


if __name__ == '__main__':
    unittest.main(verbosity=2)
