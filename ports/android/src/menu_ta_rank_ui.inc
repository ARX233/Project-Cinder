/* Private source-derived TA presentation only. No draw-time I/O, RNG or world access.
 * Include after R/ranking_init in menu.c. Requires generated ta_rank_assets_private.h.
 * Font proof: clRankingPlate setName=font8/datum0, setTitle=font1/datum0.
 * get2 0x857b440 splits first U+002F, then setTitleID joins with a newline.
 */
#include "ta_rank_assets_private.h"

static int ta_ui_partition_equal(const ta_rank_partition *a,const ta_rank_partition *b) {
  return a->course_id==b->course_id && a->traffic==b->traffic &&
    !memcmp(a->rules_sha256,b->rules_sha256,32) && !memcmp(a->physics_sha256,b->physics_sha256,32);
}
int menu_ta_rank_course(const menu_state *m) {
  return m && m->demo>=0 ? course_for(m->demo % RANKING_COURSES + m->ta_rank_offset) : -1;
}
int menu_ta_rank_model_plate(unsigned model_id) {
  return model_id<sizeof TA_UI_MODEL/sizeof *TA_UI_MODEL ? TA_UI_MODEL[model_id][0] : 0;
}
int menu_ta_rank_metadata(const menu_state *m,ta_rank_metadata *out) {
  if(!out)return 0;
  memset(out,0,sizeof *out); /* Other fields MUST be filled from parent's actual native binding. */
  if(!m || m->maker<0 || m->maker>=MENU_GARAGE_MAKERS || m->car<0 ||
     m->car>=MENU_GARAGE_CARS || m->car>=CARDB_NCARS[m->maker])return 0;
  int ended=0;
  for(int i=0;i<5;++i) {
    int g=m->name[i];
    if(g<0){ended=1;continue;}
    if(ended || g>=256){memset(out,0,sizeof *out);return 0;}
    out->name[i]=TA_UI_NAME_WCHAR[g];
  }
  if(!out->name[0])return 0;
  int title=menu_title(m),cls=m->class_car[m->maker][m->car];
  if(title<=0 || title>=5200 || cls<0 || cls>=47){memset(out,0,sizeof *out);return 0;}
  out->title_id=(uint32_t)title;out->class_id=(uint32_t)cls;return 1;
}
static int ta_ui_name_glyph(uint32_t ch) {
  for(int k=0;k<256;++k)if(TA_UI_NAME_WCHAR[k]==ch)return k;
  return -1;
}
void menu_set_ta_rank_view(menu_state *m,const ta_rank_view *view,int status) {
  if(!m)return;
  unsigned source=status==MENU_TA_RANK_COMMUNITY ? TA_RANK_SOURCE_COMMUNITY_UNVERIFIED : TA_RANK_SOURCE_LOCAL_UNVERIFIED;
  int ok=view && (status==MENU_TA_RANK_LOCAL || status==MENU_TA_RANK_STORE_ERROR || status==MENU_TA_RANK_COMMUNITY) &&
    view->source_kind==source &&
    view->partition.course_id==(uint32_t)menu_ta_rank_course(m) && view->partition.traffic==(uint32_t)!!m->ta_traffic &&
    view->row_count<=TA_RANK_DISPLAY && view->real_count<=TA_RANK_TOP;
  if(ok && m->ta_rank_valid && m->ta_rank_snapshot.source_kind==source &&
     ta_ui_partition_equal(&m->ta_rank_snapshot.partition,&view->partition) &&
     view->generation<m->ta_rank_snapshot.generation)ok=0;
  for(uint32_t i=0;ok && i<view->row_count;++i) {
    const ta_rank_row *r=&view->rows[i];
    if(r->position!=i+1){ok=0;break;}
    if(i<view->real_count) {
      const ta_rank_metadata *d=&r->record.attempt.metadata;
      if(r->source_kind!=source || r->default_index!=UINT32_MAX ||
         r->display_ms<1 || r->display_ms>TA_RANK_MAX_SCORE_MS || r->display_ms!=r->record.score_ms ||
         !ta_ui_partition_equal(&r->record.attempt.partition,&view->partition) ||
         d->model_id>=247 || d->title_id==0 || d->title_id>=5200 || d->class_id>=47 ||
         d->power>24 || d->handling>24 || !d->name[0]){ok=0;break;}
      int ended=0;
      for(int k=0;k<5;++k) {
        if(!d->name[k]){ended=1;continue;}
        if(ended || ta_ui_name_glyph(d->name[k])<0){ok=0;break;}
      }
    } else if(r->source_kind!=TA_RANK_SOURCE_FACTORY_DEFAULT ||
              r->display_ms!=TA_RANK_FACTORY_DISPLAY_MS || r->default_index>=10 ||
              r->default_index!=i-view->real_count){ok=0;break;}
  }
  if(ok){m->ta_rank_snapshot=*view;m->ta_rank_valid=1;m->ta_rank_status=status;return;}
  memset(&m->ta_rank_snapshot,0,sizeof m->ta_rank_snapshot);m->ta_rank_valid=0;
  m->ta_rank_status=view || status==MENU_TA_RANK_STORE_ERROR ? MENU_TA_RANK_STORE_ERROR : MENU_TA_RANK_UNAVAILABLE;
}
static const ta_rank_row *ta_ui_row(const menu_state *m,int slot) {
  if(!m || !m->ta_rank_valid || slot<0 || slot>=(int)m->ta_rank_snapshot.row_count ||
     m->ta_rank_snapshot.partition.course_id!=(uint32_t)menu_ta_rank_course(m) ||
     m->ta_rank_snapshot.partition.traffic!=(uint32_t)!!m->ta_traffic)return NULL;
  return &m->ta_rank_snapshot.rows[slot];
}
/* Insert the best old card time into this local display only. Keep a new
 * full record at the same time in preference to the metadata-free PB. */
static int ta_ui_saved_pb_rank(const menu_state *m,int ms) {
  if (m->ta_traffic || m->ta_rank_status==MENU_TA_RANK_COMMUNITY || ms<=0 || (unsigned)ms>TA_RANK_MAX_SCORE_MS) return 0;
  for (int k=0;k<(int)TA_RANK_DISPLAY;++k) {
    const ta_rank_row *row=ta_ui_row(m,k);
    if (!row || row->source_kind!=TA_RANK_SOURCE_LOCAL_UNVERIFIED ||
        row->display_ms>(unsigned)ms) return k+1;
    if (row->display_ms==(unsigned)ms) return 0;
  }
  return 0;
}
/* Native isR35 0x857cac8 tests raw model232..242, not physics/car type. */
static int ta_ui_is_r35(uint32_t model) {return model>=232 && model<=242;}
static int ta_ui_real_assets(const ta_rank_row *row) {
  const ta_rank_metadata *d=&row->record.attempt.metadata;
  if(d->model_id>=247 || d->class_id>=47 || d->title_id>=5200 || d->power>24 || d->handling>24)return 0;
  if(anm_sprite(menu_ta_rank_model_plate(d->model_id))<0)return 0;
  if(ta_ui_is_r35(d->model_id)) {
    if(ID.ranking_step<0 || anm_sprite(5679)<0 || anm_sprite(5680)<0)return 0;
  } else {
    int grade=car_tune_grade((int)d->power,(int)d->handling);
    if(grade<0 || grade>=5 || anm_sprite(TA_UI_HANDLING[grade])<0)return 0;
  }
  for(int k=0;k<3;++k) {
    int sid=TA_UI_CLASS[d->class_id][k];
    if(sid>3 && anm_sprite(sid)<0)return 0;
  }
  for(int k=0;k<5 && d->name[k];++k) {
    int g=ta_ui_name_glyph(d->name[k]);
    if(g<0 || anm_sprite(106000+g)<0)return 0;
  }
  uint32_t at=TA_UI_TITLE_AT[d->title_id],n=TA_UI_TITLE_LEN[d->title_id];
  if(n>128)return 0; /* Native unmapped ID5149 is an empty title, not substitute text. */
  for(uint32_t k=0;k<n;++k)if(TA_UI_TITLE_GLYPHS[at+k]!=UINT16_MAX &&
      anm_sprite(110000+TA_UI_TITLE_GLYPHS[at+k])<0)return 0;
  return 1;
}
static void ta_ui_glyph(int sprite,float gx,float gy,const float xf[6],const float mul[4],const float add[4],float dy) {
  float w=anm_sprite_width(sprite),h=anm_sprite_height(sprite);
  /* All50 original ranking name/title records are axis-aligned translations.
   * Never silently approximate a future rotated/sheared replacement resource. */
  if(sprite<0 || w<=0 || h<=0 || xf[3]!=0 || xf[4]!=0 || xf[2]<=0 || xf[5]<=0)return;
  float x=xf[0]+xf[2]*gx,y=xf[1]+dy+xf[5]*gy;
  const float src[4]={0,0,w,h},dst[4]={x,y,x+xf[2]*w,y+xf[5]*h};
  anm_draw_part_col(sprite,src,dst,mul,add);
}
static void ta_ui_name(const uint32_t name[5],int anim,int frame,float alpha,float dy) {
  float xf[6],mul[4],add[4];
  if(anm_sprite_xf(anim,frame,R.t_name,xf,mul,add)) {
    mul[3]*=alpha;
    for(int k=0;k<5 && name[k];++k)
      ta_ui_glyph(anm_sprite(106000+ta_ui_name_glyph(name[k])),24.0f*(float)k,0,xf,mul,add,dy);
  }
}
/* The original plate keeps the calendar for sorting. Use the gap above
 * its title text to show the recorded date on Cinder's board. */
static void ta_ui_stamp(const char *text,const float xf[6],const float mul[4],const float add[4],float dy) {
  float date_xf[6]={xf[0],xf[1]-10.0f*xf[5],xf[2]*0.32f,xf[3],xf[4],xf[5]*0.32f};
  float x=0;
  for (const unsigned char *c=(const unsigned char *)text;*c;++c,x+=24) {
    if (*c==' ') continue;
    int g=ta_ui_name_glyph((uint32_t)*c+0xfee0u);
    if (g>=0) ta_ui_glyph(anm_sprite(106000+g),x,0,date_xf,mul,add,dy);
  }
}
static void ta_ui_date(uint64_t completed_at_ms,const float xf[6],const float mul[4],const float add[4],float dy) {
  uint64_t seconds=completed_at_ms/1000u;
  time_t stamp=(time_t)seconds;
  struct tm date;
  if (!seconds || stamp<0 || (uint64_t)stamp!=seconds || !localtime_r(&stamp,&date) ||
      date.tm_year<-1900 || date.tm_year>8099) return;
  char label[32];
  snprintf(label,sizeof label,"%04d/%02d/%02d %02d:%02d:%02d",
           date.tm_year+1900,date.tm_mon+1,date.tm_mday,date.tm_hour,date.tm_min,date.tm_sec);
  ta_ui_stamp(label,xf,mul,add,dy);
}
static void ta_ui_saved_text(const menu_ta_saved_pb *pb,int anim,int frame,float alpha,float dy) {
  static const uint32_t unknown_name[5]={'S'+0xfee0,'A'+0xfee0,'V'+0xfee0,'E'+0xfee0,'D'+0xfee0};
  uint32_t name[5]={0};
  for (int k=0;k<5 && pb->name[k]>=0 && pb->name[k]<256;++k)
    name[k]=TA_UI_NAME_WCHAR[pb->name[k]];
  ta_ui_name(name[0]?name:unknown_name,anim,frame,alpha,dy);
  float xf[6],mul[4],add[4];
  if (anm_sprite_xf(anim,frame,R.t_title,xf,mul,add)) {
    mul[3]*=alpha;
    ta_ui_stamp("SAVED PB",xf,mul,add,dy);
  }
}
static void ta_ui_text(const ta_rank_row *row,int anim,int frame,float alpha,float dy) {
  const ta_rank_metadata *d=&row->record.attempt.metadata;
  float xf[6],mul[4],add[4];
  ta_ui_name(d->name,anim,frame,alpha,dy);
  if(anm_sprite_xf(anim,frame,R.t_title,xf,mul,add)) {
    mul[3]*=alpha;float x=0,y=0;
    ta_ui_date(row->record.attempt.completed_at_ms,xf,mul,add,dy);
    uint32_t at=TA_UI_TITLE_AT[d->title_id],n=TA_UI_TITLE_LEN[d->title_id];
    for(uint32_t k=0;k<n;++k) {
      unsigned g=TA_UI_TITLE_GLYPHS[at+k];
      if(g==UINT16_MAX){x=0;y+=16;continue;}
      ta_ui_glyph(anm_sprite(110000+(int)g),x,y,xf,mul,add,dy);
      x+=TA_UI_TITLE_WCHAR[g]<=127?8.0f:16.0f;
    }
  }
  /* Its original last-record draw order is preserved; it was hidden in the ANM pass. */
  int slash=anm_sprite(3351);
  if(anm_sprite_xf(anim,frame,slash,xf,mul,add)) {
    mul[3]*=alpha;ta_ui_glyph(slash,0,0,xf,mul,add,dy);
  }
}
/* Port-owned provenance notice, rendered in existing original name glyphs.
 * Placement below authored last row is a new provenance overlay, not arcade art. */
static void ta_ui_notice(const char *text,float alpha) {
  float x=8,y=458;
  for(const unsigned char *c=(const unsigned char*)text;*c;++c,x+=9) {
    if(*c==' ')continue;
    int g=ta_ui_name_glyph((uint32_t)*c+0xfee0u),s=g<0?-1:anm_sprite(106600+g);
    float w=anm_sprite_width(s),h=anm_sprite_height(s);
    if(s<0 || w<=0 || h<=0)continue;
    const float src[4]={0,0,w,h},dst[4]={x,y,x+9,y+14};
    anm_draw_part(s,src,dst,alpha);
  }
}
