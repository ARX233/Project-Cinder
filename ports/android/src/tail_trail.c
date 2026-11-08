#include "tail_trail.h"
#include <math.h>
#include <string.h>

void tail_trail_reset(TailTrail *t) { if (t) memset(t, 0, sizeof(*t)); }
static int valid_vec(TailTrailVec3 v) {
    return isfinite(v.x) && isfinite(v.y) && isfinite(v.z);
}
static TailTrailVec3 transform(const float *m, TailTrailVec3 v) {
    TailTrailVec3 r = {m[0]*v.x+m[4]*v.y+m[8]*v.z+m[12],
                       m[1]*v.x+m[5]*v.y+m[9]*v.z+m[13],
                       m[2]*v.x+m[6]*v.y+m[10]*v.z+m[14]};
    return r;
}
int tail_trail_tick(TailTrail *t, uint64_t id, int active, int emit,
                    const TailTrailAnchor a[2], const float m[16], float max_step) {
    TailTrailSample s;
    size_t i, j, k;
    int boundary = 0;
    if (!t) return 0;
    if (!active || !a || !m || !isfinite(max_step) || max_step <= 0) goto bad;
    for (i=0;i<16;i++) if (!isfinite(m[i])) goto bad;
    if (m[3]!=0 || m[7]!=0 || m[11]!=0 || m[15]!=1) goto bad;
    for (i=0;i<2;i++) {
        if (!valid_vec(a[i].center) || !valid_vec(a[i].axis) ||
            !isfinite(a[i].half_width) || a[i].half_width < 0) goto bad;
        for (j=0;j<2;j++) {
            float w = j ? -a[i].half_width : a[i].half_width;
            TailTrailVec3 v = {a[i].center.x+w*a[i].axis.x,
                               a[i].center.y+w*a[i].axis.y,
                               a[i].center.z+w*a[i].axis.z};
            s.edge[i][j] = transform(m,v);
            if (!valid_vec(s.edge[i][j])) goto bad;
        }
    }
    if (t->count > TAIL_TRAIL_CAPACITY) goto bad;
    if (t->active && t->slot_id != id) tail_trail_reset(t);
    if (t->active && t->count) {
        /* Double precision avoids overflowing the cutoff comparison. */
        for (i=0;i<2;i++) {
            double d2=0;
            for (k=0;k<3;k++) {
                const TailTrailVec3 *x=&s.edge[i][0], *y=&t->samples[t->count-1].edge[i][0];
                double d = k==0 ? (double)x->x-y->x : k==1 ? (double)x->y-y->y : (double)x->z-y->z;
                d2+=d*d;
            }
            if (d2 > (double)max_step*max_step) { tail_trail_reset(t); break; }
        }
    }
    /* Stable compaction preserves paired lamps and chronological ordering.
     * Use the actual float result and <= 0, not an invented epsilon. */
    for (i=0, j=0;i<t->count;i++) {
        float alpha = t->samples[i].alpha;
        if (!isfinite(alpha)) goto bad;
        /* Expiring a strip-start must not join the surviving strips. */
        boundary |= t->samples[i].break_before;
        alpha -= .1f;
        if (alpha > 0.0f) {
            if (i != j) t->samples[j] = t->samples[i];
            t->samples[j].break_before = boundary;
            t->samples[j++].alpha = alpha;
            boundary = 0;
        }
    }
    t->count = j;
    t->break_pending |= boundary;
    if (!emit) { t->break_pending = 1; return 1; }
    if (t->count == TAIL_TRAIL_CAPACITY) {
        memmove(t->samples,t->samples+1,(TAIL_TRAIL_CAPACITY-1)*sizeof(t->samples[0]));
        t->count--;
    }
    s.alpha=.8f; s.break_before=!t->count || t->break_pending;
    t->samples[t->count++]=s; t->slot_id=id; t->active=1; t->break_pending=0;
    return 1;
bad:
    tail_trail_reset(t); return 0;
}
static void vertex(TailTrailVertex *v, TailTrailVec3 p, float a) {
    v->position=p; v->rgba[0]=1; v->rgba[1]=0; v->rgba[2]=0; v->rgba[3]=a;
}
size_t tail_trail_triangles(const TailTrail *t, unsigned lamp, TailTrailVertex *out, size_t cap) {
    size_t i,n=0,need=0;
    if (!t || !out || lamp>1 || t->count<2 || t->count>TAIL_TRAIL_CAPACITY) return 0;
    for (i=1;i<t->count;i++) if (!t->samples[i].break_before) need+=6;
    if (cap<need) return 0;
    for (i=1;i<t->count;i++) {
        const TailTrailSample *a=&t->samples[i-1],*b=&t->samples[i];
        if (b->break_before) continue;
        vertex(&out[n++],a->edge[lamp][0],a->alpha);
        vertex(&out[n++],a->edge[lamp][1],a->alpha);
        vertex(&out[n++],b->edge[lamp][0],b->alpha);
        vertex(&out[n++],b->edge[lamp][0],b->alpha);
        vertex(&out[n++],a->edge[lamp][1],a->alpha);
        vertex(&out[n++],b->edge[lamp][1],b->alpha);
    }
    return n;
}
