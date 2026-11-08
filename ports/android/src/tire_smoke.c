#include "tire_smoke.h"
#include <math.h>
#include <string.h>

/* All finite/range checks below are conservative presentation safety policy,
 * not claims about the original's malformed-data handling. */
#define INPUT_LIMIT 1000000.0f
static int vector_ok(const float *p, unsigned n) {
    for (unsigned i=0; i<n; ++i)
        if (!isfinite(p[i]) || fabsf(p[i])>INPUT_LIMIT) return 0;
    return 1;
}
static int input_ok(const TireSmokeInput *in) {
    return in && vector_ok(in->velocity,3) && vector_ok(in->emitter[0],3) &&
        vector_ok(in->emitter[1],3) && isfinite(in->amount[0]) && isfinite(in->amount[1]) &&
        in->amount[0]>=0 && in->amount[0]<=1 && in->amount[1]>=0 && in->amount[1]<=1;
}
static float le_float(const unsigned char *p) {
    uint32_t u=(uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
    float f; memcpy(&f,&u,sizeof f); return f;
}
int tire_smoke_input_from_effect(TireSmokeInput *out, const void *effect, size_t bytes) {
    TireSmokeInput in;
    const unsigned char *p=(const unsigned char *)effect;
    if (!out) return 0;
    memset(out,0,sizeof *out);
    if (!p || bytes<TIRE_SMOKE_EFFECT_BYTES || sizeof(float)!=4) return 0;
    for (unsigned j=0;j<3;++j) {
        in.velocity[j]=le_float(p+0x30+4*j);
        in.emitter[0][j]=le_float(p+0x18+4*j);
        in.emitter[1][j]=le_float(p+0x24+4*j);
    }
    in.amount[0]=le_float(p+0x50); in.amount[1]=le_float(p+0x54);
    if (!input_ok(&in)) return 0;
    *out=in; return 1;
}
void tire_smoke_reset(TireSmoke *s) { if(s) memset(s,0,sizeof *s); }

void tire_smoke_step(TireSmoke *s, uint64_t owner, uint64_t tick,
                     const TireSmokeInput *in, int generate) {
    if (!s) return;
    if (!owner || !input_ok(in) || s->count>TIRE_SMOKE_MAX || s->phase>1) { tire_smoke_reset(s); return; }
    for (unsigned i=0;i<s->count;++i) {
        const TireSmokeParticle *p=&s->particle[i];
        if(p->emitter>1 || p->direct>1 || p->age>=TIRE_SMOKE_LIFE ||
            !vector_ok(p->pos,3) || !vector_ok(p->direction,3) ||
            !isfinite(p->scale) || p->scale<0 || p->scale>3 ||
            !isfinite(p->alpha) || p->alpha<=0 || p->alpha>1 ||
            !isfinite(p->fade) || p->fade<0 || p->fade>1) { tire_smoke_reset(s); return; }
    }
    if (s->owner!=owner || (s->has_tick && (tick<s->last_tick ||
        (tick!=s->last_tick && (s->last_tick==UINT64_MAX || tick!=s->last_tick+1)))))
        tire_smoke_reset(s);
    if (s->has_tick && tick==s->last_tick) return;
    s->owner=owner; s->last_tick=tick; s->has_tick=1;

    /* 0x8628035..8130: old particles track the current native emitter (direct)
     * or its 7/8-to-1/8 interior point, minus age * stored unit direction.
     * This is intentionally NOT a ballistic/world-anchored replacement. */
    unsigned kept=0;
    for (unsigned i=0;i<s->count;++i) {
        TireSmokeParticle p=s->particle[i];
        for(unsigned j=0;j<3;++j) {
            float anchor=in->emitter[p.emitter][j];
            if (!p.direct) {
                /* Preserve original nested-midpoint arithmetic. */
                float midpoint=(in->emitter[0][j]+in->emitter[1][j])*0.5f;
                anchor=(anchor+(anchor+midpoint)*0.5f)*0.5f;
            }
            p.pos[j]=anchor-(float)p.age*p.direction[j];
        }
        p.scale=fminf(p.scale*1.2f,3.0f);
        p.alpha-=p.fade;
        ++p.age;
        if (p.alpha>0 && p.age<TIRE_SMOKE_LIFE) s->particle[kept++]=p;
    }
    s->count=kept;
    if (!generate) return; /* Original generation counter advances only enabled. */
    s->phase=(s->phase+1u)%2u;
    if (!s->phase) return; /* 0x8628151..8156: every second enabled tick skipped. */
    float speed=sqrtf(in->velocity[0]*in->velocity[0]+in->velocity[1]*in->velocity[1]+
                       in->velocity[2]*in->velocity[2]);
    /* Zero-speed normalization would divide by zero in original code. Reject
     * births instead of publishing NaNs; existing particles still aged above. */
    if (!(speed>0) || !isfinite(speed)) return;
    int remainder=(int)speed%40;
    float scale=((float)remainder+20.0f)/40.0f*0.5f;
    scale*=scale;
    float direction[3], inverse_speed=1.0f/speed;
    for (unsigned j=0;j<3;++j) direction[j]=in->velocity[j]*inverse_speed;
    /* Original multiplies by 0.3, rotates by zero, then normalizes again.
     * Retain this operation order instead of introducing presentation RNG. */
    for(unsigned j=0;j<3;++j) direction[j]*=0.30000001192092896f;
    float d=sqrtf(direction[0]*direction[0]+direction[1]*direction[1]+direction[2]*direction[2]);
    float inverse_d=1.0f/d;
    for(unsigned j=0;j<3;++j) direction[j]*=inverse_d;
    for(unsigned wheel=0;wheel<2;++wheel) {
        if (in->amount[wheel]==0) continue;
        if(s->count==TIRE_SMOKE_MAX) {
            memmove(s->particle,s->particle+1,(TIRE_SMOKE_MAX-1)*sizeof *s->particle);
            --s->count;
        }
        TireSmokeParticle *p=&s->particle[s->count++]; memset(p,0,sizeof *p);
        memcpy(p->pos,in->emitter[wheel],sizeof p->pos);
        memcpy(p->direction,direction,sizeof p->direction);
        p->emitter=wheel; p->direct=(unsigned)remainder&1u;
        p->alpha=fminf(15.0f*in->amount[wheel],1.0f);
        p->fade=p->alpha/25.0f; p->scale=scale;
    }
}
size_t tire_smoke_vertices(const TireSmoke *s, const float view[16],
                           TireSmokeVertex *v, size_t capacity) {
    if(!s || !view || !v || s->count>TIRE_SMOKE_MAX || capacity<4u*s->count ||
        !vector_ok(view,16)) return 0;
    /* Original triangles A B C, B D C. Quad B D C A reproduces exactly that
     * diagonal with generic indices 0,1,2,0,2,3. Exact native numerical atlas
     * UV rectangle (not an invented animated flipbook) 0x93d9e60. */
    static const float UV[4][2]={{0.5f,1},{0.5f,0.5f},{0,0.5f},{0,1}};
    static const float X[4]={-1,-1,1,1};
    static const unsigned TOP[4]={1,0,0,1};
    for(unsigned i=0;i<s->count;++i) {
        const TireSmokeParticle *p=&s->particle[i];
        float center[3];
        if(p->emitter>1 || !vector_ok(p->pos,3) || !isfinite(p->scale) ||
            p->scale<0 || p->scale>3 || !isfinite(p->alpha) || p->alpha<0 || p->alpha>1) return 0;
        for(unsigned j=0;j<3;++j)
            center[j]=view[j]*p->pos[0]+view[4+j]*p->pos[1]+view[8+j]*p->pos[2]+view[12+j];
        for(unsigned j=0;j<4;++j) {
            TireSmokeVertex *q=&v[4*i+j];
            q->pos[0]=center[0]+X[j]*(p->emitter?-1.0f:1.0f)*2.0f*p->scale;
            /* 0x8627c65..7dfe: base up=2, top=2*base+base*scale/2,
             * bottom=base-base*scale/2. Not a generic square particle. */
            q->pos[1]=center[1]+(TOP[j]?4.0f+p->scale:2.0f-p->scale);
            q->pos[2]=center[2];
            memcpy(q->uv,UV[j],sizeof q->uv);
            q->rgba[0]=q->rgba[1]=q->rgba[2]=1; q->rgba[3]=p->alpha;
        }
    }
    return s->count;
}
