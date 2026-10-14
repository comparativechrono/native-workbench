# Validation, releases and publisher trust

## Published curated workflows/results release, 0.16.0

The exact packaged source is `e855dc4396e0c16ae35f4e840eb9cc734adb4441`.
[Candidate run 37952018931](https://github.com/comparativechrono/workbench/actions/runs/37952018931)
passed 488 Linux source tests/four Windows-only skips and 332 Windows tests/four
platform or privilege skips per path, plus exact packaged native feature and
regression gates. The [candidate workflow](../.github/workflows/native-curated-candidate.yml)
builds one matching source/Starter pair. The independent audit matches its
748 current source files to Git and checks archive/core/pack/runtime identities.

[Updater run 37952583789](https://github.com/comparativechrono/workbench/actions/runs/37952583789)
derives the core update from that frozen Starter without rebuilding the app.
Its 18 main checks per Windows path start with actual published 0.11.0 private
runtime behavior and preserve old results, references, settings and packs.
Eleven nested curated checks and seven installation checks without the extra
pack are separately scoped. Explicit import of align 0.4.1 is verified; the
updater does not install it implicitly. The folder picker is not covered.

[Release-check run 37952595124](https://github.com/comparativechrono/workbench/actions/runs/37952595124)
runs results/CWL/DAG/icon and scrolling gates in ordinary/spaced paths and a
four-check positive long-path gate. The release-specific `_0160` validators
retain frame assertions and require both Starter and extra-pack scientific
truth with disabled long-path opt-in and restored runner policy. The additional
alignment uses a 254-character native cwd and 268-character SAM path; native
working directories at or above 260 characters remain unsupported.

The [release lock](evidence/curated-workflows-0.16.0-release-lock.json) binds exact
archives, run/job/step conclusions, original report hashes, helper-source commits
and screenshot identities. `scripts/publish_app_0160.py` verifies the complete
lock in a read-only preparation, requires the exact merged main/PR12 identity,
refuses existing tag/release replacement, promotes accepted bytes unchanged and
rehashes every public asset after publication.
[Publication run 37955110070](https://github.com/comparativechrono/workbench/actions/runs/37955110070)
verified all 13 assets. Publication/tag commit is
`60243d45a81a6ef7e16e4a0ee719f4aa2e4f74c9`, distinct from the packaged source; actual
download evidence is in the [receipt](evidence/curated-workflows-0.16.0-public-downloads-2026-10-09.json).

See the [release handover](curated-workflows-0.16.0-release-handover.md),
[archive audit](evidence/curated-workflows-0.16.0-release-archive-audit-2026-10-09.json),
[updater evidence](evidence/update-0.16.0-final-validation-2026-10-09.json),
[release regressions](evidence/curated-workflows-0.16.0-release-regression-final-2026-10-09.json)
and [visual review](evidence/curated-workflows-0.16.0-release-visual-review-2026-10-09.json).
Recorded QC measurements require valid output provenance; missing/corrupt data
does not become zero or a QC pass. Fixture answers remain separate from
biological acceptance thresholds. Hosted 96-DPI, CLI updater and offline
private-host checks retain their documented limits.

## Historical candidate validation protocols

The candidate sections below retain their original named bytes, scope and
publication status. Their earlier pending/release statements are historical.
The rejected `7a9aca7` and superseded `a447997` 0.16 candidates, old updater
attempts and original immutable source companions remain retained; no old pass
is relabelled as validation of the final `e855dc4` archives.

## Reference-management candidate, 0.15.0

The [candidate workflow](../.github/workflows/native-reference-management-candidate.yml)
builds one matching source/Starter pair and runs separate exact Windows gates in
ordinary and spaced paths. New evidence must distinguish live provider downloads,
deterministic Range/checkpoint fixtures, offline local operations and native GUI
interaction. The [feature guide](reference-management.md) defines the contracts;
the [handover](reference-management-0.15.0-handover.md) records actual results.

Resume validation must reject changed prefix/discovery identities, never append
an invalid range and never expose partial bytes as a ready input. Import and
relocation require reviewed source/receipt identities, rehashed copies, atomic
registry changes and cancellation/failure preservation. Relocation must retain
old paths and frozen-plan/provenance bytes. NCBI assembly identity must remain
distinct from mutable annotation observations, and imported metadata must remain
explicitly user-declared. Neither a source pass nor a Linux provider download is
an exact packaged Windows or release/upgrade pass.

The accepted development candidate combines exact feature evidence from run
37855047291 with validator-only recheck 37857029068. The latter passed batch and
all 15 Windows source invocations on the unchanged Starter. Original failures,
skips, unchanged archive identity and separate scopes are retained in the
[final combined record](evidence/reference-management-0.15.0-final-validation-2026-10-08.json).
This completes the recorded hosted gates, not publication or baseline-upgrade validation.

## Recovery, resource budgets and portable projects, 0.14.0

The [candidate workflow](../.github/workflows/native-recovery-candidate.yml)
builds matching source/Starter archives and preserves published pack/runtime,
profile and trust identities. The [feature guide](recovery-projects.md) defines
explicit CPU admission rather than OS CPU enforcement, completed-step restart
rather than within-tool checkpoints, and bounded offline project imports.
The [handover](recovery-projects-0.14.0-handover.md) records current status.
Final source `0e2d5cbcbf1786d6e1723f8466b4b6b94da04802` passed
[run 37842857764](https://github.com/comparativechrono/workbench/actions/runs/37842857764)
with 289 source passes/four skips and all configured exact Windows gates in
both paths. The handover links the final source, Windows and independent archive
records and retains superseded failed runs. This is an unpublished tester
candidate; no baseline upgrade, updater or release gate is implied.

The recovery gate must distinguish unmodified packaged application execution
from a separate instrumented abrupt-interruption fixture. Restart evidence
requires changed-input/parameter/pin/output invalidation, original-result
preservation and meaningful scientific output assertions. Concurrency checks
must observe actual independent native step overlap and declared-budget limits;
small fixtures do not constitute a capacity or speed benchmark. Project checks
cover missing exact dependencies, explicit same-byte mapping, moved folders,
integrity failures and offline execution without installing or substituting
packs. External stock-CWL Linux fixture execution is a separate bounded claim.

Independent downloaded-archive inspection uses
[`audit_recovery_candidate.py`](../scripts/audit_recovery_candidate.py), exact
commit file comparisons, complete runtime inventories, transport/inner hashes
and ZIP CRCs. It performs no native execution and publishes nothing.
No update or release gate is implied by candidate validation.

## Batch, queue and reusable-index candidate, 0.13.0

The [candidate workflow](../.github/workflows/native-batch-candidate.yml) binds
one standalone Windows archive and its corresponding source to exact commit and
SHA-256 identities. The [batch gate](../scripts/check_batch_windows.py) separately
checks explicit sample mapping, paused queue persistence, frozen plan/input
integrity, serial execution and cancellation, known synthetic alignment/variant
truth, real minimap2 index build/reuse/corruption behavior, and the native
Samples/Queue/Reference indexes controls. It retains failures and captures in
ordinary and space-containing paths. Source subprocess-death tests exercise
queue ownership and index lease recovery; a clean reopen check alone is not
evidence for abrupt interruption.

Existing readiness, process accounting, tool-library and workspace gates run
against separate extractions of the same archive. Counts from these scopes must
remain distinct. No benchmark, physical display/trackpad acceptance, live
reference download, production Full setup or updater pass may be inferred from
this candidate. Record actual results in [current state](current-state.md) and
dated evidence before calling the candidate validated. This workflow publishes
temporary Actions artifacts, not a GitHub release.

The [0.13.0 handover](batch-queue-indexes-0.13.0-handover.md) records the passing
final candidate and retained initial failures. The final exact-package gate also
holds real external queue/history read handles: short conflicts must commit
after release; a persistent conflict must preserve the old receipt and jobs,
leave no new plan, and report failure within the tested bounded wait. Controlled
source tests and native filesystem tests remain distinct evidence.

## Scrolling frames, 0.8 candidate

`scripts/check_scroll_frames_windows.py` complements the settled-image comparison
in the existing native UI gate. It runs the exact packaged executable/private
Python and samples the actual desktop with screen `BitBlt`, not `PrintWindow`.
Clean reference captures may request repaint; observed scrolling frames must
not. A reusable DIB and `GdiFlush` make the captured pixel bytes available;
`DwmFlush` is only a presentation timing aid, not a barrier for the application's
paint processing or a guarantee of observing every display frame.

The gate covers standalone options, workflow options and general settings in
the supported minimum-height window. Each panel receives fifty down/up wheel
cycles and repeated wheel events at both boundaries. Mask finite edit/button
regions to exclude caret and hover animation, normalize unused alpha bytes,
and retain static text/background. Require distinct masked endpoint images,
sufficient text pixels, and each requested endpoint's visible bitmap and
scroll offset. A test that only accepts either endpoint could falsely pass an
unmoving screen. Unexpected intermediate frames, unmatched endpoint positions,
timing and captures remain in the evidence.

Separate native message checks exercise tiny positive/negative wheel deltas
through the panel and a child edit. Label these sent Windows messages honestly:
they verify fractional accumulation and routing, not physical trackpad hardware.
The existing settled-text, full native UI, References/update and long-path
scientific gates remain applicable to the same candidate.

The optional exact previous package is a diagnostic comparison. A missed flash
in finite samples is not proof of no flicker; an unavailable diagnostic is
unrun, never passed. The fixed-package frame and precision checks remain
mandatory. Preserve the dated [scroll evidence](evidence/native-workflow-0.8.0-scroll-2026-10-06.json)
alongside earlier settled-image results rather than broadening their scope.

## Nested Windows result-path regression, 0.8 candidate

`scripts/check_long_paths_windows.py` uses the exact packaged private host's
**Check installation** action and the pinned five-step starter scientific
profile. Its dedicated job in `native-workspace-ui-check.yml` disables ordinary
long-path opt-in only on a disposable hosted Windows runner, starts fresh
processes, proves ordinary and extended file probes differ, and restores the
previous policy in `finally`. Application execution must never change a user's
machine policy or require administrator privileges to apply this fix.

The corrected package must complete alignment, BAM preparation, variant
calling, statistics and reporting, preserve the pinned scientific truth, and
independently rehash every output. The regression isolates long result files
while keeping the installation root and native working directory short. An
unchanged previous candidate supplies a separately reported negative control
while its artifact is available. Its expiry may mark that diagnostic unrun,
never passed; the corrected-package regression remains mandatory. Keep the
old failure, new success, policy setup/restoration and exact artifact identities
in the [dated evidence](evidence/native-workflow-0.8.0-long-path-2026-10-06.json).

`workspace/tests/test_engine_paths.py` complements this with real files under
an emulated path limit, synthetic backend execution, canonical identity and
containment/hash/link regressions. Its source pass is not native Windows proof.

## Reference application gate, 0.7

The initial reference provider is tested separately from tool-pack algorithms.
Source tests in `workspace/tests/test_reference_*.py` cover release-specific
discovery, restricted HTTPS redirects, metadata limits, immutable selections,
streaming gzip/BSD/SHA checks, cancellation, publication rollback, receipt
agreement, local file changes, typed input binding and frozen methods. They use
deterministic synthetic network responses and do not establish Windows GUI
behavior.

`scripts/check_references_windows.py` exercises a disposable, exact application
archive with public Ensembl release 116 yeast data. Independent compressed and
expanded SHA-256 values are pinned for genome, GTF, cDNA, ncRNA and protein files.
The check cancels an in-progress transfer, downloads a complete selection, starts
a separate socket-denied host, binds a local reference and runs native SAMtools
indexing against all 17 contigs. It retains methods, receipts, results and native
window captures. Linux invocation must explicitly skip GUI and native analysis;
that evidence must never be reported as a Windows pass.

`.github/workflows/native-reference-check.yml` dispatches against an exact starter
asset and SHA-256, with ordinary and space-containing installation paths. It
uses read-only repository permissions. An optional exact updater payload checks
0.6.0-to-0.7.0 migration, core identity and preservation of user data and pack
fixtures. The updater transaction uses its separate interpreter so it does not
lock the target runtime's DLLs. The GUI smoke and captures do not constitute
full manual acceptance on managed PCs, multi-monitor/high-DPI configurations,
Unicode/long paths, human genomes or institutional proxies.

Candidate evidence and final public-asset evidence remain distinct. Keep the
exact app, updater, source and gate hashes with each report; never overwrite
published candidate bytes after a fix. The source companion records evidence
available at creation time. A later final-gate report can supersede its pending
release status without replacing the archive.

## Earlier validation baseline

Status: maintained handover, audited against repository commit
`1b537869e9d88e493078e1a1f241d16013273f44` on 2026-10-04.
This is an operational procedure, not a claim that every historical pack has
passed every gate. See [the knowledge index](README.md) for current status and
[pack development](pack-development.md) for authoring contracts.

## Separate the kinds of evidence

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| Archive/static validation | Schema, inventories, identity, declared hashes and safe paths | Scientific correctness or executable startup |
| Core unit/contract tests | Parser, graph, trust, transaction and reporting behavior covered by those tests | Operation of every optional tool |
| Linux scientific execution | Known-answer/upstream agreement for the identified Linux binaries | Native Windows execution |
| Native Windows pack gate | Real execution through a released app's native bridge, import and fixture checks | Full GUI behavior, every path, large datasets or clinical validity |
| Manual Windows deployment/UI check | The recorded interactions on that machine and policy configuration | Approval in other institutions or unrestricted platform support |
| Real-data benchmark | Specified dataset, truth, versions, parameters and resources | General accuracy or all protocols |

Always record failed and skipped checks, substituted backends and exact tested
versions. A suite that silently skips because compiled fixtures are absent is
not evidence of a working release. The historical app test count is a dated
observation, not a permanent release target.

## Scientific verification method

Use small, public/synthetic fixtures with independent expected answers. Include
the actual biological properties relevant to the tool: sequences, mapping
positions/CIGAR/flags, splice junctions, alleles/genotypes, abundance estimates,
or expected absence of calls. Avoid producing expected results solely by running
the same implementation. A pinned upstream implementation is useful as a second
comparison, alongside known truth.

Exercise the normal graph engine and actual UI defaults. Include paired/single
operations, relevant compression and strand modes, malformed or incompatible
inputs, empty valid outcomes, optional features and meaningful concurrency.
Validate that failure does not yield apparently complete successful results.
Use tolerances only with a scientific reason; retain exact outputs/hashes where
determinism permits. A seed can be reproducible within a build without ensuring
identical draws across different standard-library implementations.

`workbench-checks.json` uses bounded assertions and pinned fixture assets, not
embedded commands or Python expressions. The ordinary installed backend runs
them through **Check installation**. Add richer regression cases in `tests/`
where fixture assertions cannot express the required property. Relevant code:
[pack checks](../workspace/pack_checks.py),
[scientific metadata](../workspace/PACK-METADATA.md), and
[independent FASTQ oracle notes](../tests/README.md).

For source changes, run focused tests covering the affected contract and any
required release gate. Core application tests should use artificial packs and
not require every optional scientific tool. Optional packs get independent
validation. Do not repeatedly run a broad suite simply to increase a count.

## Released-app compatibility

Test against the oldest declared supported app and the current app. Loading a
new pack into edited checkout code does not prove compatibility with a shipped
application. Keep the released app and starter packs unchanged, verify their
hashes, and use a disposable extraction for each test.

The RNA contract suite checks the released 0.6.0 Python graph/archive contracts
without running scientific executables. Run it in a fresh Python process, with
both exact RNA pack versions present in the disposable released app and their
ZIPs available. Explicitly set the kallisto version: the suite's historical
default is 1.0.0, while the current version is 1.0.1.

```sh
NW_RNASEQ_APP_ROOT=/path/to/disposable/native-workbench \
NW_RNASEQ_ARCHIVE_DIR=/path/to/rna-pack-zips \
NW_RNASEQ_STARTER_ZIP=/path/to/native-workbench-0.6.0-starter-windows.zip \
NW_RNASEQ_STAR_VERSION=1.0.0 \
NW_RNASEQ_KALLISTO_VERSION=1.0.1 \
python3 tests/test_rnaseq_pipeline.py --report /path/to/evidence/rna-contracts.json
```

The app tree must be assembled beforehand with the exact packs; this command
does not fetch or assemble it. Its archive import test substitutes a copy
callback for native folder publication and explicitly reports that no native
importer or scientific executable ran. Do not describe this as the Windows gate.

The October pack contract suite additionally checks FastQC fan-in to MultiQC,
STAR RNA BAM fan-out to featureCounts branches, merged reporting, BEDTools FASTA
to BLAST, rejection of DNA/RNA and protein/nucleotide mismatches, explicit strand
choices and saved pins. It also compares every selected pack folder with its
exact ZIP payload. Like the RNA contract suite, its archive publication uses a
Python copy callback and runs no scientific executables or native importer.

```sh
NW_POPULAR_STARTER_ZIP=/path/to/native-workbench-0.6.0-starter-windows.zip \
NW_POPULAR_PACK_DIR=/path/to/prepared-packs \
NW_POPULAR_ARCHIVE_DIR=/path/to/exact-final-zips \
NW_POPULAR_STAR_ARCHIVE=/path/to/native-workbench-pack-star-1.0.0.zip \
NW_POPULAR_TEMP_DIR=/path/to/disposable-applications \
python3 tests/test_popular_pipeline.py --report /path/to/evidence/popular-contracts.json
```

The [2026-10-04 report](evidence/popular-pack-graph-contracts-2026-10-04.json) records
8/8 passing tests with no failures, errors or skips on Linux/Python 3.12.14.
Its SHA-256 is
`5c4d53d4067070b09af5d3e7698b3fbb06fcba92e4a454ff7d70c4fd7ae4f0ad`.
The first attempt failed the strict immutability assertion when an unexplained
transient Java source file disappeared from a prepared pack. A fresh run passed
without changing pack bytes, weakening assertions or replacing the failed record.
Its diagnostic record remains separate from this successful final report.
The [earlier successful proposal report](evidence/popular-pack-graph-contracts-before-blast-diagnostics-2026-10-04.json)
is also retained with its original hashes. Its old BLAST guard later failed
native error-output checks, so the suite was rerun against the corrected final
archive. The current suite compares the archive against the actual disposable
graph-tested pack copy, avoiding races with another build's preparation folder.

All five packs and STAR are required. Per-pack `NW_POPULAR_<ID>_PACK_DIR` and
`NW_POPULAR_<ID>_ARCHIVE` overrides select isolated frozen builds. A missing-pack
skip is not a passing compatibility check. See current release evidence for the
recorded run rather than assuming the command has been run on a fresh checkout.

For GATK 1.0.0, use the [pack guide](../docs/GATK-PACK.md) to recover the exact
released starter and prepare/package the frozen pack, then run in a fresh
process:

```sh
NW_GATK_STARTER_ZIP=/path/to/native-workbench-0.6.0-starter-windows.zip \
NW_GATK_PACK_DIR=/path/to/gatk-1.0.0 \
NW_GATK_ARCHIVE=/path/to/native-workbench-pack-gatk-1.0.0.zip \
NW_GATK_TEMP_DIR=/path/to/disposable-applications \
python3 tests/test_gatk_pipeline.py --report /path/to/evidence/gatk-contracts.json
```

The seven graph/archive contracts cover standalone discovery, the pack-owned
BAM preflight helper, two-sample preparation and gVCF merging, joint-genotyping
branches, named methods/pins, RNA/type/order rejection and strict archive/import
immutability. The graph suite does not execute scientific tools and substitutes
a Python copy callback for native folder publication, including when its host
is Windows. The separate native installation gate exercises the real importer
and scientific runner.

During the Linux GATK graph runs, six graph/application tests passed while the
strict archive-copy test observed transient temporary files or altered hashes
inside disposable copies. Retain those failed diagnostics; do not describe them
as seven passing Linux tests or exclude files to make the check pass. The same
strict suite passed all seven contracts in both Windows paths on the candidate
and exact final archive. The [GATK validation record](evidence/gatk-1.0.0-validation-2026-10-04.json)
records the distinct stages and exact hashes.

### Annotation, expression, coverage and phylogenetics contracts

`tests/test_next_pipeline.py` checks SnpEff, DESeq2, mosdepth and IQ-TREE against
the unchanged released 0.6.0 starter. Do not confuse it with the older
`tests/test_expansion_pipeline.py`. Run in a fresh process and select one pack
for its independent release gate, or several for local integration. Each selected
archive is required; CLI execution fails on missing prerequisites. Ordinary test
discovery may skip absent optional builds, which is not release evidence.

| Environment variable | Meaning |
| --- | --- |
| `NW_EXPANSION_PACK_IDS` | Comma-separated `snpeff,deseq2,mosdepth,iqtree`; defaults to all four |
| `NW_EXPANSION_STARTER_ZIP` | Exact SHA-pinned released 0.6.0 starter |
| `NW_EXPANSION_TEMP_DIR` | Parent for disposable application copies |
| `NW_EXPANSION_<ID>_VERSION` | Expected numeric pack version; defaults to `1.0.0` |
| `NW_EXPANSION_<ID>_ARCHIVE` | Exact installable ZIP for that selected pack |
| `NW_EXPANSION_<ID>_PACK_DIR` | Optional prepared/installed folder; absent means extract the exact ZIP for graph tests |
| `NW_EXPANSION_MUSCLE_ARCHIVE` | Pinned published MUSCLE 0.5.2 dependency for IQ-TREE |
| `NW_EXPANSION_FEATURECOUNTS_ARCHIVE` | Pinned published featureCounts 1.0.0 dependency for DESeq2 |
| `NW_EXPANSION_KALLISTO_ARCHIVE` | Pinned published kallisto 1.0.1 dependency for DESeq2 |

Use uppercase IDs in variable names, for example:

```sh
NW_EXPANSION_PACK_IDS=mosdepth \
NW_EXPANSION_STARTER_ZIP=/path/to/native-workbench-0.6.0-starter-windows.zip \
NW_EXPANSION_MOSDEPTH_ARCHIVE=/path/to/native-workbench-pack-mosdepth-1.0.0.zip \
NW_EXPANSION_TEMP_DIR=/path/to/disposable-applications \
python3 tests/test_next_pipeline.py --report /path/to/evidence/mosdepth-contracts.json
```

The suite uses real published dependency descriptors. It checks standalone
operations, typed branches/merges and source ordering, methods, separate presets
and pipeline saves, changed-pin rejection, payload identity, unchanged released
app/starter files, archive import and duplicate-version immutability. It does
not execute a scientific pipeline: broad `metrics`/`file` connections still need
adapter checks and scientific tests. Archive publication substitutes a checked
Python copy callback for the native importer, even on Windows.

Preserve strict failed-copy diagnostics from managed Linux workspaces; transient
files in a disposable tree are not permission to exclude inventory entries or
weaken immutability assertions. Retain the reports and exact artifact hashes,
remove reconstructible copies when needed, and use the independent native gate
for Windows evidence. Historical success on an earlier archive does not validate
a subsequently changed adapter, license tree or manifest.

### Metagenomics resource, graph and scientific contracts

`tests/test_metagenomics_resources.py` checks the shared descriptor and local
archive helper with synthetic byte files. Its successful source run covers
resource identity, paired fragment accounting, relocation, unused absent
indexes, declaration validation before expensive hashing, archive bounds,
disk checks and failure cleanup. It does not execute Kraken2, Bracken, the app,
or a native importer. Record the exact helper SHA and platform with its result;
do not describe this unit suite as scientific or Windows evidence.

`tests/test_metagenomics_pipeline.py` uses unchanged released Workbench 0.6.0
and exact selected pack archives. The primary disposable app contains starter
plus selected packs to establish standalone discovery. A second app adds
SHA-pinned prerequisites for connections. Kraken-only selection requires the
published fastp 0.4.1 archive; Bracken-only selection requires an explicitly
pinned frozen Kraken2 archive. The latter is a testing dependency, not a
requirement for Bracken's independent external-report operation.

Use `NW_METAGENOMICS_PACK_IDS=kraken2`, `bracken`, or `kraken2,bracken`, with
`NW_METAGENOMICS_STARTER_ZIP`, `_TEMP_DIR` and selected
`NW_METAGENOMICS_<ID>_VERSION`, `_ARCHIVE`, optional `_PACK_DIR`. Bracken-only
gates additionally require `NW_METAGENOMICS_KRAKEN2_SHA256`; Kraken selection
uses `NW_METAGENOMICS_FASTP_ARCHIVE`. Run in a fresh process:

```sh
python3 tests/test_metagenomics_pipeline.py --report /path/to/evidence/metagenomics-contracts.json
```

The expected graph counts are six for Kraken2, seven for Bracken and nine for
both. These tests cover standalone operation, source provenance, typed edges,
branch ranks, presets and pinned pipelines, exact archive payloads, duplicate
imports and unchanged core files. Archive publication uses a checked Python
copy callback, not the native importer. Generic file/metrics connections cannot
establish database/model association, report structure, read lengths or counting
units; the adapters and scientific suites must establish those properties.
Missing CLI prerequisites or skipped cases must fail the gate.

The native workflow has separate installation, graph and scientific gates for
each metagenomics pack. It uses a source-committed dependency lock at
`tools/metagenomics/native-dependencies.json`, verifies the chosen dependency
archive and checks out regression sources at the workflow commit. Both ordinary
and space-containing paths are required. Bracken's scientific command includes
`--kraken2-archive` to execute the actual classification-to-estimation chain;
an earlier source-only fixture record does not replace that chain. Keep
installation checks, helper/resource tests, graph contracts and real scientific
execution distinct in the final report. Candidate and exact-final archives each
need their own gates and immutable source/provenance evidence.

Small synthetic metagenomics data can establish known assignments, abundance
arithmetic, no-hit behavior and portability regressions. It cannot establish
accuracy of an arbitrary downloaded database, large-database memory/performance,
clinical pathogen detection or GUI behavior. Source documentation of a gate is
not evidence that a release has passed it; use dated exact-archive records.

## Native Windows pack gate

Package once, freeze the archive, and calculate its SHA-256. On Windows, use a
fresh extraction of a SHA-verified released application. From a developer
checkout, using the released application's bundled Python:

```powershell
& C:/ci/app/native-workbench/runtime/python/python.exe -I scripts/check_pack_release_windows.py --app-root C:/ci/app/native-workbench --archive C:/releases/native-workbench-pack-example-1.0.0.zip --report C:/ci/evidence/native-pack.json
```

The [gate](../scripts/check_pack_release_windows.py) refuses Linux, imports the
archive through the released app, executes the pack's declared checks using
`WorkbenchBridge.exe`, requires nonzero successful checks, and verifies
duplicate-version rejection without manifest replacement. It performs no
network requests. It modifies the disposable app; do not point it at a user's
working installation. Retain the JSON evidence and check
`nativeWindowsHost`, `nativeWindowsExecuted`, exact pack identity, check results,
duplicate rejection and success rather than quoting only the process exit code.

The repository's manually dispatched
[Native Windows pack check workflow](../.github/workflows/native-pack-check.yml)
takes `release_tag`, exact `asset_name` and `asset_sha256`. It runs on
`windows-2022` in two paths, `ordinary` and `path with spaces`. It verifies the
candidate archive and the released starter, then downloads the check helper
from the workflow's exact source commit. The pinned starter is:

- Release: [app-v0.6.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.6.0)
- Asset: `native-workbench-0.6.0-starter-windows.zip`
- SHA-256: `16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a`

The workflow uses `contents: read`, has no catalogue key and publishes nothing.
Its release lookup currently examines the first 100 releases. Older releases
outside that page need a reviewed lookup improvement. Despite the input label
mentioning drafts, the read-only workflow token did not see draft candidates in
the RNA release work. Use separately versioned, clearly labelled public
prerelease candidates when needed; do not broaden token privileges simply to
make a draft visible.

Extra regressions have deliberately narrow scope:

- `check_star_chunks_windows.py` runs for the exact STAR 1.0.0 asset and checks
  repeated input/output chunks using real paired alignments and gene counts.
- `check_kallisto_defaults_windows.py` runs only for the old kallisto 1.0.0 asset,
  whose original fixture used one thread. kallisto 1.0.1's own installation checks
  now use two threads and three bootstraps. Do not apply the old helper's
  one-thread-fixture assumption to 1.0.1.
- `tools/blast/check_offline.py` runs for BLAST pack assets. It checks installed
  hashes, known alignment coordinates in a directory with spaces, missing local
  database failures, malformed FASTA and rejection of remote arguments. Its
  explicit `osNetworkBlocked: false` records that CI did not disable networking;
  the regression is code-path evidence, not a firewall test.

For SnpEff, DESeq2, mosdepth and IQ-TREE assets, the workflow runs three distinct
gates: native installation/declared fixtures, `test_next_pipeline.py` released-app
contracts, and `tests/test_<id>_pack.py` scientific/failure regressions against the
installed exact archive. IQ-TREE regressions additionally execute the pinned
MUSCLE dependency for real alignment-to-tree checks. The workflow selects the
one pack identified by the asset, verifies dependency archives, and records the
helper source commit. Both ordinary and space-containing paths are required.

Graph and scientific diagnostic steps use `always() && !cancelled()` so an
installation-fixture failure does not hide independent evidence. This is not
`continue-on-error`: any failed gate still fails the overall job. Preserve each
report and the final job outcome; a later successful step cannot turn a failed
installation into a passing release.

The [DESeq2 development workflow](../.github/workflows/deseq2-development-check.yml)
is a separate diagnostic path. It recovers private R, prepares a disposable pack
from checkout source and runs native statistical/failure regressions, retaining
runtime versions and reports. It does not download/import the frozen published
pack and cannot replace its exact-archive native gate. Likewise, the
[R runtime workflow](../.github/workflows/build-r-runtime.yml) establishes pinned
installer recovery/relocation, not DESeq2 scientific correctness. Keep source-only
development evidence separate from candidate correspondence and final release
evidence. Runtime/source companion hashes must remain bound to the final pack;
publish the matching companion beside every release distributing that runtime.

The matrix alone does not prove Unicode/long-path support, offline network
blocking, cancellation, interactive GUI behavior or institutional deployment.
Record those separately, including expected rejection for a pack's declared
path limitations. Test upgrades beside old versions, saved graph pins, unchanged
inputs, failed subprocess cleanup and methods/provenance. Test real offline
behavior with networking disabled after obtaining approved installers.

## Freeze, publish and verify

1. Assign the stable pack ID and a new numeric pack version. Finalize executable,
   metadata, README, fixtures and license/source contents before packaging.
2. Run `scripts/package_split.py pack` and
   `scripts/validate_pack_release.py`; retain the reported archive/manifest
   hashes and inventory. Review the actual ZIP contents, not only local build
   folders. Test the exact candidate on native Windows.
3. Retain matching source, build/patch provenance, dependency notices and test
   evidence. If candidate and final versions differ, record the exact allowed
   differences and compare executable/command/schema/fixture bytes. A successful
   candidate does not excuse checking the exact final archive.
4. Publish independent tags `pack-<id>-v<version>` in this repository, with the
   installable ZIP and matching source/evidence assets. Application releases use
   `app-v<version>`. Preserve older tags/assets for saved pins. A failed published
   version receives a new version with a clear explanation, never replacement
   bytes under the old identity.
5. Download every final public asset independently and compare its size and
   SHA-256 with the frozen local artifact. Verify committed source bytes too.
   Run the native gate on the **exact final archive**, retain its run URL/report,
   and update release notes to describe actual results and remaining limits.
6. Once publisher trust is provisioned, publish a newly signed catalogue only
   after all its immutable asset URLs/hashes have been verified. Complete a
   clean-client refresh/download/install test before announcing online availability.

Testing a final archive may require publishing it first for the read-only CI
workflow to fetch it. Keep its status clearly identified as under validation
until that gate passes. Publication is not evidence of validation. Likewise, do
not promote a historical candidate or stale draft simply because its asset name
resembles the final release.

Build-time provenance may correctly say `windowsExecuted: false` because the
builder performed no Windows execution. Keep that record intact and attach
subsequent native evidence to the exact archive hash. Editing the archive to
change the flag would invalidate the artifact that was tested.

## Known exact-final release evidence

These records provide concrete examples of the method. They are small scientific
regressions, not human-scale performance benchmarks or clinical validation.

| Final pack | Exact final native run | Recorded scope |
| --- | --- | --- |
| [STAR 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-star-v1.0.0) | [37149903110](https://github.com/comparativechrono/workbench/actions/runs/37149903110) | Five scientific checks per path, plus repeated-chunk paired alignment/count regression at two threads |
| [kallisto 1.0.1](https://github.com/comparativechrono/workbench/releases/tag/pack-kallisto-v1.0.1) | [37150386848](https://github.com/comparativechrono/workbench/actions/runs/37150386848) | Single/paired gzipped-read truth at two threads and three bootstraps in both paths |
| [FastQC 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-fastqc-v1.0.0) | [37207251061](https://github.com/comparativechrono/workbench/actions/runs/37207251061) | Two checks per path: plain single/gzip paired reads, bases, GC, Q40 and report truth |
| [MultiQC 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-multiqc-v1.0.0) | [37208730673](https://github.com/comparativechrono/workbench/actions/runs/37208730673) | One aggregation case per path with six selected reports and all five supported parsers |
| [featureCounts 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-featurecounts-v1.0.0) | [37208535793](https://github.com/comparativechrono/workbench/actions/runs/37208535793) | Six checks per path, single/paired counts, three strand modes and two threads |
| [BEDTools 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-bedtools-v1.0.0) | [37207758617](https://github.com/comparativechrono/workbench/actions/runs/37207758617) | Fifteen checks per path, including CRLF, empty outputs, 64-bit coordinates and strand extraction |
| [BLAST 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-blast-v1.0.0) | [37210341211](https://github.com/comparativechrono/workbench/actions/runs/37210341211) | Five scientific checks plus six adapter/local-failure regressions per path; four search modes, coordinates/frames, no hits, spaces, missing databases and invalid/remote arguments |
| [GATK 1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-gatk-v1.0.0) | [37220420948](https://github.com/comparativechrono/workbench/actions/runs/37220420948) | Nine scientific checks plus seven graph/archive contracts per path; all nine exposed operations, known alleles/genotypes, duplicate/recalibration truth, typed branches and real file fan-in |

STAR final ZIP SHA-256:
`edbeefff1c1149b632407f50a8a28847989a34eaa004752b43680fb6e29e4877`.
kallisto final ZIP SHA-256:
`641cd1f2b05e0951b1f8a58f45d6308ca6206bf86bf90fb74d0daa2860f5eecd`.
The releases carry `native-workbench-star-1.0.0-windows-validation.json` and
`native-workbench-kallisto-1.0.1-windows-validation.json`, respectively, and
matching source/evidence companions. Historical candidate reports inside a
companion are not a substitute for the final archive's validation report.

Exact new archive hashes, final Windows evidence assets and matching source
companions are recorded in [the inventory](release-inventory.json). Every gate
also imports through the native bridge and verifies duplicate-version rejection.
The source/evidence ZIPs retain their creation-time status; separate final JSON
records supersede historical pending-final statements. BEDTools' source companion
contains an empty static-validation log; its separate final JSON supplies a fresh
complete static inventory/schema/hash verification. Preserve the published ZIP
and this explicit correction rather than silently replacing it.

GATK's exact final gate ran at source
`eb4a255b69a2eabfb539937218a1d0e57c5776a3` in ordinary and space-containing
`windows-2022` paths, with no failures/errors/skips. Its final archive SHA-256 is
`e9eb3a4966f83d667ebb424612aaedd07236bac98c3462d4efbe02c55166bb24`; its manifest
SHA-256 is `4d876053d922628f8c97896268a32c72a648b6c51b93d3364beecc641293e713`.
The release supplies `native-workbench-gatk-1.0.0-windows-validation.json` and
`SHA256SUMS.txt`. The source companion preserves the 14 passing Linux
scientific/regression tests, candidate evidence, failed Linux copy diagnostics
and its creation-time pending-final status. The separate final report closes
that status without replacing the source ZIP. Its full knowledge snapshot was
specific to that pack companion. The 0.7 application packager now includes root
`AGENTS.md`, the complete knowledge directory, recursive documentation and
workflow definitions in its own hashed source inventory.

`scripts/make_pack_validation_candidate.py` creates a separate numeric candidate
and a correspondence report from a frozen proposed final pack. Only the pack
version and permitted README prefix change; executable, commands, metadata,
fixtures and source must remain byte-identical. Candidate releases retain failures
and superseded trials for diagnosis, not as user installation recommendations.

The failures drove useful regression coverage: STAR could exit successfully
while producing no expected alignments because of the libc++ buffer behavior;
kallisto 1.0.0 omitted requested multithreaded plaintext bootstraps. The latter
remains available unchanged and is superseded by 1.0.1. Zero-bootstrap or
single-thread 1.0.0 behavior was not the failing case.

## Catalogue trust is a separate unfinished deployment step

As of the audit date, **the signed online catalogue and public `source.json`
trust file are not published/configured**. The released 0.6.0 app contains an
empty `workspace/catalog-sources.json`. Offline **Manage tools → Import pack ZIP**
works and verifies the inventory, but reports that the publisher has not been
authenticated. Do not turn a checksum list, unsigned preview, arbitrary GitHub
search result or test key into trusted production discovery.

[Catalogue publication](../docs/catalogue-publishing-0.6.md) defines the actual
mechanism: an externally provisioned maintainer RSA key (2048–4096 bits, exponent
65537), an explicit public source definition, approved HTTPS/redirect hosts, and
RSASSA-PKCS1-v1_5/SHA-256 signatures over exact payload bytes. The private key
stays outside the repository, archives and output directory; it is not generated
or uploaded by the publisher. GitHub credentials and catalogue signing keys have
different purposes. Never include either in handover documents or examples.

For a local unsigned inspection using a release map:

```sh
python3 scripts/publish_pack_catalog.py \
  --release-map /path/to/reviewed-release-map.json \
  --unsigned-preview \
  --output /path/to/new-preview-directory
```

The map must point to actual local archives and their verified immutable HTTPS
release URLs. `publishing/releases-0.6.0.json` is the historical map of the first
18 packs, not a complete current optional-pack map. Create/review an updated map
before a future catalogue publication. The script validates archives and emits
`catalogue-preview.UNSIGNED.json`; it does not upload or verify live URLs.

Once a maintainer supplies the intended external key, follow the signing command
in [GitHub publication](../docs/github-publication.md), using the updated map and
the final catalogue URL. Use a new output directory for each attempt. Review the
source-key fingerprint through a trusted channel, keep publication timestamps
increasing, and retain old signed catalogues. Key replacement requires explicit
source trust replacement. A catalogue signature does not authenticate a source
file obtained from an unknown party.

To make a reviewed source preinstalled later, create a **new application version**
with that source object in `workspace/catalog-sources.json`; do not modify the
already checksummed 0.6.0 release. Offline deployment and institutional mirrors
remain supported distribution approaches without uploading sample data.

## Evidence to leave for the next maintainer

For each release, leave a discoverable record of source commit, tag, app/pack/tool
versions, input archive and patch hashes, compiler/dependency identity, final
asset names/sizes/hashes, manifest hash, test commands/environment, passed/failed/
skipped results, native Windows run/report links, known limitations and matching
license/source companion contents. Distinguish proposed work from completed
checks. Keep synthetic fixture provenance and scientific expected answers with
the recipe. Never make a future maintainer depend on an ephemeral workspace,
private browser state or an unrecorded local compiler installation.
