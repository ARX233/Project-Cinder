/* Standalone: cc -std=c11 -DWMMT_LOOP_ATOMICS_TEST test_rx7_rev_host.c -lm -o /tmp/rx7_rev_test */
#include <assert.h>
#include <math.h>
#include <string.h>
#include "../src/sound.c"
float car_kmh(const car_state *c) { return fabsf(c->speed) * 3.6f; }
static void check(float expected) { assert(fabsf(LOOP_LOAD(LOOPS[L_REV].vol) - expected) < 0.0001f); }
static void frame(car_state *c, car_input *in) { ++c->se.rev_sequence; snd_update(c,in,1.0f/60); }
int main(void) {
  car_state car = {0}; car_input input = {0};
  static short data[4] = {10000,-10000,10000,-10000};
  (void)snd_init("/this-path-does-not-exist-rx7");
  car.se.rev_enabled=1; car.se.rev_vol=.5f;
  snd_set_car(5,24); snd_rev_start(car.se.rev_sequence); frame(&car,&input); check(0); /* absent */
  REV_SAMPLE.data=data; REV_SAMPLE.n=4; REV_SAMPLE.rate=22050;
  LOOP_STORE(LOOPS[L_REV].pitch,22000.0f/22050.0f);
  frame(&car,&input); check(.365f);
  short out[64]; snd_mix(out,32); int nonzero=0; for(int i=0;i<64;i++) nonzero |= out[i]!=0; assert(nonzero);
  snd_set_car(6,24); check(0); frame(&car,&input); check(.365f);
  snd_set_car(4,24); check(0); frame(&car,&input); check(.365f); /* RX-8 */
  car.se.rev_enabled=0; frame(&car,&input); check(0);
  car.se.rev_enabled=1; frame(&car,&input); check(.365f);
  snd_set_car(3,24); frame(&car,&input); check(0);
  snd_set_car(7,24); frame(&car,&input); check(0);
  snd_set_car(5,24); car.se.rev_enabled=0; frame(&car,&input); check(0);
  car.se.rev_enabled=1; car.se.rev_vol=NAN; frame(&car,&input); check(0);
  car.se.rev_vol=INFINITY; frame(&car,&input); check(0);
  car.se.rev_vol=-.1f; frame(&car,&input); check(0);
  car.se.rev_vol=2; frame(&car,&input); check(.73f);
  snd_rev_quiet(); check(0); snd_update(&car,&input,1.0f/60); check(0); /* stale snapshot */
  frame(&car,&input); check(.73f); snd_quiet(); check(0);
  snd_set_car(6,24); snd_update(&car,&input,1.0f/60); check(0); /* no cross-car reuse */
  frame(&car,&input); check(.73f); car.se.rev_sequence=0; snd_update(&car,&input,0); check(0);
  /* Existing 1.7 gain is unchanged. */
  car.rpm=4000; E.rpm=4000; E.accel=5000; E.accel_target=5000; input.throttle=1;
  snd_update(&car,&input,0); float rpm=band_rpm(engine_set->engine_bands,E.rpm);
  assert(fabsf(LOOP_LOAD(LOOPS[S_ENG0].vol)-1.7f*.30f*band_gain(&engine_set->engine_bands[0],rpm))<.0001f);
  E.valb_left=0; car.se.valb=1; car.se.valb_vol=.5f;
  int slot=shot_next; snd_update(&car,&input,0);
  assert(fabsf(SHOTS[slot].vol-1.7f*.73f*.73f*.5f)<.0001f);
  car.se.backfire=1; car.se.backfire_vol=.5f; car.se.backfire_hz=22050;
  slot=shot_next; snd_update(&car,&input,0);
  assert(fabsf(SHOTS[slot].vol-1.7f*.73f*.5f)<.0001f);
  return 0;
}
