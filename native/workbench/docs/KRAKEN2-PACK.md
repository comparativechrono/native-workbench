# Kraken2 classification pack 1.0.0

Native Workbench 0.6.0 or newer, Windows x86-64. Real upstream **Kraken2
2.17.2** classifies single or paired Phred+33 FASTQ reads against an explicitly
selected local nucleotide database. A private Python runtime is included. No
Docker, WSL, browser, administrator privileges or system Python is required.

## Choose and register a database

The tool pack contains no general-purpose biological database. Its tiny synthetic
database is only an installation fixture, not suitable for analysing real samples.
Choose a prebuilt database appropriate for your organisms and question, obtain
it separately, and retain its provider, release and original download checksum.
Database composition determines which organisms can be detected and can introduce
false assignments or omissions. A classified read is not evidence of infection.

`prepare-archive` accepts an already downloaded tar/tar.gz/tgz and safely extracts
only the three Kraken2 index files into this run's resource folder by default.
Choose the explicit matching-model option to also extract/register standard Bracken
distributions after confirming their source and settings. It does not download anything. `register-database`
accepts the `hash.k2d` file in an existing folder containing `opts.k2d` and
`taxo.k2d`, without copying or changing those large files. Both return a small
`database-resource.json` descriptor for future selection or pipeline connection.
Keep the referenced directory: the descriptor is not a database archive.

Provide the database label, source description and release. Optional source URL
is provenance only and is never fetched. Select any matching
`database<N>mers.kmer_distrib` files if Bracken will be used. Confirm explicitly
that those distributions correspond to these exact index files, the filename's
read length and standard Kraken2 model settings. Names and hashes cannot prove
that biological association; external models are labelled as user-attested.

Full SHA-256 index hashes are checked during registration and before/after each
classification. This adds sequential disk I/O but avoids silently classifying
against a changed resource. The fingerprint identifies index/taxonomy/options
bytes, not publisher trust. Register resources again after moving them, or use
the documented safe relative descriptor form. See
[the shared contract](METAGENOMICS-RESOURCES.md).

## Classification and outputs

`classify-single` and `classify-paired` accept plain or gzip four-line FASTQ.
Records, DNA IUPAC symbols, Phred+33 quality range and paired names/order/counts
are checked. Both mates must be selected in order; duplicate physical files are
rejected. Read identifiers ending in /1 and /2 must agree with their mate. Reads
are streamed into a private uncompressed temporary copy for consistent native
input; that copy is removed after execution. Plan disk for decompressed reads
plus the per-fragment assignment output. No trimming is performed.

Default classification uses confidence 0, minimum hit groups 2 and minimum base
quality 0. Confidence can raise assignments to an ancestor or unclassified; it
is not a calibrated probability. A quality threshold masks low-quality bases
inside upstream Kraken2. Reports retain ordinary six columns and all nonzero
observed taxa; no MPA or minimizer-count columns are substituted. Outputs:

- `kraken.report.tsv`: unchanged upstream six-column taxonomic report.
- `kraken.assignments.tsv`: upstream per-read/per-pair classification and minimizer hits.
- `classification-record.json`: database/report hashes, settings and observed length/counts;
  connect this output to Bracken's classified-input operation.
- `analysis-provenance.json` and `kraken.log`: actual arguments, source identity,
  input hashes, resource settings and upstream diagnostics.

Paired inputs produce one classification per **fragment**, not two independent
mate classifications. Report percentages use all input fragments including
unclassified ones. Kraken2 classification is not Bracken abundance estimation.
Bracken requires a matching distribution model and read length; nonstandard
confidence/quality/hit-group settings require corresponding model evidence.

## Memory, scope and native port

Installation, database and output paths must contain ASCII characters; spaces
are supported. Input FASTQ paths can contain Unicode because Python stages them.
Only 64-bit little-endian, current reverse-complement Kraken2 DNA database format
0 with 32/40-bit compact hash cells is accepted. Both the 56-byte options layout
from Kraken2 2.0.8 and the subsequent 64-byte layout (including2.1.3) are supported;
pre2.0.8 reverse-complement version0 databases need an upstream rebuild. External taxonomy IDs must fit unsigned32-bit: the upstream six-column report
otherwise truncates them even when per-read output preserves64-bit IDs. This
pack rejects that inconsistency before classification. Protein databases, daemon mode,
database downloading/building/merging, paired interleaving and FASTA queries are
not exposed. General-purpose database building remains an upstream preparation
task, not hidden inside classification.

Memory-mapped mode is the default and uses native Windows file mappings. It
avoids eagerly allocating a full hash-table buffer, but random disk access can
be much slower when RAM is insufficient; it is not a promise that every database
fits a laptop. Load mode allocates the hash table in RAM and performs bounded
sequential loading. Threads affect classification, not total RAM. Keep huge
databases on suitable local storage and review upstream resource requirements.

The port preserves upstream minimizer, compact-hash, LCA, confidence and report
algorithms. Changes are confined to Win32 mapping, binary CRT/stream I/O,
bounded 64-bit reads, LLP64 integer/leading-zero handling, error reporting and
removal of unused POSIX daemon/FIFO code. Windows preload is sequential; there
is no substitute taxonomic classifier. LLVM/MinGW 20260922, LLVM23.1.2 OpenMP,
private CPython3.13.16 and corresponding source/licensing material are retained.

## Rebuild and validate

Run `python scripts/fetch_kraken2_build_inputs.py` explicitly to recover pinned
sources. Add `--with-toolchain` to retrieve the SHA-pinned Linux-hosted compiler
archive, extract it to a development folder, and provide its root as
`--toolchain`; no historical mosdepth build is needed. Provide the
LLVM/MinGW20260922 UCRT x86-64 compiler location to
`python tools/kraken2/build.py --toolchain PATH --output NEW_BUILD`.
For an unchanged Linux reference build use `--linux --upstream`.
Generate fixtures with `tools/kraken2/fixtures.py --builder BUILD/build_db
--output NEW_FIXTURE`. The build script records flags, compiler/binary hashes,
patches and PE imports; it does not claim native Windows execution.

`scripts/prepare_kraken2_pack.py` requires the build, fixture directory and pinned
inputs, then creates a new independent pack. Package with
`scripts/package_split.py pack` and validate its exact archive. Run
`tests/test_kraken2_pack.py --pack PACK --report REPORT` on Windows; Linux
requires `--binary BUILD/classify` and establishes separate upstream/adapter
evidence. Native archive import, scientific execution and paths with spaces are
distinct release gates. Small synthetic checks do not establish whole-database
performance, every workplace policy, clinical validation or accuracy for an
unspecified reference collection.

Cite Wood DE, Lu J, Langmead B (2019), *Improved metagenomic analysis with Kraken
2*, Genome Biology 20:257, https://doi.org/10.1186/s13059-019-1891-0.
