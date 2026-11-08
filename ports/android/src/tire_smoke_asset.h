#ifndef RE3DXPLUS_TIRE_SMOKE_ASSET_H
#define RE3DXPLUS_TIRE_SMOKE_ASSET_H
/* Strict zero-copy parser for the proposed new MAIN member tiresmoke.bin.
 * No filesystem/device APIs. Caller retains bytes until RGBA upload returns.
 * CRC detects accidental damage, NOT authenticity: successor MAIN manifest
 * must pin the whole bank's SHA256 below. Original 1800 profile unchanged. */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#define TIRE_SMOKE_ASSET_SIZE 262160u
#define TIRE_SMOKE_ASSET_SHA256 "5a0a2d31d64583fc2dd7a8cda2bc81f9bdf80ae07cdad3981d0409ea11748e92"
#define TIRE_SMOKE_PIXEL_SHA256 "b5efd85e0bad26dfc6c48a59a19a0fd9e02c1206af6646d4f427df0535f6e108"
#define TIRE_SMOKE_PIXEL_CRC32 UINT32_C(0x72fa81b7)
typedef struct TireSmokeAtlas { const unsigned char *rgba; size_t bytes; unsigned width,height; } TireSmokeAtlas;
static inline uint32_t tire_smoke_asset_le32(const unsigned char *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static inline int tire_smoke_asset_parse(TireSmokeAtlas *out,const void *data,size_t bytes) {
    if(!out) return 0;
    memset(out,0,sizeof *out);
    const unsigned char *p=(const unsigned char *)data;
    if(!p || bytes!=TIRE_SMOKE_ASSET_SIZE || memcmp(p,"TSM1\x00\x01\x00\x01",8) ||
        tire_smoke_asset_le32(p+8)!=262144u || tire_smoke_asset_le32(p+12)!=TIRE_SMOKE_PIXEL_CRC32) return 0;
    uint32_t crc=UINT32_MAX;
    for(size_t i=16;i<bytes;++i) {
        crc^=p[i];
        for(unsigned bit=0;bit<8;++bit) crc=(crc>>1)^(UINT32_C(0xedb88320)&(0u-(crc&1u)));
    }
    if((crc^UINT32_MAX)!=TIRE_SMOKE_PIXEL_CRC32) return 0;
    out->rgba=p+16;out->bytes=262144u;out->width=out->height=256;return 1;
}
#endif
