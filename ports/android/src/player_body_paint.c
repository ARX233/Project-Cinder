#include "player_body_paint.h"
#include "player_paint_model_profile_private.h"
#include <string.h>
static player_paint_key key(player_body_paint_identity i){return (player_paint_key){i.pack,i.custom_color,i.aero};}
static int same(player_body_paint_identity a,player_body_paint_identity b){return a.raw_model==b.raw_model&&a.pack==b.pack&&a.factory_paint==b.factory_paint&&a.custom_color==b.custom_color&&a.aero==b.aero&&a.vinyl==b.vinyl&&a.bonnet==b.bonnet&&a.context_generation==b.context_generation;}
int player_body_paint_identity_valid(player_body_paint_identity i){
 if(!i.context_generation||i.pack>=55||i.custom_color>10||i.aero>3||i.bonnet>4)return 0;
 if(i.custom_color&&i.raw_model>=232&&i.raw_model<=242)return 0;
 for(size_t n=0;n<sizeof PLAYER_PAINT_MODELS/sizeof PLAYER_PAINT_MODELS[0];n++){
  if(PLAYER_PAINT_MODELS[n].model==i.raw_model)return PLAYER_PAINT_MODELS[n].pack==i.pack&&PLAYER_PAINT_MODELS[n].paint==i.factory_paint;
 }return 0;
}
int player_body_paint_clear(player_body_paint_cache*c,int lost){
 if(!c||!app_player_paint_clear(&c->selected,lost))return 0;
 memset(c,0,sizeof *c);return 1;
}
int player_body_paint_ready(const player_body_paint_cache*c,player_body_paint_identity i,const wpk_scene*s){return c&&c->prepared&&player_body_paint_identity_valid(i)&&same(c->identity,i)&&app_player_paint_ready(&c->selected,key(i),i.context_generation,s,i.vinyl,i.bonnet);}
int player_body_paint_prepare(player_body_paint_cache*c,const player_paint_reader*r,player_body_paint_identity i,wpk_scene*s,const player_paint_overlay*o){
 if(!c||c->selected.applying)return 0;
 if(!player_body_paint_identity_valid(i)){player_body_paint_clear(c,c->identity.context_generation&&c->identity.context_generation!=i.context_generation);return 0;}
 if(c->prepared&&!same(c->identity,i)&&!player_body_paint_clear(c,c->identity.context_generation!=i.context_generation))return 0;
 c->prepared=0;
 if(!app_player_paint_want(&c->selected,r,key(i),i.context_generation,s,i.vinyl,i.bonnet,o))return 0;
 c->identity=i;c->prepared=1;return 1;
}
int player_body_paint_apply(player_body_paint_cache*c,player_body_paint_identity i,wpk_scene*s,app_player_paint_scope*scope){
 if(!player_body_paint_ready(c,i,s))return 0;
 return app_player_paint_apply(&c->selected,key(i),i.context_generation,s,i.vinyl,i.bonnet,scope);
}
uint16_t player_body_paint_available_mask(const player_paint_reader*r,player_body_paint_identity i,const wpk_scene*s){
 if(!r||!player_body_paint_identity_valid(i)||(i.raw_model>=232&&i.raw_model<=242)||!s||!s->n_tex||s->n_tex>65535||!s->textures||!s->tex_alpha||!s->tex_tbl||!s->n_batch||s->n_batch>65536||!s->batches)return 0;
 uint16_t mask=0;
 for(unsigned color=1;color<=10;color++){
  const player_paint_page*p=NULL;size_t count=0;i.custom_color=(uint8_t)color;
  if(player_paint_lookup(r,key(i),&p,&count)!=PLAYER_PAINT_OK||!count||count>3)continue;
  int good=1,indices[3]={0};
  for(size_t n=0;n<count&&good;n++){
   int at=indices[n]=wpk_find_texture(s,p[n].material);if(at<0||(uint32_t)at>=s->n_tex||!s->textures[at]){good=0;break;}
   for(size_t j=0;j<n;j++)if(indices[j]==at)good=0;
   int referenced=0;for(uint32_t b=0;b<s->n_batch;b++)if(s->batches[b].count&&(s->batches[b].tex==at||s->batches[b].env==at||s->batches[b].spec==at)){referenced=1;break;}
   if(!referenced)good=0;
  }if(good)mask|=(uint16_t)(1u<<(color-1));
 }return mask;
}
