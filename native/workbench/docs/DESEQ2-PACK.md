# DESeq2 and tximport pack 1.0.0

This optional Workbench 0.6.0 pack uses unmodified **DESeq2 1.52.0**, **tximport
1.40.0**, Bioconductor 3.23 and private **R 4.6.1** for local bulk RNA gene-level
differential expression. It also bundles isolated Python 3.13.16 to stage files
and launch R. Users do not install R, Python, packages, WSL or Docker. No analysis
uploads, automatic downloads, package installations or browser launches occur.
The archive is under development until the release records its final native gate.

## Operations and sample identity

- **Raw count matrix:** tab-separated `gene_id` followed by sample ID columns.
  Supply unnormalized, non-negative integer gene counts, never TPM, FPKM or
  normalized/rounded expression. Numeric checks cannot prove how counts arose.
- **featureCounts samples:** select 4–64 single-sample gene count tables, such as
  the `counts` output of Workbench featureCounts. Their genes, annotation
  coordinates and order must agree exactly. Assignment summaries are rejected.
- **kallisto samples:** select 4–64 `abundance.tsv` files from the same transcript
  reference and a `transcript_id` / `gene_id` mapping TSV. Every transcript must
  have one exact mapping; version suffixes are not stripped. Real tximport imports
  estimated counts, abundances and lengths with `countsFromAbundance="no"`;
  `DESeqDataSetFromTximport` retains transcript-length normalization offsets.
  Quantifier bootstrap files are not biological replicates and are not used.

Every operation requires a TSV sample sheet:

```text
sample_id	condition	biological_replicate	batch	input_index
control1	control	individual1	batch1	1
control2	control	individual2	batch2	2
treated1	treated	individual3	batch1	3
treated2	treated	individual4	batch2	4
```

These are tab-separated columns, not literal backslash-t characters. Matrix mode
matches `sample_id` to exact count column names. Multiple-file modes map
`input_index` to the **1-based selected-file/connected-source position**, each
exactly once. Confirm that order in the frozen plan. Input hashes and the realized
sample order are retained in results; matching basenames do not establish identity.
At least two globally distinct asserted biological replicate IDs per condition
are required; three or more are preferable. This cannot establish independence,
adequate power, or the correctness of sample metadata. Technical replicates must
be combined appropriately before use; paired/repeated measurements are unsupported.

Choose `condition` or additive `batch + condition`; batch adjustment needs at least
two batch levels, a full-rank design and at least two residual degrees of freedom.
Completely confounded designs fail. Continuous covariates, interactions and custom
R formulas are intentionally outside this version. Enter explicit numerator and
denominator condition labels: positive log2 fold change means higher expression
in the numerator. No label is guessed from a filename.

## Inference and outputs

DESeq2 uses serial Wald inference, median-of-ratios size-factor estimation,
parametric dispersion fitting with upstream fallback, Cook-distance filtering,
independent filtering and Benjamini–Hochberg adjustment. The chosen total-count
prefilter and FDR alpha are recorded. Automatic outlier count replacement is
disabled. Log2 fold changes are unshrunk maximum-likelihood estimates.

Outputs include all input genes with prefiltered/NA statuses preserved, normalized
counts of retained genes, imported counts, the actual design matrix, PCA and MA
PDFs, PCA coordinates, session information, methods, commands and input hashes.
PCA uses design-aware variance stabilization and up to 500 most-variable genes;
PCA/MA plots aid interpretation and are not automatic experimental acceptance tests.
This pack does not perform transcript-level differential expression, single-cell
analysis, enrichment analysis or clinical interpretation.

Released Workbench uses the broad `metrics` type for count/abundance tables. It
cannot statically distinguish every metrics file or TPM table. The adapter checks
the actual format, identifiers and values at execution; a graph connection alone
does not establish statistical compatibility. PDF outputs use generic `file` ports.

## Runtime, resources and reproducibility

The pack supports Windows x86-64 and ASCII paths, including spaces. It extracts
its hash-checked R and contributed-package ZIPs into **each run's private
`_runtime` folder**. This avoids the released application's pack-file-count limit
and never writes into installed packs or user R libraries. `--vanilla` and an
explicit private library path disable user/site startup files. Selected inputs
are copied and hashed before analysis; their source files are checked unchanged.
R requires a space-free temporary path. The adapter creates one unique private
child under the Windows user temporary directory and uses its existing short
Windows path alias when necessary. If no suitable alias exists, select an
existing writable **Temporary files folder** whose full path has no spaces.
Only the private child is deleted after R exits; the selected parent is preserved.
No drive mapping, registry edits or administrator privileges are used.
No shell or arbitrary R expression is accepted. This is trusted local code, not
an OS security sandbox; absence of network code is not a firewall guarantee.

Allow disk space for the private runtime in every retained run, plus input copies
and outputs. Large 64-sample analyses need substantial RAM; no hard process-memory
cap or large-cohort benchmark is claimed. At most 250,000 genes are accepted. The
uncompressed runtime plus packages are bounded during extraction. Use a short
local run directory if Windows path-length limits affect your installation.

`tools/deseq2/windows-lock.json` pins all upstream binary/source inputs, including
build-time LinkingTo dependencies. All contributed-package source tarballs and
original ZIP licences are retained; the R source release includes recommended
package sources. The complete private R runtime preserves its component notices.
Adapters and preparation recipes are MIT; upstream licenses remain authoritative.

The separate `native-workbench-deseq2-1.0.0-r-runtime-sources.zip` companion
contains corresponding Rtools45 external library and compiler-runtime sources,
Tcl/Tk bundle sources, and immutable R-project recipes and patches. It must be
published beside the pack. `tools/deseq2/r-runtime-source-archive.json` binds its
exact SHA-256 and byte count to the private R runtime, while
`r-runtime-source-lock.json` pins each of its 230 input files. The installed
pack retains these records and the source recovery script under `licenses/`.
This source download is separate so it does not increase the installed pack's
runtime footprint; an installed pack performs no source download during analysis.

## Build and validation

1. `python scripts/fetch_deseq2_build_inputs.py --cache build/deseq2-inputs`
2. On a disposable Windows builder, use the separately reviewed
   `scripts/build_r_runtime_windows.py --output NEW_DIRECTORY`. This verifies the
   official installer before a build-only private installation, removes generated
   uninstallers, tests relocated vanilla startup and exports a ZIP plus inventory.
   Reassemble exported parts and verify the recorded complete archive SHA-256.
3. `python scripts/prepare_deseq2_pack.py --cache build/deseq2-inputs --r-runtime-zip RUNTIME.zip --r-runtime-provenance PROVENANCE.json --destination NEW_PACK_DIRECTORY`
4. Package with `scripts/package_split.py pack`, statically validate with
   `scripts/validate_pack_release.py`, and run the exact archive through the
   released native Windows import/scientific gate in ordinary and spaced paths.
5. `python tests/test_deseq2_pack.py --pack INSTALLED_PACK --report evidence.json`
   executes the frozen native pack, compares all genes with an independent direct
   invocation of the pinned DESeq2 API, checks synthetic effect direction/FDR,
   count-source equivalence, designs, sample mapping, malformed inputs, startup
   isolation and unchanged installed/user files. It refuses Linux rather than
   reporting scientific skips as passes.

A separate three-transcript fixture is actual unmodified upstream kallisto 0.52.0
output from the released kallisto pack's synthetic reads. Its exact upstream
archive/executable/input/output hashes are retained; the gate checks tximport
counts, TPM and lengths without claiming differential inference on three genes.

The generated 300-gene/six-sample fixtures are deterministic artificial counts,
not reads and not a real-cohort sensitivity benchmark. Exact final native evidence,
artifact hashes and the source companion must be retained with a published release.
The fixture plants 12 positive and 12 negative effects. The pinned upstream
analysis reports 13 positive and 15 negative discoveries at adjusted P < 0.05,
including four incidental discoveries among the null genes; installation checks
use those observed deterministic totals. This does not calibrate empirical FDR.
The regression suite separately compares all six inferential columns for all
300 genes against direct DESeq2 matrix and tximport APIs at relative tolerance
1e-10. The tximport path centers normalization factors to geometric mean one,
whereas ordinary matrix size factors are not recentered; consequently its
normalized mean is not expected to be identical even for identical gene counts.

References: Love et al. (2014), doi:10.1186/s13059-014-0550-8;
Soneson et al. (2015), doi:10.12688/f1000research.7563.2.
