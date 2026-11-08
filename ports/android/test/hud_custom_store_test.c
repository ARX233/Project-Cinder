#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
static int fail_rename;
static int wrapped_rename(const char *a,const char *b) {
    if(fail_rename) { errno=EACCES; return -1; } return rename(a,b);
}
#define rename wrapped_rename
#include "../src/hud_custom_store.h"
#undef rename
static void put(const char *p,const char *s) { FILE *f=fopen(p,"wb"); assert(f); assert(fwrite(s,1,strlen(s),f)==strlen(s)); assert(!fclose(f)); }
static void get(const char *p,char *b,size_t size) { FILE *f=fopen(p,"rb"); size_t n; assert(f); n=fread(b,1,size-1,f); b[n]=0; assert(!fclose(f)); }
int main(int argc, char **argv) {
    char path[4096]; const char *p=path; int fd;
    char buf[2048], before[2048]; HudCustomLayout a,b; HudCustomResult r;
    if (argc != 2 || snprintf(path, sizeof path, "%s/hud-custom-test.XXXXXX", argv[1]) >= (int)sizeof path) { fprintf(stderr, "usage: %s TEST_OUTPUT_DIRECTORY\n", argv[0]); return 2; }
    fd=mkstemp(path); assert(fd>=0); assert(close(fd)==0); assert(unlink(path)==0);
    hud_custom_default(&a); assert(a.stick_deadzone_percent==8 && !a.shift_separate && a.map.k==100 && !a.map.dx);
    assert(hud_custom_load(p,&b)==HUD_CUSTOM_MISSING && b.stick_deadzone_percent==8);
    assert(hud_custom_save(p,&a,0)==HUD_CUSTOM_EDIT_REQUIRED); assert(access(p,F_OK));
    a.shift_separate=1; a.shift.k=60; a.shift.dx=-2000; a.shift.dy=2000; a.map.k=160; a.map.dy=-123;
    assert(hud_custom_validate(&a)); assert(hud_custom_save(p,&a,1)==HUD_CUSTOM_OK);
    assert(hud_custom_load(p,&b)==HUD_CUSTOM_OK && b.shift.dx==-2000 && b.map.dy==-123 && b.shift_separate==1);
    put(p,"HUD_CUSTOM 1\ndeadzone=9\nshift_separate=1\nshift=120,20,30\nmap=100,0,0\nrank=100,0,0\ntimer=100,0,0\nmeter=100,0,0\n");
    assert(hud_custom_load(p,&b)==HUD_CUSTOM_OK && b.shift_separate==1 && b.shift.dx==20);
    assert(b.separate_buttons==0 && b.button_opacity_percent==100 && b.button[0].k==100);
    a.button_opacity_percent=30; a.separate_buttons=9;
    a.button[0]=(HudCustomTransform){90,52,-8}; a.button[3]=(HudCustomTransform){140,200,100};
    assert(hud_custom_save(p,&a,1)==HUD_CUSTOM_OK && hud_custom_load(p,&b)==HUD_CUSTOM_OK);
    assert(b.button_opacity_percent==30 && b.separate_buttons==9 && b.button[0].dx==52 &&
           b.button[3].k==140 && b.button[3].dy==100 && b.shift_separate==1);
    get(p,before,sizeof before); fail_rename=1; a.map.dy=500; assert(hud_custom_save(p,&a,1)==HUD_CUSTOM_IO_ERROR); fail_rename=0;
    get(p,buf,sizeof buf); assert(!strcmp(buf,before));
    put(p,"HUD_CUSTOM 3\nnew-format\n"); assert(hud_custom_load(p,&b)==HUD_CUSTOM_UNSUPPORTED);
    assert(hud_custom_save(p,&a,1)==HUD_CUSTOM_UNSUPPORTED); get(p,buf,sizeof buf); assert(!strcmp(buf,"HUD_CUSTOM 3\nnew-format\n"));
    put(p,"HUD_CUSTOM 9999999999999999999999999999999999999999999\nfuture\n"); assert(hud_custom_load(p,&b)==HUD_CUSTOM_UNSUPPORTED); assert(hud_custom_save(p,&a,1)==HUD_CUSTOM_UNSUPPORTED); get(p,buf,sizeof buf); assert(!strcmp(buf,"HUD_CUSTOM 9999999999999999999999999999999999999999999\nfuture\n"));
    put(p,"HUD_CUSTOM 99999999999999999999x\n"); assert(hud_custom_load(p,&b)==HUD_CUSTOM_CORRUPT);
    put(p,"garbage"); assert(hud_custom_load(p,&b)==HUD_CUSTOM_CORRUPT); assert(hud_custom_save(p,&a,0)==HUD_CUSTOM_EDIT_REQUIRED); get(p,buf,sizeof buf); assert(!strcmp(buf,"garbage"));
    assert(hud_custom_save(p,&a,1)==HUD_CUSTOM_OK);
    put(p,"HUD_CUSTOM 1\ndeadzone=-1\n"); assert(hud_custom_load(p,&b)==HUD_CUSTOM_CORRUPT);
    put(p,"HUD_CUSTOM 1\ndeadzone=8\nshift_separate=0\nshift=100,0,0\nmap=100,0,0\nrank=100,0,0\ntimer=100,0,0\nmeter=100,0,"); assert(hud_custom_load(p,&b)==HUD_CUSTOM_CORRUPT);
    memset(buf,'x',sizeof buf-1); buf[sizeof buf-1]=0; put(p,buf); assert(hud_custom_load(p,&b)==HUD_CUSTOM_UNSUPPORTED); assert(hud_custom_save(p,&a,1)==HUD_CUSTOM_UNSUPPORTED); get(p,before,sizeof before); assert(!strcmp(buf,before));
    memcpy(buf,"HUD_CUSTOM 3\n",13); put(p,buf); assert(hud_custom_load(p,&b)==HUD_CUSTOM_UNSUPPORTED); assert(hud_custom_save(p,&a,1)==HUD_CUSTOM_UNSUPPORTED); get(p,before,sizeof before); assert(!strcmp(buf,before));
    { const unsigned char bytes[] = {'H','U','D','_','C','U','S','T','O','M',' ','3','\n',0,255,1}; unsigned char got[sizeof bytes]; FILE *f=fopen(p,"wb"); assert(f); assert(fwrite(bytes,1,sizeof bytes,f)==sizeof bytes); assert(!fclose(f)); assert(hud_custom_load(p,&b)==HUD_CUSTOM_UNSUPPORTED); assert(hud_custom_save(p,&a,1)==HUD_CUSTOM_UNSUPPORTED); f=fopen(p,"rb"); assert(f); assert(fread(got,1,sizeof got,f)==sizeof got); assert(fgetc(f)==EOF); assert(!fclose(f)); assert(!memcmp(bytes,got,sizeof bytes)); }
    memset(buf,'x',sizeof buf-1); buf[sizeof buf-1]=0; put(p,buf);
    a.stick_deadzone_percent=-1; r=hud_custom_save(p,&a,1); assert(r==HUD_CUSTOM_INVALID); get(p,before,sizeof before); assert(!strcmp(buf,before));
    assert(unlink(p)==0); puts("hud custom tests passed"); return 0;
}
