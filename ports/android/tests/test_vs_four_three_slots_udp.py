"""Loopback slot compaction; four stored contexts, fake clock and UI."""
import os, subprocess, tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1]
class Checked(str):
 def replace(self, old, new, count=-1):
  assert old in self, f"fixture transformation anchor missing: {old!r}"
  return Checked(super().replace(old,new,count))
s=Checked((R/'tests/test_vs_four_to_three_udp.py').read_text())
s=s.replace('ROOT=Path(__file__).resolve().parents[1]', 'ROOT=Path('+repr(str(R))+')')
s=s.replace('int host_normal(void){if(H.n!=3 || H.owner!=101 || H.p[0].id!=101 || H.p[1].id!=102 || H.p[2].id!=103)return 0;', 'int host_normal(void){if(H.n!=3 || H.owner!=101 || H.p[0].id!=101 || H.p[1].id!=EXPECTED1 || H.p[2].id!=EXPECTED2)return 0;')
s=s.replace('HOST=f.HOST+r"""','HOST=f.HOST+"#define EXPECTED1 %d\\n#define EXPECTED2 %d\\n" % tuple(101+i for i in range(1,4) if i!=DEAD)+r"""')
s=s.replace('profile=f.support.block', 'DEAD=int(os.environ["DROP_SLOT"])\nprofile=f.support.block')
s=s.replace('double deadline(int i)', '''int client_fd(int i){load(i);int fd=N.fd;save(i);return fd;}
void check_go(int i,int dead,int count){load(i);assert(G.vs_go.n==count);int k=0;for(int j=0;j<4;j++){if(count==3&&j==dead)continue;vs_recovery_wire_extension e;assert(G.vs_go.player[k].id==101u+(unsigned)j);assert(vs_recovery_wire_decode(&e,G.vs_go.player[k].profile,G.vs_go.player[k].profile_len));assert(e.nonce==1001u+(unsigned)j&&e.seq>0);assert(VR.peer_nonce[k]==e.nonce&&VR.peer_seq[k]==e.seq);if(i==j)assert(G.vs_go.pcb==k);k++;}assert(k==count);save(i);}
void check_lobby(int i,int dead){load(i);const net_lobby*l=net_lobby_valid_now();assert(net_lobby_current_valid()&&l->connected&&l->n==3&&l->host==0);int k=0;for(int j=0;j<4;j++){if(j==dead)continue;assert(l->player[k].id==101u+(unsigned)j);if(i==j)assert(l->me==k);k++;}save(i);}
double deadline(int i)''')
s=s.replace('MAIN=r"""', 'MAIN="#define DEAD %d\\n" % DEAD+r"""')
s=s.replace('double deadline(int);','double deadline(int);void check_go(int,int,int),check_lobby(int,int);')
s=s.replace('for(int i=0;i<n;i++)client_poll(i,t,status);','for(int i=0;i<4;i++)if(n==4||i!=DEAD)client_poll(i,t,status);')
s=s.replace('assert(client_begin(i));}', 'assert(client_begin(i));check_go(i,-1,4);}')
s=s.replace('client_lobby(0)==3&&client_lobby(1)==3&&client_lobby(2)==3', '(DEAD==1||client_lobby(1)==3)&&(DEAD==2||client_lobby(2)==3)&&(DEAD==3||client_lobby(3)==3)&&client_lobby(0)==3')
s=s.replace('serial[3];for(int i=0;i<3;i++){assert(client_lobby(i)==3);', 'serial[4]={0};for(int i=0;i<4;i++)if(i!=DEAD){check_lobby(i,DEAD);assert(client_lobby(i)==3);')
s=s.replace('for(int i=0;i<3;i++)', 'for(int i=0;i<4;i++)if(i!=DEAD)')
s=s.replace('for(int i=1;i<3;i++)', 'for(int i=1;i<4;i++)if(i!=DEAD)')
s=s.replace('if(i!=DEAD){vs_recovery_wire_extension e;if(!vs_recovery_wire_decode(&e,H.p[i]', '{vs_recovery_wire_extension e;if(!vs_recovery_wire_decode(&e,H.p[i]').replace('for(int i=0;i<4;i++){vs_recovery_wire_extension e;if(!vs_recovery_wire_decode(&e,H.p[i]', 'for(int i=0;i<3;i++){vs_recovery_wire_extension e;if(!vs_recovery_wire_decode(&e,H.p[i]')
s=s.replace('assert(got);}', 'assert(got);check_go(i,DEAD,3);assert(client_fd(i)==fds[i]);}')
s=s.replace('double deadline(int);void check_go', 'double deadline(int);int client_fd(int);void check_go')
s=s.replace('for(int i=0;i<4;i++)client_open(i,port);', 'int fds[4];for(int i=0;i<4;i++){client_open(i,port);fds[i]=client_fd(i);assert(fds[i]>=0);}')
s=s.replace('101, 102 and 103 remain; 104 timed out.', 'the chosen guest timed out.')
s=s.replace('printf("PASS 4->3 race', 'printf("PASS 4->3 race')
with tempfile.TemporaryDirectory() as t:
 p=Path(t)/'run.py';p.write_text(s)
 for slot in (1,2,3):
  print('TEST DROPPED SLOT',slot,flush=True)
  subprocess.run(['python3',str(p)],env={**os.environ,'DROP_SLOT':str(slot),'PYTHONDONTWRITEBYTECODE':'1'},check=True,timeout=55)
