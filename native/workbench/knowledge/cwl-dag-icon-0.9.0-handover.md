# CWL, DAG and icon 0.9.0 release handover

**2026-10-06: accepted, published and independently public-download verified.** [Native Workbench 0.9.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.9.0)
is release **405123004**, a development prerelease published at
**2026-10-06T20:39:35Z**. [PR #2](https://github.com/comparativechrono/workbench/pull/2)
is merged at **`1ee61f1e2334bf0049aa4b9227da6f8663fc0c43`**, also the release tag
commit. The user stated, “Go ahead accept and release, the testers are happy
with it.” The [acceptance record](evidence/cwl-dag-icon-0.9.0-acceptance-2026-10-06.json)
keeps user acceptance separate from automated checks. Published 0.8.0 and all
tool-pack bytes remain unchanged. The [feature guide](cwl-results.md) describes
the export contract and external execution requirements.

## Exact candidate

Application source is **`beea34ab29f3e7cb9a7e79dbcfa11c89f40ee59d`**, packaged by
[run 37485987457](https://github.com/comparativechrono/workbench/actions/runs/37485987457).
The [candidate bundle](https://github.com/comparativechrono/workbench/actions/runs/37485987457/artifacts/11424165351)
is artifact **11424165351**, 75,880,943 bytes, SHA-256
`26f1f2070de5ffae4cdb219bd22579f22a3af943eab6e93048fa6e38ad041071`.
It was independently downloaded and hash-verified. Its six original members
were promoted byte-for-byte to the public release; the CI artifact remains the
original build evidence, distinct from publication.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-0.9.0-starter-windows.zip` | 17,002,821 | `c2661c144e073c4efdd190ffd186bacd9398b6413b81770d7a057c3947eecf02` |
| `native-workbench-0.9.0-source.zip` | 46,423,298 | `7bfc3802cad3b476300ae7075214e2c06ee320d987df66945ff0809cb3218824` |
| `native-workbench-0.9.0-update-from-0.6.0.zip` | 12,951,447 | `eed778882bed560e765c1f2c03d6473b2ea07f2b219e4bd81bff7297e67b177d` |

The [artifact audit](evidence/cwl-dag-icon-0.9.0-artifact-audit-2026-10-06.json)
verified ZIP CRCs, 497 source entries against the exact Git commit, 70 core
entries, 65 update entries and all 19 update blobs. All 143 starter-pack files
match the accepted 0.8.0 starter, and all 17 packaged Python modules match the
source companion. The native executable's nine icon frames match the ICO
regenerated from the exact SVG source. This resource inspection is separate
from native displayed-icon validation.

## Completed checks and retained failures

The [validation ledger](evidence/cwl-dag-icon-0.9.0-validation-2026-10-06.json)
binds the reports to the above archives. Initial run **37485987457 failed
overall**; it must not be described as a completed feature gate.

| Check | Recorded result |
| --- | --- |
| Linux source gate | 125 passed, zero failures/skips; stock `cwltool 3.3.20260925135507` validated and executed the controlled fixture. |
| Existing native workspace, each path | 32 passed. |
| References/update, each path | 9 passed, including nonempty reference-provenance CWL and 0.6.0-to-0.9.0 preservation. |
| Initial native feature gate, each path | 7 science/export/SVG checks passed; 1 GUI fixture check failed; zero skips. |
| Final focused native feature gate, each path | 9 passed, zero failures/skips; `nativeGUIValidated: true`. |
| Long-path native regression | 3 checks passed, zero failures/skips; full five-stage starter pipeline, all 20 output hashes checked with opt-in disabled and original policy restored. |

The ordinary and space-containing native cases use Windows Server 2022 and
private Python 3.13.16. Independently, six exact Windows-produced CWL documents
passed stock schema validation on Linux. Their original Windows paths were
unavailable there and produced location warnings; this is not execution of
those scientific workflows on Linux. Native replay of the embedded runner is
also distinct from invoking a Windows CWL engine.

The initial GUI fixture demanded a canvas width of 560 logical pixels, while
the hosted desktop supplied 457 at 96 DPI. It failed before the new connection
interactions. Validator commit `3352ef7` fitted the fixture to the actual viewport
without changing application bytes. Its focused
[run 37487450679](https://github.com/comparativechrono/workbench/actions/runs/37487450679)
then failed because it checked the wrong selected inspector; the retained
screenshot showed the connection. These are retained failed checks, not passes.

Validator **`a8c939a81ee6bdc0f3bb8f3682d4a415d768d9e8`** explicitly selects each
receiving card before inspecting its connection. Focused
[run 37488239616](https://github.com/comparativechrono/workbench/actions/runs/37488239616)
used the unchanged `beea34a` package and confirmed the intended connections and
native icons. Its normal-to-zoom capture interaction timed out, so the overall
GUI check still failed. Both normal captures were reviewed and showed clear
routes; that partial evidence did not close the full check.

Final validator **`bc972125814c1f24dca86391d0c5f240716a52f3`** passed focused
[run 37489208656](https://github.com/comparativechrono/workbench/actions/runs/37489208656)
against the same `beea34a` archives: **9 checks per path, zero failures/skips**,
both native GUI flags true. The final
[ordinary report](evidence/cwl-dag-icon-0.9.0-final-ordinary-native-results.json)
and [space-containing-path report](evidence/cwl-dag-icon-0.9.0-final-spaces-native-results.json)
retain the checks. All four normal (100%) and zoomed (83%) captures were reviewed
and showed clear cards, routes and arrowheads.

Geometry located the zoom button centre at `(582, 732)`, outside the hosted
work area of `1024 × 728`; that point hit `MSTaskListWClass`, the taskbar.
The final fixture therefore uses the native button's `BM_CLICK` command for
zoom capture only. This is not reported as a new physical-click pass. The
separate 32-check workspace gate already covers physical zoom-button clicks.
Real connection interactions and native icons remain checked in the focused
gate. No application bytes changed to repair these validator fixtures, and all
three earlier failed runs remain failed historical records.

## Updater from the published 0.8.0 baseline

The additional updater is built from the published 0.8.0 starter and the accepted
0.9.0 starter without changing accepted application or updater-engine bytes.
Its dedicated native gate is separate from the earlier 0.6.0 updater checks.

Two early native gate attempts failed before applying the update and remain
failed evidence. [Run 37526784016](https://github.com/comparativechrono/workbench/actions/runs/37526784016)
(source `a2312028f4bc6b1849c42a9c4acb8fb918d75310`) passed one check per path,
then the fixture incorrectly expected a provider display name in provenance
that uses the provider ID. The unchanged 0.8.0 reference analysis completed,
but this did not establish updater success. The retained
[ordinary report](evidence/cwl-dag-icon-0.9.0-updater-attempt-1-ordinary-2026-10-06.json)
and [spaces report](evidence/cwl-dag-icon-0.9.0-updater-attempt-1-spaces-2026-10-06.json)
record the failure.

[Run 37527241170](https://github.com/comparativechrono/workbench/actions/runs/37527241170)
(source `316f707`) also failed before the update: its saved-workflow fixture
omitted an explicit reference-input binding and was rejected with
`Reference genome needs 1 source(s).` Its
[ordinary report](evidence/cwl-dag-icon-0.9.0-updater-attempt-2-ordinary-2026-10-06.json)
and [spaces report](evidence/cwl-dag-icon-0.9.0-updater-attempt-2-spaces-2026-10-06.json)
remain diagnostics. These were corrections to validation fixtures, not changes
to the accepted application or updater engine.

The corrected fixture at **`648676c4388f1c4dc9f9af0476bf31f9cfca8c92`** passed
[run 37527359533](https://github.com/comparativechrono/workbench/actions/runs/37527359533):
all three jobs succeeded, with **13 native checks per ordinary/space-containing
path, zero failures and zero skips**. Each native run verified 70 core files,
preserved all 202 tracked existing files without changes, and repeated the
update idempotently. Saved settings, pinned workflows, packs, reference files
and existing results were included in preservation checks.

Real SAMtools reference analysis succeeded before and after the update; the
post-update result included CWL reference provenance. The reference fixture was
created from the packaged synthetic FASTA, not newly downloaded. Python host
socket operations were denied; native subprocesses were not OS-firewalled.
The updated app also passed seven scientific/export/SVG checks: 202 alignment
records, the known `starter:1351 G>A; GT=1/1` variant, 20 independently hashed
outputs, 18 command comparisons and five embedded-runner replays. This checks
the native updater CLI/private runtime, not its folder-picker UI or a Windows
CWL-engine invocation.

The [build record](evidence/cwl-dag-icon-0.9.0-update-build-2026-10-06.json),
[ordinary native report](evidence/cwl-dag-icon-0.9.0-update-final-ordinary-2026-10-06.json)
and [spaces native report](evidence/cwl-dag-icon-0.9.0-update-final-spaces-2026-10-06.json)
were downloaded and verified. The new archive is
`native-workbench-0.9.0-update-from-0.8.0.zip`, **12,864,532 bytes**, SHA-256
`caa50ff7807be889fd9f4fbb617a458b1d2b38f397ce365d4fc7fc17a2511d9e`.
It changes seven core files, removes none, and preserves all 143 starter-pack
files. Its accepted target application, updater engine and launcher bytes were
not rebuilt. The original candidate checksum list remains unchanged; the new
updater has a separate `UPDATE-SHA256SUMS.txt`.

## Publication

[Publication run 37528064595](https://github.com/comparativechrono/workbench/actions/runs/37528064595)
passed all steps, including **18 promotion guard checks** and fresh anonymous
download/checksum verification of all **12 public assets**. The
[publication receipt](evidence/cwl-dag-icon-0.9.0-publication-receipt-2026-10-06.json)
records the release identity and asset hashes. A separate
[independent public-download audit](evidence/cwl-dag-icon-0.9.0-public-downloads-2026-10-06.json)
passed for **all 12 assets**, **five ZIP CRCs** and **three checksum manifests**.
It confirmed that all six original candidate members and the new updater match
their exact validated bytes, and that release metadata/tag stayed unchanged.
The [published release validation record](evidence/cwl-dag-icon-0.9.0-release-validation-2026-10-06.json)
retains the native gates. These public checks reuse exact candidate/updater
Windows evidence; they do not claim new native execution.

One local copy of `WINDOWS-EVIDENCE.zip` was unexpectedly truncated after its
first completed download check. A fresh public download to a new temporary file
was hash-verified, atomically substituted locally and passed the full final
CRC/checksum audit. The diagnostic remains in the audit record; no public asset
was changed or replaced.

The release includes the unchanged accepted starter, source, 0.6.0 updater,
`BUILD-PROVENANCE.json`, `source-metadata.json` and `SHA256SUMS.txt`. It adds the
separately tested 0.8.0 updater, `BUILD-UPDATE-PROVENANCE.json`,
`UPDATE-SHA256SUMS.txt`, `RELEASE-VALIDATION.json`, `WINDOWS-EVIDENCE.zip` and
`EVIDENCE-SHA256SUMS.txt`. The evidence ZIP carries the earlier and final native
reports/captures plus updater evidence and validation source. Creation-time
pending statements in accepted source/build companions are historical; this
release record supplies later checks without replacing the tested archives.

- [Windows starter](https://github.com/comparativechrono/workbench/releases/download/app-v0.9.0/native-workbench-0.9.0-starter-windows.zip)
- [Updater from 0.8.0](https://github.com/comparativechrono/workbench/releases/download/app-v0.9.0/native-workbench-0.9.0-update-from-0.8.0.zip)
- [Updater from 0.6.0](https://github.com/comparativechrono/workbench/releases/download/app-v0.9.0/native-workbench-0.9.0-update-from-0.6.0.zip)
- [Matching application source](https://github.com/comparativechrono/workbench/releases/download/app-v0.9.0/native-workbench-0.9.0-source.zip)

## Limits

Both published updaters have passing native preservation gates, as recorded
above. No updater from 0.7.0 is included or claimed. Independent CWL
execution needs a compatible engine, Python 3.10+, matching packs and data;
Windows binaries are not translated to another operating system. Optional
executable replacements and rebound data need their own scientific validation.
No rerun of all optional packs, broad physical-display survey or new temporal
scrolling acceptance is claimed. User acceptance does not broaden those automated
validation claims.
