# Native Workbench — feasibility prototype

A local bioinformatics portability experiment for x86-64 Windows and Linux.
This package contains actual executables, source code, reproducible experiments
and measured results. It is a research preview, not a finished replacement for
WSL or a general Linux-binary runtime.

**Execution was tested on Linux only. Windows executables were cross-compiled
and structurally inspected; native Windows execution is not yet verified.**

## Try the Windows preview

1. Extract the ZIP into a writable folder.
2. Open `bin/windows/bwfastq.exe` (or `START-WINDOWS.cmd`).
3. Select an uncompressed FASTQ, then a new output JSON filename.
4. For a known small example, choose `examples/tiny.fastq` and compare the result
   with `examples/tiny.expected.json`.

This is a minimal native file-picker interface for FASTQ statistics. It is not a
complete tool catalogue or pipeline editor. The executable uses ordinary Windows
file/thread APIs and the Windows C runtime. Its computation is embedded in the
executable; it does not boot Linux, start a VM, download dependencies, or allocate
executable code at runtime. It is unsigned, so deployment must follow the
computer's normal application policy. Do not change organisational protections
to run the preview.

For a Windows smoke report, run `CHECK-WINDOWS.cmd` if local script policy permits.
It calls `scripts/validate_windows.ps1` without overriding execution policy.
The report is written below `results/windows-<unique-id>/windows-validation.json`.
No report is uploaded. That harness checks native execution, output values,
Unicode paths, long-read parallel computation, malformed input, overwrite
protection and the two upstream portable tools. It does not establish Windows
pipe/cancellation correctness or replace broader deployment testing.

Command-line examples in PowerShell:

```powershell
.\bin\windows\bwfastq.exe stats --input .\examples\tiny.fastq --output .\stats.json
.\bin\windows\bwfastq.exe revcomp --input .\examples\tiny.fastq --output .\reverse.fastq
.\bin\portable\minimap2.exe -a -x sr -t 2 .\examples\reference.fa .\examples\reads.fastq
```

Existing output files are protected. Named outputs appear at their final name
only after completion. Handled errors/cancellation remove temporary output;
crashes may leave recognisable `.partial.*` files. Standard-output bytes already
sent through a pipe cannot be retracted.

## What was built

**Prepared-code experiment.** `src/fastq_module.c` is compiled once on Linux into
4,877 bytes of position-independent x86-64 code and read-only data. The exact same
bytes are linked into Linux and Windows hosts. A small, versioned function table
provides input, output, allocation, cancellation and native parallel work.
The publisher performs compilation/linking; end users run a normal executable.
There is no runtime instruction interpreter or guest kernel.

This establishes a narrow tool-module interface, not the Linux syscall ABI.
The demonstration tool was written for this interface. Loading an arbitrary
Ubuntu executable, glibc, Python environment or Docker image is not implemented.
A Linux-package-to-module conversion pipeline remains research work.

**Practical portability baseline.** Unmodified upstream seqtk 1.4 and minimap2
2.28 were also rebuilt with Cosmopolitan 3.3.10. Those portable `.exe` files are
included under `bin/portable`. They retain the upstream programs' CLI; minimap2
supports the tested two-thread alignment. All scientific equivalence and timing
measurements in this package were made on Linux, not Windows.

**Workflow experiment.** With Python 3 installed, a local runner connects seqtk
reverse-complement output directly to minimap2, as a binary pipe without a shell:

```sh
python scripts/run_workflow.py --input examples/reads.fastq --reference examples/reference.fa --output-dir my-new-run --threads 2 --backend portable
```

On Windows it launches the portable executables directly. On Linux it uses an
explicit included APE loader, requiring no system-loader installation. This
reverse-complement-and-align workflow is a plumbing demonstration, not a general
recommendation for read preprocessing. The runner writes logs and `run.json`,
records both exit statuses, and publishes SAM only if both stages succeed.

## Format and portability limits

The custom FASTQ tool accepts strict four-line, uncompressed FASTQ with ACGTN in
either case and printable Phred+33 qualities. Wrapped records, other IUPAC codes,
and gzip input are outside this prototype's contract. Each logical line is
limited to 16 MiB. The upstream tools have their own broader format contracts.

`--threads` exercises multiple workers only for a single custom-tool read of at
least 65,536 bases; ordinary short-read custom statistics are single-threaded.
Minimap2's real pthread implementation provides the practical aligner test.

Prepared modules currently require x86-64, small static stack frames, no libc
imports, mutable globals, TLS, exceptions or nonlocal jumps across the API.
Build gates check stack usage, entry layout, relocations and unresolved symbols.
These gates are useful constraints, not a proof of arbitrary binary portability.
Modules are trusted native code with access to host-process memory: the API is
not a security sandbox. This prototype has no Linux fork, signal, mmap or futex
compatibility implementation.

The tools and runner perform local processing. The custom runtime exposes no
network API; there is no updater or telemetry in the code. This is not an OS-level
network-isolation guarantee for arbitrary code or other programs synchronising
chosen folders. Original files are read directly, with no VM copy. The Python
runner hashes inputs separately for provenance, which adds an input read.

## Rebuild and repeat

On Linux x86-64 with GCC, GNU binutils and Python 3:

```sh
python scripts/build.py
python tests/generate_fixtures.py build/test-fixtures
python tests/run_correctness.py
python scripts/benchmark_module.py
```

The correctness suite regenerates about 100 MiB of edge-case fixtures when needed.
The benchmark generates a 63 MB synthetic input; these generated files are not
in the ZIP. Build the Windows host using the pinned llvm-mingw toolchain described
in `platform_windows/README.md`. Rebuild real upstream tools and repeat their
benchmarks using `baselines/README.md`. Compiler downloads are not bundled.

Read `docs/RESULTS.md` for measurements and decisions, `docs/ARCHITECTURE.md` for
the runtime boundary, and `results/` for machine-readable evidence. `manifest.json`
records SHA256 for distributable files. Own experimental source uses the MIT
license in `LICENSE`; third-party software retains its included licenses.
