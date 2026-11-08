# Original resource native media backend (ABI 1)

Real in-process FFmpeg decode/resample/scale/encode/mux; no renaming WAV/Bink suffixes. The public [C header](oc_media.h) is callable from a thin JNI adapter or from [ctypes](media_ctypes.py). This implementation includes ctypes, not a new Java/Gradle integration.

## Codec/container choice and Android boundary

- WAV → AAC-LC, 44.1 kHz, stereo, 128 kbit/s, M4A/MP4 audio container.
- Original Bink1 video + separate original PCM WAV BGM → AVC **Constrained Baseline**, YUV420p, actual SPS **Level <= 3.0**, MP4 with AAC-LC. Original dimensions and frame rate retained within even `<=640x480`, `<=30fps`; other envelopes fail closed, not silently resized. Encoder SPS is inspected before output header writing.
- H264 target bitrate is 1.8 Mbit/s with requested 2 Mbit/s maxrate, **not a strict rate cap**: OpenH264 warns that disabling frame skipping prevents strict rate control. Frame skipping is disabled to preserve the original frame count. Output-byte budget is hard.
- Official Android 9 [CDD §5.3 source](https://android.googlesource.com/platform/compatibility/cdd/+/refs/heads/pie-release/5_multimedia/5_3_video-decoding.md) says MPEG-4 support only mandates **Simple Profile Level 3**, not arbitrary 640x480. Its H264 §5.3.4 requires Baseline / Main Level 3.1 support for H264 implementations, including SD 720x480 at 30 fps. This is why the native MPEG-4 encoder was rejected and BSD OpenH264 selected. See also [supported formats](https://developer.android.com/media/platform/supported-formats) and [Android 9 CDD](https://source.android.com/docs/compatibility/9/android-9-cdd).
- Target: compliant Android 9+ arm64 handheld/media framework with AVC/AAC support. This is the standard-compatible codec route, **not a claim that every vendor device was exercised**. Parent should query `MediaCodecList` / format capability and handle playback failure. No device, AVD, APK, original main, or Unicorn execution occurred. An Android-cross-compiled `.so` is not an on-device test.

## FD ABI / caller contract

```
oc_media_convert_fd(mode, source_fd, audio_fd, output_fd,
                    &limits, cancel_callback, opaque, &result)
```

Mode 1 uses source WAV and audio_fd=-1; mode 2 uses source Bink + audio WAV. All descriptors are caller-owned seekable regular files. Caller opens source from its already validated immutable snapshot and creates the job partial with `O_CREAT|O_EXCL`; **never pass an existing published output, even if empty**. API checks regular/access flags, nonempty/bounded input, output empty + link count 1, and rejects source/output inode aliasing. It cannot retrospectively prove that a descriptor was opened O_EXCL, or guard against a caller racing writes/links; caller ownership is mandatory. Use whole files, not an FD for a subrange inside another file.

Native API accepts no paths. Custom AVIO uses pread/pwrite, preserves FD offsets, and never opens another file, spawns a process, renames, truncates, or unlinks. No FD is closed by the library. Source bytes are streamed with 32 KiB AVIO buffers, one decoded video frame at a time and a bounded audio FIFO; no complete movie is cached. Finite positive declared durations are required. Duration, width/height, video frame count, input file bytes (per input), output high-water bytes, monotonic wall time, packet/frame/resample buffers and probing are bounded.

Initialize `abi=1`, `size=sizeof(struct)` on both structs (`Limits` is 64 bytes, `Result` 320 bytes on tested arm64 ABI). Every limit must be nonzero except preview duration; duration <=1h, wall <=24h, dimensions <=4096 additional API ceilings. Output codec envelope still <=640x480. `max_duration_ms` is a **reject/failure budget**, not a truncation request. Preview is explicit `preview_duration_ms`, default 0, never used in complete recipes. Successful movie conversion stops at the shortest declared video/BGM duration (frame/sample rounding applies).

Cancel callback is also installed as libavformat interrupt. Return nonzero to stop; API returns -2, leaving only new partial bytes. Callback must be thread-safe, bounded and nonthrowing; ctypes catches Python exceptions and cancels. It must remain alive until the synchronous call returns. Callback runs in ordinary calling-thread I/O/frame loops; it cannot preempt a single codec call or blocked filesystem syscall. Wall-time checks have the same cooperative boundary.

Return 0 only after codec drain, trailer, AVIO flush and fsync. Error -1 invalid ABI/FD/format; -2 cancelled; -3 budget; -4 codec; -5 I/O. Caller publishes only result 0, never a partial. New job partials are deliberately retained on error; library does not delete anything. For transactional all-assets conversion the parent publishes the **whole job** only when all required recipes pass.

## Deliberate recipe gaps

The original [movie recipe](../../../../../prepare_movie.sh) adds blinking PNG labels at (29,18) to playdemo/tutorial, with alpha `abs(1-2*mod(T,1))`. **Overlay is not implemented**, neither decoded labels nor alpha animation. Intro is a real base video+BGM conversion, while labeled movie outputs are **not recipe-equivalent**. Do not mark full original conversion ready from this backend proof. H264 differs from the old x264 Main/CRF20 recipe; no perceptual/bit-exact parity is asserted. MP4 metadata is finalized at the tail, not `faststart`; local completed-file VideoView playback is intended, not progressive streaming.

AO is out of this module: parent is handling safe bounded extraction of the existing 214-car baker. This backend neither runs the old CLI nor spawns a compiler on Android.

## Offline build / proof

See [dependency pins and licenses](DEPENDENCIES.md), [build script](build_native.py), [host tests](test_media.py), [full decode verifier](verify_media.c), and [proof verification](verify_proof.py).

```
# Build-host only: uses official source archives; all generated files under NEW work.
python3 -B prepare_dependencies.py --work /ABS/NEW/media-work
python3 -B build_native.py --work /ABS/NEW/media-work --target host
python3 -B build_native.py --work /ABS/NEW/media-work --target android --ndk /ABS/SDK/ndk/28.0.13004108
python3 -B test_media.py --work /ABS/NEW/media-work --original-data /READ_ONLY_ORIGINAL/data
```

Host profile is macOS arm64/Apple clang; Android profile uses NDK clang19 `aarch64-linux-android28`. Build requires make and pkg-config; no Gradle/JDK task. Compiler temporaries/home/cache/logs remain under work. The verifier is a host-only C helper, not an APK executable. Build it against the retained FFmpeg static libraries, then pass its path through `verify_proof.py` (expects work/proof/verify_media).

## Retained proof location

External workspace used: `/Volumes/CodexWork/android135-original-convert-l809giqy/media-native-zWakBX`.

- `prefix-host/lib/liboc_media.dylib`: host library.
- `prefix-android/lib/liboc_media.so`: unstripped cross library; `prefix-android/stripped/liboc_media.so`: 5.1 MiB packaging candidate.
- `build-{host,android}/oc_media.o`, `prefix-*/lib/*.a`, dependency tarballs, generated config and full build logs remain available for relinking/compliance.
- `proof/run-8d5df0cd/results.json`: **19 passing assertions**, including synth mono48k→stereo44.1k, explicit preview, cancellation before/mid, duration/input/output/frame/resolution/wall budgets, ABI rejection, wrong signatures, preserving existing output, and all three full original videos + original WAV.
- `proof/run-8d5df0cd/verified.json`: successful outputs fully decoded again, codec/profile/level/frame-count checked and streaming SHA-256 identities recorded.
- `logs/android-final-elf.txt`: AArch64 ELF, NDK r28/API28 note, all four LOADs p_align 0x4000, libc/libm/libdl only. `logs/android-final-exports.txt`: only two ABI exports.
- `logs/host-final-stderr.log`: complete tests 11.37 s on this Mac; max RSS 67,141,632 bytes. This is not phone performance.
- `logs/original-wav-headers.json`: bounded header inventory of 401 original WAVs, all PCM tag1; seven channel/rate/depth classes, all in this backend's supported envelope. `proof/pcm-classes-c57c2733/results.json`: one original file per each of the seven classes converted and fully decoded (including mono/stereo 8-bit 22050/44100 and stereo16-bit28000). This is **not** a claim that all 401 files were fully transcoded.

Original full outputs: intro 1785 frames/59.5s/12,675,742 bytes; playdemo 840 frames/28s/5,936,030 bytes; tutorial 1595 frames/53.219727s/9,056,351 bytes. All decoded AVC profile 578 (ConstrainedBaseline), level30,640x480; AAC profile1(LC),44100Hz,2ch. AAC encoder priming/edit-list trimming is present; sample counts may round by a few samples at shortest boundaries. No audio sample-perfect equivalence claim.

Android candidate SHA-256: `fc9bf01c111066f8ef224ea965090a44532edcee64c4c8f838282e550e2b1845` (stripped), `040158135891e3c6157e592b20201f621ef26d893919e9771d3a721f010f494b` (unstripped). Host SHA-256: `d418a162376a91c0c88aebc94b34a0f5a3d0c6f7133462c9a15644fa7486b978`.
