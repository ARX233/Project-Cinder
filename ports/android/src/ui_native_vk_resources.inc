/* Immutable single-level UI uploads. No GL binding, pixel-store or context state. */
#include <limits.h>
#include "native_vk.h"

static uint32_t ui_native_texture_rgba8(unsigned w, unsigned h, const void *pixels) {
  if (!pixels || !w || !h || w > INT_MAX || h > INT_MAX ||
      (size_t)w > SIZE_MAX / 4 / h) return 0;
  const cinder_vk_sampler sampler = {
    .use_state = VK_TRUE, .mipmaps = VK_FALSE,
    .min_filter = VK_FILTER_LINEAR, .mag_filter = VK_FILTER_LINEAR,
    .mipmap_mode = VK_SAMPLER_MIPMAP_MODE_NEAREST,
    .address_u = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    .address_v = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .anisotropy = 1.0f
  };
  return cinder_vk_texture_rgba8((int)w, (int)h, pixels, (size_t)w * h * 4, &sampler);
}
