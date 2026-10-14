# October 2026 tool-pack expansion

Selection reviewed on 2026-10-04. This batch adds **FastQC, MultiQC,
featureCounts, BEDTools and NCBI BLAST+** as independent optional packs for
Native Workbench 0.6.0. The starter still contains only minimap2, SAMtools and
BCFtools. Each new operation can run alone or participate in a compatible
user-built pipeline.

## Why these tools

There is no universal, comparable popularity ranking across bioinformatics
tools. Download counts, citations, public-server jobs and repository stars
measure different things. The selection uses documented adoption in maintained
community workflows and teaching material, then prioritises gaps in Workbench's
existing twenty-pack inventory. It is a practical first expansion, not a claim
that these are the five most-used tools in every field.

| Tool | Evidence of established use | Gap addressed in Workbench |
| --- | --- | --- |
| FastQC | [nf-core/rnaseq](https://nf-co.re/rnaseq/latest/) includes FastQC read QC; Galaxy's [sequence-analysis teaching material](https://training.galaxyproject.org/training-material/topics/sequence-analysis/) includes a dedicated QC practical. | Familiar per-file read-quality diagnostics, alongside the existing preprocessing tools. |
| MultiQC | nf-core/rnaseq presents its QC using MultiQC. Galaxy's [reference-based RNA-seq practical](https://training.galaxyproject.org/training-material/topics/transcriptomics/tutorials/ref-based/tutorial.html) aggregates featureCounts summaries with MultiQC. | A shared report can consume quality outputs from several branches. |
| featureCounts | The Galaxy RNA-seq practical explicitly connects STAR alignments to featureCounts. The [nf-core module](https://nf-co.re/modules/subread_featurecounts/) is reused by multiple sequencing workflows. | Explicit gene counting downstream of RNA alignments, with library-strandedness and read-versus-fragment choices. |
| BEDTools | The [nf-core intersect module](https://nf-co.re/modules/bedtools_intersect/) is reused across several assay types; nf-core/rnaseq also uses BEDTools for coverage processing. | General interval overlap, merging and reference-sequence extraction. |
| NCBI BLAST+ | Galaxy teaches [local BLAST+ searches](https://training.galaxyproject.org/training-material/topics/sequence-analysis/tutorials/ncbi-blast-against-the-madland/tutorial.html); nf-core maintains a [BLASTN module](https://nf-co.re/modules/blast_blastn/) used in viral and other sequence workflows. | Local nucleotide/protein sequence-similarity searches without uploading queries. |

These sources establish use and workflow relevance, not a numerical ranking or
endorsement of this Windows packaging. The operations exposed here are narrower
than each complete upstream command-line interface. For example, using BEDTools
as selection evidence does not mean this pack exposes every coverage or BAM
operation used by nf-core.

## Operations and scientific boundaries

| Pack | Operations and inputs | Results and important boundaries |
| --- | --- | --- |
| `fastqc` | Single or paired plain/gzip FASTQ. Validate the chosen Phred encoding and, for pairs, mate identity/order/count. | Separate upstream HTML, original ZIP, data and module-summary files for each mate. Reads are assessed, not trimmed. QC flags need experimental interpretation. A private Java runtime is included. |
| `multiqc` | Aggregate 1–64 local FastQC ZIP/data files, fastp JSON, STAR final summaries, featureCounts assignment summaries or captured kallisto quantification logs. | Combined HTML report, parsed data and source provenance. Feed a FastQC ZIP **or** its extracted data, not both for the same result. Filename namespaces prevent equal basenames from overwriting each other; they do not infer biological sample identity. kallisto `run_info.json` and abundance tables are not compatible substitutes for its log. |
| `featurecounts` | Single-end or paired-fragment RNA BAM plus a matching GTF. Choose unstranded, forward or reverse library preparation explicitly. | Gene counts and assignment summary. Paired mode counts fragments with both ends mapped and excludes chimeric pairs. One BAM per operation; combine separate summaries in MultiQC. Counts are not differential-expression results. |
| `bedtools` | Plain BED interval sorting, overlap selection, no-overlap selection, subtraction, merging, coverage and FASTA extraction; strand-aware selection/extraction requires BED6. | BED results, coverage metrics or nucleotide FASTA. Inputs use zero-based, half-open coordinates; match chromosome names and reference assembly. The initial interface supports BED3–BED6 and at most 1,000,000 records per input under the 0.6.0 core validator, not BED12 split blocks or arbitrary upstream formats. |
| `blast` | BLASTN, BLASTP, BLASTX and TBLASTN searches using local, uncompressed nucleotide/protein query and subject FASTA appropriate to the selected program. A private database is rebuilt for each run. | Tabular matches, labelled text and an ASN.1 archive. Translated searches require the appropriate genetic code. A similarity hit is not an automatic functional annotation or proof of orthology; no hits is a valid result. No query upload or remote-search mode is exposed. |

Read each installed pack's `PACK-README.md` for the exact pinned tool versions,
parameters, supported formats, compression and path restrictions. Graph types
catch many incompatible connections, but a compatible type does not establish
that two files use the same reference, sample or annotation release. Resource
needs remain those of the upstream software and selected datasets.

This batch pins FastQC **0.13.0**, MultiQC **1.35**, featureCounts **2.1.1**,
BEDTools **2.31.1-workbench1** and BLAST+ **2.17.0**. Pack versions are separate
from upstream versions. See the individual guides for
[FastQC](FASTQC-PACK.md), [MultiQC](MULTIQC-PACK.md),
[featureCounts](FEATURECOUNTS-PACK.md), [BEDTools](BEDTOOLS-PACK.md) and
[BLAST+](BLAST-PACK.md).

The featureCounts interface fixes a conservative counting policy: exon features
are grouped by `gene_id`; secondary alignments, NH-tagged multimappers and
ambiguous assignments are excluded, while duplicate flags alone do not discard
reads. Supplementary
alignments are rejected by the input guard so they cannot silently be double
counted. The exact policy and parameters belong in the generated methods and
must be reviewed for the experiment. Workbench does not infer the library's
strandedness from its filenames.

## Compose useful pipelines

**Read QC with a combined report:** add one FastQC operation per sample or read
pair, then connect its original FastQC ZIP outputs to a MultiQC aggregation
step. Separate QC nodes are siblings in the DAG; MultiQC depends on their
outputs. A paired FastQC node supplies separate reports for each mate. The
reported names preserve input identity instead of silently merging equal file
basenames.

**RNA alignment and gene counts:** connect a STAR RNA BAM output to the matching
single-end or paired featureCounts operation, and choose a GTF from the same
assembly. Connect the featureCounts assignment summary and supported alignment
logs to MultiQC. The RNA type intentionally prevents a DNA BAM workflow being
silently treated as splice-aware RNA analysis. Selecting paired counting for a
declared single-end alignment is also rejected. The earlier HISAT2 pack exposes
RNA alignments, but compatibility with a particular workflow should be checked
against its declared pairing state and the counting pack's input requirements.

**Intervals to sequence search:** extract nucleotide sequences from a reference
FASTA with BEDTools, then connect its nucleotide FASTA output to BLASTN's query
input and provide a local nucleotide subject FASTA. A nucleotide product is not
accepted by BLASTP's protein query input. Protein search requires protein input;
the mere presence of a `.fa` suffix does not determine sequence type.
The extraction-to-BLAST example uses the ordinary `getfasta` operation and
distinct intervals with unique coordinate identifiers. Repeated identical
intervals produce duplicate identifiers, and strand-labelled headers include
characters outside this first BLAST pack's identifier contract; those inputs
need deliberate identifier preparation before searching.

Review the methods preview before execution. The saved graph pins each pack
version and manifest, and completed runs retain methods, graph, settings and
input/output provenance. Independent DAG branches are currently scheduled in
dependency order rather than executed concurrently. Removing a step requires
reconnecting any consumers of its outputs before the pipeline can run again.

## Installation and reporting in restricted workplaces

Import the installable `native-workbench-pack-<id>-<version>.zip` through
**Manage tools → Import pack ZIP**, then run **Check installation**. The pack
contains its required executable/runtime dependencies; system Python, Java,
Docker or WSL are not needed. Pack downloads or installation media can be
transferred separately from the analysis data.

The native application remains the analysis interface. FastQC and MultiQC also
produce HTML files for inspection. Reading those interactive HTML reports needs
an approved HTML viewer; it does not require the application itself to launch
in a browser or start a web server. Machine-readable report data are also
retained for environments where viewing HTML is restricted.

These optional runtime bundles can be considerably larger than the starter.
Only install the tools needed. Offline import verifies inventory integrity but
does not authenticate an unknown publisher. The signed online catalogue remains
a separate deployment step; see [catalogue publishing](catalogue-publishing-0.6.md).

## Validation and maintenance

Validation has distinct layers:

1. Per-pack scientific tests run known synthetic inputs through the real
   upstream tool and check informative outputs, rather than only exit codes.
   Linux reference execution is recorded as Linux evidence.
2. [`test_popular_pipeline.py`](../tests/test_popular_pipeline.py) checks the
   unmodified released 0.6.0 graph and Python archive-import contracts: QC
   fan-in, RNA counting, FASTA connections, incompatible inputs, pairing,
   explicit strandedness, saved pins and duplicate-version protection.
   It substitutes a Python copy callback for native folder publication and
   **does not execute scientific programs or a native Windows importer**.
3. The native Windows CI gate must import and execute the exact immutable pack
   archive with the released Windows bridge, including a path with spaces.
   Published release notes and evidence must identify the final archive hash
   and actual run result. An executable's PE header, a successful cross-build or
   a Linux test is not evidence of Windows execution.

On **2026-10-04**, all **eight released-application graph/import checks passed**
on Linux against the five frozen 1.0.0 pack archives, with no skipped checks.
Every imported payload matched the exact folder used for graph discovery;
duplicate imports preserved installed files and receipts. This includes the
corrected featureCounts, MultiQC and BLAST archives, not their earlier
development folders. The separate report records `nativeWindowsExecuted: false`,
`scientificExecutablesExecuted: false` and `nativeImporterExecuted: false`.

Recorded native evidence on **2026-10-04**:

| Pack 1.0.0 | Exact final archive gate | Scope per installation path |
| --- | --- | --- |
| [FastQC](https://github.com/comparativechrono/workbench/releases/tag/pack-fastqc-v1.0.0) | [Passed: 37207251061](https://github.com/comparativechrono/workbench/actions/runs/37207251061) | Two checks: plain single-end and gzip paired-end FASTQ; known read/base counts, length, GC and Q40 quality; two threads and offline HTML. |
| [BEDTools](https://github.com/comparativechrono/workbench/releases/tag/pack-bedtools-v1.0.0) | [Passed: 37207758617](https://github.com/comparativechrono/workbench/actions/runs/37207758617) | Fifteen checks: interval operations, empty overlap, Windows CRLF, 64-bit coordinates, coverage and forward/reverse-complement extraction. |
| [featureCounts](https://github.com/comparativechrono/workbench/releases/tag/pack-featurecounts-v1.0.0) | [Passed: 37208535793](https://github.com/comparativechrono/workbench/actions/runs/37208535793) | Six checks: single reads and paired fragments across all three strandedness modes; exact counts, assignment reasons and guard output; two threads. |
| [MultiQC](https://github.com/comparativechrono/workbench/releases/tag/pack-multiqc-v1.0.0) | [Passed: 37208730673](https://github.com/comparativechrono/workbench/actions/runs/37208730673) | One check aggregates six inputs through all five supported upstream parsers, with distinct same-named FastQC samples and both featureCounts columns. Numerical metrics and input identities are asserted. |
| [BLAST+](https://github.com/comparativechrono/workbench/releases/tag/pack-blast-v1.0.0) | [Passed: 37210341211](https://github.com/comparativechrono/workbench/actions/runs/37210341211) | Five scientific checks: known coordinates for BLASTN, BLASTP, BLASTX and TBLASTN, plus a valid no-hit result. Six additional local error-path checks cover missing databases, malformed FASTA, rejected remote flags and retained diagnostics; installed pack files remain unchanged. |

All five final gates above used the SHA-pinned released **0.6.0** starter,
its actual native bridge, and both ordinary and space-containing installation
paths. Import and duplicate-version rejection passed in both locations.
The matching `native-workbench-<id>-1.0.0-windows-validation.json` release asset
records archive/manifest hashes, workflow commits, assertions and limitations.
These are native command-line/bridge checks on Windows Server 2022, not a full
desktop GUI, arbitrary Unicode/long-path or institutional acceptance test.

Preserve early candidate failures as development evidence. featureCounts'
initial assertions needed to match its real Windows CRLF output; its scientific
executable and counting algorithm did not change. MultiQC's adapter needed to
accept the native runner's precreated empty output directory so that upstream
report filenames remained the declared filenames. BLAST's native launcher also
needed to forward child stdout/stderr explicitly so that failed local database
operations retained their diagnostic messages; its six scientific executables
were unchanged by that launcher correction. The corrected candidates and
final releases have their own identities; previously published bytes are not
replaced or silently promoted.

To rerun the graph gate, recover the checksummed 0.6.0 starter and STAR 1.0.0
dependency, prepare the five pack directories, and supply their exact-version
installable ZIPs. The test copies them into disposable applications and never
modifies the shared starter. Configuration is documented at the top of the test:

```sh
NW_POPULAR_STARTER_ZIP=/path/to/native-workbench-0.6.0-starter-windows.zip \
NW_POPULAR_STAR_ARCHIVE=/path/to/native-workbench-pack-star-1.0.0.zip \
NW_POPULAR_PACK_DIR=/path/to/packs \
NW_POPULAR_ARCHIVE_DIR=/path/to/installable-zips \
python3 tests/test_popular_pipeline.py --report /path/to/graph-contracts.json
```

Set `NW_POPULAR_<ID>_VERSION` when deliberately testing a future pack version.
Individual frozen artifacts can be selected with `NW_POPULAR_<ID>_PACK_DIR`
and `NW_POPULAR_<ID>_ARCHIVE`; a common staging directory is not required.
The JSON report records exact versions, manifests and archive hashes and marks
native/scientific execution as false. An absent prerequisite produces a skipped
suite and a non-success report, never a passing claim. Preserve scientific,
graph and Windows records separately so that future maintainers can see what
was actually exercised. None of these small software regressions establish
clinical fitness or performance on a whole human cohort.

Follow [pack development](../knowledge/pack-development.md) and
[validation and releases](../knowledge/validation-and-releases.md) when updating
these packs. Keep upstream algorithms and published pack identities intact,
retain matching source/licences, and issue a new pack version for changed bytes.

## Further candidates

Salmon, StringTie, DESeq2/edgeR, deepTools, Picard, SPAdes and Kraken2/Bracken
remain useful candidates for later review. Several appear in the same maintained
community workflows, but they require their own packaging, resource guidance,
typed contracts and scientific/native validation. Their mention here is a
backlog, not a claim that they are already available or a promise that every
upstream operation will fit the current pack schema.
