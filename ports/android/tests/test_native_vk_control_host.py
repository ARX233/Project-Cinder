#!/usr/bin/env python3
"""Stable actual native control APIs + actual app readiness setters, no GL context.
Actual shared main flush/wait is executed with mocked Vulkan/replay boundaries.
Loader flush is an explicitly mocked boundary (actual helper covered by mip/image
suites). UBSan only; no GPU/fence execution, general recovery or TSan claim.
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
OUT = Path(os.environ.get('CINDER_TEST_OUT', os.environ.get('TMPDIR', tempfile.gettempdir()))).resolve() / 'round6-control'
OUT.mkdir(parents=True, exist_ok=True)
BASELINE = Path(os.environ.get('CINDER_APP_BASELINE', str(ROOT.parent / 'round6-baseline/src/app.c'))).resolve()
INPUTS = {name: (ROOT / name).read_bytes() for name in (
    'tests/test_native_vk_control_host.py', 'src/vkgl.c', 'src/native_vk.inc',
    'src/native_vk_resources.inc', 'src/native_vk.h', 'src/app.c')}
CORE = INPUTS['src/vkgl.c'].decode()
NATIVE = INPUTS['src/native_vk.inc'].decode()
RESOURCE = INPUTS['src/native_vk_resources.inc'].decode()
APP = INPUTS['src/app.c'].decode()
BASE_BYTES = BASELINE.read_bytes()
BASE = BASE_BYTES.decode()


def fun(source, anchor):
    a = source.index(anchor)
    b = source.index('{', a)
    mask = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: ' ' * len(m.group()), source, flags=re.S)
    depth = 0
    for i in range(b, len(source)):
        depth += (mask[i] == '{') - (mask[i] == '}')
        if not depth:
            return source[a:i+1] + '\n'
    raise AssertionError(anchor)


SETTER_ANCHORS = ('static void pack_set(int k, int state) {', 'static void paint_set(int k, int state) {',
                  'static void track_set(int state) {', 'static void start_set(int course1) {')
setters = ''.join(fun(APP, anchor) for anchor in SETTER_ANCHORS)
base_setters = ''.join(fun(BASE, anchor) for anchor in SETTER_ANCHORS)
controls = ''.join(fun(CORE, anchor) for anchor in (
    'static void flush(int final, int present)', 'static void flush_wait(void)',
    'int cinder_vk_flush(void)', 'int cinder_vk_finish(void)', 'int cinder_vk_error_pending(void)'))
epoch = fun(NATIVE, 'static int native_reject(void)') + fun(NATIVE, 'uint64_t cinder_vk_error_epoch(void)')
stream = ('static __thread cinder_vk_upload_stream native_upload_stream;\n' +
          fun(RESOURCE, 'int cinder_vk_upload_stream_set(') + fun(RESOURCE, 'cinder_vk_upload_stream cinder_vk_upload_stream_get('))
assert re.search(r'static _Atomic int native_loader_failed\s*;', CORE)
assert not re.search(r'\b(?:ctx|cur_up|set_err|glFinish|glFlush|glGetError)\s*\(', controls + epoch + stream)

prefix = r'''
#include <assert.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "native_vk.h"
#define H(T,x) ((T)(uintptr_t)(x))
static uint64_t native_reject_count;
static _Atomic int native_loader_failed;
static struct {VkDevice dev;uint64_t serial,done;}D;
typedef struct {size_t i,n;VkDeviceSize used;}ring;
typedef struct {VkCommandBuffer cmd;VkCommandPool pool;ring stage;int open;}uploader;
static struct frame {uploader up;VkCommandBuffer cmd;VkCommandPool pool;VkFence fence;VkSemaphore acquire,render_done;int submitted;}frame,*F;
static struct {int acquired,headless;}S;
static int S_waited;
static int platform_native_profile; /* actual shared main fatal-policy selector */
static VkSemaphore backend_render_semaphore(void){assert(F);return F->render_done;} /* present=0 here; actual WSI selector covered by platform fixture */
static size_t n_ops,n_items,n_vb;
static unsigned legacy_error,loader_calls,loader_fault,pending_loader,close_calls,replay_calls,submit_calls,wait_calls,fence_resets,pool_resets,ring_resets;
static char calls[256];static size_t n_calls;
static void call(char c){assert(n_calls+1<sizeof calls);calls[n_calls++]=c;calls[n_calls]=0;}
static void close_pass(void){++close_calls;call('C');}
static void replay(VkCommandBuffer cmd,int final){assert(F&&cmd==F->cmd&&!final);++replay_calls;call('R');}
static VkResult fake_begin(VkCommandBuffer cmd,const VkCommandBufferBeginInfo*b){assert(cmd==F->cmd&&b->flags==VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT);call('B');return VK_SUCCESS;}
static VkResult fake_end(VkCommandBuffer cmd){assert(cmd==F->cmd||cmd==F->up.cmd);call(cmd==F->cmd?'E':'U');return VK_SUCCESS;}
static VkResult submit(VkCommandBuffer*cmd,uint32_t n,VkSemaphore wait,VkSemaphore signal,VkFence fence){assert(F&&n>=1&&n<=2&&cmd[n-1]==F->cmd&&fence==F->fence&&!signal);if(n==2)assert(cmd[0]==F->up.cmd);assert(wait==(S.acquired&&!S.headless?F->acquire:VK_NULL_HANDLE));++submit_calls;call('S');return VK_SUCCESS;}
static VkResult fake_wait(VkDevice dev,uint32_t n,const VkFence*f,VkBool32 all,uint64_t timeout){assert(dev==D.dev&&n==1&&*f==F->fence&&all&&timeout==UINT64_MAX);++wait_calls;call('W');return VK_SUCCESS;}
static VkResult fake_reset_fence(VkDevice dev,uint32_t n,const VkFence*f){assert(dev==D.dev&&n==1&&*f==F->fence);++fence_resets;call('F');return VK_SUCCESS;}
static VkResult fake_reset_pool(VkDevice dev,VkCommandPool pool,VkCommandPoolResetFlags flags){assert(dev==D.dev&&!flags&&(pool==F->pool||pool==F->up.pool));++pool_resets;call(pool==F->pool?'M':'P');return VK_SUCCESS;}
static void ring_reset(ring*r){assert(r==&F->up.stage);r->i=0;r->used=0;++ring_resets;call('Z');}
static void loader_flush(void){++loader_calls;call('L');if(loader_fault)native_loader_failed=1;else pending_loader=0;}
#define vkBeginCommandBuffer fake_begin
#define vkEndCommandBuffer fake_end
#define vkWaitForFences fake_wait
#define vkResetFences fake_reset_fence
#define vkResetCommandPool fake_reset_pool
#define VKCHECK(x) do{VkResult result_=(x);assert(result_==VK_SUCCESS);}while(0)
#define PLATFORM_CHECK(x) VKCHECK(x)
#pragma GCC poison ctx cur_up set_err glFinish glFlush glGetError glReadPixels vkgl_glFinish vkgl_glFlush
'''
control_tests = r'''
static void reset(void){
 memset(&frame,0,sizeof frame);F=&frame;D.dev=H(VkDevice,1);D.serial=31;D.done=2;frame.cmd=H(VkCommandBuffer,2);frame.pool=H(VkCommandPool,3);frame.fence=H(VkFence,4);frame.up.cmd=H(VkCommandBuffer,5);frame.up.pool=H(VkCommandPool,6);frame.acquire=H(VkSemaphore,7);frame.render_done=H(VkSemaphore,8);frame.up.stage=(ring){2,3,99};
 S.acquired=S.headless=S_waited=0;n_ops=3;n_items=7;n_vb=11;native_reject_count=0;native_loader_failed=0;loader_calls=loader_fault=pending_loader=close_calls=replay_calls=submit_calls=wait_calls=fence_resets=pool_resets=ring_resets=0;n_calls=0;calls[0]=0;legacy_error=0x0502;assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_FRAME));
}
static void main_controls(void){
 reset();frame.up.open=1;uint64_t before=cinder_vk_error_epoch();assert(cinder_vk_flush()&&!n_calls&&!submit_calls&&frame.up.open&&n_ops==3&&n_items==7&&n_vb==11&&frame.up.stage.i==2&&frame.up.stage.used==99&&cinder_vk_error_epoch()==before&&legacy_error==0x0502);
 assert(cinder_vk_finish()&&!strcmp(calls,"CUBRESWFMPZ")&&close_calls==1&&replay_calls==1&&submit_calls==1&&wait_calls==1&&fence_resets==1&&pool_resets==2&&ring_resets==1&&!frame.up.open&&!frame.submitted&&!n_ops&&!n_items&&!n_vb&&!frame.up.stage.i&&!frame.up.stage.used&&frame.up.stage.n==3&&D.done==30&&!cinder_vk_error_pending()&&legacy_error==0x0502);
 reset();S.acquired=1;assert(cinder_vk_finish()&&!strcmp(calls,"CBRESWFMPZ")&&S_waited&&D.done==30);reset();D.done=40;assert(cinder_vk_finish()&&D.done==40);reset();
 puts("PASS actual main flush defers unchanged queues; finish executes actual shared flush+wait order, closes pass/submits upload before replay, resets fences/pools/stage and advances done serial without GL/context/error state");
}
static void loader_controls(void){
 for(int finish=0;finish<2;++finish){reset();F=NULL;assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));pending_loader=1;assert((finish?cinder_vk_finish():cinder_vk_flush())&&loader_calls==1&&!pending_loader&&!strcmp(calls,"L")&&!submit_calls&&!wait_calls&&!cinder_vk_error_pending()&&!cinder_vk_error_epoch()&&legacy_error==0x0502);
 reset();F=NULL;assert(cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER));pending_loader=1;loader_fault=1;assert(!(finish?cinder_vk_finish():cinder_vk_flush())&&loader_calls==1&&pending_loader&&native_loader_failed&&cinder_vk_error_pending()&&!cinder_vk_error_epoch());assert(!(finish?cinder_vk_finish():cinder_vk_flush())&&loader_calls==1&&cinder_vk_error_epoch()==1&&legacy_error==0x0502);}
 reset();puts("PASS explicit LOADER works without main F and delegates shared loader boundary; failed boundary leaves pending+poison visible, subsequent control rejects; no mock GPU/fence execution claim");
}
static void invalid_controls(void){
 for(int finish=0;finish<2;++finish)for(int fault=0;fault<5;++fault){reset();switch(fault){case 0:D.dev=VK_NULL_HANDLE;break;case 1:F=NULL;break;case 2:native_upload_stream=(cinder_vk_upload_stream)9;break;case 3:native_upload_stream=(cinder_vk_upload_stream)-1;break;case 4:native_loader_failed=1;break;}
 assert(!(finish?cinder_vk_finish():cinder_vk_flush())&&cinder_vk_error_epoch()==1&&!n_calls&&!loader_calls&&!submit_calls&&legacy_error==0x0502);assert(cinder_vk_error_pending()==(fault==4));}
 reset();assert(!cinder_vk_upload_stream_set((cinder_vk_upload_stream)-1)&&cinder_vk_upload_stream_get()==CINDER_VK_UPLOAD_FRAME&&cinder_vk_error_epoch()==1&&!cinder_vk_error_pending());
 uint64_t new_frame_epoch=cinder_vk_error_epoch();D.serial++;assert(cinder_vk_flush()&&cinder_vk_error_epoch()==new_frame_epoch&&!cinder_vk_error_pending()&&legacy_error==0x0502);
 reset();puts("PASS missing device/frame and invalid role increment epoch without touching legacy error or issuing work; old rejection is observational epoch only, not sticky pending, allowing a new clean-frame epoch snapshot");
}
static void*reject_worker(void*arg){uintptr_t worker=(uintptr_t)arg;assert(cinder_vk_upload_stream_get()==CINDER_VK_UPLOAD_FRAME);assert(cinder_vk_upload_stream_set(worker%2?CINDER_VK_UPLOAD_LOADER:CINDER_VK_UPLOAD_FRAME));for(unsigned i=0;i<20000;++i)assert(!native_reject());assert(cinder_vk_upload_stream_get()==(worker%2?CINDER_VK_UPLOAD_LOADER:CINDER_VK_UPLOAD_FRAME));return NULL;}
static void atomic_epoch(void){
 reset();pthread_t threads[8];for(uintptr_t i=0;i<8;++i)assert(!pthread_create(&threads[i],NULL,reject_worker,(void*)i));for(unsigned i=0;i<8;++i)assert(!pthread_join(threads[i],NULL));assert(cinder_vk_error_epoch()==160000&&!cinder_vk_error_pending()&&cinder_vk_upload_stream_get()==CINDER_VK_UPLOAD_FRAME&&legacy_error==0x0502);
 __atomic_store_n(&native_reject_count,UINT64_MAX-9,__ATOMIC_RELAXED);for(uintptr_t i=0;i<8;++i)assert(!pthread_create(&threads[i],NULL,reject_worker,(void*)i));for(unsigned i=0;i<8;++i)assert(!pthread_join(threads[i],NULL));assert(cinder_vk_error_epoch()==UINT64_MAX&&cinder_vk_error_pending()&&!native_reject()&&cinder_vk_error_epoch()==UINT64_MAX&&legacy_error==0x0502);
 reset();puts("PASS actual atomic reject/epoch: eight rejection-only threads exact count, concurrent saturation without wrap, thread-local native roles; no arbitrary command/public-state concurrency or TSan claim");
}
int main(void){main_controls();loader_controls();invalid_controls();atomic_epoch();return 0;}
'''
publisher_prefix = r'''
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct {signed char pack_state[8],paint_state[8];int track_ready,start_ready;struct{signed char pack[8],paint[8];int track,start;}pub;}facts;
static struct {signed char pack_state[8],paint_state[8];int track_ready,start_ready;struct{signed char pack[8],paint[8];int track,start;}pub;pthread_mutex_t load_mx;}G={.load_mx=PTHREAD_MUTEX_INITIALIZER};
static unsigned sync_calls,lock_calls,unlock_calls,legacy_error;static int sync_ok,locked;static facts before_sync,expected_after;
static facts snapshot(void){facts f={0};memcpy(f.pack_state,G.pack_state,8);memcpy(f.paint_state,G.paint_state,8);f.track_ready=G.track_ready;f.start_ready=G.start_ready;memcpy(f.pub.pack,G.pub.pack,8);memcpy(f.pub.paint,G.pub.paint,8);f.pub.track=G.pub.track;f.pub.start=G.pub.start;return f;}
static int sync_boundary(void){assert(!locked);facts now=snapshot();assert(!memcmp(&now,&before_sync,sizeof now));++sync_calls;assert(legacy_error==0x0502);return sync_ok;}
static int test_lock(pthread_mutex_t*m){assert(m==&G.load_mx&&!locked&&!memcmp(&G.pub,&before_sync.pub,sizeof G.pub));int result=pthread_mutex_lock(m);assert(!result);locked=1;++lock_calls;return result;}
static int test_unlock(pthread_mutex_t*m){assert(m==&G.load_mx&&locked);facts now=snapshot();assert(!memcmp(&now,&expected_after,sizeof now));locked=0;++unlock_calls;return pthread_mutex_unlock(m);}
static void mutex_available(void){assert(!pthread_mutex_trylock(&G.load_mx));assert(!pthread_mutex_unlock(&G.load_mx));}
#define pthread_mutex_lock test_lock
#define pthread_mutex_unlock test_unlock
#ifdef WMMT_NATIVE_VK
static int cinder_vk_finish(void){return sync_boundary();}
#pragma GCC poison ctx cur_up set_err glFinish glFlush glGetError vkgl_glFinish vkgl_glFlush
#else
static void glFinish(void){assert(sync_boundary());}
#endif
'''
publisher_tests = r'''
static void reset(int ok){memset(G.pack_state,0x22,sizeof G.pack_state);memset(G.paint_state,0x33,sizeof G.paint_state);G.track_ready=41;G.start_ready=43;memset(&G.pub,0x55,sizeof G.pub);sync_calls=lock_calls=unlock_calls=0;locked=0;sync_ok=ok;legacy_error=0x0502;before_sync=snapshot();}
static void invoke(int kind,int k,int state){expected_after=before_sync;switch(kind){case 0:expected_after.pack_state[k]=(signed char)state;expected_after.pub.pack[k]=(signed char)(state==1||state==-1?state:0);pack_set(k,state);break;case 1:expected_after.paint_state[k]=(signed char)state;expected_after.pub.paint[k]=(signed char)(state==1);paint_set(k,state);break;case 2:expected_after.track_ready=state;if(!state)expected_after.start_ready=0;expected_after.pub.track=state;expected_after.pub.start=expected_after.start_ready;track_set(state);break;case 3:expected_after.start_ready=state;expected_after.pub.start=state;start_set(state);break;default:assert(0);}}
static int needs_sync(int kind,int state){return kind<2?state==1:kind==2?state!=0:1;}
static void verify_success(int kind,int k,int state){
 facts want=before_sync;switch(kind){case 0:want.pack_state[k]=(signed char)state;want.pub.pack[k]=(signed char)(state==1||state==-1?state:0);break;case 1:want.paint_state[k]=(signed char)state;want.pub.paint[k]=(signed char)(state==1);break;case 2:want.track_ready=state;if(!state)want.start_ready=0;want.pub.track=state;want.pub.start=want.start_ready;break;case 3:want.start_ready=state;want.pub.start=state;break;}
 facts now=snapshot();assert(!memcmp(&now,&want,sizeof now)&&sync_calls==(unsigned)needs_sync(kind,state)&&lock_calls==1&&unlock_calls==1&&!locked&&legacy_error==0x0502);mutex_available();
}
static void golden(int kind,int k,int state){facts now=snapshot();printf("GOLD %d %d %d %u %u %u ",kind,k,state,sync_calls,lock_calls,unlock_calls);const unsigned char*p=(const unsigned char*)&now;for(size_t i=0;i<sizeof now;++i)printf("%02x",p[i]);puts("");}
int main(void){
 const int states[]={-1,0,1,2,3,7};for(int kind=0;kind<4;++kind)for(int k=0;k<8;k+=7)for(unsigned j=0;j<sizeof states/sizeof states[0];++j){int state=states[j];reset(1);invoke(kind,k,state);verify_success(kind,k,state);golden(kind,k,state);
#ifdef WMMT_NATIVE_VK
 reset(0);invoke(kind,k,state);if(needs_sync(kind,state)){facts now=snapshot();assert(!memcmp(&now,&before_sync,sizeof now)&&sync_calls==1&&!lock_calls&&!unlock_calls&&!locked&&legacy_error==0x0502);}else verify_success(kind,k,state);
#endif
 }
 puts("PASS actual four publishers: sync-before-mutation, false sync no state/pub/lock publication, successful state+pub updates and unlocked mutex; exact state0/-1/other controls");return 0;
}
'''

results = []
with tempfile.TemporaryDirectory(prefix='control-', dir=OUT) as work:
    work = Path(work)
    flags = ['-I', str(ROOT / 'src')]
    if sys.platform == 'darwin':
        flags += ['-I', '/opt/homebrew/include']
    cc = os.environ.get('CC', 'clang')
    compile_flags = [cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-missing-field-initializers',
                     '-fsanitize=undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', *flags]
    def run_fixture(name, text, defines=()):
        source = work / (name + '.c')
        source.write_text(text)
        binary = work / name
        subprocess.run([*compile_flags, *defines, str(source), '-pthread', '-o', str(binary)], check=True, timeout=120)
        result = subprocess.run([str(binary)], check=True, text=True, capture_output=True, timeout=45)
        (OUT / (name + '.log')).write_text(result.stdout + result.stderr)
        results.append({'name': name, 'exit_code': result.returncode, 'stdout': result.stdout,
                        'compiler': cc, 'defines': list(defines), 'sanitizer': 'undefined',
                        'fixture_sha256': hashlib.sha256(text.encode()).hexdigest()})
        return result.stdout
    print(run_fixture('actual-control', prefix + epoch + stream + controls + control_tests), end='')
    tokens = {}
    goldens = {}
    for mode, defines in (('gles', ()), ('vkcompat', ('-DWMMT_VK=1',)), ('native', ('-DWMMT_NATIVE_VK=1',))):
        source = work / ('setters-' + mode + '.c')
        source.write_text(setters)
        token_text = subprocess.run([cc, '-E', '-P', '-x', 'c', *defines, str(source)], check=True,
                                    text=True, capture_output=True, timeout=30).stdout
        tokens[mode] = re.findall(r'\w+|[^\s]', token_text)
        stdout = run_fixture('publishers-' + mode, publisher_prefix + setters + publisher_tests, defines)
        goldens[mode] = [line for line in stdout.splitlines() if line.startswith('GOLD ')]
    source = work / 'baseline-setters.c'
    source.write_text(base_setters)
    base_tokens = re.findall(r'\w+|[^\s]', subprocess.run([cc, '-E', '-P', '-x', 'c', str(source)],
                            check=True, text=True, capture_output=True, timeout=30).stdout)
    assert tokens['gles'] == tokens['vkcompat'] == base_tokens
    stdout = run_fixture('publishers-baseline', publisher_prefix + base_setters + publisher_tests)
    goldens['baseline'] = [line for line in stdout.splitlines() if line.startswith('GOLD ')]
    assert goldens['native'] == goldens['gles'] == goldens['vkcompat'] == goldens['baseline']
    assert len(goldens['native']) == 48
    print('PASS 48 exact successful publisher action controls agree native/GLES/VKcompat/baseline, plus 48 native false-sync/control cases; GLES/VKcompat preprocessed setter tokens exactly equal round6 baseline')

assert (ROOT / 'src/native_vk.h').read_bytes() == INPUTS['src/native_vk.h'], 'included header changed during fixture compilation'
pins = {name: hashlib.sha256(data).hexdigest() for name, data in INPUTS.items()}
report = {'status': 'pass', 'results': results, 'source_sha256': pins,
          'baseline': {'path': str(BASELINE), 'sha256': hashlib.sha256(BASE_BYTES).hexdigest()},
          'actual_subsets_sha256': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in (
              ('controls', controls), ('epoch', epoch), ('stream', stream), ('publishers', setters))},
          'legacy_token_equivalence': {'gles': True, 'vkcompat': True}, 'successful_action_controls_per_mode': 48,
          'native_false_sync_configurations': 48, 'native_guarded_failure_cases': 26,
          'native_nonsync_state_controls_with_false_sync_configured': 22,
          'authority': {'main_control': 'actual native wrappers + actual shared flush/flush_wait; Vulkan/replay boundaries mocked',
                        'loader_control': 'actual native wrappers; shared loader_flush boundary mocked (actual helper tested in image/mipmap suites)',
                        'publishers': 'actual four setter bodies; native finish and legacy glFinish are sync-result/ordering mocks',
                        'atomic': 'actual reject+epoch functions across eight rejection-only pthreads; no arbitrary public-state concurrency claim'},
          'gpu_execution': 'unknown/not executed', 'asan': 'not claimed', 'tsan': 'not claimed', 'recovery': 'not claimed'}
(OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
print('source pins', json.dumps(pins, sort_keys=True))
