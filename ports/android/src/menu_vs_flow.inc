/* Menu-only ordered VS round. Included after pre_tune_enter in menu.c.
 * App owns room membership, validated current-round generation, votes/commits,
 * protocol pumping and the all-player barrier. These helpers perform no I/O,
 * transport calls, random draws, persistence or permanent tune mutation.
 * Original mseqJoin: area -> ramp -> day -> wait105 -> (>20 points) setting
 * -> sendJoinCard -> wait106 -> course decide -> race. */
static void vs_flow_clear(menu_state *m) {
  m->vs.round = 0;
  m->vs.flow_stage = MENU_VS_FLOW_ROOM;
  m->vs.round_cancel = 0;
  m->vs.tune_base_power = m->vs.tune_base_handling = 0;
  m->vs.tune_maker = m->vs.tune_car = m->vs.tune_slot = -1;
  m->vs.tune_skip = 0;
  m->vs.tune_timer = 0;
  m->vs.omakase_sample_valid = 0;
#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
  pre_race_tune_clear(&m->pre_tune);
  m->pre_tune_setting = 0;
  m->pre_tune_car_touch = NULL;
  m->pre_tune_car_inside = 0;
#endif
}

int menu_vs_round_active(const menu_state *m) {
  return m && m->game == MENU_GAME_VS && m->vs.round != 0 &&
         m->vs.flow_stage != MENU_VS_FLOW_ROOM;
}

static int vs_flow_identity(const menu_state *m, uint64_t round) {
  return menu_vs_round_active(m) && round && round == m->vs.round &&
         m->vs.state == MENU_VS_LOBBY && m->vs.n >= 2 && m->vs.n <= MENU_VS_PLAYERS &&
         m->vs.me >= 0 && m->vs.me < m->vs.n &&
         m->vs.host >= 0 && m->vs.host < m->vs.n && !m->vs.round_cancel;
}

int menu_vs_round_begin(menu_state *m, uint64_t round) {
  if (!m || !round || m->game != MENU_GAME_VS || m->screen != MENU_VS ||
      m->vs.state != MENU_VS_LOBBY || m->vs.n < 2 || m->vs.n > MENU_VS_PLAYERS ||
      m->vs.me < 0 || m->vs.me >= m->vs.n || m->vs.host < 0 || m->vs.host >= m->vs.n ||
      menu_vs_round_active(m)) return 0;
  vs_flow_clear(m);
  m->vs.round = round;
  m->vs.flow_stage = MENU_VS_FLOW_AREA;
  m->vs.area_final = m->vs.day_final = -1;
  m->vs.day = m->vs.day_voted = m->vs.voted = 0;
  m->vs.loaded = m->vs.wait_others = 0;
  m->vs.match_t = m->vs.match_n = m->vs.match_me = m->vs.match_played = 0;
  m->vs.start = 0;
  m->vs.area_go = 1; /* consumed by production step(), not a network START */
  m->tap = m->key = m->back = m->key_held = 0;
  return 1;
}

/* Values are original raw areas0..7, NOT the visual strip's card1..8.
 * Omakase emits a concrete random area and only adds a presentation marker.
 * A choosing value is NOT yet a confirmed vote. The new coordinator owns tally. */
int menu_vs_omakase_samples(menu_state *m, uint64_t round, uint32_t first, uint32_t second, uint32_t third) {
  if (!vs_flow_identity(m, round) || m->vs.flow_stage != MENU_VS_FLOW_AREA || m->vs.voted) return 0;
  m->vs.omakase_sample[0] = first;
  m->vs.omakase_sample[1] = second;
  m->vs.omakase_sample[2] = third;
  m->vs.omakase_sample_valid = 1;
  return 1;
}

int menu_vs_map_vote(const menu_state *m, uint64_t round, int *area, int *confirmed, int *omakase) {
  if (!vs_flow_identity(m, round) || m->vs.flow_stage != MENU_VS_FLOW_AREA ||
      m->screen != MENU_VS_AREA || m->vs.area_final >= 0) return 0;
  int card = m->vs.voted ? m->vs.vote : m->vs.item;
  if (area) *area = menu_vs_card_area(card);
  if (confirmed) *confirmed = m->vs.voted != 0;
  if (omakase) *omakase = m->vs.voted == 2;
  return 1;
}

int menu_vs_map_commit(menu_state *m, uint64_t round, int area) {
  if (!vs_flow_identity(m, round) || m->vs.flow_stage != MENU_VS_FLOW_AREA ||
      m->screen != MENU_VS_AREA || area < 0 || area > 7) return 0;
  int card;
  for (card = 1; card < MENU_VS_CARDS && menu_vs_card_area(card) != area; ++card) {}
  if (card == MENU_VS_CARDS || (m->vs.area_final >= 0 && m->vs.area_final != card)) return 0;
  m->vs.area_final = card;
  return 1;
}

int menu_vs_time_open(menu_state *m, uint64_t round) {
  if (!vs_flow_identity(m, round) || m->vs.flow_stage != MENU_VS_FLOW_AREA ||
      m->vs.area_final <= 0 || m->vs.area_final >= MENU_VS_CARDS || m->screen != MENU_VS_AREA) return 0;
  menu_vs_day_open(m);
  return m->screen == MENU_BGM && m->vs.flow_stage == MENU_VS_FLOW_DAY && m->vs.day;
}

int menu_vs_time_vote(const menu_state *m, uint64_t round, int *zone, int *confirmed) {
  if (!vs_flow_identity(m, round) || m->vs.flow_stage != MENU_VS_FLOW_DAY ||
      m->screen != MENU_BGM || !m->vs.day || m->vs.day_final >= 0) return 0;
  if (zone) *zone = m->zone;
  if (confirmed) *confirmed = m->vs.day_voted != 0;
  return 1;
}

int menu_vs_time_commit(menu_state *m, uint64_t round, int zone) {
  if (!vs_flow_identity(m, round) || m->vs.flow_stage != MENU_VS_FLOW_DAY ||
      m->screen != MENU_BGM || !m->vs.day || zone < 0 || zone > 1 || zone >= m->zones ||
      (m->vs.day_final >= 0 && m->vs.day_final != zone)) return 0;
  m->vs.day_final = zone;
  return 1;
}

/* Freeze a verified day commit only after the original day vote has opened.
 * Low cards still participate in READY with their unchanged earned tune. Failure
 * for an eligible/invalid card is NOT silently treated as readiness. */
int menu_vs_tune_open(menu_state *m, uint64_t round) {
  if (!vs_flow_identity(m, round) || m->vs.flow_stage != MENU_VS_FLOW_DAY ||
      m->screen != MENU_BGM || !m->vs.day || m->vs.area_final <= 0 ||
      m->vs.area_final >= MENU_VS_CARDS || m->vs.day_final < 0 || m->vs.day_final > 1 ||
      m->vs.day_final >= m->zones || m->maker < 0 || m->maker >= CARDB_ALL ||
      m->car < 0 || m->car >= CARDB_NCARS[m->maker]) return 0;
  int p, h;
  menu_tune(m, &p, &h);
  if (story_tune_budget(p, h) < 0) return 0;
  m->vs.tune_base_power = p;
  m->vs.tune_base_handling = h;
  m->vs.tune_maker = m->maker;
  m->vs.tune_car = m->car;
  m->vs.tune_slot = m->save_slot;
  m->vs.tune_skip = m->save_skip;
  m->zone = m->vs.day_final;
#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
  if (p + h > 20) {
    if (!pre_tune_enter(m, MENU_VS, m->sel, 0)) return 0;
    m->vs.flow_stage = MENU_VS_FLOW_TUNE;
    m->vs.day = 0;
    return 1;
  }
#endif
  /* Original mseqJoin skips setting at <=20 earned points; explicit per-player
   * READY still travels through the new room protocol before any race GO. */
  m->vs.day = 0;
  m->vs.flow_stage = MENU_VS_FLOW_READY;
  go(m, MENU_VS);
  return 1;
}

static int vs_tune_identity(const menu_state *m, uint64_t round) {
  if (!vs_flow_identity(m, round) ||
      m->maker != m->vs.tune_maker || m->car != m->vs.tune_car ||
      m->save_slot != m->vs.tune_slot || m->save_skip != m->vs.tune_skip ||
      m->maker < 0 || m->maker >= CARDB_ALL ||
      m->car < 0 || m->car >= CARDB_NCARS[m->maker]) return 0;
  int p, h;
  menu_tune(m, &p, &h);
  return p == m->vs.tune_base_power && h == m->vs.tune_base_handling;
}

int menu_vs_tune_draft(const menu_state *m, uint64_t round, int *power, int *handling) {
#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
  if (!vs_tune_identity(m, round) || m->vs.flow_stage != MENU_VS_FLOW_TUNE ||
      m->screen != MENU_SETTING || !m->pre_tune_setting || !m->pre_tune.state ||
      !pre_race_tune_slot_matches(&m->pre_tune, m->save_slot, m->save_skip)) return 0;
  int p = m->pre_tune.power, total = m->vs.tune_base_power + m->vs.tune_base_handling;
  if (!story_tune_allocation_valid(total, p, total - p)) return 0;
  *power = p;
  *handling = total - p;
  return 1;
#else
  (void)m; (void)round; (void)power; (void)handling;
  return 0;
#endif
}

/* A local confirmation or the authority's deadline uses the same transient
 * editor. The finalized network allocation may be the last draft received. */
int menu_vs_tune_accept(menu_state *m, uint64_t round, int power, int handling) {
  if (!vs_tune_identity(m, round) ||
      !story_tune_allocation_valid(m->vs.tune_base_power + m->vs.tune_base_handling, power, handling)) return 0;
  int editing = m->vs.flow_stage == MENU_VS_FLOW_TUNE && m->screen == MENU_SETTING;
  if (!editing && (m->vs.flow_stage != MENU_VS_FLOW_READY || m->screen != MENU_VS)) return 0;
#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
  if (m->vs.tune_base_power + m->vs.tune_base_handling > 20) {
    if ((editing && !m->pre_tune_setting) || !m->pre_tune.state ||
        !pre_race_tune_slot_matches(&m->pre_tune, m->save_slot, m->save_skip)) return 0;
    m->pre_tune.power = power;
    if (m->pre_tune.state == 1 && !pre_race_tune_confirm(&m->pre_tune)) return 0;
  } else
#endif
  if (power != m->vs.tune_base_power || handling != m->vs.tune_base_handling) return 0;
  if (editing) {
#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
    m->pre_tune_setting = 0;
#endif
    m->vs.flow_stage = MENU_VS_FLOW_READY;
    go(m, MENU_VS);
    m->bars = 1;
    m->vs.held = 0;
    m->tap = m->key = m->key_held = 0;
  }
  return 1;
}

int menu_vs_tune_ready(const menu_state *m, uint64_t round, int *power, int *handling) {
  if (!vs_tune_identity(m, round) || m->vs.flow_stage != MENU_VS_FLOW_READY ||
      m->screen != MENU_VS) return 0;
  int p = m->vs.tune_base_power, h = m->vs.tune_base_handling;
#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
  if (p + h > 20 && (!pre_race_tune_slot_matches(&m->pre_tune, m->save_slot, m->save_skip) ||
      !pre_race_tune_vs_apply(&m->pre_tune, m->maker, m->car, &p, &h))) return 0;
#endif
  if (power) *power = p;
  if (handling) *handling = h;
  return 1;
}

static int vs_flow_request_cancel(menu_state *m) {
  if (!menu_vs_round_active(m) || m->vs.flow_stage >= MENU_VS_FLOW_LOADING) return 0;
  m->vs.round_cancel = 1; /* sticky until app/authority acknowledges the round abort */
#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
  pre_race_tune_clear(&m->pre_tune);
  m->pre_tune_setting = 0;
  m->pre_tune_car_touch = NULL;
  m->pre_tune_car_inside = 0;
#endif
  m->vs.start = m->vs.area_go = m->vs.day = 0;
  go(m, MENU_VS);
  m->bars = 1;
  snprintf(m->vs.note, sizeof m->vs.note, "%s", "CANCELING SELECTION - WAITING FOR ROOM");
  return 1;
}

int menu_vs_cancel_requested(const menu_state *m, uint64_t *round) {
  if (!menu_vs_round_active(m) || !m->vs.round_cancel) return 0;
  if (round) *round = m->vs.round;
  return 1;
}

int menu_vs_round_cancel(menu_state *m, uint64_t round, const char *note) {
  if (!m || !round || m->vs.round != round) return 0; /* stale abort cannot cancel a new round */
  vs_flow_clear(m);
  menu_vs_aborted(m, note ? note : "SELECTION CANCELED - BACK IN ROOM");
  return 1;
}
