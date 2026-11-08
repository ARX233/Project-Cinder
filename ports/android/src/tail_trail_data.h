#ifndef TAIL_TRAIL_DATA_H
#define TAIL_TRAIL_DATA_H

#include "tail_trail.h"

/* Format only: private generated data is supplied separately. pack is a bare
 * CARDB_PACKS key (no cars/ prefix or extension); body is 0 stock, 1..3 aero A..C.
 * Lamp order is TAIL_L1, TAIL_R1. center and axis are body-local; axis
 * includes the lamp transform's scale. width_scale is the original car-ID
 * table value before the .4 and dynamic distance factors. A (pack,body) pair
 * must be unique. Records with missing provenance must not be emitted. */
typedef struct {
  const char *pack;
  unsigned body;
  TailTrailVec3 center[2];
  TailTrailVec3 axis[2];
  float width_scale;
} TailTrailDataRecord;

/* Optional tail_trail_private_data.h supplies a nonempty static const
 * TailTrailDataRecord tail_trail_data[] and TAIL_TRAIL_DATA_COUNT as its
 * sizeof-derived element count. It must include this header itself. */
#endif
