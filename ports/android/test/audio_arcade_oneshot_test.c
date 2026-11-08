/* Host test: cc -std=c11 audio_arcade_oneshot_test.c -lm -o /tmp/audio_arcade_oneshot_test */
#include <assert.h>
#include <float.h>
#include <math.h>
#include <stdio.h>
#include "../src/sound.c"
float car_kmh(const car_state *c) { (void)c; return 0; }
static int close_to(float a, float b) { return fabsf(a - b) < 1e-6f; }
int main(void) {
  car_state car = {0}; car_input in = {0};
  snd_set_car(1, 0); assert(valb_sample == S_VALB2);
  snd_set_car(6, 0); assert(valb_sample == S_VALB3);
  snd_set_car(999, 0); assert(valb_sample == S_VALVE);
  SAMPLES[S_VALVE].n = 22050; SAMPLES[S_VALVE].rate = 22050;
  car.se.valb = car.se.backfire = 1; car.se.valb_vol = 0.5f;
  car.se.backfire_vol = 0.8f; car.se.backfire_hz = 11025;
  snd_update(&car, &in, 1.0f/60);
  assert(!car.se.valb && !car.se.backfire && shot_next == 2);
  assert(SHOTS[0].s == &SAMPLES[S_VALVE] && SHOTS[0].pitch == 1.0f);
  assert(close_to(SHOTS[0].vol, 1.7f*.73f*.73f*.5f));
  assert(SHOTS[1].s == &SAMPLES[S_BACKFIRE2] && SHOTS[1].pitch == .5f);
  assert(close_to(SHOTS[1].vol, 1.7f*.73f*.8f));
  in.throttle = 1; car.rpm = 6000; car.shift_event = 1;
  snd_update(&car, &in, 1.0f/60); in.throttle = 0;
  snd_update(&car, &in, 1.0f/60); assert(shot_next == 2);
  car.se.valb = car.se.backfire = 1; car.se.backfire_hz = 0;
  snd_update(&car, &in, 1.0f/60);
  assert(shot_next == 3 && SHOTS[2].s == &SAMPLES[S_BACKFIRE1] && SHOTS[2].pitch == 1);
  car.se.backfire = 1; car.se.backfire_vol = NAN;
  snd_update(&car, &in, 1.0f/60); assert(shot_next == 3 && !car.se.backfire);
  E.valb_left = 0; car.se.valb = 1; car.se.valb_vol = NAN;
  snd_update(&car, &in, 0); assert(shot_next == 3 && !car.se.valb);
  car.se.valb = car.se.backfire = 1; car.se.valb_vol = INFINITY;
  car.se.backfire_vol = INFINITY; car.se.backfire_hz = 22050;
  snd_update(&car, &in, 0); assert(shot_next == 3);
  car.se.valb = car.se.backfire = 1; car.se.valb_vol = -1; car.se.backfire_vol = -1;
  snd_update(&car, &in, 0); assert(shot_next == 3);
  car.se.backfire = 1; car.se.backfire_vol = 1; car.se.backfire_hz = NAN;
  snd_update(&car, &in, 0); assert(shot_next == 3);
  car.se.valb = car.se.backfire = 1; car.se.valb_vol = FLT_MAX;
  car.se.backfire_vol = FLT_MAX; car.se.backfire_hz = 22050;
  snd_update(&car, &in, 0);
  assert(shot_next == 1 && close_to(SHOTS[3].vol, 1.7f*.73f*.73f*2));
  assert(close_to(SHOTS[0].vol, 1.7f*.73f*2) && SHOTS[0].pitch == 1);
  /* Once the sample-duration cooldown has elapsed the selected variant plays again. */
  snd_set_car(1, 0); SAMPLES[S_VALB2].n = 100; SAMPLES[S_VALB2].rate = 100;
  car.se.valb = 1; car.se.valb_vol = 1;
  snd_update(&car, &in, 1.0f); assert(SHOTS[1].s == &SAMPLES[S_VALB2]);
  assert(close_to(SHOTS[1].vol, 1.7f*.73f*.73f));
  /* A matching control update must leave all loop targets unchanged. */
  float vol[N_LOOP], pitch[N_LOOP];
  car_state control = car; car_input controls = in;
  unsigned char saved_E[sizeof E]; memcpy(saved_E, &E, sizeof E);
  snd_update(&control, &controls, 0);
  for (int i = 0; i < N_LOOP; ++i) { vol[i] = LOOP_LOAD(LOOPS[i].vol); pitch[i] = LOOP_LOAD(LOOPS[i].pitch); }
  memcpy(&E, saved_E, sizeof E);
  car.se.backfire = 1; car.se.backfire_vol = .5f; car.se.backfire_hz = 22050;
  snd_update(&car, &in, 0);
  for (int i = 0; i < N_LOOP; ++i) { assert(vol[i] == LOOP_LOAD(LOOPS[i].vol)); assert(pitch[i] == LOOP_LOAD(LOOPS[i].pitch)); }
  snd_menu(SND_START_GO); assert(close_to(SHOTS[(shot_next + N_SHOT - 1) % N_SHOT].vol, 1.2f));
  E.shot_cooldown = 0; car.impact = 10;
  snd_update(&car, &in, 0);
  assert(SHOTS[(shot_next + N_SHOT - 1) % N_SHOT].s == &SAMPLES[S_CRASH1]);
  assert(close_to(SHOTS[(shot_next + N_SHOT - 1) % N_SHOT].vol, .65f));
  /* Exercise actual mixer and its existing soft limiter at boosted maximum. */
  static short pcm[8] = {32767,32767,32767,32767,32767,32767,32767,32767};
  short out[8];
  memset(SHOTS, 0, sizeof SHOTS); shot_next = 0; snd_quiet();
  SAMPLES[S_BACKFIRE2] = (sample){pcm, 8, SND_RATE};
  E.backfire_k = 0; car.se.backfire = 1; car.se.backfire_vol = FLT_MAX; car.se.backfire_hz = 22050;
  snd_update(&car, &in, 0); snd_quiet(); snd_mix(out, 4);
  assert(out[0] > 0 && out[0] <= 32767 && out[0] == out[1]);
  memset(SHOTS, 0, sizeof SHOTS);
  SAMPLES[S_GYAP] = (sample){pcm, 8, 22050};
  car.se.road_hz = 22050; car.se.road_vol = .5f;
  snd_update(&car, &in, 0); snd_mix(out, 4);
  assert(!car.se.road_hz && ROAD.s == &SAMPLES[S_GYAP] && ROAD.pos == 2);
  assert(close_to(ROAD.vol, .73f * 1.8f * .5f) && out[0] > 0);
  snd_update(&car, &in, 0); snd_mix(out, 4);
  assert(ROAD.pos == 4); /* no native request, no restart */
  car.se.road_hz = 11025;
  snd_update(&car, &in, 0); snd_mix(out, 4);
  assert(ROAD.pos == 1); /* same voice, restarted at the new native frequency */
  unsigned long long before = ROAD_LOAD();
  car.se.road_hz = 11025; car.se.road_vol = NAN;
  snd_update(&car, &in, 0); assert(ROAD_LOAD() == before);
  snd_quiet(); snd_mix(out, 4);
  assert(!ROAD.s && out[0] == 0);
  puts("arcade one-shots passed");
}
