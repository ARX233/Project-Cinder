#ifndef RE3DXPLUS_RENDER_STORY_ASSEMBLY_H
#define RE3DXPLUS_RENDER_STORY_ASSEMBLY_H
/* Pure scoped presentation: no vehicle/physics/RNG/global writes. */
#include "render.h"
#include "story_part_visibility.h"
#include <math.h>

/* -1 preserves the pre-existing group path, including named world objects. */
static inline int render_story_part_visibility(const render_params *p, int limited, uint32_t group) {
    return p && p->story_assembly_enabled && !limited
        ? story_part_visible(group,p->story_assembly_flags) : -1;
}
/* Body-root children known in this WPK contract. The independent RUN/STOP
 * lamp meshes were authored over the body lenses at neutral height. Keep
 * those overlays and wing brake lights aligned when the body moves. The
 * shared LIGHT mesh and non-body groups retain their original posture. */
static inline int render_story_body_group(uint32_t group) {
    return group<WPK_GROUPS || group==WPK_LAMP_OFF || group==WPK_LAMP_ON ||
        group==WPK_BRAKE_RUN || group==WPK_BRAKE_STOP ||
        (group>WPK_BRAKE_HIGH && group<WPK_BRAKE_WING2+0x20) ||
        (group>=WPK_MIRROR && group<WPK_BONNET+4) ||
        (group>=WPK_STORY_MUFFLER1 && group<WPK_STORY_END);
}
static inline float render_story_body_offset(const render_params *p,int limited,uint32_t group) {
    if(!p || !p->story_assembly_enabled || limited || !render_story_body_group(group) ||
        !isfinite(p->story_body_y) || fabsf(p->story_body_y)>2.0f) return 0.0f;
    return p->story_body_y;
}
/* Exact local-root translation: M*T(0,y,0), inverse-eye T^-1*eye.
 * Caller uses both cmvp and ce for culling BEFORE submitting this chunk. */
static inline void render_story_translate_y(const mat4 *model,const mat4 *vp,
        const float eye[3],float y,mat4 *cm,mat4 *cmvp,float ce[3]) {
    *cm=*model;
    for(unsigned r=0;r<4;++r) cm->m[12+r]+=model->m[4+r]*y;
    *cmvp=mat4_mul(*vp,*cm);
    ce[0]=eye[0];ce[1]=eye[1]-y;ce[2]=eye[2];
}
#endif
