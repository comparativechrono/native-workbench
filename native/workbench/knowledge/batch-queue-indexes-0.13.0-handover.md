# Samples, queue and reference indexes: 0.13.0 candidate

## Status and authorization

The owner requested implementation of the next accepted tranche on 2026-10-08.
This work is in [draft PR #8](https://github.com/comparativechrono/workbench/pull/8),
branch `feature/batch-queue-indexes`, stacked on the unpublished 0.12.0 branch at
`dc7c8e9ea78f12d6229150c48af8c60d6632046b`. It is not a release request.
Published **0.11.0**, its assets, the 32-pack setup profile and catalogue trust
remain unchanged. No 0.13.0 updater has been built or tested.

Implementation covers explicit CSV/TSV sample mapping, independent sample jobs,
an explicit combined metrics/text report mode, a durable serial queue and
verified reusable minimap2 short-read indexes. See the
[batch/queue guide](batch-workflows.md) and [index contract](reference-indexes.md).
This tranche does not implement completed-step restart, concurrent analysis,
generic cohort pooling or indexes for all aligners.

## Exact packaged candidate

The final development candidate is packaged from
`0ceca7b9c1762542f8fb665a6695b998d32f311e` in
[run 37828085808](https://github.com/comparativechrono/workbench/actions/runs/37828085808).
Its build and both Windows jobs passed. It supersedes the initial `80e9071`
candidate after a bounded queue/history storage fix; original observations
remain historical evidence and are not transferred to changed bytes.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-0.13.0-starter-windows.zip` | 17,714,330 | `7bf98515d9403e851fcc189f022fed0386fbcdbfa6857823699d4170fc076c75` |
| `native-workbench-0.13.0-source.zip` | 47,165,595 | `3bd021f0ba9be8255b1710487cfd2a94ed8ff0d3c2b69ea6487bc1f7a5819b23` |
| `native-workbench-pack-align-0.4.1.zip` | 575,862 | `3a08cf061f0b62c5502d1420115db3fcae2b04bf695ad3cfd1c3063de0fafa02` |

The candidate includes `align` 0.4.1 beside unchanged 0.4.0. The new version
declares application 0.13.0 and adds typed build/use index operations; saved
0.4.0 workflow pins are not upgraded. Existing native executables and licences
are retained. Build artifacts are temporary GitHub Actions artifacts, not
published application or pack downloads.

For tester download, open the final run's **Artifacts** section and select
`batch-transfer-starter-0ceca7b9c1762542f8fb665a6695b998d32f311e`.
Extract the artifact ZIP, then the enclosed Starter ZIP. GitHub access may be
required; artifacts expire after their recorded 30-day retention. This is a
standalone test candidate, not an updater for an existing installation.

## Final validation

The [final source record](evidence/batch-queue-indexes-0.13.0-final-source-2026-10-08.json)
records **217 passes, five skips, no failures** across 17 suites. Four skipped
checks require Windows; one requires an optional independent CWL runner.
The [final Windows evidence](evidence/batch-queue-indexes-0.13.0-final-windows-2026-10-08.json)
records exact packaged execution on ordinary and spaced paths. Each path passed
**11 batch/queue/index/interface**, **14 resource**, **five readiness/diagnostic**,
**seven library** and **32 workspace** checks. Independent align 0.4.1 import and
its declared scientific check passed. Three separately instrumented transport
checks passed with original host bytes restored; their fixture scope is explicit.
Windows source suites separately passed **28 queue**, **18 index with one symlink
privilege skip**, and **ten diagnostics with one POSIX-only skip**.

The [final independent archive audit](evidence/batch-queue-indexes-0.13.0-final-archive-audit-2026-10-08.json)
verified all 663 current source files against the packaged commit, all 266 Starter
members, 79 core files and 25 runtime Python modules including `file_io.py`.
It confirmed 143 published pack files, 39 private runtime files and production
profile/trust unchanged. Native application/bridge bytes and align 0.4.1 identity
match the initial candidate. The standalone pack ZIP was not independently
downloaded in this archive audit; its actual native import has separate evidence.

The exact packaged held-reader check demonstrated successful queue admission and
history commit after short external readers close. A persistent reader exhausted
the bounded wait and returned an explicit Windows error while preserving queue
bytes, in-memory jobs and output folders. Real Windows source tests separately
cover both queue and history, including temporary-file cleanup. No analysis is
automatically retried. This closes the demonstrated file-access risk; it does not
reconstruct missing error messages from every historical failed run.

## Initial candidate and retained failures

The [source evidence](evidence/batch-queue-indexes-0.13.0-source-2026-10-08.json)
records **213 passes, three skips, no failures** across 17 affected suites in the
initial build. Two skipped checks require Windows and one requires an optional
independent CWL runner. These are not native execution or benchmarking results.

The [independent archive audit](evidence/batch-queue-indexes-0.13.0-archive-audit-2026-10-08.json)
verified bounded transport artifacts, reconstructed source bytes, 659 current
source files against the packaged commit, all 265 Starter members, 143 unchanged
published pack files and 39 unchanged private runtime files. It inspected PE
architecture and the new pack contract; it did not execute Windows binaries.
The standalone pack ZIP was not independently downloaded in that audit. Its
native import and declared scientific check have separate execution evidence.

The [initial Windows record](evidence/batch-queue-indexes-0.13.0-initial-windows-2026-10-08.json)
retains the original unsuccessful overall run, including its successful
independent gates. Each path passed 14 resource, five readiness/diagnostic,
seven library and 32 workspace checks, plus independent pack import and its
declared known-answer check. Three transport checks used a separately labelled,
temporarily instrumented host with original bytes restored; they are not
unmodified-host execution claims. Windows queue source tests passed 22 and
diagnostic source tests passed ten with one POSIX-only skip.

Initial validator defects included default-Windows decoding of UTF-8 CWL,
an observer opening an atomically replaced receipt without delete sharing,
and expecting first-run setup after creating real user data. Corrections retain
the integrity assertions and distinguish returning-installation behavior.
The corrected Windows index suite passes 18 tests with one symlink-privilege
skip. Later rechecks retain their own reports rather than replacing earlier
failures or combining duplicate pass counts.

The [retained recheck records](evidence/batch-queue-indexes-0.13.0-rechecks-2026-10-08.json)
include the full ten-check pass in both paths from
[run 37823492777](https://github.com/comparativechrono/workbench/actions/runs/37823492777).
Validator commit `06a8b47b22f8e08266ea9b83ddbcfd37b06008be` changes diagnostics
and tests only; the packaged application remains `80e9071`. These checks cover
sample metadata/CWL, serial native scientific results, cancellation, deliberate
input/companion corruption, index build/reuse/equivalence and tampering, and
actual Samples, Queue and Indexes controls. Earlier intermittent preparation
and pre-execution failures are not explained by this later successful run.
The [targeted diagnostic](evidence/batch-queue-indexes-0.13.0-queue-diagnostic-2026-10-08.json)
then reproduced a real Windows replacement hazard: an open reader, even with
DELETE sharing, caused `os.replace` to fail with WinError 5; closing it allowed
the same rename to succeed. Its 24 small queue cycles per path all passed, but
only two/one observations overlapped active state, so those cycles do not prove
the cause of the earlier failures. The confirmed hazard motivated the narrow
fix in the final candidate: at most nine rename attempts with 550 ms total retry
waits for Windows errors 5/32/33. Existing staged bytes are reused; persistent
errors propagate without deleting the destination or rerunning an analysis.

Independent and root screenshot reviews of the same application in recheck 3
found no new dialog overlap or missing buttons at 96 DPI. Long table labels
elide; full values and notices are in scrollable controls. The screenshot named
`queue-native-completed.bmp` still selects the cancelled sample, so completion
is established by the separate persisted scientific-result assertions, not
that image alone. These are settled-image observations, not a temporal flicker
or physical-display test.
The final ordinary Samples preview, paused Queue and verified Indexes captures
were also reviewed by the primary agent, with the same bounded result. The
final audit independently confirms native UI source and executable bytes are
unchanged between these reviews.

The frozen recheck workflow now pins the final candidate above. Its no-application-
change guard must pass before any archive reuse. The observer diagnostic workflow
retains the original candidate pin as a historical reproduction experiment.
Documentation/evidence-only commits skip rebuilding the accepted test bytes;
such skips are never counted as successful validation runs.

## Remaining acceptance boundaries

Hosted Windows checks use synthetic scientific truth, bounded cancellation
fixtures and the observed 96-DPI desktop. They do not establish realistic cohort
capacity, Windows–Linux performance equivalence, physical trackpad behavior,
high-DPI/multi-monitor access or institutional endpoint approval. The inherited
1040-pixel main-window minimum clips 16 pixels on the hosted 1024-pixel work area;
that environment is not complete small-screen acceptance.

Live Ensembl downloads, Full online setup and a published-baseline updater were
not rerun for this candidate. Existing evidence for their published versions
does not become a new pass for 0.13.0. Representative-machine tester acceptance
and a separately authorized release/update workflow remain outstanding.
