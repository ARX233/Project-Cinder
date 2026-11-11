/* Player for the arcade's 2D sprite animations (.anm), packed by tools/menupack.py
 * into data/menu.bin. Frames are laid out on the arcade's 640x480 screen and drawn
 * scaled to the 1024x768 display (the same 4:3, x1.6). */
#ifndef ANM_H
#define ANM_H

/* A screen wider than 4:3 (an iPhone's 3:2): the 1024x768 layout in its middle, edge more
 * on each side (0 on the iPad); anm_fill covers all of it. */
void anm_view(float edge);
float anm_edge(void); /* the extra width on each side in 1024-wide layout pixels */
/* 1 if this frame drew a menu bar or a full-width fill out to such a screen's sides (anm.c
 * lays those out 16:9 itself): app.c then leaves the sides as they are */
int anm_wide_drawn(void);
/* Opens data_dir/menu.bin (needs a GL context), optionally appending a validated sprites-only
 * story-cutin.bin and card-pages.bin. Android receives each optional file's independently
 * catalog-verified path from Java; unavailable files stay disabled with no path guessing.
 * Other platforms load the optional files beside data_dir/menu.bin.
 * Invalid card packs leave the existing base and story resources unchanged. */
int anm_load(const char *data_dir);
/* Once a frame: drops the textures of sprites not drawn for three seconds. */
void anm_trim(void);
/* Upload every sprite of an animation now (or keep them from anm_trim): one drawn mid-race
 * would read and upload its sprites in that frame. */
void anm_preload(int anim);
/* Get one packed sprite ready: with upload set, read and upload it and draw it once over a
 * pixel at no opacity (the driver finishes an upload on the texture's first draw); returns 1
 * if that was done now. One up already is kept from anm_trim. */
int anm_warm_sprite(int sprite, int upload);
/* The packed sprites an animation's frames use (each once, at most max); returns how many. */
int anm_sprites(int anim, int *out, int max);
/* The arcade's id of a packed sprite (-1 if none). */
int anm_sprite_id(int sprite);
/* Index of a packed animation by name (as in menupack.py ANIMS), or -1. */
int anm_find(const char *name);
int anm_frames(int anim);
/* Packed index of the arcade's sprite id (or a pre-rendered text, menupack.py TEXT_BASE + k), or -1. */
int anm_sprite(int arcade_id);
/* Borrow the packed sprite's GL texture, loading it on first use. The caller
 * must have the same live GL context used by anm_load current; this API cannot
 * verify context identity or detect context loss. Returns 0 for invalid index,
 * absent current context (where detectable), or failed load. Reacquire each
 * frame: anm_trim may delete a handle not touched for over 180 frames. Do not
 * delete or cache the borrowed handle across trim/context recreation. */
unsigned int anm_sprite_texture(int sprite);
/* Draw one frame; alpha fades the whole layer (1 = as authored). */
void anm_draw(int anim, int frame, float alpha);
/* clSpriteAnime::setImageReplace: draw packed sprite `to` (-1 = nothing) wherever the frame
 * has `from`, sized as `to`. The frame is moved by (dx, dy) on the 640x480 screen. */
typedef struct { int from, to; } anm_swap;
void anm_draw_ex(int anim, int frame, float alpha, float dx, float dy, const anm_swap *swap, int nswap);
/* The same, scaled: each point p of the frame goes to (dx, dy) + zoom * p. */
void anm_draw_xf(int anim, int frame, float alpha, float dx, float dy, float zoom, const anm_swap *swap, int nswap);
/* And scaled by sx across, sy down (clSpriteAnime's setScale and setPos). */
void anm_draw_xy(int anim, int frame, float alpha, float dx, float dy, float sx, float sy, const anm_swap *swap,
                 int nswap);
/* A screen-specific composition may anchor semantic groups without stretching its
 * pictures or disturbing the animation. Match ORIGINAL packed template identities
 * (before image replacement); translate after the record's affine in 640x480
 * units. Only matching records override the old implicit wide-edge decoration.
 * NULL/empty moves retain the ordinary draw path; no global layout state. */
typedef struct { int sprite; float dx, dy; } anm_layout_move;
void anm_draw_layout(int anim, int frame, float alpha, float dx, float dy,
                     const anm_swap *swap, int nswap, const anm_layout_move *moves, int nmoves);
/* One packed sprite, top-left at (x, y) on the 640x480 screen, at its own size. */
void anm_draw_sprite(int sprite, float x, float y, float alpha);
/* The part src (x0, y0, x1, y1 in the sprite's pixels) of a packed sprite, stretched over dst
 * (x0, y0, x1, y1 on the 640x480 screen). */
void anm_draw_part(int sprite, const float src[4], const float dst[4], float alpha);
/* The same in a colour: c * mul + add (an anim record's, anm_sprite_xf) */
void anm_draw_part_col(int sprite, const float src[4], const float dst[4], const float mul[4], const float add[4]);
/* Program-owned UI artwork, separate from the verified imported game resources.
 * x/y/w/h are author-space 640x480 units; no game sprite IDs or sidecar paths
 * are changed. The built-in texture follows the same idle trim lifecycle. */
enum { ANM_BUILTIN_VS_MODE = 0 };
void anm_draw_builtin(int image, float x, float y, float w, float h, float alpha);
/* Where a frame draws packed sprite `sprite`: r = x0, y0, x1, y1 on the 640x480 screen.
 * Returns 0 if the frame has no such sprite. */
int anm_sprite_rect(int anim, int frame, int sprite, float r[4]);
/* the same for the frame's k-th record of that sprite (0 the first; a template may be drawn
 * more than once), with its opacity in *alpha; 0 if there are not k + 1 of them */
int anm_sprite_rect_at(int anim, int frame, int sprite, int k, float r[4], float *alpha);
/* Its opacity there (0 if the frame has no such sprite): a clSpriteFont hung on a template
 * (setImageReplace with a clSpriteAnimeReplace) shows with it. */
float anm_sprite_alpha(int anim, int frame, int sprite);
/* Its record there: xf = x, y, a, b, c, d (a point p of the sprite goes to (x + a px + c py,
 * y + b px + d py)) and its colour, c * mul + add; 0 if the frame has no such sprite. A font hung
 * on a template is drawn with these. */
int anm_sprite_xf(int anim, int frame, int sprite, float xf[6], float mul[4], float add[4]);
/* Nontransparent source bounds in sprite pixels, excluding transparent padding. */
int anm_sprite_content_rect(int sprite, float rect[4]);
/* Width of a packed sprite in 640x480 pixels (0 if there is none). */
float anm_sprite_width(int sprite);
float anm_sprite_height(int sprite);
/* Cover the screen with one colour (a = opacity); the white flash when the game starts. */
void anm_fill(float r, float g, float b, float a);

#endif
