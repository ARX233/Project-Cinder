/* Read only the actual selected original VPK plane before GO. The existing
 * stock-wpk/RGB565 vinyl path must never replace a custom Ghost body page. */
static int app_arcade_vinyl_read(int pack,int body,int base_paint,int vinyl,int bonnet,
                                  ghost_paint_overlay *overlay,unsigned char **owned) {
  if(owned)*owned=NULL;if(overlay)memset(overlay,0,sizeof *overlay);
  if(!owned||!overlay||pack<0||pack>=CARDB_NPACKS||body<0||body>3||base_paint<0||base_paint>=32||vinyl<=0||vinyl>255||bonnet<0)return 0;
  char path[1200];int length=snprintf(path,sizeof path,"%s/vinyl/%s.vpk",G.data_dir,CARDB_PACKS[pack]);
  if(length<=0||length>=(int)sizeof path)return 0;
  int fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);if(fd<0)return 0;
  struct stat st;unsigned char head[236],best[12]={0},entry[12];unsigned char*z=NULL,*pixels=NULL;int ok=0;
  if(fstat(fd,&st)||!S_ISREG(st.st_mode)||st.st_size<236||st.st_size>64*1024*1024)goto out_ghost_vinyl;
  size_t at=0;while(at<sizeof head){ssize_t got=read(fd,head+at,sizeof head-at);if(got<0&&errno==EINTR)continue;if(got<=0)goto out_ghost_vinyl;at+=(size_t)got;}
  if(memcmp(head,"VPK1",4))goto out_ghost_vinyl;
  uint32_t count=ah_u32(head+4),planes=ah_u32(head+8);uint64_t directory=236u+(uint64_t)count*12u+(uint64_t)planes*8u;
  if(!count||count>4096||!planes||planes>4096||directory>(uint64_t)st.st_size)goto out_ghost_vinyl;
  const unsigned char*material=head+12+48*body;size_t mlen=0;while(mlen<48&&material[mlen])mlen++;
  if(!mlen||mlen==48)goto out_ghost_vinyl;
  for(size_t i=0;i<mlen;i++)if(material[i]<32||material[i]>=127||material[i]=='/'||material[i]=='\\')goto out_ghost_vinyl;
  unsigned works=head[204+base_paint];int carbon=bonnet>1,found=0;
  for(uint32_t i=0;i<count;i++){
    at=0;while(at<sizeof entry){ssize_t got=read(fd,entry+at,sizeof entry-at);if(got<0&&errno==EINTR)continue;if(got<=0)goto out_ghost_vinyl;at+=(size_t)got;}
    if(entry[0]!=body||entry[1]!=vinyl||(entry[2]&&entry[2]!=works))continue;
    if(entry[3]==carbon||!found){memcpy(best,entry,12);found=1+(entry[3]==carbon);}
  }
  if(!found)goto out_ghost_vinyl;
  uint32_t plane=ah_u32(best+8);unsigned char loc[8];if(plane>=planes)goto out_ghost_vinyl;
  off_t position=(off_t)(236u+(uint64_t)count*12u+(uint64_t)plane*8u);if(lseek(fd,position,SEEK_SET)!=position)goto out_ghost_vinyl;
  at=0;while(at<sizeof loc){ssize_t got=read(fd,loc+at,sizeof loc-at);if(got<0&&errno==EINTR)continue;if(got<=0)goto out_ghost_vinyl;at+=(size_t)got;}
  uint64_t offset=ah_u32(loc);uint32_t compressed=ah_u32(loc+4);size_t raw=512u*512u*(best[7]?1u:4u);
  if(offset<directory||!compressed||compressed>compressBound((uLong)raw)||offset>(uint64_t)st.st_size||compressed>(uint64_t)st.st_size-offset)goto out_ghost_vinyl;
  z=malloc(compressed);pixels=malloc(raw);if(!z||!pixels||lseek(fd,(off_t)offset,SEEK_SET)!=(off_t)offset)goto out_ghost_vinyl;
  at=0;while(at<compressed){ssize_t got=read(fd,z+at,compressed-at);if(got<0&&errno==EINTR)continue;if(got<=0)goto out_ghost_vinyl;at+=(size_t)got;}
  z_stream stream={0};stream.next_in=z;stream.avail_in=compressed;stream.next_out=pixels;stream.avail_out=(uInt)raw;
  if(inflateInit(&stream)!=Z_OK)goto out_ghost_vinyl;int rc=inflate(&stream,Z_FINISH);
  int exact=rc==Z_STREAM_END&&stream.total_in==compressed&&stream.total_out==raw;inflateEnd(&stream);if(!exact)goto out_ghost_vinyl;
  struct stat after;if(fstat(fd,&after)||after.st_dev!=st.st_dev||after.st_ino!=st.st_ino||after.st_mode!=st.st_mode||after.st_size!=st.st_size||after.st_mtime!=st.st_mtime||after.st_ctime!=st.st_ctime)goto out_ghost_vinyl;
#ifdef __APPLE__
  if(after.st_mtimespec.tv_nsec!=st.st_mtimespec.tv_nsec||after.st_ctimespec.tv_nsec!=st.st_ctimespec.tv_nsec)goto out_ghost_vinyl;
#else
  if(after.st_mtim.tv_nsec!=st.st_mtim.tv_nsec||after.st_ctim.tv_nsec!=st.st_ctim.tv_nsec)goto out_ghost_vinyl;
#endif
  overlay->pixels=pixels;overlay->bytes=raw;overlay->width=overlay->height=512;memcpy(overlay->material,material,mlen);
  overlay->rgb_mask=best[7]!=0;memcpy(overlay->color,best+4,4);overlay->vinyl=(uint32_t)vinyl;overlay->carbon_bonnet=(unsigned char)carbon;
  ghost_catalog_sha256_bytes(pixels,raw,overlay->sha256);*owned=pixels;pixels=NULL;ok=1;
 out_ghost_vinyl:free(z);free(pixels);close(fd);return ok;
}
