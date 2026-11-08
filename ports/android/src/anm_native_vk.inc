/* ANM's display-space packets. No GL context, VAO or mutable uniform state.
 * texture() still supplies handles from the shared resource table during migration.
 * Every quad is a bounded CPU span; submit copies it before the caller returns. */
#include "native_vk.h"

static int anm_native_quad(const float v[16], uint32_t tex, const float mul[4], const float add[4],
                           unsigned blend, VkBool32 warm_only) {
  int width = 0, height = 0;
  cinder_vk_screen_extent(&width, &height);
  cinder_vk_draw d;
  /* All current ANM callers are display overlays. Warming explicitly creates only
   * the display-compatible pipeline, never a draw in the loader's tiny GL target. */
  if (!cinder_vk_draw_init(&d, A.prog, 0, width, height)) return 0;
  d.pipeline.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP;
  d.pipeline.blend = VK_TRUE;
  d.pipeline.src_blend = VK_BLEND_FACTOR_SRC_ALPHA;
  d.pipeline.dst_blend = blend ? VK_BLEND_FACTOR_ONE : VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
  d.pipeline.blend_op = blend == 2 ? VK_BLEND_OP_REVERSE_SUBTRACT : VK_BLEND_OP_ADD;
  d.pipeline.depth_test = d.pipeline.depth_write = VK_FALSE;
  d.pipeline.cull = VK_CULL_MODE_NONE;
  d.pipeline.stencil = VK_FALSE;
  /* texture() authors a non-mipmapped linear/clamp sampler. Specify it in
   * the packet too, by immutable reflection, with no texture-state inheritance. */
  const cinder_vk_sampler sampler = {
    .use_state = VK_TRUE, .min_filter = VK_FILTER_LINEAR, .mag_filter = VK_FILTER_LINEAR,
    .mipmap_mode = VK_SAMPLER_MIPMAP_MODE_NEAREST,
    .address_u = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .address_v = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    .anisotropy = 1.0f,
  };
  d.attributes[0] = (cinder_vk_attribute){
    .format = VK_FORMAT_R32G32_SFLOAT, .stride = 4 * sizeof(float),
    .data = v, .bytes = 16 * sizeof(float),
  };
  d.attributes[1] = (cinder_vk_attribute){
    .format = VK_FORMAT_R32G32_SFLOAT, .stride = 4 * sizeof(float), .offset = 2 * sizeof(float),
    .data = v, .bytes = 16 * sizeof(float),
  };
  const float view[2] = { 1.0f / (512.0f + A.edge), A.edge / (512.0f + A.edge) - 1.0f };
  if (!cinder_vk_uniform(&d, "uView", view, sizeof view) ||
      !cinder_vk_uniform(&d, "uMul", mul, 4 * sizeof(float)) ||
      !cinder_vk_uniform(&d, "uAdd", add, 4 * sizeof(float)) ||
      !cinder_vk_texture(&d, "uTex", tex) || !cinder_vk_sampler_state(&d, "uTex", &sampler)) return 0;
  d.count = 4;
  d.warm_only = warm_only;
  return cinder_vk_submit(&d);
}
