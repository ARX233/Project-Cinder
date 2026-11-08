/* Session-only race balance. Never changes earned garage/story points. */
#ifndef PRE_RACE_TUNE_H
#define PRE_RACE_TUNE_H

typedef struct {
  int state; /* 0 empty, 1 editing, 2 confirmed */
  int game, maker, car;
  int base_power, base_handling;
  int power;
  int slot_bound, save_slot, save_skip; /* explicit garage/guest ownership scope */
} pre_race_tune;

void pre_race_tune_clear(pre_race_tune *t);
/* Capture a legal earned allocation with native total>20 guard in every mode.
 * A <=20 VS profile may become ready unchanged without opening this editor.
 * Failed begin clears previous state. */
int pre_race_tune_begin(pre_race_tune *t, int game, int maker, int car, int power, int handling);
/* Bind after begin at the menu/app boundary. slot=0..MENU_SAVES, skip=0/1.
 * Match before applying/taking; this detects same-car/same-tune slot switches. */
int pre_race_tune_bind_slot(pre_race_tune *t, int slot, int skip);
int pre_race_tune_slot_matches(const pre_race_tune *t, int slot, int skip);
int pre_race_tune_step(pre_race_tune *t, int delta);
int pre_race_tune_confirm(pre_race_tune *t);
/* Apply confirmed VS draft without consuming. Original budget/identity must match. */
int pre_race_tune_vs_apply(const pre_race_tune *t, int maker, int car, int *power, int *handling);
/* Consume once for a non-VS race. Always clears, even on mismatch. */
int pre_race_tune_take(pre_race_tune *t, int game, int maker, int car,
                       int base_power, int base_handling, int *power, int *handling);
#endif
