#!/usr/bin/env python3
"""Compile actual optional-resource and JNI startup helpers, no GPU/device/VM."""
from pathlib import Path
import os, subprocess, tempfile, unittest
ROOT = Path(__file__).resolve().parents[1]
# This file is copied to ports/android/tests before execution.
SRC = ROOT / 'src'
JDK = Path(os.environ.get('JAVA_HOME', '/Library/Java/JavaVirtualMachines/jdk-25.jdk/Contents/Home'))

def function(text, name):
    pos=text.index(name+'('); start=text.rfind('\n',0,pos)+1
    a=text.index('{',pos); level=0
    for i in range(a,len(text)):
        if text[i]=='{':level+=1
        elif text[i]=='}':
            level-=1
            if level==0:return text[start:i+1]+'\n'
    raise AssertionError('Unclosed helper')

class NativePaths(unittest.TestCase):
    def run_c(self, source, flags=()):
        with tempfile.TemporaryDirectory(prefix='resource-native-',dir=os.environ.get('TMPDIR')) as d:
            p=Path(d); (p/'test.c').write_text(source)
            subprocess.run(['cc','-std=c11','-pthread',*flags,str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True)

    def test_optional_getter(self):
        text=(SRC/'main_android.c').read_text()
        code='''#include <assert.h>
#include <pthread.h>
#include <string.h>
#include <stddef.h>
static struct {pthread_mutex_t mx;char optional_files[14][512];} A={.mx=PTHREAD_MUTEX_INITIALIZER};
'''+function(text,'android_optional_resource_path')+r'''
int main(void){char out[512];
assert(!android_optional_resource_path("story-cutin.bin",out,sizeof out)&&!out[0]);
strcpy(A.optional_files[0],"/verified/story-cutin.bin");
assert(android_optional_resource_path("story-cutin.bin",out,sizeof out));assert(!strcmp(out,A.optional_files[0]));
assert(!android_optional_resource_path("card-pages.bin",out,sizeof out)&&!out[0]);
strcpy(A.optional_files[6],"/verified/front_halo.wpk");strcpy(A.optional_files[7],"/verified/front_halo.bin");
assert(android_optional_resource_path("front_halo.wpk",out,sizeof out)&&!strcmp(out,A.optional_files[6]));
assert(android_optional_resource_path("front_halo.bin",out,sizeof out)&&!strcmp(out,A.optional_files[7]));
strcpy(A.optional_files[8],"/verified/mileage-aura.wpk");strcpy(A.optional_files[9],"/verified/mileage-menu.bin");
assert(android_optional_resource_path("mileage-aura.wpk",out,sizeof out)&&!strcmp(out,A.optional_files[8]));
assert(android_optional_resource_path("mileage-menu.bin",out,sizeof out)&&!strcmp(out,A.optional_files[9]));
strcpy(A.optional_files[10],"/verified/ghost-match.bin");
assert(android_optional_resource_path("ghost-match.bin",out,sizeof out)&&!strcmp(out,A.optional_files[10]));
strcpy(A.optional_files[11],"/verified/ghost-wheel-lman.wpk");
assert(android_optional_resource_path("ghost-wheel-lman.wpk",out,sizeof out)&&!strcmp(out,A.optional_files[11]));
strcpy(A.optional_files[12],"/verified/finish-menu.bin");
assert(android_optional_resource_path("finish-menu.bin",out,sizeof out)&&!strcmp(out,A.optional_files[12]));
strcpy(A.optional_files[13],"/verified/crown-scenes.bin");
assert(android_optional_resource_path("crown-scenes.bin",out,sizeof out)&&!strcmp(out,A.optional_files[13]));
assert(!android_optional_resource_path("../story-cutin.bin",out,sizeof out));
assert(!android_optional_resource_path("story-cutin.bin",out,2)&&!out[0]);
assert(!android_optional_resource_path(NULL,out,sizeof out));
assert(!android_optional_resource_path("story-cutin.bin",NULL,0));return 0;}
'''
        self.run_c(code)

    def test_meter_android_disabled_and_other_platform_fallback(self):
        text=(SRC/'hud.c').read_text(); a=text.index('static char meter_extra_path'); b=text.index('/* Preview owns',a)
        code=r'''#include <assert.h>
#include <string.h>
#include <stdio.h>
#define MP_CARS 2
#define MP_ZONES 4
struct row {int n[4];}; static const struct row METERDB[2]={{0}},METERDB_V2[2]={{0}};
struct pack {int sprites;}; static struct pack meter_legacy,meter_extra;
static char meter_path[1024],last_extra[1024];static void *meter_car;static int reads;
static void preview_clear(void){}
static void mp_clear(struct pack *p){p->sprites=0;}
static int mp_read(const char *path,int extra,void *counts,struct pack *p){if(extra){reads++;snprintf(last_extra,sizeof last_extra,"%s",path);}p->sprites=1;return 1;}
'''+text[a:b]+function(text,'hud_set_extra_directory')+function(text,'meters_index')+r'''
int main(void){
hud_set_extra_directory(NULL);meters_index("/bait/legacy");
#ifdef __ANDROID__
assert(reads==0&&!meter_extra_path[0]&&!meter_extra.sprites);
#else
assert(reads==1&&!strcmp(last_extra,"/bait/legacy/meters-v2.bin"));
#endif
reads=0;hud_set_extra_directory("/verified/card");meters_index("/bait/legacy");
assert(reads==1&&!strcmp(last_extra,"/verified/card/meters-v2.bin"));
char huge[2048];memset(huge,'x',sizeof huge-1);huge[sizeof huge-1]=0;
reads=0;hud_set_extra_directory(huge);meters_index("/bait/legacy");assert(reads==0&&!meter_extra_path[0]);
reads=0;hud_set_extra_directory("");meters_index("/bait/legacy");
#ifdef __ANDROID__
assert(reads==0&&!meter_extra_path[0]);
#else
assert(reads==1);
#endif
return 0;}
'''
        self.run_c(code,['-D__ANDROID__']);self.run_c(code)

    def test_actual_native_start_failure_and_reattach(self):
        text=(SRC/'main_android.c').read_text()
        start=text.index('JNIEXPORT jboolean JNICALL JFN(nativeStart)');end=text.index('JNIEXPORT void JNICALL JFN(nativeSurface)',start)
        code=r'''#include <jni.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <pthread.h>
#include <stdatomic.h>
static struct {
  pthread_mutex_t mx;JavaVM *vm;jobject activity;
  jmethodID show_movie,play_bgm,play_race_bgm,set_bgm_volume,set_bgm_gameplay_paused,fail,frame_rate_limit_changed;
  jmethodID ghost_cloud_configured,ghost_cloud_refresh,ghost_cloud_poll,ghost_cloud_enqueue;
  jmethodID ghost_cloud_search,ghost_cloud_search_id,ghost_cloud_report,ghost_cloud_defense_refresh,ghost_cloud_defense_poll;
  jmethodID crown_refresh,crown_poll,crown_ack,crown_enqueue;
  jmethodID timing_cloud_submit,timing_cloud_ack,timing_cloud_refresh,timing_cloud_board,online_vs_address;
  char data_dir[512],save_dir[512],sidecar_dir[512],ta_store_dir[512],ghost_crown_dir[512],optional_files[14][512];
  _Atomic unsigned activity_generation;
} A={.mx=PTHREAD_MUTEX_INITIALIZER};
static _Atomic unsigned bgm_extra_mask;
static int exception,fail_utf,fail_method,fail_ref,fail_attr,fail_stack,fail_thread,refs,created,detached,released;
static JavaVM vm_slot;
static jint fake_vm(JNIEnv *e,JavaVM **v){*v=&vm_slot;return JNI_OK;}
static jboolean fake_exception(JNIEnv *e){return exception?JNI_TRUE:JNI_FALSE;}
static const char *fake_utf(JNIEnv *e,jstring s,jboolean *b){if(fail_utf){exception=1;return NULL;}return (const char*)s;}
static void fake_release(JNIEnv *e,jstring s,const char *p){released++;}
static jmethodID fake_method(JNIEnv *e,jclass c,const char *n,const char *s){if(fail_method){exception=1;return NULL;}return (jmethodID)1;}
static jobject fake_new(JNIEnv *e,jobject o){if(fail_ref){exception=1;return NULL;}refs++;return o;}
static void fake_delete(JNIEnv *e,jobject o){refs--;}
static void *game(void *p){return NULL;}
static int attr_init(pthread_attr_t *a){return fail_attr?1:pthread_attr_init(a);}
static int attr_stack(pthread_attr_t *a,size_t n){return fail_stack?1:pthread_attr_setstacksize(a,n);}
static int create_thread(pthread_t *t,const pthread_attr_t *a,void *(*f)(void*),void *p){if(fail_thread)return 1;created++;*t=pthread_self();return 0;}
static int detach_thread(pthread_t t){detached++;return 0;}
#define pthread_attr_init attr_init
#define pthread_attr_setstacksize attr_stack
#define pthread_create create_thread
#define pthread_detach detach_thread
#define JFN(name) native_##name
#define ROOT_CALL(actor,root) native_nativeStart(&e,NULL,(jobject)(actor),(jstring)"/data",(jstring)"/save",(jstring)"/card",NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,(jstring)(root),NULL)
'''+text[start:end]+r'''
int main(void){struct JNINativeInterface_ table={.GetJavaVM=fake_vm,.ExceptionCheck=fake_exception,.GetStringUTFChars=fake_utf,.ReleaseStringUTFChars=fake_release,.GetMethodID=fake_method,.NewGlobalRef=fake_new,.DeleteGlobalRef=fake_delete};JNIEnv e=&table;
#define CALL(actor,data) native_nativeStart(&e,NULL,(jobject)(actor),(jstring)(data),(jstring)"/save",(jstring)"/card",(jstring)"/cutin",NULL,(jstring)"/wpk",(jstring)"/bfx",NULL,NULL,(jstring)"/halo-wpk",(jstring)"/halo-bin",(jstring)"/aura",(jstring)"/mileage",(jstring)"/match",(jstring)"/ghost-wheel",(jstring)"/finish-menu",(jstring)"/crown-scenes",(jstring)"/ta-private",(jstring)"/ghost-private")
assert(!CALL(1,NULL)&&!A.activity&&!refs);
fail_utf=1;assert(!CALL(1,"/data")&&!A.activity&&!refs);fail_utf=exception=0;
fail_method=1;assert(!CALL(1,"/data")&&!A.activity&&!refs);fail_method=exception=0;
fail_ref=1;assert(!CALL(1,"/data")&&!A.activity&&!refs);fail_ref=exception=0;
char huge[513];memset(huge,'x',512);huge[512]=0;assert(!CALL(1,huge)&&!A.activity&&!refs);
fail_attr=1;assert(!CALL(1,"/data")&&!A.activity&&!refs&&!A.data_dir[0]);fail_attr=0;
fail_stack=1;assert(!CALL(1,"/data")&&!A.activity&&!refs);fail_stack=0;
fail_thread=1;assert(!CALL(1,"/data")&&!A.activity&&!refs&&!A.ta_store_dir[0]&&!atomic_load(&bgm_extra_mask));fail_thread=0;
assert(CALL(1,"/data")&&refs==1&&created==1&&detached==1);assert(!strcmp(A.data_dir,"/data")&&!strcmp(A.optional_files[0],"/cutin")&&!A.optional_files[1][0]);
assert(!strcmp(A.optional_files[6],"/halo-wpk")&&!strcmp(A.optional_files[7],"/halo-bin")&&!strcmp(A.ghost_crown_dir,"/ghost-private"));
assert(!strcmp(A.optional_files[8],"/aura")&&!strcmp(A.optional_files[9],"/mileage")&&!strcmp(A.optional_files[10],"/match")&&!strcmp(A.optional_files[11],"/ghost-wheel")&&!strcmp(A.optional_files[12],"/finish-menu"));
assert(!strcmp(A.optional_files[13],"/crown-scenes"));
atomic_store(&bgm_extra_mask,0);assert(CALL(2,"/bait")&&refs==1&&created==1&&A.activity==(jobject)2);assert(!strcmp(A.data_dir,"/data")&&!atomic_load(&bgm_extra_mask));assert(atomic_load(&A.activity_generation)==2);assert(!strcmp(A.ta_store_dir,"/ta-private"));
/* Reattach must preserve the first private root despite a new Activity bait. */
assert(ROOT_CALL(3,"/bait-rank")&&!strcmp(A.ta_store_dir,"/ta-private")&&!strcmp(A.save_dir,"/save"));
/* Reset only the fake singleton to simulate independent cold starts. */
A.activity=NULL;refs=0;assert(ROOT_CALL(4,NULL)&&!A.ta_store_dir[0]&&!strcmp(A.save_dir,"/save"));
A.activity=NULL;refs=0;assert(ROOT_CALL(5,"relative")&&!A.ta_store_dir[0]&&!strcmp(A.save_dir,"/save"));
A.activity=NULL;refs=0;huge[0]='/';assert(ROOT_CALL(6,huge)&&!A.ta_store_dir[0]&&!strcmp(A.save_dir,"/save"));return 0;}
'''
        self.run_c(code,['-I'+str(JDK/'include'),'-I'+str(JDK/'include/darwin')])

if __name__=='__main__':unittest.main()
