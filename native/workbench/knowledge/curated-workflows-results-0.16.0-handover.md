# Curated workflows and results: 0.16.0 handover

Current status: the owner subsequently authorized publication. The corrected final
0.16.0 archives are published and validated in the
[release handover](curated-workflows-0.16.0-release-handover.md). The candidate
identities and unpublished-only authorization below are preserved as historical
records and do not describe the current release.

Status on 2026-10-09: **implemented and validated within the recorded hosted scope; unpublished review candidate**.

Review: [draft PR #11](https://github.com/comparativechrono/workbench/pull/11), branch `feature/curated-workflows-results`, based on reference-management head `f45622f8915a3fa80c0904fcd97c216e0b5980f3`.
The preceding [draft PR #10](https://github.com/comparativechrono/workbench/pull/10) and [draft PR #9](https://github.com/comparativechrono/workbench/pull/9) remain unmerged.
Initial repository and remote inspection found no saved implementation or version decision for this set. **0.16.0** was assigned to distinguish these bytes from the frozen 0.15.0 reference-management candidate. Published **0.11.0** remains unchanged.

## What changed

- Two local synthetic training workflows: alignment with QC, and variant calling. The catalogue explains inputs, expected answers, exact versions/manifest pins and missing dependencies. Loading requires confirmation and does not execute or download anything.
- Native searchable results show sample identity, recorded SAMtools/BCFtools measurements, provenance and raw-output paths. Measurements require matching frozen-plan, output-record and file hashes; changed/missing evidence is explicitly unavailable.
- Failed preparation retains the submitted analysis name and actual cause, with corrective guidance. No sample QC pass thresholds or clinical conclusions are inferred.
- Existing standalone/workflow behavior, reference management, queues, reusable indexes, restart and portable projects are preserved. Published packs and production profile/trust bytes are unchanged.

See the [feature contract](curated-workflows-results.md). Open **File → Curated workflows...** to review training inputs; use **Results** to search recorded analyses.

## Exact tested candidate and downloads

Tested source commit: `7a9aca71ddd4816b51dbe693873f42fa50a6b746`.
All three jobs passed in [run 37941573921](https://github.com/comparativechrono/workbench/actions/runs/37941573921).
Subsequent review-branch changes only add documentation/evidence; they do not change the tested application. The matching source archive is bound to this tested commit.

- [Windows Starter download](https://github.com/comparativechrono/workbench/actions/runs/37941573921/artifacts/11620934453).
- [Complete candidate and corresponding source](https://github.com/comparativechrono/workbench/actions/runs/37941573921/artifacts/11621489330).
- [Ordinary-path reports and screenshots](https://github.com/comparativechrono/workbench/actions/runs/37941573921/artifacts/11622060614).
- [Spaced-path reports and screenshots](https://github.com/comparativechrono/workbench/actions/runs/37941573921/artifacts/11621414963).

These are temporary Actions downloads, retained until **2026-11-08**, and may require GitHub sign-in. Extract the artifact container to obtain the named inner ZIP. No release asset or updater was published.

| Inner archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-0.16.0-starter-windows.zip` | 17,846,720 | `1ff91bdb386171aeb166fec4fce4ad23e31287dc9e9695167db113994f416131` |
| `native-workbench-0.16.0-source.zip` | 47,765,332 | `8fc6a510d178632f12259a3e6e6b115c2c6c40562906eecc5a5557a7a9a361de` |
| `native-workbench-pack-align-0.4.1.zip` | 575,862 | `3a08cf061f0b62c5502d1420115db3fcae2b04bf695ad3cfd1c3063de0fafa02` |

## Recorded validation

The [combined record](evidence/curated-workflows-results-0.16.0-final-validation-2026-10-09.json) binds logs, reports, captures, gate scripts, native executables and archives to the tested commit.

| Scope | Result |
| --- | --- |
| Strict desktop/bridge compilation; portable native JSON/list-selection/framing regression | Passed |
| Linux source selection | 474 passed, four Windows-only skips |
| Windows source selection, each path | 318 passed, four explicit skips |
| Curated science/results/native interface, each path | All 11 checks passed |
| Preserved native gates, each path | Live references 9; reference management 10; resource accounting 14; readiness 5; batch 11; recovery 12; separate instrumented transport 3; library 7; workspace 32; independent pack import/scientific check passed |
| Screenshot review | Six new-feature captures per path at observed 96 DPI; [visual record](evidence/curated-workflows-results-0.16.0-final-visual-review-2026-10-09.json) |
| Independent downloaded archive audit | Passed; [audit record](evidence/curated-workflows-results-0.16.0-final-archive-audit-2026-10-09.json) |

Both workflows ran through the exact bundled native tools offline, preserving 202 mapped properly paired records; variant calling produced known `starter:1351 G>A GT=1/1` truth. Checks covered persisted search, changed-output rejection/restoration, missing exact dependencies without substituting align 0.4.1, actual missing-input failure and native failure guidance.

The archive audit verified four transport sizes/digests/CRCs, inner Starter/reassembled source, all **734** current source files against the exact Git commit, all **87** core files and **33** Python runtime modules. All **143** published pack files and **39** private-runtime files are preserved, along with the 32-pack setup profile and production trust metadata. The independent align ZIP was validated by the native CI import gate; the local audit checked its declaration/bundled content rather than downloading the aggregate artifact again.

Linux skips are two native held-reader cases and two native diagnostic path cases, which run on Windows. Windows skips concern the separate portable-Linux scientific adapter, stock-CWL replay, a POSIX symlink case, and a Windows symlink case requiring unavailable privileges. These are listed per suite rather than counted as passes.

The legacy library capture helper emitted ignored ctypes control-enumeration warnings (four ordinary, two spaced); functional library assertions passed. No exhaustive control-enumeration claim is made. New curated/results captures were separately inspected. Long detail panes and the graph intentionally use scrollable viewports.

## Rejected attempts retained

- `1226947256e8d31124a45227d22933c5d4a6b08e`, [run 37938879718](https://github.com/comparativechrono/workbench/actions/runs/37938879718): Windows output checks incorrectly compared path-stat creation time with handle-fstat change time. The fix retains cross-API identity/size/mtime and same-API timestamp checks, with five new regressions. The live-reference gate also needed its explicit supported-version list updated. [Source](evidence/curated-workflows-results-0.16.0-initial-source-2026-10-09.json), [Windows](evidence/curated-workflows-results-0.16.0-initial-windows-2026-10-09.json), [audit](evidence/curated-workflows-results-0.16.0-initial-archive-audit-2026-10-09.json).
- `23cf175cd03baededcc5a97ea597f55f68d5c9ae`, [run 37940096315](https://github.com/comparativechrono/workbench/actions/runs/37940096315): both paths passed all eight curated backend/scientific checks, but catalogue creation dereferenced absent rows before its first response. Both dialogs now use typed empty arrays and a tested selector for missing/stale/empty selections. [Second attempt](evidence/curated-workflows-results-0.16.0-second-attempt-2026-10-09.json), [audit](evidence/curated-workflows-results-0.16.0-second-archive-audit-2026-10-09.json).

Earlier failed downloads/audit preparation errors remain recorded; none were accepted as valid archives. Previous candidate passes were not transferred to rebuilt bytes.

## Remaining limitations

Representative Windows-PC, high-DPI, multi-monitor and physical-trackpad acceptance remain outstanding. Small synthetic truth is not biological/clinical validation or a realistic capacity benchmark. Scientific Linux CWL validation, realistic Windows–Linux benchmarking, executable signing/institutional deployment and release/updater validation remain separate work. Report-only stock-CWL source checks do not satisfy the scientific Linux requirements. No merge, tag, release or updater is authorized by this set.
