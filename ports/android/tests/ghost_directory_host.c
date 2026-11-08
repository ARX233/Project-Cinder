/* Full production menu.c. Audio/HUD/ANM rendering calls are observed, not GPU.
 * fixture.h contains real source ANM bounds and genuine catalogue/binding inputs.
 * This test NEVER calls a native engine and is NOT actual-play evidence. */
#include PORT_MENU
#include <assert.h>
#include "fixture.h"
#define COUNT(a) ((int)(sizeof(a)/sizeof *(a)))
static float test_edge;
static unsigned draw_calls,part_calls,source_hits,source_draws;
static int saw_disabled_history,saw_disabled_revenge,saw_win,saw_lose,last_result_frame;
static int topbar_message;
static unsigned menu_option_draws;
static int crown_sprite_drawn;
static float crown_sprite_bounds[4];
static FILE *trace_file;
static int collect_fields,field_count,field_parts[20],no_date_digits;
static int test_player_model=-1,stock_hp_seen,tune_power_seen;
int title_model(int maker,int car,int color){(void)maker;(void)car;(void)color;return test_player_model;}
int title_glyph_index(unsigned codepoint){return (int)codepoint;}
int car_tune_hp(int stock,int power){stock_hp_seen=stock;tune_power_seen=power;return 740;}
int car_tune_grade(int power,int handling){(void)power;(void)handling;return CAR_GRADE_B;}
static void trace_anm(int a,int f,float alpha,float x,float y,float zoom,const anm_swap*s,int n){
 if(!trace_file||a<0)return;
 fprintf(trace_file,"{\"anm\":\"%s\",\"frame\":%d,\"alpha\":%.9g,\"x\":%.9g,\"y\":%.9g,\"zoom\":%.9g,\"swap\":[",FIX_ANM[a].name,f,alpha,x,y,zoom);
 for(int i=0;i<n;++i)fprintf(trace_file,"%s[%d,%d]",i?",":"",s[i].from,s[i].to);
 fputs("]}\n",trace_file);
}
static void capture(const char*tag,const menu_state*m){
 const char*on=getenv("CINDER_UI_TRACE");if(!on||strcmp(on,"1"))return;
 char path[80];snprintf(path,sizeof path,"trace_%s.jsonl",tag);trace_file=fopen(path,"wx");assert(trace_file);
 menu_state steady=*m;steady.t=120; /* source steady frame, not blank native intro frame0 */
 draw_ghost_hub(&steady,0,0,1024,768,NULL,NULL);fclose(trace_file);trace_file=NULL;
}
void snd_menu(int which){(void)which;}
int anm_find(const char *name){for(int i=0;i<COUNT(FIX_ANM);++i)if(!strcmp(name,FIX_ANM[i].name))return i;return -1;}
int anm_frames(int a){return a>=0&&a<COUNT(FIX_ANM)?FIX_ANM[a].frames:1;}
int anm_sprite(int id){return no_date_digits&&id>=1752&&id<=1761?-1:id;}
int anm_sprite_id(int id){return id;}
float anm_sprite_width(int id){for(int i=0;i<COUNT(FIX_SPRITE);++i)if(FIX_SPRITE[i].id==id)return FIX_SPRITE[i].w;return id>=0?32:0;}
float anm_sprite_height(int id){for(int i=0;i<COUNT(FIX_SPRITE);++i)if(FIX_SPRITE[i].id==id)return FIX_SPRITE[i].h;return id>=0?32:0;}
int anm_sprite_rect(int a,int f,int s,float r[4]){
 for(int i=0;i<COUNT(FIX_RECT);++i)if(FIX_RECT[i].anim==a&&FIX_RECT[i].frame==f&&FIX_RECT[i].sprite==s){memcpy(r,FIX_RECT[i].r,4*sizeof *r);source_hits++;return 1;}return 0;
}
int anm_sprite_rect_at(int a,int f,int s,int k,float r[4],float*alpha){if(k)return 0;if(alpha)*alpha=1;return anm_sprite_rect(a,f,s,r);}
float anm_sprite_alpha(int a,int f,int s){float r[4];return anm_sprite_rect(a,f,s,r)?1:0;}
static void observe(int a,int f){if(a<0)return;assert(a<COUNT(FIX_ANM));assert(f>=0&&f<anm_frames(a));++draw_calls;
 if(strstr(FIX_ANM[a].name,"menu_layout_tg_"))++source_draws;
 if(a==ID.win)saw_win=1;if(a==ID.lose){saw_lose=1;last_result_frame=f;}
}
void anm_draw(int a,int f,float alpha){trace_anm(a,f,alpha,0,0,1,NULL,0);observe(a,f);}
void anm_draw_ex(int a,int f,float alpha,float x,float y,const anm_swap *s,int n){trace_anm(a,f,alpha,x,y,1,s,n);observe(a,f);
 for(int i=0;i<n;++i){if(s[i].from==0x104d&&s[i].to==0x136b)saw_disabled_history=1;if(s[i].from==0x104e&&s[i].to==0x136c)saw_disabled_revenge=1;
  if(a>=0&&a==ID.top&&s[i].from==T_TOPBAR_MES)topbar_message=s[i].to;}}
void anm_draw_xy(int a,int f,float alpha,float x,float y,float sx,float sy,const anm_swap*s,int n){(void)sx;(void)sy;anm_draw_ex(a,f,alpha,x,y,s,n);}
void anm_draw_xf(int a,int f,float alpha,float x,float y,float z,const anm_swap*s,int n){trace_anm(a,f,alpha,x,y,z,s,n);observe(a,f);}
void anm_draw_sprite(int s,float x,float y,float a){(void)s;(void)x;(void)y;(void)a;++part_calls;}
void anm_draw_part(int s,const float src[4],const float dst[4],float a){
 if(s>=1737&&s<=1744){crown_sprite_drawn=s;memcpy(crown_sprite_bounds,dst,sizeof crown_sprite_bounds);}
 if(collect_fields){assert(field_count<COUNT(field_parts));field_parts[field_count++]=s;}
 if(trace_file)fprintf(trace_file,"{\"part\":%d,\"src\":[%.9g,%.9g,%.9g,%.9g],\"dst\":[%.9g,%.9g,%.9g,%.9g],\"alpha\":%.9g}\n",s,src[0],src[1],src[2],src[3],dst[0],dst[1],dst[2],dst[3],a);
for(int i=0;i<4;++i)assert(isfinite(src[i])&&isfinite(dst[i]));assert(src[2]>src[0]&&src[3]>src[1]);++part_calls;}
void anm_fill(float r,float g,float b,float a){(void)r;(void)g;(void)b;(void)a;}
float anm_edge(void){return test_edge*1.6f;}
void hud_ui_begin(float w,float h){assert(w>0&&h>0);}
void hud_ui_end(void){}
float hud_ui_text_width(const char*s,float px){return (float)strlen(s)*8*px;}
float hud_ui_text(const char*s,float x,float y,float px,float r,float g,float b,float a){(void)y;(void)r;(void)g;(void)b;(void)a;return x+hud_ui_text_width(s,px);}
void hud_draw_menu_keys(float w,float h,int held,int keys,int back){(void)w;(void)h;(void)held;(void)keys;(void)back;}
void hud_draw_menu_option(float w,float h,int held){(void)w;(void)h;(void)held;++menu_option_draws;}
int hud_menu_key(float x,float y){float e=test_edge*1.6f;
 if(x>=22-e&&x<=226-e&&y>=634&&y<=726)return -1;
 if(x>=798+e&&x<=1002+e&&y>=634&&y<=726)return 1;
 if(x>=722+e&&x<=806+e&&y>=46&&y<=106)return HUD_MENU_BACK;
 if(x>=622+e&&x<=706+e&&y>=46&&y<=106)return HUD_MENU_OPTION;return 0;}
static void check_card_fields(void) {
 menu_state m={0};
 menu_ghost_directory_area area={.raw_model=92,.power=17,.handling=17};
 const cardb_car *car=&CARDB_CARS[0][0];
 int anim=ghost_original_bind().rival;
 collect_fields=1;
 ghost_card_power(&m,&area,car,anim,65,1);
 assert(stock_hp_seen==car->hp&&tune_power_seen==17&&field_count==7);
 assert(field_parts[0]==TITLE_GLYPH1+0xff17&&field_parts[1]==TITLE_GLYPH1+0xff14&&
        field_parts[2]==TITLE_GLYPH1+0xff10&&field_parts[6]==TITLE_GLYPH1+0xff22);
 field_count=0;test_player_model=232;
 ghost_card_power(&m,&area,car,anim,215,1);
 assert(field_count==9&&field_parts[0]==TITLE_GLYPH1+0xff30&&field_parts[5]==TITLE_GLYPH1+0xff28);
 field_count=0;test_player_model=-1;
 ghost_card_date(&area,anim,65,1);
 const int unknown[]={1753,1761,1761,1759,4585,1753,4585,1753};
 assert(field_count==COUNT(unknown));
 for(int i=0;i<field_count;++i)assert(field_parts[i]==unknown[i]);
 field_count=0;no_date_digits=1;
 area.recorded=(menu_ghost_record_date){.year=2024,.month=2,.day=29,.hour=13,.minute=47};
 ghost_card_date(&area,anim,215,1);
 const int known[]={2,0,2,4,0,2,2,9,1,3,4,7};
 assert(field_count==COUNT(known));
 for(int i=0;i<field_count;++i)assert(field_parts[i]==CARD_GLYPH2+known[i]);
 no_date_digits=collect_fields=0;
}
static void tick(menu_state*m,int n){for(int i=0;i<n;++i)assert(!menu_update(m,1.0f/60.0f));}
static void gas(menu_state*m){m->tap=1;tick(m,10);}
static void move(menu_state*m,int direction){int ticks=ghost_original_move_ticks(&m->ghost.ui);m->key=direction;tick(m,1);if(m->ghost.ui.from>=0)tick(m,ticks-1);}
static void touch(menu_state*m,void*id,int phase,float x,float y){menu_touch(m,id,phase,x*1.6f,y*1.6f);}
static void setup_ids(void){memset(&ID,0xff,sizeof ID);ID.name_back=anm_find("menu_g_name_name_back");ID.name_select=anm_find("menu_layout_name_select");ID.name_line=anm_find("menu_g_name_line");
 ID.top=anm_find("menu_g_topbar_bar");assert(ID.top>=0);
 const char*t[]={"menu_g_name_katakana","menu_g_name_hiragana","menu_g_name_capital","menu_g_name_small","menu_g_name_end"};for(int i=0;i<5;++i)ID.name_tab[i]=anm_find(t[i]);ID.day_cards=anm_find("menu_layout_yn_card_1_gold");ID.win=anm_find("menu_g_finish_win");ID.lose=anm_find("menu_g_finish_lose");}
static void hit_center(menu_state*m,int slot){float r[4];assert(ghost_original_rect(ghost_original_bind(),&m->ghost.ui,slot,r));float x=(r[0]+r[2])*.5f,y=(r[1]+r[3])*.5f;assert(ghost_hit(m,x,y)==slot+10);}
static int overlap(const float a[4],const float b[4]){return a[0]<b[2]&&a[2]>b[0]&&a[1]<b[3]&&a[3]>b[1];}
static int visual(int area){for(int i=0;i<8;++i)if(menu_ghost_course_area(i)==area)return i;assert(0);return -1;}

/* main_android.c converts framebuffer pixels to menu units using height
 * and the 4:3 centre. Check both directions through production menu_touch. */
static void course_touch(menu_state *m,void *finger,int phase,float x,float y,float w,float h) {
 float scale=768.0f/h,edge=(w*scale-1024.0f)*.5f;
 float px=(x*1.6f+edge)/scale,py=y*1.6f/scale;
 assert(px>=0&&px<w&&py>=0&&py<h);
 menu_touch(m,finger,phase,px*scale-edge,py*scale);
}

static void check_course_taps(const menu_state *initial) {
 static const float viewport[][2]={{1024,768},{1600,900},{1920,882}};
 const ghost_original_assets a=ghost_original_bind();
 float old_edge=test_edge;
 for(int v=0;v<COUNT(viewport);++v) {
  float w=viewport[v][0],h=viewport[v][1];
  test_edge=(w*480.0f/h-640.0f)*.5f;
  menu_state m=*initial;
  menu_ghost_open(&m);
  m.ghost.level=-1;
  ghost_page(&m,GHOST_UI_COURSE);
  for(int i=0;i<5;++i)move(&m,1);
  assert(m.ghost.ui.sel==5&&m.ghost.ui.scroll==-176&&m.ghost.ui.position==3);

  /* Osaka's 256px template ends at x492, but its visible art ends at x440.
   * Fukuoka's visible left side at x470 must win, and x446 is blank. */
  float src[4],fukuoka[4];
  assert(anm_sprite_rect(a.course,500,anm_sprite(4661),src));
  assert(ghost_original_rect(a,&m.ghost.ui,6,fukuoka));
  assert(src[0]+m.ghost.ui.scroll+26==fukuoka[0]);
  assert(fukuoka[0]==454&&fukuoka[2]==530&&ghost_hit(&m,446,209)==0);
  assert(ghost_hit(&m,470,209)==16);
  course_touch(&m,(void*)1,TOUCH_BEGAN,470,209,w,h);
  course_touch(&m,(void*)2,TOUCH_ENDED,470,209,w,h);
  assert(m.ghost.ui.sel==5&&m.ghost.touch==(void*)1);
  course_touch(&m,(void*)1,TOUCH_CANCELLED,470,209,w,h);
  assert(m.ghost.ui.sel==5&&!m.ghost.touch);
  course_touch(&m,(void*)1,TOUCH_BEGAN,470,209,w,h);
  course_touch(&m,(void*)1,TOUCH_MOVED,446,209,w,h);
  assert(m.ghost.touch==(void*)1&&!m.ghost.held);
  course_touch(&m,(void*)1,TOUCH_ENDED,446,209,w,h);
  assert(m.ghost.ui.sel==5&&!m.ghost.touch);
  course_touch(&m,(void*)1,TOUCH_BEGAN,470,209,w,h);
  course_touch(&m,(void*)1,TOUCH_ENDED,470,209,w,h);
  assert(m.ghost.ui.sel==6&&m.ghost.ui.from==5&&m.ghost.ui.position==4);
  for(int t=0;t<5;++t) {
   /* A second contact during the five authored slide frames never advances. */
   course_touch(&m,(void*)2,TOUCH_BEGAN,452,220,w,h);
   course_touch(&m,(void*)2,TOUCH_ENDED,452,220,w,h);
   assert(!m.ghost.touch&&m.ghost.ui.sel==6&&!m.ghost.ui.deciding);
   tick(&m,1);
  }
  assert(m.ghost.ui.from<0&&ghost_hit(&m,452,220)==16);
  course_touch(&m,(void*)1,TOUCH_BEGAN,452,220,w,h);
  course_touch(&m,(void*)1,TOUCH_ENDED,452,220,w,h);
  tick(&m,10);
  assert(m.ghost.ui.page==GHOST_UI_RIVAL&&m.ghost.area_slot==7);
  m.back=1;tick(&m,1);
  assert(m.ghost.ui.page==GHOST_UI_COURSE&&m.ghost.ui.sel==6&&m.ghost.ui.scroll==-176&&m.ghost.ui.position==4);

  move(&m,1);
  assert(m.ghost.ui.sel==7&&m.ghost.ui.position==5);
  assert(ghost_hit(&m,432,209)==16); /* visible Fukuoka inside Hakone's transparent left padding */
  assert(ghost_hit(&m,540,225)==17);
  course_touch(&m,(void*)1,TOUCH_BEGAN,324,209,w,h);
  course_touch(&m,(void*)1,TOUCH_ENDED,324,209,w,h);
  assert(m.ghost.ui.sel==5&&m.ghost.ui.from<0&&!m.ghost.ui.deciding); /* direct nonadjacent tap */

  /* At 4:3 only the sliver at x630..640 is visible. The same authored
   * card is fully exposed by the wider Android viewport. */
  assert(ghost_original_focus_course(&m.ghost.ui,4));
  assert(ghost_hit(&m,635,209)==17);
  course_touch(&m,(void*)1,TOUCH_BEGAN,635,209,w,h);
  course_touch(&m,(void*)1,TOUCH_ENDED,635,209,w,h);
  assert(m.ghost.ui.sel==7&&m.ghost.ui.from<0&&m.ghost.ui.scroll==-176);
 }
 test_edge=old_edge;
}

static void check_player_replay_menu(void) {
 menu_state m={0};
 menu_ghost_open(&m);
 menu_ghost_directory_row rows[2]={REAL_ROWS[0],REAL_ROWS[0]};
 rows[1].source_kind=MENU_GHOST_SOURCE_CLOUD;
 rows[1].record_index=MENU_GHOST_CLOUD_RECORDS;
 rows[1].areas[0].ramp=CAR_GHOST_TA_RAMP_BASE+1;
 rows[1].areas[0].route=0;
 assert(rows[1].areas[0].native_available);
 menu_ghost_directory_view view={.rows=rows,.count=2,.epoch=1,.player_level=-1};
 assert(menu_ghost_set_directory(&m,&view));
 m.ghost.level=rows[1].areas[0].level;
 ghost_rivals(&m,0);
 assert(m.ghost.directory_row==1);
 assert(!menu_ghost_set_map(&m,rows[1].areas[0].ramp,0)); /* legacy actions stay original-only */
 assert(ghost_arcade_request(&m));
 unsigned request=0;
 assert(menu_ghost_take_action(&m,&request)==MENU_GHOST_CHALLENGE_CLOUD);
 assert(m.ghost.request_ramp==CAR_GHOST_TA_RAMP_BASE+1 && m.ghost.request_route==0);
 assert(menu_ghost_complete(&m,request,1,NULL) && menu_ghost_begin_pre(&m));

 menu_ghost_open(&m);
 m.ghost.search_kind=3;
 ghost_page(&m,GHOST_UI_NAME);
 menu_ghost_set_availability(&m,0,1,0);
 assert(menu_ghost_name_glyphs(m.ghost.query,rows[1].name));
 ghost_name_input(&m,275);
 uint16_t name[5]={0};
 assert(menu_ghost_search_query(&m,name)==5 && m.ghost.ui.page==GHOST_UI_NAME);
 assert(!memcmp(name,rows[1].name,sizeof name));
 assert(menu_ghost_set_directory(&m,NULL));
 view.epoch++;
 assert(menu_ghost_set_directory(&m,&view) && m.ghost.ui.page==GHOST_UI_NAME);
 menu_ghost_search_complete(&m,1);
 assert(m.ghost.ui.page==GHOST_UI_COURSE && m.ghost.previous_query_valid);
}

static void selected_profile(menu_state*m,int record,int area){menu_ghost_open(m);m->ghost.search_kind=3;assert(menu_ghost_name_glyphs(m->ghost.query,REAL_ROWS[record].name));ghost_rivals(m,area);
 int sel=-1;for(int i=0;i<m->ghost.ui.count;++i)if(ghost_directory_index(m,i)==record){sel=i;break;}assert(sel>=0);m->ghost.ui.sel=sel;m->ghost.directory_row=record;
 const menu_ghost_directory_area*a=&REAL_ROWS[record].areas[area];assert(menu_ghost_set_map(m,a->ramp,a->route));}
int main(void){
 check_card_fields();
 _Static_assert(MENU_GHOST_ACTION_NONE==0&&MENU_GHOST_RECORD_LOCAL==1&&MENU_GHOST_CHALLENGE_LOCAL==2&&MENU_GHOST_FETCH_KING==3&&MENU_GHOST_CHALLENGE_KING==4&&MENU_GHOST_SUBMIT_CLAIM==5&&MENU_GHOST_CHALLENGE_ARCADE==6,"stable action IDs");
 setup_ids();check_player_replay_menu();menu_state m;memset(&m,0,sizeof m);menu_ghost_open(&m);
 assert(!ghost_root_available(&m,0)&&!ghost_root_available(&m,1)&&!ghost_root_available(&m,2)&&!ghost_root_available(&m,3));
 menu_ghost_directory_view view={.rows=REAL_ROWS,.count=196,.epoch=1,.player_level=-1};assert(menu_ghost_set_directory(&m,&view));
 assert(ghost_root_available(&m,0)&&!ghost_root_available(&m,1)&&!ghost_root_available(&m,2)&&ghost_root_available(&m,3));
 check_course_taps(&m);
 short glyph[5];unsigned profiles=0;
 for(int i=0;i<196;++i){assert(menu_ghost_name_glyphs(glyph,REAL_ROWS[i].name));for(int j=0;j<5;++j)assert(glyph[j]>=0&&NAMEDB_WCHAR[glyph[j]]==REAL_ROWS[i].name[j]);for(int a=0;a<8;++a)profiles+=!!REAL_ROWS[i].areas[a].native_available;}
 assert(profiles==1267);uint16_t invalid[5]={0xd800,0,0,0,0};assert(!menu_ghost_name_glyphs(glyph,invalid));
 for(int wide=0;wide<2;++wide){test_edge=wide?213.33333f:0;
  for(int slot=0;slot<4;++slot){m.ghost.ui.sel=slot;hit_center(&m,slot);}m.ghost.ui.sel=0;
  draw_ghost_hub(&m,0,0,wide?1706.6666f:1024,768,NULL,NULL);assert(saw_disabled_history&&saw_disabled_revenge);if(!wide)capture("root",&m);
  m.ghost.ui.sel=1;gas(&m);assert(m.ghost.ui.page==GHOST_UI_SEARCH&&!m.ghost.pending_action);
  m.ghost.ui.sel=2;gas(&m);assert(m.ghost.ui.page==GHOST_UI_SEARCH&&!m.ghost.pending_action);
  m.ghost.ui.sel=0;gas(&m);assert(m.ghost.ui.page==GHOST_UI_LEVEL);
  for(int l=0;l<10;++l){m.ghost.ui.sel=l;hit_center(&m,l);draw_ghost_hub(&m,0,0,1024,768,NULL,NULL);}m.ghost.ui.sel=REAL_ROWS[0].areas[0].level;if(!wide)capture("level",&m);
  gas(&m);assert(m.ghost.ui.page==GHOST_UI_COURSE);
  for(int v=0;v<8;++v){assert(ghost_original_focus_course(&m.ghost.ui,v));hit_center(&m,v);draw_ghost_hub(&m,0,0,1024,768,NULL,NULL);assert(menu_ghost_course_area(v)==(v==6?7:v==7?6:v));}
  m.ghost.ui.sel=0;m.ghost.ui.scroll=0;m.ghost.ui.position=0;if(!wide)capture("course",&m);gas(&m);assert(m.ghost.ui.page==GHOST_UI_RIVAL&&m.ghost.ui.count>0);hit_center(&m,m.ghost.ui.sel);draw_ghost_hub(&m,0,0,1024,768,NULL,NULL);if(!wide)capture("rival",&m);
  if(m.ghost.ui.count>1){int old=m.ghost.ui.sel;move(&m,1);assert(m.ghost.ui.sel==old+1&&m.ghost.ui.from<0);}
  m.back=1;tick(&m,1);assert(m.ghost.ui.page==GHOST_UI_COURSE);m.back=1;tick(&m,1);assert(m.ghost.ui.page==GHOST_UI_LEVEL);m.back=1;tick(&m,1);assert(m.ghost.ui.page==GHOST_UI_SEARCH);
  int serial=m.ghost.request_serial;float r[4];assert(ghost_original_rect(ghost_original_bind(),&m.ghost.ui,0,r));float x=(r[0]+r[2])*.5f,y=(r[1]+r[3])*.5f;
  touch(&m,(void*)1,TOUCH_BEGAN,x,y);touch(&m,(void*)2,TOUCH_ENDED,x,y);assert(m.ghost.touch==(void*)1);touch(&m,(void*)1,TOUCH_CANCELLED,x,y);assert(!m.ghost.touch&&m.ghost.request_serial==(unsigned)serial&&!m.ghost.ui.deciding);
  touch(&m,(void*)1,TOUCH_BEGAN,x,y);touch(&m,(void*)1,TOUCH_ENDED,x,y);assert(m.ghost.ui.deciding==10);tick(&m,9);assert(m.ghost.ui.page==GHOST_UI_SEARCH);tick(&m,1);assert(m.ghost.ui.page==GHOST_UI_LEVEL);
  m.back=1;tick(&m,1);move(&m,1);assert(m.ghost.ui.from<0);move(&m,-1);assert(m.ghost.ui.sel==0);
 }
 /* Real names: all196 exact Unicode queries select the original record IDs. */
 short player_name[5]={1,2,3,4,5};memcpy(m.name,player_name,sizeof player_name);m.garage_changed=0;
 for(int i=0;i<196;++i){menu_ghost_open(&m);m.ghost.ui.sel=3;gas(&m);assert(m.ghost.ui.page==GHOST_UI_NAME_TYPE);if(!i)capture("name_type",&m);hit_center(&m,0);gas(&m);assert(m.ghost.ui.page==GHOST_UI_NAME);
  menu_ghost_name_glyphs(m.ghost.query,REAL_ROWS[i].name);if(!i)capture("name",&m);draw_ghost_hub(&m,0,0,1024,768,NULL,NULL);ghost_name_input(&m,275);assert(m.ghost.ui.page==GHOST_UI_COURSE);assert(ghost_row_matches(&m,(unsigned)i,-1,-1));
  assert(!memcmp(m.name,player_name,sizeof player_name)&&!m.garage_changed);m.back=1;tick(&m,1);assert(m.ghost.ui.page==GHOST_UI_NAME);for(int n=0;n<5;++n){m.back=1;tick(&m,1);}assert(!ghost_query_length(&m));m.back=1;tick(&m,1);assert(m.ghost.ui.page==GHOST_UI_NAME_TYPE);assert(m.ghost.previous_query_valid);
 }
 /* Actual numeric keyboard: released original grid keys only change query. */
 gas(&m);assert(m.ghost.ui.page==GHOST_UI_NAME);
 topbar_message=-1;
 draw_ghost_hub(&m,0,0,1024,768,NULL,NULL);
 assert(topbar_message==6351); /* Original name prompt, not the tournament member tile. */
 for(int wide=0;wide<2;++wide){test_edge=wide?213.33333f:0;float tabs[6][4];
  for(int k=0;k<6;++k){assert(ghost_name_tab(&m,k,NULL,NULL,tabs[k]));assert(tabs[k][1]>=366&&tabs[k][3]<=394);
   for(int j=0;j<k;++j)assert(!overlap(tabs[k],tabs[j]));
   const float hud[4][4]={{22/1.6f-test_edge,634/1.6f,226/1.6f-test_edge,726/1.6f},{798/1.6f+test_edge,634/1.6f,1002/1.6f+test_edge,726/1.6f},
    {722/1.6f+test_edge,46/1.6f,806/1.6f+test_edge,106/1.6f},{622/1.6f+test_edge,46/1.6f,706/1.6f+test_edge,106/1.6f}};
   for(int j=0;j<4;++j)assert(!overlap(tabs[k],hud[j]));
   float x=(tabs[k][0]+tabs[k][2])*.5f,y=(tabs[k][1]+tabs[k][3])*.5f;assert(!hud_menu_key(x*1.6f,y*1.6f)&&ghost_hit(&m,x,y)==270+k);
   int old=m.ghost.query_page;touch(&m,(void*)8,TOUCH_BEGAN,x,y);touch(&m,(void*)8,TOUCH_CANCELLED,x,y);assert(m.ghost.query_page==old&&m.ghost.ui.page==GHOST_UI_NAME);
   touch(&m,(void*)8,TOUCH_BEGAN,x,y);touch(&m,(void*)8,TOUCH_ENDED,x,y);if(k<5)assert(m.ghost.query_page==k);else assert(m.ghost.ui.page==GHOST_UI_NAME&&!ghost_query_length(&m));
  }
  for(int page=0;page<5;++page){m.ghost.query_page=page;
   for(int key=0;key<60;++key)if(ghost_name_grid(&m,key)!=-1){float x=NAMEDB_GRID_X[key%20],y=NAMEDB_GRID_Y[key/20];
    const float glyph[4]={x,y,x+32,y+32},pop[4]={x-4.8f,y-4.8f,x+36.8f,y+36.8f};
    for(int k=0;k<6;++k){assert(!overlap(glyph,tabs[k]));assert(!overlap(pop,tabs[k]));}
   }
  }
  touch(&m,(void*)8,TOUCH_BEGAN,GHOST_NAME_TAB_X[0],GHOST_NAME_TAB_Y);touch(&m,(void*)8,TOUCH_ENDED,GHOST_NAME_TAB_X[0],GHOST_NAME_TAB_Y);assert(m.ghost.query_page==0);
 }
 touch(&m,(void*)3,TOUCH_BEGAN,NAMEDB_GRID_X[3]+12,NAMEDB_GRID_Y[0]+16);touch(&m,(void*)3,TOUCH_ENDED,NAMEDB_GRID_X[3]+12,NAMEDB_GRID_Y[0]+16);assert(ghost_query_length(&m)==1&&NAMEDB_WCHAR[m.ghost.query[0]]==0xff13);assert(!m.garage_changed&&!memcmp(m.name,player_name,sizeof player_name));
 assert(!ghost_name_touch_code(&m,NAN,20)&&!ghost_name_touch_code(&m,20,1e30f));
 /* Every genuine recorded profile gets one exact immutable request, never a fake
  * name-derived identity or class-as-level fallback. This does not play a car. */
 unsigned admitted=0;
 for(int i=0;i<196;++i)for(int a=0;a<8;++a)if(REAL_ROWS[i].areas[a].native_available){selected_profile(&m,i,a);assert(menu_ghost_request(&m,MENU_GHOST_CHALLENGE_ARCADE));unsigned id=0;assert(menu_ghost_take_action(&m,&id)==6&&id);assert(!menu_ghost_take_action(&m,&id));id=m.ghost.active_request;
  assert(m.ghost.request_record_index==(unsigned)i&&m.ghost.request_area_slot==a&&m.ghost.request_catalog_epoch==view.epoch);assert(m.ghost.request_id_devel==REAL_ROWS[i].id_devel&&m.ghost.request_id1==REAL_ROWS[i].id1&&m.ghost.request_id2==REAL_ROWS[i].id2);assert(m.ghost.request_ramp==REAL_ROWS[i].areas[a].ramp&&m.ghost.request_route==REAL_ROWS[i].areas[a].route);
  assert(menu_ghost_complete(&m,id,1,NULL)&&!menu_ghost_complete(&m,id,1,NULL));assert(menu_ghost_begin_pre(&m)&&menu_ghost_preparing(&m));menu_ghost_open(&m);assert(!menu_ghost_complete(&m,id,1,"STALE")&&!menu_ghost_begin_pre(&m));++admitted;
 }
 assert(admitted==1267);
 selected_profile(&m,0,0);assert(menu_ghost_request(&m,6));unsigned id=0;assert(menu_ghost_take_action(&m,&id)==6);assert(menu_ghost_complete(&m,id,1,NULL)&&menu_ghost_begin_pre(&m));tick(&m,600);assert(!m.ghost.pre_go);m.ready=1;assert(menu_update(&m,1.0f/60.0f)==1&&m.ghost.pre_go);tick(&m,600);
 menu_ghost_race_finished(&m,MENU_GHOST_RESULT_LOSE,0);
 assert(m.ghost.ui.page==GHOST_UI_SEARCH&&m.ghost.result==MENU_GHOST_RESULT_LOSE&&!m.ghost.claim_eligible);
 selected_profile(&m,0,0);assert(menu_ghost_request(&m,6));id=0;assert(menu_ghost_take_action(&m,&id)==6);++view.epoch;assert(menu_ghost_set_directory(&m,&view));assert(!menu_ghost_complete(&m,id,1,NULL)&&!m.ghost.active_request);
 selected_profile(&m,0,0);assert(menu_ghost_request(&m,6));id=0;assert(menu_ghost_take_action(&m,&id)==6);assert(menu_ghost_complete(&m,id,1,NULL)&&menu_ghost_begin_pre(&m));assert(menu_ghost_set_directory(&m,NULL)&&m.screen==MENU_GHOST&&!menu_ghost_preparing(&m));
 assert(!menu_ghost_request(&m,6)&&!menu_ghost_request(&m,3)&&!menu_ghost_request(&m,4)&&!menu_ghost_request(&m,5));
 assert(menu_ghost_set_directory(&m,&view));menu_ghost_directory_view bad=view;bad.count=MENU_GHOST_DIRECTORY_MAX_RECORDS+1u;assert(!menu_ghost_set_directory(&m,&bad));menu_ghost_directory_row duplicate[2]={REAL_ROWS[0],REAL_ROWS[1]};duplicate[1].record_index=duplicate[0].record_index;bad=view;bad.rows=duplicate;bad.count=2;assert(!menu_ghost_set_directory(&m,&bad));
 for(int wide=0;wide<2;++wide) {
  test_edge=wide?213.33333f:0;
  menu_ghost_open(&m);m.ghost.ui.sel=3;
  menu_option_draws=0;draw_ghost_hub(&m,0,0,1024,768,NULL,NULL);
  assert(!menu_option_draws);
  menu_touch(&m,(void*)9,TOUCH_BEGAN,664+test_edge*1.6f,72);
  assert(!m.ghost.touch);
  menu_touch(&m,(void*)9,TOUCH_ENDED,664+test_edge*1.6f,72);
  m.option=1;tick(&m,1);
  assert(m.ghost.ui.page==GHOST_UI_SEARCH&&m.ghost.ui.sel==3);
  assert(!m.ghost.pending_action&&!m.ghost.active_request);
 }
 assert(source_hits&&source_draws&&draw_calls&&part_calls);
 printf("PASS full production menu: genuine196 Unicode/name filters; real1267 immutable request/PRE gates; authored Search/Level/Course8/Rival/Name geometry; narrow/wide capture/cancel/Back; result callback and removed Record entry; source_rect_hits=%u source_draws=%u. Host menu only, not native-play/GPU/device evidence.\n",source_hits,source_draws);
 return 0;
}
