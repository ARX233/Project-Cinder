/* Ordinary replays share the validated profile codec, with no crown authority. */
_Static_assert(MENU_GHOST_LOCAL_RECORDS==GHOST_CROWN_AREAS*GHOST_LOCAL_REPLAYS_PER_AREA,
               "local replay directory capacity");

static int app_replay_save(const ghost_crown_record *profile,unsigned area) {
  const char *root=app_crown_root();
  if (!root || area>=GHOST_CROWN_AREAS) return 0;
  unsigned match=GHOST_LOCAL_REPLAYS_PER_AREA,empty=match,oldest=match;
  uint64_t match_rev=0,oldest_rev=0,oldest_stamp=UINT64_MAX;
  for (unsigned slot=0;slot<GHOST_LOCAL_REPLAYS_PER_AREA;++slot) {
    ghost_crown_record prior={0};
    ghost_store_result result=ghost_replay_load(root,area,slot,profile->race.physics_sha256,&prior);
    if (result==GHOST_STORE_NOT_FOUND && empty==GHOST_LOCAL_REPLAYS_PER_AREA) empty=slot;
    if (result!=GHOST_STORE_OK) continue;
    if (!memcmp(prior.name,profile->name,sizeof prior.name) &&
        prior.race.owner.type==profile->race.owner.type &&
        prior.raw_ramp==profile->raw_ramp && prior.race.route==profile->race.route) {
      match=slot;match_rev=prior.revision;
    }
    if (prior.race.recorded_at<oldest_stamp) {
      oldest=slot;oldest_rev=prior.revision;oldest_stamp=prior.race.recorded_at;
    }
    ghost_crown_free(&prior);
  }
  unsigned slot=match<GHOST_LOCAL_REPLAYS_PER_AREA?match:
                empty<GHOST_LOCAL_REPLAYS_PER_AREA?empty:oldest;
  if(slot>=GHOST_LOCAL_REPLAYS_PER_AREA)return 0;
  uint64_t revision=slot==match?match_rev:slot==empty?0:oldest_rev;
  ghost_store_result result=ghost_replay_save(root,area,slot,profile,revision);
  return result==GHOST_STORE_OK || result==GHOST_STORE_COMMITTED_UNSYNCED;
}

static unsigned app_replay_index(unsigned area,unsigned slot) {
  return MENU_GHOST_CLOUD_RECORDS+area*GHOST_LOCAL_REPLAYS_PER_AREA+slot;
}

static int app_replay_is_current_card(const ghost_crown_record *record) {
  const menu_state *m=&G.menu;
  menu_body_color_view player;
  if (m->save_skip || m->name[0]<0 || !menu_body_color_get(m,&player)) return 0;
  if (record->race.owner.type!=(unsigned)player.type) return 0;
  uint16_t name[5];
  return app_ghost_card_name(name) && !memcmp(name,record->name,sizeof name);
}

static void app_replay_directory(void) {
  const char *physics=car_ghost_physics_id(),*root=app_crown_root();
  if (!root || !physics) return;
  const unsigned first=AC.row_count;
  uint64_t timestamps[MENU_GHOST_LOCAL_RECORDS];
  for (unsigned area=0;area<GHOST_CROWN_AREAS;++area)
    for (unsigned slot=0;slot<GHOST_LOCAL_REPLAYS_PER_AREA;++slot) {
      ghost_crown_record record={0};
      if (ghost_replay_load(root,area,slot,physics,&record)!=GHOST_STORE_OK) continue;
      short glyph[5];
      car_ghost_arcade_spec spec;
      car_ghost_arcade_binding binding;
      unsigned index=app_replay_index(area,slot);
      int duplicate=0;
      const app_cloud_snapshot *snapshot=app_cloud_visible();
      for (unsigned i=0;i<snapshot->count;++i) {
        const ghost_crown_record *shared=&snapshot->rows[i].record;
        if (shared->revision==record.revision && shared->race.trail_bytes==record.race.trail_bytes &&
            !memcmp(shared->race.trail,record.race.trail,record.race.trail_bytes)) {duplicate=1;break;}
      }
      if (!duplicate && !app_replay_is_current_card(&record) &&
          menu_ghost_name_glyphs(glyph,record.name) &&
          app_profile_bind(&record,area,1,app_cloud_source(index),0,&spec,&binding) &&
          car_ghost_arcade_validate_trail(&binding,record.race.trail,record.race.trail_bytes)) {
        app_profile_row(&record,area,index,MENU_GHOST_SOURCE_CLOUD,&binding);
        unsigned pos=AC.row_count-1;
        menu_ghost_directory_row row=AC.rows[pos];
        while(pos>first && timestamps[pos-first-1]<record.race.recorded_at) {
          AC.rows[pos]=AC.rows[pos-1];
          timestamps[pos-first]=timestamps[pos-first-1];
          --pos;
        }
        AC.rows[pos]=row;
        timestamps[pos-first]=record.race.recorded_at;
      }
      ghost_crown_free(&record);
    }
}

static int app_replay_requested(unsigned request) {
  const char *physics=car_ghost_physics_id(),*root=app_crown_root();
  unsigned index=G.menu.ghost.request_record_index;
  unsigned area=(unsigned)G.menu.ghost.request_area_slot;
  unsigned local=index-MENU_GHOST_CLOUD_RECORDS;
  ghost_crown_record record={0};
  int loaded=physics && root && local<MENU_GHOST_LOCAL_RECORDS &&
    area==local/GHOST_LOCAL_REPLAYS_PER_AREA &&
    ghost_replay_load(root,area,local%GHOST_LOCAL_REPLAYS_PER_AREA,physics,&record)==GHOST_STORE_OK;
  int ok=app_profile_requested(request,loaded?&record:NULL,area,app_cloud_source(index),0);
  ghost_crown_free(&record);
  return ok;
}

static struct {
  uint64_t serial,token;
  char card[33];
} AGR;

static void app_ta_replay_arm(void) {
  AGR.token=0;
  if(G.menu.game!=MENU_GAME_TA || !app_ghost_card_key(AGR.card))return;
  if(!app_crown_root() && !android_ghost_cloud_configured())return;
  if(++AGR.serial==0)++AGR.serial;
  if(car_ghost_arm_time_attack_recording(AGR.serial))AGR.token=AGR.serial;
}

static int app_ta_replay_export(void *out,size_t capacity,size_t *bytes) {
  return car_ghost_time_attack_recording_export(AGR.token,out,capacity,bytes);
}

static void app_ta_replay_finish(void) {
  if(!AGR.token || G.menu.game!=MENU_GAME_TA || G.car.race.state!=CAR_RACE_GOAL)return;
  char key[33];
  if(!app_ghost_card_key(key) || strcmp(key,AGR.card)) {
    AGR.token=0;
    return;
  }
  int course;
  uint32_t field[6];
  car_spec owner;
  if(!car_ghost_time_attack_recording_info(AGR.token,&course,field,&owner))return;
  int area=car_ghost_time_attack_area(course);
  unsigned raw_ramp=(unsigned)(CAR_GHOST_TA_RAMP_BASE+course);
  ghost_crown_record profile={0};
  if(area>=0 && app_replay_profile(&profile,&owner,raw_ramp,raw_ramp+1u,0,field) &&
     app_replay_capture(&profile,(unsigned)area,AGR.token,app_ta_replay_export)) {
    (void)app_replay_save(&profile,(unsigned)area);
    (void)app_cloud_publish(&profile,(unsigned)area);
  }
  ghost_crown_free(&profile);
  AGR.token=0;
}
