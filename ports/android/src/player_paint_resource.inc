/* Include ONCE at end of ghost_catalog.c to reuse its bounded streaming SHA,
 * pread and nanosecond fd-identity helpers. No old Ghost symbols/logic change. */
#include "player_paint_resource.h"
#include "player_paint_profile_private.h"
struct player_paint_resource {int fd;struct stat identity;};
static int ppr_read(void*ctx,uint64_t off,void*out,size_t n){
 player_paint_resource*r=ctx;struct stat st;
 if(!r||(!out&&n)||off>PLAYER_PAINT_PROFILE_BYTES||n>PLAYER_PAINT_PROFILE_BYTES-off||fstat(r->fd,&st)||!same_stat(&st,&r->identity))return 0;
 if(!read_at(r->fd,out,n,off)||fstat(r->fd,&st)||!same_stat(&st,&r->identity)){if(out)memset(out,0,n);return 0;}return 1;
}
static int ppr_verify(void*ctx,uint64_t off,uint64_t n,const uint8_t expected[32]){
 player_paint_resource*r=ctx;uint8_t b[65536],digest[32];sha256_ctx sha;
 if(!r||!expected||off>PLAYER_PAINT_PROFILE_BYTES||n>PLAYER_PAINT_PROFILE_BYTES-off)return 0;
 sha_init(&sha);for(uint64_t at=0;at<n;){size_t size=(size_t)(n-at);if(size>sizeof b)size=sizeof b;if(!ppr_read(r,off+at,b,size))return 0;sha_update(&sha,b,size);at+=size;}sha_final(&sha,digest);return !memcmp(digest,expected,32);
}
void player_paint_resource_close(player_paint_resource*r){if(r){if(r->fd>=0)close(r->fd);memset(r,0,sizeof *r);free(r);}}
int player_paint_resource_open_main(int root,player_paint_resource**out){
 if(out)*out=NULL;if(!out||root<0)return 0;
 struct stat dir;if(fstat(root,&dir)||!S_ISDIR(dir.st_mode))return 0;
 int fd=openat(root,"player-body-paints.bin",O_RDONLY|O_NOFOLLOW|O_NONBLOCK);if(fd<0)return 0;
 player_paint_resource*r=calloc(1,sizeof *r);if(!r){close(fd);return 0;}r->fd=fd;
 static const uint8_t expected[32]=PLAYER_PAINT_PROFILE_SHA256;
 if(fstat(fd,&r->identity)||!S_ISREG(r->identity.st_mode)||r->identity.st_size!=PLAYER_PAINT_PROFILE_BYTES||!ppr_verify(r,0,PLAYER_PAINT_PROFILE_BYTES,expected)){player_paint_resource_close(r);return 0;}
 *out=r;return 1;
}
int player_paint_resource_source(player_paint_resource*r,ghost_asset_source*out){
 if(out)memset(out,0,sizeof *out);struct stat st;if(!r||!out||fstat(r->fd,&st)||!same_stat(&st,&r->identity))return 0;
 static const uint8_t expected[32]=PLAYER_PAINT_PROFILE_SHA256;
 out->context=r;out->length=PLAYER_PAINT_PROFILE_BYTES;memcpy(out->sha256,expected,32);
 out->read_at=ppr_read;out->verify_sha256=ppr_verify;out->sha256_bytes=ghost_catalog_sha256_bytes;return 1;
}
