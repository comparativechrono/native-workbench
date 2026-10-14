# kallisto RNA-seq pack 1.0.1

Requires Native Workbench 0.6.0 or newer on 64-bit Windows. Import the pack ZIP in **Manage tools → Import pack ZIP**. No WSL, Docker, installed Python, network service or separate tool installation is required to run it.

The pack contains kallisto **0.52.0-workbench2**, built from upstream 0.52.0 with documented Windows portability fixes. Its five operations are:

- Build a transcriptome index once, then reuse its `transcripts.idx` file across samples.
- Quantify single-end reads using an existing index.
- Quantify paired-end reads using an existing index.
- Index and quantify single-end reads in one operation.
- Index and quantify paired-end reads in one operation.

Use a **transcript/cDNA FASTA**, such as the cDNA download from the appropriate Ensembl release. A genomic FASTA used for STAR alignment is not interchangeable with it. Sequence IDs must be unique. Record the reference release and retain the index's Workbench provenance. The index operation uses 31-base k-mers by default, with 25 and 21 available for shorter reads; reads shorter than k cannot contribute indexed k-mers. Indexes use kallisto format 13. Prefer indexes built by this pack and rebuild if in doubt. Other tools' index files are incompatible even though the pipeline editor uses a general index-file type.

Inputs can be plain or gzip-compressed FASTQ/FASTA. FASTQ structure, nucleotide symbols, quality lengths and printable Phred+33 values are validated; paired workflows also validate mate names, counts and order. Read 1 and read 2 must be the matching files from the same sample. The single-end workflow requires the library's **fragment-length mean and standard deviation**; these are not populated with guessed defaults and are not simply read lengths. They accept whole bases. Paired-end workflows estimate fragment lengths from the reads.

Choose the actual library strandedness: unstranded, FR (single read/read 1 follows the transcript strand), or RF (single read/read 1 opposes it). This setting is not inferred. CPU count, bootstrap count and seed are recorded in the methods and result provenance. `0` bootstraps disables resampling; bootstrap replicates estimate technical quantification uncertainty and do not replace biological replication.

Results include:

- `quant/abundance.tsv`: transcript identifier, length, effective length, estimated fragment count and TPM. Counts can be fractional when fragments are compatible with more than one transcript.
- `quant/run_info.json`: kallisto version, index version, processed and pseudoaligned fragment counts, arguments and run statistics.
- `quant/bootstrap-estimates.tsv`: every requested plaintext bootstrap table, unchanged except for a leading zero-based replicate column. With 0 bootstraps it contains the header only. The individual upstream `bs_abundance_N.tsv` files are also retained in the run folder.
- `read-check.json`: strict FASTQ validation summary.
- `transcripts.idx` when indexing is part of the operation.

Quantification outputs are typed as metrics, not DNA alignments or variant calls. This pack does not perform differential-expression analysis, gene-level aggregation, single-cell BUS processing, long-read quantification, sequence-bias correction or BAM generation. HDF5 is disabled; use the TSV outputs and plaintext bootstrap estimates. No external genomic D-list is supplied. Upstream abundance-estimation algorithms are unchanged.

Paths must contain ASCII characters; spaces are supported. The tools use individual arguments without a command shell. Transcriptome size and worker count determine resource needs; the thread setting does not cap RAM. Inputs are read locally and results are written in the new run folder. Data are not uploaded.

## Fix in 1.0.1

Version 1.0.1 fixes missing plaintext bootstrap output when more than one thread is selected. Upstream 0.52.0 accidentally compiled the multithreaded bootstrap dispatch only when HDF5 was enabled, although its existing worker supports plaintext. This build invokes that unchanged worker for plaintext without HDF5. Bootstrap seeds, sampling and estimation are unchanged. Version 1.0.0 still works with zero bootstraps or one thread; its requested-bootstrap runs with multiple threads fail explicitly because the expected files are absent. Existing 1.0.0 releases remain unchanged.

## Validation and reproducibility

**Check installation** uses the actual two-thread UI default and runs real single-end and paired-end quantification on included synthetic transcripts and gzipped reads. It checks exactly 20 pseudoaligned fragments, the known 12:6:2 transcript abundance ratio and 600000:300000:100000 TPM, plus requested bootstrap output and strict read validation. This is a scientific regression fixture, not an accuracy benchmark on experimental data. Source-build tests additionally compare the numeric estimates with the official Linux upstream release, check strandedness, ambiguous transcripts, malformed reads and reusable indexes. Native Windows validation is recorded separately in the release verification report; cross-compilation by itself is not proof of Windows execution.

The source tag, commit, archives, SHA-256 hashes, build flags, library notices and exact portability patch are retained under `licenses/`. Windows binaries link the runtime statically and need only Windows system DLLs; they target baseline x86-64 without requiring AVX or AVX2. Bootstrap draws may differ across compiler/platform standard libraries; the same seed is repeatable within the same pack build.

From the source repository, with LLVM-MinGW 20260922 UCRT available, run:

```sh
python scripts/build_kallisto_native.py --fetch --cache vendor-expanded/kallisto --toolchain /path/to/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64
python scripts/prepare_kallisto_pack.py --vendor vendor-expanded/kallisto --toolchain /path/to/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64
```

Use `--linux` on the build command for the matching GCC Linux reference implementation. Pack versioning is independent of application versioning. The pack retains its BSD-licensed kallisto/Bifrost sources, zlib and embedded third-party notices, LLVM/MinGW notices and MIT Workbench adapters.

Cite: Bray NL, Pimentel H, Melsted P, Pachter L. Near-optimal probabilistic RNA-seq quantification. *Nature Biotechnology* 34, 525–527 (2016). https://doi.org/10.1038/nbt.3519

Upstream source: https://github.com/pachterlab/kallisto/tree/v0.52.0
