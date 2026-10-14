# Prodigal and FastTree pack batch

Date: 2026-10-13. Status: implementation, exact Windows validation, archive audit
and visual review complete. The owner subsequently authorized merging PR #16;
it is merged into `fix/native-ui-0.16.1` at
`8addaa1278c535e4931eb0b2b85b8f47b51ddd66`. The merge tree exactly matches the
reviewed delivery tree. No release or catalogue change is published. See the
[merge receipt](evidence/prodigal-fasttree-merge-2026-10-13.json).

Review: [merged PR #16](https://github.com/comparativechrono/workbench/pull/16),
stacked on the unmerged wrapped-library PR #15.

## Source and scope

Branch: `feature/prodigal-fasttree-packs`, based on
`fix/native-ui-0.16.1` at `2b2e97aa15970f0e7fb3a5428e8ab7dad6acada2`.
The existing wrapped toolshed and all other application changes are preserved.
Published application **0.16.0** and the unpublished **0.16.1** application
candidate are unchanged. The new pack identities are `prodigal` **1.0.0** and
`fasttree` **1.0.0**; these are independent of upstream tool versions.

- Prodigal: separate prokaryotic genome and metagenome prediction operations,
  explicit genome genetic-code settings, upstream metagenome model selection,
  GFF annotations and predicted protein/CDS FASTA products.
- FastTree: separate nucleotide and protein alignment operations, explicit
  substitution model, rate treatment, seed and optional SH-like local support.
  Outputs remain unrooted approximate maximum-likelihood trees; local support
  is not a conventional bootstrap or a posterior probability.

Both packs use pinned real upstream sources and private native executables.
Adapters validate file roles and preserve scientific results. No system Python,
WSL, Docker, online analysis or application-specific UI branch is introduced.

## Exact review candidate

Pack build source: `d175076d57f4c84743cb375369c604085a720204`, tree
`e15f450758f0713755f68c7f5ad2b9b42832c611`.
[Build and native science run 38387733137](https://github.com/comparativechrono/workbench/actions/runs/38387733137)
passed all three jobs. The original failed candidate below is superseded for
review, but its evidence remains unchanged.

[Download both pack ZIPs and matching source/evidence](https://github.com/comparativechrono/workbench/actions/runs/38387733137/artifacts/11806999226).
The Actions download is a containing ZIP: extract it, then use **Manage tools →
Import pack ZIP** on each `native-workbench-pack-*.zip`. Use published **0.16.0**
or the existing **0.16.1** UI candidate. No signed catalogue or Full-selection
change is included. Offline import verifies inventory and reports that publisher
identity is unverified. GitHub sign-in may be needed for Actions downloads;
this artifact expires on **2026-11-12**.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `native-workbench-pack-prodigal-1.0.0.zip` | 1,855,319 | `321a8717b2e8841f7caf2c13ac2837638c9cc10000aaeb0919463c70cb07dad4` |
| `native-workbench-pack-fasttree-1.0.0.zip` | 853,557 | `4525aa8001b7b190eecbee5a164bb9586ce9f78d8672635df25ae4e462165c20` |
| `native-workbench-prodigal-fasttree-1.0.0-source-evidence.zip` | 5,246,791 | `2c4f1fb1f1d4f2aa7d855e8eaf47aa8726bea2ef19a1a9b7876e0189c5ef6e64` |

The containing artifact SHA-256 is
`39436067a80e28b89837ba7d266201f9b909792eaee73dc298bed61fb0cf14fd`.
Prodigal manifest SHA-256 is
`731ddc3f415e6727e2b4d8bee73103de7c4835ae6e9a66be9b5d67e77cdfd757`;
FastTree manifest SHA-256 is
`83e45c8c7222bea53e4023861450aa79db0a2f003f7e2a82f6c6362923bcdc55`.

## Completed validation scopes

- **Hosted source and Linux:** Prodigal 17 passes; FastTree 13 passes and one
  Windows-only MUSCLE skip; 20 official Linux reference cases were freshly run
  within the FastTree suite. Evidence-binding tests passed six, pack checks 14,
  and pack-manager tests 46 with one Windows-only long-path skip. These are
  **96 passes and two platform skips**, separate from native Windows evidence.
- **Downloaded archive audit:** exact transport and inner hashes, ZIP inventories,
  924 Git source files and 967 source-companion entries matched. Retained recipes,
  guard sources, upstream pins, licences and binary provenance matched. The
  actual Prodigal PE reserves 8 MiB and initially commits 64 KiB. This establishes
  byte/source correspondence, not independent bit-identical recompilation.
- **Exact Windows science, ordinary and spaced paths:** each path passed all
  **16 Prodigal and 14 FastTree regression tests**, with no selected native skips.
  Prodigal's previously failing non-SD cases pass. Both packs import through the
  native bridge, run their declared checks and reject duplicate versions.
- **Real application integration:** both paths completed nucleotide and protein
  MUSCLE 0.5.2 → FastTree DAGs with preserved residues, taxa and independent
  known unrooted pairs. Normal pinned runs, wrong input/stale manifest rejection,
  methods, CWL export, provenance and result search passed. The combined
  installation check passed seven core checks, one executed Starter scientific
  graph and ten installed-pack checks. Repeated assertions are not extra unique
  scientific coverage. All 274 original released-app files remained unchanged.
- **Frozen UI recheck:** validator `9ea63994661073b115e80533c3288d50d250decb`,
  [run 38389163430](https://github.com/comparativechrono/workbench/actions/runs/38389163430),
  passed eight separate validator tests and 12 GUI-scope checks per path on the
  same pack archives and unchanged 0.16.1 archive. All four forms start at their
  true top and reach the final page through wheel scrolling. Recorded Results
  search and exact operation/tool provenance passed; all 277 original app files
  remained unchanged. Only four named validator/workflow/test files differ from
  the pack build source. This adds visual coverage, not new pack science.

The native science application is published 0.16.0, source
`e855dc4396e0c16ae35f4e840eb9cc734adb4441`, Starter ZIP SHA-256
`f96e03e43cac92ba8ca9a0a3807eb671f9924d5e624cadbba94d1a5ca1309073`.
GUI acceptance uses the existing 0.16.1 UI source
`ff13db729a6215e9fe5dfa4a4efdb9c769880287`, Starter ZIP SHA-256
`28f1362287991621dde030da54eb444846142c0243be6b9d86c4b4f1bf99dd47`.
Published MUSCLE 0.5.2 archive SHA-256 is
`c07d3e398f48df683926c0970ef77c3b7d2bdab6426b80c80186f2360ed25258`.

The first successful build's GUI walk retained nonzero starting scroll positions
for three forms. Its limited visual scope remains recorded; the frozen recheck
corrects that coverage gap without rebuilding any archive. All **44 actual display images** from the frozen recheck were directly reviewed:
30 form pages and 14 library/Results views, with no blocking layout issue in the
1024×728 application window at 96 DPI. The 44 supplemental PrintWindow captures
remain separately labelled. See the [visual receipt](evidence/prodigal-fasttree-1.0.0-visual-2026-10-13.json)
and [final review index](evidence/prodigal-fasttree-1.0.0-final-review-2026-10-13.json). Actual display BitBlt captures and supplemental
PrintWindow repaints are distinguished; finite settled images cannot establish
zero flashing.

See the [source receipt](evidence/prodigal-fasttree-1.0.0-source-2026-10-13.json),
[archive audit](evidence/prodigal-fasttree-1.0.0-archive-2026-10-13.json),
[native science/integration](evidence/prodigal-fasttree-1.0.0-native-2026-10-13.json)
and [frozen form recheck](evidence/prodigal-fasttree-1.0.0-frozen-forms-2026-10-13.json).
They preserve report hashes and artifact identities. The source companion retains
its creation-time pending statements; later exact-hash receipts supersede them
without editing the tested ZIPs.

Representative Windows PCs, high DPI, multiple monitors, physical trackpads,
realistic workload benchmarking, signing/institutional deployment, scientific
Linux CWL execution and release/updater validation remain separate. Runs here
used the application's private native host; GUI Run-button execution was not
asserted. Python socket denial is not OS network isolation. Synthetic fixtures
establish neither biological QC thresholds nor clinical suitability or resource
forecasts. These initial interfaces retain the documented input/path bounds;
see the [Prodigal](../docs/PRODIGAL-PACK.md) and
[FastTree](../docs/FASTTREE-PACK.md) guides. No remaining implementation blocker
is known within this bounded batch.

## Initial candidate and required corrections

Source `b7fb88b8a81e55b9faef78861fe7a4ce08e61671`,
[run 38385903740](https://github.com/comparativechrono/workbench/actions/runs/38385903740),
passed the hosted Linux/source build and independently downloaded source audit.
Both Windows paths then failed two of 16 Prodigal scientific regressions:
forced non-Shine-Dalgarno training and automatic fallback exceeded the executable's
default 1 MiB stack. The unchanged upstream routine has approximately 1.25 MiB
of local arrays. A Prodigal-only linker correction reserves 8 MiB, verified from
the PE header; it does not change the scientific algorithm. The same regression
assertions must pass on the rebuilt archive.

The separate GUI gates imported both packs, completed normal recorded runs and
checked all four forms. Both stopped at Results because the driver expected the
run-level word `success`; the application correctly records `completed` and the
individual scientific step records `success`. Correct the driver, retaining the
actual operation/version/hash assertions and screenshots.

The unchanged application's Results parser does not interpret these new JSON
measurement formats. Search, status, executable versions and provenance remain
available; measurements are recorded in `prediction-summary.json` and
`alignment-summary.json` in the result folder. Do not claim native summary tiles
for these measurements. FastTree's installation checks cover identities/counts;
its extended scientific suite, rather than installation checks alone, asserts
independently constructed tree splits.

The initial [source](evidence/prodigal-fasttree-1.0.0-initial-source-2026-10-13.json),
[archive](evidence/prodigal-fasttree-1.0.0-initial-archive-2026-10-13.json) and
[failed native](evidence/prodigal-fasttree-1.0.0-initial-native-2026-10-13.json)
receipts retain exact identities, counts, original report hashes and unavailable
checks. Neither the partial successes nor a later corrected run erase these
failures. Rebuilt unpublished candidates keep distinct archive hashes.
