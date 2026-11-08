/* Optional original blink label; ABI1 header and original implementation unchanged.
 * SPDX-License-Identifier: MIT */
#ifndef OC_MEDIA_OVERLAY_H
#define OC_MEDIA_OVERLAY_H
#include "oc_media.h"
#ifdef __cplusplus
extern "C" {
#endif
#define OC_MEDIA_OVERLAY_ABI 2u
#define OC_MEDIA_OVERLAY_MAX_WIDTH 512u
#define OC_MEDIA_OVERLAY_MAX_HEIGHT 128u
#define OC_MEDIA_OVERLAY_MAX_PIXELS 65536u
typedef struct {
    uint32_t abi, size, width, height, stride_bytes;
    int32_t x, y;
    uint32_t flags; /* must be 0; straight, not premultiplied, RGBA8 */
    uint64_t rgba_bytes;
    const uint8_t *rgba; /* exact width*height*4 bytes, tight stride; caller-owned */
} oc_media_overlay;
/* Optional diagnostic observer. Pointers are readonly and valid only during this
   callback. No full movie retention. Frame RGB stride is tight width*3. Time is
   exactly pts*tb_num/tb_den seconds. Callback must be bounded/nonthrowing and not
   modify any FD/buffer. NULL disables its additional before-frame copy. */
typedef void (*oc_media_rgb_observer)(void *opaque, const uint8_t *before_rgb,
    const uint8_t *after_rgb, uint32_t width, uint32_t height, uint32_t stride,
    int64_t pts, uint32_t tb_num, uint32_t tb_den);
/* Separate variant library also exports unmodified oc_media_convert_fd ABI1.
   mode must be BINK_AVC_AAC when overlay != NULL. All original FD, limit, cancel,
   result and publication contracts remain. Overlay is copied after validation
   before any output bytes. NULL overlay is valid (diagnostic RGB roundtrip only).
   No PNG parser in native: parent decodes a validated PNG FD with bounded Pillow.
   x/y and the full label must fit actual video; no implicit clipping/resizing. */
int oc_media_convert_overlay_fd(int mode, int source_fd, int audio_fd, int output_fd,
    const oc_media_overlay *overlay, oc_media_rgb_observer observer,
    void *observer_opaque, const oc_media_limits *limits, oc_media_cancel cancel,
    void *opaque, oc_media_result *result);
/* The same bounded pure compositor used by conversion. Mutates only RGB bytes;
   validates all arguments before mutation. Uses exact rational time, one-second
   triangle opacity, floor(RGBA_alpha*opacity) as 8-bit geq alpha, then rounded
   straight-alpha RGB blend. RGB must be tight <=640x480. No paths/FDs or allocations.
   pts<=1e9, 0<timebase terms<=1e9. Returns 0 or OC_MEDIA_INVALID. */
int oc_media_overlay_apply_rgb24(const oc_media_overlay *overlay, uint8_t *rgb,
    uint64_t rgb_bytes, uint32_t width, uint32_t height, uint32_t stride,
    int64_t pts, uint32_t tb_num, uint32_t tb_den);
const char *oc_media_overlay_build_info(void);
#ifdef __cplusplus
}
#endif
#endif
