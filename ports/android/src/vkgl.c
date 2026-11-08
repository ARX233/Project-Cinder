/* vkgl: OpenGL ES (the port's part of it) on Vulkan; see vkgl.h.
 *
 * Coordinates: an offscreen framebuffer keeps GL's rows in memory (row 0 the bottom), so a
 * texture rendered to is sampled as in GL, and GL's counter-clockwise front is Vulkan's
 * clockwise there. The screen is shown row 0 at the top: its pipelines turn y over in the
 * vertex shader (vkglsl.py's vkgl_flip_y), its viewport and scissor are counted from the top,
 * and GL's front stays counter-clockwise.
 *
 * Images rest in one layout each between uses (textures SHADER_READ_ONLY, renderbuffers
 * their attachment layout, the swapchain's PRESENT_SRC); a pass or a copy takes them out
 * and puts them back. Something the GPU may still be using is not changed but replaced
 * (a texture or buffer given new contents), and the old freed when its frame is done. */
#define VKGL_IMPL
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>

#include "vkgl.h"
#include "native_vk.h"

#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define FRAMES 2
#define MAX_ATTR 8
#define MAX_UNITS 8
#define MAX_SAMP 8
#define UBO_RANGE 4096
#define CHUNK 256 /* objects in a table's chunk */
#define MAX_CHUNKS 1024

#define GL_RGBA8_ 0x8058
#define GL_RGB8_ 0x8051
#define GL_RGBA16F_ 0x881A
#define GL_R11F_G11F_B10F_ 0x8C3A
#define GL_HALF_FLOAT_ 0x140B
#define GL_DEPTH24_STENCIL8_ 0x88F0
#define GL_DEPTH_STENCIL_ 0x84F9
#define GL_UNSIGNED_INT_24_8_ 0x84FA
#define GL_DEPTH_STENCIL_ATTACHMENT_ 0x821A
#define GL_READ_FRAMEBUFFER_ 0x8CA8
#define GL_DRAW_FRAMEBUFFER_ 0x8CA9
#define GL_MAX_SAMPLES_ 0x8D57
#define GL_TEXTURE_MAX_ANISOTROPY_ 0x84FE
#define GL_MAX_TEXTURE_MAX_ANISOTROPY_ 0x84FF
#define GL_COLOR_ 0x1800
#define GL_DEPTH_ 0x1801
#define GL_STENCIL_ 0x1802

/* Native platform profile does not initialize compatibility contexts. */
static int platform_native_profile, platform_created, platform_create_attempted, native_frame_claimed;

static void logf_(const char *fmt, ...) {
  va_list a;
  va_start(a, fmt);
  fputs("vkgl: ", stderr);
  vfprintf(stderr, fmt, a);
  fputc('\n', stderr);
  va_end(a);
}

#define VKCHECK(x)                                                         \
  do {                                                                     \
    VkResult r_ = (x);                                                     \
    if (r_ != VK_SUCCESS) logf_("%s failed: %d (line %d)", #x, r_, __LINE__); \
  } while (0)

/* Native main/device errors cannot be mistaken for completed GPU ownership.
 * Loader submission/wait uses its separate lease-preserving nonfatal policy. */
#define PLATFORM_CHECK(x) do { VkResult result_ = (x); if (result_ != VK_SUCCESS) { \
  logf_("%s failed: %d (line %d)", #x, result_, __LINE__); \
  if (platform_native_profile) abort(); } } while (0)

static void *xcalloc(size_t n, size_t s) {
  void *p = calloc(n ? n : 1, s);
  if (!p) {
    logf_("out of memory");
    abort();
  }
  return p;
}

/* a growable array: (pointer, count, capacity), grown to hold one more */
#define GROW(p, n, cap)                                   \
  do {                                                    \
    if ((n) >= (cap)) {                                   \
      size_t c_ = (cap) ? (size_t)(cap) * 2 : 64;          \
      void *q_ = realloc((p), c_ * sizeof *(p));          \
      if (!q_) {                                          \
        logf_("out of memory");                           \
        abort();                                          \
      }                                                   \
      (p) = q_;                                           \
      (cap) = c_;                                         \
    }                                                     \
  } while (0)

/* ---- the device ---- */

static struct {
  VkInstance inst;
  VkPhysicalDevice pd;
  VkDevice dev;
  VkQueue q;
  uint32_t qfam;
  VkPhysicalDeviceProperties props;
  VkPhysicalDeviceMemoryProperties mp;
  int aniso, astc, swapchain_ext;
  float max_aniso;
  int max_samples;
  pthread_mutex_t lock;  /* the objects' tables, the memory, the dead */
  pthread_mutex_t qlock; /* the queue */
  pthread_mutex_t plock; /* the pipelines' table */
  VkPipelineCache pcache;
  char pcache_path[512];
  /* formats picked for GL's */
  VkFormat f4444, f5551, f11, fd24, fs16;
  VkComponentMapping sw4444, sw5551;
  int conv5551;
  VkFormat vfmt_short3;
  uint32_t lazy_type; /* a lazily allocated memory type, or ~0 */
  char renderer[300], extensions[400];
  _Atomic uint64_t serial; /* main writer; loader retirement/creation also reads it */
  volatile uint64_t done;  /* the last frame the GPU has finished */
  uint32_t uid;            /* for images and programs */
} D = { .lazy_type = ~0u };

/* Images and programs share this sequence. Every writer must be atomic and
 * nonwrapping: a loader image must not roll back a concurrently published
 * program UID and accidentally reuse a cached pipeline's program identity. */
static uint32_t resource_uid_next(void) {
  uint32_t uid = __atomic_load_n(&D.uid, __ATOMIC_RELAXED);
  do {
    if (uid == UINT32_MAX) return 0;
  } while (!__atomic_compare_exchange_n(&D.uid, &uid, uid + 1, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED));
  return uid + 1;
}
static uint64_t done_serial(void) { return __atomic_load_n(&D.done, __ATOMIC_ACQUIRE); }

/* ---- memory: blocks of a type, each its free ranges; buffers and images in blocks of their
 * own (no granularity to mind between them) ---- */

typedef struct {
  VkDeviceMemory mem;
  VkDeviceSize size;
  uint8_t *map;
  uint32_t type;
  int image, dedicated, live;
  struct range { VkDeviceSize off, size; } *free;
  size_t n_free, cap_free;
} mblock;

typedef struct {
  int block; /* -1 none */
  VkDeviceSize off, size;
} vmem;

static mblock *blocks;
static size_t n_blocks, cap_blocks;
#define BLOCK_SIZE ((VkDeviceSize)32 << 20)

static uint32_t mem_type(uint32_t bits, VkMemoryPropertyFlags want, VkMemoryPropertyFlags pref) {
  for (int pass = 0; pass < 2; ++pass)
    for (uint32_t i = 0; i < D.mp.memoryTypeCount; ++i) {
      VkMemoryPropertyFlags f = D.mp.memoryTypes[i].propertyFlags;
      if (!(bits & (1u << i)) || (f & want) != want) continue;
      if (pass == 0 && (f & pref) != pref) continue;
      return i;
    }
  return ~0u;
}

static int block_new(uint32_t type, VkDeviceSize size, int image, int dedicated) {
  VkMemoryAllocateInfo ai = { VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL, size, type };
  VkDeviceMemory m;
  if (vkAllocateMemory(D.dev, &ai, NULL, &m) != VK_SUCCESS) return -1;
  int k = -1;
  for (size_t i = 0; i < n_blocks; ++i)
    if (!blocks[i].mem) k = (int)i;
  if (k < 0) {
    GROW(blocks, n_blocks, cap_blocks);
    k = (int)n_blocks++;
  }
  mblock *b = &blocks[k];
  memset(b, 0, sizeof *b);
  b->mem = m, b->size = size, b->type = type, b->image = image, b->dedicated = dedicated;
  if ((D.mp.memoryTypes[type].propertyFlags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) &&
      vkMapMemory(D.dev, m, 0, VK_WHOLE_SIZE, 0, (void **)&b->map) != VK_SUCCESS) {
    vkFreeMemory(D.dev, m, NULL);
    memset(b, 0, sizeof *b);
    return -1;
  }
  GROW(b->free, b->n_free, b->cap_free);
  b->free[b->n_free++] = (struct range){ 0, size };
  return k;
}

static int block_take(mblock *b, VkDeviceSize size, VkDeviceSize align, VkDeviceSize *off) {
  for (size_t i = 0; i < b->n_free; ++i) {
    struct range *r = &b->free[i];
    VkDeviceSize o = (r->off + align - 1) / align * align;
    if (o + size > r->off + r->size) continue;
    VkDeviceSize end = r->off + r->size;
    struct range before = { r->off, o - r->off }, after = { o + size, end - (o + size) };
    /* the range becomes what is left before and after */
    if (before.size && after.size) {
      *r = before;
      GROW(b->free, b->n_free, b->cap_free);
      memmove(&b->free[i + 2], &b->free[i + 1], (b->n_free - i - 1) * sizeof *b->free);
      b->free[i + 1] = after;
      b->n_free++;
    } else if (before.size) {
      *r = before;
    } else if (after.size) {
      *r = after;
    } else {
      memmove(&b->free[i], &b->free[i + 1], (b->n_free - i - 1) * sizeof *b->free);
      b->n_free--;
    }
    *off = o;
    b->live++;
    return 1;
  }
  return 0;
}

/* (under D.lock) */
static int mem_alloc(VkMemoryRequirements r, VkMemoryPropertyFlags want, VkMemoryPropertyFlags pref, int image, vmem *out) {
  uint32_t type = mem_type(r.memoryTypeBits, want, pref);
  if (type == ~0u) return -1;
  out->size = r.size;
  if (r.size > BLOCK_SIZE / 4 || (want & VK_MEMORY_PROPERTY_LAZILY_ALLOCATED_BIT)) {
    int k = block_new(type, r.size, image, 1);
    if (k < 0) return -1;
    block_take(&blocks[k], r.size, 1, &out->off);
    out->block = k;
    return 0;
  }
  for (size_t i = 0; i < n_blocks; ++i) {
    mblock *b = &blocks[i];
    if (b->mem && !b->dedicated && b->type == type && b->image == image && block_take(b, r.size, r.alignment, &out->off)) {
      out->block = (int)i;
      return 0;
    }
  }
  int k = block_new(type, BLOCK_SIZE, image, 0);
  if (k < 0) return -1;
  block_take(&blocks[k], r.size, r.alignment, &out->off);
  out->block = k;
  return 0;
}

static void mem_free(vmem *m) {
  if (m->block < 0 || !m->size) return;
  mblock *b = &blocks[m->block];
  m->block = -1;
  if (--b->live == 0 && b->dedicated) {
    vkFreeMemory(D.dev, b->mem, NULL);
    free(b->free);
    memset(b, 0, sizeof *b);
    return;
  }
  /* back into the sorted ranges, joined with its neighbours */
  size_t i = 0;
  while (i < b->n_free && b->free[i].off < m->off) i++;
  GROW(b->free, b->n_free, b->cap_free);
  memmove(&b->free[i + 1], &b->free[i], (b->n_free - i) * sizeof *b->free);
  b->free[i] = (struct range){ m->off, m->size };
  b->n_free++;
  if (i + 1 < b->n_free && b->free[i].off + b->free[i].size == b->free[i + 1].off) {
    b->free[i].size += b->free[i + 1].size;
    memmove(&b->free[i + 1], &b->free[i + 2], (b->n_free - i - 2) * sizeof *b->free);
    b->n_free--;
  }
  if (i > 0 && b->free[i - 1].off + b->free[i - 1].size == b->free[i].off) {
    b->free[i - 1].size += b->free[i].size;
    memmove(&b->free[i], &b->free[i + 1], (b->n_free - i - 1) * sizeof *b->free);
    b->n_free--;
  }
}

static uint8_t *mem_map(const vmem *m) { return blocks[m->block].map ? blocks[m->block].map + m->off : NULL; }

/* ---- buffers' and images' memory ---- */

typedef struct {
  VkBuffer buf;
  vmem mem;
  uint8_t *map;
  VkDeviceSize size;
  uint64_t serial; /* the last frame that used it */
} vbufmem;

/* Recoverable allocation for explicit native ownership. Never publish a partial
 * VkBuffer/backing, including bind/map failures after memory allocation. */
static vbufmem *bufmem_try_new(VkDeviceSize size, VkBufferUsageFlags usage) {
  if (!D.dev) return NULL;
  vbufmem *b = calloc(1, sizeof *b);
  if (!b) return NULL;
  b->mem.block = -1;
  b->size = size ? size : 4;
  VkBufferCreateInfo ci = { VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO };
  ci.size = b->size;
  ci.usage = usage;
  if (vkCreateBuffer(D.dev, &ci, NULL, &b->buf) != VK_SUCCESS) { free(b); return NULL; }
  VkMemoryRequirements r;
  vkGetBufferMemoryRequirements(D.dev, b->buf, &r);
  pthread_mutex_lock(&D.lock);
  int ok = mem_alloc(r, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                     VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, 0, &b->mem);
  pthread_mutex_unlock(&D.lock);
  if (ok != 0) goto fail;
  if (vkBindBufferMemory(D.dev, b->buf, blocks[b->mem.block].mem, b->mem.off) != VK_SUCCESS) goto fail;
  b->map = mem_map(&b->mem);
  if (!b->map) goto fail;
  return b;
fail:
  vkDestroyBuffer(D.dev, b->buf, NULL);
  if (b->mem.block >= 0) {
    pthread_mutex_lock(&D.lock);
    mem_free(&b->mem);
    pthread_mutex_unlock(&D.lock);
  }
  free(b);
  return NULL;
}
static vbufmem *bufmem_new(VkDeviceSize size, VkBufferUsageFlags usage) {
  vbufmem *b = bufmem_try_new(size, usage);
  if (!b) { logf_("no memory for a buffer of %llu", (unsigned long long)size); abort(); }
  return b;
}

static void bufmem_free(vbufmem *b) {
  vkDestroyBuffer(D.dev, b->buf, NULL);
  pthread_mutex_lock(&D.lock);
  mem_free(&b->mem);
  pthread_mutex_unlock(&D.lock);
  free(b);
}

typedef struct vimg {
  VkImage img;
  vmem mem;
  VkImageView view; /* sampled: its levels, depth aspect alone */
  VkImageView att;  /* attachment: level 0 */
  VkFormat fmt;
  VkImageAspectFlags aspect;
  VkImageUsageFlags usage; /* actual create usage, including optional swapchain flags */
  VkComponentMapping swz;
  int w, h, levels, layers, samples;
  int view_levels;     /* the levels the sampled view has */
  uint32_t level_mask; /* the levels given contents */
  VkImageLayout rest;
  int sampled, transient, swapchain;
  int implicit; /* the multisampled one a texture (or the screen) is rendered through: its
                 * samples needed only within the frame */
  int defined; /* its contents kept (at replay) */
  int in_rest; /* in its resting layout (else still undefined: a new attachment, an acquired
                 * swapchain image) */
  uint64_t serial;
  uint32_t uid;
  int native_upload_pending, native_retire_pending; /* D.lock: deferred ownership */
  uint32_t native_target_refs; /* D.lock: strong immutable target snapshots */
} vimg;

static int is_depth(VkFormat f) {
  return f == VK_FORMAT_D16_UNORM || f == VK_FORMAT_D24_UNORM_S8_UINT || f == VK_FORMAT_D32_SFLOAT_S8_UINT ||
         f == VK_FORMAT_D32_SFLOAT || f == VK_FORMAT_D16_UNORM_S8_UINT || f == VK_FORMAT_X8_D24_UNORM_PACK32;
}
static int has_stencil(VkFormat f) {
  return f == VK_FORMAT_D24_UNORM_S8_UINT || f == VK_FORMAT_D32_SFLOAT_S8_UINT || f == VK_FORMAT_D16_UNORM_S8_UINT;
}

#define VKGL_SSAO_DEPTH_USAGE (VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | \
                               VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT)

static const VkComponentMapping SWZ_ID = { VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY,
                                           VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY };

static VkResult view_try(const vimg *im, int sampled, int levels, VkImageView *v) {
  VkImageViewCreateInfo vi = { VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO };
  vi.image = im->img;
  vi.viewType = sampled && im->layers == 6 ? VK_IMAGE_VIEW_TYPE_CUBE : VK_IMAGE_VIEW_TYPE_2D;
  vi.format = im->fmt;
  vi.components = sampled ? im->swz : SWZ_ID;
  vi.subresourceRange.aspectMask = sampled && is_depth(im->fmt) ? VK_IMAGE_ASPECT_DEPTH_BIT : im->aspect;
  vi.subresourceRange.levelCount = (uint32_t)levels;
  vi.subresourceRange.layerCount = sampled ? (uint32_t)im->layers : 1;
  *v = VK_NULL_HANDLE;
  if (platform_native_profile) {
    /* Runtime-error output is undefined, not an owned view to roll back.
     * Publish only success; every try caller still checks result + non-NULL. */
    VkImageView view = VK_NULL_HANDLE;
    VkResult result = vkCreateImageView(D.dev, &vi, NULL, &view);
    if (result == VK_SUCCESS) *v = view;
    return result;
  }
  return vkCreateImageView(D.dev, &vi, NULL, v);
}

static VkImageView view_new(const vimg *im, int sampled, int levels) {
  if (platform_native_profile) {
    VkImageView v = VK_NULL_HANDLE;
    VkResult result = view_try(im, sampled, levels, &v);
    VKCHECK(result);
    /* Live view replacement must not continue with a missing/undefined view.
     * Recoverable constructors use view_try directly, including strict WSI. */
    if (result != VK_SUCCESS || !v) {
      logf_("native live image view unavailable: %d", result);
      abort();
    }
    return v;
  }
  VkImageView v = VK_NULL_HANDLE;
  VKCHECK(view_try(im, sampled, levels, &v));
  return v;
}

/* sampled: a texture (rests SHADER_READ_ONLY); else an attachment (a renderbuffer's, the
 * screen's depth, a multisampled one of a texture's), transient when its samples are
 * never kept */
static vimg *image_new_usage(VkFormat fmt, int w, int h, int levels, int layers, int samples, int sampled, int transient,
                             VkComponentMapping swz, VkImageUsageFlags requested_usage) {
  vimg *im = calloc(1, sizeof *im);
  if (!im) return NULL;
  im->mem.block = -1;
  im->fmt = fmt, im->w = w, im->h = h, im->levels = levels, im->layers = layers, im->samples = samples;
  im->sampled = sampled, im->swz = swz;
  im->aspect = is_depth(fmt) ? VK_IMAGE_ASPECT_DEPTH_BIT | (has_stencil(fmt) ? VK_IMAGE_ASPECT_STENCIL_BIT : 0)
                             : VK_IMAGE_ASPECT_COLOR_BIT;
  int comp = fmt >= VK_FORMAT_BC1_RGB_UNORM_BLOCK && fmt <= VK_FORMAT_ASTC_12x12_SRGB_BLOCK;
  VkImageCreateInfo ci = { VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO };
  ci.flags = layers == 6 ? VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT : 0;
  ci.imageType = VK_IMAGE_TYPE_2D;
  ci.format = fmt;
  ci.extent = (VkExtent3D){ (uint32_t)w, (uint32_t)h, 1 };
  ci.mipLevels = (uint32_t)levels;
  ci.arrayLayers = (uint32_t)layers;
  ci.samples = (VkSampleCountFlagBits)samples;
  ci.tiling = VK_IMAGE_TILING_OPTIMAL;
  VkImageUsageFlags att = is_depth(fmt) ? VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT : VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
  if (sampled) {
    ci.usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    if (!comp && layers == 1) ci.usage |= att;
  } else if (transient && D.lazy_type != ~0u) {
    ci.usage = att | VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT;
  } else {
    ci.usage = att | (samples == 1 ? VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT : 0);
    transient = 0;
  }
  if (requested_usage) {
    ci.usage = requested_usage;
    transient = !!(requested_usage & VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT);
  }
  im->transient = transient;
  im->usage = ci.usage;
  ci.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
  if (vkCreateImage(D.dev, &ci, NULL, &im->img) != VK_SUCCESS || !im->img) {
    logf_("no image %d x %d format %d", w, h, fmt);
    free(im);
    return NULL;
  }
  VkMemoryRequirements r;
  vkGetImageMemoryRequirements(D.dev, im->img, &r);
  pthread_mutex_lock(&D.lock);
  int ok = transient ? mem_alloc(r, VK_MEMORY_PROPERTY_LAZILY_ALLOCATED_BIT, 0, 1, &im->mem) : -1;
  if (ok != 0) ok = mem_alloc(r, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT, 0, 1, &im->mem);
  if (ok != 0) ok = mem_alloc(r, 0, 0, 1, &im->mem);
  im->uid = ok == 0 ? resource_uid_next() : 0;
  pthread_mutex_unlock(&D.lock);
  if (ok != 0) {
    logf_("no memory for an image %d x %d", w, h);
    vkDestroyImage(D.dev, im->img, NULL);
    free(im);
    return NULL;
  }
  if (!im->uid || vkBindImageMemory(D.dev, im->img, blocks[im->mem.block].mem, im->mem.off) != VK_SUCCESS) goto fail;
  im->rest = sampled ? VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL
                     : is_depth(fmt) ? VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL : VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
  if (sampled) {
    im->view_levels = 1;
    if (view_try(im, 1, 1, &im->view) != VK_SUCCESS || !im->view) goto fail;
  }
  if (!comp && layers == 1 && (im->usage & (VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT)) &&
      (view_try(im, 0, 1, &im->att) != VK_SUCCESS || !im->att)) goto fail;
  return im;
fail:
  if (im->view) vkDestroyImageView(D.dev, im->view, NULL);
  if (im->att) vkDestroyImageView(D.dev, im->att, NULL);
  vkDestroyImage(D.dev, im->img, NULL);
  pthread_mutex_lock(&D.lock);
  mem_free(&im->mem);
  pthread_mutex_unlock(&D.lock);
  free(im);
  return NULL;
}

/* Compatibility allocation keeps the previous usage policy exactly. Native
 * sampled resources supply explicit usage instead of inheriting attachment bits. */
static vimg *image_new(VkFormat fmt, int w, int h, int levels, int layers, int samples, int sampled, int transient,
                       VkComponentMapping swz) {
  return image_new_usage(fmt, w, h, levels, layers, samples, sampled, transient, swz, 0);
}

/* ---- the dead: freed once the GPU is past the frame that last used them ---- */

enum { DEAD_IMAGE, DEAD_BUFMEM, DEAD_VIEW, DEAD_FB };
typedef struct {
  int kind;
  void *p;
  uint64_t h;
  uint64_t serial;
} dead_t;
static dead_t *dead;
static size_t n_dead, cap_dead;

static void fb_cache_forget(VkImageView v);

static void dead_add(int kind, void *p, uint64_t h, uint64_t serial) {
  pthread_mutex_lock(&D.lock);
  GROW(dead, n_dead, cap_dead);
  dead[n_dead++] = (dead_t){ kind, p, h, serial };
  pthread_mutex_unlock(&D.lock);
}

static void image_free_now(vimg *im) {
  /* Only unpublished constructor failures or serial/fence-safe retirement reach
   * this point. Cached framebuffers must outlive every in-flight use too. */
  if (im->att) fb_cache_forget(im->att);
  if (im->view) vkDestroyImageView(D.dev, im->view, NULL);
  if (im->att) vkDestroyImageView(D.dev, im->att, NULL);
  if (!im->swapchain) {
    vkDestroyImage(D.dev, im->img, NULL);
    pthread_mutex_lock(&D.lock);
    mem_free(&im->mem);
    pthread_mutex_unlock(&D.lock);
  }
  free(im);
}

/* Pure capability predicate, independently testable with synthetic Vulkan properties. */
static int ssao_depth_properties_ok(int w, int h, VkFormatFeatureFlags features, VkResult result,
                                    const VkImageFormatProperties *p) {
  const VkFormatFeatureFlags required = VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT;
  return w > 0 && h > 0 && (features & required) == required && result == VK_SUCCESS && p &&
         (uint32_t)w <= p->maxExtent.width && (uint32_t)h <= p->maxExtent.height && p->maxExtent.depth >= 1 &&
         p->maxMipLevels >= 1 && p->maxArrayLayers >= 1 && (p->sampleCounts & VK_SAMPLE_COUNT_1_BIT);
}

int vkgl_ssao_depth_supported(int w, int h) {
  if (!D.pd || !D.dev || !D.fd24 || w <= 0 || h <= 0 ||
      (uint32_t)w > D.props.limits.maxFramebufferWidth || (uint32_t)h > D.props.limits.maxFramebufferHeight) return 0;
  VkFormatProperties fp;
  VkImageFormatProperties ip = { 0 };
  vkGetPhysicalDeviceFormatProperties(D.pd, D.fd24, &fp);
  VkResult r = vkGetPhysicalDeviceImageFormatProperties(D.pd, D.fd24, VK_IMAGE_TYPE_2D, VK_IMAGE_TILING_OPTIMAL,
                                                         VKGL_SSAO_DEPTH_USAGE, 0, &ip);
  if (!ssao_depth_properties_ok(w, h, fp.optimalTilingFeatures, r, &ip)) return 0;
  /* A successful probe is not a reservation for later allocations. */
  vimg *im = image_new(D.fd24, w, h, 1, 1, 1, 1, 0, SWZ_ID);
  if (!im) return 0;
  image_free_now(im);
  return 1;
}

/* Native loader commands are not covered by the main frame's serial until their
 * own fence has completed. Pin images even if their public texture is deleted
 * before the platform loader flush/handoff. All lease flags/list use D.lock. */
static vimg **native_upload_images;
static size_t n_native_upload_images, cap_native_upload_images;
static _Atomic int native_loader_failed; /* unknown completion: atomic diagnostic visibility across owners */
static int native_image_upload_hold(vimg *im) {
  pthread_mutex_lock(&D.lock);
  if (!im->native_upload_pending) {
    if (n_native_upload_images == cap_native_upload_images) {
      size_t cap = cap_native_upload_images ? cap_native_upload_images * 2 : 16;
      if (cap < cap_native_upload_images || cap > SIZE_MAX / sizeof *native_upload_images) {
        pthread_mutex_unlock(&D.lock); return 0;
      }
      vimg **images = realloc(native_upload_images, cap * sizeof *images);
      if (!images) { pthread_mutex_unlock(&D.lock); return 0; }
      native_upload_images = images; cap_native_upload_images = cap;
    }
    native_upload_images[n_native_upload_images++] = im;
    im->native_upload_pending = 1;
  }
  pthread_mutex_unlock(&D.lock);
  return 1;
}
/* (the image's framebuffers go now: no pass is made with them after this) */
static void image_drop(vimg *im) {
  if (!im) return;
  pthread_mutex_lock(&D.lock);
  if (im->native_upload_pending || im->native_target_refs) {
    im->native_retire_pending = 1;
    pthread_mutex_unlock(&D.lock);
    return;
  }
  pthread_mutex_unlock(&D.lock);
  uint64_t s = im->serial > D.serial ? im->serial : D.serial;
  dead_add(DEAD_IMAGE, im, 0, s);
}
/* Strong target snapshots keep an image alive even after its public resource
 * handle is removed/reused. Table access and recording still obey the port's
 * designated-owner/loader-fence handoff protocol, not arbitrary concurrent use. */
static int native_target_image_hold(vimg *im) {
  if (!im) return 0;
  pthread_mutex_lock(&D.lock);
  int ok = !im->native_upload_pending && !im->native_retire_pending && im->native_target_refs < UINT32_MAX;
  if (ok) ++im->native_target_refs;
  pthread_mutex_unlock(&D.lock);
  return ok;
}
static void native_target_image_release(vimg *im) {
  if (!im) return;
  pthread_mutex_lock(&D.lock);
  if (!im->native_target_refs) {
    pthread_mutex_unlock(&D.lock);
    logf_("native target image reference underflow");
    return;
  }
  --im->native_target_refs;
  int retire = !im->native_target_refs && !im->native_upload_pending && im->native_retire_pending;
  pthread_mutex_unlock(&D.lock);
  if (retire) image_drop(im);
}
/* Only call after a successful wait for LOADER_UP's submitted upload fence. The
 * single loader owner cannot append new commands while completing this batch. */
static void native_image_upload_complete(void) {
  for (;;) {
    pthread_mutex_lock(&D.lock);
    if (!n_native_upload_images) { pthread_mutex_unlock(&D.lock); return; }
    vimg *im = native_upload_images[--n_native_upload_images];
    im->native_upload_pending = 0;
    int retire = im->native_retire_pending && !im->native_target_refs;
    pthread_mutex_unlock(&D.lock);
    /* Do not touch a nonretired image after unlocking: its owner can now drop
     * it and a concurrently advancing main fence may free it. */
    if (retire) image_drop(im);
  }
}

static void bufmem_drop(vbufmem *b) {
  if (b) dead_add(DEAD_BUFMEM, b, 0, b->serial > D.serial ? b->serial : D.serial);
}

static void dead_free(uint64_t upto) {
  size_t k = 0;
  for (;;) {
    dead_t d = { -1 };
    pthread_mutex_lock(&D.lock);
    while (k < n_dead && dead[k].serial > upto) k++;
    if (k < n_dead) {
      d = dead[k];
      dead[k] = dead[--n_dead];
    }
    pthread_mutex_unlock(&D.lock);
    if (d.kind < 0) break;
    if (d.kind == DEAD_IMAGE) image_free_now(d.p);
    else if (d.kind == DEAD_BUFMEM) bufmem_free(d.p);
    else if (d.kind == DEAD_VIEW) vkDestroyImageView(D.dev, (VkImageView)(uintptr_t)d.h, NULL);
    else if (d.kind == DEAD_FB) vkDestroyFramebuffer(D.dev, (VkFramebuffer)(uintptr_t)d.h, NULL);
  }
}

/* ---- the GL objects: tables of chunks that never move (both threads look things up) ---- */

#define TABLE(T, name)                                                       \
  static T *name##_chunks[MAX_CHUNKS];                                       \
  static GLuint name##_next = 1;                                             \
  static GLuint *name##_free;                                                \
  static size_t name##_nfree, name##_capfree;                                \
  static T *name##_get(GLuint id) {                                          \
    if (!id || id >= (GLuint)CHUNK * MAX_CHUNKS) return NULL;                \
    T *c = name##_chunks[id / CHUNK];                                        \
    if (!c || !c[id % CHUNK].used) return NULL;                              \
    return &c[id % CHUNK];                                                   \
  }                                                                          \
  static GLuint name##_gen(void) {                                           \
    pthread_mutex_lock(&D.lock);                                             \
    GLuint id = name##_nfree ? name##_free[--name##_nfree] : name##_next++;  \
    if (id >= (GLuint)CHUNK * MAX_CHUNKS) {                                  \
      pthread_mutex_unlock(&D.lock);                                         \
      logf_("too many " #name);                                              \
      return 0;                                                              \
    }                                                                        \
    if (!name##_chunks[id / CHUNK]) name##_chunks[id / CHUNK] = xcalloc(CHUNK, sizeof(T)); \
    T *o = &name##_chunks[id / CHUNK][id % CHUNK];                           \
    memset(o, 0, sizeof *o);                                                 \
    o->used = 1;                                                             \
    pthread_mutex_unlock(&D.lock);                                           \
    return id;                                                               \
  }                                                                          \
  static void name##_release(GLuint id) {                                    \
    T *o = name##_get(id);                                                   \
    if (!o) return;                                                          \
    pthread_mutex_lock(&D.lock);                                             \
    o->used = 0;                                                             \
    GROW(name##_free, name##_nfree, name##_capfree);                         \
    name##_free[name##_nfree++] = id;                                        \
    pthread_mutex_unlock(&D.lock);                                           \
  }

typedef struct {
  int used;
  GLenum target; /* 0 until bound */
  vimg *im;
  GLenum min, mag, wrap_s, wrap_t;
  float aniso;
  cinder_vk_sampler native_sampler; /* explicit defaults for native-owned textures */
} vtex;
TABLE(vtex, tex)

typedef struct {
  int used;
  vbufmem *m;
} vbuf;
TABLE(vbuf, buf)

typedef struct {
  int used;
  vimg *im;
} vrbo;
TABLE(vrbo, rbo)

typedef struct {
  int kind; /* 0 none, 1 texture, 2 renderbuffer */
  GLuint name;
  int samples; /* a texture's multisampled (EXT_multisampled_render_to_texture) */
} vatt;
typedef struct {
  int used;
  vatt color, depth, stencil;
  vimg *ms; /* the multisampled image a texture is rendered through */
  int native; /* immutable strong image snapshots, never public-name lookup */
  vimg *native_color, *native_depth;
} vfbo;
TABLE(vfbo, fbo)

typedef struct {
  int enabled;
  GLint size;
  GLenum type;
  GLboolean norm;
  GLsizei stride;
  GLuint buf;
  const void *ptr;
} vattr;
typedef struct {
  int used;
  vattr a[MAX_ATTR];
  GLuint ebo;
} vvao;
TABLE(vvao, vao)

typedef struct {
  char name[48];
  int code; /* vkglsl.py's: 1 float .. 4 vec4, 5 int, 6 mat4, 7 sampler2D, 8 samplerCube */
  int off;  /* in the block; a sampler's binding */
} vuni;
typedef struct {
  int used;
  uint32_t uid;
  VkShaderModule vs, fs;
  VkShaderModule vs2, fs2; /* (all highp: vkgl_spv's) */
  int alt;                 /* the pipelines from vs2, fs2 (the first pair failed) */
  int n_uni;
  vuni *uni;
  int block; /* the uniform block's size */
  uint8_t *shadow;
  int dirty;
  uint64_t ubo_serial; /* the frame its block was last put in the ring */
  VkBuffer ubo_buf;
  uint32_t ubo_off;
  int n_samp;
  int samp_cube[MAX_SAMP];
  int samp_unit[MAX_SAMP];
  uint32_t inputs;
  char key[17];
} vprog;
TABLE(vprog, prog)

/* Module existence only: pipeline creation can still fail later. */
int vkgl_program_usable(GLuint id) {
  vprog *p = prog_get(id);
  return p && p->vs && p->fs && p->shadow;
}

/* ---- a thread's GL state (the game's, the loading thread's) ---- */

typedef struct {
  int loader;
  GLenum err;
  GLuint prog, array_buf, rbo, draw_fb, read_fb, vao;
  int unit;
  GLuint tex2d[MAX_UNITS], texcube[MAX_UNITS];
  vvao vao0;
  float generic[MAX_ATTR][4];
  int blend, depth_test, cull, scissor_test, stencil_test;
  GLenum bsrc, bdst, beq, dfunc, cull_face, front;
  int cmask, depth_write;
  GLenum sfunc, sfail, szfail, szpass;
  GLint sref;
  GLuint smask, swmask;
  GLint vp[4], sc[4];
  float clear[4];
  int unpack, pack;
} vctx;

static void ctx_init(vctx *c, int loader) {
  memset(c, 0, sizeof *c);
  c->loader = loader;
  c->vao0.used = 1;
  for (int i = 0; i < MAX_ATTR; ++i) c->generic[i][3] = 1.0f;
  c->bsrc = GL_ONE, c->bdst = GL_ZERO, c->beq = GL_FUNC_ADD;
  c->dfunc = GL_LESS, c->cull_face = GL_BACK, c->front = GL_CCW;
  c->cmask = 15, c->depth_write = 1;
  c->sfunc = GL_ALWAYS, c->sfail = c->szfail = c->szpass = GL_KEEP;
  c->smask = c->swmask = 0xffffffffu;
  c->unpack = c->pack = 4;
}

/* Outside vctx: preview snapshots restore vctx and must not roll back the epoch. */
static uint64_t main_error_epoch, loader_error_epoch;
static vctx main_ctx, loader_ctx;
static __thread vctx *cur_tls;
static vctx *ctx(void) { return cur_tls ? cur_tls : &main_ctx; }

static void set_err(GLenum e) {
  vctx *c = ctx();
  uint64_t *epoch = c == &main_ctx ? &main_error_epoch : c == &loader_ctx ? &loader_error_epoch : NULL;
  if (epoch) {
    uint64_t old = __atomic_load_n(epoch, __ATOMIC_RELAXED);
    while (old != UINT64_MAX && !__atomic_compare_exchange_n(epoch, &old, old + 1, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {}
  }
  /* Unknown contexts remain untrusted; vkgl_error_epoch returns UINT64_MAX for them. */
  if (!c->err) c->err = e;
}

static vvao *cur_vao(vctx *c) {
  vvao *v = c->vao ? vao_get(c->vao) : NULL;
  return v ? v : &c->vao0;
}

/* A scoped snapshot for the menu meter preview. Vulkan's GL emulation does not
 * expose GLES state queries, so snapshot its actual context/VAO/program shadow. */
typedef struct {
  vctx state; vvao vao; GLuint program; unsigned char *shadow; int size;
  int samplers[MAX_SAMP];
} vkgl_preview_snapshot;
void *vkgl_preview_save(GLuint program) {
  vprog *p = prog_get(program);
  if (!p || !p->shadow || p->block < 0) return NULL;
  vkgl_preview_snapshot *s = calloc(1, sizeof *s);
  if (!s) return NULL;
  s->shadow = malloc(p->block ? (size_t)p->block : 1);
  if (!s->shadow) { free(s); return NULL; }
  s->state = *ctx(); s->vao = *cur_vao(ctx()); s->program = program; s->size = p->block;
  memcpy(s->shadow, p->shadow, (size_t)s->size);
  memcpy(s->samplers, p->samp_unit, sizeof s->samplers);
  return s;
}
void vkgl_preview_restore(void *snapshot) {
  vkgl_preview_snapshot *s = snapshot;
  if (!s) return;
  vprog *p = prog_get(s->program);
  if (p && p->shadow && p->block == s->size) {
    memcpy(p->shadow, s->shadow, (size_t)s->size);
    memcpy(p->samp_unit, s->samplers, sizeof s->samplers); p->dirty = 1;
  }
  *ctx() = s->state;
  *cur_vao(ctx()) = s->vao;
  free(s->shadow); free(s);
}

/* Unlike preview restore, preserve an unconsumed error raised inside the scope.
 * A sticky error from before the scope retains priority, even if consumed inside it. */
void vkgl_scope_restore_preserve_error(void *snapshot) {
  if (!snapshot) return;
  vctx *c = ctx();
  GLenum pending = c->err;
  vkgl_preview_restore(snapshot);
  if (c->err == GL_NO_ERROR) c->err = pending;
}

/* ---- formats ---- */

static VkFormatProperties fmt_props(VkFormat f) {
  VkFormatProperties p;
  vkGetPhysicalDeviceFormatProperties(D.pd, f, &p);
  return p;
}
static int fmt_has(VkFormat f, VkFormatFeatureFlags want) { return (fmt_props(f).optimalTilingFeatures & want) == want; }

enum { CONV_COPY, CONV_RGB_RGBA, CONV_5551_1555, CONV_RAW };
typedef struct {
  VkFormat fmt;
  VkComponentMapping swz;
  int conv;
  int src_bpp, dst_bpp;
} tfmt;

#define SW(r, g, b, a) \
  (VkComponentMapping) { VK_COMPONENT_SWIZZLE_##r, VK_COMPONENT_SWIZZLE_##g, VK_COMPONENT_SWIZZLE_##b, VK_COMPONENT_SWIZZLE_##a }

/* a texture's (or renderbuffer's) GL format as the Vulkan one, and what its pixels need */
static int tex_format(GLenum ifmt, GLenum fmt, GLenum type, tfmt *o) {
  memset(o, 0, sizeof *o);
  o->swz = SWZ_ID;
  o->conv = CONV_COPY;
  switch (ifmt) {
  case GL_RGB:
    if (type == GL_UNSIGNED_SHORT_5_6_5) {
      o->fmt = VK_FORMAT_R5G6B5_UNORM_PACK16, o->src_bpp = o->dst_bpp = 2;
    } else if (type == GL_UNSIGNED_BYTE) {
      o->fmt = VK_FORMAT_R8G8B8A8_UNORM, o->conv = CONV_RGB_RGBA, o->src_bpp = 3, o->dst_bpp = 4;
      o->swz = SW(IDENTITY, IDENTITY, IDENTITY, ONE);
    } else {
      return -1;
    }
    return 0;
  case GL_RGBA:
    if (type == GL_UNSIGNED_BYTE) {
      o->fmt = VK_FORMAT_R8G8B8A8_UNORM, o->src_bpp = o->dst_bpp = 4;
    } else if (type == GL_UNSIGNED_SHORT_4_4_4_4) {
      o->fmt = D.f4444, o->swz = D.sw4444, o->src_bpp = o->dst_bpp = 2;
    } else if (type == GL_UNSIGNED_SHORT_5_5_5_1) {
      o->fmt = D.f5551, o->swz = D.sw5551, o->src_bpp = o->dst_bpp = 2;
      if (D.conv5551) o->conv = CONV_5551_1555;
    } else {
      return -1;
    }
    return 0;
  case GL_LUMINANCE:
    o->fmt = VK_FORMAT_R8_UNORM, o->swz = SW(R, R, R, ONE), o->src_bpp = o->dst_bpp = 1;
    return 0;
  case GL_LUMINANCE_ALPHA:
    o->fmt = VK_FORMAT_R8G8_UNORM, o->swz = SW(R, R, R, G), o->src_bpp = o->dst_bpp = 2;
    return 0;
  case GL_ALPHA:
    o->fmt = VK_FORMAT_R8_UNORM, o->swz = SW(ZERO, ZERO, ZERO, R), o->src_bpp = o->dst_bpp = 1;
    return 0;
  case GL_RGBA8_:
    o->fmt = VK_FORMAT_R8G8B8A8_UNORM, o->src_bpp = o->dst_bpp = 4;
    return 0;
  case GL_RGB8_:
    o->fmt = VK_FORMAT_R8G8B8A8_UNORM, o->swz = SW(IDENTITY, IDENTITY, IDENTITY, ONE), o->conv = CONV_RGB_RGBA;
    o->src_bpp = 3, o->dst_bpp = 4;
    return 0;
  case GL_RGB565:
    o->fmt = VK_FORMAT_R5G6B5_UNORM_PACK16, o->src_bpp = o->dst_bpp = 2;
    return 0;
  case GL_RGBA4:
    o->fmt = D.f4444, o->swz = D.sw4444, o->src_bpp = o->dst_bpp = 2;
    return 0;
  case GL_RGB5_A1:
    o->fmt = D.f5551, o->swz = D.sw5551, o->src_bpp = o->dst_bpp = 2;
    return 0;
  case GL_R11F_G11F_B10F_:
    o->fmt = D.f11, o->src_bpp = o->dst_bpp = 4;
    return 0;
  case GL_RGBA16F_:
    o->fmt = VK_FORMAT_R16G16B16A16_SFLOAT, o->src_bpp = o->dst_bpp = 8;
    return 0;
  case GL_DEPTH24_STENCIL8_:
    o->fmt = D.fd24, o->src_bpp = o->dst_bpp = 4;
    return 0;
  case GL_DEPTH_COMPONENT16:
    o->fmt = VK_FORMAT_D16_UNORM, o->src_bpp = o->dst_bpp = 2;
    return 0;
  case GL_STENCIL_INDEX8:
    o->fmt = D.fs16 ? D.fs16 : D.fd24, o->src_bpp = o->dst_bpp = 1;
    return 0;
  }
  /* ASTC (KHR_texture_compression_astc_ldr): 0x93B0 4x4 .. 0x93BD 12x12, Vulkan's in the
   * same order, each with an sRGB one after it */
  if (ifmt >= 0x93B0 && ifmt <= 0x93BD && D.astc) {
    o->fmt = (VkFormat)(VK_FORMAT_ASTC_4x4_UNORM_BLOCK + 2 * (int)(ifmt - 0x93B0));
    o->conv = CONV_RAW;
    return 0;
  }
  (void)fmt;
  return -1;
}

static void astc_block(VkFormat f, int *bw, int *bh) {
  static const int B[14][2] = { { 4, 4 }, { 5, 4 }, { 5, 5 }, { 6, 5 }, { 6, 6 }, { 8, 5 }, { 8, 6 },
                                { 8, 8 }, { 10, 5 }, { 10, 6 }, { 10, 8 }, { 10, 10 }, { 12, 10 }, { 12, 12 } };
  int k = (f - VK_FORMAT_ASTC_4x4_UNORM_BLOCK) / 2;
  *bw = B[k][0], *bh = B[k][1];
}

/* ---- frames: what one frame in flight has (its command buffers, the rings its uniforms,
 * vertices and pixels go up in, its descriptor pools) ---- */

typedef struct {
  vbufmem **b;
  size_t n, cap, i;
  VkDeviceSize used, chunk;
  VkBufferUsageFlags usage;
} ring;

/* size bytes at align in the ring: their buffer and offset; the mapped pointer */
static uint8_t *ring_alloc(ring *r, VkDeviceSize size, VkDeviceSize align, VkBuffer *buf, VkDeviceSize *off) {
  for (;;) {
    if (r->i < r->n) {
      vbufmem *b = r->b[r->i];
      VkDeviceSize o = (r->used + align - 1) / align * align;
      if (o + size <= b->size) {
        r->used = o + size;
        *buf = b->buf;
        *off = o;
        return b->map + o;
      }
      r->i++;
      r->used = 0;
      continue;
    }
    GROW(r->b, r->n, r->cap);
    r->b[r->n++] = bufmem_new(size > r->chunk ? size : r->chunk, r->usage);
  }
}

static void ring_reset(ring *r) {
  /* (a ring that ran over keeps its buffers: the next frames are likely the same) */
  r->i = 0;
  r->used = 0;
}

typedef struct {
  VkCommandPool pool;
  VkCommandBuffer cmd;
  int open;
  VkFence fence;
  ring stage;
} uploader;

typedef struct {
  VkCommandPool pool;
  VkCommandBuffer cmd;
  int open;
  uploader up;
  VkFence fence;
  int submitted;
  VkSemaphore acquire, render_done;
  ring ubo, vtx;
  VkDescriptorPool *dpool;
  size_t n_dpool, cap_dpool, dpool_i;
} vframe;

static vframe FR[FRAMES];
static vframe *F;
static uploader LOADER_UP;

static void uploader_init(uploader *u) {
  VkCommandPoolCreateInfo pi = { VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO };
  pi.flags = VK_COMMAND_POOL_CREATE_TRANSIENT_BIT;
  pi.queueFamilyIndex = D.qfam;
  PLATFORM_CHECK(vkCreateCommandPool(D.dev, &pi, NULL, &u->pool));
  VkCommandBufferAllocateInfo ai = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, u->pool,
                                     VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1 };
  PLATFORM_CHECK(vkAllocateCommandBuffers(D.dev, &ai, &u->cmd));
  VkFenceCreateInfo fi = { VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
  PLATFORM_CHECK(vkCreateFence(D.dev, &fi, NULL, &u->fence));
  u->stage.chunk = 8 << 20;
  u->stage.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT;
}

static VkCommandBuffer up_cmd(uploader *u) {
  if (!u->open) {
    VkCommandBufferBeginInfo bi = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO };
    bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    VKCHECK(vkBeginCommandBuffer(u->cmd, &bi));
    u->open = 1;
  }
  return u->cmd;
}

static uploader *cur_up(void) { return ctx()->loader ? &LOADER_UP : &F->up; }

static VkResult submit(VkCommandBuffer *cmds, uint32_t n, VkSemaphore wait, VkSemaphore signal, VkFence fence) {
  VkSubmitInfo si = { VK_STRUCTURE_TYPE_SUBMIT_INFO };
  VkPipelineStageFlags stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT;
  si.commandBufferCount = n;
  si.pCommandBuffers = cmds;
  if (wait) si.waitSemaphoreCount = 1, si.pWaitSemaphores = &wait, si.pWaitDstStageMask = &stage;
  if (signal) si.signalSemaphoreCount = 1, si.pSignalSemaphores = &signal;
  pthread_mutex_lock(&D.qlock);
  VkResult result = vkQueueSubmit(D.q, 1, &si, fence);
  pthread_mutex_unlock(&D.qlock);
  VKCHECK(result);
  return result;
}

/* the loading thread's uploads to the GPU and done with: what it made is the game's to use */
static void loader_flush(void) {
  uploader *u = &LOADER_UP;
  if (!u->open || native_loader_failed) return;
  VkResult ended = vkEndCommandBuffer(u->cmd);
  VKCHECK(ended);
  if (ended != VK_SUCCESS) { native_loader_failed = 1; return; }
  u->open = 0;
  if (submit(&u->cmd, 1, VK_NULL_HANDLE, VK_NULL_HANDLE, u->fence) != VK_SUCCESS) {
    native_loader_failed = 1; return; /* never wait forever on an unsubmitted fence */
  }
  VkResult completion = vkWaitForFences(D.dev, 1, &u->fence, VK_TRUE, UINT64_MAX);
  VKCHECK(completion);
  if (completion != VK_SUCCESS) { native_loader_failed = 1; return; }
  native_image_upload_complete();
  VkResult fence_reset = vkResetFences(D.dev, 1, &u->fence);
  VKCHECK(fence_reset);
  if (fence_reset != VK_SUCCESS) { native_loader_failed = 1; return; }
  VkResult pool_reset = vkResetCommandPool(D.dev, u->pool, 0);
  VKCHECK(pool_reset);
  if (pool_reset != VK_SUCCESS) { native_loader_failed = 1; return; }
  ring_reset(&u->stage);
}

static void barrier(VkCommandBuffer c, const vimg *im, int level, int levels, int layer, int layers, VkImageLayout from,
                    VkImageLayout to) {
  VkImageMemoryBarrier b = { VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER };
  b.srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT;
  b.dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT;
  b.oldLayout = from;
  b.newLayout = to;
  b.srcQueueFamilyIndex = b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
  b.image = im->img;
  b.subresourceRange = (VkImageSubresourceRange){ im->aspect, (uint32_t)level, (uint32_t)levels, (uint32_t)layer, (uint32_t)layers };
  vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0, NULL, 0, NULL, 1, &b);
}

/* a new image to its resting layout (its contents undefined) */
static void image_settle(vimg *im) {
  VkCommandBuffer c = up_cmd(cur_up());
  barrier(c, im, 0, im->levels, 0, im->layers, VK_IMAGE_LAYOUT_UNDEFINED, im->rest);
  im->in_rest = 1;
}

/* ---- textures ---- */

static int is_pot(int x) { return x > 0 && !(x & (x - 1)); }
static int full_levels(int w, int h) {
  int n = 1;
  while (w > 1 || h > 1) w = w > 1 ? w / 2 : 1, h = h > 1 ? h / 2 : 1, n++;
  return n;
}

static vtex *bound_tex(GLenum target) {
  vctx *c = ctx();
  int cube = target != GL_TEXTURE_2D;
  GLuint name = cube ? c->texcube[c->unit] : c->tex2d[c->unit];
  return tex_get(name);
}

/* the sampled view with the levels given so far, from the base on */
static void tex_view(vimg *im) {
  int n = 0;
  while (n < im->levels && (im->level_mask >> n & 1)) n++;
  if (n < 1) n = 1;
  if (n == im->view_levels) return;
  dead_add(DEAD_VIEW, NULL, (uint64_t)(uintptr_t)im->view, D.serial);
  im->view = view_new(im, 1, n);
  im->view_levels = n;
}

static int image_busy(const vimg *im) { return im->serial > done_serial() || im->serial == D.serial; }

/* level `level` of t (face `face` of a cube) about to be given w x h pixels in f: its image
 * to put them in, new if it has none of this kind or the GPU may still be reading it */
static vimg *tex_image_for(vtex *t, int level, int layers, VkFormat fmt, VkComponentMapping swz, int w, int h, int data) {
  vimg *im = t->im;
  int bw = level ? (im ? im->w : w << level) : w, bh = level ? (im ? im->h : h << level) : h;
  int fresh = !im || im->fmt != fmt || im->layers != layers || im->w != bw || im->h != bh || level >= im->levels;
  if (!fresh && !image_busy(im)) return im;
  int levels = level ? full_levels(bw, bh) : data && is_pot(bw) && is_pot(bh) ? full_levels(bw, bh) : 1;
  if (im && !fresh && im->levels > levels) levels = im->levels;
  vimg *n = image_new(fmt, bw, bh, levels, layers, 1, 1, 0, swz);
  if (!n) return NULL;
  image_settle(n);
  /* the levels it had, but for the one being given (a level after the base; the base given
   * again with the same size keeps the rest too) */
  if (im && im->fmt == fmt && im->layers == layers && im->w == bw && im->h == bh) {
    VkCommandBuffer c = up_cmd(cur_up());
    uint32_t keep = im->level_mask & ~(1u << level);
    for (int l = 0; l < im->levels && l < levels; ++l) {
      if (!(keep >> l & 1)) continue;
      barrier(c, im, l, 1, 0, layers, im->rest, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
      barrier(c, n, l, 1, 0, layers, n->rest, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
      int lw = bw >> l > 0 ? bw >> l : 1, lh = bh >> l > 0 ? bh >> l : 1;
      VkImageCopy r = { { n->aspect, (uint32_t)l, 0, (uint32_t)layers }, { 0, 0, 0 },
                        { n->aspect, (uint32_t)l, 0, (uint32_t)layers }, { 0, 0, 0 }, { (uint32_t)lw, (uint32_t)lh, 1 } };
      vkCmdCopyImage(c, im->img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, n->img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &r);
      barrier(c, im, l, 1, 0, layers, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, im->rest);
      barrier(c, n, l, 1, 0, layers, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, n->rest);
      n->level_mask |= 1u << l;
    }
    im->serial = D.serial; /* (read by this frame's uploads) */
  }
  image_drop(im);
  t->im = n;
  return n;
}

/* Shared Vulkan upload recording; caller supplies the uploader's staged bytes. */
static void image_upload_record(VkCommandBuffer c, vimg *im, int level, int face, int w, int h,
                                VkBuffer sb, VkDeviceSize so) {
  barrier(c, im, level, 1, face, 1, im->rest, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
  VkBufferImageCopy r = { so, 0, 0, { im->aspect, (uint32_t)level, (uint32_t)face, 1 }, { 0, 0, 0 }, { (uint32_t)w, (uint32_t)h, 1 } };
  vkCmdCopyBufferToImage(c, sb, im->img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &r);
  barrier(c, im, level, 1, face, 1, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, im->rest);
}

/* pixels into level, face of im (from the staging ring), rows packed by the unpack alignment */
static void image_upload(vimg *im, int level, int face, int w, int h, const tfmt *f, const void *data, size_t raw_size,
                         int unpack) {
  uploader *u = cur_up();
  VkDeviceSize size;
  if (f->conv == CONV_RAW) size = raw_size;
  else size = (VkDeviceSize)w * h * f->dst_bpp;
  VkBuffer sb;
  VkDeviceSize so;
  uint8_t *dst = ring_alloc(&u->stage, size, 16, &sb, &so);
  if (f->conv == CONV_RAW) {
    memcpy(dst, data, raw_size);
  } else {
    size_t pitch = ((size_t)w * f->src_bpp + (size_t)unpack - 1) / (size_t)unpack * (size_t)unpack;
    const uint8_t *src = data;
    for (int y = 0; y < h; ++y, src += pitch) {
      uint8_t *d = dst + (size_t)y * w * f->dst_bpp;
      if (f->conv == CONV_COPY) {
        memcpy(d, src, (size_t)w * f->src_bpp);
      } else if (f->conv == CONV_RGB_RGBA) {
        for (int x = 0; x < w; ++x) d[4 * x] = src[3 * x], d[4 * x + 1] = src[3 * x + 1], d[4 * x + 2] = src[3 * x + 2], d[4 * x + 3] = 255;
      } else if (f->conv == CONV_5551_1555) {
        const uint16_t *s16 = (const uint16_t *)src;
        uint16_t *d16 = (uint16_t *)d;
        for (int x = 0; x < w; ++x) d16[x] = (uint16_t)((s16[x] >> 1) | ((s16[x] & 1u) << 15));
      }
    }
  }
  VkCommandBuffer c = up_cmd(u);
  image_upload_record(c, im, level, face, w, h, sb, so);
  if (ctx()->loader && u->stage.n > 4) loader_flush(); /* (a big step: its staging back sooner) */
}

static void tex_spec(GLenum target, GLint level, const tfmt *f, int w, int h, const void *data, size_t raw) {
  int face = 0, layers = 1;
  GLenum bind = GL_TEXTURE_2D;
  if (target >= GL_TEXTURE_CUBE_MAP_POSITIVE_X && target <= GL_TEXTURE_CUBE_MAP_NEGATIVE_Z) {
    face = (int)(target - GL_TEXTURE_CUBE_MAP_POSITIVE_X), layers = 6, bind = GL_TEXTURE_CUBE_MAP;
  }
  vtex *t = bound_tex(bind);
  if (!t || w < 1 || h < 1 || level < 0 || level > 15) {
    set_err(GL_INVALID_OPERATION);
    return;
  }
  vimg *im = t->im;
  /* a cube's faces after the first go into its image as it is */
  if (!(layers == 6 && face && im && im->layers == 6 && level < im->levels && !image_busy(im)))
    im = tex_image_for(t, level, layers, f->fmt, f->swz, w, h, data != NULL);
  if (!im) {
    set_err(GL_OUT_OF_MEMORY);
    return;
  }
  if (data) image_upload(im, level, face, w, h, f, data, raw, ctx()->unpack);
  im->level_mask |= 1u << level;
  tex_view(im);
}

/* ---- samplers, by the texture's parameters ---- */

typedef struct {
  cinder_vk_sampler state;
  int levels;
  VkSampler s;
} samp_t;
static samp_t *samps;
static size_t n_samps, cap_samps;

/* The cache/driver boundary takes Vulkan values only. Compatibility texture
 * defaults are translated by sampler_for; native packets bypass translation
 * and never mutate texture resources to change addressing. */
static VkSampler cinder_vk_sampler_get(const cinder_vk_sampler *requested, int levels) {
  cinder_vk_sampler key = *requested;
  key.use_state = 1;
  if (!key.mipmaps) {
    levels = 1;
    key.mipmap_mode = VK_SAMPLER_MIPMAP_MODE_NEAREST; /* maxLod .25 must stay at L0 */
  }
  if (!key.mipmaps || !D.aniso || key.anisotropy < 1.0f) key.anisotropy = 1.0f;
  else if (key.anisotropy > D.max_aniso) key.anisotropy = D.max_aniso;
  pthread_mutex_lock(&D.lock);
  for (size_t i = 0; i < n_samps; ++i) {
    samp_t *s = &samps[i]; const cinder_vk_sampler *k = &s->state;
    if (s->levels == levels && k->min_filter == key.min_filter && k->mag_filter == key.mag_filter &&
        k->mipmap_mode == key.mipmap_mode && k->address_u == key.address_u && k->address_v == key.address_v &&
        k->mipmaps == key.mipmaps && k->anisotropy == key.anisotropy) {
      if (platform_native_profile && !s->s) continue; /* never perpetuate a failed Native cache entry */
      pthread_mutex_unlock(&D.lock);
      return s->s;
    }
  }
  VkSamplerCreateInfo si = { VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO };
  si.magFilter = key.mag_filter; si.minFilter = key.min_filter;
  si.mipmapMode = key.mipmap_mode;
  si.addressModeU = key.address_u; si.addressModeV = key.address_v;
  si.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
  si.anisotropyEnable = key.anisotropy > 1.0f; si.maxAnisotropy = key.anisotropy;
  si.minLod = 0; si.maxLod = key.mipmaps ? (float)levels : 0.25f;
  si.borderColor = VK_BORDER_COLOR_FLOAT_OPAQUE_BLACK;
  VkSampler s = VK_NULL_HANDLE;
  VkResult result = vkCreateSampler(D.dev, &si, NULL, &s);
  if (platform_native_profile && (result != VK_SUCCESS || !s)) {
    /* Error output is undefined; a missing success handle is not a cache hit.
     * The actual Native binding caller rejects NULL without descriptor writes. */
    logf_("native sampler unavailable: %d", result);
    pthread_mutex_unlock(&D.lock);
    return VK_NULL_HANDLE;
  }
  if (result == VK_SUCCESS) {
    GROW(samps, n_samps, cap_samps);
    samps[n_samps++] = (samp_t){ key, levels, s };
  } else logf_("sampler creation failed: %d", result);
  pthread_mutex_unlock(&D.lock);
  return s;
}
static VkSamplerAddressMode wrap_mode(GLenum w) {
  return w == GL_CLAMP_TO_EDGE ? VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE
         : w == GL_MIRRORED_REPEAT ? VK_SAMPLER_ADDRESS_MODE_MIRRORED_REPEAT : VK_SAMPLER_ADDRESS_MODE_REPEAT;
}
static cinder_vk_sampler sampler_defaults(const vtex *t) {
  GLenum min = t->min ? t->min : GL_NEAREST_MIPMAP_LINEAR, mag = t->mag ? t->mag : GL_LINEAR;
  int mip = min != GL_NEAREST && min != GL_LINEAR;
  cinder_vk_sampler state = { .use_state=1, .mipmaps=(VkBool32)mip,
    .min_filter=min == GL_NEAREST || min == GL_NEAREST_MIPMAP_NEAREST || min == GL_NEAREST_MIPMAP_LINEAR ? VK_FILTER_NEAREST : VK_FILTER_LINEAR,
    .mag_filter=mag == GL_NEAREST ? VK_FILTER_NEAREST : VK_FILTER_LINEAR,
    .mipmap_mode=min == GL_NEAREST_MIPMAP_LINEAR || min == GL_LINEAR_MIPMAP_LINEAR ? VK_SAMPLER_MIPMAP_MODE_LINEAR : VK_SAMPLER_MIPMAP_MODE_NEAREST,
    .address_u=wrap_mode(t->wrap_s), .address_v=wrap_mode(t->wrap_t),
    .anisotropy=mip && D.aniso && t->aniso > 1.0f ? floorf(t->aniso + 0.5f) : 1.0f };
  return state;
}
static VkSampler sampler_for(const vtex *t, int levels) {
  cinder_vk_sampler state = t->native_sampler.use_state ? t->native_sampler : sampler_defaults(t);
  return cinder_vk_sampler_get(&state, levels);
}
int cinder_vk_texture_sampler(uint32_t texture, cinder_vk_sampler *out) {
  const vtex *t = tex_get(texture);
  if (!out || !t || !t->im) return 0;
  *out = t->native_sampler.use_state ? t->native_sampler : sampler_defaults(t);
  return 1;
}

/* ---- the GL calls: textures ---- */

void vkgl_glGenTextures(GLsizei n, GLuint *out) {
  for (GLsizei i = 0; i < n; ++i) out[i] = tex_gen();
}

void vkgl_glDeleteTextures(GLsizei n, const GLuint *names) {
  vctx *c = ctx();
  for (GLsizei i = 0; i < n; ++i) {
    vtex *t = tex_get(names[i]);
    if (!t) continue;
    image_drop(t->im);
    t->im = NULL;
    for (int u = 0; u < MAX_UNITS; ++u) {
      if (c->tex2d[u] == names[i]) c->tex2d[u] = 0;
      if (c->texcube[u] == names[i]) c->texcube[u] = 0;
    }
    tex_release(names[i]);
  }
}

void vkgl_glActiveTexture(GLenum unit) {
  int u = (int)(unit - GL_TEXTURE0);
  if (u < 0 || u >= MAX_UNITS) {
    set_err(GL_INVALID_ENUM);
    return;
  }
  ctx()->unit = u;
}

void vkgl_glBindTexture(GLenum target, GLuint name) {
  vctx *c = ctx();
  vtex *t = tex_get(name);
  if (name && !t) { /* (a name not from glGenTextures: GL makes it) */
    set_err(GL_INVALID_OPERATION);
    return;
  }
  if (t && !t->target) t->target = target;
  if (target == GL_TEXTURE_CUBE_MAP) c->texcube[c->unit] = name;
  else c->tex2d[c->unit] = name;
}

void vkgl_glTexImage2D(GLenum target, GLint level, GLint ifmt, GLsizei w, GLsizei h, GLint border, GLenum fmt, GLenum type,
                       const void *data) {
  tfmt f;
  /* a sized depth texture's or an unsized one's format as asked */
  if (tex_format((GLenum)ifmt, fmt, type, &f) != 0 && tex_format(fmt, fmt, type, &f) != 0) {
    logf_("texture format 0x%x/0x%x/0x%x unknown", ifmt, fmt, type);
    set_err(GL_INVALID_ENUM);
    return;
  }
  (void)border;
  tex_spec(target, level, &f, w, h, data, 0);
}

void vkgl_glCompressedTexImage2D(GLenum target, GLint level, GLenum ifmt, GLsizei w, GLsizei h, GLint border, GLsizei size,
                                 const void *data) {
  tfmt f;
  if (tex_format(ifmt, 0, 0, &f) != 0 || f.conv != CONV_RAW) {
    set_err(GL_INVALID_ENUM);
    return;
  }
  int bw, bh;
  astc_block(f.fmt, &bw, &bh);
  if ((size_t)size < (size_t)((w + bw - 1) / bw) * (size_t)((h + bh - 1) / bh) * 16u) {
    set_err(GL_INVALID_VALUE);
    return;
  }
  (void)border;
  tex_spec(target, level, &f, w, h, data, (size_t)size);
}

void vkgl_glTexParameteri(GLenum target, GLenum pname, GLint v) {
  vtex *t = bound_tex(target);
  if (!t) return;
  if (pname == GL_TEXTURE_MIN_FILTER) t->min = (GLenum)v;
  else if (pname == GL_TEXTURE_MAG_FILTER) t->mag = (GLenum)v;
  else if (pname == GL_TEXTURE_WRAP_S) t->wrap_s = (GLenum)v;
  else if (pname == GL_TEXTURE_WRAP_T) t->wrap_t = (GLenum)v;
  else if (pname == GL_TEXTURE_MAX_ANISOTROPY_) t->aniso = (float)v;
}

void vkgl_glTexParameterf(GLenum target, GLenum pname, GLfloat v) {
  if (pname == GL_TEXTURE_MAX_ANISOTROPY_) {
    vtex *t = bound_tex(target);
    if (t) t->aniso = v;
    return;
  }
  vkgl_glTexParameteri(target, pname, (GLint)v);
}

void vkgl_glPixelStorei(GLenum pname, GLint v) {
  if (pname == GL_UNPACK_ALIGNMENT) ctx()->unpack = v;
  else if (pname == GL_PACK_ALIGNMENT) ctx()->pack = v;
}

/* the levels after the base from it, by blits (the image's format must allow it) */
void vkgl_glGenerateMipmap(GLenum target) {
  vtex *t = bound_tex(target);
  if (!t || !t->im) return;
  vimg *im = t->im;
  if (im->levels < 2) {
    if (!(im = tex_image_for(t, 1, im->layers, im->fmt, im->swz, im->w >> 1 ? im->w >> 1 : 1, im->h >> 1 ? im->h >> 1 : 1, 1)))
      return;
  }
  VkCommandBuffer c = up_cmd(cur_up());
  for (int l = 1; l < im->levels; ++l) {
    int sw = im->w >> (l - 1), sh = im->h >> (l - 1), dw = im->w >> l, dh = im->h >> l;
    sw = sw ? sw : 1, sh = sh ? sh : 1, dw = dw ? dw : 1, dh = dh ? dh : 1;
    barrier(c, im, l - 1, 1, 0, im->layers, im->rest, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
    barrier(c, im, l, 1, 0, im->layers, im->rest, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    VkImageBlit b = { { im->aspect, (uint32_t)l - 1, 0, (uint32_t)im->layers }, { { 0, 0, 0 }, { sw, sh, 1 } },
                      { im->aspect, (uint32_t)l, 0, (uint32_t)im->layers }, { { 0, 0, 0 }, { dw, dh, 1 } } };
    vkCmdBlitImage(c, im->img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, im->img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b,
                   VK_FILTER_LINEAR);
    barrier(c, im, l - 1, 1, 0, im->layers, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, im->rest);
    barrier(c, im, l, 1, 0, im->layers, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, im->rest);
    im->level_mask |= 1u << l;
  }
  tex_view(im);
}

/* ---- buffers ---- */

#define BUF_USAGE (VK_BUFFER_USAGE_VERTEX_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT)

void vkgl_glGenBuffers(GLsizei n, GLuint *out) {
  for (GLsizei i = 0; i < n; ++i) out[i] = buf_gen();
}

void vkgl_glDeleteBuffers(GLsizei n, const GLuint *names) {
  vctx *c = ctx();
  for (GLsizei i = 0; i < n; ++i) {
    vbuf *b = buf_get(names[i]);
    if (!b) continue;
    bufmem_drop(b->m);
    b->m = NULL;
    if (c->array_buf == names[i]) c->array_buf = 0;
    vvao *v = cur_vao(c);
    if (v->ebo == names[i]) v->ebo = 0;
    buf_release(names[i]);
  }
}

void vkgl_glBindBuffer(GLenum target, GLuint name) {
  vctx *c = ctx();
  if (target == GL_ARRAY_BUFFER) c->array_buf = name;
  else if (target == GL_ELEMENT_ARRAY_BUFFER) cur_vao(c)->ebo = name;
}

static vbuf *bound_buf(GLenum target) {
  vctx *c = ctx();
  return buf_get(target == GL_ELEMENT_ARRAY_BUFFER ? cur_vao(c)->ebo : c->array_buf);
}

static int bufmem_busy(const vbufmem *m) { return m->serial > done_serial() || m->serial == D.serial; }

void vkgl_glBufferData(GLenum target, GLsizeiptr size, const void *data, GLenum usage) {
  vbuf *b = bound_buf(target);
  (void)usage;
  if (!b) {
    set_err(GL_INVALID_OPERATION);
    return;
  }
  if (!b->m || b->m->size != (VkDeviceSize)(size ? size : 4) || bufmem_busy(b->m)) {
    bufmem_drop(b->m);
    b->m = bufmem_new((VkDeviceSize)size, BUF_USAGE);
  }
  if (data && size) memcpy(b->m->map, data, (size_t)size);
}

void vkgl_glBufferSubData(GLenum target, GLintptr off, GLsizeiptr size, const void *data) {
  vbuf *b = bound_buf(target);
  if (!b || !b->m || off < 0 || (VkDeviceSize)(off + size) > b->m->size) {
    set_err(GL_INVALID_VALUE);
    return;
  }
  if (bufmem_busy(b->m)) { /* a new one with the old contents */
    vbufmem *n = bufmem_new(b->m->size, BUF_USAGE);
    memcpy(n->map, b->m->map, (size_t)b->m->size);
    bufmem_drop(b->m);
    b->m = n;
  }
  memcpy(b->m->map + off, data, (size_t)size);
}

/* ---- renderbuffers ---- */

void vkgl_glGenRenderbuffers(GLsizei n, GLuint *out) {
  for (GLsizei i = 0; i < n; ++i) out[i] = rbo_gen();
}

void vkgl_glDeleteRenderbuffers(GLsizei n, const GLuint *names) {
  for (GLsizei i = 0; i < n; ++i) {
    vrbo *r = rbo_get(names[i]);
    if (!r) continue;
    image_drop(r->im);
    r->im = NULL;
    if (ctx()->rbo == names[i]) ctx()->rbo = 0;
    rbo_release(names[i]);
  }
}

void vkgl_glBindRenderbuffer(GLenum target, GLuint name) {
  (void)target;
  ctx()->rbo = name;
}

void vkgl_glRenderbufferStorageMultisample(GLenum target, GLsizei samples, GLenum ifmt, GLsizei w, GLsizei h) {
  vrbo *r = rbo_get(ctx()->rbo);
  tfmt f;
  (void)target;
  if (!r || tex_format(ifmt, 0, 0, &f) != 0) {
    set_err(GL_INVALID_OPERATION);
    return;
  }
  int s = samples <= 1 ? 1 : samples <= 2 ? 2 : samples <= 4 ? 4 : 8;
  if (s > D.max_samples) s = D.max_samples;
  image_drop(r->im);
  /* (multisampled: never kept, but by a pass a later one goes on from) */
  r->im = image_new(f.fmt, w, h, 1, 1, s, 0, s > 1, SWZ_ID);
  if (!r->im) set_err(GL_OUT_OF_MEMORY);
}

void vkgl_glRenderbufferStorage(GLenum target, GLenum ifmt, GLsizei w, GLsizei h) {
  vkgl_glRenderbufferStorageMultisample(target, 1, ifmt, w, h);
}

/* ---- framebuffers (the GL objects; their passes below) ---- */

void vkgl_glGenFramebuffers(GLsizei n, GLuint *out) {
  for (GLsizei i = 0; i < n; ++i) out[i] = fbo_gen();
}

void vkgl_glDeleteFramebuffers(GLsizei n, const GLuint *names) {
  vctx *c = ctx();
  for (GLsizei i = 0; i < n; ++i) {
    vfbo *f = fbo_get(names[i]);
    if (!f) continue;
    if (f->native) {
      cinder_vk_target_destroy(names[i]);
      if (c->draw_fb == names[i]) c->draw_fb = 0;
      if (c->read_fb == names[i]) c->read_fb = 0;
      continue;
    }
    image_drop(f->ms);
    f->ms = NULL;
    if (c->draw_fb == names[i]) c->draw_fb = 0;
    if (c->read_fb == names[i]) c->read_fb = 0;
    fbo_release(names[i]);
  }
}

void vkgl_glBindFramebuffer(GLenum target, GLuint name) {
  vctx *c = ctx();
  if (target == GL_FRAMEBUFFER || target == GL_DRAW_FRAMEBUFFER_) c->draw_fb = name;
  if (target == GL_FRAMEBUFFER || target == GL_READ_FRAMEBUFFER_) c->read_fb = name;
}

static vfbo *bound_fbo(GLenum target) {
  vctx *c = ctx();
  return fbo_get(target == GL_READ_FRAMEBUFFER_ ? c->read_fb : c->draw_fb);
}

static void fbo_attach(GLenum target, GLenum point, int kind, GLuint name, int samples) {
  vfbo *f = bound_fbo(target);
  if (!f) {
    set_err(GL_INVALID_OPERATION);
    return;
  }
  if (f->native) { set_err(GL_INVALID_OPERATION); return; } /* immutable snapshot target */
  vatt a = { name ? kind : 0, name, samples > 1 ? samples : 0 };
  if (point == GL_COLOR_ATTACHMENT0) f->color = a;
  else if (point == GL_DEPTH_ATTACHMENT) f->depth = a;
  else if (point == GL_STENCIL_ATTACHMENT) f->stencil = a;
  else if (point == GL_DEPTH_STENCIL_ATTACHMENT_) f->depth = f->stencil = a;
  else set_err(GL_INVALID_ENUM);
}

void vkgl_glFramebufferTexture2D(GLenum target, GLenum point, GLenum textarget, GLuint tex, GLint level) {
  (void)textarget, (void)level;
  fbo_attach(target, point, 1, tex, 0);
}

void vkgl_glFramebufferTexture2DMultisampleEXT(GLenum target, GLenum point, GLenum textarget, GLuint tex, GLint level,
                                               GLsizei samples) {
  (void)textarget, (void)level;
  if (point != GL_COLOR_ATTACHMENT0) { /* (a depth texture rendered multisampled: not here) */
    set_err(GL_INVALID_OPERATION);
    return;
  }
  int s = samples <= 1 ? 0 : samples <= 2 ? 2 : samples <= 4 ? 4 : 8;
  if (s > D.max_samples) s = D.max_samples;
  fbo_attach(target, point, 1, tex, s);
}

void vkgl_glFramebufferRenderbuffer(GLenum target, GLenum point, GLenum rbtarget, GLuint rb) {
  (void)rbtarget;
  fbo_attach(target, point, 2, rb, 0);
}

static vimg *att_image(const vatt *a) {
  if (a->kind == 1) {
    vtex *t = tex_get(a->name);
    return t ? t->im : NULL;
  }
  if (a->kind == 2) {
    vrbo *r = rbo_get(a->name);
    return r ? r->im : NULL;
  }
  return NULL;
}

GLenum vkgl_glCheckFramebufferStatus(GLenum target) {
  vfbo *f = bound_fbo(target);
  if (!f) return GL_FRAMEBUFFER_COMPLETE; /* the screen's */
  vimg *c = att_image(&f->color), *d = att_image(&f->depth), *s = att_image(&f->stencil);
  if (!c && !d) return GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT;
  if ((f->color.kind && (!c || !c->att || is_depth(c->fmt))) || (f->depth.kind && (!d || !is_depth(d->fmt))) ||
      (f->stencil.kind && (!s || s != d || !has_stencil(s->fmt))))
    return GL_FRAMEBUFFER_UNSUPPORTED;
  if (c && d) {
    int cs = f->color.samples ? f->color.samples : c->samples;
    if (cs != d->samples) return 0x8D56; /* GL_FRAMEBUFFER_INCOMPLETE_MULTISAMPLE */
  }
  return GL_FRAMEBUFFER_COMPLETE;
}

/* ---- programs ---- */

static uint64_t prog_key(const char *vs, const char *fs, const char **attribs, int n) {
  uint64_t h = 0xcbf29ce484222325ull;
#define FNV(b) (h ^= (uint8_t)(b), h *= 0x100000001b3ull)
  for (const char *p = vs; *p; ++p) FNV(*p);
  FNV(0);
  for (const char *p = fs; *p; ++p) FNV(*p);
  FNV(0);
  for (int i = 0; i < n; ++i) {
    if (i) FNV(' ');
    for (const char *p = attribs[i]; *p; ++p) FNV(*p);
  }
#undef FNV
  return h;
}

static VkShaderModule shader_module(const uint32_t *words, size_t n) {
  if (platform_native_profile) {
    VkShaderModuleCreateInfo ci = { VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO };
    ci.codeSize = n * 4;
    ci.pCode = words;
    VkShaderModule m = VK_NULL_HANDLE;
    VkResult result = vkCreateShaderModule(D.dev, &ci, NULL, &m);
    VKCHECK(result);
    /* Native off-table program construction already owns rollback. Failure
     * output is undefined: neither publish it nor guess that it can be freed. */
    if (result != VK_SUCCESS || !m) {
      logf_("native shader module unavailable: %d", result);
      return VK_NULL_HANDLE;
    }
    return m;
  }
  VkShaderModuleCreateInfo ci = { VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO };
  ci.codeSize = n * 4;
  ci.pCode = words;
  VkShaderModule m = VK_NULL_HANDLE;
  VKCHECK(vkCreateShaderModule(D.dev, &ci, NULL, &m));
  return m;
}

/* refl: vkglsl.py's line after the key */
static int prog_reflect(vprog *p, const char *refl) {
  char *s = strdup(refl), *save = NULL;
  char *tok = strtok_r(s, " \n", &save); /* the key */
  tok = tok ? strtok_r(NULL, " \n", &save) : NULL;
  if (!tok) {
    free(s);
    return -1;
  }
  p->block = atoi(tok);
  tok = strtok_r(NULL, " \n", &save);
  p->inputs = tok ? (uint32_t)strtoul(tok, NULL, 10) : 0;
  int cap = 8;
  p->uni = xcalloc((size_t)cap, sizeof *p->uni);
  while ((tok = strtok_r(NULL, " \n", &save))) {
    char *c1 = strchr(tok, ':'), *c2 = c1 ? strchr(c1 + 1, ':') : NULL;
    if (!c2) continue;
    if (p->n_uni == cap) {
      cap *= 2;
      p->uni = realloc(p->uni, (size_t)cap * sizeof *p->uni);
    }
    vuni *u = &p->uni[p->n_uni++];
    memset(u, 0, sizeof *u);
    snprintf(u->name, sizeof u->name, "%.*s", (int)(c1 - tok), tok);
    u->code = atoi(c1 + 1);
    u->off = atoi(c2 + 1);
    if (u->code >= 7 && p->n_samp < MAX_SAMP) p->samp_cube[p->n_samp++] = u->code == 8;
  }
  free(s);
  if (p->block > UBO_RANGE) {
    logf_("a uniform block of %d bytes", p->block);
    return -1;
  }
  p->shadow = xcalloc((size_t)(p->block ? p->block : 16), 1);
  p->dirty = 1;
  return 0;
}

static uint32_t *read_words(const char *path, size_t *n) {
  FILE *f = fopen(path, "rb");
  if (!f) return NULL;
  fseek(f, 0, SEEK_END);
  long len = ftell(f);
  fseek(f, 0, SEEK_SET);
  uint32_t *w = len > 0 ? malloc((size_t)len) : NULL;
  if (w && fread(w, 1, (size_t)len, f) != (size_t)len) {
    free(w);
    w = NULL;
  }
  fclose(f);
  *n = (size_t)len / 4;
  return w;
}

static void dump_program(const char *path, const char *vs, const char *fs, const char **attribs, int n) {
  FILE *f = fopen(path, "w");
  if (!f) return;
  for (int i = 0; i < n; ++i) fprintf(f, "%s%s", i ? " " : "// attribs: ", attribs[i]);
  fprintf(f, "\n//----VS\n%s\n//----FS\n%s", vs, fs);
  fclose(f);
}

GLuint vkgl_program(const char *vs, const char *fs, const char **attribs, int n_attribs) {
  uint64_t key = prog_key(vs, fs, attribs, n_attribs);
  char hex[17];
  snprintf(hex, sizeof hex, "%016llx", (unsigned long long)key);
  GLuint id = prog_gen();
  vprog *p = prog_get(id);
  memcpy(p->key, hex, sizeof p->key);
  for (int i = 0; i < VKGL_N_SPV; ++i) {
    if (memcmp(VKGL_SPV[i].refl, hex, 16) != 0) continue;
    if (prog_reflect(p, VKGL_SPV[i].refl) != 0) break;
    p->vs = shader_module(VKGL_SPV[i].vs, (size_t)VKGL_SPV[i].n_vs);
    p->fs = shader_module(VKGL_SPV[i].fs, (size_t)VKGL_SPV[i].n_fs);
    if (VKGL_SPV[i].n_vs2) {
      p->vs2 = shader_module(VKGL_SPV[i].vs2, (size_t)VKGL_SPV[i].n_vs2);
      p->fs2 = shader_module(VKGL_SPV[i].fs2, (size_t)VKGL_SPV[i].n_fs2);
    }
    if (!(p->uid = resource_uid_next())) { vkgl_glDeleteProgram(id); return 0; }
    return id;
  }
  /* not made ahead: on the desktop, made now by vkglsl.py; else kept for the next build */
  const char *dir = getenv("VKGL_SPV_DIR");
  char path[1024];
  if (dir) {
    char prefix[900], cmd[2400], refl[16384];
    snprintf(path, sizeof path, "%s/%s.txt", dir, hex);
    snprintf(prefix, sizeof prefix, "%s/%s", dir, hex);
    dump_program(path, vs, fs, attribs, n_attribs);
    const char *tool = getenv("VKGL_TOOLS") ? getenv("VKGL_TOOLS") : "tools/vkglsl.py";
    snprintf(cmd, sizeof cmd, "python3 %s one %s %s", tool, path, prefix);
    if (system(cmd) == 0) {
      size_t nv = 0, nf = 0;
      snprintf(path, sizeof path, "%s.vert.spv", prefix);
      uint32_t *v = read_words(path, &nv);
      snprintf(path, sizeof path, "%s.frag.spv", prefix);
      uint32_t *f = read_words(path, &nf);
      snprintf(path, sizeof path, "%s.refl", prefix);
      FILE *rf = fopen(path, "r");
      int ok = rf && fgets(refl, sizeof refl, rf) && v && f && prog_reflect(p, refl) == 0;
      if (rf) fclose(rf);
      if (ok) {
        p->vs = shader_module(v, nv);
        p->fs = shader_module(f, nf);
      }
      free(v);
      free(f);
      if (ok) {
        if (!(p->uid = resource_uid_next())) { vkgl_glDeleteProgram(id); return 0; }
        return id;
      }
    }
    logf_("program %s: no SPIR-V", hex);
  } else {
    logf_("program %s not in vkgl_spv.c: not drawn", hex);
    if (getenv("VKGL_MISSING_DIR")) {
      snprintf(path, sizeof path, "%s/%s.txt", getenv("VKGL_MISSING_DIR"), hex);
      dump_program(path, vs, fs, attribs, n_attribs);
    }
  }
  /* (a program that draws nothing, so the game goes on) */
  if (!(p->uid = resource_uid_next())) { vkgl_glDeleteProgram(id); return 0; }
  if (!p->shadow) p->shadow = xcalloc(16, 1);
  return id;
}

void vkgl_glDeleteProgram(GLuint id) {
  vprog *p = prog_get(id);
  if (!p) return;
  /* (its pipelines stay in the table: a program is deleted once, at the end) */
  if (p->vs) vkDestroyShaderModule(D.dev, p->vs, NULL);
  if (p->fs) vkDestroyShaderModule(D.dev, p->fs, NULL);
  if (p->vs2) vkDestroyShaderModule(D.dev, p->vs2, NULL);
  if (p->fs2) vkDestroyShaderModule(D.dev, p->fs2, NULL);
  free(p->uni);
  free(p->shadow);
  if (ctx()->prog == id) ctx()->prog = 0;
  prog_release(id);
}

void vkgl_glUseProgram(GLuint id) { ctx()->prog = id; }

GLint vkgl_glGetUniformLocation(GLuint id, const GLchar *name) {
  vprog *p = prog_get(id);
  if (!p) return -1;
  for (int i = 0; i < p->n_uni; ++i) {
    const char *a = p->uni[i].name, *b = name;
    while (*a && *a == *b) a++, b++;
    if (!*a && !*b) return i;
  }
  return -1;
}

static vuni *uni_at(GLint loc, vprog **pp) {
  vprog *p = prog_get(ctx()->prog);
  if (!p || loc < 0 || loc >= p->n_uni) return NULL;
  *pp = p;
  return &p->uni[loc];
}

static void uni_put(GLint loc, const void *v, size_t n) {
  vprog *p;
  vuni *u = uni_at(loc, &p);
  if (!u || u->code >= 7) return;
  static const size_t SIZE[7] = { 0, 4, 8, 12, 16, 4, 64 };
  if (n > SIZE[u->code]) n = SIZE[u->code];
  if (memcmp(p->shadow + u->off, v, n) != 0) {
    memcpy(p->shadow + u->off, v, n);
    p->dirty = 1;
  }
}

void vkgl_glUniform1i(GLint loc, GLint v) {
  vprog *p;
  vuni *u = uni_at(loc, &p);
  if (!u) return;
  if (u->code >= 7) {
    if (u->off >= 1 && u->off <= MAX_SAMP) p->samp_unit[u->off - 1] = v;
    return;
  }
  if (u->code == 1) {
    float f = (float)v;
    uni_put(loc, &f, 4);
  } else {
    uni_put(loc, &v, 4);
  }
}
void vkgl_glUniform1f(GLint loc, GLfloat a) { uni_put(loc, &a, 4); }
void vkgl_glUniform2f(GLint loc, GLfloat a, GLfloat b) {
  float v[2] = { a, b };
  uni_put(loc, v, sizeof v);
}
void vkgl_glUniform3f(GLint loc, GLfloat a, GLfloat b, GLfloat c) {
  float v[3] = { a, b, c };
  uni_put(loc, v, sizeof v);
}
void vkgl_glUniform4f(GLint loc, GLfloat a, GLfloat b, GLfloat c, GLfloat d) {
  float v[4] = { a, b, c, d };
  uni_put(loc, v, sizeof v);
}
void vkgl_glUniform3fv(GLint loc, GLsizei n, const GLfloat *v) {
  (void)n;
  uni_put(loc, v, 12);
}
void vkgl_glUniform4fv(GLint loc, GLsizei n, const GLfloat *v) {
  (void)n;
  uni_put(loc, v, 16);
}
void vkgl_glUniformMatrix4fv(GLint loc, GLsizei n, GLboolean transpose, const GLfloat *v) {
  (void)n, (void)transpose;
  uni_put(loc, v, 64);
}

/* ---- vertex arrays ---- */

void vkgl_glGenVertexArraysOES(GLsizei n, GLuint *out) {
  for (GLsizei i = 0; i < n; ++i) out[i] = vao_gen();
}

void vkgl_glDeleteVertexArraysOES(GLsizei n, const GLuint *names) {
  for (GLsizei i = 0; i < n; ++i) {
    if (ctx()->vao == names[i]) ctx()->vao = 0;
    vao_release(names[i]);
  }
}

void vkgl_glBindVertexArrayOES(GLuint name) { ctx()->vao = name; }

void vkgl_glEnableVertexAttribArray(GLuint i) {
  if (i < MAX_ATTR) cur_vao(ctx())->a[i].enabled = 1;
}
void vkgl_glDisableVertexAttribArray(GLuint i) {
  if (i < MAX_ATTR) cur_vao(ctx())->a[i].enabled = 0;
}

void vkgl_glVertexAttribPointer(GLuint i, GLint size, GLenum type, GLboolean norm, GLsizei stride, const void *ptr) {
  vctx *c = ctx();
  if (i >= MAX_ATTR) {
    set_err(GL_INVALID_VALUE);
    return;
  }
  vattr *a = &cur_vao(c)->a[i];
  a->size = size, a->type = type, a->norm = norm, a->stride = stride, a->buf = c->array_buf, a->ptr = ptr;
}

void vkgl_glVertexAttrib4f(GLuint i, GLfloat x, GLfloat y, GLfloat z, GLfloat w) {
  if (i >= MAX_ATTR) return;
  float *g = ctx()->generic[i];
  g[0] = x, g[1] = y, g[2] = z, g[3] = w;
}

/* ---- fixed function state ---- */

static int *cap_of(vctx *c, GLenum cap) {
  switch (cap) {
  case GL_BLEND: return &c->blend;
  case GL_DEPTH_TEST: return &c->depth_test;
  case GL_CULL_FACE: return &c->cull;
  case GL_SCISSOR_TEST: return &c->scissor_test;
  case GL_STENCIL_TEST: return &c->stencil_test;
  }
  return NULL;
}
void vkgl_glEnable(GLenum cap) {
  int *p = cap_of(ctx(), cap);
  if (p) *p = 1;
}
void vkgl_glDisable(GLenum cap) {
  int *p = cap_of(ctx(), cap);
  if (p) *p = 0;
}
void vkgl_glBlendFunc(GLenum s, GLenum d) { ctx()->bsrc = s, ctx()->bdst = d; }
void vkgl_glBlendEquation(GLenum e) { ctx()->beq = e; }
void vkgl_glColorMask(GLboolean r, GLboolean g, GLboolean b, GLboolean a) {
  ctx()->cmask = (r ? 1 : 0) | (g ? 2 : 0) | (b ? 4 : 0) | (a ? 8 : 0);
}
void vkgl_glCullFace(GLenum m) { ctx()->cull_face = m; }
void vkgl_glFrontFace(GLenum m) { ctx()->front = m; }
void vkgl_glDepthFunc(GLenum f) { ctx()->dfunc = f; }
void vkgl_glDepthMask(GLboolean m) { ctx()->depth_write = m != 0; }
void vkgl_glStencilFunc(GLenum f, GLint ref, GLuint mask) {
  vctx *c = ctx();
  c->sfunc = f, c->sref = ref, c->smask = mask;
}
void vkgl_glStencilOp(GLenum fail, GLenum zfail, GLenum zpass) {
  vctx *c = ctx();
  c->sfail = fail, c->szfail = zfail, c->szpass = zpass;
}
void vkgl_glStencilMask(GLuint m) { ctx()->swmask = m; }
void vkgl_glViewport(GLint x, GLint y, GLsizei w, GLsizei h) {
  GLint *v = ctx()->vp;
  v[0] = x, v[1] = y, v[2] = w, v[3] = h;
}
void vkgl_glScissor(GLint x, GLint y, GLsizei w, GLsizei h) {
  GLint *v = ctx()->sc;
  v[0] = x, v[1] = y, v[2] = w, v[3] = h;
}
void vkgl_glClearColor(GLfloat r, GLfloat g, GLfloat b, GLfloat a) {
  float *c = ctx()->clear;
  c[0] = r, c[1] = g, c[2] = b, c[3] = a;
}

/* ---- render passes: by what a pass's attachments are (compat: what pipelines and
 * framebuffers must match) and what it loads and stores ---- */

typedef struct {
  VkFormat cfmt, dfmt;
  int samples, resolve;
  VkRenderPass rp; /* one of them, for the pipelines and framebuffers */
} compat_t;
static compat_t compats[64];
static int n_compats;

typedef struct {
  int compat;
  uint8_t cload, cstore, dload, dstore, sload, sstore, cundef, dundef;
  VkImageLayout crest, drest, rrest;
  VkRenderPass rp;
} rp_t;
static rp_t *rps;
static size_t n_rps, cap_rps;

static VkRenderPass rp_make(const compat_t *k, const rp_t *o) {
  VkAttachmentDescription a[3];
  VkAttachmentReference cref = { 0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL },
                        dref = { 0, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL },
                        rref = { 0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL };
  uint32_t n = 0;
  memset(a, 0, sizeof a);
  if (k->cfmt) {
    cref.attachment = n;
    a[n].format = k->cfmt;
    a[n].samples = (VkSampleCountFlagBits)k->samples;
    a[n].loadOp = (VkAttachmentLoadOp)o->cload;
    a[n].storeOp = (VkAttachmentStoreOp)o->cstore;
    a[n].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    a[n].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    a[n].initialLayout = o->cundef ? VK_IMAGE_LAYOUT_UNDEFINED : o->crest;
    a[n].finalLayout = o->crest;
    n++;
  }
  if (k->dfmt) {
    dref.attachment = n;
    a[n].format = k->dfmt;
    a[n].samples = (VkSampleCountFlagBits)k->samples;
    a[n].loadOp = (VkAttachmentLoadOp)o->dload;
    a[n].storeOp = (VkAttachmentStoreOp)o->dstore;
    a[n].stencilLoadOp = (VkAttachmentLoadOp)o->sload;
    a[n].stencilStoreOp = (VkAttachmentStoreOp)o->sstore;
    a[n].initialLayout = o->dundef ? VK_IMAGE_LAYOUT_UNDEFINED : o->drest;
    a[n].finalLayout = o->drest;
    n++;
  }
  if (k->resolve) {
    rref.attachment = n;
    a[n].format = k->cfmt;
    a[n].samples = VK_SAMPLE_COUNT_1_BIT;
    a[n].loadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    a[n].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    a[n].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    a[n].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    a[n].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    a[n].finalLayout = o->rrest;
    n++;
  }
  VkSubpassDescription sp = { 0 };
  sp.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
  sp.colorAttachmentCount = k->cfmt ? 1 : 0;
  sp.pColorAttachments = &cref;
  sp.pResolveAttachments = k->resolve ? &rref : NULL;
  sp.pDepthStencilAttachment = k->dfmt ? &dref : NULL;
  /* what came before (passes, copies, the swapchain's acquire) done before, what comes after
   * waits for this */
  VkSubpassDependency dep[2] = {
    { VK_SUBPASS_EXTERNAL, 0,
      VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT | VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT |
        VK_PIPELINE_STAGE_VERTEX_SHADER_BIT | VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT,
      VK_PIPELINE_STAGE_VERTEX_SHADER_BIT | VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT | VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT |
        VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT | VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
      VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT | VK_ACCESS_TRANSFER_WRITE_BIT,
      VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
        VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT,
      0 },
    { 0, VK_SUBPASS_EXTERNAL,
      VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT |
        VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT,
      VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT | VK_PIPELINE_STAGE_VERTEX_SHADER_BIT | VK_PIPELINE_STAGE_TRANSFER_BIT |
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT |
        VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT,
      VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT,
      VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_TRANSFER_READ_BIT | VK_ACCESS_TRANSFER_WRITE_BIT |
        VK_ACCESS_COLOR_ATTACHMENT_READ_BIT | VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
        VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT,
      0 },
  };
  VkRenderPassCreateInfo ci = { VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO };
  ci.attachmentCount = n;
  ci.pAttachments = a;
  ci.subpassCount = 1;
  ci.pSubpasses = &sp;
  ci.dependencyCount = 2;
  ci.pDependencies = dep;
  VkRenderPass rp;
  if (platform_native_profile) rp = VK_NULL_HANDLE;
  VkResult result = vkCreateRenderPass(D.dev, &ci, NULL, &rp);
  VKCHECK(result);
  /* Do not publish a compatibility/cache entry with an undefined render pass.
   * This native-only fatal boundary is deliberately not global VKCHECK policy:
   * the loader's explicit nonfatal failures must preserve unknown leases. */
  if (platform_native_profile && (result != VK_SUCCESS || !rp)) {
    logf_("native render pass unavailable: %d", result); abort();
  }
  return rp;
}

static int compat_id(VkFormat cfmt, VkFormat dfmt, int samples, int resolve) {
  for (int i = 0; i < n_compats; ++i) {
    compat_t *k = &compats[i];
    if (k->cfmt == cfmt && k->dfmt == dfmt && k->samples == samples && k->resolve == resolve) return i;
  }
  if (n_compats == 64) {
    logf_("too many kinds of framebuffer");
    return 0;
  }
  compat_t *k = &compats[n_compats];
  *k = (compat_t){ cfmt, dfmt, samples, resolve, VK_NULL_HANDLE };
  rp_t o = { 0 };
  o.cload = o.dload = o.sload = VK_ATTACHMENT_LOAD_OP_LOAD;
  o.crest = o.rrest = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
  o.drest = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;
  k->rp = rp_make(k, &o);
  return n_compats++;
}

/* Native targets must not alias compatibility kind zero when the cache is full.
 * Native-profile rp_make now explicitly fails fatally before publication;
 * legacy VKCHECK remains log-only. Capacity admission is not device recovery. */
static int native_compat_id(VkFormat cfmt, VkFormat dfmt, int samples, int resolve) {
  for (int i = 0; i < n_compats; ++i) {
    const compat_t *k = &compats[i];
    if (k->cfmt == cfmt && k->dfmt == dfmt && k->samples == samples && k->resolve == resolve) return i;
  }
  return n_compats < 64 ? compat_id(cfmt, dfmt, samples, resolve) : -1;
}

static VkRenderPass rp_get(const rp_t *o) {
  for (size_t i = 0; i < n_rps; ++i) {
    rp_t *r = &rps[i];
    if (r->compat == o->compat && r->cload == o->cload && r->cstore == o->cstore && r->dload == o->dload &&
        r->dstore == o->dstore && r->sload == o->sload && r->sstore == o->sstore && r->cundef == o->cundef &&
        r->dundef == o->dundef && r->crest == o->crest && r->drest == o->drest && r->rrest == o->rrest)
      return r->rp;
  }
  GROW(rps, n_rps, cap_rps);
  rps[n_rps] = *o;
  rps[n_rps].rp = rp_make(&compats[o->compat], o);
  return rps[n_rps++].rp;
}

/* framebuffers by their views (the game's thread's alone) */
typedef struct {
  int compat;
  VkImageView v[3];
  int w, h;
  VkFramebuffer fb;
} fbent;
static fbent *fbs;
static size_t n_fbs, cap_fbs;

static VkFramebuffer fb_get(int compat, const VkImageView *v, int n, int w, int h) {
  if (platform_native_profile) {
    if (!v || n < 1 || n > 3 || w < 1 || h < 1 || compat < 0 || compat >= n_compats || !compats[compat].rp) {
      logf_("native framebuffer key unavailable"); abort();
    }
    VkImageView key[3] = { VK_NULL_HANDLE, VK_NULL_HANDLE, VK_NULL_HANDLE };
    for (int i = 0; i < n; ++i) {
      if (!v[i]) { logf_("native framebuffer has a missing view"); abort(); }
      key[i] = v[i];
    }
    pthread_mutex_lock(&D.lock);
    for (size_t i = 0; i < n_fbs; ++i) {
      fbent *e = &fbs[i];
      if (e->compat == compat && e->w == w && e->h == h && !memcmp(e->v, key, sizeof key)) {
        VkFramebuffer fb = e->fb;
        pthread_mutex_unlock(&D.lock);
        if (!fb) { logf_("native framebuffer cache contains a missing handle"); abort(); }
        return fb;
      }
    }
    VkFramebufferCreateInfo ci = { VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO };
    ci.renderPass = compats[compat].rp;
    ci.attachmentCount = (uint32_t)n;
    ci.pAttachments = v;
    ci.width = (uint32_t)w;
    ci.height = (uint32_t)h;
    ci.layers = 1;
    VkFramebuffer fb = VK_NULL_HANDLE;
    VkResult result = vkCreateFramebuffer(D.dev, &ci, NULL, &fb);
    VKCHECK(result);
    if (result != VK_SUCCESS || !fb) {
      pthread_mutex_unlock(&D.lock);
      logf_("native framebuffer unavailable: %d", result); abort();
    }
    GROW(fbs, n_fbs, cap_fbs);
    fbent *e = &fbs[n_fbs];
    memset(e, 0, sizeof *e);
    e->compat = compat; e->w = w; e->h = h; e->fb = fb;
    memcpy(e->v, key, sizeof key);
    ++n_fbs;
    pthread_mutex_unlock(&D.lock);
    return fb;
  }
  pthread_mutex_lock(&D.lock);
  for (size_t i = 0; i < n_fbs; ++i) {
    fbent *e = &fbs[i];
    if (e->compat == compat && e->w == w && e->h == h && !memcmp(e->v, v, (size_t)n * sizeof *v)) {
      VkFramebuffer fb = e->fb;
      pthread_mutex_unlock(&D.lock);
      return fb;
    }
  }
  VkFramebufferCreateInfo ci = { VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO };
  ci.renderPass = compats[compat].rp;
  ci.attachmentCount = (uint32_t)n;
  ci.pAttachments = v;
  ci.width = (uint32_t)w;
  ci.height = (uint32_t)h;
  ci.layers = 1;
  GROW(fbs, n_fbs, cap_fbs);
  fbent *e = &fbs[n_fbs++];
  memset(e, 0, sizeof *e);
  e->compat = compat, e->w = w, e->h = h;
  memcpy(e->v, v, (size_t)n * sizeof *v);
  VKCHECK(vkCreateFramebuffer(D.dev, &ci, NULL, &e->fb));
  VkFramebuffer fb = e->fb;
  pthread_mutex_unlock(&D.lock);
  return fb;
}

/* (when the view is destroyed: the GPU is done with its framebuffers) */
static void fb_cache_forget(VkImageView view) {
  /* Constructor cleanup may run on the loader while the main owner caches an
   * unrelated framebuffer. Do not race array growth/swap-removal. */
  pthread_mutex_lock(&D.lock);
  for (size_t i = 0; i < n_fbs;) {
    fbent *e = &fbs[i];
    if (e->v[0] == view || e->v[1] == view || e->v[2] == view) {
      vkDestroyFramebuffer(D.dev, e->fb, NULL);
      *e = fbs[--n_fbs];
    } else {
      i++;
    }
  }
  pthread_mutex_unlock(&D.lock);
}

/* ---- pipelines, by the state a draw has ---- */

static const VkFormat VFMT[] = {
  VK_FORMAT_UNDEFINED,
  VK_FORMAT_R32_SFLOAT, VK_FORMAT_R32G32_SFLOAT, VK_FORMAT_R32G32B32_SFLOAT, VK_FORMAT_R32G32B32A32_SFLOAT,     /* 1 float */
  VK_FORMAT_R8_UNORM, VK_FORMAT_R8G8_UNORM, VK_FORMAT_R8G8B8_UNORM, VK_FORMAT_R8G8B8A8_UNORM,                  /* 5 ubyte n */
  VK_FORMAT_R8_USCALED, VK_FORMAT_R8G8_USCALED, VK_FORMAT_R8G8B8_USCALED, VK_FORMAT_R8G8B8A8_USCALED,          /* 9 ubyte */
  VK_FORMAT_R16_SNORM, VK_FORMAT_R16G16_SNORM, VK_FORMAT_R16G16B16_SNORM, VK_FORMAT_R16G16B16A16_SNORM,        /* 13 short n */
  VK_FORMAT_R16_SSCALED, VK_FORMAT_R16G16_SSCALED, VK_FORMAT_R16G16B16_SSCALED, VK_FORMAT_R16G16B16A16_SSCALED, /* 17 short */
  VK_FORMAT_R16_UNORM, VK_FORMAT_R16G16_UNORM, VK_FORMAT_R16G16B16_UNORM, VK_FORMAT_R16G16B16A16_UNORM,        /* 21 ushort n */
  VK_FORMAT_R8_SNORM, VK_FORMAT_R8G8_SNORM, VK_FORMAT_R8G8B8_SNORM, VK_FORMAT_R8G8B8A8_SNORM,                  /* 25 byte n */
};

#define N_VFMT (int)(sizeof VFMT / sizeof *VFMT)
static VkFormat vfmt_dev[N_VFMT]; /* VFMT as this GPU reads them: three parts as four where it must */

/* a vertex attribute's format code (VFMT), 0 if not one here; its element's size */
static int vfmt_code(GLenum type, int size, int norm, int *esize) {
  if (size < 1 || size > 4) return 0;
  switch (type) {
  case GL_FLOAT: *esize = 4 * size; return size;
  case GL_UNSIGNED_BYTE: *esize = size; return (norm ? 4 : 8) + size;
  case GL_SHORT: *esize = 2 * size; return (norm ? 12 : 16) + size;
  case GL_UNSIGNED_SHORT: *esize = 2 * size; return norm ? 20 + size : 0;
  case GL_BYTE: *esize = size; return norm ? 24 + size : 0;
  }
  return 0;
}

typedef struct {
  uint32_t prog;
  uint16_t compat;
  uint8_t topo, flip;
  uint8_t blend, bsrc, bdst, beq;
  uint8_t cmask, depth_test, depth_write, dfunc;
  uint8_t cull, front_ccw, stencil, sfunc;
  uint8_t sfail, szfail, szpass, smask;
  uint8_t swmask, inst, pad[2];
  uint8_t afmt[MAX_ATTR];
  uint16_t astride[MAX_ATTR];
} pkey;

typedef struct {
  pkey k;
  VkPipeline p;
  int used;
} pent;
static pent *pipes;
static size_t n_pipes, cap_pipes; /* cap a power of two */

static VkDescriptorSetLayout dsl[MAX_SAMP + 1];
static VkPipelineLayout playout[MAX_SAMP + 1];

static uint64_t hash_bytes(const void *p, size_t n) {
  const uint8_t *b = p;
  uint64_t h = 0xcbf29ce484222325ull;
  for (size_t i = 0; i < n; ++i) h = (h ^ b[i]) * 0x100000001b3ull;
  return h;
}

static VkBlendFactor blend_factor(GLenum f) {
  switch (f) {
  case GL_ZERO: return VK_BLEND_FACTOR_ZERO;
  case GL_ONE: return VK_BLEND_FACTOR_ONE;
  case GL_SRC_COLOR: return VK_BLEND_FACTOR_SRC_COLOR;
  case GL_ONE_MINUS_SRC_COLOR: return VK_BLEND_FACTOR_ONE_MINUS_SRC_COLOR;
  case GL_DST_COLOR: return VK_BLEND_FACTOR_DST_COLOR;
  case GL_ONE_MINUS_DST_COLOR: return VK_BLEND_FACTOR_ONE_MINUS_DST_COLOR;
  case GL_SRC_ALPHA: return VK_BLEND_FACTOR_SRC_ALPHA;
  case GL_ONE_MINUS_SRC_ALPHA: return VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
  case GL_DST_ALPHA: return VK_BLEND_FACTOR_DST_ALPHA;
  case GL_ONE_MINUS_DST_ALPHA: return VK_BLEND_FACTOR_ONE_MINUS_DST_ALPHA;
  case GL_SRC_ALPHA_SATURATE: return VK_BLEND_FACTOR_SRC_ALPHA_SATURATE;
  }
  return VK_BLEND_FACTOR_ONE;
}

static VkCompareOp compare_op(GLenum f) { return (VkCompareOp)(f >= GL_NEVER && f <= GL_ALWAYS ? f - GL_NEVER : 7); }

static VkStencilOp stencil_op(GLenum o) {
  switch (o) {
  case GL_ZERO: return VK_STENCIL_OP_ZERO;
  case GL_REPLACE: return VK_STENCIL_OP_REPLACE;
  case GL_INCR: return VK_STENCIL_OP_INCREMENT_AND_CLAMP;
  case GL_DECR: return VK_STENCIL_OP_DECREMENT_AND_CLAMP;
  case GL_INVERT: return VK_STENCIL_OP_INVERT;
  case GL_INCR_WRAP: return VK_STENCIL_OP_INCREMENT_AND_WRAP;
  case GL_DECR_WRAP: return VK_STENCIL_OP_DECREMENT_AND_WRAP;
  }
  return VK_STENCIL_OP_KEEP;
}

/* Native cache observation/replacement shares the pipeline-table mutex with
 * actual pipeline creation, including creation outside the table lookup lock. */
static VkResult backend_pipeline_create(const VkGraphicsPipelineCreateInfo *info, VkPipeline *pipeline) {
  if (platform_native_profile) pthread_mutex_lock(&D.plock);
  VkResult result = vkCreateGraphicsPipelines(D.dev, D.pcache, 1, info, NULL, pipeline);
  if (platform_native_profile) pthread_mutex_unlock(&D.plock);
  return result;
}

static VkPipeline pipeline_make(const pkey *k, vprog *p) {
  if (platform_native_profile) {
    /* Program modules/key fields are immutable while published. Only this
     * preference changes across main/loader creation, so snapshot it atomically
     * once: a single create must never mix the two shader pairs. */
    int alt = __atomic_load_n(&p->alt, __ATOMIC_ACQUIRE) != 0;
    if (alt && (!p->vs2 || !p->fs2)) return VK_NULL_HANDLE;
    const compat_t *cp = &compats[k->compat];
    float flip = k->flip ? -1.0f : 1.0f;
    VkSpecializationMapEntry me = { 0, 0, 4 };
    VkSpecializationInfo spec = { 1, &me, 4, &flip };
    VkPipelineShaderStageCreateInfo st[2] = {
      { VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_VERTEX_BIT, alt ? p->vs2 : p->vs, "main",
        &spec },
      { VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_FRAGMENT_BIT, alt ? p->fs2 : p->fs, "main",
        NULL },
    };
    VkVertexInputBindingDescription vb[MAX_ATTR];
    VkVertexInputAttributeDescription va[MAX_ATTR];
    uint32_t n = 0;
    for (uint32_t i = 0; i < MAX_ATTR; ++i) {
      if (!(p->inputs >> i & 1)) continue;
      vb[n] = (VkVertexInputBindingDescription){ i, k->astride[i],
                                                 (k->inst >> i & 1) ? VK_VERTEX_INPUT_RATE_INSTANCE : VK_VERTEX_INPUT_RATE_VERTEX };
      va[n] = (VkVertexInputAttributeDescription){ i, i, vfmt_dev[k->afmt[i]], 0 };
      n++;
    }
    VkPipelineVertexInputStateCreateInfo vi = { VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO };
    vi.vertexBindingDescriptionCount = n;
    vi.pVertexBindingDescriptions = vb;
    vi.vertexAttributeDescriptionCount = n;
    vi.pVertexAttributeDescriptions = va;
    VkPipelineInputAssemblyStateCreateInfo ia = { VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO };
    ia.topology = (VkPrimitiveTopology)k->topo;
    VkPipelineViewportStateCreateInfo vs = { VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO };
    vs.viewportCount = vs.scissorCount = 1;
    VkPipelineRasterizationStateCreateInfo rs = { VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO };
    rs.polygonMode = VK_POLYGON_MODE_FILL;
    rs.cullMode = k->cull;
    rs.frontFace = k->front_ccw ? VK_FRONT_FACE_COUNTER_CLOCKWISE : VK_FRONT_FACE_CLOCKWISE;
    rs.lineWidth = 1.0f;
    VkPipelineMultisampleStateCreateInfo ms = { VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO };
    ms.rasterizationSamples = (VkSampleCountFlagBits)cp->samples;
    VkPipelineDepthStencilStateCreateInfo ds = { VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO };
    ds.depthTestEnable = k->depth_test;
    ds.depthWriteEnable = k->depth_test && k->depth_write;
    ds.depthCompareOp = (VkCompareOp)k->dfunc;
    ds.stencilTestEnable = k->stencil;
    ds.front = (VkStencilOpState){ (VkStencilOp)k->sfail, (VkStencilOp)k->szpass, (VkStencilOp)k->szfail, (VkCompareOp)k->sfunc,
                                   k->smask, k->swmask, 0 };
    ds.back = ds.front;
    VkPipelineColorBlendAttachmentState cb = { 0 };
    cb.blendEnable = k->blend;
    cb.srcColorBlendFactor = cb.srcAlphaBlendFactor = (VkBlendFactor)k->bsrc;
    cb.dstColorBlendFactor = cb.dstAlphaBlendFactor = (VkBlendFactor)k->bdst;
    cb.colorBlendOp = cb.alphaBlendOp = (VkBlendOp)k->beq;
    cb.colorWriteMask = k->cmask;
    VkPipelineColorBlendStateCreateInfo bs = { VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO };
    bs.attachmentCount = cp->cfmt ? 1 : 0;
    bs.pAttachments = &cb;
    VkDynamicState dyn[3] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR, VK_DYNAMIC_STATE_STENCIL_REFERENCE };
    VkPipelineDynamicStateCreateInfo dy = { VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO };
    dy.dynamicStateCount = 3;
    dy.pDynamicStates = dyn;
    VkGraphicsPipelineCreateInfo ci = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO };
    ci.stageCount = 2;
    ci.pStages = st;
    ci.pVertexInputState = &vi;
    ci.pInputAssemblyState = &ia;
    ci.pViewportState = &vs;
    ci.pRasterizationState = &rs;
    ci.pMultisampleState = &ms;
    ci.pDepthStencilState = &ds;
    ci.pColorBlendState = &bs;
    ci.pDynamicState = &dy;
    ci.layout = playout[p->n_samp];
    ci.renderPass = cp->rp;
    VkPipeline pl = VK_NULL_HANDLE;
    if (getenv("VKGL_DEBUG")) logf_("pipeline for %s, compat %d, flip %d", p->key, k->compat, k->flip);
    VkResult r = getenv("VKGL_TEST_ALT") && !alt ? VK_ERROR_INITIALIZATION_FAILED
                                                 : backend_pipeline_create(&ci, &pl);
    if (r == VK_SUCCESS && pl) return pl;
    /* Pipeline creation has defined per-element outputs even on failed calls:
     * every non-null returned pipeline is owned and must not be discarded. */
    if (pl) { vkDestroyPipeline(D.dev, pl, NULL); pl = VK_NULL_HANDLE; }
    logf_("native pipeline unavailable: %d (program %s%s, compat %d)", r, p->key, alt ? " all highp" : "", k->compat);
    if (r == VK_ERROR_DEVICE_LOST) return VK_NULL_HANDLE;
    if (!alt && p->vs2 && p->fs2) {
      st[0].module = p->vs2; st[1].module = p->fs2;
      pl = VK_NULL_HANDLE;
      r = backend_pipeline_create(&ci, &pl);
      if (r == VK_SUCCESS && pl) {
        __atomic_store_n(&p->alt, 1, __ATOMIC_RELEASE);
        logf_("program %s all highp: made", p->key);
        return pl;
      }
      if (pl) vkDestroyPipeline(D.dev, pl, NULL);
      logf_("program %s all highp: unavailable (%d)", p->key, r);
    }
    return VK_NULL_HANDLE;
  }
  const compat_t *cp = &compats[k->compat];
  float flip = k->flip ? -1.0f : 1.0f;
  VkSpecializationMapEntry me = { 0, 0, 4 };
  VkSpecializationInfo spec = { 1, &me, 4, &flip };
  VkPipelineShaderStageCreateInfo st[2] = {
    { VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_VERTEX_BIT, p->alt ? p->vs2 : p->vs, "main",
      &spec },
    { VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_FRAGMENT_BIT, p->alt ? p->fs2 : p->fs, "main",
      NULL },
  };
  VkVertexInputBindingDescription vb[MAX_ATTR];
  VkVertexInputAttributeDescription va[MAX_ATTR];
  uint32_t n = 0;
  for (uint32_t i = 0; i < MAX_ATTR; ++i) {
    if (!(p->inputs >> i & 1)) continue;
    vb[n] = (VkVertexInputBindingDescription){ i, k->astride[i],
                                               (k->inst >> i & 1) ? VK_VERTEX_INPUT_RATE_INSTANCE : VK_VERTEX_INPUT_RATE_VERTEX };
    va[n] = (VkVertexInputAttributeDescription){ i, i, vfmt_dev[k->afmt[i]], 0 };
    n++;
  }
  VkPipelineVertexInputStateCreateInfo vi = { VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO };
  vi.vertexBindingDescriptionCount = n;
  vi.pVertexBindingDescriptions = vb;
  vi.vertexAttributeDescriptionCount = n;
  vi.pVertexAttributeDescriptions = va;
  VkPipelineInputAssemblyStateCreateInfo ia = { VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO };
  ia.topology = (VkPrimitiveTopology)k->topo;
  VkPipelineViewportStateCreateInfo vs = { VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO };
  vs.viewportCount = vs.scissorCount = 1;
  VkPipelineRasterizationStateCreateInfo rs = { VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO };
  rs.polygonMode = VK_POLYGON_MODE_FILL;
  rs.cullMode = k->cull;
  rs.frontFace = k->front_ccw ? VK_FRONT_FACE_COUNTER_CLOCKWISE : VK_FRONT_FACE_CLOCKWISE;
  rs.lineWidth = 1.0f;
  VkPipelineMultisampleStateCreateInfo ms = { VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO };
  ms.rasterizationSamples = (VkSampleCountFlagBits)cp->samples;
  VkPipelineDepthStencilStateCreateInfo ds = { VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO };
  ds.depthTestEnable = k->depth_test;
  ds.depthWriteEnable = k->depth_test && k->depth_write;
  ds.depthCompareOp = (VkCompareOp)k->dfunc;
  ds.stencilTestEnable = k->stencil;
  ds.front = (VkStencilOpState){ (VkStencilOp)k->sfail, (VkStencilOp)k->szpass, (VkStencilOp)k->szfail, (VkCompareOp)k->sfunc,
                                 k->smask, k->swmask, 0 };
  ds.back = ds.front;
  VkPipelineColorBlendAttachmentState cb = { 0 };
  cb.blendEnable = k->blend;
  cb.srcColorBlendFactor = cb.srcAlphaBlendFactor = (VkBlendFactor)k->bsrc;
  cb.dstColorBlendFactor = cb.dstAlphaBlendFactor = (VkBlendFactor)k->bdst;
  cb.colorBlendOp = cb.alphaBlendOp = (VkBlendOp)k->beq;
  cb.colorWriteMask = k->cmask;
  VkPipelineColorBlendStateCreateInfo bs = { VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO };
  bs.attachmentCount = cp->cfmt ? 1 : 0;
  bs.pAttachments = &cb;
  VkDynamicState dyn[3] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR, VK_DYNAMIC_STATE_STENCIL_REFERENCE };
  VkPipelineDynamicStateCreateInfo dy = { VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO };
  dy.dynamicStateCount = 3;
  dy.pDynamicStates = dyn;
  VkGraphicsPipelineCreateInfo ci = { VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO };
  ci.stageCount = 2;
  ci.pStages = st;
  ci.pVertexInputState = &vi;
  ci.pInputAssemblyState = &ia;
  ci.pViewportState = &vs;
  ci.pRasterizationState = &rs;
  ci.pMultisampleState = &ms;
  ci.pDepthStencilState = &ds;
  ci.pColorBlendState = &bs;
  ci.pDynamicState = &dy;
  ci.layout = playout[p->n_samp];
  ci.renderPass = cp->rp;
  VkPipeline pl = VK_NULL_HANDLE;
  if (getenv("VKGL_DEBUG")) logf_("pipeline for %s, compat %d, flip %d", p->key, k->compat, k->flip);
  VkResult r = getenv("VKGL_TEST_ALT") && !p->alt ? VK_ERROR_INITIALIZATION_FAILED /* (the second try tested) */
                                                  : backend_pipeline_create(&ci, &pl);
  if (r != VK_SUCCESS) {
    logf_("pipeline failed: %d (program %s%s, compat %d)", r, p->key, p->alt ? " all highp" : "", k->compat);
    if (!p->alt && p->vs2) { /* the program's from now on all highp, if that one goes */
      st[0].module = p->vs2, st[1].module = p->fs2;
      pl = VK_NULL_HANDLE;
      r = backend_pipeline_create(&ci, &pl);
      logf_("program %s all highp: %s", p->key, r == VK_SUCCESS ? "made" : "failed too");
      if (r == VK_SUCCESS) p->alt = 1;
      else pl = VK_NULL_HANDLE;
    } else {
      pl = VK_NULL_HANDLE;
    }
  }
  return pl;
}

static VkPipeline pipeline_get(const pkey *k, vprog *p, int *made) {
  if (platform_native_profile) {
    uint64_t h = hash_bytes(k, sizeof *k);
    pthread_mutex_lock(&D.plock);
    if (cap_pipes) {
      for (size_t probe = 0, i = h & (cap_pipes - 1); probe < cap_pipes;
           ++probe, i = (i + 1) & (cap_pipes - 1)) {
        if (!pipes[i].used) break;
        if (!memcmp(&pipes[i].k, k, sizeof *k)) {
          VkPipeline cached = pipes[i].p;
          if (cached) { pthread_mutex_unlock(&D.plock); return cached; }
          break; /* Old/corrupt NULL row is not a successful cache hit. */
        }
      }
    }
    pthread_mutex_unlock(&D.plock);
    VkPipeline pl = pipeline_make(k, p);
    pthread_mutex_lock(&D.plock);
    /* Even a failed creator may use a valid winner published meanwhile. */
    if (cap_pipes) {
      for (size_t probe = 0, i = h & (cap_pipes - 1); probe < cap_pipes;
           ++probe, i = (i + 1) & (cap_pipes - 1)) {
        if (!pipes[i].used) break;
        if (!memcmp(&pipes[i].k, k, sizeof *k)) {
          if (pipes[i].p) {
            if (pl) vkDestroyPipeline(D.dev, pl, NULL);
            pl = pipes[i].p;
            pthread_mutex_unlock(&D.plock);
            return pl;
          }
          if (pl) { /* Repair in place without a duplicate entry/count. */
            pipes[i].p = pl;
            if (made) *made = 1;
          }
          pthread_mutex_unlock(&D.plock);
          return pl;
        }
      }
    }
    if (!pl) { pthread_mutex_unlock(&D.plock); return VK_NULL_HANDLE; }
    if ((n_pipes + 1) * 2 > cap_pipes) {
      size_t cap = cap_pipes ? cap_pipes * 2 : 1024;
      pent *t = xcalloc(cap, sizeof *t);
      for (size_t i = 0; i < cap_pipes; ++i) {
        if (!pipes[i].used) continue;
        size_t j = hash_bytes(&pipes[i].k, sizeof *k) & (cap - 1);
        while (t[j].used) j = (j + 1) & (cap - 1);
        t[j] = pipes[i];
      }
      free(pipes); pipes = t; cap_pipes = cap;
    }
    size_t i = h & (cap_pipes - 1);
    while (pipes[i].used) i = (i + 1) & (cap_pipes - 1);
    pipes[i] = (pent){ *k, pl, 1 };
    ++n_pipes;
    /* Accumulate successful insertion/repair, not mere attempts/race winners. */
    if (made) *made = 1;
    pthread_mutex_unlock(&D.plock);
    return pl;
  }
  uint64_t h = hash_bytes(k, sizeof *k);
  pthread_mutex_lock(&D.plock);
  if (cap_pipes) {
    for (size_t i = h & (cap_pipes - 1);; i = (i + 1) & (cap_pipes - 1)) {
      if (!pipes[i].used) break;
      if (!memcmp(&pipes[i].k, k, sizeof *k)) {
        VkPipeline pl = pipes[i].p;
        pthread_mutex_unlock(&D.plock);
        return pl;
      }
    }
  }
  pthread_mutex_unlock(&D.plock);
  /* (made outside the lock: the other thread's lookups don't wait for it) */
  VkPipeline pl = pipeline_make(k, p);
  if (made) *made = 1;
  pthread_mutex_lock(&D.plock);
  if ((n_pipes + 1) * 2 > cap_pipes) {
    size_t cap = cap_pipes ? cap_pipes * 2 : 1024;
    pent *t = xcalloc(cap, sizeof *t);
    for (size_t i = 0; i < cap_pipes; ++i) {
      if (!pipes[i].used) continue;
      size_t j = hash_bytes(&pipes[i].k, sizeof *k) & (cap - 1);
      while (t[j].used) j = (j + 1) & (cap - 1);
      t[j] = pipes[i];
    }
    free(pipes);
    pipes = t;
    cap_pipes = cap;
  }
  size_t i = h & (cap_pipes - 1);
  while (pipes[i].used && memcmp(&pipes[i].k, k, sizeof *k)) i = (i + 1) & (cap_pipes - 1);
  if (pipes[i].used) { /* the other thread made it meanwhile */
    vkDestroyPipeline(D.dev, pl, NULL);
    pl = pipes[i].p;
  } else {
    pipes[i] = (pent){ *k, pl, 1 };
    n_pipes++;
  }
  pthread_mutex_unlock(&D.plock);
  return pl;
}

/* ---- descriptor sets: a frame's, from its pools, the same ones again within it ---- */

typedef struct {
  int n;
  VkBuffer ubo;
  uint32_t range;
  VkImageView v[MAX_SAMP];
  VkSampler s[MAX_SAMP];
} dkey;
typedef struct {
  dkey k;
  VkDescriptorSet set;
  uint64_t serial;
} dent;
#define DCACHE 8192
static dent dcache[DCACHE];

static VkDescriptorSet desc_alloc(int n) {
  if (platform_native_profile) {
    vframe *f = F;
    if (!f || n < 0 || n > MAX_SAMP || f->dpool_i > f->n_dpool) {
      logf_("native descriptor allocator state unavailable"); abort();
    }
    /* Main owns descriptor replay. frame_begin resets all of this frame's
     * pools after a new D.serial; same-serial flush_wait does not reset them.
     * Cursor movement within a serial is forward-only. New pool creation also
     * resets counts, including numerical handle reuse after device recreation. */
    static struct {
      vframe *frame;
      uint64_t serial;
      VkDescriptorPool pool;
      uint32_t sets, samplers;
    } budget;
    if (budget.frame != f || budget.serial != D.serial) {
      memset(&budget, 0, sizeof budget);
      budget.frame = f;
      budget.serial = D.serial;
    }
    /* Current device negotiation does not enable KHR_maintenance2. Before
     * physical-device Vulkan 1.1, negative allocation errors may be historical
     * fragmentation codes; that bounded ambiguity is not general OOM recovery. */
    int ambiguous_fragmentation = D.props.apiVersion < VK_API_VERSION_1_1;
    /* Bound actual allocation attempts. Capacity-only rollover does not use an
     * attempt: never probe a full pool on Vulkan 1.0 without maintenance1. */
    for (int attempt = 0; attempt < 8;) {
      if (f->dpool_i == f->n_dpool) {
        VkDescriptorPoolSize sz[2] = { { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 1024 },
                                       { VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 4096 } };
        VkDescriptorPoolCreateInfo ci = { VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
        ci.maxSets = 1024;
        ci.poolSizeCount = 2;
        ci.pPoolSizes = sz;
        VkDescriptorPool pool = VK_NULL_HANDLE;
        VkResult result = vkCreateDescriptorPool(D.dev, &ci, NULL, &pool);
        VKCHECK(result);
        if (result != VK_SUCCESS || !pool) {
          logf_("native descriptor pool unavailable: %d", result); abort();
        }
        GROW(f->dpool, f->n_dpool, f->cap_dpool);
        f->dpool[f->n_dpool++] = pool;
        budget.pool = pool;
        budget.sets = budget.samplers = 0;
      }
      VkDescriptorPool pool = f->dpool[f->dpool_i];
      if (!pool) { logf_("native descriptor pool handle missing"); abort(); }
      if (budget.pool != pool) {
        budget.pool = pool;
        budget.sets = budget.samplers = 0;
      }
      /* Every dsl[n] consumes one UBO and n combined-image samplers. */
      if (budget.sets >= 1024 || (uint32_t)n > 4096 - budget.samplers) {
        ++f->dpool_i;
        budget.pool = VK_NULL_HANDLE;
        budget.sets = budget.samplers = 0;
        continue;
      }
      VkDescriptorSetAllocateInfo ai = { VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
      ai.descriptorPool = f->dpool[f->dpool_i];
      ai.descriptorSetCount = 1;
      ai.pSetLayouts = &dsl[n];
      VkDescriptorSet s = VK_NULL_HANDLE;
      ++attempt;
      VkResult result = vkAllocateDescriptorSets(D.dev, &ai, &s);
      if (result == VK_SUCCESS && s) {
        ++budget.sets;
        budget.samplers += (uint32_t)n;
        return s;
      }
      if (result == VK_ERROR_DEVICE_LOST ||
          (result != VK_ERROR_OUT_OF_POOL_MEMORY && result != VK_ERROR_FRAGMENTED_POOL &&
           !(ambiguous_fragmentation && result < 0))) {
        logf_("native descriptor allocation unavailable: %d", result); abort();
      }
      if (ambiguous_fragmentation && result != VK_ERROR_OUT_OF_POOL_MEMORY && result != VK_ERROR_FRAGMENTED_POOL)
        logf_("native Vulkan 1.0 descriptor allocation ambiguous fragmentation: %d", result);
      ++f->dpool_i;
      budget.pool = VK_NULL_HANDLE;
      budget.sets = budget.samplers = 0;
    }
    logf_("native descriptor allocation made no progress in eight attempts"); abort();
  }
  vframe *f = F;
  for (;;) {
    if (f->dpool_i == f->n_dpool) {
      VkDescriptorPoolSize sz[2] = { { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 1024 },
                                     { VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 4096 } };
      VkDescriptorPoolCreateInfo ci = { VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
      ci.maxSets = 1024;
      ci.poolSizeCount = 2;
      ci.pPoolSizes = sz;
      GROW(f->dpool, f->n_dpool, f->cap_dpool);
      VKCHECK(vkCreateDescriptorPool(D.dev, &ci, NULL, &f->dpool[f->n_dpool++]));
    }
    VkDescriptorSetAllocateInfo ai = { VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
    ai.descriptorPool = f->dpool[f->dpool_i];
    ai.descriptorSetCount = 1;
    ai.pSetLayouts = &dsl[n];
    VkDescriptorSet s;
    if (vkAllocateDescriptorSets(D.dev, &ai, &s) == VK_SUCCESS) return s;
    f->dpool_i++;
  }
}

static VkDescriptorSet desc_get(const dkey *k) {
  uint64_t h = hash_bytes(k, sizeof *k);
  dent *e = &dcache[h & (DCACHE - 1)];
  if (e->serial == D.serial && !memcmp(&e->k, k, sizeof *k)) return e->set;
  VkDescriptorSet s = desc_alloc(k->n);
  VkDescriptorBufferInfo bi = { k->ubo, 0, k->range };
  VkDescriptorImageInfo ii[MAX_SAMP];
  VkWriteDescriptorSet w[MAX_SAMP + 1];
  memset(w, 0, sizeof w);
  for (int i = 0; i <= MAX_SAMP; ++i) w[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
  uint32_t nw = 0;
  if (k->ubo) {
    w[nw].dstSet = s;
    w[nw].dstBinding = 0;
    w[nw].descriptorCount = 1;
    w[nw].descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC;
    w[nw].pBufferInfo = &bi;
    nw++;
  }
  for (int i = 0; i < k->n; ++i) {
    ii[i] = (VkDescriptorImageInfo){ k->s[i], k->v[i], VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL };
    w[nw].dstSet = s;
    w[nw].dstBinding = (uint32_t)i + 1;
    w[nw].descriptorCount = 1;
    w[nw].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    w[nw].pImageInfo = &ii[i];
    nw++;
  }
  vkUpdateDescriptorSets(D.dev, nw, w, 0, NULL);
  e->k = *k;
  e->set = s;
  e->serial = D.serial;
  return s;
}

/* ---- a frame's recording: its operations (passes and blits) and the passes' items ---- */

enum { OP_PASS, OP_BLIT };
typedef struct {
  int kind;
  /* a pass: its attachments (the screen's color stands for the swapchain image acquired at
   * replay), the clear it starts with, what is discarded after it, its items */
  int screen, compat, w, h;
  vimg *color, *depth, *resolve;
  int clear, discard;
  float cc[4];
  size_t first, n;
  /* a blit: its images, rectangles (Vulkan's rows) and what of them */
  vimg *src, *dst;
  int src_screen, dst_screen;
  int s[4], d[4];
  VkImageAspectFlags copy_aspects; /* 0 keeps legacy GL copy projection */
  VkFilter filter;
  int resolve_blit;
} vop;

enum { IT_DRAW, IT_CLEAR };
typedef struct {
  int kind;
  VkPipeline pipe;
  VkPipelineLayout layout;
  VkDescriptorSet set;
  uint32_t dyn;
  int vp[4], sc[4];
  uint32_t sref;
  uint32_t nvb, vb;
  VkBuffer ib;
  VkDeviceSize ibo;
  VkIndexType itype;
  uint32_t count, first, indexed;
  int bits; /* a clear's: GL's */
  float cc[4];
} vitem;

static vop *ops;
static size_t n_ops, cap_ops;
static long cur_pass = -1;
static vitem *items;
static size_t n_items, cap_items;
static VkBuffer *vbb;
static VkDeviceSize *vbo;
static uint32_t *vbs; /* (the binding) */
static size_t n_vb, cap_vb, cap_vbo, cap_vbs;

static vimg SCREEN; /* the screen's color in a pass's record */
static struct {
  VkSurfaceKHR surface;
  VkSwapchainKHR chain;
  vimg **img;
  uint32_t n, cur;
  int acquired, headless, w, h;
  VkFormat fmt;
  vimg *ms, *depth; /* the screen's multisampled color (resolved into the swapchain's), depth */
  int samples;
  int compat; /* the screen's framebuffer kind (-1 without one), for the loading's first draws */
} S = { .compat = -1 };

/* Native metadata is immutable and holds its images independently of public
 * texture/attachment handle lifetime. Never lazily allocate or resolve names. */
static int native_fb_target(const vfbo *f, vop *t) {
  memset(t, 0, sizeof *t); t->kind = OP_PASS;
  if (!f || !f->native) return 0;
  vimg *c = f->native_color, *d = f->native_depth;
  if (!c && !d) return 0;
  if (c && (!c->native_target_refs || !c->img || !c->uid || !c->att || is_depth(c->fmt) || c->layers != 1 || c->levels != 1 ||
            c->aspect != VK_IMAGE_ASPECT_COLOR_BIT || !(c->usage & VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT) || c->native_upload_pending ||
            (c->samples != 1 && c->samples != 2 && c->samples != 4 && c->samples != 8) ||
            (f->color.kind != 1 && f->color.kind != 2) || c->sampled != (f->color.kind == 1) || (c->sampled && (c->samples != 1 || !c->view || c->view_levels != 1 || !(c->usage & VK_IMAGE_USAGE_SAMPLED_BIT))))) return 0;
  if (d && (!d->native_target_refs || !d->img || !d->uid || !d->att || !is_depth(d->fmt) || d->layers != 1 || d->levels != 1 ||
            d->aspect != (VkImageAspectFlags)(VK_IMAGE_ASPECT_DEPTH_BIT | (has_stencil(d->fmt) ? VK_IMAGE_ASPECT_STENCIL_BIT : 0)) ||
            !(d->usage & VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT) || d->native_upload_pending ||
            (d->samples != 1 && d->samples != 2 && d->samples != 4 && d->samples != 8) ||
            (f->depth.kind != 1 && f->depth.kind != 2) || d->sampled != (f->depth.kind == 1) || (d->sampled && (d->samples != 1 || !d->view || d->view_levels != 1 || !(d->usage & VK_IMAGE_USAGE_SAMPLED_BIT))))) return 0;
  if ((!c && f->color.kind) || (!d && (f->depth.kind || f->stencil.kind))) return 0;
  t->color = c; t->depth = d;
  if (f->color.samples) {
    vimg *m = f->ms;
    if (!c || c->samples != 1 || f->color.kind != 1 || !c->view ||
        (f->color.samples != 2 && f->color.samples != 4 && f->color.samples != 8) ||
        !m || !m->img || !m->uid || !m->att || !m->implicit || !m->transient || m->sampled || m->levels != 1 || m->layers != 1 ||
        m->aspect != VK_IMAGE_ASPECT_COLOR_BIT || m->fmt != c->fmt || m->w != c->w || m->h != c->h ||
        m->samples != f->color.samples || m->usage != (VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSIENT_ATTACHMENT_BIT)) return 0;
    t->color = m; t->resolve = c;
  } else if (f->ms) return 0;
  t->w = c ? c->w : d->w; t->h = c ? c->h : d->h;
  if (t->w <= 0 || t->h <= 0 || (c && d && (c->w != d->w || c->h != d->h || t->color->samples != d->samples))) return 0;
  t->compat = native_compat_id(c ? c->fmt : VK_FORMAT_UNDEFINED, d ? d->fmt : VK_FORMAT_UNDEFINED,
                               t->color ? t->color->samples : d->samples, t->resolve != NULL);
  return t->compat >= 0;
}

/* the target of framebuffer name as a pass's (0 if it can't be drawn to) */
static int fb_target(GLuint name, vop *t) {
  memset(t, 0, sizeof *t);
  t->kind = OP_PASS;
  if (!name) {
    if (!S.n) return 0;
    t->screen = 1;
    t->w = S.w, t->h = S.h;
    t->depth = S.depth;
    if (S.ms) t->color = S.ms, t->resolve = &SCREEN;
    else t->color = &SCREEN;
  } else {
    vfbo *f = fbo_get(name);
    if (!f) return 0;
    if (f->native) return native_fb_target(f, t);
    vimg *c = att_image(&f->color), *d = att_image(&f->depth);
    if ((f->color.kind && !c) || (f->depth.kind && !d) || (!c && !d)) return 0;
    if (c && f->color.samples) { /* rendered multisampled into the texture */
      if (!f->ms || f->ms->fmt != c->fmt || f->ms->w != c->w || f->ms->h != c->h || f->ms->samples != f->color.samples) {
        image_drop(f->ms);
        f->ms = image_new(c->fmt, c->w, c->h, 1, 1, f->color.samples, 0, 1, SWZ_ID);
        if (!f->ms) return 0;
        f->ms->implicit = 1;
      }
      t->color = f->ms, t->resolve = c;
    } else {
      t->color = c;
    }
    t->depth = d;
    t->w = c ? c->w : d->w, t->h = c ? c->h : d->h;
    if (d && (d->w < t->w || d->h < t->h)) t->w = d->w < t->w ? d->w : t->w, t->h = d->h < t->h ? d->h : t->h;
    if (c && d && t->color->samples != d->samples) return 0;
  }
  VkFormat cf = t->color ? (t->color == &SCREEN ? S.fmt : t->color->fmt) : VK_FORMAT_UNDEFINED;
  t->compat = compat_id(cf, t->depth ? t->depth->fmt : VK_FORMAT_UNDEFINED, t->color ? t->color->samples : t->depth->samples,
                        t->resolve != NULL);
  return 1;
}

static void close_pass(void) { cur_pass = -1; }

static vop *open_pass(vctx *c) {
  vop t;
  if (!fb_target(c->draw_fb, &t)) return NULL;
  if (cur_pass >= 0) {
    vop *o = &ops[cur_pass];
    if (o->color == t.color && o->depth == t.depth && o->resolve == t.resolve && o->screen == t.screen) return o;
  }
  GROW(ops, n_ops, cap_ops);
  t.first = n_items;
  ops[n_ops] = t;
  cur_pass = (long)n_ops;
  return &ops[n_ops++];
}

static int D_warm_compat = -1; /* the scene's framebuffer kind, for the loading's first draws */
static uint64_t frame_draws;
/* Kept separately: a mixed frame must never be reported as native-complete. */
static uint64_t compat_draw_count;

/* GL's viewport or scissor box as Vulkan's (rows from the top on the screen) */
static void box_vk(const GLint *b, const vop *o, int *out) {
  out[0] = b[0], out[2] = b[2], out[3] = b[3];
  out[1] = o->screen ? o->h - (b[1] + b[3]) : b[1];
}

static uint32_t max_index(const void *idx, GLenum type, int count) {
  uint32_t m = 0;
  if (type == GL_UNSIGNED_SHORT) {
    const uint16_t *p = idx;
    for (int i = 0; i < count; ++i) m = p[i] > m ? p[i] : m;
  } else if (type == GL_UNSIGNED_BYTE) {
    const uint8_t *p = idx;
    for (int i = 0; i < count; ++i) m = p[i] > m ? p[i] : m;
  } else {
    const uint32_t *p = idx;
    for (int i = 0; i < count; ++i) m = p[i] > m ? p[i] : m;
  }
  return m;
}

static VkPrimitiveTopology topology(GLenum mode) {
  switch (mode) {
  case GL_POINTS: return VK_PRIMITIVE_TOPOLOGY_POINT_LIST;
  case GL_LINES: return VK_PRIMITIVE_TOPOLOGY_LINE_LIST;
  case GL_LINE_STRIP: return VK_PRIMITIVE_TOPOLOGY_LINE_STRIP;
  case GL_TRIANGLE_STRIP: return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP;
  case GL_TRIANGLE_FAN: return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_FAN;
  }
  return VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
}

static vimg *dummy2d, *dummycube;
static VkSampler dummy_sampler;

/* the part of a pipeline's key that's GL's state, for drawing into framebuffer kind compat */
static void key_state(pkey *k, const vctx *c, int compat, int screen) {
  const compat_t *cp = &compats[compat];
  k->compat = (uint16_t)compat;
  k->flip = (uint8_t)screen;
  if (cp->cfmt) {
    k->blend = (uint8_t)c->blend;
    if (c->blend) {
      k->bsrc = (uint8_t)blend_factor(c->bsrc), k->bdst = (uint8_t)blend_factor(c->bdst);
      k->beq = (uint8_t)(c->beq == GL_FUNC_SUBTRACT ? VK_BLEND_OP_SUBTRACT
                        : c->beq == GL_FUNC_REVERSE_SUBTRACT ? VK_BLEND_OP_REVERSE_SUBTRACT : VK_BLEND_OP_ADD);
    }
    k->cmask = (uint8_t)c->cmask;
  }
  if (cp->dfmt) {
    k->depth_test = (uint8_t)c->depth_test;
    if (c->depth_test) k->depth_write = (uint8_t)c->depth_write, k->dfunc = (uint8_t)compare_op(c->dfunc);
    if (c->stencil_test && has_stencil(cp->dfmt)) {
      k->stencil = 1;
      k->sfunc = (uint8_t)compare_op(c->sfunc);
      k->sfail = (uint8_t)stencil_op(c->sfail), k->szfail = (uint8_t)stencil_op(c->szfail), k->szpass = (uint8_t)stencil_op(c->szpass);
      k->smask = (uint8_t)c->smask, k->swmask = (uint8_t)c->swmask;
    }
  }
  if (c->cull)
    k->cull = (uint8_t)(c->cull_face == GL_FRONT ? VK_CULL_MODE_FRONT_BIT
                       : c->cull_face == GL_BACK ? VK_CULL_MODE_BACK_BIT : VK_CULL_MODE_FRONT_AND_BACK);
  k->front_ccw = (uint8_t)((c->front == GL_CCW) == !!screen);
}

static void draw(GLenum mode, GLint first, GLsizei count, GLenum itype, const void *indices, int indexed) {
  vctx *c = ctx();
  vprog *p = prog_get(c->prog);
  if (count <= 0) return;
  if (!p || !p->vs || !p->fs || !p->shadow) { set_err(GL_INVALID_OPERATION); return; }
  vvao *vao = cur_vao(c);
  vop *o = NULL;
  int warm = c->loader;
  if (!warm) {
    if (!(o = open_pass(c))) { set_err(GL_INVALID_OPERATION); return; }
    warm = !o->screen && o->w == 1 && o->h == 1; /* the loading's framebuffer of a pixel */
  }
  pkey k;
  memset(&k, 0, sizeof k);
  k.prog = p->uid;
  k.topo = (uint8_t)topology(mode);
  if (!warm) key_state(&k, c, o->compat, o->screen);
  /* the vertices: a buffer's, or the game's own memory copied into the frame's ring (as many
   * as the indices reach), or an attribute's one value */
  VkBuffer vb[MAX_ATTR];
  VkDeviceSize vo[MAX_ATTR];
  uint32_t vbind[MAX_ATTR], nvb = 0;
  long top = -1; /* the highest vertex, once needed */
  const void *idx_mem = NULL;
  VkBuffer ib = VK_NULL_HANDLE;
  VkDeviceSize ibo = 0;
  VkIndexType vit = itype == GL_UNSIGNED_INT ? VK_INDEX_TYPE_UINT32 : VK_INDEX_TYPE_UINT16;
  vbuf *eb = indexed ? buf_get(vao->ebo) : NULL;
  if (indexed) {
    if (eb && eb->m) idx_mem = eb->m->map + (uintptr_t)indices;
    else if (!vao->ebo) idx_mem = indices;
    else return;
  }
  for (uint32_t i = 0; i < MAX_ATTR; ++i) {
    if (!(p->inputs >> i & 1)) continue;
    vattr *a = &vao->a[i];
    int esize = 16, fc = 4;
    if (a->enabled && !(fc = vfmt_code(a->type, a->size, a->norm, &esize))) return;
    k.afmt[i] = (uint8_t)fc;
    if (!a->enabled) { /* the attribute's value, once for all the vertices */
      k.inst |= (uint8_t)(1u << i);
      k.astride[i] = 16;
      if (!warm) {
        uint8_t *m = ring_alloc(&F->vtx, 16, 16, &vb[nvb], &vo[nvb]);
        memcpy(m, c->generic[i], 16);
        vbind[nvb++] = i;
      }
      continue;
    }
    int stride = a->stride ? a->stride : esize;
    k.astride[i] = (uint16_t)stride;
    if (warm) continue;
    if (a->buf) {
      vbuf *b = buf_get(a->buf);
      if (!b || !b->m) return;
      b->m->serial = D.serial;
      vb[nvb] = b->m->buf, vo[nvb] = (uintptr_t)a->ptr;
    } else {
      if (top < 0) top = indexed ? (long)max_index(idx_mem, itype, count) : (long)first + count - 1;
      size_t bytes = (size_t)top * (size_t)stride + (size_t)esize;
      uint8_t *m = ring_alloc(&F->vtx, bytes, 16, &vb[nvb], &vo[nvb]);
      memcpy(m, a->ptr, bytes);
    }
    vbind[nvb++] = i;
  }
  if (warm) { /* for the scene's framebuffer and the screen's, either may draw it */
    int made = 0, sc = S.compat;
    pkey w = k;
    if (D_warm_compat >= 0) key_state(&w, c, D_warm_compat, 0), pipeline_get(&w, p, &made);
    w = k;
    if (sc >= 0) key_state(&w, c, sc, 1), pipeline_get(&w, p, &made);
    return;
  }
  if (indexed) {
    if (eb) {
      eb->m->serial = D.serial;
      ib = eb->m->buf, ibo = (uintptr_t)indices;
    } else if (itype == GL_UNSIGNED_BYTE) {
      uint16_t *m = (uint16_t *)ring_alloc(&F->vtx, (VkDeviceSize)count * 2, 4, &ib, &ibo);
      for (GLsizei i = 0; i < count; ++i) m[i] = ((const uint8_t *)indices)[i];
    } else {
      size_t bytes = (size_t)count * (itype == GL_UNSIGNED_INT ? 4 : 2);
      memcpy(ring_alloc(&F->vtx, bytes, 4, &ib, &ibo), indices, bytes);
    }
    if (eb && itype == GL_UNSIGNED_BYTE) return; /* (not in a buffer here) */
  }
  VkPipeline pl = pipeline_get(&k, p, NULL);
  if (!pl) { set_err(GL_INVALID_OPERATION); return; }
  /* the uniforms (again only when changed) and textures */
  int block = p->block > 16 ? p->block : 16;
  if (p->dirty || p->ubo_serial != D.serial) {
    VkDeviceSize off;
    uint8_t *m = ring_alloc(&F->ubo, (VkDeviceSize)block, D.props.limits.minUniformBufferOffsetAlignment, &p->ubo_buf, &off);
    memcpy(m, p->shadow, (size_t)(p->block > 0 ? p->block : 0));
    p->ubo_off = (uint32_t)off;
    p->ubo_serial = D.serial;
    p->dirty = 0;
  }
  dkey dk;
  memset(&dk, 0, sizeof dk);
  dk.n = p->n_samp;
  dk.ubo = p->ubo_buf;
  dk.range = (uint32_t)block;
  for (int i = 0; i < p->n_samp; ++i) {
    int unit = p->samp_unit[i];
    vtex *t = unit >= 0 && unit < MAX_UNITS ? tex_get(p->samp_cube[i] ? c->texcube[unit] : c->tex2d[unit]) : NULL;
    vimg *im = t ? t->im : NULL;
    if (im && im->view && (im->level_mask & 1) && (im->layers == 6) == p->samp_cube[i]) {
      im->serial = D.serial;
      dk.v[i] = im->view;
      dk.s[i] = sampler_for(t, im->view_levels);
    } else {
      dk.v[i] = p->samp_cube[i] ? dummycube->view : dummy2d->view;
      dk.s[i] = dummy_sampler;
    }
    if (!dk.s[i]) { set_err(GL_INVALID_OPERATION); return; }
  }
  GROW(items, n_items, cap_items);
  vitem *it = &items[n_items++];
  memset(it, 0, sizeof *it);
  it->kind = IT_DRAW;
  it->pipe = pl;
  it->layout = playout[p->n_samp];
  it->set = desc_get(&dk);
  it->dyn = p->ubo_off;
  box_vk(c->vp, o, it->vp);
  if (c->scissor_test) {
    box_vk(c->sc, o, it->sc);
  } else {
    it->sc[0] = it->sc[1] = 0, it->sc[2] = o->w, it->sc[3] = o->h;
  }
  it->sref = (uint32_t)c->sref;
  it->vb = (uint32_t)n_vb;
  it->nvb = nvb;
  for (uint32_t i = 0; i < nvb; ++i) {
    if (n_vb >= cap_vb) {
      size_t cap = cap_vb ? cap_vb * 2 : 256;
      vbb = realloc(vbb, cap * sizeof *vbb), vbo = realloc(vbo, cap * sizeof *vbo), vbs = realloc(vbs, cap * sizeof *vbs);
      if (!vbb || !vbo || !vbs) abort();
      cap_vb = cap_vbo = cap_vbs = cap;
    }
    vbb[n_vb] = vb[i], vbo[n_vb] = vo[i], vbs[n_vb] = vbind[i];
    n_vb++;
  }
  it->indexed = (uint32_t)indexed;
  it->ib = ib, it->ibo = ibo, it->itype = vit;
  it->count = (uint32_t)count;
  it->first = (uint32_t)first;
  o->n = n_items - o->first;
  frame_draws++;
  __atomic_add_fetch(&compat_draw_count, 1, __ATOMIC_RELAXED);
}

/* Independent packet entry, reusing only the low-level Vulkan executor. */
#include "native_vk.inc"
#include "native_vk_upload.inc"
#include "native_vk_resources.inc"
#include "native_vk_objects.inc"
#include "native_vk_images.inc"
#include "native_vk_mipmap.inc"
#include "native_vk_targets.inc"

void vkgl_glDrawArrays(GLenum mode, GLint first, GLsizei count) { draw(mode, first, count, 0, NULL, 0); }
void vkgl_glDrawElements(GLenum mode, GLsizei count, GLenum type, const void *indices) {
  draw(mode, 0, count, type, indices, 1);
}

void vkgl_glClear(GLbitfield mask) {
  vctx *c = ctx();
  if (c->loader) return;
  vop *o = open_pass(c);
  if (!o) return;
  int bits = 0;
  if ((mask & GL_COLOR_BUFFER_BIT) && c->cmask && o->color) bits |= GL_COLOR_BUFFER_BIT;
  if ((mask & GL_DEPTH_BUFFER_BIT) && c->depth_write && o->depth) bits |= GL_DEPTH_BUFFER_BIT;
  if ((mask & GL_STENCIL_BUFFER_BIT) && (c->swmask & 0xff) && o->depth && has_stencil(o->depth->fmt))
    bits |= GL_STENCIL_BUFFER_BIT;
  if (!bits) return;
  int full = !c->scissor_test || (c->sc[0] <= 0 && c->sc[1] <= 0 && c->sc[0] + c->sc[2] >= o->w && c->sc[1] + c->sc[3] >= o->h);
  if (o->n == 0 && full) { /* the pass starts with it */
    o->clear |= bits;
    if (bits & GL_COLOR_BUFFER_BIT) memcpy(o->cc, c->clear, sizeof o->cc);
    return;
  }
  GROW(items, n_items, cap_items);
  vitem *it = &items[n_items++];
  memset(it, 0, sizeof *it);
  it->kind = IT_CLEAR;
  it->bits = bits;
  memcpy(it->cc, c->clear, sizeof it->cc);
  if (c->scissor_test) box_vk(c->sc, o, it->sc);
  else it->sc[2] = o->w, it->sc[3] = o->h;
  o->n = n_items - o->first;
}

/* GL's discard (and invalidate): the attachments of the last pass on the framebuffer are not
 * stored, if nothing else came after it */
static void discard(GLenum target, GLsizei n, const GLenum *att) {
  vctx *c = ctx();
  if (c->loader || (target != GL_FRAMEBUFFER && target != GL_DRAW_FRAMEBUFFER_)) return;
  vop t;
  if (!fb_target(c->draw_fb, &t) || !n_ops) return;
  vop *o = &ops[n_ops - 1];
  if (o->kind != OP_PASS || o->color != t.color || o->depth != t.depth || o->screen != t.screen) return;
  for (GLsizei i = 0; i < n; ++i) {
    GLenum a = att[i];
    if (a == GL_COLOR_ATTACHMENT0 || a == GL_COLOR_) o->discard |= GL_COLOR_BUFFER_BIT;
    if (a == GL_DEPTH_ATTACHMENT || a == GL_DEPTH_ || a == GL_DEPTH_STENCIL_ATTACHMENT_) o->discard |= GL_DEPTH_BUFFER_BIT;
    if (a == GL_STENCIL_ATTACHMENT || a == GL_STENCIL_ || a == GL_DEPTH_STENCIL_ATTACHMENT_) o->discard |= GL_STENCIL_BUFFER_BIT;
  }
  close_pass();
}
void vkgl_glDiscardFramebufferEXT(GLenum target, GLsizei n, const GLenum *att) { discard(target, n, att); }
void vkgl_glInvalidateFramebuffer(GLenum target, GLsizei n, const GLenum *att) { discard(target, n, att); }

void vkgl_glBlitFramebuffer(GLint sx0, GLint sy0, GLint sx1, GLint sy1, GLint dx0, GLint dy0, GLint dx1, GLint dy1,
                            GLbitfield mask, GLenum filter) {
  vctx *c = ctx();
  if (c->loader) return;
  vop s, d;
  if (!fb_target(c->read_fb, &s) || !fb_target(c->draw_fb, &d)) {
    set_err(GL_INVALID_OPERATION);
    return;
  }
  close_pass();
  for (int depth = 0; depth < 2; ++depth) {
    if (!(mask & (depth ? GL_DEPTH_BUFFER_BIT : GL_COLOR_BUFFER_BIT))) continue;
    vop b;
    memset(&b, 0, sizeof b);
    b.kind = OP_BLIT;
    if (depth) {
      b.src = s.depth, b.dst = d.depth;
    } else {
      /* a multisampled source read resolved (the screen's: the swapchain image after its pass) */
      b.src = s.resolve ? s.resolve : s.color;
      b.dst = d.resolve ? d.resolve : d.color;
      b.src_screen = b.src == &SCREEN, b.dst_screen = b.dst == &SCREEN;
    }
    if (!b.src || !b.dst || (depth && b.src->samples != b.dst->samples)) {
      set_err(GL_INVALID_OPERATION);
      continue;
    }
    b.resolve_blit = b.src->samples > 1;
    int sh = s.h, dh = d.h;
    b.s[0] = sx0, b.s[2] = sx1, b.s[1] = s.screen ? sh - sy0 : sy0, b.s[3] = s.screen ? sh - sy1 : sy1;
    b.d[0] = dx0, b.d[2] = dx1, b.d[1] = d.screen ? dh - dy0 : dy0, b.d[3] = d.screen ? dh - dy1 : dy1;
    b.filter = filter == GL_LINEAR && !depth ? VK_FILTER_LINEAR : VK_FILTER_NEAREST;
    GROW(ops, n_ops, cap_ops);
    ops[n_ops++] = b;
  }
}

/* ---- replay: the frame's operations into a command buffer, each attachment loaded and
 * stored only as what comes after needs ---- */

static int S_waited, S_out_of_date;
/* A frame fence does not prove WSI has consumed a presentation wait. Native
 * presentation semaphores belong to swapchain images, reused only after that
 * image is acquired again and the submit waits its acquire semaphore. */
static VkSemaphore *native_present_wait;
static uint32_t native_present_count;
#include "native_vk_present.inc"
static VkSemaphore backend_render_semaphore(void) {
  if (!platform_native_profile) return F->render_done;
  if (!native_present_wait || S.cur >= native_present_count || !native_present_wait[S.cur]) {
    logf_("missing native presentation semaphore"); abort();
  }
  return native_present_wait[S.cur];
}

static vimg *real(vimg *im) { return im == &SCREEN ? (S.acquired ? S.img[S.cur] : NULL) : im; }

static int acquire(void) {
  if (S.acquired) return 1;
  if (platform_native_profile && (!D.dev || !F || !S.img || S.w <= 0 || S.h <= 0 || (!S.headless && !S.chain))) return 0;
  if (!S.n) return 0;
  if (S.headless) {
    S.cur = 0;
    S.acquired = 1;
    return 1;
  }
  VkResult r = vkAcquireNextImageKHR(D.dev, S.chain, UINT64_MAX, F->acquire, VK_NULL_HANDLE, &S.cur);
  if (r != VK_SUCCESS && r != VK_SUBOPTIMAL_KHR) {
    if (platform_native_profile && r != VK_ERROR_OUT_OF_DATE_KHR && r != VK_ERROR_SURFACE_LOST_KHR) {
      logf_("native acquire unavailable: %d", r); abort();
    }
    S_out_of_date = 1;
    return 0;
  }
  /* (suboptimal goes on: Android says so of a swapchain not turned as the screen is, which the
   * compositor turns, as it did GL's) */
  if (platform_native_profile && S.cur >= S.n) { logf_("invalid acquired image index"); abort(); }
  native_present_image_reuse(S.cur);
  /* SUBOPTIMAL acquired a usable image; persistent Android rotation must not
   * invalidate the surface every frame. Real acquire errors above stay stale. */
  S.acquired = 1;
  S_waited = 0;
  S.img[S.cur]->in_rest = 0;
  S.img[S.cur]->defined = 0;
  return 1;
}

static int op_uses(const vop *o, const vimg *im) {
  if (o->kind == OP_PASS) return o->color == im || o->depth == im || o->resolve == im;
  return o->src == im || o->dst == im;
}

/* whether pass i's im (aspect bits: GL's) must be stored */
static int must_store(size_t i, vimg *im, int bits, int final) {
  const vop *o = &ops[i];
  if (o->discard & bits) return 0;
  if (im == &SCREEN || im->sampled || im->swapchain || (S.headless && im == S.img[0])) return 1;
  for (size_t j = i + 1; j < n_ops; ++j) {
    const vop *n = &ops[j];
    if (!op_uses(n, im)) continue;
    if (n->kind == OP_BLIT) return 1;
    if (n->n == 0 && !n->clear) continue; /* (a pass with nothing in it is not replayed) */
    if (n->resolve == im) return 0; /* (written whole by the resolve) */
    int need = bits;
    if (im == n->depth && !has_stencil(im->fmt)) need &= ~GL_STENCIL_BUFFER_BIT;
    return (n->clear & need) != need;
  }
  if (!final) return 1; /* (the frame goes on after a glFinish: it may load it) */
  return !im->implicit;
}

static void replay_pass(VkCommandBuffer cmd, size_t i, int final) {
  vop *o = &ops[i];
  if (o->n == 0 && !o->clear) return;
  if ((o->screen || o->color == &SCREEN) && !acquire()) return;
  vimg *col = real(o->color), *res = real(o->resolve), *dep = o->depth;
  compat_t *cp = &compats[o->compat];
  rp_t r;
  memset(&r, 0, sizeof r);
  r.compat = o->compat;
  int cstore = 0, dstore = 0, sstore = 0;
  if (col) {
    r.cload = (uint8_t)(o->clear & GL_COLOR_BUFFER_BIT ? VK_ATTACHMENT_LOAD_OP_CLEAR
                        : col->defined ? VK_ATTACHMENT_LOAD_OP_LOAD : VK_ATTACHMENT_LOAD_OP_DONT_CARE);
    r.cundef = r.cload != VK_ATTACHMENT_LOAD_OP_LOAD || !col->in_rest;
    cstore = must_store(i, o->color, GL_COLOR_BUFFER_BIT, final);
    r.cstore = (uint8_t)(cstore ? VK_ATTACHMENT_STORE_OP_STORE : VK_ATTACHMENT_STORE_OP_DONT_CARE);
    r.crest = col->rest;
  }
  if (dep) {
    int st = has_stencil(dep->fmt);
    r.dload = (uint8_t)(o->clear & GL_DEPTH_BUFFER_BIT ? VK_ATTACHMENT_LOAD_OP_CLEAR
                        : dep->defined ? VK_ATTACHMENT_LOAD_OP_LOAD : VK_ATTACHMENT_LOAD_OP_DONT_CARE);
    r.sload = (uint8_t)(!st ? VK_ATTACHMENT_LOAD_OP_DONT_CARE
                        : o->clear & GL_STENCIL_BUFFER_BIT ? VK_ATTACHMENT_LOAD_OP_CLEAR
                        : dep->defined ? VK_ATTACHMENT_LOAD_OP_LOAD : VK_ATTACHMENT_LOAD_OP_DONT_CARE);
    r.dundef = (r.dload != VK_ATTACHMENT_LOAD_OP_LOAD && r.sload != VK_ATTACHMENT_LOAD_OP_LOAD) || !dep->in_rest;
    dstore = must_store(i, dep, GL_DEPTH_BUFFER_BIT, final);
    sstore = st && must_store(i, dep, GL_STENCIL_BUFFER_BIT, final);
    r.dstore = (uint8_t)(dstore ? VK_ATTACHMENT_STORE_OP_STORE : VK_ATTACHMENT_STORE_OP_DONT_CARE);
    r.sstore = (uint8_t)(sstore ? VK_ATTACHMENT_STORE_OP_STORE : VK_ATTACHMENT_STORE_OP_DONT_CARE);
    r.drest = dep->rest;
  }
  if (res) r.rrest = res->rest;
  VkRenderPass rp = rp_get(&r);
  VkImageView v[3];
  int nv = 0;
  if (col) v[nv++] = col->att;
  if (dep) v[nv++] = dep->att;
  if (res) v[nv++] = res->att;
  VkFramebuffer fb = fb_get(o->compat, v, nv, o->w, o->h);
  VkClearValue cv[3];
  memset(cv, 0, sizeof cv);
  nv = 0;
  if (col) memcpy(cv[nv++].color.float32, o->cc, sizeof o->cc);
  if (dep) cv[nv].depthStencil.depth = 1.0f, cv[nv++].depthStencil.stencil = 0;
  VkRenderPassBeginInfo bi = { VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO };
  bi.renderPass = rp;
  bi.framebuffer = fb;
  bi.renderArea.extent = (VkExtent2D){ (uint32_t)o->w, (uint32_t)o->h };
  bi.clearValueCount = (uint32_t)nv + (res ? 1 : 0);
  bi.pClearValues = cv;
  vkCmdBeginRenderPass(cmd, &bi, VK_SUBPASS_CONTENTS_INLINE);
  VkPipeline lp = VK_NULL_HANDLE;
  VkDescriptorSet ls = VK_NULL_HANDLE;
  uint32_t ldyn = ~0u, lref = ~0u;
  int lvp[4] = { -1, -1, -1, -1 }, lsc[4] = { -1, -1, -1, -1 };
  VkBuffer lib = VK_NULL_HANDLE;
  VkDeviceSize libo = ~0ull;
  VkBuffer lvb[MAX_ATTR];
  VkDeviceSize lvo[MAX_ATTR];
  memset(lvb, 0, sizeof lvb);
  for (size_t k = o->first; k < o->first + o->n; ++k) {
    vitem *it = &items[k];
    int sc[4];
    sc[0] = it->sc[0] > 0 ? it->sc[0] : 0;
    sc[1] = it->sc[1] > 0 ? it->sc[1] : 0;
    sc[2] = (it->sc[0] + it->sc[2] < o->w ? it->sc[0] + it->sc[2] : o->w) - sc[0];
    sc[3] = (it->sc[1] + it->sc[3] < o->h ? it->sc[1] + it->sc[3] : o->h) - sc[1];
    if (sc[2] <= 0 || sc[3] <= 0) continue;
    if (it->kind == IT_CLEAR) {
      VkClearAttachment ca[2];
      uint32_t n = 0;
      if (it->bits & GL_COLOR_BUFFER_BIT) {
        ca[n].aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, ca[n].colorAttachment = 0;
        memcpy(ca[n++].clearValue.color.float32, it->cc, sizeof it->cc);
      }
      if (it->bits & (GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)) {
        ca[n].aspectMask = (it->bits & GL_DEPTH_BUFFER_BIT ? VK_IMAGE_ASPECT_DEPTH_BIT : 0) |
                           (it->bits & GL_STENCIL_BUFFER_BIT ? VK_IMAGE_ASPECT_STENCIL_BIT : 0);
        ca[n].colorAttachment = 0;
        ca[n].clearValue.depthStencil.depth = 1.0f, ca[n++].clearValue.depthStencil.stencil = 0;
      }
      VkClearRect cr = { { { sc[0], sc[1] }, { (uint32_t)sc[2], (uint32_t)sc[3] } }, 0, 1 };
      vkCmdClearAttachments(cmd, n, ca, 1, &cr);
      continue;
    }
    if (it->vp[2] <= 0 || it->vp[3] <= 0) continue;
    if (it->pipe != lp) vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, lp = it->pipe);
    if (memcmp(it->vp, lvp, sizeof lvp)) {
      VkViewport vp = { (float)it->vp[0], (float)it->vp[1], (float)it->vp[2], (float)it->vp[3], 0.0f, 1.0f };
      vkCmdSetViewport(cmd, 0, 1, &vp);
      memcpy(lvp, it->vp, sizeof lvp);
    }
    if (memcmp(sc, lsc, sizeof lsc)) {
      VkRect2D rc = { { sc[0], sc[1] }, { (uint32_t)sc[2], (uint32_t)sc[3] } };
      vkCmdSetScissor(cmd, 0, 1, &rc);
      memcpy(lsc, sc, sizeof lsc);
    }
    if (it->sref != lref) vkCmdSetStencilReference(cmd, VK_STENCIL_FACE_FRONT_AND_BACK, lref = it->sref);
    if (it->set != ls || it->dyn != ldyn) {
      vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, it->layout, 0, 1, &it->set, 1, &it->dyn);
      ls = it->set, ldyn = it->dyn;
    }
    for (uint32_t j = 0; j < it->nvb; ++j) {
      uint32_t b = vbs[it->vb + j];
      if (lvb[b] == vbb[it->vb + j] && lvo[b] == vbo[it->vb + j]) continue;
      vkCmdBindVertexBuffers(cmd, b, 1, &vbb[it->vb + j], &vbo[it->vb + j]);
      lvb[b] = vbb[it->vb + j], lvo[b] = vbo[it->vb + j];
    }
    if (it->indexed) {
      if (it->ib != lib || it->ibo != libo) {
        vkCmdBindIndexBuffer(cmd, it->ib, it->ibo, it->itype);
        lib = it->ib, libo = it->ibo;
      }
      vkCmdDrawIndexed(cmd, it->count, 1, 0, 0, 0);
    } else {
      vkCmdDraw(cmd, it->count, 1, it->first, 0);
    }
  }
  vkCmdEndRenderPass(cmd);
  if (col) col->in_rest = 1, col->defined = cstore, col->serial = D.serial;
  if (dep) dep->in_rest = 1, dep->defined = dstore || sstore, dep->serial = D.serial;
  if (res) res->in_rest = 1, res->defined = 1, res->serial = D.serial;
  (void)cp;
}

static void replay_blit(VkCommandBuffer cmd, vop *o) {
  if ((o->src_screen || o->dst_screen) && !acquire()) return;
  vimg *s = real(o->src), *d = real(o->dst);
  VkImageLayout sl = s->in_rest ? s->rest : VK_IMAGE_LAYOUT_UNDEFINED, dl = d->in_rest ? d->rest : VK_IMAGE_LAYOUT_UNDEFINED;
  barrier(cmd, s, 0, 1, 0, 1, sl, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
  barrier(cmd, d, 0, 1, 0, 1, dl, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
  VkImageAspectFlags a = o->copy_aspects ? o->copy_aspects : is_depth(s->fmt) ? s->aspect & d->aspect : VK_IMAGE_ASPECT_COLOR_BIT;
  if (o->resolve_blit) {
    int x = o->s[0] < o->s[2] ? o->s[0] : o->s[2], y = o->s[1] < o->s[3] ? o->s[1] : o->s[3];
    int w = abs(o->s[2] - o->s[0]), h = abs(o->s[3] - o->s[1]);
    int dx = o->d[0] < o->d[2] ? o->d[0] : o->d[2], dy = o->d[1] < o->d[3] ? o->d[1] : o->d[3];
    VkImageResolve r = { { a, 0, 0, 1 }, { x, y, 0 }, { a, 0, 0, 1 }, { dx, dy, 0 }, { (uint32_t)w, (uint32_t)h, 1 } };
    vkCmdResolveImage(cmd, s->img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, d->img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &r);
  } else {
    VkImageBlit b = { { a, 0, 0, 1 }, { { o->s[0], o->s[1], 0 }, { o->s[2], o->s[3], 1 } },
                      { a, 0, 0, 1 }, { { o->d[0], o->d[1], 0 }, { o->d[2], o->d[3], 1 } } };
    vkCmdBlitImage(cmd, s->img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, d->img, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &b,
                   o->filter);
  }
  barrier(cmd, s, 0, 1, 0, 1, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, s->rest);
  barrier(cmd, d, 0, 1, 0, 1, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, d->rest);
  s->in_rest = d->in_rest = 1;
  d->defined = 1;
  s->serial = d->serial = D.serial;
}

static void replay(VkCommandBuffer cmd, int final) {
  size_t best = 0;
  for (size_t i = 0; i < n_ops; ++i) {
    vop *o = &ops[i];
    if (o->kind == OP_BLIT) {
      replay_blit(cmd, o);
      continue;
    }
    replay_pass(cmd, i, final);
    /* the scene's kind: the most drawn pass with depth that isn't the screen's */
    if (!o->screen && o->depth && o->color && o->n > best && o->w > 1) {
      best = o->n;
      D_warm_compat = o->compat;
    }
  }
}

/* ---- frames ---- */

static void frame_begin(void) {
  F = &FR[D.serial % FRAMES];
  if (F->submitted) {
    PLATFORM_CHECK(vkWaitForFences(D.dev, 1, &F->fence, VK_TRUE, UINT64_MAX));
    PLATFORM_CHECK(vkResetFences(D.dev, 1, &F->fence));
    F->submitted = 0;
  }
  if (D.serial > FRAMES && D.done < D.serial - FRAMES) __atomic_store_n(&D.done, D.serial - FRAMES, __ATOMIC_RELEASE);
  dead_free(done_serial());
  PLATFORM_CHECK(vkResetCommandPool(D.dev, F->pool, 0));
  PLATFORM_CHECK(vkResetCommandPool(D.dev, F->up.pool, 0));
  F->open = F->up.open = 0;
  ring_reset(&F->up.stage);
  ring_reset(&F->ubo);
  ring_reset(&F->vtx);
  for (size_t i = 0; i < F->n_dpool; ++i) PLATFORM_CHECK(vkResetDescriptorPool(D.dev, F->dpool[i], 0));
  F->dpool_i = 0;
}

/* the frame so far to the GPU (and, at its end, the screen's image handed on) */
static void flush(int final, int present) {
  close_pass();
  VkCommandBuffer cmds[2];
  uint32_t n = 0;
  if (F->up.open) {
    PLATFORM_CHECK(vkEndCommandBuffer(F->up.cmd));
    F->up.open = 0;
    cmds[n++] = F->up.cmd;
  }
  VkCommandBufferBeginInfo bi = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO };
  bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
  PLATFORM_CHECK(vkBeginCommandBuffer(F->cmd, &bi));
  replay(F->cmd, final);
  PLATFORM_CHECK(vkEndCommandBuffer(F->cmd));
  cmds[n++] = F->cmd;
  VkSemaphore wait = VK_NULL_HANDLE, signal = VK_NULL_HANDLE;
  if (S.acquired && !S.headless && !S_waited) wait = F->acquire, S_waited = 1;
  if (present && S.acquired && !S.headless) signal = backend_render_semaphore();
  VkResult queued = submit(cmds, n, wait, signal, F->fence);
  if (platform_native_profile && queued != VK_SUCCESS) abort();
  F->submitted = 1;
  n_ops = n_items = n_vb = 0;
}

/* (a glFinish, a glReadPixels: all of it done before going on) */
static void flush_wait(void) {
  flush(0, 0);
  PLATFORM_CHECK(vkWaitForFences(D.dev, 1, &F->fence, VK_TRUE, UINT64_MAX));
  PLATFORM_CHECK(vkResetFences(D.dev, 1, &F->fence));
  F->submitted = 0;
  if (D.done < D.serial - 1) __atomic_store_n(&D.done, D.serial - 1, __ATOMIC_RELEASE);
  PLATFORM_CHECK(vkResetCommandPool(D.dev, F->pool, 0));
  PLATFORM_CHECK(vkResetCommandPool(D.dev, F->up.pool, 0));
  ring_reset(&F->up.stage);
}

/* Native stream ownership is explicit and independent of compatibility ctx().
 * Main submission/fence error handling retains the shared process-fatal policy;
 * loader_flush already reports unknown completion by preserving its leases. */
int cinder_vk_flush(void) {
  if (!D.dev || native_loader_failed || cinder_vk_error_epoch() == UINT64_MAX) return native_reject();
  if (native_upload_stream == CINDER_VK_UPLOAD_LOADER) {
    loader_flush();
    return !native_loader_failed;
  }
  if (native_upload_stream != CINDER_VK_UPLOAD_FRAME || !F) return native_reject();
  return 1; /* main commands are submitted at presentation or explicit finish */
}
int cinder_vk_finish(void) {
  if (!D.dev || native_loader_failed || cinder_vk_error_epoch() == UINT64_MAX) return native_reject();
  if (native_upload_stream == CINDER_VK_UPLOAD_LOADER) {
    loader_flush();
    return !native_loader_failed;
  }
  if (native_upload_stream != CINDER_VK_UPLOAD_FRAME || !F) return native_reject();
  flush_wait();
  return 1;
}
int cinder_vk_error_pending(void) {
  return native_loader_failed || cinder_vk_error_epoch() == UINT64_MAX;
}

static int backend_present(void) {
  flush(1, 1);
  int r = 0;
  if (S.acquired && !S.headless) {
    VkPresentInfoKHR pi = { VK_STRUCTURE_TYPE_PRESENT_INFO_KHR };
    pi.waitSemaphoreCount = 1;
    VkSemaphore render_done = backend_render_semaphore();
    pi.pWaitSemaphores = &render_done;
    pi.swapchainCount = 1;
    pi.pSwapchains = &S.chain;
    pi.pImageIndices = &S.cur;
    VkSwapchainPresentFenceInfoEXT fence_info;
    VkResult image_result = (VkResult)INT32_MIN;
    int fenced = native_present_attach(&pi, &fence_info, &image_result);
    pthread_mutex_lock(&D.qlock);
    VkResult pr = vkQueuePresentKHR(D.q, &pi);
    pthread_mutex_unlock(&D.qlock);
    if (fenced) native_present_result(pr, image_result);
    if (platform_native_profile && pr != VK_SUCCESS && pr != VK_SUBOPTIMAL_KHR &&
        pr != VK_ERROR_OUT_OF_DATE_KHR && pr != VK_ERROR_SURFACE_LOST_KHR) {
      logf_("native present unavailable: %d", pr); abort();
    }
    if (pr == VK_ERROR_OUT_OF_DATE_KHR) r = 1;
    else if (pr != VK_SUCCESS && pr != VK_SUBOPTIMAL_KHR) r = -1;
  }
  if (S_out_of_date) r = r ? r : 1, S_out_of_date = 0;
  S.acquired = 0;
  S_waited = 0;
  D.serial++;
  frame_begin();
  return r;
}

int vkgl_present(void) { return backend_present(); }

/* ---- the screen ---- */

static void screen_free(void) {
  /* PRESENT fences, not submission fences/device idle, authorize strict WSI
   * resource retirement. Complete all pending presentations before any view,
   * swapchain, semaphore or surface owner can be destroyed. */
  native_present_retire_all();
  VkResult idle = vkDeviceWaitIdle(D.dev);
  if (platform_native_profile && idle != VK_SUCCESS) { logf_("surface wait idle failed: %d", idle); abort(); }
  for (uint32_t i = 0; i < S.n; ++i) {
    if (S.img[i]->att) fb_cache_forget(S.img[i]->att);
    if (S.img[i]->swapchain) {
      vkDestroyImageView(D.dev, S.img[i]->att, NULL);
      free(S.img[i]);
    } else {
      fb_cache_forget(S.img[i]->att);
      image_free_now(S.img[i]);
    }
  }
  free(S.img);
  S.img = NULL;
  S.n = 0;
  S.compat = -1;
  if (S.ms) fb_cache_forget(S.ms->att), image_free_now(S.ms), S.ms = NULL;
  if (S.depth) fb_cache_forget(S.depth->att), image_free_now(S.depth), S.depth = NULL;
  S.acquired = 0;
}

void vkgl_screen_size(int *w, int *h) { *w = S.w, *h = S.h; }

static int backend_surface(VkSurfaceKHR surface, int w, int h, int strict, int (*screen_target)(vop *)) {
  if (n_ops) flush_wait(); /* (what was drawn for the old one) */
  VkSwapchainKHR old = S.chain;
  screen_free();
  S.headless = !surface;
  S.chain = VK_NULL_HANDLE;
  if (S.surface && S.surface != surface) {
    if (old) vkDestroySwapchainKHR(D.dev, old, NULL), old = VK_NULL_HANDLE;
    vkDestroySurfaceKHR(D.inst, S.surface, NULL);
  }
  S.surface = surface;
  if (!surface) {
    S.fmt = VK_FORMAT_R8G8B8A8_UNORM;
    S.img = xcalloc(1, sizeof *S.img);
    S.img[0] = image_new(S.fmt, w, h, 1, 1, 1, 0, 0, SWZ_ID);
    if (!S.img[0]) return -1;
    S.n = 1;
    S.samples = getenv("VKGL_SCREEN_MSAA") ? atoi(getenv("VKGL_SCREEN_MSAA")) : 1;
  } else {
    VkBool32 ok = VK_FALSE;
    VkResult support = vkGetPhysicalDeviceSurfaceSupportKHR(D.pd, D.qfam, surface, &ok);
    if (strict && support != VK_SUCCESS) return -1;
    if (!ok) {
      logf_("the queue can't present to this surface");
      return -1;
    }
    VkSurfaceCapabilitiesKHR caps;
    VkResult capability = vkGetPhysicalDeviceSurfaceCapabilitiesKHR(D.pd, surface, &caps);
    VKCHECK(capability);
    if (strict && capability != VK_SUCCESS) return -1;
    uint32_t nf = 0;
    VkResult formats = vkGetPhysicalDeviceSurfaceFormatsKHR(D.pd, surface, &nf, NULL);
    if (strict && (formats != VK_SUCCESS || !nf || nf > 65536)) return -1;
    uint32_t format_capacity = nf;
    VkSurfaceFormatKHR *fs = xcalloc(nf, sizeof *fs);
    formats = vkGetPhysicalDeviceSurfaceFormatsKHR(D.pd, surface, &nf, fs);
    if (strict && (formats != VK_SUCCESS || !nf || nf > format_capacity)) { free(fs); return -1; }
    VkSurfaceFormatKHR sf = fs[0];
    for (uint32_t i = 0; i < nf; ++i)
      if (fs[i].format == VK_FORMAT_R8G8B8A8_UNORM || (fs[i].format == VK_FORMAT_B8G8R8A8_UNORM && sf.format != VK_FORMAT_R8G8B8A8_UNORM))
        sf = fs[i];
    free(fs);
    if (caps.currentExtent.width != 0xffffffffu) w = (int)caps.currentExtent.width, h = (int)caps.currentExtent.height;
    if (strict) {
      if (w <= 0 || h <= 0 || !(caps.supportedUsageFlags & VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT)) return -1;
      if (caps.currentExtent.width == UINT32_MAX) {
        if ((uint32_t)w < caps.minImageExtent.width) w = (int)caps.minImageExtent.width;
        if ((uint32_t)h < caps.minImageExtent.height) h = (int)caps.minImageExtent.height;
        if ((uint32_t)w > caps.maxImageExtent.width) w = (int)caps.maxImageExtent.width;
        if ((uint32_t)h > caps.maxImageExtent.height) h = (int)caps.maxImageExtent.height;
      }
      if (w <= 0 || h <= 0 || (uint32_t)w > D.props.limits.maxImageDimension2D ||
          (uint32_t)h > D.props.limits.maxImageDimension2D) return -1;
    }
    uint32_t count = caps.minImageCount < 3 ? 3 : caps.minImageCount;
    if (caps.maxImageCount && count > caps.maxImageCount) count = caps.maxImageCount;
    VkSwapchainCreateInfoKHR ci = { VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR };
    ci.surface = surface;
    ci.minImageCount = count;
    ci.imageFormat = sf.format;
    ci.imageColorSpace = sf.colorSpace;
    ci.imageExtent = (VkExtent2D){ (uint32_t)w, (uint32_t)h };
    ci.imageArrayLayers = 1;
    ci.imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT |
                    (caps.supportedUsageFlags & (VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT));
    ci.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
    ci.preTransform = caps.supportedTransforms & VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR ? VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR
                                                                                        : caps.currentTransform;
    ci.compositeAlpha = caps.supportedCompositeAlpha & VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR ? VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR
                        : caps.supportedCompositeAlpha & VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR ? VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR
                                                                                           : VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR;
    ci.presentMode = VK_PRESENT_MODE_FIFO_KHR;
    ci.clipped = VK_TRUE;
    ci.oldSwapchain = old;
    VkResult r = vkCreateSwapchainKHR(D.dev, &ci, NULL, &S.chain);
    if (old) vkDestroySwapchainKHR(D.dev, old, NULL);
    if (r != VK_SUCCESS) {
      logf_("no swapchain: %d", r);
      S.chain = VK_NULL_HANDLE;
      return -1;
    }
    S.fmt = sf.format;
    uint32_t n = 0;
    VkResult images = vkGetSwapchainImagesKHR(D.dev, S.chain, &n, NULL);
    if (strict && (images != VK_SUCCESS || !n || n > 65536)) return -1;
    uint32_t image_capacity = n;
    VkImage *imgs = xcalloc(n, sizeof *imgs);
    images = vkGetSwapchainImagesKHR(D.dev, S.chain, &n, imgs);
    if (strict && (images != VK_SUCCESS || !n || n > image_capacity)) { free(imgs); return -1; }
    S.img = xcalloc(n, sizeof *S.img);
    for (uint32_t i = 0; i < n; ++i) {
      vimg *im = xcalloc(1, sizeof *im);
      im->img = imgs[i];
      im->mem.block = -1;
      im->fmt = S.fmt, im->w = w, im->h = h, im->levels = im->layers = im->samples = 1;
      im->aspect = VK_IMAGE_ASPECT_COLOR_BIT;
      im->usage = ci.imageUsage;
      im->swz = SWZ_ID;
      im->rest = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
      im->swapchain = 1;
      im->uid = resource_uid_next();
      if (!im->uid) { S.n = i; free(im); free(imgs); screen_free(); return -1; }
      if (strict) {
        /* Constructor failure is recoverable; do not enter the deep/live
         * view_new fatal boundary or publish an undefined error output. */
        S.img[i] = im; S.n = i + 1;
        VkImageView attachment = VK_NULL_HANDLE;
        if (view_try(im, 0, 1, &attachment) != VK_SUCCESS || !attachment) { free(imgs); return -1; }
        im->att = attachment;
      } else {
        im->att = view_new(im, 0, 1);
        S.img[i] = im;
      }
    }
    free(imgs);
    S.n = n;
    S.samples = getenv("VKGL_SCREEN_MSAA") ? atoi(getenv("VKGL_SCREEN_MSAA")) : 4;
    logf_("swapchain %d x %d, %u images, format %d, transform %d", w, h, n, S.fmt, (int)caps.currentTransform);
  }
  if (S.samples > D.max_samples) S.samples = D.max_samples;
  if (S.samples < 1) S.samples = 1;
  S.w = w, S.h = h;
  SCREEN.fmt = S.fmt, SCREEN.w = w, SCREEN.h = h, SCREEN.samples = 1;
  SCREEN.usage = S.n && S.img[0] ? S.img[0]->usage : 0;
  if (S.samples > 1) {
    S.ms = image_new(S.fmt, w, h, 1, 1, S.samples, 0, 1, SWZ_ID);
    if (S.ms) S.ms->implicit = 1;
  }
  S.depth = image_new(D.fd24, w, h, 1, 1, S.ms ? S.samples : 1, 0, 1, SWZ_ID);
  if (!S.depth) return -1;
  vop t;
  S.compat = screen_target(&t) ? t.compat : -1;
  if (strict && S.compat < 0) return -1;
  return 0;
}

static void backend_release_surface(void) {
  if (n_ops) flush_wait();
  screen_free();
  if (S.chain) vkDestroySwapchainKHR(D.dev, S.chain, NULL);
  S.chain = VK_NULL_HANDLE;
  if (S.surface) vkDestroySurfaceKHR(D.inst, S.surface, NULL);
  S.surface = VK_NULL_HANDLE;
}

/* Compatibility entry points keep their original projection and ownership. */
static int compat_screen_target(vop *t) { return fb_target(0, t); }
int vkgl_surface(VkSurfaceKHR surface, int w, int h) { return backend_surface(surface, w, h, 0, compat_screen_target); }
void vkgl_release_surface(void) { backend_release_surface(); }

/* ---- reading back, waiting ---- */

void vkgl_glFinish(void) {
  if (ctx()->loader) loader_flush();
  else flush_wait();
}

void vkgl_glFlush(void) {
  /* (the game's frame goes at its end; the loading thread's uploads now, as it hands them
   * over after a flush) */
  if (ctx()->loader) loader_flush();
}

void vkgl_glReadPixels(GLint x, GLint y, GLsizei w, GLsizei h, GLenum format, GLenum type, void *px) {
  vctx *c = ctx();
  vop t;
  if (c->loader || format != GL_RGBA || type != GL_UNSIGNED_BYTE || !fb_target(c->read_fb, &t) || w <= 0 || h <= 0) {
    set_err(GL_INVALID_OPERATION);
    return;
  }
  flush_wait();
  vimg *src = t.resolve ? t.resolve : t.color;
  if (src == &SCREEN) {
    if (!S.headless && !S.acquired) {
      set_err(GL_INVALID_OPERATION);
      return;
    }
    src = S.img[S.headless ? 0 : S.cur];
  }
  if (!src || src->samples > 1 || is_depth(src->fmt)) {
    set_err(GL_INVALID_OPERATION);
    return;
  }
  int bpp = src->fmt == VK_FORMAT_R5G6B5_UNORM_PACK16 ? 2 : 4;
  vbufmem *b = bufmem_new((VkDeviceSize)w * h * bpp, VK_BUFFER_USAGE_TRANSFER_DST_BIT);
  int vy = t.screen ? t.h - (y + h) : y;
  VkCommandBuffer cmd = up_cmd(&F->up);
  VkImageLayout from = src->in_rest ? src->rest : VK_IMAGE_LAYOUT_UNDEFINED;
  barrier(cmd, src, 0, 1, 0, 1, from, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);
  VkBufferImageCopy r = { 0, 0, 0, { VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1 }, { x, vy, 0 }, { (uint32_t)w, (uint32_t)h, 1 } };
  vkCmdCopyImageToBuffer(cmd, src->img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, b->buf, 1, &r);
  barrier(cmd, src, 0, 1, 0, 1, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, src->rest);
  src->in_rest = 1;
  VKCHECK(vkEndCommandBuffer(cmd));
  F->up.open = 0;
  submit(&F->up.cmd, 1, VK_NULL_HANDLE, VK_NULL_HANDLE, F->fence);
  VKCHECK(vkWaitForFences(D.dev, 1, &F->fence, VK_TRUE, UINT64_MAX));
  VKCHECK(vkResetFences(D.dev, 1, &F->fence));
  VKCHECK(vkResetCommandPool(D.dev, F->up.pool, 0));
  int bgr = src->fmt == VK_FORMAT_B8G8R8A8_UNORM || src->fmt == VK_FORMAT_B8G8R8A8_SRGB;
  for (int row = 0; row < h; ++row) {
    const uint8_t *s = b->map + (size_t)(t.screen ? h - 1 - row : row) * (size_t)w * bpp;
    uint8_t *d = (uint8_t *)px + (size_t)row * (size_t)w * 4;
    for (int i = 0; i < w; ++i, d += 4) {
      if (bpp == 2) {
        unsigned v = (unsigned)s[2 * i] | (unsigned)s[2 * i + 1] << 8;
        d[0] = (uint8_t)((v >> 11) * 255 / 31), d[1] = (uint8_t)(((v >> 5) & 63) * 255 / 63), d[2] = (uint8_t)((v & 31) * 255 / 31);
        d[3] = 255;
      } else {
        const uint8_t *q = s + 4 * i;
        d[0] = q[bgr ? 2 : 0], d[1] = q[1], d[2] = q[bgr ? 0 : 2], d[3] = q[3];
      }
    }
  }
  bufmem_free(b);
}

/* Non-consuming error observation for the history validity guard. */
int vkgl_error_pending(void) { return ctx()->err != GL_NO_ERROR; }
uint64_t vkgl_error_epoch(void) { vctx *c = ctx(); uint64_t *e = c == &main_ctx ? &main_error_epoch : c == &loader_ctx ? &loader_error_epoch : NULL; return e ? __atomic_load_n(e, __ATOMIC_RELAXED) : UINT64_MAX; }

/* ---- queries ---- */

GLenum vkgl_glGetError(void) {
  vctx *c = ctx();
  GLenum e = c->err;
  c->err = GL_NO_ERROR;
  return e;
}

void vkgl_glGetIntegerv(GLenum p, GLint *v) {
  vctx *c = ctx();
  switch (p) {
  case GL_FRAMEBUFFER_BINDING: *v = (GLint)c->draw_fb; return;
  case GL_ACTIVE_TEXTURE: *v = (GLint)(GL_TEXTURE0 + c->unit); return;
  case GL_VIEWPORT: memcpy(v, c->vp, sizeof c->vp); return;
  case GL_SCISSOR_BOX: memcpy(v, c->sc, sizeof c->sc); return;
  case GL_DEPTH_FUNC: *v = (GLint)c->dfunc; return;
  case GL_MAX_SAMPLES_: *v = D.max_samples; return;
  case GL_BLEND_SRC_RGB: case GL_BLEND_SRC_ALPHA: *v = (GLint)c->bsrc; return;
  case GL_BLEND_DST_RGB: case GL_BLEND_DST_ALPHA: *v = (GLint)c->bdst; return;
  case GL_BLEND_EQUATION_RGB: case GL_BLEND_EQUATION_ALPHA: *v = (GLint)c->beq; return;
  case GL_CULL_FACE_MODE: *v = (GLint)c->cull_face; return;
  case GL_FRONT_FACE: *v = (GLint)c->front; return;
  case GL_TEXTURE_BINDING_2D: *v = (GLint)c->tex2d[c->unit]; return;
  case GL_TEXTURE_BINDING_CUBE_MAP: *v = (GLint)c->texcube[c->unit]; return;
  case GL_ELEMENT_ARRAY_BUFFER_BINDING: *v = (GLint)cur_vao(c)->ebo; return;
  case GL_CURRENT_PROGRAM: *v = (GLint)c->prog; return;
  case GL_ARRAY_BUFFER_BINDING: *v = (GLint)c->array_buf; return;
  case GL_DEPTH_BITS: *v = 24; return;
  case GL_STENCIL_BITS: *v = 8; return;
  case GL_RED_BITS: case GL_GREEN_BITS: case GL_BLUE_BITS: case GL_ALPHA_BITS: *v = 8; return;
  case GL_MAX_TEXTURE_SIZE: *v = (GLint)D.props.limits.maxImageDimension2D; return;
  case GL_MAX_TEXTURE_IMAGE_UNITS: *v = MAX_UNITS; return;
  }
  *v = 0;
}

void vkgl_glGetBooleanv(GLenum p, GLboolean *v) {
  vctx *c = ctx();
  if (p == GL_DEPTH_WRITEMASK) *v = (GLboolean)c->depth_write;
  else if (p == GL_SCISSOR_TEST) *v = c->scissor_test ? GL_TRUE : GL_FALSE;
  else if (p == GL_DEPTH_TEST) *v = c->depth_test ? GL_TRUE : GL_FALSE;
  else if (p == GL_BLEND) *v = c->blend ? GL_TRUE : GL_FALSE;
  else if (p == GL_CULL_FACE) *v = c->cull ? GL_TRUE : GL_FALSE;
  else if (p == GL_COLOR_WRITEMASK) for (int i = 0; i < 4; ++i) v[i] = (GLboolean)(c->cmask >> i & 1);
  else *v = GL_FALSE;
}

void vkgl_glGetFloatv(GLenum p, GLfloat *v) {
  if (p == GL_MAX_TEXTURE_MAX_ANISOTROPY_ && D.aniso) *v = D.max_aniso;
  else if (p == GL_MAX_TEXTURE_MAX_ANISOTROPY_) set_err(GL_INVALID_ENUM);
  else *v = 0;
}

const GLubyte *vkgl_glGetString(GLenum p) {
  switch (p) {
  case GL_VENDOR: return (const GLubyte *)"vkgl";
  case GL_RENDERER: return (const GLubyte *)D.renderer;
  case GL_VERSION: return (const GLubyte *)"OpenGL ES 3.0 vkgl";
  case GL_SHADING_LANGUAGE_VERSION: return (const GLubyte *)"OpenGL ES GLSL ES 1.00";
  case GL_EXTENSIONS: return (const GLubyte *)D.extensions;
  }
  return (const GLubyte *)"";
}

static int same(const char *a, const char *b) {
  while (*a && *a == *b) a++, b++;
  return *a == *b;
}

void (*vkgl_get_proc(const char *name))(void) {
  static const struct { const char *name; void (*fn)(void); } T[] = {
    { "glBlitFramebuffer", (void (*)(void))vkgl_glBlitFramebuffer },
    { "glRenderbufferStorageMultisample", (void (*)(void))vkgl_glRenderbufferStorageMultisample },
    { "glRenderbufferStorageMultisampleEXT", (void (*)(void))vkgl_glRenderbufferStorageMultisample },
    { "glInvalidateFramebuffer", (void (*)(void))vkgl_glInvalidateFramebuffer },
    { "glFramebufferTexture2DMultisampleEXT", (void (*)(void))vkgl_glFramebufferTexture2DMultisampleEXT },
    { "glDiscardFramebufferEXT", (void (*)(void))vkgl_glDiscardFramebufferEXT },
    { "glGenVertexArraysOES", (void (*)(void))vkgl_glGenVertexArraysOES },
    { "glBindVertexArrayOES", (void (*)(void))vkgl_glBindVertexArrayOES },
    { "glDeleteVertexArraysOES", (void (*)(void))vkgl_glDeleteVertexArraysOES },
  };
  for (size_t i = 0; i < sizeof T / sizeof *T; ++i)
    if (same(T[i].name, name)) return T[i].fn;
  return NULL;
}

void vkgl_thread_loader(void) {
  cur_tls = &loader_ctx;
#ifdef WMMT_NATIVE_VK
  cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER);
#endif
}

/* ---- the pipelines kept between runs ---- */

static void backend_pipeline_cache_file(const char *path) {
  snprintf(D.pcache_path, sizeof D.pcache_path, "%s", path);
  FILE *f = fopen(path, "rb");
  if (!f) return;
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  void *data = n > 0 ? malloc((size_t)n) : NULL;
  if (data && fread(data, 1, (size_t)n, f) == (size_t)n) {
    VkPipelineCacheCreateInfo ci = { VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO };
    ci.initialDataSize = (size_t)n;
    ci.pInitialData = data;
    VkPipelineCache pc = VK_NULL_HANDLE;
    if (vkCreatePipelineCache(D.dev, &ci, NULL, &pc) == VK_SUCCESS && (!platform_native_profile || pc)) {
      /* Without privateData, distinct creations may share the same value.
       * Self-merge is invalid, but the old creation still owns one reference. */
      if (!platform_native_profile || (D.pcache && pc != D.pcache))
        vkMergePipelineCaches(D.dev, pc, 1, &D.pcache);
      vkDestroyPipelineCache(D.dev, D.pcache, NULL);
      D.pcache = pc;
      logf_("pipeline cache: %ld bytes from %s", n, path);
    }
  }
  free(data);
  fclose(f);
}

static void backend_pipeline_cache_save(void) {
  if (!D.pcache_path[0]) return;
  size_t n = 0;
  if (vkGetPipelineCacheData(D.dev, D.pcache, &n, NULL) != VK_SUCCESS || !n) return;
  void *data = malloc(n);
  if (data && vkGetPipelineCacheData(D.dev, D.pcache, &n, data) == VK_SUCCESS) {
    char tmp[600];
    snprintf(tmp, sizeof tmp, "%s.new", D.pcache_path);
    FILE *f = fopen(tmp, "wb");
    if (f) {
      int ok = fwrite(data, 1, n, f) == n;
      fclose(f);
      if (ok) rename(tmp, D.pcache_path);
    }
  }
  free(data);
}

void vkgl_pipeline_cache_file(const char *path) { backend_pipeline_cache_file(path); }
void vkgl_pipeline_cache_save(void) { backend_pipeline_cache_save(); }

/* ---- the start ---- */

VkInstance vkgl_instance(void) { return D.inst; }

static int has_ext(const VkExtensionProperties *e, uint32_t n, const char *name) {
  for (uint32_t i = 0; i < n; ++i)
    if (same(e[i].extensionName, name)) return 1;
  return 0;
}

/* Descriptor fallbacks are real images, uploaded through an explicit frame
 * uploader. Reserve every byte before recording. Initialization failures after
 * commands/device creation retain the backend's fatal policy, never fake handles. */
static vimg *backend_dummy_image(uploader *u, int layers) {
  vimg *im = image_new(VK_FORMAT_R8G8B8A8_UNORM, 1, 1, 1, layers, 1, 1, 0, SWZ_ID);
  if (!im) return NULL;
  size_t old_i = u->stage.i;
  VkDeviceSize old_used = u->stage.used, offset = 0;
  VkBuffer buffer = VK_NULL_HANDLE;
  uint8_t *dst = native_ring_alloc(&u->stage, (VkDeviceSize)layers * 4, 16, &buffer, &offset);
  VkCommandBuffer cmd = dst && buffer ? native_up_cmd(u) : VK_NULL_HANDLE;
  if (!cmd) {
    u->stage.i = old_i; u->stage.used = old_used;
    image_free_now(im);
    return NULL;
  }
  for (int i = 0; i < layers; ++i) { dst[4*i] = dst[4*i+1] = dst[4*i+2] = 0; dst[4*i+3] = 255; }
  barrier(cmd, im, 0, 1, 0, layers, VK_IMAGE_LAYOUT_UNDEFINED, im->rest);
  for (int i = 0; i < layers; ++i) image_upload_record(cmd, im, 0, i, 1, 1, buffer, offset + 4*(VkDeviceSize)i);
  im->in_rest = im->defined = 1;
  im->level_mask = 1;
  im->serial = D.serial;
  return im;
}

static const char *compat_platform_init(void) {
  ctx_init(&main_ctx, 0);
  ctx_init(&loader_ctx, 1);
  snprintf(D.renderer, sizeof D.renderer, "vkgl on %s (Vulkan %u.%u.%u)", D.props.deviceName,
           VK_VERSION_MAJOR(D.props.apiVersion), VK_VERSION_MINOR(D.props.apiVersion), VK_VERSION_PATCH(D.props.apiVersion));
  snprintf(D.extensions, sizeof D.extensions,
           "GL_OES_vertex_array_object GL_EXT_discard_framebuffer GL_EXT_multisampled_render_to_texture%s%s",
           D.aniso ? " GL_EXT_texture_filter_anisotropic" : "", D.astc ? " GL_KHR_texture_compression_astc_ldr" : "");
  return D.renderer;
}

/* Device/queue/layout/frame allocation is shared; no GL state is consulted. */
static int backend_create(const char *const *inst_ext, int n_ext, const char *(*compat_init)(void)) {
  pthread_mutex_init(&D.lock, NULL);
  pthread_mutex_init(&D.qlock, NULL);
  pthread_mutex_init(&D.plock, NULL);
  VkApplicationInfo app = { VK_STRUCTURE_TYPE_APPLICATION_INFO };
  app.pApplicationName = "WMMT3DX port";
  app.apiVersion = VK_API_VERSION_1_0;
  VkInstanceCreateInfo ici = { VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO };
  ici.pApplicationInfo = &app;
  ici.enabledExtensionCount = (uint32_t)n_ext;
  ici.ppEnabledExtensionNames = inst_ext;
  const char **optional_instance_extensions = platform_native_profile ? native_present_instance_prepare(&ici) : NULL;
  const char *layer = "VK_LAYER_KHRONOS_validation";
  if (getenv("VKGL_VALIDATE")) ici.enabledLayerCount = 1, ici.ppEnabledLayerNames = &layer;
  VkResult r = vkCreateInstance(&ici, NULL, &D.inst);
  if (platform_native_profile && r == VK_SUCCESS && !D.inst) r = VK_ERROR_INITIALIZATION_FAILED;
  free(optional_instance_extensions);
  if (platform_native_profile) native_present_instance_created(r);
  if (r != VK_SUCCESS) {
    logf_("no Vulkan instance: %d", r);
    return -1;
  }
  uint32_t n = 0;
  r = vkEnumeratePhysicalDevices(D.inst, &n, NULL);
  if (platform_native_profile && (r != VK_SUCCESS || n > 1024)) goto native_instance_fail;
  if (!n) {
    logf_("no Vulkan device");
    if (platform_native_profile) { vkDestroyInstance(D.inst, NULL); D.inst = VK_NULL_HANDLE; }
    return -1;
  }
  uint32_t pd_capacity = n;
  VkPhysicalDevice *pds = xcalloc(n, sizeof *pds);
  r = vkEnumeratePhysicalDevices(D.inst, &n, pds);
  if (platform_native_profile && (r != VK_SUCCESS || !n || n > pd_capacity)) { free(pds); goto native_instance_fail; }
  D.pd = VK_NULL_HANDLE;
  for (uint32_t i = 0; i < n && !D.pd; ++i) {
    uint32_t nq = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(pds[i], &nq, NULL);
    if (platform_native_profile && (!nq || nq > 4096)) continue;
    uint32_t queue_capacity = nq;
    VkQueueFamilyProperties *qs = xcalloc(nq, sizeof *qs);
    vkGetPhysicalDeviceQueueFamilyProperties(pds[i], &nq, qs);
    if (platform_native_profile && nq > queue_capacity) { free(qs); continue; }
    for (uint32_t q = 0; q < nq; ++q)
      if (qs[q].queueFlags & VK_QUEUE_GRAPHICS_BIT) {
        D.pd = pds[i], D.qfam = q;
        break;
      }
    free(qs);
  }
  free(pds);
  if (!D.pd) {
    logf_("no Vulkan device that draws");
    if (platform_native_profile) { vkDestroyInstance(D.inst, NULL); D.inst = VK_NULL_HANDLE; }
    return -1;
  }
  vkGetPhysicalDeviceProperties(D.pd, &D.props);
  vkGetPhysicalDeviceMemoryProperties(D.pd, &D.mp);
  VkPhysicalDeviceFeatures have, want;
  vkGetPhysicalDeviceFeatures(D.pd, &have);
  memset(&want, 0, sizeof want);
  D.aniso = want.samplerAnisotropy = have.samplerAnisotropy;
  D.astc = want.textureCompressionASTC_LDR = have.textureCompressionASTC_LDR;
  D.max_aniso = D.props.limits.maxSamplerAnisotropy;
  uint32_t ne = 0;
  r = vkEnumerateDeviceExtensionProperties(D.pd, NULL, &ne, NULL);
  if (platform_native_profile && (r != VK_SUCCESS || ne > 65536)) goto native_instance_fail;
  uint32_t extension_capacity = ne;
  VkExtensionProperties *ext = xcalloc(ne, sizeof *ext);
  r = vkEnumerateDeviceExtensionProperties(D.pd, NULL, &ne, ext);
  if (platform_native_profile && (r != VK_SUCCESS || ne > extension_capacity)) { free(ext); goto native_instance_fail; }
  const char *dext[2];
  uint32_t nd = 0;
  if (n_ext && (D.swapchain_ext = has_ext(ext, ne, VK_KHR_SWAPCHAIN_EXTENSION_NAME))) dext[nd++] = VK_KHR_SWAPCHAIN_EXTENSION_NAME;
  VkPhysicalDeviceSwapchainMaintenance1FeaturesEXT maintenance = { VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SWAPCHAIN_MAINTENANCE_1_FEATURES_EXT };
  const char *maintenance_extension = platform_native_profile ? native_present_device_prepare(ext, ne, &maintenance) : NULL;
  if (maintenance_extension) dext[nd++] = maintenance_extension;
  free(ext);
  if (platform_native_profile && n_ext && !D.swapchain_ext) goto native_instance_fail;
  float prio = 1.0f;
  VkDeviceQueueCreateInfo qi = { VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO };
  qi.queueFamilyIndex = D.qfam;
  qi.queueCount = 1;
  qi.pQueuePriorities = &prio;
  VkDeviceCreateInfo dci = { VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO };
  dci.queueCreateInfoCount = 1;
  dci.pQueueCreateInfos = &qi;
  dci.enabledExtensionCount = nd;
  dci.ppEnabledExtensionNames = dext;
  dci.pEnabledFeatures = &want;
  if (maintenance_extension) dci.pNext = &maintenance;
  r = vkCreateDevice(D.pd, &dci, NULL, &D.dev);
  if (platform_native_profile && r == VK_SUCCESS && !D.dev) r = VK_ERROR_INITIALIZATION_FAILED;
  if (platform_native_profile) native_present_device_created(r);
  if (r != VK_SUCCESS) {
    logf_("no Vulkan device made: %d", r);
    if (platform_native_profile) { vkDestroyInstance(D.inst, NULL); D.inst = VK_NULL_HANDLE; D.dev = VK_NULL_HANDLE; }
    return -1;
  }
  vkGetDeviceQueue(D.dev, D.qfam, 0, &D.q);
  /* GL's formats as this GPU has them */
  VkFormatFeatureFlags tex = VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT | VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT;
  if (fmt_has(VK_FORMAT_R4G4B4A4_UNORM_PACK16, tex)) D.f4444 = VK_FORMAT_R4G4B4A4_UNORM_PACK16, D.sw4444 = SWZ_ID;
  else D.f4444 = VK_FORMAT_B4G4R4A4_UNORM_PACK16, D.sw4444 = SW(B, G, R, A);
  if (fmt_has(VK_FORMAT_R5G5B5A1_UNORM_PACK16, tex)) D.f5551 = VK_FORMAT_R5G5B5A1_UNORM_PACK16, D.sw5551 = SWZ_ID;
  else if (fmt_has(VK_FORMAT_B5G5R5A1_UNORM_PACK16, tex)) D.f5551 = VK_FORMAT_B5G5R5A1_UNORM_PACK16, D.sw5551 = SW(B, G, R, A);
  else D.f5551 = VK_FORMAT_A1R5G5B5_UNORM_PACK16, D.sw5551 = SWZ_ID, D.conv5551 = 1;
  D.f11 = fmt_has(VK_FORMAT_B10G11R11_UFLOAT_PACK32, tex | VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT)
            ? VK_FORMAT_B10G11R11_UFLOAT_PACK32 : VK_FORMAT_R16G16B16A16_SFLOAT;
  D.fd24 = fmt_has(VK_FORMAT_D24_UNORM_S8_UINT, VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT)
             ? VK_FORMAT_D24_UNORM_S8_UINT : VK_FORMAT_D32_SFLOAT_S8_UINT;
  VkSampleCountFlags sc = D.props.limits.framebufferColorSampleCounts & D.props.limits.framebufferDepthSampleCounts;
  D.max_samples = sc & VK_SAMPLE_COUNT_4_BIT ? 4 : sc & VK_SAMPLE_COUNT_2_BIT ? 2 : 1;
  D.lazy_type = mem_type(~0u, VK_MEMORY_PROPERTY_LAZILY_ALLOCATED_BIT, 0);
  /* (a vec3 attribute read as four: the fourth is the next 2 bytes of the vertex, unused) */
  for (int i = 1; i < N_VFMT; ++i) {
    vfmt_dev[i] = VFMT[i];
    if ((fmt_props(VFMT[i]).bufferFeatures & VK_FORMAT_FEATURE_VERTEX_BUFFER_BIT) && !getenv("VKGL_VEC3_AS_4")) continue;
    if ((i - 1) % 4 == 2 && (fmt_props(VFMT[i + 1]).bufferFeatures & VK_FORMAT_FEATURE_VERTEX_BUFFER_BIT)) vfmt_dev[i] = VFMT[i + 1];
    else logf_("vertex format %d: none", VFMT[i]);
  }
  VkPipelineCacheCreateInfo pci = { VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO };
  PLATFORM_CHECK(vkCreatePipelineCache(D.dev, &pci, NULL, &D.pcache));
  for (int k = 0; k <= MAX_SAMP; ++k) {
    VkDescriptorSetLayoutBinding b[MAX_SAMP + 1];
    for (int i = 0; i <= k; ++i)
      b[i] = (VkDescriptorSetLayoutBinding){ (uint32_t)i,
                                             i ? VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER : VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC,
                                             1, i ? VK_SHADER_STAGE_FRAGMENT_BIT : VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT,
                                             NULL };
    VkDescriptorSetLayoutCreateInfo li = { VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO };
    li.bindingCount = (uint32_t)k + 1;
    li.pBindings = b;
    PLATFORM_CHECK(vkCreateDescriptorSetLayout(D.dev, &li, NULL, &dsl[k]));
    VkPipelineLayoutCreateInfo pl = { VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
    pl.setLayoutCount = 1;
    pl.pSetLayouts = &dsl[k];
    PLATFORM_CHECK(vkCreatePipelineLayout(D.dev, &pl, NULL, &playout[k]));
  }
  for (int i = 0; i < FRAMES; ++i) {
    vframe *f = &FR[i];
    VkCommandPoolCreateInfo pi = { VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO };
    pi.flags = VK_COMMAND_POOL_CREATE_TRANSIENT_BIT;
    pi.queueFamilyIndex = D.qfam;
    PLATFORM_CHECK(vkCreateCommandPool(D.dev, &pi, NULL, &f->pool));
    VkCommandBufferAllocateInfo ai = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, f->pool,
                                       VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1 };
    PLATFORM_CHECK(vkAllocateCommandBuffers(D.dev, &ai, &f->cmd));
    VkFenceCreateInfo fi = { VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
    PLATFORM_CHECK(vkCreateFence(D.dev, &fi, NULL, &f->fence));
    VkSemaphoreCreateInfo si = { VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO };
    PLATFORM_CHECK(vkCreateSemaphore(D.dev, &si, NULL, &f->acquire));
    PLATFORM_CHECK(vkCreateSemaphore(D.dev, &si, NULL, &f->render_done));
    uploader_init(&f->up);
    f->ubo.chunk = 4 << 20, f->ubo.usage = VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT;
    f->vtx.chunk = 8 << 20, f->vtx.usage = VK_BUFFER_USAGE_VERTEX_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT;
  }
  uploader_init(&LOADER_UP);
  const char *device_label = compat_init ? compat_init() : D.props.deviceName;
  D.serial = 1;
  frame_begin();
  dummy2d = backend_dummy_image(&F->up, 1);
  dummycube = backend_dummy_image(&F->up, 6);
  if (!dummy2d || !dummycube) { logf_("no descriptor fallback upload"); abort(); }
  VkSamplerCreateInfo si = { VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO };
  si.addressModeU = si.addressModeV = si.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
  PLATFORM_CHECK(vkCreateSampler(D.dev, &si, NULL, &dummy_sampler));
  const VkPhysicalDeviceLimits *L = &D.props.limits;
  logf_("limits: samplers %u per stage (%u in a set), sampled images %u, uniform buffers dynamic %u, vertex out %u, fragment in %u, driver %u",
        L->maxPerStageDescriptorSamplers, L->maxDescriptorSetSamplers, L->maxPerStageDescriptorSampledImages,
        L->maxDescriptorSetUniformBuffersDynamic, L->maxVertexOutputComponents, L->maxFragmentInputComponents,
        D.props.driverVersion);
  logf_("B10G11R11 features 0x%x, A2B10G10R10 0x%x", (unsigned)fmt_props(VK_FORMAT_B10G11R11_UFLOAT_PACK32).optimalTilingFeatures,
        (unsigned)fmt_props(VK_FORMAT_A2B10G10R10_UNORM_PACK32).optimalTilingFeatures);
  logf_("%s; ASTC %s, anisotropy %s (%.0f), MSAA up to %d, 4444 %d, 5551 %d, R11G11B10 %s, D24S8 %s, lazy memory %s",
        device_label, D.astc ? "yes" : "no", D.aniso ? "yes" : "no", D.max_aniso, D.max_samples, D.f4444, D.f5551,
        D.f11 == VK_FORMAT_B10G11R11_UFLOAT_PACK32 ? "yes" : "no", D.fd24 == VK_FORMAT_D24_UNORM_S8_UINT ? "yes" : "no",
        D.lazy_type != ~0u ? "yes" : "no");
  return 0;
native_instance_fail:
  logf_("native device/extension enumeration unavailable");
  if (D.inst) vkDestroyInstance(D.inst, NULL);
  D.inst = VK_NULL_HANDLE; D.pd = VK_NULL_HANDLE;
  return -1;
}

int vkgl_create(const char *const *inst_ext, int n_ext) { return backend_create(inst_ext, n_ext, compat_platform_init); }

#include "native_vk_platform.inc"
