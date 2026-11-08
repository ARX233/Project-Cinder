# Optional original blink overlay — separate ABI2 variant

This is **additive** to the frozen ABI1 backend. Its original sources, libraries, build directories and proof outputs are unchanged. [oc_media_overlay.h](oc_media_overlay.h) introduces only an optional RGBA overlay descriptor and three versioned entry points. The separate `liboc_media_overlay.so` also exports the **unchanged original ABI1** conversion/build-info functions. It can be used alone: call original ABI1 for intro/WAV; call ABI2 for labeled playdemo/tutorial. Do not load both libraries merely to obtain the old ABI.

## Input / API

Native API accepts **no PNG paths, shell commands, Lua or executable content**. It takes caller-owned decoded straight RGBA8 bytes. The [Python helper](media_overlay_ctypes.py) decodes a parent-validated PNG **FD** using the parent's existing trusted Pillow runtime:

```python
from original_convert.native_backend.media_overlay_ctypes import (
    OverlayBackend, load_png_overlay_fd, Limits,
)
backend = OverlayBackend('/APP_NATIVE_LIB_DIR/liboc_media_overlay.so')
label = load_png_overlay_fd(png_fd, x=29, y=18,
                           other_fds=(bink_fd, wav_fd, new_partial_fd))
result = backend.convert_overlay(2, bink_fd, wav_fd, new_partial_fd,
                                 Limits(), label, cancel=is_cancelled)
# Parent publishes only if result.status == 0 and all required job recipes pass.
```

The new entry point is `oc_media_convert_overlay_fd(mode,source_fd,audio_fd,output_fd,overlay,observer,observer_opaque,limits,cancel,opaque,result)`. `overlay` may be NULL; the diagnostic observer should be NULL in production. The optional observer receives readonly before/after RGB frames plus **exact original rational** frame timestamp; it is used only for bounded sampled-frame proof. All callbacks must be nonthrowing, bounded and not mutate the buffers/descriptors. The ctypes wrapper turns a Python observer exception into cancellation rather than continuing a silently failed proof.

Only the overlay descriptor uses ABI **2** (`sizeof=48` on arm64). Existing Limits/Result remain ABI **1**, sizes **64/320**, with original semantics. Descriptor: width, height, tight RGBA stride, x/y, flags=0, exact RGBA byte count, readable const buffer. Native validates before output bytes, copies the label once, validates it again against actual video dimensions, and frees the copy after conversion. A raw C pointer must actually reference the supplied readable storage; ordinary C APIs cannot validate arbitrary invalid virtual addresses. Python retains its owned buffer until the call returns.

Limits/checks:

- PNG helper: regular readable FD; nonzero compressed size **<=1 MiB**; exact PNG signature; single frame; dimensions/pixels checked **before pixel decode**; source/audio/output inode aliases rejected. Pread preserves PNG FD offset. The parent must still resolve/open the descriptor inside its approved immutable snapshot. No PNG executable or libavcodec PNG decoder is added.
- Overlay: width **<=512**, height **<=128**, **<=65536 pixels / 262144 RGBA bytes**; tight `width*4` stride and exact byte length; nonnegative x/y; full rectangle inside actual video. No silent clipping/rescaling. RGBA/RGB memory alias rejected by pure compositor.
- Original limits still apply: FD validation/alias checks, source/output bytes, duration, frame count, resolution, monotonic deadline, cancellation/AVIO interrupt. One RGB24 video frame is <=921600 bytes. Observer adds one same-sized before-frame copy only when enabled; no full movie caching.
- Rational time: `0<=pts<=1e9`, `0<num,den<=1e9`; multiplication fits uint64. Cancellation is checked before/after composition/observer and in original I/O/frame/encode loops. It cannot preempt a single callback, filesystem syscall or codec invocation.

## Original recipe

Uses original unscaled PNGs:

| Movie | Original label | Size | Offset |
|---|---|---|---|
| playdemo | `atract_p_movie_playdemo.png` | 128x16 | (29,18) |
| tutorial | `atract_p_movie_tutorial.png` | 256x32 | (29,18) |

At exact time `T=framePTS*time_base`, opacity is `abs(1-2*frac(T))`, repeated every second. Source alpha is scaled with this value and **floored to 8-bit**, matching the 8-bit `geq` alpha assignment in the original [prepare_movie.sh](../../../../../prepare_movie.sh) recipe (FFmpeg's 8-bit `vf_geq.c` assigns evaluated values to uint8). RGB then uses rounded straight-alpha blending. Alpha is not replaced with a hard opaque box, and original antialiasing is retained.

Original Bink rates are **not exactly 30**: playdemo timebase `333333/10000000`, tutorial `166833/5000000`. Therefore frame15 has mathematical opacities `1/1000000` and `499/500000`, not exactly zero. **Both become exactly alpha8=0**, so their pre-encode RGB frames remain byte-identical. A separate exact `T=1/2` test on each real decoded movie frame + real PNG also proves zero opacity.

This closes the missing label/position/blink behavior in the optional native route. **Not bit-exact legacy filter equivalence**: composition occurs in RGB after Bink YUV→RGB conversion and returns to YUV420p; the old FFmpeg filter graph may blend in a different intermediate colorspace / 30fps image-frame timing. H264/AAC encoder settings and local completed MP4 container limitations remain as documented for ABI1. Intro must use no label. AO and full one-click job completeness remain outside this media extension.

## Proof

Workspace: `/Volumes/CodexWork/android135-original-convert-l809giqy/media-native-zWakBX/overlay-v2-4if7ph`.

Final [test source](test_overlay.py), host-only independent [frame decoder](extract_rgb_frames.c), and pure compositor [sanitizer test](test_overlay_pixels.c). All original assets were read-only; no APK, device, AVD, original main, Unicorn, Lua or original executable was run.

`proof/run-243b46e1/results.json`: **34 passing cases**, with many frame/pixel assertions per case:

- Both full original movies **with and without labels**, fully re-decoded as H264 ConstrainedBaseline profile578/Level30/640x480 + AAC-LC44.1k stereo. Frame counts remain playdemo840 / tutorial1595; decoded audio hashes are unchanged by overlay.
- At frames0/7/15/30, native before-RGB matches a separately decoded original Bink frame. Entire after-RGB matches an **independent Pillow alpha_composite reference**; observed maximum channel error **0**. Outside the (29,18) label rectangle, every pre-encode RGB byte is unchanged.
- Frame0 peak alpha255 changes 3234 RGB bytes for playdemo / 5823 for tutorial. Frame7 intermediate alpha136 / 135 is independently checked. Frame15 quantized alpha0 changes **0** bytes for each movie, and exact-half-second pure composition also changes 0 bytes.
- Final encoded sampled label crops were decoded and compared to pre-encode rendered RGB; maximum observed crop MAE across overlay samples is about **5.11/255** (lossy H264/chroma conversion, not an overlay math tolerance). Pixel-reference checks themselves are exact.
- New library's ABI1 one-second output SHA matches old library exactly: `7653d99046cdd2c00a643e47c90645df690f6c5873c8bd8c8d157886829d4887`.
- Invalid overlay ABI/struct size/dimensions/stride/byte count/null pointer/offset/flags, RGB alias/byte bounds, invalid rational times, PNG inode alias/pipe/oversize/animation, cancellation during actual composition, observer exception, output/frame/duration/resolution budgets, existing-output preservation, and explicit labeled preview.

`logs/overlay-ubsan-final.log`: a separate **128-case + exact peak/zero/large-time/alias** compositor boundary test passed with host `-fsanitize=undefined`. ASan is **not claimed passed**: this machine's Apple ASan runtime deadlocked before `main` in recursive malloc/AsanInit; the owned process was sampled (`logs/overlay-sanitizer-sample.txt`) and stopped. No compositor frame ran in that ASan process. Normal full-media tests and UBSan passed.

Zero-frame byte identity is a **pre-encode RGB** assertion. The decoded lossy MP4 can show ordinary chroma/quantization/prediction noise at the same frame, reflected in the measured crop MAE; no byte-perfect decoded-video claim is made.

Overlay outputs: playdemo **5,978,435 bytes / 840 frames / 28 s**, tutorial **9,442,137 bytes / 1595 frames / 53.219727 s**. Host-only reference used pre-existing Pillow12.0.0 and NumPy2.3.5; NumPy is a test dependency, not required by the runtime overlay helper. Pillow runtime provenance/version belongs to the parent's existing Chaquopy runtime kit. No new dependency download, PNG codec enablement, or license class was introduced. Native dependencies remain exactly the pinned LGPL FFmpeg9.0.2 + BSD OpenH2642.6.0 + NDK runtime/notices in [DEPENDENCIES.md](DEPENDENCIES.md).

## Build / artifacts

[build_overlay.py](build_overlay.py) uses the frozen ABI1 bridge object and retained dependency archives; only the new variant build directories are written. It verifies base source SHA `4fda60908417de7dbea900e8eab94534a747461ffc80ed7c814bc31a6d9158b7`, and verifies old libraries/object files remain unchanged before/after linking. The new standalone converter is an explicitly documented additive derivative of the frozen core, not a modification of that core. Future core security changes must deliberately update both implementations.

```
PYTHONPATH=/ABS/BASE_WORK/src python3 -B build_overlay.py \
  --base-work /ABS/BASE_WORK --work /ABS/OVERLAY_WORK --target host
python3 -B build_overlay.py --base-work /ABS/BASE_WORK \
  --work /ABS/OVERLAY_WORK --target android
```

Runtime candidate: `build-android/stripped/liboc_media_overlay.so`, **5.1 MiB**, SHA256 **`2e88baa7d461622f43a66b181a141d5c8f7f8bdb131e60940575e642f27888aa`**. Unstripped Android SHA **`c74dad73620ba450d0422bd445a74345e6dff9613c0e4e685253cf879744948f`**; host dylib SHA **`42adfd8bcbfa1945654454b47e0bde65fdd8566cb342328080536929dd11680e`**.

`logs/android-overlay-elf.txt`: all four LOADs p_align **0x4000**, AArch64/API28/r28, only libc/libm/libdl dependencies. `logs/android-overlay-exports.txt`: old two ABI1 + three ABI2 symbols only. No on-device execution claim; APK ZIP alignment and actual vendor playback still need parent release validation.

Retain variant objects, sources, script and base FFmpeg/static archives for LGPL corresponding-source/relink obligations, alongside existing notices. Do not distribute only the stripped library and assume that satisfies LGPL.
