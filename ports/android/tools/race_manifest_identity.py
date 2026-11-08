"""Bounded static Android binary-XML package/version identity, not Android ABI.
Only reads the reviewed candidate manifest; no SDK invocation or target loading.
"""
import struct
from resource_pack_common import require

ANDROID='http://schemas.android.com/apk/res/android'
NONE=0xffffffff

def identity(raw, *, version_code=2, version_name='0.2'):
    require(type(raw)is bytes and 8<=len(raw)<=1024**2,'manifest byte budget')
    require(struct.unpack_from('<HHI',raw)==(3,8,len(raw)),'binary XML root header')
    strings=None;root=None;stack=[];offset=8;roots=0
    while offset<len(raw):
        require(offset+8<=len(raw),'truncated XML chunk')
        kind,head,size=struct.unpack_from('<HHI',raw,offset)
        require(8<=head<=size and size%4==0 and size<=len(raw)-offset,'XML chunk bounds')
        b=raw[offset:offset+size]
        if kind==1:
            require(strings is None and root is None and head>=28,'string pool position/header')
            count,styles,flags,start,style_start=struct.unpack_from('<IIIII',b,8)
            require(count<=65536 and styles==0 and style_start==0 and flags in (0,0x100,1,0x101)and
                head+4*count<=start<=size,'string pool bounds/flags')
            strings=[]
            for i in range(count):
                at=start+struct.unpack_from('<I',b,head+4*i)[0]
                require(start<=at<size,'string offset')
                def length(pos,wide):
                    step=2 if wide else 1;require(pos+step<=size,'string length bound')
                    first=struct.unpack_from('<H',b,pos)[0]if wide else b[pos];mask=0x8000 if wide else 0x80
                    if first&mask:
                        require(pos+2*step<=size,'long string length bound')
                        second=struct.unpack_from('<H',b,pos+step)[0]if wide else b[pos+step]
                        return ((first&(mask-1))<<(16 if wide else 8))|second,pos+2*step
                    return first,pos+step
                if flags&0x100:
                    units,at=length(at,False);length_bytes,at=length(at,False)
                    require(at+length_bytes<size and b[at+length_bytes]==0,'UTF8 terminator')
                    text=b[at:at+length_bytes].decode('utf-8','strict')
                    require(len(text.encode('utf-16-le'))//2==units,'UTF8 UTF16-unit count')
                else:
                    units,at=length(at,True);length_bytes=units*2
                    require(at+length_bytes+2<=size and b[at+length_bytes:at+length_bytes+2]==b'\0\0','UTF16 terminator')
                    text=b[at:at+length_bytes].decode('utf-16-le','strict')
                require('\0'not in text,'NUL string');strings.append(text)
        else:
            require(strings is not None,'XML before string pool')
            def string(index):
                require(index!=NONE and index<len(strings),'XML string index');return strings[index]
            if kind in (0x100,0x101):
                require(head==16 and size==24,'namespace node size')
                prefix,uri=struct.unpack_from('<II',b,16);string(prefix);string(uri)
            elif kind==0x180:
                require(head==8 and (size-8)//4<=len(strings),'resource map size')
            elif kind==0x102:
                require(head==16 and size>=36,'start-element header')
                ns,name,attr_start,attr_size,count,id_index,class_index,style_index=struct.unpack_from('<IIHHHHHH',b,16)
                require(attr_start>=20 and attr_size==20 and count<=1024 and 16+attr_start+count*20<=size,'attribute table bounds')
                for value in (id_index,class_index,style_index):require(value<=count,'attribute index bound')
                label=(None if ns==NONE else string(ns),string(name));attrs={}
                for i in range(count):
                    at=16+attr_start+20*i;ans,aname,araw,typed_size,reserved,typ,value=struct.unpack_from('<IIIHBBI',b,at)
                    require(typed_size==8 and reserved==0,'typed attribute header')
                    key=(None if ans==NONE else string(ans),string(aname));require(key not in attrs,'duplicate XML attribute')
                    val=string(value)if typ==3 else value
                    if araw!=NONE:
                        text=string(araw)
                        if typ==3:require(text==val,'raw/typed string contradiction')
                    attrs[key]=(typ,val)
                if not stack:
                    roots+=1;require(roots==1 and label==(None,'manifest'),'unique manifest root');root=attrs
                stack.append(label)
            elif kind==0x103:
                require(head==16 and size==24 and stack,'end-element header')
                ns,name=struct.unpack_from('<II',b,16);label=(None if ns==NONE else string(ns),string(name))
                require(stack.pop()==label,'unbalanced XML element')
            else:
                require(False,'unsupported XML chunk')
        offset+=size
    require(offset==len(raw)and not stack and root is not None,'incomplete XML document')
    require(root.get((None,'package'))==(3,'com.projectcinder.game')and
        root.get((ANDROID,'versionCode'))==(0x10,version_code)and root.get((ANDROID,'versionName'))==(3,version_name),
        f'race release requires com.projectcinder.game versionName{version_name}/versionCode{version_code}')
    return {'package':'com.projectcinder.game','version_name':version_name,'version_code':version_code,
        'static_binary_manifest_identity_only':True}
