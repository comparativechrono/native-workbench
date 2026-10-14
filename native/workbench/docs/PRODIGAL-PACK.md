# Prodigal prokaryotic gene prediction pack

This independent optional pack is **prodigal 1.0.0** for Windows x86-64.
Its scientific executable is **Prodigal 2.6.3-workbench1**, built from upstream
commit `004218fbeb2cf54fe12d88ec2eede6a27d70ebf7`. No Python, Java, WSL, Docker,
network connection or administrator privileges are required to run it.

## Supported operations

- **Genome:** train on the supplied prokaryotic assembly, then predict coding
  genes. Explicitly select genetic code 11 (usual bacterial/archaeal/plastid),
  4 (TGA translates W), or 25 (TGA translates G). Select automatic initiation
  model training or force the upstream non-Shine-Dalgarno model (`-n`).
- **Metagenome:** predict on short or mixed prokaryotic contigs with upstream
  preset models. Prodigal chooses each sequence's model and translation table;
  the GFF Model Data records the actual selection. This mode does not accept a
  genetic-code override or learn a new model from the complete input.

Both operations expose **Require complete genes at contig ends** (`-c`, default
false) and **Prevent genes crossing long N gaps** (`-m`, default true). These
options are biological decisions; neither setting is a QC pass criterion.
An assembly of a eukaryotic genome is not an appropriate input for these
prokaryotic gene prediction models. No gene function, expression or homology
assignment is performed. Proteins from an entire proteome are not necessarily
homologous and should not simply be aligned together to construct a gene tree.

## Inputs and limits

Supply one uncompressed, unaligned DNA FASTA with A/C/G/T/N (either case).
Gzip, GenBank, protein, FASTQ, aligned FASTA and other IUPAC ambiguity codes are
rejected with an explanation. Resolve ambiguous bases explicitly upstream;
the launcher never silently rewrites sequence. Each record must be nonempty.
The first header word must be unique, at most 200 characters, and contain only
ASCII letters, digits, underscore, dot, hyphen or colon. Printable ASCII header
descriptions are retained, except quotes are rejected. Headers are limited to
1024 characters; sequence lines to 8192. Rewrap long sequence lines.

The supported bound is 30 million bases per contig, one billion total bases and
one million contigs. Genome training additionally requires at least 20,000
non-N bases and at most 30 million bases including the upstream 12-base training separators.
Upstream recommends at least 100,000 bases for reliable training and emits its
own warning below that amount; a small fixture does not establish biological
accuracy. The stricter upper bound prevents silent upstream training truncation
near its fixed 32-million-base buffer. N-runs are limited to 4,000 per contig (and 4,000 across genome training)
to protect the upstream mask array. The artificial training separators do not add N-runs. These are implementation limits, not available-memory forecasts.

Paths must be ASCII; spaces are supported. There are no CPU-thread controls:
this Prodigal build is single-threaded and targets baseline x86-64 without AVX.
Its Windows executable reserves an 8 MiB process stack (64 KiB initially
committed) because upstream non-SD training uses fixed local arrays larger
than the Windows linker default 1 MiB stack. This is a virtual-address
reservation, not a prediction of total memory use.
No saved training models, external model files, alternate annotation formats,
score-dump outputs or translation tables beyond 11/4/25 are exposed initially.

## Outputs and interpretation

- `genes.gff`: original upstream GFF3, with 1-based inclusive coordinates,
  strand, score, initiation/partial information and model metadata.
- `proteins.faa`: predicted protein sequences, retaining upstream terminal `*`
  stop symbols. Partial genes may not have a terminal stop.
- `coding-sequences.fna`: predicted CDS DNA in coding orientation, including
  the reverse complement for minus-strand genes.
- `prediction-summary.json`: recorded mode/settings, input contigs/bases/Ns
  and actual predicted gene/protein/CDS counts, with the executed child argv.

GFF `partial=xy` denotes partialness at the physical left/right sequence ends,
not universally the biological 5-prime/3-prime ends. FASTA output IDs use the
input first-word identifier plus the gene ordinal. GFF ID values use sequence
ordinal plus gene ordinal. N masking is unchanged upstream behavior, including
how terminal N runs are handled. No sequences or genes are invented when no
prediction is made: GFF retains metadata and both FASTA outputs can be empty.
A downstream tool requiring records may then reject that empty input clearly.

The application separately records frozen pack/tool identities, input hashes,
parameters, execution logs and output hashes. Methods describe predictions and
settings; they are not experimental confirmation or automatic QC acceptance.

## Source and validation

Upstream source:
`https://codeload.github.com/hyattpd/Prodigal/tar.gz/004218fbeb2cf54fe12d88ec2eede6a27d70ebf7`

Archive SHA-256:
`9caafa079a29ff8f02b5ea84729fec4ecf03975c9ccf4acade4909368b69f317`.

The complete GPL-3.0-or-later source archive is retained in `licenses/`, together
with the exact compatibility patch, build recipe and compiler/runtime notices.
The patch fixes fourteen undefined overlapping `sprintf` metadata appends by
writing at the existing string terminator. It changes the displayed version;
it does not change prediction, training, scoring or translation algorithms.
A Windows-only linker setting raises the stack reservation to 8 MiB; the
builder records and verifies the actual PE reserve/commit fields. Native
regressions cover forced non-SD training and automatic non-SD fallback, both
of which overflowed the original 1 MiB reservation in the first Windows gate.
The separate MIT native launcher validates inputs, maps explicit flags and
starts the bundled executable without a shell. Its source is retained.

Check installation has synthetic known-answer genome and metagenome checks,
including both strands and exact constructed CDS/proteins, plus a legitimate
zero-gene check. Extended tests cover translation tables, partial genes,
N-masking, malformed inputs and pristine Linux upstream comparison. Source,
Linux execution, PE import inspection, native Windows science and application
GUI checks are separate evidence scopes. Consult the dated candidate handover
for exact tested archives/commits, failures, skipped checks and remaining limits.

Reproduce from the checkout root with a pinned LLVM/MinGW toolchain:

```sh
python3 scripts/build_prodigal_native.py --cache build/prodigal --toolchain /path/to/llvm-mingw --fetch
python3 scripts/prepare_prodigal_pack.py --cache build/prodigal --toolchain /path/to/llvm-mingw --destination packs/prodigal-1.0.0
python3 scripts/build_prodigal_native.py --cache build/prodigal --linux
python3 scripts/build_prodigal_native.py --cache build/prodigal --linux --upstream
NW_PRODIGAL_CACHE=build/prodigal python3 -m unittest discover -s tests -p test_prodigal_pack.py -v
```

Native exact-pack science accepts `tests/test_prodigal_pack.py --pack PATH
--report report.json`. Build-time provenance never claims execution testing.

Citation: Hyatt D et al. (2010), *Prodigal: prokaryotic gene recognition and
translation initiation site identification*, BMC Bioinformatics 11:119.
<https://doi.org/10.1186/1471-2105-11-119>
