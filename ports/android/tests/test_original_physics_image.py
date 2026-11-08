"""Synthetic safety tests; optional local original/golden checks never execute code.

Run with PYTHONDONTWRITEBYTECODE=1 and WMMT_TEST_WORK_ROOT pointing to an
existing scratch directory.  Optional WMMT_TEST_ORIGINAL_MAIN enables the real
main-only reconstruction; WMMT_TEST_GOLDEN_ZIP enables comparison-only golden
checking.  Neither path is accepted by the production conversion API as a
reference/result input.  Fixtures contain synthetic instructions/data only.
"""
from contextlib import ExitStack
import hashlib
import importlib.util
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

# Both repository invocation and a directly copied isolated test file work.
MODULE_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'original_convert' / 'physics_image.py'
if not MODULE_PATH.is_file():
    MODULE_PATH = Path(__file__).with_name('physics_image.py')
spec = importlib.util.spec_from_file_location('original_physics_image_under_test', MODULE_PATH)
physics = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = physics
spec.loader.exec_module(physics)


def synthetic_elf(loads=None):
    """Make a real, small ELF32 file with program + section tables from scratch."""
    if loads is None:
        loads = [(0x8048000, b'\x90' * 32, 64, 5)]
    names = b'\0.shstrtab\0'
    # Only a name table is needed by general reader tests; alloc bytes are PT_LOAD.
    phoff = 52
    payload = bytearray(phoff + 32 * len(loads))
    programs = []
    for address, data, memory_size, flags in loads:
        offset = len(payload)
        payload.extend(data)
        programs.append((1, offset, address, address, len(data), memory_size, flags, 1))
    names_offset = len(payload)
    payload.extend(names)
    shoff = len(payload)
    payload.extend(bytes(40))
    payload.extend(struct.pack('<10I', 1, 3, 0, 0, names_offset, len(names), 0, 0, 1, 0))
    ident = b'\x7fELF\x01\x01\x01' + bytes(9)
    struct.pack_into('<16sHHIIIIIHHHHHH', payload, 0, ident, 2, 3, 1, loads[0][0], phoff, shoff,
                     0, 52, 32, len(loads), 40, 2, 1)
    for index, row in enumerate(programs):
        struct.pack_into('<8I', payload, phoff + index * 32, *row)
    return bytes(payload)


def change(blob, offset, fmt, value):
    result = bytearray(blob)
    struct.pack_into(fmt, result, offset, value)
    return bytes(result)


class ElfStructureTests(unittest.TestCase):
    def test_synthetic_load_projection_and_bss_zeroes(self):
        elf = physics.Elf32(synthetic_elf())
        self.assertEqual(elf.read(0x8048000, 4), b'\x90' * 4)
        self.assertEqual(elf.image(0x8048000, 0x8048048), b'\x90' * 32 + bytes(40))
        with self.assertRaises(physics.PhysicsImageError):
            elf.read(0x8048020, 1)  # memory exists, but no file-backed byte

    def test_projection_retains_holes(self):
        elf = physics.Elf32(synthetic_elf([(0x8048000, b'A', 2, 5), (0x8048010, b'B', 4, 6)]))
        self.assertEqual(elf.image(0x8048000, 0x8048014), b'A' + bytes(15) + b'B' + bytes(3))

    def test_bad_header_shapes(self):
        good = synthetic_elf()
        for offset, fmt, value in ((0, '<I', 0), (4, '<B', 2), (5, '<B', 2), (6, '<B', 0),
                                   (7, '<B', 3), (16, '<H', 3), (18, '<H', 62), (20, '<I', 0),
                                   (36, '<I', 1), (40, '<H', 51), (42, '<H', 31),
                                   (44, '<H', 0), (46, '<H', 39), (48, '<H', 0), (50, '<H', 10)):
            with self.subTest(offset=offset), self.assertRaises(physics.PhysicsImageError):
                physics.Elf32(change(good, offset, fmt, value))

    def test_bad_header_ranges_and_truncation(self):
        good = synthetic_elf()
        for damaged in (good[:51], good[:-1], change(good, 28, '<I', 0xFFFFFFF0),
                        change(good, 32, '<I', 0xFFFFFFF0), change(good, 32, '<I', 52)):
            with self.assertRaises(physics.PhysicsImageError):
                physics.Elf32(damaged)

    def test_invalid_program_ranges_and_alignment(self):
        good = synthetic_elf()
        # filesz > memsz; overflowing VA; out-of-file bytes; bad congruence; flags.
        for offset, value in ((52 + 20, 1), (52 + 8, 0xFFFFFFF0), (52 + 4, 0xFFFFFF00),
                              (52 + 28, 3), (52 + 28, 4096), (52 + 24, 8)):
            with self.subTest(offset=offset, value=value), self.assertRaises(physics.PhysicsImageError):
                physics.Elf32(change(good, offset, '<I', value))

    def test_overlapping_load_memory_and_file_ranges(self):
        good = synthetic_elf([(0x8048000, b'A' * 8, 16, 5), (0x8048020, b'B' * 8, 16, 6)])
        for damaged in (change(good, 84 + 8, '<I', 0x8048008), change(good, 84 + 4, '<I', 116)):
            with self.assertRaises(physics.PhysicsImageError):
                physics.Elf32(damaged)

    def test_bad_string_table_and_section_bounds(self):
        good = synthetic_elf()
        shoff = struct.unpack_from('<I', good, 32)[0]
        for offset, value in ((shoff + 4, 1), (shoff + 40, 0xFFFFFF00),
                              (shoff + 44, 1), (shoff + 56, 0xFFFFFF00), (shoff + 64, 8)):
            with self.subTest(offset=offset), self.assertRaises(physics.PhysicsImageError):
                physics.Elf32(change(good, offset, '<I', value))

    def test_unmapped_reads_and_invalid_projection_fail_closed(self):
        elf = physics.Elf32(synthetic_elf())
        for address, size in ((0, 1), (0xFFFFFFFF, 4), (-1, 4), (0x8048000, -1)):
            with self.assertRaises(physics.PhysicsImageError):
                elf.read(address, size)
        with self.assertRaises(physics.PhysicsImageError):
            elf.image(1, 32 * 1024 * 1024)

    def test_cancel_during_bounded_elf_parse(self):
        count = 0
        def cancel():
            nonlocal count
            count += 1
            return count == 3
        with self.assertRaises(physics.ConversionCancelled):
            physics.Elf32(synthetic_elf(), cancel)


class InitializerTests(unittest.TestCase):
    def test_synthetic_copy_reads_source_not_embedded_result(self):
        code = b'\xa1' + struct.pack('<I', 0x943DA44) + b'\xa3' + struct.pack('<I', 0x98027E8)
        elf = physics.Elf32(synthetic_elf([(0x897E4DE, code, len(code), 5),
                                         (0x943DA44, b'\x19\x27\x53\x81', 4, 4)]))
        image = bytearray(physics.IMAGE_SIZE)
        physics._copy(elf, image, 0x897E4DE, 0x897E4E3, 0x943DA44, 0x98027E8)
        i = 0x98027E8 - physics.IMAGE_BASE
        self.assertEqual(image[i:i + 4], b'\x19\x27\x53\x81')
        with self.assertRaises(physics.PhysicsImageError):
            physics._copy(elf, image, 0x897E4DE, 0x897E4E3, 0x943DA48, 0x98027E8)

    def test_unknown_instruction_shape_is_rejected(self):
        elf = physics.Elf32(synthetic_elf())
        with self.assertRaises(physics.PhysicsImageError) as error:
            physics._shape(elf, 0x8048000, b'\xc7')
        self.assertEqual(error.exception.code, 'unsupported_initialization')

    def test_linx_decoder_rejects_unlisted_semantics(self):
        code = bytearray(0x300)
        code[0:5] = b'\xbe' + struct.pack('<I', 0x98033E0)
        elf = physics.Elf32(synthetic_elf([(0x89EBEE6, bytes(code), len(code), 5)]))
        with self.assertRaises(physics.PhysicsImageError) as error:
            physics._linx_stores(elf, None)
        self.assertEqual(error.exception.code, 'unsupported_initialization')

    def test_synthetic_floats_follow_f32_rounding_and_truncation(self):
        start = 0x89AD5F8
        code = bytearray(0x40)
        def put(va, value):
            code[va - start:va - start + len(value)] = value
        def word(value):
            return struct.pack('<I', value)
        put(start, b'\xc7\x44\x24\x04' + struct.pack('<f', 7.0))
        put(0x89AD600, b'\xc7\x04\x24' + struct.pack('<f', -3.0))
        put(0x89AD607, b'\xe8' + struct.pack('<i', 0x84223D8 - 0x89AD60C))
        put(0x89AD60C, b'\xd9\x5d\xfc\xf3\x0f\x10\x45\xfc')
        put(0x89AD614, b'\xf3\x0f\x59\x05' + word(0x9433E04))
        put(0x89AD61C, b'\xc7\x04\x24' + struct.pack('<f', 2.0))
        put(0x89AD623, b'\xf3\x0f\x2c\xc0')
        put(0x89AD627, b'\x66\xa3' + word(0x9803094))
        put(0x89AD62D, b'\xe8' + struct.pack('<i', 0x8422168 - 0x89AD632))
        put(0x89AD632, b'\xd9\x1d' + word(0x9803090))
        elf = physics.Elf32(synthetic_elf([(start, bytes(code), len(code), 5),
                                         (0x9433E04, struct.pack('<f', 11.25), 4, 4)]))
        image = bytearray(physics.IMAGE_SIZE)
        physics._float_initializers(elf, image)
        root = struct.unpack_from('<f', image, 0x9803090 - physics.IMAGE_BASE)[0]
        angle = struct.unpack_from('<H', image, 0x9803094 - physics.IMAGE_BASE)[0]
        self.assertEqual(root, physics._f32(math.sqrt(2.0)))
        self.assertEqual(angle, math.trunc(physics._f32(physics._f32(math.atan2(-3, 7)) * 11.25)) & 65535)


class OutputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='physics-image-', dir=os.environ.get('WMMT_TEST_WORK_ROOT'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'synthetic-main'
        self.source.write_bytes(synthetic_elf())
        self.output = self.root / 'phys.img'

    def run_synthetic_io(self, **kwargs):
        """Patch only test acceptance constants + derivation to isolate file I/O."""
        image = bytearray(physics.IMAGE_SIZE)
        with ExitStack() as stack:
            stack.enter_context(patch.object(physics, 'SOURCE_SHA256', hashlib.sha256(self.source.read_bytes()).hexdigest()))
            stack.enter_context(patch.object(physics, 'IMAGE_SHA256', hashlib.sha256(image).hexdigest()))
            stack.enter_context(patch.object(physics, '_build_image', return_value=(image, {})))
            return physics.convert_physics_image(self.source, self.output, **kwargs)

    def test_unknown_pin_rejected_before_output(self):
        with self.assertRaises(physics.PhysicsImageError) as error:
            physics.convert_physics_image(self.source, self.output)
        self.assertEqual(error.exception.code, 'unsupported_source')
        self.assertFalse(self.output.exists())

    def test_no_reference_or_pin_override_in_api(self):
        for kwargs in ({'golden_path': self.source}, {'expected_source_sha256': '0' * 64}):
            with self.assertRaises(TypeError):
                physics.convert_physics_image(self.source, self.output, **kwargs)

    def test_never_overwrites_existing_path_or_broken_symlink(self):
        self.output.write_bytes(b'preserve this synthetic result')
        with self.assertRaises(physics.PhysicsImageError) as error:
            physics.convert_physics_image(self.source, self.output)
        self.assertEqual(error.exception.code, 'output_exists')
        self.assertEqual(self.output.read_bytes(), b'preserve this synthetic result')
        broken = self.root / 'broken.img'
        broken.symlink_to(self.root / 'absent')
        with self.assertRaises(physics.PhysicsImageError) as error:
            physics.convert_physics_image(self.source, broken)
        self.assertEqual(error.exception.code, 'output_exists')

    def test_output_parent_must_exist_and_have_no_symlink_component(self):
        real = self.root / 'real'
        real.mkdir()
        link = self.root / 'link'
        link.symlink_to(real, target_is_directory=True)
        for output in (self.root / 'missing' / 'phys.img', link / 'phys.img'):
            with self.assertRaises(physics.PhysicsImageError) as error:
                physics.convert_physics_image(self.source, output)
            self.assertEqual(error.exception.code, 'io_error')
        self.assertEqual(list(real.iterdir()), [])

    def test_source_symlink_and_parent_traversal_are_rejected(self):
        link = self.root / 'source-link'
        link.symlink_to(self.source)
        with self.assertRaises(physics.PhysicsImageError):
            physics.convert_physics_image(link, self.output)
        with self.assertRaises(physics.PhysicsImageError) as error:
            physics.convert_physics_image(self.source, self.root / 'child' / '..' / 'phys.img')
        self.assertEqual(error.exception.code, 'invalid_path')

    def test_cancel_before_read_does_not_touch_output(self):
        with self.assertRaises(physics.ConversionCancelled):
            physics.convert_physics_image(self.root / 'absent', self.output, cancel=lambda: True)
        self.assertFalse(self.output.exists())

    def test_cancel_after_source_read_does_not_create_output(self):
        cancelled = False
        def progress(phase, done, total):
            nonlocal cancelled
            if phase == 'read_source':
                cancelled = True
        with self.assertRaises(physics.ConversionCancelled):
            physics.convert_physics_image(self.source, self.output, cancel=lambda: cancelled, progress=progress)
        self.assertFalse(self.output.exists())

    def test_cancel_before_output_write_keeps_output_absent(self):
        cancelled = False
        def progress(phase, done, total):
            nonlocal cancelled
            if phase == 'recheck_source':
                cancelled = True
        with self.assertRaises(physics.ConversionCancelled):
            self.run_synthetic_io(cancel=lambda: cancelled, progress=progress)
        self.assertFalse(self.output.exists())

    def test_cancel_after_creation_retains_only_new_partial(self):
        cancelled = False
        def progress(phase, done, total):
            nonlocal cancelled
            if phase == 'write_image':
                cancelled = True
        with self.assertRaises(physics.ConversionCancelled):
            self.run_synthetic_io(cancel=lambda: cancelled, progress=progress)
        self.assertEqual(self.output.stat().st_size, 1024 * 1024)

    def test_synthetic_io_complete_source_hash_and_progress(self):
        source_before = self.source.read_bytes()
        calls = []
        result = self.run_synthetic_io(progress=lambda *args: calls.append(args))
        self.assertEqual(result['source_sha256'], result['source_sha256_after'])
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(self.output.stat().st_size, physics.IMAGE_SIZE)
        self.assertTrue(all(isinstance(a[0], str) and isinstance(a[1], int) and isinstance(a[2], int) for a in calls))

    def test_concurrent_output_creation_is_not_overwritten(self):
        def progress(phase, done, total):
            if phase == 'recheck_source':
                self.output.write_bytes(b'concurrent result')
        with self.assertRaises(physics.PhysicsImageError) as error:
            self.run_synthetic_io(progress=progress)
        self.assertEqual(error.exception.code, 'output_exists')
        self.assertEqual(self.output.read_bytes(), b'concurrent result')

    def test_source_mutation_between_hashes_is_rejected(self):
        def progress(phase, done, total):
            if phase == 'read_source':
                with self.source.open('ab') as stream:
                    stream.write(b'x')
        with self.assertRaises(physics.PhysicsImageError) as error:
            self.run_synthetic_io(progress=progress)
        self.assertEqual(error.exception.code, 'source_changed')
        self.assertFalse(self.output.exists())

    def test_wrong_derived_digest_is_never_written(self):
        with patch.object(physics, 'SOURCE_SHA256', hashlib.sha256(self.source.read_bytes()).hexdigest()), \
             patch.object(physics, '_build_image', return_value=(bytearray(physics.IMAGE_SIZE), {})):
            with self.assertRaises(physics.PhysicsImageError) as error:
                physics.convert_physics_image(self.source, self.output)
        self.assertEqual(error.exception.code, 'image_mismatch')
        self.assertFalse(self.output.exists())


@unittest.skipUnless(os.environ.get('WMMT_TEST_ORIGINAL_MAIN'), 'Local user-owned main not selected')
class RealOriginalTests(unittest.TestCase):
    def test_main_only_conversion_then_optional_comparison(self):
        main = Path(os.environ['WMMT_TEST_ORIGINAL_MAIN'])
        before = hashlib.sha256(main.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix='physics-real-', dir=os.environ.get('WMMT_TEST_WORK_ROOT')) as tmp:
            out = Path(tmp) / 'phys.img'
            # This call has only main and a new output path: no reference bytes.
            result = physics.convert_physics_image(main, out)
            self.assertEqual(result['image_sha256'], physics.IMAGE_SHA256)
            self.assertEqual(out.stat().st_size, 6588744)
            self.assertEqual(result['steps']['import_slots'], 484)
            golden_path = os.environ.get('WMMT_TEST_GOLDEN_ZIP')
            if golden_path:
                # Open golden strictly AFTER main-only derivation has completed.
                with zipfile.ZipFile(golden_path) as archive:
                    matches = [name for name in archive.namelist() if name.rsplit('/', 1)[-1] == 'phys.img']
                    self.assertEqual(len(matches), 1)
                    info = archive.getinfo(matches[0])
                    self.assertEqual(info.file_size, 6588744)
                    golden = archive.read(matches[0])
                self.assertEqual(hashlib.sha256(golden).hexdigest(), physics.IMAGE_SHA256)
                self.assertEqual(out.read_bytes(), golden)
        self.assertEqual(hashlib.sha256(main.read_bytes()).hexdigest(), before)
        self.assertEqual(before, physics.SOURCE_SHA256)


if __name__ == '__main__':
    unittest.main(verbosity=2)
