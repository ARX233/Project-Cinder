#!/usr/bin/env python3
"""Test extracted production network/notice boundary with a gameplay sentinel."""
from pathlib import Path
import os, re, subprocess, tempfile
s = (Path(__file__).resolve().parents[1] / "src/app.c").read_text()
f = s[s.index("void app_frame(float dt) {"):]
start = f.index("if (G.vs_race && net_is_open()) {")
guard = f.index("if (!G.vs_closed) {", start)
brace = f.index("{", guard)
masked = re.sub(r"/\*.*?\*/|//[^\n]*|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", lambda m: " "*len(m.group()), f, flags=re.S)
depth=1
for end in range(brace+1,len(f)):
    depth += (masked[end] == "{") - (masked[end] == "}")
    if not depth: break
assert depth == 0
body=f[brace+1:end]
for needle in ("hud_input_dt(&G.hud, &in, dt)", "car_reset(&G.car)", "car_set_manual(&G.car", "garage_save()", "menu_pause_update(&G.menu, dt)", "menu_finish_update(&G.menu, dt)", "timing60_race_steps(", "G.hud.shift_up += in.shift_up", "car_update(&G.car, &in)"):
    assert needle in body, needle
assert "if (G.vs_closed) vs_closed_draw();" in f[end:]
assert "if (!G.vs_closed) menu_finish_draw(&G.menu);" in f[end:]
assert "if (G.paused && !G.vs_closed)" in f[end:]
# Compile the actual result predicate and post-update CLOSED/ABORT gates.
result_end = body.index('    int goal = race->state')
# The new fifth-mode exclusion changes this predicate's prefix. The former
# rindex('if (race->over') selected the STORY fallback instead, swallowing
# unrelated StoryTail/Ghost/HUD code and even redeclaring vs_finish_ready.
result_start = body.rindex('  if (!app_ghost_mode() && race->over', 0, result_end)
result_gate = body[result_start:result_end]
assert result_gate.rstrip().endswith('{')
def braced(text, anchor):
    begin = text.index(anchor)
    left = text.index('{', begin)
    clean = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', lambda m: ' '*len(m.group()), text, flags=re.S)
    depth = 1
    for end in range(left + 1, len(text)):
        depth += (clean[end] == '{') - (clean[end] == '}')
        if not depth: return text[begin:end + 1]
    raise AssertionError(anchor)

# Bound the tick fragment to its actual physics for-block before selecting the
# existing CLOSED/ABORT -> sampling prefix; do not enlarge its mocked subsystem.
physics_for = braced(body, '  for (int i = 0; i < physics_steps; ++i) {')
tick_start = physics_for.index('    car_update(&G.car, &in);')
tick_end = physics_for.index('#ifdef __ANDROID__\n    if (G.car.race.jct_select_valid)', tick_start)
tick = physics_for[tick_start:tick_end]
finish_start = body.index('#ifdef __ANDROID__\n  int vs_finish_ready = 1;')
finish_gate = body[finish_start:result_start]
# The fallback Story goal gate is a separate exact production block. Preserve
# its legacy scenarios explicitly, without dragging HUD sounds/StoryTail in.
story_fallback = braced(body, '  if (race->over && !G.menu.finish && !movie && !G.story_end_started')
timeout_start = s.index('static int vs_remote_timed_out(double now) {')
timeout_end = s.index('\n}', timeout_start) + 2
timeout_helper = s[timeout_start:timeout_end]
gate_start = s.index('static int vs_receive_gate_check(')
gate_end = s.index('\n}', gate_start) + 2
receive_gate_helper = s[gate_start:gate_end]
block=f[start:brace+1]+"\n int executed_physics_ticks=0; ++gameplay; for (int i=0;i<requested;++i) {\n"+tick+"\n ++after_tick; } (void)executed_physics_ticks; car_race *race=&G.car.race;\n"+story_fallback+'\n'+finish_gate+result_gate+" ++saves; } } ++draws; if (G.vs_closed) ++notices;\n"
result_function='static int result_allowed(int movie, int vs_finish_ready) { car_race *race=&G.car.race;\n'+result_gate+' return 1; } return 0; }\n'
pre=r'''
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#define NET_NAME 20
#define VS_RECOVERY_READY_SIZE 47
#define VS_PROFILE 12
#define CAR_RACE_RUN 7
#define CAR_RACE_GOAL 8
#define MENU_GAME_STORY 3
#define VS_GONE 10.0
#define VS_CLOSED_NOTICE 180
typedef struct { int shift_up; } car_input;
typedef struct { int state,over; float countdown; } car_race;
static struct { int vs_race,vs_closed,paused,in_menu,story_end_started,story_end_freeze,n_ten,rival; struct { int finish,game; } menu;
 struct { int screen_w,screen_h; } hud; struct { car_race race; } car;
 float movie_len; FILE *perf; } G;
/* The original closure scenarios are legacy races, never fifth-mode Ghost. */
static int app_ghost_mode(void) { return 0; }
static int host,closed,network,polls,host_polls,silence_calls,gameplay,draws,notices,exits;
static struct { struct { int initialized; } recovery; unsigned race; } VR;
typedef struct { int connected; } lobby_state;
static lobby_state lobby;
static int finish_decision, finish_abort, track_ticks, trail_ticks, junction_resets;
#ifdef __ANDROID__
static int race_junction_ui, race_junction_barrier;
typedef struct { int waiting; double since, last; } vs_receive_gate;
static vs_receive_gate VG_finish;
/* The closure-boundary fixture assumes no sticky host abort and a drained
 * network queue; it does not validate networking or recovery internals. */
static int vs_host_loading_abort(unsigned race) { (void)race; return 0; }
static void vs_recovery_request_abort(void *r) { (void)r; }
static int net_receive_drained(void) { return 1; }
static int net_lobby_current_valid(void) { return 1; }
#endif
static void junction_ui_reset(void *p) { (void)p; ++junction_resets; }
static void junction_barrier_reset(void *p) { (void)p; ++junction_resets; }
static void player_tracks_tick(void *p) { (void)p; ++track_ticks; }
/* The dedicated tail scene fixture validates geometry; this sentinel checks
 * that a CLOSED/ABORT received within physics prevents subsequent sampling. */
static void race_tail_tick(int movie) { (void)movie; ++trail_ticks; }
static void android_story_bgm_pause(void) {}
static int vs_recovery_profile(unsigned char *p) { memset(p,0,VS_RECOVERY_READY_SIZE); return VS_RECOVERY_READY_SIZE; }
static int vs_recovery_finish_ready(void) { return finish_decision; }
static const lobby_state *net_lobby_valid_now(void) { return &lobby; }
static int requested,ticks,after_tick,saves,close_on_tick,abort_on_tick,cleared,menu_calls,story_calls,hold_calls;
static int vs_recovery_observe_now(void) { return abort_on_tick && ticks >= abort_on_tick; }
static void car_clear_junction(car_race *r) { (void)r; ++cleared; }
static int vs_abort_to_lobby(void) { return finish_abort || (abort_on_tick && ticks >= abort_on_tick); }
static void car_update(void *c,car_input *i) { (void)c;(void)i; ++ticks; if (ticks == close_on_tick) closed=1; }
static void hud_story_cutin_step(car_race *r,int hit) { (void)r;(void)hit;++story_calls; }
/* Fixed stand-in for a HUD FIFO requiring 299 ticks; no rendering or assets. */
static int hud_story_cutin_goal_hold(const car_race *r) { if (r != &G.car.race) abort(); ++hold_calls; return 299; }
static double seconds;
static int net_is_open(void) { return network; }
static int vs_host_is_open(void) { return host; }
static int net_host_closed(void) { return closed; }
static double now_ms(void) { return 123000.0; }
static double net_silence(double now) { if (now!=123.0) abort(); ++silence_calls; return seconds; }
static void vs_name(char *s,size_t n) { snprintf(s,n,"test"); }
static void vs_profile(unsigned char *p) { memset(p,0,VS_PROFILE); }
static void vs_host_poll(double t,const char *n) { (void)t;(void)n;++host_polls; }
static void net_poll(double t,int a,const char *n,const unsigned char *p,int z) { (void)t;(void)a;(void)n;(void)p;(void)z;++polls; }
static void vs_off(void) { ++exits; }
static void snd_quiet(void) {}
static void hud_init(void *p,int w,int h) { (void)p;(void)w;(void)h; }
static void menu_vs_closed(void *p,const char *s) { (void)p;(void)s; }
static void menu_frame(float dt,double start) { (void)dt;(void)start; ++menu_calls; }
'''
pre += '#ifdef __ANDROID__\n' + receive_gate_helper + '\n#endif\n' + timeout_helper + '\n' + result_function + 'static void production_frame(float dt) { double frame_start=0;\n'
post=r'''
 (void)dt; (void)movie; (void)in; (void)steps; (void)t0; }
static void reset(void) {
#ifdef __ANDROID__
 memset(&VG_finish,0,sizeof VG_finish);
#endif
 memset(&G,0,sizeof G); G.vs_race=1; G.car.race.state=CAR_RACE_RUN;
 host=closed=polls=host_polls=silence_calls=gameplay=draws=notices=exits=0;
 requested=ticks=after_tick=saves=close_on_tick=abort_on_tick=cleared=menu_calls=story_calls=hold_calls=0; network=1; seconds=0; lobby.connected=1; VR.recovery.initialized=0; finish_decision=1; finish_abort=track_ticks=trail_ticks=junction_resets=0; }
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"failed line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
int main(void) {
 reset(); closed=1; production_frame(.016f); CHECK(G.vs_closed==2 && polls==1 && gameplay==0 && draws==1 && notices==1);
 closed=0; for(int i=0;i<178;i++) production_frame(.016f);
 CHECK(G.vs_closed==180 && polls==179 && gameplay==0 && draws==179 && notices==179 && exits==0);
 production_frame(.016f); CHECK(exits==1 && G.in_menu && draws==179 && polls==180);
 reset(); seconds=10; production_frame(.016f); CHECK(!G.vs_closed && gameplay==1 && polls==1 && draws==1);
 seconds=11; production_frame(.016f); CHECK(G.vs_closed==2 && gameplay==1 && polls==2 && draws==2);
 reset(); host=1; seconds=11; G.car.race.state=CAR_RACE_GOAL; G.car.race.over=1; production_frame(.016f); CHECK(!G.vs_closed && gameplay==1 && saves==1 && host_polls==1 && silence_calls==0);
 reset(); lobby.connected=0; seconds=11; production_frame(.016f); CHECK(!G.vs_closed && silence_calls==0 && gameplay==1);
 reset(); G.vs_race=0; closed=1; production_frame(.016f); CHECK(!G.vs_closed && gameplay==1 && polls==0);
 reset(); network=0; closed=1; production_frame(.016f); CHECK(!G.vs_closed && gameplay==1 && polls==0);
 reset(); closed=1; G.paused=1; production_frame(.016f); CHECK(gameplay==0 && notices==1);
 /* Execute the shipped result predicate across all its independent gates. */
 reset(); G.car.race.over=1; CHECK(result_allowed(0, 1));
 G.car.race.over=0; CHECK(!result_allowed(0, 1)); G.car.race.over=1;
 G.menu.finish=1; CHECK(!result_allowed(0, 1)); G.menu.finish=0;
 G.vs_closed=1; CHECK(!result_allowed(0, 1)); G.vs_closed=0;
 G.story_end_freeze=1; CHECK(!result_allowed(0, 1)); G.story_end_freeze=0;
 CHECK(!result_allowed(1, 1)); CHECK(result_allowed(0, 1));
 /* A close during car_update must stop the remaining ticks and save. */
 reset(); requested=5; close_on_tick=1; G.car.race.over=1; production_frame(.016f);
 CHECK(ticks==1 && after_tick==0 && G.vs_closed==1 && cleared==1 && saves==0 && trail_ticks==0);
 production_frame(.016f); CHECK(ticks==1 && saves==0 && notices==2);
#ifdef __ANDROID__
 reset(); requested=5; abort_on_tick=1; G.car.race.over=1; production_frame(.016f);
 CHECK(ticks==1 && after_tick==0 && track_ticks==0 && trail_ticks==0 && saves==0 && menu_calls==1 && draws==0);
 reset(); G.car.race.over=1; G.car.race.state=CAR_RACE_GOAL; VR.recovery.initialized=1; finish_decision=0; production_frame(.016f); CHECK(saves==0);
 finish_decision=1; production_frame(.016f); CHECK(saves==1);
 reset(); G.car.race.over=1; VR.recovery.initialized=1; finish_decision=-1; finish_abort=1; production_frame(.016f); CHECK(saves==0 && draws==0 && menu_calls==1);
#endif
 reset(); requested=5; G.car.race.over=1; production_frame(.016f);
 CHECK(ticks==5 && after_tick==5 && saves==1);
#ifdef __ANDROID__
 CHECK(trail_ticks==5);
#endif
 reset(); G.car.race.over=1; G.story_end_freeze=1; production_frame(.016f); CHECK(saves==0);
 reset(); G.vs_race=0; G.menu.game=MENU_GAME_STORY; G.rival=0; G.car.race.over=1; G.car.race.state=CAR_RACE_GOAL;
 production_frame(.016f); CHECK(story_calls==1 && hold_calls==1 && G.story_end_freeze==299 && saves==0);
 production_frame(.016f); CHECK(story_calls==1 && hold_calls==1 && saves==0);
 puts("vs closed extracted control flow passed"); return 0; }
'''
work = Path(os.environ.get('TMPDIR', str(Path(__file__).resolve().parents[2] / 'tmp'))).resolve()
work.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=work) as t:
    c=Path(t)/"fixture.c"; exe=Path(t)/"fixture"; c.write_text(pre+block+post)
    for flags in ([], ['-D__ANDROID__']):
        subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror","-Wno-unused-function","-fsanitize=undefined","-fno-sanitize-recover=undefined",*flags,str(c),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
