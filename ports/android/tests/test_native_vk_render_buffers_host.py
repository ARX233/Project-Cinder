#!/usr/bin/env python3
"""Real renderer buffer producers against bounded recorders, never Vulkan pixels.
Native GL buffer/VAO/attribute names are poisoned. Compare successful pool and
selftest/tail bytes with the legacy producer; inject creation/update/file failure.
All generated files live on the APFS workspace; private inputs are not fabricated.
"""
from pathlib import Path
import os, re, subprocess, sys, tempfile
R = Path(__file__).resolve().parents[1]
O = Path(os.environ.get('TMPDIR', R.parent / 'tmp')).resolve()
assert O == Path('/Volumes/CodexWork') or str(O).startswith('/Volumes/CodexWork/')
S = (R / 'src/render.c').read_text()
def fun(anchor, source=S):
    a = source.index(anchor); b = source.index('{', a)
    mask = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', lambda m: ' '*len(m.group()), source, flags=re.S)
    depth = 0
    for i in range(b, len(source)):
        depth += (mask[i] == '{') - (mask[i] == '}')
        if not depth: return source[a:i+1]
    raise AssertionError(anchor)

def arms(anchor):
    first=fun(anchor); rest=S[S.index(first)+len(first):]
    if rest.startswith('\n#else\n') and rest[len('\n#else\n'):].startswith(anchor):
        return '#ifdef WMMT_NATIVE_VK\n'+first+'\n#else\n'+fun(anchor,rest)+'\n#endif\n'
    return first
POISON = '''
#pragma GCC poison glGenBuffers glBindBuffer glBufferData glBufferSubData glDeleteBuffers glGenVertexArraysOES glBindVertexArrayOES glDeleteVertexArraysOES glVertexAttribPointer glEnableVertexAttribArray glDisableVertexAttribArray glGetVertexAttribiv glGetVertexAttribPointerv
'''
PRE = r'''
#include <assert.h>
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>
#include "render.h"
#ifdef WMMT_NATIVE_VK
#include "native_vk.h"
#endif
typedef uint32_t GLuint; typedef int GLint, GLsizei; typedef unsigned GLenum;
typedef ptrdiff_t GLintptr, GLsizeiptr;
#define GL_ARRAY_BUFFER 1
#define GL_ELEMENT_ARRAY_BUFFER 2
#define GL_STATIC_DRAW 3
#define GL_TRIANGLES 4
#define GL_UNSIGNED_SHORT 5
#define GL_FALSE 0
#define GL_TRUE 1
struct buffer {unsigned char *data; size_t bytes; int live;};
static struct buffer buffers[512];
static unsigned next_id=1, creates, updates, destroys, vaos, fail_create, fail_update;
static GLuint array_bound, index_bound;
static wpk_scene *watched;
static uint32_t old_vfill,old_ifill,old_nfill,old_vbo,old_ibo,old_nbo;
static unsigned read_fail_nth,read_change_nth,read_hits;
static off_t read_target=-1;
static uint16_t read_bad_index;
static void watch(wpk_scene *s) {
 watched=s;wpk_pool *p=&s->pools[s->batches[s->next_batch].pool];
 old_vfill=p->vfill;old_ifill=p->ifill;old_nfill=p->nfill;
 old_vbo=p->vbo;old_ibo=p->ibo;old_nbo=p->nbo;
}
static void unpublished(void) {
#ifdef WMMT_NATIVE_VK
 if(watched){wpk_batch*b=&watched->batches[watched->next_batch];wpk_pool*p=&watched->pools[b->pool];
 assert(!b->count&&p->vfill==old_vfill&&p->ifill==old_ifill&&p->nfill==old_nfill);
 assert(p->vbo==old_vbo&&p->ibo==old_ibo&&p->nbo==old_nbo);}
#endif
}
static GLuint new_buffer(size_t n,const void*data) {
 unpublished();++creates;if(creates==fail_create)return 0;
 GLuint id=next_id++;assert(id<512);buffers[id]=(struct buffer){calloc(n?n:1,1),n,1};assert(buffers[id].data);
 if(data)memcpy(buffers[id].data,data,n);return id;
}
static int update_buffer(GLuint id,size_t off,size_t n,const void*data) {
 unpublished();++updates;assert(id&&id<512&&buffers[id].live&&off<=buffers[id].bytes&&n<=buffers[id].bytes-off&&(!n||data));
 if(updates==fail_update)return 0;memcpy(buffers[id].data+off,data,n);return 1;
}
static void destroy_buffer(GLuint id) {
 if(!id)return;assert(id<512&&buffers[id].live);++destroys;buffers[id].live=0;free(buffers[id].data);buffers[id].data=NULL;
}
#ifdef WMMT_NATIVE_VK
uint32_t cinder_vk_buffer_create(size_t n,const void*p){assert(n);return new_buffer(n,p);}
int cinder_vk_buffer_update(uint32_t id,size_t off,size_t n,const void*p){return update_buffer(id,off,n,p);}
void cinder_vk_buffer_destroy(uint32_t id){destroy_buffer(id);}
#else
static void glGenBuffers(int n,GLuint*p){for(int i=0;i<n;++i)p[i]=new_buffer(0,NULL);}
static void glBindBuffer(GLenum t,GLuint b){if(t==GL_ARRAY_BUFFER)array_bound=b;else {assert(t==GL_ELEMENT_ARRAY_BUFFER);index_bound=b;}}
static void glBufferData(GLenum t,GLsizeiptr n,const void*p,GLenum usage){(void)usage;GLuint id=t==GL_ARRAY_BUFFER?array_bound:index_bound;assert(id&&buffers[id].live&&n>=0);free(buffers[id].data);buffers[id].data=calloc(n?n:1,1);assert(buffers[id].data);buffers[id].bytes=n;if(p)memcpy(buffers[id].data,p,n);}
static void glBufferSubData(GLenum t,GLintptr off,GLsizeiptr n,const void*p){assert(update_buffer(t==GL_ARRAY_BUFFER?array_bound:index_bound,off,n,p));}
static void glDeleteBuffers(int n,const GLuint*p){for(int i=0;i<n;++i)destroy_buffer(p[i]);}
static void glDeleteVertexArraysOES(int n,const GLuint*p){for(int i=0;i<n;++i){assert(p[i]);++vaos;}}
#endif
static size_t cube_upload(wpk_scene*s,uint32_t i){(void)s;(void)i;return 1;}
static size_t tex_upload(wpk_scene*s,uint32_t i){(void)s;(void)i;return 1;}
static size_t ao_upload(wpk_scene*s){(void)s;return 1;}
static void ao_open(wpk_scene*s){(void)s;}
static GLuint texture_deletes[128];static unsigned texture_delete_count;
static unsigned char texture_owned[1024],texture_live[1024];static int texture_lifetime_check;
static void record_texture_destroy(GLuint id){if(!id)return;assert(texture_delete_count<128);texture_deletes[texture_delete_count++]=id;if(texture_lifetime_check){assert(id<1024&&texture_owned[id]&&texture_live[id]);texture_live[id]=0;}}
static void glDeleteTextures(int n,const GLuint*p){for(int i=0;i<n;++i)record_texture_destroy(p[i]);}
#ifdef WMMT_NATIVE_VK
void cinder_vk_texture_destroy(uint32_t id){record_texture_destroy(id);}
#endif
'''
HELPERS = S[S.index('typedef struct {\n  char magic[4];'):S.index('#ifndef WMMT_NATIVE_VK\nGLuint gl_compile_program(')]
REAL = fun('static int read_at(').replace('read_at(', 'raw_read_at(', 1) + r'''
static int read_at(int fd,void*dst,size_t n,off_t off) {
 if(off==read_target){++read_hits;if(read_hits==read_fail_nth)return -1;}
 int ok=raw_read_at(fd,dst,n,off);
 if(!ok&&off==read_target&&read_hits==read_change_nth&&n>=2)memcpy(dst,&read_bad_index,2);
 return ok;
}
''' + '\n'.join(fun(x) for x in ['static void *scratch(', 'static void file_close(', 'static int gloss_open(', 'static int road_texture(', 'int wpk_open(', 'int wpk_upload(', 'static void pool_free(', 'void wpk_free(', 'int wpk_free_step('])
BODY = r'''
struct spec {uint32_t nv,ni;int gloss;};
static unsigned char *vertices[8],*normals[8];static uint16_t *indices[8];
static wpk_batch_rec records[8];static uint32_t noffs[8];static struct spec specs[8];static int nbatch,stride;
static void make_scene(wpk_scene*s,int lit,const struct spec*bs,int n) {
 assert(n>0&&n<=8);for(int i=0;i<8;++i){free(vertices[i]);free(normals[i]);free(indices[i]);vertices[i]=normals[i]=NULL;indices[i]=NULL;}
 nbatch=n;stride=lit?32:24;int ng=0;for(int i=0;i<n;++i){specs[i]=bs[i];ng+=bs[i].gloss;}
 wpk_header h={.magic={'W','P','K',lit?'3':'2'},.n_tex=ng?1:0,.n_chunk=1,.n_batch=n,.chunk_size=20};
 h.tex_off=sizeof h;h.chunk_off=h.tex_off+h.n_tex*sizeof(wpk_tex);h.batch_off=h.chunk_off+36;
 size_t at=h.batch_off+n*(lit?28:20);
 for(int i=0;i<n;++i){const struct spec*q=bs+i;records[i]=(wpk_batch_rec){.tex=0xffff,.vtx_off=at,.vtx_count=q->nv,.idx_count=q->ni};at+=q->nv*stride;records[i].idx_off=at;at+=q->ni*2;noffs[i]=0;
 vertices[i]=calloc(q->nv?q->nv:1,stride);normals[i]=calloc(q->nv?q->nv:1,8);indices[i]=calloc(q->ni?q->ni:1,2);assert(vertices[i]&&normals[i]&&indices[i]);
 for(uint32_t k=0;k<q->nv;++k){float p[3]={(float)k,(float)i,(float)(k%7)};memcpy(vertices[i]+k*stride,p,12);for(int j=12;j<stride;++j)vertices[i][k*stride+j]=(unsigned char)(k*17+i*31+j);vertices[i][k*stride+23]=255;for(int j=0;j<8;++j)normals[i][k*8+j]=(unsigned char)(k*13+i*7+j);}
 for(uint32_t k=0;k<q->ni;++k)indices[i][k]=q->nv?(uint16_t)(k%q->nv):0;
 if(q->gloss){noffs[i]=at;at+=q->nv*8;}}
 uint32_t goff=at;size_t total=at+(ng?8+72+12*ng+8:0);unsigned char*file=calloc(total,1);assert(file);memcpy(file,&h,sizeof h);
 wpk_chunk ch={.first=0,.n=n,.hi={100,100,100}};memcpy(file+h.chunk_off,&ch,36);
 for(int i=0;i<n;++i){memcpy(file+h.batch_off+i*(lit?28:20),records+i,20);memcpy(file+records[i].vtx_off,vertices[i],bs[i].nv*stride);memcpy(file+records[i].idx_off,indices[i],bs[i].ni*2);if(bs[i].gloss)memcpy(file+noffs[i],normals[i],bs[i].nv*8);}
 if(ng){uint32_t counts[2]={1,(uint32_t)ng};memcpy(file+goff,counts,8);size_t g=goff+80;for(int i=0;i<n;++i)if(bs[i].gloss){uint32_t b=i;memcpy(file+g,&b,4);memcpy(file+g+8,&noffs[i],4);g+=12;}memcpy(file+g,&goff,4);memcpy(file+g+4,"GLS1",4);}
 int fd=open("fixture.wpk",O_CREAT|O_TRUNC|O_WRONLY,0600);assert(fd>=0&&write(fd,file,total)==(ssize_t)total);close(fd);free(file);
 read_target=-1;read_hits=read_fail_nth=read_change_nth=0;watched=NULL;
 assert(wpk_open(s,"fixture.wpk")==0);
}
static int upload_one(wpk_scene*s){uint32_t first=s->next_batch;watch(s);int done;do {done=wpk_upload(s,1);}while(!done&&s->next_batch==first);watched=NULL;return done;}
static void check(wpk_scene*s,unsigned rejected,int zero_normals) {
 uint32_t vf[8]={0},nf[8]={0},ix[8]={0};
 for(int i=0;i<nbatch;++i){wpk_batch*b=s->batches+i;wpk_pool*p=s->pools+b->pool;const struct spec*q=specs+i;unsigned pool=b->pool;assert(pool<8);
 if(rejected&(1u<<i)){assert(!b->count);continue;}
 assert(b->count==q->ni&&b->ioff==ix[pool]);
 if(q->nv){assert(p->vbo&&buffers[p->vbo].bytes==p->vbytes);assert(!memcmp(buffers[p->vbo].data+vf[pool],vertices[i],q->nv*stride));}
 for(uint32_t k=0;k<q->ni;++k){uint16_t actual;memcpy(&actual,buffers[p->ibo].data+ix[pool]+k*2,2);assert(actual==(uint16_t)(indices[i][k]+vf[pool]/stride));}
 if(q->gloss){assert(p->nbo&&buffers[p->nbo].bytes==p->nbytes);for(uint32_t k=0;k<q->nv*8;++k)assert(buffers[p->nbo].data[nf[pool]+k]==(zero_normals?0:normals[i][k]));nf[pool]+=q->nv*8;}
 vf[pool]+=q->nv*stride;ix[pool]+=q->ni*2;
 }
 for(unsigned i=0;i<s->n_pools;++i){assert(s->pools[i].vfill==vf[i]&&s->pools[i].ifill==ix[i]&&s->pools[i].nfill==nf[i]);assert(!s->pools[i].vao);}
}
static uint64_t hash(const unsigned char*p,size_t n){uint64_t h=1469598103934665603ull;for(size_t i=0;i<n;++i)h=(h^p[i])*1099511628211ull;return h;}
static void golden(const char*name,wpk_scene*s) {
 printf("%s",name);for(unsigned i=0;i<s->n_pools;++i){wpk_pool*p=s->pools+i;uint32_t ids[3]={p->vbo,p->ibo,p->nbo};for(int j=0;j<3;++j){size_t n=ids[j]?buffers[ids[j]].bytes:0;printf(" %zu:%016llx",n,(unsigned long long)hash(ids[j]?buffers[ids[j]].data:NULL,n));}}putchar('\n');
}
static void no_leaks(void){for(unsigned i=1;i<next_id;++i)assert(!buffers[i].live);}
static void success(void) {
 wpk_scene s;
 make_scene(&s,0,(struct spec[]){{3,6,0},{2,32769,0},{4,6,0}},3);assert(!upload_one(&s));assert(s.batches[0].count==6&&!s.batches[1].count);while(!upload_one(&s)){}check(&s,0,0);golden("unlit-chunks",&s);wpk_free(&s);no_leaks();
 make_scene(&s,1,(struct spec[]){{2,6,0},{3,3,0}},2);while(!upload_one(&s)){}check(&s,0,0);golden("lit32",&s);wpk_free(&s);no_leaks();
 make_scene(&s,0,(struct spec[]){{1,3,0},{3,32769,1},{2,6,1},{1,3,0}},4);assert(s.n_pools==3);while(!upload_one(&s)){}check(&s,0,0);golden("gloss-split",&s);
 unsigned old=destroys;assert(!wpk_free_step(&s,1)&&s.n_pools==2&&destroys==old+2);assert(!wpk_free_step(&s,0)&&destroys==old+2);while(!wpk_free_step(&s,1)){}assert(s.fd==-1&&!s.pools);no_leaks();
 make_scene(&s,0,(struct spec[]){{65533,3,0},{3,3,0},{1,3,0}},3);assert(s.n_pools==2);while(!upload_one(&s)){}check(&s,0,0);golden("uint16-limit",&s);wpk_free(&s);no_leaks();
 make_scene(&s,0,(struct spec[]){{3,3,1}},1);s.gloss_noff[0]=UINT32_MAX;while(!upload_one(&s)){}check(&s,0,1);golden("missing-normal-zero",&s);wpk_free(&s);no_leaks();
 make_scene(&s,0,(struct spec[]){{0,0,0}},1);while(!upload_one(&s)){}assert(!s.batches[0].count&&!s.pools[0].vfill&&!s.pools[0].ifill);wpk_free(&s);no_leaks();
}
#ifdef WMMT_NATIVE_VK
static void failures(void) {
 wpk_scene s;
 for(unsigned fail=1;fail<=3;++fail){make_scene(&s,0,(struct spec[]){{3,32769,1}},1);fail_create=creates+fail;while(!upload_one(&s)){}assert(!s.batches[0].count&&!s.pools[0].vbo&&!s.pools[0].ibo&&!s.pools[0].nbo&&!s.pools[0].vfill&&!s.pools[0].ifill&&!s.pools[0].nfill);fail_create=0;wpk_free(&s);no_leaks();}
 for(unsigned fail=1;fail<=4;++fail){make_scene(&s,0,(struct spec[]){{3,32769,1}},1);fail_update=updates+fail;while(!upload_one(&s)){}assert(!s.batches[0].count&&!s.pools[0].vbo&&!s.pools[0].ibo&&!s.pools[0].nbo&&!s.pools[0].vfill&&!s.pools[0].ifill&&!s.pools[0].nfill);fail_update=0;wpk_free(&s);no_leaks();}
 /* Failed append after a committed draw must neither delete nor overwrite it. */
 for(unsigned fail=1;fail<=4;++fail){make_scene(&s,0,(struct spec[]){{3,3,1},{2,32769,1},{4,6,1}},3);assert(!upload_one(&s));wpk_pool before=s.pools[0];unsigned old=destroys;s.batches[1].ioff=777;fail_update=updates+fail;assert(!upload_one(&s));assert(s.batches[1].ioff==777&&!s.batches[1].count&&!memcmp(&before,s.pools,sizeof before)&&destroys==old);fail_update=0;assert(upload_one(&s));check(&s,2,0);wpk_free(&s);no_leaks();}
 /* Bounded second index chunk can fail or change between scan and write. */
 for(int change=0;change<2;++change){make_scene(&s,0,(struct spec[]){{3,32769,1}},1);read_target=records[0].idx_off+65536;read_bad_index=3;if(change)read_change_nth=2;else read_fail_nth=2;while(!upload_one(&s)){}assert(!s.batches[0].count&&!s.pools[0].vbo&&!s.pools[0].vfill&&!s.pools[0].ifill&&!s.pools[0].nfill);wpk_free(&s);no_leaks();}
 make_scene(&s,0,(struct spec[]){{3,3,0}},1);unsigned old=creates;assert(ftruncate(s.fd,0)==-1);int fd=open("fixture.wpk",O_WRONLY);assert(fd>=0&&ftruncate(fd,1)==0);close(fd);while(!upload_one(&s)){}assert(creates==old&&!s.batches[0].count);wpk_free(&s);no_leaks();
 make_scene(&s,0,(struct spec[]){{3,3,0}},1);old=creates;read_target=records[0].idx_off;read_change_nth=1;read_bad_index=3;while(!upload_one(&s)){}assert(creates==old&&!s.batches[0].count);wpk_free(&s);no_leaks();
 make_scene(&s,0,(struct spec[]){{3,3,0}},1);old=creates;s.pools[0].ibytes=1;while(!upload_one(&s)){}assert(creates==old&&!s.batches[0].count&&!s.pools[0].vfill);wpk_free(&s);no_leaks();
 wpk_pool p={.vao=999};pool_free(&p);assert(!p.vao&&!vaos);
}
#endif
int main(void){success();
#ifdef WMMT_NATIVE_VK
 failures();
#endif
 for(int i=0;i<8;++i){free(vertices[i]);free(normals[i]);free(indices[i]);}
 no_leaks();return 0;}
'''

LIFETIME_REAL = '\n'.join(fun(x) for x in ['int wpk_has_paint(', 'void wpk_paint(', 'void wpk_free_paints(', 'void wpk_share_sync('])
LIFETIME_BODY = r'''
static void no_leaks(void){for(unsigned i=1;i<next_id;++i)assert(!buffers[i].live);}
static wpk_scene stock;
static uint32_t stock_textures[3]={901,902,7};
static void lifetime_scene(wpk_scene*s){
 memset(s,0,sizeof *s);s->fd=-1;s->n_tex=7;s->n_cube=2;s->n_ao=2;s->n_pools=2;s->n_paints=2;
 s->loaded=calloc(s->n_tex,sizeof *s->loaded);s->textures=calloc(s->n_tex,sizeof *s->textures);s->tex_warm=calloc(s->n_tex,1);s->share_idx=malloc(s->n_tex*sizeof *s->share_idx);s->paints=calloc(s->n_paints,sizeof *s->paints);s->cubes=calloc(s->n_cube,sizeof *s->cubes);s->ao_tex=calloc(s->n_ao,sizeof *s->ao_tex);s->pools=calloc(s->n_pools,sizeof *s->pools);
 assert(s->loaded&&s->textures&&s->tex_warm&&s->share_idx&&s->paints&&s->cubes&&s->ao_tex&&s->pools);
 memcpy(s->loaded,(uint32_t[7]){11,0,12,13,16,0,0},7*sizeof *s->loaded);memcpy(s->textures,s->loaded,7*sizeof *s->textures);memset(s->tex_warm,1,7);
 for(unsigned i=0;i<s->n_tex;++i)s->share_idx[i]=0xffff;
 s->share_idx[1]=0;s->share_idx[5]=1;s->share_idx[6]=2;stock=(wpk_scene){.n_tex=3,.textures=stock_textures};s->share=&stock;wpk_share_sync(s);
 assert(s->textures[1]==901&&s->textures[5]==902&&s->textures[6]==7);
 s->paints[0]=(wpk_paint_swap){.src=2,.dst=0,.k=1};s->paints[1]=(wpk_paint_swap){.src=3,.dst=4,.k=1};
 s->cubes[0]=14;s->ao_tex[1]=15;
 for(unsigned i=0;i<s->n_pools;++i){s->pools[i].vbo=new_buffer(24,NULL);s->pools[i].ibo=new_buffer(6,NULL);s->pools[i].nbo=new_buffer(8,NULL);}
 texture_delete_count=0;texture_lifetime_check=1;memset(texture_owned,0,sizeof texture_owned);memset(texture_live,0,sizeof texture_live);
 for(unsigned i=11;i<=16;++i)texture_owned[i]=texture_live[i]=1;
 texture_live[901]=texture_live[902]=texture_live[7]=1;
}
static void lifetime_expect(const char*name,const GLuint*ids,unsigned n){
 assert(texture_delete_count==n&&!memcmp(texture_deletes,ids,n*sizeof *ids));assert(texture_live[901]&&texture_live[902]&&texture_live[7]);
 for(unsigned i=11;i<=16;++i)assert(!texture_live[i]);
 assert(stock.textures==stock_textures&&!memcmp(stock_textures,(uint32_t[3]){901,902,7},sizeof stock_textures));
 printf("%s",name);for(unsigned i=0;i<n;++i)printf(" %u",texture_deletes[i]);putchar('\n');no_leaks();texture_lifetime_check=0;
}
int main(void){wpk_scene s;
 /* Full free destroys loaded ownership, never the two stock aliases/white. */
 lifetime_scene(&s);wpk_paint(&s,1);assert(s.textures[0]==12&&s.textures[4]==13);unsigned old=destroys;wpk_free(&s);assert(destroys==old+6&&!s.loaded&&!s.pools&&!s.n_tex&&s.fd==-1);lifetime_expect("free-loaded-cube-AO",(GLuint[]){11,12,13,16,14,15},6);wpk_free(&s);assert(texture_delete_count==6);
 /* Paint eviction resets displayed bases before deleting only paint sources. */
 lifetime_scene(&s);wpk_paint(&s,1);wpk_free_paints(&s);assert(texture_delete_count==2&&texture_deletes[0]==12&&texture_deletes[1]==13&&s.textures[0]==11&&s.textures[4]==16&&!s.loaded[2]&&!s.loaded[3]&&!s.textures[2]&&!s.textures[3]&&!s.tex_warm[2]&&!s.tex_warm[3]);assert(texture_live[11]&&texture_live[16]&&texture_live[14]&&texture_live[15]);wpk_free_paints(&s);assert(texture_delete_count==2);wpk_share_sync(&s);assert(s.textures[1]==901&&s.textures[5]==902&&s.textures[6]==7);wpk_free(&s);lifetime_expect("free-paints-once",(GLuint[]){12,13,11,16,14,15},6);
 /* Trimming spends budget on pools, zero/borrowed slots and actual owners;
  * remaining cube/AO resources are released once by the final full free. */
 lifetime_scene(&s);old=destroys;assert(!wpk_free_step(&s,0)&&s.n_pools==2&&s.n_tex==7&&!texture_delete_count&&destroys==old);assert(!wpk_free_step(&s,1)&&s.n_pools==1&&destroys==old+3&&!texture_delete_count);assert(!wpk_free_step(&s,1)&&!s.n_pools&&s.n_tex==7&&destroys==old+6&&!texture_delete_count);assert(!wpk_free_step(&s,1)&&s.n_tex==6&&!texture_delete_count);assert(!wpk_free_step(&s,2)&&s.n_tex==4&&texture_delete_count==1&&texture_deletes[0]==16);assert(!wpk_free_step(&s,1)&&s.n_tex==3&&texture_delete_count==2&&texture_deletes[1]==13);assert(wpk_free_step(&s,100)&&s.fd==-1&&!s.loaded&&!s.pools);lifetime_expect("trim-budgeted-own-only",(GLuint[]){16,13,12,11,14,15},6);assert(wpk_free_step(&s,1)&&texture_delete_count==6);return 0;}
'''

SELF_PRE = r'''
#define GL_RENDERBUFFER 10
#define GL_RGB565 11
#define GL_FRAMEBUFFER 12
#define GL_COLOR_ATTACHMENT0 13
#define GL_EXTENSIONS 14
#define GL_TEXTURE_2D 15
#define GL_COMPRESSED_RGB_PVRTC_4BPPV1_IMG 16
#define GL_TEXTURE_MIN_FILTER 17
#define GL_TEXTURE_MAG_FILTER 18
#define GL_LINEAR 19
#define GL_FRAMEBUFFER_BINDING 20
#define GL_VIEWPORT 21
#define GL_FLOAT 22
#define GL_UNSIGNED_BYTE 23
static uint32_t white_tex=7,native_loader_program=8;
typedef struct {uint32_t target;int w,h;} native_scene_view;
static native_scene_view native_scene;
static unsigned calls,buffer_draws;
static void dump_draw(GLuint vbo,GLuint ibo) {
 assert(vbo&&buffers[vbo].live);++buffer_draws;
 uint64_t h=1469598103934665603ull;
 for(size_t i=0;i<buffers[vbo].bytes;++i)h=(h^buffers[vbo].data[i])*1099511628211ull;
 printf("draw %zu:%016llx",buffers[vbo].bytes,(unsigned long long)h);
 if(ibo){assert(buffers[ibo].live);h=1469598103934665603ull;for(size_t i=0;i<buffers[ibo].bytes;++i)h=(h^buffers[ibo].data[i])*1099511628211ull;printf(" %zu:%016llx",buffers[ibo].bytes,(unsigned long long)h);}putchar('\n');
}
static int native_loader_triangle(uint32_t p,uint32_t tex,native_scene_view v,uint32_t vb,uint32_t ib,int warm){assert(p==8&&tex&&v.w==1&&v.h==1&&!warm);dump_draw(vb,ib);return 1;}
static void glFinish(void){++calls;}
void render_warm_begin(void){}
static void glGenRenderbuffers(int n,GLuint*p){assert(n==1);*p=1;}
static void glBindRenderbuffer(GLenum a,GLuint b){(void)a;(void)b;}
static void glRenderbufferStorage(GLenum a,GLenum b,int w,int h){(void)a;(void)b;assert(w==1&&h==1);}
static void glGenFramebuffers(int n,GLuint*p){assert(n==1);*p=1;}
static void glBindFramebuffer(GLenum a,GLuint b){(void)a;(void)b;}
static void glFramebufferRenderbuffer(GLenum a,GLenum b,GLenum c,GLuint d){(void)a;(void)b;(void)c;(void)d;}
static void glDeleteFramebuffers(int n,const GLuint*p){(void)n;(void)p;}
static void glDeleteRenderbuffers(int n,const GLuint*p){(void)n;(void)p;}
static GLuint st_texture(int size,int mips,double*api,double*cpu){assert(size==256||size==512);assert(mips>=0&&mips<=2);*api=*cpu=0;return 7;}
static const unsigned char*glGetString(GLenum e){assert(e==GL_EXTENSIONS);return (const unsigned char*)"";}
static void glGenTextures(int n,GLuint*p){assert(n==1);*p=7;}
static void glBindTexture(GLenum a,GLuint b){(void)a;(void)b;}
static void glCompressedTexImage2D(GLenum a,int b,GLenum c,int d,int e,int f,GLsizei n,const void*p){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)n;(void)p;}
static void glTexParameteri(GLenum a,GLenum b,int c){(void)a;(void)b;(void)c;}
static int mip_filter(void){return GL_LINEAR;}
static void tex_aniso(void){}
static GLenum glGetError(void){return 0;}
#ifndef WMMT_NATIVE_VK
static void glGetIntegerv(GLenum e,GLint*p){for(int i=0;i<(e==GL_VIEWPORT?4:1);++i)p[i]=0;}
static void glViewport(int a,int b,int c,int d){(void)a;(void)b;(void)c;(void)d;}
static void glBindVertexArrayOES(GLuint b){(void)b;}
static void glDisableVertexAttribArray(GLuint a){(void)a;}
static void glVertexAttribPointer(GLuint a,int b,GLenum c,int d,int e,const void*f){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;}
static void glDrawArrays(GLenum mode,int first,int n){assert(mode==GL_TRIANGLES&&!first&&n==3);dump_draw(array_bound,0);}
static void glDrawElements(GLenum mode,int n,GLenum type,const void*off){assert(mode==GL_TRIANGLES&&n==3&&type==GL_UNSIGNED_SHORT&&!off);dump_draw(array_bound,index_bound);}
#endif
'''
# Resource boundary for this byte test; target ownership/faults are tested separately.
SELF_PRE += r'''
#ifdef WMMT_NATIVE_VK
int cinder_vk_finish(void){++calls;return 1;}
int cinder_vk_program_ready(uint32_t p){return p==8;}
uint32_t cinder_vk_attachment_create(const cinder_vk_storage_desc*d){assert(d&&d->width==1&&d->height==1&&d->format==CINDER_VK_STORAGE_RGB565);return 1;}
uint32_t cinder_vk_target_create(const cinder_vk_target_create_desc*d){assert(d&&d->color.kind==CINDER_VK_IMAGE_ATTACHMENT&&d->color.id==1&&!d->depth_stencil.id);return 1;}
int cinder_vk_target_ready(uint32_t t){return t==1;}
int cinder_vk_target_info(uint32_t t,cinder_vk_target_desc*out){assert(t==1);*out=(cinder_vk_target_desc){.width=1,.height=1,.color_format=VK_FORMAT_R5G6B5_UNORM_PACK16,.samples=VK_SAMPLE_COUNT_1_BIT};return 1;}
void cinder_vk_target_destroy(uint32_t t){assert(t==1);}
void cinder_vk_attachment_destroy(uint32_t t){assert(t==1);}
#endif
'''
TARGETS=(R/'src/render_native_targets.inc').read_text()
SELF_REAL = '#ifdef WMMT_NATIVE_VK\n'+fun('static GLuint native_target_attachment(',TARGETS)+'\n'+fun('static GLuint native_target_compose(',TARGETS)+'\n#endif\n'
SELF_REAL += '\n'.join(arms(x) for x in ['static double st_ms(', 'static double st_draw(', 'void render_selftest('])
SELF_BODY = r'''
int main(void){char out[4096];render_selftest(out,sizeof out);assert(buffer_draws==15&&strstr(out,"batch 4000 verts")&&strstr(out,"512 nomip"));for(unsigned i=1;i<next_id;++i)assert(!buffers[i].live);
#ifdef WMMT_NATIVE_VK
 /* A zero direct handle must never become the loader's client-memory fallback. */
 for(unsigned i=1;i<=3;++i){unsigned old=buffer_draws;fail_create=creates+i;render_selftest(out,sizeof out);assert(buffer_draws==old+(i==1?2:13));for(unsigned k=1;k<next_id;++k)assert(!buffers[k].live);fail_create=0;}
#endif
 return 0;}
'''

TAIL_PRE = r'''
#define WMMT_VK 1
#include "native_vk.h"
typedef unsigned char GLboolean;
#define GL_TEXTURE0 100
#define GL_TEXTURE_2D 10
#define GL_DEPTH_TEST 11
#define GL_LEQUAL 12
#define GL_CULL_FACE 13
#define GL_STENCIL_TEST 14
#define GL_BLEND 15
#define GL_FUNC_ADD 16
#define GL_SRC_ALPHA 17
#define GL_ONE 18
#define GL_STREAM_DRAW 19
#define GL_FLOAT 20
typedef struct {GLuint id;GLint mvp,eye,fog,fog_color,tex,uv_off,grade,wet,horizon;} scene_prog;
static scene_prog progs[2]={{.id=1}};static GLuint white_tex=7;static const char *FS="FS";
typedef struct {uint32_t target;int w,h;} native_scene_view;
static native_scene_view native_scene={0,64,48};
static unsigned program_creates,draws,fail_submit;
static const TailTrailVertex *expected;static size_t expected_n;
static int prog_init(scene_prog*p,const char*f){assert(f==FS);++program_creates;*p=(scene_prog){.id=9};return 0;}
#ifdef WMMT_NATIVE_VK
int cinder_vk_program_ready(uint32_t p){return p==9;}
void cinder_vk_program_destroy(uint32_t p){assert(p==9);}
#else
static int vkgl_program_usable(GLuint p){assert(p==9);return 1;}
static void glDeleteProgram(GLuint p){assert(p==9);}
#endif
static void dump_tail(const void*data,size_t n,size_t stride) {
 assert(stride==36&&n==expected_n*stride);uint64_t h=1469598103934665603ull;
 const unsigned char*p=data;for(size_t i=0;i<n;++i)h=(h^p[i])*1099511628211ull;
 for(size_t i=0;i<expected_n;++i){float v[9];memcpy(v,p+i*stride,sizeof v);assert(v[0]==expected[i].position.x&&v[1]==expected[i].position.y&&v[2]==expected[i].position.z&&v[3]==0&&v[4]==0&&!memcmp(v+5,expected[i].rgba,16));}
 printf("tail %zu:%016llx\n",n,(unsigned long long)h);++draws;
}
#ifdef WMMT_NATIVE_VK
int cinder_vk_draw_init(cinder_vk_draw*d,uint32_t p,uint32_t t,int w,int h){assert(p==1&&w==64&&h==48);memset(d,0,sizeof *d);d->program=p;d->target=t;return 1;}
int cinder_vk_uniform(cinder_vk_draw*d,const char*n,const void*p,size_t b){(void)d;assert(n&&p&&b);return 1;}
int cinder_vk_texture(cinder_vk_draw*d,const char*n,uint32_t t){(void)d;assert(n&&t==white_tex);return 1;}
void cinder_vk_screen_extent(int*w,int*h){*w=64;*h=48;}
int cinder_vk_submit(const cinder_vk_draw*d){assert(!d->attributes[0].buffer&&!d->attributes[1].buffer&&!d->attributes[2].buffer&&d->attributes[2].format==VK_FORMAT_R32G32B32A32_SFLOAT);if(fail_submit)return 0;dump_tail(d->attributes[0].data,d->attributes[0].bytes,d->attributes[0].stride);return 1;}
#else
static uint64_t vkgl_error_epoch(void){return 0;}
static void *vkgl_preview_save(GLuint p){assert(p==1);return (void*)1;}
static void vkgl_scope_restore_preserve_error(void*p){assert(p==(void*)1);}
static void glGenVertexArraysOES(int n,GLuint*p){assert(n==1);*p=1;}
static void glBindVertexArrayOES(GLuint p){(void)p;}
static void glUseProgram(GLuint p){(void)p;}
static void glUniformMatrix4fv(GLint l,int n,int t,const float*p){(void)l;(void)n;(void)t;(void)p;}
static void glUniform1i(GLint l,int a){(void)l;(void)a;}
static void glUniform1f(GLint l,float a){(void)l;(void)a;}
static void glUniform2f(GLint l,float a,float b){(void)l;(void)a;(void)b;}
static void glUniform3f(GLint l,float a,float b,float c){(void)l;(void)a;(void)b;(void)c;}
static void glActiveTexture(GLenum e){(void)e;}
static void glBindTexture(GLenum e,GLuint t){(void)e;(void)t;}
static void glEnable(GLenum e){(void)e;}
static void glDisable(GLenum e){(void)e;}
static void glDepthMask(int b){(void)b;}
static void glDepthFunc(GLenum e){(void)e;}
static void glColorMask(int a,int b,int c,int d){(void)a;(void)b;(void)c;(void)d;}
static void glBlendEquation(GLenum e){(void)e;}
static void glBlendFunc(GLenum a,GLenum b){(void)a;(void)b;}
static void glEnableVertexAttribArray(GLuint a){(void)a;}
static void glVertexAttribPointer(GLuint a,int b,GLenum c,int d,int e,const void*f){(void)a;(void)b;(void)c;(void)d;(void)e;(void)f;}
static void glDrawArrays(GLenum mode,int first,int n){assert(mode==GL_TRIANGLES&&!first&&n==(int)expected_n);dump_tail(buffers[array_bound].data,buffers[array_bound].bytes,36);}
#endif
'''
TAIL_REAL = '#ifdef WMMT_NATIVE_VK\n'+fun('static void native_program_release(')+'\n#endif\n'
TAIL_REAL += (R/'src/render_native_effects.inc').read_text().split('static int native_effect_quads(')[0]+'\n#endif\n'
a = S.index('/* ---- isolated, float-colour tail trail drawing ---- */')
b = S.index('#ifdef __ANDROID__\n/* clTireTrack::draw:', a)
TAIL_REAL += S[a:b]
TAIL_BODY = r'''
int main(void){TailTrailVertex v[2*TAIL_TRAIL_MAX_VERTICES];mat4 vp=mat4_identity();render_params rp={0};
 for(unsigned i=0;i<2*TAIL_TRAIL_MAX_VERTICES;++i){v[i].position=(TailTrailVec3){(float)i*.5f,(float)(i%13),-(float)i};for(int j=0;j<4;++j)v[i].rgba[j]=(float)((i+j)%31)/31;}
 expected=v;expected_n=3;assert(render_tail_triangles(&vp,v,expected_n,&rp));expected_n=6;assert(render_tail_triangles(&vp,v,expected_n,&rp));expected_n=2*TAIL_TRAIL_MAX_VERTICES;assert(render_tail_triangles(&vp,v,expected_n,&rp));assert(draws==3&&rp.draws==3);
#ifdef WMMT_NATIVE_VK
 assert(!creates&&!updates&&!destroys&&!program_creates&&!tail_render.vao&&!tail_render.vbo);
 /* Native readiness needs shader metadata, never a useless VAO/VBO pair. */
 assert(tail_render_prepare()&&program_creates==1&&!creates);assert(tail_render_prepare()&&program_creates==1&&!creates);
 fail_submit=1;assert(!render_tail_triangles(&vp,v,expected_n,&rp)&&tail_render.failed&&rp.draws==3);
#endif
 render_tail_release();for(unsigned i=1;i<next_id;++i)assert(!buffers[i].live);return 0;}
'''

def compile_run(directory, label, text, native):
    c = directory / (label+'.c'); exe = directory / label; c.write_text(text)
    cmd = [os.environ.get('CC','clang'), '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wno-unused-variable', '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I', str(R/'src')]
    if native: cmd += ['-DWMMT_NATIVE_VK', '-DWMMT_VK']
    if sys.platform == 'darwin': cmd += ['-I','/opt/homebrew/include']
    subprocess.run(cmd+[str(c),'-lm','-o',str(exe)], check=True, timeout=120)
    return subprocess.check_output([str(exe)], cwd=directory, text=True, timeout=60)

with tempfile.TemporaryDirectory(prefix='native-vk-render-buffers-', dir=O) as td:
    td = Path(td)
    legacy = compile_run(td, 'legacy', PRE+HELPERS+REAL+BODY, False)
    native = compile_run(td, 'native', PRE+POISON+HELPERS+REAL+BODY, True)
    assert native == legacy, (legacy, native)
    print(native, end='')
    legacy = compile_run(td, 'lifetime-legacy', PRE+HELPERS+REAL+LIFETIME_REAL+LIFETIME_BODY, False)
    native = compile_run(td, 'lifetime-native', PRE+POISON+HELPERS+REAL+LIFETIME_REAL+LIFETIME_BODY, True)
    assert native == legacy and len(native.splitlines()) == 3
    print(native, end='')
    print('actual free/paint eviction/budgeted trim: exact legacy/direct native deleted IDs; no white/borrowed deletion: PASS')
    legacy = compile_run(td, 'self-legacy', PRE+SELF_PRE+SELF_REAL+SELF_BODY, False)
    native = compile_run(td, 'self-native', PRE+POISON+SELF_PRE+SELF_REAL+SELF_BODY, True)
    assert native.splitlines()[:15] == legacy.splitlines() and len(legacy.splitlines()) == 15
    print('selftest exact triangle/stress buffer bytes + direct creation failures: PASS')
    legacy = compile_run(td, 'tail-legacy', PRE+TAIL_PRE+TAIL_REAL+TAIL_BODY, False)
    native = compile_run(td, 'tail-native', PRE+POISON+TAIL_PRE+TAIL_REAL+TAIL_BODY, True)
    assert native == legacy and len(native.splitlines()) == 3
    print('tail exact legacy float bytes at 3/6/max vertices, no native buffer/VAO allocation: PASS')
print('native renderer buffers: exact legacy capacities/bytes, WPK chunk/normal/rebase/rollover, transactional failures and trim: PASS (UBSan CPU recorders)')
