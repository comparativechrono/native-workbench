# Deployment and Windows acceptance companion

Status on **2026-10-09**: implementation, exact archive audit and hosted Windows
observations are complete, with **failed keyboard acceptance retained**.
[Draft PR #14](https://github.com/comparativechrono/workbench/pull/14) is open on
`feature/deployment-acceptance`, based on main
`9ac6f906e3acd88e743ed87c76cbf99c9087636d`. Tested toolkit commit:
`1a7d1e5f70e3ca710c9b3f6b1313353e8d46cc78`, clean tree
`6ef5ac330f7ea7026d382312641e70e1e91d01c9`. Later knowledge/evidence commits do
not change the tested kit. Published application **0.16.0**, updater and pack bytes
are unchanged. Nothing in this set was merged or released.

The owner approved this bounded set with “okay, lets do that”. Benchmarking is
handled separately. Scientific Linux CWL profiles and SDK/build recovery remain
later work. Signing and institutional approval require external prerequisites.

## Implementation

- A verified offline tester kit made from four exact published archives, with
  separate application/toolkit identities and an immutable file manifest.
  Verification precedes fresh disposable external copies; reports and user state
  stay outside the kit. Existing destinations are not overwritten.
- Readable and JSON inventories of files, components, PE formats, declared DLL
  imports and actual licence/source notices, retaining explicit unknowns. They
  do not establish complete dynamic dependency closure or licensing compliance.
- Guided manual reporting, explicit automated-report imports, selected attachments
  and actual Windows Authenticode observations. No automatic user, hostname,
  domain, IP or device identifiers; no automatic upload. Automation cannot
  complete the manual checklist or establish institutional approval.
- A native gate using the published updater's real folder picker and bounded
  keyboard/resize/results interactions. Failures remain failed while independent
  observations finish. Signature collection uses built-in system PowerShell
  modules without changing execution policy, security policy or trust settings.

Use the [tester guide](../docs/deployment-acceptance.md),
[IT review guide](../docs/institutional-deployment.md) and
[candidate workflow](../.github/workflows/deployment-acceptance-candidate.yml).

## Exact download

[Download the review kit](https://github.com/comparativechrono/workbench/actions/runs/37979351047/artifacts/11641200131).
GitHub sign-in is required; the artifact expires **2026-11-08 19:19 UTC**.

| Item | Identity |
| --- | --- |
| Inner ZIP | `native-workbench-0.16.0-deployment-toolkit.zip`, 126,486,209 bytes |
| Kit SHA-256 | `756489dce12acee16beee3d90da9142cb84e75a5580cabf4392490ce1f4107fa` |
| Download wrapper SHA-256 | `7e4fca6d814ad17aa82980db6ca735e9b3f191b1fd1a9e5b885e926290ab5cc5` |
| Manifest SHA-256 | `9e9fd96a0ad6e5bfe44d4803b97c8241534f67f176f8688588616388847fe650` |
| Packaged application source | `e855dc4396e0c16ae35f4e840eb9cc734adb4441` |
| Tested toolkit source | `1a7d1e5f70e3ca710c9b3f6b1313353e8d46cc78` |

An independent download audit checked wrapper identity, ZIP CRCs, all **375** kit
files, **12** toolkit Git sources, all **748** application Git sources and the four
original archives. All **274** Starter and **78** updater files match published
bytes; core, packs, private runtime, provenance and source correspondence passed.
The packaged acceptance CLI verified the clean manifest. This static/Linux audit
is separate from native Windows execution.

| Published input | SHA-256 |
| --- | --- |
| Starter 0.16.0 | `f96e03e43cac92ba8ca9a0a3807eb671f9924d5e624cadbba94d1a5ca1309073` |
| Updater 0.11.0 → 0.16.0 | `d75d5129e9b9feaef70faa62d5ea91049c0162df8c7bdc74c7bc81d1933eec8f` |
| Source 0.16.0 | `f746f00a82675c2cf52364a3b4d040721c6d06ac5605488efbdc0376ef5b7e44` |
| Disposable 0.11.0 baseline | `e816e2f7cd5efe98af752fbf072fab00344ebaa2b6963795c2fbf4a86b5fa81c` |

The [input lock](../packaging/deployment-0.16.0-lock.json) records exact sizes and
URLs. Starter contains align/bam/variants 0.4.0 and align 0.4.1. Updating preserves
installed pack pins and does not install align 0.4.1 automatically. The baseline
is a disposable test fixture.

## Validation

[Final run 37979351047](https://github.com/comparativechrono/workbench/actions/runs/37979351047)
is **failed** because Results Escape after keyboard Search failed on fresh and
upgraded installations in each path. Observation collection completed;
`nativeGUIValidated` and `success` remain false. No failure was waived.

| Scope | Ordinary path | Path with spaces |
| --- | --- | --- |
| Kit, actual verify launcher and external-copy preparation | Passed | Passed |
| Native updater/desktop scenarios | 14 passed, 2 failed, 0 blocked/skipped | 14 passed, 2 failed, 0 blocked/skipped |
| Curated workflows/results | 11 passed, 0 failed/skipped | 11 passed, 0 failed/skipped |
| Authenticode observations | 72 files: 60 Valid, 12 NotSigned | 72 files: 60 Valid, 12 NotSigned |
| Final immutable-kit verification | Passed | Passed |
| Imported automation / manual checklist | 1 summary / all 10 not-tested | 1 summary / all 10 not-tested |
| Screenshots reviewed | 21 native + 6 curated | 21 native + 6 curated |

The companion source suites passed **87 tests**, with no failures/skips, on
`ubuntu-22.04`: `python3 tests/test_deployment_inventory.py` (23),
`python3 tests/test_deployment_bundle.py` (25),
`python3 tests/test_deployment_acceptance.py` (30), and
`python3 tests/test_deployment_ui_gate.py` (9). These are Linux source tests.
Native jobs executed the exact packaged application/private Python on Windows
Server 2022 (`10.0.20348`); no Windows source-suite result is claimed here.

The real updater picker passed cancellation, invalid-folder rejection/retry,
installation and repeat use. It verified **87** new core files and preserved
**163** fixture files, including actual SAMtools reference output, independent
non-default settings, connected pipeline pins and local reference receipts.
The only allowed new fixture state was the one-NUL session lock. Upgraded
readback passed. Fresh Starter selection queued no installs and retained all
186 pack files. These counts belong to this run, not the earlier release fixture.

Both synthetic workflows retained 202 alignment records; variant calling retained
`starter:1351 G>A GT=1/1`. Exact-version dependency failures, changed evidence,
persisted results, missing-input guidance and native results search passed.
Recorded measurements retain explicit no-QC-verdict wording. Scientific hosts
denied Python socket operations; this does not establish OS network isolation.
Optional packs and all earlier application suites were not rerun for these
unchanged app bytes. Synthetic checks are not realistic benchmarks.

## Known failures and review limits

**Keyboard:** Escape immediately after keyboard Results Search left the window
open in all four fresh/upgraded cases. Results was foreground but no control had
focus before or after Escape. Clicking the query with real pointer input restored
focus; the following Escape closed. That diagnostic does not pass the original
requirement or establish the internal cause. The visible Close fallback was not
needed or tested in the final run.

**Display:** hosted desktop **1024×768**, work area **1024×728**, **96 DPI**.
The app's 1040-pixel minimum width clips its right edge. Requested 1280×900
resizing produced actual 1040×728. Bounded resize assertions describe navigation
and control bounds; they do not establish narrow-display acceptance.

All **54** captures were reviewed: 42 native via six contact sheets plus nine
full-resolution checks, and all 12 curated captures individually. No additional
fixed-control overlap was observed. Dialogs, measurements and guidance were
readable; main-window clipping remains recorded. Signature counts are file
occurrences, including duplicate updater payloads. Valid means the runner's
current trust context. Scripts are outside the collector scope; no signing or
institutional approval occurred.

## Evidence, delivery recovery and continuation

- [Final evidence](evidence/deployment-acceptance-final-2026-10-09.json) records
  exact source/archive/report identities, job steps, counts, failures and limits.
- [Archive audit receipt](evidence/deployment-acceptance-archive-audit-2026-10-09.json)
  and [visual review receipt](evidence/deployment-acceptance-visual-review-2026-10-09.json)
  preserve completed observations.
- Full original reports and screenshots: [ordinary evidence](https://github.com/comparativechrono/workbench/actions/runs/37979351047/artifacts/11639996891)
  and [spaced-path evidence](https://github.com/comparativechrono/workbench/actions/runs/37979351047/artifacts/11640790831).
  Sign-in is required and both expire **2026-11-08**. Wrapper and native-report
  hashes are retained in the final evidence.
- [Attempt history](evidence/deployment-acceptance-attempts-2026-10-09.json)
  preserves seven earlier failed/incomplete attempts, the rejected dirty preview,
  the corrected transient branch-tree mistake and the final failed-acceptance run.

The local executor disconnected after validation, documentation preparation and
independent verification of all original report copies. The final knowledge
files were recovered and saved through GitHub using the exact existing tree.
Detailed local per-file review receipts and report copies could not be read back
for committing. These durable aggregate receipts use verified observations and
hashed artifact references; original complete JSON/BMP files remain in Actions.
No unavailable per-file hashes or contents are reconstructed.

Next development: a **separately versioned Results focus/Escape fix**, plus
narrow-display handling or an explicit supported-display boundary. Preserve
published 0.16.0 bytes and repeat exact ordinary/spaced native gates for changes.
Representative-PC, high-DPI/transitions, multiple monitors, physical trackpads,
Unicode/path-limit manual observations, managed-machine policy and IT approval
remain outstanding. All 10 manual items are not-tested. Signing needs a controlled
identity; scientific Linux CWL and SDK/build recovery remain later sets, with
benchmarking handled separately.
