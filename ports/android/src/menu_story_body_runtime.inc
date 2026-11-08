/* Exact render-only semantic stamps. body_row_for is the existing private
 * source-derived maker/car/factory -> raw_model map; no pack/paint inversion. */
int menu_story_body_for_profile(int maker,int car,int color,int power,int handling,int direct_full,story_body_view *out) {
  if (!out) return 0;
  memset(out,0,sizeof *out);
  const body_color_row *r=body_row_for(maker,car,color);
  return r && story_body_view_capture_model(out,r->pack,r->raw_model,r->type,power,handling,direct_full);
}
int menu_story_body_get(const menu_state *m,menu_story_body_stamp *out) {
  if (!out) return 0;
  memset(out,0,sizeof *out);
  if (!m || !body_row(m) || m->save_slot<0 || m->save_slot>MENU_SAVES ||
      (m->save_skip!=0 && m->save_skip!=1) ||
      !menu_story_body_for_profile(m->maker,m->car,m->color,m->st_power[m->maker][m->car],
          m->st_handling[m->maker][m->car],m->tune_full[m->maker][m->car],&out->view)) return 0;
  out->kind=1;out->context=m->screen;out->peer=-1;
  out->maker=m->maker;out->car=m->car;out->color=m->color;
  out->save_slot=m->save_slot;out->save_skip=m->save_skip;
  out->own_index=m->save_skip ? -1 : menu_own_find(m,m->maker,m->car);
  if (out->own_index>=0) out->born=m->own[out->own_index].born;
  return 1;
}
int menu_story_body_owner_same(const menu_state *m,const menu_story_body_stamp *old) {
  if (!m || !old || old->kind!=1 || !old->view.valid ||
      m->maker!=old->maker || m->car!=old->car || m->color!=old->color ||
      m->save_slot!=old->save_slot || m->save_skip!=old->save_skip) return 0;
  const body_color_row *r=body_row(m);
  int own=m->save_skip ? -1 : menu_own_find(m,m->maker,m->car);
  return r && r->raw_model==old->view.raw_model && r->pack==old->view.pack && r->type==old->view.type &&
      own==old->own_index && (own<0 || m->own[own].born==old->born);
}
int menu_story_body_same(const menu_state *m,const menu_story_body_stamp *old) {
  return menu_story_body_owner_same(m,old) && old->context==m->screen &&
      old->view.earned_power==m->st_power[m->maker][m->car] &&
      old->view.earned_handling==m->st_handling[m->maker][m->car] &&
      old->view.direct_full==m->tune_full[m->maker][m->car];
}
int menu_story_body_scene_view(const menu_state *m,const menu_car *car,story_body_view *out) {
  if (!m || !car || !out) return 0;
  memset(out,0,sizeof *out);
  if (!car->story_body_valid) {
    /* Unknown/purchase/movie owns no earned state, but a known pack retains its
     * original DefaultGet (notably GDBF-.5), never another car's tuned height. */
    out->valid=1;out->pack=car->pack;out->raw_model=-1;
    out->body_y=story_body_height(car->pack,0);return 1;
  }
  const menu_story_body_stamp *s=&car->story_body;
  if (!s->view.valid || car->pack!=s->view.pack) return 0;
  if (s->kind==1) {
    if (m->new_card || !menu_story_body_same(m,s)) return 0;
  } else if (s->kind==2) {
    int i=s->peer;
    if (m->screen!=MENU_VS_MATCH || s->context!=m->screen || i<0 || i>=m->vs.match_n || i>=MENU_VS_PLAYERS ||
        !m->vs.match[i].base_valid || m->vs.match[i].maker!=s->maker ||
        m->vs.match[i].car!=s->car || m->vs.match[i].color!=s->color ||
        m->vs.match[i].base_power!=s->view.earned_power || m->vs.match[i].base_handling!=s->view.earned_handling) return 0;
    story_body_view exact;
    if (!menu_story_body_for_profile(s->maker,s->car,s->color,s->view.earned_power,s->view.earned_handling,0,&exact) ||
        exact.raw_model!=s->view.raw_model || exact.pack!=s->view.pack || exact.type!=s->view.type) return 0;
  } else return 0;
  *out=s->view;return 1;
}
