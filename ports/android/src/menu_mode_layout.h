/* Original menu_layout_mode_sel, resting frames 0/100/200/300: 256px
 * selected and 128px idle sprites centred at y=192 in 640x480 author space.
 * Live VS extends the row with a fifth disc using the same size and spacing.
 * Fit the whole row uniformly on viewports too narrow for the extension. */
#ifndef MENU_MODE_LAYOUT_H
#define MENU_MODE_LAYOUT_H
#include <math.h>

#define MENU_MODE_SLOTS 5
#define MENU_MODE_SLIDE 5

/* At rest the bottom bar starts at y=397 and its artwork spans rows 1..54. */
#define MENU_FOOTER_SCALE 1.16f
#define MENU_FOOTER_OFFSET (480.0f - (397.0f + 55.0f) * MENU_FOOTER_SCALE)
#define MENU_FOOTER_TOP (480.0f - (55.0f - 1.0f) * MENU_FOOTER_SCALE)
#define MENU_FOOTER_CENTER ((MENU_FOOTER_TOP + 480.0f) * 0.5f)
typedef struct { float x, y, w, h; } menu_mode_rect;

static inline int menu_mode_index_valid(int index) { return index >= 0 && index < MENU_MODE_SLOTS; }

static inline void menu_mode_rest(int selected, float scale, menu_mode_rect out[MENU_MODE_SLOTS]) {
  static const float left[MENU_MODE_SLOTS][MENU_MODE_SLOTS] = {
    {11, 262, 376, 490, 604},
    {20, 132, 376, 490, 604},
    {20, 134, 252, 490, 604},
    {20, 134, 248, 375, 604},
    {20, 134, 248, 362, 489},
  };
  for (int i = 0; i < MENU_MODE_SLOTS; ++i) {
    float size = (i == selected ? 256.0f : 128.0f) * scale;
    out[i] = (menu_mode_rect){320.0f + (left[selected][i] - 376.0f) * scale,
                             192.0f - size * 0.5f, size, size};
  }
}

/* Frames 90..94 of each original selection group interpolate by sixths;
 * the first rest frame completes the sixth step. */
static inline int menu_mode_layout(int selected, int from, int tick, float edge,
                                   menu_mode_rect out[MENU_MODE_SLOTS]) {
  if (!out || !menu_mode_index_valid(selected) ||
      (from != -1 && (!menu_mode_index_valid(from) || (selected - from != 1 && from - selected != 1)))) return 0;
  float width = 640.0f + (isfinite(edge) && edge > 0.0f ? 2.0f * edge : 0.0f);
  float scale = fminf(1.0f, width / 748.0f);
  menu_mode_rest(selected, scale, out);
  if (from >= 0) {
    menu_mode_rect start[MENU_MODE_SLOTS];
    menu_mode_rest(from, scale, start);
    float t = tick < 0 ? 0.0f : tick >= MENU_MODE_SLIDE ? 1.0f : (float)(tick + 1) / 6.0f;
    for (int i = 0; i < MENU_MODE_SLOTS; ++i) {
      out[i].x = start[i].x + (out[i].x - start[i].x) * t;
      out[i].y = start[i].y + (out[i].y - start[i].y) * t;
      out[i].w = start[i].w + (out[i].w - start[i].w) * t;
      out[i].h = out[i].w;
    }
  }
  return 1;
}

static inline float menu_mode_edge(float edge) {
  return isfinite(edge) && edge > 0.0f ? fminf(edge, 4096.0f) : 0.0f;
}

/* Fill the content between the existing top/bottom chrome, cropping rather than
 * stretching the source artwork. Source coordinates remain inside its bounds. */
static inline int menu_mode_picture(float width, float height, float edge,
                                    float src[4], menu_mode_rect *dst) {
  if (!src || !dst || !isfinite(width) || !isfinite(height) || width <= 0.0f || height <= 0.0f) return 0;
  edge = menu_mode_edge(edge);
  *dst = (menu_mode_rect){-edge, 84.0f, 640.0f + 2.0f * edge, MENU_FOOTER_TOP - 84.0f};
  float scale = fmaxf(dst->w / width, dst->h / height);
  float sw = dst->w / scale, sh = dst->h / scale;
  src[0] = (width - sw) * 0.5f; src[1] = (height - sh) * 0.5f;
  src[2] = src[0] + sw; src[3] = src[1] + sh;
  return 1;
}

static inline menu_mode_rect menu_mode_detail(float edge) {
  edge = menu_mode_edge(edge);
  return (menu_mode_rect){24.0f - edge, 328.0f, 340.0f, 60.0f};
}

static inline int menu_mode_hit(const menu_mode_rect rect[MENU_MODE_SLOTS], float x, float y) {
  if (!rect || !isfinite(x) || !isfinite(y)) return -1;
  int hit = -1;
  float nearest = 1.0f;
  for (int i = 0; i < MENU_MODE_SLOTS; ++i) {
    float dx = 2.0f * (x - rect[i].x) / rect[i].w - 1.0f;
    float dy = 2.0f * (y - rect[i].y) / rect[i].h - 1.0f;
    float distance = dx * dx + dy * dy;
    if (distance < nearest) nearest = distance, hit = i;
  }
  return hit;
}
#endif
