# Current project state

**Integration update, 2026-10-13:** the owner authorized checking compatibility
and merging the completed PR stack. PRs [#18](https://github.com/comparativechrono/workbench/pull/18),
[#17](https://github.com/comparativechrono/workbench/pull/17),
[#15](https://github.com/comparativechrono/workbench/pull/15) and
[#14](https://github.com/comparativechrono/workbench/pull/14) are now merged,
carrying the already merged #16 work into `main` at
`9c9cdeacf35d1bf3aa60277f0fb05d5af41c6254`. Every merge preserved the reviewed
source tree exactly. Five pack archives load together with eight scientific
workflows and unchanged version pins; 30 focused source checks passed.

Published **0.16.0**, candidate archives and historical validation remain unchanged.
This is source integration, not a release or deployment-acceptance claim. No open
PRs remain. The [integration receipt](evidence/stack-integration-2026-10-13.json)
records merge identities, compatibility checks and outstanding work. Earlier
review/draft statements below are dated history superseded only for merge status.

## Active review: Primer3 and PLINK2, 2026-10-13

Independent **1.0.0** packs are ready in
[draft PR #18](https://github.com/comparativechrono/workbench/pull/18) on
`feature/primer3-plink2-packs`, based on Kalign delivery
`8c0321d0cf04751a7c921d42098bed13ebb7b11a`. Kalign PR #17 remains draft/unmerged.
Tested source `3d1d83b70d053af625b5cb45362851c0fefab2a1` implements paired PCR
primer design and bounded VCF hardcall allele/genotype/missingness summaries.
Published 0.16.0 and frozen 0.16.1 application bytes remain unchanged.

The [hosted run](https://github.com/comparativechrono/workbench/actions/runs/38403212748)
passed 111 source tests with one explicit Windows-only Linux skip; each Windows
path passed 14 Primer3 and 17 PLINK2 tests without selected skips, eight science
and ten GUI gates, exact-pin graphs and Starter/installed-pack regressions.
Independent audit matched 984 Git files, 1288 source-companion entries and all
recorded graph/output identities. All 38 actual display screenshots were reviewed.
The [handover](primer3-plink2-handover.md) and
[final index](evidence/primer3-plink2-1.0.0-final-review-2026-10-13.json) record
hashes, downloads, local pre-freeze corrections and limits. Native Results does
not yet parse these packs' measurement files. Broader display/PC acceptance and
benchmarking remain separate; no merge, release or catalogue change is included.

## Previous development: Kalign pack, 2026-10-13

Kalign **1.0.0** is ready for unpublished review in
[draft PR #17](https://github.com/comparativechrono/workbench/pull/17), based on
merged integration commit `8addaa1278c535e4931eb0b2b85b8f47b51ddd66`.
Tested source `8149bdc02a2104e97ea6512ae0a8bc76c8defc32` provides serial default
nucleotide/protein alignment, explicit alphabets, typed MSA outputs and recorded
measurements. Application binaries are unchanged.

Hosted checks passed 94 source tests (one explicit Linux platform skip), all 17
selected tests per Windows path without skips, both real Kalign→FastTree DAGs,
Starter/installed-pack regressions and seven GUI gate checks per path. All 20
actual display images were reviewed at 96 DPI. The downloaded archive audit
matched 953 Git files and 1103 companion entries. Native Results does not yet
parse the pack's JSON measurements. The [handover](kalign-handover.md) records
exact archives, the initial fixture-newline correction, and acceptance limits.
Kalign is unmerged/unpublished; no release or catalogue change is included.

## Merged development: Prodigal and FastTree packs, 2026-10-13

The first approved tool batch adds optional `prodigal` **1.0.0** and `fasttree`
**1.0.0** packs in [merged PR #16](https://github.com/comparativechrono/workbench/pull/16).
Pack/validator source is `d175076d57f4c84743cb375369c604085a720204`, based on
`fix/native-ui-0.16.1` at `2b2e97aa15970f0e7fb3a5428e8ab7dad6acada2`.
There are no application changes; published **0.16.0** and the wrapped-library
**0.16.1** candidate below are preserved.

Prodigal provides genome and metagenome gene prediction with explicit biological
settings and GFF/protein/CDS outputs. FastTree provides nucleotide/protein
approximate-ML inference from homologous alignments, with explicit models and
local-support interpretation. Both retain real pinned upstream source,
compatibility/build provenance, licences, native adapters and measured JSON
outputs without invented QC thresholds. The unchanged Results interface supports
search, status and exact tool provenance; it does not yet parse these new JSON
measurements into native summary tiles.

The corrected [build/native run](https://github.com/comparativechrono/workbench/actions/runs/38387733137)
passed 16 Prodigal and 14 FastTree tests per Windows path without selected skips,
both real MUSCLE-to-FastTree DAGs and Starter regressions. The independently
downloaded archive audit matched 924 Git files and 967 companion entries. Frozen
validator `9ea63994661073b115e80533c3288d50d250decb`,
[run 38389163430](https://github.com/comparativechrono/workbench/actions/runs/38389163430),
passed eight validator tests and 12 GUI checks per path on unchanged archives.
All four forms were scrolled from their true first page through the last; all
44 actual display images were reviewed without a blocking layout finding at 96 DPI.

PR #16 merged into `fix/native-ui-0.16.1` at `8addaa1278c535e4931eb0b2b85b8f47b51ddd66` on the owner's instruction. The
[handover](prodigal-fasttree-handover.md) and
[final index](evidence/prodigal-fasttree-1.0.0-final-review-2026-10-13.json) retain
the first candidate's stack failure, GUI-driver correction and earlier limited
form capture scope. No main/PR #15 merge, release, online catalogue, benchmark or broader
deployment acceptance is included.

## Previous development: wrapped tool library, 2026-10-10

The presentation and overflow-scroll correction are implemented in application
source `ff13db729a6215e9fe5dfa4a4efdb9c769880287` on `fix/native-ui-0.16.1`,
starting from `568f2a74a62c4befb7ffe9c9f26390fe5a8c1d72`, in
[draft PR #15](https://github.com/comparativechrono/workbench/pull/15). The base
remains `feature/deployment-acceptance` at
`f74d90229be6a78d6ad0c0076c54c04bb7e7cae2`; the version is unpublished **0.16.1**.

Full tool names wrap in bold and descriptions in regular weight within the left
pane; the hover label popup is removed. Native TreeView 104 sits in bounded pixel
viewport 430. Native coarse scrolling remains enabled behind the clip, allowing
both long rows and a long catalogue to remain reachable. Category, keyboard,
search/filter, selection and drag contracts remain, alongside existing workflows,
Methods, Samples, reference management and exact tool/version pins.

The [build run](https://github.com/comparativechrono/workbench/actions/runs/38075960020)
passed **258 source tests in 20 suites**, C++ JSON and three strict native builds.
Archive audit matched 864 Git source files, 34 runtime modules, six examples,
90 core/277 Starter files and unchanged pack/runtime baselines; the updater
reconstructed the exact Starter core. The spaced path passed all ten native
gates/124 checks. The ordinary path passed nine gates/111 checks and one feedback
check before a runner console obscured the app. That original failure remains.

Frozen validator `7ea0ce6bf6821089c524c307f99efb0a1892d2a3`,
[run 38076722339](https://github.com/comparativechrono/workbench/actions/runs/38076722339),
passed all 13 feedback checks per path on unchanged application archives,
including overflow at both tested widths. Together this establishes **124 distinct
native checks per path**: seven wrapped-library, 23 patch, 13 feedback and 81
regressions. Repeated checks add no unique coverage; 18 separate validator tests
do not add to the 258 source count. Final evidence audit and review of 41 actual
display images are complete; the candidate is **ready for unpublished draft
review**. The [final index](evidence/wrapped-library-0.16.1-final-acceptance-2026-10-10.json)
binds all scopes and limits. The caption click at the modal-close setup boundary
does not establish automatic foreground restoration; finite captures do not
prove zero flashing. Representative-PC and broader display acceptance remain
outstanding.

The [handover](wrapped-tool-library-0.16.1-handover.md) retains every earlier
application, driver and infrastructure failure and narrower diagnostic result.
The historical strict resize negative-control failure remains unchanged.
Published **0.16.0** remains unchanged; no merge, release, benchmark or external
deployment acceptance is included.

## Previous development: Tools resize correction, 2026-10-10

Application source `51077179a6e92020a7e9b992fa0cbe2b5a6c3e1e` implements the
bounded correction in [draft PR #15](https://github.com/comparativechrono/workbench/pull/15)
on `fix/native-ui-0.16.1`, based on `feature/deployment-acceptance` at
`f74d90229be6a78d6ad0c0076c54c04bb7e7cae2`. The version remains unpublished
**0.16.1**. Resizing now places the controls and their children without drawing
intermediate layouts, then repaints the complete window. Minimize preserves the
normal layout dimensions and panel scroll positions. Existing Run/category
behavior, separate Methods, Samples editing and workflows remain in scope.

The [resize handover](resize-redraw-0.16.1-handover.md) binds the new Starter,
matching source and updater to **235 source checks in 18 suites**, three strict
native builds and the independent archive/source audit. **117 distinct native
checks per path** passed across the original build run and unchanged-archive
recheck: 81 existing regressions, 23 patch/resize checks and 13 feedback checks.
Repeated gates add no unique coverage; source totals include validator tests.

Candidate passive samples after `DwmFlush` showed the target layout in Tools and
Workflow modes, fresh and upgraded installations, ordinary and spaced paths.
Pre-wait frames can still show the previous layout or newly exposed black bands.
The strict old-package single-transition comparison also had no post-wait stale
frames, so that negative-control requirement remains failed. A separate bounded
comparison sampled three bursts of 12 concurrent resizes per package: the old
package had **14 mixed-layout frames among 46 samples**; the corrected package
had **zero among 64**. Independent screenshot review confirmed duplicated and
shifted controls in old mixed frames, while retained corrected frames show whole
endpoint layouts. This supports the narrow paint-ordering correction; unequal
observation durations do not establish a speed improvement or universal behavior.
The final workflow still fails the unchanged strict negative-control requirement.
The earlier roughly 0.3-second observation remains an upper sampled interval,
not an exact lag measurement. Finite frame samples cannot prove zero flicker.

Published **0.16.0**, `main`, published assets and earlier historical evidence are
unchanged. No merge or release is included. Representative-PC/high-DPI/multiple-
monitor/physical-trackpad acceptance and the separately managed benchmarking,
signing/IT, scientific Linux CWL and SDK work remain outstanding.

## Previous tester-feedback candidate of unpublished 0.16.1

Snapshot: **2026-10-09**. [Draft PR #15](https://github.com/comparativechrono/workbench/pull/15)
continues on `fix/native-ui-0.16.1`, based on the unmerged deployment companion
branch at `f74d90229be6a78d6ad0c0076c54c04bb7e7cae2`. Application source is
`73778e00461e2b83c07b9ea97df2b9c5d4b6317d`. It remains unpublished **0.16.1**;
published **0.16.0**, `main` and published assets are unchanged.

Implementation addresses Run flashing/redundant polling redraws and category
expansion anchoring/collapse redraws. Methods is separate again; the primary
Readiness button is removed while Run preflight remains. Native Samples provides
New, Edit and Save as CSV/TSV plus a verified one-row Starter example. File
columns, base folders and mapping remain explicit. This adds no runtime/memory
forecast or independent biological replicates.

The [handover](tester-feedback-0.16.1-handover.md) and new evidence bind this
revision's exact Starter, matching source and updater. **220 source tests in 18
suites** passed with no configured skips, together with the C++ JSON check and
three strict native builds. The independent archive/source audit passed. Seven
Windows regression scopes passed **81 checks per path** (11 batch, 11 curated,
five readiness, 10 references, nine results, three scroll and 32 workspace).
Their **112 capture files** were reviewed at original resolution or through
explicitly recorded exact-byte equivalence; no blocking regression layout defect
was observed within those 96-DPI viewports.

Final validator `f9e7120196ddd284d33c0e8221b78fbf4529058f` completed
[run 37999874335](https://github.com/comparativechrono/workbench/actions/runs/37999874335)
with **19 patch and 13 tester-feedback checks passed per path** on unchanged
archives. Together with the 81 regression checks, this is **113 unique configured
checks per path**. Repeated patch observations do not add unique coverage. The
**23 portable validator tests** (eight patch, 15 feedback) passed separately from
the 220 application source tests. All four earlier partial attempts and their
focused failure receipts and original-report hashes remain in the [attempt record](evidence/tester-feedback-0.16.1-attempts-2026-10-09.json).

The complete feedback gate exercised Samples without a workflow, editing and
CSV/TSV roundtrip, discarded/rejected edits, explicit one-row example mapping,
and actual queued science: 202 proper-pair alignments and the known homozygous
starter:1351 G>A SNP with sample/CWL/output provenance. Its 41 temporal series
per path contain 1,510 ordinary and 1,306 spaced-path frames, with no sampled
black block or unexpected stable difference. These are finite observations,
not a zero-flicker claim. The [native record](evidence/tester-feedback-0.16.1-native-validation-2026-10-09.json)
links focused, sanitized receipts, original-report hashes and artifact locations.

Patch visual review covered 82 capture files (43 unique images and 39 exact-byte
duplicates). Settled controls fit; immediate Tools resize frames can retain old
geometry and clip the right/bottom edge until the first later sample, about
0.30–0.32 seconds. Workflow samples were stable. This bounded resize observation
is separate from Run/category flashing acceptance. Final feedback visual review
passed for all **192 capture files**: 51 unique BMP hashes, 52 direct views and
140 verified exact-hash reuses. Hashes, dimensions and lossless PNG pixels match
the native reports; no unexpected layout defect was observed within the captured
viewports. [Ordinary receipt](evidence/tester-feedback-0.16.1-feedback-visual-ordinary-2026-10-09.json),
[spaces receipt](evidence/tester-feedback-0.16.1-feedback-visual-spaces-2026-10-09.json).
Observed workspace sizes are 960×680 and 1024×728 at 96 DPI;
the Samples window is 940×680. Broader display acceptance is not established.

The revision is ready as an unpublished draft review candidate. Evidence is
minimized for repository delivery: focused, sanitized results and original-report
SHA-256 values are retained, while opaque tokens and detailed runner/input records
are excluded. Full originals remain in the local validation workspace and Actions
artifacts, scheduled to expire on **2026-11-08**; hashes do not preserve access to
raw content after expiry. The handover records the automatic upload-review
rejection and the resulting evidence boundary.

Earlier `8938e709` source/native/visual receipts remain historical and do not
validate this revision. No merge or release is part of this work. Benchmarking is
separate; representative-machine/high-DPI/multiple-monitor/physical-trackpad and
managed-machine acceptance, signing/IT, scientific Linux CWL and SDK/build
recovery remain outstanding.

## Prior unpublished candidate: native keyboard and narrow-display patch

Snapshot: **2026-10-09**. [Draft PR #15](https://github.com/comparativechrono/workbench/pull/15)
contains **0.16.1** on `fix/native-ui-0.16.1`, stacked on
`feature/deployment-acceptance` and draft PR #14. Candidate source is
`8938e709b041106e8a46e1447383e8e9ba3e0cb9`;
[candidate run 37988570028](https://github.com/comparativechrono/workbench/actions/runs/37988570028)
passed 141 source tests and 84 native checks per Windows path; the independent
archive/source audit and settled 96-DPI visual review passed. That unpublished
candidate completed draft-review validation before this tester-feedback revision.
Published 0.16.0 and the original deployment
companion's failed observations remain unchanged. Nothing is merged or released.

The patch restores Results query focus before disabling a focused action, keeps
asynchronous replies from taking focus from another control, and requires actual
keyboard Search followed by Escape on fresh and upgraded installations. It also
uses monitor work-area bounds for initial placement and minimum size, with a
960×680 logical minimum and a compact three-pane layout for the observed narrow
desktop. Scientific operations, saved pins, pack/runtime bytes, setup profile and
catalogue trust retain their existing contracts.

The third revision also makes read-only `queue/status` requests nonblocking for
editing and Results focus only when no outgoing actions are queued. Other busy
guards and FIFO command ordering remain; queuing a mutation immediately refreshes
control availability. The native gate now observes passive focus holds for
2.4 seconds across polling intervals without restoring focus during the hold.
This behavior passed the third candidate's native checks, with separately
recorded source, archive and visual evidence.

The target is the observed 96-DPI desktop and a 960-pixel outer minimum width.
Source review identifies busy Cancel/Results overlap below **908 logical client
pixels** and possible footer overlap below **902**. Smaller work areas and high
DPI remain unvalidated; clamping to a work area does not establish acceptance of
every resulting layout.

The [patch handover](ui-patch-0.16.1-handover.md) records the implementation and
required evidence. The candidate builds a new Starter, matching source archive
and core-only 0.16.0→0.16.1 updater. Its own
[source evidence](evidence/ui-patch-0.16.1-source-validation-2026-10-09.json)
records 141 passes in 13 Python suites, no failures or skips, the C++ JSON check
and all three strict-warning native builds. The
[archive audit](evidence/ui-patch-0.16.1-archive-audit-2026-10-09.json) verifies
787 Git source files, 33 packaged Python/source matches, 87 core files, 186
unchanged pack files and 39 unchanged private-runtime files. Archive hashes are
recorded in that receipt and the handover.

The [native validation record](evidence/ui-patch-0.16.1-native-validation-2026-10-09.json)
and [final visual review](evidence/ui-patch-0.16.1-visual-review-2026-10-09.json)
bind the original candidate run and the final validator-only recheck to these
same archives. Settled observations passed in both Windows paths at 96 DPI.

The earlier interpretation that original post-resize screenshots omitted
General settings/Readiness was incorrect: crops taken from the original image
bytes show both. It is not evidence of a product defect or transient absence.
The [validator-only recheck](https://github.com/comparativechrono/workbench/actions/runs/37989535317)
at `69022689e686b2cacdc98dbdbef728e664941e67` passed the same 19 patch checks per
path using the unchanged `8938e709` archives. This is a repeat within the 84-check
scope, not 103 unique checks. Passive visible captures taken before PrintWindow
show the fixed controls settled by the first requested 250-ms frame (about
0.3 seconds elapsed); later 750/1250-ms observations were unchanged. Immediate
frames can retain the old geometry, a bounded resize observation rather than a
missing-control finding. These samples establish the recorded settled layout;
they do not establish zero flicker or exclude shorter unsampled transients.

Representative-PC,
high-DPI, multi-monitor, physical-trackpad and managed-machine acceptance,
executable signing and IT approval remain outstanding. Scientific Linux CWL and
SDK/build recovery remain later sets; benchmarking is handled separately.

The first candidate, `5e2bc368c5ea869ff794ad9d90a40480b6fd06fe`, remains a
failed attempt in [run 37986650814](https://github.com/comparativechrono/workbench/actions/runs/37986650814).
Its build passed **141 source tests in 13 Python suites**, with no failures or
skips, the C++ JSON check and all three strict-warning native builds. The new UI
gate recorded **11 passes/two failures** in the ordinary path and **10 passes/two
failures** in the spaced path. Each path separately passed 65 existing checks:
11 curated, 32 workspace, 10 reference-management, nine results and three scroll
checks. Validator corrections use the proper control IDs and wait for the Setup
dismissal reply before app closure. The spaced-path filter-clear failure's cause
is unproven; explicit Home/Shift+End selection makes the next attempt observable.
These results remain tied to the first candidate, not the new archives.

The second candidate, `473428671cbb75505c163a9a761caf84e73dfdd9`, also remains a
failed attempt in [run 37987546291](https://github.com/comparativechrono/workbench/actions/runs/37987546291).
The ordinary path passed all 84 configured checks. In the spaced path, the patch
gate recorded **11 passes/two failures**, at library Tab and Home focus before
Results opened; the 65 existing checks passed in both paths. Those reports and
archive audits remain retained. The third candidate adds the polling fix and
passive focus observations; the earlier ordinary-path pass does not waive the
spaced-path failures or validate the new bytes.

## Deployment and acceptance companion baseline

Snapshot: **2026-10-09**. [Draft PR #14](https://github.com/comparativechrono/workbench/pull/14)
implements a verified offline kit, exact file/executable/runtime/licence inventories,
structured manual reports, actual Authenticode observations and a native updater
folder-picker/desktop gate around unchanged published **0.16.0**.

Exact observations are complete for tooling commit
1a7d1e5f70e3ca710c9b3f6b1313353e8d46cc78 in
[run 37979351047](https://github.com/comparativechrono/workbench/actions/runs/37979351047).
All 87 Linux companion source tests passed. Each ordinary/spaced Windows path
recorded **14 native passes and two failed fresh/upgraded Results Escape checks**,
plus 11 curated passes. CI remains failed. No control had focus after keyboard
Search. A real pointer click into the query then Escape closed the window, but
that diagnostic does not pass the original requirement. The visible Close fallback
was not needed or tested in the final run.

Exact archive/source audit passed and all 54 captures were reviewed. The hosted
1024×768 desktop, 1024×728 work area at 96 DPI, is narrower than the app's 1040
minimum width; its right edge is clipped. Bounded resize assertions do not imply
narrow-display acceptance. Actual signature observations cover 72 file occurrences
per path: 60 Valid and 12 NotSigned in the runner's trust context, not IT approval.
All 10 manual acceptance items remain not-tested.

The [handover](deployment-acceptance-handover.md),
[final evidence](evidence/deployment-acceptance-final-2026-10-09.json) and
[attempt history](evidence/deployment-acceptance-attempts-2026-10-09.json) preserve
the exact identities and failed observations. Full raw reports/screenshots remain
in the hashed Actions artifacts; aggregate receipts were recovered through GitHub
after the local workspace executor disconnected during delivery.

These observations prompted the separately versioned 0.16.1 Results focus/Escape
and narrow-display review candidate above. Its own hosted validation is separate;
the original companion's failures are not relabelled as passes. Representative-PC,
high-DPI, multiple-monitor, physical-trackpad and managed-machine observations,
IT approval and signing remain outstanding. Benchmarking is separate; scientific
Linux CWL and SDK/build recovery remain later sets.

## Published application: 0.16.0

Snapshot: **2026-10-09**. Application **0.16.0** is published
as a [development prerelease](https://github.com/comparativechrono/workbench/releases/tag/app-v0.16.0).
Release ID **408075619**, published at **2026-10-09T15:54:56Z**;
immutable tag/merged [PR #12](https://github.com/comparativechrono/workbench/pull/12)
commit `60243d45a81a6ef7e16e4a0ee719f4aa2e4f74c9`. Packaged application/source commit is
`e855dc4396e0c16ae35f4e840eb9cc734adb4441`. The accepted archives were promoted
without rebuilding. The owner authorized this release on 2026-10-09 with
“Great lets do a new release at this point”; no additional tester acceptance
is inferred from that authorization.

This release includes readiness/diagnostics, batches/queues/indexes,
restart/resource scheduling/portable projects, reference management and the
two curated synthetic workflows with native measured results/search/failure
guidance. The pack self-check fix removes unnecessary report-directory nesting;
child working directories at or above 260 characters remain unsupported.

[Candidate run 37952018931](https://github.com/comparativechrono/workbench/actions/runs/37952018931)
passed 488 Linux source tests/four Windows-only skips and 332 Windows source
tests/four platform or privilege skips per path. Both Windows paths passed the
11 curated checks and the recorded reference, performance, readiness, batch,
recovery, transport, library, workspace and independent-pack gates.
[Release regressions 37952595124](https://github.com/comparativechrono/workbench/actions/runs/37952595124)
passed nine results/CWL/DAG/icon and three scrolling checks per path, plus four
positive long-path checks with policy restoration. The additional alignment
used a 254-character native working directory and 268-character SAM path and
retained 202 mapped proper-pair records.

[Updater run 37952583789](https://github.com/comparativechrono/workbench/actions/runs/37952583789)
passed 18 main checks per path from published 0.11.0, verified 87 core files and
preserved 204 existing files; the only expected addition was a one-NUL-byte
session lock. Each upgraded installation also passed 11 nested curated checks
and seven installation checks with align 0.4.1 absent. These nested scopes are
not summed into an inflated test total. Separate explicit import added the
43 align 0.4.1 files while preserving 182 installed pack files. The updater
folder picker and live reference downloads were not part of this gate.

The archive audit verified 748 exact Git source files, 87 core files and
33 runtime modules; 143 published pack files and 39 private-runtime files,
production trust and the 32-pack profile are unchanged. Twenty-four final
Starter/upgraded curated-result captures and 24 additional results/scroll
captures were reviewed at 96 DPI.

[Publication run 37955110070](https://github.com/comparativechrono/workbench/actions/runs/37955110070)
verified all **13 public assets** by anonymous download. Release/tooling source,
native evidence and asset identities are recorded separately in
`RELEASE-VALIDATION.json`. See the
[release handover](curated-workflows-0.16.0-release-handover.md),
[acceptance lock](evidence/curated-workflows-0.16.0-release-lock.json),
[archive audit](evidence/curated-workflows-0.16.0-release-archive-audit-2026-10-09.json),
[updater evidence](evidence/update-0.16.0-final-validation-2026-10-09.json),
[release regressions](evidence/curated-workflows-0.16.0-release-regression-final-2026-10-09.json)
and [public-download receipt](evidence/curated-workflows-0.16.0-public-downloads-2026-10-09.json).

Representative-PC/high-DPI/multi-monitor/physical-trackpad acceptance,
scientific Linux CWL validation, realistic Windows–Linux benchmarks, executable
signing and institutional deployment remain outstanding. Synthetic fixtures do
not establish biological/clinical fitness or realistic capacity. No new download
of all 32 optional packs or full scientific rerun of every optional tool is claimed.

## Historical implementation and release records

The sections below retain their original dates, candidate identities and
authorization/validation scope. Their references to unpublished branches,
draft reviews, pending release gates or the then-current 0.11.0 baseline are
historical. Features from 0.12–0.15 are now included in 0.16.0; those candidate
versions were not separately published. The earlier `7a9aca7` and `a447997`
0.16.0 candidates were superseded, and their passes do not validate `e855dc4`.

## Historical review candidate: 0.16.0 before release fixes

Curated synthetic workflows and native recorded-result summaries/search are
implemented on `feature/curated-workflows-results`, based on reference-management
head `f45622f8915a3fa80c0904fcd97c216e0b5980f3`. Exact candidate
`7a9aca71ddd4816b51dbe693873f42fa50a6b746` passed all configured hosted Windows
gates in ordinary and space-containing paths, including 11 curated checks per
path. Source checks passed (474 Linux; 318 Windows per path, each with four
explicit skips); downloaded archive/source audit and 12 new-feature screenshot
reviews passed. The [handover](curated-workflows-results-0.16.0-handover.md)
records exact hashes, downloads, failed attempts, skips and limits.
[Draft PR #11](https://github.com/comparativechrono/workbench/pull/11) is ready
for review. Published 0.11.0 is unchanged; nothing is merged or released.
Representative-PC and release/updater acceptance remain separate.

## Previous set: 0.15.0 reference management, unpublished

On **2026-10-08** the owner requested the remaining accepted work one group at a
time. The first group was reference management: resumable downloads, local import,
safe library relocation and NCBI RefSeq assembly discovery. It is retained on
`feature/reference-management`, based on `38917349449ce56a45d3e0f4f41b7d2a38621c6d`.
See the [feature contract](reference-management.md) and
[candidate handover](reference-management-0.15.0-handover.md).

Implementation and recorded hosted validation are complete in
[draft PR #10](https://github.com/comparativechrono/workbench/pull/10).
Frozen application `46bbb39dda2cc5bb08c30af494cb340f976acf3b` passed nine live
reference and ten reference-management/interface checks per Windows path, with
all 22 new reference captures reviewed at 96 DPI. Its Linux build passed 430
source checks/four skips. A successful validator-only frozen-archive recheck
ran all 15 Windows source suites: 274 passes/four explicit skips per path,
and all 11 batch checks. Other exact native regression gates and independent
archive verification passed; failed earlier attempts remain recorded.

See the handover for exact downloads, hashes and combined evidence. These are
the prior 0.15.0 candidate's results; they do not validate the new 0.16.0 bytes.
The unpublished 0.15.0 candidate remains ready for tester review.
Representative-machine acceptance, realistic benchmarking and release/update
work remain separate. No 0.15.0
updater or baseline upgrade was tested. Published 0.11.0, production pack/trust
bytes and the frozen 0.14.0 candidate remain unchanged. This set does not
complete the entire roadmap or satisfy the earlier broader-completion release
condition.

## Previous implementation tranche: 0.14.0, unpublished

On **2026-10-08** the owner requested the final implementation tranche in the
accepted [roadmap](roadmap.md). Work is on `feature/recovery-projects`, stacked
on unpublished 0.13.0 at `9f5cd4c88634b4cab04cec66b9e43e93e1db0e17`.
The scope is verified restart at completed-step boundaries, declared CPU
admission budgets for concurrent DAG steps, and portable project bundles.
See [recovery, resources and projects](recovery-projects.md).

Implementation is in [draft PR #9](https://github.com/comparativechrono/workbench/pull/9).
Final packaged source `0e2d5cbcbf1786d6e1723f8466b4b6b94da04802` passed
[run 37842857764](https://github.com/comparativechrono/workbench/actions/runs/37842857764):
**289 source checks with four skips**, including actual report-only stock-CWL
replay. Each Windows path passed **12 recovery/resource/project/interface,
11 batch/index, 14 resource, five readiness/diagnostic, seven library and 32
workspace checks**, plus independent pack import/science and three separately
instrumented transport checks. Windows source suites passed 126 with three
skips per path. Independent archive verification checked 689 exact source files,
82 core files and unchanged published packs/runtime/trust.

Earlier failures exposed validator assumptions/imports and genuine Windows
short-path metadata defects; screenshot review found a clipped export label.
All were corrected and the final archive rerun. Both sets of six final captures
were reviewed at 96 DPI. Failed attempts remain recorded. **Implementation and
recorded hosted validation are complete; representative-machine acceptance,
realistic benchmarking and release/update work remain.** No 0.14.0 updater was
built or tested; live reference downloads and Full online setup were not rerun.
See exact downloads, evidence and retained validation limitations in the
[handover](recovery-projects-0.14.0-handover.md).
Historical source and Windows passes below apply only to their named candidates.
Published **0.11.0** and production packs/profile/trust remain unchanged.
This request authorizes development, not a merge, tag or publication. The
0.12.0 and 0.13.0 review branches remain unmerged and unpublished.

## Previous tranche: 0.13.0, unpublished

On **2026-10-08** the owner requested the next accepted tranche. Work continues
on `feature/batch-queue-indexes`, stacked on the 0.12.0 review branch at
`dc7c8e9ea78f12d6229150c48af8c60d6632046b`. It adds explicit sample-table mapping,
independent sample batches and combined reports, a durable serial queue, and
verified reusable minimap2 short-read indexes. The new `align` **0.4.1** candidate
sits beside immutable **0.4.0**; saved pins remain unchanged. The published
32-pack setup profile and catalogue trust remain unchanged.

See [batch workflows and queue](batch-workflows.md),
[reference-index contracts](reference-indexes.md) and the
[candidate handover](batch-queue-indexes-0.13.0-handover.md). Implementation is in
[draft PR #8](https://github.com/comparativechrono/workbench/pull/8).
The final candidate from `0ceca7b9c1762542f8fb665a6695b998d32f311e` passed
[run 37828085808](https://github.com/comparativechrono/workbench/actions/runs/37828085808):
**217 source checks with five skips** and **11 batch/queue/index/interface,
14 resource, five readiness/diagnostic, seven library and 32 workspace checks
per Windows path**. Independent pack import and three separately instrumented
transport checks also passed. Windows source suites separately passed 28 queue,
18 index with one privilege skip, and ten diagnostics with one POSIX-only skip.

A deterministic Windows check exposed receipt replacement failing while a reader
held the file open. The final candidate adds bounded retries for queue/history
commits; exact packaged checks prove brief conflicts recover and persistent
conflicts preserve old bytes and jobs. Earlier failed runs remain recorded; the
diagnostic does not reconstruct every missing historical error message.
The final archive audit verified 663 source files, 79 core files and unchanged
published packs/runtime/trust. **Implementation and the recorded hosted gates
are complete; representative-machine acceptance and release work remain.**
This request authorizes development, not publication. Neither 0.12.0 nor 0.13.0
has been released, and published 0.11.0 remains the baseline.

## Previous tranche: 0.12.0, unpublished

On **2026-10-08** the owner accepted the [broader feature roadmap](roadmap.md).
The first milestone is in progress on `feature/readiness-performance`, based on
`82729febfcfab1c43bd9c9798d03c80f595545cb`: explicit run readiness, scoped local
performance records and review-before-save diagnostic ZIPs. See the
[feature guide and validation handover](readiness-performance.md).

The first implementation tranche is ready for tester review in [draft PR #7](https://github.com/comparativechrono/workbench/pull/7).
Exact candidate source `eaa691d55a3659a793086ce272b826bcba1cabea` passed
[run 37808653384](https://github.com/comparativechrono/workbench/actions/runs/37808653384):
**144 source checks passed, three skipped**; each Windows path passed **14 native
resource, five readiness/diagnostic, seven library and 32 workspace checks**.
Windows diagnostic source checks separately passed ten with one POSIX-only skip.
Two independent screenshot reviews confirmed the corrected readiness introduction
and diagnostic Save controls fit at the observed 96 DPI. Earlier failed attempts,
the fixed offline hostname regression and the rejected cross-process font test
remain recorded rather than being counted as successful checks.

The [candidate evidence](evidence/readiness-performance-0.12.0-candidate-2026-10-08.json)
and [independent archive audit](evidence/readiness-performance-0.12.0-artifact-audit-2026-10-08.json)
bind exact source, starter bytes, native reports, limits and preserved pack/runtime
identities. One pre-cleanup resource snapshot in the spaced-path run is correctly
partial. The hosted desktop clips 16 pixels of the main window's minimum width;
this is not complete small-screen acceptance.

**0.12.0 remains unpublished.** Representative-machine acceptance, a realistic
Windows–Linux benchmark and release/update gates remain outstanding. No 0.12.0
updater was built or tested; live reference downloads and Full online setup were
not rerun by this candidate workflow. Published 0.11.0 below remains unchanged.
Sample batching, durable queues and reusable indexes are the active 0.13.0
tranche above. Verified completed-step restart and bounded concurrency are
implemented in the 0.14.0 candidate above.

## Historical published baseline: 0.11.0

Snapshot: **2026-10-08**. Application **0.11.0 is published** as a development
prerelease at [app-v0.11.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.11.0).
Release **406281343** was published at **2026-10-08T00:36:31Z**.
Its tag and [PR #6](https://github.com/comparativechrono/workbench/pull/6) merge
point to `a97af2d02a3a6f4623ceec0f06f69fa10d04cbb6`; packaged application source is
`acfa060c9a400d82509278b657ee37853c7922b0`. Accepted application/source/updater
archives were promoted unchanged; no application rebuild occurred.

The tool library uses expandable native categories from installed pack metadata,
with multiple open sections, search restoration and stable selection/scrolling.
Standalone tool forms and workflow Add/double-click/drag behavior remain.

Exact Windows checks passed in ordinary and space-containing paths:
**7 library, 32 workspace, 8 References, 9 results and 3 scrolling panel groups**
per path. The new updater from published **0.10.1** passed **13 checks per path**,
preserving 204 existing files and verifying 72 core files. Live Ensembl five-type
downloads, cancellation, independent hashes, compatible GUI input binding,
offline native reuse and provenance were rerun. The Linux source gate passed
70 checks and updater source checks passed 17.

Read-only [preparation run 37708488034](https://github.com/comparativechrono/workbench/actions/runs/37708488034)
and [publication run 37708604434](https://github.com/comparativechrono/workbench/actions/runs/37708604434)
passed. Both ran 11 promotion guard tests. Publication verified all **11 public
assets** by anonymous download; the independent second audit checked all asset
sizes/hashes, four ZIP CRCs and three checksum manifests. Publication checks
reuse the exact-package native runs and do not claim new Windows execution.

The [release summary](evidence/tool-library-0.11.0-release-summary.json),
[acceptance lock](evidence/tool-library-0.11.0-release-lock.json),
[publication record](evidence/tool-library-0.11.0-publication-2026-10-08.json),
[public audit](evidence/tool-library-0.11.0-public-downloads-2026-10-08.json),
[release inventory](release-inventory.json) and
[release notes](../docs/releases/0.11.0.md) retain exact identities and limits.
The [feature handover](expandable-tool-library.md) preserves the failed validator
attempts separately from the passing final gates. The owner explicitly requested
“Please release 0.11.0 properly”; no extra manual tester observations are inferred.

Hosted native observations were at 96 DPI; physical trackpad, high-DPI and
multi-monitor behavior remain unvalidated. All 32 pack downloads were not
repeated for this layout change. Packs and production trust/profile retain
their previously published identities. The separate tester-machine Heimdal
bridge approval issue is not resolved or bypassed by this release.

## Published 0.10.1 baseline

Application **0.10.1** remains available unchanged at
[app-v0.10.1](https://github.com/comparativechrono/workbench/releases/tag/app-v0.10.1).
Its updater supports 0.10.0; the new 0.11.0 updater supports 0.10.1.
Release 405862679 was published at 2026-10-07T14:38:46Z from packaged source
`00b53cdded5db3bb176ee7e5a06546b8a0c66fff`, with tag/PR5 merge
`28b1ff621f7fdafe6162a3d7ce1d7984962a290b`. Historical evidence follows.

## Tool Setup corrective patch, 0.10.1

The patch keeps the package list enabled for inspection during installation,
locks checkbox edits, updates changed cells in place, retains navigation state
and suppresses redundant control redraws/compositing. Exact native run
`37634723095` passed both paths: setup 14, workspace 32, References 8, results 9,
update 13 and a separate published-baseline negative control. The baseline
showed disabled scrolling, lost navigation state and variable header pixels;
the patch retained 391 stable samples and working busy wheel/scrollbar navigation.
Each upgrade preserved all 204 existing fixture files and verified 72 core files.
References explicitly omitted its optional embedded updater helper; the separate
updater passed. Linux source checks were 161 passed/one Windows-only skip; the
separate Windows source suite passed all 47 pack-manager checks.

Real production Full passed four checks: all 32 exact pins installed with
unchanged official trust, reopened offline, preserved the expected 202-record
alignment/BAM output and exposed BED input. Independent archive review verified
590 matching source files and unchanged production metadata/143 starter pack files.
Finite hosted samples do not cover all physical displays or institutional networks.

The generic download message previously hid both network and local-file errors.
New diagnostics distinguish bounded HTTP/TLS/proxy/DNS/timeout and destination
write failures, retain the pack name, and omit raw exception text, signed URLs
and credentials. The testers' download failure remains undiagnosed: old/new
transports worked in development and the exact patch passed Windows Full.
If their installation still fails, obtain the pack name and exact new message.

The [publication record](evidence/tool-setup-0.10.1-publication-2026-10-07.json),
[public audit](evidence/tool-setup-0.10.1-public-downloads-2026-10-07.json),
[release inventory](release-inventory.json), [release notes](../docs/releases/0.10.1.md)
and [handover](tool-setup-0.10.1-handover.md) retain exact identities and limits.
Earlier releases and all published pack bytes remain unchanged.

## Published tool setup, 0.10.0, 2026-10-07

The user approved Full (recommended), Starter and Custom setup over the existing
pack manager. Application **0.10.0 is released**. The native
setup interface and durable per-pack queue use the 32 current published pack
identities; application and tool versions remain independent. The small Starter
retains its unchanged three packs, and Manage tools/offline import remain.
See [tool setup](tool-setup.md) and the [size assessment](full-bundle-sizing-2026-10-06.md).

The new production-trust candidate is source
`5a390acd8440856e3f4e32de237322a18bb82d7e`, built once in
[run 37618824677](https://github.com/comparativechrono/workbench/actions/runs/37618824677).
Its exact Starter/updater passed **13 setup, 32 workspace, eight References,
nine results/CWL/DAG/icon and 13 upgrade checks per Windows path**. Each upgrade
preserved **203 existing files** and verified **72 target core files**. References'
optional updater helper was not requested; the separate 0.9.0 upgrade suite
supplies its own evidence. The build source gate passed **152 tests**, with one
Windows-only skip; the separate Windows pack-manager suite passed all **42**.
Live production Full passed **four checks in each Windows path**, installing all
32 exact published pins with the bundled owner trust, reopening offline and
preserving 202 expected alignment/BAM records. The separate isolated-fixture
all-pack gate also passed four checks. All six candidate workflow jobs succeeded.

The [new archive audit](evidence/tool-setup-0.10.0-artifact-audit-2026-10-07.json)
verified all candidate archive hashes/CRCs, 572 Git-matched source files,
143 unchanged Starter pack files, the reviewed production source and exact
updater replacements. See the [handover](tool-setup-0.10.0-handover.md),
[new validation record](evidence/tool-setup-0.10.0-validation-2026-10-07.json) and
[acceptance record](evidence/tool-setup-0.10.0-acceptance-2026-10-07.json) for final
promotion status. Earlier candidate `8cee606` and its validator corrections remain
separate [historical evidence](evidence/tool-setup-0.10.0-validation-2026-10-06.json).

The **official signed catalogue is published and independently verified**.
Owner-started [run 37617540915](https://github.com/comparativechrono/workbench/actions/runs/37617540915)
published all 32 exact pins from reviewed `main` at
`9f82aa5d1d9a0a372fc0492b7dff448694af8813`. The reviewed public source is bundled
in candidate `5a390acd`; its live production Full gates passed in both paths. The earlier
empty-trust candidate is historical evidence and is not promoted as the
production Full installer. [Merged PR #3](https://github.com/comparativechrono/workbench/pull/3)
retains implementation and evidence; published 0.9.0 and existing pack bytes
remain unchanged.

## Catalogue signing infrastructure, 2026-10-07

The protected manual signing/publication infrastructure was merged into `main`
at `9f82aa5d1d9a0a372fc0492b7dff448694af8813` through
[PR #4](https://github.com/comparativechrono/workbench/pull/4). It passed **56 source
checks, zero failures/errors/skips**, in
[run 37583926483](https://github.com/comparativechrono/workbench/actions/runs/37583926483).
The [dated evidence](evidence/catalogue-signing-2026-10-07.json) records exact
source identities, test-only signing, mocked publication, and the corrected
historical pack-identity bug and local integration setup errors. These checks
validate signing cleanup, identity binding and publication safeguards; they do
not establish a live production catalogue.

The owner subsequently provisioned the key and public fingerprint and started
[production run 37617540915](https://github.com/comparativechrono/workbench/actions/runs/37617540915).
Both signing and publication jobs passed, including the same **56 source tests**,
fresh download and complete validation of **32 archives / 3,799,806,535 bytes**,
and anonymous public readback. Publication at **2026-10-07T11:58:34Z** created
catalogue commit `0048c4e3644aae7ed172d804fff0981982510e7b` with immutable signed
history. The reviewed owner public fingerprint is
`8d2093f9fafd71de56fea2038faeb2efa0964767d3235430b06428132cdc8505`.

The [independent production audit](evidence/catalogue-production-2026-10-07.json)
verified nine anonymous documents: three current files, four commit-pinned
history files, and the exact source lock/profile. Hashes, all 32 pack pins and
owner identity agree; both the application verifier and a separate
cryptography/OpenSSL verifier accepted the 3072-bit RSA signature. This was the
first catalogue publication, with no prior production history to compare.
No private key was read by the agent. The successful job establishes usable
signing configuration; environment protection settings are still not exposed to
the connector for administrative inspection.

The [owner guide](../publishing/catalogue-signing.md) remains the operational
reference. This catalogue publication does not establish Windows application
validation or release. The public source is bundled into the new 0.10.0
candidate, whose exact-package production gates passed before promotion.
The published 0.9.0 runtime remains unchanged.

## Published CWL results, DAG routing and icon, 2026-10-06

Version **0.9.0** adds a packed CWL v1.2
`workflow.cwl` in each newly prepared analysis, preserving frozen dependencies,
parameters, pack pins, hashes, provenance and actual original-run status. Its
embedded Python runner is independent of Workbench; rerunning it externally
needs a CWL engine, Python 3.10+, matching packs and the input data. Normal native
app operation keeps its bundled runtime and existing standalone requirements.

The same release changes route saved/native DAG edges around cards and
derive a native multi-resolution application icon from the repository SVG.
Exact candidate `beea34ab29f3e7cb9a7e79dbcfa11c89f40ee59d` was accepted,
merged in [PR #2](https://github.com/comparativechrono/workbench/pull/2) and
published unchanged. The [acceptance record](evidence/cwl-dag-icon-0.9.0-acceptance-2026-10-06.json)
retains the user's explicit authorization. Initial
[run 37485987457](https://github.com/comparativechrono/workbench/actions/runs/37485987457)
passed **125 source checks** including stock `cwltool` fixture execution, plus
**32 workspace, 9 References/update and 7 science/export/SVG checks per Windows
path**. Its new GUI fixture failed, so the overall run did not pass. The
long-path gate separately passed three checks covering the full five-stage
starter pipeline and 20 output hashes. All three failed validator attempts remain
retained diagnostics. Final focused
[run 37489208656](https://github.com/comparativechrono/workbench/actions/runs/37489208656)
passed **9 checks per path, zero failures/skips**, against the same application
bytes; four normal/83%-zoom captures were reviewed. The zoom capture used a
native button command because the VM taskbar covered its screen location;
physical zoom clicks were already covered by the separate workspace gate.
The [release handover](cwl-dag-icon-0.9.0-handover.md)
records exact downloads, hashes, acceptance and publication checks. The
[CWL results guide](cwl-results.md) records the export contract and limits,
including external input rebinding, optional compatible executable overrides
and the absence of a universal cross-platform or biological-preflight guarantee.
Published 0.8.0 archives, historical release evidence and tool-pack bytes remain
unchanged. The accepted candidate includes its tested 0.6.0 updater. The separate
0.8.0-to-0.9.0 updater passed [run 37527359533](https://github.com/comparativechrono/workbench/actions/runs/37527359533):
13 native checks per path, zero failures/skips, 70 verified core files and
202 preserved existing files. Post-update reference and scientific/CWL analyses
passed. The two earlier updater-fixture failures are retained in the handover.
[Publication run 37528064595](https://github.com/comparativechrono/workbench/actions/runs/37528064595)
passed all steps, including 18 promotion guard checks and fresh anonymous
downloads of all 12 public assets. The [publication receipt](evidence/cwl-dag-icon-0.9.0-publication-receipt-2026-10-06.json)
records the completed publication. The [independent public-download report](evidence/cwl-dag-icon-0.9.0-public-downloads-2026-10-06.json)
confirms all 12 asset hashes/sizes, five ZIP CRCs, three checksum manifests and
unchanged accepted application/updater bytes; the [release validation record](evidence/cwl-dag-icon-0.9.0-release-validation-2026-10-06.json)
retains the exact native evidence. Publication verification did not rerun Windows.

## Published native interface update, 2026-10-06

The user accepted the latest tested **0.8.0** candidate and explicitly authorized
publication. This supersedes the earlier pending tester-acceptance status.
The development prerelease promotes the exact
`b3928ca6a29d22b5f010a303658c2e19c24324da` candidate without rebuilding or changing
its archives. [Release 404720508](https://github.com/comparativechrono/workbench/releases/tag/app-v0.8.0)
was published at **2026-10-06T13:12:15Z** with nine assets. The
[public-download record](evidence/native-ui-0.8.0-public-downloads-2026-10-06.json)
verifies all nine assets, all four ZIP CRCs and both checksum manifests. The
[release validation record](evidence/native-ui-0.8.0-release-validation-2026-10-06.json)
retains the exact accepted-archive evidence. The
[release handover](native-ui-0.8.0-release-handover.md) records the accepted
identities, publication diagnostics and completed public verification.

The work from `ui/galaxy-native-workspace` is merged into `main` for application
**0.8.0** with the user-approved Galaxy-inspired native interface: Tools on the
left, standalone options in the centre, General settings on the right, and a
separate drag/drop Workflow mode whose right pane edits the selected step.
Standalone tools and the workflow preserve independent edits within the running
process. [PR #1](https://github.com/comparativechrono/workbench/pull/1) merged at
`2086175`. Testers accepted the layout, then identified problems with
workflow chaining and input ownership, scrolling text, navigation/deletion,
the first Manage tools opening and unclear tool names/indexing guidance.

The feedback revision leaves new workflow tool ports unconnected and adds
explicit reusable input cards, with file controls owned by the input rather
than duplicated in every tool. It adds canvas panning, visible zoom controls,
Windows gesture handling and hover deletion; repairs native panel repainting
and initial pack-manager state; and names the scientific program in the tool
library. The [starter audit](starter-tool-semantics.md) confirms that SAMtools
sort already converts minimap2 SAM to sorted BAM, while the standalone faidx
utility is not a prerequisite for starter alignment or variant operations.
Published pack bytes, operation IDs and saved pins remain unchanged.

### Current scroll-flashing follow-up

The user confirmed that the nested-output-path pipeline fix worked, but reported
that text still flashes while scrolling. This is user acceptance of the reported
pipeline fix; it does not establish that every workflow or display configuration
is accepted. The previous zero-difference scroll comparison checked settled
images before and after a clean redraw. It did not observe intermediate frames
and is not evidence that scrolling was free from visible flashing.

The current revision makes form and General settings panel descendants paint
together, queues their repaint instead of forcing each scroll message to draw
immediately, and avoids layout/redraw work when scrolling or focus leaves the
scroll position unchanged. It also accumulates small wheel deltas separately for
each panel; a rounded zero movement previously entered the line-up command path.
Exact candidate `b3928ca6a29d22b5f010a303658c2e19c24324da` passed all five jobs in
[run 37453380541](https://github.com/comparativechrono/workbench/actions/runs/37453380541):
82 source checks, the existing 32 workspace and 8 References/update checks in
each Windows path, the five-stage long-path scientific regression, and the new
scroll gate. The [scroll record](evidence/native-workflow-0.8.0-scroll-2026-10-06.json)
binds the reports to the exact package.

At 96 DPI on Windows Server 2022, the new gate sampled **960 desktop frames**
across standalone options, General settings and workflow options at
27.16–31.80 frames/second. There were no unexpected static-text/background frames,
and all 300 requested endpoint transitions were observed. All **18 precision-wheel
cases passed**. The old package also had no unexpected sampled frames, so the
tester's **visual flashing was not reproduced in CI**. Six old precision-wheel
cases failed, reporting zero movement where 48 pixels were expected; those
separate movement failures now pass. Sampling masks edit/button regions and
cannot exclude shorter flashes between frames or establish behavior on the
tester's physical display. The user's later acceptance is separate manual
feedback and does not change what the CI observation established.

Download the [published Windows starter](https://github.com/comparativechrono/workbench/releases/download/app-v0.8.0/native-workbench-0.8.0-starter-windows.zip).
The [accepted CI bundle](https://github.com/comparativechrono/workbench/actions/runs/37453380541/artifacts/11408021439)
is retained as candidate evidence and expires 5 November 2026. The
16,948,940-byte starter SHA-256 is
`df001a80033ff8e834045ec683c79672e0efdbd4880fb89fca8bf8c36d830fdc`.
The bundle, all three ZIP CRCs, build provenance, 68 core entries, 143 unchanged
pack entries, 15 workspace source copies and 14 relevant source files were
verified during candidate acceptance. Published 0.7.0 is unchanged.

### Accepted nested-output-path fix

A later user installation report passed all seven application/integrity checks
but blocked the starter pipeline after its first alignment. The native runner
had produced and hashed 202 SAM records; Python then failed an ordinary-path
existence check on a **269-character** output path. The folder was 255 characters
and both components identified the same file. User registry state was not
captured. No private directory paths or uploaded data are committed.

The earlier correction `0d3282046d7aa05dc822315c9a237c8ac534cd7a` uses explicit Windows
extended paths at pipeline/check filesystem boundaries while retaining ordinary
paths in provenance, plans and tool arguments. Trust, containment and reparse
protections remain enforced. The **82-check source gate** passed, including
seven emulated-path regressions; **22 additional selected core/pack-check
contracts** passed locally. Exact packaged Windows validation passed in
[run 37449356224](https://github.com/comparativechrono/workbench/actions/runs/37449356224).
With long-path policy disabled before fresh private Python processes launched,
the previous package reproduced the missing-output failure on a 268-character
SAM path. The correction passed all **7 core checks and 5 scientific stages**,
and all **20 output hashes** were independently verified; **19 output paths
exceeded 260 characters**, reaching 279. The native result includes BAM and
the expected homozygous **starter:1351 G>A, GT 1/1** call. The original runner
policy was restored afterward. No user machine policy change was required.

The same corrected package passed **32 workspace and 8 References/update
checks in each Windows path**, with zero failures or skips. All 56 capture
hashes were verified. The long-path check itself is a host/CLI execution test,
distinct from the ordinary/space-containing GUI gate.

The [prior long-path bundle](https://github.com/comparativechrono/workbench/actions/runs/37449356224/artifacts/11404414503)
expires 5 November 2026. Extract its starter into a separate folder for review.
The verified starter is 16,948,757 bytes, SHA-256
`71a84d2c6f7f293bf7f57c1fa3221fc942fce57bca61c8ed3344d593c31c262c`.
All 68 core entries, 143 unchanged pack entries and 15 workspace source copies
matched their expected bytes.
The [sanitized long-path record](evidence/native-workflow-0.8.0-long-path-2026-10-06.json)
tracks the report, fix and new regression. Previous 32+8 native results below
remain valid within their original path scope; they did not cover deep result
paths with legacy policy behavior. No universal optional-pack/deep-installation
or shell-dialog long-path support is claimed.

### Prior feedback candidate, retained evidence

The first feedback source `4cb5f335c0d22b159555df90b275c1f7ec32750e` passed
**75 source checks on Linux**, with zero failures or skips. Its native gate
failed before GUI launch when a raw-text SAM assertion rejected equivalent
floating-point formatting; both paths passed eight packaged-host and eight
References/update checks. Revised source
`0d2a993fca95a5837a69aa05c63aa5e806c553af` includes a typed comparison and
small-delta Ctrl+wheel handling, and passed
[run 37441781509](https://github.com/comparativechrono/workbench/actions/runs/37441781509).
Each ordinary and space-containing Windows installation passed **32 workspace
checks** (8 host, 2 scientific and 22 GUI) plus **8 References/update checks**,
with zero failures or skips, on Windows Server 2022/private Python 3.13.16 at
96 DPI. Native minimap2-to-SAMtools sorting preserved 202 properly paired
alignment records and produced coordinate-sorted BAM. Native pointer checks
covered connections, pan/zoom, hover deletion/Undo, input ownership and Manage
tools. The scroll comparison found zero differences across 197,198 sampled
static-text/background pixels per path in settled images, not intermediate
scrolling frames; all 56 workspace/References capture
hashes were verified. See the [feedback record](evidence/native-workflow-0.8.0-feedback-2026-10-06.json)
and [native UI guide](native-ui.md) for exact scope and limitations.

The [prior feedback candidate bundle](https://github.com/comparativechrono/workbench/actions/runs/37441781509/artifacts/11401422780)
expires 5 November 2026; it does not contain the nested-output-path correction.
The 16,948,268-byte starter has SHA-256
`de099e5feef437c788352c31c0e743c7e8f22aa08bfe2364e59b715ec3501806`;
its 68 core entries, 143 unchanged pack entries and 15 workspace source copies
were verified.
Physical trackpad pinch, high-DPI/multi-monitor movement and native folder
pickers remain unvalidated. Layout acceptance does not establish acceptance of
these changed workflow behaviors; manual retesting remains outstanding.

The previous candidate at `c82c559d02a0b70e79afe67da93ace9e344f1ef3` passed
18 workspace and 8 References/update checks per Windows path in
[run 37376078599](https://github.com/comparativechrono/workbench/actions/runs/37376078599),
with verified archives/inventories and 36 capture hashes. Its
[2026-10-05 evidence](evidence/native-ui-0.8.0-development-2026-10-05.json)
is historical and does not cover the feedback fixes. Updater coverage is
0.6.0-to-0.8.0 only; no 0.7.0 upgrade is claimed. Published 0.7.0 bytes and all
dated release evidence below remain unchanged.

## Reference-discovery release

The 0.7 source adds a native References finder and offline local library,
initially using release-pinned Ensembl archive datasets. Genome FASTA, GTF,
cDNA, ncRNA and protein files can be explicitly downloaded, checked, expanded
and bound to compatible tool inputs. Receipts and exact file hashes feed into
the frozen plan, methods and results. Reference datasets stay separate from
executable packs. Current reference documentation is in the
[0.7 guide](../docs/reference-discovery-0.7.md).

The [0.7.0 release](https://github.com/comparativechrono/workbench/releases/tag/app-v0.7.0)
promotes the exact rc3 archives. The separate exact-final native
[run 37320844819](https://github.com/comparativechrono/workbench/actions/runs/37320844819)
passed eight checks in each ordinary and space-containing Windows path, with
zero failures or skips. Live downloads/cancellation, integrity, offline reference
use and native SAMtools indexing, frozen provenance, 0.6.0-to-0.7.0 preservation,
measured References layout, search/discovery/reset and actual **Use for input**
binding were checked. All twelve final captures were reviewed and their hashes
verified. The [final native record](evidence/reference-0.7.0-final-windows-2026-10-05.json)
and [final eight-asset verification](evidence/reference-0.7.0-final-assets-2026-10-05.json)
bind this completed release gate to its exact bytes. The release supplies the
final report, full Windows evidence and supplemental checksums; candidate
evidence remains separate history.

The source companion includes AGENTS and knowledge files. The updater preserves
installed packs, saved pins/settings, results and references. Its tested native
CLI is distinct from the untested updater folder-picker interaction. The later
concurrency audit below adds GUI download/cancel coverage. Folder pickers,
wider high-DPI/multi-monitor acceptance, Unicode/long paths,
human genomes and institutional proxies remain outside the automated gate.
The [release handover](reference-release-handover.md) retains exact identities,
failed candidates and scoped evidence; existing pack audits remain dated.

### Concurrent work audit, 2026-10-05

The follow-up audit compared released `main` at `0993e85` with the independent
`finish-reference-release` branch at `5a54556`. The independent desktop fixes
were already covered by the released implementation. Its rc2 publication run
stopped before building or publishing because that candidate already existed;
its latest pending-rc3 documentation predates the final acceptance and release.
No open pull request or active workflow was present at the initial audit. The
[retained state](evidence/reference-concurrency-initial-state-2026-10-05.json)
records those observations without treating the independent branch's historical
pending status as the current release status.

All eight final public assets were freshly downloaded and verified again; the
[artifact audit](evidence/reference-concurrency-assets-audit-2026-10-05.json)
passed 57 assertions covering hashes, inventories, source correspondence and
retained native evidence. No published bytes changed. Useful additional native
Download/Cancel coverage was ported into the existing gate in commit `ad5b59c`;
the obsolete candidate-specific workflow and stale documents remain unmerged.
The expanded exact-final [run 37339280407](https://github.com/comparativechrono/workbench/actions/runs/37339280407)
passed eight checks per path with zero failures or skips. The
[fresh native audit](evidence/reference-concurrency-windows-2026-10-05.json)
passed 43 independent evidence checks; all twenty captures were hash-verified
and visually reviewed. The native UI selected all five file checkboxes, typed a
destination containing spaces, downloaded there, preserved existing references,
and bound existing and new downloads through **Use for input**. The GUI Cancel
case stopped early without publishing a ready entry or leaving partial output;
the separate backend cancellation case stopped after at least 1 MiB transferred.
The existing offline/provenance, native SAMtools and updater-preservation gates
also ran again. See the [reconciliation record](evidence/reference-concurrency-reconciliation-2026-10-05.json)
for the full evidence and preserved independent history. No application change
or replacement release was needed; version remains **0.7.0**, with no
concurrency-related blocker.

Three new audit supplements retain the expanded Windows reports and captures
alongside the unchanged original eight release assets. Their independent public
download verification is [recorded separately](evidence/reference-concurrency-public-assets-2026-10-05.json).

### Initial resume audit, retained as history

The resume started from clean `main` at
`5338853ba3b69438fc36c1b9dcd3ad89d6bbcde4`; work continues on
`release/reference-0.7.0-completion`. The published diagnostic candidate
[`app-v0.7.0-rc1`](https://github.com/comparativechrono/workbench/releases/tag/app-v0.7.0-rc1)
points to `8ad25c71ec13d2c06a670b59a2cc13ca84a50ac9`. An exact GitHub release lookup
for `app-v0.7.0` returned 404 at the initial audit. At that checkpoint 0.7.0 was
not a completed release, and rc1 did not contain the later interface fix.

The missing interface finding is now recovered: the online References details
panel overlapped the destination/download row by 15 pixels. The last Windows
[run 37295599791](https://github.com/comparativechrono/workbench/actions/runs/37295599791)
also failed while the automation synchronously sent a right-arrow key to the
native tab control. Existing commit `b9d0ee7` reserves the layout gaps and queues
the key event; `5338853` clarifies the validation scope. Neither fix had a Windows
workflow run at the resume audit. They require a rebuilt candidate and native
validation, not an assumed pass.

That failed Windows run nevertheless records seven completed backend/native CLI
checks in each ordinary and space-containing installation path, including all
five live yeast downloads, cancellation, offline use/provenance and native
SAMtools indexing. The reported “0.6.0 update” means the **0.6.0-to-0.7.0 updater
CLI**, not an update to 0.6.0 or a tested folder-picker interaction: 187 existing
files were preserved and only the expected `user-data/session.lock` was added.
These are recovered historical results for rc1 bytes, not new Windows execution.

The resumed Linux checks passed **93 tests, zero failures/errors/skips** for
reference discovery, download, provenance, service/host, packaging and updater
contracts. The [fresh report](evidence/reference-resume-source-checks-2026-10-05.json)
and [log](evidence/reference-resume-source-checks-2026-10-05.txt) also confirm all
15 runtime hashes recorded with the earlier 139-test source report still match.
This does not rerun those 139 tests or establish a Windows GUI pass. See the
[release handover](reference-release-handover.md) for exact identities and remaining
gates. The 0.6.0 and pack inventory below retains its original audit scope.

## What is available

The native desktop application **0.8.0** and **32 distinct tool packs** are
published as development prereleases. There are 33 published pack versions,
because kallisto 1.0.0 is retained after being superseded by 1.0.1. Historical
candidate releases are additional diagnostics, not current analysis packs.

The Windows starter contains only the `align`, `bam` and `variants` packs
(minimap2, SAMtools and BCFtools). Users extract the starter and run
`NativeWorkbench.exe`; no Docker, WSL, browser launch or system Python is required.
Additional packs install through **Manage tools > Import pack ZIP**, including on
offline computers. The [0.8.0 application release](https://github.com/comparativechrono/workbench/releases/tag/app-v0.8.0)
supplies a 16,948,940-byte starter, a separate updater for an existing **0.6.0**
installation, the explicit matching source companion and checksums/build evidence.
There is no 0.7.0-to-0.8.0 updater; use a separate starter installation and retain
the existing 0.7.0 folder.
Individual tool packs can be much larger. The unchanged
[0.6.0 baseline release](https://github.com/comparativechrono/workbench/releases/tag/app-v0.6.0)
retains its historical 0.5.4 updater, SDK, source and verification assets; its
16,871,065-byte starter is the exact baseline for the new update. The JSON
inventory preserves that earlier application record separately.

The current published pack identities are below. The JSON inventory records
their exact release URLs, archive filenames, sizes and GitHub-reported digests.
These are **pack versions**, which differ from upstream tool versions.

| Pack ID | Current pack version | Purpose |
| --- | --- | --- |
| `align` | 0.4.0 | minimap2 read alignment; starter |
| `bam` | 0.4.0 | SAMtools alignment-file operations; starter |
| `variants` | 0.4.0 | BCFtools variant operations; starter |
| `reads` | 0.4.0 | Read quality |
| `trimming` | 0.4.0 | Read trimming |
| `fastp` | 0.4.1 | Read preprocessing and reports; retain the report fix |
| `bwa` | 0.4.0 | BWA alignment |
| `bowtie2` | 0.5.3 | Bowtie 2 DNA alignment |
| `hisat2` | 0.5.3 | HISAT2 DNA and RNA alignment |
| `freebayes` | 0.4.0 | FreeBayes variant calling |
| `lofreq` | 0.5.3 | LoFreq variant calling |
| `vardict` | 0.5.3 | VarDictJava targeted variants |
| `mutect2` | 0.5.4 | GATK Mutect2 somatic variants |
| `variant-pipeline` | 0.4.0 | Existing bundled variant pipeline |
| `research-variants` | 0.4.1 | Existing research variant workflows |
| `seqkit` | 0.5.2 | Sequence utilities |
| `muscle` | 0.5.2 | Multiple sequence alignment |
| `vsearch` | 0.5.2 | Amplicon operations |
| `star` | 1.0.0 | Bulk RNA alignment and optional annotated gene counts |
| `kallisto` | 1.0.1 | Bulk RNA transcript quantification |
| `fastqc` | 1.0.0 | Single/paired FASTQ quality reports |
| `multiqc` | 1.0.0 | Aggregate explicitly selected local QC reports |
| `featurecounts` | 1.0.0 | Single-end RNA read or paired-fragment gene counts |
| `bedtools` | 1.0.0 | BED interval operations and reference sequence extraction |
| `blast` | 1.0.0 | Local nucleotide/protein and translated similarity searches |
| `gatk` | 1.0.0 | GATK 4 germline calling, alignment preparation, gVCF combination/genotyping and VCF operations |
| `snpeff` | [1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-snpeff-v1.0.0) | SnpEff/SnpSift local annotation databases, consequences, INFO annotation and impact selection |
| `deseq2` | [1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-deseq2-v1.0.0) | DESeq2/tximport bulk gene-level differential expression |
| `mosdepth` | [1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-mosdepth-v1.0.0) | Complete-reference and target-region BAM coverage |
| `iqtree` | [1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-iqtree-v1.0.0) | Nucleotide/protein maximum-likelihood tree inference from alignments |
| `kraken2` | [1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-kraken2-v1.0.0) | Register/prepare local databases and classify single or paired FASTQ reads |
| `bracken` | [1.0.0](https://github.com/comparativechrono/workbench/releases/tag/pack-bracken-v1.0.0) | Estimate taxonomic abundance from a Workbench classification record or explicitly declared external report |

Existing bundled pipeline packs remain available for reproducibility. The
development direction is individually usable tools or small related operations
composed into user-built pipelines. Installing a newer pack does not replace the
version or manifest hash pinned by a saved pipeline.

## What the evidence establishes

The initial 2026-10-04 handover read release metadata and RNA CI records; it did
not repeat every older binary download or scientific run. The later optional-pack
work independently downloaded and rehashed each new public release asset,
retained Linux/source regression evidence, and ran the exact final pack ZIPs
through the released 0.6.0 native Windows bridge. The inventory records these
verification levels separately. Earlier application and pack evidence remains
dated evidence for its original bytes, not a fresh test of every older tool.

| Component | Recorded evidence | Boundary |
| --- | --- | --- |
| App 0.8.0 | Exact accepted archives promoted unchanged; 82 CI source checks, 32 workspace and 8 References/update checks per native path, full starter long-path pipeline and 960-frame/18-case scroll checks passed; user accepted the candidate; all nine public assets independently downloaded and verified | Native display scope is Windows Server 2022 at 96 DPI. CI did not reproduce visual flashing on either package; precision-wheel movement failure was reproduced and corrected. Updater coverage is 0.6.0 only. |
| App 0.7.0 | Release work: 93 Linux source-contract passes and eight exact-final native checks per path. Follow-up concurrency audit: eight public assets downloaded again, 57 artifact assertions, eight new native checks per path with zero failures/skips, 43 evidence assertions and twenty captures reviewed, including GUI Download/Cancel | References-specific GUI and packaged-host/native CLI coverage at 96 DPI on Windows Server 2022; GUI Cancel stops early and a separate backend case cancels after 1 MiB. Folder pickers and broader desktop/path acceptance remain outside the gate. |
| App 0.6.0 | 214 automated tests passed, one Windows-only skip; eight starter checks; actual 0.5.4-to-0.6.0 updater migration on Linux; desktop/updater compiled with warnings treated as errors | Scientific execution used the portable Linux reference backend. This is not proof of the current Windows GUI or native long-path behavior. |
| Original 18 independent archives | Preserved original pack IDs, versions, manifests, contents and licence/source materials; archive inventories, sizes, hashes and ZIP CRCs audited | Repackaging did not constitute a new native Windows execution test for every tool. |
| STAR 1.0.0 | Eight Linux scientific tests and six released-app graph/import contracts; exact published archive passed native Windows CI in ordinary and space-containing paths | Five scientific fixtures plus a two-thread, two-pass buffer regression; small synthetic data, not a human-genome benchmark. |
| kallisto 1.0.1 | Ten Linux scientific tests and six released-app graph/import contracts; exact published archive passed native Windows CI in ordinary and space-containing paths | Single/paired fixtures exercise two threads and three bootstrap replicates; not validation of all RNA-seq protocols. |
| FastQC 1.0.0 | Eight Linux source/scientific tests; exact final ZIP passed two native scientific checks in each path | Single plain and synchronized paired gzip FASTQ; counts, bases, GC and Q40 truth; private Java runtime, no GUI acceptance claim. |
| MultiQC 1.0.0 | Ten Linux source/regression tests, including real FastQC output; exact final ZIP passed its multi-input native check in each path | Six explicitly selected reports exercise five parsers; no whole-folder scanning, sample-merging inference or clinical interpretation. |
| featureCounts 1.0.0 | Eight Linux scientific/guard tests; exact final ZIP passed six native checks in each path | Single/paired counting at two threads, all three strand modes and known gene/assignment truth. |
| BEDTools 1.0.0 | Seven Linux regression tests, with all 15 fixture cases compared byte-for-byte to unmodified upstream; exact final ZIP passed 15 native checks in each path | Interval truth, CRLF, valid empty results, 64-bit coordinates and forward/reverse-complement extraction; exposed BED operations only. |
| BLAST 1.0.0 | Linux tests: 10 passed and one deliberately skipped on unmodified upstream; all 11 passed on the patched build. Exact final ZIP passed five scientific checks and six additional regressions in each native path | Four search modes, known coordinates/frames and a legitimate no-hit case; local-only failure regressions are separate from OS network isolation. |
| GATK 1.0.0 | Fourteen Linux scientific/regression tests passed. Exact final native Windows gate passed nine scientific checks and seven graph/archive contracts in each path, with no failures/errors/skips | Nine exposed operations with synthetic variant/genotype, duplicate and recalibration truth; no general Windows GATK support, clinical validation or whole-genome/cohort performance claim. |
| SnpEff 1.0.0 | Exact final ZIP passed four native installation/scientific checks, six graph/archive contracts and 13 additional scientific/failure regressions per path | Independent codon and allele truth, explicit database genetic codes and whole-record impact selection; consequences are not pathogenicity or assembly validation. |
| DESeq2 1.0.0 | Exact final ZIP passed three native installation/scientific checks, six graph/archive contracts and 14 additional scientific/failure regressions per path | Direct upstream matrix and tximport oracles cover 300 genes each. Synthetic bulk-expression/design/import tests do not establish experimental adequacy, FDR calibration or large-cohort performance. |
| mosdepth 1.0.0 | Exact final ZIP passed four native installation/scientific checks, six graph/archive contracts and 11 additional scientific/failure regressions per path | BAM/CIGAR/pair-overlap and full-reference denominator truth, BED targets and malformed-input rejection; no base-quality filtering or RNA expression claim. |
| IQ-TREE 1.0.0 | Exact final ZIP passed four native installation/scientific checks, six graph/archive contracts and 13 additional scientific/failure regressions per path | DNA/protein model and support truth, real MUSCLE-to-IQ-TREE execution, safe taxon restoration and bounded summaries; not species-tree or large-dataset validation. |
| Kraken2 1.0.0 | Exact final ZIP passed 6 native installation/scientific checks, 6 graph/archive contracts and 16 additional scientific/failure regressions per path | Synthetic assignments, paired fragment counts, gzip and local database/path guards; no production database bundled or large-database/clinical validation. |
| Bracken 1.0.0 | Exact final ZIP passed 4 native installation/scientific checks, 7 graph/archive contracts and 17 additional scientific/failure regressions per path | Independent Bayesian arithmetic, exact upstream estimator and real Kraken2-to-Bracken execution; database/model association, read-length approximation and estimated-abundance denominators remain explicit. |

The five-pack October [graph/import report](evidence/popular-pack-graph-contracts-2026-10-04.json)
records **eight tests passed, zero failures/errors/skips** on Linux with the
unchanged released 0.6.0 app and the corrected frozen BLAST guard. It binds the
exact ZIP/manifest hashes of the disposable graph-tested pack copies to FastQC
fan-in reporting, STAR-to-featureCounts branches at a shared DAG level, merged
reporting and BEDTools-to-BLAST nucleotide search. Type/pairing mismatches,
missing strand choices, duplicate connections and changed saved pins are rejected.
It explicitly records that no scientific executable or native importer ran.

The RNA graph/import contract tests used a Python copy callback in place of
native folder publication. The separate Windows jobs exercised the released
0.6.0 app's actual native bridge, pack import and duplicate-version rejection.
Do not describe the former as equivalent to the latter.

Final native Windows records:

- [STAR run 37149903110](https://github.com/comparativechrono/workbench/actions/runs/37149903110)
  completed successfully at source `1b87d7506898d49e339e547e02aed53ed7a9b167`.
  All five checks passed in each location. The additional buffer regression
  produced 400 SAM records from 200 read pairs with expected gene counts and
  identical ordinary/recycled-buffer results; installed pack files were unchanged.
  [Final validation JSON](https://github.com/comparativechrono/workbench/releases/download/pack-star-v1.0.0/native-workbench-star-1.0.0-windows-validation.json).
- [kallisto run 37150386848](https://github.com/comparativechrono/workbench/actions/runs/37150386848)
  completed successfully at source `a3a14f015c375fc318f4b0114b785667c6f26472`.
  Single-end and paired-end checks both passed at two threads and three
  bootstrap replicates in each location, including gzip reads.
  [Final validation JSON](https://github.com/comparativechrono/workbench/releases/download/pack-kallisto-v1.0.1/native-workbench-kallisto-1.0.1-windows-validation.json).

The added packs' final runs also used the actual native importer and rejected a
duplicate version without replacing the installed manifest:

| Pack | Exact-final Windows run | Scientific checks per path |
| --- | --- | --- |
| FastQC 1.0.0 | [37207251061](https://github.com/comparativechrono/workbench/actions/runs/37207251061) | 2 |
| MultiQC 1.0.0 | [37208730673](https://github.com/comparativechrono/workbench/actions/runs/37208730673) | 1 multi-input case |
| featureCounts 1.0.0 | [37208535793](https://github.com/comparativechrono/workbench/actions/runs/37208535793) | 6 |
| BEDTools 1.0.0 | [37207758617](https://github.com/comparativechrono/workbench/actions/runs/37207758617) | 15 |
| BLAST 1.0.0 | [37210341211](https://github.com/comparativechrono/workbench/actions/runs/37210341211) | 5, plus 6 adapter/local-failure regressions |
| GATK 1.0.0 | [37220420948](https://github.com/comparativechrono/workbench/actions/runs/37220420948) | 9, plus 7 graph/archive contracts |
| mosdepth 1.0.0 | [37228329920](https://github.com/comparativechrono/workbench/actions/runs/37228329920) | 4, plus 6 graph/archive contracts and 11 scientific/failure regressions |
| IQ-TREE 1.0.0 | [37229409061](https://github.com/comparativechrono/workbench/actions/runs/37229409061) | 4, plus 6 graph/archive contracts and 13 scientific/failure regressions |
| SnpEff 1.0.0 | [37229552990](https://github.com/comparativechrono/workbench/actions/runs/37229552990) | 4, plus 6 graph/archive contracts and 13 scientific/failure regressions |
| DESeq2 1.0.0 | [37230943331](https://github.com/comparativechrono/workbench/actions/runs/37230943331) | 3, plus 6 graph/archive contracts and 14 scientific/failure regressions |

The four new exact-final runs used the released 0.6.0 application unchanged in
ordinary and space-containing `windows-2022` paths. mosdepth's helper source was
`102e85e2ce38c750b521c70e532001dd55451509`; IQ-TREE, SnpEff and DESeq2 used
`24c6899aa7c19208ec88ae816879952ed0d8527e`. Their release assets include separate
`native-workbench-<id>-1.0.0-windows-validation.json` reports. Graph contracts use
the released Python engine and a checked publication callback; native installation
checks separately exercise the actual bridge/importer and scientific commands.

DESeq2's [source-build development run 37229593426](https://github.com/comparativechrono/workbench/actions/runs/37229593426)
passed all 14 native scientific/failure regressions at source `24c6899aa7c19208ec88ae816879952ed0d8527e`.
This did not import the final ZIP. The subsequent exact-final
[run 37230943331](https://github.com/comparativechrono/workbench/actions/runs/37230943331)
independently passed three native installation checks, six graph/archive
contracts and 14 scientific regressions in each Windows path, with zero
failures/errors/skips. The [dated validation record](evidence/deseq2-1.0.0-validation-2026-10-04.json)
and [public final report](https://github.com/comparativechrono/workbench/releases/download/pack-deseq2-v1.0.0/native-workbench-deseq2-1.0.0-windows-validation.json)
bind these results to archive SHA-256
`eccffbcaf3adad6ab1da63ea771fe103a807a88722a56f5db82072cf02c1292d`
and manifest SHA-256
`f5a06708651f14f25e89ca3588ed6bf2f91442e43d635a9fc7ab5af066112ee1`.
The pack, source/evidence and R-runtime source ZIPs were independently downloaded
and rehashed against the frozen artifacts.

The exact DESeq2 ZIP's earlier Linux graph attempt preserved one strict failure
after temporary extracted files reappeared following cleanup; five
graph/application tests passed and no installed file changed. Earlier six-test
Linux success applies to a different archive. Both exact-final Windows graph
suites subsequently passed all six cases, including duplicate-import immutability,
without weakening assertions. Preserve the original failed report and separate
source-build evidence; the final native report closes the release gate without
rewriting that history.

The corresponding source/evidence ZIPs are listed with digests in the inventory.
They preserve Linux and candidate-stage evidence, including historical status
at creation. The separate final validation JSON supersedes any pending-final-gate
statement inside those immutable companions; do not rewrite the companions.
Passing a scientific fixture is not clinical validation, a full desktop
acceptance test or proof of performance on arbitrary datasets.

GATK's [dated validation record](evidence/gatk-1.0.0-validation-2026-10-04.json)
links the frozen pack, matching source and distinct test stages. Candidate
[run 37220034835](https://github.com/comparativechrono/workbench/actions/runs/37220034835)
passed nine scientific checks and seven graph/archive contracts in each of the
ordinary and space-containing `windows-2022` paths. The scientific gate used the
released native bridge/importer; the graph/archive suite used the unchanged
released Python engine and a copy callback for folder publication.
The exact final [GATK 1.0.0 release](https://github.com/comparativechrono/workbench/releases/tag/pack-gatk-v1.0.0)
then passed the same nine scientific checks and seven graph/archive contracts
in each path in [run 37220420948](https://github.com/comparativechrono/workbench/actions/runs/37220420948),
at source `eb4a255b69a2eabfb539937218a1d0e57c5776a3`, with no failures/errors/skips.
The [separate final validation report](https://github.com/comparativechrono/workbench/releases/download/pack-gatk-v1.0.0/native-workbench-gatk-1.0.0-windows-validation.json)
binds those results to the released ZIP and manifest hashes.

The Linux graph suite's six graph/application tests passed, but its strict
archive-copy test observed transient files or altered hashes inside disposable
copies. The diagnostic reports are retained; there is no claim of a clean
seven-test Linux pass. Windows candidate and final graph/archive checks passed without
weakening the inventory or duplicate-immutability assertions. The published
source companion retains its creation-time status; the separate final validation
report supersedes pending-final statements without changing its bytes.

## Kraken2 and Bracken exact-final evidence

| Final pack | Native Windows run | Recorded result |
| --- | --- | --- |
| Kraken2 1.0.0 | [37235526518](https://github.com/comparativechrono/workbench/actions/runs/37235526518) | 6 installation, 6 graph/archive, 16 scientific/failure checks per path |
| Bracken 1.0.0 | [37236121810](https://github.com/comparativechrono/workbench/actions/runs/37236121810) | 4 installation, 7 graph/archive, 17 scientific/failure checks per path |

Kraken2's [final validation record](evidence/kraken2-1.0.0-validation-2026-10-04.json) binds the exact ZIP and manifest
to helper source `85ef78b0436417a85d8d70ed685dc2a52c24f7a4`. Its final pack SHA-256 is
`9feb39546f6af9d718629304d7fc6a5d70d8a015839deef7d4a869e7587a0e91`.

Bracken's [final validation record](evidence/bracken-1.0.0-validation-2026-10-04.json) binds the exact ZIP and manifest
to helper source `289c4176561fe6c8bbbfba1e225cd65fbafb126d`. Its final pack SHA-256 is
`bfd5ae2ea3ef3e54f3ae5b97530e58bf1aad8562d66ca1c8e190b87472f1d853`.

The unchanged released 0.6.0 application and ordinary/space-containing
`windows-2022` paths were used. Native installation exercised the actual
importer/bridge; graph/archive tests used the released Python engine with a
checked copy callback. Bracken's full scientific suite also executed actual
Kraken classification followed by the unchanged upstream abundance estimator.
Every final public asset was independently downloaded and rehashed.

The separately retained [shared-resource checks](evidence/metagenomics-resources-2026-10-04.json)
passed 17 source-level tests on Linux for descriptor identities, path/archives,
fragment accounting and failure cleanup. That report explicitly records no
scientific executable, native importer or Windows execution; it is not a native
release gate. It is preserved in Git because the earlier source companions did
not include this report.

These are small synthetic checks, not GUI acceptance, production-scale database
benchmarks or clinical validation. The packs remain optional and independently
usable. Reference indexes and Bracken read-length distributions remain separate
local resources; no reference download occurs during analysis. Registration
hashes database bytes but keeps external database/model association explicitly
user-attested. Bracken's external-report operation likewise retains declared
provenance rather than fabricating a Workbench classification history. Exact
read length is the default; representative-length mode is a recorded
approximation. Paired abundance counts fragments, not twice as many mate reads.

Source/evidence companions retain their creation-time pending-final status.
The separate exact-final reports supersede that status without replacing any
published bytes. Historical candidate/failure records remain preserved and are
excluded from the 32 current pack identities. See the
[pipeline guide](../docs/KRAKEN2-BRACKEN-PIPELINE.md) and
[resource contract](../docs/METAGENOMICS-RESOURCES.md).

## Important current limits

See the [RNA-seq guide](../docs/rna-seq-packs.md),
[kallisto pack guide](../docs/KALLISTO-PACK.md),
[additional pack guide](../docs/popular-packs-2026-10.md), each installed `PACK-README.md`
and its bundled provenance files for detailed supported interfaces.

- **STAR 1.0.0** uses STAR `2.7.11b-workbench1`. It builds a private index on
  every run because the 0.6.0 graph cannot expose reusable directory-valued
  products. Inputs are uncompressed genomic FASTA and Phred+33 FASTQ; annotated
  operations require a matching GTF. Paths must be ASCII and contain no commas;
  spaces are supported. Human-scale work generally needs tens of GB of RAM and
  substantial storage; the SAMtools sorting-memory setting does not limit STAR
  RAM. STARsolo, shared-memory indexes, external decompression and CRAM are not
  exposed. RNA alignments are deliberately incompatible with the existing DNA
  calling/preparation operations. Gene counts contain three strand columns;
  users select the column appropriate to the library downstream.
- **kallisto 1.0.1** uses `0.52.0-workbench2`. It needs a transcript/cDNA FASTA
  or compatible version-13 kallisto index, accepts plain/gzip inputs, and requires
  ASCII paths (spaces work). Single-end quantification requires an appropriate
  fragment-length mean and SD in whole bases, not guessed read-length defaults.
  Library strandedness is explicit. Outputs are transcript estimated counts,
  TPM and optional plaintext bootstrap estimates. Differential expression,
  transcript-to-gene aggregation, single-cell BUS, long reads, bias correction,
  BAM and HDF5 are outside this interface. The generic graph index type cannot
  identify every index format; the adapter validates the kallisto version.
- **kallisto 1.0.0** had an upstream conditional-compilation defect in this
  no-HDF5 build: multithread plaintext bootstrap dispatch was skipped. The
  adapter failed on missing outputs; this was not a general failure of zero-
  bootstrap quantification. Its earlier passing checks used one thread.
  Version 1.0.1 fixes dispatch to the existing upstream worker without changing
  its sampling or estimation algorithms. Keep 1.0.0 bytes and pipeline pins
  unchanged; explicitly select 1.0.1 for new/updated pipelines.
- **FastQC 1.0.0** uses unmodified FastQC 0.13.0 with private Temurin
  8u504-b01. Four-line plain/gzip FASTQ, explicit Phred+33/+64 and synchronized
  mates are supported. ASCII paths must exclude semicolons; filenames beginning
  with lowercase `stdin` are rejected because upstream treats them as streams.
  QC flags require interpretation and do not trim or filter reads.
- **MultiQC 1.0.0** uses MultiQC 1.35 with private Python 3.13.16 and pinned
  Windows wheels. It accepts 1–64 explicitly selected metrics files from five
  supported parsers; kallisto requires its captured quantification log, not
  `run_info.json` or `abundance.tsv`. Input names are namespaced to preserve
  separate rows; no biological sample matching is inferred. Implicit settings,
  version checks, uploads and AI are disabled. Its Python audit hook and report
  CSP are bounded controls, not an OS sandbox. Reports do not launch a browser;
  viewing HTML separately may require an approved viewer. Per-run private wheel
  extraction needs about 1 GiB extra disk space.
- **featureCounts 1.0.0** uses the official unmodified Subread 2.1.1 Windows
  executable. It counts one RNA BAM against matching plain GTF, with explicit
  strandedness. Paired counting requires both aligned ends and excludes chimeras;
  supplementary alignments are rejected, NH multimappers/secondary and ambiguous
  reads excluded, and duplicate-marked reads retained. Results are raw integer
  gene counts, not normalization or differential expression. The guard requires
  exact contig names but does not prove genome/sample identity.
- **BEDTools 1.0.0** exposes nine interval operations using
  `2.31.1-workbench1`. Input is consistent plain BED3–6 with zero-based half-open
  coordinates; released 0.6.0 bounds inputs to one million intervals and rejects
  empty downstream BED inputs even when an upstream no-hit result is legitimate.
  Sequence extraction privately copies and indexes plain FASTA, with individual
  contigs bounded to 2,147,483,647 bases. No BED12/GTF/VCF/BAM semantics are implied.
- **BLAST 1.0.0** uses BLAST+ 2.17.0 built with static MSVC runtime from pinned
  NCBI/SQLite source. It exposes BLASTN, BLASTP, BLASTX and TBLASTN with local,
  uncompressed FASTA queries/subjects. Each run builds a private version-4
  database; reusable database folders, remote search and automatic download are
  not exposed. The guard validates complete FASTA records/identifiers and the
  selected alphabet. Similarity hits do not establish function or orthology;
  translated searches require an appropriate genetic code. Narrow source patches
  retain paths with spaces and remove implicit remote sequence/database fallback;
  the guard disables usage reporting and preserves child diagnostics. Exact
  coordinate/translated-frame and local-failure checks are bounded evidence,
  not a network firewall or validation of all BLAST operations.
- **GATK 1.0.0** exposes nine germline/preparation/VCF operations using unchanged
  GATK 4.7.0.0, its existing Workbench local-path adaptation and private Java 17.
  It requires coordinate-sorted single-sample DNA BAMs with a declared sample
  and a resolvable RG tag on every alignment, the matching plain reference, and
  BED intervals for calling/BQSR. MarkDuplicates retains reads and disables
  optical-duplicate detection; it is not UMI-aware. BQSR learns over selected
  intervals using explicit known sites and applies the model to the full BAM.
  HaplotypeCaller uses pure-Java PairHMM/Smith-Waterman implementations, with
  slower performance possible than native acceleration. CombineGVCFs accepts
  two to 32 distinct-sample inputs. Released 0.6.0 uses labelled generic file
  ports for gVCFs, keeping them incompatible with ordinary VCF ports; the
  adapter validates file roles, NON_REF likelihoods and sample uniqueness.
  Generic file connections alone do not establish gVCF compatibility. Genuine
  empty ordinary VCF results remain valid. Filters are explicit site-annotation
  criteria, not a guaranteed Best Practices protocol. GenomicsDB, Spark, VQSR,
  Python-dependent CNV tools and clinical/whole-genome performance validation
  are outside this scope. See the [pack guide](../docs/GATK-PACK.md).
- Resource demands and portability constraints remain tool-specific. A local
  GUI cannot make a large reference fit into insufficient RAM. Do not promise
  generic Linux binary compatibility, arbitrary Unicode paths or universal
  support for every upstream command.

The [four-pack guide](../docs/ANNOTATION-EXPRESSION-COVERAGE-PHYLOGENETICS.md)
describes the newer limits. SnpEff database resources remain separate local
inputs with explicit assembly/release/codon mappings. DESeq2 accepts independent
bulk samples with condition or additive batch-plus-condition designs; raw count
semantics and actual biological independence cannot be proven by broad metrics
ports. Its private per-run R tree consumes extra disk, and R scratch needs a
space-free path or existing short alias. Mosdepth aggregates all BAM samples,
including uncovered reference contigs in its primary denominator; it applies no
base-quality filter. IQ-TREE consumes aligned nucleotide/protein sequences and
omits detailed JSON bipartitions above 256 taxa while preserving the complete
Newick tree. Small synthetic checks establish neither GUI acceptance nor clinical
or human-genome/cohort performance.

## Unfinished work and safe starting points

1. **Catalogue maintenance and future packs.** Application 0.10.0, the signed
   32-pack catalogue and reviewed public source are published and verified;
   production Full and all exact-package gates passed. New official packs must
   retain the protected publication process and deliberately reviewed profile
   changes. Preserve the catalogue key, immutable published bytes and saved
   version pins; Manage tools and offline import remain available for additions.
2. **Broader desktop acceptance and long paths.** The 0.8.0 gates cover the
   recorded workspace and References interactions at 96 DPI; they do not establish the
   entire desktop, folder-picker interactions, high-DPI or
   multi-monitor behavior, Unicode/long paths or managed-PC usability. Record
   exact versions/environment when adding those checks, and run
   **File > Check installation** on target machines.
3. **Broader scientific and usability coverage.** Expand native checks for packs
   without equivalent current evidence, resource guidance and representative
   datasets. Preserve tool defaults in validation cases and exercise optional
   features explicitly. Keep patient/private data out of public fixtures and
   release diagnostics.
4. **Future schema improvements.** Reusable STAR indexes need a designed,
   versioned directory-product contract; tool-specific index typing is also a
   useful extension. These remain proposals, not implemented 0.8.0 features.

The older `publishing/releases-0.6.0.json`,
`publishing/publication-layout-0.6.0.json` and parts of the publication guide
describe the original **18-pack split**. They are not the complete later optional-pack
inventory. Preserve their historical meaning and use this snapshot when planning
the next catalogue generation; add validated release mappings deliberately.

The [public RNA candidate release](https://github.com/comparativechrono/workbench/releases/tag/rna-candidates-20261003)
is a diagnostic archive. Its early STAR candidates exposed logging/buffer faults;
later candidates established correspondence with the final packs. Do not present
candidate downloads as current supported analysis versions, remove historical
published bytes, or infer that a successful candidate replaces an exact-final
archive check.

The [October optional-pack candidates](https://github.com/comparativechrono/workbench/releases/tag/popular-candidates-20261004)
retain failed and superseded diagnostics. featureCounts' first candidate counted
correctly but its full-row checks did not accept Windows CRLF; a stale second
candidate was not promoted. MultiQC's first candidate exposed the runner's
precreated output directory behavior. Later candidates and exact-final gates
record the fixes; retain historical bytes and correspondence reports. BLAST
0.0.1 passed five scientific result-file checks per path but lost child diagnostic
output; candidate 0.0.2 uses explicit inherited standard handles and passes the
additional local-failure regressions. Only the separate exact-final gate validates
the published 1.0.0 archive.

Finally, a Git clone alone is not the full third-party build environment. Recover
the explicit [0.8.0 application source companion](https://github.com/comparativechrono/workbench/releases/download/app-v0.8.0/native-workbench-0.8.0-source.zip)
and matching pack source/licence materials as described in
[source recovery](../docs/source-recovery/README.md). Do not depend on a previous
agent's scratch paths, compiler cache, browser session or unpublished credentials.

DESeq2's complete corresponding sources additionally require the separate
`native-workbench-deseq2-1.0.0-r-runtime-sources.zip` release asset: Rtools base
libraries and compiler runtimes, Tcl/Tk extensions, original notices and exact
build recipes/patches. Its runtime-bound lock and SHA-256 are recorded in
`tools/deseq2/`; see [the recovery notes](../tools/deseq2/R-RUNTIME-SOURCES.md).
The smaller source/evidence companion contains tracked source and reports, not
this external-library archive. Installed packs never fetch sources during analysis.
