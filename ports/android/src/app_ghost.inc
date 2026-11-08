/* Independent fifth-mode orchestration. Included by app.c after its menu/load
 * helpers. Local crown storage is independent of transport and world rankings. */
#include "ghost_store.h"
#include "ghost_format.h"
#include "ghost_catalog.h"
#include <limits.h>

static struct {
  int entered, prepared, active;
  int ramp, route, course, maker, car, color, manual;
  int rival_pack, rival_paint;
  short rival_name[5]; /* glyphs snapshotted from the bound original identity */
  unsigned request;
  uint64_t serial, token, crown_revision;
  int crown_challenge, player_recording;
  car_spec owner;
  car_ghost_config config;
  int checked, checked_ramp, checked_route, local_available;
  int root_valid;
  char physical_root[4096]; /* resolved from trusted app configuration, never uploaded metadata */
  int arcade, arcade_area, arcade_card_slot;
  long long arcade_card_born;
  uint32_t arcade_record;
  uint64_t arcade_epoch;
  car_ghost_arcade_binding arcade_binding;
  car_ghost_default_binding default_binding;
  ghost_catalog_area arcade_style; /* immutable source cosmetics, not player's style */
} AG;

static int app_ghost_mode(void) { return G.menu.game == MENU_GAME_GHOST; }
static int app_ghost_rival_pack(int *paint) {
  if (paint) *paint = AG.rival_paint;
  return app_ghost_mode() && (AG.prepared || AG.active) ? AG.rival_pack : -1;
}
static void app_arcade_paint_drop(int context_lost);
static void app_ghost_clear(void) {
  app_arcade_paint_drop(0);
  uint64_t serial = AG.serial;
  int entered = AG.entered, root_valid = AG.root_valid;
  char root[sizeof AG.physical_root];
  memcpy(root, AG.physical_root, sizeof root);
  car_ghost_clear();
  memset(&AG, 0, sizeof AG);
  AG.serial = serial; AG.entered = entered; AG.rival_pack = -1;
  AG.root_valid = root_valid; memcpy(AG.physical_root, root, sizeof root);
}
static void app_ghost_note(const char *note) {
  snprintf(G.menu.ghost.note, sizeof G.menu.ghost.note, "%s", note);
}
static void app_ghost_fail(const char *note) {
  app_ghost_clear();
  G.menu.finish = G.menu.finish_ghost = 0;
  menu_ghost_race_finished(&G.menu, MENU_GHOST_RESULT_INVALID, 0);
  app_ghost_note(note);
  G.menu.ready = 0;
  G.in_menu = 1; G.paused = 0;
  G.n_rival = G.n_ten = G.vs_race = G.vs_closed = 0;
  G.rival = G.menu.story_sel = -1;
}
/* A model must really exist for the record owner's exact native type. Never
 * borrow the current player's model when the profile is unknown. */
static int app_ghost_model(const car_spec *owner, int *paint) {
  if (!owner) return -1;
  for (int mk = 0; mk < CARDB_ALL; ++mk)
    for (int c = 0; c < CARDB_NCARS[mk]; ++c)
      for (int co = 0; co < CARDB_CARS[mk][c].ncolors; ++co) {
        const cardb_color *color = &CARDB_CARS[mk][c].colors[co];
        if (color->type != (int)owner->type || color->gears != owner->gears ||
            color->pack < 0 || color->pack >= NPACKS ||
            (int)CARDB_TYRES[color->pack][6] != owner->spokes) continue;
        int match = 1;
        for (int i = 0; i < 6; ++i)
          if (!isfinite(owner->tyres[i]) || owner->tyres[i] != CARDB_TYRES[color->pack][i]) match = 0;
        if (match) { if (paint) *paint = color->paint; return color->pack; }
      }
  return -1;
}
static int app_ghost_field(int ramp, int route, uint32_t field[6]) {
  return ramp >= 1 && ramp <= 22 && route == 0 &&
         car_ghost_race_field(ramp, route, 0, field) && car_ghost_render_course(field) >= 0;
}
static int app_ghost_read(ghost_store_record *record, int ramp, int route, const uint32_t field[6]) {
  const char *physics = car_ghost_physics_id();
  if (!AG.root_valid || !physics || strlen(physics) != 64 ||
      ghost_store_load(AG.physical_root, physics, record) != GHOST_STORE_OK) return 0;
  if (!ghost_store_contains_map(record, (uint32_t)ramp, (uint32_t)route) ||
      memcmp(record->race_field, field, sizeof record->race_field) ||
      app_ghost_model(&record->owner, NULL) < 0) {
    ghost_store_free(record); return 0;
  }
  return 1;
}
static void app_ghost_config_local(car_ghost_config *cfg, const ghost_store_record *record,
                                   const uint32_t field[6], uint64_t token) {
  memset(cfg, 0, sizeof *cfg);
  cfg->abi_version = CAR_GHOST_ABI_VERSION; cfg->session_token = token;
  cfg->kind = record ? CAR_GHOST_CHALLENGE : CAR_GHOST_QUALIFICATION;
  cfg->record_player = 1;
  memcpy(cfg->race_field, field, sizeof cfg->race_field);
  /* Local practice is not a world crown. Both qualification and challenge use
   * the same reviewed non-tutorial field; no 2.8 km/12 km metadata mismatch. */
  if (record) {
    cfg->rival = record->owner; cfg->trail = record->trail; cfg->trail_bytes = record->trail_bytes;
    cfg->trail_band[0] = record->owner.power; cfg->trail_band[1] = record->owner.handling;
    uint64_t now = (uint64_t)time(NULL);
    uint64_t age = now >= record->recorded_at ? (now - record->recorded_at) / 3600u : UINT64_MAX;
    cfg->trail_band[2] = age <= 876000u ? (int)age : -1;
  }
}
static menu_ghost_record_date app_ghost_record_date(unsigned year,unsigned month,unsigned day,
                                                    unsigned hour,unsigned minute) {
  static const uint8_t days[]={31,28,31,30,31,30,31,31,30,31,30,31};
  if (!year || year>9999 || !month || month>12 || hour>23 || minute>59)
    return (menu_ghost_record_date){0};
  unsigned limit=days[month-1]+(month==2 && year%4==0 && (year%100!=0 || year%400==0));
  if (!day || day>limit) return (menu_ghost_record_date){0};
  return (menu_ghost_record_date){.year=year,.month=month,.day=day,.hour=hour,.minute=minute};
}

#include "app_ghost_arcade.inc"

static void app_ghost_availability(void) {
  menu_state *m = &G.menu;
  if (m->screen != MENU_GHOST || AG.prepared || AG.active || m->ghost.active_request) return;
  if (!AG.checked || AG.checked_ramp != m->ghost.ramp || AG.checked_route != m->ghost.route) {
    AG.local_available = 0;
    uint32_t field[6]; ghost_store_record record = {0};
    if (car_ghost_physics_id() && app_ghost_field(m->ghost.ramp, m->ghost.route, field) &&
        app_ghost_read(&record, m->ghost.ramp, m->ghost.route, field)) {
      car_ghost_config cfg;
      app_ghost_config_local(&cfg, &record, field, UINT64_MAX);
      AG.local_available = car_ghost_prepare(&cfg); /* strict trail/native compatibility, not CRC alone */
      car_ghost_clear();
    }
    ghost_store_free(&record);
    AG.checked = 1; AG.checked_ramp = m->ghost.ramp; AG.checked_route = m->ghost.route;
  }
  menu_ghost_set_availability(m, AG.local_available, android_ghost_cloud_configured(), 0);
}
static void app_ghost_resolve_root(void) {
  AG.root_valid=0;AG.physical_root[0]=0;
  char *physical=realpath(G.save_dir,NULL);
  if(physical && strlen(physical)<sizeof AG.physical_root) {
    memcpy(AG.physical_root,physical,strlen(physical)+1);
    AG.root_valid=1;
  }
  free(physical);
}

#include "app_ghost_card.inc"

/* Called only on the game thread, before vs_menu. Entering Ghost stops a former
 * VS session once and schedules the optional cloud catalogue worker. */
static void app_ghost_menu(void) {
  menu_state *m = &G.menu;
  if (!app_ghost_mode()) {
    if (AG.entered || AG.prepared || AG.active) { app_ghost_clear(); AG.entered = 0; }
    if (AC.catalog || AC.attempted || GC.wait) app_arcade_unbind();
    return;
  }
  if (!AG.entered) {
    app_ghost_clear(); AG.entered = 1;
    app_ghost_resolve_root();
    if (!AG.root_valid) app_ghost_note("LOCAL SAVE DIRECTORY UNAVAILABLE");
    vs_off();
    memset(&m->vs, 0, sizeof m->vs);
    G.vs_race = G.vs_closed = G.vs_wait = G.vs_seen_loaded = 0;
    G.story_race = G.story_cut_pending = G.story_old_ended = 0;
    story_carry_cancel();
    G.rival = m->story_sel = -1;
  }
  if (AG.prepared && !menu_ghost_preparing(m) && !menu_ghost_choosing_options(m)) app_ghost_clear(); /* Back/cancel/stale request */
  app_cloud_menu();
  app_arcade_directory();
  if(GC.search_ready && (AC.published || (AC.attempted && !AC.catalog))) {
    menu_ghost_search_complete(m,GC.search_ready>0);
    GC.search_ready=0;
  }
  app_ghost_availability();
  unsigned request = 0;
  int action = menu_ghost_take_action(m, &request);
  if (!action) return;
  if (action == MENU_GHOST_FETCH_KING || action == MENU_GHOST_CHALLENGE_KING || action == MENU_GHOST_SUBMIT_CLAIM) {
    (void)menu_ghost_complete(m, request, 0, "VERIFIED WORLD CROWN UNAVAILABLE");
    return;
  }
  if (action == MENU_GHOST_CHALLENGE_ARCADE) {
    if (app_arcade_requested(request)) app_replay_arm();
    return;
  }
  if (action == MENU_GHOST_CHALLENGE_DEFAULT) {
    if (app_default_requested(request)) {
      if (m->ghost.search_kind==0 && m->ghost.level==9) app_crown_arm();
      app_replay_arm();
    }
    return;
  }
  if (action == MENU_GHOST_CHALLENGE_LOCAL_CROWN) {
    if (app_crown_requested(request)) app_replay_arm();
    return;
  }
  if (action == MENU_GHOST_CHALLENGE_CLOUD) {
    int remote=m->ghost.request_record_index<MENU_GHOST_CLOUD_RECORDS;
    if (remote?app_cloud_requested(request):app_replay_requested(request)) app_replay_arm();
    return;
  }
  uint32_t field[6];
  if (!AG.root_valid) {
    (void)menu_ghost_complete(m, request, 0, "LOCAL SAVE DIRECTORY UNAVAILABLE"); return;
  }
  if (m->ghost.request_route != 0) {
    (void)menu_ghost_complete(m, request, 0, "SUPPORTED ROUTE 0 ONLY"); return;
  }
  if (!car_ghost_physics_id() || !app_ghost_field(m->ghost.request_ramp, m->ghost.request_route, field)) {
    (void)menu_ghost_complete(m, request, 0, "GHOST ENGINE OR MAP UNAVAILABLE"); return;
  }
  ghost_store_record record = {0};
  if (action != MENU_GHOST_RECORD_LOCAL && action != MENU_GHOST_CHALLENGE_LOCAL) {
    (void)menu_ghost_complete(m, request, 0, "UNSUPPORTED GHOST ACTION"); return;
  }
  if (action == MENU_GHOST_CHALLENGE_LOCAL && !app_ghost_read(&record, m->ghost.request_ramp, m->ghost.request_route, field)) {
    AG.checked = 0;
    (void)menu_ghost_complete(m, request, 0, "NO VALID LOCAL RECORD FOR THIS MAP"); return;
  }
  car_ghost_config cfg;
  if (++AG.serial == 0 || AG.serial == UINT64_MAX) AG.serial = 1;
  app_ghost_config_local(&cfg, action == MENU_GHOST_CHALLENGE_LOCAL ? &record : NULL, field, AG.serial);
  int pack = action == MENU_GHOST_CHALLENGE_LOCAL ? app_ghost_model(&record.owner, &AG.rival_paint) : -1;
  int ok = car_ghost_prepare(&cfg);
  ghost_store_free(&record); cfg.trail = NULL; cfg.trail_bytes = 0; /* native prepare owns its immutable copy */
  if (!ok) {
    car_ghost_clear(); AG.checked = 0;
    (void)menu_ghost_complete(m, request, 0, "GHOST RECORD VALIDATION FAILED"); return;
  }
  if (!menu_ghost_complete(m, request, 1, "GHOST PREPARED") || !menu_ghost_begin_pre(m)) {
    app_ghost_clear(); return;
  }
  AG.config = cfg; AG.token = cfg.session_token; AG.request = request;
  AG.ramp = m->ghost.request_ramp; AG.route = m->ghost.request_route;
  AG.course = car_ghost_render_course(field); AG.prepared = 1;
  AG.maker = m->maker; AG.car = m->car; AG.color = m->color; AG.manual = m->manual;
  AG.rival_pack = pack;
  m->course = AG.course; m->story_sel = -1; m->finish = m->finish_story = 0;
}
static int app_ghost_go_valid(void) {
  car_ghost_observation o;
  return app_ghost_mode() && AG.prepared && !AG.active && menu_ghost_preparing(&G.menu) &&
         AG.request == G.menu.ghost.prepared_request && AG.token &&
         AG.ramp == G.menu.ghost.request_ramp && AG.route == G.menu.ghost.request_route &&
         G.menu.maker == AG.maker && G.menu.car == AG.car && G.menu.color == AG.color &&
         G.menu.manual == AG.manual && G.menu.course == AG.course &&
         car_ghost_status(&o) && o.status == CAR_GHOST_PREPARED && o.session_token == AG.token &&
         o.kind == AG.config.kind && (!AG.arcade || (app_arcade_frozen() && app_arcade_appearance_ready()));
}
static int app_ghost_started(const car_spec *owner) {
  car_ghost_observation o;
  if (!AG.prepared || !owner || !car_ghost_status(&o) || o.session_token != AG.token ||
      o.status != CAR_GHOST_RUNNING || o.kind != AG.config.kind ||
      (o.recording!=AG.config.record_player &&
       !(AG.player_recording && !AG.crown_challenge && !o.recording)) ||
      (AG.arcade && !app_arcade_frozen()) ||
      (o.kind == CAR_GHOST_CHALLENGE && !o.native_target_valid) ||
       (o.kind == CAR_GHOST_DEFAULT && (!o.native_default_ai_valid || o.native_target_valid))) return 0;
  if(!o.recording)AG.player_recording=AG.config.record_player=0;
  AG.owner = *owner; AG.active = 1; AG.prepared = 0;
  return 1;
}
/* Return 1 once a Ghost race was closed (including an invalid native result).
 * This is intentionally before the ordinary TA/VS/story result branches. */
static int app_ghost_finish(void) {
  if (!app_ghost_mode() || G.menu.finish) return 0;
  if(ACP.draw_fault){app_ghost_fail("EXACT GHOST APPEARANCE LOST - RACE INVALIDATED");return 1;}
  car_ghost_observation o = {0};
  int observed = car_ghost_status(&o);
  if (AG.active && observed && o.session_token == AG.token &&
      o.status != CAR_GHOST_FAILED && !G.car.race.over) return 0;
  int terminal = AG.active && observed && o.session_token == AG.token && o.kind == AG.config.kind &&
              o.status == CAR_GHOST_FINISHED && o.result_valid &&
              (G.car.race.play_state == 3 || G.car.race.play_state == 6 || G.car.race.play_state == 8) &&
              (o.kind != CAR_GHOST_CHALLENGE || o.native_target_valid) &&
               (o.kind != CAR_GHOST_DEFAULT || (o.native_default_ai_valid && !o.native_target_valid)) &&
               (!AG.arcade || app_arcade_frozen());
  /* Native retirement/time-up is a real loss, not malformed engine data.
   * Only a completed goal may publish a full-distance recording. */
  int valid = terminal && o.goal_reached && G.car.race.play_state == 8;
  /* Let the native pilot and sampler record the winner's short runout on
   * ordinary simulation ticks before publishing a new crown. */
  uint32_t record_ticks=6u;
  if(AG.crown_challenge && o.won)record_ticks=CAR_GHOST_CROWN_RUNOUT_TICKS;
  else if(AG.config.race_field[0]==GHOST_LONG_TA_STAGE)record_ticks=9u;
  if (valid && (!AG.arcade || AG.player_recording || (AG.crown_challenge && AG.config.record_player && o.won)) &&
      !o.export_ready && o.native_ticks-o.finish_tick<record_ticks) return 0;
  int result = !terminal ? MENU_GHOST_RESULT_INVALID : o.kind == CAR_GHOST_QUALIFICATION ?
               (valid ? MENU_GHOST_RESULT_FINISHED : MENU_GHOST_RESULT_INVALID) :
               (valid && o.won && o.place == 0 ? MENU_GHOST_RESULT_WIN : MENU_GHOST_RESULT_LOSE);
  const char *storage_note = NULL;
  if (AG.arcade && terminal) {
    int player_rank = -1, level = -1;
    uint64_t wins = app_arcade_history_totals(NULL);
    if (wins <= INT_MAX)
      (void)car_ghost_arcade_difficulty(AG.owner.power, AG.owner.handling, (uint32_t)wins, &level, &player_rank);
    if (AG.arcade==1 || AG.arcade==2)
      storage_note=app_arcade_history_record(AG.arcade_record+(AG.arcade==2?GHOST_CATALOG_RECORDS:0u),
                                             (unsigned)AG.arcade_area,result==MENU_GHOST_RESULT_WIN);
    else if (G.car.race.play_state!=3 && !G.menu.save_skip)
      storage_note=app_arcade_history_player(result==MENU_GHOST_RESULT_WIN);
    if(valid)app_cloud_report(result==MENU_GHOST_RESULT_WIN,o.gap_m);
    int crown=AG.crown_challenge && result==MENU_GHOST_RESULT_WIN;
    if (valid && (crown || AG.player_recording)) {
      ghost_crown_record record={0};
      int captured=app_ghost_capture_profile(o.export_ready,&record);
      int saved=captured && app_replay_save(&record,(unsigned)AG.arcade_area);
      int queued=captured && app_cloud_publish(&record,(unsigned)AG.arcade_area);
      char error[sizeof AC.crown_note];
      const char *note=crown?app_crown_publish(captured?&record:NULL,error,sizeof error):NULL;
      const char *cloud=queued?"CLOUD REPLAY QUEUED":saved?"PLAYER REPLAY SAVED":"";
      snprintf(AC.crown_note,sizeof AC.crown_note,"%s%s%s",note?note:"",note && *cloud?" / ":"",cloud);
      ghost_crown_free(&record);
      AC.published=0;
    }
    if (G.car.race.play_state != 3) { /* Target result2 skips the console for manual retirement. */
      menu_finish_ghost(&G.menu, result, valid, o.gap_m, player_rank, AG.arcade_binding.target_rank);
      if (storage_note) app_ghost_note(storage_note);
      return 0; /* the race still owns the display until menu_finish_update leaves */
    }
  }
  if (valid && !AG.arcade) {
    ghost_store_record record = {0};
    const char *physics = car_ghost_physics_id();
    size_t bytes = 0;
    int saved = 0;
    if (AG.root_valid && o.export_ready && physics && strlen(physics) == 64 && car_ghost_export(NULL, 0, &bytes) && bytes && bytes <= GHOST_MAX_BYTES) {
      record.trail = malloc(bytes);
      if (record.trail && car_ghost_export(record.trail, bytes, &record.trail_bytes) && record.trail_bytes == bytes) {
        record.ramp = (uint32_t)AG.ramp; record.route = (uint32_t)AG.route;
        memcpy(record.race_field, AG.config.race_field, sizeof record.race_field);
        record.owner = AG.owner; memcpy(record.physics_sha256, physics, 65);
        record.recorded_at = (uint64_t)time(NULL);
        int rc = ghost_store_save(AG.physical_root, &record);
        saved = rc == GHOST_STORE_OK || rc == GHOST_STORE_COMMITTED_UNSYNCED;
        storage_note = rc == GHOST_STORE_COMMITTED_UNSYNCED ? "LOCAL RECORD PUBLISHED - DURABILITY UNCONFIRMED" :
                       saved ? "LOCAL RECORD SAVED - PRACTICE ONLY" : "RECORD SAVE FAILED - PREVIOUS RECORD KEPT";
      }
    }
    if (!storage_note) storage_note = "RECORD EXPORT FAILED - PREVIOUS RECORD KEPT";
    ghost_store_free(&record);
    /* Finishing a qualification without a usable recording is not success. */
    if (o.kind == CAR_GHOST_QUALIFICATION && !saved) result = MENU_GHOST_RESULT_INVALID;
  }
  app_ghost_clear();
  menu_ghost_race_finished(&G.menu, result, 0); /* local win is never a cloud claim */
  if (storage_note) app_ghost_note(storage_note);
  G.menu.ready = 0; G.in_menu = 1; G.paused = 0;
  G.n_rival = G.n_ten = G.vs_race = G.vs_closed = 0;
  G.rival = G.menu.story_sel = -1;
  memset(G.rival_model, 0, sizeof G.rival_model);
  return 1;
}
