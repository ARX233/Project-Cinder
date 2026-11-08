/* Include in render.c after render_native_textures.inc / wpk_texture_over.
 * RGBA8 exact level zero; deterministic CPU mip means, no RGB565 approximation.
 * GL names route through existing GL or VKGL; native path uses resource API.
 */
#include "render_ghost_paint.h"
static void rgp_down(const uint8_t*s,unsigned w,unsigned h,uint8_t*d){
 unsigned dw=w>1?w/2:1,dh=h>1?h/2:1,sx=w>1,sy=h>1;
 for(unsigned y=0;y<dh;y++)for(unsigned x=0;x<dw;x++)for(unsigned c=0;c<4;c++){
  const uint8_t*p=s+((size_t)(y<<sy)*w+(x<<sx))*4+c;
  d[((size_t)y*dw+x)*4+c]=(uint8_t)((p[0]+p[sx*4]+p[(size_t)w*sy*4]+p[((size_t)w*sy+sx)*4]+2)/4);
 }
}
uint32_t render_ghost_paint_rgba8(const uint8_t*rgba,size_t bytes,unsigned w,unsigned h){
 if(!rgba||!w||!h||w>2048||h>2048||bytes!=(size_t)w*h*4)return 0;
 /* Source page dimensions in this recipe are powers of two. Reject rather than
  * silently change sampler/UV semantics for an unexpected replacement. */
 if((w&(w-1))||(h&(h-1)))return 0;
 size_t mipbytes=0;unsigned levels=1;
 for(unsigned lw=w,lh=h;lw>1||lh>1;){lw=lw>1?lw/2:1;lh=lh>1?lh/2:1;mipbytes+=(size_t)lw*lh*4;levels++;}
 if(levels>12||mipbytes>bytes)return 0;
 uint8_t*mips=malloc(mipbytes?mipbytes:1);if(!mips)return 0;
 const uint8_t*src=rgba;uint8_t*dst=mips;
 for(unsigned lw=w,lh=h;lw>1||lh>1;){rgp_down(src,lw,lh,dst);lw=lw>1?lw/2:1;lh=lh>1?lh/2:1;src=dst;dst+=(size_t)lw*lh*4;}
 uint32_t texture=0;
#ifdef WMMT_NATIVE_VK
 cinder_vk_texture_subresource slices[12];const uint8_t*p=rgba;size_t at=0;
 for(unsigned lw=w,lh=h,l=0;l<levels;l++){
  slices[l]=(cinder_vk_texture_subresource){l,0,p,(size_t)lw*lh*4,0};
  if(!l)p=mips;else {at+=(size_t)lw*lh*4;p=mips+at;}
  lw=lw>1?lw/2:1;lh=lh>1?lh/2:1;
 }
 cinder_vk_texture_desc desc={.width=(int)w,.height=(int)h,.levels=(int)levels,.layers=1,
  .format=CINDER_VK_TEX_RGBA8,.sampler=native_scene_sampler(levels>1,1,0),.subresources=slices,.subresource_count=levels};
 texture=cinder_vk_texture_create(&desc);
#else
 GLint old_texture=0,old_unpack=4;glGetIntegerv(GL_TEXTURE_BINDING_2D,&old_texture);glGetIntegerv(GL_UNPACK_ALIGNMENT,&old_unpack);
 glPixelStorei(GL_UNPACK_ALIGNMENT,1);glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
 const uint8_t*p=rgba;size_t at=0;
 for(unsigned lw=w,lh=h,l=0;l<levels;l++){
  glTexImage2D(GL_TEXTURE_2D,(GLint)l,GL_RGBA,(GLsizei)lw,(GLsizei)lh,0,GL_RGBA,GL_UNSIGNED_BYTE,p);
  if(!l)p=mips;else {at+=(size_t)lw*lh*4;p=mips+at;}
  lw=lw>1?lw/2:1;lh=lh>1?lh/2:1;
 }
 glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,levels>1?mip_filter():GL_LINEAR);
 glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
 glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_REPEAT);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_REPEAT);
 if(levels>1)tex_aniso();
 if(glGetError()!=GL_NO_ERROR){if(texture)glDeleteTextures(1,&texture);texture=0;}
 glBindTexture(GL_TEXTURE_2D,(GLuint)old_texture);glPixelStorei(GL_UNPACK_ALIGNMENT,old_unpack);
#endif
 free(mips);return texture;
}
void render_ghost_paint_destroy(uint32_t texture){if(!texture)return;
#ifdef WMMT_NATIVE_VK
 cinder_vk_texture_destroy(texture);
#else
 glDeleteTextures(1,&texture);
#endif
}
