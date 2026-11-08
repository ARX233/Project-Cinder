/* Explicit scene packets. CPU visibility/material selection remains shared in
 * meaning with GLES; Vulkan bindings/uniforms/pipeline are fully specified here.
 * No GL state is queried, snapshotted or used by this path. */
#ifdef WMMT_NATIVE_VK
static void native_mesh(cinder_vk_draw *d, const wpk_scene *s, const wpk_batch *b) {
  const wpk_pool *pl = &s->pools[b->pool];
  d->attributes[0] = (cinder_vk_attribute){.format=VK_FORMAT_R32G32B32_SFLOAT, .stride=s->stride, .buffer=pl->vbo};
  d->attributes[1] = (cinder_vk_attribute){.format=VK_FORMAT_R32G32_SFLOAT, .stride=s->stride, .buffer=pl->vbo, .offset=12};
  d->attributes[2] = (cinder_vk_attribute){.format=VK_FORMAT_R8G8B8A8_UNORM, .stride=s->stride, .buffer=pl->vbo, .offset=20};
  if (s->lit)
    d->attributes[3] = (cinder_vk_attribute){.format=VK_FORMAT_R16G16B16_SNORM, .stride=s->stride, .buffer=pl->vbo, .offset=24};
  if (pl->nbo)
    d->attributes[3] = (cinder_vk_attribute){.format=VK_FORMAT_R16G16B16_SNORM, .stride=8, .buffer=pl->nbo};
  d->indexed = VK_TRUE; d->index_buffer = pl->ibo; d->index_offset = b->ioff; d->count = b->count;
}
static int native_scene_packet(cinder_vk_draw *d, const wpk_scene *s, const wpk_batch *b,
    const mat4 *mvp, const mat4 *model, const float eye[3], int kind, const render_params *p, float wet, const float horizon[3]) {
  int cutout = kind == WPK_CUTOUT;
  int gloss = !s->lit && b->gloss != 0xffff && !p->no_gloss;
  uint32_t program = s->lit ? lit_progs[2*b->prog+cutout].id : gloss ? gloss_progs[cutout].id : progs[cutout].id;
  if (!cinder_vk_draw_init(d, program, native_scene.target, native_scene.w, native_scene.h)) return 0;
  native_mesh(d, s, b);
  d->pipeline.depth_test = !p->no_depth_test; d->pipeline.depth_write = kind != WPK_BLEND;
  d->pipeline.cull = s->two_sided ? VK_CULL_MODE_NONE : VK_CULL_MODE_BACK_BIT;
  d->pipeline.blend = kind == WPK_BLEND;
  d->pipeline.src_blend = VK_BLEND_FACTOR_SRC_ALPHA;
  d->pipeline.dst_blend = (b->flags & WPK_BLEND_MASK) == 2 ? VK_BLEND_FACTOR_ONE : VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
  int ok = cinder_vk_uniform(d, "uMVP", mvp->m, sizeof mvp->m) &&
    cinder_vk_uniform(d, "uEye", eye, 3*sizeof *eye) &&
    cinder_vk_uniform(d, "uFog", (float[2]){p->fog_far,p->fog_near}, 2*sizeof(float)) &&
    cinder_vk_uniform(d, "uFogColor", p->fog_color, sizeof p->fog_color) &&
    cinder_vk_texture(d, "uTex", b->tex == 0xffff ? white_tex : s->textures[b->tex]);
  if (!s->lit) {
    float grade[3] = {1,1,1};
    if (enhance_on) enhance_grade(p, s->tex_wet && b->tex < s->n_tex && s->tex_wet[b->tex] && !(b->flags & WPK_BLEND_MASK), grade);
    else if (p->grade[0] > 0) memcpy(grade,p->grade,sizeof grade);
    float uv[2] = {p->uv_shift[0],p->uv_shift[1]};
    if (b->flags & ~WPK_BLEND_MASK) {
      int cols=((b->flags>>2)&7)+1, rows=((b->flags>>5)&7)+1;
      int frames=((b->flags>>8)&15)+1, fps2=(b->flags>>12)&15;
      int frame=(int)(p->time*(float)fps2*0.5f)%frames;
      uv[0]+=(float)(frame%cols)/(float)cols; uv[1]+=(float)(frame/cols%rows)/(float)rows;
    }
    ok = ok && cinder_vk_uniform(d,"uGrade",grade,sizeof grade) && cinder_vk_uniform(d,"uUVOff",uv,sizeof uv);
    if (gloss) {
      ok = ok && cinder_vk_texture(d,"uGloss",s->textures[b->gloss]) && cinder_vk_texture(d,"uCube",s->cubes[b->cube]);
    } else {
      float w = s->tex_wet && b->tex < s->n_tex && s->tex_wet[b->tex] ? wet : 0;
      ok = ok && cinder_vk_uniform(d,"uWet",&w,sizeof w) && cinder_vk_uniform(d,"uHorizon",horizon,3*sizeof(float)) &&
        cinder_vk_texture(d,"uFrame",native_frame_texture ? native_frame_texture : white_tex);
    }
  } else {
    lit_draw ld; lit_begin(&ld,mvp,model,eye,p);
    int ff = b->prog == WPK_LIT_FF;
    float diffuse[2][3], ambient[3];
    for (int k=0;k<3;++k) {
      for (int i=0;i<2;++i) diffuse[i][k]=p->light_diffuse[i][k]*(ff?p->material_diffuse[k]:1);
      ambient[k]=p->ambient[k]*(ff?p->material_ambient[k]:1);
    }
    float power=b->power, fk=enhance_on?frame_k*1.12f:frame_k;
    if (enhance_on && power>=0 && power<=1) power*=0.88f;
    uint32_t ao=ao_on && b->tex<s->n_ao && s->ao_tex[b->tex] ? s->ao_tex[b->tex] : white_tex;
    ok = ok && cinder_vk_uniform(d,"uMV",ld.mv.m,sizeof ld.mv.m) &&
      cinder_vk_uniform(d,"uL0",ld.l[0],sizeof ld.l[0]) && cinder_vk_uniform(d,"uL1",ld.l[1],sizeof ld.l[1]) &&
      cinder_vk_uniform(d,"uD0",diffuse[0],sizeof diffuse[0]) && cinder_vk_uniform(d,"uD1",diffuse[1],sizeof diffuse[1]) &&
      cinder_vk_uniform(d,"uAmb",ambient,sizeof ambient) &&
      cinder_vk_uniform(d,"uOver",(float[2]){p->over,over_inv_tan},2*sizeof(float)) &&
      cinder_vk_uniform(d,"uOverDir",(float[2]){sinf(OVER_PITCH),cosf(OVER_PITCH)},2*sizeof(float)) &&
      cinder_vk_uniform(d,"uPower",&power,sizeof power) && cinder_vk_uniform(d,"uFrameK",&fk,sizeof fk) &&
      cinder_vk_texture(d,"uAO",ao) && cinder_vk_texture(d,"uOverTex",native_over_texture?native_over_texture:white_tex) &&
      cinder_vk_texture(d,"uFrame",native_frame_texture?native_frame_texture:white_tex);
    if (b->prog != WPK_LIT_FF) {
      ok = ok && cinder_vk_texture(d,"uEnv",b->env==0xffff?white_tex:s->textures[b->env]) &&
        cinder_vk_texture(d,"uSpec",b->spec==0xffff?white_tex:s->textures[b->spec]);
    }
  }
  return ok;
}
static void native_scene_draw(const wpk_scene *s, const mat4 *vp, const mat4 *model,
    const float *eye, int pass, render_params *p, int limited, uint32_t group) {
  mat4 mvp = mat4_mul(*vp,*model);
  float wet=!s->lit && s->tex_wet && frame_wet ? p->wet : 0, horizon[3]={0,0,0};
  if (wet>0) {
    float f[3]={-p->view.m[2],0,-p->view.m[10]}, norm=sqrtf(f[0]*f[0]+f[2]*f[2]);
    float a[3]={eye[0]+f[0]/(norm+1e-6f)*1e5f,eye[1],eye[2]+f[2]/(norm+1e-6f)*1e5f};
    const float *m=mvp.m;
    float cy=m[1]*a[0]+m[5]*a[1]+m[9]*a[2]+m[13], cw=m[3]*a[0]+m[7]*a[1]+m[11]*a[2]+m[15];
    if (norm<1e-3f || cw<=0 || blur.w<=0 || blur.h<=0) wet=0;
    else { horizon[0]=1.0f/(float)blur.w; horizon[1]=1.0f/(float)blur.h; horizon[2]=0.5f+0.5f*cy/cw; }
  }
  for (uint32_t c=0;c<s->n_chunk;++c) {
    const wpk_chunk *ch=&s->chunks[c];
    if (!wpk_chunk_valid(ch,s->n_batch) || (limited && ch->group!=group)) continue;
    int story_part=render_story_part_visibility(p,limited,ch->group);
    if (story_part==0) continue;
    float body_y=render_story_body_offset(p,limited,ch->group);
    mat4 cm=*model,cmvp=mvp; float ce[3]={eye[0],eye[1],eye[2]};
    if (body_y!=0.0f) render_story_translate_y(model,vp,eye,body_y,&cm,&cmvp,ce);
    int wheel=limited?-1:ch->group>=WPK_WHEEL && ch->group<WPK_WHEEL+4?(int)(ch->group-WPK_WHEEL):-1;
    float range=0;
    if (!limited) {
      if (ch->group>=WPK_CTIRE && ch->group<WPK_CTIRE+4) {
        if (!p->wheel_custom) continue;
        wheel=(int)(ch->group-WPK_CTIRE);
      } else if (wheel>=0 && p->wheel_custom) continue;
      if (wheel>=0 && p->wheel_side && wheel!=p->wheel_side-1) continue;
      if (wheel>=0) range=p->range[WPK_GROUND];
      else if (ch->group==WPK_LAMP_OFF || ch->group==WPK_LAMP_ON) {
        if ((ch->group==WPK_LAMP_ON)!=(p->lamps_on!=0)) continue;
        range=p->range[WPK_GROUND];
      } else if (ch->group==WPK_BRAKE_RUN || ch->group==WPK_BRAKE_STOP || ch->group==WPK_BRAKE_LIGHT) {
        if (!p->lamps_on || (ch->group==WPK_BRAKE_STOP && !p->braking) || (ch->group==WPK_BRAKE_RUN && p->braking)) continue;
        range=p->range[WPK_GROUND];
      } else if (ch->group>WPK_BRAKE_HIGH && ch->group<WPK_BRAKE_WING2+0x20) {
        if (!p->lamps_on || !p->braking || p->wing<0 || p->wing>4 || !(ch->group>>p->wing&1)) continue;
        range=p->range[WPK_GROUND];
      } else if (ch->group>=WPK_MIRROR && ch->group<WPK_BONNET+4) {
        uint32_t shown=ch->group<WPK_WING?WPK_MIRROR+(uint32_t)p->mirror:
          ch->group<WPK_BONNET?(p->wing<4?WPK_WING+(uint32_t)p->wing:0):WPK_BONNET+(uint32_t)p->bonnet;
        if (ch->group!=shown) continue;
        range=p->range[WPK_GROUND];
      } else if (story_part>0) range=p->range[WPK_GROUND];
      else if (ch->group<WPK_GROUPS) range=p->range[ch->group];
      else {
        uint32_t obj=ch->group-WPK_GROUPS;
        if (!p->object_visible || p->n_objects<=0 || obj>=(uint32_t)p->n_objects || !p->object_visible[obj]) continue;
        range=p->range[WPK_SHORT];
      }
      if (box_distance(ch->lo,ch->hi,ce)>range) continue;
    }
    if (box_outside(&cmvp,ch->lo,ch->hi)) continue;
    if (wheel>=0 && p->wheels) {
      const float *t=p->wheels[wheel];
      float center[3]={0.5f*(ch->lo[0]+ch->hi[0]),0.5f*(ch->lo[1]+ch->hi[1]),0.5f*(ch->lo[2]+ch->hi[2])};
      float sn=sinf(p->wheel_rot[wheel]), cs=cosf(p->wheel_rot[wheel]);
      mat4 w=mat4_identity();
      for (int r=0;r<3;++r) { w.m[r]=t[r]; w.m[4+r]=t[4+r]*cs+t[8+r]*sn; w.m[8+r]=-t[4+r]*sn+t[8+r]*cs; }
      float at[3]={center[0],p->wheels_hub?center[1]:t[13],center[2]};
      for (int r=0;r<3;++r) w.m[12+r]=at[r]-(w.m[r]*center[0]+w.m[4+r]*center[1]+w.m[8+r]*center[2]);
      cm=mat4_mul(*model,w); cmvp=mat4_mul(*vp,cm);
      float d[3]={eye[0]-w.m[12],eye[1]-w.m[13],eye[2]-w.m[14]};
      for (int r=0;r<3;++r) ce[r]=w.m[4*r]*d[0]+w.m[4*r+1]*d[1]+w.m[4*r+2]*d[2];
    } else if (wheel>=0 && p->wheel_drop!=0) {
      mat4 w=mat4_identity(); w.m[13]=-p->wheel_drop;
      cm=mat4_mul(*model,w); cmvp=mat4_mul(*vp,cm); ce[1]+=p->wheel_drop;
    }
    if (!s->warm[c]) { s->warm[c]=1; ++p->new_chunks; }
    for (uint32_t i=ch->first;i<ch->first+ch->n;++i) {
      const wpk_batch *b=&s->batches[i];
      if (!b->count) continue;
      int blend=b->flags&WPK_BLEND_MASK;
      int kind=blend?WPK_BLEND:b->cutout&&!s->solid?WPK_CUTOUT:WPK_OPAQUE;
      if (kind!=pass || b->pool>=s->n_pools) continue;
      cinder_vk_draw packet;
      if (!native_scene_packet(&packet,s,b,&cmvp,&cm,ce,kind,p,wet,horizon) || !cinder_vk_submit(&packet)) continue;
      if (b->tex!=0xffff) s->tex_warm[b->tex]=1;
      if (!s->lit && b->gloss!=0xffff && !p->no_gloss) s->tex_warm[b->gloss]=1;
      s->pools[b->pool].warm=1; ++p->draws; p->triangles+=(int)b->count/3;
    }
  }
}

static void native_shadow_draw(const wpk_scene *const *scenes, const mat4 *matrices, int n, render_params *p) {
  for (int stage=0;stage<3;++stage) for (int i=0;i<n;++i) {
    const wpk_scene *s=scenes[i]; const mat4 *mvp=&matrices[i];
    cinder_vk_draw d;
    if (!cinder_vk_draw_init(&d,shadow_prog,native_scene.target,native_scene.w,native_scene.h)) return;
    d.pipeline.depth_test=VK_TRUE; d.pipeline.depth_write=VK_FALSE;
    d.pipeline.depth_compare=stage==2?VK_COMPARE_OP_ALWAYS:VK_COMPARE_OP_LESS_OR_EQUAL;
    d.pipeline.stencil=VK_TRUE; d.pipeline.stencil_compare=stage==2?VK_COMPARE_OP_EQUAL:VK_COMPARE_OP_ALWAYS;
    d.stencil_reference=stage==1?0:1;
    d.pipeline.depth_fail=stage==2?VK_STENCIL_OP_ZERO:VK_STENCIL_OP_KEEP;
    d.pipeline.depth_pass=stage==2?VK_STENCIL_OP_ZERO:VK_STENCIL_OP_REPLACE;
    d.pipeline.cull=stage==1?VK_CULL_MODE_FRONT_BIT:VK_CULL_MODE_BACK_BIT;
    d.pipeline.color_mask=stage==2?15:0;
    d.pipeline.blend=stage==2; d.pipeline.src_blend=VK_BLEND_FACTOR_SRC_ALPHA;
    d.pipeline.dst_blend=VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
#ifdef SHADOW_DEBUG
    const float color[4]={1,0,0,1};
#else
    const float color[4]={0,0,0,enhance_on?0.55f:SHADOW_ALPHA};
#endif
    if (!cinder_vk_uniform(&d,"uMVP",mvp->m,sizeof mvp->m) || !cinder_vk_uniform(&d,"uColor",color,sizeof color)) return;
    for (uint32_t c=0;c<s->n_chunk;++c) {
      const wpk_chunk *ch=&s->chunks[c];
      if (ch->group!=WPK_SHADOW || !wpk_chunk_valid(ch,s->n_batch) || box_outside(mvp,ch->lo,ch->hi)) continue;
      for (uint32_t j=ch->first;j<ch->first+ch->n;++j) {
        const wpk_batch *b=&s->batches[j];
        if (!b->count || b->pool>=s->n_pools) continue;
        native_mesh(&d,s,b); cinder_vk_submit(&d);
      }
    }
  }
  p->draws+=3*n;
}
#endif
