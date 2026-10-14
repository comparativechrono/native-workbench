# Reference management: 0.15.0 handover

Status on 2026-10-08: **first reference-management group implemented and hosted Windows validation complete; unpublished and ready for tester review**.

## Verified candidate and downloads

[Draft PR #10](https://github.com/comparativechrono/workbench/pull/10) contains
this first remaining group. The frozen application source is
`46bbb39dda2cc5bb08c30af494cb340f976acf3b`, tree
`6b1641f7f915a93d8a007933aa6cba62cafc10e9`. Final validation combines the exact
feature checks in [build run 37855047291](https://github.com/comparativechrono/workbench/actions/runs/37855047291)
with the successful [frozen-archive recheck 37857029068](https://github.com/comparativechrono/workbench/actions/runs/37857029068).
The latter corrects only validators, at `016b14109c50dcce36e635586781b5bb5e19d79b`;
application bytes were not rebuilt. Earlier failures remain recorded below.

- [Windows Starter test download](https://github.com/comparativechrono/workbench/actions/runs/37855047291/artifacts/11583866299): **17,817,278 bytes** for the inner ZIP.
- [Complete candidate bundle with matching source](https://github.com/comparativechrono/workbench/actions/runs/37855047291/artifacts/11583697066).
- [Final combined validation evidence](evidence/reference-management-0.15.0-final-validation-2026-10-08.json).

Actions downloads are temporary (retained until 2026-11-07) and may require
GitHub sign-in. The Starter artifact wraps the application ZIP in another ZIP;
extract both layers and open `native-workbench/NativeWorkbench.exe` in a fresh
test folder. This is not a published release or an updater.

| Inner archive | SHA-256 |
| --- | --- |
| `native-workbench-0.15.0-starter-windows.zip` | `ce3bcc9c5634dd90f024ecf20f0308a144641c67e0c11c205501518773f6a4c2` |
| `native-workbench-0.15.0-source.zip` | `0b501b428cbe88b6d3b7cb601f5aa88e029cc20a1ac9903ff4663fee142b1df2` |

The frozen Linux build passed **430 checks with four skips** across 29 invocations,
including five specifically named frontend-boundary checks. Both Windows paths
passed **nine live reference** and **ten management/interface** checks. All 22
new reference screenshots were reviewed at 96 DPI. The successful recheck ran
all 15 Windows source suites: **274 passes and four explicit skips per path**,
plus all **11 batch/index/interface checks**. Other exact frozen gates passed
14 process/resource, five readiness, 12 recovery, seven library, 32 workspace,
independent pack import/science and three separately instrumented transport checks.
Independent downloads verified hashes/CRC, 710 matching source files, all 85 core
files, and unchanged published packs/private runtime/32-pack profile/trust.

The four Windows skips are the Linux-only core adapter, unavailable Windows
stock-CWL replay, POSIX diagnostics symlink case and privileged index symlink
case. They are not passes. Stock report-only CWL replay passed separately on
Linux; no scientific Windows–Linux parity claim follows. Hosted checks do not
replace representative-PC, high-DPI, trackpad or institutional acceptance.
No 0.15.0 updater, published-baseline upgrade or public release was performed.
Published **0.11.0** and `main` remain unchanged; the broader roadmap remains open.

## Development and retained earlier evidence

The owner asked to implement the remaining accepted groups one at a time.
This first group covers resumable reference downloads, importing local references,
safe library relocation and an additional provider. See the
[feature contract](reference-management.md). The previous conditional release
request was not satisfied: the broader roadmap is not yet complete. This new
request authorizes development, not publication.

Work is on `feature/reference-management`, based on
`38917349449ce56a45d3e0f4f41b7d2a38621c6d` from the unmerged 0.14.0 review
branch. App version 0.15.0 separates this work from that frozen candidate.
Published 0.11.0, immutable pack bytes and production catalogue/profile/trust
remain unchanged. No merge, release or updater has been performed.

The [local source record](evidence/reference-management-0.15.0-local-source-2026-10-08.json)
has **422 passed, six skipped** across 28 suites. Four skips are Windows-only;
two need the external stock CWL runner, which the candidate workflow installs.
An initial local harness applied isolated mode to seven historical suites whose
helper imports require ordinary invocation; their import failures and successful
documented invocations are retained separately. No application change was used
to conceal those harness failures.

An independent critical audit reran 82 overlapping source checks, all passing.
It exposed and verified fixes for orphan checkpoint files, publication-before-
registration crash recovery, malformed pending IDs, cancellation boundaries and
NCBI annotation wording. Existing reference tests also exposed a run-startup
error path introduced by earlier resource-policy work; lifecycle checks now run
before graph interpretation and a missing graph gets a clear validation error.
The native desktop compiled with the pinned toolchain and strict warnings.
Final UI review also fixed stale import confirmation returning after form edits
and a server-list refresh; the native gate exercises edit, close/reopen and a
fresh explicit preview. One local strict-build attempt failed on an unknown
temporary object-file type; its identical retry passed. The cause was not
established, and the clean CI build remains required.

[Live Linux NCBI checks](evidence/reference-management-0.15.0-ncbi-linux-2026-10-08.json)
discovered and downloaded yeast `GCF_000146045.2` genome, GTF and protein files,
independently verifying upstream MD5, gzip integrity and compressed/expanded
SHA-256. The observed annotation was SGD R64-5-1, dated 2026-07-10. This is a
retrieved annotation snapshot, not an immutable assembly annotation release.

The first exact candidate, commit `5592604a101fdfc2db4f2055399e7e54f7684b21`,
failed [run 37853140376](https://github.com/comparativechrono/workbench/actions/runs/37853140376).
Its [source checks](evidence/reference-management-0.15.0-initial-source-2026-10-08.json)
passed 424 with four Windows-only skips, including the stock CWL report replay;
its [archive audit](evidence/reference-management-0.15.0-initial-archive-audit-2026-10-08.json)
verified exact identity. [Both native paths](evidence/reference-management-0.15.0-initial-windows-2026-10-08.json)
exposed three defects: ordinary versus extended Windows default-destination paths,
NCBI Find files sending an accession instead of the lookup selector, and an
installation check misclassifying pure URL parsing and requiring explicit rules
for the new reference modules. Those defects were corrected for the rebuilt candidate. The source workflow
now checks the exact runtime-module inventory and rejects disallowed networking,
while preserving the narrow pure-parser and exception-only imports.

Each path passed six live Ensembl and six management/host checks before failure.
All existing configured native regression gates passed. The Windows source step
stopped after provider and manager suites: 42 passed, one error, and the remaining
12 suites were not executed. Partial results are not acceptance. Exact packaged
rechecks and final screenshot review remain required. Existing 0.14.0 passes apply
only to its named artifacts.

Remaining groups after this set include curated workflows/results improvements,
executable signing and institutional deployment, scientific Linux CWL profiles,
realistic Windows–Linux benchmarks and representative-machine acceptance.
Existing SDK templates, validators, signed catalogues and offline pack imports
are already present. Do not describe that entire developer toolkit as absent.

The second candidate, `8ff5cf18b957905bbb92a0a08e21a6871ae49712`,
passed all nine live-reference checks in both Windows paths but was also rejected
in [run 37854004440](https://github.com/comparativechrono/workbench/actions/runs/37854004440).
Its [recheck evidence](evidence/reference-management-0.15.0-rechecks-2026-10-08.json)
retains 430 source passes/four skips, successful archive verification and the
newly reached Windows failures. Native NCBI discovery worked; the validator had
incorrectly required Download to enable before selecting a file. A later service
source check exposed a short-versus-resolved Windows default-path comparison.
Screenshot review also found the GUI initially displayed the old default folder
after relocation. All three are corrected for another exact-package recheck.

The frozen application candidate is now
`46bbb39dda2cc5bb08c30af494cb340f976acf3b`, from
[run 37855047291](https://github.com/comparativechrono/workbench/actions/runs/37855047291).
Both Windows paths passed **nine live reference checks and ten reference-management
checks**, including all native interactions. All 22 reference captures were
reviewed at 96 DPI with no blocking visual defects.
[Source](evidence/reference-management-0.15.0-frozen-source-2026-10-08.json),
[archive](evidence/reference-management-0.15.0-frozen-archive-audit-2026-10-08.json)
and [native evidence](evidence/reference-management-0.15.0-frozen-windows-2026-10-08.json)
retain the exact identities and scope. The overall run still failed: one source
mock compared short and canonical root spellings, and the ordinary batch validator
interacted with the search control during an asynchronous Tools transition.
The next recheck corrects only these validators and reuses the same archived
application bytes; ten unreached Windows source suites must also execute.
