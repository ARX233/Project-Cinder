/* Production TA completion -> independent LOCAL_UNVERIFIED machine board.
 * Included after app_ghost.inc. No original RC calls, clock/RNG writes, old PB
 * migration, renderer I/O, claimed server rank, or change to title awards. */
#include "ta_rank.h"
#include "ta_rank_outbox.h"
#include "ghost_arcade_models.inc"
#include <fcntl.h>
#include <time.h>
#include <unistd.h>
/* Configuration outlives model release; Android never falls back to external saves. */
static char ATR_DIRECTORY[1024];
static int ATR_DIRECTORY_CONFIGURED;
static struct {
  ta_rank_context *book;
  ta_rank_outbox *pending;
  ta_rank_status store_status, pending_status;
  int board_open, pending_open;
  int legacy_pb_loaded;
  char root[1024];
  uint8_t rules[32], physics[32], boot[16];
  uint64_t serial;
  int initialized, entropy;
#ifdef __ANDROID__
  struct {
    double poll_after, send_after, send_deadline, fetch_after, fetch_deadline;
    uint32_t cursor;
    uint8_t inflight[16];
    int sending, fetching, course, traffic;
    ta_rank_view board;
  } remote;
#endif
  struct {
    int active, invalid, done, slot, maker, car, color, manual;
    long long born;
    float last_elapsed;
    int final_snap;
    uint32_t final_elapsed_bits;
    car_ta_ranking_observation binding;
    ta_rank_attempt attempt;
  } run;
} ATR;
static long long app_ta_rank_born(void) {
  const menu_state *m=&G.menu;
  if(m->own_sel>=0 && m->own_sel<m->n_own && m->own[m->own_sel].maker==m->maker && m->own[m->own_sel].car==m->car)
    return m->own[m->own_sel].born;
  return 0;
}
static void app_ta_rank_put64(uint8_t *p,uint64_t x) { for(unsigned k=0;k<8;k++)p[k]=(uint8_t)(x>>(8*k)); }
static float app_ta_rank_float(uint32_t bits) { float f;memcpy(&f,&bits,4);return f; }
static int app_ta_rank_spec_equal(const car_spec *a,const car_spec *b) {
  return a->type==b->type && a->gears==b->gears && a->spokes==b->spokes &&
    a->power==b->power && a->handling==b->handling && !memcmp(a->tyres,b->tyres,sizeof a->tyres);
}
void app_ta_rank_release(void) {
  menu_set_ta_rank_view(&G.menu,NULL,MENU_TA_RANK_UNAVAILABLE);
  memset(G.menu.ta_rank_saved_pb,0,sizeof G.menu.ta_rank_saved_pb);
  ta_rank_destroy(ATR.book);ta_rank_outbox_destroy(ATR.pending);memset(&ATR,0,sizeof ATR);
}
static const char *app_ta_rank_directory(void) {
#ifdef __ANDROID__
  return ATR_DIRECTORY;
#else
  return ATR_DIRECTORY_CONFIGURED?ATR_DIRECTORY:G.save_dir;
#endif
}
void app_ta_rank_save_dir(const char *dir) {
  char candidate[sizeof ATR_DIRECTORY]={0};
  if(dir) {
    size_t n=strnlen(dir,sizeof candidate);
    if(n<sizeof candidate)memcpy(candidate,dir,n+1);
  }
  if(strcmp(app_ta_rank_directory(),candidate))app_ta_rank_release();
  memcpy(ATR_DIRECTORY,candidate,sizeof ATR_DIRECTORY);ATR_DIRECTORY_CONFIGURED=1;
}
static void app_ta_rank_ensure(void) {
  const char *directory=app_ta_rank_directory();
  if(ATR.initialized && !strcmp(ATR.root,directory))return;
  app_ta_rank_release();ATR.initialized=1;ATR.store_status=ATR.pending_status=TA_RANK_UNSAFE_PATH;
  if(!directory[0] || strlen(directory)>=sizeof ATR.root)return;
  memcpy(ATR.root,directory,strlen(directory)+1);
  /* A portable semantic cohort, not a target-dependent object/GL hash. Original
   * arcade course ids, real mode6+Goal8, finite binary32-truncated twenty-bit
   * timing, no debug/reset/gearbox/official-emulation, actual traffic partition.
   * Future server registry must independently approve these identities. */
  static const char policy[]="Cinder-TA-local-v1|original-main:2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6|course-id15-except5,7,11|frontendTA2/native6/goal8|f32*1000-trunc20bit|strict-owner/timeASC-dateDESC-seqDESC/top100|traffic-separated|no-debug-reset-gearbox-official-emulation|one-native-final-interpolation<=one-60Hz-step+2ulp|local-unverified";
  const char *physics=car_ghost_physics_id();
  if(!physics || !*physics || strlen(physics)>512)return;
  ghost_catalog_sha256_bytes((const unsigned char*)policy,sizeof policy-1,ATR.rules);
  ghost_catalog_sha256_bytes((const unsigned char*)physics,strlen(physics),ATR.physics);
  ATR.book=ta_rank_create(ATR.rules,ATR.physics);
  ATR.store_status=ATR.book?ta_rank_store_open(ATR.book,ATR.root):TA_RANK_MEMORY;
  ATR.board_open=ATR.store_status==TA_RANK_OK || ATR.store_status==TA_RANK_NOT_FOUND;
  ATR.pending=ta_rank_outbox_create(ATR.rules,ATR.physics);
  ATR.pending_status=ATR.pending?ta_rank_outbox_open(ATR.pending,ATR.root):TA_RANK_MEMORY;
  ATR.pending_open=ATR.pending_status==TA_RANK_OK || ATR.pending_status==TA_RANK_NOT_FOUND;
  /* OS entropy is independent of the original MT; no timestamp-as-nonce fallback. */
  int fd=open("/dev/urandom",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
  if(fd>=0) {
    size_t n=0;while(n<sizeof ATR.boot){ssize_t k=read(fd,ATR.boot+n,sizeof ATR.boot-n);if(k<=0)break;n+=(size_t)k;}
    ATR.entropy=n==sizeof ATR.boot;close(fd);
  }
}
static int app_ta_rank_saved_plate(int pack) {
  if (pack<0) return 0;
  int plate=0;
  for (size_t k=0;k<sizeof GHOST_ARCADE_MODELS/sizeof *GHOST_ARCADE_MODELS;++k) {
    if (GHOST_ARCADE_MODELS[k].pack!=pack) continue;
    int candidate=menu_ta_rank_model_plate(GHOST_ARCADE_MODELS[k].model);
    if (!candidate || (plate && plate!=candidate)) return 0;
    plate=candidate;
  }
  return plate;
}
/* Legacy totals are per save slot. A matching per-car time can identify
 * the model, but the file has no historical tune or completion date. */
static void app_ta_rank_read_saved_pb(void) {
  memset(G.menu.ta_rank_saved_pb,0,sizeof G.menu.ta_rank_saved_pb);
  if (!G.save_dir[0]) return;
  for (int slot=1;slot<=MENU_SAVES;++slot) {
    char path[1100],line[256];
    snprintf(path,sizeof path,"%s/records%d",G.save_dir,slot);
    FILE *f=fopen(path,"r");
    if (!f) continue;
    int complete=fgets(line,sizeof line,f) && (strchr(line,'\n') || feof(f));
    if (!complete) { fclose(f); continue; }
    int times[CAR_COURSES],i=0;
    const char *p=line;
    for (;i<CAR_COURSES;++i) {
      char *end;
      long ms=strtol(p,&end,10);
      if (end==p || ms<0 || ms>TA_RANK_MAX_SCORE_MS ||
          (*end && !strchr(" \t\r\n",*end))) break;
      times[i]=(int)ms;
      p=end;
    }
    if (i!=CAR_COURSES || p[strspn(p," \t\r\n")]) { fclose(f); continue; }
    enum { UNKNOWN_PACK=-1, AMBIGUOUS_PACK=-2 };
    int packs[CAR_COURSES];
    for (i=0;i<CAR_COURSES;++i) packs[i]=UNKNOWN_PACK;
    while (fgets(line,sizeof line,f)) {
      int course,pack,ms,end=0;
      if (sscanf(line,"car %3d %3d %9d %n",&course,&pack,&ms,&end)!=3 || line[end] ||
          course<0 || course>=CAR_COURSES || pack<0 || pack>=CARDB_NPACKS ||
          ms<=0 || ms!=times[course]) continue;
      if (packs[course]==UNKNOWN_PACK) packs[course]=pack;
      else if (packs[course]!=pack) packs[course]=AMBIGUOUS_PACK;
    }
    fclose(f);
    short name[5]={-1,-1,-1,-1,-1};
    snprintf(path,sizeof path,"%s/garage%d",G.save_dir,slot);
    f=fopen(path,"r");
    if (f) {
      while (name[0]<0 && fgets(line,sizeof line,f)) name_read(line,name);
      fclose(f);
    }
    for (i=0;i<CAR_COURSES;++i) {
      menu_ta_saved_pb *best=&G.menu.ta_rank_saved_pb[car_course_id(i)];
      if (times[i]>0 && (!best->ms || times[i]<best->ms)) {
        best->ms=times[i];
        best->plate=app_ta_rank_saved_plate(packs[i]);
        memcpy(best->name,name,sizeof best->name);
      }
    }
  }
}
#ifdef __ANDROID__
extern int android_timing_cloud_submit(const uint8_t *,size_t);
extern int android_timing_cloud_ack(void);
extern int android_timing_cloud_refresh(const char *,const char *,int,int);
extern int android_timing_cloud_board(unsigned char **,size_t *);

static void app_ta_rank_hex(char out[65],const uint8_t hash[32]) {
  static const char digits[]="0123456789abcdef";
  for (int i=0;i<32;++i) { out[2*i]=digits[hash[i]>>4]; out[2*i+1]=digits[hash[i]&15]; }
  out[64]=0;
}

static void app_ta_rank_cloud_tick(int course,int traffic) {
  double now=now_ms();
  if(now<ATR.remote.poll_after)return;
  ATR.remote.poll_after=now+250;
  if(!android_ghost_cloud_configured()) {
    ATR.remote.sending=ATR.remote.fetching=0;
    ATR.remote.board.row_count=0;
    ATR.remote.send_after=ATR.remote.fetch_after=0;
    return;
  }
  if(ATR.remote.sending) {
    int ack=android_timing_cloud_ack();
    if(ack || now>=ATR.remote.send_deadline) {
      if(ack==1 && ATR.pending_open) {
        ta_rank_status saved=ta_rank_outbox_ack(ATR.pending,ATR.remote.inflight);
        if(saved!=TA_RANK_NOT_FOUND)ATR.pending_status=saved;
        ATR.remote.fetch_after=0;
      }
      ATR.remote.sending=0;
      ATR.remote.send_after=now+(ack==1?250:15000);
    }
  }
  uint32_t count=ta_rank_outbox_count(ATR.pending);
  if(!ATR.remote.sending && ATR.pending_open && count && now>=ATR.remote.send_after) {
    uint32_t index=ATR.remote.cursor++%count;
    ta_rank_attempt a;
    uint8_t record[TA_RANK_COMMUNITY_ROW_BYTES];
    if(ta_rank_outbox_copy(ATR.pending,index,&a,NULL)==TA_RANK_OK && ta_rank_community_encode(&a,record) &&
       android_timing_cloud_submit(record,sizeof record)) {
      memcpy(ATR.remote.inflight,a.attempt,16);
      ATR.remote.sending=1;
      ATR.remote.send_deadline=now+20000;
    }
  }
  if(ATR.remote.fetching) {
    unsigned char *data=NULL;size_t bytes=0;
    int reply=android_timing_cloud_board(&data,&bytes);
    if(reply || now>=ATR.remote.fetch_deadline) {
      ta_rank_partition part={.course_id=(uint32_t)ATR.remote.course,.traffic=(uint32_t)ATR.remote.traffic};
      memcpy(part.rules_sha256,ATR.rules,32);memcpy(part.physics_sha256,ATR.physics,32);
      if(reply!=1 || !ta_rank_community_board(data,bytes,&part,&ATR.remote.board))ATR.remote.board.row_count=0;
      ATR.remote.fetching=0;
    }
    free(data);
  }
  if(!ATR.remote.fetching && course>=0 && ATR.book &&
     (course!=ATR.remote.course || traffic!=ATR.remote.traffic || now>=ATR.remote.fetch_after)) {
    char rules[65],physics[65];
    app_ta_rank_hex(rules,ATR.rules);app_ta_rank_hex(physics,ATR.physics);
    ATR.remote.fetching=android_timing_cloud_refresh(rules,physics,course,traffic);
    if(ATR.remote.fetching) {
      ATR.remote.course=course;ATR.remote.traffic=traffic;
      ATR.remote.fetch_after=now+15000;ATR.remote.fetch_deadline=now+20000;
    }
  }
}
#endif

static void app_ta_rank_menu(void) {
  /* Menu ownership is not a paused race continuation or a delayed Goal token. */
  if(ATR.run.active)ATR.run.invalid=1;
  app_ta_rank_ensure();
  int course=G.menu.screen==MENU_RANKING ? menu_ta_rank_course(&G.menu) : -1;
  int traffic=!!G.menu.ta_traffic;
#ifdef __ANDROID__
  app_ta_rank_cloud_tick(course,traffic);
#endif
  if(G.menu.screen!=MENU_RANKING){ATR.legacy_pb_loaded=0;return;}
  if(!ATR.legacy_pb_loaded){app_ta_rank_read_saved_pb();ATR.legacy_pb_loaded=1;}
#ifdef __ANDROID__
  const ta_rank_view *remote=&ATR.remote.board;
  if(course>=0 && remote->row_count && remote->partition.course_id==(uint32_t)course &&
     remote->partition.traffic==(uint32_t)traffic) {
    menu_set_ta_rank_view(&G.menu,remote,MENU_TA_RANK_COMMUNITY);
    if(G.menu.ta_rank_valid)return;
  }
#endif
  ta_rank_view view;
  if(!ATR.book || course<0 || ta_rank_view_local(ATR.book,(uint32_t)course,(uint32_t)traffic,1,&view)!=TA_RANK_OK) {
    menu_set_ta_rank_view(&G.menu,NULL,MENU_TA_RANK_UNAVAILABLE);return;
  }
  int okay=(ATR.store_status==TA_RANK_OK || ATR.store_status==TA_RANK_NOT_FOUND) &&
    (ATR.pending_status==TA_RANK_OK || ATR.pending_status==TA_RANK_NOT_FOUND);
  menu_set_ta_rank_view(&G.menu,&view,okay?MENU_TA_RANK_LOCAL:MENU_TA_RANK_STORE_ERROR);
}
static int app_ta_rank_model(const car_ta_ranking_observation *o,uint32_t *model) {
  const cardb_color *col=chosen_color();unsigned count=0;uint32_t found=0;
  for(size_t k=0;k<sizeof GHOST_ARCADE_MODELS/sizeof GHOST_ARCADE_MODELS[0];k++) {
    if(GHOST_ARCADE_MODELS[k].maker==G.menu.maker && GHOST_ARCADE_MODELS[k].car==G.menu.car &&
       GHOST_ARCADE_MODELS[k].color==G.menu.color && GHOST_ARCADE_MODELS[k].type==o->owner.type &&
       GHOST_ARCADE_MODELS[k].gears==o->owner.gears && GHOST_ARCADE_MODELS[k].pack==col->pack &&
       GHOST_ARCADE_MODELS[k].paint==col->paint) {
      found=GHOST_ARCADE_MODELS[k].model;++count;
    }
  }
  if(count!=1)return 0;*model=found;return 1;
}
static void app_ta_rank_invalidate(void) { if(ATR.run.active)ATR.run.invalid=1; }
static int app_ta_rank_owner_current(void) {
  return G.menu.save_slot==ATR.run.slot && G.menu.maker==ATR.run.maker &&
    G.menu.car==ATR.run.car && G.menu.color==ATR.run.color && G.menu.manual==ATR.run.manual &&
    app_ta_rank_born()==ATR.run.born && G.menu.game==MENU_GAME_TA && !G.menu.official &&
    !G.vs_race && !G.vs_closed && !G.n_ten && !app_ghost_mode();
}
static int app_ta_rank_observe(car_ta_ranking_observation *o) {
  if(!app_ta_rank_owner_current() || !car_ta_ranking_info(o))return 0;
  const car_ta_ranking_observation *b=&ATR.run.binding;
  return o->abi_version==CAR_TA_RANKING_ABI_VERSION && o->native_mode==6 &&
    o->course==b->course && o->course_id==b->course_id && o->ta_slot==b->ta_slot &&
    o->city==b->city && o->traffic==b->traffic && o->manual==b->manual &&
    !memcmp(o->race_field,b->race_field,sizeof b->race_field) && app_ta_rank_spec_equal(&o->owner,&b->owner);
}
static void app_ta_rank_start(void) {
  memset(&ATR.run,0,sizeof ATR.run);
  if(G.menu.game!=MENU_GAME_TA || G.menu.official || G.vs_race || G.vs_closed || G.n_ten || app_ghost_mode())return;
  app_ta_rank_ensure();
  if(!(ATR.board_open || ATR.pending_open) || !ATR.entropy || ATR.serial==UINT64_MAX ||
     getenv("WMMT_TA_GOAL") || getenv("WMMT_TA_TIME") || getenv("WMMT_PILOT"))return;
  car_ta_ranking_observation b;
  if(!car_ta_ranking_info(&b) || b.goal || b.course!=G.race_course || b.traffic!=!!G.race_traffic ||
     b.native_mode!=6 || !app_ta_rank_spec_equal(&b.owner,&G.race_spec))return;
  ta_rank_attempt *a=&ATR.run.attempt;
  if(!menu_ta_rank_metadata(&G.menu,&a->metadata) || !app_ta_rank_model(&b,&a->metadata.model_id))return;
  a->metadata.car_type=b.owner.type;a->metadata.power=(uint32_t)b.owner.power;a->metadata.handling=(uint32_t)b.owner.handling;
  memcpy(a->partition.rules_sha256,ATR.rules,32);memcpy(a->partition.physics_sha256,ATR.physics,32);
  a->partition.course_id=(uint32_t)b.course_id;a->partition.traffic=(uint32_t)b.traffic;
  memcpy(a->race_field,b.race_field,sizeof a->race_field);
  a->native_game_mode=6;a->frontend_game_mode=2;a->eligible=1;
  ATR.run.slot=G.menu.save_slot;ATR.run.maker=G.menu.maker;ATR.run.car=G.menu.car;
  ATR.run.color=G.menu.color;ATR.run.manual=G.menu.manual;ATR.run.born=app_ta_rank_born();
  if(ATR.run.slot && ATR.run.born<=0)return;
  uint8_t identity[64]={0},hash[32];
  /* This identity is ONLY local to one save directory. A copied card keeps its
   * identity and restart deduplication. It is neither globally unique nor an
   * original arcade ID or credential; a future server uses trusted auth instead. */
  memcpy(identity,"CINDER-TA-CARD-v1",17);app_ta_rank_put64(identity+24,(uint64_t)ATR.run.slot);
  app_ta_rank_put64(identity+32,(uint64_t)ATR.run.maker);app_ta_rank_put64(identity+40,(uint64_t)ATR.run.car);
  app_ta_rank_put64(identity+48,(uint64_t)ATR.run.born);
  ghost_catalog_sha256_bytes(identity,sizeof identity,hash);memcpy(a->owner,hash,16);
  memset(identity,0,sizeof identity);memcpy(identity,ATR.boot,16);app_ta_rank_put64(identity+16,++ATR.serial);
  memcpy(identity+24,a->owner,16);memcpy(identity+40,b.race_field,24);
  ghost_catalog_sha256_bytes(identity,sizeof identity,hash);memcpy(a->attempt,hash,16);
  /* An unregistered guest has a distinct local run identity, not a fabricated
   * persistent arcade card or authenticated global principal. */
  if(!ATR.run.slot)memcpy(a->owner,a->attempt,16);
  ATR.run.binding=b;ATR.run.last_elapsed=app_ta_rank_float(b.elapsed_bits);
  ATR.run.active=isfinite(ATR.run.last_elapsed) && ATR.run.last_elapsed>=0.0f;
}
static void app_ta_rank_tick(void) {
  if(!ATR.run.active || ATR.run.invalid || ATR.run.done)return;
  car_ta_ranking_observation o;
  if(!app_ta_rank_observe(&o)){ATR.run.invalid=1;return;}
  float elapsed=app_ta_rank_float(o.elapsed_bits);
  if(!isfinite(elapsed) || elapsed<0.0f){ATR.run.invalid=1;return;}
  if(ATR.run.final_snap && o.elapsed_bits!=ATR.run.final_elapsed_bits){ATR.run.invalid=1;return;}
  if(elapsed+0.00001f<ATR.run.last_elapsed) {
    /* Original GoalWait interpolates the finish within its last 60 Hz tick.
     * Real Nagoya evidence: 199.162155 -> final split199.159866. This is NOT a
     * race reset. Permit one bounded rebase ONLY onto the complete native final
     * checkpoint, then require that exact frozen clock forever. */
    float magnitude=fmaxf(elapsed,ATR.run.last_elapsed);
    float ulp=nextafterf(magnitude,INFINITY)-magnitude;
    int final=(o.native_state==7 || o.native_state==8) && o.checkpoint_count>=2 &&
      o.checkpoint_count<=CAR_SECTIONS+1 && o.checkpoint_next==o.checkpoint_count &&
      o.split_count==o.checkpoint_count && o.elapsed_bits==o.split_bits[o.checkpoint_count-1];
    if(!final || ATR.run.last_elapsed-elapsed>1.0f/60.0f+2.0f*ulp){ATR.run.invalid=1;return;}
    ATR.run.final_snap=1;ATR.run.final_elapsed_bits=o.elapsed_bits;
  }
  ATR.run.last_elapsed=elapsed;
}
static void app_ta_rank_finish(const car_race *race) {
  if(!ATR.run.active || ATR.run.done)return;
  ATR.run.done=1;
  car_ta_ranking_observation o;
  uint32_t console_elapsed_bits;memcpy(&console_elapsed_bits,&race->total,4);
  int valid=!ATR.run.invalid && app_ta_rank_observe(&o) && o.goal && o.native_state==8 &&
    race->over && race->play_state==8 && race->state==CAR_RACE_GOAL &&
    isfinite(race->total) && console_elapsed_bits==o.elapsed_bits;
  ATR.run.active=0;if(!valid)return;
  struct timespec now;
  if(clock_gettime(CLOCK_REALTIME,&now) || now.tv_sec<0 || (uint64_t)now.tv_sec>253402300799ull)return;
  ta_rank_attempt *a=&ATR.run.attempt;
  a->completed_at_ms=(uint64_t)now.tv_sec*1000u+(uint64_t)now.tv_nsec/1000000u;
  a->native_result_state=8;a->native_elapsed_bits=o.elapsed_bits;
  if(o.checkpoint_count<2 || o.checkpoint_count>CAR_SECTIONS+1 || o.split_count!=o.checkpoint_count)return;
  a->checkpoint_count=o.checkpoint_count-2;
  if(a->checkpoint_count>TA_RANK_CHECKPOINTS)return;
  for(unsigned k=0;k<a->checkpoint_count;k++)a->checkpoint_bits[k]=o.split_bits[k+1];
  /* Independent publications, not an invented two-file transaction. Queue first
   * so a healthy future-upload queue also captures a player outside local top100
   * or when the separate board is corrupt. No input replay or server receipt is
   * manufactured: queued metadata remains an unverified local proposal. */
  ta_rank_status queued=ATR.pending_open?ta_rank_outbox_enqueue(ATR.pending,a):ATR.pending_status;
  if(queued!=TA_RANK_NO_CHANGE && queued!=TA_RANK_DUPLICATE)ATR.pending_status=queued;
  ta_rank_submission sub={0};
  ta_rank_status status=ATR.board_open?ta_rank_commit_local(ATR.book,a,&sub):ATR.store_status;
  /* An unchanged/duplicate proposal does not fsync a previous uncertain commit
   * and does not recover an earlier failed proposal. Only real publication OK
   * clears its last error/COMMITTED_UNSYNCED disclosure. */
  if(status!=TA_RANK_NO_CHANGE && status!=TA_RANK_DUPLICATE)ATR.store_status=status;
  fprintf(stderr,"TA local board: %s; position %u; pending %s/%u; LOCAL_UNVERIFIED, no server receipt\n",
    ta_rank_error(status),sub.position,ta_rank_outbox_error(queued),ta_rank_outbox_count(ATR.pending));
}
