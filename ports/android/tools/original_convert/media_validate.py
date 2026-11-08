"""Bounded FD-only ISO-BMFF closure for our trusted native media encoder.

Validates required codec/config/timing/sample/chunk/edit metadata and complete
mdat byte ownership. Does NOT decode AAC/H264 access units, prove perceptual
quality, or authenticate a file by itself. Unknown noncritical metadata is
bounded/skipped and reported; external references/fragments/encryption fail.
"""
import os
import stat
import struct
from .source import OriginalInputError, ConversionCancelled

MAX_BOXES=4096
MAX_DEPTH=12
MAX_METADATA=8*1024*1024
MAX_SAMPLES=30000
MAX_SAMPLE_BYTES=8*1024*1024
_BAD={b'moof',b'mvex',b'senc',b'saiz',b'saio',b'pssh',b'encv',b'enca'}
_MATRIX=(65536,0,0,0,65536,0,0,0,1073741824)

def _err(message):raise OriginalInputError('Media container: '+message)
def _poll(cancel):
    if cancel is not None:
        try:stop=cancel()
        except BaseException as exc:raise OriginalInputError('Media cancellation callback failed') from exc
        if stop:raise ConversionCancelled('Media conversion cancelled')
def _u(b,o=0):return struct.unpack_from('>I',b,o)[0]
def _h(b,o=0):return struct.unpack_from('>H',b,o)[0]
def _q(b,o=0):return struct.unpack_from('>Q',b,o)[0]

class _Reader:
    def __init__(self,fd,size,cancel):self.fd=fd;self.size=size;self.cancel=cancel;self.boxes=0;self.metadata=0;self.unknown=[];self.unknown_bytes=0
    def read(self,pos,n):
        _poll(self.cancel)
        if type(pos)is not int or type(n)is not int or pos<0 or n<0 or pos+n>self.size or n>1024*1024:_err('read/metadata bound')
        self.metadata+=n
        if self.metadata>MAX_METADATA:_err('aggregate metadata budget')
        b=os.pread(self.fd,n,pos)
        if len(b)!=n:_err('truncated or changed file')
        return b
    def children(self,start,end,depth=0):
        if depth>MAX_DEPTH or not 0<=start<=end<=self.size:_err('box nesting/range budget')
        rows=[];pos=start
        while pos<end:
            self.boxes+=1
            if self.boxes>MAX_BOXES or end-pos<8:_err('box count/trailing bytes')
            b=self.read(pos,8);n,t=_u(b),b[4:8];head=8
            if n==1:
                if end-pos<16:_err('truncated large box')
                n=_q(self.read(pos+8,8));head=16
            if n==0:_err('open-ended boxes are not emitted by this recipe')
            if n<head or n>end-pos or t in _BAD:_err('box overflow/unsupported fragment or encryption')
            rows.append((t,pos+head,pos+n));pos+=n
        return rows
    def body(self,row,maximum=1024*1024):
        _,p,e=row
        if e-p>maximum:_err('box payload budget')
        return self.read(p,e-p)
    def index(self,rows,known,path):
        out={}
        for row in rows:
            t,p,e=row
            if t in known:
                if t in out:_err('duplicate '+t.decode('latin1'))
                out[t]=row
            else:
                if e-p>65536:_err('unknown metadata box budget')
                self.unknown_bytes+=e-p
                if self.unknown_bytes>256*1024:_err('unknown metadata aggregate budget')
                self.unknown.append({'path':path+'/'+t.decode('latin1'),'bytes':e-p})
        return out

def _plain(value):
    if hasattr(value,'items'):return {k:_plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_plain(v) for v in value]
    return value

def _select(rows,kind):
    matches=[r for r in rows if r[0]==kind]
    if len(matches)!=1:_err('missing/duplicate selector box')
    return matches[0]

def _need(index,types):
    if any(t not in index for t in types):_err('missing required box')
def _full(b,version=0,flags=0):
    if len(b)<4 or b[0]!=version or int.from_bytes(b[1:4],'big')!=flags:_err('fullbox version/flags')
def _time(b,kind):
    if len(b)<4 or b[0] not in (0,1) or b[1:4]!=b'\0\0\0':_err('time box version')
    v=b[0]
    if kind=='mvhd':
        if len(b)!=(100 if not v else 112):_err('mvhd size')
        scale=_u(b,12 if not v else 20);duration=_u(b,16) if not v else _q(b,24)
        tail=20 if not v else 32
        if _u(b,tail)!=65536 or _h(b,tail+4)!=256 or struct.unpack_from('>9I',b,tail+16)!=_MATRIX:_err('movie rate/volume/matrix profile')
    else:
        if len(b)!=(24 if not v else 36):_err('mdhd size')
        scale=_u(b,12 if not v else 20);duration=_u(b,16) if not v else _q(b,24)
    if not scale or scale>1000000000 or not duration or duration>2**63-1:_err('timebase/duration bound')
    return scale,duration

def _descriptors(b):
    rows=[];p=0
    while p<len(b):
        tag=b[p];p+=1;n=0
        for i in range(4):
            if p==len(b):_err('descriptor length truncation')
            x=b[p];p+=1;n=(n<<7)|(x&127)
            if not x&128:break
        else:_err('descriptor length overflow')
        if not n or n>4096 or p+n>len(b) or len(rows)>=16:_err('descriptor payload bound')
        rows.append((tag,b[p:p+n]));p+=n
    return rows

def _aac(b):
    _full(b);root=_descriptors(b[4:])
    if len(root)!=1 or root[0][0]!=3:_err('ES descriptor shape')
    es=root[0][1]
    if len(es)<3 or es[2]!=0 or _h(es)==0:_err('external ES dependency/URL/flags')
    children=_descriptors(es[3:])
    if [x[0] for x in children]!=[4,6] or children[1][1]!=b'\x02':_err('decoder/SL descriptor shape')
    cfg=children[0][1]
    if len(cfg)<13 or cfg[0]!=0x40 or cfg[1]!=0x15:_err('not MPEG-4 AAC audio')
    maxrate,average=_u(cfg,5),_u(cfg,9)
    if not 1<=maxrate<=512000 or not 1<=average<=512000:_err('AAC bitrate budget')
    spec=_descriptors(cfg[13:])
    if len(spec)!=1 or spec[0][0]!=5:_err('missing/duplicate AudioSpecificConfig')
    asc=spec[0][1]
    # Parse the two-octet GASpecificConfig; optional exact SBR-present=0 sync
    # extension emitted by the reviewed native AAC encoder. Never HE-AAC/PCE.
    if len(asc)not in (2,5):_err('unsupported AAC config extension')
    bits=int.from_bytes(asc[:2],'big');aot=bits>>11;freq=(bits>>7)&15;channels=(bits>>3)&15;ga=bits&7
    if (aot,freq,channels,ga)!=(2,4,2,0) or (len(asc)==5 and asc[2:]!=bytes.fromhex('56e500')):_err('AAC must be LC/44100/stereo/1024-sample')
    return {'codec':'mp4a','audio_object_type':aot,'sample_rate':44100,'channels':2,'asc_hex':asc.hex()}

class _Bits:
    def __init__(self,b):self.b=b;self.p=0
    def get(self,n=1):
        if n<0 or self.p+n>len(self.b)*8:_err('SPS truncation')
        v=0
        for _ in range(n):v=(v<<1)|((self.b[self.p//8]>>(7-self.p%8))&1);self.p+=1
        return v
    def ue(self):
        z=0
        while self.get()==0:
            z+=1
            if z>24:_err('SPS Exp-Golomb budget')
        return (1<<z)-1+self.get(z)
    def se(self):
        v=self.ue();return (v+1)//2 if v&1 else -(v//2)
def _sps(nal):
    if not 4<=len(nal)<=1024 or nal[0]&31!=7 or nal[0]&128:_err('SPS NAL shape')
    raw=bytearray();zeros=0;i=1
    while i<len(nal):
        x=nal[i]
        if zeros>=2 and x==3:
            if i+1==len(nal) or nal[i+1]>3:_err('SPS emulation prevention')
            zeros=0;i+=1;continue
        raw.append(x);zeros=zeros+1 if x==0 else 0;i+=1
    bits=_Bits(raw);profile=bits.get(8);compat=bits.get(8);level=bits.get(8)
    if (profile,compat,level)!=(66,192,30):_err('AVC not Constrained Baseline Level3')
    sid=bits.ue()
    if sid>31 or bits.ue()>12:_err('SPS ID/frame number bound')
    poc=bits.ue()
    if poc==0:
        if bits.ue()>12:_err('SPS picture order bound')
    elif poc==1:
        bits.get();bits.se();bits.se();count=bits.ue()
        if count>32:_err('SPS cycle bound')
        for _ in range(count):bits.se()
    elif poc!=2:_err('SPS picture order type')
    if bits.ue()>6:_err('SPS reference/Level3 DPB bound')
    bits.get();mbw=bits.ue()+1;mbh=bits.ue()+1;frame=bits.get()
    if not frame:_err('interlaced AVC outside reviewed mobile profile')
    bits.get();crop=[bits.ue() for _ in range(4)] if bits.get() else [0,0,0,0]
    width=mbw*16-2*(crop[0]+crop[1]);height=(2-frame)*mbh*16-2*(2-frame)*(crop[2]+crop[3])
    if (width,height)!=(640,480):_err('SPS coded/display dimensions')
    return sid

def _avcc(b):
    if len(b)<7 or len(b)>4096 or tuple(b[:5])!=(1,66,192,30,255) or b[5]&224!=224:_err('AVC config/profile/NAL length')
    count=b[5]&31;p=6;ids=set()
    if not 1<=count<=4:_err('SPS count')
    for _ in range(count):
        if p+2>len(b):_err('SPS length')
        n=_h(b,p);p+=2
        if p+n>len(b):_err('SPS byte bound')
        sid=_sps(b[p:p+n]);p+=n
        if sid in ids:_err('duplicate SPS')
        ids.add(sid)
    if p==len(b):_err('missing PPS')
    count=b[p];p+=1
    if not 1<=count<=4:_err('PPS count')
    pids=set()
    for _ in range(count):
        if p+2>len(b):_err('PPS length')
        n=_h(b,p);p+=2
        if not 2<=n<=1024 or p+n>len(b) or b[p]&31!=8 or b[p]&128:_err('PPS NAL bound')
        # Our PPS prefix IDs contain no emulation bytes; IDs are first ue fields.
        rbsp=b[p+1:p+n].replace(b'\0\0\x03',b'\0\0');q=_Bits(rbsp);pid=q.ue();sid=q.ue()
        if pid>255 or pid in pids or sid not in ids:_err('PPS/SPS linkage')
        pids.add(pid);p+=n
    if p!=len(b):_err('AVC config trailing bytes')
    return {'codec':'avc1','profile_idc':66,'constraint_flags':192,'level_idc':30,'width':640,'height':480,'nal_length_bytes':4}

def _table(r,row,width,limit=MAX_SAMPLES):
    b=r.body(row);_full(b)
    if len(b)<8:_err('table header')
    n=_u(b,4)
    if not 1<=n<=limit or len(b)!=8+n*width:_err('table count/length')
    return b,n

def _sample_entry(r,row,handler):
    b=r.body(row);_full(b)
    if len(b)<8 or _u(b,4)!=1:_err('sample description count')
    entries=r.children(row[1]+8,row[2],6)
    if len(entries)!=1:_err('sample entry cardinality')
    entry=entries[0];codec=entry[0];head=28 if codec==b'mp4a' else 78 if codec==b'avc1' else 0
    if not head or handler!=('soun' if codec==b'mp4a' else 'vide') or entry[2]-entry[1]<head:_err('unknown or mismatched codec')
    prefix=r.read(entry[1],head)
    if prefix[:6]!=b'\0'*6 or _h(prefix,6)!=1:_err('external sample data reference')
    children=r.index(r.children(entry[1]+head,entry[2],7),{b'esds',b'avcC',b'btrt',b'pasp'},'sample-entry')
    if b'pasp'in children:
        if codec!=b'avc1' or r.body(children[b'pasp'])!=struct.pack('>II',1,1):_err('pixel aspect outside square-pixel profile')
    if b'btrt'in children:
        br=r.body(children[b'btrt']);cap=512000 if codec==b'mp4a' else 32000000
        if len(br)!=12 or _u(br)>8*1024*1024 or not 1<=_u(br,4)<=cap or not 1<=_u(br,8)<=cap:_err('bitrate metadata budget')
    if codec==b'mp4a':
        if prefix[8:16]!=b'\0'*8 or prefix[20:24]!=b'\0'*4 or (_h(prefix,16),_h(prefix,18),_u(prefix,24))!=(2,16,44100<<16):_err('audio sample entry format')
        _need(children,[b'esds'])
        if b'avcC'in children:_err('mixed codec configuration')
        return _aac(r.body(children[b'esds'],4096))
    if (_h(prefix,24),_h(prefix,26))!=(640,480) or prefix[8:24]!=b'\0'*16 or (_u(prefix,28),_u(prefix,32),_u(prefix,36),_h(prefix,40),_h(prefix,74),_h(prefix,76))!=(72<<16,72<<16,0,1,24,65535) or prefix[42]>31:_err('video sample entry dimensions/header')
    _need(children,[b'avcC'])
    if b'esds'in children:_err('mixed codec configuration')
    return _avcc(r.body(children[b'avcC'],4096))

def _track(r,row,expected):
    idx=r.index(r.children(row[1],row[2],2),{b'tkhd',b'edts',b'mdia'},'trak');_need(idx,[b'tkhd',b'edts',b'mdia'])
    b=r.body(idx[b'tkhd']);v=b[0] if b else 9
    if v not in (0,1) or len(b)!=(84 if v==0 else 96) or b[1:4]!=b'\0\0\x03':_err('tkhd shape/flags')
    tid=_u(b,12 if v==0 else 20);duration=_u(b,20) if v==0 else _q(b,28);matrixoff=40 if v==0 else 52
    if not 1<=tid<=26 or struct.unpack_from('>9I',b,matrixoff)!=_MATRIX:_err('track ID/matrix')
    dims=struct.unpack_from('>II',b,matrixoff+36)
    ed=r.index(r.children(idx[b'edts'][1],idx[b'edts'][2],3),{b'elst'},'edts');_need(ed,[b'elst']);eb=r.body(ed[b'elst'])
    if len(eb)<8 or eb[0]not in(0,1) or eb[1:4]!=b'\0'*3 or _u(eb,4)!=1 or len(eb)!=(20 if eb[0]==0 else 28):_err('edit list cardinality/version')
    edit=list(struct.unpack_from('>IiHH' if eb[0]==0 else '>QqHH',eb,8))
    if edit[1]not in(0,1024) or edit[2:]!=[1,0] or not edit[0]:_err('unsupported edit/priming')
    md=r.index(r.children(idx[b'mdia'][1],idx[b'mdia'][2],3),{b'mdhd',b'hdlr',b'minf'},'mdia');_need(md,[b'mdhd',b'hdlr',b'minf'])
    scale,dur=_time(r.body(md[b'mdhd']),'mdhd');hb=r.body(md[b'hdlr'],4096);_full(hb)
    if len(hb)<24 or hb[8:12]not in(b'soun',b'vide'):_err('track handler')
    handler=hb[8:12].decode();codec_dims=(0,0) if handler=='soun' else (640<<16,480<<16)
    if dims!=codec_dims or _h(b,matrixoff-8)!=0 or _h(b,matrixoff-6)!=(1 if handler=='soun' else 0) or _h(b,matrixoff-4)!=(256 if handler=='soun' else 0) or _h(b,matrixoff-2)!=0:_err('tkhd display/volume/layer profile')
    mi=r.index(r.children(md[b'minf'][1],md[b'minf'][2],4),{b'stbl',b'dinf',b'smhd',b'vmhd'},'minf');_need(mi,[b'stbl',b'dinf'])
    if (handler=='soun' and (b'smhd'not in mi or b'vmhd'in mi)) or (handler=='vide' and (b'vmhd'not in mi or b'smhd'in mi)):_err('media header kind')
    if r.body(mi[b'smhd' if handler=='soun' else b'vmhd'])!=(b'\0'*8 if handler=='soun' else b'\0\0\0\x01'+b'\0'*8):_err('media header padding/mode profile')
    di=r.index(r.children(mi[b'dinf'][1],mi[b'dinf'][2],5),{b'dref'},'dinf');_need(di,[b'dref']);dr=di[b'dref'];db=r.read(dr[1],8);_full(db)
    refs=r.children(dr[1]+8,dr[2],6)
    if _u(db,4)!=1 or len(refs)!=1 or refs[0][0]!=b'url ' or r.body(refs[0])!=b'\0\0\0\x01':_err('external/multiple data reference')
    sb=r.index(r.children(mi[b'stbl'][1],mi[b'stbl'][2],5),{b'stsd',b'stts',b'stsc',b'stsz',b'stco',b'co64',b'stss',b'ctts',b'sgpd',b'sbgp'},'stbl');_need(sb,[b'stsd',b'stts',b'stsc',b'stsz'])
    if (b'stco'in sb)==(b'co64'in sb):_err('chunk offset table cardinality')
    config=_sample_entry(r,sb[b'stsd'],handler)
    z=r.body(sb[b'stsz']);_full(z)
    if len(z)<12:_err('sample size table header')
    default,count=_u(z,4),_u(z,8)
    if not 1<=count<=MAX_SAMPLES or len(z)!=(12 if default else 12+4*count):_err('sample size count/length')
    sizes=[default]*count if default else list(struct.unpack_from('>'+str(count)+'I',z,12))
    if any(not 1<=n<=MAX_SAMPLE_BYTES for n in sizes):_err('empty/oversize sample')
    tb,n=_table(r,sb[b'stts'],8);runs=[list(struct.unpack_from('>II',tb,8+8*i)) for i in range(n)]
    if any(not a or not delta for a,delta in runs) or sum(a for a,_ in runs)!=count or sum(a*b for a,b in runs)!=dur:_err('sample timing/count/duration inconsistency')
    offset_box=sb.get(b'stco',sb.get(b'co64'));width=4 if b'stco'in sb else 8;ob,nchunks=_table(r,offset_box,width)
    offsets=[(_u if width==4 else _q)(ob,8+i*width) for i in range(nchunks)]
    sc,nsc=_table(r,sb[b'stsc'],12);mapping=[struct.unpack_from('>III',sc,8+12*i) for i in range(nsc)]
    if mapping[0][0]!=1 or any(not 1<=f<=nchunks or not 1<=c<=count or d!=1 for f,c,d in mapping) or any(mapping[i][0]>=mapping[i+1][0] for i in range(len(mapping)-1)):_err('chunk mapping shape')
    intervals=[];used=0;j=0
    for i,off in enumerate(offsets,1):
        _poll(r.cancel)
        while j+1<len(mapping) and mapping[j+1][0]<=i:j+=1
        n=mapping[j][1]
        if used+n>count:_err('chunk sample overrun')
        length=sum(sizes[used:used+n]);used+=n;intervals.append((off,off+length))
    if used!=count:_err('unmapped samples')
    if b'ctts'in sb:
        cb,cn=_table(r,sb[b'ctts'],8)
        if any(_u(cb,8+8*i+4)!=0 for i in range(cn)) or sum(_u(cb,8+8*i) for i in range(cn))!=count:_err('unsupported composition offsets')
    if handler=='vide':
        _need(sb,[b'stss']);kb,kn=_table(r,sb[b'stss'],4);keys=[_u(kb,8+4*i) for i in range(kn)]
        if keys[0]!=1 or keys[-1]>count or any(a>=b for a,b in zip(keys,keys[1:])) or b'sgpd'in sb or b'sbgp'in sb:_err('keyframe/roll metadata')
    else:
        _need(sb,[b'sgpd',b'sbgp']);gb=r.body(sb[b'sgpd']);bb=r.body(sb[b'sbgp'])
        if gb!=bytes.fromhex('01000000726f6c6c0000000200000001ffff') or bb!=b'\0'*4+b'roll'+struct.pack('>III',1,count,1):_err('AAC roll/priming metadata')
        if b'stss'in sb:_err('audio keyframe table')
    facts={'handler':handler,'codec':config['codec'],'timescale':scale,'duration':dur,'sample_count':count,'stts':runs,'edit':edit,'track_duration':duration}
    if facts!=_plain(expected):_err('track timing/count/edit differs from pinned plan')
    return facts,config,intervals,tid

def validate_media_fd(fd,expected,*,kind,max_bytes,cancel=None,forbidden_fds=()):
    """Expected is the authenticated task.expected mapping from media.parse_plan.
    Returns structural observations only. Preserves offsets, never opens paths.
    """
    _poll(cancel)
    if type(fd)is not int or fd<0 or kind not in('wav','movie') or type(max_bytes)is not int or not 1<=max_bytes<=128*1024*1024:_err('FD/type/byte budget')
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or not 8<=st.st_size<=max_bytes:_err('regular output/size budget')
        for other in forbidden_fds:
            if type(other)is not int or other<0:_err('source FD type')
            s=os.fstat(other)
            if (s.st_dev,s.st_ino)==(st.st_dev,st.st_ino):_err('source/output FD alias')
        r=_Reader(fd,st.st_size,cancel);root=r.children(0,st.st_size)
        if [x[0] for x in root]!=[b'ftyp',b'free',b'mdat',b'moov']:_err('top-level closure/order/extra tail')
        ftyp,free,mdat,moov=root
        if r.body(ftyp,64).hex()!=expected['ftyp_hex'] or any(r.body(free,4096)):_err('ftyp/known padding profile')
        moov_rows=r.children(moov[1],moov[2],1)
        tracks=[x for x in moov_rows if x[0]==b'trak']
        mi=r.index([x for x in moov_rows if x[0]!=b'trak'],{b'mvhd'},'moov')
        _need(mi,[b'mvhd']);scale,dur=_time(r.body(mi[b'mvhd']),'mvhd')
        if (scale,dur)!=(expected['movie_timescale'],expected['movie_duration']) or len(tracks)!=(1 if kind=='wav' else 2):_err('movie duration/track cardinality')
        by_handler={x['handler']:x for x in expected['tracks']};observed=[];configs=[];intervals=[];ids=set();seen=set()
        for row in tracks:
            # Select by independently parsed hdlr, then exact required cardinality.
            mdia=_select(r.children(row[1],row[2],2),b'mdia')
            hdlr=_select(r.children(mdia[1],mdia[2],3),b'hdlr');hb=r.body(hdlr,4096)
            if len(hb)<12:_err('short handler')
            handler=hb[8:12].decode('ascii','strict')
            if handler in seen or handler not in by_handler:_err('duplicate/extra handler')
            facts,config,parts,tid=_track(r,row,by_handler[handler])
            if tid in ids:_err('duplicate track ID')
            seen.add(handler);ids.add(tid);observed.append(facts);configs.append(config);intervals+=parts
        if seen!=set(by_handler):_err('missing handler')
        pos=mdat[1]
        for start,end in sorted(intervals):
            if start!=pos or end<=start or end>mdat[2]:_err('mdat gap/overlap/unowned/out-of-range chunk')
            pos=end
        if pos!=mdat[2]:_err('mdat trailing/unowned bytes')
        endstat=os.fstat(fd)
        if (endstat.st_dev,endstat.st_ino,endstat.st_size,endstat.st_mtime_ns)!=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns):_err('file changed during validation')
        return {'coverage':'required-container-structure-and-mdat-ownership; not access-unit decode','bytes':st.st_size,'movie_timescale':scale,'movie_duration':dur,'tracks':sorted(observed,key=lambda t:t['handler']),'codecs':configs,'boxes_checked':r.boxes,'metadata_bytes_read':r.metadata,'unknown_metadata_skipped':r.unknown,'unknown_metadata_bytes':r.unknown_bytes}
    except (OSError,ValueError,UnicodeError,struct.error,OverflowError,KeyError,TypeError) as exc:
        if isinstance(exc,OriginalInputError):raise
        raise OriginalInputError('Media container malformed/closed FD') from exc
