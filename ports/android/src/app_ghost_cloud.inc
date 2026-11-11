/* Android owns HTTP and retries. The game thread binds immutable native data. */
#ifdef __ANDROID__
extern int android_ghost_cloud_configured(void);
extern int android_ghost_cloud_refresh(const char *physics);
extern int android_ghost_cloud_search(const char *physics,const uint16_t *name,unsigned name_length);
extern int android_ghost_cloud_poll(unsigned char **data,size_t *bytes);
extern int android_ghost_cloud_enqueue_card(unsigned area,const void *data,size_t bytes,const char *card_id);
extern int android_ghost_cloud_report(const unsigned char id[16],int won,unsigned raw_model,
                                      unsigned hp,int32_t ghost_gap,const uint16_t *name,unsigned name_length);
extern int android_ghost_cloud_defense_refresh(const char *card_id);
extern int android_ghost_cloud_defense_poll(unsigned char **data,size_t *bytes);
extern int android_ghost_crown_refresh(const char *physics,const char *key);
extern int android_ghost_crown_poll(unsigned char **data,size_t *bytes);
extern int android_ghost_crown_ack(void);
extern int android_ghost_crown_enqueue(unsigned area,const unsigned char previous[16],
                                       const void *data,size_t bytes,const char *card_id);
#else
static int android_ghost_cloud_configured(void) { return 0; }
static int android_ghost_cloud_refresh(const char *physics) { (void)physics;return 0; }
static int android_ghost_cloud_search(const char *physics,const uint16_t *name,unsigned n) {
  (void)physics;(void)name;(void)n;return 0;
}
static int android_ghost_cloud_poll(unsigned char **data,size_t *bytes) { (void)data;(void)bytes;return 0; }
static int android_ghost_cloud_enqueue_card(unsigned area,const void *data,size_t bytes,const char *key) {
  (void)area;(void)data;(void)bytes;(void)key;return 0;
}
static int android_ghost_cloud_report(const unsigned char id[16],int won,unsigned model,unsigned hp,
                                      int32_t gap,const uint16_t *name,unsigned n) {
  (void)id;(void)won;(void)model;(void)hp;(void)gap;(void)name;(void)n;return 0;
}
static int android_ghost_cloud_defense_refresh(const char *key) { (void)key;return 0; }
static int android_ghost_cloud_defense_poll(unsigned char **data,size_t *bytes) { (void)data;(void)bytes;return 0; }
static int android_ghost_crown_refresh(const char *physics,const char *key) { (void)physics;(void)key;return 0; }
static int android_ghost_crown_poll(unsigned char **data,size_t *bytes) { (void)data;(void)bytes;return 0; }
static int android_ghost_crown_ack(void) { return 0; }
static int android_ghost_crown_enqueue(unsigned area,const unsigned char previous[16],
                                       const void *data,size_t bytes,const char *card_id) {
  (void)area;(void)previous;(void)data;(void)bytes;(void)card_id;return 0;
}
#endif

typedef struct {
  ghost_crown_record record;
  car_ghost_arcade_binding binding;
  unsigned area;
  unsigned char id[16];
} app_cloud_row;

typedef struct {
  unsigned count;
  app_cloud_row rows[MENU_GHOST_CLOUD_RECORDS];
} app_cloud_snapshot;

static struct {
  unsigned wait,search_count;
  int search_ready;
  int use_search;
  double refresh_after,request_deadline;
  uint16_t search[5];
  app_cloud_snapshot discovery, matches, crowns;
  int crown_online,crown_ready,crown_wait;
  unsigned crown_occupied,crown_owned;
  uint64_t crown_generation;
  char crown_card[33],crown_requested_card[33];
  double crown_refresh_after,crown_deadline;
} GC;

static const app_cloud_snapshot *app_cloud_visible(void) {
  return GC.use_search ? &GC.matches : &GC.discovery;
}

static unsigned app_ghost_card_name(uint16_t name[5]) {
  unsigned n=0;
  memset(name,0,5*sizeof *name);
  while(n<5 && G.menu.name[n]>=0 && G.menu.name[n]<NAMEDB_N) {
    name[n]=NAMEDB_WCHAR[G.menu.name[n]];++n;
  }
  return n;
}

static int app_ghost_card_key(char key[33]) {
  const menu_state *m=&G.menu;
  if(m->save_skip || m->save_slot<1 || m->save_slot>MENU_SAVES ||
     m->own_sel<0 || m->own_sel>=m->n_own || m->name[0]<0) return 0;
  const menu_own *card=&m->own[m->own_sel];
  if(card->born<=0 || card->maker!=m->maker || card->car!=m->car) return 0;
  unsigned char input[40]="CINDER-GHOST-CARD-v1", hash[32];
  ah_w32(input+20,(uint32_t)m->save_slot);ah_w32(input+24,(uint32_t)card->maker);
  ah_w32(input+28,(uint32_t)card->car);ah_w64(input+32,(uint64_t)card->born);
  ghost_catalog_sha256_bytes(input,sizeof input,hash);
  static const char digits[]="0123456789abcdef";
  for(unsigned i=0;i<16;++i){key[i*2]=digits[hash[i]>>4];key[i*2+1]=digits[hash[i]&15];}
  key[32]=0;
  return 1;
}

static uint64_t app_cloud_source(unsigned index) {
  return UINT64_C(0x5000000000000000)+index+1u;
}
static void app_cloud_free(app_cloud_snapshot *snapshot) {
  for (unsigned i=0;i<snapshot->count;++i) ghost_crown_free(&snapshot->rows[i].record);
  snapshot->count=0;
}
static void app_cloud_invalidate_directory(void) {
  AC.published=0;
  if(++AC.epoch==0)++AC.epoch;
}
static void app_cloud_select_snapshot(int use_search) {
  if(GC.use_search==use_search)return;
  GC.use_search=use_search;
  app_cloud_invalidate_directory();
}
static void app_cloud_close(void) {
  app_cloud_free(&GC.discovery);
  app_cloud_free(&GC.matches);
  app_cloud_free(&GC.crowns);
  memset(&GC,0,sizeof GC);
}

static int app_cloud_unpack(app_cloud_snapshot *snapshot,unsigned char *packet,size_t length,int crown) {
  enum { ROW_BYTES=21 };
  if(!length || packet[0]>(crown?GHOST_CROWN_AREAS:MENU_GHOST_CLOUD_RECORDS))return 0;
  unsigned count=packet[0];
  size_t at=1;
  unsigned occupied=0;
  for(unsigned i=0;i<count;++i) {
    if(length-at<ROW_BYTES)return 0;
    unsigned area=packet[at];
    if(crown) {
      if(area>=GHOST_CROWN_AREAS || (occupied&(1u<<area)))return 0;
      occupied|=1u<<area;
    }
    uint32_t bytes=ah_u32(packet+at+17);
    at+=ROW_BYTES;
    if(bytes>length-at)return 0;
    at+=bytes;
  }
  if(at!=length)return 0;
  app_cloud_row rows[MENU_GHOST_CLOUD_RECORDS]={0};
  unsigned accepted=0;
  at=1;
  for(unsigned i=0;i<count;++i) {
    unsigned area=packet[at];
    const unsigned char *id=packet+at+1;
    uint32_t bytes=ah_u32(packet+at+17);
    at+=ROW_BYTES;
    app_cloud_row *row=&rows[accepted];
    short glyph[5];
    car_ghost_arcade_spec spec;
    if(bytes && area<GHOST_CROWN_AREAS &&
       ghost_profile_unpack(packet+at,bytes,car_ghost_physics_id(),&row->record)==GHOST_STORE_OK &&
       menu_ghost_name_glyphs(glyph,row->record.name) &&
       app_profile_bind(&row->record,area,1,crown?app_crown_source(area):app_cloud_source(accepted),
                        crown,&spec,&row->binding) &&
       car_ghost_arcade_validate_trail(&row->binding,row->record.race.trail,row->record.race.trail_bytes)) {
      row->area=area;memcpy(row->id,id,sizeof row->id);++accepted;
    } else ghost_crown_free(&row->record);
    at+=bytes;
  }
  int changed=accepted!=snapshot->count;
  for(unsigned i=0;!changed && i<accepted;++i)
    changed=memcmp(rows[i].id,snapshot->rows[i].id,sizeof rows[i].id)!=0;
  if(crown && (occupied!=GC.crown_occupied || changed)) {
    ++GC.crown_generation;
    app_cloud_invalidate_directory();
  }
  if(crown)GC.crown_occupied=occupied;
  if(changed) {
    app_cloud_free(snapshot);
    memcpy(snapshot->rows,rows,sizeof rows);snapshot->count=accepted;
    if(snapshot==app_cloud_visible())app_cloud_invalidate_directory();
  } else for(unsigned i=0;i<accepted;++i)ghost_crown_free(&rows[i].record);
  return 1;
}

static void app_cloud_crown_tick(int configured,int visible) {
  if(configured!=GC.crown_online) {
    GC.crown_online=configured;
    GC.crown_ready=GC.crown_wait=0;
    GC.crown_refresh_after=0;
    GC.crown_occupied=GC.crown_owned=0;
    GC.crown_card[0]=0;
    app_cloud_free(&GC.crowns);
    app_cloud_invalidate_directory();
  }
  if(!configured)return;
  int ack=android_ghost_crown_ack();
  if(ack) {
    if(G.menu.crown_award.active && G.menu.crown_award.pending) {
      G.menu.crown_award.pending=0;
      if(ack<0)G.menu.crown_award.active=0;
    }
    snprintf(AC.crown_note,sizeof AC.crown_note,"%s",ack>0?"SERVER CROWN UPDATED":
      ack==-1?"SERVER CROWN CHANGED - CHALLENGE THE CURRENT HOLDER":"SERVER REJECTED CROWN RECORD");
    GC.crown_refresh_after=0;
    if(GC.crown_wait) {
      unsigned char *packet=NULL;
      size_t length=0;
      (void)android_ghost_crown_poll(&packet,&length);
      free(packet);
      GC.crown_wait=0;
    }
    if(GC.crown_ready) {
      GC.crown_ready=0;
      app_cloud_invalidate_directory();
    }
  }
  double now=now_ms();
  if(GC.crown_wait) {
    unsigned char *packet=NULL;
    size_t length=0;
    int reply=android_ghost_crown_poll(&packet,&length);
    if(!reply && now<GC.crown_deadline)return;
    int ready=reply>0 && length>=2 && app_cloud_unpack(&GC.crowns,packet+1,length-1,1);
    GC.crown_owned=ready?packet[0]:0;
    if(ready)memcpy(GC.crown_card,GC.crown_requested_card,sizeof GC.crown_card);
    free(packet);
    if(GC.crown_ready!=ready)app_cloud_invalidate_directory();
    GC.crown_ready=ready;
    GC.crown_wait=0;
    if(!ready)GC.crown_refresh_after=now+5000.0;
  }
  const char *physics=car_ghost_physics_id();
  char key[33]={0};
  int has_card=!menu_in_attract(&G.menu) && app_ghost_card_key(key);
  if(visible && physics && (now>=GC.crown_refresh_after || (GC.crown_ready && strcmp(key,GC.crown_card)))) {
    GC.crown_wait=android_ghost_crown_refresh(physics,has_card?key:NULL);
    if(GC.crown_wait)memcpy(GC.crown_requested_card,key,sizeof key);
    GC.crown_refresh_after=now+(GC.crown_wait?15000.0:1500.0);
    GC.crown_deadline=now+30000.0;
  }
}

static void app_cloud_crown_directory(void) {
  if(!GC.crown_ready)return;
  for(unsigned i=0;i<GC.crowns.count;++i) {
    const app_cloud_row *row=&GC.crowns.rows[i];
    app_profile_row(&row->record,row->area,row->area,MENU_GHOST_SOURCE_LOCAL_CROWN,&row->binding);
  }
}

static int app_cloud_crown_requested(unsigned request) {
  unsigned area=(unsigned)G.menu.ghost.request_area_slot;
  const app_cloud_row *row=NULL;
  if(GC.crown_ready && android_ghost_cloud_configured())
    for(unsigned i=0;i<GC.crowns.count;++i)
      if(GC.crowns.rows[i].area==area) { row=&GC.crowns.rows[i];break; }
  if(!app_profile_requested(request,row?&row->record:NULL,area,app_crown_source(area),1)) {
    GC.crown_refresh_after=0;
    return 0;
  }
  AG.cloud_crown=1;
  memcpy(AG.crown_opponent,row->id,sizeof AG.crown_opponent);
  app_crown_arm();
  return 1;
}

static const char *app_cloud_crown_publish(const ghost_crown_record *record,int *submitted) {
  char key[33];
  if(!AG.config.record_player || !app_ghost_card_key(key))return "SERVER CROWN REQUIRES A REGISTERED CARD";
  unsigned char *blob=NULL;
  size_t length=0;
  if(!record || ghost_profile_pack(record,&blob,&length)!=GHOST_STORE_OK)
    return "INCOMPLETE WINNER TRAIL - SERVER CROWN KEPT";
  int queued=android_ghost_crown_enqueue((unsigned)AG.arcade_area,AG.crown_opponent,blob,length,key);
  free(blob);
  if(!queued)return "COULD NOT QUEUE SERVER CROWN RECORD";
  *submitted=1;
  GC.crown_refresh_after=0;
  GC.crown_ready=0;
  app_cloud_invalidate_directory();
  return "SERVER CROWN UPDATE QUEUED";
}

static void app_attract_crown_snapshot(menu_state *m,int configured) {
  int status=configured ? (GC.crown_ready?MENU_ATTRACT_CROWN_ONLINE:MENU_ATTRACT_CROWN_PENDING) :
                         MENU_ATTRACT_CROWN_LOCAL;
  /* Only the online authority may populate the online board. An empty or
   * failed response cannot expose old local holders under a server label. */
  if (status==m->attract_crown_status &&
      (status!=MENU_ATTRACT_CROWN_ONLINE || m->attract_crown_generation==GC.crown_generation)) return;
  m->attract_crown_status=status;
  m->attract_crown_generation=GC.crown_generation;
  m->attract_crown_occupied=0;
  memset(m->attract_crowns,0,sizeof m->attract_crowns);
  if (status==MENU_ATTRACT_CROWN_ONLINE) {
    m->attract_crown_occupied=GC.crown_occupied;
    for (unsigned i=0;i<GC.crowns.count;++i) {
      const app_cloud_row *row=&GC.crowns.rows[i];
      menu_attract_crown *holder=&m->attract_crowns[row->area];
      if (menu_ghost_name_glyphs(holder->glyphs,row->record.name))
        holder->car=app_profile_area(&row->record,&row->binding);
    }
  } else if (status==MENU_ATTRACT_CROWN_LOCAL) {
    const char *root=app_crown_root(),*physics=car_ghost_physics_id();
    if (!root || !physics) return;
    for (unsigned area=0;area<GHOST_CROWN_AREAS;++area) {
      ghost_crown_record record={0};
      car_ghost_arcade_binding binding;
      if (!app_crown_load_bound(root,physics,area,&record,&binding)) continue;
      menu_attract_crown *holder=&m->attract_crowns[area];
      if (menu_ghost_name_glyphs(holder->glyphs,record.name))
        holder->car=app_profile_area(&record,&binding);
      ghost_crown_free(&record);
    }
  }
}

static void app_cloud_menu(void) {
  menu_state *m=&G.menu;
  if(AG.prepared || AG.active || m->ghost.active_request)return;
  int ghost=m->screen==MENU_GHOST;
  int page=m->ghost.ui.page;
  // Applying a new directory invalidates row indices. Wait until the player
  // leaves an active rival list or completes the current selection animation.
  if(ghost && (page==GHOST_UI_RIVAL || page==GHOST_UI_RESULT || m->ghost.ui.commit || m->ghost.touch))return;
  if(!ghost || page==GHOST_UI_SEARCH || m->ghost.search_kind!=3)
    app_cloud_select_snapshot(0);
  int configured=android_ghost_cloud_configured();
  int attract=menu_in_attract(m);
  app_cloud_crown_tick(configured,attract || ghost || m->screen==MENU_CARD);
  if(attract) app_attract_crown_snapshot(m,configured);
  else m->attract_crown_status=MENU_ATTRACT_CROWN_IDLE;
  if(!configured && (GC.discovery.count || GC.matches.count)) {
    app_cloud_free(&GC.discovery);
    app_cloud_free(&GC.matches);
    app_cloud_invalidate_directory();
    GC.refresh_after=0;
  }
  uint16_t name[5]={0};
  unsigned n=menu_ghost_search_query(m,name);
  if(GC.wait) {
    unsigned char *packet=NULL;
    size_t length=0;
    int reply=android_ghost_cloud_poll(&packet,&length);
    if(!reply && configured && now_ms()<GC.request_deadline)return;
    if(!reply)reply=-1;
    if(GC.search_count) {
      if(n==GC.search_count && !memcmp(name,GC.search,n*sizeof *name)) {
        GC.search_ready=reply>0 && app_cloud_unpack(&GC.matches,packet,length,0)?1:-1;
        app_cloud_select_snapshot(GC.search_ready>0);
      }
    } else if(reply>0) {
      (void)app_cloud_unpack(&GC.discovery,packet,length,0);
    }
    free(packet);
    GC.wait=GC.search_count=0;
  }
  if(n && GC.search_ready)return;
  if(!n)GC.search_ready=0;
  const char *physics=car_ghost_physics_id();
  if(n) {
    if(physics && android_ghost_cloud_search(physics,name,n)) {
      memcpy(GC.search,name,n*sizeof *name);GC.search_count=n;GC.wait=1;
      GC.request_deadline=now_ms()+30000.0;
    } else GC.search_ready=-1;
  } else if(physics && configured && now_ms()>=GC.refresh_after) {
    GC.wait=android_ghost_cloud_refresh(physics);
    GC.refresh_after=now_ms()+(GC.wait?30000.0:1500.0);
    GC.request_deadline=GC.refresh_after;
  }
}

static void app_cloud_directory(void) {
  const app_cloud_snapshot *snapshot=app_cloud_visible();
  for(unsigned i=0;i<snapshot->count;++i)
    app_profile_row(&snapshot->rows[i].record,snapshot->rows[i].area,i,MENU_GHOST_SOURCE_CLOUD,&snapshot->rows[i].binding);
}
static int app_cloud_requested(unsigned request) {
  unsigned index=G.menu.ghost.request_record_index;
  unsigned area=(unsigned)G.menu.ghost.request_area_slot;
  const app_cloud_snapshot *snapshot=app_cloud_visible();
  const ghost_crown_record *record=index<snapshot->count && snapshot->rows[index].area==area ?
    &snapshot->rows[index].record : NULL;
  return app_profile_requested(request,record,area,app_cloud_source(index),0);
}

static void app_replay_arm(void) {
  char key[33];
  if((app_crown_root() || android_ghost_cloud_configured()) && app_ghost_card_key(key) &&
     car_ghost_arm_cloud_recording(AG.token)) {
    AG.player_recording=1;
    AG.config.record_player=1;
  }
}
static int app_cloud_publish(const ghost_crown_record *record,unsigned area) {
  char key[33];
  if(!record || !android_ghost_cloud_configured() || !app_ghost_card_key(key))return 0;
  unsigned char *blob=NULL;
  size_t length=0;
  if(ghost_profile_pack(record,&blob,&length)!=GHOST_STORE_OK)return 0;
  int queued=android_ghost_cloud_enqueue_card(area,blob,length,key);
  free(blob);
  return queued;
}

static void app_cloud_report(int won,float gap) {
  char key[33];
  const app_cloud_snapshot *snapshot=app_cloud_visible();
  if(AG.arcade!=4 || AG.arcade_record>=snapshot->count || !app_ghost_card_key(key))return;
  menu_body_color_view player;
  if(!menu_body_color_get(&G.menu,&player))return;
  uint16_t name[5];
  unsigned n=app_ghost_card_name(name);
  unsigned hp=(unsigned)car_tune_hp(CARDB_CARS[G.menu.maker][G.menu.car].hp,AG.owner.power);
  int32_t ghost_gap=isfinite(gap) && fabsf(gap)<=1000000.0f?(int32_t)lroundf(-gap):INT32_MIN;
  (void)android_ghost_cloud_report(snapshot->rows[AG.arcade_record].id,won,(unsigned)player.raw_model,
                                   hp,ghost_gap,name,n);
}
