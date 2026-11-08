/* WGPAINT1: bounded original custom body pages, never a host pathname. */
#ifndef GHOST_PAINT_H
#define GHOST_PAINT_H
#include <stddef.h>
#include <stdint.h>
#define GHOST_PAINT_MAX_SECTION (128u*1024u*1024u)
#define GHOST_PAINT_MAX_IMAGE (16u*1024u*1024u)
#define GHOST_PAINT_MAX_RECORDS 1024u
#define GHOST_PAINT_MAX_PAGES 3u
#define GHOST_PAINT_MAX_DIM 2048u
/* Common Resource-owned capability: all offsets relative, live fd identity. */
#include "ghost_asset_source.h"
typedef ghost_asset_source ghost_paint_source;
typedef struct { uint16_t pack; uint8_t custom_color, aero; } ghost_paint_key;
typedef struct {
 ghost_paint_key key; uint8_t page, alpha_present; uint16_t width,height;
 uint32_t raw_size, compressed_size, crc32; uint64_t compressed_offset;
 uint8_t rgba_sha256[32], source_sha256[32], lua_sha256[32];
 char material[48], source_path[128];
} ghost_paint_page;
typedef struct ghost_paint_reader ghost_paint_reader;
typedef enum { GHOST_PAINT_OK=0, GHOST_PAINT_ARGUMENT, GHOST_PAINT_IO, GHOST_PAINT_HASH,
 GHOST_PAINT_SHAPE, GHOST_PAINT_MEMORY, GHOST_PAINT_ABSENT } ghost_paint_result;
ghost_paint_result ghost_paint_open(const ghost_paint_source *source, ghost_paint_reader **out);
void ghost_paint_close(ghost_paint_reader *reader);
/* Descriptors borrow reader lifetime. Pages sort by original page number. */
ghost_paint_result ghost_paint_lookup(const ghost_paint_reader *reader, ghost_paint_key key,
 const ghost_paint_page **pages, size_t *count);
/* Selected page only: malloc RGBA8, original bottom-up rows, no quantization.
 * The descriptor must be one returned by this reader. Every failure clears output. */
ghost_paint_result ghost_paint_read_rgba(const ghost_paint_reader *reader, const ghost_paint_page *page,
 uint8_t **rgba, size_t *bytes);
/* Narrow delegation to catalog's existing memory SHA; no second algorithm.
 * Used for bounded caller-approved decoded vinyl plane fingerprints. */
int ghost_paint_hash_bytes(const ghost_paint_reader *reader, const void *bytes,
 size_t size, uint8_t out[32]);
const char *ghost_paint_error(ghost_paint_result result);
#endif
