#include PORT_MENU
#include <assert.h>
void snd_menu(int x) { (void)x; }
static int drawn_frame, drawn_count, hidden[9];
int anm_sprite(int id) { return id; }
int anm_sprite_rect(int anim, int frame, int sprite, float r[4]) {
  (void)anim; (void)frame;
  for (int i=0;i<9;++i) if (sprite==TG_SEL_ICON[0][i]) {
    r[0]=i*50; r[1]=100; r[2]=i*50+30; r[3]=130; return 1;
  }
  return 0;
}
void anm_draw(int a,int f,float z) { (void)a;(void)f;(void)z; }
void anm_draw_xy(int a,int f,float z,float x,float y,float sx,float sy,const anm_swap *s,int n) { (void)a;(void)f;(void)z;(void)x;(void)y;(void)sx;(void)sy;(void)s;(void)n; }
void anm_draw_sprite(int a,float x,float y,float z) { (void)a;(void)x;(void)y;(void)z; }
void anm_draw_ex(int a,int f,float z,float x,float y,const anm_swap *s,int n) {
  (void)z;(void)x;(void)y;
  if (a != ID.tg_all[0]) return;
  drawn_frame=f; drawn_count=n; memset(hidden,0,sizeof hidden);
  for(int j=0;j<n;++j) for(int i=0;i<9;++i)
    if(s[j].from==TG_SEL_ICON[0][i] && s[j].to==-1) hidden[i]=1;
}
static void select_pack(menu_state *m, const char *pack) {
  for (int a=0; a<CARDB_ALL; ++a) for (int b=0; b<CARDB_NCARS[a]; ++b)
    if (!strcmp(CARDB_PACKS[CARDB_CARS[a][b].colors[0].pack],pack)) { m->maker=a; m->car=b; return; }
  assert(!"pack missing");
}
int main(void) {
  menu_state m={0}; select_pack(&m,"nis_R35"); int mk=m.maker,c=m.car;
  assert(tg_wheels_only(&m) && !tg_gem(&m));
  ID.tg_all[0]=123; ID.top=321; ID.bottom=322;
  /* A new car has no selectable wheel: only refusal is drawn and reachable. */
  m.dress_kind=-1; m.dress_free=1; tg_select_open(&m);
  assert(m.sel==0 && !tg_sel_open_ok(&m,0)); m.card_t=TG_FADE;
  draw_tg_select(&m,0,NULL,NULL); assert(drawn_frame/100==0 && drawn_count==10);
  for(int i=0;i<9;++i) assert(hidden[i]==(i!=0));
  tg_select_step(&m,0,1); assert(m.sel==0 && !m.deciding);
  m.tap_y=110; m.tap_x=105; tg_select_step(&m,1,0); assert(m.sel==0 && !m.deciding);
  m.tap_x=5; tg_select_step(&m,1,0); assert(m.sel==0 && m.deciding);
  tg_select_done(&m); assert(m.screen==MENU_SETTING);
  /* A saved custom wheel enables the option even below the first unlock. */
  m.wheel[mk][c]=1; m.dress_kind=-1; tg_select_open(&m); assert(m.sel==2);
  m.card_t=TG_FADE; draw_tg_select(&m,0,NULL,NULL); assert(!hidden[2]);
  tg_select_step(&m,0,-1); assert(m.sel==0); tg_select_step(&m,0,1); assert(m.sel==2);
  m.wheel[mk][c]=0;
  /* First won wheel independently enables it without changing the old save. */
  int first_wheel=1; while(first_wheel<=63 && DRESS_LADDER[0][first_wheel][0]!=0) ++first_wheel;
  assert(first_wheel<=63); m.dress_lv[mk][c]=first_wheel; m.dress_kind=-1; tg_select_open(&m);
  assert(m.sel==2 && tg_sel_open_ok(&m,0)); m.card_t=TG_FADE;
  draw_tg_select(&m,0,NULL,NULL); assert(drawn_count==9 && !hidden[2]);
  m.dress_kind=-1; m.dress_lv[mk][c]=63; tg_select_open(&m);
  assert(m.sel==2 && m.screen==MENU_TG_SELECT);
  m.card_t=TG_FADE; draw_tg_select(&m,0,NULL,NULL);
  assert(drawn_frame/100==2 && drawn_count==9);
  for(int i=0;i<9;++i) assert(hidden[i]==(i!=0 && i!=2));
  tg_select_step(&m,0,-1); assert(m.sel==0 && !m.tg.move);
  draw_tg_select(&m,0,NULL,NULL); assert(drawn_frame/100==0);
  tg_select_step(&m,0,1); assert(m.sel==2 && !m.tg.move);
  m.tap_y=110; m.tap_x=5; tg_select_step(&m,1,0); assert(m.sel==0 && !m.deciding);
  m.tap_x=105; tg_select_step(&m,1,0); assert(m.sel==2 && !m.deciding);
  m.tap_x=55; tg_select_step(&m,1,0); assert(m.sel==2 && !m.deciding);
  m.tap_x=105; tg_select_step(&m,1,0); assert(m.deciding>0 && m.tg.decided);
  m.aero[mk][c]=3; m.bonnet[mk][c]=2; m.wing[mk][c]=4; m.mirror[mk][c]=1; m.neon[mk][c]=2; m.vinyl[mk][c]=3;
  m.dress_lv[mk][c]=63; m.tg.gem=0;
  for (int k=1;k<=8;++k) assert(!tg_sel_open_ok(&m,k));
  assert(tg_sel_open_ok(&m,0) && tg_sel_open_ok(&m,9)); m.dress_free=1;
  for(int s=1;s<9;++s) if(s!=2) { m.tg.gem=0; m.sel=s; tg_select_done(&m); assert(m.screen==MENU_TG_SELECT); }
  m.tg.gem=0; m.sel=2; tg_select_done(&m); assert(m.screen==MENU_TG_MAKER);
  m.tg.gem=0; m.sel=0; tg_select_done(&m); assert(m.screen==MENU_SETTING);
  m.dress_lv[mk][c]=0; m.n_dress_due=0; menu_dress_win(&m,63); assert(m.dress_lv[mk][c]==63);
  for(int i=0;i<m.n_dress_due;++i) assert(DRESS_LADDER[0][m.dress_due[i]][0]==0);
  while(tg_due(&m)) assert(m.screen==MENU_TG_GET && m.tg.kind==0);
  for(int lv=1;lv<=63;++lv) {
    m.dress_lv[mk][c]=lv-1; m.n_dress_due=0; menu_dress_win(&m,1);
    assert(m.n_dress_due == (DRESS_LADDER[0][lv][0]==0));
    if(m.n_dress_due) { assert(tg_due(&m)); assert(m.tg.kind==0 && m.tg.lv==lv); }
  }
  m.dress_due_maker=mk; m.dress_due_car=c; m.n_dress_due=1;
  int forbidden=1; while(forbidden<=63 && DRESS_LADDER[0][forbidden][0]==0) ++forbidden;
  assert(forbidden<=63); m.dress_due[0]=forbidden; assert(!tg_due(&m));
  assert(m.aero[mk][c]==3 && m.bonnet[mk][c]==2 && m.wing[mk][c]==4 && m.mirror[mk][c]==1 && m.neon[mk][c]==2 && m.vinyl[mk][c]==3);
  select_pack(&m,"nis_R35_specV"); assert(!tg_wheels_only(&m)); m.dress_lv[m.maker][m.car]=0; menu_dress_win(&m,2);
  assert(m.n_dress_due>0); select_pack(&m,"nis_R35"); assert(!tg_due(&m));
  select_pack(&m,"nis_R35_specV"); m.tg.gem=tg_gem(&m); m.dress_lv[m.maker][m.car]=63;
  assert(tg_sel_open_ok(&m,1) && tg_sel_open_ok(&m,2));
  m.dress_kind=-1; tg_select_open(&m); m.card_t=TG_FADE; draw_tg_select(&m,0,NULL,NULL); assert(drawn_count==1);
  m.sel=2; m.tg.move=0; tg_select_step(&m,0,-1); assert(m.sel==1 && m.tg.move==-1);
  for(int a=0;a<CARDB_ALL;++a) for(int b=0;b<CARDB_NCARS[a];++b) { m.maker=a;m.car=b; if(tg_gem(&m)) { assert(!tg_wheels_only(&m)); m.tg.gem=1; assert(tg_sel_open_ok(&m,5)); goto found; } }
  assert(!"gem missing");
found: select_pack(&m,"nis_R35"); assert(m.aero[mk][c]==3 && m.wing[mk][c]==4); puts("R35 dress tests passed");
}
