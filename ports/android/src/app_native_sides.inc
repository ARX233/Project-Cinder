/* Explicit wide-side commands. Resource creation is still the shared allocator
 * in sides_target; no framebuffer/viewport, VAO or uniform state is consulted. */
#include "native_vk.h"

static int sides_native_copy(uint32_t target, int width, int height, int xl, int xr) {
  if (!target || width <= 0 || height <= 0 || xl < 0 || xr < 0 || xl >= width || xr >= width) return 0;
  /* Preserve the Adreno workaround exactly: screen endpoints are asset coords,
   * so core's screen-origin transform makes these copies physically straight.
   * The resulting texture rows still require wide_sides' v0=1, v1=0. */
  const cinder_vk_copy_region left={
    .source=0, .target=target,
    .source_rect={xl,height,xl+1,0}, .target_rect={xl,0,xl+1,height},
    .aspects=VK_IMAGE_ASPECT_COLOR_BIT, .filter=VK_FILTER_NEAREST,
  }, right={
    .source=0, .target=target,
    .source_rect={xr,height,xr+1,0}, .target_rect={xr,0,xr+1,height},
    .aspects=VK_IMAGE_ASPECT_COLOR_BIT, .filter=VK_FILTER_NEAREST,
  };
  /* Both columns are attempted, as on the compatibility path. Return this
   * command epoch's result; never drain glGetError (an older sticky error). */
  int left_ok=cinder_vk_copy(&left);
  int right_ok=cinder_vk_copy(&right);
  return left_ok && right_ok;
}

static int sides_native_draw(uint32_t program, uint32_t texture, int width, int height, const float vertices[20]) {
  cinder_vk_draw d;
  if (!texture || !vertices || !cinder_vk_draw_init(&d,program,0,width,height)) return 0;
  d.pipeline=(cinder_vk_pipeline){
    .topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP, .blend=VK_FALSE,
    .src_blend=VK_BLEND_FACTOR_ONE, .dst_blend=VK_BLEND_FACTOR_ZERO,
    .blend_op=VK_BLEND_OP_ADD, .color_mask=15,
    .depth_test=VK_FALSE, .depth_write=VK_FALSE, .depth_compare=VK_COMPARE_OP_LESS_OR_EQUAL,
    .cull=VK_CULL_MODE_NONE, .asset_front=VK_FRONT_FACE_COUNTER_CLOCKWISE,
    .stencil=VK_FALSE, .stencil_compare=VK_COMPARE_OP_ALWAYS,
    .stencil_fail=VK_STENCIL_OP_KEEP, .depth_fail=VK_STENCIL_OP_KEEP, .depth_pass=VK_STENCIL_OP_KEEP,
    .stencil_compare_mask=255, .stencil_write_mask=255,
  };
  for (int i=0; i<CINDER_VK_ATTRIBUTES; ++i)
    d.attributes[i]=(cinder_vk_attribute){.format=VK_FORMAT_UNDEFINED, .value={1,1,1,1}};
  d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT, .stride=20,
    .data=vertices, .bytes=20*sizeof(float)};
  d.attributes[1]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT, .stride=20, .offset=2*sizeof(float),
    .data=vertices, .bytes=20*sizeof(float)};
  d.attributes[2]=(cinder_vk_attribute){.format=VK_FORMAT_R32_SFLOAT, .stride=20, .offset=4*sizeof(float),
    .data=vertices, .bytes=20*sizeof(float)};
  const cinder_vk_sampler sampler={
    .use_state=VK_TRUE, .mipmaps=VK_FALSE,
    .min_filter=VK_FILTER_LINEAR, .mag_filter=VK_FILTER_LINEAR,
    .mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,
    .address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    .address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .anisotropy=1,
  };
  float dy=1.5f/(float)height;
  d.count=4;
  return cinder_vk_uniform(&d,"uDy",&dy,sizeof dy) &&
    cinder_vk_texture(&d,"uTex",texture) && cinder_vk_sampler_state(&d,"uTex",&sampler) && cinder_vk_submit(&d);
}
