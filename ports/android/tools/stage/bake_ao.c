/* Bake a car's ambient occlusion (the port's, not the arcade's) into its shadow pages:
 * data/cars/<pack>.ao beside each car pack (pack_cars.py's WPK3).
 *
 * clCarModelData::constructBody composites each body page from the paint, a shadow texture
 * (ShadowTextureGet) and the vinyl, and nsTextureReplace::TextureReplace multiplies the page's
 * colour by the shadow / 255. Every car's shadow is dummy.tga, plain white: the arcade never
 * darkens anything there. This fills that slot: for each texel of a body page (a texture the
 * car.cg batches map once, inside 0..1) the surface point under it, from which `rays` rays go
 * out over the hemisphere about its normal (cosine weighted), each hit within AO_REACH
 * occluding by how near it is (1 - t / reach); the ground under the tyres stops the rays going
 * down. What occludes: the body as it always shows (chunk group 0, the stock tyres and wheels,
 * the lamps' off set) and, for a dress-up part's own texels, that part; never what blends
 * (glass, the lamps' glow) or the other parts' alternatives. Texels under several triangles
 * (a page mapped mirror-wise on both sides, or on both faces of a wing) take the least
 * occlusion of them; empty ones the mean of their neighbours, so the filtering at a seam does
 * not reach white; a 3 x 3 mean smooths the noise.
 *
 * File: "WAO1", u32 n_maps, then per map {char texture name[48], u16 w, u16 h, u8 shadow[w h]}
 * (rows as the texture's: texel (x, y) at uv ((x + 0.5) / w, (y + 0.5) / h)), the colour's
 * multiplier * 255 (render.c FS_LIT).
 *
 * usage: bake_ao <pack.wpk> <out.ao> [size 256] [rays 96] */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define AO_REACH 10.0f    /* 1 m (the packs' units are 0.1 m) */
#define AO_NEAR 0.25f     /* hits nearer than this are the faceted surface itself */
#define AO_BIAS 0.04f
#define AO_STRENGTH 0.9f  /* the multiplier where every ray is blocked at once: 1 - this */
#define AO_GAMMA 0.8f

enum { G_WHEEL = 0x100, G_LAMP_OFF = 0x110, G_LAMP_ON = 0x111, G_BRAKE_RUN = 0x112, G_BRAKE_LIGHT = 0x114,
       G_MIRROR = 0x120, G_CTIRE = 0x12a, G_BRAKE_HIGH = 0x140, G_SHADOW = 0xffff };

typedef struct { float p[3], uv[2], n[3]; } vert;
typedef struct { float a[3], e1[3], e2[3]; } tri;
typedef struct { float lo[3], hi[3]; int first, count; } node; /* count 0: inner, its left child next, first the right one */
typedef struct { tri *t; int n; node *nodes; int n_nodes; int *order; } bvh;

static uint8_t *file;
static size_t file_size;

static float dot3(const float *a, const float *b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
static void cross3(const float *a, const float *b, float *o) {
  o[0] = a[1] * b[2] - a[2] * b[1], o[1] = a[2] * b[0] - a[0] * b[2], o[2] = a[0] * b[1] - a[1] * b[0];
}
static void norm3(float *a) {
  float l = sqrtf(dot3(a, a));
  if (l > 0) a[0] /= l, a[1] /= l, a[2] /= l;
}

/* ---- the triangles' tree (median splits on the longest axis of the centres) ---- */
static float *cen;
static int axis_sort;
static int by_axis(const void *x, const void *y) {
  float a = cen[3 * *(const int *)x + axis_sort], b = cen[3 * *(const int *)y + axis_sort];
  return a < b ? -1 : a > b;
}

static void tri_box(const tri *t, float *lo, float *hi) {
  for (int k = 0; k < 3; ++k) {
    float a = t->a[k], b = a + t->e1[k], c = a + t->e2[k];
    lo[k] = fminf(lo[k], fminf(a, fminf(b, c)));
    hi[k] = fmaxf(hi[k], fmaxf(a, fmaxf(b, c)));
  }
}

static int build(bvh *b, int first, int count) {
  int me = b->n_nodes++;
  node *nd = &b->nodes[me];
  for (int k = 0; k < 3; ++k) nd->lo[k] = 1e30f, nd->hi[k] = -1e30f;
  float clo[3] = { 1e30f, 1e30f, 1e30f }, chi[3] = { -1e30f, -1e30f, -1e30f };
  for (int i = first; i < first + count; ++i) {
    int t = b->order[i];
    tri_box(&b->t[t], nd->lo, nd->hi);
    for (int k = 0; k < 3; ++k) clo[k] = fminf(clo[k], cen[3 * t + k]), chi[k] = fmaxf(chi[k], cen[3 * t + k]);
  }
  if (count <= 4) {
    nd->first = first, nd->count = count;
    return me;
  }
  int ax = 0;
  for (int k = 1; k < 3; ++k)
    if (chi[k] - clo[k] > chi[ax] - clo[ax]) ax = k;
  axis_sort = ax;
  qsort(b->order + first, (size_t)count, sizeof(int), by_axis);
  int half = count / 2;
  nd->count = 0;
  build(b, first, half);
  int r = build(b, first + half, count - half);
  b->nodes[me].first = r;
  return me;
}

static void bvh_make(bvh *b, tri *t, int n) {
  b->t = t, b->n = n, b->n_nodes = 0;
  b->nodes = malloc(sizeof(node) * (size_t)(2 * n + 1));
  b->order = malloc(sizeof(int) * (size_t)(n ? n : 1));
  cen = malloc(sizeof(float) * 3 * (size_t)(n ? n : 1));
  for (int i = 0; i < n; ++i) {
    b->order[i] = i;
    for (int k = 0; k < 3; ++k) cen[3 * i + k] = t[i].a[k] + (t[i].e1[k] + t[i].e2[k]) / 3.0f;
  }
  if (n) build(b, 0, n);
  free(cen);
}

static int box_hit(const node *nd, const float *o, const float *inv, float tmax) {
  float t0 = 0, t1 = tmax;
  for (int k = 0; k < 3; ++k) {
    float a = (nd->lo[k] - o[k]) * inv[k], b = (nd->hi[k] - o[k]) * inv[k];
    if (a > b) { float s = a; a = b; b = s; }
    t0 = fmaxf(t0, a), t1 = fminf(t1, b);
    if (t0 > t1) return 0;
  }
  return 1;
}

/* the nearest hit within (tmin, tmax), else tmax */
static float trace(const bvh *b, const float *o, const float *d, float tmin, float tmax) {
  if (!b->n) return tmax;
  float inv[3] = { 1.0f / d[0], 1.0f / d[1], 1.0f / d[2] };
  int stack[96], sp = 0;
  stack[sp++] = 0;
  while (sp) {
    const node *nd = &b->nodes[stack[--sp]];
    if (!box_hit(nd, o, inv, tmax)) continue;
    if (nd->count) {
      for (int i = nd->first; i < nd->first + nd->count; ++i) {
        const tri *t = &b->t[b->order[i]];
        float p[3], q[3], s[3];
        cross3(d, t->e2, p);
        float det = dot3(t->e1, p);
        if (fabsf(det) < 1e-9f) continue;
        float id = 1.0f / det;
        for (int k = 0; k < 3; ++k) s[k] = o[k] - t->a[k];
        float u = dot3(s, p) * id;
        if (u < 0 || u > 1) continue;
        cross3(s, t->e1, q);
        float v = dot3(d, q) * id;
        if (v < 0 || u + v > 1) continue;
        float h = dot3(t->e2, q) * id;
        if (h > tmin && h < tmax) tmax = h;
      }
    } else if (sp < 94) {
      stack[sp++] = nd->first;
      stack[sp++] = (int)(nd - b->nodes) + 1;
    }
  }
  return tmax;
}

/* ---- the pack ---- */
typedef struct { int tex, flags, prog, group; uint32_t voff, vcount, ioff, icount; } batch;

static uint32_t rd32(size_t off) { uint32_t v; memcpy(&v, file + off, 4); return v; }
static uint16_t rd16(size_t off) { uint16_t v; memcpy(&v, file + off, 2); return v; }

static void get_vert(const batch *b, uint32_t i, vert *v) {
  const uint8_t *p = file + b->voff + 32u * i;
  memcpy(v->p, p, 12);
  memcpy(v->uv, p + 12, 8);
  int16_t n[3];
  memcpy(n, p + 24, 6);
  for (int k = 0; k < 3; ++k) v->n[k] = n[k] / 32767.0f;
  norm3(v->n);
}

static int occluder_group(int g) {
  return g == 0 || (g >= G_WHEEL && g < G_WHEEL + 4) || g == G_LAMP_OFF;
}
static int part_group(int g) { return (g >= G_MIRROR && g < G_CTIRE) || (g >= 0x180 && g < 0x18a); }
static int unlit_story_part(const batch *b) { return b->group >= 0x180 && b->group < 0x18a && b->prog != 1; }

static int add_tris(const batch *bs, int nb, int want_group, tri **out, int *n, int *cap) {
  for (int i = 0; i < nb; ++i) {
    const batch *b = &bs[i];
    if ((b->flags & 3) || (want_group < 0 ? !occluder_group(b->group) : b->group != want_group)) continue;
    for (uint32_t k = 0; k + 2 < b->icount; k += 3) {
      vert v[3];
      for (int j = 0; j < 3; ++j) get_vert(b, rd16(b->ioff + 2u * (k + (uint32_t)j)), &v[j]);
      if (*n == *cap) *cap = *cap ? 2 * *cap : 4096, *out = realloc(*out, sizeof(tri) * (size_t)*cap);
      tri *t = &(*out)[(*n)++];
      for (int c = 0; c < 3; ++c) t->a[c] = v[0].p[c], t->e1[c] = v[1].p[c] - v[0].p[c], t->e2[c] = v[2].p[c] - v[0].p[c];
    }
  }
  return 0;
}

static uint32_t rng_state;
static float rnd(void) {
  rng_state ^= rng_state << 13, rng_state ^= rng_state >> 17, rng_state ^= rng_state << 5;
  return (float)(rng_state >> 8) / 16777216.0f;
}

int main(int argc, char **argv) {
  if (argc < 3) {
    fprintf(stderr, "usage: bake_ao pack.wpk out.ao [size] [rays]\n");
    return 2;
  }
  int max_size = argc > 3 ? atoi(argv[3]) : 256, rays = argc > 4 ? atoi(argv[4]) : 96;
  FILE *f = fopen(argv[1], "rb");
  if (!f) return perror(argv[1]), 1;
  fseek(f, 0, SEEK_END);
  file_size = (size_t)ftell(f);
  fseek(f, 0, SEEK_SET);
  file = malloc(file_size);
  if (fread(file, 1, file_size, f) != file_size) return fprintf(stderr, "%s: short read\n", argv[1]), 1;
  fclose(f);
  if (memcmp(file, "WPK3", 4)) return fprintf(stderr, "%s: not a lit pack\n", argv[1]), 1;
  uint32_t n_tex = rd32(4), n_chunk = rd32(8), n_batch = rd32(12), tex_off = rd32(20), chunk_off = rd32(24),
           batch_off = rd32(28);
  batch *bs = calloc(n_batch, sizeof(batch));
  for (uint32_t c = 0; c < n_chunk; ++c) {
    size_t r = chunk_off + 36u * c;
    uint32_t first = rd32(r + 24), n = rd32(r + 28), group = rd32(r + 32);
    for (uint32_t i = first; i < first + n && i < n_batch; ++i) bs[i].group = (int)group;
  }
  for (uint32_t i = 0; i < n_batch; ++i) {
    size_t r = batch_off + 28u * i;
    bs[i].tex = rd16(r), bs[i].flags = rd16(r + 2);
    bs[i].voff = rd32(r + 4), bs[i].vcount = rd32(r + 8), bs[i].ioff = rd32(r + 12), bs[i].icount = rd32(r + 16);
    bs[i].prog = file[r + 20];
  }
  /* the ground: the tyres' lowest point */
  float ground = 1e30f;
  for (uint32_t i = 0; i < n_batch; ++i)
    if (bs[i].group >= G_WHEEL && bs[i].group < G_WHEEL + 4)
      for (uint32_t k = 0; k < bs[i].vcount; ++k) {
        float y;
        memcpy(&y, file + bs[i].voff + 32u * k + 4, 4);
        ground = fminf(ground, y);
      }
  if (ground > 1e29f) ground = -1e30f;
  /* the body pages: textures car.cg maps (solid), all inside 0..1 */
  int *page = calloc(n_tex, sizeof(int));
  for (uint32_t i = 0; i < n_batch; ++i)
    if (bs[i].prog == 1 && !(bs[i].flags & 3) && bs[i].tex < (int)n_tex && bs[i].group != G_SHADOW && page[bs[i].tex] >= 0)
      page[bs[i].tex] = 1;
  for (uint32_t i = 0; i < n_batch; ++i) {
    if (bs[i].tex >= (int)n_tex || page[bs[i].tex] <= 0 || (bs[i].flags & 3) || unlit_story_part(&bs[i])) continue;
    for (uint32_t k = 0; k < bs[i].vcount; ++k) {
      float uv[2];
      memcpy(uv, file + bs[i].voff + 32u * k + 12, 8);
      if (uv[0] < -0.01f || uv[0] > 1.01f || uv[1] < -0.01f || uv[1] > 1.01f) page[bs[i].tex] = -1;
    }
  }
  /* the occluders: the body as always shown; each part's own */
  tri *base_t = NULL;
  int base_n = 0, base_cap = 0;
  add_tris(bs, (int)n_batch, -1, &base_t, &base_n, &base_cap);
  bvh base;
  bvh_make(&base, base_t, base_n);
  int n_maps = 0;
  for (uint32_t t = 0; t < n_tex; ++t) n_maps += page[t] > 0;
  FILE *o = fopen(argv[2], "wb");
  if (!o) return perror(argv[2]), 1;
  fwrite("WAO1", 1, 4, o);
  uint32_t nm = (uint32_t)n_maps;
  fwrite(&nm, 4, 1, o);
  for (uint32_t t = 0; t < n_tex; ++t) {
    if (page[t] <= 0) continue;
    size_t tr = tex_off + 64u * t;
    char name[48];
    memcpy(name, file + tr, 48);
    int tw = rd16(tr + 48), th = rd16(tr + 50);
    int w = tw, h = th;
    while (w > max_size || h > max_size) w = w > 1 ? w / 2 : 1, h = h > 1 ? h / 2 : 1;
    float *sum = calloc((size_t)w * h, sizeof(float));
    int *cnt = calloc((size_t)w * h, sizeof(int));
    long samples = 0;
    for (uint32_t i = 0; i < n_batch; ++i) {
      const batch *b = &bs[i];
      if (b->tex != (int)t || (b->flags & 3) || b->group == G_SHADOW || unlit_story_part(b)) continue;
      if (!occluder_group(b->group) && !part_group(b->group)) continue;
      bvh part = { 0 };
      tri *pt = NULL;
      int pn = 0, pcap = 0;
      if (part_group(b->group)) {
        add_tris(bs, (int)n_batch, b->group, &pt, &pn, &pcap);
        bvh_make(&part, pt, pn);
      }
      for (uint32_t k = 0; k + 2 < b->icount; k += 3) {
        vert v[3];
        for (int j = 0; j < 3; ++j) get_vert(b, rd16(b->ioff + 2u * (k + (uint32_t)j)), &v[j]);
        float e1[3], e2[3], fn[3];
        for (int c = 0; c < 3; ++c) e1[c] = v[1].p[c] - v[0].p[c], e2[c] = v[2].p[c] - v[0].p[c];
        cross3(e1, e2, fn);
        if (dot3(fn, fn) < 1e-12f) continue;
        norm3(fn);
        /* the texels whose centres it covers */
        float x[3], y[3];
        for (int j = 0; j < 3; ++j) x[j] = v[j].uv[0] * (float)w - 0.5f, y[j] = v[j].uv[1] * (float)h - 0.5f;
        float area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0]);
        if (fabsf(area) < 1e-8f) continue;
        int x0 = (int)floorf(fminf(x[0], fminf(x[1], x[2]))), x1 = (int)ceilf(fmaxf(x[0], fmaxf(x[1], x[2])));
        int y0 = (int)floorf(fminf(y[0], fminf(y[1], y[2]))), y1 = (int)ceilf(fmaxf(y[0], fmaxf(y[1], y[2])));
        for (int py = y0 < 0 ? 0 : y0; py <= y1 && py < h; ++py)
          for (int px = x0 < 0 ? 0 : x0; px <= x1 && px < w; ++px) {
            float b1 = ((float)px - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * ((float)py - y[0]);
            float b2 = (x[1] - x[0]) * ((float)py - y[0]) - ((float)px - x[0]) * (y[1] - y[0]);
            b1 /= area, b2 /= area;
            float b0 = 1 - b1 - b2;
            const float eps = -0.02f;
            if (b0 < eps || b1 < eps || b2 < eps) continue;
            float p[3], n[3];
            for (int c = 0; c < 3; ++c) {
              p[c] = b0 * v[0].p[c] + b1 * v[1].p[c] + b2 * v[2].p[c];
              n[c] = b0 * v[0].n[c] + b1 * v[1].n[c] + b2 * v[2].n[c];
            }
            norm3(n);
            if (dot3(n, n) < 0.5f) memcpy(n, fn, sizeof n);
            float gside = dot3(fn, n) < 0 ? -1.0f : 1.0f;
            float org[3];
            for (int c = 0; c < 3; ++c) org[c] = p[c] + AO_BIAS * gside * fn[c] + AO_BIAS * n[c];
            /* a frame about n */
            float tx[3], ty[3], up[3] = { 0, 1, 0 };
            if (fabsf(n[1]) > 0.9f) up[0] = 1, up[1] = 0;
            cross3(up, n, tx);
            norm3(tx);
            cross3(n, tx, ty);
            rng_state = 0x9e3779b9u ^ (uint32_t)(px * 73856093) ^ (uint32_t)(py * 19349663) ^ (uint32_t)(k * 83492791);
            if (!rng_state) rng_state = 1;
            float occ = 0;
            for (int r = 0; r < rays; ++r) {
              /* stratified over a sqrt(rays) grid, cosine weighted */
              int sq = (int)sqrtf((float)rays), cx = r % sq, cy = (r / sq) % sq;
              float u1 = r < sq * sq ? ((float)cx + rnd()) / (float)sq : rnd();
              float u2 = r < sq * sq ? ((float)cy + rnd()) / (float)sq : rnd();
              float rr = sqrtf(u1), ph = 6.2831853f * u2;
              float lx = rr * cosf(ph), ly = rr * sinf(ph), lz = sqrtf(fmaxf(0.0f, 1 - u1));
              float d[3];
              for (int c = 0; c < 3; ++c) d[c] = lx * tx[c] + ly * ty[c] + lz * n[c];
              for (int c = 0; c < 3; ++c)
                if (fabsf(d[c]) < 1e-6f) d[c] = 1e-6f;
              float hit = trace(&base, org, d, AO_NEAR, AO_REACH);
              if (part.n) hit = trace(&part, org, d, AO_NEAR, hit);
              if (d[1] < 0 && ground > -1e29f) {
                float tg = (ground - org[1]) / d[1];
                if (tg > 0 && tg < hit) hit = tg;
              }
              if (hit < AO_REACH) occ += 1 - hit / AO_REACH;
            }
            /* a texel two triangles share takes the less occluded: a page mapped once for both
             * sides of a thin part (a wing's top and underside) shows its open side's */
            float a = occ / (float)rays;
            if (!cnt[py * w + px] || a < sum[py * w + px]) sum[py * w + px] = a;
            cnt[py * w + px]++;
            samples++;
          }
      }
      if (pt) free(pt), free(part.nodes), free(part.order);
    }
    /* the covered texels' values, then the empty ones from their neighbours, a ring at a time */
    float *val = malloc(sizeof(float) * (size_t)w * h);
    int *has = malloc(sizeof(int) * (size_t)w * h);
    for (int i = 0; i < w * h; ++i) has[i] = cnt[i] > 0, val[i] = cnt[i] ? sum[i] : 0;
    /* the 3 x 3 mean over the covered texels */
    float *sm = malloc(sizeof(float) * (size_t)w * h);
    for (int py = 0; py < h; ++py)
      for (int px = 0; px < w; ++px) {
        float a = 0;
        int c = 0;
        if (!has[py * w + px]) { sm[py * w + px] = 0; continue; }
        for (int dy = -1; dy <= 1; ++dy)
          for (int dx = -1; dx <= 1; ++dx) {
            int qx = px + dx, qy = py + dy;
            if (qx < 0 || qy < 0 || qx >= w || qy >= h || !has[qy * w + qx]) continue;
            a += val[qy * w + qx] * (dx || dy ? 1.0f : 2.0f), c += dx || dy ? 1 : 2;
          }
        sm[py * w + px] = a / (float)c;
      }
    memcpy(val, sm, sizeof(float) * (size_t)w * h);
    for (int ring = 0; ring < 8; ++ring) {
      int *nh = malloc(sizeof(int) * (size_t)w * h);
      memcpy(nh, has, sizeof(int) * (size_t)w * h);
      for (int py = 0; py < h; ++py)
        for (int px = 0; px < w; ++px) {
          if (has[py * w + px]) continue;
          float a = 0;
          int c = 0;
          for (int dy = -1; dy <= 1; ++dy)
            for (int dx = -1; dx <= 1; ++dx) {
              int qx = px + dx, qy = py + dy;
              if (qx < 0 || qy < 0 || qx >= w || qy >= h || !has[qy * w + qx]) continue;
              a += val[qy * w + qx], c++;
            }
          if (c) sm[py * w + px] = a / (float)c, nh[py * w + px] = 1;
        }
      for (int i = 0; i < w * h; ++i)
        if (nh[i] && !has[i]) val[i] = sm[i];
      free(has);
      has = nh;
    }
    uint8_t *out = malloc((size_t)w * h);
    long covered = 0;
    double mean = 0;
    for (int i = 0; i < w * h; ++i) {
      float occ = has[i] ? val[i] : 0;
      float s = 1 - AO_STRENGTH * powf(fminf(fmaxf(occ, 0.0f), 1.0f), AO_GAMMA);
      out[i] = (uint8_t)lrintf(fminf(fmaxf(s, 0.0f), 1.0f) * 255.0f);
      if (cnt[i]) covered++, mean += out[i];
    }
    uint16_t wh[2] = { (uint16_t)w, (uint16_t)h };
    fwrite(name, 1, 48, o);
    fwrite(wh, 2, 2, o);
    fwrite(out, 1, (size_t)w * h, o);
    printf("  %s: %dx%d (page %dx%d), %ld texels covered, %ld samples, mean %.0f\n", name, w, h, tw, th, covered,
           samples, covered ? mean / covered : 0);
    free(sum), free(cnt), free(val), free(has), free(sm), free(out);
  }
  fclose(o);
  printf("%s: %d maps, %d occluding triangles, ground %.2f\n", argv[2], n_maps, base_n, ground);
  return 0;
}
