/* OpenGL ES 2.0 renderer for .wpk scenes (format: tools/pack.py). */
#ifndef RENDER_H
#define RENDER_H

#include <stddef.h>
#include <stdint.h>

#include "mathx.h"
#include "tail_trail.h"

typedef struct {
  uint16_t tex, flags;
  uint32_t count;
  uint32_t pool, ioff; /* its wpk_pool, and where its indices start in the pool's (bytes) */
  uint8_t cutout; /* drawn alpha-tested: its texture (or a paint for it) or vertex colours hold alpha */
  /* a lit scene's (WPK3) material: WPK_LIT_* program, env and specular map textures, env power */
  uint8_t prog;
  uint16_t env, spec;
  float power;
  /* a map's gloss program (pack.py's GLS1 section): its gloss texture and reflection cube
   * (0xFFFF none) */
  uint16_t gloss, cube;
  float lo[3], hi[3]; /* its vertices' box */
} wpk_batch;

/* the lit scenes' programs (the cars): the arcade's fixed-function lighting for the parts
 * without a program of their own, car.cg (paint: sphere-mapped environment, specular),
 * car_blend.cg (glass, lamps, wheels: a specular map mixes the environment in) */
enum { WPK_LIT_FF, WPK_LIT_CAR, WPK_LIT_CAR_BLEND, WPK_LIT_PROGS };

/* Batches one after another in the file share a vertex and an index buffer, up to 65536
 * vertices (their indices made the pool's as they go up): the course's 9440 batches had a
 * buffer pair each, and every first draw on the iPad cost more the more buffers GL held
 * (from 2 ms with the course alone to 16-26 ms once the car select's 47 models were in). */
typedef struct {
  uint32_t vbo, ibo;
  uint32_t vao;            /* its vertex array object in the app's GL context (made on first draw) */
  uint32_t vbytes, ibytes; /* its size */
  uint32_t vfill, ifill;   /* how much of it is up */
  uint8_t warm;            /* drawn with once (wpk_warm_stats) */
  uint32_t nbo, nbytes, nfill; /* the gloss batches' pools: their normals (s16 x 4 a vertex) */
} wpk_pool;

typedef struct {
  float lo[3], hi[3];
  uint32_t first, n;
  uint32_t group; /* WPK_GROUND, WPK_SHORT, WPK_LONG, or WPK_GROUPS + object index */
} wpk_chunk;

/* The arcade's three model lists, each drawn to its own distance */
enum { WPK_GROUND, WPK_SHORT, WPK_LONG, WPK_GROUPS };
/* a car's tyre and wheel at one corner (FL, FR, RL, RR, as car.h's CAR_FL..), placed where
 * they stand still; render_params.wheels turns them */
#define WPK_WHEEL 0x100u
/* a car's lamps (pack_cars.py): unlit, as the menus show the cars, and lit, as a race does
 * (clCarModelData::constructBody by the car's mode); render_params.lamps_on picks */
#define WPK_LAMP_OFF 0x110u
#define WPK_LAMP_ON 0x111u
/* its brake lamp model's RUN (off the brake) and STOP (on it); render_params.braking picks */
#define WPK_BRAKE_RUN 0x112u
#define WPK_BRAKE_STOP 0x113u
/* the rest of it (LIGHT, the headlights' glow), which no switch turns off: the race's only, as
 * RUN and STOP (clMenuCar::init loads no brake lamp model) */
#define WPK_BRAKE_LIGHT 0x114u
/* its STOP_HIGH and STOP_WING2, on the brake too for the wings (render_params.wing 0..4) whose
 * bits the group's low 5 bits set (nsBrakeParts::BrakelampHasHighMount, BrakelampHasWingBrake) */
#define WPK_BRAKE_HIGH 0x140u
#define WPK_BRAKE_WING2 0x160u
/* its dress-up parts, a group per switch child (clCarModelData's table 0x97773c0): MIRROR1..2,
 * WING1..4, BONNET1..4; render_params.mirror, wing and bonnet pick one of each */
#define WPK_MIRROR 0x120u
#define WPK_WING 0x122u
#define WPK_BONNET 0x126u
/* its tyres for a dress-up wheel (CustomTireLocation, TireStatus.scale[2]), by corner like
 * WPK_WHEEL: render_params.wheel_custom shows them instead of the WPK_WHEEL chunks */
#define WPK_CTIRE 0x12au
/* a car's shadow volume (pack.py --shadow): drawn by render_shadows alone */
#define WPK_SHADOW 0xffffu

/* batch flags: the low bits are the blend mode (1 alpha, 2 additive), the rest a texture flipbook */
#define WPK_BLEND_MASK 3

/* wpk_draw's passes, in the order a frame draws them: the PowerVR GPU sorts the opaque
 * pixels of a tile itself (hidden surface removal) unless a shader can discard, so the
 * opaque batches draw with a program that cannot, the alpha-tested ones after them, and
 * the blended ones last (render_blend_pass on). */
enum { WPK_OPAQUE, WPK_CUTOUT, WPK_BLEND, WPK_PASSES };
/* a texture's format in a pack: 0 RGB565, 1 RGBA4444, 2 RGBA5551 (with mipmaps made on
 * load), or from WPK_ASTC ASTC LDR (Android's packs: WPK_ASTC + 2 * block (0 4x4, 1 6x6,
 * 2 8x8) + alpha, its mipmaps in the pack) */
#define WPK_ASTC 3

/* a car's paint k >= 1: texture `src` ("p<k>:<name>") stands in for texture `dst` ("<name>") */
typedef struct {
  uint16_t k, dst, src;
} wpk_paint_swap;

typedef struct {
  uint32_t n_tex, n_chunk, n_batch;
  uint32_t *textures; /* GL names the batches draw with */
  uint32_t *loaded;   /* GL names as loaded (textures differs while a paint is on) */
  wpk_chunk *chunks;
  wpk_batch *batches;
  wpk_pool *pools;
  uint32_t n_pools;
  wpk_paint_swap *paints;
  uint32_t n_paints;
  unsigned char *tex_alpha; /* by texture: it (or a paint that stands in for it) has alpha */
  unsigned char *tex_wet;   /* by texture: a road's (render_hq's wet road, render_params.wet) */
  int lit;       /* WPK3: normals and materials, drawn with the cars' lighting */
  uint32_t stride; /* vertex bytes: 24, 32 lit */
  int two_sided; /* draw back faces too (the cars: their models mix both windings) */
  int solid;     /* opaque batches ignore the textures' alpha (the sky box's leave it empty) */
#ifdef __ANDROID__
  int course_arrows; /* legacy component-order repair is scoped to route arrow scenes */
#endif
  unsigned char *warm; /* by chunk: drawn before (the driver finishes a texture's upload on first use) */
  int warm_chunk;       /* wpk_prewarm's chunk under way (-1 none) and its next batch */
  uint32_t warm_batch;
  unsigned char *tex_warm; /* by texture: drawn with (wpk_warm_paints, wpk_warm_stats) */
  /* the file, read a piece at a time while wpk_upload still has textures or buffers to hand
   * to GL (wpk_upload_paints opens it again for the paints left out) */
  char *path;
  int fd;
  void *tex_tbl;   /* the file's texture records (all of the scene's life) */
  void *batch_tbl; /* and batch records, till the upload is done */
  uint32_t rec_size;
  void *scratch;
  size_t scratch_size;
  uint32_t next_tex, next_batch;
  unsigned char *is_paint; /* by texture: a paint ("p<k>:<name>") */
  int skip_paints;         /* wpk_upload leaves the paints out, for wpk_upload_paints */
  /* a dress-up aero set's pack borrows the textures it stores empty (size 0) from the
   * stock pack of its car (wpk_share): by texture, the stock pack's index or 0xFFFF */
  const void *share;
  uint16_t *share_idx;
  /* the gloss section: its cubes (GL names, then the file's face records, 6 x 12 bytes a
   * cube, till uploaded) and by batch where its normals are in the file (0 none) */
  uint32_t n_cube, next_cube;
  uint32_t *cubes;
  unsigned char *cube_warm;
  void *cube_tbl;
  uint32_t *gloss_noff;
  /* the car's ambient occlusion (tools/stage/bake_ao.c, <pack>.ao beside it): the file's maps
   * till wpk_upload hands them to GL, then by texture the map that darkens it (0 none) */
  unsigned char *ao_file;
  size_t ao_size;
  uint32_t *ao_tex, n_ao;
} wpk_scene;

typedef struct {
  float fog_color[3];
  float fog_far, fog_near;
  /* the map's colour grade: the scene programs' base * colour times it before the fog (the
   * port's own, by city and time zone: app.c MAP_GRADE); 0 none (1, 1, 1) */
  float grade[3];
  /* render_hq's wet road (a map's asphalt and lines reflect the lights of the last frame):
   * how much, 0 dry */
  float wet;
  float range[WPK_GROUPS]; /* chunk cull distance per group */
  float time; /* seconds, drives the animated signs' texture flipbooks */
  float uv_shift[2]; /* added to every texture coordinate (the miniature course's running gradation) */
  const unsigned char *object_visible; /* by object index; objects are drawn to range[WPK_SHORT] */
  int n_objects;
  int lamps_on; /* the cars' WPK_LAMP_ON chunks instead of their WPK_LAMP_OFF ones: a race's cars */
  int no_gloss; /* the maps' gloss batches without their reflection (plain base * colour) */
  int braking;  /* the car's WPK_BRAKE_STOP chunks instead of its WPK_BRAKE_RUN ones */
  /* the car's dress-up parts, as clCarConstructParam keeps them: the aero mirror (0 stock,
   * 1), the wing (0 stock, 1..3 the ones won, 4 none) and the bonnet (0 stock, 1..3) */
  int mirror, wing, bonnet;
  /* the lit scenes' lights (data/car_light.lua, the menu's lua): two directional lights,
   * each the direction its light travels in world space and its diffuse colour; the scene
   * ambient; the material the fixed-function parts take (car_light.lua material); and the
   * camera's view matrix for the sphere maps */
  float light_dir[2][3], light_diffuse[2][3], ambient[3];
  float material_diffuse[3], material_ambient[3];
  mat4 view;
  /* the car being drawn, per corner: its tyre's posture relative to the body (rotation, with
   * the hub's height as translation y; x and z are ignored) and the turn about the axle. The
   * WPK_WHEEL chunks turn about their centre by it. NULL: they stand as packed. */
  const float (*wheels)[16];
  const float *wheel_rot;
  /* the wheels turned where they are packed (the menus' cars): the hub's height its own, not
   * the posture's */
  int wheels_hub;
  /* without wheels: the tyres and wheels stand that much lower than packed (the body over
   * them jacked up: menu.c's wheel worn) */
  float wheel_drop;
  /* the car wears a dress-up wheel (wpk_draw_wheels): its WPK_CTIRE tyres, not its own
   * WPK_WHEEL tyres and wheels; wheel_side, a wheel pack's WPK_WHEEL + side - 1 alone (0 all) */
  int wheel_custom, wheel_side;
  /* how much of the overhead map (render_overhead) the cars' reflections take, 0 none: the
   * car it was drawn for alone */
  float over;
  int draws, triangles, new_chunks; /* stats of the last frame */
  int night; /* enhanced lighting's explicit time zone: 0 day, nonzero night; unrelated to wet */
  /* Explicit scene pass exception: menu miniature gradation/runlight overlays.
   * Zero preserves normal depth testing, without inheriting any GL enable bit. */
  int no_depth_test;
  /* Scoped body-root story presentation; caller sets/restores all three.
   * Zero preserves world/object and all pre-existing car draw behavior. */
  uint32_t story_assembly_flags;
  int story_assembly_enabled;
  float story_body_y;
} render_params;

/* Textures loaded from now on at half their size (power-of-two ones 64 or more a side):
 * the iPhone 4's memory. */
void wpk_tex_half(int on);
/* Textures loaded from now on filtered to `degree` anisotropy, trilinear between their
 * mipmaps (1: neither, as the iPad has it). Call it after render_init, with a context. */
void render_aniso(float degree);

/* Extra shader-uniform lighting refinements; 0 restores the original renderer exactly.
 * Independent of HQ options and their performance governor; no targets are allocated. */
void render_enhance(int on);
int render_init(void);
/* Begin one presentation with an explicit default target/extent. GLES no-op;
 * native passes may override it until their matching end. */
void render_display_begin(int width, int height);
#ifdef WMMT_NATIVE_VK
/* Main scene's explicitly authored background/clear, retained for final composite.
 * Reflection, loader and self-test target clears do not change this definition. */
void render_scene_clear(float r, float g, float b, float a);
/* Clear only actual depth on the current explicit scene target. No background,
 * stencil, target selection or viewport change; missing metadata fails closed. */
void render_scene_depth_clear(void);
/* Menu/display clear: explicit target 0, actual color/depth only (not stencil). */
void render_display_clear(float r, float g, float b, float a);
#endif
int wpk_load(wpk_scene *s, const char *path);
#ifdef __ANDROID__
int wpk_load_course_arrows(wpk_scene *s, const char *path);
#endif
/* wpk_load in steps: wpk_open reads the tables, then each wpk_upload call hands about
 * `budget` bytes of textures and buffers to GL and returns 1 once all are up. Draw a scene
 * only after that. */
int wpk_open(wpk_scene *s, const char *path);
int wpk_upload(wpk_scene *s, size_t budget);
void wpk_free(wpk_scene *s);
/* wpk_free a step at a time (the course's ten thousand buffers and textures), `budget` GL
 * objects a call; 1 once all are gone and the scene is freed. */
int wpk_free_step(wpk_scene *s, uint32_t budget);
/* Paint a car (tools/stage/pack_cars.py): 0 is the paint it was packed with; a paint not
 * in GL yet shows as 0. */
void wpk_paint(wpk_scene *s, int k);
/* (after wpk_load) the batches with this texture drawn alpha-blended, though their material
 * says opaque */
void wpk_blend_texture(wpk_scene *s, const char *name);
/* A car's other paints, apart (skip_paints set before its upload): only the car under the
 * car select's cursor and the race's need them. wpk_upload_paints hands about `budget`
 * bytes to GL a call and returns 1 once all are up; wpk_has_paint says whether paint k is;
 * wpk_free_paints drops them again; wpk_warm_paints first-draws up to `budget` of the new
 * ones (as wpk_warm), 0 once none is left cold. */
/* The index of s's texture `name` (the file's name without its extension), or -1. */
int wpk_find_texture(const wpk_scene *s, const char *name);
/* The cars' baked ambient occlusion (the OPTION screen's) on or off. */
void wpk_ao(int on);
/* A copy of s's texture i (RGB565, read again from s's file) with a sticker blended over it
 * (pack_vinyl.py, as the arcade's nsTextureReplace::TextureReplace): `over` ow x oh, premultiplied
 * RGBA, or (rgb set) alpha alone in colour rgb; a new GL texture with its mipmaps, or 0. */
uint32_t wpk_texture_over(wpk_scene *s, int i, const uint8_t *over, int ow, int oh, const uint8_t *rgb);
int wpk_upload_paints(wpk_scene *s, size_t budget);
int wpk_has_paint(const wpk_scene *s, int k);
void wpk_free_paints(wpk_scene *s);
/* s (just opened) borrows its empty textures from base, the same car's stock pack, by name;
 * wpk_share_sync, before each draw of s, takes base's textures as they are then (its paint) */
void wpk_share(wpk_scene *s, const wpk_scene *base);
void wpk_share_sync(wpk_scene *s);
int wpk_warm_paints(wpk_scene *s, int budget);

/* Draw one scene with a model matrix; eye is in the scene's local space.
 * pass: WPK_OPAQUE, WPK_CUTOUT or WPK_BLEND (the batches of that kind). */
void wpk_draw(const wpk_scene *s, const mat4 *view_proj, const mat4 *model, const float *eye_local,
              int pass, render_params *p);
/* Exact mesh group; model and eye are in the chunk's local coordinate system. */
void wpk_draw_group(const wpk_scene *s, const mat4 *vp, const mat4 *model, const float *eye, int pass, render_params *p, uint32_t group);
/* A dress-up wheel's pack (pack_cars.py --wheels: WHEEL_L in WPK_WHEEL, WHEEL_R in + 1, at
 * the hub) on the four corners of a car drawn with `model` (eye_local in the car's frame):
 * hub[axle] = the left hub's x and z, the scale across and in diameter (src/carwheel.h);
 * the corner's posture and turn from p->wheels and p->wheel_rot as the car's own tyres. */
void wpk_draw_wheels(const wpk_scene *w, const mat4 *view_proj, const mat4 *model, const float *eye_local,
                     int pass, render_params *p, const float hub[2][4]);

/* First-draw up to `budget` batches of the chunks that are within their range plus `margin`
 * and were never drawn, into one pixel, a chunk at a time. iOS finishes a texture's or
 * buffer's upload when it is first drawn with, which took a frame's time (up to 30 ms) as a
 * chunk came into view; this moves that work ahead of the car in small steps. Returns how
 * many batches it drew: 0 once nothing in reach is left cold. */
int wpk_prewarm(wpk_scene *s, const mat4 *view_proj, const float *eye_local, float margin, int budget,
                const render_params *p);

/* wpk_prewarm for the loading (app.c), which may run on a thread of its own with a GL
 * context sharing the app's: every cold chunk, `budget` batches at most, with the program
 * render_warm_begin sets up instead of the scene's (it needs no matrix: what lands in the
 * one pixel does not matter). Draw into a framebuffer of one pixel. wpk_warm_near takes
 * the cold chunks nearest `eye` first, and with p only those in reach (as wpk_prewarm);
 * wpk_cold_near counts those still cold. */
void render_warm_begin(void);
int wpk_warm(wpk_scene *s, int budget);
/* The first draw with a texture of its own (the street lights' sprites), after render_warm_begin */
void render_warm_texture(uint32_t tex);
int wpk_warm_near(wpk_scene *s, const float *eye, float margin, int budget, const render_params *p);
int wpk_cold_near(const wpk_scene *s, const float *eye, float margin, const render_params *p);

/* What the first draws (wpk_prewarm, wpk_warm*) cost since the last call, by what was new
 * to GL in them (a buffer pool, a texture, or neither), as text for perf.log. */
void wpk_warm_stats(char *out, size_t n);

/* clRenderShadow (data/system/alpha_stencil.igb): the n cars' shadow volumes (their scenes'
 * WPK_SHADOW chunks, each with its model-view-projection) darken the ground inside them.
 * Draw it after the opaque and alpha-tested passes; it needs a stencil buffer. */
void render_shadows(const wpk_scene *const *s, const mat4 *mvp, int n, render_params *p);

/* clRadialBlur (data/shader/radial_blur.cg): at speed the arcade draws the frame into a
 * texture, then blurs bands along the left and right edges toward the screen's centre.
 * render_blur_begin (amount > 0, from the camera) points the drawing at a w x h texture
 * and returns 1; render_blur_end then puts it on the framebuffer that was bound, blurred.
 * Draw the HUD after it. */
int render_blur_begin(float amount, int w, int h);
void render_blur_end(void);
/* The size the 3D is drawn at between render_blur_begin (that returned 1) and its end
 * (render_hq_level's share of the screen's), for its viewport. */
void render_blur_size(int *w, int *h);
/* A phone of today's (Android): the 3D from then on through a multisampled (samples) half-float
 * target with a bloom (its share bloom) and a highlights' roll-off, by render_blur_begin/end
 * every frame. 0 if the GPU has not what it takes (and nothing changes). */
int render_hq(int samples, float bloom);
/* With render_hq: screen-space ambient occlusion of strength k (0 none, 1 full), from the
 * depth of each frame whose view render_hq_view gave (the race's): near and far planes, the
 * tangents of the half angles across (x) and up (y). */
void render_ssao(float k);
void render_hq_view(float near, float far, float tan_x, float tan_y);
/* Before render_hq: no rendering into textures (EXT_multisampled_render_to_texture), the
 * multisampled buffers and blits as on a GPU without it, to compare. */
void render_hq_blits(void);
/* The frame rate first: render_hq's level 0 (all as asked) to 7, each giving up more (the
 * ambient occlusion; the 3D at 90%, then 84% of the screen's size; 2x multisampling; 75%;
 * no bloom; no reflections of the last frame); the level set. */
int render_hq_level(int level);
/* The settings' switches for render_hq (each 1 on, as render_hq starts): the bloom, the
 * ambient occlusion (render_ssao on as well), the paint's reflection of the last frame and
 * the wet road's (render_params.wet its strength). The samples are render_hq's own (a
 * restart). */
void render_hq_options(int bloom, int ao, int paint, int wet);
/* Sharpen the frame (FSR 1's RCAS, 0 off .. 1 most; not the arcade's): render_blur_begin
 * then takes the frame into its texture (RGBA8) whatever the blur, and render_blur_end
 * sharpens the middle as it puts it on. deep: keep that texture RGBA8 while sharp is 0 for a
 * while (the sharpening switched on but sitting out), not make it anew each way. */
void render_sharpen(float sharp, int deep);

/* Time the ways a texture or a buffer can go to GL (glGenerateMipmap, mip_down's levels,
 * none, PVRTC) and their first draw, into one line of text for perf.log (about 0.2 s). */
void render_selftest(char *out, size_t n);

/* Not the arcade's (Allan's request): what is over a car (bridges, the decks above, signs,
 * tunnel roofs) in its paint's and glass's reflections. The maps' batches above the car and
 * near it are drawn looking ahead and up from over its roof (`car`, its body matrix: y up)
 * into a small texture with alpha where something is; the cars' programs then take it over
 * their environment along the eye's reflection as far as render_params.over says. Draws
 * the n scenes (a map, its signs: their named objects as p->object_visible says) with the
 * framebuffer and viewport given back as they were; returns how many batches it drew, -1
 * when there is no framebuffer for it. */
int render_overhead(const wpk_scene *const *s, int n, const mat4 *car, render_params *p);

/* The back mirror: render_backmirror_begin binds its w x h target (cleared to clear; -1
 * when there is none) for a scene drawn as any other, render_backmirror_end goes back to
 * the frame's; then render_backmirror_draw puts it at x, y, w, h under proj, flipped left
 * to right. */
int render_backmirror_begin(int w, int h, const float clear[3]);
void render_backmirror_end(void);
void render_backmirror_draw(const mat4 *proj, float x, float y, float w, float h);

void render_begin(const render_params *p);
void render_blend_pass(int on);

/* One vertex of render_sprites (the .wpk vertex layout) */
typedef struct {
  float pos[3], uv[2];
  uint8_t rgba[4];
} render_vertex;

/* Up to RENDER_MAX_SPRITES quads of 4 vertices each, already in view space (proj alone
 * takes them to the screen), added onto the scene with one texture: depth tested but not
 * written, no fog, both sides (the street lights' glows). Call between render_begin and
 * the end of the frame's drawing; p's fog is set back afterwards. */
#define RENDER_MAX_SPRITES 4096
void render_sprites(const mat4 *proj, const render_vertex *v, int n_quads, uint32_t tex, render_params *p);
/* the same added by their own colour (glBlendFunc(GL_SRC_COLOR, GL_ONE): clCarSpotLight's) */
void render_sprites_by_colour(const mat4 *proj, const render_vertex *v, int n_quads, uint32_t tex, render_params *p);
/* A bounded world-space triangle list from tail_trail_triangles (up to both
 * lamps), with float RGBA retained through attribute upload. Additive SRC_ALPHA/
 * ONE, depth-tested LEQUAL, no depth writes/culling/fog/grade; the internal white
 * texture is equivalent to untextured colour. All caller GL state is restored,
 * including a non-default VAO. The current target, viewport and scissor are kept.
 * Call on the rendering thread, after render_init, inside the 3D effect pass
 * (before render_blur_end). Returns 1 when a draw is submitted, 0 for no data,
 * invalid inputs or an unavailable renderer; this is not GPU/visual validation.
 * Coordinates must be finite and within +/-1e12, colours finite in [0,1]. */
int render_tail_triangles(const mat4 *vp, const TailTrailVertex *v, size_t n_vertices, render_params *p);
/* Own-car smoke: camera-space quads, original float alpha, nonadditive blend.
 * quads is a QUAD count (4 vertices each); main camera only. CPU submission is
 * not a claim of device/GPU validation. Dedicated resources, no shared cache. */
#include "tire_smoke.h"
int render_tire_smoke(const mat4 *projection, const TireSmokeVertex *vertices, size_t quads,
                      uint32_t texture, render_params *params);
void render_tire_smoke_release(void);
void render_tire_smoke_context_lost(void);
/* Only on the owning rendering context/device: release before its teardown.
 * Surface replacement/pause is NOT context loss; keep these resources then.
 * Once the context/device is already lost, forget IDs WITHOUT deleting them.
 * render_init also forgets them for a newly initialized renderer context. */
void render_tail_release(void);
void render_tail_context_lost(void);
#ifdef __ANDROID__
/* Original tire-track blend/depth/colour-mask state; vertices are world-space,
 * vp is the view-projection matrix, and tex is the dedicated tirepattern image.
 * Call after render_blend_pass(0), while depth testing and back-face culling are on. */
void render_tire_tracks(const mat4 *vp, const render_vertex *v, int n_quads, uint32_t tex, render_params *p);
#endif

#endif
