#include "junction_barrier.h"
#include "anm.h"
#include "gl.h"
#ifdef WMMT_NATIVE_VK
#include "native_vk.h"
#endif
#include <math.h>
#include <string.h>

void junction_barrier_reset(junction_barrier *b) { if (b) memset(b, 0, sizeof *b); }
static int valid_point(const junction_barrier_point *p) {
  return p && isfinite(p->v[0]) && isfinite(p->v[1]) && isfinite(p->v[2]);
}
static int distinct(const junction_barrier_point *a, const junction_barrier_point *b) {
  return a->v[0] != b->v[0] || a->v[1] != b->v[1] || a->v[2] != b->v[2];
}
int junction_barrier_tick(junction_barrier *b, int state, int left_kind, int right_kind,
                          const junction_barrier_point *v1, const junction_barrier_point *v2,
                          const junction_barrier_point *v3, float distance) {
  if (!b) return 0;
  if (!isfinite(distance)) { junction_barrier_reset(b); return 0; }
  if (state == 1) {
    if ((v1 && !valid_point(v1)) || (v2 && !valid_point(v2)) || (v3 && !valid_point(v3)) ||
        (v1 && v2 && v3 && (!distinct(v1,v2) || !distinct(v1,v3) || !distinct(v2,v3)))) {
      junction_barrier_reset(b); return 0;
    }
    if (!b->ready || b->manager_state != 1) {
      if (!valid_point(v1) || !valid_point(v2) || !valid_point(v3) ||
          !distinct(v1,v3) || !distinct(v3,v2) || !distinct(v1,v2)) { junction_barrier_reset(b); return 0; }
      /* Copy first, since callers may supply pointers to existing fields. */
      junction_barrier_point a=*v1, c=*v2, m=*v3;
      b->left.start=a; b->left.end=m; b->left.kind=left_kind;
      b->right.start=m; b->right.end=c; b->right.kind=right_kind; b->ready=1;
    }
    b->left.display_state=b->right.display_state=1;
  } else if ((state == 2 || state == 3) && b->ready) {
    b->left.display_state = state == 2 ? 2 : 3;
    b->right.display_state = state == 2 ? 3 : 2;
  } else { junction_barrier_reset(b); return 0; }
  b->manager_state=state;
  return 1;
}

/* Rectangle is equivalent to the original two coplanar triangles, with a
 * different diagonal. UV bands are from the original static initializer;
 * state 3 selects the alternate frame, not a change to destination kind. */
static int frame_quad(const junction_barrier_side *s, int side, float h, render_vertex *v) {
  if (!valid_point(&s->start) || !valid_point(&s->end) ||
      (s->start.v[0] == s->end.v[0] && s->start.v[2] == s->end.v[2])) return 0;
  float y0=s->start.v[1]+h, y1=s->end.v[1]+h;
  if (!isfinite(y0) || !isfinite(y1) || y0==s->start.v[1] || y1==s->end.v[1]) return 0;
  float u0=(side ? 0.5f : 0.0f) + (s->display_state==3 ? 0.25f : 0.0f);
  const float u[4]={u0,u0+0.25f,u0+0.25f,u0}, vv[4]={1,1,0,0};
  for (int i=0;i<4;i++) {
    const junction_barrier_point *pt=(i==0 || i==3)?&s->start:&s->end;
    memcpy(v[i].pos,pt->v,sizeof pt->v);
    if (i<2) v[i].pos[1]=i==0?y0:y1;
    v[i].uv[0]=u[i]; v[i].uv[1]=vv[i];
    memset(v[i].rgba,255,sizeof v[i].rgba);
  }
  return 1;
}
static double frame_distance2(const junction_barrier_side *s, const float eye[3], float h) {
  double d=0;
  for (int i=0;i<3;i++) {
    double c=((double)s->start.v[i]+(double)s->end.v[i])*0.5 + (i==1?(double)h*0.5:0.0);
    double x=c-(double)eye[i]; d+=x*x;
  }
  return d;
}
int junction_barrier_draw(const junction_barrier *b, const mat4 *world_vp,
                          const float eye[3], float native_to_world, render_params *p) {
  if (!b || !b->ready || !world_vp || !eye || !p || !isfinite(native_to_world) ||
      native_to_world<=0) return 0;
  for (int i=0;i<16;i++) if (!isfinite(world_vp->m[i])) return 0;
  for (int i=0;i<3;i++) if (!isfinite(eye[i])) return 0;
  float h=85.0f*native_to_world;
  if (!isfinite(h) || h<=0) return 0;
  render_vertex verts[8];
  if (!frame_quad(&b->left,0,h,verts) || !frame_quad(&b->right,1,h,verts+4)) return 0;
  /* Additive RGB is order-independent in ideal arithmetic; still order the
   * transparent candidates far first to match the surrounding pass convention. */
  if (frame_distance2(&b->right,eye,h)>frame_distance2(&b->left,eye,h)) {
    render_vertex tmp[4]; memcpy(tmp,verts,sizeof tmp); memcpy(verts,verts+4,sizeof tmp); memcpy(verts+4,tmp,sizeof tmp);
  }
#ifdef WMMT_NATIVE_VK
  /* Basic device availability only: this metadata query never acquires/claims
   * a frame. The caller already admitted the frame outside Android's mutex;
   * the typed sprite recorder still validates its explicit target/program. */
  if (!cinder_vk_device_api_version()) return 0;
#else
  if (!glGetString(GL_VERSION)) return 0;
#endif
  int sprite=anm_sprite(0x569);
  if (sprite<0) return 0;
#ifndef WMMT_NATIVE_VK
  /* texture() uploads/binds on the active unit; the scene shader samples unit 0. */
  glActiveTexture(GL_TEXTURE0);
#endif
  unsigned int tex=anm_sprite_texture(sprite);
  if (!tex) return 0;
#ifdef WMMT_NATIVE_VK
  /* The legacy path explicitly enables depth even for a caller's overlay
   * parameters. Author that choice without mutating caller state or GL bits.
   * This sprite wrapper only writes draws; all other parameters stay borrowed. */
  render_params native_params=*p;
  native_params.no_depth_test=0;
  render_sprites_by_colour(world_vp,verts,2,tex,&native_params);
  p->draws=native_params.draws;
#else
  glBlendEquation(GL_FUNC_ADD);
  glEnable(GL_DEPTH_TEST);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glEnableVertexAttribArray(2);
  render_sprites_by_colour(world_vp,verts,2,tex,p);
#endif
  return 2;
}
