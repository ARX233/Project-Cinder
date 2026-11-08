"""Reconstruct the menu's complete cars.json schema from the reviewed original.

No x86/Lua is executed.  The model-data switch is compiled into constant-field
assignment records and direct graph edges; those records are composed as data.
Only C7 absolute immediates and unconditional joins are accepted in case bodies.
Maker cases likewise become constant lists plus reviewed selector overrides.
Unknown opcodes/control flow, malformed tables, and unpinned mains fail closed.

The hidden-page labels/colour names and text-sprite numbering are authored port
UI compatibility rules from tools/cardb.py, not historical generated results.
All model metadata, maker order, hidden IDs, horsepower and physics types come
from original ELF bytes.  Original car.lua is parsed as bounded data only to
verify each emitted folder's paint coverage.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct

from .physics_image import Elf32, SOURCE_SHA256, PhysicsImageError, ConversionCancelled, _check, _parent_fd, _read_source
from .car_tables import _decode_main, _model_car, _cstring, _read_lua, _paint_count

ALGORITHM = '3dxplus-static-menu-car-data-v1'
TEXT_FIRST = 100002
MAKERS = ('GEMBALLA', 'MAZDA', 'MITSUBISHI', 'NISSAN', 'SUBARU', 'TOYOTA')
SPEED_GEARS = {3824: 4, 3825: 5, 3826: 6}
# These three labels and two disambiguations are port UI policy, not game bytes.
HIDDEN_COLOR = {43: '個人タクシー', 52: '個人タクシー', 51: '教習車'}
HIDDEN_LABEL = {50: 'TOYOTA HIACE HIGH LIFT', 51: 'Mazda Mazdaspeed Atenza [GG3P]（教習車仕様）'}
MODEL_BASE = 0x97FF7E0
MODEL_LIMIT = 0x97FF86C
MODEL_FUNCTION = (0x88DC0C8, 0x88E5747)
MAKER_BASE = 0x97FFA20
MAKER_RETURN = 0x88EC191
MAKER_FUNCTION = (0x88EC10F, 0x88EC50A)


class MenuCarDataError(PhysicsImageError):
    pass


def _need(ok, message, code='unsupported_menu_car_data'):
    if not ok:
        raise MenuCarDataError(code, message)


def _shape(elf, address, prefix):
    _need(elf.code(address, len(prefix)) == prefix, 'Unsupported menu-car encoding at ' + hex(address))


def _operand(elf, address, prefix, width=4):
    _shape(elf, address, prefix)
    return int.from_bytes(elf.code(address + len(prefix), width), 'little')


def _jump(elf, address, opcode=b'\xe9'):
    _shape(elf, address, opcode)
    width = 1 if opcode in (b'\xeb', b'\x77') else 4
    return address + len(opcode) + width + int.from_bytes(elf.code(address + len(opcode), width), 'little', signed=True)


def _pinned(elf, cancel=None):
    _check(cancel)
    _need(isinstance(elf, Elf32), 'An Elf32 reader is required', 'invalid_source')
    _need(hashlib.sha256(elf.data).hexdigest() == SOURCE_SHA256, 'Unsupported main SHA-256', 'unsupported_source')


def _store_record(elf, address, store_base, store_limit):
    _shape(elf, address, b'\xc7\x05')
    target, value = struct.unpack('<II', elf.code(address + 2, 8))
    _need(store_base <= target <= store_limit - 4 and (target - store_base) % 4 == 0,
          'Constant field is outside the reviewed result record')
    return target, value


def _constant_records(elf, start, *, function_range, store_range, terminal, cancel=None):
    """Decode a finite constant-assignment DAG into records, never CPU state.

    There is no register file, stack, emulated memory, callable target, indirect
    branch execution, or input-dependent branch evaluator.  Only absolute
    constant assignments and direct joins may lead to the declared terminal.
    """
    records, seen = [], set()
    coordinate = start
    lo, hi = function_range
    for _ in range(256):
        _check(cancel)
        if coordinate == terminal:
            return records
        _need(lo <= coordinate and coordinate + 2 <= hi and coordinate not in seen,
              'Cyclic or out-of-range constant-case graph')
        seen.add(coordinate)
        if elf.code(coordinate, 2) == b'\xc7\x05':
            _need(coordinate + 10 <= hi, 'Constant assignment crosses function bounds')
            records.append(_store_record(elf, coordinate, *store_range))
            coordinate += 10
        elif elf.code(coordinate, 1) == b'\xe9':
            _need(coordinate + 5 <= hi, 'Direct join crosses function bounds')
            coordinate = _jump(elf, coordinate)
        else:
            raise MenuCarDataError('unsupported_menu_car_data', 'Nonconstant case semantics at ' + hex(coordinate))
    raise MenuCarDataError('unsupported_menu_car_data', 'Constant-case graph budget exceeded')


def _decode_models(elf, cancel=None):
    _need(_operand(elf, 0x88DC132, b'\x3d') == 246, 'Unknown menu model dispatch bound')
    table = _operand(elf, 0x88DC1CF, b'\xff\x24\x85')
    _need(table == 0x940ED98 and _jump(elf, 0x88DC1CD, b'\x77') == 0x88DC1D6,
          'Unknown menu model switch table')
    _shape(elf, 0x88DC316, b'\xc9\xb8')
    _need(int.from_bytes(elf.code(0x88DC318, 4), 'little') == MODEL_BASE,
          'Unexpected model record return address')
    _shape(elf, 0x88DC31C, b'\xc3')
    # Decode common default assignments before the dispatch; skip only exact
    # compiler prologue/argument/guard encodings with no result-record effect.
    prologue_shapes = {0x88DC0C8: b'\x55', 0x88DC0E7: b'\x89\xe5',
                       0x88DC0FD: b'\x8b\x45\x08', 0x88DC132: b'\x3d\xf6\x00\x00\x00'}
    coordinate, common = MODEL_FUNCTION[0], []
    while coordinate < 0x88DC1CD:
        _check(cancel)
        prefix = prologue_shapes.get(coordinate)
        if prefix:
            _shape(elf, coordinate, prefix)
            coordinate += len(prefix)
        else:
            common.append(_store_record(elf, coordinate, MODEL_BASE, MODEL_LIMIT))
            coordinate += 10
    _need(coordinate == 0x88DC1CD, 'Malformed model switch prologue')
    targets = struct.unpack('<247I', elf.read(table, 247 * 4))
    _need(len(set(targets)) == 247, 'Unexpected menu model case identity')
    out = []
    for target in targets:
        records = common + _constant_records(elf, target, function_range=MODEL_FUNCTION,
                      store_range=(MODEL_BASE, MODEL_LIMIT), terminal=0x88DC316, cancel=cancel)
        fields = dict(records)
        required = [MODEL_BASE + index * 4 for index in range(12)]
        _need(all(at in fields for at in required), 'Menu case leaves a required field unknown')
        row = [fields[at] for at in required]
        _need(row[7] in SPEED_GEARS, 'Unknown forward-gear sprite')
        for at in row[:3]:
            if at:
                _cstring(elf, at, 1024)
        out.append(row)
    return out, {'model_jump_table': hex(table), 'model_case_count': len(targets),
                 'common_assignment_records': len(common), 'model_result_base': hex(MODEL_BASE)}


def decode_car_model_data(elf, *, cancel=None):
    """Pinned ELF helper: 247 lists of the 12 original get_car_model_data words."""
    _pinned(elf, cancel)
    return _decode_models(elf, cancel)[0]


def _list_fields(elf, start, cancel=None):
    fields, coordinate = {}, start
    for _ in range(32):
        _check(cancel)
        if elf.code(coordinate, 2) != b'\xc7\x05':
            return fields, coordinate
        target, value = _store_record(elf, coordinate, MAKER_BASE, MAKER_BASE + 52)
        fields[target] = value
        coordinate += 10
    raise MenuCarDataError('unsupported_menu_car_data', 'Maker constant-run budget exceeded')


def _maker_values(fields):
    _need(MAKER_BASE in fields, 'Maker list has no count')
    count = fields[MAKER_BASE]
    _need(1 <= count <= 12 and all(MAKER_BASE + 4 * i in fields for i in range(1, 13)),
          'Incomplete maker list fields')
    values = [fields[MAKER_BASE + 4 * i] for i in range(1, count + 1)]
    _need(all(0 <= value < 56 for value in values) and len(set(values)) == len(values) and
          all(fields[MAKER_BASE + 4 * i] == 0xFFFFFFFF for i in range(count + 1, 13)),
          'Invalid maker car identity or padding')
    return values


def _decode_makers(elf, cancel=None):
    _shape(elf, 0x88EC0FF, b'\x83\xfb\x05')
    table = _operand(elf, 0x88EC108, b'\xff\x24\x9d')
    _need(table == 0x94109B0, 'Unknown maker dispatch table')
    _shape(elf, MAKER_RETURN, b'\x8b\x5d\xf8\x8b\x75\xfc\xb8')
    _need(int.from_bytes(elf.code(0x88EC198, 4), 'little') == MAKER_BASE, 'Unexpected maker result address')
    _shape(elf, 0x88EC19C, b'\xc9\xc3')
    targets = struct.unpack('<6I', elf.read(table, 24))
    normal, hidden = [], {}
    for maker, start in enumerate(targets):
        _check(cancel)
        selector = None
        if elf.code(start, 2) == b'\x83\xfe':
            selector = _operand(elf, start, b'\x83\xfe', 1)
            start += 3
        fields, end = _list_fields(elf, start, cancel)
        prefix = elf.code(end, 2)
        if end == MAKER_RETURN:
            overrides = {}
        elif prefix[:1] == b'\xe9':
            fields.update(_constant_records(elf, _jump(elf, end), function_range=MAKER_FUNCTION,
                          store_range=(MAKER_BASE, MAKER_BASE + 52), terminal=MAKER_RETURN, cancel=cancel))
            overrides = {}
        elif prefix == b'\x0f\x85':
            _need(selector is not None and _jump(elf, end, prefix) == MAKER_RETURN,
                  'Unknown maker equality override')
            overrides = {selector: _constant_records(elf, end + 6, function_range=MAKER_FUNCTION,
                         store_range=(MAKER_BASE, MAKER_BASE + 52), terminal=MAKER_RETURN, cancel=cancel)}
        elif prefix == b'\x0f\x87':
            _need(selector is not None and selector < 8 and _jump(elf, end, prefix) == MAKER_RETURN,
                  'Unknown maker selector range')
            second = _operand(elf, end + 6, b'\xff\x24\xb5')
            _need(second == 0x94109C8, 'Unknown hidden maker switch table')
            overrides = {i: _constant_records(elf, target, function_range=MAKER_FUNCTION,
                         store_range=(MAKER_BASE, MAKER_BASE + 52), terminal=MAKER_RETURN, cancel=cancel)
                         for i, target in enumerate(struct.unpack('<' + 'I' * (selector + 1), elf.read(second, 4 * (selector + 1))))}
        else:
            raise MenuCarDataError('unsupported_menu_car_data', 'Unknown maker case edge at ' + hex(end))
        baseline = _maker_values(fields)
        normal.append(baseline)
        for index, records in overrides.items():
            amended = dict(fields)
            amended.update(records)
            values = _maker_values(amended)
            added = [car for car in values if car not in baseline]
            if not added:
                continue
            _need(len(added) == 1 and index not in hidden, 'Ambiguous hidden car selector')
            hidden[index] = {'maker': maker, 'car': added[0]}
    _need(set(hidden) == set(range(8)), 'Incomplete hidden maker selectors')
    return normal, [hidden[i] for i in range(8)]


def decode_maker_lists(elf, *, cancel=None):
    """Pinned ELF helper: six normal lists plus eight hidden {maker,car} rows."""
    _pinned(elf, cancel)
    normal, hidden = _decode_makers(elf, cancel)
    return {'normal': normal, 'hidden': hidden}


def _physics_types(elf, cancel=None):
    base = _operand(elf, 0x893CD6D, b'\xba')
    outbase = _operand(elf, 0x893CD72, b'\xb8')
    count = _operand(elf, 0x893CE0B, b'\x81\xfe')
    stride = _operand(elf, 0x893CD8A, b'\x83\xc0', 1)
    _shape(elf, 0x893CD80, b'\x39\x5a\x0c')
    _shape(elf, 0x893CE22, b'\x8b\x00\xc9\xc3')
    _need((base, outbase, count, stride) == (0x9418160, 0x9418168, 311, 24), 'Unknown physics-type table geometry')
    types = {}
    for index in range(count):
        _check(cancel)
        row = struct.unpack('<6I', elf.read(base + index * stride, stride))
        if row[3] < 120:
            _need(row[2] < 256, 'Unknown physics-type identity')
            types.setdefault(row[3], row[2])
    return types


def _horsepower(elf, car):
    _need(_operand(elf, 0x856875D, b'\xc7\x44\x24\x04') == 1 and
          _jump(elf, 0x8568768, b'\xe8') == 0x893DD48, 'Unknown GetCarData model-to-car semantics')
    table = _operand(elf, 0x856876D, b'\x8b\x04\x85')
    _need(table == 0x9736980 and 0 <= car < 120, 'Unknown horsepower pointer table')
    pointer = int.from_bytes(elf.read(table + 4 * car, 4), 'little')
    hp = int.from_bytes(elf.read(pointer + 0x20, 4), 'little')
    _need(1 <= hp <= 10000, 'Invalid stock horsepower')
    return hp


def _disk_names(car_directory, cancel=None):
    root = Path(car_directory)
    names, folded = {}, set()
    with _parent_fd(root / '_not_opened') as (directory, _):
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                _check(cancel)
                _need(index < 1024 and entry.name.casefold() not in folded, 'Ambiguous/oversized original car directory', 'invalid_source')
                folded.add(entry.name.casefold())
                if entry.is_dir(follow_symlinks=False):
                    names[entry.name.casefold()] = entry.name
    return names


def from_elf(elf, car_directory, *, cancel=None, progress=None):
    """Produce full makers/texts/packs schema from a pinned shared Elf32 reader."""
    _pinned(elf, cancel)
    def step(phase, current, total=4):
        _check(cancel)
        if progress:
            progress(phase, current, total)
    step('decode_menu_model_records', 0)
    models, model_provenance = _decode_models(elf, cancel)
    step('decode_menu_maker_lists', 1)
    normal, hidden = _decode_makers(elf, cancel)
    decoded = _decode_main(elf, cancel)
    folders = {car: name for name, car in decoded['nicknames'].items()}
    ranges = {}
    for car, first, last, _, _ in decoded['model_ranges']:
        ranges.setdefault(car, (first, last))
    disk = _disk_names(car_directory, cancel)
    for item in hidden:
        car = item['car']
        folders[car] = disk.get(folders[car].casefold(), folders[car])
    types = _physics_types(elf, cancel)
    step('compose_menu_car_records', 2)
    texts, packs, makers = [], {}, []
    for maker, ids in enumerate(normal + [[r['car'] for r in hidden]]):
        cars = []
        for car_id in ids:
            _check(cancel)
            _need(car_id in ranges, 'Maker car has no model range')
            first, last = ranges[car_id]
            _need(0 <= first <= last < len(models), 'Menu car model is outside dispatch table')
            colors = []
            for model in range(first, last + 1):
                v = models[model]
                name = _cstring(elf, v[2], 1024) if v[2] else ''
                if not name and maker == 6:
                    name = HIDDEN_COLOR.get(car_id, '')
                if not name:
                    continue
                car = _model_car(decoded['model_ranges'], model, True)
                base = _model_car(decoded['model_ranges'], model, False)
                owner = car if folders[car].casefold() in disk else base
                _need(owner in folders and folders[owner].casefold() in disk, 'Menu paint has no original owner folder')
                folder = disk[folders[owner].casefold()]
                paint = len(packs.setdefault(folder, []))
                ctype = types.get(car, 0) or types.get(base, 0)
                if not ctype and folders[car].casefold().endswith('_taxi'):
                    # Port's Aristo-taxi policy, but derive its type from the
                    # original non-taxi car record instead of embedding 32.
                    ordinary = folders[car].casefold()[:-5]
                    ordinary_ids = [cid for cid, name_ in folders.items() if name_.casefold() == ordinary]
                    _need(len(ordinary_ids) == 1, 'Taxi has no original non-taxi physics identity')
                    ctype = types.get(ordinary_ids[0], 0)
                _need(ctype > 0, 'Unknown physics type for menu paint')
                if name not in texts:
                    texts.append(name)
                packs[folder].append(model)
                colors.append({'model': model, 'name': name, 'text': TEXT_FIRST + texts.index(name),
                               'swatch': v[3], 'folder': folder, 'paint': paint, 'type': ctype,
                               'gears': SPEED_GEARS[v[7]]})
            v = models[first]
            lines = [_cstring(elf, v[i], 1024) if v[i] else '' for i in (0, 1)]
            label = HIDDEN_LABEL.get(car_id, f'{lines[0].strip()} {lines[1]}') if maker == 6 else f'{lines[0].strip()} {lines[1]}'
            model_car = _model_car(decoded['model_ranges'], first, True)
            cars.append({'car': car_id, 'folder': folders[car_id], 'label': label, 'lines': lines,
                         'logo': v[5], 'drive': v[6], 'speed': v[7], 'bglogo': v[9],
                         'plate': v[11], 'hp': _horsepower(elf, model_car), 'colors': colors})
        makers.append({'name': (MAKERS + ('HIDDEN',))[maker], 'cars': cars})
    hidden_packs = [car['folder'] for car in makers[6]['cars']]
    order = sorted(folder for folder in packs if folder not in hidden_packs) + hidden_packs
    _need(len(order) == len(set(order)) == 55 and set(order) == set(packs), 'Unknown menu pack ABI coverage')
    step('verify_original_lua_paint_coverage', 3)
    lua_sources = {}
    for index, folder in enumerate(order):
        _check(cancel)
        car, source = _read_lua(Path(car_directory) / folder / 'car.lua', cancel)
        _need(1 <= len(packs[folder]) <= _paint_count(car), 'Menu paint count exceeds original Lua coverage')
        lua_sources[folder + '/car.lua'] = source
        if progress:
            progress('menu_car_lua', index + 1, len(order))
    step('menu_car_data_complete', 4)
    return {'makers': makers, 'texts': texts, 'packs': {folder: len(packs[folder]) for folder in order},
            'pack_order': order, 'source_sha256': SOURCE_SHA256, 'algorithm': ALGORITHM,
            'provenance': {**model_provenance, 'maker_jump_table': '0x094109b0',
             'hidden_jump_table': '0x094109c8', 'hidden_selectors': hidden,
             'horsepower_pointer_table': '0x09736980', 'horsepower_field_offset': 0x20,
             'physics_type_table': '0x09418160', 'lua_sources': lua_sources,
             'port_ui_policy': 'hidden labels/unnamed colors and text numbering; taxi type derived from original base car'}}


def build_menu_car_data(main_path, car_directory, *, cancel=None, progress=None):
    """Path API; no old JSON/header/expected-pin override accepted."""
    _check(cancel)
    try:
        with _parent_fd(main_path) as (directory, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                raw, before = _read_source(fd, cancel, progress, retain=True)
                _need(before == SOURCE_SHA256, 'Unsupported main SHA-256', 'unsupported_source')
                out = from_elf(Elf32(raw, cancel), car_directory, cancel=cancel, progress=progress)
                _, after = _read_source(fd, cancel, progress, retain=False)
                _need(before == after, 'Main changed during menu reconstruction', 'source_changed')
                held, named = os.fstat(fd), os.stat(name, dir_fd=directory, follow_symlinks=False)
                _need((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino), 'Main path was replaced', 'source_changed')
            finally:
                os.close(fd)
        out['source_sha256_after'] = after
        return out
    except OSError as exc:
        raise MenuCarDataError('io_error', 'Cannot read original menu-car inputs: ' + str(exc)) from exc


def write_menu_car_data(main_path, car_directory, output_path, *, cancel=None, progress=None):
    """Exclusively create derived JSON; retain a newly-created partial on failure."""
    try:
        with _parent_fd(output_path) as (directory, name):
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise MenuCarDataError('output_exists', 'Menu car output already exists')
            out = build_menu_car_data(main_path, car_directory, cancel=cancel, progress=progress)
            payload = (json.dumps(out, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
            _check(cancel)
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            try:
                offset = 0
                while offset < len(payload):
                    _check(cancel)
                    n = os.write(fd, payload[offset:offset + 65536])
                    _need(n > 0, 'Output write made no progress', 'io_error')
                    offset += n
                os.fsync(fd)
            finally:
                os.close(fd)
        return out
    except FileExistsError as exc:
        raise MenuCarDataError('output_exists', 'Menu car output was created concurrently') from exc
    except OSError as exc:
        raise MenuCarDataError('io_error', 'Cannot write menu car data: ' + str(exc)) from exc
