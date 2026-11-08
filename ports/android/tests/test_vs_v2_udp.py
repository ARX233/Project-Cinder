import os,sys,time,socket,select,struct,subprocess,tempfile,pathlib
root=pathlib.Path(__file__).resolve().parents[1]; d=pathlib.Path(tempfile.mkdtemp(prefix='vs-v2-',dir='/Volumes/CodexWork'));os.environ.update(TMPDIR=str(d),PYTHONDONTWRITEBYTECODE='1');port=47197;Z=bytes(16)
def head(k,r):return b'WV\2'+bytes([k])+r
class P:
 def __init__(self,i):
  self.i=i;self.j=i.to_bytes(16,'little');self.r=Z;self.g=0;self.race=0;self.s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.s.connect(('127.0.0.1',port))
 def send(self,k,b=b'',r=None):self.s.send(head(k,self.r if r is None else r)+b)
 def hello(self,initial=False):self.send(1,struct.pack('<I16sQQB16sB',self.i,self.j,0 if initial else self.g,0 if initial else self.race,0,b'x',0),Z if initial else None)
 def wait(self,k,check=lambda x:True,t=1):
  end=time.monotonic()+t
  while time.monotonic()<end:
   if not select.select([self.s],[],[],max(0,end-time.monotonic()))[0]:break
   x=self.s.recv(4096)
   if x[3]==k and check(x):return x
  raise AssertionError((self.i,'missing',k))
 def drain(self):
  while select.select([self.s],[],[],0)[0]:self.s.recv(4096)
 def absent(self,k,t=.15):
  end=time.monotonic()+t
  while time.monotonic()<end:
   if select.select([self.s],[],[],max(0,end-time.monotonic()))[0]:
    x=self.s.recv(4096);assert x[3]!=k,(self.i,'unexpected',k)
 def join(self):
  self.hello(True);x=self.wait(2,lambda x:x[20:36]==self.j);self.r=x[4:20];self.g=struct.unpack_from('<Q',x,36)[0]
def launch(kind,fast=False):
 if kind=='c':
  s=(root/'src/vs_host.c').read_text().replace('htons(NET_PORT)','htons(%d)'%port)
  if fast:s=s.replace('#define TIMEOUT 6.0','#define TIMEOUT 1.5').replace('#define TIMEOUT_RACING 20.0','#define TIMEOUT_RACING 1.5')
  (d/'host.c').write_text(s)
  (d/'main.c').write_text('#include "vs_host.h"\n#include <time.h>\n#include <unistd.h>\nint gk_send(int p,const void*b,int n){(void)p;(void)b;return n;}\nint gk_recv(void*b,int n,int*p){(void)b;(void)n;(void)p;return 0;}\nint main(void){if(vs_host_open(0,1))return 1;struct timespec t;while(vs_host_is_open()){clock_gettime(CLOCK_MONOTONIC,&t);vs_host_poll(t.tv_sec+t.tv_nsec*1e-9,"test");usleep(1000);}return 0;}')
  subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-I'+str(root/'src'),str(d/'host.c'),str(d/'main.c'),'-o',str(d/'host')],check=True);cmd=[str(d/'host')]
 else:
  if fast:cmd=[sys.executable,'-c',"import sys;sys.path.insert(0,sys.argv[1]);import vs_server as s;s.TIMEOUT=s.TIMEOUT_RACING=1.5;sys.argv=['server',sys.argv[2]];s.main()",str(root/'tools'),str(port)]
  else:cmd=[sys.executable,str(root/'tools/vs_server.py'),str(port)]
 p=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);time.sleep(.15);assert p.poll() is None,p.stderr.read();return p
for kind in ('c','python'):
 proc=launch(kind);ps=[P(i) for i in range(1,5)]
 try:
  for p in ps:p.join()
  room=ps[0].r;assert all(p.r==room for p in ps)
  for p in ps:p.drain()
  start=struct.pack('<QQBBB',1,42,2,13,7);ps[0].send(3,start);gs=[p.wait(4) for p in ps]
  for i,(p,g) in enumerate(zip(ps,gs)):assert struct.unpack_from('<QQ',g,20)==(2,1) and g[43]==i;p.g=2;p.race=1;p.hello()
  ps[0].send(3,start);assert ps[0].wait(4)==gs[0];time.sleep(.1)
  for p in ps:p.drain()
  payload=bytes(i%251 for i in range(0x278));wire=head(5,room)+struct.pack('<QQB',2,1,1)+payload;ps[1].s.send(wire);assert ps[0].wait(5)==wire
  for p in ps:p.drain()
  ps[2].send(5,struct.pack('<QQB',2,1,1)+payload);ps[0].absent(5)
  ps[3].send(6,ps[3].j+struct.pack('<Q',2));first=[p.wait(10) for p in ps[:3]]
  for p in ps[:3]:p.drain()
  again=[p.wait(10) for p in ps[:3]];assert all(struct.unpack_from('<QQ',x,20)==(3,1) for x in first+again)
  for p in ps[:3]:p.drain()
  ps[0].send(3,struct.pack('<QQBBB',3,43,1,10,2));ps[0].absent(4)
  ps[0].g=3;ps[0].race=0;ps[0].hello();time.sleep(.1);ps[0].drain()
  ps[0].absent(10,.6);ps[1].wait(10)
  for p in ps[:3]:p.g=3;p.race=0;p.hello()
  time.sleep(.1)
  for p in ps[:3]:p.drain()
  ps[0].send(3,struct.pack('<QQBBB',3,43,1,10,2));gs=[p.wait(4) for p in ps[:3]];assert all(struct.unpack_from('<QQ',x,20)==(4,2) for x in gs)
  for p in ps[:3]:p.g=4;p.race=2;p.hello();p.drain()
  ps[1].s.send(wire);ps[0].absent(5)
  for p in ps[:3]:p.drain()
  ps[0].send(3,start);ps[0].absent(4)
  for p in ps[:3]:p.send(12,struct.pack('<QQ',4,2))
  for p in ps[:3]:p.wait(2,lambda x:struct.unpack_from('<QQ',x,36)==(5,0))
  for p in ps[:3]:p.g=5;p.race=0;p.hello()
  ps[0].send(6,ps[0].j+struct.pack('<Q',5))
  for p in ps[1:3]:p.wait(9)
  proc.wait(timeout=2);proc=launch(kind);fresh=P(1);fresh.join();assert fresh.r!=room
  fresh.send(6,fresh.j+struct.pack('<Q',1),room);time.sleep(.1);fresh.drain();fresh.hello();fresh.wait(2)
  fresh.send(3,start,room);fresh.absent(4);fresh.s.close()
  print(kind,'PASS',flush=True)
 finally:
  if proc.poll() is None:proc.terminate()
  proc.wait(timeout=3)
  for p in ps:p.s.close()
for kind in ('c','python'):
 proc=launch(kind,True); ps=[P(i) for i in range(1,4)]; new=None
 try:
  for p in ps:p.join()
  for p in ps:p.drain()
  ps[0].send(3,struct.pack('<QQBBB',1,44,1,13,0));[p.wait(4) for p in ps]
  for p in ps:p.g=2;p.race=1;p.hello();p.drain()
  end=time.monotonic()+1.8
  while time.monotonic()<end:
   for p in ps[:2]:p.hello()
   time.sleep(.2)
  for p in ps[:2]:p.wait(10,lambda x:struct.unpack_from('<QQ',x,20)==(3,1))
  for p in ps[:2]:p.g=3;p.race=0;p.hello();p.drain()
  time.sleep(.1);ps[2].drain();ps[2].hello(True);ps[2].absent(2,.2)
  new=P(3);new.j=(99).to_bytes(16,'little');new.join();assert new.g==3
  end=time.monotonic()+1.8
  while time.monotonic()<end and proc.poll() is None:
   try:ps[1].hello();new.hello()
   except ConnectionRefusedError:break
   time.sleep(.2)
  ps[1].wait(9);new.wait(9);proc.wait(timeout=2)
  print(kind,'PASS shortened timeout, stale join rejection, new nonce rejoin, owner timeout',flush=True)
 finally:
  if proc.poll() is None:proc.terminate()
  proc.wait(timeout=3)
  for p in ps:p.s.close()
  if new:new.s.close()
for kind in ('c','python'):
 proc=launch(kind); ps=[P(i) for i in range(1,4)]
 try:
  for p in ps:p.join()
  for p in ps:p.drain()
  ps[0].send(3,struct.pack('<QQBBB',1,50,1,13,0)); [p.wait(4) for p in ps]
  for p in ps:p.g=2;p.race=1;p.hello();p.drain()
  ps[2].send(12,struct.pack('<QQ',2,1));ps[0].send(3,struct.pack('<QQBBB',2,51,2,13,0));ps[0].absent(4)
  ps[2].send(6,ps[2].j+struct.pack('<Q',2))
  for p in ps[:2]:p.wait(10,lambda x:struct.unpack_from('<QQ',x,20)==(3,1))
  print(kind,'PASS done-member departure while race active aborts',flush=True)
 finally:
  if proc.poll() is None:proc.terminate()
  proc.wait(timeout=3)
  for p in ps:p.s.close()
for kind in ('c','python'):
 proc=launch(kind); ps=[P(i) for i in range(1,5)]
 try:
  ps[0].join();ps[1].join();ps[2].hello(True)
  ps[0].wait(2,lambda x:x[61]==3); ps[2].drain()
  ps[0].send(3,struct.pack('<QQBBB',1,61,1,13,0))
  active=ps[0].wait(2,lambda x:x[60]==1)
  assert struct.unpack_from('<QQ',active,36)==(2,1)
  go=ps[0].wait(4);ps[1].wait(4);ps[2].drain()
  ps[2].hello(True);retry_lobby=ps[2].wait(2,lambda x:x[60]==1)
  assert retry_lobby[20:36]==ps[2].j and struct.unpack_from('<QQ',retry_lobby,36)==(2,1)
  retry_go=ps[2].wait(4);assert ps[2].wait(4, t=1)==retry_go
  ps[3].hello(True);ps[3].absent(2,.15)
  ps[0].send(3,struct.pack('<QQBBB',1,61,1,13,0));assert ps[0].wait(4)==go
  ps[2].drain();ps[1].send(6,ps[1].j+struct.pack('<Q',1))
  lost=ps[2].wait(2,lambda x:x[60]==2)
  assert lost[20:36]==ps[2].j and struct.unpack_from('<QQQ',lost,36)==(3,0,1)
  ps[2].wait(10,lambda x:struct.unpack_from('<QQ',x,20)==(3,1))
  for p in (ps[0],ps[2]):p.r=lost[4:20];p.g=3;p.race=0;p.hello()
  time.sleep(.1);ps[3].hello(True)
  new=ps[3].wait(2,lambda x:x[20:36]==ps[3].j)
  assert new[60]==0 and struct.unpack_from('<QQQ',new,36)==(3,0,1)
  print(kind,'PASS lost admission/GO, phase-2 debt, no active join, new join phase-0',flush=True)
 finally:
  if proc.poll() is None:proc.terminate()
  proc.wait(timeout=3)
  for p in ps:p.s.close()
print('build:',d)
