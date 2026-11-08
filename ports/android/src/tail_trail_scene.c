#include "tail_trail_scene.h"
#include "mathx.h"
#include <math.h>
#include <string.h>
#if defined(__has_include)
# if __has_include("tail_trail_private_data.h")
#  include "tail_trail_private_data.h"
# endif
#endif

void tail_trail_scene_reset(TailTrailScene *scene) {
    if (scene) memset(scene, 0, sizeof(*scene));
}
const TailTrailDataRecord *tail_trail_scene_lookup(const char *pack, unsigned body) {
    if (!pack || !pack[0] || body > 3) return NULL;
#ifdef TAIL_TRAIL_DATA_COUNT
    const TailTrailDataRecord *found = NULL;
    for (size_t i = 0; i < TAIL_TRAIL_DATA_COUNT; ++i) {
        if (tail_trail_data[i].body == body && !strcmp(pack, tail_trail_data[i].pack)) {
            if (found) return NULL; /* ambiguous private mapping is never guessed */
            found = &tail_trail_data[i];
        }
    }
    return found;
#else
    return NULL; /* public/source-only builds do not invent lamp locations */
#endif
}
static int affine(const float m[16]) {
    if (!m) return 0;
    for (int i = 0; i < 16; ++i) if (!isfinite(m[i])) return 0;
    return m[3] == 0 && m[7] == 0 && m[11] == 0 && m[15] == 1;
}
int tail_trail_scene_tick(TailTrailScene *scene, unsigned index, uint64_t identity,
                          int active, const char *pack, unsigned body, int roof,
                          const float model[16], const float view[16], const float eye[3]) {
    if (!scene || index >= TAIL_TRAIL_SCENE_CARS) return 0;
    TailTrailSceneSlot *slot = &scene->slot[index];
    /* Private metadata is immutable. A previously unique hit can be reused,
     * but compare the actual key each tick: slot/body changes must still reset.
     * Never cache an ambiguous/missing lookup as a guessed stock record. */
    const TailTrailDataRecord *record = NULL;
    if (active) {
        if (slot->record && pack && slot->record->body == body &&
            !strcmp(slot->record->pack, pack)) record = slot->record;
        else record = tail_trail_scene_lookup(pack, body);
    }
    if (!record || !identity || !affine(model) || !affine(view) || !eye ||
        !isfinite(eye[0]) || !isfinite(eye[1]) || !isfinite(eye[2]) ||
        !isfinite(record->width_scale) || record->width_scale <= 0 || record->width_scale > 100) {
        memset(slot, 0, sizeof(*slot)); return 0;
    }
    const float max_step = 100.0f; /* port guard for a discontinuous world pose */
    double world_step2 = 0;
    for (int i = 0; i < 3; ++i) {
        double step = (double)model[12+i] - slot->last_origin[i];
        world_step2 += step * step;
    }
    if (slot->record != record || world_step2 > max_step * max_step)
        tail_trail_reset(&slot->trail);
    slot->record = record;
    memcpy(slot->last_origin, model + 12, sizeof slot->last_origin);
    /* clCarLampSource::update (8626599..862670b): normalize the body's +Z
     * and camera's -Z and emit only for dot > .6. The workspace branch reads
     * the current S2DInfoMeter's PLAY_VIEW (0 roof, 1 behind), which selects
     * the near cutoff. Scale=300 and far=630 are shared by both views. */
    double norm_body = 0, norm_view = 0, dot = 0, d2 = 0;
    for (int i = 0; i < 3; ++i) {
        double b = model[8+i], v = -view[2+4*i];
        double d = (double)model[12+i] - eye[i];
        norm_body += b*b; norm_view += v*v; dot += b*v; d2 += d*d;
    }
    if (!(norm_body > 0) || !(norm_view > 0) || !isfinite(d2)) {
        memset(slot, 0, sizeof(*slot)); return 0;
    }
    float distance = (float)sqrt(d2);
    float factor = distance > 300.0f ? 1.0f : .5f + .5f * (distance / 300.0f);
    int emit = isfinite(distance) && distance > (roof ? 107.0f : 115.0f) && distance < 630.0f &&
               dot / sqrt(norm_body * norm_view) > (double).6f;
    TailTrailAnchor anchors[2];
    for (int i = 0; i < 2; ++i) {
        anchors[i].center = record->center[i]; anchors[i].axis = record->axis[i];
        anchors[i].half_width = .4f * record->width_scale * factor;
    }
    /* CTailLampTrail::Main stores endpoints after applying the current view.
     * Its inverse-current-view conversion at rebuild cancels Draw's view
     * transform. Retain the sampled view-space positions directly here. */
    mat4 world, camera;
    memcpy(world.m, model, sizeof world.m);
    memcpy(camera.m, view, sizeof camera.m);
    mat4 lamp_view = mat4_mul(camera, world);
    return tail_trail_tick(&slot->trail, identity, 1, emit, anchors, lamp_view.m, max_step);
}
