"""Current source host integration only: real loopback, not APK/device/auth/settlement.

The legacy guest is a Python wire client, not an old APK or old C parser.
This test does not inject stale GO or cover cancel/reconnect timing.
"""
import ctypes, os, select, socket, struct, subprocess, sys, tempfile, time, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BOOT=r"""
import socket,runpy,sys
bind,connect=socket.socket.bind,socket.socket.connect
def safe_bind(s,a):
 assert a==('0.0.0.0',0); bind(s,('127.0.0.1',0)); print('PORT',s.getsockname()[1],flush=True)
def safe_connect(s,a):
 assert a==('10.255.255.255',1); connect(s,('127.0.0.1',9))
socket.socket.bind,socket.socket.connect=safe_bind,safe_connect
p=sys.argv[1];sys.argv=[p,'0'];runpy.run_path(p,run_name='__main__')
"""
C=r"""
#include <stdint.h>
#include "net.h"
#include "vs_recovery_wire.h"
int gk_send(int p,const void*b,int n){(void)p;(void)b;(void)n;return -1;}
int gk_recv(void*b,int n,int*p){(void)b;(void)n;(void)p;return 0;}
void car_link_deliver(int p,const unsigned char*b,int n){(void)p;(void)b;(void)n;}
static unsigned char profile[47]; static net_go g;
int init(int port){unsigned char b[21]; for(int i=0;i<21;i++)b[i]=i;
 vs_recovery_wire_extension e={0,0,0x123456789abcdef0ULL,7};
 if(!vs_recovery_wire_encode(profile,47,b,21,&e)||!vs_recovery_wire_put_ready(profile,47,1))return -2;
 if(net_open("127.0.0.1",port,101))return -1; net_require_valid_go(1);return 0;}
void poll_client(double t){net_poll(t,0,"new",profile,47);}
int players(void){return net_lobby_valid_now()->n;}
int take(void){return net_take_go(&g);} unsigned race(void){return g.race;}
int pcb(void){return g.pcb;} int count(void){return g.n;}
unsigned id(int i){return g.player[i].id;} int plen(int i){return g.player[i].profile_len;}
int pbyte(int i,int j){return g.player[i].profile[j];}
"""
M=b'WV\x01'
class Integration(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='wv1-strict-');self.addCleanup(self.tmp.cleanup)
  d=Path(self.tmp.name); (d/'shim.c').write_text(C)
  lib=d/'client.so'
  subprocess.run([os.environ.get('CC','cc'),'-std=c11','-shared','-fPIC','-I',str(ROOT/'src'),str(d/'shim.c'),str(ROOT/'src/net.c'),str(ROOT/'src/vs_recovery_wire.c'),'-o',str(lib)],check=True,capture_output=True,text=True)
  self.c=ctypes.CDLL(str(lib));self.c.poll_client.argtypes=[ctypes.c_double]
  self.proc=subprocess.Popen([sys.executable,'-u','-c',BOOT,str(ROOT/'tools/vs_server.py')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'});self.addCleanup(self.stop)
  self.assertTrue(select.select([self.proc.stdout],[],[],5)[0]);line=self.proc.stdout.readline().split();self.assertEqual(line[0],'PORT')
  self.assertEqual(self.c.init(int(line[1])),0);self.addCleanup(self.c.net_close)
  self.old=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.old.bind(('127.0.0.1',0));self.old.connect(('127.0.0.1',int(line[1])));self.old.setblocking(False);self.addCleanup(self.old.close);self.t=1.
 def stop(self):
  if self.proc.poll() is None:
   self.proc.terminate()
   try:self.proc.wait(timeout=3)
   except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=3)
  self.proc.stdout.close();self.proc.stderr.close()
 def spin(self,p):
  end=time.monotonic()+3
  while time.monotonic()<end:
   self.t+=.01;self.c.poll_client(self.t)
   if p():return
   time.sleep(.005)
  self.fail('loopback timeout')
 def get_go(self):
  while True:
   try:b=self.old.recv(4096)
   except BlockingIOError:return None
   if b[:4]==M+b'\x04':return b
 def test_two_rounds(self):
  self.c.poll_client(self.t);self.spin(lambda:self.c.players()==1)
  base=bytes(range(21));self.old.send(M+b'\x01'+struct.pack('<IB16sB',202,0,b'old',21)+base);self.spin(lambda:self.c.players()==2)
  last=0
  for _ in range(2):
   self.c.net_start(3,17,5);pkt=[None]
   def receive():
    if pkt[0] is None:pkt[0]=self.get_go()
    return pkt[0] is not None
   self.spin(receive);self.spin(lambda:bool(self.c.take()))
   rid,seed,ramp,km,n,pcb=struct.unpack_from('<IIBBBB',pkt[0],4)
   self.assertGreater(rid,last);self.assertEqual((rid,ramp,km,n,pcb),(self.c.race(),3,17,2,1));self.assertEqual((self.c.pcb(),self.c.count()),(0,2))
   self.assertEqual([self.c.id(i) for i in range(2)],[101,202]);self.assertEqual([self.c.plen(i) for i in range(2)],[47,21])
   at=16;records=[]
   for i in range(n):
    slot,pid=struct.unpack_from('<BI',pkt[0],at);length=pkt[0][at+21];data=pkt[0][at+22:at+22+length];self.assertEqual(len(data),length);at+=22+length;records.append((slot,pid,length,data))
   self.assertEqual(at+1,len(pkt[0]));self.assertEqual([(x[0],x[1],x[2]) for x in records],[(0,101,47),(1,202,21)])
   self.assertEqual(records[1][3],base);self.assertEqual(records[0][3],bytes(self.c.pbyte(0,i) for i in range(47)));self.assertEqual(records[0][3][42:],b'RDY1\x01');last=rid
   end=time.monotonic()+.1
   while time.monotonic()<end:self.get_go();self.c.poll_client(self.t);time.sleep(.005)
if __name__=='__main__':unittest.main()
