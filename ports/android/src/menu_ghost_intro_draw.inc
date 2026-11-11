/* The Ghost matchup uses the 640x480 stage from clSeqTgMatchingInformation.
 * Draw the grid from Target_anm's plane and animate the original plate sprites
 * without requiring a newly converted menu.bin. */
static void ghost_intro_project(const mat4 *view,const float p[2],float out[3]) {
  const float y=-3.141f, *m=view->m;
  for (int i=0;i<3;++i) out[i]=m[i]*p[0]+m[i+4]*y+m[i+8]*p[1]+m[i+12];
}

static void ghost_intro_grid_line(const mat4 *view,const float ground[8]) {
  const float near=5.0f, focal=512.0f/tanf(27.5f*DEG);
  float xy[8];
  for (int i=0;i<4;i+=2) {
    float v[2][3];
    ghost_intro_project(view,ground+2*i,v[0]);
    ghost_intro_project(view,ground+2*i+2,v[1]);
    if (v[0][2]>-near && v[1][2]>-near) return;
    for (int j=0;j<2;++j) {
      if (v[j][2]>-near) {
        const float *far=v[1-j];
        float t=(-near-v[j][2])/(far[2]-v[j][2]);
        for (int k=0;k<2;++k) v[j][k]+=(far[k]-v[j][k])*t;
        v[j][2]=-near;
      }
      float sc=-focal/v[j][2];
      xy[2*(i+j)]=512.0f+v[j][0]*sc;
      xy[2*(i+j)+1]=384.0f-v[j][1]*sc;
    }
  }
  hud_ui_quad(xy,.46f,.46f,.49f,.42f);
}

static void ghost_intro_grid(const menu_state *m,float w,float h) {
  const typeof(GHOST_INTRO_POSE[0]) *p=&GHOST_INTRO_POSE[ghost_intro_pose(m)];
  const float up[3]={0,1,0}, z0=-2.274f, z1=347.976f, x0=-180.0f, x1=180.25f;
  mat4 view=mat4_look_at(p->eye,p->aim,up);
  hud_ui_begin(w,h);
  for (int i=0;i<=36;++i) {
    float x=x0+10.0f*i;
    const float line[8]={x,z0,x,z1,x+.25f,z0,x+.25f,z1};
    ghost_intro_grid_line(&view,line);
  }
  for (int i=0;i<=35;++i) {
    float z=z0+10.0f*i;
    const float line[8]={x0,z,x1,z,x0,z+.25f,x1,z+.25f};
    ghost_intro_grid_line(&view,line);
  }
  hud_ui_end();
}

static int ghost_intro_art(int sid) {
  int converted=130000+sid;
  return anm_sprite(converted)>=0 ? converted : sid;
}

static void ghost_intro_plate(const cardb_car *car,const short name[5],int cls,int title,
                             int power,int handling,int rival,int ph,int t,float w,float h) {
  if (!car) return;
  int anim=ph?ID.plate_ph:ID.plate;
  if (anim<0) return;
  /* menu_p_pre_tg_rival_car: the plate slots unfold over the first ten ticks. */
  float s=fminf(1.0f,.008f+.0992f*t), x=rival?532.0f:106.0f, y=398.0f-s;
  int tint=anm_sprite(rival?ghost_intro_art(3142):3141), blue=anm_sprite(3141);
  anm_swap sw[]={
    {anm_sprite(7450),anm_sprite(car->plate)}, {blue,tint},
    {anm_sprite(1391),-1}, {anm_sprite(1392),-1}, {anm_sprite(1389),-1},
    {anm_sprite(1390),-1}, {anm_sprite(1439),-1},
  };
  anm_draw_xy(anim,0,s,x,y,1,s,sw,sizeof sw/sizeof *sw);
  if (rival && tint<0 && blue>=0) {
    /* Existing packs contain the blue sprite only. Tint it to the rival's green. */
    const float src[4]={0,0,256,64}, dst[4]={x-128,y-56*s,x+128,y+8*s};
    const float mul[4]={.6f,1.7f,.65f,s}, add[4]={0,.16f,0,0};
    anm_draw_part_col(blue,src,dst,mul,add);
  }
  if (s<.95f) return;

  int n=0;
  while (n<5 && name[n]>=0 && name[n]<NAMEDB_N) ++n;
  for (int i=0;i<n;++i)
    anm_draw_sprite(anm_sprite(NAME_GLYPH5+name[i]),x-14.0f*n+28.0f*i,y-41.0f,1);
  int pre=anm_sprite(CARD_CLASSP+(cls>=0 && cls<=46?cls:0));
  float text_x=x-74.0f;
  if (pre>=0) {
    game_sprite(anm_sprite_id(pre),(menu_mode_rect){text_x,y-7,40,15},1);
    text_x+=33;
  }
  const unsigned short *glyphs;
  int count=title_glyphs(title,&glyphs);
  float scale=.46f, width=32;
  for (int i=0;i<count;++i) width+=title_glyph_half(glyphs[i])?16:28;
  scale=fminf(scale,(x+74-text_x)/width);
  for (int i=0;i<count;++i) {
    game_sprite(TITLE_GLYPH5+glyphs[i],(menu_mode_rect){text_x,y-7,32*scale,32*scale},1);
    text_x+=(title_glyph_half(glyphs[i])?16:28)*scale;
  }
  float r[4];
  char text[12];
  if (anm_sprite_rect(anim,0,anm_sprite(1391),r)) {
    snprintf(text,sizeof text,"%d",ph?power:car_tune_hp(car->hp,power));
    card_glyphs(CARD_GLYPH2,"-,",8.0f,text,x+r[0],y+r[1],1);
  }
  if (anm_sprite_rect(anim,0,anm_sprite(1392),r)) {
    if (ph) {
      snprintf(text,sizeof text,"%d",handling);
      card_glyphs(CARD_GLYPH2,"-,",8.0f,text,x+r[0],y+r[1],1);
    } else {
      static const char *const grade[]={"DG","D","B","G","HG"};
      int art=TA_UI_HANDLING[car_tune_grade(power,handling)];
      if (anm_sprite(art)>=0) game_sprite(art,(menu_mode_rect){x+r[0],y+r[1],20,13},1);
      else {
        hud_ui_begin(w,h);
        game_text(grade[car_tune_grade(power,handling)],x+r[0]+7,y+r[1]+2,1.7f,1);
        hud_ui_end();
      }
    }
  }
}

static void ghost_intro_overlay(const menu_state *m,float w,float h) {
  int t=m->ghost.intro_t;
  if (!ghost_intro_crown(m)) {
    /* menu_p_pre_tg_rival_vs_3: the VS art lands at (193,346). */
    int frame=t-GHOST_INTRO_VS;
    if (frame<8) return;
    float a=fminf(1,(frame-7)*.25f), z=.92f+.08f*a;
    game_sprite(4868,(menu_mode_rect){321-128*z,410-64*z,256*z,128*z},a);
    return;
  }
  int frame=t-GHOST_INTRO_CROWN;
  if (frame<0) return;
  unsigned area=(unsigned)m->ghost.request_area_slot;
  static const int crowns[]={1773,1779,1780,1781,1777,1778,1775,1776};
  const ghost_crown_art *crown=ghost_original_crown(area);
  if (!crown) return;
  /* menu_p_pre_tg_rival_crown: the area emblem shrinks in, rebounds, and holds. */
  float s=frame<7?2.0f-(2.0f-.5625f)*frame/7.0f:fminf(.75f,.5625f+.0625f*(frame-7));
  float y=frame<7?236.0f+16.0f*frame/7.0f:236.0f;
  if (frame<11) game_sprite(451,(menu_mode_rect){216,132,208,208},.22f*(1-frame/11.0f));
  int art=ghost_intro_art(crowns[area]);
  if (anm_sprite(art)<0) art=crown->menu;
  game_sprite(art,(menu_mode_rect){320-128*s,y-128*s,256*s,256*s},fminf(1,.25f+.11f*frame));
  if (frame>=10) {
    int title=ghost_intro_art(6601);
    if (anm_sprite(title)>=0) game_sprite(title,(menu_mode_rect){192,310,256,64},1);
    else {
      hud_ui_begin(w,h);
      game_text("STORE CHAMPION",320,332,3.5f,1);
      hud_ui_end();
    }
  }
}

static void draw_ghost_intro(const menu_state *m,float w,float h,void (*draw3d)(void *),void *ctx) {
  int t=m->ghost.intro_t, end=ghost_intro_end(m);
  anm_fill(.91f,.91f,.91f,1);
  if (ID.shogo_bg>=0) anm_draw(ID.shogo_bg,0,1);
  ghost_intro_grid(m,w,h);
  if (draw3d) draw3d(ctx);

  const menu_ghost_directory_row *r=ghost_intro_rival(m);
  if (r && t>=GHOST_INTRO_PLATES) {
    const menu_ghost_directory_area *a=&r->areas[m->ghost.request_area_slot];
    const cardb_car *own=chosen_car(m,m->car), *other=ghost_bound_car(a);
    short rival_name[5];
    menu_ghost_name_glyphs(rival_name,r->name);
    int power,handling;
    menu_tune(m,&power,&handling);
#if defined(__ANDROID__) || defined(WMMT_PRE_RACE_TEST)
    pre_race_tune draft=m->pre_tune;
    if (pre_race_tune_slot_matches(&draft,m->save_slot,m->save_skip))
      pre_race_tune_take(&draft,m->game,m->maker,m->car,power,handling,&power,&handling);
#endif
    int ph=has(own->label,"[R35]") || (other && has(other->label,"[R35]"));
    ghost_intro_plate(own,m->name,m->class_car[m->maker][m->car],menu_title(m),
                      power,handling,0,ph,t-GHOST_INTRO_PLATES,w,h);
    ghost_intro_plate(other,rival_name,(int)a->class_id,(int)a->title,
                      a->power,a->handling,1,ph,t-GHOST_INTRO_PLATES,w,h);
    ghost_intro_overlay(m,w,h);
  }
  float fade=t<GHOST_INTRO_FADE?1.0f-(float)t/GHOST_INTRO_FADE:
             t>end?(float)(t-end)/GHOST_INTRO_FADE:0;
  anm_fill(0,0,0,fade);
}
