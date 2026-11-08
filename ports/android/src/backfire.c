#include "backfire.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define BFX_MAX_FILE (32u*1024u*1024u)
typedef struct { const unsigned char *p; size_t n; } reader;
static int take(reader *r, size_t n, const unsigned char **p) { if(n>r->n) return 0; *p=r->p; r->p+=n; r->n-=n; return 1; }
static int u16(reader *r, unsigned *v) { const unsigned char *p; if(!take(r,2,&p)) return 0; *v=p[0]|((unsigned)p[1]<<8); return 1; }
static int u32(reader *r, uint32_t *v) { const unsigned char *p; if(!take(r,4,&p)) return 0; *v=(uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); return 1; }
static int utf8(const unsigned char *p, size_t n) {
  for(size_t i=0;i<n;) { unsigned c=p[i++], need, v, min; if(c<0x80) { if(!c) return 0; continue; } if(c>=0xc2 && c<=0xdf) need=1,v=c&31,min=0x80; else if(c>=0xe0&&c<=0xef) need=2,v=c&15,min=0x800; else if(c>=0xf0&&c<=0xf4) need=3,v=c&7,min=0x10000; else return 0; if(need>n-i) return 0; while(need--) { c=p[i++]; if((c&0xc0)!=0x80) return 0; v=(v<<6)|(c&63); } if(v<min||v>0x10ffff||(v>=0xd800&&v<=0xdfff)) return 0; } return 1;
}
static int str(reader *r, char *s) { unsigned n; const unsigned char *p; if(!u16(r,&n)||!n||n>=BFX_NAME||!take(r,n,&p)||!utf8(p,n)) return 0; memcpy(s,p,n); s[n]=0; return 1; }
static int floats(reader *r, float *v, size_t n) { for(size_t i=0;i<n;i++) { uint32_t u; if(!u32(r,&u)) return 0; memcpy(v+i,&u,4); if(!isfinite(v[i]) || fabs((double)v[i]) > 1e12) return 0; } return 1; }
/* Paths are canonical generator ordinals: root '.' or 0..65535 components. */
static int ordinal_path(const char *s) {
  unsigned parts=0;
  if(!strcmp(s,".")) return 1;
  while(*s) {
    unsigned v=0, digits=0;
    if(*s<'0'||*s>'9'||(*s=='0' && s[1]>='0' && s[1]<='9')) return 0;
    while(*s>='0' && *s<='9') { v=v*10+(unsigned)(*s++-'0'); if(++digits>5||v>65535) return 0; }
    if(++parts>256) return 0;
    if(!*s) return 1;
    if(*s++!='/' || !*s) return 0;
  }
  return 0;
}
static int one_of(const char *s, const char *const *items, size_t count) {
  for(size_t i=0;i<count;i++) if(!strcmp(s,items[i])) return 1;
  return 0;
}
static int valid_car(const char *s, size_t *body_len, int *id) {
  const char *p=s; unsigned v=0;
  while(*p && *p!='|') {
    unsigned char c=(unsigned char)*p++;
    if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='/'||c==':')) return 0;
  }
  if(p==s || *p!='|') return 0;
  *body_len=(size_t)(p-s); ++p;
  if(!*p || (*p=='0' && p[1])) return 0;
  while(*p) { if(*p<'0'||*p>'9' || v>119) return 0; v=v*10+(unsigned)(*p++-'0'); }
  if(v>119) return 0;
  *id=(int)v; return 1;
}
void bfx_free(bfx_asset *a) { if(!a) return; free(a->mesh); free(a->nozzle); memset(a,0,sizeof *a); }
int bfx_parse(bfx_asset *out, const void *bytes, size_t size) {
  reader r={(const unsigned char *)bytes,size}; const unsigned char *p; unsigned ver, flags; uint32_t frames,nm,nn; bfx_asset a={0};
  if(!out||!bytes||size>BFX_MAX_FILE||sizeof(float)!=4||!take(&r,4,&p)||memcmp(p,"BFX1",4)||!u16(&r,&ver)||ver!=1||!u16(&r,&flags)||(flags&~1u)||!u32(&r,&frames)||frames!=BFX_FRAMES||!u32(&r,&nm)||!u32(&r,&nn)||!nm||nm>BFX_MAX_MESH||nn>BFX_MAX_NOZZLE) return -1;
  a.flags=flags; a.nmesh=nm; a.nnozzle=nn;
  if(nm && !(a.mesh=calloc(nm,sizeof *a.mesh))) goto fail;
  if(nn && !(a.nozzle=calloc(nn,sizeof *a.nozzle))) goto fail;
  static const char *const variants[]={"SAMLL_A","MIDDLE_A","LARGE_A","SMALL_B","MIDDLE_B","LARGE_B"};
  static const char *const mufflers[]={"MUFFLER1","MUFFLER2"};
  static const char *const slots[]={"MF_NULL_R1","MF_NULL_R2","MF_NULL_L1","MF_NULL_L2"};
  for(uint32_t i=0;i<nm;i++) {
    bfx_mesh *m=&a.mesh[i];
    if(!u32(&r,&m->group)||!m->group||!u32(&r,&m->geometry)||!u32(&r,&m->ordinal)||!str(&r,m->variant)||!one_of(m->variant,variants,6)||!str(&r,m->path)||!ordinal_path(m->path)||!floats(&r,&m->frame[0][0],BFX_FRAMES*16)) goto fail;
    for(uint32_t j=0;j<i;j++) if(a.mesh[j].group==m->group || (a.mesh[j].geometry==m->geometry && a.mesh[j].ordinal==m->ordinal && !strcmp(a.mesh[j].path,m->path))) goto fail;
  }
  for(uint32_t i=0;i<nn;i++) {
    bfx_nozzle *n=&a.nozzle[i]; size_t len; int id;
    if(!str(&r,n->car)||!valid_car(n->car,&len,&id)||!str(&r,n->muffler)||!one_of(n->muffler,mufflers,2)||!str(&r,n->name)||!one_of(n->name,slots,4)||!str(&r,n->path)||!ordinal_path(n->path)||!floats(&r,n->matrix,16)) goto fail;
    for(uint32_t j=0;j<i;j++) {
      bfx_nozzle *prev=&a.nozzle[j]; size_t plen; int pid;
      if(!valid_car(prev->car,&plen,&pid)) goto fail;
      if(len==plen && !memcmp(prev->car,n->car,len)) {
        if(id!=pid || (!strcmp(prev->muffler,n->muffler) && !strcmp(prev->name,n->name))) goto fail;
      }
    }
  }
  if(r.n) goto fail; *out=a; return 0;
fail: bfx_free(&a); return -1;
}
int bfx_load(bfx_asset *out,const char *path) { FILE *f=fopen(path,"rb"); unsigned char *buf; long n; int ret; if(!f) return -1; if(fseek(f,0,SEEK_END)|| (n=ftell(f))<0 || (unsigned long)n>BFX_MAX_FILE || fseek(f,0,SEEK_SET)) { fclose(f); return -1; } buf=malloc((size_t)n+1); if(!buf){fclose(f);return -1;} if(fread(buf,1,(size_t)n,f)!=(size_t)n){free(buf);fclose(f);return -1;} fclose(f); ret=bfx_parse(out,buf,(size_t)n); free(buf); return ret; }
void bfx_reset(bfx_playback *p) { memset(p->frame,-1,sizeof p->frame); memset(p->type,-1,sizeof p->type); }
int bfx_car_id(const char *key, const char *body) {
  size_t len; int id;
  if(!key || !body || !valid_car(key,&len,&id) || strlen(body)!=len || memcmp(key,body,len)) return -1;
  return id;
}
int bfx_variant_b(int id) { static const unsigned char b[]={0x25,0x26,0x27,0x28,0x29,0x2a,0x2b,0x2c,0x2d,0x32,0x34,0x5f,0x60,0x61,0x71,0x75,0x76}; for(size_t i=0;i<sizeof b;i++) if(id==b[i]) return 1; return 0; }
void bfx_step(bfx_playback *p, const bfx_asset *a, int car, const char *id,
              int tuned_muffler, int pulse, int type) {
  if (!p || !a || !id || car < 0 || car >= BFX_MAX_CARS) return;
  const char *muffler = tuned_muffler ? "MUFFLER2" : "MUFFLER1";
  for (unsigned i = 0; i < a->nnozzle && i < BFX_MAX_NOZZLE; ++i) {
    const bfx_nozzle *nozzle = &a->nozzle[i];
    if (bfx_car_id(nozzle->car, id) < 0 || strcmp(nozzle->muffler, muffler)) {
      p->frame[car][i] = -1;
      continue;
    }
    int frame = p->frame[car][i];
    if (frame >= 0 && ++frame >= BFX_FRAMES) frame = -1;
    if (frame < 0 && pulse && (type == 0 || type == 1)) {
      frame = 0;
      p->type[car][i] = (int8_t)type;
    }
    p->frame[car][i] = (int8_t)frame;
  }
}
