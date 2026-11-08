/* Offline equivalent of finiTarget's win -> save -> publish per-area crown.
 * Only locally sampled trajectories can replace a local champion. */
#include "namedb.h"

static char ghost_crown_save_dir[512];

void app_ghost_crown_save_dir(const char *dir) {
  ghost_crown_save_dir[0]=0;
  if (dir && dir[0]=='/' && strlen(dir)<sizeof ghost_crown_save_dir)
    memcpy(ghost_crown_save_dir,dir,strlen(dir)+1);
}

static const char *app_crown_root(void) {
#ifndef __ANDROID__
  if (!ghost_crown_save_dir[0] && AG.root_valid) return AG.physical_root;
#endif
  return ghost_crown_save_dir[0] ? ghost_crown_save_dir : NULL;
}

static uint64_t app_crown_source(unsigned area) {
  return UINT64_C(0x4000000000000000)+(uint64_t)area+1u;
}

static int app_profile_bind(const ghost_crown_record *record,unsigned area,uint64_t token,
                            uint64_t source,int crown,car_ghost_arcade_spec *spec,car_ghost_arcade_binding *binding) {
  const ghost_store_record *race=&record->race;
  *spec=(car_ghost_arcade_spec){
    .raw_model_id=record->raw_model,.power=race->owner.power,.handling=race->owner.handling,
    .raw_ramp=(int)record->raw_ramp,.raw_route=(int)race->route,.header_stage=race->race_field[0],
    .source_id=source,.session_token=token,.has_crown=crown,
    .raw_custom_color=record->custom_color,.raw_aero=record->aero,.raw_wheel=record->wheel,
    .trail=race->trail,.trail_bytes=race->trail_bytes,
  };
  int matches=spec->raw_ramp<CAR_GHOST_TA_RAMP_BASE ?
    car_ghost_crown_area_matches(area,spec->raw_ramp) :
    !crown && area<GHOST_CROWN_AREAS && car_ghost_time_attack_area(spec->raw_ramp-CAR_GHOST_TA_RAMP_BASE)==(int)area;
  return matches && car_ghost_arcade_bind(spec,binding) &&
    (uint32_t)binding->ramp==race->ramp && binding->rival.type==race->owner.type &&
    binding->rival.gears==race->owner.gears && !memcmp(binding->race_field,race->race_field,24);
}

static void app_profile_row(const ghost_crown_record *record,unsigned area,unsigned index,
                            unsigned source_kind,const car_ghost_arcade_binding *binding) {
  menu_ghost_directory_row *row=&AC.rows[AC.row_count++];
  *row=(menu_ghost_directory_row){.record_index=index,.id1=(uint32_t)record->revision,
    .id2=(uint32_t)(record->revision>>32),.source_kind=source_kind};
  memcpy(row->name,record->name,sizeof row->name);
  row->areas[area]=(menu_ghost_directory_area){
    .level=binding->target_level,.native_available=1,.ramp=binding->ramp,.route=binding->raw_route,
    .pack=binding->pack,.paint=binding->paint,.raw_model=record->raw_model,
    .power=binding->rival.power,.handling=binding->rival.handling,.title=record->title,
    .native_type=(int)binding->rival.type,.base_paint=binding->base_paint,.custom_color=binding->custom_color,
    .aero=(int)record->aero,.mirror=(int)record->mirror,.wing=(int)record->wing,.bonnet=(int)record->bonnet,
    .wheel=record->wheel==143u?0:(int)record->wheel+1,.neon=(int)record->neon,.vinyl=(int)record->vinyl,
  };
  time_t stamp=(time_t)record->race.recorded_at;
  struct tm date;
  if (stamp>0 && (uint64_t)stamp==record->race.recorded_at && localtime_r(&stamp,&date))
    row->areas[area].recorded=app_ghost_record_date(date.tm_year+1900,date.tm_mon+1,date.tm_mday,
                                                   date.tm_hour,date.tm_min);
}
static void app_crown_directory(void) {
  const char *physics=car_ghost_physics_id(),*root=app_crown_root();
  if (!root || !physics) return;
  for (unsigned area=0;area<GHOST_CROWN_AREAS;++area) {
    ghost_crown_record record={0};
    if (ghost_crown_load(root,area,physics,&record)!=GHOST_STORE_OK) continue;
    short glyph[5];
    car_ghost_arcade_spec spec;car_ghost_arcade_binding binding;
    if (menu_ghost_name_glyphs(glyph,record.name) &&
        app_profile_bind(&record,area,1,app_crown_source(area),1,&spec,&binding) &&
        car_ghost_arcade_validate_trail(&binding,record.race.trail,record.race.trail_bytes))
      app_profile_row(&record,area,area,MENU_GHOST_SOURCE_LOCAL_CROWN,&binding);
    ghost_crown_free(&record);
  }
}

static void app_crown_arm(void) {
  const menu_state *m=&G.menu;
  int record=app_crown_root() && !m->save_skip && m->name[0]>=0 && AG.arcade_card_born>0;
  AG.crown_challenge=car_ghost_arm_local_crown(AG.token,record);
  if (AG.crown_challenge && record) AG.config.record_player=1;
}

static int app_profile_requested(unsigned request,const ghost_crown_record *record,unsigned area,
                                 uint64_t source,int crown) {
  menu_state *m=&G.menu;
  uint64_t revision=(uint64_t)m->ghost.request_id2<<32|m->ghost.request_id1;
  car_ghost_arcade_spec spec;car_ghost_arcade_binding binding;
  if (++AG.serial==0 || AG.serial==UINT64_MAX) AG.serial=1;
  int ok=record && AC.published && m->ghost.request_catalog_epoch==AC.epoch &&
    record->revision==revision && app_profile_bind(record,area,AG.serial,source,crown,&spec,&binding) &&
    binding.ramp==m->ghost.request_ramp && binding.raw_route==m->ghost.request_route &&
    car_ghost_arcade_prepare(&spec,&binding);
  if (!ok) {
    car_ghost_clear();
    (void)menu_ghost_complete(m,request,0,crown?"LOCAL CHAMPION RECORD CHANGED OR INVALID":"CLOUD REPLAY UNAVAILABLE");
    return 0;
  }
  if (!menu_ghost_complete(m,request,1,crown?"LOCAL CHAMPION PREPARED":"CLOUD REPLAY PREPARED") ||
      !menu_ghost_begin_pre(m)) {
    app_ghost_clear();
    return 0;
  }
  if(!crown)(void)car_ghost_arm_rival_runout(AG.serial);
  AG.config=(car_ghost_config){.abi_version=CAR_GHOST_ABI_VERSION,.session_token=AG.serial,
    .kind=CAR_GHOST_CHALLENGE,.rival=binding.rival};
  memcpy(AG.config.race_field,binding.race_field,24);
  AG.arcade_binding=binding;
  AG.arcade_style=(ghost_catalog_area){.car_=record->raw_model,.custom_color_=record->custom_color,
    .aero_=record->aero,.aero_mirror_=record->mirror,.wing_=record->wing,.bonnet_=record->bonnet,
    .wheel_=record->wheel,.neon_=record->neon,.vinyl_=record->vinyl,.title_=record->title,
    .class_=record->class_id,.crown_=(uint32_t)crown};
  AG.token=AG.serial;AG.request=request;AG.arcade=crown?3:4;
  AG.arcade_record=m->ghost.request_record_index;AG.arcade_area=(int)area;
  AG.arcade_epoch=AC.epoch;AG.crown_revision=crown?revision:0;
  AG.ramp=binding.ramp;AG.route=binding.raw_route;AG.course=binding.render_course;AG.prepared=1;
  AG.maker=m->maker;AG.car=m->car;AG.color=m->color;AG.manual=m->manual;
  AG.arcade_card_slot=m->save_slot;
  AG.arcade_card_born=m->own_sel>=0 && m->own_sel<m->n_own &&
    m->own[m->own_sel].maker==m->maker && m->own[m->own_sel].car==m->car ? m->own[m->own_sel].born : 0;
  (void)menu_ghost_name_glyphs(AG.rival_name,record->name);
  AG.rival_pack=binding.pack;AG.rival_paint=binding.base_paint;
  m->course=AG.course;m->story_sel=-1;m->finish=m->finish_story=0;
  return 1;
}

static int app_crown_requested(unsigned request) {
  menu_state *m=&G.menu;
  unsigned area=(unsigned)m->ghost.request_area_slot;
  const char *physics=car_ghost_physics_id(),*root=app_crown_root();
  ghost_crown_record record={0};
  int loaded=root && physics && area<GHOST_CROWN_AREAS && area==m->ghost.request_record_index &&
    ghost_crown_load(root,area,physics,&record)==GHOST_STORE_OK;
  int ok=app_profile_requested(request,loaded?&record:NULL,area,app_crown_source(area),1);
  ghost_crown_free(&record);
  if (ok) app_crown_arm();
  else AC.published=0;
  return ok;
}

static int app_replay_profile(ghost_crown_record *profile,const car_spec *owner,
                              unsigned raw_ramp,unsigned ramp,unsigned route,const uint32_t field[6]) {
  const menu_state *m=&G.menu;
  menu_body_color_view player;
  const char *physics=car_ghost_physics_id();
  if (!physics || strlen(physics)!=64 || m->save_skip || m->name[0]<0 ||
      m->own_sel<0 || m->own_sel>=m->n_own || m->own[m->own_sel].born<=0 ||
      m->own[m->own_sel].maker!=m->maker || m->own[m->own_sel].car!=m->car ||
      !menu_body_color_get(m,&player)) return 0;
  int maker=m->maker,car=m->car;
  *profile=(ghost_crown_record){
    .raw_model=(uint32_t)player.raw_model,.raw_ramp=raw_ramp,
    .custom_color=(uint32_t)player.custom_color,.aero=(uint32_t)player.aero,
    .mirror=(uint32_t)m->mirror[maker][car],.wing=(uint32_t)m->wing[maker][car],
    .bonnet=(uint32_t)player.bonnet,.wheel=m->wheel[maker][car]?(uint32_t)m->wheel[maker][car]-1u:143u,
    .neon=(uint32_t)m->neon[maker][car],.vinyl=(uint32_t)player.vinyl,
    .title=(uint32_t)menu_title(m),.class_id=(uint32_t)m->class_car[maker][car],
    .race={.ramp=ramp,.route=route,.owner=*owner},
  };
  for (unsigned i=0;i<5 && m->name[i]>=0 && m->name[i]<NAMEDB_N;++i)
    profile->name[i]=NAMEDB_WCHAR[m->name[i]];
  memcpy(profile->race.race_field,field,sizeof profile->race.race_field);
  memcpy(profile->race.physics_sha256,physics,sizeof profile->race.physics_sha256);
  return 1;
}

static int app_replay_capture(ghost_crown_record *profile,unsigned area,uint64_t token,
                              int (*export_trail)(void *,size_t,size_t *)) {
  size_t bytes=0;
  if (!export_trail(NULL,0,&bytes) || !bytes || bytes>GHOST_MAX_BYTES) return 0;
  time_t now=time(NULL);
  profile->race.recorded_at=now>0?(uint64_t)now:0;
  profile->race.trail=malloc(bytes);
  car_ghost_arcade_spec spec;
  car_ghost_arcade_binding binding;
  if (profile->race.trail && export_trail(profile->race.trail,bytes,&profile->race.trail_bytes) &&
      profile->race.trail_bytes==bytes &&
      app_profile_bind(profile,area,token,app_crown_source(area),0,&spec,&binding) &&
      car_ghost_arcade_validate_trail(&binding,profile->race.trail,bytes)) return 1;
  ghost_crown_free(profile);
  return 0;
}

static int app_ghost_capture_profile(int export_ready,ghost_crown_record *out) {
  return export_ready &&
    app_replay_profile(out,&AG.owner,(unsigned)AG.arcade_binding.raw_ramp,(unsigned)AG.ramp,(unsigned)AG.route,AG.config.race_field) &&
    app_replay_capture(out,(unsigned)AG.arcade_area,AG.token,car_ghost_export);
}

static const char *app_crown_publish(const ghost_crown_record *record, char *error, size_t error_size) {
  const char *root=app_crown_root();
  if (!root) return "LOCAL CROWN STORAGE UNAVAILABLE";
  if (!AG.config.record_player) return "LOCAL CROWN REQUIRES A REGISTERED CARD";
  if (!record) return "INCOMPLETE WINNER TRAIL - PREVIOUS CHAMPION KEPT";
  ghost_store_result result=ghost_crown_save(root,(unsigned)AG.arcade_area,record,AG.crown_revision);
  if (result==GHOST_STORE_OK) return "LOCAL COURSE CHAMPION UPDATED";
  if (result==GHOST_STORE_COMMITTED_UNSYNCED) return "LOCAL CHAMPION UPDATED - DURABILITY UNCONFIRMED";
  snprintf(error, error_size, "CROWN SAVE FAILED - %s", ghost_store_error(result));
  return error;
}
