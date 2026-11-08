"""Real host/net and extracted loading helper; fake transport and UI, not full app."""
from pathlib import Path
import ast, subprocess, tempfile
R=Path(__file__).resolve().parents[1]
s=(R/'src/app.c').read_text()
def take(m):
 p=s.index(m);i=s.index('{',p)+1;d=1
 while d:
  d+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[p:i]+'\n'
tree=ast.parse((R/'tests/test_vs_host_epoch_vsday.py').read_text()); ns={'f':''.join(take(m) for m in ('static int vs_peer_cooldown(', 'static int vs_own_profile_matches(', 'static int vs_own_lobby_ready(', 'static int vs_same_build(', 'static void vs_day('))}
for node in tree.body:
 if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('host','main','client'):
  ns[node.targets[0].id]=eval(compile(ast.Expression(node.value),'<fixture>','eval'),ns)
host=ns['host']+'\nint host_status(void){return H.p[1].status;} int host_started(void){return H.started;} int host_accepted(void){return H.accepted;}\n'
client=ns['client'].replace('int vs_song;} G;','int vs_song; net_go vs_go; int vs_seen_loaded;} G;')
assert client.count('static __typeof__(N) saved[2];') == 1
client=client.replace('static __typeof__(N) saved[2];','static struct { unsigned capable, ready_capable; uint64_t peer_nonce[NET_PLAYERS]; } VR;\n'+take('static int vs_others_loaded(')+'\nstatic __typeof__(N) saved[2];')
client=client.replace('#define MENU_VS_LOADED 70','#define MENU_VS_LOADED 70\nextern int guest_status;')
assert client.count('i==0 ? menu_vs_status(&M) : 66') == 1
client=client.replace('i==0 ? menu_vs_status(&M) : 66','i==0 ? menu_vs_status(&M) : guest_status')
client+="""\nint check_loaded(int *match,int *current,int *status){load(0);*match=vs_host_loading_lobby_matches(net_lobby_valid_now(),G.vs_go.race);*current=net_lobby_current_valid();*status=net_lobby_valid_now()->player[1].status;int r=vs_others_loaded();save(0);return r;}\nvoid use_go(void){G.vs_go=received[0];G.vs_seen_loaded=0;}\nint seen(void){return G.vs_seen_loaded;}\n"""
main=ns['main'].replace('int active;','int active; int guest_status=66;')
assert main.count('static struct packet up[128],down[2][128],first[2];') == 1
main=main.replace('static struct packet up[128],down[2][128],first[2];','static struct packet up[128],down[2][128],first[2],old_lobby;')
assert main.count('assert(dn[id]<128);') == 1
main=main.replace('assert(dn[id]<128);','if(id==0 && n>13 && p[3]==2 && guest_status==70){old_lobby.n=n;memcpy(old_lobby.data,b,n);}\n assert(dn[id]<128);')
main=main.replace('int main(void){uint32_t','int host_status(void);int host_started(void);int host_accepted(void);int check_loaded(int*,int*,int*);void use_go(void);int seen(void);\nint main(void){uint32_t')
pos=main.index('vs_host_close();puts(')
main=main[:pos]+"""use_go(); assert(host_started()&&host_accepted());
 guest_status=70;client_poll(1,5.3);vs_host_poll(5.3,\"test\");assert(host_status()==70 && old_lobby.n);
 guest_status=1;client_poll(1,5.9);vs_host_poll(5.9,\"test\");assert(host_status()==1);dn[0]=0;down[0][dn[0]++]=old_lobby;
 client_poll(0,6.0);int match,current,status;int result=check_loaded(&match,&current,&status);
 printf(\"stale H=%d snapshot=%d loaded=%d current=%d match=%d ready=%d started=%d accepted=%d\\n\",host_status(),status,result,current,match,vs_host_control_ready(),host_started(),host_accepted());
 assert(host_status()==1&&status==70&&result==0&&!match&&seen()==0);
 use_go(); struct packet invalid=old_lobby;invalid.data[4]=0;dn[0]=0;down[0][dn[0]++]=invalid;client_poll(0,6.1);
 result=check_loaded(&match,&current,&status);
 printf("invalid H=%d snapshot=%d loaded=%d current=%d match=%d\\n",host_status(),status,result,current,match);
 assert(host_status()==1&&status==70&&result==0&&!current&&!match&&seen()==0);
 use_go();
 guest_status=70;client_poll(1,6.5);vs_host_poll(6.5,\"test\");assert(host_status()==70);dn[0]=0;
 client_poll(0,6.6);vs_host_poll(6.6,\"test\");client_poll(0,6.7);
 result=check_loaded(&match,&current,&status);
 printf(\"matching H=%d snapshot=%d loaded=%d current=%d match=%d ready=%d started=%d accepted=%d\\n\",host_status(),status,result,current,match,vs_host_control_ready(),host_started(),host_accepted());
 assert(host_status()==70&&status==70&&result==1&&match&&(seen()&2));
 use_go();dn[0]=0;down[0][dn[0]++]=invalid;client_poll(0,6.8);
 result=check_loaded(&match,&current,&status);
 printf("invalid-matching H=%d snapshot=%d loaded=%d current=%d match=%d seen=%d\\n",host_status(),status,result,current,match,seen());
 /* A matching host cannot make an invalid latest client roster a safe
   * loading boundary; do not learn a loaded latch from that snapshot. */
  assert(host_status()==70&&status==70&&result==0&&match&&!current&&seen()==0);
 """+main[pos:]
with tempfile.TemporaryDirectory(prefix='host-stale-') as tmp:
 d=Path(tmp)
 for name,text in [('host.c',host),('client.c',client),('main.c',main)]: (d/name).write_text(text)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined,float-cast-overflow','-D__ANDROID__','-I'+str(R/'src'),str(d/'host.c'),str(d/'client.c'),str(d/'main.c'),str(R/'src/vs_recovery_wire.c'),'-o',str(d/'test')],check=True,timeout=30)
 subprocess.run([str(d/'test')],check=True,timeout=10)
