/* Original-derived earned story budget and visual assembly. Pure functions only:
 * never save garage data, touch physics/RNG, or infer progress from race balance. */
#ifndef STORY_ASSEMBLY_H
#define STORY_ASSEMBLY_H
#include <stdint.h>

#define STORY_TUNE_MAX 24
#define STORY_TUNE_TOTAL 34
#define STORY_TUNE_BASIC_MAX 10
#define STORY_TUNE_SELECT_AFTER 20

/* Original-reachable point encoding: until20 neither axis exceeds10; after20
 * neither falls below10. Invalid/malformed input returns -1, never grants points. */
int story_tune_budget(int power, int handling);
/* Native mseqStory/TA/Ten/Join guard: earned total>20, not displayed HP>600. */
int story_tune_selectable(int power, int handling);
/* All legal allocations of one existing budget, 0..34. Outputs unchanged on error.
 * total<=20: max(0,total-10)..min(10,total); total>20: 10..total-10. */
int story_tune_power_range(int total, int *minimum, int *maximum);
int story_tune_allocation_valid(int total, int power, int handling);

/* These bits are model-assembly state, NOT parameters to native beforeInit. */
enum story_assembly_flag {
  STORY_ASSEMBLY_MUFFLER = 1u << 0,
  STORY_ASSEMBLY_ROLL_CAGE = 1u << 1,
  STORY_ASSEMBLY_SUSPENSION = 1u << 2,
  STORY_ASSEMBLY_CLEAR_TAIL = 1u << 3,
  STORY_ASSEMBLY_GOLD_EMBLEM = 1u << 4,
  STORY_ASSEMBLY_GLASS_SMOKE = 1u << 5,
  STORY_ASSEMBLY_MACH_STICKER = 1u << 6
};
typedef struct {
  uint32_t flags;
  int earned_total;
  int muffler; /* MUFFLER1 or MUFFLER2: zero-based selection */
  int roll_cage; /* that car/body's ROLLBAR subtree, never common geometry */
  int suspension; /* native visual body-height state only, not tyre/wheel wear or physics */
  int clear_tail; /* WINKER1 or WINKER2: zero-based selection */
  int gold_emblem; /* EMBLEM1 or EMBLEM2: zero-based */
  int glass; /* GLASS1 stock; GLASS2 smoke; GLASS3 smoke+Mach */
} story_assembly;

/* bng_car_type is original ECarType (cardb_color.type), NOT menu car index.
 * Only original BNG33 (CELSIOR/UCF10 incl taxi) uses the alternate IsTuned column.
 * Pass permanent earned values. direct_full is an explicit full-tune grant:
 * resolves like completed34 (24/10), irrespective of temporary race allocation.
 * Invalid earned state fails closed and clears output. No other wear is changed. */
int story_assembly_resolve(int bng_car_type, int earned_power, int earned_handling,
                           int direct_full, story_assembly *out);
#endif
