# Expandable native tool library

## Current presentation contract, 2026-10-10

The user requested full text in the native library after testers found the
hover label popup annoying and long labels obscured by the centre pane. Each
tool row must show the complete `displayName` in **bold**, followed by its
complete `displayDescription` in regular weight. Wrap both within the left
pane, size the row for its text, and reflow when the available width changes.
If a complete row is taller than the viewport, ordinary scrolling must reach
every line. Do not truncate the label or rely on a hover popup to reveal it.

Retain control 104 as the native TreeView, with its category hierarchy,
selection and accessible text. Category headings remain navigation items, and
the existing keyboard, search/filter, standalone-selection and workflow-drag
contracts below remain in force. This changes presentation without changing
published pack metadata, tool IDs, version pins or saved scientific workflows.

The current implementation at `ff13db729a6215e9fe5dfa4a4efdb9c769880287` measures and
draws the complete text with separate bold and regular fonts, allocates integral
TreeView row heights, and wraps oversized tokens without widening the column.
Full names and descriptions remain in native item text. Reflow caches usable
width, reserves scrollbar space and preserves the first visible row/offset;
unchanged catalogue polls leave the tree intact. Tooltips are disabled, and
high-contrast mode uses Windows system colours.

TreeView 104 is hosted inside native parent viewport 430. The outer viewport
scrolls pixels through tall rows; the child window is bounded to the viewport
height plus the largest row. Real native item rectangles and hit targets remain
aligned with the visible child. This replaces the original candidate's native
whole-item scrolling, which exact Windows checks showed could not reach the
suffix of an oversized row. The earlier `3bf08f0` checks reached all text in a
2,048-character fixture, but a separate overflow-scroll sequence produced a blank
viewport. That failed candidate prompted a frozen diagnostic, which established that
`TVS_NOSCROLL` prevents native first-visible-item movement and clearing it allows
the anchor to move. The current correction permanently leaves native coarse
scrolling enabled, extending the child by one DPI-adjusted native scrollbar
width beyond the parent's clip. The visible pixel scrollbar, text wrapping and
paint bounds use the parent viewport. Current exact-package source/build/archive
checks passed. The full `ff13db7` run and frozen feedback recheck `7ea0ce6`,
run 38076722339, together passed 124 distinct native checks per path on unchanged
archives, including complete wrapped text, font weights, no hover popup and
overflow scrolling. The original ordinary feedback interruption by a runner
console remains retained. Final evidence audit and 41-image review are complete;
the [final index](evidence/wrapped-library-0.16.1-final-acceptance-2026-10-10.json)
binds the passing hosted candidate scope and its limits.
The viewport uses a registered application window class compatible with
composited drawing, following a control-creation failure in the first viewport
candidate. Current exact startup succeeds; prior failures remain in the handover.

This implemented **0.16.1** follow-up is ready for unpublished draft review,
with source/archive/native/visual validation recorded, following retained failed candidates, in
[draft PR #15](https://github.com/comparativechrono/workbench/pull/15).
The [wrapped-library handover](wrapped-tool-library-0.16.1-handover.md) tracks
its implementation and new exact-package evidence. The historical 0.11.0
records below establish their original category implementation and publication,
not acceptance of these new wrapped rows.

## Released 0.11.0, 2026-10-08

[Version 0.11.0 is published](https://github.com/comparativechrono/workbench/releases/tag/app-v0.11.0) as a development
prerelease. It provides both a standalone Starter and a validated updater from
0.10.1. [PR #6](https://github.com/comparativechrono/workbench/pull/6) merged at
`a97af2d02a3a6f4623ceec0f06f69fa10d04cbb6`; the packaged application remains source
`acfa060c9a400d82509278b657ee37853c7922b0`.

Final native gates passed 7 library, 32 workspace, 8 References, 9 results,
3 scrolling panel groups and 13 upgrade checks per ordinary/space-containing
Windows path. Each upgrade preserved 204 existing files and verified 72 core
files. Live Ensembl downloads were rerun. Publication and an independent second
download verified all eleven public assets, their checksum manifests and ZIPs.

The [release summary](evidence/tool-library-0.11.0-release-summary.json),
[acceptance lock](evidence/tool-library-0.11.0-release-lock.json),
[publication record](evidence/tool-library-0.11.0-publication-2026-10-08.json) and
[public audit](evidence/tool-library-0.11.0-public-downloads-2026-10-08.json)
supersede the original pending acceptance/updater/publication statements below.
Those statements are retained as dated development history. See the
[0.11.0 notes](../docs/releases/0.11.0.md) for installation, update instructions,
failed helper attempts and validation limits.

## Original development handover, 2026-10-07

Development started **2026-10-07** from published 0.10.1 documentation baseline
`3a6e06f8fa05a8ceebed4584bd3433e07f08df52`, on
`feature/expandable-tool-library`. The tested development candidate is **0.11.0**.
Published 0.10.1 and its independent tool packs remain unchanged. This page is
a development handover with exact-package Windows evidence, not release or
tester acceptance. Implementation and validation are ready for tester review
in [PR #6](https://github.com/comparativechrono/workbench/pull/6).

## Requested interaction

Testers asked to replace the category dropdown and flat scrolling tool list
with visible category headings that expand to show their tools, as in Galaxy.
The official Galaxy Training Network
[interface tutorial](https://training.galaxyproject.org/training-material/topics/introduction/tutorials/galaxy-intro-short/tutorial.html)
(last modified 2026-09-23) and its
[interface image](https://training.galaxyproject.org/training-material/topics/introduction/images/galaxy_interface.png)
were inspected on 2026-10-07. The image itself shows a 2025 event banner; its
page's modification date is not evidence that the screenshot was captured in
2026. The design reference is search above browsable tool sections. Workbench
retains its own native controls, styling, branding and general-settings pane.
No Galaxy images, code or other assets are included in the application.

## Native implementation

`desktop/desktop_workspace.cpp` uses a Windows TreeView for tool library control
104. Category headings come from the installed catalogue and contain tool
children with the existing scientific display names. Categories are navigation
items, never executable tools or workflow inputs. Multiple categories may be
open at once. The category dropdown is removed, giving the library more space.

Single-click a heading to expand or collapse it. Native arrow-key navigation
and Enter/Space on a heading provide keyboard access. Selecting a tool opens
its standalone form in Tools mode. In Workflow mode, Add to workflow,
double-click and dragging a tool onto the canvas keep their existing meanings.
Expanding a heading must never add a step or replace the current form.

Search includes category names and existing tool search metadata. Search and
the existing compatible-output filter reveal matching tools inside their
categories. Clearing a filter restores the ordinary browsing expansion state.
Expansion, selection and viewport are session presentation state, separate from
saved scientific workflows and exact pack pins. Routine model refreshes should
not rebuild an unchanged tree or reset the user's browsing position. Installing
a pack supplies new tool/category metadata without an application rebuild.

## Validation and candidate status

The native implementation is complete and has passed a strict-warning
cross-build with the pinned LLVM-MinGW 20260922 UCRT compiler. The Linux source
gate passed **70 tests, no failures or skips** across desktop host (12), modes
(11), workflow inputs (11), pack service (6), setup manager (15), setup service
(7) and split packaging (8). Independent review found and corrected a Win32
expansion-notification issue: repeated toggles can omit notifications after
`TVIS_EXPANDEDONCE`, so the view now records actual expansion state directly.
These source/build findings are separate from the exact packaged Windows checks
below. No tester acceptance, public release or updater is claimed yet.

The candidate workflow is `.github/workflows/native-tool-library-candidate.yml`.
It builds a standalone Windows starter and matching source once, then tests
those exact bytes in ordinary and space-containing installation paths. Existing
workspace checks retain their real starter analysis and workflow interactions;
the focused library gate covers category navigation and filtering. Gate code
must read control 104 as a TreeView without changing unrelated ListView tests.

The frozen candidate was built from
`acfa060c9a400d82509278b657ee37853c7922b0` in
[run 37678010251](https://github.com/comparativechrono/workbench/actions/runs/37678010251).
Its existing workspace gate passed **32 checks in each Windows path**, including
actual tool dragging, compatible port connections and the native minimap2 to
SAMtools chain preserving all 202 expected alignment records. The first focused
library gate stopped at its initial collapsed-heading assertion in both paths;
the run as a whole therefore failed. Those results are retained, not counted as
focused-library passes.

The helper had treated any nonzero TreeView state as expanded. Final raw state
inspection returned `16` (`TVIS_BOLD`) for every initial category, with the
`32` (`TVIS_EXPANDED`) bit absent. The corrected helper masks that bit and
cross-checks it against independently retrieved item state. The verification-only
workflow downloads the same frozen starter, checks its SHA-256 and uses fresh
extractions. It does not rebuild the application.

[Run 37678715894](https://github.com/comparativechrono/workbench/actions/runs/37678715894),
using validator commit `3c2d5079355e6a056dcdbe39f25b7b7bead7d670`, passed
**all six focused category checks in each Windows path, with no skips**. These
cover collapsed headings, pointer and keyboard expansion, search and restoration,
standalone form selection, distinct workflow selection/add/double-click/drag
behavior, and an actual offline pack import supplying a new category. The last
case uses a synthetic pack, not a new published scientific tool.

Independent static audit passed **26 grouped checks**: all 72 core inventory
entries, 602 source files matched to the exact Git commit, all 143 Starter pack
files unchanged from published 0.10.1, and unchanged production profile/trust.
The [validation record](evidence/tool-library-0.11.0-validation-2026-10-07.json)
binds native reports, screenshots and archives. The
[static audit](evidence/tool-library-0.11.0-static-audit-2026-10-07.json) has its
own narrower scope. Creation-time pending status inside immutable build/source
companions is superseded by these records; do not rewrite those archives.

## Tester download and remaining release work

Download the
[standalone Windows candidate](https://github.com/comparativechrono/workbench/actions/runs/37678010251/artifacts/11507651323)
while signed into GitHub. Extract the artifact, then extract its inner
`native-workbench-0.11.0-starter-windows.zip` into a separate test folder and run
`NativeWorkbench.exe`. No older installation is required. The artifact is
retained until 2026-11-06; it is not a permanent release download.

The inner Starter archive is **17,044,022 bytes**, SHA-256
`e816e2f7cd5efe98af752fbf072fab00344ebaa2b6963795c2fbf4a86b5fa81c`.
The matching source archive is **46,875,983 bytes**, SHA-256
`a45ad640f0767bb56458b59ce50d263537e54ebb401a0e809f31a5453adb2f2b`.
Both are retained by the candidate workflow. Keep the original application
source and separate validator identities when recording later acceptance.

Before a release, obtain tester acceptance, build and validate an updater from
the supported published baseline, and follow the established exact-artifact
promotion/public-download workflow. Do not overlay this Starter onto an existing
installation or present the candidate as an already validated upgrade.

Live Full downloads, Ensembl downloads and upgrades are outside this layout
change's candidate gate. Prior passes for those features apply only to their
recorded artifacts. This UI work does not resolve the separate tester-machine
bridge/security investigation or establish managed-PC approval.
Native captures were at 96 DPI; finite hosted screenshots do not establish
physical-display flicker behavior, touchpad interaction or high-DPI acceptance.
