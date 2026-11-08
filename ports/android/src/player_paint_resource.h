#ifndef PLAYER_PAINT_RESOURCE_H
#define PLAYER_PAINT_RESOURCE_H
#include "ghost_asset_source.h"
typedef struct player_paint_resource player_paint_resource;
/* PROGRAM-OWNED authority only: Resource broker supplies an already approved
 * immutable MAIN data-root directory FD for the new pinned profile. Never pass
 * a user-selected path/fd or a receipt-derived hash. Opens only the fixed main
 * member player-body-paints.bin, no optional namespace/JNI input. Failure means
 * palette unavailable + explicit fresh reconversion, never inplace repair.
 * Existing reader/cache must close before holder; root fd remains caller-owned. */
int player_paint_resource_open_main(int approved_main_root_fd, player_paint_resource **out);
int player_paint_resource_source(player_paint_resource *resource, ghost_asset_source *out);
void player_paint_resource_close(player_paint_resource *resource);
#endif
