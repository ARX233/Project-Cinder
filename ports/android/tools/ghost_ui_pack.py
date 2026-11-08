#!/usr/bin/env python3
"""Opt-in private Ghost UI WCP1 conversion. This does not approve a ResourceStore catalog.

Example: ghost_ui_pack.py --source-root ORIGINAL --base-menu VERIFIED/menu.bin
                         --output NEW/ghost-ui.bin
Inputs remain read-only; output and adjacent receipts must not already exist.
"""
import argparse
import hashlib
import json
from pathlib import Path
from original_convert.menu_support import OriginalSupport
from original_convert.ghost_ui import pack_ghost_ui
import struct


def inventory(path):
    """Only base identities; do not import legacy generators or generated headers."""
    ids=set();names=set()
    with path.open('rb') as f:
        length=path.stat().st_size
        def read(n):
            b=f.read(n)
            if len(b)!=n:raise ValueError('truncated WMN3')
            return b
        def skip(n):
            if n<0 or n>length-f.tell():raise ValueError('WMN3 range outside file')
            f.seek(n,1)
        if read(4)!=b'WMN3':raise ValueError('base must be WMN3')
        n,=struct.unpack('<I',read(4))
        if n>65535:raise ValueError('base sprite count')
        for _ in range(n):
            sid,w,h,z=struct.unpack('<iHHI',read(12))
            if sid<0 or sid in ids or w>2048 or h>2048:raise ValueError('base sprite identity')
            ids.add(sid);skip(z or w*h*4)
        n,=struct.unpack('<I',read(4))
        if n>4096:raise ValueError('base animation count')
        for _ in range(n):
            name,nf,nr=struct.unpack('<48sII',read(56))
            if b'\0' not in name:raise ValueError('base animation name')
            name=name.split(b'\0')[0].decode('ascii')
            if name in names:raise ValueError('duplicate base animation')
            names.add(name);skip(nf*8+nr*44)
        if f.tell()!=length:raise ValueError('base trailing bytes')
    return ids,names


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',required=True,type=Path)
    p.add_argument('--base-menu',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();root=a.source_root.resolve(strict=True)
    support=OriginalSupport.from_main(root/'main')
    if not a.base_menu.is_file() or a.base_menu.stat().st_size>512*1024*1024:
        p.error('base-menu must be a bounded reviewed WMN3 input')
    expected=a.output.with_suffix('.expected.json');provenance=a.output.with_suffix('.provenance.json')
    if a.output.exists() or expected.exists() or provenance.exists():p.error('outputs already exist')
    ids,anims=inventory(a.base_menu);reads={}
    def read(path,**kw):
        source=(root/path).resolve(strict=True)
        if root not in source.parents or not source.is_file():raise ValueError('source escapes original root')
        if source.stat().st_size>kw.get('max_bytes',32*1024*1024):raise ValueError('source byte limit')
        b=source.read_bytes();reads[path]={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()};return b
    r=pack_ghost_ui(read,support,ids,anims,a.output)
    with a.base_menu.open('rb') as f:base_digest=hashlib.file_digest(f,'sha256').hexdigest()
    r.update(resource_path='ghost-ui.bin',base_menu_sha256=base_digest,original_read_set=reads,
             sprite_count=len(r['sprite_ids']),animation_count=len(r['animations']))
    with provenance.open('x',encoding='utf-8') as f:json.dump(r,f,sort_keys=True,ensure_ascii=False,indent=2)
    with expected.open('x',encoding='utf-8') as f:
        json.dump({'files':[{'path':'ghost-ui.bin','size':r['bytes'],'sha256':r['observed_sha256']}]},f,sort_keys=True,separators=(',',':'));f.write('\n')
    print(json.dumps({'bytes':r['bytes'],'sha256':r['observed_sha256'],'sprites':r['sprite_count'],'animations':r['animation_count']},sort_keys=True))


if __name__=='__main__':main()
