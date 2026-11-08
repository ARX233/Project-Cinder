#ifndef RE3DXPLUS_TIRE_SMOKE_H
#define RE3DXPLUS_TIRE_SMOKE_H
/* Offline reconstruction of main SHA256 2e659115...: clRollUpManager type 0.
 * Own/player car only. This module never reads/writes physics or native RNG.
 * No allocation, GL, resource IO, time source, or global mutable state.
 * See REPORT.md for observed/derived facts and explicit safety adaptations. */
#include <stddef.h>
#include <stdint.h>
#define TIRE_SMOKE_MAX 50u
#define TIRE_SMOKE_LIFE 25u
#define TIRE_SMOKE_EFFECT_BYTES 0x58u

typedef struct TireSmokeInput {
    float velocity[3];      /* native SInfoCarEffect +0x30, display coordinates */
    float emitter[2][3];    /* native +0x18, +0x24; do not remap through CAR_* */
    float amount[2];        /* native +0x50, +0x54; NOT track opacity or brake */
} TireSmokeInput;
typedef struct TireSmokeParticle {
    float pos[3], direction[3];
    float alpha, fade, scale;
    unsigned age, emitter, direct;
} TireSmokeParticle;
typedef struct TireSmoke {
    TireSmokeParticle particle[TIRE_SMOKE_MAX]; /* oldest to newest */
    uint64_t owner, last_tick;
    unsigned count, phase;
    int has_tick;
} TireSmoke;
/* Float colour matches original igVec4f alpha; no byte quantization. */
typedef struct TireSmokeVertex { float pos[3], uv[2], rgba[4]; } TireSmokeVertex;

/* Decode only existing public SInfoCarEffect bytes; no engine calls, no writes
 * to input. Full failure clears output. Accept exactly this minimum prefix or
 * a larger native structure. In/out storage must not overlap. */
int tire_smoke_input_from_effect(TireSmokeInput *out, const void *effect, size_t bytes);
void tire_smoke_reset(TireSmoke *smoke);
/* One call after each completed 60 Hz native car snapshot. owner=0 or NULL
 * input clears state. Duplicate tick does nothing. Owner change, rewind, or a
 * non-consecutive tick clears old history before accepting the current tick.
 * generate=0 ages existing smoke without generating; paused callers must NOT
 * step. Reset on menu, race/movie change, teardown, or context loss. */
void tire_smoke_step(TireSmoke *smoke, uint64_t owner, uint64_t tick,
                     const TireSmokeInput *input, int generate);
/* Pure, no side effects: high-FPS and repeated mirror/main calls cannot spawn
 * or age particles. view is rigid GL-column-major world->camera. Output is
 * camera space, original FIFO order, four vertices per quad. capacity is in
 * vertices. Return value is QUAD COUNT (0..TIRE_SMOKE_MAX), NOT vertex count;
 * exactly 4*return_value vertices are written. An undersized buffer returns 0
 * without writing partial geometry. No invented distance/frustum cull or sorting;
 * GPU clipping handles coverage. */
size_t tire_smoke_vertices(const TireSmoke *smoke, const float view[16],
                           TireSmokeVertex *vertices, size_t capacity);
#endif
