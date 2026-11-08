#include "lights.h"
#include "neondb.h"
#include "tenline.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

/* nsStreetLightManager::stTextureParam (0x93d9ac0), by colour group (white, yellow, orange,
 * blue): the lamp's glint from streetlight.tga and the glow under it from streettube.tga.
 * uv: left, top, right, bottom (GL's bottom-up v); size and offset in world units. */
typedef struct {
  float uv[4], w, h, ox, oy;
} sprite_param;
static const sprite_param STREET_LAMP[4] = {
  { { 0.0234375f, 0.80859375f, 0.48046875f, 0.51171875f }, 36.5625f, 23.75f, 0, -14.375f },
  { { 0.5234375f, 0.80859375f, 0.98046875f, 0.51171875f }, 36.5625f, 23.75f, 0, -14.375f },
  { { 0.0234375f, 0.30859375f, 0.48046875f, 0.01171875f }, 36.5625f, 23.75f, 0, -14.375f },
  { { 0.5f, 0.5f, 1.0f, 0.0f }, 40.0f, 40.0f, 0, 0 },
};
static const sprite_param STREET_TUBE[4] = {
  { { 0.0f, 1.0f, 0.5f, 0.5f }, 16.0f, 16.0f, 0, 0 },
  { { 0.5f, 1.0f, 1.0f, 0.5f }, 16.0f, 16.0f, 0, 0 },
  { { 0.0f, 0.5f, 0.5f, 0.0f }, 16.0f, 16.0f, 0, 0 },
  { { 0.5f, 0.5f, 1.0f, 0.0f }, 16.0f, 16.0f, 0, 0 },
};
/* nsBuildlingLightManager's (0x93db680), by group (red1, red2, red3, white1, white2): the red
 * aircraft warning lights from buildinglight.tga, the white ones from bridge_light.tga; and
 * their blink period in frames (0x93db714), lit for its first half */
static const sprite_param BUILDING[5] = {
  { { 0, 1, 1, 0 }, 32.0f, 32.0f, 0, 0 }, { { 0, 1, 1, 0 }, 32.0f, 32.0f, 0, 0 }, { { 0, 1, 1, 0 }, 32.0f, 32.0f, 0, 0 },
  { { 0, 1, 1, 0 }, 48.0f, 48.0f, 0, 0 }, { { 0, 1, 1, 0 }, 48.0f, 48.0f, 0, 0 },
};
static const int BUILDING_BLINK[5] = { 120, 120, 0, 0, 0 };
/* clPrimitive::setup's draw distances: lights further ahead than this are left out */
#define STREET_RANGE 1500.0f
#define BUILDING_RANGE 5000.0f
enum { TEX_LAMP, TEX_TUBE, TEX_BUILDING, TEX_BRIDGE, TEX_GOAL, TEX_TEN_LINE, TEX_SPOT, TEX_SPARK };

/* clGoalLine::clLine::update (0x89778f0): up to 20 lights in a row across the road, from 6
 * units in from one road-edge point to 6 in from the other, (int)((length - 2) * 0.05) + 1 of
 * them, 8.2 units up, scaled 2.5 (preScale) and turned to face the camera (its rotation,
 * transposed). Each is the IGB's glow and flash quad (goal_light_yellow.igb for the goal,
 * _blue for the checkpoint; both from goal_light01.tga: yellow its right half, blue its left,
 * the flashes below the glows), drawn additive (igBlendFunctionAttr SRC_ALPHA, ONE) at the
 * igColorAttr's 0.8 grey, without depth writes. Their igTransformSequence1_5 pulses them
 * (scale keys at these frames of 1/60 s, looped); every other light runs 250 ms ahead
 * (setAnimOffset). */
#define GOAL_MAX 20
#define GOAL_INSET 6.0f
#define GOAL_LIFT 8.2f
#define GOAL_SCALE 2.5f
#define GLOW_HALF 5.0f
#define FLASH_HALF 4.37167f
#define GOAL_GREY 204
static const float GOAL_KEY[12] = { 0, 2, 5, 11, 13, 14, 15, 17, 23, 26, 28, 29 };
static const float GLOW_SCALE[12] = { 0.99380f, 0.92648f, 0.70817f, 0.19941f, 0.11223f, 0.1f,
                                      0.11147f, 0.19360f, 0.68320f, 0.90640f, 0.98853f, 1.0f };
static const float FLASH_SCALE[12] = { 0.6051f, 0.6416f, 0.7408f, 0.9584f, 0.9949f, 1.0f,
                                       0.9949f, 0.9584f, 0.7408f, 0.6416f, 0.6051f, 0.6f };
/* by row (goal, checkpoint), glow then flash: left, top, right, bottom (GL's bottom-up v) */
static const float GOAL_UV[2][2][4] = {
  { { 0.5f, 1.0f, 1.0f, 0.5f }, { 0.5f, 0.5f, 1.0f, 0.0f } },
  { { 0.0f, 1.0f, 0.5f, 0.5f }, { 0.0f, 0.5f, 0.5f, 0.0f } },
};

typedef struct {
  float pos[3];
  uint32_t type;
} light_point;

typedef struct {
  char pack[48];
  uint8_t kind, body, count;
  float position[8][3];
} front_halo_car;

static struct {
  wpk_scene sprites;
  /* the under neons' glows (neon.wpk, loaded with the rest; neon_tried once it was tried) */
  wpk_scene neon;
  int neon_tried;
  char neon_path[1200];
  wpk_scene front_halo;
  front_halo_car *halo_cars;
  uint32_t n_halo_cars;
  light_point *pts; /* street lights, then building lights */
  int n_street, n_building;
  render_vertex v[2][4 * RENDER_MAX_SPRITES];
} L;

/* the lights of a city's file (lights.bin Tokyo's, lights_<city>.bin the others'); none
 * when it is missing */
int lights_points(const char *path) {
  free(L.pts);
  L.pts = NULL;
  L.n_street = L.n_building = 0;
  FILE *f = fopen(path, "rb");
  if (!f) return -1;
  char magic[4];
  uint32_t n[2];
  int ok = fread(magic, 4, 1, f) == 1 && fread(n, 4, 2, f) == 2 && magic[0] == 'L' && magic[3] == '1';
  if (ok) {
    L.pts = malloc(sizeof *L.pts * (n[0] + n[1] + 1));
    ok = L.pts && fread(L.pts, sizeof *L.pts, n[0] + n[1], f) == n[0] + n[1];
  }
  fclose(f);
  if (!ok) {
    free(L.pts);
    L.pts = NULL;
    return -1;
  }
  L.n_street = (int)n[0];
  L.n_building = (int)n[1];
  return 0;
}

int lights_load(const char *data_dir) {
  char path[1200];
  snprintf(L.neon_path, sizeof L.neon_path, "%s/neon.wpk", data_dir);
  snprintf(path, sizeof path, "%s/lights.wpk", data_dir);
  if (wpk_load(&L.sprites, path) != 0 || L.sprites.n_tex < 4) return -1;
  /* the neons now too: on first use their 12 uploads hitched the frame they first showed in */
  L.neon_tried = 1;
  if (wpk_load(&L.neon, L.neon_path) != 0) fprintf(stderr, "no %s, no under neons\n", L.neon_path);
  snprintf(path, sizeof path, "%s/lights.bin", data_dir);
  return lights_points(path);
}

static uint32_t halo_le32(const unsigned char b[4]) {
  return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16 | (uint32_t)b[3] << 24;
}

int lights_front_halo_load(const char *atlas, const char *anchors) {
  FILE *f = fopen(anchors, "rb");
  if (!f) return -1;
  unsigned char header[8];
  uint32_t n = 0;
  if (fread(header, 1, sizeof header, f) == sizeof header && !memcmp(header, "HL01", 4))
    n = halo_le32(header + 4);
  front_halo_car *cars = n && n <= 1024 ? calloc(n, sizeof *cars) : NULL;
  int valid = cars != NULL;
  for (uint32_t i = 0; valid && i < n; ++i) {
    unsigned char row[52];
    front_halo_car *c = &cars[i];
    valid = fread(row, 1, sizeof row, f) == sizeof row && row[0] && memchr(row, 0, 48) &&
            row[48] <= 1 && row[49] <= 3 && row[50] >= 1 && row[50] <= 8 && row[51] == 0;
    if (!valid) break;
    memcpy(c->pack, row, sizeof c->pack);
    c->kind = row[48];
    c->body = row[49];
    c->count = row[50];
    for (int a = 0; valid && a < c->count; ++a) {
      for (int k = 0; valid && k < 3; ++k) {
        unsigned char bytes[4];
        if (fread(bytes, 1, sizeof bytes, f) != sizeof bytes) { valid = 0; break; }
        uint32_t word = halo_le32(bytes);
        memcpy(&c->position[a][k], &word, sizeof word);
        valid = isfinite(c->position[a][k]) && fabsf(c->position[a][k]) <= 100.0f;
      }
    }
  }
  valid = valid && fgetc(f) == EOF && !ferror(f);
  fclose(f);
  if (!valid) { free(cars); return -1; }
  wpk_scene sprites = {.fd = -1};
  if (wpk_load(&sprites, atlas) != 0 || sprites.n_tex != 1 || !sprites.textures[0]) {
    wpk_free(&sprites);
    free(cars);
    return -1;
  }
  if (L.n_halo_cars) wpk_free(&L.front_halo);
  free(L.halo_cars);
  L.front_halo = sprites;
  L.halo_cars = cars;
  L.n_halo_cars = n;
  return 0;
}

/* a camera-facing quad of p at view-space centre c */
static void quad(render_vertex *q, const float *c, const sprite_param *p) {
  float x0 = c[0] + p->ox - p->w * 0.5f, x1 = x0 + p->w;
  float y1 = c[1] + p->oy + p->h * 0.5f, y0 = y1 - p->h;
  const float xs[4] = { x0, x1, x1, x0 }, ys[4] = { y1, y1, y0, y0 };
  const float us[4] = { p->uv[0], p->uv[2], p->uv[2], p->uv[0] }, vs[4] = { p->uv[1], p->uv[1], p->uv[3], p->uv[3] };
  for (int k = 0; k < 4; ++k) {
    q[k].pos[0] = xs[k];
    q[k].pos[1] = ys[k];
    q[k].pos[2] = c[2];
    q[k].uv[0] = us[k];
    q[k].uv[1] = vs[k];
    q[k].rgba[0] = q[k].rgba[1] = q[k].rgba[2] = q[k].rgba[3] = 255;
  }
}

/* The lights of [first, first + n) with a type in [lo, hi] up to range ahead, as quads:
 * sprite a[type] into out0 and (with b) sprite b[type] into out1; blink gives the types'
 * blink periods (NULL: steady). Returns how many. */
static int gather(const mat4 *view, const float *eye, int first, int n, int lo, int hi, float range,
                  const sprite_param *a, const sprite_param *b, const int *blink, int frame,
                  render_vertex *out0, render_vertex *out1) {
  const float *m = view->m;
  int count = 0;
  for (int i = first; i < first + n && count < RENDER_MAX_SPRITES; ++i) {
    const light_point *l = &L.pts[i];
    int t = (int)l->type;
    if (t < lo || t > hi) continue;
    float dx = l->pos[0] - eye[0], dz = l->pos[2] - eye[2];
    if (dx > range || dx < -range || dz > range || dz < -range) continue;
    if (blink && blink[t] && frame % blink[t] >= blink[t] / 2) continue;
    float c[3];
    for (int r = 0; r < 3; ++r) c[r] = m[r] * l->pos[0] + m[4 + r] * l->pos[1] + m[8 + r] * l->pos[2] + m[12 + r];
    if (c[2] > -1.0f || c[2] < -range) continue;
    quad(out0 + 4 * count, c, &a[t]);
    if (b) quad(out1 + 4 * count, c, &b[t]);
    count++;
  }
  return count;
}

void lights_draw(const mat4 *proj, const mat4 *view, int night, float time, render_params *rp) {
  if (!L.pts) return;
  /* the camera's position: the view matrix is a rotation R and a translation t, eye = -R^T t */
  const float *m = view->m;
  float eye[3];
  for (int k = 0; k < 3; ++k) eye[k] = -(m[4 * k] * m[12] + m[4 * k + 1] * m[13] + m[4 * k + 2] * m[14]);
  int frame = (int)(time * 60.0f);
  int n = gather(view, eye, 0, L.n_street, 0, 3, STREET_RANGE, STREET_LAMP, STREET_TUBE, NULL, frame, L.v[0], L.v[1]);
  render_sprites(proj, L.v[1], n, L.sprites.textures[TEX_TUBE], rp);
  render_sprites(proj, L.v[0], n, L.sprites.textures[TEX_LAMP], rp);
  if (!night) return;
  n = gather(view, eye, L.n_street, L.n_building, 0, 2, BUILDING_RANGE, BUILDING, NULL, BUILDING_BLINK, frame, L.v[0], NULL);
  render_sprites(proj, L.v[0], n, L.sprites.textures[TEX_BUILDING], rp);
  n = gather(view, eye, L.n_street, L.n_building, 3, 4, BUILDING_RANGE, BUILDING, NULL, BUILDING_BLINK, frame, L.v[0], NULL);
  render_sprites(proj, L.v[0], n, L.sprites.textures[TEX_BRIDGE], rp);
}

/* a key of the lights' pulse at frame f (0..29) */
static float goal_key(const float *v, float f) {
  for (int k = 1; k < 12; ++k)
    if (f <= GOAL_KEY[k]) return v[k - 1] + (v[k] - v[k - 1]) * (f - GOAL_KEY[k - 1]) / (GOAL_KEY[k] - GOAL_KEY[k - 1]);
  return v[11];
}

/* a camera-facing square of half size h at view-space centre c, texture rect uv */
static void goal_quad(render_vertex *q, const float *c, float h, const float *uv) {
  const float xs[4] = { c[0] - h, c[0] + h, c[0] + h, c[0] - h }, ys[4] = { c[1] + h, c[1] + h, c[1] - h, c[1] - h };
  const float us[4] = { uv[0], uv[2], uv[2], uv[0] }, vs[4] = { uv[1], uv[1], uv[3], uv[3] };
  for (int k = 0; k < 4; ++k) {
    q[k].pos[0] = xs[k];
    q[k].pos[1] = ys[k];
    q[k].pos[2] = c[2];
    q[k].uv[0] = us[k];
    q[k].uv[1] = vs[k];
    q[k].rgba[0] = q[k].rgba[1] = q[k].rgba[2] = GOAL_GREY;
    q[k].rgba[3] = 255;
  }
}

int lights_warm(void) {
  static int done;
  if (done || !L.sprites.n_tex) return 0;
  done = 1;
  for (uint32_t k = 0; k < L.sprites.n_tex; ++k) render_warm_texture(L.sprites.textures[k]);
  if (L.n_halo_cars) render_warm_texture(L.front_halo.textures[0]);
  return (int)L.sprites.n_tex + (L.n_halo_cars != 0);
}

void lights_draw_goal(const mat4 *proj, const mat4 *view, const car_race *r, float time, render_params *rp) {
  if (L.sprites.n_tex <= TEX_GOAL || !r->lines) return;
  const float *m = view->m;
  int n = 0;
  for (int row = 0; row < 2; ++row) {
    if (!(r->lines & (1 << row))) continue;
    const float *a = r->line[row][0], *b = r->line[row][1];
    float d[3] = { b[0] - a[0], b[1] - a[1], b[2] - a[2] };
    float len = sqrtf(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
    int count = (int)((len - 2.0f) * 0.05f) + 1;
    if (len <= 0.0f || count < 1) continue;
    if (count > GOAL_MAX) count = GOAL_MAX;
    float s[3], e[3];
    for (int k = 0; k < 3; ++k) {
      s[k] = a[k] + GOAL_INSET * d[k] / len;
      e[k] = b[k] - GOAL_INSET * d[k] / len;
    }
    for (int i = 0; i < count; ++i) {
      float f = count > 1 ? (float)i / (float)(count - 1) : 0.0f;
      float p[3] = { s[0] + (e[0] - s[0]) * f, s[1] + (e[1] - s[1]) * f + GOAL_LIFT, s[2] + (e[2] - s[2]) * f };
      float c[3];
      for (int k = 0; k < 3; ++k) c[k] = m[k] * p[0] + m[4 + k] * p[1] + m[8 + k] * p[2] + m[12 + k];
      if (c[2] > -1.0f) continue; /* behind the camera */
      float t = fmodf(time + (i & 1 ? 0.0f : 0.25f), 29.0f / 60.0f) * 60.0f;
      goal_quad(L.v[0] + 4 * n++, c, GLOW_HALF * GOAL_SCALE * goal_key(GLOW_SCALE, t), GOAL_UV[row][0]);
      goal_quad(L.v[0] + 4 * n++, c, FLASH_HALF * GOAL_SCALE * goal_key(FLASH_SCALE, t), GOAL_UV[row][1]);
    }
  }
  render_sprites(proj, L.v[0], n, L.sprites.textures[TEX_GOAL], rp);
}

/* clTenRivalLine::update (0x861d8c8), the 10-in-a-row's blue line across the road at the
 * rival: rival_line_blue.igb's mesh (tenline.h) posed from the two points a, b as x along
 * b - a its full length, y up (0, 1, 0) made square to it times TEN_RIVAL_LINE_HEIGHT
 * (effect_config.lua: 14), z their cross, at the middle; additive, its vertex colours. */
#define TEN_LINE_HEIGHT 14.0f

void lights_draw_ten_line(const mat4 *proj, const mat4 *view, const car_race *r, render_params *rp) {
  if (L.sprites.n_tex <= TEX_TEN_LINE || !r->ten_line_on) return;
  const float *a = r->ten_line[0], *b = r->ten_line[1], *m = view->m;
  float d[3] = { b[0] - a[0], b[1] - a[1], b[2] - a[2] };
  float len = sqrtf(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]);
  if (len <= 0.0f) return;
  float x[3] = { d[0] / len, d[1] / len, d[2] / len };
  float z[3] = { -x[2], 0.0f, x[0] }; /* x cross (0, 1, 0) */
  float zl = sqrtf(z[0] * z[0] + z[2] * z[2]);
  if (zl <= 0.0f) return;
  z[0] /= zl, z[2] /= zl;
  float y[3] = { z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0] };
  int n = 0;
  for (int t = 0; t < TENLINE_VERTS; t += 3, ++n) {
    render_vertex *q = L.v[0] + 4 * n;
    for (int k = 0; k < 4; ++k) {
      int i = t + (k < 3 ? k : 2); /* the triangle as a quad with its last corner twice */
      const float *v = TENLINE_POS[i];
      float p[3];
      for (int j = 0; j < 3; ++j)
        p[j] = (a[j] + b[j]) * 0.5f + v[0] * len * x[j] + v[1] * TEN_LINE_HEIGHT * y[j] + v[2] * z[j];
      for (int j = 0; j < 3; ++j) q[k].pos[j] = m[j] * p[0] + m[4 + j] * p[1] + m[8 + j] * p[2] + m[12 + j];
      q[k].uv[0] = v[3];
      q[k].uv[1] = v[4];
      memcpy(q[k].rgba, TENLINE_RGBA[i], 4);
    }
  }
  render_sprites(proj, L.v[0], n, L.sprites.textures[TEX_TEN_LINE], rp);
}

/* clCarSpotLight (init 0x8603978, update 0x8603c84, draw 0x8604248): the headlights' pool,
 * sprite/car_lightspot_a3.tga (image 1334) on two overlapping quads in the car's space, one
 * per lamp, flat on the road (y 0 and 0.05), 12 to 250 ahead, v 0 at the car (the bright
 * edge); vertex colour effect_config.lua's CAR_SPOT_LIGHT_MORNING (0.4, 0.4, 0.5) or _NIGHT
 * (0.7, 0.7, 0.8) by clWorkSpace::getDayTimeSelect; drawn depth tested, not written,
 * glBlendFunc(GL_SRC_COLOR, GL_ONE). */
static const float SPOT_X[2][2] = { { -36.0f, 54.0f }, { -54.0f, 36.0f } };
static const float SPOT_Y[2] = { 0.0f, 0.05f };
#define SPOT_NEAR 12.0f
#define SPOT_FAR 250.0f

void lights_draw_spots(const mat4 *proj, const mat4 *view, const float *const *bodies, int n, int night, render_params *rp) {
  if (L.sprites.n_tex <= TEX_SPOT || n <= 0) return;
  const uint8_t grey = night ? 179 : 102, blue = night ? 204 : 128;
  const float *m = view->m;
  int q = 0;
  for (int i = 0; i < n && q + 2 <= RENDER_MAX_SPRITES; ++i) {
    const float *b = bodies[i];
    for (int s = 0; s < 2; ++s, ++q) {
      render_vertex *v = L.v[0] + 4 * q;
      const float xs[4] = { SPOT_X[s][0], SPOT_X[s][1], SPOT_X[s][1], SPOT_X[s][0] };
      const float zs[4] = { SPOT_FAR, SPOT_FAR, SPOT_NEAR, SPOT_NEAR };
      const float us[4] = { 0, 1, 1, 0 }, vs[4] = { 1, 1, 0, 0 };
      for (int k = 0; k < 4; ++k) {
        float p[3];
        for (int j = 0; j < 3; ++j) p[j] = b[j] * xs[k] + b[4 + j] * SPOT_Y[s] + b[8 + j] * zs[k] + b[12 + j];
        for (int j = 0; j < 3; ++j) v[k].pos[j] = m[j] * p[0] + m[4 + j] * p[1] + m[8 + j] * p[2] + m[12 + j];
        v[k].uv[0] = us[k];
        v[k].uv[1] = vs[k];
        v[k].rgba[0] = v[k].rgba[1] = grey;
        v[k].rgba[2] = blue;
        v[k].rgba[3] = 255;
      }
    }
  }
  render_sprites_by_colour(proj, L.v[0], q, L.sprites.textures[TEX_SPOT], rp);
}

/* car_frontlight.igb's head01..03 on the shared car_headlight.dds atlas. */
static const sprite_param HEADLIGHT[3] = {
  { { 0.0f, 1.0f, 0.5f, 0.5f }, 15.0f, 15.0f, 0, 0 },
  { { 0.5f, 1.0f, 1.0f, 0.5f }, 15.0f, 15.0f, 0, 0 },
  { { 0.0f, 0.5f, 0.5f, 0.0f }, 15.0f, 15.0f, 0, 0 },
};

void lights_draw_front_halo(const mat4 *proj, const mat4 *view, const float *eye,
                            const float *body, const char *pack, int aero, int mirror,
                            render_params *rp) {
  if (!pack) return;
  const front_halo_car *car = NULL;
  for (uint32_t i = 0; i < L.n_halo_cars; ++i) {
    const front_halo_car *row = &L.halo_cars[i];
    if (row->kind == 0 && row->body == aero && !strcmp(row->pack, pack)) { car = row; break; }
  }
  if (!car) return;
  const float *forward = body + 8, *v = view->m;
  const float length = sqrtf(forward[0]*forward[0] + forward[1]*forward[1] + forward[2]*forward[2]);
  if (!(length > 0.0f)) return;
  const float divisor[2][3] = {{30,30,20}, {20,30,10}};
  const float limit[2][3] = {{6,6,10}, {6,6,8}};
  int camera = !!mirror, n = 0;
  /* clCarLampManager uses a reduced set on cars with more than two locators.
   * The main-view Supra also omits R2 (slot 1 in each of its four bodies). */
  int layers = car->count <= 2 ? 7 : camera ? 5 : 1;
  int skip_supra_r2 = !camera && car->count > 2 && !strcmp(pack, "toy_JZA80");
  for (int a = 0; a < car->count; ++a) {
    if (skip_supra_r2 && a == 1) continue;
    const float *local = car->position[a];
    float world[3], direction[3], center[3];
    float dist2 = 0, dot = 0;
    for (int k = 0; k < 3; ++k) {
      world[k] = body[k]*local[0] + body[4+k]*local[1] + body[8+k]*local[2] + body[12+k];
      direction[k] = eye[k] - world[k];
      dist2 += direction[k] * direction[k];
      dot += direction[k] * forward[k];
    }
    /* clCarLampHalo::update, facing alpha and view-space billboard. */
    const float distance = sqrtf(dist2);
    if (!(dot > 0.0f) || !(distance > 5.0f) || !isfinite(distance)) continue;
    const float alpha = fminf(1.0f, dot / (distance * length));
    for (int k = 0; k < 3; ++k) world[k] += direction[k] * (5.0f / distance);
    for (int k = 0; k < 3; ++k)
      center[k] = v[k]*world[0] + v[4+k]*world[1] + v[8+k]*world[2] + v[12+k];
    if (center[2] >= -1.0f) continue;
    for (int layer = 0; layer < 3; ++layer) {
      if (!(layers & (1 << layer))) continue;
      sprite_param sprite = HEADLIGHT[layer];
      float scale = fminf(distance / divisor[camera][layer], limit[camera][layer]);
      sprite.w *= scale;
      sprite.h *= scale;
      render_vertex *q = L.v[0] + 4 * n++;
      quad(q, center, &sprite);
      for (int i = 0; i < 4; ++i) q[i].rgba[3] = (uint8_t)(alpha * 255.0f + 0.5f);
      if (!camera && !layer) {
        const float angle = 3.0f * (direction[0]*forward[0] + direction[2]*forward[2]) / (distance * length);
        float s = sinf(angle), c = cosf(angle);
        for (int i = 0; i < 4; ++i) {
          float x = q[i].pos[0] - center[0], y = q[i].pos[1] - center[1];
          q[i].pos[0] = center[0] + c*x - s*y;
          q[i].pos[1] = center[1] + s*x + c*y;
        }
      }
    }
  }
  render_sprites(proj, L.v[0], n, L.front_halo.textures[0], rp);
}

/* clNeon::setup (0x895094c): the model's matrix makeScale(NeonScaleGetFromCarId) with the
 * translation NeonOffsetGetFromCarId, under the car's: the quad's corners (u along x, v
 * along -z, as the IGBs map them) moved by it, then by frame. The IGBs' blend is
 * SRC_ALPHA, ONE; neon.wpk has the alpha multiplied in (pack_neon.py). */
#define NEON_HALF 29.0f

void lights_draw_neon(const mat4 *proj, const mat4 *view, const float *frame, int pack, int body, int neon, render_params *rp) {
  if (neon < 1 || neon > 12) return;
  if (!L.neon_tried) {
    L.neon_tried = 1;
    if (wpk_load(&L.neon, L.neon_path) != 0) fprintf(stderr, "no %s, no under neons\n", L.neon_path);
  }
  if (L.neon.n_tex < neon) return;
  const float *pl = NEON_PLACE[pack >= 0 && pack < (int)(sizeof NEON_PLACE / sizeof NEON_PLACE[0]) ? pack : 0][body & 3];
  const float *m = view->m, *f = frame;
  const float xs[4] = { -NEON_HALF, NEON_HALF, NEON_HALF, -NEON_HALF }, zs[4] = { NEON_HALF, NEON_HALF, -NEON_HALF, -NEON_HALF };
  const float us[4] = { 0, 1, 1, 0 }, vs[4] = { 0, 0, 1, 1 };
  render_vertex *q = L.v[0];
  for (int k = 0; k < 4; ++k) {
    float l[3] = { xs[k] * pl[3] + pl[0], pl[1], zs[k] * pl[5] + pl[2] }, p[3];
    for (int j = 0; j < 3; ++j) p[j] = f[j] * l[0] + f[4 + j] * l[1] + f[8 + j] * l[2] + f[12 + j];
    for (int j = 0; j < 3; ++j) q[k].pos[j] = m[j] * p[0] + m[4 + j] * p[1] + m[8 + j] * p[2] + m[12 + j];
    q[k].uv[0] = us[k];
    q[k].uv[1] = vs[k];
    q[k].rgba[0] = q[k].rgba[1] = q[k].rgba[2] = q[k].rgba[3] = 255;
  }
  render_sprites(proj, q, 1, L.neon.textures[neon - 1], rp);
}

uint32_t lights_spark_texture(int k) {
  return k >= 0 && k < 2 && L.sprites.n_tex > TEX_SPARK + k ? L.sprites.textures[TEX_SPARK + k] : 0;
}
