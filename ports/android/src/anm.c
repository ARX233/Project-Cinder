#include "anm.h"

#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

#include "gl.h"
#include "time_texture.h"
#include "ui_vs_mode.inc"

typedef struct {
  uint16_t sprite, blend; /* 0 alpha, 1 added, 2 subtracted (clDrawBuffer::draw's modes 1, 3) */
  float a, b, c, d, x, y;   /* screen = (x, y) + [a c; b d] * (u, v) on 640x480 */
  int16_t mul[4], add[4];   /* colour transform: c * mul / 256 + add / 255 */
} anm_rec;

typedef struct {
  char name[48];
  uint32_t nframes, nrecs;
  uint32_t (*frames)[2]; /* start, count */
  anm_rec *recs;
} anm_anim;

static struct {
  /* Sprites are uploaded when first drawn and dropped when unused for a while, so only
   * the screens on show take texture memory (menu.bin holds about 60 MB of them). */
  GLuint *tex;
  long *offset;      /* of each sprite's pixels in menu.bin */
  uint32_t *zsize;   /* their zlib-packed size, 0 = raw */
  uint32_t *used;    /* clock of the last draw */
  uint32_t clock;
  FILE *file, *extra_file, *card_file, *ghost_file, *mileage_file, *ghost_match_file, *finish_menu_file, *crown_scenes_file; /* independently verified optional resources */
  uint32_t base_sprites, story_end, ghost_begin, mileage_begin, ghost_match_begin, finish_menu_begin, crown_scenes_begin;
  float (*size)[2];
  int *ids; /* the arcade's sprite id of each packed sprite */
  uint16_t (*cols)[2]; /* on a wide screen: its first and past-last columns with any opacity, once up */
  uint16_t (*content)[4]; /* lazy crop bounds for UI that draws a sprite without its padding */
  uint32_t nsprites, nanims;
  anm_anim *anims;
  GLuint prog;
  GLint u_mul, u_add, u_tex, u_view;
  float edge; /* anm_view */
  uint32_t wide_clock; /* the clock when a frame last drew out to the screen's sides */
  GLuint builtin_tex[1];
  uint32_t builtin_used[1];
} A;

static const float SCALE = 1024.0f / 640.0f;

#ifdef WMMT_NATIVE_VK
#include "ui_native_vk_resources.inc"
#include "anm_native_vk.inc"
#else
/* the program, with the 1024-wide layout in the middle of a screen anm_view widens */
static void use_prog(void) {
  glUseProgram(A.prog);
  glUniform2f(A.u_view, 1.0f / (512.0f + A.edge), A.edge / (512.0f + A.edge) - 1.0f);
}
#endif

void anm_view(float edge) { A.edge = edge; }
float anm_edge(void) { return A.edge; }

int anm_wide_drawn(void) { return A.edge > 0.0f && A.wide_clock == A.clock + 1; }

static int read_all(FILE *f, void *p, size_t n) { return fread(p, 1, n, f) == n; }

/* Optional sprites-only WMN3. Validate everything before publishing any indices. */
static void load_extra(const char *data_dir) {
  char path[1024];
  FILE *f = NULL;
#if defined(__ANDROID__)
  extern int android_optional_resource_path(const char *, char *, size_t);
  if (!android_optional_resource_path("story-cutin.bin", path, sizeof path)) return;
  f = fopen(path, "rb");
#else
  if (snprintf(path, sizeof path, "%s/story-cutin.bin", data_dir) >= (int)sizeof path) return;
  f = fopen(path, "rb");
#endif
  if (!f) return;
  uint32_t n, nanims; char magic[4];
  int *ids = NULL; float (*size)[2] = NULL; long *offset = NULL; uint32_t *zs = NULL;
  if (fseek(f, 0, SEEK_END)) goto bad_extra;
  long length = ftell(f);
  if (length < 12 || length > 256L * 1024 * 1024 || fseek(f, 0, SEEK_SET)) goto bad_extra;
  if (!read_all(f, magic, 4) || memcmp(magic, "WMN3", 4) || !read_all(f, &n, 4) ||
      n > 65535 - A.nsprites) goto bad_extra;
  if (!n) goto bad_extra;
  ids = calloc(n, sizeof *ids); size = calloc(n, sizeof *size);
  offset = calloc(n, sizeof *offset); zs = calloc(n, sizeof *zs);
  if (!ids || !size || !offset || !zs) goto bad_extra;
  for (uint32_t i = 0; i < n; ++i) {
    uint16_t wh[2];
    if (!read_all(f, &ids[i], 4) || !read_all(f, wh, 4) || !read_all(f, &zs[i], 4) ||
        ids[i] < 0 || !wh[0] || !wh[1] || wh[0] > 2048 || wh[1] > 2048) goto bad_extra;
    for (uint32_t j = 0; j < A.nsprites; ++j) if (ids[i] == A.ids[j]) goto bad_extra;
    for (uint32_t j = 0; j < i; ++j) if (ids[i] == ids[j]) goto bad_extra;
    size_t raw = (size_t)wh[0] * wh[1] * 4, stored = zs[i] ? zs[i] : raw;
    if (zs[i] && stored > compressBound((uLong)raw)) goto bad_extra;
    offset[i] = ftell(f);
    if (offset[i] < 0 || offset[i] > length || stored > (size_t)(length - offset[i])) goto bad_extra;
    size[i][0] = wh[0]; size[i][1] = wh[1];
    /* Fail closed on corrupt compressed pixels, not only on a valid header. */
    if (zs[i]) {
      unsigned char *z = malloc(stored), *pixels = malloc(raw); uLongf out = (uLongf)raw;
      int ok = z && pixels && read_all(f, z, stored) && uncompress(pixels, &out, z, stored) == Z_OK && out == raw;
      free(z); free(pixels);
      if (!ok) goto bad_extra;
    } else if (fseek(f, (long)stored, SEEK_CUR)) goto bad_extra;
  }
  if (!read_all(f, &nanims, 4) || nanims || ftell(f) != length) goto bad_extra;
  uint32_t total = A.nsprites + n;
  GLuint *tex = calloc(total, sizeof *tex); long *offs = calloc(total, sizeof *offs);
  uint32_t *zsize = calloc(total, sizeof *zsize), *used = calloc(total, sizeof *used);
  float (*sizes)[2] = calloc(total, sizeof *sizes); int *allids = calloc(total, sizeof *allids);
  uint16_t (*cols)[2] = calloc(total, sizeof *cols);
  if (!tex || !offs || !zsize || !used || !sizes || !allids || !cols) {
    free(tex); free(offs); free(zsize); free(used); free(sizes); free(allids); free(cols);
    goto bad_extra;
  }
#define COPY_BASE(dst, src) memcpy(dst, src, A.nsprites * sizeof *(src))
  COPY_BASE(tex, A.tex); COPY_BASE(offs, A.offset); COPY_BASE(zsize, A.zsize);
  COPY_BASE(used, A.used); COPY_BASE(sizes, A.size); COPY_BASE(allids, A.ids); COPY_BASE(cols, A.cols);
#undef COPY_BASE
  memcpy(offs + A.nsprites, offset, n * sizeof *offset);
  memcpy(zsize + A.nsprites, zs, n * sizeof *zs);
  memcpy(sizes + A.nsprites, size, n * sizeof *size);
  memcpy(allids + A.nsprites, ids, n * sizeof *ids);
  free(A.tex); free(A.offset); free(A.zsize); free(A.used); free(A.size); free(A.ids); free(A.cols);
  A.tex = tex; A.offset = offs; A.zsize = zsize; A.used = used; A.size = sizes; A.ids = allids; A.cols = cols;
  A.base_sprites = A.nsprites; A.nsprites = total; A.extra_file = f;
  free(ids); free(size); free(offset); free(zs);
  return;
 bad_extra:
  fprintf(stderr, "Ignoring invalid story-cutin.bin\n");
  free(ids); free(size); free(offset); free(zs); fclose(f);
}


/* WCP1 v1: sprite blobs then named animations; records carry original int32 IDs.
 * Parse and validate into private storage: failure never publishes partial state. */
static FILE *load_sprite_animations(const char *data_dir, const char *name, int allow_sprites_only) {
  char path[1024]; FILE *f = NULL;
#if defined(__ANDROID__)
  extern int android_optional_resource_path(const char *, char *, size_t);
  if (!android_optional_resource_path(name, path, sizeof path)) return NULL;
  f = fopen(path, "rb");
#else
  if (snprintf(path, sizeof path, "%s/%s", data_dir, name) >= (int)sizeof path) return NULL;
  f = fopen(path, "rb");
#endif
  if (!f) return NULL;
  char magic[4]; uint32_t version, n = 0, na = 0, total; long length;
  int *ids = NULL; float (*sizes)[2] = NULL; long *offs = NULL; uint32_t *zs = NULL;
  anm_anim *anims = NULL;
  GLuint *tex = NULL; long *alloff = NULL; uint32_t *allzs = NULL, *used = NULL;
  float (*allsize)[2] = NULL; int *allids = NULL; uint16_t (*cols)[2] = NULL; anm_anim *allanims = NULL;
  if (fseek(f, 0, SEEK_END) || (length = ftell(f)) < 16 || length > 256L*1024*1024 || fseek(f,0,SEEK_SET)) goto bad_card;
  if (!read_all(f,magic,4) || memcmp(magic,"WCP1",4) || !read_all(f,&version,4) || version != 1 ||
      !read_all(f,&n,4) || n > 65535-A.nsprites || !read_all(f,&na,4) || (!na && (!allow_sprites_only || !n)) || na > 4096-A.nanims) goto bad_card;
  ids=calloc(n ? n : 1,sizeof *ids); sizes=calloc(n ? n : 1,sizeof *sizes);
  offs=calloc(n ? n : 1,sizeof *offs); zs=calloc(n ? n : 1,sizeof *zs); anims=calloc(na ? na : 1,sizeof *anims);
  if (!ids || !sizes || !offs || !zs || !anims) goto bad_card;
  for (uint32_t i=0;i<n;i++) {
    uint16_t wh[2];
    if (!read_all(f,&ids[i],4) || !read_all(f,wh,4) || !read_all(f,&zs[i],4) || ids[i]<0 || !wh[0] || !wh[1] || wh[0]>2048 || wh[1]>2048) goto bad_card;
    for (uint32_t j=0;j<A.nsprites;j++) if (ids[i]==A.ids[j]) goto bad_card;
    for (uint32_t j=0;j<i;j++) if (ids[i]==ids[j]) goto bad_card;
    size_t raw=(size_t)wh[0]*wh[1]*4, stored=zs[i] ? zs[i] : raw;
    if (zs[i] && stored>compressBound((uLong)raw)) goto bad_card;
    offs[i]=ftell(f); if (offs[i]<0 || offs[i]>length || stored>(size_t)(length-offs[i])) goto bad_card;
    sizes[i][0]=wh[0]; sizes[i][1]=wh[1];
    if (zs[i]) {
      unsigned char *z=malloc(stored), *px=malloc(raw); uLongf out=(uLongf)raw;
      int ok=0;
      if (z && px && read_all(f,z,stored)) {
        z_stream stream={0}; stream.next_in=z; stream.avail_in=(uInt)stored; stream.next_out=px; stream.avail_out=(uInt)raw;
        if (inflateInit(&stream)==Z_OK) { int rc=inflate(&stream,Z_FINISH);
          ok=rc==Z_STREAM_END && stream.total_in==stored && stream.total_out==out; inflateEnd(&stream); }
      }
      free(z); free(px); if (!ok) goto bad_card;
    } else if (fseek(f,(long)raw,SEEK_CUR)) goto bad_card;
  }
  for (uint32_t i=0;i<na;i++) {
    anm_anim *a=&anims[i];
    if (!read_all(f,a->name,48) || !memchr(a->name,0,48) || !a->name[0] ||
        !read_all(f,&a->nframes,4) || !a->nframes || a->nframes>10000 ||
        !read_all(f,&a->nrecs,4) || a->nrecs>200000) goto bad_card;
    for (uint32_t j=0;j<A.nanims;j++) if (!strcmp(a->name,A.anims[j].name)) goto bad_card;
    for (uint32_t j=0;j<i;j++) if (!strcmp(a->name,anims[j].name)) goto bad_card;
    a->frames=calloc(a->nframes,sizeof *a->frames); a->recs=calloc(a->nrecs ? a->nrecs : 1,sizeof *a->recs);
    if (!a->frames || !a->recs || !read_all(f,a->frames,(size_t)a->nframes*8)) goto bad_card;
    for (uint32_t j=0;j<a->nframes;j++) if (a->frames[j][0]>a->nrecs || a->frames[j][1]>a->nrecs-a->frames[j][0]) goto bad_card;
    for (uint32_t j=0;j<a->nrecs;j++) {
      int32_t sid; anm_rec *r=&a->recs[j]; uint32_t k;
      if (!read_all(f,&sid,4) || !read_all(f,&r->blend,2) || r->blend>2 ||
          !read_all(f,&r->a,24) || !read_all(f,r->mul,16)) goto bad_card;
      if (!isfinite(r->a) || !isfinite(r->b) || !isfinite(r->c) || !isfinite(r->d) || !isfinite(r->x) || !isfinite(r->y)) goto bad_card;
      for (k=0;k<A.nsprites;k++) if (A.ids[k]==sid) break;
      if (k==A.nsprites) { uint32_t j2; for (j2=0;j2<n;j2++) if (ids[j2]==sid) break;
        if (j2==n) goto bad_card; k+=j2; }
      r->sprite=(uint16_t)k;
    }
  }
  if (ftell(f)!=length) goto bad_card;
  total=A.nsprites+n;
  tex=calloc(total,sizeof *tex); alloff=calloc(total,sizeof *alloff); allzs=calloc(total,sizeof *allzs);
  used=calloc(total,sizeof *used); allsize=calloc(total,sizeof *allsize); allids=calloc(total,sizeof *allids);
  cols=calloc(total,sizeof *cols); allanims=calloc(A.nanims+na ? A.nanims+na : 1,sizeof *allanims);
  if (!tex || !alloff || !allzs || !used || !allsize || !allids || !cols || !allanims) goto bad_card;
#define CP(dst,src) memcpy(dst,src,A.nsprites*sizeof *(src))
  CP(tex,A.tex); CP(alloff,A.offset); CP(allzs,A.zsize); CP(used,A.used); CP(allsize,A.size); CP(allids,A.ids); CP(cols,A.cols);
#undef CP
  memcpy(alloff+A.nsprites,offs,n*sizeof *offs); memcpy(allzs+A.nsprites,zs,n*sizeof *zs);
  memcpy(allsize+A.nsprites,sizes,n*sizeof *sizes); memcpy(allids+A.nsprites,ids,n*sizeof *ids);
  memcpy(allanims,A.anims,A.nanims*sizeof *anims); memcpy(allanims+A.nanims,anims,na*sizeof *anims);
  free(A.tex); free(A.offset); free(A.zsize); free(A.used); free(A.size); free(A.ids); free(A.cols); free(A.anims);
  A.tex=tex; A.offset=alloff; A.zsize=allzs; A.used=used; A.size=allsize; A.ids=allids; A.cols=cols;
  A.anims=allanims; A.nsprites=total; A.nanims+=na;
  free(ids); free(sizes); free(offs); free(zs); free(anims); return f;
bad_card:
  fprintf(stderr,"Ignoring invalid %s\n",name);
  if (anims) for (uint32_t i=0;i<na;i++) { free(anims[i].frames); free(anims[i].recs); }
  free(anims); free(ids); free(sizes); free(offs); free(zs); free(tex); free(alloff); free(allzs); free(used); free(allsize); free(allids); free(cols); free(allanims); fclose(f);
  return NULL;
}

#include "ghost_ui_loader.inc"

int anm_load(const char *data_dir) {
  free(A.content);
  A.content = NULL;
  static const char *vs =
    "attribute vec2 aPos; attribute vec2 aUV; varying vec2 vUV;\n"
    "uniform vec2 uView;\n"
    "void main() { vUV = aUV; gl_Position = vec4(aPos.x * uView.x + uView.y, 1.0 - aPos.y / 384.0, 0.0, 1.0); }\n";
  static const char *fs =
    "precision mediump float; uniform sampler2D uTex; uniform vec4 uMul, uAdd; varying vec2 vUV;\n"
    "void main() { gl_FragColor = clamp(texture2D(uTex, vUV) * uMul + uAdd, 0.0, 1.0); }\n";
  const char *attribs[] = { "aPos", "aUV" };
#ifdef WMMT_NATIVE_VK
  A.prog = cinder_vk_program_create(vs, fs, attribs, 2);
#else
  A.prog = gl_compile_program(vs, fs, attribs, 2);
#endif
  if (!A.prog) return -1;
#ifndef WMMT_NATIVE_VK
  A.u_mul = glGetUniformLocation(A.prog, "uMul");
  A.u_add = glGetUniformLocation(A.prog, "uAdd");
  A.u_tex = glGetUniformLocation(A.prog, "uTex");
  A.u_view = glGetUniformLocation(A.prog, "uView");
#endif

  char path[1024];
  snprintf(path, sizeof path, "%s/menu.bin", data_dir);
  FILE *f = fopen(path, "rb");
  if (!f) return -1;
  char magic[4];
  if (!read_all(f, magic, 4) || memcmp(magic, "WMN3", 4) || !read_all(f, &A.nsprites, 4) || A.nsprites > 65535) goto fail;
  A.tex = calloc(A.nsprites, sizeof *A.tex);
  A.offset = calloc(A.nsprites, sizeof *A.offset);
  A.zsize = calloc(A.nsprites, sizeof *A.zsize);
  A.used = calloc(A.nsprites, sizeof *A.used);
  A.size = calloc(A.nsprites, sizeof *A.size);
  A.ids = calloc(A.nsprites, sizeof *A.ids);
  A.cols = calloc(A.nsprites, sizeof *A.cols);
  for (uint32_t i = 0; i < A.nsprites; ++i) {
    uint16_t wh[2];
    if (!read_all(f, &A.ids[i], 4) || !read_all(f, wh, 4) || wh[0] > 2048 || wh[1] > 2048) goto fail;
    if (!read_all(f, &A.zsize[i], 4)) goto fail;
    A.offset[i] = ftell(f);
    if (fseek(f, A.zsize[i] ? (long)A.zsize[i] : (long)wh[0] * wh[1] * 4, SEEK_CUR) != 0) goto fail;
    A.size[i][0] = wh[0];
    A.size[i][1] = wh[1];
  }
  if (!read_all(f, &A.nanims, 4) || A.nanims > 4096) goto fail;
  A.anims = calloc(A.nanims, sizeof *A.anims);
  for (uint32_t i = 0; i < A.nanims; ++i) {
    anm_anim *an = &A.anims[i];
    if (!read_all(f, an->name, 48) || !read_all(f, &an->nframes, 4) || !read_all(f, &an->nrecs, 4)) goto fail;
    an->name[47] = 0;
    an->frames = malloc(an->nframes * sizeof *an->frames);
    an->recs = malloc(an->nrecs * sizeof *an->recs);
    if (!an->frames || !an->recs || !read_all(f, an->frames, an->nframes * sizeof *an->frames) ||
        !read_all(f, an->recs, an->nrecs * sizeof *an->recs))
      goto fail;
    for (uint32_t k = 0; k < an->nframes; ++k)
      if (an->frames[k][0] + an->frames[k][1] > an->nrecs) goto fail;
  }
  A.file = f;
  A.base_sprites = A.nsprites;
  load_extra(data_dir);
  A.story_end = A.nsprites;
  A.card_file = load_sprite_animations(data_dir, "card-pages.bin", 0);
  load_ghost_ui(data_dir);
  A.mileage_begin = A.nsprites;
  A.mileage_file = load_sprite_animations(data_dir, "mileage-menu.bin", 0);
  A.ghost_match_begin = A.nsprites;
  A.ghost_match_file = load_sprite_animations(data_dir, "ghost-match.bin", 1);
  /* Prepared packs can already supply these exact sprites via card-pages.bin. */
  A.finish_menu_begin = A.nsprites;
  if (anm_find("cons_g_last_000m") < 0)
    A.finish_menu_file = load_sprite_animations(data_dir, "finish-menu.bin", 0);
  A.crown_scenes_begin = A.nsprites;
  A.crown_scenes_file = load_sprite_animations(data_dir, "crown-scenes.bin", 0);
  return 0;
fail:
  fprintf(stderr, "menu.bin is damaged\n");
  fclose(f);
  A.nanims = 0;
  return -1;
}

static int read_sprite_pixels(int i, unsigned char *px, size_t n) {
  unsigned char *z = A.zsize[i] ? malloc(A.zsize[i]) : NULL;
  uLongf got = (uLongf)n;
  FILE *f = (uint32_t)i < A.base_sprites ? A.file :
            A.crown_scenes_file && (uint32_t)i >= A.crown_scenes_begin ? A.crown_scenes_file :
            A.finish_menu_file && (uint32_t)i >= A.finish_menu_begin ? A.finish_menu_file :
            A.ghost_match_file && (uint32_t)i >= A.ghost_match_begin ? A.ghost_match_file :
            A.mileage_file && (uint32_t)i >= A.mileage_begin ? A.mileage_file :
            (A.ghost_file && (uint32_t)i >= A.ghost_begin ? A.ghost_file :
             (!A.card_file || (uint32_t)i < A.story_end ? A.extra_file : A.card_file));
  int ok = f && fseek(f, A.offset[i], SEEK_SET) == 0 &&
           (A.zsize[i] ? z && read_all(f, z, A.zsize[i]) && uncompress(px, &got, z, A.zsize[i]) == Z_OK && got == n
                       : read_all(f, px, n));
  free(z);
  return ok;
}

int anm_sprite_content_rect(int sprite, float rect[4]) {
  if (!rect || sprite < 0 || (uint32_t)sprite >= A.nsprites) return 0;
  int w = (int)A.size[sprite][0], h = (int)A.size[sprite][1];
  if (w <= 0 || h <= 0) return 0;
  if (!A.content) A.content = calloc(A.nsprites, sizeof *A.content);
  if (!A.content) return 0;
  uint16_t *bounds = A.content[sprite];
  if (!bounds[2]) {
    size_t bytes = (size_t)w * h * 4;
    unsigned char *pixels = malloc(bytes);
    if (!pixels || !read_sprite_pixels(sprite, pixels, bytes)) {
      free(pixels);
      return 0;
    }
    int left = w, top = h, right = 0, bottom = 0;
    for (int y = 0; y < h; ++y)
      for (int x = 0; x < w; ++x)
        if (pixels[((size_t)y * w + x) * 4 + 3] > 8) {
          if (x < left) left = x;
          if (y < top) top = y;
          if (x + 1 > right) right = x + 1;
          bottom = y + 1;
        }
    free(pixels);
    bounds[0] = (uint16_t)left;
    bounds[1] = (uint16_t)top;
    bounds[2] = right ? (uint16_t)right : UINT16_MAX;
    bounds[3] = (uint16_t)bottom;
  }
  if (!bounds[3]) return 0;
  for (int i = 0; i < 4; ++i) rect[i] = bounds[i];
  return 1;
}

/* Restore the classic VS overlays with old and new imported packs. The arcade's
 * disc, ring, preview and caption band still come from the installed resources. */
static int vs_select_pixels(int i, unsigned char *px) {
  int id = A.ids[i];
  if (id >= 107011 && id <= 107012 && A.size[i][0] == 256 && A.size[i][1] == 256) {
    const unsigned pixels = 256 * 256;
    const vs_art *art = &VS_SELECT_ICONS[id - 107011];
    uLongf got = pixels * 2;
    if (uncompress(px, &got, art->data, art->size) != Z_OK || got != pixels * 2) return 0;
    /* Expand grey/alpha in place, starting at the end to preserve unread bytes. */
    for (unsigned p = pixels; p-- > 0;) {
      unsigned char grey = px[p * 2], alpha = px[p * 2 + 1];
      px[p * 4] = px[p * 4 + 1] = px[p * 4 + 2] = grey;
      px[p * 4 + 3] = alpha;
    }
    return 1;
  }
  enum { BAND_W = 512, BAND_H = 64 };
  if (id < 107021 || id > 107022 || A.size[i][0] != BAND_W || A.size[i][1] != BAND_H) return 0;
  int band = anm_sprite(2317); /* menu_p_mode_txt_tg */
  if (band < 0 || A.size[band][0] != BAND_W || A.size[band][1] != BAND_H ||
      !read_sprite_pixels(band, px, BAND_W * BAND_H * 4)) return 0;

  /* As in tools/vsdiscs.py, combine the band alpha above and left of its
   * original lettering, then composite a white port-authored caption. */
  unsigned char rows[BAND_H], cols[BAND_W];
  for (int y = 0; y < BAND_H; ++y) rows[y] = px[(y * BAND_W + 100) * 4 + 3];
  for (int x = 0; x < BAND_W; ++x) cols[x] = px[(2 * BAND_W + x) * 4 + 3];
  const vs_art *art = &VS_SELECT_CAPTIONS[id - 107021];
  uLongf got = BAND_W * BAND_H;
  if (uncompress(px, &got, art->data, art->size) != Z_OK || got != BAND_W * BAND_H) return 0;
  for (int p = BAND_W * BAND_H; p-- > 0;) {
    int band_alpha = rows[p / BAND_W] * cols[p % BAND_W];
    band_alpha = (band_alpha + 32) / 64;
    if (band_alpha > 255) band_alpha = 255;
    int text = px[p], alpha = text * 255 + band_alpha * (255 - text);
    unsigned char grey = alpha ? (text * 255 * 255 + alpha / 2) / alpha : 0;
    px[p * 4] = px[p * 4 + 1] = px[p * 4 + 2] = grey;
    px[p * 4 + 3] = (alpha + 127) / 255;
  }
  return 1;
}

/* Upload the sprite's texture on first use (0 if its pixels cannot be read). */
static GLuint texture(int i) {
  A.used[i] = A.clock;
  if (A.tex[i]) return A.tex[i];
  size_t n = (size_t)A.size[i][0] * (size_t)A.size[i][1] * 4;
  unsigned char *px = malloc(n);
  if (!px || (!vs_select_pixels(i, px) && !read_sprite_pixels(i, px, n))) {
    free(px);
    return 0;
  }
  /* The old menu packer unblended sprite 1573 despite its existing alpha. */
  if ((uint32_t)i < A.base_sprites)
    time_texture_fix(A.ids[i], (int)A.size[i][0], (int)A.size[i][1], px);
  if (A.edge > 0.0f && !A.cols[i][1]) {
    int w = (int)A.size[i][0], h = (int)A.size[i][1], c0 = w, c1 = 0;
    for (int y = 0; y < h; ++y)
      for (int x = 0; x < w; ++x)
        if (px[((size_t)y * w + x) * 4 + 3] > 8) {
          if (x < c0) c0 = x;
          if (x + 1 > c1) c1 = x + 1;
        }
    A.cols[i][0] = (uint16_t)(c0 < c1 ? c0 : 0), A.cols[i][1] = (uint16_t)(c0 < c1 ? c1 : w);
  }
#ifdef WMMT_NATIVE_VK
  A.tex[i] = ui_native_texture_rgba8((unsigned)A.size[i][0], (unsigned)A.size[i][1], px);
#else
  glGenTextures(1, &A.tex[i]);
  glBindTexture(GL_TEXTURE_2D, A.tex[i]);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, (GLsizei)A.size[i][0], (GLsizei)A.size[i][1], 0, GL_RGBA,
               GL_UNSIGNED_BYTE, px);
#endif
  free(px);
  return A.tex[i];
}

unsigned int anm_sprite_texture(int sprite) {
  if (sprite < 0 || (uint32_t)sprite >= A.nsprites || !A.tex || !A.used ||
      !A.size || !A.offset || !A.zsize || !A.ids || !A.cols) return 0;
#ifndef WMMT_NATIVE_VK
  if (!glGetString(GL_VERSION)) return 0;
#endif
  return texture(sprite);
}

void anm_trim(void) {
  A.clock++;
  if (A.clock % 60) return;
  for (uint32_t i = 0; i < A.nsprites; ++i)
    if (A.tex[i] && A.clock - A.used[i] > 180) {
#ifdef WMMT_NATIVE_VK
      cinder_vk_texture_destroy(A.tex[i]);
#else
      glDeleteTextures(1, &A.tex[i]);
#endif
      A.tex[i] = 0;
    }
  if (A.builtin_tex[0] && A.clock - A.builtin_used[0] > 180) {
#ifdef WMMT_NATIVE_VK
    cinder_vk_texture_destroy(A.builtin_tex[0]);
#else
    glDeleteTextures(1, &A.builtin_tex[0]);
#endif
    A.builtin_tex[0] = 0;
  }
}

/* the patched iOS SDK has no plain strcmp for armv7 */
static int same_name(const char *a, const char *b) {
  while (*a && *a == *b) a++, b++;
  return *a == *b;
}

void anm_preload(int anim) {
  if (anim < 0 || (uint32_t)anim >= A.nanims) return;
  const anm_anim *an = &A.anims[anim];
  for (uint32_t i = 0; i < an->nrecs; ++i)
    if (an->recs[i].sprite < A.nsprites) texture(an->recs[i].sprite);
}

int anm_warm_sprite(int sprite, int upload) {
  if (sprite < 0 || (uint32_t)sprite >= A.nsprites) return 0;
  if (A.tex[sprite]) {
    A.used[sprite] = A.clock;
    return 0;
  }
  if (!upload) return 0;
#ifdef WMMT_NATIVE_VK
  static const float v[16] = { 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 1, 1 };
  const float mul[4] = { 1, 1, 1, 0 }, add[4] = { 0, 0, 0, 0 };
  anm_native_quad(v, texture(sprite), mul, add, 0, VK_TRUE);
#else
  use_prog();
  glUniform1i(A.u_tex, 0);
  glActiveTexture(GL_TEXTURE0);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glDisableVertexAttribArray(2);
  static const float v[16] = { 0, 0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 1, 1 };
  glUniform4f(A.u_mul, 1, 1, 1, 0);
  glUniform4f(A.u_add, 0, 0, 0, 0);
  glBindTexture(GL_TEXTURE_2D, texture(sprite));
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, v);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, v + 2);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
#endif
  return 1;
}

int anm_sprites(int anim, int *out, int max) {
  if (anim < 0 || (uint32_t)anim >= A.nanims) return 0;
  const anm_anim *an = &A.anims[anim];
  int n = 0;
  for (uint32_t i = 0; i < an->nrecs; ++i) {
    int s = an->recs[i].sprite, seen = s >= (int)A.nsprites;
    for (int k = 0; k < n && !seen; ++k) seen = out[k] == s;
    if (!seen && n < max) out[n++] = s;
  }
  return n;
}

int anm_sprite_id(int sprite) { return sprite >= 0 && (uint32_t)sprite < A.nsprites ? A.ids[sprite] : -1; }

int anm_find(const char *name) {
  for (uint32_t i = 0; i < A.nanims; ++i)
    if (same_name(A.anims[i].name, name)) return (int)i;
  return -1;
}

int anm_frames(int anim) { return anim >= 0 && (uint32_t)anim < A.nanims ? (int)A.anims[anim].nframes : 0; }

/* a and b the same picture: menu.bin can hold an id twice (a font's sheet and its 32 x 32
 * template, both menu_f_28's 0x49), anm_sprite finding the first */
static int same_sprite(int a, int b) {
  return a == b || (a >= 0 && b >= 0 && (uint32_t)a < A.nsprites && (uint32_t)b < A.nsprites && A.ids[a] == A.ids[b]);
}

int anm_sprite(int arcade_id) {
  for (uint32_t i = 0; i < A.nsprites; ++i)
    if (A.ids[i] == arcade_id) return (int)i;
  return -1;
}

void anm_draw(int anim, int frame, float alpha) { anm_draw_ex(anim, frame, alpha, 0, 0, 0, 0); }

void anm_draw_ex(int anim, int frame, float alpha, float dx, float dy, const anm_swap *swap, int nswap) {
  anm_draw_xf(anim, frame, alpha, dx, dy, 1.0f, swap, nswap);
}

/* A screen wider than 4:3 (anm_view): the menus' bars go to its edges, as a 16:9 layout of the
 * arcade's would have them. The title bar (menu_p_title_bar, its lines all across) runs on from
 * both its ends; the bottom bar (menu_p_bottom_bar, a capsule wider than the screen, its
 * pattern two pixels across) takes its two ends out by the edge and its middle in between;
 * the time plate (menu_p_time_plate, cut by the 4:3's right edge) and what sits on it go
 * out to the screen's right. Records of a frame that turn or skew are drawn as they are. */
enum { WIDE_NONE, WIDE_RIGHT, WIDE_TITLE_BAR, WIDE_BOTTOM_BAR };

static int wide_kind(int sprite) {
  switch (A.ids[sprite]) {
  case 1908: case 1573: case 1905: case 1906: case 1907:
    return WIDE_RIGHT;
  case 1574:
    return WIDE_TITLE_BAR;
  case 1748:
    return WIDE_BOTTOM_BAR;
  default:
    return WIDE_NONE;
  }
}

/* the edge on the 640x480 screen */
static float wide_edge(void) { return A.edge / SCALE; }

/* how far a record of `sprite` (the frame's own, before any swap) moves across */
static float wide_dx(const anm_rec *r, int sprite) {
  if (A.edge <= 0.0f || r->b != 0.0f || r->c != 0.0f || sprite < 0 || (uint32_t)sprite >= A.nsprites) return 0.0f;
  return wide_kind(sprite) == WIDE_RIGHT ? wide_edge() : 0.0f;
}

/* columns u0..u1 of the sprite drawn where its columns d0..d1 would be, at opacity f */
typedef struct { float u0, u1, d0, d1, f; } wide_piece;
#define WIDE_FADE 24 /* steps of a picture's edge fading out, over half a side */
#define WIDE_PIECES (1 + 2 * WIDE_FADE)

/* plain: the frame drawn where it was laid out (no move or scale): one with a picture right
 * up to a 4:3 edge (a full-bleed photo or band) has its edge column drawn on out across the
 * side, fading (a mirror would show its text and lights backwards) */
static int wide_pieces(const anm_rec *r, int sprite, int plain, wide_piece pc[WIDE_PIECES]) {
  float w = A.size[sprite][0];
  pc[0] = (wide_piece){ 0, w, 0, w, 1 };
  int own = r->sprite;
  if (A.edge <= 0.0f || r->b != 0.0f || r->c != 0.0f || r->a <= 0.0f || own >= (int)A.nsprites || own != sprite)
    return 1;
  float e = wide_edge(), x0 = r->x, x1 = r->x + r->a * w;
  switch (wide_kind(own)) {
  case WIDE_RIGHT:
    pc[0].d0 += e / r->a, pc[0].d1 += e / r->a;
    return 1;
  case WIDE_TITLE_BAR: {
    A.wide_clock = A.clock + 1;
    /* on past each end at the 4:3's edge or beyond: lines from just in from its left end (as
     * bright as there; its middle is a shade darker), drawn out */
    int n = 1;
    if (x0 <= 0.5f) pc[n++] = (wide_piece){ 8, 24, (-e - r->x) / r->a, 4.0f / r->a, 1 }; /* (over its lit end) */
    if (x1 >= 640.0f - 64.0f) pc[n++] = (wide_piece){ 8, 24, w, w + (640.0f + e - x1) / r->a, 1 };
    return n;
  }
  case WIDE_BOTTOM_BAR: {
    A.wide_clock = A.clock + 1;
    /* an even shift keeps the two-pixel pattern unbroken where the pieces meet */
    float sh = 2.0f * floorf(e / 2.0f + 0.5f), c = w * 0.5f;
    if (sh > c * 0.4f) sh = c * 0.4f;
    pc[0] = (wide_piece){ 0, c, -sh, c - sh, 1 };
    pc[1] = (wide_piece){ c - sh, c + sh, c - sh, c + sh, 1 };
    pc[2] = (wide_piece){ c, w, c + sh, w + sh, 1 };
    return 3;
  }
  default: {
    if (!plain) return 1;
    if (r->a >= 4.0f && x0 <= 1.0f && x1 >= 639.0f) {
      /* a few texels stretched over the whole 4:3 (menu_p_bg_line, the attract's white and
       * black): over the whole screen */
      pc[0].d0 = (-e - r->x) / r->a, pc[0].d1 = (640.0f + e - r->x) / r->a;
      A.wide_clock = A.clock + 1;
      return 1;
    }
    /* by where its picture is in it (a 640-wide photo in a 1024 texture) */
    float u0 = A.cols[sprite][0], u1 = A.cols[sprite][1];
    if (r->a * (u1 - u0) < 560.0f) return 1; /* (a photo across the 4:3; a silhouette's would streak) */
    float c0 = r->x + r->a * u0, c1 = r->x + r->a * u1, k = 0.5f * e / r->a / WIDE_FADE;
    int n = 1;
    for (int i = 0; i < WIDE_FADE; ++i) {
      float f = 1.0f - ((float)i + 0.5f) / WIDE_FADE;
      /* a column a few in: the picture's own edge may be a lit line */
      if (fabsf(c0) < 4.0f) pc[n++] = (wide_piece){ u0 + 3.5f, u0 + 3.5f, u0 - k * (i + 1), u0 - k * i, f };
      if (fabsf(c1 - 640.0f) < 4.0f) pc[n++] = (wide_piece){ u1 - 3.5f, u1 - 3.5f, u1 + k * i, u1 + k * (i + 1), f };
    }
    return n;
  }
  }
}

void anm_draw_xf(int anim, int frame, float alpha, float dx, float dy, float zoom, const anm_swap *swap, int nswap) {
  anm_draw_xy(anim, frame, alpha, dx, dy, zoom, zoom, swap, nswap);
}

static void draw_xy_layout(int anim, int frame, float alpha, float dx, float dy, float sx, float sy,
                           const anm_swap *swap, int nswap, const anm_layout_move *moves, int nmoves) {
  if (anim < 0 || (uint32_t)anim >= A.nanims) return;
  const anm_anim *an = &A.anims[anim];
  if (frame < 0) frame = 0;
  if ((uint32_t)frame >= an->nframes) frame = (int)an->nframes - 1;
#ifndef WMMT_NATIVE_VK
  use_prog();
  glUniform1i(A.u_tex, 0);
  glActiveTexture(GL_TEXTURE0);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  /* the 3D renderer leaves its buffers bound and a third attribute on */
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glDisableVertexAttribArray(2);
  int blend = 0;
#endif
  const anm_rec *r = an->recs + an->frames[frame][0];
  int plain = dx == 0.0f && dy == 0.0f && sx == 1.0f && sy == 1.0f;
  for (uint32_t k = 0; k < an->frames[frame][1]; ++k, ++r) {
    int sprite = r->sprite;
    float mx = 0.0f, my = 0.0f;
    if (moves) for (int i = 0; i < nmoves; ++i) {
      if (same_sprite(moves[i].sprite, r->sprite)) {
        if (isfinite(moves[i].dx) && isfinite(moves[i].dy)) {
          mx = moves[i].dx; my = moves[i].dy;
        }
        break; /* a group belongs to the authored template, not its replacement */
      }
    }
    for (int i = 0; i < nswap; ++i)
      if (same_sprite(swap[i].from, sprite)) {
        sprite = swap[i].to; /* once: a template may be another's digit (TOTAL TIME's) */
        break;
      }
    if (sprite < 0 || (uint32_t)sprite >= A.nsprites) continue;
    float a = r->mul[3] / 256.0f * alpha;
    if (a <= 0.0f && r->add[3] <= 0) continue;
    float w = A.size[sprite][0];
    GLuint tx = texture(sprite); /* (first: its columns for wide_pieces) */
    wide_piece pc[WIDE_PIECES];
    int npc;
    if (mx != 0.0f || my != 0.0f) {
      /* Explicit composition placement supersedes automatic edge extrusion for
       * this record only. In particular, do not widen a moved song panel twice. */
      pc[0] = (wide_piece){ 0, w, 0, w, 1 };
      npc = 1;
    } else npc = wide_pieces(r, sprite, plain, pc);
#ifndef WMMT_NATIVE_VK
    if (r->blend != blend) {
      /* the arcade's ONE, ONE: its fades scale the colour; here the alpha does */
      blend = r->blend;
      glBlendFunc(GL_SRC_ALPHA, blend ? GL_ONE : GL_ONE_MINUS_SRC_ALPHA);
      glBlendEquation(blend == 2 ? GL_FUNC_REVERSE_SUBTRACT : GL_FUNC_ADD);
    }
    glUniform4f(A.u_mul, r->mul[0] / 256.0f, r->mul[1] / 256.0f, r->mul[2] / 256.0f, a);
    glUniform4f(A.u_add, r->add[0] / 255.0f, r->add[1] / 255.0f, r->add[2] / 255.0f, r->add[3] / 255.0f * alpha);
    glBindTexture(GL_TEXTURE_2D, tx);
#endif
    for (int p = 0; p < npc; ++p) {
#ifndef WMMT_NATIVE_VK
      if (p && pc[p].f != pc[p - 1].f) {
        glUniform4f(A.u_mul, r->mul[0] / 256.0f, r->mul[1] / 256.0f, r->mul[2] / 256.0f, a * pc[p].f);
        glUniform4f(A.u_add, r->add[0] / 255.0f, r->add[1] / 255.0f, r->add[2] / 255.0f,
                    r->add[3] / 255.0f * alpha * pc[p].f);
      }
#endif
      float h = A.size[sprite][1], v[16];
      static const float corner[4][2] = { { 0, 0 }, { 1, 0 }, { 0, 1 }, { 1, 1 } };
      for (int i = 0; i < 4; ++i) {
        float u = pc[p].u0 + corner[i][0] * (pc[p].u1 - pc[p].u0), t = corner[i][1] * h;
        float q = pc[p].d0 + corner[i][0] * (pc[p].d1 - pc[p].d0);
        v[i * 4 + 0] = (dx + sx * (r->x + r->a * q + r->c * t)) * SCALE;
        v[i * 4 + 1] = (dy + sy * (r->y + r->b * q + r->d * t)) * SCALE;
        if (mx != 0.0f) v[i * 4 + 0] += mx * SCALE;
        if (my != 0.0f) v[i * 4 + 1] += my * SCALE;
        v[i * 4 + 2] = u / w;
        v[i * 4 + 3] = corner[i][1];
      }
#ifdef WMMT_NATIVE_VK
      const float mul[4] = { r->mul[0] / 256.0f, r->mul[1] / 256.0f, r->mul[2] / 256.0f, a * pc[p].f };
      const float add[4] = { r->add[0] / 255.0f, r->add[1] / 255.0f, r->add[2] / 255.0f,
                             r->add[3] / 255.0f * alpha * pc[p].f };
      anm_native_quad(v, tx, mul, add, r->blend, VK_FALSE);
#else
      glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, v);
      glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, v + 2);
      glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
#endif
    }
  }
#ifndef WMMT_NATIVE_VK
  if (blend) {
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glBlendEquation(GL_FUNC_ADD);
  }
#endif
}

void anm_draw_xy(int anim, int frame, float alpha, float dx, float dy, float sx, float sy, const anm_swap *swap,
                 int nswap) {
  draw_xy_layout(anim, frame, alpha, dx, dy, sx, sy, swap, nswap, NULL, 0);
}

void anm_draw_layout(int anim, int frame, float alpha, float dx, float dy,
                     const anm_swap *swap, int nswap, const anm_layout_move *moves, int nmoves) {
  draw_xy_layout(anim, frame, alpha, dx, dy, 1.0f, 1.0f, swap, nswap, moves, nmoves);
}

int anm_sprite_rect(int anim, int frame, int sprite, float r[4]) {
  float a;
  return anm_sprite_rect_at(anim, frame, sprite, 0, r, &a);
}

int anm_sprite_rect_at(int anim, int frame, int sprite, int nth, float r[4], float *alpha) {
  if (anim < 0 || (uint32_t)anim >= A.nanims || sprite < 0 || (uint32_t)sprite >= A.nsprites) return 0;
  const anm_anim *an = &A.anims[anim];
  if (frame < 0) frame = 0;
  if ((uint32_t)frame >= an->nframes) frame = (int)an->nframes - 1;
  const anm_rec *rec = an->recs + an->frames[frame][0];
  for (uint32_t k = 0; k < an->frames[frame][1]; ++k, ++rec) {
    if (!same_sprite(rec->sprite, sprite) || nth-- > 0) continue;
    *alpha = rec->mul[3] / 256.0f;
    float w = A.size[rec->sprite][0], h = A.size[rec->sprite][1];
    float xs[2] = { rec->x, rec->x + rec->a * w + rec->c * h };
    float ys[2] = { rec->y, rec->y + rec->b * w + rec->d * h };
    float ox = wide_dx(rec, rec->sprite);
    r[0] = fminf(xs[0], xs[1]) + ox;
    r[2] = fmaxf(xs[0], xs[1]) + ox;
    r[1] = fminf(ys[0], ys[1]);
    r[3] = fmaxf(ys[0], ys[1]);
    return 1;
  }
  return 0;
}

int anm_sprite_xf(int anim, int frame, int sprite, float xf[6], float mul[4], float add[4]) {
  if (anim < 0 || (uint32_t)anim >= A.nanims || sprite < 0) return 0;
  const anm_anim *an = &A.anims[anim];
  if (frame < 0) frame = 0;
  if ((uint32_t)frame >= an->nframes) frame = (int)an->nframes - 1;
  const anm_rec *rec = an->recs + an->frames[frame][0];
  for (uint32_t k = 0; k < an->frames[frame][1]; ++k, ++rec) {
    if (!same_sprite(rec->sprite, sprite)) continue;
    const float v[6] = { rec->x, rec->y, rec->a, rec->b, rec->c, rec->d };
    for (int i = 0; i < 6; ++i) xf[i] = v[i];
    for (int i = 0; i < 4; ++i) mul[i] = rec->mul[i] / 256.0f, add[i] = rec->add[i] / 255.0f;
    return 1;
  }
  return 0;
}

float anm_sprite_alpha(int anim, int frame, int sprite) {
  if (anim < 0 || (uint32_t)anim >= A.nanims || sprite < 0) return 0.0f;
  const anm_anim *an = &A.anims[anim];
  if (frame < 0) frame = 0;
  if ((uint32_t)frame >= an->nframes) frame = (int)an->nframes - 1;
  const anm_rec *rec = an->recs + an->frames[frame][0];
  for (uint32_t k = 0; k < an->frames[frame][1]; ++k, ++rec)
    if (same_sprite(rec->sprite, sprite)) return rec->mul[3] / 256.0f;
  return 0.0f;
}

float anm_sprite_width(int sprite) {
  return sprite >= 0 && (uint32_t)sprite < A.nsprites ? A.size[sprite][0] : 0.0f;
}

float anm_sprite_height(int sprite) {
  return sprite >= 0 && (uint32_t)sprite < A.nsprites ? A.size[sprite][1] : 0.0f;
}

void anm_draw_sprite(int sprite, float x, float y, float alpha) {
  if (sprite < 0 || (uint32_t)sprite >= A.nsprites || alpha <= 0.0f) return;
#ifndef WMMT_NATIVE_VK
  use_prog();
  glUniform1i(A.u_tex, 0);
  glActiveTexture(GL_TEXTURE0);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glDisableVertexAttribArray(2);
#endif
  float x1 = x + A.size[sprite][0], y1 = y + A.size[sprite][1];
  const float v[16] = { x * SCALE, y * SCALE, 0, 0, x1 * SCALE, y * SCALE, 1, 0,
                        x * SCALE, y1 * SCALE, 0, 1, x1 * SCALE, y1 * SCALE, 1, 1 };
#ifdef WMMT_NATIVE_VK
  const float mul[4] = { 1, 1, 1, alpha }, add[4] = { 0, 0, 0, 0 };
  anm_native_quad(v, texture(sprite), mul, add, 0, VK_FALSE);
#else
  glUniform4f(A.u_mul, 1, 1, 1, alpha);
  glUniform4f(A.u_add, 0, 0, 0, 0);
  glBindTexture(GL_TEXTURE_2D, texture(sprite));
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, v);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, v + 2);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
#endif
}

/* Only a compiled program asset can reach this upload path. Imported game
 * bytes continue to go through the existing bounded menu/sidecar readers. */
static GLuint builtin_texture(int image) {
  if (image != ANM_BUILTIN_VS_MODE || !A.prog) return 0;
  A.builtin_used[0] = A.clock;
  if (A.builtin_tex[0]) return A.builtin_tex[0];
#ifndef WMMT_NATIVE_VK
  if (!glGetString(GL_VERSION)) return 0;
#endif
  const size_t bytes = 256u * 256u * 4u;
  unsigned char *px = malloc(bytes);
  uLongf got = (uLongf)bytes;
  if (!px) return 0;
  if (uncompress(px, &got, ANM_VS_MODE_Z, sizeof ANM_VS_MODE_Z) != Z_OK || got != bytes) {
    free(px);
    return 0;
  }
#ifdef WMMT_NATIVE_VK
  A.builtin_tex[0] = ui_native_texture_rgba8(256, 256, px);
#else
  glGenTextures(1, &A.builtin_tex[0]);
  glBindTexture(GL_TEXTURE_2D, A.builtin_tex[0]);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 256, 256, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
#endif
  free(px);
  return A.builtin_tex[0];
}

void anm_draw_builtin(int image, float x, float y, float w, float h, float alpha) {
  if (image != ANM_BUILTIN_VS_MODE || !isfinite(x) || !isfinite(y) ||
      !isfinite(w) || !isfinite(h) || !isfinite(alpha) || w <= 0.0f || h <= 0.0f || alpha <= 0.0f ||
      !isfinite(x + w) || !isfinite(y + h) || !isfinite(x*SCALE) || !isfinite(y*SCALE) ||
      !isfinite((x+w)*SCALE) || !isfinite((y+h)*SCALE)) return;
  GLuint tex = builtin_texture(image);
  if (!tex) return;
  if (alpha > 1.0f) alpha = 1.0f;
  static const float add[4] = {0, 0, 0, 0};
  const float mul[4] = {1, 1, 1, alpha};
  const float v[16] = {x*SCALE, y*SCALE, 0, 0, (x+w)*SCALE, y*SCALE, 1, 0,
                       x*SCALE, (y+h)*SCALE, 0, 1, (x+w)*SCALE, (y+h)*SCALE, 1, 1};
#ifdef WMMT_NATIVE_VK
  anm_native_quad(v, tex, mul, add, 0, VK_FALSE);
#else
  use_prog();
  glUniform1i(A.u_tex, 0);
  glActiveTexture(GL_TEXTURE0);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glDisableVertexAttribArray(2);
  glUniform4f(A.u_mul, mul[0], mul[1], mul[2], mul[3]);
  glUniform4f(A.u_add, add[0], add[1], add[2], add[3]);
  glBlendEquation(GL_FUNC_ADD);
  glBindTexture(GL_TEXTURE_2D, tex);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, v);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, v + 2);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
#endif
}

void anm_draw_part(int sprite, const float src[4], const float dst[4], float alpha) {
  static const float add[4] = { 0, 0, 0, 0 };
  const float mul[4] = { 1, 1, 1, alpha };
  anm_draw_part_col(sprite, src, dst, mul, add);
}

void anm_draw_part_col(int sprite, const float src[4], const float dst[4], const float mul[4], const float add[4]) {
  if (sprite < 0 || (uint32_t)sprite >= A.nsprites || (mul[3] <= 0.0f && add[3] <= 0.0f)) return;
#ifndef WMMT_NATIVE_VK
  use_prog();
  glUniform1i(A.u_tex, 0);
  glActiveTexture(GL_TEXTURE0);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glDisableVertexAttribArray(2);
#endif
  float u0 = src[0] / A.size[sprite][0], v0 = src[1] / A.size[sprite][1];
  float u1 = src[2] / A.size[sprite][0], v1 = src[3] / A.size[sprite][1];
  float x0 = dst[0] * SCALE, y0 = dst[1] * SCALE, x1 = dst[2] * SCALE, y1 = dst[3] * SCALE;
  const float v[16] = { x0, y0, u0, v0, x1, y0, u1, v0, x0, y1, u0, v1, x1, y1, u1, v1 };
#ifdef WMMT_NATIVE_VK
  anm_native_quad(v, texture(sprite), mul, add, 0, VK_FALSE);
#else
  glUniform4f(A.u_mul, mul[0], mul[1], mul[2], mul[3]);
  glUniform4f(A.u_add, add[0], add[1], add[2], add[3]);
  glBindTexture(GL_TEXTURE_2D, texture(sprite));
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, v);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, v + 2);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
#endif
}

void anm_fill(float r, float g, float b, float a) {
  static int white = -2;
  if (white == -2) white = anm_sprite(841); /* atract_p_white */
  if (white < 0 || a <= 0.0f) return;
#ifndef WMMT_NATIVE_VK
  use_prog();
  glUniform1i(A.u_tex, 0);
  glActiveTexture(GL_TEXTURE0);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glDisableVertexAttribArray(2);
#endif
  /* sample the middle of the white sprite so its edges don't show */
  const float x0 = -A.edge, x1 = 1024.0f + A.edge;
  const float v[16] = { x0, 0, 0.5f, 0.5f, x1, 0, 0.5f, 0.5f, x0, 768, 0.5f, 0.5f, x1, 768, 0.5f, 0.5f };
#ifdef WMMT_NATIVE_VK
  const float mul[4] = { r, g, b, a }, add[4] = { 0, 0, 0, 0 };
  anm_native_quad(v, texture(white), mul, add, 0, VK_FALSE);
#else
  glUniform4f(A.u_mul, r, g, b, a);
  glUniform4f(A.u_add, 0, 0, 0, 0);
  glBindTexture(GL_TEXTURE_2D, texture(white));
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, v);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, v + 2);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
#endif
}
