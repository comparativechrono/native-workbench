# Native Workbench 0.16.0 release handover

Status on **2026-10-09: published development prerelease; public downloads verified**.
[Native Workbench 0.16.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.16.0)
was published at **2026-10-09T15:54:56Z**, release ID **408075619**.
All exact candidate, updater and release-regression jobs passed. Feature PRs
#7–#11 and release PR #12 are merged. The immutable tag targets
`60243d45a81a6ef7e16e4a0ee719f4aa2e4f74c9`, distinct from packaged source
`e855dc4396e0c16ae35f4e840eb9cc734adb4441`. Publication downloaded and verified
all 13 public assets without rebuilding the accepted archives.

The user authorized a new release on 2026-10-09 with the exact instruction:
**“Great lets do a new release at this point”**. The intended channel is a
**development prerelease**, matching the existing 0.11.0 release channel. The
immutable tag is `app-v0.16.0`; previous published assets were not overwritten.

The [candidate handover](curated-workflows-results-0.16.0-handover.md) remains
the historical record of the earlier unpublished review scope, its limits and
rejected attempts. Its statement that publication was unauthorized applied to
that earlier instruction. The later authorization above permits this release
effort; it does not turn pending checks into passes.

## Current corrected candidate

Application/source commit: `e855dc4396e0c16ae35f4e840eb9cc734adb4441`.
[Candidate run 37952018931](https://github.com/comparativechrono/workbench/actions/runs/37952018931)
built the following archives. Its Linux source selection passed **488 tests**
with **four Windows-only skips**. Each Windows path passed 332 source checks
with four platform/privilege skips across 19 suites. All three jobs and every
required step passed; the 22 native reports and their capture hashes were
independently verified. Final curated screenshots passed visual review in both paths.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-0.16.0-starter-windows.zip` | 17,846,873 | `f96e03e43cac92ba8ca9a0a3807eb671f9924d5e624cadbba94d1a5ca1309073` |
| `native-workbench-0.16.0-source.zip` | 47,848,425 | `f746f00a82675c2cf52364a3b4d040721c6d06ac5605488efbdc0376ef5b7e44` |
| `native-workbench-pack-align-0.4.1.zip` | 575,862 | `3a08cf061f0b62c5502d1420115db3fcae2b04bf695ad3cfd1c3063de0fafa02` |

The [complete artifact 11626720550](https://github.com/comparativechrono/workbench/actions/runs/37952018931/artifacts/11626720550)
is **65,972,456 bytes**, SHA-256
`2c17413e96cf113c4ddb007651ac45b471d74ba4b3b5aaeb0a579bd5009308cd`.
Downloaded aggregate/inner archive identities and CRCs were checked. All **748**
`SOURCE-RECOVERY.json` current-source entries match their recorded sizes/hashes
and exact Git bytes. The package inventories contain 87 core files and 33 Python
runtime modules, preserving 143 published pack files and 39 private-runtime
files. The align ZIP is unchanged. This inspection does not establish Windows
execution.

The accepted exact bytes must be promoted without rebuilding. Release-tooling/validator commits and the final publication
commit are separate from the packaged application-source commit. Original Actions
downloads are temporary and may require sign-in. The final archives and durable
evidence are now available from the public release above.

## Historical candidate: not the publication input

The previous application was built from
`7a9aca71ddd4816b51dbe693873f42fa50a6b746` in successful
[candidate run 37941573921](https://github.com/comparativechrono/workbench/actions/runs/37941573921).
The hashes below identify those historical bytes, **not an accepted release
freeze**. Its passes remain valid only for their recorded scope and cannot be
transferred to the corrected candidate above. The publisher/updater inputs have
been retargeted to the final source, whose complete acceptance is recorded below.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-0.16.0-starter-windows.zip` | 17,846,720 | `1ff91bdb386171aeb166fec4fce4ad23e31287dc9e9695167db113994f416131` |
| `native-workbench-0.16.0-source.zip` | 47,765,332 | `8fc6a510d178632f12259a3e6e6b115c2c6c40562906eecc5a5557a7a9a361de` |
| `native-workbench-pack-align-0.4.1.zip` | 575,862 | `3a08cf061f0b62c5502d1420115db3fcae2b04bf695ad3cfd1c3063de0fafa02` |

The [complete candidate artifact 11621489330](https://github.com/comparativechrono/workbench/actions/runs/37941573921/artifacts/11621489330)
was independently downloaded and checked: **65,891,317 bytes**, SHA-256
`9aab1bac997122fbf2c5418075bf4f2e35a2af442b06810b29656824e4ff020d`,
valid ZIP CRCs. Its independent align pack matches the frozen inner archive.
Actions artifacts are temporary and may require sign-in; these are not release
download links.

The existing candidate evidence covers the two synthetic training workflows,
native measured results/search/failure guidance, preserved reference and
workflow behavior, and ordinary/spaced Windows paths. Its archive audit binds
734 source files, 87 core files and 33 Python runtime modules to the frozen
source; 143 published pack files and 39 private-runtime files are preserved.
Production trust and setup-profile bytes remain unchanged. Full counts,
screenshots and platform-specific skips remain in the historical handover.

## Release regression requiring a replacement candidate

The first additional regression run,
[37949426177](https://github.com/comparativechrono/workbench/actions/runs/37949426177),
is rejected. The results gate passed all nine checks in both paths, but the
scrolling fixture matched two operation rows and did not reach its frame checks.
A release-specific scrolling validator now selects the exact standard row while
preserving the frame assertions. The final frozen-package run below passed.

The long-path gate passed the original Starter/core scientific checks but
failed the additional align 0.4.1 self-check. Diagnosis found an application
bug: creating the pack-check workflow underneath its 37-character report
directory made the child working directory **291 characters** long, so Windows
`CreateProcess` failed. The declared supported long-path scenario requires the
child working directory to remain below 260 characters. The implemented fix
creates self-check graph runs directly under the installation-check output
parent, beside the pack-check report directory. It preserves that report and
its exact result-folder references. It does not weaken the boundary or bypass the additional-pack
assertions.

The original run and diagnostic rerun are retained in the
[rejected release-regression record](evidence/curated-workflows-0.16.0-release-regression-rejected-2026-10-09.json).
The replacement source `a44799723a280cca18c989e74e4c9ff7e1807a5e`,
[run 37951228444](https://github.com/comparativechrono/workbench/actions/runs/37951228444),
contained the application fix. Its native feature gates passed, but the full
Windows source selection had two failures per path: the new test compared a
`RUNNER~1` temporary-directory alias with its resolved `runneradmin` path.
Its [successful archive audit](evidence/curated-workflows-0.16.0-release-archive-audit-prefinal-a447997-2026-10-09.json)
does not override those failures. The final `e855dc4` change resolves the test
fixture path before comparison; application behavior is unchanged from
`a447997`. Neither superseded run is final release acceptance.

The final candidate has its own complete ordinary/spaced native reports,
screenshots, source/archive audit, release regressions and updater. The positive
long-path gate now explicitly requires the extra align 0.4.1 operation, a native
working directory below 260 characters, a SAM path above 260 characters and the
fixture's 202 mapped proper-pair records. Its four required checks cannot be
satisfied by the earlier Starter-only partial success.

## Additional release work and historical updater evidence

The updater targets the **published 0.11.0 Starter only**, whose archive is
17,044,022 bytes with SHA-256
`e816e2f7cd5efe98af752fbf072fab00344ebaa2b6963795c2fbf4a86b5fa81c`.
It must update the 87 core files while preserving installed packs, saved state,
results and references. It does not implicitly install align 0.4.1. That pack
is a separate checksummed release ZIP for explicit offline import; no catalogue
or publisher-trust change is part of this release.

The validator creates a real legacy reference analysis using the original
0.11.0 application's private host/runtime before upgrading that same
installation. It then checks exact input/reference identities and receipts,
provider ID separately from its display name, native FAI truth, CWL/methods
provenance, honest legacy-result interpretation and unchanged external bytes.
The scope is the native updater CLI/private runtime; the updater's interactive
folder picker and live reference downloads are not covered by this gate.

- **First updater attempt rejected:**
  [run 37949425935](https://github.com/comparativechrono/workbench/actions/runs/37949425935),
  validator source `f231ade2bd2c1602f4a7725c10f15bedda61149e`. Both Windows jobs
  failed after four checks. Core installation/repeat behavior and preservation
  of 204 existing files had passed, but this is not an accepted updater result.
  A legacy validation assertion expected the reference provider ID in the
  methods display. The current application preserves the provider ID and
  receipt while displaying its recorded `provider_name`. The updater validator
  was corrected to check these separate identities; the frozen application
  bytes were not changed. The native FAI/CWL and external-reference hash
  assertions remain required. See the
  [first updater failure record](evidence/update-0.16.0-first-validation-2026-10-09.json).
- **Second updater attempt passed its historical hosted scope:**
  [run 37949918855](https://github.com/comparativechrono/workbench/actions/runs/37949918855),
  source `d66401191005db0bdf32b1f76d3fe3318fa14ad4`, all three jobs passed.
  The source selection passed 24 checks. Each Windows path passed 18 main
  checks, with no failures or skips, plus 11 nested curated/native-interface
  checks and seven installation checks without the additional pack. These
  counts describe distinct report scopes and are not summed. Checks verified
  87 core files, 204 preserved files with no changes, explicit import of 43
  additional-pack files while preserving 182 existing pack files, and 17
  unchanged legacy scientific/reference files. The hosted updater is
  **13,193,325 bytes**, SHA-256
  `b0ac85144deaca9008df11d025b157ca6be6977874c19637a6a525da573d2395`.
  Independent downloaded archive/report verification also passed. This updater
  targets the now-rejected `7a9aca7` application; its bytes and passes remain
  historical and must not be used in the final release lock. Retain its
  [pre-fix validation](evidence/update-0.16.0-pre-fix-validation-2026-10-09.json)
  and [pre-fix visual review](evidence/update-0.16.0-pre-fix-visual-review-2026-10-09.json).
- **Additional Windows regressions:** final results/CWL/DAG/icon and scrolling
  checks passed in both paths, along with four positive long-path checks and
  verified policy restoration. Their accepted final run is recorded below.

The publisher requires a complete release lock, successful locked jobs and
required steps, archive/report/source correspondence, the exact merged `main`
commit and absence of the new tag/release. Its read-only preparation must pass
before publication. Native update evidence is mandatory by report kind; missing
upgrade identities or preservation evidence cannot fall back to a generic
application pass. Publication must retain raw evidence and matching helper
sources, create new assets without replacement, then verify downloaded public
bytes.

## Accepted final validation and delivery status

- **Candidate:** [run 37952018931](https://github.com/comparativechrono/workbench/actions/runs/37952018931),
  source `e855dc4396e0c16ae35f4e840eb9cc734adb4441`: all three jobs/steps passed.
  Linux 488 passes/four skips; each Windows path 332 passes/four skips.
  Each path passed curated 11, live references 9, management 10, resource 14,
  readiness 5, batch 11, recovery 12, transport 3, library 7, workspace 32 and
  independent align import/scientific verification.
- **Updater:** [run 37952583789](https://github.com/comparativechrono/workbench/actions/runs/37952583789),
  packaging/validator `0e92d969e13fb7fe96b972bdb71b433f834dbbbe`: 24 source checks,
  all three jobs passed, 18 native checks per path plus nested curated 11.
  Archive **13,199,905 bytes**, SHA-256
  `d75d5129e9b9feaef70faa62d5ea91049c0162df8c7bdc74c7bc81d1933eec8f`.
  All 87 core files match the final Starter; 204 existing files, 182 installed
  pack files and 17 legacy scientific/reference files remain preserved.
  Align 0.4.1 stays absent until explicit import, which adds its exact 43 files.
- **Release regressions:** [run 37952595124](https://github.com/comparativechrono/workbench/actions/runs/37952595124),
  same validator `0e92d96`: all three jobs/steps passed. Results 9 and scroll 3
  per path; 960 frames, 300 endpoint transitions and 18 precision cases per path.
  Long paths 4, including the additional 202-record alignment check; native cwd
  254 and SAM path 268 characters. Disabled runner policy was restored.
- **Independent checks:** [archive audit](evidence/curated-workflows-0.16.0-release-archive-audit-2026-10-09.json),
  [release regression record](evidence/curated-workflows-0.16.0-release-regression-final-2026-10-09.json),
  [24 final curated/results visual reviews](evidence/curated-workflows-0.16.0-release-visual-review-2026-10-09.json)
  and 24 additional results/scroll captures. No earlier candidate passes are inherited.
- **Integration:** [PR #12](https://github.com/comparativechrono/workbench/pull/12)
  is merged at `60243d45a81a6ef7e16e4a0ee719f4aa2e4f74c9`; the final lock and read-only preparation passed.
  Implementation PRs #7–#11 were merged first with their exact recorded heads.
- **Publication:** completed in [run 37955110070](https://github.com/comparativechrono/workbench/actions/runs/37955110070).
  All 13 assets passed anonymous public-download checks. The new tag and release
  retain the accepted archives unchanged; the actual receipt is recorded below.

## Limits that remain after release checks

Hosted ordinary/spaced-path execution and synthetic known answers do not
establish representative-PC, high-DPI, multi-monitor or physical-trackpad
acceptance, biological/clinical validity, realistic workload capacity or
Windows–Linux performance. Scientific Linux CWL validation, realistic
benchmarking, executable signing and institutional deployment remain separate
outstanding work. Source-suite platform/privilege skips remain explicit in the
candidate evidence. The prior library capture helper's ignored enumeration
warnings are retained; functional checks do not imply exhaustive visual
coverage. The unchanged 32-pack catalogue was not fully downloaded or all
optional scientific tools revalidated for this application release.

## Hosted publication preparation

[Read-only preparation run 37954220037](https://github.com/comparativechrono/workbench/actions/runs/37954220037) passed at `1527a2ca0bbca760735b2e34920c72b397ab5d54`, including all 16 publisher guard tests, online identities and preparation of 13 assets. The publication job was intentionally skipped on this verification branch. The downloaded compact receipt passed size, SHA-256 and ZIP CRC checks and records no remote release mutations. The [preparation record](evidence/curated-workflows-0.16.0-release-preparation-2026-10-09.json) retains artifacts, receipt and feature merge identities. PR #12 was subsequently merged and public promotion completed.

## Final publication

[Publication run 37955110070](https://github.com/comparativechrono/workbench/actions/runs/37955110070)
passed all promotion steps at the merged release commit above. The verification-only
job was intentionally skipped on the publication branch. The publisher created a
new tag and draft, verified all 13 uploaded assets, published the development
prerelease without changing the latest-release channel, and verified every public
asset by anonymous download. The [publication record](evidence/curated-workflows-0.16.0-publication-2026-10-09.json)
retains actual release/asset IDs, hashes, run steps, merge identities, receipt and
final `RELEASE-VALIDATION.json`. The [independent download audit](evidence/curated-workflows-0.16.0-public-downloads-2026-10-09.json)
records a second download and archive/checksum/source check. Historical candidate
and creation-time provenance files are retained unchanged; this final record
supersedes their pending publication status.
