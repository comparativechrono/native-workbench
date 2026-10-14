# Kalign optional pack

**Merge update, 2026-10-13:** this pack stage and its dependent PR stack are now
merged into `main` at `9c9cdeacf35d1bf3aa60277f0fb05d5af41c6254` on the owner's
instruction. Source trees and candidate archives are unchanged by the merges.
The [integration receipt](evidence/stack-integration-2026-10-13.json) supersedes
only the draft/unmerged status in the original review handover below. No release
or catalogue publication occurred; validation and acceptance limits still apply.

Date: 2026-10-13. Status: **ready for unpublished draft review** in
[PR #17](https://github.com/comparativechrono/workbench/pull/17).

The owner requested merging the completed Prodigal/FastTree batch and proceeding
to Kalign. [PR #16](https://github.com/comparativechrono/workbench/pull/16) merged
into its existing `fix/native-ui-0.16.1` integration branch at
`8addaa1278c535e4931eb0b2b85b8f47b51ddd66`. Kalign is on `feature/kalign-pack`,
based on that merge. PR #15/main were not merged. Published application **0.16.0**
and the existing **0.16.1** UI candidate remain unchanged. No release or catalogue
publication is included; Kalign PR #17 remains draft and unmerged.

## Implementation

Independent pack `kalign` **1.0.0** provides explicit nucleotide and protein
multiple-sequence alignment from uncompressed, ungapped FASTA. It returns typed
MSA FASTA, recorded measurements, settings/sequence mapping and a scientific log.
The native guard preserves accepted IDs, full descriptions, input order and
ungapped residues, with actionable input/installation/output guidance.

Pinned upstream Kalign **3.5.1**, commit
`3e6de1df29d111c5fa5beb4c4294ef681978fd23`, archive SHA-256
`01bacb2205e7b6792c570b163b5ccc0713284737ba862ca3b500a96a8a4d1bd9`, becomes
**3.5.1-workbench1**. The retained patch changes the CLI alphabet boundary because
upstream composition guessing can misclassify valid sequences. Windows I/O/time
compatibility is a forced header. Upstream alignment/scoring routines are
unchanged. The initial interface is serial default alignment on baseline x86-64;
ensemble, refinement and custom penalties are outside scope. Both executable
identities, recipes, exact upstream source, patch/header, fixtures/reference and
embedded third-party/compiler notices are retained.

Homology and common orientation are scientific input requirements; an alignment
does not establish them. DNA scoring treats U as T and IUPAC ambiguity as N while
preserving displayed letters. Protein scoring uses the upstream PFASUM43/default
settings. See [the pack guide](../docs/KALIGN-PACK.md) for accepted alphabets,
bounds, downstream requirements and reproduction commands.

## Exact candidate and downloads

Tested source: **`8149bdc02a2104e97ea6512ae0a8bc76c8defc32`**.
Source tree: `27ecf6181bef93217a4218335311b4e2ca93fa58`.
Later delivery commits change knowledge/evidence only; these remain the tested
pack/validator identities. The source companion's creation-time pending status
is superseded by the final review index below.

- [Pack and complete source/evidence download](https://github.com/comparativechrono/workbench/actions/runs/38396201555/artifacts/11812411631)
- [Successful build and both Windows jobs](https://github.com/comparativechrono/workbench/actions/runs/38396201555)
- [Ordinary-path raw reports/screenshots](https://github.com/comparativechrono/workbench/actions/runs/38396201555/artifacts/11812306798)
- [Spaced-path raw reports/screenshots](https://github.com/comparativechrono/workbench/actions/runs/38396201555/artifacts/11812291802)
- [Final evidence index](evidence/kalign-1.0.0-final-review-2026-10-13.json)

Actions downloads expire **2026-11-12** and can require GitHub sign-in. Extract the
download, then use **Manage tools → Import pack ZIP** with
`native-workbench-pack-kalign-1.0.0.zip`. This is an optional pack, not an app ZIP.
Its minimum application version is 0.16.0. No signed catalogue entry is created.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Kalign pack ZIP | 2057266 | `f4c2ecb232673f5fff538155d3554712a52f3b5edc938dc04ad3202e9f2bf173` |
| Source/evidence ZIP | 6025727 | `776e7dcd94df3c9cc342b368d51469c070491dd1ee0d437197492f67a0bd2aa4` |
| Outer Actions download | 8089085 | `0045deb488be104725c325c81fb71370e7e7ce178eb3436dcb97106a99af1306` |

Manifest SHA-256:
`89779c41ac6b6c60eaacc3e477d20a10daedd7bd79ddf9654002d81a5e5054c7`.
The download audit matched **953 Git files** and **1103 companion inventory
entries**, including retained recipes/fixtures, source, compatibility changes,
licences, and both PE executable hashes. This is source/byte correspondence,
not independent bit-identical recompilation.

## Validation and retained correction

The hosted source suites passed **94 tests**, with one explicit Linux skip for a
Windows-only long-path filesystem test. The Kalign suite comprises two source
contracts, 15 science/failure tests and a fresh pristine Linux reference test
covering both independent nucleotide/protein indel fixtures. It passed all 18
with no skips. Linux execution is not native Windows evidence.

In **each ordinary and spaced Windows path**, the exact archive passed:

- Native import, two declared known-indel checks and duplicate-version rejection.
- All **17 selected source/science tests**, zero failures/errors/skips; these
  include 15 native scientific/failure tests. The separate pristine Linux class
  is excluded from Windows selection, not reported as skipped or executed.
- Real typed nucleotide and protein **Kalign → FastTree** graphs, exact saved
  pins, residue preservation and known six-taxon topology. FastTree is the
  immutable merged but unpublished 1.0.0 candidate from PR #16.
- Seven application checks, one Starter scientific workflow and five installed
  pack checks, with no skips. Results search, Methods/CWL and provenance passed.
- Seven GUI gate checks on unchanged 0.16.1; both forms were covered from their
  true first page to their last. Ten actual display screenshots per path were
  directly reviewed, with 20 separate PrintWindow captures retained in total.

All **20 actual display images** show readable wrapped names, descriptions,
forms and Results/provenance without a blocking captured layout defect. Scope:
1024×768 hosted desktop, 1024×728 application, 96 DPI. The 274 released-app and
277 UI-app files, and installed pack/dependency bytes, remained unchanged.
Overlapping assertions and repeated checks are not summed as unique coverage.

The [initial attempt](evidence/kalign-1.0.0-initial-attempt-2026-10-13.json),
source `3b8e2114ae596b14eb1c47a3bc9a8060802fe7cd`, failed one source contract on
both Windows paths: generated truth JSON used CRLF rather than canonical LF.
All 15 native scientific tests passed, but graph/Starter checks were not reached.
The generator now writes canonical UTF-8/LF bytes; the exact assertion was kept.
The corrected archive was rebuilt and fully revalidated. Initial archives and
reports remain historical, not recommended installation bytes.

## Limits and next work

Pack JSON measurements remain output files. The unchanged native Results panel
shows recorded status, exact versions/provenance and search, but no parsed Kalign
measurement tiles and no invented QC pass thresholds. Its unavailable-measurement
message is expected. GUI checks inspect recorded runs; execution used the actual
private native host, not an automated GUI Run-button assertion.

Small synthetic fixtures do not establish general alignment accuracy, orthology,
large-data limits, memory/time forecasts or clinical validity. ASCII paths are
required; spaces are supported. Downstream FastTree has its own count, length
and alphabet requirements. Normal analysis is local, but the private-host socket
block is not an OS-level network isolation claim.

Representative-PC/high-DPI/multiple-monitor/physical-trackpad acceptance,
scientific Linux CWL, executable signing/institutional deployment, realistic
benchmarking and release/updater validation remain separate. The broader tool
roadmap is unchanged; Primer3 and PLINK2 require separately bounded interfaces.
Do not merge PR #17 or publish its candidate without the owner's next instruction.
