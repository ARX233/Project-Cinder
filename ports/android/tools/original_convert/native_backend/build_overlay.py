#!/usr/bin/env python3
"""Additive overlay variant. Never reconfigures/rebuilds/writes the frozen ABI1 base.
Uses already-retained official dependency archives and original bridge object.
"""
import argparse,hashlib,json,os,pathlib,subprocess
p=argparse.ArgumentParser();p.add_argument('--base-work',required=True);p.add_argument('--work',required=True);p.add_argument('--target',choices=['host','android'],required=True);p.add_argument('--ndk',default='/Users/arx/Library/Android/sdk/ndk/28.0.13004108');a=p.parse_args()
b=pathlib.Path(a.base_work).resolve();w=pathlib.Path(a.work).resolve();s=pathlib.Path(__file__).resolve().parent;t=a.target
assert w.is_dir() and w!=b
assert hashlib.sha256((b/'src/oc_media.c').read_bytes()).hexdigest()=='4fda60908417de7dbea900e8eab94534a747461ffc80ed7c814bc31a6d9158b7'
for n in ['logs',f'build-{t}']:(w/n).mkdir(exist_ok=True)
env=os.environ.copy();env.update(HOME=str(b/'home'),TMPDIR=str(b/'tmp'),XDG_CACHE_HOME=str(b/'cache'),CCACHE_DISABLE='1',PYTHONDONTWRITEBYTECODE='1')
tool=pathlib.Path(a.ndk)/'toolchains/llvm/prebuilt/darwin-x86_64/bin';cc=str(tool/'aarch64-linux-android28-clang') if t=='android' else '/usr/bin/clang';cxx=str(tool/'aarch64-linux-android28-clang++') if t=='android' else '/usr/bin/clang++';prefix=b/f'prefix-{t}';build=w/f'build-{t}'
def run(args,log):
    with (w/'logs'/log).open('wb') as f:subprocess.run([str(x) for x in args],cwd=build,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
objects=[]
for name in ['oc_media_overlay','oc_overlay_pixels']:
    obj=build/(name+'.o');run([cc,'-std=c11','-O2','-fPIC','-Wall','-Wextra','-Werror',f'-I{s}',f'-I{b}/src',f'-I{prefix}/include','-c',s/(name+'.c'),'-o',obj],f'compile-{name}-{t}.log');objects.append(obj)
libs=[prefix/f'lib/lib{n}.a' for n in ['avformat','avcodec','swscale','swresample','avutil','openh264']]
base_object=b/f'build-{t}/oc_media.o';before={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in [base_object,prefix/'lib'/('liboc_media.so' if t=='android' else 'liboc_media.dylib')]}
out=build/('liboc_media_overlay.so' if t=='android' else 'liboc_media_overlay.dylib')
flags=['-shared','-Wl,-z,max-page-size=16384','-Wl,-z,common-page-size=16384','-Wl,-soname,liboc_media_overlay.so','-Wl,--no-undefined',f'-Wl,--version-script={s}/oc_media_overlay.map','-static-libstdc++'] if t=='android' else ['-dynamiclib','-Wl,-install_name,@rpath/liboc_media_overlay.dylib']
run([cxx,*flags,base_object,*objects,*libs,'-lm','-o',out],f'link-overlay-{t}.log')
assert before=={str(x):hashlib.sha256(pathlib.Path(x).read_bytes()).hexdigest() for x in before}
if t=='host':
    (w/'proof').mkdir(exist_ok=True)
    run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',f'-I{prefix}/include',s/'extract_rgb_frames.c',*libs,'-lc++','-lm','-o',w/'proof/extract_rgb_frames'],'compile-extract-rgb-host.log')
with (w/'logs'/f'overlay-build-{t}.json').open('w') as f:json.dump({'output':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'base_unchanged':before},f,indent=2);f.write('\n')
print(out)
