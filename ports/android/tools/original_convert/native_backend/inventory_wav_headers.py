#!/usr/bin/env python3
"""Host proof: bounded RIFF fmt/header inventory; never decodes or executes game code."""
import argparse,collections,json,pathlib,struct
p=argparse.ArgumentParser();p.add_argument('root');a=p.parse_args();rows=[]
for path in sorted(pathlib.Path(a.root).rglob('*.wav')):
    with path.open('rb') as f:
        head=f.read(12)
        if head[:4]!=b'RIFF' or head[8:]!=b'WAVE':rows.append({'path':str(path),'error':'not RIFF WAVE'});continue
        row={'path':str(path)}
        for _ in range(64):
            h=f.read(8)
            if len(h)!=8:break
            tag,n=struct.unpack('<4sI',h)
            if tag==b'fmt ':
                if n<16 or n>65536:raise ValueError('fmt bound')
                data=f.read(min(n,64));fmt,ch,rate,br,align,bits=struct.unpack('<HHIIHH',data[:16]);row.update(format_tag=fmt,channels=ch,sample_rate=rate,bits=bits);break
            f.seek(n+(n&1),1)
        rows.append(row)
print(json.dumps({'count':len(rows),'format_counts':dict(collections.Counter(str((r.get('format_tag'),r.get('channels'),r.get('sample_rate'),r.get('bits'))) for r in rows)),'files':rows},indent=2))
