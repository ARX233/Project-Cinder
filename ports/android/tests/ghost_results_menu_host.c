/* Full production menu.c and original generated car/dress data. GPU calls
 * record which result animation is submitted, without initializing GL. */
#define main story_timezone_test_main
#include "story_timezone_host.c"
#undef main

enum { WIN = 1, LOSE, TIMEUP, ADVANTAGE, GAUGE_FRAME, GAUGE_BAR, GAUGE_TEXT };
static int drawn[GAUGE_TEXT + 1];

void anm_draw(int anim, int frame, float alpha) {
  assert(anim >= WIN && anim <= GAUGE_TEXT && frame >= 0 && alpha >= 0 && alpha <= 1);
  ++drawn[anim];
}
void anm_draw_ex(int anim, int frame, float alpha, float dx, float dy, const anm_swap *swaps, int n) {
  (void)dx; (void)dy; (void)swaps; (void)n;
  anm_draw(anim, frame, alpha);
}
void anm_fill(float r, float g, float b, float a) {
  assert(r == 0 && g == 0 && b == 0 && a > 0 && a <= 1);
}
int anm_frames(int anim) { return anim == WIN ? 150 : 300; }
void snd_menu_loop(int which, int on) { (void)which; (void)on; }

static void setup(menu_state *m, int level, int points) {
  memset(m, 0, sizeof *m);
  memset(drawn, 0, sizeof drawn);
  m->game = MENU_GAME_GHOST;
  m->screen = MENU_GHOST_PRE;
  m->n_own = 1;
  m->own[0] = (menu_own){.maker = 1, .car = 2, .born = 1};
  m->maker = 1;
  m->car = 2;
  assert(!tg_gem(m) && !tg_wheels_only(m));
  m->dress_lv[1][2] = level;
  m->dress_points[1][2] = points;
}

static void finish(menu_state *m, int expected_screen, int expected_banner, int expected_gauge) {
  int ticks = m->finish_wait + ST_RES_LEN + RES_OUT_FADE;
  for (int i = 0; i < ticks; ++i) {
    assert(m->screen == MENU_GHOST_PRE);
    m->tap = 1; /* early and repeated input never skips settlement */
    if (i + 1 == ticks)
      assert(menu_finish_update(m, 1.0f / 60.0f) == MENU_LEAVE);
    else {
      assert(menu_finish_update(m, 1.0f / 60.0f) == MENU_PAUSED);
      menu_finish_draw(m);
    }
  }
  assert(!m->finish && !m->finish_ghost && m->screen == expected_screen);
  assert(drawn[expected_banner] > 0);
  assert(!!drawn[GAUGE_BAR] == expected_gauge);
  assert(!!drawn[GAUGE_TEXT] == expected_gauge);
}

int main(void) {
  menu_state m;
  ID.win = WIN; ID.lose = LOSE; ID.ten_timeup = TIMEUP; ID.st_adv = ADVANTAGE;
  ID.st_waku = GAUGE_FRAME; ID.tg_result_bar = GAUGE_BAR; ID.tg_result_moji = GAUGE_TEXT;

  setup(&m, 10, 400);
  menu_finish_ghost(&m, MENU_GHOST_RESULT_WIN, 1, 36.0f, 3, 3);
  assert(m.dress_points[1][2] == 900 && m.dress_lv[1][2] == 10 && m.garage_changed);
  finish(&m, MENU_GHOST, WIN, 1);

  setup(&m, 10, 700);
  menu_finish_ghost(&m, MENU_GHOST_RESULT_WIN, 1, 36.0f, 3, 4);
  assert(m.dress_points[1][2] == 0 && m.dress_lv[1][2] == 11 && m.n_dress_due == 1);
  menu_finish_ghost(&m, MENU_GHOST_RESULT_WIN, 1, 36.0f, 3, 4);
  assert(m.dress_lv[1][2] == 11 && m.n_dress_due == 1);
  finish(&m, MENU_TG_GET, WIN, 1);
  assert(m.tg.kind == 1 && !m.n_dress_due);
  tg_leave(&m);
  assert(m.screen == MENU_GHOST);

  setup(&m, 63, 0);
  menu_finish_ghost(&m, MENU_GHOST_RESULT_WIN, 1, 36.0f, 3, 4);
  assert(!m.garage_changed && m.dress_lv[1][2] == 63 && !m.n_dress_due);
  finish(&m, MENU_GHOST, WIN, 0);

  setup(&m, 10, 400);
  menu_finish_ghost(&m, MENU_GHOST_RESULT_LOSE, 1, -36.0f, 3, 3);
  assert(m.dress_points[1][2] == 650 && m.dress_lv[1][2] == 10 && !m.n_dress_due);
  finish(&m, MENU_GHOST, LOSE, 1);

  setup(&m, 10, 400);
  menu_finish_ghost(&m, MENU_GHOST_RESULT_LOSE, 0, -36.0f, 3, 3);
  assert(m.dress_points[1][2] == 400 && !m.garage_changed);
  finish(&m, MENU_GHOST, TIMEUP, 0);

  setup(&m, 10, 400);
  menu_finish_ghost(&m, MENU_GHOST_RESULT_INVALID, 0, 0, 3, 3);
  assert(!m.finish && !m.n_dress_due && !m.garage_changed && m.dress_points[1][2] == 400);
  puts("PASS full production Ghost results: 420-frame settlement, correct draw route, one part, maxed, loss, time-up, invalid");
  return 0;
}
