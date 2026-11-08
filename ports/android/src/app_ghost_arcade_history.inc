/* Per-card outgoing results. V3 keeps the original opponent history and
 * adds aggregate results for player recordings and local crowns. */
#include <sys/statvfs.h>
#define ARCADE_HISTORY_RECORDS (GHOST_CATALOG_RECORDS+CAR_GHOST_DEFAULT_RECORDS)
#define ARCADE_HISTORY_SLOTS (ARCADE_HISTORY_RECORDS*GHOST_CATALOG_AREAS)
#define ARCADE_HISTORY_V2_BYTES (80u+ARCADE_HISTORY_SLOTS*20u+4u)
#define ARCADE_HISTORY_BYTES (ARCADE_HISTORY_V2_BYTES+8u)
static uint32_t ah_u32(const unsigned char*p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t ah_u64(const unsigned char*p){return ah_u32(p)|(uint64_t)ah_u32(p+4)<<32;}
static void ah_w32(unsigned char*p,uint32_t v){for(int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static void ah_w64(unsigned char*p,uint64_t v){ah_w32(p,(uint32_t)v);ah_w32(p+4,(uint32_t)(v>>32));}
static int app_arcade_history_path(char*path,size_t capacity){
 if(!AG.root_valid||AC.history_slot<1||AC.history_slot>MENU_SAVES||AC.history_born<=0||AC.history_maker<0||AC.history_maker>=MENU_GARAGE_MAKERS||AC.history_car<0||AC.history_car>=MENU_GARAGE_CARS)return 0;
 int n=snprintf(path,capacity,"%s/ghost-arcade-v2-%d-%d-%d-%lld.cgh",AG.physical_root,AC.history_slot,AC.history_maker,AC.history_car,AC.history_born);
 return n>0&&(size_t)n<capacity;
}
/* 0.4 only changed the paint section. Both catalog digests use the same
 * recorded/default indices, so the 0.3 history remains valid. */
static int app_arcade_history_catalog(const unsigned char *digest) {
 static const unsigned char cinder_03[32]={
  0xed,0x2e,0x3c,0xc9,0x3e,0x7a,0x6e,0x9e,0x1d,0x77,0xa1,0xc0,0xfc,0xd2,0xfa,0x50,
  0x08,0x4a,0x48,0xec,0x54,0x09,0xa8,0xb1,0x35,0x11,0x3e,0x5d,0x8d,0x42,0x9d,0xa1
 };
 return !memcmp(digest,GHOST_CATALOG_APPROVED_SHA256,32) || !memcmp(digest,cinder_03,32);
}
static void app_arcade_history_sync(void){
 menu_state*m=&G.menu;int slot=0,maker=0,car=0;long long born=0;
 if(!m->save_skip&&m->save_slot>=1&&m->save_slot<=MENU_SAVES&&m->own_sel>=0&&m->own_sel<m->n_own){const menu_own*o=&m->own[m->own_sel];if(o->maker==m->maker&&o->car==m->car&&o->born>0){slot=m->save_slot;maker=o->maker;car=o->car;born=o->born;}}
 if(AC.history_slot==slot&&AC.history_maker==maker&&AC.history_car==car&&AC.history_born==born)return;
 m->ghost.previous_query_valid=0;AC.history_slot=slot;AC.history_maker=maker;AC.history_car=car;AC.history_born=born;AC.history_bad=0;
 memset(AC.history,0,sizeof AC.history);AC.player_races=AC.player_wins=0;AC.published=0;if(++AC.epoch==0)++AC.epoch;
 char path[4096];if(!app_arcade_history_path(path,sizeof path))return;
 const char*leaf=strrchr(path,'/');if(!leaf){AC.history_bad=1;return;}leaf++;
 int dir=open(AG.physical_root,O_RDONLY|O_DIRECTORY|O_NOFOLLOW);if(dir<0){AC.history_bad=1;return;}
 int fd=openat(dir,leaf,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);int error=errno;close(dir);
 if(fd<0){if(error!=ENOENT)AC.history_bad=1;return;}
 struct stat st;unsigned char*b=NULL;size_t done=0;
 if(fstat(fd,&st)||!S_ISREG(st.st_mode)||(st.st_size!=ARCADE_HISTORY_V2_BYTES && st.st_size!=ARCADE_HISTORY_BYTES))goto bad_ah;
 size_t bytes=(size_t)st.st_size;
 b=malloc(bytes);if(!b)goto bad_ah;
 while(done<bytes){ssize_t n=read(fd,b+done,bytes-done);if(n<0&&errno==EINTR)continue;if(n<=0)goto bad_ah;done+=(size_t)n;}
 if(memcmp(b,"CGAHST2\0",8)||ah_u32(b+8)!=(bytes==ARCADE_HISTORY_BYTES?3u:2u)||ah_u32(b+12)!=ARCADE_HISTORY_SLOTS||ah_u32(b+16)!=(uint32_t)slot||ah_u32(b+20)!=(uint32_t)maker||ah_u32(b+24)!=(uint32_t)car||ah_u32(b+28)||ah_u64(b+32)!=(uint64_t)born||!app_arcade_history_catalog(b+40)||ah_u32(b+72)||ah_u32(b+76)||ah_u32(b+bytes-4)!=(uint32_t)crc32(0,b,bytes-4))goto bad_ah;
 for(unsigned i=0;i<ARCADE_HISTORY_SLOTS;i++){const unsigned char*p=b+80+20*i;uint32_t played=ah_u32(p),won=ah_u32(p+4),lost=ah_u32(p+8);uint64_t when=ah_u64(p+12);if((uint64_t)won+lost!=played||!!played!=!!when)goto bad_ah;}
 if(bytes==ARCADE_HISTORY_BYTES){
  uint32_t played=ah_u32(b+bytes-12),won=ah_u32(b+bytes-8);
  if(won>played)goto bad_ah;
  AC.player_races=played;AC.player_wins=won;
 }
 for(unsigned i=0;i<ARCADE_HISTORY_SLOTS;i++){const unsigned char*p=b+80+20*i;unsigned r=i/8,a=i%8;AC.history[r][a].played=ah_u32(p);AC.history[r][a].won=ah_u32(p+4);AC.history[r][a].lost=ah_u32(p+8);AC.history[r][a].when=ah_u64(p+12);}
 free(b);close(fd);return;
 bad_ah:free(b);close(fd);AC.history_bad=1; /* retain damaged/foreign file, never overwrite */
}
/* 1 committed+synced;2 committed,durability uncertain;0 previous file retained. */
static int app_arcade_history_publish(void){
 if(AC.history_bad)return 0;char path[4096],temp[512];if(!app_arcade_history_path(path,sizeof path))return 0;
 const char*leaf=strrchr(path,'/');if(!leaf)return 0;leaf++;
 int n=snprintf(temp,sizeof temp,"%s.tmp.%llu",leaf,(unsigned long long)AG.token);if(n<=0||n>=(int)sizeof temp)return 0;
 int dir=open(AG.physical_root,O_RDONLY|O_DIRECTORY|O_NOFOLLOW);if(dir<0)return 0;struct statvfs space;
 if(fstatvfs(dir,&space)||(uint64_t)space.f_bavail*space.f_frsize<64u*1024u*1024u+ARCADE_HISTORY_BYTES){close(dir);return 0;}
 struct stat existing;if(!fstatat(dir,leaf,&existing,AT_SYMLINK_NOFOLLOW)&&!S_ISREG(existing.st_mode)){close(dir);return 0;}
 unsigned char*b=calloc(1,ARCADE_HISTORY_BYTES);if(!b){close(dir);return 0;}
 memcpy(b,"CGAHST2\0",8);ah_w32(b+8,3);ah_w32(b+12,ARCADE_HISTORY_SLOTS);ah_w32(b+16,(uint32_t)AC.history_slot);ah_w32(b+20,(uint32_t)AC.history_maker);ah_w32(b+24,(uint32_t)AC.history_car);ah_w64(b+32,(uint64_t)AC.history_born);memcpy(b+40,GHOST_CATALOG_APPROVED_SHA256,32);
 for(unsigned i=0;i<ARCADE_HISTORY_SLOTS;i++){unsigned char*p=b+80+20*i;unsigned r=i/8,a=i%8;ah_w32(p,AC.history[r][a].played);ah_w32(p+4,AC.history[r][a].won);ah_w32(p+8,AC.history[r][a].lost);ah_w64(p+12,AC.history[r][a].when);}
 ah_w32(b+ARCADE_HISTORY_BYTES-12,AC.player_races);
 ah_w32(b+ARCADE_HISTORY_BYTES-8,AC.player_wins);
 ah_w32(b+ARCADE_HISTORY_BYTES-4,(uint32_t)crc32(0,b,ARCADE_HISTORY_BYTES-4));
 int fd=openat(dir,temp,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);if(fd<0){free(b);close(dir);return 0;}
 size_t done=0;int good=1;while(done<ARCADE_HISTORY_BYTES){ssize_t amount=write(fd,b+done,ARCADE_HISTORY_BYTES-done);if(amount<0&&errno==EINTR)continue;if(amount<=0){good=0;break;}done+=(size_t)amount;}
 free(b);if(fsync(fd))good=0;if(close(fd))good=0;
 /* Numeric names stay bound to the opened private directory even if its path
  * is concurrently renamed/replaced. Interrupted staging is never adopted. */
 if(!good||renameat(dir,temp,dir,leaf)){unlinkat(dir,temp,0);close(dir);return 0;}
 int synced=fsync(dir)==0;close(dir);return synced?1:2;
}
static const char*app_arcade_history_record(unsigned index,unsigned area,int won){
 if(index>=ARCADE_HISTORY_RECORDS||area>=8||AC.history_bad||AC.history_slot<1)return "LOCAL HISTORY NOT SAVED - PREVIOUS DATA KEPT";
 time_t now=time(NULL);if(now<=0)return "LOCAL HISTORY CLOCK UNAVAILABLE";
 uint32_t old_played=AC.history[index][area].played,old_won=AC.history[index][area].won,old_lost=AC.history[index][area].lost;uint64_t old_when=AC.history[index][area].when;
 if(old_played==UINT32_MAX)return "LOCAL HISTORY COUNTER LIMIT";
 AC.history[index][area].played++;AC.history[index][area].when=(uint64_t)now;if(won)AC.history[index][area].won++;else AC.history[index][area].lost++;
 int rc=app_arcade_history_publish();if(!rc){AC.history[index][area].played=old_played;AC.history[index][area].won=old_won;AC.history[index][area].lost=old_lost;AC.history[index][area].when=old_when;}
 AC.published=0;if(++AC.epoch==0)++AC.epoch;
 return rc==1?NULL:rc==2?"LOCAL HISTORY COMMITTED - DURABILITY UNCONFIRMED":"LOCAL HISTORY WRITE FAILED - PREVIOUS DATA KEPT";
}


static uint64_t app_arcade_history_totals(uint64_t *races) {
 uint64_t played=AC.player_races,wins=AC.player_wins;
 for(unsigned i=0;i<ARCADE_HISTORY_RECORDS;++i)
  for(unsigned area=0;area<GHOST_CATALOG_AREAS;++area){
   played+=AC.history[i][area].played;wins+=AC.history[i][area].won;
  }
 if(races)*races=played;
 return wins;
}

static const char *app_arcade_history_player(int won) {
 if(AC.history_bad || AC.history_slot<1 || AC.player_races==UINT32_MAX)
  return "LOCAL HISTORY NOT SAVED - PREVIOUS DATA KEPT";
 ++AC.player_races;AC.player_wins+=(uint32_t)won;
 int saved=app_arcade_history_publish();
 if(!saved){--AC.player_races;AC.player_wins-=(uint32_t)won;}
 AC.published=0;
 return saved==1?NULL:saved==2?"LOCAL HISTORY COMMITTED - DURABILITY UNCONFIRMED":
                              "LOCAL HISTORY WRITE FAILED - PREVIOUS DATA KEPT";
}
