#include "pre_race_tune.h"
#include "story_assembly.h"
#include "menu.h"
#include <string.h>

void pre_race_tune_clear(pre_race_tune *t) {
  if (t) { memset(t, 0, sizeof *t); t->save_slot = -1; }
}

static int game_valid(int game) {
  return game == MENU_GAME_STORY || game == MENU_GAME_TEN || game == MENU_GAME_TA || game == MENU_GAME_VS || game == MENU_GAME_GHOST;
}

static int draft_valid(const pre_race_tune *t) {
  if (!t || !game_valid(t->game) || t->maker < 0 || t->car < 0 ||
      !story_tune_selectable(t->base_power, t->base_handling)) return 0;
  const int total = t->base_power + t->base_handling;
  /* Check the bounded power before subtracting it, even for corrupted state. */
  return t->power >= 0 && t->power <= STORY_TUNE_MAX &&
         story_tune_allocation_valid(total, t->power, total - t->power);
}

int pre_race_tune_begin(pre_race_tune *t, int game, int maker, int car, int power, int handling) {
  if (!t) return 0;
  pre_race_tune_clear(t);
  if (!game_valid(game) || maker < 0 || car < 0 || !story_tune_selectable(power, handling)) return 0;
  t->state = 1;
  t->game = game; t->maker = maker; t->car = car;
  t->base_power = power; t->base_handling = handling; t->power = power;
  return 1;
}

int pre_race_tune_bind_slot(pre_race_tune *t, int slot, int skip) {
  if (!t || (t->state != 1 && t->state != 2) || !draft_valid(t) ||
      slot < 0 || slot > MENU_SAVES || (skip != 0 && skip != 1)) return 0;
  /* A confirmed selection cannot be rebound to another owner. */
  if (t->slot_bound && (t->save_slot != slot || t->save_skip != skip)) return 0;
  t->slot_bound = 1; t->save_slot = slot; t->save_skip = skip;
  return 1;
}

int pre_race_tune_slot_matches(const pre_race_tune *t, int slot, int skip) {
  return t && (t->state == 1 || t->state == 2) && t->slot_bound == 1 &&
         t->save_slot == slot && t->save_skip == skip &&
         slot >= 0 && slot <= MENU_SAVES && (skip == 0 || skip == 1) && draft_valid(t);
}

int pre_race_tune_step(pre_race_tune *t, int delta) {
  if (!t || t->state != 1 || (delta != -1 && delta != 1) || !draft_valid(t)) return 0;
  const int power = t->power + delta;
  const int total = t->base_power + t->base_handling;
  if (!story_tune_allocation_valid(total, power, total - power)) return 0;
  t->power = power;
  return 1;
}

int pre_race_tune_confirm(pre_race_tune *t) {
  if (!t || t->state != 1 || !draft_valid(t)) return 0;
  t->state = 2;
  return 1;
}

int pre_race_tune_vs_apply(const pre_race_tune *t, int maker, int car, int *power, int *handling) {
  if (!t || !power || !handling || power == handling || t->state != 2 || t->game != MENU_GAME_VS ||
      t->maker != maker || t->car != car || t->base_power != *power || t->base_handling != *handling ||
      !draft_valid(t)) return 0;
  const int total = t->base_power + t->base_handling;
  *power = t->power; *handling = total - t->power;
  return 1;
}

int pre_race_tune_take(pre_race_tune *t, int game, int maker, int car,
                       int base_power, int base_handling, int *power, int *handling) {
  if (!t) return 0;
  int ok = t->state == 2 && game_valid(game) && game != MENU_GAME_VS &&
           t->game == game && t->maker == maker && t->car == car &&
           t->base_power == base_power && t->base_handling == base_handling &&
           power && handling && power != handling && draft_valid(t);
  if (ok) { *power = t->power; *handling = t->base_power + t->base_handling - t->power; }
  pre_race_tune_clear(t);
  return ok;
}
