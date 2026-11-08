/* The arcade's street lights (clStreetLightManager) and, at night, building lights
 * (clBuildingLightManager): glow sprites at the locators of the map's distribution models,
 * packed by tools/stage/pack_lights.py into lights.wpk (the sprites) and lights.bin. */
#ifndef LIGHTS_H
#define LIGHTS_H

#include "car.h"
#include "mathx.h"
#include "render.h"

/* 0 when lights.wpk and lights.bin loaded; the race draws no lights without them */
int lights_load(const char *data_dir);
int lights_front_halo_load(const char *atlas, const char *anchors);
/* The lights of another map: Tokyo's lights.bin or a city's lights_<city>.bin (none if it is
 * missing, then -1) */
int lights_points(const char *path);

/* Draw the lights the camera sees, after the scene (render_begin is in effect): view and
 * proj are the race camera's, time the race clock in seconds (the building lights blink).
 * Building lights only at night. */
void lights_draw(const mat4 *proj, const mat4 *view, int night, float time, render_params *rp);

/* The first draws with the sprites' textures, once, in the loading's warm-up (render_warm_begin
 * in effect); how many there were (0 after the first call) */
int lights_warm(void);

/* The rows of lights across the road at the goal and at the next checkpoint (clGoalLine) that
 * race r has, as lights_draw (lights.wpk's fifth texture, goal_light01.tga) */
void lights_draw_goal(const mat4 *proj, const mat4 *view, const car_race *r, float time, render_params *rp);
/* The 10-in-a-row's blue line across the road at the rival (car_race ten_line) */
void lights_draw_ten_line(const mat4 *proj, const mat4 *view, const car_race *r, render_params *rp);

/* The headlights' pools on the road in front of n cars (their body matrices, GL column-major),
 * clCarSpotLight's, after the scene like the lights; morning or night colour */
void lights_draw_spots(const mat4 *proj, const mat4 *view, const float *const *bodies, int n, int night, render_params *rp);

/* Original clCarLampHalo for the main or mirror view. Spot/halo visibility
 * shares the native lamp bit; callers supply only lit, visible cars. */
void lights_draw_front_halo(const mat4 *proj, const mat4 *view, const float *eye,
                            const float *body, const char *pack, int aero, int mirror,
                            render_params *rp);

/* The under neon (clNeon) of a car: neon 1..12 (car_neon_<colour>_race.igb, then the spot
 * neons' car_spotneon_*), its quad (x and z -29..29, flat) scaled and moved by the car's
 * nsNeonData row (src/neondb.h: CARDB_PACKS pack, body 0..3) in the space of `frame` (GL
 * column-major, world), drawn additive after the scene like the lights; the textures
 * (neon.wpk) load the first time one is drawn */
void lights_draw_neon(const mat4 *proj, const mat4 *view, const float *frame, int pack, int body, int neon, render_params *rp);

/* The wall sparks' pictures (lights.wpk's eighth and ninth: car_spark03.tga, car_spark04.tga),
 * 0 when lights.wpk has none */
uint32_t lights_spark_texture(int k);

#endif
