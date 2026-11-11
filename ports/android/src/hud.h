/* On-screen virtual controls and gauges. Coordinates are in points on a
 * 1024x768 landscape screen, origin top-left. */
#ifndef HUD_H
#define HUD_H

#include "car.h"

enum { TOUCH_BEGAN, TOUCH_MOVED, TOUCH_ENDED, TOUCH_CANCELLED };
enum { HUD_STEER_KEYS, HUD_STEER_GYRO, HUD_STEER_WHEEL, HUD_STEER_STICK, HUD_STEER_MODES };
enum { HUD_STICK_FLOAT, HUD_STICK_FIXED };

typedef struct {
  void *left_touch, *right_touch; /* steering buttons */
  int steer_mode; /* default KEYS; use hud_set_steer_mode when changing */
  int stick_center_mode;
  void *steer_touch;
  float steer_v, wheel_turn, wheel_last, stick_x0, stick_y0, stick_x, stick_y;
  void *throttle_touch, *brake_touch;
  int shift_up, shift_down; /* pending presses, consumed by hud_input */
  int camera_pressed, reset_pressed;
  int pause_pressed; /* the pause button (only it: a tap in the middle paused by mistake) */
  int pause_disabled; /* online VS */
  float screen_w, screen_h;
  /* the gyro steering (the OPTION screen's): the iPad turned like a wheel steers, the steer
   * buttons go, the brake takes their place and the shift buttons the brake's. tilt: the
   * turn (radians, + to the right, app_tilt); full: the turn that is full lock */
  int gyro;
  float tilt, full;
  /* the OPTION screen's slider pedals: a pedal's travel is the finger's height on its key
   * (the key's foot 0, its top and above 1); the pedals' last travels */
  int slide;
  float throttle_v, brake_v;
  int passing_available, passing_pressed; /* VS intrusion switch */
} hud_state;

void hud_init(hud_state *h, float screen_w, float screen_h);
/* Call on mode changes, including GYRO; clears active controls to prevent stuck touches. */
void hud_set_steer_mode(hud_state *h, int mode);
void hud_set_stick_center_mode(hud_state *h, int mode);
/* mode-aware layout variants; legacy functions below retain their boolean gyro API. */
int hud_layout_hit_mode(int mode, float x, float y);
void hud_layout_clamp_mode(int group, int mode, float k, float *dx, float *dy);
void hud_draw_layout_mode(float screen_w, float screen_h, int mode, int sel);
/* A screen wider than 4:3 (an iPhone's 3:2): edge layout px more on each side of the
 * 1024x768 layout (0 on the iPad); the consoles move out to the sides, the race's touch keys
 * too, key_k times their size. */
void hud_wide(float edge, float key_k);
/* A phone's 16:9 (after hud_wide), clear of the touch keys: the meters and the plate under
 * them dy layout px up, the shift gate and the map over it left px up; the top keys either
 * side of the back mirror (hud_wide's row is for the iPhone, without it). */
void hud_lift(float dy, float left);
/* By part (an iPhone's bigger keys): the meters, the name plate and the challenger
 * pill up (layout px), the map with its name and seconds left up, and the shift gate up. */
void hud_lift_parts(float cluster, float plate, float pill, float map, float gate);
/* The driver's class on the plate under the meters: 0 N .. 46 SSS (GetClass's). */
#define HUD_CLASSES 47
void hud_set_class(int cls);
/* And the card's title (src/title.h's id, 0 for 湾岸の新人) and name (namedb.h characters, -1
 * past its end; NULL or none: GUEST), drawn in the menus' glyphs (menu.bin). */
void hud_set_card(int title, const short *name);
/* `id` identifies a finger (the UITouch pointer on iOS). */
void hud_touch(hud_state *h, void *id, int phase, float x, float y);
/* Fill input and consume edge-triggered buttons. dt is elapsed seconds; invalid or
 * nonpositive values do not advance wheel return, and values above 0.1s are capped.
 * Call once per input tick. Full lock returns to center in 1/3s of accepted time. */
void hud_input_dt(hud_state *h, car_input *in, float dt);
/* Compatibility wrapper: advances as one 1/60s tick. */
void hud_input(hud_state *h, car_input *in);

int hud_gl_init(void);
/* Loads the arcade gauge sprites from data_dir/hud.bin (after hud_gl_init). */
int hud_load(const char *data_dir);
/* The car's own meters and gear pattern: its CARDB_PACKS index (src/meterdb.h), and the
 * night meters or the morning ones. Loads their sprites from meters.bin. */
void hud_set_car(int pack, int night);
/* Set before hud_load; NULL/empty uses data_dir. Overlong paths disable the sidecar. */
void hud_set_extra_directory(const char *dir);
/* 0 Normal, 1 For Racing, 2 Special; apply by calling hud_set_car afterwards. */
void hud_set_meter(int style);
/* Structural validation, not a checksum or authenticity check. */
int hud_validate_meter_file(const char *path);
int hud_meter_available(void);
/* Selected car/style preview, in menu 640x480 coordinates. Returns 0 if unavailable. */
int hud_meter_preview(int pack, int style, float x, float y, float w, float h, float alpha);
/* First-draws up to n of the HUD's sprites not drawn yet (the car's meters included), for
 * the race's title page; returns how many are left. */
int hud_warm(float screen_w, float screen_h, int n);
/* The car's tune on its plate: horsepower (car_tune_hp) and handling grade (car_tune_grade). */
void hud_set_tune(int hp, int grade);
/* The race's course (car_start's), for the time attack console: its name on the route map,
 * and the map starts afresh. */
void hud_set_course(int course);
/* The minimap of a city (CAR_TOKYO..): navi.bin Tokyo's, navi_<city>.bin the others' */
void hud_set_city(int city);
/* A checkpoint gave time: TIME EXTEND shows from the race's total `total` (car_race). */
void hud_time_extend(float total);
/* The route signs over the car (car_race.sign 1..HUD_SIGNS): the red ones and the caution
 * blink, and their sound repeats while they show. */
#define HUD_SIGNS 14
int hud_sign_blinks(int sign);
/* The course's RECORD TIME and the player's own (YOUR RECORD), in s; 0 shows dashes. */
void hud_set_records(float record, float yours);
/* The same personal-best run's cumulative checkpoint times, starting at zero. */
void hud_set_record_splits(int count, const float *at);
/* Returns 1 on a new intermediate TA checkpoint and opens the extend banner. */
int hud_ta_checkpoint(const car_race *race);
/* A story race: the time attack's records and course name are left out. */
void hud_set_story(int story);
/* A story race's rivals by slot: ECharacter, box visibility, select, original
 * series ID, and whether those slots still match the actual physics inputs. */
void hud_set_story_rivals(const int *chara, const unsigned char *shown, int n, int sel,
                          int series, int ranking_slots_valid);
/* A 10-in-a-row race at the level (0..9, 10 the 32-man extend), -1 for none: clTenConsole's
 * LV, rival count and split times stand in for the time attack's column. */
void hud_set_ten(int level);
/* A versus race (clJoinConsole): the link's other machines' boxes (clRivalInfoConsole1), n of
 * them (0: not a versus), in PCB order as car_set_versus has them: the name's characters
 * (namedb.h's, -1 past the end), the title (src/title.h, 0 the first), the car's name plate
 * (cardb.h's plate), its horsepower and handling grade (car_tune_hp, car_tune_grade), its tune,
 * and whether the box shows the tune's steps (an R35 in the race: changeToStepDisp). With them
 * the place, the cars in the race and the distance left stand in for the time attack's column
 * (car_race vs_rank, vs_gap, remain). seat: the machine's PCB id (0..3), its mark's colour. */
typedef struct {
  short name[5];
  int title, plate, hp, grade, power, handling, steps, seat;
} hud_vs_box;
void hud_set_vs(const hud_vs_box *box, int n);
/* The original Target console uses the same card art as a VS box, but
 * receives one frozen rival profile and a separate native signed gap. */
void hud_set_ghost_card(const hud_vs_box *box, int crown_area); /* -1 for an ordinary ghost */
void hud_set_ghost_gap(float gap_mm);
/* The 10-in-a-row rivals' lines (Cut::clCutIn): `frames` arcade frames of them, from the
 * race's cut-in info (car_race cut_*); hud_draw draws them. */
void hud_ten_cutin(const car_race *r, int frames);
/* Separate race dialogue; loop is the card's story-clear loop, not its race index. */
void hud_story_cutin_start(int select, int loop);
/* continuous=1 ONLY for the next period of the same uninterrupted attempt;
 * retries, returns, new stories and changed loops must use 0/start. Different
 * select/loop always reset. Queued but unpresented rows are never carried. */
void hud_story_cutin_period(int select, int loop, int continuous);
void hud_story_cutin_step(const car_race *r, int hit);
/* End a confirmed intermediate period without queuing its final result line. */
void hud_story_cutin_suspend(void);
/* Bounded port timing for result dialogue during the goal freeze. This may
 * initialize the result event if the goal appeared after the latest tick. */
int hud_story_cutin_goal_hold(const car_race *r);
/* Draw separately after the finish layer, including Goal and TimeUp states. */
void hud_story_cutin_draw(void);
/* A story realtime movie's show (src/storydemo.h's table, -1 none): started with the movie
 * (its pictures put up in GL), one arcade frame of it (1 while it holds the movie still), drawn
 * over the movie, ended with it */
void hud_demo_start(int table);
int hud_demo_step(void);
void hud_demo_draw(const hud_state *h);
void hud_demo_end(void);
/* clGraphicFrame's negaposi (+0x174, neg.cg) as a 10-in-a-row rival is beaten: the 3D scene
 * drawn so far, colours inverted. */
void hud_negate(const hud_state *h);
/* clGraphics' clFader (draw 0x852b118) in white over the whole screen, alpha 0..1 */
void hud_white(const hud_state *h, float alpha);
/* the same in grey (0 black, 1 white) */
void hud_fade(const hud_state *h, float grey, float alpha);
/* The race camera's view and projection (column-major), for the rival's mark over its car */
void hud_rival_view(const float view[16], const float proj[16]);
/* -1: hidden/unknown; otherwise leader's remaining metres (0..600).
 * story_excluded marks original non-ranking story slots; trailing receives
 * whether a competing opponent leads; ties count as not trailing.
 * ghost_gap_mm is NULL outside Ghost Battle. */
int hud_finish_result(const car_race *r, int story, int count, unsigned story_excluded,
                      int ten, int versus, const float *ghost_gap_mm, int *trailing);
/* One fixed 60 Hz visual tick; draw entry points do not advance these clocks. */
void hud_visual_tick(const car_state *car);
void hud_draw(const hud_state *h, const car_state *car, const car_input *in, float fps);

/* Race console transforms in 1024x768 layout points; identity is (1,0,0). */
enum { HUD_RACE_MAP, HUD_RACE_RANK, HUD_RACE_TIME, HUD_RACE_METER, HUD_RACE_GROUPS };
void hud_race_layout_set(int group, float k, float dx, float dy);
int hud_race_layout_hit(float x, float y);
/* Largest scale fitting the current visible layout, capped at 1.6 and floored
 * at 0.6 for sidecar v1. If even 0.6 cannot fit, clamp centers the oversized
 * group and clipping remains possible. The editor displays/persists its choice. */
float hud_race_layout_max_scale(int group);
void hud_race_layout_clamp(int group, float k, float *dx, float *dy);
void hud_draw_race_layout(float screen_w, float screen_h, int sel);

enum { HUD_KEYS_TOP, HUD_KEYS_LEFT, HUD_KEYS_RIGHT, HUD_KEY_GROUPS };
enum { HUD_EDIT_SHIFT = HUD_KEY_GROUPS, HUD_EDIT_SHIFT_UP, HUD_EDIT_SHIFT_DOWN,
       HUD_EDIT_PAUSE, HUD_EDIT_CAMERA, HUD_EDIT_GROUPS };
void hud_set_stick_deadzone_percent(int percent);
/* Separate transform is absolute, anchored like the right keys; disabled inherits them. */
void hud_shift_layout_set(int separate, float k, float dx, float dy);
void hud_button_layout_set(int group, int separate, float k, float dx, float dy);
void hud_set_button_opacity_percent(int percent);
#define HUD_KEY_K_MIN 0.6f
#define HUD_KEY_K_MAX 1.6f
void hud_layout_set(int group, float k, float dx, float dy);
int hud_layout_hit(int gyro, float x, float y);
void hud_layout_clamp(int group, int gyro, float k, float *dx, float *dy);
void hud_draw_layout(float screen_w, float screen_h, int gyro, int sel);

/* The menus' left/right keys and back button: which one is at (x, y)
 * (-1, +1, HUD_MENU_BACK, or 0), and drawing them (held = the one being pressed, or 0;
 * keys is a direction mask on Android and back enables the return button). */
enum { HUD_MENU_LEFT_KEY = 1, HUD_MENU_RIGHT_KEY = 2, HUD_MENU_BOTH_KEYS = 3 };
#define HUD_MENU_BACK 2
#define HUD_MENU_OPTION 3 /* the OPTION button (the brand select's, left of back) */
#define HUD_MENU_HIDDEN 4 /* the maker select's hidden cars key, in the bottom bar's middle */
int hud_menu_key(float x, float y);
void hud_draw_menu_keys(float screen_w, float screen_h, int held, int keys, int back);
/* the OPTION button, a gear, in the same style (held: being pressed) */
void hud_draw_menu_option(float screen_w, float screen_h, int held);
/* the car setting's wheel key, in the OPTION button's place (HUD_MENU_OPTION): the
 * dress-up menu */
void hud_draw_menu_dress(float screen_w, float screen_h, int held);
/* the hidden cars key (HUD_MENU_HIDDEN): the button; its caption is the menus' sprite */
void hud_draw_menu_hidden(float screen_w, float screen_h, int held);
/* the save's car view's delete key there, a bin (armed: red, the next press deletes) */
void hud_draw_menu_erase(float screen_w, float screen_h, int held, int armed);

/* The online versus's screen (a port screen, no arcade sprites): panels, buttons and text in
 * a 5x7 font (capitals, digits and . : - / < > ( ) ! ? + #), in the menus' points (1024 x 768,
 * x past EDGE). */
void hud_ui_begin(float screen_w, float screen_h);
void hud_ui_rect(float x, float y, float w, float h, float r, float g, float b, float a);
/* Four HUD-space XY points in triangle-strip order, using the same UI batch. */
void hud_ui_quad(const float xy[8], float r, float g, float b, float a);
void hud_ui_button(float x, float y, float w, float h, int held);
/* text with its top left at (x, y), each font pixel px points; returns the x after it */
float hud_ui_text(const char *s, float x, float y, float px, float r, float g, float b, float a);
float hud_ui_text_width(const char *s, float px);
void hud_ui_end(void);

#endif
