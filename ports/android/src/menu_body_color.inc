/* Original clseqCardCustomColorSelectThread (0x87ccaec/0x87d6800).
 * Extra-colour availability is the user's explicit PORT policy, not a forged
 * card renewal count. No IO, model/type mutation, texture upload or RNG here. */
#include "body_color_assets_private.h"
static void tg_select_open(menu_state *m);

static const body_color_row *body_row_for(int maker, int car, int factory) {
  if (maker < 0 || maker >= CARDB_ALL || car < 0 || car >= CARDB_NCARS[maker] ||
      factory < 0 || factory >= CARDB_CARS[maker][car].ncolors) return NULL;
  const cardb_color *c = &CARDB_CARS[maker][car].colors[factory];
  for (int i = 0; i < BODY_COLOR_ROWS_COUNT; ++i) {
    const body_color_row *r = BODY_COLOR_ROWS + i;
    if (r->maker == maker && r->car == car && r->factory == factory)
      return r->pack == c->pack && r->paint == c->paint && r->type == c->type ? r : NULL;
  }
  return NULL; /* never canonicalize an ambiguous pack/paint back into a raw ID */
}
static const body_color_row *body_row(const menu_state *m) {
  return m ? body_row_for(m->maker, m->car, m->color) : NULL;
}

static int body_extra_raw(int raw) {
  if (raw >= 232 && raw <= 242) return 0; /* original isR35, including SpecV */
  if (raw >= 224 && raw <= 231) return 0; /* PORT: eight hidden frontend aliases
    * lack reviewed canonical appearance-only page bindings; stock0 stays valid. */
  return raw >= 0 && raw < 247;
}

int menu_body_color_restore(menu_state *m, int maker, int car, int custom) {
  if (!m || custom < 0 || custom > 10) return 0;
  int k = menu_own_find(m, maker, car);
  if (k < 0) return 0;
  const body_color_row *r = body_row_for(maker, car, m->own[k].color);
  if (!r || (custom && (!body_extra_raw(r->raw_model) ||
      r->swatch[custom-1] <= 3 || r->name[custom-1] <= 0))) return 0;
  m->custom_color[maker][car] = (unsigned char)custom;
  return 1; /* hydration only: no resource dependency, normalization or dirty edge */
}

static int body_owned(const menu_state *m) {
  if (m->save_skip) return -1; /* guest remains session-only */
  int k = menu_own_find(m, m->maker, m->car);
  return k >= 0 && k == m->own_sel && m->own[k].color == m->color ? k : -1;
}

void menu_body_color_clear_pages(menu_state *m) {
  if (m) memset(&m->body_pages, 0, sizeof m->body_pages);
}

int menu_body_color_set_pages(menu_state *m, int raw_model, unsigned mask) {
  const body_color_row *r = body_row(m);
  if (!r || raw_model != r->raw_model || mask & ~0x7ffu) return 0;
  m->body_pages.raw_model = raw_model;
  m->body_pages.maker = m->maker; m->body_pages.car = m->car;
  m->body_pages.factory = m->color; m->body_pages.aero = m->aero[m->maker][m->car];
  m->body_pages.save_slot = m->save_slot; m->body_pages.save_skip = m->save_skip;
  m->body_pages.mask = mask;
  return 1;
}

static unsigned body_mask(const menu_state *m, const body_color_row *r) {
  if (!r || !body_extra_raw(r->raw_model)) return 0;
  if (m->body_pages.raw_model != r->raw_model || m->body_pages.maker != m->maker ||
      m->body_pages.car != m->car || m->body_pages.factory != m->color ||
      m->body_pages.aero != m->aero[m->maker][m->car] ||
      m->body_pages.save_slot != m->save_slot || m->body_pages.save_skip != m->save_skip) return 0;
  unsigned mask = m->body_pages.mask & 0x7ffu;
  for (int i = 0; i < 10; ++i)
    if (r->swatch[i] <= 3 || r->name[i] <= 0 || anm_sprite(r->swatch[i]) < 0 || anm_sprite(r->name[i]) < 0)
      mask &= ~(2u << i);
  return mask;
}

static int body_art(void) {
  return anm_frames(anm_find("menu_g_carsel_col_11")) == 1060 &&
         anm_frames(anm_find("menu_g_carsel_col_11_arrow")) == 1999 &&
         anm_sprite(7767) >= 0;
}

static int body_owner_same(const menu_state *m) {
  const body_color_row *r = body_row(m);
  if (!m->body_edit.active || !r || m->maker != m->body_edit.maker ||
      m->car != m->body_edit.car || m->color != m->body_edit.factory ||
      r->raw_model != m->body_edit.raw_model || m->save_slot != m->body_edit.save_slot ||
      m->save_skip != m->body_edit.save_skip || m->aero[m->maker][m->car] != m->body_edit.aero ||
      m->custom_color[m->maker][m->car] != m->body_edit.before) return 0;
  int k = body_owned(m);
  return k == m->body_edit.own && (k < 0 || m->own[k].born == m->body_edit.born);
}

int menu_body_color_get(const menu_state *m, menu_body_color_view *out) {
  if (!out) return 0;
  memset(out, 0, sizeof *out);
  const body_color_row *r = body_row(m);
  if (!r) return 0;
  int custom = m->custom_color[m->maker][m->car];
  if (m->screen == MENU_BODY_COLOR) {
    if (!body_owner_same(m)) return 0;
    custom = m->sel;
  }
  if (custom < 0 || custom > 10 || (custom &&
      (!body_extra_raw(r->raw_model) || r->name[custom-1] <= 0 ||
       r->swatch[custom-1] <= 3 || (m->screen == MENU_BODY_COLOR &&
       !(body_mask(m, r) & (1u << custom)))))) return 0;
  *out = (menu_body_color_view){ r->raw_model, r->pack, r->paint, r->type, custom,
      m->aero[m->maker][m->car], m->vinyl[m->maker][m->car], m->bonnet[m->maker][m->car] };
  return 1;
}

static int body_available(const menu_state *m) {
  const body_color_row *r = body_row(m);
  if (!m->dress_free || m->new_card || !r || !body_art()) return 0;
  /* Follow existing free-parts access. Guests can confirm for this session but
   * cannot create or dirty a registered save. Invalid committed bytes fail closed. */
  int v = m->custom_color[m->maker][m->car];
  unsigned mask = body_mask(m, r);
  return v >= 0 && v <= 10 && (mask & 1u) && (mask & (1u << v)) && (mask & 0x7feu);
}

static int body_open(menu_state *m) {
  if (!body_available(m)) return 0;
  const body_color_row *r = body_row(m);
  int k = body_owned(m), v = m->custom_color[m->maker][m->car];
  memset(&m->body_edit, 0, sizeof m->body_edit);
  m->body_edit.active = 1; m->body_edit.own = k;
  m->body_edit.born = k >= 0 ? m->own[k].born : 0;
  m->body_edit.maker = m->maker; m->body_edit.car = m->car;
  m->body_edit.factory = m->color; m->body_edit.raw_model = r->raw_model;
  m->body_edit.save_slot = m->save_slot; m->body_edit.save_skip = m->save_skip;
  m->body_edit.aero = m->aero[m->maker][m->car]; m->body_edit.before = v;
  go(m, MENU_BODY_COLOR); m->sel = v; m->spin = -24.0f; m->body_tab_focus = 0;
  return 1;
}

static void body_close(menu_state *m, int commit) {
  if (commit && body_owner_same(m) && m->sel >= 0 && m->sel <= 10 &&
      (body_mask(m, body_row(m)) & (1u << m->sel)) &&
      m->sel != m->body_edit.before) {
    m->custom_color[m->maker][m->car] = (unsigned char)m->sel;
    if (m->body_edit.own >= 0 && m->save_slot >= 1 && m->save_slot <= MENU_SAVES)
      m->garage_changed = 1; /* APP persists once; previews never raise this. */
  }
  memset(&m->body_edit, 0, sizeof m->body_edit);
  tg_select_open(m);
}

/* Native 100-frame places, 59-frame idle and six-frame moves. There is NO
 * +60 decide strip (the last place ends at1059). Original run holds30 frames
 * (0x9771198), then fades over1/6s; private confirm never enters the unrelated
 * menu_update global deciding dispatcher. */
static int body_frame(const menu_state *m) { return color_frame(m); }
static int body_arrow_frame(const menu_state *m) {
  int k = m->from >= 0 ? m->from : m->sel;
  return (k == 10 ? 11 : k) * 100 + m->t % 59;
}

static int body_hit(const menu_state *m) {
  int strip = anm_find("menu_g_carsel_col_11"), frame = body_frame(m);
  unsigned mask = body_mask(m, body_row(m));
  for (int i = 0; i <= 10; ++i) {
    float r[4];
    if ((mask & (1u << i)) && anm_sprite_rect(strip, frame, anm_sprite(7661 - i), r) &&
        m->tap_x >= r[0] && m->tap_x < r[2] && m->tap_y >= r[1] && m->tap_y < r[3]) return i;
  }
  return -1;
}

static void body_step(menu_state *m, int tap, int key, int back) {
  if (back || !body_owner_same(m) || !body_art() || m->sel < 0 || m->sel > 10 ||
      !(body_mask(m, body_row(m)) & (1u << m->sel))) {
    snd_menu(SND_CANCEL); body_close(m, 0); return;
  }
  m->spin -= 0.3f;
  if (m->body_edit.confirm) {
    if (++m->body_edit.confirm > 40) body_close(m, 1);
    return;
  }
  if (m->from >= 0) {
    if (m->t >= COLOR_MOVE) { m->from = -1; m->t = 0; }
    return;
  }
  if (!tap && !key) return;
  int target = key ? m->sel + (key > 0 ? 1 : -1) : body_hit(m);
  if (target >= 0 && target != m->sel) {
    int direction = target > m->sel ? 1 : -1;
    target = m->sel + direction; /* touch emulates one native steering step */
    unsigned mask = body_mask(m, body_row(m));
    while (target >= 0 && target <= 10 && !(mask & (1u << target))) target += direction;
  }
  if (target < 0 || target > 10) return; /* empty space never confirms */
  if (target == m->sel) {
    if (!key) { snd_menu(SND_SELECT); m->body_edit.confirm = 1; }
  } else {
    snd_menu(SND_CURSOR); m->from = m->sel; m->sel = target; m->t = 0;
  }
}

/* Extra part card on the native dress-up strip (y=343). Its factory
 * swatch and label are original sprites; paint authority remains body_available. */
static int body_tab_show(const menu_state *m) {
  const body_color_row *r = body_row(m);
  return m->dress_free && !m->new_card && r && body_extra_raw(r->raw_model) &&
         anm_sprite(7767) >= 0 && anm_sprite(4954) >= 0;
}

static float body_row_scale(const menu_state *m) {
  if (!body_tab_show(m)) return 1.0f;
  float width = 640.0f + 2.0f * anm_edge() * (640.0f / 1024.0f);
  return fminf(1.0f, width / 720.0f);
}

static float body_row_x(const menu_state *m, float scale) {
  return body_tab_show(m) ? 320.0f - 354.0f * scale : 0.0f;
}

static void body_tab_rect(const menu_state *m, float r[4]) {
  float scale = body_row_scale(m);
  float x = (m->tg.gem ? 644.0f : 655.0f) * scale + body_row_x(m, scale);
  float w = (m->body_tab_focus ? 74.0f : 57.0f) * scale;
  float h = (m->body_tab_focus ? 62.0f : 48.0f) * scale;
  r[0] = x - w * 0.5f; r[1] = 343.0f - h * 0.5f;
  r[2] = x + w * 0.5f; r[3] = 343.0f + h * 0.5f;
}

static int body_tab_hit(const menu_state *m) {
  if (!body_tab_show(m)) return 0;
  float r[4];
  body_tab_rect(m, r);
  return m->tap_x >= r[0] && m->tap_x < r[2] && m->tap_y >= r[1] && m->tap_y < r[3];
}

static void body_tab_draw(const menu_state *m) {
  if (!body_tab_show(m)) return;
  const body_color_row *r = body_row(m);
  const cardb_color *c = &CARDB_CARS[m->maker][m->car].colors[m->color];
  int custom = m->custom_color[m->maker][m->car];
  int swatch = anm_sprite(custom > 0 && custom <= 10 ? r->swatch[custom-1] : c->swatch);
  if (swatch < 0) swatch = anm_sprite(c->swatch);

  float box[4];
  body_tab_rect(m, box);
  float w = box[2] - box[0], h = box[3] - box[1];
  float alpha = body_available(m) ? 1.0f : 0.52f;
  const float frame_src[4] = {6,6,122,122};
  anm_draw_part(anm_sprite(4954), frame_src, box, alpha);
  float sw = anm_sprite_width(swatch), sh = anm_sprite_height(swatch);
  if (sw > 0 && sh > 0) {
    float y = box[1]+h*.18f;
    const float swatch_src[4] = {0,0,sw,sh};
    const float swatch_dst[4] = {box[0]+w*.22f,y,box[2]-w*.22f,y+w*.56f*sh/sw};
    anm_draw_part(swatch, swatch_src, swatch_dst, alpha);
  }
  /* ボディカラー, cropped at the end of the long vowel in the original title. */
  const float label_src[4] = {2,0,148,33};
  float y = box[1]+h*.63f;
  const float label_dst[4] = {box[0]+w*.07f,y,box[2]-w*.07f,y+w*.86f*33.0f/146.0f};
  anm_draw_part(anm_sprite(7767), label_src, label_dst, alpha);
}

static void draw_body_color(const menu_state *m, void (*draw3d)(void *), void *ctx) {
  const body_color_row *r = body_row(m);
  if (!r || !body_owner_same(m)) return;
  const cardb_car *c = chosen_car(m, m->car);
  draw_back(ID.bg_carsel, m->t % 240, 1); draw_bg_logo(c, m->t % 240, 1);
  anm_draw(ID.line, m->t % anm_frames(ID.line), 1);
  if (draw3d) draw3d(ctx);
  anm_swap info[3]; int n = car_swaps(c, info);
  anm_draw_ex(ID.car_info, m->t % 240, 1, 0, 0, info, n);
  anm_swap sw[11]; unsigned mask = body_mask(m, r);
  for (int i = 0; i <= 10; ++i) sw[i] = (anm_swap){anm_sprite(7661-i),
      !(mask & (1u<<i)) ? -1 : anm_sprite(i ? r->swatch[i-1] : c->colors[m->color].swatch)};
  int frame = body_frame(m);
  anm_draw_ex(anm_find("menu_g_carsel_col_11"), frame, 1, 0, 0, sw, 11);
  anm_draw(anm_find("menu_g_carsel_col_11_arrow"), body_arrow_frame(m), 1);
  anm_swap none = {anm_sprite(T_COL_FONT),-1}; anm_draw_ex(ID.col_name,0,1,0,0,&none,1);
  int name = anm_sprite(m->sel ? r->name[m->sel-1] : c->colors[m->color].name);
  anm_draw_sprite(name,624-anm_sprite_width(name),316,1);
}
