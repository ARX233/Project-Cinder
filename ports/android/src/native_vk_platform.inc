/* Native platform ownership over shared Vulkan primitives, not a GL facade.
 * Process-lifetime device; one frame owner and one designated loader. Creation
 * is one-shot: no device-loss recovery or arbitrary table concurrency contract. */
static int native_surface_stale;
static int platform_screen_target(vop *t) {
  memset(t, 0, sizeof *t);
  if (!S.n || !S.img || !S.depth || S.w <= 0 || S.h <= 0) return 0;
  t->kind = OP_PASS; t->screen = 1; t->w = S.w; t->h = S.h;
  t->depth = S.depth; t->color = S.ms ? S.ms : &SCREEN;
  t->resolve = S.ms ? &SCREEN : NULL;
  t->compat = native_compat_id(S.fmt, S.depth->fmt, S.ms ? S.ms->samples : 1, S.ms != NULL);
  return t->compat >= 0;
}
int cinder_vk_platform_create(const char *const *extensions, int count) {
  if (platform_create_attempted || D.dev || count < 0 || (count && !extensions)) return -1;
  for (int i = 0; i < count; ++i) if (!extensions[i]) return -1;
  platform_create_attempted = platform_native_profile = 1;
  if (backend_create(extensions, count, NULL) != 0) return -1;
  if (!D.inst || !D.dev || !D.q || !D.pcache || !F || !dummy2d || !dummycube || !dummy_sampler) {
    logf_("incomplete native device initialization"); abort();
  }
  /* Completing the actual fallback upload establishes descriptor-read ownership;
   * neither image handles nor readiness are synthesized. */
  if (!cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_FRAME) || !cinder_vk_finish()) {
    logf_("native fallback upload unavailable"); abort();
  }
  native_frame_claimed = 0;
  platform_created = 1;
  return 0;
}
VkInstance cinder_vk_platform_instance(void) { return platform_created && D.dev ? D.inst : VK_NULL_HANDLE; }
const char *cinder_vk_device_name(void) { return platform_created && D.dev ? D.props.deviceName : "unavailable"; }
uint32_t cinder_vk_device_api_version(void) { return platform_created && D.dev ? D.props.apiVersion : 0; }
cinder_vk_retirement_mode cinder_vk_platform_retirement_mode(void) {
  if (!platform_created || !D.dev || native_upload_stream != CINDER_VK_UPLOAD_FRAME || !F ||
      !S.n || !S.img || S.w <= 0 || S.h <= 0) return CINDER_VK_RETIREMENT_UNAVAILABLE;
  if (S.headless) return CINDER_VK_RETIREMENT_HEADLESS;
  if (!S.surface || !S.chain || !native_present_wait || native_present_count != S.n ||
      !native_present_fences_ready()) return CINDER_VK_RETIREMENT_UNAVAILABLE;
  return native_present_fences_enabled() ? native_retirement.enabled_device : CINDER_VK_RETIREMENT_IDLE_FALLBACK;
}
void cinder_vk_platform_release_surface(void) {
  if (!platform_created || !D.dev || native_upload_stream != CINDER_VK_UPLOAD_FRAME || !F) { native_reject(); return; }
  native_frame_claimed = 0;
  /* An acquired semaphore must be consumed before that frame slot is reused,
   * including a pause/replacement before any screen draw was recorded. */
  if (S.acquired) flush_wait();
  /* screen_free first waits all pending negotiated PRESENT fences before
   * destroying any WSI object. Without the optional feature, retain the R7
   * idle fallback without claiming explicit present-fence authority. */
  backend_release_surface();
  native_present_fences_destroy();
  for (uint32_t i = 0; i < native_present_count; ++i)
    if (native_present_wait[i]) vkDestroySemaphore(D.dev, native_present_wait[i], NULL);
  free(native_present_wait); native_present_wait = NULL; native_present_count = 0;
  S.w = S.h = 0; S.headless = 0; S.cur = 0;
  memset(&SCREEN, 0, sizeof SCREEN);
  S_waited = S_out_of_date = native_surface_stale = 0;
}
int cinder_vk_platform_surface(VkSurfaceKHR surface, int width, int height) {
  /* A fresh non-null input is consumed even on rejection. Re-submitting the
   * already transferred handle is invalid and must not destroy live ownership. */
  if (surface && surface == S.surface) { native_reject(); return -1; }
  if (!platform_created || !D.dev || native_upload_stream != CINDER_VK_UPLOAD_FRAME || !F) {
    if (surface && D.inst) vkDestroySurfaceKHR(D.inst, surface, NULL);
    native_reject(); return -1;
  }
  cinder_vk_platform_release_surface();
  if (width <= 0 || height <= 0 || (uint32_t)width > D.props.limits.maxImageDimension2D ||
      (uint32_t)height > D.props.limits.maxImageDimension2D || (surface && !D.swapchain_ext)) {
    if (surface) vkDestroySurfaceKHR(D.inst, surface, NULL);
    native_reject(); return -1;
  }
  if (backend_surface(surface, width, height, 1, platform_screen_target) != 0) {
    /* backend_surface takes ownership before its first fallible Vulkan query. */
    cinder_vk_platform_release_surface();
    native_reject(); return -1;
  }
  if (!S.headless) {
    native_present_wait = xcalloc(S.n, sizeof *native_present_wait);
    native_present_count = S.n;
    VkSemaphoreCreateInfo ci = { VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO };
    for (uint32_t i = 0; i < native_present_count; ++i) {
      VkSemaphore semaphore = VK_NULL_HANDLE;
      if (vkCreateSemaphore(D.dev, &ci, NULL, &semaphore) != VK_SUCCESS || !semaphore) {
        cinder_vk_platform_release_surface(); native_reject(); return -1;
      }
      native_present_wait[i] = semaphore;
    }
    if (!native_present_fences_create(S.n)) { cinder_vk_platform_release_surface(); native_reject(); return -1; }
  }
  return 0;
}
int cinder_vk_platform_frame_ready(void) {
  if (native_surface_stale) return 0;
  if (!platform_created || !D.dev || native_upload_stream != CINDER_VK_UPLOAD_FRAME || !F ||
      !S.img || !S.n || !S.depth || S.w <= 0 || S.h <= 0 ||
      (!S.headless && (!S.surface || !S.chain || !native_present_wait || native_present_count != S.n || !native_present_fences_ready())) || cinder_vk_error_pending()) return 0;
  if (!acquire()) return 0; /* actual acquire, before the application renders */
  native_frame_claimed = 1;
  return 1;
}
int cinder_vk_platform_surface_stale(void) {
  return platform_created && D.dev && native_upload_stream == CINDER_VK_UPLOAD_FRAME && !cinder_vk_error_pending() && (S_out_of_date || native_surface_stale);
}
int cinder_vk_platform_present(void) {
  if (!platform_created || !D.dev || native_upload_stream != CINDER_VK_UPLOAD_FRAME || !F ||
      !native_frame_claimed || !S.acquired || !S.n || !S.img || S.w <= 0 || S.h <= 0 ||
      (!S.headless && (!S.surface || !S.chain || !native_present_wait || native_present_count != S.n || !native_present_fences_ready())) || cinder_vk_error_pending()) { native_reject(); return -1; }
  native_frame_claimed = 0; /* exactly one presentation per successful claim */
  int result = backend_present();
  if (result) native_surface_stale = 1;
  return result;
}
void cinder_vk_platform_pipeline_cache_file(const char *path) {
  if (!platform_created || !D.dev || native_upload_stream != CINDER_VK_UPLOAD_FRAME || !path || !path[0]) { native_reject(); return; }
  pthread_mutex_lock(&D.plock);
  backend_pipeline_cache_file(path);
  pthread_mutex_unlock(&D.plock);
}
void cinder_vk_platform_pipeline_cache_save(void) {
  if (!platform_created || !D.dev || native_upload_stream != CINDER_VK_UPLOAD_FRAME) { native_reject(); return; }
  pthread_mutex_lock(&D.plock);
  backend_pipeline_cache_save();
  pthread_mutex_unlock(&D.plock);
}
