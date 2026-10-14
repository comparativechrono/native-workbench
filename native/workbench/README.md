# Native Workbench

Run bioinformatics tools locally on Windows through a native desktop application.
Choose files and folders, run a tool, or connect compatible tools into a branching
pipeline. Analysis data stays on the machine.

The small starter distribution includes **minimap2, SAMtools and BCFtools**.
Native **Tool setup** offers all 32 current packs through **Full**, or a smaller
**Custom** selection. Packs stay independently versioned; **Manage tools** also
supports approved signed catalogues and offline ZIP import.
The application does not require Docker, WSL or a system Python installation.

## Release status

[**0.16.0 is published as a development prerelease**](https://github.com/comparativechrono/workbench/releases/tag/app-v0.16.0).
It brings together readiness and diagnostics, sample batches and queues,
reusable indexes, verified restart, resource scheduling, portable projects,
reference management, and curated training workflows with native results.
The two synthetic workflows explain exact tool requirements and expected
answers. Results show recorded measurements, searchable analyses and useful
failure guidance without inventing sample QC pass thresholds.

The **17.85 MB Starter** (17,846,873 bytes) is a fresh installation. The separate
**13.20 MB updater** (13,199,905 bytes) upgrades published **0.11.0** while
preserving installed packs, saved settings/pins, setup state, results and
references. A fresh Starter includes the original align/bam/variants 0.4.0
packs and additional align 0.4.1 side by side. The updater leaves the additional
pack for explicit [offline ZIP import](https://github.com/comparativechrono/workbench/releases/download/app-v0.16.0/native-workbench-pack-align-0.4.1.zip).
The 32-pack Full/Custom profile and production trust remain unchanged.

The exact application passed its native candidate and release checks in ordinary
and space-containing Windows paths. The updater passed 18 checks per path,
verifying all 87 core files and preserving 204 existing files. A separate
four-check long-path gate passed the Starter chain and additional align
self-check with machine long-path opt-in disabled and restored afterward.
Native child working directories of 260 characters or more remain unsupported.

[Publication run 37955110070](https://github.com/comparativechrono/workbench/actions/runs/37955110070)
promoted the accepted application archives without rebuilding and verified all
13 public assets by anonymous download. Packaged source is
`e855dc4396e0c16ae35f4e840eb9cc734adb4441`; release/tooling source is recorded
separately. See the [release notes](docs/releases/0.16.0.md),
[release handover](knowledge/curated-workflows-0.16.0-release-handover.md) and
[public-download receipt](knowledge/evidence/curated-workflows-0.16.0-public-downloads-2026-10-09.json).

These are finite hosted Windows checks at 96 DPI. Representative PCs, physical
trackpads, high-DPI/multi-monitor displays, scientific Linux CWL validation,
realistic benchmarking, executable signing and institutional deployment remain
separate work. Synthetic truth is not biological or clinical validation.
Full downloads of all 32 optional packs were not repeated. Existing endpoint
security policies, including the reported Heimdal bridge block, remain an
organisation approval matter.

Results retain `workflow.cwl`, dependency diagrams, methods and provenance.
Separate CWL execution requires the documented engine, Python, matching packs
and inputs; normal Workbench operation gains no such dependency. See the
[CWL guide](knowledge/cwl-results.md) and
[current development status](knowledge/current-state.md).

## Using the application

Download the [0.16.0 Windows Starter ZIP](https://github.com/comparativechrono/workbench/releases/download/app-v0.16.0/native-workbench-0.16.0-starter-windows.zip),
extract it and run `NativeWorkbench.exe`. At first launch choose **Full**,
**Starter** or **Custom**. For Full or Custom, choose **Refresh catalogue**, review
the tools and download size, then choose **Install selection**. Starter works
without pack downloads. Use **File > Check installation** to check the target
machine. See the [tool setup guide](knowledge/tool-setup.md) for cancellation,
retry and offline use.

Use **Tools** for one operation, or switch to **Workflow** to add reusable input
cards and connect compatible tool ports. Input cards own the selected files;
tool cards own their options and connections. See the
[native interface guide](knowledge/native-ui.md).

Open **File → Curated workflows...** to review the synthetic training inputs,
expected answers and exact dependencies before loading an editable workflow.
Use **Results** to search recorded analyses, measurements, raw outputs and
failure guidance. See the [workflow/results guide](knowledge/curated-workflows-results.md).

Open **References** for Ensembl archive or NCBI RefSeq discovery, resumable
downloads, reviewed local-reference import and verified library relocation.
On **Downloaded**, select a reference and a compatible input, then choose
**Use for input**. The local library works offline; loading or running an
analysis does not start downloads. cDNA and ncRNA remain distinct products.
See the [reference-management guide](knowledge/reference-management.md).

To add more tools later, reopen **Tool setup** through **Manage tools**, or use
the manager's catalogue selection. For offline import, download the tool's
`native-workbench-pack-…zip` asset from the
[pack releases](https://github.com/comparativechrono/workbench/releases). In
Workbench, open **Manage tools**, choose **Import pack ZIP**, and select that ZIP.
The ZIP can be copied to an offline machine before importing; running the tool
does not require a network connection. The starter already includes the `align`,
`bam` and `variants` packs.

### More optional tools

These additions cover widely used QC, counting, interval and similarity-search
operations. They are independent downloads; installing one does not replace the bundled
starter tools. Installed packs use additional disk space.

| Pack | What it adds |
| --- | --- |
| [FastQC 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-fastqc-v1.0.0) | Single/paired FASTQ quality reports, including gzip inputs |
| [MultiQC 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-multiqc-v1.0.0) | Combine explicitly selected local FastQC, fastp, STAR, featureCounts and kallisto reports |
| [featureCounts 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-featurecounts-v1.0.0) | Count reads or paired fragments from an RNA BAM against matching GTF genes |
| [BEDTools 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-bedtools-v1.0.0) | Intersect, subtract, cover, sort/merge intervals and extract reference sequences |
| [NCBI BLAST+ 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-blast-v1.0.0) | Local BLASTN, BLASTP, BLASTX and TBLASTN searches against your own FASTA sequences |

Use [the pack guide](docs/popular-packs-2026-10.md) for supported inputs,
scientific choices, pipeline branches and resource requirements. Reports are
created locally; viewing an HTML report separately may require an approved
viewer. The desktop app does not launch a browser to run these tools.

### Annotation, expression, coverage and phylogenetics

These optional packs connect to existing tools without replacing the bundled
starter tools:

| Pack | What it adds |
| --- | --- |
| [SnpEff + SnpSift 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-snpeff-v1.0.0) | Local database construction, variant consequences, local VCF annotations and impact selection |
| [DESeq2 + tximport 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-deseq2-v1.0.0) | Bulk differential expression from raw counts, featureCounts or kallisto sample outputs |
| [mosdepth 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-mosdepth-v1.0.0) | Whole-reference and target-region BAM depth and breadth |
| [IQ-TREE 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-iqtree-v1.0.0) | Nucleotide/protein tree inference from alignments such as MUSCLE output |

All four passed their exact-final native Windows installation, graph and
scientific regressions in ordinary and space-containing paths. See the
[four-pack guide](docs/ANNOTATION-EXPRESSION-COVERAGE-PHYLOGENETICS.md) for compatible
connections, sample sheets, separate database resources and material limits.
Private runtimes are included. Matching source/evidence assets accompany the
releases; DESeq2 additionally requires its separate R-runtime source companion
when redistributing the complete corresponding sources.

### Metagenomic classification and abundance

| Pack | What it adds |
| --- | --- |
| [Kraken2 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-kraken2-v1.0.0) | Prepare/register a local database, then classify single or paired FASTQ reads |
| [Bracken 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-bracken-v1.0.0) | Reestimate taxonomic abundance from a Workbench classification record or explicitly declared external report |

Both exact-final archives passed native Windows installation, graph and
scientific gates in ordinary and space-containing paths, including a real
Kraken2-to-Bracken chain. Large databases are separate local resources: select an
existing database or prepare an already downloaded archive. The packs do not
download reference data during analysis. Bracken requires a model matching the
database and selected read length; paired report counts remain fragments.
See the [pipeline guide](docs/KRAKEN2-BRACKEN-PIPELINE.md) for setup, model
declarations, supported inputs and evidence limits.

### RNA-seq tools

Install [STAR 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-star-v1.0.0)
for splice-aware alignment and optional annotated gene counts, or
[kallisto 1.0.1](https://github.com/comparativechrono/workbench/releases/tag/pack-kallisto-v1.0.1)
for transcript quantification. Download the pack ZIP from its release and use
**Manage tools → Import pack ZIP**.

STAR needs a genomic FASTA, with a matching GTF for gene counts; kallisto needs
a transcript/cDNA FASTA or a reusable kallisto index. STAR requires uncompressed
inputs and rebuilds its index per run; kallisto accepts gzip inputs. See the
[RNA-seq guide](docs/rna-seq-packs.md) for compatible pipeline branches, resource
limits and interpretation of counts. Use kallisto 1.0.1 for the corrected
multithread bootstrap support; existing saved pipelines keep their original
pack version until explicitly updated.

### GATK germline tools

Install [GATK 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-gatk-v1.0.0)
for GATK **4.7.0.0** with its own Java 17 runtime. Its nine operations cover
duplicate marking, base-quality recalibration, HaplotypeCaller VCF/gVCF calling,
CombineGVCFs, GenotypeGVCFs, variant selection, filtering and validation. Run them
individually or connect sample branches into a joint-genotyping pipeline.

See the [GATK pack guide](docs/GATK-PACK.md) for inputs, scientific choices and
validation status. The exact final archive passed nine native scientific checks
and seven graph/archive contracts in both ordinary and space-containing Windows
paths. The existing Mutect2 pack remains the somatic calling interface.
GenomicsDB, Spark, VQSR and Python-dependent GATK tools
are outside this pack, and human whole-genome performance is not yet established.

### Updating an existing installation

For published **0.11.0**, use the
[0.16.0 updater](https://github.com/comparativechrono/workbench/releases/download/app-v0.16.0/native-workbench-0.16.0-update-from-0.11.0.zip).
Close Workbench, extract the updater outside the application folder, run
`UpdateWorkbench.exe`, and choose the existing `native-workbench` folder.
Installed packs, saved settings/workflow pins, setup state, results and reference
files are retained. Native CLI preservation passed in both Windows paths;
the interactive folder picker was not part of that automated gate.

This updater supports **published 0.11.0 only**, including installations with
additional packs; it does not target the unpublished 0.12–0.15 candidates.
Import the separate align 0.4.1 ZIP explicitly if reusable-index workflows need
it. Existing saved workflows keep their exact versions.

From 0.10.1, first use the
[0.11.0 updater](https://github.com/comparativechrono/workbench/releases/download/app-v0.11.0/native-workbench-0.11.0-update-from-0.10.1.zip).
From 0.10.0, first use the
[0.10.1 updater](https://github.com/comparativechrono/workbench/releases/download/app-v0.10.1/native-workbench-0.10.1-update-from-0.10.0.zip).
From 0.9.0, first use the
[0.10.0 updater](https://github.com/comparativechrono/workbench/releases/download/app-v0.10.0/native-workbench-0.10.0-update-from-0.9.0.zip).
Earlier 0.6.0 and 0.8.0 installations have updaters to 0.9.0 in the
[earlier release](docs/releases/0.9.0.md). There is no updater for 0.7.0:
retain that installation and extract the 0.16.0 Starter into a separate folder.
Extraction does not migrate data automatically. Do not overlay the Starter
onto an existing installation.

Saved pipelines retain exact pack versions and manifest hashes. Installing a
newer pack does not silently change an existing pipeline. Methods descriptions,
pipeline diagrams and execution records accompany results.

## Development and independent packs

Start with the [project knowledge base](knowledge/README.md) for the approach,
architecture, development methods, decisions, validation evidence and next steps.
Agents should first read [AGENTS.md](AGENTS.md).

This repository contains application source and pack development tools. Large
executables, private runtimes, third-party source archives and pack ZIPs belong
in release assets, not Git history. Application and pack tags can be released
independently in this repository; a second repository is not required.

- [Pack development](docs/pack-development-0.6.md)
- [Signed catalogue publishing](docs/catalogue-publishing-0.6.md)
- [Repository-specific publishing plan](docs/github-publication.md)
- [Source recovery](docs/source-recovery/README.md)

Some build and scientific test paths require the separately distributed runtime
and source companions. This checkout alone is not the complete third-party
build environment. Keep the matching source companions available alongside
binary releases.

The application license is in [LICENSE](LICENSE). Third-party tools and runtimes
retain their respective licenses and notices.
