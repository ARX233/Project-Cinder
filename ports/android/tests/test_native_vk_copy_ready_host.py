#!/usr/bin/env python3
"""Actual shared native copy prepare/query/commit + renderer readiness predicate.
Target metadata and per-format features are controlled CPU mocks. No Vulkan
commands/driver/pixels/fences run; missing feature masks are admission stress,
not a claim that every mask describes a conformant physical device.
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
OUT = Path(os.environ.get('CINDER_TEST_OUT', os.environ.get('TMPDIR', tempfile.gettempdir()))).resolve() / 'round6-copy-ready'
OUT.mkdir(parents=True, exist_ok=True)
INPUTS = {name: (ROOT / name).read_bytes() for name in (
    'tests/test_native_vk_copy_ready_host.py', 'src/native_vk.inc', 'src/vkgl.c',
    'src/native_vk.h', 'src/render_native_post.inc')}
NATIVE = INPUTS['src/native_vk.inc'].decode()
CORE = INPUTS['src/vkgl.c'].decode()
POST = INPUTS['src/render_native_post.inc'].decode()


def fun(source, anchor):
    a = source.index(anchor)
    end = re.search(r'^}\s*$', source[a:], flags=re.M)
    assert end, anchor
    return source[a:a + end.end()].rstrip() + '\n'


def schema(name):
    end = CORE.index('} ' + name + ';') + len('} ' + name + ';')
    start = CORE.rfind('typedef struct', 0, end)
    return CORE[start:end] + '\n'


anchors = ('static int native_reject(void) {', 'uint64_t cinder_vk_error_epoch(void) {',
           'int cinder_vk_target_info(uint32_t id, cinder_vk_target_desc *out) {',
           'static int native_copy_rect_valid(', 'static int native_color_blit_format(',
           'static int native_copy_prepare(', 'int cinder_vk_copy_ready(', 'int cinder_vk_copy(')
parts = {anchor: fun(NATIVE, anchor) for anchor in anchors}
front = fun(POST, 'static int native_hq_copy_ready(void) {')
assert 'cinder_vk_copy_ready(' in front, 'renderer readiness update has not landed'
assert not re.search(r'\b(?:F|native_reject|ctx|set_err)\b', parts['static int native_copy_prepare('])
actual = ''.join(parts.values())

prefix = r'''
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "native_vk.h"
typedef struct {VkFormat fmt;int samples;VkImageUsageFlags usage;uint64_t serial;}vimg;
'''
state = r'''
enum {OP_PASS,OP_BLIT};
static struct {uint64_t serial;}D;
static int frame,*F;
static uint64_t native_reject_count,native_copy_count,compat_draw_count;
static unsigned legacy_error;
static vimg image[8],SCREEN;
static vop targets[4],ops[16];static int live[4],cur_pass;static size_t n_ops,cap_ops;
static unsigned grew,feature_queries,lookups;
static VkFormatFeatureFlags features[256];
static struct {int on,msrt,single_frame;uint32_t ms_fbo;}hq;
static struct {uint32_t fbo;int w,h;}blur;
static int fb_target(uint32_t id,vop*out){++lookups;if(id>=4||!live[id])return 0;*out=targets[id];return 1;}
static int fmt_has(VkFormat format,VkFormatFeatureFlags required){++feature_queries;return (uint32_t)format<256&&(features[format]&required)==required;}
#define GROW(p,n,c) do{assert((p)==ops&&(n)<(c));++grew;}while(0)
#pragma GCC poison ctx cur_up set_err glGetError glFinish glFlush vkgl_error_epoch
'''
tests = r'''
#define ALL_FEATURES (VK_FORMAT_FEATURE_TRANSFER_SRC_BIT|VK_FORMAT_FEATURE_TRANSFER_DST_BIT|VK_FORMAT_FEATURE_BLIT_SRC_BIT|VK_FORMAT_FEATURE_BLIT_DST_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT|VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT)
static void reset(void){
 memset(image,0,sizeof image);memset(&SCREEN,0,sizeof SCREEN);memset(targets,0,sizeof targets);memset(ops,0,sizeof ops);memset(live,0,sizeof live);for(unsigned i=0;i<256;++i)features[i]=ALL_FEATURES;
 for(unsigned i=0;i<8;++i)image[i]=(vimg){.fmt=i<2?VK_FORMAT_B10G11R11_UFLOAT_PACK32:VK_FORMAT_D24_UNORM_S8_UINT,.samples=1,.usage=VK_IMAGE_USAGE_TRANSFER_SRC_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT,.serial=10+i};
 live[1]=live[2]=1;targets[1]=(vop){.w=8,.h=6,.color=&image[0],.depth=&image[2]};targets[2]=(vop){.w=8,.h=6,.color=&image[1],.depth=&image[3]};
 hq.on=1;hq.msrt=hq.single_frame=0;hq.ms_fbo=1;blur.fbo=2;blur.w=8;blur.h=6;D.serial=41;F=&frame;cur_pass=7;n_ops=0;cap_ops=16;grew=feature_queries=lookups=0;native_reject_count=5;native_copy_count=3;compat_draw_count=97;legacy_error=0x0502;
}
static cinder_vk_copy_region region(void){return(cinder_vk_copy_region){.source=1,.target=2,.aspects=VK_IMAGE_ASPECT_COLOR_BIT,.source_rect={0,0,8,6},.target_rect={0,0,8,6},.filter=VK_FILTER_NEAREST};}
typedef struct {vimg image[8],screen;vop ops[16];size_t n,cap;int pass;unsigned grows,old_error;uint64_t epoch,copies,compat;}snapshot;
static snapshot capture(void){snapshot s={.screen=SCREEN,.n=n_ops,.cap=cap_ops,.pass=cur_pass,.grows=grew,.old_error=legacy_error,.epoch=cinder_vk_error_epoch(),.copies=native_copy_count,.compat=compat_draw_count};memcpy(s.image,image,sizeof image);memcpy(s.ops,ops,sizeof ops);return s;}
static void unchanged(const snapshot*s){assert(!memcmp(s->image,image,sizeof image)&&!memcmp(&s->screen,&SCREEN,sizeof SCREEN)&&!memcmp(s->ops,ops,sizeof ops)&&s->n==n_ops&&s->cap==cap_ops&&s->pass==cur_pass&&s->grows==grew&&s->old_error==legacy_error&&s->epoch==cinder_vk_error_epoch()&&s->copies==native_copy_count&&s->compat==compat_draw_count);}
static void check(cinder_vk_copy_region*r,int expected,int count){
 snapshot before=capture();F=NULL;assert(cinder_vk_copy_ready(r)==expected);unchanged(&before);F=&frame;assert(cinder_vk_copy_ready(r)==expected);unchanged(&before);
 vop prepared[2];memset(prepared,0xab,sizeof prepared);int n=91;assert(native_copy_prepare(r,prepared,&n)==expected);assert(n==(expected?count:0));unchanged(&before);
 int ok=cinder_vk_copy(r);assert(ok==expected&&legacy_error==0x0502&&compat_draw_count==before.compat);
 if(!ok){assert(cinder_vk_error_epoch()==before.epoch+1&&native_copy_count==before.copies&&cur_pass==before.pass&&n_ops==before.n&&grew==before.grows&&!memcmp(image,before.image,sizeof image)&&!memcmp(ops,before.ops,sizeof ops));}
 else if(!count)unchanged(&before);
 else {assert(cinder_vk_error_epoch()==before.epoch&&native_copy_count==before.copies+1&&n_ops==before.n+(size_t)count&&grew==before.grows+(unsigned)count&&cur_pass==-1&&!memcmp(ops,before.ops,before.n*sizeof *ops));for(int i=0;i<count;++i){vop*o=&ops[before.n+(size_t)i];assert(o->kind==OP_BLIT&&o->src->serial==D.serial&&o->dst->serial==D.serial);}}
}
static void frontend(void){
 reset();features[VK_FORMAT_B10G11R11_UFLOAT_PACK32]&=~VK_FORMAT_FEATURE_BLIT_DST_BIT;snapshot s=capture();F=NULL;assert(!native_hq_copy_ready());unchanged(&s);image[0].samples=4;s=capture();assert(native_hq_copy_ready());unchanged(&s);
 reset();features[VK_FORMAT_B10G11R11_UFLOAT_PACK32]&=~VK_FORMAT_FEATURE_BLIT_SRC_BIT;assert(!native_hq_copy_ready());reset();features[VK_FORMAT_B10G11R11_UFLOAT_PACK32]&=~VK_FORMAT_FEATURE_BLIT_DST_BIT;hq.msrt=1;assert(native_hq_copy_ready());hq.msrt=0;hq.single_frame=1;assert(native_hq_copy_ready());hq.single_frame=0;hq.on=0;assert(native_hq_copy_ready());
 reset();targets[2].resolve=&image[4];assert(!native_hq_copy_ready());reset();targets[1].color=&image[1];assert(!native_hq_copy_ready());reset();image[0].fmt=VK_FORMAT_R8G8B8A8_UINT;assert(!native_hq_copy_ready());reset();targets[1].w=7;assert(!native_hq_copy_ready());
 puts("PASS actual frontend readiness before scene selection: raw1x missing blit rejects, raw4x resolve needs no blit, target resolve/alias/numeric-class/extent guards share actual backend query; direct paths preserved");
}
static void capability_masks(void){
 cinder_vk_copy_region r;reset();r=region();features[image[0].fmt]&=~VK_FORMAT_FEATURE_BLIT_SRC_BIT;check(&r,0,0);reset();r=region();features[image[1].fmt]&=~VK_FORMAT_FEATURE_BLIT_DST_BIT;check(&r,0,0);
 reset();r=region();r.filter=VK_FILTER_LINEAR;features[image[0].fmt]&=~VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;check(&r,0,0);reset();r=region();r.filter=VK_FILTER_LINEAR;check(&r,1,1);
 reset();r=region();image[0].samples=4;features[image[0].fmt]&=~(VK_FORMAT_FEATURE_BLIT_SRC_BIT|VK_FORMAT_FEATURE_BLIT_DST_BIT|VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT);check(&r,1,1);assert(ops[0].resolve_blit&&ops[0].src==&image[0]);
 reset();r=region();features[image[0].fmt]&=~VK_FORMAT_FEATURE_TRANSFER_SRC_BIT;check(&r,0,0);reset();r=region();features[image[1].fmt]&=~VK_FORMAT_FEATURE_TRANSFER_DST_BIT;check(&r,0,0);
 reset();r=region();image[1].fmt=VK_FORMAT_R16G16B16A16_SFLOAT;check(&r,1,1);reset();r=region();image[0].samples=4;image[1].fmt=VK_FORMAT_R16G16B16A16_SFLOAT;check(&r,0,0);
 puts("PASS actual prepare/query/commit feature parity: source/destination blit separately missing, linear filtering gate, raw4x resolve without blit, transfer features, cross-format blit versus exact-format resolve");
}
#define BAD(change) do{reset();cinder_vk_copy_region r=region();change;check(&r,0,0);}while(0)
static void rejection_matrix(void){
 reset();check(NULL,0,0);BAD(r.aspects=0;r.filter=(VkFilter)2);BAD(r.aspects=0x80);BAD(r.filter=(VkFilter)-1);BAD(r.filter=(VkFilter)2);BAD(r.source=3);BAD(r.target=3);BAD(live[1]=0);BAD(live[2]=0);BAD(targets[2].resolve=&image[4]);BAD(targets[1].color=NULL);BAD(targets[2].color=NULL);BAD(targets[1].color=targets[2].color);BAD(image[0].samples=0);BAD(image[1].samples=2);BAD(image[0].usage&=~VK_IMAGE_USAGE_TRANSFER_SRC_BIT);BAD(image[1].usage&=~VK_IMAGE_USAGE_TRANSFER_DST_BIT);BAD(image[0].fmt=VK_FORMAT_R8G8B8A8_UINT);BAD(image[1].fmt=VK_FORMAT_R8G8B8A8_SINT);
 BAD(r.source_rect[0]=-1);BAD(r.source_rect[2]=9);BAD(r.source_rect[1]=7);BAD(r.source_rect[0]=r.source_rect[2]);BAD(r.target_rect[3]=7);BAD(r.target_rect[0]=r.target_rect[2]);BAD(image[0].samples=4;r.target_rect[2]=7);BAD(image[0].samples=4;r.source_rect[0]=8;r.source_rect[2]=0);
 BAD(r.aspects=VK_IMAGE_ASPECT_DEPTH_BIT;image[2].samples=4);BAD(r.aspects=VK_IMAGE_ASPECT_DEPTH_BIT;r.filter=VK_FILTER_LINEAR);BAD(r.aspects=VK_IMAGE_ASPECT_DEPTH_BIT;image[3].fmt=VK_FORMAT_D16_UNORM);BAD(r.aspects=VK_IMAGE_ASPECT_STENCIL_BIT;image[2].fmt=VK_FORMAT_D16_UNORM);BAD(r.aspects=VK_IMAGE_ASPECT_DEPTH_BIT;image[2].fmt=image[3].fmt=VK_FORMAT_R8_UNORM);
 BAD(r.aspects=VK_IMAGE_ASPECT_COLOR_BIT|VK_IMAGE_ASPECT_DEPTH_BIT;image[3].usage&=~VK_IMAGE_USAGE_TRANSFER_DST_BIT);
 puts("PASS null/aspect/filter/target/missing/alias/usage/sample/class/rect/resolve/depth/stencil negatives: query pure and commit admission agrees; failed second aspect never splits pass, stamps serial or records first aspect");
}
static void positive_packets(void){
 reset();cinder_vk_copy_region r=region();check(&r,1,1);assert(!ops[0].resolve_blit&&!memcmp(ops[0].s,r.source_rect,sizeof r.source_rect));
 reset();r=region();n_ops=2;ops[0]=(vop){.kind=OP_PASS,.w=3,.h=2};ops[1]=(vop){.kind=OP_PASS,.w=4,.h=4};cur_pass=1;check(&r,1,1);assert(n_ops==3&&ops[0].w==3&&ops[1].w==4);
 reset();r=region();r.aspects|=VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT;check(&r,1,2);assert(ops[0].copy_aspects==VK_IMAGE_ASPECT_COLOR_BIT&&ops[1].copy_aspects==(VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT));
 reset();r=region();r.aspects=VK_IMAGE_ASPECT_DEPTH_BIT;check(&r,1,1);reset();r=region();r.aspects=VK_IMAGE_ASPECT_STENCIL_BIT;check(&r,1,1);
 reset();r=region();targets[1].screen=1;targets[2].screen=1;targets[1].color=&SCREEN;SCREEN=image[0];check(&r,1,1);assert(ops[0].src_screen&&!ops[0].dst_screen&&ops[0].s[1]==6&&ops[0].s[3]==0&&ops[0].d[1]==6&&ops[0].d[3]==0);
 reset();r=region();image[4]=(vimg){.fmt=image[0].fmt,.samples=1,.usage=VK_IMAGE_USAGE_TRANSFER_SRC_BIT,.serial=19};image[0].samples=4;targets[1].resolve=&image[4];check(&r,1,1);assert(ops[0].src==&image[4]&&!ops[0].resolve_blit);
 puts("PASS exact prepared/committed color+depth/stencil packets, one coverage increment per public copy, screen Y conversion/source identity and resolved-source snapshot behavior");
}
static void no_frame_and_noop(void){
 reset();cinder_vk_copy_region r=region();F=NULL;snapshot s=capture();assert(cinder_vk_copy_ready(&r));unchanged(&s);assert(!cinder_vk_copy(&r)&&cinder_vk_error_epoch()==s.epoch+1&&cur_pass==s.pass&&n_ops==s.n&&native_copy_count==s.copies&&!memcmp(image,s.image,sizeof image));
 reset();r=region();r.aspects=0;r.source=r.target=UINT32_MAX;memset(r.source_rect,0,sizeof r.source_rect);F=NULL;s=capture();assert(cinder_vk_copy_ready(&r)&&cinder_vk_copy(&r));unchanged(&s);assert(!lookups&&!feature_queries);
 reset();r=region();r.aspects=0;check(&r,1,0);
 puts("PASS readiness does not need F or modify old GL error/coverage/native epoch/pass/ops/serial; real nonempty copy still rejects no-F; zero-aspect noop preserves original no-F/invalid-handle contract and has no counter increment");
}
int main(void){frontend();capability_masks();rejection_matrix();positive_packets();no_frame_and_noop();return 0;}
'''

fixture = (prefix + schema('vop') + state + fun(CORE, 'static int is_depth(') +
           fun(CORE, 'static int has_stencil(') + actual + front + tests)
with tempfile.TemporaryDirectory(prefix='copy-ready-', dir=OUT) as work:
    work = Path(work)
    c = work / 'copy.c'
    c.write_text(fixture)
    flags = ['-I', str(ROOT / 'src')]
    if sys.platform == 'darwin':
        flags += ['-I', '/opt/homebrew/include']
    command = [os.environ.get('CC', 'clang'), '-std=gnu11', '-Wall', '-Wextra', '-Werror',
               '-Wno-missing-field-initializers', '-fsanitize=undefined', '-fno-sanitize-recover=all',
               *flags, str(c), '-o', str(work / 'copy')]
    subprocess.run(command, check=True, timeout=120)
    result = subprocess.run([str(work / 'copy')], capture_output=True, text=True, timeout=30)
    (OUT / 'run.log').write_text(result.stdout + result.stderr)
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
    report = {'status': 'pass' if result.returncode == 0 else 'fail', 'exit_code': result.returncode,
              'source_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in INPUTS.items()},
              'actual_subset_sha256': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in parts.items()},
              'frontend_subset_sha256': hashlib.sha256(front.encode()).hexdigest(),
              'fixture_sha256': hashlib.sha256(fixture.encode()).hexdigest(), 'stdout': result.stdout, 'stderr': result.stderr,
              'authority': 'actual prepare/query/commit/metadata/frontend-readiness functions and actual vop schema; target/format-feature mocks',
              'limits': ['No GPU/driver/pixel/fence execution', 'Feature masks are bounded admission stress, not a device-conformance claim',
                         'UBSan only; no ASan/TSan claim', 'No arbitrary concurrency or recovery claim']}
    assert (ROOT / 'src/native_vk.h').read_bytes() == INPUTS['src/native_vk.h']
    (OUT / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    result.check_returncode()
