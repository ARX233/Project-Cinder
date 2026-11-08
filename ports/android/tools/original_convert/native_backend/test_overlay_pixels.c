/* Host-only ASan/UBSan compositor boundary regression. SPDX-License-Identifier: MIT */
#include "oc_media_overlay.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    const size_t n = 640u*480u*3u;
    uint8_t *rgb=malloc(n), *before=malloc(n), *rgba=malloc(512u*128u*4u);
    assert(rgb&&before&&rgba);memset(rgba,255,512u*128u*4u);
    oc_media_overlay o={.abi=2,.size=sizeof o,.width=128,.height=16,.stride_bytes=512,.x=29,.y=18,.rgba_bytes=8192,.rgba=rgba};
    for (int i=0;i<128;++i) {
        memset(rgb,85,n);memcpy(before,rgb,n);
        o.width=1u+(uint32_t)(i*37)%512u;o.height=1u+(uint32_t)(i*19)%128u;
        o.stride_bytes=o.width*4;o.rgba_bytes=(uint64_t)o.stride_bytes*o.height;
        o.x=1+(i*17)%640;o.y=1+(i*13)%480;
        int r=oc_media_overlay_apply_rgb24(&o,rgb,n,640,480,1920,i,333333,10000000);
        if ((uint64_t)o.x+o.width>640 || (uint64_t)o.y+o.height>480) {
            assert(r==-1);assert(!memcmp(rgb,before,n));
        } else {assert(r==0);assert(!memcmp(rgb,before,3));}
    }
    o.width=1;o.height=1;o.stride_bytes=4;o.rgba_bytes=4;o.x=0;o.y=0;
    rgba[0]=255;rgba[1]=rgba[2]=0;rgba[3]=128;memset(rgb,100,n);
    assert(!oc_media_overlay_apply_rgb24(&o,rgb,n,640,480,1920,0,1,2));
    assert(rgb[0]==178&&rgb[1]==50&&rgb[2]==50);
    memset(rgb,100,n);assert(!oc_media_overlay_apply_rgb24(&o,rgb,n,640,480,1920,1,1,2));
    for (size_t i=0;i<n;++i)assert(rgb[i]==100);
    assert(!oc_media_overlay_apply_rgb24(&o,rgb,n,640,480,1920,1000000000,1000000000,999999937));
    memcpy(before,rgb,n);o.rgba=rgb;
    assert(oc_media_overlay_apply_rgb24(&o,rgb,n,640,480,1920,0,1,30)==-1&&!memcmp(rgb,before,n));
    free(rgb);free(before);free(rgba);puts("Compositor bounds passed (128 cases + exact peak/zero/overflow/alias)");return 0;
}
