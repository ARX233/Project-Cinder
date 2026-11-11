#ifndef MILEAGE_STYLE_H
#define MILEAGE_STYLE_H

#include <math.h>
#include <stdint.h>

/* The 3DX+ card stores two positions on a 7 x 7 chart. Zero in a Cinder
 * garage is the absent record, which resolves to the arcade's center. */
static inline unsigned mileage_style_encode(int contact, int wall) {
  if (contact < 0 || contact > 6 || wall < 0 || wall > 6) return 0;
  return 1 + (unsigned)(contact * 7 + wall);
}

static inline void mileage_style_decode(unsigned value, int *contact, int *wall) {
  unsigned cell = value >= 1 && value <= 49 ? value - 1 : 24;
  *contact = (int)(cell / 7);
  *wall = (int)(cell % 7);
}

/* nsMenuCheck::checkAura: green, purple, red and blue, respectively. */
static inline int mileage_aura_color(unsigned style) {
  int contact, wall;
  mileage_style_decode(style, &contact, &wall);
  if (wall >= 3) return contact >= 3 ? 0 : 1;
  return contact >= 3 ? 3 : 2;
}

static inline int mileage_aura_level(double meters) {
  if (!isfinite(meters) || meters < 5000000.0) return -1;
  double km = floor(meters / 1000.0);
  return (km > 10000) + (km > 30000) + (km > 100000) + (km > 500000);
}

typedef struct {
  float wall_force, contact_force, contact_event;
  unsigned wall_ticks, quiet_ticks;
  int last_kind;
} mileage_style_log;

static inline void mileage_style_reset(mileage_style_log *log) {
  *log = (mileage_style_log){.last_kind = 0x7fff};
}

/* yt::CHitLogger::Drive. The quiet window closes an event before its
 * contribution reaches the per-race total. */
static inline void mileage_style_contact(mileage_style_log *log, int hit, int kind, float force) {
  if (hit && kind <= 3 && kind <= log->last_kind) {
    log->last_kind = kind;
    log->contact_event += force;
    log->quiet_ticks = 0;
  } else if (log->quiet_ticks < 10 && ++log->quiet_ticks == 10) {
    log->contact_force += fminf(fmaxf(log->contact_event, 0), 2500);
    log->contact_event = 0;
    log->last_kind = 0x7fff;
  }
}

static inline int mileage_style_axis(int old, int category) {
  /* clRaceThread::finiJoin blends the round's axis by 1/3, then truncates. */
  const float third = 1.0f / 3.0f;
  float round = (float)((1 - category) * 3) * third - 1.0f;
  float current = (float)old * third - 1.0f;
  float adjustment = round * third;
  int axis = (int)(((current + adjustment) + 1.0f) * 3.0f);
  return axis < 0 ? 0 : axis > 6 ? 6 : axis;
}

static inline unsigned mileage_style_commit(unsigned previous, const mileage_style_log *log) {
  int contact, wall;
  mileage_style_decode(previous, &contact, &wall);
  int contact_class = log->contact_force < 3500 ? -1 : log->contact_force >= 7500 ? 1 : 0;
  int wall_class = log->wall_force > 300000 || log->wall_ticks > 30 ? 1 :
                   log->wall_force < 20000 && log->wall_ticks <= 6 ? -1 : 0;
  return mileage_style_encode(mileage_style_axis(contact, contact_class), mileage_style_axis(wall, wall_class));
}
#endif
