# Curated training workflows and recorded results

The 2026-10-09 set builds on reference-management review head
`f45622f8915a3fa80c0904fcd97c216e0b5980f3`, on
`feature/curated-workflows-results`. Initial repository and remote inspection found no
saved implementation of this set. The handover established the scope but no
candidate version. This implementation assigns **0.16.0** to distinguish its
bytes from the frozen 0.15.0 reference-management candidate. Published 0.11.0
and the earlier unmerged draft branches remain unchanged. See the
[candidate handover](curated-workflows-results-0.16.0-handover.md) for evidence.

## Two synthetic training workflows

The native Curated workflows window describes each example before an explicit
load action. Loading configures the editable workflow; it does not start an
analysis, install tools or retrieve references. Existing workflow and standalone
editing sessions retain their established behavior. The original bundled
example remains available.

| Workflow | Inputs and operation | Expected answers |
| --- | --- | --- |
| Alignment with QC | Bundled artificial reference and 101 matched FASTQ read pairs; minimap2 paired alignment, SAMtools preparation and attributed statistics report. | 202 mapped, properly paired alignment records, a sorted/duplicate-marked BAM and CSI index; raw pair validation, flag counts and alignment statistics. |
| Variant calling | The same synthetic inputs, followed by diploid BCFtools calling and statistics. | One recorded SNP, `starter:1351 G>A GT=1/1`, with retained raw VCF/statistics. These are training truth checks, not biological validation or quality thresholds. |

`workspace/curated_workflows.py` fixes all pack versions and manifest hashes.
The catalogue selects published `align`, `bam` and `variants` **0.4.0**, even
when the separately installed align 0.4.1 candidate is available. Upstream
tools are minimap2 **2.28-r1209**, pair validator **1.0.1**, SAMtools **1.24** and
BCFtools **1.24**. The built-in report remains **0.5.0**. Missing or conflicting
dependencies block loading and identify the exact required pack; no silent
substitution occurs. File size and SHA-256 checks bind bundled fixture bytes.
The small, artificial inputs are retained under `examples/starter`; expected
answers are fixed in code and checked against the fixture's independent truth.

## Measurements and interpretation

`workspace/results_summary.py` builds summaries from recorded runs. Supported
SAMtools and BCFtools text outputs are read within explicit limits and verified
against their recorded SHA-256 before exposing measurements. Missing, changed,
unsupported or malformed data remain unavailable with an explanation. Results
can contain useful completed-step measurements even when another step fails;
the overall run state and per-step provenance remain visible.

There is **no application-invented sample QC pass/fail threshold**. Labels such
as mapped reads, duplicates or variants describe recorded tool measurements.
Fixture expected answers remain separate from scientific interpretation of a
user's sample. Raw outputs, methods, exact tool requirements and failure actions
remain accessible from the result's folder and summary.

Search uses recorded names, sample identities, run states and tools. It does not
scan arbitrary folders or scientific output contents. The host accepts recorded
run IDs, not caller-selected paths. Summaries are read-only and do not rewrite
results, rerun tools or change reference-library state.

## Integration and validation

The native host exposes `examples/list`, `examples/load`, `results/search` and
`results/summary`. Existing `example`, `history`, `run/get`, methods and folder
actions retain their contracts. Both new runtime modules are explicitly included
by `scripts/package_split.py` and in the corresponding source archive.

The [candidate workflow](../.github/workflows/native-curated-candidate.yml)
builds one exact source/Starter pair, then executes the new scientific/results
and native interface gate in ordinary and space-containing Windows paths.
Reference-management, recovery, batches/queue/indexes, readiness, resource,
library and workspace regressions use separate extractions of those same bytes.
The independent archive audit verifies transport and archive identities, source
correspondence, runtime inventory, unchanged published packs and production
profile/trust. Screenshot review is a separate recorded check.

Hosted synthetic checks do not establish representative-PC acceptance, high-DPI
or physical trackpad behavior, realistic Windows–Linux benchmarking, scientific
Linux CWL equivalence, executable signing/institutional deployment or release/
updater validation. No merge, tag, release or updater is part of this set.
