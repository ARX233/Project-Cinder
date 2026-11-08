"""Guarded, source-derived character-wheel color compatibility.

This is deliberately NOT a universal component-order-100 texture conversion.
Rules are minted from the pinned main's character identity, original car.lua,
and wheel-only diffuse bindings in that car's original tire IGB.  They contain
source/encoded digests, not golden pixels or an embedded folder/image patch table.
The caller must bind rule.source_receipts to its signed input recipe before
publication.  No old WPK/JSON/header is accepted by the derivation API.

The hook operates only for kind='characar', validates all selected textures and
mesh/material ownership before mutating anything, and preserves alpha.  Its
packed-channel operation is independently checked against source RGBA decode ->
R/B swap -> RGB565/RGBA4444 quantization.  Existing stock/aero behavior is untouched.
"""
from __future__ import annotations

from array import array
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys

from .physics_image import SOURCE_SHA256, Elf32, PhysicsImageError, ConversionCancelled, _check, _parent_fd, _read_source
from .car_tables import NAME, _decode_main, _read_lua

ALGORITHM = '3dxplus-reviewed-chara-wheel-rb-v1'
WHEEL = 0x100
MAX_IGB_BYTES = 32 * 1024 * 1024
_SEAL = object()


class CharaColorError(PhysicsImageError):
    pass


def _need(ok, message, code='invalid_chara_color_rule'):
    if not ok:
        raise CharaColorError(code, message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _swap_packed(data, fmt):
    """RGB565 or RGBA4444 red/blue exchange; green/alpha bits unchanged."""
    _need(type(data) is bytes and len(data) % 2 == 0 and fmt in (0, 1), 'Unsupported packed character image')
    pixels = array('H')
    pixels.frombytes(data)
    if sys.byteorder != 'little':
        pixels.byteswap()
    if fmt == 0:
        out = array('H', (((p & 0x001F) << 11) | (p & 0x07E0) | ((p >> 11) & 0x001F) for p in pixels))
    else:
        out = array('H', (((p & 0x00F0) << 8) | (p & 0x0F0F) | ((p & 0xF000) >> 8) for p in pixels))
    if sys.byteorder != 'little':
        out.byteswap()
    return out.tobytes()


def _encode_source_rgba(image):
    """The approved 128x128 source lane, matching stage.pack.encode16 exactly."""
    image = image.convert('RGBA')
    width, height = image.size
    _need((width, height) == (128, 128), 'Unreviewed character-wheel image dimensions')
    rgba = image.tobytes()
    alpha = rgba[3::4]
    if min(alpha) == 255:
        fmt = 0
        values = ((rgba[i] >> 3) << 11 | (rgba[i + 1] >> 2) << 5 | (rgba[i + 2] >> 3)
                  for i in range(0, len(rgba), 4))
    else:
        _need(not all(a < 8 or a > 247 for a in alpha), 'Unreviewed RGBA5551 character-wheel lane')
        fmt = 1
        values = ((rgba[i] >> 4) << 12 | (rgba[i + 1] >> 4) << 8 | (rgba[i + 2] >> 4) << 4 | (rgba[i + 3] >> 4)
                  for i in range(0, len(rgba), 4))
    data = array('H', values)
    if sys.byteorder != 'little':
        data.byteswap()
    return width, height, fmt, data.tobytes()


@dataclass(frozen=True)
class ImageRule:
    name: str
    source_index: int
    source_format: int
    component_order: int
    width: int
    height: int
    wpk_format: int
    before_sha256: str
    after_sha256: str
    source_payload_sha256: str
    source_wheel_paths: tuple

    def receipt(self):
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


@dataclass(frozen=True)
class VerifiedCharaWheelRule:
    folder: str
    main_name: str
    model: int
    car: int
    wheel_name: str
    source_main_sha256: str
    source_receipts: tuple
    images: tuple
    rule_id: str
    _seal: object = field(repr=False, compare=False)

    def receipt(self):
        return {'algorithm': ALGORITHM, 'folder': self.folder, 'main_name': self.main_name,
                'model': self.model, 'car': self.car, 'wheel_name': self.wheel_name,
                'source_main_sha256': self.source_main_sha256,
                'source_receipts': [dict(row) for row in self.source_receipts],
                'images': [image.receipt() for image in self.images]}


def _mint_rule(folder, main_name, identity, wheel_name, receipts, images):
    provisional = VerifiedCharaWheelRule(folder, main_name, identity['model'], identity['car'], wheel_name,
                       SOURCE_SHA256, tuple(tuple(sorted(row.items())) for row in receipts), tuple(images), '', _SEAL)
    digest = _sha(json.dumps(provisional.receipt(), sort_keys=True, separators=(',', ':')).encode())
    return VerifiedCharaWheelRule(folder, main_name, identity['model'], identity['car'], wheel_name,
                       SOURCE_SHA256, provisional.source_receipts, tuple(images), digest, _SEAL)


def _stage_scene():
    """Lazy existing source parser import; no original code/plugin is loaded."""
    stage = Path(__file__).resolve().parents[1] / 'stage'
    inserted = str(stage) not in sys.path
    if inserted:
        sys.path.insert(0, str(stage))
    try:
        scene = importlib.import_module('scene')
        tex = importlib.import_module('tex')
    finally:
        if inserted:
            sys.path.remove(str(stage))
    _need(Path(scene.__file__).resolve() == (stage / 'scene.py').resolve() and
          Path(tex.__file__).resolve() == (stage / 'tex.py').resolve(), 'Unexpected scene/image parser module')
    return scene


def _stat_identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


@contextmanager
def _original_scene(path, scene, cancel=None):
    """Feed the parser a verified owned descriptor, not a racy source pathname."""
    with _parent_fd(path) as (parent, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            before = os.fstat(fd)
            _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_IGB_BYTES, 'IGB source is not a bounded regular file')
            digest, count = hashlib.sha256(), 0
            while count < before.st_size:
                _check(cancel)
                data = os.read(fd, min(65536, before.st_size - count))
                _need(bool(data), 'IGB source shrank while reading', 'source_changed')
                digest.update(data)
                count += len(data)
            _need(not os.read(fd, 1), 'IGB source grew while reading', 'source_changed')
            descriptor_root = '/proc/self/fd' if os.path.isdir('/proc/self/fd') else '/dev/fd'
            reference = f'{descriptor_root}/{fd}'
            # Confirm the exact descriptor alias names the already-authorized file.
            alias_fd = os.open(reference, os.O_RDONLY)
            try:
                alias = os.fstat(alias_fd)
                _need((alias.st_dev, alias.st_ino) == (before.st_dev, before.st_ino), 'Descriptor alias identity mismatch')
            finally:
                os.close(alias_fd)
            os.lseek(fd, 0, os.SEEK_SET)
            library, meshes = scene.meshes(reference)
            _need(len(library.buf) == before.st_size and _sha(library.buf) == digest.hexdigest(),
                  'IGB parser bytes differ from verified source', 'source_changed')
            yield library, meshes, {'bytes': before.st_size, 'sha256': digest.hexdigest()}
            after = os.fstat(fd)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _need(_stat_identity(before) == _stat_identity(after) == _stat_identity(named),
                  'IGB source changed during rule derivation', 'source_changed')
        finally:
            os.close(fd)


def _wheel_path(path):
    return any(isinstance(name, str) and name.startswith('WHEEL_') for name in path)


def _source_image_decode(library, image):
    # Existing parser's DDS adapter is trusted converter source, never game code.
    tex = importlib.import_module('tex')
    raw = library.ref(image[13])
    _need(raw is not None and raw.mem is not None, 'Wheel image has no original payload')
    return tex.to_pil(image, raw.mem), raw.mem


def _derive_one(root, folder, main_name, identity, scene, cancel):
    car_path = root / 'data' / 'characar' / folder / 'car.lua'
    car, lua = _read_lua(car_path, cancel)
    tire = car.get('TireStatus')
    _need(isinstance(tire, dict) and isinstance(tire.get('file'), list) and tire['file'], 'Character car has no tire source')
    _need(tire.get('wheel_name') == 'dummy_wheel', 'Unreviewed external character wheel source')
    relative = tire['file'][0]
    _need(isinstance(relative, str) and '\\' not in relative and '\x00' not in relative, 'Unsafe tire source path')
    parts = PurePosixPath(relative).parts
    _need(len(parts) == 4 and parts[:2] == ('data', 'characar') and parts[2].casefold() == folder.casefold()
          and parts[3].lower().endswith('.igb') and all(part not in ('.', '..') for part in parts),
          'Tire source is outside its reviewed character folder')
    from PIL import Image
    images = []
    with _original_scene(root.joinpath(*parts), scene, cancel) as (library, meshes, source):
        selected = {mesh['image'].index: mesh['image'] for mesh in meshes
                    if mesh.get('image') is not None and _wheel_path(mesh['path'])}
        _need(len(selected) == 1, 'Reviewed character lane requires exactly one wheel diffuse image')
        for image in selected.values():
            _check(cancel)
            name = library.string(image[22])
            _need(isinstance(name, str) and name and len(name.encode('latin1')) <= 255, 'Wheel image name is unavailable')
            _need(image[6].i32 == 100 and image[11].i32 in (14, 15) and
                  image[2].i32 == image[3].i32 == 128, 'Unreviewed character image dimensions, component order or format')
            refs = [mesh for mesh in meshes if mesh.get('image') is image]
            _need(refs and all(_wheel_path(mesh['path']) for mesh in refs), 'Wheel diffuse image is reused by non-wheel source geometry')
            _need(not any(mesh['state'].get(key) is image for mesh in meshes for key in ('env_image', 'spec_image')),
                  'Wheel diffuse image is also an environment/specular source')
            rgba, payload = _source_image_decode(library, image)
            before = _encode_source_rgba(rgba)
            r, g, b, a = rgba.convert('RGBA').split()
            after = _encode_source_rgba(Image.merge('RGBA', (b, g, r, a)))
            _need(before[:3] == after[:3] and _swap_packed(before[3], before[2]) == after[3],
                  'Packed conversion does not match original RGBA semantic conversion')
            images.append(ImageRule(name, image.index, image[11].i32, image[6].i32, *before[:3],
                          _sha(before[3]), _sha(after[3]), _sha(payload), tuple(tuple(mesh['path']) for mesh in refs)))
    receipts = [{'path': f'data/characar/{folder}/car.lua', **lua}, {'path': relative, **source}]
    return _mint_rule(folder, main_name, identity, tire['wheel_name'], receipts, images)


def derive_chara_wheel_rules(main_path, original_root, folders, *, cancel=None):
    """Mint per-source immutable rules; caller binds their receipts before publish."""
    _check(cancel)
    _need(isinstance(folders, (list, tuple)) and 1 <= len(folders) <= 64 and
          all(isinstance(folder, str) and NAME.fullmatch(folder) for folder in folders) and
          len({folder.casefold() for folder in folders}) == len(folders), 'Invalid or ambiguous character folder selection')
    root = Path(original_root)
    try:
        with _parent_fd(main_path) as (directory, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            try:
                raw, digest = _read_source(fd, cancel, None, retain=True)
                _need(digest == SOURCE_SHA256, 'Unsupported main SHA-256', 'unsupported_source')
                models = _decode_main(Elf32(raw, cancel), cancel)['character_models']
                scene = _stage_scene()
                rules = {}
                for folder in folders:
                    _check(cancel)
                    matches = [key for key in models if key.casefold() == folder.casefold()]
                    _need(len(matches) == 1, 'Character folder has no unique pinned-main model identity')
                    main_name = matches[0]
                    rules[folder] = _derive_one(root, folder, main_name, models[main_name], scene, cancel)
                _, after = _read_source(fd, cancel, None, retain=False)
                _need(after == digest, 'Main changed during character color derivation', 'source_changed')
                held, named = os.fstat(fd), os.stat(name, dir_fd=directory, follow_symlinks=False)
                _need((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino), 'Main path was replaced', 'source_changed')
            finally:
                os.close(fd)
        return rules
    except OSError as exc:
        raise CharaColorError('io_error', 'Cannot read original character color sources: ' + str(exc)) from exc


def derive_chara_wheel_rule(main_path, original_root, folder, *, cancel=None):
    return derive_chara_wheel_rules(main_path, original_root, [folder], cancel=cancel)[folder]


def apply_chara_wheel_colors(folder, kind, wheel, textures, meshes, verified_rule):
    """Existing pack_cars pre-write hook: verify first, then atomically replace pixels.

    No disk or reference pack reads occur here.  Wrong/missing/tampered rules,
    changed decoder output, unsupported encodings, missing wheel geometry or
    non-wheel/environment/specular reuse fail before any texture is changed.
    """
    if kind != 'characar':
        return {'applied': False, 'images': []}
    rule = verified_rule
    _need(type(rule) is VerifiedCharaWheelRule and rule._seal is _SEAL, 'A source-derived verified character rule is required')
    _need(rule.source_main_sha256 == SOURCE_SHA256 and folder == rule.folder,
          'Character rule source pin or folder mismatch')
    _need(_sha(json.dumps(rule.receipt(), sort_keys=True, separators=(',', ':')).encode()) == rule.rule_id,
          'Character rule commitment mismatch')
    _need(isinstance(wheel, dict) and wheel.get('name') == rule.wheel_name == 'dummy_wheel', 'Character wheel identity differs from source')
    _need(isinstance(textures, dict) and isinstance(meshes, (list, tuple)) and len(rule.images) == 1, 'Invalid character hook input shape')
    _need(all(isinstance(mesh, (tuple, list)) and len(mesh) == 6 and type(mesh[0]) is int and
              (mesh[5] is None or isinstance(mesh[5], (tuple, list)) and len(mesh[5]) == 4)
              for mesh in meshes), 'Invalid character mesh/material shape')
    replacements = {}
    for image in rule.images:
        _need(type(image) is ImageRule and image.component_order == 100 and image.source_format in (14, 15),
              'Unreviewed source image rule')
        _need(image.name in textures, 'Reviewed original wheel texture is missing')
        record = textures[image.name]
        _need(isinstance(record, (tuple, list)) and len(record) == 4, 'Invalid wheel texture record')
        width, height, fmt, data = record
        _need(all(type(value) is int for value in (width, height, fmt)) and
              (width, height, fmt) == (image.width, image.height, image.wpk_format) and
              type(data) is bytes and len(data) == width * height * 2 and _sha(data) == image.before_sha256,
              'Wheel texture differs from verified original decoding')
        refs = [mesh for mesh in meshes if mesh[1] == image.name]
        _need(refs and all(WHEEL <= mesh[0] < WHEEL + 4 for mesh in refs), 'Wheel image is reused outside wheel chunks')
        _need(not any(mesh[5] is not None and image.name in (mesh[5][1], mesh[5][2]) for mesh in meshes),
              'Wheel image is reused as environment/specular material')
        swapped = _swap_packed(data, fmt)
        _need(_sha(swapped) == image.after_sha256, 'Packed result differs from source RGBA semantic conversion')
        replacements[image.name] = (width, height, fmt, swapped)
    textures.update(replacements)
    return {'applied': True, 'images': list(replacements), 'rule_id': rule.rule_id,
            'model': rule.model, 'car': rule.car, 'source_main_sha256': rule.source_main_sha256}
