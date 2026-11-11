/* Project Cinder HUD: explicit packets, not a GL-state adapter.
 *
 * Paint is a CPU value passed by value down the HUD selection/geometry call
 * graph. It is never a current program, binding, VAO or uniform shadow. Each
 * primitive constructs a fresh complete pipeline/attributes/UBO/samplers/rect
 * packet. In particular, nested anm drawing cannot change a pending HUD paint.
 * GLES/VKcompat retain their original drawing bodies in hud.c for comparison.
 */
#include "native_vk.h"

typedef struct { float r, g, b, a; } hud_native_rgba;
typedef struct {
  mat4 projection;
  hud_native_rgba mul, add;
  int additive, negate;
  float opacity;
} hud_native_paint;

static hud_native_paint hud_native_paint_for(mat4 projection) {
  return (hud_native_paint){.projection=projection, .mul={1,1,1,1}, .opacity=1};
}

static int hud_native_packet(cinder_vk_draw *d, uint32_t program,
                             hud_native_paint paint, VkPrimitiveTopology topology) {
  int width=0, height=0;
  cinder_vk_screen_extent(&width, &height);
  if (!cinder_vk_draw_init(d, program, 0, width, height)) return 0;
  /* Deliberately spell out even the disabled features: none is inherited. */
  d->pipeline = (cinder_vk_pipeline){
    .topology=topology, .blend=VK_TRUE,
    .src_blend=paint.negate ? VK_BLEND_FACTOR_ONE_MINUS_DST_COLOR : VK_BLEND_FACTOR_SRC_ALPHA,
    .dst_blend=paint.negate ? VK_BLEND_FACTOR_ZERO : paint.additive ? VK_BLEND_FACTOR_ONE : VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
    .blend_op=VK_BLEND_OP_ADD, .color_mask=15,
    .depth_test=VK_FALSE, .depth_write=VK_FALSE, .depth_compare=VK_COMPARE_OP_LESS_OR_EQUAL,
    .cull=VK_CULL_MODE_NONE, .asset_front=VK_FRONT_FACE_COUNTER_CLOCKWISE,
    .stencil=VK_FALSE, .stencil_compare=VK_COMPARE_OP_ALWAYS,
    .stencil_fail=VK_STENCIL_OP_KEEP, .depth_fail=VK_STENCIL_OP_KEEP, .depth_pass=VK_STENCIL_OP_KEEP,
    .stencil_compare_mask=255, .stencil_write_mask=255,
  };
  /* Constant attributes are explicit, including NAVI arrow/preview white.
   * Reflected unused inputs may be ignored, but must never read a previous VAO. */
  for (int i=0; i<CINDER_VK_ATTRIBUTES; ++i)
    d->attributes[i]=(cinder_vk_attribute){.format=VK_FORMAT_UNDEFINED, .value={1,1,1,1}};
  return 1;
}

static int hud_native_solid(hud_native_paint paint, const float *vertices, size_t bytes,
                            VkPrimitiveTopology topology, uint32_t count) {
  cinder_vk_draw d;
  if (!hud_native_packet(&d, prog, paint, topology)) return 0;
  d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT, .stride=8,
    .data=vertices, .bytes=bytes};
  d.count=count;
  paint.mul.a *= paint.opacity;
  return cinder_vk_uniform(&d,"uProj",paint.projection.m,sizeof paint.projection.m) &&
    cinder_vk_uniform(&d,"uColor",&paint.mul,sizeof paint.mul) && cinder_vk_submit(&d);
}

/* upload() is the only HUD/navi texture producer: GL_LINEAR for min/mag,
 * GL_CLAMP_TO_EDGE on both axes, no generated mip levels or anisotropy. */
static int hud_native_sample(cinder_vk_draw *d, uint32_t texture) {
  const cinder_vk_sampler sampler={
    .use_state=VK_TRUE, .mipmaps=VK_FALSE,
    .min_filter=VK_FILTER_LINEAR, .mag_filter=VK_FILTER_LINEAR,
    .mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,
    .address_u=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    .address_v=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .anisotropy=1,
  };
  return cinder_vk_texture(d,"uTex",texture) && cinder_vk_sampler_state(d,"uTex",&sampler);
}

static int hud_native_textured(hud_native_paint paint, uint32_t texture,
                               const float *vertices, size_t bytes, int warm_only) {
  cinder_vk_draw d;
  if (!hud_native_packet(&d,tex_prog,paint,VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP)) return 0;
  d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT, .stride=16,
    .data=vertices, .bytes=bytes};
  d.attributes[1]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT, .stride=16,
    .offset=8, .data=vertices, .bytes=bytes};
  d.count=4; d.warm_only=warm_only != 0;
  return cinder_vk_uniform(&d,"uProj",paint.projection.m,sizeof paint.projection.m) &&
    cinder_vk_uniform(&d,"uMul",&paint.mul,sizeof paint.mul) &&
    cinder_vk_uniform(&d,"uAdd",&paint.add,sizeof paint.add) &&
    hud_native_sample(&d,texture) && cinder_vk_submit(&d);
}

static void hud_native_draw_k(hud_native_paint paint, const hud_sprite *sp,
                              float cx, float cy, float deg, float k) {
  if (!sp->tex) return;
  float a=deg*(float)M_PI/180.0f, c=cosf(a), s=sinf(a);
  float hw=sp->w*k*.5f, hh=sp->h*k*.5f;
  static const float corner[4][2]={{-1,-1},{1,-1},{-1,1},{1,1}};
  float v[16];
  for (int i=0; i<4; ++i) {
    float x=corner[i][0]*hw, y=corner[i][1]*hh;
    v[4*i]=cx+x*c-y*s; v[4*i+1]=cy+x*s+y*c;
    v[4*i+2]=(corner[i][0]+1)*.5f; v[4*i+3]=(corner[i][1]+1)*.5f;
  }
  hud_native_textured(paint,sp->tex,v,sizeof v,0);
}

static void hud_native_fill_rect(hud_native_paint paint, float x, float y, float w, float h) {
  float v[8] = { x, y, x + w, y, x, y + h, x + w, y + h };
  hud_native_solid(paint, v, sizeof v, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP, 4);
}

static void hud_native_frame_rect(hud_native_paint paint, rect r, float t) {
  hud_native_fill_rect(paint, r.x, r.y, r.w, t);
  hud_native_fill_rect(paint, r.x, r.y + r.h - t, r.w, t);
  hud_native_fill_rect(paint, r.x, r.y, t, r.h);
  hud_native_fill_rect(paint, r.x + r.w - t, r.y, t, r.h);
}

static void hud_native_ring(hud_native_paint paint, float cx, float cy, float r0, float r1) {
  float v[66 * 2];
  int n = 0;
  for (int i = 0; i <= 32; ++i) {
    float a = (float)i / 32.0f * 2.0f * (float)M_PI;
    v[n++] = cx + cosf(a) * r1; v[n++] = cy + sinf(a) * r1;
    v[n++] = cx + cosf(a) * r0; v[n++] = cy + sinf(a) * r0;
  }
  hud_native_solid(paint, v, sizeof v, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP, n / 2);
}

static void hud_native_disc(hud_native_paint paint, float cx, float cy, float r) { hud_native_ring(paint, cx, cy, 0, r); }

static void hud_native_triangle(hud_native_paint paint, float x0, float y0, float x1, float y1, float x2, float y2) {
  float v[6] = { x0, y0, x1, y1, x2, y2 };
  hud_native_solid(paint, v, sizeof v, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST, 3);
}

static void hud_native_fill_rrect(hud_native_paint paint, rect r, float rad) {
  float v[2 + 28 * 2 + 2];
  v[0] = r.x + r.w / 2;
  v[1] = r.y + r.h / 2;
  int n = rrect_path(r, rad, 0, v + 2);
  v[2 + n * 2] = v[2];
  v[3 + n * 2] = v[3];
  hud_native_solid(paint, v, sizeof v, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_FAN, n + 2);
}

static void hud_native_stroke_rrect(hud_native_paint paint, rect r, float rad, float t) {
  float a[28 * 2], b[28 * 2], v[29 * 4];
  int n = rrect_path(r, rad, 0, a);
  rrect_path(r, rad, t, b);
  for (int i = 0; i <= n; ++i) {
    int k = i % n;
    v[i * 4 + 0] = a[k * 2]; v[i * 4 + 1] = a[k * 2 + 1];
    v[i * 4 + 2] = b[k * 2]; v[i * 4 + 3] = b[k * 2 + 1];
  }
  hud_native_solid(paint, v, sizeof v, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP, (n + 1) * 2);
}

static void hud_native_button(hud_native_paint paint, rect r, int held) {
  if (held) paint.mul = (hud_native_rgba){1.0f, 0.42f, 0.05f, 0.70f};
  else paint.mul = (hud_native_rgba){0.04f, 0.05f, 0.08f, 0.50f};
  hud_native_fill_rrect(paint, r, 12);
  paint.mul = (hud_native_rgba){1, 1, 1, 0.07f}; /* top sheen */
  hud_native_fill_rrect(paint, (rect){ r.x + 4, r.y + 4, r.w - 8, fminf(r.h * 0.22f, 26) }, 8);
  paint.mul = (hud_native_rgba){0.85f, 0.88f, 0.92f, held ? 0.95f : 0.60f};
  hud_native_stroke_rrect(paint, r, 12, 2);
}

static void hud_native_pedal_bar(hud_native_paint paint, rect r, float v) {
  float x = r.x + r.w - 12, y0 = r.y + PEDAL_FOOT, y1 = r.y + r.h - PEDAL_FOOT;
  paint.mul = (hud_native_rgba){0, 0, 0, 0.5f};
  hud_native_fill_rect(paint, x, y0, 6, y1 - y0);
  paint.mul = (hud_native_rgba){1.0f, 0.42f, 0.05f, 0.95f};
  hud_native_fill_rect(paint, x, y1 - v * (y1 - y0), 6, v * (y1 - y0));
}

static void hud_native_chevron(hud_native_paint paint, float cx, float cy, float s, float dx, float dy) {
  /* thick arrow head pointing along (dx, dy) */
  float px = -dy, py = dx;
  float v[12] = {
    cx + dx * s, cy + dy * s, cx - dx * s * 0.2f + px * s, cy - dy * s * 0.2f + py * s,
    cx - dx * s * 0.2f - px * s, cy - dy * s * 0.2f - py * s,
  };
  hud_native_solid(paint, v, sizeof v, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST, 3);
}

static void hud_native_digit(hud_native_paint paint, int d, float x, float y, float w, float h) {
  static const unsigned char SEG[11] = { 0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F,
                                         0x50 /* 'r' */ };
  float t = w * 0.18f, hh = h * 0.5f;
  unsigned char s = SEG[d];
  if (s & 1) hud_native_fill_rect(paint, x, y, w, t);
  if (s & 2) hud_native_fill_rect(paint, x + w - t, y, t, hh);
  if (s & 4) hud_native_fill_rect(paint, x + w - t, y + hh, t, hh);
  if (s & 8) hud_native_fill_rect(paint, x, y + h - t, w, t);
  if (s & 16) hud_native_fill_rect(paint, x, y + hh, t, hh);
  if (s & 32) hud_native_fill_rect(paint, x, y, t, hh);
  if (s & 64) hud_native_fill_rect(paint, x, y + hh - t * 0.5f, w, t);
}

static void hud_native_number(hud_native_paint paint, int v, int digits, float x, float y, float w, float h) {
  for (int i = digits - 1; i >= 0; --i) {
    int d = v % 10;
    v /= 10;
    if (v == 0 && d == 0 && i < digits - 1) continue; /* no leading zeros */
    hud_native_digit(paint, d, x + (float)i * (w * 1.35f), y, w, h);
  }
}

static void hud_native_sprite_k(hud_native_paint paint, int id, float cx, float cy, float deg, float k) { hud_native_draw_k(paint, &SPR[id], cx, cy, deg, k); }

static void hud_native_blit(hud_native_paint paint, int id, float x, float y) {
  hud_native_sprite_k(paint, id, x + SPR[id].w * HUD_K * 0.5f, y + SPR[id].h * HUD_K * 0.5f, 0, HUD_K);
}

static void hud_native_draw_meters(hud_native_paint paint, const car_state *car) {
  if (!meter_car) return;
  int night = meter_night;
  int count = meter_v2_active ? METERDB_V2[meter_car - METERDB].n[night] : meter_car->n[night];
  for (int i = 0; i < count; ++i) {
    const meterdb_part *p = meter_v2_active ? &METERDB_V2[meter_car - METERDB].parts[night][i] : &meter_car->parts[night][i];
    float deg = p->a0 + p->a1 * meter_input(p, car);
    paint.additive = p->add != 0; /* the R35's glowing night needles */
    const hud_sprite *sp = &METER[i];
    /* Captured after CSeq::Exec; pause freezes the simulation count. */
    if (i == racing_lamp_slot && racing_lamp_on.tex && car->rev_rate > RACING_LAMP_REV_THRESHOLD &&
        car->rev_lamp_frame % 5 > 1)
      sp = &racing_lamp_on;
    hud_native_draw_k(paint, sp, CLUSTER_X + (p->x - 560) * HUD_K, CLUSTER_Y + (p->y - 228) * HUD_K, deg, HUD_K);
    
  }
}

static void hud_native_draw_shifter(hud_native_paint paint, const car_state *car) {
  int gears = meter_car ? meter_car->gears : 6;
  gears = gears < 4 ? 4 : gears > 6 ? 6 : gears;
  int pattern = SPR_SHIFT4 + gears - 4;
  if (!SPR[pattern].tex) return;
  float ox = SHIFT_X - 30 * SHIFT_K, oy = SHIFT_Y - 36 * SHIFT_K; /* pattern top-left */
  hud_native_sprite_k(paint, pattern, SHIFT_X, SHIFT_Y, 0, SHIFT_K);
  int g = car->gear < 0 ? 0 : car->gear > gears ? gears : car->gear;
  hud_native_sprite_k(paint, (car->manual ? SPR_BALL_MT : SPR_BALL_AT) + g, ox + KNOB[g][0] * SHIFT_K, oy + KNOB[g][1] * SHIFT_K, 0, SHIFT_K);
  hud_native_sprite_k(paint, car->manual ? SPR_TAG_MT : SPR_TAG_AT, ox + TAG[0] * SHIFT_K, oy + TAG[1] * SHIFT_K, 0, SHIFT_K);
}

static void hud_native_blit_rank(hud_native_paint paint, char c, float x, float y) {
  const char *l = strchr("NABCS", c);
  int s = c >= '0' && c <= '9' ? SPR_RANK_DIGIT + c - '0' : l && c ? SPR_RANK + (int)(l - "NABCS") : -1;
  if (s < 0) return;
  if (SPR[s].tex) hud_native_blit(paint, s, x, y);
  else if (c == 'N') hud_native_blit(paint, SPR_CLASS_N, x, y); /* a hud.bin from before the classes */
}

static void hud_native_draw_plate(hud_native_paint paint, const car_state *car) {
  if (!SPR[SPR_PLATE].tex) return;
  float k = HUD_K, x0 = 1024 + EDGE - SPR[SPR_PLATE].w * k, y0 = INFO_Y;
  hud_native_blit(paint, SPR_PLATE, x0, y0);
  hud_native_blit(paint, SPR_PILL, x0 + 20 * k, y0 + 3 * k);
  char g[3];
  int wide = class_glyphs(plate_class, g);
  float gx = wide ? 22 : 27; /* frame 1: 0x1115, 0x1108, 0x1109; frame 0: 0x1115, 0x1109 */
  for (int i = 0; i < (wide ? 3 : 2); ++i) hud_native_blit_rank(paint, g[i], x0 + (gx + 10 * i) * k, y0 + 2 * k);
  hud_native_blit(paint, SPR_CLASS_KYU, x0 + (wide ? 52 : 47) * k, y0 + 3 * k);
  if (!plate_text_ok()) { /* (draw_plate_text draws the card's) */
    hud_native_blit(paint, SPR_TITLE, x0 + 71 * k, y0 + 3.5f * k);
    hud_native_sprite_k(paint, SPR_NAME, x0 + 119 * k, y0 + 32 * k, 0, k); /* the font draws the name centred */
  } else if (!plate_name_n) {
    hud_native_sprite_k(paint, SPR_NAME, x0 + 119 * k, y0 + 32 * k, 0, k);
  }
  int kmh = (int)(fminf(car_kmh(car), 999.0f) + 0.5f);
  for (int pass = 0; pass < 2; ++pass) {
    int base = pass ? SPR_BIG : SPR_BIG_SHADOW;
    for (int i = 0, div = 100; i < 3; ++i, div /= 10)
      if (kmh >= div || i == 2) hud_native_blit(paint, base + kmh / div % 10, x0 + (7 + 19 * i) * k, y0 + 24 * k);
  }
  hud_native_blit(paint, SPR_KMH, x0 + 72 * k, y0 + 40 * k);
  for (int i = 0, div = 100; i < 3; ++i, div /= 10)
    hud_native_blit(paint, SPR_SMALL + plate_hp / div % 10, x0 + (110 + 10 * i) * k, y0 + 40 * k);
  hud_native_blit(paint, SPR_BARIKI, x0 + 140 * k, y0 + 40 * k);
  hud_native_blit(paint, SPR_GRADE + plate_grade, x0 + 166 * k, y0 + 40 * k);
}

static void hud_native_ta_blit(hud_native_paint paint, int id, float ax, float ay) { hud_native_blit(paint, id, tx(ax), ty(ay)); }

static void hud_native_map_blit(hud_native_paint paint, int id, float ax, float ay) { hud_native_blit(paint, id, tx(ax), ty(ay) - MAP_UP); }

static void hud_native_draw_till_goal(hud_native_paint paint, float remain) {
  hud_native_ta_blit(paint, SPR_TILL_GOAL, 9, 12);
  int d = (int)remain;
  if (d <= 999) {
    int n = d <= 9 ? 1 : d <= 99 ? 2 : 3;
    for (int i = 0, div = n == 3 ? 100 : n == 2 ? 10 : 1; i < n; ++i, div /= 10)
      hud_native_ta_blit(paint, SPR_GOAL_DIGIT + d / div % 10, 10 + 40 * i, 30);
    hud_native_ta_blit(paint, SPR_GOAL_M, 10 + 40 * n, 30);
    return;
  }
  int u = (d + 50) / 100; /* 100 m */
  if (u > 999) u = 999;
  if (u <= 99) {
    hud_native_ta_blit(paint, SPR_GOAL_DIGIT + u / 10, 10, 30);
    hud_native_ta_blit(paint, SPR_GOAL_DOT, 43, 30);
    hud_native_ta_blit(paint, SPR_GOAL_DIGIT + u % 10, 70, 30);
    hud_native_ta_blit(paint, SPR_GOAL_KM, 110, 30);
  } else {
    hud_native_ta_blit(paint, SPR_GOAL_DIGIT + u / 100, 10, 30);
    hud_native_ta_blit(paint, SPR_GOAL_DIGIT + u / 10 % 10, 50, 30);
    hud_native_ta_blit(paint, SPR_GOAL_DOT, 83, 30);
    hud_native_ta_blit(paint, SPR_GOAL_DIGIT + u % 10, 110, 30);
    hud_native_ta_blit(paint, SPR_GOAL_KM, 155, 30);
  }
}

static void hud_native_draw_laptime(hud_native_paint paint, float t, float y, const float *x) {
  int ms = (int)(t * 1000.0f + 0.5f);
  if (ms < 0) ms = 0;
  if (ms > 9 * 60000 + 59999) ms = 9 * 60000 + 59999;
  int m = ms / 60000, sec = ms / 1000 % 60, f = ms % 1000;
  hud_native_ta_blit(paint, SPR_TA_DIGIT + m, x[0], y);
  hud_native_ta_blit(paint, SPR_TA_QUOTE1, x[1], y);
  hud_native_ta_blit(paint, SPR_TA_DIGIT + sec / 10, x[2], y);
  hud_native_ta_blit(paint, SPR_TA_DIGIT + sec % 10, x[3], y);
  hud_native_ta_blit(paint, SPR_TA_QUOTE2, x[4], y + 1);
  hud_native_ta_blit(paint, SPR_TA_DIGIT + f / 100, x[5], y);
  hud_native_ta_blit(paint, SPR_TA_DIGIT + f / 10 % 10, x[6], y);
  hud_native_ta_blit(paint, SPR_TA_DIGIT + f % 10, x[7], y);
}

static void hud_native_draw_times(hud_native_paint paint, const car_race *r) {
  static const float TOTAL_X[8] = { 14, 27, 37, 51, 65, 75, 89, 103 };
  static const float SECTION_X[8] = { 14, 26, 36, 49, 62, 72, 85, 98 };
  hud_native_ta_blit(paint, SPR_TA_PILL, -28, 87);
  hud_native_draw_laptime(paint, r->total, 100, TOTAL_X);
  hud_native_ta_blit(paint, SPR_TA_TOTAL, 13, 85);
  hud_native_ta_blit(paint, SPR_TA_SECTION, 16, 121);
  /* the sections driven, and the one being driven so far */
  int rows = r->sections < 4 ? r->sections : 4;
  for (int k = 0; k < rows && k <= r->section; ++k) {
    float t = k < r->section ? r->split[k + 1] - r->split[k] : r->total - r->split[k];
    hud_native_draw_laptime(paint, t, 136 + 18 * k, SECTION_X);
  }
}

static void hud_native_draw_time_left(hud_native_paint paint, float left) {
  int v = left>0 ? (int)fminf(left,9999.0f) : 0;
  int digits=v>=1000?4:3, first=v>=1000?1000:100;
  for (int i = 0, div = first; i < digits; ++i, div /= 10) hud_native_map_blit(paint, SPR_LTIME_SHADOW + v / div % 10, 53.0f + 15.0f * (float)i, 364);
  if (v <= 9) paint.mul = (hud_native_rgba){1, 0.30f, 0.30f, 1};
  hud_native_map_blit(paint, SPR_TIME, 15, 366);
  for (int i = 0, div = first; i < digits; ++i, div /= 10) hud_native_map_blit(paint, SPR_LTIME + v / div % 10, 53.0f + 15.0f * (float)i, 364);
  paint.mul = (hud_native_rgba){1, 1, 1, 1};
}

static void hud_native_draw_time_extend(hud_native_paint paint, float total) {
  if (extend_at < 0) return;
  float t = (total - extend_at) * 60.0f;
  if (t < 0 || t >= EXTEND_IN + EXTEND_HOLD + EXTEND_OUT) { extend_at = -1; return; }
  float k = 1, a = 1, glow = 0;
  if (t < EXTEND_IN) {
    float u = t / EXTEND_IN;
    k = u < 0.7f ? 2.0f - 1.14f * u / 0.7f : 0.86f + 0.14f * (u - 0.7f) / 0.3f;
    a = u;
    glow = 1 - u;
  } else if (t < EXTEND_IN + EXTEND_HOLD) {
    glow = 64.0f / 255.0f * (0.5f - 0.5f * cosf((t - EXTEND_IN) * 2.0f * (float)M_PI / 30.0f));
  } else {
    float u = (t - EXTEND_IN - EXTEND_HOLD) / EXTEND_OUT;
    k = 1 + u;
    a = 1 - u;
  }
  paint.mul = (hud_native_rgba){1, 1, 1, a};
  paint.add = (hud_native_rgba){glow, glow, glow, 0};
  hud_native_sprite_k(paint, SPR_TIME_EXTEND, 512, 250, 0, HUD_K * k); /* the arcade's (320, 156) */
  paint.add = (hud_native_rgba){0, 0, 0, 0};
  if (ta_delta_sign) {
    int ids[9];
    time_extend_digits(ids);
    for (int i = 0; i < 9; ++i)
      hud_native_sprite_k(paint, ids[i], time_extend_digit_x(i), time_extend_digit_y(), 0, HUD_K);
    if (ta_delta_sign > 0)
      hud_native_sprite_k(paint, ids[0], time_extend_digit_x(0), time_extend_digit_y(), 90, HUD_K);
  }
}

static void hud_native_draw_record(hud_native_paint paint, int label, float label_y, float y, float t) {
  static const float X[8] = { 522, 534, 544, 557, 570, 580, 593, 606 };
  int ms = (int)(t * 1000.0f);
  if (ms > 99 * 60000 + 59999) ms = 99 * 60000 + 59999;
  int d[7] = { ms / 60000 % 10, ms / 10000 % 6, ms / 1000 % 10, ms / 100 % 10, ms / 10 % 10, ms % 10, ms / 600000 };
  static const int SLOT[6] = { 0, 2, 3, 5, 6, 7 };
  for (int i = 0; i < 6; ++i) hud_native_blit(paint, ms ? SPR_TA_DIGIT + d[i] : SPR_REC_DASH, rx(X[SLOT[i]]), ty(y));
  if (ms && d[6]) hud_native_blit(paint, SPR_TA_DIGIT + d[6], rx(509), ty(y)); /* ten minutes and more */
  hud_native_blit(paint, SPR_TA_QUOTE1, rx(X[1]), ty(y));
  hud_native_blit(paint, SPR_TA_QUOTE2, rx(X[4]), ty(y + 1));
  hud_native_blit(paint, label, rx(522), ty(label_y));
}

static void hud_native_draw_sign(hud_native_paint paint, const car_race *r) {
  int sign = r->state == CAR_RACE_RUN && r->sign >= 1 && r->sign <= HUD_SIGNS ? r->sign : 0;
  if (!sign) return;
  /* the blink loop's alpha (of 256): each 15 frames it comes back in over 5 or 6 */
  static const unsigned char BLINK[60] = {
    0, 0, 64, 128, 192, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    0, 51, 102, 154, 205, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    0, 51, 102, 154, 205, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255,
    0, 43, 85, 128, 171, 213, 255, 255, 255, 255, 255, 255, 255, 255, 255 };
  float a = hud_sign_blinks(sign) ? BLINK[(sign_t + 59) % 60] / 255.0f : 1.0f;
  const float k = 1.6f; /* the arcade's 640x480 to the 1024x768 screen */
  paint.mul = (hud_native_rgba){1, 1, 1, a};
  hud_native_sprite_k(paint, SPR_SIGN + sign - 1, (289 + 32) * k, (81 + 32) * k, 0, k);
  paint.mul = (hud_native_rgba){1, 1, 1, 1};
}

static void hud_native_draw_records(hud_native_paint paint) {
  if (!SPR[SPR_BUYIN].tex) return;
  hud_native_draw_record(paint, SPR_REC_TIME, 15, 29, rec_time);
  hud_native_draw_record(paint, SPR_REC_YOUR, 55, 69, rec_yours);
  hud_native_blit(paint, SPR_BUYIN, rx(536), ty(130) - PILL_UP);
}

static void hud_native_draw_keys(hud_native_paint paint, const hud_state *h, float steer, int all_keys) {
  paint.opacity = button_opacity;
  /* steering (the gyro's: none); each side's keys in its own projection (key_ortho) */
  if (all_keys) {
    rect brake = h->gyro ? G_BRAKE : BRAKE, up = h->gyro ? G_SHIFT_UP : SHIFT_UP, down = h->gyro ? G_SHIFT_DOWN : SHIFT_DOWN;
    mat4 side_proj = key_ortho(h->screen_w, h->screen_h, KEY_LEFT);
    paint.projection = side_proj;
    if (!h->gyro && h->steer_mode == HUD_STEER_WHEEL) {
      /* a wheel: rim, hub and three spokes turned by the wheel's turn, the top's mark orange */
      float a = h->wheel_turn, cx = WHEEL_CX, cy = WHEEL_CY;
      paint.mul = (hud_native_rgba){0.04f, 0.05f, 0.08f, 0.45f};
      hud_native_disc(paint, cx, cy, WHEEL_R);
      paint.mul = (hud_native_rgba){0.85f, 0.88f, 0.92f, h->steer_touch ? 0.95f : 0.65f};
      hud_native_ring(paint, cx, cy, WHEEL_R - 18, WHEEL_R);
      hud_native_disc(paint, cx, cy, 22);
      for (int k = 0; k < 3; ++k) {
        float sa = a + (k == 0 ? (float)M_PI : k == 1 ? 0.0f : (float)M_PI / 2.0f), c = cosf(sa), sn = sinf(sa);
        float px = -sn * 7, py = c * 7, r0 = 20, r1 = WHEEL_R - 16;
        hud_native_triangle(paint, cx + c * r0 + px, cy + sn * r0 + py, cx + c * r1 + px, cy + sn * r1 + py, cx + c * r0 - px, cy + sn * r0 - py);
        hud_native_triangle(paint, cx + c * r1 + px, cy + sn * r1 + py, cx + c * r1 - px, cy + sn * r1 - py, cx + c * r0 - px, cy + sn * r0 - py);
      }
      paint.mul = (hud_native_rgba){1.0f, 0.42f, 0.05f, 0.95f};
      float ta = a - (float)M_PI / 2.0f;
      hud_native_disc(paint, cx + cosf(ta) * (WHEEL_R - 9), cy + sinf(ta) * (WHEEL_R - 9), 9);
    } else if (!h->gyro && h->steer_mode == HUD_STEER_STICK) {
      /* the stick: its base and knob where the thumb is, else a faint ring where it waits */
      float bx = h->steer_touch ? h->stick_x0 : WHEEL_CX, by = h->steer_touch ? h->stick_y0 : WHEEL_CY;
      float kx = h->steer_touch ? h->stick_x : bx, ky = h->steer_touch ? h->stick_y : by;
      paint.mul = (hud_native_rgba){0.04f, 0.05f, 0.08f, h->steer_touch ? 0.45f : 0.25f};
      hud_native_disc(paint, bx, by, STICK_R + 20);
      paint.mul = (hud_native_rgba){0.85f, 0.88f, 0.92f, h->steer_touch ? 0.8f : 0.35f};
      hud_native_ring(paint, bx, by, STICK_R + 16, STICK_R + 20);
      paint.mul = (hud_native_rgba){h->steer_touch ? 1.0f : 0.85f, h->steer_touch ? 0.42f : 0.88f, h->steer_touch ? 0.05f : 0.92f, h->steer_touch ? 0.9f : 0.5f};
      hud_native_disc(paint, kx, ky, 38);
    } else if (!h->gyro) {
      hud_native_button(paint, LEFT, h->left_touch != 0);
      hud_native_button(paint, RIGHT, h->right_touch != 0);
      paint.mul = (hud_native_rgba){1, 1, 1, 0.92f};
      hud_native_chevron(paint, LEFT.x + LEFT.w / 2 - 6, LEFT.y + LEFT.h / 2, 30, -1, 0);
      hud_native_chevron(paint, RIGHT.x + RIGHT.w / 2 + 6, RIGHT.y + RIGHT.h / 2, 30, 1, 0);
    }
    /* wheel angle bar between the two (the stick's above its zone; the wheel shows its own) */
    float mid = (LEFT.x + RIGHT.x + RIGHT.w) / 2, by = h->steer_mode == HUD_STEER_STICK ? STICK_ZONE.y - 14 : LEFT.y - 14;
    if (h->steer_mode != HUD_STEER_WHEEL) {
      paint.mul = (hud_native_rgba){0, 0, 0, 0.4f};
      hud_native_fill_rect(paint, LEFT.x, by, RIGHT.x + RIGHT.w - LEFT.x, 6);
      paint.mul = (hud_native_rgba){1.0f, 0.42f, 0.05f, 0.95f};
      if (steer > 0) hud_native_fill_rect(paint, mid, by, steer * (mid - LEFT.x), 6);
      else hud_native_fill_rect(paint, mid + steer * (mid - LEFT.x), by, -steer * (mid - LEFT.x), 6);
    }

    /* pedals: ribbed pads, throttle tall and narrow like the cabinet's (the gyro's brake on the left) */
    if (h->gyro) {
      hud_native_button(paint, brake, h->brake_touch != 0);
      paint.mul = (hud_native_rgba){1, 1, 1, 0.55f};
      for (int i = 0; i < 5; ++i) hud_native_fill_rect(paint, brake.x + 18, brake.y + 28 + i * 20, brake.w - 36, 6);
      if (h->slide) hud_native_pedal_bar(paint, brake, h->brake_touch ? h->brake_v : 0);
    }
    side_proj = key_ortho(h->screen_w, h->screen_h, KEY_RIGHT);
    paint.projection = side_proj;
    hud_native_button(paint, THROTTLE, h->throttle_touch != 0);
    if (!h->gyro) hud_native_button(paint, brake, h->brake_touch != 0);
    paint.mul = (hud_native_rgba){1, 1, 1, 0.55f};
    for (int i = 0; i < 6; ++i) hud_native_fill_rect(paint, THROTTLE.x + 28, THROTTLE.y + 30 + i * 20, THROTTLE.w - 56, 6);
    if (!h->gyro)
      for (int i = 0; i < 5; ++i) hud_native_fill_rect(paint, brake.x + 18, brake.y + 28 + i * 20, brake.w - 36, 6);
    /* slider pedals: each one's travel, a bar up its right edge */
    if (h->slide) {
      hud_native_pedal_bar(paint, THROTTLE, h->throttle_touch ? h->throttle_v : 0);
      if (!h->gyro) hud_native_pedal_bar(paint, brake, h->brake_touch ? h->brake_v : 0);
    }

    paint.projection = control_ortho(h->screen_w, h->screen_h, HUD_EDIT_SHIFT_UP);
    hud_native_button(paint, up, 0);
    paint.mul = (hud_native_rgba){1, 1, 1, 0.92f};
    hud_native_chevron(paint, up.x + up.w / 2, up.y + up.h / 2 - 4, 22, 0, -1);
    paint.projection = control_ortho(h->screen_w, h->screen_h, HUD_EDIT_SHIFT_DOWN);
    hud_native_button(paint, down, 0);
    hud_native_chevron(paint, down.x + down.w / 2, down.y + down.h / 2 + 4, 22, 0, 1);
  }

  if (all_keys) {
    paint.projection = key_ortho(h->screen_w, h->screen_h, KEY_TOP);
    hud_native_button(paint, RESET, 0);
    paint.mul = (hud_native_rgba){1, 1, 1, 0.9f};
    hud_native_ring(paint, RESET.x + 24, RESET.y + 24, 10, 14);
    hud_native_triangle(paint, RESET.x + 32, RESET.y + 6, RESET.x + 42, RESET.y + 17, RESET.x + 29, RESET.y + 19);
    paint.projection = control_ortho(h->screen_w, h->screen_h, HUD_EDIT_CAMERA);
    hud_native_button(paint, CAMERA, 0);
    hud_native_ring(paint, CAMERA.x + 24, CAMERA.y + 24, 7, 12);
  }
  if (!h->pause_disabled) {
    paint.projection = control_ortho(h->screen_w, h->screen_h, HUD_EDIT_PAUSE);
    hud_native_button(paint, PAUSE, 0);
    paint.mul = (hud_native_rgba){1, 1, 1, 0.9f};
    hud_native_fill_rect(paint, PAUSE.x + 15, PAUSE.y + 13, 6, 22);
    hud_native_fill_rect(paint, PAUSE.x + 27, PAUSE.y + 13, 6, 22);
  }
  if (all_keys && h->passing_available) {
    paint.projection = key_ortho(h->screen_w, h->screen_h, KEY_TOP);
    hud_native_button(paint, PAUSE, h->passing_pressed);
    paint.mul = (hud_native_rgba){1, 1, 1, 0.9f};
    hud_native_ring(paint, PAUSE.x + 27, PAUSE.y + 24, 8, 11);
    for (int ray = 0; ray < 3; ++ray) hud_native_fill_rect(paint, PAUSE.x + 7, PAUSE.y + 16 + 7 * ray, 12, 2);
  }
}

void hud_draw_menu_option(float screen_w, float screen_h, int held) {
  rect r = menu_place(MENU_OPTION, KEY_RIGHT);
  hud_native_paint paint = hud_native_paint_for(screen_ortho(screen_w, screen_h));
  hud_native_button(paint, r, held);
  /* a gear: eight teeth round a ring */
  paint.mul = (hud_native_rgba){1, 1, 1, 0.92f};
  float cx = r.x + r.w / 2, cy = r.y + r.h / 2;
  hud_native_ring(paint, cx, cy, 5, 13);
  for (int k = 0; k < 8; ++k) {
    float a = (float)k * 0.785398f, c = cosf(a), s = sinf(a), w = 4.0f;
    float x0 = cx + c * 11, y0 = cy + s * 11, x1 = cx + c * 18, y1 = cy + s * 18;
    hud_native_triangle(paint, x0 - s * w, y0 + c * w, x1 - s * w, y1 + c * w, x1 + s * w, y1 - c * w);
    hud_native_triangle(paint, x0 - s * w, y0 + c * w, x1 + s * w, y1 - c * w, x0 + s * w, y0 - c * w);
  }
}

void hud_draw_menu_dress(float screen_w, float screen_h, int held) {
  rect r = menu_place(MENU_OPTION, KEY_RIGHT);
  hud_native_paint paint = hud_native_paint_for(screen_ortho(screen_w, screen_h));
  hud_native_button(paint, r, held);
  /* a wheel: the rim, the hub and five spokes */
  paint.mul = (hud_native_rgba){1, 1, 1, 0.92f};
  float cx = r.x + r.w / 2, cy = r.y + r.h / 2;
  hud_native_ring(paint, cx, cy, 15, 19);
  hud_native_ring(paint, cx, cy, 2, 5);
  for (int k = 0; k < 5; ++k) {
    float a = (float)k * 1.256637f - 1.570796f, c = cosf(a), s = sinf(a), w = 1.8f;
    float x0 = cx + c * 4, y0 = cy + s * 4, x1 = cx + c * 16, y1 = cy + s * 16;
    hud_native_triangle(paint, x0 - s * w, y0 + c * w, x1 - s * w, y1 + c * w, x1 + s * w, y1 - c * w);
    hud_native_triangle(paint, x0 - s * w, y0 + c * w, x1 + s * w, y1 - c * w, x0 + s * w, y0 - c * w);
  }
}

void hud_draw_menu_hidden(float screen_w, float screen_h, int held) {
  hud_native_paint paint = hud_native_paint_for(screen_ortho(screen_w, screen_h));
  hud_native_button(paint, menu_place(MENU_HIDDEN, KEY_TOP), held);
}

void hud_draw_menu_erase(float screen_w, float screen_h, int held, int armed) {
  rect r = menu_place(MENU_OPTION, KEY_RIGHT);
  hud_native_paint paint = hud_native_paint_for(screen_ortho(screen_w, screen_h));
  hud_native_button(paint, r, held);
  /* a bin: the lid and its handle, the body with three slots (red once armed) */
  if (armed) paint.mul = (hud_native_rgba){1, 0.25f, 0.2f, 0.95f};
  else paint.mul = (hud_native_rgba){1, 1, 1, 0.92f};
  float cx = r.x + r.w / 2, cy = r.y + r.h / 2;
  hud_native_fill_rect(paint, cx - 6, cy - 21, 12, 3);
  hud_native_fill_rect(paint, cx - 17, cy - 18, 34, 4);
  hud_native_fill_rect(paint, cx - 13, cy - 11, 3, 29);
  hud_native_fill_rect(paint, cx + 10, cy - 11, 3, 29);
  hud_native_fill_rect(paint, cx - 13, cy + 15, 26, 3);
  for (int k = -1; k <= 1; ++k) hud_native_fill_rect(paint, cx + (float)k * 6 - 1, cy - 7, 2.5f, 19);
}

void hud_draw_menu_keys(float screen_w, float screen_h, int held, int keys, int back) {
  rect left = menu_arrow_place(MENU_LEFT, -1), right = menu_arrow_place(MENU_RIGHT, 1);
  rect ret = menu_place(MENU_BACK, KEY_RIGHT);
  hud_native_paint paint = hud_native_paint_for(screen_ortho(screen_w, screen_h));
#if defined(__ANDROID__) || defined(WMMT_MID_MENU_KEYS_TEST)
  for (int i = 0; i < 2; ++i) {
    if (!(keys & (1 << i))) continue;
    int direction = i ? 1 : -1;
    rect r = i ? right : left;
    float v[48];
    menu_arrow_vertices(r, direction, 2, v);
    paint.mul = (hud_native_rgba){0.13f, 0.13f, 0.15f, 0.65f};
    hud_native_solid(paint, v, sizeof v, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST, 24);
    menu_arrow_vertices(r, direction, 0, v);
    float shade = held == direction ? 0.78f : 1.0f;
    paint.mul = (hud_native_rgba){shade, shade, shade, 0.97f};
    hud_native_solid(paint, v, sizeof v, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST, 24);
  }
#else
  if (keys) {
    hud_native_button(paint, left, held < 0);
    hud_native_button(paint, right, held == 1);
    paint.mul = (hud_native_rgba){1, 1, 1, 0.92f};
    hud_native_chevron(paint, left.x + left.w / 2 - 6, left.y + left.h / 2, 22, -1, 0);
    hud_native_chevron(paint, right.x + right.w / 2 + 6, right.y + right.h / 2, 22, 1, 0);
  }
#endif
  if (back) {
    /* a return arrow: shaft and hook, with a chevron head pointing left */
    hud_native_button(paint, ret, held == HUD_MENU_BACK);
    paint.mul = (hud_native_rgba){1, 1, 1, 0.92f};
    float cx = ret.x + ret.w / 2, cy = ret.y + ret.h / 2;
    hud_native_chevron(paint, cx - 12, cy + 6, 16, -1, 0);
    hud_native_fill_rect(paint, cx - 14, cy + 4, 26, 4);
    hud_native_fill_rect(paint, cx + 10, cy - 12, 4, 20);
    hud_native_fill_rect(paint, cx - 2, cy - 12, 16, 4);
  }
}

static void hud_native_draw_layout_mode(float screen_w, float screen_h, int mode, int sel) {
  hud_state h;
  hud_init(&h, screen_w, screen_h);
  hud_set_steer_mode(&h, mode);
  hud_native_paint paint = hud_native_paint_for(screen_ortho(screen_w, screen_h));
  hud_native_draw_keys(paint, &h, 0, 1);
  
  /* each group's box, the chosen one's orange */
  for (int g = 0; g < HUD_EDIT_GROUPS; ++g) {
    if (g >= HUD_EDIT_SHIFT && g != sel) continue;
    rect r = placed_group(g, mode);
    r = (rect){ r.x - 6, r.y - 6, r.w + 12, r.h + 12 };
    if (g == sel) paint.mul = (hud_native_rgba){1.0f, 0.42f, 0.05f, 0.95f};
    else paint.mul = (hud_native_rgba){1, 1, 1, 0.35f};
    hud_native_frame_rect(paint, r, g == sel ? 4 : 2);
  }
}

/* A group affine produces a new value; there is nothing to save/restore after
 * an anm, navi or nested HUD draw. The caller's original paint is untouched. */
static hud_native_paint hud_native_group(hud_native_paint paint, int group) {
  float x,y; race_pivot(group,&x,&y);
  float k=race_k[group];
  mat4 affine=mat4_identity();
  affine.m[0]=affine.m[5]=k;
  affine.m[12]=(1-k)*x+race_dx[group];
  affine.m[13]=(1-k)*y+race_dy[group];
  paint.projection=mat4_mul(paint.projection,affine);
  return paint;
}

/* Preview is intentionally independent of the UI batch and of any GL/VKcompat
 * scope. Resource uploads may use the resource table, but drawing reads none of
 * its program/uniform/vertex/binding state, even when preview_load is cached. */
int hud_meter_preview(int pack, int style, float x, float y, float w, float h, float alpha) {
  if (!tex_prog || w<=0 || h<=0 || alpha<=0 || !preview_load(pack,style)) return 0;
  int zone=style*2, count=style ? METERDB_V2[pack].n[zone] : METERDB[pack].n[0];
  float l=1e9f,r=-1e9f,t=1e9f,b=-1e9f;
  car_state idle={0};
  for (int i=0;i<count;++i) {
    const meterdb_part *p=style ? &METERDB_V2[pack].parts[zone][i] : &METERDB[pack].parts[0][i];
    const preview_alpha_bounds *a=&preview_alpha[i];
    if (!a->visible) continue;
    float angle=(p->a0+p->a1*meter_input(p,&idle))*(float)M_PI/180.0f;
    float c=cosf(angle),s=sinf(angle);
    for (int j=0;j<4;++j) {
      float dx=(j&1 ? a->r : a->l)-preview_meter[i].w*.5f;
      float dy=(j&2 ? a->b : a->t)-preview_meter[i].h*.5f;
      float xx=p->x+dx*c-dy*s, yy=p->y+dx*s+dy*c;
      l=fminf(l,xx);r=fmaxf(r,xx);t=fminf(t,yy);b=fmaxf(b,yy);
    }
  }
  if (r<=l || b<=t) return 0;
  float k=fminf(w/(r-l),h/(b-t)), cx=x+w*.5f, cy=y+h*.5f;
  hud_native_paint paint=hud_native_paint_for(screen_ortho(1024,768));
  paint.mul.a=fminf(alpha,1);
  for (int i=0;i<count;++i) {
    const meterdb_part *p=style ? &METERDB_V2[pack].parts[zone][i] : &METERDB[pack].parts[0][i];
    paint.additive=p->add != 0;
    hud_native_draw_k(paint,&preview_meter[i],(cx+(p->x-(l+r)*.5f)*k)*1.6f,
      (cy+(p->y-(t+b)*.5f)*k)*1.6f,p->a0+p->a1*meter_input(p,&idle),k*1.6f);
  }
  return 1;
}

static int hud_native_warm_one(hud_native_paint paint, GLuint tex, unsigned char *done, int *n) {
  if (!tex || *done) return 0;
  if (*n<=0) return 1;
  static const float v[16]={0,0,0,0, 1,0,1,0, 0,1,0,1, 1,1,1,1};
  /* warm_only validates resources/builds a pipeline without a frame/pass/item. */
  if (!hud_native_textured(paint,tex,v,sizeof v,1)) return 1;
  *done=1; --*n;
  return 0;
}
int hud_warm(float screen_w, float screen_h, int n) {
  if (!tex_prog) return 0;
  hud_native_paint paint=hud_native_paint_for(screen_ortho(screen_w,screen_h));
  paint.mul.a=0;
  int left=0;
  for (int i=0;i<METERDB_MAX_PARTS;++i) left+=hud_native_warm_one(paint,METER[i].tex,&meter_warm[i],&n);
  for (int i=0;i<SPR_COUNT;++i) left+=hud_native_warm_one(paint,SPR[i].tex,&spr_warm[i],&n);
  for (int i=0;i<2;++i) left+=hud_native_warm_one(paint,NAVI.tex[i],&navi_warm[i],&n);
  return left;
}

static void hud_native_navi(const hud_state *h, const car_race *r) {
  if (!NAVI.n || navi_city<0 || navi_city!=navi_requested) return;
  if (NAVI.next!=r->next_area) {
    NAVI.lit[0]=NAVI.next==NAVI_UNSET ? NAVI_UNSET : NAVI.lit[1];
    NAVI.lit[1]=r->area; NAVI.lit[2]=r->next_area; NAVI.next=r->next_area;
  }
  int width=0,height=0;
  cinder_vk_screen_extent(&width,&height);
  if (width<=0 || height<=0 || h->screen_h<=0 || h->screen_w+2*EDGE<=0) return;
  float sx=(float)width/(h->screen_w+2*EDGE), sy=(float)height/h->screen_h;
  float x=tx(17),y=ty(285)-MAP_UP,w=88*HUD_K,hh=82*HUD_K;
  race_map_rect(&x,&y,&w,&hh);
  double wx=floor((double)(x+EDGE)*sx+.5), wy=floor((double)(h->screen_h-y-hh)*sy+.5);
  double ww=floor((double)w*sx+.5), wh=floor((double)hh*sy+.5);
  if (!isfinite(wx)||!isfinite(wy)||!isfinite(ww)||!isfinite(wh)||ww<=0||wh<=0) return;
  double x0=fmax(wx,0),y0=fmax(wy,0),x1=fmin(wx+ww,width),y1=fmin(wy+wh,height);
  if (x1<=x0 || y1<=y0) return;
  int clipped[4]={(int)x0,(int)y0,(int)(x1-x0),(int)(y1-y0)};
  /* Local depth clear cannot erase world depth outside the minimap clip. */
  if (!cinder_vk_clear(0,VK_IMAGE_ASPECT_DEPTH_BIT,NULL,clipped)) return;
  float fx=-sinf(r->map_angle),fz=-cosf(r->map_angle);
  const float eye[3]={r->map_x,2000,r->map_z},at[3]={r->map_x,0,r->map_z},up[3]={fx,0,fz};
  mat4 mvp=mat4_mul(mat4_ortho(-2000,2000,-1200,2800,5,10000),mat4_look_at(eye,at,up));
  if (x0!=wx || y0!=wy || x1!=wx+ww || y1!=wy+wh) {
    mat4 crop=mat4_identity();
    crop.m[0]=(float)(ww/(x1-x0)); crop.m[5]=(float)(wh/(y1-y0));
    crop.m[12]=(float)((2*(wx-x0)+ww)/(x1-x0)-1);
    crop.m[13]=(float)((2*(wy-y0)+wh)/(y1-y0)-1);
    mvp=mat4_mul(crop,mvp);
  }
  hud_native_paint paint=hud_native_paint_for(mvp);
  cinder_vk_draw road;
  if (!hud_native_packet(&road,NAVI.prog,paint,VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST)) return;
  memcpy(road.viewport,clipped,sizeof clipped); memcpy(road.scissor,clipped,sizeof clipped);
  road.pipeline.depth_test=VK_TRUE;
  road.indexed=VK_TRUE; road.index_type=VK_INDEX_TYPE_UINT16; road.index_buffer=NAVI.ibo;
  if (!cinder_vk_uniform(&road,"uMVP",mvp.m,sizeof mvp.m)||!hud_native_sample(&road,NAVI.tex[0])) return;
  for (int pass=0;pass<2;++pass) {
    road.pipeline.depth_write=pass==0;
    for (int i=0;i<NAVI.n;++i) {
      const navi_mesh *m=&NAVI.mesh[i];
      if (m->blend!=pass || (m->area>=0 && navi_lit(m->area)!=m->on)) continue;
      size_t base=(size_t)m->vert*NAVI_VERT;
      road.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32B32_SFLOAT,.stride=NAVI_VERT,.buffer=NAVI.vbo,.offset=base};
      road.attributes[1]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=NAVI_VERT,.buffer=NAVI.vbo,.offset=base+12};
      road.attributes[2]=(cinder_vk_attribute){.format=VK_FORMAT_R8G8B8A8_UNORM,.stride=NAVI_VERT,.buffer=NAVI.vbo,.offset=base+20};
      road.count=m->n_index; road.index_offset=(size_t)m->index*2;
      cinder_vk_submit(&road);
    }
  }
  float v[4][5];
  for (int i=0;i<4;++i) {
    float lx=i&1 ? -NAVI_ICON : NAVI_ICON,lz=i&2 ? NAVI_ICON : -NAVI_ICON;
    v[i][0]=r->map_x+lx*fz+lz*fx; v[i][1]=1900; v[i][2]=r->map_z-lx*fx+lz*fz;
    v[i][3]=NAVI_ICON_UV[i][0]; v[i][4]=NAVI_ICON_UV[i][1];
  }
  /* Fresh packet, not the last indexed mesh packet: no EBO or vertex colour
   * input can leak into the icon; white and disabled depth are explicit. */
  cinder_vk_draw icon;
  if (!hud_native_packet(&icon,NAVI.prog,paint,VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP)) return;
  memcpy(icon.viewport,clipped,sizeof clipped); memcpy(icon.scissor,clipped,sizeof clipped);
  icon.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32B32_SFLOAT,.stride=20,.data=v,.bytes=sizeof v};
  icon.attributes[1]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=20,.offset=12,.data=v,.bytes=sizeof v};
  icon.count=4;
  if (cinder_vk_uniform(&icon,"uMVP",mvp.m,sizeof mvp.m)&&hud_native_sample(&icon,NAVI.tex[1]))
    cinder_vk_submit(&icon);
}

static void hud_native_ta(hud_native_paint paint, const hud_state *h, const car_state *car) {
  const car_race *r=&car->race;
  if (!SPR[SPR_TILL_GOAL].tex) return;
  if (ten_level<0 && !vs_n) {
    hud_native_draw_till_goal(hud_native_group(paint,HUD_RACE_RANK),r->remain);
    hud_native_draw_times(hud_native_group(paint,HUD_RACE_TIME),r);
  }
  hud_native_paint map=hud_native_group(paint,HUD_RACE_MAP);
  hud_native_map_blit(map,SPR_MAP_WAKU,15,262);
  hud_native_navi(h,r);
  if (!ta_story && ta_course>=0 && ta_course<CAR_COURSES) hud_native_map_blit(map,SPR_MAP_NAME+ta_course,15,266);
  if (ta_story && r->map_text>=1 && r->map_text<=19) hud_native_map_blit(map,SPR_MAP_TEXT+r->map_text-1,15,266);
  hud_native_draw_time_left(hud_native_group(paint,HUD_RACE_TIME),r->time_left);
  if (!ta_story && ten_level<0) hud_native_draw_records(paint);
  hud_native_draw_sign(paint,r);
  if (r->state==CAR_RACE_RUN) hud_native_draw_time_extend(paint,r->total);
}

void hud_draw(const hud_state *h, const car_state *car, const car_input *in, float fps) {
  (void)in;
  hud_native_paint paint=hud_native_paint_for(screen_ortho(h->screen_w,h->screen_h));
  int consoles=ten_level<0 || ten_disp,all_keys=!keys_pause_only();
  hud_native_draw_keys(paint,h,car->steer,all_keys);
  hud_native_paint counter=paint; counter.mul=(hud_native_rgba){1,1,1,.6f};
  hud_native_number(counter,(int)(fps+.5f),2,16,16,12,20);
  if (tex_prog && consoles) {
    hud_native_paint meter=hud_native_group(paint,HUD_RACE_METER);
    hud_native_draw_meters(meter,car);
    hud_native_draw_shifter(paint,car);
    hud_native_draw_plate(meter,car);
    hud_native_ta(paint,h,car);
    draw_plate_text();
  }
  /* These are the unchanged animation owner API. It supplies its own explicit
   * native packets independently; do not recreate GL bindings around calls. */
  if (consoles) draw_rival_marks(car,0);
  draw_ten(car);
  if (consoles && ta_story && ten_level<0) draw_story_info(car);
  if (consoles) {
    draw_vs(car);
    draw_ghost_card(&car->race);
  }
  draw_ten_banner(car);
  draw_finish_remaining(&car->race);
  draw_countdown(car);
  draw_cutin();
}

void hud_negate(const hud_state *h) {
  hud_native_paint paint=hud_native_paint_for(screen_ortho(h->screen_w,h->screen_h));
  paint.negate=1;
  hud_native_fill_rect(paint,-EDGE,0,h->screen_w+2*EDGE,h->screen_h);
}
void hud_fade(const hud_state *h, float grey, float alpha) {
  if (alpha<=0) return;
  hud_native_paint paint=hud_native_paint_for(screen_ortho(h->screen_w,h->screen_h));
  paint.mul=(hud_native_rgba){grey,grey,grey,fminf(alpha,1)};
  hud_native_fill_rect(paint,-EDGE,0,h->screen_w+2*EDGE,h->screen_h);
}

/* The begin/end UI API deliberately owns its own pending CPU batch. A preview,
 * navi, anm or standalone key draw cannot alter this batch's projection/style. */
static hud_native_paint hud_native_ui_paint;
static void ui_flush(void) {
  if (!ui_n) return;
  hud_native_paint paint=hud_native_ui_paint;
  paint.mul=(hud_native_rgba){ui_rgba[0],ui_rgba[1],ui_rgba[2],ui_rgba[3]};
  hud_native_solid(paint,ui_v,(size_t)ui_n*12*sizeof *ui_v,VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST,(uint32_t)ui_n*6);
  ui_n=0;
}
static void ui_color(float r,float g,float b,float a) {
  if (ui_n && (ui_rgba[0]!=r||ui_rgba[1]!=g||ui_rgba[2]!=b||ui_rgba[3]!=a)) ui_flush();
  ui_rgba[0]=r;ui_rgba[1]=g;ui_rgba[2]=b;ui_rgba[3]=a;
}
static void ui_quad(float x,float y,float w,float h) {
  if (ui_n==UI_QUADS) ui_flush();
  float *v=ui_v+ui_n++*12;
  v[0]=x;v[1]=y;v[2]=x+w;v[3]=y;v[4]=x;v[5]=y+h;
  v[6]=x+w;v[7]=y;v[8]=x+w;v[9]=y+h;v[10]=x;v[11]=y+h;
}
void hud_ui_begin(float screen_w,float screen_h) {
  hud_native_ui_paint=hud_native_paint_for(screen_ortho(screen_w,screen_h));
  ui_n=0;
}
void hud_ui_end(void) { ui_flush(); }
void hud_ui_button(float x,float y,float w,float h,int held) {
  ui_flush(); hud_native_button(hud_native_ui_paint,(rect){x,y,w,h},held);
}
