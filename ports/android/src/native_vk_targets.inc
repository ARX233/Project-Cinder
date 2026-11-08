/* Explicit level-zero storage and strong-snapshot attachment composition.
 * No upload, compatibility binding, enum translation or draw-time allocation.
 * A returned storage handle has undefined contents until a pass writes it. */
static int native_storage_samples(int samples) {
  return samples == 1 || samples == 2 || samples == 4 || samples == 8;
}

static int native_storage_format(cinder_vk_storage_format format, VkFormat *out) {
  VkFormat f;
  switch (format) {
  case CINDER_VK_STORAGE_RGBA8: f = VK_FORMAT_R8G8B8A8_UNORM; break;
  case CINDER_VK_STORAGE_RGB565: f = VK_FORMAT_R5G6B5_UNORM_PACK16; break;
  case CINDER_VK_STORAGE_RGBA16F: f = VK_FORMAT_R16G16B16A16_SFLOAT; break;
  case CINDER_VK_STORAGE_R11G11B10F: f = D.f11; break;
  case CINDER_VK_STORAGE_DEPTH16: f = VK_FORMAT_D16_UNORM; break;
  case CINDER_VK_STORAGE_DEPTH24_STENCIL8: f = D.fd24; break;
  default: return 0;
  }
  if (!f || (format == CINDER_VK_STORAGE_DEPTH24_STENCIL8 && (!is_depth(f) || !has_stencil(f))) ||
      (format <= CINDER_VK_STORAGE_R11G11B10F && is_depth(f))) return 0;
  *out = f;
  return 1;
}

/* This is the common framebuffer limit, not a rounding policy. Every storage
 * request still probes its exact format, usage, extent and sample count. */
int cinder_vk_sample_limit(void) {
  if (!D.dev || !D.pd) return 0;
  VkSampleCountFlags counts = D.props.limits.framebufferColorSampleCounts &
    D.props.limits.framebufferDepthSampleCounts & D.props.limits.framebufferStencilSampleCounts;
  return counts & VK_SAMPLE_COUNT_8_BIT ? 8 : counts & VK_SAMPLE_COUNT_4_BIT ? 4 :
    counts & VK_SAMPLE_COUNT_2_BIT ? 2 : counts & VK_SAMPLE_COUNT_1_BIT ? 1 : 0;
}

static int native_storage_capabilities(VkFormat format, int w, int h, int samples,
                                        VkImageUsageFlags usage, int linear) {
  if (!D.dev || !D.pd || !format || w <= 0 || h <= 0 || !native_storage_samples(samples) ||
      (uint32_t)w > D.props.limits.maxImageDimension2D || (uint32_t)h > D.props.limits.maxImageDimension2D ||
      (uint32_t)w > D.props.limits.maxFramebufferWidth || (uint32_t)h > D.props.limits.maxFramebufferHeight ||
      D.props.limits.maxFramebufferLayers < 1) return 0;
  VkFormatFeatureFlags required = is_depth(format) ? VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT :
    VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT;
  VkSampleCountFlags counts = is_depth(format) ? D.props.limits.framebufferDepthSampleCounts :
    D.props.limits.framebufferColorSampleCounts;
  if (has_stencil(format)) counts &= D.props.limits.framebufferStencilSampleCounts;
  if (!(counts & (VkSampleCountFlags)samples)) return 0;
  if (usage & VK_IMAGE_USAGE_SAMPLED_BIT) required |= VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT;
  if (usage & VK_IMAGE_USAGE_TRANSFER_SRC_BIT) required |= VK_FORMAT_FEATURE_TRANSFER_SRC_BIT;
  if (usage & VK_IMAGE_USAGE_TRANSFER_DST_BIT) required |= VK_FORMAT_FEATURE_TRANSFER_DST_BIT;
  if (linear) required |= VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
  if (!fmt_has(format, required)) return 0;
  VkImageFormatProperties p = { 0 };
  VkResult result = vkGetPhysicalDeviceImageFormatProperties(D.pd, format, VK_IMAGE_TYPE_2D,
    VK_IMAGE_TILING_OPTIMAL, usage, 0, &p);
  /* A lower bound on storage rejects impossible resource limits, not a claim
   * about implementation-specific tiling/compression/allocation requirements. */
  unsigned bpp = format == VK_FORMAT_R16G16B16A16_SFLOAT || format == VK_FORMAT_D32_SFLOAT_S8_UINT ? 8 :
    format == VK_FORMAT_D16_UNORM || format == VK_FORMAT_R5G6B5_UNORM_PACK16 ? 2 : 4;
  uint64_t bytes = (uint64_t)(unsigned)w * (unsigned)h;
  if (bytes > UINT64_MAX / bpp / (unsigned)samples) return 0;
  bytes *= bpp * (unsigned)samples;
  return result == VK_SUCCESS && (uint32_t)w <= p.maxExtent.width && (uint32_t)h <= p.maxExtent.height &&
    p.maxExtent.depth >= 1 && p.maxMipLevels >= 1 && p.maxArrayLayers >= 1 &&
    (p.sampleCounts & (VkSampleCountFlags)samples) && bytes <= p.maxResourceSize;
}

static vimg *native_storage_new(const cinder_vk_storage_desc *desc, int sampled) {
  VkFormat format;
  if (!desc || desc->transfer_src > VK_TRUE || desc->transfer_dst > VK_TRUE || desc->transient > VK_TRUE ||
      !native_storage_samples(desc->samples) || !native_storage_format(desc->format, &format) ||
      (sampled && (desc->samples != 1 || desc->transient || desc->sampler.use_state != VK_TRUE ||
                   desc->sampler.mipmaps || !native_sampler_valid(&desc->sampler))) ||
      (desc->transient && (desc->transfer_src || desc->transfer_dst || sampled))) return NULL;
  VkImageUsageFlags usage = is_depth(format) ? VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT : VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
  if (sampled) usage |= VK_IMAGE_USAGE_SAMPLED_BIT;
  if (desc->transfer_src) usage |= VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
  if (desc->transfer_dst) usage |= VK_IMAGE_USAGE_TRANSFER_DST_BIT;
  if (desc->transient) usage |= VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT;
  int linear = sampled && (desc->sampler.min_filter == VK_FILTER_LINEAR || desc->sampler.mag_filter == VK_FILTER_LINEAR);
  if (!native_storage_capabilities(format, desc->width, desc->height, desc->samples, usage, linear)) return NULL;
  vimg *im = image_new_usage(format, desc->width, desc->height, 1, 1, desc->samples, sampled,
                             (int)desc->transient, SWZ_ID, usage);
  if (!im) return NULL;
  if (!im->img || !im->uid || !im->att || (sampled && !im->view) || im->usage != usage) {
    image_free_now(im); return NULL;
  }
  return im;
}

uint32_t cinder_vk_texture_storage(const cinder_vk_storage_desc *desc) {
  vimg *im = native_storage_new(desc, 1);
  if (!im) { native_reject(); return 0; }
  uint32_t id = tex_gen();
  vtex *texture = tex_get(id);
  if (!id || !texture) {
    if (id) tex_release(id);
    image_free_now(im); native_reject(); return 0;
  }
  texture->im = im;
  texture->native_sampler = desc->sampler;
  return id;
}

uint32_t cinder_vk_attachment_create(const cinder_vk_storage_desc *desc) {
  vimg *im = native_storage_new(desc, 0);
  if (!im) { native_reject(); return 0; }
  uint32_t id = rbo_gen();
  vrbo *attachment = rbo_get(id);
  if (!id || !attachment) {
    if (id) rbo_release(id);
    image_free_now(im); native_reject(); return 0;
  }
  attachment->im = im;
  return id;
}

void cinder_vk_attachment_destroy(uint32_t id) {
  if (!id) return;
  vrbo *attachment = rbo_get(id);
  if (!attachment) { native_reject(); return; }
  image_drop(attachment->im);
  attachment->im = NULL;
  rbo_release(id);
}

static int native_target_ref(cinder_vk_image_ref ref, vimg **out) {
  *out = NULL;
  if (ref.kind == CINDER_VK_IMAGE_NONE) return ref.id == 0;
  if (!ref.id) return 0;
  if (ref.kind == CINDER_VK_IMAGE_TEXTURE) {
    vtex *t = tex_get(ref.id);
    if (t) *out = t->im;
  } else if (ref.kind == CINDER_VK_IMAGE_ATTACHMENT) {
    vrbo *r = rbo_get(ref.id);
    if (r) *out = r->im;
  } else return 0;
  return *out != NULL;
}

static int native_target_storage_valid(const vimg *im, int depth) {
  if (!im) return 1;
  VkImageAspectFlags aspect = depth ? VK_IMAGE_ASPECT_DEPTH_BIT |
    (has_stencil(im->fmt) ? VK_IMAGE_ASPECT_STENCIL_BIT : 0) : VK_IMAGE_ASPECT_COLOR_BIT;
  VkImageUsageFlags attachment = depth ? VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT : VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
  return im->img && im->uid && im->att && im->fmt && is_depth(im->fmt) == depth && im->aspect == aspect &&
    im->w > 0 && im->h > 0 && im->levels == 1 && im->layers == 1 && native_storage_samples(im->samples) &&
    (im->usage & attachment) && (!im->sampled || (im->view && im->view_levels == 1 && (im->usage & VK_IMAGE_USAGE_SAMPLED_BIT))) &&
    !im->native_upload_pending && !im->native_retire_pending;
}

uint32_t cinder_vk_target_create(const cinder_vk_target_create_desc *desc) {
  vimg *color, *depth;
  if (!desc || !native_target_ref(desc->color, &color) || !native_target_ref(desc->depth_stencil, &depth) ||
      (!color && !depth) || !native_target_storage_valid(color, 0) || !native_target_storage_valid(depth, 1) ||
      (color && color->sampled != (desc->color.kind == CINDER_VK_IMAGE_TEXTURE)) ||
      (depth && depth->sampled != (desc->depth_stencil.kind == CINDER_VK_IMAGE_TEXTURE)) ||
      (color && color->sampled && color->samples != 1) || (depth && depth->sampled && depth->samples != 1) ||
      (color && depth && (color == depth || color->w != depth->w || color->h != depth->h)) ||
      (desc->resolve_samples != 0 && !native_storage_samples(desc->resolve_samples))) {
    native_reject(); return 0;
  }
  int resolve = desc->resolve_samples > 1;
  int samples = resolve ? desc->resolve_samples : color ? color->samples : depth->samples;
  if ((resolve && (!color || desc->color.kind != CINDER_VK_IMAGE_TEXTURE || !color->sampled || color->samples != 1)) ||
      (depth && depth->samples != samples)) { native_reject(); return 0; }
  if (color && !native_target_image_hold(color)) { native_reject(); return 0; }
  if (depth && !native_target_image_hold(depth)) {
    if (color) native_target_image_release(color);
    native_reject(); return 0;
  }
  vfbo snapshot = { .used = 1, .native = 1, .native_color = color, .native_depth = depth };
  snapshot.color = (vatt){ (int)desc->color.kind, desc->color.id, resolve ? samples : 0 };
  snapshot.depth = (vatt){ (int)desc->depth_stencil.kind, desc->depth_stencil.id, 0 };
  if (depth && has_stencil(depth->fmt)) snapshot.stencil = snapshot.depth;
  if (resolve) {
    VkImageUsageFlags usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT;
    if (!native_storage_capabilities(color->fmt, color->w, color->h, samples, usage, 0)) goto fail;
    snapshot.ms = image_new_usage(color->fmt, color->w, color->h, 1, 1, samples, 0, 1, SWZ_ID, usage);
    if (!snapshot.ms) goto fail;
    if (!native_target_storage_valid(snapshot.ms, 0) || snapshot.ms->usage != usage || !snapshot.ms->transient) goto fail;
    snapshot.ms->implicit = 1;
  }
  uint32_t id = fbo_gen();
  vfbo *target = fbo_get(id);
  if (!id || !target) {
    if (id) fbo_release(id);
    goto fail;
  }
  *target = snapshot;
  vop pass;
  if (!fb_target(id, &pass)) {
    memset(target, 0, sizeof *target);
    /* release expects a live table slot */
    target->used = 1; fbo_release(id);
    goto fail;
  }
  return id;
fail:
  /* Nothing here was submitted. Owned unpublished MS storage can free now;
   * borrowed snapshots are released, never public texture/attachment handles. */
  if (snapshot.ms) image_free_now(snapshot.ms);
  if (depth) native_target_image_release(depth);
  if (color) native_target_image_release(color);
  native_reject(); return 0;
}

void cinder_vk_target_destroy(uint32_t id) {
  if (!id) return;
  vfbo *target = fbo_get(id);
  if (!target || !target->native) { native_reject(); return; }
  vimg *color = target->native_color, *depth = target->native_depth, *ms = target->ms;
  target->native_color = target->native_depth = target->ms = NULL;
  fbo_release(id);
  image_drop(ms);
  if (depth) native_target_image_release(depth);
  if (color) native_target_image_release(color);
}

int cinder_vk_target_ready(uint32_t id) {
  vfbo *target = fbo_get(id);
  vop pass;
  return target && target->native && fb_target(id, &pass);
}
