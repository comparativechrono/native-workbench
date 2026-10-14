# Developing a scientific tool pack

Status: maintained handover, audited against repository commit
`1b537869e9d88e493078e1a1f241d16013273f44` on 2026-10-04.
Start with [the knowledge index](README.md); use
[validation and releases](validation-and-releases.md) before distribution.

## What a pack owns

A pack is a versioned, self-contained scientific tool or small group of related
operations. Indexing plus alignment can be one operation where the index cannot
yet be expressed as a reusable product. A pack owns executable dependencies,
declared commands, form fields, semantic input/output contracts, methods text,
citations, fixtures and scientific assertions. The application owns discovery,
the native interface, graph composition, validation, execution and reporting.
New operations using existing types should not require special cases in the UI.

The current publication layout uses **one GitHub repository with independent
application and pack release tags**. A second repository remains possible, but
is not required. This is the accepted decision in
[GitHub publication](../docs/github-publication.md) and the
[SDK guide](../docs/pack-development-0.6.md), superseding the original
two-repository suggestion.

Workbench does not make arbitrary Linux executables run on Windows. Select an
existing compatible build or build the actual upstream tool for Windows, using
the existing Cosmopolitan/APE or native Windows approach where appropriate.
Packing an ELF executable does not turn it into a Windows executable. Packs are
trusted executable software, **not a sandbox**. Hashes establish byte identity;
they do not prove a publisher is trustworthy or restrict a tool's behavior.

## A practical authoring sequence

1. Define the supported scientific operation and expected user inputs. Read the
   upstream documentation and inspect its license, dependencies and resource
   needs. Galaxy Tool Shed wrappers can suggest operations and tests; Workbench
   does not interpret Galaxy XML, Cheetah or dependency recipes.
2. Pin the upstream source archive/commit and dependencies. Retain the source
   hash, source URL, exact compiler, flags and all patches. Prove basic native
   execution before designing an elaborate wrapper around an unported tool.
3. Adapt the smallest necessary OS, build or I/O boundary. Preserve upstream
   scientific algorithms and expose unsupported features as explicit limitations.
   Record behavior changes, including stricter input rejection. Do not silently
   replace a difficult scientific tool with an approximation under its name.
4. Design explicit operation variants, ports and parameters. Make consequential
   biological choices visible; do not invent defaults requiring experimental
   knowledge. For example, single-end kallisto needs the library's fragment mean
   and standard deviation, not values inferred from read length.
5. Prepare the manifest, metadata, fixtures and known-answer checks. Include all
   runtime files and licenses. Keep build downloads separate from analysis;
   reference retrieval produces local inputs with provenance.
6. Compare scientific results with independent truth and a pinned upstream
   reference where feasible. Then run the graph, archive and native Windows
   gates in [the release procedure](validation-and-releases.md).

## The four contracts

| File or value | Contract | Authority |
| --- | --- | --- |
| `pack.ini`, `format=2` | Tools, assets, forms, output paths and ordered execution steps | Native manifest parser and runner |
| `workbench-schema.json`, `schema: 1` | Category, semantic ports, state requirements, methods, citations and supported constraints | `workspace/catalog.py` and graph engine |
| `workbench-checks.json`, `schema: 1` | Fixture bindings and bounded scientific assertions | `workspace/pack_checks.py` |
| `workbench-pack.json`, `schema: 1`, `packApi: 1` | Installable ZIP envelope: identity, compatibility and complete file inventory | Pack manager and release validator |

An installed pack normally contains `pack.ini`, `bin/`, pinned metadata and
fixtures, `licenses/` and an optional `PACK-README.md`. The ZIP contains
`workbench-pack.json` alongside the `pack/` tree. Every runtime file, including
DLLs, interpreter modules and configuration, must be a declared, SHA-256-pinned
tool or asset. An approved README and the license tree have special inventory
rules; they are still covered by the ZIP's complete file inventory.

`pack.ini` is execution authority. Metadata cannot add an executable or rewrite
arguments. Commands use indexed `arg.N` entries passed as individual arguments,
with `exec`, `pipe` and `copy` steps. There is no shell command field. Do not add
shell quotes around placeholders: the process launcher performs Windows argument
quoting. `{inputs:id}` expands a multiple-file field into separate arguments.
Private runtimes must be self-contained and must not write into the installed
pack or change PATH, the registry, global Python/Java, or other packs.

Detailed references:

- [Manifest format](../docs/PACK-FORMAT.txt), including placeholders, output
  ownership and process steps. Its title and historical UI ordering refer to
  0.4; use current source for later behavior.
- [Typed metadata guide](../docs/PACK-SCHEMA-0.5.2.txt) and
  [later scientific metadata extensions](../workspace/PACK-METADATA.md).
- [Current parser and registered types](../workspace/catalog.py),
  [engine](../workspace/engine.py), and
  [native pack model](../desktop/pack_model.cpp).

## Scientific meaning must survive graph composition

File extensions are insufficient. A genomic `reference` is distinct from
arbitrary nucleotide FASTA; protein sequences and alignments use separate types.
RNA `sam-rna`/`bam-rna` outputs do not implicitly connect to DNA `sam`/`bam`
preparation or variant-calling operations. Quantification tables are metrics,
not alignment or variant files. New registered types require a reviewed core
change and validation; packs cannot install their own global aliases.

Each manifest file input/output occurs exactly once in the metadata. Grouped
mate ports contain precisely read 1 and read 2 in that order, with one source
group. Multi-source ports use an actual manifest `files` input with explicit
cardinality. Graph compatibility does not establish valid FASTQ records or
matching mates: run a pinned pair/read validator where the tool depends on
positional pairing. `different-from` rejects the same physical input file,
including hard-link aliases; it does not establish different biological samples.

Declare only state supported by the operation: compression, alphabet, sorting,
pairing, mate repair, duplicate handling, abundance weights and filtering
selection, as applicable. `propagateStateFrom` expresses lineage, not a new
scientific guarantee. FASTA/FASTQ compression, reference/BAM consistency, sample
headers and BED/VCF resource contracts need their appropriate checks. Header
checks are not full-record validation or proof of experimental suitability.

Preserve legitimate empty biological outcomes with `nonempty=false` where
appropriate. A no-hit result must not be replaced with invented records. A
downstream operation requiring records should reject an empty input clearly.

Current limitations matter when designing new packs:

- The generic `index` type cannot distinguish every tool's index format.
  kallisto therefore verifies its supported index version in its adapter.
- Reusable directory-valued graph products are not supported by released 0.6.0.
  STAR 1.0.0 builds a private index inside each run rather than advertising a
  reusable index folder.
- Executable path limitations must be expressed as `pathPolicy` and rejected
  before execution. STAR requires ASCII paths without commas; kallisto requires
  ASCII paths; both support spaces. Do not solve this by guessing path escaping
  or silently moving a user's files.
- Resource settings are specific: STAR's SAMtools sorting memory does not cap
  STAR indexing/alignment RAM. Record practical resource needs without implying
  all workloads fit on a teaching laptop.

Methods text describes the operation and interpretation choices, not a claim of
successful completion. The frozen plan and results add exact versions, parameters,
commands, hashes, sources and citations. Preserve the distinction between planned
methods and successfully completed methods after branch failures.

## Versions and reproducibility

Application version, pack API, minimum application version, pack version and
upstream tool version are distinct. API 1 accepts three-part numeric pack
versions without prerelease/build suffixes. Tool versions may retain build
suffixes such as `0.52.0-workbench2`.

Increment the pack version when **any packaged bytes change**, including a
compiler-only rebuild, defaults, checks, documentation or license material.
Never replace published bytes under an existing `(pack ID, version)`. Preserve
stable IDs such as `align`, `bam` and `variants`; they are the established
Minimap2, SAMtools and BCFtools identities. Saved pipelines pin pack version and
manifest hash, so upgrades must coexist with old versions and must not silently
retarget saved workflows.

Keep source archives or immutable source references, patch files, dependency
notices, build commands, compiler identity, binary hashes and observed PE/DLL
imports. Publish the corresponding source required for each redistributed
component. A source URL, a file name, or an application source ZIP is not by
itself proof that all required tool source has been provided. Check what the
companion actually contains.

The repository intentionally excludes compiled tools, private runtimes and most
vendor archives. Follow [source recovery](../docs/source-recovery/README.md) and
its exact-hash inventories for historical builds. Recover inputs into a separate
tree; do not overwrite current app source with the old 0.5.4 source companion.
The RNA and later optional-pack source/evidence companions supplement that history.

## Starting a new pack

Use the [independent Seqtk example](../pack-examples/independent-pack/README.md)
as a format example, not as an already compiled or validated tool. With your own
pinned native executable, actual tool version, license and provenance, run from
the checkout root (PowerShell example):

```powershell
python pack-examples/independent-pack/prepare.py --tool-exe C:/build/seqtk.exe --tool-version 1.4-r122 --pack-version 1.0.0 --license C:/source/seqtk/LICENSE --provenance C:/build/provenance.json --output C:/build/example-seqtk-1.0.0
python scripts/package_split.py pack --pack-root C:/build/example-seqtk-1.0.0 --output C:/releases/example-seqtk-1.0.0.zip
python scripts/validate_pack_release.py C:/releases/example-seqtk-1.0.0.zip
```

Paths and the Seqtk version above are examples to replace with the actual build.
The last command is static integrity validation only. The preparer requires a
new/empty output location. Inspect its assertions, then replace them with truth
for the new operation rather than retaining the example's reverse-complement
answers.

Current limits include 1 GiB expanded per pack, 2,000 files and implied folders combined,
and 512 MiB per declared runtime file. The archive/import code rejects unsafe
paths, links, case collisions, extra files and hash changes. Keep license paths
shallow: nested source/license copies have previously exceeded Windows path
limits. Never weaken inventory/path checks simply to fit a larger package.

## Continuing the RNA builds

The current recipes are explicit but not yet a universal relocatable build
system. Inspect their constants before running them in a fresh checkout.

| Recipe | Required inputs and location assumptions |
| --- | --- |
| `scripts/build_star_native.py` | SHA-pinned STAR/zlib archives; sibling `rna-build/star` cache; sibling `toolchains/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64` |
| `scripts/prepare_star_pack.py` | Built STAR/OpenMP plus hash-pinned SAMtools and paircheck helpers; recovered helper license trees; emits `packs/star-1.0.0` |
| `scripts/build_kallisto_native.py` | Pinned kallisto/zlib; explicit `--cache` and `--toolchain` supported; emits `build-windows` or `build-linux` under cache |
| `scripts/prepare_kallisto_pack.py` | Matching native build record, patch, notices and toolchain; explicit `--vendor`, `--toolchain`, `--destination`; current pack version 1.0.1 |

For kallisto, a consistent cache avoids the older test-default cache path:

```sh
python3 scripts/build_kallisto_native.py --fetch --cache vendor-expanded/kallisto --toolchain /path/to/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64
python3 scripts/prepare_kallisto_pack.py --vendor vendor-expanded/kallisto --toolchain /path/to/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64
python3 scripts/build_kallisto_native.py --linux --cache vendor-expanded/kallisto
NW_KALLISTO_CACHE="$PWD/vendor-expanded/kallisto" python3 -m unittest discover -s tests -p test_kallisto_pack.py -v
```

The Linux build needs its host compiler; upstream-comparison tests also need the
SHA-pinned official Linux reference expected by the test. A skipped comparison
is not a passed comparison. `--fetch` retrieves build sources; it is not an
analysis-time network requirement. Native Windows tests remain a separate gate.

For STAR, after arranging the stated sibling toolchain and recovered helpers:

```sh
python3 scripts/build_star_native.py --fetch
python3 scripts/prepare_star_pack.py
python3 scripts/build_star_native.py --linux
python3 scripts/build_star_native.py --linux --upstream
python3 -m unittest discover -s tests -p test_star_pack.py -v
```

STAR's Linux test backend also requires the recovered APE loader/helper paths
described in the test source. Preparation may update local generated pack files;
use a disposable build tree, then package and validate its exact bytes. Neither
build command proves Windows execution. Build-time provenance deliberately
records that execution testing has not been performed; attach later validation
evidence separately instead of changing an already frozen release archive.

## Continuing the October optional packs

The [usage and selection guide](../docs/popular-packs-2026-10.md) records why
FastQC, MultiQC, featureCounts, BEDTools and BLAST+ were selected. These are a
practical shortlist of widely adopted missing capabilities, not a numerical
popularity ranking. Existing packs already cover the core DNA aligners/callers
and STAR/kallisto RNA operations; do not duplicate their identities.

| Pack | Build entry point and contract |
| --- | --- |
| FastQC | `scripts/prepare_fastqc_pack.py`; upstream jar plus private Temurin runtime and Java boundary adapter; [guide](../docs/FASTQC-PACK.md) |
| MultiQC | `scripts/prepare_multiqc_pack.py`; `tools/multiqc/windows-lock.json` pins private CPython and Windows wheels; [guide](../docs/MULTIQC-PACK.md) |
| featureCounts | `scripts/build_featurecounts_native.py` and `scripts/prepare_featurecounts_pack.py`; official Subread Windows binary plus compiled input guard; [guide](../docs/FEATURECOUNTS-PACK.md) |
| BEDTools | `scripts/build_bedtools_native.py` and `scripts/prepare_bedtools_pack.py`; LLVM/MinGW port and input guard, preserving upstream interval algorithms; [guide](../docs/BEDTOOLS-PACK.md) |
| BLAST+ | `scripts/build_blast_windows.ps1` and `scripts/prepare_blast_pack.py`; pinned NCBI/SQLite source with MSVC static runtime and bounded local-only/path fixes; [guide](../docs/BLAST-PACK.md) |

Read each recipe's explicit cache, destination, compiler and reference-build
requirements. Build commands are development-time network operations; prepared
packs require no download during analysis. Private Java/Python runtimes and
corresponding source make some optional packs much larger than the starter.
MultiQC keeps pinned wheels compressed inside the installed pack to meet the
file-count bound, then extracts into each private run directory. Preserve the
upstream wheel DLL loaders; repacking Python modules without their native
libraries can pass Linux tests while failing Windows imports.

BLAST's initial build and adapter-only CI/export records distinguish the unchanged
six upstream scientific binaries from its corrected Windows guard. Their GitHub
Actions artifacts can expire. Rebuild normally with
`scripts/build_blast_windows.ps1` from the public SHA-pinned NCBI/SQLite sources
and current guard, using the documented MSVC/CMake environment; do not require
an old run's artifact to remain downloadable. Release source/provenance companions
retain the exact source and build records needed to review the distributed bytes.

## Continuing GATK germline builds

GATK 1.0.0 adds nine operations independently of the existing Mutect2 0.5.4
identity. Both use upstream GATK 4.7.0.0 and its inherited Workbench local-path
adaptation. The [GATK guide](../docs/GATK-PACK.md) gives the complete recovery,
preparation, scientific-test and archive commands. `scripts/fetch_gatk_build_inputs.py`
recovers the SHA-pinned Mutect2 seed, Java compiler/reference runtime and released
application only when explicitly requested. `scripts/prepare_gatk_pack.py`
verifies the seed envelope, complete file inventory, upstream JAR and Linux
compiler; it requires a new output directory. It preserves the private Java 17
runtime and corresponding source/licensing materials while compiling only the
new boundary adapter. Never modify the published seed or final 1.0.0 bytes.

Keep the scientific contracts explicit:

- Coordinate-sorted DNA BAMs require one sample and an RG tag on every record
  resolving to a declared read group. Header-only checks missed a case where
  GATK silently discarded reads; retain the missing-RG regression.
- MarkDuplicates retains reads and disables optical-duplicate detection. BQSR
  trains on selected BED intervals using explicit known sites, then applies
  the model to the whole BAM. It does not invent a duplicate-marked state.
- Released 0.6.0 has no gVCF type. Labelled generic file ports preserve graph
  compatibility while keeping gVCFs incompatible with ordinary VCF ports.
  The adapter checks NON_REF likelihoods, sample names and duplicate inputs;
  arbitrary generic-file connections still need runtime role validation.
- A genotyped VCF can retain a NON_REF header even after its variants are
  removed by selection. Do not reject valid empty ordinary VCFs solely on that
  header. Nonempty reference-confidence records remain inappropriate for
  ordinary VCF operations; preserve the chained empty-subset regression.
- CombineGVCFs uses a real `files` port for two to 32 sources. Its successful
  merge does not establish GenomicsDB support or large-cohort performance.
- BAM preflight discovers executables used by workflows, not every tool merely
  declared in a manifest. The four BAM operations include real SAMtools
  quickcheck steps so the pack supplies its own pinned validation helper even
  when the installation gate restricts its catalogue to GATK.

The source/evidence companion includes a full knowledge snapshot and `AGENTS.md`.
Its historical pending-final status is superseded by the separate exact-final
Windows report, not by replacement archive bytes. The generic application
`build_sources` selection still needs its own reviewed handover-inclusion fix.

## Continuing annotation, expression, coverage and phylogenetics packs

The [four-pack overview](../docs/ANNOTATION-EXPRESSION-COVERAGE-PHYLOGENETICS.md)
connects these independently installable packs to existing tools. Their guides
and recipes are the authority for current pins and supported operations; this
section records maintenance contracts, not final release validation status.

| Pack | Preparation and scientific boundary |
| --- | --- |
| SnpEff | `scripts/fetch_snpeff_build_inputs.py`, `scripts/prepare_snpeff_pack.py`; private Java and upstream SnpEff/SnpSift; [guide](../docs/SNPEFF-PACK.md) |
| DESeq2 | `scripts/fetch_deseq2_build_inputs.py`, `scripts/prepare_deseq2_pack.py`; private Windows R, DESeq2 and tximport; [guide](../docs/DESEQ2-PACK.md) |
| mosdepth | `scripts/fetch_mosdepth_build_inputs.py`, `scripts/prepare_mosdepth_pack.py`; upstream coverage algorithm with documented boundary patches and its own SAMtools helper; [guide](../docs/MOSDEPTH-PACK.md) |
| IQ-TREE | `scripts/fetch_iqtree_build_inputs.py`, `scripts/prepare_iqtree_pack.py`; official native executable with a private Python input/output adapter; [guide](../docs/IQTREE-PACK.md) |

Retain these scientific distinctions:

- SnpEff executable packs and annotation database resources are separate.
  Database construction/conversion records explicit assembly and annotation
  release, the default genetic code and exact per-contig codon mappings. Do not
  infer a mitochondrial code from contig names or inherit unrelated assemblies'
  configuration. Preserve mappings when converting a downloaded database and
  when reloading the checked local resource ZIP. Ordinary VCF ports exclude
  gVCF records; local INFO annotation requires biallelic, normalized,
  assembly-matched inputs. Impact filtering selects whole records when any ANN
  entry matches; it does not remove other ALT alleles or declare pathogenicity.
- DESeq2 consumes raw integer gene counts or tximport-derived kallisto counts,
  never a table merely accepted because it has type `metrics`. Four to 64
  featureCounts/kallisto files use real fan-in; sample-sheet `input_index` binds
  each selected file in order. Keep explicit biological replicate identities,
  numerator/denominator, full-rank design and residual-degree-of-freedom guards.
  Counts and abundance roles remain runtime checks because released 0.6.0 has
  broad metrics types. Preserve realized sample names in the design matrix and
  the distinction between unshrunk estimates, filtering and significance.
- mosdepth stages and validates the same BAM bytes it executes. Coordinate
  sorting is required; RNA BAM acceptance means genomic depth, not expression.
  The primary summary aggregates upstream per-base depth over every `@SQ`
  reference base, including entirely uncovered contigs. Preserve the separately
  labelled raw upstream summary and its potentially different denominator.
  Target means use BED target bases. Proper-pair overlap handling, MAPQ/flag
  filters and CIGAR gaps must remain explicit; no base-quality threshold exists.
  Do not replace upstream coverage with a new read-counting implementation.
- IQ-TREE preserves distinct nucleotide/protein MSA types and rejects unsuitable
  aligned input before inference. Keep datatype-specific model choices, MFP/BIC
  selection and support settings in methods. The iterative Newick parser avoids
  recursion failure on ladder trees. Detailed JSON bipartitions stop above 256
  taxa to prevent quadratic summary output; the full Newick tree and upstream
  inference remain intact, with an explicit summary-omission flag. This pack
  does not expose partitioned/codon analyses or species-tree inference.

Recover private R on native Windows with
`scripts/build_r_runtime_windows.py` or the
[runtime recovery workflow](../.github/workflows/build-r-runtime.yml). Verify the
pinned official installer, relocation check, per-part inventory and reconstructed
runtime ZIP hash. This is build-time recovery, not an installer run on the user's
machine. The DESeq2 preparer binds the runtime to that provenance and retains
pinned package ZIPs. Analysis extracts hash-checked archives into each run's
private `_runtime`, uses `--vanilla` and private library paths, and never installs
packages into user libraries. Retained runs therefore include runtime disk cost.

Source completeness includes transitive native libraries and compiler runtimes,
not just the named tool. For DESeq2, the pack retains R/package/Python sources;
the separately published R-runtime source companion retains Rtools external
libraries, GCC/MinGW runtime sources, Tcl/Tk extensions, original notices and
matching R-project recipes/patches. Keep
`tools/deseq2/r-runtime-source-lock.json`, `r-runtime-source-archive.json` and
`prepare_runtime_sources.py` consistent with the actual companion and runtime.
The source closure includes the MXE CMake configuration/module/test subtree.
Use the documented base-only build target; upstream `build.sh` also builds an
unrelated full Rtools toolchain. See
[the source notes](../tools/deseq2/R-RUNTIME-SOURCES.md). Binary version strings
support version correspondence, not a claim of bit-identical recompilation.
Apply the same review to IQ-TREE's compiled-in Boost/Eigen/Rust dependencies and
SnpEff's Java dependencies; a large source ZIP alone proves no closure.

## Continuing Kraken2 and Bracken builds

The [pipeline guide](../docs/KRAKEN2-BRACKEN-PIPELINE.md) describes the two optional
packs, using Kraken2 2.17.2 and Bracken 3.1 source pins. Consult the
[Kraken2](../docs/KRAKEN2-PACK.md) and [Bracken](../docs/BRACKEN-PACK.md) guides for
their build commands and supported operations. This maintenance section records
contracts, not a completed release or native Windows validation claim.

Both packs include the same pinned
[`tools/metagenomics/resources.py`](../tools/metagenomics/resources.py) asset.
Keep its schema, copies, provenance and tests synchronized before freezing either
pack. The [resource specification](../docs/METAGENOMICS-RESOURCES.md) is the exact
field/API contract. Use ordinary `file` ports for database descriptors and
classification records; released 0.6.0 displays directory selectors but its graph
preparation still requires ordinary files. Do not add per-tool core branches or
weaken archive limits to accommodate databases.

Kraken registration selects `hash.k2d`, locates the other two index files,
inspects actual options and hashes the complete index/taxonomy/options identity.
The files remain in place. Validate cheap labels, source fields, model filenames
and declarations before a potentially long hash scan. Local archive preparation
uses the bounded streaming helper and an owned results child; default
classification-only mode skips model extraction. Explicit model preparation
requires the same database/read-length/standard-settings declaration as ordinary
registration. Preserve cleanup if subsequent scientific options inspection or
registration fails. Never unpack arbitrary archive members or follow links.

The resource descriptor records a content fingerprint, not publisher identity or
proof of model origin. Registration labels external models
`user-attested-external`. Only a separately verified construction can claim
`locally-built`. A classification record binds a sibling ordinary six-column
report to that fingerprint, settings, observed read lengths and read/fragment
counts. Bracken checks the descriptor, report and selected distribution; it does
not open or rehash enormous Kraken indexes it never consumes. Preserve the
lexical-only handling of unused database paths, including absent drives.

Retain the scientific boundaries:

- Kraken's paired classification and downstream report counts are fragments,
  one per pair. Bracken's model length is an individual read length, not insert
  size or the sum of mate lengths. Plain/gzip FASTQ validation and synchronized
  pairs must precede native classification.
- Bracken's recorded pipeline requires the supported standard classification
  model. Exact observed read lengths are the default; an explicitly selected
  representative length is an approximation, not a mixture model.
- External Bracken reports need explicit database/model, length and unit
  declarations. Keep user-attested provenance distinct from a hash-bound
  Workbench classification record; both remain user-editable evidence.
- Keep the upstream estimator unchanged, including thresholds, integer
  truncation and reestimated report contents. Fractions use upstream retained
  estimated abundance, excluding unclassified/unallocated observations, not all
  input reads or organism cell counts. A valid all-unclassified classification
  does not imply an estimable abundance table.
- Distribution checks must accept valid upstream zero-count terms and multiple
  contigs per genome while checking complete, consistent count denominators.
  Record changes between validation and execution as failures, including the
  descriptor/record themselves, not only scientific data files.

## Portability lessons to retain

- Preserve the fastp 0.4.1 reporting fix in `tools/build_fastp.py`. JSON command
  text must round-trip Windows backslashes, quotes and control characters exactly;
  syntactically valid JSON can still corrupt paths through `\t`, `\f` or `\u`
  escapes. HTML command/title text must be escaped as text. Charts use bundled
  Plotly without a CDN fallback or cloud-sharing controls. `tools/test_fastp.py`
  checks exact JSON/HTML round-trips, local script references and unchanged
  trimming truth. Its Linux tests using backslash-containing filenames do not
  claim that the Windows filesystem was exercised.
- Long-path imports previously failed inside nested license trees. Keep staging
  shallow, retain `native_path` handling and same-volume atomic publication in
  `desktop/packs.cpp`, and preserve the native long-path copy/duplicate-import
  regression in `desktop/modular_validation.cpp`. Shortening a test path alone
  would hide the fault; long-path-aware application code also does not guarantee
  that every third-party tool accepts long input/output paths.
- STAR default-parameter logging inspected `.good()` on an unopened stream. The
  libc++ Windows build could dereference a null stream buffer; the patch also
  requires `.is_open()`.
- STAR relied on implementation-defined `stringbuf.pubsetbuf` behavior. libc++
  ignored the external buffer, yielding empty alignments despite a zero exit
  status. `tools/star/WorkbenchBufferStream.h` supplies bounded external buffers;
  tests cover recycling, exact input lengths, seeks and overflow while retaining
  upstream mapping and counting algorithms.
- Generated version/header bytes must participate in the build cache signature.
  An unchanged executable after a source/version edit is not a successful new
  build. Check the runtime version and binary hash, not just the artifact name.
- kallisto 0.52.0's no-HDF5 branch omitted multithreaded plaintext bootstrap
  dispatch. The 1.0.1 pack invokes the existing upstream worker; it does not
  change sampling or abundance estimation. Tests exercise the actual two-thread
  default and requested bootstraps, including thread counts 1, 2 and 4.
- featureCounts Windows output uses CRLF. Scientific row assertions must allow
  the documented line-ending difference while still matching the complete row
  and exact number. Do not loosen a count assertion so expected `4` also accepts
  `40`. The CRLF regression is in `tests/test_featurecounts_pack.py`.
- The native runner precreates declared output parents. Upstream MultiQC treats
  an existing `multiqc_data` directory, even when empty, as a collision and
  renames outputs. `prepare_output_space` removes only the expected empty reserved
  directory; it rejects existing reports/nonempty directories and leaves force
  overwrite disabled. Test through the native runner and against actual FastQC
  output, not only hand-authored sample reports.
- FastQC treats basenames beginning with lowercase `stdin` as stream sentinels.
  The Java adapter rejects them before execution to prevent an apparent hang.
  Preserve the failure regression and explicit Phred offsets; an upstream
  diagnostic typo is not evidence that its Q40 calculation uses the wrong offset.
- BLAST's local search mode alone does not prevent network fallback during
  formatting or shared query loading. The bounded source patch removes those
  fallbacks and disables implicit GenBank loading; the guard disables usage
  reporting/configuration and rejects remote arguments. Exercise missing local
  databases, malformed FASTA and `-remote`/`-rid` failures. These checks establish
  selected code-path behavior, not an OS firewall or arbitrary-code sandbox.
  Keep the separate makeblastdb absolute database-name quoting fix for spaces.
- A Windows wrapper can produce valid result files while losing child process
  diagnostics. BLAST's guard used `CREATE_NO_WINDOW` without explicit standard
  handle inheritance, so the native failure regression could not see upstream
  errors. Pass the child's stdin/stdout/stderr deliberately with
  `STARTF_USESTDHANDLES`, and test captured failure diagnostics on Windows as well
  as successful scientific output. Five passing result-file fixtures alone did
  not cover this boundary.
- Freeze from the exact final pack folder and compare its entire inventory to
  the archive. A same-named discovery folder can be stale after an isolated fix.
  Do not mutate published candidate versions; create a new numeric candidate
  and record exact correspondence to the proposed final payload.
- R on Windows needs a space-free temporary path even when the pack and results
  support spaces. DESeq2 creates an owned child under user temporary storage and
  uses an existing Windows short-path alias when needed. The optional
  `scratch-root` directory provides an explicit writable space-free alternative.
  Remove only the owned child; preserve the selected parent. Do not introduce
  drive mappings, registry changes or administrator requirements to hide this.
- SnpEff's configuration parser treated a Windows drive-qualified `dataDir` as
  relative. Invoke `-dataDir data` from the existing private database working
  directory. Test real Windows drive paths and spaces; Linux absolute paths do
  not expose this parser boundary.
- IQ-TREE's adapter JSON must use explicit LF output on Windows. Native text
  fixture assertions inspect decoded bytes without universal-newline conversion.
  Keep the raw-byte regression as well as parsed scientific JSON assertions;
  valid JSON alone does not establish the declared output-byte contract.
- Preserve exact failing cases. Successful startup and a small one-thread test
  are insufficient evidence for a multithreaded scientific workflow.

These lessons are traceable to the build scripts, `tools/star/`,
`tools/kallisto/`, the corresponding October pack adapters/tests,
`tools/test_fastp.py`, `tests/test_star_pack.py`, `tests/test_kallisto_pack.py`,
[RNA usage documentation](../docs/rna-seq-packs.md) and release evidence.
