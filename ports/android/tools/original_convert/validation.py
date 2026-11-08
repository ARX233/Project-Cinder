"""Final checks for a controlled original-conversion job, never external imports.

SourceEntry records originate in this process's converters. A private completion
record is post-job integrity metadata, not a presigned legacy resource manifest.
"""
import hashlib
import os
from pathlib import Path
import stat
import struct
from .source import OwnedOutput,SourceEntry,OriginalInputError,HASH,source_path,check_cancel


def validate_ao_fd(fd,expected_layout,*,cancel=None):
    st=os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or not 8<=st.st_size<=16*1024*1024:
        raise OriginalInputError('Invalid AO file size/type')
    head=os.pread(fd,8,0)
    if len(head)!=8 or head[:4]!=b'WAO1':raise OriginalInputError('Invalid AO header')
    count=struct.unpack_from('<I',head,4)[0]
    if not isinstance(expected_layout,list) or count!=len(expected_layout) or count>256:
        raise OriginalInputError('AO map ownership/count differs from reviewed recipe')
    offset=8;names=set()
    for row in expected_layout:
        check_cancel(cancel)
        if not isinstance(row,dict) or set(row)!={'name_hex','width','height'}:raise OriginalInputError('Invalid reviewed AO shape')
        block=os.pread(fd,52,offset)
        if len(block)!=52:raise OriginalInputError('Truncated AO map header')
        name=block[:48];w,h=struct.unpack_from('<HH',block,48)
        if name.hex()!=row['name_hex'] or (w,h)!=(row['width'],row['height']) or (w,h)!=(256,256) or name in names:
            raise OriginalInputError('AO map identity/dimensions differ from reviewed recipe')
        names.add(name);offset+=52+w*h
        if offset>st.st_size:raise OriginalInputError('Truncated AO pixels')
    if offset!=st.st_size:raise OriginalInputError('Unexpected AO file tail')
    return {'maps':count,'bytes':offset}


def _identity(st):return(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)


def verify_owned_outputs(output,targets,*,cancel=None,progress=None):
    """Only this process's new output capability, exact recipe paths and receipts."""
    if not isinstance(output,OwnedOutput) or not isinstance(targets,dict) or len(targets)!=1801:
        raise OriginalInputError('Complete controlled 1801-file output capability required')
    if set(output.files)!=set(targets):raise OriginalInputError('Missing or unexpected converter output ownership')
    expected_dirs={''}
    for name in targets:
        source_path('data/'+name)
        parts=name.split('/')
        expected_dirs.update('/'.join(parts[:k]) for k in range(1,len(parts)))
    actual=set();pending=[('',output.root)]
    while pending:
        parent,path=pending.pop()
        with os.scandir(path) as entries:
            for item in entries:
                check_cancel(cancel);name=(parent+'/' if parent else '')+item.name
                if item.is_symlink():raise OriginalInputError('Converter output contains a symbolic link')
                if item.is_dir(follow_symlinks=False):
                    if name not in expected_dirs:raise OriginalInputError('Unexpected converter output directory')
                    pending.append((name,Path(item.path)))
                elif item.is_file(follow_symlinks=False):
                    if name not in targets or name in actual:raise OriginalInputError('Unexpected converter output file')
                    actual.add(name)
                else:raise OriginalInputError('Converter output contains a special file')
    if actual!=set(targets):raise OriginalInputError('Converter output tree is incomplete')
    rows=[]
    for number,name in enumerate(sorted(targets)):
        check_cancel(cancel);target=targets[name];registered=output.files[name]
        if not isinstance(registered,SourceEntry):raise OriginalInputError('Missing component completion receipt')
        fd=os.open(output.root/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size!=registered.size or before.st_size>target['max_bytes']:
                raise OriginalInputError('Converter output size/type changed')
            h=hashlib.sha256();offset=0
            while offset<before.st_size:
                check_cancel(cancel);block=os.pread(fd,min(128*1024,before.st_size-offset),offset)
                if not block:raise OriginalInputError('Converter output short read')
                h.update(block);offset+=len(block)
            digest=h.hexdigest()
            if digest!=registered.sha256 or (target['sha256'] is not None and digest!=target['sha256']):
                raise OriginalInputError('Converter output differs from validated component/reviewed byte profile: '+name)
            if target['kind']=='ao':validate_ao_fd(fd,target['ao_layout'],cancel=cancel)
            elif target['sha256'] is None and target['kind'] not in ('m4a','mp4'):
                raise OriginalInputError('Unreviewed generated-output format')
            if _identity(before)!=_identity(os.fstat(fd)):raise OriginalInputError('Converter output changed during verification')
        finally:os.close(fd)
        rows.append({'path':name,'bytes':registered.size,'sha256':digest})
        if progress:progress('verify-original-output',number+1,len(targets))
    return rows


def completion_bytes(job,output,rows):
    if (not isinstance(output,OwnedOutput) or not isinstance(job,dict) or len(rows)!=1801 or
            not output.root.name.startswith('original-convert-')):
        raise OriginalInputError('Only a complete controlled job may receive a completion record')
    header=['WMMT-ORIGINAL-COMPLETION-1','job\t'+job['job_id'],'nonce\t'+job['nonce'],
            'profile\t'+job['profile_sha256'],'readset\t'+job['readset_sha256'],'output\t'+output.root.name]
    previous=''
    for row in rows:
        name=row['path'];source_path('data/'+name)
        if name<=previous or not HASH.fullmatch(row['sha256']) or type(row['bytes']) is not int or row['bytes']<0:
            raise OriginalInputError('Invalid completion ownership record')
        header.append('file\t%s\t%d\t%s'%(name,row['bytes'],row['sha256']));previous=name
    return ('\n'.join([*header,'END',''])).encode('utf-8')
