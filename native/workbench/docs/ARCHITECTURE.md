# Prepared native computation with a host interface

The experiment tests whether a fixed Linux-compiled computational module can
execute through a small OS interface without a Linux kernel or CPU emulator.
It does not attempt an ELF compatibility layer for unmodified Linux programs.

## Compilation and loading

`fastq_module.c` compiles with GNU GCC's x86-64 System V convention, freestanding
code generation, position-independent code and red-zone use disabled. A linker
script places entry code at offset zero, followed by relative code and read-only
data. Mutable global data and BSS are rejected. The publication script rejects
nonrelative input relocations, final unresolved symbols/relocations, dynamic or
large stack frames and obvious raw system-entry instructions.

The final module is embedded as bytes in a read-only executable section of each
platform host. It is not copied into a dynamically executable allocation. Thus
the exact same verified computation bytes are available in the Linux ELF host
and the Windows PE host; host code and executable headers differ.

The Windows host marks module callbacks with `sysv_abi`. Compiler-generated
bridges reconcile calling conventions when the callback implementation invokes
Win32 APIs. The fixed-width ABI structure is 72 bytes and contains a version,
size, capabilities, context and function pointers. Entry and callback types are
in `include/bw_api.h`.

This controlled module has no Linux-specific thread-local variables, C++ stack
unwinding or large stack allocations. Supporting those in ordinary dependencies
would require more compiler/runtime work. A structural PE check alone does not
establish that these bridges work correctly on a native Windows machine.

## Host operations

- Input and output callbacks operate on already-open host streams. Short reads,
  partial writes, EOF and errors have explicit return conventions.
- Allocations belong to the host and are released through the matching callback.
- Parallel work is synchronous: all indexed tasks finish before return. Native
  POSIX threads or Windows threads execute the same module callback. If fewer
  worker threads can be started, the caller processes the remaining tasks.
- Cancellation is cooperative. Linux checks signal state around poll-based I/O;
  Windows checks an atomic flag and repeatedly cancels pending main-thread I/O.
- No nested parallel call, exception or longjmp across the ABI is supported.

The module's direct pointers and native instructions make it trusted code, not a
sandbox. Limiting the callback table does not prevent malicious code from
accessing host memory. Security isolation is a separate requirement.

## Files and results

Input bytes come from native file handles. Path conversion belongs to the host:
Windows receives UTF-16 paths through native command-line/file-dialog APIs.
No Linux filesystem mount or duplicate dataset is necessary. Output files use
sibling temporary names and are published only after success without replacing
an existing destination. Pipes expose partial streams by their nature.

The independent workflow runner launches real seqtk and minimap2 processes,
connects their binary streams, records both statuses, and keeps paths as argument
arrays. It does not pass a concatenated command to a shell. Its Python dependency
is for developer validation; the custom Windows stats preview runs directly.

## What would make a new runtime worthwhile

The experimental program has deliberately been written to a compact portable
interface. Automatically adapting an existing Linux package graph to that
interface is not implemented. A credible follow-on study would need to retain
Linux-oriented build convenience while resolving libc, TLS, mmap, futex, fork,
plugin and signal expectations across dependencies.

The existing Cosmopolitan baseline already rebuilt two real tools with zero
source patches. A new runtime must improve dependency coverage, porting effort
or demonstrated performance over that baseline. Producing a small standalone
executable alone is insufficient evidence of a new OS technique.

Relevant upstream foundations:

- https://github.com/jart/cosmopolitan
- https://github.com/wishstudio/flinux
- https://github.com/lkl/linux
- https://unikraft.github.io/loupe/
- https://learn.microsoft.com/en-us/cpp/build/stack-usage
