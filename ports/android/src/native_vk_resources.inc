/* Native resource upload ownership. These streams select Vulkan command pools,
 * not GL bindings, unpack state, programs or texture units. The port has one
 * main frame owner and one platform-designated loader, matching shared uploaders. */
static __thread cinder_vk_upload_stream native_upload_stream;
int cinder_vk_upload_stream_set(cinder_vk_upload_stream stream) {
  if ((uint32_t)stream > CINDER_VK_UPLOAD_LOADER) return native_reject();
  native_upload_stream = stream;
  return 1;
}
cinder_vk_upload_stream cinder_vk_upload_stream_get(void) { return native_upload_stream; }
static uploader *native_resource_up(void) {
  if (!D.dev || (native_upload_stream == CINDER_VK_UPLOAD_LOADER && native_loader_failed)) return NULL;
  uploader *u = native_upload_stream == CINDER_VK_UPLOAD_LOADER ? &LOADER_UP : F ? &F->up : NULL;
  return u && u->pool && u->cmd ? u : NULL;
}
uint32_t cinder_vk_texture_rgba8(int w, int h, const void *pixels, size_t bytes,
                               const cinder_vk_sampler *sampler) {
  if (w <= 0 || h <= 0 || !pixels || !sampler || sampler->use_state != VK_TRUE ||
      sampler->mipmaps || !native_sampler_valid(sampler) ||
      (uint32_t)w > D.props.limits.maxImageDimension2D || (uint32_t)h > D.props.limits.maxImageDimension2D ||
      (size_t)w > SIZE_MAX / 4 / (size_t)h) { native_reject(); return 0; }
  size_t size = (size_t)w * (size_t)h * 4;
  if (size > bytes || size > PTRDIFF_MAX) { native_reject(); return 0; }
  uploader *u = native_resource_up();
  const VkFormat format = VK_FORMAT_R8G8B8A8_UNORM;
  const VkFormatFeatureFlags required = VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT | VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT |
    VK_FORMAT_FEATURE_TRANSFER_SRC_BIT | VK_FORMAT_FEATURE_TRANSFER_DST_BIT;
  if (!u || !fmt_has(format, required) ||
      ((sampler->min_filter == VK_FILTER_LINEAR || sampler->mag_filter == VK_FILTER_LINEAR) &&
       !fmt_has(format, VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT))) { native_reject(); return 0; }
  vimg *im = image_new(format, w, h, 1, 1, 1, 1, 0, SWZ_ID);
  if (!im) { native_reject(); return 0; }
  size_t stage_i = u->stage.i;
  VkDeviceSize stage_used = u->stage.used;
  VkBuffer staging = VK_NULL_HANDLE;
  VkDeviceSize offset = 0;
  uint8_t *dst = native_ring_alloc(&u->stage, size, 16, &staging, &offset);
  if (!dst || !staging || offset > UINT64_MAX-size || offset % 4) {
    u->stage.i = stage_i; u->stage.used = stage_used;
    image_free_now(im); native_reject(); return 0;
  }
  memcpy(dst, pixels, size);
  uint32_t id = tex_gen();
  vtex *t = tex_get(id);
  if (!id || !t) {
    u->stage.i = stage_i; u->stage.used = stage_used;
    image_free_now(im); native_reject(); return 0;
  }
  t->im = im;
  t->native_sampler = *sampler;
  VkCommandBuffer cmd = native_up_cmd(u);
  if (!cmd || (native_upload_stream == CINDER_VK_UPLOAD_LOADER && !native_image_upload_hold(im))) {
    u->stage.i = stage_i; u->stage.used = stage_used;
    t->im = NULL; tex_release(id); image_free_now(im); native_reject(); return 0;
  }
  barrier(cmd, im, 0, 1, 0, 1, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
  VkBufferImageCopy copy = { offset, 0, 0, { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, { 0, 0, 0 },
    { (uint32_t)w, (uint32_t)h, 1 } };
  vkCmdCopyBufferToImage(cmd, staging, im->img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &copy);
  barrier(cmd, im, 0, 1, 0, 1, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, im->rest);
  im->level_mask = 1;
  im->in_rest = im->defined = 1;
  /* The loader's completed upload fence is still the handoff boundary. */
  if (native_upload_stream == CINDER_VK_UPLOAD_LOADER && u->stage.n > 4) {
    loader_flush();
    if (native_loader_failed) { cinder_vk_texture_destroy(id); native_reject(); return 0; }
  }
  return id;
}
void cinder_vk_texture_destroy(uint32_t id) {
  if (!id) return;
  vtex *t = tex_get(id);
  if (!t) { native_reject(); return; }
  image_drop(t->im);
  t->im = NULL;
  memset(&t->native_sampler, 0, sizeof t->native_sampler);
  tex_release(id);
}
