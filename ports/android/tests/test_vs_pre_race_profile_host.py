#!/usr/bin/env python3
"""Exercise production profile, acknowledgement and race-tune snippets on host."""
from pathlib import Path
import os, subprocess, tempfile
src=Path(__file__).resolve().parents[1]/"src"
s=(src/"app.c").read_text()
profile_start=s.index("static void vs_profile(")
profile=s[profile_start:s.index("#ifdef __ANDROID__\n/* Optional WV1 profile extension.",profile_start)]
own_start=s.index("static int vs_own_profile_matches(")
profile+=s[own_start:s.index("#endif",own_start)]
start=s.index("    const cardb_color *col = chosen_color();", s.index("  if (go) {"))
end=s.index("    /* a race chosen before the course finished loading",start)
race=s[start:end]
assert "vs_own_lobby_ready(l, m)" in s
assert "vs_own_profile_matches(&go.player[go.pcb], expected)" in s
pre=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "car.h"
#include "menu.h"
#include "net.h"
#define __ANDROID__ 1
#define VS_PROFILE_CAR 5
#define VS_PROFILE_NAME 10
#define VS_PROFILE_DRESS 12
#define VS_PROFILE_BUILD 19
#define VS_PROFILE 21
#define VS_BUILD_NAMESPACE 'W'
#define VS_BUILD_REVISION 168
typedef struct { int type,gears,pack; } cardb_color;
static const cardb_color color={13,6,0};
static const unsigned char CARDB_TYRES[1][7]={{1,2,3,4,5,6,7}};
static struct { menu_state menu; unsigned int vs_id; } G;
static int base_power=24,base_handling=10,status;
static const cardb_color *chosen_color(void) { return &color; }
void menu_tune(const menu_state *m,int *p,int *h) { (void)m; *p=base_power; *h=base_handling; }
void menu_story_tune(const menu_state *m,int *p,int *h) { menu_tune(m,p,h); }
int menu_title(const menu_state *m) { (void)m; return 0; }
int menu_vs_status(const menu_state *m) { (void)m; return status; }
'''
post=r'''
static car_spec race(int vs) {
'''+race+r'''
return spec;
}
int main(void) {
 G.vs_id=123; G.menu.game=MENU_GAME_VS; G.menu.maker=0; G.menu.car=0;
 assert(pre_race_tune_begin(&G.menu.pre_tune,MENU_GAME_VS,0,0,24,10));
 assert(pre_race_tune_step(&G.menu.pre_tune,-1)); assert(pre_race_tune_confirm(&G.menu.pre_tune));
 unsigned char p[VS_PROFILE]; vs_profile(p); assert(p[3]==23 && p[4]==11);
 car_spec spec=race(1); assert(spec.power==p[3] && spec.handling==p[4]);
 net_lobby l={0}; l.connected=1; l.n=1; l.me=0; l.player[0].id=G.vs_id;
 assert(!vs_own_lobby_ready(&l,&G.menu)); l.player[0].profile_len=VS_PROFILE;
 memcpy(l.player[0].profile,p,VS_PROFILE); status=7;
 assert(!vs_own_lobby_ready(&l,&G.menu)); l.player[0].status=7;
 assert(vs_own_lobby_ready(&l,&G.menu));
 assert(vs_own_profile_matches(&l.player[0],p)); l.player[0].profile[3]++;
 assert(!vs_own_profile_matches(&l.player[0],p)); assert(!vs_own_lobby_ready(&l,&G.menu));
 l.player[0].profile[3]--; l.player[0].id++; assert(!vs_own_lobby_ready(&l,&G.menu));
 assert(G.menu.tune_power[0][0]==0); puts("VS profile/race/echo tests passed");
}
'''
with tempfile.TemporaryDirectory(prefix="vs-tune-profile-") as t:
 c=Path(t)/"fixture.c"; exe=Path(t)/"fixture"; c.write_text(pre+profile+post)
 subprocess.run([os.environ.get("CC","cc"),"-std=c11","-Wall","-Wextra","-Werror","-DWMMT_PRE_RACE_TEST","-I",str(src),str(c),str(src/"pre_race_tune.c"),"-o",str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
