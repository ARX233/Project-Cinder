#!/usr/bin/env python3
"""Offline trusted-source build. All writes remain beneath --work; no downloads.
Requires verified/extracted ffmpeg-9.0.2 and openh264-{host,android} directories.
Source tar URLs/hashes and license obligations are in DEPENDENCIES.md.
"""
import argparse, os, pathlib, subprocess, shutil, json
p=argparse.ArgumentParser();p.add_argument('--work',required=True);p.add_argument('--target',choices=['host','android'],required=True);p.add_argument('--ndk',default='/Users/arx/Library/Android/sdk/ndk/28.0.13004108');a=p.parse_args()
w=pathlib.Path(a.work).resolve();src=pathlib.Path(__file__).resolve().parent;t=a.target
assert w.is_dir() and (w/'deps/ffmpeg-9.0.2/configure').is_file()
env=os.environ.copy();env.update(HOME=str(w/'home'),TMPDIR=str(w/'tmp'),XDG_CACHE_HOME=str(w/'cache'),CCACHE_DISABLE='1',PYTHONDONTWRITEBYTECODE='1')
for n in ['home','tmp','cache','logs']: (w/n).mkdir(exist_ok=True)
prefix=w/f'prefix-{t}';build=w/f'build-{t}';prefix.mkdir(exist_ok=True);build.mkdir(exist_ok=True)
def run(args,cwd,log):
    with open(w/'logs'/log,'wb') as out:
        subprocess.run([str(x) for x in args],cwd=cwd,env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
ndk=pathlib.Path(a.ndk);tool=ndk/'toolchains/llvm/prebuilt/darwin-x86_64/bin'
openh=w/f'deps/openh264-{t}'
make=['make','-j6','USE_ASM=No','V=No','libopenh264.a']
if t=='host': make+=['OS=darwin','ARCH=arm64','CC=/usr/bin/clang','CXX=/usr/bin/clang++']; cc='/usr/bin/clang';cxx='/usr/bin/clang++'
else: make+=['OS=android','ARCH=arm64','TARGET=android-28',f'NDKROOT={ndk}'];cc=str(tool/'aarch64-linux-android28-clang');cxx=str(tool/'aarch64-linux-android28-clang++')
run(make,openh,f'openh264-{t}-repro.log')
for n in ['lib','include/wels','lib/pkgconfig']: (prefix/n).mkdir(exist_ok=True,parents=True)
# Only generated prefixes can be replaced on a deliberate rebuild; never user input/output.
shutil.copy2(openh/'libopenh264.a',prefix/'lib/libopenh264.a')
for h in (openh/'codec/api/wels').glob('*.h'): shutil.copy2(h,prefix/'include/wels'/h.name)
(prefix/'lib/pkgconfig/openh264.pc').write_text(f'prefix={prefix}\nlibdir=${{prefix}}/lib\nincludedir=${{prefix}}/include\nName: OpenH264\nDescription: Cisco OpenH264\nVersion: 2.6.0\nLibs: -L${{libdir}} -lopenh264\nLibs.private: -lc++ -lm\nCflags: -I${{includedir}}\n')
env['PKG_CONFIG_LIBDIR']=str(prefix/'lib/pkgconfig');env['PKG_CONFIG_PATH']=''
config=[str(w/'deps/ffmpeg-9.0.2/configure'),f'--prefix={prefix}','--disable-everything','--disable-autodetect','--disable-network','--disable-programs','--disable-doc','--disable-avdevice','--disable-avfilter','--disable-shared','--enable-static','--enable-pic','--disable-gpl','--disable-nonfree','--disable-version3','--disable-iconv','--disable-zlib','--disable-bzlib','--disable-lzma','--enable-swscale','--enable-swresample','--enable-libopenh264','--enable-decoder=bink,pcm_s16le,pcm_s24le,pcm_s32le,pcm_u8,pcm_f32le,aac,h264','--enable-encoder=aac,libopenh264','--enable-demuxer=bink,wav,mov','--enable-muxer=mp4,ipod','--enable-parser=aac,h264',f'--cc={cc}',f'--cxx={cxx}','--pkg-config=/opt/homebrew/bin/pkg-config','--pkg-config-flags=--static']
if t=='android':config+=['--enable-cross-compile','--target-os=android','--arch=aarch64',f'--ar={tool}/llvm-ar',f'--ranlib={tool}/llvm-ranlib',f'--strip={tool}/llvm-strip','--extra-cflags=-O2 -fPIC','--extra-ldflags=-Wl,-z,max-page-size=16384']
else:config+=['--arch=aarch64','--extra-cflags=-O2 -fPIC','--extra-libs=-lc++']
run(config,build,f'ffmpeg-config-{t}.log');run(['make','-j6'],build,f'ffmpeg-build-{t}.log');run(['make','install'],build,f'ffmpeg-install-{t}.log')
libs=[prefix/f'lib/lib{n}.a' for n in ['avformat','avcodec','swscale','swresample','avutil','openh264']]
out=prefix/'lib'/('liboc_media.so' if t=='android' else 'liboc_media.dylib')
flags=['-shared','-Wl,-z,max-page-size=16384','-Wl,-z,common-page-size=16384','-Wl,-soname,liboc_media.so','-Wl,--no-undefined',f'-Wl,--version-script={src}/oc_media.map','-static-libstdc++'] if t=='android' else ['-dynamiclib','-Wl,-install_name,@rpath/liboc_media.dylib']
# cxx driver for OpenH264 C++ runtime; compile the bridge as C separately.
run([cc,'-std=c11','-O2','-fPIC','-Wall','-Wextra','-Werror',f'-I{prefix}/include','-c',src/'oc_media.c','-o',build/'oc_media.o'],build,f'bridge-compile-{t}.log')
run([cxx,*flags,build/'oc_media.o',*libs,'-lm','-o',out],build,f'bridge-link-{t}.log')
if t=='host':
    (w/'proof').mkdir(exist_ok=True)
    run([cc,'-std=c11','-O2',f'-I{prefix}/include',src/'verify_media.c',*libs,'-lc++','-lm','-o',w/'proof/verify_media'],build,'verify-tool-compile-host.log')
(w/'logs'/f'build-{t}.json').write_text(json.dumps({'target':t,'configure':config,'output':str(out)},indent=2)+'\n')
print(out)
