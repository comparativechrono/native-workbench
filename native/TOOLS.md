# The native tools copied from Native Workbench

Thirty-seven programs, as Native Workbench built them for Windows. The paths are in the build tree
(`native/workbench`, completed by `restore_build_tree.py`); upstream versions and hashes are in the scripts named.

## How the executables are made

| Kind | What it is | Runs on | Toolchain (pinned in `docs/BUILD-0.4.txt` and the scripts) |
| --- | --- | --- | --- |
| **Cosmopolitan** | one executable (APE) that runs on Windows, Linux and macOS | Windows, Linux, macOS (x86-64) | cosmocc 3.3.10, `https://cosmo.zip/pub/cosmocc/cosmocc-3.3.10.zip`, SHA-256 `00d61c12…a52439de` |
| **LLVM-MinGW** | a native Windows program, cross-compiled on Linux (`x86_64-w64-mingw32-clang`, `-static`) | Windows | llvm-mingw 20260922 UCRT, ubuntu-22.04 x86-64, SHA-256 `bb7bb765…c665c21` |
| **MSVC** | built with Visual Studio 2022 on a Windows runner | Windows | VS 2022 `/MT`, CMake 3.31.6 (BLAST only) |
| **Upstream** | the official Windows build, fetched and checked | Windows | — |
| **Java / Python / R** | a jar or script with a private runtime | Windows (as packaged) | Temurin JREs (8, 17, 21), CPython 3.13 embeddable, R 4.6.1 |

Every LLVM-MinGW recipe also has a `--linux` GCC build used as the scientific reference, checks the DLLs the
program imports, and writes its source changes as a unified diff against the pristine upstream archive.

## The programs

| # | Program | Version | Kind | Recipe | Windows changes and limits | Needs |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | seqtk | 1.4-r122 | Cosmopolitan | `baselines/build_upstream.py`, `vendor/provenance.json` | none | — |
| 2 | minimap2 | 2.28-r1209 | Cosmopolitan | `baselines/build_upstream.py`, `vendor/provenance.json` | none; mapping threads work | — |
| 3 | SAMtools | 1.24 (HTSlib 1.24) | Cosmopolitan | `build_variant.py`, `variant-provenance.json` | no `-@`: HTSlib's recursive mutex does not work with Cosmopolitan's condition variables; no bz2, lzma, curl, plugins | — |
| 4 | BCFtools | 1.24 | Cosmopolitan | `build_variant.py`, `variant-provenance.json` | no `--threads`, plugins, GSL or Perl filters | — |
| 5 | bwfastq | 0.1.0 (in-house) | freestanding module in an LLVM-MinGW host | `scripts/build.py`, `src/fastq_module.c`, `include/bw_api.h`, `platform_windows/`, `scripts/module.ld`, `scripts/module_embed.S` | plain FASTQ only | — |
| 6 | paircheck | 1.0.1 (in-house) | Cosmopolitan | `tools/paircheck.c`, `tools/build_paircheck.py` | — | — |
| 7 | BWA | 0.7.19-r1273 | Cosmopolitan | `tools/build_bwa.py`, `vendor-expanded/bwa/` | no source patch | — |
| 8 | FreeBayes | 1.3.10 | Cosmopolitan, with HTSlib 1.24 | `tools/build_freebayes.py`, `vendor-expanded/freebayes/compat/` | `off_t` for `__off64_t`; no backtrace; `llrintl` from musl | — |
| 9 | fastp | 1.3.7 | Cosmopolitan | `tools/build_fastp.py`, `tools/test_fastp.py`, `vendor-expanded/fastp-offline-report.patch`, `docs/fastp-report-fix/` | the report loads Plotly locally and escapes the command line | — |
| 10 | Cutadapt | 5.2 | Python (official cp313 wheels) | `tools/prepare_cutadapt.py`, `vendor-expanded/cutadapt/provenance.json` | none | Python |
| 11 | LoFreq | 2.1.5-workbench-port2 | Cosmopolitan | `tools/build_lofreq.py`, `scripts/prepare_lofreq_pack.py`, `vendor-expanded/lofreq/` | `lofreq filter` called directly, not through a shell; single thread; `uniq` off | SAMtools |
| 12 | HISAT2 | 2.2.3-workbench1 | LLVM-MinGW | `scripts/build_hisat2_native.py`, `vendor-expanded/hisat2/workbench1.patch` | 64-bit index builds only; ASCII paths without commas | SAMtools, paircheck |
| 13 | MUSCLE | 5.3-workbench1 | LLVM-MinGW + OpenMP | `scripts/build_muscle_windows.py`, `vendor-expanded/muscle-5.3/workbench1.patch` | ASCII paths; at most 15,000 residues | `libomp.dll` |
| 14 | Bowtie 2 | 2.5.5 | Upstream | `scripts/fetch_bowtie2_vendor.py` | ASCII paths without commas | — |
| 15 | SeqKit | 2.14.0 | Upstream (Go) | `scripts/fetch_seqkit_vendor.py` | an extra validation pass: upstream can exit 0 on bad input | — |
| 16 | VSEARCH | 2.32.0 | Upstream | `scripts/prepare_vsearch_pack.py` | short ASCII paths | `zlib1.dll`, `libbz2.dll` |
| 17 | VarDictJava | 1.8.3 | Java 8 + portable Perl | `scripts/fetch_vardict_vendor.py`, `scripts/prepare_vardict_pack.py`, `vendor-expanded/vardict/` | Java Fisher test in place of the R step; no SV calling | Java, Perl, SAMtools, BCFtools |
| 18 | GATK Mutect2 | 4.7.0.0-workbench1 | Java 17 + a compatibility jar | `scripts/fetch_mutect2_vendor.py`, `scripts/build_mutect2_compat.py`, `scripts/prepare_mutect2_pack.py`, `vendor-expanded/gatk-thirdparty/` | Windows path fix in `IOUtils`; JDK inflater, no snappy | Java, SAMtools, BCFtools |
| 19 | GATK germline | 4.7.0.0 | Java 17 | `scripts/fetch_gatk_build_inputs.py`, `scripts/prepare_gatk_pack.py`, `tools/gatk/WorkbenchGatk.java` | pure-Java PairHMM and Smith-Waterman | Java, SAMtools |
| 20 | BEDTools | 2.31.1-workbench1 | LLVM-MinGW | `scripts/build_bedtools_native.py`, `tools/bedtools/` | binary I/O, 64-bit integers, `_mkdir`, `asprintf`; ASCII paths | — |
| 21 | BLAST+ | 2.17.0 | MSVC | `scripts/build_blast_windows.ps1`, `tools/blast/`, `.github/workflows/blast-native-build.yml` | quoted database path; remote databases and GenBank loaders removed | — |
| 22 | Kraken2 | 2.17.2-workbench1 | LLVM-MinGW + OpenMP, Python wrapper | `scripts/fetch_kraken2_build_inputs.py`, `tools/kraken2/` | Win32 memory mapping; binary streams; no daemon; ASCII paths | `libomp.dll`, Python |
| 23 | Bracken | 3.1 | Python | `scripts/fetch_bracken_build_inputs.py`, `tools/bracken/` | no `bracken-build` | Python |
| 24 | DESeq2 + tximport | 1.52.0 / 1.40.0 | R 4.6.1 | `scripts/build_r_runtime_windows.py`, `scripts/fetch_deseq2_build_inputs.py`, `tools/deseq2/` | — | R |
| 25 | FastQC | 0.13.0 | Java 8 | `scripts/prepare_fastqc_pack.py`, `tools/fastqc/WorkbenchFastQC.java` | — | Java |
| 26 | featureCounts | Subread 2.1.1 | Upstream + LLVM-MinGW guard | `scripts/build_featurecounts_native.py`, `tools/featurecounts/guard.cpp` | ASCII paths | — |
| 27 | IQ-TREE | 3.1.4 | Upstream | `scripts/fetch_iqtree_build_inputs.py`, `tools/iqtree/` | ASCII install path; cmaple off | `libiomp5md.dll` |
| 28 | kallisto | 0.52.0-workbench2 | LLVM-MinGW | `scripts/build_kallisto_native.py`, `tools/kallisto/` | no AVX2 or HDF5; plaintext bootstrap; ASCII paths | — |
| 29 | mosdepth | 0.3.14-workbench1 | Nim compiled with LLVM-MinGW | `scripts/fetch_mosdepth_build_inputs.py`, `tools/mosdepth/` | precision fixed at 2; `REF_PATH` ignored | `libhts.dll` |
| 30 | MultiQC | 1.35 | Python + 57 wheels | `scripts/prepare_multiqc_pack.py`, `tools/multiqc/` | kaleido left out; network and subprocesses blocked | Python |
| 31 | SnpEff / SnpSift | 5.4c | Java 21 | `scripts/fetch_snpeff_build_inputs.py`, `tools/snpeff/` | relative `data` folder (a drive-path bug); `;` refused in paths | Java |
| 32 | STAR | 2.7.11b-workbench1 | LLVM-MinGW + OpenMP | `scripts/build_star_native.py`, `tools/star/` | no shared memory; plain FASTQ/FASTA; ASCII paths without commas; reads up to 650 bases | `libomp.dll` |
| 33 | Kalign | 3.5.1-workbench1 | LLVM-MinGW | `scripts/build_kalign_native.py`, `tools/kalign/` | explicit alphabet; 8 MiB stack | — |
| 34 | Primer3 | 2.6.1 | LLVM-MinGW | `scripts/build_primer3_native.py`, `tools/primer3/` | masker left out | — |
| 35 | PLINK 2 | 2.0.0-a.7.12 | LLVM-MinGW | `scripts/build_plink2_native.py`, `tools/plink2/` | no LAPACK or SSE4.2; one thread | — |
| 36 | Prodigal | 2.6.3-workbench1 | LLVM-MinGW | `scripts/build_prodigal_native.py`, `tools/prodigal/` | 14 overlapping-`sprintf` fixes | — |
| 37 | FastTree | 2.2.0 | LLVM-MinGW | `scripts/build_fasttree_native.py`, `tools/fasttree/` | built for baseline x86-64 (the official build needs AVX2) | — |

Native Workbench released 1 to 32 as packs; 33 to 37 are merged but were never released. `scripts/prepare_*_pack.py`
assemble the packs: native-workbench does not use packs, but these scripts list the files each program needs at run
time and its licences.

## Gaps

- **Runtime source archives that only the released packs hold**: SAMtools/HTSlib 1.24, Cosmopolitan 3.3.10, the
  LoFreq source subset, and the HISAT2, MUSCLE, Bowtie 2 and VSEARCH sources sit in the `licenses/` folders of
  Native Workbench's pack ZIPs. The upstream ones can be fetched again from the URLs in the provenance files; the LoFreq
  subset is restorable from `pack-lofreq-v0.5.3`.
- **The R runtime for DESeq2** exists only inside `native-workbench-pack-deseq2-1.0.0.zip`; its sources are in that
  release's `native-workbench-deseq2-1.0.0-r-runtime-sources.zip`. `scripts/build_r_runtime_windows.py` remakes it on a
  Windows runner.
- **GATK's runtime** was taken from the Mutect2 0.5.4 pack, and mosdepth's SAMtools from the 0.6.0 Starter.
- **BLAST's binaries** came from a CI artifact; rebuilding needs Visual Studio on a Windows runner.
- **Kalign, Primer3, PLINK 2, Prodigal and FastTree** were only ever CI artifacts (they expire on 12 November 2026);
  their recipes here are complete.
- **Five programs are fetched, not built** (Bowtie 2, SeqKit, VSEARCH, featureCounts, IQ-TREE).
- **Known recipe problems**: STAR's and kallisto's zlib pin pairs a zlib.net URL with the hash of GitHub's tarball, so
  `--fetch` probably fails for them; `tools/build_lofreq.py` expects `vendor-expanded/lofreq/cosmocc-3.3.10.zip` when no
  compiler is already unpacked.
