/* BFX1 is untrusted local data; no GL dependencies. */
#ifndef BACKFIRE_H
#define BACKFIRE_H
#include <stddef.h>
#include <stdint.h>
/* Runtime profile is stricter than the encoder: 255-byte text, 4096 records
 * per kind, 32 MiB total. Validate composed matrices at the draw boundary;
 * finite bounded inputs do not guarantee finite products or projections. */
#define BFX_FRAMES 17
#define BFX_NAME 256
#define BFX_MAX_MESH 4096
#define BFX_MAX_NOZZLE 4096
#define BFX_MAX_CARS 4
typedef struct { uint32_t group, geometry, ordinal; char variant[BFX_NAME], path[BFX_NAME]; float frame[BFX_FRAMES][16]; } bfx_mesh;
typedef struct { char car[BFX_NAME], muffler[BFX_NAME], name[BFX_NAME], path[BFX_NAME]; float matrix[16]; } bfx_nozzle;
typedef struct { unsigned flags, nmesh, nnozzle; bfx_mesh *mesh; bfx_nozzle *nozzle; } bfx_asset;
typedef struct { int8_t frame[BFX_MAX_CARS][BFX_MAX_NOZZLE]; int8_t type[BFX_MAX_CARS][BFX_MAX_NOZZLE]; } bfx_playback;
int bfx_parse(bfx_asset *out, const void *bytes, size_t size);
int bfx_load(bfx_asset *out, const char *path);
void bfx_free(bfx_asset *asset);
void bfx_reset(bfx_playback *p);
int bfx_car_id(const char *key, const char *body);
int bfx_variant_b(int id);
void bfx_step(bfx_playback *p, const bfx_asset *a, int car, const char *id, int tuned_muffler, int pulse, int type);
#endif
