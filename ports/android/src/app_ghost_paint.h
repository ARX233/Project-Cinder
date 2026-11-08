/* Private integration helper. render.h and ghost_paint.h must precede this. */
#ifndef APP_GHOST_PAINT_H
#define APP_GHOST_PAINT_H
/* Single selected arcade opponent, <=3 original 2048² RGBA8 pages; no global cache.
 * CPU transient <=16 MiB raw + zlib-bound compressed; GPU base <=48 MiB + mipmaps.
 * Real dataset maxima are reported separately, not assumed by validation. */
typedef struct {
 const uint8_t *pixels; size_t bytes; uint16_t width,height;
 char material[48]; uint8_t rgb_mask, color[4];
 uint32_t vinyl; uint8_t carbon_bonnet;
 /* Optional decoded plane hash: zero means caller only relies on approved VPK
  * capability. Nonzero is verified with the reader/catalog SHA implementation. */
 uint8_t sha256[32];
} ghost_paint_overlay;
typedef struct {
 ghost_paint_key key; uint64_t context_generation; uint32_t texture[3];
 uint32_t vinyl,bonnet; uint8_t overlay_sha256[32];
 ghost_paint_page pages[3]; size_t count; int prepared, applying;
 wpk_scene *scene; unsigned char *batch_restore; size_t batch_capacity;
} app_ghost_paint_cache;
typedef struct {
 wpk_scene *scene; app_ghost_paint_cache *cache; int index[3];
 uint32_t old_texture[3]; unsigned char old_alpha[3];
 unsigned char *old_cutout; size_t batch_count, count;
} app_ghost_paint_scope;
/* prepare/want is called on game/context owner before readiness/GO. existing
 * cache is destroyed on key change; missing original pages/material fails closed.
 * raw custom==0 needs no custom textures, but still requires the real scene. */
int app_ghost_paint_want(app_ghost_paint_cache *cache, const ghost_paint_reader *reader,
 ghost_paint_key key, uint64_t context_generation, wpk_scene *exact_scene,
 uint32_t vinyl, uint32_t bonnet, const ghost_paint_overlay *overlay);
int app_ghost_paint_ready(const app_ghost_paint_cache *cache, ghost_paint_key key,
 uint64_t context_generation, const wpk_scene *exact_scene,
 uint32_t vinyl, uint32_t bonnet);
/* lost_context=1 forgets handles; no destroy calls into the dead context. Call
 * clear before scenes/catalog close and race exit, never while scope is active. */
int app_ghost_paint_clear(app_ghost_paint_cache *cache, int lost_context);
/* Only caller's explicit arcade slot0 may invoke apply. It refuses a mismatched
 * key/context/scene. Scope MUST be restored on every path before another draw. */
int app_ghost_paint_apply(app_ghost_paint_cache *cache, ghost_paint_key key,
 uint64_t context_generation, wpk_scene *exact_scene, uint32_t vinyl,
 uint32_t bonnet, app_ghost_paint_scope *scope);
void app_ghost_paint_restore(app_ghost_paint_scope *scope);
#endif
