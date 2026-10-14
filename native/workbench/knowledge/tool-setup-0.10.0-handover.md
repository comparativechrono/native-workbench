# Native tool setup 0.10.0 handover

Snapshot: **2026-10-07**. **0.10.0 is published** as a development prerelease at
[app-v0.10.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.10.0).
Release **405745578**, published **2026-10-07T12:35:21Z**, promotes the exact
accepted candidate archives unchanged. [PR #3](https://github.com/comparativechrono/workbench/pull/3)
and the release tag point to `2e474345dff195b860df39fdde263c840dd1fba3`; packaged
application source remains `5a390acd8440856e3f4e32de237322a18bb82d7e`.
Published 0.9.0 and all existing pack releases remain unchanged. The release
offers native Full (recommended), Starter and Custom setup while retaining
independent packs and Manage tools. Its updater supports the published 0.9.0 baseline.

The [publication record](evidence/tool-setup-0.10.0-publication-2026-10-07.json)
and [independent public audit](evidence/tool-setup-0.10.0-public-downloads-2026-10-07.json)
confirm all **ten public assets**, four ZIP CRCs and both checksum manifests.
All seven original candidate files, including the application/source/updater
archives, match the accepted bytes. Source/build companions retain their
creation-time pending notes; the later final validation/publication records
supersede those notes without replacing the immutable archives.

The protected catalogue publishing workflow and
[owner setup guide](../publishing/catalogue-signing.md) were merged into `main`
through [PR #4](https://github.com/comparativechrono/workbench/pull/4). The owner
then configured the signing key/fingerprint and started the successful
[production publication run](https://github.com/comparativechrono/workbench/actions/runs/37617540915).
The signed 32-pack catalogue is published and independently verified. Its public
source is bundled into the new exact candidate below. Native setup, workspace,
References, results/CWL/DAG/icon and 0.9.0 upgrade gates passed in both Windows
paths. Live production Full passed four checks per path, and the separate
isolated-fixture all-pack gate also passed four; all six candidate jobs succeeded.
The earlier empty-trust candidate retains its separate historical identity.

## Production-trust candidate, 2026-10-07

Application source is **`5a390acd8440856e3f4e32de237322a18bb82d7e`**, frozen once in
[run 37618824677](https://github.com/comparativechrono/workbench/actions/runs/37618824677).
Candidate artifact **11481160484** contains these exact archives; bounded
transport artifacts reassemble the same source without rebuilding.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| Starter | 17,028,340 | `659a08911cec65b8dc1ce0dd9f47fea25350a39b619c7f0aea663bae71a871ae` |
| Update from 0.9.0 | 12,880,361 | `63d96f514711d0604b6fbfe940a38bfad73900285ec13e75f95397f0d012eacf` |
| Matching source | 46,740,582 | `918adabf39c0f0cbd551b2a30d523f72135be67fe4232a9c8c54ffa6e611133b` |

| New exact-candidate gate | Actual result |
| --- | --- |
| Build source checks | 152 passed, one native-Windows-only skip; no failures. Separate Windows pack-manager suite: 42 passed. |
| Native setup, each path | 13 passed; native first-run/profile controls, signed fixture download/cancel/retry/integrity failures, persisted state and offline science. |
| Native workspace, each path | 32 passed. |
| References, each path | Eight passed; all five pinned yeast products, integrity/cancellation, compatible native selection, offline reuse and provenance. Optional References updater helper was not requested; it is not a pass. |
| Results/CWL/DAG/icon, each path | Nine passed. |
| Upgrade from published 0.9.0, each path | 13 passed; 72 core files verified and 203 existing files unchanged, including optional tools, saved/pinned state, references and actual results. Repeated update and offline scientific/CWL execution passed. |
| Live production Full, ordinary and spaces | Four passed per path using the unchanged bundled owner trust. All 32 exact published pins installed; BED inputs available; offline reopening and 202-record alignment/BAM truth passed. No skipped/unrun production checks. |
| All-pack fixture gate | Four passed; isolated test-only trust, all 32 packs and offline 202-record truth. Its production-trust omission remains explicit and is covered separately by the production gates above. |
| Independent static archive audit | Six grouped checks passed: all archives/transport hashes and CRCs, 72 core files, 572 Git-matched current source files, 143 unchanged Starter pack files, 57 updater inventory files and 11 exact replacements. Packaged production source matches the reviewed owner identity. |

See the [new validation record](evidence/tool-setup-0.10.0-validation-2026-10-07.json),
[archive audit](evidence/tool-setup-0.10.0-artifact-audit-2026-10-07.json) and
[acceptance record](evidence/tool-setup-0.10.0-acceptance-2026-10-07.json) for final
promotion status. Source/GUI/science counts overlap and are not additive unique
checks. No new physical tester session is implied by this CI validation.

## Earlier exact candidate and checks

Application source is `8cee60655fe726e9d424ddf1b2874728235828ca`.
[Candidate run 37537256084](https://github.com/comparativechrono/workbench/actions/runs/37537256084)
built the application once. Gate-only corrections at
`b2299886b049c4a9a495cb80620be9c07ec1fd70` were tested in
[run 37538868326](https://github.com/comparativechrono/workbench/actions/runs/37538868326)
against those same archive bytes. Later documentation and validator commits do
not change the candidate's application identity.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| Starter | 17,027,658 | `cab50ae315fa2e281844223fc862d7c45565b9c5557005236a7baf3fd13c0cd7` |
| Update from 0.9.0 | 12,879,332 | `fdc4a1a15e83419c78e2dd4b88dfc734a7be448d5760f39305c02735cf7c2e7c` |
| Matching source | 46,681,070 | `23765a77a30ae24a3a869b1bc50585010b041b2612c41a67478109d04d059886` |

These are development artifacts, not public release downloads. The original
artifact is **11446932575**. The verification run splits transport into bounded
artifacts and reassembles the source without rebuilding or changing any archive.
GitHub Actions artifacts have limited retention; the committed hashes, reports
and workflow recipes remain the durable record.

The following checks were performed during this implementation, rather than
inferred from historical releases:

| Check | Result and scope |
| --- | --- |
| CI source tests | 152 passed, one native-Windows-only skip, zero failures. The separate Windows pack-manager suite passed all 42 tests, including that filesystem case. |
| Native setup, each Windows path | 13 passed. First-run/profile controls, totals, minimum size/scrolling, offline Starter/reopening, persisted state, signed fixture downloads, cancellation, restart/retry, invalid hashes/signatures, existing-data preservation and offline 202-record alignment/BAM truth. |
| Workspace, each Windows path | 32 passed on the exact candidate, including native workflow interactions and scientific execution. |
| References, each Windows path | Eight passed: live pinned yeast discovery/downloads for all five products, compressed/expanded hashes, cancellation, native compatible selection, network-denied reuse and reference provenance in methods/CWL. The helper's optional updater was not requested; it is not counted as passed. |
| Results/CWL/DAG/icon, each Windows path | Nine passed in the corrected gate, including independent execution of embedded CWL runners, known variant truth, native forward/backward connections and actual icon resources. |
| 0.9.0 upgrade, each Windows path | 13 passed. All 72 target core files verified; 203 existing files preserved, including an optional pack, settings/pinned workflow, references and actual results. Repeat update and post-update offline scientific/CWL execution passed. |
| All-pack Windows coexistence | Four passed after downloading the 29 missing real pack archives. All 32 exact pins installed; BED became a usable workflow input, all packs reopened with networking denied and offline analysis preserved 202 expected alignment/BAM records. Isolated test-only catalogue trust; this did not validate the then-unavailable official signed feed or every pack's scientific operation. |
| Independent archive audit | Six grouped assertions passed: all archive hashes/sizes/CRCs, 72 core files, 558 source files matched to the candidate Git commit, 143 unchanged Starter pack files and 56 updater files including ten exact replacements. No Windows execution or independent executable rebuild is implied by this static audit. |

Counts describe separate suites and include overlapping scientific checks; do not
sum them as unique assertions. Native paths were ordinary and contained spaces
on `windows-2022`. Screenshots were reviewed for readable setup controls at
normal/minimum size and routed forward/backward canvas edges. These still images
do not establish every physical display/trackpad configuration.

Network-denied offline gates use a Python audit hook rejecting socket operations
in the private host. They do not install an OS firewall or claim to block network
access from every native subprocess. The scientific fixtures use local inputs.

The [sanitized validation record](evidence/tool-setup-0.10.0-validation-2026-10-06.json)
retains report hashes, exact checks, failures, omissions and run identities. The
[independent archive audit](evidence/tool-setup-0.10.0-artifact-audit-2026-10-06.json)
records the downloaded bytes. Earlier local packaging evidence is a different
working-tree build and must not be substituted for this candidate.

## Initial failures and corrected validators

The first native matrix failed setup in both paths. Its validator checked only
whether Continue was enabled immediately after posting Install, then clicked
before observing operation completion. Failure cleanup also raced the pending
dismissal with application close and obscured the original timeout. The corrected
gate requires the completed-operation text and waits for normal workspace editing
controls to become enabled; failed tests retain their original error and captures.

The ordinary-path results fixture also selected a receiver immediately after
dropping a connection. Its screenshot already showed the correct edge with the
producer still selected. The corrected gate waits for the producer's changed
"Used by" text before selecting the receiver, retaining the original "From"
assertion. Both corrected suites passed in both paths with unchanged application
bytes. The first failures remain evidence; the initial workflow is not relabelled
as successful. One superseded verification run was cancelled after a final
validator-readiness correction; the completed run above is the authoritative rerun.

## Production catalogue and completed release

The reviewed 32-pack download set is **3,799,806,535 bytes** across all archives,
or **3,795,572,848 additional bytes** for the 29 packs missing from Starter.
Published pins, licensing and source companions remain unchanged. The earlier
[preparation record](evidence/setup-catalogue-preparation-2026-10-06.json) remains
historical evidence; the production workflow freshly reacquired the same files.

The earlier candidate's source list was `[]` because no reviewed production
source existed at its build time. Its fixture key was deliberately isolated and
has not been promoted into production trust. Infrastructure
[PR #4](https://github.com/comparativechrono/workbench/pull/4), reviewed source
`6e973db73953a5ef1f7d221a79ce94887f2fb366`, passed **56 isolated source tests** in
[run 37583926483](https://github.com/comparativechrono/workbench/actions/runs/37583926483).
That source-only gate did not establish production publication or Windows
application validation, and its historical scope remains unchanged.

The owner subsequently created the signing key locally on Windows, supplied its
public fingerprint, configured GitHub and started
[run 37617540915](https://github.com/comparativechrono/workbench/actions/runs/37617540915)
on reviewed main commit `9f82aa5d1d9a0a372fc0492b7dff448694af8813`. Both jobs
completed successfully. The run repeated **56 source tests with no failures or
skips**, freshly downloaded and fully checked all 32 archives, signed the
catalogue, and verified anonymous publication on the first attempt. This records
the successful protected workflow use; administrative environment protection
settings are not exposed to the connector for separate inspection. No private
key was read by the agent or included in repository/public artifacts.

| Production identity | Value |
| --- | --- |
| Published at | `2026-10-07T11:58:34Z` |
| Catalogue commit | `0048c4e3644aae7ed172d804fff0981982510e7b` |
| Owner-confirmed public fingerprint | `8d2093f9fafd71de56fea2038faeb2efa0964767d3235430b06428132cdc8505` |
| Signed catalogue SHA-256 | `bf4789075e1aaad3d4ef158f879fc3ff94a869985d6324b0e594f69a522a739d` |
| Public source SHA-256 | `9f4ef018e03ea8a27251927fe59d4656b7619b227814497b4f66947269ee297b` |
| Immutable history | `history/20261007T115834Z/` at the catalogue commit |

The [independent production audit](evidence/catalogue-production-2026-10-07.json)
verified nine anonymous documents: current catalogue/source/report, four
commit-pinned history files, and exact source lock/profile. All document hashes
and 32 pack pins agree with the run receipt and preparation evidence. Both the
application verifier and an independent cryptography/OpenSSL implementation
accepted the 3072-bit RSA signature and owner fingerprint. The catalogue Git
tree contains exactly seven intended public JSON files; first publication has no
previous catalogue history to compare. Two evidence ZIP hashes and CRCs were
also checked. The separate audit did not redownload the multi-gigabyte archives;
it reviewed this run's complete archive/member validation evidence.

The reviewed public source is bundled into candidate `5a390acd`; its completed
native regression and live production Full gates passed as recorded above.
The established immutable-artifact release workflow promoted the exact validated
archives and verified all ten public downloads. Independent anonymous download
verification also passed. The earlier empty-trust archive was not promoted.
Catalogue/public-download auditing did not execute Windows; the accepted candidate
run supplies the separate native evidence.

Cancellation/retry retains completed packs; an unfinished archive restarts its
download. Abrupt process termination can leave unowned staging directories, which
are never reported as installed tools or deleted speculatively. Scientific
databases and references remain separate from pack setup. See the
[feature guide](tool-setup.md) for the stable implementation contract.
