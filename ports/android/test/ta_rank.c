/* Offline production-core tests. All created artifacts stay in caller TMPDIR. */
#if defined(__linux__) && !defined(_GNU_SOURCE)
#define _GNU_SOURCE 1
#endif
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static int fault;
static ssize_t test_write(int fd,const void *p,size_t n){if(fault==1){errno=EIO;return -1;}return write(fd,p,n);}
static int test_sync(int fd){struct stat s;assert(!fstat(fd,&s));if((fault==2&&!S_ISDIR(s.st_mode))||(fault==4&&S_ISDIR(s.st_mode))){errno=EIO;return -1;}return fsync(fd);}
static int test_rename(int a,const char *b,int c,const char *d){if(fault==3){errno=EIO;return -1;}return renameat(a,b,c,d);}
static ssize_t test_read(int fd,void *p,size_t n){if(fault==5){errno=EIO;return -1;}return read(fd,p,n);}
static int test_close(int fd){int flags=fcntl(fd,F_GETFL);int fail=fault==6&&flags>=0&&(flags&O_ACCMODE)==O_WRONLY;int r=close(fd);if(fail){errno=EIO;return -1;}return r;}
#define write test_write
#define read test_read
#define close test_close
#define fsync test_sync
#define renameat test_rename
#include "../src/ta_rank.c"
#undef write
#undef read
#undef close
#undef fsync
#undef renameat
static uint32_t bits(float f){uint32_t x;memcpy(&x,&f,4);return x;}
static uint8_t rules[32]={1},physics[32]={2};
static ta_rank_attempt attempt(unsigned identity,unsigned course,unsigned traffic,float seconds,uint64_t date){
 ta_rank_attempt a={0};memcpy(a.partition.rules_sha256,rules,32);memcpy(a.partition.physics_sha256,physics,32);
 a.partition.course_id=course;a.partition.traffic=traffic;put32(a.owner,identity+1);put32(a.attempt,identity+1);put32(a.attempt+4,course);put32(a.attempt+8,traffic);
 a.completed_at_ms=date;a.native_elapsed_bits=bits(seconds);a.checkpoint_count=2;a.checkpoint_bits[0]=bits(seconds*.25f);a.checkpoint_bits[1]=bits(seconds*.75f);
 a.race_field[0]=course<15?stages[course]:0;a.race_field[2]=28;a.race_field[3]=bits(1000);a.race_field[4]=bits(1000000);
 a.native_game_mode=6;a.frontend_game_mode=2;a.native_result_state=8;a.eligible=1;a.metadata.name[0]=0x6e7e;a.metadata.name[1]=0x5cb8;
 a.metadata.power=17;a.metadata.handling=17;a.metadata.title_id=1;a.metadata.model_id=3;a.metadata.car_type=11;return a;
}
static void model_tests(void){
 uint32_t ms;assert(ta_rank_time_ms(bits(120),&ms)&&ms==120000);
 assert(ta_rank_time_ms(bits(.001f),&ms)&&ms==1);assert(!ta_rank_time_ms(bits(0),&ms)&&!ms);
 assert(!ta_rank_time_ms(bits(-1),&ms));assert(!ta_rank_time_ms(bits(NAN),&ms));assert(!ta_rank_time_ms(bits(INFINITY),&ms));assert(!ta_rank_time_ms(bits(FLT_MAX),&ms));
 assert(ta_rank_time_ms(bits(1048.574f),&ms)&&ms==1048574);assert(ta_rank_time_ms(bits(1048.575f),&ms)&&ms==1048574);assert(!ta_rank_time_ms(bits(nextafterf(1048.575f,INFINITY)),&ms));assert(!ta_rank_time_ms(bits(1199.999f),&ms));
 assert(ta_rank_time_ms(bits(nextafterf(.001f,0)),&ms)==0);
 for(unsigned c=0;c<15;c++)for(unsigned t=0;t<2;t++){
  ta_rank_context *ctx=ta_rank_create(rules,physics);assert(ctx);ta_rank_view v;
  ta_rank_attempt a=attempt(1,c,t,120,1000);ta_rank_submission result;
  if(!ta_rank_course_enabled(c)){assert(ta_rank_submit_local(ctx,&a,&result)==TA_RANK_INVALID);assert(ta_rank_view_local(ctx,c,t,1,&v)==TA_RANK_INVALID);ta_rank_destroy(ctx);continue;}
  assert(ta_rank_view_local(ctx,c,t,1,&v)==TA_RANK_OK&&v.real_count==0&&v.row_count==10);
  for(unsigned i=0;i<10;i++)assert(v.rows[i].source_kind==TA_RANK_SOURCE_FACTORY_DEFAULT&&v.rows[i].display_ms==1199999&&v.rows[i].default_index==i&&!v.rows[i].record.score_ms);
  assert(ta_rank_submit_local(ctx,&a,&result)==TA_RANK_OK&&result.position==1);
  assert(ta_rank_submit_local(ctx,&a,&result)==TA_RANK_DUPLICATE);
  a.metadata.title_id++;assert(ta_rank_submit_local(ctx,&a,&result)==TA_RANK_ATTEMPT_CONFLICT);a.metadata.title_id--;
  a.attempt[15]++;a.native_elapsed_bits=bits(121);assert(ta_rank_submit_local(ctx,&a,&result)==TA_RANK_NO_CHANGE);
  a.native_elapsed_bits=bits(120);assert(ta_rank_submit_local(ctx,&a,&result)==TA_RANK_NO_CHANGE);
  a.native_elapsed_bits=bits(119);assert(ta_rank_submit_local(ctx,&a,&result)==TA_RANK_OK&&result.position==1);
  a=attempt(3,c,t,119,1001);assert(ta_rank_submit_local(ctx,&a,&result)==TA_RANK_OK&&result.position==1);
  a=attempt(4,c,t,119,1001);assert(ta_rank_submit_local(ctx,&a,&result)==TA_RANK_OK&&result.position==1);
  ta_rank_record r;assert(ta_rank_get_local(ctx,c,t,1,&r)==TA_RANK_OK&&get32(r.attempt.owner)==5);
  assert(ta_rank_get_local(ctx,c,t,2,&r)==TA_RANK_OK&&get32(r.attempt.owner)==4);
  for(unsigned i=5;i<120;i++){a=attempt(i,c,t,120+(float)i,1000);ta_rank_status s=ta_rank_submit_local(ctx,&a,&result);assert(s==(i<102?TA_RANK_OK:TA_RANK_NO_CHANGE));}
  assert(ta_rank_view_local(ctx,c,t,0,&v)==TA_RANK_OK&&v.real_count==100&&v.row_count==10);
  for(unsigned i=1;i<=100;i++)assert(ta_rank_get_local(ctx,c,t,i,&r)==TA_RANK_OK);
  assert(ta_rank_get_local(ctx,c,t,101,&r)==TA_RANK_INVALID);
  ta_rank_destroy(ctx);
 }
 ta_rank_context *ctx=ta_rank_create(rules,physics);ta_rank_attempt good=attempt(7,0,0,120,0),a;ta_rank_submission out;
 for(unsigned k=0;k<18;k++){
  a=good;switch(k){case 0:a.native_result_state=7;break;case 1:a.native_game_mode=8;break;case 2:a.frontend_game_mode=4;break;case 3:a.eligible=0;break;case 4:a.partition.traffic=2;break;case 5:a.checkpoint_count=8;break;case 6:a.checkpoint_bits[0]=bits(NAN);break;case 7:a.checkpoint_bits[1]=bits(200);break;case 8:a.checkpoint_bits[2]=bits(1);break;case 9:a.completed_at_ms=MAX_DATE+1;break;case 10:memset(a.owner,0,16);break;case 11:a.metadata.power=25;break;case 12:a.metadata.name[0]=0xd800;break;case 13:a.metadata.original_id1=1;break;case 14:a.race_field[0]=364;break;case 15:a.race_field[4]=bits(INFINITY);break;case 16:a.partition.physics_sha256[0]++;break;case 17:memset(a.attempt,0,16);break;}
  assert(ta_rank_submit_local(ctx,&a,&out)==TA_RANK_INVALID);
 }
 ctx->m.sequence=UINT64_MAX;assert(ta_rank_submit_local(ctx,&good,&out)==TA_RANK_EXHAUSTED);ta_rank_destroy(ctx);
 puts("model: f32,all15course/30traffic selectors,top100,owner/ties/defaults/gates PASS");
}
static char *new_directory(void){const char *root=getenv("TMPDIR");assert(root&&root[0]=='/');char *p=malloc(4096);assert(p);assert(snprintf(p,4096,"%s/rank-host-XXXXXX",root)<4096);assert(mkdtemp(p));return p;}
static void leaf_remove(int fd,const char *name){struct stat s;assert(!fstatat(fd,name,&s,AT_SYMLINK_NOFOLLOW));assert(S_ISREG(s.st_mode)||S_ISLNK(s.st_mode)||S_ISFIFO(s.st_mode));assert(!unlinkat(fd,name,0));}
static unsigned char *read_leaf(int dir,const char *name,size_t *n){int f=openat(dir,name,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);assert(f>=0);struct stat s;assert(!fstat(f,&s)&&S_ISREG(s.st_mode));*n=(size_t)s.st_size;unsigned char *p=malloc(*n);assert(p&&read_all(f,p,*n));assert(!close(f));return p;}
static void write_leaf(int dir,const char *name,const unsigned char *p,size_t n){int f=openat(dir,name,O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW|O_NONBLOCK,0600);assert(f>=0);assert(write_all(f,p,n));assert(!close(f));}
static void search_only_parent_test(void) {
#if defined(O_PATH) || defined(O_SEARCH)
 if (!geteuid()) return; /* root's directory reads bypass this regression */
 char *parent=new_directory();
 char leaf[4104];assert(snprintf(leaf,sizeof leaf,"%s/private",parent)<(int)sizeof leaf);
 assert(!mkdir(leaf,0700) && !chmod(parent,0111));
 assert(open(parent,O_RDONLY|O_DIRECTORY)<0 && errno==EACCES);
 ta_rank_context *book=ta_rank_create(rules,physics);assert(book);
 ta_rank_outbox *outbox=ta_rank_outbox_create(rules,physics);assert(outbox);
 assert(ta_rank_store_open(book,leaf)==TA_RANK_NOT_FOUND);
 assert(ta_rank_outbox_open(outbox,leaf)==TA_RANK_NOT_FOUND);
 ta_rank_attempt a=attempt(1,0,0,120,1000);
 assert(ta_rank_commit_local(book,&a,NULL)==TA_RANK_OK);
 assert(ta_rank_outbox_enqueue(outbox,&a)==TA_RANK_OK);
 assert(ta_rank_store_open(book,leaf)==TA_RANK_OK);
 assert(ta_rank_outbox_open(outbox,leaf)==TA_RANK_OK);
 leaf_remove(book->directory,book->basename);
 leaf_remove(outbox->directory,outbox->basename);
 ta_rank_destroy(book);
 ta_rank_outbox_destroy(outbox);
 assert(!chmod(parent,0700) && !rmdir(leaf) && !rmdir(parent));
 free(parent);
 puts("search-only Android parent: board and outbox commit and reload PASS");
#endif
}
static void store_tests(void){
 char *path=new_directory();ta_rank_context *ctx=ta_rank_create(rules,physics);assert(ta_rank_store_open(ctx,path)==TA_RANK_NOT_FOUND);
 ta_rank_attempt a=attempt(1,0,0,120,1000);ta_rank_submission out;
 assert(ta_rank_commit_local(ctx,&a,&out)==TA_RANK_OK);ta_rank_view v;assert(ta_rank_view_local(ctx,0,0,1,&v)==TA_RANK_OK&&v.real_count==1);
 size_t bytes;unsigned char *original=read_leaf(ctx->directory,ctx->basename,&bytes);uint64_t generation=v.generation;
 const int rollback_faults[4]={1,2,3,6};
 for(unsigned f=0;f<4;f++){a=attempt(10+f,0,0,110,1000);fault=rollback_faults[f];assert(ta_rank_commit_local(ctx,&a,&out)==TA_RANK_IO);fault=0;
  size_t n;unsigned char *p=read_leaf(ctx->directory,ctx->basename,&n);assert(n==bytes&&!memcmp(p,original,n));free(p);
  assert(ta_rank_view_local(ctx,0,0,1,&v)==TA_RANK_OK&&v.real_count==1&&v.generation==generation);
 }
 a=attempt(20,0,0,110,1000);fault=4;assert(ta_rank_commit_local(ctx,&a,&out)==TA_RANK_COMMITTED_UNSYNCED);fault=0;
 assert(ta_rank_view_local(ctx,0,0,1,&v)==TA_RANK_OK&&v.real_count==2);
 ta_rank_context *loaded=ta_rank_create(rules,physics);fault=5;assert(ta_rank_store_open(loaded,path)==TA_RANK_IO);fault=0;
 assert(ta_rank_view_local(loaded,0,0,1,&v)==TA_RANK_OK&&v.real_count==0);
 assert(ta_rank_store_open(loaded,path)==TA_RANK_OK);
 assert(ta_rank_view_local(loaded,0,0,1,&v)==TA_RANK_OK&&v.real_count==2&&v.rows[0].display_ms==110000);
 a=attempt(21,0,0,100,1000);assert(ta_rank_submit_local(loaded,&a,&out)==TA_RANK_OK);assert(ta_rank_commit_local(loaded,&a,&out)==TA_RANK_STALE);ta_rank_destroy(loaded);
 /* Filesystem nanoseconds are part of the mutation token, not second-only checks. */
 struct stat x=ctx->expected,y=x;
#if defined(__APPLE__)
 y.st_ctimespec.tv_nsec^=1;
#else
 y.st_ctim.tv_nsec^=1;
#endif
 assert(!same_stat(&x,&y));
 /* Replace same owned file after open: refuse commit instead of overwriting. */
 write_leaf(ctx->directory,ctx->basename,original,bytes);a=attempt(30,0,0,90,0);assert(ta_rank_commit_local(ctx,&a,&out)==TA_RANK_STALE);
 ta_rank_store_close(ctx);assert(ta_rank_store_open(ctx,path)==TA_RANK_OK);
 int dir=dup(ctx->directory);assert(dir>=0);char name[160];memcpy(name,ctx->basename,sizeof name);ta_rank_store_close(ctx);
 unsigned char *bad=malloc(bytes);assert(bad);memcpy(bad,original,bytes);bad[HEADER+8]^=1;write_leaf(dir,name,bad,bytes);
 assert(ta_rank_store_open(ctx,path)==TA_RANK_CORRUPT);assert(ta_rank_commit_local(ctx,&a,&out)==TA_RANK_INVALID);
 size_t n;unsigned char *p=read_leaf(dir,name,&n);assert(n==bytes&&!memcmp(p,bad,n));free(p);
 memcpy(bad,original,bytes);put32(bad+8,2);write_leaf(dir,name,bad,bytes);assert(ta_rank_store_open(ctx,path)==TA_RANK_FOREIGN);
 leaf_remove(dir,name);assert(!mkfifoat(dir,name,0600));assert(ta_rank_store_open(ctx,path)==TA_RANK_UNSAFE_PATH);leaf_remove(dir,name);
 write_leaf(dir,"victim",original,bytes);assert(!symlinkat("victim",dir,name));assert(ta_rank_store_open(ctx,path)==TA_RANK_UNSAFE_PATH);
 p=read_leaf(dir,"victim",&n);assert(n==bytes&&!memcmp(p,original,n));free(p);leaf_remove(dir,name);
 assert(!linkat(dir,"victim",dir,name,0));assert(ta_rank_store_open(ctx,path)==TA_RANK_UNSAFE_PATH);leaf_remove(dir,name);
 assert(!symlinkat(path,dir,"alias"));char alias[4096];assert(snprintf(alias,sizeof alias,"%s/alias",path)<(int)sizeof alias);assert(ta_rank_store_open(ctx,alias)==TA_RANK_UNSAFE_PATH);
 /* Distinct full physics hashes get independent files; neither touches legacy PB. */
 uint8_t other[32]={3};ta_rank_context *cohort=ta_rank_create(rules,other);assert(strcmp(cohort->basename,name));assert(ta_rank_store_open(cohort,path)==TA_RANK_NOT_FOUND);ta_rank_destroy(cohort);
 assert(ta_rank_store_open(ctx,"relative")==TA_RANK_UNSAFE_PATH);char dot[4096];assert(snprintf(dot,sizeof dot,"%s/../x",path)<(int)sizeof dot);assert(ta_rank_store_open(ctx,dot)==TA_RANK_UNSAFE_PATH);
 free(bad);free(original);ta_rank_destroy(ctx);assert(!close(dir));printf("store: CRC/version/FIFO/symlink/hardlink/statns/4rollbackfaults/readfailure/committed_unsynced/reload/cohorts PASS (%s)\n",path);free(path);
}
static void full_wire_tests(void){
 char *path=new_directory();ta_rank_context *ctx=ta_rank_create(rules,physics);assert(ta_rank_store_open(ctx,path)==TA_RANK_NOT_FOUND);
 unsigned total=0;ta_rank_submission out;
 for(unsigned c=0;c<15;c++)for(unsigned t=0;t<2;t++)if(ta_rank_course_enabled(c))for(unsigned i=0;i<100;i++){
  ta_rank_attempt a=attempt(i,c,t,100+(float)i,1000+i);assert(ta_rank_submit_local(ctx,&a,&out)==TA_RANK_OK);total++;
 }
 assert(total==2400);unsigned char *data=NULL;size_t bytes=0;assert(encode_model(&ctx->m,&data,&bytes)==TA_RANK_OK&&bytes==HEADER+2400*ROW_BYTES&&bytes<TA_RANK_STORE_MAX_BYTES);
 write_leaf(ctx->directory,ctx->basename,data,bytes);
 ta_rank_context *reload=ta_rank_create(rules,physics);assert(ta_rank_store_open(reload,path)==TA_RANK_OK);ta_rank_view view;
 for(unsigned c=0;c<15;c++)for(unsigned t=0;t<2;t++)if(ta_rank_course_enabled(c)){
  assert(ta_rank_view_local(reload,c,t,1,&view)==TA_RANK_OK&&view.real_count==100);
  for(unsigned i=0;i<10;i++)assert(view.rows[i].source_kind==TA_RANK_SOURCE_LOCAL_UNVERIFIED&&view.rows[i].display_ms==(100+i)*1000);
 }
 model *decoded=calloc(1,sizeof *decoded);assert(decoded);memcpy(decoded->rules,rules,32);memcpy(decoded->physics,physics,32);
 /* Malformed semantic rows with VALID checksums are still rejected. */
 unsigned char *bad=malloc(bytes);assert(bad);
 for(unsigned kind=0;kind<11;kind++){
  memcpy(bad,data,bytes);memset(decoded->count,0,sizeof decoded->count);
  if(kind==0)put32(bad+HEADER+184,TA_RANK_TIME_SENTINEL);
  if(kind==1)put64(bad+HEADER+188,0);
  if(kind==2)memcpy(bad+HEADER+ROW_BYTES+8,bad+HEADER+8,16); /* duplicate owner */
  if(kind==3)memcpy(bad+HEADER+ROW_BYTES+24,bad+HEADER+24,16); /* duplicate attempt */
  if(kind==4)put32(bad+HEADER,5); /* disabled native course */
  if(kind==5)put32(bad+HEADER+152,224); /* noncanonical model alias */
  if(kind==6)put32(bad+HEADER+156,45);
  if(kind==7)put32(bad+HEADER+148,47);
  if(kind==8)put32(bad+HEADER+144,5200);
  if(kind==9)put32(bad+HEADER+88,1); /* reserved field word1 */
  if(kind==10)put32(bad+HEADER+104,1); /* reserved field word5 */
  put32(bad+28,checksum(bad,bytes));assert(decode_model(decoded,bad,bytes)==TA_RANK_CORRUPT);
 }
 free(bad);free(decoded);free(data);ta_rank_destroy(ctx);ta_rank_destroy(reload);free(path);
 puts("wire: 24 enabled partitions/2400rows bounded reload + validCRC semantic corruptions PASS");
}
static void outbox_tests(void){
 char *path=new_directory();ta_rank_outbox *q=ta_rank_outbox_create(rules,physics);assert(q);
 ta_rank_attempt slow=attempt(999,0,0,300,1000),copy;ta_rank_submission sub;
 assert(ta_rank_outbox_enqueue(q,&slow)==TA_RANK_INVALID);assert(ta_rank_outbox_open(q,path)==TA_RANK_NOT_FOUND);
 /* A real finisher outside local top100 MUST still become durable pending. */
 ta_rank_context *book=ta_rank_create(rules,physics);for(unsigned i=0;i<100;i++){ta_rank_attempt a=attempt(i,0,0,100+(float)i,1000);assert(ta_rank_submit_local(book,&a,&sub)==TA_RANK_OK);}
 assert(ta_rank_submit_local(book,&slow,&sub)==TA_RANK_NO_CHANGE&&sub.position==0);
 assert(ta_rank_outbox_enqueue(q,&slow)==TA_RANK_OK&&ta_rank_outbox_count(q)==1);
 uint64_t generation=ta_rank_outbox_generation(q);assert(ta_rank_outbox_copy(q,0,&copy,NULL)==TA_RANK_OK&&equal_attempt(&copy,&slow));
 assert(ta_rank_outbox_enqueue(q,&slow)==TA_RANK_DUPLICATE&&ta_rank_outbox_generation(q)==generation);
 ta_rank_attempt changed=slow;changed.metadata.title_id++;assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_ATTEMPT_CONFLICT);
 ta_rank_attempt faster=attempt(999,0,0,290,1001);faster.attempt[15]=1;
 assert(ta_rank_outbox_enqueue(q,&faster)==TA_RANK_OK&&ta_rank_outbox_count(q)==1);
 size_t n;unsigned char *snapshot=read_leaf(q->directory,q->basename,&n);generation=ta_rank_outbox_generation(q);
 changed=faster;changed.attempt[15]=2;changed.completed_at_ms=2000;
 assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_NO_CHANGE&&ta_rank_outbox_generation(q)==generation);
 changed.native_elapsed_bits=bits(291);assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_NO_CHANGE);
 size_t z;unsigned char *bytes=read_leaf(q->directory,q->basename,&z);assert(z==n&&!memcmp(bytes,snapshot,n));free(bytes);free(snapshot);
 for(unsigned i=0;i<255;i++){ta_rank_attempt a=attempt(i,0,0,100+(float)i,1000);assert(ta_rank_outbox_enqueue(q,&a)==TA_RANK_OK);}
 assert(ta_rank_outbox_count(q)==256);snapshot=read_leaf(q->directory,q->basename,&n);assert(n==PENDING_BYTES);generation=ta_rank_outbox_generation(q);
 changed=attempt(10000,0,0,1,1000);assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_OUTBOX_FULL);
 assert(ta_rank_outbox_count(q)==256&&ta_rank_outbox_generation(q)==generation);
 bytes=read_leaf(q->directory,q->basename,&z);assert(z==n&&!memcmp(bytes,snapshot,n));free(bytes);
 ta_rank_outbox *loaded=ta_rank_outbox_create(rules,physics);assert(ta_rank_outbox_open(loaded,path)==TA_RANK_OK&&ta_rank_outbox_count(loaded)==256);
 assert(ta_rank_outbox_copy(loaded,0,&copy,&generation)==TA_RANK_OK&&equal_attempt(&copy,&faster));assert(ta_rank_outbox_copy(loaded,256,&copy,NULL)==TA_RANK_NOT_FOUND);ta_rank_outbox_destroy(loaded);
 changed=faster;changed.native_elapsed_bits=bits(280);changed.attempt[15]=3;
 const int failures[4]={1,2,3,6};generation=ta_rank_outbox_generation(q);
 for(unsigned i=0;i<4;i++){
  fault=failures[i];assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_IO);fault=0;
  assert(ta_rank_outbox_generation(q)==generation&&ta_rank_outbox_count(q)==256);
  bytes=read_leaf(q->directory,q->basename,&z);assert(z==n&&!memcmp(bytes,snapshot,n));free(bytes);
 }
 fault=4;assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_COMMITTED_UNSYNCED);fault=0;
 assert(ta_rank_outbox_count(q)==256&&ta_rank_outbox_copy(q,0,&copy,NULL)==TA_RANK_OK&&equal_attempt(&copy,&changed));
 assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_DUPLICATE);
 uint8_t foreign[32]={3};loaded=ta_rank_outbox_create(rules,foreign);assert(strcmp(q->basename,loaded->basename));assert(ta_rank_outbox_open(loaded,path)==TA_RANK_NOT_FOUND);ta_rank_outbox_destroy(loaded);
 /* Modified same-inode state cannot be overwritten, including nanosecond token. */
 write_leaf(q->directory,q->basename,snapshot,n);changed.native_elapsed_bits=bits(270);changed.attempt[15]=4;assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_STALE);
 int dir=dup(q->directory);assert(dir>=0);char name[160];memcpy(name,q->basename,sizeof name);pending_close(q);
 unsigned char *bad=malloc(n);assert(bad);memcpy(bad,snapshot,n);bad[HEADER+8]^=1;write_leaf(dir,name,bad,n);assert(ta_rank_outbox_open(q,path)==TA_RANK_CORRUPT);assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_INVALID);
 bytes=read_leaf(dir,name,&z);assert(z==n&&!memcmp(bytes,bad,n));free(bytes);
 memcpy(bad,snapshot,n);bad[32]^=1;put32(bad+28,checksum(bad,n));write_leaf(dir,name,bad,n);assert(ta_rank_outbox_open(q,path)==TA_RANK_FOREIGN);
 memcpy(bad,snapshot,n);memcpy(bad+HEADER+ROW_BYTES+8,bad+HEADER+8,16);put32(bad+28,checksum(bad,n));write_leaf(dir,name,bad,n);assert(ta_rank_outbox_open(q,path)==TA_RANK_CORRUPT);
 for(unsigned k=0;k<6;k++){
  const unsigned offsets[6]={152,156,148,144,88,104};const uint32_t values[6]={247,45,47,0,1,1};
  memcpy(bad,snapshot,n);put32(bad+HEADER+offsets[k],values[k]);put32(bad+28,checksum(bad,n));write_leaf(dir,name,bad,n);assert(ta_rank_outbox_open(q,path)==TA_RANK_CORRUPT);
 }
 leaf_remove(dir,name);assert(!mkfifoat(dir,name,0600));assert(ta_rank_outbox_open(q,path)==TA_RANK_UNSAFE_PATH);leaf_remove(dir,name);
 write_leaf(dir,"queue-victim",snapshot,n);assert(!symlinkat("queue-victim",dir,name));assert(ta_rank_outbox_open(q,path)==TA_RANK_UNSAFE_PATH);
 bytes=read_leaf(dir,"queue-victim",&z);assert(z==n&&!memcmp(bytes,snapshot,n));free(bytes);leaf_remove(dir,name);
 write_leaf(dir,name,snapshot,n);fault=5;assert(ta_rank_outbox_open(q,path)==TA_RANK_IO);fault=0;assert(ta_rank_outbox_open(q,path)==TA_RANK_OK);
 changed=faster;changed.native_elapsed_bits=bits(270);changed.attempt[15]=5;q->m.sequence=UINT64_MAX;assert(ta_rank_outbox_enqueue(q,&changed)==TA_RANK_EXHAUSTED);
 free(snapshot);free(bad);ta_rank_outbox_destroy(q);ta_rank_destroy(book);assert(!close(dir));free(path);
 puts("outbox: >top100 finisher durable,256full preserved,strictowner/dedupe/reload/cohorts/CRC/FIFO/symlink/statns/4rollbackfaults/committed_unsynced PASS");
}
static void metadata_bounds_tests(void){
 ta_rank_context *book=ta_rank_create(rules,physics);ta_rank_outbox *q=ta_rank_outbox_create(rules,physics);char *path=new_directory();assert(ta_rank_outbox_open(q,path)==TA_RANK_NOT_FOUND);
 for(unsigned k=0;k<10;k++){
  ta_rank_attempt a=attempt(999,0,0,120,0);ta_rank_submission sub;
  switch(k){case 0:a.metadata.model_id=247;break;case 1:a.metadata.model_id=224;break;case 2:a.metadata.model_id=231;break;case 3:a.metadata.car_type=45;break;case 4:a.metadata.class_id=47;break;case 5:a.metadata.title_id=0;break;case 6:a.metadata.title_id=5200;break;case 7:a.race_field[1]=1;break;case 8:a.race_field[5]=1;break;case 9:a.metadata.model_id=UINT32_MAX;break;}
  assert(ta_rank_submit_local(book,&a,&sub)==TA_RANK_INVALID);assert(ta_rank_outbox_enqueue(q,&a)==TA_RANK_INVALID);assert(ta_rank_outbox_count(q)==0);
 }
 for(unsigned i=0;i<3;i++){
  ta_rank_attempt a=attempt(i,0,0,120+(float)i,0);a.metadata.model_id=246;a.metadata.car_type=42+i;a.metadata.class_id=46;a.metadata.title_id=5149;
  assert(ta_rank_submit_local(book,&a,NULL)==TA_RANK_OK);assert(ta_rank_outbox_enqueue(q,&a)==TA_RANK_OK);
 }
 ta_rank_outbox_destroy(q);ta_rank_destroy(book);free(path);puts("shared metadata: canonical model<247/noaliases224..231,type<45,class<47,title1..5199,reserved field zero direct+wire+outbox PASS");
}
static void community_tests(void) {
  ta_rank_attempt slow=attempt(2,0,0,181.203f,1000),fast=slow,copy;
  fast.attempt[15]=1;fast.native_elapsed_bits=bits(170.0f);
  fast.metadata.original_id_valid=1;fast.metadata.original_id1=123;
  uint8_t board[8+TA_RANK_COMMUNITY_ROW_BYTES]={'C','T','B','1',1};
  assert(ta_rank_community_encode(&fast,board+8));
  ta_rank_view view;
  assert(ta_rank_community_board(board,sizeof board,&fast.partition,&view));
  assert(view.source_kind==TA_RANK_SOURCE_COMMUNITY_UNVERIFIED && view.row_count==1);
  assert(view.rows[0].display_ms==170000 && !view.rows[0].record.attempt.metadata.original_id1);
  assert(!ta_rank_community_board(board,sizeof board-1,&fast.partition,&view));
  board[8+36]^=1;
  assert(!ta_rank_community_board(board,sizeof board,&fast.partition,&view));

  char *dir=new_directory();ta_rank_outbox *q=ta_rank_outbox_create(rules,physics);
  assert(ta_rank_outbox_open(q,dir)==TA_RANK_NOT_FOUND);
  assert(ta_rank_outbox_enqueue(q,&slow)==TA_RANK_OK);
  assert(ta_rank_outbox_enqueue(q,&fast)==TA_RANK_OK);
  assert(ta_rank_outbox_ack(q,slow.attempt)==TA_RANK_NOT_FOUND);
  fault=3;assert(ta_rank_outbox_ack(q,fast.attempt)==TA_RANK_IO);fault=0;
  assert(ta_rank_outbox_copy(q,0,&copy,NULL)==TA_RANK_OK && equal_attempt(&copy,&fast));
  assert(ta_rank_outbox_ack(q,fast.attempt)==TA_RANK_OK);
  assert(ta_rank_outbox_open(q,dir)==TA_RANK_OK && !ta_rank_outbox_count(q));
  leaf_remove(q->directory,q->basename);ta_rank_outbox_destroy(q);assert(!rmdir(dir));free(dir);
  puts("community wire, no private serials, and durable exact-ID outbox ack PASS");
}
int main(void){model_tests();search_only_parent_test();store_tests();full_wire_tests();outbox_tests();metadata_bounds_tests();community_tests();puts("TA rank production leaf tests PASS");return 0;}
