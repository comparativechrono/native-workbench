# Annotation, expression, coverage and phylogenetics

These four optional packs extend existing Native Workbench workflows on Windows
x86-64. Each works with **Workbench 0.6.0**, independently or as part of a typed
pipeline. The application and its starter tools remain separate installations
from these optional downloads.

**Release status, 2026-10-04:** SnpEff, DESeq2, mosdepth and IQ-TREE 1.0.0 are published
and have passed exact-final native Windows installation, graph and scientific
regressions on the unchanged released 0.6.0 app, in ordinary and space-containing
paths. Consult each release's separate validation record for its tested bytes
and scope; native command-line gates do not establish desktop GUI acceptance.

| Pack and detailed guide | Operations | Release |
| --- | --- | --- |
| [SnpEff + SnpSift](SNPEFF-PACK.md), `snpeff` | Build a local annotation database; predict variant consequences; copy selected annotations from a local VCF; select a consequence impact | [pack-snpeff-v1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-snpeff-v1.0.0) |
| [DESeq2 + tximport](DESEQ2-PACK.md), `deseq2` | Differential gene expression from a raw count matrix, featureCounts tables, or kallisto abundances | [pack-deseq2-v1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-deseq2-v1.0.0) |
| [mosdepth](MOSDEPTH-PACK.md), `mosdepth` | Coverage across the complete BAM reference dictionary; target-region depth and breadth | [pack-mosdepth-v1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-mosdepth-v1.0.0) |
| [IQ-TREE](IQTREE-PACK.md), `iqtree` | Nucleotide or protein phylogenetic inference, model selection and optional branch support | [pack-iqtree-v1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-iqtree-v1.0.0) |

## Install and run locally

Download the selected release's
`native-workbench-pack-<id>-1.0.0.zip`. In Workbench choose **Manage tools → Import
pack ZIP**, then run **Check installation**. The downloaded ZIP can be transferred
to an offline computer. The signed online catalogue remains unconfigured; these
instructions use offline ZIP import. Keep the matching source and licence
materials when redistributing packs.

Each release supplies a matching source/evidence companion. DESeq2 also has a
separate `native-workbench-deseq2-1.0.0-r-runtime-sources.zip` asset containing
the Rtools/Tcl/Tk external-library sources and build recipes. It is part of the
corresponding-source set, not an installable pack or analysis-time download.
Follow [its source recovery notes](../tools/deseq2/R-RUNTIME-SOURCES.md) when
rebuilding or redistributing. Source companions preserve their creation-time
pending statements; the separate exact-final validation JSON closes those
statements without replacing immutable source archives.

SnpEff includes private Java; DESeq2 includes private R, contributed packages and
Python; IQ-TREE includes private Python; mosdepth supplies its native binaries
and helpers. Users do not install system runtimes, Docker or WSL, and analysis
does not launch a browser or upload data. DESeq2 extracts its runtime into each
run and may require a selected writable temporary folder without spaces when
Windows cannot provide a suitable short path. See its guide for that setting.

Choose an individual operation to save **tool settings**, or connect operations
to save a **pipeline**. Saved pipelines retain exact pack versions and manifest
pins. Review the planned methods and input sources before running; results retain
methods, the DAG and execution provenance.

## Useful connections

- **Variant VCF → SnpEff annotation → SnpSift impact selection.** Supply the
  matching local database resource to annotation. A database-building operation
  can feed several annotation branches. Ordinary small-variant VCF is supported;
  genotype gVCFs first. Impact selection retains an entire record when any
  allele/transcript annotation matches, including its other alleles and original
  FILTER labels. Consequences do not establish pathogenicity.
- **featureCounts or kallisto sample outputs → DESeq2.** Connect 4–64 distinct
  sample tables and supply a sample sheet with explicit groups and biological
  replicate identities. Its `input_index` maps each sample to the selected-file
  or connected-source position. Kallisto also requires a matching transcript-to-gene
  table. Specify the design and numerator/denominator contrast; at least two
  independent biological replicates per condition are required. Raw matrix mode
  matches sample IDs to column names. TPM, normalized counts and quantification
  bootstraps are not substitutes for raw counts or biological replication.
- **Coordinate-sorted BAM → mosdepth.** The same alignment can feed whole-reference
  and target-region branches, with selected summaries collected by Workbench's
  reporting operation. Targets require matching, sorted, nonoverlapping BED3/BED4
  intervals. The primary summary includes uncovered bases and empty contigs in
  its denominator; labelled raw upstream reports can have different totals.
- **MUSCLE alignment → IQ-TREE.** Connect nucleotide to nucleotide, or protein to
  protein. Choose model selection or a supported fixed model and, if needed,
  branch-support analysis. Different model settings can share one alignment at
  the same DAG level. The output is an unrooted Newick tree; interpretation and
  biological rooting remain the user's responsibility.

## Resources and material limits

A **tool pack ZIP** installs executable software. A SnpEff **database resource
ZIP** is a selected analysis input, built or prepared separately and reusable
across runs. It records assembly, annotation release, genetic codes and checksums.
No preselected human annotation database is bundled. The small synthetic database
is an installation fixture. Other reference and annotation files likewise remain
explicit local inputs; these packs do not provide an Ensembl browser or automatic
reference download.

Workbench 0.6.0 uses broad `metrics` types for expression tables and generic
`file` types for databases, depth products, PDFs and trees. A permitted connection
does not establish biological compatibility; pack adapters check their formats
and roles during execution.

DESeq2 supports bulk gene-level condition and additive batch-plus-condition
comparisons, with full-rank and residual-degree checks; paired, single-cell and
custom-formula analyses are outside this pack. Mosdepth aggregates all BAM samples,
has no base-quality filter, and measures genomic coverage even for RNA BAMs.
IQ-TREE requires already aligned, sufficiently informative sequences and exposes
neither partition/codon analysis nor species-tree inference. SnpEff local VCF
annotation requires normalized biallelic records and matching assemblies.

Use the individual guides for path restrictions, memory and disk needs, exact
versions and supported inputs. Thread settings do not impose a RAM cap. Synthetic
checks establish their stated software behavior; they do not establish
whole-genome performance, experimental adequacy, GUI acceptance or clinical
validation.
