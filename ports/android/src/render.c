#include "render.h"
#include "render_story_assembly.h"
#ifdef __ANDROID__
#include "ghost_catalog.h"
#endif

#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

#include "gl.h"
#ifdef WMMT_NATIVE_VK
#include "native_vk.h"
typedef struct { uint32_t target; int w, h; } native_scene_view;
static native_scene_view native_scene;
static uint32_t native_frame_texture, native_over_texture;
/* Explicit render_scene_clear background for this frame's final composite.
 * Other render passes and loader material parameters never change it. */
static float native_post_clear_color[4];
#endif
#if defined(WMMT_VK) && !defined(WMMT_NATIVE_VK)
/* Implemented by the Vulkan GL adapter; capability does not change the user setting. */
extern int vkgl_ssao_depth_supported(int w, int h);
#ifndef WMMT_NATIVE_VK
extern int vkgl_program_usable(GLuint id);
#endif
extern int vkgl_error_pending(void);
extern uint64_t vkgl_error_epoch(void);
/* Existing adapter scope: includes actual VAO/attribute state, unlike its GL queries. */
extern void *vkgl_preview_save(GLuint program);
extern void vkgl_scope_restore_preserve_error(void *snapshot);
#endif
#ifdef WMMT_EGL
#include <EGL/egl.h>
#endif

/* Same shading as the arcade's stage pixel program minus the gloss cubemap:
 * base texture * vertex colour (baked lighting), times the map's grade (render_params.grade),
 * then linear distance fog. */
static const char *VS =
  "attribute vec3 aPos; attribute vec2 aUV; attribute vec4 aColor;\n"
  "uniform mat4 uMVP; uniform vec3 uEye; uniform vec2 uFog; uniform vec2 uUVOff;\n"
  "varying vec2 vUV; varying lowp vec4 vColor; varying lowp float vFog;\n"
  "void main() {\n"
  "  gl_Position = uMVP * vec4(aPos, 1.0); vUV = aUV + uUVOff; vColor = aColor;\n"
  "  vFog = clamp((uFog.x - distance(aPos, uEye)) / (uFog.x - uFog.y), 0.0, 1.0);\n"
  "}\n";
#define FS_HEAD                                                                    \
  "precision mediump float;\n"                                                     \
  "uniform sampler2D uTex; uniform lowp vec3 uFogColor; uniform lowp vec3 uGrade;\n" \
  "varying vec2 vUV; varying lowp vec4 vColor; varying lowp float vFog;\n"         \
  "#ifdef WET\n"                                                                   \
  "uniform sampler2D uFrame; uniform float uWet; uniform vec3 uHorizon;\n"         \
  "#endif\n"                                                                       \
  "void main() {\n"                                                                \
  "  lowp vec4 c = texture2D(uTex, vUV) * vColor;\n"
/* WET (render_hq's road at night): the last frame mirrored about the horizon (uHorizon: one
 * over the frame's size, the horizon's height in it), streaked down the road a little, its
 * lights alone (over 0.55, at most 0.3: a tunnel's row of lamps is no white sheet) on the
 * asphalt, the more the nearer the horizon (the glancing angle) */
#define FS_TAIL                                                                    \
  "#ifdef WET\n"                                                                   \
  "  if (uWet > 0.0) {\n"                                                          \
  "    vec2 uv = gl_FragCoord.xy * uHorizon.xy;\n"                                 \
  "    float below = uHorizon.z - uv.y, y = uHorizon.z + below;\n"                  \
  "    if (below > 0.0 && y < 1.0) {\n"                                            \
  "      vec3 r = texture2D(uFrame, vec2(uv.x, y)).rgb + texture2D(uFrame, vec2(uv.x, y + below * 0.15)).rgb\n" \
  "             + texture2D(uFrame, vec2(uv.x, min(y + below * 0.3, 1.0))).rgb;\n"  \
  "      float g = clamp(1.0 - below * 2.5, 0.0, 1.0);\n"                         \
  "      c.rgb += min(max(r * (1.0 / 3.0) - 0.55, 0.0) * 1.5, 0.3) * (uWet * g * g);\n"            \
  "    }\n"                                                                        \
  "  }\n"                                                                          \
  "#endif\n"                                                                       \
  "  gl_FragColor = vec4(mix(uFogColor, c.rgb * uGrade, vFog), c.a);\n"            \
  "}\n"
static const char *FS = FS_HEAD FS_TAIL;
static const char *FS_CUTOUT = FS_HEAD "  if (c.a < 0.5) discard;\n" FS_TAIL;

/* The maps' gloss program (the stage IGBs' Cg, ARB text): base * colour plus the gloss map
 * times the cube at the eye's reflection about the normal, the sum fogged. */
static const char *VS_GLOSS =
  "attribute vec3 aPos; attribute vec2 aUV; attribute vec4 aColor; attribute vec3 aNormal;\n"
  "uniform mat4 uMVP; uniform vec3 uEye; uniform vec2 uFog; uniform vec2 uUVOff;\n"
  "varying vec2 vUV; varying lowp vec4 vColor; varying lowp float vFog; varying vec3 vRefl;\n"
  "void main() {\n"
  "  gl_Position = uMVP * vec4(aPos, 1.0); vUV = aUV + uUVOff; vColor = aColor;\n"
  "  vec3 i = normalize(aPos - uEye), n = normalize(aNormal);\n"
  "  vRefl = i - 2.0 * dot(n, i) * n;\n"
  "  vFog = clamp((uFog.x - distance(aPos, uEye)) / (uFog.x - uFog.y), 0.0, 1.0);\n"
  "}\n";
static const char *FS_GLOSS =
  "precision mediump float;\n"
  "uniform sampler2D uTex, uGloss; uniform samplerCube uCube; uniform lowp vec3 uFogColor, uGrade;\n"
  "varying vec2 vUV; varying lowp vec4 vColor; varying lowp float vFog; varying vec3 vRefl;\n"
  "void main() {\n"
  "  lowp vec4 c = texture2D(uTex, vUV) * vColor + texture2D(uGloss, vUV) * vec4(textureCube(uCube, vRefl).rgb, 1.0);\n"
  "#if CUTOUT\n"
  "  if (c.a < 0.5) discard;\n"
  "#endif\n"
  "  gl_FragColor = vec4(mix(uFogColor, c.rgb * uGrade, vFog), c.a);\n"
  "}\n";

/* The lit scenes' (the cars') programs, after the arcade's: car.cg and car_blend.cg are Cg
 * compiled to ARB programs that the car IGBs carry (tools/stage/scene.py car_shader), the rest
 * of a car (tyres, underbody) and the traffic take the fixed-function lighting with
 * car_light.lua's material. Lights and eye are in the model's space. PROG picks the program
 * (WPK_LIT_*), CUTOUT the alpha-tested variant. */
static const char *VS_LIT =
  "attribute vec3 aPos; attribute vec2 aUV; attribute vec4 aColor; attribute vec3 aNormal;\n"
  "uniform mat4 uMVP, uMV; uniform vec3 uEye, uL0, uL1, uD0, uD1, uAmb; uniform float uPower; uniform vec2 uFog;\n"
  "varying vec2 vUV; varying lowp vec4 vColor;\n"
  "#if PROG == 0\n"
  "varying lowp float vFog;\n"
  "#else\n"
  "varying vec2 vEnv; varying vec3 vOver;\n"
  "#endif\n"
  "#if PROG == 1\n"
  "varying vec3 vHalf, vNormal;\n"
  "#endif\n"
  "#if FRAME_ENV\n"
  "varying vec3 vFrame; varying float vFres;\n"
  "#endif\n"
  "void main() {\n"
  "  gl_Position = uMVP * vec4(aPos, 1.0); vUV = aUV;\n"
  /* render_hq's paint: the eye's reflection in view space, and Schlick's Fresnel term */
  "#if FRAME_ENV\n"
  "  vec3 fp = normalize((uMV * vec4(aPos, 1.0)).xyz), fn = normalize((uMV * vec4(aNormal, 0.0)).xyz);\n"
  "  vFrame = reflect(fp, fn);\n"
  "  float fc = 1.0 - clamp(-dot(fp, fn), 0.0, 1.0);\n"
  "  vFres = fc * fc * fc * fc * fc;\n"
  "#endif\n"
  "#if PROG != 0\n"
  /* the eye's reflection in the model's space, for the overhead map (render_overhead) */
  "  vec3 vi = normalize(aPos - uEye), vn = normalize(aNormal);\n"
  "  vOver = vi - 2.0 * dot(vn, vi) * vn;\n"
  "#endif\n"
  "  vec3 d = clamp((max(dot(aNormal, uL0), 0.0) * uD0 + uAmb + max(dot(aNormal, uL1), 0.0) * uD1) * aColor.rgb, 0.0, 1.0);\n"
  "#if PROG == 0\n"
  "  vColor = vec4(d, aColor.a);\n"
  "  vFog = clamp((uFog.x - distance(aPos, uEye)) / (uFog.x - uFog.y), 0.0, 1.0);\n"
  "#elif PROG == 1\n"
  /* car.cg: the environment's weight 1 - uniformEnvMapPower rides in the colour's alpha, the
   * sphere map's v takes the upper half of the image */
  "  vColor = vec4(d, 1.0 - uPower);\n"
  "  vHalf = normalize(normalize(uEye - aPos) + uL0); vNormal = aNormal;\n"
  "  vec2 n = (uMV * vec4(aNormal, 0.0)).xy * 0.5 + 0.5;\n"
  "  vEnv = vec2(n.x, n.y * 0.5 + 0.5);\n"
  "#else\n"
  /* car_blend.cg: the view vector reflected about the normal in view space, the upper 40% */
  "  vColor = vec4(d, aColor.a);\n"
  "  vec3 p = (uMV * vec4(aPos, 1.0)).xyz;\n"
  "  vec3 e = p * inversesqrt(dot(p, p) + 1.0);\n"
  "  vec3 n = normalize((uMV * vec4(aNormal, 0.0)).xyz);\n"
  "  vec2 r = e.xy - 2.0 * dot(e, n) * n.xy;\n"
  "  vEnv = vec2(r.x * 0.5 + 0.5, (r.y * 0.5 + 0.5) * 0.4 + 0.6);\n"
  "#endif\n"
  "}\n";
/* glass shows the overhead map this much more than its own reflection (not the arcade's) */
#define OVER_GLASS "0.75"
static const char *FS_LIT =
  "precision mediump float;\n"
  "uniform sampler2D uTex, uEnv, uSpec, uAO; uniform lowp vec3 uFogColor;\n"
  "varying vec2 vUV; varying lowp vec4 vColor;\n"
  "#if PROG == 0\n"
  "varying lowp float vFog;\n"
  "#else\n"
  "varying vec2 vEnv; varying vec3 vOver;\n"
  /* the environment with what is over the car over it: the reflection as the overhead map
   * sees it (its eye looks ahead and OVER_PITCH up: uOverDir its sine and cosine; its x the
   * car's -x), as much as the map has something there (alpha) and uOver.x lets, fading
   * toward its edges (uOver.y = 1 / tan of its half angle); a its share */
  "uniform sampler2D uOverTex; uniform vec2 uOver, uOverDir;\n"
  "vec4 overhead(vec3 env) {\n"
  "  float ahead = dot(vOver.yz, uOverDir);\n"
  "  vec2 d = vec2(-vOver.x, vOver.y * uOverDir.y - vOver.z * uOverDir.x) / max(ahead, 0.01) * uOver.y;\n"
  "  lowp vec4 o = texture2D(uOverTex, d * 0.5 + 0.5);\n"
  "  float w = o.a * uOver.x * clamp(ahead * 4.0, 0.0, 1.0) * clamp((1.0 - max(abs(d.x), abs(d.y))) * 5.0, 0.0, 1.0);\n"
  "  return vec4(mix(env, o.rgb, w), w);\n"
  "}\n"
  "#endif\n"
  "#if PROG == 1\n"
  "varying highp vec3 vHalf, vNormal;\n"
  "#endif\n"
  /* render_hq: the paint reflects the last frame (the street, its lights) as an environment:
   * a reflection ahead at its place on the screen, one behind the eye mirrored into the
   * screen's upper part (clear of the car itself, in the lower middle); uFrameK 0 outside
   * the race's frames */
  "#if FRAME_ENV\n"
  "uniform sampler2D uFrame; uniform float uFrameK; varying vec3 vFrame; varying float vFres;\n"
  "vec3 frame_env() {\n"
  "  vec3 r = normalize(vFrame);\n"
  "  vec2 q = r.xy / (abs(r.z) + 0.3);\n"
  "  vec2 uv = 0.5 + 0.5 * q * vec2(0.56, 1.0);\n"
  "  if (r.z > 0.0) uv.y = 0.6 + 0.4 * clamp(0.5 + 0.5 * q.y, 0.0, 1.0);\n"
  "  return texture2D(uFrame, clamp(uv, 0.002, 0.998)).rgb;\n"
  "}\n"
  "#endif\n"
  "void main() {\n"
  "  lowp vec4 t = texture2D(uTex, vUV);\n"
  /* the baked ambient occlusion (bake_ao.c; white where there is none, or it is off) */
  "  lowp float ao = texture2D(uAO, vUV).r;\n"
  "#if PROG == 0\n"
  "  lowp vec4 c = t * vColor;\n"
  "  c.rgb *= ao;\n"
  "#elif PROG == 1\n"
  /* the environment scaled by its own brightness, plus a specular power of 256 */
  "  vec3 e = overhead(texture2D(uEnv, vEnv).rgb).rgb * vColor.rgb;\n"
  "  e *= dot(e, e);\n"
  "  highp float s = pow(clamp(dot(normalize(vNormal), normalize(vHalf)), 0.0, 1.0), 256.0);\n"
  "#if FRAME_ENV\n"
  /* the clear coat: the frame's reflection squared (its lights, not a grey wash of the dark
   * street over the paint) by the Fresnel term over a small floor */
  "  vec3 fe = frame_env();\n"
  "  e += fe * fe * (uFrameK * (0.15 + 1.45 * vFres));\n"
  "#endif\n"
  "  vec4 c = vec4((t.rgb * vColor.rgb + vColor.a * e + s) * ao, 1.0);\n"
  "#else\n"
  /* glass (see-through: its specular map's reflection is faint) shows what is overhead more
   * than the sky; the opaque parts (wheels, lamp bodies) as they were */
  "  vec4 o = overhead(texture2D(uEnv, vEnv).rgb);\n"
  "  float g = o.a * " OVER_GLASS " * step(t.a, 0.98);\n"
  "  vec4 c = vec4(mix(t.rgb, o.rgb, min(texture2D(uSpec, vUV).r + g, 1.0)) * ao, t.a) * vColor;\n"
  "#endif\n"
  "#if CUTOUT\n"
  "  if (c.a < 0.5) discard;\n"
  "#endif\n"
  "#if PROG == 0\n"
  "  gl_FragColor = vec4(mix(uFogColor, c.rgb, vFog), c.a);\n"
  "#else\n"
  "  gl_FragColor = c;\n"
  "#endif\n"
  "}\n";

typedef struct {
  GLuint id;
  GLint mvp, mv, eye, l0, l1, d0, d1, amb, power, fog, fog_color, over, over_dir, frame_k;
} lit_prog;
/* render_hq's paint reflection: the last frame's texture unit, and its weight while the
 * race's frame is drawn (render_blur_begin .. end) */
#define FRAME_UNIT 5
static float frame_k;
static int frame_wet; /* the wet road takes the last frame too (render_hq_options) */
static int frame_env; /* lit_init: car.cg with the frame's reflection */
/* A frame was recorded into blur.tex since its last allocation/reset. */
static int frame_history_valid;
#ifdef WMMT_VK
static uint64_t frame_start_epoch, frame_history_epoch;
static int frame_recording_trusted;
#endif
/* by WPK_LIT_* * 2 + alpha-tested (car.cg's output is opaque: its pair is the same program) */
static lit_prog lit_progs[2 * WPK_LIT_PROGS];
/* the overhead map's texture unit and 1 / tan of its half angle (render_overhead) */
#define OVER_UNIT 3
#define OVER_PITCH 0.61f /* its eye's look above ahead (35 degrees) */
static float over_inv_tan = 1.0f;
/* the baked ambient occlusion's texture unit, and whether it shows (wpk_ao) */
#define AO_UNIT 4
static int ao_on = 1;
void wpk_ao(int on) { ao_on = on != 0; }

/* the shadow volumes' program: positions, one colour */
static const char *VS_SHADOW =
  "attribute vec3 aPos; uniform mat4 uMVP;\n"
  "void main() { gl_Position = uMVP * vec4(aPos, 1.0); }\n";
static const char *FS_SHADOW =
  "precision mediump float; uniform lowp vec4 uColor;\n"
  "void main() { gl_FragColor = uColor; }\n";
static GLuint shadow_prog;
#ifndef WMMT_NATIVE_VK
static GLint shadow_mvp, shadow_color;
#endif
/* the arcade's final pass darkens the marked pixels with black at alpha 0.5 */
#define SHADOW_ALPHA 0.5f

/* clRadialBlur's composite: the frame's texture 1:1 in the middle; in the side bands the
 * average of radial_blur.cg's 8 samples (each scaled toward the centre by up to
 * BlurWidth -0.07 times Width 1), mixed in by the band's alpha (1 at the screen edge, 0 at
 * its inner edge). The samples' coordinates come from the vertex shader, so the GPU fetches
 * them ahead. BLUR_TAPS 1 is the middle's program; with SHARPEN the middle sharpened (the
 * OPTION screen's, not the arcade's): AMD FidelityFX FSR 1's RCAS on the frame's own
 * 1024 x 768, its four neighbours' coordinates from the vertex shader too. Its lobe comes from
 * the green channel alone (about the luma) rather than from each channel's: a third of the
 * arithmetic over the 786k pixels, which the A5X's GPU, already near its 16.7 ms, feels. */
static const char *VS_BLUR =
  "attribute vec2 aPos; attribute vec2 aUV; attribute float aAlpha;\n"
  "varying vec2 vT0; varying lowp float vAlpha;\n"
  "#if SHARPEN\n"
  "uniform vec2 uTexel; varying vec2 vN, vS, vW, vE;\n"
  "#endif\n"
  "#if BLUR_TAPS > 1\n"
  "varying vec2 vT1, vT2, vT3, vT4, vT5, vT6, vT7;\n"
  "#endif\n"
  "void main() {\n"
  "  gl_Position = vec4(aPos, 0.0, 1.0); vT0 = aUV; vAlpha = aAlpha;\n"
  "#if SHARPEN\n"
  "  vN = aUV - vec2(0.0, uTexel.y); vS = aUV + vec2(0.0, uTexel.y);\n"
  "  vW = aUV - vec2(uTexel.x, 0.0); vE = aUV + vec2(uTexel.x, 0.0);\n"
  "#endif\n"
  "#if BLUR_TAPS > 1\n"
  "  vec2 d = aUV - 0.5;\n"
  "  vT1 = d * (1.0 - 0.07 / 7.0) + 0.5; vT2 = d * (1.0 - 0.07 * 2.0 / 7.0) + 0.5;\n"
  "  vT3 = d * (1.0 - 0.07 * 3.0 / 7.0) + 0.5; vT4 = d * (1.0 - 0.07 * 4.0 / 7.0) + 0.5;\n"
  "  vT5 = d * (1.0 - 0.07 * 5.0 / 7.0) + 0.5; vT6 = d * (1.0 - 0.07 * 6.0 / 7.0) + 0.5;\n"
  "  vT7 = d * 0.93 + 0.5;\n"
  "#endif\n"
  "}\n";
static const char *FS_BLUR =
  "precision mediump float;\n"
  "uniform sampler2D uTex;\n"
  "#if HQ\n"
  "#define LOWP\n"
  "uniform sampler2D uBloom, uAO; uniform float uBloomK;\n"
  "#else\n"
  "#define LOWP lowp\n"
  "#endif\n"
  "varying vec2 vT0; varying lowp float vAlpha;\n"
  "#if BLUR_TAPS > 1\n"
  "varying vec2 vT1, vT2, vT3, vT4, vT5, vT6, vT7;\n"
  "#endif\n"
  "#if SHARPEN\n"
  "uniform float uSharp; varying vec2 vN, vS, vW, vE;\n"
  "#endif\n"
  "void main() {\n"
  "  lowp vec4 c = texture2D(uTex, vT0);\n"
  "#if SHARPEN\n"
  /* RCAS: the most negative lobe that keeps the cross of five from clipping, at most
   * 1/4 - 1/16, times the sharpness */
  "  lowp vec3 n = texture2D(uTex, vN).rgb, so = texture2D(uTex, vS).rgb;\n"
  "  lowp vec3 w = texture2D(uTex, vW).rgb, e = texture2D(uTex, vE).rgb;\n"
  "  float mn = min(min(n.g, so.g), min(w.g, e.g)), mx = max(max(n.g, so.g), max(w.g, e.g));\n"
  "  float hit = max(-mn / (4.0 * mx + 0.004), (1.0 - mx) / min(4.0 * mn - 4.0, -0.004));\n"
  "  float lobe = clamp(hit, -0.1875, 0.0) * uSharp;\n"
  "  c.rgb = clamp((lobe * (n + so + w + e) + c.rgb) * (1.0 / (4.0 * lobe + 1.0)), 0.0, 1.0);\n"
  "#endif\n"
  "#if BLUR_TAPS > 1\n"
  "  LOWP vec4 b = (c + texture2D(uTex, vT1) + texture2D(uTex, vT2) + texture2D(uTex, vT3) + texture2D(uTex, vT4)\n"
  "                 + texture2D(uTex, vT5) + texture2D(uTex, vT6) + texture2D(uTex, vT7)) * 0.125;\n"
  "  c = mix(c, b, vAlpha);\n"
  "#endif\n"
  /* render_hq: the ambient occlusion (white without), the bloom added, then the highlights
   * over 0.8 rolled off toward 1 (below it the arcade's colours as they were) */
  "#if HQ\n"
  "  c.rgb *= texture2D(uAO, vT0).r;\n"
  "  c.rgb += texture2D(uBloom, vT0).rgb * uBloomK;\n"
  "  c.rgb = mix(c.rgb, 0.8 + 0.2 * (1.0 - exp((0.8 - c.rgb) * 5.0)), step(0.8, c.rgb));\n"
  "#endif\n"
  "  gl_FragColor = vec4(c.rgb, 1.0);\n"
  "}\n";
static GLuint blur_progs[6]; /* the middle's, the bands', the middle's sharpened; +3: render_hq's */
#ifndef WMMT_NATIVE_VK
static GLint sharp_texel[2], sharp_amount[2], bloom_k[3];
#endif
static struct {
  GLuint fbo, tex, depth;
  int w, h, deep; /* deep: RGBA8 (sharpening: 16 bits' steps would show), else RGB565 */
  GLint screen; /* the framebuffer to put the frame on */
  int out_w, out_h; /* its size (render_hq's frame is scaled up to it) */
  float amount, sharp;
} blur;

/* the opaque and blended batches' program (no discard), the alpha-tested ones' */
typedef struct {
  GLuint id;
  GLint mvp, eye, fog, fog_color, tex, uv_off, grade, wet, horizon; /* (wet, horizon: WET's) */
} scene_prog;
static scene_prog progs[2], gloss_progs[2];
static GLuint white_tex;
/* The shader samples uFrame even at frame_k==0: always supply a safe texture. */
static void frame_sampler(GLuint tex) {
#ifdef WMMT_NATIVE_VK
  native_frame_texture = tex;
#else
  GLint active;
  glGetIntegerv(GL_ACTIVE_TEXTURE, &active);
  glActiveTexture(GL_TEXTURE0 + FRAME_UNIT);
  glBindTexture(GL_TEXTURE_2D, tex);
  glActiveTexture((GLenum)active);
#endif
}
static void frame_sampler_off(void) {
  frame_k = 0.0f; frame_wet = 0;
  frame_sampler(white_tex);
}

#if defined(WMMT_EGL) && !defined(WMMT_NATIVE_VK)
PFNGLGENVERTEXARRAYSOESPROC wmmt_glGenVertexArraysOES;
PFNGLBINDVERTEXARRAYOESPROC wmmt_glBindVertexArrayOES;
PFNGLDELETEVERTEXARRAYSOESPROC wmmt_glDeleteVertexArraysOES;
#endif

typedef struct {
  char magic[4];
  uint32_t n_tex, n_chunk, n_batch;
  float chunk_size;
  uint32_t tex_off, chunk_off, batch_off;
} wpk_header;

typedef struct {
  char name[48];
  uint16_t w, h;
  uint32_t fmt, off, size;
} wpk_tex;

typedef struct {
  uint16_t tex, flags;
  uint32_t vtx_off, vtx_count, idx_off, idx_count;
} wpk_batch_rec;

/* a buffer pool's vertices at most: its indices stay 16-bit */
#define POOL_VERTS 65536u

/* Shared by normal and shadow drawing; subtraction avoids first+n overflow. */
static int wpk_chunk_valid(const wpk_chunk *ch, uint32_t n_batch) {
  return ch->first <= n_batch && ch->n <= n_batch - ch->first;
}

/* File ranges are half-open; an empty range is valid through EOF. */
static int wpk_range_valid(uint64_t size, uint64_t off, uint64_t length) {
  return off <= size && length <= size - off;
}

/* GL buffer sizes and our pool counters must both represent the whole index buffer. */
static int wpk_index_buffer_valid(uint32_t bytes, uint32_t count) {
  uint64_t total = (uint64_t)bytes + (uint64_t)count * 2u;
  return total <= UINT32_MAX && total <= PTRDIFF_MAX;
}

/* Validate before changing indices or sending any part of this batch to GL. */
static int wpk_indices_valid(const uint16_t *idx, uint32_t count, uint32_t vertices, uint32_t base) {
  if (vertices > POOL_VERTS || base > POOL_VERTS || vertices > POOL_VERTS - base) return 0;
  for (uint32_t i = 0; i < count; ++i)
    if (idx[i] >= vertices || (uint32_t)idx[i] >= POOL_VERTS - base) return 0;
  return 1;
}

#ifndef WMMT_NATIVE_VK
GLuint gl_compile_program(const char *vs, const char *fs, const char **attribs, int n_attribs) {
#ifdef WMMT_DUMP_PROGS
  {
    static int dumped;
    char path[256];
    snprintf(path, sizeof path, "%s/%03d.txt", getenv("WMMT_DUMP_PROGS"), dumped++);
    FILE *f = fopen(path, "w");
    if (f) {
      for (int i = 0; i < n_attribs; ++i) fprintf(f, "%s%s", i ? " " : "// attribs: ", attribs[i]);
      fprintf(f, "\n//----VS\n%s\n//----FS\n%s", vs, fs);
      fclose(f);
    }
  }
#endif
#ifdef WMMT_VK
  return vkgl_program(vs, fs, attribs, n_attribs); /* (made ahead as SPIR-V: tools/vkglsl.py) */
#else
  GLuint p = glCreateProgram();
  const char *src[2] = { vs, fs };
  GLenum type[2] = { GL_VERTEX_SHADER, GL_FRAGMENT_SHADER };
  for (int i = 0; i < 2; ++i) {
    GLuint s = glCreateShader(type[i]);
    glShaderSource(s, 1, &src[i], NULL);
    glCompileShader(s);
    GLint ok = 0;
    glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
      char log[1024];
      glGetShaderInfoLog(s, sizeof log, NULL, log);
      fprintf(stderr, "shader compile failed: %s\n", log);
      return 0;
    }
    glAttachShader(p, s);
    glDeleteShader(s);
  }
  for (int i = 0; i < n_attribs; ++i) glBindAttribLocation(p, (GLuint)i, attribs[i]);
  glLinkProgram(p);
  GLint ok = 0;
  glGetProgramiv(p, GL_LINK_STATUS, &ok);
  if (!ok) {
    char log[1024];
    glGetProgramInfoLog(p, sizeof log, NULL, log);
    fprintf(stderr, "program link failed: %s\n", log);
    return 0;
  }
  return p;
#endif
}

#endif

#ifdef WMMT_NATIVE_VK
/* Catalog identity uses the exact shared shader/attribute bytes below. Native
 * programs have immutable reflection and NO legacy uniform shadow. */
static GLuint native_program_create(const char *vs, const char *fs, const char **attribs, int n) {
  GLuint id = cinder_vk_program_create(vs, fs, attribs, n);
  if (!cinder_vk_program_ready(id)) {
    if (id) cinder_vk_program_destroy(id);
    return 0;
  }
  return id;
}
static void native_program_release(GLuint *id) {
  if (*id) cinder_vk_program_destroy(*id);
  *id = 0;
}
static void native_render_programs_release(void) {
  for (int i = 0; i < 2; ++i) {
    native_program_release(&progs[i].id);
    native_program_release(&gloss_progs[i].id);
  }
  for (int i = 0; i < 3; ++i) native_program_release(&blur_progs[i]);
  native_program_release(&shadow_prog);
  for (int i = 0; i < 2 * WPK_LIT_PROGS; ++i) {
    GLuint id = lit_progs[i].id;
    for (int j = i + 1; j < 2 * WPK_LIT_PROGS; ++j)
      if (lit_progs[j].id == id) lit_progs[j].id = 0;
    native_program_release(&lit_progs[i].id);
  }
}
#endif

static int prog_init(scene_prog *p, const char *fs) {
  const char *attribs[] = { "aPos", "aUV", "aColor" };
#ifdef WMMT_NATIVE_VK
  memset(p, 0, sizeof *p);
  p->id = native_program_create(VS, fs, attribs, 3);
#else
  p->id = gl_compile_program(VS, fs, attribs, 3);
#endif
  if (!p->id) return -1;
#ifndef WMMT_NATIVE_VK
  p->mvp = glGetUniformLocation(p->id, "uMVP");
  p->eye = glGetUniformLocation(p->id, "uEye");
  p->fog = glGetUniformLocation(p->id, "uFog");
  p->fog_color = glGetUniformLocation(p->id, "uFogColor");
  p->tex = glGetUniformLocation(p->id, "uTex");
  p->uv_off = glGetUniformLocation(p->id, "uUVOff");
  p->grade = glGetUniformLocation(p->id, "uGrade");
  p->wet = glGetUniformLocation(p->id, "uWet");
  p->horizon = glGetUniformLocation(p->id, "uHorizon");
  glUseProgram(p->id);
  glUniform1i(glGetUniformLocation(p->id, "uFrame"), FRAME_UNIT);
  if (p->wet >= 0) glUniform1f(p->wet, 0.0f);
#endif
  return 0;
}

static int lit_init(lit_prog *p, int prog, int cutout) {
  char head[96], vs[8192], fs[8192];
  snprintf(head, sizeof head, "#define PROG %d\n#define CUTOUT %d\n#define FRAME_ENV %d\n", prog, cutout,
           frame_env && prog == 1);
  snprintf(vs, sizeof vs, "%s%s", head, VS_LIT);
  snprintf(fs, sizeof fs, "%s%s", head, FS_LIT);
  const char *attribs[] = { "aPos", "aUV", "aColor", "aNormal" };
#ifdef WMMT_NATIVE_VK
  memset(p, 0, sizeof *p);
  p->id = native_program_create(vs, fs, attribs, 4);
#else
  p->id = gl_compile_program(vs, fs, attribs, 4);
#endif
  if (!p->id) return -1;
#ifndef WMMT_NATIVE_VK
  GLint *loc[] = { &p->mvp, &p->mv, &p->eye, &p->l0, &p->l1, &p->d0, &p->d1, &p->amb, &p->power, &p->fog, &p->fog_color, &p->over, &p->over_dir };
  const char *names[] = { "uMVP", "uMV", "uEye", "uL0", "uL1", "uD0", "uD1", "uAmb", "uPower", "uFog", "uFogColor", "uOver", "uOverDir" };
  for (int i = 0; i < 13; ++i) *loc[i] = glGetUniformLocation(p->id, names[i]);
  glUseProgram(p->id);
  glUniform1i(glGetUniformLocation(p->id, "uTex"), 0);
  glUniform1i(glGetUniformLocation(p->id, "uEnv"), 1);
  glUniform1i(glGetUniformLocation(p->id, "uSpec"), 2);
  glUniform1i(glGetUniformLocation(p->id, "uOverTex"), OVER_UNIT);
  glUniform1i(glGetUniformLocation(p->id, "uAO"), AO_UNIT);
  glUniform1i(glGetUniformLocation(p->id, "uFrame"), FRAME_UNIT);
  p->frame_k = glGetUniformLocation(p->id, "uFrameK");
  glUniform2f(p->over, 0, 1);
  glUniform2f(p->over_dir, sinf(OVER_PITCH), cosf(OVER_PITCH));
#endif
  return 0;
}

static int gloss_init(scene_prog *p, int cutout) {
  char fs[2048];
  snprintf(fs, sizeof fs, "#define CUTOUT %d\n%s", cutout, FS_GLOSS);
  const char *attribs[] = { "aPos", "aUV", "aColor", "aNormal" };
#ifdef WMMT_NATIVE_VK
  memset(p, 0, sizeof *p);
  p->id = native_program_create(VS_GLOSS, fs, attribs, 4);
#else
  p->id = gl_compile_program(VS_GLOSS, fs, attribs, 4);
#endif
  if (!p->id) return -1;
#ifndef WMMT_NATIVE_VK
  p->mvp = glGetUniformLocation(p->id, "uMVP");
  p->eye = glGetUniformLocation(p->id, "uEye");
  p->fog = glGetUniformLocation(p->id, "uFog");
  p->fog_color = glGetUniformLocation(p->id, "uFogColor");
  p->tex = glGetUniformLocation(p->id, "uTex");
  p->uv_off = glGetUniformLocation(p->id, "uUVOff");
  p->grade = glGetUniformLocation(p->id, "uGrade");
  p->wet = p->horizon = -1;
  glUseProgram(p->id);
  glUniform1i(p->tex, 0);
  glUniform1i(glGetUniformLocation(p->id, "uGloss"), 1);
  glUniform1i(glGetUniformLocation(p->id, "uCube"), 2);
#endif
  return 0;
}

int render_init(void) {
  /* render_init starts a renderer context; stale IDs may belong to a lost one.
   * For same-context reinitialization, release tail resources before this call. */
  render_tail_context_lost();
  render_tire_smoke_context_lost();
#ifdef WMMT_NATIVE_VK
  /* As with tail context loss, old-context names must not be destroyed in the
   * replacement context. Failure cleanup below owns only this attempt's IDs. */
  memset(progs, 0, sizeof progs);
  memset(gloss_progs, 0, sizeof gloss_progs);
  memset(lit_progs, 0, sizeof lit_progs);
  memset(blur_progs, 0, 3 * sizeof blur_progs[0]);
  shadow_prog = 0;
#endif
#ifdef WMMT_NATIVE_VK
  if (prog_init(&progs[0], FS) || prog_init(&progs[1], FS_CUTOUT)) goto native_bad;
#else
  if (prog_init(&progs[0], FS) || prog_init(&progs[1], FS_CUTOUT)) return -1;
#endif
#ifdef WMMT_NATIVE_VK
  if (gloss_init(&gloss_progs[0], 0) || gloss_init(&gloss_progs[1], 1)) goto native_bad;
#else
  if (gloss_init(&gloss_progs[0], 0) || gloss_init(&gloss_progs[1], 1)) return -1;
#endif
  for (int k = 0; k < 3; ++k) {
    char vs[2048], fs[4096];
    snprintf(vs, sizeof vs, "#define BLUR_TAPS %d\n#define SHARPEN %d\n%s", k == 1 ? 8 : 1, k == 2, VS_BLUR);
    snprintf(fs, sizeof fs, "#define BLUR_TAPS %d\n#define SHARPEN %d\n#define HQ 0\n%s", k == 1 ? 8 : 1, k == 2, FS_BLUR);
    const char *attribs[] = { "aPos", "aUV", "aAlpha" };
#ifdef WMMT_NATIVE_VK
    blur_progs[k] = native_program_create(vs, fs, attribs, 3);
#else
    blur_progs[k] = gl_compile_program(vs, fs, attribs, 3);
#endif
#ifdef WMMT_NATIVE_VK
    if (!blur_progs[k]) goto native_bad;
#else
    if (!blur_progs[k]) return -1;
#endif
#ifndef WMMT_NATIVE_VK
    glUseProgram(blur_progs[k]);
    glUniform1i(glGetUniformLocation(blur_progs[k], "uTex"), 0);
#endif
  }
#ifndef WMMT_NATIVE_VK
  sharp_texel[0] = glGetUniformLocation(blur_progs[2], "uTexel");
  sharp_amount[0] = glGetUniformLocation(blur_progs[2], "uSharp");
#endif
  const char *shadow_attr[] = { "aPos" };
#ifdef WMMT_NATIVE_VK
  shadow_prog = native_program_create(VS_SHADOW, FS_SHADOW, shadow_attr, 1);
#else
  shadow_prog = gl_compile_program(VS_SHADOW, FS_SHADOW, shadow_attr, 1);
#endif
#ifdef WMMT_NATIVE_VK
  if (!shadow_prog) goto native_bad;
#else
  if (!shadow_prog) return -1;
#endif
#ifndef WMMT_NATIVE_VK
  shadow_mvp = glGetUniformLocation(shadow_prog, "uMVP");
  shadow_color = glGetUniformLocation(shadow_prog, "uColor");
#endif
  for (int k = 0; k < WPK_LIT_PROGS; ++k)
    for (int c = 0; c < 2; ++c) {
      if (k == WPK_LIT_CAR && c) {
        lit_progs[2 * k + 1] = lit_progs[2 * k];
        continue;
      }
#ifdef WMMT_NATIVE_VK
      if (lit_init(&lit_progs[2 * k + c], k, c)) goto native_bad;
#else
      if (lit_init(&lit_progs[2 * k + c], k, c)) return -1;
#endif
    }
#if defined(WMMT_EGL) && !defined(WMMT_NATIVE_VK)
  wmmt_glGenVertexArraysOES = (PFNGLGENVERTEXARRAYSOESPROC)eglGetProcAddress("glGenVertexArraysOES");
  wmmt_glBindVertexArrayOES = (PFNGLBINDVERTEXARRAYOESPROC)eglGetProcAddress("glBindVertexArrayOES");
  wmmt_glDeleteVertexArraysOES = (PFNGLDELETEVERTEXARRAYSOESPROC)eglGetProcAddress("glDeleteVertexArraysOES");
  if (!wmmt_glGenVertexArraysOES || !wmmt_glBindVertexArrayOES || !wmmt_glDeleteVertexArraysOES) return -1;
#endif
  static const uint8_t px[4] = { 255, 255, 255, 255 };
#ifdef WMMT_NATIVE_VK
  const cinder_vk_sampler white_sampler = { .use_state=1,.min_filter=VK_FILTER_NEAREST,.mag_filter=VK_FILTER_NEAREST,
    .mipmap_mode=VK_SAMPLER_MIPMAP_MODE_NEAREST,.address_u=VK_SAMPLER_ADDRESS_MODE_REPEAT,
    .address_v=VK_SAMPLER_ADDRESS_MODE_REPEAT,.anisotropy=1 };
  white_tex=cinder_vk_texture_rgba8(1,1,px,sizeof px,&white_sampler);
  if (!white_tex) goto native_bad;
#else
  glGenTextures(1, &white_tex);
  glBindTexture(GL_TEXTURE_2D, white_tex);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
#endif
  frame_history_valid = 0;
  frame_sampler_off();
  return 0;
#ifdef WMMT_NATIVE_VK
native_bad:
  native_render_programs_release();
  return -1;
#endif
}

static int is_pot(int v) { return v > 0 && (v & (v - 1)) == 0; }

/* all n bytes at off, 0 when read */
static int read_at(int fd, void *dst, size_t n, off_t off) {
  char *d = dst;
  while (n) {
    ssize_t r = pread(fd, d, n, off);
    if (r <= 0) return -1;
    d += r;
    n -= (size_t)r;
    off += r;
  }
  return 0;
}

/* the scene's buffer for what wpk_upload reads, n bytes at least */
static void *scratch(wpk_scene *s, size_t n) {
  if (n > s->scratch_size) {
    free(s->scratch);
    s->scratch = malloc(n);
    s->scratch_size = s->scratch ? n : 0;
  }
  return s->scratch;
}

static void file_close(wpk_scene *s) {
  if (s->fd >= 0) close(s->fd);
  s->fd = -1;
  free(s->scratch);
  s->scratch = NULL;
  s->scratch_size = 0;
}

/* pack.py's gloss section, if the file has one (its last 8 bytes: the offset, "GLS1"): the
 * cubes' face records kept for wpk_upload, the gloss batches' textures, cubes and normals */
static int gloss_open(wpk_scene *s) {
  struct stat st;
  char foot[8];
  if (fstat(s->fd, &st) != 0 || st.st_size < 8 || read_at(s->fd, foot, 8, st.st_size - 8) != 0 ||
      memcmp(foot + 4, "GLS1", 4) != 0)
    return 0;
  uint32_t off, n[2];
  memcpy(&off, foot, 4);
  if (read_at(s->fd, n, sizeof n, off) != 0) return -1;
#ifdef WMMT_NATIVE_VK
  /* These legacy table expressions use 32-bit file offsets. Validate before
   * their multiplication/addition, allocation or any face-record indexing. */
  uint64_t cube_bytes=(uint64_t)n[0]*72u,gloss_bytes=(uint64_t)n[1]*12u;
  uint64_t table_end=(uint64_t)off+8u+cube_bytes+gloss_bytes;
  if (cube_bytes>UINT32_MAX || gloss_bytes>UINT32_MAX || table_end>UINT32_MAX ||
      table_end>(uint64_t)st.st_size-8u) return -1;
#endif
  s->n_cube = n[0];
  s->cubes = calloc(n[0] ? n[0] : 1, sizeof(uint32_t));
  s->cube_warm = calloc(n[0] ? n[0] : 1, 1);
  s->cube_tbl = malloc((n[0] ? n[0] : 1) * 72u);
  s->gloss_noff = calloc(s->n_batch ? s->n_batch : 1, sizeof(uint32_t));
  uint8_t *g = malloc((n[1] ? n[1] : 1) * 12u);
  if (!s->cubes || !s->cube_warm || !s->cube_tbl || !s->gloss_noff || !g ||
      read_at(s->fd, s->cube_tbl, n[0] * 72u, off + 8) != 0 || read_at(s->fd, g, n[1] * 12u, off + 8 + n[0] * 72u) != 0) {
    free(g);
    return -1;
  }
  for (uint32_t i = 0; i < n[1]; ++i) {
    uint32_t b, noff;
    uint16_t t[2];
    memcpy(&b, g + 12 * i, 4);
    memcpy(t, g + 12 * i + 4, 4);
    memcpy(&noff, g + 12 * i + 8, 4);
    if (b >= s->n_batch || t[0] >= s->n_tex || t[1] >= n[0]) continue;
    s->batches[b].gloss = t[0];
    s->batches[b].cube = t[1];
    s->gloss_noff[b] = noff;
  }
  free(g);
  return 0;
}

#ifdef WMMT_NATIVE_VK
static size_t native_wpk_cube_upload(wpk_scene *s, uint32_t i);
static size_t native_wpk_ao_upload(wpk_scene *s);
#endif

/* cube i's six faces from the file to GL; its bytes, 0 if unreadable */
static size_t cube_upload(wpk_scene *s, uint32_t i) {
#ifdef WMMT_NATIVE_VK
  return native_wpk_cube_upload(s, i);
#else
  static const GLenum types[3] = { GL_UNSIGNED_SHORT_5_6_5, GL_UNSIGNED_SHORT_4_4_4_4,
                                   GL_UNSIGNED_SHORT_5_5_5_1 };
  size_t done = 0;
  glGenTextures(1, &s->cubes[i]);
  glBindTexture(GL_TEXTURE_CUBE_MAP, s->cubes[i]);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 2);
  for (int f = 0; f < 6; ++f) {
    const uint8_t *r = (const uint8_t *)s->cube_tbl + 72u * i + 12u * (uint32_t)f;
    uint16_t size, fmt;
    uint32_t off, bytes;
    memcpy(&size, r, 2);
    memcpy(&fmt, r + 2, 2);
    memcpy(&off, r + 4, 4);
    memcpy(&bytes, r + 8, 4);
    void *px = scratch(s, bytes);
    if (!px || fmt > 2 || bytes < (size_t)size * size * 2 || read_at(s->fd, px, bytes, off) != 0) {
      fprintf(stderr, "%s: cube %u unreadable\n", s->path, i);
      glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
      return 0;
    }
    GLenum gl = fmt == 0 ? GL_RGB : GL_RGBA;
    glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + (GLenum)f, 0, (GLint)gl, size, size, 0, gl, types[fmt], px);
    done += bytes;
  }
  glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
  return done;
#endif
}

/* a car's ambient occlusion maps (bake_ao.c: "WAO1", n, then {name[48], u16 w, h, u8 [w h]}),
 * <pack>.ao beside <pack>.wpk, read whole for wpk_upload */
static void ao_open(wpk_scene *s) {
  size_t n = strlen(s->path);
  if (n < 4 || n > 1000) return;
  char path[1024];
  memcpy(path, s->path, n - 4);
  memcpy(path + n - 4, ".ao", 4);
  int fd = open(path, O_RDONLY);
  struct stat st;
  if (fd < 0) return;
  if (fstat(fd, &st) == 0 && st.st_size > 8 && st.st_size < (16 << 20)) {
    s->ao_file = malloc((size_t)st.st_size);
    if (s->ao_file && read_at(fd, s->ao_file, (size_t)st.st_size, 0) == 0 && memcmp(s->ao_file, "WAO1", 4) == 0) {
      s->ao_size = (size_t)st.st_size;
    } else {
      free(s->ao_file);
      s->ao_file = NULL;
    }
  }
  close(fd);
}

/* the maps to GL (luminance, with their mipmaps: the 2 x 2 means), by the texture each darkens */
static size_t ao_upload(wpk_scene *s) {
#ifdef WMMT_NATIVE_VK
  return native_wpk_ao_upload(s);
#else
  const uint8_t *f = s->ao_file, *end = f + s->ao_size;
  const wpk_tex *tex = s->tex_tbl;
  size_t done = 0;
  uint32_t n;
  memcpy(&n, f + 4, 4);
  s->ao_tex = calloc(s->n_tex ? s->n_tex : 1, sizeof(uint32_t));
  s->n_ao = s->ao_tex ? s->n_tex : 0;
  f += 8;
  for (uint32_t m = 0; m < n && s->ao_tex && f + 52 <= end; ++m) {
    uint16_t wh[2];
    memcpy(wh, f + 48, 4);
    int w = wh[0], h = wh[1];
    const uint8_t *px = f + 52;
    if (!is_pot(w) || !is_pot(h) || px + (size_t)w * h > end) break;
    int t = -1;
    for (uint32_t i = 0; i < s->n_tex && t < 0; ++i)
      if (memcmp(tex[i].name, f, sizeof tex[i].name) == 0) t = (int)i;
    f = px + (size_t)w * h;
    if (t < 0 || s->ao_tex[t]) continue;
    uint8_t *mip = malloc((size_t)w * h);
    if (!mip) break;
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glGenTextures(1, &s->ao_tex[t]);
    glBindTexture(GL_TEXTURE_2D, s->ao_tex[t]);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_LUMINANCE, w, h, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, px);
    const uint8_t *src = px;
    for (int lw = w, lh = h, level = 1; lw > 1 || lh > 1; ++level) {
      int dw = lw > 1 ? lw / 2 : 1, dh = lh > 1 ? lh / 2 : 1, sx = lw > 1, sy = lh > 1;
      uint8_t *dst = mip + (src == px ? 0 : (size_t)(src - mip) + (size_t)lw * lh);
      for (int y = 0; y < dh; ++y)
        for (int x = 0; x < dw; ++x) {
          const uint8_t *q = src + (size_t)(y << sy) * (size_t)lw + (size_t)(x << sx);
          dst[(size_t)y * dw + x] = (uint8_t)((q[0] + q[sx] + q[(size_t)lw * sy] + q[(size_t)lw * sy + sx] + 2) / 4);
        }
      glTexImage2D(GL_TEXTURE_2D, level, GL_LUMINANCE, dw, dh, 0, GL_LUMINANCE, GL_UNSIGNED_BYTE, dst);
      src = dst, lw = dw, lh = dh;
    }
    free(mip);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    done += (size_t)w * h;
  }
  glPixelStorei(GL_UNPACK_ALIGNMENT, 2);
  free(s->ao_file);
  s->ao_file = NULL;
  return done + 1;
#endif
}

/* The file is read a piece at a time (pread): its tables here, each texture and buffer as
 * wpk_upload hands it to GL. A course is near 200 MB, more than the app's address space
 * has room for in one piece once the menus are up (the night map failed to map, and the
 * time zone select went back to the morning). */
/* a road's texture by its name (the asphalt and its painted lines, render_hq's WET):
 * "asph", "line" or "roadtile" in it, any case */
static int road_texture(const char *name) {
  static const char *const words[] = { "asph", "line", "roadtile" };
  for (const char *n = name; *n; ++n)
    for (int w = 0; w < 3; ++w) {
      const char *a = n, *b = words[w];
      while (*b && (*a | 0x20) == *b) a++, b++;
      if (!*b) return 1;
    }
  return 0;
}

int wpk_open(wpk_scene *s, const char *path) {
  memset(s, 0, sizeof *s);
  s->fd = -1;
  int fd = open(path, O_RDONLY);
  if (fd < 0) return -1;
  wpk_header h;
  /* WPK1 has no chunk groups (everything is ground); WPK2 adds one per chunk; WPK3 normals
   * and materials (lit) */
  int v3 = 0, v2 = 0;
  if (read_at(fd, &h, sizeof h, 0) == 0) {
    v3 = memcmp(h.magic, "WPK3", 4) == 0;
    v2 = v3 || memcmp(h.magic, "WPK2", 4) == 0;
  }
  if (!v2 && (read_at(fd, &h, sizeof h, 0) != 0 || memcmp(h.magic, "WPK1", 4) != 0)) {
    close(fd);
    return -1;
  }
  s->fd = fd;
  s->path = strdup(path);
  s->lit = v3;
  s->stride = v3 ? 32 : 24;
  s->rec_size = v3 ? 28 : 20;
  s->n_tex = h.n_tex;
  s->n_chunk = h.n_chunk;
  s->n_batch = h.n_batch;
  size_t chunk_rec = v2 ? 36 : 32;
  if ((uint64_t)h.n_tex * sizeof(wpk_tex) > SIZE_MAX ||
      (uint64_t)h.n_batch * s->rec_size > SIZE_MAX ||
      (uint64_t)h.n_chunk * chunk_rec > SIZE_MAX) {
    fprintf(stderr, "WPK: table size exceeds host limits\n");
    wpk_free(s);
    return -1;
  }
  s->textures = calloc(h.n_tex ? h.n_tex : 1, sizeof(uint32_t));
  s->loaded = calloc(h.n_tex ? h.n_tex : 1, sizeof(uint32_t));
  s->chunks = calloc(h.n_chunk ? h.n_chunk : 1, sizeof(wpk_chunk));
  s->batches = calloc(h.n_batch ? h.n_batch : 1, sizeof(wpk_batch));
  s->warm = calloc(h.n_chunk ? h.n_chunk : 1, 1);
  s->warm_chunk = -1;
  s->tex_alpha = calloc(h.n_tex ? h.n_tex : 1, 1);
  s->tex_wet = calloc(h.n_tex ? h.n_tex : 1, 1);
  s->tex_warm = calloc(h.n_tex ? h.n_tex : 1, 1);
  s->is_paint = calloc(h.n_tex ? h.n_tex : 1, 1);
  s->paints = calloc(h.n_tex ? h.n_tex : 1, sizeof(wpk_paint_swap));
  s->tex_tbl = malloc((h.n_tex ? h.n_tex : 1) * sizeof(wpk_tex));
  s->batch_tbl = malloc((h.n_batch ? h.n_batch : 1) * (size_t)s->rec_size);
  char *chunk_tbl = malloc((h.n_chunk ? h.n_chunk : 1) * chunk_rec);
  if (!s->path || !s->textures || !s->loaded || !s->chunks || !s->batches || !s->warm ||
      !s->tex_alpha || !s->tex_wet || !s->tex_warm || !s->is_paint || !s->paints ||
      !s->tex_tbl || !s->batch_tbl || !chunk_tbl || read_at(fd, s->tex_tbl, h.n_tex * sizeof(wpk_tex), h.tex_off) ||
      read_at(fd, s->batch_tbl, h.n_batch * (size_t)s->rec_size, h.batch_off) ||
      read_at(fd, chunk_tbl, h.n_chunk * chunk_rec, h.chunk_off)) {
    free(chunk_tbl);
    wpk_free(s);
    return -1;
  }
  for (uint32_t i = 0; i < h.n_chunk; ++i) {
    const char *r = chunk_tbl + i * chunk_rec;
    memcpy(&s->chunks[i], r, 32);
    s->chunks[i].group = 0;
    if (v2) memcpy(&s->chunks[i].group, r + 32, 4);
  }
  free(chunk_tbl);
  for (uint32_t i = 0; i < h.n_batch; ++i) s->batches[i].gloss = s->batches[i].cube = 0xFFFF;
  if (!v3 && gloss_open(s) != 0) {
    wpk_free(s);
    return -1;
  }
  /* the buffer pools: the batches as they come, POOL_VERTS vertices a pool at most, the gloss
   * ones (with their normals' buffer) in pools of their own */
  s->pools = calloc(h.n_batch ? h.n_batch : 1, sizeof(wpk_pool));
  if (!s->pools) {
    wpk_free(s);
    return -1;
  }
  struct stat mesh_stat;
  if (fstat(fd, &mesh_stat) != 0 || mesh_stat.st_size < 0) {
    fprintf(stderr, "WPK: cannot determine mesh file size\n");
    wpk_free(s);
    return -1;
  }
  uint32_t verts = 0;
  int pool_gloss = 0;
  for (uint32_t i = 0; i < h.n_batch; ++i) {
    const wpk_batch_rec *r = (const wpk_batch_rec *)((const char *)s->batch_tbl + (size_t)i * s->rec_size);
    int gloss = s->gloss_noff && s->gloss_noff[i];
    if (!wpk_range_valid((uint64_t)mesh_stat.st_size, r->vtx_off, (uint64_t)r->vtx_count * s->stride) ||
        !wpk_range_valid((uint64_t)mesh_stat.st_size, r->idx_off, (uint64_t)r->idx_count * 2u)) {
      fprintf(stderr, "WPK: batch %u has invalid file ranges\n", i);
      wpk_free(s);
      return -1;
    }
    if (r->vtx_count > POOL_VERTS) {
      fprintf(stderr, "WPK: batch %u exceeds vertex limit\n", i);
      wpk_free(s);
      return -1;
    }
    if (!s->n_pools || r->vtx_count > POOL_VERTS - verts || gloss != pool_gloss) {
      s->n_pools++;
      verts = 0;
      pool_gloss = gloss;
    }
    wpk_pool *pl = &s->pools[s->n_pools - 1];
    if (!wpk_index_buffer_valid(pl->ibytes, r->idx_count)) {
      fprintf(stderr, "WPK: batch %u exceeds index buffer limit\n", i);
      wpk_free(s);
      return -1;
    }
    s->batches[i].pool = s->n_pools - 1;
    pl->vbytes += r->vtx_count * s->stride;
    pl->ibytes += r->idx_count * 2u;
    if (gloss) pl->nbytes += r->vtx_count * 8u;
    verts += r->vtx_count;
  }

  /* paint textures: "p<k>:<name of the texture they replace>" */
  const wpk_tex *tex = s->tex_tbl;
  for (uint32_t i = 0; s->tex_wet && !v3 && i < h.n_tex; ++i) s->tex_wet[i] = (unsigned char)road_texture(tex[i].name);
  for (uint32_t i = 0; i < h.n_tex; ++i) {
    const char *n = tex[i].name;
    if (n[0] != 'p' || n[1] < '0' || n[1] > '9') continue;
    int k = 0;
    const char *c = n + 1;
    while (*c >= '0' && *c <= '9') k = k * 10 + (*c++ - '0');
    if (*c++ != ':') continue;
    for (uint32_t j = 0; j < h.n_tex; ++j) {
      const char *a = tex[j].name, *b = c;
      while (*a && *a == *b) a++, b++;
      if (*a == *b && j != i) {
        s->paints[s->n_paints++] = (wpk_paint_swap){ (uint16_t)k, (uint16_t)j, (uint16_t)i };
        s->is_paint[i] = 1;
        break;
      }
    }
  }
  /* formats 1 and 2 (4444, 5551): pack.py encode16 keeps alpha only where some is see-through */
  for (uint32_t i = 0; i < h.n_tex; ++i)
    s->tex_alpha[i] = tex[i].fmt >= WPK_ASTC ? (tex[i].fmt - WPK_ASTC) & 1 : tex[i].fmt != 0;
  for (uint32_t i = 0; i < s->n_paints; ++i) s->tex_alpha[s->paints[i].dst] |= s->tex_alpha[s->paints[i].src];
  if (v3) ao_open(s);
  return 0;
}


/* The 16-bit formats' channels (pack.py encode16): bits from the top, red first. */
static const uint8_t TEX_BITS[3][4] = { { 5, 6, 5, 0 }, { 4, 4, 4, 4 }, { 5, 5, 5, 1 } };

/* src (w x h, 16-bit format fmt) halved into dst, each texel the mean of its 2 x 2 (or
 * 2 x 1 where a side is already 1: those two taken twice) */
static void mip_down(const uint16_t *src, int w, int h, uint16_t *dst, int fmt) {
  const uint8_t *bits = TEX_BITS[fmt];
  int dw = w > 1 ? w / 2 : 1, dh = h > 1 ? h / 2 : 1;
  int sx = w > 1, sy = h > 1;
  for (int y = 0; y < dh; ++y)
    for (int x = 0; x < dw; ++x) {
      const uint16_t *p = src + (size_t)(y << sy) * (size_t)w + (size_t)(x << sx);
      uint16_t q[4] = { p[0], p[sx], p[(size_t)w * (size_t)sy], p[(size_t)w * (size_t)sy + (size_t)sx] };
      uint16_t out = 0;
      int shift = 16;
      for (int c = 0; c < 4 && bits[c]; ++c) {
        shift -= bits[c];
        unsigned mask = (1u << bits[c]) - 1u, sum = 0;
        for (int k = 0; k < 4; ++k) sum += (q[k] >> shift) & mask;
        out |= (uint16_t)(((sum + 2u) / 4u) << shift); /* rounded: 1-bit alpha needs 2 of 4 */
      }
      dst[(size_t)y * (size_t)dw + (size_t)x] = out;
    }
}

/* wpk_tex_half: power-of-two textures at least TEX_HALF_MIN on both sides go up from their
 * second level (a quarter of the memory) */
static int tex_half;
#define TEX_HALF_MIN 64
void wpk_tex_half(int on) { tex_half = on != 0; }

/* render_aniso: the ground's textures at a glancing angle. The iPad's GL has neither
 * trilinear worth its bandwidth nor the anisotropic extension; an Adreno 540 has both, and
 * the road a long way ahead is where a 4:3 arcade texture shows its mip seams most. The
 * value is the degree asked for (1: off, as the iPad has it). */
static float aniso = 1;
#ifndef GL_TEXTURE_MAX_ANISOTROPY_EXT
#define GL_TEXTURE_MAX_ANISOTROPY_EXT 0x84FE
#define GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT 0x84FF
#endif
void render_aniso(float degree) {
  if (degree <= 1) {
    aniso = 1;
    return;
  }
#ifdef WMMT_NATIVE_VK
  float most=cinder_vk_anisotropy_limit();
  if (most <= 1) {
#else
  GLfloat most = 1;
  glGetFloatv(GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT, &most);
  if (glGetError() != GL_NO_ERROR || most <= 1) {
#endif /* no extension: trilinear alone */
    aniso = 1.5f;
    return;
  }
  aniso = degree < (float)most ? degree : (float)most;
}

/* the minifying filter for a texture with mipmaps, and the degree with it */
#ifndef WMMT_NATIVE_VK
static GLint mip_filter(void) { return aniso > 1 ? GL_LINEAR_MIPMAP_LINEAR : GL_LINEAR_MIPMAP_NEAREST; }
static void tex_aniso(void) {
  if (aniso > 1.5f) glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAX_ANISOTROPY_EXT, aniso);
}
#endif

/* texture i from the file to GL; its size, or 0 if it could not be read. A power-of-two
 * texture gets its mipmaps from mip_down, here on the loading thread: glGenerateMipmap left
 * them to the driver, which made them on the texture's first draw (about 20 ms a batch on
 * the iPad 3, the race's and the menus' stutter). */
/* ASTC textures (a pack made for Android, tools/stage: wpk fmt WPK_ASTC + 2 * block + alpha,
 * block 0 4x4, 1 6x6, 2 8x8): each level's blocks of 16 bytes, from the base down to 1 x 1
 * (the base alone for a texture not a power of two), handed to GL as they are */
#ifdef __ANDROID__
/* Both approved legacy inventories still contain these DEFAULT-order textures.
 * The signed original conversion does the component swap before DDS decode.
 * For these exact packed payloads, swapping the packed channels yields exactly
 * the same bytes, leaving the old resource on disk and alpha/green untouched. */
static void wpk_restore_course_arrow_order(const wpk_tex *t, uint16_t *pixels) {
  static const struct {
    const char *name;
    uint16_t w, h, fmt;
    uint8_t digest[32];
  } legacy[] = {
    { "course_arrow_stepanim_01.tga", 256, 256, 1,
      { 0x5c, 0x85, 0x68, 0xd3, 0x64, 0x53, 0x41, 0x62, 0xee, 0x60, 0xae, 0xe1, 0x31, 0x7f, 0xc3, 0xa2, 0x6f, 0x7b, 0x85, 0xd9, 0xd5, 0x55, 0xd6, 0xbb, 0xe5, 0xb3, 0x71, 0x07, 0x02, 0xdc, 0xa8, 0x14 } },
    { "coursearrow.tga", 256, 256, 1,
      { 0x5a, 0xf2, 0x24, 0x61, 0x3a, 0xfa, 0xeb, 0x04, 0x2d, 0x92, 0xb8, 0xe2, 0x02, 0x9b, 0x6c, 0x63, 0x60, 0xeb, 0x30, 0x4d, 0x88, 0x15, 0xdd, 0x94, 0xcb, 0x8c, 0x49, 0x00, 0x7d, 0x64, 0x4c, 0xa0 } },
    { "coursearrow02.dds", 256, 128, 0,
      { 0xbe, 0x45, 0x7a, 0x2a, 0x38, 0x24, 0x1a, 0x74, 0xe5, 0x42, 0xcc, 0x84, 0xb3, 0x9b, 0x56, 0xf3, 0x76, 0x56, 0xd0, 0xc9, 0x55, 0x17, 0xaa, 0x9a, 0xed, 0xc7, 0xb5, 0x8c, 0x48, 0x59, 0xf4, 0xea } },
  };
  for (unsigned i = 0; i < sizeof legacy / sizeof legacy[0]; ++i) {
    if (t->w != legacy[i].w || t->h != legacy[i].h || t->fmt != legacy[i].fmt ||
        t->size != (uint32_t)t->w * t->h * 2 || strncmp(t->name, legacy[i].name, sizeof t->name))
      continue;
    uint8_t digest[32];
    ghost_catalog_sha256_bytes(pixels, t->size, digest);
    if (memcmp(digest, legacy[i].digest, sizeof digest)) return;
    unsigned r = t->fmt == 0 ? 0xf800 : 0xf000;
    unsigned b = t->fmt == 0 ? 0x001f : 0x00f0;
    unsigned shift = t->fmt == 0 ? 11 : 8;
    for (uint32_t j = 0; j < t->size / 2; ++j) {
      unsigned x = pixels[j];
      pixels[j] = (uint16_t)((x & ~(r | b)) | ((x & r) >> shift) | ((x & b) << shift));
    }
    return;
  }
}
#endif

static int wpk_read_packed_texture(wpk_scene *s, const wpk_tex *t, uint16_t *pixels) {
  if (read_at(s->fd, pixels, t->size, t->off) != 0) return -1;
#ifdef __ANDROID__
  if (s->course_arrows) wpk_restore_course_arrow_order(t, pixels);
#endif
  return 0;
}

#ifdef WMMT_NATIVE_VK
#include "render_native_textures.inc"
#endif

#ifndef WMMT_NATIVE_VK
static const struct { GLenum gl; int b; } ASTC[3] = { { 0x93B0, 4 }, { 0x93B4, 6 }, { 0x93B7, 8 } };
#endif
static size_t astc_upload(wpk_scene *s, uint32_t i) {
#ifdef WMMT_NATIVE_VK
  return native_wpk_astc_upload(s, i);
#else
  const wpk_tex *t = (const wpk_tex *)s->tex_tbl + i;
  int pot = is_pot(t->w) && is_pot(t->h), k = (int)(t->fmt - WPK_ASTC) / 2, b = ASTC[k].b;
  unsigned char *px = scratch(s, t->size);
  if (!px || read_at(s->fd, px, t->size, t->off) != 0) {
    fprintf(stderr, "%s: texture %u unreadable\n", s->path, i);
    return 0;
  }
  glGenTextures(1, &s->loaded[i]);
  glBindTexture(GL_TEXTURE_2D, s->loaded[i]);
  size_t at = 0;
  for (int w = t->w, h = t->h, level = 0;; ++level) {
    size_t n = (size_t)((w + b - 1) / b) * (size_t)((h + b - 1) / b) * 16;
    if (at + n > t->size) {
      fprintf(stderr, "%s: texture %u: ASTC levels short\n", s->path, i);
      break;
    }
    glCompressedTexImage2D(GL_TEXTURE_2D, level, ASTC[k].gl, w, h, 0, (GLsizei)n, px + at);
    at += n;
    if (!pot || (w == 1 && h == 1)) break;
    w = w > 1 ? w / 2 : 1;
    h = h > 1 ? h / 2 : 1;
  }
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, pot ? mip_filter() : GL_LINEAR);
  if (pot) tex_aniso();
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  GLint wrap = pot ? GL_REPEAT : GL_CLAMP_TO_EDGE;
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, wrap);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, wrap);
  s->textures[i] = s->loaded[i];
  s->tex_warm[i] = 0;
  return t->size;
#endif
}

static size_t tex_upload(wpk_scene *s, uint32_t i) {
#ifdef WMMT_NATIVE_VK
  return native_wpk_tex_upload(s, i);
#else
  static const GLenum types[3] = { GL_UNSIGNED_SHORT_5_6_5, GL_UNSIGNED_SHORT_4_4_4_4,
                                   GL_UNSIGNED_SHORT_5_5_5_1 };
  const wpk_tex *t = (const wpk_tex *)s->tex_tbl + i;
  if (t->fmt >= WPK_ASTC && t->fmt < WPK_ASTC + 6) return astc_upload(s, i);
  int pot = is_pot(t->w) && is_pot(t->h);
  /* the levels after the base take a third of its size (all but its size, one side 1 wide) */
  uint16_t *px = scratch(s, t->size + (pot ? t->size + 16 : 0));
  if (!px || t->fmt > 2 || t->size < (size_t)t->w * t->h * 2 || wpk_read_packed_texture(s, t, px) != 0) {
    fprintf(stderr, "%s: texture %u unreadable\n", s->path, i);
    return 0;
  }
  GLenum fmt = t->fmt == 0 ? GL_RGB : GL_RGBA;
  glPixelStorei(GL_UNPACK_ALIGNMENT, 2);
  glGenTextures(1, &s->loaded[i]);
  glBindTexture(GL_TEXTURE_2D, s->loaded[i]);
  int w0 = t->w, h0 = t->h;
  uint16_t *base = px;
  if (pot && tex_half && w0 >= TEX_HALF_MIN && h0 >= TEX_HALF_MIN) { /* the base: its first mip */
    base = px + (size_t)w0 * h0;
    mip_down(px, w0, h0, base, (int)t->fmt);
    w0 /= 2, h0 /= 2;
  }
  glTexImage2D(GL_TEXTURE_2D, 0, (GLint)fmt, w0, h0, 0, fmt, types[t->fmt], base);
  if (pot) {
    uint16_t *src = base, *dst = base + (size_t)w0 * h0;
    for (int w = w0, h = h0, level = 1; w > 1 || h > 1; ++level) {
      mip_down(src, w, h, dst, (int)t->fmt);
      w = w > 1 ? w / 2 : 1;
      h = h > 1 ? h / 2 : 1;
      glTexImage2D(GL_TEXTURE_2D, level, (GLint)fmt, w, h, 0, fmt, types[t->fmt], dst);
      src = dst;
      dst += (size_t)w * h;
    }
  }
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, pot ? mip_filter() : GL_LINEAR);
  if (pot) tex_aniso();
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  GLint wrap = pot ? GL_REPEAT : GL_CLAMP_TO_EDGE;
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, wrap);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, wrap);
  s->textures[i] = s->loaded[i];
  s->tex_warm[i] = 0;
  return t->size;
#endif
}

int wpk_find_texture(const wpk_scene *s, const char *name) {
  const wpk_tex *t = s->tex_tbl;
  size_t n = strlen(name);
  if (!t || !n) return -1;
  for (uint32_t i = 0; i < s->n_tex; ++i) {
    /* (the patched iOS SDK has no plain strncmp for armv7) */
    size_t k = 0;
    while (k < n && t[i].name[k] == name[k]) k++;
    if (k == n && (t[i].name[n] == '.' || t[i].name[n] == 0)) return (int)i;
  }
  return -1;
}

uint32_t wpk_texture_over(wpk_scene *s, int i, const uint8_t *over, int ow, int oh, const uint8_t *rgb) {
  if (i < 0 || (uint32_t)i >= s->n_tex || !s->path) return 0;
  const wpk_tex *t = (const wpk_tex *)s->tex_tbl + i;
  if (t->fmt != 0 || !is_pot(t->w) || !is_pot(t->h) || t->size < (size_t)t->w * t->h * 2 || ow < 1 || oh < 1) return 0;
  int w = t->w, h = t->h;
  uint16_t *px = malloc((size_t)w * h * 2 * 2 + 64);
  int fd = open(s->path, O_RDONLY);
  int ok = px && fd >= 0 && read_at(fd, px, (size_t)w * h * 2, t->off) == 0;
  if (fd >= 0) close(fd);
  if (!ok) {
    free(px);
    return 0;
  }
  /* nsTextureReplace::TextureReplace's blend: rgb = rgb (1 - a) + vinyl a (the vinyl's
   * premultiplied, or one colour with an alpha plane) */
  for (int y = 0; y < h; ++y) {
    const uint8_t *row = over + (size_t)(y * oh / h) * (size_t)ow * (rgb ? 1 : 4);
    uint16_t *d = px + (size_t)y * w;
    for (int x = 0; x < w; ++x) {
      int ox = x * ow / w;
      unsigned a, r, g, b;
      if (rgb) {
        a = row[ox];
        if (!a) continue;
        r = rgb[0] * a, g = rgb[1] * a, b = rgb[2] * a;
      } else {
        const uint8_t *o = row + 4 * ox;
        a = o[3];
        if (!a) continue;
        r = o[0] * 255u, g = o[1] * 255u, b = o[2] * 255u;
      }
      unsigned p = d[x], k = 255u - a;
      unsigned br = ((p >> 11) & 31u) * 255u / 31u, bg = ((p >> 5) & 63u) * 255u / 63u, bb = (p & 31u) * 255u / 31u;
      br = (br * k + r + 127u) / 255u, bg = (bg * k + g + 127u) / 255u, bb = (bb * k + b + 127u) / 255u;
      if (br > 255u) br = 255u;
      if (bg > 255u) bg = 255u;
      if (bb > 255u) bb = 255u;
      d[x] = (uint16_t)(((br * 31u + 127u) / 255u) << 11 | ((bg * 63u + 127u) / 255u) << 5 | (bb * 31u + 127u) / 255u);
    }
  }
  /* up as tex_upload does it: its mipmaps from mip_down, from the second level under tex_half */
#ifdef WMMT_NATIVE_VK
  uint32_t texture=native_scene_packed_texture(px,(size_t)w*h*4+64,w,h,0,tex_half,1);
  free(px);
  return texture;
#else
  GLuint name = 0;
  glPixelStorei(GL_UNPACK_ALIGNMENT, 2);
  glGenTextures(1, &name);
  glBindTexture(GL_TEXTURE_2D, name);
  uint16_t *base = px;
  if (tex_half && w >= TEX_HALF_MIN && h >= TEX_HALF_MIN) {
    base = px + (size_t)w * h;
    mip_down(px, w, h, base, 0);
    w /= 2, h /= 2;
  }
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, w, h, 0, GL_RGB, GL_UNSIGNED_SHORT_5_6_5, base);
  uint16_t *src = base, *dst = base + (size_t)w * h;
  for (int lw = w, lh = h, level = 1; lw > 1 || lh > 1; ++level) {
    mip_down(src, lw, lh, dst, 0);
    lw = lw > 1 ? lw / 2 : 1;
    lh = lh > 1 ? lh / 2 : 1;
    glTexImage2D(GL_TEXTURE_2D, level, GL_RGB, lw, lh, 0, GL_RGB, GL_UNSIGNED_SHORT_5_6_5, dst);
    src = dst;
    dst += (size_t)lw * lh;
  }
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, mip_filter());
  tex_aniso();
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
  free(px);
  return name;
#endif
}

#include "render_ghost_paint.inc"

int wpk_upload(wpk_scene *s, size_t budget) {
  if (s->next_cube >= s->n_cube && s->next_tex >= s->n_tex && s->next_batch >= s->n_batch) return 1;
  if (s->fd < 0) return 1; /* unreadable: what is in GL stays */
  size_t done = 0;
  for (; s->next_cube < s->n_cube && done < budget; ++s->next_cube) {
    size_t n = cube_upload(s, s->next_cube);
    done += n ? n : 1;
  }
  for (; s->next_tex < s->n_tex && done < budget; ++s->next_tex) {
    uint32_t i = s->next_tex;
    if (s->skip_paints && s->is_paint[i]) continue; /* wpk_upload_paints */
    if (s->share_idx && s->share_idx[i] != 0xFFFF) continue; /* the stock pack's */
    size_t n = tex_upload(s, i);
    done += n ? n : 1;
  }
  if (s->ao_file && s->next_tex >= s->n_tex && done < budget) done += ao_upload(s);
  uint32_t stride = s->stride, rec_size = s->rec_size;
  for (; s->next_batch < s->n_batch && done < budget; ++s->next_batch) {
    const char *rec = (const char *)s->batch_tbl + (size_t)s->next_batch * rec_size;
    const wpk_batch_rec *r = (const wpk_batch_rec *)rec;
    wpk_batch *b = &s->batches[s->next_batch];
    b->tex = r->tex;
    b->flags = r->flags;
    b->count = 0; /* published only after all index uploads succeed */
    b->cutout = r->tex != 0xFFFF && r->tex < s->n_tex && s->tex_alpha[r->tex];
    wpk_pool *pl = &s->pools[b->pool];
    uint32_t base = pl->vfill / stride;
    if (!wpk_indices_valid(NULL, 0, r->vtx_count, base) ||
        (uint64_t)r->idx_count * 2u > SIZE_MAX || (uint64_t)r->vtx_count * stride > SIZE_MAX) {
      fprintf(stderr, "WPK: batch %u exceeds mesh limits\n", s->next_batch);
      done++;
      continue;
    }
    size_t vbytes = (size_t)r->vtx_count * stride, ibytes = (size_t)r->idx_count * 2u;
    struct stat st;
    if (fstat(s->fd, &st) != 0 || st.st_size < 0 ||
        !wpk_range_valid((uint64_t)st.st_size, r->vtx_off, vbytes) ||
        !wpk_range_valid((uint64_t)st.st_size, r->idx_off, ibytes)) {
      fprintf(stderr, "WPK: batch %u has invalid file ranges\n", s->next_batch);
      done++;
      continue;
    }
    /* Scan index data in bounded chunks, even for a very large valid file. */
    enum { INDEX_CHUNK = 65536 };
    size_t index_scratch = ibytes < INDEX_CHUNK ? ibytes : INDEX_CHUNK;
    if (index_scratch > SIZE_MAX - vbytes) {
      fprintf(stderr, "WPK: batch %u exceeds scratch limit\n", s->next_batch);
      done++;
      continue;
    }
    size_t scratch_bytes = vbytes + index_scratch;
    uint8_t *v = scratch(s, scratch_bytes ? scratch_bytes : 1);
    uint16_t *idx = v ? (uint16_t *)(void *)(v + vbytes) : NULL;
    int indices_ok = v != NULL;
    for (size_t at = 0; indices_ok && at < ibytes;) {
      size_t n = ibytes - at < INDEX_CHUNK ? ibytes - at : INDEX_CHUNK;
      if (read_at(s->fd, idx, n, (off_t)((uint64_t)r->idx_off + at)) != 0 ||
          !wpk_indices_valid(idx, (uint32_t)(n / 2u), r->vtx_count, base)) indices_ok = 0;
      at += n;
    }
    if (!indices_ok || !wpk_indices_valid(idx, 0, r->vtx_count, base)) {
      fprintf(stderr, "WPK: batch %u has unreadable or invalid indices\n", s->next_batch);
      done++;
      continue;
    }
    if (read_at(s->fd, v, vbytes, r->vtx_off) != 0) {
      fprintf(stderr, "WPK: batch %u has unreadable vertices\n", s->next_batch);
      b->count = 0;
      done++;
      continue;
    }
    for (uint32_t k = 0; k < r->vtx_count && !b->cutout; ++k) b->cutout = v[stride * k + 23] < 128;
    /* its box (render_overhead culls a map's batches one by one) */
    for (int a = 0; a < 3; ++a) b->lo[a] = 1e30f, b->hi[a] = -1e30f;
    for (uint32_t k = 0; k < r->vtx_count; ++k) {
      float q[3];
      memcpy(q, v + (size_t)stride * k, sizeof q);
      for (int a = 0; a < 3; ++a) {
        if (q[a] < b->lo[a]) b->lo[a] = q[a];
        if (q[a] > b->hi[a]) b->hi[a] = q[a];
      }
    }
    if (s->lit) {
      /* u8 program, u8 pad, u16 env, u16 specular map, u16 env power * 10000 */
      uint16_t m[3];
      memcpy(m, rec + 22, sizeof m);
      b->prog = (uint8_t)rec[20] < WPK_LIT_PROGS ? (uint8_t)rec[20] : WPK_LIT_FF;
      b->env = m[0] < s->n_tex ? m[0] : 0xFFFF;
      b->spec = m[1] < s->n_tex ? m[1] : 0xFFFF;
      b->power = (float)m[2] / 10000.0f;
      if (b->prog == WPK_LIT_CAR) b->cutout = 0; /* car.cg writes alpha 1 */
    }
#ifdef WMMT_NATIVE_VK
    /* Append transaction: existing drawable ranges stay intact. Missing handles
     * remain private until every vertex/normal/index span has been written. */
    size_t nb = pl->nbytes ? (size_t)r->vtx_count * 8u : 0;
    if (pl->vfill > pl->vbytes || vbytes > pl->vbytes - pl->vfill ||
        pl->ifill > pl->ibytes || ibytes > pl->ibytes - pl->ifill ||
        pl->nfill > pl->nbytes || nb > pl->nbytes - pl->nfill) {
      fprintf(stderr, "WPK: batch %u exceeds pool capacity\n", s->next_batch);
      done++;
      continue;
    }
    uint32_t vbo = pl->vbo, ibo = pl->ibo, nbo = pl->nbo;
    if (!vbo && pl->vbytes) vbo = cinder_vk_buffer_create(pl->vbytes, NULL);
    if (!ibo && pl->ibytes) ibo = cinder_vk_buffer_create(pl->ibytes, NULL);
    if (!nbo && pl->nbytes) nbo = cinder_vk_buffer_create(pl->nbytes, NULL);
    int uploaded = (!pl->vbytes || vbo) && (!pl->ibytes || ibo) && (!pl->nbytes || nbo);
    if (uploaded && vbytes) uploaded = cinder_vk_buffer_update(vbo, pl->vfill, vbytes, v);
    if (uploaded && nb) {
      uint32_t noff = s->gloss_noff ? s->gloss_noff[s->next_batch] : 0;
      if (!noff || read_at(s->fd, v, nb, noff) != 0) memset(v, 0, nb);
      uploaded = cinder_vk_buffer_update(nbo, pl->nfill, nb, v);
    }
    /* Keep the bounded re-read/validation: the file may change after its scan. */
    for (size_t at = 0; uploaded && at < ibytes;) {
      size_t n = ibytes - at < INDEX_CHUNK ? ibytes - at : INDEX_CHUNK;
      if (read_at(s->fd, idx, n, (off_t)((uint64_t)r->idx_off + at)) != 0 ||
          !wpk_indices_valid(idx, (uint32_t)(n / 2u), r->vtx_count, base)) {
        uploaded = 0;
        break;
      }
      for (size_t k = 0; k < n / 2u; ++k) idx[k] = (uint16_t)(idx[k] + base);
      uploaded = cinder_vk_buffer_update(ibo, (size_t)pl->ifill + at, n, idx);
      at += n;
    }
    if (!uploaded) {
      if (vbo != pl->vbo) cinder_vk_buffer_destroy(vbo);
      if (ibo != pl->ibo) cinder_vk_buffer_destroy(ibo);
      if (nbo != pl->nbo) cinder_vk_buffer_destroy(nbo);
      fprintf(stderr, "WPK: batch %u buffer upload failed or indices changed\n", s->next_batch);
      done++;
      continue;
    }
    pl->vbo = vbo; pl->ibo = ibo; pl->nbo = nbo;
    b->ioff = pl->ifill;
    pl->vfill += (uint32_t)vbytes;
    pl->nfill += (uint32_t)nb;
    pl->ifill += (uint32_t)ibytes;
    b->count = r->idx_count;
    done += nb;
#else
    if (!pl->vbo) {
      glGenBuffers(1, &pl->vbo);
      glBindBuffer(GL_ARRAY_BUFFER, pl->vbo);
      glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)pl->vbytes, NULL, GL_STATIC_DRAW);
      glGenBuffers(1, &pl->ibo);
      glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, pl->ibo);
      glBufferData(GL_ELEMENT_ARRAY_BUFFER, (GLsizeiptr)pl->ibytes, NULL, GL_STATIC_DRAW);
    }
    glBindBuffer(GL_ARRAY_BUFFER, pl->vbo);
    glBufferSubData(GL_ARRAY_BUFFER, (GLintptr)pl->vfill, (GLsizeiptr)vbytes, v);
    pl->vfill += (uint32_t)vbytes;
    if (pl->nbytes) {
      /* a gloss batch: its normals into the pool's other buffer, lined up with the vertices */
      size_t nb = (size_t)r->vtx_count * 8;
      uint32_t noff = s->gloss_noff ? s->gloss_noff[s->next_batch] : 0;
      if (!pl->nbo) {
        glGenBuffers(1, &pl->nbo);
        glBindBuffer(GL_ARRAY_BUFFER, pl->nbo);
        glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)pl->nbytes, NULL, GL_STATIC_DRAW);
      }
      if (!noff || read_at(s->fd, v, nb, noff) != 0) memset(v, 0, nb);
      glBindBuffer(GL_ARRAY_BUFFER, pl->nbo);
      glBufferSubData(GL_ARRAY_BUFFER, (GLintptr)pl->nfill, (GLsizeiptr)nb, v);
      pl->nfill += (uint32_t)nb;
      done += nb;
    }
    /* Re-read and validate each chunk before upload; a failed or changed file leaves
     * count zero, so partially written index bytes cannot be drawn. */
    b->ioff = pl->ifill;
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, pl->ibo);
    for (size_t at = 0; at < ibytes;) {
      size_t n = ibytes - at < INDEX_CHUNK ? ibytes - at : INDEX_CHUNK;
      if (read_at(s->fd, idx, n, (off_t)((uint64_t)r->idx_off + at)) != 0 ||
          !wpk_indices_valid(idx, (uint32_t)(n / 2u), r->vtx_count, base)) {
        indices_ok = 0;
        break;
      }
      for (size_t k = 0; k < n / 2u; ++k) idx[k] = (uint16_t)(idx[k] + base);
      glBufferSubData(GL_ELEMENT_ARRAY_BUFFER, (GLintptr)(pl->ifill + at), (GLsizeiptr)n, idx);
      at += n;
    }
    if (indices_ok) {
      pl->ifill += (uint32_t)ibytes;
      b->count = r->idx_count;
    } else {
      fprintf(stderr, "WPK: batch %u indices changed or became unreadable\n", s->next_batch);
    }
#endif
    if (ibytes > SIZE_MAX - vbytes || vbytes + ibytes > SIZE_MAX - done) done = SIZE_MAX;
    else done += vbytes + ibytes;
  }
  if (s->next_cube < s->n_cube || s->next_tex < s->n_tex || s->next_batch < s->n_batch) return 0;
  /* everything (but the paints left for later) now lives in GL */
  free(s->batch_tbl);
  s->batch_tbl = NULL;
  free(s->cube_tbl);
  s->cube_tbl = NULL;
  free(s->gloss_noff);
  s->gloss_noff = NULL;
  file_close(s);
  return 1;
}

int wpk_has_paint(const wpk_scene *s, int k) {
  for (uint32_t i = 0; i < s->n_paints; ++i)
    if (s->paints[i].k == k && !s->loaded[s->paints[i].src]) return 0;
  return 1;
}

int wpk_upload_paints(wpk_scene *s, size_t budget) {
  size_t done = 0;
  for (uint32_t i = 0; i < s->n_paints; ++i) {
    uint16_t t = s->paints[i].src;
    if (s->loaded[t]) continue;
    if (done >= budget) return 0;
    if (s->fd < 0 && (!s->path || (s->fd = open(s->path, O_RDONLY)) < 0)) return 1; /* gone: the model's own */
    size_t n = tex_upload(s, t);
    done += n ? n : 1;
  }
  if (s->next_tex >= s->n_tex && s->next_batch >= s->n_batch) file_close(s);
  return 1;
}

void wpk_free_paints(wpk_scene *s) {
  wpk_paint(s, 0);
  for (uint32_t i = 0; i < s->n_paints; ++i) {
    uint16_t t = s->paints[i].src;
#ifdef WMMT_NATIVE_VK
    if (s->loaded[t]) cinder_vk_texture_destroy(s->loaded[t]);
#else
    if (s->loaded[t]) glDeleteTextures(1, &s->loaded[t]);
#endif
    s->loaded[t] = s->textures[t] = 0;
    s->tex_warm[t] = 0;
  }
}

void wpk_share(wpk_scene *s, const wpk_scene *base) {
  const wpk_tex *tex = s->tex_tbl, *btex = base->tex_tbl;
  s->share = base;
  s->share_idx = malloc((s->n_tex ? s->n_tex : 1) * sizeof(uint16_t));
  if (!s->share_idx) return;
  for (uint32_t i = 0; i < s->n_tex; ++i) {
    s->share_idx[i] = 0xFFFF;
    if (tex[i].size) continue;
    for (uint32_t j = 0; btex && j < base->n_tex; ++j)
      if (memcmp(tex[i].name, btex[j].name, sizeof tex[i].name) == 0) {
        s->share_idx[i] = (uint16_t)j;
        s->tex_alpha[i] = base->tex_alpha[j];
        break;
      }
  }
  /* the paints follow the stock pack's (wpk_paint on base): none of its own on what it borrows */
  uint32_t n = 0;
  for (uint32_t i = 0; i < s->n_paints; ++i) {
    wpk_paint_swap p = s->paints[i];
    if (s->share_idx[p.src] == 0xFFFF && s->share_idx[p.dst] == 0xFFFF) s->paints[n++] = p;
    else s->is_paint[p.src] = 0;
  }
  s->n_paints = n;
}

void wpk_share_sync(wpk_scene *s) {
  const wpk_scene *base = s->share;
  for (uint32_t i = 0; base && s->share_idx && i < s->n_tex; ++i)
    if (s->share_idx[i] != 0xFFFF) s->textures[i] = base->textures[s->share_idx[i]];
}

int wpk_load(wpk_scene *s, const char *path) {
  if (wpk_open(s, path) != 0) return -1;
  wpk_upload(s, (size_t)-1);
  return 0;
}

#ifdef __ANDROID__
int wpk_load_course_arrows(wpk_scene *s, const char *path) {
  if (wpk_open(s, path) != 0) return -1;
  s->course_arrows = 1;
  wpk_upload(s, (size_t)-1);
  return 0;
}
#endif

static void pool_free(wpk_pool *pl) {
#ifdef WMMT_NATIVE_VK
  if (pl->vbo) cinder_vk_buffer_destroy(pl->vbo);
  if (pl->ibo) cinder_vk_buffer_destroy(pl->ibo);
  if (pl->nbo) cinder_vk_buffer_destroy(pl->nbo);
#else
  if (pl->vao) glDeleteVertexArraysOES(1, &pl->vao);
  if (pl->vbo) glDeleteBuffers(1, &pl->vbo);
  if (pl->ibo) glDeleteBuffers(1, &pl->ibo);
  if (pl->nbo) glDeleteBuffers(1, &pl->nbo);
#endif
  pl->vao = pl->vbo = pl->ibo = pl->nbo = 0;
}

void wpk_free(wpk_scene *s) {
  for (uint32_t i = 0; s->pools && i < s->n_pools; ++i) pool_free(&s->pools[i]);
  for (uint32_t i = 0; s->loaded && i < s->n_tex; ++i)
#ifdef WMMT_NATIVE_VK
    if (s->loaded[i]) cinder_vk_texture_destroy(s->loaded[i]);
#else
    if (s->loaded[i]) glDeleteTextures(1, &s->loaded[i]);
#endif
  for (uint32_t i = 0; s->cubes && i < s->n_cube; ++i)
#ifdef WMMT_NATIVE_VK
    if (s->cubes[i]) cinder_vk_texture_destroy(s->cubes[i]);
#else
    if (s->cubes[i]) glDeleteTextures(1, &s->cubes[i]);
#endif
  free(s->cubes);
  free(s->cube_warm);
  free(s->cube_tbl);
  free(s->gloss_noff);
  for (uint32_t i = 0; s->ao_tex && i < s->n_ao; ++i)
#ifdef WMMT_NATIVE_VK
    if (s->ao_tex[i]) cinder_vk_texture_destroy(s->ao_tex[i]);
#else
    if (s->ao_tex[i]) glDeleteTextures(1, &s->ao_tex[i]);
#endif
  free(s->ao_tex);
  free(s->ao_file);
  file_close(s);
  free(s->path);
  free(s->tex_tbl);
  free(s->batch_tbl);
  free(s->textures);
  free(s->loaded);
  free(s->paints);
  free(s->is_paint);
  free(s->chunks);
  free(s->batches);
  free(s->pools);
  free(s->warm);
  free(s->tex_alpha);
  free(s->tex_wet);
  free(s->tex_warm);
  free(s->share_idx);
  memset(s, 0, sizeof *s);
  s->fd = -1;
}

int wpk_free_step(wpk_scene *s, uint32_t budget) {
  for (; budget && s->n_pools; --budget) pool_free(&s->pools[--s->n_pools]);
  for (; budget && s->n_tex; --budget) {
    uint32_t i = --s->n_tex;
#ifdef WMMT_NATIVE_VK
    if (s->loaded && s->loaded[i]) cinder_vk_texture_destroy(s->loaded[i]);
#else
    if (s->loaded && s->loaded[i]) glDeleteTextures(1, &s->loaded[i]);
#endif
  }
  if (s->n_pools || s->n_tex) return 0;
  wpk_free(s);
  return 1;
}

void wpk_blend_texture(wpk_scene *s, const char *name) {
  const wpk_tex *tex = s->tex_tbl;
  for (uint32_t i = 0; tex && i < s->n_batch; ++i) {
    if (s->batches[i].tex >= s->n_tex) continue;
    const char *a = tex[s->batches[i].tex].name, *b = name;
    while (*a && *a == *b) a++, b++;
    if (*a == *b) s->batches[i].flags = (uint16_t)((s->batches[i].flags & ~WPK_BLEND_MASK) | 1);
  }
}

void wpk_paint(wpk_scene *s, int k) {
  if (!wpk_has_paint(s, k)) k = 0;
  for (uint32_t i = 0; i < s->n_paints; ++i) s->textures[s->paints[i].dst] = s->loaded[s->paints[i].dst];
  for (uint32_t i = 0; i < s->n_paints; ++i)
    if (s->paints[i].k == k) s->textures[s->paints[i].dst] = s->loaded[s->paints[i].src];
}

/* This switch only changes existing uniform values, never shaders or HQ feature choices. */
static int enhance_on;
void render_enhance(int on) { enhance_on = on != 0; }

/* The caller supplies the time zone; fog and rain do not reliably indicate night. */
static float enhance_night(const render_params *p) {
  return p->night ? 1.0f : 0.0f;
}

static void enhance_grade(const render_params *p, int road, float out[3]) {
  float night = enhance_night(p);
  for (int k = 0; k < 3; ++k) {
    float base = p->grade[0] > 0.0f ? p->grade[k] : 1.0f;
    /* Slightly restrained highlights, a cool night grade, and a dry asphalt lift.
     * This retains the texture's baked detail rather than introducing a mirror. */
    float scale = 0.985f + night * (k == 2 ? 0.045f : k == 1 ? 0.020f : 0.0f);
    if (road) scale *= 1.055f + 0.025f * night;
    out[k] = base * scale;
  }
}

void render_display_begin(int width, int height) {
#ifdef WMMT_NATIVE_VK
  native_scene = (native_scene_view){0, width, height};
#else
  (void)width; (void)height;
#endif
}

void render_begin(const render_params *p) {
#ifdef WMMT_NATIVE_VK
  if (native_scene.w <= 0 || native_scene.h <= 0) {
    native_scene.target = 0;
    cinder_vk_screen_extent(&native_scene.w, &native_scene.h);
  }
#endif
#ifndef WMMT_NATIVE_VK
  static const float none[3] = { 1.0f, 1.0f, 1.0f };
  float adjusted[3];
  const float *grade = p->grade[0] > 0.0f ? p->grade : none;
  if (enhance_on) { enhance_grade(p, 0, adjusted); grade = adjusted; }
  for (int i = 3; i >= 0; --i) { /* the programs' fog; the opaque one's left in use */
    const scene_prog *pr = i < 2 ? &progs[i] : &gloss_progs[i - 2];
    glUseProgram(pr->id);
    glUniform3fv(pr->fog_color, 1, p->fog_color);
    glUniform3fv(pr->grade, 1, grade);
    glUniform2f(pr->fog, p->fog_far, p->fog_near);
    glUniform1i(pr->tex, 0);
    glUniform2f(pr->uv_off, 0, 0);
  }
#endif
#ifndef WMMT_NATIVE_VK
  glActiveTexture(GL_TEXTURE0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glEnableVertexAttribArray(2);
  glEnable(GL_DEPTH_TEST);
  glDepthFunc(GL_LEQUAL);
  glEnable(GL_CULL_FACE);
  glCullFace(GL_BACK);
  glFrontFace(GL_CCW);
#else
  /* Native draws name samplers and their complete pipeline in each packet. */
  (void)p;
#endif
}

/* ---- render_hq (a phone of today's, app_console): the 3D through a multisampled
 * half-float target, resolved into blur.tex, then a bloom (a bright pass and a chain of
 * half-size levels down and back up, after the one Call of Duty: Advanced Warfare showed at
 * SIGGRAPH 2014) added in the composite, which rolls the highlights off (FS_BLUR's HQ). The
 * ES3 entry points are looked up: gl.h is the ES2 header. ---- */
#define HQ_LEVELS 4
#define HQ_LEVELS_N 8 /* render_hq_level's */
typedef void (*hq_blit_fn)(GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLbitfield, GLenum);
typedef void (*hq_rbms_fn)(GLenum, GLsizei, GLenum, GLsizei, GLsizei);
typedef void (*hq_inval_fn)(GLenum, GLsizei, const GLenum *);
typedef void (*hq_tex_ms_fn)(GLenum, GLenum, GLenum, GLuint, GLint, GLsizei);
static struct {
  int on, samples, fmt; /* fmt: HQ_FORMATS' the targets are in */
  float bloom;           /* the bloom's share in the composite */
  hq_blit_fn blit;
  hq_rbms_fn storage_ms;
  hq_inval_fn invalidate;
  /* EXT_multisampled_render_to_texture (Adreno's, Mali's): the samples live in the tile
   * memory alone and the frame lands resolved in its texture as each tile is stored, no
   * multisampled buffer in memory and no blit; the frame alternates between blur.tex and
   * rt_tex (the paint and the wet road read the last one), swapped in render_blur_end. */
  int msrt;
#ifndef WMMT_VK
  int msrt_available;
#endif
  /* render_hq_level's: what has been given up for the frame rate, and as asked: the share
   * of the screen's size the 3D is drawn at, the samples and the bloom */
  int level, samples0;
  float scale, bloom0;
  int opt_bloom, opt_ao, opt_paint, opt_wet; /* render_hq_options' (the settings' switches) */
  hq_tex_ms_fn tex_ms;
  hq_rbms_fn storage_ms_ext;
  GLuint rt_tex, rt_fbo, rt_depth;
  GLuint ms_fbo, ms_color, ms_depth;
  GLuint tex[HQ_LEVELS], fbo[HQ_LEVELS];
  int w[HQ_LEVELS], h[HQ_LEVELS];
  GLuint down_prog[2], up_prog; /* down: [1] with the bright pass */
  GLint down_texel[2], down_thresh, up_texel;
  /* render_ssao: the depth resolved into z_tex, the occlusion at half size in ao_tex[0], its
   * blur in [1]; view: the near and far planes, the tangents of the half angles (x, y) */
  float ssao, view[4];
  int ssao_ok, view_set, ao_on, aw, ah; /* ao_on: this frame's made */
#ifdef WMMT_VK
  int single_ready, single_attempted, single_frame;
  GLuint single_fbo[2]; /* follows blur.tex and rt_tex, respectively */
#endif
  GLuint z_tex, z_fbo, ao_tex[2], ao_fbo[2], ao_prog, ao_blur_prog;
  GLint ao_view, ao_texel, ao_k, ao_blur_texel;
} hq;
static int hq_said; /* the format told to the log */

static const char *VS_POST =
  "attribute vec2 aPos; varying vec2 vUV;\n"
  "void main() { gl_Position = vec4(aPos, 0.0, 1.0); vUV = aPos * 0.5 + 0.5; }\n";
/* four bilinear taps, a 4x4 box of the level above; the first with the bright pass (a soft
 * knee about the threshold, by the brightest channel) */
static const char *FS_DOWN =
  "precision mediump float; uniform sampler2D uTex; uniform vec2 uTexel; varying vec2 vUV;\n"
  "#if BRIGHT\n"
  "uniform float uThresh;\n"
  "#endif\n"
  "void main() {\n"
  "  vec3 c = (texture2D(uTex, vUV + vec2(-uTexel.x, -uTexel.y)).rgb + texture2D(uTex, vUV + vec2(uTexel.x, -uTexel.y)).rgb\n"
  "          + texture2D(uTex, vUV + vec2(-uTexel.x, uTexel.y)).rgb + texture2D(uTex, vUV + uTexel).rgb) * 0.25;\n"
  "#if BRIGHT\n"
  "  float br = max(c.r, max(c.g, c.b)), knee = uThresh * 0.5;\n"
  "  float soft = clamp(br - uThresh + knee, 0.0, 2.0 * knee);\n"
  "  soft = soft * soft / (4.0 * knee + 0.0001);\n"
  "  c *= max(soft, br - uThresh) / max(br, 0.0001);\n"
  "#endif\n"
  "  gl_FragColor = vec4(c, 1.0);\n"
  "}\n";
/* the level below up by a 3x3 tent, added to this one */
static const char *FS_UP =
  "precision mediump float; uniform sampler2D uTex; uniform vec2 uTexel; varying vec2 vUV;\n"
  "void main() {\n"
  "  vec2 d = uTexel;\n"
  "  vec3 c = texture2D(uTex, vUV).rgb * 4.0\n"
  "         + (texture2D(uTex, vUV + vec2(d.x, 0.0)).rgb + texture2D(uTex, vUV - vec2(d.x, 0.0)).rgb\n"
  "         + texture2D(uTex, vUV + vec2(0.0, d.y)).rgb + texture2D(uTex, vUV - vec2(0.0, d.y)).rgb) * 2.0\n"
  "         + texture2D(uTex, vUV + d).rgb + texture2D(uTex, vUV - d).rgb\n"
  "         + texture2D(uTex, vUV + vec2(d.x, -d.y)).rgb + texture2D(uTex, vUV + vec2(-d.x, d.y)).rgb;\n"
  "  gl_FragColor = vec4(c * (1.0 / 16.0), 1.0);\n"
  "}\n";
/* render_ssao: ambient occlusion from the resolved depth, at half size: the point and its
 * normal (from the nearer neighbour each way, 4 texels off: the depth's own noise at a
 * glancing angle is small beside it) in view space, 8 taps on a spiral turned by a 4 x 4
 * pattern within SSAO_R (world units, 0.1 m) of it, each occluding as its elevation over
 * the surface (less an angle's bias, as HBAO's) by a falloff with distance; fading out by
 * SSAO_FAR. Out: the occlusion, the depth in 16 bits for the blur. */
#define SSAO_R "12.0"
#define SSAO_FAR "2000.0"
static const char *FS_SSAO =
  "precision highp float;\n"
  "uniform sampler2D uTex; uniform vec4 uView; uniform vec2 uTexel; uniform float uK;\n"
  "varying vec2 vUV;\n"
  "float lin(vec2 uv) { return uView.x * uView.y / (uView.y - texture2D(uTex, uv).r * (uView.y - uView.x)); }\n"
  "vec3 pos(vec2 uv) {\n"
  "  uv = (floor(uv / uTexel) + 0.5) * uTexel;\n" /* the texel's centre, where its depth is */
  "  float z = lin(uv);\n"
  "  return vec3((uv * 2.0 - 1.0) * uView.zw * z, -z);\n"
  "}\n"
  "vec3 near_of(vec3 p, vec3 a, vec3 b) { return abs(a.z - p.z) < abs(b.z - p.z) ? a - p : p - b; }\n"
  "void main() {\n"
  "  vec3 p = pos(vUV);\n"
  "  float z = -p.z;\n"
  "  if (z > " SSAO_FAR ") { gl_FragColor = vec4(1.0, 1.0, 1.0, 1.0); return; }\n"
  "  vec2 dx = vec2(uTexel.x * 4.0, 0.0), dy = vec2(0.0, uTexel.y * 4.0);\n"
  "  vec3 n = normalize(cross(near_of(p, pos(vUV + dx), pos(vUV - dx)), near_of(p, pos(vUV + dy), pos(vUV - dy))));\n"
  "  vec2 f = floor(mod(gl_FragCoord.xy, 4.0));\n"
  "  float a = (f.x * 4.0 + mod(f.y * 3.0 + f.x, 4.0)) * 0.3927;\n"
  "  vec2 r = " SSAO_R " / (z * 2.0 * uView.zw);\n"
  "  r *= min(1.0, 0.12 / r.y);\n"
  "  float sum = 0.0, r2 = " SSAO_R " * " SSAO_R ";\n"
  "  for (int i = 0; i < 8; ++i) {\n"
  "    float t = (float(i) + 0.5) * 0.125, ang = a + float(i) * 2.39996;\n"
  "    vec3 v = pos(vUV + vec2(cos(ang), sin(ang)) * r * t) - p;\n"
  "    float vv = dot(v, v) + 0.01, fall = max(1.0 - vv / r2, 0.0);\n"
  "    sum += max(dot(v, n) * inversesqrt(vv) - 0.25, 0.0) * fall * fall;\n"
  "  }\n"
  "  float ao = max(0.0, 1.0 - sum * uK * (2.0 / 8.0));\n"
  "  ao = mix(ao, 1.0, smoothstep(0.5 * " SSAO_FAR ", " SSAO_FAR ", z));\n"
  "  float d = z / " SSAO_FAR " * 255.0;\n"
  "  gl_FragColor = vec4(ao, floor(d) / 255.0, fract(d), 1.0);\n"
  "}\n";
/* its 4 x 4 blur (one turn of the pattern each way), the taps of about the same depth only
 * (the noise's pattern gone, no halo across an edge) */
static const char *FS_AO_BLUR =
  "precision highp float; uniform sampler2D uTex; uniform vec2 uTexel; varying vec2 vUV;\n"
  "void main() {\n"
  "  vec4 c = texture2D(uTex, vUV);\n"
  "  float z = c.g + c.b / 255.0, sum = 0.0, wsum = 0.0;\n"
  "  for (int y = -2; y < 2; ++y)\n"
  "    for (int x = -2; x < 2; ++x) {\n"
  "      vec4 s = texture2D(uTex, vUV + vec2(float(x), float(y)) * uTexel);\n"
  "      float w = max(0.0, 1.0 - abs(s.g + s.b / 255.0 - z) / (0.05 * z + 0.002));\n"
  "      sum += s.r * w; wsum += w;\n"
  "    }\n"
  "  gl_FragColor = vec4(wsum > 0.0 ? sum / wsum : c.r, 0.0, 0.0, 1.0);\n"
  "}\n";

#define GL_RGBA16F_ 0x881A
#define GL_R11F_G11F_B10F_ 0x8C3A
#define GL_HALF_FLOAT_ 0x140B
#define GL_RGBA8_ 0x8058
/* the targets' formats, best first: 32 bits of floats (the tiles hold as many pixels as
 * RGBA8's: 4x MSAA in RGBA16F cost the Mi 6 5 ms a frame), 64, then no floats */
#ifndef WMMT_NATIVE_VK
static const struct { GLenum internal, format, type; } HQ_FORMATS[3] = {
  { GL_R11F_G11F_B10F_, GL_RGB, GL_HALF_FLOAT_ },
  { GL_RGBA16F_, GL_RGBA, GL_HALF_FLOAT_ },
  { GL_RGBA8_, GL_RGBA, GL_UNSIGNED_BYTE },
};
#endif
#define GL_READ_FRAMEBUFFER_ 0x8CA8
#define GL_DRAW_FRAMEBUFFER_ 0x8CA9
#define GL_MAX_SAMPLES_ 0x8D57
#define GL_DEPTH24_STENCIL8_ 0x88F0
#define GL_DEPTH_STENCIL_ 0x84F9
#define GL_UNSIGNED_INT_24_8_ 0x84FA
#define GL_DEPTH_STENCIL_ATTACHMENT_ 0x821A

#ifdef WMMT_NATIVE_VK
#include "render_native_targets.inc"
#else
/* a target's texture in hq.fmt, bound, linear and clamped (blur.tex's too) */
static void hq_tex_image(int w, int h) {
  glTexImage2D(GL_TEXTURE_2D, 0, (GLint)HQ_FORMATS[hq.fmt].internal, w, h, 0, HQ_FORMATS[hq.fmt].format,
               HQ_FORMATS[hq.fmt].type, NULL);
}

static GLuint hq_texture(int w, int h) {
  GLuint t;
  glGenTextures(1, &t);
  glBindTexture(GL_TEXTURE_2D, t);
  hq_tex_image(w, h);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  return t;
}

static GLuint hq_fbo(GLuint tex) {
  GLuint f;
  glGenFramebuffers(1, &f);
  glBindFramebuffer(GL_FRAMEBUFFER, f);
  glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
  return f;
}

static void hq_free(void) {
  frame_history_valid = 0;
  frame_sampler_off();
  if (hq.ms_fbo) glDeleteFramebuffers(1, &hq.ms_fbo);
  if (hq.ms_color) glDeleteRenderbuffers(1, &hq.ms_color);
  if (hq.ms_depth) glDeleteRenderbuffers(1, &hq.ms_depth);
  for (int i = 0; i < HQ_LEVELS; ++i) {
    if (hq.fbo[i]) glDeleteFramebuffers(1, &hq.fbo[i]);
    if (hq.tex[i]) glDeleteTextures(1, &hq.tex[i]);
  }
  hq.ms_fbo = hq.ms_color = hq.ms_depth = 0;
  memset(hq.tex, 0, sizeof hq.tex);
  memset(hq.fbo, 0, sizeof hq.fbo);
  if (hq.z_fbo) glDeleteFramebuffers(1, &hq.z_fbo);
  if (hq.z_tex) glDeleteTextures(1, &hq.z_tex);
  for (int i = 0; i < 2; ++i) {
    if (hq.ao_fbo[i]) glDeleteFramebuffers(1, &hq.ao_fbo[i]);
    if (hq.ao_tex[i]) glDeleteTextures(1, &hq.ao_tex[i]);
  }
  if (hq.rt_fbo) glDeleteFramebuffers(1, &hq.rt_fbo);
  if (hq.rt_tex) glDeleteTextures(1, &hq.rt_tex);
  if (hq.rt_depth) glDeleteRenderbuffers(1, &hq.rt_depth);
  hq.rt_fbo = hq.rt_tex = hq.rt_depth = 0;
  hq.z_fbo = hq.z_tex = 0;
  memset(hq.ao_tex, 0, sizeof hq.ao_tex);
  memset(hq.ao_fbo, 0, sizeof hq.ao_fbo);
  hq.ssao_ok = 0;
#ifdef WMMT_VK
  for (int i = 0; i < 2; ++i) {
    if (hq.single_fbo[i]) glDeleteFramebuffers(1, &hq.single_fbo[i]);
    hq.single_fbo[i] = 0;
  }
  hq.single_ready = hq.single_attempted = hq.single_frame = 0;
#endif
}

/* render_ssao's targets: the depth (as the multisampled one's, for the blit) and the half
 * size occlusion's two; without them no occlusion, the rest as it was */
static GLuint z_texture(int w, int h) {
  GLuint t;
  glGenTextures(1, &t);
  glBindTexture(GL_TEXTURE_2D, t);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH24_STENCIL8_, w, h, 0, GL_DEPTH_STENCIL_, GL_UNSIGNED_INT_24_8_, NULL);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  return t;
}

/* The optional single-sample Vulkan compatibility path already attaches z_tex. */
static void ssao_targets(int w, int h) {
  if (hq.ssao <= 0.0f || !hq.ao_prog || !hq.opt_ao) return;
  int ok = hq.z_tex != 0;
  if (!hq.msrt
#ifdef WMMT_VK
      && !hq.single_ready
#endif
  ) {
    hq.z_tex = z_texture(w, h);
    glGenFramebuffers(1, &hq.z_fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, hq.z_fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT_, GL_TEXTURE_2D, hq.z_tex, 0);
    ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
  }
  hq.aw = w / 2 > 1 ? w / 2 : 1;
  hq.ah = h / 2 > 1 ? h / 2 : 1;
  for (int i = 0; ok && i < 2; ++i) {
    glGenTextures(1, &hq.ao_tex[i]);
    glBindTexture(GL_TEXTURE_2D, hq.ao_tex[i]);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, hq.aw, hq.ah, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    /* the blur's taps exact (its depths must not blend), the composite's smooth */
    GLint filter = i ? GL_LINEAR : GL_NEAREST;
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filter);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    hq.ao_fbo[i] = hq_fbo(hq.ao_tex[i]);
    ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
  }
  hq.ssao_ok = ok;
  fprintf(stderr, "render_ssao: %s\n", ok ? "on" : "no depth texture target, off");
}

/* the targets for a w x h frame (blur's own texture and framebuffer being the resolve's);
 * 0 if this GPU can't */
/* MSRT writes colour into either texture and shares transient depth/stencil. */
static int msrt_targets(int w, int h) {
  glGenRenderbuffers(1, &hq.rt_depth);
  glBindRenderbuffer(GL_RENDERBUFFER, hq.rt_depth);
  hq.storage_ms_ext(GL_RENDERBUFFER, hq.samples, GL_DEPTH24_STENCIL8_OES, w, h);
  hq.rt_tex = hq_texture(w, h);
  glGenFramebuffers(1, &hq.rt_fbo);
  int ok = 1;
  for (int k = 0; k < 2; ++k) {
    glBindFramebuffer(GL_FRAMEBUFFER, k ? hq.rt_fbo : blur.fbo);
    hq.tex_ms(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, k ? hq.rt_tex : blur.tex, 0, hq.samples);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, hq.rt_depth);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT, GL_RENDERBUFFER, hq.rt_depth);
    ok = ok && glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
  }
  if (!ok) { /* blur's back as render_blur_begin made it */
    glBindFramebuffer(GL_FRAMEBUFFER, blur.fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, blur.tex, 0);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, blur.depth);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT, GL_RENDERBUFFER, blur.depth);
  }
  fprintf(stderr, "render_hq: %s\n", ok ? "rendered to texture" : "no rendering to texture, blits");
  return ok;
}

static int hq_targets(int w, int h, GLint screen) {
  hq_free();
#ifndef WMMT_VK
  /* MSRT2 permits depth texture attachments but discards them at resolve.
   * Use core GLES3 blits for readable depth while keeping MSAA. */
  int need_depth = hq.opt_ao && hq.ssao > 0.0f && hq.ao_prog;
  hq.msrt = hq.msrt_available && !need_depth;
#endif
  if (hq.msrt && !msrt_targets(w, h)) {
    hq_free();
#ifndef WMMT_VK
    hq.msrt_available = 0;
#endif
    hq.msrt = 0;
  }
  if (hq.msrt) {
    int ok = 1;
    for (int i = 0, lw = w, lh = h; ok && i < HQ_LEVELS; ++i) {
      lw = lw / 2 > 1 ? lw / 2 : 1;
      lh = lh / 2 > 1 ? lh / 2 : 1;
      hq.w[i] = lw, hq.h[i] = lh;
      hq.tex[i] = hq_texture(lw, lh);
      hq.fbo[i] = hq_fbo(hq.tex[i]);
      ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    }
#ifndef WMMT_VK
    if (ok) ssao_targets(w, h);
#endif
    glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)screen);
    return ok;
  }
  glGenRenderbuffers(1, &hq.ms_color);
  glBindRenderbuffer(GL_RENDERBUFFER, hq.ms_color);
  hq.storage_ms(GL_RENDERBUFFER, hq.samples, HQ_FORMATS[hq.fmt].internal, w, h);
  glGenRenderbuffers(1, &hq.ms_depth);
  glBindRenderbuffer(GL_RENDERBUFFER, hq.ms_depth);
  hq.storage_ms(GL_RENDERBUFFER, hq.samples, GL_DEPTH24_STENCIL8_OES, w, h);
  glGenFramebuffers(1, &hq.ms_fbo);
  glBindFramebuffer(GL_FRAMEBUFFER, hq.ms_fbo);
  glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, hq.ms_color);
  glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, hq.ms_depth);
  glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT, GL_RENDERBUFFER, hq.ms_depth);
  int ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
  for (int i = 0, lw = w, lh = h; ok && i < HQ_LEVELS; ++i) {
    lw = lw / 2 > 1 ? lw / 2 : 1;
    lh = lh / 2 > 1 ? lh / 2 : 1;
    hq.w[i] = lw, hq.h[i] = lh;
    hq.tex[i] = hq_texture(lw, lh);
    hq.fbo[i] = hq_fbo(hq.tex[i]);
    ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
  }
#ifndef WMMT_VK
  if (ok) ssao_targets(w, h);
#endif
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)screen);
  return ok;
}

#endif /* reference resource graph */
static int msrt_off;
void render_hq_blits(void) { msrt_off = 1; }

#ifdef WMMT_NATIVE_VK
static void native_hq_programs_release(void) {
  for (int i = 0; i < 2; ++i) native_program_release(&hq.down_prog[i]);
  native_program_release(&hq.up_prog);
  for (int i = 3; i < 6; ++i) native_program_release(&blur_progs[i]);
}
#endif

int render_hq(int samples, float bloom) {
  frame_history_valid = 0;
  frame_sampler_off();
#ifdef WMMT_NATIVE_VK
  hq_free();
#endif
  hq.on = 0;
  if (samples <= 0) return 0;
#ifdef WMMT_NATIVE_VK
  GLint most = cinder_vk_sample_limit();
  if (most < 1) return 0;
  samples = samples < most ? samples : most;
  samples = samples >= 8 ? 8 : samples >= 4 ? 4 : samples >= 2 ? 2 : 1;
  hq.msrt = !msrt_off;
#else
#ifdef WMMT_EGL
  hq.blit = (hq_blit_fn)eglGetProcAddress("glBlitFramebuffer");
  hq.storage_ms = (hq_rbms_fn)eglGetProcAddress("glRenderbufferStorageMultisample");
  hq.invalidate = (hq_inval_fn)eglGetProcAddress("glInvalidateFramebuffer");
#endif
  if (!hq.blit || !hq.storage_ms) {
    fprintf(stderr, "render_hq: no GLES3 blit, as before\n");
    return 0;
  }
  const char *ext = (const char *)glGetString(GL_EXTENSIONS);
  hq.msrt = 0;
  if (!msrt_off && ext && strstr(ext, "GL_EXT_multisampled_render_to_texture")) {
#ifdef WMMT_EGL
    hq.tex_ms = (hq_tex_ms_fn)eglGetProcAddress("glFramebufferTexture2DMultisampleEXT");
    hq.storage_ms_ext = (hq_rbms_fn)eglGetProcAddress("glRenderbufferStorageMultisampleEXT");
#endif
    hq.msrt = hq.tex_ms && hq.storage_ms_ext;
  }
#ifndef WMMT_VK
  hq.msrt_available = hq.msrt;
#endif
  GLint most = 0;
  glGetIntegerv(GL_MAX_SAMPLES_, &most);
#endif
  hq.samples = hq.samples0 = samples < most ? samples : most;
  hq.bloom = hq.bloom0 = bloom;
  hq.scale = 1.0f;
  hq.level = 0;
  hq.opt_bloom = hq.opt_ao = hq.opt_paint = hq.opt_wet = 1;
  const char *attribs[] = { "aPos" };
#ifdef WMMT_NATIVE_VK
  native_hq_programs_release();
#endif
  for (int k = 0; k < 2; ++k) {
    char fs[2048];
    snprintf(fs, sizeof fs, "#define BRIGHT %d\n%s", k, FS_DOWN);
#ifdef WMMT_NATIVE_VK
    hq.down_prog[k] = native_program_create(VS_POST, fs, attribs, 1);
#else
    hq.down_prog[k] = gl_compile_program(VS_POST, fs, attribs, 1);
#endif
#ifdef WMMT_NATIVE_VK
    if (!hq.down_prog[k]) goto native_bad;
#else
    if (!hq.down_prog[k]) return 0;
#endif
#ifndef WMMT_NATIVE_VK
    glUseProgram(hq.down_prog[k]);
    glUniform1i(glGetUniformLocation(hq.down_prog[k], "uTex"), 0);
    hq.down_texel[k] = glGetUniformLocation(hq.down_prog[k], "uTexel");
#endif
  }
#ifndef WMMT_NATIVE_VK
  hq.down_thresh = glGetUniformLocation(hq.down_prog[1], "uThresh");
#endif
#ifdef WMMT_NATIVE_VK
  hq.up_prog = native_program_create(VS_POST, FS_UP, attribs, 1);
#else
  hq.up_prog = gl_compile_program(VS_POST, FS_UP, attribs, 1);
#endif
#ifdef WMMT_NATIVE_VK
    if (!hq.up_prog) goto native_bad;
#else
    if (!hq.up_prog) return 0;
#endif
#ifndef WMMT_NATIVE_VK
  glUseProgram(hq.up_prog);
  glUniform1i(glGetUniformLocation(hq.up_prog, "uTex"), 0);
  hq.up_texel = glGetUniformLocation(hq.up_prog, "uTexel");
#endif
  for (int k = 0; k < 3; ++k) {
    char vs[2048], fs[4096];
    snprintf(vs, sizeof vs, "#define BLUR_TAPS %d\n#define SHARPEN %d\n%s", k == 1 ? 8 : 1, k == 2, VS_BLUR);
    snprintf(fs, sizeof fs, "#define BLUR_TAPS %d\n#define SHARPEN %d\n#define HQ 1\n%s", k == 1 ? 8 : 1, k == 2, FS_BLUR);
    const char *battr[] = { "aPos", "aUV", "aAlpha" };
#ifdef WMMT_NATIVE_VK
    GLuint p = native_program_create(vs, fs, battr, 3);
#else
    GLuint p = gl_compile_program(vs, fs, battr, 3);
#endif
#ifdef WMMT_NATIVE_VK
    if (!p) goto native_bad;
#else
    if (!p) return 0;
#endif
    blur_progs[3 + k] = p;
#ifndef WMMT_NATIVE_VK
    glUseProgram(p);
    glUniform1i(glGetUniformLocation(p, "uTex"), 0);
    glUniform1i(glGetUniformLocation(p, "uBloom"), 1);
    glUniform1i(glGetUniformLocation(p, "uAO"), 2);
    bloom_k[k] = glGetUniformLocation(p, "uBloomK");
#endif
  }
#ifndef WMMT_NATIVE_VK
  sharp_texel[1] = glGetUniformLocation(blur_progs[5], "uTexel");
  sharp_amount[1] = glGetUniformLocation(blur_progs[5], "uSharp");
#endif
  /* the maps' programs again, with WET for the roads */
  for (int k = 0; k < 2; ++k) {
    static char fs[2][4096];
    snprintf(fs[k], sizeof fs[k], "#define WET 1\n%s", k ? FS_CUTOUT : FS);
    scene_prog np;
    if (prog_init(&np, fs[k]) == 0) {
#ifdef WMMT_NATIVE_VK
      cinder_vk_program_destroy(progs[k].id);
#else
      glDeleteProgram(progs[k].id);
#endif
      progs[k] = np;
    }
  }
  /* car.cg again, with the frame's reflection */
  frame_env = 1;
  lit_prog np;
  if (lit_init(&np, WPK_LIT_CAR, 0) == 0) { /* (its output is opaque: one for both, as render_init) */
#ifdef WMMT_NATIVE_VK
    cinder_vk_program_destroy(lit_progs[2 * WPK_LIT_CAR].id);
#else
    glDeleteProgram(lit_progs[2 * WPK_LIT_CAR].id);
#endif
    lit_progs[2 * WPK_LIT_CAR] = lit_progs[2 * WPK_LIT_CAR + 1] = np;
  } else {
    frame_env = 0;
  }
  hq.fmt = 0;
  hq.on = 1;
  fprintf(stderr, "render_hq: %dx MSAA (of %d), bloom %.2f\n", hq.samples, most, bloom);
  hq_said = 0;
  return 1;
#ifdef WMMT_NATIVE_VK
native_bad:
  native_hq_programs_release();
  return 0;
#endif
}

void render_ssao(float k) {
  hq.ssao = 0.0f;
  if (!hq.on || k <= 0.0f) return;
  const char *attribs[] = { "aPos" };
  if (
#ifdef WMMT_NATIVE_VK
      !cinder_vk_program_ready(hq.ao_prog) || !cinder_vk_program_ready(hq.ao_blur_prog)
#else
      !hq.ao_prog
#endif
  ) {
#ifdef WMMT_NATIVE_VK
    native_program_release(&hq.ao_prog);
    native_program_release(&hq.ao_blur_prog);
#endif
#ifdef WMMT_NATIVE_VK
    hq.ao_prog = native_program_create(VS_POST, FS_SSAO, attribs, 1);
#else
    hq.ao_prog = gl_compile_program(VS_POST, FS_SSAO, attribs, 1);
#endif
#ifdef WMMT_NATIVE_VK
    hq.ao_blur_prog = hq.ao_prog ? native_program_create(VS_POST, FS_AO_BLUR, attribs, 1) : 0;
#else
    hq.ao_blur_prog = hq.ao_prog ? gl_compile_program(VS_POST, FS_AO_BLUR, attribs, 1) : 0;
#endif
    if (!hq.ao_blur_prog
#ifdef WMMT_NATIVE_VK
        || !cinder_vk_program_ready(hq.ao_prog) || !cinder_vk_program_ready(hq.ao_blur_prog)
#elif defined(WMMT_VK)
        || !vkgl_program_usable(hq.ao_prog) || !vkgl_program_usable(hq.ao_blur_prog)
#endif
    ) {
#ifdef WMMT_NATIVE_VK
      if (hq.ao_prog) cinder_vk_program_destroy(hq.ao_prog);
#else
      if (hq.ao_prog) glDeleteProgram(hq.ao_prog);
#endif
#ifdef WMMT_NATIVE_VK
      if (hq.ao_blur_prog) cinder_vk_program_destroy(hq.ao_blur_prog);
#else
      if (hq.ao_blur_prog) glDeleteProgram(hq.ao_blur_prog);
#endif
      hq.ao_prog = hq.ao_blur_prog = 0;
      fprintf(stderr, "render_ssao: no program, off\n");
      return;
    }
#ifndef WMMT_NATIVE_VK
    glUseProgram(hq.ao_prog);
    glUniform1i(glGetUniformLocation(hq.ao_prog, "uTex"), 0);
    hq.ao_view = glGetUniformLocation(hq.ao_prog, "uView");
    hq.ao_texel = glGetUniformLocation(hq.ao_prog, "uTexel");
    hq.ao_k = glGetUniformLocation(hq.ao_prog, "uK");
    glUseProgram(hq.ao_blur_prog);
    glUniform1i(glGetUniformLocation(hq.ao_blur_prog, "uTex"), 0);
    hq.ao_blur_texel = glGetUniformLocation(hq.ao_blur_prog, "uTexel");
#endif
  }
  hq.ssao = k;
#ifdef WMMT_NATIVE_VK
  native_graph_dirty = 1; /* retain committed extents until the replacement succeeds */
#else
  blur.w = blur.h = 0; /* the targets again, with the occlusion's */
#endif
}

/* the levels' frame scale, samples (0 as asked), bloom (as asked or none), occlusion, the
 * last frame's reflections */
static const struct { float scale; int samples, bloom, ao, env; } HQ_LEVEL[HQ_LEVELS_N] = {
  { 1.0f, 0, 1, 1, 1 },   { 1.0f, 0, 1, 0, 1 },   { 0.9f, 0, 1, 0, 1 },   { 0.84f, 0, 1, 0, 1 },
  { 0.84f, 2, 1, 0, 1 },  { 0.75f, 2, 1, 0, 1 },  { 0.75f, 2, 0, 0, 1 },  { 0.75f, 2, 0, 0, 0 },
};

#if defined(WMMT_VK) && !defined(WMMT_NATIVE_VK)
/* Build the optional pair without destroying the working MSAA targets or last frame.
 * A failed attempt is not retried until targets are recreated (resize/format change). */
static void vk_single_targets(int w, int h) {
  GLint fb;
  hq.single_attempted = 1;
  /* The existing MSRT depth texture, if any, belongs to the baseline path. */
  if (hq.z_tex || !vkgl_ssao_depth_supported(w, h)) return;
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fb);
  /* Never overwrite the previous-frame sampler on FRAME_UNIT. */
  glActiveTexture(GL_TEXTURE0);
  /* Isolate errors caused by this optional allocation from earlier scene errors. */
  GLenum prior = glGetError();
  if (prior != GL_NO_ERROR) fprintf(stderr, "render_ssao: prior GL error 0x%x\n", prior);
  hq.z_tex = z_texture(w, h);
  if (!hq.msrt) {
    hq.rt_tex = hq_texture(w, h);
    hq.rt_fbo = hq_fbo(hq.rt_tex);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, blur.depth);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT, GL_RENDERBUFFER, blur.depth);
  }
  int ok = hq.z_tex && hq.rt_tex && hq.rt_fbo;
  if (!hq.msrt && glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) ok = 0;
  glGenFramebuffers(2, hq.single_fbo);
  if (!hq.single_fbo[0] || !hq.single_fbo[1]) ok = 0;
  for (int i = 0; i < 2; ++i) {
    glBindFramebuffer(GL_FRAMEBUFFER, hq.single_fbo[i]);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, i ? hq.rt_tex : blur.tex, 0);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT_, GL_TEXTURE_2D, hq.z_tex, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) ok = 0;
  }
  if (glGetError() != GL_NO_ERROR) ok = 0;
  if (ok) {
    hq.single_ready = 1; /* ssao_targets uses the already attached texture */
    ssao_targets(w, h);
    if (!hq.ssao_ok || glGetError() != GL_NO_ERROR) ok = 0;
  }
  if (!ok) {
    for (int i = 0; i < 2; ++i) {
      if (hq.single_fbo[i]) glDeleteFramebuffers(1, &hq.single_fbo[i]);
      hq.single_fbo[i] = 0;
    }
    if (!hq.msrt) {
      if (hq.rt_fbo) glDeleteFramebuffers(1, &hq.rt_fbo);
      if (hq.rt_tex) glDeleteTextures(1, &hq.rt_tex);
      hq.rt_fbo = hq.rt_tex = 0;
    }
    if (hq.z_tex) glDeleteTextures(1, &hq.z_tex);
    for (int i = 0; i < 2; ++i) {
      if (hq.ao_fbo[i]) glDeleteFramebuffers(1, &hq.ao_fbo[i]);
      if (hq.ao_tex[i]) glDeleteTextures(1, &hq.ao_tex[i]);
      hq.ao_fbo[i] = hq.ao_tex[i] = 0;
    }
    hq.z_tex = 0;
    hq.single_ready = hq.ssao_ok = 0;
    fprintf(stderr, "render_ssao: single-sample targets unavailable; MSAA retained\n");
  }
  glBindTexture(GL_TEXTURE_2D, 0);
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)fb);
}
#endif

int render_hq_level(int level) {
  if (!hq.on) return 0;
  level = level < 0 ? 0 : level >= HQ_LEVELS_N ? HQ_LEVELS_N - 1 : level;
  hq.level = level;
  int samples = HQ_LEVEL[level].samples && HQ_LEVEL[level].samples < hq.samples0 ? HQ_LEVEL[level].samples : hq.samples0;
  if (samples != hq.samples || HQ_LEVEL[level].scale != hq.scale) {
    hq.samples = samples;
    hq.scale = HQ_LEVEL[level].scale;
#ifdef WMMT_NATIVE_VK
    native_graph_dirty = 1;
#else
    blur.w = blur.h = 0; /* the targets again, at the new size */
#endif
  }
  hq.bloom = HQ_LEVEL[level].bloom && hq.opt_bloom ? hq.bloom0 : 0.0f;
  return level;
}

void render_hq_options(int bloom, int ao, int paint, int wet) {
#ifndef WMMT_VK
  if (ao != hq.opt_ao && hq.ssao > 0.0f) blur.w = blur.h = 0;
#endif
  hq.opt_bloom = bloom, hq.opt_ao = ao, hq.opt_paint = paint, hq.opt_wet = wet;
  render_hq_level(hq.level);
}

void render_hq_view(float near, float far, float tan_x, float tan_y) {
  hq.view[0] = near, hq.view[1] = far, hq.view[2] = tan_x, hq.view[3] = tan_y;
  hq.view_set = 1;
}

#include "render_native_post.inc"

#ifndef WMMT_NATIVE_VK
/* Reference path: uniforms and blend state are authored by the callers below. */
/* a full-screen pass of prog into fbo's w x h, from tex */
static void hq_pass(GLuint prog, GLuint fbo, int w, int h, GLuint tex) {
  static const float quad[] = { -1, -1, 1, -1, -1, 1, 1, 1 };
  glBindFramebuffer(GL_FRAMEBUFFER, fbo);
  glViewport(0, 0, w, h);
  glUseProgram(prog);
  glBindTexture(GL_TEXTURE_2D, tex);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, quad);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}
#endif

/* the frame resolved into blur.tex, and the bloom's levels from it, the result in tex[0] */
static int hq_resolve_bloom(void) {
#ifdef WMMT_NATIVE_VK
  return native_hq_resolve_bloom();
#else
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
  int history_ok = !cinder_vk_error_pending();
#else
  int history_ok = !vkgl_error_pending();
#endif
#else
  int history_ok = 1;
#endif
  if (!hq_said) {
    static const char *names[3] = { "R11G11B10F", "RGBA16F", "RGBA8" };
    fprintf(stderr, "render_hq: %dx%d in %s\n", blur.w, blur.h, names[hq.fmt]);
    hq_said = 1;
  }
  int ao = hq.ssao_ok && hq.view_set && HQ_LEVEL[hq.level].ao && hq.opt_ao;
#ifdef WMMT_VK
  ao = ao && hq.single_frame;
  int direct = hq.msrt || hq.single_frame;
#else
  int direct = hq.msrt;
#endif
  if (!direct) {
    glBindFramebuffer(GL_READ_FRAMEBUFFER_, hq.ms_fbo);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER_, blur.fbo);
    hq.blit(0, 0, blur.w, blur.h, 0, 0, blur.w, blur.h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
    if (cinder_vk_error_pending()) history_ok = 0;
#else
    if (vkgl_error_pending()) history_ok = 0;
#endif
#endif
  }
  if (ao && !direct) {
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER_, hq.z_fbo);
    hq.blit(0, 0, blur.w, blur.h, 0, 0, blur.w, blur.h, GL_DEPTH_BUFFER_BIT, GL_NEAREST);
#ifndef WMMT_VK
    GLenum error = glGetError();
    if (error != GL_NO_ERROR) {
      ao = hq.ssao_ok = 0;
      fprintf(stderr, "render_ssao: depth resolve error 0x%x, off\n", error);
    }
#endif
  }
  if (hq.invalidate && !direct) {
    const GLenum all[] = { GL_COLOR_ATTACHMENT0, GL_DEPTH_ATTACHMENT, GL_STENCIL_ATTACHMENT };
    glBindFramebuffer(GL_FRAMEBUFFER, hq.ms_fbo);
    hq.invalidate(GL_FRAMEBUFFER, 3, all);
  }
  glBindVertexArrayOES(0);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glDisable(GL_BLEND);
  glActiveTexture(GL_TEXTURE0);
  glEnableVertexAttribArray(0);
#ifdef WMMT_VK
  if (ao) {
    GLenum prior = glGetError();
    if (prior != GL_NO_ERROR) fprintf(stderr, "render_ssao: prior GL error 0x%x\n", prior);
    int complete = 1;
    for (int i = 0; i < 2; ++i) {
      glBindFramebuffer(GL_FRAMEBUFFER, hq.ao_fbo[i]);
      if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) complete = 0;
    }
    GLenum error = glGetError();
    if (!complete || error != GL_NO_ERROR) {
      ao = 0;
      hq.single_ready = 0;
      fprintf(stderr, "render_ssao: AO framebuffer failed; returning to MSAA\n");
    }
  }
#endif
  if (ao) {
    glUseProgram(hq.ao_prog);
    glUniform4fv(hq.ao_view, 1, hq.view);
    glUniform2f(hq.ao_texel, 1.0f / (float)blur.w, 1.0f / (float)blur.h);
    glUniform1f(hq.ao_k, hq.ssao);
    hq_pass(hq.ao_prog, hq.ao_fbo[0], hq.aw, hq.ah, hq.z_tex);
    glUseProgram(hq.ao_blur_prog);
    glUniform2f(hq.ao_blur_texel, 1.0f / (float)hq.aw, 1.0f / (float)hq.ah);
    hq_pass(hq.ao_blur_prog, hq.ao_fbo[1], hq.aw, hq.ah, hq.ao_tex[0]);
#ifdef WMMT_VK
    if (glGetError() != GL_NO_ERROR) {
      /* Keep this frame's colour; do not composite a failed AO result. */
      ao = 0;
      hq.single_ready = 0;
      fprintf(stderr, "render_ssao: pass failed; returning to MSAA\n");
    }
#endif
  }
  hq.ao_on = ao;
  if (hq.bloom <= 0.0f) return history_ok;
  /* down: the bright pass into the half size, then each level a half of the one above */
  for (int i = 0; i < HQ_LEVELS; ++i) {
    int src_w = i ? hq.w[i - 1] : blur.w, src_h = i ? hq.h[i - 1] : blur.h;
    GLuint prog = hq.down_prog[i == 0];
    glUseProgram(prog);
    if (!i) glUniform1f(hq.down_thresh, 0.75f);
    glUniform2f(hq.down_texel[i == 0], 1.0f / (float)src_w, 1.0f / (float)src_h);
    hq_pass(prog, hq.fbo[i], hq.w[i], hq.h[i], i ? hq.tex[i - 1] : blur.tex);
  }
  /* up: each level's tent added to the one above it */
  GLint bsrc, bdst;
  glGetIntegerv(GL_BLEND_SRC_RGB, &bsrc);
  glGetIntegerv(GL_BLEND_DST_RGB, &bdst);
  glEnable(GL_BLEND);
  glBlendFunc(GL_ONE, GL_ONE);
  glUseProgram(hq.up_prog);
  for (int i = HQ_LEVELS - 1; i > 0; --i) {
    glUniform2f(hq.up_texel, 1.0f / (float)hq.w[i], 1.0f / (float)hq.h[i]);
    hq_pass(hq.up_prog, hq.fbo[i - 1], hq.w[i - 1], hq.h[i - 1], hq.tex[i]);
  }
  glDisable(GL_BLEND);
  glBlendFunc((GLenum)bsrc, (GLenum)bdst);
  return history_ok;
#endif
}

static int sharp_deep;
void render_sharpen(float sharp, int deep) {
  blur.sharp = sharp;
  sharp_deep = deep || sharp > 0.0f;
}

static int render_blur_begin_inner(float amount, int w, int h) {
  frame_sampler_off();
  if (amount <= 0.0f && blur.sharp <= 0.0f && !hq.on) return 0;
  blur.out_w = w, blur.out_h = h;
  if (hq.on && hq.scale < 1.0f) { /* (even sizes: the half size ones exact) */
    w = (int)((float)w * hq.scale) & ~1;
    h = (int)((float)h * hq.scale) & ~1;
  }
  int deep = sharp_deep || hq.on ? 1 + hq.on : 0; /* 2: render_hq's format (HQ_FORMATS) */
#ifdef WMMT_NATIVE_VK
  if (w <= 0 || h <= 0) { frame_history_valid = 0; return 0; }
  if (native_graph_dirty || blur.w != w || blur.h != h || blur.deep != deep || !cinder_vk_target_ready(blur.fbo) ||
      (hq.on && (native_graph_samples != hq.samples || native_graph_fmt != hq.fmt))) {
    int made = 0;
    if (hq.on) for (int fmt = hq.fmt; fmt < 3 && !made; ++fmt)
      made = native_blur_allocate(w, h, deep, 1, fmt, hq.samples, hq.msrt);
    else made = native_blur_allocate(w, h, deep, 0, hq.fmt, 1, 0);
    if (!made && hq.on) {
      /* All native HDR formats failed. The fallback is itself transactional. */
      if (amount > 0.0f || blur.sharp > 0.0f) {
        w = blur.out_w; h = blur.out_h;
        deep = sharp_deep ? 1 : 0;
        made = native_blur_allocate(w, h, deep, 0, 2, 1, 0);
      } else { hq_free(); hq.on = 0; }
    }
    if (!made) { frame_history_valid = 0; frame_sampler_off(); return 0; }
  }
#else
  if (blur.w != w || blur.h != h || (blur.w > 0 && blur.deep != deep)) {
    frame_history_valid = 0;
    if (blur.fbo) {
      glDeleteFramebuffers(1, &blur.fbo);
      glDeleteTextures(1, &blur.tex);
      glDeleteRenderbuffers(1, &blur.depth);
    }
    glGenTextures(1, &blur.tex);
    glBindTexture(GL_TEXTURE_2D, blur.tex);
    /* 16 bits: half the memory traffic of the frame's store and the blur's reads */
    if (deep == 2) hq_tex_image(w, h); /* the resolve's: as the multisampled one */
    else if (deep) glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    else glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, w, h, 0, GL_RGB, GL_UNSIGNED_SHORT_5_6_5, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenRenderbuffers(1, &blur.depth);
    glBindRenderbuffer(GL_RENDERBUFFER, blur.depth);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8_OES, w, h);
#ifdef WMMT_NATIVE_VK
    blur.screen = (GLint)native_scene.target;
#else
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &blur.screen);
#endif
    glGenFramebuffers(1, &blur.fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, blur.fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, blur.tex, 0);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, blur.depth);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT, GL_RENDERBUFFER, blur.depth);
    int ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)blur.screen);
    if (hq.on && (!ok || !hq_targets(w, h, blur.screen))) {
      hq_free();
      if (++hq.fmt >= 3) {
        fprintf(stderr, "render_hq: no %dx%d multisampled targets, as before\n", w, h);
        hq.on = 0;
      }
      blur.w = blur.h = 0; /* again, in the next format or without */
      glDeleteFramebuffers(1, &blur.fbo);
      glDeleteTextures(1, &blur.tex);
      glDeleteRenderbuffers(1, &blur.depth);
      blur.fbo = blur.tex = blur.depth = 0;
      return render_blur_begin_inner(amount, blur.out_w, blur.out_h);
    }
    if (!ok) {
      fprintf(stderr, "radial blur: no %dx%d framebuffer\n", w, h);
      blur.w = blur.h = -1; /* do not try again */
      frame_sampler_off();
      return 0;
    }
    blur.w = w;
    blur.h = h;
    blur.deep = deep;
  }
#endif
  if (blur.w <= 0) { frame_sampler_off(); return 0; }
#ifdef WMMT_NATIVE_VK
  blur.screen = (GLint)native_scene.target;
#else
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &blur.screen);
#endif
#ifdef WMMT_VK
  hq.single_frame = 0;
  if (hq.on && hq.ssao > 0.0f && hq.ao_prog && hq.ao_blur_prog && hq.opt_ao && HQ_LEVEL[hq.level].ao) {
    if (!hq.single_attempted) vk_single_targets(w, h);
    hq.single_frame = hq.single_ready;
  }
  if (hq.single_frame) {
#ifdef WMMT_NATIVE_VK
    if (!cinder_vk_target_ready(hq.single_fbo[1])) hq.single_frame = hq.single_ready = 0;
#else
    GLenum prior = glGetError();
    if (prior != GL_NO_ERROR) fprintf(stderr, "render_ssao: prior GL error 0x%x\n", prior);
    glBindFramebuffer(GL_FRAMEBUFFER, hq.single_fbo[1]);
    int complete = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    GLenum error = glGetError();
    if (!complete || error != GL_NO_ERROR) {
      hq.single_frame = hq.single_ready = 0;
      fprintf(stderr, "render_ssao: scene framebuffer failed; returning to MSAA\n");
    }
#endif
  }
#ifdef WMMT_NATIVE_VK
  if (!native_hq_copy_ready()) {
    /* The shared resource bridge's raw MSAA RBO may not be transfer-capable.
     * Decide before scene recording; ordinary blur/direct rendering must receive
     * the scene, never a stale resolve texture. Preserve the outer error epoch. */
    fprintf(stderr, "render_hq: native MSAA target cannot transfer; ordinary blur retained\n");
    hq_free();
    hq.on = 0;
    blur.w = blur.h = 0;
    native_bloom_ready = 0;
    return render_blur_begin_inner(amount, blur.out_w, blur.out_h);
  }
#endif
#ifndef WMMT_NATIVE_VK
  glBindFramebuffer(GL_FRAMEBUFFER, !hq.on ? blur.fbo : hq.single_frame ? hq.single_fbo[1] : hq.msrt ? hq.rt_fbo : hq.ms_fbo);
#endif
#else
  glBindFramebuffer(GL_FRAMEBUFFER, !hq.on ? blur.fbo : hq.msrt ? hq.rt_fbo : hq.ms_fbo);
#endif
#ifdef WMMT_NATIVE_VK
  /* Expected constructor/format/optional-SSAO failures precede scene recording.
   * Rebase only here; unknown completion remains pending and cannot be trusted. */
  frame_start_epoch = cinder_vk_error_epoch();
  frame_recording_trusted = frame_start_epoch != UINT64_MAX && !cinder_vk_error_pending();
#endif
  blur.amount = amount > 1.0f ? 1.0f : amount < 0.0f ? 0.0f : amount;
  /* Rebind only a completed earlier frame, never the attached scene texture. */
  GLuint scene_tex = 0;
#ifdef WMMT_VK
  if (hq.single_frame) scene_tex = hq.rt_tex;
#endif
  if (hq.msrt) scene_tex = hq.rt_tex;
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
  if (cinder_vk_error_pending() || cinder_vk_error_epoch() == UINT64_MAX || cinder_vk_error_epoch() != frame_start_epoch)
#else
  if (vkgl_error_pending() || vkgl_error_epoch() == UINT64_MAX || vkgl_error_epoch() != frame_start_epoch)
#endif
    frame_recording_trusted = frame_history_valid = 0;
#endif
  if (hq.on && frame_env && frame_history_valid && blur.tex && blur.tex != scene_tex &&
      HQ_LEVEL[hq.level].env && (hq.opt_paint || hq.opt_wet)) {
    frame_sampler(blur.tex);
    frame_k = hq.opt_paint ? 0.9f : 0.0f;
    frame_wet = hq.opt_wet;
  } else {
    /* The allocation path may have rebound unit 5 if it was previously active. */
    frame_sampler_off();
  }
  return 1;
}

int render_blur_begin(float amount, int w, int h) {
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
  frame_start_epoch = cinder_vk_error_epoch();
#else
  frame_start_epoch = vkgl_error_epoch();
#endif
#ifdef WMMT_NATIVE_VK
  frame_recording_trusted = frame_start_epoch != UINT64_MAX && !cinder_vk_error_pending();
#else
  frame_recording_trusted = frame_start_epoch != UINT64_MAX && !vkgl_error_pending();
#endif
  if (frame_history_valid && (!frame_recording_trusted || frame_history_epoch != frame_start_epoch))
    frame_history_valid = 0;
#endif
  int active = render_blur_begin_inner(amount, w, h);
#ifdef WMMT_NATIVE_VK
  /* Scene target is selected by this pass, never inferred from GL bindings. */
  native_scene = (native_scene_view){0, w, h};
  if (active) native_scene = (native_scene_view){!hq.on ? blur.fbo : hq.single_frame ? hq.single_fbo[1] :
      hq.msrt ? hq.rt_fbo : hq.ms_fbo, blur.w, blur.h};
#endif
  return active;
}

void render_blur_size(int *w, int *h) {
  *w = blur.w, *h = blur.h;
}

void render_blur_end(void) {
  int history_ok = 1;
#ifdef WMMT_NATIVE_VK
  uint32_t scene_target = native_scene.target;
  native_scene = (native_scene_view){(uint32_t)blur.screen, blur.out_w, blur.out_h};
#endif
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
  if (!frame_recording_trusted || cinder_vk_error_pending() || cinder_vk_error_epoch() == UINT64_MAX ||
#else
  if (!frame_recording_trusted || vkgl_error_pending() || vkgl_error_epoch() == UINT64_MAX ||
#endif
#ifdef WMMT_NATIVE_VK
      cinder_vk_error_epoch() != frame_start_epoch) history_ok = 0;
#else
      vkgl_error_epoch() != frame_start_epoch) history_ok = 0;
#endif
#endif
  frame_sampler_off();
#if defined(__APPLE__) && !defined(WMMT_NATIVE_VK)
#ifdef WMMT_VK
  if (!hq.single_frame)
#endif
  {
    const GLenum discard[] = { GL_DEPTH_ATTACHMENT, GL_STENCIL_ATTACHMENT };
    glDiscardFramebufferEXT(GL_FRAMEBUFFER, 2, discard);
  }
#endif
  frame_k = 0;
  frame_wet = 0;
#if defined(WMMT_VK) && !defined(WMMT_NATIVE_VK)
  if (hq.single_frame) {
    GLenum error = glGetError();
    if (error != GL_NO_ERROR) {
      /* Preserve the colour already drawn, but do not consume suspect depth. */
      hq.ssao_ok = hq.single_ready = 0;
      history_ok = 0;
      fprintf(stderr, "render_ssao: scene GL error 0x%x; returning to MSAA\n", error);
    }
  }
#endif
  if (hq.on && (hq.msrt
#ifdef WMMT_VK
                || hq.single_frame
#endif
                )) {
    /* the depth not stored (unless it is render_ssao's), then this frame's texture blur's */
    if (hq.invalidate && hq.rt_depth
#ifdef WMMT_VK
        && !hq.single_frame
#endif
    ) {
#ifdef WMMT_NATIVE_VK
      if (!cinder_vk_discard(scene_target, VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT)) history_ok = 0;
#else
      const GLenum ds[] = { GL_DEPTH_ATTACHMENT, GL_STENCIL_ATTACHMENT };
      hq.invalidate(GL_FRAMEBUFFER, 2, ds);
#endif
    }
    GLuint t = blur.tex, f = blur.fbo;
    blur.tex = hq.rt_tex, blur.fbo = hq.rt_fbo;
    hq.rt_tex = t, hq.rt_fbo = f;
#ifdef WMMT_VK
    GLuint sf = hq.single_fbo[0];
    hq.single_fbo[0] = hq.single_fbo[1];
    hq.single_fbo[1] = sf;
#endif
  }
  if (hq.on && !hq_resolve_bloom()) history_ok = 0;
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
  if (cinder_vk_error_pending() || cinder_vk_error_epoch() == UINT64_MAX || cinder_vk_error_epoch() != frame_start_epoch)
#else
  if (vkgl_error_pending() || vkgl_error_epoch() == UINT64_MAX || vkgl_error_epoch() != frame_start_epoch)
#endif
    history_ok = 0;
#endif
  /* Recording is not a proof of asynchronous GPU completion. */
  frame_history_valid = hq.on && history_ok;
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
  if (frame_history_valid) frame_history_epoch = cinder_vk_error_epoch();
#else
  if (frame_history_valid) frame_history_epoch = vkgl_error_epoch();
#endif
#endif
  hq.view_set = 0; /* each frame's own (the menus' 3D has none) */
#ifdef WMMT_NATIVE_VK
  if (!native_post_clear((uint32_t)blur.screen, native_post_clear_color)) frame_history_valid = 0;
#else
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)blur.screen);
  glViewport(0, 0, blur.out_w, blur.out_h);
  /* the composite covers the screen: a clear spares the tiler loading last frame's buffers */
  GLboolean depth_mask;
  glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_mask);
  glDepthMask(GL_TRUE);
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
  glDepthMask(depth_mask);
#endif
  /* clRadialBlur::setupPosition on the arcade's 640 x 480 screen, in clip space: the bands
   * are 239 pixels wide and slide in from outside the screen as the blur grows (240 pixels
   * per unit), their texture with them, so the frame stays where it is */
  float a = blur.amount, shift = 0.75f * (a - 1.0f);
  float lo = -1.0f + shift, li = shift - 81.0f / 320.0f; /* left band: outer, inner edge */
  float ri = -shift + 0.25f, ro = -shift + 319.0f / 320.0f;
  /* x, y, u, v, alpha */
  const float mid[] = { li, -1, 0, 0, 0, ri, -1, 0, 0, 0, ri, 1, 0, 0, 0, li, 1, 0, 0, 0 };
  const float band[] = { lo, -1, 0, 0, 1, li, -1, 0, 0, 0, li, 1, 0, 0, 0, lo, 1, 0, 0, 1,
                         ri, -1, 0, 0, 0, ro, -1, 0, 0, 1, ro, 1, 0, 0, 1, ri, 1, 0, 0, 0 };
  static const uint16_t idx[] = { 0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7 };
  float v[40];
#ifndef WMMT_NATIVE_VK
  glBindVertexArrayOES(0);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glDisable(GL_BLEND);
  if (hq.on) {
    glActiveTexture(GL_TEXTURE1);
    glBindTexture(GL_TEXTURE_2D, hq.bloom > 0.0f ? hq.tex[0] : blur.tex);
    glActiveTexture(GL_TEXTURE2);
    glBindTexture(GL_TEXTURE_2D, hq.ao_on ? hq.ao_tex[1] : white_tex);
  }
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, blur.tex);
#endif
  for (int k = 0; k < 2; ++k) {
    const float *src = k ? band : mid;
    int n = k ? 8 : 4;
    for (int i = 0; i < n; ++i) {
      memcpy(v + 5 * i, src + 5 * i, 5 * sizeof *v);
      v[5 * i + 2] = (src[5 * i] + 1.0f) * 0.5f; /* the frame 1:1 */
      v[5 * i + 3] = (src[5 * i + 1] + 1.0f) * 0.5f;
    }
#ifdef WMMT_NATIVE_VK
    if (!native_final_composite(v, (size_t)n * 5 * sizeof *v, idx, k)) frame_history_valid = 0;
#else
    int q = hq.on ? 3 : 0;
    if (!k && blur.sharp > 0.0f) {
      glUseProgram(blur_progs[q + 2]);
      glUniform2f(sharp_texel[q / 3], 1.0f / (float)blur.w, 1.0f / (float)blur.h);
      glUniform1f(sharp_amount[q / 3], blur.sharp);
      if (q) glUniform1f(bloom_k[2], hq.bloom);
    } else {
      glUseProgram(blur_progs[q + k]);
      if (q) glUniform1f(bloom_k[k], hq.bloom);
    }
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 5 * sizeof *v, v);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 5 * sizeof *v, v + 2);
    glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, 5 * sizeof *v, v + 4);
    glDrawElements(GL_TRIANGLES, k ? 12 : 6, GL_UNSIGNED_SHORT, idx);
#endif
  }
#ifndef WMMT_NATIVE_VK
  glEnable(GL_DEPTH_TEST);
  glEnable(GL_CULL_FACE);
#endif
}

void render_blend_pass(int on) {
#ifndef WMMT_NATIVE_VK
  if (on) {
    glEnable(GL_BLEND);
    glDepthMask(GL_FALSE);
  } else {
    glDisable(GL_BLEND);
    glDepthMask(GL_TRUE);
  }
#else
  /* WPK kind/effect/post packets already author blend and depth write. This
   * legacy scheduling hook must not create a second inherited native state. */
  (void)on;
#endif
}

#include "render_native_effects.inc"

static void sprites(const mat4 *proj, const render_vertex *v, int n_quads, uint32_t tex, render_params *p, GLenum src) {
  static uint16_t idx[6 * RENDER_MAX_SPRITES];
  if (!idx[1])
    for (int i = 0; i < RENDER_MAX_SPRITES; ++i) {
      uint16_t b = (uint16_t)(4 * i);
      uint16_t *q = idx + 6 * i;
      q[0] = b, q[1] = b + 1, q[2] = b + 2, q[3] = b, q[4] = b + 2, q[5] = b + 3;
    }
  if (n_quads > RENDER_MAX_SPRITES) n_quads = RENDER_MAX_SPRITES;
  if (n_quads <= 0) return;
#ifdef WMMT_NATIVE_VK
  if (native_effect_quads(proj, v, n_quads, tex, idx, src == GL_SRC_COLOR, 0, p)) ++p->draws;
#else
  const scene_prog *pr = &progs[0];
  glUseProgram(pr->id);
  glUniformMatrix4fv(pr->mvp, 1, GL_FALSE, proj->m);
  glUniform3f(pr->eye, 0, 0, 0);
  glUniform2f(pr->fog, 1e9f, 1e8f);
  glUniform2f(pr->uv_off, 0, 0);
  glUniform3f(pr->grade, 1.0f, 1.0f, 1.0f); /* (the lamps, sparks and mirror as they are) */
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendFunc(src, GL_ONE);
  glDepthMask(GL_FALSE);
  glBindTexture(GL_TEXTURE_2D, tex);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof *v, v->pos);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof *v, v->uv);
  glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof *v, v->rgba);
  glDrawElements(GL_TRIANGLES, (GLsizei)n_quads * 6, GL_UNSIGNED_SHORT, idx);
  glEnable(GL_CULL_FACE);
  glUniform2f(pr->fog, p->fog_far, p->fog_near);
  if (enhance_on) { float grade[3]; enhance_grade(p, 0, grade); glUniform3fv(pr->grade, 1, grade); }
  else if (p->grade[0] > 0.0f) glUniform3fv(pr->grade, 1, p->grade);
  p->draws++;
#endif
}

void render_sprites(const mat4 *proj, const render_vertex *v, int n_quads, uint32_t tex, render_params *p) {
  sprites(proj, v, n_quads, tex, p, GL_SRC_ALPHA);
}

void render_sprites_by_colour(const mat4 *proj, const render_vertex *v, int n_quads, uint32_t tex, render_params *p) {
  sprites(proj, v, n_quads, tex, p, GL_SRC_COLOR);
}

/* ---- isolated, float-colour tail trail drawing ---- */
/* Keep the exact scene VS/FS and attribute list: vkgl hashes their text, so a
 * private program reuses the shipped SPIR-V without sharing uniform storage.
 * A private VAO avoids overwriting the caller's pointers/enables/EBO; a VBO
 * avoids ES3 client arrays and keeps deferred Vulkan draws independent of the
 * temporary CPU conversion below. Never change generic attributes (not VAO state). */
static struct {
  scene_prog program;
  GLuint vao, vbo;
  int failed;
} tail_render;

typedef struct { float pos[3], uv[2], rgba[4]; } tail_render_vertex;

void render_tail_context_lost(void) { memset(&tail_render, 0, sizeof tail_render); }

void render_tail_release(void) {
#ifndef WMMT_NATIVE_VK
  if (tail_render.vao) glDeleteVertexArraysOES(1, &tail_render.vao);
  if (tail_render.vbo) glDeleteBuffers(1, &tail_render.vbo);
#endif
#ifdef WMMT_NATIVE_VK
  if (tail_render.program.id) cinder_vk_program_destroy(tail_render.program.id);
#else
  if (tail_render.program.id) glDeleteProgram(tail_render.program.id);
#endif
  render_tail_context_lost();
}

static int tail_render_prepare(void) {
  if (tail_render.failed) return 0;
#ifdef WMMT_NATIVE_VK
  if (cinder_vk_program_ready(tail_render.program.id)) return 1;
  native_program_release(&tail_render.program.id);
#else
  if (tail_render.program.id && tail_render.vao && tail_render.vbo) return 1;
#endif
  if (prog_init(&tail_render.program, FS)) goto bad;
#if defined(WMMT_VK) && !defined(WMMT_NATIVE_VK)
  /* A missing SPIR-V still returns a nonzero program name. */
  if (!vkgl_program_usable(tail_render.program.id)) goto bad;
#endif
#ifndef WMMT_NATIVE_VK
  const scene_prog *pr = &tail_render.program;
  if (pr->mvp < 0 || pr->eye < 0 || pr->fog < 0 || pr->fog_color < 0 ||
      pr->tex < 0 || pr->uv_off < 0 || pr->grade < 0) goto bad;
#endif
#ifndef WMMT_NATIVE_VK
  glGenVertexArraysOES(1, &tail_render.vao);
  glGenBuffers(1, &tail_render.vbo);
  if (!tail_render.vao || !tail_render.vbo) goto bad;
#endif
  return 1;
bad:
  render_tail_release();
  tail_render.failed = 1; /* No allocation/compile storm; explicit release/loss retries. */
  return 0;
}

#ifndef WMMT_VK
typedef struct {
  GLint program, array, vao, active, texture;
  GLint src_rgb, dst_rgb, src_a, dst_a, eq_rgb, eq_a, depth_func;
  GLboolean blend, depth, cull, stencil, depth_write, colour[4];
} tail_render_gl_state;

static void tail_render_gl_save(tail_render_gl_state *s) {
  glGetIntegerv(GL_CURRENT_PROGRAM, &s->program);
  glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &s->array);
  glGetIntegerv(GL_VERTEX_ARRAY_BINDING_OES, &s->vao);
  glGetIntegerv(GL_ACTIVE_TEXTURE, &s->active);
  glActiveTexture(GL_TEXTURE0);
  glGetIntegerv(GL_TEXTURE_BINDING_2D, &s->texture);
  glActiveTexture((GLenum)s->active);
  glGetIntegerv(GL_BLEND_SRC_RGB, &s->src_rgb); glGetIntegerv(GL_BLEND_DST_RGB, &s->dst_rgb);
  glGetIntegerv(GL_BLEND_SRC_ALPHA, &s->src_a); glGetIntegerv(GL_BLEND_DST_ALPHA, &s->dst_a);
  glGetIntegerv(GL_BLEND_EQUATION_RGB, &s->eq_rgb); glGetIntegerv(GL_BLEND_EQUATION_ALPHA, &s->eq_a);
  glGetIntegerv(GL_DEPTH_FUNC, &s->depth_func);
  s->blend = glIsEnabled(GL_BLEND); s->depth = glIsEnabled(GL_DEPTH_TEST);
  s->cull = glIsEnabled(GL_CULL_FACE); s->stencil = glIsEnabled(GL_STENCIL_TEST);
  glGetBooleanv(GL_DEPTH_WRITEMASK, &s->depth_write);
  glGetBooleanv(GL_COLOR_WRITEMASK, s->colour);
}

static void tail_render_gl_restore(const tail_render_gl_state *s) {
  glBindVertexArrayOES((GLuint)s->vao); /* Restores its EBO and attribute layout too. */
  glBindBuffer(GL_ARRAY_BUFFER, (GLuint)s->array);
  glBlendEquationSeparate((GLenum)s->eq_rgb, (GLenum)s->eq_a);
  glBlendFuncSeparate((GLenum)s->src_rgb, (GLenum)s->dst_rgb, (GLenum)s->src_a, (GLenum)s->dst_a);
  if (s->blend) glEnable(GL_BLEND); else glDisable(GL_BLEND);
  if (s->depth) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
  if (s->cull) glEnable(GL_CULL_FACE); else glDisable(GL_CULL_FACE);
  if (s->stencil) glEnable(GL_STENCIL_TEST); else glDisable(GL_STENCIL_TEST);
  glDepthFunc((GLenum)s->depth_func); glDepthMask(s->depth_write);
  glColorMask(s->colour[0], s->colour[1], s->colour[2], s->colour[3]);
  glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, (GLuint)s->texture);
  glActiveTexture((GLenum)s->active); glUseProgram((GLuint)s->program);
}
#endif

int render_tail_triangles(const mat4 *vp, const TailTrailVertex *v, size_t n_vertices, render_params *p) {
  /* Validate before ANY GL calls, including lazy resource creation. No update,
   * aging, anchor inference or float-to-byte colour conversion belongs here. */
  if (!vp || !v || !p || !n_vertices || n_vertices > 2u * TAIL_TRAIL_MAX_VERTICES ||
      n_vertices % 3u || !white_tex || !progs[0].id || tail_render.failed) return 0;
  for (int i = 0; i < 16; ++i) if (!isfinite(vp->m[i])) return 0;
  tail_render_vertex vertices[2 * TAIL_TRAIL_MAX_VERTICES];
  for (size_t i = 0; i < n_vertices; ++i) {
    const float pos[3] = { v[i].position.x, v[i].position.y, v[i].position.z };
    for (int j = 0; j < 3; ++j) {
      if (!isfinite(pos[j]) || fabsf(pos[j]) > 1e12f) return 0;
      vertices[i].pos[j] = pos[j];
    }
    for (int j = 0; j < 4; ++j) {
      if (!isfinite(v[i].rgba[j]) || v[i].rgba[j] < 0 || v[i].rgba[j] > 1) return 0;
      vertices[i].rgba[j] = v[i].rgba[j];
      /* Bound intermediate shader products/sums, not just a cancelling result. */
      double bound = fabs((double)vp->m[12 + j]);
      for (int k = 0; k < 3; ++k) bound += fabs((double)vp->m[4 * k + j] * pos[k]);
      if (bound > 1e30) return 0;
    }
    vertices[i].uv[0] = vertices[i].uv[1] = 0;
  }
#ifdef WMMT_NATIVE_VK
  cinder_vk_draw packet;
  if (!native_effect_init(&packet, vp, white_tex, 1e30f, 1e29f)) return 0;
  packet.pipeline.depth_test = VK_TRUE;
  packet.pipeline.blend = VK_TRUE;
  packet.pipeline.src_blend = VK_BLEND_FACTOR_SRC_ALPHA;
  packet.pipeline.dst_blend = VK_BLEND_FACTOR_ONE;
  native_effect_vertices(&packet, vertices, n_vertices * sizeof vertices[0], sizeof vertices[0], VK_FORMAT_R32G32B32A32_SFLOAT);
  packet.count = (uint32_t)n_vertices;
  if (!cinder_vk_submit(&packet)) { tail_render.failed = 1; return 0; }
  ++p->draws; p->triangles += (int)(n_vertices / 3u);
  return 1;
#else
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
  uint64_t epoch = cinder_vk_error_epoch();
#else
  uint64_t epoch = vkgl_error_epoch();
#endif
  if (epoch == UINT64_MAX) return 0;
  /* The baseline program is not changed; the existing scope API requires a
   * valid program to snapshot in addition to the full actual adapter context. */
  void *snapshot = vkgl_preview_save(progs[0].id);
  if (!snapshot) return 0;
#else
  tail_render_gl_state state;
  tail_render_gl_save(&state);
#endif
  int submitted = 0;
  if (!tail_render_prepare()) goto restore;
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
  if (cinder_vk_error_epoch() != epoch) goto device_error;
#else
  if (vkgl_error_epoch() != epoch) goto device_error;
#endif
#endif
  const scene_prog *pr = &tail_render.program;
  glUseProgram(pr->id);
  glUniformMatrix4fv(pr->mvp, 1, GL_FALSE, vp->m);
  glUniform3f(pr->eye, 0, 0, 0);
  /* With the bounded world coordinates above, this ratio clamps exactly to 1:
   * no fog, while keeping the shipped shader text/hash completely unchanged. */
  glUniform2f(pr->fog, 1e30f, 1e29f);
  glUniform3f(pr->fog_color, 0, 0, 0);
  glUniform2f(pr->uv_off, 0, 0); glUniform3f(pr->grade, 1, 1, 1);
  glUniform1i(pr->tex, 0);
  if (pr->wet >= 0) glUniform1f(pr->wet, 0);
  glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, white_tex);
  glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LEQUAL); glDepthMask(GL_FALSE);
  glDisable(GL_CULL_FACE); glDisable(GL_STENCIL_TEST);
  glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
  glEnable(GL_BLEND); glBlendEquation(GL_FUNC_ADD); glBlendFunc(GL_SRC_ALPHA, GL_ONE);
  glBindVertexArrayOES(tail_render.vao);
  glBindBuffer(GL_ARRAY_BUFFER, tail_render.vbo);
  glBufferData(GL_ARRAY_BUFFER, (GLsizeiptr)(n_vertices * sizeof vertices[0]), vertices, GL_STREAM_DRAW);
  glEnableVertexAttribArray(0); glEnableVertexAttribArray(1); glEnableVertexAttribArray(2);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof vertices[0], (const void *)offsetof(tail_render_vertex, pos));
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof vertices[0], (const void *)offsetof(tail_render_vertex, uv));
  glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, sizeof vertices[0], (const void *)offsetof(tail_render_vertex, rgba));
  glDrawArrays(GL_TRIANGLES, 0, (GLsizei)n_vertices);
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
  if (cinder_vk_error_epoch() != epoch) goto device_error;
#else
  if (vkgl_error_epoch() != epoch) goto device_error;
#endif
#endif
  submitted = 1;
  ++p->draws; p->triangles += (int)(n_vertices / 3u);
  goto restore;
#ifdef WMMT_VK
device_error:
  render_tail_release(); tail_render.failed = 1;
#endif
restore:
#ifdef WMMT_VK
  vkgl_scope_restore_preserve_error(snapshot);
#else
  /* Do not drain glGetError: an older caller error must not be consumed. */
  tail_render_gl_restore(&state);
#endif
  return submitted;
#endif
}

#include "render_tire_smoke.inc"

#ifdef __ANDROID__
/* clTireTrack::draw: SRC_ALPHA/ONE_MINUS_SRC_ALPHA, RGB writes only,
 * depth-tested with depth writes off, texture clamped across and repeated
 * along the track. The caller normalizes the blend/cull/depth baseline. */
void render_tire_tracks(const mat4 *vp, const render_vertex *v, int n_quads, uint32_t tex, render_params *p) {
  static uint16_t idx[6 * RENDER_MAX_SPRITES];
  if (!vp || !v || !p || !tex || n_quads <= 0) return;
  if (n_quads > RENDER_MAX_SPRITES) n_quads = RENDER_MAX_SPRITES;
  if (!idx[1])
    for (int i = 0; i < RENDER_MAX_SPRITES; ++i) {
      uint16_t b = (uint16_t)(4 * i), *q = idx + 6 * i;
      q[0] = b; q[1] = b + 1; q[2] = b + 2; q[3] = b; q[4] = b + 2; q[5] = b + 3;
    }
#ifdef WMMT_NATIVE_VK
  if (native_effect_quads(vp, v, n_quads, tex, idx, 0, 1, p)) {
    ++p->draws; p->triangles += 2 * n_quads;
  }
#else
  GLboolean mask[4], depth_write;
  glGetBooleanv(GL_COLOR_WRITEMASK, mask);
  glGetBooleanv(GL_DEPTH_WRITEMASK, &depth_write);
  const scene_prog *pr = &progs[0];
  glUseProgram(pr->id);
  glUniformMatrix4fv(pr->mvp, 1, GL_FALSE, vp->m);
  glUniform3f(pr->eye, 0, 0, 0);
  glUniform2f(pr->fog, 1e9f, 1e8f);
  glUniform2f(pr->uv_off, 0, 0);
  glUniform3f(pr->grade, 1, 1, 1);
  glUniform1i(pr->tex, 0);
  if (pr->wet >= 0) glUniform1f(pr->wet, 0);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, tex);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
  glEnable(GL_DEPTH_TEST);
  glDepthMask(GL_FALSE);
  glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_FALSE);
  glDisable(GL_CULL_FACE);
  glEnable(GL_BLEND);
  glBlendEquation(GL_FUNC_ADD);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glEnableVertexAttribArray(2);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof *v, v->pos);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof *v, v->uv);
  glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof *v, v->rgba);
  glDrawElements(GL_TRIANGLES, (GLsizei)n_quads * 6, GL_UNSIGNED_SHORT, idx);
  /* Do not leak this texture into later passes that omit an explicit bind. */
  glBindTexture(GL_TEXTURE_2D, white_tex);
  glColorMask(mask[0], mask[1], mask[2], mask[3]);
  glDepthMask(depth_write);
  glDisable(GL_BLEND);
  glEnable(GL_CULL_FACE);
  glUniform2f(pr->fog, p->fog_far, p->fog_near);
  if (enhance_on) { float grade[3]; enhance_grade(p, 0, grade); glUniform3fv(pr->grade, 1, grade); }
  else if (p->grade[0] > 0.0f) glUniform3fv(pr->grade, 1, p->grade);
  ++p->draws;
  p->triangles += 2 * n_quads;
#endif
}
#endif

static float box_distance(const float *lo, const float *hi, const float *p) {
  float d2 = 0;
  for (int k = 0; k < 3; ++k) {
    float d = p[k] < lo[k] ? lo[k] - p[k] : p[k] > hi[k] ? p[k] - hi[k] : 0;
    d2 += d * d;
  }
  return sqrtf(d2);
}

/* Is the box entirely outside one of the clip planes of mvp (column-major)? */
static int box_outside(const mat4 *mvp, const float *lo, const float *hi) {
  const float *m = mvp->m;
  for (int i = 0; i < 6; ++i) {
    /* planes: w + x, w - x, w + y, w - y, w + z, w - z */
    int row = i / 2;
    float sg = i & 1 ? -1.0f : 1.0f;
    float a = m[3] + sg * m[row], b = m[7] + sg * m[4 + row], c = m[11] + sg * m[8 + row],
          d = m[15] + sg * m[12 + row];
    /* the box corner furthest along the plane normal */
    float x = a > 0 ? hi[0] : lo[0], y = b > 0 ? hi[1] : lo[1], z = c > 0 ? hi[2] : lo[2];
    if (a * x + b * y + c * z + d < 0) return 1;
  }
  return 0;
}

/* Bind batch b's buffers and vertex layout: through its pool's vertex array object, made
 * the first time (in the app's context: the loading thread's, which uploads the buffers,
 * does not draw with these); *bound is the one bound now (0 none). */
#ifndef WMMT_NATIVE_VK
static void bind_batch(const wpk_scene *s, const wpk_batch *b, GLuint *bound) {
  wpk_pool *pl = &s->pools[b->pool];
  if (pl->vao) {
    if (*bound != pl->vao) glBindVertexArrayOES(pl->vao);
    *bound = pl->vao;
    return;
  }
  GLsizei stride = (GLsizei)s->stride;
  glGenVertexArraysOES(1, &pl->vao);
  glBindVertexArrayOES(pl->vao);
  *bound = pl->vao;
  glBindBuffer(GL_ARRAY_BUFFER, pl->vbo);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, pl->ibo);
  for (GLuint a = 0; a < (s->lit ? 4u : 3u); ++a) glEnableVertexAttribArray(a);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, (const void *)0);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, (const void *)12);
  glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, stride, (const void *)20);
  if (s->lit) glVertexAttribPointer(3, 3, GL_SHORT, GL_TRUE, stride, (const void *)24);
  if (pl->nbo) { /* a gloss pool's normals */
    glEnableVertexAttribArray(3);
    glBindBuffer(GL_ARRAY_BUFFER, pl->nbo);
    glVertexAttribPointer(3, 3, GL_SHORT, GL_TRUE, 8, (const void *)0);
  }
}

#endif

/* a lit scene's per-draw values, in the model's space */
typedef struct {
  mat4 mvp, mv;
  float eye[3], l[2][3];
  unsigned set; /* lit_progs whose uniforms this draw has set */
  int cur;      /* the lit_progs entry in use, -1 none */
  uint32_t env, spec; /* GL textures on units 1 and 2 */
  uint32_t ao;        /* and on AO_UNIT */
} lit_draw;

static void lit_begin(lit_draw *d, const mat4 *mvp, const mat4 *model, const float *eye_local, const render_params *p) {
  d->mvp = *mvp;
  d->mv = mat4_mul(p->view, *model);
  memcpy(d->eye, eye_local, sizeof d->eye);
  /* toward each light, turned into the model's frame (the transpose of its rotation) */
  const float *m = model->m;
  for (int i = 0; i < 2; ++i) {
    const float *w = p->light_dir[i];
    float l[3];
    for (int k = 0; k < 3; ++k) l[k] = -(m[4 * k] * w[0] + m[4 * k + 1] * w[1] + m[4 * k + 2] * w[2]);
    float n = sqrtf(l[0] * l[0] + l[1] * l[1] + l[2] * l[2]);
    for (int k = 0; k < 3; ++k) d->l[i][k] = n > 0 ? l[k] / n : 0;
  }
  d->set = 0;
  d->cur = -1;
  d->env = d->spec = d->ao = 0;
}

#ifndef WMMT_NATIVE_VK
static const lit_prog *lit_use(lit_draw *d, int idx, const render_params *p) {
  const lit_prog *lp = &lit_progs[idx];
  if (d->cur != idx) glUseProgram(lp->id);
  d->cur = idx;
  if (d->set & (1u << idx)) return lp;
  d->set |= 1u << idx;
  int ff = idx / 2 == WPK_LIT_FF;
  float dif[2][3], amb[3];
  for (int k = 0; k < 3; ++k) {
    /* the fixed-function parts take the material; car.cg and car_blend.cg the lights as they are */
    for (int i = 0; i < 2; ++i) dif[i][k] = p->light_diffuse[i][k] * (ff ? p->material_diffuse[k] : 1.0f);
    amb[k] = p->ambient[k] * (ff ? p->material_ambient[k] : 1.0f);
  }
  glUniformMatrix4fv(lp->mvp, 1, GL_FALSE, d->mvp.m);
  glUniformMatrix4fv(lp->mv, 1, GL_FALSE, d->mv.m);
  glUniform3fv(lp->eye, 1, d->eye);
  glUniform3fv(lp->l0, 1, d->l[0]);
  glUniform3fv(lp->l1, 1, d->l[1]);
  glUniform3fv(lp->d0, 1, dif[0]);
  glUniform3fv(lp->d1, 1, dif[1]);
  glUniform3fv(lp->amb, 1, amb);
  glUniform2f(lp->fog, p->fog_far, p->fog_near);
  glUniform3fv(lp->fog_color, 1, p->fog_color);
  if (lp->over >= 0) glUniform2f(lp->over, p->over, over_inv_tan);
  if (lp->frame_k >= 0) glUniform1f(lp->frame_k, enhance_on ? frame_k * 1.12f : frame_k);
  return lp;
}
#endif

void wpk_draw_wheels(const wpk_scene *w, const mat4 *view_proj, const mat4 *model, const float *eye_local,
                     int pass, render_params *p, const float hub[2][4]) {
  render_params q = *p;
  /* Separate wheel-pack owner, never the BODY root story scope. */
  q.story_assembly_enabled = 0;
  q.story_assembly_flags = 0;
  q.story_body_y = 0;
  q.wheels = NULL;
  q.wheel_custom = 0;
  q.wheel_drop = 0;
  for (int k = 0; k < 4; ++k) {
    /* corner k: front left, front right, rear left, rear right (pack_cars.py corner) */
    const float *h = hub[k >> 1];
    float side = k & 1 ? -1.0f : 1.0f, sc[3] = { h[2], h[3], h[3] };
    float r[9] = { 1, 0, 0, 0, 1, 0, 0, 0, 1 }, y = 0;
    if (p->wheels) {
      /* clCarDisp::update's tyre node: the posture, then the spin about x (wpk_draw's) */
      const float *t = p->wheels[k];
      float sn = sinf(p->wheel_rot[k]), cs = cosf(p->wheel_rot[k]);
      for (int i = 0; i < 3; ++i) {
        r[i] = t[i];
        r[3 + i] = t[4 + i] * cs + t[8 + i] * sn;
        r[6 + i] = -t[4 + i] * sn + t[8 + i] * cs;
      }
      y = t[13];
    }
    mat4 c = mat4_identity();
    for (int col = 0; col < 3; ++col)
      for (int i = 0; i < 3; ++i) c.m[4 * col + i] = r[3 * col + i] * sc[col];
    c.m[12] = side * h[0], c.m[13] = y - (p->wheels ? 0.0f : p->wheel_drop), c.m[14] = h[1];
    mat4 m = mat4_mul(*model, c);
    /* the eye in the corner's frame */
    float d[3] = { eye_local[0] - c.m[12], eye_local[1] - c.m[13], eye_local[2] - c.m[14] }, e[3];
    for (int col = 0; col < 3; ++col)
      e[col] = (r[3 * col] * d[0] + r[3 * col + 1] * d[1] + r[3 * col + 2] * d[2]) / sc[col];
    q.wheel_side = (k & 1) + 1;
    wpk_draw(w, view_proj, &m, e, pass, &q);
  }
  p->draws = q.draws, p->triangles = q.triangles, p->new_chunks = q.new_chunks;
}

#include "render_native_scene.inc"

static void wpk_draw_internal(const wpk_scene *s, const mat4 *view_proj, const mat4 *model, const float *eye_local,
              int pass, render_params *p, int limited, uint32_t group) {
#ifdef WMMT_NATIVE_VK
  native_scene_draw(s, view_proj, model, eye_local, pass, p, limited, group);
  return;
#else
  const scene_prog *pr = &progs[pass == WPK_CUTOUT];
  mat4 mvp = mat4_mul(*view_proj, *model);
  lit_draw ld;
  if (s->lit) {
    lit_begin(&ld, &mvp, model, eye_local, p);
  } else {
    glUseProgram(pr->id);
    glUniformMatrix4fv(pr->mvp, 1, GL_FALSE, mvp.m);
    glUniform3fv(pr->eye, 1, eye_local);
    glUniform2f(pr->uv_off, p->uv_shift[0], p->uv_shift[1]);
  }
  if (s->two_sided) glDisable(GL_CULL_FACE);
  int last_flags = -1, turned = 0;
  GLuint bound = 0;
  /* the unlit scenes' program in use (the gloss one for a gloss batch), whether the gloss one
   * has this draw's matrix yet, and the texture coordinates' offset both take */
  const scene_prog *cur = pr, *gp = &gloss_progs[pass == WPK_CUTOUT];
  int plain_set = 1, gloss_set = 0;
  const int story_scope = p->story_assembly_enabled && !limited;
  int road_grade[2] = { 0, 0 };
  /* WET: the road's batches reflect the last frame, mirrored about the horizon: where a point
   * far ahead level with the eye lands on the screen */
  float wet = !s->lit && s->tex_wet && pr->wet >= 0 && frame_wet ? p->wet : 0.0f, wet_set = 0.0f;
  if (wet > 0.0f) {
    float f[3] = { -p->view.m[2], 0.0f, -p->view.m[10] }, n = sqrtf(f[0] * f[0] + f[2] * f[2]);
    float a[3] = { eye_local[0] + f[0] / (n + 1e-6f) * 1e5f, eye_local[1], eye_local[2] + f[2] / (n + 1e-6f) * 1e5f };
    const float *m = mvp.m;
    float cy = m[1] * a[0] + m[5] * a[1] + m[9] * a[2] + m[13], cw = m[3] * a[0] + m[7] * a[1] + m[11] * a[2] + m[15];
    if (n < 1e-3f || cw <= 0.0f || blur.w <= 0) wet = 0.0f;
    else glUniform3f(pr->horizon, 1.0f / (float)blur.w, 1.0f / (float)blur.h, 0.5f + 0.5f * cy / cw);
  }
  float uv_u = p->uv_shift[0], uv_v = p->uv_shift[1];
  /* Persistent storage: a later plain/gloss switch must use this CHUNK's
   * matrix/eye, never a pointer to a block-local wheel/height temporary. */
  mat4 bound_mvp = mvp;
  float bound_eye[3] = {eye_local[0],eye_local[1],eye_local[2]};
  const float *cur_mvp = bound_mvp.m, *cur_eye = bound_eye;
  uint32_t gloss_tex = 0, gloss_cube = 0;
  for (uint32_t c = 0; c < s->n_chunk; ++c) {
    const wpk_chunk *ch = &s->chunks[c];
    if (!wpk_chunk_valid(ch, s->n_batch)) continue;
    if (limited && ch->group != group) continue;
    int story_part = render_story_part_visibility(p,limited,ch->group);
    if (story_part == 0) continue;
    float body_y = render_story_body_offset(p,limited,ch->group);
    mat4 cm = *model, cmvp = mvp;
    float ce[3] = {eye_local[0],eye_local[1],eye_local[2]};
    if (body_y != 0.0f)
      render_story_translate_y(model,view_proj,eye_local,body_y,&cm,&cmvp,ce);
    float range;
    int wheel = limited ? -1 : ch->group >= WPK_WHEEL && ch->group < WPK_WHEEL + 4 ? (int)(ch->group - WPK_WHEEL) : -1;
    if (limited) goto group_cull;
    if (ch->group >= WPK_CTIRE && ch->group < WPK_CTIRE + 4) {
      if (!p->wheel_custom) continue;
      wheel = (int)(ch->group - WPK_CTIRE);
    } else if (wheel >= 0 && p->wheel_custom) {
      continue;
    }
    if (wheel >= 0 && p->wheel_side && wheel != p->wheel_side - 1) continue;
    if (wheel >= 0) {
      range = p->range[WPK_GROUND]; /* as the body */
    } else if (ch->group == WPK_LAMP_OFF || ch->group == WPK_LAMP_ON) {
      if ((ch->group == WPK_LAMP_ON) != (p->lamps_on != 0)) continue;
      range = p->range[WPK_GROUND];
    } else if (ch->group == WPK_BRAKE_RUN || ch->group == WPK_BRAKE_STOP || ch->group == WPK_BRAKE_LIGHT) {
      /* clCarLampManager is the race's: the menus' cars have no brake lamp glow */
      if (!p->lamps_on || (ch->group == WPK_BRAKE_STOP && !p->braking) || (ch->group == WPK_BRAKE_RUN && p->braking))
        continue;
      range = p->range[WPK_GROUND];
    } else if (ch->group > WPK_BRAKE_HIGH && ch->group < WPK_BRAKE_WING2 + 0x20) {
      if (!p->lamps_on || !p->braking || p->wing < 0 || p->wing > 4 || !(ch->group >> p->wing & 1)) continue;
      range = p->range[WPK_GROUND];
    } else if (ch->group >= WPK_MIRROR && ch->group < WPK_BONNET + 4) {
      /* one child of each part's switch (0x8944dd0's tables 0x97774cc, 0x97774d4, 0x97774e4);
       * wing 4 is none of them */
      uint32_t shown = ch->group < WPK_WING ? WPK_MIRROR + (uint32_t)p->mirror
                       : ch->group < WPK_BONNET ? (p->wing < 4 ? WPK_WING + (uint32_t)p->wing : 0)
                       : WPK_BONNET + (uint32_t)p->bonnet;
      if (ch->group != shown) continue;
      range = p->range[WPK_GROUND];
    } else if (story_part > 0) {
      /* These numeric values are also legal world object IDs. Only the scoped
       * enabled path treats them as owned body-root parts. */
      range = p->range[WPK_GROUND];
    } else if (ch->group < WPK_GROUPS) {
      range = p->range[ch->group];
    } else {
      /* named objects (pack.py --objects) show only when asked for */
      uint32_t obj = ch->group - WPK_GROUPS;
      if (!p->object_visible || p->n_objects <= 0 || obj >= (uint32_t)p->n_objects || !p->object_visible[obj]) continue;
      range = p->range[WPK_SHORT];
    }
    if (box_distance(ch->lo, ch->hi, ce) > range) continue;
  group_cull:
    if (box_outside(&cmvp, ch->lo, ch->hi)) continue;
    if ((wheel >= 0 && (p->wheels || p->wheel_drop != 0.0f)) || body_y != 0.0f || turned) {
      /* clCarDisp::update: the tyre node at (TireLocation x, the posture's y, z) turned by the
       * posture, its spin node about x by the turn; the corner's centre stands for the hub */
      turned = body_y != 0.0f;
      if (wheel >= 0 && p->wheels) {
        const float *t = p->wheels[wheel];
        float h[3] = { 0.5f * (ch->lo[0] + ch->hi[0]), 0.5f * (ch->lo[1] + ch->hi[1]), 0.5f * (ch->lo[2] + ch->hi[2]) };
        float sn = sinf(p->wheel_rot[wheel]), cs = cosf(p->wheel_rot[wheel]);
        mat4 w;
        /* columns: posture * rotation about x */
        for (int r = 0; r < 3; ++r) {
          w.m[r] = t[r];
          w.m[4 + r] = t[4 + r] * cs + t[8 + r] * sn;
          w.m[8 + r] = -t[4 + r] * sn + t[8 + r] * cs;
        }
        w.m[3] = w.m[7] = w.m[11] = 0;
        float at[3] = { h[0], p->wheels_hub ? h[1] : t[13], h[2] };
        for (int r = 0; r < 3; ++r) /* translate so the centre h lands at `at` */
          w.m[12 + r] = at[r] - (w.m[r] * h[0] + w.m[4 + r] * h[1] + w.m[8 + r] * h[2]);
        w.m[15] = 1;
        cm = mat4_mul(*model, w);
        cmvp = mat4_mul(*view_proj, cm);
        float d[3] = { eye_local[0] - w.m[12], eye_local[1] - w.m[13], eye_local[2] - w.m[14] };
        for (int r = 0; r < 3; ++r) ce[r] = w.m[4 * r] * d[0] + w.m[4 * r + 1] * d[1] + w.m[4 * r + 2] * d[2];
        turned = 1;
      } else if (wheel >= 0) {
        mat4 w = mat4_identity();
        w.m[13] = -p->wheel_drop;
        cm = mat4_mul(*model, w);
        cmvp = mat4_mul(*view_proj, cm);
        ce[1] += p->wheel_drop;
        turned = 1;
      }
      if (s->lit) {
        lit_begin(&ld, &cmvp, &cm, ce, p);
      } else {
        glUniformMatrix4fv(cur->mvp, 1, GL_FALSE, cmvp.m);
        glUniform3fv(cur->eye, 1, ce);
        if (story_scope) {
          bound_mvp = cmvp;
          memcpy(bound_eye,ce,sizeof bound_eye);
          plain_set = cur == pr;
          gloss_set = cur == gp;
        } else {
          /* Preserve legacy non-story/limited shader-switch behavior exactly. */
          plain_set = 1;
          gloss_set = 0;
        }
      }
    }
    if (!s->warm[c]) {
      s->warm[c] = 1;
      p->new_chunks++;
    }
    for (uint32_t i = ch->first; i < ch->first + ch->n; ++i) {
      wpk_batch *b = &s->batches[i];
      if (!b->count) continue;
      int blend = b->flags & WPK_BLEND_MASK;
      int kind = blend ? WPK_BLEND : b->cutout && !s->solid ? WPK_CUTOUT : WPK_OPAQUE;
      if (kind != pass) continue;
      if (s->lit) {
        const lit_prog *lp = lit_use(&ld, 2 * b->prog + (kind == WPK_CUTOUT), p);
        if (b->prog != WPK_LIT_FF) {
          uint32_t env = b->env == 0xFFFF ? white_tex : s->textures[b->env];
          uint32_t spec = b->spec == 0xFFFF ? white_tex : s->textures[b->spec];
          if (env != ld.env || (b->prog == WPK_LIT_CAR_BLEND && spec != ld.spec)) {
            glActiveTexture(GL_TEXTURE1);
            glBindTexture(GL_TEXTURE_2D, ld.env = env);
            if (b->prog == WPK_LIT_CAR_BLEND) {
              glActiveTexture(GL_TEXTURE2);
              glBindTexture(GL_TEXTURE_2D, ld.spec = spec);
            }
            glActiveTexture(GL_TEXTURE0);
          }
          /* uPower attenuates the existing environment, not the specular exponent. */
          if (b->prog == WPK_LIT_CAR) {
            float power = b->power;
            if (enhance_on && power >= 0.0f && power <= 1.0f) power *= 0.88f;
            glUniform1f(lp->power, power);
          }
        }
        uint32_t ao = ao_on && b->tex < s->n_ao && s->ao_tex[b->tex] ? s->ao_tex[b->tex] : white_tex;
        if (ao != ld.ao) {
          glActiveTexture(GL_TEXTURE0 + AO_UNIT);
          glBindTexture(GL_TEXTURE_2D, ld.ao = ao);
          glActiveTexture(GL_TEXTURE0);
        }
      }
      if (!s->lit) {
        const scene_prog *want = b->gloss != 0xFFFF && !p->no_gloss ? gp : pr;
        if (want != cur) {
          glUseProgram(want->id);
          cur = want;
          if (want == gp && !gloss_set) {
            glUniformMatrix4fv(gp->mvp, 1, GL_FALSE, cur_mvp);
            glUniform3fv(gp->eye, 1, cur_eye);
            gloss_set = 1;
          } else if (want == pr && !plain_set) {
            glUniformMatrix4fv(pr->mvp, 1, GL_FALSE, cur_mvp);
            glUniform3fv(pr->eye, 1, cur_eye);
            plain_set = 1;
          }
          glUniform2f(cur->uv_off, uv_u, uv_v);
        }
        if (enhance_on) {
          int which = want == gp;
          int road = s->tex_wet && b->tex < s->n_tex && s->tex_wet[b->tex] && !blend;
          if (road_grade[which] != road) {
            float grade[3]; enhance_grade(p, road, grade);
            glUniform3fv(cur->grade, 1, grade);
            road_grade[which] = road;
          }
        }
        if (want == gp) {
          uint32_t gt = s->textures[b->gloss], gc = s->cubes[b->cube];
          if (gt != gloss_tex) {
            glActiveTexture(GL_TEXTURE1);
            glBindTexture(GL_TEXTURE_2D, gloss_tex = gt);
            s->tex_warm[b->gloss] = 1;
          }
          if (gc != gloss_cube) {
            glActiveTexture(GL_TEXTURE2);
            glBindTexture(GL_TEXTURE_CUBE_MAP, gloss_cube = gc);
          }
          glActiveTexture(GL_TEXTURE0);
        }
      }
      if (wet > 0.0f && cur == pr) {
        float w = b->tex < s->n_tex && s->tex_wet[b->tex] ? wet : 0.0f;
        if (w != wet_set) glUniform1f(pr->wet, wet_set = w);
      }
      if (b->flags != last_flags) {
        if (blend == 2) glBlendFunc(GL_SRC_ALPHA, GL_ONE);
        else glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        if (!s->lit && ((b->flags | last_flags) & ~WPK_BLEND_MASK)) {
          /* animated sign: step through its flipbook (layout in tools/stage/pack.py) */
          float u = 0, v = 0;
          if (b->flags & ~WPK_BLEND_MASK) {
            int cols = ((b->flags >> 2) & 7) + 1, rows = ((b->flags >> 5) & 7) + 1;
            int frames = ((b->flags >> 8) & 15) + 1, fps2 = (b->flags >> 12) & 15;
            int f = (int)(p->time * (float)fps2 * 0.5f) % frames;
            u = (float)(f % cols) / (float)cols;
            v = (float)(f / cols % rows) / (float)rows;
          }
          uv_u = u + p->uv_shift[0];
          uv_v = v + p->uv_shift[1];
          glUniform2f(cur->uv_off, uv_u, uv_v);
        }
        last_flags = b->flags;
      }
      glBindTexture(GL_TEXTURE_2D, b->tex == 0xFFFF ? white_tex : s->textures[b->tex]);
      bind_batch(s, b, &bound);
      glDrawElements(GL_TRIANGLES, (GLsizei)b->count, GL_UNSIGNED_SHORT, (const void *)(uintptr_t)b->ioff);
      if (b->tex != 0xFFFF) s->tex_warm[b->tex] = 1;
      s->pools[b->pool].warm = 1;
      p->draws++;
      p->triangles += (int)b->count / 3;
    }
  }
  /* back to no vertex array object: the other drawing binds its own buffers and arrays */
  if (bound) glBindVertexArrayOES(0);
  if (enhance_on && !s->lit && (road_grade[0] || road_grade[1])) {
    float grade[3]; enhance_grade(p, 0, grade);
    if (road_grade[1]) { glUseProgram(gp->id); glUniform3fv(gp->grade, 1, grade); }
    if (road_grade[0]) { glUseProgram(pr->id); glUniform3fv(pr->grade, 1, grade); }
    /* The active program may have changed while restoring both. */
    glUseProgram(pr->id);
  } else if (cur != pr) glUseProgram(pr->id);
  if (wet_set != 0.0f) glUniform1f(pr->wet, 0.0f);
  if (gloss_cube) {
    glActiveTexture(GL_TEXTURE2);
    glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
    glActiveTexture(GL_TEXTURE0);
  }
  if (s->two_sided) glEnable(GL_CULL_FACE);
#endif
}

void wpk_draw(const wpk_scene *s, const mat4 *vp, const mat4 *model, const float *eye, int pass, render_params *p) {
  wpk_draw_internal(s, vp, model, eye, pass, p, 0, 0);
}
void wpk_draw_group(const wpk_scene *s, const mat4 *vp, const mat4 *model, const float *eye, int pass, render_params *p, uint32_t group) {
  if (s && vp && model && eye && p && pass >= 0 && pass < WPK_PASSES) wpk_draw_internal(s, vp, model, eye, pass, p, 1, group);
}

/* ---- the overhead map (render_overhead) ---- */
#define OVER_SIZE 256
#define OVER_TAN 1.73f    /* its half angle's tangent: 60 degrees each way */
#define OVER_ROOF 14.0f   /* its eye over the car's origin (1.4 m) */
#define OVER_REACH 500.0f /* what it draws: within 50 m across of the eye */
#define OVER_NEAR 4.0f
/* the undersides in the shade: their maps' colours were lit from above */
#define OVER_SHADE "0.5"
static const char *VS_OVER =
  "attribute vec3 aPos; attribute vec2 aUV; attribute vec4 aColor;\n"
  "uniform mat4 uMVP; varying vec2 vUV; varying lowp vec4 vColor;\n"
  "void main() { gl_Position = uMVP * vec4(aPos, 1.0); vUV = aUV; vColor = aColor; }\n";
static const char *FS_OVER =
  "precision mediump float;\n"
  "uniform sampler2D uTex; uniform lowp float uCut; varying vec2 vUV; varying lowp vec4 vColor;\n"
  "void main() {\n"
  "  lowp vec4 c = texture2D(uTex, vUV) * vColor;\n"
  "  if (c.a < uCut) discard;\n"
  "  gl_FragColor = vec4(c.rgb * " OVER_SHADE ", 1.0);\n"
  "}\n";
static struct {
  GLuint prog, fbo, tex, depth;
  GLint mvp, cut;
  int state; /* 0 not made yet, 1 ready, -1 none */
} over;

static int over_init(void) {
  const char *attribs[] = { "aPos", "aUV", "aColor" };
  over.state = -1;
#ifdef WMMT_NATIVE_VK
  over.prog = native_program_create(VS_OVER, FS_OVER, attribs, 3);
#else
  over.prog = gl_compile_program(VS_OVER, FS_OVER, attribs, 3);
#endif
  if (!over.prog) return -1;
#ifndef WMMT_NATIVE_VK
  over.mvp = glGetUniformLocation(over.prog, "uMVP");
  over.cut = glGetUniformLocation(over.prog, "uCut");
  glUseProgram(over.prog);
  glUniform1i(glGetUniformLocation(over.prog, "uTex"), 0);
#endif
#ifdef WMMT_NATIVE_VK
  GLuint tex=0, depth=0, fbo=0;
  int ok=native_simple_target(OVER_SIZE,OVER_SIZE,CINDER_VK_STORAGE_RGBA8,CINDER_VK_STORAGE_DEPTH16,&tex,&depth,&fbo);
  if(ok) {
    cinder_vk_target_destroy(over.fbo); cinder_vk_texture_destroy(over.tex); cinder_vk_attachment_destroy(over.depth);
    over.tex=tex; over.depth=depth; over.fbo=fbo;
  }
#else
  GLint screen;
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screen);
  glGenTextures(1, &over.tex);
  glBindTexture(GL_TEXTURE_2D, over.tex);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, OVER_SIZE, OVER_SIZE, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
  glGenRenderbuffers(1, &over.depth);
  glBindRenderbuffer(GL_RENDERBUFFER, over.depth);
  glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT16, OVER_SIZE, OVER_SIZE);
  glGenFramebuffers(1, &over.fbo);
  glBindFramebuffer(GL_FRAMEBUFFER, over.fbo);
  glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, over.tex, 0);
  glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, over.depth);
  int ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)screen);
#endif
  if (!ok) {
#ifdef WMMT_NATIVE_VK
    native_program_release(&over.prog);
#endif
    fprintf(stderr, "overhead map: no %dx%d framebuffer\n", OVER_SIZE, OVER_SIZE);
    return -1;
  }
  over_inv_tan = 1.0f / OVER_TAN;
  over.state = 1;
  return 0;
}

int render_overhead(const wpk_scene *const *s, int n, const mat4 *car, render_params *p) {
  if (!over.state) over_init();
  if (over.state < 0) return -1;
#ifdef WMMT_NATIVE_VK
  if (!cinder_vk_program_ready(over.prog) || !cinder_vk_target_ready(over.fbo)) return -1;
#endif
  /* the eye over the roof looking ahead and OVER_PITCH up (the car's y, z), the map's x
   * the car's -x (the lit programs' overhead() sees it the same way) */
  const float *m = car->m;
  float eye[3], at[3], up[3], sn = sinf(OVER_PITCH), cs = cosf(OVER_PITCH);
  for (int k = 0; k < 3; ++k) {
    eye[k] = m[12 + k] + OVER_ROOF * m[4 + k];
    at[k] = eye[k] + sn * m[4 + k] + cs * m[8 + k];
    up[k] = cs * m[4 + k] - sn * m[8 + k];
  }
  float far = OVER_REACH * 2.0f;
  mat4 vp = mat4_mul(mat4_perspective(2.0f * atanf(OVER_TAN), 1.0f, OVER_NEAR, far), mat4_look_at(eye, at, up));
#ifdef WMMT_NATIVE_VK
  const float clear[4]={0,0,0,0};
  if(!cinder_vk_clear(over.fbo,VK_IMAGE_ASPECT_COLOR_BIT|VK_IMAGE_ASPECT_DEPTH_BIT,clear,NULL)) return -1;
#else
  GLint screen, view[4];
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &screen);
  glGetIntegerv(GL_VIEWPORT, view);
  glBindFramebuffer(GL_FRAMEBUFFER, over.fbo);
  glViewport(0, 0, OVER_SIZE, OVER_SIZE);
  glClearColor(0, 0, 0, 0);
  glDepthMask(GL_TRUE);
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
#endif
#ifndef WMMT_NATIVE_VK
  glUseProgram(over.prog);
  glUniformMatrix4fv(over.mvp, 1, GL_FALSE, vp.m);
  glActiveTexture(GL_TEXTURE0);
  glEnable(GL_DEPTH_TEST);
  glDepthFunc(GL_LEQUAL);
  glDisable(GL_CULL_FACE); /* seen from under: what was modelled to be seen from above too */
  glDisable(GL_BLEND);
  GLuint bound = 0;
  float cut = -1.0f;
#endif
  int draws = 0;
  for (int i = 0; i < n; ++i) {
    const wpk_scene *sc = s[i];
    if (!sc || !sc->n_batch || sc->lit) continue;
    for (uint32_t c = 0; c < sc->n_chunk; ++c) {
      const wpk_chunk *ch = &sc->chunks[c];
      if (!wpk_chunk_valid(ch, sc->n_batch)) continue;
      if (ch->group >= WPK_GROUPS) {
        uint32_t obj = ch->group - WPK_GROUPS;
        if (!p->object_visible || p->n_objects <= 0 || obj >= (uint32_t)p->n_objects || !p->object_visible[obj]) continue;
      }
      if (ch->hi[1] < eye[1] || box_distance(ch->lo, ch->hi, eye) > far) continue;
      for (uint32_t b = ch->first; b < ch->first + ch->n; ++b) {
        const wpk_batch *bt = &sc->batches[b];
        if (!bt->count || (bt->flags & WPK_BLEND_MASK) || bt->hi[1] < eye[1] + OVER_NEAR) continue;
        /* near it across, then in the view */
        float dx = eye[0] < bt->lo[0] ? bt->lo[0] - eye[0] : eye[0] > bt->hi[0] ? eye[0] - bt->hi[0] : 0;
        float dz = eye[2] < bt->lo[2] ? bt->lo[2] - eye[2] : eye[2] > bt->hi[2] ? eye[2] - bt->hi[2] : 0;
        if (dx * dx + dz * dz > OVER_REACH * OVER_REACH || box_outside(&vp, bt->lo, bt->hi)) continue;
        float want = bt->cutout && !sc->solid ? 0.5f : -1.0f;
#ifdef WMMT_NATIVE_VK
        cinder_vk_draw packet;
        if (bt->pool >= sc->n_pools || !cinder_vk_draw_init(&packet, over.prog, over.fbo, OVER_SIZE, OVER_SIZE)) continue;
        packet.pipeline.depth_test = packet.pipeline.depth_write = VK_TRUE;
        native_mesh(&packet, sc, bt);
        if (!cinder_vk_uniform(&packet, "uMVP", vp.m, sizeof vp.m) ||
            !cinder_vk_uniform(&packet, "uCut", &want, sizeof want) ||
            !cinder_vk_texture(&packet, "uTex", bt->tex == 0xFFFF ? white_tex : sc->textures[bt->tex]) ||
            !cinder_vk_submit(&packet)) continue;
#else
        if (want != cut) glUniform1f(over.cut, cut = want);
        glBindTexture(GL_TEXTURE_2D, bt->tex == 0xFFFF ? white_tex : sc->textures[bt->tex]);
        bind_batch(sc, bt, &bound);
        glDrawElements(GL_TRIANGLES, (GLsizei)bt->count, GL_UNSIGNED_SHORT, (const void *)(uintptr_t)bt->ioff);
#endif
        draws++;
        p->triangles += (int)bt->count / 3;
      }
    }
  }
#ifndef WMMT_NATIVE_VK
  if (bound) glBindVertexArrayOES(0);
#endif
#if defined(WMMT_EGL) && !defined(WMMT_NATIVE_VK)
  static int dump_n;
  if (getenv("WMMT_OVER_DUMP") && ++dump_n % 30 == 0) { /* test: the map as a picture every 30 frames */
    static unsigned char px[OVER_SIZE * OVER_SIZE * 4];
    char name[64];
    snprintf(name, sizeof name, "%s/over%04d.ppm", getenv("WMMT_OVER_DUMP"), dump_n / 30);
    glReadPixels(0, 0, OVER_SIZE, OVER_SIZE, GL_RGBA, GL_UNSIGNED_BYTE, px);
    FILE *f = fopen(name, "wb");
    if (f) {
      fprintf(f, "P6\n%d %d\n255\n", OVER_SIZE, OVER_SIZE);
      for (int y = OVER_SIZE - 1; y >= 0; --y)
        for (int x = 0; x < OVER_SIZE; ++x) {
          unsigned char *q = px + 4 * (y * OVER_SIZE + x);
          unsigned char c[3] = { q[3] ? q[0] : 255, q[3] ? q[1] : 0, q[3] ? q[2] : 255 };
          fwrite(c, 1, 3, f);
        }
      fclose(f);
    }
  }
#endif
#if defined(__APPLE__) && !defined(WMMT_NATIVE_VK)
  const GLenum discard[] = { GL_DEPTH_ATTACHMENT };
  glDiscardFramebufferEXT(GL_FRAMEBUFFER, 1, discard);
#endif
#ifndef WMMT_NATIVE_VK
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)screen);
  glViewport(view[0], view[1], view[2], view[3]);
  glEnable(GL_CULL_FACE);
  /* the cars' programs read it on their own unit */
  glActiveTexture(GL_TEXTURE0 + OVER_UNIT);
  glBindTexture(GL_TEXTURE_2D, over.tex);
  glActiveTexture(GL_TEXTURE0);
#endif
#ifdef WMMT_NATIVE_VK
  native_over_texture = over.tex;
#endif
  p->draws += draws;
  return draws;
}

/* ---- the back mirror (clBackMirror: its own scene drawn into a 200x72 target, then put
 * on the screen flipped left to right) ---- */
static struct {
  GLuint fbo, tex, depth;
  int w, h;
  GLint screen, view[4];
#ifdef WMMT_NATIVE_VK
  native_scene_view saved_native;
#endif
} bm;

int render_backmirror_begin(int w, int h, const float clear[3]) {
  if (w < 8 || h < 8) return -1;
#ifdef WMMT_NATIVE_VK
  if(bm.w!=w || bm.h!=h || !cinder_vk_target_ready(bm.fbo)) {
    GLuint tex=0,depth=0,fbo=0;
    if(!native_simple_target(w,h,CINDER_VK_STORAGE_RGBA8,CINDER_VK_STORAGE_DEPTH16,&tex,&depth,&fbo)) return -1;
    cinder_vk_target_destroy(bm.fbo); cinder_vk_texture_destroy(bm.tex); cinder_vk_attachment_destroy(bm.depth);
    bm.tex=tex; bm.depth=depth; bm.fbo=fbo; bm.w=w; bm.h=h;
  }
#else
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &bm.screen);
  glGetIntegerv(GL_VIEWPORT, bm.view);
  if (bm.w != w || bm.h != h) {
    if (!bm.fbo) {
      glGenTextures(1, &bm.tex);
      glGenRenderbuffers(1, &bm.depth);
      glGenFramebuffers(1, &bm.fbo);
    }
    glBindTexture(GL_TEXTURE_2D, bm.tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindRenderbuffer(GL_RENDERBUFFER, bm.depth);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT16, w, h);
    glBindFramebuffer(GL_FRAMEBUFFER, bm.fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, bm.tex, 0);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, bm.depth);
    int ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)bm.screen);
    if (!ok) {
      fprintf(stderr, "back mirror: no %dx%d framebuffer\n", w, h);
      bm.w = bm.h = 0;
      return -1;
    }
    bm.w = w, bm.h = h;
  }
#endif
#ifdef WMMT_NATIVE_VK
  bm.saved_native = native_scene;
  native_scene = (native_scene_view){bm.fbo, w, h};
  const float color[4]={clear[0],clear[1],clear[2],1};
  if(!cinder_vk_clear(bm.fbo,VK_IMAGE_ASPECT_COLOR_BIT|VK_IMAGE_ASPECT_DEPTH_BIT,color,NULL)) {
    native_scene=bm.saved_native; return -1;
  }
#else
  glBindFramebuffer(GL_FRAMEBUFFER, bm.fbo);
  glViewport(0, 0, w, h);
  /* drawHigh's clear: the colour (0.847, 1, 0.976) unless the mirror says otherwise */
  glClearColor(clear[0], clear[1], clear[2], 1);
  glDepthMask(GL_TRUE);
  glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
#endif
  return 0;
}

void render_backmirror_end(void) {
#ifdef WMMT_NATIVE_VK
  (void)cinder_vk_discard(bm.fbo,VK_IMAGE_ASPECT_DEPTH_BIT);
  native_scene = bm.saved_native;
#else
#ifdef __APPLE__
  const GLenum discard[] = { GL_DEPTH_ATTACHMENT };
  glDiscardFramebufferEXT(GL_FRAMEBUFFER, 1, discard);
#endif
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)bm.screen);
  glViewport(bm.view[0], bm.view[1], bm.view[2], bm.view[3]);
#endif
}

void render_backmirror_draw(const mat4 *proj, float x, float y, float w, float h) {
  if (!bm.w) return;
  /* the clBackMirror quad's corners: u 1 at its left, 0 at its right (a mirror) */
  const render_vertex v[4] = {
    { { x, y, 0 }, { 1, 1 }, { 255, 255, 255, 255 } },
    { { x + w, y, 0 }, { 0, 1 }, { 255, 255, 255, 255 } },
    { { x + w, y + h, 0 }, { 0, 0 }, { 255, 255, 255, 255 } },
    { { x, y + h, 0 }, { 1, 0 }, { 255, 255, 255, 255 } },
  };
  static const uint16_t idx[6] = { 0, 1, 2, 0, 2, 3 };
  const scene_prog *pr = &progs[0];
#ifdef WMMT_NATIVE_VK
  /* A real explicit packet: neither the active GL program/VAO nor any prior
   * uniform, texture, blend, stencil or viewport state can influence this draw. */
  int sw, sh;
  cinder_vk_screen_extent(&sw, &sh);
  cinder_vk_draw packet;
  if (!cinder_vk_draw_init(&packet, pr->id, 0, sw, sh)) return;
  const float zero[3] = {0, 0, 0}, grade[3] = {1, 1, 1}, fog[2] = {1e9f, 1e8f}, uv[2] = {0, 0};
  if (!cinder_vk_uniform(&packet, "uMVP", proj->m, sizeof proj->m) ||
      !cinder_vk_uniform(&packet, "uEye", zero, sizeof zero) ||
      !cinder_vk_uniform(&packet, "uFog", fog, sizeof fog) ||
      !cinder_vk_uniform(&packet, "uFogColor", zero, sizeof zero) ||
      !cinder_vk_uniform(&packet, "uGrade", grade, sizeof grade) ||
      !cinder_vk_uniform(&packet, "uUVOff", uv, sizeof uv) ||
      !cinder_vk_texture(&packet, "uTex", bm.tex)) return;
  packet.attributes[0] = (cinder_vk_attribute){.format=VK_FORMAT_R32G32B32_SFLOAT,
    .stride=sizeof *v, .data=v, .bytes=sizeof v, .offset=offsetof(render_vertex, pos)};
  packet.attributes[1] = (cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,
    .stride=sizeof *v, .data=v, .bytes=sizeof v, .offset=offsetof(render_vertex, uv)};
  packet.attributes[2] = (cinder_vk_attribute){.format=VK_FORMAT_R8G8B8A8_UNORM,
    .stride=sizeof *v, .data=v, .bytes=sizeof v, .offset=offsetof(render_vertex, rgba)};
  packet.count = 6; packet.indexed = VK_TRUE;
  packet.indices = idx; packet.index_bytes = sizeof idx;
  cinder_vk_submit(&packet);
  return;
#else
  glBindVertexArrayOES(0);
  glUseProgram(pr->id);
  glUniformMatrix4fv(pr->mvp, 1, GL_FALSE, proj->m);
  glUniform3f(pr->eye, 0, 0, 0);
  glUniform2f(pr->fog, 1e9f, 1e8f);
  glUniform2f(pr->uv_off, 0, 0);
  glUniform3f(pr->grade, 1.0f, 1.0f, 1.0f); /* (the lamps, sparks and mirror as they are) */
  glDisable(GL_CULL_FACE);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_BLEND);
  glDepthMask(GL_FALSE);
  glActiveTexture(GL_TEXTURE0);
  glBindTexture(GL_TEXTURE_2D, bm.tex);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof *v, v->pos);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof *v, v->uv);
  glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof *v, v->rgba);
  glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_SHORT, idx);
  glEnable(GL_CULL_FACE);
  glEnable(GL_DEPTH_TEST);
#endif
}

#ifndef WMMT_NATIVE_VK
static void draw_volume(const wpk_scene *s, const mat4 *mvp) {
  GLuint bound = 0;
  glUniformMatrix4fv(shadow_mvp, 1, GL_FALSE, mvp->m);
  for (uint32_t c = 0; c < s->n_chunk; ++c) {
    const wpk_chunk *ch = &s->chunks[c];
    if (ch->group != WPK_SHADOW || !wpk_chunk_valid(ch, s->n_batch) || box_outside(mvp, ch->lo, ch->hi)) continue;
    for (uint32_t i = ch->first; i < ch->first + ch->n; ++i) {
      const wpk_batch *b = &s->batches[i];
      if (!b->count) continue; /* not uploaded yet, or rejected: do not cache an empty VAO */
      bind_batch(s, b, &bound);
      glDrawElements(GL_TRIANGLES, (GLsizei)b->count, GL_UNSIGNED_SHORT, (const void *)(uintptr_t)b->ioff);
    }
  }
}

#endif

/* The arcade marks the pixels in the frame's alpha: the volumes' front faces that pass the
 * depth test set it (STENCIL_INC), then their back faces that pass clear it (STENCIL_DEC), so
 * what stays marked is the ground (or a tyre) inside a volume; its final pass darkens them.
 * The port marks them in the stencil buffer and darkens them by drawing the volumes once more,
 * which clears the marks again. */
void render_shadows(const wpk_scene *const *s, const mat4 *mvp, int n, render_params *p) {
  if (n <= 0) return;
#ifdef WMMT_NATIVE_VK
  native_shadow_draw(s, mvp, n, p);
  return;
#else
  glUseProgram(shadow_prog);
  glEnable(GL_STENCIL_TEST);
  glStencilMask(0xff);
  glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE);
  glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
  glDepthMask(GL_FALSE);
  glDisable(GL_BLEND);
  glEnable(GL_CULL_FACE);
  for (int pass = 0; pass < 2; ++pass) {
    glStencilFunc(GL_ALWAYS, pass == 0, 0xff);
    glCullFace(pass == 0 ? GL_BACK : GL_FRONT);
    for (int i = 0; i < n; ++i) draw_volume(s[i], &mvp[i]);
  }
  glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
  glStencilFunc(GL_EQUAL, 1, 0xff);
  glStencilOp(GL_KEEP, GL_ZERO, GL_ZERO);
  glDepthFunc(GL_ALWAYS);
  glEnable(GL_BLEND);
  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
#ifdef SHADOW_DEBUG
  glUniform4f(shadow_color, 1, 0, 0, 1);
#else
  /* Reuse the existing stencil shadow pass; the off path remains unchanged. */
  glUniform4f(shadow_color, 0, 0, 0, enhance_on ? 0.55f : SHADOW_ALPHA);
#endif
  glCullFace(GL_BACK);
  for (int i = 0; i < n; ++i) draw_volume(s[i], &mvp[i]);
  p->draws += 3 * n;
  glBindVertexArrayOES(0);
  glDepthFunc(GL_LEQUAL);
  glDisable(GL_BLEND);
  glDepthMask(GL_TRUE);
  glDisable(GL_STENCIL_TEST);
#endif
}

/* what the first draws cost (wpk_warm_stats), by what was new in them: the batch's buffer
 * pool, else its texture, else neither */
enum { WARM_NEW_POOL, WARM_NEW_TEX, WARM_OLD, WARM_KINDS };
static struct {
  int n[WARM_KINDS];
  double ms[WARM_KINDS], max[WARM_KINDS];
} warm_cost;

static double warm_clock(void) {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (double)tv.tv_sec * 1e3 + (double)tv.tv_usec * 1e-3;
}

#include "render_native_warm.inc"

/* a cube's first draw: one triangle over the pixel the scissor leaves, sampling it */
static void warm_cube(GLuint cube) {
  static GLuint prog;
  static const char *vs = "attribute vec3 aPos; varying vec3 vDir;\n"
                          "void main() { gl_Position = vec4(aPos, 1.0); vDir = aPos + vec3(0.0, 0.0, 1.0); }\n";
  static const char *fs = "precision mediump float; uniform samplerCube uCube; varying vec3 vDir;\n"
                          "void main() { gl_FragColor = textureCube(uCube, vDir); }\n";
  static const float pos[9] = { -1, -1, 0, 3, -1, 0, -1, 3, 0 };
  if (
#ifdef WMMT_NATIVE_VK
      !cinder_vk_program_ready(prog)
#else
      !prog
#endif
  ) {
#ifdef WMMT_NATIVE_VK
    native_program_release(&prog);
#endif
    const char *attribs[] = { "aPos" };
#ifdef WMMT_NATIVE_VK
    prog = native_program_create(vs, fs, attribs, 1);
#else
    prog = gl_compile_program(vs, fs, attribs, 1);
#endif
    if (!prog) return;
  }
#ifdef WMMT_NATIVE_VK
  (void)native_warm_cube(prog, cube, pos, sizeof pos);
#else
  GLint was = 0;
  glGetIntegerv(GL_CURRENT_PROGRAM, &was);
  glUseProgram(prog);
  glBindTexture(GL_TEXTURE_CUBE_MAP, cube);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, pos);
  glDrawArrays(GL_TRIANGLES, 0, 3);
  glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
  glUseProgram((GLuint)was);
#endif
}

/* batch b's first triangle with texture tex (index t of the scene's, or 0xFFFF) */
#ifdef WMMT_NATIVE_VK
static int native_warm_draw(const wpk_scene *s, const wpk_batch *b, uint32_t tex, uint32_t t, const render_params *params) {
  if (b->pool >= s->n_pools || !s->pools || !s->tex_warm || (t != 0xFFFF && t >= s->n_tex)) return 0;
  wpk_pool *pl = &s->pools[b->pool];
  int kind = !pl->warm ? WARM_NEW_POOL : t != 0xFFFF && !s->tex_warm[t] ? WARM_NEW_TEX : WARM_OLD;
  double t0 = warm_clock();
  if (!native_warm_material(s, b, tex, params)) return 0;
  if (!s->lit && b->gloss != 0xFFFF && (!params || !params->no_gloss)) s->tex_warm[b->gloss] = 1;
  if (!s->lit && b->gloss != 0xFFFF && b->cube != 0xFFFF && b->cube < s->n_cube && s->cube_warm && (!params || !params->no_gloss)) s->cube_warm[b->cube] = 1;
  double ms = warm_clock() - t0;
  pl->warm = 1;
  if (t != 0xFFFF) s->tex_warm[t] = 1;
  warm_cost.n[kind]++;
  warm_cost.ms[kind] += ms;
  if (ms > warm_cost.max[kind]) warm_cost.max[kind] = ms;
  return 1;
}
#else
static void warm_draw(const wpk_scene *s, const wpk_batch *b, uint32_t tex, uint32_t t) {
  wpk_pool *pl = &s->pools[b->pool];
  int kind = !pl->warm ? WARM_NEW_POOL : t != 0xFFFF && !s->tex_warm[t] ? WARM_NEW_TEX : WARM_OLD;
  double t0 = warm_clock();
  glBindTexture(GL_TEXTURE_2D, tex);
  glBindBuffer(GL_ARRAY_BUFFER, pl->vbo);
  glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, pl->ibo);
  GLsizei stride = (GLsizei)s->stride;
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, (const void *)0);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, (const void *)12);
  glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, stride, (const void *)20);
  glDrawElements(GL_TRIANGLES, b->count < 3 ? (GLsizei)b->count : 3, GL_UNSIGNED_SHORT, (const void *)(uintptr_t)b->ioff);
  if (b->gloss != 0xFFFF && !s->tex_warm[b->gloss]) {
    /* a gloss batch: its gloss texture as well, and its cube with a program that samples one */
    glBindTexture(GL_TEXTURE_2D, s->textures[b->gloss]);
    glDrawElements(GL_TRIANGLES, b->count < 3 ? (GLsizei)b->count : 3, GL_UNSIGNED_SHORT, (const void *)(uintptr_t)b->ioff);
    s->tex_warm[b->gloss] = 1;
  }
  if (b->cube != 0xFFFF && !s->cube_warm[b->cube]) {
    warm_cube(s->cubes[b->cube]);
    s->cube_warm[b->cube] = 1;
  }
  double ms = warm_clock() - t0;
  pl->warm = 1;
  if (t != 0xFFFF) s->tex_warm[t] = 1;
  warm_cost.n[kind]++;
  warm_cost.ms[kind] += ms;
  if (ms > warm_cost.max[kind]) warm_cost.max[kind] = ms;
}
#endif

void wpk_warm_stats(char *out, size_t n) {
  static const char *names[WARM_KINDS] = { "new pool", "new texture", "old" };
  size_t len = (size_t)snprintf(out, n, "first draws:");
  for (int k = 0; k < WARM_KINDS && len < n; ++k)
    len += (size_t)snprintf(out + len, n - len, " %s %d avg %.2f max %.2f ms%s", names[k], warm_cost.n[k],
                            warm_cost.n[k] ? warm_cost.ms[k] / warm_cost.n[k] : 0.0, warm_cost.max[k],
                            k + 1 < WARM_KINDS ? "," : "");
  memset(&warm_cost, 0, sizeof warm_cost);
}

/* whether chunk ch is within reach of eye_local by p's ranges plus margin (as wpk_draw) */
static int chunk_in_reach(const wpk_chunk *ch, const float *eye_local, float margin, const render_params *p) {
  float range = p->range[ch->group < WPK_GROUPS ? ch->group : WPK_SHORT]; /* objects: as wpk_draw */
  return box_distance(ch->lo, ch->hi, eye_local) <= range + margin;
}

/* the chunks wpk_prewarm and wpk_warm* first-draw: the cold ones nearest eye_local first
 * (NULL: as they come), with p only those in its reach plus margin, a batch's first triangle
 * each, into the pixel the scissor leaves */
static int warm_batches(wpk_scene *s, const float *eye_local, float margin, int budget, const render_params *p) {
  int warmed = 0;
  if (!s->warm || !s->n_chunk) return 0; /* not loaded */
#ifndef WMMT_NATIVE_VK
  glEnable(GL_SCISSOR_TEST);
  glScissor(0, 0, 1, 1);
#endif
  while (warmed < budget) {
    /* the next cold chunk (wpk_draw may have drawn the one under way meanwhile) */
    if (s->warm_chunk >= 0 && ((uint32_t)s->warm_chunk >= s->n_chunk || s->warm[s->warm_chunk])) s->warm_chunk = -1;
    if (s->warm_chunk < 0) {
      float best = 1e30f;
      for (uint32_t c = 0; c < s->n_chunk; ++c) {
        const wpk_chunk *ch = &s->chunks[c];
        if (!wpk_chunk_valid(ch, s->n_batch)) { s->warm[c] = 1; continue; }
        if (s->warm[c] || (p && !chunk_in_reach(ch, eye_local, margin, p))) continue;
        float d = eye_local ? box_distance(ch->lo, ch->hi, eye_local) : 0;
        if (d >= best) continue;
        best = d;
        s->warm_chunk = (int)c;
        s->warm_batch = ch->first;
        if (!eye_local) break;
      }
    }
    if (s->warm_chunk < 0) break;
    const wpk_chunk *ch = &s->chunks[s->warm_chunk];
    if (!wpk_chunk_valid(ch, s->n_batch)) {
      s->warm[s->warm_chunk] = 1;
      s->warm_chunk = -1;
      continue;
    }
    if (s->warm_batch < ch->first || s->warm_batch > ch->first + ch->n) s->warm_batch = ch->first;
    if (s->warm_batch < ch->first + ch->n) {
      const wpk_batch *b = &s->batches[s->warm_batch++];
      if (b->count) {
        uint32_t t = b->tex < s->n_tex ? b->tex : 0xFFFF;
#ifdef WMMT_NATIVE_VK
        if (!native_warm_draw(s, b, t == 0xFFFF ? white_tex : s->textures[t], t, p)) {
          --s->warm_batch; /* retry a rejected material, never mark its chunk warm */
          break;
        }
#else
        warm_draw(s, b, t == 0xFFFF ? white_tex : s->textures[t], t);
#endif
        warmed++;
      }
    }
    if (s->warm_batch >= ch->first + ch->n) {
      s->warm[s->warm_chunk] = 1;
      s->warm_chunk = -1;
    }
  }
#ifndef WMMT_NATIVE_VK
  glDisable(GL_SCISSOR_TEST);
#endif
  return warmed;
}

int wpk_prewarm(wpk_scene *s, const mat4 *view_proj, const float *eye_local, float margin, int budget,
                const render_params *p) {
  if (!s->warm || !s->n_chunk) return 0;
#ifdef WMMT_NATIVE_VK
  (void)view_proj;
  native_warm_view = native_scene;
#else
  glUseProgram(progs[0].id);
  glUniformMatrix4fv(progs[0].mvp, 1, GL_FALSE, view_proj->m);
  glUniform2f(progs[0].uv_off, 0, 0);
#endif
  return warm_batches(s, eye_local, margin, budget, p);
}

int wpk_warm_near(wpk_scene *s, const float *eye, float margin, int budget, const render_params *p) {
#ifdef WMMT_NATIVE_VK
  native_warm_view = native_scene;
#endif
  return warm_batches(s, eye, margin, budget, p);
}

int wpk_cold_near(const wpk_scene *s, const float *eye, float margin, const render_params *p) {
  int cold = 0;
  for (uint32_t c = 0; s->warm && c < s->n_chunk; ++c)
    cold += !s->warm[c] && wpk_chunk_valid(&s->chunks[c], s->n_batch) &&
            (!p || chunk_in_reach(&s->chunks[c], eye, margin, p));
  return cold;
}

/* The loading's own program: the scene's vertex layout and texture, no uniforms to set (so
 * one shared by the GL contexts of two threads stays the same), positions as they are. */
static const char *WARM_VS =
  "attribute vec3 aPos; attribute vec2 aUV; attribute vec4 aColor;\n"
  "varying vec2 vUV; varying lowp vec4 vColor;\n"
  "void main() { gl_Position = vec4(aPos, 1.0); vUV = aUV; vColor = aColor; }\n";
static const char *WARM_FS =
  "precision mediump float;\n"
  "uniform sampler2D uTex;\n"
  "varying vec2 vUV; varying lowp vec4 vColor;\n"
  "void main() { gl_FragColor = texture2D(uTex, vUV) * vColor; }\n";

void render_warm_begin(void) {
  static GLuint warm_prog;
  if (
#ifdef WMMT_NATIVE_VK
      !cinder_vk_program_ready(warm_prog)
#else
      !warm_prog
#endif
  ) {
#ifdef WMMT_NATIVE_VK
    native_program_release(&warm_prog);
#endif
    const char *attribs[] = { "aPos", "aUV", "aColor" };
#ifdef WMMT_NATIVE_VK
    warm_prog = native_program_create(WARM_VS, WARM_FS, attribs, 3);
#else
    warm_prog = gl_compile_program(WARM_VS, WARM_FS, attribs, 3);
#endif
  }
#ifdef WMMT_NATIVE_VK
  native_loader_program = warm_prog;
  native_warm_view.target = 0;
  cinder_vk_screen_extent(&native_warm_view.w, &native_warm_view.h);
#else
  glUseProgram(warm_prog);
  glActiveTexture(GL_TEXTURE0);
  glEnableVertexAttribArray(0);
  glEnableVertexAttribArray(1);
  glEnableVertexAttribArray(2);
#endif
}

int wpk_warm(wpk_scene *s, int budget) { return warm_batches(s, NULL, 0, budget, NULL); }

void render_warm_texture(uint32_t tex) {
  /* one triangle over the pixel, from client memory */
#ifdef WMMT_NATIVE_VK
  double t0 = warm_clock();
  if (!native_loader_triangle(native_loader_program, tex, native_warm_destination(), 0, 0, 1)) return;
#else
  static const float pos[9] = { -1, -1, 0, 3, -1, 0, -1, 3, 0 }, uv[6] = { 0, 0, 1, 0, 0, 1 };
  static const unsigned char col[12] = { 0 };
  double t0 = warm_clock();
  glBindTexture(GL_TEXTURE_2D, tex);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, pos);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 0, uv);
  glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, 0, col);
  glDrawArrays(GL_TRIANGLES, 0, 3);
#endif
  double ms = warm_clock() - t0;
  warm_cost.n[WARM_NEW_TEX]++;
  warm_cost.ms[WARM_NEW_TEX] += ms;
  if (ms > warm_cost.max[WARM_NEW_TEX]) warm_cost.max[WARM_NEW_TEX] = ms;
}

int wpk_warm_paints(wpk_scene *s, int budget) {
  int warmed = 0;
#ifndef WMMT_NATIVE_VK
  glEnable(GL_SCISSOR_TEST);
  glScissor(0, 0, 1, 1);
#endif
  for (uint32_t i = 0; i < s->n_paints && warmed < budget; ++i) {
    const wpk_paint_swap *p = &s->paints[i];
#ifdef WMMT_NATIVE_VK
    if (p->src >= s->n_tex || p->dst >= s->n_tex || !s->loaded || !s->tex_warm) continue;
#endif
    if (!s->loaded[p->src] || s->tex_warm[p->src]) continue;
    /* a batch the paint stands in for the texture of */
    for (uint32_t j = 0; j < s->n_batch; ++j)
      if (s->batches[j].tex == p->dst && j < s->next_batch && s->batches[j].count) {
#ifdef WMMT_NATIVE_VK
        if (!native_warm_draw(s, &s->batches[j], s->loaded[p->src], p->src, NULL)) return warmed;
#else
        warm_draw(s, &s->batches[j], s->loaded[p->src], p->src);
#endif
        warmed++;
        break;
      }
#ifndef WMMT_NATIVE_VK
    s->tex_warm[p->src] = 1;
#endif
  }
#ifndef WMMT_NATIVE_VK
  glDisable(GL_SCISSOR_TEST);
#endif
  return warmed;
}

/* render_selftest */
static double st_ms(void) {
  struct timeval tv;
  gettimeofday(&tv, NULL);
  return (double)tv.tv_sec * 1e3 + (double)tv.tv_usec * 1e-3;
}

/* a triangle of quad buffer vbo with texture tex into the pixel; ms till the GPU is done */
#ifdef WMMT_NATIVE_VK
static double st_draw(GLuint vbo, GLuint tex, GLuint target) {
  if (!vbo || !tex || !target || !cinder_vk_finish()) return -1.0;
  double t0=st_ms();
  if (!native_loader_triangle(native_loader_program,tex,(native_scene_view){target,1,1},vbo,0,0) ||
      !cinder_vk_finish()) return -1.0;
  return st_ms()-t0;
}
#else
static double st_draw(GLuint vbo, GLuint tex, GLuint target) {
  glFinish();
  double t0 = st_ms();
#ifdef WMMT_NATIVE_VK
  int recorded = vbo && native_loader_triangle(native_loader_program, tex, (native_scene_view){target,1,1}, vbo, 0, 0);
  if (!recorded) return -1.0;
#else
  (void)target;
  glBindTexture(GL_TEXTURE_2D, tex);
  glBindBuffer(GL_ARRAY_BUFFER, vbo);
  glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, (const void *)0);
  glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 24, (const void *)12);
  glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, 24, (const void *)20);
  glDrawArrays(GL_TRIANGLES, 0, 3);
#endif
  glFinish();
  return st_ms() - t0;
}
#endif

/* a size x size RGB565 texture of noise: mips 0 none, 1 glGenerateMipmap, 2 mip_down;
 * the time of the calls (and of mip_down) into api */
#ifdef WMMT_NATIVE_VK
static GLuint st_texture(int size, int mips, double *api, double *cpu) {
  *api=*cpu=-1.0;
  if(size<=0 || size>16384 || !is_pot(size) || mips<0 || mips>2) return 0;
  uint16_t *px=malloc((size_t)size*size*2*2);
  if(!px) return 0;
  uint32_t r=12345u;
  for(int i=0;i<size*size;++i) { r=r*1103515245u+12345u; px[i]=(uint16_t)(r>>16); }
  if(!cinder_vk_finish()) { free(px); return 0; }
  double t0=st_ms(); *cpu=0;
  cinder_vk_texture_subresource sub[31]={{0,0,px,(size_t)size*size*2,0}};
  int levels=mips?native_scene_levels(size,size):1;
  if(mips==2) {
    uint16_t *src=px,*dst=px+(size_t)size*size;
    for(int w=size,level=1;w>1;++level) {
      double c0=st_ms(); mip_down(src,w,w,dst,0); *cpu+=st_ms()-c0; w/=2;
      sub[level]=(cinder_vk_texture_subresource){(uint32_t)level,0,dst,(size_t)w*w*2,0};
      src=dst; dst+=(size_t)w*w;
    }
  }
  cinder_vk_sampler sampler=native_scene_sampler(mips!=0,1,0); sampler.anisotropy=1.0f;
  const cinder_vk_texture_desc d={.width=size,.height=size,.levels=levels,.layers=1,
    .format=CINDER_VK_TEX_RGB565,.sampler=sampler,.subresources=sub,.subresource_count=mips==2?(size_t)levels:1};
  GLuint tex=mips==1?cinder_vk_texture_generate_mips(&d):cinder_vk_texture_create(&d);
  *api=tex?st_ms()-t0:-1.0;
  if(!tex) *cpu=-1.0;
  free(px); return tex;
}
#else
static GLuint st_texture(int size, int mips, double *api, double *cpu) {
  uint16_t *px = malloc((size_t)size * size * 2 * 2);
  uint32_t r = 12345u;
  for (int i = 0; i < size * size; ++i) {
    r = r * 1103515245u + 12345u;
    px[i] = (uint16_t)(r >> 16);
  }
  glFinish();
  double t0 = st_ms();
  GLuint tex;
  glGenTextures(1, &tex);
  glBindTexture(GL_TEXTURE_2D, tex);
  glPixelStorei(GL_UNPACK_ALIGNMENT, 2);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, size, size, 0, GL_RGB, GL_UNSIGNED_SHORT_5_6_5, px);
  *cpu = 0;
  if (mips == 1) glGenerateMipmap(GL_TEXTURE_2D);
  if (mips == 2) {
    uint16_t *src = px, *dst = px + (size_t)size * size;
    for (int w = size, level = 1; w > 1; ++level) {
      double c0 = st_ms();
      mip_down(src, w, w, dst, 0);
      *cpu += st_ms() - c0;
      w /= 2;
      glTexImage2D(GL_TEXTURE_2D, level, GL_RGB, w, w, 0, GL_RGB, GL_UNSIGNED_SHORT_5_6_5, dst);
      src = dst;
      dst += (size_t)w * w;
    }
  }
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, mips ? mip_filter() : GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
  *api = st_ms() - t0;
  free(px);
  return tex;
}
#endif

#ifndef GL_COMPRESSED_RGB_PVRTC_4BPPV1_IMG
#define GL_COMPRESSED_RGB_PVRTC_4BPPV1_IMG 0x8C00
#endif

#ifdef WMMT_NATIVE_VK
void render_selftest(char *out, size_t n) {
  if(!n) return;
  GLuint rb=native_target_attachment(1,1,CINDER_VK_STORAGE_RGB565,1,0,0);
  GLuint fb=rb?native_target_compose(rb,CINDER_VK_IMAGE_ATTACHMENT,0,CINDER_VK_IMAGE_NONE,0,1,1):0;
  if(!fb) {
    cinder_vk_target_destroy(fb); cinder_vk_attachment_destroy(rb);
    snprintf(out,n,"selftest unavailable: native 1x1 target"); return;
  }
  render_warm_begin();
  static const float tri[18]={-1,-1,0,0,0,0,3,-1,0,2,0,0,-1,3,0,0,2,0};
  float v[18]; memcpy(v,tri,sizeof v);
  for(int k=0;k<3;++k) memset(&v[6*k+5],0xff,4);
  GLuint vbo=cinder_vk_buffer_create(sizeof v,v);
  size_t len=0; GLuint keep=0;
  if(!cinder_vk_program_ready(native_loader_program) || !cinder_vk_finish()) {
    snprintf(out,n,"selftest unavailable: native resources/finish"); goto done;
  }
  (void)st_draw(vbo,white_tex,fb); /* missing triangle buffer cannot become client0; batch is independent */
  len+=(size_t)snprintf(out+len,n-len,"selftest native host wall ms (not physical GPU timing):");
  static const struct {int size,mips;const char *name;} T[]={
    {256,1,"256 genmip"},{256,2,"256 cpumip"},{256,0,"256 nomip"},
    {512,1,"512 genmip"},{512,2,"512 cpumip"},{512,0,"512 nomip"}};
  for(size_t i=0;i<sizeof T/sizeof T[0] && len<n;++i) {
    double api,cpu; GLuint tex=st_texture(T[i].size,T[i].mips,&api,&cpu);
    double first=st_draw(vbo,tex,fb),again=st_draw(vbo,tex,fb);
    if(!tex || first<0 || again<0)
      len+=(size_t)snprintf(out+len,n-len," | %s unavailable",T[i].name);
    else len+=(size_t)snprintf(out+len,n-len," | %s api %.2f cpu %.2f first %.2f again %.2f",T[i].name,api,cpu,first,again);
    if(T[i].mips==2 && !keep && tex) keep=tex;
    else cinder_vk_texture_destroy(tex);
  }
  if(len<n) len+=(size_t)snprintf(out+len,n-len," | pvrtc unavailable (native unsupported)");
  if(len<n) {
    enum {NV=4000,NI=9000};
    unsigned char *vb=calloc(NV,24); uint16_t *ib=malloc(NI*2);
    if(ib) for(int i=0;i<NI;++i) ib[i]=(uint16_t)(i%NV);
    int finished=cinder_vk_finish(); double t0=st_ms();
    GLuint b[2]={finished&&vb?cinder_vk_buffer_create(NV*24,vb):0,finished&&ib?cinder_vk_buffer_create(NI*2,ib):0};
    double api=st_ms()-t0,first=-1,again=-1;
    for(int pass=0;pass<2;++pass) {
      if(!b[0] || !b[1] || !keep || !cinder_vk_finish()) continue;
      double d0=st_ms();
      if(native_loader_triangle(native_loader_program,keep,(native_scene_view){fb,1,1},b[0],b[1],0) && cinder_vk_finish())
        *(pass?&again:&first)=st_ms()-d0;
    }
    if(first<0 || again<0) snprintf(out+len,n-len," | batch unavailable");
    else snprintf(out+len,n-len," | batch %d verts api %.2f first %.2f again %.2f",NV,api,first,again);
    cinder_vk_buffer_destroy(b[0]); cinder_vk_buffer_destroy(b[1]); free(vb); free(ib);
  }
done:
  cinder_vk_texture_destroy(keep); cinder_vk_buffer_destroy(vbo);
  cinder_vk_target_destroy(fb); cinder_vk_attachment_destroy(rb);
}
#else
void render_selftest(char *out, size_t n) {
  GLint prev_fb = 0;
#ifdef WMMT_NATIVE_VK
  prev_fb = (GLint)native_scene.target;
#else
  GLint vp[4];
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &prev_fb);
  glGetIntegerv(GL_VIEWPORT, vp);
#endif
  GLuint rb, fb;
  glGenRenderbuffers(1, &rb);
  glBindRenderbuffer(GL_RENDERBUFFER, rb);
  glRenderbufferStorage(GL_RENDERBUFFER, GL_RGB565, 1, 1);
  glGenFramebuffers(1, &fb);
  glBindFramebuffer(GL_FRAMEBUFFER, fb);
  glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, rb);
#ifndef WMMT_NATIVE_VK
  glViewport(0, 0, 1, 1);
  glBindVertexArrayOES(0);
#endif
  render_warm_begin();
  static const float tri[18] = { -1, -1, 0, 0, 0, 0, 3, -1, 0, 2, 0, 0, -1, 3, 0, 0, 2, 0 };
  float v[18];
  memcpy(v, tri, sizeof v);
  for (int k = 0; k < 3; ++k) memset(&v[6 * k + 5], 0xff, 4); /* white */
  GLuint vbo;
#ifdef WMMT_NATIVE_VK
  vbo = cinder_vk_buffer_create(sizeof v, v);
#else
  glGenBuffers(1, &vbo);
  glBindBuffer(GL_ARRAY_BUFFER, vbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof v, v, GL_STATIC_DRAW);
#endif
  st_draw(vbo, white_tex, fb); /* the program's and the buffer's first use */
  size_t len = 0;
  len += (size_t)snprintf(out + len, n - len, "selftest (first draw = upload left to the driver):");
  static const struct { int size, mips; const char *name; } T[] = {
    { 256, 1, "256 genmip" }, { 256, 2, "256 cpumip" }, { 256, 0, "256 nomip" },
    { 512, 1, "512 genmip" }, { 512, 2, "512 cpumip" }, { 512, 0, "512 nomip" },
  };
  GLuint keep = 0;
  for (size_t i = 0; i < sizeof T / sizeof T[0] && len < n; ++i) {
    double api, cpu;
    GLuint tex = st_texture(T[i].size, T[i].mips, &api, &cpu);
    double first = st_draw(vbo, tex, fb), again = st_draw(vbo, tex, fb);
    len += (size_t)snprintf(out + len, n - len, " | %s api %.2f cpu %.2f first %.2f again %.2f", T[i].name, api, cpu,
                            first, again);
    if (T[i].mips == 2 && !keep) keep = tex;
    else glDeleteTextures(1, &tex);
  }
  /* PVRTC 4 bpp (noise for its blocks: the upload's cost is the same) */
  const char *ext = (const char *)glGetString(GL_EXTENSIONS);
  if (ext && strstr(ext, "GL_IMG_texture_compression_pvrtc") && len < n) {
    for (int size = 256; size <= 512 && len < n; size *= 2) {
      size_t bytes = (size_t)size * size / 2;
      unsigned char *data = malloc(bytes);
      for (size_t i = 0; i < bytes; ++i) data[i] = (unsigned char)(i * 2654435761u >> 13);
      glFinish();
      double t0 = st_ms();
      GLuint tex;
      glGenTextures(1, &tex);
      glBindTexture(GL_TEXTURE_2D, tex);
      for (int w = size, level = 0; w >= 1; w /= 2, ++level) {
        int bw = w < 8 ? 8 : w; /* PVRTC 4 bpp: 32 bytes at least */
        glCompressedTexImage2D(GL_TEXTURE_2D, level, GL_COMPRESSED_RGB_PVRTC_4BPPV1_IMG, w, w, 0,
                               (GLsizei)(bw * bw / 2), data);
      }
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, mip_filter());
      tex_aniso();
      glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
      double api = st_ms() - t0;
      double first = st_draw(vbo, tex, fb), again = st_draw(vbo, tex, fb);
      len += (size_t)snprintf(out + len, n - len, " | %d pvrtc api %.2f first %.2f again %.2f err 0x%x", size, api, first,
                              again, glGetError());
      glDeleteTextures(1, &tex);
      free(data);
    }
  }
  /* a course batch's size of vertices and indices: their first use */
  if (len < n) {
    enum { NV = 4000, NI = 9000 };
    unsigned char *vb = calloc(NV, 24);
    uint16_t *ib = malloc(NI * 2);
#ifdef WMMT_NATIVE_VK
    if (ib)
#endif
    for (int i = 0; i < NI; ++i) ib[i] = (uint16_t)(i % NV);
    glFinish();
    double t0 = st_ms();
    GLuint b[2];
#ifdef WMMT_NATIVE_VK
    b[0] = vb ? cinder_vk_buffer_create(NV * 24, vb) : 0;
    b[1] = ib ? cinder_vk_buffer_create(NI * 2, ib) : 0;
#else
    glGenBuffers(2, b);
    glBindBuffer(GL_ARRAY_BUFFER, b[0]);
    glBufferData(GL_ARRAY_BUFFER, NV * 24, vb, GL_STATIC_DRAW);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, b[1]);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER, NI * 2, ib, GL_STATIC_DRAW);
#endif
    double api = st_ms() - t0;
    double first = 0, again = 0;
    for (int pass = 0; pass < 2; ++pass) {
      glFinish();
      double d0 = st_ms();
#ifdef WMMT_NATIVE_VK
      int recorded = b[0] && b[1] && native_loader_triangle(native_loader_program, keep, (native_scene_view){fb,1,1}, b[0], b[1], 0);
#else
      glBindTexture(GL_TEXTURE_2D, keep);
      glBindBuffer(GL_ARRAY_BUFFER, b[0]);
      glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, (const void *)0);
      glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 24, (const void *)12);
      glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, 24, (const void *)20);
      glDrawElements(GL_TRIANGLES, 3, GL_UNSIGNED_SHORT, 0);
#endif
      glFinish();
      *(pass ? &again : &first) = st_ms() - d0;
#ifdef WMMT_NATIVE_VK
      if (!recorded) *(pass ? &again : &first) = -1.0;
#endif
    }
    len += (size_t)snprintf(out + len, n - len, " | batch %d verts api %.2f first %.2f again %.2f", NV, api, first, again);
#ifdef WMMT_NATIVE_VK
    cinder_vk_buffer_destroy(b[0]);
    cinder_vk_buffer_destroy(b[1]);
#else
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);
    glDeleteBuffers(2, b);
#endif
    free(vb);
    free(ib);
  }
  glDeleteTextures(1, &keep);
#ifdef WMMT_NATIVE_VK
  cinder_vk_buffer_destroy(vbo);
#else
  glDeleteBuffers(1, &vbo);
  glBindBuffer(GL_ARRAY_BUFFER, 0);
#endif
#ifndef WMMT_NATIVE_VK
  glDisableVertexAttribArray(1);
  glDisableVertexAttribArray(2);
#endif
  glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)prev_fb);
  glDeleteFramebuffers(1, &fb);
  glDeleteRenderbuffers(1, &rb);
#ifndef WMMT_NATIVE_VK
  glViewport(vp[0], vp[1], vp[2], vp[3]);
#endif
}
#endif
