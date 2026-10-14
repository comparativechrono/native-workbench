# Desktop implementation and validation boundary

The 0.2 desktop is a Win32 C++17 program. It launches the same three tool binaries
that passed the user's initial Windows checks. The prepared-module host and the
upstream Cosmopolitan executables are separate implementation approaches; the
desktop unifies their user interaction without claiming a general Linux ABI.

## Components

- `desktop/gui.cpp`: native controls, file dialogs, background worker, queued UI
  events, cancellation controls, elapsed time and opening results.
- `desktop/runner.cpp`: argument quoting, restricted inherited handles, process
  Job Objects, binary pipe I/O, staged output publication and run records.
- `desktop/packs.cpp`: manifest parsing, native SHA-256, pack discovery and
  staged imports. See `TOOL-PACKS.md` for the exact format.
- `desktop/validation.cpp`: native test harness; no shell or interpreter.
- `desktop/common.cpp`: Unicode conversion, JSON escaping and filesystem helpers.

The UI owns its controls. A worker runs jobs, imports or validation and posts
messages back to the UI thread. Closing while busy requests cancellation and
waits for the worker's completion before destroying the window.

The runner supplies an explicit executable path and quotes argument values for
Windows process parsing. It does not concatenate a command for `cmd.exe` or
PowerShell. A child starts suspended, is assigned to a kill-on-close Job Object,
then resumes. Only its three standard stream handles are inherited. stdout and
stderr are drained in bounded alternating chunks. Output bytes go to a new file;
stderr bytes go to a log and a bounded, decoded GUI view. A file-write failure
fails the run even if the child would otherwise ignore its output error.

Cancellation terminates the Job Object. This is a deliberate stop, not a promise
that arbitrary tools get a graceful shutdown callback. No completed result is
reported after cancellation. The Job Object does not provide filesystem or
network isolation.

The publisher controls the tool build. Current pack definitions select versions
of the fixed three-tool contract. Supporting additional tools requires extending
the job definitions and validating their builds; it is not an implemented
arbitrary-package import feature.

## Validation evidence

The desktop was cross-compiled with the pinned llvm-mingw C++ compiler using
`-Wall -Wextra -Werror`. Its PE structure, imports, bundled tool hashes and package
layout are checked in the build environment. These checks cannot prove native
Windows UI behavior, high-DPI layout, cancellation timing or output performance.

The user supplied a screenshot showing all nine earlier PowerShell-harness
checks passing on Windows. Those checks exercised the unchanged three tool
executables. The new native **Check installation** button adds desktop-runner
and pack-management cases, including actual active-process cancellation. Its
results must come from a native Windows run; no such result is fabricated by
cross-compilation or source inspection.

The test harness only processes synthetic/example data. It creates a new report
folder and leaves it in place for inspection. A deliberate tampered-pack fixture
and a deliberate failed-job fixture may remain inside that test folder; they are
never installed into the application's normal `packs` directory.

## Deliberate limits

Only one analysis runs at a time. The GUI has no workflow editor, online package
registry, authentication, cloud component or automatic updater. Large-output
hashing adds an output read at completion. The runner currently polls its pipes
and no performance comparison has yet been made with a direct tool invocation
on Windows. Its progress indicator communicates activity, not work percentage.

Statistics still use the original strict FASTQ parser and line limits. Its
thread setting parallelizes individual very long reads; short-read statistics
do not become a parallel file parser. Minimap2 supplies the real threaded
alignment implementation. Neither successful test outputs nor prepared native
code imply complete scientific validation for every input and option.

## 0.2.1 path-length correction

A user run of 0.2.0 passed 16 of 17 native checks. The pack-import test hit a
legacy Windows path-length limit while copying the nested licence directory.
Declaring longPathAware alone depended on the machine's long-path policy.

The host's file and directory operations now normalize ordinary paths and pass
explicit extended-length paths to the Win32 filesystem APIs. Pack checks,
recursive copy, traversal, rename and cleanup all use this form. Display paths,
provenance records and arguments sent to analysis tools retain ordinary paths.
NUL handles and the intentional named-pipe cancellation fixture are unchanged.

The same import check creates private source/destination fixtures with licence
paths of at least 320 characters, verifies copied bytes and hashes, and repeats
duplicate-version protection. Three path-normalization assertions accompany
the existing quoting check. There are still 17 checks. No OS setting is changed,
and separate tools may retain their own input/executable path limitations.
