/* Immutable render-only assembly snapshot. The caller supplies a validated
 * exact car/model identity and PERMANENT earned progress, before race balance.
 * Never infer an owner from pack/paint; several profiles share these resources. */
#ifndef STORY_BODY_VIEW_H
#define STORY_BODY_VIEW_H
#include "story_assembly.h"
#include "story_body_height.h"
#include <string.h>

typedef struct {
  int valid, pack, type, raw_model;
  int earned_power, earned_handling, direct_full;
  story_assembly assembly;
  float body_y;
} story_body_view;

static inline int story_body_view_capture(story_body_view *out, int pack, int type,
                                         int earned_power, int earned_handling, int direct_full) {
  if (!out) return 0;
  memset(out,0,sizeof *out);
  if (pack < 0 || pack >= 55 ||
      !story_assembly_resolve(type,earned_power,earned_handling,direct_full,&out->assembly)) return 0;
  out->valid=1; out->pack=pack; out->type=type; out->raw_model=-1;
  out->earned_power=earned_power; out->earned_handling=earned_handling; out->direct_full=direct_full;
  out->body_y=story_body_height(pack,out->assembly.flags);
  return 1;
}
/* Owned/guest/network records with validated raw_model must use this exact
 * variant-aware path. A wrong-pack raw_model fails instead of guessing. */
static inline int story_body_view_capture_model(story_body_view *out, int pack, int raw_model, int type,
                                               int earned_power, int earned_handling, int direct_full) {
  if (!story_body_view_capture(out,pack,type,earned_power,earned_handling,direct_full)) return 0;
  if (!story_body_height_for_model(pack,raw_model,out->assembly.flags,&out->body_y)) {
    memset(out,0,sizeof *out); return 0;
  }
  out->raw_model=raw_model;
  return 1;
}
#endif
