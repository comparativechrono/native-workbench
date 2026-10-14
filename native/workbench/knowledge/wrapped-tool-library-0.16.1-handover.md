# Wrapped native tool library, unpublished 0.16.1

## Status and scope, 2026-10-10

The wrapped library and overflow-scroll correction are implemented. The exact
candidate passed **124 distinct native checks per Windows path**. Final evidence
audit and screenshot review are complete; this is **ready for unpublished draft
review**. Previous application, driver and infrastructure failures remain recorded.
Work continues on
`fix/native-ui-0.16.1`, starting at
`568f2a74a62c4befb7ffe9c9f26390fe5a8c1d72`. It continues
[draft PR #15](https://github.com/comparativechrono/workbench/pull/15), based on
`feature/deployment-acceptance` at
`f74d90229be6a78d6ad0c0076c54c04bb7e7cae2`. The application version remains
unpublished **0.16.1**. Published **0.16.0** and its assets remain unchanged;
no merge or release is included.

Testers reported that the centre pane obscures long tool labels and that the
hover popup needed to read them is annoying. The requested presentation is a
fully readable, wrapped tool name in **bold**, followed by the complete regular-
weight description. Text must fit the left pane's width; a row taller than the
viewport must be readable through ordinary scrolling. Reading a tool's label
must not require hovering over it. This is a native presentation
change inspired by the user's description of Galaxy, not an integration with
Galaxy or a change to scientific tool metadata.

The [library contract](expandable-tool-library.md) records the requirements.
Keep the native TreeView category hierarchy, keyboard navigation, selection,
search, compatible-output filtering and workflow dragging. Preserve standalone
forms, workflow pins and saved graphs, Methods, Samples editing, reference
management and the existing Run/category/resize corrections. Pack IDs,
versions, published bytes and scientific execution are outside this change.

## Implementation

Application and initial gate source is frozen at
`ff13db729a6215e9fe5dfa4a4efdb9c769880287`. The native library retains
TreeView control 104 inside native parent
viewport 430 and draws each tool's name using the bold font, followed by its
regular-weight description. Row height follows the measured wrapped text.
Wrapping uses the same font measurements as painting, splits oversized tokens
without breaking UTF-16 surrogate pairs, and keeps the text inside the library
column. The model supplies the complete canonical display fields; names use
font weight 700 and descriptions use weight 400. Full name and description
remain available as native item text.

The outer viewport owns pixel scrolling because the native TreeView's own
whole-item scrolling could not expose the suffix of a row taller than the
viewport. Its real child window is bounded to the viewport height plus the
largest row, rather than the complete catalogue height. The child is positioned
through native window geometry; item rectangles and pointer hit targets remain
actual screen coordinates. Current Windows checks cover complete tested
names/descriptions, font weights, absence of hover popups and a 2,048-character
fixture in both path layouts. The separate catalogue-overflow checks also passed.

The viewport now uses a registered application window class compatible with
the existing composited drawing. The preceding viewport build failed while
creating the native control before desktop interaction began. The registered-
class correction restored desktop startup. The later overflow defect was
diagnosed separately and corrected by retaining native coarse scrolling.

Reflow is cached by usable width and catalogue content; unchanged model polls
do not rebuild the rows. The viewport reserves scrollbar space before categories
expand, preserving the width and viewport anchor. Reflow retains the first
visible row and its within-row pixel offset. Native category and keyboard
behavior, standalone selection, search, compatible-output filtering and workflow
dragging remain connected to the same tool identities. The library disables its
tooltip behavior and uses system colours in Windows high-contrast mode.

The current implementation and relevant portable checks have passed independent
source review. Its exact build, archive/source audit and native checks passed;
final evidence audit and screenshot review are complete. This description is
not a claim of completed native accessibility, high-contrast or broader display
acceptance.

## Current validation

[Run 38075960020](https://github.com/comparativechrono/workbench/actions/runs/38075960020)
has built and tested source `ff13db729a6215e9fe5dfa4a4efdb9c769880287`.
The correction permanently enables native coarse scrolling and extends the
TreeView child by one DPI-adjusted native scrollbar width beyond the parent
clip. The visible scrollbar, wrap width and paint bounds belong to the parent
viewport. Native item geometry remains real, while the hidden native scrollbar
can no longer block first-visible-item movement.

The [current source receipt](evidence/wrapped-library-0.16.1-final-source-2026-10-10.json)
records **258 tests in 20 suites**, C++ JSON and three strict native builds passed.
The [archive audit](evidence/wrapped-library-0.16.1-native-scroll-archive-2026-10-10.json)
matched **864 Git source files**, 34 runtime modules, six examples, 90 core files
and 277 Starter files. Both audited baselines retain the same 39 runtime and
186 pack files. The updater's 55 inventory files and nine operations reconstruct
the exact new Starter core.

In the original full run, the spaced path passed all ten native gates, comprising **124 checks**. The
ordinary path passed nine full gates (**111 checks**) and one feedback check
before a foreground timeout immediately after the Samples-without-workflow
scenario. Review of the retained failure screenshot showed the GitHub hosted
runner console obscuring the app, with the app's caption still exposed. This is
an infrastructure obstruction; no new application or overflow-scroll failure
was established by that attempt.

A feedback-only frozen recheck of both paths passed on the unchanged
`ff13db7` archives: validator `7ea0ce6bf6821089c524c307f99efb0a1892d2a3`,
[run 38076722339](https://github.com/comparativechrono/workbench/actions/runs/38076722339).
Its 18 portable gate tests and independent review passed. The only focus recovery
is a real caption click after the blank Samples window closes at the setup
boundary; rendering and scrolling assertions are unchanged. Each path passed
all **13 feedback checks**, including overflow at both 960 and 1024 widths.
All three recheck jobs succeeded. No application bytes were rebuilt or modified
for this recheck.
The [native evidence audit](evidence/wrapped-library-0.16.1-native-scroll-native-2026-10-10.json)
retains this failed overall verdict and verifies the report/archive identities.
Together, the original run and frozen recheck establish **124 distinct native
checks per path** on the same archives: seven wrapped-library, 23 UI patch,
13 tester-feedback and 81 existing regression checks. Repeated checks add no
unique coverage. The separate 18 validator tests do not add to the 258 source
count. The [final acceptance index](evidence/wrapped-library-0.16.1-final-acceptance-2026-10-10.json)
binds the completed evidence audits, exact archives and both visual reviews.
The original full run remains failed; its partial ordinary outcome is retained
separately rather than relabelled as a pass.

Visual review covered **41 actual display image records**: 25 from the original
run and 16 from the frozen recheck. No additional layout defect was found in the
unobscured selected captures; fresh recheck images show populated overflow and
collapse endpoints in both paths. Still images and finite temporal samples do
not establish zero flashing. Both feedback rechecks required one exposed owned
caption click after closing the blank Samples modal; automatic foreground
restoration after modal close is not established.

## Previous package validation and diagnosis

The dedicated candidate workflow is
`.github/workflows/native-wrapped-library-candidate.yml`;
[run 38074534436](https://github.com/comparativechrono/workbench/actions/runs/38074534436)
completed with a **failed native verdict**. Its 258 source tests in 20 suites,
C++ JSON check, three strict native builds and independent archive/source audit
passed. The audit matched 862 Git source files, 34 runtime modules, six examples,
90 core files and 277 Starter files; 39 runtime and 186 pack files were unchanged
against both audited baselines.

Both paths passed eight complete native gates, comprising 104 checks. The focused
wrapped-library gate passed four checks in each path before encountering a
missing keyboard-focus precondition. The ordinary-path feedback gate passed
11 checks before exposing the real blank viewport during overflow scrolling.
The spaced-path feedback gate passed one check before a hosted runner console
obscured the app; that infrastructure failure is separate from the application
overflow failure. Those partial gate results did not establish acceptance of
that previous package.

Frozen validator `f037fb612097aeff7fd576960a25d17c376504ee` completed
[run 38075533050](https://github.com/comparativechrono/workbench/actions/runs/38075533050)
successfully against the unchanged `3bf08f0` archives. All seven focused wrapped-
library checks passed in both paths. The separate diagnostic completed with
`nativeGUIValidated=false`: `TVS_NOSCROLL` prevented the native first-visible-item
operation from moving the TreeView anchor, while clearing that flag allowed it
to move. This isolates the blank-overflow cause; it does not erase the earlier
overall native failures or supply acceptance for a production change.

The production correction at `ff13db7` keeps native coarse item scrolling enabled
and places its scrollbar outside the parent's clipping viewport. The parent
retains the visible pixel scrollbar and wrapping width. Its new build and complete
relevant native checks passed as recorded above.

Required focused observations include complete wrapped names/descriptions,
bold names and regular descriptions, absence of the library label popup, complete
text reachability at the supported narrower and wider window sizes, and retained category,
keyboard, search, selection and drag behavior. Source checks, existing native
regressions, archive/source correspondence and screenshot review must be
recorded separately with exact identities. Do not infer a new pass from a
previous candidate or count repeated gates as additional unique coverage.

The earlier resize candidate remains documented in the unchanged
[resize handover](resize-redraw-0.16.1-handover.md). Its strict single-transition
negative control was not reproduced and its workflow remains failed; the
bounded concurrent-resize comparison is separately scoped. The new library
candidate does not rerun or reclassify that historical negative control.
Historical resize workflows are manual-only, while the library workflow owns
validation of this new scope.

## Retained attempts and diagnosis

| Source or validator | Observation | Consequence |
| --- | --- | --- |
| Original application and gate `a2c35bf035281b3446dfab8c133fd34e8545ce78`, [run 38072008564](https://github.com/comparativechrono/workbench/actions/runs/38072008564) | 254 source tests in 20 suites, the C++ JSON check, three strict native builds and the independent archive/source audit passed. Seven native gates passed in each path; three stopped on assumptions in their drivers, including a required whole row within the viewport and exact name-only labels. | The original candidate was not accepted as complete; failures remain retained. |
| Frozen-package validator `5c5da273653d125156911cb7a27633e0924dce91` | The corrected focused gate checked complete text across scrolling and failed because native wheel input could not reveal a full wrapped line. | This exposed a real limitation of the original application, not just a test-driver mismatch. |
| Diagnostic validator `fa762eb70a946d6968683944fcf7c9fc92165acf` | Native TreeView scrolling stopped at whole-item boundaries and could not reach the suffix of the oversized row. The diagnostic completed; it did not mark the GUI validated. | A production viewport correction was required, with fresh package validation. |
| First viewport application and gate `aed0e2ac898fce412927a7bc997d57c164d60b3c`, [run 38074041970](https://github.com/comparativechrono/workbench/actions/runs/38074041970) | 258 source tests in 20 suites, three strict native builds, the C++ JSON check and archive/source audit passed. All ten native gates failed in each path because native control creation prevented desktop startup. Some non-desktop checks completed before that failure. | These archives are superseded. The production class-registration fix requires another exact build and complete native validation. |
| Registered-class application and gate `3bf08f0a8ae94f8842afc3fa07f4c20789f7ed3e`, [run 38074534436](https://github.com/comparativechrono/workbench/actions/runs/38074534436) | Source/build/audit passed; eight complete native gates passed per path. Wrapped checks stopped after four passes on a missing focus precondition. Feedback stopped after 11 ordinary-path passes on a real blank overflow viewport; the spaced path stopped after one pass when a runner console obscured the app. | Overall failed; preserve separate application, driver and infrastructure failures. The later diagnostic/recheck is separately recorded below. |
| Frozen validator `f037fb612097aeff7fd576960a25d17c376504ee`, [run 38075533050](https://github.com/comparativechrono/workbench/actions/runs/38075533050) | All seven focused checks passed in both paths on unchanged `3bf08f0` archives. The separate diagnostic showed `TVS_NOSCROLL` blocks native first-visible-item movement; clearing it moved the anchor. The diagnostic did not mark the GUI validated. | Recheck run succeeded within its narrower scope and prompted the later production correction; it did not establish acceptance of the unchanged failed package. |
| Final application and initial gate `ff13db729a6215e9fe5dfa4a4efdb9c769880287`, [run 38075960020](https://github.com/comparativechrono/workbench/actions/runs/38075960020) | Source/build/archive passed; spaced path passed all ten gates/124 checks. Ordinary passed nine gates/111 checks and one feedback check before a runner console obscured the app. | Full run failed on infrastructure obstruction; its original verdict remains unchanged. |
| Frozen feedback validator `7ea0ce6bf6821089c524c307f99efb0a1892d2a3`, [run 38076722339](https://github.com/comparativechrono/workbench/actions/runs/38076722339) | All 13 feedback checks passed in both paths on unchanged `ff13db7` archives; all three jobs succeeded. | Combined exact-package scope is 124 distinct checks/path. Repeats add no unique coverage; final audit and visual review passed within their recorded scope. |

The first viewport attempt's focused native receipt has SHA-256
`31b6d41c0083f079d864226c7cb7a99725c9c3f0cb8a3411239098d0118e6c8a`.
It records 51 partial checks per path, zero successful gates and unavailable
desktop interaction checks. Partial work is not counted as acceptance.

The original Starter SHA-256 is
`e5fc48276f92a4038aaeadcea5b28eefa70386f849ae35579b04f6e117e53085`
(17,886,478 bytes). Its source archive is
`64677205101d704957e6bbf9da66245256b5dca1ad606ec908f8f0fffec7df14`
(48,461,110 bytes), and updater is
`5db241c23ac5d63d70ebbed18980075a6900977ac8281384d8ca6c2df9e02e64`
(13,049,139 bytes). These identities belong to the superseded original
implementation, not the revised viewport candidate. Its audit matched 858 Git
source files, 34 runtime modules, six examples, 90 core files and 277 Starter
files; 39 runtime and 186 pack files stayed unchanged against both baselines.

## Evidence and delivery

The current `ff13db7` archives are independently verified below and completed
the recorded native scope. Final evidence audit and screenshot review are complete.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| Starter | 17,889,148 | `28f1362287991621dde030da54eb444846142c0243be6b9d86c4b4f1bf99dd47` |
| Matching source | 48,487,148 | `002fbc8401ab744a8172f3ae11d240c925ed7a8d1241bd5d94e0413675bb1b5d` |
| Update from 0.16.0 | 13,051,808 | `d0a20f0b8288c79dba695e9cc82e78a78e95244ebb267e959d99fb9e438e7aee` |

[Windows Starter download](https://github.com/comparativechrono/workbench/actions/runs/38075960020/artifacts/11678725746)
and [0.16.0 updater download](https://github.com/comparativechrono/workbench/actions/runs/38075960020/artifacts/11678319898)
are temporary Actions artifacts, retained until **2026-11-09**, and may require
GitHub sign-in. Extract the Starter artifact, then its inner archive into a
separate test folder and start `NativeWorkbench.exe`. Preserve the inner
archive's SHA-256 identity above. This is an unpublished review download.

The [evidence index](evidence/wrapped-library-0.16.1-historical-evidence-index-2026-10-10.json)
binds 14 preserved focused receipts for the earlier and current archive/native
attempts and diagnostics. It retains their failed results and narrower
diagnostic scopes. The [current class diagnostic](evidence/wrapped-library-0.16.1-native-scroll-class-diagnostic-2026-10-10.json)
is diagnostic evidence, not GUI acceptance.

Previous `3bf08f0` archives are identified below. They are superseded failed
review bytes, not the current `ff13db7` archives or a completed acceptance candidate.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| Starter | 17,889,122 | `48a1dbd91575c04c5b30bf59dd7d3a9c1383e22893c809bfad87f976f1c3caca` |
| Matching source | 48,479,470 | `a59c12e7150dd45371d9f85e65e412036521f11d510ca8b6bb5ced215087cde2` |
| Update from 0.16.0 | 13,051,787 | `b5fc660a87410696893c1edf780ae1faebb9c6d629a118de262c0200a3f12fdc` |

The previous `3bf08f0` source-validation receipt has SHA-256
`c6e9bf325d0e6d3c180e3717a53ace9a977f7a1eb645c3e6a18e9a98d13c91b8`.
The [recheck native audit](evidence/wrapped-library-0.16.1-feedback-recheck-native-2026-10-10.json)
and [recheck visual review](evidence/wrapped-library-0.16.1-feedback-recheck-visual-2026-10-10.json)
complete the recorded scope. Focused receipts and original-report hashes retain
identities and findings; raw runner paths, tokens and unnecessary metadata are
excluded. Binary reports/captures remain in expiring Actions artifacts.

Delivery remains an unpublished review candidate in draft PR #15.
Representative-PC, high-DPI, multiple-monitor, physical-trackpad and managed-
machine acceptance remain outstanding. Executable signing and institutional
approval, scientific Linux CWL, SDK/build recovery and separately managed
benchmarking are outside this presentation change.
