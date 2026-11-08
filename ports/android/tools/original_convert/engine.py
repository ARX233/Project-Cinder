"""APK-owned original resource job entry point. No external result import path.

Only a complete APK-pinned original read-set is decoded, in a newly owned private
snapshot and output tree. Completion is a post-conversion integrity record, NOT a
legacy DMF signature and NOT ResourceStore readiness or an activation operation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid
from .source import (ReviewedReadSet,FileTreeSource,VerifiedSnapshot,OwnedOutput,SourceEntry,
                     OriginalInputError,HASH,check_cancel,source_path,_directory,_unique_object)

SCHEMA='wmmt-original-job-v1'
PROFILE_SCHEMA='wmmt-original-race-recipe-v1'
JOB_FIELDS=frozenset(('schema','job_id','nonce','profile_sha256','readset_sha256','recipe_sha256',
                      'source_kind','source_path','profile_id'))


def _json(data,limit):
    if not isinstance(data,bytes) or not 0<len(data)<=limit:raise OriginalInputError('Job/recipe byte budget')
    try:return json.loads(data.decode('utf-8','strict'),object_pairs_hook=_unique_object)
    except (UnicodeError,ValueError,RecursionError) as exc:raise OriginalInputError('Invalid job/recipe JSON') from exc


def _small(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or not 0<st.st_size<=limit:raise OriginalInputError('Invalid private job metadata')
        data=b''
        while len(data)<=st.st_size:
            block=os.read(fd,min(131072,st.st_size+1-len(data)))
            if not block:break
            data+=block
        after=os.fstat(fd)
        if len(data)!=st.st_size or (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise OriginalInputError('Private job metadata changed during read')
        return data
    finally:os.close(fd)


def validate_job(directory,bundle):
    """Service already confines this directory to Context.noBackupFilesDir."""
    raw=Path(directory)
    if not raw.is_absolute():raise OriginalInputError('Private job path must be absolute')
    root=_directory(raw)
    if root!=raw or root.parent.name!='re3dxplus-original-jobs':raise OriginalInputError('Unexpected private job namespace')
    try:
        name=str(uuid.UUID(root.name))
        if name!=root.name:raise ValueError()
    except (ValueError,AttributeError) as exc:raise OriginalInputError('Invalid private job UUID') from exc
    job=_json(_small(root/'job.json',1024*1024),1024*1024)
    if (not isinstance(job,dict) or set(job)!=JOB_FIELDS or job['schema']!=SCHEMA or job['job_id']!=name or
            not isinstance(job['nonce'],str) or not HASH.fullmatch(job['nonce'])):
        raise OriginalInputError('Invalid original job descriptor')
    for key in ('profile_sha256','readset_sha256','recipe_sha256','profile_id'):
        if job[key]!=bundle[key]:raise OriginalInputError('Original job differs from the APK release recipe')
    kind=job['source_kind'];relative=job['source_path']
    if (kind,relative) not in (('zip','incoming.zip'),('tree','incoming')):
        raise OriginalInputError('Job source must be the owned staged ZIP or directory')
    owner=('WMMT-ORIGINAL-JOB-1\njob\t%s\nnonce\t%s\nprofile\t%s\nEND\n'%(name,job['nonce'],job['profile_sha256'])).encode('utf-8')
    if _small(root/'owner.tsv',4096)!=owner:raise OriginalInputError('Private job owner binding mismatch')
    _directory(root/'snapshots');_directory(root/'outputs')
    if os.path.lexists(root/'completion.tsv'):raise OriginalInputError('Original job has already produced a completion record')
    return root,job


def parse_recipe(bundle):
    for data_key,pin_key,limit in (('readset','readset_sha256',8*1024*1024),('recipe','recipe_sha256',8*1024*1024)):
        data=bundle[data_key];pin=bundle[pin_key]
        if not isinstance(pin,str) or not HASH.fullmatch(pin) or not isinstance(data,bytes) or len(data)>limit or hashlib.sha256(data).hexdigest()!=pin:
            raise OriginalInputError('Packaged recipe/read-set pin mismatch')
    readset=ReviewedReadSet.parse(bundle['readset'],expected_sha256=bundle['readset_sha256'])
    if len(readset.files)!=13994:raise OriginalInputError('Incomplete successor source inventory')
    recipe=_json(bundle['recipe'],8*1024*1024)
    expected={'schema','profile_id','runtime','native','raw','wheels','cars','extras','media','outputs',
              'route_arrow_order','player_paints','player_paints_plan_sha256','smoke','smoke_plan_sha256'}
    if (not isinstance(recipe,dict) or set(recipe)!=expected or recipe['schema']!=PROFILE_SCHEMA or
            recipe['profile_id']!=bundle['profile_id'] or not isinstance(recipe['outputs'],list) or len(recipe['outputs'])!=1801 or
            not isinstance(recipe['raw'],list) or len(recipe['raw'])!=1030):
        raise OriginalInputError('Incomplete original recipe inventory')
    if (not isinstance(recipe['native'],dict) or set(recipe['native'])!={'liboa_native.so','liboc_media_overlay.so'} or
            any(not isinstance(h,str) or not HASH.fullmatch(h) for h in recipe['native'].values())):
        raise OriginalInputError('Incomplete native converter release pins')
    targets={};previous=''
    for row in recipe['outputs']:
        if not isinstance(row,dict) or set(row) not in ({'path','max_bytes','sha256','kind'},{'path','max_bytes','sha256','kind','ao_layout'}):
            raise OriginalInputError('Invalid reviewed output row')
        name=row['path'];source_path('data/'+name)
        if (name<=previous or name in targets or name=='main' or name.startswith('data/') or type(row['max_bytes']) is not int or
                not 0<=row['max_bytes']<=512*1024*1024 or row['kind'] not in ('fixed','ao','m4a','mp4') or
                (row['sha256'] is not None and (not isinstance(row['sha256'],str) or not HASH.fullmatch(row['sha256'])))):
            raise OriginalInputError('Unsafe or invalid output inventory')
        if row['sha256'] is None and row['kind'] not in ('ao','m4a','mp4'):raise OriginalInputError('Unreviewed generated output authority')
        if row['kind']=='ao' and 'ao_layout' not in row:raise OriginalInputError('AO ownership/dimensions are not specified')
        targets[name]=row;previous=name
    folded={p.casefold() for p in targets}
    if len(folded)!=1801:raise OriginalInputError('Case-aliased output inventory')
    raw_paths=set()
    for row in recipe['raw']:
        if not isinstance(row,dict) or set(row)!={'source','path'}:raise OriginalInputError('Invalid raw source mapping')
        source_path(row['source']);name=row['path']
        if name in raw_paths or name not in targets or row['source'] not in readset.files:raise OriginalInputError('Unbound raw source/output mapping')
        entry=readset.files[row['source']];target=targets[name]
        if target['sha256']!=entry.sha256 or target['max_bytes']!=entry.size:raise OriginalInputError('Raw bytes are not bound to the authenticated original')
        raw_paths.add(name)
    if recipe['route_arrow_order'] is not True:
        raise OriginalInputError('New vehicle restoration recipe requires original route image order')
    from . import player_paints
    player_plan=player_paints.parse_plan(_canonical(recipe['player_paints']),
                                        expected_sha256=recipe['player_paints_plan_sha256'])
    paint=recipe['player_paints'];target=targets.get('player-body-paints.bin')
    if (target is None or target['kind']!='fixed' or target['sha256']!=paint['bank_sha256'] or
            target['max_bytes']!=paint['bank_bytes']):
        raise OriginalInputError('Player paint output is not bound to signed recipe')
    for row in paint['source_files']:
        source=readset.files.get(row['path'])
        if source is None or source.size!=row['bytes'] or source.sha256!=row['sha256']:
            raise OriginalInputError('Player paint dependency is not bound to signed read-set')
    if any(name in readset.files for name in paint['absences']):
        raise OriginalInputError('Reviewed player paint source absence changed')
    from . import smoke
    smoke.parse_plan(_canonical(recipe['smoke']),expected_sha256=recipe['smoke_plan_sha256'])
    if targets.get(smoke.DEST)!={'path':smoke.DEST,'max_bytes':smoke.OUTPUT_BYTES,'sha256':smoke.OUTPUT_SHA256,'kind':'fixed'}:
        raise OriginalInputError('Smoke output is not fixed to lossless TSM1')
    for name,size,digest in smoke.SOURCES:
        if readset.files.get(name)!=SourceEntry(size,digest):raise OriginalInputError('Smoke source closure mismatch')
    if recipe['cars'].get('story_assembly') is not True:
        raise OriginalInputError('Successor requires explicit original story assembly geometry')
    from . import cars as car_component
    car_plan=_component_plan(car_component,recipe['cars'])
    for task in car_plan.tasks:
        row=targets.get(task.path)
        if row is None or row['kind']!='fixed' or row['sha256']!=task.sha256 or row['max_bytes']!=task.size:
            raise OriginalInputError('Story car task/output binding differs')
    for row in recipe['cars']['story_height']['source_files']:
        if readset.files.get(row['path'])!=SourceEntry(row['bytes'],row['sha256']):
            raise OriginalInputError('Story height dependency not bound to read-set')
    return readset,recipe,targets


def _canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n').encode('utf-8')


def _component_plan(module,value):
    data=_canonical(value)
    return module.parse_plan(data,expected_sha256=hashlib.sha256(data).hexdigest())


def _claim(output,name,targets,cancel):
    path=output.root/name;fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size>targets[name]['max_bytes']:raise OriginalInputError('Converted file type/size rejected: '+name)
        h=hashlib.sha256();offset=0
        while True:
            check_cancel(cancel);block=os.pread(fd,131072,offset)
            if not block:break
            offset+=len(block);h.update(block)
        entry=SourceEntry(offset,h.hexdigest());expected=targets[name]['sha256']
        if expected is not None and entry.sha256!=expected:raise OriginalInputError('Converted output differs from reviewed byte profile: '+name)
    finally:os.close(fd)
    output.files[name]=entry
    return entry


def _native_directory(feedback,recipe):
    path=Path(str(feedback.getNativeLibraryDir()))
    if not path.is_absolute() or not path.is_dir():raise OriginalInputError('Packaged extracted native-library directory unavailable')
    # No job/source path, environment command or dynamic downloaded library is used.
    for name in ('liboa_native.so','liboc_media_overlay.so'):
        p=path/name
        if not p.is_file() or p.is_symlink():raise OriginalInputError('Packaged native converter library missing: '+name)
        expected=recipe['native'].get(name)
        if not isinstance(expected,str) or not HASH.fullmatch(expected):raise OriginalInputError('Missing native-library release pin')
        with p.open('rb') as library:
            actual=hashlib.file_digest(library,'sha256').hexdigest()
        if actual!=expected:raise OriginalInputError('Native converter library differs from signed recipe: '+name)
    return path


def _convert_snapshot(snapshot,output,recipe,targets,scratch_parent,native_dir,*,cancel=None,progress=None):
    """Trusted pipeline core; host integration can exercise it without claiming Android."""
    import gc
    from . import wheels,extras,cars,media,maps,player_paints,smoke
    from .physics_image import convert_physics_image
    from .menu_support import OriginalSupport
    from .menu_car_data import from_elf
    from .menu_components import pack_hud,pack_meters,pack_navi
    from .full_menu import pack_full_menu
    from .ao import Backend,bake_owned
    start=time.monotonic();stages=[]
    def done(name,count):
        stages.append({'component':name,'files':count,'elapsed_seconds':round(time.monotonic()-start,3)})
        if progress:progress('completed-'+name,count,count)
        gc.collect()
    with FileTreeSource(snapshot.root,snapshot.readset) as source:
        for index,row in enumerate(recipe['raw']):
            output.copy_from(source,row['source'],row['path'],cancel=cancel)
            if progress:progress('copy-original-runtime-data',index+1,len(recipe['raw']))
        done('raw',1030)
        convert_physics_image(snapshot.root/'main',output.target('phys.img'),cancel=cancel,progress=progress)
        _claim(output,'phys.img',targets,cancel);done('physics',1)
        smoke.convert(snapshot,output,smoke.parse_plan(_canonical(recipe['smoke']),expected_sha256=recipe['smoke_plan_sha256']),cancel=cancel,progress=progress)
        _claim(output,smoke.DEST,targets,cancel);done('tire-smoke',1)
        cars.convert_cars(snapshot,output,_component_plan(cars,recipe['cars']),cancel=cancel,progress=progress);done('cars',265)
        paint_plan=player_paints.parse_plan(_canonical(recipe['player_paints']),
                                           expected_sha256=recipe['player_paints_plan_sha256'])
        player_paints.convert(snapshot,output,paint_plan,cancel=cancel,progress=progress)
        _claim(output,'player-body-paints.bin',targets,cancel);done('player-paints',1)
        wheels.convert_wheels(snapshot,output,_component_plan(wheels,recipe['wheels']),cancel=cancel,progress=progress);done('wheels',149)
        maps.check_dependencies()
        for city in ('tokyo','oosaka','hakone','nagoya','fukuoka'):
            for zone in ('daytime','night'):
                plan=maps.plan_maps(snapshot,city,zone,cancel=cancel)
                maps.convert_maps(plan,output,scratch_parent=scratch_parent,cancel=cancel,progress=progress,route_arrow_order=recipe['route_arrow_order'])
                for name in plan.outputs:_claim(output,name,targets,cancel)
                gc.collect()
        done('maps',40)
        extras.convert_extras(snapshot,output,_component_plan(extras,recipe['extras']),scratch_parent=scratch_parent,cancel=cancel,progress=progress);done('extras',66)
        support=OriginalSupport.from_main(snapshot.root/'main',cancel=cancel)
        car_data=from_elf(support.elf,snapshot.root/'data/car',cancel=cancel)
        def read(name,*,max_bytes,cancel=None):
            if name not in snapshot.readset.files:raise OriginalInputError('2D dependency missing from APK read-set: '+name)
            return source.read(name,max_bytes=max_bytes,cancel=cancel)
        pack_hud(support,read,output.target('hud.bin'),cancel=cancel,progress=progress);_claim(output,'hud.bin',targets,cancel)
        pack_meters(support,read,output.target('meters.bin'),car_data['pack_order'],cancel=cancel,progress=progress);_claim(output,'meters.bin',targets,cancel)
        for name,asset in (('navi.bin','SkNavi.igb'),('navi_oosaka.bin','OsNavi.igb'),('navi_hakone.bin','HkNavi.igb'),('navi_nagoya.bin','NkNavi.igb'),('navi_fukuoka.bin','FkNavi.igb')):
            pack_navi(support,read,output.target(name),asset,cancel=cancel,progress=progress);_claim(output,name,targets,cancel)
        pack_full_menu(support,read,output.target('menu.bin'),car_data,scratch_parent=scratch_parent,cancel=cancel,progress=progress)
        _claim(output,'menu.bin',targets,cancel);done('menu-hud-meters-navigation',8)
        media.convert_media(snapshot,output,_component_plan(media,recipe['media']),library=native_dir/'liboc_media_overlay.so',cancel=cancel,progress=progress);done('media',26)
        # Run the expensive AO stage last: validate all 2D/media dependencies and
        # wiring before spending hour-scale CPU time. Quality and recipe unchanged.
        ao=Backend(native_dir/'liboa_native.so')
        ao_names=sorted(p for p,row in targets.items() if row['kind']=='ao')
        if len(ao_names)!=214:raise OriginalInputError('Incomplete AO recipe')
        for index,name in enumerate(ao_names):
            bake_owned(ao,output,name[:-3]+'.wpk',cancel=cancel)
            if progress:progress('bake-ambient-occlusion',index+1,len(ao_names))
        done('ao',214)
        # Re-read every approved source after all native/Pillow/IGB work. The private
        # snapshot is read-only, but this detects accidental same-UID mutation too.
        for index,name in enumerate(sorted(snapshot.readset.files)):
            for _ in source.chunks(name,cancel=cancel):pass
            if progress:progress('reverify-original-input',index+1,len(snapshot.readset.files))
    if sum(row['files'] for row in stages)!=1801:raise OriginalInputError('Pipeline did not complete the entire dataset')
    return stages


def _ensure_signed_helpers():
    # Chaquopy's extract_packages includes stage and original_convert. Explicit
    # package import triggers eager extraction of stage/*.py at AssetFinder/app;
    # immutable adapter checks must see real packaged files, not virtual guesses.
    import importlib,sys
    stage=importlib.import_module('stage')
    expected=_directory(Path(__file__).absolute().parents[1]/'stage')
    origin=getattr(stage,'__file__',None)
    if origin is None or Path(origin).absolute()!=expected/'__init__.py':
        raise OriginalInputError('Refusing stage helpers outside the signed application package')
    for name in ('igb','tex','scene','pack','lualite','pack_cars','pack_vinyl','pack_lights','pack_neon','pack_mini','pack_tire_track','story_part_groups'):
        path=expected/(name+'.py')
        if path.is_symlink() or not path.is_file():raise OriginalInputError('Signed helper extraction is incomplete: '+name)
    if str(expected) not in sys.path:sys.path.insert(0,str(expected))


def run_job(job_dir,feedback):
    """Called only by the APK nonexported :convert service; never publishes data."""
    from .release_assets import load_bundle
    from .runtime_check import validate_runtime
    from .validation import verify_owned_outputs,completion_bytes
    bundle=load_bundle();root,job=validate_job(job_dir,bundle)
    readset,recipe,targets=parse_recipe(bundle)
    cancel=lambda:bool(feedback.isCancelled())
    def progress(stage,current,total):
        check_cancel(cancel);feedback.onProgress(str(stage),int(current),int(total))
    check_cancel(cancel)
    runtime=validate_runtime(expected_versions=recipe['runtime'])
    needed=readset.total_bytes+sum(row['max_bytes'] for row in targets.values())+128*1024*1024
    space=os.statvfs(root)
    if space.f_bavail*space.f_frsize<needed:raise OriginalInputError('Insufficient private storage for verified snapshot and complete output')
    native_dir=_native_directory(feedback,recipe)
    if job['source_kind']=='zip':
        from .archive import ArchiveSource
        source=ArchiveSource(root/'incoming.zip',readset,cancel=cancel)
    else:source=FileTreeSource(root/'incoming',readset)
    started=time.monotonic()
    with source:snapshot=VerifiedSnapshot.create(source,root/'snapshots',cancel=cancel,progress=progress)
    check_cancel(cancel)
    output=OwnedOutput(root/'outputs')
    _ensure_signed_helpers()
    stages=_convert_snapshot(snapshot,output,recipe,targets,root/'snapshots',native_dir,cancel=cancel,progress=progress)
    rows=verify_owned_outputs(output,targets,cancel=cancel,progress=progress)
    complete=completion_bytes(job,output,rows)
    check_cancel(cancel)
    fd=os.open(root/'completion.tsv',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    try:
        view=memoryview(complete)
        while view:
            check_cancel(cancel);n=os.write(fd,view)
            if n<=0:raise OriginalInputError('Completion record short write')
            view=view[n:]
        os.fsync(fd)
    finally:os.close(fd)
    # Main process must still re-read, verify, copy and atomically select. No Ready,
    # legacy DMF or user-output signature is created in this worker.
    return json.dumps({'schema':'wmmt-original-result-v1','job_id':job['job_id'],'profile_sha256':job['profile_sha256'],
                       'readset_sha256':readset.sha256,'recipe_sha256':job['recipe_sha256'],
                       'output':output.root.name,'files':1801,'source_files':len(readset.files),'source_bytes':snapshot.bytes,
                       'complete_dataset':True,'activated':False,'publication_authority':False,
                       'elapsed_seconds':round(time.monotonic()-started,3),'components':stages,
                       'runtime':runtime,'completion_sha256':hashlib.sha256(complete).hexdigest()},sort_keys=True,separators=(',',':'))
