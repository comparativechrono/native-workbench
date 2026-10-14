# Native interface development

**New development, 2026-10-07:** the [expandable tool library](expandable-tool-library.md)
replaces the dropdown/flat list below with native category headings in the next
0.11.0 candidate. Its validation status is separate from the historical native
interface results recorded on this page; published 0.10.1 remains unchanged.

**Status recorded: 2026-10-06.** The Galaxy-inspired interface is published in
application **0.8.0**, a development prerelease. Work started from
`7c6f2437842788daf9918ac2194ef859b153092c` on `ui/galaxy-native-workspace`;
[PR #1](https://github.com/comparativechrono/workbench/pull/1) merged at `2086175`.
The user accepted the latest tested candidate and authorized publication.
The exact accepted bytes were promoted without a rebuild to
[app-v0.8.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.8.0).
All nine public assets were independently downloaded and verified. The
[0.8.0 release handover](native-ui-0.8.0-release-handover.md) records acceptance,
archive identities and publication status. Earlier pending-acceptance statements
below describe their original checkpoints and are superseded by this decision.
Testers accepted the three-pane layout, then reported workflow input duplication,
difficult chaining, missing navigation/delete controls, text corruption while
scrolling and an error on the first opening of Manage tools. The feedback
revision passed its native gate, then a user installation report exposed an
additional defect with deeply nested Windows result paths. The pipeline fix is
source `0d3282046d7aa05dc822315c9a237c8ac534cd7a`, which passed exact-package
validation in [run 37449356224](https://github.com/comparativechrono/workbench/actions/runs/37449356224).
See the [long-path record](evidence/native-workflow-0.8.0-long-path-2026-10-06.json).
The user confirmed that this pipeline fix worked, then reported that text still
flashes while scrolling. The current repaint follow-up at
`b3928ca6a29d22b5f010a303658c2e19c24324da` passed exact-package automated gates in
[run 37453380541](https://github.com/comparativechrono/workbench/actions/runs/37453380541).
The visual flashing was not reproduced by CI on either old or new bytes.
Subsequent acceptance is user-reported; it is not a new CI observation or a
claim about additional display configurations.

The prior feedback source `0d2a993fca95a5837a69aa05c63aa5e806c553af` passed
**32 workspace checks and 8 References/update checks per Windows path** in
[run 37441781509](https://github.com/comparativechrono/workbench/actions/runs/37441781509),
with zero failures or skips. Those ordinary/space-containing path checks did
not establish behavior beyond the legacy Windows path limit. Their original
successful scope is retained below; it does not validate the current fix.

The 2026-10-05 candidate at `c82c559d02a0b70e79afe67da93ace9e344f1ef3`
and its successful automated Windows gate remain historical evidence below.
Layout acceptance is not acceptance of the corrected workflow behavior.
The published 0.7.0 release and its reference-validation evidence remain
unchanged. The 0.8.0 release promotes the latest accepted candidate only.

Download the [published 0.8.0 Windows starter](https://github.com/comparativechrono/workbench/releases/download/app-v0.8.0/native-workbench-0.8.0-starter-windows.zip),
extract it into a **separate folder** and launch `NativeWorkbench.exe`.
The [accepted candidate bundle](https://github.com/comparativechrono/workbench/actions/runs/37453380541/artifacts/11408021439)
remains historical build evidence and expires **5 November 2026**. The separate
[updater](https://github.com/comparativechrono/workbench/releases/download/app-v0.8.0/native-workbench-0.8.0-update-from-0.6.0.zip)
requires 0.6.0; no 0.7.0-to-0.8.0 updater is supplied or validated.

| Accepted build/release item | Bytes | SHA-256 |
| --- | ---: | --- |
| Actions bundle | 75,599,305 | `234688eabc01315aceba6fd588094bc7bf2263670766d0bdc9d088f8f0c735c1` |
| `native-workbench-0.8.0-starter-windows.zip` | 16,948,940 | `df001a80033ff8e834045ec683c79672e0efdbd4880fb89fca8bf8c36d830fdc` |

All 68 core entries, 143 unchanged starter-pack entries, 15 packaged workspace
source copies and 14 relevant source files were verified against their
corresponding inventories/source. All three ZIP CRCs and build provenance were
checked. The packaged native executable SHA-256 is
`e32fc3e5acb42766641a822f01835430b3312b84c3174bd282fe2a50ef6f9d71`.

## Scroll-flashing follow-up, 2026-10-06

The earlier pipeline confirmation preceded the separate scrolling report; the
user has now accepted the latest scrolling candidate for publication. The previous scrolling
regression sampled static text and background after movement had settled, then
compared that image with a clean redraw. Its zero-difference result establishes
the tested final rendering, not what a person saw between frames while scrolling.
Preserve that result with its original scope.

The correction adds `WS_EX_COMPOSITED` to the form and General
settings panels, so child labels and controls are painted together. Scroll
layout retains the no-pixel-copy behavior but queues repainting rather than
forcing immediate descendant paints for every event. Boundary scrolls and
focus changes that do not change the scroll position avoid unnecessary layout.
Source review also found that small wheel deltas rounded to zero could enter
the `SB_LINEUP` command path and move upward. The correction accumulates the
fraction separately for each panel and does nothing until it yields movement.
The [exact-package scroll record](evidence/native-workflow-0.8.0-scroll-2026-10-06.json)
retains the new run, hashes and prior-package comparison. All five jobs passed:
82 CI source checks, 32 workspace plus 8 References/update checks in each native
path, the full five-stage long-path pipeline regression and the temporal scroll
gate. The latter observed standalone options, General settings and workflow
options at 96 DPI on Windows Server 2022 with private Python 3.13.16.

| Current-package scroll observation | Result |
| --- | --- |
| Desktop frames | 320 per panel; 960 total |
| Unexpected static-text/background frames | 0 |
| Requested/observed endpoint transitions | 300 / 300 |
| Precision-wheel cases | 18 passed |
| Observed sampling rate | 27.16–31.80 frames/second |

The gate samples the displayed desktop without asking the app to repaint during
observation. Edit/button regions are masked; this is a finite static-text and
background observation. The previous package also had zero unexpected frames
across the same 960 samples. Therefore the **reported visual flashing was not
reproduced in CI**, and these results do not prove its absence on the tester's
display or between sampled frames. The user's subsequent acceptance supersedes
the pending manual-review status while leaving these automated limits unchanged.

The prior-package comparison did reproduce a separate precision-wheel defect:
six negative-one-unit cases, routed through panels and child edits, remained at
offset zero instead of reaching the expected 48 pixels. All 18 current-package
precision cases passed. A detected movement failure must not be described as
reproduction of the visual flashing.

The [prior long-path bundle](https://github.com/comparativechrono/workbench/actions/runs/37449356224/artifacts/11404414503)
and its SHA-256 `71a84d2c6f7f293bf7f57c1fa3221fc942fce57bca61c8ed3344d593c31c262c`
remain historical evidence. Published 0.7.0 and all historical package/evidence
bytes remain unchanged. Version 0.8.0 is now published from the accepted bytes;
the [public-download record](evidence/native-ui-0.8.0-public-downloads-2026-10-06.json)
and [release validation](evidence/native-ui-0.8.0-release-validation-2026-10-06.json)
bind publication to those identities.

## Nested Windows result paths, 2026-10-06

A supplied installation report passed all seven application/integrity checks,
but the starter pipeline stopped after the first alignment. The native runner
had successfully produced and hashed a 69,441-byte SAM with 202 records; Python
orchestration then reported that output missing. The recorded paths agreed:
the containing folder was 255 characters and the output path was 269. This
localized the failure to ordinary Python filesystem access beyond Windows'
legacy path boundary, rather than an absent alignment or wrong output identity.
The report did not capture the user's registry setting, and no such setting is
inferred as an observed fact. Only sanitized lengths, outcomes and hashes are
retained in the evidence; private user paths and uploaded data are excluded.

The fix reuses explicit extended-path I/O at engine filesystem boundaries:
existence/stat checks, hashing, derived-input preflight, FASTA/BED/VCF readers,
report generation and run-record writes. Plans, provenance, path comparisons
and tool arguments retain ordinary normalized identities. Manifest verification,
frozen-plan checks, output containment and symlink/junction guards remain in
place. Installation-check output readers use the same boundary. This addresses
deep pipeline results without requiring a user to change a machine policy.

The updated CI source gate passed **82 checks, zero failures or skips**, including
seven new path regressions. Those seven use real local files and a synthetic
backend under an **emulated** ordinary-path limit to check chained outputs,
hashing/report consumption and retained trust/path protections. A further 22
selected core/pack-check contracts passed locally; they are separate from the
82-check gate and native Windows execution.

The exact packaged regression then disabled the CI runner's long-path policy
before launching fresh private Python processes. The previous package
reproduced the missing-output error on a **268-character SAM path**, with a
254-character result folder: ordinary existence checks failed while extended
I/O found the valid file. The fixed package passed the complete **Check
installation** flow: all **7 core checks** and all **5 scientific pipeline
stages** succeeded. All **20 output files** were independently rehashed;
**19 paths exceeded 260 characters**, with a maximum of **279**. The result
included actual BAM and the expected homozygous SNP at **starter:1351 G>A,
GT 1/1**. The two negative-control and three fixed-package regression assertions
passed with no skips. The runner's original policy value was restored afterward.
This modifies only the disposable validation runner, not a user's configuration.

| Exact-package evidence | Record |
| --- | --- |
| Previous package installation result | [Prior result](evidence/native-workflow-0.8.0-long-path-prior-2026-10-06.json) |
| Expected old-package failure and path comparison | [Negative control](evidence/native-workflow-0.8.0-long-path-negative-control-2026-10-06.json) |
| Corrected full installation/scientific result | [Fixed result](evidence/native-workflow-0.8.0-long-path-fixed-2026-10-06.json) |
| Policy setup and restoration | [Runner policy](evidence/native-workflow-0.8.0-long-path-policy-2026-10-06.json) |

The same corrected package also passed the existing native UI and References
gates on **Windows Server 2022/private Python 3.13.16 at 96 DPI**:

| Installation path | Workspace checks | References/update checks | Failures/skips |
| --- | ---: | ---: | --- |
| Ordinary | [32](evidence/native-workflow-0.8.0-long-path-ordinary-ui-2026-10-06.json) | [8](evidence/native-workflow-0.8.0-long-path-ordinary-references-2026-10-06.json) | 0 / 0 |
| Contains spaces | [32](evidence/native-workflow-0.8.0-long-path-spaces-ui-2026-10-06.json) | [8](evidence/native-workflow-0.8.0-long-path-spaces-references-2026-10-06.json) | 0 / 0 |

Each workspace total is 8 packaged-host, 2 scientific and 22 GUI checks. All 56
workspace/References capture hashes were verified. The new long-path regression
is a host/CLI scientific execution check, not a separate GUI interaction claim.

The user subsequently confirmed that the pipeline fix worked. This is separate
manual feedback for the reported failure, not a rerun of the automated checks.
This is not a universal long-path claim for every optional executable, arbitrary
deep installation/reference-library location or Windows shell dialog. Physical
trackpad pinch, higher-DPI/multiple-monitor behavior and manual tester acceptance
also retain their separate limits.

## User-approved direction

Testers requested familiar Galaxy-style tool discovery and workflow editing.
The user approved a three-pane native interface, with general settings in the
right pane during standalone use and selected-step options there during
workflow editing. This replaces the earlier arrangement of a small graph,
step list and editor in the central area. It preserves the accepted searchable
tool library and does not revive the rejected wheel selectors.

Official design references are the Galaxy Training Network's
[interface introduction](https://training.galaxyproject.org/training-material/topics/introduction/tutorials/galaxy-intro-short/tutorial.html)
and [workflow editor guide](https://training.galaxyproject.org/training-material/topics/galaxy-interface/tutorials/workflow-editor/tutorial.html).
Galaxy is copyrighted open-source software; its
[current licence](https://github.com/galaxyproject/galaxy/blob/dev/LICENSE.txt)
describes the applicable terms. Workbench uses its own branding, controls and
Win32/GDI+ drawing. No Galaxy code, icons or screenshots are incorporated into
the application. The left panel is the installed tool library: references to a
tool shed do not imply a newly implemented Galaxy-compatible marketplace.

## Layout and operation

| Area | Tools mode | Workflow mode |
| --- | --- | --- |
| Header | Tools and Workflow buttons; Native Workbench identity | The same mode buttons |
| Left pane | Searchable installed tool library, category filter, Manage tools | The same library; drag a tool to the canvas or use Add to workflow |
| Central pane | Selected tool's description, explicit file inputs and run parameters | Workflow canvas with explicit input cards and tool cards |
| Right pane | General settings: analysis name, input browsing folder, output folder, References | Selected tool's connections/options or selected input's files; General settings remains accessible |
| Run action | Run tool | Run workflow |
| Save action | Save settings | Save workflow |

Selecting a tool in Tools mode opens that tool's standalone form. Switching
tools does not append hidden workflow steps. In Workflow mode, selecting a
canvas tool opens its options in the right pane. Adding a workflow tool leaves
its ports unconnected and creates no file-input cards. **Add input** creates a
named reference, single FASTQ, paired FASTQ or other installed semantic input.
Select that input card to bind its files once, then reuse its output in multiple
tools. Paired reads remain one atomic input with explicit read-1/read-2 fields.
Downloaded references can be assigned before the input is connected to a tool.

Dragging an input card's output or a tool output to a tool input requests an
explicit graph connection. Compatible targets depend on declared
semantic types, required state, capacity and cycle rules. The named-source
picker remains an alternative to pointer dragging. A workflow tool's inspector
shows its connections without repeating the file editors owned by input cards.
Standalone Tools mode retains its direct file fields.

Drag empty canvas to pan. The minus/plus buttons zoom between 25% and 200%; the
percentage button resets to 100%. Ctrl+wheel zooms around the pointer, and
Windows pan/zoom gesture messages are handled. Physical trackpad pinch behavior
has not been verified on hardware. Hovering a card header exposes its delete
cross; Delete also removes the selected card. Removal disconnects consumers
and supports Undo. Canvas positions, pan and zoom are presentation state, not
saved scientific graph parameters.

The input folder is a browsing starting point for native file pickers. Selecting
it does not bind every file in that folder or infer paired reads. Tool inputs
remain individually selected named fields, owned by an input card in Workflow
mode or the standalone form in Tools mode. The output folder is the parent for
new run directories, which retain methods, files, checksums and logs. References
opens the existing native finder/local library; download and binding remain
explicit operations. Results access remains available without introducing a
Galaxy dataset-history pane or dataset-history semantics.

The app remains native Win32 with a private Python host over anonymous pipes.
It requires no browser, HTTP listener, Docker, WSL or system Python. Tool
metadata continues to generate fields and determine scientific compatibility;
the layout adds no per-tool execution implementations.

## Session and save contracts

`DesktopHost` owns one workflow model and an independent cached `DesktopModel`
for each opened standalone tool. Mode changes preserve current parameters,
file bindings, selection and undo state **within the running process**. They do
not create automatic saved analyses or promise recovery of unsaved edits after
closing the application. Opening the same tool again preserves its edits;
reopening a deliberately cleared tool starts a new single-tool model.

Canonical persistence remains the existing separate contracts:

- Saved tool settings are presets, with an exact pack pin and reusable
  parameters; file/sample bindings are excluded.
- Saved workflows are connected, typed pipeline graphs. They retain exact
  pack pins and exclude local file bindings. A saved workflow still requires
  at least two connected tools.
- Loading a pipeline or the example selects Workflow mode. Loading a preset
  applies it to the active selected tool after compatibility validation.
- Reference targets, review and run preparation use the active model.
  Switching modes/tools is blocked during active runs and pack/reference
  operations. Frozen run evidence remains independent of later edits.
- A catalogue refresh updates all editing sessions while preserving their
  existing pack-version and manifest pins.

Explicitly injected host models remain the active workflow session for existing
embedders/tests and retain their older default source-allocation behavior.
Production workflow sessions set `auto_sources=False`; standalone sessions
retain automatic file slots. Normal native startup begins with an empty Tools
session. Existing saved graph/source IDs, connections and pack pins are not
rewritten. Explicit paired input schemas retain canonical read roles across
save/load and receivers with different manifest input IDs.

## Native host and canvas boundary

| Private RPC | Request | Response |
| --- | --- | --- |
| `workspace/mode` | `{"mode":"tool"}` or `{"mode":"workflow"}` | Active snapshot including `mode` |
| `workspace/tool` | `{"toolId":"bam/reference-index"}` | Preserved standalone tool snapshot, `mode: "tool"` |
| `workspace/connection-targets` | `{"ref":"step-1::sorted"}` | `{"ref":"step-1::sorted","targets":[{"nodeId":"step-2","portId":"alignment"}]}` |

The `model` RPC uses the existing `{"action":...,"payload":...}` envelope:

| Action | Payload | Effect |
| --- | --- | --- |
| `add_input` | `{"inputType":"reference","label":"Genome"}` | Create and select an unconnected reusable source |
| `select` | `{"nodeId":"input-1"}` | Select an input card and its file inspector |
| `apply_fields` | `{"sourceId":"input-1","files":{"input-1":{"reference":"C:/data/genome.fa"}}}` | Bind that source's declared field; actual field IDs come from the snapshot |
| `remove_source` | `{"sourceId":"input-1"}` | Remove the source and disconnect its consumers, with Undo |

Snapshot `inputTypes` derives IDs, labels and file schemas from installed port
metadata, including accepted semantic alternatives such as SAM and BAM. A
source inspector has `kind: "source"`, `sourceId`, `fields` and `consumers`.
A tool inspector has `kind: "tool"`; its connection choices remain available,
while workflow `ports[].sources` and `sources` omit duplicate file editors.

Connection previews are read-only and concern one dragged source at a time.
They traverse the producer's ancestors to exclude cyclic targets, then apply
the same semantic/state rules used by connection validation. A single-source
port can be replaced; multiple-source ports must have room for the added
source. Existing connections are not duplicated. The actual `connect` action
remains authoritative and atomically rejects invalid edges.

Do not add every port's full source-choice list to every node snapshot. That
would make large graphs quadratic in response size and violate the private
host's 8 MiB frame limit. Ordinary node inputs stay compact; the selected
inspector retains its source picker choices. Preview targets have only
`nodeId` and `portId`. Canvas positions are presentation state and do not change
dependency order, pack pins or scientific graph semantics.

## Feedback revision, 2026-10-06

The initial scrolling correction moves child controls together without copying old pixels,
then repaints the panel and all children. Manage tools starts with correctly
typed empty arrays before its asynchronous response arrives; the first opening
must not parse an absent value as an array.

Library labels now identify the scientific program as well as the operation.
Starter minimap2 produces SAM; **SAMtools — Coordinate sort to BAM (SAM/BAM
input)** already supplies the direct SAM-to-sorted-BAM path. **SAMtools — FASTA
lookup index (.fai)** names the standalone lookup-index export accurately.
Starter alignment and variant operations prepare their own required indexes,
so a separate faidx card is not a prerequisite. Canonical pack/workflow IDs,
commands and published pack bytes remain unchanged. See the
[starter tool audit](starter-tool-semantics.md) for exact commands, limitations
and the distinction between FASTA lookup and aligner-specific indexes.

The revised source gate ran these seven suites on Linux with Python 3.12.14:

| Suite | Passed |
| --- | ---: |
| `test_workflow_inputs.py` | 11 |
| `test_catalog_presentation.py` | 7 |
| `test_desktop_modes.py` | 11 |
| `test_desktop_host.py` | 12 |
| `test_reference_service.py` | 10 |
| `test_split_release.py` | 8 |
| `test_core_update.py` | 16 |

Total: **75 passed, zero failures or skips**. The new tests cover unconnected
workflow tools, standalone bindings, shared references before connection,
paired roles and file validation across save/load, removal/undo, atomic invalid
edits, SAM/BAM connection differences and unchanged canonical pack metadata.
These source checks do not execute Windows controls or scientific binaries.
The first revised native gate in
[run 37440843001](https://github.com/comparativechrono/workbench/actions/runs/37440843001)
failed before GUI launch because it compared a SAM floating-point tag as raw
text (`0.0100` versus equivalent `0.01`). Both paths passed eight packaged-host
checks and eight References/update checks. The next attempt uses typed float
comparison and also checks accumulated small Ctrl+wheel deltas; its complete
native results passed as described below. The
[feedback record](evidence/native-workflow-0.8.0-feedback-2026-10-06.json)
retains both attempt identities and outcomes.

The exact revised package passed
[run 37441781509](https://github.com/comparativechrono/workbench/actions/runs/37441781509)
on **Windows Server 2022 with bundled Python 3.13.16 at 96 DPI**:

| Installation path | Packaged host | Native scientific checks | Native GUI | References/update | Failures/skips |
| --- | ---: | ---: | ---: | ---: | --- |
| [Ordinary](evidence/native-workflow-0.8.0-final-ordinary-ui-2026-10-06.json) | 8 | 2 | 22 | [8](evidence/native-workflow-0.8.0-final-ordinary-references-2026-10-06.json) | 0 / 0 |
| [Contains spaces](evidence/native-workflow-0.8.0-final-spaces-ui-2026-10-06.json) | 8 | 2 | 22 | [8](evidence/native-workflow-0.8.0-final-spaces-references-2026-10-06.json) | 0 / 0 |

The GUI checks used actual native pointer interactions for input-to-tool and
tool-to-tool connections, shared input selection and its single file form,
canvas panning in both directions, 83% zoom hit-testing, zoom reset, hover-cross
deletion/Undo for both tools and sources, and the first Manage tools opening
and reopening. Dialog interactions preserved unsaved form edits. A native
message regression accumulated 120 Ctrl+wheel deltas of one unit and reached
116% zoom; this checks high-resolution event handling, not physical trackpad
hardware.

The scroll regression compared **197,198 static-text/background pixels** at the
same scrolled offset before and after a clean redraw, with **zero differing
pixels in each path**. These were settled captures; no intermediate scroll
frames were sampled. All 36 workspace GUI capture hashes were verified.
These assertions concern the tested native controls and scroll positions at
96 DPI; they do not establish every display scaling or accessibility setting.

The scientific checks executed starter minimap2 paired alignment directly into
SAMtools coordinate sorting. They verified binary BAM output with **202 mapped,
properly paired records**, coordinate order, preserved mandatory SAM fields
and typed optional tags. No separate reference-index operation was needed.
Float values were compared according to their declared type, not cosmetic
decimal formatting. The eight References/update checks also passed in each
path, retaining download/cancellation, integrity, offline/provenance and
**0.6.0-to-0.8.0** data-preservation coverage. No 0.7.0 updater claim follows.

Physical trackpad pinch, high-DPI/multi-monitor movement, native folder-picker
interaction and manual tester reacceptance of the corrected workflow remain
unvalidated. The accepted layout, source tests and automated native result are
separate evidence. Version 0.8.0 remains a review candidate rather than a
published release.

The prior feedback
[bundle](https://github.com/comparativechrono/workbench/actions/runs/37441781509/artifacts/11401422780)
expires 5 November 2026 and does not contain the later nested-output-path fix.
Its verified 16,948,268-byte starter SHA-256 remains
`de099e5feef437c788352c31c0e743c7e8f22aa08bfe2364e59b715ec3501806`.

## Historical verification checkpoint, 2026-10-05

These source checks were performed for the previous candidate on **Linux
x86-64 with Python 3.12.14**, against the modified working tree:

| Command | Result |
| --- | --- |
| `python3 workspace/tests/test_desktop_modes.py` | 11 passed, 0 failures, 0 skips |
| `python3 workspace/tests/test_desktop_host.py` | 12 passed, 0 failures, 0 skips |
| `python3 workspace/tests/test_reference_service.py` | 10 passed, 0 failures, 0 skips |
| `python3 tests/test_split_release.py` | 8 passed, 0 failures, 0 skips |
| `python3 tests/test_core_update.py` | 16 passed, 0 failures, 0 skips |

Total: **57 passed, 0 failures, 0 skips**. The
[development record](evidence/native-ui-0.8.0-development-2026-10-05.json)
retains this checkpoint and candidate-specific native attempts.

The new suite checks independent session edits/undo, strict requests, active
reference binding/review/run selection, busy-state exclusion, pipeline/preset
loading, catalogue refresh with unchanged pins, and connection type/state/cycle
and capacity rules. A synthetic 512-node graph remains below the 8 MiB snapshot
limit; its 511-target preview remains below 64 KiB. These fixtures do not execute
scientific tools or native Windows controls.

The exact final candidate from 2026-10-05 passed native Windows
[run 37376078599](https://github.com/comparativechrono/workbench/actions/runs/37376078599)
on **Windows Server 2022 with bundled Python 3.13.16**, at the observed **96 DPI**.
Each ordinary and space-containing installation passed **18 workspace checks**
(6 packaged-host checks and 12 GUI checks) plus **8 References/update checks**,
with zero failures or skips.

| Installation path | Workspace report | References/update report |
| --- | --- | --- |
| Ordinary | [18 passed](evidence/native-ui-0.8.0-final-ordinary-ui-2026-10-05.json) | [8 passed](evidence/native-ui-0.8.0-final-ordinary-references-2026-10-05.json) |
| Contains spaces | [18 passed](evidence/native-ui-0.8.0-final-spaces-ui-2026-10-05.json) | [8 passed](evidence/native-ui-0.8.0-final-spaces-references-2026-10-05.json) |

The workspace gate exercised the actual packaged executable: standalone tool
selection, distinct panes, two tool-list-to-canvas drags, an output-to-input
connection, right-pane selection/options, General settings, mode-specific
guidance, retained standalone inputs/browsing folder and workflow edits, and
pane separation at actual window sizes of 1044×788 and 1044×740 on the runner's
1024×768 display. Requested larger sizes were constrained by that desktop;
these checks do not establish coverage at the application's absolute minimum
height or on a larger monitor. Pointer clicks and drags used native
`SendInput`. One additional regression queued `WM_LBUTTONDBLCLK`/`WM_LBUTTONUP`
to the real ListView to check activation of an unselected refreshed row; that
notification case is distinguished from the physical pointer assertions.

References checks covered all five live products, cancellation, receipt/file
integrity, offline native SAMtools analysis, frozen provenance, native
References download/binding controls, and **0.6.0-to-0.8.0** migration with an
idempotent repeat preserving user data. This does not establish an upgrade from
0.7.0. All three downloaded candidate archive hashes, the 68 core entries and
143 starter entries were verified. All 36 final capture hashes were verified;
the corrected Tools/minimum and connected-workflow captures were visually
reviewed.

Earlier failures and successful intermediate runs remain in the
[development record](evidence/native-ui-0.8.0-development-2026-10-05.json).
They exposed gate control detection and real tool-list activation issues.
Visual review of an intermediate passing candidate also found stale workflow
guidance in Tools mode; the final candidate fixes it and adds a native
regression. Historical results retain their exact source/artifact identities.

The historical [candidate bundle](https://github.com/comparativechrono/workbench/actions/runs/37376078599/artifacts/11371647135)
contains the older starter, matching source and 0.6.0 updater; it expires
**4 November 2026** and does not include the 2026-10-06 feedback fixes.

| Historical verified item | SHA-256 |
| --- | --- |
| Actions bundle, 75,395,876 bytes | `61bd2deca854b43596b82be95cebb4d72179df6cd34c2abe097361df8777de7e` |
| `native-workbench-0.8.0-starter-windows.zip` | `5e59dee9efd38f2ee10516292294e4bd711b2c0a61e35b2bbbb49965f27383e4` |

The maintained gate is
[`scripts/check_workspace_ui_windows.py`](../scripts/check_workspace_ui_windows.py).
At that checkpoint, manual tester acceptance, broader accessibility evaluation,
high-DPI and multi-monitor movement, and native folder-picker interaction were
outside the automated acceptance. The later layout acceptance and workflow
findings above do not retroactively change its test scope. Do not count unrun
scenarios as passed. A future release
must retain its own exact artifact identity and publication verification; this
checkpoint validates a review candidate and leaves published 0.7.0 unchanged.
