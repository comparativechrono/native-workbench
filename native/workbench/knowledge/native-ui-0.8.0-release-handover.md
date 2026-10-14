# Native Workbench 0.8.0 release handover

Recorded **2026-10-06**. The user explicitly accepted the latest tested 0.8.0
candidate and authorized publication. This is user-reported acceptance of the
candidate, separate from the automated evidence below. It supersedes the
previous pending tester-confirmation status. **0.8.0 is published as a development
prerelease**, and all nine public assets have been independently downloaded and
verified. The [release](https://github.com/comparativechrono/workbench/releases/tag/app-v0.8.0)
was published at **2026-10-06T13:12:15Z**. Published 0.7.0 remains unchanged.

## Accepted source and immutable candidate

The release promotes the exact archives built from
`b3928ca6a29d22b5f010a303658c2e19c24324da`, validated in
[run 37453380541](https://github.com/comparativechrono/workbench/actions/runs/37453380541).
The [candidate bundle](https://github.com/comparativechrono/workbench/actions/runs/37453380541/artifacts/11408021439)
is artifact **11408021439**, 75,599,305 bytes, SHA-256
`234688eabc01315aceba6fd588094bc7bf2263670766d0bdc9d088f8f0c735c1`.
Its recorded expiry is **2026-11-05T10:59:55Z**; a temporary CI artifact is not a
durable release download.

| Accepted archive | Bytes | SHA-256 |
| --- | ---: | --- |
| [native-workbench-0.8.0-starter-windows.zip](https://github.com/comparativechrono/workbench/releases/download/app-v0.8.0/native-workbench-0.8.0-starter-windows.zip) | 16,948,940 | `df001a80033ff8e834045ec683c79672e0efdbd4880fb89fca8bf8c36d830fdc` |
| [native-workbench-0.8.0-update-from-0.6.0.zip](https://github.com/comparativechrono/workbench/releases/download/app-v0.8.0/native-workbench-0.8.0-update-from-0.6.0.zip) | 12,897,242 | `3dd146267b9a8300ba957c84914bc324ea537c05b09268b48381ae6a4d530e96` |
| [native-workbench-0.8.0-source.zip](https://github.com/comparativechrono/workbench/releases/download/app-v0.8.0/native-workbench-0.8.0-source.zip) | 46,243,835 | `c2590379b45d313acbcd5bbc41344b288aa6ad159804bf06dcbdcc9726adb22f` |

The packaged `NativeWorkbench.exe` SHA-256 is
`e32fc3e5acb42766641a822f01835430b3312b84c3174bd282fe2a50ef6f9d71`.
Candidate recovery verified all three ZIP CRCs, build provenance, 68 core
inventory entries, 143 unchanged starter-pack entries, 15 packaged workspace
source copies and 14 relevant source files. The
[scroll/candidate ledger](evidence/native-workflow-0.8.0-scroll-2026-10-06.json)
retains exact report and capture hashes and earlier failures.

The release workflow promoted these accepted bytes without rebuilding them.
Later handover and publication records remain separate from the source
companion's creation-time snapshot. Do not replace an archive to make its
historical pending statements appear current. Published 0.7.0 application and
tool-pack bytes remain unchanged.

## What the accepted candidate passed

All five jobs in run 37453380541 passed. Evidence is tied to the accepted
archives, not inferred from the release tag:

- **82 source checks** passed in Linux CI with no failures or skips.
- Each ordinary and space-containing Windows path passed **32 workspace checks**
  (8 host, 2 scientific and 22 GUI) and **8 References/update checks**, with no
  failures or skips. Native minimap2-to-SAMtools execution preserved 202 paired
  alignment records and produced sorted BAM. Both paths retain 28 verified
  workspace/References captures.
- The nested-output regression ran the full five-stage starter pipeline with
  long-path policy disabled in disposable CI. All 7 core checks passed; all 20
  pipeline output hashes were independently checked, including 19 paths over
  260 characters, up to 279. The expected homozygous **starter:1351 G>A, GT 1/1**
  result and real BAM were retained. The prior missing-output failure was
  reproduced separately, and the original CI policy was restored.
- Three native panels passed temporal and precision-wheel checks at 96 DPI on
  Windows Server 2022/private Python 3.13.16: 960 sampled desktop frames, zero
  unexpected static-text/background frames, all 300 requested endpoint
  transitions observed, and all 18 precision-wheel cases passed.
- Native updater coverage is **0.6.0 to 0.8.0**. It preserved all 187 existing
  files, repeated idempotently, verified 68 target core files and reopened
  offline. No 0.7.0-to-0.8.0 updater is supplied or claimed.

The user had already confirmed the nested-output pipeline fix. The subsequent
acceptance covers the latest reviewed candidate and authorizes publication;
no additional machine, display model, DPI or physical input-device measurements
are inferred from that acceptance.

## Limits retained after acceptance

The user's visual flashing was **not reproduced in CI**: the prior package also
had zero unexpected frames across the same 960 samples. Six old precision-wheel
cases did fail and now pass; that movement defect is distinct from the visual
flashing report. Sampling at 27.16–31.80 observed frames/second masks edit/button
regions and cannot exclude shorter flashes between samples. Earlier settled
pixel comparisons were not temporal observations.

Native coverage does not establish every physical trackpad, high-DPI or
multiple-monitor configuration, native folder-picker interaction, optional-pack
long path or institutional deployment. It is research/teaching validation, not
clinical validation. Accepted user feedback does not widen those automated
claims. See the [native interface guide](native-ui.md) for the workflow and
input contracts.

## Publication and final public verification

[Release 404720508](https://github.com/comparativechrono/workbench/releases/tag/app-v0.8.0)
is public, non-draft and marked as a development prerelease. Tag **app-v0.8.0**
points to **`6fa1886b2027cfe634d9f9234fff773cd6c646d0`**. The accepted interface
work merged through [PR #1](https://github.com/comparativechrono/workbench/pull/1)
at `2086175`. Packaged source remains **`b3928ca`**: subsequent source-control
changes contain documentation, release records and promotion automation, not a
rebuilt application.

The release contains the three archives above plus `BUILD-PROVENANCE.json`,
`source-metadata.json`, `SHA256SUMS.txt`, `RELEASE-VALIDATION.json`,
`WINDOWS-EVIDENCE.zip` and `EVIDENCE-SHA256SUMS.txt`. The
[independent public-download record](evidence/native-ui-0.8.0-public-downloads-2026-10-06.json)
records fresh anonymous downloads of all **nine assets**: sizes and SHA-256
values match GitHub metadata and the frozen promotion bytes; six original
companion files also match the accepted candidate. All four ZIP CRCs and both
checksum manifests passed. The
[retained release validation](evidence/native-ui-0.8.0-release-validation-2026-10-06.json)
matches the published report and binds the accepted native evidence.

Two publication diagnostics remain separate history. The
[first attempt](evidence/native-ui-0.8.0-publication-attempt-1-2026-10-06.json)
failed with HTTP 415 while obtaining a build artifact, before any release
mutation. The [second attempt](evidence/native-ui-0.8.0-publication-attempt-2-2026-10-06.json)
verified all nine draft assets and published successfully, then its first public
GET returned HTTP 404 and failed that workflow's verification step. Publication
had already occurred; the independent downloads above subsequently succeeded
without replacing any asset. The separate [read-only verification run 37469812304](https://github.com/comparativechrono/workbench/actions/runs/37469812304)
subsequently passed every step and all 11 promotion/verification guard tests. It
recovered the exact retained promotion archive and anonymously reverified all
nine canonical public downloads without remote mutations. Its
[final record](evidence/native-ui-0.8.0-final-public-verification-2026-10-06.json)
and [raw receipt](evidence/native-ui-0.8.0-final-public-verification-receipt-2026-10-06.json)
remain separate from both original failed attempts.

Public-download verification reuses the exact accepted candidate's Windows
evidence; it does not claim new native execution against final URLs. User
acceptance, automated native results and public byte verification remain
distinct records. Existing evidence and historical candidate objects are
preserved. There is no 0.7.0-to-0.8.0 updater; the supplied update is for 0.6.0
only.
