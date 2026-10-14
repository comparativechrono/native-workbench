# Tool Setup corrective patch 0.10.1

Snapshot: 2026-10-07. Branch: `fix/tool-setup-0.10.1`, from published-main
`4777f020f0907b4431d0a5be115ef5d9aa776457`. **Final status: 0.10.1 released**
as a development prerelease; the dated preparation sections below retain their
original evidence boundaries.

Testers reported flashing column headers, unusable package scrolling and the
message “Download failed. Check the connection and whether the approved host
is accessible.” The exact published 0.10.0 archive and its successful prior
Windows reports remain immutable historical evidence. New checks must establish
the behavior missing from that coverage.

## Changes and diagnosis

The native setup list was disabled during refresh or installation, which also
prevented scrolling. The patch keeps navigation enabled and vetoes checkbox
changes while selection is locked. It updates changed row cells in place,
retains selection/focus/scroll position across structural updates, and avoids
repeated radio, text, progress and column updates. The report list is already
double-buffered; the setup window no longer adds top-level compositing around
it. Failed/cancelled/interrupted operation notices retain the pack name.

Header flashing has not yet been independently reproduced. The new gate samples
actual desktop header pixels through sustained idle and live polling, records
observed changes rather than assuming them, and exercises real wheel and scrollbar
navigation. A separate disposable extraction of published 0.10.0 supplies a
negative control. A network failure is a failed prerequisite, not evidence of
the expected UI regression.

The old downloader caught every URLError and OSError with the same message,
including local create/write/flush failures. New diagnostics distinguish bounded
HTTP status, proxy authentication, certificate/TLS, DNS, timeout/refusal/reset,
and permissions/full/locked/missing local storage. Only approved hostnames appear;
raw exceptions, signed URLs and proxy credentials do not. Signing, hashes,
approved-host checks, cancellation and timeout/retry policy remain unchanged.

The exact released downloader matched the inspected pre-patch source. Both old
and new Linux transport probes verified the current 32-pack production catalogue
and the 486,120-byte reads archive with SHA-256
`2dd05fece8deb2b0178d8b1bc2b6830f175b3fbc2f5a4d48f9c9023cbfe6775b`.
The testers' failure has not been reproduced or diagnosed. The improved message
will distinguish the next necessary action on their machine.

The patch also corrects stale bundled README text claiming production trust was
not included. It retains the same owner public key, setup profile and pack bytes.

## Validation before native candidate

- Backend source checks: 68 passed; one native Windows filesystem test skipped.
  These are 46 pack-manager passes plus 15 setup-manager and seven service passes;
  the Windows-only case must be executed by CI, not counted here.
- Seven focused synthetic patch-updater packaging guards passed. They enforce
  the exact published baseline, core-only replacements and unchanged pack,
  production trust and setup-profile bytes.
- UI gate Python syntax and whitespace checks passed. This is not a native UI pass.

The dedicated `native-setup-patch-candidate.yml` builds exact starter, matching
source and 0.10.0 updater archives once. It runs ordinary and space-containing
Windows setup/UI/References/results/upgrade checks and one real production Full
installation. The updater gate includes saved setup selection and queue state
alongside installed tools, settings/pins, references and results. Native results,
archive identities, failures and later release status must be appended after
actual checks. No new Windows pass is asserted in this preparation snapshot.

## First candidate execution

Run `37633214062`, source `12b7c89580fd97acc55a731a298d20b01af7473c`,
compiled successfully: 161 source checks passed and one Windows-only test skipped;
all 47 pack-manager checks then passed natively on Windows. Both native path
variants passed workspace 32, results 9, References 8 and update 13 checks.
The new UI probe failed on both old and patched applications at its immediate
profile-switch interaction: it posted Space without restoring actual list focus.
That is a failed probe, not a UI pass or reproduced baseline defect. The validator
now waits for profile acknowledgment and the actual GUI-thread focus before keys.
It also compares active header pixels with the settled idle reference and keeps
the disposable probe application outside retained evidence. No application-code
change was needed for this probe correction. A new complete candidate run is
required; the first attempt is not accepted release evidence.

## Corrected candidate, native checks complete; Full pending

Candidate `00b53cdded5db3bb176ee7e5a06546b8a0c66fff`, run `37634723095`,
passed all ordinary and space-containing Windows jobs: setup 14, workspace 32,
References 8, results 9 and update 13 per path, plus a separate one-check
published-baseline negative control. References reports its optional embedded
updater as unrequested; the separate 13-check updater passed. All 47 native
Windows pack-manager source tests passed. Linux source checks were 161 passed
and one Windows-only skip; these overlap earlier source results.

The published baseline showed five navigation defects per path, an unchanged
wheel position (25 to 25), a disabled list throughout active samples, lost
selection/focus and multiple header pixel hashes during both idle and active
observations. The patch retained a single identical normalized header image
across 391 samples in total, including 98 active samples per path. Wheel input
moved the viewport from 25 to 16 while keeping the selected/focused pack;
checkbox edits remained blocked during active installation. Six/seven changing
progress states established live activity over approximately 4.96 seconds.
These are finite hosted desktop observations, not all physical-display coverage.
Only final header bitmaps were retained, so transient baseline images cannot be
visually classified retrospectively.

The core updater preserved all 204 pre-existing fixture files in each path,
verified all 72 target core files and safely reported already-installed on repeat.
The independent bounded-download audit verified all three archives, 590 matching
source files, unchanged production trust/profile and 143 starter pack files.
Both compact audits are retained under `knowledge/evidence/tool-setup-0.10.1-*`.
Real production Full, release acceptance and public-download verification remain
pending at this snapshot; no tester-PC download diagnosis is asserted.

## Accepted for immutable promotion

Run `37634723095` completed successfully, including production Full: all 32 exact
pack pins installed using unchanged official trust, reopened offline, preserved
202 alignment/BAM records and contributed the BED workflow input. Its four checks
had no skips or unrun scope. The exact report, final state, artifact hash/size
and ZIP CRC were independently checked; the publication guards accepted them.
The complete acceptance lock in `scripts/publish_app_0101.py` pins the three
archives, four original CI artifacts and 13 reviewed report hashes. PR #5 and
read-only preparation will precede publication. No public release is claimed
at this acceptance snapshot; the tester-PC download failure remains undiagnosed.

## Published result

Release **405862679**: [app-v0.10.1](https://github.com/comparativechrono/workbench/releases/tag/app-v0.10.1),
published **2026-10-07T14:38:46Z**. PR #5 merged at
`28b1ff621f7fdafe6162a3d7ce1d7984962a290b`, which is the release tag commit.
The application/source/update archives remain the exact accepted `00b53cdd` bytes.
Read-only preparation run `37637802039` verified all ten prepared assets, then
publication run `37638350825` passed its 28 guards, immutable promotion and
anonymous ten-asset verification. No release asset was replaced or rebuilt.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| Starter | 17,032,722 | `a8c4d374104d62fdf46dbd405e9d5bc36f5e2ea191f573faa63cfb29b433ba79` |
| Update from 0.10.0 | 12,858,983 | `fbf1f20d93c1fe781608cba6d48c948979986c06cdb9a4ce5b825b088d2fc3fb` |
| Source | 46,832,829 | `4130c105e0ce0956c234718f93926d1f9b3f6bfd81048b8fc6e8823617c583ab` |

The UI correction is complete in the tested hosted conditions. The original
machine-specific download cause remains a blocker to claiming that user's
installation problem resolved. Apply the 0.10.0 updater, retry setup, and collect
the exact new message plus pack name if it fails. Do not relax certificate,
signature, checksum or approved-host checks to make an unexplained failure pass.

Independent public verification downloaded all ten assets again and found no
mismatches: all expected sizes/SHA-256, four public ZIP CRCs and both checksum
manifests passed. Seven original candidate files remain byte-identical; 13
reviewed reports and all 32 completed production pins bind to the public starter.
The public audit performed no new Windows execution and retains that distinction.
