/* Private typed selected-opponent cache and transactional draw override. */
#include "render.h"
#include "ghost_paint.h"
#include "render_ghost_paint.h"
#include "app_ghost_paint.h"
#include <stdlib.h>
#include <string.h>
static int agp_same(ghost_paint_key a,ghost_paint_key b){return a.pack==b.pack&&a.custom_color==b.custom_color&&a.aero==b.aero;}
static int agp_scene(const wpk_scene*s){return s&&s->n_tex&&s->n_tex<=65535&&s->textures&&s->tex_alpha&&s->n_batch&&s->n_batch<=65536&&s->batches&&s->tex_tbl;}
static int agp_indices(const app_ghost_paint_cache*c,const wpk_scene*s,int idx[3]){
 if(!agp_scene(s))return 0;
 for(size_t i=0;i<c->count;i++){
  idx[i]=wpk_find_texture(s,c->pages[i].material);
  if(idx[i]<0||(uint32_t)idx[i]>=s->n_tex||!s->textures[idx[i]]||!c->texture[i])return 0;
  for(size_t j=0;j<i;j++)if(idx[i]==idx[j])return 0;
  /* A real body page must be referenced by a material, not an unused name that
   * could let preGO pass while the actual geometry keeps the base appearance. */
  int referenced=0;
  for(uint32_t b=0;b<s->n_batch;b++)if(s->batches[b].count&&(s->batches[b].tex==idx[i]||s->batches[b].env==idx[i]||s->batches[b].spec==idx[i])){referenced=1;break;}
  if(!referenced)return 0;
 }
 return 1;
}
int app_ghost_paint_clear(app_ghost_paint_cache*c,int lost){
 if(!c||c->applying)return 0;
 if(!lost)for(size_t i=0;i<c->count;i++)render_ghost_paint_destroy(c->texture[i]);
 free(c->batch_restore);memset(c,0,sizeof *c);return 1;
}
int app_ghost_paint_ready(const app_ghost_paint_cache*c,ghost_paint_key key,uint64_t generation,const wpk_scene*s,uint32_t vinyl,uint32_t bonnet){
 int idx[3];return c&&c->prepared&&!c->applying&&c->context_generation==generation&&generation&&c->scene==s&&c->vinyl==vinyl&&c->bonnet==bonnet&&
  agp_same(c->key,key)&&agp_scene(s)&&s->n_batch<=c->batch_capacity&&(!key.custom_color||agp_indices(c,s,idx));
}
static int agp_overlay_fingerprint(const ghost_paint_reader*r,uint32_t vinyl,uint32_t bonnet,const ghost_paint_overlay*o,uint8_t out[32]){
 memset(out,0,32);if(!vinyl)return o==NULL;
 if(!o||!r||!o->pixels||!o->width||!o->height||o->width>2048||o->height>2048||o->rgb_mask>1||o->vinyl!=vinyl||o->carbon_bonnet!=(bonnet>1)||
  o->bytes!=(size_t)o->width*o->height*(o->rgb_mask?1:4))return 0;
 size_t n=0;while(n<48&&o->material[n]){unsigned char c=(unsigned char)o->material[n];if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='.'))return 0;n++;}if(!n||n==48)return 0;
 uint8_t raw_hash[32],given=0;for(unsigned i=0;i<32;i++)given|=o->sha256[i];
 if(!ghost_paint_hash_bytes(r,o->pixels,o->bytes,raw_hash)||(given&&memcmp(raw_hash,o->sha256,32)))return 0;
 uint8_t identity[96]={0};memcpy(identity,raw_hash,32);memcpy(identity+32,o->material,n);identity[80]=(uint8_t)o->width;identity[81]=(uint8_t)(o->width>>8);identity[82]=(uint8_t)o->height;identity[83]=(uint8_t)(o->height>>8);
 identity[84]=o->rgb_mask;memcpy(identity+85,o->color,4);identity[89]=(uint8_t)vinyl;identity[90]=(uint8_t)bonnet;
 return ghost_paint_hash_bytes(r,identity,sizeof identity,out);
}
/* Same integer nsTextureReplace blend as original port, but retain full RGBA8
 * original paint (no RGB565 roundtrip), alpha unchanged. */
static void agp_blend(uint8_t*base,unsigned w,unsigned h,const ghost_paint_overlay*o){
 for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++){
  size_t at=((size_t)(y*o->height/h)*o->width+x*o->width/w)*(o->rgb_mask?1:4);const uint8_t*p=o->pixels+at;
  unsigned a=p[o->rgb_mask?0:3];if(!a)continue;uint8_t*d=base+((size_t)y*w+x)*4;
  for(unsigned c=0;c<3;c++){unsigned overlay=o->rgb_mask?o->color[c]*a:p[c]*255u;unsigned v=(d[c]*(255u-a)+overlay+127u)/255u;d[c]=(uint8_t)(v>255?255:v);}
 }
}
int app_ghost_paint_want(app_ghost_paint_cache*c,const ghost_paint_reader*r,ghost_paint_key key,uint64_t generation,wpk_scene*s,uint32_t vinyl,uint32_t bonnet,const ghost_paint_overlay*overlay){
 uint8_t fingerprint[32];
 if(!c||c->applying||!generation||key.pack>=55||key.custom_color>10||key.aero>3||vinyl>255||bonnet>4||(!key.custom_color&&vinyl)||!agp_overlay_fingerprint(r,vinyl,bonnet,overlay,fingerprint)){
  if(c&&!c->applying)app_ghost_paint_clear(c,c->context_generation&&c->context_generation!=generation);return 0;
 }
 if(app_ghost_paint_ready(c,key,generation,s,vinyl,bonnet)&&!memcmp(c->overlay_sha256,fingerprint,32))return 1;
 /* A generation change means all handles from that context are invalid. */
 if(!app_ghost_paint_clear(c,c->context_generation&&c->context_generation!=generation))return 0;
 if(!agp_scene(s))return 0;
 c->key=key;c->context_generation=generation;c->scene=s;c->vinyl=vinyl;c->bonnet=bonnet;memcpy(c->overlay_sha256,fingerprint,32);
 if(key.custom_color){
  const ghost_paint_page*pages=NULL;size_t n=0;
  if(ghost_paint_lookup(r,key,&pages,&n)!=GHOST_PAINT_OK||!n||n>3)goto fail;
  c->count=n;memcpy(c->pages,pages,n*sizeof *pages);
  if(vinyl&&(pages[0].page!=1||strcmp(pages[0].material,overlay->material)))goto fail;
  /* Validate all material destinations before decoding/uploading anything. */
  for(size_t i=0;i<n;i++){
   int at=wpk_find_texture(s,pages[i].material);
   if(at<0||(uint32_t)at>=s->n_tex||!s->textures[at])goto fail;
   for(size_t j=0;j<i;j++)if(!strcmp(pages[i].material,pages[j].material))goto fail;
  }
  for(size_t i=0;i<n;i++){
   uint8_t*rgba=NULL;size_t bytes=0;
   if(ghost_paint_read_rgba(r,pages+i,&rgba,&bytes)!=GHOST_PAINT_OK)goto fail;
   if(vinyl&&i==0)agp_blend(rgba,pages[i].width,pages[i].height,overlay);
   c->texture[i]=render_ghost_paint_rgba8(rgba,bytes,pages[i].width,pages[i].height);free(rgba);
   if(!c->texture[i])goto fail;
  }
  int idx[3];if(!agp_indices(c,s,idx))goto fail;
 }
 c->batch_restore=malloc(s->n_batch);if(!c->batch_restore)goto fail;
 c->batch_capacity=s->n_batch;c->prepared=1;return 1;
 fail:app_ghost_paint_clear(c,0);return 0;
}
int app_ghost_paint_apply(app_ghost_paint_cache*c,ghost_paint_key key,uint64_t generation,wpk_scene*s,uint32_t vinyl,uint32_t bonnet,app_ghost_paint_scope*scope){
 if(!scope||(c&&c->applying))return 0;memset(scope,0,sizeof *scope);
 if(!app_ghost_paint_ready(c,key,generation,s,vinyl,bonnet))return 0;
 int idx[3];if(c->count&&!agp_indices(c,s,idx))return 0;
 scope->scene=s;scope->cache=c;scope->count=c->count;scope->batch_count=s->n_batch;scope->old_cutout=c->batch_restore;
 for(uint32_t b=0;b<s->n_batch;b++)scope->old_cutout[b]=s->batches[b].cutout;
 for(size_t i=0;i<c->count;i++){
  int at=scope->index[i]=idx[i];scope->old_texture[i]=s->textures[at];scope->old_alpha[i]=s->tex_alpha[at];
  s->textures[at]=c->texture[i];s->tex_alpha[at]|=c->pages[i].alpha_present;
  for(uint32_t b=0;b<s->n_batch;b++)if(s->batches[b].tex==at)s->batches[b].cutout|=c->pages[i].alpha_present;
 }
 c->applying=1;return 1;
}
void app_ghost_paint_restore(app_ghost_paint_scope*scope){
 if(!scope||!scope->scene||!scope->cache||!scope->cache->applying)return;
 for(size_t i=0;i<scope->count;i++){int at=scope->index[i];scope->scene->textures[at]=scope->old_texture[i];scope->scene->tex_alpha[at]=scope->old_alpha[i];}
 for(size_t b=0;b<scope->batch_count;b++)scope->scene->batches[b].cutout=scope->old_cutout[b];
 scope->cache->applying=0;memset(scope,0,sizeof *scope);
}
