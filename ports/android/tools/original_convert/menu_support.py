"""Pinned, data-only support for the original 3DX+ 2D converters.

Importing this module reads no files. OriginalSupport is the explicit replacement
for menupack's import-time generated headers/JSON/text files. All game values
below are read from the selected main's PT_LOAD bytes, never from compiled port
tables or a previous conversion. Tiny instruction-shape checks extract operands;
there is no emulation, dynamic game import, code execution or general decoder.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
import re
import struct
from types import MappingProxyType

from .physics_image import Elf32, SOURCE_SHA256, _parent_fd, _read_source
from .source import check_cancel, source_path

ALGORITHM = '3dxplus-static-2d-support-v1'
SPRITE_TABLE, SPRITE_COUNT = 0x9551560, 0x1F9B
FONT_TABLE, FONT_COUNT = 0x930E4E0, 11
MAX_STRING = 4096
MAX_TEXT = 4096
MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024
MAX_IMAGE_EDGE = 4096
NAME = re.compile(r'[A-Za-z0-9_]+\Z')


class MenuConversionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def need(condition, message, code='invalid_2d'):
    if not condition:
        raise MenuConversionError(code, message)


def dimensions(width, height):
    need(type(width) is int and type(height) is int and
         0 < width <= MAX_IMAGE_EDGE and 0 < height <= MAX_IMAGE_EDGE and
         width * height <= MAX_PIXELS, '2D image dimensions exceed budget')
    return width, height


@dataclass(frozen=True)
class Sprite:
    path: str
    width: float
    height: float


@dataclass(frozen=True)
class MeterPart:
    sprite: int
    x: float
    y: float
    a0: float
    a1: float
    input: int
    additive: int = 0


class OriginalSupport:
    """Only construct through a pinned main factory. No generated support inputs.

    Resource bytes are supplied separately through a bounded ``read(name,
    max_bytes=..., cancel=...)`` callback, normally FileTreeSource.read. Support
    metadata alone is not a signed read-set, release signature, or Ready record.
    """
    def __init__(self, raw, *, cancel=None):
        need(isinstance(raw, bytes) and len(raw) <= 32 * 1024 * 1024,
             'Bounded immutable main bytes required', 'unsupported_source')
        need(hashlib.sha256(raw).hexdigest() == SOURCE_SHA256,
             'Unsupported main SHA-256', 'unsupported_source')
        self.elf = Elf32(raw, cancel)
        self.cancel = cancel
        names = {}
        for sid in range(SPRITE_COUNT):
            check_cancel(cancel)
            pointer = self.u32(SPRITE_TABLE + 44 * sid)
            if not pointer:
                continue
            path = self.cstr(pointer)
            if not path:
                continue
            # Arcade capture surfaces are not original assets and must never be opened.
            if sid in (2, 3):
                need(path == ('/tmp/joinshot.png' if sid == 2 else '/tmp/joinsync.png'),
                     'Unexpected runtime-only sprite path')
                continue
            source_path(path)
            need(path.startswith('data/sprite/'), 'Unexpected sprite resource path')
            width, height = struct.unpack('<2f', self.elf.read(SPRITE_TABLE + 44 * sid + 16, 8))
            need(all(math.isfinite(v) and 0 <= v <= MAX_IMAGE_EDGE for v in (width, height)),
                 'Nonfinite or excessive sprite table size')
            names[sid] = Sprite(path, width, height)
        self.sprites = MappingProxyType(names)

    @classmethod
    def from_main(cls, path, *, cancel=None, progress=None):
        with _parent_fd(path) as (directory, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                raw, digest = _read_source(fd, cancel, progress, retain=True)
                need(digest == SOURCE_SHA256, 'Unsupported main SHA-256', 'unsupported_source')
                return cls(raw, cancel=cancel)
            finally:
                os.close(fd)

    @classmethod
    def from_source(cls, source, *, cancel=None, progress=None):
        return cls(source.read('main', max_bytes=32 * 1024 * 1024,
                               cancel=cancel, progress=progress), cancel=cancel)

    def u32(self, address):
        return struct.unpack('<I', self.elf.read(address, 4))[0]

    def ints(self, address, count):
        need(0 <= count <= 16384, 'Static table count budget')
        return struct.unpack('<' + str(count) + 'I', self.elf.read(address, count * 4))

    def cstr(self, address, *, encoding='utf-8', limit=MAX_STRING):
        check_cancel(self.cancel)
        if address == 0:
            return ''
        segment = self.elf._segment(address, 1)
        raw = self.elf.read(address, min(limit, segment.address + segment.file_size - address))
        end = raw.find(b'\0')
        need(end >= 0, 'Unterminated static string')
        try:
            return raw[:end].decode(encoding, 'strict')
        except UnicodeError as exc:
            raise MenuConversionError('invalid_2d', 'Invalid static string encoding') from exc

    def wstr(self, address, *, limit=MAX_TEXT):
        if address == 0:
            return ''
        out = []
        for index in range(limit):
            check_cancel(self.cancel)
            value = self.u32(address + 4 * index)
            if not value:
                return ''.join(out)
            need(value <= 0xFFFF and not 0xD800 <= value <= 0xDFFF,
                 'Invalid BMP static wchar value')
            out.append(chr(value))
        raise MenuConversionError('invalid_2d', 'Wide string count budget')

    def shape(self, address, prefix):
        need(self.elf.code(address, len(prefix)) == prefix,
             'Unsupported 2D initializer shape at ' + hex(address), 'unsupported_2d_shape')

    def font(self, font):
        need(type(font) is int and 0 <= font < FONT_COUNT, 'Unknown sprite font')
        values = self.ints(FONT_TABLE + 36 * font, 9)
        nglyph, half, full, cell, cols, rows, cells, pages, glyph_map = values
        need(0 < nglyph <= 65536 and 0 < half <= full <= cell <= 256 and
             0 < cols <= 128 and 0 < rows <= 128 and 0 < cells <= 16384 and
             cells == cols * rows and pages > 0 and glyph_map > 0,
             'Unsupported sprite font table')
        return values

    def glyph(self, font, char):
        need(isinstance(char, str) and len(char) == 1 and ord(char) <= 0xFFFF and
             not 0xD800 <= ord(char) <= 0xDFFF, 'Sprite font accepts BMP scalars only')
        nglyph, half, full, cell, cols, rows, cells, pages, glyph_map = self.font(font)
        ch = ord(char)
        page = struct.unpack('<h', self.elf.read(glyph_map + 2 * (ch >> 5), 2))[0]
        need(0 <= page < 2048, 'Unsupported sprite font map page')
        glyph = struct.unpack('<h', self.elf.read(glyph_map + 0x1000 + 64 * page + 2 * (ch & 31), 2))[0]
        need(0 <= glyph < nglyph, 'Character is not present in original sprite font', 'missing_glyph')
        sid = self.u32(pages + 4 * (glyph // cells))
        need(sid in self.sprites, 'Font sheet sprite is missing')
        k = glyph % cells
        return sid, (k % cols * cell, k // cols * cell, cell, cell), (half if ch <= 127 else full)

    def title_chars(self):
        chars = set()
        for index in range(5200):
            check_cancel(self.cancel)
            chars.update(self.wstr(self.u32(0x9745580 + 28 * index + 20), limit=128))
        need(len(chars) <= 2000, 'Title glyph namespace budget')
        return tuple(sorted(chars))

    def name_chars(self):
        return tuple(chr(v) for v in self.ints(0x932A440, 256)
                     if 0 < v <= 0xFFFF and not 0xD800 <= v <= 0xDFFF)

    def story_select(self):
        images = tuple(tuple(self.ints(0x93FC920 + 16 * i, 2)) for i in range(111))
        levels = self.ints(0x93FD040, 20)
        texts = tuple((4, self.cstr(self.u32(0x93FD340 + 4 * i))) for i in range(22))
        texts += ((1, 'スタートランプ'),)
        texts += tuple((4, self.cstr(self.u32(0x93FD2E0 + 4 * i))) for i in range(17))
        return {'sprites': tuple(sorted({sid for row in images for sid in row} | set(levels) | {0x4E7, 0x4E8})),
                'texts': texts, 'ramp_of': self.ints(0x93FD120, 110)}

    def tuning(self):
        """Reproduce sttune.py's text-index order without its emulator-only flags."""
        texts, sprites, part_names = [], set(), set()
        def text(pointer):
            value = self.wstr(pointer)
            if not value:
                return -1
            if value not in texts:
                texts.append(value)
            return texts.index(value)
        def row(address):
            tuner, picture, name, a, b, c, _shop = self.ints(address, 7)
            sprites.add(picture)
            values = tuple(text(p) for p in (name, a, b, c))
            part_names.add(values[0])
            return values
        for address, count in ((0x93FC264, 11), (0x93FC384, 11), (0x93FC4A4, 12), (0x93FC604, 11)):
            for i in range(1, count):
                row(address + 28 * i)
        row(0x93FC5F4)
        row(0x93FC5D8)
        for i in range(18):
            sprites.update(self.ints(0x93FC0E0 + 16 * i, 4))
        for address in (0x9773960, 0x9773920):
            for p in self.ints(address, 10):
                part_names.add(text(p))
        for address in (0x93FC200, 0x93FC240):
            sprites.update(self.ints(address, 10))
        for address in (0x9773820, 0x97738A0, 0x9773520, 0x97735A0, 0x97737A0,
                        0x9773720, 0x97736A0, 0x9773620, 0x97734A0):
            for p in self.ints(address, 30):
                text(p)
        for address in (0x9773460, 0x9773420, 0x97733E0):
            for p in self.ints(address, 12):
                text(p)
        text(self.u32(0x9773988))
        text(self.u32(0x977398C))
        step, colon = self.wstr(0x933A5DC), self.wstr(0x93F0EE4)
        for i in range(1, 36):
            value = step + ''.join(chr(0xFF10 + int(c)) for c in str(i))
            if value not in texts:
                texts.append(value)
        for index in sorted(part_names):
            if index >= 0:
                value = colon + texts[index]
                if value not in texts:
                    texts.append(value)
        return {'sprites': tuple(sorted(i for i in sprites if i > 100)),
                'texts': tuple((1, text) for text in texts)}

    def tuning_effects(self):
        """Only STEFF sprites/texts; car pose/flag tables are not 2D payload."""
        sprites, texts = set(), []
        for table, strings, count in ((0x93FD780, 0x9776720, 10), (0x93FD820, 0x9776780, 10),
                                      (0x93FD8C0, 0x97767E0, 10), (0x93FD960, 0x9776830, 1),
                                      (0x93FD970, 0x9776838, 1), (0x93FD640, 0x9776660, 10),
                                      (0x93FD6E0, 0x97766C0, 10), (0x93FD980, 0, 1)):
            for index in range(count):
                check_cancel(self.cancel)
                title, part, anim, pose = self.ints(table + 16 * index, 4)
                need(title < SPRITE_COUNT and part < SPRITE_COUNT and pose < 8,
                     'Unsupported tuning-effect table')
                sprites.update((title, part))
                if strings:
                    a, b = self.ints(strings + 8 * index, 2)
                    texts.append((1, (self.wstr(a), self.wstr(b))))
        sprites.update(self.ints(0x93FD5E0, 17))
        sprites.update(range(0x479, 0x483))
        sprites.update(range(2657, 2667))
        sprites.update(range(2668, 2678))
        return {'sprites': tuple(sorted(i for i in sprites if i > 1)), 'texts': tuple(texts)}

    def bgm_texts(self):
        count = self.u32(0x93DD760)
        need(0 < count <= 128, 'BGM text count budget')
        result = []
        for index in range(count):
            song = struct.unpack('<i', self.elf.read(0x93DD780 + 4 * index, 4))[0]
            need(-1 <= song <= 0x6E, 'BGM song selector out of range')
            title = 'RANDOM' if song == 0x6E else 'NO BGM' if song < 0 else self.wstr(self.u32(0x931F4E0 + 12 * song + 8), limit=256)
            result.append((0, title))
        return tuple(result)

    def ten_banners(self):
        fmt = self.cstr(0x93D2AD0)
        need(fmt == '%s人目', 'Unsupported ten-rival banner format')
        result = [(4, fmt.replace('%s', self.cstr(self.u32(0x93D2240 + 4 * i)))) for i in range(32)]
        result += [(4, self.cstr(self.u32(0x93D21C0 + 4 * i))) for i in range(32)]
        return tuple(result)

    def story_demo(self):
        """Recover storydemo.py's data tables and literal initializer strings.

        C7 immediate stores and basic_string constructor arguments are projected
        from one fixed, pinned 0x8000-byte initializer. This scans data shapes; it
        does not execute instructions, branch, emulate x86 or call constructors.
        Every required one of the 221 string records must have a unique owner.
        """
        events, anim_max = [], -1
        for table in range(127):
            check_cancel(self.cancel)
            pointer, count = self.ints(0x976B7C0 + 8 * table, 2)
            need(count <= 4096 and len(events) + count <= 65535, 'Story demo event budget')
            for index in range(count):
                frame, kind, arg = struct.unpack('<3i', self.elf.read(pointer + 12 * index, 12))
                need(0 <= frame <= 32767 and 0 <= kind <= 21 and 0 <= arg <= 4096,
                     'Invalid story demo event')
                events.append((frame, kind, arg))
                if kind in (8, 9):
                    anim_max = max(anim_max, arg)
        need(0 <= anim_max < 512, 'Story demo animation row budget')
        animations = []
        for index in range(anim_max + 1):
            cluster, x, y, anim, first, length = struct.unpack('<6i', self.elf.read(0x976FC00 + 24 * index, 24))
            need(first == length == 0 and 0 <= anim < 4096, 'Unsupported story demo animation row')
            path = self.cstr(self.u32(0x954FB60 + 8 * anim))
            source_path(path)
            need(path.startswith('data/anime/') and path.endswith('.anm'), 'Unsafe demo animation path')
            animations.append(path.rsplit('/', 1)[1][:-4])
        start, rows, record_size = 0x97FC1A0, 221, 28
        values, assigned = [[0] * 7 for _ in range(rows)], set()
        code = self.elf.code(0x85D6142, 0x8000)
        offset, arg4 = 0, None
        while offset < len(code):
            check_cancel(self.cancel)
            if code[offset:offset + 2] == b'\xc7\x05' and offset + 10 <= len(code):
                address, value = struct.unpack_from('<Ii', code, offset + 2)
                if start <= address < start + rows * record_size:
                    relative = address - start
                    need(relative % 4 == 0, 'Unaligned story cut-in initializer')
                    row, field = divmod(relative, record_size)
                    if field != 20:
                        values[row][field // 4] = value
                offset += 10
            elif code[offset:offset + 4] == b'\xc7\x44\x24\x04' and offset + 8 <= len(code):
                arg4 = struct.unpack_from('<I', code, offset + 4)[0]
                offset += 8
            elif code[offset:offset + 3] == b'\xc7\x04\x24' and offset + 7 <= len(code):
                address = struct.unpack_from('<I', code, offset + 3)[0]
                if start <= address < start + rows * record_size and (address - start) % record_size == 20:
                    row = (address - start) // record_size
                    need(arg4 is not None and row not in assigned, 'Duplicate/missing story string initializer')
                    values[row][5] = self.wstr(arg4)
                    assigned.add(row)
                offset += 7
            else:
                offset += 1
        need(len(assigned) == rows, 'Story demo initializer string coverage incomplete')
        need(all(0 <= row[1] < 66 and 0 <= row[2] < 64 for row in values),
             'Story demo character/expression out of range')
        return {'animations': tuple(sorted(set(animations))),
                'texts': tuple((row[1], row[2], row[5]) for row in values),
                'events': len(events), 'tables': 127}

    def wear_texts(self):
        """The 41 wear banners from finite literal case DAGs, no sprintf/calls.

        Case selection is the reviewed port recipe from weartexts.py. All names,
        suffixes and sprite IDs remain native C7/05 literal operands read from
        main. Conditional dispatch itself is not interpreted or executed.
        """
        self.shape(0x88E6161, b'\xff\x24\xbd\x74\xf4\x40\x09')
        for address, prefix in ((0x88E6206, b'\xff\x24\xb5\x98\xf4\x40\x09'),
                                (0x88E626C, b'\xff\x24\xb5\xcc\xf4\x40\x09'),
                                (0x88E6286, b'\xff\x24\xb5\xe8\xf4\x40\x09'),
                                (0x88E62F0, b'\xff\x24\xb5\x20\xf6\x40\x09')):
            self.shape(address, prefix)
        def store(address, expected):
            self.shape(address, b'\xc7\x05')
            dest, value = self.ints(address + 2, 2)
            need(dest == expected, 'Unknown wear constant field owner')
            return value
        default_action = store(0x88E6360, 0x97FF8A0)
        def row(start):
            fields, seen, position = {0x97FF8A0: default_action}, set(), start
            for _ in range(64):
                check_cancel(self.cancel)
                if position == 0x88E61D0:
                    need(0x97FF880 in fields and 0x97FF8A0 in fields, 'Wear text fields incomplete')
                    return self.cstr(fields[0x97FF880]) + self.cstr(fields[0x97FF8A0])
                need(0x88E60C4 <= position < 0x88E8200 and position not in seen,
                     'Wear literal case graph cycle/range')
                seen.add(position)
                opcode = self.elf.code(position, 2)
                if opcode == b'\xc7\x05':
                    target, value = self.ints(position + 2, 2)
                    need(0x97FF880 <= target <= 0x97FF8A4 and target % 4 == 0,
                         'Wear constant store escapes result record')
                    fields[target] = value
                    position += 10
                elif opcode[:1] == b'\xe9':
                    # A fixed direct join in the immutable constant-case DAG;
                    # no input-dependent branch evaluation or CPU state exists.
                    displacement = struct.unpack('<i', self.elf.code(position + 1, 4))[0]
                    position += 5 + displacement
                else:
                    raise MenuConversionError('unsupported_2d_shape', 'Nonliteral wear case at ' + hex(position))
            raise MenuConversionError('invalid_2d', 'Wear literal case record budget')
        starts = [0x88E7CBB, 0x88E6419, 0x88E7C45, 0x88E6388, 0x88E7CF5,
                  0x88E7CDC, 0x88E6450, 0x88E7C7C, 0x88E6326]
        starts += [self.u32(0x940F620 + 4 * n) for n in range(5)]
        starts += [0x88E63F5, 0x88E62A6]
        texts = [row(address) for address in starts]
        # These two are authored as literals by the original port recipe, not
        # raster input copied from a previous conversion.
        texts += ['装着完了！', '純正ホイールに交換完了！']
        texts += [row(self.u32(0x940F4CC + 4 * n)) for n in range(7)]
        texts += [row(self.u32(0x940F498 + 4 * n)) for n in range(7, 13)]
        texts += [row(self.u32(0x940F4E8 + 4 * n)) for n in (1, 11, 21, 31, 41, 42, 43, 48, 58, 68)]
        need(len(texts) == 41 and all(0 < len(text) <= 128 for text in texts), 'Wear text namespace incomplete')
        return tuple((4, text) for text in texts)

    def parts_sprite_literals(self):
        """Conservative sprite closure of every native dress/wheel literal case.

        All image-result writes in this pinned function are absolute C7/05
        literals (the only register-to-result write is the debug name at +0).
        Projecting the complete finite case inventory avoids executing ladder,
        gem, model or colour conditionals. The result is a *superset*, not a
        claim that all these cases are reachable at one dress level. No sprite
        comes from a generated dressdb header or from a previous image pack.
        """
        start, end, result_base = 0x88E60C4, 0x88E8350, 0x97FF880
        self.shape(start, b'\x55\x89\xe5\x81\xec\x28\x01\x00\x00')
        self.shape(0x88E63D5, b'\xff\x24\xb5\x34\xf6\x40\x09')
        code = self.elf.code(start, end - start)
        dress, wheels, provenance = set(), set(), []
        selected = {4, 16, 20, 24, 28, 36}
        offset = 0
        while offset < len(code):
            check_cancel(self.cancel)
            if code[offset:offset + 2] == b'\xc7\x05' and offset + 10 <= len(code):
                target, value = struct.unpack_from('<II', code, offset + 2)
                field = target - result_base
                if field in selected and value > 1:
                    need(value in self.sprites, 'Dress literal references missing/non-sprite data')
                    if field in (20, 24):
                        dress.add(value)
                    if field in (4, 16, 28, 36):
                        wheels.add(value)
                    provenance.append({'instruction': hex(start + offset), 'operand': hex(start + offset + 6),
                                       'field': field, 'sprite': value})
                offset += 10
            elif (code[offset:offset + 1] == b'\x89' and offset + 6 <= len(code) and
                  code[offset + 1] & 0xC7 == 5):
                target = struct.unpack_from('<I', code, offset + 2)[0]
                need(target - result_base not in selected, 'Nonliteral dress image assignment', 'unsupported_2d_shape')
                offset += 6
            else:
                offset += 1
        need(0 < len(dress) <= 2048 and 0 < len(wheels) <= 2048 and len(provenance) <= 4096,
             'Dress/wheel literal coverage budget')
        return {'dress': tuple(sorted(dress)), 'wheels': tuple(sorted(wheels)),
                'coverage': 'all-literal-cases-superset', 'provenance': tuple(provenance),
                'function_range': (hex(start), hex(end))}

    def dress_sprites(self):
        return self.parts_sprite_literals()['dress']

    def wheel_set_sprites(self):
        return self.parts_sprite_literals()['wheels']

    def cutin_faces(self):
        names, images = {}, []
        for char in range(66):
            name = self.cstr(0x9768FA0 + 32 * char, limit=32)
            need('::' in name, 'Cut-in character name is invalid')
            name = name.split('::', 1)[1]
            case = self.u32(0x93CFFB8 + 4 * char)
            if self.elf.code(case, 1) == b'\xba':
                sprite = self.u32(case + 1)
                if sprite in (0, 1):
                    need(name == 'CHAR_NO', 'Unexpected native no-image character')
                    sprite = None
                else:
                    need(sprite in self.sprites, 'Cut-in sheet unavailable')
            elif case == 0x85D4703:
                sprite = 0xD71
                need(sprite in self.sprites, 'Default cut-in sheet unavailable')
            else:
                sprite = None  # Explicit native cases without an image assignment.
            need(name not in names, 'Duplicate cut-in character name')
            names[name] = sprite
            images.append(sprite)
        return {'names': MappingProxyType(names), 'by_char': tuple(images)}

    def uv_cells(self, *, with_provenance=False):
        """Project the fixed unrolled UV initializer into literal-word references.

        The admitted region has no control-flow, calls, arithmetic, indirect
        source reads or general memory. Its MOVE/zero/float-stack *data-flow*
        is parsed into a dictionary of references to immutable ELF words; only
        the final 276 records are materialised. Unknown shapes fail closed.
        This is not a general x86 VM and never dispatches an instruction/PC.
        """
        start, stop, base, end = 0x8A0AB49, 0x8A10C95, 0x9803C80, 0x9806398
        self.shape(0x8A0AB3F, b'\xbf\x80\x3c\x80\x09')
        self.shape(stop, b'\xe9\x87\x9e\xff\xff')
        code = self.elf.code(start, stop - start)
        # A symbolic word is None (unknown), 0 (zero), or an ELF word address.
        regs, sse, slots, output, floating = [None] * 8, [None] * 8, {}, {}, []
        regs[7] = 0x8A0AB40
        position, operations = 0, 0
        def word(reference):
            need(reference is not None, 'UV read lacks a literal owner')
            return -reference if reference < 0 else (0 if reference == 0 else self.u32(reference))
        def operand(at):
            need(at < len(code), 'Truncated UV operand')
            modrm = code[at]
            mode, register, rm = modrm >> 6, (modrm >> 3) & 7, modrm & 7
            if mode == 3:
                return register, ('register', rm), at + 1
            if mode == 0 and rm == 5:
                need(at + 5 <= len(code), 'Truncated UV absolute address')
                return register, ('absolute', struct.unpack_from('<I', code, at + 1)[0]), at + 5
            need(rm == 5 and mode in (1, 2), 'Unreviewed UV addressing mode')
            width = 1 if mode == 1 else 4
            need(at + 1 + width <= len(code), 'Truncated UV stack slot')
            offset = int.from_bytes(code[at + 1:at + 1 + width], 'little', signed=True)
            need(-0x7AC <= offset <= -4 and offset % 4 == 0, 'UV stack slot outside fixed frame')
            return register, ('slot', offset), at + 1 + width
        def get(target, bank):
            kind, address = target
            if kind == 'register':
                return bank[address]
            if kind == 'slot':
                need(address in slots, 'UV stack data-flow has no owner')
                return slots[address]
            if base <= address < end:
                need(address in output, 'UV table data-flow reads uninitialised word')
                return output[address]
            self.elf.read(address, 4)
            return address
        def put(target, reference, bank):
            need(reference is not None, 'UV store lacks a literal owner')
            kind, address = target
            if kind == 'register':
                bank[address] = reference
            elif kind == 'slot':
                slots[address] = reference
            else:
                need(base <= address <= end - 4 and (address - base) % 4 == 0,
                     'UV literal store escapes reviewed table')
                output[address] = reference
        while position < len(code):
            check_cancel(self.cancel)
            operations += 1
            need(operations <= 5000, 'UV operation count budget')
            opcode = code[position]
            if opcode == 0xFC:  # fixed clear-direction annotation, not host state
                position += 1
            elif code[position:position + 2] == b'\x31\xc0':
                regs[0] = 0
                position += 2
            elif code[position:position + 3] == b'\x0f\x57\xc9':
                sse[1] = 0
                position += 3
            elif 0xB8 <= opcode <= 0xBF:
                need(position + 5 <= len(code), 'Truncated UV literal')
                regs[opcode - 0xB8] = start + position + 1
                position += 5
            elif opcode == 0xB1:
                need(code[position + 1] == 9 and word(regs[1]) == 0, 'Unknown UV fixed zero span')
                regs[1] = start + position + 1  # byte literal handled by REP below
                position += 2
            elif code[position:position + 2] == b'\xf3\xab':
                count = 9 if code[position - 2:position] == b'\xb1\x09' or (
                    regs[1] and self.elf.read(regs[1], 1) == b'\x09') else word(regs[1])
                dest = word(regs[7])
                need(count == 9 and word(regs[0]) == 0 and base <= dest <= end - 36,
                     'UV zero-span outside reviewed table')
                for i in range(9):
                    output[dest + 4 * i] = 0
                # EDI is an affine destination cursor, kept separately as a
                # synthetic literal (negative references never leave this local pass).
                regs[7] = -(dest + 36)
                regs[1] = 0
                position += 2
            elif opcode in (0x89, 0x8B, 0xC7):
                register, target, following = operand(position + 1)
                if opcode == 0xC7:
                    need(register == 0 and following + 4 <= len(code), 'Unsupported UV literal store')
                    put(target, start + following, regs)
                    position = following + 4
                elif opcode == 0x89:
                    put(target, regs[register], regs)
                    position = following
                else:
                    regs[register] = get(target, regs)
                    position = following
            elif code[position:position + 3] in (b'\xf3\x0f\x10', b'\xf3\x0f\x11'):
                register, target, following = operand(position + 3)
                if code[position + 2] == 0x10:
                    sse[register] = get(target, sse)
                else:
                    put(target, sse[register], sse)
                position = following
            elif opcode == 0xD9:
                modrm = code[position + 1]
                if 0xC8 <= modrm <= 0xCF:
                    index = modrm - 0xC8
                    need(index < len(floating), 'UV float-stack exchange underflow')
                    floating[0], floating[index] = floating[index], floating[0]
                    position += 2
                else:
                    kind, target, following = operand(position + 1)
                    need(kind in (0, 2, 3) and target[0] != 'register', 'Unreviewed UV float form')
                    if kind == 0:
                        floating.insert(0, get(target, regs))
                        need(len(floating) <= 8, 'UV float-stack depth budget')
                    else:
                        need(floating, 'UV float-stack store underflow')
                        put(target, floating[0], regs)
                        if kind == 3:
                            floating.pop(0)
                    position = following
            else:
                raise MenuConversionError('unsupported_2d_shape', 'Unsupported literal UV form at ' + hex(start + position))
        need(not floating and len(output) == (end - base) // 4, 'UV word ownership coverage incomplete')
        result = []
        for index in range(276):
            values = []
            for field in range(5):
                ref = output[base + 36 * index + 4 * field]
                raw = b'\0' * 4 if ref == 0 else self.elf.read(ref, 4)
                values.append(struct.unpack('<I' if field == 0 else '<f', raw)[0])
            sprite, *uv = values
            need(sprite < SPRITE_COUNT and all(math.isfinite(v) and 0 <= v <= 4 for v in uv),
                 'UV projected scalar out of range')
            result.append((sprite, *(round(v * 1024) for v in uv)))
        if with_provenance:
            return {'cells': tuple(result), 'word_sources': tuple(tuple(
                {'kind': 'zero'} if output[base + 36 * index + 4 * field] == 0 else
                {'kind': 'elf-word', 'address': hex(output[base + 36 * index + 4 * field])}
                for field in range(5)) for index in range(276)),
                'projection': 'fixed-unrolled-literal-word-flow', 'operations': operations,
                'initializer_range': (hex(start), hex(stop)), 'initialized_records': 278}
        return tuple(result)

    def pack_order(self, available_folders):
        """CARDB_PACKS order from main nickname table and reviewed hidden stores.

        The order policy (normal alphabetical, then hidden maker polling order)
        belongs to the port; car IDs themselves are operand-derived, not copied
        from cardb.h. available_folders is an explicit 55-folder read-set scope.
        """
        names = {}
        need(isinstance(available_folders, (tuple, list, dict)) and len(available_folders) == 55,
             'An explicit 55-pack folder scope is required')
        available = {}
        for name in available_folders:
            need(isinstance(name, str) and NAME.fullmatch(name) and name.casefold() not in available,
                 'Ambiguous or unsafe car pack folder')
            available[name.casefold()] = name
        for index in range(56):
            pointer, car = self.ints(0x9417720 + 8 * index, 2)
            name = self.cstr(pointer)
            need(NAME.fullmatch(name) and car not in names, 'Invalid car nickname table')
            if name.casefold() in available:
                names[car] = available[name.casefold()]
        need(len(names) == 55 and set(names.values()) == set(available_folders),
             'Folder scope differs from main car table')
        self.shape(0x88EC108, b'\xff\x24\x9d\xb0\x09\x41\x09')
        self.shape(0x88EC229, b'\xff\x24\xb5\xc8\x09\x41\x09')
        # Toyota hidden cases 0,1,3,4,6; Subaru, Mazda and Nissan use one conditional store each.
        hidden_store = [self.u32(0x94109C8 + 4 * k) for k in (0, 1)]
        hidden_store += [0x88EC2BB, self.u32(0x94109C8 + 12), self.u32(0x94109C8 + 16),
                         0x88EC444, self.u32(0x94109C8 + 24), 0x88EC355]
        hidden = []
        for address in hidden_store:
            self.shape(address, b'\xc7\x05')
            dest, car = self.ints(address + 2, 2)
            need(0x97FFA24 <= dest <= 0x97FFA50 and (dest - 0x97FFA20) % 4 == 0 and car in names,
                 'Unsupported hidden car initializer')
            hidden.append(names[car])
        need(len(set(hidden)) == 8, 'Hidden pack order is ambiguous')
        return tuple(sorted(set(names.values()) - set(hidden)) + hidden)

    def meter_layouts(self, pack_order):
        """Behind-view dial/needle rows, matching the compiled meterdb part ABI.

        main's 0xe8-byte stCarData defines every ID/coordinate/angle. R35's
        night needles draw their day base then additive night image. SpecV's
        rev lamps depend on live rev and are deliberately outside WMT1 v1.
        """
        self.shape(0x856876D, b'\x8b\x04\x85\x80\x69\x73\x09')
        self.shape(0x85B6BFF, b'\xc7\x44\x24\x08\xe8\x00\x00\x00')
        self.shape(0x85B6E11, b'\x8b\x85\x08\xf9\xff\xff\x85\xff\x0f\x45\xc3')
        self.shape(0x85B8B70, b'\xc7\x85\x2c\xff\xff\xff\x01\x00\x00\x00')
        folders = {}
        for index in range(56):
            pointer, car = self.ints(0x9417720 + 8 * index, 2)
            folders[self.cstr(pointer).casefold()] = car
        result = []
        for folder in pack_order:
            check_cancel(self.cancel)
            need(folder.casefold() in folders, 'Unknown meter pack')
            car = folders[folder.casefold()]
            address = self.u32(0x9736980 + 4 * car)
            data = self.elf.read(address, 0xE8)
            u = lambda off: struct.unpack_from('<I', data, off)[0]
            f = lambda off: struct.unpack_from('<f', data, off)[0]
            need(0 < u(0x20) <= 2000 and 3 <= u(0x24) <= 8, 'Invalid stock meter identity')
            xy = [(f(off), f(off + 4)) for off in (0x98, 0xA0, 0xA8)]
            angle = [(f(off), f(off + 4)) for off in (0xC8, 0xB8, 0xC0)]
            need(all(math.isfinite(v) and abs(v) <= 4096 for pair in xy + angle for v in pair),
                 'Invalid static meter geometry')
            zones = []
            for night in (0, 1):
                sd, td, bd = u(0x38 + 12 * night), u(0x3C + 12 * night), u(0x40 + 12 * night)
                sd2, td2 = u(0x68 + 4 * night), u(0x70 + 4 * night)
                sn, tn, bn = u(0x50 + 12 * night), u(0x54 + 12 * night), u(0x58 + 12 * night)
                tn2 = u(0x78 + 4 * night)
                sd, td, tn = sd2 if sd2 != 1 else sd, td2 if td2 != 1 else td, tn2 if tn2 != 1 else tn
                def part(sid, dial, variable=0, additive=0):
                    need(sid in self.sprites, 'Required original meter sprite missing')
                    a0, a1 = angle[dial] if variable else (0., 0.)
                    return MeterPart(sid, *xy[dial], a0, a1, variable, additive)
                parts = [part(sd, 0), part(td, 1)]
                # The original isR35 branch's model predicate is encoded in main;
                # the extra meter assets identify precisely these two car records.
                layered = night and sd2 != 1 and td2 != 1 and u(0x78) != 1 and u(0x7C) != 1
                if layered:
                    parts += [part(u(0x50), 0, 1), part(u(0x78), 1, 2)]
                parts += [part(sn, 0, 1, int(bool(layered))), part(tn, 1, 2, int(bool(layered)))]
                if u(0x28) & 1:
                    parts.append(part(bd, 2))
                    if layered:
                        parts.append(part(u(0x58), 2, 3))
                    parts.append(part(bn, 2, 3, int(bool(layered))))
                need(len(parts) <= 9, 'Meter ABI part count exceeded')
                zones.append(tuple(parts))
            result.append({'folder': folder, 'car': car, 'hp': u(0x20), 'gears': u(0x24), 'parts': tuple(zones)})
        need(len(result) == 55, 'Required meter pack coverage is not 55')
        return tuple(result)

    def navi_areas(self):
        result = {}
        for area in range(1, 75):
            for offset, on in ((0, 1), (4, 0)):
                name = self.cstr(self.u32(0x93D9F84 + 12 * area + offset))
                if name:
                    need(NAME.fullmatch(name), 'Unsafe minimap node name')
                    result.setdefault(name, (area, on))
        return MappingProxyType(result)
