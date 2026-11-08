/* Single-race opaque native trail streams. No filesystem/network access. */
#ifndef GHOST_RUNTIME_H
#define GHOST_RUNTIME_H
#include "ghost_format.h"

#define GHOST_INPUT_TOKEN "@ghost/validated-input"
#define GHOST_OUTPUT_TOKEN "@ghost/record-output"
#define GHOST_INPUT_HANDLE UINT32_C(0x47480001)
#define GHOST_OUTPUT_HANDLE UINT32_C(0x47480002)

/* Copies the fully validated native input; failure discards every prior race.
 * The policy's callback/context must remain valid until clear. */
ghost_format_result ghost_runtime_prepare(const void *data, size_t size,
                                          const ghost_format_policy *policy);
/* Legacy local crowns may end at the line. Extend only the owned playback
 * stream, using the last recorded motion and native road coordinates. */
void ghost_runtime_extend_crown(float goal_mm, uint32_t runout_ticks);
/* Only explicit Ghost sessions may call begin. Challenge recording is optional.
 * Qualification sessions have a distinct entry, never an implicit no-blob fallback. */
int ghost_runtime_begin(int record);
int ghost_runtime_begin_qualification(const ghost_format_policy *policy);
void ghost_runtime_stop(void);
void ghost_runtime_discard_recording(void);
void ghost_runtime_clear(void);
int ghost_runtime_active(void);
int ghost_runtime_recording(void);
const ghost_format_info *ghost_runtime_input_info(void);
/* Read back one validated owned header ID without exposing mutable bytes. */
int ghost_runtime_input_area(uint32_t index, uint32_t *area);

/* Used solely by the private generated-physics bridge. Tokens are fixed host
 * capabilities: server strings never reach these functions. */
uint32_t ghost_runtime_open(int output);
int ghost_runtime_is_handle(uint32_t handle);
size_t ghost_runtime_read(uint32_t handle, void *output, size_t size, size_t count);
size_t ghost_runtime_write(uint32_t handle, const void *input, size_t size, size_t count);
void ghost_runtime_close(uint32_t handle);
int ghost_runtime_eof(uint32_t handle);
/* Returns 1 only after native Save closed a non-overflowed, revalidated stream.
 * A NULL destination is a size query; short buffers return 0 without copying.
 * No raw virtual-memory object or pointer is exported. */
int ghost_runtime_export(void *output, size_t capacity, size_t *bytes,
                         ghost_format_info *info);
#endif
