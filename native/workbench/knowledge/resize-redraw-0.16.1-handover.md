# Tools resize correction for unpublished 0.16.1

Updated **2026-10-10**, following the owner's request: “Okay. Let's fix that.”
The correction is implemented. A bounded concurrent-resize comparison observed
mixed layouts in the old package and none in the corrected package, confirmed by
screenshot review. The new application's recorded checks pass. The separate
strict single-transition negative control remains unreproduced, so the workflow
is not green and the original lag's exact duration is not established.

## Source and implementation

Work continues in [draft PR #15](https://github.com/comparativechrono/workbench/pull/15)
on `fix/native-ui-0.16.1`, from starting head
`93c0a6b1189781fb8df960b025a512ed73461240`. The base remains
`feature/deployment-acceptance` at `f74d90229be6a78d6ad0c0076c54c04bb7e7cae2`
and unmerged draft PR #14. New application/build source is frozen at
`51077179a6e92020a7e9b992fa0cbe2b5a6c3e1e`. The version remains unpublished
**0.16.1**; this does not replace any published archive.

Previously, changing a control's bounds could draw that control while child
fields and later controls still showed their previous layout. The resize path
now positions all levels without painting or copying their old pixels, then
repaints the completed window. Normal mode changes and scrolling keep their
existing repaint behavior. Minimize avoids laying out an invisible zero-size
client, preserving normal dimensions and panel scroll positions until restore.

The change preserves the Run/category redraw corrections, separate Methods,
Run preflight, native Samples editing, reference management and workflows.
Pack/runtime bytes, saved pins and scientific known answers remain unchanged.
There are no new QC thresholds or runtime/memory predictions.

## Exact archives and downloads

[Build run 38041029923](https://github.com/comparativechrono/workbench/actions/runs/38041029923)
created these frozen archives once. Later validator changes do not rebuild them.
The [independent audit](evidence/resize-redraw-0.16.1-archive-audit-2026-10-10.json)
binds each archive to committed source and independently downloaded bytes.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-0.16.1-starter-windows.zip` | 17,879,852 | `7fd59d5b021867991506e98ef94c5b239245030fb9da55d77accf8d8e2d43682` |
| `native-workbench-0.16.1-source.zip` | 48,380,545 | `92daf78ad2bfc69d221c7274c69d7918e963dfe6e41405ee36ddf768c8f2e387` |
| `native-workbench-0.16.1-update-from-0.16.0.zip` | 13,042,517 | `35bbd786043561ea40a1a12f941da8f370f26fc9df63cd2904dbee16a18bbda5` |

Downloads: [Starter](https://github.com/comparativechrono/workbench/actions/runs/38041029923/artifacts/11665417695),
[core updater](https://github.com/comparativechrono/workbench/actions/runs/38041029923/artifacts/11665288657),
[combined candidate/source](https://github.com/comparativechrono/workbench/actions/runs/38041029923/artifacts/11665532524),
[source part 1](https://github.com/comparativechrono/workbench/actions/runs/38041029923/artifacts/11665532542)
and [source part 2](https://github.com/comparativechrono/workbench/actions/runs/38041029923/artifacts/11665587526).
These require GitHub access and expire **2026-11-09**. They are temporary Actions
artifacts, not release assets. The combined wrapper was not independently
downloaded; five bounded transfer wrappers and ordered source-part reassembly
were independently verified, including hashes and ZIP integrity.

The audit matches **844 committed source files**, 34 packaged Python modules,
six example files, 90 core files and all 277 Starter files. All 186 published
pack files and 39 private-runtime files, pack pins, production trust and setup
selection match published 0.16.0. Nine updater operations reconstruct the exact
new Starter core. Only `NativeWorkbench.exe` and `SOURCE-AVAILABILITY.json`
differ from the previous 73778 tester-feedback candidate's core. This is archive
correspondence, not signing or independent build-reproducibility evidence.

## Completed checks and retained attempts

The [source receipt](evidence/resize-redraw-0.16.1-source-validation-2026-10-10.json)
records **235 checks in 18 suites**, zero configured skips, the C++ JSON check
and three strict native builds. The total includes validator tests. The later
validator-only recheck passed 30 focused portable tests (15 patch, 15 feedback),
and the final diagnostic validator passed 31 (16 patch, 15 feedback). These
overlapping tests are not added to the 235 as unique application coverage.

**117 distinct native checks passed per installation path**, across the same
frozen application archives: 81 regression checks (11 batch, five readiness,
11 curated, 32 workspace, 10 reference-management, nine results and three scroll),
23 patch/resize checks and 13 tester-feedback checks. Ordinary paths and paths
containing spaces are both covered. This count combines completed scopes across
runs; it is not a claim that any complete workflow run passed. Repeated gates
and resize observations add no unique coverage.

- The [original attempt](evidence/resize-redraw-0.16.1-attempt1-2026-10-10.json)
  at application/gate source `51077179a6e92020a7e9b992fa0cbe2b5a6c3e1e`
  passed the 81 regressions and 13 feedback checks in each path, plus all four
  candidate resize groups. The full patch gate then failed in the validator's
  Results focus driver: a second `Keyboard` instance rebound a ctypes structure
  signature. The old-package comparison stopped at a setup pointer-hit guard
  before sampling. Neither failure is relabelled a successful complete gate.
- The [frozen recheck run 38041764557](https://github.com/comparativechrono/workbench/actions/runs/38041764557)
  at validator `6a4f2c37a98706b478af994e099e3a24c01ba0d7` passed all
  **23 patch and 13 feedback checks per path** on unchanged application archives.
  The old-package ordinary-path negative control completed six transitions and
  88 frames: five immediate pre-wait frames were non-target, but no post-wait
  source-layout or other non-target frames were observed. Its strict requirement
  to reproduce a post-wait defect was not met, so the workflow remains failed.
  This unreproduced negative control is a limit on the fix claim, not evidence
  that the candidate failed its own resize checks.
- [Final run 38042425723](https://github.com/comparativechrono/workbench/actions/runs/38042425723)
  at validator `20514d31650f71d4ab99dd9450a747823a995667` repeated all
  23 patch and 13 feedback passes per path on identical archives. The unchanged
  strict negative control again did not reproduce a post-wait defect; the run
  remains failed on that requirement. Its added concurrent-resize observation
  is reported below without changing the strict verdict or adding duplicate
  checks to the 117-per-path total.
  Its standard resize observations contain 697 frames across 48 transitions:
  all 649 post-wait frames matched target, while 21 of 48 immediate frames were
  non-target. The repeated feedback gate sampled 2,610 frames with no recorded
  black block or unexpected stable change. These are final-run counts; the
  earlier recheck's 24 immediate non-target and 2,969 feedback frames remain
  separate observations, not values for this run.

## Resize observations and evidence limit

Candidate tests cover Tools and Workflow modes, fresh installations and actual
0.16.0 upgrades, in both path layouts. Every sampled candidate frame after
`DwmFlush` matched the target layout. This Windows compositor wait is a timing
aid, not a proof that every visible display frame was captured. Pre-wait images
can retain the previous layout or show newly exposed black bands. Those images
must remain in the record; this is not a zero-flicker claim.

The [first visual review](evidence/resize-redraw-0.16.1-attempt1-visual-review-2026-10-10.json)
and [recheck visual review](evidence/resize-redraw-0.16.1-recheck-visual-review-2026-10-10.json)
retain the distinction between pre-wait transitions and settled target frames.
The latter verified 194 patch captures through 69 unique original-resolution
views and 125 exact-hash duplicate reuses. Settled Tools/Workflow, empty/populated
Results, setup and updater screens showed no blocking control clipping or
overlap. It retains 24 immediate transitional captures rather than calling every
frame clean.
The observed display scope is the hosted 96-DPI desktop at 960×680 and 1024×728;
a requested 1280×900 window was clamped to the available desktop. The old
negative control also reached the target after the wait. Successful new-package
samples alone therefore do not establish that the original visible lag has
been eliminated.

The additional concurrent-resize diagnostic used the old and corrected exact
packages on fresh ordinary-path installations, with three bursts of 12 resizes
each. It sampled **46 old-package frames**, of which **14** matched neither
complete endpoint layout (five, five and four by burst). It sampled **64
corrected-package frames**, all matching a complete endpoint. Independent review
confirmed old frames with duplicated General settings panes/text, shifted
headings/fields/footer buttons and black strips; some of those captures began
after the final resize call returned in each burst. Retained corrected frames
show complete endpoint layouts.

This is direct bounded evidence for the paint-ordering correction preventing the
observed mixed layouts during that resize sequence. Both diagnostic reports mark
observation completion, not `nativeGUIValidated`; they do not replace the strict
single-transition gate or prove that every display frame is correct. The runs
have different worker durations and sample counts, so they are not a performance
comparison. The previously reported roughly 0.3-second settling interval remains
unquantified more precisely. The [observation receipt](evidence/resize-redraw-0.16.1-observation-2026-10-10.json)
binds both packages, all 72 resize-call intervals and 110 capture intervals; the
[observation visual review](evidence/resize-redraw-0.16.1-observation-visual-review-2026-10-10.json)
records the inspected images.

The [previous tester-feedback handover](tester-feedback-0.16.1-handover.md) and
all its receipts remain unchanged. Its application source is
`73778e00461e2b83c07b9ea97df2b9c5d4b6317d`; its Starter SHA-256 is
`1291f93b5ece3c4da34eb2f2e29fccc83b6d87ec5fb73abf28bfd9cc8f155b75`
(17,879,604 bytes), from build run 37997370988. Earlier immediate Tools captures
showed the previous layout despite correct native bounds; the image was correct
by the first later sample at about 0.30–0.32 seconds. That interval was not an
exact measurement of the defect's duration, and the earlier 220 source/113 native
passes do not apply to the new application bytes.

## Delivery and remaining work

Keep focused sanitized receipts, exact source/archive identities and original
report hashes in the repository. Exclude opaque session/review tokens and
unnecessary runner/input metadata. Original hashes preserve identity, not access
to raw reports after Actions artifacts expire.

Published **0.16.0**, `main` at
`9ac6f906e3acd88e743ed87c76cbf99c9087636d`, and published assets remain unchanged.
No merge or release is part of this follow-up. Representative-PC, high-DPI,
multiple-monitor, physical-trackpad and managed-machine acceptance remain
outstanding. Signing/IT approval, scientific Linux CWL, SDK/build recovery and
the separately managed benchmarking programme are outside this correction.
