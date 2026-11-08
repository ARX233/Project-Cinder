/* Original 3DX+ Ghost presentation; no file, native world or race authority.
 * main SHA256 2e6591153d7e599437465f736a42e27b01a3b56c881bee58365fb21d0678b1f6.
 * Search tables 0x94082e0..8400; Level 0x9408420..84b0; Rival
 * clSpinBoxRivalStd 0x93de170..3c8; Course 0x94085c0..8600.
 * Touch/release capture is a port adapter over the actual ANM geometry. */
#ifndef GHOST_ORIGINAL_UI_H
#define GHOST_ORIGINAL_UI_H
#include "anm.h"
#include <math.h>
#include <string.h>
enum { GHOST_UI_SEARCH, GHOST_UI_LEVEL, GHOST_UI_COURSE,
       GHOST_UI_RIVAL, GHOST_UI_NAME, GHOST_UI_NAME_TYPE, GHOST_UI_RESULT };
typedef struct {
  int page, sel, from, tick, deciding, commit, count;
  int position, arrow_tick;
  float scroll, scroll_from;
} ghost_original_ui;
typedef struct {
  int search, arrows, ring, name_type, name_ring;
  int level, level_arrows, your_level, rival, rival_arrows, course;
} ghost_original_assets;
typedef struct { int menu, console, ink_height; } ghost_crown_art;
static inline const ghost_crown_art *ghost_original_crown(unsigned area) {
  /* clEffAreaType order. Menu art from getCrownSprite4RivalSelect;
   * console art from nsRivalMark's table at 0x93cfb60. */
  static const ghost_crown_art art[] = {
    {1737,1666,64}, {1742,1671,71}, {1743,1672,66}, {1744,1673,84},
    {1740,1669,64}, {1741,1670,63}, {1739,1668,69}, {1738,1667,62},
  };
  return area < sizeof art / sizeof *art ? &art[area] : NULL;
}
/* menu_layout_tg_vs_course is in visual order. Fukuoka is the enlarged
 * picture at frame 600 (4661), Hakone at frame 700 (4655). */
static const struct { int picture, whole_area, unavailable; } GHOST_COURSE_ART[] = {
  {4646,5545,6524}, {4648,5546,7009}, {4650,5550,7010}, {4652,5557,7011},
  {4659,4659,7014}, {4654,4657,7012}, {4661,4661,7015}, {4655,5559,7013},
};
static inline ghost_original_assets ghost_original_bind(void) {
  ghost_original_assets a={anm_find("menu_layout_tg_search_grayout"),
    anm_find("menu_layout_tg_search_grayout_arrow"), anm_find("menu_layout_tg_seach_ring"),
    anm_find("menu_layout_tg_search_2"), anm_find("menu_layout_tg_seach_ring_2"),
    anm_find("menu_layout_tg_lv"), anm_find("menu_layout_tg_lv_arrow"),
    anm_find("menu_layout_tg_lv_yourlv"), anm_find("menu_layout_tg_vs_sel"),
    anm_find("menu_layout_tg_rival"), anm_find("menu_layout_tg_vs_course")};
  return a;
}
static inline int ghost_original_available(ghost_original_assets a) {
  return a.search>=0 && a.arrows>=0 && a.ring>=0 && anm_frames(a.search)>=400 &&
         anm_frames(a.arrows)>=360 && anm_frames(a.ring)>=360;
}
static inline void ghost_original_open(ghost_original_ui *u,int page) {
  memset(u,0,sizeof *u);u->page=page;u->from=-1;
  u->count=page==GHOST_UI_SEARCH?4:page==GHOST_UI_LEVEL?10:page==GHOST_UI_COURSE?8:
           page==GHOST_UI_NAME_TYPE?2:0;
}
static inline int ghost_original_count(const ghost_original_ui *u) { return u->count; }
static inline int ghost_original_move_ticks(const ghost_original_ui *u) {
  return u->page==GHOST_UI_SEARCH||u->page==GHOST_UI_NAME_TYPE?4:5;
}
static inline float ghost_original_scroll(const ghost_original_ui *u) {
  return u->from<0?u->scroll:u->scroll_from+(u->scroll-u->scroll_from)*(float)u->tick/5.0f;
}
static inline int ghost_original_frame(const ghost_original_ui *u) {
  if(u->sel<0 || u->sel>=ghost_original_count(u))return 0;
  if(u->page==GHOST_UI_COURSE) {
    if(u->deciding)return u->sel*100+60+(10-u->deciding);
    if(u->from>=0)return u->from<u->sel?u->from*100+90+u->tick:u->sel*100+94-u->tick;
    return u->sel*100+u->tick%59;
  }
  if(u->deciding)return u->sel*100+61+(10-u->deciding);
  if(u->from>=0)return u->from<u->sel?u->from*100+91+u->tick:u->sel*100+95-u->tick;
  return u->sel*100+1+u->tick%59;
}
/* One independently populated level/rival card, not one frame group per rival.
 * The five source positions are left2,left1,selected,right1,right2. */
static inline int ghost_original_card_frame(const ghost_original_ui *u,int item) {
  static const int idle[5]={25,45,65,135,155};
  static const int decide[5]={240,260,210,280,300};
  static const int move[6]={20,40,60,130,150,170};
  int d=item-u->sel;
  if(u->from>=0) {
    int old=item-u->from;
    if(u->from>u->sel) { /* authored forward walk: cards move right */
      if(d< -2 || d>3)return -1;
      return move[d+2]+(u->tick?u->tick-1:0);
    }
    if(old< -2 || old>3)return -1;
    return move[old+2]+4-u->tick;
  }
  if(d< -2 || d>2)return -1;
  if(u->deciding)return decide[d+2]+10-u->deciding;
  return idle[d+2]+(d==0?u->tick%59:0);
}
static inline int ghost_original_arrow_frame(const ghost_original_ui *u) {
  /* Search spin box +0xb0 uses its previous 59-frame loop through a
   * slide, then restarts at the new selection (original 0x9408380/90). */
  if(u->deciding)return -1;
  int slot=u->from>=0?u->from:u->sel;
  return slot*100+1+(u->from>=0?u->arrow_tick:u->tick)%59;
}
static inline int ghost_rival_arrow_frame(const ghost_original_ui *u) {
  /* clSpinBoxRivalStd::setSpin selects distinct authored blocks by
   * endpoint. Sprite 446 is the base and 899 is its animated glow. */
  if(u->from>=0||u->deciding||u->count<2)return -1;
  int level=u->page==GHOST_UI_LEVEL; /* level's ANM has the endpoint blocks reversed */
  int start=u->sel==0?(level?61:121):u->sel+1==u->count?(level?121:61):1;
  return start+u->tick%59;
}
/* Restore the viewport reached by steering right from the first card.
 * Original rightward scrolling occurs on the fourth-to-fifth and fifth-to-sixth moves. */
static inline int ghost_original_focus_course(ghost_original_ui *u,int slot) {
  if(u->page!=GHOST_UI_COURSE || u->from>=0 || u->deciding || slot<0 || slot>=u->count)return 0;
  int steps=slot<=3?0:slot>=5?2:1;
  u->sel=slot;u->position=slot-steps;
  u->scroll=u->scroll_from=-88.0f*(float)steps;
  u->tick=u->arrow_tick=0;
  return 1;
}
static inline int ghost_original_move(ghost_original_ui *u,int direction) {
  if(u->from>=0 || u->deciding || (direction!=-1&&direction!=1))return 0;
  int n=u->sel+direction;if(n<0||n>=ghost_original_count(u))return 0;
  if(u->page==GHOST_UI_COURSE) {
    int scroll=direction>0?u->position>2&&u->sel<=4:u->position<=2&&u->sel>2;
    if(!scroll)u->position+=direction;
    u->scroll_from=u->scroll;
    if(scroll)u->scroll-=88.0f*(float)direction;
  }
  u->arrow_tick=u->tick%59;u->from=u->sel;u->sel=n;u->tick=0;return 1;
}
static inline int ghost_original_decide(ghost_original_ui *u,int enabled) {
  if(!enabled||u->from>=0||u->deciding)return 0;
  u->deciding=10;u->commit=0;return 1;
}
static inline int ghost_original_tick(ghost_original_ui *u) {
  if(u->deciding){if(!--u->deciding){u->commit=1;return 1;}return 0;}
  if(u->from>=0){
    ++u->arrow_tick;
    if(++u->tick>=ghost_original_move_ticks(u)){u->from=-1;u->tick=0;}
  }
  else if(++u->tick>=59000)u->tick=0;
  return 0;
}
static inline int ghost_original_rect(ghost_original_assets a,const ghost_original_ui *u,int slot,float r[4]) {
  static const int disc[4]={453,1896,1898,925};
  if(slot<0||slot>=ghost_original_count(u))return 0;
  if(u->page==GHOST_UI_LEVEL||u->page==GHOST_UI_RIVAL) {
    int f=ghost_original_card_frame(u,slot);if(f<0)return 0;
    return anm_sprite_rect(u->page==GHOST_UI_LEVEL?a.level:a.rival,f,anm_sprite(950),r);
  }
  if(u->page==GHOST_UI_COURSE) {
    float alpha;
    if(!anm_sprite_rect_at(a.course,ghost_original_frame(u),anm_sprite(GHOST_COURSE_ART[slot].picture),0,r,&alpha) || alpha<=0)return 0;
    /* All eight original whole-area sprites share the nontransparent
     * rectangle [52,204) x [1,121) in their 256x128 canvases. */
    float x=r[0]+ghost_original_scroll(u),y=r[1];
    float w=(r[2]-r[0])/256.0f,h=(r[3]-r[1])/128.0f;
    r[0]=x+52.0f*w;r[2]=x+204.0f*w;r[1]=y+h;r[3]=y+121.0f*h;
    return 1;
  }
  int sprite=u->page==GHOST_UI_NAME_TYPE?(slot?1571:1570):disc[slot];
  int anim=u->page==GHOST_UI_NAME_TYPE?a.name_type:a.search;
  return anm_sprite_rect(anim,ghost_original_frame(u),anm_sprite(sprite),r);
}
static inline int ghost_original_hit(ghost_original_assets a,const ghost_original_ui *u,float x,float y) {
  if(u->from>=0||u->deciding||!isfinite(x)||!isfinite(y))return -1;
  if(u->page==GHOST_UI_COURSE) {
    for(int i=0;i<u->count;++i) {
      float r[4];
      if(ghost_original_rect(a,u,i,r)&&x>=r[0]&&x<r[2]&&y>=r[1]&&y<r[3])return i;
    }
    return -1;
  }
  /* Selected first: its large authored bounds can overlap the small neighbours. */
  for(int pass=0;pass<2;++pass)for(int i=0;i<ghost_original_count(u);++i) {
    if((i==u->sel)!=(pass==0))continue;
    float r[4];if(!ghost_original_rect(a,u,i,r))continue;
    float rx=(r[2]-r[0])*.5f,ry=(r[3]-r[1])*.5f;
    if(rx<=0||ry<=0)continue;
    float dx=(x-(r[0]+r[2])*.5f)/rx,dy=(y-(r[1]+r[3])*.5f)/ry;
    if(dx*dx+dy*dy<1)return i;
  }
  return -1;
}
#endif
