#include "story_assembly.h"
#include <string.h>

int story_tune_power_range(int total, int *minimum, int *maximum) {
  if (total < 0 || total > STORY_TUNE_TOTAL || !minimum || !maximum || minimum == maximum) return 0;
  if (total <= STORY_TUNE_SELECT_AFTER) {
    *minimum = total > STORY_TUNE_BASIC_MAX ? total - STORY_TUNE_BASIC_MAX : 0;
    *maximum = total < STORY_TUNE_BASIC_MAX ? total : STORY_TUNE_BASIC_MAX;
  } else {
    *minimum = STORY_TUNE_BASIC_MAX;
    *maximum = total - STORY_TUNE_BASIC_MAX;
  }
  return 1;
}

int story_tune_allocation_valid(int total, int power, int handling) {
  int lo, hi;
  if (power < 0 || power > STORY_TUNE_MAX || handling < 0 || handling > STORY_TUNE_MAX ||
      !story_tune_power_range(total, &lo, &hi)) return 0;
  return power >= lo && power <= hi && power + handling == total;
}

int story_tune_budget(int power, int handling) {
  /* Check each bound before adding, including callers passing INT_MAX. */
  if (power < 0 || power > STORY_TUNE_MAX || handling < 0 || handling > STORY_TUNE_MAX) return -1;
  int total = power + handling;
  return story_tune_allocation_valid(total, power, handling) ? total : -1;
}

int story_tune_selectable(int power, int handling) {
  return story_tune_budget(power, handling) > STORY_TUNE_SELECT_AFTER;
}

int story_assembly_resolve(int bng_car_type, int earned_power, int earned_handling,
                           int direct_full, story_assembly *out) {
  if (!out) return 0;
  memset(out, 0, sizeof *out);
  if (bng_car_type < 0 || bng_car_type > 55 || (direct_full != 0 && direct_full != 1)) return 0;
  int p = direct_full ? STORY_TUNE_MAX : earned_power;
  int h = direct_full ? STORY_TUNE_BASIC_MAX : earned_handling;
  int total = story_tune_budget(p, h);
  if (total < 0) return 0;
  const int ucf10 = bng_car_type == 33;
  /* IsTuned 0x85689d0, pointer table0x9736ae0; clCarConstructParam
   * from card0x89438a0 routes only these flags to model assembly. */
  out->earned_total = total;
  out->muffler = p >= 2; /* TUNE_ID3: threshold2 in both columns */
  out->roll_cage = !ucf10 && h >= 8; /* ID12: normal8, UCF10=100 */
  out->suspension = ucf10 ? h >= 4 : h >= 6; /* ID8 OR ID10 */
  out->clear_tail = ucf10 && h >= 2; /* ID9 */
  out->gold_emblem = ucf10 && h >= 5; /* ID11 */
  int smoke = ucf10 && h >= 7; /* ID13 */
  int mach = ucf10 && h >= 10; /* ID14 */
  out->glass = smoke ? (mach ? 2 : 1) : 0;
  out->flags = (out->muffler ? STORY_ASSEMBLY_MUFFLER : 0u) |
               (out->roll_cage ? STORY_ASSEMBLY_ROLL_CAGE : 0u) |
               (out->suspension ? STORY_ASSEMBLY_SUSPENSION : 0u) |
               (out->clear_tail ? STORY_ASSEMBLY_CLEAR_TAIL : 0u) |
               (out->gold_emblem ? STORY_ASSEMBLY_GOLD_EMBLEM : 0u) |
               (smoke ? STORY_ASSEMBLY_GLASS_SMOKE : 0u) |
               (mach ? STORY_ASSEMBLY_MACH_STICKER : 0u);
  return 1;
}
