# Pinned native media dependencies

Collected 2026-11-03; this is build-time dependency acquisition only. The APK has no network acquisition or runtime executable requirement.

| Dependency | Official source / version | SHA-256 | Authority / license |
|---|---|---|---|
| FFmpeg | https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz | `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e` | Observed HTTPS/TLS download, **local SHA**, not an independently authenticated official checksum. Official https://ffmpeg.org/download.html identified 9.0.2 as latest stable (released 2026-09-18). `.asc` downloaded but **not verified**: no trusted signing-key verification was performed. Build: LGPL 2.1 or later. |
| Cisco OpenH264 | https://github.com/cisco/openh264/archive/refs/tags/v2.6.0.tar.gz | `558544ad358283a7ab2930d69a9ceddf913f4a51ee9bf1bfb9e377322af81a69` | Official Cisco repository tag, observed HTTPS/TLS download, **local SHA**, no independently authenticated official checksum. Source copyright BSD-2-Clause. |
| Android NDK | Existing local official NDK `28.0.13004108` / r28; https://developer.android.com/ndk/downloads/revision_history | No SDK archive downloaded or archive checksum asserted | `source.properties` confirms version. clang 19 driver `aarch64-linux-android28-clang`. Static libc++/libc++abi/compiler support uses bundled LLVM notices/exceptions; bundled Android cpufeatures is BSD-style. NDK read only. |

OpenH264 was compiled from source, **not** downloaded as a Cisco-distributed prebuilt binary. Neither its BSD copyright license nor any Cisco binary patent-royalty arrangement is a blanket patent clearance for this application/distribution. AAC/H.264 patent review remains a release responsibility.

## Configuration

The complete reproducible configuration is in [build_native.py](build_native.py). Essential FFmpeg options:

```
--disable-everything --disable-autodetect --disable-network
--disable-programs --disable-doc --disable-avdevice --disable-avfilter
--disable-shared --enable-static --enable-pic
--disable-gpl --disable-nonfree --disable-version3
--disable-iconv --disable-zlib --disable-bzlib --disable-lzma
--enable-swscale --enable-swresample --enable-libopenh264
--enable-decoder=bink,pcm_s16le,pcm_s24le,pcm_s32le,pcm_u8,pcm_f32le,aac,h264
--enable-encoder=aac,libopenh264
--enable-demuxer=bink,wav,mov --enable-muxer=mp4,ipod
--enable-parser=aac,h264 --pkg-config-flags=--static
```

No protocol is enabled: generated FFmpeg protocol table contains only NULL. No x264, GPL codec/filter, host ffmpeg/afconvert executable, libavfilter, network, or codec download is used. AAC/H264 decoders + MOV demuxer are retained for host output verification; runtime public API only accepts BIK1 and PCM RIFF/WAVE input signatures.

OpenH264: `USE_ASM=No`, `OS=darwin ARCH=arm64` host; `OS=android ARCH=arm64 TARGET=android-28` cross build. This compiles only its static library target, not demos, Gradle, tests, or downloadable submodules. No modifications to upstream dependency source were made.

Android final link uses `-z max-page-size=16384`, `-z common-page-size=16384`, `--no-undefined`, static C++ runtime, and [oc_media.map](oc_media.map) to export only the two ABI functions and localize all FFmpeg/OpenH264/C++ symbols. This also makes upstream AArch64 assembly table references link correctly in the combined shared library. Final ELF depends only on libc/libm/libdl. ELF alignment does not establish APK ZIP alignment; packaging must check that separately.

## Redistribution

Carry [FFmpeg LGPL text](licenses/FFmpeg-LGPL-2.1.txt), [FFmpeg license description](licenses/FFmpeg-LICENSE.md), [Cisco copyright license](licenses/OpenH264-LICENSE.txt), [LLVM/NDK notices](licenses/NDK-LLVM-NOTICE.txt), and [Android cpufeatures notice](licenses/Android-cpufeatures-NOTICE.txt) with the release.

The combined native `.so` contains statically linked LGPL code. Distribution must provide the corresponding FFmpeg source/configuration and a practical rebuild/relink route for the combined library; retaining only an APK or a URL to upstream is not a complete compliance plan. This work retains exact source tarballs/extracted source, all static `.a` archives, bridge object file, generated config, and build script in the external workspace. The application must allow replacement/rebuilt library use as legally required; do not prohibit reverse engineering for debugging LGPL modifications. Final distribution/legal review belongs to the parent release task.
