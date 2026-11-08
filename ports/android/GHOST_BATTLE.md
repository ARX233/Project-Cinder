# Ghost Battle — original Search UI and native replay workflow

## Cloud replay sharing in 0.6

The Android launcher has **选择资源 → 云端化身设置**. Enter an HTTPS server origin and
the operator-issued access token. Enabling this shares the driver name, vehicle
configuration and complete native recordings from finished, registered-card
Ghost matches. A connection failure leaves the recording in a bounded private
outbox. Enter Ghost mode again to retry queued uploads and refresh the directory.
Playback, ordinary local races and the per-area local crown use the same
installed resources and native engine.

The current mobile catalogue loads up to 16 recent compatible entries into
the existing level and name searches. Select a rival labelled **CLOUD REPLAY**
to race the downloaded recording. The server has paginated lists and stores
recordings beyond the current mobile window. Upload receipts acknowledge storage;
they confer neither a verified win nor a world crown.

[Start the local server and provision accounts](server/README.md). The Java
client permits HTTP only for loopback testing. Android deployments should use an
HTTPS origin with a certificate trusted by the device. The server uses the same
authenticated HTTP entry point for Time Attack. Public Time Attack results
require full input evidence and a configured trusted timing verifier; the
Android client currently sends Ghost recordings only.

## What is implemented

**Ghost Battle** retains stable game ID 4; Story=0, TenFight=1, TimeAttack=2
and live VS=3 are unchanged. The compact visual order is now
**Story / Ghost / TenFight / TimeAttack / VS**, with the original hard navigation
boundaries. Ghost uses the original arcade Target disc; live multiplayer retains
the program-owned **VS Mode** disc. Mode artwork uses measured alpha-content
bounds before aspect-preserving cover cropping, rather than stretching its padded
texture canvas. Japanese/English descriptions sit on the right.

The Ghost entry now draws the original 3DX+ four Search discs, Japanese title,
selection/ring frames and exact no-history/no-revenge replacements. Touch,
key/tap selection and Back share the same state/strict request rules. The four
original search choices are the menu's entry points.

**Current restoration:** original Search→Level/Name→Course→Rival selection now
binds 196 shipped identities and their 1,267 real recordings (1,000 distinct
payloads). All 301 empty archive slots remain unavailable: they are never converted
to invented trails or AI. Native difficulty comes from original model/tune/win
rules, not comments or class labels. Ordered repeated road areas remain intact.

The compiled default table is a **different typed source**: 120 raw metadata rows,
including eleven nonzero GUEST placeholders skipped by the original manager. Only
109 manager-eligible rows may be offered, with exact original names/styles and a
separate default-AI action. Original random-ramp/weighted-route helpers run once on
actual confirmation, never while enumerating/rendering the directory. Preparation
and PRE retain the chosen map/cookie without rerolling. The original intentional
mode-8 null-trail CRivalAI/CRivalCar branch is not a failed-recording fallback.
The combined directory therefore has at most 305 genuine rows, not 316 opponents
or 960 fabricated recordings.

Current-card local match history is recorded only from genuine terminal results,
separately for the two source kinds, card slot/model and card birth identity.
Corrupt/foreign history is retained rather than overwritten; the private v2 file
uses bounded counters/CRC and directory-fd-bound atomic publication. No incoming
revenge, cloud result or server crown is fabricated. No cloud service is deployed.

The opt-in original UI v4 family has 83 sprites/17 ANMs, 4,062,649 bytes, SHA-256
`5e57e3b9e6aeb993b4e410633c26b9e6b55e01095a6f8eadfd797ff9253ea782`.
A separately approved WGBANK2 contains exact metadata/trails and the WGPAINT1
section: 54,528,259 bytes, SHA-256
`ed2e3cc93e7a6e9e1d77a1c0fcd2fa50084a48ec5409a8b135113e5d8d429da1`.
The 148 custom-colour profiles use 29 exact body/colour keys and 87 original RGBA
pages; 120 custom-plus-vinyl profiles compose the original selected VPK plane
before GO. Two GC8 aero pages deliberately retain the original embedded-DDS
no-op outcome, not a guessed material alias. Missing model/aero/wheel/paint/vinyl
readiness cannot silently substitute a base-colour car. Draw overrides restore
shared material state; a lost exact appearance aborts before another physics tick.

Android receives only Store-minted bounded SHA-verified capabilities, with paint
inside the sixth optional namespace, not another JNI path. Legacy 15-ANM/UI and
resource-free verifier profiles, old 41-row metadata, main resource hashes and
unrelated optional trust remain unchanged. Device/GPU/pixel/physical-refresh
parity is not established by CPU source-bitmap previews or offline engine tests.

This mode uses the original interactive **CTarget (native mode 8)**, not the
CGhost story movie player, a transparent time-attack replay, an ordinary AI
replacement or a fabricated network PCB. It shares the original collision
registration/solver. Native mode 9 is Tournament, not an alternative recording
mode. Wins come from the original frozen result/rank and retirement/terminal
state, not the rival's current distance gap.

The separate **local recording/practice adapter remains ERamp 1..22, route 0**;
its legacy remote format/policy limits are not broadened. Shipped recordings use
their reviewed original frontend raw-ramp/route mapping, exact float32 target-field
helper and native StageAry/pAreaAry ordered-area validation. Their nonzero routes
are not normalized to route zero. Default source metadata deliberately has no
chosen route until its original helper selects one. A compatible same-city course
index loads graphics only; it never substitutes a TA race field. Tutorial and
normal fields remain distinct; no short recording can pose as a full-distance rival.

## Legacy local practice records

The removed Record / Challenge screen used a solo qualification race to capture
a native `070426a` trail and save it locally. Playback required the saved car,
physics cohort, ramp/route and race field. The record format is retained for
existing files and native replay tests.

The sidecar is a single most-recent valid recording named `ghost_local_v1`.
It is not a cloud catalog or per-player leaderboard. The 184-byte explicit
little-endian envelope contains the owner profile, field/ramp/route, recording
Unix timestamp, physics SHA cohort and bounded native payload. No native
pointers, compiler struct padding or heap snapshots are persisted. A different
physics cohort, unsupported version, malformed data or incompatible map is
rejected without deleting the previous recording. Current caps are 8,192
samples, 512 areas and 395,292 native payload bytes.

Length, byte-sum, CRC32, finite-value and index checks are corruption/safety
checks, **not authentication or anti-cheat**. The native loader is entered only
after the host's current native-area/field policy accepts the data. These checks
are not a complete road-topology or human-input replay verifier.

The app resolves only its trusted platform save directory to a physical root
for Ghost I/O; legacy save paths are unchanged. Storage pins each directory
component without following symlinks and accepts no caller-selected filename.
It writes a private temporary file, flushes/syncs and renames atomically. Failure
before rename preserves old bytes; `COMMITTED_UNSYNCED` explicitly means a new
file was committed but directory durability is uncertain. Existing garage,
record, option and touch-layout formats are not repurposed.

The sampler may need its next original step after the player's terminal tick.
The app may wait at most six existing fixed simulation ticks before export;
repeated presentation frames do not count. It never manufactures a final sample
or advances extra physics to make a recording appear valid. Incomplete recording
or I/O failure is reported and does not replace the previous valid recording.

## Future cloud/world-crown contract

**No cloud service is configured or deployed by this change.** World-crown
fetch/start/submission controls cannot contact an unknown endpoint or display a
fabricated king. Local wins cannot become server-verified wins by setting a
Boolean. The original local-card crown update is deliberately not copied as
server authority.

The [server reference store](<server/ghost_service.py>) and its
[contract/deployment notes](<server/README.md>) implement this rule:

- Partition kings by reviewed course/route, rules SHA and physics SHA.
- Before racing, issue an immutable challenge bound to the authenticated player,
  challenge ID, old king revision/blob SHA, rules/physics and expiry.
- Submit bounded native recording and separate input evidence with their exact
  digests. The accepted JSON schema has no `win`, `rank`, `verified`, arbitrary
  player identity or filesystem path fields.
- A **trusted server-side replay verifier** must validate the race and its full
  binding. Missing verifier, malformed evidence, failure, timeout, cancellation
  or expiry never grant a crown. The default is `UNVERIFIED` / HTTP-503 semantics.
- Verified winners replace the still-matching king in one transaction/CAS.
  Defeating an old snapshot after somebody else won may be recorded as
  `VERIFIED_WIN_STALE`, but cannot overwrite the newer king. Repeated identical
  claims return the same receipt.
- Seed the first partition only through a trusted, reviewed administration
  process, for example an audited high-level qualifying recording; clients
  cannot seize an empty partition.

The reference store is not an online service or an anti-cheat implementation.
Production auth/TLS/HTTP/blob storage, rules/physics registry, quotas/auditing,
game-side input-evidence capture/upload and an isolated original-engine replay
worker still need to be connected. A trajectory file alone is not proof of a
legitimate human race. Synthetic verifier tests establish protocol/CAS behavior,
not original-engine server validation. Synchronous verifier timeouts cannot
terminate a hung in-process adapter; production needs a killable isolated worker.

## Native build integration

The three originally disabled sampler routines are recovered by the dedicated
[private variant generator](<tools/recomp/make_ghost_variant.py>). It verifies
pinned original ELF and guarded baseline identities and refuses to overwrite
inputs or an existing output. It restores original sampling bodies/callees,
uses opaque validated memory streams, adds two bounded observation/tire hooks,
and extends only the **explicitly gated mode-6 recording-constructor branch**.
Normal four-mode recording remains disabled. This does not replace the vehicle
or Target solver, alter the 60 Hz clock or change the default rendering backend.

The separately gated compiled-default bridge additionally restores the original
owner STireDimension argument **before** the early default GetSetting copy. A new
private v7 variant adds only that handoff hook and an independent capability
marker to the preserved v6 translation; vehicle/RNG formulas are unchanged. The
[pinned default bridge generator](<tools/recomp/make_default_ghost_variant.py>)
accepts only the reviewed v6 hash, refuses existing outputs, and verifies that
removing its two additions restores the original baseline byte-for-byte. A v6
engine still lists source metadata but rejects default-AI preparation. Offline
regression compared all 1,267 recorded cases at 241 ticks using complete VM,
register/x87, heap and RNG state: v6/v7 snapshots were byte-identical. All 109×8
eligible default cases also exercised actual moving finite native AI with no
Target/sampler/recorder. These are native CPU facts, not GPU/device qualification.

Example for a developer who owns the reviewed original inputs:

```sh
python3 tools/recomp/make_ghost_variant.py \
  --baseline /path/to/reviewed/private/phys_rc.c \
  --elf /path/to/original/main \
  --output /path/to/new/private/phys_rc_ghost.c

# Set all existing resource-free build/runtime/signing prerequisites as usual.
PHYS_SOURCE=/path/to/new/private/phys_rc_ghost.c ./build_android.sh
```

The [Android build script](<build_android.sh>) includes the Ghost leaf modules
and guards a build-local physics copy, leaving the caller's private source
immutable. No private generated physics, original assets, recorded player frames
or game payload is added to the public source tree. A legacy translation still
links/runs the original four modes; its absent Ghost capability fails closed.
Simply adding a menu entry does not make the old no-record engine record.

Use a consistent `RC_FPT=double` and `-ffp-contract=off` for the generated physics
and every host physics adapter in the Android build. Do not mix FP cohorts or use
fast-math: the format validator rejects that compile mode. Cohort IDs commit to
reviewed native/generator/bridge/FP inputs, not just a filename or original ELF
hash. A future server registry must review the complete build/rules identity.

The normal script still defaults to VKcompat (`VK=1`); `VK=0` selects GLES3.
Native Vulkan remains separately staged. This implementation was source/CPU
checked across all three, but no GPU, phone, APK, visual or network deployment
qualification is implied.
