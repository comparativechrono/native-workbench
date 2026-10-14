# RNA-seq packs for Native Workbench

STAR and kallisto are independently installed packs for Native Workbench 0.6.0.
They extend the RNA alignment support already provided by the HISAT2 pack.
Install the selected pack ZIP through **Manage tools → Import pack ZIP**; do not
extract it into the application yourself. The application, starter packs and
existing saved pipelines do not need to be replaced.

## Choose the operation and reference

| Pack | Purpose | Reference inputs | Main results |
| --- | --- | --- | --- |
| STAR | Splice-aware alignment to a genome, with annotated gene counting when selected | Genomic FASTA; matching GTF for annotated operations | RNA SAM and coordinate-sorted BAM, BAM index, splice junctions, alignment summary and annotated gene counts |
| kallisto | Estimate transcript abundance from bulk RNA-seq | Transcript FASTA, or a compatible kallisto index made from it | Transcript estimated counts and TPM, run information and optional bootstrap estimates |

Use a genome and annotation from the same assembly and annotation release.
Chromosome names must match exactly. For kallisto, use transcript sequences
(such as an Ensembl cDNA FASTA), including the transcripts you intend to quantify.
A whole-genome FASTA is not a substitute for a transcriptome.

For kallisto, select the actual library strandedness. STAR writes all three
gene-count columns for you to select downstream. For single-end kallisto quantification,
provide the fragment-length mean and standard deviation appropriate to the
library; these cannot be reliably learned from the single reads alone. Read
length and fragment length are different quantities. Paired-end inputs must
contain matching mates in the same order.

## Build a pipeline

Each operation can run on its own. In the pipeline editor, connect compatible
FASTQ output from preprocessing to a STAR or kallisto read input. STAR 1.0.0
requires uncompressed FASTQ and FASTA; kallisto accepts plain or gzip-compressed
reads and transcript FASTA. A single uncompressed read
source can feed both tools as parallel branches. STAR consumes a genomic
reference; kallisto consumes a transcript reference, so the two branches use
different reference inputs.

kallisto also offers a separate index operation. Connect its index output to
quantification, or select an existing index file to reuse it across samples.
The combined index-and-quantify operations are convenient for an initial run.

The first STAR pack groups indexing with alignment and keeps its index inside
the run directory. Workbench 0.6.0 does not support reusable directory-valued
graph products, so these operations rebuild the STAR index for each run.
Allow for that time, memory and disk cost when planning multiple samples.

STAR alignments are explicitly typed as RNA alignments. They are not offered as
inputs to the existing DNA variant-calling and DNA preparation operations.
The generic index port in Workbench 0.6.0 cannot distinguish every index format;
the kallisto adapter checks the index version before quantification.

Review the generated methods description and parameters before running. Methods,
the DAG, executable versions, input hashes and execution records are retained
with the results. Saved pipelines pin the exact pack version and manifest.

## Interpret the outputs

STAR's annotated gene-count table reports separate unstranded and strand-specific
columns; choose the column appropriate to the library preparation. kallisto
reports transcript-level estimated counts and TPM. These are different analyses
and should not be compared as if they were the same count matrix. Differential
expression and transcript-to-gene aggregation need an appropriate downstream
analysis and experiment design.

Use **Check installation** to run the small, bundled synthetic scientific checks
after importing each pack. These checks establish expected behavior on those
fixtures; they do not benchmark a human genome or validate every RNA-seq protocol.
See each pack's README for supported input compression, path restrictions,
resource settings, build provenance and the exact validation evidence.

## Development and validation

The pack build and preparation scripts live under `scripts/`; their native
adapters and portability code live under `tools/star/` and `tools/kallisto/`.
Upstream algorithms remain in pinned upstream source. Build records retain the
source and executable hashes, dependency notices and local portability patches.

`tests/test_star_pack.py` and `tests/test_kallisto_pack.py` exercise the scientific
contracts. `tests/test_rnaseq_pipeline.py` checks both packs against an unmodified
released 0.6.0 application, including graph compatibility, saved version pins,
archive import and duplicate-version rejection.

The manually invoked **Native Windows pack check** GitHub workflow imports a
SHA-pinned candidate into the released Windows application and runs its declared
scientific checks in ordinary and space-containing paths. It only uses synthetic
pack fixtures and has read-only repository permissions. It does not publish
packs or require a catalogue signing key.

Upstream projects and manuals:

- [STAR](https://github.com/alexdobin/STAR)
- [kallisto](https://github.com/pachterlab/kallisto)
- [kallisto manual](https://pachterlab.github.io/kallisto/manual)
