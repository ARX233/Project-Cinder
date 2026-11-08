"""Additive ABI2 loader. No subprocess/network. PNG input is a parent-validated FD."""
import ctypes as C
import fcntl
import io
import os
import stat
import warnings
try:
    from .media_ctypes import Backend, Limits, Result, Cancel
except ImportError:
    from media_ctypes import Backend, Limits, Result, Cancel

class Overlay(C.Structure):
    _fields_=[('abi',C.c_uint32),('size',C.c_uint32),('width',C.c_uint32),('height',C.c_uint32),('stride_bytes',C.c_uint32),('x',C.c_int32),('y',C.c_int32),('flags',C.c_uint32),('rgba_bytes',C.c_uint64),('rgba',C.POINTER(C.c_uint8))]
    def __init__(self,rgba,width,height,x=29,y=18):
        super().__init__()
        if not(0<width<=512 and 0<height<=128 and width*height<=65536 and x>=0 and y>=0 and x+width<=640 and y+height<=480):raise ValueError('overlay dimensions/offset budget')
        if len(rgba)!=width*height*4:raise ValueError('exact RGBA byte length required')
        self._pixels=C.create_string_buffer(bytes(rgba),len(rgba));self._origin_identity=None
        self.abi=2;self.size=C.sizeof(self);self.width=width;self.height=height;self.stride_bytes=width*4;self.x=x;self.y=y;self.rgba_bytes=len(rgba);self.rgba=C.cast(self._pixels,C.POINTER(C.c_uint8))

def load_png_overlay_fd(fd,*,x=29,y=18,other_fds=(),max_png_bytes=1024*1024):
    """Strict single PNG, bounded before pixel decode; preserves input FD offset.
    Parent must resolve the FD inside its immutable approved snapshot, never pass
    a device/pipe, and pass source/audio/output FDs in other_fds for inode checks.
    A bounded <=1MiB PNG is buffered; movies are never buffered here.
    """
    from PIL import Image
    st=os.fstat(fd);identity=(st.st_dev,st.st_ino)
    if not stat.S_ISREG(st.st_mode) or not(0<st.st_size<=max_png_bytes<=1024*1024):raise ValueError('PNG regular-file/byte budget')
    if fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE==os.O_WRONLY:raise ValueError('PNG FD not readable')
    for other in other_fds:
        if other is not None and other>=0:
            s=os.fstat(other)
            if (s.st_dev,s.st_ino)==identity:raise ValueError('PNG FD aliases media/output FD')
    raw=os.pread(fd,st.st_size,0)
    if len(raw)!=st.st_size or raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('PNG signature/short read')
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as im:
            w,h=im.size
            if im.format!='PNG' or not(0<w<=512 and 0<h<=128 and w*h<=65536) or getattr(im,'n_frames',1)!=1:raise ValueError('PNG format/frame/pixel budget')
            rgba=im.convert('RGBA');data=rgba.tobytes();rgba.close()
    overlay=Overlay(data,w,h,x,y);overlay._origin_identity=identity
    return overlay

Observer=C.CFUNCTYPE(None,C.c_void_p,C.POINTER(C.c_uint8),C.POINTER(C.c_uint8),C.c_uint32,C.c_uint32,C.c_uint32,C.c_int64,C.c_uint32,C.c_uint32)
class OverlayBackend(Backend):
    def __init__(self,library):
        super().__init__(library)
        self.lib.oc_media_overlay_build_info.restype=C.c_char_p
        self.lib.oc_media_convert_overlay_fd.argtypes=[C.c_int,C.c_int,C.c_int,C.c_int,C.POINTER(Overlay),Observer,C.c_void_p,C.POINTER(Limits),Cancel,C.c_void_p,C.POINTER(Result)]
        self.lib.oc_media_convert_overlay_fd.restype=C.c_int
        self.lib.oc_media_overlay_apply_rgb24.argtypes=[C.POINTER(Overlay),C.POINTER(C.c_uint8),C.c_uint64,C.c_uint32,C.c_uint32,C.c_uint32,C.c_int64,C.c_uint32,C.c_uint32]
        self.lib.oc_media_overlay_apply_rgb24.restype=C.c_int
    def convert_overlay(self,mode,source_fd,audio_fd,output_fd,limits,overlay=None,cancel=lambda:False,observer=None):
        if overlay is not None and overlay._origin_identity:
            for fd in [source_fd,audio_fd,output_fd]:
                if fd>=0:
                    st=os.fstat(fd)
                    if (st.st_dev,st.st_ino)==overlay._origin_identity:raise ValueError('PNG/media/output inode alias')
        callback_failed=[False];callback_error=[None]
        def observe(_,before,after,w,h,stride,pts,num,den):
            try:observer(before,after,w,h,stride,pts,num,den)
            except BaseException as exc:callback_failed[0]=True;callback_error[0]=repr(exc)
        def check(_):
            try:return int(callback_failed[0] or bool(cancel()))
            except BaseException:return 1
        ocb=Observer(observe) if observer else Observer();ccb=Cancel(check);result=Result()
        status=self.lib.oc_media_convert_overlay_fd(mode,source_fd,audio_fd,output_fd,C.byref(overlay) if overlay is not None else None,ocb,None,C.byref(limits),ccb,None,C.byref(result))
        assert status==result.status
        result._observer_error=callback_error[0]
        return result
