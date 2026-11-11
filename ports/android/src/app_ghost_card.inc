/* Card 3 is local outgoing history. Card 4 is the distinct incoming history
 * reported by challengers of this card's uploaded ghost. */
static struct {
  char card[33],requested_card[33];
  int waiting,visible,crown_online;
  double refresh_after;
} AGC;

static void app_ghost_card_defense(const unsigned char *packet,size_t bytes,
                                  menu_card_ghost_stats *stats) {
  enum { HEADER=9, ROW=27 };
  if(bytes<HEADER)return;
  uint32_t wins=ah_u32(packet),races=ah_u32(packet+4);
  unsigned count=packet[8];
  if(wins>races || count>MENU_CARD_GHOST_RECENT || count>races || bytes!=HEADER+ROW*count)return;
  menu_card_ghost_match recent[MENU_CARD_GHOST_RECENT]={0};
  unsigned accepted=0;
  for(unsigned i=0;i<count;++i) {
    const unsigned char *row=packet+HEADER+ROW*i;
    uint64_t when=ah_u64(row);
    uint16_t name[5];
    for(unsigned j=0;j<5;++j)name[j]=(uint16_t)(row[12+j*2]|row[13+j*2]<<8);
    menu_card_ghost_match match={.raw_model=row[9],.hp=row[10]|row[11]<<8,.area=row[22]};
    if(row[8]>1 || match.raw_model>=247 || match.hp<1 || match.hp>1000 ||
       match.area>=GHOST_CROWN_AREAS || !name[0] || !menu_ghost_name_glyphs(match.glyphs,name))continue;
    time_t timestamp=(time_t)when;
    struct tm date;
    if(timestamp>0 && (uint64_t)timestamp==when && localtime_r(&timestamp,&date))
      match.date=app_ghost_record_date(date.tm_year+1900,date.tm_mon+1,date.tm_mday,date.tm_hour,date.tm_min);
    int32_t gap=(int32_t)ah_u32(row+23);
    match.has_gap=gap>=-1000000 && gap<=1000000;
    if(match.has_gap)match.gap_m=(int)gap;
    recent[accepted++]=match;
  }
  stats->defense_races=races;stats->defense_wins=wins;
  stats->defense_recent_count=accepted;
  memcpy(stats->defense_recent,recent,sizeof recent);
}

static unsigned app_ghost_local_crowns(void) {
  const char *physics=car_ghost_physics_id(),*root=app_crown_root();
  if(!root || !physics)return 0;
  unsigned mask=0;
  for(unsigned area=0;area<GHOST_CROWN_AREAS;++area) {
    ghost_crown_record crown={0};
    if(ghost_crown_load(root,area,physics,&crown)==GHOST_STORE_OK &&
       car_ghost_crown_area_matches(area,(int)crown.raw_ramp) &&
       app_replay_is_current_card(&crown))mask|=1u<<area;
    ghost_crown_free(&crown);
  }
  return mask;
}

static void app_ghost_card_menu(void) {
  menu_state *m=&G.menu;
  char key[33]={0};
  int visible=m->screen==MENU_CARD && app_ghost_card_key(key);
  menu_card_ghost_stats *stats=&m->card_ghost_stats;
  if(visible && (!AGC.visible || strcmp(key,AGC.card) || AGC.crown_online!=GC.crown_online)) {
    memset(stats,0,sizeof *stats);
    memcpy(AGC.card,key,sizeof key);
    AGC.refresh_after=0;
    app_ghost_resolve_root();
    app_arcade_history_sync();
    uint64_t races,wins=app_arcade_history_totals(&races);
    stats->races=races>UINT_MAX?UINT_MAX:(unsigned)races;
    stats->wins=wins>UINT_MAX?UINT_MAX:(unsigned)wins;
    /* finiTarget grants one Maxi Coin on ordinary wins. Existing local
     * history never enabled the original revenge bonus. */
    stats->coins=wins>999999u?999999u:(unsigned)wins;
    if(!android_ghost_cloud_configured()) stats->crown_mask=app_ghost_local_crowns();
  } else if(!visible && AGC.visible) memset(stats,0,sizeof *stats);
  if(visible && GC.crown_online)
    stats->crown_mask=GC.crown_ready && !strcmp(key,GC.crown_card)?GC.crown_owned:0;
  AGC.visible=visible;
  AGC.crown_online=GC.crown_online;
  if(AGC.waiting) {
    unsigned char *packet=NULL;
    size_t bytes=0;
    int reply=android_ghost_cloud_defense_poll(&packet,&bytes);
    if(!reply && android_ghost_cloud_configured() && now_ms()<AGC.refresh_after)return;
    AGC.waiting=0;
    if(reply>0 && visible && !strcmp(key,AGC.requested_card))
      app_ghost_card_defense(packet,bytes,stats);
    free(packet);
  }
  if(visible && android_ghost_cloud_configured() && now_ms()>=AGC.refresh_after) {
    AGC.waiting=android_ghost_cloud_defense_refresh(key);
    if(AGC.waiting)memcpy(AGC.requested_card,key,sizeof key);
    AGC.refresh_after=now_ms()+(AGC.waiting?30000.0:1500.0);
  }
}
