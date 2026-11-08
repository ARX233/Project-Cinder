/* Bounded exact-time original blink compositor. SPDX-License-Identifier: MIT */
#include "oc_media_overlay.h"
#include <stddef.h>
int oc_overlay_validate(const oc_media_overlay *o, uint32_t w, uint32_t h) {
    if (!o || o->abi != OC_MEDIA_OVERLAY_ABI || o->size != sizeof *o || o->flags ||
        !o->rgba || !o->width || !o->height ||
        o->width > OC_MEDIA_OVERLAY_MAX_WIDTH || o->height > OC_MEDIA_OVERLAY_MAX_HEIGHT ||
        (uint64_t)o->width * o->height > OC_MEDIA_OVERLAY_MAX_PIXELS ||
        o->stride_bytes != o->width * 4 ||
        o->rgba_bytes != (uint64_t)o->stride_bytes * o->height ||
        o->x < 0 || o->y < 0 || (uint64_t)o->x + o->width > w ||
        (uint64_t)o->y + o->height > h)
        return OC_MEDIA_INVALID;
    return 0;
}
int oc_media_overlay_apply_rgb24(const oc_media_overlay *o, uint8_t *rgb,
    uint64_t bytes, uint32_t w, uint32_t h, uint32_t stride,
    int64_t pts, uint32_t num, uint32_t den) {
    if (!rgb || !w || !h || w > 640 || h > 480 || stride != w * 3 ||
        bytes != (uint64_t)stride * h || pts < 0 || pts > 1000000000 ||
        !num || num > 1000000000 || !den || den > 1000000000 ||
        oc_overlay_validate(o, w, h)) return OC_MEDIA_INVALID;
    uintptr_t rp = (uintptr_t)rgb, op = (uintptr_t)o->rgba;
    if (rp > UINTPTR_MAX - bytes || op > UINTPTR_MAX - o->rgba_bytes ||
        (rp < op + o->rgba_bytes && op < rp + bytes)) return OC_MEDIA_INVALID;
    uint64_t rem = (uint64_t)pts * num % den;
    uint64_t tri = 2 * rem > den ? 2 * rem - den : den - 2 * rem;
    for (uint32_t y = 0; y < o->height; ++y) {
        const uint8_t *s = o->rgba + (uint64_t)y * o->stride_bytes;
        uint8_t *d = rgb + ((uint64_t)o->y + y) * stride + (uint64_t)o->x * 3;
        for (uint32_t x = 0; x < o->width; ++x, s += 4, d += 3) {
            /* FFmpeg geq returns 8-bit alpha, so positive product truncates. */
            uint32_t a = (uint32_t)((uint64_t)s[3] * tri / den);
            for (int c = 0; c < 3; ++c)
                d[c] = (uint8_t)(((uint32_t)s[c] * a + (uint32_t)d[c] * (255-a) + 127) / 255);
        }
    }
    return 0;
}
