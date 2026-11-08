#!/usr/bin/env python3
"""Host-only full decode + identity verification of successful conversion results."""
import argparse, hashlib, json, pathlib, subprocess
p=argparse.ArgumentParser();p.add_argument('--work',required=True);p.add_argument('--results',required=True);a=p.parse_args();w=pathlib.Path(a.work).resolve();r=json.loads(pathlib.Path(a.results).read_text());rows=[]
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        while b:=f.read(1024*1024):h.update(b)
    return h.hexdigest()
for test in r['tests']:
    if test['status']:continue
    out=pathlib.Path(test['output']);done=subprocess.run([str(w/'proof/verify_media'),str(out)],check=True,capture_output=True,text=True);decoded=json.loads(done.stdout)
    for stream in decoded['streams']:
        if stream['codec']=='h264':
            assert stream['profile']==578 and stream['level']<=30
            assert stream['decoded_frames']==test['video_frames']==stream['declared_frames']
            assert stream['width']<=640 and stream['height']<=480
        else:assert stream['codec']=='aac' and stream['profile']==1 and stream['sample_rate']==44100 and stream['channels']==2
    rows.append({'name':test['name'],'output':str(out),'output_sha256':sha(out),'input_sha256':sha(test['source']),'audio_input_sha256':sha(test['audio']) if test['audio'] else None,'decode':decoded,'decoder_stderr':done.stderr})
path=pathlib.Path(a.results).parent/'verified.json'
with path.open('x') as f:json.dump(rows,f,indent=2);f.write('\n')
print(path)
