# IQ-TREE phylogenetic inference pack 1.0.0

This optional pack runs unmodified upstream IQ-TREE **3.1.4** locally on Windows
x86-64 with a private Python **3.13.16** runtime for input validation and output
provenance. It needs Workbench **0.6.0** or newer. No system Python, Docker, WSL,
Java, browser or analysis upload is required. Import the separate pack ZIP using
Manage tools → Import pack ZIP. No genome or annotation database is needed.

## Operations and interpretation

Two operations infer a maximum-likelihood phylogeny from an **already aligned**
nucleotide or protein FASTA. Connect the matching MUSCLE aligned output, or select
a local alignment. This is not a read mapper, alignment algorithm, species-tree
estimator, partition/codon analysis, divergence dating tool or tree viewer.

Both operations expose:

- ModelFinder Plus (`MFP`), selected by BIC, or a bounded fixed-model list:
  DNA `GTR+G4`, `HKY+G4`, `JC`; protein `LG+G4`, `WAG+G4`, `JTT+G4`.
- No branch support (default), ultrafast bootstrap, SH-aLRT, or both. Support
  replicates are 1,000–10,000; ignored when support is none. UFBoot enables the
  upstream `-bnni` correction. Both-method labels are SH-aLRT/UFBoot, as reported
  by IQ-TREE. These values are support measures, not posterior probabilities.
- Threads 1–64 (default 2), random seed 1–2,147,483,647 (default 42). The seed
  records a reproducibility setting; identical floating-point results across
  CPUs, operating systems, thread counts and builds are not promised.

The Newick output is **unrooted** with an arbitrary display root. Original
first-word FASTA identifiers are restored as correctly quoted Newick names;
full headers and the safe internal names used in upstream reports are retained
in `analysis-provenance.json`. Outputs include the tree, unmodified upstream
report and log, selected-model summary, and exact child argument array, hashes,
settings, mapping and alignment statistics. ModelFinder's intermediate model
comparison data and any support/checkpoint files remain in `iqtree-work`.
Detailed JSON bipartitions are included for at most 256 taxa; above that bound
the JSON explicitly directs readers to the complete Newick tree, avoiding a
quadratic-size summary. Tree inference and the full tree output are unchanged.
Workbench adds its usual methods draft and DAG. Review biological sampling,
homology, recombination, model adequacy, rooting and support before publication.

The released application has no dedicated phylogenetic-tree type: Newick is
explicitly labelled but uses the generic `file` output type. Inputs use the real
`msa-nucleotide` and `msa-protein` contracts. A protein alphabet consisting only
of DNA-like letters remains protein when the protein operation is selected.

## Input and local-compute bounds

Choose an uncompressed aligned FASTA up to 256 MiB, 4–10,000 taxa, and
20–1,000,000 columns. Every row must have the same width, unique nonempty
first-word identifiers and at least one canonical residue. At least four distinct
sequences and one parsimony-informative column are required by this pack; it
returns an actionable error for identical or insufficiently informative data.
These are conservative frontend limits, not a claim that every permitted input
will fit in a desktop computer's memory or be scientifically adequate.

DNA accepts IUPAC DNA/RNA ambiguity codes; U is explicitly normalized to T.
Protein accepts the standard twenty amino acids plus B/X/Z. Stop symbols, U/O/J
require manual review and are rejected; MUSCLE can retain some of these symbols,
so not every possible MUSCLE protein output is accepted. Dot gaps become hyphens,
and letters become upper case. No sites or taxa are deleted. Identical sequences
among otherwise informative data are retained with IQ-TREE `-keep-ident`.

An ASCII-only installation and results path is required by the upstream Windows
filename implementation; spaces are supported. The private adapter reads selected
Unicode input paths, stages safe ASCII filenames inside the result directory,
and records the source hash. Input files remain unchanged. CPU threads are not a
RAM cap. Runs do not automatically resume or overwrite prior results.

## Build and source provenance

```
python3 scripts/fetch_iqtree_build_inputs.py --fetch
python3 scripts/prepare_iqtree_pack.py
python3 tests/test_iqtree_pack.py --report build/iqtree-evidence/linux.json
```

The build recipe pins official Windows and Linux release archives and every
retained source/runtime input in `tools/iqtree/input-lock.json`. The Windows
executable is upstream's exact binary, with its exact app-local Intel OpenMP
DLL; it is not recompiled or algorithmically patched. PE imports are recorded.
Only the command-line executable is distributed, not the double-click launcher.
The private Python embedded search path has no `import site`, registry/global
packages, installer or pip dependency; adapter calls use `-I -B -X utf8`.

`licenses` contains the exact IQ-TREE tag source, matching lsd2 and cmaple
submodule archives, CPython source, original Python notices, GPLv2 text, the
adapter/build source and upstream build workflow. The tag source retains bundled
library notices and source. Compiled dependency sources are also retained: full
Boost 1.84.0, Eigen 3.4.0 and the exact Chocolatey 3.4.0.20240224 header package,
all 252 registry archives pinned by the upstream Cargo.lock, phylo_grad at its
pinned git revision, and Rust 1.98.1 standard-library sources and vendored
components. The recipe verifies every crate checksum against Cargo.lock and
compares all 530 packaged Eigen headers byte-for-byte with upstream source.
Original component licenses are retained within these archives; compiler runtime
notices and the GCC Runtime Library Exception are retained separately. The exact
upstream September 10 Windows CI dependency versions and link line are recorded
in `licenses/upstream-dependency-evidence.txt`. This is source availability, not
a claim of bit-for-bit reconstruction of the official compiler environment. cmaple is disabled in the
upstream Windows build and its facilities are not exposed by this pack.

The upstream Windows DLL identifies Intel OpenMP 5.0.20140611. The retained
historical OpenMP license is the Intel/LLVM release_35 license and attribution
notice, with the original Intel copyright also stated in NOTICE.txt. Intel's
published licensing explanation is recorded in provenance. This source notice
is not represented as a byte-reproducing recipe for the Intel-compiled DLL.

## Validation boundaries

Fixtures are deterministic synthetic alignments constructed from a common
ancestral sequence with three separate shared-mutation pairs and private terminal
mutations. Their taxon identities, 800 columns, 300 variable and 210 informative
columns and three unrooted pair splits are known from construction, independently
of IQ-TREE. Tests parse the actual Newick, compare supported models and site
counts, validate real support labels and exercise explicit alphabets, malformed
inputs, safe names, unchanged files, thread options, spaces and upstream binary
agreement. The scientific suite runs real MUSCLE Super5 in both alphabets before IQ-TREE;
Windows uses the pinned published MUSCLE 0.5.2 pack, and Linux uses upstream
MUSCLE 5.3. The separate released-app graph test checks matching ports,
branches and saved pins without executing scientific tools.

Linux execution uses the pinned official Linux build, not a claim of Windows
execution. Pack-owned Check installation fixtures run the actual installed
Windows binary and validate tree/model/report truth. Exact published-archive
Windows evidence is supplied separately at release time. The native regression
CLI is `python tests/test_iqtree_pack.py --pack INSTALLED_PACK --muscle-archive
MUSCLE_0.5.2_PACK_ZIP --report REPORT_JSON`. This is a research and
teaching pack; small fixtures do not establish clinical or large-phylogeny
performance validation.

Cite IQ-TREE 3, ModelFinder and UFBoot2 as appropriate to selected operations:
https://doi.org/10.1093/molbev/msag117,
https://doi.org/10.1038/nmeth.4285,
https://doi.org/10.1093/molbev/msx281.
