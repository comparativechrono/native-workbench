# Kalign multiple sequence alignment pack 1.0.0

This optional pack supplies **Kalign 3.5.1-workbench1**, built from upstream
release 3.5.1 at immutable commit
`3e6de1df29d111c5fa5beb4c4294ef681978fd23`. Two operations align homologous
nucleotide or protein sequences and produce a typed aligned FASTA. The initial
build uses one CPU thread and baseline x86-64 instructions. No AVX2, OpenMP,
system Python, WSL, administrator access or network is required for analysis.

## Scientific operation

Select the operation matching the actual sequence alphabet. Nucleotide alignment
explicitly uses upstream **DNA scoring**; it is also suitable for homologous RNA
sequence letters when that scoring choice is intended. U scores as T but is
retained in the output. This does not align RNA secondary structures. Protein
alignment uses upstream **PFASUM43** scoring and the upstream variable-scoring
matrix default. There is no automatic alphabet or model selection.

Both operations use upstream default single alignment: five consistency anchors
with weight 2.0, no ensemble, refinement, custom penalties or guide-tree noise.
DNA gap-open/extension/terminal-extension defaults are 8/6/0; protein defaults
are 7/1.25/1. The upstream variable-scoring amplitude is 0 for DNA and 2 for
protein. These are algorithm settings, not QC thresholds or accuracy guarantees.
More advanced upstream modes and multiple input-file merging are outside this
initial pack.

For the supported default-mode operations, the CLI boundary corrects an upstream behavior where `--type protein` could
still reject proteins made only of nucleotide-like letters, and `--type dna`
could reject ambiguity-heavy DNA. Explicit type now controls the alphabet before
the unchanged scientific routines run. Windows compatibility changes address
`getline`, `localtime_r` and a macro collision. The exact patch and build-time
version suffix distinguish this build from the official upstream distribution.
No alignment, guide-tree or scoring algorithm is replaced.

## Input boundary

- One uncompressed, ungapped FASTA with 2–10000 nonempty sequences, each
  1–15000 residues; at most 10000000 total residues and 64 MiB. These pack
  validation bounds do not cap RAM or forecast runtime.
- Select homologous sequences. The program does not select orthologues, establish
  homology, align reads to a genome or infer gene/species trees.
  Nucleotide sequences must already share orientation; Kalign does not
  reverse-complement sequences or preserve codon frames.
- Unique first-word identifiers contain 1–128 ASCII letters, digits, underscore,
  dot or hyphen. Rename punctuation/pipe-delimited IDs first. ASCII headers may
  contain descriptions, up to 1024 characters; full headers and input order are
  restored after alignment.
- Nucleotide accepts DNA/RNA IUPAC letters. Protein accepts the standard 20 amino
  acids and B/X/Z. Original letters are retained after uppercasing; ambiguous
  DNA letters use the upstream N scoring class. Protein stops, J, U and O are
  rejected. Inspect stops before removing biologically appropriate terminal `*`;
  internal stops may indicate a sequence or gene-prediction problem.
- Gaps, residue whitespace, compressed data and empty records are rejected with
  corrective guidance. ASCII installation, input and results paths are supported,
  including paths containing spaces. Unicode paths remain outside this pack.

The native helper stages safe private IDs and verifies every output ID, each
ungapped residue and equal alignment-row lengths before writing the final FASTA.
It preserves duplicate biological sequences when they have distinct identifiers.
The original input is never edited, and existing outputs are not overwritten.
The bounded helper starts the real Kalign executable with argument arrays, without
a shell; failures direct the user to `kalign.log`.

## Results and downstream use

`alignment.afa` is the aligned nucleotide or protein FASTA. Its typed output can
connect to the corresponding FastTree operation. FastTree separately requires at
least four taxa and 20 columns, and at least one recognized residue in every taxon.
An accepted Kalign result does not necessarily satisfy these additional conditions.

`alignment-summary.json` records sequence/residue counts, input-length range,
alignment columns, gaps, all-gap columns and ambiguity characters.
`analysis-settings.json` records the exact child argument array, algorithm
defaults and identifier mapping. `kalign.log` retains upstream messages. These
measurements have no invented pass thresholds. Workbench's frozen plan and result
record pack/tool hashes, input provenance and execution status. Settings alone do
not establish that a run finished. The existing Results interface supports status,
search and tool provenance; it does not yet parse this new JSON into summary tiles.

## Rebuild and scientific checks

Python is a development dependency only. From the repository root:

```sh
python scripts/build_kalign_native.py --fetch --linux --cache build/kalign-cache --build build/kalign-linux
python scripts/build_kalign_native.py --linux --upstream --cache build/kalign-cache --build build/kalign-reference-linux
python tests/test_kalign_pack.py --build build/kalign-linux --reference-binary build/kalign-reference-linux/kalign --report build/kalign-linux-checks.json
python scripts/build_kalign_native.py --cache build/kalign-cache --build build/kalign-windows --toolchain /path/to/llvm-mingw
python scripts/prepare_kalign_pack.py --cache build/kalign-cache --build build/kalign-windows --destination packs/kalign-1.0.0
python scripts/package_split.py pack --pack-root packs/kalign-1.0.0 --output build/kalign-1.0.0.zip
python scripts/validate_pack_release.py build/kalign-1.0.0.zip
```

Native Windows scientific checks use the unpacked **exact pack**:

```powershell
python tests/test_kalign_pack.py --pack C:/test/kalign-1.0.0 --report C:/test/kalign-science.json
```

Two six-sequence synthetic fixtures independently specify a 240-residue ancestor,
private substitutions, a 12-residue deletion and a shared insertion. Their expected
homology is constructed before any aligner is run; the scientific suite checks
actual aligned residue pairs and preserved inputs, not just process success.
Pristine Linux upstream reference comparisons cover the ordinary DNA/protein
fixtures. Explicit-alphabet correction cases are separate regressions because the
unmodified CLI rejects them. Installation checks verify complete known-indel
alignments and measured counts; the extended suite also checks aligned residue
pairs, independent upstream comparisons and failure boundaries.
The recorded reference can be reproduced with
`python tools/kalign/record_reference.py --binary build/kalign-reference-linux/kalign --output build/kalign-reference.json`;
the Linux suite freshly re-executes and compares those cases with the retained record.

The pack retains the complete SHA-pinned upstream source archive, Apache-2.0
licence and embedded third-party source notices, exact patch, Windows compatibility
header, native helper, fixture generator, recipes and compiler/runtime notices.
`licenses/build-provenance.json` records actual commands and hashes. Build/PE
inspection, Linux execution, native Windows execution, application integration and
GUI review are separate evidence. This guide is not a claim that an archive passed
those gates or was published. Representative PCs and realistic benchmarking remain
separate work.

Upstream reference: [Kalign 3.5.1](https://github.com/TimoLassmann/kalign/releases/tag/v3.5.1).
Cite [Lassmann, Kalign 3, Bioinformatics](https://doi.org/10.1093/bioinformatics/btz795).
