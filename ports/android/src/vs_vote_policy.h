/* Original-supported ballot rules + explicitly identified port ramp adaptation.
 * Header-only, pure bounded data; no native/file/socket/RNG calls.
 * Original SHA2e6591...: clNet getJoinArea0x8920178; day0x891aa08;
 * raw JOIN_RAMPS0x9739140 and ramp presentation0x93faa00. */
#ifndef WMMT_VS_VOTE_POLICY_H
#define WMMT_VS_VOTE_POLICY_H
#include <stdint.h>
#define VS_VOTE_POLICY_PLAYERS 4
/* UI course index is car.c COURSES index, NOT original area or native ERamp. */
static const uint8_t vs_vote_raw_area[22] = {0,0,0,0,1,1,2,2,2,2,3,3,3,3,5,6,6,4,7,7,7,7};
static const uint8_t vs_vote_raw_native[22] = {2,3,4,5,6,7,8,9,10,11,12,13,14,15,1,16,17,18,19,20,21,22};
static const uint8_t vs_vote_raw_course[22] = {0,1,0,1,2,3,4,4,4,4,5,5,5,5,7,9,9,6,8,8,8,8};
static const uint8_t vs_vote_area_count[8] = {4,2,4,4,1,1,2,4};
static const uint8_t vs_vote_area_ramps[8][4] = {{3,2,0,1},{5,4,0,0},{6,7,9,8},{10,11,13,12},
                                              {17,0,0,0},{14,0,0,0},{15,16,0,0},{18,19,20,21}};
/* CONFIRMED concrete area0..7; bit0x80 is omakase presentation, counted normally.
 * Choosing/unconfirmed is not a vote; caller supplies its frozen confirmed mask.
 * All-invalid fallback of the original resolver is C1/0; the new room policy
 * instead waits for all members (no deadline-driven invented ballot). */
static inline int vs_vote_area_result(const uint16_t *choice, unsigned n, unsigned confirmed,
                                      uint8_t shared_byte, int *area) {
  if (!choice || !area || n < 2 || n > 4 || confirmed != (1u<<n)-1u) return 0;
  unsigned count[8] = {0}, best=0, ties[8], nt=0;
  for (unsigned i=0;i<n;i++) {
    if (choice[i] & ~0x87u) return 0;
    unsigned a=choice[i]&0x7fu; if(a>7) return 0;
    if (++count[a]>best) best=count[a];
  }
  for(unsigned a=0;a<8;a++) if(count[a]==best) ties[nt++]=a;
  if(!nt) return 0;
  *area=(int)ties[shared_byte%nt];return 1;
}
/* Original getJoinDayTime: one confirmed bit per player, majority; ties DAY0.
 * No original day-omakase selector was observed; no abstain input is accepted. */
static inline int vs_vote_day_result(const uint16_t *choice, unsigned n, unsigned confirmed, int *zone) {
  if(!choice || !zone || n<2 || n>4 || confirmed!=(1u<<n)-1u)return 0;
  unsigned night=0;
  for(unsigned i=0;i<n;i++){if(choice[i]>1)return 0;night+=choice[i];}
  *zone=night>n-night;return 1;
}
/* PORT ADAPTATION, NOT ORIGINAL RAMP-SELECT EQUIVALENCE: the original has its
 * own start-ramp sequence/confirmed ramp resolver; that UI/lottery is not fully
 * recovered. With no extra protocol substage, choose ONCE from that area's
 * exact original raw-ramp row using the MATCH-shared seed high bytes. Nagoya
 * and Osaka are original fixed ramps. Do not use native physics/global rand. */
static inline int vs_vote_ramp_for_area(int area, uint32_t shared_seed) {
  if(area<0 || area>7)return -1;
  return vs_vote_area_ramps[area][(shared_seed>>8)%vs_vote_area_count[area]];
}
static inline int vs_vote_ramp_in_area(int raw, int area) {
  return raw>=0 && raw<22 && area>=0 && area<8 && vs_vote_raw_area[raw]==area;
}
#endif
