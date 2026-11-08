/* Internal renderer bridge: original RGBA bytes, existing GL/VKGL/NativeVK.
 * Caller is current game context owner, before GO, not suspended/loader thread. */
#ifndef RENDER_GHOST_PAINT_H
#define RENDER_GHOST_PAINT_H
#include <stdint.h>
#include <stddef.h>
uint32_t render_ghost_paint_rgba8(const uint8_t *rgba, size_t bytes, unsigned width, unsigned height);
void render_ghost_paint_destroy(uint32_t texture);
#endif
