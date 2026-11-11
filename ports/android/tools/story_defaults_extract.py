#!/usr/bin/env python3
"""Extract private story defaults from the exact original ELF, never into git."""
import argparse, csv, hashlib, os, re, struct
from pathlib import Path

SHA256 = "2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6"
ROOT = Path("/Volumes/CodexWork")
STORY = 0x973a5c0
COUNTS = 0x93dd760
GROUPS = 0x93dd780
PATHS = 0x931f4e0
SIGNATURES = {
 0x857d28c: bytes.fromhex("55 89 e5 57 8d 4d e8 8d 45 dc 8d bd 2c fd ff ff 56 53 81 ec dc 02 00 00 8b 55 0c c7 45 e4 04 00 00 00 c7 45 e8 00 00 00 00 8b 5d 10 85 d2 89 55 dc"),
 0x857d0a4: bytes.fromhex("55 89 e5 53 8d 9d 4c fd ff ff 81 ec c4 02 00 00 8b 45 08 89 1c 24 c7 44 24 08 58 01 00 00 69 00 58 01 00 00 05 c0 a5 73 09"),
 0x86338bc: bytes.fromhex("55 89 e5 57 56 53 83 ec 04 8b 55 08 8b 7d 0c 8b 04 95 60 d7 3d 09 85 c0 89 45 f0 0f 8e 28 01 00 00 89 d0 c1 e0 04 8d 04 90 8d 14 80 39 ba 80 d7 3d 09"),
 0x8835590: bytes.fromhex("55 89 e5 8b 55 08 8b 4d 0c 85 d2 89 c8 7e 1c 83 f9 09 7f 17 83 fa 01 74 0f 83 e2 01 b8 6e 00 00 00 75 05 83 f9 09 74 03 8d 41 64 c9 c3"),
}
class Invalid(ValueError): pass
class Elf:
 def __init__(self, data, expected_sha=SHA256):
  if hashlib.sha256(data).hexdigest() != expected_sha: raise Invalid("ELF SHA-256 mismatch")
  self.data=data
  if len(data)<52 or data[:7]!=b"\x7fELF\x01\x01\x01" or struct.unpack_from("<HH",data,16)!=(2,3): raise Invalid("not x86 ELF32 little endian executable")
  off=struct.unpack_from("<I",data,28)[0]; size,count=struct.unpack_from("<HH",data,42)
  if size!=32 or not count or off+size*count>len(data): raise Invalid("bad program headers")
  self.loads=[]
  for i in range(count):
   typ,o,va,_,fs,ms,_,_=struct.unpack_from("<8I",data,off+size*i)
   if typ==1:
    if fs>ms or o+fs>len(data) or va+ms>2**32: raise Invalid("bad PT_LOAD")
    self.loads.append((va,o,fs))
 def read(self,va,size):
  if va<0 or size<0 or va+size>2**32: raise Invalid("bad VA range")
  matches=[o+va-v for v,o,n in self.loads if v<=va and va+size<=v+n]
  if len(matches)!=1: raise Invalid("unmapped or ambiguous VA")
  return self.data[matches[0]:matches[0]+size]
 def i32(self,va): return struct.unpack("<i",self.read(va,4))[0]
 def string(self,va):
  result=bytearray()
  for i in range(512):
   b=self.read(va+i,1)
   if b==b"\0":
    try: return result.decode("ascii")
    except UnicodeDecodeError as e: raise Invalid("invalid sound path") from e
   result+=b
  raise Invalid("unterminated string")
def story_index(loop, episode):
 if loop<0 or not 0<=episode<100: raise Invalid("story index out of range")
 if loop==0 or episode>9: return episode
 return 110 if loop>1 and loop%2==0 and episode==9 else 100+episode

def parse_menu(source):
 groups=[]
 for symbol,count in [("SONG_FILE",22),("SONG_FILE_MT",25),("SONG_FILE_R",14)]:
  m=re.search(r"\b"+symbol+r"\s*\[[^]]+\]\s*=\s*\{([^}]+)\}",source,re.S)
  if not m: raise Invalid("missing menu array "+symbol)
  body=re.sub(r"/\*.*?\*/","",m.group(1),flags=re.S)
  parts=[x.strip() for x in body.split(",") if x.strip()]
  if len(parts)!=count or parts[0]!="NULL" or parts[-1]!="NULL" or any(not re.fullmatch(r'"[A-Za-z0-9_]+"',x) for x in parts[1:-1]): raise Invalid("unexpected menu array "+symbol)
  songs=[None]+[x[1:-1] for x in parts[1:-1]]+[None]
  if len(set(songs[1:-1]))!=count-2: raise Invalid("ambiguous Android filename")
  groups.append(songs)
 return groups

def extract(elf,groups):
 for va,signature in SIGNATURES.items():
  if elf.read(va,len(signature))!=signature: raise Invalid("machine-code signature mismatch")
 if [elf.i32(COUNTS+4*g) for g in range(3)]!=[22,25,14]: raise Invalid("unexpected group lengths")
 maps=[]
 for g,songs in enumerate(groups):
  ids=[elf.i32(GROUPS+100*g+4*i) for i in range(len(songs))]
  if ids[0]!=110 or ids[-1]!=-1 or len(set(ids))!=len(ids): raise Invalid("invalid group table")
  mapping={}
  for ident in ids[1:-1]:
   if not 0<=ident<110: raise Invalid("unsupported BGM ID")
   ptr=struct.unpack("<I",elf.read(PATHS+12*ident,4))[0]; path=elf.string(ptr)
   if not path.startswith("data/sound/bgm/") or not path.endswith(".wav"): raise Invalid("bad sound path")
   name=path.rsplit("/",1)[-1][:-4]; matches=[i for i,s in enumerate(songs) if s==name]
   if len(matches)!=1: raise Invalid("unmapped Android song %s group %d"%(name,g))
   mapping[ident]=matches[0]
  maps.append(mapping)
 rows=[]
 for index in range(111):
  base=STORY+index*0x158; day=elf.i32(base+0x10)
  if day not in (0,1): raise Invalid("invalid day")
  lines=[]; raw=[]; fallback=[]
  for g in range(3):
   first=elf.i32(base+0x54+4*g); second=elf.i32(base+0x54+4*(15+g)); ident=second if first==-1 else first
   if ident not in maps[g]: raise Invalid("unmapped default index %d group %d ID %d"%(index,g,ident))
   lines.append(maps[g][ident]);raw.append(ident);fallback.append(first==-1)
  rows.append((day,lines,raw,fallback))
 return rows

def check_csv(rows,path):
 with open(path,newline="",encoding="utf-8") as f: records=list(csv.DictReader(f))
 if len(records)<111: raise Invalid("CSV lacks rows")
 for i,(day,_,ids,_) in enumerate(rows):
  r=records[i]
  if int(r["original_index"])!=i or int(r["raw_day_bool"])!=day or any(int(r["default_group%d"%g])!=ids[g] for g in range(3)): raise Invalid("CSV mismatch at %d"%i)

def emit(rows):
 lines=["/* Private derived data. Never commit. */", "#ifndef ANDROID_STORY_DEFAULTS_PRIVATE_H", "#define ANDROID_STORY_DEFAULTS_PRIVATE_H", "typedef struct { unsigned char day; unsigned char bgm[3]; } story_default_row;", "static const story_default_row story_defaults_private[111] = {"]
 lines += ["  {%d, {%d, %d, %d}},"%(day,*songs) for day,songs,_,_ in rows]
 return "\n".join(lines+["};", "#endif", ""])

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument("--elf",required=True,type=Path);ap.add_argument("--menu",required=True,type=Path);ap.add_argument("--output",required=True,type=Path);ap.add_argument("--cross-check-csv",type=Path);a=ap.parse_args()
 out=a.output.resolve(); root=ROOT.resolve(strict=True)
 if not out.is_relative_to(root) or out==root: raise Invalid("output must be inside /Volumes/CodexWork")
 elf=Elf(a.elf.read_bytes());rows=extract(elf,parse_menu(a.menu.read_text(encoding="utf-8")))
 if a.cross_check_csv: check_csv(rows,a.cross_check_csv)
 fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
 with os.fdopen(fd,"w",encoding="utf-8") as f: f.write(emit(rows))
 print("validated 111 rows x 3 groups; wrote",out)
if __name__=="__main__": main()
