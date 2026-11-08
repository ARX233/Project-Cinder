/* Host-only proof utility, not packaged in APK. SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/stat.h>
#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
#include <libavutil/sha.h>
#include <libavutil/imgutils.h>
typedef struct {int fd; int64_t pos,size;} IO;
static int rd(void*p,uint8_t*b,int n){IO*i=p;ssize_t r=pread(i->fd,b,n,i->pos);if(r>0)i->pos+=r;return r>0?(int)r:r<0?AVERROR(errno):AVERROR_EOF;}
static int64_t sk(void*p,int64_t o,int w){IO*i=p;if(w==AVSEEK_SIZE)return i->size;int64_t b=w==SEEK_SET?0:w==SEEK_CUR?i->pos:w==SEEK_END?i->size:-1;if(b<0||o < -b || b+o>i->size)return AVERROR(EINVAL);return i->pos=b+o;}
static int drain(AVCodecContext*c,AVFrame*f,int64_t*frames,int64_t*samples,struct AVSHA*h){int r;while((r=avcodec_receive_frame(c,f))>=0){(*frames)++;*samples+=f->nb_samples;
 if(c->codec_type==AVMEDIA_TYPE_VIDEO){int n=av_image_get_buffer_size(f->format,f->width,f->height,1);uint8_t*b=av_malloc(n);if(!b)return -1;av_image_copy_to_buffer(b,n,(const uint8_t*const*)f->data,f->linesize,f->format,f->width,f->height,1);av_sha_update(h,b,n);av_free(b);}else{int n=av_get_bytes_per_sample(f->format)*f->nb_samples;int planar=av_sample_fmt_is_planar(f->format);for(int k=0;k<(planar?f->ch_layout.nb_channels:1);k++)av_sha_update(h,f->extended_data[k],n*(planar?1:f->ch_layout.nb_channels));}av_frame_unref(f);}return r==AVERROR(EAGAIN)||r==AVERROR_EOF?0:r;}
int main(int argc,char**argv){if(argc!=2)return 2;int fd=open(argv[1],O_RDONLY);struct stat st;if(fd<0||fstat(fd,&st))return 2;IO io={fd,0,st.st_size};AVIOContext*pb=avio_alloc_context(av_malloc(32768),32768,0,&io,rd,NULL,sk);AVFormatContext*f=avformat_alloc_context();f->pb=pb;f->flags|=AVFMT_FLAG_CUSTOM_IO;int r=avformat_open_input(&f,NULL,av_find_input_format("mov"),NULL);if(r<0)return 3;r=avformat_find_stream_info(f,NULL);if(r<0)return 4;if(f->nb_streams>2)return 5;
 AVCodecContext*c[2]={0};int64_t frames[2]={0},samples[2]={0};struct AVSHA*h[2]={0};AVFrame*frame=av_frame_alloc();AVPacket*p=av_packet_alloc();
 for(unsigned k=0;k<f->nb_streams;k++){AVCodecParameters*q=f->streams[k]->codecpar;const AVCodec*d=avcodec_find_decoder(q->codec_id);c[k]=avcodec_alloc_context3(d);avcodec_parameters_to_context(c[k],q);c[k]->err_recognition=AV_EF_EXPLODE;c[k]->thread_count=1;if(avcodec_open2(c[k],d,NULL)<0)return 6;h[k]=av_sha_alloc();av_sha_init(h[k],256);}
 while((r=av_read_frame(f,p))>=0){unsigned k=p->stream_index;if(k>=f->nb_streams)return 7;r=avcodec_send_packet(c[k],p);av_packet_unref(p);if(r<0||drain(c[k],frame,&frames[k],&samples[k],h[k])<0)return 8;}if(r!=AVERROR_EOF)return 9;
 printf("{\"duration_us\":%lld,\"streams\":[",(long long)f->duration);
 for(unsigned k=0;k<f->nb_streams;k++){avcodec_send_packet(c[k],NULL);if(drain(c[k],frame,&frames[k],&samples[k],h[k])<0)return 10;AVCodecParameters*q=f->streams[k]->codecpar;uint8_t digest[32];av_sha_final(h[k],digest);printf("%s{\"codec\":\"%s\",\"profile\":%d,\"level\":%d,\"width\":%d,\"height\":%d,\"sample_rate\":%d,\"channels\":%d,\"decoded_frames\":%lld,\"decoded_samples\":%lld,\"declared_frames\":%lld,\"decoded_sha256\":\"",k?",":"",avcodec_get_name(q->codec_id),q->profile,q->level,q->width,q->height,q->sample_rate,q->ch_layout.nb_channels,(long long)frames[k],(long long)samples[k],(long long)f->streams[k]->nb_frames);for(int x=0;x<32;x++)printf("%02x",digest[x]);printf("\"}");avcodec_free_context(&c[k]);av_free(h[k]);}
 printf("]}\n");av_frame_free(&frame);av_packet_free(&p);avformat_close_input(&f);av_freep(&pb->buffer);avio_context_free(&pb);close(fd);return 0;}
