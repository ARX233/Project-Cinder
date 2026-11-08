from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[1]
source=(root/"src/app.c").read_text()
test=(root/"tests/test_vs_peer_cooldown_host.py").read_text()
projection=source[source.index("      m->vs.racing[i] = pl->status"):].split("\n",1)[0]
a=source.index("  if (m->vs.start) {",source.index("static void vs_menu(void)"));b=source.index("\n  net_go go;",a);start=source[a:b]
runner="static int run_status(int status){menu_state state={0},*m=&state; const net_lobby*l=&strict; double now=10; strict.player[1].status=status; H.p[1].status=status; m->screen=MENU_VS;m->vs.state=MENU_VS_LOBBY;m->vs.start=1;for(int i=0;i<l->n;i++){const net_player*pl=&l->player[i];"+projection+"}\n"+start+"\nreturn m->vs.area_go;}\n"
assert test.count('#define MENU_VS_LOADED 20') == 1
assert test.count('int main(void){') == 1
test=test.replace('#define MENU_VS_LOADED 20', '#define MENU_VS_LOADED 70')
test=test.replace("int main(void){",runner+"int main(void){")
needle=" setflag(1);assert(vs_host_lobby_matches(&strict));"
assert test.count(needle) == 1
insert=" setflag(0); int values[]={0,1,2,16,32,48,64,66,68,70,72,73}; for(int legacy=0;legacy<2;legacy++){if(legacy)H.p[1].profile_len=strict.player[1].profile_len=21;for(unsigned i=0;i<sizeof values/sizeof values[0];i++){int result=run_status(values[i]);printf(\"legacy=%d peer status %d: area_go=%d\\n\",legacy,values[i],result);assert(result==(values[i]==0));}} strict.player[1].status=0;H.p[1].status=0;setflag(0);\n"
test=test.replace(needle,insert+needle)
test=test.replace("R=Path(__file__).resolve().parents[1]", "R=Path("+repr(str(root))+")")
exec(compile(test,"isolated-fixture","exec"),{"__file__":str(root/"tests/test_vs_peer_cooldown_host.py")})
menu=(root/"src/menu.c").read_text();p=menu.index("int menu_vs_status(");q=menu.index("{",p)+1;d=1
while d:
 d+=(menu[q]=="{")-(menu[q]=="}");q+=1
func=menu[p:q]
fixture="""#include <assert.h>
#include <stdio.h>
#include <string.h>
#include \"menu.h\"
"""+func+"""
int main(void){menu_state m;memset(&m,0,sizeof m);m.screen=MENU_VS;m.vs.state=MENU_VS_LOBBY;assert(menu_vs_status(&m)==0);printf(\"actual menu status in lobby=0\\n\");return 0;}
"""
with tempfile.TemporaryDirectory(prefix="lobby-menu-",) as tmp:
 c=Path(tmp)/"test.c";exe=Path(tmp)/"test";c.write_text(fixture);subprocess.run(["cc","-std=c11","-I"+str(root/"src"),str(c),"-o",str(exe)],check=True);subprocess.run([str(exe)],check=True)
