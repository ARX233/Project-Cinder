/* A selected opponent's real original materials, prepared only on current game
 * context, never decoded/uploaded in draw. The catalogue owns reader callbacks. */
static struct {ghost_paint_reader*reader;app_ghost_paint_cache cache;uint64_t context_generation,session_token;int draw_fault;} ACP={.context_generation=1};
#include "app_ghost_vinyl.inc"

/* The rival spin box shows up to six actual models during a slide. Preview
 * cache entries belong to those visible materials, never the player's paint. */
static int app_arcade_paint_apply(wpk_scene *scene,app_ghost_paint_scope *scope,app_player_paint_scope *local_scope);
static app_ghost_paint_cache ghost_preview_paint[6];
static int ghost_preview_base_paint[6];
/* A locally saved champion uses the verified MAIN paint pages it raced with.
 * Own caches keep its draw independent from the player's current appearance. */
static player_body_paint_cache local_crown_preview_paint,local_crown_race_paint;

static int app_ghost_preview_is_local(const menu_car *car) {
 if (car->ghost_row<0) return 1; /* standby profiles carry the MAIN paint identity */
 unsigned kind=G.menu.ghost.directory.rows[car->ghost_row-1].source_kind;
 return kind==MENU_GHOST_SOURCE_LOCAL_CROWN || kind==MENU_GHOST_SOURCE_CLOUD;
}

static menu_body_color_view app_ghost_local_preview_view(const menu_ghost_directory_area *area) {
 return (menu_body_color_view){.raw_model=(int)area->raw_model,.pack=area->pack,.paint=area->base_paint,
  .custom_color=area->custom_color,.aero=area->aero,.vinyl=area->vinyl,.bonnet=area->bonnet};
}

static ghost_paint_key app_ghost_preview_key(const menu_car *car,const menu_ghost_directory_area *area) {
 return (ghost_paint_key){(uint16_t)car->pack,(uint8_t)area->custom_color,(uint8_t)car->aero};
}

static wpk_scene *app_ghost_preview_stock(const menu_car *car) {
 if (car->pack<0 || car->pack>=NPACKS || G.seen.pack[car->pack]!=1 ||
     !paint_ready(car->pack,car->paint)) return NULL;
 return car_pack(car->pack);
}

static wpk_scene *app_ghost_preview_model(const menu_car *car) {
 wpk_scene *stock=app_ghost_preview_stock(car);
 if (!stock) return NULL;
 return car->aero ? menu_aero(car->pack,car->aero) : stock;
}

static app_ghost_paint_cache *app_ghost_preview_cache(const menu_car *car,const menu_ghost_directory_area *area,
                                                    wpk_scene *scene) {
 for (unsigned i=0;i<sizeof ghost_preview_paint/sizeof *ghost_preview_paint;++i) {
  app_ghost_paint_cache *cache=&ghost_preview_paint[i];
  if (ghost_preview_base_paint[i]==car->paint && app_ghost_paint_ready(cache,app_ghost_preview_key(car,area),ACP.context_generation,scene,car->vinyl,car->bonnet))
   return cache;
 }
 return NULL;
}

static void app_ghost_preview_prepare(const menu_scene *shown) {
 /* The matchup uses the frozen rival material already prepared for the race. */
 if (menu_ghost_preparing(&G.menu)) shown=NULL;
 unsigned keep=0;
 int local_visible=0;
 for (int i=0;shown&&i<shown->n;++i) {
  const menu_car *car=&shown->cars[i];
  if (!car->ghost_row) continue;
  const menu_ghost_directory_area *area=menu_ghost_preview_profile(&G.menu,car->ghost_row);
  wpk_scene *scene=app_ghost_preview_model(car);
  if (!area || !scene || !area->custom_color) continue;
  if (app_ghost_preview_is_local(car)) {
   menu_body_color_view v=app_ghost_local_preview_view(area);
   car_paint_for_draw(car_pack(car->pack),car->aero?scene:NULL,car->paint);
   app_body_prepare(&local_crown_preview_paint,&v,scene);
   local_visible=1;
   continue;
  }
  app_ghost_paint_cache *cache=app_ghost_preview_cache(car,area,scene);
  if (cache) keep|=1u<<(cache-ghost_preview_paint);
 }
 if (!local_visible) player_body_paint_clear(&local_crown_preview_paint,0);
 for (unsigned i=0;i<sizeof ghost_preview_paint/sizeof *ghost_preview_paint;++i)
  if (!(keep&(1u<<i)) && ghost_preview_paint[i].prepared) app_ghost_paint_clear(&ghost_preview_paint[i],0);
 if (!ACP.reader) return;
 for (int i=0;shown&&i<shown->n;++i) {
  const menu_car *car=&shown->cars[i];
  if (!car->ghost_row) continue;
  const menu_ghost_directory_area *area=menu_ghost_preview_profile(&G.menu,car->ghost_row);
  if (!area || !area->custom_color || app_ghost_preview_is_local(car)) continue;
  wpk_scene *scene=app_ghost_preview_model(car);
  if (!scene || app_ghost_preview_cache(car,area,scene)) continue;
  const ghost_paint_page *pages;
  size_t count;
  ghost_paint_key key=app_ghost_preview_key(car,area);
  if (ghost_paint_lookup(ACP.reader,key,&pages,&count)!=GHOST_PAINT_OK) continue;
  ghost_paint_overlay overlay;unsigned char *owned=NULL;
  if (car->vinyl&&!app_arcade_vinyl_read(car->pack,car->aero,car->paint,car->vinyl,car->bonnet,&overlay,&owned))
   continue;
  int uploaded=0;
  for (unsigned j=0;j<sizeof ghost_preview_paint/sizeof *ghost_preview_paint;++j) {
   if (keep&(1u<<j)) continue;
   car_paint_for_draw(car_pack(car->pack),car->aero?scene:NULL,car->paint);
   uploaded=app_ghost_paint_want(&ghost_preview_paint[j],ACP.reader,key,ACP.context_generation,
                                scene,car->vinyl,car->bonnet,car->vinyl?&overlay:NULL);
   if (uploaded) ghost_preview_base_paint[j]=car->paint;
   break;
  }
  free(owned);
  if (uploaded) return;
 }
}

static int app_ghost_preview_apply(const menu_car *car,wpk_scene *scene,story_body_view *body,
                                   app_ghost_paint_scope *scope,app_player_paint_scope *local_scope) {
 const menu_ghost_directory_area *area=menu_ghost_preview_profile(&G.menu,car->ghost_row);
 if (!area || !story_body_view_capture_model(body,area->pack,(int)area->raw_model,area->native_type,
                                            area->power,area->handling,0)) return 0;
 if (!area->custom_color) return 1;
 if (menu_ghost_preparing(&G.menu)) return app_arcade_paint_apply(scene,scope,local_scope);
 if (app_ghost_preview_is_local(car)) {
  menu_body_color_view v=app_ghost_local_preview_view(area);
  player_body_paint_apply(&local_crown_preview_paint,app_body_identity(&v),scene,local_scope);
  return 1;
 }
 app_ghost_paint_cache *cache=app_ghost_preview_cache(car,area,scene);
 if (cache) app_ghost_paint_apply(cache,app_ghost_preview_key(car,area),ACP.context_generation,
                                 scene,car->vinyl,car->bonnet,scope);
 return 1;
}
static ghost_paint_key app_arcade_paint_key(void){
 return (ghost_paint_key){(uint16_t)AG.arcade_binding.pack,(uint8_t)AG.arcade_binding.custom_color,(uint8_t)AG.arcade_style.aero_};
}
static menu_body_color_view app_ghost_local_race_view(void) {
 return (menu_body_color_view){.raw_model=(int)AG.arcade_style.car_,.pack=AG.arcade_binding.pack,
  .paint=AG.arcade_binding.base_paint,.custom_color=AG.arcade_binding.custom_color,
  .aero=(int)AG.arcade_style.aero_,.vinyl=(int)AG.arcade_style.vinyl_,.bonnet=(int)AG.arcade_style.bonnet_};
}
static void app_arcade_paint_drop(int lost){
 (void)app_ghost_paint_clear(&ACP.cache,lost);ACP.session_token=0;ACP.draw_fault=0;
 player_body_paint_clear(&local_crown_race_paint,lost);
}
static void app_arcade_paint_close(int lost){
 app_arcade_paint_drop(lost);
 for (unsigned i=0;i<sizeof ghost_preview_paint/sizeof *ghost_preview_paint;++i)
  app_ghost_paint_clear(&ghost_preview_paint[i],lost);
 player_body_paint_clear(&local_crown_preview_paint,lost);
 ghost_paint_close(ACP.reader);ACP.reader=NULL;
}
static int app_arcade_paint_open(void){
 ghost_asset_source source;
 return AC.catalog && ghost_catalog_paint_source(AC.catalog,&source)==GHOST_CATALOG_OK &&
        ghost_paint_open(&source,&ACP.reader)==GHOST_PAINT_OK;
}
static int app_arcade_appearance_ready(void){
 if(!AG.arcade)return 1;
 if(!AG.prepared&&!AG.active)return 0;
 int pack=AG.rival_pack,aero_id=(int)AG.arcade_style.aero_;
 if(pack<0||pack>=NPACKS||G.seen.pack[pack]!=1||!paint_ready(pack,AG.rival_paint)||aero_id<0||aero_id>3)return 0;
 wpk_scene*stock=car_pack(pack),*aero=NULL,*scene=stock;if(!stock||stock==&G.fd3s)return 0;
 if(aero_id){menu_aero_want(pack,aero_id);aero=menu_aero(pack,aero_id);if(!aero)return 0;scene=aero;}
 vs_dress_t d;
 app_ghost_arcade_apply_dress(&d);
 if (d.wheel && !wheel_model(d.wheel)) {
  int slot = wheel_find(d.wheel);
  /* Existing verified packs predate this model. The stock rim is only a
   * visual fallback; the rival identity, tyres and route stay bound. */
  if (d.wheel != MENU_WHEEL_LEMANS || slot < 0 || G.wheel_state[slot] != WHEEL_MISSING) return 0;
 }
 car_paint_for_draw(stock,aero,AG.rival_paint);
 if(!AG.arcade_binding.custom_color){
  if(d.vinyl){const char*page=NULL;uint32_t texture=vinyl_tex(pack,aero_id,AG.rival_paint,d.vinyl,d.bonnet,&page);
   if(!texture||!page||wpk_find_texture(scene,page)<0)return 0;}
  return 1;
 }
 if(AG.arcade==3 || AG.arcade==4){
  menu_body_color_view v=app_ghost_local_race_view();
  if(ACP.session_token!=AG.token)app_arcade_paint_drop(0);
  int ok=app_body_prepare(&local_crown_race_paint,&v,scene);
  if(ok)ACP.session_token=AG.token;
  return ok;
 }
 if(!ACP.reader)return 0;
 ghost_paint_key key=app_arcade_paint_key();
 if(ACP.session_token==AG.token&&app_ghost_paint_ready(&ACP.cache,key,ACP.context_generation,scene,AG.arcade_style.vinyl_,AG.arcade_style.bonnet_))return 1;
 if(ACP.session_token!=AG.token)app_arcade_paint_drop(0);
 ghost_paint_overlay overlay;unsigned char*owned=NULL;
 if(d.vinyl&&!app_arcade_vinyl_read(pack,aero_id,AG.rival_paint,d.vinyl,d.bonnet,&overlay,&owned))return 0;
 int ok=app_ghost_paint_want(&ACP.cache,ACP.reader,key,ACP.context_generation,scene,AG.arcade_style.vinyl_,AG.arcade_style.bonnet_,d.vinyl?&overlay:NULL);
 free(owned);if(ok)ACP.session_token=AG.token;return ok;
}
static int app_arcade_paint_apply(wpk_scene*scene,app_ghost_paint_scope*scope,app_player_paint_scope*local_scope){
 if(ACP.session_token==AG.token){
  if(AG.arcade==3 || AG.arcade==4){
   menu_body_color_view v=app_ghost_local_race_view();
   if(player_body_paint_apply(&local_crown_race_paint,app_body_identity(&v),scene,local_scope))return 1;
  }else if(app_ghost_paint_apply(&ACP.cache,app_arcade_paint_key(),ACP.context_generation,scene,
      AG.arcade_style.vinyl_,AG.arcade_style.bonnet_,scope))return 1;
 }
 ACP.draw_fault=1;
 return 0;
}
static void app_ghost_context_reset(void){
 app_ghost_release_assets(1);if(++ACP.context_generation==0)++ACP.context_generation;
}
static int app_ghost_arcade_aero(int*pack,int*set){
 if(!pack||!set||!AG.arcade||(!AG.prepared&&!AG.active)||!AG.arcade_style.aero_)return 0;
 *pack=AG.rival_pack;*set=(int)AG.arcade_style.aero_;return *pack>=0&&*set>=1&&*set<=3;
}
