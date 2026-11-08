/* Included in vkgl.c beside the shared Vulkan executor, NOT a GL adapter.
 * This implementation deliberately never reads ctx(), cur_vao(), p->shadow,
 * p->samp_unit, or calls the compatibility draw()/key_state()/open_pass(). */
#include "native_vk.h"
#include <limits.h>
#include <math.h>

static uint64_t native_draw_count, native_reject_count, native_clear_count, native_copy_count, native_discard_count;

void cinder_vk_screen_extent(int *width, int *height) {
  if (width) *width = S.w;
  if (height) *height = S.h;
}
void cinder_vk_get_coverage(cinder_vk_coverage *out) {
  if (!out) return;
  out->native_draws = __atomic_load_n(&native_draw_count, __ATOMIC_RELAXED);
  out->compatibility_draws = __atomic_load_n(&compat_draw_count, __ATOMIC_RELAXED);
  out->rejected_packets = __atomic_load_n(&native_reject_count, __ATOMIC_RELAXED);
  out->native_clears = __atomic_load_n(&native_clear_count, __ATOMIC_RELAXED);
  out->native_copies = __atomic_load_n(&native_copy_count, __ATOMIC_RELAXED);
  out->native_discards = __atomic_load_n(&native_discard_count, __ATOMIC_RELAXED);
}
static int native_reject(void) {
  uint64_t old = __atomic_load_n(&native_reject_count, __ATOMIC_RELAXED);
  while (old != UINT64_MAX &&
         !__atomic_compare_exchange_n(&native_reject_count, &old, old + 1, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {}
  return 0;
}
uint64_t cinder_vk_error_epoch(void) {
  return __atomic_load_n(&native_reject_count, __ATOMIC_RELAXED);
}
static int native_program_valid(const vprog *p) {
  return p && p->vs && p->fs && p->block >= 0 && p->block <= CINDER_VK_UNIFORM_BYTES &&
         p->n_samp >= 0 && p->n_samp <= CINDER_VK_SAMPLERS && !(p->inputs >> CINDER_VK_ATTRIBUTES);
}
int cinder_vk_draw_init(cinder_vk_draw *d, uint32_t program, uint32_t target, int w, int h) {
  vprog *p = prog_get(program);
  if (!d || !native_program_valid(p) || w <= 0 || h <= 0) return 0;
  memset(d, 0, sizeof *d);
  d->program = program; d->target = target; d->uniform_bytes = (uint32_t)p->block;
  d->viewport[2] = d->scissor[2] = w;
  d->viewport[3] = d->scissor[3] = h;
  d->pipeline = (cinder_vk_pipeline){
    .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST,
    .src_blend = VK_BLEND_FACTOR_ONE, .dst_blend = VK_BLEND_FACTOR_ZERO,
    .blend_op = VK_BLEND_OP_ADD, .color_mask = 15,
    .depth_compare = VK_COMPARE_OP_LESS_OR_EQUAL,
    .asset_front = VK_FRONT_FACE_COUNTER_CLOCKWISE,
    .stencil_compare = VK_COMPARE_OP_ALWAYS,
    .stencil_fail = VK_STENCIL_OP_KEEP, .depth_fail = VK_STENCIL_OP_KEEP, .depth_pass = VK_STENCIL_OP_KEEP,
    .stencil_compare_mask = 255, .stencil_write_mask = 255,
  };
  for (int i = 0; i < CINDER_VK_ATTRIBUTES; ++i) d->attributes[i].value[3] = 1.0f;
  d->index_type = VK_INDEX_TYPE_UINT16;
  return 1;
}
int cinder_vk_uniform(cinder_vk_draw *d, const char *name, const void *value, size_t n) {
  if (!d || !name || !value) return 0;
  vprog *p = prog_get(d->program);
  if (!native_program_valid(p) || d->uniform_bytes != (uint32_t)p->block) return 0;
  static const size_t sizes[] = {0, 4, 8, 12, 16, 4, 64};
  for (int i = 0; i < p->n_uni; ++i) {
    const vuni *u = &p->uni[i];
    if (strcmp(u->name, name)) continue;
    if (u->code < 1 || u->code > 6 || n != sizes[u->code] || u->off < 0 ||
        (size_t)u->off > d->uniform_bytes || n > d->uniform_bytes - (size_t)u->off) return 0;
    memcpy(d->uniforms + u->off, value, n);
    return 1;
  }
  return 1; /* optimized-out optional value */
}
int cinder_vk_texture(cinder_vk_draw *d, const char *name, uint32_t texture) {
  if (!d || !name) return 0;
  vprog *p = prog_get(d->program);
  if (!native_program_valid(p)) return 0;
  for (int i = 0; i < p->n_uni; ++i) {
    const vuni *u = &p->uni[i];
    if (strcmp(u->name, name)) continue;
    if (u->code < 7 || u->code > 8 || u->off < 1 || u->off > p->n_samp) return 0;
    d->textures[u->off - 1] = texture;
    return 1;
  }
  return 1;
}
int cinder_vk_sampler_state(cinder_vk_draw *d, const char *name, const cinder_vk_sampler *sampler) {
  if (!d || !name || !sampler) return 0;
  vprog *p = prog_get(d->program);
  if (!native_program_valid(p)) return 0;
  for (int i = 0; i < p->n_uni; ++i) {
    const vuni *u = &p->uni[i];
    if (strcmp(u->name, name)) continue;
    if (u->code < 7 || u->code > 8 || u->off < 1 || u->off > p->n_samp) return 0;
    d->samplers[u->off - 1] = *sampler;
    return 1;
  }
  return 1;
}

/* Only formats already supported by the shared pipeline executor are admitted.
 * Unsupported formats fail closed, never silently change the vertex layout. */
static int native_format(VkFormat format, int *size) {
  for (int i = 1; i < N_VFMT; ++i) if (VFMT[i] == format) {
    /* A driver may require vec3 to be fetched as vec4. Bound the actual GPU
     * read, not only the source declaration, including the final vertex. */
    for (int j = 1; j < N_VFMT; ++j) if (VFMT[j] == vfmt_dev[i]) {
      int n = (j - 1) % 4 + 1;
      *size = n * (j <= 4 ? 4 : j >= 13 && j <= 24 ? 2 : 1);
      return i;
    }
    return 0;
  }
  return 0;
}
static int native_span(size_t total, size_t offset, size_t count, size_t stride, size_t size) {
  if (!count || offset > total || size > total - offset) return 0;
  return count - 1 <= (total - offset - size) / stride;
}
static int native_box_valid(const int b[4]) {
  return b[0] >= 0 && b[1] >= 0 && b[2] > 0 && b[3] > 0 &&
         b[0] <= INT_MAX - b[2] && b[1] <= INT_MAX - b[3];
}
/* Packet and clear ordering share only the low-level pass record, never a
 * compatibility context. Extent/compatibility are included when joining. */
static vop *native_open_target(const vop *target) {
  if (cur_pass < 0 || ops[cur_pass].kind != OP_PASS ||
      ops[cur_pass].color != target->color || ops[cur_pass].depth != target->depth ||
      ops[cur_pass].resolve != target->resolve || ops[cur_pass].screen != target->screen ||
      ops[cur_pass].compat != target->compat || ops[cur_pass].w != target->w || ops[cur_pass].h != target->h) {
    GROW(ops, n_ops, cap_ops);
    ops[n_ops] = *target;
    ops[n_ops].first = n_items;
    cur_pass = (long)n_ops++;
  }
  return &ops[cur_pass];
}
/* Successful recording gives level zero planned contents for later packets.
 * NOT GPU completion, defined/in_rest, a layout transition, or other mip levels:
 * replay still owns ordering/barriers. Depth views expose depth, not stencil. */
static void native_written_level0(vimg *im, VkImageAspectFlags aspects) {
  if (im && (aspects & (is_depth(im->fmt) ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT)))
    im->level_mask |= 1u;
}
static void native_written_target(const vop *target, VkImageAspectFlags aspects) {
  native_written_level0(target->color, aspects & VK_IMAGE_ASPECT_COLOR_BIT);
  native_written_level0(target->resolve, aspects & VK_IMAGE_ASPECT_COLOR_BIT);
  native_written_level0(target->depth, aspects & VK_IMAGE_ASPECT_DEPTH_BIT);
}
int cinder_vk_clear(uint32_t target_id, VkImageAspectFlags aspects, const float color[4], const int rect[4]) {
  const VkImageAspectFlags allowed = VK_IMAGE_ASPECT_COLOR_BIT | VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT;
  if (aspects & ~allowed) return native_reject();
  if (!aspects) return 1;
  if (!F) return native_reject();
  vop target;
  if (!fb_target(target_id, &target)) return native_reject();
  int bits = 0;
  if (aspects & VK_IMAGE_ASPECT_COLOR_BIT) {
    if (!target.color || !color) return native_reject();
    for (int i = 0; i < 4; ++i) if (!isfinite(color[i])) return native_reject();
    bits |= GL_COLOR_BUFFER_BIT;
  }
  if (aspects & VK_IMAGE_ASPECT_DEPTH_BIT) {
    if (!target.depth) return native_reject();
    bits |= GL_DEPTH_BUFFER_BIT;
  }
  if (aspects & VK_IMAGE_ASPECT_STENCIL_BIT) {
    if (!target.depth || !has_stencil(target.depth->fmt)) return native_reject();
    bits |= GL_STENCIL_BUFFER_BIT;
  }
  int full_rect[4] = {0, 0, target.w, target.h};
  if (!rect) rect = full_rect;
  if (!native_box_valid(rect) || rect[0] > target.w || rect[1] > target.h ||
      rect[2] > target.w - rect[0] || rect[3] > target.h - rect[1]) return native_reject();
  vop *o = native_open_target(&target);
  int full = rect[0] == 0 && rect[1] == 0 && rect[2] == target.w && rect[3] == target.h;
  if (!o->n && full) {
    o->clear |= bits;
    if (bits & GL_COLOR_BUFFER_BIT) memcpy(o->cc, color, sizeof o->cc);
  } else {
    GROW(items, n_items, cap_items);
    vitem *it = &items[n_items++];
    memset(it, 0, sizeof *it);
    it->kind = IT_CLEAR; it->bits = bits;
    if (bits & GL_COLOR_BUFFER_BIT) memcpy(it->cc, color, sizeof it->cc);
    box_vk(rect, o, it->sc);
    o->n = n_items - o->first;
  }
  native_written_target(&target, aspects);
  __atomic_add_fetch(&native_clear_count, 1, __ATOMIC_RELAXED);
  return 1;
}

int cinder_vk_target_info(uint32_t id, cinder_vk_target_desc *out) {
  if (!out) return 0;
  memset(out, 0, sizeof *out);
  vop t;
  if (!fb_target(id, &t)) return 0;
  const vimg *attachment = t.color ? t.color : t.depth;
  if (!attachment || t.w <= 0 || t.h <= 0 || attachment->samples < 1) return 0;
  *out = (cinder_vk_target_desc){t.w, t.h, t.color ? t.color->fmt : VK_FORMAT_UNDEFINED,
    t.depth ? t.depth->fmt : VK_FORMAT_UNDEFINED, (VkSampleCountFlagBits)attachment->samples, t.resolve != NULL,
    t.color ? t.color->usage : 0, t.depth ? t.depth->usage : 0, t.resolve ? t.resolve->usage : 0};
  return 1;
}
static int native_copy_rect_valid(const int *r, int w, int h) {
  return r[0] >= 0 && r[0] <= w && r[2] >= 0 && r[2] <= w && r[1] >= 0 && r[1] <= h &&
    r[3] >= 0 && r[3] <= h && r[0] != r[2] && r[1] != r[3];
}
/* The normalized/float attachment formats supported by this renderer. Integer
 * color formats are deliberately not converted across numeric classes. */
static int native_color_blit_format(VkFormat f) {
  switch (f) {
  case VK_FORMAT_R4G4B4A4_UNORM_PACK16: case VK_FORMAT_B4G4R4A4_UNORM_PACK16:
  case VK_FORMAT_R5G6B5_UNORM_PACK16: case VK_FORMAT_B5G6R5_UNORM_PACK16:
  case VK_FORMAT_R5G5B5A1_UNORM_PACK16: case VK_FORMAT_B5G5R5A1_UNORM_PACK16: case VK_FORMAT_A1R5G5B5_UNORM_PACK16:
  case VK_FORMAT_R8_UNORM: case VK_FORMAT_R8G8_UNORM: case VK_FORMAT_R8G8B8_UNORM: case VK_FORMAT_B8G8R8_UNORM:
  case VK_FORMAT_R8G8B8A8_UNORM: case VK_FORMAT_B8G8R8A8_UNORM: case VK_FORMAT_R8G8B8A8_SRGB: case VK_FORMAT_B8G8R8A8_SRGB:
  case VK_FORMAT_A2R10G10B10_UNORM_PACK32: case VK_FORMAT_A2B10G10R10_UNORM_PACK32:
  case VK_FORMAT_R16_SFLOAT: case VK_FORMAT_R16G16_SFLOAT: case VK_FORMAT_R16G16B16A16_SFLOAT:
  case VK_FORMAT_R32_SFLOAT: case VK_FORMAT_R32G32_SFLOAT: case VK_FORMAT_R32G32B32A32_SFLOAT:
  case VK_FORMAT_B10G11R11_UFLOAT_PACK32: case VK_FORMAT_E5B9G9R9_UFLOAT_PACK32:
    return 1;
  default: return 0;
  }
}
static int native_copy_prepare(const cinder_vk_copy_region *r, vop prepared[2], int *count) {
  *count = 0;
  const VkImageAspectFlags allowed = VK_IMAGE_ASPECT_COLOR_BIT | VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT;
  if (!r || (r->aspects & ~allowed) || (uint32_t)r->filter > VK_FILTER_LINEAR) return 0;
  if (!r->aspects) return 1;
  vop source, target; int n = 0;
  if (!fb_target(r->source, &source) || !fb_target(r->target, &target) || target.resolve ||
      !native_copy_rect_valid(r->source_rect, source.w, source.h) ||
      !native_copy_rect_valid(r->target_rect, target.w, target.h)) return 0;
  for (int depth = 0; depth < 2; ++depth) {
    VkImageAspectFlags aspects = r->aspects & (depth ? VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT : VK_IMAGE_ASPECT_COLOR_BIT);
    if (!aspects) continue;
    vop b; memset(&b, 0, sizeof b); b.kind = OP_BLIT;
    b.src = depth ? source.depth : source.resolve ? source.resolve : source.color;
    b.dst = depth ? target.depth : target.resolve ? target.resolve : target.color;
    if (!b.src || !b.dst || b.src == b.dst || b.src->samples < 1 || b.dst->samples != 1 ||
        !(b.src->usage & VK_IMAGE_USAGE_TRANSFER_SRC_BIT) || !(b.dst->usage & VK_IMAGE_USAGE_TRANSFER_DST_BIT) ||
        !fmt_has(b.src->fmt, VK_FORMAT_FEATURE_TRANSFER_SRC_BIT) ||
        !fmt_has(b.dst->fmt, VK_FORMAT_FEATURE_TRANSFER_DST_BIT)) return 0;
    b.copy_aspects = aspects; b.filter = r->filter;
    b.src_screen = b.src == &SCREEN; b.dst_screen = b.dst == &SCREEN;
    memcpy(b.s, r->source_rect, sizeof b.s); memcpy(b.d, r->target_rect, sizeof b.d);
    if (source.screen) { b.s[1] = source.h - b.s[1]; b.s[3] = source.h - b.s[3]; }
    if (target.screen) { b.d[1] = target.h - b.d[1]; b.d[3] = target.h - b.d[3]; }
    if (depth) {
      if (b.src->samples != 1 || r->filter != VK_FILTER_NEAREST || b.src->fmt != b.dst->fmt ||
          ((aspects & VK_IMAGE_ASPECT_DEPTH_BIT) && !is_depth(b.src->fmt)) ||
          ((aspects & VK_IMAGE_ASPECT_STENCIL_BIT) && !has_stencil(b.src->fmt))) return 0;
    } else {
      if (!native_color_blit_format(b.src->fmt) || !native_color_blit_format(b.dst->fmt)) return 0;
      b.resolve_blit = b.src->samples > 1;
      if (b.resolve_blit && (b.src->fmt != b.dst->fmt ||
          abs(b.s[2]-b.s[0]) != abs(b.d[2]-b.d[0]) || abs(b.s[3]-b.s[1]) != abs(b.d[3]-b.d[1]) ||
          (b.s[2] > b.s[0]) != (b.d[2] > b.d[0]) || (b.s[3] > b.s[1]) != (b.d[3] > b.d[1]))) return 0;
    }
    if (!b.resolve_blit && (!fmt_has(b.src->fmt, VK_FORMAT_FEATURE_BLIT_SRC_BIT) ||
        !fmt_has(b.dst->fmt, VK_FORMAT_FEATURE_BLIT_DST_BIT) ||
        (r->filter == VK_FILTER_LINEAR && !fmt_has(b.src->fmt, VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT)))) return 0;
    prepared[n++] = b;
  }
  *count = n;
  return 1;
}
/* A capability query shares every recording predicate, but never splits a pass,
 * stamps a resource, increments rejection diagnostics or depends on main F. */
int cinder_vk_copy_ready(const cinder_vk_copy_region *r) {
  vop prepared[2]; int count;
  return native_copy_prepare(r, prepared, &count);
}
int cinder_vk_copy(const cinder_vk_copy_region *r) {
  vop copy[2]; int n;
  if (!native_copy_prepare(r, copy, &n)) return native_reject();
  if (!n) return 1;
  if (!F) return native_reject();
  /* Atomic admission: no command, pass split or lifetime mutation before every
   * requested aspect has been checked. Resource metadata lookup may allocate. */
  cur_pass = -1;
  for (int i = 0; i < n; ++i) {
    GROW(ops, n_ops, cap_ops);
    ops[n_ops++] = copy[i];
    copy[i].src->serial = copy[i].dst->serial = D.serial;
    native_written_level0(copy[i].dst, copy[i].copy_aspects);
  }
  __atomic_add_fetch(&native_copy_count, 1, __ATOMIC_RELAXED);
  return 1;
}
int cinder_vk_discard(uint32_t id, VkImageAspectFlags aspects) {
  const VkImageAspectFlags allowed = VK_IMAGE_ASPECT_COLOR_BIT | VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT;
  if (aspects & ~allowed) return native_reject();
  if (!aspects) return 1;
  if (!F) return native_reject();
  vop t;
  if (!fb_target(id, &t)) return native_reject();
  int bits = 0;
  if ((aspects & VK_IMAGE_ASPECT_COLOR_BIT) && t.color) bits |= GL_COLOR_BUFFER_BIT;
  if ((aspects & VK_IMAGE_ASPECT_DEPTH_BIT) && t.depth) bits |= GL_DEPTH_BUFFER_BIT;
  if ((aspects & VK_IMAGE_ASPECT_STENCIL_BIT) && t.depth && has_stencil(t.depth->fmt)) bits |= GL_STENCIL_BUFFER_BIT;
  if (bits && n_ops) {
    vop *o = &ops[n_ops-1];
    if (o->kind == OP_PASS && o->color == t.color && o->depth == t.depth && o->resolve == t.resolve &&
        o->screen == t.screen && o->compat == t.compat && o->w == t.w && o->h == t.h) {
      o->discard |= bits;
      cur_pass = -1;
    }
    /* A post-copy invalidation is only a hint. Do not erase the prior pass's
     * store: that copy still reads it at replay. Keeping contents is legal. */
  }
  __atomic_add_fetch(&native_discard_count, 1, __ATOMIC_RELAXED);
  return 1;
}

static void native_key(pkey *k, const cinder_vk_draw *d, const vprog *p, const vop *o) {
  const cinder_vk_pipeline *s = &d->pipeline;
  memset(k, 0, sizeof *k);
  k->prog = p->uid; k->compat = (uint16_t)o->compat; k->flip = (uint8_t)o->screen;
  k->topo = (uint8_t)s->topology;
  if (compats[o->compat].cfmt) {
    k->blend = !!s->blend; k->bsrc = (uint8_t)s->src_blend; k->bdst = (uint8_t)s->dst_blend;
    k->beq = (uint8_t)s->blend_op; k->cmask = (uint8_t)s->color_mask;
  }
  if (compats[o->compat].dfmt) {
    k->depth_test = !!s->depth_test; k->depth_write = !!s->depth_write; k->dfunc = (uint8_t)s->depth_compare;
    if (s->stencil && has_stencil(compats[o->compat].dfmt)) {
      k->stencil = 1; k->sfunc = (uint8_t)s->stencil_compare;
      k->sfail = (uint8_t)s->stencil_fail; k->szfail = (uint8_t)s->depth_fail; k->szpass = (uint8_t)s->depth_pass;
      k->smask = (uint8_t)s->stencil_compare_mask; k->swmask = (uint8_t)s->stencil_write_mask;
    }
  }
  k->cull = (uint8_t)s->cull;
  k->front_ccw = (uint8_t)((s->asset_front == VK_FRONT_FACE_COUNTER_CLOCKWISE) == !!o->screen);
}
static int native_sampler_valid(const cinder_vk_sampler *s) {
  if (!s->use_state) return 1;
  return s->use_state == 1 && s->mipmaps <= 1 &&
    (uint32_t)s->min_filter <= VK_FILTER_LINEAR && (uint32_t)s->mag_filter <= VK_FILTER_LINEAR &&
    (uint32_t)s->mipmap_mode <= VK_SAMPLER_MIPMAP_MODE_LINEAR &&
    (uint32_t)s->address_u <= VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE &&
    (uint32_t)s->address_v <= VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE &&
    isfinite(s->anisotropy) && s->anisotropy >= 1.0f;
}
static int native_pipeline_valid(const cinder_vk_pipeline *p) {
  return (uint32_t)p->topology <= VK_PRIMITIVE_TOPOLOGY_TRIANGLE_FAN && p->blend <= 1 &&
    (uint32_t)p->src_blend <= VK_BLEND_FACTOR_SRC_ALPHA_SATURATE && (uint32_t)p->dst_blend <= VK_BLEND_FACTOR_SRC_ALPHA_SATURATE &&
    (uint32_t)p->blend_op <= VK_BLEND_OP_MAX && !(p->color_mask & ~15u) && p->depth_test <= 1 && p->depth_write <= 1 &&
    (uint32_t)p->depth_compare <= VK_COMPARE_OP_ALWAYS && !(p->cull & ~VK_CULL_MODE_FRONT_AND_BACK) &&
    (uint32_t)p->asset_front <= VK_FRONT_FACE_CLOCKWISE && p->stencil <= 1 && (uint32_t)p->stencil_compare <= VK_COMPARE_OP_ALWAYS &&
    (uint32_t)p->stencil_fail <= VK_STENCIL_OP_DECREMENT_AND_WRAP && (uint32_t)p->depth_fail <= VK_STENCIL_OP_DECREMENT_AND_WRAP &&
    (uint32_t)p->depth_pass <= VK_STENCIL_OP_DECREMENT_AND_WRAP && p->stencil_compare_mask <= 255 && p->stencil_write_mask <= 255;
}
int cinder_vk_submit(const cinder_vk_draw *d) {
  if (!d) return native_reject();
  if (!d->count) return 1;
  vprog *p = prog_get(d->program);
  if (!native_program_valid(p) || d->uniform_bytes != (uint32_t)p->block ||
      !native_pipeline_valid(&d->pipeline) || !native_box_valid(d->viewport) || !native_box_valid(d->scissor) ||
      d->count > INT_MAX || d->first > INT_MAX - d->count || d->indexed > 1 || d->warm_only > 1 ||
      (d->indexed && d->index_type != VK_INDEX_TYPE_UINT16 && d->index_type != VK_INDEX_TYPE_UINT32)) return native_reject();
  vop target;
  if (!fb_target(d->target, &target)) return native_reject();
  VkFormat depth_format = compats[target.compat].dfmt;
  if ((d->pipeline.depth_test && !depth_format) ||
      (d->pipeline.stencil && (!depth_format || !has_stencil(depth_format)))) return native_reject();
  if (d->scissor[0] > target.w || d->scissor[1] > target.h ||
      d->scissor[2] > target.w - d->scissor[0] || d->scissor[3] > target.h - d->scissor[1]) return native_reject();
  size_t top = (size_t)d->first + d->count - 1;
  const unsigned char *idx = NULL;
  vbuf *eb = NULL;
  size_t index_size = d->index_type == VK_INDEX_TYPE_UINT32 ? 4 : 2;
  if (d->indexed) {
    if (d->first) return native_reject(); /* no implicit base-index convention */
    if (d->index_offset % index_size) return native_reject();
    if (d->index_buffer) {
      eb = buf_get(d->index_buffer);
      if (!eb || !eb->m || !native_span((size_t)eb->m->size, d->index_offset, d->count, index_size, index_size)) return native_reject();
      idx = eb->m->map + d->index_offset;
    } else {
      if (!d->indices || !native_span(d->index_bytes, d->index_offset, d->count, index_size, index_size)) return native_reject();
      idx = (const unsigned char *)d->indices + d->index_offset;
    }
    top = 0;
    for (uint32_t i = 0; i < d->count; ++i) {
      uint32_t n = 0;
      if (index_size == 2) { uint16_t v; memcpy(&v, idx + (size_t)i * 2, 2); n = v; }
      else memcpy(&n, idx + (size_t)i * 4, 4);
      if (n > top) top = n;
    }
  }
  pkey k;
  native_key(&k, d, p, &target);
  int sizes[MAX_ATTR] = {0};
  vbuf *buffers[MAX_ATTR] = {0};
  for (int i = 0; i < MAX_ATTR; ++i) {
    if (!(p->inputs >> i & 1)) continue;
    const cinder_vk_attribute *a = &d->attributes[i];
    if (a->format == VK_FORMAT_UNDEFINED) { k.afmt[i] = 4; k.inst |= (uint8_t)(1u << i); k.astride[i] = 16; continue; }
    int format = native_format(a->format, &sizes[i]);
    if (!format || a->stride < (uint32_t)sizes[i] || a->stride > UINT16_MAX) return native_reject();
    k.afmt[i] = (uint8_t)format; k.astride[i] = (uint16_t)a->stride;
    size_t span = a->bytes;
    if (a->buffer) {
      buffers[i] = buf_get(a->buffer);
      if (!buffers[i] || !buffers[i]->m) return native_reject();
      span = (size_t)buffers[i]->m->size;
    } else if (!a->data) return native_reject();
    if (top == SIZE_MAX || !native_span(span, a->offset, top + 1, a->stride, (size_t)sizes[i])) return native_reject();
  }
  /* Validate every sampled image and reject attachment feedback before recording. */
  vtex *textures[MAX_SAMP] = {0};
  for (int i = 0; i < p->n_samp; ++i) {
    if (!native_sampler_valid(&d->samplers[i])) return native_reject();
    if (!d->textures[i]) continue; /* explicit optional binding: neutral dummy */
    vtex *t = textures[i] = tex_get(d->textures[i]);
    vimg *im = t ? t->im : NULL;
    if (!im || !im->view || !(im->level_mask & 1) || (im->layers == 6) != p->samp_cube[i] ||
        im == target.color || im == target.depth || im == target.resolve) return native_reject();
  }
  VkPipeline pipeline = pipeline_get(&k, p, NULL);
  if (!pipeline) return native_reject();
  if (d->warm_only) return 1;
  if (!F) return native_reject();
  VkBuffer vb[MAX_ATTR]; VkDeviceSize vo[MAX_ATTR]; uint32_t binding[MAX_ATTR], nvb = 0;
  for (int i = 0; i < MAX_ATTR; ++i) {
    if (!(p->inputs >> i & 1)) continue;
    const cinder_vk_attribute *a = &d->attributes[i];
    if (a->format == VK_FORMAT_UNDEFINED) {
      memcpy(ring_alloc(&F->vtx, 16, 16, &vb[nvb], &vo[nvb]), a->value, 16);
    } else if (buffers[i]) {
      buffers[i]->m->serial = D.serial;
      vb[nvb] = buffers[i]->m->buf; vo[nvb] = a->offset;
    } else {
      size_t bytes = top * a->stride + (size_t)sizes[i];
      memcpy(ring_alloc(&F->vtx, bytes, 16, &vb[nvb], &vo[nvb]), (const unsigned char *)a->data + a->offset, bytes);
    }
    binding[nvb++] = (uint32_t)i;
  }
  VkBuffer ib = VK_NULL_HANDLE; VkDeviceSize ibo = 0;
  if (d->indexed) {
    if (eb) { eb->m->serial = D.serial; ib = eb->m->buf; ibo = d->index_offset; }
    else memcpy(ring_alloc(&F->vtx, (size_t)d->count * index_size, 4, &ib, &ibo), idx, (size_t)d->count * index_size);
  }
  dkey dk;
  memset(&dk, 0, sizeof dk);
  dk.n = p->n_samp; dk.range = (uint32_t)(p->block > 16 ? p->block : 16);
  VkDeviceSize uniform_offset;
  void *uniforms = ring_alloc(&F->ubo, dk.range, D.props.limits.minUniformBufferOffsetAlignment, &dk.ubo, &uniform_offset);
  memset(uniforms, 0, dk.range);
  memcpy(uniforms, d->uniforms, d->uniform_bytes);
  for (int i = 0; i < p->n_samp; ++i) {
    vtex *t = textures[i];
    if (t) {
      t->im->serial = D.serial; dk.v[i] = t->im->view;
      dk.s[i] = d->samplers[i].use_state ? cinder_vk_sampler_get(&d->samplers[i], t->im->view_levels) : sampler_for(t, t->im->view_levels);
    } else {
      dk.v[i] = p->samp_cube[i] ? dummycube->view : dummy2d->view;
      dk.s[i] = d->samplers[i].use_state ? cinder_vk_sampler_get(&d->samplers[i], 1) : dummy_sampler;
    }
    if (!dk.s[i]) return native_reject();
  }
  /* Open by explicit attachments, not by compatibility context bindings. */
  vop *o = native_open_target(&target);
  GROW(items, n_items, cap_items);
  vitem *it = &items[n_items++]; memset(it, 0, sizeof *it);
  it->kind = IT_DRAW; it->pipe = pipeline; it->layout = playout[p->n_samp];
  it->set = desc_get(&dk); it->dyn = (uint32_t)uniform_offset;
  box_vk(d->viewport, o, it->vp); box_vk(d->scissor, o, it->sc);
  it->sref = d->stencil_reference; it->nvb = nvb; it->vb = (uint32_t)n_vb;
  for (uint32_t i = 0; i < nvb; ++i) {
    if (n_vb >= cap_vb) {
      size_t cap = cap_vb ? cap_vb * 2 : 256;
      vbb = realloc(vbb, cap * sizeof *vbb); vbo = realloc(vbo, cap * sizeof *vbo); vbs = realloc(vbs, cap * sizeof *vbs);
      if (!vbb || !vbo || !vbs) abort(); cap_vb = cap_vbo = cap_vbs = cap;
    }
    vbb[n_vb] = vb[i]; vbo[n_vb] = vo[i]; vbs[n_vb++] = binding[i];
  }
  it->indexed = d->indexed; it->ib = ib; it->ibo = ibo; it->itype = d->index_type;
  it->first = d->first; it->count = d->count; o->n = n_items - o->first;
  /* Publish only attachment roles this admitted draw can write. This is not a
   * claim that rasterization touched every texel (nor that the GPU ran yet). */
  int triangles = k.topo >= VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
  uint32_t minimum = triangles ? 3u : k.topo == VK_PRIMITIVE_TOPOLOGY_POINT_LIST ? 1u : 2u;
  if (d->count >= minimum && !(triangles && k.cull == VK_CULL_MODE_FRONT_AND_BACK) &&
      !(k.depth_test && k.dfunc == VK_COMPARE_OP_NEVER) && !(k.stencil && k.sfunc == VK_COMPARE_OP_NEVER) &&
      d->viewport[0] < d->scissor[0] + d->scissor[2] && d->scissor[0] < d->viewport[0] + d->viewport[2] &&
      d->viewport[1] < d->scissor[1] + d->scissor[3] && d->scissor[1] < d->viewport[1] + d->viewport[3]) {
    VkImageAspectFlags written = k.cmask ? VK_IMAGE_ASPECT_COLOR_BIT : 0;
    if (k.depth_test && k.depth_write) written |= VK_IMAGE_ASPECT_DEPTH_BIT;
    native_written_target(&target, written);
  }
  ++frame_draws; __atomic_add_fetch(&native_draw_count, 1, __ATOMIC_RELAXED);
  return 1;
}
