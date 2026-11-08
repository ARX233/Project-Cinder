/* A distinct original compiled-default target-AI source. Never an archived
 * trail fallback. Metadata enumeration never selects a random course. */
static unsigned app_default_directory_fill(unsigned first){
 unsigned count=first;if(!car_ghost_default_available())return count;
 for(unsigned i=0;i<CAR_GHOST_DEFAULT_RECORDS;i++){
  car_ghost_default_view v;if(!car_ghost_default_record(i,&v)||!v.manager_eligible)continue;
  int names_ok=1;for(unsigned j=0;j<5;j++)if(v.name[j]>UINT16_MAX)names_ok=0;
  if(!names_ok||count>=GHOST_CATALOG_RECORDS+CAR_GHOST_DEFAULT_RECORDS){AC.failed_profiles++;continue;}
  menu_ghost_directory_row*r=&AC.rows[count++];memset(r,0,sizeof *r);
  r->source_kind=MENU_GHOST_SOURCE_DEFAULT;r->record_index=i;r->id_devel=v.id_devel;r->id1=v.id1;r->id2=v.id2;
  for(unsigned j=0;j<5;j++)r->name[j]=(uint16_t)v.name[j];
  for(unsigned a=0;a<8;a++){
   menu_ghost_directory_area*d=&r->areas[a];d->level=v.car.target_level;d->native_available=1;
   d->default_crown=v.crown_area==(int)a;
   d->ramp=d->route=-1; /* Original random ramp/route ONLY at actual confirm. */
   d->pack=v.car.pack;d->paint=v.car.paint;d->raw_model=v.raw_model_id;d->power=v.car.rival.power;d->handling=v.car.rival.handling;d->title=v.title;
   d->native_type=(int)v.car.rival.type;d->base_paint=v.car.base_paint;d->custom_color=v.car.custom_color;
   d->aero=(int)v.raw_aero;d->mirror=(int)v.raw_mirror;
   d->wing=(int)v.raw_wing;d->bonnet=(int)v.raw_bonnet;
   d->wheel=v.raw_wheel==143u?0:(int)v.raw_wheel+1;
   d->neon=(int)v.raw_neon;d->vinyl=(int)v.raw_vinyl;
  }
 }
 return count;
}
static const menu_ghost_directory_row*app_default_directory_row(unsigned index){
 for(unsigned i=GHOST_CATALOG_RECORDS;i<AC.row_count;i++)if(AC.rows[i].source_kind==MENU_GHOST_SOURCE_DEFAULT&&AC.rows[i].record_index==index)return &AC.rows[i];
 return NULL;
}
static void app_default_style(const car_ghost_default_binding*b,ghost_catalog_area*a){
 memset(a,0,sizeof *a);const car_ghost_default_view*v=&b->record;
 a->car_=v->raw_model_id;a->custom_color_=v->raw_custom_color;a->vinyl_=v->raw_vinyl;a->bonnet_=v->raw_bonnet;a->wing_=v->raw_wing;
 a->aero_=v->raw_aero;a->aero_mirror_=v->raw_mirror;a->wheel_=v->raw_wheel;a->neon_=v->raw_neon;
 a->dress_=v->dress;a->dress_x_=v->dress_x;a->player_win_count_=v->player_win_count;a->title_=v->title;a->class_=v->class_id;
 a->odo_count_=v->odo_count;a->cool_wild_=v->cool_wild;a->smooth_rough_=v->smooth_rough;
 a->tune_power_=(uint32_t)b->car.rival.power;a->tune_handling_=(uint32_t)b->car.rival.handling;
 a->ramp_=(uint32_t)b->car.raw_ramp;a->route_=(uint32_t)b->car.raw_route;a->crown_=v->crown_area==(int)b->area;
}
static int app_default_requested(unsigned request){
 menu_state*m=&G.menu;unsigned index=m->ghost.request_record_index;int area=m->ghost.request_area_slot;
 const menu_ghost_directory_row*r=app_default_directory_row(index);car_ghost_default_view v;
 if(!AC.published||!request||!r||area<0||area>=8||m->ghost.request_source_kind!=MENU_GHOST_SOURCE_DEFAULT||
    m->ghost.request_catalog_epoch!=AC.epoch||!r->areas[area].native_available||!car_ghost_default_available()||
    !car_ghost_default_record(index,&v)||!v.manager_eligible||m->ghost.request_id_devel!=v.id_devel||m->ghost.request_id1!=v.id1||m->ghost.request_id2!=v.id2){
  (void)menu_ghost_complete(m,request,0,"ORIGINAL DEFAULT SELECTION EXPIRED");return 0;
 }
 app_ghost_clear();if(++AG.serial==0||AG.serial==UINT64_MAX)AG.serial=1;
 car_ghost_default_spec spec={.index=index,.area=(unsigned)area,.session_token=AG.serial,.first_tutorial=0};car_ghost_default_binding b;
 /* This is the sole original random ramp/route call for this confirmation. */
 if(!car_ghost_default_select(&spec,&b)||!menu_ghost_bind_default_request(m,(uint64_t)request,b.car.ramp,b.car.raw_route)||!car_ghost_default_prepare(&b)){
  car_ghost_clear();(void)menu_ghost_complete(m,request,0,"ORIGINAL DEFAULT NATIVE PREPARATION FAILED");return 0;
 }
 if(!menu_ghost_complete(m,request,1,"ORIGINAL DEFAULT PREPARED")||!menu_ghost_begin_pre(m)){app_ghost_clear();return 0;}
 memset(&AG.config,0,sizeof AG.config);AG.config.abi_version=CAR_GHOST_ABI_VERSION;AG.config.session_token=AG.serial;AG.config.kind=CAR_GHOST_DEFAULT;AG.config.rival=b.car.rival;
 memcpy(AG.config.race_field,b.car.race_field,sizeof AG.config.race_field);
 AG.token=AG.serial;AG.request=request;AG.arcade=2;AG.arcade_record=index;AG.arcade_area=area;AG.arcade_epoch=AC.epoch;
 AG.default_binding=b;AG.arcade_binding=b.car;app_default_style(&b,&AG.arcade_style);
 AG.ramp=b.car.ramp;AG.route=b.car.raw_route;AG.course=b.car.render_course;AG.prepared=1;
 (void)menu_ghost_name_glyphs(AG.rival_name,r->name);
 AG.maker=m->maker;AG.car=m->car;AG.color=m->color;AG.manual=m->manual;AG.rival_pack=b.car.pack;AG.rival_paint=b.car.base_paint;
 AG.arcade_card_slot=m->save_slot;AG.arcade_card_born=0;
 if(m->own_sel>=0&&m->own_sel<m->n_own&&m->own[m->own_sel].maker==m->maker&&m->own[m->own_sel].car==m->car)AG.arcade_card_born=m->own[m->own_sel].born;
 m->course=AG.course;m->story_sel=-1;m->finish=m->finish_story=0;return 1;
}
