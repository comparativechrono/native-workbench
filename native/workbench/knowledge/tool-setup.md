# Tool setup: Full, Starter and Custom

**Current patch: [0.10.1](https://github.com/comparativechrono/workbench/releases/tag/app-v0.10.1), 2026-10-07.**
The package list remains scrollable during refresh/install, with checkbox edits
locked while active. Repeated header redraws and navigation resets were corrected
and verified against the published 0.10.0 baseline in both native Windows paths.
See the [patch handover](tool-setup-0.10.1-handover.md) for exact evidence and limits.

A download failure now names the pack and distinguishes HTTP/proxy/TLS/DNS or
connection causes from local storage/write failures. Record that exact message,
resolve the named cause, then use **Retry**. Completed packs remain installed.
The original tester-PC failure remains undiagnosed; do not treat successful
hosted downloads as proof about that machine's network or storage.

**Initial feature release: [0.10.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.10.0), 2026-10-07.** The user approved this direction on
2026-10-06. Published 0.9.0 and all existing pack releases remain unchanged.
The earlier empty-trust candidate passed the native checks recorded in the
[0.10.0 handover](tool-setup-0.10.0-handover.md). As of **2026-10-07**, the official
signed 32-pack catalogue is published and independently verified. Its reviewed
public source is bundled in candidate `5a390acd`. Exact-package native setup,
workspace, References, results/CWL/DAG/icon and 0.9.0 upgrade checks passed in
ordinary and space-containing Windows paths. Live production Full passed four
checks in each path using the bundled owner trust and all 32 exact pack pins.
All six candidate jobs succeeded. The accepted archives were published unchanged;
[independent downloads](evidence/tool-setup-0.10.0-public-downloads-2026-10-07.json)
verified all ten public assets, four ZIP CRCs and both checksum manifests.

## Installing tools

Open **Tool setup** from the native application. A new installation offers it at
first launch; an existing installation can open it when the user chooses. Merely
opening the application or this window does not download anything.

| Choice | What it does |
| --- | --- |
| **Full — recommended** | Selects all 32 packs in this application's reviewed setup profile. Already installed exact versions are retained. |
| **Starter** | Keeps the three bundled packs: minimap2 alignment, SAMtools and BCFtools. No pack download is needed. |
| **Custom** | Keeps Starter and downloads the selected additional tools. |

Refresh the official catalogue to verify the available versions, review the
missing tools and download size, then choose Install. The setup window shows
progress for the current pack and the complete selection. Downloaded archives
must pass the existing pack manager's signed-catalogue, SHA-256, safe-path,
manifest, complete-file-inventory and compatibility checks before publication.

Cancel stops the current cancellable transfer; a short final publication step
must finish first. Completed packs remain installed. Failed, cancelled or
interrupted selections can be retried, including after reopening Workbench.
Retry retains the chosen versions, archive hashes, manifest hashes and publisher
key. The unfinished pack may need to download again; this is completed-pack
reuse, not byte-range resume of a partial archive. An error does not remove
working tools or silently change the selection to a newer pack.

Graceful cancellation removes the current temporary download/extraction. An
abrupt process termination can leave temporary installation directories; retry
does not treat those files as installed tools or delete directories whose live
ownership it cannot establish.

Installed tools remain available offline. **Manage tools** and offline pack
import remain available for future official packs and packs written by other
developers. Full is a convenient selection of independent packs, not a closed
list of what Workbench can run. References and scientific databases are still
separate, explicitly selected resources.

## Download and disk space

The [measured 32-pack assessment](full-bundle-sizing-2026-10-06.md) found a
**3.81 GB total download and 4.67 GB initial extracted files** including the
published 0.9.0 Starter. The new setup interface adds a small core change; its
exact packaged size must be measured from its own candidate.

A fresh Starter already contains three of the selected packs. The
released 0.10.0 Starter is **17,028,340 bytes**; its matching source and updater
identities are in the handover. The remaining 29
published archives total **3,795,572,848 bytes**. Setup's download estimate counts
only the missing selection. These numbers exclude reference databases, results,
filesystem allocation overhead, extraction working space and per-run expansion
of private runtimes. They are not a guarantee of sufficient storage or memory
for a particular analysis. Each existing pack keeps its licence and source trees;
no repacking or shared-runtime deduplication changes its scientific identity.

## Trust and deployment status

`workspace/setup-profile.json` contains reviewed pack identities, names and byte
sizes. `publishing/setup-assets.json` additionally locks the immutable release
URLs. Neither file authenticates a publisher. The official source must be a
reviewed entry in the application's `workspace/catalog-sources.json`, with ID
`native-workbench-official`; a user-imported source merely using the same ID is
insufficient to become the recommended setup source.

The owner-started [production run 37617540915](https://github.com/comparativechrono/workbench/actions/runs/37617540915)
succeeded on reviewed `main` commit `9f82aa5d1d9a0a372fc0492b7dff448694af8813`.
It repeated **56 source tests**, freshly downloaded and fully validated all 32
archives, signed the catalogue, published commit
`0048c4e3644aae7ed172d804fff0981982510e7b`, and verified anonymous downloads.
The official [catalogue](https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json)
and [public source](https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/source.json)
are available. The owner-confirmed fingerprint is
`8d2093f9fafd71de56fea2038faeb2efa0964767d3235430b06428132cdc8505`.

The [independent audit](evidence/catalogue-production-2026-10-07.json) confirms
that current and commit-pinned history bytes agree, all 32 pins match the source
lock and preparation report, and both the application and independent
cryptography/OpenSSL signature verifiers accept the owner key. This is public
metadata and signature validation; no new Windows result is implied.

The reviewed source is bundled in `workspace/catalog-sources.json` in production
candidate `5a390acd8440856e3f4e32de237322a18bb82d7e`. Earlier candidate `8cee606` deliberately had an empty
source list and used isolated fixture trust in the all-pack native gate; its
passing checks cannot substitute for the new production setup gate. Starter and
offline imports remain independent of network availability.

The [owner signing guide](../publishing/catalogue-signing.md) documents the
protected `catalogue-production` workflow. The successful signing job establishes
that its configured key and fingerprint work; administrative protection settings
remain unavailable for connector inspection. Private keys stay outside Git and
public outputs, and no private key was read by the agent. The new candidate was built with these exact public trust bytes and passed live
production Full in both Windows paths.
Existing independent pack/source releases remain the download authorities.

## Implementation and preservation

`workspace/setup_manager.py` owns profile selection, exact queues, per-pack
progress and persisted retry state at `user-data/tool-setup.json`. It uses the
existing `PackManager` downloader and native importer. `service.py` owns the
background worker and prevents conflicting tool/reference/check/setup jobs;
`desktop_host.py` exposes bounded `setup/*` calls through the private pipe.
`desktop/desktop_workspace.cpp` implements the native controls. This adds no
browser, listening HTTP server, administrator requirement or system Python.

`package_split.py` includes the setup module and profile in the core inventory.
It still bundles exactly the same three Starter packs, outside core ownership.
The source companion includes the setup code, knowledge pages, workflows and
only the curated public setup metadata and `catalogue-signing.md` owner guide
from `publishing/`; that directory is not swept for local signing/staging
material. Adding the guide affects future source companions only; the recorded
candidate archives remain unchanged.

`scripts/build_update_0100.py` creates the app-only 0.9.0-to-0.10.0 updater from
one exact starter ZIP and native updater launcher. The published baseline is
pinned to SHA-256
`c2661c144e073c4efdd190ffd186bacd9398b6413b81770d7a057c3947eecf02`.
It checks both core inventories, unchanged Starter pack bytes and the new setup
components, then verifies every replacement against the candidate. It performs
no network request or native execution. Existing packs and exact saved workflow
pins, user source configuration, setup queue, references and results remain
outside the core transaction. The application and updater versions advance to
0.10.0; pack API and pack versions do not change.

## Validation and remaining gates

The new [production-candidate validation record](evidence/tool-setup-0.10.0-validation-2026-10-07.json)
records `windows-2022` execution of source `5a390acd` in
[run 37618824677](https://github.com/comparativechrono/workbench/actions/runs/37618824677):
**13 setup, 32 workspace, eight References, nine results/CWL/DAG/icon and 13
upgrade checks passed per path**. Upgrades preserved 203 files and checked 72
core files. The source gate passed 152 tests with one Windows-only skip; native
Windows pack-manager checks passed all 42 tests. References' optional updater
helper was not requested and is not counted as passed. The independent
[archive audit](evidence/tool-setup-0.10.0-artifact-audit-2026-10-07.json) checked
572 exact source files, 143 unchanged Starter pack files and all 11 updater
replacements. Live production Full passed four checks per Windows path, and the
separate isolated-fixture all-pack gate passed four. Production runs installed
all 32 exact pins, reopened offline and preserved 202 expected alignment/BAM
records. All six workflow jobs succeeded. See the [acceptance record](evidence/tool-setup-0.10.0-acceptance-2026-10-07.json)
for the promotion decision and the [publication record](evidence/tool-setup-0.10.0-publication-2026-10-07.json)
for the completed release. No accepted archive was rebuilt.

The earlier [candidate validation record](evidence/tool-setup-0.10.0-validation-2026-10-06.json)
retains historical `windows-2022` execution of source `8cee606`: per path, **13
setup, 32 workspace, eight References, nine results/CWL/DAG/icon and 13 upgrade
checks passed**. The exact upgrade preserved 203 existing files and verified all
72 target core files. Test scopes overlap; these are not additive unique-test
counts. Initial asynchronous GUI test failures were corrected in validators and
rerun against unchanged application bytes, with the failures retained.

Full setup downloaded the 29 missing real packs (**3,795,572,848 bytes**), and four
checks covering all 32 packs' coexistence, offline startup, pack-driven BED input
and 202-record scientific truth passed. The offline host denied Python socket
operations; this was not an OS firewall test. This used isolated test-only
catalogue trust, not a deployed
production source. An independent audit verified all three candidate archives,
558 matching Git source files and 143 unchanged Starter pack files. See the
handover for exact archive identities, run URLs, skips and remaining limits.

The combined local Linux source gate passed **136 tests**, with **one native-Windows
long-path check skipped** and no failures. It covers setup profiles, exact queue
and signing identities, cancellation/retry, state-write failures, private host
integration, pack import, catalogue publication and core packaging/upgrades.
The [source record](evidence/tool-setup-source-2026-10-06.json) pins the tested
files and lists every suite. The packaging checks below are included in that
total, not additional passes. The native desktop, bridge and updater also
cross-compiled using the pinned LLVM-MinGW with warnings as errors; compilation
does not establish native Windows execution.

The local Linux packaging/update checks performed during this implementation
passed **28 tests, zero failures or skips**:

```sh
python3 -m unittest discover -s tests -p 'test_setup_release.py' -v
python3 -m unittest discover -s tests -p 'test_split_release.py' -v
python3 -m unittest discover -s tests -p 'test_core_update.py' -v
```

Those tests establish synthetic archive/inventory and update-transaction
properties. They do not establish Windows behavior. Backend/UI/trust tests and
exact candidate results must retain their own dated evidence.

Before promoting a release, validate the exact packaged application in ordinary
and space-containing Windows paths: native Full/Starter/Custom interactions,
explicit refresh/install, signed downloads, cancellation, integrity failures,
restart/retry, offline operation, tool-catalogue refresh and mutual exclusion.
An all-32-pack coexistence check must retain every published pin and observe
startup/tool discovery without claiming every tool's scientific operations were
rerun. Existing scientific/UI/References/CWL gates remain separate.

`scripts/check_update_0100_windows.py` additionally checks the exact published
0.9.0 baseline and candidate updater, an existing optional pack, saved settings
and connected pinned workflow, actual reference results and receipts, every
preserved file hash, idempotent repeat update, and new offline scientific/CWL
execution. It uses the updater's private interpreter and does not claim native
updater folder-picker interaction or a live reference download. Its Windows run
passed in both paths for both the earlier empty-trust candidate and the new
production-trust candidate; each record pins its own exact archives.

The candidate workflow must retain input/output hashes, source commit, failures,
screenshots and native reports. The production signed catalogue is now verified;
fresh online Full setup against that exact deployed trust also passed in both
Windows paths. The accepted immutable candidate is now published, and all ten
public downloads were independently verified. Fixture-only production omissions
and unrequested helper checks are not counted as passes; the separate production
Full and updater suites retain their own evidence.
