"""Data-only original map conversion; no Lua/ELF execution or child processes.

Public API: plan_maps(snapshot_or_root, city, time, reviewed_root=False), then
convert_maps(plan, owned_output, scratch_parent=...). Explicit roots are an
analyst/host-validation lane, NOT authenticated Android source snapshots. Neither
lane signs output hashes, publishes a ResourceStore.Ready, or activates a dataset.

The source16-v4 recipe preserves pack_tokyo.sh/pack_city.py model order, original
16-bit CPU textures (ground 512, buildings/sky 1024), and optional GLS1 gloss.
For the fixed reviewed main and the four non-Tokyo cities, only planned MAIN-SCENE
models normalize decoded vertex colour R/B to the current runtime ABI. Course
arrows and sky have independent ABIs and are excluded. G/A, texture pixels and
geometry are unchanged. Tokyo is a no-op in every layer. This inherits reviewed runtime visuals, not
an explanation by old source-script flags or a guessed GPU colour convention.
This compatibility rule does not claim to explain the original GPU shader cause.
It is deliberately not the old ASTC/AI-upscaled Android profile. Byte/file budgets
and cooperative cancellation do NOT hard-sandbox pack.py's intermediate memory,
NumPy allocations, IGB graph walk, triangle splitting, or native Pillow codecs.
Use one owned conversion worker; do not run other users of pack concurrently.

Explicit route_arrow_order=True selects the separate v5-route-order recipe.
Only the authenticated semantic coursearrow layer uses the original DEFAULT
DXT component-order conversion; v4/default behavior and all other layers remain
unchanged. New output requires a new reviewed resource profile/import, never an
in-place repair of an existing dataset. Signing/activation belongs to the host.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import builtins
import hashlib
import importlib
import math
import os
from pathlib import Path
import re
import stat
import struct
import tempfile
import threading
from types import SimpleNamespace

from .source import (VerifiedSnapshot, OwnedOutput, SourceEntry, MAIN_SHA256,
                     OriginalInputError, check_cancel, source_path, _directory)
from .physics_image import Elf32

RECIPE = 'wmmt-original-maps-source16-v4'
# Explicit opt-in only. Existing v4 profiles and tex.to_pil remain unchanged.
ROUTE_ARROW_RECIPE = 'wmmt-original-maps-source16-v5-route-order'
ROUTE_ARROW_INPUTS = {
    'data/coursearrow/fk_coursearrow_distribution.igb': 'b53249ff5f18e7d0edc065f89e72d6814846c66a2487f9b4d5b2e1583230f2f9',
    'data/coursearrow/hk_coursearrow_distribution.igb': 'f9ba8352c1c0db22fc765a73649e055305c7534968c095eb33c3ffe6e196c4f7',
    'data/coursearrow/nk_coursearrow_distribution.igb': 'fd2b228dfc2c8f66555cd35b6ce447d2967a29cfc2bead28f820bbe709e0a902',
    'data/coursearrow/ok_coursearrow_distribution.igb': 'dfa1994d952385a3dfd0277c20271fc325a5e7fadf9575a240db24933dac6d1b',
    'data/coursearrow/sk_coursearrow_distribution.igb': '758fad622b347f3411586bef4718d51a5db3d671190a0d664f0a79a9ae0f5b46',
    'data/coursearrow/tk_coursearrow_distribution.igb': 'c9db0884f80f8b9ffa8da47f75d7e4918528e74726871182b9d1f93e2272f25c',
    'data/coursearrow/wg_coursearrow_distribution.igb': 'a8e1aac38821265bf9a091fde66b632bd16f4752715f7a7dc74ab775331c5898',
}


def route_arrow_rule(plan, enabled=False):
    """Bind new decoding to the semantic coursearrow output and audited source.

    Pixel conversion is format/order driven, not a yellow filename tint. The
    finite source hashes constrain this migration; they do not authorize any
    additional source input, output namespace, or in-place dataset activation.
    """
    if type(enabled) is not bool:
        raise OriginalInputError('Route arrow order flag must be boolean')
    if not enabled:
        return None
    if not isinstance(plan, MapPlan) or plan._token is not _TOKEN:
        raise OriginalInputError('A map audit plan is required for route arrow order')
    source = [item for item in plan.inputs if item.path == plan.arrow]
    if (len(source) != 1 or plan.arrow not in ROUTE_ARROW_INPUTS or
            source[0].sha256 != ROUTE_ARROW_INPUTS[plan.arrow]):
        raise OriginalInputError('Route arrow source differs from reviewed original')
    return {'id': 'original-coursearrow-dxt-order-v1', 'kind': 'original-image-order',
            'layer': 'coursearrow', 'main_sha256': MAIN_SHA256,
            'model': plan.arrow, 'model_sha256': source[0].sha256,
            'output': plan.outputs[1], 'source_order': 100, 'target_order': 107,
            'formats': [14, 15, 16], 'rgba8_unchanged': True,
            'excluded_layers': ['main-scene', 'sky', 'cars', 'sprite', 'lights', 'neon'],
            'unchanged': ['green', 'alpha', 'vertex-colours', 'geometry', 'materials', 'visibility', 'timing'],
            'authority': 'Original ELF static converter registration and RGB565 endpoint/selector helper; no original execution'}

VERTEX_ABI_CITIES = ('oosaka', 'hakone', 'nagoya', 'fukuoka')
VERTEX_ABI_MAIN_SHA256 = '2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'
# Keep the v2 Fukuoka identifiers as compatibility aliases; its colour rule is unchanged.
FUKUOKA_VERTEX_RULE = 'fukuoka-vertex-rb-runtime-abi-v1'
FUKUOKA_VERTEX_MAIN_SHA256 = VERTEX_ABI_MAIN_SHA256
CITIES = ('tokyo', 'oosaka', 'hakone', 'nagoya', 'fukuoka')
TIMES = ('daytime', 'night')
TABLE = 0x094209E0
MAKERS = tuple(('sk_makerkanban_C1_kandabashi sk_makerkanban_C1_shibapark '
                'sk_makerkanban_C1_shiodome sk_makerkanban_shinkanjo_ariake '
                'sk_makerkanban_shinkanjo_kiba sk_makerkanban_Wangan_13gouchi '
                'wg_makerkanban_Wangan_daikokuhuto wg_makerkanban_Wangan_kukochuo '
                'sk_makerkanban_Yokohane_shibaura yh_makerkanban_Yokohane_haneda '
                'yh_makerkanban_Yokohane_shioiri').split())
OTHER = ('c1_otherlight', 'sk_otherlight', 'wg_otherlight', 'yh_otherlight')
_LISTS = ('GroundModel', 'ShortRangeBuildModel', 'LongRangeBuildModel', 'FlareModel', 'SkyBoxModel')
_BASENAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,159}\.igb\Z')
_TOKEN = object()
_PACK_LOCK = threading.Lock()
_BLOCK = 128 * 1024
_FORBIDDEN_ENV = ('WPK_TEX_EXPORT', 'WPK_TEX_UPSCALED', 'WPK_TEX_UPSCALED_MAX',
                  'WPK_TEX_ASTC', 'WPK_ASTCENC')


@dataclass(frozen=True)
class Budgets:
    max_files: int = 512
    max_file_bytes: int = 512 * 1024 * 1024
    max_input_bytes: int = 4 * 1024 * 1024 * 1024
    max_output_bytes: int = 1024 * 1024 * 1024
    max_scratch_bytes: int = 6 * 1024 * 1024 * 1024
    reserve_bytes: int = 64 * 1024 * 1024
    max_lua_bytes: int = 1024 * 1024
    max_model_vertices: int = 4_000_000
    max_model_triangles: int = 4_000_000
    max_image_pixels: int = 4096 * 4096

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise OriginalInputError('Invalid map byte/count budget')


@dataclass(frozen=True)
class InputFile:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class MapPlan:
    root: Path
    city: str
    time: str
    ground: tuple[str, ...]
    short: tuple[str, ...]
    long: tuple[str, ...]
    sky: tuple[str, ...]
    textures: str
    arrow: str
    barricade: str | None
    inputs: tuple[InputFile, ...]
    outputs: tuple[str, ...]
    source_authority: str
    readset_sha256: str | None
    budgets: Budgets
    _token: object = field(default=None, repr=False, compare=False)

    @property
    def input_bytes(self):
        return sum(item.size for item in self.inputs)

    def describe(self):
        return {'recipe': RECIPE, 'city': self.city, 'time': self.time,
                'source_authority': self.source_authority, 'readset_sha256': self.readset_sha256,
                'groups': {'ground': list(self.ground), 'short': list(self.short),
                           'long': list(self.long), 'sky': list(self.sky)},
                'textures': self.textures, 'arrow': self.arrow, 'barricade': self.barricade,
                'inputs': [vars(item) for item in self.inputs], 'outputs': list(self.outputs),
                'input_bytes': self.input_bytes, 'budgets': vars(self.budgets),
                'profile_rules': profile_rules(self),
                'complete_dataset': False, 'activated': False}


def profile_rules(plan):
    """Fixed source/ABI rules, not caller-supplied output bytes or hash patches."""
    if not isinstance(plan, MapPlan) or plan._token is not _TOKEN:
        raise OriginalInputError('A map audit plan is required for profile rules')
    if plan.city == 'tokyo':
        return []
    if plan.city not in VERTEX_ABI_CITIES:
        raise OriginalInputError('Unsupported city for vertex ABI normalization')
    main = [item for item in plan.inputs if item.path == 'main']
    if len(main) != 1 or main[0].sha256 != VERTEX_ABI_MAIN_SHA256:
        raise OriginalInputError('City vertex ABI rule requires the fixed reviewed main')
    return [{'id': plan.city + '-vertex-rb-runtime-abi-v1', 'kind': 'runtime-abi-normalization',
             'city': plan.city, 'main_sha256': VERTEX_ABI_MAIN_SHA256,
             'source': 'decoded IGB vertex colour only', 'channels': [2, 1, 0, 3],
             'layer': 'main-scene', 'main_output': plan.outputs[0],
             'input_scope': 'planned ground/short/long/barricade models only',
             'excluded_layers': ['coursearrow', 'sky'],
             'unchanged': ['green', 'alpha', 'texture-pixels', 'position', 'uv', 'normal', 'indices', 'matrix'],
             'rationale': 'Preserve current 1.34 %s runtime vertex-colour ABI and corrected visuals' % plan.city.capitalize(),
             'provenance': 'Explicit reviewed code rule; independent golden comparison is verification only, never conversion input',
             'not_claimed': 'Original GPU shader cause or a universal city channel convention'}]


def _main_scene_color_rule(plan, model, stage, rule):
    """Bind both output layer and exact planned source model before normalization."""
    if rule is None or stage != plan.outputs[0]:
        return None
    main_models = set(plan.ground + plan.short + plan.long)
    if plan.barricade:
        main_models.add(plan.barricade)
    return rule if model in main_models else None


def _normalize_vertex_colors(meshes, rule, *, cancel=None):
    """Copy only the decoded colour field; do not mutate any other source array."""
    counts = {'colored_meshes': 0, 'vertices': 0}
    if rule is None:
        return counts
    if (rule.get('city') not in VERTEX_ABI_CITIES or
            rule.get('id') != rule['city'] + '-vertex-rb-runtime-abi-v1'):
        raise OriginalInputError('Unsupported vertex compatibility rule')
    import numpy as np
    for mesh in meshes:
        check_cancel(cancel)
        vertices = mesh['verts']
        colors = vertices.get('color')
        if colors is None:
            continue
        if (not isinstance(colors, np.ndarray) or colors.dtype != np.dtype('u1') or
                colors.ndim != 2 or colors.shape != (len(vertices['pos']), 4)):
            raise OriginalInputError('Invalid original vertex colour ABI shape/type')
        mesh['verts'] = dict(vertices, color=colors[:, [2, 1, 0, 3]])
        counts['colored_meshes'] += 1
        counts['vertices'] += len(colors)
    return counts


def _identity(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


@contextmanager
def _member(root, name, max_bytes):
    """No symlinks, wrong-case aliases, special files, or path traversal."""
    source_path(name)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    try:
        parts = name.split('/')
        for index, part in enumerate(parts):
            # Narrow directory listing only: never recursively discover player files.
            names = os.listdir(directory)
            if len(names) > 16384:
                raise OriginalInputError('Original directory entry budget')
            matches = [n for n in names if n.casefold() == part.casefold()]
            if matches != [part]:
                raise OriginalInputError('Missing, wrong-case or ambiguous original member: ' + name)
            if index < len(parts) - 1:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = nxt
            else:
                fd = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= max_bytes:
            raise OriginalInputError('Original member type/size budget: ' + name)
        yield fd, before
        after = os.fstat(fd)
        named = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
        if _identity(before) != _identity(after) or _identity(after) != _identity(named):
            raise OriginalInputError('Original member changed: ' + name)
    except OSError as exc:
        raise OriginalInputError('Cannot read original member ' + name + ': ' + str(exc)) from exc
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def _read(root, name, budgets, *, cancel=None, retain=False, expected=None, target=None):
    digest, chunks, count = hashlib.sha256(), [], 0
    limit = budgets.max_lua_bytes if name.endswith('.lua') else budgets.max_file_bytes
    with _member(root, name, limit) as (fd, before):
        if expected is not None and before.st_size != expected.size:
            raise OriginalInputError('Original member length changed: ' + name)
        while True:
            check_cancel(cancel)
            b = os.read(fd, _BLOCK)
            if not b:
                break
            count += len(b)
            if count > before.st_size:
                raise OriginalInputError('Original member grew: ' + name)
            digest.update(b)
            if retain:
                chunks.append(b)
            if target is not None:
                target.write(b)
        check_cancel(cancel)
        value = digest.hexdigest()
        if count != before.st_size or (expected is not None and value != expected.sha256):
            raise OriginalInputError('Original member failed SHA-256: ' + name)
    return InputFile(name, count, value), b''.join(chunks)


def _comments(text):
    # Keep quoted text intact. We parse data fields only, never evaluate Lua.
    token = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|--\[\[.*?\]\]|--[^\n]*', re.S)
    return token.sub(lambda m: ' ' if m[0].startswith('--') else m[0], text)


def parse_scene(data, expected_prefix):
    """Strict ASCII file-list subset, tolerating legacy non-UTF8 comments only."""
    source_path(expected_prefix + 'textures.igb')
    if not isinstance(data, bytes) or len(data) > 1024 * 1024:
        raise OriginalInputError('Invalid Lua data size')
    text = _comments(data.decode('latin1'))
    prefixes = re.findall(r'(?m)^\s*AbsPath\s*=\s*"([^"\n]*)"\s*$', text)
    if len(re.findall(r'\bAbsPath\s*=', text)) != 1 or prefixes != [expected_prefix]:
        raise OriginalInputError('Missing, duplicate or unsupported AbsPath')
    result = {}
    for key in _LISTS:
        starts = list(re.finditer(r'\b' + key + r'\s*=', text))
        if not starts and key == 'FlareModel':
            result[key] = ()
            continue
        if len(starts) != 1:
            raise OriginalInputError('Missing or duplicate Lua list: ' + key)
        rest = text[starts[0].end():]
        match = re.match(r'\s*\{([^{}]*)\}', rest, re.S)
        if match is None:
            raise OriginalInputError('Unsupported Lua list expression: ' + key)
        values = []
        body = match[1].strip()
        entries = body.split(',')
        if entries and not entries[-1].strip():
            entries.pop()
        for item in entries:
            if not item.strip() and not body:
                continue
            m = re.fullmatch(r'\s*AbsPath\s*\.\.\s*"([^"\\]*)"\s*', item)
            if m is None or not _BASENAME.fullmatch(m[1]):
                raise OriginalInputError('Unsafe or dynamic Lua model path: ' + key)
            values.append(expected_prefix + m[1])
        if len(values) != len(set(v.casefold() for v in values)):
            raise OriginalInputError('Duplicate original model name: ' + key)
        result[key] = tuple(values)
    arrows = re.findall(r'(?m)^\s*CourseArrow\s*=\s*"([^"\\]*)"\s*$', text)
    if (len(re.findall(r'\bCourseArrow\s*=', text)) != 1 or len(arrows) != 1 or
            not re.fullmatch(r'data/coursearrow/[A-Za-z0-9_]+\.igb', arrows[0])):
        raise OriginalInputError('Missing or unsafe CourseArrow')
    if not result['GroundModel'] or not result['SkyBoxModel']:
        raise OriginalInputError('Original scene has no ground or sky')
    result['CourseArrow'] = arrows[0]
    return result


def plan_maps(source, city, time, *, reviewed_root=False, budgets=None, cancel=None, progress=None):
    """Audit dependencies before packing. Root is the original game's root, not data/."""
    check_cancel(cancel)
    if city not in CITIES or time not in TIMES:
        raise OriginalInputError('Map city/time is not whitelisted')
    budgets = budgets or Budgets()
    if not isinstance(budgets, Budgets):
        raise OriginalInputError('Map budgets required')
    snapshot = source if isinstance(source, VerifiedSnapshot) else None
    if snapshot is None and reviewed_root is not True:
        raise OriginalInputError('A VerifiedSnapshot or explicitly reviewed root is required')
    root = _directory(snapshot.root if snapshot is not None else source)
    captured = {}

    def obtain(name, retain=False):
        source_path(name)
        if name in captured and not retain:
            return captured[name], b''
        expected = None
        if snapshot is not None:
            expected = snapshot.readset.files.get(name)
            if expected is None:
                raise OriginalInputError('Map dependency is not in the reviewed read-set: ' + name)
        item, data = _read(root, name, budgets, cancel=cancel, retain=retain, expected=expected)
        captured[name] = item
        if len(captured) > budgets.max_files or sum(v.size for v in captured.values()) > budgets.max_input_bytes:
            raise OriginalInputError('Map input read-set budget')
        if progress:
            progress('plan-maps-file', len(captured), budgets.max_files)
        return item, data

    prefix = 'data/' + city + '/' + time + '/'
    scene_path = prefix + time + '.lua'
    scene = parse_scene(obtain(scene_path, True)[1], prefix)
    g, s, l = [list(scene[k]) for k in _LISTS[:3]]
    l += scene['FlareModel']
    if city == 'tokyo':
        if time == 'daytime':
            primary = parse_scene(obtain('data/other_stage/c1_daytime.lua', True)[1], prefix)
            g = list(primary['GroundModel'])
            makers = [prefix + name + '.igb' for name in MAKERS]
            if [p for p in scene['GroundModel'] if 'makerkanban' in p] != makers:
                raise OriginalInputError('Unsupported Tokyo maker ordering')
            g += makers
            s = list(primary['ShortRangeBuildModel'])
            # shell's extra original signboard, absent from c1_daytime.lua's S list.
            extra = prefix + 'wg_area01_kanban.igb'
            if extra not in scene['ShortRangeBuildModel'] or len(s) < 13:
                raise OriginalInputError('Missing Tokyo daytime signboard')
            s.insert(13, extra)
            l = list(primary['LongRangeBuildModel'])
            if primary['SkyBoxModel'] != scene['SkyBoxModel'] or primary['CourseArrow'] != scene['CourseArrow']:
                raise OriginalInputError('Conflicting Tokyo daytime sky/arrows')
        else:
            l = list(scene['LongRangeBuildModel']) + [prefix + 'sk_searchlight.igb'] + list(scene['FlareModel'])
        g += [prefix + name + '.igb' for name in OTHER]
    for group in (g, s, l, list(scene['SkyBoxModel'])):
        if len(group) != len(set(p.casefold() for p in group)):
            raise OriginalInputError('Conflicting model names in map group')
    models = g + s + l + list(scene['SkyBoxModel'])
    if len(models) != len(set(p.casefold() for p in models)):
        raise OriginalInputError('Model occurs in multiple map groups')
    textures = prefix + 'textures.igb'
    barricade = 'data/stage_common/gurdrail_' + time + '.igb' if city == 'tokyo' else None
    for name in ['main', textures, scene['CourseArrow'], *models, *([barricade] if barricade else [])]:
        obtain(name)
    if captured['main'].sha256 != MAIN_SHA256:
        raise OriginalInputError('Unsupported original main SHA-256')
    suffix = '' if time == 'daytime' else '_night'
    tag = '' if city == 'tokyo' else '_' + city
    outputs = (city + suffix + '.wpk', 'arrows' + tag + suffix + '.wpk',
               'arrows' + tag + suffix + '.names', 'sky' + tag + suffix + '.wpk')
    return MapPlan(root, city, time, tuple(g), tuple(s), tuple(l), tuple(scene['SkyBoxModel']),
                   textures, scene['CourseArrow'], barricade, tuple(captured[n] for n in sorted(captured)),
                   outputs, 'verified-snapshot' if snapshot else 'explicit-reviewed-root',
                   snapshot.readset.sha256 if snapshot else None, budgets, _TOKEN)


def barricade_text(main, *, cancel=None):
    """Pinned static ELF VA reads only, identical %.4f recipe to barricades.py."""
    check_cancel(cancel)
    if hashlib.sha256(main).hexdigest() != MAIN_SHA256:
        raise OriginalInputError('Unsupported original main SHA-256')
    elf = Elf32(main, cancel)
    pointer, count = struct.unpack('<II', elf.read(TABLE + 8, 8))
    if count != 126:
        raise OriginalInputError('Unsupported barricade count')
    lines = ['# scale_x x y z rot_x rot_y rot_z  (from clGraphicFrame::setBarricade, 126 pieces)']
    for index in range(count):
        check_cancel(cancel)
        model, *values = struct.unpack('<i7f', elf.read(pointer + 32 * index, 32))
        if model not in (0, 1) or not all(math.isfinite(v) for v in values):
            raise OriginalInputError('Invalid barricade placement')
        lines.append(' '.join('%.4f' % v for v in values))
    return ('\n'.join(lines) + '\n').encode('ascii')


def _environment(pack=None):
    if any(key in os.environ for key in _FORBIDDEN_ENV):
        raise OriginalInputError('Map recipe forbids external texture/ASTC environment overrides')
    if pack is not None and (pack.TEX_EXPORT or pack.TEX_UPSCALED or pack.TEX_ASTC):
        raise OriginalInputError('Map recipe forbids modified pack texture/ASTC globals')


def check_dependencies():
    """Fail before any packing if the packaged numeric/texture backend is unusable.

    A host OpenBLAS build was observed returning zeros for float32 identity
    multiplication. Version strings alone do not establish a usable backend.
    No fallback, install, native encoder discovery, or runtime rebuilding occurs.
    """
    _environment()
    try:
        import numpy as np
        import PIL
        pack = importlib.import_module('pack')
    except ImportError as exc:
        raise OriginalInputError('Map conversion requires packaged pack, NumPy and Pillow') from exc
    _environment(pack)
    if not callable(getattr(pack, 'main', None)) or not hasattr(pack, 'VERTEX'):
        raise OriginalInputError('Trusted stage pack module is unavailable')
    values = np.array([[1, 2, 3, 1], [4, 5, 6, 1]], dtype=np.float32)
    identity = np.eye(4, dtype=np.float32)
    posture = np.diag(np.array([2, 3, 4, 1], dtype=np.float32))
    posture[3, :3] = [16, -8, 4]  # Alchemy row-vector scale plus translation.
    moved = values @ posture
    larger = np.arange(1, 33, dtype=np.float32).reshape(8, 4)
    expected = np.array([[18, -2, 16, 1], [24, 7, 28, 1]], dtype=np.float32)
    if (not np.array_equal(values @ identity, values) or
            not np.array_equal(larger @ identity, larger) or
            not np.array_equal(identity @ identity, identity) or
            not np.isfinite(moved).all() or not np.array_equal(moved, expected)):
        raise OriginalInputError('NumPy float32 matrix backend failed identity/posture self-test')
    config = getattr(np.__config__, 'CONFIG', {})
    blas = config.get('Build Dependencies', {}).get('blas', {})
    return {'numpy_version': np.__version__, 'numpy_path': str(Path(np.__file__).resolve()),
            'pillow_version': PIL.__version__, 'pillow_path': str(Path(PIL.__file__).resolve()),
            'blas': {key: str(blas.get(key, 'unavailable')) for key in ('name', 'version', 'openblas configuration')},
            'float32_matrix_selftest': 'pass',
            'cases': ['2x4-f32-identity', '8x4-f32-identity', '4x4-f32-identity',
                      '2x4-f32-row-vector-scale-translation-finite']}


def _separate(source, other):
    if source == other or source in other.parents or other in source.parents:
        raise OriginalInputError('Source and owned output/scratch must be disjoint')


def _free_space(path, needed):
    space = os.statvfs(path)
    if space.f_bavail * space.f_frsize < needed:
        raise OriginalInputError('Insufficient map job disk space')


def _copy_outputs(source, target, expected_size, cancel):
    count, digest = 0, hashlib.sha256()
    with source.open('rb') as src, target.open('xb') as dst:
        while True:
            check_cancel(cancel)
            b = src.read(_BLOCK)
            if not b:
                break
            count += len(b)
            if count > expected_size:
                raise OriginalInputError('Generated map changed during publication')
            digest.update(b)
            dst.write(b)
        dst.flush()
        os.fsync(dst.fileno())
    if count != expected_size:
        raise OriginalInputError('Generated map length changed during publication')
    return SourceEntry(count, digest.hexdigest())


class _BudgetWriter:
    def __init__(self, file, total, maximum, cancel):
        self.file, self.total, self.maximum, self.cancel = file, total, maximum, cancel

    def __enter__(self):
        self.file.__enter__()
        return self

    def __exit__(self, *args):
        return self.file.__exit__(*args)

    def write(self, value):
        check_cancel(self.cancel)
        n = len(value.encode('utf-8')) if isinstance(value, str) else len(value)
        if n > self.maximum - self.total[0]:
            raise OriginalInputError('Map output byte budget')
        # Bounded write chunks provide cancellation even when pack built a large blob.
        result = 0
        for offset in range(0, len(value), _BLOCK):
            check_cancel(self.cancel)
            result += self.file.write(value[offset:offset + _BLOCK])
        self.total[0] += n
        return result

    def __getattr__(self, key):
        return getattr(self.file, key)


@contextmanager
def _pack_context(pack, plan, scratch, outputs, cancel, progress, *, route_arrow_order=False):
    """Adapt pack.main locally; restore all globals even on cancellation/failure.

    No global builtins/open, shared scene module, cwd, environment or sys.argv
    mutations. Other pack-based converters must not run concurrently.
    """
    original_scene, original_igb = pack.scene, pack.IGB
    original_open = pack.__dict__.get('open', None)
    original_library, original_decode = pack.load_library, pack.decode_image
    original_collect, original_batches = pack.collect, pack.build_batches
    rules = profile_rules(plan)
    color_rule = rules[0] if rules else None
    arrow_rule = route_arrow_rule(plan, route_arrow_order)
    # Strong references prevent cross-phase Python id reuse from authorizing
    # another object's pixels. Image identity is bound to the exact IGB owner.
    arrow_owners = {}
    state = {'stage': None, 'batch_index': 0, 'unsupported_optional_gloss': [],
             'profile_rules': rules, 'profile_rule_applications': [],
             'profile_rule_layer_exclusions': [], 'route_arrow_rule': arrow_rule,
             'route_arrow_decodes': []}
    active_paths, source_roles, affected_vertices = {}, [], {}
    optional_images, skipped_images, diffuse_images = {}, set(), set()
    allowed = {item.path for item in plan.inputs}
    allowed.add('_barricades.txt')
    total, library, model_count = [0], {}, [0]
    expected_models = len(plan.ground) + len(plan.short) + len(plan.long) + len(plan.sky) + 1 + bool(plan.barricade)

    def member(name):
        if not isinstance(name, str) or name not in allowed:
            raise OriginalInputError('Packer attempted an unplanned input')
        return str(scratch / name)

    def igb(name):
        check_cancel(cancel)
        obj = original_igb(member(name))
        for img in obj.of_type('igImage'):
            w, h = img[2].i32, img[3].i32
            if w <= 0 or h <= 0 or w * h > plan.budgets.max_image_pixels:
                raise OriginalInputError('Original image pixel budget')
        return obj

    def meshes(name):
        check_cancel(cancel)
        if progress:
            progress('convert-map-model', model_count[0], expected_models)
        obj, result = original_scene.meshes(member(name))
        if arrow_rule is not None and state['stage'] == plan.outputs[1] and name == plan.arrow:
            arrow_owners[id(obj)] = (obj, tuple(obj.of_type('igImage')))
        vertices = sum(len(m['verts']['pos']) for m in result)
        triangles = sum(len(m['tris']) for m in result)
        if vertices > plan.budgets.max_model_vertices or triangles > plan.budgets.max_model_triangles:
            raise OriginalInputError('Decoded map model geometry budget')
        model_rule = _main_scene_color_rule(plan, name, state['stage'], color_rule)
        normalized = _normalize_vertex_colors(result, model_rule, cancel=cancel)
        if model_rule is not None:
            state['profile_rule_applications'].append({'id': model_rule['id'], 'model': name,
                                                       'stage': state['stage'], 'layer': 'main-scene', **normalized})
        elif color_rule is not None:
            layer = ('coursearrow' if state['stage'] == plan.outputs[1] else
                     'sky' if state['stage'] == plan.outputs[3] else 'unbound-or-unplanned-main-input')
            state['profile_rule_layer_exclusions'].append({'id': color_rule['id'], 'model': name,
                                                          'stage': state['stage'], 'layer': layer,
                                                          'normalized': False})
        import numpy as np
        for mesh_index, m in enumerate(result):
            if (not np.isfinite(m['matrix']).all() or
                    any(not np.isfinite(value).all() for value in m['verts'].values()) or
                    (m['tris'].size and (m['tris'].min() < 0 or m['tris'].max() >= len(m['verts']['pos'])))):
                raise OriginalInputError('Nonfinite or invalid decoded original geometry')
            diffuse = m['image']
            if isinstance(diffuse, str):
                if diffuse not in library:
                    raise OriginalInputError('Missing original texture binding: ' + diffuse)
                lib, image = library[diffuse]
                key = (id(lib), image.index)
                if key in skipped_images:
                    raise OriginalInputError('An unsupported optional gloss is also used as diffuse')
                diffuse_images.add(key)
            roles = []
            material = m['state'].get('gloss')
            if material and material[0] in library and len(m['verts']['pos']) and len(m['tris']):
                lib, image = library[material[0]]
                if image[11].i32 == 65536:
                    key = (id(lib), image.index)
                    if key in diffuse_images:
                        raise OriginalInputError('Unsupported gloss image is also diffuse')
                    row = {'source_relative_image': plan.textures, 'image_index': image.index,
                           'image_name': lib.string(image[22]), 'format': 65536,
                           'model': name, 'mesh_index': mesh_index, 'material_mesh': m['name'],
                           'material_path': list(m['path']), 'gloss_texture': material[0],
                           'cube_texture': material[1], 'stage': state['stage'],
                           'affected_batch_ids': [], 'decode_skipped': key in skipped_images,
                           'reason': 'pack optional material gloss fmt=65536 has no CPU decoder; no pixels fabricated'}
                    optional_images.setdefault(key, []).append(row)
                    state['unsupported_optional_gloss'].append(row)
                    roles.append(row)
            if active_paths.get(name) in (0, 1, 2) and len(m['verts']['pos']) and len(m['tris']):
                source_roles.append((m['tris'], roles))
        model_count[0] += 1
        check_cancel(cancel)
        return obj, result

    def load_library(name):
        result = original_library(name)
        library.clear()
        library.update(result)
        optional_images.clear()
        skipped_images.clear()
        diffuse_images.clear()
        return result

    def collect(*args, **kwargs):
        active_paths.clear()
        active_paths.update({path: group for group, path in args[0]})
        source_roles.clear()
        affected_vertices.clear()
        result = original_collect(*args, **kwargs)
        # Normal map paths precede --place instances in pack.collect. The exact
        # original triangle-array identities prove this alignment; no fuzzy match.
        if len(source_roles) > len(result[2]):
            raise OriginalInputError('Cannot bind optional material provenance')
        for (triangles, roles), packed in zip(source_roles, result[2]):
            if packed[4] is not triangles:
                raise OriginalInputError('Optional material/source triangle binding changed')
            if roles:
                affected_vertices[id(packed[3])] = roles
        return result

    def build_batches(parts, tex_index):
        result = original_batches(parts, tex_index)
        first = state['batch_index']
        state['batch_index'] += len(result)
        if not any(id(part[2]) in affected_vertices for part in parts):
            return result
        # Reproduce ONLY grouping/split accounting to annotate actual output batch
        # ordinals. Geometry/pixels are still produced exclusively by pack.py.
        import numpy as np
        groups = {}
        for name, flags, vert, tris, material in parts:
            if material is not None and material[0] == 'G':
                material = (material[0], tex_index.get(material[1], 0xFFFF), material[2], 0)
            elif material is not None:
                material = (material[0], tex_index.get(material[1], 0xFFFF),
                            tex_index.get(material[2], 0xFFFF), material[3])
            key = (tex_index.get(name, 0xFFFF), flags, material)
            groups.setdefault(key, []).append((vert, tris))
        ordinal = first
        for _, items in sorted(groups.items(), key=lambda kv: (kv[0][1] & 3 != 0, kv[0][0], kv[0][2] or ())):
            base, roles = 0, []
            def record():
                for role in roles:
                    if ordinal not in role['affected_batch_ids']:
                        role['affected_batch_ids'].append(ordinal)
            for vert, tris in items:
                used = len(np.unique(tris))
                if base + used > 65535:
                    record()
                    ordinal += 1
                    base, roles = 0, []
                roles += affected_vertices.get(id(vert), [])
                base += used
            if base:
                record()
                ordinal += 1
        if ordinal != first + len(result):
            raise OriginalInputError('Optional gloss output batch accounting mismatch')
        return result

    def decode_image(obj, image):
        check_cancel(cancel)
        w, h = image[2].i32, image[3].i32
        if w <= 0 or h <= 0 or w * h > plan.budgets.max_image_pixels:
            raise OriginalInputError('Original image pixel budget')
        owner = arrow_owners.get(id(obj))
        if (arrow_rule is not None and state['stage'] == plan.outputs[1] and
                owner is not None and owner[0] is obj and
                any(candidate is image for candidate in owner[1])):
            memory = obj.ref(image[13])
            if memory is None or memory.mem is None:
                raise OriginalInputError('Missing original coursearrow image bytes')
            try:
                im = pack.tex.to_pil_original_order(image, memory.mem)
            except (ValueError, TypeError, AttributeError) as exc:
                raise OriginalInputError('Unsupported original coursearrow image order') from exc
            state['route_arrow_decodes'].append({
                'stage': state['stage'], 'model': plan.arrow,
                'image_index': image.index, 'image_name': obj.string(image[22]),
                'format': image[11].i32, 'order': image[6].i32,
                'source_bytes_sha256': hashlib.sha256(memory.mem).hexdigest(),
                'decoded_rgba_sha256': hashlib.sha256(im.tobytes()).hexdigest()})
        else:
            im = original_decode(obj, image)
        if im is None:
            key = (id(obj), image.index)
            # The sole reviewed exception preserves pack's existing optional
            # reflection downgrade, never a missing diffuse or unknown decoder.
            if image[11].i32 != 65536 or key not in optional_images or key in diffuse_images:
                raise OriginalInputError('Unsupported or missing original texture pixels')
            skipped_images.add(key)
            for row in optional_images[key]:
                row['decode_skipped'] = True
        return im

    def safe_open(name, mode='r', *args, **kwargs):
        check_cancel(cancel)
        if name in outputs and mode in ('wb', 'w'):
            return _BudgetWriter(builtins.open(outputs[name], 'xb' if mode == 'wb' else 'x',
                                               *args, **kwargs), total, plan.budgets.max_output_bytes, cancel)
        if name == '_barricades.txt' and mode == 'r':
            return builtins.open(member(name), mode, *args, **kwargs)
        raise OriginalInputError('Packer attempted an unplanned file operation')

    pack.scene = SimpleNamespace(meshes=meshes)
    pack.IGB, pack.open = igb, safe_open
    pack.load_library, pack.decode_image = load_library, decode_image
    pack.collect, pack.build_batches = collect, build_batches
    try:
        yield state
    finally:
        pack.scene, pack.IGB = original_scene, original_igb
        pack.load_library, pack.decode_image = original_library, original_decode
        pack.collect, pack.build_batches = original_collect, original_batches
        if original_open is None:
            pack.__dict__.pop('open', None)
        else:
            pack.open = original_open


def inspect_wpk(path, *, max_bytes=1024 * 1024 * 1024):
    """Validate generated WPK2/source16 ranges, groups, indices and GLS1 sidecar."""
    size = Path(path).stat().st_size
    if not 32 <= size <= max_bytes:
        raise OriginalInputError('Generated WPK byte budget')
    with builtins.open(path, 'rb') as f:
        data = f.read()
    magic, nt, nc, nb, chunk, to, co, bo = struct.unpack_from('<4sIIIfIII', data)
    if (magic != b'WPK2' or not nt or not nc or not nb or nt > 65535 or
            not math.isfinite(chunk) or chunk <= 0 or to != 32 or
            co != to + nt * 64 or bo != co + nc * 36 or bo + nb * 20 > size):
        raise OriginalInputError('Invalid generated WPK2 header/tables')
    start = bo + nb * 20

    def bounds(offset, count):
        if offset < start or offset % 4 or count < 0 or count > size - offset:
            raise OriginalInputError('Invalid generated WPK payload range')

    formats, vertices, indices, groups = set(), [], 0, set()
    for i in range(nt):
        _name, w, h, fmt, offset, count = struct.unpack_from('<48sHHIII', data, to + 64 * i)
        if not w or not h or fmt not in (0, 1, 2) or count != w * h * 2:
            raise OriginalInputError('Map output is not CPU source16 texture data')
        bounds(offset, count)
        formats.add(fmt)
    for i in range(nc):
        *box, first, count, group = struct.unpack_from('<6fIII', data, co + 36 * i)
        if (not all(math.isfinite(v) for v in box) or any(box[j] > box[j+3] for j in range(3)) or
                not count or first + count > nb):
            raise OriginalInputError('Invalid generated map chunk')
        groups.add(group)
    for i in range(nb):
        texture, flags, vo, nv, io, ni = struct.unpack_from('<HHIIII', data, bo + 20 * i)
        if (texture != 0xFFFF and texture >= nt) or not nv or nv > 65535 or ni % 3:
            raise OriginalInputError('Invalid generated map batch')
        bounds(vo, nv * 24)
        bounds(io, ni * 2)
        if ni and max(struct.unpack_from('<%dH' % ni, data, io)) >= nv:
            raise OriginalInputError('Generated index escapes vertex buffer')
        vertices.append(nv)
        indices += ni
    gloss = None
    if data[-4:] == b'GLS1':
        offset, = struct.unpack_from('<I', data, size - 8)
        bounds(offset, 8)
        cubes, batches = struct.unpack_from('<II', data, offset)
        if offset + 8 + cubes * 72 + batches * 12 != size - 8 or not cubes or not batches:
            raise OriginalInputError('Invalid GLS1 table bounds')
        for i in range(cubes * 6):
            w, fmt, off, count = struct.unpack_from('<HHII', data, offset + 8 + i * 12)
            if not 0 < w <= 256 or fmt not in (0, 1, 2) or count != w * w * 2:
                raise OriginalInputError('Invalid GLS1 cube source16 texture')
            bounds(off, count)
        for i in range(batches):
            batch, texture, cube, off = struct.unpack_from('<IHHI', data, offset + 8 + cubes * 72 + i * 12)
            if batch >= nb or texture >= nt or cube >= cubes:
                raise OriginalInputError('Invalid GLS1 batch binding')
            bounds(off, vertices[batch] * 8)
        gloss = {'cubes': cubes, 'batches': batches}
    return {'magic': 'WPK2', 'bytes': size, 'textures': nt, 'chunks': nc, 'batches': nb,
            'triangles': indices // 3, 'groups': sorted(groups),
            'texture_formats': sorted(formats), 'gloss': gloss,
            'sha256': hashlib.sha256(data).hexdigest()}


def convert_maps(plan, output, *, scratch_parent, cancel=None, progress=None, route_arrow_order=False):
    """Run pack.main(args) three times in THIS process, never a shell/subprocess.

    Incomplete scratch/output is retained on failure; caller owns job cleanup.
    Generated files are checked and exclusively copied to OwnedOutput only after
    all three phases pass. Output hashes are observations, never presigned pins.
    """
    check_cancel(cancel)
    if not isinstance(plan, MapPlan) or plan._token is not _TOKEN or not isinstance(output, OwnedOutput):
        raise OriginalInputError('A map audit plan and new OwnedOutput are required')
    _environment()
    profile_rules(plan)  # Validate the fixed source/ABI binding before creating scratch.
    route_arrow_rule(plan, route_arrow_order)  # New recipe is explicitly requested, never inherited.
    dependencies = check_dependencies()
    parent, outroot = _directory(scratch_parent), _directory(output.root)
    if parent == plan.root or plan.root in parent.parents:
        raise OriginalInputError('Scratch parent must not be inside original source')
    _separate(plan.root, outroot)
    destinations = {name: output.target(name) for name in plan.outputs}
    b = plan.budgets
    if plan.input_bytes + b.max_output_bytes > b.max_scratch_bytes:
        raise OriginalInputError('Map scratch byte budget')
    _free_space(parent, plan.input_bytes + b.max_output_bytes + b.reserve_bytes)
    _free_space(outroot, b.max_output_bytes + b.reserve_bytes)
    if os.stat(parent).st_dev == os.stat(outroot).st_dev:
        _free_space(parent, plan.input_bytes + 2 * b.max_output_bytes + b.reserve_bytes)
    pack = importlib.import_module('pack')  # trusted packaged stage modules, never source-root sys.path
    _environment(pack)
    # Detect accidental unrelated modules, without requiring host filesystem layout on Android.
    if not callable(getattr(pack, 'main', None)) or not hasattr(pack, 'VERTEX'):
        raise OriginalInputError('Trusted stage pack module is unavailable')
    if not _PACK_LOCK.acquire(blocking=False):
        raise OriginalInputError('Another in-process map conversion is active')
    scratch = None
    try:
        scratch = Path(tempfile.mkdtemp(prefix='map-job-', dir=parent))
        for index, item in enumerate(plan.inputs):
            check_cancel(cancel)
            target = scratch / item.path
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open('xb') as dst:
                _read(plan.root, item.path, b, cancel=cancel, expected=item, target=dst)
            os.chmod(target, 0o400)
            if progress:
                progress('snapshot-map-file', index + 1, len(plan.inputs))
        if plan.barricade:
            # main is fixed-pin static data. It is not imported, loaded or executed.
            with (scratch / 'main').open('rb') as f:
                main = f.read()
            with (scratch / '_barricades.txt').open('xb') as f:
                f.write(barricade_text(main, cancel=cancel))
        generated = scratch / '_generated'
        generated.mkdir(mode=0o700)
        outputs = {name: generated / name for name in plan.outputs}
        args = [plan.outputs[0], '--textures', plan.textures, '--max-tex-build', '1024']
        if plan.barricade:
            args += ['--place', plan.barricade, '_barricades.txt']
        args += list(plan.ground)
        if plan.short:
            args += ['--short', *plan.short]
        if plan.long:
            args += ['--long', *plan.long]
        phases = [args, [plan.outputs[1], '--textures', plan.textures, '--objects', plan.arrow],
                  [plan.outputs[3], '--textures', plan.textures, '--chunk', '1000000',
                   '--max-tex', '1024', *plan.sky]]
        with _pack_context(pack, plan, scratch, outputs, cancel, progress,
                           route_arrow_order=route_arrow_order) as pack_state:
            for index, argv in enumerate(phases):
                check_cancel(cancel)
                _environment(pack)
                pack_state['stage'], pack_state['batch_index'] = argv[0], 0
                if progress:
                    progress('convert-map-phase', index, len(phases))
                pack.main(argv)
                check_cancel(cancel)
        if route_arrow_order and not pack_state['route_arrow_decodes']:
            raise OriginalInputError('New route arrow recipe decoded no authenticated route images')
        optional_gloss = [row for row in pack_state['unsupported_optional_gloss'] if row['decode_skipped']]
        if any(not row['affected_batch_ids'] for row in optional_gloss):
            raise OriginalInputError('Optional gloss downgrade lacks output batch provenance')
        checks = {}
        for name in plan.outputs:
            check_cancel(cancel)
            path = outputs[name]
            if not path.is_file():
                raise OriginalInputError('Packer did not produce planned output: ' + name)
            if name.endswith('.wpk'):
                checks[name] = inspect_wpk(path, max_bytes=b.max_output_bytes)
            else:
                names = path.read_bytes()
                if (not names or len(names) > 1024 * 1024 or not names.endswith(b'\n') or
                        b'\0' in names or any(not line for line in names.splitlines())):
                    raise OriginalInputError('Invalid generated arrow names')
                checks[name] = {'bytes': len(names), 'objects': len(names.splitlines()),
                                'sha256': hashlib.sha256(names).hexdigest()}
        if (not set(checks[plan.outputs[0]]['groups']) <= {0, 1, 2} or
                checks[plan.outputs[3]]['groups'] != [0] or
                checks[plan.outputs[1]]['groups'] != list(range(3, 3 + checks[plan.outputs[2]]['objects']))):
            raise OriginalInputError('Generated scene/sky/arrow group identity mismatch')
        result = []
        for index, name in enumerate(plan.outputs):
            check_cancel(cancel)
            entry = _copy_outputs(outputs[name], destinations[name], checks[name]['bytes'], cancel)
            if entry.sha256 != checks[name]['sha256']:
                raise OriginalInputError('Generated map digest changed during publication')
            output.files[name] = entry
            result.append({'path': name, 'bytes': entry.size, 'sha256': entry.sha256, 'structure': checks[name]})
            if progress:
                progress('write-map-file', index + 1, len(plan.outputs))
        check_cancel(cancel)
        identity = {}
        for module in (pack, importlib.import_module('scene'), importlib.import_module('tex'),
                       importlib.import_module('igb'), importlib.import_module(__name__)):
            path = Path(module.__file__)
            identity[module.__name__] = hashlib.sha256(path.read_bytes()).hexdigest()
        import numpy
        import PIL
        return {'component': 'maps', 'recipe': ROUTE_ARROW_RECIPE if route_arrow_order else RECIPE,
                'route_arrow_rule': pack_state['route_arrow_rule'],
                'route_arrow_decodes': pack_state['route_arrow_decodes'],
                'city': plan.city, 'time': plan.time,
                'source_authority': plan.source_authority, 'readset_sha256': plan.readset_sha256,
                'source_read_set': [vars(item) for item in plan.inputs], 'code_sha256': identity,
                'numpy_version': numpy.__version__, 'pillow_version': PIL.__version__,
                'dependency_checks': dependencies,
                'files': result, 'unsupported_optional_gloss': optional_gloss,
                'profile_rules': pack_state['profile_rules'],
                'profile_rule_applications': pack_state['profile_rule_applications'],
                'profile_rule_layer_exclusions': pack_state['profile_rule_layer_exclusions'],
                'scratch': str(scratch), 'complete_dataset': False,
                'activated': False, 'android_executed': False,
                'limits': ['cooperative per-file/model/phase cancellation, not a CPU or memory sandbox',
                           'pack buffers library, meshes, split geometry and output blob in process',
                           'source16 recipe differs from legacy ASTC/HQ profile; hashes are observed only']}
    finally:
        _PACK_LOCK.release()
