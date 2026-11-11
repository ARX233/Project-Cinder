/* Unit boundary only: all metadata/maps are separately measured actual Native
 * getter/select outputs. These host callbacks do NOT constitute native wins. */
#define main recorded_regression_main
#include "ghost_directory_host.c"
#undef main
#include "default_fixture.h"
static void bind_reject_unchanged(menu_state *m,uint64_t id,int ramp,int route){
 menu_state before;memcpy(&before,m,sizeof before);
 assert(!menu_ghost_bind_default_request(m,id,ramp,route));assert(!memcmp(&before,m,sizeof before));
}
static int published_default(const menu_state*m,unsigned raw){
 for(unsigned i=0;i<m->ghost.directory.count;++i)if(m->ghost.directory.rows[i].source_kind==MENU_GHOST_SOURCE_DEFAULT&&m->ghost.directory.rows[i].record_index==raw)return (int)i;
 return -1;
}
static void default_profile(menu_state*m,unsigned raw,int area){
 menu_ghost_open(m);int row=published_default(m,raw);assert(row>=0);
 m->ghost.search_kind=3;assert(menu_ghost_name_glyphs(m->ghost.query,m->ghost.directory.rows[row].name));
 ghost_rivals(m,area);int selected=-1;
 for(int i=0;i<m->ghost.ui.count;++i)if(ghost_directory_index(m,i)==row){selected=i;break;}
 assert(selected>=0);m->ghost.ui.sel=selected;m->ghost.directory_row=row;
}
static void pick_time(menu_state *m) {
 assert(menu_ghost_choosing_options(m)&&m->screen==MENU_BGM);
 float r[4];
 int sprite=m->zone?T_NIGHT:T_MORNING;
 assert(anm_sprite_rect(ID.day_cards,100*m->zone+(m->card_t+1)%60,sprite,r));
 m->tap=1;m->tap_x=(r[0]+r[2])*.5f;m->tap_y=(r[1]+r[3])*.5f;
 tick(m,1);
 assert(m->deciding);
 tick(m,m->deciding);
}

static void run_tuned_flow(menu_state *m) {
 m->tune_full[m->maker][m->car]=1;m->tune_power[m->maker][m->car]=20;
 m->zone=0;m->zones=2;m->bgm=1;
 m->key=1;tick(m,SLIDE+1);assert(m->zone==1);
 pick_time(m);assert(m->screen==MENU_SETTING&&menu_ghost_choosing_options(m));
 m->back=1;tick(m,1);assert(m->screen==MENU_BGM&&m->zone==1&&!m->pre_tune.state);
 pick_time(m);assert(m->screen==MENU_SETTING&&menu_ghost_choosing_options(m));
 m->key=1;tick(m,1);assert(m->pre_tune.power==19);
 m->tap=1;m->tap_x=320;m->tap_y=200;tick(m,1);assert(m->deciding);
 tick(m,m->deciding);assert(menu_ghost_preparing(m)&&m->pre_tune.state==2);
 assert(m->tune_power[m->maker][m->car]==20&&m->bgm==1);
 m->tune_full[m->maker][m->car]=0;
}

int main(void){
 _Static_assert(MENU_GHOST_CHALLENGE_ARCADE==6&&MENU_GHOST_CHALLENGE_DEFAULT==7,"stable action append");
 _Static_assert(MENU_GHOST_SOURCE_RECORDED==0&&MENU_GHOST_SOURCE_DEFAULT==1,"zero remains recorded");
 _Static_assert(MENU_GHOST_DIRECTORY_RECORDS==196&&MENU_GHOST_DEFAULT_RECORDS==120&&MENU_GHOST_DIRECTORY_MAX_RECORDS==324+MENU_GHOST_CLOUD_RECORDS+MENU_GHOST_LOCAL_RECORDS,"typed raw ranges/capacity");
 assert(!recorded_regression_main());
 for(int i=0;i<196;++i)assert(REAL_ROWS[i].source_kind==MENU_GHOST_SOURCE_RECORDED);
 menu_state m;memset(&m,0,sizeof m);menu_ghost_open(&m);
 unsigned eligible=0;short glyph[5];
 for(unsigned i=0;i<120;++i){const menu_ghost_directory_row*r=&UI_DEFAULT_FIX_ROWS[i];assert(r->source_kind==MENU_GHOST_SOURCE_DEFAULT&&r->record_index==i);assert(menu_ghost_name_glyphs(glyph,r->name));eligible+=DEFAULT_ELIGIBLE[i];
  for(int a=0;a<8;++a){assert(r->areas[a].ramp==-1&&r->areas[a].route==-1);assert(!!r->areas[a].native_available==!!DEFAULT_ELIGIBLE[i]);}
 }
 assert(eligible==109&&DEFAULT_NATIVE_AVAILABLE==1&&DEFAULT_ENUM_ZERO_RNG==1);
 menu_ghost_directory_view view={.rows=UI_DEFAULT_FIX_ROWS,.count=120,.epoch=11,.player_level=-1};assert(menu_ghost_set_directory(&m,&view));assert(ghost_directory_count(&m,-1,-1)==109);
 static const int original_champion[8]={111,112,113,115,118,116,117,119};
 for(int area=0;area<8;++area){
  m.ghost.search_kind=0;m.ghost.level=9;ghost_rivals(&m,area);
  assert(m.ghost.ui.count==1 && ghost_directory_index(&m,0)==original_champion[area]);
  assert(ghost_directory_index(&m,1)<0 && ghost_course_available(&m,visual(area)));
  menu_scene scene={0};
  assert(ghost_preview_scene(&m,&scene) && scene.n==1 && scene.cars[0].ghost_row==original_champion[area]+1);
  const menu_car *car=&scene.cars[0];
  assert(car->pack==UI_DEFAULT_FIX_ROWS[original_champion[area]].areas[area].pack);
  /* Original selected pose moves forward by 501.2665 units. Sprite scale
   * never widens or stretches the original 6.9-scale model. */
  assert(car->model[12]==-12.0f && car->model[13]==-6.0f);
  assert(fabsf(car->model[14]-501.26648f)<0.0001f);
  assert(car->cp && car->cp_x==317.5f && fabsf(car->cp_y-327.9f)<0.0001f);
  for(int axis=0;axis<3;++axis){
   const float *basis=car->model+4*axis;
   float norm2=basis[0]*basis[0]+basis[1]*basis[1]+basis[2]*basis[2];
   assert(fabsf(norm2-47.61f)<0.0001f);
  }
  if(area==0)assert(car->pack==21 && car->paint==0 && car->aero==3 && car->wheel==24);
  if(area==1)assert(car->pack==43 && car->paint==2 && car->aero==2 && car->vinyl==21);
  mat4 idle;memcpy(idle.m,car->model,sizeof idle.m);
  assert(ghost_original_decide(&m.ghost.ui,1));
  for(int tick_index=0;tick_index<10;++tick_index){
   int frame=ghost_original_card_frame(&m.ghost.ui,0);
   assert(frame==210+tick_index);
   const float *pose=GHOST_PREVIEW_POSES[GHOST_PREVIEW_FRAME[frame]-1];
   scene=(menu_scene){0};
   assert(ghost_preview_scene(&m,&scene)&&scene.n==1);
   car=&scene.cars[0];
   assert(car->model[14]==0.0f&&car->cp_x==pose[0]&&car->cp_y==pose[1]);
   for(int column=0;column<4;++column){
    assert(fabsf(car->model[4*column]-idle.m[4*column]*pose[2])<0.00001f);
    assert(fabsf(car->model[4*column+1]-idle.m[4*column+1]*pose[3])<0.00001f);
    if(column<3)assert(car->model[4*column+2]==idle.m[4*column+2]);
   }
   assert(ghost_original_tick(&m.ghost.ui)==(tick_index==9));
  }
 }
 menu_ghost_open(&m);
 for(unsigned i=0;i<120;++i){assert(!!ghost_row_matches(&m,i,-1,-1)==!!DEFAULT_ELIGIBLE[i]);
  if(!DEFAULT_ELIGIBLE[i]){m.ghost.directory_row=(int)i;m.ghost.area_slot=0;assert(!menu_ghost_action_available(&m,6)&&!menu_ghost_action_available(&m,7)&&!ghost_arcade_request(&m));}
 }
 /* Actual original page commits must enqueue7 without choosing a course in UI. */
 menu_ghost_open(&m);gas(&m);assert(m.ghost.ui.page==GHOST_UI_LEVEL);m.ghost.ui.sel=UI_DEFAULT_FIX_ROWS[0].areas[0].level;gas(&m);assert(m.ghost.ui.page==GHOST_UI_COURSE);gas(&m);assert(m.ghost.ui.page==GHOST_UI_RIVAL);gas(&m);assert(m.ghost.pending_action==7&&m.ghost.request_ramp==-1&&m.ghost.request_route==-1);
 unsigned page_id=0;assert(menu_ghost_take_action(&m,&page_id)==7&&menu_ghost_complete(&m,page_id,0,NULL));
 unsigned name_queries=0;short unchanged_name[5]={1,2,3,4,5};memcpy(m.name,unchanged_name,sizeof unchanged_name);m.garage_changed=0;
 for(unsigned i=0;i<120;++i)if(DEFAULT_ELIGIBLE[i]){menu_ghost_open(&m);m.ghost.ui.sel=3;gas(&m);assert(m.ghost.ui.page==GHOST_UI_NAME_TYPE);gas(&m);assert(m.ghost.ui.page==GHOST_UI_NAME);
  assert(menu_ghost_name_glyphs(m.ghost.query,UI_DEFAULT_FIX_ROWS[i].name));ghost_name_input(&m,275);assert(m.ghost.ui.page==GHOST_UI_COURSE&&ghost_row_matches(&m,i,-1,-1));
  assert(!m.garage_changed&&!memcmp(m.name,unchanged_name,sizeof unchanged_name));++name_queries;
 }
 assert(name_queries==109);
 unsigned admissions=0;
 for(int n=0;n<COUNT(DEFAULT_MAPS);++n){const default_map_fixture*b=&DEFAULT_MAPS[n];assert(b->index<120&&DEFAULT_ELIGIBLE[b->index]&&b->area<8&&b->ramp>=1&&b->ramp<=22&&b->route>=0);
  assert(b->source_id==DEFAULT_SOURCE_IDS[b->index]&&b->source_id>((uint64_t)1<<53)&&b->token>((uint64_t)1<<53)&&b->cookie&&b->field[0]);
  default_profile(&m,b->index,(int)b->area);const menu_ghost_directory_row *r=&UI_DEFAULT_FIX_ROWS[b->index];
  assert(!menu_ghost_action_available(&m,6)&&menu_ghost_action_available(&m,7));
  assert(ghost_arcade_request(&m));assert(m.ghost.pending_action==7&&m.ghost.request_source_kind==MENU_GHOST_SOURCE_DEFAULT);
  assert(m.ghost.request_record_index==b->index&&m.ghost.request_area_slot==(int)b->area&&m.ghost.request_catalog_epoch==view.epoch);
  assert(m.ghost.request_id_devel==r->id_devel&&m.ghost.request_id1==r->id1&&m.ghost.request_id2==r->id2);
  assert(m.ghost.request_ramp==-1&&m.ghost.request_route==-1);
  bind_reject_unchanged(&m,m.ghost.active_request,b->ramp,b->route); /* not yet taken */
  unsigned id=0;assert(menu_ghost_take_action(&m,&id)==7&&id&&!m.ghost.pending_action);assert(!menu_ghost_take_action(&m,&id));id=m.ghost.active_request;
  assert(!menu_ghost_complete(&m,id,1,NULL)&&m.ghost.active_request==id&&m.ghost.status==MENU_GHOST_BUSY&&!menu_ghost_begin_pre(&m));
  bind_reject_unchanged(&m,0,b->ramp,b->route);bind_reject_unchanged(&m,((uint64_t)1<<32)|id,b->ramp,b->route);
  bind_reject_unchanged(&m,id,0,b->route);bind_reject_unchanged(&m,id,23,b->route);bind_reject_unchanged(&m,id,b->ramp,-1);
  assert(menu_ghost_bind_default_request(&m,id,b->ramp,b->route));
  assert(m.ghost.request_ramp==b->ramp&&m.ghost.ramp==b->ramp&&m.ghost.request_route==b->route&&m.ghost.route==b->route);
  assert(r->areas[b->area].ramp==-1&&r->areas[b->area].route==-1); /* metadata never gets a random course */
  menu_state bound;memcpy(&bound,&m,sizeof bound);assert(menu_ghost_bind_default_request(&m,id,b->ramp,b->route)&&!memcmp(&bound,&m,sizeof bound));
  bind_reject_unchanged(&m,id,b->ramp==22?21:22,b->route);
  assert(menu_ghost_set_directory(&m,&view)&&m.ghost.active_request==id); /* same-view refresh cannot reroll */
  assert(menu_ghost_complete(&m,id,1,NULL)&&m.ghost.completed_action==7&&!menu_ghost_complete(&m,id,1,NULL));
  assert(menu_ghost_begin_pre(&m)&&menu_ghost_choosing_options(&m));bind_reject_unchanged(&m,id,b->ramp,b->route);
  if(!n){run_tuned_flow(&m);tick(&m,600);assert(!m.ghost.pre_go&&!m.ghost.intro_t);m.ready=1;
   tick(&m,220);assert(menu_update(&m,1.0f/60.0f)==1&&m.ghost.pre_go);
   menu_ghost_race_finished(&m,MENU_GHOST_RESULT_LOSE,0);
   assert(m.ghost.ui.page==GHOST_UI_SEARCH&&m.ghost.result==MENU_GHOST_RESULT_LOSE&&!m.ghost.claim_eligible);
  }else menu_ghost_open(&m);
  ++admissions;
 }
 assert(admissions==872); /* actual separately enumerated109*8 select outputs */
 const default_map_fixture *b=&DEFAULT_MAPS[0];
 default_profile(&m,b->index,(int)b->area);assert(ghost_arcade_request(&m));menu_ghost_race_finished(&m,MENU_GHOST_RESULT_WIN,1);assert(m.ghost.result==MENU_GHOST_RESULT_INVALID&&!m.ghost.claim_eligible&&m.ghost.ui.page!=GHOST_UI_RESULT);
 default_profile(&m,b->index,(int)b->area);assert(ghost_arcade_request(&m));unsigned premature=0;assert(menu_ghost_take_action(&m,&premature)==7);menu_ghost_race_finished(&m,MENU_GHOST_RESULT_WIN,1);assert(m.ghost.result==MENU_GHOST_RESULT_INVALID&&!m.ghost.claim_eligible&&m.ghost.ui.page!=GHOST_UI_RESULT);
 default_profile(&m,b->index,(int)b->area);assert(ghost_arcade_request(&m));unsigned id=0;assert(menu_ghost_take_action(&m,&id)==7);
 assert(menu_ghost_complete(&m,id,0,"REAL NATIVE BIND REJECTED")&&!m.ghost.active_request&&!menu_ghost_begin_pre(&m)); /* failure can precede map */
 default_profile(&m,b->index,(int)b->area);assert(ghost_arcade_request(&m));assert(menu_ghost_take_action(&m,&id)==7);m.ghost.request_source_kind=MENU_GHOST_SOURCE_RECORDED;
 bind_reject_unchanged(&m,id,b->ramp,b->route);assert(!menu_ghost_complete(&m,id,1,NULL)&&!m.ghost.active_request);
 default_profile(&m,b->index,(int)b->area);assert(ghost_arcade_request(&m));assert(menu_ghost_take_action(&m,&id)==7);++view.epoch;assert(menu_ghost_set_directory(&m,&view));bind_reject_unchanged(&m,id,b->ramp,b->route);assert(!menu_ghost_complete(&m,id,1,NULL));
 default_profile(&m,b->index,(int)b->area);assert(ghost_arcade_request(&m));assert(menu_ghost_take_action(&m,&id)==7);assert(menu_ghost_bind_default_request(&m,id,b->ramp,b->route)&&menu_ghost_complete(&m,id,1,NULL)&&menu_ghost_begin_pre(&m));
 assert(menu_ghost_set_directory(&m,NULL)&&!menu_ghost_preparing(&m));menu_ghost_race_finished(&m,MENU_GHOST_RESULT_INVALID,1);assert(m.ghost.result==MENU_GHOST_RESULT_INVALID&&!m.ghost.claim_eligible&&m.ghost.ui.page!=GHOST_UI_RESULT);
 /* The UI WIN path is an API callback-contract test, NOT evidence of a native win. */
 assert(menu_ghost_set_directory(&m,&view));default_profile(&m,b->index,(int)b->area);assert(ghost_arcade_request(&m));assert(menu_ghost_take_action(&m,&id)==7);assert(menu_ghost_bind_default_request(&m,id,b->ramp,b->route)&&menu_ghost_complete(&m,id,1,NULL)&&menu_ghost_begin_pre(&m));pick_time(&m);assert(menu_ghost_preparing(&m));m.ready=1;tick(&m,220);assert(menu_update(&m,1.0f/60.0f)==1);menu_ghost_race_finished(&m,MENU_GHOST_RESULT_WIN,0);assert(m.ghost.ui.page==GHOST_UI_SEARCH&&m.ghost.result==MENU_GHOST_RESULT_WIN&&!m.ghost.claim_eligible);
 /* Combined builtin rows total316, 305 selectable; a raw index is not global. */
 static menu_ghost_directory_row combined[318];memcpy(combined,REAL_ROWS,sizeof REAL_ROWS);memcpy(combined+196,UI_DEFAULT_FIX_ROWS,sizeof UI_DEFAULT_FIX_ROWS);
 menu_ghost_directory_view both=view;both.rows=combined;both.count=316;++both.epoch;assert(menu_ghost_set_directory(&m,&both));m.ghost.search_kind=0;assert(ghost_directory_count(&m,-1,-1)==305);
 assert(combined[0].record_index==combined[196].record_index&&combined[0].source_kind!=combined[196].source_kind);
 default_profile(&m,0,0);capture("default_rival",&m);assert(ghost_arcade_request(&m)&&m.ghost.pending_action==7);menu_ghost_open(&m);
 int seed_fukuoka=ghost_champion(&m,7),seed_hakone=ghost_champion(&m,6);
 assert(seed_fukuoka>=0&&seed_hakone>=0&&seed_fukuoka!=seed_hakone);
 m.ghost.level=9;ghost_rivals(&m,6);crown_sprite_drawn=0;
 draw_ghost_carousel(&m,ghost_original_bind(),1);assert(crown_sprite_drawn==1739);
 combined[316]=(menu_ghost_directory_row){.source_kind=MENU_GHOST_SOURCE_LOCAL_CROWN,
   .record_index=7,.id1=0x12,.id2=1,.name={0xff21,0xff32,0xff38}};
 combined[316].areas[7]=(menu_ghost_directory_area){.level=8,.native_available=1,.pack=21,
   .paint=0,.ramp=19,.route=0};
 ++both.epoch;both.count=317;
 assert(menu_ghost_set_directory(&m,&both));
 assert(ghost_champion(&m,7)==316&&ghost_champion(&m,6)==seed_hakone);
 m.ghost.search_kind=0;
 assert(ghost_directory_count(&m,-1,-1)==305);
 m.ghost.level=9;ghost_rivals(&m,7);assert(m.ghost.directory_row==316);
 crown_sprite_drawn=0;draw_ghost_carousel(&m,ghost_original_bind(),1);assert(crown_sprite_drawn==1738);
 assert(crown_sprite_bounds[1]>=84&&crown_sprite_bounds[3]<=136);
 m.ghost.ramp=19;m.ghost.route=0;
 assert(ghost_arcade_request(&m)&&menu_ghost_take_action(&m,&id)==MENU_GHOST_CHALLENGE_LOCAL_CROWN);
 assert(m.ghost.request_source_kind==MENU_GHOST_SOURCE_LOCAL_CROWN&&m.ghost.request_area_slot==7);
 assert(m.ghost.request_id1==0x12&&m.ghost.request_id2==1&&m.ghost.request_ramp==19);
 assert(menu_ghost_complete(&m,id,1,NULL)&&menu_ghost_begin_pre(&m)&&menu_ghost_choosing_options(&m));
 pick_time(&m);assert(menu_ghost_preparing(&m));
 assert(ghost_intro_crown(&m));m.ready=1;
 ghost_vs_drawn=0;crown_sprite_drawn=0;
 tick(&m,132);ghost_intro_overlay(&m,1024,768);assert(!ghost_vs_drawn&&!crown_sprite_drawn);
 tick(&m,38);ghost_intro_overlay(&m,1024,768);assert(!ghost_vs_drawn&&crown_sprite_drawn==1776);
 tick(&m,100);assert(m.ghost.intro_t==270&&!m.ghost.pre_go);
 assert(menu_update(&m,1.0f/60.0f)==1);
 menu_ghost_open(&m);assert(!m.ghost.intro_t);
 combined[317]=combined[316];combined[317].source_kind=MENU_GHOST_SOURCE_CLOUD;
 combined[317].record_index=0;
 ++both.epoch;both.count=318;
 assert(menu_ghost_set_directory(&m,&both));
 assert(ghost_champion(&m,7)==316&&ghost_directory_count(&m,-1,-1)==306);
 m.ghost.level=8;m.ghost.area_slot=7;m.ghost.directory_row=317;
 ghost_rivals(&m,7);crown_sprite_drawn=0;
 draw_ghost_carousel(&m,ghost_original_bind(),1);assert(!crown_sprite_drawn);
 m.ghost.ramp=19;m.ghost.route=0;
 assert(ghost_arcade_request(&m)&&menu_ghost_take_action(&m,&id)==MENU_GHOST_CHALLENGE_CLOUD);
 assert(m.ghost.request_source_kind==MENU_GHOST_SOURCE_CLOUD&&m.ghost.request_area_slot==7);
 assert(menu_ghost_complete(&m,id,1,NULL)&&menu_ghost_begin_pre(&m));
 menu_ghost_open(&m);
 menu_ghost_directory_row pair[2]={UI_DEFAULT_FIX_ROWS[0],UI_DEFAULT_FIX_ROWS[0]};menu_ghost_directory_view bad=both;bad.rows=pair;bad.count=2;assert(!menu_ghost_set_directory(&m,&bad));
 pair[1]=REAL_ROWS[0];assert(menu_ghost_set_directory(&m,&bad)); /* same index0 across kinds */
 bad.count=1;pair[0]=UI_DEFAULT_FIX_ROWS[0];pair[0].source_kind=4;assert(!menu_ghost_set_directory(&m,&bad));pair[0]=UI_DEFAULT_FIX_ROWS[0];pair[0].record_index=120;assert(!menu_ghost_set_directory(&m,&bad));pair[0]=REAL_ROWS[0];pair[0].record_index=196;assert(!menu_ghost_set_directory(&m,&bad));
 pair[0]=UI_DEFAULT_FIX_ROWS[0];pair[0].areas[0].ramp=1;pair[0].areas[0].route=0;assert(!menu_ghost_set_directory(&m,&bad));
 /* Empty archived area is still RECORDED and cannot become a default action. */
 pair[0]=REAL_ROWS[0];for(int a=0;a<8;++a){pair[0].areas[a].native_available=0;pair[0].areas[a].ramp=pair[0].areas[a].route=-1;}
 assert(menu_ghost_set_directory(&m,&bad));m.ghost.directory_row=0;m.ghost.area_slot=0;assert(!menu_ghost_request(&m,6)&&!menu_ghost_request(&m,7)&&!ghost_arcade_request(&m));
 /* Owner capability off: metadata alone never authorizes a default game. */
 static menu_ghost_directory_row offline[120];memcpy(offline,UI_DEFAULT_FIX_ROWS,sizeof offline);for(int i=0;i<120;++i)for(int a=0;a<8;++a)offline[i].areas[a].native_available=0;
 menu_ghost_directory_view no_bridge=view;no_bridge.rows=offline;assert(menu_ghost_set_directory(&m,&no_bridge));m.ghost.search_kind=0;assert(!ghost_directory_count(&m,-1,-1)&&!ghost_root_available(&m,0));m.ghost.directory_row=0;m.ghost.area_slot=0;assert(!menu_ghost_request(&m,7));
 printf("PASS typed original DEFAULT UI: actual120 metadata/109 eligible/11 disabled; actual872 late-map request7/PRE contracts; pair(kind,index), wrongkind, stale/epoch/detach/placeholder/bridge gates; recorded196/1267 intact; zero Native calls/RNG in UI. WIN/LOSE callback contracts are NOT native-gameplay outcomes.\n");
 return 0;
}
