/* WVS4-only APP glue. All session authority lives in vs_session/net, not menu
 * statuses. No WV1/optional extension fallback, native RNG or native data edits.
 * Native Init may block inside the immutable original object; this glue cannot
 * interrupt it. All checks below surround RETURNED calls at safe boundaries. */
#include "story_assembly.h"
#include "namedb.h"
#include "titledb.h"
#include "dressdb.h"
#include "vs_vote_policy.h"
#include "vs_vote_policy_adapter.inc"
#ifndef APP_VS4_TEARDOWN_EXTRA
#define APP_VS4_TEARDOWN_EXTRA() ((void)0)
#endif
#define VS_PROFILE_CAR 5
#define VS_PROFILE_NAME 10
#define VS_PROFILE_DRESS 12
#define VS_PROFILE_BUILD 19
#define VS_BUILD_NAMESPACE 'C'
#define VS_BUILD_REVISION 4
#define VS_PROFILE VS4_PROFILE
#define VS_LOADING_MIN 30
#ifdef __ANDROID__
int android_online_vs_address(char *out, size_t capacity);
#endif
static void app_ta_rank_invalidate(void);
static struct {
  unsigned char registration[VS_PROFILE];
  int slot, skip, registered, native_initialized, local_finished, result_processed;
  int done_requested, teardown, begin_song, release_lost_context;
  int draft_power;
  uint64_t draft_at;
  uint64_t ui_round, ui_config, phase_at, song_round, song_config;
  int final_song;
  uint16_t map_choice[VS4_PLAYERS],day_choice[VS4_PLAYERS];
  unsigned map_ready,day_ready; /* last observed ballot presentation, never authority */
  int ui_phase;
  vs4_nonce result_incarnation;
  uint64_t result_round, result_config;
} AV4;

static uint64_t app_vs4_now(void) {
  double t=now_ms();
  /* Passing a regressed/invalid time to the core triggers its fail-closed clock
   * policy; never fabricate an advancing timestamp for liveness. */
  return isfinite(t) && t>=0 && t<(double)UINT64_MAX ? (uint64_t)t : 0;
}
static void vs_name(char *out,int n) {
  menu_name_ascii(&G.menu,out,n);
  if (!out[0]) snprintf(out,n,"PLAYER %d",G.menu.save_slot>0?G.menu.save_slot:1);
}
static void vs_ascii(char *out,int n,const char *s) {
  int k=0;
  for (;s&&*s&&k<n-1;++s) {
    unsigned char c=(unsigned char)*s;
    if(c<0x80)out[k++]=(char)c;
    else if(c==0xef&&(unsigned char)s[1]==0xbc&&(unsigned char)s[2]==0x8d)out[k++]='-',s+=2;
  }
  out[k]=0;
}
/* Registration uses permanent earned baseline P/H. TUNE_READY is a separate,
 * slot-bound allocation and must never be fed back into registration. */
static int vs_profile(unsigned char p[VS_PROFILE]) {
  int power,handling,mk=G.menu.maker,c=G.menu.car;
  if(mk<0||mk>=CARDB_ALL||c<0||c>=CARDB_NCARS[mk]||G.menu.color<0||G.menu.color>=CARDB_CARS[mk][c].ncolors)return 0;
  menu_tune(&G.menu,&power,&handling);
  if(story_tune_budget(power,handling)<0)return 0;
  memset(p,0,VS_PROFILE);p[0]=(unsigned char)mk;p[1]=(unsigned char)c;p[2]=(unsigned char)G.menu.color;
  p[3]=(unsigned char)power;p[4]=(unsigned char)handling;
  for(int i=0;i<5;++i)p[5+i]=G.menu.name[i]>=0?(unsigned char)G.menu.name[i]:255;
  int title=menu_title(&G.menu);p[10]=(unsigned char)title;p[11]=(unsigned char)(title>>8);
  p[12]=(unsigned char)G.menu.aero[mk][c];p[13]=(unsigned char)G.menu.mirror[mk][c];p[14]=(unsigned char)G.menu.wing[mk][c];p[15]=(unsigned char)G.menu.bonnet[mk][c];
  p[16]=G.menu.wheel[mk][c];p[17]=(unsigned char)G.menu.neon[mk][c];p[18]=G.menu.vinyl[mk][c];p[19]='C';p[20]=4;return 1;
}
static int vs_slot_matches(void) {
  int p,h;menu_tune(&G.menu,&p,&h);
  return AV4.registered&&AV4.slot==G.menu.save_slot&&AV4.skip==G.menu.save_skip&&
    AV4.registration[0]==G.menu.maker&&AV4.registration[1]==G.menu.car&&AV4.registration[2]==G.menu.color&&AV4.registration[3]==p&&AV4.registration[4]==h;
}
/* Before tune confirmation the room displays the registration baseline. */
static void vs_member_profile(const net_player *m,unsigned char p[VS_PROFILE]) {
  if(vs4_profile_valid(m,m->profile)){memcpy(p,m->profile,VS_PROFILE);return;}
  memcpy(p,m->identity,3);p[3]=m->base_power;p[4]=m->base_handling;memcpy(p+5,m->identity+3,16);
}
static int vs_same_build(const net_player *m) {unsigned char p[VS_PROFILE];vs_member_profile(m,p);return p[19]=='C'&&p[20]==4;}
static const cardb_color *vs_color(const net_player *m) {
  unsigned char p[VS_PROFILE];vs_member_profile(m,p);
  if(!vs_same_build(m)||p[0]>=CARDB_ALL||p[1]>=CARDB_NCARS[p[0]])return NULL;
  const cardb_car *c=&CARDB_CARS[p[0]][p[1]];return p[2]<c->ncolors?&c->colors[p[2]]:NULL;
}
static vs_dress_t vs_dress(const net_player *m) {
  unsigned char p[VS_PROFILE];vs_member_profile(m,p);const unsigned char *d=p+12;vs_dress_t v={0};
  v.aero=d[0]<=3?d[0]:0;v.mirror=d[1]<=1?d[1]:0;v.wing=d[2]<=4?d[2]:0;v.bonnet=d[3]<=3?d[3]:0;v.wheel=d[4];v.neon=d[5]<=12?d[5]:0;v.vinyl=d[6]<100?d[6]:0;return v;
}
static int vs_r35(int maker,int car) {
  if(maker<0||maker>=CARDB_ALL||car<0||car>=CARDB_NCARS[maker])return 0;
  for(const char *p=CARDB_CARS[maker][car].label;*p;++p)if(p[0]=='['&&p[1]=='R'&&p[2]=='3'&&p[3]=='5'&&p[4]==']')return 1;
  return 0;
}
/* Actual generated game catalog boundary; this is NOT ownership/authentication
 * of a remote card. It permits only model-supported IDs and never grants parts
 * or writes anyone's garage. Baseline and temporary P/H use the same legal
 * allocation grammar, while the session core separately freezes the budget. */
static int vs4_profile_game_valid(const uint8_t p[VS_PROFILE],void *ctx) {
  (void)ctx;
  if(!p||p[19]!='C'||p[20]!=4||p[0]>=CARDB_ALL||p[1]>=CARDB_NCARS[p[0]]||story_tune_budget(p[3],p[4])<0)return 0;
  const cardb_car *car=&CARDB_CARS[p[0]][p[1]];
  if(p[2]>=car->ncolors)return 0;
  const cardb_color *col=&car->colors[p[2]];
  if(col->pack<0||col->pack>=CARDB_NPACKS||col->gears<1||col->gears>6||col->type<0)return 0;
  int end=0;for(int i=5;i<10;++i){int glyph=p[i];if(glyph==255)end=1;else if(end||glyph>=NAMEDB_N)return 0;}
  int title=p[10]|p[11]<<8;
  /* title_glyphs intentionally falls back to TITLE_FIRST for unknown IDs, so
   * validate the actual generated bounds/length instead of accepting fallback. */
  if(title>=TITLEDB_N||(title&&!TITLEDB_LEN[title]))return 0;
  if(p[16]){int set;if(!menu_wheel_pack(p[16],&set))return 0;}
  const char *pack=CARDB_PACKS[car->colors[0].pack];
  if(strcmp(pack,"nis_R35")==0 && (p[12]||p[13]||p[14]||p[15]||p[17]||p[18]))return 0;
  int gem=pack[0]=='g'&&pack[1]=='e'&&pack[2]=='m';
  const int value[4]={p[12],p[13],p[14],p[15]},kind[4]={1,4,3,2};
  for(int part=0;part<4;++part)if(value[part]){
    int known=0;for(int lv=1;lv<64;++lv)if(DRESS_LADDER[gem][lv][0]==kind[part]&&DRESS_LADDER[gem][lv][1]==value[part])known=1;
    if(!known)return 0;
  }
  if(p[17]){int known=0;for(int lv=1;lv<64;++lv)if((DRESS_LADDER[gem][lv][0]==6||DRESS_LADDER[gem][lv][0]==8)&&DRESS_LADDER[gem][lv][1]==p[17])known=1;if(!known)return 0;}
  if(p[18]){
    int known=0;for(int lv=1;lv<64;++lv)if(DRESS_LADDER[gem][lv][0]==5){int v=DRESS_LADDER[gem][lv][1];int count=gem?(v==43?5:1):((v==1||v==11||v==21||v==31||v==48||v==58||v==68)?10:1);if(p[18]>=v&&p[18]<v+count)known=1;}
    if(!known)return 0;
  }
  return 1;
}
static unsigned app_vs4_all(const vs4_state *s) {return s&&s->n>=1&&s->n<=4?(1u<<s->n)-1u:0;}
static int app_vs4_snapshot_matches(const vs4_state *s) {
  const app_vs_round *r=&G.vs_go;
  if(!s||!r->round||s->round!=r->round||s->config!=r->config||s->membership!=r->membership||s->term!=r->term||
     !vs4_nonce_equal(s->incarnation,r->incarnation)||s->n!=r->n||s->me!=r->pcb||s->ramp!=r->ramp||s->zone!=r->zone||s->km!=r->km||s->song!=r->song||s->seed!=r->seed)return 0;
  for(int i=0;i<r->n;++i)if(!s->members[i].live||s->members[i].id!=r->player[i].id||!vs4_nonce_equal(s->members[i].session,r->player[i].session)||memcmp(s->members[i].profile,r->player[i].profile,VS_PROFILE))return 0;
  return 1;
}
static void app_vs4_poll_transport(void) {
  uint64_t now=app_vs4_now();char name[NET_NAME+1];vs_name(name,sizeof name);
  if(vs_host_is_open())vs_host_poll(now,name);
  if(net_is_open())net_poll(now);
  /* net_poll may just have queued an owner command on our loopback authority. */
  if(vs_host_is_open())vs_host_poll(now,name);
}
/* Called only outside a native call. Teardown ACK follows actual local cleanup. */
static void app_vs4_teardown(const char *note) {
  app_story_body_clear();
  int processed=AV4.result_processed;
  app_ta_rank_invalidate();app_rotary_stop();app_body_drop(AV4.release_lost_context);snd_quiet();
  car_clear_junction(&G.car.race);
#ifdef __ANDROID__
  junction_ui_reset(&race_junction_ui);junction_barrier_reset(&race_junction_barrier);race_tail_reset();
#endif
  APP_VS4_TEARDOWN_EXTRA();app_timing_reset();
  pre_race_tune_clear(&G.menu.pre_tune);
  G.vs_race=G.vs_closed=G.vs_wait=G.vs_seen_loaded=G.paused=0;G.n_rival=0;
  AV4.native_initialized=AV4.local_finished=0;AV4.teardown=1;
  memset(&G.vs_go,0,sizeof G.vs_go);hud_init(&G.hud,G.hud.screen_w,G.hud.screen_h);
  menu_vs_aborted(&G.menu,processed?"LOCAL RESULT PROCESSED - RETURNING TO ROOM":note);
  G.in_menu=1;
  if(net_is_open())net_teardown_done();
}
static void app_vs4_cancel(const char *note) {
  /* Cancel is sticky before packets/ACK/UI; no result may be processed after it. */
  if(net_is_open())net_cancel();
  app_vs4_teardown(note?note:"ROUND CANCELED - BACK IN ROOM");
  app_vs4_poll_transport();
}
/* Explicit leave/new room only. Ordinary abort/recovery NEVER closes sockets. */
static void vs_off(void) {
  if(net_is_open()&&net_session()->view.phase!=VS4_ROOM){net_cancel();app_vs4_poll_transport();app_vs4_teardown("YOU LEFT THE ROOM");app_vs4_poll_transport();}
  net_close();vs_host_close();net_scan(0,0);G.menu.vs.hosting=0;G.menu.vs.n_found=0;
  memset(&AV4,0,sizeof AV4);memset(&G.vs_go,0,sizeof G.vs_go);
}
/* Game-thread session shutdown: forgotten handles, not calls into a dead GL/VK
 * context. Parent declares in app.h and calls beside other owned asset releases. */
void app_vs_release(void) { AV4.release_lost_context=1;vs_off(); }
/* Return -1 terminal cleanup, 0 waiting, 1 native UPDATE allowed. */
static int app_vs4_native_gate(void) {
  if(!G.vs_race)return 1;
  app_vs4_poll_transport();const vs4_client *c=net_session();const vs4_state *s=net_state();
  if(!net_is_open()||c->stop||c->authority_lost||s->phase==VS4_ABORTING) {
    if(!AV4.teardown)app_vs4_teardown(c->authority_lost?"HOST LOST - ROOM RECOVERING":net_error_message());
    return -1;
  }
  if(!app_vs4_snapshot_matches(s)){app_vs4_cancel("FROZEN ROUND CHANGED - ROUND CANCELED");return -1;}
  int allowed=AV4.native_initialized&&!AV4.local_finished&&net_receive_drained()&&net_native_allowed();
  G.vs_wait=!allowed;
  if(!allowed)snd_rev_quiet();
  return allowed;
}
static void vs_link_send(const unsigned char *p,int n,void *ctx) {(void)ctx;net_race_send(p,n);}
static void vs_link_receive(void *ctx) {
  (void)ctx;app_vs4_poll_transport();
  /* This may run INSIDE immutable native Update. Never teardown/re-enter native
   * here. Abort stays sticky for the immediately following safe APP boundary. */
  if(!net_receive_drained()||!net_native_allowed())return;
  unsigned char packet[VS4_NATIVE];
  for(int pcb=0;pcb<G.vs_go.n;++pcb)if(pcb!=G.vs_go.pcb&&net_take_race(pcb,packet))car_link_deliver(pcb,packet,VS4_NATIVE);
}
static void app_vs4_roster(const vs4_state *s,int match);

static int app_vs4_tune_open(const vs4_state *s) {
  menu_state *m=&G.menu;
  if(m->vs.flow_stage!=MENU_VS_FLOW_DAY)return 1;
  return menu_vs_time_commit(m,s->round,s->zone)&&menu_vs_tune_open(m,s->round);
}

static int app_vs4_accept_tune(const vs4_state *s) {
  const net_player *member=&s->members[s->me];
  const unsigned char *p=member->profile;
  unsigned char expected[VS_PROFILE];
  memcpy(expected,AV4.registration,sizeof expected);
  expected[3]=p[3];expected[4]=p[4];
  return member->id==G.vs_id&&vs4_profile_valid(member,p)&&!memcmp(p,expected,sizeof expected)&&
    menu_vs_tune_accept(&G.menu,s->round,p[3],p[4]);
}

static int app_vs4_capture(const vs4_state *s) {
  if(!s)return 0;
  unsigned all=app_vs4_all(s);const vs4_client *c=net_session();const vs4_state *live=net_state();
  /* A receipt is only usable at the CURRENT LOAD fence, never a copied earlier
   * LOAD or a second initialization after the local native sequence exists. */
  if(AV4.native_initialized||!c->joined||s->phase!=live->phase||s->event!=live->event||
     s->round!=live->round||s->config!=live->config||s->membership!=live->membership||
     s->term!=live->term||!vs4_nonce_equal(s->incarnation,live->incarnation))return 0;
  if(!all||s->n<2||s->me>=s->n||s->phase!=VS4_LOAD||s->tuned!=all||!s->round||!s->config||c->stop||c->authority_lost||!vs_slot_matches())return 0;
  app_vs_round r;memset(&r,0,sizeof r);r.incarnation=s->incarnation;r.membership=s->membership;r.term=s->term;r.round=s->round;r.config=s->config;
  r.seed=s->seed;r.ramp=s->ramp;r.zone=s->zone;r.km=s->km;r.song=s->song;r.n=s->n;r.pcb=s->me;
  if(r.ramp>=22||r.zone>1||r.km<1||r.km>100)return 0;
  for(int i=0;i<r.n;++i){if(!s->members[i].live||!vs4_profile_valid(&s->members[i],s->members[i].profile)||!vs4_profile_game_valid(s->members[i].profile,NULL)||story_tune_budget(s->members[i].base_power,s->members[i].base_handling)<0||!vs_color(&s->members[i]))return 0;r.player[i]=s->members[i];}
  if(!app_vs4_tune_open(s)||!app_vs4_accept_tune(s))return 0;
  app_vs4_roster(s,1);
  G.vs_go=r;G.menu.vs.ramp=r.ramp;G.menu.vs.km=r.km;G.menu.zone=r.zone;G.menu.course=vs_vote_raw_course[r.ramp];
  menu_vs_song(&G.menu,r.song-2);G.vs_song=G.menu.song;G.pre_wait=0;
  menu_vs_loading(&G.menu);
  if(G.menu.vs.state!=MENU_VS_LOADING)return 0;
  AV4.native_initialized=AV4.local_finished=AV4.result_processed=AV4.done_requested=AV4.teardown=0;
  return 1;
}
/* Native Init has RETURNED and exact own paint/model/HUD are ready. Never wait
 * for peer native packets as a LOAD prerequisite; that would deadlock all peers. */
static int app_vs4_initialized(void) {
  app_vs4_poll_transport();
  if(!app_vs4_snapshot_matches(net_state())||net_session()->stop||net_session()->authority_lost||net_state()->phase!=VS4_LOAD){app_vs4_cancel("ROUND CHANGED WHILE LOADING");return 0;}
  AV4.native_initialized=1;G.vs_wait=1;
  if(!net_load_ready()){app_vs4_cancel("LOAD READY NOT ACCEPTED");return 0;}
  return 1;
}
/* The local native goal is not authority to award stars. A sticky cancellation
 * or changed config is checked before accepting the all-FINISH RESULTS fence. */
static int app_vs4_finish_ready(void) {
  if(!G.vs_race)return 1;
  app_vs4_poll_transport();const vs4_state *s=net_state();const vs4_client *c=net_session();
  if(c->stop||c->authority_lost||!app_vs4_snapshot_matches(s)){app_vs4_cancel("ROUND CANCELED BEFORE RESULTS");return -1;}
  if(!AV4.local_finished){if(!net_finish())return 0;AV4.local_finished=1;G.vs_wait=1;snd_rev_quiet();}
  if(s->phase!=VS4_RESULTS||s->finished!=app_vs4_all(s)||!net_receive_drained())return 0;
  if(AV4.result_processed)return 0;
  AV4.result_processed=1;AV4.result_incarnation=s->incarnation;AV4.result_round=s->round;AV4.result_config=s->config;
  return 1; /* mark before local result UI/save calls; no durable-save claim */
}
static void app_vs4_result_ui_left(void) {
  G.vs_race=0;G.vs_wait=0;app_rotary_stop();app_body_drop(0);car_clear_junction(&G.car.race);
#ifdef __ANDROID__
  race_tail_reset();junction_ui_reset(&race_junction_ui);junction_barrier_reset(&race_junction_barrier);
#endif
  APP_VS4_TEARDOWN_EXTRA();AV4.native_initialized=0;
}
static void app_vs4_notice(void) {
  if(!G.vs_race||G.menu.finish||(!G.vs_wait&&!AV4.local_finished))return;
  const char *msg=AV4.local_finished?"FINISH RECEIVED - WAITING FOR ALL PLAYERS":
    net_state()->phase==VS4_LOAD?"LOADING COMPLETE - WAITING FOR ALL PLAYERS":"WAITING FOR RACE TRANSPORT";
  float w=G.hud.screen_w,h=G.hud.screen_h,p=fminf(w/260.0f,h/140.0f);
  hud_ui_begin(w,h);hud_ui_rect(0,h*.45f,w,24*p,0,0,0,.8f);
  hud_ui_text(msg,(w-hud_ui_text_width(msg,p))*.5f,h*.45f+6*p,p,1,.9f,.5f,1);hud_ui_end();
}
static int app_vs4_command(unsigned op,unsigned target,unsigned value,const vs4_state *s) {
  vs4_command c;memset(&c,0,sizeof c);c.op=(uint8_t)op;c.target=(uint8_t)target;c.value=(uint16_t)value;
  /* WVS4 reserved config bytes MUST stay zero for READY/CHOICE commands. */
  if(op==VS4_ADVANCE||op==VS4_BEGIN){c.ramp=s->ramp;c.zone=s->zone;c.km=s->km;c.song=s->song;}
  return net_command(&c);
}
static void app_vs4_roster(const vs4_state *s,int match) {
  menu_state *m=&G.menu;m->vs.n=s->n;m->vs.me=s->me;m->vs.host=s->owner;
  /* Core clears votes between phases. Keep only actually observed ballots for
   * the local reveal; never display a cleared TIME value as a new MAP ballot. */
  if(s->phase==VS4_MAP){AV4.map_ready=s->ready;for(int i=0;i<s->n;++i)AV4.map_choice[i]=s->members[i].choice;}
  if(s->phase==VS4_TIME){AV4.day_ready=s->ready;for(int i=0;i<s->n;++i)AV4.day_choice[i]=s->members[i].choice;}
  for(int i=0;i<s->n;++i){const net_player *pl=&s->members[i];unsigned char p[VS_PROFILE];vs_member_profile(pl,p);const cardb_color *col=vs_color(pl);
    char nm[NET_NAME+1];char raw[NET_NAME+1];memcpy(raw,pl->name,NET_NAME);raw[NET_NAME]=0;vs_ascii(nm,sizeof nm,raw);snprintf(m->vs.name[i],sizeof m->vs.name[i],"%s",nm);
    m->vs.mismatch[i]=!col||!vs4_profile_game_valid(p,NULL)||story_tune_budget(pl->base_power,pl->base_handling)<0;m->vs.racing[i]=s->phase>=VS4_LOAD&&s->phase<=VS4_RESULTS;
    if(col)vs_ascii(m->vs.car[i],sizeof m->vs.car[i],CARDB_CARS[p[0]][p[1]].label);else snprintf(m->vs.car[i],sizeof m->vs.car[i],"UPDATE ALL CLIENTS");
    int end=0;for(int j=0;j<5;++j){end|=p[5+j]==255;m->vs.glyph[i][j]=(short)(end?-1:p[5+j]);}
    m->vs.other_vote[i]=(AV4.map_ready&(1u<<i))?((AV4.map_choice[i]&0x80)?2:1):0;
    int area=AV4.map_choice[i]&7;int card=1;for(;card<MENU_VS_CARDS&&menu_vs_card_area(card)!=area;++card){}m->vs.other[i]=(AV4.map_ready&(1u<<i))&&card<MENU_VS_CARDS?card:0;
    m->vs.other_day[i]=(AV4.day_ready&(1u<<i))?1:0;m->vs.other_zone[i]=AV4.day_choice[i]&1;
    if(!match)continue;
    m->vs.match[i].maker=col?p[0]:-1;m->vs.match[i].car=col?p[1]:-1;m->vs.match[i].color=col?p[2]:-1;m->vs.match[i].power=p[3];m->vs.match[i].handling=p[4];
    m->vs.match[i].base_power=pl->base_power;m->vs.match[i].base_handling=pl->base_handling;
    m->vs.match[i].base_valid=col && !m->vs.mismatch[i] && pl->live;
    memcpy(m->vs.match[i].glyph,m->vs.glyph[i],sizeof m->vs.match[i].glyph);
    if(m->vs.match[i].glyph[0]<0)menu_name_glyphs(m->vs.match[i].glyph,nm);
    vs_dress_t d=vs_dress(pl);m->vs.match[i].aero=d.aero;m->vs.match[i].mirror=d.mirror;m->vs.match[i].wing=d.wing;m->vs.match[i].bonnet=d.bonnet;m->vs.match[i].wheel=d.wheel;m->vs.match[i].neon=d.neon;m->vs.match[i].vinyl=d.vinyl;m->vs.match[i].title=p[10]|p[11]<<8;
  }
  if(match){m->vs.match_n=s->n;m->vs.match_me=s->me;}
}
static int app_vs4_open(const char *host) {
  unsigned char p[VS_PROFILE];char name[NET_NAME+1];if(!vs_profile(p)||!vs4_profile_game_valid(p,NULL))return 0;vs_name(name,sizeof name);
  memset(&AV4,0,sizeof AV4);AV4.slot=G.menu.save_slot;AV4.skip=G.menu.save_skip;memcpy(AV4.registration,p,VS_PROFILE);AV4.registered=1;
  net_set_decision_validator(vs4_vote_decision,NULL);
  net_set_registration_validator(vs4_profile_game_valid,NULL);
  if(net_open(host,NET_PORT,G.vs_id,name,p)!=0){AV4.registered=0;return 0;}G.vs_asked=now_ms()*1e-3;return 1;
}
static int app_vs4_random_song(void) {
  uint32_t word=0;size_t have=0;int fd=open("/dev/urandom",O_RDONLY|O_NOFOLLOW);if(fd<0)return -2;
  while(have<sizeof word){ssize_t n=read(fd,(unsigned char*)&word+have,sizeof word-have);if(n<0&&errno==EINTR)continue;if(n<=0)break;have+=(size_t)n;}
  close(fd);return have==sizeof word?1+(int)(word%20):-2;
}
static int app_vs4_final_song(const vs4_state *s,int *out) {
  if(AV4.song_round!=s->round||AV4.song_config!=s->config){
    int song=G.menu.song;if(song==0)song=app_vs4_random_song();
    if(song < -1||song>20){snprintf(G.menu.vs.note,sizeof G.menu.vs.note,"BGM ENTROPY UNAVAILABLE - WAITING");return 0;}
    AV4.final_song=song;AV4.song_round=s->round;AV4.song_config=s->config;
  }
  *out=AV4.final_song+2;return 1;
}
static void app_vs4_begin(const vs4_state *s) {
  for(int i=0;i<s->n;++i)if(G.menu.vs.mismatch[i]){snprintf(G.menu.vs.note,sizeof G.menu.vs.note,"INVALID CAR PROFILE - UPDATE ALL CLIENTS");return;}
  int song=G.menu.song;if(song==0)song=app_vs4_random_song();
  if(song < -1||song>20){snprintf(G.menu.vs.note,sizeof G.menu.vs.note,"BGM ENTROPY UNAVAILABLE - TRY AGAIN");return;}
  vs4_command c;memset(&c,0,sizeof c);c.op=VS4_BEGIN;c.target=VS4_MATCH;c.km=(uint8_t)(G.menu.vs.km>=1&&G.menu.vs.km<=100?G.menu.vs.km:15);c.song=(uint8_t)(song+2);
  if(net_command(&c)){AV4.begin_song=song;G.vs_song=song;G.menu.vs.start=0;}
  (void)s;
}
/* Protocol MATCH acknowledges the roster. The arcade's car introduction
 * instead uses final cards and plays before native race loading. */
static void app_vs4_match_ready(int resources_ready) {
  const vs4_state *s=net_state();menu_state *m=&G.menu;
  if(!net_is_open()||net_session()->stop||s->phase!=VS4_LOAD||m->vs.match_played||
     !app_vs4_snapshot_matches(s))return;
  if(m->screen==MENU_VS&&m->vs.state==MENU_VS_LOADING&&resources_ready)menu_vs_match(m);
  if(menu_vs_match_done(m))menu_vs_match_back(m);
}

static void app_vs4_tune(const vs4_state *s,uint64_t now) {
  menu_state *m=&G.menu;
  if(!app_vs4_tune_open(s)){app_vs4_cancel("TUNE EDITOR NOT READY");return;}
  if(s->tuned&(1u<<s->me)){
    if(!app_vs4_accept_tune(s))app_vs4_cancel("TUNE CONFIRMATION REJECTED");
    return;
  }

  unsigned remaining=s->tune_remaining_ms;
  int timed_authority=remaining!=VS4_TUNE_UNKNOWN;
  uint64_t since=timed_authority?net_session()->heard:AV4.phase_at;
  uint64_t elapsed=now>=since?now-since:0;
  if(!timed_authority)remaining=VS4_TUNE_MS;
  remaining=elapsed<remaining?remaining-(unsigned)elapsed:0;
  int ticks=(int)((remaining*60u+999u)/1000u);
  if(m->vs.flow_stage==MENU_VS_FLOW_TUNE&&(ticks+59)/60<(m->vs.tune_timer+59)/60&&ticks)
    snd_menu(SND_TIME_COUNT);
  m->vs.tune_timer=ticks;

  int p,h;
  if(m->vs.flow_stage==MENU_VS_FLOW_TUNE){
    if(!menu_vs_tune_draft(m,s->round,&p,&h)){app_vs4_cancel("INVALID TUNE ALLOCATION");return;}
    if(!remaining){
      if(!menu_vs_tune_accept(m,s->round,p,h)){app_vs4_cancel("TUNE CONFIRMATION REJECTED");return;}
    }else{
      if(timed_authority&&(AV4.draft_power!=p||(now>=AV4.draft_at&&now-AV4.draft_at>=250))){
        unsigned char draft[VS_PROFILE];
        memcpy(draft,AV4.registration,sizeof draft);draft[3]=(unsigned char)p;draft[4]=(unsigned char)h;
        if(net_tune_draft(draft)){AV4.draft_power=p;AV4.draft_at=now;}
      }
      return;
    }
  }
  if(!menu_vs_tune_ready(m,s->round,&p,&h)){app_vs4_cancel("INVALID TUNE ALLOCATION");return;}
  unsigned char tuned[VS_PROFILE];
  memcpy(tuned,AV4.registration,sizeof tuned);tuned[3]=(unsigned char)p;tuned[4]=(unsigned char)h;
  if(vs4_profile_valid(&s->members[s->me],tuned))(void)net_tune_ready(tuned);
  else app_vs4_cancel("INVALID TUNE ALLOCATION");
}
static void app_vs4_flow(void) {
  menu_state *m=&G.menu;const vs4_state *s=net_state();const vs4_client *client=net_session();
  if(!client->joined)return;
  if(client->stop||client->authority_lost||s->phase==VS4_ABORTING){
    if(!AV4.teardown)app_vs4_teardown(client->authority_lost?"HOST LOST - ROOM RECOVERING":net_error_message());
    snprintf(m->vs.note,sizeof m->vs.note,"%s",client->authority_lost?"ROOM RECOVERING - WAITING FOR QUORUM":net_error_message());return;
  }
  if(s->phase==VS4_ROOM){
    if(AV4.ui_round||AV4.teardown){if(G.vs_race)app_vs4_teardown("ROUND COMPLETE - BACK IN ROOM");menu_vs_aborted(m,AV4.result_processed?"LOCAL RESULT PROCESSED - BACK IN ROOM":"BACK IN ROOM");AV4.ui_round=0;AV4.teardown=0;}
    app_vs4_roster(s,0);m->vs.state=MENU_VS_LOBBY;
    if(m->vs.start&&s->me==s->owner&&s->n>=2)app_vs4_begin(s);
    return;
  }
  if(!vs_slot_matches()){app_vs4_cancel("CARD OR SAVE SLOT CHANGED - ROUND CANCELED");return;}
  for(int i=0;i<s->n;++i){unsigned char p[VS_PROFILE];vs_member_profile(&s->members[i],p);if(!vs4_profile_game_valid(p,NULL)||story_tune_budget(s->members[i].base_power,s->members[i].base_handling)<0){app_vs4_cancel("UNSUPPORTED GAME PROFILE - ROUND CANCELED");return;}}
  if(AV4.ui_round!=s->round){
    if(s->phase!=VS4_MATCH){app_vs4_cancel("MISSING ROUND START - ROUND CANCELED");return;}
    m->vs.state=MENU_VS_LOBBY;app_vs4_roster(s,0);
    if(!menu_vs_round_begin(m,s->round)){app_vs4_cancel("MENU ROUND NOT READY");return;}
    /* The roster is frozen before opening the course vote. */
    m->vs.area_go=0;AV4.draft_power=-1;AV4.result_processed=AV4.done_requested=AV4.native_initialized=AV4.local_finished=0;AV4.map_ready=AV4.day_ready=0;AV4.ui_round=s->round;AV4.ui_phase=VS4_MATCH;AV4.phase_at=app_vs4_now();AV4.teardown=0;
  }
  app_vs4_roster(s,0);
  if(s->phase!=AV4.ui_phase){AV4.ui_phase=s->phase;AV4.phase_at=app_vs4_now();}
  unsigned all=app_vs4_all(s);uint64_t now=app_vs4_now();
  if(s->phase==VS4_MATCH){
    if(!(s->ready&(1u<<s->me)))(void)app_vs4_command(VS4_PHASE_READY,VS4_MATCH,0,s);
    if(s->me==s->owner&&s->ready==all)(void)app_vs4_command(VS4_ADVANCE,VS4_MAP,0,s);
  }else if(s->phase==VS4_MAP){
    m->vs.state=MENU_VS_LOBBY;
    if(m->screen==MENU_VS)m->vs.area_go=1;
    if(!m->vs.omakase_sample_valid)(void)menu_vs_omakase_samples(m,s->round,s->seed,s->seed>>8,s->seed>>16);
    int area,confirmed,omakase;
    if(menu_vs_map_vote(m,s->round,&area,&confirmed,&omakase)&&confirmed&&!(s->ready&(1u<<s->me)))(void)app_vs4_command(VS4_CHOICE,VS4_MAP,(unsigned)area|(omakase?0x80u:0u),s);
    if(s->me==s->owner&&s->ready==all){
      uint16_t choices[4];for(int i=0;i<s->n;++i)choices[i]=s->members[i].choice;
      int winner;if(vs_vote_area_result(choices,s->n,s->ready,(uint8_t)s->seed,&winner)){
        vs4_command c;memset(&c,0,sizeof c);c.op=VS4_ADVANCE;c.target=VS4_TIME;c.ramp=(uint8_t)vs_vote_ramp_for_area(winner,s->seed);c.zone=s->zone;c.km=s->km;c.song=s->song;(void)net_command(&c);
      }
    }
  }else if(s->phase==VS4_TIME){
    int area=vs_vote_raw_area[s->ramp];
    if(m->screen==MENU_VS_AREA){(void)menu_vs_map_commit(m,s->round,area);if(now>=AV4.phase_at&&now-AV4.phase_at>=1600)(void)menu_vs_time_open(m,s->round);}
    m->vs.ramp=s->ramp;m->course=vs_vote_raw_course[s->ramp];
    int zone,confirmed;if(menu_vs_time_vote(m,s->round,&zone,&confirmed)&&confirmed&&!(s->ready&(1u<<s->me)))(void)app_vs4_command(VS4_CHOICE,VS4_TIME,(unsigned)zone,s);
    if(s->me==s->owner&&s->ready==all){uint16_t choices[4];for(int i=0;i<s->n;++i)choices[i]=s->members[i].choice;int winner;
      int song;if(vs_vote_day_result(choices,s->n,s->ready,&winner)&&app_vs4_final_song(s,&song)){vs4_command c;memset(&c,0,sizeof c);c.op=VS4_ADVANCE;c.target=VS4_TUNE;c.ramp=s->ramp;c.km=s->km;c.song=(uint8_t)song;c.zone=(uint8_t)winner;(void)net_command(&c);}}
  }else if(s->phase==VS4_TUNE){
    app_vs4_tune(s,now);
    if(!net_session()->stop&&s->me==s->owner&&s->tuned==all)(void)app_vs4_command(VS4_ADVANCE,VS4_LOAD,0,s);
  }else if(s->phase==VS4_LOAD){
    vs4_state config;if(net_take_config(&config)&&!app_vs4_capture(&config)){app_vs4_cancel("LOAD CONFIGURATION REJECTED");return;}
  }else if(s->phase==VS4_RESULTS){
    /* Stars/title pages are still presented. DONE is not an animation shortcut. */
    if(AV4.result_processed&&G.in_menu&&!m->finish&&m->screen==MENU_VS&&!AV4.done_requested){if(net_done())AV4.done_requested=1;}
    if(AV4.done_requested)snprintf(m->vs.note,sizeof m->vs.note,"RESULT PROCESSED - WAITING FOR ALL DONE");
  }
}
static void vs_menu(void) {
  menu_state *m=&G.menu;
  if(m->vs.connect<0){
    int leave=m->vs.connect==MENU_VS_LEAVE;
    m->vs.connect=0;
    vs_off();
    if(leave)menu_vs_left(m);
    else menu_vs_closed(m,"YOU LEFT THE ROOM");
    return;
  }
  /* A round-cancel pulse applies even after the original selection page moved. */
  uint64_t canceled;if(net_is_open()&&menu_vs_cancel_requested(m,&canceled)){(void)canceled;app_vs4_cancel("SELECTION CANCELED - BACK IN ROOM");return;}
  int related=m->game==MENU_GAME_VS&&(m->screen==MENU_VS||m->screen==MENU_VS_MATCH||m->screen==MENU_VS_AREA||m->screen==MENU_BGM||m->screen==MENU_SETTING||m->screen==MENU_VS_STAR||m->screen==MENU_VS_SEL);
  if(!related){if(net_is_open()||vs_host_is_open())vs_off();return;}
  char name[NET_NAME+1];vs_name(name,sizeof name);
  if(m->vs.connect){m->vs.connect=0;vs_off();
    if(m->vs.kind==MENU_VS_LAN){vs_host_set_decision_validator(vs4_vote_decision,NULL);vs_host_set_registration_validator(vs4_profile_game_valid,NULL);if(vs_host_open(NET_PORT)!=0||!app_vs4_open("127.0.0.1")){vs_off();snprintf(m->vs.note,sizeof m->vs.note,"COULD NOT HOST WVS4 ROOM");return;}m->vs.hosting=1;}
    else {
      char address[16];
#ifdef __ANDROID__
      int available=android_online_vs_address(address,sizeof address);
#else
      int available=0;
#endif
      if(!available){snprintf(m->vs.note,sizeof m->vs.note,"ONLINE MATCHMAKING UNAVAILABLE");return;}
      if(!app_vs4_open(address)){snprintf(m->vs.note,sizeof m->vs.note,"COULD NOT OPEN WVS4 ROOM");return;}
    }
    m->vs.state=MENU_VS_CONNECTING;
  }
  if(m->vs.join){int index=m->vs.join-1;m->vs.join=0;net_found found[MENU_VS_FOUND];int n=net_found_list(found,MENU_VS_FOUND);
    if(m->vs.kind!=MENU_VS_LAN||index<0||index>=n){snprintf(m->vs.note,sizeof m->vs.note,"WVS4 ROOM NO LONGER AVAILABLE");return;}
    char ip[16];snprintf(ip,sizeof ip,"%s",found[index].ip);vs_off();if(!app_vs4_open(ip)){snprintf(m->vs.note,sizeof m->vs.note,"COULD NOT JOIN WVS4 ROOM");return;}m->vs.state=MENU_VS_CONNECTING;
  }
  if(!net_is_open()){
    if(m->vs.kind==MENU_VS_LAN){net_scan(now_ms()*1e-3,1);net_found f[MENU_VS_FOUND];m->vs.n_found=net_found_list(f,MENU_VS_FOUND);for(int i=0;i<m->vs.n_found;++i)snprintf(m->vs.found[i],sizeof m->vs.found[i],"%.15s (%d/%d)",f[i].name,f[i].n,NET_PLAYERS);if(net_scan_incompatible())snprintf(m->vs.note,sizeof m->vs.note,"UPDATE ALL CLIENTS AND ROOM SERVER");}
    return;
  }
  app_vs4_poll_transport();if(!net_session()->joined){snprintf(m->vs.note,sizeof m->vs.note,"%s",net_error_message()[0]?net_error_message():"CONNECTING TO WVS4 ROOM...");return;}
  app_vs4_flow();
}
