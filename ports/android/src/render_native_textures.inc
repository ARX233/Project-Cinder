/* Immutable sampled scene resources. Included after mip_down/tex_half/aniso;
 * the caller supplies data and sampling, never an active GL unit or unpack mode. */
static cinder_vk_sampler native_scene_sampler(int mips, int repeat, int ao) {
  cinder_vk_sampler s = { .use_state=1, .mipmaps=(VkBool32)!!mips,
    .min_filter=VK_FILTER_LINEAR, .mag_filter=VK_FILTER_LINEAR,
    .mipmap_mode=!ao && mips && aniso > 1 ? VK_SAMPLER_MIPMAP_MODE_LINEAR : VK_SAMPLER_MIPMAP_MODE_NEAREST,
    .address_u=repeat ? VK_SAMPLER_ADDRESS_MODE_REPEAT : VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    .address_v=repeat ? VK_SAMPLER_ADDRESS_MODE_REPEAT : VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
    .anisotropy=!ao && mips && aniso > 1.5f ? floorf(aniso + 0.5f) : 1.0f };
  return s;
}
static int native_scene_levels(int w, int h) {
  int n=1;
  while (w>1 || h>1) { w=w>1?w/2:1; h=h>1?h/2:1; ++n; }
  return n;
}
static cinder_vk_texture_format native_scene_packed_format(unsigned format) {
  static const cinder_vk_texture_format f[3]={CINDER_VK_TEX_RGB565,CINDER_VK_TEX_RGBA4444,CINDER_VK_TEX_RGBA5551};
  return f[format]; /* caller validates the three file encodings */
}
/* Pixels and all CPU mip outputs live in the named bounded arena until the
 * factory has copied them. CPU mip math is the same rounded packed-channel mean. */
static uint32_t native_scene_packed_texture(uint16_t *pixels, size_t capacity, int w, int h, unsigned format,
                                          int half, int mips) {
  if (!pixels || w<=0 || h<=0 || format>2 || (size_t)w>SIZE_MAX/2/(size_t)h) return 0;
  size_t base_bytes=(size_t)w*(size_t)h*2;
  if (base_bytes>capacity) return 0;
  unsigned char *start=(unsigned char*)pixels, *end=start+capacity;
  uint16_t *base=pixels;
  if (half && w>=TEX_HALF_MIN && h>=TEX_HALF_MIN) {
    size_t next=(size_t)(w/2)*(size_t)(h/2)*2;
    if (base_bytes>capacity || next>capacity-base_bytes) return 0;
    base=(uint16_t*)(start+base_bytes);
    mip_down(pixels,w,h,base,(int)format); w/=2;h/=2;
  }
  cinder_vk_texture_subresource slices[31];
  int n=0; uint16_t *src=base;
  for (int lw=w,lh=h;;) {
    size_t bytes=(size_t)lw*(size_t)lh*2;
    if (n>=31 || (unsigned char*)src>end || bytes>(size_t)(end-(unsigned char*)src)) return 0;
    slices[n]=(cinder_vk_texture_subresource){(uint32_t)n,0,src,bytes,0};++n;
    if (!mips || (lw==1 && lh==1)) break;
    int dw=lw>1?lw/2:1,dh=lh>1?lh/2:1;
    uint16_t *dst=src+(size_t)lw*(size_t)lh;
    size_t next=(size_t)dw*(size_t)dh*2;
    if ((unsigned char*)dst>end || next>(size_t)(end-(unsigned char*)dst)) return 0;
    mip_down(src,lw,lh,dst,(int)format);src=dst;lw=dw;lh=dh;
  }
  cinder_vk_texture_desc d={.width=w,.height=h,.levels=n,.layers=1,
    .format=native_scene_packed_format(format),.sampler=native_scene_sampler(mips,mips,0),
    .subresources=slices,.subresource_count=(size_t)n};
  return cinder_vk_texture_create(&d);
}
static size_t native_wpk_astc_upload(wpk_scene *s, uint32_t i) {
  if (!s || !s->tex_tbl || !s->loaded || !s->textures || !s->tex_warm || i>=s->n_tex) return 0;
  const wpk_tex *t=(const wpk_tex*)s->tex_tbl+i;
  if (t->fmt<WPK_ASTC || t->fmt>=WPK_ASTC+6 || !t->w || !t->h) return 0;
  unsigned k=(unsigned)(t->fmt-WPK_ASTC)/2;
  static const unsigned blocks[3]={4,6,8};
  static const cinder_vk_texture_format formats[3]={CINDER_VK_TEX_ASTC_4x4,CINDER_VK_TEX_ASTC_6x6,CINDER_VK_TEX_ASTC_8x8};
  int pot=is_pot(t->w)&&is_pot(t->h),levels=pot?native_scene_levels(t->w,t->h):1;
  cinder_vk_texture_subresource slices[31];size_t at=0;
  if (levels>31) return 0;
  for (int w=t->w,h=t->h,l=0;l<levels;++l) {
    size_t cols=((size_t)w+blocks[k]-1)/blocks[k],rows=((size_t)h+blocks[k]-1)/blocks[k];
    if (cols>SIZE_MAX/16/rows) return 0;
    size_t bytes=cols*rows*16;
    if (at>t->size || bytes>(size_t)t->size-at) { fprintf(stderr,"%s: texture %u: ASTC levels short\n",s->path,i);return 0; }
    slices[l]=(cinder_vk_texture_subresource){(uint32_t)l,0,NULL,bytes,0};at+=bytes;
    w=w>1?w/2:1;h=h>1?h/2:1;
  }
  unsigned char *pixels=scratch(s,t->size);
  if (!pixels || read_at(s->fd,pixels,t->size,t->off)!=0) { fprintf(stderr,"%s: texture %u unreadable\n",s->path,i);return 0; }
  at=0;for(int l=0;l<levels;++l){slices[l].data=pixels+at;at+=slices[l].bytes;}
  cinder_vk_texture_desc d={.width=t->w,.height=t->h,.levels=levels,.layers=1,.format=formats[k],
    .sampler=native_scene_sampler(pot,pot,0),.subresources=slices,.subresource_count=(size_t)levels};
  uint32_t texture=cinder_vk_texture_create(&d);
  if (!texture) return 0;
  s->loaded[i]=s->textures[i]=texture;s->tex_warm[i]=0;
  return t->size;
}
static size_t native_wpk_tex_upload(wpk_scene *s, uint32_t i) {
  if (!s || !s->tex_tbl || !s->loaded || !s->textures || !s->tex_warm || i>=s->n_tex) return 0;
  const wpk_tex *t=(const wpk_tex*)s->tex_tbl+i;
  if (t->fmt>=WPK_ASTC && t->fmt<WPK_ASTC+6) return native_wpk_astc_upload(s,i);
  if (t->fmt>2 || !t->w || !t->h || (size_t)t->w>SIZE_MAX/2/t->h || t->size<(size_t)t->w*t->h*2) return 0;
  int pot=is_pot(t->w)&&is_pot(t->h);
  size_t capacity=t->size;
  if (pot) { if (capacity>(SIZE_MAX-16)/2) return 0;capacity=capacity*2+16; }
  uint16_t *pixels=scratch(s,capacity);
  if (!pixels || wpk_read_packed_texture(s,t,pixels)!=0) {fprintf(stderr,"%s: texture %u unreadable\n",s->path,i);return 0;}
  uint32_t texture=native_scene_packed_texture(pixels,capacity,t->w,t->h,t->fmt,pot&&tex_half,pot);
  if (!texture) return 0;
  s->loaded[i]=s->textures[i]=texture;s->tex_warm[i]=0;
  return t->size;
}
static size_t native_wpk_cube_upload(wpk_scene *s, uint32_t i) {
  if (!s || !s->cube_tbl || !s->cubes || i>=s->n_cube) return 0;
  uint32_t offsets[6],bytes[6];uint16_t size=0,format=0;size_t total=0;
  for (unsigned f=0;f<6;++f) {
    const uint8_t *r=(const uint8_t*)s->cube_tbl+(size_t)72*i+12*f;uint16_t face_size,face_format;
    memcpy(&face_size,r,2);memcpy(&face_format,r+2,2);memcpy(&offsets[f],r+4,4);memcpy(&bytes[f],r+8,4);
    if (!face_size || face_format>2 || (f&&(face_size!=size || face_format!=format)) ||
        (size_t)face_size>SIZE_MAX/2/face_size || bytes[f]<(size_t)face_size*face_size*2 || bytes[f]>SIZE_MAX-total) return 0;
    size=face_size;format=face_format;total+=bytes[f];
  }
  uint8_t *pixels=scratch(s,total);if(!pixels)return 0;
  cinder_vk_texture_subresource slices[6];size_t at=0;
  for(unsigned f=0;f<6;++f){
    if(read_at(s->fd,pixels+at,bytes[f],offsets[f])!=0){fprintf(stderr,"%s: cube %u unreadable\n",s->path,i);return 0;}
    slices[f]=(cinder_vk_texture_subresource){0,f,pixels+at,(size_t)size*size*2,0};at+=bytes[f];
  }
  cinder_vk_texture_desc d={.width=size,.height=size,.levels=1,.layers=6,.format=native_scene_packed_format(format),
    .sampler=native_scene_sampler(0,0,0),.subresources=slices,.subresource_count=6};
  uint32_t texture=cinder_vk_texture_create(&d);if(!texture)return 0;
  s->cubes[i]=texture;return total;
}
static size_t native_wpk_ao_upload(wpk_scene *s) {
  if (!s || !s->ao_file || s->ao_size<8 || (s->n_tex && !s->tex_tbl)) return 0;
  const uint8_t *f=s->ao_file,*end=f+s->ao_size;uint32_t maps;memcpy(&maps,f+4,4);f+=8;
  const wpk_tex *textures=s->tex_tbl;size_t done=0;
  s->ao_tex=calloc(s->n_tex?s->n_tex:1,sizeof(uint32_t));s->n_ao=s->ao_tex?s->n_tex:0;
  for(uint32_t m=0;m<maps&&s->ao_tex&&(size_t)(end-f)>=52;++m){
    uint16_t wh[2];memcpy(wh,f+48,4);int w=wh[0],h=wh[1];const uint8_t *pixels=f+52;
    if(!is_pot(w)||!is_pot(h)||(size_t)w>SIZE_MAX/(size_t)h||(size_t)w*h>(size_t)(end-pixels))break;
    int t=-1;for(uint32_t i=0;i<s->n_tex&&t<0;++i)if(!memcmp(textures[i].name,f,sizeof textures[i].name))t=(int)i;
    f=pixels+(size_t)w*h;if(t<0||s->ao_tex[t])continue;
    uint8_t *mip=malloc((size_t)w*h);if(!mip)break;
    cinder_vk_texture_subresource slices[31];int n=1;
    slices[0]=(cinder_vk_texture_subresource){0,0,pixels,(size_t)w*h,0};const uint8_t *src=pixels;
    for(int lw=w,lh=h;lw>1||lh>1;){
      int dw=lw>1?lw/2:1,dh=lh>1?lh/2:1,sx=lw>1,sy=lh>1;
      uint8_t *dst=mip+(src==pixels?0:(size_t)(src-mip)+(size_t)lw*lh);
      for(int y=0;y<dh;++y)for(int x=0;x<dw;++x){const uint8_t*q=src+(size_t)(y<<sy)*lw+(x<<sx);dst[(size_t)y*dw+x]=(uint8_t)((q[0]+q[sx]+q[(size_t)lw*sy]+q[(size_t)lw*sy+sx]+2)/4);}
      slices[n]=(cinder_vk_texture_subresource){(uint32_t)n,0,dst,(size_t)dw*dh,0};++n;src=dst;lw=dw;lh=dh;
    }
    cinder_vk_texture_desc d={.width=w,.height=h,.levels=n,.layers=1,.format=CINDER_VK_TEX_L8,
      .sampler=native_scene_sampler(1,0,1),.subresources=slices,.subresource_count=(size_t)n};
    uint32_t texture=cinder_vk_texture_create(&d);free(mip);
    if(!texture)continue;
    s->ao_tex[t]=texture;done+=(size_t)w*h;
  }
  free(s->ao_file);s->ao_file=NULL;return done+1;
}
