/* Complete production menu_update/menu_touch, with existing host state fixture.
 * Optional private generated headers are read-only compile inputs, not fixtures. */
#define main previous_story_test_main
#include "story_timezone_host.c"
#undef main

static float test_edge;
int anm_find(const char *n) {(void)n;return 1;}
int anm_frames(int n) {(void)n;return 600;}
float anm_edge(void) { return test_edge * 1.6f; }
float anm_sprite_width(int s) { (void)s; return 256; }
float anm_sprite_height(int s) { (void)s; return 256; }
int hud_menu_key(float x, float y) {
  float e = test_edge * 1.6f;
  if (x >= 22-e && x <= 226-e && y >= 634 && y <= 726) return -1;
  if (x >= 798+e && x <= 1002+e && y >= 634 && y <= 726) return 1;
  if (x >= 722+e && x <= 806+e && y >= 46 && y <= 106) return HUD_MENU_BACK;
  if (x >= 622+e && x <= 706+e && y >= 46 && y <= 106) return HUD_MENU_OPTION;
  return 0;
}
static void home(menu_state *m, int selected) {
  memset(m, 0, sizeof *m);
  m->screen = MENU_GAME;
  m->sel = selected;
  m->from = -1;
  m->story_pick = -1;
  m->game = GAME_MODE[selected].game;
}
static void author_touch(menu_state *m, void *id, int phase, float x, float y) {
  menu_touch(m, id, phase, x*1.6f, y*1.6f);
}
int main(void) {
  menu_state m;
  const int screens[5] = {MENU_ST_LEVEL, MENU_TEN_COURSE, MENU_MODE, MENU_VS_SEL, MENU_GHOST};
  const int ghost_slot=game_slot(MENU_GAME_GHOST);
  for (int s=0; s<5; ++s) {
    home(&m, s); m.deciding=1;
    assert(menu_update(&m, 1.0f/60.0f)==0);
    assert(m.screen==screens[GAME_MODE[s].game] && m.game==GAME_MODE[s].game);
  }
  for (int width=0; width<2; ++width) {
    test_edge=width?213.33333f:0;
    for (int s=0;s<5;++s) for (int d=-1;d<=1;d+=2) {
      home(&m,s);m.key=d;tick(&m,1);
      int target=s+d;
      if(target<0||target>=5) assert(m.sel==s&&m.from==-1);
      else { assert(m.sel==target&&m.from==s);tick(&m,4);assert(m.from==-1&&m.t==0); }
    }
    home(&m,ghost_slot);menu_mode_rect r[5];assert(game_rects(&m,r));
    float x=r[ghost_slot].x+r[ghost_slot].w*.5f;
    author_touch(&m,(void*)1,TOUCH_BEGAN,x,192);
    tick(&m,1);assert(m.deciding==30&&m.screen==MENU_GAME);
    author_touch(&m,(void*)1,TOUCH_ENDED,x,192);
    tick(&m,29);assert(m.screen==MENU_GAME&&m.deciding==1);
    tick(&m,1);assert(m.screen==MENU_GHOST&&m.game==4);
    for(int t=0;t<600;++t)assert(!menu_update(&m,1.0f/60.0f));
    /* Actual upstream non-touch inputs, not only the pointer adapter. */
    m.key=1;tick(&m,1);assert(m.ghost.ui.sel==1&&m.ghost.ui.from==0);
    tick(&m,3);assert(m.ghost.ui.from==-1);
    m.tap=1;tick(&m,1);assert(!m.ghost.pending_action&&strstr(m.ghost.note,"DIRECTORY"));
    m.option=1;tick(&m,1);assert(m.ghost.ui.page==GHOST_UI_SEARCH&&m.ghost.ui.sel==1);
    /* The old settings-button location has no Ghost action. */
    menu_touch(&m,(void*)9,TOUCH_BEGAN,664+test_edge*1.6f,72);
    assert(!m.ghost.touch);
    menu_touch(&m,(void*)9,TOUCH_ENDED,664+test_edge*1.6f,72);
    assert(m.ghost.ui.page==GHOST_UI_SEARCH&&!m.ghost.pending_action);
    assert(menu_ghost_request(&m,MENU_GHOST_RECORD_LOCAL));
    unsigned id=0;assert(menu_ghost_take_action(&m,&id)==MENU_GHOST_RECORD_LOCAL&&id);
    /* Real captured Back release returns to visual slot4, never a WV1 screen. */
    menu_touch(&m,(void*)3,TOUCH_BEGAN,760+test_edge*1.6f,70);
    assert(!m.back);menu_touch(&m,(void*)3,TOUCH_ENDED,760+test_edge*1.6f,70);
    tick(&m,1);assert(m.screen==MENU_GAME&&m.sel==ghost_slot&&!m.ghost.active_request);
    assert(!menu_ghost_complete(&m,id,1,"STALE"));
  }
  menu_ghost_open(&m);
  assert(!menu_ghost_begin_pre(&m));
  assert(menu_ghost_request(&m,MENU_GHOST_RECORD_LOCAL));
  unsigned ready_id=0;assert(menu_ghost_take_action(&m,&ready_id)==MENU_GHOST_RECORD_LOCAL);
  assert(!menu_ghost_begin_pre(&m));
  assert(menu_ghost_complete(&m,ready_id,1,NULL));
  assert(menu_ghost_begin_pre(&m)&&menu_ghost_preparing(&m)&&!m.ready);
  assert(!menu_ghost_begin_pre(&m)&&!menu_ghost_set_map(&m,2,0));
  for(int t=0;t<600;t++)assert(!menu_update(&m,1.0f/60.0f));
  m.ready=1;assert(menu_update(&m,1.0f/60.0f)==1&&m.ghost.pre_go);
  for(int t=0;t<600;t++)assert(!menu_update(&m,1.0f/60.0f));
  m.back=1;tick(&m,1);assert(m.screen==MENU_GHOST&&!m.ghost.prepared_request&&!m.ghost.claim_eligible);
  assert(!menu_ghost_complete(&m,ready_id,1,"STALE")&&!menu_ghost_begin_pre(&m));
  m.screen=MENU_GHOST_PRE;m.ready=1; /* forging only the screen cannot bypass request admission */
  for(int t=0;t<600;t++)assert(!menu_update(&m,1.0f/60.0f));
  puts("PASS complete production menu: 5 routes, hard boundaries, 4/10/20 timing, ghost release/cancel/Back, PRE600wait/ready GO once/forged PRE rejected");
  return 0;
}
