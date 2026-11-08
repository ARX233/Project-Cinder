#ifndef HUD_CUSTOM_STORE_H
#define HUD_CUSTOM_STORE_H
/* Header-only POSIX sidecar. Define _POSIX_C_SOURCE=200809L before system
 * headers on strict POSIX hosts. Serialize all writers externally. */
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct HudCustomTransform { int k, dx, dy; } HudCustomTransform;
#define HUD_CUSTOM_BUTTONS 4
typedef struct HudCustomLayout {
    int stick_deadzone_percent, shift_separate;
    HudCustomTransform shift, map, rank, timer, meter;
    int button_opacity_percent, separate_buttons;
    HudCustomTransform button[HUD_CUSTOM_BUTTONS];
} HudCustomLayout;
typedef enum HudCustomResult {
    HUD_CUSTOM_OK=0, HUD_CUSTOM_MISSING=1, HUD_CUSTOM_CORRUPT=2,
    HUD_CUSTOM_UNSUPPORTED=3, HUD_CUSTOM_IO_ERROR=4,
    HUD_CUSTOM_INVALID=5, HUD_CUSTOM_EDIT_REQUIRED=6
} HudCustomResult;
static inline void hud_custom_default(HudCustomLayout *v) {
    HudCustomTransform t={100,0,0}; if(!v) return;
    v->stick_deadzone_percent=8; v->shift_separate=0;
    v->shift=v->map=v->rank=v->timer=v->meter=t;
    v->button_opacity_percent=100; v->separate_buttons=0;
    for(int i=0;i<HUD_CUSTOM_BUTTONS;++i) v->button[i]=t;
}
static inline int hud_custom_transform_valid(HudCustomTransform t) {
    return t.k>=60 && t.k<=160 && t.dx>=-2000 && t.dx<=2000 && t.dy>=-2000 && t.dy<=2000;
}
static inline int hud_custom_validate(const HudCustomLayout *v) {
    if(!v || v->button_opacity_percent<0 || v->button_opacity_percent>100 ||
       v->separate_buttons<0 || v->separate_buttons>=(1<<HUD_CUSTOM_BUTTONS)) return 0;
    for(int i=0;i<HUD_CUSTOM_BUTTONS;++i)
        if(!hud_custom_transform_valid(v->button[i])) return 0;
    return v->stick_deadzone_percent>=0 && v->stick_deadzone_percent<=50 &&
        (v->shift_separate==0 || v->shift_separate==1) &&
        hud_custom_transform_valid(v->shift) && hud_custom_transform_valid(v->map) &&
        hud_custom_transform_valid(v->rank) && hud_custom_transform_valid(v->timer) &&
        hud_custom_transform_valid(v->meter);
}
/* Canonical signed decimal, no leading zeros, plus, whitespace or -0. */
static inline int hud_custom_parse_int(const char **s,int *out) {
    const char *p=*s; unsigned int x=0; int neg=0;
    if(*p=='-') { neg=1; ++p; }
    if(*p<'0'||*p>'9') return 0;
    if(*p=='0' && (neg || (p[1]>='0' && p[1]<='9'))) return 0;
    do { unsigned int d=(unsigned int)(*p++-'0');
        if(x>((unsigned int)INT_MAX-d)/10U) return 0; x=x*10U+d;
    } while(*p>='0' && *p<='9');
    *out=neg?-(int)x:(int)x; *s=p; return 1;
}
static inline int hud_custom_line1(const char **p,const char *name,int *v) {
    size_t n=strlen(name); if(strncmp(*p,name,n)) return 0; *p+=n;
    if(!hud_custom_parse_int(p,v)||**p!='\n') return 0; ++*p; return 1;
}
static inline int hud_custom_line3(const char **p,const char *name,HudCustomTransform *v) {
    size_t n=strlen(name); if(strncmp(*p,name,n)) return 0; *p+=n;
    if(!hud_custom_parse_int(p,&v->k)||**p!=',') return 0; ++*p;
    if(!hud_custom_parse_int(p,&v->dx)||**p!=',') return 0; ++*p;
    if(!hud_custom_parse_int(p,&v->dy)||**p!='\n') return 0; ++*p; return 1;
}
/* Read-only. On a non-OK result, output is reset to defaults. */
static inline HudCustomResult hud_custom_load(const char *path,HudCustomLayout *out) {
    char b[1026]; size_t n; int oversized; FILE *f; const char *p, *version; HudCustomLayout v;
    if(!out||!path||!*path) return HUD_CUSTOM_INVALID; hud_custom_default(out);
    f=fopen(path,"rb"); if(!f) return errno==ENOENT?HUD_CUSTOM_MISSING:HUD_CUSTOM_IO_ERROR;
    n=fread(b,1,sizeof b-1,f); if(ferror(f)) { fclose(f); return HUD_CUSTOM_IO_ERROR; }
    if(fclose(f)!=0) return HUD_CUSTOM_IO_ERROR;
    oversized=(n==sizeof b-1); b[n]=0; p=b;
    /* Oversized input cannot be fully classified: preserve it, even if edited. */
    if(strncmp(p,"HUD_CUSTOM ",11)) return oversized?HUD_CUSTOM_UNSUPPORTED:HUD_CUSTOM_CORRUPT; p+=11;
    version=p;
    if(*p<'0'||*p>'9') return oversized?HUD_CUSTOM_UNSUPPORTED:HUD_CUSTOM_CORRUPT;
    if(*p=='0' && p[1]>='0' && p[1]<='9') return oversized?HUD_CUSTOM_UNSUPPORTED:HUD_CUSTOM_CORRUPT;
    do { ++p; } while(*p>='0' && *p<='9');
    if(*p!='\n') return oversized?HUD_CUSTOM_UNSUPPORTED:HUD_CUSTOM_CORRUPT;
    if(p-version!=1 || (*version!='1' && *version!='2')) return HUD_CUSTOM_UNSUPPORTED;
    if(oversized) return HUD_CUSTOM_UNSUPPORTED;
    if(memchr(b,0,n)) return HUD_CUSTOM_CORRUPT; ++p;
    hud_custom_default(&v);
    if(!hud_custom_line1(&p,"deadzone=",&v.stick_deadzone_percent)||
       !hud_custom_line1(&p,"shift_separate=",&v.shift_separate)||
       !hud_custom_line3(&p,"shift=",&v.shift)||!hud_custom_line3(&p,"map=",&v.map)||
       !hud_custom_line3(&p,"rank=",&v.rank)||!hud_custom_line3(&p,"timer=",&v.timer)||
       !hud_custom_line3(&p,"meter=",&v.meter)) return HUD_CUSTOM_CORRUPT;
    if(*version=='2' &&
       (!hud_custom_line1(&p,"opacity=",&v.button_opacity_percent)||
        !hud_custom_line1(&p,"separate_buttons=",&v.separate_buttons)||
        !hud_custom_line3(&p,"shift_up=",&v.button[0])||
        !hud_custom_line3(&p,"shift_down=",&v.button[1])||
        !hud_custom_line3(&p,"pause=",&v.button[2])||
        !hud_custom_line3(&p,"camera=",&v.button[3]))) return HUD_CUSTOM_CORRUPT;
    if(*p||!hud_custom_validate(&v)) return HUD_CUSTOM_CORRUPT;
    *out=v; return HUD_CUSTOM_OK;
}
/* Every save requires user_edited==1; unknown versions are NEVER overwritten.
 * Explicit user edit may replace corrupt data. Before rename, failure leaves the
 * destination untouched. Callers must serialize ALL writers: rename is not CAS.
 * The file is fsynced; the directory entry is not guaranteed power-loss durable. */
static inline HudCustomResult hud_custom_save(const char *path,const HudCustomLayout *v,int user_edited) {
    HudCustomLayout old; HudCustomResult r; char *tmp; size_t len; int fd,ok; FILE *f;
    if(!path||!*path||!hud_custom_validate(v)) return HUD_CUSTOM_INVALID;
    if(user_edited!=1) return HUD_CUSTOM_EDIT_REQUIRED;
    r=hud_custom_load(path,&old);
    if(r==HUD_CUSTOM_UNSUPPORTED||r==HUD_CUSTOM_IO_ERROR||r==HUD_CUSTOM_INVALID) return r;
    len=strlen(path); if(len>(size_t)-1-12) return HUD_CUSTOM_IO_ERROR;
    tmp=(char *)malloc(len+12); if(!tmp) return HUD_CUSTOM_IO_ERROR;
    memcpy(tmp,path,len); memcpy(tmp+len,".tmp.XXXXXX",12);
    fd=mkstemp(tmp); if(fd<0) { free(tmp); return HUD_CUSTOM_IO_ERROR; }
    f=fdopen(fd,"wb"); if(!f) { close(fd); unlink(tmp); free(tmp); return HUD_CUSTOM_IO_ERROR; }
    ok=fprintf(f,"HUD_CUSTOM 2\ndeadzone=%d\nshift_separate=%d\nshift=%d,%d,%d\nmap=%d,%d,%d\nrank=%d,%d,%d\ntimer=%d,%d,%d\nmeter=%d,%d,%d\nopacity=%d\nseparate_buttons=%d\nshift_up=%d,%d,%d\nshift_down=%d,%d,%d\npause=%d,%d,%d\ncamera=%d,%d,%d\n",
       v->stick_deadzone_percent,v->shift_separate,v->shift.k,v->shift.dx,v->shift.dy,
       v->map.k,v->map.dx,v->map.dy,v->rank.k,v->rank.dx,v->rank.dy,
       v->timer.k,v->timer.dx,v->timer.dy,v->meter.k,v->meter.dx,v->meter.dy,
       v->button_opacity_percent,v->separate_buttons,
       v->button[0].k,v->button[0].dx,v->button[0].dy,v->button[1].k,v->button[1].dx,v->button[1].dy,
       v->button[2].k,v->button[2].dx,v->button[2].dy,v->button[3].k,v->button[3].dx,v->button[3].dy)>=0;
    if(ok && fflush(f)!=0) ok=0; if(ok && fsync(fd)!=0) ok=0;
    if(fclose(f)!=0) ok=0; if(ok && rename(tmp,path)!=0) ok=0;
    if(!ok) unlink(tmp); free(tmp); return ok?HUD_CUSTOM_OK:HUD_CUSTOM_IO_ERROR;
}
#ifdef __cplusplus
}
#endif
#endif
