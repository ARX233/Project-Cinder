/* Complete immutable sampled images. All source rows and device capabilities
 * are checked before allocation; all views/staging/table/begin/lease work is
 * completed before the first image command. Loader completion remains the
 * platform handoff boundary, not a promise made by a returned public handle. */
#define NATIVE_TEXTURE_USAGE (VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT)
enum { NATIVE_TEXTURE_COPY, NATIVE_TEXTURE_RGB_RGBA, NATIVE_TEXTURE_5551_1555 };
typedef struct {
  VkFormat format;
  VkComponentMapping swizzle;
  unsigned src_bpp, dst_bpp, block, conversion;
} native_texture_format_info;

static int native_texture_format(cinder_vk_texture_format format, native_texture_format_info *out) {
  native_texture_format_info f = { .swizzle = SWZ_ID, .block = 1 };
  switch (format) {
  case CINDER_VK_TEX_RGBA8: f.format = VK_FORMAT_R8G8B8A8_UNORM; f.src_bpp = f.dst_bpp = 4; break;
  case CINDER_VK_TEX_RGB8:
    f.format = VK_FORMAT_R8G8B8A8_UNORM; f.src_bpp = 3; f.dst_bpp = 4; f.conversion = NATIVE_TEXTURE_RGB_RGBA;
    f.swizzle.a = VK_COMPONENT_SWIZZLE_ONE; break;
  case CINDER_VK_TEX_RGB565: f.format = VK_FORMAT_R5G6B5_UNORM_PACK16; f.src_bpp = f.dst_bpp = 2; break;
  case CINDER_VK_TEX_RGBA4444: f.format = D.f4444; f.swizzle = D.sw4444; f.src_bpp = f.dst_bpp = 2; break;
  case CINDER_VK_TEX_RGBA5551:
    f.format = D.f5551; f.swizzle = D.sw5551; f.src_bpp = f.dst_bpp = 2;
    if (D.conv5551) f.conversion = NATIVE_TEXTURE_5551_1555;
    break;
  case CINDER_VK_TEX_L8:
    f.format = VK_FORMAT_R8_UNORM; f.src_bpp = f.dst_bpp = 1;
    f.swizzle = (VkComponentMapping){ VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_ONE }; break;
  case CINDER_VK_TEX_LA8:
    f.format = VK_FORMAT_R8G8_UNORM; f.src_bpp = f.dst_bpp = 2;
    f.swizzle = (VkComponentMapping){ VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_G }; break;
  case CINDER_VK_TEX_A8:
    f.format = VK_FORMAT_R8_UNORM; f.src_bpp = f.dst_bpp = 1;
    f.swizzle = (VkComponentMapping){ VK_COMPONENT_SWIZZLE_ZERO, VK_COMPONENT_SWIZZLE_ZERO, VK_COMPONENT_SWIZZLE_ZERO, VK_COMPONENT_SWIZZLE_R }; break;
  case CINDER_VK_TEX_ASTC_4x4: f.format = VK_FORMAT_ASTC_4x4_UNORM_BLOCK; f.block = 4; break;
  case CINDER_VK_TEX_ASTC_6x6: f.format = VK_FORMAT_ASTC_6x6_UNORM_BLOCK; f.block = 6; break;
  case CINDER_VK_TEX_ASTC_8x8: f.format = VK_FORMAT_ASTC_8x8_UNORM_BLOCK; f.block = 8; break;
  default: return 0;
  }
  if (!f.format || (f.block > 1 && !D.astc)) return 0;
  *out = f;
  return 1;
}

static int native_texture_capabilities(const native_texture_format_info *f, uint32_t w, uint32_t h,
                                       uint32_t levels, uint32_t layers, int linear, size_t bytes) {
  if (!D.dev || !D.pd || !w || !h || !levels || !layers ||
      w > D.props.limits.maxImageDimension2D || h > D.props.limits.maxImageDimension2D ||
      (layers == 6 && (w > D.props.limits.maxImageDimensionCube || h > D.props.limits.maxImageDimensionCube))) return 0;
  VkFormatFeatureFlags required = VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT |
    VK_FORMAT_FEATURE_TRANSFER_SRC_BIT | VK_FORMAT_FEATURE_TRANSFER_DST_BIT;
  if (linear) required |= VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
  if (!fmt_has(f->format, required)) return 0;
  VkImageFormatProperties properties = { 0 };
  VkResult result = vkGetPhysicalDeviceImageFormatProperties(D.pd, f->format, VK_IMAGE_TYPE_2D,
    VK_IMAGE_TILING_OPTIMAL, NATIVE_TEXTURE_USAGE, layers == 6 ? VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT : 0, &properties);
  return result == VK_SUCCESS && w <= properties.maxExtent.width && h <= properties.maxExtent.height &&
    properties.maxExtent.depth >= 1 && levels <= properties.maxMipLevels && layers <= properties.maxArrayLayers &&
    (properties.sampleCounts & VK_SAMPLE_COUNT_1_BIT) && (VkDeviceSize)bytes <= properties.maxResourceSize;
}

int cinder_vk_texture_format_supported(cinder_vk_texture_format format) {
  native_texture_format_info f;
  return native_texture_format(format, &f) &&
    native_texture_capabilities(&f, 1, 1, 1, 1, 0, f.block > 1 ? 16 : f.dst_bpp);
}
float cinder_vk_anisotropy_limit(void) {
  return D.dev && D.aniso && isfinite(D.max_aniso) && D.max_aniso >= 1.0f ? D.max_aniso : 1.0f;
}

typedef struct {
  const cinder_vk_texture_subresource *source;
  size_t stride, rows, source_row, output_row, size;
  uint32_t width, height;
  VkBuffer buffer;
  VkDeviceSize offset;
} native_texture_upload;

uint32_t cinder_vk_texture_create(const cinder_vk_texture_desc *desc) {
  native_texture_format_info format;
  if (!desc || desc->width <= 0 || desc->height <= 0 || desc->levels <= 0 || desc->levels > 31 ||
      desc->levels > full_levels(desc->width, desc->height) || (desc->layers != 1 && desc->layers != 6) ||
      (desc->layers == 6 && desc->width != desc->height) || desc->sampler.use_state != VK_TRUE ||
      !native_sampler_valid(&desc->sampler) || !native_texture_format(desc->format, &format) ||
      !desc->subresources || desc->subresource_count != (size_t)desc->levels * (size_t)desc->layers) {
    native_reject(); return 0;
  }
  /* Bounded by the descriptor's 31 levels and 6 faces, never caller-sized heap
   * metadata. Canonical slots permit arbitrary input order but no duplicate. */
  native_texture_upload uploads[31 * 6] = { 0 };
  size_t total = 0;
  for (size_t i = 0; i < desc->subresource_count; ++i) {
    const cinder_vk_texture_subresource *source = &desc->subresources[i];
    if (source->level >= (uint32_t)desc->levels || source->layer >= (uint32_t)desc->layers || !source->data) {
      native_reject(); return 0;
    }
    native_texture_upload *p = &uploads[(size_t)source->layer * (size_t)desc->levels + source->level];
    if (p->source) { native_reject(); return 0; }
    p->source = source;
    p->width = (uint32_t)desc->width >> source->level;
    p->height = (uint32_t)desc->height >> source->level;
    if (!p->width) p->width = 1;
    if (!p->height) p->height = 1;
    if (format.block > 1) {
      size_t columns = ((size_t)p->width + format.block - 1) / format.block;
      p->rows = ((size_t)p->height + format.block - 1) / format.block;
      if (columns > SIZE_MAX / 16) { native_reject(); return 0; }
      p->source_row = p->output_row = columns * 16;
    } else {
      if ((size_t)p->width > SIZE_MAX / format.src_bpp || (size_t)p->width > SIZE_MAX / format.dst_bpp) {
        native_reject(); return 0;
      }
      p->rows = p->height;
      p->source_row = (size_t)p->width * format.src_bpp;
      p->output_row = (size_t)p->width * format.dst_bpp;
    }
    p->stride = source->row_stride ? source->row_stride : p->source_row;
    if (p->stride < p->source_row || (p->rows - 1 && p->stride > (SIZE_MAX - p->source_row) / (p->rows - 1)) ||
        p->rows > SIZE_MAX / p->output_row) { native_reject(); return 0; }
    size_t span = (p->rows - 1) * p->stride + p->source_row;
    p->size = p->rows * p->output_row;
    if (span > source->bytes || span > PTRDIFF_MAX || p->size > PTRDIFF_MAX ||
        (uintptr_t)source->data > UINTPTR_MAX - (span - 1) || total > SIZE_MAX - p->size) {
      native_reject(); return 0;
    }
    total += p->size;
  }
  uploader *u = native_resource_up();
  int linear = desc->sampler.min_filter == VK_FILTER_LINEAR || desc->sampler.mag_filter == VK_FILTER_LINEAR ||
    (desc->sampler.mipmaps && desc->sampler.mipmap_mode == VK_SAMPLER_MIPMAP_MODE_LINEAR);
  if (!u || !native_texture_capabilities(&format, (uint32_t)desc->width, (uint32_t)desc->height,
                                        (uint32_t)desc->levels, (uint32_t)desc->layers, linear, total)) {
    native_reject(); return 0;
  }
  vimg *im = image_new_usage(format.format, desc->width, desc->height, desc->levels, desc->layers,
                            1, 1, 0, format.swizzle, NATIVE_TEXTURE_USAGE);
  if (!im) { native_reject(); return 0; }
  if (im->view_levels != desc->levels) {
    VkImageView view = VK_NULL_HANDLE;
    if (view_try(im, 1, desc->levels, &view) != VK_SUCCESS || !view) {
      if (view) vkDestroyImageView(D.dev, view, NULL);
      image_free_now(im); native_reject(); return 0;
    }
    /* No commands/descriptors ever saw the constructor's single-level view. */
    if (im->view) vkDestroyImageView(D.dev, im->view, NULL);
    im->view = view;
    im->view_levels = desc->levels;
  }
  /* Preparing several spans is one cursor transaction. Retain any grown
   * backing/table capacity on failure, but restore the existing prefix cursor
   * so a loader with no open commands can reuse the unreferenced stage bytes. */
  size_t stage_i = u->stage.i;
  VkDeviceSize stage_used = u->stage.used;
  for (size_t i = 0; i < desc->subresource_count; ++i) {
    native_texture_upload *p = &uploads[i];
    uint8_t *dst = native_ring_alloc(&u->stage, p->size, 16, &p->buffer, &p->offset);
    if (!dst || !p->buffer || p->offset > UINT64_MAX - p->size || p->offset % 16) {
      u->stage.i = stage_i; u->stage.used = stage_used;
      image_free_now(im); native_reject(); return 0;
    }
    for (size_t row = 0; row < p->rows; ++row) {
      const uint8_t *src = (const uint8_t *)p->source->data + row * p->stride;
      uint8_t *out = dst + row * p->output_row;
      if (format.conversion == NATIVE_TEXTURE_RGB_RGBA) {
        for (size_t x = 0; x < p->width; ++x) {
          memcpy(out + 4 * x, src + 3 * x, 3); out[4 * x + 3] = 255;
        }
      } else if (format.conversion == NATIVE_TEXTURE_5551_1555) {
        for (size_t x = 0; x < p->width; ++x) {
          uint16_t value; memcpy(&value, src + 2 * x, sizeof value);
          value = (uint16_t)((value >> 1) | ((value & 1u) << 15));
          memcpy(out + 2 * x, &value, sizeof value);
        }
      } else memcpy(out, src, p->source_row);
    }
  }
  uint32_t id = tex_gen();
  vtex *texture = tex_get(id);
  if (!id || !texture) {
    u->stage.i = stage_i; u->stage.used = stage_used;
    image_free_now(im); native_reject(); return 0;
  }
  VkCommandBuffer cmd = native_up_cmd(u);
  if (!cmd || (native_upload_stream == CINDER_VK_UPLOAD_LOADER && !native_image_upload_hold(im))) {
    u->stage.i = stage_i; u->stage.used = stage_used;
    tex_release(id); image_free_now(im); native_reject(); return 0;
  }
  /* No cursor rollback beyond this point: commands may retain every span even
   * when subsequent loader end/submit/wait/reset reports unknown completion. */
  for (size_t i = 0; i < desc->subresource_count; ++i) {
    native_texture_upload *p = &uploads[i];
    uint32_t level = (uint32_t)(i % (size_t)desc->levels), layer = (uint32_t)(i / (size_t)desc->levels);
    barrier(cmd, im, (int)level, 1, (int)layer, 1, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    VkBufferImageCopy copy = { p->offset, 0, 0, { VK_IMAGE_ASPECT_COLOR_BIT, level, layer, 1 }, { 0, 0, 0 },
      { p->width, p->height, 1 } };
    vkCmdCopyBufferToImage(cmd, p->buffer, im->img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &copy);
    barrier(cmd, im, (int)level, 1, (int)layer, 1, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, im->rest);
  }
  im->level_mask = (1u << (unsigned)desc->levels) - 1u;
  im->in_rest = im->defined = 1;
  texture->im = im;
  texture->native_sampler = desc->sampler;
  if (native_upload_stream == CINDER_VK_UPLOAD_LOADER && u->stage.n > 4) {
    loader_flush();
    if (native_loader_failed) { cinder_vk_texture_destroy(id); native_reject(); return 0; }
  }
  return id;
}
#undef NATIVE_TEXTURE_USAGE
