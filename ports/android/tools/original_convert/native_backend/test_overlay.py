#!/usr/bin/env python3
"""Real original Bink/PNG proof + independent Pillow pixel references, host only."""
import argparse,ctypes as C,hashlib,json,os,pathlib,subprocess,uuid
from fractions import Fraction
import numpy as np
from PIL import Image
from media_ctypes import Backend,Limits
from media_overlay_ctypes import Overlay,OverlayBackend,load_png_overlay_fd
p=argparse.ArgumentParser();p.add_argument('--base-work',required=True);p.add_argument('--work',required=True);p.add_argument('--original-data',required=True);a=p.parse_args();broot=pathlib.Path(a.base_work).resolve();w=pathlib.Path(a.work).resolve();orig=pathlib.Path(a.original_data);d=w/'proof'/('run-'+uuid.uuid4().hex[:8]);d.mkdir();backend=OverlayBackend(w/'build-host/liboc_media_overlay.dylib');rows=[];samples=[0,7,15,30]
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        while data:=f.read(1024*1024):h.update(data)
    return h.hexdigest()
def ref(before,overlay,pts,num,den):
    # Independent library reference: exact Fraction alpha lookup, then Pillow's
    # alpha_composite implementation (not a reimplementation of native RGB loop).
    rgba=C.string_at(overlay.rgba,overlay.rgba_bytes);im=Image.frombytes('RGBA',(overlay.width,overlay.height),rgba)
    rem=(pts*num)%den;tri=abs(den-2*rem);lut=[alpha*tri//den for alpha in range(256)]
    im.putalpha(im.getchannel('A').point(lut))
    canvas=Image.new('RGBA',(640,480));canvas.paste(im,(overlay.x,overlay.y))
    bg=Image.frombytes('RGB',(640,480),before).convert('RGBA');expected=Image.alpha_composite(bg,canvas).convert('RGB').tobytes()
    return expected,tri,den,max(lut)
def decode(path):
    r=subprocess.run([str(broot/'proof/verify_media'),str(path)],capture_output=True,text=True,check=True);facts=json.loads(r.stdout)
    video=next((s for s in facts['streams'] if s['codec']=='h264'),None)
    if video:assert video['profile']==578 and video['level']<=30 and video['decoded_frames']==video['declared_frames']
    for s in facts['streams']:
        if s['codec']=='aac':assert s['profile']==1 and s['sample_rate']==44100 and s['channels']==2
    return facts
# ABI1 function in the new library must remain byte-identical to old library.
for label,lib in [('old',Backend(broot/'prefix-host/lib/liboc_media.dylib')),('variant',backend)]:
    src=os.open(orig/'movie/playdemo.bik',os.O_RDONLY);aud=os.open(orig/'sound/bgm/attract/demo_japan.wav',os.O_RDONLY);out=d/f'abi1-{label}.mp4';ofd=os.open(out,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    try:r=lib.convert(2,src,aud,ofd,Limits(preview_duration_ms=1000));assert r.status==0,r.as_dict()
    finally:os.close(src);os.close(aud);os.close(ofd)
assert sha(d/'abi1-old.mp4')==sha(d/'abi1-variant.mp4');rows.append({'test':'ABI1-export-compatibility','sha256':sha(d/'abi1-old.mp4')})

for movie,bgm in [('playdemo','demo'),('tutorial','tutorial')]:
    source=orig/f'movie/{movie}.bik';audio=orig/f'sound/bgm/attract/{bgm}_japan.wav';png=orig/f'sprite/atract_p_movie_{movie}.png';source_samples=d/(movie+'-source-rgb');source_samples.mkdir()
    subprocess.run([str(w/'proof/extract_rgb_frames'),str(source),str(source_samples),','.join(map(str,samples))],check=True,capture_output=True,text=True)
    capture_by_mode={}
    for enabled in [False,True]:
        mode='blink' if enabled else 'plain';out=d/f'{movie}-{mode}.mp4';infd=os.open(source,os.O_RDONLY);afd=os.open(audio,os.O_RDONLY);ofd=os.open(out,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600);pfd=os.open(png,os.O_RDONLY);captured={}
        try:
            os.lseek(pfd,9,0);overlay=load_png_overlay_fd(pfd,other_fds=(infd,afd,ofd));assert os.lseek(pfd,0,1)==9
            def observer(before,after,width,height,stride,pts,num,den):
                if pts not in samples:return
                assert (width,height,stride)==(640,480,1920)
                before=C.string_at(before,width*height*3);after=C.string_at(after,width*height*3)
                assert before==(source_samples/f'frame-{pts}.rgb').read_bytes(),'source RGB differs from independent decode'
                expected,tri,period,max_alpha=ref(before,overlay,pts,num,den) if enabled else (before,0,1,0)
                arr=np.frombuffer(after,dtype=np.uint8).astype(np.int16);exp=np.frombuffer(expected,dtype=np.uint8).astype(np.int16);error=np.abs(arr-exp)
                assert int(error.max())<=1,('Pillow independent per-pixel mismatch',pts,int(error.max()))
                mask=np.ones((height,width),dtype=bool);mask[overlay.y:overlay.y+overlay.height,overlay.x:overlay.x+overlay.width]=False
                aa=np.frombuffer(after,dtype=np.uint8).reshape(height,width,3);bb=np.frombuffer(before,dtype=np.uint8).reshape(height,width,3)
                assert np.array_equal(aa[mask],bb[mask]),'unexpected pixels outside label box'
                if pts==15:assert after==before,'quantized-alpha zero frame must be exactly unchanged'
                if enabled and pts==0:assert after!=before,'peak must visibly composite label'
                captured[int(pts)]={'pts':pts,'tb_num':num,'tb_den':den,'triangle':str(Fraction(tri,period)),'max_effective_alpha8':max_alpha,'pillow_max_channel_error':int(error.max()),'changed_rgb_bytes':int(np.count_nonzero(aa!=bb)),'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(after).hexdigest()}
                # Retain only four sampled frames, never a complete movie.
                (d/f'{movie}-{mode}-frame-{pts}.rgb').write_bytes(after)
            r=backend.convert_overlay(2,infd,afd,ofd,Limits(),overlay if enabled else None,observer=observer)
            assert r.status==0,(r.as_dict(),r._observer_error);assert set(captured)==set(samples)
        finally:
            for fd in [infd,afd,ofd,pfd]:os.close(fd)
        verified=decode(out);video=next(s for s in verified['streams'] if s['codec']=='h264');assert video['decoded_frames']==r.video_frames
        output_samples=d/f'{movie}-{mode}-decoded-rgb';output_samples.mkdir();subprocess.run([str(w/'proof/extract_rgb_frames'),str(out),str(output_samples),','.join(map(str,samples))],check=True,capture_output=True,text=True)
        for pts in samples:
            decoded=np.frombuffer((output_samples/f'frame-{pts}.rgb').read_bytes(),dtype=np.uint8).astype(np.int16).reshape(480,640,3)
            rendered=np.frombuffer((d/f'{movie}-{mode}-frame-{pts}.rgb').read_bytes(),dtype=np.uint8).astype(np.int16).reshape(480,640,3)
            crop=(slice(overlay.y,overlay.y+overlay.height),slice(overlay.x,overlay.x+overlay.width))
            mae=float(np.abs(decoded[crop]-rendered[crop]).mean());assert mae<16,('encoded label crop distortion too high',movie,mode,pts,mae)
            captured[pts]['encoded_crop_mae']=mae
        capture_by_mode[mode]=captured
        rows.append({'test':'full-movie-'+movie+'-'+mode,'output':str(out),'output_sha256':sha(out),'original_png_sha256':sha(png),'conversion':r.as_dict(),'fully_decoded':verified,'pixel_samples':captured})
    # Exact T=1/2 (not a native Bink timestamp) on an actual decoded movie frame:
    # independently assert complete pixel identity using the real original PNG.
    pfd=os.open(png,os.O_RDONLY)
    try:o=load_png_overlay_fd(pfd)
    finally:os.close(pfd)
    before=(source_samples/'frame-15.rgb').read_bytes();rgb=(C.c_uint8*len(before)).from_buffer_copy(before)
    assert backend.lib.oc_media_overlay_apply_rgb24(C.byref(o),rgb,len(rgb),640,480,1920,1,1,2)==0
    assert bytes(rgb)==before
    rows.append({'test':'exact-half-second-zero-'+movie,'rgb_sha256':hashlib.sha256(before).hexdigest()})

# Fail-closed native overlay validation; output remains empty for invalid options.
png=orig/'sprite/atract_p_movie_playdemo.png';pfd=os.open(png,os.O_RDONLY)
try:good=load_png_overlay_fd(pfd)
finally:os.close(pfd)
for field,value in [('abi',99),('size',4),('width',513),('height',129),('stride_bytes',1),('rgba_bytes',2**64-1),('rgba',None),('x',-1),('y',480),('flags',1)]:
    o=Overlay(C.string_at(good.rgba,good.rgba_bytes),good.width,good.height);setattr(o,field,value);out=d/f'invalid-{field}.mp4';ofd=os.open(out,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600);infd=os.open(orig/'movie/playdemo.bik',os.O_RDONLY);afd=os.open(orig/'sound/bgm/attract/demo_japan.wav',os.O_RDONLY)
    try:r=backend.convert_overlay(2,infd,afd,ofd,Limits(),o);assert r.status==-1 and out.stat().st_size==0,(field,r.as_dict())
    finally:
        for fd in [ofd,infd,afd]:os.close(fd)
    rows.append({'test':'reject-overlay-'+field,'status':r.status})
for label,pts,num,den in [('negative-pts',-1,1,30),('zero-den',0,1,0),('large-timebase',1,1000000001,30)]:
    rgb=(C.c_uint8*(640*480*3))();before=bytes(rgb);assert backend.lib.oc_media_overlay_apply_rgb24(C.byref(good),rgb,len(rgb),640,480,1920,pts,num,den)==-1;assert bytes(rgb)==before;rows.append({'test':'reject-'+label})
# Mutating RGB must never alias its readonly label input, even via the pure API.
rgb=(C.c_uint8*(640*480*3))();o=Overlay(C.string_at(good.rgba,good.rgba_bytes),good.width,good.height);o.rgba=C.cast(rgb,C.POINTER(C.c_uint8));before=bytes(rgb)
assert backend.lib.oc_media_overlay_apply_rgb24(C.byref(o),rgb,len(rgb),640,480,1920,0,1,30)==-1 and bytes(rgb)==before
rows.append({'test':'reject-rgba-rgb-memory-alias'})
assert backend.lib.oc_media_overlay_apply_rgb24(C.byref(good),rgb,len(rgb)-1,640,480,1920,0,1,30)==-1 and bytes(rgb)==before
rows.append({'test':'reject-rgb-byte-bound'})
# Strict PNG FD checks before decode, including source/output inode alias.
pfd=os.open(png,os.O_RDONLY)
try:
    try:load_png_overlay_fd(pfd,other_fds=(pfd,));raise AssertionError('alias accepted')
    except ValueError:pass
finally:os.close(pfd)
rows.append({'test':'reject-png-inode-alias'})
for label,size,animated in [('oversized',(513,16),False),('animated',(16,16),True)]:
    path=d/f'bad-{label}.png';im=Image.new('RGBA',size,(255,255,255,255));im.save(path,save_all=animated,append_images=[Image.new('RGBA',size,(0,0,0,0))] if animated else [])
    fd=os.open(path,os.O_RDONLY)
    try:
        try:load_png_overlay_fd(fd);raise AssertionError('invalid PNG accepted')
        except ValueError:pass
    finally:os.close(fd)
    rows.append({'test':'reject-png-'+label})
rfd,wfd=os.pipe()
try:
    try:load_png_overlay_fd(rfd);raise AssertionError('PNG pipe accepted')
    except ValueError:pass
finally:os.close(rfd);os.close(wfd)
rows.append({'test':'reject-png-pipe'})
# Cancellation after actual frame compositing, and inherited output-byte budget.
for label,cancel,limits in [('cancel-in-observer',True,Limits()),('output-budget',False,Limits(max_output_bytes=128))]:
    out=d/f'{label}.mp4';ofd=os.open(out,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600);infd=os.open(orig/'movie/playdemo.bik',os.O_RDONLY);afd=os.open(orig/'sound/bgm/attract/demo_japan.wav',os.O_RDONLY);seen=[False]
    def observe_cancel(*_):seen[0]=True
    try:r=backend.convert_overlay(2,infd,afd,ofd,limits,good,cancel=lambda:cancel and seen[0],observer=observe_cancel);assert r.status==(-2 if cancel else -3);assert out.stat().st_size<=limits.max_output_bytes
    finally:
        for fd in [ofd,infd,afd]:os.close(fd)
    rows.append({'test':label,'result':r.as_dict()})
for label,limits,expected in [('frame-budget',Limits(max_video_frames=1),-3),('duration-budget',Limits(max_duration_ms=100),-3),('resolution-budget',Limits(max_width=320),-3),('observer-throws',Limits(),-2),('old-output-preserved',Limits(),-1),('preview-overlay',Limits(preview_duration_ms=300),0)]:
    out=d/f'{label}.mp4'
    if label=='old-output-preserved':out.write_bytes(b'KEEP_OLD_OUTPUT')
    ofd=os.open(out,os.O_RDWR if label=='old-output-preserved' else os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600);infd=os.open(orig/'movie/playdemo.bik',os.O_RDONLY);afd=os.open(orig/'sound/bgm/attract/demo_japan.wav',os.O_RDONLY)
    def raising_observer(*_):raise RuntimeError('intentional observer cancellation')
    try:
        r=backend.convert_overlay(2,infd,afd,ofd,limits,good,observer=raising_observer if label=='observer-throws' else None)
        assert r.status==expected,(label,r.as_dict())
        if label=='old-output-preserved':assert out.read_bytes()==b'KEEP_OLD_OUTPUT'
        if label=='preview-overlay':assert 'with original blink' in bytes(r.message).decode()
    finally:
        for fd in [ofd,infd,afd]:os.close(fd)
    rows.append({'test':label,'result':r.as_dict()})
with (d/'results.json').open('x') as f:json.dump({'library':backend.lib.oc_media_overlay_build_info().decode(),'tests':rows},f,indent=2);f.write('\n')
print('RESULTS='+str(d/'results.json'));print('PASSED='+str(len(rows)))
