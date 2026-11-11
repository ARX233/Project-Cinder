#include <assert.h>
#include "mileage_style.h"

int main(void) {
  assert(mileage_aura_level(4999999.9) == -1);
  assert(mileage_aura_level(5000000) == 0);
  const double cut[] = {10000000, 30000000, 100000000, 500000000};
  for (int i = 0; i < 4; ++i) {
    assert(mileage_aura_level(cut[i] + 999) == i);
    assert(mileage_aura_level(cut[i] + 1000) == i + 1);
  }
  assert(mileage_aura_level(INFINITY) == -1);
  assert(mileage_aura_color(0) == 0);
  assert(mileage_aura_color(mileage_style_encode(0, 6)) == 1);
  assert(mileage_aura_color(mileage_style_encode(0, 0)) == 2);
  assert(mileage_aura_color(mileage_style_encode(6, 0)) == 3);
  assert(mileage_style_encode(7, 0) == 0);

  mileage_style_log log;
  mileage_style_reset(&log);
  assert(mileage_style_commit(0, &log) == mileage_style_encode(4, 4));
  for (int event = 0; event < 3; ++event) {
    mileage_style_contact(&log, 1, 1, 2400);
    mileage_style_contact(&log, 1, 2, 500); /* weaker kind ignored */
    mileage_style_contact(&log, 1, 0, 900);
    for (int i = 0; i < 9; ++i) mileage_style_contact(&log, 0, 0, 0);
    assert(log.contact_force == event * 2500);
    mileage_style_contact(&log, 0, 0, 0);
    assert(log.contact_force == (event + 1) * 2500);
  }
  log.wall_ticks = 31;
  assert(mileage_style_commit(0, &log) == mileage_style_encode(2, 2));
  assert(mileage_aura_color(mileage_style_commit(0, &log)) == 2);
  return 0;
}
