"""FD-only binding for the trusted, budgeted original-conversion AO backend."""
import ctypes as C
import hashlib
import os
from pathlib import Path
import re
from threading import Event

from .source import (OwnedOutput, OriginalInputError, ConversionCancelled, SourceEntry, check_cancel)
from .work_queue import run_parallel

# A separately pinned implementation of the existing 256/96 recipe. Keep the
# resource profile identity so earlier verified installations remain usable.
SERIAL_AO_SHA256 = 'b730592c4e68407c281bc02c1863d3a4b12406dfa3af144b0c5c92d8e058b7a9'
PARALLEL_AO_SHA256 = 'b4cb0a9cc57ebb0dd3a8864af3f4f3a2b6adc3b066dd298609ff3b814c207e2c'

# The Android service owns the overall deadline (normally four hours).
MAX_AO_JOB_WALL_MS = 6 * 60 * 60 * 1000
MAX_AO_WORKERS = 8

POLL=C.CFUNCTYPE(C.c_int,C.c_void_p)


class Limits(C.Structure):
    _fields_=[('struct_size',C.c_uint32),('abi_version',C.c_uint32)]+[
        (n,C.c_uint64) for n in ('max_source_bytes','max_heap_bytes','max_output_bytes',
                                'max_work_units','max_wall_ms','max_cpu_ms')]+[
        (n,C.c_uint32) for n in ('max_textures','max_chunks','max_batches','max_triangles',
                                'max_maps','max_texture_dimension','size','rays')]


class Cancel(C.Structure):
    _fields_=[('struct_size',C.c_uint32),('poll',POLL),('user',C.c_void_p)]


class Result(C.Structure):
    _fields_=[('struct_size',C.c_uint32),('abi_version',C.c_uint32),('status',C.c_int32),('system_errno',C.c_int32)]+[
        (n,C.c_uint64) for n in ('source_bytes','output_bytes','heap_peak_bytes','work_units',
                                'elapsed_wall_ms','elapsed_cpu_ms','allocations_live')]+[
        ('maps',C.c_uint32),('triangles',C.c_uint32),('message',C.c_char*160)]


class _StopSignal:
    def __init__(self,backend):
        self.flag=C.c_uint32()
        self.poll=POLL(('oa_poll_stop',backend.lib))
        self.request=backend.lib.oa_request_stop
        self.request.argtypes=[C.POINTER(C.c_uint32)]
        self.request.restype=None
        self.event=Event()

    def set(self):
        self.request(C.byref(self.flag))
        self.event.set()

    def is_set(self):
        return self.event.is_set()

    def native_cancel(self):
        return Cancel(C.sizeof(Cancel),self.poll,C.cast(C.pointer(self.flag),C.c_void_p))


class Backend:
    def __init__(self,library):
        path=Path(library)
        if not path.is_absolute() or not path.is_file():
            raise OriginalInputError('AO backend must be an absolute packaged native library')
        self.path=path
        self.lib=C.CDLL(str(path))
        self.lib.oa_default_limits.argtypes=[C.POINTER(Limits)]
        self.lib.oa_default_limits.restype=None
        self.lib.oa_bake_fd.argtypes=[C.c_int,C.c_int,C.POINTER(Limits),C.POINTER(Cancel),C.POINTER(Result)]
        self.lib.oa_bake_fd.restype=C.c_int

    def limits(self):
        value=Limits();self.lib.oa_default_limits(C.byref(value))
        if value.struct_size!=C.sizeof(Limits) or value.abi_version!=1 or value.size!=256 or value.rays!=96:
            raise OriginalInputError('AO backend ABI/recipe mismatch')
        return value

    def convert(self,source_fd,output_fd,*,limits=None,cancel=None,stop=None):
        """Caller must own immutable source and O_EXCL-created empty output FDs."""
        check_cancel(cancel)
        if type(source_fd) is not int or type(output_fd) is not int or source_fd<0 or output_fd<0:
            raise OriginalInputError('AO requires owned file descriptors')
        limit=limits if limits is not None else self.limits()
        if not isinstance(limit,Limits):raise OriginalInputError('Invalid AO limits')
        result=Result();result.struct_size=C.sizeof(Result)
        callback_error=[]
        def poll(_):
            try:return int(bool(cancel and cancel()))
            except BaseException as exc:
                callback_error.append(exc);return 1
        flag=None
        if stop is not None:
            flag=stop.native_cancel()
        elif cancel is not None:
            flag=Cancel(C.sizeof(Cancel),POLL(poll),None)
        code=self.lib.oa_bake_fd(source_fd,output_fd,C.byref(limit),C.byref(flag) if flag is not None else None,C.byref(result))
        if callback_error:raise OriginalInputError('AO cancellation callback failed') from callback_error[0]
        if code==5:raise ConversionCancelled('AO conversion cancelled')
        if code!=0:
            message=bytes(result.message).split(b'\0',1)[0].decode('utf-8','replace')
            raise OriginalInputError('AO conversion rejected (%d): %s (wall %.1fs, CPU %.1fs)'%(
                code,message,result.elapsed_wall_ms/1000,result.elapsed_cpu_ms/1000))
        if result.status!=0 or result.abi_version!=1 or result.allocations_live!=0:
            raise OriginalInputError('AO backend returned an invalid completion record')
        return {n:int(getattr(result,n)) for n in ('source_bytes','output_bytes','heap_peak_bytes','work_units',
                    'elapsed_wall_ms','elapsed_cpu_ms','maps','triangles','allocations_live')}


def _hash_fd(fd,cancel):
    digest=hashlib.sha256();count=0;offset=0
    while True:
        check_cancel(cancel);b=os.pread(fd,128*1024,offset)
        if not b:break
        offset+=len(b);count+=len(b);digest.update(b)
    return SourceEntry(count,digest.hexdigest())


def _plan_bake(output,source_name):
    if not isinstance(output,OwnedOutput):
        raise OriginalInputError('AO requires an owned output job')
    if not isinstance(source_name,str) or not re.fullmatch(r'cars/[A-Za-z0-9_]+\.wpk',source_name):
        raise OriginalInputError('Only this job car WPKs may seed AO')
    source_entry=output.files.get(source_name)
    if not isinstance(source_entry,SourceEntry):
        raise OriginalInputError('Car WPK has not been validated in this job')
    return output.root/source_name,source_entry,output.target(source_name[:-4]+'.ao')


def _bake(backend,source,source_entry,destination,*,expected=None,cancel=None,stop=None,limits=None):
    check_cancel(cancel)
    source_fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        if _hash_fd(source_fd,cancel)!=source_entry:raise OriginalInputError('Job car WPK changed before AO conversion')
        output_fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            try:
                result=backend.convert(source_fd,output_fd,limits=limits,cancel=cancel if stop is None else None,stop=stop)
            except OriginalInputError as exc:
                if isinstance(exc,ConversionCancelled):
                    raise
                raise OriginalInputError(f'{source.name}: {exc}') from exc
            check_cancel(cancel)
            observed=_hash_fd(output_fd,cancel)
            if result['output_bytes']!=observed.size or (expected is not None and observed!=expected):
                raise OriginalInputError('AO output does not match its signed completion profile')
            os.fsync(output_fd)
        finally:os.close(output_fd)
        if _hash_fd(source_fd,cancel)!=source_entry:raise OriginalInputError('Job car WPK changed during AO conversion')
    finally:os.close(source_fd)
    return observed,result


def bake_owned(backend,output,source_name,*,expected=None,cancel=None,progress=None):
    """Add one AO beside this job's own already-validated car WPK."""
    check_cancel(cancel)
    if not isinstance(backend,Backend):
        raise OriginalInputError('AO requires a packaged backend')
    if expected is not None and not isinstance(expected,SourceEntry):
        raise OriginalInputError('Invalid signed AO expectation')
    plan=_plan_bake(output,source_name)
    observed,result=_bake(backend,*plan,expected=expected,cancel=cancel)
    destination_name=source_name[:-4]+'.ao'
    output.files[destination_name]=observed
    if progress:progress('bake-ambient-occlusion',1,1)
    return {'path':destination_name,'bytes':observed.size,'sha256':observed.sha256,'native':result,
            'complete_dataset':False,'activated':False,'expected_output_verified':expected is not None}


def bake_owned_many(backend,output,source_names,*,workers,worker_limit=None,cancel=None,progress=None,wall_budget_ms=None,on_baked=None):
    """Run independent native bakes. Only the coordinator updates job receipts."""
    check_cancel(cancel)
    if not isinstance(backend,Backend) or type(workers) is not int or not 1<=workers<=MAX_AO_WORKERS:
        raise OriginalInputError('AO worker count must be 1 to 8 for a packaged backend')
    names=tuple(source_names)
    if len(names)!=len(set(names)):
        raise OriginalInputError('Duplicate AO job destination')
    total=len(names)
    limits=backend.limits()
    if wall_budget_ms is not None:
        if type(wall_budget_ms) is not int or not 1<=wall_budget_ms<=MAX_AO_JOB_WALL_MS or cancel is None:
            raise OriginalInputError('AO job wall budget requires a bounded cancellable job')
        # Wall time includes time spent descheduled. The service still cancels
        # at its original deadline and the native CPU/work quotas remain active.
        limits.max_wall_ms=wall_budget_ms
    plans=[_plan_bake(output,name) for name in names]
    completed = 0

    def commit(plan, result):
        nonlocal completed
        observed, _ = result
        name = plan[2].relative_to(output.root).as_posix()
        output.files[name] = observed
        if on_baked:
            on_baked(name)
        completed += 1
        if progress:
            progress('bake-ambient-occlusion', completed, total)

    if workers == 1:
        for plan in plans:
            commit(plan, _bake(backend, *plan, cancel=cancel, limits=limits))
        return min(total, 1)

    # Only the coordinator calls Java; running native workers observe a local flag.
    stopped = _StopSignal(backend)

    def convert(plan):
        return _bake(backend, *plan, cancel=stopped.is_set, stop=stopped, limits=limits)

    return run_parallel(plans, convert, commit, capacity=workers,
                        worker_limit=worker_limit or (lambda: workers),
                        cancel=cancel, stop=stopped.set)
