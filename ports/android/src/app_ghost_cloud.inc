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
#endif

typedef struct {
  ghost_crown_record record;
  car_ghost_arcade_binding binding;
  unsigned area;
  unsigned char id[16];
} app_cloud_row;

static struct {
  unsigned count,wait,search_count;
  int search_ready;
  double refresh_after,request_deadline;
  uint16_t search[5];
  app_cloud_row rows[MENU_GHOST_CLOUD_RECORDS];
} GC;

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
static void app_cloud_close(void) {
  for (unsigned i=0;i<GC.count;++i) ghost_crown_free(&GC.rows[i].record);
  memset(&GC,0,sizeof GC);
}

static int app_cloud_unpack(unsigned char *packet,size_t length) {
  enum { ROW_BYTES=21 };
  if(!length || packet[0]>MENU_GHOST_CLOUD_RECORDS)return 0;
  unsigned count=packet[0];
  size_t at=1;
  for(unsigned i=0;i<count;++i) {
    if(length-at<ROW_BYTES)return 0;
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
    if(area<GHOST_CROWN_AREAS &&
       ghost_profile_unpack(packet+at,bytes,car_ghost_physics_id(),&row->record)==GHOST_STORE_OK &&
       menu_ghost_name_glyphs(glyph,row->record.name) &&
       app_profile_bind(&row->record,area,1,app_cloud_source(accepted),0,&spec,&row->binding) &&
       car_ghost_arcade_validate_trail(&row->binding,row->record.race.trail,row->record.race.trail_bytes)) {
      row->area=area;memcpy(row->id,id,sizeof row->id);++accepted;
    } else ghost_crown_free(&row->record);
    at+=bytes;
  }
  int changed=accepted!=GC.count;
  for(unsigned i=0;!changed && i<accepted;++i)
    changed=memcmp(rows[i].id,GC.rows[i].id,sizeof rows[i].id)!=0;
  if(changed) {
    for(unsigned i=0;i<GC.count;++i)ghost_crown_free(&GC.rows[i].record);
    memcpy(GC.rows,rows,sizeof rows);GC.count=accepted;
    AC.published=0;
    if(++AC.epoch==0)++AC.epoch;
  } else for(unsigned i=0;i<accepted;++i)ghost_crown_free(&rows[i].record);
  return 1;
}

static void app_cloud_menu(void) {
  menu_state *m=&G.menu;
  if(m->screen!=MENU_GHOST || AG.prepared || AG.active || m->ghost.active_request)return;
  uint16_t name[5]={0};
  unsigned n=menu_ghost_search_query(m,name);
  int page=m->ghost.ui.page;
  int browsing=(page==GHOST_UI_SEARCH || page==GHOST_UI_LEVEL ||
                (page==GHOST_UI_COURSE && m->ghost.search_kind==0)) &&
               !m->ghost.ui.commit && !m->ghost.touch;
  if(GC.wait) {
    unsigned char *packet=NULL;
    size_t length=0;
    int reply=android_ghost_cloud_poll(&packet,&length);
    if(!reply && android_ghost_cloud_configured() && now_ms()<GC.request_deadline)return;
    if(!reply)reply=-1;
    if(GC.search_count) {
      if(n==GC.search_count && !memcmp(name,GC.search,n*sizeof *name))
        GC.search_ready=reply>0 && app_cloud_unpack(packet,length)?1:-1;
      GC.refresh_after=0;
    } else if(browsing && reply>0) (void)app_cloud_unpack(packet,length);
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
  } else if(browsing && physics && android_ghost_cloud_configured() && now_ms()>=GC.refresh_after) {
    GC.wait=android_ghost_cloud_refresh(physics);
    GC.refresh_after=now_ms()+(GC.wait?30000.0:1500.0);
    GC.request_deadline=GC.refresh_after;
  }
}

static void app_cloud_directory(void) {
  for(unsigned i=0;i<GC.count;++i)
    app_profile_row(&GC.rows[i].record,GC.rows[i].area,i,MENU_GHOST_SOURCE_CLOUD,&GC.rows[i].binding);
}
static int app_cloud_requested(unsigned request) {
  unsigned index=G.menu.ghost.request_record_index;
  unsigned area=(unsigned)G.menu.ghost.request_area_slot;
  const ghost_crown_record *record=index<GC.count && GC.rows[index].area==area ? &GC.rows[index].record : NULL;
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
  if(AG.arcade!=4 || AG.arcade_record>=GC.count || !app_ghost_card_key(key))return;
  menu_body_color_view player;
  if(!menu_body_color_get(&G.menu,&player))return;
  uint16_t name[5];
  unsigned n=app_ghost_card_name(name);
  unsigned hp=(unsigned)car_tune_hp(CARDB_CARS[G.menu.maker][G.menu.car].hp,AG.owner.power);
  int32_t ghost_gap=isfinite(gap) && fabsf(gap)<=1000000.0f?(int32_t)lroundf(-gap):INT32_MIN;
  (void)android_ghost_cloud_report(GC.rows[AG.arcade_record].id,won,(unsigned)player.raw_model,
                                   hp,ghost_gap,name,n);
}
