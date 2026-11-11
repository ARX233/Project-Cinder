/* The Android side of the port (main.m's, for a phone like the Xiaomi Mi 6): MainActivity.java
 * hands over the SurfaceView's surface, touches, the gravity and the lifecycle; the game runs
 * on a thread of its own here with an OpenGL ES 3 context (4x MSAA) on that surface, the
 * loading thread with a context sharing it, and the sound through AAudio. Built with -DWMMT_VK
 * the game's GL goes through vkgl (Vulkan) instead: a swapchain on the surface, the loading
 * thread vkgl's second. */
#ifdef WMMT_VK
#define VK_USE_PLATFORM_ANDROID_KHR
#endif
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <aaudio/AAudio.h>
#include <android/log.h>
#include <android/native_window_jni.h>
#include <jni.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include "timing60.h"
#include <unistd.h>

#ifdef WMMT_DEBUG_LOG
#error "The Android 1.24 no-log build must not include the diagnostic collector"
#endif
#include "app.h"
#ifdef WMMT_NATIVE_VK
#include "native_vk.h"
#else
#include "gl.h"
#endif
#include "sound.h"
#include "hud.h"

/* the attract movies (prepare_movie.sh), indexed as app_movie() returns them */
static const char *const MOVIES[3] = { "intro.mp4", "playdemo.mp4", "tutorial.mp4" };

#define TOUCH_MAX 256
typedef struct { int id, phase; float x, y; } touch_ev;

static struct {
  JavaVM *vm;
  jobject activity;
  jmethodID show_movie, play_bgm, play_race_bgm, set_bgm_volume, set_bgm_gameplay_paused, fail, frame_rate_limit_changed;
  jmethodID online_vs_address;
  jmethodID ghost_cloud_configured, ghost_cloud_refresh, ghost_cloud_poll, ghost_cloud_enqueue;
  jmethodID ghost_cloud_search, ghost_cloud_search_id, ghost_cloud_report;
  jmethodID ghost_cloud_defense_refresh, ghost_cloud_defense_poll;
  jmethodID crown_refresh, crown_poll, crown_ack, crown_enqueue;
  jmethodID timing_cloud_submit, timing_cloud_ack, timing_cloud_refresh, timing_cloud_board;
  _Atomic unsigned activity_generation;
  _Atomic int refresh_millihz; /* Java's <=120 Hz display hint, 0 uses safe 60 Hz */
  _Atomic int frame_rate_limit; /* game-thread option, read by the Activity */
  unsigned synced_generation;
  int bgm_level, bgm_gameplay_paused;
  char data_dir[512], save_dir[512], sidecar_dir[512], ta_store_dir[512], ghost_crown_dir[512];
  char optional_files[14][512]; /* Java publishes only catalog-verified read-only paths. */
  pthread_mutex_t mx;
  pthread_cond_t cv;
  ANativeWindow *window; /* the surface to draw on (NULL while there is none) */
  int window_changed, paused, started;
  touch_ev touches[TOUCH_MAX];
  int n_touch, touch_desync;
  int press_start, memory_warning;
  jlong movie_token, movie_done_ev; /* protected by mx; 0 means no live request/event */
  uint64_t movie_serial;
  unsigned movie_generation;
  int movie_start_ev;
  float tilt;
  int tilt_new, wants_tilt;
  /* the game thread's own */
#ifdef WMMT_VK
  int vk_up, have_surface;
  VkSurfaceKHR vk_surface;
#endif
  EGLDisplay dpy;
  EGLConfig config;
  EGLContext ctx, load_ctx;
  EGLSurface surface;
  int fb_w, fb_h;
  float touch_k, touch_edge;
  int movie; /* shown, -1 none */
  const char *bgm;
  AAudioStream *audio;
} A = { .movie = -1, .bgm_level = -1, .mx = PTHREAD_MUTEX_INITIALIZER, .cv = PTHREAD_COND_INITIALIZER };

/* TOUCH_FAILSAFE_BEGIN: queue mutation requires A.mx; active IDs belong solely to
 * the game thread. A poisoned queue rejects every event until its poison is taken.
 * Thereafter unknown IDs are suppressed permanently: a new explicit DOWN alone
 * can enroll an ID, so old fingers cannot reactivate after cancellation. */
static void touch_enqueue(touch_ev ev) {
  if (A.touch_desync) return;
  if (A.n_touch == TOUCH_MAX) {
    A.n_touch = 0;
    A.touch_desync = 1;
    return;
  }
  A.touches[A.n_touch++] = ev;
}

/* Called under A.mx. The returned snapshot predates any later producer overflow. */
static int touch_take(touch_ev *out, int *desync) {
  int n = A.n_touch;
  memcpy(out, A.touches, (size_t)n * sizeof *out);
  *desync = A.touch_desync;
  A.n_touch = A.touch_desync = 0;
  return n;
}

typedef struct touch_active {
  int id;
  float x, y;
  struct touch_active *next;
} touch_active;
static touch_active *touch_active_head;
static int touch_strict;

static void touch_cancel_all(void) {
#ifdef WMMT_DEBUG_LOG
  debug_log_emit("{\"event\":\"touch_cancel_all\"}");
#endif
  while (touch_active_head) {
    touch_active *p = touch_active_head;
    touch_active_head = p->next;
    app_touch((void *)((intptr_t)p->id + 1), 3, p->x * A.touch_k - A.touch_edge, p->y * A.touch_k);
    free(p);
  }
  touch_strict = 1;
}

/* A newer overflow or lifecycle poison invalidates the remaining snapshot.
 * This check is deliberately short; input can arrive again after it returns. */
static void touch_reconcile_snapshot(int *n, int *desync) {
  pthread_mutex_lock(&A.mx);
  if (A.touch_desync) {
    A.n_touch = 0;
    A.touch_desync = 0;
    *n = 0;
    *desync = 1;
  }
  pthread_mutex_unlock(&A.mx);
}

static void touch_deliver(touch_ev *events, int n, int desync) {
  if (desync) touch_cancel_all();
  for (int i = 0; i < n; ++i) {
    int remaining = n - i, poisoned = 0;
    touch_reconcile_snapshot(&remaining, &poisoned);
    if (poisoned) { touch_cancel_all(); return; }
    touch_ev e = events[i];
    touch_active **link = &touch_active_head;
    while (*link && (*link)->id != e.id) link = &(*link)->next;
    touch_active *p = *link;
    if (e.phase == 0 && !p) {
      p = malloc(sizeof *p);
      if (!p) {
        /* Discard both the unprocessed snapshot and anything concurrently queued.
         * The poison prevents new events until the game thread takes it. */
        pthread_mutex_lock(&A.mx);
        A.n_touch = 0;
        A.touch_desync = 1;
        pthread_mutex_unlock(&A.mx);
        touch_cancel_all();
        return;
      }
      *p = (touch_active){ e.id, e.x, e.y, NULL };
      *link = p;
    } else if (touch_strict && !p) {
      continue;
    }
    if (p) { p->x = e.x; p->y = e.y; }
#ifdef WMMT_DEBUG_LOG
    /* Phase only: raw coordinates can disclose typed names or card choices. */
    if (e.phase == 0 || e.phase == 2 || e.phase == 3)
      debug_log_emit("{\"event\":\"touch\",\"phase\":%d}", e.phase);
#endif
    app_touch((void *)((intptr_t)e.id + 1), e.phase, e.x * A.touch_k - A.touch_edge, e.y * A.touch_k);
    if (p && (e.phase == 2 || e.phase == 3)) {
      *link = p->next;
      free(p);
    }
  }
}
/* TOUCH_FAILSAFE_END */

/* Set only after the immutable sidecar passed CardResources.prepare. Failure events
 * disable a group for this session, without touching its persisted preference. */
static _Atomic unsigned bgm_extra_mask;
int android_bgm_group_available(int group) {
  return group >= 1 && group <= 2 && (atomic_load(&bgm_extra_mask) & (1u << group)) != 0;
}

/* HUD may declare this function locally. Copies a stable snapshot under the activity lock;
 * returns 1 when available, 0 when absent or the caller's buffer is too small. */
int android_card_resources_dir(char *out, size_t capacity) {
  int ok = 0;
  if (!out || capacity == 0) return 0;
  pthread_mutex_lock(&A.mx);
  size_t n = strlen(A.sidecar_dir);
  if (n && n < capacity) { memcpy(out, A.sidecar_dir, n + 1); ok = 1; }
  else out[0] = '\0';
  pthread_mutex_unlock(&A.mx);
  return ok;
}

/* No filesystem guessing: unavailable/unverified optional resources stay disabled. */
int android_optional_resource_path(const char *name, char *out, size_t capacity) {
  static const char *const names[] = {"story-cutin.bin", "card-pages.bin", "backfire.wpk", "backfire.bfx",
      "ghost-ui.bin", "builtin-ghosts.bin", "front_halo.wpk", "front_halo.bin", "mileage-aura.wpk", "mileage-menu.bin", "ghost-match.bin", "ghost-wheel-lman.wpk", "finish-menu.bin", "crown-scenes.bin"};
  if (!name || !out || !capacity) return 0;
  out[0] = 0;
  int index = -1;
  for (int i = 0; i < (int)(sizeof names / sizeof names[0]); ++i) if (!strcmp(name, names[i])) index = i;
  if (index < 0) return 0;
  pthread_mutex_lock(&A.mx);
  size_t n = strlen(A.optional_files[index]);
  int ok = n && n < capacity;
  if (ok) memcpy(out, A.optional_files[index], n + 1);
  pthread_mutex_unlock(&A.mx);
  return ok;
}

static double now_s(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (double)t.tv_sec + t.tv_nsec * 1e-9;
}

/* ---- sound: sound.c's mix, 44.1 kHz stereo int16, low latency ---- */

_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "audio error flag must be lock-free");
static _Atomic unsigned audio_disconnect_generation;
static _Atomic int audio_other_error;
static unsigned audio_generation, audio_handled_generation;
static snd_retry audio_retry;

static aaudio_data_callback_result_t audio_cb(AAudioStream *s, void *user, void *data, int32_t frames) {
  snd_mix((short *)data, frames);
  snd_diag_callback((const short *)data, frames);
  return AAUDIO_CALLBACK_RESULT_CONTINUE;
}

/* The callback only publishes an error. The game thread owns stream lifetime. */
static void audio_error(AAudioStream *s, void *user, aaudio_result_t err) {
  unsigned generation = (unsigned)(uintptr_t)user;
  if (err == AAUDIO_ERROR_DISCONNECTED) {
    snd_diag_disconnect(&audio_disconnect_generation, generation);
  } else atomic_store_explicit(&audio_other_error, err, memory_order_relaxed);
}

static void audio_close(void) {
  if (A.audio) { AAudioStream_close(A.audio); A.audio = NULL; }
}
static int audio_start(void) {
  aaudio_result_t r = AAudioStream_requestStart(A.audio);
  fprintf(stderr, "audio_diag start=%d state=%d\n", r, AAudioStream_getState(A.audio));
  return r == AAUDIO_OK;
}
static int audio_open(void) {
  AAudioStreamBuilder *b = NULL;
  if (audio_generation == UINT32_MAX) { fprintf(stderr, "audio_diag generation exhausted\n"); return 0; }
  ++audio_generation;
  aaudio_result_t r = AAudio_createStreamBuilder(&b);
  if (r != AAUDIO_OK) { fprintf(stderr, "audio_diag create=%d\n", r); return 0; }
  AAudioStreamBuilder_setFormat(b, AAUDIO_FORMAT_PCM_I16);
  AAudioStreamBuilder_setChannelCount(b, 2);
  AAudioStreamBuilder_setSampleRate(b, SND_RATE);
  AAudioStreamBuilder_setPerformanceMode(b, AAUDIO_PERFORMANCE_MODE_LOW_LATENCY);
  AAudioStreamBuilder_setUsage(b, AAUDIO_USAGE_GAME);
  AAudioStreamBuilder_setDataCallback(b, audio_cb, NULL);
  /* Integer token is never dereferenced; late callbacks cannot target a newer generation. */
  AAudioStreamBuilder_setErrorCallback(b, audio_error, (void *)(uintptr_t)audio_generation);
  r = AAudioStreamBuilder_openStream(b, &A.audio);
  AAudioStreamBuilder_delete(b);
  if (r != AAUDIO_OK) { A.audio = NULL; fprintf(stderr, "audio_diag open=%d\n", r); return 0; }
  int format = AAudioStream_getFormat(A.audio), channels = AAudioStream_getChannelCount(A.audio);
  int rate = AAudioStream_getSampleRate(A.audio);
  fprintf(stderr, "audio_diag open=%d format=%d rate=%d channels=%d state=%d\n", r, format, rate, channels, AAudioStream_getState(A.audio));
  /* snd_mix writes stereo int16 and assumes SND_RATE; never start an incompatible stream. */
  if (format != AAUDIO_FORMAT_PCM_I16 || channels != 2 || rate != SND_RATE) {
    fprintf(stderr, "audio_diag incompatible stream; not started\n");
    audio_close(); return 0;
  }
  if (!audio_start()) { audio_close(); return 0; }
  return 1;
}

/* Called only when the game is active. A generation is never reused; old
 * callback notifications therefore cannot clear or supersede newer ones. */
static void audio_service(int resume, double now) {
  int err = atomic_exchange_explicit(&audio_other_error, 0, memory_order_relaxed);
  if (err) fprintf(stderr, "audio_diag callback_error=%d\n", err);
  int interrupted = 0;
  unsigned disconnected = atomic_load_explicit(&audio_disconnect_generation, memory_order_relaxed);
  if (A.audio && disconnected == audio_generation && disconnected != audio_handled_generation) {
    audio_handled_generation = disconnected;
    fprintf(stderr, "audio_diag disconnected generation=%u\n", disconnected);
    audio_close();
    now = now_s(); interrupted = 1;
    snd_retry_interrupt(&audio_retry, now);
    if (!audio_retry.pending) fprintf(stderr, "audio_diag retry_exhausted attempts=3\n");
  }
  if (resume && A.audio) {
    int state = AAudioStream_getState(A.audio);
    if (state != AAUDIO_STREAM_STATE_STARTED && !audio_start()) {
      audio_close();
      now = now_s(); interrupted = 1;
      snd_retry_interrupt(&audio_retry, now);
      if (!audio_retry.pending) fprintf(stderr, "audio_diag retry_exhausted attempts=3\n");
    }
  }
  /* Apply resume after processing a pending disconnect or failed resume start.
   * A newly interrupted stream still observes its full five-second backoff. */
  if (resume && !A.audio && !audio_retry.pending && audio_retry.attempts >= 3)
    snd_retry_begin(&audio_retry, now + (interrupted ? 5.0 : 0.0));
  if (snd_retry_due(&audio_retry, now, 0)) {
    int ok = audio_open();
    now = now_s();
    snd_retry_result(&audio_retry, now, ok);
    if (!ok && !audio_retry.pending) fprintf(stderr, "audio_diag retry_exhausted attempts=3\n");
  }
  if (A.audio) {
    /* A started state, not merely a successful start request, must persist for
     * ten active seconds before the retry budget is reset. */
    snd_retry_stability(&audio_retry, now, AAudioStream_getState(A.audio) == AAUDIO_STREAM_STATE_STARTED);
  }
}

/* ---- calls up to MainActivity (the game thread is attached to the VM) ---- */

static JNIEnv *env_here(void) {
  JNIEnv *env = NULL;
  if ((*A.vm)->GetEnv(A.vm, (void **)&env, JNI_VERSION_1_6) != JNI_OK) (*A.vm)->AttachCurrentThread(A.vm, &env, NULL);
  return env;
}

static void call_str(jmethodID m, const char *s) {
  JNIEnv *env = env_here();
  jstring js = s ? (*env)->NewStringUTF(env, s) : NULL;
  pthread_mutex_lock(&A.mx);
  jobject activity = (*env)->NewLocalRef(env, A.activity);
  pthread_mutex_unlock(&A.mx);
  if (activity) { (*env)->CallVoidMethod(env, activity, m, js); (*env)->DeleteLocalRef(env, activity); }
  if (js) (*env)->DeleteLocalRef(env, js);
}

static void play_race_bgm(const char *track, const char *fallback, int fade_ms) {
  JNIEnv *env = env_here();
  jstring cue = (*env)->NewStringUTF(env, track);
  jstring alt = fallback ? (*env)->NewStringUTF(env, fallback) : NULL;
  pthread_mutex_lock(&A.mx);
  jobject activity = (*env)->NewLocalRef(env, A.activity);
  pthread_mutex_unlock(&A.mx);
  if (activity) {
    if (!(*env)->ExceptionCheck(env))
      (*env)->CallVoidMethod(env, activity, A.play_race_bgm, cue, alt, (jint)fade_ms);
    (*env)->DeleteLocalRef(env, activity);
  }
  if (cue) (*env)->DeleteLocalRef(env, cue);
  if (alt) (*env)->DeleteLocalRef(env, alt);
}

static jobject ghost_cloud_activity(JNIEnv *env) {
  pthread_mutex_lock(&A.mx);
  jobject activity=(*env)->NewLocalRef(env,A.activity);
  pthread_mutex_unlock(&A.mx);
  return activity;
}

static void sync_frame_rate_limit(void) {
  int limit = app_frame_rate_limit();
  if (limit == atomic_load(&A.frame_rate_limit)) return;
  atomic_store(&A.frame_rate_limit, limit);
  JNIEnv *env = env_here();
  pthread_mutex_lock(&A.mx);
  jobject activity = (*env)->NewLocalRef(env, A.activity);
  pthread_mutex_unlock(&A.mx);
  if (activity) {
    (*env)->CallVoidMethod(env, activity, A.frame_rate_limit_changed);
    (*env)->DeleteLocalRef(env, activity);
  }
  if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
}
static int ghost_cloud_jni_ok(JNIEnv *env) {
  if (!(*env)->ExceptionCheck(env)) return 1;
  (*env)->ExceptionClear(env);
  return 0;
}
int android_online_vs_address(char *out, size_t capacity) {
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jstring address=activity?(*env)->CallObjectMethod(env,activity,A.online_vs_address):NULL;
  int available=0;
  if (ghost_cloud_jni_ok(env) && address && out) {
    size_t length=(size_t)(*env)->GetStringUTFLength(env,address);
    if (length && length<capacity) {
      const char *value=(*env)->GetStringUTFChars(env,address,NULL);
      if (value) {
        memcpy(out,value,length+1);
        (*env)->ReleaseStringUTFChars(env,address,value);
        available=1;
      }
    }
  }
  if (address) (*env)->DeleteLocalRef(env,address);
  if (activity) (*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && available;
}
int android_ghost_cloud_configured(void) {
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jboolean configured=activity?(*env)->CallBooleanMethod(env,activity,A.ghost_cloud_configured):JNI_FALSE;
  if (activity) (*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && configured;
}
int android_ghost_cloud_refresh(const char *physics) {
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jstring id=activity?(*env)->NewStringUTF(env,physics):NULL;
  jboolean queued=id?(*env)->CallBooleanMethod(env,activity,A.ghost_cloud_refresh,id):JNI_FALSE;
  if (id) (*env)->DeleteLocalRef(env,id);
  if (activity) (*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && queued;
}
int android_ghost_crown_refresh(const char *physics,const char *card_id) {
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jstring id=activity && physics?(*env)->NewStringUTF(env,physics):NULL;
  jstring card=id && card_id?(*env)->NewStringUTF(env,card_id):NULL;
  jboolean queued=id && (!card_id || card)?(*env)->CallBooleanMethod(env,activity,A.crown_refresh,id,card):JNI_FALSE;
  if(card)(*env)->DeleteLocalRef(env,card);
  if(id)(*env)->DeleteLocalRef(env,id);
  if(activity)(*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && queued;
}
static int ghost_cloud_search(const char *physics,const uint16_t *name,unsigned length,const char *hex_id) {
  if (!physics || (hex_id==NULL && (!name || !length || length>5))) return 0;
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jstring version=activity?(*env)->NewStringUTF(env,physics):NULL;
  jstring query=NULL;
  if (version) query=hex_id?(*env)->NewStringUTF(env,hex_id):
      (*env)->NewString(env,(const jchar *)name,(jsize)length);
  jmethodID method=hex_id?A.ghost_cloud_search_id:A.ghost_cloud_search;
  jboolean queued=query?(*env)->CallBooleanMethod(env,activity,method,version,query):JNI_FALSE;
  if (query) (*env)->DeleteLocalRef(env,query);
  if (version) (*env)->DeleteLocalRef(env,version);
  if (activity) (*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && queued;
}
int android_ghost_cloud_search(const char *physics,const uint16_t *name,unsigned length) {
  return ghost_cloud_search(physics,name,length,NULL);
}
int android_ghost_cloud_search_id(const char *physics,const char *hex_id) {
  return hex_id && ghost_cloud_search(physics,NULL,0,hex_id);
}
static int ghost_cloud_poll(jmethodID method,unsigned char **data,size_t *bytes) {
  *data=NULL;*bytes=0;
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jbyteArray reply=activity?(*env)->CallObjectMethod(env,activity,method):NULL;
  if (activity) (*env)->DeleteLocalRef(env,activity);
  if (!ghost_cloud_jni_ok(env)) return -1;
  if (!reply) return 0;
  jsize n=(*env)->GetArrayLength(env,reply);
  unsigned char *buffer=n>0 && n<=8*1024*1024 ? malloc((size_t)n) : NULL;
  if (buffer) (*env)->GetByteArrayRegion(env,reply,0,n,(jbyte *)buffer);
  (*env)->DeleteLocalRef(env,reply);
  if (!ghost_cloud_jni_ok(env) || !buffer) { free(buffer);return -1; }
  *data=buffer;*bytes=(size_t)n;
  return 1;
}
int android_ghost_cloud_poll(unsigned char **data,size_t *bytes) {
  return ghost_cloud_poll(A.ghost_cloud_poll,data,bytes);
}
int android_ghost_crown_poll(unsigned char **data,size_t *bytes) {
  return ghost_cloud_poll(A.crown_poll,data,bytes);
}
int android_ghost_crown_ack(void) {
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jint result=activity?(*env)->CallIntMethod(env,activity,A.crown_ack):0;
  if(activity)(*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env)?result:0;
}
int android_ghost_crown_enqueue(unsigned area,const unsigned char previous[16],
                                const void *data,size_t bytes,const char *card_id) {
  if(area>=8 || !previous || !data || !bytes || bytes>512u*1024u || !card_id)return 0;
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jboolean queued=JNI_FALSE;
  jbyteArray id=activity?(*env)->NewByteArray(env,16):NULL;
  jbyteArray blob=id?(*env)->NewByteArray(env,(jsize)bytes):NULL;
  jstring card=blob?(*env)->NewStringUTF(env,card_id):NULL;
  if(card) {
    (*env)->SetByteArrayRegion(env,id,0,16,(const jbyte *)previous);
    (*env)->SetByteArrayRegion(env,blob,0,(jsize)bytes,data);
    if(ghost_cloud_jni_ok(env))
      queued=(*env)->CallBooleanMethod(env,activity,A.crown_enqueue,(jint)area,id,blob,card);
    (*env)->DeleteLocalRef(env,card);
  }
  if(blob)(*env)->DeleteLocalRef(env,blob);
  if(id)(*env)->DeleteLocalRef(env,id);
  if(activity)(*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && queued;
}
int android_ghost_cloud_enqueue_card(unsigned area,const void *data,size_t bytes,const char *card_id) {
  if (area>=8 || !data || !bytes || bytes>512u*1024u) return 0;
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jbyteArray blob=activity?(*env)->NewByteArray(env,(jsize)bytes):NULL;
  jboolean queued=JNI_FALSE;
  if (blob) {
    (*env)->SetByteArrayRegion(env,blob,0,(jsize)bytes,data);
    if (ghost_cloud_jni_ok(env)) {
      jstring card=card_id?(*env)->NewStringUTF(env,card_id):NULL;
      if (!card_id || card)
        queued=(*env)->CallBooleanMethod(env,activity,A.ghost_cloud_enqueue,(jint)area,blob,card);
      if (card) (*env)->DeleteLocalRef(env,card);
    }
    (*env)->DeleteLocalRef(env,blob);
  }
  if (activity) (*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && queued;
}
int android_ghost_cloud_enqueue(unsigned area,const void *data,size_t bytes) {
  return android_ghost_cloud_enqueue_card(area,data,bytes,NULL);
}
int android_ghost_cloud_report(const unsigned char id[16],int challenger_won,unsigned raw_model,
                               unsigned hp,int32_t ghost_gap_metres,const uint16_t *name,unsigned name_length) {
  if (!id || !name || !name_length || name_length>5 || raw_model>=247 || !hp || hp>2000) return 0;
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jbyteArray replay=activity?(*env)->NewByteArray(env,16):NULL;
  jstring rival=NULL;
  jboolean queued=JNI_FALSE;
  if (replay) {
    (*env)->SetByteArrayRegion(env,replay,0,16,(const jbyte *)id);
    if (ghost_cloud_jni_ok(env)) rival=(*env)->NewString(env,(const jchar *)name,(jsize)name_length);
    if (rival)
      queued=(*env)->CallBooleanMethod(env,activity,A.ghost_cloud_report,replay,
            challenger_won?JNI_TRUE:JNI_FALSE,(jint)raw_model,(jint)hp,(jint)ghost_gap_metres,rival);
  }
  if (rival) (*env)->DeleteLocalRef(env,rival);
  if (replay) (*env)->DeleteLocalRef(env,replay);
  if (activity) (*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && queued;
}
int android_ghost_cloud_defense_refresh(const char *card_id) {
  if (!card_id) return 0;
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jstring card=activity?(*env)->NewStringUTF(env,card_id):NULL;
  jboolean queued=card?(*env)->CallBooleanMethod(env,activity,A.ghost_cloud_defense_refresh,card):JNI_FALSE;
  if (card) (*env)->DeleteLocalRef(env,card);
  if (activity) (*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && queued;
}
int android_ghost_cloud_defense_poll(unsigned char **data,size_t *bytes) {
  return ghost_cloud_poll(A.ghost_cloud_defense_poll,data,bytes);
}

int android_timing_cloud_submit(const uint8_t *record, size_t bytes, int want_result) {
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jbyteArray data=activity?(*env)->NewByteArray(env,(jsize)bytes):NULL;
  jboolean queued=JNI_FALSE;
  if(data) {
    (*env)->SetByteArrayRegion(env,data,0,(jsize)bytes,(const jbyte *)record);
    if(ghost_cloud_jni_ok(env))queued=(*env)->CallBooleanMethod(env,activity,A.timing_cloud_submit,data,(jboolean)!!want_result);
    (*env)->DeleteLocalRef(env,data);
  }
  if(activity)(*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && queued;
}
int android_timing_cloud_ack(unsigned char **data,size_t *bytes) {
  return ghost_cloud_poll(A.timing_cloud_ack,data,bytes);
}
int android_timing_cloud_refresh(const char *rules,const char *physics,int course,int traffic) {
  JNIEnv *env=env_here();
  jobject activity=ghost_cloud_activity(env);
  jstring r=activity?(*env)->NewStringUTF(env,rules):NULL;
  jstring p=r?(*env)->NewStringUTF(env,physics):NULL;
  jboolean queued=p?(*env)->CallBooleanMethod(env,activity,A.timing_cloud_refresh,r,p,(jint)course,(jint)traffic):JNI_FALSE;
  if(p)(*env)->DeleteLocalRef(env,p);
  if(r)(*env)->DeleteLocalRef(env,r);
  if(activity)(*env)->DeleteLocalRef(env,activity);
  return ghost_cloud_jni_ok(env) && queued;
}
int android_timing_cloud_board(unsigned char **data,size_t *bytes) {
  return ghost_cloud_poll(A.timing_cloud_board,data,bytes);
}

/* the movie the attract loop wants and the BGM (main.m syncMovie) */
static void sync_bgm_gameplay_pause(int paused) {
  JNIEnv *env = env_here();
  pthread_mutex_lock(&A.mx);
  jobject activity = (*env)->NewLocalRef(env, A.activity);
  pthread_mutex_unlock(&A.mx);
  if (activity) {
    (*env)->CallVoidMethod(env, activity, A.set_bgm_gameplay_paused, (jboolean)paused);
    (*env)->DeleteLocalRef(env, activity);
  }
}

/* Called immediately when the story hold begins, before rendering. Leave the
 * frame cache alone: sync_movie also replays the state to a replacement Activity. */
void android_story_bgm_pause(void) { sync_bgm_gameplay_pause(1); }

/* Publish one identity for this view request, including hides. Do not call Java
 * under mx: runOnUiThread may run inline and report a missing/failed movie. */
static void sync_movie_view(int want, unsigned generation) {
  JNIEnv *env = env_here();
  jstring name = want >= 0 ? (*env)->NewStringUTF(env, MOVIES[want]) : NULL;
  pthread_mutex_lock(&A.mx);
  jobject activity = generation == atomic_load(&A.activity_generation)
      ? (*env)->NewLocalRef(env, A.activity) : NULL;
  jlong token = 0;
  if (activity) {
    token = (jlong)++A.movie_serial;
    if (!token) token = (jlong)++A.movie_serial;
    A.movie_token = want >= 0 ? token : 0;
    A.movie_generation = generation;
    A.movie_done_ev = 0;
    A.movie_start_ev = 0;
    A.movie = want;
  }
  pthread_mutex_unlock(&A.mx);
  if (activity) {
    (*env)->CallVoidMethod(env, activity, A.show_movie, name, token);
    (*env)->DeleteLocalRef(env, activity);
  }
  if (name) (*env)->DeleteLocalRef(env, name);
}

/* Game-thread-only menu mutation, also drained while suspended. Keep the shown
 * cache until sync_movie sends null; setting it to -1 here suppresses removal. */
static void movie_finish_pending(void) {
  pthread_mutex_lock(&A.mx);
  jlong token = A.movie_done_ev;
  int start = A.movie_start_ev;
  int current = token && token == A.movie_token &&
      A.movie_generation == atomic_load(&A.activity_generation);
  A.movie_done_ev = 0;
  A.movie_start_ev = 0;
  if (current) A.movie_token = 0;
  /* Keep owner validation and this movie-only transition atomic with nativeStart. */
  if (current && A.movie >= 0 && app_movie() == A.movie) {
    if (start) app_press_start();
    else app_movie_done();
  }
  pthread_mutex_unlock(&A.mx);
}

static void sync_movie(void) {
  unsigned generation = atomic_load(&A.activity_generation);
  if (generation != A.synced_generation) {
    A.synced_generation = generation;
    A.movie = -2; A.bgm = NULL; A.bgm_level = -1; A.bgm_gameplay_paused = -1;
  }
  int level = app_get_bgm_volume();
  if (level != A.bgm_level) {
    A.bgm_level = level;
    JNIEnv *env = env_here();
    pthread_mutex_lock(&A.mx);
    jobject activity = (*env)->NewLocalRef(env, A.activity);
    pthread_mutex_unlock(&A.mx);
    if (activity) {
      (*env)->CallVoidMethod(env, activity, A.set_bgm_volume, app_bgm_volume_multiplier());
      (*env)->DeleteLocalRef(env, activity);
    }
  }
  int want = app_movie();
  if (want != A.movie) sync_movie_view(want, generation);
  int paused = app_bgm_gameplay_paused();
  /* Pause before a replacement can start; release a replaced track before resuming. */
  if (paused && paused != A.bgm_gameplay_paused) {
    A.bgm_gameplay_paused = paused;
    sync_bgm_gameplay_pause(paused);
  }
  const char *track = app_bgm();
  if (track != A.bgm) {
    A.bgm = track;
    int fade_ms = app_bgm_crossfade_ms();
    if (track && (fade_ms || strncmp(track, "ten_", 4) == 0))
      play_race_bgm(track, app_bgm_fallback(), fade_ms);
    else call_str(A.play_bgm, track);
  }
  if (!paused && paused != A.bgm_gameplay_paused) {
    A.bgm_gameplay_paused = paused;
    sync_bgm_gameplay_pause(paused);
  }
}

/* ---- GL ---- */

#ifdef WMMT_NATIVE_VK
/* Native platform owns a transferred surface on success AND failure. The OS
 * creation step owns nothing until vkCreateAndroidSurfaceKHR succeeds. */
static int egl_init(void) {
  static const char *const ext[] = { VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_ANDROID_SURFACE_EXTENSION_NAME };
  if (cinder_vk_platform_create(ext, 2) != 0) return -1;
  char path[600];
  snprintf(path, sizeof path, "%s/vk_pipelines.bin", A.save_dir);
  cinder_vk_platform_pipeline_cache_file(path);
  A.vk_up = 1;
  return 0;
}
static void *loader(void *arg) {
  if (!cinder_vk_upload_stream_set(CINDER_VK_UPLOAD_LOADER)) return NULL;
  app_loader();
  return NULL;
}
static void take_window(void) {
  A.window_changed = 0;
  if (A.have_surface) cinder_vk_platform_release_surface();
  A.have_surface = 0; A.vk_surface = VK_NULL_HANDLE;
  A.fb_w = A.fb_h = 0;
  if (!A.window) return;
  int width = ANativeWindow_getWidth(A.window), height = ANativeWindow_getHeight(A.window);
  if (width <= 0 || height <= 0) return;
  VkAndroidSurfaceCreateInfoKHR ci = { VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR };
  ci.window = A.window;
  VkSurfaceKHR surface = VK_NULL_HANDLE;
  if (vkCreateAndroidSurfaceKHR(cinder_vk_platform_instance(), &ci, NULL, &surface) != VK_SUCCESS) {
    fprintf(stderr, "no Vulkan surface\n"); return;
  }
  /* Ownership moves here, including every platform_surface failure path. */
  if (cinder_vk_platform_surface(surface, width, height) != 0) {
    fprintf(stderr, "no Vulkan surface\n"); return;
  }
  A.have_surface = 1; /* readiness to acquire is separate from an acquired frame */
  cinder_vk_screen_extent(&A.fb_w, &A.fb_h);
  fprintf(stderr, "surface %dx%d (Vulkan)\n", A.fb_w, A.fb_h);
}
#define SURFACE_UP A.have_surface
#elif defined(WMMT_VK)
/* Vulkan (vkgl): reuse the pipeline cache from save_dir; do not collect
 * missing-shader diagnostic files in this no-log build. */
static int egl_init(void) {
  static const char *const ext[] = { VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_ANDROID_SURFACE_EXTENSION_NAME };
  if (vkgl_create(ext, 2) != 0) return -1;
  char path[600];
  snprintf(path, sizeof path, "%s/vk_pipelines.bin", A.save_dir);
  vkgl_pipeline_cache_file(path);
  A.vk_up = 1;
  A.load_ctx = (EGLContext)1; /* (a loading thread: vkgl's second) */
  return 0;
}

static void *loader(void *arg) {
  vkgl_thread_loader();
  app_loader();
  return NULL;
}

/* the surface MainActivity has now (under A.mx): its swapchain, or none */
static void take_window(void) {
  A.window_changed = 0;
  if (A.have_surface) {
    vkgl_release_surface(); /* (the surface with it) */
    A.vk_surface = VK_NULL_HANDLE;
    A.have_surface = 0;
  }
  if (!A.window) return;
  VkAndroidSurfaceCreateInfoKHR ci = { VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR };
  ci.window = A.window;
  if (vkCreateAndroidSurfaceKHR(vkgl_instance(), &ci, NULL, &A.vk_surface) != VK_SUCCESS ||
      vkgl_surface(A.vk_surface, ANativeWindow_getWidth(A.window), ANativeWindow_getHeight(A.window)) != 0) {
    fprintf(stderr, "no Vulkan surface\n");
    return;
  }
  A.have_surface = 1;
  vkgl_screen_size(&A.fb_w, &A.fb_h);
  fprintf(stderr, "surface %dx%d (Vulkan)\n", A.fb_w, A.fb_h);
}
#define SURFACE_UP A.have_surface
#else
#define SURFACE_UP (A.surface != EGL_NO_SURFACE)

static int egl_init(void) {
  A.dpy = eglGetDisplay(EGL_DEFAULT_DISPLAY);
  if (!eglInitialize(A.dpy, NULL, NULL)) return -1;
  /* 8-bit colour, depth 24 + stencil 8 (the cars' shadows), 4x MSAA where there is (an
   * Adreno resolves it on chip, nearly free) */
  for (int samples = 4; samples >= 0; samples -= 4) {
    const EGLint attr[] = { EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR, EGL_SURFACE_TYPE, EGL_WINDOW_BIT | EGL_PBUFFER_BIT,
                            EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 0,
                            EGL_DEPTH_SIZE, 24, EGL_STENCIL_SIZE, 8,
                            EGL_SAMPLE_BUFFERS, samples ? 1 : 0, EGL_SAMPLES, samples, EGL_NONE };
    EGLint n = 0;
    if (eglChooseConfig(A.dpy, attr, &A.config, 1, &n) && n == 1) {
      fprintf(stderr, "EGL config: %d samples\n", samples);
      break;
    }
    if (!samples) return -1;
  }
  const EGLint ca[] = { EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE };
  A.ctx = eglCreateContext(A.dpy, A.config, EGL_NO_CONTEXT, ca);
  if (A.ctx == EGL_NO_CONTEXT) return -1;
  A.load_ctx = eglCreateContext(A.dpy, A.config, A.ctx, ca);
  return 0;
}

static void *loader(void *arg) {
  const EGLint pa[] = { EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE };
  EGLSurface pb = eglCreatePbufferSurface(A.dpy, A.config, pa);
  if (!eglMakeCurrent(A.dpy, pb, pb, A.load_ctx)) {
    fprintf(stderr, "loading thread: no context\n");
    return NULL;
  }
  app_loader();
  return NULL;
}

/* the surface MainActivity has now (under A.mx): made current, or none */
static void take_window(void) {
  if (A.surface != EGL_NO_SURFACE) {
    eglMakeCurrent(A.dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroySurface(A.dpy, A.surface);
    A.surface = EGL_NO_SURFACE;
  }
  A.window_changed = 0;
  if (!A.window) return;
  A.surface = eglCreateWindowSurface(A.dpy, A.config, A.window, NULL);
  if (A.surface == EGL_NO_SURFACE || !eglMakeCurrent(A.dpy, A.surface, A.surface, A.ctx)) {
    fprintf(stderr, "no window surface: 0x%x\n", eglGetError());
    A.surface = EGL_NO_SURFACE;
    return;
  }
  eglQuerySurface(A.dpy, A.surface, EGL_WIDTH, &A.fb_w);
  eglQuerySurface(A.dpy, A.surface, EGL_HEIGHT, &A.fb_h);
  eglSwapInterval(A.dpy, 1);
  fprintf(stderr, "surface %dx%d\n", A.fb_w, A.fb_h);
}
#endif

/* The drawable extent and this cache belong to the game thread, not JNI's
 * Surface callback. Reuse the existing poison/strict-DOWN touch contract at a
 * mapping discontinuity: no queued old gesture is replayed in the new layout. */
static int ui_viewport_sync(int *snapshot_n, int *snapshot_desync) {
  static int mapped_w, mapped_h;
  int w = A.fb_w, h = A.fb_h;
  if (w <= 0 || h <= 0) return 0;
  if (w == mapped_w && h == mapped_h) return 1;
  float k = 768.0f / (float)h;
  float edge = ((float)w * k - 1024.0f) * 0.5f;
  if (edge < 1.0f) edge = 0.0f;
  if (mapped_w > 0) {
    /* Release captures using their previous mapping, before publishing k/edge. */
    touch_cancel_all();
    pthread_mutex_lock(&A.mx);
    A.n_touch = 0;
    A.touch_desync = 1;
    pthread_mutex_unlock(&A.mx);
    if (snapshot_n) *snapshot_n = 0;
    if (snapshot_desync) *snapshot_desync = 1;
  }
  /* The keys a little smaller than the iPhone's, matching the initial layout. */
  if (!app_viewport(w, h, edge, edge > 0.0f ? 1.2f : 1.0f)) return 0;
  A.touch_k = k;
  A.touch_edge = edge;
  mapped_w = w;
  mapped_h = h;
  return 1;
}

static int start_game(void) {
  app_save_dir(A.save_dir);
  app_ta_rank_save_dir(A.ta_store_dir);
  app_ghost_crown_save_dir(A.ghost_crown_dir);
  app_console();
  if (!ui_viewport_sync(NULL, NULL)) return -1;
  /* HUD loads once on this game thread; later Activity recreation does not reload it. */
  char sidecar[sizeof A.sidecar_dir];
  hud_set_extra_directory(android_card_resources_dir(sidecar, sizeof sidecar) ? sidecar : NULL);
  if (app_init(A.data_dir, A.fb_w, A.fb_h, 1024, 768) != 0) {
    fprintf(stderr, "%s\n", app_error());
    call_str(A.fail, app_error());
    return -1;
  }
  snd_retry_begin(&audio_retry, now_s());
  pthread_t t;
#ifdef WMMT_NATIVE_VK
  if (A.vk_up && pthread_create(&t, NULL, loader, NULL) == 0) pthread_detach(t);
#else
  if (A.load_ctx != EGL_NO_CONTEXT && pthread_create(&t, NULL, loader, NULL) == 0) pthread_detach(t);
#endif
  else fprintf(stderr, "no loading thread: the menu frames load\n");
  return 0;
}

static void *game(void *arg) {
  env_here();
  if (egl_init() != 0) {
#ifdef WMMT_NATIVE_VK
    call_str(A.fail, "no native Vulkan on this phone");
#else
    call_str(A.fail, "no OpenGL ES 3 on this phone");
#endif
    return NULL;
  }
  double last = 0;
  timing60_display_pacer pacer = {0};
  int failed = 0, away = 0;
  for (;;) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    int64_t ns = (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
    float refresh = timing60_limited_display_rate(atomic_load(&A.refresh_millihz) * 0.001f,
                                                  atomic_load(&A.frame_rate_limit));
    int64_t deadline = timing60_display_deadline(&pacer, ns, refresh);
    ts.tv_sec = deadline / 1000000000LL;
    ts.tv_nsec = deadline % 1000000000LL;
    int sleep_result;
    do { sleep_result = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL); }
    while (sleep_result == EINTR);
    if (sleep_result) { fprintf(stderr, "clock_nanosleep failed: %d\n", sleep_result); break; }
    touch_ev tv[TOUCH_MAX];
    int nt, touch_desync, press, warn, tilt_new;
    float tilt;
    pthread_mutex_lock(&A.mx);
    while (A.paused || (!A.window && !A.window_changed)) {
      if (A.movie_done_ev) {
        pthread_mutex_unlock(&A.mx);
        movie_finish_pending();
        pthread_mutex_lock(&A.mx);
      }
      if (A.started && !away && !failed) {
        /* The lifecycle callback poisoned the queue. Release captures on the
         * game thread even if no further surface/frame ever arrives. */
        pthread_mutex_unlock(&A.mx);
        touch_cancel_all();
#ifdef WMMT_DEBUG_LOG
        debug_log_emit("{\"event\":\"lifecycle_pause\"}");
        debug_log_flush();
#endif
        pthread_mutex_lock(&A.mx);
        app_suspend(1); /* the loading thread stops too */
#ifdef WMMT_VK
#ifdef WMMT_NATIVE_VK
        cinder_vk_platform_pipeline_cache_save();
#else
        vkgl_pipeline_cache_save();
#endif
#endif
        snd_retry_stability(&audio_retry, now_s(), 0);
        if (A.audio) {
          aaudio_result_t pause_result = AAudioStream_requestPause(A.audio);
          fprintf(stderr, "audio_diag pause=%d state=%d\n", pause_result, AAudioStream_getState(A.audio));
        }
        away = 1;
      }
      last = 0;
      timing60_display_reset(&pacer);
      if (A.paused || (!A.window && !A.window_changed))
        pthread_cond_wait(&A.cv, &A.mx);
    }
    if (A.window_changed) {
      take_window();
      last = 0;
      timing60_display_reset(&pacer);
      if (A.started && !failed) app_timing_reset();
    }
    /* Keep queued input while the surface is unavailable; overflow poisons it. */
    nt = 0; touch_desync = 0;
#ifdef WMMT_NATIVE_VK
    /* WSI may wait. Do not block lifecycle/input callbacks on A.mx. Only this
     * game thread mutates the backend surface; no window pointer is used here. */
    pthread_mutex_unlock(&A.mx);
    int frame_ready = SURFACE_UP && cinder_vk_platform_frame_ready();
    pthread_mutex_lock(&A.mx);
    if (A.paused || A.window_changed) frame_ready = 0;
    if (SURFACE_UP && !frame_ready && cinder_vk_platform_surface_stale()) A.window_changed = 1;
    press = warn = tilt_new = 0; tilt = 0;
    if (frame_ready) {
      nt = touch_take(tv, &touch_desync);
      press = A.press_start, warn = A.memory_warning;
      A.press_start = A.memory_warning = 0;
      tilt = A.tilt, tilt_new = A.tilt_new;
      A.tilt_new = 0;
    } /* Non-WSI rejection remains paced idle, not a surface/device recovery. */
#else
    if (SURFACE_UP) nt = touch_take(tv, &touch_desync);
    press = A.press_start, warn = A.memory_warning;
    A.press_start = A.memory_warning = 0;
    tilt = A.tilt, tilt_new = A.tilt_new;
    A.tilt_new = 0;
#endif
    pthread_mutex_unlock(&A.mx);
#ifdef WMMT_NATIVE_VK
    if (!frame_ready) {
      snd_retry_stability(&audio_retry, now_s(), 0); last = 0; timing60_display_reset(&pacer);
      /* Reset makes the next display deadline immediate. Bound unavailable
       * admission polling without changing the normal ready-frame pacer. */
      usleep(10000);
      continue;
    }
#else
    if (!SURFACE_UP) { snd_retry_stability(&audio_retry, now_s(), 0); last = 0; timing60_display_reset(&pacer); continue; }
#endif
    /* A ready surface is not evidence of a usable UI/input extent. Keep the
     * previous mapping until an actual positive drawable size is available. */
    if (A.fb_w <= 0 || A.fb_h <= 0) continue;
    if (!A.started) {
      A.started = 1;
      failed = start_game() != 0;
      if (!failed) sync_frame_rate_limit();
    }
    if (failed) {
      usleep(100000);
      continue;
    }
    if (!ui_viewport_sync(&nt, &touch_desync)) continue;
    audio_service(away, now_s());
    if (away) {
      app_suspend(0);
      away = 0;
    }
    if (warn) {
#ifdef WMMT_DEBUG_LOG
      if (debug_log_enabled()) debug_log_emit("{\"event\":\"memory_warning\"}");
#endif
      app_memory_warning();
    }
    movie_finish_pending();
    if (press) app_press_start();
    touch_reconcile_snapshot(&nt, &touch_desync);
    touch_deliver(tv, nt, touch_desync);
    A.wants_tilt = app_wants_tilt();
    if (tilt_new) app_tilt(tilt);
    double now = now_s();
    timing60_display_started(&pacer, (int64_t)(now * 1000000000.0));
    float dt = last > 0 ? (float)(now - last) : 0.0f;
    last = now;
#ifndef WMMT_NATIVE_VK
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
#endif
    /* Recheck just before the frame; later arrivals are handled next frame. */
    int empty = 0, poisoned = 0;
    touch_reconcile_snapshot(&empty, &poisoned);
    if (poisoned) touch_cancel_all();
    app_present(dt);
    sync_frame_rate_limit();
#ifdef WMMT_DEBUG_LOG
    /* Batch durability requests away from input callbacks; no synchronous I/O here. */
    static unsigned debug_flush_frames;
    if (++debug_flush_frames >= 120) { debug_flush_frames = 0; debug_log_flush(); }
#endif
    sync_movie();
#ifdef WMMT_NATIVE_VK
    /* Actual target-0 metadata filters absent aspects; no extension lookup or
     * inherited framebuffer binding. app owns explicit default-target selection. */
    cinder_vk_discard(0, VK_IMAGE_ASPECT_DEPTH_BIT | VK_IMAGE_ASPECT_STENCIL_BIT);
#else
    /* depth and stencil need not go out to memory */
    static PFNGLDISCARDFRAMEBUFFEREXTPROC discard_fb;
    if (!discard_fb) discard_fb = (PFNGLDISCARDFRAMEBUFFEREXTPROC)eglGetProcAddress("glDiscardFramebufferEXT");
    const GLenum discard[] = { GL_DEPTH_EXT, GL_STENCIL_EXT };
    if (discard_fb) discard_fb(GL_FRAMEBUFFER, 2, discard);
#endif
    double p0 = now_s();
#ifdef WMMT_VK
    /* (the swapchain made again for a new size or rotation) */
#ifdef WMMT_NATIVE_VK
    int present_result = cinder_vk_platform_present();
    if (present_result != 0 && cinder_vk_platform_surface_stale()) {
      pthread_mutex_lock(&A.mx);
      if (A.window) A.window_changed = 1;
      pthread_mutex_unlock(&A.mx);
    }
#else
    if (vkgl_present() != 0 && A.window) {
      pthread_mutex_lock(&A.mx);
      A.window_changed = 1;
      pthread_mutex_unlock(&A.mx);
    }
#endif
#else
    eglSwapBuffers(A.dpy, A.surface);
#endif
    double present_ms = (now_s() - p0) * 1000.0;
    app_frame_done(present_ms);
#ifdef WMMT_DEBUG_LOG
    {
      static unsigned long long debug_present_seq;
      ++debug_present_seq; /* game thread: one present for each app_frame */
      if (debug_log_enabled() && debug_present_seq % 12 == 0) {
        if (isfinite(present_ms) && present_ms >= 0.0 && present_ms < 1e9)
          debug_log_emit("{\"event\":\"present\",\"render_seq\":%llu,\"swap_us\":%llu}",
                         debug_present_seq, (unsigned long long)(present_ms * 1000.0));
        else
          debug_log_emit("{\"event\":\"present\",\"render_seq\":%llu,\"swap_us\":null}", debug_present_seq);
      }
    }
#endif
  }
  /* The game thread is process-lived; a fatal pacer error reaches this cleanup.
   * Quiesce the loader before releasing readers. The surface/context may already
   * be gone: forget GPU handles. This is not a new nativeStop lifecycle API. */
  if (A.started) app_suspend(1);
  snd_rev_stop();
  app_vs_release();
  app_smoke_release(1);
  app_body_release_assets(1);
  app_ghost_release_assets(1);
  app_ta_rank_release();
  return NULL;
}

/* ---- JNI ---- */

#define JFN(name) Java_com_wmmt_port_MainActivity_##name

JNIEXPORT void JNICALL JFN(nativeBgmFailure)(JNIEnv *env, jclass cls, jobject owner, jint group) {
  (void)cls;
  /* A late callback from a destroyed/replaced Activity must not disable the
   * resource group selected by its successor. */
  pthread_mutex_lock(&A.mx);
  int current = owner && A.activity && (*env)->IsSameObject(env, owner, A.activity);
  if (current && group >= 1 && group <= 2) atomic_fetch_and(&bgm_extra_mask, ~(1u << group));
  pthread_mutex_unlock(&A.mx);
}

JNIEXPORT jboolean JNICALL JFN(nativeStart)(JNIEnv *env, jclass cls, jobject activity, jstring data, jstring save, jstring sidecar,
                                           jstring cutin, jstring card_pages, jstring backfire_wpk, jstring backfire_bfx,
                                           jstring ghost_ui, jstring builtin_ghosts, jstring front_halo_wpk, jstring front_halo_anchors,
                                           jstring mileage_aura, jstring mileage_menu, jstring ghost_match, jstring ghost_wheel, jstring finish_menu,
                                           jstring crown_scenes, jstring ta_store_dir, jstring ghost_crown_dir) {
  if (!activity || !data || !save) return JNI_FALSE;
  JavaVM *vm = NULL;
  if ((*env)->GetJavaVM(env, &vm) != JNI_OK || !vm) return JNI_FALSE;
  jstring input[] = {data, save, sidecar, cutin, card_pages, backfire_wpk, backfire_bfx, ghost_ui,
                     builtin_ghosts, front_halo_wpk, front_halo_anchors, mileage_aura, mileage_menu, ghost_match, ghost_wheel, finish_menu,
                     crown_scenes, ta_store_dir, ghost_crown_dir};
  enum { path_count = sizeof input / sizeof *input, first_optional = 3,
         ta_store_index = path_count - 2, ghost_crown_index = path_count - 1 };
  _Static_assert(ta_store_index - first_optional == sizeof A.optional_files / sizeof A.optional_files[0],
                 "JNI optional resource paths must match native storage");
  const char *path[path_count] = {NULL};
  jboolean result = JNI_FALSE;
  for (int i = 0; i < path_count && !(*env)->ExceptionCheck(env); ++i)
    if (input[i]) path[i] = (*env)->GetStringUTFChars(env, input[i], NULL);
  if ((*env)->ExceptionCheck(env) || !path[0] || !path[1]) goto release;
  for (int i = 0; i < ta_store_index; ++i) if (path[i] && strlen(path[i]) >= 512) goto release;
  jmethodID show = (*env)->GetMethodID(env, cls, "showMovie", "(Ljava/lang/String;J)V");
  if (!show || (*env)->ExceptionCheck(env)) goto release;
  jmethodID bgm = (*env)->GetMethodID(env, cls, "playBgm", "(Ljava/lang/String;)V");
  if (!bgm || (*env)->ExceptionCheck(env)) goto release;
  jmethodID race_bgm = (*env)->GetMethodID(env, cls, "playRaceBgm", "(Ljava/lang/String;Ljava/lang/String;I)V");
  if (!race_bgm || (*env)->ExceptionCheck(env)) goto release;
  jmethodID volume = (*env)->GetMethodID(env, cls, "setBgmVolume", "(F)V");
  if (!volume || (*env)->ExceptionCheck(env)) goto release;
  jmethodID paused = (*env)->GetMethodID(env, cls, "setBgmGameplayPaused", "(Z)V");
  if (!paused || (*env)->ExceptionCheck(env)) goto release;
  jmethodID fail = (*env)->GetMethodID(env, cls, "fail", "(Ljava/lang/String;)V");
  if (!fail || (*env)->ExceptionCheck(env)) goto release;
  jmethodID frame_rate_limit_changed = (*env)->GetMethodID(env, cls, "frameRateLimitChanged", "()V");
  if (!frame_rate_limit_changed || (*env)->ExceptionCheck(env)) goto release;
  jmethodID online_vs_address=(*env)->GetMethodID(env,cls,"onlineVsAddress","()Ljava/lang/String;");
  if (!online_vs_address || (*env)->ExceptionCheck(env)) goto release;
  jmethodID cloud_configured=(*env)->GetMethodID(env,cls,"ghostCloudConfigured","()Z");
  if (!cloud_configured || (*env)->ExceptionCheck(env)) goto release;
  jmethodID cloud_refresh=(*env)->GetMethodID(env,cls,"ghostCloudRefresh","(Ljava/lang/String;)Z");
  if (!cloud_refresh || (*env)->ExceptionCheck(env)) goto release;
  jmethodID cloud_poll=(*env)->GetMethodID(env,cls,"ghostCloudPoll","()[B");
  if (!cloud_poll || (*env)->ExceptionCheck(env)) goto release;
  jmethodID cloud_enqueue=(*env)->GetMethodID(env,cls,"ghostCloudEnqueue","(I[BLjava/lang/String;)Z");
  if (!cloud_enqueue || (*env)->ExceptionCheck(env)) goto release;
  jmethodID cloud_search=(*env)->GetMethodID(env,cls,"ghostCloudSearch","(Ljava/lang/String;Ljava/lang/String;)Z");
  if (!cloud_search || (*env)->ExceptionCheck(env)) goto release;
  jmethodID cloud_search_id=(*env)->GetMethodID(env,cls,"ghostCloudSearchId","(Ljava/lang/String;Ljava/lang/String;)Z");
  if (!cloud_search_id || (*env)->ExceptionCheck(env)) goto release;
  jmethodID cloud_report=(*env)->GetMethodID(env,cls,"ghostCloudReport","([BZIIILjava/lang/String;)Z");
  if (!cloud_report || (*env)->ExceptionCheck(env)) goto release;
  jmethodID cloud_defense_refresh=(*env)->GetMethodID(env,cls,"ghostCloudDefenseRefresh","(Ljava/lang/String;)Z");
  if (!cloud_defense_refresh || (*env)->ExceptionCheck(env)) goto release;
  jmethodID cloud_defense_poll=(*env)->GetMethodID(env,cls,"ghostCloudDefensePoll","()[B");
  if (!cloud_defense_poll || (*env)->ExceptionCheck(env)) goto release;
  jmethodID crown_refresh=(*env)->GetMethodID(env,cls,"ghostCrownRefresh","(Ljava/lang/String;Ljava/lang/String;)Z");
  if(!crown_refresh || (*env)->ExceptionCheck(env))goto release;
  jmethodID crown_poll=(*env)->GetMethodID(env,cls,"ghostCrownPoll","()[B");
  if(!crown_poll || (*env)->ExceptionCheck(env))goto release;
  jmethodID crown_ack=(*env)->GetMethodID(env,cls,"ghostCrownPollAck","()I");
  if(!crown_ack || (*env)->ExceptionCheck(env))goto release;
  jmethodID crown_enqueue=(*env)->GetMethodID(env,cls,"ghostCrownEnqueue","(I[B[BLjava/lang/String;)Z");
  if(!crown_enqueue || (*env)->ExceptionCheck(env))goto release;
  jmethodID timing_submit=(*env)->GetMethodID(env,cls,"timingCloudSubmit","([BZ)Z");
  if (!timing_submit || (*env)->ExceptionCheck(env)) goto release;
  jmethodID timing_ack=(*env)->GetMethodID(env,cls,"timingCloudPollAck","()[B");
  if (!timing_ack || (*env)->ExceptionCheck(env)) goto release;
  jmethodID timing_refresh=(*env)->GetMethodID(env,cls,"timingCloudRefresh","(Ljava/lang/String;Ljava/lang/String;II)Z");
  if (!timing_refresh || (*env)->ExceptionCheck(env)) goto release;
  jmethodID timing_board=(*env)->GetMethodID(env,cls,"timingCloudPollBoard","()[B");
  if (!timing_board || (*env)->ExceptionCheck(env)) goto release;
  jobject replacement = (*env)->NewGlobalRef(env, activity);
  if (!replacement || (*env)->ExceptionCheck(env)) goto release;
  pthread_mutex_lock(&A.mx);
  if (A.activity) {
    (*env)->DeleteGlobalRef(env, A.activity);
    A.activity = replacement;
    atomic_fetch_add(&A.activity_generation, 1);
    pthread_mutex_unlock(&A.mx);
    result = JNI_TRUE;
    goto release;
  }
  A.vm = vm; A.activity = replacement;
  A.show_movie = show; A.play_bgm = bgm; A.play_race_bgm = race_bgm; A.set_bgm_volume = volume;
  A.set_bgm_gameplay_paused = paused; A.fail = fail;
  A.frame_rate_limit_changed = frame_rate_limit_changed;
  A.online_vs_address=online_vs_address;
  A.ghost_cloud_configured=cloud_configured;A.ghost_cloud_refresh=cloud_refresh;
  A.ghost_cloud_poll=cloud_poll;A.ghost_cloud_enqueue=cloud_enqueue;
  A.ghost_cloud_search=cloud_search;A.ghost_cloud_search_id=cloud_search_id;A.ghost_cloud_report=cloud_report;
  A.ghost_cloud_defense_refresh=cloud_defense_refresh;A.ghost_cloud_defense_poll=cloud_defense_poll;
  A.crown_refresh=crown_refresh;A.crown_poll=crown_poll;A.crown_ack=crown_ack;A.crown_enqueue=crown_enqueue;
  A.timing_cloud_submit=timing_submit;A.timing_cloud_ack=timing_ack;
  A.timing_cloud_refresh=timing_refresh;A.timing_cloud_board=timing_board;
  memcpy(A.data_dir, path[0], strlen(path[0]) + 1);
  memcpy(A.save_dir, path[1], strlen(path[1]) + 1);
  A.sidecar_dir[0] = 0;
  if (path[2]) memcpy(A.sidecar_dir, path[2], strlen(path[2]) + 1);
  A.ta_store_dir[0] = A.ghost_crown_dir[0] = 0;
  if (path[ta_store_index] && path[ta_store_index][0] == '/' && strlen(path[ta_store_index]) < sizeof A.ta_store_dir)
    memcpy(A.ta_store_dir, path[ta_store_index], strlen(path[ta_store_index]) + 1);
  if (path[ghost_crown_index] && path[ghost_crown_index][0] == '/' && strlen(path[ghost_crown_index]) < sizeof A.ghost_crown_dir)
    memcpy(A.ghost_crown_dir, path[ghost_crown_index], strlen(path[ghost_crown_index]) + 1);
  for (int i = first_optional; i < ta_store_index; ++i) {
    char *destination = A.optional_files[i - first_optional];
    destination[0] = 0;
    if (path[i]) memcpy(destination, path[i], strlen(path[i]) + 1);
  }
  atomic_store(&bgm_extra_mask, A.sidecar_dir[0] ? 6u : 0u);
  pthread_t thread;
  pthread_attr_t attr;
  int error = pthread_attr_init(&attr);
  if (!error) {
    error = pthread_attr_setstacksize(&attr, 8 << 20);
    if (!error) error = pthread_create(&thread, &attr, game, NULL);
    pthread_attr_destroy(&attr);
  }
  if (error) {
    A.activity = NULL; A.vm = NULL;
    A.data_dir[0] = A.save_dir[0] = A.sidecar_dir[0] = A.ta_store_dir[0] = A.ghost_crown_dir[0] = 0;
    memset(A.optional_files, 0, sizeof A.optional_files);
    atomic_store(&bgm_extra_mask, 0u);
    (*env)->DeleteGlobalRef(env, replacement);
  } else {
    atomic_fetch_add(&A.activity_generation, 1);
    pthread_detach(thread);
    result = JNI_TRUE;
  }
  pthread_mutex_unlock(&A.mx);
release:
  for (int i = 0; i < path_count; ++i) if (path[i]) (*env)->ReleaseStringUTFChars(env, input[i], path[i]);
  return result;
}

JNIEXPORT void JNICALL JFN(nativeSurface)(JNIEnv *env, jclass cls, jobject surface, jint w, jint h) {
  ANativeWindow *win = surface ? ANativeWindow_fromSurface(env, surface) : NULL;
  pthread_mutex_lock(&A.mx);
  if (!surface) { A.n_touch = 0; A.touch_desync = 1; }
  if (A.window) ANativeWindow_release(A.window);
  A.window = win;
  A.window_changed = 1;
  pthread_cond_broadcast(&A.cv);
  pthread_mutex_unlock(&A.mx);
#ifdef WMMT_DEBUG_LOG
  if (debug_log_enabled()) debug_log_emit("{\"event\":\"surface\",\"available\":%d,\"width\":%d,\"height\":%d}", surface != NULL, (int)w, (int)h);
#endif
  /* the old surface must be let go of before surfaceDestroyed returns */
  if (!surface) {
    for (int i = 0; i < 200; ++i) {
      pthread_mutex_lock(&A.mx);
      int pending = A.window_changed && A.started;
      pthread_mutex_unlock(&A.mx);
      if (!pending) break;
      usleep(5000);
    }
  }
}

JNIEXPORT void JNICALL JFN(nativeTouch)(JNIEnv *env, jclass cls, jint id, jint phase, jfloat x, jfloat y) {
  pthread_mutex_lock(&A.mx);
  touch_enqueue((touch_ev){ id, phase, x, y });
  pthread_mutex_unlock(&A.mx);
}

JNIEXPORT void JNICALL JFN(nativePause)(JNIEnv *env, jclass cls, jboolean p) {
  pthread_mutex_lock(&A.mx);
  if (p) { A.n_touch = 0; A.touch_desync = 1; }
  A.paused = p;
  pthread_cond_broadcast(&A.cv);
  pthread_mutex_unlock(&A.mx);
}

JNIEXPORT void JNICALL JFN(nativeTilt)(JNIEnv *env, jclass cls, jfloat r) {
  pthread_mutex_lock(&A.mx);
  A.tilt = r;
  A.tilt_new = 1;
  pthread_mutex_unlock(&A.mx);
}

JNIEXPORT jboolean JNICALL JFN(nativeWantsTilt)(JNIEnv *env, jclass cls) { return A.wants_tilt ? JNI_TRUE : JNI_FALSE; }

JNIEXPORT jint JNICALL JFN(nativeFrameRateLimit)(JNIEnv *env, jclass cls) {
  (void)env; (void)cls;
  return atomic_load(&A.frame_rate_limit);
}

JNIEXPORT void JNICALL JFN(nativeRefreshRate)(JNIEnv *env, jclass cls, jobject owner, jfloat hz) {
  (void)cls;
  pthread_mutex_lock(&A.mx);
  int current = owner && A.activity && (*env)->IsSameObject(env, owner, A.activity);
  if (current) atomic_store(&A.refresh_millihz, (int)(timing60_display_rate(hz) * 1000.0f + 0.5f));
  pthread_mutex_unlock(&A.mx);
}

JNIEXPORT void JNICALL JFN(nativeMovieDone)(JNIEnv *env, jclass cls, jobject owner, jlong token, jboolean press_start) {
  (void)cls;
  pthread_mutex_lock(&A.mx);
  if (token && token == A.movie_token && !A.movie_done_ev &&
      A.movie_generation == atomic_load(&A.activity_generation) &&
      owner && A.activity && (*env)->IsSameObject(env, owner, A.activity)) {
    A.movie_done_ev = token;
    A.movie_start_ev = press_start != JNI_FALSE;
    pthread_cond_broadcast(&A.cv);
  }
  pthread_mutex_unlock(&A.mx);
}

JNIEXPORT void JNICALL JFN(nativePressStart)(JNIEnv *env, jclass cls) {
  pthread_mutex_lock(&A.mx);
  A.press_start = 1;
  pthread_mutex_unlock(&A.mx);
}

JNIEXPORT void JNICALL JFN(nativeMemoryWarning)(JNIEnv *env, jclass cls) {
  pthread_mutex_lock(&A.mx);
  A.memory_warning = 1;
  pthread_mutex_unlock(&A.mx);
}
