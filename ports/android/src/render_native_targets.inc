/* Renderer-owned immutable target graph. Each candidate is private until every
 * mandatory constructor/readiness check succeeds. Targets die before resources;
 * failed candidates never mutate a previously committed composition. */
#ifdef WMMT_NATIVE_VK
typedef struct {
  GLuint tex, fbo, depth, rt_tex, rt_fbo, rt_depth, ms_fbo, ms_color, ms_depth;
  GLuint level_tex[HQ_LEVELS], level_fbo[HQ_LEVELS], z_tex, single_fbo[2], ao_tex[2], ao_fbo[2];
  int w[HQ_LEVELS], h[HQ_LEVELS], aw, ah, single_ready, single_attempted, ssao_ok, msrt;
} native_render_graph;
static int native_graph_samples, native_graph_fmt, native_graph_dirty;

static cinder_vk_sampler native_target_sampler(VkFilter filter) {
  return (cinder_vk_sampler){.use_state=VK_TRUE,.min_filter=filter,.mag_filter=filter,
    .mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,.address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    .address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,.anisotropy=1.0f};
}
static cinder_vk_storage_format native_hq_format(int fmt) {
  return fmt==0?CINDER_VK_STORAGE_R11G11B10F:fmt==1?CINDER_VK_STORAGE_RGBA16F:CINDER_VK_STORAGE_RGBA8;
}
static GLuint native_target_texture(int w,int h,cinder_vk_storage_format format,VkFilter filter,int transfers) {
  const cinder_vk_storage_desc d={.width=w,.height=h,.samples=1,.format=format,
    .transfer_src=(VkBool32)(transfers&1),.transfer_dst=(VkBool32)((transfers>>1)&1),
    .sampler=native_target_sampler(filter)};
  return cinder_vk_texture_storage(&d);
}
static GLuint native_target_attachment(int w,int h,cinder_vk_storage_format format,int samples,int transfer,int transient) {
  const cinder_vk_storage_desc d={.width=w,.height=h,.samples=samples,.format=format,
    .transfer_src=(VkBool32)transfer,.transient=(VkBool32)transient};
  return cinder_vk_attachment_create(&d);
}
static GLuint native_target_compose(GLuint color,cinder_vk_image_kind ck,GLuint depth,cinder_vk_image_kind dk,
                                    int samples,int w,int h) {
  const cinder_vk_target_create_desc d={{color?ck:CINDER_VK_IMAGE_NONE,color},
    {depth?dk:CINDER_VK_IMAGE_NONE,depth},samples};
  GLuint f=cinder_vk_target_create(&d);
  cinder_vk_target_desc info;
  if (f && (!cinder_vk_target_ready(f) || !cinder_vk_target_info(f,&info) || info.width!=w || info.height!=h ||
      (color && info.color_format==VK_FORMAT_UNDEFINED) || (depth && info.depth_format==VK_FORMAT_UNDEFINED))) {
    cinder_vk_target_destroy(f); f=0;
  }
  return f;
}
static native_render_graph native_graph_capture(void) {
  native_render_graph g={.tex=blur.tex,.fbo=blur.fbo,.depth=blur.depth,.rt_tex=hq.rt_tex,.rt_fbo=hq.rt_fbo,
    .rt_depth=hq.rt_depth,.ms_fbo=hq.ms_fbo,.ms_color=hq.ms_color,.ms_depth=hq.ms_depth,.z_tex=hq.z_tex,
    .aw=hq.aw,.ah=hq.ah,.single_ready=hq.single_ready,.single_attempted=hq.single_attempted,
    .ssao_ok=hq.ssao_ok,.msrt=hq.msrt};
  memcpy(g.level_tex,hq.tex,sizeof g.level_tex); memcpy(g.level_fbo,hq.fbo,sizeof g.level_fbo);
  memcpy(g.w,hq.w,sizeof g.w); memcpy(g.h,hq.h,sizeof g.h);
  memcpy(g.single_fbo,hq.single_fbo,sizeof g.single_fbo);
  memcpy(g.ao_tex,hq.ao_tex,sizeof g.ao_tex); memcpy(g.ao_fbo,hq.ao_fbo,sizeof g.ao_fbo);
  return g;
}
static void native_graph_publish(const native_render_graph *g) {
  blur.tex=g->tex; blur.fbo=g->fbo; blur.depth=g->depth;
  hq.rt_tex=g->rt_tex; hq.rt_fbo=g->rt_fbo; hq.rt_depth=g->rt_depth;
  hq.ms_fbo=g->ms_fbo; hq.ms_color=g->ms_color; hq.ms_depth=g->ms_depth; hq.z_tex=g->z_tex; hq.z_fbo=0;
  memcpy(hq.tex,g->level_tex,sizeof hq.tex); memcpy(hq.fbo,g->level_fbo,sizeof hq.fbo);
  memcpy(hq.w,g->w,sizeof hq.w); memcpy(hq.h,g->h,sizeof hq.h);
  memcpy(hq.single_fbo,g->single_fbo,sizeof hq.single_fbo);
  memcpy(hq.ao_tex,g->ao_tex,sizeof hq.ao_tex); memcpy(hq.ao_fbo,g->ao_fbo,sizeof hq.ao_fbo);
  hq.msrt=g->msrt;
  hq.aw=g->aw; hq.ah=g->ah; hq.single_ready=g->single_ready;
  hq.single_attempted=g->single_attempted; hq.ssao_ok=g->ssao_ok; hq.single_frame=hq.ao_on=0;
}
static void native_graph_release(native_render_graph *g) {
  cinder_vk_target_destroy(g->fbo); cinder_vk_target_destroy(g->rt_fbo); cinder_vk_target_destroy(g->ms_fbo);
  for(int i=0;i<HQ_LEVELS;++i) cinder_vk_target_destroy(g->level_fbo[i]);
  for(int i=0;i<2;++i) { cinder_vk_target_destroy(g->single_fbo[i]); cinder_vk_target_destroy(g->ao_fbo[i]); }
  cinder_vk_texture_destroy(g->tex); cinder_vk_texture_destroy(g->rt_tex); cinder_vk_texture_destroy(g->z_tex);
  for(int i=0;i<HQ_LEVELS;++i) cinder_vk_texture_destroy(g->level_tex[i]);
  for(int i=0;i<2;++i) cinder_vk_texture_destroy(g->ao_tex[i]);
  cinder_vk_attachment_destroy(g->depth); cinder_vk_attachment_destroy(g->rt_depth);
  cinder_vk_attachment_destroy(g->ms_color); cinder_vk_attachment_destroy(g->ms_depth);
  memset(g,0,sizeof *g);
}
static int native_graph_has_target(const native_render_graph *g,uint32_t f) {
  if(!f) return 0;
  if(f==g->fbo || f==g->rt_fbo || f==g->ms_fbo) return 1;
  for(int i=0;i<HQ_LEVELS;++i) if(f==g->level_fbo[i]) return 1;
  for(int i=0;i<2;++i) if(f==g->single_fbo[i] || f==g->ao_fbo[i]) return 1;
  return 0;
}
static void native_graph_leave(const native_render_graph *g) {
  if(native_graph_has_target(g,native_scene.target))
    native_scene=(native_scene_view){native_graph_has_target(g,(uint32_t)blur.screen)?0:(uint32_t)blur.screen,
      blur.out_w,blur.out_h};
}
static void hq_free(void) {
  native_render_graph old=native_graph_capture(), empty={0};
  frame_history_valid=0; frame_sampler_off(); native_graph_leave(&old);
  native_graph_publish(&empty); blur.w=blur.h=0;
  native_graph_samples=native_graph_dirty=0; native_graph_release(&old);
}
/* Eager colour resolve only; depth has matching samples, never an invented
 * depth resolve. Failure leaves even the candidate's ordinary base untouched. */
static int native_msrt_targets(native_render_graph *g,int w,int h,int samples,int fmt) {
  GLuint tex=native_target_texture(w,h,native_hq_format(fmt),VK_FILTER_LINEAR,3);
  GLuint depth=tex?native_target_attachment(w,h,CINDER_VK_STORAGE_DEPTH24_STENCIL8,samples,0,1):0;
  GLuint f0=depth?native_target_compose(g->tex,CINDER_VK_IMAGE_TEXTURE,depth,CINDER_VK_IMAGE_ATTACHMENT,samples,w,h):0;
  GLuint f1=f0?native_target_compose(tex,CINDER_VK_IMAGE_TEXTURE,depth,CINDER_VK_IMAGE_ATTACHMENT,samples,w,h):0;
  if(!f1) {
    cinder_vk_target_destroy(f0); cinder_vk_target_destroy(f1);
    cinder_vk_texture_destroy(tex); cinder_vk_attachment_destroy(depth); return 0;
  }
  g->rt_tex=tex; g->rt_depth=depth; g->fbo=f0; g->rt_fbo=f1; g->msrt=1; return 1;
}
/* Optional single-sample depth scene + AO pair is a separate local transaction.
 * The MSAA/MSRT graph remains usable on failure, with no partial SSAO publish. */
static int native_ssao_targets(native_render_graph *g,int w,int h,int fmt) {
  native_render_graph a={0}; int extra=!g->rt_tex;
  a.aw=w/2>1?w/2:1; a.ah=h/2>1?h/2:1;
  a.z_tex=native_target_texture(w,h,CINDER_VK_STORAGE_DEPTH24_STENCIL8,VK_FILTER_NEAREST,0);
  if(!a.z_tex) goto bad;
  if(extra) {
    a.rt_tex=native_target_texture(w,h,native_hq_format(fmt),VK_FILTER_LINEAR,3);
    a.rt_fbo=a.rt_tex?native_target_compose(a.rt_tex,CINDER_VK_IMAGE_TEXTURE,g->depth,CINDER_VK_IMAGE_ATTACHMENT,0,w,h):0;
    if(!a.rt_fbo) goto bad;
  }
  for(int i=0;i<2;++i) {
    a.single_fbo[i]=native_target_compose(i?(extra?a.rt_tex:g->rt_tex):g->tex,CINDER_VK_IMAGE_TEXTURE,
      a.z_tex,CINDER_VK_IMAGE_TEXTURE,0,w,h);
    if(!a.single_fbo[i]) goto bad;
    a.ao_tex[i]=native_target_texture(a.aw,a.ah,CINDER_VK_STORAGE_RGBA8,i?VK_FILTER_LINEAR:VK_FILTER_NEAREST,0);
    a.ao_fbo[i]=a.ao_tex[i]?native_target_compose(a.ao_tex[i],CINDER_VK_IMAGE_TEXTURE,0,CINDER_VK_IMAGE_NONE,0,a.aw,a.ah):0;
    if(!a.ao_fbo[i]) goto bad;
  }
  if(extra) { g->rt_tex=a.rt_tex; g->rt_fbo=a.rt_fbo; }
  g->z_tex=a.z_tex; g->aw=a.aw; g->ah=a.ah;
  memcpy(g->single_fbo,a.single_fbo,sizeof a.single_fbo);
  memcpy(g->ao_tex,a.ao_tex,sizeof a.ao_tex); memcpy(g->ao_fbo,a.ao_fbo,sizeof a.ao_fbo);
  g->single_ready=g->ssao_ok=1; return 1;
bad:
  native_graph_release(&a); return 0;
}
static void vk_single_targets(int w,int h) {
  native_render_graph g=native_graph_capture();
  hq.single_attempted=1;
  if(g.z_tex || g.single_ready) return;
  g.single_attempted=1;
  if(native_ssao_targets(&g,w,h,hq.fmt)) native_graph_publish(&g);
}
static int native_blur_allocate(int w,int h,int deep,int on,int fmt,int samples,int msrt) {
  native_render_graph g={0};
  cinder_vk_storage_format format=deep==2?native_hq_format(fmt):deep?CINDER_VK_STORAGE_RGBA8:CINDER_VK_STORAGE_RGB565;
  g.tex=native_target_texture(w,h,format,VK_FILTER_LINEAR,3);
  g.depth=g.tex?native_target_attachment(w,h,CINDER_VK_STORAGE_DEPTH24_STENCIL8,1,0,0):0;
  if(!g.depth) goto bad;
  if(on && msrt) (void)native_msrt_targets(&g,w,h,samples,fmt);
  if(!g.msrt) {
    g.fbo=native_target_compose(g.tex,CINDER_VK_IMAGE_TEXTURE,g.depth,CINDER_VK_IMAGE_ATTACHMENT,0,w,h);
    if(!g.fbo) goto bad;
    if(on) {
      /* A raw resolve reads colour from memory: TRANSFER_SRC and nontransient. */
      g.ms_color=native_target_attachment(w,h,format,samples,1,0);
      g.ms_depth=g.ms_color?native_target_attachment(w,h,CINDER_VK_STORAGE_DEPTH24_STENCIL8,samples,0,1):0;
      g.ms_fbo=g.ms_depth?native_target_compose(g.ms_color,CINDER_VK_IMAGE_ATTACHMENT,g.ms_depth,CINDER_VK_IMAGE_ATTACHMENT,0,w,h):0;
      cinder_vk_target_desc src,dst;
      if(!g.ms_fbo || !cinder_vk_target_info(g.ms_fbo,&src) || !cinder_vk_target_info(g.fbo,&dst) ||
          !(src.color_usage&VK_IMAGE_USAGE_TRANSFER_SRC_BIT) || !(dst.color_usage&VK_IMAGE_USAGE_TRANSFER_DST_BIT) ||
          src.color_format!=dst.color_format) goto bad;
    }
  }
  if(on) for(int i=0,lw=w,lh=h;i<HQ_LEVELS;++i) {
    lw=lw/2>1?lw/2:1; lh=lh/2>1?lh/2:1; g.w[i]=lw; g.h[i]=lh;
    g.level_tex[i]=native_target_texture(lw,lh,format,VK_FILTER_LINEAR,0);
    g.level_fbo[i]=g.level_tex[i]?native_target_compose(g.level_tex[i],CINDER_VK_IMAGE_TEXTURE,0,CINDER_VK_IMAGE_NONE,0,lw,lh):0;
    if(!g.level_fbo[i]) goto bad;
  }
  /* Publish dimensions, format, capabilities and readiness together, only now. */
  native_render_graph old=native_graph_capture();
  frame_history_valid=0; frame_sampler_off(); native_graph_leave(&old);
  native_graph_publish(&g); blur.w=w; blur.h=h; blur.deep=deep;
  hq.on=on; hq.fmt=fmt; hq.msrt=g.msrt;
  native_graph_samples=samples; native_graph_fmt=fmt; native_graph_dirty=0;
  native_graph_release(&old); return 1;
bad:
  native_graph_release(&g); return 0;
}
static int native_simple_target(int w,int h,cinder_vk_storage_format cf,cinder_vk_storage_format df,
                                GLuint *tex,GLuint *depth,GLuint *fbo) {
  GLuint t=native_target_texture(w,h,cf,VK_FILTER_LINEAR,0);
  GLuint d=t?native_target_attachment(w,h,df,1,0,0):0;
  GLuint f=d?native_target_compose(t,CINDER_VK_IMAGE_TEXTURE,d,CINDER_VK_IMAGE_ATTACHMENT,0,w,h):0;
  if(!f) { cinder_vk_target_destroy(f); cinder_vk_texture_destroy(t); cinder_vk_attachment_destroy(d); return 0; }
  *tex=t; *depth=d; *fbo=f; return 1;
}
#endif
