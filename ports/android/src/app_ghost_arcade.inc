/* Included in app_ghost.inc: actual shipped catalogue -> native CTarget, not a
 * menu-only list, generic rival or TA replay. All functions run on game thread. */
#include "ghost_catalog_pin.h"
static struct {
  ghost_catalog *catalog;
  menu_ghost_directory_row rows[MENU_GHOST_DIRECTORY_MAX_RECORDS];
  menu_ghost_directory_view view;
  unsigned next_profile, bound_profiles, failed_profiles, row_count, base_rows;
  char crown_note[96];
  int default_filled;
  uint64_t epoch;
  int attempted, published, history_bad;
  int history_slot, history_maker, history_car;
  uint32_t player_races,player_wins;
  long long history_born;
  struct { uint32_t played, won, lost; uint64_t when; } history[GHOST_CATALOG_RECORDS+CAR_GHOST_DEFAULT_RECORDS][GHOST_CATALOG_AREAS];
} AC;
#include "app_ghost_arcade_history.inc"
#include "app_ghost_appearance.inc"
#include "app_ghost_default.inc"
#include "app_ghost_crown.inc"
#include "app_ghost_cloud.inc"
#include "app_ghost_replays.inc"

static uint64_t app_arcade_source_id(unsigned record, unsigned area) {
  return ((uint64_t)(record + 1u) << 32) | (uint64_t)(area + 1u);
}
static int app_arcade_spec(unsigned index, unsigned area, uint64_t token, car_ghost_arcade_spec *spec) {
  if (!spec || !AC.catalog || index >= ghost_catalog_count(AC.catalog) || area >= GHOST_CATALOG_AREAS) return 0;
  const ghost_catalog_record_view *r = ghost_catalog_record(AC.catalog, index);
  const ghost_catalog_area *a = r ? &r->areas[area] : NULL;
  if (!a || a->trail.blob_index == GHOST_CATALOG_NO_BLOB || !a->trail.raw_size || !a->trail.native_stage ||
      !ghost_catalog_area_has(a,GHOST_RAW_car_) || !ghost_catalog_area_has(a,GHOST_RAW_ramp_) ||
      !ghost_catalog_area_has(a,GHOST_RAW_route_) || !ghost_catalog_area_has(a,GHOST_RAW_tune_power_) ||
      !ghost_catalog_area_has(a,GHOST_RAW_tune_handling_) || a->car_ > INT_MAX || a->ramp_ > 21u ||
      a->route_ > INT_MAX || a->tune_power_ > CAR_TUNE_MAX || a->tune_handling_ > CAR_TUNE_MAX) return 0;
  memset(spec,0,sizeof *spec);
  spec->raw_model_id=a->car_;spec->raw_custom_color=a->custom_color_;spec->raw_aero=a->aero_;spec->raw_wheel=a->wheel_;
  spec->power=(int)a->tune_power_; spec->handling=(int)a->tune_handling_;
  spec->dress=a->dress_; spec->dress_x=a->dress_x_; spec->player_win_count=a->player_win_count_;
  spec->raw_ramp=(int)a->ramp_; spec->raw_route=(int)a->route_; spec->header_stage=a->trail.native_stage;
  spec->source_id=app_arcade_source_id(index,area); spec->session_token=token;
  spec->has_crown=a->crown_!=0; /* original historical gameplay flag, NOT a Cinder/server crown */
  spec->first_tutorial=0; /* these source native fields are the reviewed non-tutorial route */
  spec->age_hours=0; /* original non-crown path initializes age to zero; crown date verified separately */
  return 1;
}
static void app_arcade_unbind(void) {
  menu_ghost_set_directory(&G.menu,NULL); /* borrowed rows detached before catalogue close */
  app_arcade_paint_close(0);
  ghost_catalog_close(AC.catalog);
  uint64_t serial=AC.epoch;
  app_cloud_close();
  memset(&AC,0,sizeof AC); AC.epoch=serial; AC.history_slot=-1;
}
void app_ghost_release_assets(int context_lost) {
  app_arcade_paint_close(context_lost!=0);
  app_ghost_clear();app_arcade_unbind();AG.entered=0;
}
static int app_arcade_path(char *path,size_t capacity) {
#ifdef __ANDROID__
  extern int android_optional_resource_path(const char*,char*,size_t);
  return android_optional_resource_path("builtin-ghosts.bin",path,capacity);
#else
  int n=snprintf(path,capacity,"%s/builtin-ghosts.bin",G.data_dir);
  return n>0 && (size_t)n<capacity; /* exact external pin still mandatory on non-Android */
#endif
}
static void app_arcade_directory(void) {
  menu_state *m=&G.menu;
  if(m->screen!=MENU_GHOST || m->ghost.ui.page==GHOST_UI_RESULT || AG.prepared || AG.active || m->ghost.active_request) return;
  if(!AC.attempted) {
    AC.attempted=1; AC.history_slot=-1;
    char path[4096];
    if(!app_arcade_path(path,sizeof path)) return;
    ghost_catalog_result result=ghost_catalog_open_verified(path,GHOST_CATALOG_APPROVED_SHA256,&AC.catalog);
    if(result!=GHOST_CATALOG_OK || ghost_catalog_count(AC.catalog)!=GHOST_CATALOG_RECORDS) {
      ghost_catalog_close(AC.catalog); AC.catalog=NULL;
      app_ghost_note("ORIGINAL GHOST DATA UNAVAILABLE OR UNVERIFIED"); return;
    }
    if(!app_arcade_paint_open()) {
      app_arcade_paint_close(0);ghost_catalog_close(AC.catalog);AC.catalog=NULL;
      app_ghost_note("ORIGINAL CUSTOM PAINT DATA REJECTED");return;
    }
    if(++AC.epoch==0) ++AC.epoch;
    memset(AC.rows,0,sizeof AC.rows);
    for(unsigned i=0;i<GHOST_CATALOG_RECORDS;i++) {
      const ghost_catalog_record_view *r=ghost_catalog_record(AC.catalog,i);
      menu_ghost_directory_row *row=&AC.rows[i];
      row->record_index=i;row->id_devel=r->id_devel;row->id1=r->id1;row->id2=r->id2;
      memcpy(row->name,r->name,sizeof row->name);
      for(unsigned a=0;a<GHOST_CATALOG_AREAS;a++) { row->areas[a].level=-1;row->areas[a].pack=-1; }
    }
    app_ghost_note("VERIFYING ORIGINAL NATIVE ROUTES AND CAR PROFILES");
  }
  if(!AC.catalog) return;
  /* Budget expensive original native lookups; unpublished rows are never read by
   * menu. Rendering/presentation frequency does not advance the physics world. */
  for(unsigned budget=0;budget<32 && AC.next_profile<GHOST_CATALOG_RECORDS*GHOST_CATALOG_AREAS;budget++,AC.next_profile++) {
    unsigned i=AC.next_profile/GHOST_CATALOG_AREAS,a=AC.next_profile%GHOST_CATALOG_AREAS;
    const ghost_catalog_record_view *r=ghost_catalog_record(AC.catalog,i);
    if(r->areas[a].trail.blob_index==GHOST_CATALOG_NO_BLOB) continue;
    car_ghost_arcade_spec spec;car_ghost_arcade_binding b;
    if(!app_arcade_spec(i,a,1,&spec) || !car_ghost_arcade_bind(&spec,&b)) { AC.failed_profiles++;continue; }
    menu_ghost_directory_area *d=&AC.rows[i].areas[a];
    d->level=b.target_level;d->native_available=1;d->ramp=b.ramp;d->route=spec.raw_route;
    d->pack=b.pack;d->paint=b.paint;d->raw_model=spec.raw_model_id;
    d->power=b.rival.power;d->handling=b.rival.handling;d->title=r->areas[a].title_;
    const ghost_catalog_area *style=&r->areas[a];
    d->native_type=(int)b.rival.type;d->base_paint=b.base_paint;d->custom_color=b.custom_color;
    d->aero=(int)style->aero_;d->mirror=(int)style->aero_mirror_;
    d->wing=(int)style->wing_;d->bonnet=(int)style->bonnet_;
    d->wheel=style->wheel_==143u?0:(int)style->wheel_+1;
    d->neon=(int)style->neon_;d->vinyl=(int)style->vinyl_;
    const uint64_t date_fields=(UINT64_C(1)<<GHOST_RAW_year_)|(UINT64_C(1)<<GHOST_RAW_month_)|
      (UINT64_C(1)<<GHOST_RAW_day_)|(UINT64_C(1)<<GHOST_RAW_hour_)|(UINT64_C(1)<<GHOST_RAW_minute_);
    if ((style->present_mask&date_fields)==date_fields)
      d->recorded=app_ghost_record_date(style->year_,style->month_,style->day_,style->hour_,style->minute_);
    AC.bound_profiles++;
  }
  if(AC.next_profile<GHOST_CATALOG_RECORDS*GHOST_CATALOG_AREAS) return;
  if(!AC.default_filled){AC.base_rows=AC.row_count=app_default_directory_fill(GHOST_CATALOG_RECORDS);AC.default_filled=1;}
  app_arcade_history_sync();
  if(!AC.published || m->ghost.directory.rows!=AC.rows || m->ghost.directory.epoch!=AC.epoch) {
    /* Result is dismissed before a new view is published. Detach the borrowed
     * immutable old view before changing its current-card history flags. */
    if(m->ghost.directory.rows==AC.rows) menu_ghost_set_directory(m,NULL);
    AC.row_count=AC.base_rows;
    app_crown_directory();
    app_cloud_directory();
    app_replay_directory();
    AC.view.rows=AC.rows;AC.view.count=AC.row_count;AC.view.epoch=AC.epoch;AC.view.player_level=-1;
    AC.view.player_history_available=0;AC.view.player_revenge_available=0;
    uint64_t wins=app_arcade_history_totals(NULL);
    for(unsigned i=0;i<AC.base_rows;i++)for(unsigned a=0;a<GHOST_CATALOG_AREAS;a++) {
      unsigned history_index=AC.rows[i].record_index+(AC.rows[i].source_kind==MENU_GHOST_SOURCE_DEFAULT?GHOST_CATALOG_RECORDS:0u);
      AC.rows[i].areas[a].history_available=AC.history[history_index][a].played!=0;
      AC.rows[i].areas[a].revenge_available=0; /* losing a preset race is NOT an incoming player counterattack */
      AC.view.player_history_available|=AC.rows[i].areas[a].history_available;
    }
    int power,handling,rank;menu_tune(m,&power,&handling);
    (void)car_ghost_arcade_difficulty(power,handling,wins>UINT32_MAX?UINT32_MAX:(uint32_t)wins,&AC.view.player_level,&rank);
    menu_ghost_set_directory(m,&AC.view);AC.published=1;
    if(!AC.failed_profiles && AC.bound_profiles==GHOST_CATALOG_TRAILS) m->ghost.note[0]=0;
    else app_ghost_note("SOME ORIGINAL PROFILES ARE NOT NATIVE-COMPATIBLE");
    if (GC.count) app_ghost_note("CLOUD REPLAYS ADDED TO LEVEL AND NAME SEARCH");
    if (AC.crown_note[0]) {app_ghost_note(AC.crown_note);AC.crown_note[0]=0;}
  }
}
static int app_arcade_requested(unsigned request) {
  menu_state *m=&G.menu;
  unsigned index=m->ghost.request_record_index;int area=m->ghost.request_area_slot;
  const ghost_catalog_record_view *r=AC.catalog?ghost_catalog_record(AC.catalog,index):NULL;
  if(!AC.published || !request || !r || m->ghost.request_source_kind!=MENU_GHOST_SOURCE_RECORDED || area<0 || area>=8 || m->ghost.request_catalog_epoch!=AC.epoch ||
     m->ghost.request_id_devel!=r->id_devel || m->ghost.request_id1!=r->id1 || m->ghost.request_id2!=r->id2 ||
     !AC.rows[index].areas[area].native_available) {
    (void)menu_ghost_complete(m,request,0,"ORIGINAL SELECTION EXPIRED");return 0;
  }
  if(++AG.serial==0 || AG.serial==UINT64_MAX) AG.serial=1;
  car_ghost_arcade_spec spec;car_ghost_arcade_binding binding;ghost_format_policy policy;
  void *trail=NULL;size_t bytes=0;ghost_format_info info;
  if(!app_arcade_spec(index,(unsigned)area,AG.serial,&spec) || !car_ghost_arcade_bind(&spec,&binding) ||
     m->ghost.request_ramp!=binding.ramp || m->ghost.request_route!=spec.raw_route ||
     !car_ghost_arcade_policy(&binding,&policy) ||
     ghost_catalog_read_trail(AC.catalog,index,(unsigned)area,&policy,&trail,&bytes,&info)!=GHOST_CATALOG_OK) {
    free(trail);car_ghost_clear();(void)menu_ghost_complete(m,request,0,"ORIGINAL TRAIL OR NATIVE ROUTE REJECTED");return 0;
  }
  spec.trail=trail;spec.trail_bytes=bytes;
  int ok=car_ghost_arcade_prepare(&spec,&binding);free(trail);spec.trail=NULL;spec.trail_bytes=0;
  if(!ok) { car_ghost_clear();(void)menu_ghost_complete(m,request,0,"NATIVE ORIGINAL GHOST PREPARATION FAILED");return 0; }
  if(!menu_ghost_complete(m,request,1,"ORIGINAL GHOST PREPARED") || !menu_ghost_begin_pre(m)) { app_ghost_clear();return 0; }
  memset(&AG.config,0,sizeof AG.config);AG.config.abi_version=CAR_GHOST_ABI_VERSION;
  AG.config.session_token=AG.serial;AG.config.kind=CAR_GHOST_CHALLENGE;AG.config.rival=binding.rival;
  memcpy(AG.config.race_field,binding.race_field,sizeof AG.config.race_field);
  AG.token=AG.serial;AG.request=request;AG.arcade=1;AG.arcade_record=index;AG.arcade_area=area;AG.arcade_epoch=AC.epoch;
  AG.arcade_binding=binding;AG.arcade_style=r->areas[area];AG.ramp=m->ghost.request_ramp;AG.route=m->ghost.request_route;
  AG.arcade_card_slot=m->save_slot;AG.arcade_card_born=0;
  if(m->own_sel>=0 && m->own_sel<m->n_own && m->own[m->own_sel].maker==m->maker && m->own[m->own_sel].car==m->car)
    AG.arcade_card_born=m->own[m->own_sel].born;
  AG.course=binding.render_course;AG.prepared=1;AG.maker=m->maker;AG.car=m->car;AG.color=m->color;AG.manual=m->manual;
  (void)menu_ghost_name_glyphs(AG.rival_name,r->name);
  AG.rival_pack=binding.pack;AG.rival_paint=binding.base_paint; /* custom draw override is a separate exact readiness gate */
  m->course=AG.course;m->story_sel=-1;m->finish=m->finish_story=0;
  return 1;
}
static int app_arcade_frozen(void) {
  car_ghost_arcade_binding binding;long long born=0;const menu_state*m=&G.menu;
  if(m->own_sel>=0 && m->own_sel<m->n_own && m->own[m->own_sel].maker==m->maker && m->own[m->own_sel].car==m->car)
    born=m->own[m->own_sel].born;
  if(m->save_slot!=AG.arcade_card_slot || born!=AG.arcade_card_born || m->maker!=AG.maker || m->car!=AG.car || m->color!=AG.color || m->manual!=AG.manual || !AC.catalog || AG.arcade_epoch!=AC.epoch || AG.arcade_area<0 || AG.arcade_area>=8)return 0;
  if(AG.arcade==2) {
    car_ghost_default_binding d;
    if(AG.arcade_record>=CAR_GHOST_DEFAULT_RECORDS || !car_ghost_default_info(&d) || memcmp(&d,&AG.default_binding,sizeof d))return 0;
    binding=d.car;
  } else if ((AG.arcade==1 && AG.arcade_record>=GHOST_CATALOG_RECORDS) ||
             (AG.arcade!=1 && AG.arcade!=3 && AG.arcade!=4) || !car_ghost_arcade_info(&binding)) return 0;
  return binding.source_id==AG.arcade_binding.source_id && binding.pack==AG.rival_pack && binding.base_paint==AG.rival_paint &&
    binding.paint==AG.arcade_binding.paint && binding.custom_color==AG.arcade_binding.custom_color &&
    !memcmp(binding.race_field,AG.config.race_field,sizeof binding.race_field);
}
static int app_ghost_arcade_dressed(void) { return AG.arcade && (AG.prepared || AG.active); }
static void app_ghost_arcade_apply_dress(vs_dress_t *out) {
  memset(out,0,sizeof *out);if(!app_ghost_arcade_dressed())return;
  const ghost_catalog_area *a=&AG.arcade_style;
  out->aero=(int)a->aero_;out->mirror=(int)a->aero_mirror_;out->wing=(int)a->wing_;
  out->bonnet=(int)a->bonnet_;out->wheel=a->wheel_==143u?0:(int)a->wheel_+1;
  out->neon=(int)a->neon_;out->vinyl=(int)a->vinyl_;
}
