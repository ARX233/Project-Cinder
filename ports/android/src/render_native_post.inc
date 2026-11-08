/* Explicit post packets. Resource handles still use the shared allocation table;
 * no uniform shadow, texture unit, VAO, target or viewport is consulted. */
#ifdef WMMT_NATIVE_VK
static int native_bloom_ready;

/* Strict clear only requests attachments actually owned by this explicit FBO.
 * D16/D32 (without stencil) are valid fallback scene targets. */
static int native_post_clear(uint32_t target, const float color[4]) {
  cinder_vk_target_desc info;
  if (!cinder_vk_target_info(target,&info)) return 0;
  VkImageAspectFlags aspects=info.color_format!=VK_FORMAT_UNDEFINED?VK_IMAGE_ASPECT_COLOR_BIT:0;
  if (info.depth_format!=VK_FORMAT_UNDEFINED && info.depth_format!=VK_FORMAT_S8_UINT) aspects|=VK_IMAGE_ASPECT_DEPTH_BIT;
  if (info.depth_format==VK_FORMAT_D16_UNORM_S8_UINT || info.depth_format==VK_FORMAT_D24_UNORM_S8_UINT ||
      info.depth_format==VK_FORMAT_D32_SFLOAT_S8_UINT || info.depth_format==VK_FORMAT_S8_UINT) aspects|=VK_IMAGE_ASPECT_STENCIL_BIT;
  return cinder_vk_clear(target,aspects,color,NULL);
}

void render_scene_clear(float r, float g, float b, float a) {
  const float color[4]={r,g,b,a};
  memcpy(native_post_clear_color,color,sizeof color);
  if (!native_post_clear(native_scene.target,color)) frame_recording_trusted=frame_history_valid=0;
}

void render_scene_depth_clear(void) {
  cinder_vk_target_desc info;
  if (!cinder_vk_target_info(native_scene.target,&info)) {
    frame_recording_trusted=frame_history_valid=0;
    return;
  }
  /* A valid color-only or stencil-only target matches glClear(DEPTH)'s no-op.
   * The clear packet ignores depth masks and never changes the scene background. */
  if (info.depth_format!=VK_FORMAT_UNDEFINED && info.depth_format!=VK_FORMAT_S8_UINT) {
    const float unused_color[4]={0,0,0,0};
    if (!cinder_vk_clear(native_scene.target,VK_IMAGE_ASPECT_DEPTH_BIT,unused_color,NULL))
      frame_recording_trusted=frame_history_valid=0;
  }
}

void render_display_clear(float r, float g, float b, float a) {
  const float color[4]={r,g,b,a};
  cinder_vk_target_desc info;
  memcpy(native_post_clear_color,color,sizeof color);
  if (!cinder_vk_target_info(0,&info)) {
    frame_recording_trusted=frame_history_valid=0;
    return;
  }
  /* Menus clear color/depth, not stencil. Do not inherit a scene pass's target. */
  VkImageAspectFlags aspects=info.color_format!=VK_FORMAT_UNDEFINED?VK_IMAGE_ASPECT_COLOR_BIT:0;
  if (info.depth_format!=VK_FORMAT_UNDEFINED && info.depth_format!=VK_FORMAT_S8_UINT)
    aspects|=VK_IMAGE_ASPECT_DEPTH_BIT;
  if (aspects && !cinder_vk_clear(0,aspects,color,NULL)) frame_recording_trusted=frame_history_valid=0;
}

typedef struct {
  uint32_t program, target, texture;
  int w, h, additive;
  VkFilter filter;
  float texel[2], view[4], strength, threshold;
} native_post_pass;

static cinder_vk_sampler native_post_sampler(VkFilter filter) {
  return (cinder_vk_sampler){.use_state=VK_TRUE, .mipmaps=VK_FALSE,
    .min_filter=filter, .mag_filter=filter, .mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,
    .address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    .anisotropy=1.0f};
}

static int native_post_init(cinder_vk_draw *d, uint32_t program, uint32_t target, int w, int h) {
  if (!cinder_vk_draw_init(d, program, target, w, h)) return 0;
  d->pipeline.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
  d->pipeline.depth_test=d->pipeline.depth_write=d->pipeline.stencil=VK_FALSE;
  d->pipeline.depth_compare=VK_COMPARE_OP_LESS_OR_EQUAL;
  d->pipeline.cull=VK_CULL_MODE_NONE;
  d->pipeline.asset_front=VK_FRONT_FACE_COUNTER_CLOCKWISE;
  d->pipeline.color_mask=15;
  d->pipeline.blend=VK_FALSE;
  d->pipeline.src_blend=VK_BLEND_FACTOR_ONE; d->pipeline.dst_blend=VK_BLEND_FACTOR_ZERO;
  d->pipeline.blend_op=VK_BLEND_OP_ADD;
  return 1;
}

static int native_hq_pass(const native_post_pass *p) {
  static const float quad[]={-1,-1,1,-1,-1,1,1,1};
  cinder_vk_draw d;
  if (!p->texture || !native_post_init(&d,p->program,p->target,p->w,p->h)) return 0;
  d.pipeline.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP;
  /* Additive upsampling must LOAD the existing downsample, not clear it. The
   * executor loads preserved attachments; no clear/discard is issued here. */
  d.pipeline.blend=p->additive; d.pipeline.dst_blend=p->additive?VK_BLEND_FACTOR_ONE:VK_BLEND_FACTOR_ZERO;
  d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=2*sizeof(float),.data=quad,.bytes=sizeof quad};
  d.count=4;
  cinder_vk_sampler sampler=native_post_sampler(p->filter);
  return cinder_vk_uniform(&d,"uTexel",p->texel,sizeof p->texel) &&
    cinder_vk_uniform(&d,"uView",p->view,sizeof p->view) &&
    cinder_vk_uniform(&d,"uK",&p->strength,sizeof p->strength) &&
    cinder_vk_uniform(&d,"uThresh",&p->threshold,sizeof p->threshold) &&
    cinder_vk_texture(&d,"uTex",p->texture) && cinder_vk_sampler_state(&d,"uTex",&sampler) && cinder_vk_submit(&d);
}

/* Usage/format/extents are necessary, not sufficient: raw sample1 uses a blit
 * and needs its exact format capabilities. Ask the same full preflight as copy
 * before scene recording; multisample resolve need not have BLIT support. */
static int native_hq_copy_ready(void) {
  if (!hq.on || hq.msrt || hq.single_frame) return 1;
  cinder_vk_target_desc source, target;
  if (!(cinder_vk_target_info(hq.ms_fbo,&source) && cinder_vk_target_info(blur.fbo,&target) &&
      (source.color_usage & VK_IMAGE_USAGE_TRANSFER_SRC_BIT) &&
      (target.color_usage & VK_IMAGE_USAGE_TRANSFER_DST_BIT) &&
      source.color_format!=VK_FORMAT_UNDEFINED && source.color_format==target.color_format &&
      source.width==blur.w && source.height==blur.h && target.width==blur.w && target.height==blur.h)) return 0;
  const cinder_vk_copy_region copy={.source=hq.ms_fbo,.target=blur.fbo,
    .source_rect={0,0,blur.w,blur.h},.target_rect={0,0,blur.w,blur.h},
    .aspects=VK_IMAGE_ASPECT_COLOR_BIT,.filter=VK_FILTER_NEAREST};
  return cinder_vk_copy_ready(&copy);
}

static int native_hq_resolve_bloom(void) {
  int ok=!cinder_vk_error_pending();
  uint64_t epoch=cinder_vk_error_epoch();
  int direct=hq.msrt || hq.single_frame;
  int ao=hq.ssao_ok && hq.view_set && HQ_LEVEL[hq.level].ao && hq.opt_ao && hq.single_frame;
  native_bloom_ready=0; hq.ao_on=0;
  if (blur.w<=0 || blur.h<=0) return 0;
  if (ao && (hq.aw<=0 || hq.ah<=0)) { ao=0; hq.single_ready=0; ok=0; }
  if (!direct) {
    const cinder_vk_copy_region copy={.source=hq.ms_fbo,.target=blur.fbo,
      .source_rect={0,0,blur.w,blur.h},.target_rect={0,0,blur.w,blur.h},
      .aspects=VK_IMAGE_ASPECT_COLOR_BIT,.filter=VK_FILTER_NEAREST};
    if (!cinder_vk_copy(&copy)) return 0;
    if (!cinder_vk_discard(hq.ms_fbo,VK_IMAGE_ASPECT_COLOR_BIT|VK_IMAGE_ASPECT_DEPTH_BIT|VK_IMAGE_ASPECT_STENCIL_BIT)) ok=0;
  }
  /* Optional SSAO trusts exact target metadata and this explicit native epoch;
   * no legacy error drain or current framebuffer binding participates. */
  if (ao) {
    int complete=1;
    for (int i=0;i<2;++i) {
      cinder_vk_target_desc target;
      if (!hq.ao_fbo[i] || !cinder_vk_target_info(hq.ao_fbo[i],&target) ||
          target.width!=hq.aw || target.height!=hq.ah || target.color_format==VK_FORMAT_UNDEFINED ||
          target.samples!=VK_SAMPLE_COUNT_1_BIT) complete=0;
    }
    if (!complete || cinder_vk_error_pending() || cinder_vk_error_epoch()!=epoch) { ao=0; hq.single_ready=0; ok=0; }
  }
  if (ao) {
    native_post_pass p={.program=hq.ao_prog,.target=hq.ao_fbo[0],.texture=hq.z_tex,
      .w=hq.aw,.h=hq.ah,.filter=VK_FILTER_NEAREST,.strength=hq.ssao,
      .texel={1.0f/(float)blur.w,1.0f/(float)blur.h}};
    memcpy(p.view,hq.view,sizeof p.view);
    int made=native_hq_pass(&p);
    p=(native_post_pass){.program=hq.ao_blur_prog,.target=hq.ao_fbo[1],.texture=hq.ao_tex[0],
      .w=hq.aw,.h=hq.ah,.filter=VK_FILTER_NEAREST,.texel={1.0f/(float)hq.aw,1.0f/(float)hq.ah}};
    made=made && native_hq_pass(&p);
    if (!made || cinder_vk_error_pending() || cinder_vk_error_epoch()!=epoch) { ao=0; hq.single_ready=0; ok=0; }
  }
  hq.ao_on=ao;
  if (hq.bloom<=0.0f) return ok;
  for (int i=0;i<HQ_LEVELS;++i) {
    int sw=i?hq.w[i-1]:blur.w, sh=i?hq.h[i-1]:blur.h;
    native_post_pass p={.program=hq.down_prog[i==0],.target=hq.fbo[i],.texture=i?hq.tex[i-1]:blur.tex,
      .w=hq.w[i],.h=hq.h[i],.filter=VK_FILTER_LINEAR,.threshold=i?0.0f:0.75f,
      .texel={1.0f/(float)sw,1.0f/(float)sh}};
    if (!native_hq_pass(&p)) return 0;
  }
  for (int i=HQ_LEVELS-1;i>0;--i) {
    native_post_pass p={.program=hq.up_prog,.target=hq.fbo[i-1],.texture=hq.tex[i],
      .w=hq.w[i-1],.h=hq.h[i-1],.filter=VK_FILTER_LINEAR,.additive=1,
      .texel={1.0f/(float)hq.w[i],1.0f/(float)hq.h[i]}};
    if (!native_hq_pass(&p)) return 0;
  }
  native_bloom_ready=1;
  return ok;
}

static int native_final_composite(const float *vertices, size_t bytes, const uint16_t *indices, int band) {
  int q=hq.on?3:0, variant=!band && blur.sharp>0.0f?2:band;
  cinder_vk_draw d;
  if (!native_post_init(&d,blur_progs[q+variant],(uint32_t)blur.screen,blur.out_w,blur.out_h)) return 0;
  d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=5*sizeof(float),.data=vertices,.bytes=bytes};
  d.attributes[1]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=5*sizeof(float),.offset=2*sizeof(float),.data=vertices,.bytes=bytes};
  d.attributes[2]=(cinder_vk_attribute){.format=VK_FORMAT_R32_SFLOAT,.stride=5*sizeof(float),.offset=4*sizeof(float),.data=vertices,.bytes=bytes};
  d.indexed=VK_TRUE; d.index_type=VK_INDEX_TYPE_UINT16; d.indices=indices; d.count=band?12:6; d.index_bytes=d.count*sizeof *indices;
  float texel[2]={1.0f/(float)blur.w,1.0f/(float)blur.h};
  float bloom=hq.on && native_bloom_ready?hq.bloom:0.0f;
  cinder_vk_sampler sampler=native_post_sampler(VK_FILTER_LINEAR);
  int ok=cinder_vk_uniform(&d,"uTexel",texel,sizeof texel) &&
    cinder_vk_uniform(&d,"uSharp",&blur.sharp,sizeof blur.sharp) &&
    cinder_vk_uniform(&d,"uBloomK",&bloom,sizeof bloom) &&
    cinder_vk_texture(&d,"uTex",blur.tex) && cinder_vk_sampler_state(&d,"uTex",&sampler);
  if (hq.on) ok=ok && cinder_vk_texture(&d,"uBloom",native_bloom_ready?hq.tex[0]:blur.tex) &&
    cinder_vk_texture(&d,"uAO",hq.ao_on?hq.ao_tex[1]:white_tex) &&
    cinder_vk_sampler_state(&d,"uBloom",&sampler) && cinder_vk_sampler_state(&d,"uAO",&sampler);
  return ok && cinder_vk_submit(&d);
}
#endif
