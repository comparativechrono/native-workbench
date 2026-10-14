# Recovery, resources and portable projects: 0.14.0 handover

Status on 2026-10-08: **implementation and recorded hosted validation complete;
ready for tester review; unpublished**.
The owner requested the final accepted implementation tranche. This is not
authorization to merge or publish a release.

Development branch: `feature/recovery-projects`, based on
`9f5cd4c88634b4cab04cec66b9e43e93e1db0e17` from the unmerged 0.13.0 review
branch. Published 0.11.0 and production packs/profile/trust remain unchanged.
The [feature guide](recovery-projects.md) records contracts and scope.

## Final candidate

Final packaged source is `0e2d5cbcbf1786d6e1723f8466b4b6b94da04802`, tree
`23d18a92094331614b7846d15c6f91f751cd5964`.
[Run 37842857764](https://github.com/comparativechrono/workbench/actions/runs/37842857764)
completed successfully: build and both native Windows jobs. Later handover-only
commits do not change these packaged bytes or imply new application execution.
[Draft PR #9](https://github.com/comparativechrono/workbench/pull/9) is stacked
on #8, which is stacked on #7; all three remain unmerged and unpublished.

| Final artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Starter | 17,770,112 | `4ed5b3827cc0c0f4f34b8b9405458d4f15e058147b549afa383fb3f8b81f531f` |
| Matching source | 47,450,828 | `37ca5b666808e129c1b91bf826dad8b451a892cc76059b377ed9e9e38f6d23ac` |
| Existing align 0.4.1 candidate pack | 575,862 | `3a08cf061f0b62c5502d1420115db3fcae2b04bf695ad3cfd1c3063de0fafa02` |

[Download the Starter candidate](https://github.com/comparativechrono/workbench/actions/runs/37842857764/artifacts/11578890349)
or [complete candidate/source bundle](https://github.com/comparativechrono/workbench/actions/runs/37842857764/artifacts/11577594714).
These temporary Actions artifacts are retained for 30 days and may require
GitHub sign-in. Extract the outer ZIP, then the inner Starter ZIP; launch
`NativeWorkbench.exe`. They are not published release downloads.

The [final source record](evidence/recovery-projects-0.14.0-final-source-2026-10-08.json)
contains **289 passed, four skipped, zero failed/error** across 20 suites.
It includes actual stock `cwltool` report-only execution after moving the project
and deleting original inputs; it does not establish Linux scientific parity.

The [final Windows record](evidence/recovery-projects-0.14.0-final-windows-2026-10-08.json)
binds the exact Starter and native executable hashes. Each ordinary/spaced path
passed **12 recovery/resource/project/interface, 11 batch/queue/index, 14 native
resource, five readiness/diagnostic, seven library and 32 workspace checks**.
Independent align 0.4.1 ZIP import/science and three separately instrumented
transport checks also passed. Windows source suites separately passed
**126 checks with three skips** per path.

The new gates establish completed-step reuse and descendant invalidation,
preserved original results, explicit CPU admission and cancellation, offline
project movement and same-byte mapping, provenance, malformed archive rejection,
and native Resources/Restart/Projects interactions. Native results retained
202 alignments and the expected homozygous SNP; concurrent branches each retained
80,800 alignment records. These are known-answer fixtures, not a benchmark.
Abrupt termination uses a separately instrumented callback barrier; service bytes
are restored before exact-host restart. The report labels this distinction.

The [final independent archive audit](evidence/recovery-projects-0.14.0-final-archive-audit-2026-10-08.json)
verified four downloaded transport sizes/digests and ZIP CRCs, both inner archive
hashes, **689 exact-commit source files, 82 core files and 28 runtime Python
modules**. All 143 published pack files, 39 private runtime files and production
32-pack profile/trust identities are preserved. The standalone align ZIP was
checked by the native import gate; this separate archive audit does not claim
an independent download of that ZIP.

All six final screenshots per path were reviewed at 96 DPI, with an independent
reviewer for the spaced path. The export button now fits and the restart capture
visibly shows completion. Real Windows short-path export and physical scratch
identity checks pass. Earlier failed observations below remain historical evidence.

## Remaining acceptance and release work

No 0.14.0 updater, published-baseline upgrade or release gate was built or run.
Live reference downloads and Full online setup were not rerun by this candidate
workflow. Published 0.11.0 remains unchanged. Representative Windows machines,
high-DPI/physical trackpad/multi-monitor observations, institutional approval,
realistic Windows–Linux benchmarks and explicit release acceptance remain.

The existing library validator logged ignored control-enumeration callback
exceptions while all seven functional assertions passed; complete enumeration
is not established. A minor inherited queue detail message retains
“Verifying queued plan” after the row/status/counters correctly show completion.
Settled screenshots do not establish every temporal rendering case.

CPU budgets govern admission, not OS CPU limits; unknown steps run exclusively.
Restart uses declared file products and rejects unsupported descriptor/directory
state. Portable projects retain exact pins without carrying or downloading tools;
generic `file` workflow inputs and directory/descriptor inputs remain unsupported.
The further accepted roadmap features are not declared complete by this milestone.

## Earlier candidates and failed observations

[Draft PR #9](https://github.com/comparativechrono/workbench/pull/9) is stacked
on #8. The **initial** frozen application source is
`cd0ed848fd9d9c8728b0d83991511a348c13719e`, tree
`af1eda87edb7c91f19fbeff0d3ed95972fa712e9`, built in
[run 37840523641](https://github.com/comparativechrono/workbench/actions/runs/37840523641).

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Starter | 17,769,934 | `f5b347a1e379f48bd5b72950bc331f25be39a9764f6342ab066f5cb62bfe1837` |
| Matching source | 47,431,453 | `7f4394c485532815954cbebcb51f0902522af1521a2e48f04c32cb092f78bfc8` |
| Existing align 0.4.1 candidate pack | 575,862 | `3a08cf061f0b62c5502d1420115db3fcae2b04bf695ad3cfd1c3063de0fafa02` |

The [source gate](evidence/recovery-projects-0.14.0-source-2026-10-08.json)
passed **287 checks with four Windows-only skips**. This includes actual stock
`cwltool` replay of a relocated report-only project after deleting its original
inputs. It does not establish Linux scientific parity. Strict pinned native
compilation passed. The [archive audit](evidence/recovery-projects-0.14.0-archive-audit-2026-10-08.json)
verified 684 source files, 82 core files, 28 runtime Python modules and unchanged
143 published pack files, 39 private runtime files and production profile/trust.
Two incomplete local transport copies were rejected; new retrievals matched
complete official sizes/hashes and ZIP CRCs. Their cause is not established.

The [initial Windows record](evidence/recovery-projects-0.14.0-initial-windows-2026-10-08.json)
retains a **failed** run. In each path, existing workspace 32, library seven,
batch/index 11, readiness five and resource-accounting 14 checks passed, as did
independent pack import/science and three separately instrumented transport
checks. The new recovery gate stopped before a check passed: its validator
expected three steps instead of the Starter's four native steps plus a report.
The real review correctly offered four reuse decisions and report regeneration.
The isolated Windows source gate also stopped at a missing test-helper import.

At that stage only validators and test imports were corrected. The
[frozen recheck workflow](../.github/workflows/native-recovery-recheck.yml)
pins the same Starter and both executable hashes, refuses application/build
changes and records its separate validator commit. The corrected exact-native gate passed **12 checks per path** in
[run 37841697478](https://github.com/comparativechrono/workbench/actions/runs/37841697478).
A source-only follow-up confirmed physical scratch ownership but exposed
Windows short/long-path alias defects in portable metadata and one further
lexical-path test assumption. Independent screenshot reviews also found a
clipped export confirmation label and a queue capture taken before UI polling
showed completion. The [recheck record](evidence/recovery-projects-0.14.0-rechecks-2026-10-08.json)
retains these failed runs and separates the passing native feature gate.

The portable exporter now canonicalizes explicit file identities while retaining
raw graph aliases for metadata tokens; duplicate aliases and wrong hashes are
rejected. Two new regressions cover this. The native caption is shortened, and
the validator now waits for displayed queue completion and tests actual Windows
short-path project export. **These application changes required the final build
and exact-package validation above; earlier passes were not transferred.**
The old frozen recheck workflow remains pinned to its historical archive and
must not be used to imply a pass for the rebuilt candidate.

Representative Windows machines, high-DPI/physical trackpad observations,
institutional approval, realistic Windows–Linux benchmarks and release/update
validation remain separate work. The accepted roadmap's further features are
not declared complete by this milestone.
