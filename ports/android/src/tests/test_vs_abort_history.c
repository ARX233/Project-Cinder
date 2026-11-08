#include "../vs_abort_history.h"
#include <assert.h>
#include <stdio.h>
#include <stdint.h>

static uint32_t rng = 0x39ab12efu;
static uint32_t random32(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
static int naive(const uint32_t *v, unsigned n, uint32_t b)
{
    unsigned i; for (i=0; i<n; ++i) { uint32_t d = v[i]-b; if (d && d < UINT32_C(0x80000000)) return 1; } return 0;
}
static void compare(vs_abort_history *h, const uint32_t *v, unsigned n, uint32_t b)
{
    assert(vs_abort_history_query(h,1,2,3,b) == (naive(v,n,b) ? VS_ABORT_MATCH : VS_ABORT_NO_MATCH));
}
int main(void)
{
    vs_abort_history h; uint32_t seqs[1800], s, b; unsigned i,j,k;
    vs_abort_history_reset(&h);
    assert(vs_abort_history_query(&h,1,2,3,0) == VS_ABORT_NO_MATCH);
    seqs[0]=0; seqs[1]=UINT32_C(0x40000000); seqs[2]=UINT32_C(0x80000000);
    for(i=0;i<3;i++) assert(vs_abort_history_record(&h,1,2,3,seqs[i]) == VS_ABORT_MATCH);
    compare(&h,seqs,3,0);
    assert(vs_abort_history_query(&h,1,2,3,0) == VS_ABORT_MATCH);
    vs_abort_history_reset(&h);
    assert(vs_abort_history_record(&h,1,2,3,0) == VS_ABORT_MATCH);
    assert(vs_abort_history_query(&h,1,2,3,0) == VS_ABORT_NO_MATCH);
    assert(vs_abort_history_query(&h,1,2,3,UINT32_C(0x80000000)) == VS_ABORT_NO_MATCH);
    assert(vs_abort_history_query(&h,1,2,3,UINT32_C(0x80000001)) == VS_ABORT_MATCH);
    assert(vs_abort_history_query(&h,1,2,3,UINT32_MAX) == VS_ABORT_MATCH);
    for(k=0;k<2;k++) {
        vs_abort_history_reset(&h);
        for(i=0;i<1800;i++) {
            seqs[i]=(k ? UINT32_C(0xffffff00) : 1000u)+i;
            assert(vs_abort_history_record(&h,1,2,3,seqs[i]) == VS_ABORT_MATCH);
            assert(vs_abort_history_record(&h,1,2,3,seqs[i]) == VS_ABORT_MATCH);
            b=seqs[i]; compare(&h,seqs,i+1,b); compare(&h,seqs,i+1,b-1u);
            compare(&h,seqs,i+1,b-UINT32_C(0x80000000));
        }
    }
    for(k=0;k<100;k++) {
        vs_abort_history_reset(&h);
        for(i=0;i<100;i++) {
            s=random32(); seqs[i]=s;
            assert(vs_abort_history_record(&h,1,2,3,s)==VS_ABORT_MATCH);
            assert(h.entries[0].count <= 3);
            for(j=0;j<20;j++) { b=random32(); compare(&h,seqs,i+1,b); }
            compare(&h,seqs,i+1,s); compare(&h,seqs,i+1,s-1u);
            compare(&h,seqs,i+1,s-UINT32_C(0x80000000));
        }
    }
    vs_abort_history_reset(&h);
    for(i=0;i<VS_ABORT_HISTORY_KEYS;i++) assert(vs_abort_history_record(&h,i+1u,2,3,i)==VS_ABORT_MATCH);
    for(i=0;i<VS_ABORT_HISTORY_KEYS;i++) assert(vs_abort_history_query(&h,i+1u,2,3,i-1u)==VS_ABORT_MATCH);
    assert(vs_abort_history_record(&h,100,2,3,0)==VS_ABORT_UNKNOWN);
    assert(vs_abort_history_query(&h,1,2,3,0)==VS_ABORT_UNKNOWN);
    vs_abort_history_reset(&h); assert(vs_abort_history_query(&h,1,2,3,0)==VS_ABORT_NO_MATCH);
    assert(vs_abort_history_record(&h,0,2,3,0)==VS_ABORT_UNKNOWN);
    assert(vs_abort_history_query(&h,1,2,3,0)==VS_ABORT_UNKNOWN);
    vs_abort_history_reset(&h); assert(vs_abort_history_query(&h,1,0,3,0)==VS_ABORT_UNKNOWN);
    vs_abort_history_reset(&h); assert(vs_abort_history_record(&h,1,2,0,0)==VS_ABORT_UNKNOWN);
    vs_abort_history_reset(&h); h.used=VS_ABORT_HISTORY_KEYS+1u;
    assert(vs_abort_history_query(&h,1,2,3,0)==VS_ABORT_UNKNOWN);
    assert(vs_abort_history_record(NULL,1,2,3,0)==VS_ABORT_UNKNOWN);
    puts("vs_abort_history tests passed"); return 0;
}
