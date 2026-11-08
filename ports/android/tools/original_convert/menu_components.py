"""CPU original-resource 2D components, with explicit OriginalSupport inputs.

No menupack/hudpack/meterdb/navipack imports, generated support files, system
fonts, subprocesses, Lua execution or game code execution. The caller supplies a
bounded reader for original main/data resources and a new owned output path.
Output hashes are observations, NOT release signatures or publication authority.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import io
import math
import os
import re
import struct
import zlib

import numpy as np
from PIL import Image

from .physics_image import _parent_fd
from .source import check_cancel, source_path
from .menu_support import (OriginalSupport, MenuConversionError, need, dimensions,
                           MAX_ASSET_BYTES, MAX_PIXELS, MAX_TEXT)

HUD_SPRITES = ('cons_p_mis_4', 'cons_p_mis_5', 'cons_p_mis_6', 'cons_p_mis_mt', 'cons_p_mis_at') + tuple(
    'cons_p_mis_' + kind + str(i) for kind in ('m', 'a') for i in range(7)) + (
    'cons_p_speed_waku', 'cons_p_rank_waku', 'cons_p_rank_N', 'cons_p_rank_Q', 'cons_p_speed_km',
    'cons_p_bariki_bariki', 'cons_p_bariki_DG', 'cons_p_bariki_D', 'cons_p_bariki_B', 'cons_p_bariki_G', 'cons_p_bariki_HG')
HUD_ATLAS = tuple((f'big_{i}', 96 + 40 * i, 6, 40, 36) for i in range(10)) + tuple(
    (f'big_shadow_{i}', 96 + 40 * i, 41, 40, 36) for i in range(10)) + tuple(
    (f'small_{i}', 96 + 12 * i, 77, 12, 16) for i in range(10))
_FINISH = ((4, 260), (60, 260), (116, 260), (172, 260), (228, 260), (324, 260), (380, 260), (436, 260), (4, 308), (60, 308))
HUD_CROPS = [('ta_total', 4, 232, 96, 20), ('ta_quote1', 300, 232, 20, 20), ('ta_quote2', 320, 232, 20, 20),
             ('ta_section', 244, 136, 92, 16), ('ta_pill', 4, 928, 160, 32), ('map_waku', 4, 4, 92, 140),
             ('time_extend', 508, 48, 256, 32), ('goal_dot', 156, 308, 40, 48), ('goal_km', 112, 308, 40, 48),
             ('goal_m', 284, 260, 40, 48)]
HUD_CROPS += [(f'ta_{i}', 100 + 20 * i, 232, 20, 20) for i in range(10)]
HUD_CROPS += [(f'ltime_{i}', 4 + 24 * i, 144, 24, 24) for i in range(10)]
HUD_CROPS += [(f'ltime_s_{i}', 4 + 24 * (i % 5), 168 + 24 * (i // 5), 24, 24) for i in range(10)]
HUD_CROPS += [(f'goal_{i}', x, y, 56, 48) for i, (x, y) in enumerate(_FINISH)]
HUD_CROPS += [(f'map_name_{i}', x, y, 128, 16) for i, (x, y) in enumerate((
    (256, 384), (256, 400), (384, 528), (384, 544), (384, 592), (384, 608),
    (384, 480), (256, 608), (384, 464), (384, 624), (384, 560), (384, 576)))]
HUD_CROPS += [('rec_your', 240, 104, 104, 16), ('rec_time', 240, 120, 104, 16),
              ('rec_dash', 328, 168, 16, 20), ('buyin_refuse', 508, 80, 104, 36)]
HUD_CROPS += [(f'sign_{i + 1}', x, y, 64, 64) for i, (x, y) in enumerate((
    (892, 48), (892, 112), (892, 176), (892, 240), (828, 48), (828, 112), (828, 176), (828, 240),
    (764, 48), (764, 112), (956, 48), (956, 112), (956, 240), (956, 176)))]
_MAP_UV = (185, 186, 187, 188, 189, 190, 191, 194, 193, 192, 197, 195, 196, 200, 201, 199, 198, 209, 210)
_UV = {**{n: (256, 384 + 16 * (n - 185)) for n in range(185, 200)},
       **{n: (384, 496 + 16 * (n - 200)) for n in range(200, 209)}, 209: (384, 480), 210: (384, 464)}
HUD_CROPS += [(f'map_text_{i + 1}', *_UV[n], 128, 16) for i, n in enumerate(_MAP_UV)]
HUD_CROPS += [(f'rank_{c}', 360 + 12 * i, 76, 12, 16) for i, c in enumerate('NABC')]
HUD_CROPS += [('rank_S', 360, 92, 12, 16)] + [(f'rank_{i}', 372 + 12 * i, 92, 12, 16) for i in range(10)]
HUD_CROPS = tuple(HUD_CROPS)


class _Output:
    """Exclusive no-follow output; a failed new partial is deliberately retained."""
    def __init__(self, path, *, cancel=None, max_bytes=512 * 1024 * 1024):
        self.path, self.cancel, self.limit = path, cancel, max_bytes
        self.bytes, self.digest, self.fd = 0, hashlib.sha256(), None
        self.parent = None

    def __enter__(self):
        check_cancel(self.cancel)
        self.parent = _parent_fd(self.path)
        directory, name = self.parent.__enter__()
        try:
            self.fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        except BaseException:
            self.parent.__exit__(None, None, None)
            raise
        return self

    def write(self, data):
        need(isinstance(data, bytes) and self.bytes + len(data) <= self.limit, '2D output byte budget')
        for offset in range(0, len(data), 65536):
            check_cancel(self.cancel)
            chunk = data[offset:offset + 65536]
            view = memoryview(chunk)
            while view:
                count = os.write(self.fd, view)
                need(count > 0, 'Output made no progress', 'io_error')
                view = view[count:]
            self.digest.update(chunk)
            self.bytes += len(chunk)

    def __exit__(self, typ, value, traceback):
        try:
            if typ is None:
                check_cancel(self.cancel)
                os.fsync(self.fd)
        finally:
            os.close(self.fd)
            self.parent.__exit__(typ, value, traceback)

    def receipt(self, **values):
        return dict(algorithm='3dxplus-cpu-original-2d-v1', bytes=self.bytes,
                    observed_sha256=self.digest.hexdigest(), publication_authority=False, **values)


def _read(read, name, *, max_bytes=MAX_ASSET_BYTES, cancel=None):
    check_cancel(cancel)
    source_path(name)
    data = read(name, max_bytes=max_bytes, cancel=cancel)
    need(isinstance(data, bytes) and len(data) <= max_bytes, 'Original reader exceeded byte budget')
    check_cancel(cancel)
    return data


def decode_image(data):
    need(isinstance(data, bytes) and 0 < len(data) <= MAX_ASSET_BYTES, 'Image input byte budget')
    try:
        with Image.open(io.BytesIO(data)) as image:
            need(image.format in ('PNG', 'TGA', 'DDS'), 'Unsupported original image format')
            dimensions(*image.size)
            need(getattr(image, 'n_frames', 1) == 1, 'Animated original sprite is unsupported')
            image.load()
            return image.convert('RGBA')
    except (OSError, Image.DecompressionBombError) as exc:
        raise MenuConversionError('invalid_2d', 'Original image decoding failed') from exc


def crop(image, rect):
    x, y, width, height = rect
    dimensions(width, height)
    need(0 <= x <= image.width - width and 0 <= y <= image.height - height,
         'Original sprite crop is outside its image')
    return image.crop((x, y, x + width, y + height))


class SpriteRenderer:
    """Original atlas/font renderer with a bounded decoded-sheet LRU."""
    def __init__(self, support, read, *, cancel=None, cache_bytes=32 * 1024 * 1024):
        need(isinstance(support, OriginalSupport), 'Explicit OriginalSupport required')
        need(0 <= cache_bytes <= 128 * 1024 * 1024, 'Invalid sprite cache budget')
        self.support, self.read, self.cancel = support, read, cancel
        self.cache, self.cache_size, self.cache_limit = OrderedDict(), 0, cache_bytes
        self.reads = {}

    def image(self, name):
        check_cancel(self.cancel)
        if name in self.cache:
            self.cache.move_to_end(name)
            return self.cache[name].copy()
        data = _read(self.read, name, cancel=self.cancel)
        digest = hashlib.sha256(data).hexdigest()
        previous = self.reads.get(name)
        need(previous is None or previous == (len(data), digest), 'Original image changed between reads', 'source_changed')
        self.reads[name] = (len(data), digest)
        image = decode_image(data)
        size = image.width * image.height * 4
        if size <= self.cache_limit:
            while self.cache_size + size > self.cache_limit:
                _, old = self.cache.popitem(last=False)
                self.cache_size -= old.width * old.height * 4
            self.cache[name] = image.copy()
            self.cache_size += size
        return image

    def sprite(self, sid, *, table_size=False):
        need(type(sid) is int and sid in self.support.sprites, 'Original sprite ID is unavailable')
        entry = self.support.sprites[sid]
        image = self.image(entry.path)
        if table_size and entry.width > 0 and entry.height > 0:
            size = dimensions(round(entry.width), round(entry.height))
            if image.size != size:
                image = image.resize(size, Image.Resampling.LANCZOS)
        return image

    def text(self, font, text):
        check_cancel(self.cancel)
        need(isinstance(text, str) and 0 < len(text) <= MAX_TEXT, 'Invalid sprite font text length')
        _, half, full, cell, *_ = self.support.font(font)
        advances = [half if ord(c) <= 127 else full for c in text]
        width = sum(advances[:-1]) + cell
        dimensions(width, cell)
        out = Image.new('RGBA', (width, cell))
        x = 0
        for char, advance in zip(text, advances):
            check_cancel(self.cancel)
            sid, rect, actual = self.support.glyph(font, char)
            need(actual == advance, 'Sprite font advance changed')
            out.alpha_composite(crop(self.sprite(sid), rect), (x, 0))
            x += advance
        return out

    def lines(self, font, lines):
        need(isinstance(lines, (tuple, list)) and 0 < len(lines) <= 128 and
             all(isinstance(t, str) and len(t) <= MAX_TEXT for t in lines), 'Line count/text budget')
        _, half, full, cell, *_ = self.support.font(font)
        widths = [sum(half if ord(c) <= 127 else full for c in line) for line in lines]
        size = dimensions(max(widths) + cell, full * (len(lines) - 1) + cell)
        out = Image.new('RGBA', size)
        for index, line in enumerate(lines):
            if line:
                out.alpha_composite(self.text(font, line), (0, full * index))
        return out


def _drop_guide(image):
    width, height = image.size
    edge = [(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
    edge += [(0, y) for y in range(height)] + [(width - 1, y) for y in range(height)]
    if all(image.getpixel(point) == (255, 0, 0, 255) for point in edge):
        for point in edge:
            image.putpixel(point, (0, 0, 0, 0))
    return image


def pack_hud(support, read, output_path, *, cancel=None, progress=None):
    renderer = SpriteRenderer(support, read, cancel=cancel)
    total = len(HUD_SPRITES) + len(HUD_ATLAS) + 2 + 2 + len(HUD_CROPS)
    count = 0
    with _Output(output_path, cancel=cancel, max_bytes=32 * 1024 * 1024) as output:
        output.write(b'WHD1' + struct.pack('<I', total))
        def put(name, image):
            nonlocal count
            need(len(name.encode('ascii')) < 32, 'HUD sprite name ABI overflow')
            dimensions(*image.size)
            output.write(name.encode('ascii').ljust(32, b'\0') + struct.pack('<II', *image.size))
            output.write(image.tobytes())
            count += 1
            if progress:
                progress('pack_hud', count, total)
        for name in HUD_SPRITES:
            put(name, _drop_guide(renderer.image('data/sprite/' + name + '.png')))
        atlas = renderer.image('data/sprite/cons_p_01.png')
        for name, *rect in HUD_ATLAS:
            put(name, crop(atlas, rect))
        put('title', renderer.text(0, '湾岸の新人'))
        put('name', renderer.text(1, 'ＧＵＥＳＴ'))
        for name in ('cons_p_finish_made', 'cons_p_ltime_time'):
            put(name, _drop_guide(renderer.image('data/sprite/' + name + '.png')))
        for name, *rect in HUD_CROPS:
            put(name, crop(atlas, rect))
        need(count == total, 'HUD sprite count mismatch')
    return output.receipt(format='WHD1', coverage='complete-component', sprites=count,
                          input_files=len(renderer.reads), semantics='original sprites/atlas and original sprite fonts')


def pack_meters(support, read, output_path, available_folders, *, cancel=None, progress=None):
    order = support.pack_order(available_folders)
    layouts = support.meter_layouts(order)
    sprites, at, indices = [], {}, []
    for car in layouts:
        for zone in car['parts']:
            for part in zone:
                if part.sprite not in at:
                    at[part.sprite] = len(sprites)
                    sprites.append(part.sprite)
                indices.append(at[part.sprite])
            indices.extend([0xFFFF] * (9 - len(zone)))
    need(len(sprites) <= 4096, 'Meter sprite count budget')
    renderer = SpriteRenderer(support, read, cancel=cancel)
    sizes = []
    for sid in sprites:
        image = renderer.sprite(sid)
        sizes.append(image.size)
    offset = 12 + 2 * len(indices) + 12 * len(sprites)
    table = []
    for width, height in sizes:
        table.append(struct.pack('<III', width, height, offset))
        offset += width * height * 4
    need(offset <= 256 * 1024 * 1024, 'Meter output byte budget')
    with _Output(output_path, cancel=cancel, max_bytes=256 * 1024 * 1024) as output:
        output.write(b'WMT1' + struct.pack('<II', len(order), len(sprites)))
        output.write(struct.pack('<' + str(len(indices)) + 'H', *indices) + b''.join(table))
        for index, (sid, size) in enumerate(zip(sprites, sizes)):
            image = renderer.sprite(sid)
            need(image.size == size, 'Meter input size changed', 'source_changed')
            output.write(image.tobytes())
            if progress:
                progress('pack_meters', index + 1, len(sprites))
        need(output.bytes == offset, 'Meter size table mismatch')
    return output.receipt(format='WMT1', coverage='complete-component', cars=len(order),
                          sprites=len(sprites), pack_order=list(order),
                          semantics='native behind-view part order; original table image paths, including TGA',
                          optional_specv_rev_lamps=False)


def load_anm(data, *, keep=None, cancel=None):
    need(isinstance(data, bytes) and 8 <= len(data) <= 16 * 1024 * 1024, 'Animation byte budget')
    frames, max_records = struct.unpack_from('<II', data)
    need(0 < frames <= 20000 and 0 <= max_records <= 4096 and 8 + 8 * frames <= len(data),
         'Animation frame/record count budget')
    base = 8 + frames * 8
    need((len(data) - base) % 64 == 0, 'Truncated animation record bytes')
    count = (len(data) - base) // 64
    need(count <= 250000, 'Animation record budget')
    selections = []
    for index in range(frames):
        check_cancel(cancel)
        start, length = struct.unpack_from('<II', data, 8 + 8 * index)
        need(length <= max_records and start <= count and length <= count - start, 'Animation frame range is invalid')
        selections.append((start, length))
    if keep is not None:
        need(type(keep) is int and 0 < keep <= frames, 'Invalid animation frame selection')
        selections = selections[:keep]
    end = max(start + length for start, length in selections)
    records = []
    for index in range(end):
        check_cancel(cancel)
        row = struct.unpack_from('<i6f9i', data, base + 64 * index)
        need(-1 <= row[0] < 8091 and all(math.isfinite(v) and abs(v) <= 1e7 for v in row[1:7]),
             'Animation sprite/transform is invalid')
        need(all(-65536 <= v <= 65536 for v in row[7:15]) and 0 <= row[15] <= 255,
             'Animation colour/blend is invalid')
        records.append(row)
    return tuple(selections), tuple(records)


def load_cutin_lines(data, *, cancel=None):
    """Parse native ASCII-delimited cut-in text without splitting U+3000.

    The historical Python helper's str.split treated full-width spaces inside
    Japanese dialogue as separators, truncating lines. This CPU profile keeps
    that original text. '#' still denotes a space and literal \\n a new line.
    """
    need(isinstance(data, bytes) and 0 < len(data) <= 1024 * 1024, 'Cut-in source byte budget')
    try:
        text = data.decode('utf-8', 'strict')
    except UnicodeError as exc:
        raise MenuConversionError('invalid_2d', 'Cut-in source is not UTF-8') from exc
    rows, tokens = [], 0
    for line in text.splitlines():
        check_cancel(cancel)
        need(len(line) <= 16384, 'Cut-in source line budget')
        line = line.strip(' \t\r')
        if not line or line == 'ECUTIN_B':
            continue
        fields = re.split(r'[ \t]+', line)
        tokens += len(fields)
        need(tokens <= 8192 and len(rows) < 256, 'Cut-in record/token budget')
        need(len(fields) == 10 and fields[0] == 'ECUTINSERIAL_ONESHOT' and
             fields[4].startswith('nsCutinDisp::CHAR_') and fields[5].isascii() and fields[5].isdecimal(),
             'Unsupported cut-in text row')
        character, expression = fields[4].split('::', 1)[1], int(fields[5])
        need(1 <= expression <= 32 and 0 < len(fields[8]) <= MAX_TEXT, 'Cut-in expression/text budget')
        lines = tuple(fields[8].replace('#', ' ').split('\\n'))
        need(len(lines) <= 128, 'Cut-in rendered line budget')
        rows.append((character, expression, lines))
    need(rows, 'Cut-in source has no rows')
    return tuple(rows)


@dataclass(frozen=True)
class MenuRecipe:
    """Finite, explicit WMN3 slice; a partial recipe never claims full menu coverage."""
    animations: tuple
    extra_sprites: tuple = ()
    # (output sprite ID, original font ID, tuple of text lines)
    texts: tuple = ()


CORE_MENU_RECIPE = MenuRecipe(tuple((name, None) for name in (
    'atract_layout_title', 'menu_g_bg_image', 'menu_g_bg_line', 'menu_g_bg_logo',
    'menu_g_topbar_bar', 'menu_g_bottombar_bar', 'menu_layout_carsel_maker_',
    'menu_g_carsel_maker_car_image', 'menu_g_bg_carsel_2', 'menu_g_carsel_car',
    'menu_layout_carsel_car_arrow', 'menu_layout_ta_carsel', 'menu_layout_ta_course',
    'menu_g_course_map', 'menu_layout_ta_course_arrow')),
    texts=((100000, 8, ('ＧＵＥＳＴ',)), (100001, 1, ('湾岸の新人',))))


def pack_menu_slice(support, read, output_path, recipe=CORE_MENU_RECIPE, *, cancel=None, progress=None):
    """Write a real WMN3 slice for integration/proof, explicitly NOT a ready menu.bin.

    Full port-specific car/dress/demo/UV/VS/info namespaces must be supplied by a
    future reviewed full recipe; neither missing assets nor text are replaced by
    old converted resources. The receipt and filename prevent silent readiness.
    """
    need(isinstance(recipe, MenuRecipe) and 0 < len(recipe.animations) <= 1024 and
         len(recipe.extra_sprites) <= 16000 and len(recipe.texts) <= 16000, 'Menu recipe count budget')
    need(os.path.basename(output_path) != 'menu.bin', 'Partial menu must not be named menu.bin', 'incomplete_menu')
    renderer = SpriteRenderer(support, read, cancel=cancel)
    animations, used, seen_names = [], OrderedDict(), set()
    total_frames, total_records = 0, 0
    for index, (name, keep) in enumerate(recipe.animations):
        need(isinstance(name, str) and 0 < len(name.encode('ascii')) < 48 and
             all(c.isalnum() or c == '_' for c in name) and name not in seen_names,
             'Unsafe or duplicate menu animation name')
        seen_names.add(name)
        data = _read(read, 'data/anime/' + name + '.anm', max_bytes=16 * 1024 * 1024, cancel=cancel)
        frames, records = load_anm(data, keep=keep, cancel=cancel)
        total_frames += len(frames)
        total_records += len(records)
        need(total_frames <= 100000 and total_records <= 500000, 'Aggregate animation frame/record budget')
        for record in records:
            if record[0] >= 0:
                need(record[0] in support.sprites, 'Required animation sprite is unavailable')
                used.setdefault(record[0], len(used))
        animations.append((name, frames, records))
        if progress:
            progress('read_menu_anims', index + 1, len(recipe.animations))
    for sid in recipe.extra_sprites:
        need(type(sid) is int and sid in support.sprites, 'Extra menu sprite is unavailable')
        used.setdefault(sid, len(used))
    text_ids = [row[0] for row in recipe.texts]
    need(all(type(sid) is int and 100000 <= sid < 200000 for sid in text_ids) and
         len(set(text_ids)) == len(text_ids) and len(used) + len(text_ids) < 65535,
         'Menu sprite namespace conflict/budget')
    with _Output(output_path, cancel=cancel) as output:
        output.write(b'WMN3' + struct.pack('<I', len(used) + len(text_ids)))
        def put(sid, image):
            raw = image.tobytes()
            packed = zlib.compress(raw, 6)
            output.write(struct.pack('<iHHI', sid, *image.size, len(packed)))
            output.write(packed)
        for index, sid in enumerate(used):
            put(sid, renderer.sprite(sid, table_size=True))
            if progress:
                progress('pack_menu_sprites', index + 1, len(used))
        for sid, font, lines in recipe.texts:
            put(sid, renderer.lines(font, lines) if len(lines) != 1 else renderer.text(font, lines[0]))
        output.write(struct.pack('<I', len(animations)))
        for name, frames, records in animations:
            output.write(name.encode('ascii').ljust(48, b'\0') + struct.pack('<II', len(frames), len(records)))
            output.write(b''.join(struct.pack('<II', *frame) for frame in frames))
            for record in records:
                sprite = used[record[0]] if record[0] >= 0 else 0xFFFF
                output.write(struct.pack('<HH6f8h', sprite, {8: 1, 9: 2}.get(record[15], 0), *record[1:7],
                                         *(max(-32768, min(32767, v)) for v in record[7:15])))
    return output.receipt(format='WMN3', coverage='partial-menu-slice', sprites=len(used) + len(text_ids),
                          animations=len(animations), complete_menu=False,
                          missing_namespaces=['car-select-text', 'story-demo', 'story-pre', 'dress-wear',
                                              'UV-constructor', 'VS-port-art', 'port-info-page'],
                          semantics='original animation transforms/sprite table sizes, zlib CPU profile')


# A minimal bounded v8 IGB decoder used only by the two minimap source kinds.
# No graph recursion, external file following, stage scripts, or global imports.
class _IGB:
    def __init__(self, data, cancel=None):
        need(48 <= len(data) <= MAX_ASSET_BYTES, 'IGB byte budget')
        self.data, self.cancel = data, cancel
        self.work = 0
        h = self.unpack('<12I', 0)
        need(h[10] == 0xFADA and h[11] & 0xFFFF == 8, 'Only little-endian IGB v8 is supported')
        entry_bytes, entry_count, meta_bytes, meta_count, object_bytes = h[:5]
        field_bytes, field_count = h[8:10]
        need(0 < entry_count <= 60000 and 0 < meta_count <= 2048 and 0 < field_count <= 2048,
             'IGB metadata record budget')
        flags, pos = h[11], 48
        self.names, pos = self.pool(pos)
        field_start, field_end = pos, pos + field_bytes
        self.bounds(pos, field_bytes)
        pos = field_start + 12 * field_count
        need(pos <= field_end, 'IGB meta-field header overflow')
        for index in range(field_count):
            length = self.unpack('<I', field_start + 12 * index)[0]
            self.string_bytes(pos, length, field_end)
            pos += length
        pos = field_end
        align = self.unpack('<I', pos)[0]
        need(4 <= align <= 4096, 'IGB alignment block budget')
        self.bounds(pos, align)
        pos += align
        meta_start, meta_end = pos, pos + meta_bytes
        self.bounds(pos, meta_bytes)
        cursor = pos + 24 * meta_count
        need(cursor <= meta_end, 'IGB meta-object header overflow')
        self.meta = []
        fields_total = 0
        for index in range(meta_count):
            length, _, _, count, parent, _ = self.unpack('<IIIIiI', meta_start + 24 * index)
            name = self.string_bytes(cursor, length, meta_end)
            cursor += length
            fields_total += count
            need(count <= 256 and fields_total <= 32768 and -1 <= parent < meta_count,
                 'IGB field/parent budget')
            fields = []
            for j in range(count):
                need(cursor + 6 <= meta_end, 'IGB meta-field overflow')
                kind, slot, size = self.unpack('<3H', cursor)
                need(kind < field_count and size <= 4096, 'IGB field type/size invalid')
                fields.append((slot, size))
                cursor += 6
            need(len({slot for slot, _ in fields}) == len(fields), 'IGB duplicate field slot')
            self.meta.append((name, tuple(fields)))
        pos = meta_end
        if flags & (1 << 30):
            _, pos = self.pool(pos)
        if flags & (1 << 28):
            length = self.unpack('<I', pos)[0]
            need(4 <= length <= MAX_ASSET_BYTES, 'IGB pool-name block budget')
            self.bounds(pos, length)
            pos += length
        entries, end = [], pos + entry_bytes
        self.bounds(pos, entry_bytes)
        for index in range(entry_count):
            kind, length = self.unpack('<II', pos)
            need(kind < meta_count and 8 <= length <= end - pos, 'IGB directory entry invalid')
            entries.append((kind, self.fields(pos + 8, pos + length, self.meta[kind][1])))
            pos += length
        need(pos == end, 'IGB directory entry byte coverage mismatch')
        length, count = self.unpack('<II', end)
        need(8 <= length <= MAX_ASSET_BYTES and count <= 60000 and 8 + 2 * count <= length,
             'IGB index count budget')
        self.bounds(end, length)
        index_map = self.unpack('<' + str(count) + 'H', end + 8)
        need(all(index < len(entries) for index in index_map), 'IGB directory index is invalid')
        object_start = end + length + (4 if flags >> 31 else 0)
        self.bounds(object_start, object_bytes)
        op, mp, object_end = object_start, object_start + object_bytes, object_start + object_bytes
        self.objects = []
        for index, entry in enumerate(index_map):
            self.tick()
            kind, fields = entries[entry]
            name = self.meta[kind][0]
            if name.startswith('igExternal'):
                self.objects.append((name, fields, None))
            elif name == 'igMemoryDirEntry':
                size = self.integer(fields, 7)
                mem_kind = self.integer(fields, 10)
                need(0 <= size <= MAX_ASSET_BYTES and 0 <= mem_kind < meta_count, 'IGB memory block invalid')
                self.bounds(mp, size)
                self.objects.append((self.meta[mem_kind][0], {}, memoryview(data)[mp:mp + size]))
                mp += (size + 3) & ~3
            else:
                typ, size = self.unpack('<II', op)
                need(typ < meta_count and 8 <= size <= object_end - op, 'IGB object range invalid')
                objname, schema = self.meta[typ]
                self.objects.append((objname, self.fields(op + 8, op + size, schema), None))
                op += size
        need(op == object_end and mp <= len(data), 'IGB object coverage mismatch')

    def tick(self):
        self.work += 1
        need(self.work <= 300000, 'IGB work/edge budget')
        check_cancel(self.cancel)

    def bounds(self, offset, count):
        need(0 <= offset <= len(self.data) and 0 <= count <= len(self.data) - offset, 'IGB range out of bounds')

    def unpack(self, fmt, offset):
        self.tick()
        self.bounds(offset, struct.calcsize(fmt))
        return struct.unpack_from(fmt, self.data, offset)

    def string_bytes(self, offset, size, end):
        need(0 <= size <= 4096 and offset + size <= end, 'IGB string length budget')
        self.bounds(offset, size)
        raw = self.data[offset:offset + size]
        # These are length-framed strings, including a legal zero-length pool item.
        return raw.split(b'\0', 1)[0].decode('latin1')

    def pool(self, pos):
        size, count = self.unpack('<II', pos)
        need(8 <= size <= MAX_ASSET_BYTES and count <= 60000, 'IGB name pool budget')
        self.bounds(pos, size)
        cursor, end, result = pos + 8, pos + size, []
        for _ in range(count):
            length = self.unpack('<I', cursor)[0]
            cursor += 4
            result.append(self.string_bytes(cursor, length, end))
            cursor += length
        need(cursor <= end, 'IGB pool range overflow')
        return result, end

    def fields(self, start, end, schema):
        result = {}
        for slot, size in schema:
            if start + 4 > end:
                break
            need(start + size <= end, 'IGB field is truncated')
            result[slot] = self.data[start:start + size]
            start += (size + 3) & ~3
        return result

    @staticmethod
    def integer(fields, slot, default=None):
        raw = fields.get(slot)
        if raw is None and default is not None:
            return default
        need(raw is not None and 0 < len(raw) <= 4, 'IGB required integer field missing')
        return struct.unpack('<i', raw.ljust(4, b'\0'))[0]

    def ref(self, fields, slot):
        index = self.integer(fields, slot, -1)
        if index == -1:
            return None
        need(0 <= index < len(self.objects), 'IGB reference index out of bounds')
        return index

    def name(self, fields, slot=2):
        index = self.integer(fields, slot, -1)
        if index == -1:
            return ''
        need(0 <= index < len(self.names), 'IGB name index out of bounds')
        return self.names[index]

    def mem(self, index):
        need(index is not None and self.objects[index][2] is not None, 'IGB memory object required')
        return self.objects[index][2]

    def refs(self, index):
        if index is None:
            return ()
        _, fields, _ = self.objects[index]
        count = self.integer(fields, 2)
        need(0 <= count <= 60000, 'IGB object-list count budget')
        if not count:
            return ()
        data = self.mem(self.ref(fields, 4))
        need(count * 4 <= len(data), 'IGB object-list memory truncated')
        refs = struct.unpack_from('<' + str(count) + 'i', data)
        need(all(0 <= ref < len(self.objects) for ref in refs), 'IGB object-list reference out of bounds')
        return refs


def _igb_image(f, index, *, bgr=False):
    need(index is not None, 'Minimap texture is missing')
    name, fields, _ = f.objects[index]
    need(name == 'igImage', 'External/non-image minimap texture is unsupported')
    width, height = dimensions(f.integer(fields, 2), f.integer(fields, 3))
    fmt = f.integer(fields, 11)
    data = bytes(f.mem(f.ref(fields, 13)))
    if fmt in (0, 5, 7):
        mode, step = {0: ('L', 1), 5: ('RGB', 3), 7: ('RGBA', 4)}[fmt]
        need(width * height * step <= len(data), 'Minimap texture bytes truncated')
        image = Image.frombytes(mode, (width, height), data[:width * height * step]).convert('RGBA')
    else:
        need(fmt in (14, 15, 16), 'Unsupported minimap texture format')
        fourcc = {14: b'DXT1', 15: b'DXT3', 16: b'DXT5'}[fmt]
        size = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * (8 if fmt == 14 else 16)
        need(size <= len(data), 'Minimap compressed texture bytes truncated')
        header = struct.pack('<4s7I44x', b'DDS ', 124, 0x81007, height, width, size, 0, 1)
        header += struct.pack('<2I4s5I', 32, 4, fourcc, 0, 0, 0, 0, 0)
        header += struct.pack('<5I', 0x1000, 0, 0, 0, 0)
        image = decode_image(header + data[:size])
    if bgr:
        red, green, blue, alpha = image.split()
        image = Image.merge('RGBA', (blue, green, red, alpha))
    return image


def _vertices(f, index):
    name, fields, _ = f.objects[index]
    if name == 'igVertexArray1_1':
        count = f.integer(fields, 3)
        need(0 < count <= 65535, 'Old minimap vertex count budget')
        refs = f.mem(f.ref(fields, 2))
        need(len(refs) >= 80, 'Old vertex reference table truncated')
        refs = struct.unpack_from('<20i', refs)
        def block(which, dtype, width):
            index = refs[which]
            need(0 <= index < len(f.objects), 'Old vertex block reference invalid')
            data = f.mem(index)
            need(count * width * np.dtype(dtype).itemsize <= len(data), 'Old vertex block truncated')
            result = np.frombuffer(data, dtype=dtype, count=count * width).reshape(count, width).copy()
            need(np.isfinite(result).all(), 'Old vertex block nonfinite')
            return result
        result = {'pos': block(0, '<f4', 3), 'uv': block(11, '<f4', 2)}
        if refs[2] >= 0:
            # This older layout stores RGBA, not the newer interleaved BGRA.
            result['rgba'] = block(2, 'u1', 4)
        return result
    need(name == 'igVertexArray2', 'Unsupported minimap vertex array')
    streams = f.refs(f.ref(fields, 3))
    need(len(streams) == 1, 'Minimap requires one vertex stream')
    name, fields, _ = f.objects[streams[0]]
    need(name == 'igVertexData', 'IGB vertex data object required')
    stride = f.integer(fields, 6)
    need(0 < stride <= 256, 'IGB vertex stride budget')
    byte_list = f.ref(fields, 3)
    need(byte_list is not None, 'Vertex byte-list missing')
    data = f.mem(f.ref(f.objects[byte_list][1], 4))
    pos, offset, elements = 1, 0, []
    while True:
        f.tick()
        need(pos < len(data) and len(elements) <= 16, 'Vertex declaration unterminated')
        usage = data[pos]
        if usage == 0xFF:
            pos += 1
            break
        need(pos + 1 < len(data) and usage in (1, 2, 3, 4), 'Unsupported vertex declaration usage')
        size = data[pos + 1] >> 4
        need(size in (4, 6, 8, 12), 'Unsupported vertex declaration width')
        elements.append((usage, offset, size))
        offset += size
        pos += 2
    need(offset == stride and (len(data) - pos) % stride == 0, 'Vertex declaration/stride mismatch')
    count = (len(data) - pos) // stride
    need(0 < count <= 65535 and len({e[0] for e in elements}) == len(elements), 'Vertex count/duplicate declaration budget')
    raw = np.frombuffer(data, dtype='u1', count=count * stride, offset=pos).reshape(count, stride)
    result = {}
    for usage, offset, size in elements:
        chunk = np.ascontiguousarray(raw[:, offset:offset + size])
        if usage == 1:
            need(size in (6, 12), 'Unsupported position width')
            result['pos'] = chunk.view('<f4' if size == 12 else '<f2').astype(np.float32).reshape(count, 3)
        elif usage == 4:
            need(size in (4, 8), 'Unsupported UV width')
            result['uv'] = chunk.view('<f2').astype(np.float32).reshape(count, size // 2)[:, :2]
        elif usage == 2:
            need(size == 4, 'Unsupported colour width')
            result['rgba'] = chunk[:, [2, 1, 0, 3]]
    need('pos' in result and 'uv' in result and np.isfinite(result['pos']).all() and
         np.isfinite(result['uv']).all(), 'Missing or nonfinite minimap vertex fields')
    return result


def _triangles(f, fields, nverts, *, old=False):
    primitive = f.integer(fields, 6 if old else 7)
    index = f.ref(fields, 5)
    if index is None:
        indices = np.arange(nverts, dtype=np.int32)
    else:
        _, table, _ = f.objects[index]
        count = f.integer(table, 3)
        data = f.mem(f.ref(table, 2))
        need(0 <= count <= 1000000 and count * 2 <= len(data), 'Minimap index count/bytes budget')
        indices = np.frombuffer(data, dtype='<u2', count=count).astype(np.int32)
    need(len(indices) > 0 and int(indices.max()) < nverts, 'Minimap vertex index out of bounds')
    if primitive == 3:
        need(len(indices) % 3 == 0, 'Triangle-list index count mismatch')
        return indices.reshape(-1, 3).astype('<u2')
    need(primitive == 4, 'Unsupported minimap primitive')
    lengths = [len(indices)]
    length_list = f.ref(fields, 13 if old else 6)
    if length_list is not None:
        _, table, _ = f.objects[length_list]
        count = f.integer(table, 3)
        data = f.mem(f.ref(table, 2))
        need(0 < count <= 65535 and 4 * count <= len(data), 'Minimap primitive count/bytes budget')
        lengths = struct.unpack_from('<' + str(count) + 'I', data)
    need(sum(lengths) == len(indices), 'Minimap strip lengths do not cover indices')
    result, start = [], 0
    for length in lengths:
        f.tick()
        need(length >= 3, 'Minimap strip too short')
        for index in range(length - 2):
            if index % 1024 == 0:
                f.tick()
            a, b, c = map(int, indices[start + index:start + index + 3])
            if len({a, b, c}) == 3:
                result.append((a, b, c) if index % 2 == 0 else (b, a, c))
        start += length
    return np.asarray(result, dtype='<u2').reshape(-1, 3)


_VERTEX = np.dtype([('pos', '<f4', 3), ('uv', '<f4', 2), ('rgba', 'u1', 4)])


def _matmul4(left, right):
    """Fixed float32 multiply/add order; no host BLAS/FMA dispatch dependency."""
    need(left.ndim == right.ndim == 2 and left.shape[1] == right.shape[0] == 4,
         'Invalid affine matrix dimensions')
    result = np.zeros((left.shape[0], right.shape[1]), dtype=np.float32)
    with np.errstate(over='ignore', invalid='ignore'):
        for index in range(4):
            result += left[:, index:index + 1] * right[index:index + 1, :]
    need(np.isfinite(result).all(), 'Nonfinite affine product')
    return result


def _meshes(data, cancel=None):
    f = _IGB(data, cancel)
    infos = [fields for name, fields, mem in f.objects if name == 'igSceneInfo' and mem is None]
    need(len(infos) == 1, 'Minimap requires exactly one scene root')
    root = f.ref(infos[0], 5)
    need(root is not None, 'Minimap scene root missing')
    stack = [(root, np.eye(4, dtype=np.float32), None, False, (), frozenset())]
    result, total_vertices, total_indices = [], 0, 0
    while stack:
        f.tick()
        index, matrix, image, blend, path, ancestors = stack.pop()
        need(index not in ancestors and len(ancestors) < 128, 'Cyclic or overdeep minimap scene graph')
        ancestors = ancestors | {index}
        name, fields, mem = f.objects[index]
        if mem is not None:
            continue
        if name == 'igGroup':
            path += (f.name(fields),)
        if name == 'igTransform' and 8 in fields:
            need(len(fields[8]) == 64, 'Minimap transform byte size')
            local = np.frombuffer(fields[8], dtype='<f4').reshape(4, 4)
            need(np.isfinite(local).all(), 'Nonfinite minimap transform')
            matrix = _matmul4(local, matrix)
        attrs = f.refs(f.ref(fields, 8)) if name in ('igAttrSet', 'igGeometry') else ()
        need(name != 'igSimpleShader', 'Unreviewed minimap shader graph')
        for attribute in attrs:
            typ, values, _ = f.objects[attribute]
            if typ == 'igTextureBindAttr' and f.integer(values, 2) == 0:
                texture = f.ref(values, 4)
                need(texture is not None and f.objects[texture][0] == 'igTextureAttr',
                     'External minimap texture is not allowed')
                image = f.ref(f.objects[texture][1], 12)
            elif typ == 'igBlendStateAttr':
                blend = bool(f.integer(values, 4))
        if name == 'igGeometry':
            for attribute in attrs:
                typ, values, _ = f.objects[attribute]
                if typ.startswith('igGeometryAttr'):
                    need(typ in ('igGeometryAttr2', 'igGeometryAttr1_5'), 'Unsupported minimap geometry revision')
                    va = f.ref(values, 4)
                    need(va is not None, 'Minimap vertex array missing')
                    verts = _vertices(f, va)
                    triangles = _triangles(f, values, len(verts['pos']), old=typ == 'igGeometryAttr1_5')
                    total_vertices += len(verts['pos'])
                    total_indices += triangles.size
                    need(total_vertices <= 1000000 and total_indices <= 3000000,
                         'Aggregate minimap geometry budget')
                    vert = np.zeros(len(verts['pos']), _VERTEX)
                    vert['pos'] = _matmul4(np.c_[verts['pos'], np.ones(len(vert), np.float32)], matrix)[:, :3]
                    vert['uv'] = verts['uv']
                    vert['rgba'] = verts.get('rgba', 255)
                    need(np.isfinite(vert['pos']).all() and np.abs(vert['pos']).max() <= 1e9,
                         'Nonfinite/excessive transformed minimap vertices')
                    result.append((path[-1] if path else '', image, int(blend), vert, triangles))
                    need(len(result) <= 2048, 'Minimap mesh count budget')
        for child in reversed(f.refs(f.ref(fields, 7))):
            stack.append((child, matrix, image, blend, path, ancestors))
        need(len(stack) <= 60000, 'Minimap graph frontier budget')
    need(result, 'Minimap has no drawable meshes')
    return f, result


def pack_navi(support, read, output_path, navi='SkNavi.igb', *, cancel=None, progress=None):
    need(isinstance(support, OriginalSupport), 'Explicit OriginalSupport required')
    need(navi in ('SkNavi.igb', 'OsNavi.igb', 'HkNavi.igb', 'NkNavi.igb', 'FkNavi.igb'),
         'Unreviewed minimap source name')
    areas = support.navi_areas()
    f, meshes = _meshes(_read(read, 'data/minimap/' + navi, cancel=cancel), cancel)
    fi, icons = _meshes(_read(read, 'data/effect/car_icon.igb', cancel=cancel), cancel)
    road = _igb_image(f, meshes[0][1])
    # All roads must bind the exact same texture, as required by the WNV1 ABI.
    road_bytes = road.tobytes()
    for image in {mesh[1] for mesh in meshes}:
        other = _igb_image(f, image)
        need(other.size == road.size and other.tobytes() == road_bytes, 'Minimap has multiple incompatible road textures')
    icon = _igb_image(fi, icons[0][1], bgr=True)
    with _Output(output_path, cancel=cancel, max_bytes=64 * 1024 * 1024) as output:
        output.write(b'WNV1' + struct.pack('<5I', *road.size, *icon.size, len(meshes)))
        output.write(road_bytes + icon.tobytes())
        for index, (name, image, blend, vertices, triangles) in enumerate(meshes):
            area, on = areas.get(name, (-1, 0))
            output.write(struct.pack('<hBBII', area, on, blend, len(vertices), triangles.size))
            output.write(vertices.tobytes() + triangles.tobytes())
            if progress:
                progress('pack_navi', index + 1, len(meshes))
    return output.receipt(format='WNV1', coverage='complete-component', meshes=len(meshes),
                          areas=len({areas.get(m[0], (-1, 0))[0] for m in meshes}),
                          vertices=sum(len(m[3]) for m in meshes), indices=sum(m[4].size for m in meshes),
                          semantics='original bottom-up IGB texture order, BGRA vertices, BGR-swapped car icon')
