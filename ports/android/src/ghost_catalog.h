/* Immutable recorded Ghost catalogue. No default-opponent synthesis or raw-field mapping.
 * Source name scalars are uint16; all raw metadata values retain original u32 bits.
 * A bank is a capability only after external APK/private-store approval and exact SHA. */
#ifndef GHOST_CATALOG_H
#define GHOST_CATALOG_H
#include <stddef.h>
#include <stdint.h>
#include "ghost_format.h"
#include "ghost_asset_source.h"
#define GHOST_CATALOG_RECORDS 196u
#define GHOST_CATALOG_AREAS 8u
#define GHOST_CATALOG_BLOBS 1000u
#define GHOST_CATALOG_TRAILS 1267u
#define GHOST_CATALOG_MAX_FILE (256u * 1024u * 1024u)
#define GHOST_CATALOG_NO_BLOB UINT32_MAX
#define GHOST_CATALOG_AREA_FIELDS(X) \
 X(aero_) X(aero_mirror_) X(bonnet_) X(car_) X(class_) X(cool_wild_) X(crown_) \
 X(crown_get_date_day_) X(crown_get_date_hour_) X(crown_get_date_minute_) X(crown_get_date_month_) X(crown_get_date_second_) X(crown_get_date_year_) \
 X(crown_win_count_) X(crown_win_date_day_) X(crown_win_date_hour_) X(crown_win_date_minute_) X(crown_win_date_month_) X(crown_win_date_second_) X(crown_win_date_year_) \
 X(custom_color_) X(day_) X(dress_) X(dress_x_) X(hour_) X(minute_) X(month_) X(neon_) X(odo_count_) X(play_count_) X(player_win_count_) \
 X(ramp_) X(route_) X(second_) X(smooth_rough_) X(title_) X(trail_size_) X(trail_sum_) X(tune_handling_) X(tune_power_) X(vinyl_) X(wheel_) X(win_count_) X(wing_) X(year_)
#define GHOST_CATALOG_ENUM(n) GHOST_RAW_##n,
typedef enum { GHOST_CATALOG_AREA_FIELDS(GHOST_CATALOG_ENUM) GHOST_RAW_FIELD_COUNT } ghost_catalog_raw_field;
#undef GHOST_CATALOG_ENUM
typedef struct { char name[64]; uint32_t value; } ghost_catalog_scalar;
typedef struct {
 uint32_t blob_index; uint64_t compressed_offset;
 uint32_t compressed_size, raw_size, crc32, native_stage; uint8_t sha256[32];
} ghost_catalog_trail;
typedef struct {
 uint64_t present_mask; /* Missing raw fields are absent, not default values. */
#define GHOST_CATALOG_MEMBER(n) uint32_t n;
 GHOST_CATALOG_AREA_FIELDS(GHOST_CATALOG_MEMBER)
#undef GHOST_CATALOG_MEMBER
 int32_t level_comment; /* Source comment ONLY, never a difficulty binding. */
 ghost_catalog_trail trail; /* blob_index == NO_BLOB: no recording for this slot. */
} ghost_catalog_area;
typedef struct {
 uint32_t id_devel, id1, id2, version_raw, original_raw; uint16_t name[5];
 uint8_t source_sha256[32], config_sha256[32];
 size_t global_count; const ghost_catalog_scalar *globals;
 ghost_catalog_area areas[GHOST_CATALOG_AREAS];
} ghost_catalog_record_view;
typedef struct ghost_catalog ghost_catalog;
typedef enum { GHOST_CATALOG_OK=0, GHOST_CATALOG_ARGUMENT, GHOST_CATALOG_IO,
 GHOST_CATALOG_HASH, GHOST_CATALOG_SHAPE, GHOST_CATALOG_MEMORY,
 GHOST_CATALOG_ABSENT, GHOST_CATALOG_NATIVE } ghost_catalog_result;
/* expected_sha256 is mandatory external approval, not read from this bank's header.
 * Opens a regular, non-symlink file and retains its descriptor. No host data fallback. */
ghost_catalog_result ghost_catalog_open_verified(const char *path, const uint8_t expected_sha256[32], ghost_catalog **out);
void ghost_catalog_close(ghost_catalog *catalog);
/* WGBANK2's complete WGPAINT1 section, descriptor-SHA checked at open.
 * No path or descriptor escape: read_at is relative/range/stat guarded. */
ghost_catalog_result ghost_catalog_paint_source(const ghost_catalog *catalog, ghost_asset_source *out);
void ghost_catalog_sha256_bytes(const void *data, size_t bytes, uint8_t out[32]);
unsigned ghost_catalog_version(const ghost_catalog *catalog);
size_t ghost_catalog_count(const ghost_catalog *catalog);
const ghost_catalog_record_view *ghost_catalog_record(const ghost_catalog *catalog, size_t index);
const ghost_catalog_record_view *ghost_catalog_lookup(const ghost_catalog *catalog, uint32_t devel, uint32_t id1, uint32_t id2);
int ghost_catalog_global(const ghost_catalog_record_view *record, const char *name, uint32_t *value);
int ghost_catalog_area_has(const ghost_catalog_area *area, ghost_catalog_raw_field field);
const char *ghost_catalog_raw_field_name(ghost_catalog_raw_field field);
/* Selected trail only: exact DEFLATE consumption, raw SHA/CRC then strict native
 * validator using CALLER-APPROVED stage and area table. Caller frees *bytes.
 * On every failure *bytes=NULL,*size=0,*info=0. No deduplication of native area IDs. */
ghost_catalog_result ghost_catalog_read_trail(const ghost_catalog *catalog, size_t index, unsigned area,
 const ghost_format_policy *policy, void **bytes, size_t *size, ghost_format_info *info);
const char *ghost_catalog_error(ghost_catalog_result result);
#endif
