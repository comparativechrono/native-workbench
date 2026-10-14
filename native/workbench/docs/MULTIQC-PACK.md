# MultiQC local reporting pack 1.0.0

Requires Native Workbench 0.6.0 or newer on Windows x86-64. This pack runs the
real upstream MultiQC 1.35 with its own Python 3.13.16 and pinned dependencies.
No system Python, pip, browser launch, Docker, WSL or administrator setup is
needed. The optional pack is larger than a compiled single-tool pack because it
contains its private scientific Python dependencies.

## Supported operation

**MultiQC: compare QC reports** takes 1–64 explicitly selected local metrics
files, including branches of a Workbench pipeline:

- Original FastQC ZIP files, or extracted `fastqc_data.txt` files.
- fastp JSON reports.
- STAR final alignment summaries (`Log.final.out`).
- featureCounts assignment `.summary` files, including multiple BAM columns;
  each column receives a distinct label and its original label is retained.
- Captured kallisto quantification logs containing its processed/pseudoaligned
  read statistics. Upstream MultiQC does **not** read kallisto `run_info.json`
  or `abundance.tsv`; those existing outputs cannot substitute for the log.

Outputs are the self-contained interactive `multiqc_report.html`, upstream
`multiqc_data/multiqc_data.json`, general-statistics TSV and `report-inputs.json`
with original paths, hashes and display identities. The HTML can be opened
separately if workplace policy permits; creating reports does not open a browser.

Every selected report has its own `inputNNN_…` namespace. Different samples or
pipeline branches with the same original filename are not silently overwritten.
Different tools' reports are **not** assumed to represent the same biological
sample. For now they remain separate rows; use the source mapping to interpret
the comparison. Selecting identical report contents twice, including a FastQC
ZIP plus its extracted data, is rejected. These are reported QC metrics, not
recomputed reads or a clinical/experimental acceptance decision.

## Local execution and limits

Each input is limited to 64 MiB. Reports are staged in the private run directory;
source files and installed packs remain unchanged. Unknown/unparsed files fail
clearly. Whole-folder scanning, external plugins, custom configuration, arbitrary
HTML/custom-content reports, PDF/static images, AI summaries, uploads and remote
files are not exposed by this operation.

Automatic MultiQC configuration from home/current directories and environment
variables is disabled. Version checks and telemetry, cloud uploads and AI are
disabled. A Python audit hook rejects networking and external program launches.
The generated HTML includes a Content Security Policy that blocks connections
and external active resources; its plots, styling and fonts are bundled. Normal
citation hyperlinks remain explicit user navigation. These controls govern this
trusted adapter and are not a general sandbox for arbitrary executable packs.

Dependencies are preserved as original SHA-pinned Windows wheels to keep the
installed archive within Workbench's file-count bound. Each run unpacks them
into its private `report-runtime` directory without running installers or pip.
Allow approximately 1 GiB extra free disk space per report run. That directory
is retained with the run and can be removed after execution if disk space is
needed. Thread count is fixed at two for Polars; it is not a process RAM cap.
Kaleido/Chromium is omitted because only upstream interactive HTML plots are
enabled; no browser executable is included in the pack.

## Rebuilding and evidence

From a checkout with Python 3:

```sh
python3 scripts/prepare_multiqc_pack.py --fetch --cache /path/to/multiqc-cache
python3 scripts/package_split.py pack --pack-root packs/multiqc-1.0.0 --output /path/to/native-workbench-pack-multiqc-1.0.0.zip
python3 scripts/validate_pack_release.py /path/to/native-workbench-pack-multiqc-1.0.0.zip
```

`tools/multiqc/windows-lock.json` pins every runtime download and source
reference. Downloads are build-time only. The untouched MultiQC Python source
wheel and source archive, CPython source and embedded license, and dependency
wheel licenses/notices are retained. The adapter changes configuration and input
staging, not upstream QC statistics or plot calculations.

The installation check aggregates independently specified FastQC read counts,
STAR mapping metrics and kallisto pseudoalignment counts, retaining distinct
same-named samples. Source tests additionally cover duplicate and unsupported
inputs, hostile names, ZIP bounds, implicit configuration and network blocking.
Linux source execution and static archive checks do not prove native Windows
execution. Refer to the release's exact archive validation record for Windows
results, and run **File > Check installation** on the target machine.

Cite Ewels et al. (2016), Bioinformatics 32:3047–3048,
<https://doi.org/10.1093/bioinformatics/btw354>, plus the tools that produced the
original QC files. MultiQC is GPLv3-or-later; dependencies retain their own terms.
