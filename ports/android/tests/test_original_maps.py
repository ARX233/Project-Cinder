"""Map source16 plan/ownership/in-process tests.

Set ORIGINAL_MAPS_TEST_WORK to an owned scratch parent. No old runtime payload is
an input; synthetic unit trees are explicitly reviewed-root fixtures, never Ready.
The opt-in ORIGINAL_MAPS_ROOT tests audit the real source, and
ORIGINAL_MAPS_RUN_REAL=1 additionally runs Fukuoka daytime/night exactly once.
"""
import hashlib
import importlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

from tools.original_convert import maps
from tools.original_convert.source import OwnedOutput, OriginalInputError, ConversionCancelled


def scene_bytes(prefix='data/fukuoka/daytime/', ground='road.igb', short='build.igb'):
    return (f'AbsPath="{prefix}"\nCourseArrow="data/coursearrow/fk_coursearrow_distribution.igb"\n'
            f'GroundModel={{AbsPath .. "{ground}"}}\n'
            f'ShortRangeBuildModel={{AbsPath .. "{short}"}}\n'
            'LongRangeBuildModel={}\nFlareModel={}\nSkyBoxModel={AbsPath .. "sky.igb"}\n').encode()


def triangle_wpk():
    # One 1x1 RGB565 texture, one chunk, one indexed 3-vertex batch.
    h = struct.pack('<4sIIIfIII', b'WPK2', 1, 1, 1, 4000, 32, 96, 132)
    t = struct.pack('<48sHHIII', b'test', 1, 1, 0, 152, 2)
    c = struct.pack('<6fIII', 0, 0, 0, 1, 0, 1, 0, 1, 0)
    b = struct.pack('<HHIIII', 0, 0, 156, 3, 228, 3)
    v = b''.join(struct.pack('<5f4B', x, 0, z, 0, 0, 255, 255, 255, 255)
                 for x, z in ((0, 0), (1, 0), (0, 1)))
    return h + t + c + b + b'\xff\xff\0\0' + v + struct.pack('<3H', 0, 1, 2)


class MapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='maps-unit-', dir=os.environ.get('ORIGINAL_MAPS_TEST_WORK'))
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'original'
        self.root.mkdir()
        self.write('main', b'unit-fixture-not-executable')
        self.write('data/fukuoka/daytime/daytime.lua', scene_bytes())
        for name in ('road', 'build', 'sky', 'textures'):
            self.write('data/fukuoka/daytime/' + name + '.igb', b'unit-igb-placeholder')
        self.write('data/coursearrow/fk_coursearrow_distribution.igb', b'unit-arrow-placeholder')
        # No signature is asserted for these synthetic parser/ownership unit fixtures.
        self.pin = mock.patch.object(maps, 'MAIN_SHA256', hashlib.sha256(b'unit-fixture-not-executable').hexdigest())
        self.pin.start()
        self.addCleanup(self.pin.stop)
        # Synthetic fixtures never assert a signed source or Ready. Match the
        # private rule gate to that fixture for ownership-only conversion tests.
        self.rule_pin = mock.patch.object(maps, 'VERTEX_ABI_MAIN_SHA256',
                                         hashlib.sha256(b'unit-fixture-not-executable').hexdigest())
        self.rule_pin.start()
        self.addCleanup(self.rule_pin.stop)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as f:
            f.write(value)
        return path

    def plan(self, **kw):
        return maps.plan_maps(self.root, 'fukuoka', 'daytime', reviewed_root=True, **kw)

    def fakepack(self):
        p = types.ModuleType('unit_fake_pack')
        p.__file__ = maps.__file__
        p.VERTEX = None
        p.TEX_EXPORT = p.TEX_UPSCALED = None
        p.TEX_ASTC = 0
        p.IGB = lambda _: types.SimpleNamespace(of_type=lambda _: [])
        p.load_library = lambda _: {}
        p.decode_image = lambda *a: None
        p.scene = types.SimpleNamespace(meshes=lambda _: (None, []))
        p.collect = lambda *a, **k: ({}, [], [], [])
        p.build_batches = lambda *a: []
        calls = []

        def main(args):
            calls.append(tuple(args))
            # Invoke the real adapter's per-model cancellation/progress boundary.
            for name in args:
                if name.endswith('.igb'):
                    p.scene.meshes(name)
            payload = bytearray(triangle_wpk())
            if '--objects' in args:
                struct.pack_into('<I',payload,128,3)  # actual arrow object group 3
            with p.open(args[0], 'wb') as f:
                f.write(payload)
            if '--objects' in args:
                with p.open(args[0].replace('.wpk', '.names'), 'w') as f:
                    f.write('one-object\n')
        p.main = main
        return p, calls

    def convert(self, plan=None, output=None, cancel=None, progress=None, pack=None):
        p, calls = self.fakepack() if pack is None else pack
        original_import = importlib.import_module
        def modules(name):
            return p if name == 'pack' else original_import(name)
        with mock.patch.object(maps.importlib, 'import_module', side_effect=modules):
            result = maps.convert_maps(plan or self.plan(), output or OwnedOutput(self.base),
                                       scratch_parent=self.base, cancel=cancel, progress=progress)
        return result, p, calls

    def test_whitelist_and_traversal(self):
        for city, time in (('../tokyo', 'night'), ('osaka', 'daytime'), ('tokyo', '../night'), ('tokyo', 'DAYTIME')):
            with self.subTest(city=city, time=time), self.assertRaises(OriginalInputError):
                maps.plan_maps(self.root, city, time, reviewed_root=True)

    def test_reviewed_root_is_explicit_and_never_ready(self):
        with self.assertRaises(OriginalInputError):
            maps.plan_maps(self.root, 'fukuoka', 'daytime')
        plan = self.plan()
        self.assertEqual(plan.source_authority, 'explicit-reviewed-root')
        self.assertFalse(plan.describe()['complete_dataset'])
        self.assertFalse(plan.describe()['activated'])
        self.assertIsNone(plan.readset_sha256)

    def test_plan_lists_readset_and_outputs(self):
        p = self.plan()
        self.assertEqual(p.ground, ('data/fukuoka/daytime/road.igb',))
        self.assertEqual(p.short, ('data/fukuoka/daytime/build.igb',))
        self.assertEqual(p.long, ())
        self.assertEqual(p.outputs, ('fukuoka.wpk','arrows_fukuoka.wpk','arrows_fukuoka.names','sky_fukuoka.wpk'))
        self.assertEqual(len(p.inputs), 7)
        self.assertEqual(p.input_bytes, sum(v.size for v in p.inputs))
        self.assertEqual([v.path for v in p.inputs], sorted(v.path for v in p.inputs))

    def test_dynamic_and_traversal_lua_rejected(self):
        for source in (scene_bytes(ground='../road.igb'),
                       scene_bytes().replace(b'AbsPath .. "road.igb"', b'loadfile("x")()'),
                       scene_bytes() + b'GroundModel={}\n',
                       scene_bytes() + b'CourseArrow=loadfile("x")()\n',
                       scene_bytes() + b'AbsPath=function() end\n',
                       scene_bytes().replace(b'road.igb', b'ROAD.igb,evil')):
            with self.subTest(source=source), self.assertRaises(OriginalInputError):
                maps.parse_scene(source, 'data/fukuoka/daytime/')

    def test_legacy_comments_are_not_executed(self):
        source = b'-- \xff os.execute("x")\n--[[GroundModel={}]]\n' + scene_bytes()
        self.assertEqual(maps.parse_scene(source, 'data/fukuoka/daytime/')['GroundModel'][0],
                         'data/fukuoka/daytime/road.igb')

    def test_missing_model_rejected(self):
        # Removing only our test-owned fixture, never an original source member.
        (self.root/'data/fukuoka/daytime/road.igb').unlink()
        with self.assertRaisesRegex(OriginalInputError, 'Missing'):
            self.plan()

    def test_wrong_case_and_symlink_rejected(self):
        p = self.root/'data/fukuoka/daytime/road.igb'
        data = p.read_bytes()
        p.unlink()
        self.write('data/fukuoka/daytime/ROAD.igb', data)
        with self.assertRaises(OriginalInputError):
            self.plan()
        upper = self.root/'data/fukuoka/daytime/ROAD.igb'
        self.assertEqual(upper.resolve().parent, (self.root/'data/fukuoka/daytime').resolve())
        upper.unlink()
        p.symlink_to('textures.igb')
        with self.assertRaises(OriginalInputError):
            self.plan()

    def test_main_pin_mismatch_rejected(self):
        with mock.patch.object(maps, 'MAIN_SHA256', '0' * 64):
            with self.assertRaisesRegex(OriginalInputError, 'main SHA'):
                self.plan()

    def test_input_budgets_and_invalid_budget(self):
        with self.assertRaises(OriginalInputError):
            maps.Budgets(max_files=0)
        with self.assertRaises(OriginalInputError):
            self.plan(budgets=maps.Budgets(max_input_bytes=10))
        with self.assertRaises(OriginalInputError):
            self.plan(budgets=maps.Budgets(max_files=2))
        with self.assertRaises(OriginalInputError):
            self.plan(budgets=maps.Budgets(max_file_bytes=4))

    def test_cancel_before_plan_and_convert(self):
        with self.assertRaises(ConversionCancelled):
            self.plan(cancel=lambda: True)
        with self.assertRaises(ConversionCancelled):
            maps.convert_maps(self.plan(), OwnedOutput(self.base), scratch_parent=self.base, cancel=lambda: True)

    def test_plan_cannot_be_constructed_from_receipt(self):
        with self.assertRaises(OriginalInputError):
            maps.convert_maps(object(), OwnedOutput(self.base), scratch_parent=self.base)
        from dataclasses import replace
        with self.assertRaises(OriginalInputError):
            maps.convert_maps(replace(self.plan(), _token=None), OwnedOutput(self.base), scratch_parent=self.base)

    def test_overwrite_preflight_preserves_bytes(self):
        out = OwnedOutput(self.base)
        p = out.target('fukuoka.wpk')
        p.write_bytes(b'keep-existing')
        with self.assertRaises(OriginalInputError):
            maps.convert_maps(self.plan(), out, scratch_parent=self.base)
        self.assertEqual(p.read_bytes(), b'keep-existing')

    def test_changed_input_rejected_before_packer(self):
        plan = self.plan()
        p = self.root/'data/fukuoka/daytime/road.igb'
        p.write_bytes(b'changed')
        with self.assertRaises(OriginalInputError):
            self.convert(plan=plan)

    def test_external_overrides_rejected_even_after_import(self):
        for name in maps._FORBIDDEN_ENV:
            with self.subTest(name=name), mock.patch.dict(os.environ, {name: ''}):
                with self.assertRaises(OriginalInputError):
                    self.convert()
        fake = self.fakepack()
        fake[0].TEX_ASTC = 4
        with self.assertRaises(OriginalInputError):
            self.convert(pack=fake)

    def test_no_subprocess_and_direct_main_calls(self):
        with mock.patch('subprocess.Popen', side_effect=AssertionError('spawn forbidden')), \
             mock.patch('subprocess.run', side_effect=AssertionError('spawn forbidden')), \
             mock.patch('os.system', side_effect=AssertionError('shell forbidden')):
            report, pack, calls = self.convert()
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], 'fukuoka.wpk')
        self.assertEqual(calls[1][-1], 'data/coursearrow/fk_coursearrow_distribution.igb')
        self.assertIn('--objects', calls[1])
        self.assertEqual(calls[2][calls[2].index('--chunk')+1], '1000000')
        self.assertFalse(report['complete_dataset'])
        self.assertFalse(report['activated'])
        self.assertFalse(report['android_executed'])
        self.assertEqual(len(report['files']), 4)
        self.assertNotIn('open', pack.__dict__)

    def test_per_model_cancel_restores_pack_globals(self):
        fake = self.fakepack()
        original_scene = fake[0].scene
        stop = [False]
        def progress(phase, done, total):
            if phase == 'convert-map-model':
                stop[0] = True
        with self.assertRaises(ConversionCancelled):
            self.convert(pack=fake, cancel=lambda: stop[0], progress=progress)
        self.assertIs(fake[0].scene, original_scene)
        self.assertNotIn('open', fake[0].__dict__)
        self.assertFalse(maps._PACK_LOCK.locked())

    def test_optional_gloss_exception_is_role_and_format_scoped(self):
        import numpy as np
        class Image:
            index = 7
            def __init__(self, fmt):
                self.fmt = fmt
            def __getitem__(self, slot):
                return types.SimpleNamespace(i32={2:1,3:1,11:self.fmt}.get(slot,0))
        for fmt, gloss, diffuse, accepted in ((65536,True,False,True),
                (65536,False,False,False),(7,True,False,False),(65536,True,True,False)):
            with self.subTest(fmt=fmt, gloss=gloss, diffuse=diffuse):
                p, _ = self.fakepack()
                image = Image(fmt)
                lib = types.SimpleNamespace(string=lambda _: 'artist/optional-spec.tga')
                p.load_library = lambda _: {'spec':(lib,image)}
                tri = np.array([[0,1,2]], dtype=np.int32)
                mesh = {'name':'material-mesh','path':('BLOCK',),'matrix':np.eye(4,dtype=np.float32),
                        'verts':{'pos':np.zeros((3,3),dtype=np.float32)},'tris':tri,
                        'state':{'gloss':('spec','cube')} if gloss else {},
                        'image':'spec' if diffuse else None}
                p.scene = types.SimpleNamespace(meshes=lambda _: (lib,[mesh]))
                vertex = np.zeros((3,3),dtype=np.float32)
                def collect(paths,*a,**k):
                    p.scene.meshes(paths[0][1])
                    p.decode_image(lib,image)
                    return {},[],[(1,None,0,vertex,tri,None)],[]
                p.collect = collect
                p.build_batches = lambda parts,tex_index: [None]
                plan = self.plan()
                def run():
                    with maps._pack_context(p,plan,self.root,{},None,None) as state:
                        state['stage'] = 'fukuoka.wpk'
                        p.load_library(plan.textures)
                        p.collect([(1,plan.short[0])],{})
                        p.build_batches([(None,0,vertex,tri,None)],{})
                    return state
                if accepted:
                    state=run()
                    rows=state['unsupported_optional_gloss']
                    self.assertEqual(len(rows),1)
                    self.assertEqual(rows[0]['affected_batch_ids'],[0])
                    self.assertTrue(rows[0]['decode_skipped'])
                    self.assertEqual(rows[0]['source_relative_image'],plan.textures)
                    self.assertEqual(rows[0]['material_mesh'],'material-mesh')
                else:
                    with self.assertRaises(OriginalInputError):
                        run()
                self.assertNotIn('open',p.__dict__)

    def colored_mesh(self):
        import numpy as np
        colors = np.array([[1,7,213,31],[88,99,111,0],[255,0,4,255]],dtype='u1')
        verts = {'pos':np.arange(9,dtype='f4').reshape(3,3),
                 'uv':np.arange(6,dtype='f4').reshape(3,2),
                 'normal':np.array([[1,0,0],[0,1,0],[0,0,1]],dtype='f4'), 'color':colors}
        texture = types.SimpleNamespace(pixels=np.arange(16,dtype='u1').reshape(2,2,4))
        return {'name':'synthetic-material','path':('BLOCK',),'image':texture,
                'verts':verts,'tris':np.array([[0,1,2]],dtype='i4'),
                'matrix':np.eye(4,dtype='f4'),'state':{'blend':False}}

    def test_fukuoka_vertex_rule_copies_only_rb_and_preserves_all_other_fields(self):
        import numpy as np
        mesh = self.colored_mesh()
        original = mesh['verts']
        colors = original['color'].copy()
        unchanged = {key:mesh[key] for key in ('tris','matrix','state','image','path')}
        bytes_before = {key:original[key].tobytes() for key in ('pos','uv','normal')}
        matrix_before, tris_before = mesh['matrix'].tobytes(), mesh['tris'].tobytes()
        pixels_before = mesh['image'].pixels.tobytes()
        rule = maps.profile_rules(self.plan())[0]
        counts = maps._normalize_vertex_colors([mesh],rule)
        np.testing.assert_array_equal(mesh['verts']['color'],colors[:,[2,1,0,3]])
        np.testing.assert_array_equal(mesh['verts']['color'][:,[1,3]],colors[:,[1,3]])
        np.testing.assert_array_equal(original['color'],colors)  # no source-array mutation
        self.assertIsNot(mesh['verts'],original)
        for key in ('pos','uv','normal'):
            self.assertIs(mesh['verts'][key],original[key])
            self.assertEqual(mesh['verts'][key].tobytes(),bytes_before[key])
        self.assertEqual(mesh['matrix'].tobytes(),matrix_before)
        self.assertEqual(mesh['tris'].tobytes(),tris_before)
        self.assertEqual(mesh['image'].pixels.tobytes(),pixels_before)
        for key, value in unchanged.items():
            self.assertIs(mesh[key],value)
        self.assertEqual(counts,{'colored_meshes':1,'vertices':3})
        self.assertEqual(rule['id'],'fukuoka-vertex-rb-runtime-abi-v1')
        self.assertEqual(rule['channels'],[2,1,0,3])
        self.assertEqual(rule['kind'],'runtime-abi-normalization')

    def test_vertex_rule_tokyo_is_the_only_city_noop(self):
        from dataclasses import replace
        plan = replace(self.plan(),city='tokyo')
        self.assertEqual(maps.profile_rules(plan),[])
        mesh = self.colored_mesh()
        original = mesh['verts']
        counts = maps._normalize_vertex_colors([mesh],None)
        self.assertIs(mesh['verts'],original)
        self.assertEqual(counts,{'colored_meshes':0,'vertices':0})
        with self.assertRaises(OriginalInputError):
            maps.profile_rules(replace(plan,city='unknown'))

    def test_all_four_non_tokyo_rules_preserve_fields_and_bind_city(self):
        from dataclasses import replace
        import numpy as np
        for city in ('oosaka','hakone','nagoya','fukuoka'):
            with self.subTest(city=city):
                plan = replace(self.plan(),city=city)
                rules = maps.profile_rules(plan)
                self.assertEqual(len(rules),1)
                rule = rules[0]
                self.assertEqual(rule['city'],city)
                self.assertEqual(rule['layer'],'main-scene')
                self.assertEqual(rule['main_output'],plan.outputs[0])
                self.assertEqual(rule['excluded_layers'],['coursearrow','sky'])
                self.assertEqual(rule['id'],city+'-vertex-rb-runtime-abi-v1')
                self.assertEqual(rule['main_sha256'],maps.VERTEX_ABI_MAIN_SHA256)
                mesh = self.colored_mesh()
                verts = mesh['verts'];colors = verts['color'].copy()
                before = {key:verts[key].tobytes() for key in ('pos','uv','normal')}
                indices,matrix,pixels = mesh['tris'].tobytes(),mesh['matrix'].tobytes(),mesh['image'].pixels.tobytes()
                self.assertEqual(maps._normalize_vertex_colors([mesh],rule),{'colored_meshes':1,'vertices':3})
                np.testing.assert_array_equal(mesh['verts']['color'],colors[:,[2,1,0,3]])
                np.testing.assert_array_equal(mesh['verts']['color'][:,[1,3]],colors[:,[1,3]])
                np.testing.assert_array_equal(verts['color'],colors)
                for key in ('pos','uv','normal'):
                    self.assertIs(mesh['verts'][key],verts[key])
                    self.assertEqual(mesh['verts'][key].tobytes(),before[key])
                self.assertEqual(mesh['tris'].tobytes(),indices)
                self.assertEqual(mesh['matrix'].tobytes(),matrix)
                self.assertEqual(mesh['image'].pixels.tobytes(),pixels)
        with self.assertRaises(OriginalInputError):
            maps._normalize_vertex_colors([self.colored_mesh()],{'city':'tokyo','id':'tokyo-vertex-rb-runtime-abi-v1'})

    def test_vertex_rule_requires_fixed_main_and_rejects_shape_type_changes(self):
        from dataclasses import replace
        import numpy as np
        plan = self.plan()
        with mock.patch.object(maps,'VERTEX_ABI_MAIN_SHA256',
                               '2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6'):
            with self.assertRaisesRegex(OriginalInputError,'fixed reviewed main'):
                maps.profile_rules(plan)
        with self.assertRaises(OriginalInputError):
            maps.profile_rules(replace(plan,inputs=tuple(item for item in plan.inputs if item.path!='main')))
        rule = maps.profile_rules(plan)[0]
        for colors in (np.zeros((3,3),dtype='u1'),np.zeros((3,4),dtype='f4')):
            mesh = self.colored_mesh();mesh['verts']['color']=colors
            with self.assertRaisesRegex(OriginalInputError,'colour ABI'):
                maps._normalize_vertex_colors([mesh],rule)
        mesh = self.colored_mesh();mesh['verts'].pop('color');old=mesh['verts']
        self.assertEqual(maps._normalize_vertex_colors([mesh],rule),{'colored_meshes':0,'vertices':0})
        self.assertIs(mesh['verts'],old)

    def test_vertex_rule_runs_in_scoped_mesh_adapter_and_records_provenance(self):
        import numpy as np
        plan = self.plan()
        p,_ = self.fakepack()
        mesh = self.colored_mesh()
        before = mesh['verts']['color'].copy()
        p.scene = types.SimpleNamespace(meshes=lambda _: (None,[mesh]))
        with maps._pack_context(p,plan,self.root,{},None,None) as state:
            state['stage']='fukuoka.wpk'
            _,returned=p.scene.meshes(plan.short[0])
        np.testing.assert_array_equal(returned[0]['verts']['color'],before[:,[2,1,0,3]])
        self.assertEqual(len(state['profile_rules']),1)
        self.assertEqual(state['profile_rule_applications'],[
            {'id':maps.FUKUOKA_VERTEX_RULE,'model':plan.short[0],'stage':'fukuoka.wpk',
             'layer':'main-scene','colored_meshes':1,'vertices':3}])
        self.assertNotIn('open',p.__dict__)

    def test_colored_coursearrow_and_sky_are_excluded_in_all_cities(self):
        from dataclasses import replace
        import numpy as np
        for city in maps.CITIES:
            outputs=(city+'.wpk','arrows_'+city+'.wpk','arrows_'+city+'.names','sky_'+city+'.wpk')
            plan=replace(self.plan(),city=city,outputs=outputs)
            for layer,stage,model in (('main-scene',outputs[0],plan.short[0]),
                                      ('coursearrow',outputs[1],plan.arrow),
                                      ('sky',outputs[3],plan.sky[0])):
                with self.subTest(city=city,layer=layer):
                    p,_=self.fakepack();mesh=self.colored_mesh()
                    original=mesh['verts'];colors=original['color'].copy()
                    untouched={key:original[key].tobytes() for key in ('pos','uv','normal')}
                    texture=mesh['image'].pixels.tobytes()
                    p.scene=types.SimpleNamespace(meshes=lambda _: (None,[mesh]))
                    with maps._pack_context(p,plan,self.root,{},None,None) as state:
                        state['stage']=stage
                        p.scene.meshes(model)
                    applies=city!='tokyo' and layer=='main-scene'
                    np.testing.assert_array_equal(mesh['verts']['color'],colors[:,[2,1,0,3]] if applies else colors)
                    np.testing.assert_array_equal(original['color'],colors)
                    for key in ('pos','uv','normal'):
                        self.assertIs(mesh['verts'][key],original[key])
                        self.assertEqual(mesh['verts'][key].tobytes(),untouched[key])
                    self.assertEqual(mesh['image'].pixels.tobytes(),texture)
                    self.assertEqual(len(state['profile_rule_applications']),1 if applies else 0)
                    if city!='tokyo' and not applies:
                        self.assertEqual(state['profile_rule_layer_exclusions'][0]['layer'],layer)
                        self.assertFalse(state['profile_rule_layer_exclusions'][0]['normalized'])
                    if city=='tokyo':
                        self.assertIs(mesh['verts'],original)
                        self.assertEqual(state['profile_rule_layer_exclusions'],[])

    def test_main_phase_cannot_normalize_an_independent_arrow_or_sky_input(self):
        from dataclasses import replace
        import numpy as np
        for city in maps.VERTEX_ABI_CITIES:
            plan=replace(self.plan(),city=city)
            rule=maps.profile_rules(plan)[0]
            self.assertIs(maps._main_scene_color_rule(plan,plan.short[0],plan.outputs[0],rule),rule)
            for model in (plan.arrow,plan.sky[0],plan.textures):
                with self.subTest(city=city,model=model):
                    self.assertIsNone(maps._main_scene_color_rule(plan,model,plan.outputs[0],rule))
                    mesh=self.colored_mesh();colors=mesh['verts']['color'].copy()
                    p,_=self.fakepack();p.scene=types.SimpleNamespace(meshes=lambda _: (None,[mesh]))
                    with maps._pack_context(p,plan,self.root,{},None,None) as state:
                        state['stage']=plan.outputs[0]
                        p.scene.meshes(model)
                    np.testing.assert_array_equal(mesh['verts']['color'],colors)
                    self.assertEqual(state['profile_rule_applications'],[])

    def test_numeric_backend_failure_precedes_scratch_or_outputs(self):
        import numpy
        out = OwnedOutput(self.base)
        before = set(self.base.iterdir())
        with mock.patch.object(numpy, 'array_equal', return_value=False):
            with self.assertRaisesRegex(OriginalInputError, 'float32 matrix backend'):
                self.convert(output=out)
        self.assertEqual(set(self.base.iterdir()), before)
        self.assertEqual(list(out.root.iterdir()), [])

    def test_scratch_output_budgets(self):
        with self.assertRaises(OriginalInputError):
            self.convert(plan=self.plan(budgets=maps.Budgets(max_scratch_bytes=16)))
        with self.assertRaises(OriginalInputError):
            self.convert(plan=self.plan(budgets=maps.Budgets(max_output_bytes=32)))

    def test_source_output_overlap_rejected(self):
        with self.assertRaises(OriginalInputError):
            self.convert(output=OwnedOutput(self.root))

    def test_wpk_structure_and_bytes(self):
        p = self.base/'unit.wpk'
        p.write_bytes(triangle_wpk())
        result = maps.inspect_wpk(p)
        self.assertEqual(result['sha256'], hashlib.sha256(triangle_wpk()).hexdigest())
        self.assertEqual((result['textures'], result['chunks'], result['batches'], result['triangles']), (1,1,1,1))
        self.assertEqual(result['texture_formats'], [0])
        self.assertIsNone(result['gloss'])
        bad = bytearray(triangle_wpk())
        struct.pack_into('<I', bad, 32+52, 3)  # ASTC is not allowed in source16 recipe
        p.write_bytes(bad)
        with self.assertRaises(OriginalInputError):
            maps.inspect_wpk(p)
        bad = bytearray(triangle_wpk())
        struct.pack_into('<H', bad, 228, 3)  # index out of range
        p.write_bytes(bad)
        with self.assertRaises(OriginalInputError):
            maps.inspect_wpk(p)

    def test_no_old_resource_or_process_code_dependency(self):
        source = Path(maps.__file__).read_text()
        self.assertNotIn('import subprocess', source)
        self.assertNotIn('os.system(', source)
        self.assertNotIn('sys.executable', source)
        self.assertNotIn('Unicorn', source)
        self.assertNotIn('ResourceStore.Ready(', source)


@unittest.skipUnless(os.environ.get('ORIGINAL_MAPS_ROOT'), 'set ORIGINAL_MAPS_ROOT for real original audit')
class RealMapTests(unittest.TestCase):
    def test_ten_real_plans_and_tokyo_shell_order(self):
        root = os.environ['ORIGINAL_MAPS_ROOT']
        plans = {(c,t): maps.plan_maps(root,c,t,reviewed_root=True) for c in maps.CITIES for t in maps.TIMES}
        day, night = plans['tokyo','daytime'], plans['tokyo','night']
        self.assertEqual(tuple(map(len,(day.ground,day.short,day.long,day.sky))), (46,30,13,2))
        self.assertEqual(tuple(map(len,(night.ground,night.short,night.long,night.sky))), (46,19,33,2))
        self.assertTrue(day.short[13].endswith('/wg_area01_kanban.igb'))
        self.assertTrue(night.long[6].endswith('/sk_searchlight.igb'))
        self.assertEqual([Path(p).stem for p in day.ground[-4:]], list(maps.OTHER))
        # Compare EVERY model and its order against the reviewed existing shell,
        # without running that shell or taking a guessed union of Lua arrays.
        import re
        shell = (Path(__file__).resolve().parents[1]/'tools/stage/pack_tokyo.sh')
        if shell.is_file():
            text = shell.read_text()
            makers = re.search(r'MAKERS="([^"]+)"', text)[1].split()
            other = re.search(r'OTHER="([^"]+)"', text)[1].split()
            night_block = text.split('if [ "$TIME" = night ]; then',1)[1].split('else',1)[0]
            day_block = text.split('\nelse\n',1)[1].split('\nfi',1)[0]
            for plan, block in ((day,day_block),(night,night_block)):
                for key, attr in (('G','ground'),('S','short'),('L','long'),('SKY','sky')):
                    words = re.search(r'\b'+key+r'="([^"]+)"',block)[1].split()
                    expected = []
                    for word in words:
                        expected.extend(makers if word=='$MAKERS' else other if word=='$OTHER' else [word])
                    self.assertEqual([Path(p).stem for p in getattr(plan,attr)],expected)
        with (Path(root)/'main').open('rb') as f:
            lines = maps.barricade_text(f.read()).decode('ascii').splitlines()
        self.assertEqual(len(lines), 127)
        self.assertTrue(all(len(line.split()) == 7 for line in lines[1:]))

    @unittest.skipUnless(os.environ.get('ORIGINAL_MAPS_RUN_REAL') == '1', 'full conversion opt-in; avoid duplicate CPU work')
    def test_real_fukuoka_day_night(self):
        work = os.environ['ORIGINAL_MAPS_TEST_WORK']
        for time in maps.TIMES:
            plan = maps.plan_maps(os.environ['ORIGINAL_MAPS_ROOT'],'fukuoka',time,reviewed_root=True)
            out = OwnedOutput(work)
            with mock.patch('subprocess.Popen', side_effect=AssertionError('spawn forbidden')):
                report = maps.convert_maps(plan,out,scratch_parent=work)
            self.assertEqual(len(report['files']),4)
            for row in report['files']:
                self.assertEqual(hashlib.sha256((out.root/row['path']).read_bytes()).hexdigest(), row['sha256'])
                if row['path'].endswith('.wpk'):
                    self.assertGreater(row['structure']['triangles'],0)
                    self.assertTrue(set(row['structure']['texture_formats']) <= {0,1,2})


if __name__ == '__main__':
    unittest.main()
