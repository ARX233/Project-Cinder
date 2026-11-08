/* Player identity wrapper. Owns only selected textures, not WPK or Resource fd. */
#ifndef PLAYER_BODY_PAINT_H
#define PLAYER_BODY_PAINT_H
#include "render.h"
#include "player_paint.h"
#include "app_player_paint.h"
typedef struct {
 uint16_t raw_model, pack, factory_paint;
 uint8_t custom_color, aero, vinyl, bonnet;
 uint64_t context_generation;
} player_body_paint_identity;
typedef struct {
 app_player_paint_cache selected;
 player_body_paint_identity identity;
 int prepared;
} player_body_paint_cache;
/* raw model must match the exact canonical tuple; 224..231 are NOT accepted
 * aliases; R35 232..242 have no custom repaint support. The app additionally
 * retains its hidden-model policy. No model or factory paint is rewritten. */
int player_body_paint_identity_valid(player_body_paint_identity identity);
int player_body_paint_prepare(player_body_paint_cache *cache,
 const player_paint_reader *reader, player_body_paint_identity identity,
 wpk_scene *exact_scene, const player_paint_overlay *overlay);
int player_body_paint_ready(const player_body_paint_cache *cache,
 player_body_paint_identity identity, const wpk_scene *exact_scene);
int player_body_paint_clear(player_body_paint_cache *cache, int lost_context);
int player_body_paint_apply(player_body_paint_cache *cache,
 player_body_paint_identity identity, wpk_scene *exact_scene,
 app_player_paint_scope *scope);
/* Existing app_player_paint_restore restores its exact scene on every path.
 * Never nest player/Ghost scopes or draw a second car before restoring. */
/* Bit 0 == custom1; bit9 == custom10. No decoding, allocation, upload or fake
 * coverage: each bit needs the exact key AND all referenced material pages in
 * this scene. Zero on missing bank/key, noncanonical/R35 identity or bad scene. */
uint16_t player_body_paint_available_mask(const player_paint_reader *reader,
 player_body_paint_identity identity, const wpk_scene *exact_scene);
#endif
