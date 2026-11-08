"""FD-only binding for the trusted, budgeted original-conversion AO backend."""
import ctypes as C
import hashlib
import os
from pathlib import Path
import re

from .source import (OwnedOutput, OriginalInputError, ConversionCancelled, SourceEntry, check_cancel)

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

    def convert(self,source_fd,output_fd,*,limits=None,cancel=None):
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
        callback=POLL(poll)
        flag=Cancel(C.sizeof(Cancel),callback,None)
        code=self.lib.oa_bake_fd(source_fd,output_fd,C.byref(limit),C.byref(flag),C.byref(result))
        if callback_error:raise OriginalInputError('AO cancellation callback failed') from callback_error[0]
        if code==5:raise ConversionCancelled('AO conversion cancelled')
        if code!=0:
            message=bytes(result.message).split(b'\0',1)[0].decode('utf-8','replace')
            raise OriginalInputError('AO conversion rejected (%d): %s'%(code,message))
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


def bake_owned(backend,output,source_name,*,expected=None,cancel=None,progress=None):
    """Add one AO beside this job's own already-validated car WPK, never old data."""
    check_cancel(cancel)
    if not isinstance(backend,Backend) or not isinstance(output,OwnedOutput):
        raise OriginalInputError('AO requires a packaged backend and owned output job')
    if not isinstance(source_name,str) or not re.fullmatch(r'cars/[A-Za-z0-9_]+\.wpk',source_name):
        raise OriginalInputError('Only this job car WPKs may seed AO')
    source_entry=output.files.get(source_name)
    if not isinstance(source_entry,SourceEntry):raise OriginalInputError('Car WPK has not been validated in this job')
    if expected is not None and not isinstance(expected,SourceEntry):raise OriginalInputError('Invalid signed AO expectation')
    destination_name=source_name[:-4]+'.ao';destination=output.target(destination_name)
    source_fd=os.open(output.root/source_name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        if _hash_fd(source_fd,cancel)!=source_entry:raise OriginalInputError('Job car WPK changed before AO conversion')
        output_fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            result=backend.convert(source_fd,output_fd,cancel=cancel)
            check_cancel(cancel)
            observed=_hash_fd(output_fd,cancel)
            if result['output_bytes']!=observed.size or (expected is not None and observed!=expected):
                raise OriginalInputError('AO output does not match its signed completion profile')
            os.fsync(output_fd)
        finally:os.close(output_fd)
        if _hash_fd(source_fd,cancel)!=source_entry:raise OriginalInputError('Job car WPK changed during AO conversion')
    finally:os.close(source_fd)
    output.files[destination_name]=observed
    if progress:progress('bake-ambient-occlusion',1,1)
    return {'path':destination_name,'bytes':observed.size,'sha256':observed.sha256,'native':result,
            'complete_dataset':False,'activated':False,'expected_output_verified':expected is not None}
