/* Scene-space effects: fully specified packets, not snapshots of GL drawing
 * state. Resource upload handles remain shared until the resource migration. */
#ifdef WMMT_NATIVE_VK
static int native_effect_init(cinder_vk_draw *d, const mat4 *vp, uint32_t tex, float fog_far, float fog_near) {
  native_scene_view target = native_scene;
  if (target.w <= 0 || target.h <= 0) {
    target.target = 0; cinder_vk_screen_extent(&target.w, &target.h);
  }
  if (!cinder_vk_draw_init(d, progs[0].id, target.target, target.w, target.h)) return 0;
  const float eye[3]={0,0,0}, fog[2]={fog_far,fog_near}, zero[2]={0,0}, grade[3]={1,1,1}, wet=0;
  return cinder_vk_uniform(d,"uMVP",vp->m,sizeof vp->m) &&
    cinder_vk_uniform(d,"uEye",eye,sizeof eye) && cinder_vk_uniform(d,"uFogColor",eye,sizeof eye) &&
    cinder_vk_uniform(d,"uFog",fog,sizeof fog) && cinder_vk_uniform(d,"uUVOff",zero,sizeof zero) &&
    cinder_vk_uniform(d,"uGrade",grade,sizeof grade) && cinder_vk_uniform(d,"uWet",&wet,sizeof wet) &&
    cinder_vk_uniform(d,"uHorizon",eye,sizeof eye) && cinder_vk_texture(d,"uTex",tex) &&
    cinder_vk_texture(d,"uFrame",white_tex);
}
static void native_effect_vertices(cinder_vk_draw *d, const void *vertices, size_t bytes, uint32_t stride, VkFormat color) {
  d->attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32B32_SFLOAT,.stride=stride,.data=vertices,.bytes=bytes};
  d->attributes[1]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=stride,.offset=12,.data=vertices,.bytes=bytes};
  d->attributes[2]=(cinder_vk_attribute){.format=color,.stride=stride,.offset=20,.data=vertices,.bytes=bytes};
}
static int native_effect_quads(const mat4 *vp, const render_vertex *v, int n, uint32_t tex,
    const uint16_t *indices, int by_color, int tire, const render_params *p) {
  cinder_vk_draw d;
  if (!native_effect_init(&d,vp,tex,1e9f,1e8f)) return 0;
  d.pipeline.depth_test = tire || !p->no_depth_test;
  d.pipeline.blend=VK_TRUE; d.pipeline.src_blend=by_color?VK_BLEND_FACTOR_SRC_COLOR:VK_BLEND_FACTOR_SRC_ALPHA;
  d.pipeline.dst_blend=tire?VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA:VK_BLEND_FACTOR_ONE;
  d.pipeline.color_mask=tire?7:15;
  native_effect_vertices(&d,v,(size_t)n*4*sizeof *v,sizeof *v,VK_FORMAT_R8G8B8A8_UNORM);
  d.count=(uint32_t)n*6; d.indexed=VK_TRUE; d.indices=indices; d.index_bytes=(size_t)n*6*sizeof *indices;
  if (tire) {
    /* The WPK may carry mipmaps/anisotropy. Preserve those upload defaults,
     * override addressing only, and never mutate a texture shared with UI. */
    cinder_vk_sampler sampler;
    if (!cinder_vk_texture_sampler(tex,&sampler)) return 0;
    sampler.address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    sampler.address_v=VK_SAMPLER_ADDRESS_MODE_REPEAT;
    if (!cinder_vk_sampler_state(&d,"uTex",&sampler)) return 0;
  }
  return cinder_vk_submit(&d);
}
#endif
