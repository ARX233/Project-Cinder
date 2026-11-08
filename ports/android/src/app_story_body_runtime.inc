/* Whole-car presentation only. Permanent snapshots do not alias menu/native
 * physics/session allocation memory. Map object IDs may overlap the new groups,
 * hence every call restores the exact caller's three render parameters. */
static struct {
  int active;
  menu_story_body_stamp own;
  story_body_view rival[CAR_RIVALS];
} ASB;
static void app_story_body_clear(void) { memset(&ASB,0,sizeof ASB); }
static int app_story_body_peer(const net_player *peer,story_body_view *out) {
  if (!peer || !peer->live || !out) return 0;
  return menu_story_body_for_profile(peer->identity[0],peer->identity[1],peer->identity[2],
      peer->base_power,peer->base_handling,0,out);
}
static void app_story_body_draw(wpk_scene *scene,const mat4 *vp,const mat4 *model,
                                const float *eye,int pass,render_params *rp,
                                const story_body_view *view,int pack) {
  uint32_t old_flags=rp->story_assembly_flags;
  int old_enabled=rp->story_assembly_enabled;
  float old_y=rp->story_body_y;
  rp->story_assembly_enabled=1;
  rp->story_assembly_flags=view && view->valid ? view->assembly.flags : 0;
  rp->story_body_y=view && view->valid ? view->body_y : story_body_height(pack,0);
  wpk_draw(scene,vp,model,eye,pass,rp);
  rp->story_body_y=old_y;
  rp->story_assembly_flags=old_flags;
  rp->story_assembly_enabled=old_enabled;
}
