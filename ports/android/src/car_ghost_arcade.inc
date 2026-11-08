/* Actual native world road lists, not blob/header-owned approval. */
#define GHOST_STAGE_TABLE 0x943c1a0u
#define GHOST_STAGE_COUNT 414u
static uintptr_t ghost_arcade_policy_epoch;
static struct {
  uint32_t stage, list, count, kind, ids[GHOST_MAX_AREAS];
  uintptr_t cookie;
  int loop, valid;
} ghost_arcade_policy_state;

static int ghost_stage_areas(uint32_t stage, uint32_t *ids, uint32_t *count, uint32_t *kind) {
  if (!stage || stage >= GHOST_STAGE_COUNT || !rc_mem ||
      !carry_image_span(GHOST_STAGE_TABLE + stage * 16u, 16)) return 0;
  uint32_t at = GHOST_STAGE_TABLE + stage * 16u;
  uint32_t list = M32(at + 4u), mode = M32(at + 8u);
  if (mode < 1u || mode > 5u) return 0;
  for (uint32_t i = 0; i < GHOST_MAX_AREAS; ++i) {
    if (!carry_image_span(list + 4u * i, 4)) return 0;
    uint32_t area = M32(list + 4u * i);
    if (!area) {
      if (!i) return 0;
      *count = i; *kind = mode; return 1;
    }
    if (!carry_area_valid(area)) return 0;
    uint32_t id = M32(area);
    if (!ghost_area_allowed(id, NULL) || M32(STORY_AREA_TABLE + 4u * id) != area ||
        !isfinite(MF(area + 0x20u)) || MF(area + 0x20u) <= 0) return 0;
    ids[i] = id;
  }
  return 0;
}
static int ghost_arcade_policy_live(void *context) {
  /* An opaque non-dereferenced generation token makes old returned policies
   * fail after a new selection, even when the new stage uses the same roads. */
  if ((uintptr_t)context != ghost_arcade_policy_state.cookie || !ghost_arcade_policy_state.valid || !rc_mem) return 0;
  uint32_t ids[GHOST_MAX_AREAS], count, kind;
  return ghost_stage_areas(ghost_arcade_policy_state.stage, ids, &count, &kind) &&
    count == ghost_arcade_policy_state.count && kind == ghost_arcade_policy_state.kind &&
    M32(GHOST_STAGE_TABLE + ghost_arcade_policy_state.stage * 16u + 4u) == ghost_arcade_policy_state.list &&
    !memcmp(ids, ghost_arcade_policy_state.ids, count * sizeof *ids);
}
static int ghost_arcade_area_allowed(uint32_t id, void *context) {
  if (!ghost_arcade_policy_live(context) || !ghost_area_allowed(id, NULL)) return 0;
  for (uint32_t i = 0; i < ghost_arcade_policy_state.count; ++i)
    if (ghost_arcade_policy_state.ids[i] == id) return 1;
  return 0;
}
static int ghost_arcade_sequence_allowed(const uint32_t *ids, uint32_t count, void *context) {
  if (!ids || !count || count > GHOST_MAX_AREAS || !ghost_arcade_policy_live(context)) return 0;
  const uint32_t n = ghost_arcade_policy_state.count;
  int loop = ghost_arcade_policy_state.loop;
  for (uint32_t first = 0; first < n; ++first) {
    if (!loop && count > n - first) continue;
    uint32_t i = 0;
    for (; i < count; ++i)
      if (ids[i] != ghost_arcade_policy_state.ids[(first + i) % n]) break;
    if (i == count) return 1;
  }
  return 0;
}
int car_ghost_arcade_difficulty(int power, int handling, uint32_t wins, int *level, int *rank) {
  if (level) *level = -1;
  if (rank) *rank = -1;
  if (!level || !rank || power < 0 || power > CAR_TUNE_MAX || handling < 0 ||
      handling > CAR_TUNE_MAX || wins > INT_MAX || !ghost_image()) return 0;
  unsigned total = (unsigned)(power + handling);
  if (total > 35u) total = 35u;
  uint32_t row = 0x932a280u + total * 12u;
  if (!carry_image_span(row, 12)) return 0;
  unsigned l = M32(row), r = M32(row + 8u);
  if (l > 8u || r > 8u) return 0;
  if (l == 8u && wins >= 300u) l = 9u;
  if (r == 7u && wins >= 100u) r = 8u;
  *level = (int)l; *rank = (int)r;
  return 1;
}
static int ghost_arcade_field(int raw_ramp, int route, int tutorial, uint32_t field[6],
                              int *ramp, int *route_count) {
  if (raw_ramp < 0 || raw_ramp >= CAR_GHOST_TA_RAMP_BASE + CAR_COURSES || !ghost_image()) return 0;
  if (raw_ramp >= CAR_GHOST_TA_RAMP_BASE) {
    if (route || tutorial || !ghost_time_attack_field(raw_ramp - CAR_GHOST_TA_RAMP_BASE, field)) return 0;
    *ramp = raw_ramp + 1;
    *route_count = 1;
    return 1;
  }
  uint32_t record = M32(0x9739140u + 4u * (uint32_t)raw_ramp);
  if (!carry_image_span(record, 24)) return 0;
  uint32_t eramp = M32(record + 8u), count = M32(record + 20u);
  if (!count || count > 64u || route < 0 || (uint32_t)route >= count ||
      !ghost_native_race_field((int)eramp, route, tutorial, field)) return 0;
  *ramp = (int)eramp;
  *route_count = (int)count;
  return 1;
}
int car_ghost_arcade_bind(const car_ghost_arcade_spec *spec, car_ghost_arcade_binding *binding) {
  if (binding) memset(binding, 0, sizeof *binding);
  if (!spec || !binding || !spec->source_id ||
      (spec->raw_ramp >= CAR_GHOST_TA_RAMP_BASE && spec->has_crown) ||
      spec->raw_route < 0 || !spec->header_stage || spec->dress > 65535u || spec->dress_x > 31u ||
      spec->raw_aero > 3u || (spec->raw_wheel != 143u && spec->raw_wheel >= 113u) ||
      spec->power < 0 || spec->power > CAR_TUNE_MAX || spec->handling < 0 || spec->handling > CAR_TUNE_MAX ||
      spec->power + spec->handling > CAR_TUNE_TOTAL || (spec->has_crown != 0 && spec->has_crown != 1) ||
      (spec->first_tutorial != 0 && spec->first_tutorial != 1) || spec->age_hours < 0 || spec->age_hours > 876000 ||
      rc_ghost_native_bridge != GHOST_BRIDGE_MAGIC || !car_ghost_physics_id() || !ghost_image()) return 0;
  int ramp, route_count;
  uint32_t field[6];
  if (!ghost_arcade_field(spec->raw_ramp, spec->raw_route, spec->first_tutorial, field, &ramp, &route_count) ||
      field[0] != spec->header_stage) return 0;
  uint32_t stage_ids[GHOST_MAX_AREAS], stage_count, kind;
  if (!ghost_stage_areas(field[0], stage_ids, &stage_count, &kind)) return 0;
  /* The native ramp helper independently supplies the start area. A branching
   * Tokyo path can begin before its StageAry route list (e.g. stage289/ramp10).
   * Do not invent an additional start-in-selected-path requirement. */
  int index = -1;
  for (unsigned i = 0; i < sizeof GHOST_ARCADE_MODELS / sizeof *GHOST_ARCADE_MODELS; ++i)
    if (GHOST_ARCADE_MODELS[i].model == spec->raw_model_id) { index = (int)i; break; }
  if (index < 0) return 0;
  unsigned m = GHOST_ARCADE_MODELS[index].maker, c = GHOST_ARCADE_MODELS[index].car,
           k = GHOST_ARCADE_MODELS[index].color;
  if (m >= CARDB_ALL || c >= (unsigned)CARDB_NCARS[m] || k >= (unsigned)CARDB_CARS[m][c].ncolors) return 0;
  const cardb_color *color = &CARDB_CARS[m][c].colors[k];
  if (color->swatch != GHOST_ARCADE_MODELS[index].swatch || color->type != GHOST_ARCADE_MODELS[index].type ||
      color->gears != GHOST_ARCADE_MODELS[index].gears || color->pack != GHOST_ARCADE_MODELS[index].pack ||
      color->paint != GHOST_ARCADE_MODELS[index].paint || color->pack < 0 || color->pack >= CARDB_NPACKS) return 0;
  car_ghost_arcade_binding out = {0};
  out.rival.type = (unsigned)color->type; out.rival.gears = color->gears;
  if (spec->raw_custom_color > GHOST_ARCADE_PALETTES[color->pack].custom) return 0;
  memcpy(out.rival.tyres, GHOST_ARCADE_TYRES[color->pack][spec->raw_aero][spec->raw_wheel != 143u], sizeof out.rival.tyres);
  if (out.rival.tyres[1] <= 0 || out.rival.tyres[4] <= 0) return 0;
  out.rival.spokes = spec->raw_wheel == 143u ? GHOST_ARCADE_STOCK_SPOKES[color->pack] :
                                            GHOST_ARCADE_WHEEL_SPOKES[spec->raw_wheel];
  out.rival.power = spec->power; out.rival.handling = spec->handling;
  memcpy(out.race_field, field, sizeof field);
  out.maker = (int)m; out.car = (int)c; out.color = (int)k;
  out.pack = color->pack; out.base_paint = color->paint; out.custom_color = (int)spec->raw_custom_color;
  out.paint = spec->raw_custom_color ? GHOST_ARCADE_PALETTES[color->pack].base + (int)spec->raw_custom_color - 1 : color->paint;
  out.city = car_area_city((int)field[2]); out.render_course = -1;
  if (spec->raw_ramp >= CAR_GHOST_TA_RAMP_BASE) {
    out.render_course = spec->raw_ramp - CAR_GHOST_TA_RAMP_BASE;
  } else {
    for (int course = 0; course < CAR_COURSES; ++course)
      if (car_course_city(course) == out.city) { out.render_course = course; break; }
  }
  if (out.render_course < 0 || !car_ghost_arcade_difficulty(spec->power, spec->handling, spec->player_win_count,
                                                        &out.target_level, &out.target_rank)) return 0;
  out.route_count = route_count; out.source_id = spec->source_id;
  out.raw_ramp = spec->raw_ramp; out.raw_route = spec->raw_route; out.first_tutorial = spec->first_tutorial;
  out.ramp = ramp;
  *binding = out;
  return 1;
}
int car_ghost_arcade_policy(const car_ghost_arcade_binding *binding, ghost_format_policy *policy) {
  if (policy) memset(policy, 0, sizeof *policy);
  memset(&ghost_arcade_policy_state, 0, sizeof ghost_arcade_policy_state);
  if (!binding || !policy || !binding->source_id) return 0;
  int ramp, route_count;
  uint32_t field[6];
  if (!ghost_arcade_field(binding->raw_ramp, binding->raw_route, binding->first_tutorial, field, &ramp, &route_count) ||
      ramp != binding->ramp || route_count != binding->route_count ||
      memcmp(field, binding->race_field, sizeof field) ||
      !ghost_stage_areas(field[0], ghost_arcade_policy_state.ids,
                        &ghost_arcade_policy_state.count, &ghost_arcade_policy_state.kind)) return 0;
  ghost_arcade_policy_state.stage = field[0];
  ghost_arcade_policy_state.list = M32(GHOST_STAGE_TABLE + field[0] * 16u + 4u);
  /* StageAry +12 selects the road processor at CSeq::Init 0x8987e0d.
   * Native Tokyo Time Attack courses with processor 1 are loops. In
   * particular C1 In repeats its start area at the end of the first lap. */
  ghost_arcade_policy_state.loop = ghost_arcade_policy_state.kind != 2u ||
    (binding->raw_ramp >= CAR_GHOST_TA_RAMP_BASE &&
     M32(GHOST_STAGE_TABLE + field[0] * 16u + 12u) == 1u);
  if (ghost_arcade_policy_epoch == UINTPTR_MAX) return 0; /* never recycle old capabilities */
  ghost_arcade_policy_state.cookie = ++ghost_arcade_policy_epoch;
  ghost_arcade_policy_state.valid = 1;
  *policy = (ghost_format_policy){.stage=field[0], .area_allowed=ghost_arcade_area_allowed,
    .context=(void *)ghost_arcade_policy_state.cookie, .area_sequence_allowed=ghost_arcade_sequence_allowed,
    .max_ticks=binding->raw_ramp >= CAR_GHOST_TA_RAMP_BASE && field[0] == GHOST_LONG_TA_STAGE ?
        GHOST_LONG_TA_MAX_TICKS : 0u};
  return 1;
}
