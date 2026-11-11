#!/bin/sh
# Build Project Cinder for arm64-v8a on Android 9+ with OpenGL ES 3 and AAudio.
# Uses the SDK build-tools and NDK. VK=1 explicitly selects Vulkan.
#   ./build_cinder.sh
# External game payloads are excluded. 1.35 merges the reviewed original-converter
# code/runtime package (metadata only, no main/sprites/fonts/WAV/converted data).
# No automatic device installation or data transfer.
set -e
[ "$#" -eq 0 ] || { echo 'No arguments supported; device operations are not provided.' >&2; exit 1; }
cd "$(dirname "$0")"
: "${ANDROID_HOME:?Set ANDROID_HOME to your Android SDK}"
: "${JAVA_HOME:?Set JAVA_HOME to your JDK}"
: "${SIGNING_KEYSTORE:?Set SIGNING_KEYSTORE to your private keystore}"
[ -f "$SIGNING_KEYSTORE" ] || { echo 'Signing keystore missing' >&2; exit 1; }
SDK="$ANDROID_HOME"
export JAVA_HOME
BT="$SDK/build-tools/$(ls "$SDK/build-tools" | sort -V | tail -1)"
PLAT="$SDK/platforms/$(ls "$SDK/platforms" | sort -V | tail -1)"
NDK="$SDK/ndk/$(ls "$SDK/ndk" | sort -V | tail -1)"
HOST=$(ls "$NDK/toolchains/llvm/prebuilt" | head -1)
API=28
CC="$NDK/toolchains/llvm/prebuilt/$HOST/bin/aarch64-linux-android$API-clang"
OUT="${BUILD_OUT:-build/android}"
APK_OUT="${APK_OUT:-build/WMMT3DX-android.apk}"
[ ! -e "$OUT" ] || { echo "Refusing to overwrite existing build directory: $OUT" >&2; exit 1; }
mkdir -p "$OUT/apk/lib/arm64-v8a" "$OUT/classes" "$OUT/obj"
# Resource-free releases carry inventories only. Game material is supplied locally
# by the player; even optional sidecar fallbacks must never sneak into this APK.
[ -z "${GAME_DATA_ZIP:-}${CARD_RESOURCES:-}${STORY_CUTIN_BIN:-}${CARD_PAGES_BIN:-}${BACKFIRE_WPK:-}${BACKFIRE_BFX:-}" ] || {
  echo 'Resource-free build refuses GAME_DATA_ZIP/CARD_RESOURCES and all game sidecar inputs' >&2; exit 1;
}
: "${GAME_DATA_BASELINES_ZIP:?Set GAME_DATA_BASELINES_ZIP to reviewed inventories only}"
: "${SIDECARS_INDEX:?Set SIDECARS_INDEX to the reviewed sidecar metadata TSV}"
[ -f "$GAME_DATA_BASELINES_ZIP" ] && [ -f "$SIDECARS_INDEX" ] || { echo 'Missing inventory metadata' >&2; exit 1; }

# Explicit source-derived tables stay private and are never regenerated implicitly.
: "${TA_RANK_PRIVATE_INCLUDE:?Set TA_RANK_PRIVATE_INCLUDE to an explicitly prepared private generated directory}"
python3 - "$TA_RANK_PRIVATE_INCLUDE" "$OUT/ta-rank-private" <<'TA_RANK_INPUT_PY'
import hashlib,json,os,stat,sys
from pathlib import Path
# BEGIN TA_RANK_PINNED_INPUT_HELPERS
TA_RANK_HEADER_SHA256 = '15a12c68b1bd40f3e8cdeaeccbf4d8dc0cd2cda4f7f9655c4ea73f59c0d68457'
def ta_rank_stable_file(path, limit):
    before=path.lstat()
    def identity(s):
        return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>limit:
        raise ValueError('TA input must be a bounded regular single-link file: '+str(path))
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        opened=os.fstat(f.fileno())
        if identity(opened)!=identity(before):raise ValueError('TA input changed before read')
        data=f.read(limit+1)
        if len(data)>limit or len(data)!=opened.st_size or identity(os.fstat(f.fileno()))!=identity(opened):
            raise ValueError('TA input changed during read')
    if identity(path.lstat())!=identity(opened):raise ValueError('TA input changed after read')
    return data,{'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'stat':list(identity(opened))}
def ta_rank_read(directory, source_root):
    if not directory:raise ValueError('TA_RANK_PRIVATE_INCLUDE is required')
    path=Path(directory)
    if not path.is_absolute() or directory!=os.path.normpath(directory) or path.resolve(strict=True)!=path:
        raise ValueError('TA_RANK_PRIVATE_INCLUDE must be an absolute canonical non-symlink directory')
    if not stat.S_ISDIR(path.lstat().st_mode) or path.is_relative_to(Path(source_root).resolve(strict=True)):
        raise ValueError('Private TA generated input must be a directory outside the source snapshot')
    if os.path.lexists(Path(source_root)/'src/ta_rank_assets_private.h'):
        raise ValueError('Source-local TA header would shadow the verified private include')
    header,header_record=ta_rank_stable_file(path/'ta_rank_assets_private.h',8*1024*1024)
    if header_record['sha256']!=TA_RANK_HEADER_SHA256:raise ValueError('TA header differs from fixed reviewed SHA-256')
    proof=None;proof_record=None;proof_path=path/'ta-rank-assets-proof.json'
    if os.path.lexists(proof_path):
        proof,proof_record=ta_rank_stable_file(proof_path,1024*1024)
        if json.loads(proof)['header']['sha256']!=TA_RANK_HEADER_SHA256:
            raise ValueError('TA provenance proof/header digest mismatch')
    # Proof metadata is a retained readset, never authority to change the fixed pin.
    return header,proof,{'schema':'ta-rank-private-build-readset-v1','expected_header_sha256':TA_RANK_HEADER_SHA256,'header':header_record,'proof':proof_record}
def ta_rank_publish(inputs, directory):
    header,proof,readset=inputs;directory=Path(directory)
    directory.mkdir(mode=0o700)
    rows=[('ta_rank_assets_private.h',header),('readset.json',(json.dumps(readset,sort_keys=True,indent=2)+'\n').encode())]
    if proof is not None:rows.append(('ta-rank-assets-proof.json',proof))
    for name,data in rows:
        fd=os.open(str(directory/name),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    fd=os.open(str(directory),os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    return directory
# END TA_RANK_PINNED_INPUT_HELPERS
ta_rank_publish(ta_rank_read(sys.argv[1],Path.cwd()),Path(sys.argv[2]))
TA_RANK_INPUT_PY

# The three independently reviewed vehicle tables remain private. This is not
# a directory include: validate/copy only these exact pinned files to owned output.
: "${VEHICLE_RESTORE_PRIVATE_INCLUDE:?Set VEHICLE_RESTORE_PRIVATE_INCLUDE to the reviewed private vehicle-header directory}"
python3 - "$VEHICLE_RESTORE_PRIVATE_INCLUDE" "$OUT/vehicle-restore-private" <<'VEHICLE_RESTORE_INPUT_PY'
import hashlib,json,os,stat,sys
from pathlib import Path
# BEGIN VEHICLE_RESTORE_PINNED_INPUT_HELPERS
VEHICLE_RESTORE_HEADERS = {
    'body_color_assets_private.h': '9d400fbcbb480579afd1dcf759a4ffae07cf1a9adbedfa78a5c1727e504ecb87',
    'player_paint_profile_private.h': '88631bfff65ae050881d85d71b73783b1eed11f5972a53dbdbd94a8d00c59075',
    'player_paint_model_profile_private.h': '92093cfb799b19f73877a9590d8f3bf6154928e39c9cdc77a2074deee5ae8957',
}
VEHICLE_RESTORE_MAX_HEADER_BYTES = 8 * 1024 * 1024

def vehicle_restore_identity(s):
    return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_uid,s.st_gid,
            s.st_size,s.st_mtime_ns,s.st_ctime_ns)

def vehicle_restore_stable_file(directory_fd, directory, name):
    before=os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or
            not 0<before.st_size<=VEHICLE_RESTORE_MAX_HEADER_BYTES):
        raise ValueError('Vehicle input must be a bounded regular single-link file: '+str(directory/name))
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory_fd)
    with os.fdopen(fd,'rb') as f:
        opened=os.fstat(f.fileno())
        if vehicle_restore_identity(opened)!=vehicle_restore_identity(before):
            raise ValueError('Vehicle input changed before read')
        data=f.read(VEHICLE_RESTORE_MAX_HEADER_BYTES+1)
        if (len(data)!=opened.st_size or len(data)>VEHICLE_RESTORE_MAX_HEADER_BYTES or
                vehicle_restore_identity(os.fstat(f.fileno()))!=vehicle_restore_identity(opened)):
            raise ValueError('Vehicle input changed during read')
    after=os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
    if vehicle_restore_identity(after)!=vehicle_restore_identity(opened):
        raise ValueError('Vehicle input changed after read')
    digest=hashlib.sha256(data).hexdigest()
    if digest!=VEHICLE_RESTORE_HEADERS[name]:
        raise ValueError('Vehicle header differs from fixed reviewed SHA-256: '+name)
    return data,{'path':str(directory/name),'sha256':digest,'bytes':len(data),
                 'stat':list(vehicle_restore_identity(opened))}

def vehicle_restore_read(directory, source_root):
    if not isinstance(directory,str) or not directory:
        raise ValueError('VEHICLE_RESTORE_PRIVATE_INCLUDE is required')
    path=Path(directory);source=Path(source_root).resolve(strict=True)
    if (not path.is_absolute() or directory!=os.path.normpath(directory) or
            path.resolve(strict=True)!=path):
        raise ValueError('VEHICLE_RESTORE_PRIVATE_INCLUDE must be an absolute canonical non-symlink directory')
    before=path.lstat()
    if not stat.S_ISDIR(before.st_mode) or path.is_relative_to(source):
        raise ValueError('Private vehicle generated input must be a directory outside the source snapshot')
    for name in VEHICLE_RESTORE_HEADERS:
        for parent in (source,source/'src'):
            if os.path.lexists(parent/name):
                raise ValueError('Source-local vehicle header would shadow the verified private include: '+name)
    # Anchoring reads to the verified directory prevents following a substituted
    # parent path. The complete pathname and directory stat are rechecked too.
    fd=os.open(str(path),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        if vehicle_restore_identity(os.fstat(fd))!=vehicle_restore_identity(before):
            raise ValueError('Vehicle include directory changed before open')
        headers={};records={}
        for name in VEHICLE_RESTORE_HEADERS:
            headers[name],records[name]=vehicle_restore_stable_file(fd,path,name)
        if (vehicle_restore_identity(os.fstat(fd))!=vehicle_restore_identity(before) or
                vehicle_restore_identity(path.lstat())!=vehicle_restore_identity(before) or
                path.resolve(strict=True)!=path):
            raise ValueError('Vehicle include directory changed during read')
    finally:os.close(fd)
    return headers,{'schema':'vehicle-restore-private-build-readset-v1',
                    'expected_header_sha256':dict(VEHICLE_RESTORE_HEADERS),
                    'headers':records,'source_root':str(source),
                    'directory_stat':list(vehicle_restore_identity(before))}

def vehicle_restore_publish(inputs, directory):
    headers,readset=inputs
    if (set(headers)!=set(VEHICLE_RESTORE_HEADERS) or
            readset.get('schema')!='vehicle-restore-private-build-readset-v1' or
            readset.get('expected_header_sha256')!=VEHICLE_RESTORE_HEADERS or
            set(readset.get('headers',{}))!=set(VEHICLE_RESTORE_HEADERS)):
        raise ValueError('Invalid vehicle private build capability')
    for name,digest in VEHICLE_RESTORE_HEADERS.items():
        data=headers[name];record=readset['headers'][name]
        if (not isinstance(data,bytes) or hashlib.sha256(data).hexdigest()!=digest or
                record.get('sha256')!=digest or record.get('bytes')!=len(data)):
            raise ValueError('Vehicle private capability changed before publication')
    directory=Path(directory);directory.mkdir(mode=0o700)
    fd=os.open(str(directory),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        # Only the newly created directory/files are normalized, never inputs.
        os.fchmod(fd,0o700)
        rows=[*headers.items(),('readset.json',(json.dumps(readset,sort_keys=True,indent=2)+'\n').encode())]
        for name,data in rows:
            child=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=fd)
            with os.fdopen(child,'wb') as f:
                os.fchmod(f.fileno(),0o600);f.write(data);f.flush();os.fsync(f.fileno())
        os.fsync(fd)
    finally:os.close(fd)
    return directory
# END VEHICLE_RESTORE_PINNED_INPUT_HELPERS
vehicle_restore_publish(vehicle_restore_read(sys.argv[1],Path.cwd()),Path(sys.argv[2]))
VEHICLE_RESTORE_INPUT_PY

# the programs' SPIR-V for Vulkan (tools/vkglsl.py) from their sources (tools/vkprogs: a new
# one the game meets is written to the phone's save folder, <key>.txt, to put there), by the
# NDK's glslc unless there is a glslangValidator
VK="${VK:-0}"
NATIVE_VK="${NATIVE_VK:-0}"
case "$NATIVE_VK" in
  0|1) ;;
  *) echo 'NATIVE_VK must be 0 or 1' >&2; exit 1 ;;
esac
[ "$NATIVE_VK" = 0 ] || [ "$VK" = 1 ] || { echo 'Native packets require VK=1' >&2; exit 1; }
if [ "$VK" = 1 ]; then
  GLSLC="$NDK/shader-tools/$HOST/glslc"
  if ! command -v glslangValidator >/dev/null 2>&1 && [ -x "$GLSLC" ]; then export VKGLSL_CC="$GLSLC"; fi
  if [ ! -f src/vkgl_spv.c ] || python3 -c 'from pathlib import Path; import sys; out=Path("src/vkgl_spv.c").stat().st_mtime_ns; inputs=[Path("tools/vkglsl.py"),*Path("tools/vkprogs").rglob("*")]; sys.exit(0 if any(p.is_file() and p.stat().st_mtime_ns>out for p in inputs) else 1)'; then
    echo "the programs to SPIR-V..."
    python3 tools/vkglsl.py table tools/vkprogs src/vkgl_spv.c
  fi
  GFX="-DWMMT_VK src/vkgl.c src/vkgl_spv.c"
  # Staged native packet renderer. Not the default and not native-complete until
  # all production draw/pass/resource paths and hardware behavior are verified.
  [ "$NATIVE_VK" = 0 ] || GFX="$GFX -DWMMT_NATIVE_VK"
  GFX_LIBS="-lvulkan"
else
  GFX=""
  GFX_LIBS="-lEGL -lGLESv2"
fi

# The diagnostic build is opt-in; release builds do not record game events.
DEBUG_LOG="${DEBUG_LOG:-0}"
case "$DEBUG_LOG" in
  0) DEBUG_FLAGS=""; DEBUG_SRC="" ;;
  1) DEBUG_FLAGS="-DWMMT_DEBUG_LOG -DWMMT_LOG_BUILD_CODE=${VERSION_CODE:-2}"; DEBUG_SRC="src/debug_log.c" ;;
  *) echo 'DEBUG_LOG must be 0 or 1' >&2; exit 1 ;;
esac

# the native library: the game as on iOS, with main_android.c for main.m and sound_ios.m
# The generated physics is kept locally; clamp its one unbounded section walk each build
# (idempotent, and a no-op once guarded) so an older copy cannot bring the crash back.
if [ -f src/phys/phys_rc.c ]; then python3 tools/recomp/guard_sections.py src/phys/phys_rc.c; fi
if [ ! -f "$OUT/obj/phys_rc.o" ] || [ src/phys/phys_rc.c -nt "$OUT/obj/phys_rc.o" ]; then
  echo "compiling the arcade physics (takes a minute)..."
  $CC -O2 -fPIC -ffp-contract=off -DRC_FPT=double -w -c src/phys/phys_rc.c -o "$OUT/obj/phys_rc.o"
fi
$CC -O2 -fPIC -shared -std=gnu11 -ffp-contract=off -fno-fast-math -Wall -Wno-unused-function -DRC_FPT=double -DWMMT_EGL $DEBUG_FLAGS $GFX \
  -mcpu=cortex-a73 -I "$OUT/ta-rank-private" -I "$OUT/vehicle-restore-private" \
  src/main_android.c src/app.c src/ta_rank.c src/story_evidence.c src/pre_race_tune.c src/story_assembly.c src/junction_ui.c src/junction_barrier.c src/render.c src/hud.c src/car.c src/ghost_format.c src/ghost_runtime.c src/ghost_store.c src/ghost_catalog.c src/ghost_paint.c src/app_ghost_paint.c src/player_paint.c src/app_player_paint.c src/player_body_paint.c src/collide.c src/sound.c src/anm.c src/menu.c \
  src/lights.c src/spark.c src/tire_smoke.c src/tail_trail.c src/tail_trail_scene.c src/backfire.c src/backfire_wpk.c src/net.c src/vs_session.c src/vs_election.c src/vs_socket.c src/vs_host.c src/title.c src/gk.c \
  src/phys/rc_runtime.c $DEBUG_SRC "$OUT/obj/phys_rc.o" \
  -o "$OUT/apk/lib/arm64-v8a/libwmmt.so" \
  -landroid $GFX_LIBS -laaudio -llog -lz -lm -Wl,-z,max-page-size=16384,-z,common-page-size=16384

# Merge only the approved code/runtime/metadata package. No arbitrary directory
# copy, duplicate proof classes, game payloads or replacement of libwmmt.so.
: "${ORIGINAL_RUNTIME_PACKAGE:?Set ORIGINAL_RUNTIME_PACKAGE to build_original_runtime.py output}"
: "${CINDER_ARTWORK_PACKAGE:?Set CINDER_ARTWORK_PACKAGE to reviewed build_cinder_artwork.py output}"
: "${CINDER_EXPECTED_LAUNCHER:?Set CINDER_EXPECTED_LAUNCHER to independently compiled resource inventory}"
python3 - "$ORIGINAL_RUNTIME_PACKAGE" "$OUT/apk" <<'PY'
from pathlib import Path
import hashlib,os,stat,sys
sys.path.insert(0,'tools')
from verify_original_convert_apk import runtime_inventory
root=Path(sys.argv[1]).resolve(strict=True);dest=Path(sys.argv[2]).resolve(strict=True)
rows,_=runtime_inventory(root/'packaging-allowlist.json')
for name,entry in rows.items():
    source=root/name;target=dest/name
    if source.is_symlink() or not stat.S_ISREG(source.stat().st_mode):raise SystemExit('Unsafe runtime input: '+name)
    target.parent.mkdir(parents=True,exist_ok=True)
    h=hashlib.sha256();count=0
    with source.open('rb') as src,target.open('xb') as out:
        while block:=src.read(131072):h.update(block);count+=len(block);out.write(block)
    if count!=entry.size or h.hexdigest()!=entry.sha256:raise SystemExit('Runtime input pin mismatch: '+name)
PY
RUNTIME_CLASSES="$ORIGINAL_RUNTIME_PACKAGE/jars/runtime-classes.jar"
RUNTIME_JAVA="$ORIGINAL_RUNTIME_PACKAGE/jars/chaquopy-java-17.2.0.jar"
[ -f "$RUNTIME_CLASSES" ] && [ -f "$RUNTIME_JAVA" ] || { echo 'Missing deduplicated runtime Java jars' >&2; exit 1; }
# the Java side; only production sources, never actor test/stub/proof jars.
"$JAVA_HOME/bin/javac" -source 8 -target 8 -nowarn -classpath "$PLAT/android.jar:$RUNTIME_CLASSES:$RUNTIME_JAVA" -d "$OUT/classes" \
  android/java/com/wmmt/port/LauncherDialog.java \
  android/java/com/wmmt/port/LauncherWallpaperView.java android/java/com/wmmt/port/MainActivity.java android/java/com/wmmt/port/GhostCloud.java android/java/com/wmmt/port/CloudDevice.java android/java/com/wmmt/port/CardResources.java android/java/com/wmmt/port/ArcadeBgm.java android/java/com/wmmt/port/DebugLogStorage.java \
  android/java/com/wmmt/port/DataManifest.java android/java/com/wmmt/port/DataOverlay.java android/java/com/wmmt/port/DataCoordinator.java android/java/com/wmmt/port/DataBaselines.java \
  android/java/com/wmmt/port/ResourceMetadata.java android/java/com/wmmt/port/SafeResourceZip.java android/java/com/wmmt/port/ResourceStore.java \
  android/java/com/wmmt/port/OriginalProfile.java android/java/com/wmmt/port/OriginalProfilePin.java android/java/com/wmmt/port/OriginalJobStore.java \
  android/java/com/wmmt/port/OriginalSourceBroker.java android/java/com/wmmt/port/OriginalRuntime.java android/java/com/wmmt/port/OriginalRuntimeContext.java \
  android/java/com/wmmt/port/OriginalConversionService.java android/java/com/wmmt/port/OriginalConversionController.java
"$JAVA_HOME/bin/jar" cf "$OUT/program.jar" -C "$OUT/classes" .
"$BT/d8" --min-api $API --lib "$PLAT/android.jar" --output "$OUT/apk" "$OUT/program.jar" "$RUNTIME_CLASSES" "$RUNTIME_JAVA"
mkdir -p "$OUT/baseline-check" "$OUT/apk/assets"
"$JAVA_HOME/bin/javac" -source 8 -target 8 -nowarn -classpath "$OUT/classes" -d "$OUT/baseline-check" tools/DataBaselineCompiler.java tools/ResourceMetadataCheck.java
"$JAVA_HOME/bin/java" -cp "$OUT/classes:$OUT/baseline-check" DataBaselineCompiler --check "$GAME_DATA_BASELINES_ZIP"
"$JAVA_HOME/bin/java" -cp "$OUT/classes:$OUT/baseline-check" ResourceMetadataCheck "$SIDECARS_INDEX"
cp "$GAME_DATA_BASELINES_ZIP" "$OUT/apk/assets/data-baselines.zip"
cp "$SIDECARS_INDEX" "$OUT/apk/assets/sidecars-index-v1.tsv"
cmp "$GAME_DATA_BASELINES_ZIP" "$OUT/apk/assets/data-baselines.zip"
cmp "$SIDECARS_INDEX" "$OUT/apk/assets/sidecars-index-v1.tsv"

# the manifest and icon, then the apk, aligned and signed with a key of its own
python3 - "$CINDER_ARTWORK_PACKAGE" "$OUT" <<'ART'
from pathlib import Path
import hashlib,json,stat,sys
root=Path(sys.argv[1]).resolve(strict=True);dest=Path(sys.argv[2]).resolve(strict=True)
obj=json.loads((root/'artwork-manifest.json').read_text())
expected={'res/mipmap/icon.png','res/drawable-nodpi/cinder_icon_foreground.png','res/mipmap-anydpi-v26/icon.xml','res/values/colors.xml','assets/original-convert/launcher-wallpaper.jpg'}
if obj.get('schema')!='project-cinder-artwork-v1' or len(obj.get('files',[]))!=5 or {r['path'] for r in obj['files']}!=expected:raise SystemExit('Unapproved Cinder artwork inventory')
for row in obj['files']:
    name=row['path'];source=root/name
    if source.is_symlink() or not stat.S_ISREG(source.stat().st_mode):raise SystemExit('Unsafe artwork source')
    data=source.read_bytes()
    if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise SystemExit('Artwork SHA mismatch')
    if name.startswith('assets/') and row['sha256']!='2fcfa2aeeae006fc3cd10a9eafd73c577ca3657312ac9fbfb063a3bddf46054e':raise SystemExit('Wallpaper not user-approved')
    target=dest/('apk/'+name if name.startswith('assets/') else name);target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as f:f.write(data)
ART
"$BT/aapt2" compile --dir "$OUT/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/base.apk" -I "$PLAT/android.jar" --manifest android/ProjectCinderManifest.xml \
  --min-sdk-version $API --target-sdk-version 36 --version-code "${VERSION_CODE:-2}" --version-name "${VERSION_NAME:-0.2}" "$OUT/res.zip"
# (the library stored, not deflated, and page-aligned: it is mapped from the apk as it is)
(cd "$OUT/apk" && zip -q ../base.apk classes.dex && zip -q -0 -r ../base.apk lib)
# Exact metadata-only asset set; never discover game files from data/ as fallbacks.
(cd "$OUT/apk" && zip -q -0 -r ../base.apk assets)
"$BT/zipalign" -f -P 16 4 "$OUT/base.apk" "$OUT/aligned.apk"
[ ! -e "$APK_OUT" ] || { echo "Refusing to overwrite existing APK: $APK_OUT" >&2; exit 1; }
# A private caller may supply both passwords by environment reference; otherwise
# apksigner prompts interactively. Never embed passwords or print them here.
if [ "${WMMT_KS_PASS+x}" = x ] || [ "${WMMT_KEY_PASS+x}" = x ]; then
  [ "${WMMT_KS_PASS+x}" = x ] && [ "${WMMT_KEY_PASS+x}" = x ] || { echo 'Both signing password references are required' >&2; exit 1; }
  "$BT/apksigner" sign --ks "$SIGNING_KEYSTORE" --ks-pass env:WMMT_KS_PASS --key-pass env:WMMT_KEY_PASS --out "$APK_OUT" "$OUT/aligned.apk"
else
  "$BT/apksigner" sign --ks "$SIGNING_KEYSTORE" --out "$APK_OUT" "$OUT/aligned.apk"
fi
python3 tools/verify_cinder_apk.py "$APK_OUT" --expected-launcher "$CINDER_EXPECTED_LAUNCHER" --expected-runtime "$ORIGINAL_RUNTIME_PACKAGE/packaging-allowlist.json" --expected-baselines "$GAME_DATA_BASELINES_ZIP" --expected-sidecars "$SIDECARS_INDEX"
echo "built $APK_OUT"
