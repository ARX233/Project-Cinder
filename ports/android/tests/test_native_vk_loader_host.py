#!/usr/bin/env python3
"""Actual stable native app loading/warming gates with bounded CPU mocks.
No GL context/API, actual driver, real loader thread, or GPU-fence claim. The
infinite app-loader loop is observed for one iteration using a mock condition
wait escape; subprocess deadlines catch direct-loader busy-loop regressions.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('CINDER_TEST_OUT', os.environ.get('TMPDIR', tempfile.gettempdir()))).resolve() / 'round6-control/loader-report'
OUT.mkdir(parents=True, exist_ok=True)
APP_BYTES = (ROOT / 'src/app.c').read_bytes()
APP = APP_BYTES.decode()
SELF_BYTES = Path(__file__).read_bytes()
CORE_BYTES = (ROOT / 'src/vkgl.c').read_bytes()
NATIVE_BYTES = (ROOT / 'src/native_vk.inc').read_bytes()
HEADER_BYTES = (ROOT / 'src/native_vk.h').read_bytes()


def fun(source, anchor):
    a = source.index(anchor)
    # These reviewed top-level app functions close in column zero. Raw #if/#else
    # branches can each open an alternate if-block, so raw brace counting would
    # incorrectly combine mutually exclusive braces before the C preprocessor.
    end = re.search(r'^}\s*$', source[a:], flags=re.M)
    assert end, anchor
    return source[a:a + end.end()].rstrip() + '\n'


anchors = (
    'static void pack_set(int k, int state) {', 'static void paint_set(int k, int state) {',
    'static void track_set(int state) {', 'static void start_set(int course1) {',
    'static void pack_step(int k, int ctx) {', 'static void paint_step(int k, int ctx) {',
    'static int warm_step(const load_wants *w, int ctx) {', 'static int wheel_load_step(int k) {',
    'static wpk_scene *wheel_model(int wheel) {', 'static void pack_load_now(int k, int paints) {',
    'static int load_unit(const load_wants *w, int ctx) {', 'static void load_step(double frame_start) {',
    'void app_loader(void) {')
subsets = {anchor: fun(APP, anchor) for anchor in anchors}
actual = ''.join(subsets[anchor] for anchor in anchors[:10])
actual += subsets[anchors[10]].replace('static int load_unit(', 'static int real_load_unit(', 1)
actual += subsets[anchors[11]] + subsets[anchors[12]]

prefix = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "native_vk.h"
#define NPACKS 3
#define WHEEL_SLOTS 2
#define CAR_TRAFFIC_MODELS 2
#define WARM_STEP 1
#define WARM_STEP_COURSE 1
#define WARM_MARGIN 80
#define TRACK_STEP_BYTES 131072
#define LOAD_PRE_MS 16
#define LOAD_MS 8
#define LOAD_MIN_MS 2
#define WHEEL_FREE 0
#define WHEEL_MISSING 1
#define WHEEL_UP 2
#define WHEEL_WARM 3
#define WHEEL_READY 4
typedef struct {int two_sided,skip_paints,tag;}wpk_scene;
typedef struct {int course,first,n,paints_first,hold_track,cars_before_warm;}load_wants;
static const float START[2][3]={{0,0,0},{1,2,3}};
static struct {wpk_scene packs[NPACKS],sky[1],traffic[CAR_TRAFFIC_MODELS],track,arrows[1],wheel[WHEEL_SLOTS];signed char pack_state[NPACKS],paint_state[NPACKS];int track_ready,start_ready,track_zone,rp;char data_dir[8];int load_mx,load_cv;struct{signed char pack[NPACKS],paint[NPACKS];int track,start;}pub;int wheel_state[WHEEL_SLOTS],wheel_used[WHEEL_SLOTS],wheel_tick;int load_hurry,loader_up,load_busy,load_run,load_idle,away,load_units;double load_until,load_ms;load_wants wants;}G;
static uint64_t epoch;
static int pending,pending_saturation,begin_fault,warm_fault,paint_fault,near_fault_at,near_left_at,upload_fault,upload_done,warm_left,lights_left,open_fail;
static unsigned begin_calls,warm_calls,paint_calls,near_calls,upload_calls,open_calls,finish_calls,flush_calls,finish_fail_at,flush_fail_at,slot_calls,pause_calls,unit_calls,time_calls,lock_calls,unlock_calls,broadcasts,wait_calls,stream_calls;
static int slot_result,want_result,paint_result,unit_mode,locked,stream_ok,loader_active;
static double clock_ms;
static jmp_buf loader_escape;
uint64_t cinder_vk_error_epoch(void){return epoch;}
int cinder_vk_error_pending(void){return pending;}
int cinder_vk_finish(void){++finish_calls;if(finish_calls==finish_fail_at||(pending&&!pending_saturation)){++epoch;return 0;}return 1;}
int cinder_vk_flush(void){++flush_calls;if(flush_calls==flush_fail_at){pending=1;return 0;}return !pending;}
int cinder_vk_upload_stream_set(cinder_vk_upload_stream s){++stream_calls;assert(s==CINDER_VK_UPLOAD_LOADER);return stream_ok;}
static void render_warm_begin(void){++begin_calls;if(begin_fault)++epoch;}
static const char*pack_name(int k){assert(k>=0&&k<NPACKS);return "model";}
static int wpk_open(wpk_scene*s,const char*p){assert(s&&p);++open_calls;return open_fail;}
static int wpk_upload(wpk_scene*s,size_t n){assert(s&&(n==1||n==TRACK_STEP_BYTES));assert(++upload_calls<32);if(upload_fault){++epoch;return 0;}return upload_done;}
static int wpk_upload_paints(wpk_scene*s,size_t n){return wpk_upload(s,n);}
static int wpk_warm(wpk_scene*s,int n){assert(s&&n==1);assert(++warm_calls<32);if(warm_fault)++epoch;return warm_left;}
static int wpk_warm_paints(wpk_scene*s,int n){assert(s&&n==1);assert(++paint_calls<32);if(paint_fault)++epoch;return warm_left;}
static int lights_warm(void){return lights_left;}
static int wpk_warm_near(wpk_scene*s,const float*at,int margin,int n,int*rp){assert(s&&at&&n==1&&(margin==0||margin==WARM_MARGIN));assert((margin==0)==(rp==NULL));assert(++near_calls<32);if((int)near_calls==near_fault_at)++epoch;return (int)near_calls==near_left_at?1:warm_left;}
static int wheel_slot(int wheel,const int*keep,int n){assert(wheel&&!keep&&!n);++slot_calls;return slot_result;}
static void load_pause(void){++pause_calls;}
static int want_next(const load_wants*w,int from,int to){assert(w&&!from&&to>=0);return want_result;}
static int paint_next(const load_wants*w){assert(w);return paint_result;}
static int load_unit(const load_wants*w,int context){assert(w&&(context==0||context==1));assert(++unit_calls<32);if(unit_mode==1)++epoch;if(unit_mode==2)pending=1;return unit_mode!=0;}
static double now_ms(void){assert(++time_calls<64);clock_ms+=1;return clock_ms;}
static int test_lock(int*m){assert(m==&G.load_mx&&!locked);locked=1;++lock_calls;return 0;}
static int test_unlock(int*m){assert(m==&G.load_mx&&locked);locked=0;++unlock_calls;return 0;}
static int test_broadcast(int*c){assert(c==&G.load_cv&&locked);++broadcasts;if(loader_active&&broadcasts==2)G.load_run=0;return 0;}
static int test_wait(int*c,int*m){assert(c==&G.load_cv&&m==&G.load_mx&&locked&&loader_active);++wait_calls;locked=0;longjmp(loader_escape,1);}
#define pthread_mutex_lock test_lock
#define pthread_mutex_unlock test_unlock
#define pthread_cond_broadcast test_broadcast
#define pthread_cond_wait test_wait
/* Function-like poison leaves the old parameter named ctx legal, but provides
 * no GL context declaration or usable context query. */
#define ctx(...) FORBIDDEN_NATIVE_CONTEXT_CALL
#pragma GCC poison cur_up set_err glGetError glGetIntegerv glBindFramebuffer glGenFramebuffers glGenRenderbuffers glBindRenderbuffer glRenderbufferStorage glFramebufferRenderbuffer glFinish glFlush load_fb vkgl_glFinish vkgl_glFlush GLenum GLuint GLint
'''

tests = r'''
static void reset(void){memset(&G,0,sizeof G);memcpy(G.data_dir,"assets",7);G.load_run=1;G.load_until=100;G.wants=(load_wants){.course=0,.first=0,.n=1};epoch=17;pending=pending_saturation=begin_fault=warm_fault=paint_fault=near_fault_at=near_left_at=upload_fault=warm_left=lights_left=open_fail=0;upload_done=1;begin_calls=warm_calls=paint_calls=near_calls=upload_calls=open_calls=finish_calls=flush_calls=finish_fail_at=flush_fail_at=slot_calls=pause_calls=unit_calls=time_calls=lock_calls=unlock_calls=broadcasts=wait_calls=stream_calls=0;slot_result=0;want_result=paint_result=-1;unit_mode=3;locked=loader_active=0;stream_ok=1;clock_ms=0;}
static void step_gates(void){
 for(int which=0;which<3;++which)for(int fault=0;fault<4;++fault){reset();G.pack_state[0]=G.paint_state[0]=3;G.wheel_state[0]=WHEEL_WARM;if(fault==0)begin_fault=1;if(fault==1)warm_fault=paint_fault=1;if(fault==2)pending=1;if(fault==3)warm_left=1;
 if(which==0){pack_step(0,0);assert(G.pack_state[0]==3&&!G.pub.pack[0]);}else if(which==1){paint_step(0,0);assert(G.paint_state[0]==3&&!G.pub.paint[0]);}else assert(!wheel_load_step(0)&&G.wheel_state[0]==WHEEL_WARM);assert(begin_calls==1&&!finish_calls&&!lock_calls);}
 reset();G.pack_state[0]=3;G.paint_state[0]=3;G.wheel_state[0]=WHEEL_WARM;epoch=1000;pack_step(0,0);paint_step(0,0);assert(wheel_load_step(0));assert(G.pack_state[0]==1&&G.pub.pack[0]==1&&G.paint_state[0]==1&&G.pub.paint[0]==1&&G.wheel_state[0]==WHEEL_READY&&finish_calls==2&&epoch==1000);
 reset();G.pack_state[0]=3;finish_fail_at=1;pack_step(0,0);assert(G.pack_state[0]==3&&!G.pub.pack[0]&&!lock_calls&&epoch==18);
 reset();pack_step(0,0);assert(G.pack_state[0]==2&&G.packs[0].two_sided&&G.packs[0].skip_paints);pack_step(0,0);assert(G.pack_state[0]==3);paint_step(0,0);assert(G.paint_state[0]==3);G.wheel_state[0]=WHEEL_UP;assert(!wheel_load_step(0)&&G.wheel_state[0]==WHEEL_WARM);reset();open_fail=1;pack_step(0,0);assert(G.pack_state[0]==-1&&G.pub.pack[0]==-1);
 puts("PASS actual pack/paint/wheel steps: warmBegin rejection, WPK rejection, pending and remaining work never READY; old nonsticky epoch permits success; finish0 prevents publication; CPU open/upload/missing-file controls retained");
}
static void warm_gates(void){
 for(int fault=0;fault<7;++fault){reset();if(fault==0)begin_fault=1;if(fault==1)warm_fault=1;if(fault>=2&&fault<=5)near_fault_at=fault-1;if(fault==6)pending=1;
 int left=warm_step(&G.wants,0);if(left!=1||G.start_ready||G.pub.start)fprintf(stderr,"warm rejection case %d published start=%d pub=%d near=%u\n",fault,G.start_ready,G.pub.start,near_calls);assert(left==1&&!G.start_ready&&!G.pub.start);if(fault==6)assert(!begin_calls);}
 for(int at=3;at<=4;++at){reset();near_left_at=at;assert(warm_step(&G.wants,0)==1&&G.start_ready==1&&G.pub.start==1&&finish_calls==1);}
 reset();epoch=900;assert(!warm_step(&G.wants,0)&&G.start_ready==1&&G.pub.start==1&&finish_calls==1&&begin_calls==1&&near_calls==4&&epoch==900);
 reset();warm_left=1;assert(warm_step(&G.wants,0)==1&&!G.start_ready&&!finish_calls);
 reset();finish_fail_at=1;assert(warm_step(&G.wants,0)==1&&!G.start_ready&&!G.pub.start&&epoch==18);
 reset();G.track_ready=1;begin_fault=1;assert(real_load_unit(&G.wants,0)==1&&G.track_ready==1&&!G.pub.track&&!G.start_ready);reset();G.track_ready=1;assert(!real_load_unit(&G.wants,0)&&G.track_ready==2&&G.pub.track==2&&G.start_ready==1);
 puts("PASS actual course warming: before-begin epoch snapshot, near and far WPK rejection block start publication and report remaining work; clean old epoch progresses; actual load_unit cannot promote rejected warm to track-done");
}
static void direct_loops(void){
 reset();G.wheel_state[0]=WHEEL_WARM;begin_fault=1;assert(!wheel_model(12)&&warm_calls==1&&begin_calls==1&&!G.wheel_tick);reset();G.wheel_state[0]=WHEEL_UP;upload_fault=1;assert(!wheel_model(12)&&upload_calls==1&&!begin_calls);
 reset();G.wheel_state[0]=WHEEL_WARM;pending=1;assert(!wheel_model(12)&&!warm_calls&&!begin_calls&&!upload_calls&&slot_calls==1);reset();G.wheel_state[0]=WHEEL_UP;assert(wheel_model(12)==&G.wheel[0]&&upload_calls==1&&warm_calls==1&&G.wheel_state[0]==WHEEL_READY&&G.wheel_tick==1);
 reset();G.pack_state[0]=3;finish_fail_at=1;pack_load_now(0,1);assert(G.pack_state[0]==3&&warm_calls==1&&finish_calls==1&&!paint_calls);reset();G.pack_state[0]=1;G.paint_state[0]=3;paint_fault=1;pack_load_now(0,1);assert(G.paint_state[0]==3&&paint_calls==1&&!warm_calls);
 reset();pending=1;pack_load_now(0,1);assert(pause_calls==1&&!open_calls&&!warm_calls&&!upload_calls);reset();pack_load_now(0,1);assert(G.pack_state[0]==1&&G.paint_state[0]==1&&G.pub.pack[0]==1&&G.pub.paint[0]==1&&finish_calls==2&&open_calls==1);
 puts("PASS actual wheel_model/pack_load_now stop after one rejected step or before work when pending, no infinite finish0 state loop; clean CPU/open/upload/warm path reaches readiness (bounded deadline)");
}
static void budget_loop(void){
 reset();finish_fail_at=1;load_step(0);assert(finish_calls==1&&!unit_calls&&!time_calls);reset();pending=pending_saturation=1;load_step(0);assert(!unit_calls);
 for(int mode=1;mode<=2;++mode){reset();unit_mode=mode;load_step(0);assert(unit_calls==1&&finish_calls==2);}
 reset();finish_fail_at=2;load_step(0);assert(unit_calls==1&&finish_calls==2);reset();unit_mode=0;load_step(0);assert(unit_calls==1&&finish_calls==1);reset();load_step(0);assert(unit_calls>1&&unit_calls<16&&finish_calls==unit_calls+1);
 puts("PASS actual load_step: initial finish0 or pending admits no unit; step epoch/pending/finish fault breaks after one unit; completed unit and deterministic time-budget controls terminate without GL binding/FBO reads");
}
static void loader_loop(void){
 reset();stream_ok=0;app_loader();assert(stream_calls==1&&!G.loader_up&&!unit_calls&&!lock_calls);
 for(int fault=0;fault<4;++fault){reset();loader_active=1;if(fault==0)pending=1;if(fault==1)flush_fail_at=1;if(fault==2){G.away=1;finish_fail_at=1;}if(fault==3)unit_mode=0;
 if(!setjmp(loader_escape))app_loader();assert(stream_calls==1&&G.loader_up&&wait_calls==1&&!G.load_busy&&!locked&&G.load_idle&&G.load_units==1&&!G.pub.track&&!G.pub.start);if(fault==0)assert(!unit_calls);else assert(unit_calls==1);if(fault==2)assert(finish_calls==1&&!flush_calls);else assert(flush_calls==1);}
 reset();loader_active=1;if(!setjmp(loader_escape))app_loader();assert(stream_calls==1&&unit_calls==1&&flush_calls==1&&!finish_calls&&!G.load_idle&&G.load_units==1&&!G.load_busy&&!locked);
 puts("PASS actual app_loader one-iteration control: explicit LOADER role, pending suppresses unit, flush/away-finish failure marks idle not ready, clean success accounting; condition-wait escape is a mock, not a real loader-thread/fence claim");
}
int main(void){setvbuf(stdout,NULL,_IONBF,0);step_gates();warm_gates();direct_loops();budget_loop();loader_loop();return 0;}
'''

fixture = prefix + actual + tests
with tempfile.TemporaryDirectory(prefix='loader-', dir=OUT) as work:
    work = Path(work)
    source = work / 'loader.c'
    source.write_text(fixture)
    flags = ['-I', str(ROOT / 'src')]
    if sys.platform == 'darwin':
        flags += ['-I', '/opt/homebrew/include']
    command = [os.environ.get('CC', 'clang'), '-std=gnu11', '-DWMMT_NATIVE_VK=1', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-parameter', '-fsanitize=undefined', '-fno-sanitize-recover=all', *flags,
               str(source), '-o', str(work / 'loader')]
    subprocess.run(command, check=True, timeout=120)
    result = subprocess.run([str(work / 'loader')], text=True, capture_output=True, timeout=15)
    (OUT / 'run.log').write_text(result.stdout + result.stderr)
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
    report = {'status': 'pass' if not result.returncode else 'fail', 'exit_code': result.returncode,
              'source_sha256': {'src/app.c': hashlib.sha256(APP_BYTES).hexdigest(),
                                'tests/test_native_vk_loader_host.py': hashlib.sha256(SELF_BYTES).hexdigest()},
              'actual_function_sha256': {anchor: hashlib.sha256(body.encode()).hexdigest() for anchor, body in subsets.items()},
              'fixture_sha256': hashlib.sha256(fixture.encode()).hexdigest(), 'stdout': result.stdout, 'stderr': result.stderr,
              'authority': 'actual extracted function bodies; WPK/renderer sync/epoch/native role/time and pthread wait/lock boundaries mocked',
              'limits': ['No driver/GPU/fence execution', 'No real loader thread claim', 'No ASan/TSan claim', 'No general recovery claim']}
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    result.check_returncode()

    edge_actual = (fun(NATIVE_BYTES.decode(), 'static int native_reject(void) {') +
                   fun(NATIVE_BYTES.decode(), 'uint64_t cinder_vk_error_epoch(void) {') +
                   ''.join(fun(CORE_BYTES.decode(), a) for a in (
                       'int cinder_vk_flush(void) {', 'int cinder_vk_finish(void) {', 'int cinder_vk_error_pending(void) {')))
    edge_prefix = r'''
#include <assert.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "native_vk.h"
#define H(T,x) ((T)(uintptr_t)(x))
static uint64_t native_reject_count;
static _Atomic int native_loader_failed;
static cinder_vk_upload_stream native_upload_stream;
static struct {VkDevice dev;}D;
static int frame,*F=&frame;
static unsigned loader_calls,main_calls;
static void loader_flush(void){++loader_calls;}
static void flush_wait(void){++main_calls;}
#pragma GCC poison ctx cur_up set_err glFinish glFlush glGetError
'''
    edge_tests = r'''
int main(void){D.dev=H(VkDevice,1);native_reject_count=UINT64_MAX;native_upload_stream=CINDER_VK_UPLOAD_FRAME;
 assert(cinder_vk_error_pending()&&!cinder_vk_flush()&&!cinder_vk_finish()&&!main_calls&&!loader_calls&&cinder_vk_error_epoch()==UINT64_MAX);
 native_upload_stream=CINDER_VK_UPLOAD_LOADER;F=NULL;assert(!cinder_vk_flush()&&!cinder_vk_finish()&&!loader_calls&&cinder_vk_error_epoch()==UINT64_MAX);
 F=&frame;native_upload_stream=(cinder_vk_upload_stream)-1;native_reject_count=UINT64_MAX-1;assert(!cinder_vk_finish()&&cinder_vk_error_epoch()==UINT64_MAX&&cinder_vk_error_pending());
 native_upload_stream=CINDER_VK_UPLOAD_FRAME;assert(!cinder_vk_finish()&&!main_calls);native_reject_count=123;assert(!cinder_vk_error_pending()&&cinder_vk_finish()&&main_calls==1&&cinder_vk_error_epoch()==123);
 puts("PASS actual final core controls reject saturated epoch before FRAME/LOADER work, never wrap; nonsaturated old rejection remains nonsticky");return 0;}
'''
    def extra_run(name, text, expected):
        c = work / (name + '.c')
        c.write_text(text)
        exe = work / name
        subprocess.run([*command[:-3], str(c), '-o', str(exe)], check=True, timeout=120)
        observed = subprocess.run([str(exe)], text=True, capture_output=True, timeout=15)
        (OUT / (name + '.log')).write_text(observed.stdout + observed.stderr)
        assert observed.returncode == expected, (name, observed.returncode, observed.stdout, observed.stderr)
        return {'name': name, 'exit_code': observed.returncode, 'expected_exit_code': expected,
                'fixture_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'stdout': observed.stdout, 'stderr': observed.stderr}
    extras = [extra_run('saturation-final', edge_prefix + edge_actual + edge_tests, 0)]
    print(extras[0]['stdout'], end='')
    # Controlled in-memory regressions only; no production file is rewritten.
    assert_hook = r'''
#undef assert
#define assert(x) do{if(!(x)){fprintf(stderr,"negative-control assertion: %s\n",#x);exit(77);}}while(0)
'''
    early = actual.replace('int start_candidate = !n && G.start_ready != w->course + 1;',
                           'if (!n && G.start_ready != w->course + 1 && !cinder_vk_error_pending() && cinder_vk_error_epoch() == epoch) start_set(w->course + 1);')
    early = early.replace('if (start_candidate) start_set(w->course + 1);', '/* negative control: already published early */')
    assert early != actual
    extras.append(extra_run('negative-early-start', prefix + assert_hook + early + tests, 77))
    unsaturated_guard = edge_actual.replace(' || cinder_vk_error_epoch() == UINT64_MAX', '')
    assert unsaturated_guard != edge_actual
    extras.append(extra_run('negative-missing-saturation', edge_prefix + assert_hook + unsaturated_guard + edge_tests, 77))
    print('PASS controlled regression witnesses: early start publication and missing saturation guards each fail the same host assertions (exit77); production files untouched')
    report['extra_fixtures'] = extras
    report['source_sha256'].update({'src/vkgl.c': hashlib.sha256(CORE_BYTES).hexdigest(),
                                    'src/native_vk.inc': hashlib.sha256(NATIVE_BYTES).hexdigest(),
                                    'src/native_vk.h': hashlib.sha256(HEADER_BYTES).hexdigest()})
    report['actual_core_subset_sha256'] = hashlib.sha256(edge_actual.encode()).hexdigest()
    report['regressions_detected_and_fixed_by_parent'] = [
        'Saturated error epoch previously permitted native flush/finish and main load-step work; final core+app guards reject before work',
        'Start readiness previously published before same-step far warm rejection; final candidate publication follows all warm error checks']
    assert (ROOT / 'src/native_vk.h').read_bytes() == HEADER_BYTES
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
