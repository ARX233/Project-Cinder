/* Software mixer for engine and effect sounds, driven from the arcade's own
 * sample sets and rpm tables. Platform glue (audio output, BGM) lives in
 * sound_ios.m; this file is plain C so it can be tested on the desktop. */
#ifndef SOUND_H
#define SOUND_H

#include "car.h"

#define SND_RATE 44100

/* Game-thread retry policy, shared with the offline state-machine test. */
typedef struct { int attempts, pending, tracking; double next, stable_since; } snd_retry;
static inline void snd_retry_begin(snd_retry *r, double now) { r->attempts = 0; r->pending = 1; r->next = now; r->tracking = 0; }
static inline int snd_retry_due(const snd_retry *r, double now, int paused) { return !paused && r->pending && r->attempts < 3 && now >= r->next; }
static inline void snd_retry_result(snd_retry *r, double now, int ok) {
  ++r->attempts; r->tracking = 0;
  r->pending = !ok && r->attempts < 3;
  r->next = now + 5.0;
}
static inline void snd_retry_interrupt(snd_retry *r, double now) {
  if (!r->attempts) r->attempts = 1;
  r->tracking = 0; r->pending = r->attempts < 3; r->next = now + 5.0;
}
static inline void snd_retry_stability(snd_retry *r, double now, int started) {
  if (!started) r->tracking = 0;
  else if (!r->tracking) { r->tracking = 1; r->stable_since = now; }
  else if (now - r->stable_since >= 10.0) r->attempts = 0;
}

/* Loads the WAVs in data_dir/sound (every car's engine sounds in sound/engine). Returns 0
 * on success; missing files are silent. Call once before starting the audio callback;
 * sample contents and storage must remain unchanged/alive until callbacks stop. */
int snd_init(const char *data_dir);
/* The engine sound set of the car to drive (its ECarType, car_spec.type) at its power tune
 * (car_spec.power): the arcade's tuned set from power 8 on, below that the stock one. */
void snd_set_car(unsigned type, int power);
/* Game thread, once per frame: consume latched CInfoSEMc one-shots and update voices. */
void snd_update(car_state *car, const car_input *in, float dt);
/* Front-end sounds from the arcade's system_se (SND_START: gamestart.wav, SE 0x3f that
 * clPlayCheckThread plays when the player starts from the attract), and the time attack's:
 * clTimeConsole::setRemainTime ticks each second from 9 left (ti_count, SE 0xf) and from 4
 * (ti_count2, 0x31); a checkpoint's TIME EXTEND (turning6, 0x3b); clTaResult's finish1 (0x24); the
 * route signs' (clSignConsole) turning (0x54), turning2 (0x55) and turning3 (0x56); the start's
 * countdown (clCountDownConsole::setCountDown): start321 (0xc) at 2 and 1, start_go (0xd) at GO;
 * clTaResult's finish2 (0x25) and cutin2 (0x22, each row of the result); the story result's
 * points gauge counting (tuning_bar, 0x43: snd_menu_loop); the 10-in-a-row result's
 * (clTenResult2) result2 (0x29) as a face is crossed out and result_pass (0x36) with the medal; the
 * 10-in-a-row's approach2 (0x4d) as each rival comes on, approach3 (0x4e) for the last
 * (clRaceThread::race, changeTenRival), a rival's line coming up (clCutinDisp::update,
 * turning3_cutin, 0x53) and cutin2 louder as one is beaten (clRaceThread::race, 0x4c). */
enum { SND_CURSOR, SND_SELECT, SND_CANCEL, SND_START, SND_TIME_COUNT, SND_TIME_COUNT_LAST, SND_TIME_EXTEND, SND_FINISH,
       SND_TURN, SND_TURN2, SND_TURN3, SND_START321, SND_START_GO, SND_FINISH2, SND_CUTIN2, SND_TUNING_BAR,
       SND_RESULT2, SND_RESULT_PASS, SND_APPROACH2, SND_APPROACH3, SND_TURN3_CUTIN, SND_BEATEN };
void snd_menu(int which);
/* A one-shot by its file's name (data/sound/<wav>.wav, one of sound.c's) at nsAudio's volume
 * (the one-shot table's: 1 the front end's usual): the story movies' shows' sounds, the dress-up
 * part worn's parts_equip and tuning, the class-up's levelup */
void snd_effect(const char *wav, float vol);
/* A looped front-end sound (SND_TUNING_BAR) on from its start, or off. */
void snd_menu_loop(int which, int on);
/* Silence the car (engine, tyres, wall) when the race is left. */
void snd_quiet(void);
/* Game thread: successful native Mc_Start / teardown notifications only.
 * Start fences the supplied latest physics sequence; no cached envelope reuse.
 * Do not call these on ordinary model selection, pause/resume or an RPM edge. */
void snd_rev_start(unsigned observed_sequence);
void snd_rev_stop(void);
/* Game thread: silence only the rev loop when physics updates stop. Mute keeps
 * the playing source phase; a stopped source stays stopped until start. */
void snd_rev_quiet(void);
/* Audio thread: mix `frames` interleaved stereo int16 frames. */
void snd_mix(short *out, int frames);
#if defined(__ANDROID__) || defined(WMMT_AUDIO_DIAGNOSTICS)
#include <stdatomic.h>
/* Sticky monotonic token: a delayed old-stream callback cannot erase a newer one. */
static inline void snd_diag_disconnect(_Atomic unsigned *mark, unsigned generation) {
  unsigned old = atomic_load_explicit(mark, memory_order_relaxed);
  while (old < generation && !atomic_compare_exchange_weak_explicit(mark, &old, generation, memory_order_relaxed, memory_order_relaxed)) {}
}
/* Audio callback only; samples at most 64 already-mixed stereo frames. */
void snd_diag_callback(const short *out, int frames);
#endif

#endif
