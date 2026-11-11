#ifndef OA_NATIVE_H
#define OA_NATIVE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#if defined(__GNUC__)
#define OA_API __attribute__((visibility("default")))
#else
#define OA_API
#endif
#define OA_ABI_VERSION 1u
/* All sizes include the complete struct, all limits must be positive. Recipe is
 * deliberately fixed at size=256, rays=96: this backend does not downgrade AO.
 * max_heap_bytes caps all explicit parser/algorithm allocations including the
 * input snapshot and allocation-ledger headers, not allocator metadata, the two
 * small libc FILE objects or bounded libc qsort scratch/stack. It is not an RSS
 * cap; a worker process/memory policy is required for strict process isolation. */
typedef struct oa_limits {
  uint32_t struct_size, abi_version;
  uint64_t max_source_bytes, max_heap_bytes, max_output_bytes;
  uint64_t max_work_units, max_wall_ms, max_cpu_ms;
  uint32_t max_textures, max_chunks, max_batches, max_triangles, max_maps;
  uint32_t max_texture_dimension, size, rays;
} oa_limits;
/* Called synchronously on the invoking thread, at entry and every <=1024
 * instrumented math/parser units, and before/after bounded qsort/alloc/IO.
 * Return nonzero to cancel. Callback MUST NOT throw, longjmp, or reenter any
 * non-thread-safe application code; concurrent callback state must be atomic.
 * Recursive oa_bake_fd on the same thread returns OA_BUSY. Calls on separate
 * threads can run concurrently with independent state and disjoint output FDs. */
typedef int (*oa_cancel_fn)(void *user);
typedef struct oa_cancel { uint32_t struct_size; oa_cancel_fn poll; void *user; } oa_cancel;
enum oa_status {
  OA_OK=0, OA_INVALID_ARGUMENT=1, OA_BAD_FD=2, OA_BAD_WPK=3,
  OA_LIMIT=4, OA_CANCELLED=5, OA_IO=6, OA_BUSY=7, OA_NO_MEMORY=8,
  OA_INTERNAL=9
};
typedef struct oa_result {
  uint32_t struct_size, abi_version;
  int32_t status, system_errno;
  uint64_t source_bytes, output_bytes, heap_peak_bytes, work_units;
  uint64_t elapsed_wall_ms, elapsed_cpu_ms, allocations_live;
  uint32_t maps, triangles;
  char message[160];
} oa_result;
/* Optional native cancellation callback. The caller keeps a zero-initialized,
 * aligned uint32_t alive until its last worker returns. Once shared, access it
 * only through these functions. */
OA_API int oa_poll_stop(void *flag);
OA_API void oa_request_stop(uint32_t *flag);
OA_API void oa_default_limits(oa_limits *limits);
/* FD-only: never opens a path, unlinks, truncates, or closes caller FDs.
 * source/out must be different regular, seekable inodes. Output must be empty,
 * writable, non-append and caller MUST have created it with O_CREAT|O_EXCL.
 * O_EXCL cannot be proved from an existing FD: this is a calling obligation.
 * Caller grants exclusive ownership of both file contents for the duration;
 * source must remain immutable (including by other processes), out must not be
 * written concurrently. pread leaves source position unchanged. Output uses a
 * duplicated FD and consequently advances caller's output position.
 * On failure the caller owns any current partial output, with no rollback.
 * No input/output is fsync'ed; caller handles durability/atomic publication.
 * Result is required and must have struct_size set before entry. A successful
 * result has allocations_live=0. Time limits are cooperative, not hard process
 * deadlines: blocking OS IO, callback and libc qsort are not preempted.
 * Little-endian hosts only. ALL translation units require -fwrapv and
 * -fno-fast-math; legacy signed seed math needs wrap semantics. Numerical
 * profile 1 uses -ffp-contract=off; Android 1.35 explicitly selects profile 2
 * (-O2 -ffp-contract=on), with the same C ABI 1 and fixed 256/96 recipe.
 * See AO_NUMERICAL_PROFILE_135.md; do not mix these numerical profiles or call
 * profile 2 an ABI revision. qsort/libm variation still requires Android proof.
 */
OA_API int oa_bake_fd(int source_fd, int out_fd, const oa_limits *limits,
                      const oa_cancel *cancel, oa_result *result);
#ifdef __cplusplus
}
#endif
#endif
