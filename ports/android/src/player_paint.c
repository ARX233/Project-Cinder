/* Original-pixel capability reader; no filesystem/GL/original Lua dependencies. */
#include "player_paint.h"
/* APK/build-private metadata, never generated from the runtime file being opened. */
#include "player_paint_profile_private.h"
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
struct player_paint_reader { player_paint_source source; size_t count; player_paint_page *pages; };
static uint16_t gp_u16(const uint8_t*p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
static uint32_t gp_u32(const uint8_t*p){return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static uint64_t gp_u64(const uint8_t*p){return gp_u32(p)|((uint64_t)gp_u32(p+4)<<32);}
static int gp_zero(const uint8_t*p,size_t n){uint8_t x=0;for(size_t i=0;i<n;i++)x|=p[i];return !x;}
static int gp_keycmp(player_paint_key a,player_paint_key b){if(a.pack!=b.pack)return a.pack<b.pack?-1:1;if(a.custom_color!=b.custom_color)return a.custom_color<b.custom_color?-1:1;if(a.aero!=b.aero)return a.aero<b.aero?-1:1;return 0;}
static int gp_keyvalid(player_paint_key k){return k.pack<55&&k.custom_color>=1&&k.custom_color<=10&&k.aero<=3;}
static int gp_ascii(const uint8_t*p,size_t n,int path){
 size_t i=0,segment=0;if(!p[0])return 0;
 for(;i<n&&p[i];i++){
  unsigned c=p[i];int normal=(c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='.';
  if(path&&c=='/'){if(!segment||(segment==1&&p[i-1]=='.')||(segment==2&&p[i-1]=='.'&&p[i-2]=='.'))return 0;segment=0;}
  else {if(!normal)return 0;segment++;}
 }
 if(i==n||!segment||(segment==1&&p[i-1]=='.')||(segment==2&&p[i-1]=='.'&&p[i-2]=='.'))return 0;
 return gp_zero(p+i,n-i);
}
static int gp_read(const player_paint_source*s,uint64_t off,void*dst,size_t n){return off<=s->length&&(uint64_t)n<=s->length-off&&s->read_at(s->context,off,dst,n);}

player_paint_result player_paint_open(const player_paint_source *s,player_paint_reader **out){
 uint8_t h[128],r[320];player_paint_reader*c=NULL;player_paint_result e=PLAYER_PAINT_SHAPE;
 if(out)*out=NULL;
 if(!out||!s||!s->read_at||!s->verify_sha256||!s->sha256_bytes||gp_zero(s->sha256,32))return PLAYER_PAINT_ARGUMENT;
 if(s->length<128||s->length>PLAYER_PAINT_MAX_SECTION)return PLAYER_PAINT_SHAPE;
 static const uint8_t approved_sha[32]=PLAYER_PAINT_PROFILE_SHA256;
 if(s->length!=PLAYER_PAINT_PROFILE_BYTES||memcmp(s->sha256,approved_sha,32))return PLAYER_PAINT_HASH;
 if(!s->verify_sha256(s->context,0,s->length,s->sha256))return PLAYER_PAINT_HASH;
 if(!gp_read(s,0,h,sizeof h))return PLAYER_PAINT_IO;
 uint32_t count=gp_u32(h+20);uint64_t start=128u+(uint64_t)count*320u;
 if(memcmp(h,"WPPAINT1",8)||gp_u32(h+8)!=1||gp_u32(h+12)!=128||gp_u32(h+16)!=320||
  !count||count>PLAYER_PAINT_MAX_RECORDS||gp_u32(h+24)!=PLAYER_PAINT_MAX_DIM||gp_u32(h+28)!=1||
  gp_u64(h+32)!=128||gp_u64(h+40)!=start||gp_u64(h+48)!=s->length||start>s->length||
  gp_zero(h+56,32)||gp_zero(h+88,32)||gp_u32(h+120)!=1||gp_u32(h+124)!=1)return PLAYER_PAINT_SHAPE;
 static const uint8_t approved_readset[32]=PLAYER_PAINT_PROFILE_READSET_SHA256;
 if(count!=PLAYER_PAINT_PROFILE_RECORDS||memcmp(h+56,approved_readset,32))return PLAYER_PAINT_HASH;
 /* This section is specifically derived from the caller-selected original main,
  * not an arbitrary namespace with numerically identical model/pack IDs. */
 static const uint8_t main_sha[32]={0x2e,0x65,0x91,0x15,0x3d,0x7e,0x59,0x94,0x37,0x46,0x5f,0x73,0x6a,0x42,0xe2,0x7b,0x01,0xa3,0xb5,0x6c,0x88,0x1b,0xee,0x58,0x36,0x5f,0xb2,0x1d,0x06,0x78,0xb1,0xf6};
 if(memcmp(h+88,main_sha,32))return PLAYER_PAINT_HASH;
 c=calloc(1,sizeof *c);if(!c)return PLAYER_PAINT_MEMORY;
 c->source=*s;c->count=count;c->pages=calloc(count,sizeof *c->pages);if(!c->pages){e=PLAYER_PAINT_MEMORY;goto bad;}
 for(uint32_t i=0;i<count;i++){
  if(!gp_read(s,128u+(uint64_t)i*320,r,sizeof r)){e=PLAYER_PAINT_IO;goto bad;}
  player_paint_page*p=c->pages+i;
  p->key=(player_paint_key){gp_u16(r),r[2],r[3]};p->page=r[4];p->alpha_present=r[5];p->width=gp_u16(r+6);p->height=gp_u16(r+8);
  p->raw_size=gp_u32(r+12);p->compressed_size=gp_u32(r+16);p->crc32=gp_u32(r+20);p->compressed_offset=gp_u64(r+24);
  memcpy(p->rgba_sha256,r+32,32);memcpy(p->source_sha256,r+64,32);memcpy(p->lua_sha256,r+96,32);memcpy(p->material,r+128,48);memcpy(p->source_path,r+176,128);
  if(!gp_keyvalid(p->key)||p->page<1||p->page>3||p->alpha_present>1||!p->width||!p->height||p->width>2048||p->height>2048||
   gp_u16(r+10)||p->raw_size!=(uint32_t)p->width*p->height*4u||p->raw_size>PLAYER_PAINT_MAX_IMAGE||
   !p->compressed_size||p->compressed_size>(uint64_t)compressBound(p->raw_size)||p->compressed_offset>start||
   p->compressed_offset<gp_u64(h+40)||p->compressed_offset>s->length||p->compressed_size>s->length-p->compressed_offset||gp_zero(r+32,32)||gp_zero(r+64,32)||gp_zero(r+96,32)||
   !gp_ascii(r+128,48,0)||!gp_ascii(r+176,128,1)||memcmp(r+176,"data/car/",9)||!gp_zero(r+304,16))goto bad;
  if(i){player_paint_page*q=p-1;int cmp=gp_keycmp(q->key,p->key);if(cmp>0||(cmp==0&&q->page>=p->page)||(cmp<0&&p->page!=1))goto bad;
   if(cmp==0){if(!strcmp(q->material,p->material))goto bad;for(size_t j=i;j>0&&gp_keycmp(c->pages[j-1].key,p->key)==0;j--)if(!strcmp(c->pages[j-1].material,p->material))goto bad;}
  }else if(p->page!=1)goto bad;
  if(p->compressed_offset==start){start+=p->compressed_size;}else{
   /* Only an exact previously admitted pixel interval may alias. Partial overlap,
    * different dimensions/alpha/hash/CRC, gaps and forward references fail closed. */
   int alias=0;for(uint32_t j=0;j<i;j++){
    const player_paint_page*q=c->pages+j;
    if(q->compressed_offset==p->compressed_offset&&q->compressed_size==p->compressed_size&&
       q->raw_size==p->raw_size&&q->width==p->width&&q->height==p->height&&
       q->alpha_present==p->alpha_present&&q->crc32==p->crc32&&!memcmp(q->rgba_sha256,p->rgba_sha256,32)){alias=1;break;}
   }if(!alias)goto bad;
  }
 }
 if(start!=s->length)goto bad;
 *out=c;return PLAYER_PAINT_OK;
 bad:player_paint_close(c);return e;
}
void player_paint_close(player_paint_reader*c){if(c){free(c->pages);memset(c,0,sizeof *c);free(c);}}
player_paint_result player_paint_lookup(const player_paint_reader*c,player_paint_key key,const player_paint_page**pages,size_t*count){
 if(pages)*pages=NULL;if(count)*count=0;
 if(!c||!pages||!count||!gp_keyvalid(key))return PLAYER_PAINT_ARGUMENT;
 size_t lo=0,hi=c->count;while(lo<hi){size_t m=lo+(hi-lo)/2;if(gp_keycmp(c->pages[m].key,key)<0)lo=m+1;else hi=m;}
 if(lo==c->count||gp_keycmp(c->pages[lo].key,key))return PLAYER_PAINT_ABSENT;
 size_t n=0;while(lo+n<c->count&&!gp_keycmp(c->pages[lo+n].key,key))n++;
 if(!n||n>3)return PLAYER_PAINT_SHAPE;
 *pages=c->pages+lo;*count=n;return PLAYER_PAINT_OK;
}
player_paint_result player_paint_read_rgba(const player_paint_reader*c,const player_paint_page*p,uint8_t**rgba,size_t*bytes){
 uint8_t*zip=NULL,*raw=NULL;player_paint_result e=PLAYER_PAINT_SHAPE;z_stream z;uint8_t digest[32];int own=0;
 if(rgba)*rgba=NULL;if(bytes)*bytes=0;
 if(!c||!p||!rgba||!bytes)return PLAYER_PAINT_ARGUMENT;
 /* Equality checks avoid relational comparison of unrelated C object pointers. */
 for(size_t i=0;i<c->count;i++)if(p==c->pages+i){own=1;break;}
 if(!own)return PLAYER_PAINT_ARGUMENT;
 zip=malloc(p->compressed_size);raw=malloc(p->raw_size);if(!zip||!raw){e=PLAYER_PAINT_MEMORY;goto done;}
 if(!gp_read(&c->source,p->compressed_offset,zip,p->compressed_size)){e=PLAYER_PAINT_IO;goto done;}
 memset(&z,0,sizeof z);z.next_in=zip;z.avail_in=p->compressed_size;z.next_out=raw;z.avail_out=p->raw_size;
 if(inflateInit(&z)!=Z_OK){e=PLAYER_PAINT_MEMORY;goto done;}
 int rc=inflate(&z,Z_FINISH);int good=rc==Z_STREAM_END&&z.total_in==p->compressed_size&&z.total_out==p->raw_size&&z.avail_in==0;
 inflateEnd(&z);if(!good)goto done;
 c->source.sha256_bytes(raw,p->raw_size,digest);
 if(memcmp(digest,p->rgba_sha256,32)||(uint32_t)crc32(0,raw,p->raw_size)!=p->crc32){e=PLAYER_PAINT_HASH;goto done;}
 int alpha=0;for(size_t i=3;i<p->raw_size;i+=4)if(raw[i]!=255){alpha=1;break;}
 if(alpha!=p->alpha_present)goto done;
 *rgba=raw;*bytes=p->raw_size;raw=NULL;e=PLAYER_PAINT_OK;
 done:free(zip);free(raw);return e;
}
int player_paint_hash_bytes(const player_paint_reader*c,const void*bytes,size_t n,uint8_t out[32]){
 if(out)memset(out,0,32);if(!c||!bytes||!n||n>PLAYER_PAINT_MAX_IMAGE||!out)return 0;
 c->source.sha256_bytes(bytes,n,out);return 1;
}
const char *player_paint_error(player_paint_result e){static const char*const names[]={"ok","argument","io","hash","shape","memory","absent"};return (unsigned)e<sizeof names/sizeof names[0]?names[e]:"unknown";}
