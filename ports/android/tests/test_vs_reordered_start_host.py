"""Real host/net and extracted app START with fake transport and own-ready.

Not a real device, network frequency test, or a complete app execution.
"""
from pathlib import Path
import ast,subprocess,tempfile
R=Path(__file__).resolve().parents[1]
# Reuse the reviewed in-memory transport declarations without executing the other test.
tree=ast.parse((R/"tests/test_vs_host_epoch_vsday.py").read_text())
f={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ("host","main")}
s=(R/"src/app.c").read_text()
def take(marker):
 p=s.index(marker);i=s.index("{",p)+1;d=1
 while d:d+=(s[i]=="{")-(s[i]=="}");i+=1
 return s[p:i]
a=s.index("  if (m->vs.start) {",s.index("static void vs_menu(void)"));b=s.index("\n  net_go go;",a)
projection=s[s.index("      m->vs.racing[i] = pl->status"):].split("\n",1)[0]
host=f["host"]+"\nint host_status(void){return H.p[1].status;} unsigned host_seq(void){return get32(H.p[1].profile+38);}\n"
client=r"""
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "net.c"
#include "vs_host.h"
#include "vs_recovery_wire.h"
#define VS_GONE 10.0
#define MENU_VS_LOADED 70
#define MENU_VS 2
#define MENU_VS_LOBBY 2
typedef struct {int screen;struct {int state,start,area_go,racing[4],mismatch[4];} vs;} menu_state;
static struct {double vs_wait_note_until;} G;
static struct {int flag;double advertise_until;} VR;
extern int active;extern void enqueue(const void*,int,int);extern int dequeue(void*,int,int);
int gk_send(int peer,const void*b,int n){(void)peer;enqueue(b,n,active);return 0;}
int gk_recv(void*b,int n,int*peer){*peer=0;return dequeue(b,n,active);}
void car_link_deliver(int p,const unsigned char*b,int n){(void)p;(void)b;(void)n;}
static int vs_own_lobby_ready(const net_lobby*l,const menu_state*m){(void)l;(void)m;return 1;}
"""+take("static int vs_peer_cooldown(")+r"""
static int observed_abort;static void cb(const net_lobby*l,double now,void*ctx){(void)now;(void)ctx;for(int i=0;i<l->n;i++){vs_recovery_wire_extension e;if(vs_recovery_wire_decode(&e,l->player[i].profile,l->player[i].profile_len)&&e.flags==1)observed_abort++;}}
int abort_seen(void){return observed_abort;}
void owner_init(void){active=0;assert(!net_open_gk(11));net_use_strict_lobby(1);net_set_lobby_observer(cb,NULL);}
void owner_poll(double now){active=0;net_poll(now,0,"owner",NULL,0);}
int snapshot_status(void){return net_lobby_valid_now()->player[1].status;}
int current(void){return net_lobby_current_valid();}
int start_allowed(double now){menu_state state={0},*m=&state;const net_lobby*l=net_lobby_now();m->screen=MENU_VS;m->vs.state=MENU_VS_LOBBY;m->vs.start=1;for(int i=0;i<l->n;i++){const net_player*pl=&l->player[i];
"""+projection+r"""
}
"""+s[a:b]+r"""
return m->vs.area_go;}
"""
main=f["main"][:f["main"].index("int main(void)")]+r"""
#include "vs_recovery_wire.h"
void owner_init(void),owner_poll(double);int snapshot_status(void),current(void),start_allowed(double),host_status(void);unsigned host_seq(void);int abort_seen(void);
static int wireflag; static void peer(unsigned seq,int status){unsigned char b[128]={0},base[21]={0},profile[42];vs_recovery_wire_extension e={wireflag,wireflag?77:0,1002,seq};assert(vs_recovery_wire_encode(profile,sizeof profile,base,sizeof base,&e));b[0]='W';b[1]='V';b[2]=1;b[3]=1;b[4]=12;b[8]=status;memcpy(b+9,"peer",4);b[25]=42;memcpy(b+26,profile,42);enqueue(b,68,1);}
static void stage(unsigned seq,int status,double t){peer(seq,status);vs_host_poll(t,"host");owner_poll(t+.01);assert(current());printf("seq=%u status=%d -> H=%d Hseq=%u strict=%d allowed=%d\n",seq,status,host_status(),host_seq(),snapshot_status(),start_allowed(t+.01));}
int main(void){assert(!vs_host_open(0,11));assert(vs_host_enable_local());owner_init();owner_poll(1);vs_host_poll(1,"host");owner_poll(1.01);
 stage(11,0,2);stage(12,64,3);assert(host_status()==64&&snapshot_status()==64&&!start_allowed(3.01));
 stage(11,0,4);assert(host_status()==0&&host_seq()==11&&snapshot_status()==0&&!start_allowed(4.01));
 wireflag=1;stage(11,0,4.2);assert(host_status()==0&&host_seq()==11&&snapshot_status()==0&&!start_allowed(4.21)&&abort_seen()>0);wireflag=0;
 stage(13,0,5);assert(host_status()==0&&snapshot_status()==0&&start_allowed(5.01));vs_host_close();puts("reordered HELLO fake queue: PASS");return 0;}
"""
with tempfile.TemporaryDirectory(prefix="reordered-start-host-") as d:
 d=Path(d)
 for name,txt in [("host.c",host),("client.c",client),("main.c",main)]: (d/name).write_text(txt)
 subprocess.run(["cc","-std=gnu11","-Wall","-Wextra","-Werror","-Wno-unused-function","-Wno-unused-variable","-fsanitize=undefined,float-cast-overflow","-fno-sanitize-recover=all","-D__ANDROID__","-I"+str(R/"src"),str(d/"host.c"),str(d/"client.c"),str(d/"main.c"),str(R/"src/vs_recovery_wire.c"),"-o",str(d/"test")],check=True);subprocess.run([str(d/"test")],check=True)
