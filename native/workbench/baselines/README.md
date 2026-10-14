# Upstream native portability baselines

These are real, unmodified upstream bioinformatics tools, rebuilt as compact
Cosmopolitan Actually Portable Executables (APE). This is a source-recompilation
baseline for the prototype; it does not run arbitrary pre-existing Linux ELF
binaries. The x86-64 portable binaries target Windows as well as Linux, but all
execution and comparisons reported here were performed on Linux x86-64.

| Artifact | Tool version | Bytes | Use |
| --- | --- | ---: | --- |
| `bin/seqtk-cosmo.exe` | seqtk 1.4-r122 | 430,226 | Portable reverse complement and other seqtk commands |
| `bin/minimap2-cosmo.exe` | minimap2 2.28-r1209 | 606,354 | Portable sequence alignment, including pthreads and SSE dispatch |
| `bin/ape-loader-linux` | From cosmocc 3.3.10 | See provenance | Explicit Linux APE loader; no system installation |
| `bin/seqtk-linux` | seqtk 1.4-r122 | 260,856 | GCC Linux reference, dynamically linked, debug information included |
| `bin/minimap2-linux` | minimap2 2.28-r1209 | 1,007,688 | GCC Linux reference, dynamically linked, debug information included |

The Windows `.exe` files do not require the Linux APE loader. Their original
portable bytes are preserved. The Linux and portable sizes above are not a
controlled size comparison: reference binaries include debug information and
use host shared libraries; portable executables include their runtime.

## Results

The sustained synthetic fixture uses a deterministic 2,000,000-base reference
and 200,000 reads of 150 bases each. Every seventh read has one substitution.
The FASTQ input is 63,100,000 bytes. The same data are used for all builds.

| Workload | GCC Linux median | Cosmopolitan median | Ratio |
| --- | ---: | ---: | ---: |
| `seqtk seq -r` | 0.1186 s | 0.4527 s | 3.82x |
| `minimap2 -ax sr -t 2` | 1.5410 s | 1.6347 s | 1.061x |

Each median contains three sequential runs on this execution host, including
process startup and output-file writes. These are observations for these builds
and fixtures, not Windows performance measurements. Compiler versions and C
libraries differ. The seqtk result shows that native machine code alone does
not guarantee equivalent I/O performance.

Both seqtk builds exactly match an independent Python reverse-complement
oracle, including reversed quality strings. Both minimap2 builds map all
200,000 reads and produce identical SAM after removal of the `@PG` line, whose
command path necessarily differs. Raw output hashes and individual timings are
in `results-200000/benchmark.json`. Peak RSS was not measured because
`/usr/bin/time` is absent; null fields explicitly represent that absence.

The smaller initial 10,000-read comparison also passed, together with alignment
of the upstream human and orangutan mitochondrial FASTA examples. Its report is
`results/benchmark.json`. This is limited output-equivalence evidence, not an
exhaustive validation of all commands, inputs or operating systems.

## Rebuild

The tool source archives, hashes, original license files and unpacked source are
under `../vendor`. Sources are seqtk tag `v1.4` and minimap2 tag `v2.28`.
**No upstream source patches were applied.** The portable build adds the bundled
zlib header path and omits `-lz`, because Cosmopolitan libc supplies zlib. It
keeps minimap2's normal SSE2/SSE4.1 dispatch and pthreads. Final `.exe` naming
requests APE output from the cross compiler.

From the `native-workbench` directory, on Linux with GCC, GNU make, development
headers for zlib and Python 3.12 or newer:

```sh
python baselines/build_upstream.py
```

For both portable and reference builds, download this pinned compiler archive:

```text
URL: https://cosmo.zip/pub/cosmocc/cosmocc-3.3.10.zip
SHA256: 00d61c1215667314f66e288c8285bae38cc6137fca083e5bba6c74e3a52439de
```

Then pass its local location; the script verifies its hash, extracts it within
`baselines/build`, and compiles both tools:

```sh
python baselines/build_upstream.py --toolchain-archive /path/to/cosmocc-3.3.10.zip
python baselines/benchmark_upstream.py --read-count 200000 --repetitions 3
```

An already verified, extracted compiler can instead be supplied with
`--cosmocc-root /path/to/cosmocc-3.3.10`. The default 10,000-read benchmark adds
the upstream mitochondrial comparison. The larger fixture and raw outputs can
be regenerated and need not be shipped; preserve the JSON reports. The compiler
archive, build directories and `.dbg` files are not required to run the tools.

## Licenses and provenance

`../vendor/provenance.json` records archive URLs and SHA256 values, compiler
identity, build differences and artifact hashes. `licenses` includes the two
upstream MIT licenses, the pinned Cosmopolitan license, the matching runtime
licenses and notices, and notices extracted from the linked executables. Some
notices are supplied as original upstream source files containing their license
headers. `licenses/provenance.json` maps these files to pinned upstream sources.

The matching APE loader source in tag 3.3.10 uses the ISC license. Nsync in the
linked runtime uses Apache 2.0, whose complete license is included. The compiler
toolchain itself is not bundled with the prototype; its README explains the
separate compiler and runtime licenses.
