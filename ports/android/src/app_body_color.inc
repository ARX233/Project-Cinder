/* Player-only cosmetic state. Never writes car_spec, native memory, RNG or Ghost IDs.
 * ResourceRoot is the program's selected MAIN root; only its fixed, compile-pinned
 * WPPAINT1 member can grant pages. Old data without it retains original paint. */
static struct {
  player_paint_resource *resource;
  player_paint_reader *reader;
  /* Only the explicitly stamped visible player-car views, never all palettes.
   * Aero galleries show up to four bodies; the hard UI bound is twelve. */
  player_body_paint_cache preview[MENU_MAX_CARS], race;
  menu_body_color_view race_view;
  uint64_t generation;
  int attempted, race_frozen, draw_fault;
} BPC = { .generation = 1 };

static player_body_paint_identity app_body_identity(const menu_body_color_view *v) {
  return (player_body_paint_identity){
    .raw_model=(uint16_t)v->raw_model, .pack=(uint16_t)v->pack,
    .factory_paint=(uint16_t)v->paint, .custom_color=(uint8_t)v->custom_color,
    .aero=(uint8_t)v->aero, .vinyl=(uint8_t)v->vinyl,
    .bonnet=(uint8_t)v->bonnet, .context_generation=BPC.generation };
}
static void app_body_drop(int lost) {
  app_story_body_clear();
  for (int i=0;i<MENU_MAX_CARS;i++) (void)player_body_paint_clear(&BPC.preview[i],lost);
  (void)player_body_paint_clear(&BPC.race,lost);
  BPC.race_frozen=BPC.draw_fault=0;
}
static void app_body_evict_pack(int pack) {
  for (int i=0;i<MENU_MAX_CARS;i++)
    if (BPC.preview[i].prepared && BPC.preview[i].identity.pack==pack)
      (void)player_body_paint_clear(&BPC.preview[i],0);
  if (BPC.race.prepared && BPC.race.identity.pack==pack) {
    int invalid=BPC.race_frozen && BPC.race_view.custom_color;
    (void)player_body_paint_clear(&BPC.race,0);
    BPC.race_frozen=0;
    if (invalid) BPC.draw_fault=1;
  }
}
static void app_body_evict_scene(wpk_scene *scene) {
  for (int i=0;i<MENU_MAX_CARS;i++)
    if (BPC.preview[i].prepared && BPC.preview[i].selected.scene==scene)
      (void)player_body_paint_clear(&BPC.preview[i],0);
  if (BPC.race.prepared && BPC.race.selected.scene==scene) {
    int invalid=BPC.race_frozen && BPC.race_view.custom_color;
    (void)player_body_paint_clear(&BPC.race,0);
    BPC.race_frozen=0;
    if (invalid) BPC.draw_fault=1;
  }
}
static void app_body_reset(int lost) {
  app_body_drop(lost);
  player_paint_close(BPC.reader); BPC.reader=NULL;
  player_paint_resource_close(BPC.resource); BPC.resource=NULL;
  BPC.attempted=0;
  if (++BPC.generation==0) ++BPC.generation;
  menu_body_color_clear_pages(&G.menu);
}
void app_body_release_assets(int context_lost) { app_body_reset(context_lost!=0); }
static int app_body_open(void) {
  if (BPC.reader) return 1;
  if (BPC.attempted || !G.data_dir[0]) return 0;
  BPC.attempted=1;
  int fd=open(G.data_dir,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_NONBLOCK);
  if (fd<0) return 0;
  ghost_asset_source source;
  int ok=player_paint_resource_open_main(fd,&BPC.resource);
  close(fd);
  if (ok) ok=player_paint_resource_source(BPC.resource,&source) &&
              player_paint_open(&source,&BPC.reader)==PLAYER_PAINT_OK;
  if (!ok) {
    player_paint_resource_close(BPC.resource); BPC.resource=NULL;
    fprintf(stderr,"Original body colours unavailable: select a fresh original-resource conversion; old data preserved.\n");
  }
  return ok;
}
static wpk_scene *app_body_scene(const menu_body_color_view *v) {
  if (v->pack<0 || v->pack>=NPACKS || v->aero<0 || v->aero>3 || G.seen.pack[v->pack]!=1) return NULL;
  wpk_scene *stock=car_pack(v->pack), *scene=stock;
  if (!stock || stock==&G.fd3s) return NULL; /* not the missing-car substitute */
  if (v->aero) {
    menu_aero_want(v->pack,v->aero);
    scene=menu_aero(v->pack,v->aero);
    if (!scene) return NULL;
  }
  car_paint_for_draw(stock,v->aero?scene:NULL,v->paint);
  return scene;
}
static int app_body_prepare(player_body_paint_cache *cache,
                            const menu_body_color_view *v,wpk_scene *scene) {
  if (!v->custom_color) return 1;
  if (!scene || !app_body_open()) return 0;
  player_body_paint_identity id=app_body_identity(v);
  if (player_body_paint_ready(cache,id,scene)) return 1;
  player_paint_overlay overlay={0}; unsigned char *owned=NULL;
  if (v->vinyl) {
    ghost_paint_overlay source={0};
    if (!app_arcade_vinyl_read(v->pack,v->aero,v->paint,v->vinyl,v->bonnet,&source,&owned)) return 0;
    /* Explicit field copy: do not type-pun two independent resource contracts. */
    overlay.pixels=source.pixels; overlay.bytes=source.bytes;
    overlay.width=source.width; overlay.height=source.height;
    memcpy(overlay.material,source.material,sizeof overlay.material);
    overlay.rgb_mask=source.rgb_mask; memcpy(overlay.color,source.color,4);
    overlay.vinyl=source.vinyl; overlay.carbon_bonnet=source.carbon_bonnet;
    memcpy(overlay.sha256,source.sha256,32);
  }
  int ok=player_body_paint_prepare(cache,BPC.reader,id,scene,v->vinyl?&overlay:NULL);
  free(owned);
  return ok;
}
/* Fixed menu/loading pass only. No decode/upload or I/O in a draw callback. */
static int app_body_menu_prepare(const menu_scene *shown) {
  menu_body_color_view selected;
  if (menu_body_color_get(&G.menu,&selected)) {
    wpk_scene *scene=app_body_scene(&selected);
    unsigned mask=1; /* original paint remains usable even in an old dataset */
    if (scene && app_body_open()) {
      player_body_paint_identity id=app_body_identity(&selected);
      id.custom_color=0;
      mask|=(unsigned)player_body_paint_available_mask(BPC.reader,id,scene)<<1;
    }
    menu_body_color_set_pages(&G.menu,selected.raw_model,mask);
  }
  int ready=1;
  for (int i=0;i<MENU_MAX_CARS;i++) {
    const menu_car *car=shown && i<shown->n ? &shown->cars[i] : NULL;
    if (!car || !car->body_color_valid || !car->body_color.custom_color) {
      /* With no 3D title scene, slot0 can own the committed start prewarm. */
      if (car || i || (shown && shown->n)) (void)player_body_paint_clear(&BPC.preview[i],0);
      continue;
    }
    wpk_scene *scene=app_body_scene(&car->body_color);
    if (!app_body_prepare(&BPC.preview[i],&car->body_color,scene)) ready=0;
  }
  return ready;
}
static int app_body_start_ready(void) {
  menu_body_color_view v;
  if (!menu_body_color_get(&G.menu,&v)) return 0;
  return !v.custom_color || app_body_prepare(&BPC.preview[0],&v,app_body_scene(&v));
}
static int app_body_race_prepare(void) {
  menu_body_color_view v;
  if (!menu_body_color_get(&G.menu,&v)) return 0;
  wpk_scene *scene=G.aero_set?&G.aero:G.race_model;
  if (v.custom_color && v.aero!=G.aero_set) return 0; /* no silent missing-aero fallback */
  v.aero=G.aero_set; /* exact draw body, not the previous preview's borrowed scene */
  if (!app_body_prepare(&BPC.race,&v,scene)) return 0;
  BPC.race_view=v; BPC.race_frozen=1; BPC.draw_fault=0;
  for (int i=0;i<MENU_MAX_CARS;i++) (void)player_body_paint_clear(&BPC.preview[i],0);
  return 1;
}
static int app_body_menu_apply(const menu_car *car,wpk_scene *scene,app_player_paint_scope *scope) {
  memset(scope,0,sizeof *scope);
  if (!car->body_color_valid || !car->body_color.custom_color) return 1;
  player_body_paint_identity id=app_body_identity(&car->body_color);
  for (int i=0;i<MENU_MAX_CARS;i++)
    if (player_body_paint_ready(&BPC.preview[i],id,scene))
      return player_body_paint_apply(&BPC.preview[i],id,scene,scope);
  return 0;
}
/* Port diagnostic, not reconstructed arcade art. Old data stays untouched and
 * receives an actionable visible message instead of an unexplained empty palette. */
static void app_body_notice(void) {
  if (!BPC.attempted || BPC.reader) return;
  menu_body_color_view v;
  if (G.menu.screen!=MENU_BODY_COLOR && (!menu_body_color_get(&G.menu,&v) || !v.custom_color)) return;
  const char *a="ORIGINAL BODY COLOUR DATA UPDATE REQUIRED";
  const char *b="RECONVERT ORIGINAL DATA - SAVES AND OLD DATA ARE KEPT";
  float w=G.hud.screen_w,h=G.hud.screen_h,p=fminf(w/330.0f,h/160.0f);
  hud_ui_begin(w,h);
  hud_ui_rect(0,h-26*p,w,26*p,0,0,0,0.85f);
  hud_ui_text(a,(w-hud_ui_text_width(a,p))*0.5f,h-23*p,p,1,0.85f,0.4f,1);
  hud_ui_text(b,(w-hud_ui_text_width(b,p))*0.5f,h-11*p,p,1,1,1,1);
  hud_ui_end();
}
static int app_body_race_apply(wpk_scene *scene,app_player_paint_scope *scope) {
  memset(scope,0,sizeof *scope);
  if (!BPC.race_frozen) return 0;
  if (!BPC.race_view.custom_color) return 1;
  int ok=player_body_paint_apply(&BPC.race,app_body_identity(&BPC.race_view),scene,scope);
  if (!ok) BPC.draw_fault=1;
  return ok;
}
