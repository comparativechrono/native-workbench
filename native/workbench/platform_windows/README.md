# Windows host for the native FASTQ experiment

The executable hosts a prepared, trusted x86-64 analysis module through `bw_api.h`.
The **same module bytes** are embedded in the Linux and Windows hosts. This does
not load arbitrary Linux binaries or Linux container images.

Build the module using the project build first, then run:

```sh
BW_MINGW_ROOT=/path/to/llvm-mingw bash platform_windows/build.sh
```

Alternatively set `BW_WINDOWS_CC` to an x86-64 MinGW GCC or Clang executable.
The build uses the MinGW C runtime and native Windows file, memory, thread, and
dialog APIs. It does not need an installed WSL distribution or hypervisor.

The toolchain used for the initial cross-build was official llvm-mingw
`20260922`, UCRT, Linux x86-64 host:

- Source: <https://github.com/mstorsjo/llvm-mingw/releases/tag/20260922>
- Archive: `llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64.tar.xz`
- SHA-256: `bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21`

On Windows:

```powershell
.\bwfastq.exe stats --input 'C:\Data\reads.fastq' --output 'C:\Data\stats.json' --threads 4
.\bwfastq.exe revcomp --input 'C:\Data\reads.fastq' --output 'C:\Data\reverse.fastq' --threads 4
.\bwfastq.exe --version
```

Pass `-` for input or output to use standard streams. Use `cmd.exe` or a shell
that preserves native byte streams when testing pipelines; older PowerShell
versions may convert pipeline data. All file paths are received as UTF-16 and
opened with Windows Unicode APIs. Only uncompressed FASTQ is accepted.

Running with no arguments opens native input and output file pickers for a
statistics run. Output files must not exist. A run first writes a sibling file
whose name contains `.partial.`. Only after successful analysis, flushing, and
closing is it renamed to the chosen output, without replacing an existing file.
A handled failure or cancellation removes the temporary file. A process crash
may leave the recognizable `.partial.` file; it is not a completed result.
Bytes already sent to stdout cannot be retracted.
Ctrl-C requests cancellation. Input and result-output callbacks first check that
request; a native watchdog then uses a 50 ms event wait between cancellation
attempts to cover a request arriving immediately before a blocking main-thread
read or write. The completion event stops the watchdog before its handles are
closed. This mechanism has been cross-compiled but still requires the native
Windows cancellation checks described below.
The module is part of the executable's read-only code section; the host
does not allocate or modify executable memory at runtime. Device policies can
still restrict whether this application may run.

## Validation boundary

A successful Linux cross-build and PE inspection establish that a Windows
executable was produced. They do **not** establish that it ran on Windows.
Native Windows execution, dialog behavior, Unicode paths, multithreading, pipe
handling, and cancellation must be checked on a Windows x64 machine before
claiming Windows runtime compatibility.
