/* cc -std=c11 -ffunction-sections -fdata-sections car_audio_requests_test.c -Wl,-dead_strip -lm */
#include <assert.h>
#include <stdlib.h>
#include "../src/car.c"
uint8_t *rc_mem;
uint8_t *rc_va_slow(uint32_t a) { (void)a; abort(); }
int main(void) {
  rc_mem = calloc(1, 4096); assert(rc_mem); P.m = RC_MEM_BASE;
  uint32_t se = P.m + 0xb88u; car_se s = {0};
  W8(se + 0xa8, 1); WF(se + 0xac, .5f);
  W8(se + 0xb0, 1); WF(se + 0xb4, .75f); W32(se + 0xb8, 22050);
  W8(se + 0xbc, 1); WF(se + 0xc0, .25f); W32(se + 0xc4, 13000);
  read_se(&s); assert(s.valb && s.backfire && s.valb_vol == .5f && s.backfire_vol == .75f && s.backfire_hz == 22050);
  assert(s.road_hz == 13000 && s.road_vol == .25f);
  W8(se + 0xa8, 0); W8(se + 0xb0, 0); W8(se + 0xbc, 0); read_se(&s);
  assert(s.valb && s.backfire); /* retained despite a following zero tick */
  assert(s.road_hz == 13000 && s.road_vol == .25f);
  s.road_hz = 0; read_se(&s); assert(!s.road_hz);
  s.valb = s.backfire = 0; W8(se + 0xb0, 1); read_se(&s); assert(s.backfire);
  s.backfire = 0; read_se(&s); assert(!s.backfire); /* no duplicate held signal */
  car_set_ta_traffic(1); assert(P.ta_traffic == 1);
  car_set_ta_traffic(0); assert(P.ta_traffic == 0);
  free(rc_mem);
}
