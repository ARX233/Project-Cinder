"""No subprocess/runtime network. Parent supplies already-validated job FDs."""
import ctypes as C
class Limits(C.Structure):
    _fields_=[('abi',C.c_uint32),('size',C.c_uint32),('max_input_bytes',C.c_uint64),('max_output_bytes',C.c_uint64),('max_duration_ms',C.c_uint64),('max_video_frames',C.c_uint64),('max_wall_ms',C.c_uint64),('max_width',C.c_uint32),('max_height',C.c_uint32),('preview_duration_ms',C.c_uint32)]
    def __init__(self,**kw):
        super().__init__();self.abi=1;self.size=C.sizeof(self)
        values=dict(max_input_bytes=1024**3,max_output_bytes=128*1024**2,max_duration_ms=600000,max_video_frames=18000,max_wall_ms=600000,max_width=640,max_height=480);values.update(kw)
        for k,v in values.items():setattr(self,k,v)
class Result(C.Structure):
    _fields_=[('abi',C.c_uint32),('size',C.c_uint32),('status',C.c_int32),('av_error',C.c_int32),('output_bytes',C.c_uint64),('video_frames',C.c_uint64),('audio_samples',C.c_uint64),('input_bytes_read',C.c_uint64),('width',C.c_uint32),('height',C.c_uint32),('sample_rate',C.c_uint32),('channels',C.c_uint32),('message',C.c_char*256)]
    def __init__(self):super().__init__();self.abi=1;self.size=C.sizeof(self)
    def as_dict(self):return {k: (bytes(getattr(self,k)).decode() if k=='message' else getattr(self,k)) for k,_ in self._fields_}
Cancel=C.CFUNCTYPE(C.c_int,C.c_void_p)
class Backend:
    def __init__(self,library):
        self.lib=C.CDLL(str(library));self.lib.oc_media_build_info.restype=C.c_char_p
        self.lib.oc_media_convert_fd.argtypes=[C.c_int,C.c_int,C.c_int,C.c_int,C.POINTER(Limits),Cancel,C.c_void_p,C.POINTER(Result)]
        self.lib.oc_media_convert_fd.restype=C.c_int
    def convert(self,mode,source_fd,audio_fd,output_fd,limits,cancel=lambda:False):
        # Callback exceptions fail closed rather than silently cancelling nothing.
        def check(_):
            try:return int(bool(cancel()))
            except BaseException:return 1
        cb=Cancel(check);result=Result()
        status=self.lib.oc_media_convert_fd(mode,source_fd,audio_fd,output_fd,C.byref(limits),cb,None,C.byref(result))
        assert status==result.status
        return result
