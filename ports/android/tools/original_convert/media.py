"""Pinned original media component; FD-only trusted native backend, no publication.

Plan hashes are app-recipe trust inputs, NEVER player receipts/self-adopted pins.
No old runtime/gold inputs, shell, external tool, compiler, sys.path or Ready.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
from threading import Event
from types import MappingProxyType
from .source import (VerifiedSnapshot, OwnedOutput, ReviewedReadSet, SourceEntry,
    FileTreeSource, OriginalInputError, ConversionCancelled, HASH, _unique_object)
from .media_validate import validate_media_fd
from .work_queue import run_parallel

MAX_MEDIA_WORKERS = 4

_SCHEMA='wmmt-original-media-v1'
_TOKEN=object()
_AUDIO_FTYP='4d344120000002004d34412069736f6d69736f32'
_VIDEO_FTYP='69736f6d0000020069736f6d69736f32617663316d703431'
_BGM=['maxi3plus/wm3DX_P_sys_01_ent','maxi3plus/wm3DX_P_sys_02_sel','maxi3/sys_04']+['maxi3plus/wm3DX_P_race_%02d'%i for i in range(1,5)]+['maxi3dx/wm3DX_race_01_mainD']+['maxi3/wm3_%02d'%i for i in range(1,16)]
_MAPPING={'sound/bgm/'+x.split('/')[-1]+'.m4a':('wav','data/sound/bgm/'+x+'.wav',None,None) for x in _BGM}
for _name,_bik,_wav,_png in [('intro','atruct','opening',None),('playdemo','playdemo','demo','playdemo'),('tutorial','tutorial','tutorial','tutorial')]:
    _MAPPING[_name+'.mp4']=('movie','data/movie/'+_bik+'.bik','data/sound/bgm/attract/'+_wav+'_japan.wav',None if _png is None else {'source':'data/sprite/atract_p_movie_'+_png+'.png','x':29,'y':18,'width':128 if _png=='playdemo' else 256,'height':16 if _png=='playdemo' else 32})
_FRAMES={'intro.mp4':1785,'playdemo.mp4':840,'tutorial.mp4':1595}

@dataclass(frozen=True)
class MediaTask:
    path:str
    kind:str
    source:str
    audio:object
    overlay:object
    input:object
    expected:object
@dataclass(frozen=True)
class MediaPlan:
    tasks:tuple
    sha256:str
    sources:tuple
    _token:object

def _bad(msg):raise OriginalInputError('Media plan/job: '+msg)
def _int(v,lo,hi):
    if type(v)is not int or not lo<=v<=hi:_bad('integer/type budget')
    return v
def _keys(v,keys):
    if type(v)is not dict or set(v)!=set(keys):_bad('closed schema fields')
def _freeze(v):
    if type(v)is dict:return MappingProxyType({k:_freeze(x) for k,x in v.items()})
    if type(v)is list:return tuple(_freeze(x) for x in v)
    return v

def parse_plan(data,*,expected_sha256):
    """Authenticate canonical JSON, exact 26 task ownership and non-lossy metadata."""
    if (type(data)is not bytes or not 1<=len(data)<=128*1024 or type(expected_sha256)is not str or
        not HASH.fullmatch(expected_sha256) or hashlib.sha256(data).hexdigest()!=expected_sha256):_bad('signed recipe pin required')
    try:
        obj=json.loads(data.decode('utf-8','strict'),object_pairs_hook=_unique_object,
            parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
        canonical=json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    except (ValueError,UnicodeError,RecursionError,OverflowError) as exc:raise OriginalInputError('Invalid media plan JSON') from exc
    if data not in (canonical,canonical+b'\n'):_bad('noncanonical JSON')
    _keys(obj,['schema','tasks'])
    if obj['schema']!=_SCHEMA or type(obj['tasks'])is not list or len(obj['tasks'])!=26:_bad('exact media ownership required')
    tasks=[];previous='';seen=set();sources=set();wav=movie=0
    for t in obj['tasks']:
        _keys(t,['path','kind','source','audio','overlay','input','expected']);name=t['path']
        if type(name)is not str or name not in _MAPPING or name<=previous or name.casefold()in seen:_bad('unsafe/unsorted/duplicate output path')
        expected_kind,source,audio,overlay=_MAPPING[name]
        if (t['kind'],t['source'],t['audio'],t['overlay'])!=(expected_kind,source,audio,overlay):_bad('original source/overlay mapping differs from reviewed recipe')
        sources.add(source)
        if audio:sources.add(audio)
        if overlay:
            _keys(t['overlay'],['source','x','y','width','height'])
            for k in ['x','y','width','height']:_int(t['overlay'][k],0,640)
            sources.add(overlay['source'])
        inp=t['input'];_keys(inp,['pcm'] if expected_kind=='wav' else ['pcm','video']);pcm=inp['pcm'];_keys(pcm,['frames','rate','channels','bits'])
        _int(pcm['frames'],1,57600000);_int(pcm['rate'],8000,96000);_int(pcm['channels'],1,2);_int(pcm['bits'],8,32)
        if pcm['channels']!=2 or pcm['bits']!=16 or pcm['frames']>pcm['rate']*600:_bad('original PCM class/duration')
        if expected_kind=='wav' and pcm['rate']!=44100:_bad('reviewed BGM PCM rate')
        e=t['expected'];_keys(e,['audio_samples','video_frames','width','height','ftyp_hex','movie_timescale','movie_duration','tracks'])
        _int(e['audio_samples'],1,44100*600);_int(e['video_frames'],0,18000);_int(e['width'],0,640);_int(e['height'],0,480)
        _int(e['movie_timescale'],1,1000000000);_int(e['movie_duration'],1,e['movie_timescale']*600)
        if expected_kind=='wav':
            wav+=1
            if (e['video_frames'],e['width'],e['height'],e['audio_samples'],e['ftyp_hex'],e['movie_timescale'],e['movie_duration'])!=(0,0,0,pcm['frames'],_AUDIO_FTYP,44100,pcm['frames']):_bad('BGM completion profile')
        else:
            movie+=1;vi=inp['video'];_keys(vi,['frames','width','height','time_base'])
            for k in ['frames','width','height']:_int(vi[k],1,18000)
            if (vi['frames'],vi['width'],vi['height'])!=(_FRAMES[name],640,480) or type(vi['time_base'])is not list or len(vi['time_base'])!=2:_bad('original movie frame/dimensions')
            for x in vi['time_base']:_int(x,1,1000000000)
            if (e['video_frames'],e['width'],e['height'],e['ftyp_hex'],e['movie_timescale'])!=(_FRAMES[name],640,480,_VIDEO_FTYP,1000):_bad('AVC completion profile')
        if type(e['tracks'])is not list or len(e['tracks'])!=(1 if expected_kind=='wav' else 2):_bad('track cardinality')
        handlers=[]
        for tr in e['tracks']:
            _keys(tr,['handler','codec','timescale','duration','sample_count','stts','edit','track_duration']);h=tr['handler'];handlers.append(h)
            if h not in('soun','vide') or tr['codec']!=('mp4a' if h=='soun' else 'avc1'):_bad('track handler/codec')
            for k in ['timescale','duration','sample_count','track_duration']:_int(tr[k],1,10**12)
            if tr['sample_count']>30000 or tr['timescale']>1000000000 or tr['track_duration']>e['movie_duration']:_bad('track bound')
            if type(tr['stts'])is not list or not 1<=len(tr['stts'])<=8:_bad('timing run count')
            for run in tr['stts']:
                if type(run)is not list or len(run)!=2:_bad('timing run schema')
                for x in run:_int(x,1,1000000000)
            if sum(x[0] for x in tr['stts'])!=tr['sample_count'] or sum(x[0]*x[1] for x in tr['stts'])!=tr['duration']:_bad('timing arithmetic')
            edit=tr['edit']
            if type(edit)is not list or len(edit)!=4:_bad('edit schema')
            for x in edit:_int(x,0,10**12)
            if not 1<=edit[0]<=tr['track_duration'] or edit[1:]!=([1024,1,0] if h=='soun' else [0,1,0]):_bad('edit/priming profile')
            if h=='soun':
                if tr['timescale']!=44100 or tr['duration']!=e['audio_samples']+1024 or tr['sample_count']!=(e['audio_samples']+1023)//1024+1 or any(delta!=1024 for _,delta in tr['stts'][:-1]) or not 1<=tr['stts'][-1][1]<=1024:_bad('AAC priming/sample count')
            else:
                if expected_kind!='movie' or tr['sample_count']!=e['video_frames'] or tr['timescale']!=inp['video']['time_base'][1] or tr['stts']!=[[e['video_frames'],inp['video']['time_base'][0]]]:_bad('AVC timing')
        if handlers!=(['soun'] if expected_kind=='wav' else ['soun','vide']):_bad('sorted unique handlers')
        tasks.append(MediaTask(name,expected_kind,source,audio,_freeze(overlay),_freeze(inp),_freeze(e)));previous=name;seen.add(name.casefold())
    if (wav,movie,len(sources))!=(23,3,31) or seen!={x.casefold() for x in _MAPPING}:_bad('closed task/readset cardinality')
    return MediaPlan(tuple(tasks),expected_sha256,tuple(sorted(sources)),_TOKEN)

def _cancel(cancel):
    if cancel is not None:
        try:stop=cancel()
        except BaseException as exc:raise OriginalInputError('Media cancellation callback failed') from exc
        if stop:raise ConversionCancelled('Media conversion cancelled')
def _hash_fd(fd,cancel):
    st=os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_size<1:_bad('source/output is not regular')
    h=hashlib.sha256();off=0
    while off<st.st_size:
        _cancel(cancel);b=os.pread(fd,min(128*1024,st.st_size-off),off)
        if not b:_bad('file shrank during hashing')
        off+=len(b);h.update(b)
    after=os.fstat(fd)
    if (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):_bad('file changed during hash')
    return SourceEntry(off,h.hexdigest())
def _read(fd,pos,n):
    b=os.pread(fd,n,pos)
    if len(b)!=n:_bad('truncated source metadata')
    return b

def _pcm(fd,expect,*,tail=0):
    size=os.fstat(fd).st_size;h=_read(fd,0,12);riff_end=size-tail
    # Reviewed original demo_japan.wav alone has 20 zero bytes after the complete
    # declared RIFF. Its full bytes remain authenticated by snapshot.readset.
    if tail not in (0,20) or h[:4]!=b'RIFF' or h[8:]!=b'WAVE' or struct.unpack_from('<I',h,4)[0]+8!=riff_end or (tail and _read(fd,riff_end,tail)!=b'\0'*tail):_bad('RIFF source closure/padding')
    p=12;fmt=None;data=None;count=0
    while p<riff_end:
        count+=1
        if count>128 or p+8>riff_end:_bad('WAV chunk bound')
        head=_read(fd,p,8);tag=head[:4];n=struct.unpack_from('<I',head,4)[0];start=p+8;end=start+n
        if end>riff_end:_bad('WAV chunk overflow')
        if tag==b'fmt ':
            if fmt is not None or not 16<=n<=64:_bad('PCM fmt count/length')
            fmt=struct.unpack('<HHIIHH',_read(fd,start,16))
        if tag==b'data':
            if data is not None:_bad('multiple WAV data chunks')
            data=n
        p=end+(n&1)
    if p!=riff_end or fmt is None or data is None:_bad('WAV source structure')
    tag,ch,rate,byte_rate,align,bits=fmt
    if tag!=1 or ch!=expect['channels'] or rate!=expect['rate'] or bits!=expect['bits'] or align!=ch*bits//8 or byte_rate!=rate*align or data%align or data//align!=expect['frames']:_bad('PCM source differs from pinned metadata')

def _video(fd,expect):
    b=_read(fd,0,44);v=struct.unpack('<10I',b[4:44])
    if b[:3]!=b'BIK' or v[0]+8!=os.fstat(fd).st_size or (v[1],v[4],v[5],v[7],v[6])!=(expect['frames'],expect['width'],expect['height'],*expect['time_base']):_bad('Bink source differs from pinned metadata')

def convert_media(snapshot,output,plan,*,library,cancel=None,progress=None,worker_limit=None,
                  restored=(),on_converted=None):
    """No result activation/publication. Each SourceEntry is added only after closure.
    library is supplied by the trusted app engine, never by the player/plan.
    """
    if type(snapshot)is not VerifiedSnapshot or type(output)is not OwnedOutput or type(plan)is not MediaPlan or plan._token is not _TOKEN or not isinstance(snapshot.readset,ReviewedReadSet):_bad('verified snapshot/owned output/authenticated plan required')
    if cancel is not None and not callable(cancel) or progress is not None and not callable(progress):_bad('callback type')
    _cancel(cancel)
    if not isinstance(library,(str,os.PathLike)):_bad('packaged library path type')
    lib=Path(library)
    if not lib.is_absolute() or not lib.is_file() or lib.is_symlink():_bad('absolute packaged native library required')
    lib=lib.resolve(strict=True)
    for root in (snapshot.root,output.root):
        if lib.is_relative_to(Path(root).resolve()):_bad('library cannot come from player snapshot/output')
    if any(name not in snapshot.readset.files for name in plan.sources):_bad('media dependency missing from reviewed readset')
    caps={}
    for t in plan.tasks:
        caps[t.source]=(256 if t.kind=='wav' else 128)*1024*1024
        if t.audio:caps[t.audio]=128*1024*1024
        if t.overlay:caps[t.overlay['source']]=1024*1024
    if any(not 1<=snapshot.readset.files[n].size<=caps[n] for n in plan.sources):_bad('source dependency byte budget')
    restored = frozenset(restored)
    if (not restored <= {task.path for task in plan.tasks}
            or any(not isinstance(output.files.get(name), SourceEntry) for name in restored)):
        _bad('media resume requires verified output entries')
    tasks = [task for task in plan.tasks if task.path not in restored]
    targets = {task.path: output.target(task.path) for task in tasks}
    handles={};source=FileTreeSource(snapshot.root,snapshot.readset);completed={}
    try:
        # Every needed FD is reviewed/hash-bound BEFORE Pillow or native loading.
        for name in plan.sources:
            _cancel(cancel);fd,_info=source._open(name);handles[name]=fd
            if _hash_fd(fd,cancel)!=snapshot.readset.files[name]:_bad('snapshot media source hash mismatch')
        identities=[(os.fstat(fd).st_dev,os.fstat(fd).st_ino) for fd in handles.values()]
        if len(set(identities))!=31:_bad('media dependency inode aliases')
        for task in plan.tasks:
            pcm_name=task.audio or task.source
            _pcm(handles[pcm_name],task.input['pcm'],tail=20 if pcm_name=='data/sound/bgm/attract/demo_japan.wav' else 0)
            if task.kind=='movie':_video(handles[task.source],task.input['video'])
        from .native_backend.media_overlay_ctypes import OverlayBackend,load_png_overlay_fd,Limits,Result
        import ctypes as C
        if (C.sizeof(Limits),C.sizeof(Result))!=(64,320):_bad('native ABI size mismatch')
        backend=OverlayBackend(lib)
        # Pillow's warning filter is process-wide on this Python runtime.
        # Decode the two bounded overlays before starting native workers.
        overlays = {}
        for task in tasks:
            if task.overlay:
                _cancel(cancel)
                label = load_png_overlay_fd(handles[task.overlay['source']], x=29, y=18,
                                            other_fds=(handles[task.source], handles[task.audio]))
                if (label.width, label.height) != (task.overlay['width'], task.overlay['height']):
                    _bad('original PNG dimensions differ from plan')
                overlays[task.path] = label

        def convert(task, cancel):
            _cancel(cancel);sfd=handles[task.source];afd=handles[task.audio] if task.audio else -1
            needed=[task.source]+([task.audio] if task.audio else [])+([task.overlay['source']] if task.overlay else [])
            for name in needed:
                if _hash_fd(handles[name],cancel)!=snapshot.readset.files[name]:_bad('media source changed before native conversion')
            limit=Limits(max_input_bytes=(256 if task.kind=='wav' else 128)*1024*1024,max_output_bytes=(32 if task.kind=='wav' else 128)*1024*1024,max_duration_ms=600000,max_video_frames=18000,max_wall_ms=600000,max_width=640,max_height=480,preview_duration_ms=0)
            fd=os.open(targets[task.path],os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
            try:
                if (os.fstat(fd).st_dev,os.fstat(fd).st_ino)in identities:_bad('output aliases original snapshot')
                callback_errors=[]
                def poll():
                    try:return bool(cancel and cancel())
                    except BaseException as exc:callback_errors.append(exc);return True
                if task.overlay:
                    r=backend.convert_overlay(2,sfd,afd,fd,limit,overlays[task.path],cancel=poll)
                else:r=backend.convert(1 if task.kind=='wav' else 2,sfd,afd,fd,limit,cancel=poll)
                if callback_errors:raise OriginalInputError('Media native cancellation callback failed') from callback_errors[0]
                _cancel(cancel)
                if r.status==-2:raise ConversionCancelled('Media native conversion cancelled')
                if r.status!=0 or r.av_error!=0:_bad('native rejected media (%d): %s'%(r.status,bytes(r.message).decode('utf-8','replace')))
                e=task.expected
                if r.abi!=1 or r.size!=320 or (r.video_frames,r.audio_samples,r.width,r.height,r.sample_rate,r.channels)!=(e['video_frames'],e['audio_samples'],e['width'],e['height'],44100,2) or not 1<=r.output_bytes<=limit.max_output_bytes or r.output_bytes!=os.fstat(fd).st_size:_bad('native completion differs from pinned format/count profile')
                os.fsync(fd)
                container=validate_media_fd(fd,e,kind=task.kind,max_bytes=limit.max_output_bytes,cancel=cancel,forbidden_fds=tuple(handles.values()))
                observed=_hash_fd(fd,cancel)
                if observed.size!=r.output_bytes:_bad('output completion byte count mismatch')
                os.fsync(fd)
                for name in needed:
                    if _hash_fd(handles[name],cancel)!=snapshot.readset.files[name]:_bad('source changed during conversion')
                _cancel(cancel)
            finally:os.close(fd)
            return observed, r.as_dict(), container

        def commit(task, result):
            observed, native, container = result
            output.files[task.path] = observed
            if on_converted:
                on_converted(task.path)
            completed[task.path] = {'path':task.path,'bytes':observed.size,'sha256':observed.sha256,
                                    'native':native,'container':container}
            if progress:
                try:
                    progress('convert-media',len(restored)+len(completed),len(plan.tasks))
                except ConversionCancelled:
                    raise
                except BaseException as exc:
                    raise OriginalInputError('Media progress callback failed') from exc

        if worker_limit is None:
            for task in tasks:
                commit(task, convert(task, cancel))
            peak = min(len(tasks), 1)
        else:
            # Start long encodes first. Each native codec keeps its existing
            # settings and independently owns the output descriptor.
            stopped = Event()
            peak = run_parallel(sorted(tasks, key=lambda task: task.kind != 'movie'),
                                lambda task: convert(task, stopped.is_set), commit,
                                capacity=MAX_MEDIA_WORKERS, worker_limit=worker_limit,
                                cancel=cancel, stop=stopped.set)
        files = [completed[task.path] for task in tasks]
        return {'component':'media','plan_sha256':plan.sha256,'source_readset_sha256':snapshot.readset.sha256,'files':files,'workers':peak,'complete_dataset':False,'activated':False,'expected_output_verified':False,'structural_profile_verified':True,'lossy_byte_equivalence_claimed':False,'validation':'native completion plus required container closure; not runtime full decode or lossy-byte pin'}
    except (OSError,ValueError,TypeError,OverflowError,struct.error,AssertionError) as exc:
        if isinstance(exc,OriginalInputError):raise
        raise OriginalInputError('Media component failed; new job partials retained') from exc
    finally:
        for fd in handles.values():os.close(fd)
        source.close()
