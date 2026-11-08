/* WPPAINT1: bounded original custom body pages, never a host pathname. */
#ifndef PLAYER_PAINT_H
#define PLAYER_PAINT_H
#include <stddef.h>
#include <stdint.h>
#define PLAYER_PAINT_MAX_SECTION (128u*1024u*1024u)
#define PLAYER_PAINT_MAX_IMAGE (16u*1024u*1024u)
#define PLAYER_PAINT_MAX_RECORDS 8192u
#define PLAYER_PAINT_MAX_PAGES 3u
#define PLAYER_PAINT_MAX_DIM 2048u
/* Common Resource-owned capability: all offsets relative, live fd identity. */
#include "ghost_asset_source.h"
typedef ghost_asset_source player_paint_source;
typedef struct { uint16_t pack; uint8_t custom_color, aero; } player_paint_key;
typedef struct {
 player_paint_key key; uint8_t page, alpha_present; uint16_t width,height;
 uint32_t raw_size, compressed_size, crc32; uint64_t compressed_offset;
 uint8_t rgba_sha256[32], source_sha256[32], lua_sha256[32];
 char material[48], source_path[128];
} player_paint_page;
typedef struct player_paint_reader player_paint_reader;
typedef enum { PLAYER_PAINT_OK=0, PLAYER_PAINT_ARGUMENT, PLAYER_PAINT_IO, PLAYER_PAINT_HASH,
 PLAYER_PAINT_SHAPE, PLAYER_PAINT_MEMORY, PLAYER_PAINT_ABSENT } player_paint_result;
player_paint_result player_paint_open(const player_paint_source *source, player_paint_reader **out);
void player_paint_close(player_paint_reader *reader);
/* Descriptors borrow reader lifetime. Pages sort by original page number. */
player_paint_result player_paint_lookup(const player_paint_reader *reader, player_paint_key key,
 const player_paint_page **pages, size_t *count);
/* Selected page only: malloc RGBA8, original bottom-up rows, no quantization.
 * The descriptor must be one returned by this reader. Every failure clears output. */
player_paint_result player_paint_read_rgba(const player_paint_reader *reader, const player_paint_page *page,
 uint8_t **rgba, size_t *bytes);
/* Narrow delegation to catalog's existing memory SHA; no second algorithm.
 * Used for bounded caller-approved decoded vinyl plane fingerprints. */
int player_paint_hash_bytes(const player_paint_reader *reader, const void *bytes,
 size_t size, uint8_t out[32]);
const char *player_paint_error(player_paint_result result);
#endif
