/* Explicit Vulkan commands: no GL bindings, VAO, uniform shadow or state queries.
 * Resource handles share the proven allocator/retirement engine with vkgl while
 * callers migrate. Mixed native/compatibility coverage is deliberately reported. */
#ifndef CINDER_NATIVE_VK_H
#define CINDER_NATIVE_VK_H
#include <stddef.h>
#include <stdint.h>
#include <vulkan/vulkan.h>
#define CINDER_VK_ATTRIBUTES 8
#define CINDER_VK_SAMPLERS 8
#define CINDER_VK_UNIFORM_BYTES 4096

/* Process-lifetime native device/platform. No GL context or compatibility setup.
 * One frame owner; loader selects CINDER_VK_UPLOAD_LOADER explicitly below.
 * create: 0 success, -1 unavailable; no retry/device-loss recovery contract.
 * Deep device/frame initialization and main submission failures remain fatal. */
int cinder_vk_platform_create(const char *const *extensions, int count);
VkInstance cinder_vk_platform_instance(void);
const char *cinder_vk_device_name(void); /* "unavailable" before successful create */
uint32_t cinder_vk_device_api_version(void); /* 0 before successful create */
/* Active surface resource-retirement authority, not display/scanout completion.
 * Optional maintenance1 is negotiated with its complete Vulkan-1.0 dependency
 * chain. Unsupported devices keep per-image semaphores/idle fallback; no retry
 * or explicit presentation-fence authority is implied by that fallback. */
typedef enum {
  CINDER_VK_RETIREMENT_UNAVAILABLE,
  CINDER_VK_RETIREMENT_IDLE_FALLBACK,
  CINDER_VK_RETIREMENT_EXT_PRESENT_FENCE,
  CINDER_VK_RETIREMENT_KHR_PRESENT_FENCE,
  CINDER_VK_RETIREMENT_HEADLESS,
} cinder_vk_retirement_mode;
cinder_vk_retirement_mode cinder_vk_platform_retirement_mode(void);
/* surface CONSUMES a fresh VkSurfaceKHR from platform_instance on every outcome,
 * including rejection; callers MUST NOT destroy/reuse it afterward. Re-submitting
 * the currently owned handle rejects without destroying it. NULL requests
 * a real headless image, not a window. Zero/minimized dimensions are unavailable.
 * Old surface/swapchain is released; failure clears native extent/readiness. */
int cinder_vk_platform_surface(VkSurfaceKHR surface, int width, int height);
void cinder_vk_platform_release_surface(void);
/* Acquire/claim before app rendering; 0 means do not render. Repeated readiness
 * queries preserve one claim. Present consumes it: 0 success, 1 recreate, -1
 * unavailable/surface loss. Missing claim/device/frame/surface rejects safely. */
int cinder_vk_platform_frame_ready(void);
/* Only observed WSI out-of-date/surface-loss requires reconstruction. Pending
 * loader/epoch or missing frame/device admission is not recoverable by rebuild. */
int cinder_vk_platform_surface_stale(void);
int cinder_vk_platform_present(void);
void cinder_vk_platform_pipeline_cache_file(const char *path);
void cinder_vk_platform_pipeline_cache_save(void);

typedef struct {
  VkFormat format; /* UNDEFINED = constant attribute supplied in value */
  uint32_t stride, buffer; /* buffer 0 = bounded CPU span, copied at submission */
  size_t offset;
  const void *data;
  size_t bytes;
  float value[4];
} cinder_vk_attribute;

typedef struct {
  VkPrimitiveTopology topology;
  VkBool32 blend;
  VkBlendFactor src_blend, dst_blend;
  VkBlendOp blend_op;
  VkColorComponentFlags color_mask;
  VkBool32 depth_test, depth_write;
  VkCompareOp depth_compare;
  VkCullModeFlags cull;
  /* Assets use bottom-left UV/clip coordinates. Target-origin transformation
   * is explicit in the executor, not taken from a GL context. */
  VkFrontFace asset_front;
  VkBool32 stencil;
  VkCompareOp stencil_compare;
  VkStencilOp stencil_fail, depth_fail, depth_pass;
  uint32_t stencil_compare_mask, stencil_write_mask;
} cinder_vk_pipeline;

/* Optional explicit sampler state. use_state=0 temporarily uses the immutable
 * texture resource's upload defaults during resource migration; it never reads
 * a GL texture unit/binding. use_state=1 fully specifies filtering/addressing. */
typedef struct {
  VkBool32 use_state, mipmaps;
  VkFilter min_filter, mag_filter;
  VkSamplerMipmapMode mipmap_mode;
  VkSamplerAddressMode address_u, address_v;
  float anisotropy;
} cinder_vk_sampler;

typedef struct {
  uint32_t program, target; /* target 0 = swapchain attachment set */
  int viewport[4], scissor[4]; /* asset coordinates, not a GL viewport snapshot */
  uint32_t stencil_reference;
  cinder_vk_pipeline pipeline;
  cinder_vk_attribute attributes[CINDER_VK_ATTRIBUTES];
  uint32_t textures[CINDER_VK_SAMPLERS]; /* reflected binding 1..8 */
  cinder_vk_sampler samplers[CINDER_VK_SAMPLERS];
  unsigned char uniforms[CINDER_VK_UNIFORM_BYTES];
  uint32_t uniform_bytes, count, first;
  VkBool32 indexed, warm_only;
  VkIndexType index_type;
  uint32_t index_buffer;
  size_t index_offset;
  const void *indices;
  size_t index_bytes;
} cinder_vk_draw;

/* Deterministic defaults; never a snapshot of GL state. */
int cinder_vk_draw_init(cinder_vk_draw *draw, uint32_t program, uint32_t target, int width, int height);
/* Missing optional uniform/sampler = success, invalid sizes/types = rejection.
 * These functions write only caller-owned packet bytes. */
int cinder_vk_uniform(cinder_vk_draw *draw, const char *name, const void *value, size_t bytes);
int cinder_vk_texture(cinder_vk_draw *draw, const char *name, uint32_t texture);
int cinder_vk_sampler_state(cinder_vk_draw *draw, const char *name, const cinder_vk_sampler *sampler);
/* Copy sampling defaults from one explicitly named uploaded resource, never
 * from a GL binding/unit. Useful when only addressing differs for this draw. */
int cinder_vk_texture_sampler(uint32_t texture, cinder_vk_sampler *sampler);
/* Validate all spans before recording; 1 = recorded/prewarmed, 0 = rejected. */
int cinder_vk_submit(const cinder_vk_draw *draw);
void cinder_vk_screen_extent(int *width, int *height);
/* Explicit ordered attachment clear. Depth=1 and stencil=0 match this game's
 * fixed clear convention. NULL rect selects the complete target, otherwise
 * coordinates are the same bottom-left asset coordinates as draw scissors.
 * No GL scissor/color/depth/stencil masks or clear color are inherited. */
int cinder_vk_clear(uint32_t target, VkImageAspectFlags aspects, const float color[4], const int rect[4]);
typedef struct {
  uint32_t source, target;
  int source_rect[4], target_rect[4]; /* x0,y0,x1,y1; asset coordinates, flips explicit */
  VkImageAspectFlags aspects;
  VkFilter filter;
} cinder_vk_copy_region;
/* Validate every requested aspect/usage before recording ordered copy/resolve.
 * The destination must be single-sampled with no MSRT resolve attachment;
 * a later MSAA pass would otherwise overwrite a copy into its resolve image. */
/* Complete transfer admission without recording, pass/lifetime/epoch mutation or
 * a current frame. Shared target metadata lookup may populate Vulkan caches. */
int cinder_vk_copy_ready(const cinder_vk_copy_region *region);
int cinder_vk_copy(const cinder_vk_copy_region *region);
/* Advisory invalidation: absent aspects are ignored, and a pass store is not
 * retroactively discarded across a later copy/read. No GL binding is consulted. */
int cinder_vk_discard(uint32_t target, VkImageAspectFlags aspects);
typedef struct {
  int width, height;
  VkFormat color_format, depth_format;
  VkSampleCountFlagBits samples;
  VkBool32 resolves;
  VkImageUsageFlags color_usage, depth_usage, resolve_usage;
} cinder_vk_target_desc;
/* Explicit resource/attachment metadata, never the current GL framebuffer. */
int cinder_vk_target_info(uint32_t target, cinder_vk_target_desc *out);
typedef struct { uint64_t native_draws, compatibility_draws, rejected_packets, native_clears, native_copies, native_discards; } cinder_vk_coverage;
void cinder_vk_get_coverage(cinder_vk_coverage *out);

/* Explicit resource ownership, independent of GL bindings/unpack/current program.
 * Upload queues are per-thread native streams; platform loader entry selects its
 * own stream rather than consulting a compatibility context at each operation. */
typedef enum { CINDER_VK_UPLOAD_FRAME, CINDER_VK_UPLOAD_LOADER } cinder_vk_upload_stream;
int cinder_vk_upload_stream_set(cinder_vk_upload_stream stream);
cinder_vk_upload_stream cinder_vk_upload_stream_get(void);
/* Immutable single-level RGBA8 2D texture; bytes bounds the tightly packed input.
 * A complete non-mip sampler is required. Local validation/image/staging/begin
 * failure returns 0 without publishing. Shared object-table metadata retains
 * the backend's process-fatal OOM policy. Admission is not GPU completion:
 * loader fence completion remains the cross-thread handoff boundary. A failed
 * loader submission/wait retains pending leases and blocks new native uploads;
 * device-fault recovery is not implemented by this resource interface. */
uint32_t cinder_vk_texture_rgba8(int width, int height, const void *pixels, size_t bytes,
                               const cinder_vk_sampler *sampler);
void cinder_vk_texture_destroy(uint32_t texture);
/* Immutable complete sampled images. Asset-format names describe caller-owned
 * bytes, not GL enums/state; device format/swizzle selection is backend-owned.
 * Every level/layer must be present exactly once; zero row_stride means tight.
 * Creation copies all source spans before return and uses the same loader-fence
 * ownership/handoff contract as the RGBA8 convenience API above. */
typedef enum {
  CINDER_VK_TEX_RGBA8, CINDER_VK_TEX_RGB8, CINDER_VK_TEX_RGB565,
  CINDER_VK_TEX_RGBA4444, CINDER_VK_TEX_RGBA5551, CINDER_VK_TEX_L8,
  CINDER_VK_TEX_LA8, CINDER_VK_TEX_A8, CINDER_VK_TEX_ASTC_4x4,
  CINDER_VK_TEX_ASTC_6x6, CINDER_VK_TEX_ASTC_8x8
} cinder_vk_texture_format;
typedef struct {
  uint32_t level, layer;
  const void *data;
  size_t bytes, row_stride;
} cinder_vk_texture_subresource;
typedef struct {
  int width, height, levels, layers;
  cinder_vk_texture_format format;
  cinder_vk_sampler sampler;
  const cinder_vk_texture_subresource *subresources;
  size_t subresource_count;
} cinder_vk_texture_desc;
uint32_t cinder_vk_texture_create(const cinder_vk_texture_desc *texture);
int cinder_vk_texture_format_supported(cinder_vk_texture_format format);
float cinder_vk_anisotropy_limit(void);
/* Complete single-layer uncompressed chain from one level-zero span. Higher
 * levels are generated by real Vulkan linear image blits, never CPU emulation. */
uint32_t cinder_vk_texture_generate_mips(const cinder_vk_texture_desc *base);
/* Explicit native upload role; no compatibility context or sticky GL error.
 * Main flush is deferred to presentation; finish waits the submitted work.
 * Existing shared main-device fatal error policy remains unchanged. */
int cinder_vk_flush(void);
int cinder_vk_finish(void);
/* Saturating native rejection epoch; past errors are not sticky. Unknown loader
 * completion or saturation stays pending/untrusted rather than being drained. */
uint64_t cinder_vk_error_epoch(void);
int cinder_vk_error_pending(void);
/* Immutable target storage: no initial pixel upload, contents undefined until a
 * pass writes them. Explicit transfer/transient capabilities are not inherited.
 * Texture storage requires samples=1/nontransient and a complete nonmip sampler;
 * unsampled attachments ignore sampler. Actual Vulkan capability limits apply. */
typedef enum {
  CINDER_VK_STORAGE_RGBA8, CINDER_VK_STORAGE_RGB565, CINDER_VK_STORAGE_RGBA16F,
  CINDER_VK_STORAGE_R11G11B10F, CINDER_VK_STORAGE_DEPTH16,
  CINDER_VK_STORAGE_DEPTH24_STENCIL8
} cinder_vk_storage_format;
typedef struct {
  int width, height, samples;
  cinder_vk_storage_format format;
  VkBool32 transfer_src, transfer_dst, transient;
  cinder_vk_sampler sampler;
} cinder_vk_storage_desc;
uint32_t cinder_vk_texture_storage(const cinder_vk_storage_desc *storage);
uint32_t cinder_vk_attachment_create(const cinder_vk_storage_desc *storage);
void cinder_vk_attachment_destroy(uint32_t attachment);
typedef enum { CINDER_VK_IMAGE_NONE, CINDER_VK_IMAGE_TEXTURE, CINDER_VK_IMAGE_ATTACHMENT } cinder_vk_image_kind;
typedef struct { cinder_vk_image_kind kind; uint32_t id; } cinder_vk_image_ref;
typedef struct {
  cinder_vk_image_ref color, depth_stencil;
  int resolve_samples; /* 0/1: none; 2/4/8: eagerly allocated implicit MS color */
} cinder_vk_target_create_desc;
/* A target holds image snapshots, not mutable/reusable public object names.
 * Destroying a target releases its holds, never the caller's public resources. */
uint32_t cinder_vk_target_create(const cinder_vk_target_create_desc *target);
void cinder_vk_target_destroy(uint32_t target);
int cinder_vk_target_ready(uint32_t target);
int cinder_vk_sample_limit(void);
/* Generic vertex/index buffer; NULL initial data requests deterministic zeros. */
uint32_t cinder_vk_buffer_create(size_t bytes, const void *data);
int cinder_vk_buffer_update(uint32_t buffer, size_t offset, size_t bytes, const void *data);
void cinder_vk_buffer_destroy(uint32_t buffer);
/* Precompiled catalog only: no runtime compiler, GL program state or inherited
 * uniform shadow. Missing/reflection/module failure returns 0, never a dummy ID. */
uint32_t cinder_vk_program_create(const char *vs, const char *fs, const char **attribs, int n_attribs);
int cinder_vk_program_ready(uint32_t program);
void cinder_vk_program_destroy(uint32_t program);
#endif
