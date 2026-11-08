#!/usr/bin/env python3
"""Add only the reviewed default-AI tire argument handoff to a pinned private v6.
No target execution, formula/RNG changes, installation or overwriting. The generated
translation remains private; supply a NEW output path and existing parent folder.
"""
import argparse,hashlib,json,os,stat
from pathlib import Path
BASE_SHA='f61ac21dc2b1e36dd43da1287e578abd1f370fd0dbb67e52a2a40a0e48896959'
V7_SHA='736832db465d9e79d3423e42b76454d90a729019a87fa3a382d8a7281310e719'
ANCHOR=b'  RC_T(0x898f18du); esp -= 4; W32(esp, 0x898f192u);'
HOOK=b'  rc_cpu.ebp = ebp; rc_cpu.esp = esp; rc_hook(0x898f18du);\n'
OLD_MARKER=b'const volatile uint32_t rc_ghost_native_bridge = 0x47485331u;\n'
MARKER=b'const volatile uint32_t rc_ghost_default_native_bridge = 0x47444431u;\n'
def digest(b):return hashlib.sha256(b).hexdigest()
def identity(s):return (s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def read_baseline(path):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode)or before.st_size!=17966082:raise ValueError('wrong baseline shape')
  chunks=[];left=before.st_size
  while left:
   b=os.read(fd,min(left,65536))
   if not b:raise ValueError('short baseline read')
   chunks.append(b);left-=len(b)
  if identity(before)!=identity(os.fstat(fd)):raise ValueError('baseline changed while reading')
  data=b''.join(chunks)
  if digest(data)!=BASE_SHA:raise ValueError('baseline differs from reviewed v6')
  return data
 finally:os.close(fd)
def write_new(path,data):
 # User selects an output, but it must be a fresh regular file in an existing
 # resolved parent. Never replace any baseline, engine, previous output or link.
 parent=path.parent.resolve(strict=True);target=parent/path.name
 fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  with os.fdopen(fd,'wb',closefd=False)as stream:stream.write(data);stream.flush();os.fsync(fd)
 finally:os.close(fd)
 return target
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 old=read_baseline(a.baseline)
 if old.count(ANCHOR)!=1 or old.count(OLD_MARKER)!=1 or HOOK in old or MARKER in old:raise ValueError('native hook/marker context is not unique')
 new=old.replace(ANCHOR,HOOK+ANCHOR).replace(OLD_MARKER,OLD_MARKER+MARKER)
 if new.replace(HOOK,b'').replace(MARKER,b'')!=old or digest(new)!=V7_SHA:raise ValueError('unexpected changes outside two reviewed additions')
 output=write_new(a.output,new)
 if read_baseline(a.baseline)!=old:raise ValueError('baseline changed during publication; output retained for investigation')
 print(json.dumps({'baseline_sha256':BASE_SHA,'output':str(output),'output_sha256':V7_SHA,'bytes':len(new),'physics_or_rng_formula_changes':False,'only_additions':['pre-GetSettingPt tire handoff 0x898f18d','default-only capability marker 0x47444431'],'original_unchanged':True},sort_keys=True))
if __name__=='__main__':main()
