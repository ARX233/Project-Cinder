"""Original Lua/IGB/TGA wheel conversion, within a verified private job.

The wheel output plan is release metadata. No old APK or runtime payload is an
input. This component does not seal or activate a complete game dataset.
"""
from dataclasses import dataclass
import hashlib
import json
import re
from .source import (ReviewedReadSet, VerifiedSnapshot, OwnedOutput, SourceEntry,
                     OriginalInputError, HASH, check_cancel, source_path, _unique_object)


@dataclass(frozen=True)
class WheelTask:
    path: str
    kind: str
    name: str
    texture_set: int
    size: int
    sha256: str


def parse_plan(data, *, expected_sha256):
    if (not isinstance(data, bytes) or not 1 <= len(data) <= 128 * 1024 or
            not isinstance(expected_sha256, str) or not HASH.fullmatch(expected_sha256) or
            hashlib.sha256(data).hexdigest() != expected_sha256):
        raise OriginalInputError('Wheel plan must match the signed recipe pin')
    try:
        plan = json.loads(data.decode('utf-8', 'strict'), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise OriginalInputError('Invalid wheel plan JSON') from exc
    if (not isinstance(plan, dict) or set(plan) != {'schema', 'tasks'} or
            plan['schema'] != 'wmmt-original-wheels-v1' or not isinstance(plan['tasks'], list) or
            not 1 <= len(plan['tasks']) <= 149):
        raise OriginalInputError('Unsupported wheel plan')
    result, previous, keys = [], '', set()
    for row in plan['tasks']:
        if not isinstance(row, dict) or set(row) != {'path','kind','name','texture_set','bytes','sha256'}:
            raise OriginalInputError('Invalid wheel task')
        path, kind, name = row['path'], row['kind'], row['name']
        texture, size, digest = row['texture_set'], row['bytes'], row['sha256']
        if (not isinstance(path, str) or not re.fullmatch(r'wheels/[A-Za-z0-9_]+\.wpk', path) or
                not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,96}', name) or
                kind not in ('menu','custom') or type(texture) is not int or not 0 <= texture <= 31 or
                type(size) is not int or not 32 <= size <= 64 * 1024 * 1024 or
                not isinstance(digest, str) or not HASH.fullmatch(digest) or
                path <= previous or path.casefold() in keys):
            raise OriginalInputError('Unsafe, duplicate or invalid wheel task')
        expected_name = name if kind == 'menu' else name + '_' + str(texture)
        if path != 'wheels/' + expected_name + '.wpk' or (kind == 'menu' and texture != 0):
            raise OriginalInputError('Wheel plan/name binding mismatch')
        result.append(WheelTask(path,kind,name,texture,size,digest))
        previous = path
        keys.add(path.casefold())
    return tuple(result)


def _digest_file(path, *, cancel=None):
    digest, count = hashlib.sha256(), 0
    with path.open('rb') as f:
        while True:
            check_cancel(cancel)
            b = f.read(128 * 1024)
            if not b:
                break
            digest.update(b)
            count += len(b)
    return count, digest.hexdigest()


def convert_wheels(snapshot, output, tasks, *, cancel=None, progress=None):
    if not isinstance(snapshot, VerifiedSnapshot) or not isinstance(output, OwnedOutput):
        raise OriginalInputError('Wheel conversion requires a verified snapshot and a new owned output')
    if not isinstance(tasks, tuple) or not tasks or any(not isinstance(t,WheelTask) for t in tasks):
        raise OriginalInputError('An authenticated wheel task plan is required')
    check_cancel(cancel)
    # These are trusted packaged modules. Never append a player/source directory to
    # sys.path, evaluate Lua, start subprocesses or use host ASTC/upscale overrides.
    import pack_cars
    import lualite
    pack = pack_cars.pack
    if pack.TEX_EXPORT or pack.TEX_UPSCALED or pack.TEX_ASTC:
        raise OriginalInputError('This recipe forbids external texture overrides or ASTC commands')
    lua_path = 'data/wheel_list.lua'
    if lua_path not in snapshot.readset.files:
        raise OriginalInputError('Wheel list is not bound by the original read-set')
    lua = lualite.load(str(snapshot.root / lua_path), {'AbsPath':'data/'})
    if not isinstance(lua.get('WheelList'), list):
        raise OriginalInputError('Original wheel list is invalid')
    by_name = {}
    for wheel in lua['WheelList']:
        if not isinstance(wheel,dict) or not wheel.get('name'):
            continue
        name = wheel['name']
        if name in by_name:
            raise OriginalInputError('Ambiguous original wheel identity')
        by_name[name] = wheel
    result = []
    for index, task in enumerate(tasks):
        check_cancel(cancel)
        if task.kind == 'custom':
            wheel = by_name.get(task.name)
            if wheel is None or not isinstance(wheel.get('igb_files'),list) or not wheel['igb_files']:
                raise OriginalInputError('Required original custom wheel is missing')
            paths = [wheel['igb_files'][-1]]
            textures = wheel.get('texture') or []
            if task.texture_set >= len(textures) or not textures[task.texture_set]:
                raise OriginalInputError('Required original wheel texture set is missing')
            paths.append(textures[task.texture_set][-1])
        else:
            wheel = None
            paths = ['data/menu3d/wheel/' + task.name + '.igb']
        for path in paths:
            source_path(path)
            if path not in snapshot.readset.files:
                raise OriginalInputError('Wheel dependency is not authorized by this recipe')
        destination = output.target(task.path)
        if task.kind == 'menu':
            pack_cars.pack_menu_wheel(str(snapshot.root), task.name, str(destination))
        else:
            pack_cars.pack_wheel(str(snapshot.root), wheel, task.texture_set, str(destination))
        check_cancel(cancel)
        count, digest = _digest_file(destination, cancel=cancel)
        if count != task.size or digest != task.sha256:
            raise OriginalInputError('Converted wheel differs from the signed output plan')
        output.files[task.path] = SourceEntry(count,digest)
        result.append({'path':task.path,'bytes':count,'sha256':digest})
        if progress:
            progress('convert-wheels',index+1,len(tasks))
    return {'component':'wheels','readset_sha256':snapshot.readset.sha256,'files':result,
            'complete_dataset':False,'activated':False}
