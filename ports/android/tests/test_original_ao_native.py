"""FD-only AO safety/oracle tests; compile ONLY trusted project C.

Artifacts are never written into the repository. Set OA_NATIVE_WORK_ROOT to a
new/existing AO directory below the authorized external parent; default is the
unique directory allocated for this task. OA_NATIVE_FRESH_WPK may select a fresh
original-derived WPK for optional full-recipe CLI oracle proof. No emulator,
original main/APK, device, old WPK output, or output fallback is used.
Run: python3 -m unittest discover -s tests -p test_original_ao_native.py -v
"""
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
PARENT = Path('/Volumes/CodexWork/android135-original-convert-l809giqy').resolve()
WORK = Path(os.environ.get('OA_NATIVE_WORK_ROOT', str(PARENT / 'ao-fd-zbzmzktk'))).resolve()
if WORK == PARENT or not WORK.is_relative_to(PARENT) or not WORK.name.startswith('ao-'):
    raise RuntimeError('AO build/temp/proof root must be a unique ao-* directory below authorized external parent')
WORK.mkdir(parents=True, exist_ok=True)
COMPILER_TMP = WORK / 'compiler-tmp'
COMPILER_TMP.mkdir(exist_ok=True)
os.environ['TMPDIR'] = str(COMPILER_TMP)
FLAGS = ['-std=c11', '-O2', '-fwrapv', '-ffp-contract=off', '-fno-fast-math', '-pthread']
CC = os.environ.get('OA_NATIVE_CC', shutil.which('clang') or 'clang')
POLL = C.CFUNCTYPE(C.c_int, C.c_void_p)

class Limits(C.Structure):
    _fields_ = [('struct_size', C.c_uint32), ('abi_version', C.c_uint32)] + [
        (n, C.c_uint64) for n in ('max_source_bytes', 'max_heap_bytes', 'max_output_bytes',
        'max_work_units', 'max_wall_ms', 'max_cpu_ms')] + [
        (n, C.c_uint32) for n in ('max_textures', 'max_chunks', 'max_batches',
        'max_triangles', 'max_maps', 'max_texture_dimension', 'size', 'rays')]

class Cancel(C.Structure):
    _fields_ = [('struct_size', C.c_uint32), ('poll', POLL), ('user', C.c_void_p)]

class Result(C.Structure):
    _fields_ = [('struct_size', C.c_uint32), ('abi_version', C.c_uint32),
        ('status', C.c_int32), ('system_errno', C.c_int32)] + [
        (n, C.c_uint64) for n in ('source_bytes', 'output_bytes', 'heap_peak_bytes',
        'work_units', 'elapsed_wall_ms', 'elapsed_cpu_ms', 'allocations_live')] + [
        ('maps', C.c_uint32), ('triangles', C.c_uint32), ('message', C.c_char * 160)]

def load_library(path):
    lib = C.CDLL(str(path))
    lib.oa_default_limits.argtypes = [C.POINTER(Limits)]
    lib.oa_bake_fd.argtypes = [C.c_int, C.c_int, C.POINTER(Limits), C.POINTER(Cancel), C.POINTER(Result)]
    lib.oa_bake_fd.restype = C.c_int
    return lib

def defaults(lib):
    l = Limits(); lib.oa_default_limits(C.byref(l)); return l

def bake(lib, src, out, limits=None, callback=None):
    limits = limits or defaults(lib)
    r = Result(); r.struct_size = C.sizeof(r)
    cb = POLL(callback) if callback else None
    cancel = Cancel(C.sizeof(Cancel), cb, None) if cb else None
    code = lib.oa_bake_fd(src, out, C.byref(limits), C.byref(cancel) if cancel else None, C.byref(r))
    return code, r

def fixture(dim=8, triangles=1, texture_payload=True, zero_dims=False):
    """One solid car.cg body map, packed s16 normals and exact disjoint ranges."""
    to, co, bo = 32, 96, 132
    payload = bo + 28
    texture = bytes(dim * dim * 2) if texture_payload else b''
    vo = payload + len(texture)
    verts = b''.join(struct.pack('<5f4B4h', *p, *uv, 255,255,255,255, 0,32767,0,0)
        for p,uv in [((0.,0.,0.),(0.,0.)), ((1.,0.,0.),(1.,0.)), ((0.,0.,1.),(0.,1.))])
    indices = struct.pack('<3H', 0,1,2) * triangles
    header = struct.pack('<4sIIIfIII', b'WPK3',1,1,1,4000.,to,co,bo)
    tex = struct.pack('<48sHHIII', b'body',0 if zero_dims else dim,dim,0,payload,len(texture))
    chunk = struct.pack('<6fIII',0.,0.,0.,1.,0.,1.,0,1,0)
    batch = struct.pack('<HHIIIIBBHHH',0,0,vo,3,vo+len(verts),triangles*3,1,0,65535,65535,0)
    return bytearray(header+tex+chunk+batch+texture+verts+indices)

def two_map_fixture():
    d=fixture(texture_payload=False)
    verts=d[160:256]; indices=d[256:262]
    # Two inherited textures, one chunk and two distinct geometry regions.
    header=struct.pack('<4sIIIfIII',b'WPK3',2,1,2,4000.,32,160,196)
    tex=b''.join(struct.pack('<48sHHIII',name,8,8,0,252,0) for name in (b'body',b'body2'))
    chunk=struct.pack('<6fIII',0.,0.,0.,1.,0.,1.,0,2,0)
    batch=b''.join(struct.pack('<HHIIIIBBHHH',t,0,vo,3,vo+96,3,1,0,65535,65535,0)
        for t,vo in ((0,252),(1,356)))
    return bytearray(header+tex+chunk+batch+verts+indices+b'\x00\x00'+verts+indices)

class NativeAOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='test-', dir=WORK))
        cls.library = cls.root / ('liboa_native.dylib' if sys.platform=='darwin' else 'liboa_native.so')
        link = '-dynamiclib' if sys.platform=='darwin' else '-shared'
        cls.compile_cmd = [CC,*FLAGS,'-fPIC','-fvisibility=hidden',link,
            str(REPO/'tools/original_convert/ao_native/oa_native.c'),'-o',str(cls.library),'-lm']
        subprocess.run(cls.compile_cmd, check=True, capture_output=True, text=True)
        cls.lib = load_library(cls.library)
        (cls.root/'compile.json').write_text(json.dumps(cls.compile_cmd))

    def pair(self, data=None, output=b''):
        td = Path(tempfile.mkdtemp(prefix='case-', dir=self.root))
        src=td/'in.wpk'; src.write_bytes(bytes(fixture() if data is None else data))
        out=td/'out.ao'
        sf=os.open(src,os.O_RDONLY)
        of=os.open(out,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
        if output: os.write(of,output)
        def close_if_open(fd):
            try: os.close(fd)
            except OSError: pass
        self.addCleanup(close_if_open,sf); self.addCleanup(close_if_open,of)
        return sf,of,out

    def expect(self, data, status=3):
        sf,of,out=self.pair(data)
        code,r=bake(self.lib,sf,of)
        self.assertEqual(code,status,r.message)
        self.assertEqual(r.allocations_live,0)
        self.assertEqual(out.stat().st_size,0)
        os.close(sf); os.close(of)
        return r

    def test_valid_deterministic_repeat_and_no_live_allocation(self):
        hashes=[]
        for _ in range(30):
            sf,of,out=self.pair()
            os.lseek(sf,7,os.SEEK_SET)
            code,r=bake(self.lib,sf,of)
            self.assertEqual(code,0,r.message)
            self.assertEqual(r.allocations_live,0)
            self.assertEqual(os.lseek(sf,0,os.SEEK_CUR),7)
            self.assertEqual(out.read_bytes()[:8],b'WAO1\x01\x00\x00\x00')
            self.assertEqual((r.maps,r.triangles),(1,1))
            self.assertEqual(r.output_bytes,8+52+64)
            hashes.append(hashlib.sha256(out.read_bytes()).hexdigest())
        self.assertEqual(len(set(hashes)),1)

    def test_zero_payload_aero_texture_is_legal_but_zero_dimensions_not(self):
        sf,of,_=self.pair(fixture(texture_payload=False))
        self.assertEqual(bake(self.lib,sf,of)[0],0)
        self.expect(fixture(zero_dims=True))

    def test_every_truncation(self):
        d=fixture()
        for end in range(len(d)):
            self.expect(d[:end])

    def test_invalid_ranges_counts_materials_names_bounds_and_indices(self):
        base=fixture(); vo=struct.unpack_from('<I',base,136)[0]; io=struct.unpack_from('<I',base,144)[0]
        cases=[]
        for off,value,fmt in [(4,0xffffffff,'I'),(20,0xfffffffc,'I'),(24,32,'I'),(28,96,'I'),
            (132+4,32,'I'),(132+12,vo,'I'),(132+8,65537,'I'),(132+16,4,'I'),
            (132,4,'H'),(132+20,3,'B'),(132+21,1,'B'),(132+22,12,'H'),
            (96+24,1,'I'),(96+28,2,'I'),(96+32,0x10000,'I'),(io,3,'H'),
            (32+48,0,'H'),(32+52,3,'I'),(32+60,2,'I'),(16,math.nan,'f'),
            (96,math.inf,'f'),(vo,math.nan,'f'),(vo+4,math.inf,'f'),
            (vo+12,math.nan,'f'),(vo+16,math.inf,'f'),(vo,1e30,'f')]:
            d=base.copy(); struct.pack_into('<'+fmt,d,off,value); cases.append(d)
        d=base.copy(); d[32:80]=b'x'*48; cases.append(d)
        for d in cases:
            # Huge declared table counts fail quota before dereferencing.
            self.expect(d,4 if struct.unpack_from('<I',d,4)[0]==0xffffffff else 3)
        # Two chunks owning the same one batch (all offset/payload fields moved).
        d=base.copy(); d[132:132]=base[96:132]; struct.pack_into('<I',d,8,2); struct.pack_into('<I',d,28,168)
        for off in (168+4,168+12,32+56): struct.pack_into('<I',d,off,struct.unpack_from('<I',d,off)[0]+36)
        self.expect(d)

    def test_alias_nonempty_append_and_nonregular_fds(self):
        sf,of,out=self.pair()
        same=os.open(out,os.O_RDWR); self.addCleanup(os.close,same)
        self.assertEqual(bake(self.lib,of,same)[0],2)
        sf,of,out=self.pair(output=b'keep')
        self.assertEqual(bake(self.lib,sf,of)[0],2)
        self.assertEqual(out.read_bytes(),b'keep')
        af=os.open(out,os.O_WRONLY|os.O_APPEND); self.addCleanup(os.close,af)
        self.assertEqual(bake(self.lib,sf,af)[0],2)
        rd,wr=os.pipe(); self.addCleanup(os.close,rd); self.addCleanup(os.close,wr)
        self.assertEqual(bake(self.lib,rd,wr)[0],2)
        self.assertEqual(bake(self.lib,-1,of)[0],2)
        os.fstat(sf); os.fstat(of)

    def test_budget_source_heap_output_maps_triangles_work(self):
        for name,value in [('max_source_bytes',32),('max_heap_bytes',64),('max_output_bytes',8),
            ('max_triangles',1),('max_work_units',1),('max_maps',1)]:
            data=fixture(triangles=2) if name=='max_triangles' else fixture()
            if name=='max_maps': data=two_map_fixture()
            sf,of,_=self.pair(data); l=defaults(self.lib); setattr(l,name,value)
            code,r=bake(self.lib,sf,of,l)
            self.assertEqual(code,4,(name,r.message)); self.assertEqual(r.allocations_live,0)
        # Heap failures at varied points reclaim source, parser and legacy arrays.
        for cap in (512,1024,2048,4096,8192,16384,65536,149000,150000,200000):
            sf,of,_=self.pair(); l=defaults(self.lib); l.max_heap_bytes=cap
            code,r=bake(self.lib,sf,of,l)
            self.assertIn(code,(0,4)); self.assertEqual(r.allocations_live,0)

    def test_cancel_during_math_preserves_partial_and_releases_lock(self):
        sf,of,out=self.pair(fixture(dim=256))
        after_header=0
        def cancel(_):
            nonlocal after_header
            if os.fstat(of).st_size>=8: after_header+=1
            return after_header>=8
        start=time.monotonic(); code,r=bake(self.lib,sf,of,callback=cancel)
        self.assertEqual(code,5,r.message); self.assertLess(time.monotonic()-start,2)
        self.assertEqual(out.stat().st_size,8)
        self.assertGreater(r.work_units,1024)
        self.assertEqual(r.allocations_live,0)
        sf,of,_=self.pair(); self.assertEqual(bake(self.lib,sf,of)[0],0)

    def test_work_cpu_wall_limits_within_single_map(self):
        for field,value in [('max_work_units',2000),('max_cpu_ms',1),('max_wall_ms',1)]:
            sf,of,out=self.pair(fixture(dim=256)); l=defaults(self.lib); setattr(l,field,value)
            start=time.monotonic(); code,r=bake(self.lib,sf,of,l)
            self.assertEqual(code,4,(field,r.message)); self.assertLess(time.monotonic()-start,2)
            self.assertEqual(r.allocations_live,0)

    def test_concurrent_calls_and_recursive_busy(self):
        entered=threading.Event(); release=threading.Event(); result=[]
        sf,of,partial=self.pair(fixture(dim=256))
        original_sf,original_of,original=self.pair(two_map_fixture())
        self.assertEqual(bake(self.lib,original_sf,original_of)[0],0)
        def stop(_): entered.set(); release.wait(5); return 1
        thread=threading.Thread(target=lambda: result.append(bake(self.lib,sf,of,callback=stop)))
        thread.start(); self.assertTrue(entered.wait(5))
        try:
            sf2,of2,parallel=self.pair(two_map_fixture()); code,r=bake(self.lib,sf2,of2)
            self.assertEqual(code,0,r.message)
            self.assertEqual(parallel.read_bytes(),original.read_bytes())
            self.assertEqual(r.allocations_live,0)
        finally: release.set(); thread.join(5)
        self.assertFalse(thread.is_alive()); self.assertEqual(result[0][0],5)
        self.assertEqual(partial.stat().st_size,0)
        self.assertEqual(result[0][1].allocations_live,0)
        sf,of,_=self.pair(); recursive=[]
        def recurse(_):
            sf2,of2,_=self.pair(); recursive.append(bake(self.lib,sf2,of2)[0]); return 1
        self.assertEqual(bake(self.lib,sf,of,callback=recurse)[0],5)
        self.assertEqual(recursive,[7])

    def test_owned_batch_parallel_receipts_and_cancellation(self):
        sys.path.insert(0,str(REPO/'tools'))
        try:
            from original_convert.ao import Backend, _StopSignal, bake_owned_many
            from original_convert.source import ConversionCancelled, OwnedOutput, SourceEntry
        finally:
            sys.path.pop(0)
        backend=Backend(self.library)
        def new_output():
            output=OwnedOutput(self.root)
            names=[]
            fixtures = (fixture(), two_map_fixture(), fixture(dim=16), fixture(dim=32))
            for i,data in enumerate(fixtures * 2):
                name=f'cars/car{i}.wpk'
                output.target(name).write_bytes(data)
                output.files[name]=SourceEntry(len(data),hashlib.sha256(data).hexdigest())
                names.append(name)
            return output,names
        baseline,names=new_output()
        bake_owned_many(backend,baseline,names,workers=1)
        for count in (2,4,8):
            output,names=new_output()
            progress=[]
            bake_owned_many(backend,output,names,workers=count,progress=lambda _,done,total:progress.append((done,total)))
            self.assertEqual(progress,[(i,len(names)) for i in range(1,len(names)+1)])
            self.assertEqual(output.files,baseline.files)
            for name in names:
                ao=name[:-4]+'.ao'
                self.assertEqual((output.root/ao).read_bytes(),(baseline.root/ao).read_bytes())

        stop=_StopSignal(backend)
        stop.set()
        sf,of,out=self.pair(fixture(dim=256))
        with self.assertRaises(ConversionCancelled):
            backend.convert(sf,of,stop=stop)
        self.assertEqual(out.stat().st_size,0)

        output,names=new_output()
        cancelled=threading.Event()
        with self.assertRaises(ConversionCancelled):
            bake_owned_many(backend,output,names,workers=2,cancel=cancelled.is_set,
                            progress=lambda *_:cancelled.set())
        self.assertEqual(sum(name.endswith('.ao') for name in output.files),1)

    def test_bakes_resume_at_the_last_durable_checkpoint(self):
        sys.path.insert(0,str(REPO/'tools'))
        try:
            from original_convert.ao import Backend, bake_owned_many
            from original_convert.checkpoint import ConversionCheckpoint
            from original_convert.source import ConversionCancelled, SourceEntry
        finally:
            sys.path.pop(0)
        backend=Backend(self.library)
        job_root=Path(tempfile.mkdtemp(prefix='checkpoint-',dir=self.root))
        (job_root/'outputs').mkdir()
        job={key:'a'*64 for key in ('job_id','nonce','profile_sha256','readset_sha256','recipe_sha256')}
        car_names=[f'cars/car{i}.wpk' for i in range(4)]
        input_bytes=[fixture(),two_map_fixture(),fixture(dim=16),fixture(dim=32)]
        targets={name:{'max_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
                 for name,data in zip(car_names,input_bytes)}
        targets.update({name[:-4]+'.ao':{'max_bytes':5000,'sha256':None} for name in car_names})
        cancelled=threading.Event()
        checkpoint=ConversionCheckpoint(job_root,job,targets,cancelled.is_set)
        output=checkpoint.open_output()
        for name,data in zip(car_names,input_bytes):
            output.target(name).write_bytes(data)
            output.files[name]=SourceEntry(len(data),targets[name]['sha256'])
        checkpoint.save('cars')
        saved=[]
        def record(name):
            checkpoint.save('ao:'+name,[name])
            saved.append(name)
            cancelled.set()
        with self.assertRaises(ConversionCancelled):
            bake_owned_many(backend,output,car_names,workers=2,cancel=cancelled.is_set,
                            wall_budget_ms=60_000,on_baked=record)
        self.assertEqual(len(saved),1)
        persisted=(output.root/saved[0]).read_bytes()
        cancelled.clear()
        checkpoint=ConversionCheckpoint(job_root,job,targets,cancelled.is_set)
        output=checkpoint.open_output()
        self.assertTrue(checkpoint.has('cars'))
        self.assertEqual(set(output.files),set(car_names+saved))
        pending=[name for name in car_names if name[:-4]+'.ao' not in output.files]
        self.assertEqual(len(pending),3)
        bake_owned_many(backend,output,pending,workers=2,cancel=cancelled.is_set,wall_budget_ms=60_000,
                        on_baked=lambda name:checkpoint.save('ao:'+name,[name]))
        self.assertEqual((output.root/saved[0]).read_bytes(),persisted)
        self.assertEqual(len(output.files),8)
        (output.root/saved[0]).write_bytes(b'changed')
        recovered=ConversionCheckpoint(job_root,job,targets,cancelled.is_set).open_output()
        self.assertNotIn(saved[0],recovered.files)
        self.assertFalse((recovered.root/saved[0]).exists())
        self.assertEqual(len(recovered.files),7)

    def test_repeated_success_failure_no_fd_leak(self):
        directory='/dev/fd' if sys.platform=='darwin' else '/proc/self/fd'
        before=len(os.listdir(directory))
        for i in range(100):
            td=Path(tempfile.mkdtemp(prefix='repeat-',dir=self.root)); sp=td/'s'; op=td/'o'
            sp.write_bytes(fixture() if i%2 else b'bad')
            sf=os.open(sp,os.O_RDONLY); of=os.open(op,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
            try:
                code,r=bake(self.lib,sf,of)
                self.assertEqual(code,0 if i%2 else 3); self.assertEqual(r.allocations_live,0)
            finally: os.close(sf); os.close(of)
        self.assertEqual(len(os.listdir(directory)),before)

    def test_abi_and_fixed_recipe(self):
        sf,of,_=self.pair()
        for field,value in [('abi_version',2),('size',128),('rays',8),('max_maps',0)]:
            l=defaults(self.lib); setattr(l,field,value)
            self.assertEqual(bake(self.lib,sf,of,l)[0],1)

    def test_host_ubsan_and_write_failure(self):
        source=self.root/'sanitizer_harness.c'
        source.write_text(r'''
#define _POSIX_C_SOURCE 200809L
#include "oa_native.h"
#include <assert.h>
#include <fcntl.h>
#include <fenv.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/resource.h>
#include <unistd.h>
static int calls;
static int cancel(void *p) { (void)p; return ++calls>=8; }
int main(int argc,char **argv) {
  assert(argc==3);
  int s=open(argv[1],O_RDONLY); assert(s>=0);
  for(int i=0;i<100;i++) {
    char path[4096]; snprintf(path,sizeof path,"%s/san-%d.ao",argv[2],i);
    int o=open(path,O_RDWR|O_CREAT|O_EXCL,0600); assert(o>=0);
    oa_limits l; oa_default_limits(&l);
    oa_result r={.struct_size=sizeof r};
    oa_cancel c={sizeof c,cancel,NULL}; calls=0;
    if(i%3==0) l.max_heap_bytes=1024;
    if(i%3==1) l.max_work_units=1000;
    int old=fegetround(); assert(!fesetround(FE_DOWNWARD));
    int rc=oa_bake_fd(s,o,&l,i%3==2?&c:NULL,&r);
    assert(rc==OA_LIMIT || rc==OA_CANCELLED || rc==OA_OK);
    assert(fegetround()==FE_DOWNWARD); assert(!fesetround(old));
    assert(r.allocations_live==0); assert(fcntl(s,F_GETFD)>=0); assert(fcntl(o,F_GETFD)>=0);
    assert(close(o)==0);
  }
  char path[4096]; snprintf(path,sizeof path,"%s/short-write.ao",argv[2]);
  int o=open(path,O_RDWR|O_CREAT|O_EXCL,0600); assert(o>=0);
  struct rlimit before,small; assert(!getrlimit(RLIMIT_FSIZE,&before)); small=before; small.rlim_cur=16;
  signal(SIGXFSZ,SIG_IGN); assert(!setrlimit(RLIMIT_FSIZE,&small));
  oa_limits l; oa_default_limits(&l); oa_result r={.struct_size=sizeof r};
  assert(oa_bake_fd(s,o,&l,NULL,&r)==OA_IO); assert(r.output_bytes==16); assert(r.allocations_live==0);
  assert(!setrlimit(RLIMIT_FSIZE,&before)); close(o); close(s); return 0;
}
''')
        exe=self.root/'sanitizer-harness'; sample=self.root/'sanitizer-input.wpk'; sample.write_bytes(fixture())
        command=[CC,*FLAGS,'-g','-fsanitize=undefined','-fno-sanitize-recover=all',
            '-I'+str(REPO/'tools/original_convert/ao_native'),str(source),
            str(REPO/'tools/original_convert/ao_native/oa_native.c'),'-o',str(exe),'-lm']
        # A compiler/runtime failure is a real test failure, never silently a pass.
        subprocess.run(command,check=True,capture_output=True,text=True)
        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:abort_on_error=1',UBSAN_OPTIONS='halt_on_error=1')
        run=subprocess.run([str(exe),str(sample),str(self.root)],env=env,check=True,capture_output=True,text=True,timeout=60)
        (self.root/'sanitizer-proof.json').write_text(json.dumps({'command':command,'returncode':run.returncode,
            'stderr':run.stderr,'asan':False,'ubsan':True,'lsan':False,'ledger_live_at_return':0}))

    def test_host_asan_runtime_probe(self):
        # Some Apple ASan runtimes hang before main on this host. That is
        # unsupported evidence, not a backend pass; once main starts ANY timeout
        # or sanitizer report is a test failure.
        source=self.root/'asan_probe.c'
        source.write_text(r'''
#define _POSIX_C_SOURCE 200809L
#include "oa_native.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
int main(int argc,char **argv) {
  write(2,"OA_MAIN_ENTERED\\n",16); assert(argc==3);
  int s=open(argv[1],O_RDONLY); assert(s>=0);
  for(int i=0;i<3;i++) {
    char path[4096]; snprintf(path,sizeof path,"%s/asan-%d.ao",argv[2],i);
    int o=open(path,O_RDWR|O_CREAT|O_EXCL,0600); assert(o>=0);
    oa_limits l; oa_default_limits(&l); if(i==1) l.max_heap_bytes=1024;
    oa_result r={.struct_size=sizeof r};
    int rc=oa_bake_fd(s,o,&l,NULL,&r); assert(rc==(i==1?OA_LIMIT:OA_OK));
    assert(r.allocations_live==0); close(o);
  }
  close(s); return 0;
}
''')
        exe=self.root/'asan-probe'; sample=self.root/'asan-input.wpk'; sample.write_bytes(fixture())
        cmd=[CC,*FLAGS,'-g','-fsanitize=address','-I'+str(REPO/'tools/original_convert/ao_native'),
            str(source),str(REPO/'tools/original_convert/ao_native/oa_native.c'),'-o',str(exe),'-lm']
        subprocess.run(cmd,check=True,capture_output=True,text=True)
        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0:abort_on_error=1:verbosity=1')
        try:
            run=subprocess.run([str(exe),str(sample),str(self.root)],env=env,check=True,capture_output=True,text=True,timeout=10)
        except subprocess.TimeoutExpired as error:
            stderr=error.stderr or b''
            if b'OA_MAIN_ENTERED' in stderr: raise
            (self.root/'asan-unsupported.json').write_text(json.dumps({'command':cmd,'status':'unsupported-startup-timeout',
                'timeout_seconds':10,'stderr':stderr.decode(errors='replace'),'backend_entered':False,'passed':False}))
            self.skipTest('ASan runtime hangs before main; unsupported, no ASan backend proof')
        (self.root/'asan-proof.json').write_text(json.dumps({'command':cmd,'status':'pass','returncode':run.returncode,'stderr':run.stderr,'lsan':False}))

    @unittest.skipUnless(os.environ.get('OA_NATIVE_FRESH_WPK'),'full 256/96 fresh original-derived oracle proof explicitly selected')
    def test_fresh_wpk_matches_trusted_cli_oracle(self):
        fixture_path=Path(os.environ['OA_NATIVE_FRESH_WPK']).resolve()
        if not fixture_path.is_relative_to(PARENT/'car-tables-static-46v_ox3d'):
            self.fail('real oracle probe must use this task\'s fresh original-derived WPK')
        cli=self.root/'trusted-cli'; oracle=self.root/'oracle.ao'; actual=self.root/'actual.ao'
        subprocess.run([CC,*FLAGS,str(REPO/'tools/stage/bake_ao.c'),'-o',str(cli),'-lm'],check=True)
        subprocess.run([str(cli),str(fixture_path),str(oracle),'256','96'],check=True,timeout=600,capture_output=True)
        sf=os.open(fixture_path,os.O_RDONLY); of=os.open(actual,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
        try: code,r=bake(self.lib,sf,of)
        finally: os.close(sf); os.close(of)
        self.assertEqual(code,0,r.message); self.assertEqual(actual.read_bytes(),oracle.read_bytes())
        proof={'source':str(fixture_path),'source_sha256':hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
            'ao_sha256':hashlib.sha256(actual.read_bytes()).hexdigest(),'bytes':actual.stat().st_size,
            'compile_flags':FLAGS,'maps':r.maps,'triangles':r.triangles,'work_units':r.work_units,
            'peak_heap':r.heap_peak_bytes,'wall_ms':r.elapsed_wall_ms,'cpu_ms':r.elapsed_cpu_ms,
            'live_allocations':r.allocations_live,'platform':sys.platform,'android_bytes_verified':False}
        (self.root/'real-proof.json').write_text(json.dumps(proof,indent=2)); print(json.dumps(proof))

if __name__=='__main__': unittest.main()
