# Feasibility results

## What the experiment establishes

The same 4,877-byte computational module is embedded in a Linux executable and
a Windows executable. It uses a small host function table instead of Linux
system calls. Linux execution is verified; Windows construction and the exact
embedded bytes are verified, but native Windows execution is still untested.

The stronger practical result is that unmodified seqtk and minimap2 source built
successfully with the existing Cosmopolitan runtime. Their portable executables
produced matching results on the tested Linux workloads. No new kernel was
needed. This is evidence for prepared native tool packs, not evidence that
arbitrary Ubuntu binaries can run unchanged or that a novel OS has been invented.

## Correctness and filesystem behavior

`results/correctness.json` records **187 passed checks and zero failures** across
the custom Linux prepared-module and direct-link hosts. Independent reference
algorithms and literal expected values cover FASTQ statistics, reverse
complement, long-read parallel work, line boundaries and malformed input.
Host checks include Unicode paths, partial I/O, pipes, cancellation, unchanged
inputs, existing-output protection and publication races.

Named outputs are created under a temporary sibling filename and published only
after success. Handled errors clean up the temporary file. Crashes can leave
recognisable partial files, and streamed output cannot be rolled back.

The two-stage example workflow produced identical SAM, apart from invocation
metadata, for the portable and Linux reference builds on 10,000 reads. Injecting
a producer failure with a successful consumer correctly failed the whole run
and published no output (`results/workflow.json`).

## Timings measured on Linux x86-64

These are shared-host, startup-inclusive wall-clock measurements. They are not
Windows predictions or broad performance claims. Compiler and runtime choices
differ for the upstream builds; the experiment does not isolate a slowdown's
cause. Peak memory was not measured.

| Experiment | Reference median | Portable/prepared median | Interpretation |
| --- | ---: | ---: | --- |
| Custom FASTQ statistics, 200,000 reads | 0.2601 s | 0.2418 s | Similar timings amid substantial run-to-run variation; no demonstrated speedup |
| seqtk reverse complement, 200,000 reads | 0.1186 s | 0.4527 s | Portable build took 3.82 times as long |
| minimap2 alignment, 200,000 reads, 2 threads | 1.5410 s | 1.6347 s | Portable build took about 6% longer |

The custom comparison uses the same compiled computational object and host
callbacks, with five interleaved measured runs after warmup. It tests embedding
and dispatch cost, not a Linux compatibility layer. Individual timings are in
`results/module-benchmark.json`.

Upstream comparisons use three runs per build on a deterministic 2 Mb reference
and 200,000 reads, each 150 bases long, with a substitution in every seventh
read. Both seqtk builds exactly match an independent Python oracle. Both
minimap2 builds map all 200,000 reads and match SAM after removing `@PG` lines.
The initial smaller test also checks upstream mitochondrial examples. See
`baselines/results-200000/benchmark.json` and `baselines/results/benchmark.json`.

## Executable sizes

| Artifact | Bytes |
| --- | ---: |
| Shared prepared computation | 4,877 |
| Custom Linux host including computation | 21,640 |
| Custom Windows host including computation | 26,624 |
| Portable seqtk including its runtime | 430,226 |
| Portable minimap2 including its runtime | 606,354 |

The custom hosts rely on OS facilities and host runtime libraries. The upstream
Linux reference builds contain debug information. Consequently these numbers
are artifact sizes, not a controlled comparison of total installed footprint.

## Remaining gates

1. Run `CHECK-WINDOWS.cmd` on native x86-64 Windows and inspect the generated
   JSON. Cross-compilation and PE inspection cannot prove runtime behavior.
   Windows pipes, Ctrl-C and corporate deployment need additional validation.
2. Profile the seqtk slowdown before claiming comparable performance. Add
   representative compressed input and larger real datasets with known answers.
3. Expand tool/dependency coverage before designing a general tool catalogue.
   Python/R environments, plugins, fork, Linux signals, TLS and arbitrary shared
   libraries are not supported by the custom module interface.
4. Build versioned packs, a full job interface and installation/update handling.
   The current Windows GUI is only an input/output picker for FASTQ statistics;
   the upstream tools remain command-line programs in this preview.

The present decision is to pursue publisher-prepared native tool packs, using
existing portability infrastructure where it works. Develop a new host ABI only
where it demonstrates better coverage, simpler preparation or better measured
performance. Automatic adaptation of Linux package graphs remains an open
engineering problem, not a completed part of this prototype.
