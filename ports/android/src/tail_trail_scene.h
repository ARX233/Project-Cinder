#ifndef TAIL_TRAIL_SCENE_H
#define TAIL_TRAIL_SCENE_H
#include "tail_trail_data.h"
#define TAIL_TRAIL_SCENE_CARS 4
/* One race car's camera-space history, not merely a reusable display slot. */
typedef struct {
    TailTrail trail;
    const TailTrailDataRecord *record;
    float last_origin[3];
} TailTrailSceneSlot;
typedef struct { TailTrailSceneSlot slot[TAIL_TRAIL_SCENE_CARS]; } TailTrailScene;
void tail_trail_scene_reset(TailTrailScene *scene);
/* Bare CARDB_PACKS key, never a resource path. No stock/aero fallback. */
const TailTrailDataRecord *tail_trail_scene_lookup(const char *pack, unsigned body);
/* Exactly once per returned fixed tick. Inactive/missing/invalid data clears;
 * distance/facing rejection ages old samples without inserting. identity must
 * include the race/player generation. The points keep their sampled camera
 * coordinates, so rendering applies only the main projection. */
int tail_trail_scene_tick(TailTrailScene *scene, unsigned slot, uint64_t identity,
                          int active, const char *pack, unsigned body, int roof,
                          const float model[16], const float view[16], const float eye[3]);
#endif
