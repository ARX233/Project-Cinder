#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include "ghost_catalog.h"
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#ifndef O_NOFOLLOW
#error "ghost_catalog requires O_NOFOLLOW"
#endif
/* Small local SHA-256, used for external bank approval and selected raw trails. */
typedef struct { uint32_t h[8]; uint64_t n; unsigned used; unsigned char b[64]; } sha256_ctx;
static uint32_t ror(uint32_t x,unsigned n){return(x>>n)|(x<<(32-n));}
static void sha_block(sha256_ctx *c,const unsigned char *b){
 static const uint32_t k[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
 uint32_t w[64];for(unsigned i=0;i<16;i++)w[i]=((uint32_t)b[4*i]<<24)|((uint32_t)b[4*i+1]<<16)|((uint32_t)b[4*i+2]<<8)|b[4*i+3];
 for(unsigned i=16;i<64;i++){uint32_t x=w[i-15],y=w[i-2];w[i]=w[i-16]+(ror(x,7)^ror(x,18)^(x>>3))+w[i-7]+(ror(y,17)^ror(y,19)^(y>>10));}
 uint32_t a=c->h[0],d=c->h[3],b0=c->h[1],cc=c->h[2],e=c->h[4],f=c->h[5],g=c->h[6],h=c->h[7];
 for(unsigned i=0;i<64;i++){uint32_t t=h+(ror(e,6)^ror(e,11)^ror(e,25))+((e&f)^(~e&g))+k[i]+w[i];uint32_t u=(ror(a,2)^ror(a,13)^ror(a,22))+((a&b0)^(a&cc)^(b0&cc));h=g;g=f;f=e;e=d+t;d=cc;cc=b0;b0=a;a=t+u;}
 c->h[0]+=a;c->h[1]+=b0;c->h[2]+=cc;c->h[3]+=d;c->h[4]+=e;c->h[5]+=f;c->h[6]+=g;c->h[7]+=h;
}
static void sha_init(sha256_ctx*c){static const uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};memset(c,0,sizeof *c);memcpy(c->h,h,sizeof h);}
static void sha_update(sha256_ctx*c,const void*data,size_t n){const unsigned char*p=data;c->n+=n;while(n){size_t k=64-c->used;if(k>n)k=n;memcpy(c->b+c->used,p,k);c->used+=(unsigned)k;p+=k;n-=k;if(c->used==64){sha_block(c,c->b);c->used=0;}}}
static void sha_final(sha256_ctx*c,unsigned char out[32]){uint64_t bits=c->n*8;unsigned char tail[128]={0x80};unsigned n=c->used<56?56-c->used:120-c->used;for(unsigned i=0;i<8;i++)tail[n+i]=(unsigned char)(bits>>(56-8*i));sha_update(c,tail,n+8);for(unsigned i=0;i<8;i++)for(unsigned j=0;j<4;j++)out[4*i+j]=(unsigned char)(c->h[i]>>(24-8*j));}
void ghost_catalog_sha256_bytes(const void*data,size_t n,uint8_t out[32]){if(!out)return;if(!data&&n){memset(out,0,32);return;}sha256_ctx c;sha_init(&c);sha_update(&c,data,n);sha_final(&c,out);}
static uint32_t u32(const unsigned char*p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static uint64_t u64(const unsigned char*p){return u32(p)|((uint64_t)u32(p+4)<<32);}
static int read_at(int fd,void*out,size_t n,uint64_t off){unsigned char*p=out;while(n){ssize_t k=pread(fd,p,n,(off_t)off);if(k<=0)return 0;p+=k;n-=(size_t)k;off+=(size_t)k;}return 1;}
static int same_stat(const struct stat*a,const struct stat*b){
 if(a->st_dev!=b->st_dev||a->st_ino!=b->st_ino||a->st_size!=b->st_size||a->st_mtime!=b->st_mtime||a->st_ctime!=b->st_ctime)return 0;
#ifdef __APPLE__
 return a->st_mtimespec.tv_nsec==b->st_mtimespec.tv_nsec&&a->st_ctimespec.tv_nsec==b->st_ctimespec.tv_nsec;
#else
 return a->st_mtim.tv_nsec==b->st_mtim.tv_nsec&&a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;
#endif
}
struct ghost_catalog {int fd;struct stat identity;uint64_t paint_offset,paint_length;uint8_t paint_sha256[32];ghost_catalog_record_view records[196];ghost_catalog_trail blobs[1000];};
static int idcmp(const ghost_catalog_record_view*a,const ghost_catalog_record_view*b){if(a->id_devel!=b->id_devel)return a->id_devel<b->id_devel?-1:1;if(a->id1!=b->id1)return a->id1<b->id1?-1:1;return a->id2<b->id2?-1:a->id2!=b->id2;}
void ghost_catalog_close(ghost_catalog*c){if(!c)return;if(c->fd>=0)close(c->fd);for(unsigned i=0;i<196;i++)free((void*)c->records[i].globals);free(c);}
unsigned ghost_catalog_version(const ghost_catalog*c){return c?2:0;}
static int paint_read_at(void*context,uint64_t off,void*out,size_t n){const ghost_catalog*c=context;struct stat st;if(!c||(!out&&n)||off>c->paint_length||n>c->paint_length-off||fstat(c->fd,&st)||!same_stat(&st,&c->identity))return 0;if(!read_at(c->fd,out,n,c->paint_offset+off)||fstat(c->fd,&st)||!same_stat(&st,&c->identity)){if(out)memset(out,0,n);return 0;}return 1;}
static int paint_verify_sha256(void*context,uint64_t off,uint64_t n,const uint8_t expected[32]){const ghost_catalog*c=context;struct stat st;if(!c||!expected||off>c->paint_length||n>c->paint_length-off||fstat(c->fd,&st)||!same_stat(&st,&c->identity))return 0;uint8_t buffer[65536],hash[32];sha256_ctx sha;sha_init(&sha);for(uint64_t at=0;at<n;){size_t size=(size_t)(n-at);if(size>sizeof buffer)size=sizeof buffer;if(!read_at(c->fd,buffer,size,c->paint_offset+off+at))return 0;sha_update(&sha,buffer,size);at+=size;}sha_final(&sha,hash);return !memcmp(hash,expected,32)&&!fstat(c->fd,&st)&&same_stat(&st,&c->identity);}
ghost_catalog_result ghost_catalog_paint_source(const ghost_catalog*c,ghost_asset_source*out){if(out)memset(out,0,sizeof*out);if(!c||!out)return GHOST_CATALOG_ARGUMENT;if(!c->paint_length)return GHOST_CATALOG_ABSENT;struct stat st;if(fstat(c->fd,&st)||!same_stat(&st,&c->identity))return GHOST_CATALOG_IO;out->context=(void*)c;out->length=c->paint_length;memcpy(out->sha256,c->paint_sha256,32);out->read_at=paint_read_at;out->sha256_bytes=ghost_catalog_sha256_bytes;out->verify_sha256=paint_verify_sha256;return GHOST_CATALOG_OK;}
size_t ghost_catalog_count(const ghost_catalog*c){return c?196:0;}
const ghost_catalog_record_view*ghost_catalog_record(const ghost_catalog*c,size_t i){return c&&i<196?&c->records[i]:NULL;}
const ghost_catalog_record_view*ghost_catalog_lookup(const ghost_catalog*c,uint32_t d,uint32_t a,uint32_t b){if(!c)return NULL;ghost_catalog_record_view key={0};key.id_devel=d;key.id1=a;key.id2=b;size_t lo=0,hi=196;while(lo<hi){size_t m=(lo+hi)/2;int n=idcmp(&c->records[m],&key);if(n==0)return &c->records[m];if(n<0)lo=m+1;else hi=m;}return NULL;}
int ghost_catalog_global(const ghost_catalog_record_view*r,const char*name,uint32_t*v){if(!r||!name||!v)return 0;size_t lo=0,hi=r->global_count;while(lo<hi){size_t m=(lo+hi)/2;int c=strcmp(r->globals[m].name,name);if(!c){*v=r->globals[m].value;return 1;}if(c<0)lo=m+1;else hi=m;}return 0;}
int ghost_catalog_area_has(const ghost_catalog_area*a,ghost_catalog_raw_field f){return a&&(unsigned)f<45&&(a->present_mask&(UINT64_C(1)<<f))!=0;}
const char*ghost_catalog_raw_field_name(ghost_catalog_raw_field f){
#define NAME(n) #n,
 static const char*const names[]={GHOST_CATALOG_AREA_FIELDS(NAME)};
#undef NAME
 return (unsigned)f<45?names[f]:NULL;
}
static int global_is(const ghost_catalog_record_view*r,const char*k,uint32_t v){uint32_t x;return ghost_catalog_global(r,k,&x)&&x==v;}
static int key_ok(const unsigned char*p){unsigned n=0;while(n<64&&p[n]){unsigned char c=p[n];if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(n>0&&((c>='0'&&c<='9')||c=='_'))))return 0;n++;}if(n==0||n==64)return 0;for(;n<64;n++)if(p[n])return 0;return 1;}
ghost_catalog_result ghost_catalog_open_verified(const char*path,const uint8_t expected[32],ghost_catalog**out){
 if(out)*out=NULL;if(!out||!path||!expected)return GHOST_CATALOG_ARGUMENT;
 int fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);if(fd<0)return GHOST_CATALOG_IO;
 ghost_catalog*c=calloc(1,sizeof *c);if(!c){close(fd);return GHOST_CATALOG_MEMORY;}c->fd=fd;
 ghost_catalog_result result=GHOST_CATALOG_SHAPE;unsigned char h[128],hash[32],chunk[65536];struct stat st;
 if(fstat(fd,&c->identity)||!S_ISREG(c->identity.st_mode)||c->identity.st_size<128||c->identity.st_size>GHOST_CATALOG_MAX_FILE){result=GHOST_CATALOG_IO;goto fail;}
 sha256_ctx sha;sha_init(&sha);for(uint64_t pos=0;pos<(uint64_t)c->identity.st_size;){size_t n=(size_t)((uint64_t)c->identity.st_size-pos);if(n>sizeof chunk)n=sizeof chunk;if(!read_at(fd,chunk,n,pos)){result=GHOST_CATALOG_IO;goto fail;}sha_update(&sha,chunk,n);pos+=n;}sha_final(&sha,hash);
 if(memcmp(hash,expected,32)){result=GHOST_CATALOG_HASH;goto fail;}if(fstat(fd,&st)||!same_stat(&st,&c->identity)||!read_at(fd,h,128,0)){result=GHOST_CATALOG_IO;goto fail;}
 static const unsigned char main_sha[32]={0x2e,0x65,0x91,0x15,0x3d,0x7e,0x59,0x94,0x37,0x46,0x5f,0x73,0x6a,0x42,0xe2,0x7b,0x01,0xa3,0xb5,0x6c,0x88,0x1b,0xee,0x58,0x36,0x5f,0xb2,0x1d,0x06,0x78,0xb1,0xf6};
 if(memcmp(h,"WGBANK2\0",8)||u32(h+8)!=2||u32(h+12)!=128||u32(h+16)!=196||u32(h+20)!=8||u32(h+24)!=1000||u32(h+28)!=1267||u32(h+32)!=128||u32(h+36)!=1696||u32(h+40)!=61696||u32(h+48)!=(uint64_t)c->identity.st_size||u32(h+52)!=68||u32(h+56)!=200||memcmp(h+64,main_sha,32))goto fail;
 uint32_t dataoff=u32(h+44),filesize=u32(h+48),paintdir=u32(h+60);if(dataoff<61696||dataoff>8*1024*1024||dataoff>filesize||paintdir<dataoff||paintdir>filesize-64)goto fail;
 unsigned char section[64];if(!read_at(fd,section,64,paintdir)){result=GHOST_CATALOG_IO;goto fail;}c->paint_offset=u64(section+16);c->paint_length=u64(section+24);memcpy(c->paint_sha256,section+32,32);
 if(memcmp(section,"WGPSEC1\0",8)||u32(section+8)!=1||u32(section+12)||c->paint_offset!=(uint64_t)paintdir+64||c->paint_length<128||c->paint_length>128u*1024u*1024u||c->paint_length!=filesize-c->paint_offset)goto fail;
 sha_init(&sha);for(uint64_t at=0;at<c->paint_length;){size_t n=(size_t)(c->paint_length-at);if(n>sizeof chunk)n=sizeof chunk;if(!read_at(fd,chunk,n,c->paint_offset+at)){result=GHOST_CATALOG_IO;goto fail;}sha_update(&sha,chunk,n);at+=n;}sha_final(&sha,hash);if(memcmp(hash,c->paint_sha256,32)){result=GHOST_CATALOG_HASH;goto fail;}
 unsigned char ph[128];if(!read_at(fd,ph,128,c->paint_offset)){result=GHOST_CATALOG_IO;goto fail;}
 uint32_t paint_count=u32(ph+20);if(memcmp(ph,"WGPAINT1",8)||u32(ph+8)!=1||u32(ph+12)!=128||u32(ph+16)!=320||!paint_count||paint_count>1024||u32(ph+24)!=2048||u32(ph+28)!=1||u64(ph+32)!=128||u64(ph+40)!=128u+320u*paint_count||u64(ph+40)>c->paint_length||u64(ph+48)!=c->paint_length||memcmp(ph+88,main_sha,32)||u32(ph+120)!=1||u32(ph+124))goto fail;
 uint64_t pos=dataoff;unsigned char row[60];unsigned char previous[32]={0};unsigned char used[1000]={0};
 for(unsigned i=0;i<1000;i++){if(!read_at(fd,row,60,1696+60*i)){result=GHOST_CATALOG_IO;goto fail;}ghost_catalog_trail*t=&c->blobs[i];t->blob_index=i;t->compressed_offset=u64(row);t->compressed_size=u32(row+8);t->raw_size=u32(row+12);t->crc32=u32(row+16);t->native_stage=u32(row+24);memcpy(t->sha256,row+28,32);
  if(t->compressed_offset!=pos||!t->compressed_size||t->compressed_size>GHOST_MAX_BYTES+1024||t->raw_size<28||t->raw_size>GHOST_MAX_BYTES||u32(row+20)!=1||!t->native_stage||t->compressed_size>paintdir-pos||(i&&memcmp(previous,t->sha256,32)>=0))goto fail;memcpy(previous,t->sha256,32);pos+=t->compressed_size;
 }if(pos!=paintdir)goto fail;
 pos=61696;unsigned refs=0;uint64_t logical=0;
 for(unsigned i=0;i<196;i++){
  unsigned char rd[8],fixed[100];if(!read_at(fd,rd,8,128+8*i)){result=GHOST_CATALOG_IO;goto fail;}uint32_t off=u32(rd),length=u32(rd+4);if(off!=pos||length<100+34*68+1600||length>100+512*68+1600||off>dataoff||length>dataoff-off)goto fail;
  if(!read_at(fd,fixed,100,off)){result=GHOST_CATALOG_IO;goto fail;}ghost_catalog_record_view*r=&c->records[i];r->id_devel=u32(fixed);r->id1=u32(fixed+4);r->id2=u32(fixed+8);for(unsigned j=0;j<5;j++)r->name[j]=(uint16_t)(fixed[12+j*2]|((unsigned)fixed[13+j*2]<<8));r->version_raw=u32(fixed+24);r->original_raw=u32(fixed+28);memcpy(r->source_sha256,fixed+32,32);memcpy(r->config_sha256,fixed+64,32);r->global_count=u32(fixed+96);
  if(fixed[22]||fixed[23]||r->version_raw!=7||r->original_raw||r->global_count<34||r->global_count>512||length!=100+r->global_count*68+1600||(i&&idcmp(&c->records[i-1],r)>=0))goto fail;
  ghost_catalog_scalar*g=calloc(r->global_count,sizeof*g);if(!g){result=GHOST_CATALOG_MEMORY;goto fail;}r->globals=g;
  for(size_t j=0;j<r->global_count;j++){unsigned char raw[68];if(!read_at(fd,raw,68,off+100+68*j)){result=GHOST_CATALOG_IO;goto fail;}if(!key_ok(raw))goto fail;memcpy(g[j].name,raw,64);g[j].value=u32(raw+64);if(j&&strcmp(g[j-1].name,g[j].name)>=0)goto fail;}
  if(!global_is(r,"id_devel_",r->id_devel)||!global_is(r,"id1_",r->id1)||!global_is(r,"id2_",r->id2)||!global_is(r,"ver_",r->version_raw)||!global_is(r,"original_",r->original_raw))goto fail;
  static const char*const nk[5]={"name0_","name1_","name2_","name3_","name4_"};for(unsigned j=0;j<5;j++)if(!global_is(r,nk[j],r->name[j]))goto fail;
  for(unsigned j=0;j<8;j++){unsigned char raw[200];if(!read_at(fd,raw,200,off+100+68*r->global_count+j*200)){result=GHOST_CATALOG_IO;goto fail;}ghost_catalog_area*a=&r->areas[j];a->present_mask=u64(raw);if(a->present_mask>>45||u32(raw+196))goto fail;unsigned k=0;
#define FIELD(n) a->n=u32(raw+8+4*k);if(!(a->present_mask&(UINT64_C(1)<<k))&&a->n)goto fail;k++;
   GHOST_CATALOG_AREA_FIELDS(FIELD)
#undef FIELD
   a->level_comment=(int32_t)u32(raw+188);uint32_t blob=u32(raw+192);if(a->level_comment< -1||a->level_comment>100||!ghost_catalog_area_has(a,GHOST_RAW_trail_size_)||!ghost_catalog_area_has(a,GHOST_RAW_trail_sum_))goto fail;
   a->trail.blob_index=GHOST_CATALOG_NO_BLOB;
   if(blob==GHOST_CATALOG_NO_BLOB){if(a->trail_size_)goto fail;}
   else{if(blob>=1000||a->trail_size_!=c->blobs[blob].raw_size||a->trail_sum_!=c->blobs[blob].crc32)goto fail;a->trail=c->blobs[blob];used[blob]=1;refs++;logical+=a->trail_size_;}
  }pos+=length;
 }if(pos!=dataoff||refs!=1267||logical!=UINT64_C(211479748))goto fail;for(unsigned i=0;i<1000;i++)if(!used[i])goto fail;
 if(fstat(fd,&st)||!same_stat(&st,&c->identity)){result=GHOST_CATALOG_IO;goto fail;}*out=c;return GHOST_CATALOG_OK;
 fail:ghost_catalog_close(c);return result;
}
ghost_catalog_result ghost_catalog_read_trail(const ghost_catalog*c,size_t index,unsigned area,const ghost_format_policy*policy,void**bytes,size_t*size,ghost_format_info*info){
 if(bytes)*bytes=NULL;if(size)*size=0;if(info)memset(info,0,sizeof*info);
 if(!c||index>=196||area>=8||!policy||!bytes||!size||!info)return GHOST_CATALOG_ARGUMENT;
 const ghost_catalog_trail*t=&c->records[index].areas[area].trail;if(t->blob_index==GHOST_CATALOG_NO_BLOB)return GHOST_CATALOG_ABSENT;
 struct stat st;if(fstat(c->fd,&st)||!same_stat(&st,&c->identity))return GHOST_CATALOG_IO;
 unsigned char*z=malloc(t->compressed_size),*raw=malloc(t->raw_size);if(!z||!raw){free(z);free(raw);return GHOST_CATALOG_MEMORY;}ghost_catalog_result result=GHOST_CATALOG_HASH;
 if(!read_at(c->fd,z,t->compressed_size,t->compressed_offset)){result=GHOST_CATALOG_IO;goto done;}
 z_stream stream;memset(&stream,0,sizeof stream);stream.next_in=z;stream.avail_in=t->compressed_size;stream.next_out=raw;stream.avail_out=t->raw_size;
 if(inflateInit(&stream)!=Z_OK){result=GHOST_CATALOG_MEMORY;goto done;}int code=inflate(&stream,Z_FINISH);int valid=code==Z_STREAM_END&&stream.total_in==t->compressed_size&&stream.total_out==t->raw_size&&stream.avail_in==0;inflateEnd(&stream);if(!valid)goto done;
 unsigned char hash[32];sha256_ctx sha;sha_init(&sha);sha_update(&sha,raw,t->raw_size);sha_final(&sha,hash);if(memcmp(hash,t->sha256,32)||(uint32_t)crc32(0,raw,t->raw_size)!=t->crc32)goto done;
 if(fstat(c->fd,&st)||!same_stat(&st,&c->identity)){result=GHOST_CATALOG_IO;goto done;}
 if(ghost_format_validate(raw,t->raw_size,policy,info)!=GHOST_FORMAT_OK || info->stage!=t->native_stage){result=GHOST_CATALOG_NATIVE;memset(info,0,sizeof*info);goto done;}
 *bytes=raw;*size=t->raw_size;raw=NULL;result=GHOST_CATALOG_OK;
 done:free(z);free(raw);return result;
}
const char*ghost_catalog_error(ghost_catalog_result r){static const char*const e[]={"ok","argument","file changed/unavailable","digest mismatch","bank shape","memory","trail absent","native policy rejected"};return (unsigned)r<sizeof e/sizeof*e?e[r]:"unknown";}
/* Independent pinned MAIN-member capability; reuses only the streaming hash/FD helpers. */
#include "player_paint_resource.inc"
