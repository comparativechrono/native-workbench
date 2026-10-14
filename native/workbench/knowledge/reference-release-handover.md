# Reference discovery release handover

Updated **2026-10-05**. **Native Workbench 0.7.0** is published as a development
prerelease at [app-v0.7.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.7.0).
The exact-final native [run 37320844819](https://github.com/comparativechrono/workbench/actions/runs/37320844819)
passed all eight checks in both paths, with zero failures or skips, and final
public downloads are independently verified. Reference discovery/download is
complete within the documented validation scope. A later concurrency audit and
expanded exact-final run also passed; see the reconciliation section below.
The dated intermediate checkpoints preserve their original scope and failures;
the completed release and audit supersede their pending status.

## Recovered repository and release state

The repository is [comparativechrono/workbench](https://github.com/comparativechrono/workbench).
The resumed checkout was clean `main` at
`5338853ba3b69438fc36c1b9dcd3ad89d6bbcde4`. Work continues on
`release/reference-0.7.0-completion`.

| Record | Recovered identity/status |
| --- | --- |
| Published application baseline | [app-v0.6.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.6.0); its dated evidence and the 32-pack inventory remain unchanged |
| Existing candidate | [app-v0.7.0-rc1](https://github.com/comparativechrono/workbench/releases/tag/app-v0.7.0-rc1), commit `8ad25c71ec13d2c06a670b59a2cc13ca84a50ac9` |
| Candidate starter SHA-256 | `8314887d482184afac1b196f4a19d023d5abf2584dba6cedcb63a2283ce5e705` |
| Candidate 0.6.0-to-0.7.0 updater SHA-256 | `49b50acbb8c89a706fb99963f63f1fc87c008dcc162b82c86f44976739116496` |
| Final release lookup | [Exact app-v0.7.0 API lookup](https://api.github.com/repos/comparativechrono/workbench/releases/tags/app-v0.7.0) returned 404 during the resume audit |
| Last historical Windows run | [37295599791](https://github.com/comparativechrono/workbench/actions/runs/37295599791), workflow source `9543ae5030ee0ec42e404d251b67b6b1e1af4de6`, failed GUI gate |
| Existing source corrections | `b9d0ee7f16f675d0c42d77d7a093530ca052d09b` changes layout and tab automation; `5338853ba3b69438fc36c1b9dcd3ad89d6bbcde4` clarifies validation scope |

The candidate predates those corrections. No workflow run for either corrected
commit was found at the resume audit. Preserve rc1 bytes and its failed reports;
the next candidate needs its own immutable release identity.

## Missing interface finding recovered

The retained rc1 artifact's `gui-events.jsonl` records the References details
control ending at screen y=616, while the destination field, Choose folder and
Download selected controls begin at y=601. The **15-pixel overlap** is a measured
native layout defect. The [retained diagnosis](evidence/reference-resume-ui-diagnosis-2026-10-05.json)
contains the selected control bounds, source-file hash and originating artifact
identity (artifact 11337734019 from run 37295599791).

That same historical run then timed out on `SendMessageTimeoutW` while sending
`WM_KEYDOWN`/right-arrow to the native tab control (`winerror=1460`). This is an
observed automation failure; it alone does not prove the same failure occurs
for a person clicking the tab. The [original diagnostic report](evidence/reference-candidate-rc1-gui-diagnostic-2026-10-05.json)
retains its failure, traceback and exact candidate hashes.

Existing commit `b9d0ee7` reserves the details-panel height and gaps before sizing
the online lists. Its gate waits for the local library, posts tab keys to the UI
thread, and checks independently observed control geometry at normal/minimum
sizes and on the Downloaded tab. `5338853` states the measured scope. These are
source corrections awaiting a new packaged native run, not completed acceptance.

## What historical Windows evidence actually establishes

Run 37295599791 completed seven backend/native CLI checks in each ordinary and
space-containing path before the GUI failure:

1. Live release-pinned yeast discovery found genome, GTF, cDNA, ncRNA and protein.
2. Cancellation after transferred bytes removed its partial download and
   published no ready reference.
3. All five downloads were expanded atomically and their compressed/expanded
   hashes matched independently pinned identities and receipts.
4. A separate socket-denied host reopened the local library, bound a compatible
   input and generated reference-aware methods.
5. Offline native SAMtools indexed all 17 yeast contigs while preserving the
   reference, frozen identity and completed methods.
6. Application and starter-pack integrity checks passed after reference use.
7. The native updater CLI upgraded the exact 0.6.0 starter to the 0.7.0 candidate,
   then accepted an idempotent repeat and reopened preserved data offline.

The truncated phrase “0.6.0 update” therefore referred to **upgrading from 0.6.0
to 0.7.0**. The updater ran with its private interpreter. Its report records 187
existing preserved files, no changed files, and only the expected
`user-data/session.lock` addition. Installed optional packs and exact saved pins,
reference files/library and results were retained. The updater's native folder
picker was **not** exercised by that CLI check.

These are recovered prior results tied to rc1 bytes. The overall Windows gate
failed, so they must not be counted as full application or GUI acceptance.

## Checks performed during this resume

The [fresh source report](evidence/reference-resume-source-checks-2026-10-05.json)
and [unchanged test log](evidence/reference-resume-source-checks-2026-10-05.txt)
record Linux/Python 3.12.14 checks at source
`5338853ba3b69438fc36c1b9dcd3ad89d6bbcde4`:

| Suite | Passed |
| --- | ---: |
| Reference provider | 17 |
| Reference manager | 25 |
| Reference provenance | 5 |
| Reference service | 10 |
| Desktop host | 12 |
| Split packaging | 8 |
| Core updater | 16 |
| **Total** | **93** |

There were zero failures, errors or skips in the 93 source tests. These are deterministic source
contracts, with no fresh live-network, native Windows GUI or scientific
execution claim. The report also compared all 15 runtime hashes in the
[historical 139-test report](evidence/reference-source-contracts-2026-10-05.json)
against the resumed source; all match. The 139 tests remain historical evidence,
not an additional 139 tests rerun in this session.

The [fresh build record](evidence/reference-resume-build-2026-10-05.json)
records verified baseline/compiler downloads, all 65 baseline core files, and
three successful strict native cross-builds. The current geometry regression
gate also rejects the recovered rc1 bounds with the expected 15-pixel overlap.
These are build/static and regression-sensitivity checks, not new Windows
execution.

## Interim rc2 result and additional correction, 2026-10-05

The corrected layout was packaged and published as
[app-v0.7.0-rc2](https://github.com/comparativechrono/workbench/releases/tag/app-v0.7.0-rc2)
from `19444e0f2a9c9981d87f033bd3b2b17f79878add`. All five candidate assets were
independently downloaded and rehashed against their frozen local bytes and
GitHub digests. The starter SHA-256 is
`67828ca3f19bda33129e115b902f841cf64d3d66c2ba623f1be8081fc8e7b651`;
the updater SHA-256 is
`3926c280c86be0fa2b8353c3c20045d576d1d9f2c6497aec06804714a9b4d08d`.
Publication and byte verification did not close the native gate.

The new native run stopped because the References library did not populate.
Diagnostic [run 37317100708](https://github.com/comparativechrono/workbench/actions/runs/37317100708)
used the unchanged rc2 application and gate source
`456d1dbc17254ec9e6ccf0408525a9c6c4955357`. In **both ordinary and space-containing
paths**, it recorded a native modal titled “Native Workbench” with the exact
message **“Expected a JSON array”**, while References displayed “Loading local
references...” and zero local rows. Captures and control text were inspected;
the [retained diagnosis](evidence/reference-rc2-startup-diagnosis-2026-10-05.json)
binds those observations to the run, artifact and source-file hashes. The seven
backend/updater checks passed in each path, with no skips, but the overall gate
failed. The observed normal-size details-to-destination gap was now 12 pixels;
that one corrected measurement does not substitute for the uncompleted GUI gate.

Source review traced startup to an initially empty reference-state object:
the native selection helper requested a species array before any library reply.
It also identified a separate reset path: a new search sets `discovery` to null,
but the renderer attempted to iterate its files as an array. The reset failure
is a source finding at this checkpoint, not an observed Windows interaction.

The narrow desktop correction initializes collection fields as empty arrays,
returns early when no species row is selected, handles cleared discovery, and
guards absent local-file/download selections. Its strict desktop cross-build
passed, producing SHA-256
`75df84ac7ae7e4d96384c1596a53f6f5417570b2993a53917d8f852b949004af`.
The native gate is being extended to exercise live GUI search, file discovery
and a second search that clears the previous discovery. These source/gate edits
await an exact rebuilt **rc3** native run. Rc2 remains an immutable failed
candidate, and final 0.7.0 release acceptance remains pending.

## Initial release-gate checklist (historical)

1. Build and package the corrected desktop, bridge, updater and matching source
   companion from a recorded source commit, preserving the exact 0.6.0 baseline
   and starter-pack bytes. Record compiler/input/output hashes.
2. Publish a new diagnostic candidate without replacing rc1. Dispatch
   `native-reference-check.yml` against its exact starter and updater hashes.
3. Inspect both ordinary and space-containing Windows reports and captures.
   Require download/cancellation/integrity, typed offline reuse/provenance,
   migration preservation and the corrected References layout/tab gate to pass.
   Preserve failures and fix only the implicated behavior if another issue is
   found. Do not treat unavailable native checks as passes.
4. Freeze/publish the final `app-v0.7.0` assets through the established workflow,
   independently download/re-hash them, run the exact-final native gate, and
   attach separate final evidence. Update the current-state and inventory only
   to the completion level those checks establish.

The gate's limits remain explicit: automated Win32 interactions and captured
geometry do not establish broad human usability, all high-DPI/multi-monitor
setups, Unicode/long paths, institutional proxies or human-genome performance.
Scope stays on reference discovery/download; the signed pack catalogue is a
separate project item.

## Corrected rc3 native candidate acceptance

Candidate `app-v0.7.0-rc3` at source `57d635370a1cd34dd1549aff95a2feba7faeeb74`
passed native run [37318450359](https://github.com/comparativechrono/workbench/actions/runs/37318450359)
in both ordinary and space-containing paths: eight checks and no skips. The
[retained candidate evidence](evidence/reference-rc3-candidate-2026-10-05.json)
records exact archive/report/artifact/capture hashes. Root and the evidence
reviewer inspected the captures: startup error resolved, five products shown,
search/discover/search reset successful, normal/minimum details gap 12 pixels,
Downloaded tab populated and clean shutdown.

All five public rc3 assets were independently downloaded and matched the frozen
local bytes. The final staging archives are byte-identical copies of those
validated candidate archives. A gate-only extension then added a real native
tool, clicked **Use for input**, and verified the exact downloaded genome path
in the native inspector. [Run 37319693097](https://github.com/comparativechrono/workbench/actions/runs/37319693097)
passed all eight checks in both paths with no skips, using the unchanged rc3
application and gate commit `6c266a58818886c6f4f5287006f20fafc5aadd68`.
The [extended candidate evidence](evidence/reference-rc3-native-input-2026-10-05.json)
retains the exact binding and all twelve reviewed capture hashes. No application
bytes changed for the gate extension.

## Final publication and exact-final validation

The final [app-v0.7.0 release](https://github.com/comparativechrono/workbench/releases/tag/app-v0.7.0)
was published at 2026-10-05T13:54:17Z as a development prerelease. Its five initial
assets are byte-identical to rc3. Each final URL was independently downloaded,
rehashed and matched against the frozen file and GitHub digest; see the
[public-download record](evidence/reference-0.7.0-public-downloads-2026-10-05.json)
and [build record](evidence/reference-0.7.0-build-2026-10-05.json).

| Final application asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-0.7.0-starter-windows.zip` | 16,916,149 | `3d5b79924e5edc69efb7d4934696f6568377b63c312a666cc37e05b8707cf1ba` |
| `native-workbench-0.7.0-update-from-0.6.0.zip` | 12,830,009 | `9c86f8c7cbe7acb8c31cdb7472db815143e7cc63be8fda0113642baee17f1469` |
| `native-workbench-0.7.0-source.zip` | 46,002,233 | `4b4993d710430c735fff69f2655781711abcda601833de1e481411913b8c164e` |

The release tag points to **`6c266a58818886c6f4f5287006f20fafc5aadd68`**; the
immutable archives were built from **`57d635370a1cd34dd1549aff95a2feba7faeeb74`**.
The intervening changes affect the gate and evidence/handover only; application
runtime, desktop and packaging sources are identical. The source companion's
creation-time pending statements remain historical and are superseded only by
separate later evidence, never by changing the published archive.

Exact-final [run 37320844819](https://github.com/comparativechrono/workbench/actions/runs/37320844819)
independently exercised the final release URLs at gate commit `6c266a5`. Both
ordinary and space-containing paths passed **eight checks, zero failures and
zero skips**. All twelve captures were downloaded, hash-checked and visually
reviewed. The [final native report](evidence/reference-0.7.0-final-windows-2026-10-05.json)
records exact archive, report and evidence hashes, and distinguishes this final
run from the successful candidates.

The final native UI opened without the rc2 modal, discovered all five products,
cleared a prior discovery on a new search, populated five downloaded rows, used
the real **Use for input** button and displayed the exact genome path in the
native tool inspector. Normal/minimum details-to-destination spacing was 12
pixels; the application closed cleanly. The packaged host separately verified
all five compressed/expanded identities, cancellation, socket-denied offline
reuse and frozen provenance. Native SAMtools indexed all 17 yeast contigs.
The native updater CLI verified 68 target core files, preserved all 187 existing
pack/settings/reference/result files, repeated idempotently, and reopened the
updated host offline. Only the expected coordination lock was added.

There is no outstanding implementation or native reference-gate blocker. This
original run's scope excludes click-through GUI download/cancel, the updater folder picker,
whole-desktop/manual managed-PC acceptance, high-DPI/multi-monitor operation,
Unicode/long paths, institutional proxies and human-genome performance. The
network-denied private host was not an operating-system firewall test.

The release also publishes [RELEASE-VALIDATION.json](https://github.com/comparativechrono/workbench/releases/download/app-v0.7.0/RELEASE-VALIDATION.json),
[WINDOWS-EVIDENCE.zip](https://github.com/comparativechrono/workbench/releases/download/app-v0.7.0/WINDOWS-EVIDENCE.zip)
and [EVIDENCE-SHA256SUMS.txt](https://github.com/comparativechrono/workbench/releases/download/app-v0.7.0/EVIDENCE-SHA256SUMS.txt).
The [retained release report](evidence/reference-0.7.0-release-validation-2026-10-05.json)
closes the native release gate. The [final eight-asset verification](evidence/reference-0.7.0-final-assets-2026-10-05.json)
records independent downloads of the three supplements, rehashed retained
initial downloads, unchanged original asset IDs/current digests, and verified
supplemental checksum entries. All eight public assets match their frozen
bytes. No original archive or checksum file was replaced. There are no
outstanding release-publication or reference-feature blockers.

## Source stream and preserved independent work

This release follows `release/reference-0.7.0-completion` from the resumed
`main` baseline `5338853`. A concurrent independent branch
`finish-reference-release` independently identified the null-state issue in
`4eef03ddf2ad6b0426e054171c8aafe9e752e73e`. Its report recorded blocked publication
and unrun native validation for its own patch, and preserved this stream's rc2.
The branch subsequently reached
`5a5455647381bd93272326d0bd97eadbef92028d`: that documentation-only checkpoint at
13:41:42 UTC observed this stream's rc3 publication before the later final
validation and release. Its pending status is historical. The separate desktop
patch was **not merged or used** in the released application; the released fix
already covers those cases and adds absent-file/download-selection guards.

## Concurrent work reconciliation, 2026-10-05

The follow-up audit started with `main` at
`0993e856506150127d345d040d80f810c8cc10f7` and the independent branch at `5a54556`.
The [initial state record](evidence/reference-concurrency-initial-state-2026-10-05.json)
retains the branch identities, common ancestor, release assets and live workflow
records. No open pull request or active workflow was present at that checkpoint.
The independent [run 37316644535](https://github.com/comparativechrono/workbench/actions/runs/37316644535)
stopped at its existing-rc2 protection before building or publishing; its native
job was skipped. It did not overwrite the candidate or final assets.

All **eight public final assets were downloaded again** and compared with their
recorded bytes and current GitHub digests. The
[fresh artifact audit](evidence/reference-concurrency-assets-audit-2026-10-05.json)
passed 57 assertions, including source/core/updater inventories, source-to-tag
correspondence, checksum manifests and the retained final Windows evidence.
The original final report, archive identities and twelve capture hashes agree.
This is fresh byte/evidence verification; inspecting the old native report does
not count as rerunning Windows.

Only useful additional GUI coverage was ported from the independent stream.
Commit `ad5b59c06a03d3885bee5416fb47b4835ae9927f` on
`audit/reference-concurrency-20261005` extends the existing native gate with
actual file checkboxes, typed destination, Download and Cancel interactions,
while retaining current diagnostics and input-binding checks. The independent
branch's obsolete rc2-specific publication workflow and stale release-status
documents were not merged. Both development histories remain available. No
application, pack, tag or published archive bytes changed.

The expanded exact-final [run 37339280407](https://github.com/comparativechrono/workbench/actions/runs/37339280407)
at gate commit `ad5b59c` passed **eight checks per path, zero failures and zero
skips** against the unchanged final starter and updater. The
[fresh native audit](evidence/reference-concurrency-windows-2026-10-05.json)
records 43 independent evidence checks and all twenty hash-verified, visually
reviewed captures. This is new Windows execution, separate from the earlier
release acceptance.

The native UI selected all five products with their actual checkboxes, typed a
destination containing spaces, downloaded through **Download selected**, and
verified that the five exact files were published under that destination. It
preserved existing reference files and bound both existing and newly downloaded
references through **Use for input**. A separate GUI attempt clicked **Cancel**
and verified no ready library entry or partial output was published. That GUI
case cancelled early; the backend case separately cancelled after at least
1 MiB transferred. The run repeated the existing live hash, offline reuse,
provenance, native SAMtools and 0.6.0-to-0.7.0 preservation checks.

The [reconciliation record](evidence/reference-concurrency-reconciliation-2026-10-05.json)
connects the branch decisions, fresh public downloads and expanded native
evidence. The original eight release assets and their reports remain unchanged;
supplemental audit evidence is separate. Application version remains **0.7.0**.
No concurrency-related implementation, validation or release blocker remains.
The remaining scope limits are folder-picker interactions, whole-desktop/manual
managed-PC acceptance, high-DPI/multi-monitor operation, Unicode/long paths,
institutional proxies and human-genome performance. Socket-denied host evidence
does not establish an operating-system firewall test.

The existing release now also supplies
[CONCURRENCY-AUDIT.json](https://github.com/comparativechrono/workbench/releases/download/app-v0.7.0/CONCURRENCY-AUDIT.json),
[CONCURRENCY-WINDOWS-EVIDENCE.zip](https://github.com/comparativechrono/workbench/releases/download/app-v0.7.0/CONCURRENCY-WINDOWS-EVIDENCE.zip)
and [CONCURRENCY-SHA256SUMS.txt](https://github.com/comparativechrono/workbench/releases/download/app-v0.7.0/CONCURRENCY-SHA256SUMS.txt).
The bundle retains both original new Windows artifact ZIPs, all twenty captures,
reports, logs, receipts, methods, the exact gate and the independent audits.
All three supplemental public downloads match the frozen bytes and GitHub
digests, and the original eight asset identities remain unchanged; see the
[post-publication verification](evidence/reference-concurrency-public-assets-2026-10-05.json).
The release therefore has eleven explicit assets plus GitHub's generated source
links. The gate and reconciliation records are integrated on `main`; the
independent branch remains preserved at its audited commit.
