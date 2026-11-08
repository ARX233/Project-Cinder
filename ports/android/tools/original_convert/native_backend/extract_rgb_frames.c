/* Host-only independent selected-frame decoder. SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
#include <libswscale/swscale.h>
typedef struct{int fd;int64_t pos,size;}IO;
static int rd(void*p,uint8_t*b,int n){IO*i=p;ssize_t r=pread(i->fd,b,n,i->pos);if(r>0)i->pos+=r;return r>0?(int)r:r<0?AVERROR(errno):AVERROR_EOF;}
static int64_t sk(void*p,int64_t o,int q){IO*i=p;if(q==AVSEEK_SIZE)return i->size;int64_t b=q==SEEK_SET?0:q==SEEK_CUR?i->pos:q==SEEK_END?i->size:-1;if(b<0||o < -b||b+o>i->size)return AVERROR(EINVAL);return i->pos=b+o;}
int main(int argc,char**argv){
 if(argc!=4)return 2;int fd=open(argv[1],O_RDONLY);struct stat st;if(fd<0||fstat(fd,&st))return 2;
 int wanted[64],nw=0;char*cursor=argv[3];while(*cursor){if(nw==64)return 2;char*end;long n=strtol(cursor,&end,10);if(end==cursor||n<0||n>3000||(*end&&*end!=','))return 2;wanted[nw++]=n;cursor=*end?end+1:end;}
 uint8_t magic[4];if(pread(fd,magic,4,0)!=4)return 2;IO io={fd,0,st.st_size};AVIOContext*pb=avio_alloc_context(av_malloc(32768),32768,0,&io,rd,NULL,sk);AVFormatContext*f=avformat_alloc_context();f->pb=pb;f->flags|=AVFMT_FLAG_CUSTOM_IO;
 int r=avformat_open_input(&f,NULL,av_find_input_format(!memcmp(magic,"BIK",3)?"bink":"mov"),NULL);if(r<0)return 3;if(avformat_find_stream_info(f,NULL)<0)return 3;int si=av_find_best_stream(f,AVMEDIA_TYPE_VIDEO,-1,-1,NULL,0);if(si<0)return 4;AVCodecParameters*q=f->streams[si]->codecpar;if(q->width>640||q->height>480||q->width<1||q->height<1)return 4;
 const AVCodec*dec=avcodec_find_decoder(q->codec_id);AVCodecContext*c=avcodec_alloc_context3(dec);avcodec_parameters_to_context(c,q);c->thread_count=1;c->err_recognition=AV_EF_EXPLODE;if(avcodec_open2(c,dec,NULL)<0)return 4;
 AVFrame*fr=av_frame_alloc();AVPacket*p=av_packet_alloc();struct SwsContext*sws=NULL;int index=0,found=0,eof=0;
 while(found<nw){r=avcodec_receive_frame(c,fr);if(r==AVERROR(EAGAIN)){do{av_packet_unref(p);r=av_read_frame(f,p);}while(r>=0&&p->stream_index!=si);if(r==AVERROR_EOF&&!eof){eof=1;r=avcodec_send_packet(c,NULL);}else if(r>=0)r=avcodec_send_packet(c,p);av_packet_unref(p);if(r<0)return 5;continue;}if(r<0)return 6;
  for(int i=0;i<nw;i++)if(wanted[i]==index){int stride=fr->width*3;size_t bytes=(size_t)stride*fr->height;uint8_t*rgb=av_mallocz(bytes);uint8_t*planes[4]={rgb,NULL,NULL,NULL};int lines[4]={stride,0,0,0};sws=sws_getCachedContext(sws,fr->width,fr->height,fr->format,fr->width,fr->height,AV_PIX_FMT_RGB24,SWS_BILINEAR,NULL,NULL,NULL);if(!rgb||!sws||sws_scale(sws,(const uint8_t*const*)fr->data,fr->linesize,0,fr->height,planes,lines)!=fr->height)return 7;char path[4096];if(snprintf(path,sizeof path,"%s/frame-%d.rgb",argv[2],index)>=(int)sizeof path)return 7;int out=open(path,O_WRONLY|O_CREAT|O_EXCL,0600);if(out<0)return 8;size_t done=0;while(done<bytes){ssize_t n=write(out,rgb+done,bytes-done);if(n<=0)return 8;done+=n;}close(out);av_free(rgb);printf("{\"frame\":%d,\"width\":%d,\"height\":%d,\"tb_num\":%d,\"tb_den\":%d}\n",index,fr->width,fr->height,f->streams[si]->time_base.num,f->streams[si]->time_base.den);found++;}
  index++;av_frame_unref(fr);
 }
 sws_freeContext(sws);avcodec_free_context(&c);av_frame_free(&fr);av_packet_free(&p);avformat_close_input(&f);av_freep(&pb->buffer);avio_context_free(&pb);close(fd);return 0;
}
