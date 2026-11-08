/* Program-owned, bounded immutable section capability. Never deserialize pointers.
 * Context/lifetime belong to the catalogue owner; close only after consumers release.
 * read_at offsets are relative to this section, exact length; 1 success,0 failure.
 * sha256_bytes is a program-owned helper, not an untrusted bank-supplied callback. */
#ifndef GHOST_ASSET_SOURCE_H
#define GHOST_ASSET_SOURCE_H
#include <stddef.h>
#include <stdint.h>
typedef struct ghost_asset_source {
 void *context;
 uint64_t length;
 union { uint8_t sha256[32]; uint8_t expected_sha256[32]; uint8_t expected_sha[32]; };
 int (*read_at)(void *context, uint64_t relative_offset, void *out, size_t bytes);
 void (*sha256_bytes)(const void *data, size_t bytes, uint8_t out[32]);
 int (*verify_sha256)(void *context, uint64_t relative_offset, uint64_t bytes,
                      const uint8_t expected[32]);
} ghost_asset_source;
#endif
