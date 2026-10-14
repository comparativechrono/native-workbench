# Primer3 PCR primer design pack

Initial independent pack `primer3` **1.0.0**, operation `design-pcr`, native
upstream **Primer3 2.6.1**. This is an unpublished review candidate. It does not
change the application version or an existing pack. Native execution and GUI
evidence are recorded separately in the candidate handover; building this pack
alone is not proof of Windows execution.

## Scientific scope

Design standard PCR primer pairs from one local, uncompressed, ungapped DNA
FASTA record. Select a relevant template region yourself: this operation designs
across the supplied sequence without a required target interval. It does not
identify organisms, check primer specificity against a genome/database, handle
exon boundaries, run in-silico PCR, design internal probes, or establish
experimental success. No clinical claim is made.

The template must contain 60–100000 bases, A/C/G/T/N only, within a 2 MiB input
file. Lowercase becomes uppercase; no soft masking is applied. N may occur in
the template but selected primers cannot contain N. The first header word must
contain 1–128 ASCII letters, digits, underscore, dot or hyphen; the full ASCII
header is bounded at 1024 characters. Multiple records, other ambiguity codes,
gaps and compressed inputs are rejected with guidance. ASCII installation,
input and output paths are supported, including spaces. Bounds are interface
limits, not time or memory estimates. Execution is serial on baseline x86-64;
AVX/AVX2, WSL, a browser and a system scientific runtime are not required.

## Explicit settings and interpretation

The form exposes product-size minimum/maximum (40–10000 bp), maximum candidate
pairs (1–20), primer lengths (12–36 bases), minimum/optimum/maximum calculated Tm
(0–100 C), monovalent salt (0.01–1000 mM), divalent salt (0–100 mM), total dNTP
(0–100 mM), and effective annealing oligonucleotide concentration
(0.01–100000 nM). Minimum <= optimum <= maximum is enforced. Product minimum
must not exceed the template length and must be at least the maximum primer
length. Settings outside these technical bounds are unsupported, not declared
scientifically impossible.

Initial values are upstream-style examples: products 100–300 bp; five pairs;
lengths 18/20/27; Tm 57/60/63 C; monovalent salt 50 mM, divalent salt 1.5 mM,
total dNTP 0.6 mM and effective oligo 50 nM. They must be chosen for the
experiment. `PRIMER_DNA_CONC` means effective annealing oligonucleotide
concentration, not template DNA concentration; this empirical model input can
differ from the initial primer concentration in the reaction.

Primer3 uses `--default_version=2`, `--io_version=4`, strict tags, generic task,
paired primers and no internal oligo. `PRIMER_TM_FORMULA=1` and
`PRIMER_SALT_CORRECTIONS=1` select the SantaLucia nearest-neighbor model and salt
correction. Thermodynamic oligo alignment is enabled; thermodynamic template
alignment is disabled. The exact bundled thermodynamic tables are used via an
explicit path. Template masking, lowercase masking and primer N acceptance are
disabled. Other constraints/preferences retain the pinned upstream default
version 2; no repeat library or specificity database is selected. These are
model calculations and design constraints, not observed PCR measurements or QC
pass thresholds.

## Outputs

- `primers.tsv`: ranked primer sequences, always written 5′→3′, with zero-based
  half-open binding intervals on the supplied template, product length,
  calculated Tm, GC percentage and upstream pair penalty.
- `primer3-result.boulder`: complete upstream output, including rejection
  explanations and warnings. Its coordinates use `PRIMER_FIRST_BASE_INDEX=0`;
  the right-primer position is the rightmost template coordinate. Thus right
  `(position,length)` becomes `[position-length+1,position+1)` in the TSV.
- `primer3-input.boulder` and `analysis-settings.json`: exact explicit request
  and recorded chemistry/model settings. The request contains the selected
  local template sequence and the local thermodynamic table path.
- `primer3-summary.json`: recorded template/pair counts and upstream calculated
  measurements. `specificityEvaluated` is false; no QC verdict is assigned.
- `primer3.log`: captured process diagnostics; empty is valid on success.

The adapter verifies the left primer against its template substring, the right
primer against the reverse complement of its binding substring, and the
product length from template coordinates. An upstream error remains a failed
run. **Zero candidate pairs is a successful biological outcome**: the TSV
contains its header, and the summary points to Primer3's rejection explanations.
Reconsider the selected region or design constraints; do not interpret this as
a missing executable or fabricate a primer pair.

The current application Results view lists outputs, status, search and recorded
provenance. The new summary JSON is an output file; this pack does not add a
special native summary tile or a specificity viewer.

## Source, build and licensing

Pinned official source: [Primer3 v2.6.1](https://github.com/primer3-org/primer3/releases/tag/v2.6.1),
commit `7f9f17d6012f404e83bbf0f931a4d06eb4af465b`.
Archive `primer3-2.6.1.tar.gz`, SHA-256
`c981e42765ceb525f56607c6a7cf989ac5068483731c6e083b1e9fb22816463b`.
The archive URL is the immutable commit endpoint on
`https://codeload.github.com/primer3-org/primer3/tar.gz/`.

Upstream source is unmodified. The builder compiles the exact Makefile
`primer3_core` source list using existing upstream Windows conditionals;
Windows omits the unsupported masker component. The pack exposes no masking
operation. LLVM/MinGW produces statically linked native executables with an
8 MiB stack reserve/64 KiB commit and only system Windows/UCRT imports.
Compiler identity, commands, binary hashes, source/adapter hashes, PE imports
and complete thermodynamic file hashes are recorded in `build.json`.

The Primer3 suite/library is GPL-2.0-or-later; the compiled Amplicon3
`amplicontm.c/h` component, derived from DECIPHER, is GPL-3.0-or-later. Both
licence texts and the Amplicon3 source notice are retained. The full upstream
source archive, unmodified tables, compiler/runtime notices, MIT Workbench
adapter and build/preparation/fixture/reference scripts accompany the pack.
No source-only pointer is substituted for corresponding source.

```sh
python scripts/build_primer3_native.py --fetch --linux
python scripts/build_primer3_native.py --linux --upstream
python scripts/build_primer3_native.py --toolchain /path/to/llvm-mingw
python scripts/prepare_primer3_pack.py --destination build/packs/primer3-1.0.0
python tests/test_primer3_pack.py --report build/primer3-source-tests.json
python scripts/package_split.py pack --pack-root build/packs/primer3-1.0.0 --output build/native-workbench-pack-primer3-1.0.0.zip
python scripts/validate_pack_release.py build/native-workbench-pack-primer3-1.0.0.zip
```

Build and prepare accept `--cache` and `--build`. Preparation requires a new or
empty destination and rejects stale source/configuration/binary hashes.
Analysis never downloads anything. Missing binaries or thermodynamic tables
require reinstalling the complete pack, not a global environment change.

Fixtures are synthetic. The planted fixture has two predetermined 20-base arms
surrounded by N, giving independent binding coordinates and product length;
ordinary random DNA exercises unconstrained ranking. Tests also execute a fresh
pristine upstream Linux reference; agreement is a port regression, not proof of
biological effectiveness. Native Windows, both path forms, exact archive and
GUI checks remain distinct gates documented with the review candidate.

References: [Primer3 manual](https://primer3.org/manual.html);
[Untergasser et al. (2012)](https://doi.org/10.1093/nar/gks596).
