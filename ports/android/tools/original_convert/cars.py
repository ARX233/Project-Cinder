"""Original car component: APK-pinned plans, verified private input, owned output.

No external original root, caller receipt, old resource pack or generated table is
an execution input. This component never publishes/seals/activates a dataset.
The signed plan explicitly commits optional original absences; an unknown missing
source cannot silently select a legacy fallback. All dependencies are closed and
reverified before any scene or image decoder is invoked.
"""
from dataclasses import dataclass, field
import builtins
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import threading

from .source import (VerifiedSnapshot, ReviewedReadSet, FileTreeSource, OwnedOutput,
                     SourceEntry, OriginalInputError, ConversionCancelled, MAIN_SHA256,
                     HASH, check_cancel, source_path, _unique_object)
from .physics_image import (_parent_fd, PhysicsImageError,
                            ConversionCancelled as PhysicsCancelled)
from .car_tables import build_car_tables
from .chara_colors import derive_chara_wheel_rules, apply_chara_wheel_colors

_LOCK = threading.Lock()
_PLAN_SEAL = object()
_MISSING = object()
NAME = re.compile(r'[A-Za-z0-9_]{1,96}\Z')
BODIES = ('normal', 'aero_a', 'aero_b', 'aero_c')
_SUFFIX = {'normal': '', 'aero_a': '_aeroA', 'aero_b': '_aeroB', 'aero_c': '_aeroC'}


def _need(condition, message):
    if not condition:
        raise OriginalInputError(message)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'


@dataclass(frozen=True)
class CarTask:
    path: str
    folder: str
    kind: str
    body: str
    size: int
    sha256: str


@dataclass(frozen=True)
class CarsPlan:
    tasks: tuple
    absent_optional_sources: tuple
    sha256: str
    _seal: object = field(repr=False, compare=False)
    story_assembly: bool = False
    story_height: bytes = b''


STORY_HEIGHT_PLAN_SHA256 = '1fcd89261ea91e8d383cb90a57f840019b245384e4506ba12ac0ef7b0bbbaba7'
STORY_HEIGHT_SOURCE = SourceEntry(5875, '8892314496a325c6b5b9be0ee619461e91028f45aba0000966ad77938ac574a4')


def _height_plan(value):
    data = _canonical(value)
    _need(len(data) <= 65536 and hashlib.sha256(data).hexdigest() == STORY_HEIGHT_PLAN_SHA256,
          'Story height table is not the independently reviewed pack/raw-model lookup')
    _need(set(value) == {'schema', 'source_files', 'compiled_header_sha256', 'rows', 'raw_models', 'pack_order'} and
          value['schema'] == 'wmmt-original-story-height-v2' and
          value['source_files'] == [{'path': 'data/car_height.lua', 'bytes': STORY_HEIGHT_SOURCE.size,
                                     'sha256': STORY_HEIGHT_SOURCE.sha256}] and
          value['compiled_header_sha256'] == '4155db364fe9fe361fd5607e282db291324c7a64661b96b87aa1eb13dc42e697' and
          len(value['rows']) == 55 and len(value['raw_models']) == 247 and
          value['pack_order'] == [r['folder'] for r in value['rows']] and
          [r['pack'] for r in value['rows']] == list(range(55)) and
          [r['raw_model'] for r in value['raw_models']] == list(range(247)),
          'Story height source/header/pack/raw-model roster')
    return data


def _verify_story_height(plan, tables, reader, lua, cancel):
    if not plan.story_assembly:
        return
    value = json.loads(plan.story_height)
    _need(reader.readset.files.get('data/car_height.lua') == STORY_HEIGHT_SOURCE,
          'Story height source not bound to authenticated read-set')
    raw = reader.read('data/car_height.lua', max_bytes=5875, cancel=cancel)
    marker = b'\nfunction DefaultGet('
    _need(raw.count(marker) == 1, 'Pinned height literal/function boundary')
    # Only literal assignments are parsed. No original Lua/native execution.
    try:
        parsed = lua.Parser(raw.split(marker)[0].decode('utf-8', 'strict'), {}).chunk()
    except (ValueError, IndexError, RecursionError, UnicodeError) as exc:
        raise OriginalInputError('Invalid literal-only height configuration') from exc
    _need(set(parsed) == {'CarHeightList'} and len(parsed['CarHeightList']) == 56,
          'Original height literal inventory')
    lookup = {}
    for row in parsed['CarHeightList']:
        _need(type(row) is dict and set(row) == {'name', 'default', 'height'} and
              type(row['name']) is str and row['name'] not in lookup,
              'Original height literal duplicate/shape')
        lookup[row['name']] = row
    _need({r['folder'] for r in value['rows']} == set(tables['packs']),
          'Height lookup does not cover actual main-derived 55 packs')
    from .menu_support import OriginalSupport
    support = OriginalSupport.from_source(reader, cancel=cancel)
    _need(list(support.pack_order(tables['packs'])) == value['pack_order'],
          'Height table must retain native CARDB pack order, not lexical order')
    nick = {support.u32(0x9417724 + 8*i): support.cstr(support.u32(0x9417720 + 8*i)) for i in range(56)}
    for row in value['rows'] + value['raw_models']:
        check_cancel(cancel)
        original = lookup.get(row['native_nickname'])
        _need(row['explicit_match'] is True and original is not None and
              nick.get(row['car_id']) == row['native_nickname'] and
              original['default'] == row['default_y'] and original['height'] == row['suspension_y'],
              'Story nickname height disagrees with original literals/main')
    for row in value['raw_models']:
        _need(row['raw_model'] in tables['paint_models'][row['folder']] and
              value['pack_order'][row['pack']] == row['folder'], 'Raw-model pack ownership mismatch')
        owner = next((r for r in tables['model_ranges'] if r[1] <= row['raw_model'] <= r[2]), None)
        _need(owner is not None and owner[0] == row['car_id'], 'Raw-model native first-owner mismatch')
    # Render body-root translation only: do not change meshes, wheels, AO,
    # physics flags or any conversion task/output from this function.


def _plan_object(plan):
    value = {'schema': 'wmmt-original-cars-v1',
            'absent_optional_sources': list(plan.absent_optional_sources),
            'tasks': [{'path': task.path, 'folder': task.folder, 'kind': task.kind,
                       'body': task.body, 'bytes': task.size, 'sha256': task.sha256}
                      for task in plan.tasks]}
    if plan.story_assembly:
        value['story_assembly'] = True
        value['story_height'] = json.loads(plan.story_height)
    return value


def parse_plan(data, *, expected_sha256):
    if (type(data) is not bytes or not 1 <= len(data) <= 4 * 1024 * 1024 or
            not isinstance(expected_sha256, str) or not HASH.fullmatch(expected_sha256) or
            hashlib.sha256(data).hexdigest() != expected_sha256):
        raise OriginalInputError('Car plan must match its APK-signed recipe pin')
    try:
        value = json.loads(data.decode('utf-8', 'strict'), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(OriginalInputError('Nonfinite car-plan number')))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise OriginalInputError('Invalid car plan JSON') from exc
    _need(isinstance(value, dict) and set(value) in ({'schema', 'tasks', 'absent_optional_sources'}, {'schema', 'tasks', 'absent_optional_sources', 'story_assembly', 'story_height'}) and
          ('story_assembly' not in value or value['story_assembly'] is True) and
          value['schema'] == 'wmmt-original-cars-v1' and isinstance(value['tasks'], list) and
          len(value['tasks']) == 265 and isinstance(value['absent_optional_sources'], list) and
          len(value['absent_optional_sources']) <= 8192, 'Unsupported or incomplete original car plan')
    try:
        canonical = _canonical(value)
    except (ValueError, TypeError, RecursionError) as exc:
        raise OriginalInputError('Unrepresentable canonical car plan') from exc
    _need(canonical == data, 'Car plan is not canonical UTF-8 JSON with a final LF')
    tasks, previous, folded, identities = [], '', set(), {}
    for row in value['tasks']:
        _need(isinstance(row, dict) and set(row) == {'path', 'folder', 'kind', 'body', 'bytes', 'sha256'}, 'Invalid car task fields')
        path, folder, kind, body = row['path'], row['folder'], row['kind'], row['body']
        size, digest = row['bytes'], row['sha256']
        _need(all(isinstance(x, str) for x in (path, folder, kind, body)) and NAME.fullmatch(folder) and
              kind in ('car', 'characar') and body in BODIES and
              type(size) is int and 32 <= size <= 128 * 1024 * 1024 and
              isinstance(digest, str) and HASH.fullmatch(digest), 'Invalid car task type, identity or size')
        prefix = 'cars/' if kind == 'car' else 'chara/'
        _need(path == prefix + folder + _SUFFIX[body] + '.wpk' and
              (kind == 'car' or body == 'normal') and path > previous and path.casefold() not in folded,
              'Unsafe, unsorted, duplicate or incorrectly bound car destination')
        key = (kind, folder.casefold())
        _need(key not in identities or identities[key] == folder, 'Ambiguous folder casing in car plan')
        identities[key] = folder
        tasks.append(CarTask(path, folder, kind, body, size, digest))
        previous = path
        folded.add(path.casefold())
    normal = {task.folder for task in tasks if task.kind == 'car' and task.body == 'normal'}
    _need(len(normal) == 55 and sum(t.kind == 'car' and t.body != 'normal' for t in tasks) == 159 and
          sum(t.kind == 'characar' for t in tasks) == 51 and
          all(t.kind != 'car' or t.folder in normal for t in tasks), 'Incomplete car/stock/aero/character ownership')
    absent, previous, folded_absent = [], '', set()
    for name in value['absent_optional_sources']:
        source_path(name)
        _need(name.startswith('data/') and name > previous and name.casefold() not in folded_absent,
              'Unsafe, duplicate or unsorted optional-source absence')
        absent.append(name)
        folded_absent.add(name.casefold())
        previous = name
    for name in absent:
        prefix = name
        while '/' in prefix:
            prefix = prefix.rsplit('/', 1)[0]
            _need(prefix.casefold() not in folded_absent, 'Optional absence file/directory conflict')
    return CarsPlan(tuple(tasks), tuple(absent), expected_sha256, _PLAN_SEAL, value.get('story_assembly', False), _height_plan(value['story_height']) if value.get('story_assembly') else b'')


def _authenticate_plan(plan):
    _need(type(plan) is CarsPlan and plan._seal is _PLAN_SEAL and type(plan.story_assembly) is bool and type(plan.story_height) is bytes and
          (hashlib.sha256(plan.story_height).hexdigest() == STORY_HEIGHT_PLAN_SHA256 if plan.story_assembly else plan.story_height == b''),
          'Car conversion requires an authenticated APK-pinned plan, not caller tasks')
    _need(hashlib.sha256(_canonical(_plan_object(plan))).hexdigest() == plan.sha256,
          'Car plan changed after authentication')


def _environment(pack=None):
    _need(not any(name.startswith('WPK_') or name == 'WMMT_MAIN' for name in os.environ),
          'Car recipe forbids caller texture/ASTC/original-emulator environment overrides')
    if pack is not None:
        _need(not pack.TEX_ASTC and not pack.TEX_EXPORT and not pack.TEX_UPSCALED,
              'Car recipe forbids ASTC, export and upscaled texture globals')


def _modules():
    stage = Path(__file__).resolve().parents[1] / 'stage'
    inserted = str(stage) not in sys.path
    if inserted:
        sys.path.insert(0, str(stage))
    try:
        cars = importlib.import_module('pack_cars')
        lua = importlib.import_module('lualite')
        parts = importlib.import_module('story_part_groups')
    finally:
        if inserted:
            sys.path.remove(str(stage))
    for module, filename in ((cars, 'pack_cars.py'), (cars.pack, 'pack.py'), (lua, 'lualite.py'), (parts, 'story_part_groups.py')):
        _need(Path(module.__file__).resolve() == (stage / filename).resolve(), 'Unexpected unpackaged car converter module')
    _need(cars.MAX_TEX == 512 and cars.pack.WHEEL == 0x100, 'Car converter geometry/texture policy changed')
    return cars, lua


def _member(snapshot, name):
    source_path(name)
    expected = snapshot.readset.files.get(name)
    _need(expected is not None, 'Car source dependency is not bound by the APK read-set: ' + name)
    path = snapshot.root / name
    current = snapshot.root
    for part in name.split('/')[:-1]:
        current /= part
        info = os.lstat(current)
        _need(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode), 'Linked/nondirectory car source parent')
    info = os.lstat(path)
    _need(stat.S_ISREG(info.st_mode) and info.st_size == expected.size, 'Car source dependency is missing/nonregular/wrong length: ' + name)
    return expected


def _absent(snapshot, name):
    current = snapshot.root
    for part in name.split('/'):
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        _need(not stat.S_ISLNK(info.st_mode), 'Linked member in declared optional-source absence')
        _need(stat.S_ISDIR(info.st_mode) and current != snapshot.root / name,
              'Declared absent optional source exists or shadows a file')
    raise OriginalInputError('Declared absent optional source exists')


def _read_lua(reader, lua, name, cancel, env=None):
    raw = reader.read(name, max_bytes=2 * 1024 * 1024, cancel=cancel)
    try:
        result = lua.Parser(raw.decode('utf-8', 'replace'), dict(env or {})).chunk()
    except (ValueError, TypeError, IndexError, RecursionError, UnicodeError) as exc:
        raise OriginalInputError('Unsupported original data-only Lua: ' + name) from exc
    return result


def _table_texture(car, key, body):
    table = car.get(key)
    _need(isinstance(table, dict), 'Missing original car texture table: ' + key)
    value = table.get(body) or table.get('normal')
    _need(isinstance(value, dict) if key == 'BaseTexture' else isinstance(value, list) and value,
          'Invalid original body texture selection: ' + key)
    return value


def _reference(value):
    # Authenticated original Lua concatenates some AbsPath + '/shadow.igb'
    # values with a doubled separator. The OS treats that as the same member;
    # the signed read-set itself still requires one canonical spelling.
    _need(isinstance(value, str) and not value.startswith('/') and '\\' not in value and
          all(part not in ('.', '..') for part in value.split('/')), 'Unsafe original car reference')
    canonical = '/'.join(part for part in value.split('/') if part)
    source_path(canonical)
    _need(canonical.startswith('data/'), 'Original car dependency is outside data/')
    return canonical


def _dependencies(tasks, tables, configs, wheel_list):
    """Finite reviewed pack_car dependency grammar; no existence-based expansion."""
    mandatory = {'main', 'data/wheel_list.lua'}
    optional = {}
    by_name = {}
    for wheel in wheel_list:
        _need(isinstance(wheel, dict), 'Malformed original wheel list item')
        name = wheel.get('name')
        if not name:
            continue
        _need(isinstance(name, str) and name not in by_name, 'Ambiguous original wheel name')
        by_name[name] = wheel
    def required(path):
        mandatory.add(_reference(path))
    def maybe(path, reason):
        optional.setdefault(_reference(path), set()).add(reason)
    for task in tasks:
        lua_path = f'data/{task.kind}/{task.folder}/car.lua'
        mandatory.add(lua_path)
        car = configs[lua_path]
        bodies, tire = car.get('BodyIGB'), car.get('TireStatus')
        _need(isinstance(bodies, dict) and isinstance(bodies.get(task.body), str) and isinstance(tire, dict) and
              isinstance(tire.get('file'), list) and tire['file'] and isinstance(tire.get('wheel_name'), str),
              'Incomplete original body/tire model definition')
        required(bodies[task.body])
        required(tire['file'][0])
        wheel = by_name.get(tire['wheel_name'])
        _need(wheel is not None, 'Original car refers to an unknown wheel identity')
        if wheel.get('igb_files'):
            _need(isinstance(wheel['igb_files'], list), 'Invalid original wheel IGB selection')
            required(wheel['igb_files'][-1])
        shadow = car.get('ShadowIGB', {})
        _need(isinstance(shadow, dict), 'Invalid original shadow model map')
        if shadow.get(task.body):
            required(shadow[task.body])
        car_id = tables['brake_lamps']['cars'].get(task.folder)
        if car_id is None:
            folded = [v for k, v in tables['brake_lamps']['cars'].items() if k.casefold() == task.folder.casefold()]
            _need(len(folded) == 1, 'Original lamp identity is ambiguous')
            car_id = folded[0]
        body_code = BODIES.index(task.body)
        lamp = tables['brake_lamps']['lamps'].get(f'{car_id} {body_code}')
        if lamp:
            maybe('data/car/brakelamp/brakelamp_' + lamp[0] + '.igb', 'pack_car:352 optional main-derived brake-lamp IGB')
        base = _table_texture(car, 'BaseTexture', task.body)
        paints = _table_texture(car, 'BodyColorTexture', task.body)
        count = tables['packs'][task.folder] if task.kind == 'car' else 1
        _need(type(count) is int and 1 <= count <= len(paints) and all(isinstance(p, dict) for p in paints[:count]),
              'Original main paint ownership exceeds selected Lua paint availability')
        for key, value in base.items():
            if not value:
                continue
            _need(isinstance(key, str) and isinstance(value, str), 'Invalid original base texture identity')
            if paints[0].get(key):
                maybe(paints[0][key], 'pack.collect:add:307-310 first-paint file; missing uses original IGB image')
            for paint in paints[1:count]:
                if paint.get(key) and paint[key] != paints[0].get(key):
                    maybe(paint[key], 'pack_car:370 additional-paint file; missing retains base paint')
    _need(not mandatory.intersection(optional), 'Ambiguous mandatory/optional dependency role')
    return mandatory, optional


def _bind_receipts(snapshot, receipts):
    for row in receipts:
        _need(isinstance(row, dict) and set(row) >= {'path', 'bytes', 'sha256'}, 'Invalid derived car source receipt')
        expected = snapshot.readset.files.get(row['path'])
        _need(expected is not None and expected.size == row['bytes'] and expected.sha256 == row['sha256'],
              'Derived original support is not bound by the APK read-set')


def _closure(snapshot, plan, mandatory, optional):
    absent = set(plan.absent_optional_sources)
    _need(absent <= set(optional), 'Plan declares an unused or unknown optional-source absence')
    folded_present = {name.casefold() for name in snapshot.readset.files}
    _need(not any(name.casefold() in folded_present for name in absent), 'Optional absence contradicts authenticated source read-set')
    for name in sorted(absent):
        _absent(snapshot, name)
    expected_present = mandatory | (set(optional) - absent)
    for name in sorted(expected_present):
        _member(snapshot, name)
    return expected_present


def _exclusive_open(expected, file, mode='r', *args, **kwargs):
    _need(mode == 'wb' and not args and not kwargs and os.fspath(file) == os.fspath(expected),
          'Car writer attempted an unowned destination or unsupported open mode')
    with _parent_fd(expected) as (directory, name):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    return os.fdopen(fd, 'wb')


def _digest(path, expected, cancel):
    digest, count = hashlib.sha256(), 0
    with _parent_fd(path) as (directory, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    try:
        before = os.fstat(fd)
        _need(stat.S_ISREG(before.st_mode) and before.st_size == expected.size, 'Converted car has wrong file type or size')
        first = True
        while True:
            check_cancel(cancel)
            block = os.read(fd, 128 * 1024)
            if not block:
                break
            if first:
                _need(block[:4] == b'WPK3', 'Converted car is not a WPK3 resource')
                first = False
            digest.update(block)
            count += len(block)
        after = os.fstat(fd)
        _need(count == expected.size and digest.hexdigest() == expected.sha256 and
              (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
              (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Converted car differs from APK-signed output plan')
    finally:
        os.close(fd)


def convert_cars(snapshot, output, tasks, *, cancel=None, progress=None):
    _need(type(snapshot) is VerifiedSnapshot and type(output) is OwnedOutput and
          isinstance(snapshot.readset, ReviewedReadSet) and snapshot.bytes == snapshot.readset.total_bytes,
          'Car conversion requires a complete verified private snapshot and new owned output')
    _authenticate_plan(tasks)
    check_cancel(cancel)
    _need(_LOCK.acquire(False), 'Original car converter is already running')
    try:
        return _convert(snapshot, output, tasks, cancel, progress)
    except PhysicsCancelled as exc:
        raise ConversionCancelled('Original car conversion cancelled') from exc
    except PhysicsImageError as exc:
        raise OriginalInputError('Original car source support rejected: ' + str(exc)) from exc
    except OSError as exc:
        if isinstance(exc, OriginalInputError):
            raise
        raise OriginalInputError('Original car I/O failed: ' + str(exc)) from exc
    finally:
        _LOCK.release()


def _convert(snapshot, output, plan, cancel, progress):
    _environment()
    cars, lua = _modules()
    pack = cars.pack
    _environment(pack)
    old_fix, old_brakes, old_ids = cars.fix_stock_wheel_bgr, cars.BRAKE_LAMPS, cars.CAR_IDS
    old_open = getattr(pack, 'open', _MISSING)
    current_target = [None]
    try:
        check_cancel(cancel)
        _need(snapshot.readset.files.get('main', SourceEntry(0, '')).sha256 == MAIN_SHA256,
              'Authenticated car snapshot does not bind the reviewed main')
        initial = {'main', 'data/wheel_list.lua'} | {f'data/{t.kind}/{t.folder}/car.lua' for t in plan.tasks}
        for name in initial:
            _member(snapshot, name)
        targets = {}
        for task in plan.tasks:
            _need(task.path not in output.files, 'Car output already belongs to a prior component')
            targets[task.path] = output.target(task.path)
        with FileTreeSource(snapshot.root, snapshot.readset) as reader:
            # Literal-only metadata lane. No IGB/texture decoder runs here.
            for name in sorted(initial):
                if name == 'main':
                    for _ in reader.chunks(name, cancel=cancel):
                        pass
            configs = {name: _read_lua(reader, lua, name, cancel) for name in sorted(initial) if name.endswith('/car.lua')}
            wheels = _read_lua(reader, lua, 'data/wheel_list.lua', cancel, {'AbsPath': 'data/'})
            _need(isinstance(wheels.get('WheelList'), list), 'Original wheel list is invalid')
            tables = build_car_tables(snapshot.root / 'main', snapshot.root / 'data/car', cancel=cancel)
            expected = {(folder, body) for folder, bodies in tables['bodies'].items() for body in bodies}
            actual = {(t.folder, t.body) for t in plan.tasks if t.kind == 'car'}
            _need(len(tables['packs']) == 55 and len(expected) == 214 and actual == expected,
                  'Car plan does not close all original-main 55 stock and 159 aero bodies')
            chara = [t.folder for t in plan.tasks if t.kind == 'characar']
            models = tables['character_models']
            _need(len(chara) == 51 and all(sum(k.casefold() == name.casefold() for k in models) == 1 for name in chara),
                  'Character plan lacks unique pinned-main identities')
            lua_sources = tables['provenance']['lua_sources']
            _need(set(lua_sources) == {folder + '/car.lua' for folder in tables['packs']},
                  'Original car Lua provenance does not close the selected stock folders')
            lua_receipts = [{'path': 'data/car/' + relative, **row}
                            for relative, row in lua_sources.items()]
            _bind_receipts(snapshot, lua_receipts)
            mandatory, optional = _dependencies(plan.tasks, tables, configs, wheels['WheelList'])
            if plan.story_assembly:
                mandatory.add('data/car_height.lua')
                _verify_story_height(plan, tables, reader, lua, cancel)
            present = _closure(snapshot, plan, mandatory, optional)
            # Every potential source read is authenticated before any decoder, even
            # if the caller's snapshot is a larger union used by other components.
            for name in sorted(present - initial):
                for _ in reader.chunks(name, cancel=cancel):
                    pass
        from .runtime_check import validate_runtime
        runtime = validate_runtime()
        check_cancel(cancel)
        rules = derive_chara_wheel_rules(snapshot.root / 'main', snapshot.root, chara, cancel=cancel)
        for rule in rules.values():
            _bind_receipts(snapshot, rule.receipt()['source_receipts'])
        cars.configure_brake_lamps(tables['brake_lamps'])
        hook_receipts = []
        def finish_colors(folder, kind, wheel, textures, meshes):
            old_fix(folder, kind, wheel, textures, meshes)
            if kind == 'characar':
                hook_receipts.append(apply_chara_wheel_colors(folder, kind, wheel, textures, meshes, rules[folder]))
        cars.fix_stock_wheel_bgr = finish_colors
        pack.open = lambda file, mode='r', *a, **kw: _exclusive_open(current_target[0], file, mode, *a, **kw)
        completed = []
        for index, task in enumerate(plan.tasks):
            check_cancel(cancel)
            destination = output.target(task.path)
            _need(destination == targets[task.path], 'Owned car output destination changed')
            current_target[0] = destination
            paints = tables['packs'][task.folder] if task.kind == 'car' else 1
            if plan.story_assembly and task.kind == 'car':
                cars.pack_car(str(snapshot.root), task.folder, paints, wheels['WheelList'], str(destination),
                              kind=task.kind, body=task.body, story_assembly=True)
            else:
                cars.pack_car(str(snapshot.root), task.folder, paints, wheels['WheelList'], str(destination),
                              kind=task.kind, body=task.body)
            check_cancel(cancel)
            expected_file = SourceEntry(task.size, task.sha256)
            _digest(destination, expected_file, cancel)
            output.files[task.path] = expected_file
            completed.append({'path': task.path, 'bytes': task.size, 'sha256': task.sha256})
            if progress:
                progress('convert-cars', index + 1, len(plan.tasks))
        _need(len(completed) == 265 and len(hook_receipts) == 51, 'Car component conversion is incomplete')
        return {'component': 'cars', 'coverage': 'complete-component', 'plan_sha256': plan.sha256,
                'source_readset_sha256': snapshot.readset.sha256, 'files': completed,
                'normal': 55, 'aero': 159, 'chara': 51, 'runtime_selfcheck': runtime,
                'optional_absences': [{'path': name, 'reasons': sorted(optional[name])} for name in plan.absent_optional_sources],
                'source_dependency_count': len(present), 'chara_rule_ids': {name: rule.rule_id for name, rule in rules.items()},
                'complete_dataset': False, 'activated': False}
    finally:
        cars.fix_stock_wheel_bgr, cars.BRAKE_LAMPS, cars.CAR_IDS = old_fix, old_brakes, old_ids
        if old_open is _MISSING:
            if hasattr(pack, 'open'):
                delattr(pack, 'open')
        else:
            pack.open = old_open
