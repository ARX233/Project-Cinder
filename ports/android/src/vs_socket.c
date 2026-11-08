#define _POSIX_C_SOURCE 200809L
#include "vs_socket.h"
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
int vs4_entropy(vs4_nonce *out){if(!out)return 0;vs4_nonce n;size_t at=0;int fd=open("/dev/urandom",O_RDONLY);if(fd<0)return 0;while(at<16){ssize_t got=read(fd,n.b+at,16-at);if(got<0&&errno==EINTR)continue;if(got<=0){close(fd);return 0;}at+=(size_t)got;}close(fd);if(!vs4_nonce_nonzero(n))return 0;*out=n;return 1;}
int vs4_udp_open(int port,const char *ip){if(port<0||port>65535)return -1;int fd=socket(AF_INET,SOCK_DGRAM,0);if(fd<0)return -1;int flags=fcntl(fd,F_GETFL,0);if(flags<0||fcntl(fd,F_SETFL,flags|O_NONBLOCK)<0){close(fd);return -1;}struct sockaddr_in a;memset(&a,0,sizeof a);a.sin_family=AF_INET;a.sin_port=htons((uint16_t)port);if(inet_pton(AF_INET,ip?ip:"0.0.0.0",&a.sin_addr)!=1||bind(fd,(struct sockaddr *)&a,sizeof a)<0){close(fd);return -1;}return fd;}
uint64_t vs4_endpoint(const struct sockaddr_in *a){return a&&a->sin_family==AF_INET?((uint64_t)ntohl(a->sin_addr.s_addr)<<16)|ntohs(a->sin_port):0;}
struct sockaddr_in vs4_sockaddr(uint64_t ep){struct sockaddr_in a;memset(&a,0,sizeof a);a.sin_family=AF_INET;a.sin_addr.s_addr=htonl((uint32_t)(ep>>16));a.sin_port=htons((uint16_t)ep);return a;}
uint64_t vs4_now_ms(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;return (uint64_t)t.tv_sec*1000+(uint64_t)t.tv_nsec/1000000;}
void vs4_udp_emit(void *ctx,uint64_t ep,const uint8_t *b,size_t n){if(!ctx||!ep||!b||!n)return;int fd=*(int *)ctx;struct sockaddr_in a=vs4_sockaddr(ep);(void)sendto(fd,b,n,0,(const struct sockaddr *)&a,sizeof a);}
int vs4_udp_receive(int fd,uint8_t *b,size_t cap,uint64_t *source,int *empty){struct sockaddr_in a;socklen_t len=sizeof a;*empty=0;/* recvmsg MSG_TRUNC distinguishes oversized datagrams, including exact-prefix attacks. */struct iovec iov={b,cap};struct msghdr msg;memset(&msg,0,sizeof msg);msg.msg_name=&a;msg.msg_namelen=len;msg.msg_iov=&iov;msg.msg_iovlen=1;ssize_t n=recvmsg(fd,&msg,0);if(n<0){if(errno==EAGAIN||errno==EWOULDBLOCK)*empty=1;return -1;}*source=vs4_endpoint(&a);if((msg.msg_flags&MSG_TRUNC)||(size_t)n>cap)return -2;return (int)n;}
int vs4_discovery_request(const uint8_t *b,size_t n){static const uint8_t request[8]={'W','V','S','4',4,32,0,0};return n==8&&!memcmp(b,request,8);}
void vs4_discovery_offer(uint8_t out[48],const vs4_state *s,const char *name){memset(out,0,48);memcpy(out,"WVS4",4);out[4]=4;out[5]=33;out[6]=s->n;memcpy(out+8,s->incarnation.b,16);if(name){size_t n=strlen(name);if(n>16)n=16;memcpy(out+24,name,n);}if(s->n){uint32_t id=s->members[s->owner].id;out[40]=(uint8_t)(id>>24);out[41]=(uint8_t)(id>>16);out[42]=(uint8_t)(id>>8);out[43]=(uint8_t)id;}out[44]=(uint8_t)s->phase;}
