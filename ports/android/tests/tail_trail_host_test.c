#include "tail_trail.h"
#include <assert.h>
#include <math.h>
#include <string.h>
static int near(float a,float b) { return fabsf(a-b)<0.0001f; }
static void test_emit_boundaries(void) {
    TailTrail t={0}; TailTrailVertex v[TAIL_TRAIL_MAX_VERTICES];
    TailTrailAnchor a[2]={{{1,0,0},{0,1,0},1},{{-1,0,0},{0,1,0},1}};
    float m[16]={1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    int i,j,k;
    /* Rejected ticks before the first emission cannot create a segment. */
    assert(tail_trail_tick(&t,1,1,0,a,m,100) && !t.count);
    assert(tail_trail_tick(&t,1,1,0,a,m,100) && !t.count);
    assert(tail_trail_tick(&t,1,1,1,a,m,100) && t.count==1);
    m[12]=10; assert(tail_trail_tick(&t,1,1,1,a,m,100));
    m[12]=20; assert(tail_trail_tick(&t,1,1,0,a,m,100));
    m[12]=30; assert(tail_trail_tick(&t,1,1,0,a,m,100));
    m[12]=40; assert(tail_trail_tick(&t,1,1,1,a,m,100));
    assert(t.count==3 && t.samples[2].break_before && !t.break_pending);
    assert(near(t.samples[0].alpha,.4f) && near(t.samples[1].alpha,.5f));
    /* Keep the old 0..10 strip, but never draw the rejected 10..40 gap. */
    for(j=0;j<2;j++) {
        float offset=j?-1.0f:1.0f;
        assert(tail_trail_triangles(&t,(unsigned)j,v,5)==0);
        assert(tail_trail_triangles(&t,(unsigned)j,v,6)==6);
        for(i=0;i<6;i++) assert(v[i].position.x>=offset && v[i].position.x<=10+offset);
    }
    m[12]=50; assert(tail_trail_tick(&t,1,1,1,a,m,100));
    assert(t.count==4 && !t.samples[3].break_before);
    assert(tail_trail_triangles(&t,0,v,12)==12);
    for(i=0;i<6;i++) assert(v[i].position.x<=11);
    for(i=6;i<12;i++) assert(v[i].position.x>=41);
    /* Compaction must carry a removed strip-start to its next surviving point. */
    t.samples[2].alpha=.1f;
    m[12]=60; assert(tail_trail_tick(&t,1,1,0,a,m,100));
    assert(t.count==3 && t.samples[2].break_before);
    assert(tail_trail_triangles(&t,0,v,6)==6);
    /* If a whole newer singleton expires, resumption still cannot join the old strip. */
    t.samples[2].alpha=.1f;
    m[12]=70; assert(tail_trail_tick(&t,1,1,1,a,m,100));
    assert(t.count==3 && t.samples[2].break_before);
    assert(tail_trail_triangles(&t,0,v,6)==6);
    /* Identity/teleport/inactive reset both pending and per-sample boundaries. */
    assert(tail_trail_tick(&t,2,1,1,a,m,100) && t.count==1 && !t.break_pending);
    m[12]=71; assert(tail_trail_tick(&t,2,1,1,a,m,100));
    assert(tail_trail_triangles(&t,0,v,6)==6);
    m[12]=1000; assert(tail_trail_tick(&t,2,1,1,a,m,100) && t.count==1);
    m[12]=1001; assert(tail_trail_tick(&t,2,1,1,a,m,100));
    assert(tail_trail_triangles(&t,0,v,6)==6);
    assert(!tail_trail_tick(&t,2,0,0,a,m,100) && !t.count && !t.break_pending);
    /* At the synthetic full cap, dropping the head preserves an interior boundary. */
    t.count=TAIL_TRAIL_CAPACITY; t.slot_id=1; t.active=1;
    for(i=0;i<TAIL_TRAIL_CAPACITY;i++) {
        t.samples[i].alpha=.8f; t.samples[i].break_before=i==0 || i==10;
        for(j=0;j<2;j++) for(k=0;k<2;k++)
            t.samples[i].edge[j][k]=(TailTrailVec3){(float)i+(j?-1.0f:1.0f),k?-1.0f:1.0f,0};
    }
    m[12]=20; assert(tail_trail_tick(&t,1,1,1,a,m,100));
    assert(t.count==TAIL_TRAIL_CAPACITY && t.samples[9].break_before);
    assert(tail_trail_triangles(&t,0,v,TAIL_TRAIL_MAX_VERTICES)==108);
    for(i=0;i<108;i+=3) {
        float lo=fminf(v[i].position.x,fminf(v[i+1].position.x,v[i+2].position.x));
        float hi=fmaxf(v[i].position.x,fmaxf(v[i+1].position.x,v[i+2].position.x));
        assert(!(lo==10 && hi==11));
    }
    /* Repeated non-emitting ticks leave no old geometry after normal expiry. */
    for(i=0;i<10;i++) assert(tail_trail_tick(&t,1,1,0,a,m,100));
    assert(!t.count && !tail_trail_triangles(&t,0,v,TAIL_TRAIL_MAX_VERTICES));
    assert(tail_trail_tick(&t,1,1,1,a,m,100) && t.count==1);
}
int main(void) {
    test_emit_boundaries();
    TailTrail t={0},u={0}; TailTrailVertex v[TAIL_TRAIL_MAX_VERTICES];
    TailTrailAnchor a[2]={{{1,0,0},{0,1,0},2},{{-1,0,0},{0,1,0},2}};
    float m[16]={0,1,0,0,-1,0,0,0,0,0,1,0,10,20,30,1};
    int i,j;
    assert(tail_trail_tick(&t,1,1,1,a,m,100));
    assert(near(t.samples[0].edge[0][0].x,8));
    assert(near(t.samples[0].edge[0][0].y,21));
    assert(near(t.samples[0].edge[1][1].x,12));
    assert(tail_trail_triangles(&t,0,v,114)==0);
    m[12]=11; assert(tail_trail_tick(&t,1,1,1,a,m,100));
    assert(tail_trail_triangles(&t,0,v,5)==0);
    assert(tail_trail_triangles(&t,0,v,114)==6);
    assert(near(v[0].rgba[3],.7f) && near(v[2].rgba[3],.8f));
    assert(v[0].rgba[0]==1 && v[0].rgba[1]==0 && v[0].rgba[2]==0);
    assert(tail_trail_triangles(&t,1,v,114)==6 && near(v[0].position.y,19));
    assert(tail_trail_tick(&t,1,1,0,a,m,100));
    assert(t.count==2 && near(t.samples[0].alpha,.6f) && near(t.samples[1].alpha,.7f));
    for(i=0;i<30;i++) {
        assert(tail_trail_tick(&t,1,1,1,a,m,100));
        assert(t.count<=20);
        for(j=0;j<(int)t.count;j++) assert(t.samples[j].alpha>0);
    }
    /* Synthetic full queue exercises the cap even though normal fading may
     * expire samples before twenty entries are reached. */
    for(i=0;i<20;i++) { t.samples[i]=t.samples[t.count-1]; t.samples[i].alpha=.8f; }
    t.count=20;
    assert(tail_trail_tick(&t,1,1,1,a,m,100));
    assert(t.count==20 && tail_trail_triangles(&t,0,v,114)==114);
    /* Exact zero expires, tiny positive float remains: no invented epsilon.
     * Compaction must preserve order and both lamp edges. */
    t.count=3;
    for(i=0;i<3;i++) { t.samples[i].edge[0][0].x=(float)i; t.samples[i].edge[1][0].x=(float)(10+i); }
    t.samples[0].alpha=.1f;
    t.samples[1].alpha=nextafterf(.1f, INFINITY);
    t.samples[2].alpha=.5f;
    assert(tail_trail_tick(&t,1,1,0,a,m,100));
    assert(t.count==2 && t.samples[0].alpha>0 && t.samples[0].edge[0][0].x==1 && t.samples[0].edge[1][0].x==11);
    assert(t.samples[1].edge[0][0].x==2 && t.samples[1].edge[1][0].x==12);
    for(i=0;i<10;i++) assert(tail_trail_tick(&t,1,1,0,a,m,100));
    assert(t.count==0 && tail_trail_triangles(&t,0,v,114)==0);
    assert(tail_trail_tick(&t,1,1,1,a,m,100) && t.count==1);
    assert(tail_trail_triangles(&t,0,v,114)==0);
    assert(tail_trail_tick(&t,2,1,1,a,m,100) && t.count==1);
    m[12]=1000; assert(tail_trail_tick(&t,2,1,1,a,m,10) && t.count==1);
    assert(!tail_trail_tick(&t,2,0,0,a,m,10) && !t.count && !t.active);
    m[0]=NAN; assert(!tail_trail_tick(&t,2,1,1,a,m,10) && !t.count); m[0]=0;
    a[0].half_width=NAN; assert(!tail_trail_tick(&t,2,1,1,a,m,10)); a[0].half_width=2;
    m[3]=1; assert(!tail_trail_tick(&t,2,1,1,a,m,10)); m[3]=0;
    /* Vary render calls per physics tick: they cannot age or insert samples. */
    for(i=0;i<5;i++) { assert(tail_trail_tick(&t,7,1,1,a,m,10)); assert(tail_trail_tick(&u,7,1,1,a,m,10)); for(j=0;j<30;j++) (void)tail_trail_triangles(&t,0,v,114); }
    assert(t.count==u.count);
    for(i=0;i<5;i++) assert(near(t.samples[i].alpha,u.samples[i].alpha));
    tail_trail_reset(&t); assert(!t.count && !t.active);
    return 0;
}
