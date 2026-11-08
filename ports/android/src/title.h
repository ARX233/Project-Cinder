/* The titles (称号): what a play earns, as the arcade's clWorkSpace::judgeTitle has it.
 * judgeTitle gathers the card before the race (PRE), the card after it (NOW) and the race
 * into youTitle's _TitleData_ and hands it to youTitle::GetTitleList (recompiled, src/car.c
 * car_title_list), whose rules stock up to three titles; the ones that are not the card's
 * title already are offered (seqTitleSelect). The card keeps only the title it shows
 * (clV386CardData +0x170, 1 湾岸の新人 on a new card). */
#ifndef TITLE_H
#define TITLE_H

#include "car.h"

/* _TitleData_ +0: the mode's rules GetTitleList runs */
enum { TITLE_STORY = 4, TITLE_VS = 5, TITLE_TA = 6, TITLE_TEN = 7 };
#define TITLE_FIRST 1 /* 湾岸の新人 */
#define TITLE_TA_SLOTS 15 /* clEffTaCourseType's, by stage - 363 */

/* The card as judgeTitle reads it (clV386CardData's getters), once before the race and once
 * after it. */
typedef struct {
  int power, handling;  /* clCarStyle::getTunePower / getTuneHandling */
  int st_div, st_bits;  /* the story's progress (menu.h: getStoryClearDivCount, the division's bits) */
  int st_wins;          /* getStoryClearCount */
  int st_streak;        /* getStorySuccessiveVictoryCount */
  int ta_ms[TITLE_TA_SLOTS]; /* getTimeAttack by course slot, ms (0 none) */
  signed char ten[10][11];   /* getTenResult by course (src/tendb.h's order) and level */
  int vs_wins;          /* the versus wins */
} title_card;

typedef struct {
  int mode;             /* TITLE_STORY .. TITLE_TEN */
  int model;            /* the card's car (clEffCarType: src/titledb.h TITLEDB_MODEL) */
  double odo_m;         /* the card's mileage after the race (m) */
  double race_m;        /* the race's distance (m) */
  int year, month, day, hour, minute, second; /* clDateTime: now, local time */
  const short *name;    /* the card's name (namedb.h characters, -1 past its end) */
  int plays;            /* games played in a row (clPlayerWork +0x24, the continues) */
  int won;              /* the race was won (clPlayerWork +0x240 == 0) */
  title_card pre, now;
  int story_sel;        /* the story's select in the loop (clEffStoryType::getStorySelectInLoop) */
  int ta_slot;          /* the time attack's course slot (stage - 363) */
  float ta_time;        /* its time (s) */
  int ta_top;           /* the time is the machine's best on the course (the ranking's first) */
  int ten_course;       /* the 10-in-a-row's course (tendb.h's order, 0..9) and level (0..10) */
  int ten_level;
  int vs_n;             /* the versus: the others, their cars (clEffCarType, -1 unknown) */
  int vs_model[3];
  const unsigned char *log; /* the run's log (car_race.title_log), NULL none */
} title_play;

/* GetTitleList on the play: the new titles (0 for an empty slot), the card's title taken
 * out (judgeTitle's std::find); returns how many there are. */
int title_judge(const title_play *p, int current, int out[3]);

/* a title's characters (glyphs of TITLEDB_CHAR: menupack.py's TITLE_GLYPH*_BASE + k), how many */
int title_glyphs(int id, const unsigned short **glyphs);
/* whether glyph g takes a font's half width (the ASCII ones) rather than its full */
int title_glyph_half(int g);
int title_glyph_index(unsigned codepoint);
/* a model's ids, -1 for none; the models of a car's colours */
int title_model(int maker, int car, int color);

#endif
