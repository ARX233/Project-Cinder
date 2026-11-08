#ifndef TAIL_TRAIL_H
#define TAIL_TRAIL_H
#include <stddef.h>
#include <stdint.h>
/* Original main: TAIL_L1/TAIL_R1; paired samples max 20, new alpha .8,
 * old alpha -= .1 per update and samples at <= 0 are removed. Lamp-local +/-Y is transformed by lamp and
 * body matrices. Width w = .4 * car-ID table * dynamic distance factor;
 * .4 is not a fixed width. Caller must recover anchors and width.
 * Original draw: red, SRC_ALPHA/ONE, FUNC_ADD, depth test enabled, depth
 * writes disabled, no cull or texture. This module only produces triangles.
 * Teleport resets are a safety policy, not original proof. */
#define TAIL_TRAIL_CAPACITY 20
#define TAIL_TRAIL_MAX_VERTICES ((TAIL_TRAIL_CAPACITY - 1) * 6)
typedef struct { float x, y, z; } TailTrailVec3;
typedef struct {
    TailTrailVec3 center; /* body-local lamp center */
    TailTrailVec3 axis; /* lamp +Y transformed as body-local vector, incl. scale */
    float half_width; /* caller-supplied effective original w */
} TailTrailAnchor;
typedef struct { TailTrailVec3 edge[2][2]; float alpha; int break_before; } TailTrailSample;
typedef struct {
    TailTrailSample samples[TAIL_TRAIL_CAPACITY];
    size_t count;
    uint64_t slot_id;
    int active, break_pending;
} TailTrail;
typedef struct { TailTrailVec3 position; float rgba[4]; } TailTrailVertex;
void tail_trail_reset(TailTrail *trail);
/* Invoke exactly once per fixed physics tick, not per render frame. body maps
 * into the desired history space. slot_id includes a generation on slot reuse.
 * active=0 clears state for an inactive race or missing slot. emit=0 ages old
 * samples without inserting and starts a new strip on resumption; existing
 * strips keep fading rather than resetting on distance/facing rejection.
 * max_step is the caller's teleport cutoff in history coordinates.
 * Invalid inputs clear state; identity change/teleport clears before insertion.
 * Returns 1 for a valid tick (including emit=0), 0 when cleared. Even when
 * emit=0, valid anchors and body are required to detect discontinuities. */
int tail_trail_tick(TailTrail *trail, uint64_t slot_id, int active, int emit,
                    const TailTrailAnchor anchors[2], const float body[16],
                    float max_step);
/* lamp 0/1; independent red triangle list in sample coordinates. Returns
 * zero if insufficient output capacity, invalid arguments, or fewer than two. */
size_t tail_trail_triangles(const TailTrail *trail, unsigned lamp,
                            TailTrailVertex *out, size_t capacity);
#endif
