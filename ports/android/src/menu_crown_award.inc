/* clSeqTgCrownGetThread constructor, run and yield, 0x887fb68,
 * 0x8880758 and 0x887e52c of the reviewed 3DX+ main. */
static void crown_award_sprite(int sprite, float x, float y, float scale, float opacity) {
  if (sprite < 0 || opacity <= 0) return;
  float w = anm_sprite_width(sprite), h = anm_sprite_height(sprite);
  const float src[4] = {0, 0, w, h};
  const float dst[4] = {x - w * scale / 2, y - h * scale / 2,
                       x + w * scale / 2, y + h * scale / 2};
  anm_draw_part(sprite, src, dst, opacity);
}

static int crown_award_slot(int area) {
  /* The original ANM puts Fukuoka before Hakone. The saved crown mask uses
   * raw clEffAreaType order, which has Hakone before Fukuoka. */
  return area < 6 ? area : 13 - area;
}

static void draw_crown_award(const menu_state *m, float screen_w, float screen_h,
                             void (*draw3d)(void *), void *ctx) {
  const int base = 140000;
  const int emblem[8] = {1773, 1779, 1780, 1781, 1777, 1778, 1775, 1776};
  const int caption[8] = {2779, 2784, 2785, 2786, 2782, 2783, 2780, 2781};
  const float slot[8][2] = {{58,175},{131,158},{201,141},{278,124},
                            {357,128},{435,141},{507,158},{584,175}};
  int area = m->crown_award.area;
  int art = crown_award_slot(area);
  int t = m->t - CROWN_AWARD_FADE;
  int frame = t < 0 ? 0 : t;
  int original = ID.crown_award_a >= 0 && ID.crown_award_b >= 0;
  int bg = ID.crown_award_bg;
  if (bg >= 0) {
    float edge = anm_edge() * (640.0f / 1024.0f);
    const float src[4] = {0, 0, anm_sprite_width(bg), anm_sprite_height(bg)};
    const float dst[4] = {-edge, 0, 640 + edge, 480};
    anm_draw_part(bg, src, dst, 1);
    photo_bg = 1;
  } else draw_back(ID.bg, m->t % 600, 1);
  if (draw3d) draw3d(ctx);

  if (original) {
    anm_draw(ID.crown_award_frame, 0, 1);
    anm_draw(ID.crown_award_title, frame < 160 ? frame : 159, 1);
    for (int i = 0; i < 8; ++i)
      if (i != area && (m->crown_award.owned & (1u << i)))
        anm_draw(ID.crown_award_b, 60 * crown_award_slot(i) + 59, 1);
    if (t < CROWN_AWARD_MOVE) {
      anm_swap icon = {anm_sprite(base + 1773), anm_sprite(base + emblem[art])};
      anm_draw_ex(ID.crown_award_a, frame < 160 ? frame : 159, 1, 0, 0, &icon, 1);
    } else if (t >= CROWN_AWARD_LAND) {
      int land = t - CROWN_AWARD_LAND + 1;
      anm_draw(ID.crown_award_b, 60 * art + (land < 60 ? land : 59), 1);
      int message = t - CROWN_AWARD_LAND;
      if (crown_award_all(m) && t >= 351)
        anm_draw(ID.crown_award_complete, t - 351, 1);
      else if (message < 100) {
        anm_swap label = {anm_sprite(base + 2784), anm_sprite(base + caption[art])};
        anm_draw_ex(ID.crown_award_message, message, 1, 0, 0, &label, 1);
      }
    }
  } else if (t >= CROWN_AWARD_REVEAL) {
    hud_ui_begin(screen_w, screen_h);
    game_text("COURSE CROWN ACQUIRED", 320, 46, 3.2f, 1);
    hud_ui_end();
  }

  if (t >= CROWN_AWARD_MOVE && (t < CROWN_AWARD_LAND || !original)) {
    float p = fminf(1, (t - CROWN_AWARD_MOVE) / 30.0f);
    float wave = sinf(TWO_PI * p);
    float x = 320 + (slot[art][0] - 320) * p + (art < 3 ? 15 : -15) * wave;
    float y = 200 + (slot[art][1] - 200) * p + 20 * (1 - cosf(TWO_PI * p));
    int sprite = anm_sprite(base + emblem[art]);
    if (sprite < 0) sprite = anm_sprite(130000 + emblem[art]);
    if (sprite < 0) sprite = anm_sprite(ghost_original_crown((unsigned)area)->menu);
    crown_award_sprite(sprite, x, y, 1.0f - 0.65625f * p, 1);
  } else if (!original && t >= CROWN_AWARD_REVEAL) {
    int sprite = anm_sprite(130000 + emblem[art]);
    if (sprite < 0) sprite = anm_sprite(ghost_original_crown((unsigned)area)->menu);
    crown_award_sprite(sprite, 320, 200, 1, fminf(1, (t - CROWN_AWARD_REVEAL) / 15.0f));
  }
  int end = crown_award_all(m) ? CROWN_AWARD_ALL : CROWN_AWARD_NORMAL;
  float shade = t < 0 ? -t / (float)CROWN_AWARD_FADE :
      t > end ? (t - end) / (float)CROWN_AWARD_FADE : 0;
  if (shade > 0) anm_fill(0, 0, 0, shade);
}
