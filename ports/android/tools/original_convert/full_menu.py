"""Complete explicit WMN3 assembly from original sources and port-owned drawing code.

No generated header/old menu/image/font file is an input. This is a component,
not ResourceStore readiness or a publication authority. Source-derived metadata
is recovered statically by OriginalSupport and the menu_* table helpers.
"""
from collections import OrderedDict
import math
import os
from pathlib import Path
import struct
import zlib
from PIL import Image,ImageDraw,ImageFilter

from .menu_support import OriginalSupport,need,dimensions,MAX_ASSET_BYTES
from .menu_components import SpriteRenderer,_Output,_read,load_anm,load_cutin_lines,crop
from .menu_recipe import build_recipe
from .source import OwnedOutput,check_cancel

# Original clImageResourceManager placeholders and its two runtime screen
# captures. These are not disk assets. The current port represents them by the
# existing WMN3 0xffff empty reference; no substitute image is manufactured.
EMPTY_SOURCE_SPRITES=frozenset((-1,0,1,2,3))
MAX_MENU_FRAMES=100000
MAX_MENU_RECORDS=750000  # the supported complete source uses 547134, not the slice's cap
MAX_DECODED_PIXELS_BYTES=1024*1024*1024


def _complete_recipe(recipe):
    for name,count in (('ANIMS',308),('DEMO_ANIMS',57),('STORYSEL_TEXTS',40),
                       ('STTUNE_TEXTS',326),('WEAR_TEXTS',41),('STEFF_TEXTS',52),('DEMO_TEXTS',221)):
        need(name in recipe and len(recipe[name])==count,'Incomplete full menu recipe: '+name)
    need(len({name for name,_ in recipe['ANIMS']})==308,'Duplicate full menu animation namespace')


def unblend_black(image):
    out=[]
    for r,g,b,_ in image.getdata():
        a=max(r,g,b);out.append((r*255//a,g*255//a,b*255//a,a) if a else (0,0,0,0))
    result=Image.new('RGBA',image.size);result.putdata(out);return result


def render_infinity():
    w,h,ss=128,72,4
    mask=Image.new('L',(w*ss,h*ss));draw=ImageDraw.Draw(mask);a,r=42*ss,4.5*ss
    for i in range(2000):
        t=2*math.pi*i/2000;k=1+math.sin(t)**2
        y=a*math.sin(t)*math.cos(t)/k*1.25;x=a*math.cos(t)/k-.2*y
        cx,cy=w*ss/2+x,h*ss/2+y;draw.ellipse((cx-r,cy-r,cx+r,cy+r),fill=255)
    mask=mask.resize((w,h),Image.Resampling.LANCZOS)
    out=Image.new('RGBA',(w,h),(255,0,0,0))
    out.putalpha(mask.filter(ImageFilter.GaussianBlur(3.5)).point(lambda v:min(220,int(v*1.7))))
    white=Image.new('RGBA',(w,h),(254,254,254,255));white.putalpha(mask);out.alpha_composite(white);return out


def _fit_text(renderer,text,width,height,font=3):
    image=renderer.text(font,text)
    scale=min(width/image.width,height/image.height,1.)
    return image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))),Image.Resampling.LANCZOS)


def _vs_icon(renderer,index):
    image=Image.new('RGBA',(256,256));d=ImageDraw.Draw(image)
    d.ellipse((10,10,246,246),fill=(20,35,65,245),outline=(230,235,255,255),width=6)
    d.rounded_rectangle((52,112,204,198),radius=8,fill=(255,255,255,255))
    label=_fit_text(renderer,('BLUETOOTH','LAN','ONLINE')[index],218,38)
    image.alpha_composite(label,((256-label.width)//2,55))
    sub=_fit_text(renderer,'VERSUS',160,22);image.alpha_composite(sub,((256-sub.width)//2,87))
    # Port-authored geometric network pictograms, not system-font glyphs.
    if index==0:
        d.line([(128,124),(128,186),(154,155),(102,135),(154,175),(128,186)],fill='black',width=5)
    elif index==1:
        for radius in (18,30,42):d.arc((128-radius,167-radius,128+radius,167+radius),220,320,fill='black',width=5)
        d.ellipse((123,169,133,179),fill='black')
    else:
        d.ellipse((96,124,160,188),outline='black',width=4)
        d.ellipse((114,124,142,188),outline='black',width=3)
        d.line((97,156,159,156),fill='black',width=3)
    return image


def _vs_line(renderer,index):
    image=Image.new('RGBA',(512,64));d=ImageDraw.Draw(image)
    d.rounded_rectangle((5,8,507,56),radius=12,fill=(10,20,40,220),outline=(210,225,255,240),width=2)
    text=_fit_text(renderer,('NEARBY DEVICE RACE','SAME WI-FI NETWORK','INTERNET SERVER RACE')[index],478,32,1)
    image.alpha_composite(text,((512-text.width)//2,(64-text.height)//2));return image


def pack_full_menu(support,read,output_path,car_data,*,scratch_parent,cancel=None,progress=None):
    need(isinstance(support,OriginalSupport),'OriginalSupport is required')
    need(isinstance(car_data,dict) and len(car_data.get('pack_order',()))==55 and
         len(car_data.get('texts',()))==156,'Complete original menu car tables are required')
    from .menu_scene_sprites import required_scene_sprites
    scene=required_scene_sprites(support.elf,cancel=cancel)
    recipe=build_recipe(support,car_data,scene)
    _complete_recipe(recipe)
    need(not os.path.lexists(output_path),'Full menu output already exists')
    scratch=OwnedOutput(scratch_parent)
    renderer=SpriteRenderer(support,read,cancel=cancel)
    descriptors=OrderedDict();animations=[];seen_anims=set();zipped=set(recipe['ZIPPED'])
    total_frames=total_records=0
    def add(sid,callback):
        need(type(sid) is int and -0x80000000<=sid<=0x7fffffff and sid not in descriptors,
             'Duplicate/invalid full menu sprite ID')
        need(len(descriptors)<16384,'Full menu sprite count budget')
        descriptors[sid]=callback
    def original(sid):
        if sid in EMPTY_SOURCE_SPRITES:return 0xffff
        need(type(sid) is int and sid in support.sprites,'Required full menu source sprite is unavailable')
        if sid not in descriptors:
            def draw(sid=sid):
                image=renderer.sprite(sid,table_size=True)
                return unblend_black(image) if sid in recipe['ON_BLACK'] else image
            add(sid,draw)
        return list_index[sid] if sid in list_index else _index(sid)
    list_index={}
    def _index(sid):
        list_index[sid]=len(descriptors)-1
        return list_index[sid]
    def text_sprite(sid,font,text):add(sid,lambda font=font,text=text:renderer.text(font,text))
    def line_sprite(sid,font,lines):add(sid,lambda font=font,lines=tuple(lines):renderer.lines(font,lines))
    for number,(name,keep) in enumerate(recipe['ANIMS']):
        check_cancel(cancel)
        need(isinstance(name,str) and name.isascii() and 0<len(name)<48 and
             all(c.isalnum() or c=='_' for c in name),'Unsafe full menu animation name')
        if name in seen_anims:continue
        seen_anims.add(name);need(len(seen_anims)<=1024,'Full menu animation count budget')
        data=_read(read,'data/anime/'+name+'.anm',max_bytes=16*1024*1024,cancel=cancel)
        frames,records=load_anm(data,keep=keep,cancel=cancel)
        total_frames+=len(frames);total_records+=len(records)
        need(total_frames<=MAX_MENU_FRAMES and total_records<=MAX_MENU_RECORDS,
             'Complete menu aggregate animation budget exceeded')
        record_path=scratch.target('anim-%04d.records'%number)
        with _Output(record_path,cancel=cancel,max_bytes=16*1024*1024) as records_out:
            for row in records:
                index=original(row[0]);blend={8:1,9:2}.get(row[15],0)
                records_out.write(struct.pack('<HH6f4h4h',index,blend,*row[1:7],
                                             *(max(-32768,min(32767,v)) for v in row[7:15])))
                if name in recipe['DEMO_ANIMS'] and row[0]>=0:zipped.add(row[0])
        animations.append((name,frames,len(records),record_path))
        if progress:progress('read-full-menu-anims',len(animations),len(recipe['ANIMS']))
    for sid in recipe['EXTRA']:original(sid)
    for count,stride,base,offsets in ((32,24,recipe['TEN_CHARA'],(8,12,16)),
                                      (recipe['ST_CHAR_N'],20,recipe['ST_CHAR'],(4,8,12))):
        for k in range(count):
            for offset in offsets:
                sid=support.u32(base+stride*k+offset);original(sid);zipped.add(sid)
    for key,base in [('TEXTS','TEXT_BASE'),('SETTING_TEXTS','SETTING_TEXT_BASE'),('OPTION_TEXTS','OPTION_TEXT_BASE'),
                     ('VS_TEXTS','VS_TEXT_BASE'),('SAVE_TEXTS','SAVE_TEXT_BASE'),('CARD_TEXTS','CARD_TEXT_BASE'),
                     ('STORYSEL_TEXTS','STORYSEL_TEXT_BASE'),('STTUNE_TEXTS','STTUNE_TEXT_BASE'),('WEAR_TEXTS','WEAR_TEXT_BASE')]:
        for k,(font,text) in enumerate(recipe[key]):text_sprite(recipe[base]+k,font,text)
    for k,(font,text) in enumerate(support.bgm_texts()):text_sprite(recipe['BGM_TEXT_BASE']+k,font,text)
    for k in range(3):
        add(recipe['VS_ICON_BASE']+k,lambda k=k:_vs_icon(renderer,k))
        add(recipe['VS_LINE_BASE']+k,lambda k=k:_vs_line(renderer,k))
    for k,c in enumerate(recipe['SAVE_GLYPHS']):text_sprite(recipe['SAVE_GLYPH_BASE']+k,1,c)
    for k,(sid,y0,y1,text) in enumerate(recipe['CARD_HAVE']):
        def card(sid=sid,y0=y0,y1=y1,text=text):
            image=renderer.sprite(sid);image.paste((0,0,0,0),(0,y0,image.width,y1))
            caption=renderer.text(1,text);image.alpha_composite(caption,((image.width-caption.width)//2,(y0+y1-caption.height)//2));return image
        add(recipe['CARD_HAVE_YES']+k,card)
    for base,font,chars in ((recipe['CARD_GLYPH2'],2,recipe['CARD_GLYPHS2']),
                            (recipe['CARD_GLYPH5'],5,recipe['CARD_GLYPHS5'])):
        for k,char in enumerate(chars):text_sprite(base+k,font,char)
    for k,name in enumerate(recipe['CLASS_NAMES']):
        text_sprite(recipe['CARD_CLASS_BASE']+k,5,name+'級\u3000/湾岸の新人')
        text_sprite(recipe['CARD_CLASSP_BASE']+k,5,name+'級\u3000/')
    for k,car in enumerate(c for maker in car_data['makers'] for c in maker['cars']):
        for line in range(2):text_sprite(recipe['CARD_CAR_BASE']+2*k+line,2,car['lines'][line].strip() or ' ')
    for k,text in enumerate(car_data['texts']):text_sprite(recipe['CARD_COLOR_BASE']+k,2,text)
    for k,(font,*lines) in enumerate(recipe['STEFF_TEXTS']):line_sprite(recipe['STEFF_TEXT_BASE']+k,int(font),lines)
    for k,(font,text) in enumerate(support.ten_banners()):text_sprite(recipe['TEN_BANNER_TEXT_BASE']+k,font,text)
    faces=support.cutin_faces()
    def face_image(sid,expression,*,table_size):
        need(sid is not None,'Cut-in requires a real original face sheet')
        image=renderer.sprite(sid,table_size=table_size);width=recipe['CUTIN_FACE']
        columns=4 if table_size else image.width//width
        need(columns>0 and type(expression) is int and expression>=0,'Invalid face sheet cell')
        x,y=expression%columns*width,expression//columns*width
        return crop(image,(x,y,width,width))
    rows=load_cutin_lines(_read(read,recipe['CUTIN_FILE'],max_bytes=1024*1024,cancel=cancel),cancel=cancel)
    for k,(character,expression,lines) in enumerate(rows):
        need(character in faces['names'],'Unknown cut-in character')
        sid=faces['names'][character]
        line_sprite(recipe['CUTIN_TEXT_BASE']+k,recipe['CUTIN_FONT'],lines)
        add(recipe['CUTIN_FACE_BASE']+k,lambda sid=sid,expression=expression:face_image(sid,expression-1,table_size=False))
        zipped.update((recipe['CUTIN_TEXT_BASE']+k,recipe['CUTIN_FACE_BASE']+k))
    for k,(character,expression,text) in enumerate(recipe['DEMO_TEXTS']):
        line_sprite(recipe['DEMO_TEXT_BASE']+k,recipe['CUTIN_FONT'],text.replace('#',' ').replace('\\n','\n').split('\n'))
        sid=faces['by_char'][int(character)]
        if sid is not None:add(recipe['DEMO_FACE_BASE']+k,lambda sid=sid,expression=expression:face_image(sid,int(expression),table_size=True))
        zipped.update((recipe['DEMO_TEXT_BASE']+k,recipe['DEMO_FACE_BASE']+k))
    cells=support.uv_cells()
    for number in recipe['UV_USED']:
        sid,x0,y0,x1,y1=cells[number]
        def uv(sid=sid,x0=x0,y0=y0,x1=x1,y1=y1):
            image=renderer.sprite(sid);x,y=round(x0*image.width/1024),round(y0*image.height/1024)
            right,bottom=round(x1*image.width/1024),round(y1*image.height/1024)
            return crop(image,(x,y,right-x,bottom-y))
        add(recipe['UV_BASE']+number,uv)
    names=support.name_chars()
    for base,font,characters in ((recipe['NAME_GLYPH8_BASE'],8,(*names,*recipe['NAME_KEYS'])),
                                (recipe['NAME_GLYPH10_BASE'],10,names),(recipe['NAME_GLYPH5_BASE'],5,names)):
        for k,char in enumerate(characters):text_sprite(base+k,font,char);zipped.add(base+k)
    titles=support.title_chars()
    for base,font in ((recipe['TITLE_GLYPH1_BASE'],1),(recipe['TITLE_GLYPH5_BASE'],5),(recipe['TITLE_GLYPH7_BASE'],7)):
        for k,char in enumerate(titles):text_sprite(base+k,font,char);zipped.add(base+k)
    add(recipe['INFINITY_ID'],render_infinity)
    receipts=[];decoded_total=0
    with _Output(output_path,cancel=cancel,max_bytes=512*1024*1024) as writer:
        writer.write(b'WMN3'+struct.pack('<I',len(descriptors)))
        for index,(sid,draw) in enumerate(descriptors.items()):
            check_cancel(cancel);image=draw();dimensions(*image.size)
            need(image.mode=='RGBA','Full menu sprite must be RGBA')
            decoded_total+=image.width*image.height*4
            need(decoded_total<=MAX_DECODED_PIXELS_BYTES,'Complete menu decoded-pixel budget exceeded')
            pixels=image.tobytes();packed=zlib.compress(pixels,9) if sid in zipped else b''
            writer.write(struct.pack('<iHHI',sid,*image.size,len(packed)));writer.write(packed or pixels)
            receipts.append({'id':sid,'width':image.width,'height':image.height,'zipped':bool(packed)})
            if progress:progress('render-full-menu-sprites',index+1,len(descriptors))
        writer.write(struct.pack('<I',len(animations)))
        for name,frames,count,record_path in animations:
            writer.write(name.encode('ascii').ljust(48,b'\0')+struct.pack('<II',len(frames),count))
            writer.write(b''.join(struct.pack('<II',*frame) for frame in frames))
            with record_path.open('rb') as f:
                while True:
                    data=f.read(65536)
                    if not data:break
                    writer.write(data)
    return writer.receipt(component='full-menu',profile='wmmt-original-menu-source-v1',
                          full_menu_namespace=True,complete_dataset=False,activated=False,
                          sprites=receipts,animations=len(animations),input_images=renderer.reads,
                          compatibility_rules=['explicit-runtime-captures-empty-v1','parts-literal-case-superset-v1',
                                               'cutin-original-fullwidth-space-v1','port-vs-info-atlas-text-v1'])
