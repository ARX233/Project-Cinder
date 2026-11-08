/* Intentional original compiled-default target-AI. Never used for recorded data. */
#include "ghost_default_frontend.inc"
#include "ghost_default_data.inc"
__attribute__((weak)) const volatile uint32_t rc_ghost_default_native_bridge = 0;
int car_ghost_default_available(void) {
  return rc_ghost_default_native_bridge == 0x47444431u && car_ghost_physics_id() &&
         f_849bdd4 && f_849bfec && f_849c788 && f_84d94a0 && f_89fb210;
}
static struct { int pending, active, tire_hook_calls, tire_hook_valid; car_ghost_default_binding binding; } ghost_default;
static uint64_t ghost_default_choice_epoch; /* monotonic even across clear */

static int ghost_default_engine(void) {
  return f_849bdd4 && f_849bfec && f_849c788 && f_84d94a0 && f_89fb210 && car_ghost_physics_id() && ghost_image();
}
int car_ghost_default_record(uint32_t index, car_ghost_default_view *view) {
  if(view)memset(view,0,sizeof *view);
  if(!view || index>=120u || !ghost_default_engine())return 0;
  /* Exact MOV-initialized bss data. No initializer execution, allocation or RNG. */
  memcpy(VA(0x97f7ec0u),GHOST_DEFAULT_ROWS,sizeof GHOST_DEFAULT_ROWS);
  const uint32_t *row=GHOST_DEFAULT_ROWS[index];
  uint32_t style=RC_STACK_TOP-0x400u,self=style-4u;W32(self,index);memset(VA(style),0,32);
  call(f_857f5c8,2,style,self);
  car_ghost_default_view out={0};out.index=index;out.manager_eligible=index==0u || memcmp(GHOST_DEFAULT_NAMES[index],GHOST_DEFAULT_NAMES[0],20)!=0;
  out.id_devel=1;out.id1=index;out.id2=row[0];memcpy(out.name,GHOST_DEFAULT_NAMES[index],20);
  out.raw_model_id=M32(style);out.raw_custom_color=M8(style+4);out.raw_vinyl=M8(style+5);
  out.raw_bonnet=M8(style+6);out.raw_wing=M8(style+7);out.raw_aero=M32(style+8);out.raw_mirror=M8(style+12);
  out.raw_wheel=M32(style+16);out.raw_neon=M8(style+26);out.dress=M16(style+24);out.dress_x=0;
  out.player_win_count=row[19];out.crown_area=(int)row[20];out.title=row[5];out.class_id=row[6];
  out.odo_count=row[21];out.cool_wild=row[22]&255u;out.smooth_rough=(row[22]>>8)&255u;
  int at=-1;
  for(unsigned i=0;i<sizeof GHOST_ARCADE_MODELS/sizeof *GHOST_ARCADE_MODELS;i++)if(GHOST_ARCADE_MODELS[i].model==out.raw_model_id){at=(int)i;break;}
  if(at<0 || out.raw_aero>3u || (out.raw_wheel!=143u&&out.raw_wheel>=113u))return 0;
  unsigned maker=GHOST_ARCADE_MODELS[at].maker,car=GHOST_ARCADE_MODELS[at].car,color_index=GHOST_ARCADE_MODELS[at].color;
  if(maker>=CARDB_ALL || car>=(unsigned)CARDB_NCARS[maker] || color_index>=(unsigned)CARDB_CARS[maker][car].ncolors)return 0;
  const cardb_color *color=&CARDB_CARS[maker][car].colors[color_index];
  if(color->swatch!=GHOST_ARCADE_MODELS[at].swatch||color->type!=GHOST_ARCADE_MODELS[at].type||color->gears!=GHOST_ARCADE_MODELS[at].gears||color->pack!=GHOST_ARCADE_MODELS[at].pack||color->paint!=GHOST_ARCADE_MODELS[at].paint||color->pack<0||color->pack>=CARDB_NPACKS||out.raw_custom_color>GHOST_ARCADE_PALETTES[color->pack].custom)return 0;
  car_ghost_arcade_binding *b=&out.car;b->rival.type=(unsigned)color->type;b->rival.gears=color->gears;
  b->rival.power=M8(style+21);b->rival.handling=M8(style+22);
  memcpy(b->rival.tyres,GHOST_ARCADE_TYRES[color->pack][out.raw_aero][out.raw_wheel!=143u],sizeof b->rival.tyres);
  b->rival.spokes=out.raw_wheel==143u?GHOST_ARCADE_STOCK_SPOKES[color->pack]:GHOST_ARCADE_WHEEL_SPOKES[out.raw_wheel];
  if(b->rival.tyres[1]<=0||b->rival.tyres[4]<=0||b->rival.power>24||b->rival.handling>24||b->rival.power+b->rival.handling>34)return 0;
  b->maker=(int)maker;b->car=(int)car;b->color=(int)color_index;b->pack=color->pack;b->base_paint=color->paint;b->custom_color=(int)out.raw_custom_color;
  b->paint=out.raw_custom_color?GHOST_ARCADE_PALETTES[color->pack].base+(int)out.raw_custom_color-1:color->paint;
  b->raw_ramp=b->ramp=b->raw_route=b->city=b->render_course=-1;b->source_id=CAR_GHOST_DEFAULT_SOURCE_BASE|(uint64_t)(index+1u);
  if(!car_ghost_arcade_difficulty(b->rival.power,b->rival.handling,out.player_win_count,&b->target_level,&b->target_rank))return 0;
  *view=out;return 1;
}
static int ghost_default_area_ramp(uint32_t area,int ramp) {
  if(area>=8u||ramp<0||ramp>=22)return 0;
  uint32_t entry=M32(0x97391a0u+4u*area);
  return carry_image_span(entry,12)&&(uint32_t)ramp>=M32(entry+4u)&&(uint32_t)ramp<=M32(entry+8u);
}
static int ghost_default_binding_valid(const car_ghost_default_binding *binding) {
  car_ghost_default_view v;
  if(!binding||!binding->session_token||!car_ghost_default_record(binding->record.index,&v)||!v.manager_eligible||memcmp(&v,&binding->record,sizeof v)||!ghost_default_area_ramp(binding->area,binding->car.raw_ramp))return 0;
  const car_ghost_arcade_binding *b=&binding->car;
  car_ghost_arcade_spec s={.raw_model_id=v.raw_model_id,.power=v.car.rival.power,.handling=v.car.rival.handling,.dress=v.dress,.dress_x=v.dress_x,.player_win_count=v.player_win_count,.raw_ramp=b->raw_ramp,.raw_route=b->raw_route,.header_stage=b->race_field[0],.source_id=v.car.source_id,.session_token=binding->session_token,.has_crown=v.crown_area==(int)binding->area,.first_tutorial=b->first_tutorial,.raw_custom_color=v.raw_custom_color,.raw_aero=v.raw_aero,.raw_wheel=v.raw_wheel};
  car_ghost_arcade_binding expected;
  return car_ghost_arcade_bind(&s,&expected)&&!memcmp(b,&expected,sizeof expected);
}
int car_ghost_default_select(const car_ghost_default_spec *spec,car_ghost_default_binding *binding) {
  if(binding)memset(binding,0,sizeof *binding);ghost_default.pending=0;
  if(!spec||!binding||!car_ghost_default_available()||!spec->session_token||spec->area>=8u||(spec->first_tutorial!=0&&spec->first_tutorial!=1)||PG.requested)return 0;
  car_ghost_default_binding out={0};
  if(!car_ghost_default_record(spec->index,&out.record)||!out.record.manager_eligible)return 0;
  uint32_t area=RC_STACK_TOP-0x420u,ramp=area+4u;W8(area,spec->area);W8(ramp,0xffu);
  call(f_857ad4c,2,ramp,area);int raw_ramp=M8(ramp);
  if(!ghost_default_area_ramp(spec->area,raw_ramp))return 0;
  int raw_route=(int)call(f_857a7f8,1,ramp);
  uint32_t ramp_entry=M32(0x9739140u+4u*(uint32_t)raw_ramp),field[6];
  if(!carry_image_span(ramp_entry,24)||!ghost_native_race_field((int)M32(ramp_entry+8u),raw_route,spec->first_tutorial,field))return 0;
  car_ghost_default_view *v=&out.record;
  car_ghost_arcade_spec s={.raw_model_id=v->raw_model_id,.power=v->car.rival.power,.handling=v->car.rival.handling,.dress=v->dress,.dress_x=v->dress_x,.player_win_count=v->player_win_count,.raw_ramp=raw_ramp,.raw_route=raw_route,.header_stage=field[0],.source_id=v->car.source_id,.session_token=spec->session_token,.has_crown=v->crown_area==(int)spec->area,.first_tutorial=spec->first_tutorial,.raw_custom_color=v->raw_custom_color,.raw_aero=v->raw_aero,.raw_wheel=v->raw_wheel};
  if(!car_ghost_arcade_bind(&s,&out.car))return 0;
  if (ghost_default_choice_epoch == UINT64_MAX) return 0;
  out.area=spec->area;out.session_token=spec->session_token;out.choice_cookie=++ghost_default_choice_epoch;
  ghost_default.binding=out;ghost_default.pending=1;*binding=out;return 1;
}
int car_ghost_default_prepare(const car_ghost_default_binding *binding) {
  car_ghost_default_binding frozen={0};if(binding)frozen=*binding;
  int valid=binding&&car_ghost_default_available()&&ghost_default.pending&&!memcmp(&frozen,&ghost_default.binding,sizeof frozen)&&ghost_default_binding_valid(&frozen);
  car_ghost_clear();PG.requested=1;PG.observation.status=CAR_GHOST_FAILED;PG.observation.kind=CAR_GHOST_DEFAULT;
  if(!valid)return 0;
  PG.config=(car_ghost_config){.abi_version=CAR_GHOST_ABI_VERSION,.session_token=frozen.session_token,.kind=CAR_GHOST_DEFAULT,.rival=frozen.car.rival};
  memcpy(PG.config.race_field,frozen.car.race_field,24);PG.config.trail_band[0]=frozen.car.rival.power;PG.config.trail_band[1]=frozen.car.rival.handling;
  PG.config.native_flags[0]=frozen.record.crown_area==(int)frozen.area;PG.config.native_flags[1]=(unsigned char)frozen.car.first_tutorial;
  PG.arcade_on=1;PG.arcade=frozen.car;ghost_default.binding=frozen;ghost_default.active=1;
  PG.observation.session_token=frozen.session_token;PG.observation.status=CAR_GHOST_PREPARED;return 1;
}
int car_ghost_default_info(car_ghost_default_binding *binding) {
  if(binding)memset(binding,0,sizeof *binding);
  if(!binding||!ghost_default.active||!PG.requested||PG.config.kind!=CAR_GHOST_DEFAULT||PG.observation.status==CAR_GHOST_FAILED)return 0;
  *binding=ghost_default.binding;return 1;
}
static int ghost_default_ai_valid(void) {
  if(!ghost_default.active||!car_ghost_default_available()||ghost_default.tire_hook_calls!=1||!ghost_default.tire_hook_valid||!PG.started||PG.config.kind!=CAR_GHOST_DEFAULT||!rc_mem||M32(GHOST_TARGET_PTR)||rc_link_tx||rc_link_rx)return 0;
  if (PG.config.record_player) {
    if (!M32(GHOST_SAMPLER_PTR) || (!PG.saved && !ghost_runtime_recording())) return 0;
  } else if (M32(GHOST_SAMPLER_PTR) || ghost_runtime_active()) return 0;
  uint32_t cfg=M32(0x9802968u),setting=M32(0x980284cu),ai=M32(0x98028a8u),car=M32(0x98028b4u);
  if(cfg<RC_HEAP_BASE||setting<RC_HEAP_BASE||ai<RC_HEAP_BASE||car<RC_HEAP_BASE||!carry_span(cfg,0x120)||!carry_span(setting,0x47c)||!carry_span(ai,0xa0)||!carry_span(car,0x9bc)||M32(cfg+CFG_MODE)!=8u||M32(cfg+0xccu)||M32(cfg+0xbcu)!=PG.config.rival.type||M32(cfg+0xc0u)!=(uint32_t)PG.config.rival.power||M32(cfg+0xc4u)!=(uint32_t)PG.config.rival.handling||M32(cfg+0xc8u)||M8(cfg+0xd0u)!=PG.config.native_flags[0]||M8(cfg+0xd1u)!=PG.config.native_flags[1])return 0;
  for(unsigned i=0;i<6;i++)if(M32(cfg+RACE_FIELD+4u*i)!=PG.config.race_field[i])return 0;
  return 1;
}
