#include "../src/backfire.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
static unsigned char b[16384]; static size_t n;
static void u16(unsigned x){b[n++]=(unsigned char)x;b[n++]=(unsigned char)(x>>8);}
static void u32(unsigned x){u16(x);u16(x>>16);}
static void str(const char *s){size_t l=strlen(s);u16((unsigned)l);memcpy(b+n,s,l);n+=l;}
static void matrix(float x){ for(int i=0;i<16;i++){float f=i==0?x:(i%5==0?1:0);unsigned u;memcpy(&u,&f,4);u32(u);} }
static void mesh(unsigned group,unsigned geom,unsigned ordinal,const char *variant,const char *path,float x){u32(group);u32(geom);u32(ordinal);str(variant);str(path);for(int i=0;i<17;i++)matrix(x);}
static void nozzle(const char *car,const char *muffler,const char *slot,const char *path,float x){str(car);str(muffler);str(slot);str(path);matrix(x);}
static void header(unsigned meshes,unsigned nozzles){n=0;memcpy(b,"BFX1",4);n=4;u16(1);u16(0);u32(17);u32(meshes);u32(nozzles);}
static int parse(void){bfx_asset a={0};int r=bfx_parse(&a,b,n);bfx_free(&a);return r;}
static void single(const char *variant,const char *path,float x){header(1,0);mesh(1,2,3,variant,path,x);}
static void one_nozzle(const char *car,const char *muffler,const char *slot,const char *path,float x){header(1,1);mesh(1,2,3,"SAMLL_A",".",1);nozzle(car,muffler,slot,path,x);}
int main(void){
 const char *variants[]={"SAMLL_A","MIDDLE_A","LARGE_A","SMALL_B","MIDDLE_B","LARGE_B"};
 const char *slots[]={"MF_NULL_R1","MF_NULL_R2","MF_NULL_L1","MF_NULL_L2"};
 const char *badpaths[]={"", "00", "01/2", "65536", "/1", "1/", "1//2", "-1", "1/.", "1a", "99999999999999999999999"};
 const char *badcars[]={"|0","a|", "a|00", "a|120", "a|-1", "a|1x", "a|1|2", "a b|1", "a\\b|1", "a.|1"};
 for(size_t i=0;i<6;i++){single(variants[i],"0/65535",1);assert(parse()==0);}
 single("SMALL_A",".",1);assert(parse()<0);
 for(size_t i=0;i<sizeof badpaths/sizeof *badpaths;i++){single("SAMLL_A",badpaths[i],1);assert(parse()<0);one_nozzle("cars/test|0","MUFFLER1",slots[0],badpaths[i],1);assert(parse()<0);}
 for(size_t i=0;i<sizeof badcars/sizeof *badcars;i++){one_nozzle(badcars[i],"MUFFLER1",slots[0],".",1);assert(parse()<0);}
 for(int m=1;m<=2;m++)for(size_t i=0;i<4;i++){one_nozzle("cars/test:aero_a|119",m==1?"MUFFLER1":"MUFFLER2",slots[i],"1/2",1);assert(parse()==0);}
 one_nozzle("car|0","MUFFLER3",slots[0],".",1);assert(parse()<0);
 one_nozzle("car|0","MUFFLER1","MF_NULL_R3",".",1);assert(parse()<0);
 single("SAMLL_A",".",1e12f);assert(parse()==0);single("SAMLL_A",".",nextafterf(1e12f,INFINITY));assert(parse()<0);single("SAMLL_A",".",INFINITY);assert(parse()<0);single("SAMLL_A",".",NAN);assert(parse()<0);
 one_nozzle("car|0","MUFFLER1",slots[0],".",-nextafterf(1e12f,INFINITY));assert(parse()<0);
 header(2,0);mesh(1,2,3,"SAMLL_A",".",1);mesh(1,4,5,"LARGE_B","1",1);assert(parse()<0);
 header(2,0);mesh(1,2,3,"SAMLL_A",".",1);mesh(2,2,3,"LARGE_B",".",1);assert(parse()<0);
 header(1,2);mesh(1,2,3,"SAMLL_A",".",1);nozzle("car|0","MUFFLER1",slots[0],"1",1);nozzle("car|0","MUFFLER1",slots[0],"2",1);assert(parse()<0);
 header(1,2);mesh(1,2,3,"SAMLL_A",".",1);nozzle("car|0","MUFFLER1",slots[0],"1",1);nozzle("car|1","MUFFLER2",slots[1],"2",1);assert(parse()<0);
 header(0,0);assert(parse()<0);header(4097,0);assert(parse()<0);header(1,4097);assert(parse()<0);
 { char body[260]; memset(body,'x',253); body[253]=0; char car[260]; snprintf(car,sizeof car,"%s|0",body); one_nozzle(car,"MUFFLER1",slots[0],".",1); assert(parse()==0); body[253]='x';body[254]=0;snprintf(car,sizeof car,"%s|0",body);one_nozzle(car,"MUFFLER1",slots[0],".",1);assert(parse()<0); }
 { bfx_asset t={0}; assert(bfx_parse(&t,b,32u*1024u*1024u+1u)<0); }
 header(1,4);mesh(1,2,3,"SAMLL_A",".",1);nozzle("car1|37","MUFFLER1",slots[0],"1",1);nozzle("car1|37","MUFFLER1",slots[2],"2",1);nozzle("car2|1","MUFFLER1",slots[0],"3",1);nozzle("car1|37","MUFFLER2",slots[0],"4",1);
 for(size_t i=0;i<n;i++){bfx_asset t={0};assert(bfx_parse(&t,b,i)<0);bfx_free(&t);} bfx_asset a={0};assert(bfx_parse(&a,b,n)==0);
 bfx_playback *p=malloc(sizeof *p);assert(p);bfx_reset(p);assert(bfx_car_id("car1|37","car1")==37&&bfx_variant_b(37));assert(bfx_car_id("|1","")<0);
 bfx_step(p,&a,0,"car1",0,1,0);assert(p->frame[0][0]==0&&p->frame[0][1]==0&&p->frame[0][2]==-1);bfx_step(p,&a,1,"car2",0,1,1);assert(p->frame[1][2]==0);
 for(int i=1;i<17;i++){bfx_step(p,&a,0,"car1",0,1,1);assert(p->frame[0][0]==i&&p->type[0][0]==0);} bfx_step(p,&a,0,"car1",0,0,0);assert(p->frame[0][0]==-1);bfx_reset(p);assert(p->frame[1][2]==-1);
 bfx_step(p,&a,0,"car1",0,1,1);p->frame[0][1]=8;bfx_step(p,&a,0,"car1",0,1,0);assert(p->frame[0][0]==1&&p->frame[0][1]==9);bfx_step(p,&a,0,"other",0,0,0);assert(p->frame[0][0]==-1);
 bfx_step(p,&a,0,"car1",0,1,0); assert(p->frame[0][0]==0&&p->frame[0][3]==-1);
 bfx_step(p,&a,0,"car1",1,1,1); assert(p->frame[0][0]==-1&&p->frame[0][1]==-1&&p->frame[0][3]==0&&p->type[0][3]==1);
 bfx_step(p,&a,0,"car1",1,0,0); assert(p->frame[0][3]==1);
 bfx_step(p,&a,0,"car2",1,1,1); assert(p->frame[0][2]==-1&&p->frame[0][3]==-1); /* no tuned outlet on car2 */
 bfx_free(&a); free(p);b[n++]=0;assert(parse()<0);puts("BFX synthetic tests passed");return 0;
}
