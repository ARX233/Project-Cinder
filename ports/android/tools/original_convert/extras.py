"""Original vinyl/traffic/lights/neon/tire/mini conversion components.

Uses trusted packaged algorithms and a verified private source snapshot. Metadata
plans are release-pinned; external result archives/receipts are not accepted.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
import threading

from .source import (VerifiedSnapshot, OwnedOutput, SourceEntry, OriginalInputError,
                     HASH, check_cancel, _unique_object)

_FIXED = frozenset(('fd3s.wpk','lights.bin','lights.wpk','minicourse.names','minicourse.wpk',
                    'neon.wpk','tiretrack.wpk','traffic/nze121.wpk','traffic/kzh100g.wpk',
                    'traffic/truck.wpk','traffic/rc2.wpk'))
_LOCK = threading.Lock()


@dataclass(frozen=True)
class ExtrasPlan:
    files: tuple
    sha256: str


def parse_plan(data, *, expected_sha256):
    if (not isinstance(data,bytes) or not 1 <= len(data) <= 64*1024 or
            not isinstance(expected_sha256,str) or not HASH.fullmatch(expected_sha256) or
            hashlib.sha256(data).hexdigest()!=expected_sha256):
        raise OriginalInputError('Extras plan must match the signed recipe pin')
    try:obj=json.loads(data.decode('utf-8','strict'),object_pairs_hook=_unique_object)
    except (UnicodeError,ValueError,RecursionError) as exc:raise OriginalInputError('Invalid extras JSON') from exc
    if (not isinstance(obj,dict) or set(obj)!={'schema','files'} or obj['schema']!='wmmt-original-extras-v1' or
            not isinstance(obj['files'],list) or len(obj['files'])!=66):
        raise OriginalInputError('Incomplete extras profile')
    files=[];previous='';seen=set();vinyl=0
    for row in obj['files']:
        if not isinstance(row,dict) or set(row)!={'path','bytes','sha256'}:raise OriginalInputError('Invalid extras row')
        name,size,digest=row['path'],row['bytes'],row['sha256']
        if (not isinstance(name,str) or not (name in _FIXED or re.fullmatch(r'vinyl/[A-Za-z0-9_]{1,96}\.vpk',name)) or
                name<=previous or name.casefold() in seen or type(size) is not int or not 8<=size<=64*1024*1024 or
                not isinstance(digest,str) or not HASH.fullmatch(digest)):
            raise OriginalInputError('Unsafe or invalid extras row')
        if name.startswith('vinyl/'):vinyl+=1
        files.append((name,SourceEntry(size,digest)));seen.add(name.casefold());previous=name
    if vinyl!=55 or not _FIXED.issubset({n for n,_ in files}):raise OriginalInputError('Incomplete extras ownership')
    return ExtrasPlan(tuple(files),expected_sha256)


def _cli(module,args):
    old=sys.argv
    try:
        sys.argv=[module.__name__,*map(str,args)]
        module.main()
    finally:sys.argv=old


def _check_file(path,expected,cancel):
    size=path.stat().st_size
    if size!=expected.size:raise OriginalInputError('Converted extras size differs from signed plan')
    h=hashlib.sha256()
    with path.open('rb') as f:
        while True:
            check_cancel(cancel);b=f.read(128*1024)
            if not b:break
            h.update(b)
    if h.hexdigest()!=expected.sha256:raise OriginalInputError('Converted extras hash differs from signed plan')


def convert_extras(snapshot,output,plan,*,scratch_parent,cancel=None,progress=None):
    if (not isinstance(snapshot,VerifiedSnapshot) or not isinstance(output,OwnedOutput) or
            not isinstance(plan,ExtrasPlan)):
        raise OriginalInputError('Verified source, owned output and authenticated extras profile required')
    if not _LOCK.acquire(False):raise OriginalInputError('Extras converter is already running')
    try:return _convert(snapshot,output,plan,scratch_parent,cancel,progress)
    finally:_LOCK.release()


def _convert(snapshot,output,plan,scratch_parent,cancel,progress):
    check_cancel(cancel)
    from .runtime_check import validate_runtime
    validate_runtime()
    import pack
    import pack_vinyl
    import pack_lights
    import pack_neon
    import pack_mini
    import pack_tire_track
    if pack.TEX_ASTC or pack.TEX_EXPORT or pack.TEX_UPSCALED:
        raise OriginalInputError('Extras recipe forbids external ASTC or texture overrides')
    root=snapshot.root
    expected=dict(plan.files)
    # Check every final path before the first output. Algorithms only receive new
    # owned destinations; they cannot overwrite a prior component or installation.
    targets={name:output.target(name) for name in expected}
    scratch=OwnedOutput(scratch_parent)
    completed=[]
    def finish(names):
        for name in names:
            check_cancel(cancel);_check_file(targets[name],expected[name],cancel)
            output.files[name]=expected[name]
            completed.append({'path':name,'bytes':expected[name].size,'sha256':expected[name].sha256})
            if progress:progress('convert-extras',len(completed),len(expected))
    for name in expected:
        if not name.startswith('vinyl/'):continue
        folder=Path(name).stem
        source='data/car/'+folder+'/car.lua'
        if source not in snapshot.readset.files:raise OriginalInputError('Vinyl source not in original read-set')
        check_cancel(cancel);pack_vinyl.pack_car(str(root),folder,str(targets[name]));finish([name])
    for model,brake in [('NZE121','toy_NZE121_Other'),('KZH100G','toy_KZH100G_Other'),
                        ('Truck','truck_other'),('RC2','sub_RC2_Other')]:
        name='traffic/'+model.lower()+'.wpk';data=root/'data/othercar';check_cancel(cancel)
        pack.main([str(targets[name]),'--chunk','0','--lit','--bgr','--solid-opaque',
                   str(data/('LOD_'+model)/'body_low.igb'),str(data/'brakelamp'/('brakelamp_'+brake+'.igb')),
                   '--shadow',str(data/('LOD_'+model)/'shadow.igb')]);finish([name])
    car=root/'data/car/maz_FD3S';check_cancel(cancel)
    pack.main([str(targets['fd3s.wpk']),'--chunk','100000',str(car/'normal/body.igb'),str(car/'tire.igb'),
               '--shade','--swap','fd3s_body01_white='+str(car/'normal/color/fd3s_body01_colA01.tga')]);finish(['fd3s.wpk'])
    check_cancel(cancel);_cli(pack_lights,[root/'data',output.root]);finish(['lights.bin','lights.wpk'])
    check_cancel(cancel);_cli(pack_neon,[root/'data',targets['neon.wpk']]);finish(['neon.wpk'])
    check_cancel(cancel)
    with targets['tiretrack.wpk'].open('xb') as f:f.write(pack_tire_track.make(root/'data/sprite/tirepattern.tga'))
    finish(['tiretrack.wpk'])
    # Legacy mini packing temporarily modifies trusted module globals and emits a
    # compile-time comparison header. Keep that header in separate owned scratch.
    old_meshes,old_objects=pack.scene.meshes,pack.OBJECTS
    try:
        check_cancel(cancel)
        _cli(pack_mini,[root,targets['minicourse.wpk'],scratch.root/'minicourse-observed.h'])
    finally:pack.scene.meshes=old_meshes;pack.OBJECTS=old_objects
    finish(['minicourse.wpk','minicourse.names'])
    if len(completed)!=66:raise OriginalInputError('Incomplete extras conversion')
    return {'component':'extras','source_readset_sha256':snapshot.readset.sha256,'plan_sha256':plan.sha256,
            'files':completed,'complete_dataset':False,'activated':False}
