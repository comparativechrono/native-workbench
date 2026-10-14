# FastTree phylogenetics pack 1.0.0

This optional pack contains the actual **FastTree 2.2.0** inference engine,
compiled from immutable upstream commit
`a780aa4f6a18791ea76c04afaf37aafe43e51d59`. The engine source is unchanged.
The initial pack is **serial, double precision, baseline x86-64**. It does not
require AVX2, OpenMP, a system Python, WSL, an administrator or network access.
The upstream official 2.2.0 executables require AVX2; this is a separate native
build with recorded flags and imports, not a repackaging of those executables.

## Inputs and scientific choices

Two operations take an existing uncompressed aligned FASTA:

- Nucleotide phylogeny: Jukes-Cantor or GTR, explicitly selected.
- Protein phylogeny: JTT, LG or WAG, explicitly selected.

The sequences must be homologous and aligned; FastTree does not align sequences,
select orthologues, infer a species tree or choose the best model. MUSCLE's typed
nucleotide/protein alignment outputs can connect to the matching operation.
Combining every predicted gene from different genomes is not a valid homology
selection workflow.

Select **CAT20** topology search/branch lengths, or **CAT20 search followed by
Gamma20 length rescaling**. Gamma optimizes a gamma shape and common branch-length
scale after the CAT search; it does not perform a full gamma topology search.
Choose no support or 1000-resample **SH-like local support**. Those values are
between 0 and 1, not global bootstrap percentages or posterior probabilities.
The seed is explicit and recorded; equivalent numeric results need not have
identical bytes across platforms. The displayed Newick root is arbitrary.

## Supported input boundary

- 4–10000 taxa, 20–1000000 equal-length alignment columns, up to 256 MiB.
  These bounds are validation limits, not a RAM or runtime guarantee.
- Unique first-word identifiers of 1–128 characters using ASCII letters,
  digits, underscore, dot or hyphen. Descriptions after the first whitespace
  are ignored. Rename pipe-delimited or punctuated identifiers before use.
- DNA accepts IUPAC bases, U and gaps; U becomes T. Protein accepts the standard
  20 residues plus B/X/Z and gaps. Protein stops, J, U and O are rejected:
  inspect the biological meaning and remove appropriate terminal stops before
  alignment; internal stops may indicate a sequence or gene-prediction issue.
- Lowercase becomes uppercase; dot gaps become hyphens. DNA ambiguities and
  protein B/X/Z become missing data, matching FastTree's zero-weight handling
  of unknown residues. They are not interpreted as probabilistic ambiguity.
  Each taxon must retain a recognized residue. Columns are not filtered.
- ASCII installation, input and output paths; spaces supported. Gzip, PHYLIP,
  constraint trees, custom models, global bootstrap and FastTreeMP are outside
  this initial pack.

The native boundary maps IDs privately before invoking unchanged FastTree,
then verifies Newick syntax, finite nonnegative branch lengths, permitted support
values and preservation of every selected ID before writing the final tree.
Malformed inputs fail with actionable messages before scientific execution.
An engine failure points to `fasttree.log`; existing outputs are never replaced.
The helper starts FastTree with argument arrays, without a shell.

## Outputs

`inferred-tree.nwk` is the labelled unrooted approximate-ML tree, represented by
Workbench's generic file type. `alignment-summary.json` reports taxa, columns,
variable/informative columns ignoring missing data, gap and ambiguity counts,
branch lengths and local-support counts. These are measured values; no QC pass
threshold is invented. `analysis-settings.json` records choices, exact argument
array and taxon mapping. Upstream execution/model logs and the staged alignment
remain in the run directory. Workbench's frozen plan/result supplies pack/tool
hashes, input provenance and execution status; settings alone do not imply a
completed run.

## Rebuilding and checking

From the repository root, with Python used only for development/packaging:

```sh
python scripts/build_fasttree_native.py --fetch --linux --cache build/fasttree-inputs --build build/fasttree-linux
python tests/test_fasttree_pack.py --build build/fasttree-linux --reference-binary build/fasttree-inputs/FastTree --report build/fasttree-linux-checks.json
python scripts/build_fasttree_native.py --cache build/fasttree-inputs --build build/fasttree-windows --toolchain /path/to/llvm-mingw
python scripts/prepare_fasttree_pack.py --cache build/fasttree-inputs --build build/fasttree-windows --destination packs/fasttree-1.0.0
python scripts/package_split.py pack --pack-root packs/fasttree-1.0.0 --output build/fasttree-1.0.0.zip
python scripts/validate_pack_release.py build/fasttree-1.0.0.zip
```

Native Windows GCC/G++ on PATH is also supported when its runtime notices are
installed; an explicit LLVM/MinGW toolchain is preferred for recorded builds.
Native scientific checks run the **unpacked exact pack**:

```powershell
python tests/test_fasttree_pack.py --pack C:/test/fasttree-1.0.0 --muscle-archive C:/test/muscle-0.5.2.zip --report C:/test/fasttree-science.json
```

The known-answer fixture is constructed independently from an 800-site ancestor,
three shared 70-site pair substitutions and six private 15-site substitutions.
It requires six named taxa and three expected unrooted pairs. All five models,
both rate choices and both support choices are checked against independent
truth and recorded output from the SHA-pinned official Linux2.2.0 executable;
branch-length comparison allows relative 1% or absolute 0.00002 difference.
That numeric tolerance is a regression comparison, not a scientific quality
threshold. Native Windows additionally executes the unchanged published MUSCLE
0.5.2 archive for both alphabet chains. Build/PE inspection, Linux execution,
Windows execution, pack import and GUI checks are separate evidence.

The pack retains complete FastTree single-file corresponding source and GPLv3
license (the source header permits GPLv2 or later), native guard and recipe
source, compiler/runtime notices and build
provenance under `licenses/`. `build_fasttree_native.py` pins all downloads by
SHA-256 and immutable commit; the comparison-only Linux executable is not shipped.
Performance on realistic large alignments and representative PCs remains untested
unless separately recorded in the dated evidence. This document is not a release
or a claim that any particular archive passed native checks.

Recorded reference trees can be independently reproduced with
`python tools/fasttree/record_reference.py --binary build/fasttree-inputs/FastTree --verify tools/fasttree/fixtures/reference.json`.
The Linux scientific gate re-executes all 20 cases against the pinned official
reference, separate from native Windows comparisons with that frozen record.
