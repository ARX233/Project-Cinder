#!/usr/bin/env python3
"""Supplemental host proof: one original WAV for every observed PCM header class."""
import argparse,json,os,pathlib,subprocess,uuid
from media_ctypes import Backend,Limits
p=argparse.ArgumentParser();p.add_argument('--work',required=True);a=p.parse_args();w=pathlib.Path(a.work).resolve();b=Backend(w/'prefix-host/lib/liboc_media.dylib');inventory=json.loads((w/'logs/original-wav-headers.json').read_text());classes={}
for f in inventory['files']:classes.setdefault(tuple(f[k] for k in ['format_tag','channels','sample_rate','bits']),f['path'])
d=w/'proof'/('pcm-classes-'+uuid.uuid4().hex[:8]);d.mkdir();rows=[]
for i,(key,source) in enumerate(classes.items()):
    out=d/f'class-{i}.m4a';infd=os.open(source,os.O_RDONLY);outfd=os.open(out,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
    try:r=b.convert(1,infd,-1,outfd,Limits())
    finally:os.close(infd);os.close(outfd)
    assert r.status==0,r.as_dict();v=subprocess.run([str(w/'proof/verify_media'),str(out)],check=True,capture_output=True,text=True);decoded=json.loads(v.stdout);assert len(decoded['streams'])==1 and decoded['streams'][0]['codec']=='aac'
    rows.append({'source_class':key,'source':source,'output':str(out),'conversion':r.as_dict(),'decode':decoded})
with (d/'results.json').open('x') as f:json.dump(rows,f,indent=2);f.write('\n')
print(d/'results.json')
