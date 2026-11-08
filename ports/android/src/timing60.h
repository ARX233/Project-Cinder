#ifndef WMMT_TIMING60_H
#define WMMT_TIMING60_H
#include <stdint.h>
#include <math.h>
#define WMMT_PERIOD_NS 16666667LL
typedef struct { int64_t next; } timing60_pacer;
static inline void timing60_pacer_reset(timing60_pacer *p) { p->next = 0; }
static inline int64_t timing60_deadline(timing60_pacer *p, int64_t now) {
  if (!p->next) p->next = now;
  return p->next;
}
/* Preserve absolute phase after ordinary wakeup jitter. Skip deadlines too close
 * to this start; after a severe stall rebase rather than replay missed frames.
 * A half-period guard prevents rapid catch-up bursts, not all jitter. */
static inline void timing60_started(timing60_pacer *p, int64_t now) {
  if (now - p->next >= 4 * WMMT_PERIOD_NS) {
    p->next = now + WMMT_PERIOD_NS;
    return;
  }
  do { p->next += WMMT_PERIOD_NS; }
  while (p->next <= now + WMMT_PERIOD_NS / 2);
}
typedef struct { double fraction; } timing60_sim;
static inline void timing60_sim_reset(timing60_sim *s) { s->fraction = 0; }
static inline int timing60_sim_steps(timing60_sim *s, double dt) {
  if (!isfinite(dt) || dt < 0) dt = 0;
  if (dt > 0.1) dt = 0.1;
  s->fraction += dt * 60.0;
  int steps = (int)(s->fraction + 1e-7);
  s->fraction -= steps;
  if (s->fraction < 0) s->fraction = 0;
  return steps;
}
/* Discard timing around first draws and slow race/movie initialization. */
static inline int timing60_race_steps(timing60_sim *s, double dt, int paused, int first_frames) {
  if (paused || first_frames) {
    timing60_sim_reset(s);
    return 0;
  }
  return timing60_sim_steps(s, dt);
}
/* Display cadence is independent from the immutable 60 Hz simulation. A hint
 * rejected by Android naturally falls back through FIFO/vsync; invalid rates
 * use 60, and no caller can request more than 120 presentations per second. */
typedef struct { int64_t next, period; } timing60_display_pacer;
static inline float timing60_display_rate(float hz) {
  return !isfinite(hz) || hz < 30.0f ? 60.0f : hz > 120.0f ? 120.0f : hz;
}
static inline int timing60_frame_limit(int fps) {
  return fps == 60 || fps == 90 || fps == 120 ? fps : 0;
}
static inline float timing60_limited_display_rate(float hz, int fps) {
  float rate = timing60_display_rate(hz);
  return timing60_frame_limit(fps) && rate > fps ? (float)fps : rate;
}
static inline void timing60_display_reset(timing60_display_pacer *p) { p->next = 0; }
static inline int64_t timing60_display_deadline(timing60_display_pacer *p, int64_t now, float hz) {
  int64_t period = (int64_t)(1000000000.0 / timing60_display_rate(hz) + 0.5);
  if (p->period != period) { p->period = period; p->next = 0; }
  if (!p->next) p->next = now;
  return p->next;
}
static inline void timing60_display_started(timing60_display_pacer *p, int64_t now) {
  if (now - p->next >= 4 * p->period) { p->next = now + p->period; return; }
  do { p->next += p->period; } while (p->next <= now + p->period / 2);
}
#endif
