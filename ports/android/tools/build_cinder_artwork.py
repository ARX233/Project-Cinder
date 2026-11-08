#!/usr/bin/env python3
"""Prepare user-approved Cinder artwork, preserving aspect ratio and safe icon bounds."""
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw
import argparse, hashlib, json, math
PINS={'wallpaper':'2fcfa2aeeae006fc3cd10a9eafd73c577ca3657312ac9fbfb063a3bddf46054e','icon':'7f482afc7ea4c2d44d6e72ca60ad385a76f71fb1e1bee917e27fa13e74520428'}
def sha(data):return hashlib.sha256(data).hexdigest()
def build(wallpaper,icon,out):
    out=Path(out);assert out.is_absolute() and not out.exists();out.mkdir(mode=0o700)
    inputs={}
    for key,p in [('wallpaper',wallpaper),('icon',icon)]:
        p=Path(p);assert p.is_file() and not p.is_symlink();data=p.read_bytes();assert sha(data)==PINS[key],key+' unapproved image'
        inputs[key]=data
    with Image.open(icon) as original:
        original.load();im=original.convert('RGB')
    # Ignore white JPEG matte; do not squeeze the 16:9 source into a square.
    mask=Image.new('L',im.size);mask.putdata([255 if min(rgb)<232 else 0 for rgb in im.getdata()]);box=mask.getbbox();assert box
    box=(max(0,box[0]-3),max(0,box[1]-3),min(im.width,box[2]+3),min(im.height,box[3]+3));crop=im.crop(box)
    rgba=Image.new('RGBA',crop.size);pixels=[]
    for rgb in crop.getdata():
        alpha=255-min(rgb)
        if alpha<12:pixels.append((0,0,0,0));continue
        # Reverse compositing over white, retaining the supplied black/yellow/green.
        color=tuple(max(0,min(255,round((c-255+alpha)*255/alpha))) for c in rgb)
        pixels.append((*color,alpha))
    rgba.putdata(pixels)
    def centered(size,scale,transparent):
        art=rgba.resize((max(1,round(rgba.width*scale)),max(1,round(rgba.height*scale))),Image.Resampling.LANCZOS)
        canvas=Image.new('RGBA',(size,size),(0,0,0,0) if transparent else (255,255,255,255))
        canvas.alpha_composite(art,((size-art.width)//2,(size-art.height)//2));return canvas
    legacy=centered(512,400/max(rgba.size),False).convert('RGB')
    cx,cy=rgba.width/2,rgba.height/2
    radius=max(math.hypot(x+.5-cx,y+.5-cy) for y in range(rgba.height) for x in range(rgba.width) if rgba.getpixel((x,y))[3]>16)
    # 108dp adaptive foreground; all visible artwork fits within the 66dp safe circle.
    foreground=centered(432,(432*32/108)/radius,True)
    resources={
      'res/mipmap/icon.png':legacy,
      'res/drawable-nodpi/cinder_icon_foreground.png':foreground}
    rows=[]
    def put(name,data):
        p=out/name;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(data)
        rows.append({'path':name,'bytes':len(data),'sha256':sha(data)})
    import io
    for name,image in resources.items():
        b=io.BytesIO();image.save(b,format='PNG',optimize=True);put(name,b.getvalue())
    put('res/mipmap-anydpi-v26/icon.xml',b'<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android"><background android:drawable="@color/cinder_icon_background"/><foreground android:drawable="@drawable/cinder_icon_foreground"/></adaptive-icon>\n')
    put('res/values/colors.xml',b'<?xml version="1.0" encoding="utf-8"?>\n<resources><color name="cinder_icon_background">#FFFFFFFF</color></resources>\n')
    put('assets/original-convert/launcher-wallpaper.jpg',inputs['wallpaper'])
    # Derived preview only; not part of APK resource whitelist.
    preview=Image.new('RGB',(1056,552),(225,228,232));preview.paste(legacy,(8,28))
    adaptive=Image.new('RGBA',(432,432),'white');adaptive.alpha_composite(foreground)
    viewport=adaptive.crop((72,72,360,360)).resize((512,512),Image.Resampling.LANCZOS)
    round_mask=Image.new('L',(512,512));ImageDraw.Draw(round_mask).ellipse((0,0,511,511),fill=255)
    preview.paste(viewport.convert('RGB'),(536,28),round_mask)
    preview.save(out/'icon-preview.png')
    report={'schema':'project-cinder-artwork-v1','sources':PINS,'source_icon_dimensions':list(im.size),'source_crop_box':list(box),'preserved_aspect_ratio':True,'adaptive_foreground_dp':108,'adaptive_visible_safe_circle_dp':66,'artwork_radius_dp':32,'files':sorted(rows,key=lambda r:r['path'])}
    with (out/'artwork-manifest.json').open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--wallpaper',type=Path,required=True);p.add_argument('--icon',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.wallpaper,a.icon,a.out),indent=2))
