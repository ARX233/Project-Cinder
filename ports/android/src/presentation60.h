#ifndef WMMT_PRESENTATION60_H
#define WMMT_PRESENTATION60_H
#include "car.h"
#include <math.h>
#include <string.h>
/* Render-only history. Never pass this copy to car_update, sound, network,
 * odometer or results. Interpolation costs one fixed tick of visual latency. */
static inline float presentation60_lerp(float a, float b, float t) { return a + (b - a) * t; }
static inline int presentation60_near(const float *a, const float *b) {
  float d = 0;
  for (int k = 12; k < 15; ++k) { float x = a[k] - b[k]; d += x*x; }
  return isfinite(d) && d < 250.0f * 250.0f; /* reset/respawn: snap, never sweep across road */
}
static inline int presentation60_unit(float *v) {
  float n = sqrtf(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]);
  if (!isfinite(n) || n < 0.001f) return 0;
  for (int k = 0; k < 3; ++k) v[k] /= n;
  return 1;
}
static inline void presentation60_matrix(float *out, const float *a, const float *b, float t) {
  memcpy(out, b, 16 * sizeof *out);
  if (!presentation60_near(a,b)) return;
  float x[3], y[3], z[3];
  for (int k = 0; k < 3; ++k) {
    x[k] = presentation60_lerp(a[k],b[k],t);
    y[k] = presentation60_lerp(a[4+k],b[4+k],t);
  }
  if (!presentation60_unit(x)) return;
  float dot = x[0]*y[0] + x[1]*y[1] + x[2]*y[2];
  for (int k = 0; k < 3; ++k) y[k] -= dot*x[k];
  if (!presentation60_unit(y)) return;
  z[0]=x[1]*y[2]-x[2]*y[1]; z[1]=x[2]*y[0]-x[0]*y[2]; z[2]=x[0]*y[1]-x[1]*y[0];
  for (int k = 0; k < 3; ++k) {
    out[k]=x[k]; out[4+k]=y[k]; out[8+k]=z[k];
    out[12+k]=presentation60_lerp(a[12+k],b[12+k],t);
  }
}
static inline void presentation60_eye(const float *view, float *eye) {
  for (int j=0;j<3;++j) eye[j]=-(view[12]*view[4*j]+view[13]*view[4*j+1]+view[14]*view[4*j+2]);
}
static inline void presentation60_camera(float *out, const float *a, const float *b,
                                          const float *eye, float t) {
  /* A view matrix's translation is in camera coordinates, not world space.
   * At far-away map origins, a tiny rotation can change that translation by
   * thousands of units: it must not trip the world-space teleport guard. */
  float ar[16], br[16];
  memcpy(ar,a,sizeof ar); memcpy(br,b,sizeof br);
  for (int k=12;k<15;++k) ar[k]=br[k]=0;
  presentation60_matrix(out,ar,br,t);
  for (int k=0;k<3;++k) out[12+k]=-(out[k]*eye[0]+out[4+k]*eye[1]+out[8+k]*eye[2]);
}
static inline void presentation60_wheels(float out[4][16], float *rot,
  const float a[4][16], const float *ar, const float b[4][16], const float *br, float t) {
  for (int j=0;j<4;++j) {
    presentation60_matrix(out[j],a[j],b[j],t);
    rot[j]=ar[j]+remainderf(br[j]-ar[j],6.28318530718f)*t;
  }
}
static inline void presentation60_car(car_state *out, const car_state *a, const car_state *b,
                                       float t, int valid) {
  *out=*b;
  if (!valid || !isfinite(t) || !presentation60_near(a->body,b->body)) return;
  t=t<0?0:t>1?1:t;
  presentation60_matrix(out->body,a->body,b->body,t);
  float camera_delta = 0;
  for (int k=0;k<3;++k) {
    out->pos[k]=presentation60_lerp(a->pos[k],b->pos[k],t);
    float d=a->cam_pos[k]-b->cam_pos[k]; camera_delta+=d*d;
  }
  /* Movie camera cuts snap even if the car itself did not teleport. */
  if (isfinite(camera_delta) && camera_delta < 250.0f*250.0f) {
    for (int k=0;k<3;++k) out->cam_pos[k]=presentation60_lerp(a->cam_pos[k],b->cam_pos[k],t);
    presentation60_camera(out->cam_view,a->cam_view,b->cam_view,out->cam_pos,t);
    out->cam_fov=presentation60_lerp(a->cam_fov,b->cam_fov,t);
    out->cam_near=presentation60_lerp(a->cam_near,b->cam_near,t);
    out->cam_blur=presentation60_lerp(a->cam_blur,b->cam_blur,t);
  }
  if (a->mirror && b->mirror) {
    float ae[3],be[3],eye[3]; presentation60_eye(a->mirror_view,ae); presentation60_eye(b->mirror_view,be);
    for(int k=0;k<3;++k) eye[k]=presentation60_lerp(ae[k],be[k],t);
    presentation60_camera(out->mirror_view,a->mirror_view,b->mirror_view,eye,t);
    out->mirror_fov=presentation60_lerp(a->mirror_fov,b->mirror_fov,t);
    out->mirror_near=presentation60_lerp(a->mirror_near,b->mirror_near,t);
  }
  presentation60_wheels(out->tyre,out->tyre_rot,a->tyre,a->tyre_rot,b->tyre,b->tyre_rot,t);
  for (int j=0;j<CAR_RIVALS;++j) if (a->rival_shown[j] && b->rival_shown[j] &&
      presentation60_near(a->rival_body[j],b->rival_body[j])) {
    presentation60_matrix(out->rival_body[j],a->rival_body[j],b->rival_body[j],t);
    presentation60_wheels(out->rival_tyre[j],out->rival_tyre_rot[j],a->rival_tyre[j],a->rival_tyre_rot[j],
                          b->rival_tyre[j],b->rival_tyre_rot[j],t);
  }
  for (int j=0;j<b->n_traffic && j<a->n_traffic && j<CAR_TRAFFIC;++j)
    if(a->traffic[j].model==b->traffic[j].model)
      presentation60_matrix(out->traffic[j].body,a->traffic[j].body,b->traffic[j].body,t);
}
#endif
