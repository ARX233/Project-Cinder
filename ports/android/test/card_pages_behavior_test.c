#include <assert.h>
#include <string.h>
#define WMMT_CARD_UI_MOCK_CHOICES 1
#include "../src/menu.c"
static int missing, volume = 2, fail_save, meter, source; static const char *missing_name;
static int drawn[300000], part_ids[32], nparts; static float part_rect[32][4];
static int story_cells, story_portraits[20], defense_rows;
void anm_draw(int a, int f, float v) { (void)a; (void)f; (void)v; }
void anm_draw_ex(int a, int f, float v, float x, float y, const anm_swap *s, int n) {
  (void)v; (void)n;
  if (a == 2) {
    assert(story_cells < 20 && x == 105 + 108 * (story_cells % 5) && y == 170 + 60 * (story_cells / 5));
    story_portraits[story_cells++] = s[f].to;
  }
  if (a == 3) {
    assert(defense_rows < 8 && x == 319 && y == 189 + 24 * defense_rows);
    defense_rows++;
  }
}
void anm_draw_xy(int a, int f, float v, float x, float y, float sx, float sy, const anm_swap *s, int n) { (void)a;(void)f;(void)v;(void)x;(void)y;(void)sx;(void)sy;(void)s;(void)n; }
void anm_draw_sprite(int s, float x, float y, float a) { (void)x;(void)y;(void)a; if (s >= 0 && s < 300000) drawn[s]++; }
float anm_sprite_width(int s) { (void)s; return 50; }
float anm_sprite_height(int s) { (void)s; return 15; }
int anm_sprites(int a, int *out, int max) { (void)a;(void)out;(void)max; return 0; }
int anm_sprite_id(int s) { return s; }
int anm_sprite_rect(int a, int f, int s, float r[4]) { (void)a;(void)f;(void)s;(void)r; return 0; }
void anm_draw_part(int s, const float src[4], const float dst[4], float alpha) { (void)src;(void)alpha; if(nparts<32) { part_ids[nparts]=s; memcpy(part_rect[nparts],dst,4*sizeof(float)); nparts++; } }
int anm_find(const char *n) {
  if (missing || (missing_name && !strcmp(n, missing_name))) return -1;
  if (!strcmp(n, "menu_g_cardcheck_2_chara")) return 2;
  if (!strcmp(n, "menu_g_cardcheck_14_data")) return 3;
  return 1;
}
int anm_frames(int a) { (void)a; return 1; }
int anm_sprite(int id) { return id; }
void snd_menu(int x) { (void)x; }
int hud_menu_key(float x, float y) { if (y < 700) return 0; if (x < 100) return -1; if (x > 900) return 1; return 0; }
int hud_meter_preview(int pack, int style, float x, float y, float w, float h, float alpha) {
  (void)pack; (void)style; (void)x; (void)y; (void)w; (void)h; (void)alpha; return 1;
}
int app_get_bgm_volume(void) { return volume; }
int app_model_ta_best_ms(int pack, int course) { (void)pack; return course == 0 ? 123456 : 0; }
int title_model(int maker, int car, int color) { (void)maker; (void)car; (void)color; return 0; }
int app_set_bgm_volume(int v) { if (fail_save) return 0; volume = v; return 1; }
int menu_card_meter(const menu_state *m) { (void)m; return meter; }
int menu_card_bgm_source(const menu_state *m) { (void)m; return source; }
int menu_card_choice_available(const menu_state *m, int row, int choice) { (void)m; (void)row; return choice != 2; }
int menu_card_choice_set(menu_state *m, int row, int choice) { (void)m; int *p = row ? &source : &meter; if (*p == choice) return 0; *p = choice; return 1; }
int main(void) {
 menu_state m; memset(&m, 0, sizeof m); m.screen = MENU_CARD; m.card_page = 1; m.card_back = MENU_GARAGE;
 m.ten_result[3][4] = 3;
 for (int p = 2; p <= 9; p++) { m.key = 1; step(&m); assert(m.card_page == p); }
 m.card_action = 31; fail_save = 1; step(&m); assert(volume == 2 && m.card_save_failed); fail_save = 0;
 m.card_action = 31; step(&m); assert(volume == 1 && !m.card_save_failed);
 m.card_action = 42; step(&m); assert(source == 0);
 m.back = 1; step(&m); assert(m.card_page == 8);
 m.card_action = 11; step(&m); assert(m.manual == 1 && m.garage_changed);
 m.card_action = 22; step(&m); assert(meter == 0);
 m.card_action = 21; step(&m); assert(meter == 1);
 for (int p = 7; p >= 1; p--) { m.back = 1; step(&m); assert(m.card_page == p); }
 assert(m.ten_result[3][4] == 3);
 missing = 1; m.key = 1; step(&m); assert(m.card_page == 1);
 m.tap = 1; step(&m); assert(m.deciding > 0); m.deciding = 1;
 menu_update(&m, 1.0f / 60.0f); assert(m.screen == MENU_SETTING);
 /* A single unavailable later page also falls back, and can continue. */
 missing = 0; missing_name = CARD_PAGE_FRAME[6]; memset(&m, 0, sizeof m);
 m.screen = MENU_CARD; m.card_page = 4; m.card_back = MENU_GARAGE; m.tap = 1; step(&m);
 assert(m.card_page == 1 && !m.deciding); m.tap = 1; step(&m); assert(m.deciding > 0);
 m.deciding = 1; menu_update(&m, 1.0f / 60.0f); assert(m.screen == MENU_SETTING);
 missing_name = NULL; memset(&m, 0, sizeof m); m.screen = MENU_CARD; m.card_back = MENU_GARAGE; m.card_page = 9; m.tap = 1; step(&m); assert(m.deciding > 0);
 memset(&m, 0, sizeof m); m.screen = MENU_CARD; m.card_page = 1;
 void *id = (void *)1;
 menu_touch(&m, id, TOUCH_BEGAN, 950, 730); menu_touch(&m, id, TOUCH_MOVED, 500, 500);
 menu_touch(&m, id, TOUCH_ENDED, 500, 500); step(&m); assert(m.card_page == 1);
 menu_touch(&m, id, TOUCH_BEGAN, 950, 730); menu_touch(&m, id, TOUCH_MOVED, -1, -1);
 menu_touch(&m, id, TOUCH_ENDED, -1, -1); step(&m); assert(m.card_page == 1 && !m.card_touch);
 menu_touch(&m, id, TOUCH_BEGAN, 950, 730); menu_touch(&m, id, TOUCH_ENDED, 950, 730);
 step(&m); assert(m.card_page == 2);
 /* Real first-page back path and final page's existing fade destination. */
 memset(&m, 0, sizeof m); m.screen = MENU_CARD; m.card_page = 1; m.card_back = MENU_GARAGE;
 m.n_own = 1; m.own_sel = 0; m.back = 1; step(&m); assert(m.screen == MENU_GARAGE);
 memset(&m, 0, sizeof m); m.screen = MENU_CARD; m.card_page = 9; m.card_back = MENU_GARAGE;
 m.tap = 1; step(&m); assert(m.deciding > 0); m.deciding = 1;
 menu_update(&m, 1.0f / 60.0f); assert(m.screen == MENU_SETTING);
 /* Verified state fields, not the embedded template's example numbers. */
 memset(&m, 0, sizeof m); m.screen = MENU_CARD; m.card_page = 2; m.st_div = 1; m.st_bits = 3;
 memset(drawn, 0, sizeof drawn); draw_card(&m, 0, 1, 0);
 assert(story_cells == 20 && story_portraits[0] == 0x1536 && story_portraits[1] == 0x1537);
 assert(story_portraits[2] == 0x85d && story_portraits[3] == 0x1a51);
 assert(!drawn[0xabd]); /* the historical total is unknown for this saved division */
 m.card_page = 3; m.maker = 0; m.car = 0; m.dress_lv[0][0] = 12;
 m.card_ghost_stats.races = 5; m.card_ghost_stats.wins = 3; m.card_ghost_stats.coins = 4;
 memset(drawn, 0, sizeof drawn); draw_card(&m, 0, 1, 0);
 assert(!drawn[SAVE_TEXT + S_NO_DATA] && drawn[0x488+5] && drawn[0x488+3] && drawn[0x488+4]);
 m.card_page = 4; memset(drawn, 0, sizeof drawn); draw_card(&m, 0, 1, 0);
 assert(drawn[SAVE_TEXT + S_NO_DATA] && defense_rows == 0);
 m.card_ghost_stats.defense_races = 8; m.card_ghost_stats.defense_wins = 2;
 m.card_ghost_stats.defense_recent_count = 8;
 memset(drawn, 0, sizeof drawn); draw_card(&m, 0, 1, 0);
 assert(!drawn[SAVE_TEXT + S_NO_DATA] && drawn[0x493+8] && drawn[0x493+2] && defense_rows == 8);
 m.card_page = 5; m.ten_result[0][0] = 3; m.ten_result[1][1] = 3; m.ten_result[1][2] = 2;
 memset(drawn, 0, sizeof drawn); draw_card(&m, 0, 1, 0);
 assert(drawn[SAVE_TEXT + S_MEDALS] && drawn[SAVE_GLYPH + 2] == 1);
 /* Page 6 uses only known positive local versus counters. */
 m.card_page = 6; m.maker = 0; m.car = 0;
 m.vs_count_car[0][0] = 3; m.vs_wins_car[0][0] = 2; m.vs_stars_car[0][0] = 0;
 memset(drawn, 0, sizeof drawn); draw_card(&m, 0, 1, 0);
 assert(drawn[SAVE_GLYPH + 3] == 1 && drawn[SAVE_GLYPH + 2] == 1 && !drawn[SAVE_GLYPH]);
 /* Page 7 reports model-keyed TA results without treating absent results as zero. */
 m.card_page = 7; m.color = 0;
 memset(drawn, 0, sizeof drawn); draw_card(&m, 0, 1, 0);
 assert(drawn[SAVE_GLYPH + 2] == 1 && drawn[SAVE_GLYPH + 3] == 1 && drawn[SAVE_GLYPH + 6] == 1);
 /* The rendered AT/MT cells are the actual hit-test cells. */
 m.card_page = 8; nparts = 0; draw_card(&m, 0, 1, 0); assert(nparts >= 5);
 assert(part_ids[1] == 0x8b8); float x = (part_rect[1][0] + part_rect[1][2]) * .8f;
 float y = (part_rect[1][1] + part_rect[1][3]) * .8f;
 menu_touch(&m, id, TOUCH_BEGAN, x, y); menu_touch(&m, id, TOUCH_ENDED, x, y); step(&m);
 assert(m.manual == 1);
 return 0;
}
