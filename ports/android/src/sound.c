#include "sound.h"
#include "sounddb.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(__ANDROID__) || defined(WMMT_AUDIO_DIAGNOSTICS) || defined(WMMT_LOOP_ATOMICS_TEST) || defined(__LP64__)
#include <stdatomic.h>
#endif
#if defined(__ANDROID__) || defined(WMMT_AUDIO_DIAGNOSTICS)
#include <stdint.h>
#include <time.h>
_Static_assert(ATOMIC_LLONG_LOCK_FREE == 2, "audio diagnostics require lock-free 64-bit atomics");
static _Atomic unsigned long long diag_calls, diag_count, diag_abs, diag_square;
void snd_diag_callback(const short *out, int frames) {
  unsigned long long count = 0, sum = 0, square = 0;
  if (out && frames > 0) {
    int n = frames < 64 ? frames : 64;
    for (int i = 0; i < n; ++i) {
      int frame = (int)((int64_t)i * frames / n);
      int value = out[2 * (size_t)frame];
      unsigned magnitude = (unsigned)(value < 0 ? -value : value);
      sum += magnitude;
      square += (unsigned long long)magnitude * magnitude;
    }
    count = (unsigned long long)n;
  }
  atomic_fetch_add_explicit(&diag_calls, 1, memory_order_relaxed);
  atomic_fetch_add_explicit(&diag_count, count, memory_order_relaxed);
  atomic_fetch_add_explicit(&diag_abs, sum, memory_order_relaxed);
  atomic_fetch_add_explicit(&diag_square, square, memory_order_relaxed);
}
#endif

/* ---- engine model, from nsAudio::engine_calc and the tables it reads ----
 * Each layer is a looped sample with a band (r0..r1 fade in, r2..r3 fade out)
 * and the rpm at which it plays at its recorded pitch. Gain is (w)^0.2778 of
 * the band weight w; pitch is 2^((rpm - base) / 3205). Each car type has its
 * sound set (src/sounddb.h), e.g. the tuned rotaries' rx714-717 engine and
 * rn_m11t2-14t2 muffler. */
typedef sounddb_band band;

static float band_gain(const band *b, float rpm) {
  float w;
  if (rpm < b->r0 || rpm > b->r3) return 0;
  if (rpm < b->r1) w = (rpm - b->r0) / (float)(b->r1 - b->r0);
  else if (rpm <= b->r2) w = 1;
  else w = (rpm - b->r3) / (float)(b->r2 - b->r3);
  return powf(w, 0.2778f);
}

static float band_pitch(const band *b, float rpm) { return exp2f((rpm - b->base) * 0.000312012f); }

/* Preserve the original curve inside the table. Outside its highest valid
 * band, use that band's plateau endpoint instead of its zero-gain r3 edge.
 * The all-10000 sentinels are disabled layers, not usable RPM limits. */
static float band_rpm(const band bands[4], float rpm) {
  const band *highest = NULL;
  for (int i = 0; i < 4; ++i) {
    const band *b = &bands[i];
    if (b->r0 == 10000 && b->r1 == 10000 && b->r2 == 10000 && b->r3 == 10000) continue;
    if (b->r0 > b->r1 || b->r1 > b->r2 || b->r2 > b->r3 || b->r0 == b->r3) continue;
    if (!highest || b->r3 > highest->r3 || (b->r3 == highest->r3 && b->r2 > highest->r2)) highest = b;
  }
  if (!highest) return 0.0f;
  if (rpm > highest->r3) return (float)highest->r2;
  if (rpm == highest->r3) {
    for (int i = 0; i < 4; ++i) {
      const band *b = &bands[i];
      if (b->r0 == 10000 && b->r1 == 10000 && b->r2 == 10000 && b->r3 == 10000) continue;
      if (band_gain(b, rpm) > 0.0f) return rpm;
    }
    return (float)highest->r2;
  }
  return rpm;
}

/* ---- samples and voices ---- */

typedef struct {
  short *data;
  int n, rate;
} sample;

enum {
  S_ENG0, S_ENG1, S_ENG2, S_ENG3, S_MUF0, S_MUF1, S_MUF2, S_MUF3,
  S_SLIP, S_WALL, S_CRASH1, S_CRASH4, S_VALVE, S_CURSOR, S_SELECT, S_CANCEL, S_START,
  S_TIME_COUNT, S_TIME_COUNT_LAST, S_TIME_EXTEND, S_FINISH, S_TURN, S_TURN2, S_TURN3, S_START321, S_START_GO, S_FINISH2, S_CUTIN2, S_TUNING_BAR,
  S_RESULT2, S_RESULT_PASS, S_APPROACH2, S_APPROACH3, S_TURN3_CUTIN,
  /* the story movies' shows' others (src/storydemo.h: snd_effect) */
  S_VALB2, S_VALB3, S_GYAP, S_DOOR_OPEN, S_DOOR_CLOSE, S_ENGINE_START, S_PHONE2, S_RYBAL_INTRO,
  /* the dress-up part worn's (menu.c tg_wear_step: SE 0x41, 0x1e), the class-up's and the
   * story tuning work's levelup (SE 0x34); the wheel worn's jack (0x47, 0x46) and wrench
   * (0x4a, 0x4b), the level 63 part's COMPLETE (0x48); the title select's titles coming in (0x30);
   * the versus stars' star landing (0x2c) and big star (0x38) */
  S_PARTS_EQUIP, S_TUNING, S_LEVELUP, S_JACK_UP, S_JACK_DOWN, S_TUNING1, S_TUNING2, S_PARTS_COMP, S_RANK, S_WIN, S_WIN_BIGSTAR,
  S_BACKFIRE1, S_BACKFIRE2, S_ODO_COUNT,
  S_COUNT
};
/* every car type's engine and muffler loops (S_ENG0..S_MUF3 point into these) */
static sample ENGINE_SAMPLES[SOUNDDB_NSETS][8];
static const sounddb_set *engine_set = &SOUNDDB_SETS[0];
static int arcade_engine_mix;
static const char *EFFECT_FILES[S_COUNT - S_SLIP] = { "slip", "wall", "crash1", "crash4", "valb1",
                                                      "cursor", "select", "cancel", "gamestart",
                                                      "ti_count", "ti_count2", "turning6", "finish1",
                                                      "turning", "turning2", "turning3", "start321", "start_go",
                                                      "finish2", "cutin2", "tuning_bar", "result2",
                                                      "result_pass", "approach2", "approach3", "turning3_cutin",
                                                      "valb2", "valb3", "gyap", "door_open", "door_close",
                                                      "engine_start", "phone2", "rybal_intro", "parts_equip",
                                                      "tuning", "levelup", "jack_up", "jack_down", "tuning1",
                                                      "tuning2", "parts_comp", "rank", "win", "win_bigstar", "backfire1", "backfire2", "odo_count" };
static sample SAMPLES[S_COUNT];

/* Loop voices map 1:1 to the first ten samples; one-shots get their own pool. */
#define L_REV (S_WALL + 1) /* separate loop: preserve all existing sample IDs */
#define N_LOOP (L_REV + 1)
#define N_SHOT 4
static sample REV_SAMPLE;
static unsigned rev_car_type, rev_seen_sequence;
/* REV's start/stop epoch is published as one word; audio owns its phase. Bit 0
 * is playing, higher bits fence a new native Mc_Start/Mc_Stop lifetime. */
#if defined(__ANDROID__) || defined(WMMT_LOOP_ATOMICS_TEST)
_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "rev control must always be lock-free");
static _Atomic unsigned rev_control;
#define REV_CONTROL_LOAD() atomic_load_explicit(&rev_control, memory_order_acquire)
#define REV_CONTROL_STORE(value) atomic_store_explicit(&rev_control, (value), memory_order_release)
#else
static volatile unsigned rev_control;
#define REV_CONTROL_LOAD() (rev_control)
#define REV_CONTROL_STORE(value) (rev_control = (value))
#endif
static unsigned rev_audio_control; /* callback only */

typedef struct {
  const sample *s;
  double pos;
  volatile float vol, pitch; /* targets, written by the game thread */
  float cur_vol;             /* ramped on the audio thread */
  volatile int seq;          /* one-shots: bumped to (re)start */
  int played_seq;
} voice;

/* Only the game-thread targets are shared. Samples must be fully loaded before
 * the audio thread starts and remain immutable/alive until it has stopped.
 * pos and cur_vol belong exclusively to the audio thread. Relaxed operations
 * provide race freedom, not a coherent snapshot across different fields. */
#if defined(__ANDROID__) || defined(WMMT_LOOP_ATOMICS_TEST)
_Static_assert(ATOMIC_POINTER_LOCK_FREE == 2, "loop pointers must always be lock-free");
_Static_assert(__atomic_always_lock_free(sizeof(float), 0), "loop floats must always be lock-free");
typedef struct {
  _Atomic(const sample *) s;
  _Atomic float vol, pitch;
  double pos;
  float cur_vol;
} loop_voice;
#define LOOP_LOAD(field) atomic_load_explicit(&(field), memory_order_relaxed)
#define LOOP_STORE(field, value) atomic_store_explicit(&(field), (value), memory_order_relaxed)
#else
/* Keep older non-Android toolchains and their original behavior unchanged. */
typedef struct {
  const sample *s;
  volatile float vol, pitch;
  double pos;
  float cur_vol;
} loop_voice;
#define LOOP_LOAD(field) (field)
#define LOOP_STORE(field, value) ((field) = (value))
#endif

static loop_voice LOOPS[N_LOOP];
static voice SHOTS[N_SHOT];
static voice BAR; /* the story result's points gauge counting (SE 0x43, looped till stopped) */
static voice ROAD; /* callback-owned, monophonic like native one-shot 3 */
static unsigned long long road_seen; /* callback only */
#if defined(__ANDROID__) || defined(WMMT_LOOP_ATOMICS_TEST) || defined(__LP64__)
_Static_assert(ATOMIC_LLONG_LOCK_FREE == 2, "road shot commands must be lock-free");
static _Atomic unsigned long long road_command;
#define ROAD_LOAD() atomic_load_explicit(&road_command, memory_order_relaxed)
#define ROAD_STORE(value) atomic_store_explicit(&road_command, (value), memory_order_relaxed)
#else
static volatile unsigned long long road_command;
#define ROAD_LOAD() (road_command)
#define ROAD_STORE(value) (road_command = (value))
#endif
static int shot_next;

static void road_shot(uint16_t hz, float gain) {
  /* Publish the generation, native frequency and exact gain in one command. */
  uint32_t bits;
  memcpy(&bits, &gain, sizeof bits);
  unsigned long long generation = (ROAD_LOAD() >> 48) + 1u;
  ROAD_STORE(generation << 48 | (unsigned long long)hz << 32 | bits);
}

/* Minimal RIFF reader: PCM u8 or s16, mono. */
static int load_wav(sample *s, const char *path) {
  FILE *f = fopen(path, "rb");
  if (!f) return -1;
  unsigned char hdr[12];
  int bits = 0, chans = 0, ok = -1;
  if (fread(hdr, 1, 12, f) == 12 && !memcmp(hdr, "RIFF", 4) && !memcmp(hdr + 8, "WAVE", 4)) {
    unsigned char ck[8];
    while (fread(ck, 1, 8, f) == 8) {
      unsigned size = ck[4] | ck[5] << 8 | ck[6] << 16 | (unsigned)ck[7] << 24;
      if (!memcmp(ck, "fmt ", 4)) {
        unsigned char fmt[16];
        if (size < 16 || fread(fmt, 1, 16, f) != 16) break;
        chans = fmt[2] | fmt[3] << 8;
        s->rate = fmt[4] | fmt[5] << 8 | fmt[6] << 16 | fmt[7] << 24;
        bits = fmt[14] | fmt[15] << 8;
        fseek(f, (long)(size - 16 + (size & 1)), SEEK_CUR);
      } else if (!memcmp(ck, "data", 4)) {
        if (chans != 1 || (bits != 8 && bits != 16)) break;
        unsigned char *raw = malloc(size);
        if (!raw || fread(raw, 1, size, f) != size) { free(raw); break; }
        s->n = (int)(size / (bits / 8));
        s->data = malloc(sizeof(short) * (size_t)s->n);
        for (int i = 0; i < s->n; ++i)
          s->data[i] = bits == 8 ? (short)((raw[i] - 128) << 8) : (short)(raw[2 * i] | raw[2 * i + 1] << 8);
        free(raw);
        ok = 0;
        break;
      } else {
        fseek(f, (long)(size + (size & 1)), SEEK_CUR);
      }
    }
  }
  fclose(f);
  return ok;
}

int snd_init(const char *data_dir) {
  char path[1024];
  int missing = 0;
  for (int i = S_SLIP; i < S_COUNT; ++i) {
    snprintf(path, sizeof path, "%s/sound/%s.wav", data_dir, EFFECT_FILES[i - S_SLIP]);
    if (load_wav(&SAMPLES[i], path) != 0 && i != S_ODO_COUNT) missing++;
  }
  for (int k = 0; k < SOUNDDB_NSETS; ++k)
    for (int i = 0; i < 8; ++i) {
      const char *name = i < 4 ? SOUNDDB_SETS[k].engine[i] : SOUNDDB_SETS[k].muffler[i - 4];
      snprintf(path, sizeof path, "%s/sound/engine/%s.wav", data_dir, name);
      if (load_wav(&ENGINE_SAMPLES[k][i], path) != 0) missing++;
    }
  /* Original rotary warning shared by the RX-7 and RX-8. Old prepared data can omit it. */
  snprintf(path, sizeof path, "%s/sound/rx7_rev1.wav", data_dir);
  if (load_wav(&REV_SAMPLE, path) != 0 || REV_SAMPLE.n < 2 || REV_SAMPLE.rate <= 0)
    fprintf(stderr, "rotary warning sound unavailable: sound/rx7_rev1.wav\n");
  for (int i = 0; i < N_LOOP; ++i) {
    LOOP_STORE(LOOPS[i].s, i == L_REV ? &REV_SAMPLE : &SAMPLES[i]);
    LOOP_STORE(LOOPS[i].pitch, i == L_REV && REV_SAMPLE.rate > 0 ? 22000.0f / REV_SAMPLE.rate : 1.0f);
  }
  snd_set_car(5, 24); /* the FD3S, tuned; not a race/Mc_Start */
  return missing ? -1 : 0;
}

/* clAudio::playLoop 4: valve variant by ECarType (upstream table 0x931be80). */
static const unsigned char VALB_BY_TYPE[48] = {
  0,1,1,0,0,0,2,1,0,0,0,2,0,0,0,0,0,1,0,0,1,2,2,0,
  2,0,1,0,0,1,2,0,0,2,2,0,0,2,0,0,1,2,2,0,2,2,0,0
};
static int valb_sample = S_VALVE;

void snd_set_car(unsigned type, int power) {
  snd_rev_quiet();
  rev_car_type = type;
  /* Arcade ECarType: SE3P, FD3S, FC3S and the Lancer Evolution models. */
  arcade_engine_mix = (type >= 4 && type <= 6) || (type >= 9 && type <= 11) ||
                      type == 13 || type == 14 || type == 36;
  int v = type < 48 ? VALB_BY_TYPE[type] : 0;
  valb_sample = v == 0 ? S_VALVE : v == 1 ? S_VALB2 : S_VALB3;
  const unsigned char *by_type = power >= 8 ? SOUNDDB_BY_TYPE : SOUNDDB_BY_TYPE_STOCK;
  int k = type < SOUNDDB_NTYPES ? by_type[type] : 0;
  /* the audio thread reads each voice's sample pointer once per mix */
  for (int i = 0; i < 8; ++i) LOOP_STORE(LOOPS[S_ENG0 + i].s, &ENGINE_SAMPLES[k][i]);
  engine_set = &SOUNDDB_SETS[k];
}

static void play_shot(int sample_id, float vol, float pitch) {
  voice *v = &SHOTS[shot_next];
  shot_next = (shot_next + 1) % N_SHOT;
  v->s = &SAMPLES[sample_id];
  v->vol = vol;
  v->pitch = pitch;
  v->seq++;
}

/* nsAudio's one-shot table gives the countdown's two volume 1.5, approach2 and 3 and the
 * 10-in-a-row's beaten one's cutin2 (SE 0x4c) 2.0, the rest 1.0 */
void snd_menu(int which) {
  int loud = which == SND_APPROACH2 || which == SND_APPROACH3 || which == SND_BEATEN;
  play_shot(which == SND_BEATEN ? S_CUTIN2 : S_CURSOR + which,
            which == SND_START321 || which == SND_START_GO ? 1.2f : loud ? 1.6f : 0.8f, 1.0f);
}

void snd_effect(const char *wav, float vol) {
  for (int i = S_SLIP; i < S_COUNT; ++i) {
    /* (the patched iOS SDK has no plain strcmp for armv7) */
    const char *a = EFFECT_FILES[i - S_SLIP], *b = wav;
    while (*a && *a == *b) a++, b++;
    if (*a == *b) {
      play_shot(i, 0.8f * vol, 1.0f);
      return;
    }
  }
}

void snd_menu_loop(int which, int on) {
  if (which != SND_TUNING_BAR) return;
  if (on) {
    BAR.s = &SAMPLES[S_TUNING_BAR];
    BAR.pitch = 1.0f;
    BAR.seq++;
  }
  BAR.vol = on ? 0.8f : 0.0f;
}

/* ---- game-side control ---- */

static struct {
  float rpm;
  float accel, accel_target, accel_step; /* clAudioControl EngAccelOn/Off/ShiftUp/Down, 0..5000 */
  int throttle_on;
  float shot_cooldown, valb_left;
  float tick;
  unsigned backfire_k;
} E = { .rpm = 1000, .accel = 1000, .accel_target = 1000, .accel_step = 1000 };

void snd_update(car_state *car, const car_input *in, float dt) {
  int native_engine = arcade_engine_mix && car->se.rev_sequence;
  /* throttle state and gear changes drive the muffler level like the arcade */
  int on = native_engine ? car->engine_se.accel : in->throttle > 0.1f;
  if (on && !E.throttle_on) { E.accel_target = 5000; E.accel_step = 1000; }
  if (!on && E.throttle_on) {
    E.accel_target = 1000; E.accel_step = 1000;
  }
  E.throttle_on = on;
  if (native_engine ? car->engine_se.shift_up : car->shift_event > 0) {
    E.accel = fmaxf(0, E.accel_target - 5000); E.accel_step = 400;
  }
  if (native_engine ? car->engine_se.shift_down : car->shift_event < 0) {
    E.accel = fminf(5000, E.accel_target + 5000); E.accel_step = 8;
  }
  car->shift_event = 0;
  car->engine_se.shift_up = car->engine_se.shift_down = 0;
  /* muffler_calc runs per 60 Hz tick */
  for (E.tick += dt; E.tick >= 1.0f / 60.0f; E.tick -= 1.0f / 60.0f) {
    if (E.accel > E.accel_target) E.accel = fmaxf(E.accel_target, E.accel - E.accel_step);
    else if (E.accel < E.accel_target) E.accel = fminf(E.accel_target, E.accel + E.accel_step);
  }
  E.shot_cooldown -= dt;
  E.valb_left -= dt;
  /* Independent tuning, not original arcade gain values. Bound abnormal
   * requests before multiplication so the existing soft limiter stays safe. */
  const float valve_boost = 1.7f, backfire_boost = 1.7f;
  if (car->se.valb && E.valb_left <= 0 && isfinite(car->se.valb_vol) && car->se.valb_vol >= 0) {
    play_shot(valb_sample, valve_boost * 0.73f * 0.73f * fminf(car->se.valb_vol, 2.0f), 1.0f);
    E.valb_left = SAMPLES[valb_sample].rate > 0 ? (float)SAMPLES[valb_sample].n / SAMPLES[valb_sample].rate : 0.5f;
  }
  if (car->se.backfire && isfinite(car->se.backfire_vol) && car->se.backfire_vol >= 0 && isfinite(car->se.backfire_hz)) {
    int id = (E.backfire_k++ & 1u) ? S_BACKFIRE1 : S_BACKFIRE2;
    float hz = car->se.backfire_hz;
    play_shot(id, backfire_boost * 0.73f * fminf(car->se.backfire_vol, 2.0f), hz > 0 ? hz / 22050.0f : 1.0f);
  }
  car->se.valb = car->se.backfire = 0;
  if (car->se.road_hz > 0 && car->se.road_hz <= UINT16_MAX &&
      isfinite(car->se.road_vol) && car->se.road_vol > 0.0f) {
    /* Mc_Req's 0.73 gain times wave descriptor 3's 1.8 multiplier. */
    road_shot((uint16_t)car->se.road_hz, 0.73f * 1.8f * fminf(car->se.road_vol, 1.0f));
  }
  car->se.road_hz = 0;
  /* The enable bit identifies an equipped car; the physics envelope already
   * includes the high-rev state machine. Do not invent another RPM threshold. */
  if (!car->se.rev_sequence) snd_rev_quiet();
  else if (car->se.rev_sequence != rev_seen_sequence) {
    rev_seen_sequence = car->se.rev_sequence;
    float rev = car->se.rev_vol;
    /* Original CSetting::GetSettingPt 0x89bfcff..0x89bfd25 enables
     * ECarType 4..6: RX-8 SE3P, RX-7 FD and RX-7 FC. */
    if (!(REV_CONTROL_LOAD() & 1u) ||
        (rev_car_type < 4 || rev_car_type > 6) || !car->se.rev_enabled ||
        !isfinite(car->rpm) || car->rpm < 0.0f || !isfinite(rev) || rev <= 0.0f || !REV_SAMPLE.data || REV_SAMPLE.n < 2 || REV_SAMPLE.rate <= 0)
      rev = 0.0f;
    else
      rev = 0.73f * fminf(rev, 1.0f);
    LOOP_STORE(LOOPS[L_REV].vol, rev);
  }

  float accel = E.accel / 5000.0f;
  const float car_audio_boost = 1.7f; /* about +4.6 dB before the existing soft limiter */
  float eng_rpm, muf_rpm, engine_gain, muffler_gain, engine_envelope;
  if (native_engine) {
    /* Mc_Req 0x89a0678 scales GetRevRate into the shared 300..8999 audio
     * range. Using the tachometer's physical RPM skips this per-car mapping.
     * EngSndCtrl applies the accelerator envelope only to the muffler. */
    const float rpm = car->engine_se.rpm;
    eng_rpm = muf_rpm = isfinite(rpm) ? truncf(fminf(8999.0f, fmaxf(300.0f, rpm))) : 300.0f;
    engine_gain = 0.73f * fminf(1.0f, fmaxf(0.0f, car->engine_se.gain));
    muffler_gain = engine_gain;
    engine_envelope = 1.0f;
  } else {
    /* Prevent non-finite or absurd inputs from poisoning the smoothed state. */
    float input_rpm = fminf(1000000.0f, fmaxf(0.0f, car->rpm));
    if (!(E.rpm >= 0.0f) || E.rpm > 1000000.0f) E.rpm = 0.0f;
    E.rpm += (input_rpm - E.rpm) * fminf(1.0f, dt * 20.0f);
    eng_rpm = band_rpm(engine_set->engine_bands, E.rpm);
    muf_rpm = band_rpm(engine_set->muffler_bands, E.rpm);
    engine_gain = car_audio_boost * 0.30f;
    muffler_gain = car_audio_boost * 0.34f;
    engine_envelope = 0.55f + 0.45f * accel;
  }
  for (int i = 0; i < 4; ++i) {
    LOOP_STORE(LOOPS[S_ENG0 + i].vol, engine_gain * band_gain(&engine_set->engine_bands[i], eng_rpm) * engine_envelope);
    LOOP_STORE(LOOPS[S_ENG0 + i].pitch, band_pitch(&engine_set->engine_bands[i], eng_rpm));
    LOOP_STORE(LOOPS[S_MUF0 + i].vol, muffler_gain * band_gain(&engine_set->muffler_bands[i], muf_rpm) * accel);
    LOOP_STORE(LOOPS[S_MUF0 + i].pitch, band_pitch(&engine_set->muffler_bands[i], muf_rpm));
  }

  float kmh = car_kmh(car);
  LOOP_STORE(LOOPS[S_SLIP].vol, car_audio_boost * 0.45f * car->slip);
  LOOP_STORE(LOOPS[S_SLIP].pitch, 0.9f + 0.2f * fminf(1.0f, kmh / 200.0f));
  LOOP_STORE(LOOPS[S_WALL].vol, car->wall_hit > 0 && kmh > 10 ? fminf(0.6f, 0.2f + kmh / 300.0f) : 0);
  LOOP_STORE(LOOPS[S_WALL].pitch, 0.9f + 0.3f * fminf(1.0f, kmh / 250.0f));
#if defined(__ANDROID__) || defined(WMMT_AUDIO_DIAGNOSTICS)
  /* Snapshot deltas are approximate: the callback can update between loads. */
  static double last_log;
  static unsigned long long prev_calls, prev_count, prev_abs, prev_square;
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) == 0) {
    double now = ts.tv_sec + ts.tv_nsec * 1e-9;
    if (!last_log) last_log = now;
    else if (now - last_log >= 5.0) {
      unsigned long long calls = atomic_load_explicit(&diag_calls, memory_order_relaxed);
      unsigned long long count = atomic_load_explicit(&diag_count, memory_order_relaxed);
      unsigned long long sum = atomic_load_explicit(&diag_abs, memory_order_relaxed);
      unsigned long long square = atomic_load_explicit(&diag_square, memory_order_relaxed);
      unsigned long long n = count - prev_count;
      float eng = 0, muf = 0;
      int valid = 0;
      for (int i = 0; i < 8; ++i) {
        const sample *s = LOOP_LOAD(LOOPS[i].s);
        if (s && s->data && s->n >= 2 && s->rate > 0) valid++;
        if (i < 4) eng += LOOP_LOAD(LOOPS[i].vol); else muf += LOOP_LOAD(LOOPS[i].vol);
      }
      const sample *slip = LOOP_LOAD(LOOPS[S_SLIP].s);
      fprintf(stderr, "audio_diag rpm=%.1f slip=%.3f throttle=%.3f target_eng=%.4f target_muf=%.4f target_slip=%.4f samples_engine=%d/8 sample_slip=%d callbacks=%llu sampled=%llu mean_abs=%.1f rms_approx=%.1f\n",
              car->rpm, car->slip, in->throttle, eng, muf, LOOP_LOAD(LOOPS[S_SLIP].vol), valid,
              slip && slip->data && slip->n >= 2 && slip->rate > 0,
              calls - prev_calls, n, n ? (double)(sum - prev_abs) / n : 0.0,
              n ? sqrt((double)(square - prev_square) / n) : 0.0);
      prev_calls = calls; prev_count = count; prev_abs = sum; prev_square = square; last_log = now;
    }
  }
#endif

  if (car->impact > 6.0f && E.shot_cooldown <= 0) {
    play_shot(car->impact > 20.0f ? S_CRASH4 : S_CRASH1, fminf(1.0f, 0.4f + car->impact / 40.0f), 1.0f);
    E.shot_cooldown = 0.25f;
  }
  car->impact = 0;
}

/* These are presentation-only lifetime notifications, not engine calls. The
 * caller fences the latest observed sequence at a successful native race start;
 * only a subsequent physics observation may unmute it. Selection alone is not a
 * start. A mute/pause does not restart the continuously playing source. */
void snd_rev_start(unsigned observed_sequence) {
  snd_rev_quiet();
  rev_seen_sequence = observed_sequence;
  REV_CONTROL_STORE((REV_CONTROL_LOAD() + 2u) | 1u);
}

void snd_rev_stop(void) {
  snd_rev_quiet();
  REV_CONTROL_STORE((REV_CONTROL_LOAD() + 2u) & ~1u);
}

void snd_rev_quiet(void) { LOOP_STORE(LOOPS[L_REV].vol, 0.0f); }

void snd_quiet(void) {
  for (int i = 0; i < N_LOOP; ++i) LOOP_STORE(LOOPS[i].vol, 0.0f);
  if ((ROAD_LOAD() >> 32) & 0xffffu) road_shot(0, 0);
}

/* ---- audio thread ---- */

static void mix_voice(voice *v, float *acc, int frames, int loop) {
  const sample *s = v->s;
  if (!s || !s->data || s->n < 2) return;
  float target = v->vol;
  if (target <= 0.0005f && v->cur_vol <= 0.0005f) { v->cur_vol = 0; return; }
  double step = (double)v->pitch * s->rate / SND_RATE;
  float g = v->cur_vol, dg = (target - g) / (float)frames;
  double pos = v->pos;
  for (int i = 0; i < frames; ++i) {
    int p = (int)pos;
    if (p >= s->n - 1) {
      if (!loop) { v->s = NULL; break; }
      pos = fmod(pos, s->n - 1); /* also after a switch to a shorter sample */
      p = (int)pos;
    }
    float t = (float)(pos - p);
    acc[i] += g * (s->data[p] + (s->data[p + 1] - s->data[p]) * t);
    g += dg;
    pos += step;
  }
  v->pos = pos;
  v->cur_vol = target;
}

/* The loop-only counterpart preserves the interpolation and ramp calculation;
 * unlike a one-shot it never clears the shared sample pointer in the callback. */
static void mix_loop(loop_voice *v, float *acc, int frames) {
  const sample *s = LOOP_LOAD(v->s);
  if (!s || !s->data || s->n < 2) return;
  float target = LOOP_LOAD(v->vol);
  if (target <= 0.0005f && v->cur_vol <= 0.0005f) { v->cur_vol = 0; return; }
  double step = (double)LOOP_LOAD(v->pitch) * s->rate / SND_RATE;
  float g = v->cur_vol, dg = (target - g) / (float)frames;
  double pos = v->pos;
  for (int i = 0; i < frames; ++i) {
    int p = (int)pos;
    if (p >= s->n - 1) {
      pos = fmod(pos, s->n - 1);
      p = (int)pos;
    }
    float t = (float)(pos - p);
    acc[i] += g * (s->data[p] + (s->data[p + 1] - s->data[p]) * t);
    g += dg;
    pos += step;
  }
  v->pos = pos;
  v->cur_vol = target;
}

/* Original REV is voice 5 / loop wave 9: Mc_Start plays it at zero gain,
 * Mc_Req changes gain/frequency, Mc_Mute leaves it playing, Mc_Stop stops it.
 * All n original PCM frames belong to this loop (no WAV smpl subset). Keep this
 * separate from legacy engine/muffler interpolation and mute semantics. This
 * is the port's linear interpolator/block gain ramp, not a claim of bit-exact
 * proprietary OpenAL resampling or cabinet output. */
static void mix_rev(float *acc, int frames) {
  loop_voice *v = &LOOPS[L_REV];
  unsigned control = REV_CONTROL_LOAD();
  if (control != rev_audio_control) {
    rev_audio_control = control;
    v->pos = 0.0;
    v->cur_vol = 0.0f;
  }
  if (!(control & 1u)) { v->cur_vol = 0.0f; return; }
  const sample *s = LOOP_LOAD(v->s);
  if (!s || !s->data || s->n < 2 || s->rate <= 0) return;
  float target = LOOP_LOAD(v->vol);
  if (!isfinite(target) || target < 0.0f) target = 0.0f;
  float g = v->cur_vol, dg = (target - g) / (float)frames;
  /* Do not round a float 22000/22050 ratio then multiply the carrier rate. */
  const double step = 22000.0 / (double)SND_RATE;
  double pos = v->pos;
  for (int i = 0; i < frames; ++i) {
    if (pos >= s->n) pos = fmod(pos, (double)s->n);
    int p = (int)pos, next = p + 1 == s->n ? 0 : p + 1;
    float t = (float)(pos - p);
    acc[i] += g * (s->data[p] + (s->data[next] - s->data[p]) * t);
    g += dg;
    pos += step; /* zero gain still advances the original continuous loop */
  }
  v->pos = pos;
  v->cur_vol = target;
}

void snd_mix(short *out, int frames) {
  static float acc[4096];
  while (frames > 0) {
    int n = frames > 4096 ? 4096 : frames;
    memset(acc, 0, sizeof(float) * (size_t)n);
    for (int i = 0; i < L_REV; ++i) mix_loop(&LOOPS[i], acc, n);
    mix_rev(acc, n);
    if (BAR.played_seq != BAR.seq) { BAR.played_seq = BAR.seq; BAR.pos = 0; BAR.cur_vol = BAR.vol; }
    mix_voice(&BAR, acc, n, 1);
    for (int i = 0; i < N_SHOT; ++i) {
      voice *v = &SHOTS[i];
      if (v->played_seq != v->seq) { v->played_seq = v->seq; v->pos = 0; v->cur_vol = v->vol; }
      if (v->s) mix_voice(v, acc, n, 0);
    }
    unsigned long long road = ROAD_LOAD();
    if (road != road_seen) {
      road_seen = road;
      unsigned hz = (unsigned)(road >> 32) & 0xffffu;
      uint32_t bits = (uint32_t)road;
      float gain;
      memcpy(&gain, &bits, sizeof gain);
      ROAD = (voice){.s = hz ? &SAMPLES[S_GYAP] : NULL, .vol = gain, .cur_vol = gain,
                     .pitch = hz / 22050.0f};
    }
    if (ROAD.s) mix_voice(&ROAD, acc, n, 0);
    for (int i = 0; i < n; ++i) {
      out[2 * i] = out[2 * i + 1] = (short)(32767.0f * tanhf(acc[i] * (1.0f / 32767.0f))); /* soft clip */
    }
    out += 2 * n;
    frames -= n;
  }
}
