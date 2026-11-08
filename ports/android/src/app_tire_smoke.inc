/* Own-car clRollUpManager reconstruction; include after G, before VS helpers.
 * Prepared only at resource/context setup. Draw never opens/decodes a file.
 * This independent texture and particle owner never touches Ghost caches/RNG. */
static struct {
  TireSmoke particles;
  uint32_t texture;
  uint64_t owner;
  int attempted;
} PLAYER_SMOKE;

static void player_smoke_reset(void) {
  tire_smoke_reset(&PLAYER_SMOKE.particles);
  if (++PLAYER_SMOKE.owner==0) ++PLAYER_SMOKE.owner;
}
static int player_smoke_same_file(const struct stat *a,const struct stat *b) {
  if (a->st_dev!=b->st_dev || a->st_ino!=b->st_ino || a->st_mode!=b->st_mode ||
      a->st_nlink!=b->st_nlink || a->st_uid!=b->st_uid || a->st_gid!=b->st_gid ||
      a->st_size!=b->st_size || a->st_mtime!=b->st_mtime || a->st_ctime!=b->st_ctime) return 0;
#ifdef __APPLE__
  return a->st_mtimespec.tv_nsec==b->st_mtimespec.tv_nsec && a->st_ctimespec.tv_nsec==b->st_ctimespec.tv_nsec;
#else
  return a->st_mtim.tv_nsec==b->st_mtim.tv_nsec && a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;
#endif
}
void app_smoke_release(int context_lost) {
  if (PLAYER_SMOKE.texture && !context_lost) render_ghost_paint_destroy(PLAYER_SMOKE.texture);
  if (context_lost) render_tire_smoke_context_lost(); else render_tire_smoke_release();
  memset(&PLAYER_SMOKE,0,sizeof PLAYER_SMOKE);
  player_smoke_reset();
}
static void player_smoke_open(const char *data_dir) {
  if (PLAYER_SMOKE.attempted) return;
  PLAYER_SMOKE.attempted=1;
  int root=-1,fd=-1; unsigned char *bytes=NULL;
  struct stat before,opened,after,named;
  TireSmokeAtlas atlas;
  root=data_dir?open(data_dir,O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_NONBLOCK):-1;
  if (root<0 || fstatat(root,"tiresmoke.bin",&before,AT_SYMLINK_NOFOLLOW) ||
      !S_ISREG(before.st_mode) || before.st_nlink!=1 || before.st_size!=TIRE_SMOKE_ASSET_SIZE) goto done;
  fd=openat(root,"tiresmoke.bin",O_RDONLY|O_NOFOLLOW|O_NONBLOCK);
  if (fd<0 || fstat(fd,&opened) || !player_smoke_same_file(&before,&opened)) goto done;
  bytes=(unsigned char *)malloc(TIRE_SMOKE_ASSET_SIZE);
  if (!bytes) goto done;
  size_t at=0;
  while (at<TIRE_SMOKE_ASSET_SIZE) {
    ssize_t n=read(fd,bytes+at,TIRE_SMOKE_ASSET_SIZE-at);
    if (n<0 && errno==EINTR) continue;
    if (n<=0) goto done;
    at+=(size_t)n;
  }
  if (fstat(fd,&after) || fstatat(root,"tiresmoke.bin",&named,AT_SYMLINK_NOFOLLOW) ||
      !player_smoke_same_file(&opened,&after) || !player_smoke_same_file(&opened,&named)) goto done;
  unsigned char digest[32]; char hex[65];
  ghost_catalog_sha256_bytes(bytes,TIRE_SMOKE_ASSET_SIZE,digest);
  for (int i=0;i<32;i++) snprintf(hex+2*i,3,"%02x",digest[i]);
  if (strcmp(hex,TIRE_SMOKE_ASSET_SHA256) || !tire_smoke_asset_parse(&atlas,bytes,TIRE_SMOKE_ASSET_SIZE)) goto done;
  PLAYER_SMOKE.texture=render_ghost_paint_rgba8(atlas.rgba,atlas.bytes,atlas.width,atlas.height);
done:
  free(bytes);
  if (fd>=0) close(fd);
  if (root>=0) close(root);
  if (!PLAYER_SMOKE.texture) fprintf(stderr,"tire smoke: missing, changed or unavailable original atlas; explicitly reconvert original data to enable\n");
}
static void player_smoke_tick(const car_state *car) {
  if (!car || !car->tire_smoke_valid || !PLAYER_SMOKE.texture) {
    tire_smoke_reset(&PLAYER_SMOKE.particles); return;
  }
  tire_smoke_step(&PLAYER_SMOKE.particles,PLAYER_SMOKE.owner,car->tire_smoke_tick,&car->tire_smoke,1);
}
static void player_smoke_draw(const mat4 *proj,const mat4 *view,render_params *params) {
  if (!PLAYER_SMOKE.texture) return;
  TireSmokeVertex quads[TIRE_SMOKE_MAX*4];
  size_t n=tire_smoke_vertices(&PLAYER_SMOKE.particles,view->m,quads,TIRE_SMOKE_MAX*4);
  if (n) (void)render_tire_smoke(proj,quads,n,PLAYER_SMOKE.texture,params);
}
