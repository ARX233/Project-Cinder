# Android tail-lamp trail integration

Status: integrated into source and the Android native source list; no APK build,
installation, release or device/GPU visual verification has been performed.
The separate multiplayer native-hang investigation remains unresolved/paused.

## Gameplay integration

- Story, Time Attack, Ghost, 10-in-a-row and VS use the effect while play state
  is 2 and the race is running. `clRaceThread::init` reads `USE_TAIL_LAMP_TRAIL`
  (0x8904037) and disables it for four-player Link/Join and Event races
  (0x8904546–0x89046e8). The port uses the frozen VS starting count for that
  rule. Countdown/loading wait, paused or closed races, result screens, menus
  and movies do not emit or draw this effect in the port.
- Sample only after a returned fixed physics tick, after CLOSED/ABORT checks.
  Rendering does not insert or age points, so extra high-refresh/mirror draws
  do not lengthen the trail. Maximum history is the retained 20 paired samples;
  each new sample starts at .8 and ages by .1 per simulated tick. A rejected
  emission starts a new strip when emission resumes: older strips keep fading,
  but no triangles bridge the interval with no emitted samples.
- Cache a previously unique immutable pack/body record, checking its key every
  tick; slot/body changes and ambiguous/missing records still fail closed.
- Only the main 3D effect pass (before blur/composition/HUD) draws trails. The
  original low/high-quality paths both use camera 0 for the draw (0x895280c,
  0x8953a36, 0x8622033). The player's trail is hidden with their car in roof
  view. Traffic is excluded by the port.
- A frozen race/player key and actual pack/body mapping identify each slot.
  New race start, suspension, slot identity/body change, missing/invalid data
  and discontinuous motion clear affected history. A camera change resets all
  history, as in `clRaceThread::race` (0x890dfe5–0x890dffa). Inactive draw gates
  also clear history.
- Rival aero uses the model actually loaded by the renderer, not just the aero
  requested in a network profile. A stock model shown after a failed aero load
  uses stock anchors; a successfully loaded aero with no reviewed anchors is
  not given invented stock anchors.

No physical state, networking protocol/profile, results, saves or tuning values
are changed by sampling or drawing. Old 1.31 peers need no new protocol fields
for this local display effect. This does not establish physics compatibility or
fix the separately investigated native non-return.

## Geometry and original data

The local ignored `src/tail_trail_private_data.h` currently contains 210 reviewed
(pack, body) records covering 54 of the 55 selectable stock packs. It was
produced by the existing strict anchor extractor and converter from the original
**brakelamp** IGBs, not guessed vehicle bounding boxes. The original main SHA-256
is `2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6`;
pack IDs and lamp paths were independently checked against its static tables.
The header SHA-256 is
`0517153c8b58336b4390ceba5b5ba8cc1dc31e6c06f98d85d26602e8da137309`.

Centers and unnormalized +Y axes come from TAIL_L1/TAIL_R1 transforms. Half-width
uses .4 times the original per-car width and the distance factor. Original
`CTailLampTrail::Main` samples lamp endpoints in main-camera space
(0x8621eab–0x8621f0a). Its inverse-current-view conversion on rebuild (0x8621744)
cancels the current view applied by `Draw` (0x8622033). The port stores each
sample in camera space and draws with just the projection. No original ELF code
or game assets were executed or modified.

Current deliberately unsupported combinations:

- `nis_KPGC10`: all four bodies (missing/unsupported named tail transforms).
- `gem_964_38RS`, `gem_964_RSR`, `gem_997_AVA`: aero B/C have no corresponding
  BodyIGB in their original Lua definitions. If the renderer actually falls
  back to a reviewed stock body, that stock body may still show the effect.
- Unknown/chara packs and any other absent/ambiguous record: no effect.

The public source builds without this private header, but then emits no trails;
it does not invent locations. Keep the reviewed private header with the source
snapshot used for a later explicitly authorized build. It is intentionally
ignored by Git, like other original-derived private data.

`clCarLampSource::update` (0x8626410) requires normalized facing dot > .6 and
selects the near limit through the current `S2DInfoMeter` play view written by
`Get2DInfoMeter` (0x8982758–0x898276d). The strict range in world units is
107–630 from the roof and 115–630 in chase view. The scale rises as
`.5 + .5 * distance / 300` until 300, then stays at 1. This logic does not use
the brake or headlight switches. The Android port samples on fixed physics ticks
and clears discontinuities over 100 units.

## Rendering isolation

`render_tail_triangles` uses a private program/VAO/VBO and float RGBA attributes.
It reuses the existing scene shader text/attribute layout and a white texture
(no new shader source or texture asset). Shader text exactly matches existing
Vulkan source dump `tools/vkprogs/78b0a0b2b3c119c2.txt`; the generated private
SPIR-V table was not built or validated in this task. Missing/nonusable shader
or allocation failure disables the optional renderer instead of the race.

The pass is additive SRC_ALPHA/ONE, depth tested LEQUAL, no depth writes,
culling, stencil, grading or fog. Caller program, VAO/attributes/EBO, array
binding, independent RGB/alpha blend factors/equations, depth/cull/stencil
settings, colour mask, texture unit 0 and active texture are preserved. FBO,
viewport and scissor are not changed. Existing GL errors are not consumed;
Vulkan uses the adapter's scoped snapshot/error epoch. Native GLES can report
submission only, not GPU completion or success via a non-consuming error query.

Resources belong to the game rendering context/device. `render_tail_release`
requires the live owning context before teardown; after actual context loss,
`render_tail_context_lost` only forgets IDs. Surface replacement/pause is not
context loss. This is not a new full-engine device-lost recovery mechanism.

## Reproducible host checks

Run individually from this Android port (host fixture compilation only):

```sh
python3 -B tests/test_tail_trail_scene.py
TAIL_RENDER_SANITIZE=undefined python3 -B tests/test_tail_render_host.py
python3 -B tests/test_vkgl_state_query_host.py
python3 -B -m unittest discover -s tools -p 'test_tail_*.py'
```

The scene fixture compiles real geometry/scene code and extracted actual app
glue. It covers fresh/changed identities, aero/actual-model fallback, absent and
ambiguous data, camera-relative positions, view changes and distance limits,
teleport, mode/lifecycle gates, independent rivals and repeated render calls
without extra aging. Car state and GPU calls are test doubles. Renderer fixtures execute
actual extracted helpers against GLES/Vulkan state models, including failure
paths and float uploads, not real drivers. The 210 installed private records
were additionally sampled/triangulated under UBSan; their float values were
compared bit-for-bit with original-derived candidates in C11 and C++17.

Closure/ABORT sentinels, selected multiplayer GO/junction/FINISHED/late-RACE
regressions, backfire/story checks, and NDK GLES/Vulkan syntax-only checks also
passed. No test result here substitutes for an explicitly authorized later APK
build and phone visual verification.
