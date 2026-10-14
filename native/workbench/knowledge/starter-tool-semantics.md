# Starter alignment and reference-index audit

Reviewed 2026-10-06 after testers reported difficulty connecting alignment
outputs and could not identify the purpose of the reference-index operation.
The initial findings below came from source and manifests. Follow-up native
execution is recorded separately below. Published pack files and identities
were not changed.

## What the starter actually runs

| Existing operation ID | Scientific program and command | Input/output contract |
| --- | --- | --- |
| `align/single-end` | minimap2 2.28-r1209, `-a -x sr` | Single FASTQ + genomic FASTA → unsorted DNA SAM |
| `align/paired-end` | paircheck 1.0.1, then minimap2 2.28-r1209, `-a -x sr` | Atomic read-1/read-2 pair + genomic FASTA → unsorted DNA SAM and pair-check report |
| `bam/sort` | SAMtools 1.24, `sort -m 256M -T ... -o sorted.bam` | SAM or BAM → coordinate-sorted BAM |
| `bam/name-sort` | SAMtools 1.24, `sort -n ... -o namesorted.bam` | SAM or BAM → query-name-sorted BAM |
| `bam/prepare` | SAMtools name sort, `fixmate -m`, coordinate sort, `markdup`, index and summaries | Paired SAM or BAM → coordinate-sorted, duplicate-marked BAM, with duplicates retained |
| `bam/reference-index` | SAMtools 1.24, private FASTA copy then `faidx` | Genomic FASTA → private FASTA copy and its `.fai` lookup index |

There is already a supported SAM-to-BAM path: connect the minimap2 SAM output
directly to `bam/sort`. The operation converts while sorting; it is not an
order-preserving, conversion-only operation. No additional conversion pack is
needed to complete this chain. The old label, **Coordinate sort**, obscures both
the program identity and format conversion.

Coordinate sorting alone does not perform mate repair or duplicate marking.
For workflows needing these additional states, use the paired preparation
operation or its explicit component operations. Do not advertise sorting as
equivalent to that larger preparation workflow.

## Reference index meaning

`bam/reference-index` builds a **FASTA lookup index with SAMtools faidx**. It is
not a minimap2 minimizer index, BWA mapping index, STAR genome directory or
kallisto transcriptome index. It remains useful as a standalone export utility,
and must remain available for saved workflows and exact historical pack pins.

No starter operation declares an input accepting the `.fai` product. The FASTA
copy is a normal reference output that can be connected, but that does not mean
its sidecar index is reused. Starter minimap2 alignment receives the reference
FASTA directly and builds its mapping index internally. `variants/call` and
`variants/pileup` stage a private FASTA and run their own `faidx` step. Users do
not need a separate reference-index step before these operations.

The optional BWA pack similarly contains its own mapping-index step and pipes
alignment into BAM. Its behavior is distinct from starter minimap2's SAM output.
The current generic `index` semantic type does not distinguish every index
format: optional kallisto's adapter validates its own supported index and
rejects other formats. A graph connection accepted by the generic type is not
proof of index-format interchangeability. This pre-existing limitation is
also recorded in [pack development](pack-development.md).

## Display and compatibility changes

The application catalogue now supplies `displayName`, `displayDescription` and
`searchTerms`, derived from declared commands and the producers of final
scientific outputs. Canonical execution metadata remains unchanged. Native
rendering can use these fields with a fallback to the existing name/description.
The starter's resulting display labels include:

- **minimap2 — Paired-end alignment (SAM)**
- **SAMtools — Coordinate sort to BAM (SAM/BAM input)**
- **SAMtools — FASTA lookup index (.fai)**, with help explaining that alignment
  and variant operations prepare their required indexes themselves.

These are presentation changes. They do not change `align`, `bam`, `variants`, their
workflow IDs, saved labels, manifest pins, execution steps or published bytes.
The catalogue already provides `executables` with `id`, `path`, `version` and
`sha256` for each operation, along with `name`, `steps`, `ports` and `outputs`.
The installed `packs` list supplies pack names; operation descriptors do not
currently contain `packName`. Avoid selecting the first executable as the
scientific identity: executables are sorted by ID and can include validation
helpers, adapters and secondary scientific programs.

An eventual conversion-only operation would be a separate versioned change to
the SAMtools pack, using an explicit `samtools view -b -o ...` command without
filtering. It would need header/read-group, record/flag/tag preservation and
mapped/unmapped-record checks, a negative malformed-input case, exact-native
Windows validation and a new pack version. That is not required for the current
SAM → sorted BAM workflow and was not implemented in this audit.

## Evidence and scope

The checked-in `pack-examples` manifests were read through the current strict
parser and compared byte-for-byte with the recovered immutable 0.6.0 starter.
Their SHA-256 values match all three exact starter manifest pins in
`workspace/starter-check-profile.json`:

| Manifest | SHA-256 |
| --- | --- |
| `align.ini` | `81c962222c93356a4f7727b23193c71d7dcd515859e62a179574781f411824d3` |
| `bam.ini` | `45b3f9d5092b0b3014f67b29331003e1214c72919f85695a571fb371030a9888` |
| `variants.ini` | `ea4b7f0a6c28709e4190b6514c07cbf7bdd58e1a4f2a2d931f2cae3ce6ec3795` |

Source validation on Linux with Python 3.12.14: the new
`workspace/tests/test_catalog_presentation.py` passed 7 tests; existing
`test_pack_schema.py` passed 28 and `test_pack_versions.py` passed 10. All 45
passed, with no failures or skips. They cover program identification independent
of executable order, helper exclusion, conversion/index meaning, pipe program
identification, unchanged canonical fields and existing exact-pin contracts.
This does not establish native Windows execution or rendered-label appearance.

The starter scientific profile already defines a minimap2 SAM → SAMtools paired
preparation → BCFtools variant-calling check. Its truth requires 202 mapped,
paired, properly paired records and the expected homozygous SNP at
`starter:1351 G>A`. Reading this profile is not a rerun of that check.

Follow-up exact-package Windows validation passed in
[run 37441781509](https://github.com/comparativechrono/workbench/actions/runs/37441781509)
for source `0d2a993fca95a5837a69aa05c63aa5e806c553af`. Both ordinary and
space-containing installations ran explicit reference and paired-read inputs
through minimap2 SAM → `bam/sort`, without a separate reference-index step.
The checks verified binary BAM, coordinate order, read groups, and preservation
of all 202 expected records, mate flags, sequences, qualities and typed tags.
Floating tags were compared at their IEEE single-precision value, since SAM
text formatting can legitimately change on a BAM round trip. Native pointer
checks also connected an explicit source to a tool and one tool to another,
with no automatically allocated or duplicated workflow file controls. See the
[feedback evidence](evidence/native-workflow-0.8.0-feedback-2026-10-06.json)
and linked raw reports for the exact artifacts and validation limits. This did
not rerun every optional pack or the separate variant-calling truth profile.

Primary upstream documentation consulted on 2026-10-06:

- [SAMtools 1.24 sort](https://www.htslib.org/doc/1.24/samtools-sort.html): accepts
  SAM/BAM/CRAM and determines output encoding from `-o` extension.
- [SAMtools 1.24 faidx](https://www.htslib.org/doc/1.24/samtools-faidx.html): FASTA
  lookup indexing and subsequence retrieval.
- [SAMtools 1.24 view](https://www.htslib.org/doc/1.24/samtools-view.html): format
  conversion and the meaning of `-b`.
- [Official minimap2 README](https://github.com/lh3/minimap2): SAM output with
  `-a`, built-in reference indexing and optional reusable `.mmi` indexes. The
  pinned starter command and version above come from its exact manifest, not
  assumptions about the latest upstream release.
