/* Optional native WSI resource-retirement fences. Vulkan 1.0 stays the app
 * contract: Features2 is called only via the enabled KHR instance extension.
 * Khronos registry aliases the official EXT feature/fence types and sTypes to
 * KHR maintenance1. NDK28 has those EXT declarations, not the newer KHR names;
 * runtime canonical KHR extension strings below do not invent ABI structures.
 * These fences authorize resource retirement, NOT scanout/display completion. */
static int has_ext(const VkExtensionProperties *e, uint32_t n, const char *name);

static const char native_surface_maintenance_khr[] = "VK_KHR_surface_maintenance1";
static const char native_swapchain_maintenance_khr[] = "VK_KHR_swapchain_maintenance1";
enum { NATIVE_INSTANCE_EXT_MAINTENANCE = 1, NATIVE_INSTANCE_KHR_MAINTENANCE = 2 };
static struct {
  unsigned requested_instance, enabled_instance;
  cinder_vk_retirement_mode requested_device, enabled_device;
  const char *reason;
} native_retirement;

typedef enum {
  NATIVE_PRESENT_IDLE,       /* newly created/reset, unsignaled, not associated */
  NATIVE_PRESENT_PENDING,    /* QueuePresent operations are known enqueued */
  NATIVE_PRESENT_UNKNOWN,    /* fatal boundary: never infer completed or free */
  NATIVE_PRESENT_COMPLETE,   /* actual PRESENT fence wait succeeded */
} native_present_fence_state;
typedef struct { VkFence fence; native_present_fence_state state; } native_present_fence;
static native_present_fence *native_present_fences;
static uint32_t native_present_fence_count;

static int native_present_name_enabled(const VkInstanceCreateInfo *info, const char *name) {
  for (uint32_t i = 0; i < info->enabledExtensionCount; ++i)
    if (!strcmp(info->ppEnabledExtensionNames[i], name)) return 1;
  return 0;
}

/* Optional discovery failure disables the optional chain, not required Vulkan.
 * The returned array alone belongs to the caller; original names are borrowed. */
static const char **native_present_instance_prepare(VkInstanceCreateInfo *info) {
  native_retirement.requested_instance = native_retirement.enabled_instance = 0;
  native_retirement.requested_device = native_retirement.enabled_device = CINDER_VK_RETIREMENT_IDLE_FALLBACK;
  native_retirement.reason = "instance dependency chain unavailable";
  if (!native_present_name_enabled(info, VK_KHR_SURFACE_EXTENSION_NAME) || info->enabledExtensionCount > 1024) return NULL;
  uint32_t count = 0;
  VkResult result = vkEnumerateInstanceExtensionProperties(NULL, &count, NULL);
  if (result != VK_SUCCESS || !count || count > 65536) return NULL;
  uint32_t capacity = count;
  VkExtensionProperties *extensions = calloc(count, sizeof *extensions);
  if (!extensions) return NULL;
  result = vkEnumerateInstanceExtensionProperties(NULL, &count, extensions);
  if (result != VK_SUCCESS || !count || count > capacity) { free(extensions); return NULL; }
  unsigned available = 0;
  if (has_ext(extensions, count, VK_KHR_SURFACE_EXTENSION_NAME) &&
      has_ext(extensions, count, VK_KHR_GET_SURFACE_CAPABILITIES_2_EXTENSION_NAME) &&
      has_ext(extensions, count, VK_KHR_GET_PHYSICAL_DEVICE_PROPERTIES_2_EXTENSION_NAME)) {
    if (has_ext(extensions, count, VK_EXT_SURFACE_MAINTENANCE_1_EXTENSION_NAME)) available |= NATIVE_INSTANCE_EXT_MAINTENANCE;
    if (has_ext(extensions, count, native_surface_maintenance_khr)) available |= NATIVE_INSTANCE_KHR_MAINTENANCE;
  }
  free(extensions);
  if (!available) return NULL;
  const char **names = calloc((size_t)info->enabledExtensionCount + 4, sizeof *names);
  if (!names) return NULL;
  uint32_t n = info->enabledExtensionCount;
  if (n) memcpy(names, info->ppEnabledExtensionNames, (size_t)n * sizeof *names);
  const char *extra[4] = { VK_KHR_GET_PHYSICAL_DEVICE_PROPERTIES_2_EXTENSION_NAME,
    VK_KHR_GET_SURFACE_CAPABILITIES_2_EXTENSION_NAME,
    available & NATIVE_INSTANCE_EXT_MAINTENANCE ? VK_EXT_SURFACE_MAINTENANCE_1_EXTENSION_NAME : NULL,
    available & NATIVE_INSTANCE_KHR_MAINTENANCE ? native_surface_maintenance_khr : NULL };
  for (unsigned i = 0; i < 4; ++i) if (extra[i]) {
    uint32_t j = 0;
    while (j < n && strcmp(names[j], extra[i])) ++j;
    if (j == n) names[n++] = extra[i];
  }
  info->enabledExtensionCount = n; info->ppEnabledExtensionNames = names;
  native_retirement.requested_instance = available;
  return names;
}
static void native_present_instance_created(VkResult result) {
  native_retirement.enabled_instance = result == VK_SUCCESS ? native_retirement.requested_instance : 0;
}

static const char *native_present_device_prepare(const VkExtensionProperties *extensions, uint32_t count,
                                                VkPhysicalDeviceSwapchainMaintenance1FeaturesEXT *feature) {
  native_retirement.requested_device = CINDER_VK_RETIREMENT_IDLE_FALLBACK;
  native_retirement.reason = "matching device maintenance1 extension unavailable";
  const char *name = NULL;
  cinder_vk_retirement_mode mode = CINDER_VK_RETIREMENT_IDLE_FALLBACK;
  if (!D.swapchain_ext || !native_retirement.enabled_instance) return NULL;
  if ((native_retirement.enabled_instance & NATIVE_INSTANCE_EXT_MAINTENANCE) &&
      has_ext(extensions, count, VK_EXT_SWAPCHAIN_MAINTENANCE_1_EXTENSION_NAME)) {
    name = VK_EXT_SWAPCHAIN_MAINTENANCE_1_EXTENSION_NAME; mode = CINDER_VK_RETIREMENT_EXT_PRESENT_FENCE;
  } else if ((native_retirement.enabled_instance & NATIVE_INSTANCE_KHR_MAINTENANCE) &&
             has_ext(extensions, count, native_swapchain_maintenance_khr)) {
    name = native_swapchain_maintenance_khr; mode = CINDER_VK_RETIREMENT_KHR_PRESENT_FENCE;
  }
  if (!name) return NULL;
  PFN_vkGetPhysicalDeviceFeatures2KHR get_features = (PFN_vkGetPhysicalDeviceFeatures2KHR)
    vkGetInstanceProcAddr(D.inst, "vkGetPhysicalDeviceFeatures2KHR");
  if (!get_features) { native_retirement.reason = "enabled Properties2 KHR entrypoint unavailable"; return NULL; }
  *feature = (VkPhysicalDeviceSwapchainMaintenance1FeaturesEXT){ VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SWAPCHAIN_MAINTENANCE_1_FEATURES_EXT };
  VkPhysicalDeviceFeatures2KHR features = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2_KHR };
  features.pNext = feature;
  get_features(D.pd, &features);
  if (feature->swapchainMaintenance1 != VK_TRUE) {
    feature->swapchainMaintenance1 = VK_FALSE;
    native_retirement.reason = "swapchainMaintenance1 feature false";
    return NULL;
  }
  native_retirement.requested_device = mode;
  return name;
}
static void native_present_device_created(VkResult result) {
  native_retirement.enabled_device = result == VK_SUCCESS ? native_retirement.requested_device : CINDER_VK_RETIREMENT_IDLE_FALLBACK;
  if (result != VK_SUCCESS) return; /* advertised-create failure is unavailable, not a second trial */
  if (native_retirement.enabled_device == CINDER_VK_RETIREMENT_EXT_PRESENT_FENCE)
    logf_("native WSI resource retirement: EXT present fences enabled (not display completion)");
  else if (native_retirement.enabled_device == CINDER_VK_RETIREMENT_KHR_PRESENT_FENCE)
    logf_("native WSI resource retirement: KHR present fences enabled (official EXT ABI aliases; not display completion)");
  else logf_("native WSI resource retirement: per-image semaphore/idle fallback, no explicit present-fence authority (%s)",
             native_retirement.reason ? native_retirement.reason : "optional feature unavailable");
}
static int native_present_fences_enabled(void) {
  return native_retirement.enabled_device == CINDER_VK_RETIREMENT_EXT_PRESENT_FENCE ||
         native_retirement.enabled_device == CINDER_VK_RETIREMENT_KHR_PRESENT_FENCE;
}
static int native_present_fences_create(uint32_t count) {
  if (!native_present_fences_enabled()) return 1;
  if (!count || native_present_fences || native_present_fence_count) return 0;
  native_present_fences = calloc(count, sizeof *native_present_fences);
  if (!native_present_fences) return 0;
  native_present_fence_count = count;
  VkFenceCreateInfo info = { VK_STRUCTURE_TYPE_FENCE_CREATE_INFO }; /* unsignaled */
  for (uint32_t i = 0; i < count; ++i) {
    VkFence fence = VK_NULL_HANDLE;
    if (vkCreateFence(D.dev, &info, NULL, &fence) != VK_SUCCESS || !fence) return 0;
    native_present_fences[i].fence = fence;
  }
  return 1;
}
static int native_present_fences_ready(void) {
  if (S.headless || !native_present_fences_enabled()) return 1;
  if (!native_present_fences || native_present_fence_count != S.n) return 0;
  for (uint32_t i = 0; i < native_present_fence_count; ++i)
    if (!native_present_fences[i].fence || native_present_fences[i].state == NATIVE_PRESENT_UNKNOWN) return 0;
  return 1;
}
static void native_present_fence_wait(uint32_t image, int reuse) {
  if (!native_present_fences || image >= native_present_fence_count) { logf_("missing native present-fence owner"); abort(); }
  native_present_fence *slot = &native_present_fences[image];
  if (slot->state == NATIVE_PRESENT_UNKNOWN) { logf_("unknown native presentation ownership"); abort(); }
  if (slot->state == NATIVE_PRESENT_PENDING) {
    if (!slot->fence || vkWaitForFences(D.dev, 1, &slot->fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS) {
      logf_("native PRESENT-fence wait unavailable"); abort();
    }
    slot->state = NATIVE_PRESENT_COMPLETE;
  }
  if (reuse && slot->state == NATIVE_PRESENT_COMPLETE) {
    if (vkResetFences(D.dev, 1, &slot->fence) != VK_SUCCESS) { logf_("native PRESENT-fence reset unavailable"); abort(); }
    slot->state = NATIVE_PRESENT_IDLE;
  }
}
static void native_present_image_reuse(uint32_t image) {
  if (platform_native_profile && native_present_fences_enabled() && !S.headless) native_present_fence_wait(image, 1);
}
static void native_present_retire_all(void) {
  if (!platform_native_profile || !native_present_fences_enabled()) return;
  if (!native_present_fences && !native_present_fence_count) return; /* new/failed constructor, never presented */
  for (uint32_t i = 0; i < native_present_fence_count; ++i) native_present_fence_wait(i, 0);
}
static void native_present_fences_destroy(void) {
  for (uint32_t i = 0; i < native_present_fence_count; ++i)
    if (native_present_fences[i].state == NATIVE_PRESENT_PENDING || native_present_fences[i].state == NATIVE_PRESENT_UNKNOWN) {
      logf_("cannot destroy unretired native present fence"); abort();
    }
  for (uint32_t i = 0; i < native_present_fence_count; ++i)
    if (native_present_fences[i].fence) vkDestroyFence(D.dev, native_present_fences[i].fence, NULL);
  free(native_present_fences); native_present_fences = NULL; native_present_fence_count = 0;
}
static int native_present_attach(VkPresentInfoKHR *present, VkSwapchainPresentFenceInfoEXT *info, VkResult *result) {
  if (!platform_native_profile || !native_present_fences_enabled() || S.headless) return 0;
  if (!native_present_fences_ready() || S.cur >= native_present_fence_count ||
      native_present_fences[S.cur].state != NATIVE_PRESENT_IDLE) { logf_("native present fence not reusable"); abort(); }
  *result = (VkResult)INT32_MIN; /* every non-NULL pResults entry must be written */
  *info = (VkSwapchainPresentFenceInfoEXT){ VK_STRUCTURE_TYPE_SWAPCHAIN_PRESENT_FENCE_INFO_EXT };
  info->pNext = present->pNext; info->swapchainCount = 1; info->pFences = &native_present_fences[S.cur].fence;
  present->pNext = info; present->pResults = result;
  return 1;
}
static int native_present_was_enqueued(VkResult result) {
  return result == VK_SUCCESS || result == VK_SUBOPTIMAL_KHR ||
         result == VK_ERROR_OUT_OF_DATE_KHR || result == VK_ERROR_SURFACE_LOST_KHR;
}
static void native_present_result(VkResult overall, VkResult per_swapchain) {
  native_present_fence *slot = &native_present_fences[S.cur];
  /* OOM explicitly leaves synchronization/resources unaffected. Device loss or
   * an incoherent/missing per-result has unknown ownership and cannot be freed.
   * OUT_OF_DATE and SURFACE_LOST are still enqueued, including semaphore waits. */
  if (overall == VK_ERROR_OUT_OF_HOST_MEMORY || overall == VK_ERROR_OUT_OF_DEVICE_MEMORY) {
    logf_("native presentation enqueue unavailable"); abort();
  }
  if (!native_present_was_enqueued(overall) || per_swapchain != overall) {
    slot->state = NATIVE_PRESENT_UNKNOWN;
    logf_("native presentation ownership unknown: %d / %d", overall, per_swapchain); abort();
  }
  slot->state = NATIVE_PRESENT_PENDING;
}
