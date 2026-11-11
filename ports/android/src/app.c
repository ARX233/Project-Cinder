#include "app.h"
#if defined(__ANDROID__) && defined(WMMT_DEBUG_LOG)
#include "debug_log.h"
#include <math.h>
#include <stdint.h>
#endif

#include <pthread.h>
#include <fcntl.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <zlib.h>
/* (the NDK's zconf.h defines far and near away, for 16-bit DOS) */
#undef far
#undef near
#include <sys/stat.h>
#include <time.h>
#ifdef __APPLE__
#include <mach/mach.h>
#include <mach/mach_time.h>
#else
#include <time.h>
#endif

#include "anm.h"
#include "car.h"
#include "cardb.h"
#include "carwheel.h"
#include "rivaldb.h"
#include "tendb.h"
#include "storycity.h"
#include "storymovie.h"
#include "storyinfo.h"
#include "gl.h"
#ifdef WMMT_NATIVE_VK
#include "native_vk.h"
#endif
#include "hud.h"
#ifdef __ANDROID__
#include "stick_center_store.h"
#include "junction_ui.h"
#include "junction_barrier.h"
#include "tire_track.h"
#include "tire_smoke_asset.h"
#include "render_ghost_paint.h"
#include "ghost_catalog.h"
#include "tail_trail_scene.h"
#include "junction_table_private.h" /* derived privately from the verified arcade ELF */
/* Game-thread notification; the Android player applies it on the UI thread. */
void android_story_bgm_pause(void);
#endif
#include "lights.h"
#include "spark.h"
#include "backfire.h"
#include "backfire_wpk.h"
#include "mathx.h"
#include "menu.h"
#include "mileage_style.h"
#include "card_choice_store.h"
#include "story_evidence_store.h"
#include "minicourse.h"
#include "gk.h"
#include "net.h"
#include "vs_host.h"
#ifdef __ANDROID__
#include <math.h>
#endif
#include "render.h"
#include "ghost_paint.h"
#include "app_ghost_paint.h"
#include "player_body_paint.h"
#include "player_paint_resource.h"
/* Implemented by the renderer; independent of the original HQ switches. */
void render_enhance(int on);
#include "sound.h"
#include "title.h"
#include "timing60.h"
#include "presentation60.h"

/* Legacy app_frame still draws; app_present runs its fixed logic without draws. */
static int app_tick_only;
static car_input app_display_input;
static timing60_sim app_clock;
static car_state app_previous, app_display_car;
static int app_history_valid;
static float app_display_dt;
static void app_draw_frame(float dt, const car_input *input, int steps, double physics_ms, const car_state *c);
static void menu_present(double frame_start);

#define MAX_ARROWS 128

/* The arcade's maps by city (car.h CAR_TOKYO..) and time zone (menu_state.zone): Tokyo's
 * morning (other_stage/c1_daytime.lua) and night (tokyo/night/night.lua), packed by
 * tools/stage/pack_tokyo.sh, the other cities' .lua files in data/<city>/daytime and night by
 * tools/stage/pack_city.py; each with its sky box, junction arrow boards (arrows*.wpk) and
 * street lights (lights*.bin, tools/stage/pack_lights.py) and its minimap (hud_set_city).
 * Only the chosen map is in GL at a time. */
static const char *const CITY_FILE[CAR_CITIES] = { "tokyo", "oosaka", "hakone", "nagoya", "fukuoka" };
/* their FogParam (the global fog: far, near, colour) */
static const struct {
  float far, near, color[3];
} FOG[CAR_CITIES][2] = {
  { { 35000.0f, 100.0f, { 0.6f, 0.75f, 0.8f } }, { 25000.0f, 250.0f, { 0.6f, 0.75f, 0.8f } } },
  { { 25000.0f, 1.0f, { 0.88f, 0.88f, 0.905f } }, { 25000.0f, 250.0f, { 0.3f, 0.3f, 0.3f } } },
  { { 15000.0f, 100.0f, { 0.6f, 0.7f, 0.75f } }, { 2000.0f * 1.8f, 250.0f, { 0.1f, 0.1f, 0.1f } } },
  { { 25000.0f, 1.0f, { 0.88f, 0.88f, 0.905f } }, { 25000.0f, 1.0f, { 0.3f, 0.3f, 0.3f } } },
  { { 16000.0f, 1.0f, { 0.0f, 0.0f, 0.0f } }, { 25000.0f, 1.0f, { 0.3f, 0.3f, 0.3f } } },
};
/* the port's own grade of a map and its sky (render_params.grade; 0 none): Hakone's morning
 * in a brighter, warmer sun, its night darker under a cool moon, the lamps and the cars
 * as they are (Allan, 10-26: one multiply in the scene programs, nothing for the A5X) */
static const float MAP_GRADE[CAR_CITIES][2][3] = {
  [CAR_HAKONE] = { { 1.16f, 1.12f, 1.02f }, { 0.72f, 0.74f, 0.82f } },
};
/* the cars' lights (render_params light_*), data/car_light.lua by course and time zone
 * (clGraphicFrame::initCarLight): the sun and the "headlight", the scene ambient for every
 * car; its material (diffuse 1, ambient 0.9) lights all but the car.cg / car_blend.cg parts */
typedef struct {
  float dir[2][3], diffuse[2], ambient, mat_diffuse, mat_ambient;
} car_light;
static const car_light CAR_LIGHT[CAR_CITIES][2] = {
  { /* tokyo-daytime, tokyo-night */
    { { { -0.5f, -1.0f, -0.3f }, { 0.0f, -1.0f, 0.0f } }, { 0.62f, 0.52f }, 0.35f, 1.0f, 0.9f },
    { { { 0.5f, -0.15f, -0.3f }, { 0.0f, -1.0f, -0.2f } }, { 0.73f, 0.55f }, 0.32f, 1.0f, 0.9f } },
  { /* oosaka */
    { { { -0.5f, -1.0f, -0.3f }, { 0.0f, -1.0f, 0.0f } }, { 0.62f, 0.53f }, 0.35f, 1.0f, 0.9f },
    { { { 0.5f, -0.2f, -0.3f }, { 0.0f, -1.0f, -0.2f } }, { 0.73f, 0.54f }, 0.29f, 1.0f, 0.9f } },
  { /* hakone */
    { { { 0.5f, -1.0f, -0.3f }, { 0.0f, -1.0f, 0.0f } }, { 0.62f, 0.45f }, 0.31f, 1.0f, 0.9f },
    { { { 0.5f, -1.0f, -0.3f }, { 0.0f, -1.0f, 0.0f } }, { 0.79f, 0.66f }, 0.14f, 1.0f, 0.9f } },
  { /* nagoya */
    { { { -0.5f, -1.0f, -0.3f }, { 0.0f, -1.0f, 0.0f } }, { 0.62f, 0.53f }, 0.35f, 1.0f, 0.9f },
    { { { 0.5f, -0.2f, -0.3f }, { 0.0f, -1.0f, -0.2f } }, { 0.73f, 0.54f }, 0.29f, 1.0f, 0.9f } },
  { /* fukuoka */
    { { { -0.5f, -1.0f, -0.3f }, { 0.0f, -1.0f, 0.0f } }, { 0.62f, 0.53f }, 0.35f, 1.0f, 0.9f },
    { { { 0.5f, -0.2f, -0.3f }, { 0.0f, -1.0f, -0.2f } }, { 0.73f, 0.54f }, 0.29f, 1.0f, 0.9f } },
};
/* the menus' (clMenu3dEnvironment): data/menu/menu_4.lua's first two lights (car.cg reads
 * two), the ambient addRender sets (0.1), GL's default material */
static const car_light MENU_LIGHT = { { { 1.0f, -0.8f, -0.9f }, { -1.0f, -0.7f, -0.8f } }, { 0.85f, 0.8f }, 0.1f, 0.8f, 0.2f };
/* the other environments' (clMenu3dEnvironment(n): data/menu/menu_<n>.lua, 0 menu.lua) the
 * dress-up screens and the story tuning work (8) use: their first two lights, the rest as menu_4's */
static const struct {
  int env;
  car_light light;
} MENU_ENV_LIGHT[] = {
  { 0, { { { -0.3f, -0.7f, -1.0f }, { 1.0f, -0.7f, -0.3f } }, { 0.9f, 0.7f }, 0.1f, 0.8f, 0.2f } },
  { 3, { { { 0.2f, -0.2f, -0.9f }, { -0.6f, -0.2f, -0.9f } }, { 0.9f, 0.75f }, 0.1f, 0.8f, 0.2f } },
  { 5, { { { 0.7f, -0.8f, 1.0f }, { -0.3f, -0.2f, 1.0f } }, { 1.0f, 1.0f }, 0.1f, 0.8f, 0.2f } },
  /* the wheel change's (seen from behind: menu_4's lights left it black) */
  { 7, { { { -0.8f, -0.8f, 1.0f }, { 0.7f, -0.2f, 0.9f } }, { 1.0f, 0.8f }, 0.1f, 0.8f, 0.2f } },
  { 8, { { { -0.9f, -0.8f, 0.7f }, { 1.0f, -0.7f, 0.8f } }, { 0.9f, 0.7f }, 0.1f, 0.8f, 0.2f } },
  { 11, { { { 0.4f, -0.2f, -1.0f }, { -0.7f, -0.8f, -1.0f } }, { 1.0f, 0.9f }, 0.1f, 0.8f, 0.2f } },
  { 13, { { { -0.8f, -0.8f, -1.0f }, { 0.0f, -0.2f, 1.0f } }, { 1.0f, 1.0f }, 0.1f, 0.8f, 0.2f } },
  { 14, { { { 0.0f, -1.0f, -1.0f }, { 1.0f, -1.0f, 0.0f } }, { 0.9f, 0.5f }, 0.1f, 0.8f, 0.2f } },
  { 16, { { { 0.4f, -0.3f, 1.0f }, { -0.7f, -0.9f, 0.9f } }, { 1.0f, 0.9f }, 0.1f, 0.8f, 0.2f } },
};

static const car_light *menu_env_light(int env) {
  for (size_t i = 0; i < sizeof MENU_ENV_LIGHT / sizeof MENU_ENV_LIGHT[0]; ++i)
    if (MENU_ENV_LIGHT[i].env == env) return &MENU_ENV_LIGHT[i].light;
  return &MENU_LIGHT;
}

static void set_car_light(render_params *rp, const car_light *l, const mat4 *view) {
  for (int k = 0; k < 3; ++k) {
    for (int i = 0; i < 2; ++i) {
      rp->light_dir[i][k] = l->dir[i][k];
      rp->light_diffuse[i][k] = l->diffuse[i];
    }
    rp->ambient[k] = l->ambient;
    rp->material_diffuse[k] = l->mat_diffuse;
    rp->material_ambient[k] = l->mat_ambient;
  }
  rp->view = *view;
}

/* clMapDisp::initSkyBox puts the sky box 1000 m down */
#define SKY_DROP 10000.0f

/* car models: the car select's (data/cars, CARDB_PACKS), then the story rivals' own
 * (data/chara, RIVALDB_CHARA) */
#define NPACKS (CARDB_NPACKS + RIVALDB_NCHARA)

/* what the menus want loaded, for the loading (load_wants_now) */
typedef struct {
  int order[NPACKS], n; /* car models, most wanted first */
  int first;                  /* how many of them come before the course */
  int cars_before_warm;       /* the rest before warming the course (in the car select) */
  int paints[NPACKS], n_paints; /* car models whose other paints are wanted (the car under the cursor) */
  int paints_first;           /* those come before the course too (in the car select) */
  int hold_track;             /* the last map is still being freed: the next waits */
  int course;                 /* the course chosen: the map warms from its start out (warm_step) */
} load_wants;

/* what is loaded, from the loading to the menus (load_sync) */
typedef struct {
  signed char pack[NPACKS];  /* 1 in GL, -1 missing, 0 not (yet) */
  signed char paint[NPACKS]; /* 1 its other paints are in GL too */
  int track;                       /* 1 all of the map is in GL, 2 and first-drawn (warm_step) */
  int start;                       /* course + 1 whose start the race's first frames find warm (warm_step) */
} load_news;

#define CAR_BEST_MAX 512 /* car types' records kept (47 cars, 6 courses) */
/* the dress-up wheels kept in GL: the change screen's place, those either side, its colours */
#define WHEEL_SLOTS 8
#define MENU_AERO_SLOTS 4
/* a car's dress-up as a versus profile sends it (menu_state's of the car) */
typedef struct {
  int aero, mirror, wing, bonnet, wheel, neon, vinyl;
} vs_dress_t;
enum { WHEEL_FREE, WHEEL_READY, WHEEL_UP, WHEEL_WARM, WHEEL_MISSING };

/* Frozen APP race presentation/config, never a transport compatibility alias. */
typedef struct {
  vs4_nonce incarnation;
  uint64_t membership, term, round, config;
  uint32_t seed;
  int ramp, zone, km, song, n, pcb;
  net_player player[NET_PLAYERS]; /* immutable baseline P/H remain in each member */
} app_vs_round;
static struct {
  wpk_scene track; /* the map of track_city and track_zone */
  int track_city, track_zone;
  int extras_city; /* the city whose sky boxes, arrow boards, lights and minimap are loaded (-1 none) */
  /* render_hq up (Android); the OPTION screen's graphics switches last applied (hq_apply),
   * the maps' ASTC packs (*.astc.wpk) in use */
  int hq_on, hq_bloom, hq_ssao, hq_env, hq_ssao_made, hd_maps, hd_reload;
  wpk_scene track_old; /* the other time zone's, freed a step a menu frame (track_open) */
  wpk_scene sky[2];
  /* the car select's models (data/cars, tools/stage/pack_cars.py), loaded as the menus need
   * them; fd3s.wpk stands in for any that is missing */
  wpk_scene fd3s, packs[NPACKS];
  signed char pack_state[NPACKS]; /* 0 not loaded, 2 going up, 3 first drawing, 1 loaded, -1 missing */
  signed char paint_state[NPACKS]; /* its other paints (wpk_upload_paints): 0 not, 2 going up, 3 first drawing, 1 in GL */
  int low_memory; /* iOS warned: keep only the car models near the maker on show */
  wpk_scene *race_model;
  wpk_scene aero;  /* the player's car in its dress-up aero set, on race_model's textures */
  int aero_pack, aero_set; /* what aero holds (aero_set 0: nothing) */
  /* the dress-up screens' cars in their aero sets A..C (menu_aero): a car pack and set each
 * (the versus' cars flying in may be of several) */
  wpk_scene menu_aero[MENU_AERO_SLOTS];
  int menu_aero_pack[MENU_AERO_SLOTS], menu_aero_set[MENU_AERO_SLOTS], menu_aero_in[MENU_AERO_SLOTS];
  /* a versus' other cars dressed up as their profiles say (vs_dress; their aero sets in
   * menu_aero's slots, menu_aero_want) */
  vs_dress_t rival_dress[CAR_RIVALS];
  /* the dress-up wheels in GL (wheel_model, wheel_sync): menu_state.wheel's value each
   * holds, how far it is (WHEEL_*), when last wanted; the one the menus last showed */
  wpk_scene wheel[WHEEL_SLOTS];
  int wheel_id[WHEEL_SLOTS], wheel_state[WHEEL_SLOTS];
  unsigned wheel_used[WHEEL_SLOTS], wheel_tick;
  int wheel_shown;
  /* the wheel GET screen's model (get_wheel_model), the same way */
  wpk_scene get_wheel;
  int get_wheel_id, get_wheel_ok;
  /* the traffic's models (tools/stage/pack_traffic.sh), by CAR_TRAFFIC_* */
  wpk_scene traffic[CAR_TRAFFIC_MODELS];
  char data_dir[1024];
  int race_traffic;
  int options_global; /* the OPTION screen's choices from save_dir/option (options_load) */
  char save_dir[1024]; /* where perf.log, the saves (records<n>, garage<n>, slot) and timezone go (app_save_dir) */
  /* the arcade's junction arrow boards (coursearrow), one object per junction block, by time zone */
  wpk_scene arrows[2];
  char arrow_names[MAX_ARROWS][48];
  int n_arrows;
  unsigned char arrow_visible[MAX_ARROWS];
  unsigned char arrow_switched[MAX_ARROWS]; /* named in the junction block table */
  int hk_arrow; /* Hakone's board shown: 0 none, 1 hk_for, 2 hk_back */
  int arrow_table_ready;
  /* the course selects' 3D miniature of Tokyo (clMiniatureCourse, src/minicourse.h) */
  wpk_scene mini;
  unsigned char mini_visible[MINI_OBJECTS];
  const mini_course *mini_shown; /* the card it shows (NULL off the course selects) */
  float mini_from[2][3];         /* the camera and aim it moves from */
  int mini_move, mini_frame;
  car_state car;
  hud_state hud;
  menu_state menu;
  int in_menu; /* the front end is up; the race starts once a course is chosen */
  int paused;  /* the race is frozen under its pause menu */
  int track_ready; /* as load_news.track: the loading's (the menus see seen.track) */
  int start_ready; /* as load_news.start */
  int pre_wait;    /* frames the race's title page has waited for the loading */
  int pre_frames;  /* and has been up (perf.log) */
  int count_shown; /* the start's countdown as the console last showed it (app_frame) */
  /* the loading (load_unit), by the menu frames or by a thread of its own (app_loader) */
  pthread_mutex_t load_mx;
  pthread_cond_t load_cv;
  int loader_up; /* the thread is there (it says so itself) */
  int loader;    /* the menus know it is: the frames leave the loading to it */
  int load_run;  /* it may load: the menus are up and so is the app */
  int load_busy; /* it is in a load_unit */
  int load_idle; /* it found nothing to do and waits for the menus' next frame */
  double frame_start; /* the menu frame's (app_frame) */
  double load_until;  /* the thread loads between a menu frame's end (app_frame_done) and this */
  int load_hurry;     /* the menus wait for the loading (NOW LOADING, the race title, the boot logos) */
  int load_wait;      /* the car select's NOW LOADING: nothing on show but it */
  int load_units;     /* the thread's steps and their time, for perf.log (under load_mx) */
  double load_ms;
  int away;      /* the app is in the background, where iOS allows no GL */
  load_wants wants;
  load_news pub, seen; /* as the loading has it, and the menus' copy */
  render_params rp;
  int fb_w, fb_h;
  int camera; /* 0 the arcade's view behind the car, 1 its roof view */
  float fps;
  char error[256];
  /* frame timing of the race, for hunting hitches: perf.log in the data folder */
  FILE *perf;
  double race_time, max_phys, max_render;
  int perf_frames, odd_steps, slow_frames;
  /* render_hq's governor: a window's frames, those that missed; the level, the lowest it
   * may go back up to, the frames since it last went up */
  int gov_frames, gov_slow, gov_level, gov_floor, gov_since_up;
  double present_ms; /* the last frame's wait in presentRenderbuffer (app_frame_done) */
  double seg[8];     /* the race frame's render, by part (perf_frame) */
  int race_frames; /* presented race frames: GPU warm-up/reflection/perf only, never RC time */
  /* the overhead reflection (render_overhead, not the arcade's): off for a test
   * (WMMT_NO_OVERHEAD); this frame's map drawn for the player's car, its batches and ms */
  int no_over, over_drawn, over_draws, over_tris;
  int bm_shown, bm_draws, bm_tris; /* the back mirror this frame (draw_backmirror) */
  double bm_ms;
  double over_ms;
  float tilt; /* the iPad's turn about the screen's normal (app_tilt), radians */
  int no_sharp; /* test: WMMT_NO_SHARPEN */
  int ao_test;  /* test: WMMT_AO=0 or 1 over the OPTION screen's (-1 none) */
  /* an iPhone (app_wide): the screen edge layout px wider than 4:3 on each side, and the
   * A4's cuts (phone): no sharpening, overhead map, radial blur or map gloss, shorter
   * building ranges, the traffic only near, few car models kept */
  float edge;
  int phone;
  int console; /* app_console: a phone of today's (Android), everything on and further */
  int sharp_rest, sharp_rested; /* frames the sharpening sits out yet; of perf_frame's 600 */
  int time_shown;  /* the whole seconds left the console shows, for its ticks */
  int ten_rival_on; /* the 10-in-a-row's rival its approach sound was played for (-1: none yet) */
  int ten_freeze;   /* frames left of a beaten 10-in-a-row rival's still, negative frame */
  int ten_beaten_on; /* that frame's play state 9 has been seen (till it goes) */
  int ten_bgm_off;  /* the last rival is beaten: no race BGM */
  const char *ten_bgm;
  int ten_bgm_round;
  int ten_white;    /* frames since the 10-in-a-row's white went up (0: none) */
  int sign, sign_t; /* the route sign over the car, and frames to its next sound */
  int best_ms[CAR_COURSES]; /* the player's best time on each course (data_dir/records), 0 = none */
  struct { int count; float at[CAR_SECTIONS + 1]; } best_splits[CAR_COURSES];
  /* the machine's best time of each car type (model pack) on each course, from data_dir/records */
  struct { int course, pack, ms; } car_best[CAR_BEST_MAX];
  int n_car_best;
  int race_pack;   /* the race's car (CARDB pack) */
  /* the titles (src/title.h): the card before the race (judgeTitle's PRE) and its mileage then */
  title_card title_pre;
  double title_odo0;
  float story_mileage_pending_mm, story_mileage_unrestored_mm;
  /* the CPU rivals: the race's first (RIVALDB, -1 none; the others are the rows after it,
   * rival_rows), and each one's car model and paint (rival_look) */
  int rival, n_rival, rival_pack[CAR_RIVALS], rival_paint[CAR_RIVALS];
  int rival_env;   /* a test's rival (env WMMT_RIVAL), -1 none */
  int story_race;  /* the select's race to run next (0 the first; some selects have two) */
  /* One explicit automatic transition only; a retry or menu departure is fresh. */
  int story_cut_pending, story_cut_select, story_cut_loop, story_cut_period;
  /* Volatile one-attempt transition; never persisted in the user's saves. */
  uint64_t story_carry_serial, story_carry_token;
  int story_carry_select, story_carry_period, story_carry_series;
  int story_carry_attempted, story_old_ended, story_race_slots_valid;
  int story_end_freeze, story_end_started; /* goal effect; simulation held, dialogue advances */
  /* a story select's realtime movie before its race (car_movie_start): frames run and its
   * length (0: none playing), how it fades out, the race to start after it, and the models
   * of its cars 1..3 */
  float movie_frame, movie_len;
  int movie_fade, movie_in;
  /* a select's race after its first: frames left of its fade in (the previous race's
   * STORYRACE_FADE: clRaceThread::run's setFade(0, 1, 1/3)) over its movie, and that fade */
  int period_in, period_fade;
  car_spec race_spec;
  car_rival race_rv[CAR_RIVALS];
  int race_nrv, race_course;
  wpk_scene *movie_model[CAR_RIVALS];
  int movie_paint[CAR_RIVALS], movie_pack[CAR_RIVALS];
  wpk_scene *rival_model[CAR_RIVALS];
  /* the 10-in-a-row's rivals in order (its one rival on the road changes each round): their
   * car models and paints */
  int n_ten, ten_pack[CAR_TEN_RIVALS], ten_paint[CAR_TEN_RIVALS];
  float top_kmh;   /* the race's top speed so far */
  /* the online versus (net.c): this app's id at the server, when it asked to connect, the race
   * the host started (net_take_go), and the other cars in the race on the road (0: no versus;
   * they are rivals 0.. in PCB order) */
  uint32_t vs_id;
  double vs_asked, vs_abort_note_until, vs_wait_note_until, vs_no_go_note_until;
  /* the area vote, as its host: when it opened, when the result was out; the time zone vote's
  * the same and when the race was asked for */
  double vs_area_at, vs_final_at;
  double vs_day_at, vs_day_final_at, vs_day_started;
  /* the race loaded: frames waited for the others', the machines (by PCB) seen loaded */
  int vs_wait, vs_seen_loaded;
  app_vs_round vs_go;
  int vs_race;
  int vs_song;      /* the host's: its song for everyone's race */
  int vs_closed;    /* a race's frames since the host closed the game (or went quiet): its notice */
} G;
/* Fifth-mode hooks are implemented in app_ghost.inc after the load/VS helpers. */
static int app_ghost_mode(void);
static int app_ghost_rival_pack(int *paint);
static int app_ghost_arcade_dressed(void);
static void app_ghost_arcade_apply_dress(vs_dress_t *out);
static void app_ghost_context_reset(void);
static int app_ghost_arcade_aero(int *pack,int *set);
static void app_arcade_paint_drop(int context_lost);
#include "app_story_body_runtime.inc"

static void app_body_drop(int context_lost);
static void app_body_evict_pack(int pack);
static void app_body_evict_scene(wpk_scene *scene);
static void app_body_reset(int context_lost);
static void mileage_aura_open(const char *data_dir);
static player_body_paint_identity app_body_identity(const menu_body_color_view *v);
static int app_body_prepare(player_body_paint_cache *cache,const menu_body_color_view *v,wpk_scene *scene);
static int app_body_menu_prepare(const menu_scene *shown);
static int app_body_start_ready(void);
static int app_body_race_prepare(void);
static int app_body_menu_apply(const menu_car *car,wpk_scene *scene,app_player_paint_scope *scope);
static int app_body_race_apply(wpk_scene *scene,app_player_paint_scope *scope);
#ifdef __ANDROID__
static junction_ui race_junction_ui;
static junction_barrier race_junction_barrier;
#endif

#if defined(__ANDROID__) && defined(WMMT_DEBUG_LOG)
/* Only fixed keys and numeric values cross this boundary. Never inspect the
 * recompiler's virtual memory here: car_state is the public snapshot. */
static uint64_t debug_render_seq, debug_sim_seq;
/* Only fields emitted by sim; do not copy car_state (contains private/large data). */
typedef struct {
  float pos[3], vel[3], yaw, pitch, roll, speed, rpm, wall_hit, impact;
  int vel_ok, gear, on_ground;
  struct { float spark, at[3], dir[3]; } effect;
  struct { int area, next_area, section, remain_valid, place, state, play_state;
           float remain, place_at; } race;
  int in_menu, sample_time_valid;
  uint64_t sample_monotonic_ns;
} debug_snapshot;
static debug_snapshot debug_capture(void) {
  const car_state *c = &G.car;
  debug_snapshot s = {0};
  /* Capture time describes the state read, not later logger enqueue time. */
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) == 0 && ts.tv_sec >= 0 &&
      ts.tv_nsec >= 0 && ts.tv_nsec < 1000000000L &&
      (uint64_t)ts.tv_sec <= (UINT64_MAX - (uint64_t)ts.tv_nsec) / UINT64_C(1000000000)) {
    s.sample_monotonic_ns = (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
    s.sample_time_valid = 1;
  }
  for (int k = 0; k < 3; ++k) {
    s.pos[k] = c->pos[k]; s.vel[k] = c->vel[k];
    s.effect.at[k] = c->effect.at[k]; s.effect.dir[k] = c->effect.dir[k];
  }
  s.yaw=c->yaw; s.pitch=c->pitch; s.roll=c->roll; s.speed=c->speed; s.rpm=c->rpm;
  s.wall_hit=c->wall_hit; s.impact=c->impact; s.effect.spark=c->effect.spark;
  s.vel_ok=c->vel_ok; s.gear=c->gear; s.on_ground=c->on_ground;
  s.race.area=c->race.area; s.race.next_area=c->race.next_area;
  s.race.section=c->race.section; s.race.remain_valid=c->race.remain_valid;
  s.race.remain=c->race.remain; s.race.place=c->race.place; s.race.place_at=c->race.place_at;
  s.race.state=c->race.state; s.race.play_state=c->race.play_state; s.in_menu=G.in_menu;
  return s;
}
/* Rising cues only; cooldown bounds noisy oscillations. 60 subsequent steps at
 * full detail, then >=180 steps between burst starts; sustained cues do not rearm. */
static uint64_t debug_burst_until, debug_next_burst;
/* A transition in finiteness is a diagnostic cue, not proof of a collision. */
static int debug_nonfinite(const debug_snapshot *s) {
  for (int k = 0; k < 3; ++k)
    if (!isfinite(s->pos[k]) || !isfinite(s->vel[k]) ||
        !isfinite(s->effect.at[k]) || !isfinite(s->effect.dir[k])) return 1;
  return !isfinite(s->yaw) || !isfinite(s->pitch) || !isfinite(s->roll) ||
         !isfinite(s->speed) || !isfinite(s->rpm) || !isfinite(s->wall_hit) ||
         !isfinite(s->impact) || !isfinite(s->effect.spark) ||
         !isfinite(s->race.place_at) || (s->race.remain_valid && !isfinite(s->race.remain));
}
static int debug_frame_sample(uint64_t seq) { return seq % 12 == 0; }
static int debug_sim_sample(const debug_snapshot *before, const debug_snapshot *after,
                            const car_input *in) {
  int edge = (before->wall_hit <= 0 && after->wall_hit > 0) ||
             (before->impact <= 0 && after->impact > 0) ||
             (before->effect.spark <= 0 && after->effect.spark > 0) ||
             (debug_nonfinite(before) != debug_nonfinite(after));
  int shift = in->shift_up || in->shift_down || before->gear != after->gear;
  if (edge && debug_sim_seq >= debug_next_burst) {
    debug_burst_until = debug_sim_seq + 60;
    debug_next_burst = debug_sim_seq + 240;
    return 1;
  }
  return shift || debug_sim_seq % 12 == 0 || debug_sim_seq <= debug_burst_until;
}
static const char *debug_number(char out[32], double value) {
  if (!isfinite(value)) return "null";
  snprintf(out, 32, "%.9g", value);
  /* The process may have selected a locale using a comma decimal separator. */
  for (char *p = out; *p; ++p) if (*p == ',') *p = '.';
  return out;
}
static void debug_frame(float raw, float actual) {
  ++debug_render_seq;
  if (!debug_log_enabled() || !debug_frame_sample(debug_render_seq)) return;
  char n[4][32];
  debug_log_emit("{\"event\":\"frame\",\"render_seq\":%llu,\"dt_raw\":%s,\"dt_actual\":%s,\"game\":%d,\"in_menu\":%d,\"menu_screen\":%d,\"race_state\":%d,\"play_state\":%d,\"paused\":%d,\"movie\":%d,\"frozen\":%d,\"race_frames\":%d,\"race_total\":%s,\"race_time\":%s}",
    (unsigned long long)debug_render_seq, debug_number(n[0], raw), debug_number(n[1], actual),
    G.menu.game, G.in_menu, G.menu.screen, G.car.race.state, G.car.race.play_state,
    !!G.paused, G.movie_len > 0, G.ten_freeze > 0, G.race_frames,
    debug_number(n[2], G.car.race.total), debug_number(n[3], G.race_time));
}
static void debug_step(const char *phase, int index, const car_input *in, const debug_snapshot *c) {
  if (!debug_log_enabled()) return;
  char n[25][32], sample_time[32];
  if (c->sample_time_valid) snprintf(sample_time, sizeof sample_time, "%llu", (unsigned long long)c->sample_monotonic_ns);
  debug_log_emit("{\"event\":\"sim\",\"phase\":\"%s\",\"sample_monotonic_ns\":%s,\"render_seq\":%llu,\"sim_seq\":%llu,\"step_index\":%d,\"steer\":%s,\"throttle\":%s,\"brake\":%s,\"shift_up\":%d,\"shift_down\":%d,\"analog\":%d,\"pos\":[%s,%s,%s],\"vel\":[%s,%s,%s],\"vel_valid\":%d,\"yaw\":%s,\"pitch\":%s,\"roll\":%s,\"speed\":%s,\"rpm\":%s,\"gear\":%d,\"area\":%d,\"next_area\":%d,\"section\":%d,\"remain_valid\":%d,\"remain\":%s,\"place\":%d,\"place_at\":%s,\"on_ground\":%d,\"wall_hit\":%s,\"impact\":%s,\"spark\":%s,\"spark_at\":[%s,%s,%s],\"spark_dir\":[%s,%s,%s],\"in_race\":%d,\"race_state\":%d,\"play_state\":%d}",
    phase, c->sample_time_valid ? sample_time : "null", (unsigned long long)debug_render_seq, (unsigned long long)debug_sim_seq, index,
    debug_number(n[0], in->steer), debug_number(n[1], in->throttle), debug_number(n[2], in->brake),
    in->shift_up, in->shift_down, in->analog,
    debug_number(n[3], c->pos[0]), debug_number(n[4], c->pos[1]), debug_number(n[5], c->pos[2]),
    debug_number(n[6], c->vel[0]), debug_number(n[7], c->vel[1]), debug_number(n[8], c->vel[2]), !!c->vel_ok,
    debug_number(n[9], c->yaw), debug_number(n[10], c->pitch), debug_number(n[11], c->roll),
    debug_number(n[12], c->speed), debug_number(n[13], c->rpm), c->gear, c->race.area, c->race.next_area, c->race.section,
    !!c->race.remain_valid, c->race.remain_valid ? debug_number(n[14], c->race.remain) : "null",
    c->race.place, debug_number(n[15], c->race.place_at), c->on_ground, debug_number(n[16], c->wall_hit),
    debug_number(n[17], c->impact), debug_number(n[18], c->effect.spark),
    debug_number(n[19], c->effect.at[0]), debug_number(n[20], c->effect.at[1]), debug_number(n[21], c->effect.at[2]),
    debug_number(n[22], c->effect.dir[0]), debug_number(n[23], c->effect.dir[1]), debug_number(n[24], c->effect.dir[2]),
    !c->in_menu && c->race.state == CAR_RACE_RUN, c->race.state, c->race.play_state);
}
/* The nearest sampled display transforms are context, not collision evidence.
 * Coordinates and distances are display units (0.1 m), in world axes. */
typedef struct { int index, model; double rel[3], distance2; } debug_near;
static void debug_near_candidate(debug_near *near, int index, int model,
                                 const float *body, const float *pos) {
  double rel[3], distance2 = 0;
  for (int k = 0; k < 3; ++k) {
    if (!isfinite(body[12 + k]) || !isfinite(pos[k])) return;
    rel[k] = (double)body[12 + k] - (double)pos[k];
    distance2 += rel[k] * rel[k];
  }
  if (!isfinite(distance2) || (near->index >= 0 && distance2 >= near->distance2)) return;
  near->index = index; near->model = model; near->distance2 = distance2;
  for (int k = 0; k < 3; ++k) near->rel[k] = rel[k];
}
static void debug_nearby(int index) {
  if (!debug_log_enabled()) return;
  const car_state *c = &G.car;
  debug_near traffic = { .index = -1 }, rival = { .index = -1 };
  int count = c->n_traffic, shown = 0;
  if (count < 0) count = 0;
  if (count > CAR_TRAFFIC) count = CAR_TRAFFIC;
  for (int k = 0; k < count; ++k)
    debug_near_candidate(&traffic, k, c->traffic[k].model, c->traffic[k].body, c->pos);
  for (int k = 0; k < CAR_RIVALS; ++k) if (c->rival_shown[k]) {
    int model = G.rival_pack[k], t = c->race.ten_rival;
    ++shown;
    if (k == 0 && G.n_ten && t >= 0 && t < G.n_ten && t < CAR_TEN_RIVALS) model = G.ten_pack[t];
    debug_near_candidate(&rival, k, model, c->rival_body[k], c->pos);
  }
  char n[8][32];
  debug_log_emit("{\"event\":\"nearby\",\"render_seq\":%llu,\"sim_seq\":%llu,\"step_index\":%d,\"traffic_count\":%d,\"rival_shown_count\":%d,\"traffic_index\":%d,\"traffic_model\":%d,\"traffic_rel\":[%s,%s,%s],\"traffic_distance\":%s,\"rival_index\":%d,\"rival_model\":%d,\"rival_rel\":[%s,%s,%s],\"rival_distance\":%s}",
    (unsigned long long)debug_render_seq, (unsigned long long)debug_sim_seq, index, count, shown,
    traffic.index, traffic.index >= 0 ? traffic.model : -1,
    traffic.index >= 0 ? debug_number(n[0], traffic.rel[0]) : "null",
    traffic.index >= 0 ? debug_number(n[1], traffic.rel[1]) : "null",
    traffic.index >= 0 ? debug_number(n[2], traffic.rel[2]) : "null",
    traffic.index >= 0 ? debug_number(n[3], sqrt(traffic.distance2)) : "null",
    rival.index, rival.index >= 0 ? rival.model : -1,
    rival.index >= 0 ? debug_number(n[4], rival.rel[0]) : "null",
    rival.index >= 0 ? debug_number(n[5], rival.rel[1]) : "null",
    rival.index >= 0 ? debug_number(n[6], rival.rel[2]) : "null",
    rival.index >= 0 ? debug_number(n[7], sqrt(rival.distance2)) : "null");
}
static void debug_race_init(void) {
  if (!debug_log_enabled()) return;
  int story = G.menu.game == MENU_GAME_STORY;
  debug_log_emit("{\"event\":\"race_init\",\"render_seq\":%llu,\"game\":%d,\"story_pick\":%d,\"story_race\":%d,\"series\":%d,\"course\":%d,\"city\":%d}",
    (unsigned long long)debug_render_seq, G.menu.game, story ? G.menu.story_pick : -1,
    story ? G.story_race : -1, story && G.race_nrv > 0 ? G.race_rv[0].series : -1,
    G.race_course, G.track_city);
}
#endif

/* Published backfire directories are immutable for this process. The path validator
 * prevents accidental corrupt packs from reaching the legacy loader; it does not
 * defend against an adversary replacing files between validation and loading. */
static bfx_asset backfire_asset;
static bfx_playback backfire_play;
static wpk_scene backfire_scene;
static int backfire_ready;
static char backfire_body[BFX_MAX_CARS][BFX_NAME];

static wpk_scene *menu_aero(int pack, int set);
static void backfire_reset(void) {
  bfx_reset(&backfire_play);
  memset(backfire_body, 0, sizeof backfire_body);
}
static int backfire_path(char *out, size_t cap, const char *dir, const char *name) {
  int n = snprintf(out, cap, "%s/%s", dir, name);
  return n >= 0 && (size_t)n < cap;
}
static int backfire_child(const char *root, const char *path) {
  char r[4096], p[4096];
  if (!realpath(root, r) || !realpath(path, p)) return 0;
  size_t n = strlen(r);
  return !strncmp(r, p, n) && p[n] == '/' && p[n+1];
}
#ifdef __ANDROID__
#include "app_tire_smoke.inc"
/* clTireTrackManager is created for the player's car only. Its texture is a
 * separately packed copy of the original tirepattern.tga; failure simply
 * disables this optional effect, never the race. */
static TireTrack player_tracks;
static wpk_scene track_scene;
static uint32_t track_texture;

static TailTrailScene race_tail_trails;
static struct {vs4_nonce incarnation;uint64_t round,config,membership,term;int camera;} race_tail_scope;
static void race_tail_reset(void) {
  tail_trail_scene_reset(&race_tail_trails);
  memset(&race_tail_scope,0,sizeof race_tail_scope);
}
static void player_tracks_reset(void) {
  tire_track_enable(&player_tracks, 1);
  player_smoke_reset();
  race_tail_reset(); /* all fresh race/movie starts also drop the previous history */
}

#if defined(WMMT_VK) && !defined(WMMT_NATIVE_VK)
extern int vkgl_error_pending(void);
extern uint64_t vkgl_error_epoch(void);
#endif
/* The release asset is a single 64x64 RGBA4444 WPK2 texture. Reject a missing,
 * wrong, or accidentally damaged asset before handing it to the WPK loader.
 * CRC is a corruption check, not authentication of an untrusted file. */
static int player_tracks_asset_valid(const char *path) {
  unsigned char bytes[8288];
  FILE *f = fopen(path, "rb");
  if (!f) return 0;
  size_t n = fread(bytes, 1, sizeof bytes, f);
  int extra = fgetc(f), error = ferror(f);
  fclose(f);
  return n == sizeof bytes && extra == EOF && !error &&
         crc32(0, bytes, (uInt)sizeof bytes) == 0x2719ca85u;
}

static void player_tracks_open(const char *data_dir) {
  char path[1100];
  track_texture = 0;
  tire_track_init(&player_tracks);
  player_tracks_reset();
  int n = snprintf(path, sizeof path, "%s/tiretrack.wpk", data_dir);
  if (n < 0 || (size_t)n >= sizeof path || !player_tracks_asset_valid(path)) {
    fprintf(stderr, "tire tracks: missing or invalid texture asset; effect disabled\n");
    return;
  }
#ifdef WMMT_VK
  /* Do not consume an earlier error. Any new rejection during the upload
   * disables the effect; this CPU check does not certify GPU completion. */
#ifdef WMMT_NATIVE_VK
  uint64_t epoch = cinder_vk_error_epoch();
  if (epoch == UINT64_MAX || cinder_vk_error_pending()) {
#else
  uint64_t epoch = vkgl_error_epoch();
  if (epoch == UINT64_MAX || vkgl_error_pending()) {
#endif
    fprintf(stderr, "tire tracks: Vulkan adapter already in error; effect disabled\n");
    return;
  }
#endif
  track_scene.fd = -1;
  if (wpk_load(&track_scene, path) != 0) {
    fprintf(stderr, "tire tracks: texture could not be loaded; effect disabled\n");
    return;
  }
  if (track_scene.n_tex != 1 || !track_scene.textures || !track_scene.loaded ||
      !track_scene.textures[0] || track_scene.loaded[0] != track_scene.textures[0]
#ifdef WMMT_NATIVE_VK
      || cinder_vk_error_pending() || cinder_vk_error_epoch() != epoch
#elif defined(WMMT_VK)
      || vkgl_error_pending() || vkgl_error_epoch() != epoch
#endif
      ) {
    wpk_free(&track_scene);
    fprintf(stderr, "tire tracks: texture upload failed; effect disabled\n");
    return;
  }
  track_texture = track_scene.textures[0];
  /* Only the GL texture is needed after upload. Detach it before freeing the
   * WPK tables so repeated app initialization cannot leak their CPU storage. */
  track_scene.loaded[0] = 0;
  wpk_free(&track_scene);
}

/* EffectConstructParam initializes width=2 and radius=3 in display units;
 * the arcade car table gives RC2 radius=2 and SW20 radius=2.5. */
static float player_track_radius(void) {
  int pack = G.race_pack;
  if (pack < 0 || pack >= CARDB_NPACKS) return 3.0f;
  if (!strcmp(CARDB_PACKS[pack], "sub_RC2")) return 2.0f;
  if (!strcmp(CARDB_PACKS[pack], "toy_SW20")) return 2.5f;
  return 3.0f;
}

static void player_tracks_tick(const car_state *car) {
  if (!car || !track_texture) return;
  float radius = player_track_radius();
  for (unsigned int i = 0; i < TIRE_TRACK_WHEELS; ++i)
    tire_track_append(&player_tracks, i, car->track_matrix[i], car->track_alpha[i], 2.0f, radius);
}

static void player_tracks_vertex(render_vertex *out, const TireTrackVertex *in, float vbase) {
  out->pos[0] = in->x; out->pos[1] = in->y; out->pos[2] = in->z;
  out->uv[0] = in->u; out->uv[1] = in->v - vbase;
  out->rgba[0] = out->rgba[1] = out->rgba[2] = 255;
  out->rgba[3] = (uint8_t)(in->alpha * 255.0f);
}

static void player_tracks_draw(const mat4 *vp, render_params *rp) {
  static render_vertex vertices[TIRE_TRACK_WHEELS * (TIRE_TRACK_PAIRS - 1) * 4];
  int n = 0;
  if (!track_texture || !player_tracks.enabled) return;
  for (unsigned int i = 0; i < TIRE_TRACK_WHEELS; ++i) {
    const TireTrackWheel *wheel = &player_tracks.wheel[i];
    for (unsigned int j = 1; j < wheel->count; ++j) {
      const TireTrackPair *old = tire_track_pair(&player_tracks, i, j - 1);
      const TireTrackPair *cur = tire_track_pair(&player_tracks, i, j);
      if (!old || !cur || cur->strip_start ||
          (old->vertex[0].alpha == 0.0f && cur->vertex[0].alpha == 0.0f)) continue;
      /* The texture repeats along V. Subtract the same integer per quad to
       * avoid losing fractional precision in long races; guard impossible jumps. */
      float base = floorf(old->vertex[0].v);
      float dv = cur->vertex[0].v - base;
      if (!isfinite(dv) || fabsf(dv) > 4096.0f) continue;
      render_vertex *q = &vertices[4 * n++];
      /* Quad indices 0,1,2,0,2,3 preserve the original strip's diagonal. */
      player_tracks_vertex(&q[0], &old->vertex[1], base);
      player_tracks_vertex(&q[1], &old->vertex[0], base);
      player_tracks_vertex(&q[2], &cur->vertex[0], base);
      player_tracks_vertex(&q[3], &cur->vertex[1], base);
    }
  }
  if (n) {
    render_blend_pass(0); /* render_tire_tracks' documented state baseline */
    render_tire_tracks(vp, vertices, n, track_texture, rp);
  }
}

/* clRaceThread::init turns off this display effect for a four-car Link race. */
static int race_tail_active(int movie) {
  if (movie || G.in_menu || G.paused || G.menu.finish || G.vs_closed || G.vs_wait ||
      G.car.race.over || G.car.race.state != CAR_RACE_RUN || G.car.race.play_state != 2) return 0;
  if (!G.vs_race) return 1;
  return G.vs_go.round && G.vs_go.n >= 2 && G.vs_go.n <= NET_PLAYERS && G.vs_go.n != 4 &&
         G.vs_go.pcb >= 0 && G.vs_go.pcb < G.vs_go.n && G.vs_id &&
         G.vs_go.player[G.vs_go.pcb].id == G.vs_id;
}
static const char *race_tail_pack(int pack) {
  return pack >= 0 && pack < CARDB_NPACKS ? CARDB_PACKS[pack] : NULL;
}
static void race_tail_tick(int movie) {
  if (!race_tail_active(movie)) { race_tail_reset(); return; }
  /* Original resets all histories when PLAY_VIEW changes. A new Link round
   * also invalidates every slot even if the same members or cars come back. */
  int new_link_round = G.vs_race &&
      (race_tail_scope.round != G.vs_go.round || race_tail_scope.config != G.vs_go.config ||
       race_tail_scope.membership != G.vs_go.membership || race_tail_scope.term != G.vs_go.term ||
       memcmp(race_tail_scope.incarnation.b, G.vs_go.incarnation.b, sizeof G.vs_go.incarnation.b));
  if (race_tail_scope.camera != G.camera || new_link_round) {
    race_tail_reset();
    race_tail_scope.camera = G.camera;
    if (G.vs_race) {
      race_tail_scope.incarnation = G.vs_go.incarnation;
      race_tail_scope.round = G.vs_go.round;
      race_tail_scope.config = G.vs_go.config;
      race_tail_scope.membership = G.vs_go.membership;
      race_tail_scope.term = G.vs_go.term;
    }
  }
  tail_trail_scene_tick(&race_tail_trails, 0, G.vs_race ? G.vs_id : 1, 1,
                        race_tail_pack(G.race_pack), (unsigned)G.aero_set, G.camera,
                        G.car.body, G.car.cam_view, G.car.cam_pos);
  int rivals_dressed = G.vs_race || app_ghost_arcade_dressed();
  for (int i = 0; i < CAR_RIVALS; ++i) {
    uint64_t id = (uint64_t)i + 2;
    int pack = G.rival_pack[i];
    int shown = i < G.n_rival && G.car.rival_shown[i] && G.rival_model[i];
    if (G.vs_race) {
      int pcb = i + (i >= G.vs_go.pcb);
      id = pcb < G.vs_go.n ? G.vs_go.player[pcb].id : 0;
      shown = shown && i < G.vs_race;
    } else if (G.n_ten) {
      int opponent = G.car.race.ten_rival;
      shown = shown && i == 0 && opponent >= 0 && opponent < G.n_ten && opponent < CAR_TEN_RIVALS;
      if (shown) {
        id = UINT64_C(0x100) + (unsigned)opponent;
        pack = G.ten_pack[opponent];
      }
    }
    int requested = rivals_dressed ? G.rival_dress[i].aero : 0;
    unsigned body = shown && requested && menu_aero(pack, requested) ? (unsigned)requested : 0;
    tail_trail_scene_tick(&race_tail_trails, (unsigned)i + 1, id, shown,
                          race_tail_pack(pack), body, G.camera, G.car.rival_body[i],
                          G.car.cam_view, G.car.cam_pos);
  }
}
static void race_tail_draw(const mat4 *projection, render_params *rp, int movie, int player_visible) {
  if (!race_tail_active(movie)) { race_tail_reset(); return; }
  if (race_tail_scope.camera != G.camera) return;
  TailTrailVertex vertices[2 * TAIL_TRAIL_MAX_VERTICES];
  for (int slot = 0; slot < TAIL_TRAIL_SCENE_CARS; ++slot) {
    if (!slot && (!player_visible || !G.race_model)) continue;
    if (slot && (!G.car.rival_shown[slot-1] || !G.rival_model[slot-1])) continue;
    const TailTrail *trail = &race_tail_trails.slot[slot].trail;
    size_t n = tail_trail_triangles(trail, 0, vertices, 2 * TAIL_TRAIL_MAX_VERTICES);
    n += tail_trail_triangles(trail, 1, vertices + n, 2 * TAIL_TRAIL_MAX_VERTICES - n);
    if (n) (void)render_tail_triangles(projection, vertices, n, rp);
  }
}
#endif

#ifndef __ANDROID__
void app_smoke_release(int context_lost) { (void)context_lost; }
#endif

static void backfire_open(const char *data_dir) {
  char bfx[4096], wpk[4096];
  backfire_reset();
#ifdef __ANDROID__
  extern int android_optional_resource_path(const char *, char *, size_t);
  if (!android_optional_resource_path("backfire.bfx", bfx, sizeof bfx) ||
      !android_optional_resource_path("backfire.wpk", wpk, sizeof wpk)) return;
#else
  char dir[4096];
  if (snprintf(dir, sizeof dir, "%s", data_dir) >= (int)sizeof dir) return;
  if (!backfire_path(bfx, sizeof bfx, dir, "backfire.bfx") ||
      !backfire_path(wpk, sizeof wpk, dir, "backfire.wpk") ||
      !backfire_child(dir, bfx) || !backfire_child(dir, wpk)) return;
#endif
  if (bfx_load(&backfire_asset, bfx) != 0) return;
  if (bfx_wpk_validate(wpk, &backfire_asset) != 0) { bfx_free(&backfire_asset); return; }
  backfire_scene.fd = -1;
  if (wpk_load(&backfire_scene, wpk) != 0) {
    bfx_free(&backfire_asset); wpk_free(&backfire_scene); return;
  }
  backfire_scene.two_sided = 1;
  backfire_ready = 1;
}

static void front_halo_open(const char *data_dir) {
  char atlas[4096], anchors[4096];
#ifdef __ANDROID__
  (void)data_dir;
  extern int android_optional_resource_path(const char *, char *, size_t);
  if (!android_optional_resource_path("front_halo.wpk", atlas, sizeof atlas) ||
      !android_optional_resource_path("front_halo.bin", anchors, sizeof anchors)) return;
#else
  if (!backfire_path(atlas, sizeof atlas, data_dir, "front_halo.wpk") ||
      !backfire_path(anchors, sizeof anchors, data_dir, "front_halo.bin")) return;
#endif
  lights_front_halo_load(atlas, anchors);
}
static int backfire_key(char *out, size_t cap, int pack, int aero) {
  int n;
  if (pack < 0 || pack >= NPACKS) return 0;
  if (pack >= CARDB_NPACKS) n = snprintf(out, cap, "chara/%s", RIVALDB_CHARA[pack-CARDB_NPACKS]);
  else if (aero >= 1 && aero <= 3) n = snprintf(out, cap, "cars/%s:aero_%c", CARDB_PACKS[pack], 'a'+aero-1);
  else n = snprintf(out, cap, "cars/%s", CARDB_PACKS[pack]);
  return n >= 0 && (size_t)n < cap;
}
static int backfire_rival_pack(int i) {
  int t = G.car.race.ten_rival;
  return i == 0 && G.n_ten && t >= 0 && t < G.n_ten ? G.ten_pack[t] : G.rival_pack[i];
}
static const story_body_view *backfire_body_view(int slot) {
  return slot ? &ASB.rival[slot - 1] : &ASB.own.view;
}
static void backfire_tick_car(int slot, int pack, int aero, const car_effect *e) {
  char key[BFX_NAME] = "";
  if (!e || !backfire_key(key, sizeof key, pack, aero)) key[0] = 0;
  if (strcmp(backfire_body[slot], key)) {
    memset(backfire_play.frame[slot], -1, sizeof backfire_play.frame[slot]);
    memset(backfire_play.type[slot], -1, sizeof backfire_play.type[slot]);
    memcpy(backfire_body[slot], key, strlen(key)+1);
  }
  const story_body_view *view = backfire_body_view(slot);
  int tuned = view->valid && (view->assembly.flags & STORY_ASSEMBLY_MUFFLER);
  bfx_step(&backfire_play, &backfire_asset, slot, key, tuned,
           e ? e->backfire_pulse : 0, e ? e->backfire_type : -1);
}
static void backfire_tick(void) {
  if (!backfire_ready) return;
  backfire_tick_car(0, G.race_pack, G.aero_set, &G.car.effect);
  for (int i = 0; i < CAR_RIVALS; ++i) {
    int pack = backfire_rival_pack(i);
    int aero = (G.vs_race || app_ghost_arcade_dressed()) ? G.rival_dress[i].aero : 0;
    if (aero && !menu_aero(pack, aero)) aero = 0;
    backfire_tick_car(i + 1, pack, aero,
                      G.car.rival_shown[i] ? &G.car.rival_effect[i] : NULL);
  }
}
/* Invert the complete affine mesh transform: animated effect matrices may scale. */
static int backfire_eye(const mat4 *m, const float *p, float *out) {
  const float *a = m->m;
  float x=p[0]-a[12], y=p[1]-a[13], z=p[2]-a[14];
  float c00=a[5]*a[10]-a[9]*a[6], c01=a[8]*a[6]-a[4]*a[10], c02=a[4]*a[9]-a[8]*a[5];
  float det=a[0]*c00+a[1]*c01+a[2]*c02;
  if (!isfinite(det) || fabsf(det)<1e-12f || fabsf(a[3])+fabsf(a[7])+fabsf(a[11])>1e-6f || fabsf(a[15]-1)>1e-6f) return 0;
  out[0]=(c00*x+c01*y+c02*z)/det;
  out[1]=((a[9]*a[2]-a[1]*a[10])*x+(a[0]*a[10]-a[8]*a[2])*y+(a[8]*a[1]-a[0]*a[9])*z)/det;
  out[2]=((a[1]*a[6]-a[5]*a[2])*x+(a[4]*a[2]-a[0]*a[6])*y+(a[0]*a[5]-a[4]*a[1])*z)/det;
  return isfinite(out[0]) && isfinite(out[1]) && isfinite(out[2]);
}
static void backfire_draw_car(int slot, const float *body, const mat4 *vp, const float *eye, render_params *rp) {
  mat4 car; memcpy(car.m, body, sizeof car.m);
  const story_body_view *view = backfire_body_view(slot);
  int pack = slot ? backfire_rival_pack(slot - 1) : G.race_pack;
  float y = view->valid ? view->body_y : story_body_height(pack, 0);
  /* The nozzle is attached to the visible exhaust. Apply the same local
   * body height as its mesh, without moving the physics posture. */
  for (int row = 0; row < 3; ++row) car.m[12 + row] += car.m[4 + row] * y;
  for (unsigned i=0; i<backfire_asset.nnozzle; ++i) {
    int frame=backfire_play.frame[slot][i], type=backfire_play.type[slot][i];
    const bfx_nozzle *noz=&backfire_asset.nozzle[i];
    int id=bfx_car_id(noz->car, backfire_body[slot]);
    if (frame<0 || frame>=BFX_FRAMES || (type!=0 && type!=1) || id<0) continue;
    const char *variant = bfx_variant_b(id) ? (type ? "MIDDLE_B" : "SMALL_B") : (type ? "MIDDLE_A" : "SAMLL_A");
    mat4 tr, scale=mat4_identity(); memcpy(tr.m,noz->matrix,sizeof tr.m);
    scale.m[0]=scale.m[5]=scale.m[10]=0.5f;
    mat4 base=mat4_mul(mat4_mul(car,tr),scale);
    for (unsigned j=0; j<backfire_asset.nmesh; ++j) {
      const bfx_mesh *mesh=&backfire_asset.mesh[j]; if (strcmp(mesh->variant,variant)) continue;
      mat4 anim; memcpy(anim.m,mesh->frame[frame],sizeof anim.m);
      mat4 model=mat4_mul(base,anim), mvp=mat4_mul(*vp,model); float local[3]; int finite=1;
      for (int k=0;k<16;++k) finite &= isfinite(model.m[k]) && isfinite(mvp.m[k]);
      for (int k=0;k<3;++k) finite &= isfinite(eye[k]);
      if (finite && backfire_eye(&model,eye,local))
        for (int pass=0; pass<WPK_PASSES; ++pass)
          wpk_draw_group(&backfire_scene,vp,&model,local,pass,rp,mesh->group);
    }
  }
}
static void backfire_draw(const mat4 *vp, const float *eye, int movie, const car_state *c) {
  if (!backfire_ready || movie) return;
  render_begin(&G.rp); render_blend_pass(1);
  render_params p=G.rp; p.range[0]=p.range[1]=p.range[2]=1e9f; p.object_visible=NULL; p.n_objects=0;
  if (G.camera==0) backfire_draw_car(0,c->body,vp,eye,&p);
  for (int i=0;i<CAR_RIVALS;++i) if (c->rival_shown[i] && G.rival_model[i])
    backfire_draw_car(i+1,c->rival_body[i],vp,eye,&p);
  G.rp.draws=p.draws; G.rp.triangles=p.triangles; G.rp.new_chunks=p.new_chunks;
  render_begin(&G.rp); render_blend_pass(1);
#ifndef WMMT_NATIVE_VK
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#endif
}


/* iOS 6 has no clock_gettime */
static double now_ms(void) {
#ifdef __APPLE__
  static mach_timebase_info_data_t tb;
  if (!tb.denom) mach_timebase_info(&tb);
  return (double)mach_absolute_time() * tb.numer / tb.denom * 1e-6;
#else
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) return -1.0;
  return (double)t.tv_sec * 1e3 + (double)t.tv_nsec * 1e-6;
#endif
}

/* the time a menu frame may take with its loading (the course, car models), from its start,
 * the GPU's part included (load_step); more on the race's title page, which is there for
 * the loading, and in the maker logos the app boots into, which cannot be skipped for it
 * (menu_booting): both then run at an even 30 fps. And the loading's least share, however
 * long the menu's own drawing took. */
#define LOAD_MS 12.0
#define LOAD_PRE_MS 24.0
#define LOAD_MIN_MS 3.0
/* the race's own share for first-drawing the course ahead (wpk_prewarm), and how far ahead */
#define WARM_MS 2.0
#define WARM_MARGIN 6000.0f

/* where each course's race starts: the camera's place at its first frame (car_start, the
 * same on both time zones' maps). The loading first-draws the map from there out. */
static const float START[CAR_COURSES][3] = {
  { 3047, 258, -27446 }, { 822, 124, 5482 }, { 35228, 18, 29159 },
  { 647, 124, 5496 }, { 35371, 18, 29427 }, { -38825, 52, 151331 },
  { -2988, 173, -11315 }, { 7821, 123, -7066 }, { -48658, 123, 1563 },
  { -16265, 103, -48750 }, { -4147, 53, 25205 }, { 10909, -77, 46167 },
};

/* the build, for telling the pushes apart in perf.log */
#define PORT_BUILD "push158"
#define PHONE_TRAFFIC_FAR 3000.0f /* an iPhone draws the traffic this near (0.1 m, as G.rp.range) */

/* the app's resident memory in MB (iOS 6 warns the app around 300 to 400 on the iPad 3) */
static double resident_mb(void) {
#ifdef __APPLE__
  struct task_basic_info info;
  mach_msg_type_number_t n = TASK_BASIC_INFO_COUNT;
  if (task_info(mach_task_self(), TASK_BASIC_INFO, (task_info_t)&info, &n) == KERN_SUCCESS)
    return (double)info.resident_size / 1048576.0;
#elif defined(__ANDROID__)
  FILE *f = fopen("/proc/self/statm", "r");
  long pages = 0, rss = 0;
  if (f) {
    if (fscanf(f, "%ld %ld", &pages, &rss) != 2) rss = 0;
    fclose(f);
  }
  return (double)rss * 4096.0 / 1048576.0;
#endif
  return 0;
}

/* 1.24 no-log: retain the governor without creating performance logs. */
static void perf_file(void) { }

/* how much of the course the menus left cold (wpk_prewarm) */
static int cold_chunks(void) {
  int cold = 0;
  for (uint32_t c = 0; G.track.warm && c < G.track.n_chunk; ++c) cold += !G.track.warm[c];
  return cold;
}

static void perf_open(void) {
  perf_file();
  if (G.perf)
    fprintf(G.perf, "--- race, course %d, zone %d, %d of %u chunks cold, title page %.1f s, %.0f MB resident (%s)\n",
            G.menu.course, G.track_zone, cold_chunks(), G.track.n_chunk, G.pre_frames / 60.0, resident_mb(), PORT_BUILD);
  G.pre_frames = 0;
  G.race_time = G.max_phys = G.max_render = 0;
  G.perf_frames = G.odd_steps = G.slow_frames = 0;
  G.race_frames = 0;
}

/* how much the overhead map takes over the player's car's environment where it has something */
#define OVER_AMOUNT 0.9f
/* the OPTION screen's FSR sharpening (RCAS's sharpness: 1 most, each stop down halves it) */
#define SHARP_AMOUNT 0.8f
/* after a race frame that missed its vsync the sharpening's pass (the GPU's to spare: some
 * 3 ms of the A5X's) sits out this many frames, so a heavy stretch of the road keeps 60 */
#define SHARP_REST 120

/* the parts of a race frame's render (G.seg) */
enum { SEG_SKY, SEG_OPAQUE, SEG_CUTOUT, SEG_BLEND, SEG_LIGHTS, SEG_WARM, SEG_BLUR, SEG_HUD, SEGS };

/* A line for each frame that missed its vsync or ran slow, and a summary every 10 s. The
 * slow ones say where the render's time went and how long the frame before waited for the
 * GPU in presentRenderbuffer. */
static void perf_frame(float dt, int steps, double phys, double render, int warmed, const render_params *rp) {
  G.race_time += dt;
  if (phys > G.max_phys) G.max_phys = phys;
  if (render > G.max_render) G.max_render = render;
  if (steps != 1) G.odd_steps++;
  int slow = dt > 1.5f / 60.0f || phys + render > 12.0;
  if (slow) G.slow_frames++;
  /* 1080p at 60 before any effect (Allan's): over 3 of 120 frames missing their vsync (a
   * chunk's first draw aside) gives up the next of render_hq's costs; 1200 frames without a
   * miss take one back, unless the level above missed again soon after its last return */
  if (G.console) {
    /* Quality recovery windows remain 60 Hz elapsed logic intervals, not
     * 120 Hz display counts. These adjust GPU cost, never the race's state. */
    int clock_steps = 1;
#ifdef __ANDROID__
    clock_steps = steps;
#endif
    if (dt > 1.25f / 60.0f && !rp->new_chunks && !warmed) G.gov_slow += clock_steps;
    if (G.gov_since_up) G.gov_since_up += clock_steps; /* (0: never went up) */
    int window = G.gov_slow ? 120 : 1200, level = G.gov_level;
    G.gov_frames += clock_steps;
    if (G.gov_frames >= window) {
      if (G.gov_slow > 3) {
        if (G.gov_since_up && G.gov_since_up < 1800) G.gov_floor = level + 1; /* (it went up too soon) */
        level++;
      } else if (!G.gov_slow && level > G.gov_floor) {
        level--, G.gov_since_up = 1;
      }
      G.gov_frames = G.gov_slow = 0;
    }
    if (level != G.gov_level) {
      G.gov_level = render_hq_level(level);
      if (G.perf) fprintf(G.perf, "%7.2fs render_hq level %d (floor %d)\n", G.race_time, G.gov_level, G.gov_floor);
    }
  }
  if (!G.perf) {
    G.perf_frames = G.odd_steps = G.slow_frames = G.sharp_rested = 0;
    G.max_phys = G.max_render = 0;
    return;
  }
  if (slow || rp->new_chunks || warmed)
    fprintf(G.perf,
            "%7.2fs dt %5.1f ms steps %d phys %5.2f ms draw %5.2f ms first drawn %d warmed %d draws %d tris %d pos %.0f %.0f"
            " kmh %.0f | present %.1f over %.1f/%d/%d bm %.1f/%d/%d sky %.1f opq %.1f cut %.1f bl %.1f lights %.1f warm %.1f blur %.1f hud %.1f\n",
            G.race_time, dt * 1e3f, steps, phys, render, rp->new_chunks, warmed, rp->draws, rp->triangles,
            G.car.pos[0], G.car.pos[2], car_kmh(&G.car), G.present_ms, G.over_ms, G.over_draws, G.over_tris, G.bm_ms, G.bm_draws, G.bm_tris, G.seg[SEG_SKY], G.seg[SEG_OPAQUE],
            G.seg[SEG_CUTOUT], G.seg[SEG_BLEND], G.seg[SEG_LIGHTS], G.seg[SEG_WARM], G.seg[SEG_BLUR], G.seg[SEG_HUD]);
  if (++G.perf_frames == 600) {
    char warm[256];
    wpk_warm_stats(warm, sizeof warm);
    fprintf(G.perf, "%7.2fs 600 frames: %d slow, %d not one step, max phys %.2f ms, max draw %.2f ms, %d unsharpened; %s\n",
            G.race_time, G.slow_frames, G.odd_steps, G.max_phys, G.max_render, G.sharp_rested, warm);
    fflush(G.perf);
    G.perf_frames = G.odd_steps = G.slow_frames = G.sharp_rested = 0;
    G.max_phys = G.max_render = 0;
  }
}

/* The menus' frame times, a line every 10 s: the screen, what is loaded, the frames that
 * missed their vsync and the longest, the menu frames' own time (cpu: their code and GL
 * calls) and the loading thread's steps and time, the app's memory. */
static void perf_menu(float dt, double cpu) {
  static int frames, slow, slow_movie;
  static float longest;
  static double cpu_sum, cpu_max, present_sum, present_max;
  frames++;
  /* the last frame's wait in presentRenderbuffer (the GPU's share) and slow frames under a movie */
  if (dt > 1.5f / 60.0f) slow++, slow_movie += app_movie() >= 0;
  if (dt > longest) longest = dt;
  cpu_sum += cpu;
  if (cpu > cpu_max) cpu_max = cpu;
  present_sum += G.present_ms;
  if (G.present_ms > present_max) present_max = G.present_ms;
  if (frames < 600) return;
  perf_file();
  int cars = 0, paints = 0;
  for (int k = 0; k < CARDB_NPACKS; ++k) {
    cars += G.seen.pack[k] == 1;
    paints += G.seen.paint[k] == 1;
  }
  pthread_mutex_lock(&G.load_mx);
  int units = G.load_units;
  double load_ms = G.load_ms;
  G.load_units = 0;
  G.load_ms = 0;
  pthread_mutex_unlock(&G.load_mx);
  if (G.perf) {
    char warm[256];
    wpk_warm_stats(warm, sizeof warm);
    fprintf(G.perf,
            "menu screen %d: course %s%s, %d of %u chunks cold, %d of %d car models, %d with paints (%s); 600 frames: %d slow, "
            "longest %.1f ms, %d under a movie; menu cpu %.1f avg %.1f max ms; present %.1f avg %.1f max ms; loading %d steps %.0f ms; %s; %.0f MB (%s)\n",
            G.menu.screen, G.seen.track == 2 ? "warm" : G.seen.track ? "up" : "loading",
            G.seen.start == G.menu.course + 1 ? " (start warm)" : "", cold_chunks(), G.track.n_chunk, cars, CARDB_NPACKS,
            paints, G.loader ? "loading thread" : "in the frames", slow, longest * 1e3f, slow_movie, cpu_sum / frames, cpu_max,
            present_sum / frames, present_max, units,
            load_ms, warm, resident_mb(), PORT_BUILD);
    fflush(G.perf);
  }
  frames = slow = slow_movie = 0;
  longest = 0;
  cpu_sum = cpu_max = present_sum = present_max = 0;
}

const char *app_error(void) { return G.error; }

/* the patched iOS SDK has no plain strcmp for armv7 */
/* (the junction table's Osaka and Hakone names keep their scene prefix, "yazirushi_all:") */
static int same_name(const char *a, const char *b) {
  for (const char *q = b; *q; ++q)
    if (*q == ':') b = q + 1;
  while (*a && *a == *b) a++, b++;
  return *a == *b;
}

static void load_pause(void);
static void track_set(int ready);

/* Make zone's map the one going up to GL, from the next load_unit on. The other's goes to
 * track_old, which the menu frames free a step at a time (its ten thousand buffers and
 * textures at once held the time zone select for a long moment); the new one waits for that,
 * as the iPad has no room for both. */
/* data_dir/<kind>[_<city>][_night].<ext>: Tokyo's files have no city in their names but its
 * map's (tokyo.wpk) */
static void city_path(char *out, size_t n, const char *kind, int city, int zone, const char *ext) {
  snprintf(out, n, "%s/%s%s%s%s.%s", G.data_dir, kind, city && *kind ? "_" : "", city || !*kind ? CITY_FILE[city] : "",
           zone ? "_night" : "", ext);
  /* the OPTION screen's HD TEXTURES (Android): a map's pack AI-upscaled into ASTC
   * (upscale_tools, render.c astc_upload) where there is one, <name>.astc.wpk */
  size_t len = strlen(out);
  if (G.hd_maps && same_name(ext, "wpk") && len > 4 && len + 5 < n) {
    char hd[1200];
    snprintf(hd, sizeof hd, "%.*s.astc.wpk", (int)(len - 4), out);
    if (access(hd, F_OK) == 0) snprintf(out, n, "%s", hd);
  }
}

/* A city's sky boxes, arrow boards (with their names, the scene file's prefix "...:" left
 * out), lights and minimap, those of the other city freed (small: a step at once) */
static void extras_open(int city) {
  char path[1200];
  if (city == G.extras_city) return;
  G.extras_city = city;
  for (int z = 0; z < 2; ++z) {
    wpk_free(&G.sky[z]);
    wpk_free(&G.arrows[z]);
    memset(&G.sky[z], 0, sizeof G.sky[z]);
    memset(&G.arrows[z], 0, sizeof G.arrows[z]);
    city_path(path, sizeof path, "sky", city, z, "wpk");
    if (wpk_load(&G.sky[z], path) == 0) G.sky[z].two_sided = G.sky[z].solid = 1;
    else fprintf(stderr, "no %s, no sky\n", path);
    /* Hakone's morning dome is only the sun's glow: black where its alpha is 0 (all but the
     * glow), over the sky's colour (the clear, the fog's) blended, not drawn black */
    wpk_blend_texture(&G.sky[z], "hk_sky01_a.tga");
    city_path(path, sizeof path, "arrows", city, z, "wpk");
#ifdef __ANDROID__
    int arrows_status = wpk_load_course_arrows(&G.arrows[z], path);
#else
    int arrows_status = wpk_load(&G.arrows[z], path);
#endif
    if (arrows_status != 0) fprintf(stderr, "no %s, no junction arrow boards\n", path);
  }
  /* the junction table's flags are by board index: a city's own (another city's left the
   * boards of the same indices hidden but at their junctions, push87) */
  G.n_arrows = 0;
  memset(G.arrow_switched, 0, sizeof G.arrow_switched);
  G.arrow_table_ready = 0;
  G.hk_arrow = 0;
  city_path(path, sizeof path, "arrows", city, 0, "names");
  FILE *f = fopen(path, "r");
  char name[256];
  while (f && G.n_arrows < MAX_ARROWS && fscanf(f, "%255s", name) == 1) {
    const char *p = name;
    for (const char *q = name; *q; ++q)
      if (*q == ':') p = q + 1;
    snprintf(G.arrow_names[G.n_arrows++], sizeof G.arrow_names[0], "%s", p);
  }
  if (f) fclose(f);
  city_path(path, sizeof path, "lights", city, 0, "bin");
  if (lights_points(path) != 0) fprintf(stderr, "no %s, no street lights\n", path);
  hud_set_city(city);
}

static int track_open(int city, int zone) {
  char path[1200];
  load_pause();
  if (G.track_old.n_batch || G.track_old.n_tex) wpk_free(&G.track_old); /* a third switch in a row */
  G.track_old = G.track;
  memset(&G.track, 0, sizeof G.track);
  track_set(0);
  G.track_city = city;
  G.track_zone = zone;
  G.hd_reload = 0;
  extras_open(city);
  city_path(path, sizeof path, "", city, zone, "wpk");
  return wpk_open(&G.track, path);
}

/* GL objects of track_old freed a menu frame */
#define TRACK_FREE_STEP 1500
/* frames the time zone card stays at rest before its map starts loading (a quick look at the
 * other card and back costs nothing) */
#define ZONE_REST 40

/* ---- the player's best time on each course, kept in data_dir/records (a player with a
 * card, as the arcade has it): the console's YOUR RECORD (the card's
 * clV386CardData::getTimeAttack) and RECORD TIME (the machine's course record,
 * clTimeAttackRankingDataManager::getCourseRecord, 0 while no run has set one). On the iPad
 * the player is the machine's only one, so both are that best, 0 (dashes) until the course's
 * first goal. The attract loop's ranking still shows its fresh top ten at 9'59"999 (menu.c),
 * which a run places behind when it is slower. ---- */
#define RANKING_TOP_MS 599999

/* Keep the legacy total and car rows first. Optional split rows record the
 * cumulative times of the same personal-best run, ending at its total. */
static int records_splits_valid(int count, const float *at, int ms) {
  if (count < 2 || count > CAR_SECTIONS || ms <= 0 || at[0] != 0.0f) return 0;
  for (int i = 1; i <= count; ++i)
    if (!isfinite(at[i]) || at[i] <= at[i - 1]) return 0;
  float total = at[count] * 1000.0f;
  return total < (float)INT_MAX && (int)total == ms;
}

static void records_load(void) {
  char path[1100];
  snprintf(path, sizeof path, "%s/records%d", G.save_dir, G.menu.save_slot);
  FILE *f = G.menu.save_slot ? fopen(path, "r") : NULL;
  for (int i = 0; i < CAR_COURSES; ++i)
    if (!f || fscanf(f, "%d", &G.best_ms[i]) != 1 || G.best_ms[i] < 0) G.best_ms[i] = 0;
  memset(G.best_splits, 0, sizeof G.best_splits);
  G.n_car_best = 0;
  char line[256];
  while (f && fgets(line, sizeof line, f)) {
    int course, pack, ms, count, offset = 0;
    if (sscanf(line, " car %9d %9d %9d", &course, &pack, &ms) == 3 &&
        course >= 0 && course < CAR_COURSES && ms > 0 && G.n_car_best < CAR_BEST_MAX) {
      G.car_best[G.n_car_best].course = course;
      G.car_best[G.n_car_best].pack = pack;
      G.car_best[G.n_car_best++].ms = ms;
    } else if (sscanf(line, " split %3d %9d %2d%n", &course, &ms, &count, &offset) == 3 &&
               course >= 0 && course < CAR_COURSES && ms == G.best_ms[course] &&
               count >= 2 && count <= CAR_SECTIONS) {
      float at[CAR_SECTIONS + 1] = {0};
      char *p = line + offset;
      for (int i = 1; i <= count; ++i) {
        char *end;
        at[i] = strtof(p, &end);
        p = end;
      }
      if (p[strspn(p, " \t\r\n")] == '\0' && records_splits_valid(count, at, ms)) {
        G.best_splits[course].count = count;
        memcpy(G.best_splits[course].at, at, sizeof at);
      }
    }
  }
  if (f) fclose(f);
}

static void records_save(void) {
  char path[1100];
  if (!G.menu.save_slot) return;
  snprintf(path, sizeof path, "%s/records%d", G.save_dir, G.menu.save_slot);
  char tmp[sizeof path + 8];
  snprintf(tmp, sizeof tmp, "%s.XXXXXX", path);
  int fd = mkstemp(tmp);
  if (fd < 0) return;
  FILE *f = fdopen(fd, "w");
  if (!f) { close(fd); unlink(tmp); return; }
  for (int i = 0; i < CAR_COURSES; ++i) fprintf(f, "%d%c", G.best_ms[i], i + 1 < CAR_COURSES ? ' ' : '\n');
  for (int i = 0; i < G.n_car_best; ++i) fprintf(f, "car %d %d %d\n", G.car_best[i].course, G.car_best[i].pack, G.car_best[i].ms);
  for (int course = 0; course < CAR_COURSES; ++course) {
    int count = G.best_splits[course].count;
    if (!count) continue;
    fprintf(f, "split %d %d %d", course, G.best_ms[course], count);
    for (int i = 1; i <= count; ++i) fprintf(f, " %.9g", G.best_splits[course].at[i]);
    fputc('\n', f);
  }
  int ok = !ferror(f);
  if (fclose(f) != 0) ok = 0;
  if (!ok || rename(tmp, path) != 0) unlink(tmp);
}

int app_model_ta_best_ms(int pack, int course) {
  if (pack < 0 || course < 0 || course >= CAR_COURSES || !G.menu.save_slot) return 0;
  int best = 0;
  for (int k = 0; k < G.n_car_best && k < CAR_BEST_MAX; ++k) {
    int ms = G.car_best[k].ms;
    if (G.car_best[k].pack == pack && G.car_best[k].course == course && ms > 0 && (!best || ms < best)) best = ms;
  }
  return best;
}

static void records_show(int course) {
  float best = (float)G.best_ms[course] * 0.001f;
  hud_set_records(best, best);
  hud_set_record_splits(G.best_splits[course].count, G.best_splits[course].at);
}

/* A run reached the goal: clTaResult's figures (the records as they stand after it), and a
 * new best kept. The course's record is the player's best, as on the console; the run's
 * place counts the ranking's fresh top ten (all 9'59"999, menu.c) too. */
static void records_goal(int course, const car_race *race, menu_result *res, int keep) {
  int ms = (int)(race->total * 1000.0f); /* as nsTaData::setTime7 shows it */
  if (ms <= 0) ms = 1;
  int best = G.best_ms[course];
  int k = 0;
  while (k < G.n_car_best && (G.car_best[k].course != course || G.car_best[k].pack != G.race_pack)) k++;
  int car = k < G.n_car_best ? G.car_best[k].ms : 0;
  memset(res, 0, sizeof *res);
  res->new_course = !best || ms < best;
  res->new_car = !car || ms < car;
  res->new_personal = !best || ms < best;
  /* (the run's own time as it is, the kept ones a hair over their ms so they show as such) */
  res->course_record = res->new_course ? race->total : ((float)best + 0.5f) * 0.001f;
  res->car_record = res->new_car ? race->total : ((float)car + 0.5f) * 0.001f;
  res->personal = res->new_personal ? race->total : ((float)best + 0.5f) * 0.001f;
  /* the sections the course has (menu_g_finish_ta_section_1 shows four) */
  for (int i = 0; i < race->sections && i < MENU_SECTIONS; ++i)
    res->section[i] = (i + 1 < race->sections ? race->split[i + 1] : race->total) - race->split[i];
  res->total = race->total;
  res->top_speed = (int)G.top_kmh;
  /* its place: behind the player's best if that is faster, behind the default ten past 9'59"999 */
  res->rank = 1 + (best && best < ms) + (ms > RANKING_TOP_MS ? 10 : 0);
  if (!keep) {
    res->new_course = res->new_car = res->new_personal = 0;
    res->course_record = res->personal = best ? ((float)best + 0.5f) * 0.001f : 0.0f;
    res->car_record = car ? ((float)car + 0.5f) * 0.001f : 0.0f;
    return;
  }
  int have_splits = records_splits_valid(race->sections, race->split, ms);
  int save_splits = have_splits &&
    (res->new_personal || (ms == best && !G.best_splits[course].count));
  if (res->new_personal) {
    G.best_ms[course] = ms;
    G.best_splits[course].count = 0; /* never compare with the old, slower PB */
  }
  if (save_splits) {
    G.best_splits[course].count = race->sections;
    memcpy(G.best_splits[course].at, race->split, sizeof G.best_splits[course].at);
  }
  if (res->new_car) {
    if (k == G.n_car_best && k < CAR_BEST_MAX) {
      G.car_best[k].course = course;
      G.car_best[k].pack = G.race_pack;
      G.n_car_best++;
    }
    if (k < G.n_car_best) G.car_best[k].ms = ms;
  }
  if (res->new_personal || res->new_car || save_splits) records_save();
}

/* ---- the titles (clWorkSpace::judgeTitle, src/title.h): the card as its getters read it,
 * taken as the race starts and again once its results are in; the race's new titles go to
 * the title select on the way back (menu_title_due) ---- */
static double title_odo(void) {
  return G.menu.own_sel >= 0 && G.menu.own_sel < G.menu.n_own ? G.menu.own[G.menu.own_sel].odo : 0.0;
}


static void title_card_now(title_card *c) {
  const menu_state *m = &G.menu;
  int mk = m->maker, car = m->car;
  memset(c, 0, sizeof *c);
  c->power = m->st_power[mk][car];
  c->handling = m->st_handling[mk][car];
  c->st_div = m->st_div;
  c->st_bits = m->st_bits;
  int bits = 0;
  for (int i = 0; i < 20; ++i) bits += m->st_bits >> i & 1;
  c->st_wins = 20 * m->st_div + bits; /* getStoryClearCount: the episodes cleared */
  c->st_streak = m->st_streak_car[mk][car];
  for (int k = 0; k < G.n_car_best; ++k) {
    int slot = car_course_ta_slot(G.car_best[k].course);
    if (G.car_best[k].pack == G.race_pack && slot >= 0) c->ta_ms[slot] = G.car_best[k].ms;
  }
  memcpy(c->ten, m->ten_result, sizeof c->ten);
  c->vs_wins = m->vs_wins_car[mk][car];
}

/* the race over (its results on the card): judge it, the new titles due */
static void title_race_over(int mode, int won, const car_race *race, int course, int ta_top) {
  menu_state *m = &G.menu;
  title_play p;
  memset(&p, 0, sizeof p);
  p.mode = mode;
  p.model = title_model(m->maker, m->car, m->color);
  p.odo_m = title_odo();
  p.race_m = p.odo_m - G.title_odo0;
  time_t now = time(NULL);
  struct tm tm = *localtime(&now);
  p.year = tm.tm_year + 1900, p.month = tm.tm_mon + 1, p.day = tm.tm_mday;
  p.hour = tm.tm_hour, p.minute = tm.tm_min, p.second = tm.tm_sec;
  p.name = m->name;
  p.plays = m->plays++;
  p.won = won;
  p.pre = G.title_pre;
  title_card_now(&p.now);
  p.story_sel = m->story_sel;
  p.ta_slot = car_course_ta_slot(course);
  p.ta_time = race->total;
  p.ta_top = ta_top;
  p.ten_course = menu_ten_course(m);
  p.ten_level = m->ten_level;
  if (mode == TITLE_VS)
    for (int k = 0; k < m->vs.match_n && k < MENU_VS_PLAYERS; ++k) {
      if (k == m->vs.match_me || p.vs_n >= 3) continue;
      p.vs_model[p.vs_n++] = title_model(m->vs.match[k].maker, m->vs.match[k].car, m->vs.match[k].color);
    }
  p.log = race->title_log_on ? race->title_log : NULL;
  int got[3];
  int n = title_judge(&p, menu_title(m), got);
  fprintf(stderr, "titles: mode %d, %d new (%d %d %d)\n", mode, n, got[0], got[1], got[2]);
  menu_title_due(m, got);
}

/* ---- save_dir/garage<n> (save n's): the car setting screen's choices (menu_state), a line "gearbox <0 AT,
 * 1 MT>", then "tune <0 stock, 1 full> <full tune's power> <car>" for each car of the car
 * select (by its label, src/cardb.h), and "sttune <power> <handling> <gauge> <car>", the
 * story's tune and points; "own <colour> <registered (time_t)> <mileage (m)> <car>" for each
 * of the save's cars, with "cstory <divisions> <episode bits> <car>", "cten <course>
 * <medal of each level> <car>", "cclass <class 0..46> <car>" and "ctitle <title> <story wins in
 * a row> <versus wins> <car>", its story and 10-in-a-row
 * results and class (a garage from before the
 * cars kept them once, as "story_div", "story_bits" and "ten <course> <medals>") ---- */
static int car_by_label(const char *label, int *maker, int *car) {
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      if (same_name(CARDB_CARS[mk][c].label, label)) {
        *maker = mk, *car = c;
        return 1;
      }
  return 0;
}

/* A garage from before the cars: its cars are those tuned or dressed up (in their first
 * colour), the one dressed up most (else the first) taking the story and 10-in-a-row
 * results it kept for all of them. */
static void garage_adopt_cars(int legacy) {
  int best = -1, best_score = -1;
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c) {
      const menu_state *m = &G.menu;
      int used = m->tune_full[mk][c] || m->st_power[mk][c] || m->st_handling[mk][c] || m->st_gauge[mk][c] ||
                 m->dress_lv[mk][c] || m->aero[mk][c] || m->mirror[mk][c] || m->wing[mk][c] || m->bonnet[mk][c] ||
                 m->wheel[mk][c] || m->neon[mk][c] || m->vinyl[mk][c];
      if (!used || G.menu.n_own >= MENU_OWN_MAX) continue;
      int score = 4 * m->dress_lv[mk][c] + m->st_power[mk][c] + m->st_handling[mk][c] + m->st_gauge[mk][c];
      if (score > best_score) best_score = score, best = G.menu.n_own;
      G.menu.own[G.menu.n_own++] = (menu_own){ (signed char)mk, (signed char)c, 0, (long long)time(NULL), 0 };
    }
  if (best >= 0 && legacy) {
    int mk = G.menu.own[best].maker, c = G.menu.own[best].car;
    G.menu.st_div_car[mk][c] = G.menu.st_div;
    G.menu.st_bits_car[mk][c] = G.menu.st_bits;
    memcpy(G.menu.ten_car[mk][c], G.menu.ten_result, sizeof G.menu.ten_result);
  }
  fprintf(stderr, "garage from before the cars: %d cars\n", G.menu.n_own);
}

/* The OPTION screen's choices (the SAVE DATA screen's gear key too, before any save is
 * chosen): save_dir/option, the same for every save; a save's garage keeps them only for a
 * port from before (Allan, 10-24). */
/* save_dir/option's value k (0..12, as options_save writes them), or def: what render_hq
 * (the ANTI-ALIASING) and the first map (the HD TEXTURES) take before the menus have the
 * screen's options */
static int options_peek(int k, int def) {
  char path[1100];
  snprintf(path, sizeof path, "%s/option", G.save_dir);
  FILE *f = fopen(path, "r");
  int v[13], n = f ? fscanf(f, "option %d %d %d %d %d %d %d %d %d %d %d %d %d", &v[0], &v[1], &v[2], &v[3], &v[4],
                            &v[5], &v[6], &v[7], &v[8], &v[9], &v[10], &v[11], &v[12]) : 0;
  if (f) fclose(f);
  return n > k ? v[k] : def;
}

/* The OPTION screen's graphics switches to the renderer (Android, render_hq on): the bloom,
 * the SSAO (its targets made the first time it is on), the last frame's reflections (the
 * paint's, the wet road's), the maps' HD packs (the map and its extras opened again at the
 * next menu frame); the wet road's strength is the race's (G.rp.wet) */
static void hq_apply(void) {
  if (!G.hq_on) return;
  /* The enhanced-lighting switch was removed (it broke some cars' rendering): always off. */
  int enhanced = 0;
  /* Preserve each user's explicit options; the preset only refines active effects. */
  int bloom = G.menu.bloom_on, ssao = G.menu.ssao_on;
  int env = (G.menu.paint_on ? 1 : 0) | (G.menu.wet_on ? 2 : 0);
  render_enhance(enhanced);
  if (ssao && !G.hq_ssao_made) render_ssao(1.0f), G.hq_ssao_made = 1;
  if (bloom != G.hq_bloom || ssao != G.hq_ssao || env != G.hq_env) {
    render_hq_options(bloom, ssao, env & 1, env >> 1);
    G.hq_bloom = bloom, G.hq_ssao = ssao, G.hq_env = env;
  }
  if (G.menu.hd_tex != G.hd_maps) {
    G.hd_maps = G.menu.hd_tex;
    G.hd_reload = 1, G.extras_city = -1; /* (menu_frame opens them again) */
  }
}

/* Independent layout file. Never replace a malformed file except after an explicit edit. */
static int key_layout_parse(const char *s, int legacy, int v[9]) {
  const char *prefix = legacy ? "keys" : "key_layout";
  size_t n = strlen(prefix);
  if (strncmp(s, prefix, n) || (s[n] != ' ' && s[n] != '\t')) return 0;
  s += n;
  int count = legacy ? 9 : 10;
  for (int i = 0; i < count; ++i) {
    while (*s == ' ' || *s == '\t') ++s;
    if (!*s || *s == '\n' || *s == '\r') return 0;
    errno = 0; char *end; long x = strtol(s, &end, 10);
    if (end == s || errno == ERANGE || (*end && *end != ' ' && *end != '\t' && *end != '\r' && *end != '\n')) return 0;
    if (!legacy && i == 0) { if (x != 1) return 0; }
    else {
      int j = i - !legacy;
      if (j % 3 == 0 ? (x < 60 || x > 160) : (x < -2000 || x > 2000)) return 0;
      v[j] = (int)x;
    }
    s = end;
  }
  while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n') ++s;
  return !*s;
}
static int key_layout_load(void) {
  char path[1100], line[512]; int v[9], legacy = 0, loaded = 0;
  if (snprintf(path, sizeof path, "%s/key_layout", G.save_dir) >= (int)sizeof path) return 0;
  FILE *f = fopen(path, "r");
  if (!f) {
    if (errno != ENOENT) return 0;
    if (snprintf(path, sizeof path, "%s/option", G.save_dir) >= (int)sizeof path) return 0;
    f = fopen(path, "r"); if (!f) return 0;
    legacy = 1;
    if (!fgets(line, sizeof line, f) || !strchr(line, '\n')) { fclose(f); return 0; }
  }
  if (fgets(line, sizeof line, f) && strchr(line, '\n') && key_layout_parse(line, legacy, v) &&
      (legacy || fgetc(f) == EOF)) {
    for (int i = 0; i < 3; ++i) {
      G.menu.key_k[i] = G.menu.key_base_k[i] = v[3*i];
      G.menu.key_dx[i] = G.menu.key_base_dx[i] = v[3*i+1];
      G.menu.key_dy[i] = G.menu.key_base_dy[i] = v[3*i+2];
    }
    loaded = 1;
  }
  fclose(f);
  return loaded;
}
static void key_layout_clamp_visible(void) {
  for (int g = 0; g < HUD_KEY_GROUPS; ++g) {
    float x = G.menu.key_dx[g], y = G.menu.key_dy[g];
    hud_layout_clamp_mode(g, G.menu.gyro, G.menu.key_k[g] * 0.01f, &x, &y);
    G.menu.key_dx[g] = (int)floorf(x + 0.5f);
    G.menu.key_dy[g] = (int)floorf(y + 0.5f);
  }
}
#ifdef __ANDROID__
/* Clamp validated sidecar coordinates to the current device geometry in memory only.
 * Keep the persisted choice unchanged until the user explicitly edits it. */
static void custom_layout_clamp_visible(HudCustomLayout *layout, int mode) {
  HudCustomTransform *items[HUD_RACE_GROUPS] = { &layout->map, &layout->rank, &layout->timer, &layout->meter };
  _Static_assert(HUD_EDIT_GROUPS - HUD_EDIT_SHIFT_UP == HUD_CUSTOM_BUTTONS, "layout controls match saved slots");
  for (int g = 0; g < HUD_RACE_GROUPS + 1 + HUD_CUSTOM_BUTTONS; ++g) {
    const int is_key = g >= HUD_RACE_GROUPS;
    const int group = is_key ? HUD_EDIT_SHIFT + g - HUD_RACE_GROUPS : g;
    HudCustomTransform *t;
    if (!is_key) t = items[g];
    else if (group == HUD_EDIT_SHIFT) {
      if (!layout->shift_separate) continue;
      t = &layout->shift;
    } else {
      int i = group - HUD_EDIT_SHIFT_UP;
      if (!(layout->separate_buttons & (1u << i))) continue;
      t = &layout->button[i];
    }
    if (!is_key && t->k==100 && !t->dx && !t->dy) continue;
    if (!is_key) {
      float max_k = hud_race_layout_max_scale(group);
      if (isfinite(max_k) && max_k >= HUD_KEY_K_MIN && t->k * 0.01f > max_k) {
        int max_percent = (int)floorf(max_k * 100.0f + 0.0001f);
        t->k = max_percent < 60 ? 60 : max_percent;
      }
    }
    float x = (float)t->dx, y = (float)t->dy, k = t->k * 0.01f;
    if (is_key) hud_layout_clamp_mode(group, mode, k, &x, &y);
    else hud_race_layout_clamp(group, k, &x, &y);
    /* Defend the integer conversion even if a backend returns nonfinite values. */
    if (!isfinite(x)) x = 0;
    if (!isfinite(y)) y = 0;
    x = fmaxf(-2000.0f, fminf(2000.0f, x));
    y = fmaxf(-2000.0f, fminf(2000.0f, y));
    float ix = floorf(x + 0.5f), iy = floorf(y + 0.5f), cx = ix, cy = iy;
    /* Rounding must not put a fractional clamp boundary back off screen. */
    if (is_key) hud_layout_clamp_mode(group, mode, k, &cx, &cy);
    else hud_race_layout_clamp(group, k, &cx, &cy);
    if (isfinite(cx)) ix = cx < ix ? floorf(cx) : cx > ix ? ceilf(cx) : ix;
    if (isfinite(cy)) iy = cy < iy ? floorf(cy) : cy > iy ? ceilf(cy) : iy;
    t->dx = (int)fmaxf(-2000.0f, fminf(2000.0f, ix));
    t->dy = (int)fmaxf(-2000.0f, fminf(2000.0f, iy));
  }
}
/* Merge only user-edited groups; unedited coordinates remain device-independent. */
static HudCustomLayout custom_layout_merge(HudCustomLayout base, const HudCustomLayout *view, unsigned mask) {
  if (mask & CUSTOM_DIRTY_DEADZONE) base.stick_deadzone_percent=view->stick_deadzone_percent;
  if (mask & CUSTOM_DIRTY_SHIFT) { base.shift_separate=view->shift_separate; base.shift=view->shift; }
  if (mask & CUSTOM_DIRTY_MAP) base.map=view->map;
  if (mask & CUSTOM_DIRTY_RANK) base.rank=view->rank;
  if (mask & CUSTOM_DIRTY_TIME) base.timer=view->timer;
  if (mask & CUSTOM_DIRTY_METER) base.meter=view->meter;
  if (mask & CUSTOM_DIRTY_OPACITY) base.button_opacity_percent=view->button_opacity_percent;
  for (int i=0; i<HUD_CUSTOM_BUTTONS; ++i) if (mask & (CUSTOM_DIRTY_BUTTON_0 << i)) {
    unsigned bit = 1u << i;
    base.separate_buttons = (base.separate_buttons & ~bit) | (view->separate_buttons & bit);
    base.button[i] = view->button[i];
  }
  return base;
}
#endif
static int key_layout_save(void) {
  char path[1100], tmp[1100];
  if (snprintf(path, sizeof path, "%s/key_layout", G.save_dir) >= (int)sizeof path ||
      snprintf(tmp, sizeof tmp, "%s/key_layout.tmp.XXXXXX", G.save_dir) >= (int)sizeof tmp) return 0;
  int fd = mkstemp(tmp); if (fd < 0) return 0;
  FILE *f = fdopen(fd, "w"); if (!f) { close(fd); unlink(tmp); return 0; }
  unsigned mask = G.menu.key_layout_dirty;
  int k[3], x[3], y[3];
  for (int g=0; g<3; ++g) {
    k[g] = mask & (1u<<g) ? G.menu.key_k[g] : G.menu.key_base_k[g];
    x[g] = mask & (1u<<g) ? G.menu.key_dx[g] : G.menu.key_base_dx[g];
    y[g] = mask & (1u<<g) ? G.menu.key_dy[g] : G.menu.key_base_dy[g];
  }
  int ok = fprintf(f, "key_layout 1 %d %d %d %d %d %d %d %d %d\n",
      k[0], x[0], y[0], k[1], x[1], y[1], k[2], x[2], y[2]) > 0;
  if (fflush(f) != 0) ok = 0;
  if (fsync(fd) != 0) ok = 0;
  if (fclose(f) != 0) ok = 0;
  if (ok && rename(tmp, path) != 0) ok = 0;
  if (!ok) unlink(tmp);
  else {
    for (int g=0; g<3; ++g) G.menu.key_base_k[g]=k[g], G.menu.key_base_dx[g]=x[g], G.menu.key_base_dy[g]=y[g];
    G.menu.key_layout_dirty &= ~mask;
  }
  return ok;
}

static int options_load(void) {
  char path[1100];
  snprintf(path, sizeof path, "%s/option", G.save_dir);
  FILE *f = fopen(path, "r");
  if (!f) return 0;
  int a, b, c, d = 1, e = 0, ao = 1, bm = 1, hq[6] = { 1, 1, 0, 1, 1, 1 }, hires = 0;
  int test = 0, traffic = 0, frame_rate = 0;
  char line[512];
  int n = fgets(line, sizeof line, f) ?
    sscanf(line, "option %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d", &a, &b, &c, &d, &e, &ao, &bm,
           &hq[0], &hq[1], &hq[2], &hq[3], &hq[4], &hq[5], &hires, &test, &traffic, &frame_rate) : 0;
  fclose(f);
  if (n < 3) return 0;
  G.menu.story_test = test >= 0 && test <= 10 ? test : 0;
  G.menu.ta_traffic = traffic != 0;
  G.menu.frame_rate_limit = timing60_frame_limit(frame_rate);
  G.menu.hires = hires != 0;
  G.menu.hd_tex = hq[0] != 0, G.menu.bloom_on = hq[1] != 0, G.menu.ssao_on = hq[2] != 0;
  G.menu.wet_on = hq[3] != 0, G.menu.paint_on = hq[4] != 0, G.menu.aa4 = hq[5] != 0;
  G.menu.gyro = menu_steer_valid(a);
  G.menu.gyro_sens = b >= 1 && b <= 10 ? b : 5;
  G.menu.over_on = c != 0;
  G.menu.sharp_on = d != 0;
  G.menu.pedal_slide = e != 0;
  G.menu.ao_on = ao != 0;
  G.menu.bm_on = bm != 0;
  return 1;
}

static int options_save(void) {
  static int last[17] = { -1 };
  int now[17] = { G.menu.gyro, G.menu.gyro_sens, G.menu.over_on, G.menu.sharp_on, G.menu.pedal_slide, G.menu.ao_on,
                  G.menu.bm_on, G.menu.hd_tex, G.menu.bloom_on, G.menu.ssao_on, G.menu.wet_on, G.menu.paint_on,
                  G.menu.aa4, G.menu.hires, G.menu.story_test, G.menu.ta_traffic, G.menu.frame_rate_limit };
  if (G.options_global && !memcmp(now, last, sizeof now)) return 1;
  char path[1100], tmp[1100];
  if (snprintf(path, sizeof path, "%s/option", G.save_dir) >= (int)sizeof path ||
      snprintf(tmp, sizeof tmp, "%s/option.tmp.XXXXXX", G.save_dir) >= (int)sizeof tmp) return 0;
  enum { OPTION_FILE_MAX = 65536 };
  char *bytes = malloc(OPTION_FILE_MAX + 1), *tail = NULL;
  size_t tail_n = 0;
  if (!bytes) return 0;
  FILE *old = fopen(path, "rb");
  if (old) {
    size_t n = fread(bytes, 1, OPTION_FILE_MAX + 1, old);
    int bad = ferror(old) || n > OPTION_FILE_MAX;
    if (fclose(old) != 0) bad = 1;
    if (bad) { free(bytes); return 0; }
    char *newline = memchr(bytes, '\n', n);
    if (newline) { tail = newline + 1; tail_n = n - (size_t)(tail - bytes); }
  } else if (errno != ENOENT) { free(bytes); return 0; }
  int fd = mkstemp(tmp);
  if (fd < 0) { free(bytes); return 0; }
  FILE *f = fdopen(fd, "w");
  if (!f) { close(fd); unlink(tmp); free(bytes); return 0; }
  int ok = fprintf(f, "option %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d %d\n", now[0], now[1], now[2], now[3], now[4], now[5], now[6],
          now[7], now[8], now[9], now[10], now[11], now[12], now[13], now[14], now[15], now[16]) > 0;
  if (tail_n && fwrite(tail, 1, tail_n, f) != tail_n) ok = 0;
  free(bytes);
  if (fflush(f) != 0) ok = 0;
  if (fsync(fd) != 0) ok = 0;
  if (fclose(f) != 0) ok = 0;
  if (ok && rename(tmp, path) != 0) ok = 0;
  if (!ok) { unlink(tmp); return 0; }
  memcpy(last, now, sizeof last);
  G.options_global = 1;
  return 1;
}

int app_frame_rate_limit(void) { return G.menu.frame_rate_limit; }

/* a garage's "name" line into name (left as it is for another line) */
static void name_read(const char *line, short name[5]) {
  int c[5];
  if (sscanf(line, "name %d %d %d %d %d", &c[0], &c[1], &c[2], &c[3], &c[4]) != 5) return;
  for (int i = 0, end = 0; i < 5; ++i) {
    end |= c[i] < 0 || c[i] >= 256;
    name[i] = (short)(end ? -1 : c[i]);
  }
}

static void garage_load(void) {
  char path[1100], line[256], label[200];
  snprintf(path, sizeof path, "%s/garage%d", G.save_dir, G.menu.save_slot);
  FILE *f = G.menu.save_slot ? fopen(path, "r") : NULL;
  if (!f) return;
  int a, b, legacy = 0;
  while (fgets(line, sizeof line, f)) {
    if (sscanf(line, "gearbox %d", &a) == 1) G.menu.manual = a != 0;
    name_read(line, G.menu.name);
    int c2, d2 = 1;
    if (!G.options_global && sscanf(line, "option %d %d %d %d", &a, &b, &c2, &d2) >= 3) {
      G.menu.gyro = menu_steer_valid(a);
      G.menu.gyro_sens = b >= 1 && b <= 10 ? b : 5;
      G.menu.over_on = c2 != 0;
      G.menu.sharp_on = d2 != 0;
    }
    /* a garage from before the cars: the story's progress (st_div, st_bits; an older one's
     * "story <next select>" counted the selects one after the other) */
    if (sscanf(line, "story_div %d", &a) == 1 && a >= 0) G.menu.st_div = a, legacy = 1;
    if (sscanf(line, "story_bits %d", &a) == 1) G.menu.st_bits = a & 0xfffff, legacy = 1;
    if (sscanf(line, "story %d", &a) == 1 && a > 0 && a < 100)
      G.menu.st_div = a / 20, G.menu.st_bits = (1 << (a % 20)) - 1, legacy = 1;
    int c3;
    long long born;
    double odo;
    if (sscanf(line, "own %d %lld %lf %199[^\n]", &a, &born, &odo, label) == 4) {
      int mk, c;
      if (car_by_label(label, &mk, &c) && menu_own_find(&G.menu, mk, c) < 0 && G.menu.n_own < MENU_OWN_MAX &&
          a >= 0 && a < CARDB_CARS[mk][c].ncolors)
        G.menu.own[G.menu.n_own++] = (menu_own){ (signed char)mk, (signed char)c, (signed char)a, born, odo };
      continue;
    }
    if (sscanf(line, "ccolor %d %199[^\n]", &a, label) == 2) {
      int mk, c;
      if (car_by_label(label, &mk, &c)) (void)menu_body_color_restore(&G.menu,mk,c,a);
      continue; /* additive cosmetic record; never substitutes own[].color */
    }
    if (sscanf(line, "cdrive %d %d %199[^\n]", &a, &b, label) == 3) {
      int mk, c;
      unsigned value = mileage_style_encode(a, b);
      if (value && car_by_label(label, &mk, &c)) G.menu.drive_style_car[mk][c] = (unsigned char)value;
      continue;
    }
    if (sscanf(line, "cstory %d %d %199[^\n]", &a, &b, label) == 3) {
      int mk, c;
      if (car_by_label(label, &mk, &c) && a >= 0) G.menu.st_div_car[mk][c] = a, G.menu.st_bits_car[mk][c] = b & 0xfffff;
      continue;
    }
    if (sscanf(line, "cstar %d %d %199[^\n]", &a, &b, label) == 3) {
      int mk, c;
      if (car_by_label(label, &mk, &c) && a >= 0 && a <= 999999 && b >= 0 && b <= 999999)
        G.menu.vs_stars_car[mk][c] = a, G.menu.vs_count_car[mk][c] = b;
      continue;
    }
    if (sscanf(line, "cclass %d %199[^\n]", &a, label) == 2) {
      int mk, c;
      if (car_by_label(label, &mk, &c) && a >= 0 && a < HUD_CLASSES) G.menu.class_car[mk][c] = (signed char)a;
      continue;
    }
    if (sscanf(line, "ctitle %d %d %d %199[^\n]", &a, &b, &c3, label) == 4) {
      int mk, c;
      if (car_by_label(label, &mk, &c)) {
        G.menu.title_car[mk][c] = (short)(a > 0 && a < 0x7fff ? a : 0);
        G.menu.st_streak_car[mk][c] = (short)(b >= 0 && b < 0x7fff ? b : 0);
        G.menu.vs_wins_car[mk][c] = c3 >= 0 ? c3 : 0;
      }
      continue;
    }
    if (sscanf(line, "sttune %d %d %d %199[^\n]", &a, &b, &c3, label) == 4) {
      for (int mk = 0; mk < CARDB_ALL; ++mk)
        for (int c = 0; c < CARDB_NCARS[mk]; ++c)
          if (same_name(CARDB_CARS[mk][c].label, label) && a >= 0 && a <= CAR_TUNE_MAX && b >= 0 && b <= CAR_TUNE_MAX && c3 >= 0 && c3 < 20) {
            G.menu.st_power[mk][c] = (signed char)a;
            G.menu.st_handling[mk][c] = (signed char)b;
            G.menu.st_gauge[mk][c] = (signed char)c3;
          }
      continue;
    }
    if (sscanf(line, "dressp %d %199[^\n]", &a, label) == 2) {
      int mk, c;
      if (a >= 0 && a < 1000 && car_by_label(label, &mk, &c))
        G.menu.dress_points[mk][c] = (unsigned short)a;
      continue;
    }
    if (sscanf(line, "dress %d %d %199[^\n]", &a, &b, label) == 3) {
      for (int mk = 0; mk < CARDB_ALL; ++mk)
        for (int c = 0; c < CARDB_NCARS[mk]; ++c)
          if (same_name(CARDB_CARS[mk][c].label, label) && a >= 0 && a <= 63 && b >= 0 && b <= 3) {
            G.menu.dress_lv[mk][c] = (signed char)a;
            G.menu.aero[mk][c] = (signed char)b;
          }
      continue;
    }
    if (sscanf(line, "wear %d %d %d %199[^\n]", &a, &b, &c3, label) == 4) {
      for (int mk = 0; mk < CARDB_ALL; ++mk)
        for (int c = 0; c < CARDB_NCARS[mk]; ++c)
          if (same_name(CARDB_CARS[mk][c].label, label) && a >= 0 && a <= 1 && b >= 0 && b <= 4 && c3 >= 0 && c3 <= 3) {
            G.menu.mirror[mk][c] = (signed char)a;
            G.menu.wing[mk][c] = (signed char)b;
            G.menu.bonnet[mk][c] = (signed char)c3;
          }
      continue;
    }
    if (sscanf(line, "vinyl %d %199[^\n]", &a, label) == 2) {
      for (int mk = 0; mk < CARDB_ALL; ++mk)
        for (int c = 0; c < CARDB_NCARS[mk]; ++c)
          if (same_name(CARDB_CARS[mk][c].label, label) && a >= 0 && a < 100) G.menu.vinyl[mk][c] = (unsigned char)a;
      continue;
    }
    if (sscanf(line, "neon %d %199[^\n]", &a, label) == 2) {
      for (int mk = 0; mk < CARDB_ALL; ++mk)
        for (int c = 0; c < CARDB_NCARS[mk]; ++c)
          if (same_name(CARDB_CARS[mk][c].label, label) && a >= 0 && a <= 12) G.menu.neon[mk][c] = (signed char)a;
      continue;
    }
    if (sscanf(line, "wheel %d %199[^\n]", &a, label) == 2) {
      for (int mk = 0; mk < CARDB_ALL; ++mk)
        for (int c = 0; c < CARDB_NCARS[mk]; ++c)
          if (same_name(CARDB_CARS[mk][c].label, label) && a >= 0 && a <= 255) G.menu.wheel[mk][c] = (unsigned char)a;
      continue;
    }
    int t[11];
    if (sscanf(line, "ten %d %d %d %d %d %d %d %d %d %d %d %d", &a, &t[0], &t[1], &t[2], &t[3], &t[4], &t[5], &t[6], &t[7],
               &t[8], &t[9], &t[10]) == 12 && a >= 0 && a < 10) {
      for (int i = 0; i < 11; ++i) G.menu.ten_result[a][i] = (signed char)(t[i] >= 0 && t[i] <= 3 ? t[i] : 0);
      legacy |= 2;
      continue;
    }
    if (sscanf(line, "cten %d %d %d %d %d %d %d %d %d %d %d %d %199[^\n]", &a, &t[0], &t[1], &t[2], &t[3], &t[4], &t[5],
               &t[6], &t[7], &t[8], &t[9], &t[10], label) == 13 && a >= 0 && a < 10) {
      int mk, c;
      if (car_by_label(label, &mk, &c))
        for (int i = 0; i < 11; ++i) G.menu.ten_car[mk][c][a][i] = (signed char)(t[i] >= 0 && t[i] <= 3 ? t[i] : 0);
      continue;
    }
    if (sscanf(line, "tune %d %d %199[^\n]", &a, &b, label) != 3) continue;
    for (int mk = 0; mk < CARDB_ALL; ++mk)
      for (int c = 0; c < CARDB_NCARS[mk]; ++c)
        if (same_name(CARDB_CARS[mk][c].label, label) && b >= CAR_TUNE_TOTAL - CAR_TUNE_MAX && b <= CAR_TUNE_MAX) {
          G.menu.tune_full[mk][c] = (signed char)(a != 0);
          G.menu.tune_power[mk][c] = (signed char)b;
        }
  }
  fclose(f);
  if (!G.menu.n_own) garage_adopt_cars(legacy);
  /* (a garage from before the classes: each car's from its results) */
  menu_class_update(&G.menu);
}

static void garage_save(void) {
  char path[1100];
  if (!G.menu.save_slot) return;
  snprintf(path, sizeof path, "%s/garage%d", G.save_dir, G.menu.save_slot);
  FILE *f = fopen(path, "w");
  if (!f) return;
  fprintf(f, "gearbox %d\n", G.menu.manual);
  fprintf(f, "option %d %d %d %d\n", G.menu.gyro, G.menu.gyro_sens, G.menu.over_on, G.menu.sharp_on);
  /* the player's name (namedb.h's characters, -1 past its end) */
  fprintf(f, "name %d %d %d %d %d\n", G.menu.name[0], G.menu.name[1], G.menu.name[2], G.menu.name[3], G.menu.name[4]);
  /* the cars, in the order they came; each one's story and 10-in-a-row results and class
   * (raised to its results' here, as clRaceThread::fini does after each race: never lowered) */
  menu_class_update(&G.menu);
  for (int k = 0; k < G.menu.n_own; ++k) {
    const menu_own *o = &G.menu.own[k];
    const char *label = CARDB_CARS[o->maker][o->car].label;
    fprintf(f, "own %d %lld %.0f %s\n", o->color, o->born, o->odo, label);
    if (G.menu.custom_color[o->maker][o->car])
      fprintf(f, "ccolor %u %s\n", (unsigned)G.menu.custom_color[o->maker][o->car],label);
    fprintf(f, "cstory %d %d %s\n", G.menu.st_div_car[o->maker][o->car], G.menu.st_bits_car[o->maker][o->car], label);
    fprintf(f, "cclass %d %s\n", G.menu.class_car[o->maker][o->car], label);
    if (G.menu.drive_style_car[o->maker][o->car]) {
      int contact, wall;
      mileage_style_decode(G.menu.drive_style_car[o->maker][o->car], &contact, &wall);
      fprintf(f, "cdrive %d %d %s\n", contact, wall, label);
    }
    /* the versus stars and count (the card's +0x180, +0x17c) */
    fprintf(f, "cstar %d %d %s\n", G.menu.vs_stars_car[o->maker][o->car], G.menu.vs_count_car[o->maker][o->car], label);
    fprintf(f, "ctitle %d %d %d %s\n", G.menu.title_car[o->maker][o->car], G.menu.st_streak_car[o->maker][o->car],
            G.menu.vs_wins_car[o->maker][o->car], label);
    for (int c = 0; c < 10; ++c) {
      const signed char *t = G.menu.ten_car[o->maker][o->car][c];
      int any = 0;
      for (int i = 0; i < 11; ++i) any |= t[i];
      if (!any) continue;
      fprintf(f, "cten %d", c);
      for (int i = 0; i < 11; ++i) fprintf(f, " %d", t[i]);
      fprintf(f, " %s\n", label);
    }
  }
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      fprintf(f, "tune %d %d %s\n", G.menu.tune_full[mk][c], G.menu.tune_power[mk][c], CARDB_CARS[mk][c].label);
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      fprintf(f, "sttune %d %d %d %s\n", G.menu.st_power[mk][c], G.menu.st_handling[mk][c], G.menu.st_gauge[mk][c],
              CARDB_CARS[mk][c].label);
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      if (G.menu.dress_lv[mk][c] || G.menu.aero[mk][c])
        fprintf(f, "dress %d %d %s\n", G.menu.dress_lv[mk][c], G.menu.aero[mk][c], CARDB_CARS[mk][c].label);
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      if (G.menu.dress_points[mk][c] && G.menu.dress_lv[mk][c] < 63)
        fprintf(f, "dressp %u %s\n", (unsigned)G.menu.dress_points[mk][c], CARDB_CARS[mk][c].label);
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      if (G.menu.mirror[mk][c] || G.menu.wing[mk][c] || G.menu.bonnet[mk][c])
        fprintf(f, "wear %d %d %d %s\n", G.menu.mirror[mk][c], G.menu.wing[mk][c], G.menu.bonnet[mk][c],
                CARDB_CARS[mk][c].label);
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      if (G.menu.wheel[mk][c]) fprintf(f, "wheel %d %s\n", G.menu.wheel[mk][c], CARDB_CARS[mk][c].label);
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      if (G.menu.neon[mk][c]) fprintf(f, "neon %d %s\n", G.menu.neon[mk][c], CARDB_CARS[mk][c].label);
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      if (G.menu.vinyl[mk][c]) fprintf(f, "vinyl %d %s\n", G.menu.vinyl[mk][c], CARDB_CARS[mk][c].label);
  fclose(f);
}

/* ---- the port's saves (menu.c's SAVE DATA screen): save n (1..MENU_SAVES) is
 * save_dir/garage<n> and records<n>, save_dir/slot names the one in use. A garage and
 * records from before the saves become save 1. ---- */
/* Sidecars identify the selected owned card, not a car-select preview. Numeric
 * components are generated from validated database indices and registration time. */
static int bgm_level = 3;
static char bgm_current_path[1100];
/* Failed cleanup cannot be treated as an empty sidecar. Fail closed for this
 * process; in particular a same-second re-registration must not reuse it. */
static unsigned char bgm_blocked[MENU_SAVES + 1][CARDB_ALL][CARDB_MAX_CARS];
static unsigned char bgm_slot_blocked[MENU_SAVES + 1];
static int bgm_card_path(char *path, size_t size, int slot, const menu_own *o) {
  if (!G.save_dir[0] || slot < 1 || slot > MENU_SAVES || !o || o->maker < 0 ||
      o->maker >= CARDB_ALL || o->car < 0 || o->car >= CARDB_NCARS[(int)o->maker]) return 0;
  int n = snprintf(path, size, "%s/bgm_card_%d_%d_%d_%lld", G.save_dir, slot, o->maker, o->car, o->born);
  return n > 0 && (size_t)n < size;
}
static int bgm_path(char *path, size_t size) {
  int k = G.menu.own_sel;
  if (k < 0 || k >= G.menu.n_own || k >= MENU_OWN_MAX) return 0;
  const menu_own *o = &G.menu.own[k];
  int slot = G.menu.save_slot;
  if (!bgm_card_path(path, size, slot, o)) return 0;
  if (bgm_slot_blocked[slot] || bgm_blocked[slot][(int)o->maker][(int)o->car]) return 0;
  return 1;
}
/* Only a genuinely absent entry is eligible for initial creation. All other
 * errors, including a failed close, are unsafe to overwrite. Never follow links. */
static int bgm_validate(const char *path, int *level) {
  char buf[8]; struct stat st, after;
  int fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
  if (fd < 0) return errno == ENOENT ? 1 : 0;
  int ok = fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && st.st_size == 7;
  size_t used = 0;
  while (ok && used < sizeof buf) {
    ssize_t n = read(fd, buf + used, sizeof buf - used);
    if (n < 0 && errno == EINTR) continue;
    if (n < 0) { ok = 0; break; }
    if (!n) break;
    used += (size_t)n;
  }
  if (ok) ok = used == 7 && !memcmp(buf, "bgm1 ", 5) &&
      buf[5] >= '0' && buf[5] <= '3' && buf[6] == '\n' &&
      fstat(fd, &after) == 0 && S_ISREG(after.st_mode) && after.st_size == 7;
  if (close(fd) != 0) ok = 0;
  if (!ok) return 0;
  *level = buf[5] - '0';
  return 2;
}
static void bgm_load(void) {
  char path[1100]; int level = 3;
  bgm_level = 3; /* Android compatibility, not the original card default (2). */
  bgm_current_path[0] = 0;
  if (!bgm_path(path, sizeof path)) return;
  memcpy(bgm_current_path, path, strlen(path) + 1);
  if (bgm_validate(path, &level) == 2) bgm_level = level;
}
static void bgm_erase_card(int slot, const menu_own *o) {
  char path[1100];
  if (!bgm_card_path(path, sizeof path, slot, o)) return;
  if (unlink(path) && errno != ENOENT) {
    bgm_blocked[slot][(int)o->maker][(int)o->car] = 1;
    fprintf(stderr, "bgm: card cleanup failed; setting disabled for this session\n");
  }
  bgm_current_path[0] = 0;
  bgm_level = 3;
}
/* A new/deleted slot must not inherit stale card files. Only remove exact generated
 * names in this trusted save directory; never follow directory entries as links. */
static void bgm_erase(int slot) {
  if (!G.save_dir[0] || slot < 1 || slot > MENU_SAVES) return;
  DIR *dir = opendir(G.save_dir);
  if (!dir) { bgm_slot_blocked[slot] = 1; bgm_current_path[0] = 0; bgm_level = 3; return; }
  int failed = 0;
  struct dirent *entry;
  for (;;) {
    errno = 0;
    entry = readdir(dir);
    if (!entry) { if (errno) failed = 1; break; }
    int s, mk, car, used = 0; long long born;
    if (sscanf(entry->d_name, "bgm_card_%d_%d_%d_%lld%n", &s, &mk, &car, &born, &used) != 4 ||
        entry->d_name[used] || s != slot || mk < 0 || mk >= CARDB_ALL || car < 0 || car >= CARDB_NCARS[mk]) continue;
    menu_own o = { (signed char)mk, (signed char)car, 0, born, 0 };
    char canonical[1100];
    if (!bgm_card_path(canonical, sizeof canonical, slot, &o)) continue;
    const char *base = strrchr(canonical, '/');
    if (base && !strcmp(base + 1, entry->d_name) && unlink(canonical) && errno != ENOENT)
      failed = 1;
  }
  if (closedir(dir)) failed = 1;
  if (failed) {
    bgm_slot_blocked[slot] = 1;
    fprintf(stderr, "bgm: slot cleanup failed; settings disabled for this session\n");
  }
  bgm_current_path[0] = 0;
  bgm_level = 3;
}
static void bgm_sync(void) {
  char path[1100];
  if (!bgm_path(path, sizeof path)) path[0] = 0;
  if (strcmp(path, bgm_current_path)) bgm_load();
}
int app_get_bgm_volume(void) { bgm_sync(); return bgm_level; }
float app_bgm_volume_multiplier(void) {
  static const float gain[4] = { 0.0f, 0.30f / 0.70f, 0.50f / 0.70f, 1.0f };
  return gain[app_get_bgm_volume()];
}
int app_set_bgm_volume(int level) {
  char path[1100], tmp[1100], value[8] = "bgm1 0\n";
  if (level < 0 || level > 3 || !bgm_path(path, sizeof path)) return 0;
  int old_level = 3, state = bgm_validate(path, &old_level);
  if (!state) return 0;
  int n = snprintf(tmp, sizeof tmp, "%s.tmp.XXXXXX", path);
  if (n < 0 || (size_t)n >= sizeof tmp) return 0;
  int fd = mkstemp(tmp);
  if (fd < 0) return 0;
  value[5] = (char)('0' + level);
  int ok = write(fd, value, 7) == 7 && fsync(fd) == 0;
  if (close(fd) != 0) ok = 0;
  /* Recheck immediately before rename; this narrows but cannot eliminate the
   * pathname race against a concurrent writer in the save directory. */
  int checked_level = 3;
  if (ok && (bgm_validate(path, &checked_level) != state ||
             (state == 2 && checked_level != old_level))) ok = 0;
  if (ok && rename(tmp, path) != 0) ok = 0;
  if (!ok) { unlink(tmp); return 0; }
  memcpy(bgm_current_path, path, strlen(path) + 1);
  bgm_level = level;
  return 1;
}

static void save_slot_write(void) {
  char path[1100];
  snprintf(path, sizeof path, "%s/slot", G.save_dir);
  FILE *f = fopen(path, "w");
  if (!f) return;
  fprintf(f, "%d\n", G.menu.save_slot);
  fclose(f);
}

/* the old garage and records as save n's */
static void save_adopt(int n) {
  static const char *const WHAT[2] = { "garage", "records" };
  for (int i = 0; i < 2; ++i) {
    char from[1100], to[1100];
    snprintf(from, sizeof from, "%s/%s", G.save_dir, WHAT[i]);
    snprintf(to, sizeof to, "%s/%s%d", G.save_dir, WHAT[i], n);
    if (access(from, F_OK) == 0) rename(from, to);
  }
}

static void save_open(void) {
  char path[1100];
  int slot = 0;
  snprintf(path, sizeof path, "%s/slot", G.save_dir);
  FILE *f = fopen(path, "r");
  if (f) {
    if (fscanf(f, "%d", &slot) != 1 || slot < 0 || slot > MENU_SAVES) slot = 0;
    fclose(f);
  } else {
    snprintf(path, sizeof path, "%s/garage", G.save_dir);
    if (access(path, R_OK) == 0) {
      save_adopt(1);
      slot = 1;
    }
  }
#ifdef WMMT_EGL
  /* test: the data dir's garage as this save, START straight to the maker select */
  if (getenv("WMMT_SAVE_SLOT")) {
    slot = atoi(getenv("WMMT_SAVE_SLOT"));
    save_adopt(slot);
    G.menu.save_skip = 1;
  }
#endif
  G.menu.save_slot = slot;
  bgm_load();
  if (!f && slot) save_slot_write();
}

/* what the save screen shows of each save */
static void save_scan(void) {
  int any = 0;
  for (int k = 0; k < MENU_SAVES; ++k) {
    menu_save_info *s = &G.menu.save[k];
    memset(s, 0, sizeof *s);
    memset(s->name, -1, sizeof s->name);
    char path[1100], line[256];
    snprintf(path, sizeof path, "%s/garage%d", G.save_dir, k + 1);
    FILE *f = fopen(path, "r");
    if (!f) continue;
    s->used = any = 1;
    struct stat st;
    if (fstat(fileno(f), &st) == 0) s->when = (long long)st.st_mtime;
    /* (a garage from before the cars: its one story) */
    int div = 0, bits = 0, a, b, t[11];
    while (fgets(line, sizeof line, f)) {
      if (sscanf(line, "story_div %d", &a) == 1 && a >= 0) div = a;
      if (sscanf(line, "story_bits %d", &a) == 1) bits = a & 0xfffff;
      if (sscanf(line, "cstory %d %d", &a, &b) == 2 && a >= 0) s->story += 20 * a + __builtin_popcount((unsigned)b & 0xfffff);
      if (strncmp(line, "own ", 4) == 0) s->cars++;
      name_read(line, s->name);
      if (sscanf(line, "ten %d %d %d %d %d %d %d %d %d %d %d %d", &a, &t[0], &t[1], &t[2], &t[3], &t[4], &t[5], &t[6],
                 &t[7], &t[8], &t[9], &t[10]) == 12 ||
          sscanf(line, "cten %d %d %d %d %d %d %d %d %d %d %d %d", &a, &t[0], &t[1], &t[2], &t[3], &t[4], &t[5], &t[6],
                 &t[7], &t[8], &t[9], &t[10]) == 12)
        for (int i = 0; i < 11; ++i) s->medals += t[i] == 3;
    }
    fclose(f);
    s->story += 20 * div + __builtin_popcount((unsigned)bits);
  }
  if (!any) G.menu.save_new = 1, G.menu.save_del = 0;
}

/* the save DELETE took off the save screen: its garage and records (and the save in use no
 * more, if it was) */
static void save_erase(int n) {
  bgm_erase(n);
  static const char *const WHAT[2] = { "garage", "records" };
  for (int i = 0; i < 2; ++i) {
    char path[1100];
    snprintf(path, sizeof path, "%s/%s%d", G.save_dir, WHAT[i], n);
    remove(path);
  }
  if (G.menu.save_slot == n) {
    G.menu.save_slot = 0;
    bgm_load();
    save_slot_write();
  }
  fprintf(stderr, "save %d deleted\n", n);
}

static void card_choice_clear(void) {
  memset(G.menu.meter_car, 0, sizeof G.menu.meter_car);
  memset(G.menu.sound_car, 0, sizeof G.menu.sound_car);
  memset(G.menu.st_bonus_car, 0, sizeof G.menu.st_bonus_car);
  memset(G.menu.card_born, 0, sizeof G.menu.card_born);
}
/* Evidence is separate from the original garage and card selection store.
 * A missing sidecar means unknown history, never a clean first loop. */
static story_evidence story_ev[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
static unsigned char story_poison[MENU_SAVES + 1][MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
static story_evidence story_live[MENU_SAVES + 1][MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
static long long story_live_born[MENU_SAVES + 1][MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
static unsigned char story_confirmed[MENU_GARAGE_MAKERS][MENU_GARAGE_CARS];
static void story_remember(int slot,int mk,int c,long long born) {
  story_live[slot][mk][c]=story_ev[mk][c]; story_live_born[slot][mk][c]=born;
}
static int story_confirm_path(char *out,size_t n,const char *path) {
  int k=snprintf(out,n,"%s.confirmed",path); return k>=0 && (size_t)k<n;
}
static int story_path(char *p, size_t n, int mk, int car, long long born) {
  int slot=G.menu.save_slot;
  if(slot<1||slot>MENU_SAVES||mk<0||mk>=MENU_GARAGE_MAKERS||car<0||car>=MENU_GARAGE_CARS||born<=0)return 0;
  int x=snprintf(p,n,"%s/story-evidence-v1-%d-%d-%d-%lld",G.save_dir,slot,mk,car,born);
  return x>=0 && (size_t)x<n;
}
static void story_publish(int mk,int c,long long born) {
  menu_state *m=&G.menu;
  if(m->card_born[mk][c]!=born) m->meter_car[mk][c]=m->sound_car[mk][c]=0;
  m->card_born[mk][c]=born;
  m->st_bonus_car[mk][c]=story_confirmed[mk][c];
}
static void story_load_all(void) {
  menu_state *m=&G.menu;
  memset(story_ev,0,sizeof story_ev);
  memset(story_confirmed,0,sizeof story_confirmed);
  memset(m->st_bonus_car,0,sizeof m->st_bonus_car);
  if(m->save_slot<1||m->save_slot>MENU_SAVES)return;
  for(int i=0;i<m->n_own && i<MENU_OWN_MAX;i++) {
    int mk=m->own[i].maker,c=m->own[i].car; long long born=m->own[i].born; char p[1100];
    if(!story_path(p,sizeof p,mk,c,born))continue;
    story_evidence_begin(&story_ev[mk][c],m->st_div_car[mk][c],0);
    int r=se_load(p,&story_ev[mk][c]);
    char cp[1200]; story_evidence confirmed;
    if(story_confirm_path(cp,sizeof cp,p) && se_load(cp,&confirmed)==1)
      story_confirmed[mk][c]=(unsigned char)(confirmed.flags & (STORY_EVIDENCE_CLEAR|STORY_EVIDENCE_FIRST|STORY_EVIDENCE_SECOND));
    /* A disk write may precede the garage transaction. Only the independent
     * confirmation is durable authority for rewards, never WCS2 or SE01 flags. */
    story_ev[mk][c].flags &= ~(STORY_EVIDENCE_CLEAR|STORY_EVIDENCE_FIRST|STORY_EVIDENCE_SECOND);
    story_ev[mk][c].flags |= story_confirmed[mk][c];
    story_ev[mk][c].known_clean=0;
    if(story_live_born[m->save_slot][mk][c]==born && r==1 &&
       story_live[m->save_slot][mk][c].expected_div==m->st_div_car[mk][c] &&
       story_ev[mk][c].expected_div==m->st_div_car[mk][c])
      story_ev[mk][c]=story_live[m->save_slot][mk][c];
    if(r<0) story_poison[m->save_slot][mk][c]=1;
    if(r==1 && story_ev[mk][c].expected_div!=m->st_div_car[mk][c]) {
      story_ev[mk][c].expected_div=m->st_div_car[mk][c];
      story_ev[mk][c].known_clean=0;
      /* A race committed before garage_save may not be reflected there.
       * Discard pending evidence; the independent confirmation survives. */
      story_ev[mk][c].flags &= ~(STORY_EVIDENCE_CLEAR | STORY_EVIDENCE_FIRST | STORY_EVIDENCE_SECOND);
      story_poison[m->save_slot][mk][c]=1;
    }
    story_publish(mk,c,born);
  }
}
static void story_new_card_commit(void) {
  menu_state *m=&G.menu;
  if(!m->story_new_pending)return;
  int mk=m->story_new_maker,c=m->story_new_car; long long born=m->story_new_born;
  m->story_new_pending=0;
  if(mk<0||mk>=MENU_GARAGE_MAKERS||c<0||c>=MENU_GARAGE_CARS)return;
  story_evidence_begin(&story_ev[mk][c],0,0);
  story_confirmed[mk][c]=0;
  m->st_bonus_car[mk][c]=0;
  char p[1100];
  if(!story_path(p,sizeof p,mk,c,born) || cc_owner(m,mk,c)!=born)return;
  int slot=m->save_slot;
  if(story_live_born[slot][mk][c]!=born) story_poison[slot][mk][c]=0;
  story_evidence candidate,old; char cp[1200];
  story_evidence_begin(&candidate,0,1);
  /* Never take ownership of either existing file, even on timestamp collision. */
  if(story_poison[slot][mk][c]||!story_confirm_path(cp,sizeof cp,p)||
     se_load(p,&old)!=0||se_load(cp,&old)!=0||!se_save(p,&candidate)) {
    story_poison[slot][mk][c]=1; m->card_save_failed=1;
    story_evidence_begin(&story_ev[mk][c],0,0);
  } else story_ev[mk][c]=candidate;
  story_remember(slot,mk,c,born);
  story_publish(mk,c,born);
}
/* garage_save is legacy void and writes in place. Verify its observable record
 * before allowing evidence-derived no-loss rewards in this process. */
static void story_verify_garage(void) {
  menu_state *m=&G.menu; int mk=m->maker,c=m->car; long long born=cc_owner(m,mk,c);
  char path[1100],line[256],label[200];
  if(!story_path(path,sizeof path,mk,c,born))return;
  snprintf(path,sizeof path,"%s/garage%d",G.save_dir,m->save_slot);
  FILE *f=fopen(path,"r"); int own=0,stories=0,valid=1;
  if(!f)valid=0;
  while(f && fgets(line,sizeof line,f)) {
    int a,b,x,y; long long t; double odo;
    if(sscanf(line,"own %d %lld %lf %199[^\n]",&a,&t,&odo,label)==4 &&
       car_by_label(label,&x,&y) && x==mk && y==c) { own++; if(t!=born)valid=0; }
    if(sscanf(line,"cstory %d %d %199[^\n]",&a,&b,label)==3 &&
       car_by_label(label,&x,&y) && x==mk && y==c) {
      stories++; if(a!=m->st_div || b!=m->st_bits)valid=0;
    }
  }
  if(f) { int err=ferror(f); if(fclose(f))err=1; if(err)valid=0; }
  if(!valid || own!=1 || stories!=1 || story_ev[mk][c].expected_div!=m->st_div) {
    story_ev[mk][c].known_clean=0;
    story_ev[mk][c].flags &= ~(STORY_EVIDENCE_CLEAR|STORY_EVIDENCE_FIRST|STORY_EVIDENCE_SECOND);
    story_poison[m->save_slot][mk][c]=1;
    m->card_save_failed=1;
  } else if(!story_poison[m->save_slot][mk][c]) {
    unsigned int flags=(story_ev[mk][c].flags | story_confirmed[mk][c]) & (STORY_EVIDENCE_CLEAR|STORY_EVIDENCE_FIRST|STORY_EVIDENCE_SECOND);
    if(flags!=story_confirmed[mk][c]) {
      char evidence[1100],cp[1200]; story_evidence confirmation;
      story_evidence_begin(&confirmation,m->st_div,0); confirmation.flags=flags;
      if(story_path(evidence,sizeof evidence,mk,c,born) && story_confirm_path(cp,sizeof cp,evidence) && se_save(cp,&confirmation))
        story_confirmed[mk][c]=(unsigned char)flags;
      else { story_poison[m->save_slot][mk][c]=1; m->card_save_failed=1; }
    }
  }
  story_remember(m->save_slot,mk,c,born);
  story_publish(mk,c,born);
}
static void story_race_commit(int won,int final_race) {
  menu_state *m=&G.menu; int mk=m->maker,c=m->car; char p[1100];
  long long born=cc_owner(m,mk,c);
  if(!story_path(p,sizeof p,mk,c,born))return;
  int slot=m->save_slot;
  if(story_poison[slot][mk][c]) { story_publish(mk,c,born); return; }
  story_evidence candidate=story_ev[mk][c];
  if(candidate.expected_div!=m->st_div) {
    candidate.expected_div=m->st_div; candidate.known_clean=0;
  }
  if(!story_evidence_result(&candidate,m->st_div,m->story_n,won,final_race)||!se_save(p,&candidate)) {
    story_poison[slot][mk][c]=1; m->card_save_failed=1;
  } else story_ev[mk][c]=candidate;
  story_remember(slot,mk,c,born);
  story_publish(mk,c,born);
}
static void card_choice_load(void) {
  card_choice_clear();
  G.menu.card_choice_error = G.menu.save_slot && cc_load(G.save_dir, G.menu.save_slot, &G.menu) < 0;
  G.menu.card_save_failed = G.menu.card_choice_error;
  story_load_all();
}
int app_card_choice_commit(menu_state *m, int row, int choice, long long born) {
  if (m != &G.menu || m->card_choice_error || !born || !menu_card_choice_available(m, row, choice)) return 0;
  int mk = m->maker, c = m->car;
  signed char meter = m->meter_car[mk][c], sound = m->sound_car[mk][c];
  unsigned char bonus = m->st_bonus_car[mk][c];
  long long oldborn = m->card_born[mk][c];
  if (oldborn != born) m->meter_car[mk][c] = m->sound_car[mk][c] = m->st_bonus_car[mk][c] = 0;
  m->card_born[mk][c] = born;
  if (row) m->sound_car[mk][c] = choice; else m->meter_car[mk][c] = choice;
  if (cc_save(G.save_dir, m->save_slot, m)) return 1;
  m->meter_car[mk][c] = meter; m->sound_car[mk][c] = sound;
  m->st_bonus_car[mk][c] = bonus; m->card_born[mk][c] = oldborn;
  return 0;
}

/* the save chosen: loaded, or started over (the OPTION screen's choices kept) */
static void save_take(void) {
  app_story_body_clear();
  app_body_drop(0);
  menu_body_color_clear_pages(&G.menu);
  G.menu.save_slot = G.menu.save_pick;
  G.menu.save_pick = 0;
  menu_garage_reset(&G.menu);
  if (G.menu.save_pick_new) {
    bgm_erase(G.menu.save_slot);
    char path[1100];
    snprintf(path, sizeof path, "%s/records%d", G.save_dir, G.menu.save_slot);
    remove(path);
    garage_save();
  } else {
    garage_load();
  }
  card_choice_load();
  if (G.menu.save_pick_new) {
    card_choice_clear();
    if (!G.menu.card_choice_error && !cc_save(G.save_dir, G.menu.save_slot, &G.menu)) G.menu.card_choice_error = 1;
    G.menu.card_save_failed = G.menu.card_choice_error;
  }
  records_load();
  bgm_load();
  save_slot_write();
  fprintf(stderr, "save %d %s\n", G.menu.save_slot, G.menu.save_pick_new ? "started over" : "loaded");
}

void app_save_dir(const char *dir) {
  if (!dir) return;
  if (strcmp(G.save_dir, dir)) app_ta_rank_release();
  snprintf(G.save_dir, sizeof G.save_dir, "%s", dir);
}

void app_console(void) {
  G.console = 1;
  car_hits(1);
}

void app_wide(float edge, float key_k) {
  G.edge = edge > 0 ? edge : 0;
  G.phone = G.edge > 0 && !G.console;
  anm_view(G.edge);
  hud_wide(G.edge, key_k);
  menu_wide(G.edge); /* (the menus' backs across a wide screen) */
  if (G.console && G.edge > 0) {
    hud_lift(28, 40); /* (the plate sat on the pedals, the shift gate on ◀) */
  } else if (G.edge > 0) {
    /* an iPhone's keys x1.3: the plate off the pedals, the meters off it with the pill still
     * clear of them and of the records over it, the map off the gate and the gate off ◀ */
    hud_lift_parts(32, 42, 40, 40, 25);
  }
}

/* Presentation geometry only. Called on the game thread after the platform has
 * obtained a valid drawable extent; never reinitialize resources or simulation. */
int app_viewport(int fb_width, int fb_height, float edge, float key_k) {
  if (fb_width <= 0 || fb_height <= 0 || !isfinite(edge) || edge < 0.0f ||
      !isfinite(key_k) || key_k <= 0.0f) return 0;
  G.fb_w = fb_width;
  G.fb_h = fb_height;
  app_wide(edge, key_k);
  return 1;
}

#ifdef __ANDROID__
static timing60_sim android_sim;
#endif

int app_init(const char *data_dir, int fb_width, int fb_height, float screen_w, float screen_h) {
  app_smoke_release(1); /* reset owner before first tick; forget old-context names */
  app_body_reset(1); /* forget dead-context player handles before names can be reused */
  app_ghost_context_reset(); /* before any new context can reuse an old texture name */
#ifdef __ANDROID__
  timing60_sim_reset(&android_sim);
#endif
  app_timing_reset();
  char path[1100];
  G.fb_w = fb_width;
  G.fb_h = fb_height;
  if (render_init() != 0 || hud_gl_init() != 0) {
    snprintf(G.error, sizeof G.error, "shader setup failed");
    return -1;
  }
  /* a phone of today's (app_console) can afford the road ahead sharp: trilinear and 16x
   * anisotropic filtering */
  if (G.console) render_aniso(16);
  snprintf(G.data_dir, sizeof G.data_dir, "%s", data_dir);
  backfire_open(data_dir);
  mileage_aura_open(data_dir);
#ifdef __ANDROID__
  player_tracks_open(data_dir);
  player_smoke_open(data_dir);
#endif
  if (!G.save_dir[0]) snprintf(G.save_dir, sizeof G.save_dir, "%s", data_dir);
  /* and the 3D multisampled in half floats, with a bloom over the lights (a file hq_off in
   * the data folder, or WMMT_NO_HQ, for the frame times without, to compare) */
  snprintf(path, sizeof path, "%s/hq_off", G.data_dir);
  if (G.console && !getenv("WMMT_NO_HQ") && access(path, F_OK) != 0) {
    /* (hq_2x: 2x MSAA, to weigh against the 4x) */
    snprintf(path, sizeof path, "%s/hq_2x", G.data_dir);
    /* (and the OPTION screen's ANTI-ALIASING 2X, save_dir/option's 13th: from this start) */
    int ms2 = access(path, F_OK) == 0 || !options_peek(12, 1);
    /* (hq_blits: the multisampled buffers resolved by blits, not rendered into textures) */
    snprintf(path, sizeof path, "%s/hq_blits", G.data_dir);
    if (access(path, F_OK) == 0) render_hq_blits();
    G.hq_on = render_hq(ms2 ? 2 : 4, 0.6f);
    G.hq_bloom = -1; /* (hq_apply hands render_hq the switches whatever they are) */
    /* the race's ambient occlusion only with a file ssao_on or the OPTION screen's SSAO (its
     * 20 ms on the Mi 6 cost the 60 fps; hq_apply) */
    snprintf(path, sizeof path, "%s/ssao_on", G.data_dir);
    if (access(path, F_OK) == 0) render_ssao(1.0f), G.hq_ssao_made = 1;
    if (getenv("WMMT_HQ_LEVEL")) G.gov_level = G.gov_floor = render_hq_level(atoi(getenv("WMMT_HQ_LEVEL")));
  }
  /* what a texture's or a buffer's first draw costs on this GPU, each way, for perf.log */
  char test[1200];
  render_selftest(test, sizeof test);
  perf_file();
  if (G.perf) {
    fprintf(G.perf, "%s (%s)\n", test, PORT_BUILD);
    fflush(G.perf);
  }
  pthread_mutex_init(&G.load_mx, NULL);
  pthread_cond_init(&G.load_cv, NULL);
  /* the time zone of the last race (the map the menus load first) and whether there is a night */
  snprintf(path, sizeof path, "%s/timezone", G.save_dir);
  FILE *tz = fopen(path, "r");
  int zone = tz ? fgetc(tz) == '1' : 0;
  if (tz) fclose(tz);
  G.extras_city = -1;
  city_path(path, sizeof path, "", CAR_TOKYO, 1, "wpk");
  int zones = access(path, R_OK) == 0 ? 2 : 1;
  if (zone >= zones) zone = 0;
  /* the street lights' sprites (their points come by city, extras_open) */
  if (lights_load(data_dir) != 0) fprintf(stderr, "no lights.wpk/lights.bin, no street lights\n");
  front_halo_open(data_dir);
  /* the course goes up to GL a little each frame while the maker logos play (app_frame) */
  G.hd_maps = G.hq_on && options_peek(7, 1); /* (the HD TEXTURES: hq_apply after the menus' options) */
  if (track_open(CAR_TOKYO, zone) != 0) {
    snprintf(G.error, sizeof G.error, "cannot load %s", path);
    return -1;
  }
  snprintf(path, sizeof path, "%s/fd3s.wpk", data_dir);
  if (wpk_load(&G.fd3s, path) != 0) {
    snprintf(G.error, sizeof G.error, "cannot load %s", path);
    return -1;
  }
  G.fd3s.two_sided = 1;
  snprintf(path, sizeof path, "%s/minicourse.wpk", data_dir);
  if (wpk_load(&G.mini, path) == 0) G.mini.two_sided = 1;
  else fprintf(stderr, "no %s, no 3D map on the course selects\n", path);
  static const char *const TRAFFIC_FILE[CAR_TRAFFIC_MODELS] = { "nze121", "kzh100g", "truck", "rc2" };
  for (int k = 0; k < CAR_TRAFFIC_MODELS; ++k) {
    snprintf(path, sizeof path, "%s/traffic/%s.wpk", data_dir, TRAFFIC_FILE[k]);
    if (wpk_load(&G.traffic[k], path) == 0) G.traffic[k].two_sided = 1;
    else fprintf(stderr, "no %s, that traffic car is not drawn\n", path);
  }
  if (car_init(data_dir, G.error, sizeof G.error) != 0) return -1;
  hud_init(&G.hud, screen_w, screen_h);
  if (hud_load(data_dir) != 0) fprintf(stderr, "hud.bin missing, gauges off\n");
  if (snd_init(data_dir) != 0) fprintf(stderr, "some sound files are missing\n");
  /* GroundRange, ShortBuildRange, LongBuildRange from c1_daytime.lua (ground a little
   * further than the arcade's 4000 so the road ahead never pops in) */
  G.rp.range[WPK_GROUND] = 5000.0f;
  G.rp.range[WPK_SHORT] = 7000.0f;
  G.rp.range[WPK_LONG] = 10000.0f;
  G.rp.lamps_on = 1; /* the race's cars: clCarConstructParam mode 0 (3 the official machine) */
  G.rp.no_gloss = getenv("WMMT_NO_GLOSS") != NULL; /* test: the maps without their reflections */
  G.no_over = getenv("WMMT_NO_OVERHEAD") != NULL;
  G.no_sharp = getenv("WMMT_NO_SHARPEN") != NULL;
  G.ao_test = getenv("WMMT_AO") ? atoi(getenv("WMMT_AO")) != 0 : -1;
  if (G.phone) {
    G.rp.range[WPK_GROUND] = 4000.0f;
    G.rp.range[WPK_SHORT] = 4500.0f;
    G.rp.range[WPK_LONG] = 6500.0f;
    G.rp.no_gloss = G.no_over = G.no_sharp = 1;
    G.low_memory = 1;
    wpk_tex_half(1); /* the maps' textures alone were 153 MB of its 512 */
  }
  if (G.console) {
    /* GPU and memory to spare: the maps drawn much further (the arcade's own long range) */
    G.rp.range[WPK_GROUND] = 9000.0f;
    G.rp.range[WPK_SHORT] = 12000.0f;
    G.rp.range[WPK_LONG] = 18000.0f;
  }
  if (anm_load(data_dir) != 0) {
    snprintf(G.error, sizeof G.error, "cannot load %s/menu.bin", data_dir);
    return -1;
  }
  menu_init(&G.menu);
  save_open();
  int layout_loaded = key_layout_load(); /* before options_save can alter option */
  G.options_global = options_load();
  G.menu.hq_rows = G.hq_on;
  G.menu.res_row = !G.hq_on && !G.console && G.edge <= 0; /* (an iPad's) */
  hq_apply();
  garage_load();
  if (layout_loaded) key_layout_clamp_visible(); /* final gyro and geometry known; no dirty write */
#ifdef __ANDROID__
  /* The stick center is independent of HUD_CUSTOM and legacy key files. */
  {
    char stick_path[1100];
    if (snprintf(stick_path,sizeof stick_path,"%s/stick_center",G.save_dir) >= (int)sizeof stick_path)
      G.menu.stick_center_status=STICK_STORE_IO;
    else G.menu.stick_center_status=stick_store_load(stick_path,&G.menu.stick_center_mode);
  }
  /* Missing/invalid extensions always start from defaults, without writing anything. */
  hud_custom_default(&G.menu.custom_layout);
  G.menu.custom_layout.shift.k=G.menu.key_k[HUD_KEYS_RIGHT];
  G.menu.custom_layout.shift.dx=G.menu.key_dx[HUD_KEYS_RIGHT];
  G.menu.custom_layout.shift.dy=G.menu.key_dy[HUD_KEYS_RIGHT];
  G.menu.custom_layout_base=G.menu.custom_layout;
  {
    char custom_path[1100]; HudCustomLayout loaded;
    if (snprintf(custom_path,sizeof custom_path,"%s/hud_custom_layout",G.save_dir) >= (int)sizeof custom_path)
      G.menu.custom_layout_status=HUD_CUSTOM_IO_ERROR;
    else {
      G.menu.custom_layout_status=hud_custom_load(custom_path,&loaded);
      if (G.menu.custom_layout_status==HUD_CUSTOM_OK) {
        G.menu.custom_layout_base=loaded;
        custom_layout_clamp_visible(&loaded, G.menu.gyro);
        G.menu.custom_layout=loaded;
      }
    }
  }
#endif
  card_choice_load();
  records_load();
  G.menu.zone = zone;
  G.menu.ta_zone = zone;
  snprintf(path, sizeof path, "%s/story_timezone", G.save_dir);
  FILE *story_tz = fopen(path, "r");
  G.menu.story_zone = story_tz ? fgetc(story_tz) == '1' : 0;
  if (story_tz) fclose(story_tz);
  G.menu.zones = zones;
  G.race_model = &G.fd3s;
  G.rival = G.rival_env = -1;
  /* the versus: the server last used, this app's id there (fresh each start) */
  G.menu.vs.ramp = 6; /* WANGAN_OUT_13 */
  G.menu.vs.km = 13;  /* as the arcade's getJoinDist */
  G.vs_id = (uint32_t)time(NULL) * 2654435761u ^ (uint32_t)getpid() << 16 ^ (uint32_t)(now_ms() * 1000.0);
  if (!G.vs_id) G.vs_id = 1;
#ifdef WMMT_EGL
  if (getenv("WMMT_RIVAL")) G.rival = G.rival_env = atoi(getenv("WMMT_RIVAL")); /* test: race this RIVALDB rival */
#endif
  G.in_menu = 1;
#ifdef WMMT_NATIVE_VK
  uint32_t api_version = cinder_vk_device_api_version();
  fprintf(stderr, "native Vulkan %s | %u.%u.%u | tex %u batches %u chunks %u | menu ready\n",
          cinder_vk_device_name(), VK_VERSION_MAJOR(api_version), VK_VERSION_MINOR(api_version), VK_VERSION_PATCH(api_version),
          G.track.n_tex, G.track.n_batch, G.track.n_chunk);
#else
  fprintf(stderr, "GL %s | %s | tex %u batches %u chunks %u | menu ready\n",
          (const char *)glGetString(GL_RENDERER), (const char *)glGetString(GL_VERSION),
          G.track.n_tex, G.track.n_batch, G.track.n_chunk);
#endif
  return 0;
}

void app_touch(void *id, int phase, float x, float y) {
#ifdef __ANDROID__
  /* hud_init may have reset the runtime state since the last input tick. */
  hud_set_stick_center_mode(&G.hud, G.menu.stick_center_mode);
#endif
  if (phase == TOUCH_CANCELLED) {
    /* A race capture can survive a transition to pause or menu. */
    hud_touch(&G.hud, id, phase, x, y);
    menu_touch(&G.menu, id, phase, x, y);
    return;
  }
  if (G.in_menu || G.paused || (G.menu.finish && phase == TOUCH_BEGAN)) {
    /* A finger may have pressed a race control before the menu opened. */
    if (phase == TOUCH_ENDED) hud_touch(&G.hud, id, TOUCH_CANCELLED, x, y);
    menu_touch(&G.menu, id, phase, x, y);
  } else
    hud_touch(&G.hud, id, phase, x, y); /* (over the result, letting go of the pedals) */
}

void app_tilt(float radians) { G.tilt = radians; }
int app_wants_tilt(void) { return G.menu.gyro == HUD_STEER_GYRO; }

/* the OPTION screen's steering for the race's keys: the tilt for a full lock, 50 degrees at
 * sensitivity 1 down to 15 at 10 */
static void hud_options(void) {
  for (int g = 0; g < HUD_KEY_GROUPS; ++g)
    hud_layout_set(g, G.menu.key_k[g]*0.01f, G.menu.key_dx[g], G.menu.key_dy[g]);
#ifdef __ANDROID__
  {
    const HudCustomLayout *c=&G.menu.custom_layout;
    const HudCustomTransform *t[4]={&c->map,&c->rank,&c->timer,&c->meter};
    hud_set_stick_deadzone_percent(c->stick_deadzone_percent);
    hud_shift_layout_set(c->shift_separate,c->shift.k*0.01f,c->shift.dx,c->shift.dy);
    hud_set_button_opacity_percent(c->button_opacity_percent);
    for (int i=0; i<HUD_CUSTOM_BUTTONS; ++i) {
      const HudCustomTransform *b = &c->button[i];
      hud_button_layout_set(HUD_EDIT_SHIFT_UP+i,c->separate_buttons & (1u << i),b->k*0.01f,b->dx,b->dy);
    }
    for (int g=0;g<HUD_RACE_GROUPS;++g) hud_race_layout_set(g,t[g]->k*0.01f,t[g]->dx,t[g]->dy);
  }
#endif
  hud_set_steer_mode(&G.hud, G.menu.gyro);
#ifdef __ANDROID__
  hud_set_stick_center_mode(&G.hud, G.menu.stick_center_mode);
#endif
  G.hud.slide = G.menu.pedal_slide;
  G.hud.tilt = G.tilt;
  G.hud.full = (50.0f - (float)(G.menu.gyro_sens - 1) * (35.0f / 9.0f)) * 0.0174533f;
}

void app_press_start(void) {
  if (G.in_menu) menu_start(&G.menu);
}

int app_movie(void) { return G.in_menu ? menu_movie(&G.menu) : -1; }

void app_movie_done(void) {
  /* A delayed platform completion is not a transition out of another menu. */
  if (G.in_menu && G.menu.screen == MENU_MOVIE) menu_movie_done(&G.menu);
}

static const char *ten_round_bgm(const menu_state *m, int round) {
#ifdef __ANDROID__
  /* Arcade getTenRoundBgm10 (0x857ec40), using the cue names from its stream table. */
  static const char *const regular[5][10] = {
    { "ten_d1", "ten_d2", "ten_d2", "ten_d3", "ten_d3",
      "ten_d4", "ten_d4", "ten_d5", "ten_d5", "ten_d6" },
    { "ten_e1", "ten_e2", "ten_e2", "ten_e3", "ten_e3",
      "ten_e4", "ten_e4", "ten_e5", "ten_e6", "ten_e7" },
    { "ten_a1", "ten_a2", "ten_a3", "ten_a4", "ten_a5",
      "ten_a6", "ten_a7", "ten_a8", "ten_a8", "ten_a9" },
    { "ten_b1", "ten_b2", "ten_b3", "ten_b4", "ten_b5",
      "ten_b6", "ten_b6", "ten_b7", "ten_b7", "ten_b8" },
    { "ten_c1", "ten_c2", "ten_c3", "ten_c4", "ten_c5",
      "ten_c6", "ten_c6", "ten_c7", "ten_c7", "ten_c8" }
  };
  if (m->ten_level < 0 || m->ten_level > 10 || round < 0) return NULL;
  if (m->ten_level < 10) return round < 10 ? regular[m->ten_level % 5][round] : NULL;
  /* Arcade getTenRoundBgmExtend (0x857ec5c): soundtrack from the card, an optional
   * alternative selected once at the boundary, and no change between listed rounds. */
  static const struct {
    int round;
    const char *track[3][2];
  } extended[] = {
    {  0, {{ "wm3DX_P_race_02" },             { "wm2_01", "wm2_02" }, { "wmr_01" }} },
    {  2, {{ "wm3DX_P_race_03" },             { "wm2_03", "wm2_04" }, { "wmr_02" }} },
    {  5, {{ "wm3_12" },                      { "wm2_06", "wm2_09" }, { "wmr_05" }} },
    {  8, {{ "wm3DX_P_race_04" },             { "wm2_11" },           { "wmr_08" }} },
    { 11, {{ "wm3_10", "wm3_11" },            { "wm2_14" },           { "wmr_09" }} },
    { 14, {{ "wm3_04" },                      { "wm2_05", "wm2_08" }, { "wmr_01" }} },
    { 17, {{ "wm3_08" },                      { "wm2_10", "wm2_17" }, { "wmr_06" }} },
    { 20, {{ "wm3DX_P_race_01" },             { "wm2_07", "wm2_16" }, { "wmr_04" }} },
    { 23, {{ "wm3_05", "wm3_06" },            { "wm2_12", "wm2_15" }, { "wmr_03" }} },
    { 26, {{ "wm3_09" },                      { "wm2_13" },           { "wmr_07" }} },
    { 29, {{ "wm3_13" },                      { "wm2_18", "wm2_19" }, { "wmr_10" }} },
    { 30, {{ "wm3_14" },                      { "wm2_20", "wm2_22" }, { "wmr_11" }} },
    { 31, {{ "wm3_15" },                      { "wm2_21", "wm2_23" }, { "wmr_12" }} }
  };
  for (size_t i = 0; i < sizeof extended / sizeof extended[0]; ++i) {
    if (round != extended[i].round) continue;
    const char *const *tracks = extended[i].track[menu_card_bgm_source(m)];
    return tracks[tracks[1] ? rand() % 2 : 0];
  }
#else
  /* The original Ten WAV bank is installed by the Android launcher. */
  (void)m;
  (void)round;
#endif
  return NULL;
}

static int ten_bgm_active(void) {
  return !G.in_menu && G.n_ten && !G.menu.finish && !G.ten_bgm_off && G.ten_bgm;
}

const char *app_bgm(void) {
  /* The last rival stops the stream immediately; result2 still plays 0x6d. */
  if (!G.in_menu && G.ten_bgm_off && !G.menu.finish) return NULL;
  if (ten_bgm_active()) {
    /* If Android rejected an optional soundtrack, recover the same Extend
     * cue slot with the default soundtrack before the next rival appears. */
    if (G.menu.ten_level == 10 && G.ten_bgm[0] == 'w' && (G.ten_bgm[2] == '2' || G.ten_bgm[2] == 'r') &&
        menu_card_bgm_source(&G.menu) == 0) {
      const char *cue = ten_round_bgm(&G.menu, G.ten_bgm_round);
      if (cue) G.ten_bgm = cue;
    }
    return G.ten_bgm;
  }
  return menu_bgm(&G.menu, !G.in_menu);
}

const char *app_bgm_fallback(void) {
  return ten_bgm_active() ? menu_bgm(&G.menu, 1) : NULL;
}

int app_bgm_crossfade_ms(void) {
  if (!ten_bgm_active() || G.ten_rival_on <= 0) return 0;
  /* clRaceThread::changeTenRival (0x890f6e4): 120 or 1 audio updates at 60 Hz. */
  return G.menu.ten_level == 10 ? 17 : 2000;
}

int app_bgm_gameplay_paused(void) {
  return !G.in_menu && !G.menu.finish && !G.vs_race && !G.n_ten &&
         G.menu.game == MENU_GAME_STORY && G.story_end_freeze > 0;
}

/* clRaceThread::race's 10-in-a-row white (clFader): white at once as the race starts and after
 * a beaten rival's still (the "ホワイトアウト", while the next rival loads), then 6 frames on
 * the white-in fades it over 0.5 s (setFade(0, 1, 0.5): 30 frames). The alpha of the white. */
#define TEN_WHITE_HOLD 6
#define TEN_WHITE_FADE 30
static float ten_white_alpha(void) {
  if (!G.ten_white) return 0.0f;
  int t = G.ten_white - 1 - TEN_WHITE_HOLD;
  return t <= 0 ? 1.0f : 1.0f - (float)t / TEN_WHITE_FADE;
}

/* ---- Loading: the course and the car models go up to GL, and are first drawn once (the
 * driver finishes a texture's upload on its first use: wpk_prewarm), while the menus run.
 * A thread of its own does it when main.m starts one (app_loader: a GL context sharing the
 * app's, on the A5X's second core), else the menu frames in their spare time (load_step).
 * What it works on (pack_state, the course's upload and warming) belongs to whoever loads:
 * the menus pause the thread (load_pause) before they touch any of it themselves, and see
 * what is loaded through a copy they take each frame (load_sync). */

/* A car model of the car select once it is in GL (NULL while it is still loading; the
 * FD3S stands in for a missing file). */
static wpk_scene *car_pack(int k) {
  if (k < 0 || k >= NPACKS || G.seen.pack[k] < 0) return &G.fd3s;
  return G.seen.pack[k] == 1 ? &G.packs[k] : NULL;
}

/* Tell the menus what is loaded (they see it at their next load_sync): GL is done with it
 * first, as a second context must not use what it has not finished. */
static void pack_set(int k, int state) {
#ifdef WMMT_NATIVE_VK
  if (state == 1 && !cinder_vk_finish()) return;
#else
  if (state == 1) glFinish();
#endif
  G.pack_state[k] = (signed char)state;
  pthread_mutex_lock(&G.load_mx);
  G.pub.pack[k] = (signed char)(state == 1 || state == -1 ? state : 0);
  pthread_mutex_unlock(&G.load_mx);
}
static void track_set(int state) {
#ifdef WMMT_NATIVE_VK
  if (state && !cinder_vk_finish()) return;
#else
  if (state) glFinish();
#endif
  G.track_ready = state;
  if (!state) G.start_ready = 0;
  pthread_mutex_lock(&G.load_mx);
  G.pub.track = state;
  G.pub.start = G.start_ready;
  pthread_mutex_unlock(&G.load_mx);
}
static void start_set(int course1) {
#ifdef WMMT_NATIVE_VK
  if (!cinder_vk_finish()) return;
#else
  glFinish();
#endif
  G.start_ready = course1;
  pthread_mutex_lock(&G.load_mx);
  G.pub.start = course1;
  pthread_mutex_unlock(&G.load_mx);
}

/* The menus take the loading's news, and hand it what they want next (w, or NULL to keep
 * the last); outside a race and while the app is up the thread may load. */
static void load_sync(const load_wants *w) {
  pthread_mutex_lock(&G.load_mx);
  G.seen = G.pub;
  if (w) G.wants = *w;
  G.loader |= G.loader_up; /* the frames stop loading before the thread starts */
  G.load_run = G.loader && G.in_menu && !G.away;
  G.load_idle = 0;
  pthread_cond_broadcast(&G.load_cv);
  pthread_mutex_unlock(&G.load_mx);
}

/* Stop the thread after the step it is in (a texture or a few first draws): the loading
 * state is the menus' until their next load_sync. */
static void load_pause(void) {
  pthread_mutex_lock(&G.load_mx);
  G.load_run = 0;
  while (G.load_busy) pthread_cond_wait(&G.load_cv, &G.load_mx);
  pthread_mutex_unlock(&G.load_mx);
}

/* The loading's own framebuffer of one pixel, in each GL context (0 the app's, 1 the
 * thread's): it draws there, so the screen's is done with by then (no second pass over it
 * on the tile GPU). */
#ifndef WMMT_NATIVE_VK
static GLuint load_fb(int ctx) {
  static GLuint fb[2];
  if (!fb[ctx]) {
    GLuint rb;
    glGenRenderbuffers(1, &rb);
    glBindRenderbuffer(GL_RENDERBUFFER, rb);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGB565, 1, 1);
    glGenFramebuffers(1, &fb[ctx]);
    glBindFramebuffer(GL_FRAMEBUFFER, fb[ctx]);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, rb);
  }
  return fb[ctx];
}
#endif

/* first draws per step (a car model's, the course's), and the bytes of the course a step
 * hands to GL: a step is a few ms at most, and each ends with a glFlush. A first draw cost
 * up to 20 ms on the iPad (push56, the driver's mipmaps); 12 of them in a step held the
 * menus' frames for 160 ms, the app's GL waiting for the thread's. */
#define WARM_STEP 1
#define WARM_STEP_COURSE 1
#define TRACK_STEP_BYTES (128 * 1024)

/* car model k's file in data_dir, without .wpk */
static const char *pack_name(int k) {
  static char name[2][128];
  static int i;
  i ^= 1;
  if (k < CARDB_NPACKS) snprintf(name[i], sizeof name[i], "cars/%s", CARDB_PACKS[k]);
  else snprintf(name[i], sizeof name[i], "chara/%s", RIVALDB_CHARA[k - CARDB_NPACKS]);
  return name[i];
}

/* One step of loading pack k: opening it, one texture or buffer of it, or first-drawing a
 * few of its batches (so its first turn on the carousel does not stall). */
static void pack_step(int k, int ctx) {
  wpk_scene *s = &G.packs[k];
  if (G.pack_state[k] == 0) {
    char path[1200];
    snprintf(path, sizeof path, "%s/%s.wpk", G.data_dir, pack_name(k));
    if (wpk_open(s, path) != 0) {
      fprintf(stderr, "no %s, the FD3S stands in\n", path);
      pack_set(k, -1);
      return;
    }
    s->two_sided = 1;
    s->skip_paints = 1; /* paint_step, for the car under the cursor */
    pack_set(k, 2);
  } else if (G.pack_state[k] == 2) {
    if (wpk_upload(s, 1)) pack_set(k, 3);
  } else if (G.pack_state[k] == 3) {
#ifndef WMMT_NATIVE_VK
    glBindFramebuffer(GL_FRAMEBUFFER, load_fb(ctx));
#endif
#ifdef WMMT_NATIVE_VK
    uint64_t epoch = cinder_vk_error_epoch();
#endif
    render_warm_begin();
#ifdef WMMT_NATIVE_VK
    if (!wpk_warm(s, WARM_STEP) && !cinder_vk_error_pending() && cinder_vk_error_epoch() == epoch) {
#else
    if (!wpk_warm(s, WARM_STEP)) {
#endif
      pack_set(k, 1);
      fprintf(stderr, "car model %s ready\n", pack_name(k));
    }
  }
}

static void paint_set(int k, int state) {
#ifdef WMMT_NATIVE_VK
  if (state == 1 && !cinder_vk_finish()) return;
#else
  if (state == 1) glFinish();
#endif
  G.paint_state[k] = (signed char)state;
  pthread_mutex_lock(&G.load_mx);
  G.pub.paint[k] = (signed char)(state == 1);
  pthread_mutex_unlock(&G.load_mx);
}

/* One step of loading the other paints of pack k (in GL already without them): one texture,
 * or first-drawing a few. A car's model is a third of its pack, its other paints the rest:
 * all 47 with all their paints did not fit with the course (iOS warned, and the car select
 * dropped the far makers' models and loaded them again and again). */
static void paint_step(int k, int ctx) {
  wpk_scene *s = &G.packs[k];
  if (G.paint_state[k] == 0 || G.paint_state[k] == 2) {
    if (G.paint_state[k] == 0) paint_set(k, 2);
    if (wpk_upload_paints(s, 1)) paint_set(k, 3);
  } else if (G.paint_state[k] == 3) {
#ifndef WMMT_NATIVE_VK
    glBindFramebuffer(GL_FRAMEBUFFER, load_fb(ctx));
#endif
#ifdef WMMT_NATIVE_VK
    uint64_t epoch = cinder_vk_error_epoch();
#endif
    render_warm_begin();
#ifdef WMMT_NATIVE_VK
    if (!wpk_warm_paints(s, WARM_STEP) && !cinder_vk_error_pending() && cinder_vk_error_epoch() == epoch) paint_set(k, 1);
#else
    if (!wpk_warm_paints(s, WARM_STEP)) paint_set(k, 1);
#endif
  }
}

/* In the menus, once the course and the car models are up: first-draw the map, so the race
 * does not stall on a texture's first use when the car comes fast into a new part of it.
 * First what the race's first frames draw (the sky, the traffic's models, the map and its
 * arrow boards in reach of w's course's start with the race's own warming margin: the
 * race's title page waits for that, start_set), then the rest, nearest that start first.
 * 0 once it all is. */
static int warm_step(const load_wants *w, int ctx) {
#ifndef WMMT_NATIVE_VK
  glBindFramebuffer(GL_FRAMEBUFFER, load_fb(ctx));
#else
  if (cinder_vk_error_pending()) return 1;
  uint64_t epoch = cinder_vk_error_epoch();
#endif
  render_warm_begin();
  const float *at = START[w->course];
  int n = lights_warm();
  if (!n) n = wpk_warm(&G.sky[G.track_zone], WARM_STEP_COURSE);
  for (int k = 0; !n && k < CAR_TRAFFIC_MODELS; ++k) n = wpk_warm(&G.traffic[k], WARM_STEP_COURSE);
  if (!n) n = wpk_warm_near(&G.track, at, WARM_MARGIN, WARM_STEP_COURSE, &G.rp);
  if (!n) n = wpk_warm_near(&G.arrows[G.track_zone], at, WARM_MARGIN, WARM_STEP_COURSE, &G.rp);
#ifdef WMMT_NATIVE_VK
  int start_candidate = !n && G.start_ready != w->course + 1;
#else
  if (!n && G.start_ready != w->course + 1) start_set(w->course + 1);
#endif
  if (!n) n = wpk_warm_near(&G.track, at, 0, WARM_STEP_COURSE, NULL);
  if (!n) n = wpk_warm_near(&G.arrows[G.track_zone], at, 0, WARM_STEP_COURSE, NULL);
#ifdef WMMT_NATIVE_VK
  if (cinder_vk_error_pending() || cinder_vk_error_epoch() != epoch) return 1;
  /* Near-scene readiness still does not require the far warm to finish. Defer
   * publication until this step's later warm calls cannot introduce an error. */
  if (start_candidate) start_set(w->course + 1);
  if (cinder_vk_error_pending() || cinder_vk_error_epoch() != epoch) return 1;
#endif
  return n;
}

static const cardb_color *chosen_color(void) {
  return &CARDB_CARS[G.menu.maker][G.menu.car].colors[G.menu.color];
}

/* The player's car in its aero set (cars/<pack>_aeroA..C.wpk, tools/stage/pack_cars.py
 * --aero), on the stock model's textures: loaded whole as a race starts (half a MB of
 * buffers), kept till another car or set is chosen. NULL: the stock model. */
static int aero_load(wpk_scene *s, int pack, int set) {
  wpk_scene *base = car_pack(pack);
  if (!set || !base || pack >= CARDB_NPACKS) return 0;
  char path[1200];
  snprintf(path, sizeof path, "%s/%s_aero%c.wpk", G.data_dir, pack_name(pack), 'A' + set - 1);
  if (wpk_open(s, path) != 0) {
    fprintf(stderr, "no %s\n", path);
    return 0;
  }
  s->two_sided = 1;
  wpk_share(s, base);
  wpk_upload(s, (size_t)-1);
  wpk_share_sync(s);
  wpk_warm(s, 1 << 20);
  return 1;
}

static wpk_scene *aero_model(int pack, int set) {
  if (set != G.aero_set || pack != G.aero_pack) {
    if (G.aero_set) { app_body_evict_scene(&G.aero); wpk_free(&G.aero); }
    G.aero_set = 0;
    if (!aero_load(&G.aero, pack, set)) return NULL;
    G.aero_pack = pack;
    G.aero_set = set;
  }
  return G.aero_set ? &G.aero : NULL;
}

/* the dress-up screens' aero cars: those the scene shows loaded (on the stock model, which
 * the scene keeps in), all freed once no scene shows one; NULL while one is not in */
static int menu_aero_find(int pack, int set) {
  for (int k = 0; k < MENU_AERO_SLOTS; ++k)
    if (G.menu_aero_in[k] && G.menu_aero_pack[k] == pack && G.menu_aero_set[k] == set) return k;
  return -1;
}

/* car pack `pack` in aero set `set` loaded into a free slot (if not in, and one is free) */
static void menu_aero_want(int pack, int set) {
  if (set < 1 || set > 3 || !car_pack(pack) || menu_aero_find(pack, set) >= 0) return;
  for (int k = 0; k < MENU_AERO_SLOTS; ++k)
    if (!G.menu_aero_in[k]) {
      G.menu_aero_pack[k] = pack, G.menu_aero_set[k] = set;
      G.menu_aero_in[k] = aero_load(&G.menu_aero[k], pack, set) ? 1 : -1;
      return;
    }
}

static void menu_aero_sync(const menu_scene *s) {
  int pack[MENU_AERO_SLOTS], set[MENU_AERO_SLOTS], n = 0;
  for (int i = 0; s && i < s->n; ++i) {
    int a = s->cars[i].aero, dup = 0;
    if (a < 1 || a > 3 || !car_pack(s->cars[i].pack)) continue;
    for (int j = 0; j < n; ++j) dup |= pack[j] == s->cars[i].pack && set[j] == a;
    if (!dup && n < MENU_AERO_SLOTS) pack[n] = s->cars[i].pack, set[n++] = a;
  }
  /* A prepared/active original Ghost owns its exact aero independently of the
   * player's menu scene; never trim it into a stock-body substitution. */
  int ghost_pack,ghost_set;
  if(app_ghost_arcade_aero(&ghost_pack,&ghost_set)) {
    int duplicate=0;for(int j=0;j<n;j++)duplicate|=pack[j]==ghost_pack&&set[j]==ghost_set;
    if(!duplicate&&n<MENU_AERO_SLOTS)pack[n]=ghost_pack,set[n++]=ghost_set;
  }
  /* those no longer shown let go, then those shown and not in loaded into the free slots */
  for (int k = 0; k < MENU_AERO_SLOTS; ++k) {
    int keep = 0;
    for (int j = 0; j < n; ++j) keep |= G.menu_aero_pack[k] == pack[j] && G.menu_aero_set[k] == set[j];
    if (G.menu_aero_in[k] && !keep) {
      if (G.menu_aero_in[k] == 1) { app_body_evict_scene(&G.menu_aero[k]); wpk_free(&G.menu_aero[k]); }
      G.menu_aero_in[k] = 0;
    }
  }
  for (int j = 0; j < n; ++j) menu_aero_want(pack[j], set[j]);
}

static wpk_scene *menu_aero(int pack, int set) {
  int k = menu_aero_find(pack, set);
  return k >= 0 && G.menu_aero_in[k] == 1 ? &G.menu_aero[k] : NULL;
}

/* Dress-up wheels (menu_state.wheel's value; wheels/<name>_<set>.wpk, tools/stage/
 * pack_cars.py --wheels, a few hundred KB each), WHEEL_SLOTS of them in GL, the one wanted
 * least lately let go for another. wheel_slot finds or opens one's slot (-1 for the car's
 * own, or no slot free of `keep`); wheel_load_step takes it a texture or buffer, then a
 * first draw, further (1 once ready). */
static int wheel_find(int wheel) {
  for (int k = 0; wheel && k < WHEEL_SLOTS; ++k)
    if (G.wheel_state[k] != WHEEL_FREE && G.wheel_id[k] == wheel) return k;
  return -1;
}

static int wheel_slot(int wheel, const int *keep, int n_keep) {
  int k = wheel_find(wheel), set;
  if (k >= 0 || !wheel) return k;
  const char *name = menu_wheel_pack(wheel, &set);
  if (!name) return -1;
  for (int i = 0; i < WHEEL_SLOTS; ++i) {
    int kept = G.wheel_state[i] != WHEEL_FREE && G.wheel_id[i] == G.wheel_shown;
    for (int j = 0; j < n_keep; ++j) kept |= G.wheel_state[i] != WHEEL_FREE && G.wheel_id[i] == keep[j];
    if (!kept && (k < 0 || G.wheel_state[i] == WHEEL_FREE || (G.wheel_state[k] != WHEEL_FREE && G.wheel_used[i] < G.wheel_used[k])))
      k = i;
  }
  if (k < 0) return -1;
  if (G.wheel_state[k] != WHEEL_FREE && G.wheel_state[k] != WHEEL_MISSING) wpk_free(&G.wheel[k]);
  char path[1200];
  if (wheel == MENU_WHEEL_LEMANS) {
#ifdef __ANDROID__
    extern int android_optional_resource_path(const char *, char *, size_t);
    if (!android_optional_resource_path("ghost-wheel-lman.wpk", path, sizeof path)) path[0] = 0;
#else
    snprintf(path, sizeof path, "%s/ghost-wheel-lman.wpk", G.data_dir);
#endif
  } else {
    snprintf(path, sizeof path, "%s/wheels/%s_%d.wpk", G.data_dir, name, set);
  }
  G.wheel_id[k] = wheel;
  G.wheel_state[k] = path[0] && wpk_open(&G.wheel[k], path) == 0 ? WHEEL_UP : WHEEL_MISSING;
  if (G.wheel_state[k] == WHEEL_MISSING && path[0]) fprintf(stderr, "no %s\n", path);
  return k;
}

static int wheel_load_step(int k) {
  if (G.wheel_state[k] == WHEEL_UP && wpk_upload(&G.wheel[k], 1)) G.wheel_state[k] = WHEEL_WARM;
  else if (G.wheel_state[k] == WHEEL_WARM) {
#ifndef WMMT_NATIVE_VK
    GLint screen_fb = 0;
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screen_fb);
    glBindFramebuffer(GL_FRAMEBUFFER, load_fb(0));
#endif
#ifdef WMMT_NATIVE_VK
    uint64_t epoch = cinder_vk_error_epoch();
#endif
    render_warm_begin();
#ifdef WMMT_NATIVE_VK
    int left = wpk_warm(&G.wheel[k], 1);
    if (!left && !cinder_vk_error_pending() && cinder_vk_error_epoch() == epoch) G.wheel_state[k] = WHEEL_READY;
#else
    if (!wpk_warm(&G.wheel[k], 1)) G.wheel_state[k] = WHEEL_READY;
    glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)screen_fb);
#endif
  }
  return G.wheel_state[k] == WHEEL_READY;
}

/* the wheel's model in GL, loaded whole now if it is not (the race's start); NULL for the
 * car's own or a missing file */
static wpk_scene *wheel_model(int wheel) {
  int k = wheel_slot(wheel, NULL, 0);
  if (k < 0) return NULL;
#ifdef WMMT_NATIVE_VK
  while (G.wheel_state[k] == WHEEL_UP || G.wheel_state[k] == WHEEL_WARM) {
    if (cinder_vk_error_pending()) return NULL;
    uint64_t epoch = cinder_vk_error_epoch();
    wheel_load_step(k);
    if (cinder_vk_error_epoch() != epoch || cinder_vk_error_pending()) return NULL;
  }
#else
  while (G.wheel_state[k] == WHEEL_UP || G.wheel_state[k] == WHEEL_WARM) wheel_load_step(k);
#endif
  G.wheel_used[k] = ++G.wheel_tick;
  return G.wheel_state[k] == WHEEL_READY ? &G.wheel[k] : NULL;
}

/* The menus' wheels: those of the cars on show, then those the screen may show next
 * (menu_wheel_next), get a slot; one step of loading a frame goes to the first not ready.
 * On the dress-up screens a car whose wheel is still loading shows the one shown before
 * (the change screen's cursor does not wait), or till there is none its own; elsewhere the
 * car's wheel loads whole at once, as before. */
#define WHEEL_WANTS 12
static void wheel_sync(menu_scene *shown) {
  int want[WHEEL_WANTS], n = 0;
  if (G.menu.screen != MENU_TG_WHEEL && G.menu.screen != MENU_TG_WEAR && G.menu.screen != MENU_TG_GET)
    for (int i = 0; shown && i < shown->n; ++i)
      if (shown->cars[i].wheel) wheel_model(shown->cars[i].wheel);
  for (int i = 0; shown && i < shown->n && n < WHEEL_WANTS; ++i)
    if (shown->cars[i].wheel) want[n++] = shown->cars[i].wheel;
  n += menu_wheel_next(&G.menu, want + n, WHEEL_WANTS - n);
  int stepped = 0, opened = 0;
  for (int i = 0; i < n; ++i) {
    int k = wheel_find(want[i]);
    if (k < 0 && !opened) k = wheel_slot(want[i], want, n), opened = 1; /* (a file a frame) */
    if (k < 0) continue;
    G.wheel_used[k] = ++G.wheel_tick;
    if (!stepped && G.wheel_state[k] != WHEEL_READY && G.wheel_state[k] != WHEEL_MISSING) {
      wheel_load_step(k);
      stepped = 1;
    }
  }
  for (int i = 0; shown && i < shown->n; ++i) {
    if (shown->cars[i].ghost_row || G.menu.screen==MENU_GHOST_PRE) continue;
    int w = shown->cars[i].wheel, k = wheel_find(w);
    if (!w || (k >= 0 && G.wheel_state[k] == WHEEL_READY)) G.wheel_shown = w;
    else if (wheel_find(G.wheel_shown) >= 0 && G.wheel_state[wheel_find(G.wheel_shown)] == WHEEL_READY) shown->cars[i].wheel = G.wheel_shown;
    else shown->cars[i].wheel = 0;
  }
}

/* A wheel's GET screen model (wheels/<menu3d>.wpk, pack_cars.py --wheels), in GL while the
 * screen is up (0: let it go). NULL if missing. */
static wpk_scene *get_wheel_model(int wheel) {
  if (wheel != G.get_wheel_id) {
    if (G.get_wheel_ok) wpk_free(&G.get_wheel);
    G.get_wheel_ok = 0;
    G.get_wheel_id = wheel;
    const char *name = menu_wheel_get(wheel);
    char path[1200];
    if (name) {
      snprintf(path, sizeof path, "%s/wheels/%s.wpk", G.data_dir, name);
      if (wpk_open(&G.get_wheel, path) != 0) {
        fprintf(stderr, "no %s\n", path);
      } else {
        wpk_upload(&G.get_wheel, (size_t)-1);
        wpk_warm(&G.get_wheel, 1 << 20);
        G.get_wheel_ok = 1;
      }
    }
  }
  return G.get_wheel_ok ? &G.get_wheel : NULL;
}

/* that wheel on a car of pack `pack` in aero set `aero` (src/carwheel.h), once in GL */
static void draw_wheels(int wheel, int pack, int aero, const mat4 *vp, const mat4 *model, const float *eye,
                        int pass, render_params *rp) {
  int k = wheel_find(wheel);
  if (k >= 0 && G.wheel_state[k] == WHEEL_READY && pack >= 0 && pack < CARDB_NPACKS && aero >= 0 && aero <= 3)
    wpk_draw_wheels(&G.wheel[k], vp, model, eye, pass, rp, CARWHEEL[pack][aero]);
}

/* the car wears that wheel: its WPK_CTIRE tyres show */
static int wheel_on(int wheel) {
  int k = wheel_find(wheel);
  return k >= 0 && G.wheel_state[k] == WHEEL_READY;
}

/* The car select's model of the rival's ECarType (its first colour): its tyres, and its
 * look when the rival's own model is missing; -1 for no rival. */
/* rival rows: RIVALDB's, then the 10-in-a-row's characters (TENDB_CHAR) after them;
 * TEN_FIRST stands for the chosen level's rivals (rival_rows) */
#define RACE_ROWS CAR_TEN_RIVALS
#define TEN_ROW(ch) (RIVALDB_N + (ch))
#define TEN_FIRST TEN_ROW(TENDB_NCHAR)
/* the 10-in-a-row's courses (clEffTenCourseType) by city, and the time attack's course of
 * each (its map name and city; the race's own start comes from GetTenFightRaceField) */
static const int TEN_CITY[10] = { CAR_TOKYO, CAR_TOKYO, CAR_TOKYO, CAR_TOKYO, CAR_TOKYO, CAR_TOKYO,
                                  CAR_NAGOYA, CAR_OSAKA, CAR_HAKONE, CAR_FUKUOKA };
static const int TEN_TA_COURSE[10] = { 0, 1, 2, 3, 4, 5, 6, 7, 9, 8 };
static int ten_ta_course(void) { return TEN_TA_COURSE[menu_ten_course(&G.menu)]; }

/* the race's rival: the story's chosen episode's (the rival select's story_pick) once on its
 * title page, else a test's (WMMT_RIVAL) or none */
static int story_rival(void) {
  if (G.menu.game == MENU_GAME_TEN && G.menu.screen == MENU_PRE) return TEN_FIRST;
  if (G.menu.game != MENU_GAME_STORY || (G.menu.screen != MENU_PRE && !G.menu.story_day_select) || G.menu.story_pick < 0) return G.rival_env;
  int pick = G.menu.story_pick;
#ifdef WMMT_EGL
  if (getenv("WMMT_STORY_SEL")) pick = atoi(getenv("WMMT_STORY_SEL")); /* test: this story select */
#endif
  for (int i = 0; i < RIVALDB_N; ++i)
    if (RIVALDB[i].select == pick && RIVALDB[i].race == (G.menu.story_day_select ? 0 : G.story_race) && RIVALDB[i].slot == 0) return i;
  return G.rival_env;
}

/* The rivals of the race whose first rival is RIVALDB row `first`: it and the rows after it
 * of the same select and race (clEffStoryType: up to 3 in a race). */
static int rival_rows(int first, int rows[RACE_ROWS]) {
  int n = 0;
  if (first == TEN_FIRST) { /* the 10-in-a-row level's (CharacterSet10) */
    int lv = G.menu.ten_level;
    for (int i = 0; i < TENDB_RIVALS[lv]; ++i) rows[n++] = TEN_ROW(TENDB_SET[lv][i]);
    return n;
  }
  for (int i = first; first >= 0 && i < RIVALDB_N && n < CAR_RIVALS; ++i) {
    if (RIVALDB[i].select != RIVALDB[first].select || RIVALDB[i].race != RIVALDB[first].race) break;
    rows[n++] = i;
  }
  return n;
}

/* The select's next race after `race` (-1 none): its first rival's RIVALDB row. */
static int story_next_race(int select, int race) {
  for (int i = 0; i < RIVALDB_N; ++i)
    if (RIVALDB[i].select == select && RIVALDB[i].race == race + 1 && RIVALDB[i].slot == 0) return i;
  return -1;
}

/* A winning intermediate story period is not the episode's final result.
 * Do not queue its Win dialogue before the continuous next period. */
static int story_period_suspend(void) {
  return !G.vs_race && !G.n_ten && G.movie_len <= 0 && G.menu.game == MENU_GAME_STORY &&
         G.rival >= 0 && G.rival < RIVALDB_N && G.car.race.over && G.car.race.won &&
         G.car.race.play_state == 10 && RIVALDB[G.rival].select == G.menu.story_pick &&
         story_next_race(G.menu.story_pick, G.story_race) >= 0;
}

/* Story carryover is a volatile one-attempt capability, not a save file.
 * The physics adapter owns its memory and validates all restored identities. */
static void story_carry_cancel(void) {
  car_story_carry_cancel();
  G.story_carry_token = 0;
}
static int story_carry_capture(void) {
  if (G.story_carry_attempted || G.story_old_ended || !story_period_suspend()) return 0;
  int select = G.menu.story_pick;
  int next = story_next_race(select, G.story_race);
  G.story_carry_attempted = 1;
  /* rival_look can skip rows. Never label a compressed different rival slot 0. */
  if (!G.story_race_slots_valid || G.race_nrv <= 0 || G.race_rv[0].character != RIVALDB[G.rival].character ||
      G.race_rv[0].type != (unsigned)RIVALDB[G.rival].type ||
      G.race_rv[0].series != RIVALDB[G.rival].series) {
    story_carry_cancel();
    return 0;
  }
  uint64_t token = ++G.story_carry_serial;
  if (!token) token = ++G.story_carry_serial;
  int captured = car_story_carry_capture(token, RIVALDB[G.rival].series);
  if (captured < 0) { story_carry_cancel(); return 0; } /* End did not run */
  /* Both successful and failed captures have already torn down old CSeq. */
  G.story_old_ended = 1;
  if (!captured) { story_carry_cancel(); return 1; }
  G.story_carry_token = token;
  G.story_carry_select = select;
  G.story_carry_period = G.story_race + 1;
  G.story_carry_series = RIVALDB[next].series;
  return 1;
}
static void story_carry_arm(const car_rival *rv, int n) {
  if (!G.story_carry_token) return;
  int ok = G.menu.game == MENU_GAME_STORY && G.menu.pre_quiet && G.story_cut_pending &&
           G.menu.story_pick == G.story_carry_select && G.story_race == G.story_carry_period &&
           G.rival >= 0 && G.rival < RIVALDB_N && RIVALDB[G.rival].slot == 0 &&
           RIVALDB[G.rival].select == G.story_carry_select && RIVALDB[G.rival].series == G.story_carry_series &&
           n > 0 && rv && rv[0].character == RIVALDB[G.rival].character &&
           rv[0].type == (unsigned)RIVALDB[G.rival].type && rv[0].series == G.story_carry_series;
  if (!ok || !car_story_carry_arm(G.story_carry_token, G.story_carry_series)) story_carry_cancel();
}
static void story_carry_rearm(void) {
  if (G.story_carry_token && !car_story_carry_arm(G.story_carry_token, G.story_carry_series))
    story_carry_cancel();
}
static void story_carry_finish(void) {
  uint64_t token = G.story_carry_token;
  int carried = token && car_story_carry_loaded(token) && car_story_carry_finalize(token);
  if (token && !carried) car_story_carry_cancel();
  G.story_carry_token = 0;
  /* Original Init includes the carried distance in the next result by
   * subtracting it from fStartOdo (0x8987dd8). Only account separately for
   * a completed period when the port fell back to starting from scratch. */
  if (!carried) G.story_mileage_unrestored_mm += G.story_mileage_pending_mm;
  G.story_mileage_pending_mm = 0.0f;
}

static int rival_type(int rival) {
  return rival >= TEN_ROW(0) ? TENDB_CHAR[rival - TEN_ROW(0)].type : RIVALDB[rival].type;
}

static int rival_base(int rival, int *paint) {
  *paint = 0;
  if (rival < 0 || rival >= TEN_ROW(TENDB_NCHAR)) return -1;
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int i = 0; i < CARDB_NCARS[mk]; ++i)
      for (int j = 0; j < CARDB_CARS[mk][i].ncolors; ++j)
        if (CARDB_CARS[mk][i].colors[j].type == rival_type(rival)) {
          *paint = CARDB_CARS[mk][i].colors[j].paint;
          return CARDB_CARS[mk][i].colors[j].pack;
        }
  return -1;
}

/* The rival's look: its own model (data/chara), else rival_base's; -1 for no rival. */
static int rival_look(int rival, int *paint) {
  int base = rival_base(rival, paint);
  int chara = rival >= TEN_ROW(0) ? TENDB_CHAR[rival - TEN_ROW(0)].chara : RIVALDB[rival].chara;
  if (base < 0 || chara < 0) return base;
  *paint = 0;
  return CARDB_NPACKS + chara;
}

/* What the menus want loaded: the car models, most wanted first. The cars on screen, then
 * the makers up to half the list away from the one on show (or under the maker select's
 * cursor), nearest first, each its carousel (every car's first colour) before its other
 * colours; after a memory warning no further than its neighbours. Up to the car select's
 * end (the attract loop and the boot logos included) the cars on screen and the maker on
 * show come before the course (`first` of them), so that the car select finds them in; in
 * the car select the other models come before warming the course too. */
static void load_wants_now(const menu_scene *shown, load_wants *w) {
  unsigned char listed[NPACKS] = { 0 };
  w->n = 0;
  /* the OPTION screen loads as the screen it came from, the save screens as the maker select ahead */
  int ahead = G.menu.screen == MENU_SAVE || G.menu.screen == MENU_HAVE || G.menu.screen == MENU_NAME ||
              (G.menu.screen == MENU_OPTION && G.menu.opt_from == MENU_SAVE);
  int screen = G.menu.screen == MENU_OPTION || ahead ? MENU_MAKER : G.menu.screen;
  int sel = ahead ? G.menu.maker : G.menu.screen == MENU_OPTION ? G.menu.opt_sel : G.menu.sel;
#define WANT(k)                                                     \
  if ((k) >= 0 && (k) < NPACKS && !listed[k]) {               \
    listed[k] = 1;                                                  \
    w->order[w->n++] = (k);                                         \
  }
  for (int i = 0; shown && i < shown->n; ++i) WANT(shown->cars[i].pack);
  /* a save picked (HAVE, its GARAGE): its cars next, the one on view first, before the
   * course (a blank garage waited for the whole course, Allan 10-25) */
  int owned = G.menu.screen == MENU_HAVE || G.menu.screen == MENU_GARAGE;
  /* (after a memory warning only the one on view: the others were freed again at once) */
  for (int i = 0; owned && i < (G.low_memory ? 1 : G.menu.n_own); ++i) {
    int k = (i + (G.menu.own_view > 0 ? G.menu.own_view : 0)) % G.menu.n_own;
    const menu_own *o = &G.menu.own[k];
    if (o->maker >= 0 && o->maker < CARDB_ALL && o->car >= 0 && o->car < CARDB_NCARS[o->maker])
      WANT(CARDB_CARS[o->maker][o->car].colors[o->color].pack);
  }
  int n_owned = w->n;
  /* past the car select the chosen car comes first, its paint too (the race title waits for it) */
  int chosen = screen > MENU_COLOR ? chosen_color()->pack : -1;
  int before = w->n;
  WANT(chosen);
  int rows[RACE_ROWS], n_rival = chosen >= 0 ? rival_rows(G.rival, rows) : 0;
  int rival_paint[RACE_ROWS], rival[RACE_ROWS];
  for (int i = 0; i < n_rival; ++i) {
    rival[i] = rival_look(rows[i], &rival_paint[i]);
    WANT(rival[i]);
  }
  int ghost_paint = 0, ghost_pack = app_ghost_rival_pack(&ghost_paint);
  WANT(ghost_pack);
  int race_cars = w->n - before;
  /* the phone: only the maker on show, each car in its first paint */
  int reach = G.phone ? 0 : G.low_memory ? 1 : CARDB_MAKERS / 2, first = 0;
  int on_show = screen == MENU_MAKER ? sel : G.menu.maker;
  /* the hidden cars' page: its cars alone */
  if (on_show == CARDB_HIDDEN) {
    for (int all = 0; all < (G.phone ? 1 : 2); ++all)
      for (int i = 0; i < CARDB_NCARS[CARDB_HIDDEN]; ++i) {
        const cardb_car *c = &CARDB_CARS[CARDB_HIDDEN][i];
        for (int j = 0; j < (all ? c->ncolors : 1); ++j) WANT(c->colors[j].pack);
      }
    first = w->n;
    reach = -1;
  }
  for (int d = 0; d <= reach; ++d) {
    for (int sign = 1; sign >= -1; sign -= 2) {
      int maker = ((on_show + sign * d) % CARDB_MAKERS + CARDB_MAKERS) % CARDB_MAKERS;
      for (int all = 0; all < (G.phone ? 1 : 2); ++all)
        for (int i = 0; i < CARDB_NCARS[maker]; ++i) {
          const cardb_car *c = &CARDB_CARS[maker][i];
          for (int j = 0; j < (all ? c->ncolors : 1); ++j) WANT(c->colors[j].pack);
        }
    }
    if (d == 0) first = w->n;
  }
#undef WANT
  /* past the car select the cars on screen too (the garage's saved car: a count of the
   * race's cars alone left it behind the whole course, the phone's push108, the iPad's push118) */
  w->first = owned ? n_owned : screen <= MENU_COLOR ? first : before + race_cars;
  /* the boot's screens too: warming the course first (a minute of it) left the car select
   * of a maker not yet in waiting on its whole carousel the first time (push116) */
  w->cars_before_warm = screen <= MENU_COLOR;
  /* the other paints of the car under the cursor (the colour select's), or of the car chosen */
  w->n_paints = 0;
  int car = screen == MENU_CAR ? sel : G.menu.car;
  if (screen >= MENU_CAR && car >= 0 && car < CARDB_NCARS[G.menu.maker]) {
    const cardb_car *c = &CARDB_CARS[G.menu.maker][car];
    for (int j = 0; j < c->ncolors; ++j) {
      int k = c->colors[j].pack, dup = 0;
      for (int i = 0; i < w->n_paints; ++i) dup |= w->paints[i] == k;
      if (!dup && k >= 0 && k < NPACKS) w->paints[w->n_paints++] = k;
    }
  }
  if (chosen >= 0) {
    w->n_paints = 0;
    if (chosen_color()->paint) w->paints[w->n_paints++] = chosen;
    if (ghost_pack >= 0 && ghost_paint && ghost_pack != chosen) w->paints[w->n_paints++] = ghost_pack;
    for (int i = 0; i < n_rival; ++i) {
      int dup = rival[i] < 0 || !rival_paint[i] || rival[i] == chosen;
      for (int j = 0; j < w->n_paints; ++j) dup |= w->paints[j] == rival[i];
      if (!dup) w->paints[w->n_paints++] = rival[i];
    }
  }
  /* and the paints of the cars on show (the save's car in GARAGE: not the chosen one, so
   * car_paints_trim freed its paint again and again, NOW LOADING for minutes, Allan 10-25) */
  for (int i = 0; shown && i < shown->n; ++i) {
    int k = shown->cars[i].pack, dup = !shown->cars[i].paint || k < 0 || k >= NPACKS;
    for (int j = 0; j < w->n_paints; ++j) dup |= w->paints[j] == k;
    if (!dup && w->n_paints < (int)(sizeof w->paints / sizeof w->paints[0])) w->paints[w->n_paints++] = k;
  }
  w->paints_first = screen <= MENU_COLOR || chosen >= 0;
  w->hold_track = G.track_old.n_batch || G.track_old.n_tex;
  w->course = G.menu.course >= 0 && G.menu.course < CAR_COURSES ? G.menu.course : 0;
}

/* the first of w's paints to load whose model is in GL, or -1 */
static int paint_next(const load_wants *w) {
  for (int i = 0; i < w->n_paints; ++i) {
    int k = w->paints[i];
    if (G.pack_state[k] == 1 && G.paint_state[k] != 1) return k;
  }
  return -1;
}

/* the first of w's car models from..to that is still to load, or -1 */
static int want_next(const load_wants *w, int from, int to) {
  for (int i = from; i < to; ++i) {
    int k = w->order[i];
    if (G.pack_state[k] != 1 && G.pack_state[k] != -1) return k;
  }
  return -1;
}

/* One step of the loading, in GL context ctx: the cars w wants first, then the course (the
 * race needs it), then the other cars before or after warming the course (load_wants_now).
 * 0 when there is nothing left to do. */
static int load_unit(const load_wants *w, int ctx) {
  int k = want_next(w, 0, w->first);
  if (k >= 0) {
    pack_step(k, ctx);
    return 1;
  }
  k = paint_next(w);
  if (k >= 0 && w->paints_first) {
    paint_step(k, ctx);
    return 1;
  }
  if (!G.track_ready && !w->hold_track) {
    if (wpk_upload(&G.track, TRACK_STEP_BYTES)) {
      track_set(1);
      fprintf(stderr, "course ready\n");
    }
    return 1;
  }
  k = want_next(w, 0, w->n);
  if (k >= 0 && w->cars_before_warm) {
    pack_step(k, ctx);
    return 1;
  }
  if (G.track_ready) {
    if (warm_step(w, ctx)) return 1;
    if (G.track_ready == 1) track_set(2); /* the race's title page waits for this */
  }
  if (k >= 0) {
    pack_step(k, ctx);
    return 1;
  }
  k = paint_next(w);
  if (k >= 0) {
    paint_step(k, ctx);
    return 1;
  }
  return 0;
}

/* all of pack k, in the app's context (the race's car, chosen before it was in), and its
 * other paints if `paints` */
static void pack_load_now(int k, int paints) {
  load_pause();
#ifdef WMMT_NATIVE_VK
  while (k >= 0 && k < NPACKS && G.pack_state[k] != 1 && G.pack_state[k] != -1) {
    if (cinder_vk_error_pending()) return;
    uint64_t epoch = cinder_vk_error_epoch();
    pack_step(k, 0);
    if (cinder_vk_error_epoch() != epoch || cinder_vk_error_pending()) return;
  }
  while (paints && k >= 0 && k < NPACKS && G.pack_state[k] == 1 && G.paint_state[k] != 1) {
    if (cinder_vk_error_pending()) return;
    uint64_t epoch = cinder_vk_error_epoch();
    paint_step(k, 0);
    if (cinder_vk_error_epoch() != epoch || cinder_vk_error_pending()) return;
  }
#else
  GLint screen_fb = 0;
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screen_fb);
  while (k >= 0 && k < NPACKS && G.pack_state[k] != 1 && G.pack_state[k] != -1) pack_step(k, 0);
  while (paints && k >= 0 && k < NPACKS && G.pack_state[k] == 1 && G.paint_state[k] != 1) paint_step(k, 0);
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)screen_fb);
#endif
}

/* whether car model k's paint is in GL as the menus see it (the FD3S standing in has all) */
static int paint_ready(int k, int paint) {
  if (!paint || k < 0 || k >= NPACKS || G.seen.pack[k] < 0) return 1;
  return G.seen.paint[k] == 1;
}

/* whether every car of a car select scene is in GL with its paint (menu_draw3d shows them all or none) */
static int scene_ready(const menu_scene *s) {
  for (int i = 0; s && i < s->n; ++i)
    if (!car_pack(s->cars[i].pack) || !paint_ready(s->cars[i].pack, s->cars[i].paint)) return 0;
  return 1;
}

/* Free car models: all but the chosen car's (the race), or after a memory warning all
 * but the makers load_wants_now still wants and the cars it wants first (w: the cars on
 * show and the save's cars in GARAGE, of any maker; freed, they loaded again and again and
 * the garage stayed on NOW LOADING, Allan 10-25) */
static void car_packs_trim(int keep_near, const load_wants *w) {
  unsigned char want[NPACKS] = { 0 };
  want[chosen_color()->pack] = 1;
  for (int i = 0; w && i < w->first && i < w->n; ++i) want[w->order[i]] = 1;
  int rows[RACE_ROWS], n_rival = rival_rows(G.rival, rows);
  for (int i = 0; i < n_rival; ++i) {
    int paint, rival = rival_look(rows[i], &paint);
    if (rival >= 0) want[rival] = 1;
  }
  for (int i = 0; (G.vs_race || app_ghost_mode()) && i < G.n_rival; ++i) want[G.rival_pack[i]] = 1;
  for (int d = G.phone ? 0 : -1; keep_near && d <= (G.phone ? 0 : 1); ++d) {
    int maker = ((G.menu.maker + d) % CARDB_MAKERS + CARDB_MAKERS) % CARDB_MAKERS;
    if (G.menu.maker == CARDB_HIDDEN) {
      if (d) continue;
      maker = CARDB_HIDDEN;
    }
    for (int i = 0; i < CARDB_NCARS[maker]; ++i) {
      const cardb_car *c = &CARDB_CARS[maker][i];
      for (int j = 0; j < c->ncolors; ++j) want[c->colors[j].pack] = 1;
    }
  }
  /* (a look at the thread's state first, so that nothing pauses it when nothing goes) */
  int any = 0;
  for (int k = 0; k < NPACKS; ++k) any |= G.pack_state[k] > 0 && !want[k];
  if (!any) return;
  load_pause();
  for (int k = 0; k < NPACKS; ++k)
    if (G.pack_state[k] > 0 && !want[k]) {
      app_body_evict_pack(k); /* only caches borrowing the evicted pack */
      wpk_free(&G.packs[k]);
      pack_set(k, 0);
      paint_set(k, 0);
    }
  load_sync(NULL);
}

/* Free the other paints of all car models but the chosen car's and those w wants (NULL:
 * none), once more than a few cars have theirs: the car select's cursor goes past many. */
#define PAINTED_MAX 4
static void car_paints_trim(const load_wants *w, int force) {
  unsigned char keep[NPACKS] = { 0 };
  keep[chosen_color()->pack] = 1;
  int rows[RACE_ROWS], n_rival = rival_rows(G.rival, rows);
  for (int i = 0; i < n_rival; ++i) {
    int paint, rival = rival_look(rows[i], &paint);
    if (rival >= 0) keep[rival] = 1;
  }
  for (int i = 0; (G.vs_race || app_ghost_mode()) && i < G.n_rival; ++i) keep[G.rival_pack[i]] = 1;
  for (int i = 0; w && i < w->n_paints; ++i) keep[w->paints[i]] = 1;
  int painted = 0, extra = 0;
  for (int k = 0; k < NPACKS; ++k) {
    painted += G.paint_state[k] != 0;
    extra += G.paint_state[k] != 0 && !keep[k];
  }
  if (!extra || (!force && painted <= PAINTED_MAX)) return;
  load_pause();
  for (int k = 0; k < NPACKS; ++k)
    if (G.paint_state[k] != 0 && !keep[k]) {
      if (G.pack_state[k] > 0) wpk_free_paints(&G.packs[k]);
      paint_set(k, 0);
    }
  load_sync(NULL);
}

void app_memory_warning(void) {
  fprintf(stderr, "memory warning: car models of far makers freed\n");
  perf_file();
  if (G.perf) {
    fprintf(G.perf, "memory warning on screen %d (%s), %.0f MB resident\n", G.menu.screen, G.in_menu ? "menus" : "race",
            resident_mb());
    fflush(G.perf);
  }
  G.low_memory = 1;
  if(G.in_menu)app_arcade_paint_drop(0);
  car_packs_trim(G.in_menu, G.in_menu ? &G.wants : NULL);
}

/* Spend what is left of this frame's loading time (no loading thread). More on the race's
 * title page, which is there for the loading, in the boot logos, which cannot be skipped
 * for it, and while the car select waits for its cars (it shows them all at once).
 * LOAD_MIN_MS of it at least, so loading always moves on. The driver does much of an
 * upload's work later (a texture's on its first use, the rest when the frame goes to the
 * GPU), so each step waits for it (glFinish) to count it: the steps then stop in time and
 * the menus keep their 60 fps. */
static void load_step(double frame_start) {
  double budget = G.load_hurry ? LOAD_PRE_MS : LOAD_MS;
#ifdef WMMT_NATIVE_VK
  if (cinder_vk_error_pending() || !cinder_vk_finish()) return;
  double t0 = now_ms();
  for (double t = t0; t - frame_start < budget || t - t0 < LOAD_MIN_MS; t = now_ms()) {
    if (cinder_vk_error_pending()) break;
    uint64_t epoch = cinder_vk_error_epoch();
    if (!load_unit(&G.wants, 0)) break;
    if (!cinder_vk_finish() || cinder_vk_error_pending() || cinder_vk_error_epoch() != epoch) break;
  }
#else
  GLint screen_fb = 0;
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screen_fb);
  glBindFramebuffer(GL_FRAMEBUFFER, load_fb(0));
  glFinish(); /* the menu's own frame */
  double t0 = now_ms();
  for (double t = t0; t - frame_start < budget || t - t0 < LOAD_MIN_MS; t = now_ms()) {
    if (!load_unit(&G.wants, 0)) break;
    glFinish();
  }
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)screen_fb);
#endif
}

/* The thread loads between frames: from the end of a menu frame (app_frame_done, after its
 * presentRenderbuffer) till LOAD_WINDOW_MS after the frame's start, the vsync being at 16.7;
 * more when the menus wait for it. Run alongside the frames, its uploads and first draws went
 * to the GPU and the driver in the middle of theirs, and the menus dropped most of their
 * frames while it warmed the course. */
#define LOAD_WINDOW_MS 13.5
#define LOAD_HURRY_MS 16.0
#define LOAD_LATE_MS 2.0 /* after a late frame */
/* the car select's NOW LOADING: the thread's least time after a frame, the menus at 30 fps
 * meanwhile (after a vsync wait in presentRenderbuffer it had 2 ms of each frame: four car
 * models in ten seconds) */
#define LOAD_WAIT_MS 20.0

void app_frame_done(double present_ms) {
  double t = now_ms();
  G.present_ms = present_ms;
  pthread_mutex_lock(&G.load_mx);
  double until = G.frame_start + (G.load_hurry ? LOAD_HURRY_MS : LOAD_WINDOW_MS);
  double least = t + (G.load_wait ? LOAD_WAIT_MS : LOAD_LATE_MS);
  G.load_until = until > least ? until : least;
  pthread_cond_broadcast(&G.load_cv);
  pthread_mutex_unlock(&G.load_mx);
}

void app_loader(void) {
#ifdef WMMT_NATIVE_VK
  if (!cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER)) return;
#endif
  pthread_mutex_lock(&G.load_mx);
  G.loader_up = 1;
  pthread_mutex_unlock(&G.load_mx);
  for (;;) {
    pthread_mutex_lock(&G.load_mx);
    G.load_busy = 0;
    pthread_cond_broadcast(&G.load_cv); /* load_pause waits for this */
    while (!G.load_run || G.load_idle || now_ms() >= G.load_until) pthread_cond_wait(&G.load_cv, &G.load_mx);
    G.load_busy = 1;
    load_wants w = G.wants;
    pthread_mutex_unlock(&G.load_mx);
    double t0 = now_ms();
#ifdef WMMT_NATIVE_VK
    int did = cinder_vk_error_pending() ? 0 : load_unit(&w, 1);
#else
    int did = load_unit(&w, 1);
#endif
    pthread_mutex_lock(&G.load_mx);
    int away = G.away;
    pthread_mutex_unlock(&G.load_mx);
#ifdef WMMT_NATIVE_VK
    int synced = away ? cinder_vk_finish() : cinder_vk_flush();
#else
    if (away) glFinish(); /* the app goes to the background: nothing of the thread's left in flight */
    else glFlush();       /* for the app's context, which may use what it made after a pause */
#endif
    pthread_mutex_lock(&G.load_mx);
    G.load_units++;
    G.load_ms += now_ms() - t0;
    if (!did) G.load_idle = 1;
#ifdef WMMT_NATIVE_VK
    if (!synced) G.load_idle = 1; /* unknown completion never becomes published readiness */
#endif
    pthread_mutex_unlock(&G.load_mx);
  }
}

/* Audio presentation follows native sequence lifetimes, never RPM/gear guesses.
 * A paused/suspended source is muted without restarting its continuous phase. */
static int app_rotary_sequence_live;
static void app_rotary_start(void) {
  snd_rev_start(G.car.se.rev_sequence);
  app_rotary_sequence_live = 1;
}
static void app_rotary_stop(void) {
  if (app_rotary_sequence_live) snd_rev_stop();
  app_rotary_sequence_live = 0;
}

void app_suspend(int away) {
  app_timing_reset();
#ifdef __ANDROID__
  timing60_sim_reset(&android_sim);
  player_smoke_reset();
  race_tail_reset(); /* no red bridge across a suspended/resumed frame interval */
#endif
  pthread_mutex_lock(&G.load_mx);
  G.away = away;
  pthread_mutex_unlock(&G.load_mx);
  if (!away) return;
  snd_rev_quiet(); /* fence gain before the platform's asynchronous audio pause */
  load_pause();
  /* offline races return under the pause menu */
  if (!G.in_menu && !G.paused && !G.hud.pause_disabled) G.hud.pause_pressed++;
#ifdef WMMT_NATIVE_VK
  if (!cinder_vk_finish()) fprintf(stderr, "native suspend: GPU completion unconfirmed\n");
#else
  glFinish(); /* none of the app's GL work left in flight in the background */
#endif
  if (G.perf) fflush(G.perf);
}

/* ---- the stickers (vinyls): clCarModelData::constructBody blends the car's vinyl onto its
 * paint's page 1 (nsTextureReplace::TextureReplace); here the same, a composite texture made
 * from data/vinyl/<car>.vpk (tools/stage/pack_vinyl.py) the first time a car is drawn with it,
 * the last few kept (the change screen goes back and forth) */
#define VINYL_KEEP 5 /* (a versus: up to four cars at once) */
static struct {
  int pack, body, paint, vinyl, cb, used;
  uint32_t tex; /* 0: the car has no such vinyl */
  char page1[48];
} VIN[VINYL_KEEP];
static int vin_clock;

/* the composite of car pack k (CARDB_PACKS) on body 0..3 in paint `paint` with sticker `vinyl`
 * (menu_state.vinyl's: VinylTexture's entry, 0 none), the bonnet (carbon past 1: page1_cb), and
 * the name of the texture it stands in for; 0 if none (or the car is still loading) */
static uint32_t vinyl_tex(int k, int body, int paint, int vinyl, int bonnet, const char **page1) {
  int cb = bonnet > 1;
  if (vinyl <= 0 || k < 0 || k >= CARDB_NPACKS) return 0;
  body &= 3;
  for (int i = 0; i < VINYL_KEEP; ++i)
    if (VIN[i].used && VIN[i].pack == k && VIN[i].body == body && VIN[i].paint == paint && VIN[i].vinyl == vinyl &&
        VIN[i].cb == cb) {
      VIN[i].used = ++vin_clock;
      *page1 = VIN[i].page1;
      return VIN[i].tex;
    }
  wpk_scene *stock = car_pack(k);
  if (!stock || (stock == &G.fd3s && !same_name("maz_FD3S", CARDB_PACKS[k]))) return 0;
  int slot = 0;
  for (int i = 1; i < VINYL_KEEP; ++i)
    if (VIN[i].used < VIN[slot].used) slot = i;
#ifdef WMMT_NATIVE_VK
  if (VIN[slot].tex) cinder_vk_texture_destroy(VIN[slot].tex);
#else
  if (VIN[slot].tex) glDeleteTextures(1, &VIN[slot].tex);
#endif
  memset(&VIN[slot], 0, sizeof VIN[slot]);
  VIN[slot].pack = k, VIN[slot].body = body, VIN[slot].paint = paint, VIN[slot].vinyl = vinyl, VIN[slot].cb = cb;
  VIN[slot].used = ++vin_clock;
  *page1 = VIN[slot].page1;
  char path[1200];
  snprintf(path, sizeof path, "%s/vinyl/%s.vpk", G.data_dir, CARDB_PACKS[k]);
  FILE *f = fopen(path, "rb");
  if (!f) return 0;
  unsigned char head[12 + 192 + 32];
  uint32_t n, np;
  if (fread(head, 1, sizeof head, f) != sizeof head || memcmp(head, "VPK1", 4) != 0) {
    fclose(f);
    return 0;
  }
  memcpy(&n, head + 4, 4);
  memcpy(&np, head + 8, 4);
  memcpy(VIN[slot].page1, head + 12 + 48 * body, 47);
  int works = paint >= 0 && paint < 32 ? head[12 + 192 + paint] : 1;
  /* the entry: the vinyl on this body, the works livery's of the paint's WorksIndex, the
   * carbon bonnet's if it has one */
  unsigned char e[12], best[12];
  int found = 0;
  for (uint32_t i = 0; i < n && fread(e, 1, 12, f) == 12; ++i) {
    if (e[0] != body || e[1] != vinyl || (e[2] && e[2] != works)) continue;
    if (e[3] == cb || !found) memcpy(best, e, 12), found = 1 + (e[3] == cb);
  }
  uint32_t plane, off_size[2];
  uLongf want = 0;
  unsigned char *z = NULL, *px = NULL;
  if (found) {
    memcpy(&plane, best + 8, 4);
    want = (uLongf)512 * 512 * (best[7] ? 1 : 4);
    if (plane < np && fseek(f, (long)(sizeof head + 12 * n + 8 * plane), SEEK_SET) == 0 && fread(off_size, 4, 2, f) == 2 &&
        (z = malloc(off_size[1])) && (px = malloc(want)) && fseek(f, (long)off_size[0], SEEK_SET) == 0 &&
        fread(z, 1, off_size[1], f) == off_size[1]) {
      uLongf got = want;
      if (uncompress(px, &got, z, off_size[1]) != Z_OK || got != want) found = 0;
    } else {
      found = 0;
    }
  }
  fclose(f);
  free(z);
  if (found) {
    char name[64];
    int idx = -1;
    if (paint > 0) {
      snprintf(name, sizeof name, "p%d:%s", paint, VIN[slot].page1);
      idx = wpk_find_texture(stock, name);
    }
    if (idx < 0) idx = wpk_find_texture(stock, VIN[slot].page1);
    double t0 = now_ms();
    VIN[slot].tex = wpk_texture_over(stock, idx, px, 512, 512, best[7] ? best + 4 : NULL);
    fprintf(stderr, "vinyl %d on %s body %d paint %d: %s, %.1f ms\n", vinyl, CARDB_PACKS[k], body, paint,
            VIN[slot].tex ? "made" : "failed", now_ms() - t0);
  }
  free(px);
  return VIN[slot].tex;
}

/* s (the car's stock or aero scene) drawn with composite `tex` for its texture page1: the
 * index swapped, its GL name before in *old (vinyl_off puts it back) */
static int vinyl_on(wpk_scene *s, uint32_t tex, const char *page1, uint32_t *old) {
  int i = tex && s ? wpk_find_texture(s, page1) : -1;
  if (i >= 0) *old = s->textures[i], s->textures[i] = tex;
  return i;
}
static void vinyl_off(wpk_scene *s, int i, uint32_t old) {
  if (i >= 0) s->textures[i] = old;
}

/* Paint immediately before each draw: scenes can be reused by cars of different colours.
 * Borrowed textures follow stock; independently owned aero paints need their own swaps.
 * Both operations only select loaded texture names, and vinyl must be applied afterwards. */
static void car_paint_for_draw(wpk_scene *stock, wpk_scene *aero, int paint) {
  if (stock) wpk_paint(stock, paint);
  if (aero && aero != stock) {
    wpk_paint(aero, paint);
    wpk_share_sync(aero);
  }
}

/* the car select's 3D cars, with the arcade's menu camera */
static void eye_in(const mat4 *m, const float *p, float *out);

#include "app_mileage_aura.inc"

static void app_ghost_preview_prepare(const menu_scene *shown);
static wpk_scene *app_ghost_preview_stock(const menu_car *car);
static int app_ghost_preview_apply(const menu_car *car,wpk_scene *scene,story_body_view *body,
                                   app_ghost_paint_scope *scope,app_player_paint_scope *local_scope);

static void menu_draw3d(void *ctx) {
  const menu_scene *s = ctx;
  float aspect = (float)G.fb_w / (float)G.fb_h;
  float fovy = 2.0f * atanf(tanf(s->fov_x * 0.5f) / (4.0f / 3.0f));
  mat4 proj = mat4_perspective(fovy, aspect, 5.0f, 20000.0f);
  const float up[3] = { 0, 1, 0 };
  mat4 view = mat4_look_at(s->eye, s->at, up);
  mat4 vp = mat4_mul(proj, view);
  render_params rp = { .fog_far = 2e6f, .fog_near = 1e6f, .range = { 1e9f, 1e9f, 1e9f } };
  set_car_light(&rp, menu_env_light(s->env), &view);
  /* all the cars at once, not each as it comes in (load_step hurries them meanwhile) */
  if (!s->cars[0].ghost_row && !scene_ready(s)) return;
  
#ifdef WMMT_NATIVE_VK
    render_scene_depth_clear();
#else
    glClear(GL_DEPTH_BUFFER_BIT);
#endif
  wpk_scene *scene[MENU_MAX_CARS], *stock[MENU_MAX_CARS];
  int aero[MENU_MAX_CARS];
  for (int i = 0; i < s->n; ++i) {
    const menu_car *car=&s->cars[i];
    aero[i] = car->aero;
    stock[i] = car->ghost_row ? app_ghost_preview_stock(car) : car_pack(car->pack);
    scene[i] = stock[i];
    if (scene[i] && aero[i]) {
      scene[i] = menu_aero(car->pack, aero[i]);
      /* An unready optional aero must not hide the actual opponent's body. */
      if (!scene[i] && (car->ghost_row ? G.menu.screen!=MENU_GHOST_PRE : G.menu.screen==MENU_GHOST_PRE))
        scene[i]=stock[i], aero[i]=0;
    }
  }
  /* clSpriteAnimeCPModel's own scene: the eye at (0, 0, 1000) on the origin, the frustum
   * (60 degrees across the 640-wide screen, 5 to 20000) on the axis through its dot */
  const float cp_eye[3] = { 0, 0, 1000.0f }, cp_at[3] = { 0, 0, 0 };
  mat4 cp_view = mat4_look_at(cp_eye, cp_at, up);
  render_begin(&rp);
  for (int pass = 0; pass < WPK_PASSES; ++pass) {
    render_blend_pass(pass == WPK_BLEND);
    for (int i = 0; i < s->n; ++i) {
      if (!scene[i]) continue;
      car_paint_for_draw(stock[i], scene[i], s->cars[i].paint);
      mat4 model;
      memcpy(model.m, s->cars[i].model, sizeof model.m);
      const float *e = s->eye;
      mat4 cvp = vp;
      if (s->cars[i].cp) {
        float h = tanf(s->cars[i].ghost_row ? s->fov_x*0.5f : 0.52359878f) / 64.0f;
        float x = s->cars[i].cp_x, y = s->cars[i].cp_y;
        float ew = G.edge / 1.6f; /* (a wide screen's sides) */
        cvp = mat4_mul(mat4_frustum((-x - ew) * h, (640.0f + ew - x) * h, (y - 480.0f) * h, y * h, 5.0f, 20000.0f), cp_view);
        e = cp_eye;
      }
      /* the eye in the car's frame (the model matrix a rotation, a scale and a translation) */
      const float *m = model.m;
      float k2 = m[0] * m[0] + m[1] * m[1] + m[2] * m[2];
      float d[3] = { e[0] - m[12], e[1] - m[13], e[2] - m[14] };
      float eye[3] = { (d[0] * m[0] + d[1] * m[1] + d[2] * m[2]) / k2, (d[0] * m[4] + d[1] * m[5] + d[2] * m[6]) / k2,
                       (d[0] * m[8] + d[1] * m[9] + d[2] * m[10]) / k2 };
      story_body_view story_view;
      int ghost_preview=s->cars[i].ghost_row;
      if (!ghost_preview && !menu_story_body_scene_view(&G.menu,&s->cars[i],&story_view)) continue;
      rp.mirror = s->cars[i].mirror, rp.wing = s->cars[i].wing, rp.bonnet = s->cars[i].bonnet;
      rp.wheel_custom = wheel_on(s->cars[i].wheel);
      rp.wheel_drop = s->cars[i].lift;
      /* the cars flying in: their corners' spin and steer (Battle_anm.igb's) */
      static const float still[4];
      rp.wheels = s->cars[i].turned ? (const float (*)[16])s->cars[i].tyre : NULL;
      rp.wheel_rot = still;
      rp.wheels_hub = s->cars[i].turned;
      const char *page1 = "";
      app_player_paint_scope body_scope={0};
      int custom=s->cars[i].body_color_valid && s->cars[i].body_color.custom_color;
      if (custom && !app_body_menu_apply(&s->cars[i],scene[i],&body_scope)) continue;
      app_ghost_paint_scope preview_scope={0};
      if (ghost_preview && !app_ghost_preview_apply(&s->cars[i],scene[i],&story_view,&preview_scope,&body_scope)) continue;
      uint32_t vt = (body_scope.cache || preview_scope.cache) ? 0 : vinyl_tex(s->cars[i].pack, aero[i], s->cars[i].paint, s->cars[i].vinyl, s->cars[i].bonnet, &page1), vold = 0;
      int vi = vinyl_on(scene[i], vt, page1, &vold);
      app_story_body_draw(scene[i],&cvp,&model,eye,pass,&rp,&story_view,s->cars[i].pack);
      vinyl_off(scene[i], vi, vold);
      if (body_scope.cache) app_player_paint_restore(&body_scope);
      if (preview_scope.cache) app_ghost_paint_restore(&preview_scope);
      draw_wheels(s->cars[i].wheel, s->cars[i].pack, aero[i], &cvp, &model, eye, pass, &rp);
      if (pass == WPK_BLEND) mileage_aura_draw(&s->cars[i], aero[i], &cvp, &model, e, &rp);
    }
    rp.wheels = NULL;
    rp.wheels_hub = 0;
    if (s->get_wheel && s->get_wheel == G.get_wheel_id && G.get_wheel_ok) {
      mat4 model;
      memcpy(model.m, s->wheel_model, sizeof model.m);
      float eye[3];
      eye_in(&model, s->eye, eye);
      rp.mirror = rp.wing = rp.bonnet = rp.wheel_custom = 0;
      wpk_draw(&G.get_wheel, &vp, &model, eye, pass, &rp);
    }
  }
  /* the under neons (clMenuCar::setMatrix: clNeon::setPosture with (0, -3.1, 0) under the
   * car's matrix) */
  for (int i = 0; i < s->n; ++i) {
    if (!scene[i] || !s->cars[i].neon) continue;
    mat4 model, nproj = proj, nview = view;
    memcpy(model.m, s->cars[i].model, sizeof model.m);
    for (int j = 0; j < 3; ++j) model.m[12 + j] -= 3.1f * model.m[4 + j];
    if (s->cars[i].cp) {
      float h = tanf(s->cars[i].ghost_row ? s->fov_x*0.5f : 0.52359878f) / 64.0f;
      float x = s->cars[i].cp_x, y = s->cars[i].cp_y;
      float ew = G.edge / 1.6f;
      nproj = mat4_frustum((-x - ew) * h, (640.0f + ew - x) * h, (y - 480.0f) * h, y * h, 5.0f, 20000.0f);
      nview = cp_view;
    }
    lights_draw_neon(&nproj, &nview, model.m, s->cars[i].pack, aero[i], s->cars[i].neon, &rp);
  }
  render_blend_pass(0);
}

/* clMiniatureCourse::update, each frame of a course select on one of Tokyo's cards (the
 * others show a picture, mapChange): the map, the roads and the card's marks; on another card
 * the camera and its aim move to the card's in 8 frames, a straight line ((8 - n) * 0.125 of
 * the way, from where the last card's were); the projection 30 degrees across (Tokyo's maps,
 * "sk"), 5 to 20000; the gradation and the run light (named *graShape, *runlightShape) drawn
 * without the depth test (init's node walk), the gradation's texture running by its
 * sequence, the run light's glow at its sequence's place (the shader turns it to the camera).
 * fade: the screen's, which the arcade lays over in black. */
#define MINI_MOVE 8

static void eye_in(const mat4 *m, const float *p, float *out);

static void mini_draw(void *ctx, float fade) {
  const menu_state *m = ctx;
  int card = m->sel;
  int ten = m->screen == MENU_TEN_COURSE, vs = m->screen == MENU_VS_AREA;
  if (vs) card = m->vs.item;
  if (!G.mini.n_batch || card < 0 || card >= (vs ? MINI_VS_CARDS : ten ? MINI_TEN_CARDS : MINI_TA_CARDS)) return;
  const mini_course *mc = vs ? &MINI_VS[card] : ten ? &MINI_TEN[card] : &MINI_TA[card];
  if (!mc->on) return;
  if (mc != G.mini_shown) {
    if (G.mini_shown) {
      memcpy(G.mini_from[0], G.mini_shown->eye, sizeof G.mini_from[0]);
      memcpy(G.mini_from[1], G.mini_shown->at, sizeof G.mini_from[1]);
      G.mini_move = MINI_MOVE;
    }
    G.mini_shown = mc;
  }
  float eye[3], at[3];
  float k = G.mini_move ? (float)(MINI_MOVE - G.mini_move) * 0.125f : 1.0f;
  for (int i = 0; i < 3; ++i) {
    eye[i] = G.mini_from[0][i] + (mc->eye[i] - G.mini_from[0][i]) * k;
    at[i] = G.mini_from[1][i] + (mc->at[i] - G.mini_from[1][i]) * k;
  }
  float aspect = (float)G.fb_w / (float)G.fb_h;
  float fovy = 2.0f * atanf(tanf(0.5236f * 0.5f) / (4.0f / 3.0f));
  mat4 proj = mat4_perspective(fovy, aspect, 5.0f, 20000.0f);
  const float up[3] = { 0, 1, 0 };
  mat4 view = mat4_look_at(eye, at, up);
  mat4 vp = mat4_mul(proj, view);
  mat4 ident = mat4_identity();
  /* the fade as fog: black by 1 - fade wherever it is */
  render_params rp = { .fog_far = 1e7f * fade, .fog_near = 1e7f * fade - 1e7f, .range = { 1e9f, 1e9f, 1e9f },
                       .object_visible = G.mini_visible, .n_objects = MINI_OBJECTS };
  
#ifdef WMMT_NATIVE_VK
    render_scene_depth_clear();
#else
    glClear(GL_DEPTH_BUFFER_BIT);
#endif
  render_begin(&rp);
  memset(G.mini_visible, 0, sizeof G.mini_visible);
  G.mini_visible[MINI_MAP] = G.mini_visible[MINI_COURSE] = G.mini_visible[mc->macula] = 1;
  for (int pass = 0; pass < WPK_PASSES; ++pass) {
    render_blend_pass(pass == WPK_BLEND);
    wpk_draw(&G.mini, &vp, &ident, eye, pass, &rp);
  }
  int f = G.mini_frame % MINI_FRAMES;
#ifdef WMMT_NATIVE_VK
  rp.no_depth_test = 1;
#else
  glDisable(GL_DEPTH_TEST);
#endif
  render_blend_pass(1);
  memset(G.mini_visible, 0, sizeof G.mini_visible);
  G.mini_visible[mc->gradation] = 1;
  rp.uv_shift[0] = mc->uv[f];
  wpk_draw(&G.mini, &vp, &ident, eye, WPK_BLEND, &rp);
  rp.uv_shift[0] = 0;
  G.mini_visible[mc->gradation] = 0;
  G.mini_visible[mc->runlight] = 1;
  /* facing the camera: the view's rows for its axes */
  mat4 bb = ident;
  for (int i = 0; i < 3; ++i) {
    bb.m[i] = view.m[4 * i];
    bb.m[4 + i] = view.m[4 * i + 1];
    bb.m[8 + i] = view.m[4 * i + 2];
    bb.m[12 + i] = mc->run[f][i];
  }
  float eye_bb[3];
  eye_in(&bb, eye, eye_bb);
  wpk_draw(&G.mini, &vp, &bb, eye_bb, WPK_BLEND, &rp);
  render_blend_pass(0);
#ifndef WMMT_NATIVE_VK
  glEnable(GL_DEPTH_TEST);
#endif
}

/* frames the race's title page waits for the loading at most (it should never take this
 * long: a way out should something never finish) */
#define PRE_WAIT_MAX (20 * 60)
#define HUD_WARM_STEP 4 /* HUD sprites first-drawn a frame on the title page */

/* clRaceThread::initStory: the select's realtime movie before this race (src/storymovie.h), on
 * the race's course, its cars the race's rivals by their ECarType; the race (set up already)
 * starts over once it is done (movie_close) */
#define MOVIE_FADE 20 /* clRaceThread::race's setFade: 1/3 s */
/* a getFade's colour (clFader::draw: 1 atract_p_black, 2 Full_white) as hud_fade's grey */
static float fade_grey(int fade) { return fade == 2 ? 1.0f : 0.0f; }
static void story_race_start_failed(void) {
  app_story_body_clear();
  app_rotary_stop();
  story_carry_cancel();
  G.story_old_ended = 1;
  G.story_cut_pending = 0;
  G.story_race = 0;
  G.movie_len = 0;
  G.menu.finish = G.menu.finish_story = 0;
  G.paused = 0;
  G.in_menu = 1;
  hud_init(&G.hud, G.hud.screen_w, G.hud.screen_h);
  menu_open(&G.menu);
}
static int movie_open(int select, int race, const int *rows, int n_rows) {
  const storymovie *mv = NULL;
  for (int i = 0; i < STORYMOVIE_N && !mv; ++i)
    if (STORYMOVIE[i].select == select && STORYMOVIE[i].race == race) mv = &STORYMOVIE[i];
  if (!mv || getenv("WMMT_NO_MOVIE")) return 0;
  car_rival cars[CAR_RIVALS];
  int used[RACE_ROWS] = { 0 };
  memset(cars, 0, sizeof cars);
  for (int k = 0; k < CAR_RIVALS; ++k) {
    G.movie_model[k] = NULL;
    G.movie_paint[k] = 0;G.movie_pack[k]=-1;
    cars[k].type = (unsigned)mv->cars[k];
    cars[k].spokes = 5;
    for (int i = 0; mv->cars[k] && i < n_rows && i < G.n_rival; ++i) {
      if (used[i] || RIVALDB[rows[i]].type != mv->cars[k]) continue;
      used[i] = 1;
      cars[k] = G.race_rv[i];
      G.movie_model[k] = G.rival_model[i];
      G.movie_paint[k] = G.rival_paint[i];G.movie_pack[k]=G.rival_pack[i];
      break;
    }
  }
  float len = car_movie_start(&G.car, mv->movie, &G.race_spec, cars, CAR_RIVALS);
  fprintf(stderr, "story movie %d (select %d race %d): %.0f frames\n", mv->movie, select, race, len);
  if (len <= 1.0f) { /* its trails missing: the race at once */
    car_movie_end();
    car_set_rivals(G.race_rv, G.race_nrv);
    story_carry_rearm();
    if (car_start(&G.car, G.race_course, G.menu.manual, &G.race_spec) != 0) {
      story_carry_cancel();
      return -1;
    }
    app_rotary_start(); /* missing movie trail: genuine replacement native Init */
    spark_reset(); backfire_reset();
#ifdef __ANDROID__
    player_tracks_reset();
#endif
    return 0;
  }
  G.movie_len = len;
  G.movie_frame = 0;
  G.movie_fade = mv->fade;
  G.movie_in = 0;
  car_movie_update(&G.car, 0);
  hud_demo_start(mv->demo);
  return 0;
}

/* the movie's end: the race from its start, out of the movie's fade */
static void movie_close(void) {
  if (G.movie_len <= 0) return; /* repeated close cannot initialize twice */
  car_movie_end();
  hud_demo_end();
  G.movie_len = 0;
  car_set_rivals(G.race_rv, G.race_nrv);
  story_carry_rearm();
  if (car_start(&G.car, G.race_course, G.menu.manual, &G.race_spec) != 0) {
    fprintf(stderr, "race after the movie failed to start\n");
    story_race_start_failed();
    return;
  }
  app_rotary_start(); /* movie ended: restart only after successful native Init */
  story_carry_finish();
  G.story_old_ended = 0;
  spark_reset(); backfire_reset();
#ifdef __ANDROID__
    player_tracks_reset();
#endif
  G.movie_in = G.movie_fade ? MOVIE_FADE : 0;
  G.race_frames = 0;
  G.time_shown = (int)G.car.race.time_left;
  G.top_kmh = 0;
}

/* WVS4 APP implementation; Parent supplies smoke teardown after its loader. */
#ifndef APP_VS4_TEARDOWN_EXTRA
#ifdef __ANDROID__
#define APP_VS4_TEARDOWN_EXTRA() player_smoke_reset()
#else
#define APP_VS4_TEARDOWN_EXTRA() ((void)0)
#endif
#endif
#include "app_vs4.inc"

/* A phone's wide menu (app_wide): the 1024x768 layout's 4:3 middle, its outermost columns
 * drawn out over the sides, darkening toward the screen's edges, for the black bars (and the
 * sprites' bits past the arcade's 640). Android's window is multisampled and so can't be
 * copied from: the two columns go by GLES3's blit, to the same place in a texture the screen's
 * size; the iPhone's (GLES2, its own framebuffer) copies them into a texture two wide. */
#ifdef __ANDROID__
#include <EGL/egl.h>
#endif
typedef void (*blit_fn)(GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLbitfield, GLenum);
static struct {
  blit_fn blit;
  GLuint prog, tex, fb;
  GLint u_tex, u_dy;
  int w, h, fmt, off;
} SIDES;

#ifdef WMMT_NATIVE_VK
#include "app_native_sides.inc"
#endif

#ifdef __ANDROID__
/* the texture (and its framebuffer) for the blit, in sized format fmt (0: RGB8, 1: RGBA8) */
static void sides_target(int fmt) {
#ifdef WMMT_NATIVE_VK
  if (SIDES.fb) cinder_vk_target_destroy(SIDES.fb);
  if (SIDES.tex) cinder_vk_texture_destroy(SIDES.tex);
  SIDES.fb = SIDES.tex = 0;
  SIDES.w = SIDES.h = 0; SIDES.fmt = fmt;
  const cinder_vk_sampler sampler = { .use_state=1,.min_filter=VK_FILTER_LINEAR,.mag_filter=VK_FILTER_LINEAR,
    .mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,.address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    .address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.anisotropy=1 };
  const cinder_vk_storage_desc storage = { .width=G.fb_w,.height=G.fb_h,.samples=1,
    .format=CINDER_VK_STORAGE_RGBA8,.transfer_dst=1,.sampler=sampler };
  uint32_t texture = cinder_vk_texture_storage(&storage);
  if (!texture) return;
  const cinder_vk_target_create_desc desc = { .color={CINDER_VK_IMAGE_TEXTURE,texture} };
  uint32_t target = cinder_vk_target_create(&desc);
  if (!target || !cinder_vk_target_ready(target)) {
    if (target) cinder_vk_target_destroy(target);
    cinder_vk_texture_destroy(texture);
    return;
  }
  SIDES.tex = texture; SIDES.fb = target;
  SIDES.w = G.fb_w; SIDES.h = G.fb_h;
#else
  if (SIDES.fb) glDeleteFramebuffers(1, &SIDES.fb);
  if (SIDES.tex) glDeleteTextures(1, &SIDES.tex);
  glGenTextures(1, &SIDES.tex);
  glBindTexture(GL_TEXTURE_2D, SIDES.tex);
  glTexImage2D(GL_TEXTURE_2D, 0, fmt ? 0x8058 /* RGBA8 */ : 0x8051 /* RGB8 */, G.fb_w, G.fb_h, 0, fmt ? GL_RGBA : GL_RGB,
               GL_UNSIGNED_BYTE, NULL);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glGenFramebuffers(1, &SIDES.fb);
  SIDES.w = G.fb_w, SIDES.h = G.fb_h, SIDES.fmt = fmt;
#endif
}

/* the two columns into the texture; 0 if the blit was refused */
static int sides_blit(GLint screen, int xl, int xr) {
#ifdef WMMT_NATIVE_VK
  (void)screen;
  return sides_native_copy(SIDES.fb, G.fb_w, G.fb_h, xl, xr);
#else
  while (glGetError() != GL_NO_ERROR) {}
  glBindFramebuffer(GL_FRAMEBUFFER, SIDES.fb);
  glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, SIDES.tex, 0);
  glBindFramebuffer(0x8CA8 /* READ_FRAMEBUFFER */, (GLuint)screen);
#ifdef WMMT_VK
  /* vkgl reads the screen upside down (Vulkan's rows from the top) and so asks Adreno 540's
   * Vulkan for a flipped copy, which gave the column's first row alone: the source flipped
   * here instead, vkgl's copy straight (the texture's rows then from the top: wide_sides'
   * v flipped) */
  SIDES.blit(xl, G.fb_h, xl + 1, 0, xl, 0, xl + 1, G.fb_h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
  SIDES.blit(xr, G.fb_h, xr + 1, 0, xr, 0, xr + 1, G.fb_h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
#else
  SIDES.blit(xl, 0, xl + 1, G.fb_h, xl, 0, xl + 1, G.fb_h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
  SIDES.blit(xr, 0, xr + 1, G.fb_h, xr, 0, xr + 1, G.fb_h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
#endif
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)screen);
  return glGetError() == GL_NO_ERROR;
#endif
}
#else
/* the texture: the two columns side by side */
static void sides_target(int fmt) {
  (void)fmt;
  if (!SIDES.tex) glGenTextures(1, &SIDES.tex);
  glBindTexture(GL_TEXTURE_2D, SIDES.tex);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 2, G.fb_h, 0, GL_RGB, GL_UNSIGNED_BYTE, NULL);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  SIDES.w = G.fb_w, SIDES.h = G.fb_h;
}

/* the two columns into the texture's 0 and 1; 0 if the copy was refused */
static int sides_blit(GLint screen, int xl, int xr) {
  (void)screen;
  while (glGetError() != GL_NO_ERROR) {}
  glBindTexture(GL_TEXTURE_2D, SIDES.tex);
  glCopyTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, xl, 0, 1, G.fb_h);
  glCopyTexSubImage2D(GL_TEXTURE_2D, 0, 1, 0, xr, 0, 1, G.fb_h);
  return glGetError() == GL_NO_ERROR;
}
#endif

static void wide_sides(void) {
#ifdef WMMT_NATIVE_VK
  if (SIDES.off || G.fb_w < 8 || G.fb_h <= 0) return;
  float edge = G.edge * (float)G.fb_h / 768.0f + 0.5f;
  /* Preserve normal rounding, but reject invalid extents/edges before integer
   * conversion or doubled-x arithmetic (resize/lifecycle inputs can be empty). */
  if (!isfinite(edge) || edge < 2 || (double)edge >= (double)G.fb_w) return;
  int x0 = (int)edge;
  if (x0 > (G.fb_w - 4) / 2) return;
#else
  int x0 = (int)(G.edge * (float)G.fb_h / 768.0f + 0.5f); /* the layout's x 0 on the screen */
  if (SIDES.off || x0 < 2 || 2 * x0 + 4 > G.fb_w) return;
#endif
#ifdef WMMT_NATIVE_VK
  if (SIDES.prog && !cinder_vk_program_ready(SIDES.prog)) {
    cinder_vk_program_destroy(SIDES.prog);
    SIDES.prog = 0;
  }
#endif
  if (!SIDES.prog) {
    static const char *vs =
      "attribute vec2 aPos; attribute vec2 aUV; attribute float aShade; varying vec2 vUV; varying float vShade;\n"
      "void main() { vUV = aUV; vShade = aShade; gl_Position = vec4(aPos, 0.0, 1.0); }\n";
    /* a little soft up and down, so a line of text across the column doesn't streak */
    static const char *fs =
      "precision highp float; uniform sampler2D uTex; uniform float uDy; varying vec2 vUV; varying float vShade;\n"
      "void main() {\n"
      "  vec2 d = vec2(0.0, uDy);\n"
      "  vec3 c = texture2D(uTex, vUV).rgb * 0.4 + (texture2D(uTex, vUV + d).rgb + texture2D(uTex, vUV - d).rgb) * 0.2\n"
      "         + (texture2D(uTex, vUV + 2.0 * d).rgb + texture2D(uTex, vUV - 2.0 * d).rgb) * 0.1;\n"
      "  gl_FragColor = vec4(c * vShade, 1.0);\n"
      "}\n";
    const char *attribs[] = { "aPos", "aUV", "aShade" };
#ifdef WMMT_NATIVE_VK
    SIDES.prog = cinder_vk_program_create(vs, fs, attribs, 3);
    if (SIDES.prog && !cinder_vk_program_ready(SIDES.prog)) {
      cinder_vk_program_destroy(SIDES.prog);
      SIDES.prog = 0;
    }
#elif defined(__ANDROID__)
    SIDES.blit = (blit_fn)eglGetProcAddress("glBlitFramebuffer");
    SIDES.prog = SIDES.blit ? gl_compile_program(vs, fs, attribs, 3) : 0;
#else
    SIDES.prog = gl_compile_program(vs, fs, attribs, 3);
#endif
    if (!SIDES.prog) {
      fprintf(stderr, "wide menu sides: no blit or program, black bars\n");
      SIDES.off = 1;
      return;
    }
#ifndef WMMT_NATIVE_VK
    SIDES.u_tex = glGetUniformLocation(SIDES.prog, "uTex");
    SIDES.u_dy = glGetUniformLocation(SIDES.prog, "uDy");
#endif
  }
  GLint screen = 0;
#ifndef WMMT_NATIVE_VK
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screen);
#endif
  int xl = x0 + 1, xr = G.fb_w - x0 - 2; /* a pixel in from the 4:3's edges */
  if (SIDES.w != G.fb_w || SIDES.h != G.fb_h) sides_target(SIDES.fmt);
  if (!sides_blit(screen, xl, xr)) {
    /* the window's format: RGB8 asked, an RGBX surface may count as RGBA8 */
    sides_target(!SIDES.fmt);
    if (!sides_blit(screen, xl, xr)) {
      fprintf(stderr, "wide menu sides: blit refused, black bars\n");
      SIDES.off = 1;
      return;
    }
    fprintf(stderr, "wide menu sides: %s\n", SIDES.fmt ? "RGBA8" : "RGB8");
  }
#ifndef WMMT_NATIVE_VK
  glViewport(0, 0, G.fb_w, G.fb_h);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glDisable(GL_BLEND);
  glUseProgram(SIDES.prog);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, SIDES.tex);
  glUniform1i(SIDES.u_tex, 0);
  glUniform1f(SIDES.u_dy, 1.5f / (float)G.fb_h);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glEnableVertexAttribArray(2);
#endif
  const float out = 0.55f; /* the shade at the screen's edge (1 at the 4:3's) */
#ifdef __ANDROID__
  float e = 2.0f * (float)x0 / (float)G.fb_w, ul = ((float)xl + 0.5f) / (float)G.fb_w,
        ur = ((float)xr + 0.5f) / (float)G.fb_w;
#else
  float e = 2.0f * (float)x0 / (float)G.fb_w, ul = 0.25f, ur = 0.75f;
#endif
#ifdef WMMT_VK
  const float v0 = 1, v1 = 0; /* (the copy's rows from the top: sides_blit) */
#else
  const float v0 = 0, v1 = 1;
#endif
  const float v[2][20] = {
    { -1, -1, ul, v0, out, -1 + e, -1, ul, v0, 1, -1, 1, ul, v1, out, -1 + e, 1, ul, v1, 1 },
    { 1 - e, -1, ur, v0, 1, 1, -1, ur, v0, out, 1 - e, 1, ur, v1, 1, 1, 1, ur, v1, out },
  };
  for (int s = 0; s < 2; ++s) {
#ifdef WMMT_NATIVE_VK
    if (!sides_native_draw(SIDES.prog, SIDES.tex, G.fb_w, G.fb_h, v[s])) return;
#else
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 20, v[s]);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 20, v[s] + 2);
    glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, 20, v[s] + 4);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
#endif
  }
#ifndef WMMT_NATIVE_VK
  glDisableVertexAttribArray(2);
#endif
}


/* result2 at 0x89104b1 adds the native distance in whole kilometres. */
static void app_finish_mileage(void) {
  int own = G.menu.save_skip ? -1 : menu_own_find(&G.menu, G.menu.maker, G.menu.car);
  double before = own < 0 ? 0.0 : G.menu.own[own].odo;
  const car_race *race = &G.car.race;
  if ((G.menu.game == MENU_GAME_STORY && G.menu.story_test) || !race->mileage_valid) return;
  float mm = race->mileage_mm + G.story_mileage_unrestored_mm;
  int km = (int)fminf(mm * 1.0e-6f, 16777215.0f);
  double after = fmax(before, fmin(16777215.0 * 1000.0, before + 1000.0 * km));
  menu_finish_set_mileage(&G.menu, before, after);
  if (own >= 0) G.menu.own[own].odo = after;
}

#include "app_ghost.inc"
#include "app_ta_rank.inc"
#include "app_body_color.inc"

static void menu_frame(float dt, double frame_start) {
  AGR.token=0;
  app_story_body_clear(); /* returned menu/load/cancel cannot reuse a previous race stamp */
  app_rotary_stop(); /* menu entry closes the previous native audio lifetime once */
#ifdef __ANDROID__
  player_smoke_reset();
#endif
  if (BPC.race_frozen) {
    (void)player_body_paint_clear(&BPC.race,0);
    BPC.race_frozen=BPC.draw_fault=0;
  }
  if (G.mini_move > 0) --G.mini_move;
  ++G.mini_frame;
  /* The token may cross only the automatic, quiet next-period transition. */
  if (G.story_carry_token &&
      (G.menu.game != MENU_GAME_STORY || G.menu.screen != MENU_PRE || !G.menu.pre_quiet ||
       !G.story_cut_pending || G.menu.story_pick != G.story_carry_select ||
       G.story_race != G.story_carry_period)) story_carry_cancel();
  G.vs_race = 0;
  G.vs_closed = 0;
  app_ghost_menu();
  app_ghost_card_menu();
  if (!app_ghost_mode()) vs_menu();
  /* a versus on its way: the race's course loads under the versus screen's NOW LOADING */
  int vs_load = net_is_open() && G.menu.game == MENU_GAME_VS &&
    net_state()->phase == VS4_LOAD &&
    (G.menu.screen == MENU_VS || G.menu.screen == MENU_VS_MATCH) && G.menu.vs.state == MENU_VS_LOADING;
  /* the time zone select's card, once it stays at rest a moment (or is chosen), picks the map
   * to load; the other's goes a step a frame */
  int rest = G.menu.screen != MENU_BGM || G.menu.deciding || G.menu.card_t >= ZONE_REST;
  /* and the city: the chosen course's (car_course_city), a story race's its series' start
   * (STORYCITY, once its title page names the rival) */
  int city = G.track_city;
  if (app_ghost_mode() && (menu_ghost_preparing(&G.menu) || menu_ghost_choosing_options(&G.menu))) {
    city = car_course_city(AG.course); /* render resource only, native field remains immutable */
    if (G.menu.screen==MENU_BGM) {
      char night_path[1200];
      city_path(night_path,sizeof night_path,"",city,1,"wpk");
      G.menu.zones=access(night_path,R_OK)==0 ? 2 : 1;
      if (G.menu.zone>=G.menu.zones) G.menu.zone=0;
    }
  } else if (G.menu.screen == MENU_VS || G.menu.screen == MENU_VS_MATCH) {
    if (vs_load) city = car_course_city(G.menu.course);
  } else if (G.menu.screen == MENU_BGM && G.menu.vs.day) { /* the area's city, once known */
    if (G.menu.vs.area_final >= 0 || G.menu.vs.me == G.menu.vs.host) city = car_course_city(G.menu.course);
  } else if (G.menu.game == MENU_GAME_STORY) {
    int r = story_rival();
    if ((G.menu.screen == MENU_PRE || G.menu.story_day_select) && r >= 0 && RIVALDB[r].series >= 0 && RIVALDB[r].series < STORYCITY_N)
      city = STORYCITY[RIVALDB[r].series];
    if (G.menu.story_day_select) {
      char night_path[1200];
      city_path(night_path, sizeof night_path, "", city, 1, "wpk");
      G.menu.zones = access(night_path, R_OK) == 0 ? 2 : 1;
      if (G.menu.zone >= G.menu.zones) G.menu.zone = 0;
    }
  } else if (G.menu.game == MENU_GAME_TEN) {
    if (G.menu.screen == MENU_PRE) city = TEN_CITY[menu_ten_course(&G.menu)];
  } else if (G.menu.screen == MENU_BGM || G.menu.screen == MENU_PRE) /* decided, not while browsing */
    city = car_course_city(G.menu.course);
  if ((G.menu.zone != G.track_zone || city != G.track_city || G.hd_reload) && !G.menu.slide && rest &&
      track_open(city, G.menu.zone) != 0) {
    if (app_ghost_mode()) {
      app_ghost_fail("GHOST MAP RESOURCE UNAVAILABLE");
      menu_present(frame_start); return; /* never start a different native/render course */
    }
    if (net_is_open() && net_state()->phase == VS4_LOAD && G.menu.game == MENU_GAME_VS) {
      app_vs4_cancel("EXACT VS MAP RESOURCE UNAVAILABLE");menu_present(frame_start);return;
    }
    fprintf(stderr, "no map of city %d zone %d, back to Tokyo's morning\n", city, G.menu.zone);
    G.menu.zone = 0;
    G.menu.zones = 1;
    track_open(CAR_TOKYO, 0);
  }
  if (G.track_old.n_batch || G.track_old.n_tex) wpk_free_step(&G.track_old, TRACK_FREE_STEP);
  /* the race waits on its title page till all it draws is in GL and first-drawn (a cold part
   * cost the race a frame and more on the iPad): the course, its sky and arrow boards, the
   * traffic (warm_step), the chosen car with its paint, and the HUD with the car's meters
   * (hud_warm: the race's first frame took some 100 ms first-drawing them) */
  G.rival = app_ghost_mode() ? -1 : story_rival();
  G.menu.story_sel = G.rival >= 0 && G.menu.game == MENU_GAME_STORY ? RIVALDB[G.rival].select : -1;
  const cardb_color *chosen = chosen_color();
  int start_in = G.seen.track == 2 || (G.seen.track == 1 && G.seen.start == G.menu.course + 1);
  if (vs_load) start_in = G.seen.track == 2 && city == G.track_city; /* the race starts off the course's start */
  if (app_ghost_mode() && menu_ghost_preparing(&G.menu)) start_in = G.seen.track == 2 && city == G.track_city;
  int pre = G.menu.screen == MENU_PRE || vs_load || menu_ghost_preparing(&G.menu);
  int body_in = !pre || app_body_start_ready();
  int hud_in = 1;
  if (pre) {
    hud_set_meter(menu_card_meter(&G.menu));
    hud_set_car(chosen->pack, G.track_zone == 1);
    hud_in = hud_warm(G.hud.screen_w, G.hud.screen_h, HUD_WARM_STEP) == 0;
  }
  int all_in = start_in && hud_in && car_pack(chosen->pack) && paint_ready(chosen->pack, chosen->paint);
  int rows[RACE_ROWS], n_rival = rival_rows(G.rival, rows);
  for (int i = 0; i < n_rival; ++i) {
    int paint, rival = rival_look(rows[i], &paint);
    all_in = all_in && (rival < 0 || (car_pack(rival) && paint_ready(rival, paint)));
  }
  /* a versus': the machines' cars, for their flying in (MENU_VS_MATCH) */
  int match_in = 1;
  for (int k = 0; vs_load && k < G.menu.vs.match_n; ++k) {
    const net_player *member = &G.vs_go.player[k];
    const cardb_color *oc = vs_color(member);
    match_in = match_in && oc && car_pack(oc->pack) && paint_ready(oc->pack, oc->paint);
  }
  all_in = all_in && match_in;
  int ghost_paint = 0, ghost_pack = app_ghost_rival_pack(&ghost_paint);
  if (ghost_pack >= 0) all_in = all_in && ghost_pack < NPACKS && G.seen.pack[ghost_pack] == 1 &&
                                    car_pack(ghost_pack) && paint_ready(ghost_pack, ghost_paint);
  /* Unlike legacy menus, a real Ghost opponent must never be drawn as the FD3S
   * missing-model substitute. Its exact approved model remains a start gate. */
  if (app_ghost_mode() && AG.arcade && AG.prepared) {
    all_in=all_in && app_arcade_appearance_ready();
    if (menu_ghost_preparing(&G.menu)) {
      int aero=G.menu.aero[G.menu.maker][G.menu.car], wheel=G.menu.wheel[G.menu.maker][G.menu.car];
      int slot=wheel_find(wheel), set;
      /* Old packs may lack the player's optional accessories. Keep the race's
       * stock fallback after a definitive miss; an exact rival is mandatory. */
      all_in=all_in && (!aero || menu_aero_find(chosen->pack,aero)>=0) &&
        (!wheel || !menu_wheel_pack(wheel,&set) ||
         (slot>=0 && (G.wheel_state[slot]==WHEEL_READY || G.wheel_state[slot]==WHEEL_MISSING)));
    }
  }
  G.pre_wait = pre && !all_in ? G.pre_wait + 1 : 0;
  if (G.menu.screen == MENU_PRE) G.pre_frames++;
  if (G.pre_wait == PRE_WAIT_MAX) fprintf(stderr, "race title: loading still not done (track %d), starting\n", G.seen.track);
  G.menu.ready = (app_ghost_mode() ? pre && all_in && AG.prepared : all_in || G.pre_wait >= PRE_WAIT_MAX) && body_in; /* timeout cannot bypass exact player paint */
  if (vs_load) {
    G.menu.ready=all_in && body_in;
    if(G.pre_wait>=PRE_WAIT_MAX){app_vs4_cancel("EXACT VS RESOURCES TIMED OUT - ROUND CANCELED");menu_present(frame_start);return;}
  }
  if (app_ghost_mode() && pre && G.pre_wait >= PRE_WAIT_MAX) {
    app_ghost_fail("GHOST LOADING TIMED OUT - NOT STARTED");
    menu_present(frame_start); return;
  }
  /* Detect deleted cards around menu_update without changing the menu subsystem. */
  menu_own old_own[MENU_OWN_MAX];
  int old_count = G.menu.n_own, old_slot = G.menu.save_slot;
  if (old_count < 0 || old_count > MENU_OWN_MAX) old_count = 0;
  memcpy(old_own, G.menu.own, (size_t)old_count * sizeof old_own[0]);
  int story_was_selecting = G.menu.story_day_select && !G.menu.deciding;
  int go = menu_update(&G.menu, dt);
  app_ta_rank_menu();
  if (story_was_selecting && G.menu.story_day_select && G.menu.deciding) {
    char path[1200];
    snprintf(path, sizeof path, "%s/story_timezone", G.save_dir);
    FILE *tz = fopen(path, "w");
    if (tz) { fputc('0' + G.menu.story_zone, tz); fclose(tz); }
  }
  if (old_slot == G.menu.save_slot && G.menu.n_own >= 0 && G.menu.n_own <= MENU_OWN_MAX) {
    for (int i = 0; i < old_count; ++i) {
      int exists = 0;
      for (int k = 0; k < G.menu.n_own; ++k)
        if (old_own[i].maker == G.menu.own[k].maker && old_own[i].car == G.menu.own[k].car &&
            old_own[i].born == G.menu.own[k].born) { exists = 1; break; }
      if (!exists) {
        bgm_erase_card(old_slot, &old_own[i]);
        int mk = old_own[i].maker, c = old_own[i].car;
        if (mk >= 0 && mk < MENU_GARAGE_MAKERS && c >= 0 && c < MENU_GARAGE_CARS) {
          G.menu.meter_car[mk][c] = G.menu.sound_car[mk][c] = G.menu.st_bonus_car[mk][c] = 0;
          G.menu.card_born[mk][c] = 0;
          if (G.menu.card_choice_error || !cc_save(G.save_dir, old_slot, &G.menu)) G.menu.card_choice_error = G.menu.card_save_failed = 1;
        }
      }
    }
    /* A newly registered card is not yet saved: clear any orphan before it
     * can be read, including a same-second collision with a deleted card. */
    for (int k = 0; k < G.menu.n_own; ++k) {
      int exists = 0;
      for (int i = 0; i < old_count; ++i)
        if (old_own[i].maker == G.menu.own[k].maker && old_own[i].car == G.menu.own[k].car &&
            old_own[i].born == G.menu.own[k].born) { exists = 1; break; }
      if (!exists) {
        bgm_erase_card(old_slot, &G.menu.own[k]);
        int mk = G.menu.own[k].maker, c = G.menu.own[k].car;
        if (mk >= 0 && mk < MENU_GARAGE_MAKERS && c >= 0 && c < MENU_GARAGE_CARS) {
          G.menu.meter_car[mk][c] = G.menu.sound_car[mk][c] = G.menu.st_bonus_car[mk][c] = 0;
          G.menu.card_born[mk][c] = 0;
          if (G.menu.card_choice_error || !cc_save(G.save_dir, old_slot, &G.menu)) G.menu.card_choice_error = G.menu.card_save_failed = 1;
        }
      }
    }
  }
  app_vs4_match_ready(match_in && G.menu.ready);
  /* Native Init occurs once DURING LOAD after local rendering resources, not
   * after peer native packets. LOAD_READY follows returned Init + exact paint. */
  int vs = net_is_open() && net_state()->phase == VS4_LOAD && G.menu.screen == MENU_VS &&
    G.menu.vs.state == MENU_VS_LOADING && G.menu.vs.match_played && !AV4.native_initialized && G.vs_go.round;
  if (vs && G.menu.ready && G.menu.t >= VS_LOADING_MIN) go = 1;
  if (G.menu.save_erase) {
    save_erase(G.menu.save_erase);
    G.menu.save_erase = 0;
    G.menu.save_scan = 1;
  }
  if (G.menu.save_scan) {
    save_scan();
    G.menu.save_scan = 0;
  }
  if (G.menu.save_pick) save_take();
  if (G.menu.key_retry_frames>0) --G.menu.key_retry_frames;
  if (G.menu.key_layout_dirty && !G.menu.lay_drag && !G.menu.key_retry_frames) {
    G.menu.key_save_failed=!key_layout_save();
    if (G.menu.key_save_failed) G.menu.key_retry_frames=120;
  }
#ifdef __ANDROID__
  if (G.menu.stick_center_retry_frames>0) --G.menu.stick_center_retry_frames;
  if (G.menu.stick_center_dirty && !G.menu.lay_drag && !G.menu.stick_center_retry_frames &&
      G.menu.stick_center_status!=STICK_STORE_UNKNOWN && G.menu.stick_center_retries<3) {
    char path[1100];
    if (snprintf(path,sizeof path,"%s/stick_center",G.save_dir) >= (int)sizeof path)
      G.menu.stick_center_status=STICK_STORE_IO;
    else G.menu.stick_center_status=stick_store_save(path,G.menu.stick_center_mode,1);
    if (G.menu.stick_center_status==STICK_STORE_OK) G.menu.stick_center_dirty=0;
    else { ++G.menu.stick_center_retries; G.menu.stick_center_retry_frames=120; }
  }
  if (G.menu.custom_retry_frames>0) --G.menu.custom_retry_frames;
  if (G.menu.custom_layout_dirty && !G.menu.lay_drag && !G.menu.custom_retry_frames &&
      G.menu.custom_layout_status!=HUD_CUSTOM_UNSUPPORTED) {
    char custom_path[1100]; unsigned mask=G.menu.custom_layout_dirty;
    HudCustomLayout merged=custom_layout_merge(G.menu.custom_layout_base,&G.menu.custom_layout,mask);
    if (snprintf(custom_path,sizeof custom_path,"%s/hud_custom_layout",G.save_dir) >= (int)sizeof custom_path)
      G.menu.custom_layout_status=HUD_CUSTOM_IO_ERROR;
    else G.menu.custom_layout_status=hud_custom_save(custom_path,&merged,1);
    if (G.menu.custom_layout_status==HUD_CUSTOM_OK) {
      G.menu.custom_layout_base=merged;
      G.menu.custom_layout_dirty &= ~mask;
    } else G.menu.custom_retry_frames=120; /* bounded retry; keep the edit dirty */
  }
#endif
  story_new_card_commit();
  if (G.menu.garage_changed) {
    hq_apply();
    G.menu.options_dirty = !options_save();
    garage_save();
    G.menu.garage_changed = 0;
  } else if (G.menu.options_dirty && options_save()) {
    G.menu.options_dirty = 0;
  }
  if (go && app_ghost_mode() && !app_ghost_go_valid()) {
    app_ghost_fail("GHOST START REJECTED - NO PREPARED SESSION");
    go = 0;
  }
  if (go) {
    int ghost = app_ghost_mode();
    if (!ghost) car_ghost_clear();
    const cardb_color *col = chosen_color();
    app_story_body_clear();
    if (!menu_story_body_get(&G.menu,&ASB.own)) {
      if (vs) app_vs4_cancel("EXACT EARNED CAR ASSEMBLY UNAVAILABLE");
      else story_race_start_failed();
      return;
    }
    ASB.active=1;
    int power, handling;
    /* a story race runs on the story's tune (the card's), the time attack on the setting's */
    if (G.menu.game == MENU_GAME_STORY && !vs) menu_story_tune(&G.menu, &power, &handling);
    else menu_tune(&G.menu, &power, &handling);
#ifdef __ANDROID__
    /* Consume the confirmed single-race adjustment before constructing any
     * physics, HUD, or audio configuration; never change stored garage data. */
    if (vs) {
      if (!vs_slot_matches() || (G.menu.pre_tune.state &&
          !pre_race_tune_slot_matches(&G.menu.pre_tune,G.menu.save_slot,G.menu.save_skip)) ||
          !app_vs4_snapshot_matches(net_state())) { app_vs4_cancel("TUNE OR CARD CHANGED BEFORE INIT"); return; }
      const net_player *own=&G.vs_go.player[G.vs_go.pcb];
      power=own->profile[3];handling=own->profile[4];
    } else {
      if (G.menu.pre_tune.state && !pre_race_tune_slot_matches(&G.menu.pre_tune,G.menu.save_slot,G.menu.save_skip))
        pre_race_tune_clear(&G.menu.pre_tune);
      else pre_race_tune_take(&G.menu.pre_tune, G.menu.game, G.menu.maker, G.menu.car,
                             power, handling, &power, &handling);
    }
#endif
    car_spec spec = { (unsigned)col->type, col->gears, { 0 }, (int)CARDB_TYRES[col->pack][6], power, handling };
    for (int i = 0; i < 6; ++i) spec.tyres[i] = CARDB_TYRES[col->pack][i];
    /* a race chosen before the course finished loading waits for the rest */
    load_pause();
    while (G.track_old.n_batch || G.track_old.n_tex) wpk_free_step(&G.track_old, 1u << 30);
    if (!G.track_ready) track_set(wpk_upload(&G.track, (size_t)-1));
    pack_load_now(col->pack, col->paint != 0);
    car_rival rv[CAR_RIVALS] = {{0}};
    int story_slots_valid = 1;
    G.n_rival = 0;
    memset(G.rival_dress, 0, sizeof G.rival_dress);
    G.n_ten = 0;
    int ten = G.rival == TEN_FIRST, course = G.menu.course;
    G.race_traffic = !ten && !vs && G.menu.game == MENU_GAME_TA && G.menu.ta_traffic;
    car_set_ta_traffic(G.race_traffic);
    car_set_ten(0, 0, NULL, 0);
    if (ten) {
      /* the 10-in-a-row: all the level's rivals' models now (one on the road, a new one each
       * round: CSeq::Exec), their tyres for its CRivalSetting::GetSettingPt */
      car_rival tv[CAR_TEN_RIVALS];
      for (int i = 0; i < n_rival && i < CAR_TEN_RIVALS; ++i) {
        memset(&tv[i], 0, sizeof tv[i]);
        G.ten_pack[i] = rival_look(rows[i], &G.ten_paint[i]);
        if (G.ten_pack[i] >= 0) pack_load_now(G.ten_pack[i], G.ten_paint[i] != 0);
        int base_paint, base = rival_base(rows[i], &base_paint);
        tv[i].type = (unsigned)rival_type(rows[i]);
        tv[i].character = rows[i] - TEN_ROW(0);
        tv[i].level = G.menu.ten_level;
        for (int j = 0; base >= 0 && j < 6; ++j) tv[i].tyres[j] = CARDB_TYRES[base][j];
        tv[i].spokes = base >= 0 ? (int)CARDB_TYRES[base][6] : 5;
        G.n_ten++;
      }
      car_set_ten(menu_ten_stage(&G.menu), G.menu.ten_level, tv, G.n_ten);
      course = ten_ta_course();
      if (G.n_ten && G.ten_pack[0] >= 0) {
        G.rival_pack[0] = G.ten_pack[0];
        G.rival_paint[0] = G.ten_paint[0];
        G.n_rival = 1;
      }
      n_rival = 0;
    }
    if (vs) {
      /* the versus: the other machines' cars (their profiles), rivals 0.. in PCB order */
      car_link_car others[CAR_LINK_MACHINES - 1];
      for (int k = 0; k < G.vs_go.n && G.n_rival < CAR_LINK_MACHINES - 1 && G.n_rival < CAR_RIVALS; ++k) {
        if (k == G.vs_go.pcb) continue;
        const net_player *pl = &G.vs_go.player[k];
        const cardb_color *oc = vs_color(pl);
        if (!oc || !app_story_body_peer(pl,&ASB.rival[G.n_rival])) {app_vs4_cancel("FROZEN RIVAL PROFILE LOST");return;}
        car_link_car *o = &others[G.n_rival];
        memset(o, 0, sizeof *o);
        o->pcb = k;
        o->type = (unsigned)oc->type;
        for (int j = 0; j < 6; ++j) o->tyres[j] = CARDB_TYRES[oc->pack][j];
        o->spokes = (int)CARDB_TYRES[oc->pack][6];
        o->power = pl->profile[3];
        o->handling = pl->profile[4];
        G.rival_pack[G.n_rival] = oc->pack;
        G.rival_paint[G.n_rival] = oc->paint;
        pack_load_now(oc->pack, oc->paint != 0);
        /* dressed up as its player's (the profile's; its aero and wheels in now) */
        G.rival_dress[G.n_rival] = vs_dress(pl);
        menu_aero_want(oc->pack, G.rival_dress[G.n_rival].aero);
        if (G.rival_dress[G.n_rival].wheel) wheel_model(G.rival_dress[G.n_rival].wheel);
        G.n_rival++;
      }
      car_link_io io = { vs_link_send, vs_link_receive, NULL };
      car_set_versus(G.vs_go.pcb, others, G.n_rival, G.vs_go.ramp, (float)G.vs_go.km, G.vs_go.seed, &io);
      n_rival = 0;
    }
    for (int i = 0; i < n_rival; ++i) {
      int k = G.n_rival, pack = rival_look(rows[i], &G.rival_paint[k]);
      if (pack < 0) { story_slots_valid = 0; continue; }
      if (RIVALDB[rows[i]].slot != k) story_slots_valid = 0;
      for (int j = 0; j < k; ++j)
        if (rv[j].character == RIVALDB[rows[i]].character && rv[j].type == (unsigned)RIVALDB[rows[i]].type)
          story_slots_valid = 0;
      G.rival_pack[k] = pack;
      pack_load_now(pack, G.rival_paint[k] != 0);
      const rivaldb_rival *r = &RIVALDB[rows[i]];
      memset(&rv[k], 0, sizeof rv[k]);
      rv[k].type = (unsigned)r->type;
      rv[k].character = r->character;
      rv[k].level = menu_story_loop(&G.menu);
      rv[k].losses = menu_story_losses(&G.menu);
      rv[k].series = r->series;
      /* the tyres of the car select's model of its type (a rival's own car is that body, dressed) */
      int base_paint, base = rival_base(rows[i], &base_paint);
      for (int j = 0; j < 6; ++j) rv[k].tyres[j] = CARDB_TYRES[base][j];
      rv[k].spokes = (int)CARDB_TYRES[base][6];
      G.n_rival++;
    }
    if (ghost && (AG.config.kind == CAR_GHOST_CHALLENGE || AG.config.kind == CAR_GHOST_DEFAULT)) {
      G.n_rival = 1; G.rival_pack[0] = AG.rival_pack; G.rival_paint[0] = AG.rival_paint;
      app_ghost_arcade_apply_dress(&G.rival_dress[0]);
      if (G.rival_dress[0].aero) menu_aero_want(AG.rival_pack,G.rival_dress[0].aero);
      if (G.rival_dress[0].wheel) wheel_model(G.rival_dress[0].wheel);
      pack_load_now(AG.rival_pack, AG.rival_paint != 0);
      if (AG.arcade || AG.config.kind==CAR_GHOST_DEFAULT) {
        int raw=AG.arcade ? (int)AG.arcade_style.car_ : (int)AG.default_binding.record.raw_model_id;
        const car_spec *earned=AG.arcade ? &AG.arcade_binding.rival : &AG.default_binding.record.car.rival;
        if (!story_body_view_capture_model(&ASB.rival[0],AG.rival_pack,raw,(int)earned->type,earned->power,earned->handling,0)) {
          app_story_body_clear();app_ghost_fail("EXACT SOURCE GHOST ASSEMBLY UNAVAILABLE");return;
        }
      }
    }
    load_sync(NULL);
    if (!ghost) car_set_rivals(rv, ten || vs ? 0 : G.n_rival);
    if (ghost || ten || vs || !story_slots_valid) story_carry_cancel();
    else story_carry_arm(rv, G.n_rival);
    if (!ghost) app_ta_replay_arm();
    if (car_start(&G.car, course, G.menu.manual, &spec) != 0) {
      fprintf(stderr, "course %d failed to start\n", G.menu.course);
      story_carry_cancel();
      if (ghost) { app_ghost_fail("NATIVE GHOST START FAILED"); return; }
      if (vs) {
        app_vs4_cancel("RETURNED NATIVE INIT FAILURE - ROUND CANCELED"); return;
      } else story_race_start_failed();
    } else {
      if (ghost && !app_ghost_started(&spec)) { app_ghost_fail("GHOST TARGET OR RECORDER NOT READY"); return; }
      G.story_old_ended = 0;
      G.story_carry_attempted = 0;
      spark_reset(); backfire_reset();
#ifdef __ANDROID__
    player_tracks_reset();
#endif
      G.vs_race = vs ? G.n_rival : 0;
      G.hud.pause_disabled = vs;
      if (vs) G.menu.vs.state = MENU_VS_RACE;
      fprintf(stderr, "race: course %d (%s), %s colour %d, power %d handling %d, %s\n", G.menu.course,
              G.menu.official ? "official machine" : "personal best", CARDB_CARS[G.menu.maker][G.menu.car].label,
              G.menu.color, power, handling, G.menu.manual ? "MT" : "AT");
      G.in_menu = 0;
      load_pause(); /* the race loads nothing more (its own first draws aside) */
      /* the car models stay for the car select after the race (unless iOS warned), only the
       * other cars' paints go */
      if (G.low_memory) car_packs_trim(0, NULL);
      else car_paints_trim(NULL, 1);
      /* the map's fog, and its time zone for the next start */
      int z = G.track_zone;
      G.rp.night = z == 1;
      G.rp.fog_far = FOG[G.track_city][z].far;
      G.rp.fog_near = FOG[G.track_city][z].near;
      memcpy(G.rp.fog_color, FOG[G.track_city][z].color, sizeof G.rp.fog_color);
      memcpy(G.rp.grade, MAP_GRADE[G.track_city][z], sizeof G.rp.grade);
      G.rp.wet = G.console && z && G.menu.wet_on ? 0.75f : 0.0f; /* (a night's road shines with its lights) */
      char path[1200];
      snprintf(path, sizeof path, "%s/timezone", G.save_dir);
      FILE *tz = G.menu.game == MENU_GAME_TA ? fopen(path, "w") : NULL;
      if (tz) {
        fputc('0' + z, tz);
        fclose(tz);
      }
      G.race_model = car_pack(col->pack);
      wpk_paint(G.race_model, col->paint);
      int set = G.menu.aero[G.menu.maker][G.menu.car];
#ifdef WMMT_EGL
      if (getenv("WMMT_AERO")) set = atoi(getenv("WMMT_AERO")); /* test: this aero set */
#endif
      aero_model(col->pack, set);
      if (!app_body_race_prepare()) {
        app_rotary_stop(); app_ta_rank_invalidate(); app_body_drop(0);
        story_carry_cancel(); snd_quiet(); G.in_menu=1; G.paused=0;
        if (ghost) { app_ghost_fail("PLAYER APPEARANCE PREPARATION FAILED - RUN CANCELLED"); return; }
        if (vs) { app_vs4_cancel("EXACT PLAYER APPEARANCE START FAILED"); return; }
        story_race_start_failed();
        return;
      }
      wheel_model(G.menu.wheel[G.menu.maker][G.menu.car]);
      for (int i = 0; i < CAR_RIVALS; ++i) {
        G.rival_model[i] = i < G.n_rival ? car_pack(G.rival_pack[i]) : NULL;
        if (G.rival_model[i] && !ten && !vs && !ghost)
          fprintf(stderr, "rival %d: %s (%s), select %d race %d\n", i + 1, RIVALDB[rows[i]].name,
                  pack_name(G.rival_pack[i]), RIVALDB[rows[i]].select, RIVALDB[rows[i]].race);
      }
      /* the car's own engine sound, meters (morning or night) and gear pattern */
      snd_set_car((unsigned)col->type, power);
      app_rotary_start(); /* successful native race sequence, not menu car selection */
      hud_set_tune(car_tune_hp(CARDB_CARS[G.menu.maker][G.menu.car].hp, power), car_tune_grade(power, handling));
      hud_set_class(G.menu.class_car[G.menu.maker][G.menu.car]);
      hud_set_card(menu_title(&G.menu), G.menu.name);
      hud_set_meter(menu_card_meter(&G.menu));
      hud_set_car(col->pack, z == 1);
      hud_set_course(course);
      hud_set_story(G.menu.story_sel >= 0 || vs || ghost); /* a versus: the story's console (no records) */
      if (ghost && AG.arcade) {
        const car_ghost_arcade_binding *rival = &AG.arcade_binding;
        const cardb_car *model = &CARDB_CARS[rival->maker][rival->car];
        int p = rival->rival.power, h = rival->rival.handling;
        hud_vs_box card = {
          .title = (int)AG.arcade_style.title_, .plate = model->plate,
          .hp = car_tune_hp(model->hp, p), .grade = car_tune_grade(p, h),
          .power = p, .handling = h,
          .steps = vs_r35(G.menu.maker, G.menu.car) || vs_r35(rival->maker, rival->car),
        };
        memcpy(card.name, AG.rival_name, sizeof card.name);
        hud_set_ghost_card(&card, AG.crown_challenge ? AG.arcade_area : -1);
      }
      {
        int chara[CAR_RIVALS] = { 0 };
        unsigned char shown[CAR_RIVALS] = { 0 };
        int n = 0;
        for (int i = 0; !ten && G.menu.story_sel >= 0 && i < G.n_rival && i < CAR_RIVALS; ++i) {
          int slot = RIVALDB[rows[i]].slot;
          if (slot < 0 || slot >= CAR_RIVALS) continue;
          chara[slot] = RIVALDB[rows[i]].character;
          shown[slot] = STORYINFO_SHOWN[rows[i]];
          if (slot + 1 > n) n = slot + 1;
        }
        hud_set_story_rivals(chara, shown, n, G.menu.story_sel,
                             !ten && !vs && G.n_rival > 0 ? rv[0].series : -1,
                             !ten && !vs && story_slots_valid);
      }
      hud_set_ten(ten ? G.menu.ten_level : -1);
#ifdef __ANDROID__
      /* Reinitialize the route selector for this race, even after an abort. */
      memset(&race_junction_ui, 0, sizeof race_junction_ui);
      junction_barrier_reset(&race_junction_barrier);
      if (!junction_ui_init(&race_junction_ui, junction_table_private, sizeof junction_table_private))
        fprintf(stderr, "junction selector: invalid private table; hidden\n");
#endif
      /* initStory passes getStoryClearLoop in the normal card path (st_div / 5).
       * Demo/debug workspace overrides are not established. */
      {
        int select = !ten && !vs && G.menu.game == MENU_GAME_STORY && G.rival >= 0
                     ? RIVALDB[G.rival].select : -1;
        int loop = menu_story_cut_loop(G.menu.st_div, G.menu.story_test);
        int continuous = G.story_cut_pending && G.menu.pre_quiet && select >= 0 &&
                         select == G.story_cut_select && loop == G.story_cut_loop &&
                         G.story_race == G.story_cut_period;
        G.story_cut_pending = 0; /* consumed even if this is not the expected continuation */
        hud_story_cutin_period(select, loop, continuous);
      }
      {
        /* a versus: the other machines' boxes (clJoinConsole), in PCB order as car_set_versus has
         * them (a car this app does not know: its own, as the race has it); the tune's steps
         * with an R35 in the race (its or this one) */
        hud_vs_box box[CAR_RIVALS];
        int n = 0, r35 = vs_r35(G.menu.maker, G.menu.car);
        for (int k = 0; vs && k < G.menu.vs.match_n && n < CAR_RIVALS; ++k) {
          if (k == G.menu.vs.match_me) continue;
          const typeof(G.menu.vs.match[0]) *o = &G.menu.vs.match[k];
          int known = o->maker >= 0, mk = known ? o->maker : G.menu.maker, c = known ? o->car : G.menu.car;
          int power = known ? o->power : 0, handling = known ? o->handling : 0;
          hud_vs_box *b = &box[n++];
          for (int j = 0; j < 5; ++j) b->name[j] = o->glyph[j];
          b->title = o->title;
          b->plate = CARDB_CARS[mk][c].plate;
          b->hp = car_tune_hp(CARDB_CARS[mk][c].hp, power);
          b->grade = car_tune_grade(power, handling);
          b->power = power, b->handling = handling;
          b->steps = r35 || vs_r35(mk, c);
          b->seat = k;
        }
        hud_set_vs(box, n);
      }
      if (!ghost) records_show(course);
      G.race_pack = col->pack;
      if (G.story_race == 0) { /* (a select's second race: the card as the first started) */
        title_card_now(&G.title_pre);
        G.title_odo0 = title_odo();
        G.story_mileage_pending_mm = G.story_mileage_unrestored_mm = 0.0f;
      }
      G.top_kmh = 0;
      G.time_shown = (int)G.car.race.time_left;
      G.ten_rival_on = -1;
      G.ten_freeze = G.ten_beaten_on = G.ten_bgm_off = 0;
      G.ten_bgm = G.n_ten ? ten_round_bgm(&G.menu, 0) : NULL;
      G.ten_bgm_round = 0;
      G.story_end_freeze = G.story_end_started = 0;
      G.ten_white = G.n_ten ? 1 : 0;
      G.race_spec = spec;
      memcpy(G.race_rv, rv, sizeof rv);
      G.race_nrv = ghost || ten || vs ? 0 : G.n_rival;
      G.story_race_slots_valid = !ghost && !ten && !vs && story_slots_valid;
      G.race_course = course;
      if (!vs) app_ta_rank_start(); /* VS is never a time-attack recorder. */
#if defined(__ANDROID__) && defined(WMMT_DEBUG_LOG)
      debug_race_init();
#endif
      G.period_fade = ghost && G.menu.ghost.intro_t ? 1 : G.menu.pre_fade;
      G.period_in = G.period_fade ? MOVIE_FADE : 0;
      G.menu.pre_fade = 0;
      if (!ten && G.menu.game == MENU_GAME_STORY && G.rival >= 0 &&
          movie_open(RIVALDB[G.rival].select, G.story_race, rows, n_rival) != 0) {
        story_race_start_failed();
        return;
      }
      /* No movie or a missing trail: this successful Init is the real race.
       * A running movie keeps the same token until movie_close's final Init. */
      if (G.movie_len <= 0) story_carry_finish();
      if (vs) {
        /* Resolve vinyls before LOAD_READY. A first draw can read a VPK,
         * inflate the overlay and upload a composite texture for each car. */
        const char *page1;
        if (!BPC.race_frozen || !BPC.race_view.custom_color)
          vinyl_tex(G.race_pack, G.aero_set, col->paint,
                    G.menu.vinyl[G.menu.maker][G.menu.car],
                    G.menu.bonnet[G.menu.maker][G.menu.car], &page1);
        for (int i = 0; i < G.n_rival; ++i) {
          if (!G.rival_model[i]) continue;
          const vs_dress_t *dress = &G.rival_dress[i];
          int pack = G.rival_pack[i];
          int body = dress->aero && menu_aero(pack, dress->aero) ? dress->aero : 0;
          vinyl_tex(pack, body, G.rival_paint[i], dress->vinyl, dress->bonnet, &page1);
        }
        if (!app_vs4_initialized()) return;
      }
      perf_open();
      return;
    }
  }
  menu_scene scene;
  int has3d = menu_scene3d(&G.menu, &scene);
  menu_aero_sync(has3d ? &scene : NULL);
  wheel_sync(has3d ? &scene : NULL);
  get_wheel_model(has3d ? scene.get_wheel : 0);
  load_wants want;
  load_wants_now(has3d ? &scene : NULL, &want);
  if (G.low_memory) car_packs_trim(1, &want);
  car_paints_trim(&want, 0);
  load_sync(&want);
  int body_ready=app_body_menu_prepare(has3d?&scene:NULL);
  app_ghost_preview_prepare(has3d?&scene:NULL);
  /* NOW LOADING: the car select's cars on show, or the race title's course */
  int waiting = (has3d && (!scene_ready(&scene) || !body_ready)) || (G.menu.screen == MENU_PRE && !G.menu.ready);
  G.menu.loading = waiting ? G.menu.loading + 1 : 0;
  G.load_hurry = waiting || pre || menu_booting(&G.menu);
  G.load_wait = has3d && waiting;
  if (G.menu.screen != MENU_COURSE && G.menu.screen != MENU_TEN_COURSE && G.menu.screen != MENU_VS_AREA) G.mini_shown = NULL;
  if (!app_tick_only) menu_present(frame_start);
}

/* Presentation does not poll network, advance menu clocks, retry saves, publish
 * LOADED, or start physics. Loading uploads stay in the fixed menu pass. */
static void menu_present(double frame_start) {
#ifdef WMMT_NATIVE_VK
  render_display_clear(0, 0, 0, 1);
#else
  glViewport(0, 0, G.fb_w, G.fb_h);
  glClearColor(0, 0, 0, 1);
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
#endif
  menu_scene scene;
  int has3d = menu_scene3d(&G.menu, &scene);
  menu_draw(&G.menu, G.hud.screen_w, G.hud.screen_h, has3d ? menu_draw3d : NULL, &scene, mini_draw);
  app_body_notice();
  if (G.edge > 0 && !menu_photo_bg() && !anm_wide_drawn()) wide_sides();
  if (!G.loader) load_step(frame_start);
}

/* clCarDispManager::setupCar gives every car its shadow (clRenderShadow::createShadow) at
 * scale 1, 1.5 units below the car in world space */
#define SHADOW_DROP 1.5f

static void shadow_of(const mat4 *vp, const float *body, mat4 *out) {
  mat4 m;
  memcpy(m.m, body, sizeof m.m);
  m.m[13] -= SHADOW_DROP;
  *out = mat4_mul(*vp, m);
}

/* within far of the eye (a car's origin) */
static int near_eye(const float *m, const float *eye, float far) {
  float d[3] = { m[12] - eye[0], m[13] - eye[1], m[14] - eye[2] };
  return d[0] * d[0] + d[1] * d[1] + d[2] * d[2] <= far * far;
}

/* one pass of the race's cars, seen from eye_pos: the player's own (own: not from its roof),
 * the rivals' and the traffic's (those within far, 0 all) */
static void draw_race_cars(const car_state *c, const mat4 *vp, const float *eye_pos, int pass, int movie, int own,
                           float far, render_params *rp) {
  mat4 car_m;
  memcpy(car_m.m, c->body, sizeof car_m.m);
  float eye_car[3];
  eye_in(&car_m, eye_pos, eye_car);
  if (own) {
    float range = rp->range[WPK_GROUND];
    rp->range[WPK_GROUND] = 1e9f;
    car_paint_for_draw(G.race_model, G.aero_set ? &G.aero : NULL, chosen_color()->paint);
    rp->wheels = (const float (*)[16])c->tyre;
    rp->wheel_rot = c->tyre_rot;
    rp->braking = c->brake;
    rp->mirror = G.menu.mirror[G.menu.maker][G.menu.car];
    rp->wing = G.menu.wing[G.menu.maker][G.menu.car];
    rp->bonnet = G.menu.bonnet[G.menu.maker][G.menu.car];
    int wheel = G.menu.wheel[G.menu.maker][G.menu.car];
    rp->wheel_custom = wheel_on(wheel);
    rp->over = G.over_drawn ? OVER_AMOUNT : 0.0f;
    {
      const char *page1 = "";
      wpk_scene *cs = G.aero_set ? &G.aero : G.race_model;
      app_player_paint_scope body_scope={0};
      int appearance=app_body_race_apply(cs,&body_scope);
      int custom=BPC.race_frozen && BPC.race_view.custom_color;
      uint32_t vt = custom ? 0 : vinyl_tex(G.race_pack, G.aero_set, chosen_color()->paint, G.menu.vinyl[G.menu.maker][G.menu.car],
                              rp->bonnet, &page1), vold = 0;
      if (appearance) {
        int vi = vinyl_on(cs, vt, page1, &vold);
        if (ASB.active) app_story_body_draw(cs,vp,&car_m,eye_car,pass,rp,&ASB.own.view,G.race_pack);
        vinyl_off(cs, vi, vold);
        if (custom) app_player_paint_restore(&body_scope);
      }
    }
    draw_wheels(wheel, G.race_pack, G.aero_set, vp, &car_m, eye_car, pass, rp);
    rp->over = 0;
    /* the rivals' and the traffic's cars: stock */
    rp->mirror = rp->wing = rp->bonnet = rp->wheel_custom = 0;
    rp->wheels = NULL;
    rp->range[WPK_GROUND] = range;
  }
  for (int i = 0; i < CAR_RIVALS; ++i) {
    wpk_scene *model = movie ? G.movie_model[i] : G.rival_model[i];
    if (!c->rival_shown[i] || !model) continue;
    mat4 m;
    memcpy(m.m, c->rival_body[i], sizeof m.m);
    float eye[3];
    eye_in(&m, eye_pos, eye);
    rp->wheels = (const float (*)[16])c->rival_tyre[i];
    rp->wheel_rot = c->rival_tyre_rot[i];
    rp->braking = c->rival_brake[i];
    if (!movie && (G.vs_race || app_ghost_arcade_dressed())) {
      /* Actual opponent appearance: VS peer or pinned original Ghost profile. */
      const vs_dress_t *d = &G.rival_dress[i];
      int pack = G.rival_pack[i];
      wpk_scene *aero = d->aero ? menu_aero(pack, d->aero) : NULL;
      car_paint_for_draw(model, aero, G.rival_paint[i]);
      if (aero) model = aero;
      int body = aero ? d->aero : 0;
      rp->mirror = d->mirror, rp->wing = d->wing, rp->bonnet = d->bonnet;
      rp->wheel_custom = wheel_on(d->wheel);
      if(i==0 && AG.arcade && AG.active && AG.arcade_binding.custom_color) {
        app_ghost_paint_scope scope={0};
        app_player_paint_scope local_scope={0};
        if(!app_arcade_paint_apply(model,&scope,&local_scope)) {
          rp->mirror=rp->wing=rp->bonnet=rp->wheel_custom=0;rp->wheels=NULL;continue;
        }
        app_story_body_draw(model,vp,&m,eye,pass,rp,movie?NULL:&ASB.rival[i],movie?G.movie_pack[i]:G.rival_pack[i]);
        if(local_scope.cache)app_player_paint_restore(&local_scope);
        if(scope.cache)app_ghost_paint_restore(&scope); /* same WPK may be the player's model */
      } else {
        const char *page1 = "";
        uint32_t vt = vinyl_tex(pack, body, G.rival_paint[i], d->vinyl, d->bonnet, &page1), vold = 0;
        int vi = vinyl_on(model, vt, page1, &vold);
        app_story_body_draw(model,vp,&m,eye,pass,rp,movie?NULL:&ASB.rival[i],movie?G.movie_pack[i]:G.rival_pack[i]);
        vinyl_off(model, vi, vold);
      }
      draw_wheels(d->wheel, pack, body, vp, &m, eye, pass, rp);
      rp->mirror = rp->wing = rp->bonnet = rp->wheel_custom = 0;
    } else {
      car_paint_for_draw(model, NULL, movie ? G.movie_paint[i] : G.rival_paint[i]);
      app_story_body_draw(model,vp,&m,eye,pass,rp,movie?NULL:&ASB.rival[i],movie?G.movie_pack[i]:G.rival_pack[i]);
    }
    rp->wheels = NULL;
  }
  for (int i = 0; i < c->n_traffic; ++i) {
    const car_traffic *t = &c->traffic[i];
    mat4 m;
    memcpy(m.m, t->body, sizeof m.m);
    if (far > 0.0f && !near_eye(m.m, eye_pos, far)) continue;
    float eye[3];
    eye_in(&m, eye_pos, eye);
    if (G.traffic[t->model].n_batch) wpk_draw(&G.traffic[t->model], vp, &m, eye, pass, rp);
  }
}

static void draw_race_front_halos(const car_state *car, const mat4 *proj, const mat4 *view,
                                  const float *eye, int own, int mirror, render_params *rp) {
  if (!G.vs_race || G.vs_closed) return;
  if (own && car->spot && G.race_model && G.race_pack >= 0 && G.race_pack < CARDB_NPACKS)
    lights_draw_front_halo(proj, view, eye, car->body, CARDB_PACKS[G.race_pack], G.aero_set, mirror, rp);
  for (int i = 0; i < CAR_RIVALS; ++i) {
    int pack = G.rival_pack[i];
    if (!car->rival_shown[i] || !car->rival_spot[i] || !G.rival_model[i] ||
        pack < 0 || pack >= CARDB_NPACKS) continue;
    int aero = G.rival_dress[i].aero;
    if (aero && !menu_aero(pack, aero)) aero = 0;
    lights_draw_front_halo(proj, view, eye, car->rival_body[i], CARDB_PACKS[pack], aero, mirror, rp);
  }
}

/* The back mirror (clBackMirror, clGraphicFrame's traverse and drawHigh): clRaceThread::yield
 * shows it while the camera looks from the roof (the play view 0: CSeq::GetInfoMirrorCamera),
 * outside the 10-in-a-row and before the goal (play state 8), its own scene drawn into a
 * 200x72 target at the camera's fov across it, then put at x 220..420, 15..87 down the
 * arcade's 640x480, flipped left to right. The OPTION screen turns it off (the port's).
 * The arcade's scene is the lua's BackmirrorModel (the ground only) to 50 m (far 500) on a
 * pale clear colour, which showed as holes where the tunnels' roofs and the walls past 50 m
 * were (Allan, 10-26): the port's draws the sky box, the ground to BM_FAR and the buildings
 * beside it to BM_SHORT (the harness's morning C1: 67 draws, 20k triangles; the far ones 80,
 * 24k), fading into the fog's colour from BM_FOG on. */
#define BM_X 220.0f
#define BM_Y 15.0f
#define BM_W 200.0f
#define BM_H 72.0f
#define BM_FAR 1000.0f
#define BM_SHORT 600.0f
#define BM_FOG 300.0f
static void draw_backmirror(const car_state *c, int movie) {
  G.bm_shown = G.bm_draws = G.bm_tris = 0;
  G.bm_ms = 0;
  if (movie || !c->mirror || G.n_ten || !G.menu.bm_on || G.phone || c->race.play_state >= 7 || getenv("WMMT_NO_BM")) return;
  double t0 = now_ms();
  float k = (float)G.fb_h / 480.0f;
  int w = (int)(BM_W * k + 0.5f), h = (int)(BM_H * k + 0.5f);
  if (render_backmirror_begin(w, h, G.rp.fog_color)) return;
  float aspect = BM_W / BM_H;
  float fovy = 2.0f * atanf(tanf(c->mirror_fov * 0.5f) / aspect);
  mat4 view;
  memcpy(view.m, c->mirror_view, sizeof view.m);
  mat4 proj = mat4_perspective(fovy, aspect, c->mirror_near, BM_FAR);
  mat4 vp = mat4_mul(proj, view);
  float eye[3];
  const float *V = c->mirror_view;
  for (int j = 0; j < 3; j++) eye[j] = -(V[12] * V[4 * j] + V[13] * V[4 * j + 1] + V[14] * V[4 * j + 2]);
  render_params rp = G.rp;
  rp.range[WPK_GROUND] = BM_FAR;
  rp.range[WPK_SHORT] = BM_SHORT;
  rp.range[WPK_LONG] = -1.0f;
  rp.fog_near = BM_FOG;
  rp.fog_far = BM_FAR;
  rp.object_visible = NULL;
  rp.n_objects = 0;
  rp.draws = rp.triangles = rp.new_chunks = 0;
  /* the sky box, as the race's (no fog, behind everything) */
  wpk_scene *sky = &G.sky[G.track_zone];
  if (sky->n_batch) {
    mat4 sky_vp = mat4_mul(mat4_perspective(fovy, aspect, 100.0f, 600000.0f), view);
    mat4 sky_m = mat4_identity();
    sky_m.m[12] = eye[0];
    sky_m.m[13] = eye[1] - SKY_DROP;
    sky_m.m[14] = eye[2];
    const float sky_eye[3] = { 0, SKY_DROP, 0 };
    render_params sky_rp = { .night = G.track_zone == 1, .fog_far = 2e9f, .fog_near = 1e9f, .range = { 1e9f, 1e9f, 1e9f } };
    render_begin(&sky_rp);
    for (int pass = 0; pass < WPK_PASSES; ++pass) {
      render_blend_pass(pass == WPK_BLEND);
      wpk_draw(sky, &sky_vp, &sky_m, sky_eye, pass, &sky_rp);
    }
    render_blend_pass(0);
    
#ifdef WMMT_NATIVE_VK
    render_scene_depth_clear();
#else
    glClear(GL_DEPTH_BUFFER_BIT);
#endif
    rp.draws += sky_rp.draws;
    rp.triangles += sky_rp.triangles;
  }
  set_car_light(&rp, &CAR_LIGHT[G.track_city][G.track_zone], &view);
  render_begin(&rp);
  mat4 ident = mat4_identity();
  for (int pass = 0; pass < WPK_PASSES; ++pass) {
    render_blend_pass(pass == WPK_BLEND);
    wpk_draw(&G.track, &vp, &ident, eye, pass, &rp);
    /* not the player's own car: its body, wing or roof parts filled the view from the arcade's
     * mirror camera (a HIACE, an aero kit: Allan, 10-26) */
    draw_race_cars(c, &vp, eye, pass, 0, 0, BM_FAR, &rp);
  }
  draw_race_front_halos(c, &proj, &view, eye, 0, 1, &rp);
  render_blend_pass(0);
  render_backmirror_end();
  G.bm_shown = 1;
  G.bm_draws = rp.draws;
  G.bm_tris = rp.triangles;
  G.bm_ms = now_ms() - t0;
}

/* the player's car's and the traffic's shadows, onto what the opaque passes drew */
static void draw_shadows(const car_state *c, const mat4 *vp, const mat4 *car_m) {
  const wpk_scene *s[1 + CAR_RIVALS + CAR_TRAFFIC];
  mat4 mvp[1 + CAR_RIVALS + CAR_TRAFFIC];
  int n = 0;
  if (G.camera == 0 && G.race_model) {
    s[n] = G.aero_set ? &G.aero : G.race_model;
    shadow_of(vp, car_m->m, &mvp[n++]);
  }
  for (int i = 0; i < CAR_RIVALS; ++i)
    if (c->rival_shown[i] && G.rival_model[i]) {
      s[n] = G.rival_model[i];
      shadow_of(vp, c->rival_body[i], &mvp[n++]);
    }
  for (int i = 0; i < c->n_traffic && n < 1 + CAR_RIVALS + CAR_TRAFFIC; ++i) {
    const car_traffic *t = &c->traffic[i];
    if (!G.traffic[t->model].n_batch) continue;
    s[n] = &G.traffic[t->model];
    shadow_of(vp, t->body, &mvp[n++]);
  }
  render_shadows(s, mvp, n, &G.rp);
}

/* a point in a model's local frame (its matrix a rotation and a translation) */
static void eye_in(const mat4 *m, const float *p, float *out) {
  float r[3] = { p[0] - m->m[12], p[1] - m->m[13], p[2] - m->m[14] };
  for (int j = 0; j < 3; ++j) out[j] = r[0] * m->m[4 * j] + r[1] * m->m[4 * j + 1] + r[2] * m->m[4 * j + 2];
}

void app_frame(float dt) {
#if defined(__ANDROID__) && defined(WMMT_DEBUG_LOG)
  float debug_raw_dt = dt;
#endif
  double frame_start = now_ms();
  G.frame_start = frame_start;
  anm_trim();
  if (dt > 0.1f) dt = 0.1f;
#if defined(__ANDROID__) && defined(WMMT_DEBUG_LOG)
  debug_frame(debug_raw_dt, dt);
#endif
  if (!app_tick_only && dt > 0) G.fps += (1.0f / dt - G.fps) * 0.05f;
  wpk_ao(G.ao_test >= 0 ? G.ao_test : G.menu.ao_on);
#ifdef WMMT_EGL
  /* test: the versus stars screen for "stars change [wins]" once the car or game mode select is up */
  static int star_test;
  if (getenv("WMMT_STAR") && !star_test && G.in_menu && (G.menu.screen == MENU_MAKER || G.menu.screen == MENU_GAME)) {
    star_test = 1;
    int from = 0, d = 0, w = 0;
    sscanf(getenv("WMMT_STAR"), "%d %d %d", &from, &d, &w);
    G.menu.star_from = from, G.menu.star_delta = d;
    G.menu.vs_stars_car[G.menu.maker][G.menu.car] = from + d;
    G.menu.vs_wins_car[G.menu.maker][G.menu.car] = w;
    menu_vs_star_open(&G.menu);
  }
#endif
  if (G.in_menu) {
#ifdef __ANDROID__
    timing60_sim_reset(&android_sim);
#endif
    menu_frame(dt, frame_start);
    perf_menu(dt, now_ms() - frame_start);
    return;
  }

  if (G.vs_race && app_vs4_native_gate() < 0) { menu_frame(0,frame_start); return; }

  /* Lost player presentation never silently becomes a different factory colour.
   * Abort at the next safe frame boundary, without committing a Ghost/TA result. */
  if (!ASB.active || !menu_story_body_owner_same(&G.menu,&ASB.own)) BPC.draw_fault=1;
  if (BPC.draw_fault) {
    int ghost=app_ghost_mode(), versus=G.vs_race;
    app_ta_rank_invalidate(); app_rotary_stop(); app_body_drop(0);
    snd_quiet(); car_clear_junction(&G.car.race);
    G.in_menu=1; G.paused=0;
    if (ghost) {
      app_ghost_fail("PLAYER APPEARANCE LOST - RUN CANCELLED");
      menu_frame(0,frame_start); return; /* retain the actionable Ghost invalid page */
    }
    if (versus) {
      app_vs4_cancel("PLAYER APPEARANCE LOST - ROUND CANCELED");
      menu_frame(0,frame_start); return;
    }
    story_race_start_failed();
    menu_frame(0,frame_start);
    return;
  }
  /* A lost exact opponent appearance invalidates at this safe frame boundary,
   * BEFORE any further native physics/RNG/input tick. Never draw a base fallback. */
  if(app_ghost_mode() && ACP.draw_fault) {
    app_ghost_fail("EXACT GHOST APPEARANCE LOST - RACE INVALIDATED");
    snd_quiet();hud_init(&G.hud,G.hud.screen_w,G.hud.screen_h);
    car_clear_junction(&G.car.race);menu_frame(0,frame_start);return;
  }
  /* Ghost is never governed by room state. Polling continues independently of
   * user pause and soft transport pause, and cancellation wins before any tick. */
  if (app_ghost_mode()) G.vs_race = G.vs_closed = G.vs_wait = G.n_ten = 0;
  int movie = G.movie_len > 0;
  /* Handle a goal already observed before this display frame as well as one
   * reached inside the fixed-step loop below. */
  if (!movie && !G.vs_closed && !G.menu.finish && !G.story_end_started &&
      !G.vs_race && !G.n_ten && G.menu.game == MENU_GAME_STORY && G.rival >= 0 &&
      G.car.race.over && G.car.race.state == CAR_RACE_GOAL) {
    hud_story_cutin_step(&G.car.race, 0);
    G.story_end_started = 1;
    G.story_end_freeze = hud_story_cutin_goal_hold(&G.car.race);
#ifdef __ANDROID__
      if (G.story_end_freeze > 0) android_story_bgm_pause();
#endif
  }
  car_input in = {0};
  G.hud.passing_available = !movie && G.vs_race && !G.vs_wait && !G.vs_closed &&
      !G.paused && !G.menu.finish && !G.car.race.over && G.car.race.play_state == 2;
  if (!G.hud.passing_available) G.hud.passing_pressed = 0;
  int steps = 0;
  double t0 = now_ms();
  /* Once closure is known, keep polling and drawing the notice, but do not
   * consume race input, simulate, mutate race state or commit results. */
  if (!G.vs_closed) {
  /* the pause menu: the race stands still under it (not once the race has stopped running) */
  if (!movie && !G.hud.pause_disabled && G.hud.pause_pressed && !G.paused &&
      !G.menu.finish && G.car.race.state == CAR_RACE_RUN) {
    G.paused = 1;
    hud_init(&G.hud, G.hud.screen_w, G.hud.screen_h); /* let go of the pedals and the wheel */
    menu_pause_open(&G.menu);
  }
#ifdef __ANDROID__
  int android_was_paused = G.paused && !G.vs_race;
#endif
  if (G.paused) {
#ifdef __ANDROID__
    if (!G.vs_race) timing60_sim_reset(&android_sim);
#endif
    snd_quiet();
    int r = menu_pause_update(&G.menu, dt);
    if (r == MENU_LEAVE) {
      /* the screen is white: on to the menus, which come out of it (a story select starts
       * over from its first race) */
      G.paused = 0;
      if (app_ghost_mode()) app_ghost_fail("RUN CANCELLED - PREVIOUS RECORD KEPT");
      G.story_race = 0;
      G.story_cut_pending = 0;
      story_carry_cancel();
      if (G.vs_race) { app_vs4_cancel("YOU CANCELED THE ROUND - BACK IN ROOM");menu_frame(0,frame_start);return; }
      hud_init(&G.hud, G.hud.screen_w, G.hud.screen_h);
      G.in_menu = 1;
      if (G.perf) fflush(G.perf);
      menu_frame(0, frame_start);
      return;
    }
    if (r == MENU_RESUME) G.paused = 0, G.hud.pause_pressed = 0;
  }
  /* the race's end, FINISH or TIME UP over the race running on, then white: the menus */
  if (G.menu.finish && G.menu.crown_award.active && G.menu.crown_award.pending)
    app_cloud_crown_tick(android_ghost_cloud_configured(),0);
#ifdef __ANDROID__
  if(G.menu.finish && G.menu.game==MENU_GAME_TA)app_ta_rank_cloud_tick(-1);
#endif
  if (G.menu.finish && menu_finish_update(&G.menu, dt) == MENU_LEAVE) {
    if (app_ghost_mode()) {
      app_ghost_clear();
      G.n_rival = 0;
      memset(G.rival_model, 0, sizeof G.rival_model);
    }
    snd_quiet();
    hud_init(&G.hud, G.hud.screen_w, G.hud.screen_h);
    G.in_menu = 1;
    if (G.vs_race) app_vs4_result_ui_left(); /* DONE only after stars reach MENU_VS. */
    if (G.perf) fflush(G.perf);
    menu_frame(0, frame_start);
    return;
  }

  /* input and simulation (the arcade's fixed 60 Hz frames) */
  hud_options();
  hud_input_dt(&G.hud, &in, dt);
  if (G.story_end_freeze > 0 || G.story_old_ended)
    G.hud.camera_pressed = G.hud.reset_pressed = 0;
  if (G.hud.camera_pressed) {
    G.camera ^= 1;
    car_view(G.camera ? CAR_VIEW_ROOF : CAR_VIEW_BEHIND);
    G.hud.camera_pressed = 0;
  }
  /* the reset key: the car back on the road once it is in the player's hands (not over the
   * rolling start's pilot, a beaten rival's still frames or the finish) */
  if (G.vs_race) G.hud.reset_pressed=0;
  if (G.hud.reset_pressed) {
    const car_race *r = &G.car.race;
    if (r->state == CAR_RACE_RUN && r->countdown <= 0.0f && r->play_state == 2) {
      app_ta_rank_invalidate();
      AGR.token=0;
#ifdef __ANDROID__
      player_smoke_reset(); /* explicit warp fence, including the early tick2 alias */
#endif
      car_reset(&G.car);
    }
    G.hud.reset_pressed = 0;
  }
  /* app_present supplies one exact 60 Hz logic interval, never display cadence.
   * Legacy platforms retain their existing vsync-rounded behavior below. */
  t0 = now_ms();
#ifdef __ANDROID__
  /* The first two frames include race setup and initial GPU warm-up, not driving time. */
  steps = timing60_race_steps(&android_sim, dt, android_was_paused, G.race_frames < 2);
#else
  steps = (int)(dt * 60.0f + 0.5f);
  if (steps < 1 || G.race_frames < 2) steps = 1;
#endif
  if (G.paused && !G.vs_race) steps = 0; /* a versus runs on with the others under it */
  if (G.vs_race && (!net_native_allowed() || AV4.local_finished)) steps=0;
  if (G.period_in > 0) G.period_in -= steps;
  if (movie) { /* clRaceThread::race: the movie's frames, then the race */
    for (int i = 0; i < steps && G.movie_len > 0; ++i) {
      /* its show's frame first: while that holds the movie (clEffectTable +0x1e0), the movie's
       * time stands and its picture with it (clGraphicFreezeCallback) */
      if (hud_demo_step()) continue;
      G.movie_frame += 1.0f;
      if (G.movie_frame >= G.movie_len) movie_close();
      else car_movie_update(&G.car, G.movie_frame);
    }
    if (G.in_menu) { menu_frame(0, frame_start); return; }
    steps = 0;
  } else if (G.movie_in > 0) {
    G.movie_in -= steps;
  }
  int frozen = G.ten_freeze > 0 || G.story_end_freeze > 0;
  if (G.ten_freeze > 0) {
    G.ten_freeze -= steps;
    hud_ten_cutin(&G.car.race, steps);
    steps = 0;
    if (G.ten_freeze <= 0 && !G.ten_bgm_off) G.ten_white = 1; /* more rivals: white out */
  } else if (G.story_end_freeze > 0) {
    /* Keep the race fixed while advancing the result dialogue independently.
     * The 180-tick baseline is observed in runNegate; longer bounded holds
     * let this port's serial dialogue queue finish and are not arcade timing. */
    int n = steps < G.story_end_freeze ? steps : G.story_end_freeze;
    for (int i = 0; i < n; ++i) hud_story_cutin_step(&G.car.race, 0);
    G.story_end_freeze -= n;
    steps = 0;
  }
#ifdef __ANDROID__
  /* hud_input consumes edge pulses: preserve them if no simulation tick ran. */
  if (!steps && !movie && !frozen && !G.story_old_ended && !(G.paused && !G.vs_race) && !android_was_paused) {
    G.hud.shift_up += in.shift_up;
    G.hud.shift_down += in.shift_down;
    G.hud.passing_pressed |= in.passing;
  }
#endif
  int story_was_old_ended = G.story_old_ended;
  int story_tail_ticks = story_was_old_ended ? steps : 0;
  int physics_steps = story_was_old_ended ? 0 : steps;
  for (int i = 0; i < physics_steps; ++i) {
    if (G.vs_race) {
      int gate=app_vs4_native_gate();
      if(gate<0){menu_frame(0,frame_start);return;}
      if(!gate)break;
    }
    if (G.ten_white && ++G.ten_white > 1 + TEN_WHITE_HOLD + TEN_WHITE_FADE) G.ten_white = 0;
#if defined(__ANDROID__) && defined(WMMT_DEBUG_LOG)
    ++debug_sim_seq;
    int debug_on = debug_log_enabled();
    debug_snapshot debug_before;
    if (debug_on) debug_before = debug_capture();
#endif
    car_update(&G.car, &in);
    if (!G.vs_race) app_ta_rank_tick();
    /* link_receive can latch cancellation inside the native call. Its current
     * call cannot be interrupted, but no subsequent tick/result is permitted. */
    if (G.vs_race && app_vs4_native_gate()<0) {menu_frame(0,frame_start);return;}
#ifdef __ANDROID__
    /* Sampling once per simulated tick avoids dropping effects at high refresh;
     * the arcade invokes this from its display manager, so cadence may differ. */
    if (!movie) {
      player_tracks_tick(&G.car);
      player_smoke_tick(&G.car);
    }
    race_tail_tick(movie);
#endif
    if (app_ghost_mode() && G.car.race.over) break; /* next ordinary 60Hz tick may finish step3 sampling */
#ifdef __ANDROID__
    if (G.car.race.jct_select_valid) {
      junction_ui_tick(&race_junction_ui, G.car.race.jct_state, G.car.race.jct_left_area,
                       G.car.race.jct_right_area, G.car.race.jct_distance, 0, 0);
      junction_barrier_point line[3];
      const junction_barrier_point *a = NULL, *b = NULL, *mid = NULL;
      if (G.car.race.jct_line_valid) {
        for (int k = 0; k < 3; ++k) memcpy(line[k].v, G.car.race.jct_line[k], sizeof line[k].v);
        a = &line[0]; b = &line[1]; mid = &line[2];
      }
      junction_barrier_tick(&race_junction_barrier, G.car.race.jct_state, 0, 0,
                            a, b, mid, G.car.race.jct_distance);
    } else {
      junction_ui_reset(&race_junction_ui);
      junction_barrier_reset(&race_junction_barrier);
    }
#endif
#if defined(__ANDROID__) && defined(WMMT_DEBUG_LOG)
    if (debug_on) {
      debug_snapshot debug_after = debug_capture();
      if (debug_sim_sample(&debug_before, &debug_after, &in)) {
        debug_step("before", i, &in, &debug_before);
        debug_step("after", i, &in, &debug_after);
        debug_nearby(i);
      }
    }
#endif
    backfire_tick();
    in.shift_up = in.shift_down = in.passing = 0;
    /* clCarEffectManager::update's sparks, each car's */
    spark_step(0, G.car.body, &G.car.effect);
    for (int k = 0; k < CAR_RIVALS; ++k)
      spark_step(1 + k, G.car.rival_body[k], G.car.rival_shown[k] ? &G.car.rival_effect[k] : NULL);
    hud_ten_cutin(&G.car.race, 1);
    /* A continuous period's Suspend is not the episode result. Do this even
     * when the optional carry bridge is unavailable and the next Init falls back. */
    if (story_period_suspend()) hud_story_cutin_suspend();
    else hud_story_cutin_step(&G.car.race, G.car.wall_hit > 0.0f);
    if (story_carry_capture()) {
      /* End destroyed the old sequence. Preserve the remaining UI ticks,
       * but never run another physics tick against those objects. */
      story_tail_ticks = physics_steps - i - 1;
      break;
    }
    if (G.car.race.over && !G.menu.finish && !G.story_end_started &&
        !G.vs_race && !G.n_ten && G.menu.game == MENU_GAME_STORY && G.rival >= 0 &&
        G.car.race.state == CAR_RACE_GOAL) {
      G.story_end_started = 1;
      G.story_end_freeze = hud_story_cutin_goal_hold(&G.car.race);
#ifdef __ANDROID__
      if (G.story_end_freeze > 0) android_story_bgm_pause();
#endif
      break; /* no additional physics steps after the goal in a multi-step frame */
    }
    /* clRaceThread::race on a 10-in-a-row rival beaten (play state 9, one arcade frame): the
     * picture stands still 60 frames (the graphics on clGraphicFreezeCallback, nothing run),
     * colours inverted (clGraphicFrame +0x174, neg.cg), with cutin2 (SE 0x4c) and the beaten
     * one's line coming up (Cut::clCutIn::Update each frame); after the last rival the BGM
     * stops (clAudio::stopStream) */
    if (G.n_ten && G.car.race.play_state == 9 && !G.ten_beaten_on) {
      G.ten_beaten_on = 1;
      G.ten_freeze = 60;
      snd_menu(SND_BEATEN);
      if (G.car.race.ten_beaten >= G.n_ten) G.ten_bgm_off = 1;
      break;
    }
    if (G.car.race.play_state != 9) G.ten_beaten_on = 0;
    if (G.vs_race && G.car.race.over && !G.menu.finish) break; /* FINISH outside loop, no extra native goal ticks. */
  }
  /* A stopped old sequence has no physics, but dialogue still uses UI time. */
  for (int i = 0; i < story_tail_ticks; ++i) hud_story_cutin_step(&G.car.race, 0);
  if (!G.vs_closed && !G.vs_wait && !G.paused && !frozen && !movie) snd_update(&G.car, &in, dt);
  if (G.vs_closed || G.vs_wait || G.paused || frozen || movie || G.story_old_ended || G.story_end_freeze > 0 || G.ten_freeze > 0)
    snd_rev_quiet(); /* A stopped physics loop must not leave the rev buzzer sounding. */
  /* the time attack console's sounds: TIME EXTEND at a checkpoint, the last seconds' ticks */
  car_race *race = &G.car.race;
  if (!movie) app_ta_replay_finish();
  if (app_ghost_finish()) {
    snd_quiet(); hud_init(&G.hud, G.hud.screen_w, G.hud.screen_h);
    car_clear_junction(&G.car.race);
    if (G.perf) fflush(G.perf);
    menu_frame(0, frame_start); return;
  }
  /* the 10-in-a-row's rival of the round */
  if (G.n_ten && race->ten_rival >= 0 && race->ten_rival < G.n_ten && G.ten_pack[race->ten_rival] >= 0) {
    G.rival_model[0] = car_pack(G.ten_pack[race->ten_rival]);
    G.rival_paint[0] = G.ten_paint[race->ten_rival];
  }
  /* clRaceThread::race and changeTenRival as each rival is set up: approach2, the last's approach3 */
  if (G.n_ten && race->ten_rival >= 0 && race->ten_rival != G.ten_rival_on) {
    G.ten_rival_on = race->ten_rival;
    if (race->ten_rival > 0 && race->ten_rival < G.n_ten) {
      const char *cue = ten_round_bgm(&G.menu, race->ten_rival);
      /* setNextBgm keeps a cue already playing; a repeated round does not rewind it. */
      if (cue) {
        G.ten_bgm_round = race->ten_rival;
        if (!G.ten_bgm || strcmp(cue, G.ten_bgm)) G.ten_bgm = cue;
      }
    }
    snd_menu(race->ten_rival == G.n_ten - 1 ? SND_APPROACH3 : SND_APPROACH2);
  }
  int ta_checkpoint = G.menu.game == MENU_GAME_TA && hud_ta_checkpoint(race);
  if (race->extended > 0 || ta_checkpoint) {
    snd_menu(SND_TIME_EXTEND);
    if (!ta_checkpoint) hud_time_extend(race->total);
  }
  race->extended = 0;
  int left = (int)race->time_left;
  if (left < G.time_shown && left <= 9 && race->state != CAR_RACE_GOAL)
    snd_menu(left >= 5 ? SND_TIME_COUNT : SND_TIME_COUNT_LAST);
  G.time_shown = left;
  /* the start's countdown (clStandardConsole::update -> clCountDownConsole::setCountDown):
   * (int)(the seconds left + 1/12) as it changes; 2 and 1 with start321, 0 (GO) with start_go */
  int count = race->countdown > 0.0f ? (int)(race->countdown + 1.0f / 12.0f) : 0;
  if (count != G.count_shown && count <= 2) snd_menu(count ? SND_START321 : SND_START_GO);
  G.count_shown = count;
  /* the route sign's sound (clSignConsole::draw): as it comes, and the blinking ones' every
   * 20 frames while they stay; turning2 for those, turning3 for the green arrows */
  int sign = race->state == CAR_RACE_RUN ? race->sign : 0;
  if (sign != G.sign) {
    G.sign = sign;
    G.sign_t = 0;
  }
  if (G.sign > 0 && G.sign <= HUD_SIGNS && G.sign_t <= 0) {
    snd_menu(hud_sign_blinks(G.sign) ? SND_TURN2 : G.sign >= 12 ? SND_TURN3 : SND_TURN);
    G.sign_t = hud_sign_blinks(G.sign) ? 20 : 1 << 30;
  }
  G.sign_t -= steps;
  if (race->state == CAR_RACE_RUN && race->countdown <= 0.0f) {
    G.top_kmh = fmaxf(G.top_kmh, car_kmh(&G.car));
  }
#ifdef WMMT_EGL
  if (getenv("WMMT_ST_END") && (G.rival >= 0 || G.vs_race) && !movie && G.race_frames > atoi(getenv("WMMT_ST_END")))
    race->over = race->won = 1; /* test: the story race won after this many frames */
#endif
  if (race->over && !G.menu.finish && !movie && !G.story_end_started &&
      !G.vs_race && !G.n_ten && G.menu.game == MENU_GAME_STORY && G.rival >= 0 &&
      race->state == CAR_RACE_GOAL) {
    G.story_end_started = 1;
    G.story_end_freeze = hud_story_cutin_goal_hold(&G.car.race); /* bounded result-dialogue hold */
#ifdef __ANDROID__
    if (G.story_end_freeze > 0) android_story_bgm_pause();
#endif
  }
  int vs_finish_ready = 1;
  if (G.vs_race && race->over && !G.menu.finish) {
    vs_finish_ready=app_vs4_finish_ready();
    if(vs_finish_ready<0){menu_frame(0,frame_start);return;}
  }
  if (!app_ghost_mode() && race->over && !G.menu.finish && !G.vs_closed && !movie && G.story_end_freeze <= 0 && vs_finish_ready) {
    int goal = race->state == CAR_RACE_GOAL;
    menu_result res;
    if (G.vs_race) {
      /* the versus: its place (GetPlayResult) as the story's WIN or LOSE */
      int place = race->vs_place > 0 ? race->vs_place : G.vs_race + 1;
      menu_finish_open(&G.menu, goal, NULL);
      menu_finish_vs(&G.menu, place, G.vs_race + 1);
      if (!G.menu.save_skip && G.menu.own_sel >= 0 && G.menu.own_sel < G.menu.n_own) {
        unsigned char *style = &G.menu.drive_style_car[G.menu.maker][G.menu.car];
        *style = (unsigned char)car_vs_drive_style(*style);
      }
      app_finish_mileage();
      if (place == 1) G.menu.vs_wins_car[G.menu.maker][G.menu.car]++;
      int stars = menu_vs_stars(&G.menu, place, G.vs_race + 1);
      fprintf(stderr, "versus: stars %d -> %d (%+d)\n", G.menu.star_from, G.menu.star_from + stars, stars);
      title_race_over(TITLE_VS, place == 1, race, G.race_course, 0);
      garage_save();
      fprintf(stderr, "versus: place %d of %d, %.2f s\n", place, G.vs_race + 1, race->total);
    } else if (G.rival >= 0 && G.menu.game == MENU_GAME_STORY) {
      /* a story race: WIN moves the story on, no time attack records */
      /* a select with a second race (clEffStoryType's periods: select 0 runs series 24, then 25
       * against the Z31 and the Blackbird) goes on to it; the last race's WIN moves the story on */
      int pick = G.menu.story_pick;
      int next = race->won && RIVALDB[G.rival].select == pick ? story_next_race(pick, G.story_race) : -1;
      int fade = next >= 0 && pick >= 0 && pick < STORYRACE_SELECTS && G.story_race < 5 ? STORYRACE_FADE[pick][G.story_race] : 0;
      if (!G.menu.story_test) story_race_commit(race->won && RIVALDB[G.rival].select == pick, next < 0);
      menu_finish_open(&G.menu, goal, NULL);
      menu_finish_story(&G.menu, race->won, next >= 0, race->gap, fade);
      if (next >= 0) {
        G.story_mileage_pending_mm = race->story_distance_valid && isfinite(race->story_distance)
          ? fmaxf(race->story_distance, 0.0f) * 1000.0f : 0.0f;
        G.story_race++;
        G.story_cut_pending = 1;
        G.story_cut_select = pick;
        G.story_cut_loop = menu_story_cut_loop(G.menu.st_div, G.menu.story_test);
        G.story_cut_period = G.story_race;
      } else {
        G.story_cut_pending = 0;
        G.story_race = 0;
        app_finish_mileage();
        /* the points first: whether the episode was cleared before counts */
        if (!G.menu.story_test) {
        int units = menu_story_points(&G.menu, race->won && RIVALDB[G.rival].select == pick);
        menu_story_lost(&G.menu, race->won && RIVALDB[G.rival].select == pick);
        fprintf(stderr, "story points: +%d units, gauge %d, tune due %d\n", units,
                G.menu.st_gauge[G.menu.maker][G.menu.car], G.menu.st_tune_due);
        /* no dress-up parts: the arcade's come from ghost battle only (Allan, 10-24) */
        int cleared = race->won && RIVALDB[G.rival].select == pick;
        if (cleared) {
          menu_story_clear(&G.menu, G.menu.story_n);
          menu_lvup_check(&G.menu);
        }
        /* getStorySuccessiveVictoryCount: the episodes won in a row */
        short *streak = &G.menu.st_streak_car[G.menu.maker][G.menu.car];
        *streak = cleared ? (short)(*streak < 30000 ? *streak + 1 : *streak) : 0;
        title_race_over(TITLE_STORY, cleared, race, G.race_course, 0);
        garage_save();
        story_verify_garage();
        G.menu.garage_changed = 0;
        }
      }
      fprintf(stderr, "story race: %s, select %d race %d, story div %d bits %05x\n", race->won ? "WIN" : "LOSE", pick,
              G.story_race, G.menu.st_div, G.menu.st_bits);
    } else if (G.n_ten) {
      /* the 10-in-a-row's end: clTenResult */
      fprintf(stderr, "ten race: %s, %d rivals beaten, %.2f s, medal %d\n", race->won ? "CLEAR" : "OVER", race->ten_beaten,
              race->ten_now, race->ten_medal);
      /* clRaceThread::finiTen: all ten beaten outside the extend mode, the medal onto the card
       * when it beats the one there */
      signed char *best = &G.menu.ten_result[menu_ten_course(&G.menu)][G.menu.ten_level];
      if (G.menu.ten_level < 10 && race->ten_medal > *best) {
        *best = (signed char)race->ten_medal;
        menu_lvup_check(&G.menu);
      }
      menu_finish_open(&G.menu, goal, NULL);
      app_finish_mileage();
      title_race_over(TITLE_TEN, race->won, race, G.race_course, 0);
      garage_save();
      int beaten = race->ten_beaten, medal = race->ten_medal;
      if (getenv("WMMT_TEN_RES")) sscanf(getenv("WMMT_TEN_RES"), "%d %d", &beaten, &medal); /* test: this end */
      menu_finish_ten(&G.menu, beaten, race->ten_now, medal);
      menu_dress_win(&G.menu, getenv("WMMT_DRESS_WIN") ? atoi(getenv("WMMT_DRESS_WIN")) : beaten);
    } else {
      if (goal) app_ta_rank_finish(race);
      if (goal) records_goal(G.menu.course, race, &res, !G.race_traffic);
      int local_title_record=goal && !G.race_traffic && res.rank==1;
      if (goal) app_ta_rank_result(&res);
      menu_finish_open(&G.menu, goal, goal ? &res : NULL);
      app_finish_mileage();
      title_race_over(TITLE_TA, goal, race, G.menu.course, local_title_record);
      garage_save();
    }
  }
  } /* !G.vs_closed: only the renderer and closure notice continue below */
  double t1 = now_ms();
  app_display_input = in;
  if (G.car.race.state == CAR_RACE_RUN) {
    float aspect = (float)G.fb_w / (float)G.fb_h;
    float fovy = 2.0f * atanf(tanf(G.car.cam_fov * 0.5f) / (4.0f / 3.0f));
    mat4 proj = mat4_perspective(fovy, aspect, G.car.cam_near, 20000.0f);
    hud_rival_view(G.car.cam_view, proj.m);
    if (AG.active && AG.arcade) {
      car_ghost_observation opponent;
      int valid = car_ghost_status(&opponent) && opponent.session_token == AG.token &&
                  opponent.kind == AG.config.kind && opponent.status == CAR_GHOST_RUNNING &&
                  (opponent.native_target_valid || opponent.native_default_ai_valid);
      hud_set_ghost_gap(valid ? opponent.live_gap_mm : NAN);
    }
    hud_visual_tick(&G.car);
  }
  if (!app_tick_only) app_draw_frame(dt, &in, steps, t1 - t0, &G.car);
}

static void app_draw_frame(float dt, const car_input *input, int steps, double physics_ms, const car_state *c) {
  car_input in = *input;
  int movie = G.movie_len > 0;
  double t1 = now_ms();
  wpk_ao(G.ao_test >= 0 ? G.ao_test : G.menu.ao_on);
  /* the overhead map for the player's car first, before anything goes to the frame's own
   * target (a tile renderer would store the frame and load it again to come back to it) */
  {
    double o0 = now_ms();
    G.over_draws = G.over_tris = 0;
    if (G.no_over || !G.menu.over_on || !(G.camera == 0 || movie)) {
      G.over_drawn = 0;
    } else if (!(G.race_frames & 1) || !G.over_drawn) {
      /* Every other presentation: a GPU-cost cadence, not a gameplay clock. */
      mat4 body;
      memcpy(body.m, c->body, sizeof body.m);
      const wpk_scene *over[2] = { &G.track, &G.arrows[G.track_zone] };
      int t0 = G.rp.triangles;
      G.over_draws = render_overhead(over, 2, &body, &G.rp);
      G.over_tris = G.rp.triangles - t0;
      G.over_drawn = G.over_draws >= 0;
    }
    G.over_ms = now_ms() - o0;
  }

  draw_backmirror(c, movie);

  /* render: into the radial blur's texture while the camera asks for it (or the sharpening) */
  int sharp = G.menu.sharp_on && !G.no_sharp;
  if (sharp && dt > 1.5f / 60.0f && G.race_frames > 2) G.sharp_rest = SHARP_REST;
  else if (G.sharp_rest > 0) G.sharp_rest = G.sharp_rest > steps ? G.sharp_rest - steps : 0;
  if (sharp && G.sharp_rest > 0) G.sharp_rested++;
  render_sharpen(sharp && !G.sharp_rest ? SHARP_AMOUNT : 0.0f, sharp);
  int blurred = render_blur_begin(G.phone ? 0.0f : c->cam_blur, G.fb_w, G.fb_h);
#ifndef WMMT_NATIVE_VK
  int scene_w = G.fb_w, scene_h = G.fb_h;
  if (blurred) render_blur_size(&scene_w, &scene_h);
  glViewport(0, 0, scene_w, scene_h);
#endif
#ifdef WMMT_NATIVE_VK
  render_scene_clear(G.rp.fog_color[0], G.rp.fog_color[1], G.rp.fog_color[2], 1);
#else
  glClearColor(G.rp.fog_color[0], G.rp.fog_color[1], G.rp.fog_color[2], 1);
  glDepthMask(GL_TRUE);
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
#endif

  /* the arcade's own camera: fixed to the car, with its sway */
  float aspect = (float)G.fb_w / (float)G.fb_h;
  /* the arcade's view across 4:3; a wider screen sees more at the sides */
  float fovy = 2.0f * atanf(tanf(c->cam_fov * 0.5f) / (4.0f / 3.0f));
  mat4 proj = mat4_perspective(fovy, aspect, c->cam_near, 20000.0f);
  render_hq_view(c->cam_near, 20000.0f, tanf(fovy * 0.5f) * aspect, tanf(fovy * 0.5f));
  mat4 view;
  memcpy(view.m, c->cam_view, sizeof view.m);
  mat4 vp = mat4_mul(proj, view);
  mat4 ident = mat4_identity();
  mat4 car_m;
  memcpy(car_m.m, c->body, sizeof car_m.m);

  /* clCourseArrow::setup hides only the groups the junction block table names; the rest
   * (the boards along a route, e.g. TkC1_In) always show */
  if (!G.arrow_table_ready) {
    for (int i = 0; i < G.n_arrows; ++i)
      for (int id = 1; id < CAR_JCT_BLOCKS; ++id) {
        const char *name = car_jct_block_name(id);
        if (name && same_name(G.arrow_names[i], name)) G.arrow_switched[i] = 1;
      }
    G.arrow_table_ready = 1;
  }
  for (int i = 0; i < G.n_arrows; ++i) G.arrow_visible[i] = !G.arrow_switched[i];
  /* plus the junction blocks the arcade shows for where the car is now */
  for (int k = 0; k < 2; ++k) {
    const char *name = car_jct_block_name(c->jct_block[k]);
    for (int i = 0; name && i < G.n_arrows; ++i)
      if (same_name(G.arrow_names[i], name)) G.arrow_visible[i] = 1;
  }
  /* clCourseArrow::update's Hakone: the board pointing up the pass (hk_for) once the car is
   * on its way out (place 0x3a, or 0x3d 100 m in), back down (hk_back) on the way home (0x3c,
   * or 0x3b 100 m in); kept till the next, both hidden at place 0 */
  if (G.track_city == CAR_HAKONE) {
    int pl = c->race.place;
    if (pl == 0) G.hk_arrow = 0;
    else if (pl == 0x3a || (pl == 0x3d && c->race.place_at * 0.001f >= 100.0f)) G.hk_arrow = 1;
    else if (pl == 0x3c || (pl == 0x3b && c->race.place_at * 0.001f >= 100.0f)) G.hk_arrow = 2;
    for (int i = 0; i < G.n_arrows; ++i) {
      if (same_name(G.arrow_names[i], "hk_for")) G.arrow_visible[i] = G.hk_arrow == 1;
      if (same_name(G.arrow_names[i], "hk_back")) G.arrow_visible[i] = G.hk_arrow == 2;
    }
  }
  G.rp.object_visible = G.arrow_visible;
  G.rp.n_objects = G.n_arrows;

  G.rp.draws = G.rp.triangles = G.rp.new_chunks = 0;
  G.rp.time += dt;
  double seg_t = now_ms();
#define SEG_END(k)                    \
  do {                                \
    double seg_now = now_ms();        \
    G.seg[k] = seg_now - seg_t;       \
    seg_t = seg_now;                  \
  } while (0)
  /* the sky box (SkyBoxModel), centred on the camera: no fog, behind everything */
  wpk_scene *sky = &G.sky[G.track_zone];
  if (sky->n_batch) {
    /* clGraphicFrame's far plane for the sky box's view: 600000 (0x49127c00, the views of
     * mask 1 and 8). Hakone's and Osaka's domes reach 555000 out: a nearer far plane cuts the
     * horizon straight ahead out of the sky, and the clear colour shows there, moving with the car */
    mat4 sky_vp = mat4_mul(mat4_perspective(fovy, aspect, 100.0f, 600000.0f), view);
    mat4 sky_m = mat4_identity();
    sky_m.m[12] = c->cam_pos[0];
    sky_m.m[13] = c->cam_pos[1] - SKY_DROP;
    sky_m.m[14] = c->cam_pos[2];
    const float sky_eye[3] = { 0, SKY_DROP, 0 };
    render_params sky_rp = { .night = G.track_zone == 1, .fog_far = 2e9f, .fog_near = 1e9f, .range = { 1e9f, 1e9f, 1e9f } };
    memcpy(sky_rp.grade, G.rp.grade, sizeof sky_rp.grade);
    render_begin(&sky_rp);
    for (int pass = 0; pass < WPK_PASSES; ++pass) {
      render_blend_pass(pass == WPK_BLEND);
      wpk_draw(sky, &sky_vp, &sky_m, sky_eye, pass, &sky_rp);
    }
    render_blend_pass(0);
    
#ifdef WMMT_NATIVE_VK
    render_scene_depth_clear();
#else
    glClear(GL_DEPTH_BUFFER_BIT);
#endif
  }
  SEG_END(SEG_SKY);
  set_car_light(&G.rp, &CAR_LIGHT[G.track_city][G.track_zone], &view);
  render_begin(&G.rp);
  for (int pass = 0; pass < WPK_PASSES; ++pass) {
    render_blend_pass(pass == WPK_BLEND);
    wpk_draw(&G.track, &vp, &ident, c->cam_pos, pass, &G.rp);
    wpk_draw(&G.arrows[G.track_zone], &vp, &ident, c->cam_pos, pass, &G.rp);
    draw_race_cars(c, &vp, c->cam_pos, pass, movie, G.camera == 0 || movie, G.phone ? PHONE_TRAFFIC_FAR : 0.0f, &G.rp);
    if (pass == WPK_CUTOUT) draw_shadows(c, &vp, &car_m);
    SEG_END(SEG_OPAQUE + pass);
  }
#ifdef __ANDROID__
  /* Approximate frame-only junction barrier; RC still owns every route decision.
   * Getter coordinates and Lua's height are already in renderer world units. */
  if (!movie && !G.vs_closed && !G.menu.finish && c->race.state == CAR_RACE_RUN &&
      c->race.jct_select_valid) {
    render_begin(&G.rp);
    junction_barrier_draw(&race_junction_barrier, &vp, c->cam_pos, 1.0f, &G.rp);
    render_blend_pass(0);
  }
#endif
#ifdef __ANDROID__
  if (!movie && !G.vs_closed) {
    player_tracks_draw(&vp, &G.rp);
    /* Original drawLow/drawHigh use view0's track -> RollUp pass. No mirrors. */
    player_smoke_draw(&proj, &view, &G.rp);
  }
#endif
  /* the headlights' pools on the road (clCarSpotLight), then the street lights' and building
   * lights' glows, and the rows of lights at the goal and the next checkpoint */
  {
    const float *spot[1 + CAR_RIVALS];
    int n = 0;
    /* (the roof view too: the player's car is not drawn there, its lamps' pools still are) */
    if (c->spot) spot[n++] = c->body;
    for (int i = 0; i < CAR_RIVALS; ++i)
      if (c->rival_shown[i] && c->rival_spot[i] && (movie ? G.movie_model[i] : G.rival_model[i])) spot[n++] = c->rival_body[i];
    if (!getenv("WMMT_NO_SPOT")) lights_draw_spots(&proj, &view, spot, n, G.track_zone == 1, &G.rp);
  }
  if (!movie) draw_race_front_halos(c, &proj, &view, c->cam_pos, G.camera == 0, 0, &G.rp);
  /* the car's under neon (clCarDisp::update: clNeon::setPosture with the car's frame at its
   * hubs' mean height) */
  if ((G.camera == 0 || movie) && G.menu.neon[G.menu.maker][G.menu.car]) {
    mat4 f = car_m;
    float hub = 0.25f * (c->tyre[0][13] + c->tyre[1][13] + c->tyre[2][13] + c->tyre[3][13]);
    for (int j = 0; j < 3; ++j) f.m[12 + j] += hub * f.m[4 + j];
    lights_draw_neon(&proj, &view, f.m, G.race_pack, G.menu.aero[G.menu.maker][G.menu.car], G.menu.neon[G.menu.maker][G.menu.car], &G.rp);
  }
  /* a versus' other cars' */
  for (int i = 0; !movie && (G.vs_race || app_ghost_arcade_dressed()) && i < CAR_RIVALS; ++i) {
    const vs_dress_t *d = &G.rival_dress[i];
    if (!d->neon || !c->rival_shown[i] || !G.rival_model[i]) continue;
    mat4 f;
    memcpy(f.m, c->rival_body[i], sizeof f.m);
    float hub = 0.25f * (c->rival_tyre[i][0][13] + c->rival_tyre[i][1][13] + c->rival_tyre[i][2][13] + c->rival_tyre[i][3][13]);
    for (int j = 0; j < 3; ++j) f.m[12 + j] += hub * f.m[4 + j];
    lights_draw_neon(&proj, &view, f.m, G.rival_pack[i], d->aero, d->neon, &G.rp);
  }
  lights_draw(&proj, &view, G.track_zone == 1, G.rp.time, &G.rp);
  lights_draw_goal(&proj, &view, &c->race, G.rp.time, &G.rp);
  lights_draw_ten_line(&proj, &view, &c->race, &G.rp);
  backfire_draw(&vp, c->cam_pos, movie, c);
#ifdef __ANDROID__
  race_tail_draw(&proj, &G.rp, movie, G.camera == 0);
#endif
  if (!movie && !getenv("WMMT_NO_SPARK")) spark_draw(&proj, &view, &G.rp);
  render_blend_pass(0);
  SEG_END(SEG_LIGHTS);
  /* the first race frame draws all it can see; after it, whatever the menus left cold that
   * comes into reach, for WARM_MS a frame */
  int warmed = 0;
  if (!G.race_frames) {
    warmed = wpk_prewarm(&G.track, &vp, c->cam_pos, 3000.0f, 1 << 30, &G.rp);
    /* and the traffic's models, before the first car comes into view */
    const float origin[3] = { 0, 0, 0 };
    for (int k = 0; k < CAR_TRAFFIC_MODELS; ++k) warmed += wpk_prewarm(&G.traffic[k], &vp, origin, 1e9f, 1 << 30, &G.rp);
  }
  for (double w0 = now_ms(); G.race_frames && now_ms() - w0 < WARM_MS;) {
    int k = wpk_prewarm(&G.track, &vp, c->cam_pos, WARM_MARGIN, 1, &G.rp);
    if (!k) k = wpk_prewarm(&G.arrows[G.track_zone], &vp, c->cam_pos, WARM_MARGIN, 1, &G.rp);
    if (!k) break;
    warmed += k;
  }
  G.race_frames++;
  SEG_END(SEG_WARM);
  if (blurred) render_blur_end();
  SEG_END(SEG_BLUR);
  if (G.bm_shown) {
    float k = (float)G.fb_h / 480.0f, x0 = 0.5f * ((float)G.fb_w - 640.0f * k);
    mat4 px = mat4_ortho(0, (float)G.fb_w, (float)G.fb_h, 0, -1, 1);
    render_backmirror_draw(&px, x0 + BM_X * k, BM_Y * k, BM_W * k, BM_H * k);
  }
  /* the consoles (and the touch controls with them) only while the race runs: yt::CState 1
   * and 2; then the end's sprites go up */
  hud_rival_view(view.m, proj.m);
  if (G.ten_freeze > 0 || G.story_end_freeze > 0) hud_negate(&G.hud);
  if (movie) {
    hud_demo_draw(&G.hud);
    /* its last 20 frames fade out (clRaceThread::race: getFade), the race fades in from it */
    float left = G.movie_len - G.movie_frame;
    if (G.movie_fade && left < MOVIE_FADE) hud_fade(&G.hud, fade_grey(G.movie_fade), 1.0f - left / MOVIE_FADE);
  } else if (c->race.state == CAR_RACE_RUN) hud_draw(&G.hud, c, &in, G.fps);
  else if (!G.vs_closed) menu_finish_warm(G.n_ten ? 3 : app_ghost_mode() || G.vs_race || (G.rival >= 0 && G.menu.game == MENU_GAME_STORY) ? 2 : c->race.state == CAR_RACE_GOAL);
#ifdef __ANDROID__
  if (!movie && !G.vs_closed && !G.menu.finish && !G.story_end_freeze &&
      c->race.state == CAR_RACE_RUN && c->race.jct_select_valid) {
#ifndef WMMT_NATIVE_VK
    glBlendEquation(GL_FUNC_ADD); /* anm's first ordinary layer needs additive equation */
#endif
    junction_ui_draw(&race_junction_ui);
  }
#endif
  if (!G.vs_closed) menu_finish_draw(&G.menu);
  /* Story dialogue also survives Goal/TimeUp, when the normal HUD is not drawn. */
  if (!movie) hud_story_cutin_draw();
  if (!movie && G.movie_in > 0) hud_fade(&G.hud, fade_grey(G.movie_fade), (float)G.movie_in / MOVIE_FADE);
  if (G.period_in > 0) hud_fade(&G.hud, fade_grey(G.period_fade), (float)G.period_in / MOVIE_FADE);
  hud_white(&G.hud, ten_white_alpha());

  app_vs4_notice();
  SEG_END(SEG_HUD);
#undef SEG_END
  /* now and then, in a frame that is slow anyway (its render, or the frame before it, which
   * a GPU behind leaves at two vsyncs with little CPU), how long the GPU takes over its part
   * (glFinish waits for all of it): is the race short of CPU or of GPU? */
  static int gpu_sampled = -1000;
  if (G.perf && (now_ms() - t1 > 10.0 || dt > 1.5f / 60.0f) && G.race_frames - gpu_sampled >= 300) {
    gpu_sampled = G.race_frames;
    double g0 = now_ms();
#ifdef WMMT_NATIVE_VK
    int completed = cinder_vk_finish();
    if (completed)
      fprintf(G.perf, "%7.2fs native submit/wait host sample: render %.2f ms, wait %.2f ms; draws %d tris %d kmh %.0f blur %.2f"
              " over %d sharp %d\n", G.race_time, g0 - t1, now_ms() - g0, G.rp.draws, G.rp.triangles, car_kmh(c),
              c->cam_blur, G.over_draws, G.menu.sharp_on && !G.sharp_rest);
    else fprintf(G.perf, "%7.2fs native submit/wait sample unavailable (completion unconfirmed)\n", G.race_time);
#else
    glFinish();
    fprintf(G.perf, "%7.2fs gpu sample: render %.2f ms, then the GPU %.2f ms more; draws %d tris %d kmh %.0f blur %.2f"
            " over %d sharp %d\n", G.race_time, g0 - t1, now_ms() - g0, G.rp.draws, G.rp.triangles, car_kmh(c),
            c->cam_blur, G.over_draws, G.menu.sharp_on && !G.sharp_rest);
#endif
  }
  if (G.paused && !G.vs_closed) {
    menu_pause_draw(&G.menu);
    return;
  }
  perf_frame(dt, steps, physics_ms, now_ms() - t1, warmed, &G.rp);
  static int frame;
  if (frame < 10 || frame % 150 == 0)
#ifdef WMMT_NATIVE_VK
    fprintf(stderr, "frame %d dt %.3f draws %d tris %d car %.1f %.1f %.1f cam %.1f %.1f %.1f traffic %d kmh %.0f blur %.3f native epoch %llu pending %d\n",
            frame, dt, G.rp.draws, G.rp.triangles, c->pos[0], c->pos[1], c->pos[2], c->cam_pos[0], c->cam_pos[1],
            c->cam_pos[2], c->n_traffic, car_kmh(c), c->cam_blur, (unsigned long long)cinder_vk_error_epoch(), cinder_vk_error_pending());
#else
    fprintf(stderr, "frame %d dt %.3f draws %d tris %d car %.1f %.1f %.1f cam %.1f %.1f %.1f traffic %d kmh %.0f blur %.3f err 0x%x\n",
            frame, dt, G.rp.draws, G.rp.triangles, c->pos[0], c->pos[1], c->pos[2], c->cam_pos[0], c->cam_pos[1],
            c->cam_pos[2], c->n_traffic, car_kmh(c), c->cam_blur, glGetError());
#endif
  frame++;
}


void app_timing_reset(void) {
  timing60_sim_reset(&app_clock);
  app_history_valid = 0;
  memset(&app_display_input, 0, sizeof app_display_input);
}

/* Keep original RC/net/sound inputs and physics ownership in app_frame. At most
 * six fixed ticks follow a stall (100 ms admitted time); longer blocked/loading
 * intervals are deliberately discarded, never a spiral of replayed packets. */
void app_present(float dt) {
  double frame_start = now_ms();
  G.frame_start = frame_start;
#ifdef WMMT_NATIVE_VK
  render_display_begin(G.fb_w, G.fb_h);
#endif
  if (!isfinite(dt) || dt < 0) dt = 0;
  app_display_dt = dt > 0.1f ? 0.1f : dt;
  if (dt > 0) G.fps += (1.0f / dt - G.fps) * 0.05f;
  if (dt > 0.1f) app_history_valid = 0;
  int ticks = timing60_sim_steps(&app_clock, dt);
  if (G.vs_race && !G.in_menu) {
    /* app_frame polls at each simulation boundary. High-refresh frames
     * without a tick still observe transport stalls and terminal events. */
    if (!ticks && app_vs4_native_gate() <= 0) app_history_valid = 0;
  } else if (net_is_open()) {
    app_vs4_poll_transport();
  }
  double physics_ms = 0;
  app_tick_only = 1;
  for (int i = 0; i < ticks; ++i) {
    int menu = G.in_menu, camera = G.camera, movie = G.movie_len > 0;
    int reset = G.hud.reset_pressed;
    int warm = !menu && G.race_frames < 2;
    app_previous = G.car;
    double t0 = now_ms();
    app_frame(1.0f / 60.0f);
    physics_ms += now_ms() - t0;
    app_history_valid = !menu && !G.in_menu && camera == G.camera && movie == (G.movie_len > 0) &&
      !G.paused && !G.vs_wait && !G.vs_closed && !G.ten_freeze && !G.story_end_freeze && !G.story_old_ended &&
      !warm && !reset && app_previous.race.state == G.car.race.state;
    if (menu != G.in_menu || movie != (G.movie_len > 0)) {
      /* Slow Init/End/movie setup belongs to neither the new race nor menu time. */
      timing60_sim_reset(&app_clock);
      app_history_valid = 0;
      break;
    }
  }
  app_tick_only = 0;
  G.frame_start = frame_start;
  if (G.in_menu) { menu_present(frame_start); return; }
  presentation60_car(&app_display_car, &app_previous, &G.car,
                      (float)app_clock.fraction, app_history_valid);
  app_draw_frame(app_display_dt, &app_display_input, ticks, physics_ms, &app_display_car);
  /* GPU warming is not elapsed driving time, regardless of display rate. */
  if (G.race_frames <= 2) timing60_sim_reset(&app_clock);
}
