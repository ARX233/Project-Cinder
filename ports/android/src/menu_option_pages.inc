/* Shared drawing and touch geometry in the 640x480 menu coordinate system. */
enum { OPTION_CONTROLS, OPTION_GRAPHICS, OPTION_PAGES };
typedef struct { float x, y, w, h; } option_rect;
static const option_rect OPTION_TABS[OPTION_PAGES] = {{52, 99, 262, 30}, {326, 99, 262, 30}};
static const char *const OPTION_PAGE_NAMES[] = {"1  CONTROLS", "2  GRAPHICS"};
static const char *const OPTION_STEERING[] = {"BUTTONS", "GYRO", "WHEEL", "STICK"};
static const char *const OPTION_TOGGLE[] = {"ON", "OFF"};
static const char *const OPTION_RESOLUTION[] = {"1024 X 768", "2048 X 1536"};
static const char *const OPTION_AA[] = {"4X", "2X"};
static const char *const OPTION_GRAPHICS_LABELS[] = {
  "BRIDGE REFLECTION", "FSR SHARPENING", "AMBIENT OCCLUSION", "BACK MIRROR", "HD TEXTURES",
  "BLOOM", "SSAO", "WET ROAD", "PAINT REFLECTION", "ANTI-ALIASING",
};
static const float OPTION_RES_Y = 379;
static const option_rect OPTION_LAYOUT = {254, 317, 290, 27};
static const float OPTION_SCALE = 1024.0f / 640.0f;

static int option_hit(const menu_state *m, option_rect r) {
  return m->tap_x >= r.x && m->tap_x < r.x + r.w && m->tap_y >= r.y && m->tap_y < r.y + r.h;
}

static option_rect option_choice(float x, float cy, float w, float step, int i) {
  return (option_rect){x + i * step, cy - 10, w, 20};
}

static option_rect option_graphics_row(int i) {
  return (option_rect){i < 5 ? 52 : 326, 145 + 33 * (i % 5), 262, 29};
}

static void option_page_set(menu_state *m, int page) {
  if (page < 0 || page >= OPTION_PAGES || page == m->opt_page) return;
  m->opt_page = page;
  snd_menu(SND_CURSOR);
}

static void option_step(menu_state *m, int tap, int key) {
  if (key) { option_page_set(m, m->opt_page + key); return; }
  if (!tap) return;
  for (int i = 0; i < OPTION_PAGES; ++i) {
    if (option_hit(m, OPTION_TABS[i])) { option_page_set(m, i); return; }
  }
  if (m->opt_page == OPTION_CONTROLS) {
    if (option_hit(m, OPTION_LAYOUT)) { snd_menu(SND_SELECT); layout_enter(m); return; }
    for (int i = 0; i < 4; ++i) {
      if (i == m->gyro || !option_hit(m, option_choice(254, 171, 68, 74, i))) continue;
      option_set(m, &m->gyro, i);
      for (int g = 0; g < HUD_KEY_GROUPS; ++g) layout_clamp(m, g);
      layout_apply(m);
      return;
    }
    if (m->gyro == HUD_STEER_GYRO) {
      for (int i = 0; i < 10; ++i)
        if (option_hit(m, option_choice(254, 224, 21, 24, i))) { option_set(m, &m->gyro_sens, i + 1); return; }
    }
    for (int i = 0; i < 2; ++i)
      if (option_hit(m, option_choice(254, 277, 68, 74, i))) { option_set(m, &m->pedal_slide, !i); return; }
    return;
  }
  int *const values[] = {
    &m->over_on, &m->sharp_on, &m->ao_on, &m->bm_on, &m->hd_tex,
    &m->bloom_on, &m->ssao_on, &m->wet_on, &m->paint_on, &m->aa4,
  };
  for (int row = 0; row < (m->hq_rows ? 10 : 4); ++row) {
    option_rect r = option_graphics_row(row);
    for (int i = 0; i < 2; ++i)
      if (option_hit(m, option_choice(r.x + 174, r.y + 14.5f, 35, 42, i))) {
        option_set(m, values[row], !i);
        return;
      }
  }
  if (m->res_row) {
    for (int i = 0; i < 2; ++i)
      if (option_hit(m, option_choice(254, OPTION_RES_Y, 130, 144, i))) {
        option_set(m, &m->hires, i);
        return;
      }
  }
  option_fps_step(m);
}

static void option_panel(option_rect r) {
  const float k = OPTION_SCALE;
  hud_ui_rect(r.x * k, r.y * k, r.w * k, r.h * k, 0.15f, 0.17f, 0.21f, 0.76f);
  hud_ui_rect(r.x * k, r.y * k, r.w * k, 1.5f, 1, 1, 1, 0.19f);
}

static void option_label(const char *label, float x, float cy, float size, float alpha) {
  hud_ui_text(label, x * OPTION_SCALE, cy * OPTION_SCALE - 3.5f * size, size, 1, 1, 1, alpha);
}

static void option_button(option_rect r, const char *label, float size, int selected) {
  const float k = OPTION_SCALE;
  hud_ui_button(r.x * k, r.y * k, r.w * k, r.h * k, selected);
  option_label(label, r.x + (r.w - hud_ui_text_width(label, size) / k) * 0.5f, r.y + r.h * 0.5f, size, 1);
}

static void draw_option(const menu_state *m, int clock, int bars, float screen_w, float screen_h) {
  draw_back(ID.bg, clock % 600, 1);
  anm_draw(ID.line, clock % anm_frames(ID.line), 1);
  anm_swap title = { anm_sprite(T_TOPBAR_MES), anm_sprite(OPT_TEXT + O_TITLE) };
  draw_topbar(bars, 1, &title);
  draw_bottombar(bars, 1);
  hud_ui_begin(screen_w, screen_h);
  for (int i = 0; i < OPTION_PAGES; ++i)
    option_button(OPTION_TABS[i], OPTION_PAGE_NAMES[i], 3, i == m->opt_page);
  if (m->opt_page == OPTION_CONTROLS) {
    static const char *const labels[] = {"STEERING", "GYRO SENSITIVITY", "SLIDER PEDALS", "RACE BUTTONS"};
    for (int i = 0; i < 4; ++i) {
      float y = 171 + 53 * i;
      option_panel((option_rect){52, y - 21, 536, 42});
      option_label(labels[i], 68, y, 2.7f, i == 1 && m->gyro != HUD_STEER_GYRO ? 0.55f : 1);
    }
    for (int i = 0; i < 4; ++i)
      option_button(option_choice(254, 171, 68, 74, i), OPTION_STEERING[i], 2.3f, i == m->gyro);
    for (int i = 0; i < 10; ++i) {
      option_rect r = option_choice(254, 224, 21, 24, i);
      if (m->gyro == HUD_STEER_GYRO) option_button(r, "", 2, i < m->gyro_sens);
      else hud_ui_rect(r.x * OPTION_SCALE, r.y * OPTION_SCALE, r.w * OPTION_SCALE, r.h * OPTION_SCALE, 0, 0, 0, 0.23f);
    }
    char value[8];
    snprintf(value, sizeof value, "%d", m->gyro_sens);
    option_label(value, 509, 224, 3.5f, m->gyro == HUD_STEER_GYRO ? 1 : 0.55f);
    for (int i = 0; i < 2; ++i)
      option_button(option_choice(254, 277, 68, 74, i), OPTION_TOGGLE[i], 2.5f, (1 - i) == m->pedal_slide);
    option_button(OPTION_LAYOUT, "KEY LAYOUT >", 2.7f, 0);
  } else {
    const int values[] = {
      m->over_on, m->sharp_on, m->ao_on, m->bm_on, m->hd_tex,
      m->bloom_on, m->ssao_on, m->wet_on, m->paint_on, m->aa4,
    };
    for (int row = 0; row < (m->hq_rows ? 10 : 4); ++row) {
      option_rect r = option_graphics_row(row);
      float y = r.y + 14.5f;
      option_panel(r);
      option_label(OPTION_GRAPHICS_LABELS[row], r.x + 12, y, 2.1f, 1);
      for (int i = 0; i < 2; ++i)
        option_button(option_choice(r.x + 174, y, 35, 42, i), (row == 9 ? OPTION_AA : OPTION_TOGGLE)[i],
                      2.2f, (1 - i) == values[row]);
    }
    option_panel((option_rect){52, OPT_FPS_Y - 21, 536, 42});
    option_label("FRAME RATE LIMIT", 68, OPT_FPS_Y, 2.7f, 1);
    for (int i = 0; i < 4; ++i)
      option_button(option_choice(OPT_FPS_X, OPT_FPS_Y, OPT_FPS_W, OPT_FPS_STEP, i),
                    OPT_FPS_LABELS[i], 2.3f, m->frame_rate_limit == OPT_FPS_LIMITS[i]);
    if (m->res_row) {
      option_panel((option_rect){52, OPTION_RES_Y - 15, 536, 30});
      option_label("RESOLUTION (NEXT START)", 68, OPTION_RES_Y, 2.0f, 1);
      for (int i = 0; i < 2; ++i)
        option_button(option_choice(254, OPTION_RES_Y, 130, 144, i), OPTION_RESOLUTION[i], 2.2f, i == m->hires);
    }
  }
  hud_ui_end();
}
