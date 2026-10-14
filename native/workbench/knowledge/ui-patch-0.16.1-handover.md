# Native keyboard and narrow-display patch, 0.16.1

Review snapshot: **2026-10-09**, branch `fix/native-ui-0.16.1`, based on
`f74d90229be6a78d6ad0c0076c54c04bb7e7cae2` and its open draft deployment companion
[PR #14](https://github.com/comparativechrono/workbench/pull/14). The user approved
continuation after reviewing the two observed desktop defects. This is an
unpublished application patch candidate; published 0.16.0 and the companion's
original failure evidence remain unchanged. No merge or release is authorized.

## Changes and contracts

- Results moves focus to its available query before disabling a focused action.
  Asynchronous replies do not take focus back from another control. Opening
  Results places focus in the query. Keyboard Search must retain focus and allow
  immediate Escape, for empty and populated results on fresh and upgraded apps.
- The main window uses monitor work-area bounds for initial placement and minimum
  size. The logical minimum is 960×680; narrow layouts retain three panes with a
  compact library and unchanged option-editor width. Shared geometry keeps
  controls and painted separators aligned. This targets the observed 1024-pixel
  desktop; high-DPI and representative-machine acceptance remain separate.
- Application and three native resource versions become **0.16.1**. Scientific
  operations, saved pins, all four published pack trees, private runtime, setup
  profile and catalogue trust remain unchanged.
- A new candidate builder derives one Starter, matching Git/source companion and
  core-only 0.16.0→0.16.1 updater from exact published 0.16.0 inputs. The existing
  deployment workflow/lock still describe their original frozen application.

## Candidate identity and validation

The new [candidate workflow](../.github/workflows/native-ui-patch-candidate.yml)
builds once, validates source correspondence and runs separate exact Windows
installations in ordinary and spaced paths: updater picker/state preservation,
keyboard/layout, curated scientific/results, workspace, reference management,
results/replay/DAG/icon and scrolling scopes. Initial bounds must be observed
before the driver resizes the window. Native focus checks use actual keyboard
input with no pointer workaround after Results opens.

The frozen application and initial gate source is
`8938e709b041106e8a46e1447383e8e9ba3e0cb9`, full tree
`d5a5f1f9ec4c606965e734370a0be4d9cf53d8c3`.
[Draft PR #15](https://github.com/comparativechrono/workbench/pull/15) is stacked
on `feature/deployment-acceptance`; its base remains the companion commit above.
[Run 37988570028](https://github.com/comparativechrono/workbench/actions/runs/37988570028)
passed all **141 Python source tests in 13 suites**, the C++ JSON check and all
three strict-warning native builds. No source tests failed or skipped. This is
the listed affected suite set, not a new claim about every historical test.

The independent downloaded-archive audit passed: 787 current Git sources,
33 packaged Python/source matches, 87 core files, 186 unchanged pack files,
39 unchanged private-runtime files and all updater inventory/operation bytes.
Exact archives:

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| Starter Windows | 17,847,594 | `7dfed53de2279f51deaea405dbfd29b36cddb733e5a20c43b3112f27a7728a8e` |
| Source companion | 48,078,770 | `48523c0e7090f661442bec2999c1658a1532ad7a5fa7fe882b1081b23452acc7` |
| Update from 0.16.0 | 12,982,946 | `f2dc435495f43d837e80837f3ba83ff7b6963294219d5bc88bc8fb0e5d82effd` |

Both ordinary and space-containing Windows paths passed **84 checks each**:
19 updater/keyboard/layout, 11 curated science/results, 32 workspace,
10 reference-management, nine results/replay/DAG/icon and three scrolling panels.
No configured native checks failed or skipped. The actual folder picker tested
cancel, invalid selection/retry, installation and repeat use; each installation
verified all 87 core files and preserved 208 recorded fixture files. Existing
settings, pipeline pins, results and local references reopened correctly.

A [frozen-archive recheck](https://github.com/comparativechrono/workbench/actions/runs/37989535317)
used validator `69022689e686b2cacdc98dbdbef728e664941e67`, repeated all 19 patch
checks per path, and captured passive desktop frames before PrintWindow. This
reused the exact archives above without rebuilding; it is not 19 additional
unique checks. Fresh and upgraded Results retained focus through empty/populated
Search and closed immediately on Escape without pointer intervention. Library
search, its Tab target and Results Search retained sampled focus for over
2.4 seconds across the normal queue-poll interval; exact poll counts were not
instrumented.

## Visual review and delivery

The [visual record](evidence/ui-patch-0.16.1-visual-review-2026-10-09.json) binds
reviewed capture hashes to the exact archives and both validator runs. Settled
960×680 and 1024×728 layouts retain their fixed controls and three panes.
Immediate resize frames can retain prior geometry; later passive observations
show the expected layout by the first requested 250-ms sample (about 0.3 seconds
elapsed), unchanged in subsequent samples. This is not a zero-flicker claim.
The initial full-frame interpretation that General settings and Readiness were
missing was incorrect: crops from the original BMP bytes show both. Corrected
receipts retain that review correction; it is not a product-failure finding.

- [Starter download](https://github.com/comparativechrono/workbench/actions/runs/37988570028/artifacts/11644122776)
- [0.16.0→0.16.1 updater](https://github.com/comparativechrono/workbench/actions/runs/37988570028/artifacts/11643868222)
- [Complete candidate including matching source](https://github.com/comparativechrono/workbench/actions/runs/37988570028/artifacts/11643983086)
- [Ordinary native evidence](https://github.com/comparativechrono/workbench/actions/runs/37988570028/artifacts/11643758770)
  and [spaced-path native evidence](https://github.com/comparativechrono/workbench/actions/runs/37988570028/artifacts/11643554897)
- [Ordinary passive-frame evidence](https://github.com/comparativechrono/workbench/actions/runs/37989535317/artifacts/11644831083)
  and [spaced-path passive-frame evidence](https://github.com/comparativechrono/workbench/actions/runs/37989535317/artifacts/11644173880)

Actions downloads require GitHub access and expire **2026-11-08**. They are review
artifacts, not release assets. The final documentation/evidence commit changes
only `knowledge/` relative to validator `69022689`; it does not rebuild or alter
the tested application. Published 0.16.0, main and draft companion PR #14 remain
unchanged. No merge, tag or release publication was performed.

Durable receipts: [source checks](evidence/ui-patch-0.16.1-source-validation-2026-10-09.json),
[archive audit](evidence/ui-patch-0.16.1-archive-audit-2026-10-09.json),
[transport](evidence/ui-patch-0.16.1-transport-2026-10-09.json),
[build provenance](evidence/ui-patch-0.16.1-build-provenance-2026-10-09.json) and
[native validation](evidence/ui-patch-0.16.1-native-validation-2026-10-09.json).
The original builder and archive-audit receipts retain their status at creation
(before native execution); the completed native and visual records above supply
the subsequent results without rewriting those historical receipts.

## Retained attempts

The [attempt history](evidence/ui-patch-0.16.1-attempts-2026-10-09.json) preserves
both earlier failed candidates. The first gate used incorrect numeric control
IDs and closed before the asynchronous setup dismissal reply; the spaced path
also timed out clearing a filter without recording focus/selection. The second
candidate passed all 84 configured checks in the ordinary path, but both spaced
path desktop scopes failed before Results. Neither failed run is relabelled as
passing.

Source review then found that periodic read-only `queue/status` disabled focused
editing/navigation controls and could displace Results Search focus. The final
application revision exempts only that request when no action is queued. Existing
setup/reference/pack/history/closing guards and FIFO ordering remain; a queued
action immediately refreshes disabled states. The gate now observes real
Home/Shift+End selection and holds focus passively for 2.4 seconds on library
search, its Tab target and Results Search. It samples across the normal polling
interval without refocusing; it does not claim an instrumented count of polls.

## Remaining limits

The layout target is the hosted 96-DPI desktop with 960×680 and 1024×728 outer
windows. A requested 1280×900 is capped to the actual work area; it does not prove
wide-display acceptance. Source geometry can overlap below 908 logical client
pixels (busy Cancel/Results), with footer overlap below 902. Smaller work areas
and high-DPI layouts therefore remain unvalidated; the fit claim is limited to
the tested sizes. Legacy scrolling/results fixtures deliberately request other
window sizes and are not initial-work-area containment evidence.

Representative-PC, high-DPI/transitions, multiple monitors, physical trackpads,
managed-machine policy and IT approval remain outstanding. Signing requires a
controlled identity. Scientific Linux CWL and SDK/build recovery remain later
sets; benchmarking is handled separately. Only the published 0.16.0 updater
baseline was tested here. New public-release promotion/download validation,
other upgrade baselines, rollback/recovery scenarios and representative-PC
acceptance are not established by these candidate checks.
