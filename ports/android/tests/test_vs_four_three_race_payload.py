"""Real host/Net/recovery loopback, fake clock/UI and no-op car delivery.
The original fixture does not test race payloads. No Android source is changed.
"""
import os
from pathlib import Path
p = Path(__file__).resolve().parent / 'test_vs_four_three_slots_udp.py'
code = p.read_text()
anchor = 'with tempfile.TemporaryDirectory() as t:'
assert code.count(anchor) == 1
injection = r'''
def inject(old, new):
 global s
 assert s.count(old) == 1, (old, s.count(old))
 s=s.replace(old,new,1)
inject('double deadline(int i)', r"""
void send_frame(int i){load(i);unsigned char b[CAR_LINK_PACKET];memset(b,0,sizeof b);b[0]=(unsigned char)(101+i);put32(b+PACKET_COUNT,7);net_race_send(b,sizeof b);save(i);}
int ready_frames(int i,int dead){load(i);int ok=1;for(int j=0;j<4;j++)if(j!=i&&j!=dead)ok=ok&&N.rx_any[j]&&N.rx_new[j]&&N.rx[j][0]==101+j&&N.rx_count[j]==7;save(i);return ok;}
void check_frames(int i,int dead){load(i);assert(!N.rx_any[dead]);net_race_receive();for(int j=0;j<4;j++)assert(!N.rx_new[j]);assert(N.receive_drained);save(i);}
double deadline(int i)""")
inject('double deadline(int);int client_fd', 'void send_frame(int),check_frames(int,int);int ready_frames(int,int);double deadline(int);int client_fd')
inject('unsigned long long serial[4]={0};', 'for(int i=0;i<4;i++)if(i!=DEAD)send_frame(i);int frames=0;for(int z=0;z<100&&!frames;z++){vs_host_poll(t,"host");frames=1;for(int i=0;i<4;i++)if(i!=DEAD){client_poll(i,t,1);frames=frames&&ready_frames(i,DEAD);}usleep(1000);}assert(frames);for(int i=0;i<4;i++)if(i!=DEAD)check_frames(i,DEAD);printf("PASS actual race payload 4->3 frozen PCB slot %d\\n",DEAD);unsigned long long serial[4]={0};')
'''
code = code.replace(anchor, injection + '\n' + anchor, 1)
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
exec(compile(code, str(p), 'exec'), {'__file__': str(p), '__name__': '__main__'})
