/* Production app_ghost.inc with strict public-interface doubles. Synthetic
 * profiles/opaque export only: no private native frames, assets or file IDs. */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "car.h"
#include "menu.h"
#include "ghost_store.h"

#define CARDB_ALL 2
#define NPACKS 2
static const int CARDB_NCARS[2] = {1,1};
typedef struct { int pack, paint, type, gears; } cardb_color;
typedef struct { int ncolors; cardb_color colors[1]; } cardb_car;
static const cardb_car CARDB_CARS[2][1] = {{{1,{{0,0,10,5}}}},{{1,{{1,1,11,6}}}}};
static const float CARDB_TYRES[2][7] = {{1,2,3,4,5,6,5},{2,3,4,5,6,7,6}};
static struct {
  menu_state menu;
  car_state car;
  char save_dir[128];
  int in_menu, paused, n_rival, n_ten, vs_race, vs_closed, vs_wait, vs_seen_loaded;
  int story_race, story_cut_pending, story_old_ended, rival;
  void *rival_model[CAR_RIVALS];
} G;
static int stops, carries, prepares, clears, loads, saves, exports, reject, stale_complete, bad_model, no_engine;
static int store_result, has_record, published, legacy_stats, root_error;
char *realpath(const char *path, char *resolved) {
  assert(!strcmp(path,"/synthetic/save") && !resolved);
  if(root_error)return NULL;
  char *r=malloc(sizeof "/physical/save");assert(r);strcpy(r,"/physical/save");return r;
}
static unsigned serial = 30;
static car_ghost_config prepared_config;
static car_ghost_observation observation;
static car_spec synthetic_owner(void) {
  car_spec s = {.type=11,.gears=6,.spokes=6,.power=17,.handling=17};
  memcpy(s.tyres, CARDB_TYRES[1], sizeof s.tyres); return s;
}
static const char *physics_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const char *car_ghost_physics_id(void) { return no_engine ? NULL : physics_id; }
int car_ghost_race_field(int ramp,int route,int tutorial,uint32_t out[6]) {
  if(ramp<1||ramp>22||route!=0||tutorial) return 0;
  out[0]=100u+(unsigned)ramp;out[1]=0;out[2]=5;out[3]=0;out[4]=0x4b371b00;out[5]=0;return 1;
}
int car_ghost_render_course(const uint32_t field[6]) {return field&&field[0]>=101&&field[0]<=122?1:-1;}
int car_ghost_prepare(const car_ghost_config *cfg) {
  ++prepares; prepared_config=*cfg;
  assert(cfg->abi_version==CAR_GHOST_ABI_VERSION && cfg->session_token);
  assert(cfg->native_flags[0]==0 && cfg->native_flags[1]==0 && cfg->record_player==1);
  if(cfg->kind==CAR_GHOST_CHALLENGE) {
    assert(cfg->trail&&cfg->trail_bytes);
    assert(cfg->trail_band[0]==cfg->rival.power && cfg->trail_band[1]==cfg->rival.handling);
  } else assert(cfg->kind==CAR_GHOST_QUALIFICATION&&!cfg->trail&&!cfg->trail_bytes);
  observation=(car_ghost_observation){.kind=cfg->kind,.session_token=cfg->session_token,
      .status=reject||cfg->trail_band[2]<0?CAR_GHOST_FAILED:CAR_GHOST_PREPARED};
  return observation.status==CAR_GHOST_PREPARED;
}
void car_ghost_clear(void) {++clears;memset(&observation,0,sizeof observation);}
int car_ghost_status(car_ghost_observation *out) {*out=observation;return out->status!=CAR_GHOST_OFF;}
int car_ghost_export(void *out,size_t capacity,size_t *bytes) {
  ++exports; assert(observation.status==CAR_GHOST_FINISHED && observation.goal_reached);
  *bytes=32; if(!out) return 1;assert(capacity>=32);memset(out,0x42,32);return 1;
}
ghost_store_result ghost_store_load(const char *dir,const char *expected,ghost_store_record *r) {
  ++loads;assert(!strcmp(dir,"/physical/save")&&!strcmp(expected,physics_id));
  if(!has_record) return GHOST_STORE_NOT_FOUND;
  r->ramp=1;r->route=0;assert(car_ghost_race_field(1,0,0,r->race_field));
  r->owner=synthetic_owner();if(bad_model)r->owner.type=999;
  memcpy(r->physics_sha256,physics_id,65);r->recorded_at=(uint64_t)time(NULL)-7200;
  r->trail=malloc(32);assert(r->trail);memset(r->trail,0x45,32);r->trail_bytes=32;return GHOST_STORE_OK;
}
ghost_store_result ghost_store_save(const char *dir,const ghost_store_record *r) {
  ++saves;assert(!strcmp(dir,"/physical/save"));assert(r->ramp==1&&r->route==0&&r->race_field[0]==101);
  assert(!strcmp(r->physics_sha256,physics_id)&&r->recorded_at&&r->trail_bytes==32);
  assert(r->owner.type==10&&r->owner.power==17&&r->owner.handling==17);
  if(store_result==GHOST_STORE_OK||store_result==GHOST_STORE_COMMITTED_UNSYNCED) {has_record=1;++published;}
  return (ghost_store_result)store_result;
}
void ghost_store_free(ghost_store_record *r) {free(r->trail);memset(r,0,sizeof *r);}
int ghost_store_contains_map(const ghost_store_record *r,uint32_t ramp,uint32_t route) {return r->ramp==ramp&&r->route==route;}
static void vs_off(void){++stops;}
static void story_carry_cancel(void){++carries;}
void menu_ghost_open(menu_state *m) {
  m->screen=MENU_GHOST;m->game=MENU_GAME_GHOST;m->ghost.active_request=0;
  m->ghost.pending_action=m->ghost.inflight_action=0;m->ghost.prepared_request=0;m->ghost.pre_go=0;
}
void menu_ghost_set_availability(menu_state*m,int local,int cloud,int king) {
  m->ghost.local_available=!!local;m->ghost.cloud_configured=!!cloud;m->ghost.king_available=!!king;
}
int menu_ghost_take_action(menu_state*m,unsigned *id) {
  int a=m->ghost.pending_action;if(!a){*id=0;return 0;}
  *id=m->ghost.active_request;m->ghost.inflight_action=a;m->ghost.pending_action=0;return a;
}
int menu_ghost_complete(menu_state*m,unsigned id,int ok,const char*note) {
  if(stale_complete||m->screen!=MENU_GHOST||!id||m->ghost.active_request!=id)return 0;
  m->ghost.status=ok?MENU_GHOST_READY:MENU_GHOST_ERROR;m->ghost.completed_request=id;
  m->ghost.completed_action=m->ghost.inflight_action;m->ghost.inflight_action=0;m->ghost.active_request=0;
  snprintf(m->ghost.note,sizeof m->ghost.note,"%s",note);return 1;
}
int menu_ghost_begin_pre(menu_state*m) {
  if(m->ghost.status!=MENU_GHOST_READY||!m->ghost.completed_request)return 0;
  m->screen=MENU_GHOST_PRE;m->ghost.prepared_request=m->ghost.completed_request;
  m->ghost.completed_request=0;m->ghost.status=MENU_GHOST_BUSY;m->ready=0;return 1;
}
int menu_ghost_preparing(const menu_state*m) {
  return m->game==MENU_GAME_GHOST&&m->screen==MENU_GHOST_PRE&&m->ghost.prepared_request&&
   m->ghost.prepared_request==m->ghost.request_serial&&m->ghost.request_ramp==m->ghost.ramp&&
   m->ghost.request_route==m->ghost.route;
}
void menu_ghost_race_finished(menu_state*m,int result,int eligible) {
  assert(!eligible);menu_ghost_open(m);m->ghost.result=result;m->ghost.claim_eligible=m->ghost.claim_pending=0;
  m->ghost.status=result==MENU_GHOST_RESULT_INVALID?MENU_GHOST_ERROR:MENU_GHOST_READY;
}
#include "../src/app_ghost.inc"

static void reset(void) {
  car_ghost_clear();memset(&AG,0,sizeof AG);memset(&G,0,sizeof G);
  stops=carries=prepares=clears=loads=saves=exports=reject=stale_complete=bad_model=no_engine=0;
  store_result=GHOST_STORE_OK;has_record=published=root_error=0;legacy_stats=41;
  strcpy(G.save_dir,"/synthetic/save");G.in_menu=1;G.menu.ghost.ramp=1;G.menu.game=MENU_GAME_GHOST;
  G.menu.screen=MENU_GHOST;G.menu.manual=1;G.menu.maker=0;G.menu.car=G.menu.color=0;
  G.vs_race=3;G.vs_closed=7;G.vs_wait=1;G.menu.vs.state=MENU_VS_RACE;G.menu.vs.connect=G.menu.vs.start=1;
}
static void request(int action) {
  G.menu.ghost.active_request=G.menu.ghost.request_serial=++serial;
  G.menu.ghost.request_ramp=G.menu.ghost.ramp;G.menu.ghost.request_route=G.menu.ghost.route;
  G.menu.ghost.pending_action=action;G.menu.ghost.status=MENU_GHOST_BUSY;
  app_ghost_menu();
}
static void started(void) {
  assert(app_ghost_go_valid());observation.status=CAR_GHOST_RUNNING;
  observation.recording=1;observation.native_target_valid=observation.kind==CAR_GHOST_CHALLENGE;
  car_spec owner=synthetic_owner();owner.type=10;owner.gears=5;owner.spokes=5;
  memcpy(owner.tyres,CARDB_TYRES[0],sizeof owner.tyres);
  assert(app_ghost_started(&owner));G.in_menu=0;assert(AG.active&&!AG.prepared);
}
static void goal(int place) {
  observation.status=CAR_GHOST_FINISHED;observation.result_valid=observation.goal_reached=1;
  observation.won=place==0;observation.place=place;observation.gap_m=place?1.015f:-10.f;observation.export_ready=1;
  G.car.race.over=1;G.car.race.play_state=8;G.car.race.state=CAR_RACE_GOAL;
}
int main(void) {
  for(int mode=0;mode<4;++mode){reset();G.menu.game=mode;app_ghost_menu();assert(!app_ghost_finish());
    assert(!stops&&!prepares&&!loads&&!saves&&legacy_stats==41);}
  reset();app_ghost_menu();assert(stops==1&&!G.vs_race&&!G.vs_closed&&!G.menu.vs.connect&&!G.menu.vs.start);
  app_ghost_menu();assert(stops==1&&!prepares&&!saves);assert(!app_ghost_go_valid());
  request(MENU_GHOST_RECORD_LOCAL);assert(AG.prepared&&G.menu.screen==MENU_GHOST_PRE&&AG.course==1);
  assert(prepared_config.kind==CAR_GHOST_QUALIFICATION&&!prepared_config.trail);
  unsigned correct=G.menu.ghost.prepared_request;G.menu.ghost.prepared_request++;assert(!app_ghost_go_valid());
  G.menu.ghost.prepared_request=correct;G.menu.color++;assert(!app_ghost_go_valid());G.menu.color--;
  started();assert(!app_ghost_finish());goal(0);assert(app_ghost_finish());
  assert(saves==1&&exports==2&&published==1&&legacy_stats==41&&G.menu.ghost.result==MENU_GHOST_RESULT_FINISHED);
  assert(!AG.active&&G.in_menu&&!G.menu.ghost.claim_eligible&&strstr(G.menu.ghost.note,"SAVED"));
  app_ghost_menu();assert(G.menu.ghost.local_available&&!G.menu.ghost.cloud_configured);
  request(MENU_GHOST_CHALLENGE_LOCAL);assert(AG.prepared&&AG.rival_pack==1&&AG.rival_paint==1);
  assert(prepared_config.trail_band[0]==17&&prepared_config.trail_band[1]==17&&prepared_config.trail_band[2]==2);
  started();goal(1);assert(app_ghost_finish());assert(G.menu.ghost.result==MENU_GHOST_RESULT_LOSE&&!G.menu.ghost.claim_eligible);
  /* A negative gap with native rank0 is still a win; local never crowns. */
  app_ghost_menu();request(MENU_GHOST_CHALLENGE_LOCAL);started();goal(0);assert(app_ghost_finish());
  assert(G.menu.ghost.result==MENU_GHOST_RESULT_WIN&&!G.menu.ghost.claim_pending&&legacy_stats==41);
  reset();request(MENU_GHOST_CHALLENGE_LOCAL);assert(!AG.prepared&&!saves&&strstr(G.menu.ghost.note,"NO VALID"));
  /* Valid native retirement/time-up loses without exporting or replacing data;
   * even a stale rank0/won bit must not make an incomplete goal a victory. */
  for(int state=3;state<=6;state+=3){
    reset();has_record=1;request(MENU_GHOST_CHALLENGE_LOCAL);started();goal(0);
    G.car.race.play_state=state;observation.goal_reached=0;observation.export_ready=0;
    assert(app_ghost_finish()&&G.menu.ghost.result==MENU_GHOST_RESULT_LOSE);
    assert(!saves&&!exports&&has_record&&!published&&!G.menu.ghost.claim_eligible);
  }
  reset();has_record=1;request(MENU_GHOST_CHALLENGE_LOCAL);started();goal(0);
  G.car.race.play_state=6;observation.goal_reached=0;observation.status=CAR_GHOST_FAILED;
  assert(app_ghost_finish()&&G.menu.ghost.result==MENU_GHOST_RESULT_INVALID&&!exports&&!saves);
  reset();has_record=1;bad_model=1;request(MENU_GHOST_CHALLENGE_LOCAL);assert(!AG.prepared&&!saves);
  reset();reject=1;request(MENU_GHOST_RECORD_LOCAL);assert(!AG.prepared&&!saves&&observation.status==0);
  reset();no_engine=1;request(MENU_GHOST_RECORD_LOCAL);assert(!AG.prepared&&!prepares&&!loads&&!saves);
  reset();G.menu.ghost.route=1;request(MENU_GHOST_RECORD_LOCAL);assert(!AG.prepared&&strstr(G.menu.ghost.note,"ROUTE 0"));
  reset();stale_complete=1;request(MENU_GHOST_RECORD_LOCAL);assert(!AG.prepared&&observation.status==0&&!saves);
  reset();request(MENU_GHOST_RECORD_LOCAL);menu_ghost_open(&G.menu);app_ghost_menu();assert(!AG.prepared&&!exports);
  reset();request(MENU_GHOST_RECORD_LOCAL);started();observation.status=CAR_GHOST_FAILED;
  assert(app_ghost_finish()&&!saves&&G.menu.ghost.result==MENU_GHOST_RESULT_INVALID);
  reset();has_record=1;request(MENU_GHOST_RECORD_LOCAL);started();goal(0);store_result=GHOST_STORE_IO;
  assert(app_ghost_finish()&&!published&&has_record&&G.menu.ghost.result==MENU_GHOST_RESULT_INVALID);
  assert(strstr(G.menu.ghost.note,"PREVIOUS RECORD KEPT"));
  reset();request(MENU_GHOST_RECORD_LOCAL);started();goal(0);store_result=GHOST_STORE_COMMITTED_UNSYNCED;
  assert(app_ghost_finish()&&published==1&&G.menu.ghost.result==MENU_GHOST_RESULT_FINISHED);
  assert(strstr(G.menu.ghost.note,"DURABILITY UNCONFIRMED")&&!strstr(G.menu.ghost.note,"PREVIOUS"));
  reset();request(MENU_GHOST_RECORD_LOCAL);started();G.car.race.over=1;G.car.race.play_state=3;
  observation.status=CAR_GHOST_FINISHED;observation.result_valid=1;
  assert(app_ghost_finish()&&!saves&&!exports);
  /* Host physical root is pinned separately; unavailable roots cannot record. */
  reset();root_error=1;request(MENU_GHOST_RECORD_LOCAL);assert(!AG.prepared&&!loads&&!prepares&&!saves);
  assert(strstr(G.menu.ghost.note,"DIRECTORY UNAVAILABLE")&&!strcmp(G.save_dir,"/synthetic/save"));
  /* A redraw is not a native tick; drain at most six real logic ticks. */
  reset();request(MENU_GHOST_RECORD_LOCAL);started();goal(0);observation.export_ready=0;
  observation.native_ticks=100;assert(!app_ghost_finish());
  for(int i=0;i<20;++i)assert(!app_ghost_finish());assert(!saves&&!exports);
  observation.native_ticks=105;assert(!app_ghost_finish());observation.native_ticks=106;
  assert(app_ghost_finish()&&!saves&&!exports&&G.menu.ghost.result==MENU_GHOST_RESULT_INVALID);
  reset();request(MENU_GHOST_RECORD_LOCAL);started();goal(0);observation.export_ready=0;
  observation.native_ticks=200;assert(!app_ghost_finish());observation.native_ticks=203;observation.export_ready=1;
  assert(app_ghost_finish()&&saves==1&&G.menu.ghost.result==MENU_GHOST_RESULT_FINISHED);
  for(int a=MENU_GHOST_FETCH_KING;a<=MENU_GHOST_SUBMIT_CLAIM;++a){reset();request(a);
    assert(!prepares&&!saves&&!AG.prepared&&strstr(G.menu.ghost.note,"CLOUD NOT CONFIGURED"));}
  puts("PASS production app Ghost glue: local prepare/start/native result/export/storage; legacy gates, stale VS, cancellation, invalid/expired request, route0, cloud authority, save failures");
  return 0;
}
