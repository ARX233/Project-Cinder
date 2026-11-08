"""Pure-static scene sprite projections from the fixed original main ELF.

No emulator, original instruction execution, generated JSON, or historical C
header is used.  Reviewed instruction encodings bind each table/stride/field to
its original getter.  The getters' small index formulas are expressed directly
as finite Python data projections, never as a CPU/instruction interpreter.

story_pre matches menupack's legacy _storypre(): all picture/title/car/bg/info
and episode-digit IDs > 1.  WA is returned separately as story_wa.  ten is only
the dynamic TEN pre/level table union; the caller retains its other explicitly
authored TEN UI sprites.
"""
from __future__ import annotations

import hashlib
import os
import struct

from .physics_image import Elf32, SOURCE_SHA256, PhysicsImageError, ConversionCancelled, _check, _parent_fd, _read_source

ALGORITHM = '3dxplus-static-menu-scene-sprites-v1'
MAX_STORY_SELECTS = 200


class MenuSceneSpriteError(PhysicsImageError):
    pass


def _need(ok, message, code='unsupported_menu_scene_sprites'):
    if not ok:
        raise MenuSceneSpriteError(code, message)


def _shape(elf, address, prefix):
    _need(elf.code(address, len(prefix)) == prefix, 'Unsupported scene getter encoding at ' + hex(address))


def _operand(elf, address, prefix, width=4):
    _shape(elf, address, prefix)
    return int.from_bytes(elf.code(address + len(prefix), width), 'little')


# Instruction encodings only, not serialized original table/output bytes.
# These bind the algebraic projection to the reviewed lookup operations.
SHAPES = (
 (0x857CED4, b'\x55\x89\xe5\x8b\x45\x08\x8b\x00'),
 (0x857CEDF, b'\x7e\x0e'), (0x857CEEC, b'\x0f\x45\xc2\xc9\xc3'),
 (0x857DA5B, b'\x83\xfb\x03\x0f\x4d\xd8'),
 (0x857DA7E, b'\x8d\x85\x94\xfe\xff\xff'),
 (0x857DA98, b'\x8b\x84\x9d\x94\xfe\xff\xff'),
 (0x8835625, b'\xb8\x1f\x85\xeb\x51'),
 (0x8835643, b'\xf7\xe9\x89\xc8\xc1\xf8\x1f\xc1\xfa\x05\x29\xc2\x89\xd0\xc1\xe0\x04\x8d\x04\x90\x89\xca\x8d\x04\x80\x29\xc2'),
 (0x883565E, b'\x85\xdb\x7e\x18'), (0x883567A, b'\x89\xd0\xc1\xe0\x04'),
 (0x8835697, b'\x89\x37\x89\x5f\x0c\x89\x47\x08\x89\x4f\x04'),
 (0x8633553, b'\xc9\xb8\x01\x00\x00\x00\xc3'),
 (0x8633377, b'\x31\xdb\x89\xd8\x5b\xc9\xc3'),
 (0x863338D, b'\xc1\xe0\x04'), (0x8633398, b'\xc1\xe0\x04'),
 (0x86333AA, b'\xc1\xe0\x04'),
 (0x88A8892, b'\x8d\x04\xbd\x00\x00\x00\x00\xc1\xe3\x04\x29\xc3\x29\xfb\x01\xf3\xc1\xe3\x04'),
)


# name, instruction coordinate, opcode prefix, immediate/operand byte count,
# expected reviewed geometry.  These values are ABI bounds/addresses, not IDs.
OPERANDS = (
 ('story_table', 0x857DA70, b'\x05', 4, 0x973A5C0),
 ('story_stride', 0x857DA64, b'\x69\x00', 4, 0x158),
 ('story_copy_bytes', 0x857DA53, b'\xc7\x44\x24\x08', 4, 0x158),
 ('story_car_last_slot', 0x857DA4E, b'\xb8', 4, 2),
 ('ramp_story_table', 0x857D06C, b'\x05', 4, 0x973A5C0),
 ('ramp_story_stride', 0x857D066, b'\x69\x00', 4, 0x158),
 ('ramp_stack_base', 0x857D07A, b'\x8d\x85', 4, 0xFFFFFEA4),
 ('ramp_stack_field', 0x857D094, b'\x8b\x85', 4, 0xFFFFFEB0),
 ('loop_last_initial', 0x857CEDC, b'\x83\xf8', 1, 99),
 ('loop_subtract_imm8', 0x857CEE1, b'\x8d\x50', 1, 156),
 ('loop_special_select', 0x857CEE4, b'\x83\xf8', 1, 110),
 ('loop_special_value', 0x857CEE7, b'\xb8', 4, 9),
 ('story_image_table', 0x8835685, b'\x8b\xb0', 4, 0x93FC920),
 ('story_picture_table', 0x8835691, b'\x8b\x80', 4, 0x93FC928),
 ('story_title_table', 0x883567F, b'\x8b\x98', 4, 0x93FC92C),
 ('car_image_table', 0x86334C8, b'\x39\x0c\xc5', 4, 0x93DD8C0),
 ('car_image_result', 0x863355A, b'\x8b\x04\xc5', 4, 0x93DD8C4),
 ('car_image_count', 0x863354E, b'\x83\xf8', 1, 61),
 ('ramp_table', 0x8633321, b'\xba', 4, 0x93DDC00),
 ('ramp_stride', 0x8633332, b'\x83\xc2', 1, 16),
 ('ramp_count', 0x8633372, b'\x83\xfb', 1, 24),
 ('ramp_day', 0x8633390, b'\x8b\x80', 4, 0x93DDC04),
 ('ramp_night', 0x863339B, b'\x8b\x80', 4, 0x93DDC08),
 ('ramp_info', 0x86333AD, b'\x8b\x80', 4, 0x93DDC0C),
 ('story_digit_table', 0x883C31A, b'\x8b\x04\x9d', 4, 0x93FD3E0),
 ('story_last_digit', 0x883C2F6, b'\xc7\x85\x84\xfe\xff\xff', 4, 9),
 ('story_wa', 0x883C3DC, b'\xc7\x44\x9d\xb4', 4, 0xDB0),
 ('ten_pre_table', 0x88A8822, b'\xc7\x44\x24\x04', 4, 0x940D420),
 ('ten_pre_bytes', 0x88A881A, b'\xc7\x44\x24\x08', 4, 0x6E0),
 ('ten_last_level', 0x88A887F, b'\xb8', 4, 10),
 ('ten_level_table', 0x88A88FA, b'\x8b\x04\xb5', 4, 0x940D3E0),
 ('ten_bg_stack', 0x88A88A5, b'\x8b\x84\x2b', 4, 0xFFFFF908),
 ('ten_course_stack', 0x88A88B8, b'\x8b\x84\x2b', 4, 0xFFFFF90C),
 ('ten_time_stack', 0x88A88DC, b'\x8b\x84\x2b', 4, 0xFFFFF910),
 ('ten_ramp_stack', 0x88A891B, b'\x8b\x84\x2b', 4, 0xFFFFF914),
)


def _geometry(elf, cancel=None):
    for address, encoding in SHAPES:
        _check(cancel)
        _shape(elf, address, encoding)
    result = {}
    for name, address, prefix, width, expected in OPERANDS:
        _check(cancel)
        value = _operand(elf, address, prefix, width)
        _need(value == expected, 'Unknown scene table geometry: ' + name)
        result[name] = value
    _need(result['ramp_stack_field'] - result['ramp_stack_base'] == 12 and
          result['car_image_result'] - result['car_image_table'] == 4 and
          result['story_picture_table'] - result['story_image_table'] == 8 and
          result['story_title_table'] - result['story_image_table'] == 12,
          'Unexpected projected record fields')
    result['story_period'] = 256 - result['loop_subtract_imm8']
    _need(result['story_period'] == result['loop_last_initial'] + 1, 'Unknown story loop period')
    result['story_digit_count'] = result['story_last_digit'] + 1
    result['ten_levels'] = result['ten_last_level'] + 1
    result['ten_stride'] = result['ten_course_stack'] - result['ten_bg_stack']
    _need(result['ten_stride'] == 4 and
          result['ten_time_stack'] - result['ten_bg_stack'] == 8 and
          result['ten_ramp_stack'] - result['ten_bg_stack'] == 12,
          'Unknown TEN record layout')
    result['ten_courses'] = result['ten_pre_bytes'] // (result['ten_levels'] * 16)
    _need(result['ten_courses'] == 10 and result['ten_pre_bytes'] == result['ten_courses'] * result['ten_levels'] * 16,
          'Unknown TEN course/level dimensions')
    return result


def _sprite(value):
    _need(type(value) is int and 1 <= value <= 65535, 'Invalid original scene sprite identity')
    return value


def _in_loop(select, geometry):
    if select <= geometry['loop_last_initial']:
        return select
    if select == geometry['loop_special_select']:
        return geometry['loop_special_value']
    return select - geometry['story_period']


def _story_rows(elf, geometry, cancel=None):
    car_images = {}
    for index in range(geometry['car_image_count']):
        _check(cancel)
        model, sprite = struct.unpack('<2I', elf.read(geometry['car_image_table'] + index * 8, 8))
        car_images.setdefault(model, _sprite(sprite))
    ramps = []
    for index in range(geometry['ramp_count']):
        _check(cancel)
        ramp, day, night, info = struct.unpack('<4I', elf.read(geometry['ramp_table'] + index * 16, 16))
        ramps.append((ramp, _sprite(day), _sprite(night), _sprite(info)))
    ramp_indices = {}
    for index, row in enumerate(ramps):
        ramp_indices.setdefault(row[0], index)
    rows = []
    for select in range(MAX_STORY_SELECTS):
        _check(cancel)
        at = geometry['story_table'] + select * geometry['story_stride']
        first = int.from_bytes(elf.read(at, 4), 'little')
        # Existing port scene-select enumeration contract; require its observed
        # 112 rows at the public boundary rather than accepting partial input.
        if not 0 < first < 400:
            break
        model0, model1, model2, ramp = struct.unpack('<4I', elf.read(at, 16))
        inloop = _in_loop(select, geometry)
        _need(0 <= inloop < geometry['story_period'], 'Story select is outside the clear-loop-zero lane')
        picture, title = struct.unpack('<2I', elf.read(geometry['story_picture_table'] + (inloop % geometry['story_period']) * 16, 8))
        ramp_row = ramps[ramp_indices.get(ramp, 0)]
        rows.append({'select': select, 'episode': inloop + 1, 'picture': _sprite(picture), 'title': _sprite(title),
                     'cars': [car_images.get(model, 1) for model in (model0, model1, model2)],
                     'bg': list(ramp_row[1:3]), 'info': ramp_row[3]})
    else:
        raise MenuSceneSpriteError('unsupported_menu_scene_sprites', 'Story select sentinel missing within bounded table')
    digits = [_sprite(v) for v in struct.unpack('<' + 'I' * geometry['story_digit_count'],
                elf.read(geometry['story_digit_table'], geometry['story_digit_count'] * 4))]
    return rows, digits


def _ten_rows(elf, geometry, cancel=None):
    pre = []
    for course in range(geometry['ten_courses']):
        rows = []
        for level in range(geometry['ten_levels']):
            _check(cancel)
            offset = (course * geometry['ten_levels'] + level) * 16
            row = struct.unpack('<4I', elf.read(geometry['ten_pre_table'] + offset, 16))
            rows.append([_sprite(value) for value in row])
        pre.append(rows)
    levels = [_sprite(v) for v in struct.unpack('<' + 'I' * geometry['ten_levels'],
               elf.read(geometry['ten_level_table'], geometry['ten_levels'] * 4))]
    return pre, levels


def _project(elf, cancel=None):
    geometry = _geometry(elf, cancel)
    rows, digits = _story_rows(elf, geometry, cancel)
    _need(len(rows) == 112, 'Original story scene coverage must contain all 112 selects')
    pre, levels = _ten_rows(elf, geometry, cancel)
    story_ids = set(digits)
    for row in rows:
        story_ids.update([row['picture'], row['title'], *row['cars'], *row['bg'], row['info']])
    ten_ids = set(levels)
    for course in pre:
        for row in course:
            ten_ids.update(row)
    _check(cancel)
    return {'story_pre': sorted(value for value in story_ids if value > 1),
            'ten': sorted(value for value in ten_ids if value > 1),
            'story_wa': geometry['story_wa'], 'story_rows': rows, 'story_digits': digits,
            'ten_pre': pre, 'ten_levels': levels, 'source_sha256': SOURCE_SHA256, 'algorithm': ALGORITHM,
            'provenance': {'story_select_table': hex(geometry['story_table']), 'story_stride': geometry['story_stride'],
              'story_image_table': hex(geometry['story_image_table']), 'clear_loop_projection': 0,
              'story_select_count': len(rows), 'car_image_table': hex(geometry['car_image_table']),
              'car_image_count': geometry['car_image_count'], 'ramp_image_table': hex(geometry['ramp_table']),
              'ramp_image_count': geometry['ramp_count'], 'story_digit_table': hex(geometry['story_digit_table']),
              'ten_pre_table': hex(geometry['ten_pre_table']), 'ten_level_table': hex(geometry['ten_level_table']),
              'ten_dimensions': [geometry['ten_courses'], geometry['ten_levels'], 4],
              'opcode_shape_count': len(SHAPES), 'operand_shape_count': len(OPERANDS),
              'scope': 'story_pre excludes separately-returned WA; ten excludes caller-authored constant TEN sprites'}}


def from_elf(elf, cancel=None):
    """Shared immutable ELF API, pinned before any projection reads."""
    _check(cancel)
    _need(isinstance(elf, Elf32), 'A strict Elf32 reader is required', 'invalid_source')
    _need(hashlib.sha256(elf.data).hexdigest() == SOURCE_SHA256, 'Unsupported main SHA-256', 'unsupported_source')
    return _project(elf, cancel)


def required_scene_sprites(main_or_elf, cancel=None):
    """Return source-derived story_pre/TEN sets; accept a path or shared Elf32."""
    if isinstance(main_or_elf, Elf32):
        return from_elf(main_or_elf, cancel)
    _check(cancel)
    _need(isinstance(main_or_elf, (str, os.PathLike)), 'A main path or Elf32 reader is required', 'invalid_source')
    try:
        with _parent_fd(main_or_elf) as (directory, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                raw, before = _read_source(fd, cancel, None, retain=True)
                _need(before == SOURCE_SHA256, 'Unsupported main SHA-256', 'unsupported_source')
                result = from_elf(Elf32(raw, cancel), cancel)
                _, after = _read_source(fd, cancel, None, retain=False)
                _need(after == before, 'Main changed during scene projection', 'source_changed')
                held, named = os.fstat(fd), os.stat(name, dir_fd=directory, follow_symlinks=False)
                _need((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino), 'Main path was replaced', 'source_changed')
            finally:
                os.close(fd)
        result['source_sha256_after'] = after
        return result
    except OSError as exc:
        raise MenuSceneSpriteError('io_error', 'Cannot read original scene source: ' + str(exc)) from exc
