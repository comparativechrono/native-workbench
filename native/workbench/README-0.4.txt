NATIVE WORKBENCH 0.4.0 — EXPANDED WINDOWS PREVIEW

START HERE
1. Extract All into a new writable folder; keep your working 0.3 copy separately.
2. Double-click start-windows.cmd and click Check installation (34 checks).
3. The included small datasets exercise the new tools without a data download.
4. Please return windows-validation.json from the resulting check folder.
5. Try the wheel, resizing and scrolling with the window restored rather than
   maximised. This release still needs visual confirmation on your Windows PC.

Windows x86-64 is required. No Docker, WSL, administrator installation, separate
Python installation or network connection is needed to run the supplied tools.
Cutadapt uses its own bundled, isolated Python runtime. Nothing is uploaded by
the supplied workflows. Packs are trusted executable software, not a sandbox.

WHAT CHANGED
The wheel no longer draws a rectangular focus outline on mouse selection.
Keyboard navigation keeps a focus indication within the selected wedge.
Workflow descriptions, step counts and output summaries are measured and wrap;
long descriptions move into the scrolling form. Repainting and child-window
clipping have been revised to address the lines seen while scrolling. On very
small/high-DPI displays an outer scroll area keeps controls reachable.

The modular engine now supports hashed runtime assets, isolated Python tools,
and direct producer-to-consumer pipes. Both processes must succeed. Cancelling
a pipeline terminates both processes. Runtime files, inputs and completed
artifacts are protected and checked; each run records arguments and hashes.

TEN PACKS, 43 WORKFLOWS
Read quality: FASTQ statistics, quality profiles, reverse complement, pair checks.
Read alignment: minimap2 single-end and paired-end alignment.
Alignment files: SAMtools sort, fixmate, duplicate marking, merge, indexes, QC.
Variant tools: BCFtools likelihoods, calling, normalization, filtering, QC.
Variant pipeline: the original untrimmed 19-step baseline remains available.
Read trimming: Cutadapt paired, single-end and paired quality-only workflows.
fastp: paired adapter/quality trimming with local HTML and JSON reports.
BWA alignment: reference indexing and paired BWA-MEM alignment into BAM.
FreeBayes: variant calling from a prepared BAM.
Research variants: 12 complete configurable paired-read workflows.

Pinned tools: Cutadapt 5.2, fastp 1.3.7, BWA 0.7.19-r1273, minimap2 2.28-r1209,
SAMtools 1.24, BCFtools 1.24, FreeBayes 1.3.10, seqtk 1.4-r122, paircheck 1.0.1.
The earlier custom plain-FASTQ statistics module is also included.

USING THE RESEARCH PIPELINES
Select Research variants with the wheel or named selector. The workflow name
chooses Cutadapt (adapter+quality or quality-only) or fastp, BWA or minimap2,
and BCFtools or FreeBayes. Each combination is a declarative pack workflow.

Choose matching R1/R2 FASTQ files (plain or gzip), an uncompressed reference
FASTA, output folder, and biological sample/read-group/library/platform labels.
Adapters must come from the actual library preparation: enter the appropriate
R1/R2 sequences for adapter workflows. No adapter sequence is assumed. The
Cutadapt quality-only choices intentionally perform no adapter removal.

Set trimming, minimum length, alignment workers, sort memory, ploidy and caller
thresholds for your experiment. The defaults are starting settings, not evidence
that a sample is diploid or that a variant is reliable. The platform and library
metadata are entered by the user; they are not inferred from a filename.

The full workflow validates pairs, copies/indexes the reference, measures read
quality, trims reads, revalidates pairs, aligns directly into name-sorted BAM,
fixes mate information, coordinate-sorts and marks duplicates. It then indexes
the BAM, reports mapping/coverage metrics, calls variants, normalizes alleles,
applies soft filters, and produces indexed all-call and PASS-only VCFs plus QC.
Raw calls, intermediate files, logs and a run.json record remain available.

Cutadapt rejects both mates when either is too short. fastp retains orphan and
failed-read files for inspection; the full pipeline aligns only retained pairs.
fastp poly-G trimming and its memory-heavy duplication estimate are disabled;
SAMtools supplies alignment-based duplicate metrics later. Its HTML report
loads a bundled local Plotly file. Keep that file alongside the HTML report.
Duplicate-marked reads stay in the BAM; the supplied callers exclude duplicates
by default. UMI and amplicon libraries require a different validated policy.

SCOPE AND RESOURCES
This is a substantially expanded workflow for single-sample, paired short-read
germline SNPs and short indels, with uniform haploid or diploid calling. It is
not the entire variant-analysis ecosystem. Somatic, structural-variant, CNV,
long-read, cohort joint-calling, annotation and GATK workflows are not included.
Read docs/RESEARCH-WORKFLOWS.txt before interpreting calls.

SAMtools and BCFtools remain single-threaded because the pinned portable
HTSlib build has a known thread-pool compatibility problem. Trimming and
alignment workers are configurable. This limits throughput on larger datasets.
The yeast runs validate reproducibility, not human-genome accuracy or scale.

Streaming avoids large intermediate SAM and unsorted BAM files. Sorting still
needs scratch space, and the reference copy/indexes, retained BAM intermediates
and calls consume disk. BWA/minimap2 also need enough RAM for the reference.
Use a local disk with adequate free space. Sort-memory controls the SAMtools
sort budget; it does not cap the memory of every tool.

The small known-truth examples are unpacked in examples/variant-truth,
examples/trimming-truth and examples/fastp-truth. Reuse your previously supplied
university practical for larger runs; its full reads are not duplicated here.
Neither the organism name nor the earlier practical run confirms library
adapters, sample identity, ploidy or a ground-truth variant set.

VALIDATION STATUS
All 12 research combinations recovered the four known fixture variants and
genotypes with matching scientific BAM/VCF data in Linux and portable builds.
Including two full yeast-lane comparisons, all 28 final workflow runs passed.
Independent trimming oracles, malformed gzip checks, upstream tests and real
yeast-data comparisons are included in validation/. Results distinguish
portable binaries executed on Linux from execution on Windows.

Your successful 0.3 Windows checks establish the earlier execution path. The
new desktop, tools, Python runtime and pipe executor were cross-compiled and
reviewed here; native Windows execution still needs the built-in check. The
included process companion also checks streaming, failures, cancellation,
timeouts and overwrite refusal. Cross-compilation alone is not a Windows pass.

EXTENDING AND REBUILDING
Each pack declares its inputs, constraints, options, outputs, tools, runtime
assets and ordered copy/exec/pipe steps in pack.ini. A new prepared tool or
workflow does not require tool-specific GUI code. This is native software
porting and packaging; it does not execute arbitrary Linux applications.
See docs/PACK-FORMAT.txt for the schema and docs/BUILD-0.4.txt for rebuilding.

Corresponding application and tool source, pinned source archives, patches,
build scripts, licenses and reference executables are in
source/native-workbench-source.zip. That separate archive avoids expanding
development paths during ordinary Windows setup. Extract it to a short path
or a Linux workspace when rebuilding. Compiler toolchains are not included.
