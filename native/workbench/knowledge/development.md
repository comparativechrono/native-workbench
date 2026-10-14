# Development and recovery runbook

**Current set:** unpublished 0.16.0 curated workflows/results, on `feature/curated-workflows-results`. Runtime modules `curated_workflows.py` and `results_summary.py` are packaged explicitly. `native-curated-candidate.yml` builds matching source/Starter archives and validates the exact Windows package in both path layouts. See the [feature contract](curated-workflows-results.md) and [handover](curated-workflows-results-0.16.0-handover.md).

Reviewed against source commit `9368c22058a3fe3cd434e7185fcaf5ff3fd6ce22` on
2026-10-04. Recovery, packaging and updater instructions were updated for the
0.7.0 reference-discovery working tree on 2026-10-05, based on repository
baseline `8f95caa1f267d19ce72ea3cd7f2396ae66a801c1`. This is a build runbook;
consult the release inventory for publication and exact-final validation status.
Commands below run from the repository root unless stated otherwise.
Paths in angle brackets are placeholders to replace, not files supplied by Git.
Read [architecture](architecture.md) before changing an unfamiliar layer.

**Previous set:** unpublished 0.15.0 on `feature/reference-management`
extends the frozen 0.14.0 review candidate. The
[reference-management guide](reference-management.md) defines resumable transfer,
local import, copy/verify relocation and bounded NCBI RefSeq lookup contracts.
The exact candidate workflow is
[`native-reference-management-candidate.yml`](../.github/workflows/native-reference-management-candidate.yml).
It retains the immutable build inputs and adds live Ensembl/NCBI and focused
reference management gates alongside affected native regression gates. Runtime
modules `reference_transfer.py`, `reference_library.py` and `reference_ncbi.py`
must be included by `package_split.py`. No updater or release is implied.
The [frozen reference recheck](../.github/workflows/native-reference-management-recheck.yml)
rejects production/build differences, pins the original archive/executables and
reruns corrected batch/source validators without rebuilding application bytes.

**Previous tranche:** unpublished 0.14.0 on `feature/recovery-projects`
extends the unmerged 0.13.0 candidate. The [recovery/resources/projects guide](recovery-projects.md)
defines its contracts. The exact candidate workflow is
[`native-recovery-candidate.yml`](../.github/workflows/native-recovery-candidate.yml).
It retains immutable build inputs, a separate align 0.4.1 candidate pack and
independent archive extractions for each Windows gate. It builds no updater
and publishes nothing. New runtime modules must be listed in
`scripts/package_split.py` as well as retained in the matching source archive.

**Previous tranche:** unpublished 0.13.0 on `feature/batch-queue-indexes`
extends the unmerged 0.12.0 candidate. Published 0.11.0 remains the baseline.
The [batch/queue](batch-workflows.md) and [index](reference-indexes.md) guides
describe the new contracts. The exact candidate workflow is
[`native-batch-candidate.yml`](../.github/workflows/native-batch-candidate.yml):
it recovers immutable 0.6.0 runtime/source inputs, stages a separate align 0.4.1
pack, builds matching source/starter archives, and runs independent native gates
on those bytes. `package_split.py stage --extra-pack-dir <align-0.4.1>` records
the complete additional pack inventory separately from the unchanged three
Starter pins. The pack ZIP requires app 0.13.0. No updater is built by this
candidate workflow. Do not modify the production setup profile to publish a
development pack or infer release authorization from this build runbook.

**Historical release, 2026-10-07:** application 0.10.0 adds native Full/Starter/Custom tool setup.
See [tool setup](tool-setup.md) for source, packaging and exact Windows gate commands.
The official signed catalogue was published and independently verified on 2026-10-07;
see [production evidence](evidence/catalogue-production-2026-10-07.json). Its public
source is bundled in candidate `5a390acd`; exact-package native setup, workspace,
References, results/CWL/DAG/icon and 0.9.0 upgrade checks passed in both Windows
paths. Live production Full also passed four checks in each path, and all six
candidate workflow jobs succeeded. [Application 0.10.0 is published](https://github.com/comparativechrono/workbench/releases/tag/app-v0.10.0)
from those unchanged archives. Ten public assets, four ZIP CRCs and both checksum
manifests passed independent download verification. The packaged source remains
`5a390acd8440856e3f4e32de237322a18bb82d7e`; release tag/PR #3 merge is
`2e474345dff195b860df39fdde263c840dd1fba3`. Its updater supports 0.9.0 only.
Consult the [handover](tool-setup-0.10.0-handover.md) for exact evidence.

**Previous baseline, 2026-10-06:** application 0.9.0 was published from the exact
accepted `beea34a` application candidate without rebuilding. The release tag
`app-v0.9.0` and PR #2 merge commit are `1ee61f1`; the separately built updater
from 0.8.0 has its own exact native gate. Follow the
[CWL results guide](cwl-results.md) and [release handover](cwl-dag-icon-0.9.0-handover.md)
for the contract, immutable identities and publication checks. Versioned 0.7.0
commands, inventories and results below remain the historical baseline runbook.
Use `workspace/app_version.py` and recorded build inputs for new artifact names;
never replace published archives or transfer their validation results to changed
bytes. Historical [0.8.0 evidence](native-ui-0.8.0-release-handover.md) remains
unchanged. Published 0.9.0 updaters support 0.6.0 and 0.8.0, not 0.7.0.

## 0.9 results and presentation

Merged branch `feature/cwl-dag-icon` adds `workflow.cwl` result export, routed native/SVG
DAG edges and SVG-derived native icon resources. Read [the CWL results guide](cwl-results.md)
before changing the exporter or interpreting its portability. Candidate source
is `beea34ab29f3e7cb9a7e79dbcfa11c89f40ee59d`; its
[handover](cwl-dag-icon-0.9.0-handover.md) records the exact archives and passing
125-check source gate, including stock `cwltool` fixture execution. Existing
workspace/References, scientific/export/SVG and long-path checks have recorded
native passes. The final focused feature gate passed nine checks in each Windows
path with no failures/skips; its three earlier fixture/capture failures remain
diagnostics. Validator-only commits have not rebuilt or changed the candidate.
The published 0.8.0 record above remains unchanged.

The focused source commands are:

```sh
python3 workspace/tests/test_cwl_export.py
python3 workspace/tests/test_cwl_results.py
python3 tests/test_dag_routing.py
python3 tests/test_app_icon.py
```

`NW_CWLTOOL` must name the independently installed validator/runner for the
interoperability case in `test_cwl_export.py`; absent that variable, its skip is
not a CWL interoperability pass. The development workflow
[`native-results-candidate.yml`](../.github/workflows/native-results-candidate.yml)
uses a separate test-only environment with pinned `cwltool` and retains the
existing workspace/reference/packaging/updater suites. This adds no CWL runtime
dependency to the application. The routing suite also distinguishes compiler
availability from a native GUI result.

The native build scripts generate the ICO with
`python3 scripts/build_app_icon.py` from the tracked SVG. Generated icon/build
outputs remain reproducible artifacts, not a new graphics dependency. The
exact-package Windows gate in
[`scripts/check_results_windows.py`](../scripts/check_results_windows.py) checks
result exports, real native execution and standalone-runner replay, routed
geometry and native icon resources. That replay does not claim Windows CWL-engine
execution. Record source/interoperability, cross-build and native results
separately, and keep any missing prerequisite or failed check visible.

The focused verification uses the original candidate artifact instead of
rebuilding it. Final validator `bc972125814c1f24dca86391d0c5f240716a52f3` passed
[run 37489208656](https://github.com/comparativechrono/workbench/actions/runs/37489208656)
with both `nativeGUIValidated` flags true. It uses `BM_CLICK` only for the zoom
capture where the VM taskbar occludes the physical button position; the separate
workspace gate covers actual pointer zoom. Application source remains `beea34a`.
The user has accepted this exact candidate and authorized publication; see the
[acceptance record](evidence/cwl-dag-icon-0.9.0-acceptance-2026-10-06.json). The included
0.6.0 updater passed its preservation gate. The separate 0.8.0-to-0.9.0 updater
was built by [`build_update_090.py`](../scripts/build_update_090.py) against the
unchanged accepted starter, and passed the focused native gate at
[`check_update_090_windows.py`](../scripts/check_update_090_windows.py) in
[run 37527359533](https://github.com/comparativechrono/workbench/actions/runs/37527359533):
13 checks per path, zero failures/skips, 70 core files verified and 202 existing
files preserved, with native post-update reference and scientific/CWL execution.
The handover records exact updater bytes, earlier fixture failures and limits.
[Publication run 37528064595](https://github.com/comparativechrono/workbench/actions/runs/37528064595)
passed 18 promotion guard checks and verified all 12 public assets by anonymous
download. A separate [independent public audit](evidence/cwl-dag-icon-0.9.0-public-downloads-2026-10-06.json)
verified all 12 assets, five ZIP CRCs and three checksum manifests. Later
documentation records this without modifying accepted archives.

## Start without disturbing existing work

1. Read the root `AGENTS.md`, this knowledge directory and the relevant source.
   Inspect `git status --short`, the current branch and recent commits. Preserve
   uncommitted work and use a separate branch/worktree where appropriate.
2. Determine whether the change belongs to the application, an individual pack,
   shared pack API or release documentation. Do not make an optional pack a
   mandatory dependency of the starter or core tests.
3. Record the exact baseline commit and artifact versions being exercised.
   Inspect release notes and hashes before using old local caches. Historical
   folder names and executable version banners are insufficient evidence.
4. Make the narrow change, run the relevant checks, and retain the evidence.
   Publication and signing must follow the current user's authorization and
   environment permissions; this runbook does not grant credentials or authority.

There is no universal bootstrap command that rebuilds every shipped tool from a
fresh checkout. Do not invent one or silently replace missing vendor sources
with whatever version a package manager currently serves.

## What a checkout contains and what must be recovered

Git contains application source, pack recipes/adapters, small fixtures, tests and
documentation. It deliberately excludes compiled packs, private runtimes,
downloaded vendor archives and large source ZIPs. Read
[source recovery](../docs/source-recovery/README.md) before a full rebuild.

The 0.6.0 source companion contains current sources, the embedded historical
0.5.4 source ZIP and `SOURCE-RECOVERY.json`. Recovery metadata names exact pack
companions and hashes for vendor archives stored under their licence trees.
Extract historical source into a separate directory and install the specified
pack companions into a separate recovery runtime root. The historical
`scripts/restore_source_archives.py` accepts `--source-root` and `--runtime-root`
and verifies hashes before restoration. Use current application sources for app
work; do not overwrite them with recovered older files.

Release source companions and retained upstream archives are build inputs and
licence records, not analysis datasets. A recipe is only reproducible when its
sources, patches, compiler, dependencies and artifact identities remain
available. Keep newly required corresponding source with its matching release.

The current `build_sources()` in `scripts/package_split.py` includes root
`AGENTS.md`, `knowledge/`, recursive `docs/` and `.github/workflows/`, alongside
application, pack recipe, test and fixture sources. The source inventory hashes
these files. The 0.6.0 source companion predates that coverage; it remains
immutable. New companions use the new application version.

Application rebuilding no longer requires recovering the full 0.5.4 combined
runtime. Use the exact published 0.6.0 starter and source companion as the
baseline. The split packager verifies the companion against the starter's
inventoried `SOURCE-AVAILABILITY.json`, copies its hash-verified legacy source
archive and retains the recovery aliases. Optional tool source recovery is
still needed when rebuilding those historical tools, but is separate from
assembling a new application.

The exact application build inputs re-downloaded and independently hashed on
2026-10-05 are:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| [0.6.0 starter](https://github.com/comparativechrono/workbench/releases/download/app-v0.6.0/native-workbench-0.6.0-starter-windows.zip) | 16,871,065 | `16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a` |
| [0.6.0 source](https://github.com/comparativechrono/workbench/releases/download/app-v0.6.0/native-workbench-0.6.0-source.zip) | 45,128,429 | `427a9b42f2528984350479e8b0155e4ef4f0159fa6f240cc1aa84a5ec2e0e60a` |
| [LLVM-MinGW 20260922 UCRT, Ubuntu x86-64 host](https://github.com/mstorsjo/llvm-mingw/releases/download/20260922/llvm-mingw-20260922-ucrt-ubuntu-22.04-x86_64.tar.xz) | 83,924,028 | `bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21` |

Keep the extracted starter immutable and stage into a new directory. Its 65
core inventory entries were also reverified after recovery. Download integrity
and cross-compilation are not native Windows execution evidence.

## Useful checks on a source-only checkout

The current Python application/tests use the standard library. Python 3.10 or
later is needed by syntax and APIs in these files; use the released bundled
interpreter when establishing released-app behavior. OpenSSL enables the real
temporary-key signing tests. These focused suites build artificial packs and
do not need the distributed scientific executables:

```sh
python3 workspace/tests/test_desktop_host.py
python3 workspace/tests/test_pack_schema.py
python3 workspace/tests/test_pack_versions.py
python3 workspace/tests/test_pack_service.py
python3 tests/test_pack_manager.py
python3 tests/test_split_release.py
python3 tests/test_core_update.py
python3 tests/test_publish_pack_catalog.py
```

Run only suites relevant to the change. These checks cover host protocol,
semantic contracts, exact pins, pack-service lifecycle, archive/signature
handling, separate packaging and core update transactions. They do not execute
real scientific tools or establish Windows GUI behavior. The native long-path
test in `test_pack_manager.py` is skipped on Linux; signing tests can skip when
OpenSSL is absent. Report skips explicitly.

Handover check on 2026-10-04: the eight commands above ran on Linux x86-64 with
Python 3.12.14 against the stated source baseline. They ran 130 tests: 129 passed
and the native Windows long-path case was skipped. In listed order, the suite
counts were 12, 28, 10, 6, 42, 7, 14 and 11. This verifies these source-only
instructions in that environment; no scientific executable or Windows GUI was
tested during the documentation update.

Do not assume `unittest discover` over the whole repository is a source-only
unit gate. Several historical suites expect assembled applications, particular
optional packs, vendor caches or APE loader binaries. Missing dependencies can
produce errors or skipped scientific tests. Review each suite's module header
and environment variables first. Run released-app contract tests in a fresh
Python process so previously imported development modules cannot contaminate
which implementation is being tested.

## Native desktop and bridge compilation

Use the pinned LLVM-MinGW toolchain described in
[`platform_windows/README.md`](../platform_windows/README.md). The historical
cross-build baseline is `20260922`, UCRT, Linux x86-64 host; the documented archive
SHA-256 is
`bb7bb7654b33d5aa8712acb837c963b2e0c56352560c76105270a3268c665c21`.
Verify a downloaded toolchain against its provenance before using it.

```sh
export BW_MINGW_ROOT=/absolute/path/to/llvm-mingw
bash desktop/build_desktop_workspace.sh
bash desktop/build_bridge.sh
bash desktop/build_workspace_update_launcher.sh
```

Outputs are `build/desktop/DesktopWorkbench.exe`, `WorkbenchBridge.exe` and
`UpdateWorkbench.exe`. These scripts use C++17 and the Win32 libraries; no browser
framework is needed. Building the initial prepared FASTQ module with
`scripts/build.py` is a separate historical experiment, not a prerequisite for
every application change. Likewise, `desktop/build.sh` builds an older interface;
use the current scripts above for the 0.7 desktop. All three native resource
versions now follow 0.7.0, including the previously stale bridge resource.

Cross-compilation plus PE/DLL inspection proves a Windows executable was
produced, not that it ran successfully. Run the assembled distribution on actual
Windows for process launch, dialogs, resize/scroll rendering, cancellation,
endpoint restrictions and path behavior. Do not lower strict compiler checks
simply to produce an executable.

## Assembling the current starter

The 0.7 recipe accepts the exact immutable 0.6.0 split starter and its source
companion above. It verifies the frozen private runtime inventory and starter
manifest pins, then copies the starter packs byte-for-byte. An arbitrary source
checkout is not a runtime baseline. The recipe also requires the current
compiled desktop/bridge, the three new reference runtime modules and
`examples/starter`. Use new output paths: packagers refuse to overwrite artifacts.

```sh
python3 scripts/package_split.py sources \
  --base-root /absolute/path/to/frozen-0.6.0/native-workbench \
  --base-source-archive /absolute/path/to/native-workbench-0.6.0-source.zip \
  --output /absolute/path/to/new-release/native-workbench-0.7.0-source.zip \
  --metadata /absolute/path/to/new-release/source-metadata.json

python3 scripts/package_split.py stage \
  --base-root /absolute/path/to/frozen-0.6.0/native-workbench \
  --app-root /absolute/path/to/new-stage/native-workbench \
  --source-metadata /absolute/path/to/new-release/source-metadata.json

python3 scripts/package_split.py starter \
  --app-root /absolute/path/to/new-stage/native-workbench \
  --output /absolute/path/to/new-release/native-workbench-0.7.0-starter-windows.zip
```

The source and staging commands were exercised for a disposable 0.7.0 development
integration stage on 2026-10-05; that stage is not a published or frozen release. They do not
authorize replacing the published 0.6.0 assets. A release needs current source,
metadata/build resources and its own immutable artifacts. The recipe copies
`align-0.4.0`, `bam-0.4.0`, `variants-0.4.0` byte-for-byte into the starter. Core
inventory excludes optional packs and mutable results/user-data. `APP_VERSION`
is now 0.7.0, while existing pack API 1 archives retain their 0.6.0 minimum;
an application feature release does not raise every tool's compatibility floor.

Build the app-only 0.6.0-to-0.7.0 updater from that same immutable baseline and
the staged target:

```sh
python3 scripts/make_core_update.py \
  --base-root /absolute/path/to/frozen-0.6.0/native-workbench \
  --app-root /absolute/path/to/new-stage/native-workbench \
  --output /absolute/path/to/new-update-stage \
  --launcher /absolute/path/to/build/desktop/UpdateWorkbench.exe \
  --zip /absolute/path/to/new-release/native-workbench-0.7.0-update-from-0.6.0.zip
```

The updater owns inventoried core files only. Installed optional pack versions,
receipts, saved pack/manifest pins, results, local reference registries and
external reference files remain untouched. It verifies the exact baseline,
stages replacement files, commits the manifest last and rolls back handled
failures. The older 0.5.4 combined-release migration path remains in the code;
that does not imply a new 0.5.4 updater artifact has been prepared or tested.

On 2026-10-05 the Linux source-only packaging/updater suites passed 24 tests
(8 packaging, 16 updater; no skips), including 0.6.0-to-0.7.0 preservation and
an injected failure at the final manifest commit. These synthetic transaction
tests do not establish the native updater folder-picker/launch behavior.
The actual development update payload was also applied on Linux to a disposable
copy of the exact 0.6.0 starter: all 68 target core files verified, starter and
optional pack fixtures plus saved pins/reference/result fixtures were preserved,
and repeat application was idempotent. This is separate from final artifact and
native Windows updater validation.

## Pack preparation and static validation

Use an existing tool's `scripts/build_*` and `scripts/prepare_*` pair as the
closest example; read its CLI help and pinned-source definitions first. Some
older build paths depend on recovered legacy source. The
[independent-pack template](../pack-examples/independent-pack/README.md) contains
declarations and synthetic truth but deliberately no validated binary.

```sh
python3 scripts/package_split.py pack \
  --pack-root /absolute/path/to/prepared-pack \
  --output /absolute/path/to/new-release/native-workbench-pack-example-1.0.0.zip
python3 scripts/validate_pack_release.py \
  /absolute/path/to/new-release/native-workbench-pack-example-1.0.0.zip
```

The static gate checks the archive contract; it does not run scientific
executables. Never regenerate an already published `(pack ID, version)` with
different bytes. Defaults, licences, tests, adapters and manifests all count as
pack changes. Tool updates need new pack versions even if no application code
changes. See the dedicated pack and validation documents in this directory.

## Runtime-dependent checks

For source-based graph/model tests, `NW_APP_ROOT` selects the assembled runtime
used by `tests/test_workspace_engine.py`, `tests/test_core_checks.py` and
`workspace/tests/test_desktop_model.py`. These suites expect specific packs and
fixtures, so a three-pack starter may be insufficient for historical tests.
`workspace/tests/test_catalog.py` instead reads `BW_TEST_APP_ROOT`.

The portable backend in `tests/test_workspace_engine.py` requires
`baselines/bin/ape-loader-linux` in this checkout and compatible actual pack
binaries. It is a Linux-only validation adapter. Native ports such as STAR and
kallisto have separate Linux reference adapters and caches. Their tests identify
those substitutions; do not call them native Windows execution.

For the released-app RNA graph/archive contracts, assemble a disposable copy of
the SHA-verified 0.6.0 starter plus STAR 1.0.0 and kallisto 1.0.1, and provide the
exact archive directory and original starter ZIP. Then run in a fresh process:

```sh
NW_RNASEQ_APP_ROOT=/absolute/path/to/validation-app/native-workbench \
NW_RNASEQ_ARCHIVE_DIR=/absolute/path/to/pack-zips \
NW_RNASEQ_STARTER_ZIP=/absolute/path/to/native-workbench-0.6.0-starter-windows.zip \
NW_RNASEQ_STAR_VERSION=1.0.0 \
NW_RNASEQ_KALLISTO_VERSION=1.0.1 \
python3 tests/test_rnaseq_pipeline.py --report /absolute/path/to/evidence/rna-contracts.json
```

The explicit kallisto version matters: the test's historical default is 1.0.0.
This suite exercises released Python contracts and a substituted archive
publication callback. It does not execute scientific tools or the native
Windows importer. Its report states these limits.

On Windows, use a disposable extracted released application for pack validation:

```powershell
& C:/ci/app/native-workbench/runtime/python/python.exe -I scripts/check_pack_release_windows.py --app-root C:/ci/app/native-workbench --archive C:/ci/native-workbench-pack-example-1.0.0.zip --report C:/ci/evidence/native-pack.json
```

That command imports the candidate into the disposable application and runs its
declared scientific checks through the released native bridge. The repository's
[`native-pack-check.yml`](../.github/workflows/native-pack-check.yml) automates
ordinary and space-containing paths on Windows with an explicit release asset
SHA-256. Read its current inputs and special regressions before dispatching it.
It is a pack gate, not an application GUI test or real-cohort benchmark.

## Diagnosing and handing off a failure

Retain the run's `plan.json`, `run.json`, graph, methods and native logs, plus
archive/binary hashes, exact app/pack versions, host platform and the failing
command arguments. Use synthetic/minimized data for public reports. Do not put
patient, student or otherwise private analysis inputs, identifying filenames or
credentials in the repository or release artifacts.

Check success criteria beyond exit status: zero mapped records can still result
from a broken runtime adapter; optional outputs may expose thread-dependent
paths missed by default fixtures. Reproduce with the actual declared defaults,
scientific truth and independent reference where possible. Keep portability
fixes narrow, document compiler/runtime assumptions, and test the unchanged
scientific result. Consult the recorded STAR stream-buffer and kallisto bootstrap
lessons before touching those ports.

End a change with a clear account of what changed, which artifacts and platforms
were checked, skips/limitations, and the next concrete unresolved issue. Update
this knowledge directory when a decision or current-state fact changes; retain
historical evidence instead of rewriting it to look successful.
