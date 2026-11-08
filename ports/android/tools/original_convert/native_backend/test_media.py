#!/usr/bin/env python3
"""Host ABI tests; optional --original-data decodes only Bink/WAV data, no game code."""
import argparse, json, math, os, pathlib, struct, wave, hashlib, time, uuid
from media_ctypes import Backend, Limits
p=argparse.ArgumentParser();p.add_argument('--work',required=True);p.add_argument('--original-data');a=p.parse_args()
w=pathlib.Path(a.work).resolve();d=w/'proof'/('run-'+uuid.uuid4().hex[:8]);d.mkdir()
b=Backend(w/'prefix-host/lib/liboc_media.dylib');reports=[]
source=d/'tone-48k-mono.wav'
with wave.open(str(source),'wb') as f:
    f.setparams((1,2,48000,0,'NONE','not compressed'))
    f.writeframes(b''.join(struct.pack('<h',int(12000*math.sin(2*math.pi*440*i/48000))) for i in range(48000*2)))
def run(name,mode=1,src=source,audio=None,limits=None,cancel=lambda:False,expected=0,existing=False):
    out=d/(name+('.mp4' if mode==2 else '.m4a'))
    if existing:out.write_bytes(b'PRESERVE_OLD_OUTPUT')
    outfd=os.open(out,os.O_RDWR if existing else os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    infd=os.open(src,os.O_RDONLY);afd=os.open(audio,os.O_RDONLY) if audio else -1
    try:
        os.lseek(infd,7,0);os.lseek(outfd,3,0)
        start=time.monotonic();r=b.convert(mode,infd,afd,outfd,limits or Limits(),cancel)
        item={'name':name,'elapsed_s':round(time.monotonic()-start,3),'source':str(src),'audio':str(audio) if audio else None,'output':str(out),**r.as_dict()}
        assert os.lseek(infd,0,1)==7 and os.lseek(outfd,0,1)==3,'FD offsets changed'
        assert r.status==expected,item
        assert out.stat().st_size <= (limits or Limits()).max_output_bytes or existing
        if existing:assert out.read_bytes()==b'PRESERVE_OLD_OUTPUT'
        if r.status==0:
            with out.open('rb') as f:assert f.read(12)[4:8]==b'ftyp'
        reports.append(item);print(json.dumps(item),flush=True);return out
    finally:
        os.close(outfd);os.close(infd)
        if afd>=0:os.close(afd)
run('tone-success')
run('cancel-before',cancel=lambda:True,expected=-2)
calls=[0]
def cancel_mid():calls[0]+=1;return calls[0]>40
run('cancel-mid',cancel=cancel_mid,expected=-2)
run('output-budget',limits=Limits(max_output_bytes=128),expected=-3)
run('duration-budget',limits=Limits(max_duration_ms=100),expected=-3)
run('input-budget',limits=Limits(max_input_bytes=128),expected=-3)
run('existing-preserved',existing=True,expected=-1)
bad=d/'bad.wav';bad.write_bytes(b'not media bytes at all')
run('reject-not-wav',src=bad,expected=-1)
run('preview',limits=Limits(preview_duration_ms=250))
def slow_check():
    # Deliberately spend CPU inside callback to cross a 1ms monotonic deadline.
    sum(range(1000000));return False
run('wall-budget',limits=Limits(max_wall_ms=1),cancel=slow_check,expected=-3)
run('bad-abi',limits=Limits(abi=999),expected=-1)
run('zero-frame-budget',limits=Limits(max_video_frames=0),expected=-1)
if a.original_data:
    root=pathlib.Path(a.original_data)
    wav=root/'sound/bgm/attract/opening_japan.wav';bik=root/'movie/atruct.bik'
    run('original-wav-full',src=wav)
    run('original-intro-full',mode=2,src=bik,audio=wav)
    run('original-movie-frame-budget',mode=2,src=bik,audio=wav,limits=Limits(max_video_frames=1),expected=-3)
    run('original-resolution-budget',mode=2,src=bik,audio=wav,limits=Limits(max_width=320),expected=-3)
    run('reject-not-bink',mode=2,src=bad,audio=wav,expected=-1)
    for movie,bgm in [('playdemo','demo'),('tutorial','tutorial')]:
        run('original-'+movie+'-full',mode=2,src=root/f'movie/{movie}.bik',audio=root/f'sound/bgm/attract/{bgm}_japan.wav')
(d/'results.json').write_text(json.dumps({'library':b.lib.oc_media_build_info().decode(),'tests':reports},indent=2)+'\n')
print('RESULTS='+str(d/'results.json'))
