/* PROPOSED parent integration: include in render.c immediately after existing
 * render_tail_triangles, before the tire-track block. Requires tire_smoke.h.
 * Reuses existing shader text FS/VS, native_effect_init/vertices, and the pure
 * GLES state-save helpers tail_render_gl_save/restore. Own GPU objects below;
 * does not share/mutate tail's program, VAO, VBO or failed latch.
 * Add public declarations listed in INTEGRATION.md, plus release/loss hooks.
 * No new shader source/key/SPIR-V required; see shader-key-audit.json.
 */
static struct { scene_prog program; GLuint vao,vbo; int failed; } smoke_render;
void render_tire_smoke_context_lost(void) { memset(&smoke_render,0,sizeof smoke_render); }
void render_tire_smoke_release(void) {
#ifndef WMMT_NATIVE_VK
    if(smoke_render.vao) glDeleteVertexArraysOES(1,&smoke_render.vao);
    if(smoke_render.vbo) glDeleteBuffers(1,&smoke_render.vbo);
    if(smoke_render.program.id) glDeleteProgram(smoke_render.program.id);
#endif
    render_tire_smoke_context_lost();
}
#ifndef WMMT_NATIVE_VK
static int smoke_render_prepare(void) {
    if(smoke_render.failed) return 0;
    if(smoke_render.program.id && smoke_render.vao && smoke_render.vbo) return 1;
    if(prog_init(&smoke_render.program,FS)) goto bad;
#ifdef WMMT_VK
    if(!vkgl_program_usable(smoke_render.program.id)) goto bad;
#endif
    const scene_prog *pr=&smoke_render.program;
    if(pr->mvp<0 || pr->eye<0 || pr->fog<0 || pr->fog_color<0 || pr->tex<0 || pr->uv_off<0 || pr->grade<0) goto bad;
    glGenVertexArraysOES(1,&smoke_render.vao); glGenBuffers(1,&smoke_render.vbo);
    if(!smoke_render.vao || !smoke_render.vbo) goto bad;
    return 1;
bad:
    render_tire_smoke_release(); smoke_render.failed=1; return 0;
}
#endif
int render_tire_smoke(const mat4 *proj,const TireSmokeVertex *v,size_t quads,uint32_t tex,render_params *p) {
    if(!proj || !v || !p || !tex || !quads || quads>TIRE_SMOKE_MAX || smoke_render.failed) return 0;
    for(unsigned j=0;j<16;++j) if(!isfinite(proj->m[j])) return 0;
    for(size_t i=0;i<quads*4;++i) {
        for(unsigned j=0;j<3;++j) if(!isfinite(v[i].pos[j]) || fabsf(v[i].pos[j])>1e12f) return 0;
        for(unsigned j=0;j<2;++j) if(!isfinite(v[i].uv[j]) || v[i].uv[j]<0 || v[i].uv[j]>1) return 0;
        for(unsigned j=0;j<4;++j) {
            if(!isfinite(v[i].rgba[j]) || v[i].rgba[j]<0 || v[i].rgba[j]>1) return 0;
            double bound=fabs((double)proj->m[12+j]);
            for(unsigned k=0;k<3;++k) bound+=fabs((double)proj->m[4*k+j]*v[i].pos[k]);
            if(bound>1e30) return 0;
        }
    }
    TireSmokeVertex triangles[TIRE_SMOKE_MAX*6];
    static const unsigned order[6]={0,1,2,0,2,3};
    for(size_t i=0;i<quads;++i) for(unsigned j=0;j<6;++j) triangles[6*i+j]=v[4*i+order[j]];
    size_t n=quads*6;
#ifdef WMMT_NATIVE_VK
    cinder_vk_draw d;
    if(!native_effect_init(&d,proj,tex,1e30f,1e29f)) return 0;
    d.pipeline.depth_test=VK_TRUE; d.pipeline.depth_write=VK_FALSE;
    d.pipeline.depth_compare=VK_COMPARE_OP_LESS_OR_EQUAL;
    d.pipeline.cull=VK_CULL_MODE_NONE; d.pipeline.stencil=VK_FALSE;
    d.pipeline.color_mask=15;
    d.pipeline.blend=VK_TRUE; d.pipeline.blend_op=VK_BLEND_OP_ADD;
    d.pipeline.src_blend=VK_BLEND_FACTOR_SRC_ALPHA;
    d.pipeline.dst_blend=VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
    native_effect_vertices(&d,triangles,n*sizeof *triangles,sizeof *triangles,VK_FORMAT_R32G32B32A32_SFLOAT);
    d.count=(uint32_t)n;
    if(!cinder_vk_submit(&d)) { smoke_render.failed=1; return 0; }
    ++p->draws; p->triangles+=(int)(n/3); return 1;
#else
#ifdef WMMT_VK
    uint64_t epoch=vkgl_error_epoch();
    if(epoch==UINT64_MAX || vkgl_error_pending()) return 0;
    void *snapshot=vkgl_preview_save(progs[0].id);
    if(!snapshot) return 0;
#else
    tail_render_gl_state state; tail_render_gl_save(&state);
#endif
    int submitted=0;
    if(!smoke_render_prepare()) goto restore;
#ifdef WMMT_VK
    if(vkgl_error_epoch()!=epoch) goto device_error;
#endif
    const scene_prog *pr=&smoke_render.program;
    glUseProgram(pr->id); glUniformMatrix4fv(pr->mvp,1,GL_FALSE,proj->m);
    glUniform3f(pr->eye,0,0,0); glUniform2f(pr->fog,1e30f,1e29f);
    glUniform3f(pr->fog_color,0,0,0); glUniform2f(pr->uv_off,0,0);
    glUniform3f(pr->grade,1,1,1); glUniform1i(pr->tex,0);
    if(pr->wet>=0) glUniform1f(pr->wet,0);
    glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,tex);
    /* No sampler mutation: retain the independent TSM1 RGBA8 upload defaults. */
    glEnable(GL_DEPTH_TEST); glDepthFunc(GL_LEQUAL); glDepthMask(GL_FALSE);
    glDisable(GL_CULL_FACE); glDisable(GL_STENCIL_TEST);
    glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE);
    glEnable(GL_BLEND); glBlendEquation(GL_FUNC_ADD); glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
    glBindVertexArrayOES(smoke_render.vao); glBindBuffer(GL_ARRAY_BUFFER,smoke_render.vbo);
    glBufferData(GL_ARRAY_BUFFER,(GLsizeiptr)(n*sizeof *triangles),triangles,GL_STREAM_DRAW);
    glEnableVertexAttribArray(0); glEnableVertexAttribArray(1); glEnableVertexAttribArray(2);
    glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof *triangles,(const void *)offsetof(TireSmokeVertex,pos));
    glVertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,sizeof *triangles,(const void *)offsetof(TireSmokeVertex,uv));
    glVertexAttribPointer(2,4,GL_FLOAT,GL_FALSE,sizeof *triangles,(const void *)offsetof(TireSmokeVertex,rgba));
    glDrawArrays(GL_TRIANGLES,0,(GLsizei)n);
#ifdef WMMT_VK
    if(vkgl_error_epoch()!=epoch) goto device_error;
#endif
    submitted=1; ++p->draws; p->triangles+=(int)(n/3); goto restore;
#ifdef WMMT_VK
device_error:
    render_tire_smoke_release(); smoke_render.failed=1;
#endif
restore:
#ifdef WMMT_VK
    vkgl_scope_restore_preserve_error(snapshot);
#else
    tail_render_gl_restore(&state);
#endif
    return submitted;
#endif
}
