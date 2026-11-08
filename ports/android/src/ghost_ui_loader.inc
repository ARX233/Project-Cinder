/* Ghost-only WCP1 parser; Android opens only the independently catalog-verified path.
 * Duplicates or any malformed record leave existing resources completely unchanged. */
static void load_ghost_ui(const char *data_dir) {
  char path[1024]; FILE *f = NULL;
#if defined(__ANDROID__)
  extern int android_optional_resource_path(const char *, char *, size_t);
  if (!android_optional_resource_path("ghost-ui.bin", path, sizeof path)) return;
  f = fopen(path, "rb");
#else
  if (snprintf(path, sizeof path, "%s/ghost-ui.bin", data_dir) >= (int)sizeof path) return;
  f = fopen(path, "rb");
#endif
  if (!f) return;
  char magic[4]; uint32_t version, n = 0, na = 0, total; long length;
  int *ids = NULL; float (*sizes)[2] = NULL; long *offs = NULL; uint32_t *zs = NULL;
  anm_anim *anims = NULL;
  GLuint *tex = NULL; long *alloff = NULL; uint32_t *allzs = NULL, *used = NULL;
  float (*allsize)[2] = NULL; int *allids = NULL; uint16_t (*cols)[2] = NULL; anm_anim *allanims = NULL;
  if (fseek(f, 0, SEEK_END) || (length = ftell(f)) < 16 || length > 256L*1024*1024 || fseek(f,0,SEEK_SET)) goto bad_ghost;
  if (!read_all(f,magic,4) || memcmp(magic,"WCP1",4) || !read_all(f,&version,4) || version != 1 ||
      !read_all(f,&n,4) || n > 65535-A.nsprites || !read_all(f,&na,4) || !na || na > 4096-A.nanims) goto bad_ghost;
  ids=calloc(n ? n : 1,sizeof *ids); sizes=calloc(n ? n : 1,sizeof *sizes);
  offs=calloc(n ? n : 1,sizeof *offs); zs=calloc(n ? n : 1,sizeof *zs); anims=calloc(na,sizeof *anims);
  if (!ids || !sizes || !offs || !zs || !anims) goto bad_ghost;
  for (uint32_t i=0;i<n;i++) {
    uint16_t wh[2];
    if (!read_all(f,&ids[i],4) || !read_all(f,wh,4) || !read_all(f,&zs[i],4) || ids[i]<0 || !wh[0] || !wh[1] || wh[0]>2048 || wh[1]>2048) goto bad_ghost;
    for (uint32_t j=0;j<A.nsprites;j++) if (ids[i]==A.ids[j]) goto bad_ghost;
    for (uint32_t j=0;j<i;j++) if (ids[i]==ids[j]) goto bad_ghost;
    size_t raw=(size_t)wh[0]*wh[1]*4, stored=zs[i] ? zs[i] : raw;
    if (zs[i] && stored>compressBound((uLong)raw)) goto bad_ghost;
    offs[i]=ftell(f); if (offs[i]<0 || offs[i]>length || stored>(size_t)(length-offs[i])) goto bad_ghost;
    sizes[i][0]=wh[0]; sizes[i][1]=wh[1];
    if (zs[i]) {
      unsigned char *z=malloc(stored), *px=malloc(raw); uLongf out=(uLongf)raw;
      int ok=0;
      if (z && px && read_all(f,z,stored)) {
        z_stream stream={0}; stream.next_in=z; stream.avail_in=(uInt)stored; stream.next_out=px; stream.avail_out=(uInt)raw;
        if (inflateInit(&stream)==Z_OK) { int rc=inflate(&stream,Z_FINISH);
          ok=rc==Z_STREAM_END && stream.total_in==stored && stream.total_out==out; inflateEnd(&stream); }
      }
      free(z); free(px); if (!ok) goto bad_ghost;
    } else if (fseek(f,(long)raw,SEEK_CUR)) goto bad_ghost;
  }
  for (uint32_t i=0;i<na;i++) {
    anm_anim *a=&anims[i];
    if (!read_all(f,a->name,48) || !memchr(a->name,0,48) || !a->name[0] ||
        !read_all(f,&a->nframes,4) || !a->nframes || a->nframes>10000 ||
        !read_all(f,&a->nrecs,4) || a->nrecs>200000) goto bad_ghost;
    for (uint32_t j=0;j<A.nanims;j++) if (!strcmp(a->name,A.anims[j].name)) goto bad_ghost;
    for (uint32_t j=0;j<i;j++) if (!strcmp(a->name,anims[j].name)) goto bad_ghost;
    a->frames=calloc(a->nframes,sizeof *a->frames); a->recs=calloc(a->nrecs ? a->nrecs : 1,sizeof *a->recs);
    if (!a->frames || !a->recs || !read_all(f,a->frames,(size_t)a->nframes*8)) goto bad_ghost;
    for (uint32_t j=0;j<a->nframes;j++) if (a->frames[j][0]>a->nrecs || a->frames[j][1]>a->nrecs-a->frames[j][0]) goto bad_ghost;
    for (uint32_t j=0;j<a->nrecs;j++) {
      int32_t sid; anm_rec *r=&a->recs[j]; uint32_t k;
      if (!read_all(f,&sid,4) || !read_all(f,&r->blend,2) || r->blend>2 ||
          !read_all(f,&r->a,24) || !read_all(f,r->mul,16)) goto bad_ghost;
      if (!isfinite(r->a) || !isfinite(r->b) || !isfinite(r->c) || !isfinite(r->d) || !isfinite(r->x) || !isfinite(r->y)) goto bad_ghost;
      if (sid==-1) { r->sprite=0xffff; continue; }
      if (sid<0) goto bad_ghost;
      for (k=0;k<A.nsprites;k++) if (A.ids[k]==sid) break;
      if (k==A.nsprites) { uint32_t j2; for (j2=0;j2<n;j2++) if (ids[j2]==sid) break;
        if (j2==n) goto bad_ghost; k+=j2; }
      r->sprite=(uint16_t)k;
    }
  }
  if (ftell(f)!=length) goto bad_ghost;
  total=A.nsprites+n;
  tex=calloc(total,sizeof *tex); alloff=calloc(total,sizeof *alloff); allzs=calloc(total,sizeof *allzs);
  used=calloc(total,sizeof *used); allsize=calloc(total,sizeof *allsize); allids=calloc(total,sizeof *allids);
  cols=calloc(total,sizeof *cols); allanims=calloc(A.nanims+na,sizeof *allanims);
  if (!tex || !alloff || !allzs || !used || !allsize || !allids || !cols || !allanims) goto bad_ghost;
#define CP(dst,src) memcpy(dst,src,A.nsprites*sizeof *(src))
  CP(tex,A.tex); CP(alloff,A.offset); CP(allzs,A.zsize); CP(used,A.used); CP(allsize,A.size); CP(allids,A.ids); CP(cols,A.cols);
#undef CP
  memcpy(alloff+A.nsprites,offs,n*sizeof *offs); memcpy(allzs+A.nsprites,zs,n*sizeof *zs);
  memcpy(allsize+A.nsprites,sizes,n*sizeof *sizes); memcpy(allids+A.nsprites,ids,n*sizeof *ids);
  memcpy(allanims,A.anims,A.nanims*sizeof *anims); memcpy(allanims+A.nanims,anims,na*sizeof *anims);
  free(A.tex); free(A.offset); free(A.zsize); free(A.used); free(A.size); free(A.ids); free(A.cols); free(A.anims);
  A.tex=tex; A.offset=alloff; A.zsize=allzs; A.used=used; A.size=allsize; A.ids=allids; A.cols=cols;
  A.ghost_begin=A.nsprites; A.anims=allanims; A.nsprites=total; A.nanims+=na; A.ghost_file=f;
  free(ids); free(sizes); free(offs); free(zs); free(anims); return;
bad_ghost:
  fprintf(stderr,"Ignoring invalid ghost-ui.bin\n");
  if (anims) for (uint32_t i=0;i<na;i++) { free(anims[i].frames); free(anims[i].recs); }
  free(anims); free(ids); free(sizes); free(offs); free(zs); free(tex); free(alloff); free(allzs); free(used); free(allsize); free(allids); free(cols); free(allanims); fclose(f);
}
