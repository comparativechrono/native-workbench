# Development roadmap

**Integration update, 2026-10-13:** the owner authorized checking compatibility
and merging the completed PR stack. PRs [#18](https://github.com/comparativechrono/workbench/pull/18),
[#17](https://github.com/comparativechrono/workbench/pull/17),
[#15](https://github.com/comparativechrono/workbench/pull/15) and
[#14](https://github.com/comparativechrono/workbench/pull/14) are now merged,
carrying the already merged #16 work into `main` at
`9c9cdeacf35d1bf3aa60277f0fb05d5af41c6254`. Every merge preserved the reviewed
source tree exactly. Five pack archives load together with eight scientific
workflows and unchanged version pins; 30 focused source checks passed.

Published **0.16.0**, candidate archives and historical validation remain unchanged.
This is source integration, not a release or deployment-acceptance claim. No open
PRs remain. The [integration receipt](evidence/stack-integration-2026-10-13.json)
records merge identities, compatibility checks and outstanding work. Earlier
review/draft statements below are dated history superseded only for merge status.

## Active review: Primer3 and PLINK2 optional packs, 2026-10-13

The owner requested this next stage after the reviewed Kalign candidate. The
initial scope is standard Primer3 PCR primer-pair design and PLINK2 hardcall
allele/genotype counts and missingness summaries, with independent 1.0.0 packs.
PCA, association testing and additional Primer3 modes remain later interfaces.
Development is stacked on the unchanged Kalign review branch; PR #17 remains
unmerged. Implementation, exact Windows validation in both path cases, source
audit and 38-image actual-display review are complete in
[draft PR #18](https://github.com/comparativechrono/workbench/pull/18). See the
[batch handover](primer3-plink2-handover.md) for bounded contracts, exact downloads
and evidence. Native Results measurement parsing and broader acceptance remain
outstanding; no application change or publication is included.

## Previous set: Kalign optional pack, 2026-10-13

The owner authorized merging PR #16 and starting Kalign. The first batch is
merged into `fix/native-ui-0.16.1` at `8addaa1278c535e4931eb0b2b85b8f47b51ddd66`;
no release or catalogue publication followed. Kalign development starts from
that exact merged tree on `feature/kalign-pack`.

The first Kalign interface is a separate **1.0.0** pack for nucleotide and protein
multiple-sequence alignment, with exact upstream source, native Windows builds,
scientific fixtures and typed outputs for downstream FastTree. Implementation,
exact Windows gates in both path cases, downloaded source audit and 20-image
review are complete in [draft PR #17](https://github.com/comparativechrono/workbench/pull/17).
The [Kalign handover](kalign-handover.md) records tested source, downloads,
initial correction and limits. Kalign remains unmerged and unpublished.
Benchmarking remains separate.

## Merged development: Prodigal and FastTree optional packs, 2026-10-13

The owner approved the first small batch from the requested tool inventory:
**Prodigal** gene prediction and **FastTree** phylogenetic inference. Both start
as independent **1.0.0** pack candidates; no application version change is
required. Development is based on the existing wrapped-library candidate at
`2b2e97aa15970f0e7fb3a5428e8ab7dad6acada2`, preserving draft PR #15.
Both are implemented and merged in [PR #16](https://github.com/comparativechrono/workbench/pull/16).
Source and exact-archive native science passed, including both Windows path
cases, real MUSCLE-to-FastTree graphs and Starter regressions. The frozen form
recheck and 44-image visual review are complete. See the
[batch handover](prodigal-fasttree-handover.md) and
[final index](evidence/prodigal-fasttree-1.0.0-final-review-2026-10-13.json) for
exact hashes, initial failures, counts and limits. Source, native science and GUI
scopes remain separate; no release or catalogue publication is included.

The requested inventory already contains published optional packs for fastp,
Cutadapt (pack `trimming`), HISAT2, mosdepth, featureCounts, kallisto, LoFreq and
MUSCLE. Existing classic BWA is not bwa-mem2; existing kallisto bulk operations
do not implement bustools or single-cell BUS processing.

Kalign, Primer3 and PLINK2 are ready for unpublished draft review. Their initial
bounded operations are implemented; bustools and StringTie
need workflow integration; HMMER, bwa-mem2, Salmon and MACS3 need dedicated
portability work. Strelka2 needs an initial feasibility and version-specific
licensing assessment. This is a provisional engineering order, not a schedule.
Benchmarking remains separate, alongside the previously outstanding deployment,
representative-PC, signing, scientific Linux CWL and release/updater work.

## Previous set: wrapped native tool library, 2026-10-10

Unpublished **0.16.1** application source
`ff13db729a6215e9fe5dfa4a4efdb9c769880287` implements full bold wrapped names,
regular wrapped descriptions and removal of the library hover popup. The bounded
native viewport supports tall rows and overflow scrolling, preserving category,
keyboard, search/filter, selection, drag and scientific workflow contracts.

The exact build passed 258 source tests, C++ JSON, three strict native builds and
archive/source audit. The full run plus frozen feedback recheck
[38076722339](https://github.com/comparativechrono/workbench/actions/runs/38076722339)
passed **124 distinct native checks per Windows path** on unchanged archives.
The initial ordinary runner-console obstruction and earlier application/driver
failures remain recorded. Repeated checks and separate validator tests add no
unique application coverage.

Final evidence audit and 41-image review are complete. This set is **ready for
unpublished draft review** through existing
[draft PR #15](https://github.com/comparativechrono/workbench/pull/15), with the
[handover](wrapped-tool-library-0.16.1-handover.md) and
[final acceptance index](evidence/wrapped-library-0.16.1-final-acceptance-2026-10-10.json).
No merge or publication is included. Published **0.16.0**, independent pack pins
and historical resize evidence remain unchanged. Broader PC/display acceptance,
signing/IT, Linux CWL and SDK recovery remain outstanding; benchmarking is separate.

## Previous set: Tools resize correction, 2026-10-10

The bounded correction is implemented in unpublished **0.16.1** application
source `51077179a6e92020a7e9b992fa0cbe2b5a6c3e1e` in
[draft PR #15](https://github.com/comparativechrono/workbench/pull/15). It places
the complete resized layout before painting, preserving the other accepted
interface and workflow behavior. **235 source checks**, exact archive/source
correspondence and **117 distinct native checks per Windows path** passed across
the recorded runs.

A bounded concurrent-resize comparison recorded 14 mixed-layout frames among
46 old-package samples and none among 64 corrected-package samples. Screenshot
review confirmed the old duplicated/shifted controls and clean corrected
endpoints. This supports the narrow redraw correction. The separate strict
single-transition negative control did not reproduce stale layout after the
compositor wait, so the workflow remains failed on that requirement. Preserve
that failure, pre-wait transients and finite-sampling limits in the
[resize handover](resize-redraw-0.16.1-handover.md); no exact lag-duration,
performance or zero-flicker claim is established.
No merge or release is included. Published **0.16.0**, benchmarking and the
remaining external acceptance/deployment work stay separate.

## Previous set: tester-feedback revision of unpublished 0.16.1

The [draft PR #15](https://github.com/comparativechrono/workbench/pull/15)
revision is implemented in application source
`73778e00461e2b83c07b9ea97df2b9c5d4b6317d`, with published 0.16.0 unchanged.
It addresses Run/poll redraws and category expansion anchoring/collapse redraws,
restores separate Methods while keeping Run preflight and removing the primary
Readiness button, and adds native Samples New/Edit/Save as CSV/TSV plus a verified
one-row Starter example. File columns, base folders and mapping stay explicit;
there are no runtime/memory forecasts or invented independent replicates.

Source validation (**220 tests, 18 suites**), three strict native builds and the
independent archive/source audit passed. Final native coverage is **113 checks
per Windows path**: 81 completed regressions, 19 patch checks and 13 feedback
checks. Validator `f9e7120196ddd284d33c0e8221b78fbf4529058f`,
[run 37999874335](https://github.com/comparativechrono/workbench/actions/runs/37999874335),
passed on unchanged application archives, with 23 separate portable gate tests.
Repeated patch checks add no unique coverage. Four earlier partial attempts remain documented through focused failure
summaries and original-report hashes.

Visual review is complete for 112 regression, 82 patch and 192 final feedback
capture files. The feedback review covers 51 unique BMP hashes through 52 direct
views and 140 verified exact-hash reuses, with no unexpected layout defect within
the captured 96-DPI viewports. Keep the bounded immediate Tools-resize
old-geometry observation until the first later sample (~0.30–0.32 s), observed-size
limits, and the distinction between finite temporal samples and zero flicker.

The [handover](tester-feedback-0.16.1-handover.md) is ready for unpublished draft
review. Durable focused, sanitized receipts and original-report hashes replace
raw JSON uploads; full originals remain in Actions artifacts that expire on
2026-11-08. Tokens and detailed runner/input records are excluded from repository
delivery. No merge or release is included. Benchmarking is separate; external
acceptance, signing/IT, scientific Linux CWL and SDK/build recovery remain
outstanding.

## Prior set: native keyboard and narrow-display patch

[Draft PR #15](https://github.com/comparativechrono/workbench/pull/15) carries the
unpublished **0.16.1** follow-up on `fix/native-ui-0.16.1`, stacked on
`feature/deployment-acceptance` and draft PR #14. Candidate source
`8938e709b041106e8a46e1447383e8e9ba3e0cb9` addresses the observed Results
keyboard focus/Escape defect and the clipped initial window on a 1024-pixel
desktop. It retains the three-pane layout and uses the monitor work area for
placement and minimum-size bounds. That candidate completed its unpublished
draft-review validation before the
active tester-feedback revision. Published **0.16.0** is unchanged; nothing is merged or released.

[Run 37988570028](https://github.com/comparativechrono/workbench/actions/runs/37988570028)
passed 141 source tests and 84 native checks per Windows path, and the independent
archive/source audit passed. These are the third candidate's own results.
The [validator-only recheck](https://github.com/comparativechrono/workbench/actions/runs/37989535317)
at `69022689e686b2cacdc98dbdbef728e664941e67` also passed the same 19 patch checks
per path without rebuilding the application. These are repeated observations
within the 84-check scope. Crops from the original screenshots corrected the
earlier full-frame interpretation: General settings and Readiness were present.
Passive visible captures before PrintWindow show settled fixed controls by the
first 250-ms capture (about 0.3 seconds elapsed), unchanged at 750/1250 ms;
immediate frames can retain old geometry. Settled 96-DPI visual review passed;
these samples do not establish zero flicker or exclude shorter unsampled
transients. The [native record](evidence/ui-patch-0.16.1-native-validation-2026-10-09.json),
[visual review](evidence/ui-patch-0.16.1-visual-review-2026-10-09.json) and
[patch handover](ui-patch-0.16.1-handover.md) retain exact evidence and limits.

The third revision additionally keeps read-only `queue/status` polling from
disabling editing when no outgoing actions are queued. Mutation guards and FIFO
ordering remain, with availability refreshed immediately when queuing a mutation.
Passive 2.4-second focus holds now span polling intervals without refocusing.
This follows a second attempt with all 84 checks passing in the ordinary path but
two spaced-path failures at library Tab/Home focus before Results opened. All 65
existing checks per path passed; the failed attempt and its audits remain retained.

The first candidate's failed native gate and 141 source passes remain separate
in the handover. The validator now uses corrected control IDs, waits for Setup
dismissal and makes filter clearing observable; the spaced-path filter-clear
failure's cause remains unproven. Layout scope is the observed 96-DPI desktop
with a 960-pixel outer minimum width. Source review identifies busy Cancel/Results
overlap below 908 logical client pixels and possible footer overlap below 902;
smaller work areas and high DPI require further work and validation.

## Windows acceptance and deployment companion baseline

The owner accepted this bounded set on **2026-10-09** with “okay, lets do that”.
[Draft PR #14](https://github.com/comparativechrono/workbench/pull/14) implements
an unpublished companion around unchanged published **0.16.0**: verified offline
kit, file/executable/runtime/licence inventories, structured tester reporting and
native updater folder-picker/desktop checks. It does not create a new app release.

Exact observations and 54 screenshot reviews are complete for tooling commit
1a7d1e5f70e3ca710c9b3f6b1313353e8d46cc78,
[run 37979351047](https://github.com/comparativechrono/workbench/actions/runs/37979351047).
All 87 source tests passed. Each Windows path recorded 14 native passes,
**two failed Results Escape checks**, 11 curated passes and 72 signature
observations. CI remains failed and all 10 manual acceptance items remain untested.
The 1040-pixel minimum app width also clips on the hosted 1024-pixel desktop.
The [handover](deployment-acceptance-handover.md) owns exact evidence and limits.

These failures prompted the 0.16.1 review candidate above. The companion and
its original observations remain available for review; successful integrity and
science checks do not waive the failed desktop requirement or establish that the
new patch passes.

Representative-PC/high-DPI/multiple-monitor/physical-trackpad and managed-machine
observations remain outstanding. Signing needs a controlled identity, and
institutional deployment needs actual IT approval. Benchmarking is handled
separately. Scientific Linux CWL profiles and SDK/build-recovery consolidation
remain later sets.

## Current release and remaining work

The owner authorized a new release on 2026-10-09 with
“Great lets do a new release at this point”.
[0.16.0 is published as a development prerelease](https://github.com/comparativechrono/workbench/releases/tag/app-v0.16.0)
on **2026-10-09**, from packaged source
`e855dc4396e0c16ae35f4e840eb9cc734adb4441`. The release combines the implemented
measurement/readiness, multi-sample, recovery/resource/project, reference-management
and curated-workflow/results groups. Each retains its explicit contracts and
exact hosted validation; publication does not declare the whole programme complete.

The initial curated catalogue contains two synthetic training workflows:
alignment with QC and variant calling, with exact dependencies, expected
answers and missing-dependency guidance. Native results display recorded
measurements, search and actionable failures without invented QC thresholds.
The [release handover](curated-workflows-0.16.0-release-handover.md) records
source/native/updater/publication evidence, rejected attempts and remaining limits.

Representative Windows PCs, high-DPI/multi-monitor/physical-trackpad acceptance,
scientific Linux CWL validation, realistic matched Windows–Linux benchmarking,
executable signing/institutional deployment and further pack-developer tooling
remain separate work. The exact published 0.11.0→0.16.0 updater and release
gates are complete within their recorded scope. Small synthetic known answers
do not establish realistic capacity, performance parity or biological fitness.

## Historical acceptance and implementation sequence, 2026-10-08

The following chronology retains the authorization and unpublished branch status
at the time each tranche began. Its future-tense and release-pending statements
are historical; current completion and remaining acceptance work are above.

The owner accepted the feature programme below with “Great. We should do all
of these. Lets start working through them.” Development starts with a bounded
measurement/readiness milestone on `feature/readiness-performance`, based on
`82729febfcfab1c43bd9c9798d03c80f595545cb`, targeting **0.12.0**. This is
development authorization, not evidence that the features or a release are
complete. Published **0.11.0** and all published pack bytes remain unchanged.
See the [first-tranche feature guide](readiness-performance.md) and
[current state](current-state.md) for implementation and validation status.

The owner subsequently requested the next tranche. Milestone 2 now targets
unpublished **0.13.0** on `feature/batch-queue-indexes`, stacked on the unmerged
0.12.0 branch. Its first concrete index contract is minimap2 short-read `.mmi`;
its combined-analysis mode initially covers explicitly selected multi-input
metrics/text reports. Neither implies generic cohort pooling or reusable indexes
for every aligner. See [batch workflows](batch-workflows.md) and
[reference indexes](reference-indexes.md) for exact limits and evidence.
Its implementation and recorded hosted Windows gates are complete in
[draft PR #8](https://github.com/comparativechrono/workbench/pull/8); see the
[candidate handover](batch-queue-indexes-0.13.0-handover.md). Representative-machine
acceptance and release/update validation remain separate from that result.

The owner has now requested the final implementation tranche, milestone 3.
It targets unpublished **0.14.0** on `feature/recovery-projects`, starting from
`9f5cd4c88634b4cab04cec66b9e43e93e1db0e17` on the unmerged 0.13.0 branch.
See [recovery, resources and portable projects](recovery-projects.md).
Implementation and the exact hosted Windows candidate gates are complete in
[draft PR #9](https://github.com/comparativechrono/workbench/pull/9); the
[handover](recovery-projects-0.14.0-handover.md) records final downloads,
independent archive verification, failed prior attempts and remaining acceptance
and release work. Milestones 1–3 are implemented on stacked review branches,
not published releases or completed representative-machine acceptance.
This does not declare the further accepted work or benchmark programme complete.

The owner then requested the remaining groups one at a time. The first is
**reference management**, targeting unpublished 0.15.0 on
`feature/reference-management` from `38917349449ce56a45d3e0f4f41b7d2a38621c6d`.
It covers resumable downloads, reviewed local import, verified library relocation
and a bounded NCBI RefSeq accession provider. See the
[feature contract](reference-management.md) and
[handover](reference-management-0.15.0-handover.md). The original three
implementation tranches were not the entire accepted suggestion list; each
remaining group retains its own completion and validation evidence. The reference
group is now implemented and hosted-Windows validated in draft PR #10;
representative-machine acceptance and publication remain separate.

| Milestone | Accepted scope | Completion evidence |
| --- | --- | --- |
| 1 — Measurement and readiness | Local performance records, an understandable readiness report, reviewable diagnostic export and representative-machine validation. | Exact packaged Windows evidence for successful, failed and cancelled work; preserved scientific output; documented timing/counter scope and unavailable values; reviewed JSON equals exported JSON; private-data canaries absent; installation, readiness and scientific execution clearly distinguished. A separate matched Windows–Linux benchmark protocol records hardware, versions, parameters and data identities. |
| 2 — Routine multi-sample work | A sample table, general batch workflows, a durable run queue and reusable reference indexes. | Previewed sample/read-pair mapping; independent per-sample and explicitly combined analyses; exact frozen queued plans surviving restart while the next workflow remains editable; index identity and completeness verified before reuse. Saved pins and existing results survive migration. |
| 3 — Recovery and efficient execution | Verified restart at completed-step boundaries, resource-budgeted parallel execution and portable project bundles. | Fault-injected interruption/restart preserves scientific outcomes, reuses only verified completed products and invalidates changed dependencies; scheduler respects declared budgets/cancellation; project import reports missing or incompatible dependencies without silent substitution. |

High-DPI displays, keyboard navigation, physical trackpads and managed Windows
machines are acceptance work across **every** milestone. Hosted 96-DPI checks
remain useful evidence for their recorded environment; they do not establish
all of these deployment scenarios. No endpoint-security control should be
disabled to obtain a pass.

### Accepted feature contracts

| Feature | Intended behaviour and boundaries |
| --- | --- |
| Sample table and batch workflows | Import CSV/TSV sample names, paired reads, conditions, replicates and references. Preview pairing and reject ambiguity. Preserve sample identity and distinguish independent sample runs from deliberate pooling or cohort analysis. Existing pack-specific sample sheets do not establish a general application batch model. |
| Safe restart | Reuse only completed steps whose inputs, parameters, exact tool/manifest pin, reference identities and declared outputs still match. Begin at step boundaries; resuming within a scientific executable requires that tool's own supported checkpoint contract. |
| Durable queue | Queue immutable analyses with exact settings and software versions, monitor/cancel individual jobs, and edit the next workflow while one runs. Preserve queued state across reopen; never silently repin a saved or queued workflow. |
| Resource controls | Start with a total CPU budget, selected temporary-storage location, free-space checks and honest memory/storage guidance. Add bounded concurrency only after reliable measurements and admission rules exist. Unknown requirements must remain unknown. |
| Reusable reference indexes | Build once and register reference hash, indexing tool, version, options and a complete output inventory. Reject incompatible or incomplete indexes. Typed directory products and changed pack commands need explicit versioned contracts and migration tests. |
| Readiness report | Make graph/input checks, selected pack definitions, output access/storage, deferred integrity/scientific checks and actual tool execution distinct. “Check installation” passing must not imply the user's analysis can run. |
| Performance and diagnostics | Retain measurements locally with their scopes, versions and missing values. Separate preparation/hashing/orchestration from native command stages. Diagnostic sharing is an explicit review-and-save action, with no automatic upload or broad log/data collection. |
| Curated workflows and results | Supply tested workflows with small redistributable example datasets, explanations and expected answers. Add native sample-level QC summaries, searchable results and useful failure explanations with links to raw outputs and methods. Preserve exact tool pins. |

### Further accepted work

- **Reference management:** resumable large downloads, importing existing local
  references, safe library relocation and additional providers. Retain explicit
  retrieval, complete-file integrity and assembly/annotation compatibility.
- **Portable projects:** bundles containing workflows, sample metadata, exact
  pack/reference requirements and optionally data. Provide a guided missing-file
  resolution process and tested Linux execution profiles for exported CWL.
  Existing CWL export is not blanket proof of Linux scientific equivalence.
- **Institutional deployment:** executable signing, bundled executable/dependency
  inventories, offline deployment packages and IT approval documentation. Signing
  does not guarantee acceptance by endpoint-security software.
- **Pack developer toolkit:** templates, metadata/schema validation, scientific
  fixture checks, packaging checks and documented Windows–Linux comparisons.
  Third-party contributions retain independent versions, trust and licensing.

### Benchmark programme

Use direct matched-tool comparisons and complete workflow comparisons to
separate upstream execution from application overhead. Pin versions, datasets,
references, parameters and threads; use the same physical hardware with separate
Windows/Linux installations where practical. Record hardware/storage and OS
configuration. Measure first-use installation/downloads separately from offline
analysis, repeat cold/warm runs, and evaluate meaningful scientific outputs with
predeclared equivalence criteria. Document memory-counter differences rather
than comparing Windows committed-memory peaks directly to Linux maximum RSS.
Preserve failed, cancelled and unavailable measurements. Small installation
fixtures do not establish realistic cohort capacity or performance parity.

## Historical backlog, 2026-10-05

The original dated planning record follows unchanged. Its proposed catalogue
publication was subsequently completed; the signed 32-pack catalogue and
application 0.11.0 are already published. Items here describe their original
date, not current release blockers. Resolve current implementation questions
against the active milestone and maintained state above.

Snapshot: 2026-10-05. These are proposed priorities derived from the current
gaps, not a promise of functionality or authorization for external actions.
Check [current state](current-state.md) before starting; newer work may have
closed a gap. STAR, kallisto, FastQC, MultiQC, featureCounts, BEDTools, BLAST,
GATK, SnpEff, DESeq2, mosdepth and IQ-TREE packs have already been published;
adding their first versions is no longer an outstanding task. The four newest
packs passed exact-final native Windows installation, graph and scientific gates;
this does not close desktop acceptance or catalogue deployment. The 0.7 source
now implements Ensembl archive reference discovery/download and frozen run
provenance; see current-state for its separately recorded release evidence.

| Priority | Work | Completion evidence |
| --- | --- | --- |
| 1 | Validate the current native desktop experience on representative Windows machines. | Named app/pack hashes, Windows versions and reports for launch, library selection, standalone tools, settings/pipeline saves, step removal, branched/merged DAGs, provenance, resizing/scrolling, cancellation and pack management. Separate ordinary, spaced, Unicode and long-path behavior. Check declared path-policy rejections as rejections, not successful analysis. |
| 1 | Complete signed online catalogue publication when the maintainer supplies a controlled signing key. | Public signed catalogue and independently verified source fingerprint; import into a clean app, refresh/install/check a small pack; retain offline operation. Existing 0.6 archives remain unchanged. See the publishing guide for the pending trust setup. |
| 1 | Bring the future catalogue release map up to the actual public inventory. | Include the RNA, October optional, GATK, SnpEff, DESeq2, mosdepth and IQ-TREE packs with source/evidence metadata, including DESeq2's separate R-runtime source companion; explicitly handle superseded kallisto 1.0.0 while retaining it for saved pins. Revalidate all archives before signing. The old 18-pack map is not an up-to-date feed. |
| 2 | Make clean-checkout build recovery less dependent on historical source companions. | Document and verify pinned prerequisites for each supported build; retain corresponding source and licences; remove accidental dependence on a previous agent's temporary paths. Demonstrate a selected pack rebuild from the documented inputs. |
| 2 | Extend native Windows scientific coverage across the older packs. | A per-pack evidence matrix with exact archive/app hashes, supported operations, actual defaults, failure checks and scientific assertions. Do not extrapolate the newer packs' native CI passes to older tools. |
| 2 | Benchmark realistic workloads and resources. | Redistributable or explicitly authorised data, fixed versions/parameters, independent reference results, timing/RAM/disk measurements, hardware and OS details. Keep synthetic installation tests separate. Human-scale performance remains unestablished by the synthetic fixtures. |
| 3 | Improve reusable index contracts, especially STAR. | Versioned directory-valued products or another explicit model, atomic completeness checks, reference/tool/index identity, graph compatibility and migration tests. Current STAR and BLAST operations deliberately rebuild private indexes per run. |
| 3 | Design a dedicated gVCF graph type if expanding cohort workflows. | Versioned core/schema support, static separation from ordinary VCF and unrelated generic files, preserved old pipeline pins and adapter-level format/reference/sample checks. GATK 1.0.0 deliberately uses labelled generic file ports on released 0.6.0; its two-to-32-input CombineGVCFs operation does not establish GenomicsDB or large-cohort support. |
| 3 | Broaden the reference providers and large-download experience. | The initial provider supports Ensembl archive 100–116, local reuse and frozen provenance. Consider new-platform Ensembl once its download layout is stable, NCBI/RefSeq, explicit known-site bundles, resumable transfers and reference relocation. Each needs provider-specific identity, checksum, cancellation and compatibility evidence. Keep Kraken/Bracken databases and SnpEff codon mappings separate from executable packs. |
| 3 | Extend differential-expression designs only when a concrete need is established. | DESeq2 now supplies bulk gene-level differential expression and kallisto transcript-to-gene import for condition or additive batch-plus-condition designs. Paired/repeated measures, continuous covariates, interactions and single-cell analyses remain outside that interface. Any extension needs explicit experiment-design contracts, independent upstream/known-answer tests and a new pack version; broad metrics ports alone cannot establish valid raw counts or biological replication. |

Do not combine all of these into an uncontrolled redesign. Choose one concrete
gap, inspect the current code, define acceptance evidence, and make a bounded
change. Keep the app/pack boundary intact.

## Questions to resolve when the relevant task starts

- Who controls catalogue signing, where is its public fingerprint recorded, and
  how are key rotation and recovery handled? The private key must not be stored
  in this repository or supplied through a public document.
- Which Windows versions, hardware limits and institutional application-control
  configurations are supported? Current source/CI evidence is not a support
  matrix for every managed PC.
- Which RNA-seq workloads and reference sizes should drive reusable-index and
  resource design? Small synthetic checks cannot answer capacity questions.
- What reference providers, reporting outputs and additional tools do actual
  users need next? The Galaxy Tool Shed can inform tool selection, but a Galaxy
  wrapper is not by itself a Windows port, licence audit or scientific contract.

Keep resolved answers in the decision record and the relevant technical page.
