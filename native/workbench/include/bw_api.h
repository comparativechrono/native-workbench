#ifndef BW_API_H
#define BW_API_H
#include <stdint.h>
#include <stddef.h>
#if !defined(__x86_64__) && !defined(_M_X64)
#error This experiment requires x86-64
#endif
#if defined(__GNUC__) || defined(__clang__)
#define BW_ABI __attribute__((sysv_abi))
#else
#error Build the host with GCC or Clang with sysv_abi support
#endif
#define BW_ABI_VERSION 1u
#define BW_CAP_PARALLEL 1u
#define BW_MAX_LINE (16u * 1024u * 1024u)
typedef void (BW_ABI *bw_task)(void *task_context, uint32_t task_index);
typedef struct bw_host {
    uint32_t abi_version;
    uint32_t struct_size;
    uint64_t capabilities;
    void *context;
    int64_t (BW_ABI *read)(void *context, void *buffer, uint64_t capacity);
    int64_t (BW_ABI *write)(void *context, uint32_t stream, const void *buffer, uint64_t size);
    void *(BW_ABI *alloc)(void *context, uint64_t size);
    void (BW_ABI *free)(void *context, void *buffer);
    int32_t (BW_ABI *parallel_for)(void *context, uint32_t task_count, uint32_t max_threads, bw_task task, void *task_context);
    int32_t (BW_ABI *cancelled)(void *context);
} bw_host;
_Static_assert(sizeof(bw_host) == 72, "ABI struct size");
_Static_assert(offsetof(bw_host, read) == 24, "ABI callback offset");
typedef int32_t (BW_ABI *bw_entry_fn)(const bw_host *, uint32_t argc, const char *const *argv);
/* Entry argv: {"stats"|"revcomp", "1".."64"}. Exit: 0 success, 2 invalid FASTQ,
   3 host IO/allocation failure, 4 ABI/options unsupported, 130 cancelled.
   read: 0 EOF; negative error. write may be partial; streams 1 output, 2 errors.
   parallel_for is synchronous; each index executes once; return 0 on success.
   No nested parallel_for, exceptions or longjmp across the ABI.
   Modules are trusted native code, NOT a security sandbox. */
#endif
