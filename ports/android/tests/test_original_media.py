"""Pure malformed/closure tests; real original-data cases are explicit opt-in.
Run with trusted tools on PYTHONPATH. Set TMPDIR to the owned test workspace.
Optional ORIGINAL_MEDIA_REAL_PLAN + ORIGINAL_MEDIA_REAL_OUTPUTS verify all26.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch
from original_convert import media as m
from original_convert.media_validate import validate_media_fd
from original_convert.source import (OriginalInputError,ConversionCancelled,VerifiedSnapshot,
    OwnedOutput,ReviewedReadSet,SourceEntry)

def enc(obj):return json.dumps(obj,sort_keys=True,separators=(',',':')).encode()
def parse(obj):
    b=enc(obj);return m.parse_plan(b,expected_sha256=hashlib.sha256(b).hexdigest())
def track(n,handler='soun',frames=0):
    if handler=='soun':
        total=n+1024;runs=[[total//1024,1024]]
        if total%1024:runs.append([1,total%1024])
        return {'handler':'soun','codec':'mp4a','timescale':44100,'duration':total,'sample_count':sum(a for a,_ in runs),'stts':runs,'edit':[n,1024,1,0],'track_duration':n}
    return {'handler':'vide','codec':'avc1','timescale':30,'duration':frames,'sample_count':frames,'stts':[[frames,1]],'edit':[n,0,1,0],'track_duration':n}
def plan_obj():
    tasks=[]
    for name,(kind,source,audio,overlay) in sorted(m._MAPPING.items()):
        n=1024;vf=m._FRAMES.get(name,0);inp={'pcm':{'frames':n,'rate':44100,'channels':2,'bits':16}}
        exp={'audio_samples':n,'video_frames':vf,'width':640 if vf else 0,'height':480 if vf else 0,'ftyp_hex':m._VIDEO_FTYP if vf else m._AUDIO_FTYP,'movie_timescale':1000 if vf else 44100,'movie_duration':n,'tracks':[track(n)]}
        if vf:
            inp['video']={'frames':vf,'width':640,'height':480,'time_base':[1,30]};exp['tracks'].append(track(n,'vide',vf))
        tasks.append({'path':name,'kind':kind,'source':source,'audio':audio,'overlay':copy.deepcopy(overlay),'input':inp,'expected':exp})
    return {'schema':'wmmt-original-media-v1','tasks':tasks}

def box(t,p=b'',large=False):return (struct.pack('>I4sQ',1,t,len(p)+16) if large else struct.pack('>I4s',len(p)+8,t))+p
def full(p=b'',v=0,flags=0):return bytes([v])+flags.to_bytes(3,'big')+p
def desc(t,p):return bytes([t,len(p)])+p
MATRIX=(65536,0,0,0,65536,0,0,0,1073741824)
def synthetic(*,large=False,co64=False,unknown=False,two_chunks=False):
    # Arbitrary access-unit bytes deliberately illustrate container-only coverage;
    # this synthetic fixture is NOT asserted to be decodable AAC.
    expected={'audio_samples':1024,'video_frames':0,'width':0,'height':0,'ftyp_hex':m._AUDIO_FTYP,'movie_timescale':44100,'movie_duration':1024,'tracks':[track(1024)]}
    ftyp=box(b'ftyp',bytes.fromhex(m._AUDIO_FTYP),large=large);free=box(b'free',large=large);mdat=box(b'mdat',b'abCDE',large=large);offset=len(ftyp)+len(free)+(16 if large else 8)
    mv=bytearray(100);struct.pack_into('>II',mv,12,44100,1024);struct.pack_into('>I',mv,20,65536);struct.pack_into('>H',mv,24,256);struct.pack_into('>9I',mv,36,*MATRIX)
    tk=bytearray(84);tk[3]=3;struct.pack_into('>I',tk,12,1);struct.pack_into('>I',tk,20,1024);struct.pack_into('>HH',tk,34,1,256);struct.pack_into('>9I',tk,40,*MATRIX)
    md=bytearray(24);struct.pack_into('>II',md,12,44100,2048)
    hd=full(b'\0'*4+b'soun'+b'\0'*12)
    edit=box(b'edts',box(b'elst',full(struct.pack('>IIiHH',1,1024,1024,1,0))))
    cfg=bytes([0x40,0x15])+b'\0'*3+struct.pack('>II',128000,128000)+desc(5,bytes.fromhex('121056e500'))
    esds=box(b'esds',full(desc(3,b'\0\x01\0'+desc(4,cfg)+desc(6,b'\x02'))))
    entry=box(b'mp4a',b'\0'*6+b'\0\x01'+b'\0'*8+struct.pack('>HHHHI',2,16,0,0,44100<<16)+esds)
    stsd=box(b'stsd',full(struct.pack('>I',1)+entry));stts=box(b'stts',full(struct.pack('>III',1,2,1024)));stsz=box(b'stsz',full(struct.pack('>IIII',0,2,2,3)))
    stsc=box(b'stsc',full(struct.pack('>IIII',1,1,1 if two_chunks else 2,1)))
    offsets=[offset,offset+2] if two_chunks else [offset]
    stco=box(b'co64' if co64 else b'stco',full(struct.pack('>I',len(offsets))+b''.join(struct.pack('>Q' if co64 else '>I',x) for x in offsets)))
    sgpd=box(b'sgpd',bytes.fromhex('01000000726f6c6c0000000200000001ffff'));sbgp=box(b'sbgp',full(b'roll'+struct.pack('>III',1,2,1)))
    stbl=box(b'stbl',stsd+stts+stsc+stsz+stco+sgpd+sbgp)
    dinf=box(b'dinf',box(b'dref',full(struct.pack('>I',1)+box(b'url ',full(flags=1)))))
    minf=box(b'minf',box(b'smhd',full(b'\0'*4))+dinf+stbl)
    mdia=box(b'mdia',box(b'mdhd',bytes(md))+box(b'hdlr',hd)+minf)
    trak=box(b'trak',box(b'tkhd',bytes(tk))+edit+mdia)
    moov=box(b'moov',box(b'mvhd',bytes(mv))+trak+(box(b'zzzz',b'opaque') if unknown else b''))
    return ftyp+free+mdat+moov,expected

def changed(data,kind,rel,value):
    b=bytearray(data);p=b.index(kind)+4+rel;b[p:p+len(value)]=value;return bytes(b)

class MediaTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(prefix='original-media-test-',dir=os.environ.get('TMPDIR')))
    def validate(self,data,expect=None,**kw):
        if expect is None:_,expect=synthetic()
        path=self.root/('f-'+str(len(list(self.root.iterdir())))+'.mp4')
        with path.open('xb') as f:f.write(data)
        fd=os.open(path,os.O_RDONLY)
        try:return validate_media_fd(fd,expect,kind='wav',max_bytes=32*1024*1024,**kw)
        finally:os.close(fd)
    def rejects(self,data,expect=None):
        with self.assertRaises(OriginalInputError):self.validate(data,expect)
    def test_plan_pin_canonical_closed26_and_immutable(self):
        obj=plan_obj();p=parse(obj);self.assertEqual((len(p.tasks),len(p.sources)),(26,31))
        raw=enc(obj)
        for b in [raw,raw+b'\n']:self.assertEqual(len(m.parse_plan(b,expected_sha256=hashlib.sha256(b).hexdigest()).tasks),26)
        with self.assertRaises(TypeError):p.tasks[0].expected['width']=1
        for b,pin in [(raw,'0'*64),(raw,None),(raw+b'\n\n',hashlib.sha256(raw+b'\n\n').hexdigest()),(bytearray(raw),hashlib.sha256(raw).hexdigest())]:
            with self.subTest(pin=pin),self.assertRaises(OriginalInputError):m.parse_plan(b,expected_sha256=pin)
    def test_plan_path_type_counts_sources_overlays(self):
        base=plan_obj()
        changes=[('path','../intro.mp4'),('source','data/../../main'),('audio','/external.wav'),('kind','shell'),('overlay',{'source':'data/x.png','x':29,'y':18,'width':128,'height':16})]
        for key,val in changes:
            obj=copy.deepcopy(base);obj['tasks'][0][key]=val
            with self.subTest(key=key),self.assertRaises(OriginalInputError):parse(obj)
        for f in [lambda o:o['tasks'].pop(),lambda o:o['tasks'].append(copy.deepcopy(o['tasks'][0])),lambda o:o['tasks'].reverse(),lambda o:o['tasks'][0]['input']['pcm'].update(frames=True),lambda o:o['tasks'][0]['expected'].update(video_frames=3),lambda o:o['tasks'][0].update(unreviewed='anything'),lambda o:o['tasks'][0]['expected']['tracks'][0]['stts'][0].__setitem__(0,0)]:
            obj=copy.deepcopy(base);f(obj)
            with self.assertRaises(OriginalInputError):parse(obj)
        raw=b'{"schema":"wmmt-original-media-v1","schema":"wmmt-original-media-v1","tasks":[]}'
        with self.assertRaises(OriginalInputError):m.parse_plan(raw,expected_sha256=hashlib.sha256(raw).hexdigest())
    def test_container_normal_large64_co64_unknown_coverage(self):
        for opts in [{},{'large':True},{'co64':True},{'two_chunks':True},{'co64':True,'two_chunks':True},{'unknown':True}]:
            b,e=synthetic(**opts);r=self.validate(b,e);self.assertIn('not access-unit decode',r['coverage']);self.assertEqual(bool(r['unknown_metadata_skipped']),bool(opts.get('unknown')))
    def test_truncation_overflow_openended_extra_tail(self):
        b,e=synthetic()
        for bad in [b[:-1],b+b'X',b+box(b'free'),struct.pack('>I',2**32-1)+b[4:],b'\0'*4+b[4:],struct.pack('>I4sQ',1,b'ftyp',2**64-1)+b[8:]]:self.rejects(bad,e)
    def test_unknown_codec_rate_channels_ASC_and_versions(self):
        b,e=synthetic();self.rejects(b.replace(b'mp4a',b'xxxx',1),e)
        for kind,rel,value in [(b'mdhd',12,struct.pack('>I',48000)),(b'mp4a',16,struct.pack('>H',1)),(b'mp4a',24,struct.pack('>I',48000<<16)),(b'stts',0,b'\x01'),(b'url ',3,b'\0')]:self.rejects(changed(b,kind,rel,value),e)
        self.rejects(b.replace(bytes.fromhex('121056e500'),bytes.fromhex('119056e500'),1),e)
    def test_sample_sizes_counts_timing_chunk_offsets_gaps_overlap(self):
        b,e=synthetic()
        for kind,rel,value in [(b'stsz',12,b'\0'*4),(b'stsz',8,struct.pack('>I',3)),(b'stts',12,struct.pack('>I',0)),(b'stts',8,struct.pack('>I',3)),(b'stsc',8,struct.pack('>I',2)),(b'stsc',16,struct.pack('>I',2)),(b'stco',8,struct.pack('>I',1)),(b'stco',8,struct.pack('>I',2**32-1))]:self.rejects(changed(b,kind,rel,value),e)
        b,e=synthetic(two_chunks=True);self.rejects(changed(b,b'stco',12,struct.pack('>I',44)),e)
        e=copy.deepcopy(e);e['tracks'][0]['sample_count']=3;self.rejects(b,e)
    def test_duplicate_track_and_handler_cardinality(self):
        b,e=synthetic();p=b.index(b'trak')-4;n=struct.unpack_from('>I',b,p)[0];duplicate=b[p:p+n];moov=b.index(b'moov')-4;bad=bytearray(b+duplicate);struct.pack_into('>I',bad,moov,struct.unpack_from('>I',b,moov)[0]+n);self.rejects(bytes(bad),e)
        self.rejects(b.replace(b'soun',b'vide',1),e)
    def test_edits_priming_roll_and_unity_transform(self):
        b,e=synthetic()
        for kind,rel,val in [(b'elst',12,struct.pack('>i',0)),(b'elst',16,b'\0\0'),(b'sgpd',16,b'\0\0'),(b'mvhd',20,b'\0'*4),(b'tkhd',40,b'\0'*4)]:self.rejects(changed(b,kind,rel,val),e)
    def test_budgets_fd_types_alias_closed_cancel_and_callback_error(self):
        b,e=synthetic();path=self.root/'x';path.write_bytes(b);fd=os.open(path,os.O_RDONLY)
        try:
            for badfd in [True,-1,'fd']:
                with self.assertRaises(OriginalInputError):validate_media_fd(badfd,e,kind='wav',max_bytes=1024)
            with self.assertRaises(OriginalInputError):validate_media_fd(fd,e,kind='wav',max_bytes=8)
            with self.assertRaises(OriginalInputError):validate_media_fd(fd,e,kind='wav',max_bytes=1024,forbidden_fds=[fd])
            with self.assertRaises(ConversionCancelled):validate_media_fd(fd,e,kind='wav',max_bytes=1024,cancel=lambda:True)
            def boom():raise RuntimeError('callback')
            with self.assertRaises(OriginalInputError):validate_media_fd(fd,e,kind='wav',max_bytes=1024,cancel=boom)
            with patch('original_convert.media_validate.MAX_BOXES',1),self.assertRaises(OriginalInputError):validate_media_fd(fd,e,kind='wav',max_bytes=1024)
        finally:os.close(fd)
        with self.assertRaises(OriginalInputError):validate_media_fd(fd,e,kind='wav',max_bytes=1024)
    def snapshot_stub(self,p,missing=False):
        root=self.root/'source';root.mkdir();snap=object.__new__(VerifiedSnapshot);snap.root=root
        files={n:SourceEntry(1,'0'*64) for n in p.sources}
        if missing:files.pop(next(iter(files)))
        snap.readset=ReviewedReadSet(MappingProxyType(files),'0'*64,len(files));snap.bytes=len(files);return snap
    def test_api_requires_verified_types_plan_and_closed_readset(self):
        p=parse(plan_obj());out=OwnedOutput(self.root);lib=self.root/'packaged.so';lib.write_bytes(b'not executed')
        with self.assertRaises(OriginalInputError):m.convert_media('/external','/out',p,library=lib)
        snap=self.snapshot_stub(p,missing=True)
        with self.assertRaises(OriginalInputError):m.convert_media(snap,out,p,library=lib)
        self.assertEqual(out.files,{})
        self.assertFalse(hasattr(m,'publish'));self.assertFalse(hasattr(m,'Ready'))
    def test_api_no_overwrite_and_cancel_before_any_native(self):
        p=parse(plan_obj());snap=self.snapshot_stub(p);out=OwnedOutput(self.root);lib=self.root/'packaged.so';lib.write_bytes(b'not executed');old=out.target('intro.mp4');old.write_bytes(b'KEEP')
        with self.assertRaises(OriginalInputError):m.convert_media(snap,out,p,library=lib)
        self.assertEqual(old.read_bytes(),b'KEEP');self.assertEqual(out.files,{})
        with self.assertRaises(ConversionCancelled):m.convert_media(snap,out,p,library=lib,cancel=lambda:True)
        with self.assertRaises(OriginalInputError):m.convert_media(snap,out,p,library=lib,cancel=True)
    def test_api_all_source_hashes_and_inode_aliases_before_native(self):
        p=parse(plan_obj());snap=self.snapshot_stub(p);names=list(p.sources);digest=hashlib.sha256(b'X').hexdigest()
        for i,name in enumerate(names):
            path=snap.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            if i==1:os.link(snap.root/names[0],path)
            else:path.write_bytes(b'X')
        snap.readset=ReviewedReadSet(MappingProxyType({n:SourceEntry(1,digest) for n in names}),'0'*64,31)
        lib=self.root/'packaged.so';lib.write_bytes(b'not executed');out=OwnedOutput(self.root)
        with patch('original_convert.native_backend.media_overlay_ctypes.OverlayBackend') as native:
            with self.assertRaisesRegex(OriginalInputError,'inode aliases'):m.convert_media(snap,out,p,library=lib)
            native.assert_not_called()
        # A late input hash failure also happens before Pillow/native loading.
        entries=dict(snap.readset.files);entries[names[-1]]=SourceEntry(1,'0'*64);snap.readset=ReviewedReadSet(MappingProxyType(entries),'0'*64,31)
        with patch('original_convert.native_backend.media_overlay_ctypes.OverlayBackend') as native:
            with self.assertRaisesRegex(OriginalInputError,'source hash mismatch'):m.convert_media(snap,OwnedOutput(self.root),p,library=lib)
            native.assert_not_called()
        self.assertEqual(out.files,{})
    def test_reviewed_wav_zero_tail_is_exact_not_generic_trailing_acceptance(self):
        import wave
        path=self.root/'test.wav'
        with wave.open(str(path),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(44100);f.writeframes(b'\0'*16)
        expect={'frames':4,'rate':44100,'channels':2,'bits':16};data=path.read_bytes()
        for tail in [b'\0'*20,b'X'+b'\0'*19,b'\0'*21]:
            file=self.root/('wav-'+str(len(list(self.root.iterdir()))));file.write_bytes(data+tail);fd=os.open(file,os.O_RDONLY)
            try:
                with self.assertRaises(OriginalInputError):m._pcm(fd,expect)
                if tail==b'\0'*20:m._pcm(fd,expect,tail=20)
                else:
                    with self.assertRaises(OriginalInputError):m._pcm(fd,expect,tail=20)
            finally:os.close(fd)
    @unittest.skipUnless(os.environ.get('ORIGINAL_MEDIA_REAL_PLAN') and os.environ.get('ORIGINAL_MEDIA_REAL_OUTPUTS'),'opt-in actual media structural proof')
    def test_real26_full_structure_and_wrong_frame_count(self):
        raw=Path(os.environ['ORIGINAL_MEDIA_REAL_PLAN']).read_bytes();p=m.parse_plan(raw,expected_sha256=hashlib.sha256(raw).hexdigest());root=Path(os.environ['ORIGINAL_MEDIA_REAL_OUTPUTS'])
        for t in p.tasks:
            fd=os.open(root/t.path,os.O_RDONLY)
            try:
                facts=validate_media_fd(fd,t.expected,kind=t.kind,max_bytes=(32 if t.kind=='wav' else 128)*1024**2);self.assertGreater(facts['boxes_checked'],10)
                if t.kind=='movie':
                    e=json.loads(json.dumps(m._freeze_plain(t.expected))) if hasattr(m,'_freeze_plain') else json.loads(json.dumps({k:v for k,v in t.expected.items()},default=lambda x:dict(x) if hasattr(x,'items') else list(x)))
                    e['tracks'][1]['sample_count']+=1
                    with self.assertRaises(OriginalInputError):validate_media_fd(fd,e,kind=t.kind,max_bytes=128*1024**2)
            finally:os.close(fd)

class RealNativeFailureTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('ORIGINAL_MEDIA_REAL_PROOF') and os.environ.get('ORIGINAL_MEDIA_REAL_PLAN') and os.environ.get('ORIGINAL_MEDIA_REAL_LIBRARY'),'opt-in owned-snapshot native failure simulation; never a success proof')
    def test_native_status_completion_and_callback_exception_never_record_partial(self):
        from original_convert.native_backend.media_ctypes import Result
        from types import SimpleNamespace
        proofpath=Path(os.environ['ORIGINAL_MEDIA_REAL_PROOF']);proof=json.loads(proofpath.read_text());rsdata=(proofpath.parent/'production-readset.candidate.json').read_bytes();self.assertEqual(hashlib.sha256(rsdata).hexdigest(),proof['snapshot_readset_sha256'])
        readset=ReviewedReadSet.parse(rsdata,expected_sha256=proof['snapshot_readset_sha256']);snap=object.__new__(VerifiedSnapshot);snap.root=Path(proof['snapshot_root']);snap.readset=readset;snap.bytes=readset.total_bytes
        # This controlled failure fixture does not attest an externally received
        # snapshot or claim production success; production-api26.json was produced
        # independently with VerifiedSnapshot.create and the real native library.
        raw=Path(os.environ['ORIGINAL_MEDIA_REAL_PLAN']).read_bytes();plan=m.parse_plan(raw,expected_sha256=hashlib.sha256(raw).hexdigest());parent=Path(tempfile.mkdtemp(prefix='media-native-failure-',dir=os.environ.get('TMPDIR')))
        for mode in ['status','completion','callback']:
            active=[False]
            def cancel():
                if active[0]:raise RuntimeError('native callback exception')
                return False
            def convert(*args,**kwargs):
                r=Result()
                if mode=='status':r.status=-4;r.av_error=-1
                elif mode=='completion':r.status=0
                else:
                    active[0]=True
                    try:kwargs['cancel']()
                    finally:active[0]=False
                    r.status=-2
                return r
            fake=SimpleNamespace(convert=convert,convert_overlay=convert);out=OwnedOutput(parent)
            with patch('original_convert.native_backend.media_overlay_ctypes.OverlayBackend',return_value=fake):
                with self.assertRaises(OriginalInputError):m.convert_media(snap,out,plan,library=os.environ['ORIGINAL_MEDIA_REAL_LIBRARY'],cancel=cancel)
            self.assertEqual(out.files,{})
            self.assertTrue((out.root/'intro.mp4').is_file())
            self.assertEqual((out.root/'intro.mp4').stat().st_size,0)

if __name__=='__main__':unittest.main()
