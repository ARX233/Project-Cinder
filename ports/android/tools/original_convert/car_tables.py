"""Pure-static, pinned-main car pack support tables; no original code execution.

The small reviewed lookup formulas are decoded from table-address/count/stride
operands.  Car/model names, model ranges, lamp paths and wing bits are read from
ELF PT_LOAD bytes, never from a historical generated JSON/C header.  Paint counts
come from first-match model ownership and are checked against each original
car.lua's bounded, data-only parsed texture records.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct

from .physics_image import (Elf32, SOURCE_SHA256, PhysicsImageError,
                            ConversionCancelled, _check, _parent_fd, _read_source)

ALGORITHM = '3dxplus-static-car-tables-v1'
MAX_LUA_BYTES = 1024 * 1024
MAX_LUA_TOKENS = 150000
MAX_LUA_DEPTH = 40
NAME = re.compile(r'[A-Za-z0-9_]+\Z')
LAMP_PREFIX = 'data/car/brakelamp/brakelamp_'


class CarTableError(PhysicsImageError):
    pass


def _need(ok, message, code='unsupported_car_tables'):
    if not ok:
        raise CarTableError(code, message)


def _shape(elf, address, prefix):
    _need(elf.code(address, len(prefix)) == prefix,
          'Unsupported car lookup instruction at ' + hex(address))


def _operand(elf, address, prefix, width=4):
    _shape(elf, address, prefix)
    return int.from_bytes(elf.code(address + len(prefix), width), 'little')


def _cstring(elf, address, limit=512):
    seg = elf._segment(address, 1)
    data = elf.read(address, min(limit, seg.address + seg.file_size - address))
    end = data.find(b'\0')
    _need(end >= 0, 'Unterminated static table string')
    try:
        return data[:end].decode('utf-8', 'strict')
    except UnicodeError as exc:
        raise CarTableError('invalid_table_string', 'Invalid UTF-8 table string') from exc


def _model_car(rows, model, variants=True):
    """CarIDGetFromModelID: first containing range; false excludes variant rows."""
    for car, first, last, basefirst, baselast in rows:
        if (variants or (first == basefirst and last == baselast)) and first <= model <= last:
            return car
    raise CarTableError('unknown_model', 'Model does not belong to a reviewed car range')


def _wing_mask(record, body, wing_offset):
    # Each car has four {body, high[5], wing[5]} records, selected by body value.
    for index in range(4):
        offset = 1 + index * 11
        if record[offset] == body:
            return sum((record[offset + 1 + wing_offset + wing] == 1) << wing for wing in range(5))
    return 0


def _decode_main(elf, cancel=None, progress=None):
    def step(name, current):
        _check(cancel)
        if progress:
            progress(name, current, 5)
    step('car_nicknames', 0)
    nick = _operand(elf, 0x893D76D, b'\x8b\x04\xc5')
    nick_count = _operand(elf, 0x893D764, b'\x83\xf8', 1)
    _need((nick, nick_count) == (0x9417720, 56), 'Unknown nickname table geometry')
    _need(_operand(elf, 0x893D704, b'\x39\x0c\xc5') == nick + 4,
          'Unknown nickname table selection semantics')
    cars = {}
    ids = set()
    for index in range(nick_count):
        _check(cancel)
        ptr, car = struct.unpack('<II', elf.read(nick + index * 8, 8))
        name = _cstring(elf, ptr)
        _need(NAME.fullmatch(name) and name.casefold() not in {n.casefold() for n in cars} and
              0 <= car < 120 and car not in ids, 'Duplicate or invalid nickname table entry')
        cars[name] = car
        ids.add(car)
    step('car_model_ranges', 1)
    ranges_va = _operand(elf, 0x893DF90, b'\x8d\x84\xb8')
    ranges_count = _operand(elf, 0x893DFA6, b'\x83\xff', 1)
    _shape(elf, 0x893DF8D, b'\xc1\xe0\x04')  # index*16 + index*4 -> 20-byte row
    _shape(elf, 0x893DF97, b'\x3b\x50\x04\x7c\x09\x3b\x50\x08')
    _shape(elf, 0x893DE40, b'\xc1\xe0\x04\x8b\x84\xb8')
    _shape(elf, 0x893DE12, b'\x8b\x42\x04\x3b\x42\x0c')
    _shape(elf, 0x893DE1E, b'\x8b\x4a\x08\x3b\x4a\x10')
    _need((ranges_va, ranges_count) == (0x9419EA0, 121), 'Unknown model range geometry')
    ranges = []
    for i in range(ranges_count):
        _check(cancel)
        row = struct.unpack('<5i', elf.read(ranges_va + i * 20, 20))
        car, first, last, basefirst, baselast = row
        _need(0 <= car < 120 and 0 <= basefirst <= first <= last <= baselast <= 1024,
              'Invalid car model range')
        ranges.append(row)
    step('character_car_models', 2)
    character_models = {}
    for index in range(256):
        _check(cancel)
        row = struct.unpack('<6I', elf.read(0x9419888 + 24 * index, 24))
        if row == (0,) * 6:
            break
        ptr, model, _ctype, declared_car, zero0, zero1 = row
        _need(zero0 == zero1 == 0, 'Unsupported character-model record')
        name = _cstring(elf, ptr)
        car = _model_car(ranges, model, True)
        _need(NAME.fullmatch(name) and name not in cars and car == declared_car,
              'Invalid character-model identity')
        cars[name] = car
        character_models[name] = {'model': model, 'car': car}
    else:
        raise CarTableError('unsupported_car_tables', 'Unterminated character-model table')
    _need(len(character_models) == 64, 'Unexpected character-model coverage')
    step('brake_wing_masks', 3)
    mask_geometry = []
    for function in (0x893ED30, 0x893F0B0):
        table = _operand(elf, function + 1, b'\xba')
        stride = _operand(elf, function + 0x2A, b'\x8d\x9a')
        count = _operand(elf, function + 0x11A, b'\x83\xff', 1)
        body0 = _operand(elf, function + 0x12D, b'\x39\xb0')
        body1 = _operand(elf, function + 0x139, b'\x39\xb0')
        bitbase = _operand(elf, function + 0x17A, b'\x83\x3c\x95')
        _shape(elf, function + 0x181, b'\x01\x0f\x94\xc0')  # compare exactly 1; sete al
        _shape(elf, function + 0x162, b'\x8d\x04\x8d\x00\x00\x00\x00\x89\xca\xc1\xe2\x04\x29\xc2\x31\xc0\x29\xca')
        _need((table, stride, count, body0, body1) == (0x941A820, 180, 118, 0x941A824, 0x941A850),
              'Unsupported brake wing-mask table geometry')
        _need(bitbase in (table + 8, table + 28), 'Unknown high/wing field offset')
        mask_geometry.append((table, stride, count, (bitbase - table - 8) // 4))
    _need(mask_geometry[0][3] == 0 and mask_geometry[1][3] == 5,
          'Brake wing-mask semantics mismatch')
    masks = {}
    table, stride, count, _ = mask_geometry[0]
    for index in range(count):
        _check(cancel)
        row = struct.unpack('<45i', elf.read(table + index * stride, stride))
        _need(0 <= row[0] < 120 and row[0] not in masks and
              all(0 <= row[1 + k * 11] < 4 for k in range(4)) and
              all(v in (0, 1) for k in range(4) for v in row[2 + k * 11:12 + k * 11]),
              'Invalid brake mask car/body record')
        masks[row[0]] = row
    step('brake_lamp_paths', 4)
    lamps_va = _operand(elf, 0x893F431, b'\xba')
    ptr_va = _operand(elf, 0x893F43D, b'\xbb')
    lamps_count = _operand(elf, 0x893F4C9, b'\x81\xfe')
    lamps_stride = _operand(elf, 0x893F472, b'\x83\xc2', 1)
    _shape(elf, 0x893F448, b'\x3b\x3a')
    _shape(elf, 0x893F44C, b'\x8b\x45\x0c\x3b\x42\x04')
    _shape(elf, 0x893F4E0, b'\x8b\x03')
    _need((lamps_va, ptr_va, lamps_count, lamps_stride) == (0x941FB20, 0x941FB28, 288, 12),
          'Unknown brake-lamp path table geometry')
    lamps = {}
    for i in range(lamps_count):
        _check(cancel)
        car, body, ptr = struct.unpack('<3I', elf.read(lamps_va + lamps_stride * i, 12))
        key = f'{car} {body}'
        _need(car in set(cars.values()) and 0 <= body < 4 and key not in lamps,
              'Invalid or duplicate brake-lamp entry')
        if not ptr:
            continue
        path = _cstring(elf, ptr)
        _need(path.startswith(LAMP_PREFIX) and path.endswith('.igb'), 'Unsupported brake-lamp path')
        model = path[len(LAMP_PREFIX):-4]
        _need(NAME.fullmatch(model), 'Unsafe brake-lamp model name')
        row = masks.get(car)
        lamps[key] = [model, _wing_mask(row, body, 0) if row else 0,
                      _wing_mask(row, body, 5) if row else 0]
    step('main_tables_complete', 5)
    return {'nicknames': dict(list(cars.items())[:nick_count]), 'model_ranges': ranges,
            'character_models': character_models,
            'brake_lamps': {'cars': dict(sorted(cars.items())), 'lamps': lamps}}


TOKEN = re.compile(r'''(?P<space>\s+)|(?P<comment>--\[\[.*?\]\]|--[^\n]*)|(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?P<number>-?\d+\.?\d*(?:[eE][-+]?\d+)?|-?\.\d+)|(?P<name>[A-Za-z_][A-Za-z0-9_]*)|(?P<op>\.\.|[{}\[\]=,;()])''', re.S)


class _Lua:
    """Data-only parser, not Lua eval: no calls/indexing/operators/control flow."""
    def __init__(self, text, cancel=None):
        _need(len(text.encode('utf-8')) <= MAX_LUA_BYTES, 'Lua byte budget exceeded', 'invalid_lua')
        self.tokens = []
        self.cancel = cancel
        self.index = 0
        self.environment = {}
        offset = 0
        while offset < len(text):
            _check(cancel)
            match = TOKEN.match(text, offset)
            _need(match is not None, 'Unsupported data-only Lua syntax', 'invalid_lua')
            offset = match.end()
            if match.lastgroup == 'comment' and match.group().startswith('--[['):
                _need(match.group().endswith(']]'), 'Unterminated Lua block comment', 'invalid_lua')
            if match.lastgroup not in ('space', 'comment'):
                self.tokens.append((match.lastgroup, match.group()))
                _need(len(self.tokens) <= MAX_LUA_TOKENS, 'Lua token budget exceeded', 'invalid_lua')

    def peek(self, ahead=0):
        i = self.index + ahead
        return self.tokens[i] if i < len(self.tokens) else (None, None)

    def take(self, value=None):
        _check(self.cancel)
        token = self.peek()
        _need(token[0] is not None and (value is None or token[1] == value),
              'Truncated or unexpected Lua token', 'invalid_lua')
        self.index += 1
        return token

    def string(self, token):
        text, index, out = token[1:-1], 0, []
        escapes = {'a': '\a', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t',
                   'v': '\v', '\\': '\\', '"': '"', "'": "'"}
        while index < len(text):
            char = text[index]
            index += 1
            if char == '\\':
                _need(index < len(text) and text[index] in escapes, 'Unsupported Lua string escape', 'invalid_lua')
                char = escapes[text[index]]
                index += 1
            out.append(char)
        return ''.join(out)

    def expression(self, depth=0):
        _need(depth <= MAX_LUA_DEPTH, 'Lua nesting budget exceeded', 'invalid_lua')
        kind, value = self.take()
        if kind == 'string':
            result = self.string(value)
        elif kind == 'number':
            _need(len(value) <= 128, 'Lua numeric literal budget exceeded', 'invalid_lua')
            try:
                result = float(value) if any(c in value for c in '.eE') else int(value)
            except (ValueError, OverflowError) as exc:
                raise CarTableError('invalid_lua', 'Invalid Lua numeric literal') from exc
            _need(not isinstance(result, float) or math.isfinite(result), 'Nonfinite Lua number', 'invalid_lua')
        elif kind == 'name':
            if value in ('true', 'false', 'nil'):
                result = {'true': True, 'false': False, 'nil': None}[value]
            else:
                _need(value in self.environment, 'Unknown Lua identifier', 'invalid_lua')
                result = self.environment[value]
        elif value == '(':
            result = self.expression(depth + 1)
            self.take(')')
        elif value == '{':
            result = self.table(depth + 1)
        else:
            raise CarTableError('invalid_lua', 'Unsupported Lua expression')
        while self.peek()[1] == '..':
            self.take('..')
            right = self.expression(depth + 1)
            _need(isinstance(result, str) and isinstance(right, str), 'Non-string Lua concatenation', 'invalid_lua')
            result += right
            _need(len(result) <= MAX_LUA_BYTES, 'Lua string budget exceeded', 'invalid_lua')
        return result

    def table(self, depth):
        keyed, items = {}, []
        while self.peek()[1] != '}':
            if self.peek()[0] == 'name' and self.peek(1)[1] == '=':
                key = self.take()[1]
                self.take('=')
                # Original data files contain repeated named fields: Lua's
                # ordinary data-assignment semantics retain the last value.
                keyed[key] = self.expression(depth)
            elif self.peek()[1] == '[':
                self.take('[')
                key = self.expression(depth)
                self.take(']')
                self.take('=')
                _need(type(key) in (str, int) and key not in keyed, 'Invalid or duplicate Lua table key', 'invalid_lua')
                keyed[key] = self.expression(depth)
            else:
                items.append(self.expression(depth))
            if self.peek()[1] in (',', ';'):
                self.take()
            else:
                _need(self.peek()[1] == '}', 'Missing Lua table separator', 'invalid_lua')
        self.take('}')
        if keyed and items:
            for index, item in enumerate(items, 1):
                _need(index not in keyed, 'Conflicting Lua array key', 'invalid_lua')
                keyed[index] = item
            return keyed
        return keyed if keyed or not items else items

    def parse(self):
        while self.peek()[0] is not None:
            kind, name = self.take()
            _need(kind == 'name' and name not in self.environment, 'Invalid or repeated Lua assignment', 'invalid_lua')
            self.take('=')
            self.environment[name] = self.expression()
            if self.peek()[1] == ';':
                self.take(';')
        return self.environment


def _read_lua(path, cancel=None):
    try:
        with _parent_fd(path) as (directory, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                before = os.fstat(fd)
                _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_LUA_BYTES,
                      'Lua source is not a bounded regular file', 'invalid_lua')
                chunks, size = [], 0
                while size < before.st_size:
                    _check(cancel)
                    data = os.read(fd, min(65536, before.st_size - size))
                    _need(bool(data), 'Lua changed while reading', 'source_changed')
                    chunks.append(data)
                    size += len(data)
                _need(not os.read(fd, 1), 'Lua grew while reading', 'source_changed')
                after = os.fstat(fd)
                named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
                _need(identity(before) == identity(after) == identity(named), 'Lua source changed while reading', 'source_changed')
            finally:
                os.close(fd)
    except OSError as exc:
        raise CarTableError('io_error', 'Cannot read original car Lua: ' + str(exc)) from exc
    raw = b''.join(chunks)
    try:
        text = raw.decode('utf-8', 'strict')
    except UnicodeError as exc:
        raise CarTableError('invalid_lua', 'Car Lua is not valid UTF-8') from exc
    return _Lua(text, cancel).parse(), {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _pack_model_owners(decoded, actual_names, cancel=None):
    """Unique selectable model ownership; variants precede their wider base rows."""
    by_id = {car: name for name, car in decoded['nicknames'].items()}
    models = set()
    for car, first, last, _first, _last in decoded['model_ranges']:
        if car in by_id:
            models.update(range(first, last + 1))
    owners = {}
    for model in sorted(models):
        _check(cancel)
        car = _model_car(decoded['model_ranges'], model, True)
        _need(car in by_id, 'Selectable model points outside nickname table')
        name = by_id[car]
        actual = actual_names.get(name.casefold())
        if actual is None:
            base = _model_car(decoded['model_ranges'], model, False)
            _need(base in by_id, 'Variant has no nickname-table base')
            actual = actual_names.get(by_id[base].casefold())
        _need(actual is not None, 'Selectable model has no on-disk original owner', 'invalid_source')
        owners.setdefault(actual, []).append(model)
    return owners


def _paint_count(car):
    textures = car.get('BodyColorTexture')
    _need(isinstance(textures, dict) and isinstance(textures.get('normal'), list) and
          1 <= len(textures['normal']) <= 8, 'Missing/invalid normal paint records', 'invalid_lua')
    for row in textures['normal']:
        _need(isinstance(row, dict) and any(str(k).startswith('page') and isinstance(v, str) and v for k, v in row.items()),
              'Paint has no texture pages', 'invalid_lua')
    return len(textures['normal'])


def build_car_tables(main_path, car_directory, *, cancel=None, progress=None):
    """Return {packs, brake_lamps, character_models, model_ranges, provenance}.

    car_directory is the explicit original data/car directory.  Only main and
    the 55 named car.lua files are read; no old generated table is an API input.
    Returned hashes can be bound to the parent's signed source read-set.  This
    function does not publish resources or declare a ResourceStore ready.
    """
    _check(cancel)
    try:
        with _parent_fd(main_path) as (directory, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                raw, digest = _read_source(fd, cancel, progress, retain=True)
                _need(digest == SOURCE_SHA256, 'Unsupported main SHA-256', 'unsupported_source')
                decoded = _decode_main(Elf32(raw, cancel), cancel, progress)
                _, after_digest = _read_source(fd, cancel, progress, retain=False)
                _need(after_digest == digest, 'Main changed during table reconstruction', 'source_changed')
            finally:
                os.close(fd)
        car_directory = Path(car_directory)
        # Validate the full directory chain with the existing no-follow fd walker.
        with _parent_fd(car_directory / '_not_opened') as (car_fd, _):
            names = {}
            with os.scandir(car_fd) as entries:
                for index, entry in enumerate(entries):
                    _check(cancel)
                    _need(index < 1024, 'Car directory entry budget exceeded', 'invalid_source')
                    folded = entry.name.casefold()
                    _need(folded not in names, 'Case-ambiguous car directory', 'invalid_source')
                    if entry.is_dir(follow_symlinks=False):
                        names[folded] = entry.name
        paint_models = _pack_model_owners(decoded, names, cancel)
        packs, bodies, lua_sources, absent = {}, {}, {}, []
        for name, car_id in decoded['nicknames'].items():
            _check(cancel)
            actual = names.get(name.casefold())
            if actual is None:
                absent.append((name, car_id))
                continue
            car, source = _read_lua(car_directory / actual / 'car.lua', cancel)
            available_paints = _paint_count(car)
            npaint = len(paint_models.get(actual, ()))
            _need(1 <= npaint <= available_paints, 'Model paint count exceeds original Lua textures', 'invalid_lua')
            packs[actual] = npaint
            body = car.get('BodyIGB')
            _need(isinstance(body, dict) and isinstance(body.get('normal'), str), 'Missing stock body model', 'invalid_lua')
            bodies[actual] = [b for b in ('normal', 'aero_a', 'aero_b', 'aero_c') if body.get(b)]
            lua_sources[actual + '/car.lua'] = source
            if progress:
                progress('car_lua_paints', len(packs), 55)
        _need(len(packs) == 55 and len(absent) == 1, 'Original car directory coverage is incomplete', 'invalid_source')
        # Resolve a missing variant to an existing base through the false lookup,
        # not through a hardcoded folder name or historical generated result.
        for name, car_id in absent:
            own = [r for r in decoded['model_ranges'] if r[0] == car_id]
            _need(bool(own), 'Missing folder has no original model range')
            for row in own:
                for model in range(row[1], row[2] + 1):
                    base = _model_car(decoded['model_ranges'], model, False)
                    base_names = [n for n, cid in decoded['nicknames'].items() if cid == base]
                    _need(len(base_names) == 1 and base_names[0].casefold() in names,
                          'Missing variant has no on-disk original base')
        _check(cancel)
        with _parent_fd(main_path) as (directory, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                _, after_digest = _read_source(fd, cancel, progress, retain=False)
                _need(after_digest == digest, 'Main changed while reading car Lua', 'source_changed')
            finally:
                os.close(fd)
        return {'packs': dict(sorted(packs.items())), 'bodies': dict(sorted(bodies.items())),
                'paint_models': dict(sorted(paint_models.items())),
                'brake_lamps': decoded['brake_lamps'], 'character_models': decoded['character_models'],
                'model_ranges': [list(r) for r in decoded['model_ranges']],
                'source_sha256': digest, 'source_sha256_after': after_digest,
                'algorithm': ALGORITHM, 'provenance': {'lua_sources': lua_sources,
                 'nickname_table': '0x09417720', 'model_range_table': '0x09419ea0',
                 'character_model_table': '0x09419888', 'brake_mask_table': '0x0941a820',
                 'brake_file_table': '0x0941fb20', 'counts': {'nicknames': 56, 'packs': 55,
                 'model_ranges': 121, 'character_models': 64, 'mask_records': 118,
                 'lamp_records': 288}, 'absent_variants': [n for n, _ in absent]}}
    except OSError as exc:
        raise CarTableError('io_error', 'Original car table input operation failed: ' + str(exc)) from exc


def write_car_tables(main_path, car_directory, output_path, *, cancel=None, progress=None):
    """Exclusively write derived support JSON; retain newly-created partial on failure."""
    try:
        with _parent_fd(output_path) as (directory, name):
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise CarTableError('output_exists', 'Car table output already exists')
            result = build_car_tables(main_path, car_directory, cancel=cancel, progress=progress)
            payload = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            _check(cancel)
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                offset = 0
                while offset < len(payload):
                    _check(cancel)
                    n = os.write(fd, payload[offset:offset + 65536])
                    _need(n > 0, 'Car table output made no progress', 'io_error')
                    offset += n
                os.fsync(fd)
            finally:
                os.close(fd)
            return result
    except FileExistsError as exc:
        raise CarTableError('output_exists', 'Car table output was created concurrently') from exc
    except OSError as exc:
        raise CarTableError('io_error', 'Cannot write car support table: ' + str(exc)) from exc
