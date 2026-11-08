/* Bounded in-process original-asset media conversion. SPDX-License-Identifier: MIT */
#ifndef OC_MEDIA_H
#define OC_MEDIA_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define OC_MEDIA_ABI 1u
enum { OC_MEDIA_WAV_AAC = 1, OC_MEDIA_BINK_AVC_AAC = 2 };
enum { OC_MEDIA_OK = 0, OC_MEDIA_INVALID = -1, OC_MEDIA_CANCELLED = -2,
       OC_MEDIA_BUDGET = -3, OC_MEDIA_CODEC = -4, OC_MEDIA_IO = -5 };
typedef int (*oc_media_cancel)(void *opaque);
typedef struct {
    uint32_t abi, size;
    uint64_t max_input_bytes, max_output_bytes;
    uint64_t max_duration_ms, max_video_frames, max_wall_ms;
    uint32_t max_width, max_height;
    /* Deliberate preview truncation; 0 converts the complete shortest stream.
       Not a substitute for max_duration_ms, and never enabled implicitly. */
    uint32_t preview_duration_ms;
} oc_media_limits;
typedef struct {
    uint32_t abi, size;
    int32_t status, av_error;
    uint64_t output_bytes, video_frames, audio_samples, input_bytes_read;
    uint32_t width, height, sample_rate, channels;
    char message[256];
} oc_media_result;
/* All FDs remain caller-owned, seekable regular files. Input offsets are ignored;
   pread/pwrite preserve them. Output must be an empty O_EXCL-created job partial,
   never a published/old file. The caller must prevent concurrent writes/aliasing.
   WAV mode: source_fd=WAV, audio_fd=-1. Movie: source_fd=Bink, audio_fd=WAV BGM.
   No paths, shell, protocol, network, rename, unlink, truncate, or runtime compiler.
   A nonzero return leaves only the new output partial; caller publishes on 0 only.
   Synchronous callback must be thread-safe and return nonzero to cancel; keep it
   alive until return (ctypes CFUNCTYPE/JNI bridge). Checks occur in I/O, packet,
   frame and encode loops; one codec call cannot be preempted mid-call.
   Result and limits size must equal sizeof(current struct). */
int oc_media_convert_fd(int mode, int source_fd, int audio_fd, int output_fd,
                        const oc_media_limits *limits, oc_media_cancel cancel,
                        void *opaque, oc_media_result *result);
const char *oc_media_build_info(void);
#ifdef __cplusplus
}
#endif
#endif
