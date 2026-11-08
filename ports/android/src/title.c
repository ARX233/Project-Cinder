#include "title.h"

#include <string.h>

#include "namedb.h"
#include "titledb.h"

/* 10-in-a-row course c's slot in the card's results (clEffTenCourseType::data +4, stage - 333) */
static const int TEN_SLOT[10] = { 0, 1, 2, 3, 4, 5, 8, 6, 7, 9 };

static void put32(unsigned char *d, int at, int v) { memcpy(d + at, &v, 4); }
static void putf(unsigned char *d, int at, float v) { memcpy(d + at, &v, 4); }

/* clV386CardData::isStoryClear(i): the loop's episode i (20 a division, divisions before the
 * one in play all cleared) */
static int story_clear(const title_card *c, int i) {
  int div = c->st_div % 5, d = (i % 100) / 20;
  return d < div || (d == div && (c->st_bits >> (i % 20) & 1));
}

int title_judge(const title_play *p, int current, int out[3]) {
  unsigned char d[0x3b8];
  memset(d, 0, sizeof d); /* the template (0x9776e40) is all zeros */
  const title_card *pre = &p->pre, *now = &p->now;
  int model = p->model >= 0 && p->model < 256 ? p->model : 0;
  const titledb_model *tm = &TITLEDB_MODELS[model];
  put32(d, 0x00, p->mode);
  put32(d, 0x04, tm->bng);
  put32(d, 0x08, tm->color);
  putf(d, 0x0c, (float)(int)(p->odo_m / 1000.0)); /* getOdoCount: km */
  put32(d, 0x10, p->year);
  put32(d, 0x14, p->month);
  put32(d, 0x18, p->day);
  put32(d, 0x1c, now->power);
  put32(d, 0x20, now->handling);
  d[0x25] = p->won != 0;
  put32(d, 0x28, p->plays);
  putf(d, 0x2c, 1.0f); /* -(card +0x184 / 3 - 1), +0x184 0 */
  putf(d, 0x30, 1.0f);
  put32(d, 0x38, 0); /* getOverHaul */
  d[0x3c] = tm->flags & 1;
  put32(d, 0x40, p->hour);
  put32(d, 0x44, p->minute);
  put32(d, 0x48, p->second);
  putf(d, 0x4c, (float)p->race_m); /* the race's run, m */
  put32(d, 0x50, pre->power);
  put32(d, 0x54, pre->handling);
  d[0x58] = tm->flags >> 1 & 1;
  d[0x59] = tm->flags >> 2 & 1;
  int clears = now->st_wins;
  put32(d, 0x5c, clears);
  put32(d, 0x68, now->st_streak);
  for (int lv = 0; lv < 10; ++lv)
    for (int c = 0; c < 10; ++c) d[0x6c + TEN_SLOT[c] + 10 * lv] = (unsigned char)now->ten[c][lv];
  d[0xdc] = tm->flags >> 3 & 1;
  /* the card's name as a std::wstring at +0x34 is put in by car_title_list's caller below */
  if (p->mode == TITLE_STORY) {
    int sel = p->story_sel % 100;
    put32(d, 0xe0, sel);
    put32(d, 0xe4, pre->st_div / 5);
    if (!story_clear(pre, sel) && story_clear(now, sel)) {
      for (int i = 0; i < 100; ++i) d[0xe8 + i] = (unsigned char)story_clear(now, i);
    } else if (pre->st_div / 5 != now->st_div / 5) {
      memset(d + 0xe8, 1, 100); /* the loop went round */
    }
    for (int i = 0; i < 100; ++i) d[0x14c + i] = (unsigned char)story_clear(pre, i);
    put32(d, 0x1b4, clears);
    put32(d, 0x1c4, now->st_streak);
  } else if (p->mode == TITLE_TA) {
    for (int s = 0; s < TITLE_TA_SLOTS; ++s) {
      d[0x1c8 + s] = !pre->ta_ms[s] && now->ta_ms[s];
      d[0x1d7 + s] = pre->ta_ms[s] != now->ta_ms[s] && s == p->ta_slot && p->ta_top;
    }
    d[0x1e6] = 1; /* the course's ranking has runs of its own (!hasDefault) */
    put32(d, 0x1e8, p->ta_slot);
    int ms = (int)(p->ta_time * 1000.0f), mins = ms / 1000 / 60;
    put32(d, 0x1ec, mins);
    put32(d, 0x1f0, ms / 1000 - 60 * mins);
    put32(d, 0x1f4, ms % 1000);
  } else if (p->mode == TITLE_TEN) {
    for (int lv = 0; lv < 11; ++lv)
      for (int c = 0; c < 10; ++c) {
        d[0x1fc + TEN_SLOT[c] + 10 * lv] = (unsigned char)now->ten[c][lv];
        d[0x26a + TEN_SLOT[c] + 10 * lv] = (unsigned char)pre->ten[c][lv];
      }
    put32(d, 0x2d8, p->ten_level);
    put32(d, 0x2dc, p->ten_course >= 0 && p->ten_course < 10 ? TEN_SLOT[p->ten_course] : 0);
  } else if (p->mode == TITLE_VS) {
    /* clPlayerWork +0x420's 0x70 bytes: the others, the wins (all, this race), their cars */
    put32(d, 0x310, p->vs_n);
    put32(d, 0x314, now->vs_wins);
    put32(d, 0x328, now->vs_wins - pre->vs_wins);
    for (int i = 0; i < p->vs_n && i < 3; ++i) {
      int m = p->vs_model[i] >= 0 && p->vs_model[i] < 256 ? p->vs_model[i] : 0;
      put32(d, 0x32c + 4 * i, TITLEDB_MODELS[m].bng);
    }
  }
  if (p->log) memcpy(d + 0x384, p->log, CAR_TITLE_LOG);
  /* the name: a wstring (libstdc++'s: length, capacity, refcount, then 4-byte characters) laid
   * out past the _TitleData_, its pointer at +0x34 pointing there (car_title_list puts the data
   * at RC_STACK_TOP - 0x800) */
  unsigned char all[0x3b8 + 12 + 4 * 6];
  memcpy(all, d, sizeof d);
  int n = 0;
  int wname[5];
  for (int i = 0; i < 5; ++i) {
    int g = p->name ? p->name[i] : -1;
    if (g < 0) break;
    wname[n++] = g < NAMEDB_N ? NAMEDB_WCHAR[g] : 0x3000;
  }
  for (; n > 0 && n < 5; ++n) wname[n] = 0x3000; /* the card's 5, padded with spaces */
  put32(all, 0x3b8, n);
  put32(all, 0x3b8 + 4, n);
  put32(all, 0x3b8 + 8, 0);
  for (int i = 0; i < n; ++i) put32(all, 0x3b8 + 12 + 4 * i, wname[i]);
  put32(all, 0x3b8 + 12 + 4 * n, 0);
  put32(all, 0x34, (int)(0x09e40000u - 0x800u + 0x3b8u + 12u)); /* RC_STACK_TOP - 0x800 */
  /* Loading the physics image can fail; treat an unwritten list as empty. */
  int got[3] = {0, 0, 0};
  car_title_list(all, (int)sizeof all, got);
  int k = 0;
  for (int i = 0; i < 3; ++i) {
    int id = got[i] & 0xffff; /* clEffTitleType(int): a u16 */
    if (id <= 0 || id >= TITLEDB_N || id == current) continue;
    int dup = 0;
    for (int j = 0; j < k; ++j) dup |= out[j] == id;
    if (!dup) out[k++] = id;
  }
  for (int i = k; i < 3; ++i) out[i] = 0;
  return k;
}

int title_glyphs(int id, const unsigned short **glyphs) {
  if (id <= 0 || id >= TITLEDB_N) id = TITLE_FIRST;
  *glyphs = &TITLEDB_TEXT[TITLEDB_AT[id]];
  return TITLEDB_LEN[id];
}

int title_glyph_half(int g) { return g >= 0 && g < TITLEDB_CHARS && TITLEDB_CHAR[g] <= 0x7f; }

int title_glyph_index(unsigned codepoint) {
  int lo=0,hi=TITLEDB_CHARS;
  while (lo<hi) {
    int mid=lo+(hi-lo)/2;
    if (TITLEDB_CHAR[mid]<codepoint) lo=mid+1;
    else hi=mid;
  }
  return lo<TITLEDB_CHARS && TITLEDB_CHAR[lo]==codepoint ? lo : -1;
}

int title_model(int maker, int car, int color) {
  if (maker < 0 || maker >= (int)(sizeof TITLEDB_MODEL / sizeof TITLEDB_MODEL[0]) || car < 0 || car >= 12 || color < 0 || color >= 8)
    return -1;
  return TITLEDB_MODEL[maker][car][color];
}
