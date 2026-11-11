/* The arcade's front end, played from its own .anm animations: the attract loop (movie,
 * title screen, time attack ranking, maker logos), the car select (maker, car on its
 * turntable carousel, body colour), time attack mode (Personal Best / Official Machine),
 * course select, the time zone and BGM select, and the race's title page. */
#ifndef MENU_H
#define MENU_H

#include "ghost_original_ui.h"
#include "ta_rank.h"
#include <stdint.h>

enum { MENU_TA_RANK_UNAVAILABLE=0, MENU_TA_RANK_LOCAL=1, MENU_TA_RANK_STORE_ERROR=2, MENU_TA_RANK_COMMUNITY=3 };

/* APP-owned immutable catalogue presentation, never a file/world capability.
 * Areas are original clEffAreaType slots 0..7, NOT visual menu order. A native
 * binding alone supplies level/ramp/route and appearance (raw_model is not a
 * physics/model index). History/revenge flags must describe THIS player's real
 * races, not archive metadata. Unknown level/appearance use -1.
 * DEFAULT rows are native-getter metadata, never missing-record fallbacks:
 * native_available requires APP's manager-eligible + live bridge capability;
 * their directory areas keep ramp=route=-1 until an action7 is actually taken.
 * RECORDED areas still require ordinary native ERamp/route for action6. */
#define MENU_GHOST_DIRECTORY_RECORDS 196u /* recorded raw collection, unchanged */
#define MENU_GHOST_DEFAULT_RECORDS 120u /* raw compiled rows; eleven GUESTs are not selectable */
#define MENU_GHOST_CLOUD_RECORDS 16u
#define MENU_GHOST_LOCAL_RECORDS 32u
#define MENU_GHOST_DIRECTORY_MAX_RECORDS (324u + MENU_GHOST_CLOUD_RECORDS + MENU_GHOST_LOCAL_RECORDS)
#define MENU_GHOST_DIRECTORY_AREAS 8u
enum { MENU_GHOST_SOURCE_RECORDED=0, MENU_GHOST_SOURCE_DEFAULT=1, MENU_GHOST_SOURCE_LOCAL_CROWN=2, MENU_GHOST_SOURCE_CLOUD=3 };
typedef struct {
  uint16_t year;
  uint8_t month, day, hour, minute;
} menu_ghost_record_date;
typedef struct {
  int level, native_available, ramp, route;
  int pack, paint; uint32_t raw_model;
  int power, handling; uint32_t title, class_id;
  int history_available, revenge_available;
  int default_crown; /* original compiled holder for this area */
  int native_type, base_paint, custom_color;
  int aero, mirror, wing, bonnet, wheel, neon, vinyl;
  menu_ghost_record_date recorded; /* year 0 means no known timestamp */
} menu_ghost_directory_area;
typedef struct {
  uint32_t record_index, id_devel, id1, id2;
  uint16_t name[5];
  menu_ghost_directory_area areas[MENU_GHOST_DIRECTORY_AREAS];
  uint32_t source_kind; /* appended; zero-initialized legacy rows remain RECORDED */
} menu_ghost_directory_row;
typedef struct {
  const menu_ghost_directory_row *rows;
  unsigned count;
  uint64_t epoch; /* nonzero source catalogue generation; never a score */
  int player_level; /* -1 unknown; authoritative native 0..9 otherwise */
  int player_history_available, player_revenge_available;
  int cloud_crowns, cloud_crowns_ready;
  unsigned cloud_crown_occupied;
} menu_ghost_directory_view;

enum { MENU_ATTRACT_CROWN_IDLE, MENU_ATTRACT_CROWN_LOCAL,
       MENU_ATTRACT_CROWN_PENDING, MENU_ATTRACT_CROWN_ONLINE };
typedef struct {
  short glyphs[5]; /* namedb glyphs for the server or local holder */
  menu_ghost_directory_area car;
} menu_attract_crown;

#define MENU_CARD_GHOST_RECENT 8u
typedef struct {
  menu_ghost_record_date date;
  uint32_t raw_model;
  short glyphs[5]; /* namedb indices, -1 past the end */
  int area, hp;
  int gap_m, has_gap; /* positive when the defending ghost was ahead */
} menu_card_ghost_match;
typedef struct {
  unsigned races, wins, coins;
  unsigned crown_mask; /* bit per original clEffAreaType */
  unsigned defense_races, defense_wins, defense_recent_count;
  menu_card_ghost_match defense_recent[MENU_CARD_GHOST_RECENT];
} menu_card_ghost_stats;

#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
#include "pre_race_tune.h"
#endif
#if defined(__ANDROID__) || defined(WMMT_HUD_CUSTOM_TEST)
#include "hud_custom_store.h"
enum { CUSTOM_DIRTY_DEADZONE=1u<<0, CUSTOM_DIRTY_SHIFT=1u<<1,
       CUSTOM_DIRTY_MAP=1u<<2, CUSTOM_DIRTY_RANK=1u<<3,
       CUSTOM_DIRTY_TIME=1u<<4, CUSTOM_DIRTY_METER=1u<<5,
       CUSTOM_DIRTY_OPACITY=1u<<6, CUSTOM_DIRTY_BUTTON_0=1u<<7 };
#endif

/* Stable option-file values: 0/1 retain the old buttons/gyro meaning. */
static inline int menu_steer_valid(int mode) { return mode >= 0 && mode < 4 ? mode : 0; }
static inline int menu_steer_hit(float x, float y) {
  if (y < 137.0f || y >= 167.0f || x < 300.0f || x >= 636.0f) return -1;
  return (int)((x - 300.0f) / 84.0f);
}
static inline int menu_story_cut_loop(int st_div, int story_test) {
  return (story_test >= 1 && story_test <= 10 ? story_test - 1 : st_div) / 5;
}

#define MENU_VS_PLAYERS 4
#define MENU_VS_FOUND 4
/* the dress-up GET screens a race can bring (a 10-in-a-row run: a part a rival beaten) */
#define MENU_DRESS_DUE 16

/* The race's pause menu: the arcade's continue dialog (clSeqContinueThread: "Continue?" over
 * the YES and NO cards of the time zone select's spin box) in a box over the race. */
typedef struct {
  int open;        /* frames since it opened, 0 = closed */
  int sel;         /* the card at rest: 0 YES (back to the race), 1 NO (back to the menus) */
  int slide;       /* frames left of the slide over to the other card */
  int card_t;      /* frames since the card came to rest */
  int go;          /* the slide ends in deciding the other card (it was tapped) */
  int deciding;    /* frames left of the decided card, then of the fade out (YES) or to white (NO) */
  int tap;
  float tap_x, tap_y;
} menu_pause;

/* clTaResult's figures (its clArg, 0x97fda04), filled by the app as the race ends at the goal */
#define MENU_SECTIONS 7
enum { MENU_TA_RESULT_LOCAL, MENU_TA_RESULT_PENDING, MENU_TA_RESULT_ONLINE };
typedef struct {
  float course_record, car_record, personal; /* s: the course's record, the car's, the player's (after this run) */
  int new_course, new_car, new_personal;     /* this run set them */
  float section[MENU_SECTIONS];              /* s each section took (0 for those the course lacks) */
  float total;                               /* s */
  int top_speed;                             /* km/h */
  int rank;                                  /* displayed place, through 100 */
  int cloud_status;
} menu_result;

#define MENU_GARAGE_MAKERS 7 /* CARDB_ALL: the makers and the hidden cars */
/* the port's save slots (MENU_SAVE): what the screen shows of each, filled by the app */
#define MENU_SAVES 4
typedef struct {
  int used;                  /* the save has data */
  int story, medals, cars;   /* story episodes won, 10-in-a-row gold medals (its cars' together), cars */
  long long when;            /* last saved (time_t) */
  short name[5];             /* the player's name (namedb.h's characters, -1 past its end) */
} menu_save_info;
/* A save's cars, each one of the arcade's cards: the car (src/cardb.h's maker and car) and
 * its colour, when it was registered (time_t) and how far it has been driven (m). Its tune,
 * parts, story and 10-in-a-row results are menu_state's per car arrays. */
#define MENU_OWN_MAX 72
typedef struct {
  signed char maker, car, color;
  long long born;
  double odo;
} menu_own;
#define MENU_GARAGE_CARS 12  /* CARDB_MAX_CARS */

#include "story_body_view.h"
typedef struct {
  int kind,context,peer,maker,car,color,save_slot,save_skip,own_index;
  long long born;
  story_body_view view;
} menu_story_body_stamp;

typedef struct {
  int raw_model, pack, paint, type, custom_color;
  int aero, vinyl, bonnet;
} menu_body_color_view;

typedef struct {
  int ms, plate; /* legacy score and uniquely matched car-logo sprite ID, 0 if unknown */
  short name[5]; /* the name of its save slot, -1 for an empty glyph */
} menu_ta_saved_pb;

typedef struct {
  int screen;      /* MENU_MOVIE ... MENU_PRE */
  int t;           /* 60 Hz frames since the screen (or its current move) started */
  int sel, from;   /* selected item; item a move started from (-1 = idle) */
  /* the course select's strip (clThread_6_2_CourseSelect's spin box): the selected card's
   * place on screen, and the strip's shift in cards before the move (it slides 88 px a card) */
  int course_pos, course_scroll_from;
  int deciding;    /* frames left of the "decided" animation, then the race starts */
  int tap;         /* pending tap on the screen */
  float tap_x, tap_y;
  int key;         /* pending left/right key: -1, +1 (0 = none) */
  int key_held;    /* key under the finger, for drawing */
  void *key_touch; /* finger holding a left/right menu key */
  void *back_touch; /* the finger on the back key: it goes back when let go on the key */
  int game;        /* stable mode identity: STORY0, TEN1, TA2, VS3, GHOST4 */
  /* the 10-in-a-row (mseqTen): the course select's choice (its card, the course in menu
   * order: src/tendb.h), the level select's (0..9, 10 the 32-man extend) and the levels it
   * offers (11 once every level has gold); the medal of each course (clEffTenCourseType)
   * and level as the card keeps it (getTenResult: 0 none, 1 bronze, 2 silver, 3 gold; the
   * app keeps them, data_dir/garage); the level select's faces: the level they show and the
   * frames since they popped in */
  int ten_course, ten_level, ten_levels;
  signed char ten_result[10][11];
  int ten_face_lv, ten_face_t;
  int story_sel;   /* the story select of the race ahead (the app sets it; src/storypre.h), -1 none */
  /* The story's progress as the arcade's card keeps it (clV386CardData): st_div counts the
   * divisions cleared (getStoryClearDivCount: the loop is st_div / 5, the division st_div % 5,
   * 20 episodes each, four levels of five), st_bits the division's cleared episodes. The app
   * keeps them (data_dir/garage); menu_story_clear moves them on. */
  int st_div, st_bits;
  int story_test, ta_traffic; /* testing chapter page (1..10), TA traffic option */
  int card_color_pending; /* defer owned-car colour until card confirmation */
  /* Repaint is not factory m.color. Registered values are APP-persisted per
   * maker/car in the current slot; guests keep only a session value. */
  unsigned char custom_color[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  int body_tab_focus;
  struct { int raw_model, maker, car, factory, aero, save_slot, save_skip; unsigned mask; } body_pages;
  struct {
    int active, own, maker, car, factory, raw_model, before, save_slot, save_skip, aero, confirm;
    long long born;
  } body_edit; /* transaction/coverage transient, NEVER serialize */
  int st_level;    /* the level select's choice */
  int story_pick;  /* the rival select's choice: its story index (src/rivaldb.h's select), -1 none */
  int story_n;     /* and its place in the loop, 20 * division + 5 * level + episode */
  int course, official; /* the choice, once a race is ready */
  int demo;        /* rounds of the attract loop so far: picks the movie and automatic ranking course */
  menu_attract_crown attract_crowns[MENU_GHOST_DIRECTORY_AREAS];
  int attract_crown_status, attract_crown_slot;
  unsigned attract_crown_occupied;
  uint64_t attract_crown_generation;
  int ta_rank_offset, ta_rank_touch_inside; /* manual browsing shares the 12-course rotation */
  void *ta_rank_touch;
  /* APP game-thread snapshot only. No borrowed lifetime, network authority or draw-time I/O. */
  ta_rank_view ta_rank_snapshot;
  int ta_rank_valid, ta_rank_status;
  menu_ta_saved_pb ta_rank_saved_pb[TA_RANK_COURSES]; /* keyed by native course ID */
  int flash;       /* frames left of the white flash over the mode select */
  int bars;        /* the top and bottom bars slide in while t < 11 */
  int lock;        /* frames the arcade ignores input after a move */
  int back;        /* pending tap on the back button */
  int leaving;     /* the back button on the maker select: fading to white, then the title screen */
  int maker, car, color; /* the car select's choice (src/cardb.h; maker CARDB_HIDDEN: the hidden cars) */
  /* the maker select's "Maybe......Hidden Cars?" key pressed; the maker under the cursor
   * when it was (where the maker select comes back to) */
  int hidden, hidden_go, hidden_from;
  /* the colour select's ALL PARTS key (a new kind of car's, in the hidden cars key's place):
   * on, the card is made with every part and tune it can have (own_register: the dress-up
   * level 63, the story's tune full; Allan 10-26) */
  int all_parts;
  float rot, rot_speed;  /* the car carousel: angle (radians) and direction of its turn */
  float spin;      /* the body colour turntable's heading, degrees */
  int bgm;         /* the selected line within bgm_source's music group */
  int bgm_source;  /* group in which bgm was selected; session state only */
  int song;        /* the race's song (1..20), or -1 for none, once a race is ready */
  int music;       /* the menus play the entry music (0) until the mode select, then the select music (1) */
  int zone;        /* the time zone select's card, the race's map: 0 morning, 1 night */
  int zones;       /* the time zones there are maps for (the app sets it; 1: morning only) */
  int story_day_select, story_zone, story_zones_saved, story_previous_zone, ta_zone; /* port extension: separate confirmed preferences */
  int slide;       /* frames left of the cards' slide over to the other time zone */
  int card_t;      /* frames since the card came to rest (its ring flashes once) */
  int ready;       /* the app sets it once the chosen map is loaded: the title page waits for it */
  int loading;     /* the app counts the frames the car select's cars on show (or the race title's course) have been loading */
  int load_shown, load_out; /* the race title's NOW LOADING: the frames it showed, then those of its fade once done */
  float acc;
  menu_pause pause;
  int finish;      /* frames since the race ended (menu_finish_open), 0 = none */
  int finish_wait; /* frames the race runs on before FINISH or TIME UP shows */
  int finish_goal; /* it was the goal (FINISH), not the time running out (TIME UP) */
  int finish_ghost; /* an original Ghost battle result over the race */
  int finish_out;  /* frames since the result was left (the fade to black), 0 = still up */
  int pre_quiet; /* MENU_PRE between a story select's races: no title page (back_from_race) */
  int finish_story; /* a story race's end (menu_finish_story): 1 WIN, 2 LOSE, 3 on to the next race,
                    * 4 the 10-in-a-row's (menu_finish_ten), 0 the time attack's */
  /* on to the next race: how the race fades out (src/storymovie.h's STORYRACE_FADE: 1 black,
   * 2 white, 0 none), and so the screen while the next one loads and what it fades in from
   * (pre_fade; the app takes it at the start) */
  int finish_fade, pre_fade;
  menu_result result;
  struct { int active, remaining_km, total_km, hold, fade_out; } mileage;
  struct { int active, area, pending; unsigned owned; } crown_award;
  /* The car setting screen's choices: per car of the car select (src/cardb.h's makers and
   * cars), stock or full tune, and the full tune's balance as its power (the handling has
   * the rest of CAR_TUNE_TOTAL); and the gearbox, AT (0) or MT (1). menu.c sets
   * garage_changed when one changes; the app keeps them (data_dir/garage) and clears it. */
  signed char tune_full[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS], tune_power[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  int manual;
#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
  pre_race_tune pre_tune;
  int pre_tune_origin, pre_tune_bgm_sel, pre_tune_story_day, pre_tune_setting;
  void *pre_tune_car_touch;
  int pre_tune_car_inside;
#endif
  /* The port's OPTION screen (MENU_OPTION, the gear key on the maker select): steering by
   * BUTTONS (0), GYRO (1), WHEEL (2), or STICK (3), the tilt's sensitivity (1..10) and the
   * bridge reflection on the car (on 1), the FSR sharpening (on 1), the cars' baked ambient
   * occlusion (on 1) and the back mirror (on 1); kept with the garage too. */
  int gyro, gyro_sens, over_on, sharp_on, pedal_slide, ao_on, bm_on;
  /* and on Android (hq_rows, set by the app with render_hq on), the GRAPHICS rows in two
   * columns with its own: the AI-upscaled ASTC maps, the bloom, the screen-space ambient
   * occlusion, the wet road, the paint's reflection and the anti-aliasing (4x 1, 2x 0, from
   * the next start) */
  int hq_rows, hd_tex, bloom_on, ssao_on, wet_on, paint_on, aa4;
  int frame_rate_limit; /* Android presentation cap: 0 auto, 60, 90 or 120 */
  /* and on an iPad (res_row, set by the app), the screen's resolution: 1024x768 (0) or the
   * Retina iPads' 2048x1536 (1), from the next start (main.m reads it from the options) */
  int res_row, hires;
  /* the gear key pressed; the maker under the cursor meanwhile; the screen it was pressed on
   * (the maker select or the SAVE DATA screen) */
  int option, opt_sel, opt_from, opt_page;
  int key_k[3], key_dx[3], key_dy[3];
  int key_base_k[3], key_base_dx[3], key_base_dy[3];
  unsigned key_layout_dirty; /* one bit per legacy group */
  int key_retry_frames, key_save_failed;
#if defined(__ANDROID__) || defined(WMMT_HUD_CUSTOM_TEST)
  HudCustomLayout custom_layout, custom_layout_base;
  unsigned custom_layout_dirty; /* CUSTOM_DIRTY_* fields explicitly edited by the user */
  int custom_layout_status, custom_retry_frames, lay_page, lay_old_separate;
  int stick_center_mode, stick_center_dirty, stick_center_status, stick_center_retries, stick_center_retry_frames;
#endif
  int lay_sel, lay_drag, lay_tap, lay_button_down, lay_old_dx, lay_old_dy;
  void *lay_touch;
  float lay_x, lay_y;
  /* The dress-up menu the game mode select's wheel key opens (MENU_TG_SELECT, the arcade's
   * seqTgDressUpPartsSelect: there only once a car has won every part): the key pressed, the
   * menu open (its change screens can go back, the wear comes back to it), the kind of part
   * last chosen (its place is where the menu opens, -1 none) */
  int dress, dress_free, dress_kind;
  /* the save's car view's delete key pressed (erase), once to arm it, again to delete */
  int erase, erase_armed;
  int garage_changed, options_dirty; /* options_dirty: global settings that need no garage write */
  /* The port's SAVE DATA screen (MENU_SAVE, between START and the maker select; the
   * arcade's card check stands there): NEW GAME or LOAD GAME lit, the save of a NEW GAME
   * tapped once (it must be tapped again to start over in it, 0 none). The app keeps the
   * save in use (save_slot, 1..MENU_SAVES, 0 none yet), fills save[] when save_scan is set
   * and takes save_pick (the save chosen, 1..; save_pick_new: started over) once set;
   * save_skip (a test) has START go straight to the maker select. */
  int save_new, save_confirm, save_slot, save_scan, save_pick, save_pick_new, save_skip;
  /* DELETE lit (a tapped save then tapped again is deleted: save_erase, 1..MENU_SAVES, which
   * the app takes) */
  int save_del, save_erase;
  menu_save_info save[MENU_SAVES];
  /* The save's cars (n_own of them) and the one driven (own_sel, -1 none yet): st_div,
   * st_bits and ten_result are its, kept per car in st_div_car, st_bits_car and ten_car
   * (menu_own_store puts them back, menu_own_load takes a car's). HAVE (the arcade's "do
   * you have a card?", clSeqCardHaveSelectThread) offers the save's cars (GARAGE, the port's
   * look at them, then CARD, the card's first page, clSeqCardDisp1) or a new car (MAKER ...
   * COLOR, then CARD for the car registered); have_sel the card at rest (0 YES, 1 NO),
   * own_view the car GARAGE shows, card_back the screen CARD goes back to. */
  menu_own own[MENU_OWN_MAX];
  int n_own, own_sel, own_view, have_sel, card_back;
  int card_page; /* card confirmation page, 1..9; never saved */
  menu_card_ghost_stats card_ghost_stats; /* app snapshot for the selected card */
  void *card_touch; /* one captured finger; page buttons commit on release */
  int card_touch_action, card_action, card_save_failed;
  signed char meter_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS], sound_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  unsigned char st_bonus_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  long long card_born[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  int card_choice_error;
  /* The player's name (the card's five characters, namedb.h's, -1 past its end), asked for
   * by NAME (clSeqCardNameSelectThread) as soon as a NEW GAME starts: the grid's page
   * (0 katakana .. 3 small letters), the key last tapped (its place, -1 none) and the frames
   * left of its pop, of the character last put in. */
  short name[5];
  int name_page, name_key, name_pop, name_char_pop;
  int st_div_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS], st_bits_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  signed char ten_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS][10][11];
  /* each car's class (the card's +0x172: 0 N, C9..C1, B9..B1, A9..A1, S9..S1, SS9..SS1, 46
   * SSS; menu_class_update) */
  signed char class_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  /* The story's own tune per car, as the arcade's card keeps it (clCarStyle getTunePower,
   * getTuneHandling, 0..24 each) and the story points gauge (card+0x178, 0..19 units of 50
   * points). A full gauge (menu_story_points) sets st_tune_due: the tuning screen
   * (MENU_ST_TUNE, seqStTune) comes up on the way back from the race. */
  signed char st_power[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS], st_handling[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  signed char st_gauge[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  /* dress-up (the arcade's ghost battle parts, get_tb_level_parts): each car's dress-up level
   * (0..63, the parts it has won) and the aero set it wears (0 stock, 1..3 A, B, C) */
  signed char dress_lv[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS], aero[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  unsigned short dress_points[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS]; /* card+0x17a, 0..999 */
  /* and the parts it wears, as the card keeps them for clCarConstructParam: the aero mirror
   * (card+0xc: 0 stock, 1), the wing (card+7: 0 stock, 1..3, 4 none) and the bonnet (card+6:
   * 0 stock, 1..3); render_params' mirror, wing, bonnet */
  signed char mirror[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS], wing[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  signed char bonnet[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  /* and its wheel (card+0x10): 0 its own, else the dress-up wheel's emTireModelID + 1 */
  unsigned char wheel[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  /* and its under neon (card+0x1a, clCarConstructParam::setNeon): 0 none, 1..6 the straight
   * neons (green, blue, purple, red, yellow, dark purple), 7..12 the spot neons */
  signed char neon[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  /* and its sticker (vinyl: car.lua's VinylTexture entry, 0 none; 1..10 line 1 in its colours,
   * 11.. line 2, 21.. fire 1, 31.. fire 2, 41 namco, 42 pac-man, 43 works, 48.. line 3,
   * 58.. fire 3, 68.. tribal) */
  unsigned char vinyl[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  int st_tune_due;
  /* the episode (story_n) lost in a row and how often (clWorkSpace +0x24, the rivals' ease) */
  int st_lost_n, st_lost;
  /* the car setting's STOCK / FULL TUNE fixed: a car picked from the save's (its card's mode
   * kept, Allan 10-24); a new card chooses */
  int tune_locked;
  /* a car of a kind not in the save, its colour chosen: the setting (its mode first) comes
   * before its card, and the card is made when the setting goes on (Allan 10-25) */
  int new_card;
  /* One-shot notification for app-owned, durable story evidence origin. */
  int story_new_pending, story_new_maker, story_new_car;
  long long story_new_born;
  /* HAVE asking whether to keep the new car in the save (after its card) */
  int keep_ask;
  /* the class-up screen (seqLvUp, MENU_LVUP), the first on the way back from a race whose
   * card's class rose (menu_lvup_check): the class before and after, the frame its loop
   * started (0 till a tap or the intro's end) */
  int lvup_due, lvup_from, lvup_to, lvup_loop;
  /* The titles (称号, src/title.h): each car's (the card's +0x170: 0 not set yet, 湾岸の新人),
   * its story wins in a row (getStorySuccessiveVictoryCount) and its versus wins; the games
   * played since the app started (clPlayerWork +0x24, the continues). title_judge's new
   * titles for the race just run (title_n of them) wait for the title select (seqTitleSelect,
   * MENU_SHOGO), after the class-up on the way back from the race: GET (all of them), the
   * spin box (YES take it, NO keep the one the card has) for each (title_k), then REWRITE
   * if one was taken (title_taken); title_f the phase's frame, title_dec the frames since the
   * spin box was decided (0 not yet), title_out the frames of the phase's fade out (0 none). */
  short title_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS], st_streak_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  int vs_wins_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  /* The versus stars (the card's +0x180, clRaceThread::finiJoin) and versus count (+0x17c) of
   * each car; the stars screen after a versus (MENU_VS_STAR, clSeqJoStarGetThread): the stars
   * before the race and the race's change (menu_vs_stars; the screen only for one), its frame */
  int vs_stars_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS], vs_count_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  unsigned char drive_style_car[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
  int star_from, star_delta, star_t, star_skip;
  float star_spin;
  int plays;
  int title_new[3], title_n, title_k, title_phase, title_taken, title_f, title_dec, title_out;
  /* the tuning work (seqStTuneEff, MENU_ST_EFF) after the tuning screen: the row (steff.h:
   * the top bar's title, the part's picture, the install anime, the car's pose, the lines),
   * power tuned (else handling), T (power + handling after), the horsepower before and
   * after, a step that ends a stage (T 20, 30, 34: the complete picture), the tuner of
   * that picture; the frame the work's main part started (the text box on), the frame the
   * complete picture came on, the 10 s (frames left), the frames left after a tap, the
   * car's turn (degrees) and whether it is the new one (the pose's second set) */
  struct {
    int title, parts, anim, pose, text, power, total, hp0, hp1, milestone, chara;
    int main_t, complete_t, timer, quit, after;
    float angle;
  } eff;
  /* dress-up levels won since the last GET screens (menu_dress_win queues them, the way back
   * from the race shows them: MENU_TG_GET each, MENU_TG_AERO after an aero set's,
   * MENU_TG_PART after a bonnet's, wing's or mirror's, MENU_TG_WEAR after either) */
  int dress_due[MENU_DRESS_DUE], n_dress_due;
  int dress_due_maker, dress_due_car; /* transient queue owner, never saved */
  /* the GET screen (clSeqTgPartsGetAeroThread) and the aero set's change
   * (clSeqTgChangePartsAeroThread): the level and part shown, the car turning on the GET
   * screen (degrees), the change screen's choices (the aero set of each, -1 Refuse to
   * change), how many, the newest, the move under way (+1, -1 or 0, and its frame), each
   * choice's model's depth offset (0 near .. -400); the bonnet's, wing's and mirror's
   * change (clSeqTgChangeParts*Thread): the layout's places (the choices and the parts not
   * won yet) and the frame the rest loop started */
  struct {
    int lv, kind, num, name, image, gem;
    float angle;
    int opt[8], n, newest, move, move_t, decided;
    float z[8];
    int slots, rest_t;
    /* the part worn (clSeqTgWearPartsAeroThread, after the change): the value worn before
     * and the one chosen (the part's number), the same one kept (wk_s +0x42: no banner),
     * the yield's state (0 the old part, 1 white, 2 the new one, 3..5 the banner) and its
     * timer, the run's 8 s (frames left), the car's turn (degrees about y) */
    int old, chosen, same, state, timer, left;
    float ry;
    /* the white flash (menu_p_whiteout): the first frame of its run (-1 none) and when */
    int white_from, white_at;
    /* the wheel's change (clSeqTgChangePartsWheelThread): the places (menu_state.wheel's
     * values: stock, the one worn, then the maker's won), the maker, the colour chosen, the
     * cursor's place on the bar's window and the bar's scroll (pixels, and -1, +1 or 0 while
     * it slides), when the arrows' and colour cursor's loops started; the wheel worn's
     * (clSeqTgWearPartsWheelThread) jack: the car's lift, the body's over the tyres, its
     * bounce (phase, size, offset) and the COMPLETE's first frame */
    int wl[16], maker, col, win, scroll_dir, reset_t;
    float scroll;
    float lift, body, phase, amp, bounce;
    int complete_t;
  } tg;
  /* the race result's (clRaceResultConsole point_calc) gauge: shown at all, its points
   * before the race (card+0x178 * 50), those the race added (to at most 1000), the tuning
   * message once full (menu_p_finish_result_st_get_*), the advantage (m, > 0 ahead) */
  int st_show, st_prev, st_gain, st_get;
  float st_gap;
  /* the tuning screen (clSeqStTuneThread::clMenuLayout): the values with the step's +1
   * (b8, bc), its gauges' cells, the choice (c4: 1 power) and whether it is fixed (c5), the
   * choice the screen opened on, when the choice last changed (changeTune), each cell's
   * state (0 empty, 1 lit, 2 off, 3 on, 4 the step) and the frame it took it */
  struct {
    int power, handling, total, cells, choice, fixed, choice0, power0, handling0, changed;
    unsigned char state[2][24];
    int since[2][24];
  } tune;
  /* LAN discovery and managed online rooms. The app owns connections and
   * fills in room membership. The menu queues requests and selection input. */
  struct {
    int kind;            /* MENU_VS_LAN, MENU_VS_NET */
    int connect;         /* connect/host (1), MENU_VS_DISCONNECT or MENU_VS_LEAVE */
    int join;            /* the screen's ask: join found game join - 1 (the app clears it) */
    int hosting;         /* the app's: this device hosts the lobby */
    int n_found;         /* the app's: the games nearby (LAN) */
    char found[MENU_VS_FOUND][24];
    int start;           /* the host's START (the app clears it) */
    int state;           /* the app's: MENU_VS_OFF .. MENU_VS_RACE */
    /* Session-only UI round. APP supplies a validated nonzero generation;
     * it freezes the roster and owns protocol/selection authority. Never saved. */
    uint64_t round;
    int flow_stage, round_cancel;
    int tune_base_power, tune_base_handling, tune_maker, tune_car, tune_slot, tune_skip;
    int tune_timer; /* remaining time in 60 Hz display ticks */
    uint32_t omakase_sample[3];
    int omakase_sample_valid;
    int n, me, host;
    char name[MENU_VS_PLAYERS][17], car[MENU_VS_PLAYERS][32];
    short glyph[MENU_VS_PLAYERS][5]; /* the names' own characters (namedb.h's, -1 past the end; none from an older build) */
    int racing[MENU_VS_PLAYERS];
    unsigned char mismatch[MENU_VS_PLAYERS]; /* incompatible race build: block start */
    int ramp, km;        /* the host's choice (the others: the last race's) */
    int last_place, last_n; /* the last race's place of how many (0 none) */
    int held;            /* the button under the finger (1 + its number), 0 none */
    int touch;
    float tap_x, tap_y;
    int tap;
    char note[64];       /* a line from the app */
    /* the area vote (MENU_VS_AREA, the arcade's clseqJoCourseSelectThread): the app opens it
     * (area_go) when the host's START opens the vote, fills in the others' cards from their
     * status (menu_vs_status) and the host's result (area_final); the screen keeps this
     * player's card (0 omakase, 1..8 the areas by menu order), its place, the strip's scroll,
     * the 20 s and the vote */
    int area_go;
    int item, pos, item_from, move_t;
    float scroll, scroll_from;
    int timer, voted, vote, vote_t; /* voted: 0 not yet, 1 an area, 2 omakase's random one */
    int area_final, final_t;        /* the host's card, -1 none yet */
    int other[MENU_VS_PLAYERS];     /* each player's card */
    int other_vote[MENU_VS_PLAYERS]; /* -1 not in the vote, 0 choosing, 1 voted, 2 voted by omakase */
    /* the time zone vote after it (MENU_BGM with day set, the arcade's seqJoinDayTimeSelect
     * over seqStdDayTimeSelect's screen): the app opens it (menu_vs_day_open) after the area's
     * result, fills in the others' zones and the host's result (day_final); the screen keeps
     * this player's card (zone), its 20 s and its vote; the BGM stays each player's own */
    int day, day_timer, day_voted, day_t; /* day_voted 2: omakase (left to the others) */
    int day_final;                  /* the host's zone, -1 none yet */
    int other_day[MENU_VS_PLAYERS];  /* -1 not in the vote, 0 choosing, 1 voted, 2 omakase */
    int other_zone[MENU_VS_PLAYERS];
    /* the race's loading (MENU_VS's LOADING): the app's, this machine's race is in (its status
     * says so) and it waits for the others' (wait_others: the screen says so) */
    int loaded, wait_others;
    /* the cars flying in before the race (MENU_VS_MATCH, the arcade's
     * clRaceThread::JoMatchingInformation): the app opens it (menu_vs_match) with the race's
     * machines (its GO's, in PCB order: car, colour, tune, the name's glyphs) once their cars
     * are in, before the race's loading page (Allan 10-27: the cars first, then the loading);
     * menu_vs_match_back on to that page once it is over (match_played) */
    int match_t, match_n, match_me, match_played;
    struct {
      int maker, car, color, power, handling;
      short glyph[5];
      int title; /* (0 not sent) */
      int aero, mirror, wing, bonnet, wheel, neon, vinyl; /* its dress-up (menu_car's) */
      int base_power,base_handling,base_valid; /* immutable JOIN earned budget, not TUNE_READY */
    } match[MENU_VS_PLAYERS];
  } vs;
  /* Independent local/cloud ghost requests. Never a WV1 lobby or persisted score.
   * The app owns file/network/race execution; this menu only queues one action. */
  struct {
    int local_available, cloud_configured, king_available;
    int ramp, route; /* raw ERamp 1..22, zero-based native route; NOT a TA course or VS packed index */
    int request_ramp, request_route; /* immutable selection snapshot until this request completes */
    int status, pending_action, inflight_action;
    unsigned request_serial, active_request, completed_request, prepared_request;
    int completed_action, pre_go; /* once-only loading handoff, not race authority */
    int intro_t; /* Ghost matchup ticks after the exact race resources are ready */
    int choose_race_options, previous_zone, previous_zones;
    int result, claim_eligible, claim_pending; /* display only; never a granted crown */
    void *touch;
    int touch_action, held;
    ghost_original_ui ui; /* Original search presentation; separate port-only local settings. */
    menu_ghost_directory_view directory; /* borrowed until set_directory(NULL) */
    int directory_row, area_slot, level, search_kind, rival_back;
    short query[5]; /* NAMEDB glyphs, -1 past end; never the player's name */
    int query_page, query_key, query_pop, query_char_pop, query_waiting;
    short previous_query[5]; int previous_query_valid; /* actual session search, not archive history */
    uint32_t request_record_index;
    int request_area_slot;
    uint64_t request_catalog_epoch;
    uint32_t request_id_devel, request_id1, request_id2;
    char note[96];
    uint32_t request_source_kind; /* appended immutable row discriminator; not a server field */
  } ghost;
} menu_state;
enum { MENU_VS_OFF, MENU_VS_CONNECTING, MENU_VS_LOBBY, MENU_VS_LOADING, MENU_VS_RACE };
enum { MENU_VS_LAN, MENU_VS_NET, MENU_VS_KINDS };
enum { MENU_VS_LEAVE = -2, MENU_VS_DISCONNECT = -1 };
#define MENU_VS_RAMPS 22

/* The attract loop (mseqDemo) runs MOVIE, TITLE, RANKING, ATTRACT_CROWNS, LOGO, PROLOGUE; a tap
 * anywhere in it is START (the gas pedal), which flashes white into SAVE (the port's save
 * slots), then HAVE (a car of the save, through GARAGE, or a new one, through the car
 * select), each ending on CARD. The back button steps back through MAKER ... BGM, MAKER to
 * HAVE (or SAVE without cars), and from SAVE fades to white and back to the title screen. SETTING, the car's tune and gearbox, follows the colour select,
 * then GAME, the arcade's game mode select (story, 10 out run, time attack): the time attack
 * goes on to MODE, COURSE and BGM, the story to ST_LEVEL (seqStEnemyLevelSelect: the level,
 * C, B, A or A+) and ST_RIVAL (clThread_5_2_EnemySelect: one of its five episodes), then PRE.
 * The 10-in-a-row goes on to TEN_COURSE (clThread_7_1_CourseSelect) and TEN_LEVEL
 * (clSeqTenLevelSelectThread), then PRE.
 * PRE, the race's title page, stays up while the course loads. */
enum { MENU_MOVIE, MENU_TITLE, MENU_RANKING, MENU_LOGO, MENU_PROLOGUE, MENU_START,
       MENU_MAKER, MENU_CAR, MENU_COLOR, MENU_SETTING, MENU_GAME, MENU_MODE, MENU_COURSE, MENU_BGM,
       MENU_ST_LEVEL, MENU_ST_RIVAL, MENU_PRE, MENU_ST_TUNE, MENU_TEN_COURSE, MENU_TEN_LEVEL,
       MENU_TG_GET, MENU_TG_AERO, MENU_TG_PART, MENU_TG_WEAR, MENU_OPTION, MENU_SAVE, MENU_HAVE, MENU_GARAGE,
       MENU_CARD, MENU_LVUP, MENU_ST_EFF, MENU_TG_WHEEL, MENU_TG_SELECT, MENU_TG_MAKER, MENU_NAME,
       MENU_TG_VINYL, MENU_VS, MENU_VS_SEL, MENU_VS_AREA, MENU_VS_MATCH, MENU_SHOGO, MENU_VS_STAR, MENU_INFO, MENU_LAYOUT,
       MENU_GHOST, /* appended: independent hub, never routed through MENU_VS */
       MENU_GHOST_PRE, /* independently prepared loading screen; no TA/VS fallback */
       MENU_BODY_COLOR, /* original repaint UI; stable prior IDs unchanged */
       MENU_MILEAGE,
       MENU_ATTRACT_CROWNS,
       MENU_CROWN_AWARD
};
/* Exact factory identity and committed/transient repaint view for APP materials.
 * get returns committed style before page preparation outside the edit screen;
 * edit previews additionally require frozen owner and live exact page coverage.
 * set_pages publishes resource availability, NOT historical unlock/renewal state.
 * Clear before context/catalog/car/save teardown. No file IO or model remapping. */
int menu_body_color_get(const menu_state *m, menu_body_color_view *out);
/* Hydrate after the matching owned row exists; rejects unsupported saved values
 * unchanged, independent of runtime pages and without a garage_changed edge. */
int menu_body_color_restore(menu_state *m, int maker, int car, int custom);
int menu_body_color_set_pages(menu_state *m, int raw_model, unsigned mask);
void menu_body_color_clear_pages(menu_state *m);
/* Stable identities, deliberately not the home screen's visual order. */
enum { MENU_GAME_STORY = 0, MENU_GAME_TEN = 1, MENU_GAME_TA = 2, MENU_GAME_VS = 3, MENU_GAME_GHOST = 4 };
enum { MENU_GHOST_IDLE, MENU_GHOST_BUSY, MENU_GHOST_READY, MENU_GHOST_ERROR };
enum { MENU_GHOST_ACTION_NONE, MENU_GHOST_RECORD_LOCAL, MENU_GHOST_CHALLENGE_LOCAL,
       MENU_GHOST_FETCH_KING, MENU_GHOST_CHALLENGE_KING, MENU_GHOST_SUBMIT_CLAIM,
       MENU_GHOST_CHALLENGE_ARCADE, /* 6: genuine recorded CTarget/race/trail */
       MENU_GHOST_CHALLENGE_DEFAULT, /* 7: explicitly selected original compiled target AI */
       MENU_GHOST_CHALLENGE_LOCAL_CROWN, /* 8: validated per-area champion recording */
       MENU_GHOST_CHALLENGE_CLOUD }; /* 9: downloaded compatible recording */
enum { MENU_GHOST_RESULT_NONE, MENU_GHOST_RESULT_FINISHED, MENU_GHOST_RESULT_WIN,
       MENU_GHOST_RESULT_LOSE, MENU_GHOST_RESULT_INVALID };

/* Author-space (640x480) hub; no network, file IO, physics or persisted ranking.
 * Each queued action has one nonzero request ID and can be taken once. Returning
 * to home invalidates old completions. The app starts ghost races itself, never
 * via menu_update's legacy race-return path. */
void menu_ghost_open(menu_state *m);
/* Bind a borrowed immutable view; validate before retaining it. APP keeps all row
 * storage alive/unchanged until unbound. NULL always invalidates before APP frees
 * storage. A changed pointer/count/epoch invalidates active/completed/PRE asks.
 * A same-view refresh changes no selections or request serial. No catalogue IO. */
int menu_ghost_set_directory(menu_state *m, const menu_ghost_directory_view *view);
/* Exact original UTF16 scalar -> NAMEDB_WCHAR mapping; no ASCII transliteration,
 * invented handles or replacement identity. Returns 0 if any glyph is absent. */
int menu_ghost_name_glyphs(short glyph[5], const uint16_t name[5]);
unsigned menu_ghost_search_query(const menu_state *m, uint16_t name[5]);
void menu_ghost_search_complete(menu_state *m, int available);
/* Original eight-card visual order -> original area slot (0..7). */
int menu_ghost_course_area(int visual_slot);
void menu_ghost_set_availability(menu_state *m, int local_available, int cloud_configured, int king_available);
/* Metadata-fixed map, not a fabricated course/route carousel. Returns 0 while
 * busy or for invalid raw ERamp/negative route. The app must validate actual
 * native route count and rule/key compatibility before enabling a challenge.
 * A changed selection invalidates local/king availability; refill only for the
 * matching metadata. Every request copies these values into request_* fields. */
int menu_ghost_set_map(menu_state *m, int raw_ramp, int route);
int menu_ghost_action_available(const menu_state *m, int action);
int menu_ghost_request(menu_state *m, int action);
int menu_ghost_take_action(menu_state *m, unsigned *request_id);
/* Action7 only: after taking the immutable DEFAULT request, APP selects the
 * original native random map ONCE and attaches that frozen result here. No RNG
 * or native/file work occurs in UI. Requires the same inflight BUSY request,
 * source kind/index/id tuple/area/epoch and native-available metadata. Invalid
 * input returns0 without clearing/changing anything. Repeating the SAME map is
 * idempotent; a different second map is rejected. Complete(ok=1)/PRE require a
 * bound ERamp1..22 and rawRoute>=0; failure completion may precede binding. */
int menu_ghost_bind_default_request(menu_state *m, uint64_t request_id, int nativeERamp, int rawRoute);
int menu_ghost_complete(menu_state *m, unsigned request_id, int ok, const char *note);
/* Consume one successful current RECORD/CHALLENGE completion into its own PRE.
 * Clears ready; the app loads the frozen request map/car and then sets ready.
 * menu_update emits GO exactly once. The app must additionally require its
 * prepared engine capability and GHOST identity before creating any race. */
int menu_ghost_begin_pre(menu_state *m);
int menu_ghost_preparing(const menu_state *m);
int menu_ghost_choosing_options(const menu_state *m);
/* claim_eligible is app-owned: only a cloud challenge with its fixed challenge
 * snapshot may offer submission. A local win is never authority to take a crown.
 * Even successful submission stays pending server validation; no crown is set. */
void menu_ghost_race_finished(menu_state *m, int result, int claim_eligible);

/* The cars the car select shows in 3D this frame (the carousel, or the colour turntable),
 * with the arcade's menu camera. Units and axes are the race's (0.1 m, +y up). */
#define MENU_MAX_CARS 12
/* aero: the dress-up set (0 stock), mirror, wing, bonnet its parts (render_params'), wheel
 * its wheel (menu_state.wheel's), lift its body over its tyres (render_params.wheel_drop), neon
 * its under neon (clMenuCar's: lights_draw_neon 3.1 under the car's matrix); cp:
 * drawn as the dress-up screens' clSpriteAnimeCPModel, its own camera on the axis through
 * screen point cp_x, cp_y (640 x 480) */
typedef struct {
  int pack, paint, aero, cp;
  float cp_x, cp_y;
  float model[16];
  int mirror, wing, bonnet, wheel;
  float lift;
  /* its under neon (menu_state.neon's) */
  int neon;
  /* its sticker (menu_state.vinyl's) */
  int vinyl;
  /* its wheels turned (the versus' cars flying in): each corner's rotation (a GL matrix's
   * columns, render_params.wheels'), at its own place */
  int turned;
  float tyre[4][16];
  /* Appended exact player identity, NEVER inferred from shared pack/paint.
   * Valid only for explicit owned/guest player contexts, not purchase/rivals. */
  int body_color_valid;
  menu_body_color_view body_color;
  int story_body_valid;
  menu_story_body_stamp story_body;
  int ghost_row; /* Ghost directory index + 1, -(area + 1) on the attract board, zero otherwise */
} menu_car;
typedef struct {
  int n;
  menu_car cars[MENU_MAX_CARS];
  float eye[3], at[3];
  float fov_x; /* radians, on the arcade's 4:3 screen */
  int env;     /* the screen's clMenu3dEnvironment (data/menu/menu_<env>.lua's lights) */
  /* the wheel GET screen's turning wheel (menu_state.wheel's value, 0 none; its model
   * menu_wheel_get's) at matrix wheel_model */
  int get_wheel;
  float wheel_model[16];
} menu_scene;

/* Needs anm_load() first. Starts the attract loop. */
void menu_init(menu_state *m);
/* Pure game-thread TA presentation; metadata fills name/title/class ONLY.
 * Parent MUST overwrite model/type/P/H from the actual frozen native binding. */
int menu_ta_rank_metadata(const menu_state *m, ta_rank_metadata *out);
int menu_ta_rank_model_plate(unsigned model_id); /* original ranking logo sprite ID, or 0 */
int menu_ta_rank_course(const menu_state *m);
void menu_set_ta_rank_view(menu_state *m, const ta_rank_view *view, int status);
/* A phone's 16:9, edge layout px past the 4:3 on each side: the courses' photos behind the
 * screens go its full width; menu_photo_bg: one was drawn by the last menu_draw. */
void menu_wide(float edge);
int menu_photo_bg(void);
/* A new game's progress: every car stock and without parts, no story or 10-in-a-row results
 * (the OPTION screen's choices stay). */
void menu_garage_reset(menu_state *m);
/* The driven car's story and 10-in-a-row results back to its per car arrays; car k's
 * (own[k]) into st_div, st_bits and ten_result, k the car driven. */
void menu_own_store(menu_state *m);
void menu_own_load(menu_state *m, int k);
/* GetClass (0x857bb0c) of car (maker, car) by its story and 10-in-a-row results. */
int menu_class(const menu_state *m, int maker, int car);
/* clRaceThread::fini: each of the save's cars' class up to GetClass's (it never goes down);
 * the driven car's results first back to its arrays (menu_own_store). */
void menu_class_update(menu_state *m);
/* After a race's results: the class-up screen due if the car's class rose (the class kept
 * raised to it). */
void menu_lvup_check(menu_state *m);
/* After a race's results: the new titles (title_judge's, 0 for none) offered on the way back */
void menu_title_due(menu_state *m, const int titles[3]);
/* the chosen car's title (1 湾岸の新人 when it has none yet) */
int menu_title(const menu_state *m);
/* Implemented by the independent per-car settings integration. Choices unavailable
 * for the current car must not be changed; these functions do not save the garage. */
int menu_card_meter(const menu_state *m);
int menu_card_bgm_source(const menu_state *m);
int menu_card_choice_available(const menu_state *m, int row, int choice);
int menu_card_choice_set(menu_state *m, int row, int choice);
/* The save's car of this maker and car (-1 none). */
int menu_own_find(const menu_state *m, int maker, int car);
/* Back to the mode select (after a race). */
void menu_open(menu_state *m);
/* The chosen car's tune as car_spec has it: power and handling, 0 and 0 when stock. */
void menu_tune(const menu_state *m, int *power, int *handling);
/* The chosen car's story tune (the story races run on it). */
void menu_story_tune(const menu_state *m, int *power, int *handling);
/* clRaceResultConsole::point_calc's story points for the race just run (before
 * menu_story_clear: the episode's earlier clear counts): moves the chosen car's gauge on,
 * a full one to the tuning screen. Returns the units (50 points each) earned. */
int menu_story_points(menu_state *m, int won);
/* The story race's loop (0 the first) and its episode's losses so far, for the rivals */
int menu_story_loop(const menu_state *m);
int menu_story_losses(const menu_state *m);
/* The episode's end: a WIN clears its losses, a LOSE counts one */
void menu_story_lost(menu_state *m, int won);
/* The 10-in-a-row's race: its clEffTenCourseType (0..9), EStage and level. */
int menu_ten_course(const menu_state *m);
int menu_ten_stage(const menu_state *m);
/* Open the pause menu over the race. */
void menu_pause_open(menu_state *m);
/* Advance it by dt seconds: MENU_PAUSED while it is up, MENU_RESUME once YES is decided
 * and the box has faded, MENU_LEAVE once NO is decided and the screen is white. Then the
 * menus are back on the race's last menu, the time zone and BGM select, coming out of
 * the white. */
enum { MENU_PAUSED, MENU_RESUME, MENU_LEAVE };
int menu_pause_update(menu_state *m, float dt);
/* Draws it over the race (needs no 3D). */
void menu_pause_draw(const menu_state *m);
/* The end of a time attack over the race (car_race.over): the music stops, the race runs on
 * a moment, then FINISH and the result (goal = 1, with res), left with a tap, or TIME UP,
 * both with the result music. menu_finish_update gives MENU_PAUSED meanwhile, then
 * MENU_LEAVE once the screen is black, the menus coming back out of it on the time zone and
 * BGM select. Taps go to menu_touch meanwhile. */
void menu_finish_open(menu_state *m, int goal, const menu_result *res);
void menu_ta_finish_records(menu_state *m, const uint32_t best_ms[3], unsigned rank, unsigned flags);
void menu_finish_set_mileage(menu_state *m, double before_m, double after_m);
void menu_finish_set_crown_award(menu_state *m, int area, unsigned owned, int pending);
int menu_finish_update(menu_state *m, float dt);
void menu_finish_draw(const menu_state *m);
/* Each race frame from the moment the race stops running (goal or time up, before
 * menu_finish_open): gets the end's sprites up, one a frame, so they show without a hitch.
 * Draws (nothing to see), so it goes with the frame's drawing. */
/* goal: 0 TIME UP, 1 FINISH, 2 a story race, 3 a 10-in-a-row (what menu_finish_ten names) */
void menu_finish_warm(int goal);
/* after menu_finish_open, for a story race: WIN or LOSE (clRaceResultConsole_story) in place of
 * the time attack's result */
/* a story race's end: WIN or LOSE; next: won, and the select runs another race (no WIN yet:
 * its fade, then the next race), fade the race's STORYRACE_FADE */
void menu_finish_story(menu_state *m, int won, int next, float gap, int fade);
/* after menu_finish_open, for a 10-in-a-row: its end (clTenResult) in place of the time
 * attack's, from the rivals beaten, the total time and the medal (CTenSeq::GetResult 1..3,
 * counted when all were beaten) */
void menu_finish_ten(menu_state *m, int beaten, float time, int medal);
/* after menu_finish_open, for an online versus: WIN or LOSE (the story's) with the place of
 * how many; back to MENU_VS after */
void menu_finish_vs(menu_state *m, int place, int n);
void menu_finish_ghost(menu_state *m, int result, int goal, float gap, int player_rank, int rival_rank);
/* a versus' stars for the place (1 the first) of n machines (clRaceThread::finiJoin's table by
 * the stars held: none lost up to 2000); the car's stars and count updated, the change kept
 * for the stars screen (shown on the way back to the lobby when not 0); the change */
int menu_vs_stars(menu_state *m, int place, int n);
/* the stars screen (MENU_VS_STAR) for star_from and star_delta, then the lobby */
void menu_vs_star_open(menu_state *m);
/* the host closed the game under a versus race: back to MENU_VS, off, with `note` on it */
void menu_vs_closed(menu_state *m, const char *note);
void menu_vs_left(menu_state *m);
/* Keep the existing connection/host while returning an aborted race to its lobby. */
void menu_vs_aborted(menu_state *m, const char *note);
/* The area vote's status byte (the lobby's HELLO, which the servers pass on unread): 0 the
 * lobby, 1 racing, MENU_VS_CHOOSING + card while choosing, MENU_VS_VOTED + card voted,
 * MENU_VS_OMAKASE + card voted by omakase, MENU_VS_FINAL + card the host's result */
enum { MENU_VS_CHOOSING = 2, MENU_VS_VOTED = 16, MENU_VS_OMAKASE = 32, MENU_VS_FINAL = 48, MENU_VS_CARDS = 9 };
/* then the time zone vote's (+ zone, 0 morning, 1 night): MENU_VS_DAY choosing, MENU_VS_DAY_VOTED
 * voted, MENU_VS_DAY_FINAL the host's result, MENU_VS_DAY_OMAKASE left to the others; and
 * MENU_VS_LOADED: the race loaded, waiting for the others' (1 while loading and racing) */
enum { MENU_VS_DAY = 64, MENU_VS_DAY_VOTED = 66, MENU_VS_DAY_FINAL = 68, MENU_VS_LOADED = 70, MENU_VS_DAY_OMAKASE = 72 };
/* a status of the time zone vote's (the host's tells the others the vote is on) */
#define MENU_VS_IN_DAY(st) (((st) >= MENU_VS_DAY && (st) < MENU_VS_LOADED) || ((st) >= MENU_VS_DAY_OMAKASE && (st) < MENU_VS_DAY_OMAKASE + 2))
int menu_vs_status(const menu_state *m);
/* Ordered room UI only, no transport or all-player authority. All clients update
 * together. APP rejects stale round IDs and freezes participant identity.
 * begin: existing room -> AREA; day_open: committed area/ramp -> DAY;
 * tune_open: committed day -> per-player TUNE (<=20 earned points: unchanged
 * READY). None of these writes permanent story/tune/AT/MT/customization data. */
enum { MENU_VS_FLOW_ROOM, MENU_VS_FLOW_AREA, MENU_VS_FLOW_DAY,
       MENU_VS_FLOW_TUNE, MENU_VS_FLOW_READY, MENU_VS_FLOW_LOADING };
int menu_vs_round_active(const menu_state *m);
int menu_vs_round_begin(menu_state *m, uint64_t round);
/* map_vote area is -1 while hovering random, else original area0..7; omakase
 * confirm resolves a concrete area and marker. It is NOT an abstention. */
int menu_vs_map_vote(const menu_state *m, uint64_t round, int *area, int *confirmed, int *omakase);
int menu_vs_map_commit(menu_state *m, uint64_t round, int area);
/* Sampled local UI timer inputs, not native physics RNG or network authority.
 * Original uses first&7; area6 + second&1 rerolls with (third>>2)&7.
 * Without APP samples, this port uses its monotonically stepped UI frame. */
int menu_vs_omakase_samples(menu_state *m, uint64_t round, uint32_t first, uint32_t second, uint32_t third);
int menu_vs_time_open(menu_state *m, uint64_t round);
int menu_vs_time_vote(const menu_state *m, uint64_t round, int *zone, int *confirmed);
int menu_vs_time_commit(menu_state *m, uint64_t round, int zone);
int menu_vs_tune_open(menu_state *m, uint64_t round);
int menu_vs_tune_draft(const menu_state *m, uint64_t round, int *power, int *handling);
int menu_vs_tune_accept(menu_state *m, uint64_t round, int power, int handling);
int menu_vs_tune_ready(const menu_state *m, uint64_t round, int *power, int *handling);
/* Back queues sticky whole-round cancellation, not a local-only rewind. APP
 * keeps pumping the room, sends cancel and acknowledges the same generation. */
int menu_vs_cancel_requested(const menu_state *m, uint64_t *round);
int menu_vs_round_cancel(menu_state *m, uint64_t round, const char *note);
/* the area's result in: the time zone vote (MENU_BGM, vs.day) */
void menu_vs_day_open(menu_state *m);
/* MENU_VS_MATCH: open it (from MENU_VS's loading, m->vs.match filled in), whether it is over,
 * and back to the loading page after it */
void menu_vs_match(menu_state *m);
int menu_vs_match_done(const menu_state *m);
void menu_vs_match_back(menu_state *m);
/* the arcade's omakase: a random card (1..8), Hakone at half the odds */
int menu_vs_random_card(void);
/* the host's song for everyone's race (the GO's): the BGM line and the song as day_decide's */
void menu_vs_song(menu_state *m, int song);
/* the card name's glyphs (namedb's, -1 past its end) of an ASCII name (vs_name's: a save
 * with no name sends PLAYER n, which is nP) */
void menu_name_glyphs(short g[5], const char *ascii);
/* the vote's card (1..8) to the arcade's area (0 C1 .. 7 FUKUOKA: areaIDFromMenuOrder) */
int menu_vs_card_area(int card);
/* the race's GO: from the votes (or the lobby) to the versus' NOW LOADING */
void menu_vs_loading(menu_state *m);
/* the join ramp's name for the versus screen (0..MENU_VS_RAMPS-1) */
const char *menu_vs_ramp_name(int ramp);
/* the player's name in capitals for the online lobby (kana as romaji) */
void menu_name_ascii(const menu_state *m, char *out, int n);
/* clRaceThread::finiStory on a won episode (story_n): clears it, and the division's last
 * (its 20th, A+'s fifth) moves the story on to the next division. */
void menu_story_clear(menu_state *m, int n);
/* Battles won with the chosen car (a story race won, each 10-in-a-row rival beaten): its
 * dress-up level goes up one each (to 63), and an aero set won comes up after the race. */
void menu_dress_win(menu_state *m, int wins);
/* A dress-up wheel's pack (menu_state.wheel: emTireModelID + 1): its wheel_list.lua name and
 * texture set, data/wheels/<name>_<set>.wpk; NULL for none. */
/* Original emTireModelID 98 is used by a Ghost opponent, outside the dress ladder. */
enum { MENU_WHEEL_LEMANS = 99 };
const char *menu_wheel_pack(int wheel, int *set);
/* its GET screen model's pack name (wheels/<name>.wpk), NULL if none */
const char *menu_wheel_get(int wheel);
/* The dress-up wheels the screen may show next (up to max, the nearest first): the GET
 * screen's won one and the one worn, the change screen's places either side and the place's
 * colours, the wheel worn. The app keeps them loaded ahead. */
int menu_wheel_next(const menu_state *m, int *out, int max);
/* Taps on the items and the left/right keys (1024x768 points); with the pause menu open,
 * on its cards. */
void menu_touch(menu_state *m, void *id, int phase, float x, float y);
/* The start button: leaves the attract loop (not while it boots, menu_booting). */
void menu_start(menu_state *m);
/* The maker logos and the prologue the app boots into, before the first attract movie: no
 * tap skips them, so the course and the car models have that time to load (app.c). */
int menu_booting(const menu_state *m);
/* The attract movie that should be on screen now (0 atruct, 1 playdemo, 2 tutorial), or -1. */
int menu_movie(const menu_state *m);
/* The movie ended (or is missing): on to the title screen. */
void menu_movie_done(menu_state *m);
/* The BGM to play: a file name in data_dir/sound/bgm (without .m4a), or NULL for none.
 * racing: the race's song rather than the menus' music. */
const char *menu_bgm(const menu_state *m, int racing);
/* Advance by dt seconds; returns 1 once a race has been chosen (m->course, m->zone,
 * m->song) and its title page has shown (with m->ready set). */
int menu_update(menu_state *m, float dt);
/* The 3D layer of the current screen; returns 0 when it has none. */
int menu_scene3d(const menu_state *m, menu_scene *s);
const menu_ghost_directory_area *menu_ghost_preview_profile(const menu_state *m,int ghost_row);
int menu_in_attract(const menu_state *m);
int menu_story_body_for_profile(int maker,int car,int color,int power,int handling,int direct_full,story_body_view *out);
int menu_story_body_get(const menu_state *m,menu_story_body_stamp *out);
int menu_story_body_owner_same(const menu_state *m,const menu_story_body_stamp *old);
int menu_story_body_same(const menu_state *m,const menu_story_body_stamp *old);
int menu_story_body_scene_view(const menu_state *m,const menu_car *car,story_body_view *out);
/* Draws the screen; draw3d (if set) is called where the 3D cars go, between the
 * backgrounds and the overlays. */
/* mini3d (if set): the course selects' 3D map of Tokyo (clMiniatureCourse) over the
 * background, given the menu and the screen's fade (1 none, 0 black) */
void menu_draw(const menu_state *m, float screen_w, float screen_h, void (*draw3d)(void *), void *ctx,
               void (*mini3d)(void *, float));

#endif
