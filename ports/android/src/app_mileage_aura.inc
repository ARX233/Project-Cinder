/* Original clMenuCarAura and clMenuCar::setMatrix. These effects belong to
 * menu car presentations and use the source IGB meshes and additive materials. */
#include "mileage_aura_pose.inc"

static wpk_scene mileage_aura = {.fd = -1};
static int mileage_aura_glow_tex[4];
static struct {
  int screen;
  int64_t tick;
  double opened_ms;
  float phase;
  uint32_t rng;
} mileage_aura_clock = {.screen = -1};

static void mileage_aura_open(const char *data_dir) {
  char path[1200];
#ifdef __ANDROID__
  (void)data_dir;
  extern int android_optional_resource_path(const char *, char *, size_t);
  if (!android_optional_resource_path("mileage-aura.wpk", path, sizeof path)) return;
#else
  if (snprintf(path, sizeof path, "%s/mileage-aura.wpk", data_dir) >= (int)sizeof path) return;
  if (access(path, R_OK) != 0) return;
#endif
  if (wpk_load(&mileage_aura, path) != 0) return;
  mileage_aura.two_sided = 1;
  const char *const names[] = {"car_aura_glow_g.tga", "nondxt_car_aura_glow_p.tga",
                               "car_aura_glow_r.tga", "car_aura_glow_b.tga"};
  for (int color = 0; color < 4; ++color)
    mileage_aura_glow_tex[color] = wpk_find_texture(&mileage_aura, names[color]);
}

static mat4 mileage_aura_model(const mat4 *car, const char *pack, int aero) {
  for (size_t i = 0; i < sizeof MILEAGE_AURA_POSE / sizeof *MILEAGE_AURA_POSE; ++i) {
    if (strcmp(MILEAGE_AURA_POSE[i].pack, pack)) continue;
    const float *p = MILEAGE_AURA_POSE[i].body[aero >= 0 && aero < 4 ? aero : 0];
    mat4 local = mat4_identity();
    for (int j = 0; j < 3; ++j) {
      local.m[5 * j] = p[j];
      local.m[12 + j] = p[3 + j];
    }
    return mat4_mul(*car, local);
  }
  return *car;
}

static void mileage_aura_tick(double now, int screen) {
  int64_t tick = (int64_t)(now * 0.06); /* one increment per menu tick at any display rate */
  if (mileage_aura_clock.screen != screen || tick < mileage_aura_clock.tick ||
      tick - mileage_aura_clock.tick > 60) {
    mileage_aura_clock.screen = screen;
    mileage_aura_clock.tick = tick - 1;
    mileage_aura_clock.opened_ms = now;
    mileage_aura_clock.phase = 0;
    mileage_aura_clock.rng = (uint32_t)tick;
  }
  while (mileage_aura_clock.tick < tick) {
    mileage_aura_clock.rng = 1664525u * mileage_aura_clock.rng + 1013904223u;
    mileage_aura_clock.phase += (float)(mileage_aura_clock.rng >> 24) * (1.0f / 2048.0f);
    ++mileage_aura_clock.tick;
  }
}

static void mileage_aura_glow(mat4 model, const mat4 *vp, int level, int color, render_params *rp) {
  int texture = mileage_aura_glow_tex[color];
  if (texture < 0 || !mileage_aura.textures[texture]) return;
  static const float box_height[] = {0.5f, 0.6f, 0.7f, 0.8f, 1.0f};
  static const float gain[] = {0.2f, 0.4f, 0.5f, 1.0f, 1.0f};
  for (int i = 0; i < 3; ++i) model.m[4 + i] *= box_height[level];
  mat4 clip = mat4_mul(*vp, model);
  float lo[2] = {INFINITY, INFINITY}, hi[2] = {-INFINITY, -INFINITY};
  for (int i = 0; i < 8; ++i) {
    float x = i & 1 ? 10.0f : -10.0f, y = i & 2 ? 38.0f : 0.0f, z = i & 4 ? 22.0f : -22.0f;
    float w = clip.m[3] * x + clip.m[7] * y + clip.m[11] * z + clip.m[15];
    if (!(w > 0.0f)) return;
    for (int j = 0; j < 2; ++j) {
      float a = (clip.m[j] * x + clip.m[4 + j] * y + clip.m[8 + j] * z + clip.m[12 + j]) / w;
      if (!isfinite(a)) return;
      lo[j] = fminf(lo[j], a);
      hi[j] = fmaxf(hi[j], a);
    }
  }
  float cx = (hi[0] + lo[0]) * 0.5f, cy = (hi[1] + lo[1]) * 0.5f;
  float half_w = (hi[0] - lo[0]) * 0.95f, half_h = (hi[1] - lo[1]) * 1.15f;
  if (half_w <= 0.0f || half_h <= 0.0f || half_w > 4.0f || half_h > 4.0f) return;
  uint8_t light = (uint8_t)(255 * gain[level] * (0.7f + 0.3f * fabsf(sinf(mileage_aura_clock.phase))));
  render_vertex quad[4] = {
    {{cx - half_w, cy - half_h, 0}, {0, 0}, {light, light, light, 255}},
    {{cx + half_w, cy - half_h, 0}, {1, 0}, {light, light, light, 255}},
    {{cx + half_w, cy + half_h, 0}, {1, 1}, {light, light, light, 255}},
    {{cx - half_w, cy + half_h, 0}, {0, 1}, {light, light, light, 255}},
  };
  mat4 screen = mat4_identity();
  render_sprites(&screen, quad, 1, mileage_aura.textures[texture], rp);
}

static void mileage_aura_draw(const menu_car *car, int aero, const mat4 *vp,
                              const mat4 *body, const float *eye, render_params *rp) {
  if (!mileage_aura.n_batch || !car->story_body_valid || car->story_body.kind != 1) return;
  int index = car->story_body.own_index;
  if (index < 0 || index >= G.menu.n_own) return;
  const menu_own *own = &G.menu.own[index];
  int level = mileage_aura_level(own->odo);
  if (level < 0 || car->pack < 0 || car->pack >= CARDB_NPACKS) return;
  int color = mileage_aura_color(G.menu.drive_style_car[own->maker][own->car]);
  mat4 model = mileage_aura_model(body, CARDB_PACKS[car->pack], aero);
  mileage_aura_tick(G.frame_start, G.menu.screen);
  const double period = 14.983333587;
  float seconds = (float)fmod((G.frame_start - mileage_aura_clock.opened_ms) * 0.001, period);
  float lift = 1.0f - (float)(0.999 * seconds / period);
  for (int rise = 0; rise < 2; ++rise) {
    mat4 part = model;
    for (int j = 0; j < 3; ++j) part.m[12 + j] += model.m[4 + j] * (2 + 2 * rise) * lift;
    float local_eye[3];
    eye_in(&part, eye, local_eye);
    for (int j = 0; j < 3; ++j) local_eye[j] /= v3_dot(part.m + 4 * j, part.m + 4 * j);
    for (int i = 0; i <= level; ++i)
      wpk_draw_group(&mileage_aura, vp, &part, local_eye, WPK_BLEND, rp, (uint32_t)(16 * color + 1 + 2 * i + rise));
  }
  mileage_aura_glow(model, vp, level, color, rp);
}
