/* Loader/prewarm has its own explicit per-thread destination. Warm-only submits
 * compile/materialize the pipeline and never start/record a frame. Selftest uses
 * the same bounded layout builder but explicitly requests a real draw. */
#ifdef WMMT_NATIVE_VK
static __thread native_scene_view native_warm_view;
static __thread uint32_t native_loader_program;

static native_scene_view native_warm_destination(void) {
  native_scene_view v=native_warm_view;
  if (v.w<=0 || v.h<=0) { v.target=0; cinder_vk_screen_extent(&v.w,&v.h); }
  return v;
}

static int native_warm_init(cinder_vk_draw *d, uint32_t program, native_scene_view v, int warm) {
  if (!cinder_vk_draw_init(d,program,v.target,v.w,v.h)) return 0;
  d->warm_only=warm;
  d->pipeline.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
  d->pipeline.color_mask=15; d->pipeline.depth_compare=VK_COMPARE_OP_LESS_OR_EQUAL;
  d->pipeline.depth_test=d->pipeline.depth_write=d->pipeline.stencil=VK_FALSE;
  d->pipeline.cull=VK_CULL_MODE_NONE; d->pipeline.asset_front=VK_FRONT_FACE_COUNTER_CLOCKWISE;
  d->pipeline.blend=VK_FALSE; d->pipeline.blend_op=VK_BLEND_OP_ADD;
  d->pipeline.src_blend=VK_BLEND_FACTOR_ONE; d->pipeline.dst_blend=VK_BLEND_FACTOR_ZERO;
  d->scissor[2]=d->scissor[3]=1;
  return 1;
}

static int native_warm_cube(uint32_t program, uint32_t cube, const float *pos, size_t bytes) {
  cinder_vk_draw d;
  if (!native_warm_init(&d,program,native_warm_destination(),1)) return 0;
  d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32B32_SFLOAT,.stride=3*sizeof(float),.data=pos,.bytes=bytes};
  d.count=3;
  return cinder_vk_texture(&d,"uCube",cube) && cinder_vk_submit(&d);
}

static int native_warm_material(const wpk_scene *s, const wpk_batch *b, uint32_t texture, const render_params *params) {
  if (!s || !b || !texture || b->pool>=s->n_pools || !b->count || !s->pools) return 0;
  if (s->lit && b->prog>=WPK_LIT_PROGS) return 0;
  int gloss=!s->lit && b->gloss!=0xffff && (!params || !params->no_gloss);
  if (gloss && (b->gloss>=s->n_tex || b->cube>=s->n_cube || !s->textures || !s->cubes)) return 0;
  if (s->lit && ((b->env!=0xffff && (b->env>=s->n_tex || !s->textures)) ||
      (b->spec!=0xffff && (b->spec>=s->n_tex || !s->textures)))) return 0;
  int blend=(b->flags&WPK_BLEND_MASK)!=0, cutout=!blend && b->cutout && !s->solid;
  uint32_t program=s->lit?lit_progs[2*b->prog+cutout].id:gloss?gloss_progs[cutout].id:progs[cutout].id;
  cinder_vk_draw d;
  if (!native_warm_init(&d,program,native_warm_destination(),1)) return 0;
  native_mesh(&d,s,b);
  d.count=b->count<3?b->count:3;
  d.pipeline.depth_test=!params || !params->no_depth_test; d.pipeline.depth_write=!blend;
  d.pipeline.cull=s->two_sided?VK_CULL_MODE_NONE:VK_CULL_MODE_BACK_BIT;
  d.pipeline.blend=blend; d.pipeline.src_blend=VK_BLEND_FACTOR_SRC_ALPHA;
  d.pipeline.dst_blend=(b->flags&WPK_BLEND_MASK)==2?VK_BLEND_FACTOR_ONE:VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
  mat4 identity=mat4_identity();
  const float zero[4]={0,0,0,0}, one[3]={1,1,1}, eye[3]={0,0,1}, light[3]={0,1,0}, fog[2]={1e30f,1e29f};
  float power=b->power;
  /* All uniforms are packet values, including optional WET/FRAME_ENV uniforms.
   * These are prewarm constants, never a borrowed render_begin uniform shadow. */
  int ok=cinder_vk_uniform(&d,"uMVP",identity.m,sizeof identity.m) && cinder_vk_uniform(&d,"uMV",identity.m,sizeof identity.m) &&
    cinder_vk_uniform(&d,"uEye",eye,sizeof eye) && cinder_vk_uniform(&d,"uFog",fog,sizeof fog) &&
    cinder_vk_uniform(&d,"uFogColor",zero,3*sizeof(float)) && cinder_vk_uniform(&d,"uGrade",one,sizeof one) &&
    cinder_vk_uniform(&d,"uUVOff",zero,2*sizeof(float)) && cinder_vk_uniform(&d,"uWet",zero,sizeof(float)) &&
    cinder_vk_uniform(&d,"uHorizon",zero,3*sizeof(float)) && cinder_vk_uniform(&d,"uL0",light,sizeof light) &&
    cinder_vk_uniform(&d,"uL1",light,sizeof light) && cinder_vk_uniform(&d,"uD0",one,sizeof one) &&
    cinder_vk_uniform(&d,"uD1",zero,3*sizeof(float)) && cinder_vk_uniform(&d,"uAmb",one,sizeof one) &&
    cinder_vk_uniform(&d,"uPower",&power,sizeof power) && cinder_vk_uniform(&d,"uOver",(float[2]){0,1},2*sizeof(float)) &&
    cinder_vk_uniform(&d,"uOverDir",(float[2]){sinf(OVER_PITCH),cosf(OVER_PITCH)},2*sizeof(float)) &&
    cinder_vk_uniform(&d,"uFrameK",zero,sizeof(float)) && cinder_vk_texture(&d,"uTex",texture);
  /* Upload-default sampler state is an intentional immutable resource bridge. */
  if (s->lit) {
    uint32_t ao=ao_on && b->tex<s->n_ao && s->ao_tex && s->ao_tex[b->tex]?s->ao_tex[b->tex]:white_tex;
    ok=ok && cinder_vk_texture(&d,"uAO",ao) && cinder_vk_texture(&d,"uOverTex",white_tex) && cinder_vk_texture(&d,"uFrame",white_tex);
    if (b->prog!=WPK_LIT_FF) ok=ok && cinder_vk_texture(&d,"uEnv",b->env==0xffff?white_tex:s->textures[b->env]) &&
      cinder_vk_texture(&d,"uSpec",b->spec==0xffff?white_tex:s->textures[b->spec]);
  } else if (gloss) ok=ok && cinder_vk_texture(&d,"uGloss",s->textures[b->gloss]) && cinder_vk_texture(&d,"uCube",s->cubes[b->cube]);
  else ok=ok && cinder_vk_texture(&d,"uFrame",white_tex);
  return ok && cinder_vk_submit(&d);
}

static int native_loader_triangle(uint32_t program, uint32_t texture, native_scene_view target,
    uint32_t vbo, uint32_t ibo, int warm) {
  static const float pos[9]={-1,-1,0,3,-1,0,-1,3,0}, uv[6]={0,0,1,0,0,1};
  static const unsigned char color[12]={0};
  cinder_vk_draw d;
  if (!native_warm_init(&d,program,target,warm)) return 0;
  if (vbo) {
    d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32B32_SFLOAT,.stride=24,.buffer=vbo};
    d.attributes[1]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=24,.buffer=vbo,.offset=12};
    d.attributes[2]=(cinder_vk_attribute){.format=VK_FORMAT_R8G8B8A8_UNORM,.stride=24,.buffer=vbo,.offset=20};
  } else {
    d.attributes[0]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32B32_SFLOAT,.stride=12,.data=pos,.bytes=sizeof pos};
    d.attributes[1]=(cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT,.stride=8,.data=uv,.bytes=sizeof uv};
    d.attributes[2]=(cinder_vk_attribute){.format=VK_FORMAT_R8G8B8A8_UNORM,.stride=4,.data=color,.bytes=sizeof color};
  }
  d.count=3;
  if (ibo) { d.indexed=VK_TRUE; d.index_type=VK_INDEX_TYPE_UINT16; d.index_buffer=ibo; }
  return cinder_vk_texture(&d,"uTex",texture) && cinder_vk_submit(&d);
}
#endif
