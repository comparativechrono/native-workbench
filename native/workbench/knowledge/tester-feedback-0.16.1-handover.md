# Tester-feedback revision of unpublished 0.16.1

Implementation checkpoint: **2026-10-09**. Work continues on
`fix/native-ui-0.16.1` in [draft PR #15](https://github.com/comparativechrono/workbench/pull/15),
from verified starting head `8cd3457745da52d38b5470c9ae917c8394ca46b0`.
The PR remains stacked on `feature/deployment-acceptance`, base
`f74d90229be6a78d6ad0c0076c54c04bb7e7cae2`, and unmerged draft
[PR #14](https://github.com/comparativechrono/workbench/pull/14).
Published **0.16.0**, `main` and all published assets remain unchanged.

This is a further revision of the unpublished **0.16.1** candidate, not a release.
Implementation is frozen at application source
`73778e00461e2b83c07b9ea97df2b9c5d4b6317d`. Source/build validation, archive
correspondence and seven regression scopes are complete. Final native coverage is **113 checks per Windows path**, including the complete
13-check tester-feedback gate. The recorded source, archive, native, temporal
and visual reviews are complete; this is ready as an **unpublished draft review
candidate** within the limits below. No merge or publication is part of this work.

## Implemented revision contracts

| Area | Revision contract | Required observations |
| --- | --- | --- |
| Run and polling | Remove redundant redraws during unchanged status polling and address the reported Run flashing. Retain meaningful state updates, mutation guards and command ordering. | Temporal captures around Run and repeated polling, with actual state changes still visible; no inference of zero flicker from a settled screenshot. |
| Tool categories | Preserve the viewport anchor when expanding a category and address the black flash on collapse. | Expansion/collapse at meaningful scroll positions, stable anchor behavior and temporal captures of the visible window. |
| Methods and preflight | Restore Methods as a separate action and remove the primary Readiness button. Keep Run preflight and its actionable validation. Do not add runtime or memory forecasts. | Native control visibility, Methods content, invalid-input blocking and valid Run behavior. |
| Samples | Add native New, Edit and Save as CSV/TSV, with a verified one-row Starter example. | Create/edit/export/reimport through the native controls, cancellation and error cases, and scientific batch use of the resulting table. |

The sample editor must keep file-path columns, base folders and input mapping
explicit. Only columns marked as file paths are resolved for export; metadata
must not be guessed to be paths. Saving elsewhere must preserve the intended
input identities, and Save as must preserve an existing destination file.
The example represents one synthetic sample using the existing Starter inputs;
duplicating its rows must not be presented as independent biological replicates.
Loading or editing a table does not silently choose a workflow or run analysis.

The previous keyboard/focus and narrow-display fixes remain requirements.
Reference management, existing workflows, saved pins, published pack bytes and
scientific known answers must remain intact. Recorded measurements still do not
establish invented QC pass thresholds.

## Evidence boundary

The preceding [UI-patch handover](ui-patch-0.16.1-handover.md) and its receipts are
immutable historical evidence for application source
`8938e709b041106e8a46e1447383e8e9ba3e0cb9` and final validator
`69022689e686b2cacdc98dbdbef728e664941e67`. Its **141 source passes, 84 native
checks per path, 19 repeated patch checks per path, archive audit and settled
96-DPI visual review apply only to those prior archives**. They do not test this
tester-feedback revision. Original failed attempts and the corrected screenshot
interpretation remain in those records.

New application bytes require a new source/archive correspondence audit and
their own source, native, temporal and screenshot results. Record application
and validator commits separately. A repeat of a gate on unchanged archives is a
repeat observation, not additional unique coverage.

## Exact candidate and downloads

[Build/native run 37997370988](https://github.com/comparativechrono/workbench/actions/runs/37997370988)
created the frozen application archives. The
[archive audit](evidence/tester-feedback-0.16.1-archive-audit-2026-10-09.json)
records independent downloads, ZIP integrity and correspondence to committed
source; the [transport receipt](evidence/tester-feedback-0.16.1-transport-2026-10-09.json)
records verified source-part reassembly. Subsequent gates do not rebuild them.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-0.16.1-starter-windows.zip` | 17,879,604 | `1291f93b5ece3c4da34eb2f2e29fccc83b6d87ec5fb73abf28bfd9cc8f155b75` |
| `native-workbench-0.16.1-source.zip` | 48,270,849 | `0accfb48b8b7b3193b4c72e76c45c404db7979d877ce0805d2687d5a849fe1f1` |
| `native-workbench-0.16.1-update-from-0.16.0.zip` | 13,042,264 | `86dd3d9796099b366a9e01012acc50d00d501a1fdaab89b7119236b44db4b4d8` |

Actions downloads:
[Starter](https://github.com/comparativechrono/workbench/actions/runs/37997370988/artifacts/11647526336),
[core updater](https://github.com/comparativechrono/workbench/actions/runs/37997370988/artifacts/11647591236),
[combined candidate/source](https://github.com/comparativechrono/workbench/actions/runs/37997370988/artifacts/11647531259),
[source part 1](https://github.com/comparativechrono/workbench/actions/runs/37997370988/artifacts/11647676250)
and [source part 2](https://github.com/comparativechrono/workbench/actions/runs/37997370988/artifacts/11647641125).
The combined wrapper was not independently downloaded; the five bounded
transfer wrappers were verified and the source parts reassembled in order.
The [artifact inventory](evidence/tester-feedback-0.16.1-artifacts-2026-10-09.json)
retains API wrapper digests and expiration dates. These are temporary Actions
artifacts, not published release assets.

The audit matched **826 Git source files**, **34 packaged runtime-source files**,
two example-source files and **90 core files**. All **186 published pack files**
and **39 private-runtime files**, exact pack pins, production trust and setup
selection remain unchanged. Nine updater operations reconstruct the exact new
Starter core. Hash correspondence does not establish signing, IT approval or
independent build reproducibility.

## Validation status

| Scope | Observed result |
| --- | --- |
| Source and native builds | **220 Python tests in 18 suites passed**, no configured skips; C++ JSON check and three strict-warning native builds passed. [Source receipt](evidence/tester-feedback-0.16.1-source-validation-2026-10-09.json). |
| Exact archive/source audit | Passed for the three archives above, separately from execution. |
| Seven completed Windows regressions | **81 passed per path**: batch 11, curated 11, readiness 5, references 10, results 9, scroll 3, workspace 32. Ordinary and space-containing installations use the exact frozen Starter. |
| Existing patch/updater gate | **19 passed per path** in final validator `f9e71201`, repeated on unchanged archives after earlier passing rechecks. Repeats do not add unique coverage. |
| New tester-feedback native/temporal gate | **13 passed per path** at final validator `f9e71201`, completing all configured scenarios. Together with 81 regressions and 19 patch checks, this is **113 unique checks per path**. Four partial attempts remain retained below. |
| Regression screenshot review | All **112 capture files** reviewed (56 per path), at original resolution or through recorded exact-byte equivalence. No blocking layout defect within these captured 96-DPI viewports. [Ordinary](evidence/tester-feedback-0.16.1-regression-visual-ordinary-2026-10-09.json), [spaces](evidence/tester-feedback-0.16.1-regression-visual-spaces-2026-10-09.json). |
| Patch screenshot review | 82 files reviewed: 43 unique images and 39 exact-byte duplicates. Settled controls fit; bounded immediate Tools-resize frames retain old geometry until the first later sample (~0.30–0.32 s). [Ordinary](evidence/tester-feedback-0.16.1-patch-visual-ordinary-2026-10-09.json), [spaces](evidence/tester-feedback-0.16.1-patch-visual-spaces-2026-10-09.json). |
| Final feedback screenshot/temporal review | All **192 capture files** verified: 51 unique BMP hashes, 52 direct views and 140 exact-hash reuses. No unexpected layout defect within the captured viewports. [Ordinary](evidence/tester-feedback-0.16.1-feedback-visual-ordinary-2026-10-09.json), [spaces](evidence/tester-feedback-0.16.1-feedback-visual-spaces-2026-10-09.json). Finite temporal observations do not establish zero flicker. |
| Draft delivery | Implementation and recorded validation complete; ready for unpublished review with focused, sanitized receipts and original-report hashes. |

Final validator is `f9e7120196ddd284d33c0e8221b78fbf4529058f`,
[successful recheck run 37999874335](https://github.com/comparativechrono/workbench/actions/runs/37999874335).
Its **23 portable gate tests** (eight patch, 15 feedback) passed separately from
the 220 application-source tests. Production/packaging correspondence was
checked before the validator-only workflow reused the frozen archives. The
[native receipt](evidence/tester-feedback-0.16.1-native-validation-2026-10-09.json)
links focused final results, original-report SHA-256 values and the
[ordinary](https://github.com/comparativechrono/workbench/actions/runs/37999874335/artifacts/11648054427)
and [spaced-path](https://github.com/comparativechrono/workbench/actions/runs/37999874335/artifacts/11648519094)
Windows evidence artifacts. The
[independent validation summary](evidence/tester-feedback-0.16.1-independent-validation-2026-10-09.json)
additionally records gate results/skips, exact 277-file correspondence, focused
scientific assertions, queue completion, per-group temporal counts and timing
gaps, and the retrieved final-validator CI log hash. Detailed runner/input records
are excluded from the repository evidence.

The complete feedback gate exercises Samples without a workflow; native row,
cell and column editing through Save as and CSV/TSV reload; discarded drafts and
duplicate-ID rejection; explicit Starter example mapping; and Queue then Start.
The scientific assertions record **202 proper-pair alignments** and the known
**starter:1351 G>A homozygous SNP**, with sample, CWL and output provenance.
Forty-one temporal series per path contain **1,510 ordinary** and **1,306 spaced**
frames, with no sampled black block or unexpected stable difference. These are
finite observations, not proof of zero flicker. Final static feedback visual
review separately matched every capture hash and dimension to the native report
and verified lossless PNG pixel correspondence. The 192 capture files represent
51 unique BMP hashes: 52 direct original-resolution views and 140 exact-hash
reuses cover all files. No unexpected layout defect was observed within those
captured viewports.

Patch captures come from validator `91bb99e1` and run 37997995825 on the frozen
application. The immediate Tools-resize frames can clip right/bottom content at
old geometry; later recorded frames are settled, and workflow resize samples are
stable. This bounded resize observation is separate from the Run/category
flashing requirement and does not establish zero flicker.

## Retained attempts

The [attempt record](evidence/tester-feedback-0.16.1-attempts-2026-10-09.json)
retains exact original report hashes, partial results and failure explanations.
The [original-report SHA-256 manifest](evidence/tester-feedback-0.16.1-raw-index-2026-10-09.json)
identifies source reports and their artifact locations; it does not contain or
link full raw JSON blobs committed to Git. Focused, sanitized receipts preserve
reviewed assertions, counts, identities and limitations. Access to original raw
fields requires the corresponding Actions artifact. Binary screenshots are not
committed.
Each attempt uses application source `73778e00461e2b83c07b9ea97df2b9c5d4b6317d`.

| Attempt | Validator and run | Outcome per Windows path |
| --- | --- | --- |
| Initial | `73778e00461e2b83c07b9ea97df2b9c5d4b6317d`, [37997370988](https://github.com/comparativechrono/workbench/actions/runs/37997370988) | Seven regressions passed 81 checks. Patch stopped before its first check because an obsolete assertion expected 87 core files rather than the audited 90. Feedback passed five checks, then its case-sensitive Methods assertion rejected the selected operation's text. |
| Recheck 1 | `91bb99e1aa22acfafa626f813cf15d475ba7e7e9`, [37997995825](https://github.com/comparativechrono/workbench/actions/runs/37997995825) | Patch passed 19. Feedback passed seven, then the inherited wait rejected the expected Remove sample row confirmation. Cleanup timed out and masked the primary failure label; both remain in the traceback. |
| Recheck 2 | `516618fea10936229b1f8ee4cc4bdaf8dd12ad9e`, [37998730356](https://github.com/comparativechrono/workbench/actions/runs/37998730356) | Patch passed 19. Feedback passed seven; expected Remove row worked, then the validator queried a disappearing dialog caption with WM_GETTEXT (`0xd`). The next validator snapshots only top-level captions; child text checks remain strict. |
| Recheck 3 | `1b4f8311467014c128d6e72716ceedfc3fea9ec3`, [37999214954](https://github.com/comparativechrono/workbench/actions/runs/37999214954) | Patch passed 19 per path. Ordinary feedback passed seven, then the Samples reopening click transition was not yet unobscured. Spaced feedback passed 11, including CSV/TSV roundtrip, explicit mapping and queued known-answer science (202 proper-pair alignments; starter:1351 G>A homozygous SNP), then cleanup timed out. The complete gate remains unpassed. |
| Final recheck | `f9e7120196ddd284d33c0e8221b78fbf4529058f`, [37999874335](https://github.com/comparativechrono/workbench/actions/runs/37999874335) | **19 patch and 13 feedback checks passed per path**, after bounded pointer-readiness and actual queue-completion/main-idle observations before clean close. Application archives are unchanged. |

The initial feedback attempt sampled 18 temporal series per path: **1,066
ordinary** and **997 spaced-path** frames, with no sampled black block or
unexpected stable-state difference. These are bounded, partial observations
before the Methods failure, not a completed feedback review. Later repeated
samples likewise do not turn incomplete gates into passes.

## Evidence delivery boundary

Automatic approval review rejected uploads of unfiltered raw reports containing
opaque session/cache or review tokens, detailed Windows runner paths/logs/tool and
run metadata, and input identifiers. Those rejected blobs were not referenced in
a commit. Delivery therefore uses focused, sanitized receipts, original-report
SHA-256 values and GitHub artifact links. Opaque tokens and detailed runner/input
records are excluded; no upload retry or bypass is part of delivery.

Raw originals remain in the local validation workspace and original Actions
artifacts. The artifacts are scheduled to expire on **2026-11-08**. The original
report hashes identify exact evidence but cannot recover its content after
expiry. Repository receipts retain the reviewed scientific and validation
conclusions and their explicit scope; they do not promise permanent access to
all raw records, logs or frame samples.

## Remaining limits

Representative-PC, high-DPI/transitions, multiple-monitor, physical-trackpad and
managed-machine acceptance remain outstanding. The previous layout evidence was
limited to its hosted 96-DPI sizes; source review identified overlap below 908
logical client pixels for busy Cancel/Results and below 902 for the footer.
This revision was observed at workspace sizes 960×680 and 1024×728 and a
940×680 Samples window, at **96 DPI**. Broader display acceptance is not
established; earlier source geometry limits are not expanded by these tests.

Finite temporal sampling does not establish zero flicker or exclude shorter
unsampled transients. Synthetic examples establish their stated known answers,
not biological replication, realistic capacity or clinical fitness.
Executable signing still needs a controlled identity; institutional deployment
requires actual IT approval. Scientific Linux CWL and SDK/build recovery remain
later sets. Benchmarking is handled separately.
