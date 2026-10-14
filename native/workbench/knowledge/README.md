# Native Workbench knowledge base

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

**Primer3/PLINK2 ready for draft review, 2026-10-13:** independent **1.0.0**
packs are complete in [draft PR #18](https://github.com/comparativechrono/workbench/pull/18),
stacked on unchanged Kalign draft PR #17. Tested source
`3d1d83b70d053af625b5cb45362851c0fefab2a1` passed both Windows path cases,
31 scientific tests per path, normal graphs, Starter/pack regressions and GUI
checks. All 38 actual display images were reviewed. See the
[handover](primer3-plink2-handover.md) and
[final evidence](evidence/primer3-plink2-1.0.0-final-review-2026-10-13.json).
[Pack/source download](https://github.com/comparativechrono/workbench/actions/runs/38403212748/artifacts/11816422463)
expires 2026-11-12. Measurements remain output files; native Results shows status
and provenance. Application bytes are unchanged; nothing is merged or published.

**Kalign ready for draft review, 2026-10-13:** optional **1.0.0** is implemented in
[draft PR #17](https://github.com/comparativechrono/workbench/pull/17), based on
merged PR #16. Exact source `8149bdc02a2104e97ea6512ae0a8bc76c8defc32` passed
both Windows path cases, Kalign→FastTree graphs, regressions and native GUI checks.
All 20 actual display screenshots were reviewed. The [handover](kalign-handover.md)
and [final evidence](evidence/kalign-1.0.0-final-review-2026-10-13.json) retain the
initial fixture-line-ending correction, exact hashes and scope limits.
[Pack/source download](https://github.com/comparativechrono/workbench/actions/runs/38396201555/artifacts/11812411631)
expires 2026-11-12. No release or catalogue publication is included.

**Merged first pack batch, 2026-10-13:** [PR #16](https://github.com/comparativechrono/workbench/pull/16)
merged into `fix/native-ui-0.16.1` at `8addaa1278c535e4931eb0b2b85b8f47b51ddd66`
on the owner's instruction. The [batch handover](prodigal-fasttree-handover.md)
retains exact native science, GUI review, source audit and download evidence.
This did not merge PR #15 into main or publish any application, pack or catalogue.
Published **0.16.0** and the unpublished **0.16.1** application bytes are unchanged.

**Previous wrapped tool library, 2026-10-10:** implemented in unpublished
**0.16.1** source `ff13db729a6215e9fe5dfa4a4efdb9c769880287` in
[draft PR #15](https://github.com/comparativechrono/workbench/pull/15).
Names wrap in bold, descriptions wrap in regular text, and the hover popup is
removed. Native scrolling reaches tall rows without losing the library viewport.

The exact build passed **258 source tests**, C++ JSON, three strict native builds
and the archive/source audit. **124 distinct native checks per Windows path**
passed across the full run and unchanged-archive feedback recheck
[38076722339](https://github.com/comparativechrono/workbench/actions/runs/38076722339).
The separate 18 validator tests and repeated native checks add no new application
coverage. Final evidence audit and **41-image visual review** are complete;
the candidate is **ready for unpublished draft review**. The
[final acceptance index](evidence/wrapped-library-0.16.1-final-acceptance-2026-10-10.json)
retains all previous failures, including the initial ordinary runner-console
obstruction. Representative-PC and broader display acceptance remain outstanding.
Start with the [handover](wrapped-tool-library-0.16.1-handover.md) and
[library contract](expandable-tool-library.md).
[Windows review download](https://github.com/comparativechrono/workbench/actions/runs/38075960020/artifacts/11678725746).
Published **0.16.0** remains unchanged; nothing is merged or released.

**Previous resize correction, 2026-10-10:** implemented in unpublished **0.16.1**
application source `51077179a6e92020a7e9b992fa0cbe2b5a6c3e1e` in
[draft PR #15](https://github.com/comparativechrono/workbench/pull/15).
The app places the complete resized layout before painting it. A bounded resize
comparison recorded 14 mixed-layout frames in the old package and none in the
corrected package; screenshot review confirmed the difference. **235 source
checks** and **117 distinct native checks per Windows path** passed across the
recorded runs; exact archive/source correspondence passed. The separate strict
single-transition negative control remains unreproduced, so the workflow is not
green and no exact lag-duration or zero-flicker claim is made. Start with the [resize handover](resize-redraw-0.16.1-handover.md)
for exact identities, failed attempts and evidence limits. Published **0.16.0**
remains unchanged; nothing is merged or released.

**Previous tester-feedback candidate, 2026-10-09:**
[Draft PR #15](https://github.com/comparativechrono/workbench/pull/15) contains
unpublished **0.16.1** application source
`73778e00461e2b83c07b9ea97df2b9c5d4b6317d`: reduced Run/poll redraws,
anchored category expansion/collapse, separate Methods with Run preflight, and
native Samples New/Edit/Save as CSV/TSV with a verified one-row Starter example.

The exact archives passed **220 source tests**, strict native builds and the
archive/source audit. Native Windows checks passed **113 per path**: 81 regression,
19 patch and 13 tester-feedback checks. Validator-only tests passed **23**,
separately from application tests. Final validator
`f9e7120196ddd284d33c0e8221b78fbf4529058f`,
[run 37999874335](https://github.com/comparativechrono/workbench/actions/runs/37999874335),
uses the unchanged application archives. Regression, settled patch and final
feedback visual reviews passed within their recorded 96-DPI scope. The candidate
is ready for **unpublished draft review**. The bounded immediate Tools-resize
transient and all four partial attempts are retained. Focused, sanitized receipts
and original-report hashes are saved; raw reports remain in expiring Actions
artifacts.
Start with the [handover](tester-feedback-0.16.1-handover.md).
Published **0.16.0** remains unchanged; nothing is merged or released.

**Deployment companion baseline:**
[Draft PR #14](https://github.com/comparativechrono/workbench/pull/14) contains the
unpublished Windows acceptance and deployment companion for unchanged published
**0.16.0**. Implementation, exact-kit observations and 54 screenshot reviews are
complete. Tooling commit: 1a7d1e5f70e3ca710c9b3f6b1313353e8d46cc78;
[final run](https://github.com/comparativechrono/workbench/actions/runs/37979351047).
All 87 companion source tests passed. Each Windows path recorded 14 native passes,
**two failed Results Escape checks**, and 11 curated passes. CI remains failed.
The hosted 1024-pixel desktop also clips the app's 1040-pixel minimum width.

Start with the [companion handover](deployment-acceptance-handover.md),
[tester guide](../docs/deployment-acceptance.md) and
[IT review guide](../docs/institutional-deployment.md). All 10 manual checks remain
untested; representative PCs, high DPI, multiple monitors, physical trackpads,
managed-machine approval and signing remain external work. Its failed keyboard
and narrow-display observations prompted the preceding 0.16.1 UI patch;
the companion evidence remains unchanged. Benchmarking is separate; scientific
Linux CWL and SDK/build recovery remain later sets. The published record below is
unchanged.

**Current release, 2026-10-09:**
[0.16.0 development prerelease](https://github.com/comparativechrono/workbench/releases/tag/app-v0.16.0),
packaged source `e855dc4396e0c16ae35f4e840eb9cc734adb4441`.
Start with the [release handover](curated-workflows-0.16.0-release-handover.md),
[current state](current-state.md), [release notes](../docs/releases/0.16.0.md)
and [public-download receipt](evidence/curated-workflows-0.16.0-public-downloads-2026-10-09.json).

The cumulative release includes [readiness and diagnostics](readiness-performance.md),
[sample batches and queue](batch-workflows.md), [reusable indexes](reference-indexes.md),
[restart, resource budgets and portable projects](recovery-projects.md),
[reference management](reference-management.md), and
[curated workflows and recorded results](curated-workflows-results.md).
Published packs/profile/trust remain unchanged; additional align 0.4.1 is a
separate explicit import for upgraded installations.

Exact evidence: [release lock](evidence/curated-workflows-0.16.0-release-lock.json),
[archive audit](evidence/curated-workflows-0.16.0-release-archive-audit-2026-10-09.json),
[native release checks](evidence/curated-workflows-0.16.0-release-regression-final-2026-10-09.json),
[updater](evidence/update-0.16.0-final-validation-2026-10-09.json) and
[visual review](evidence/curated-workflows-0.16.0-release-visual-review-2026-10-09.json).
The [roadmap](roadmap.md) retains representative-PC, scientific Linux CWL,
benchmarking, signing and institutional work as outstanding.

The [original 0.16 candidate](curated-workflows-results-0.16.0-handover.md),
[0.15](reference-management-0.15.0-handover.md),
[0.14](recovery-projects-0.14.0-handover.md) and
[0.13](batch-queue-indexes-0.13.0-handover.md) handovers remain historical records
of those exact bytes and their original unpublished review scopes. They do not
replace the corrected release's own acceptance evidence.

This is the durable handover for people and agents continuing Native Workbench.
It records why the project exists, how it works, how to extend it, and which
claims the evidence supports. It is stored as plain UTF-8 Markdown and JSON:
open, diffable files with no proprietary reader or external memory service.
"Knowledge base" describes this directory; it does not claim compliance with a
separate standard called Open Knowledge Format.

**Historical review:** 2026-10-07. **Historical starting source baseline:**
[`8f95caa1f267d19ce72ea3cd7f2396ae66a801c1`](https://github.com/comparativechrono/workbench/commit/8f95caa1f267d19ce72ea3cd7f2396ae66a801c1).
This handover includes the 0.7 reference-discovery implementation and
Kraken2/Bracken metagenomics after the annotation,
expression, coverage and phylogenetics expansion. SnpEff, DESeq2, mosdepth and IQ-TREE have successful
exact-final Windows installation, graph and scientific gates. Evidence for
each release retains its own date and tested bytes. Re-check the current tree
and releases before treating this snapshot as current.

The [0.8.0 native interface](native-ui.md) was published as a development
prerelease after user acceptance; [PR #1](https://github.com/comparativechrono/workbench/pull/1)
is merged. The release promotes the exact tested candidate bytes without a
rebuild. All nine public assets were independently downloaded and hash-verified;
see the
[0.8.0 release handover](native-ui-0.8.0-release-handover.md). Testers
accepted its layout and reported workflow/input, scrolling and navigation
issues. The 2026-10-06 revision adds explicit reusable workflow inputs and
navigation controls, fixes native repaint/first-open errors and clarifies
scientific tool names. The first feedback candidate's **75 source checks passed**, followed by **32
workspace checks and 8 References/update checks in each Windows path**, with
zero failures or skips. These include native workflow pointer interactions,
scroll repaint comparison and a 202-record minimap2 SAM-to-sorted-BAM run. The
[feedback record](evidence/native-workflow-0.8.0-feedback-2026-10-06.json)
retains an earlier scientific-assertion failure and keeps the revised candidate
separate from the
[successful 2026-10-05 candidate](evidence/native-ui-0.8.0-development-2026-10-05.json).
The guide retains tested candidate identities and identifies untested physical
trackpad/display scenarios. A later user report exposed a separate ordinary-path
I/O failure on a 269-character pipeline output. The corrected candidate passed
**82 CI source checks**, the repeated **32+8 native checks per path**, and a new
long-path regression that reproduces the old error and passes the full corrected
starter pipeline with machine long-path policy disabled. All 20 pipeline output
hashes were checked, including the expected variant-call truth. The fix preserves
ordinary provenance identities and uses extended paths at filesystem boundaries.
See the
[sanitized long-path record](evidence/native-workflow-0.8.0-long-path-2026-10-06.json).
Earlier native passes did not establish this deep-output-path behavior.
The user subsequently confirmed that the pipeline fix worked, while reporting
that text still flashes during scrolling. That pipeline confirmation is user
acceptance of the reported fix, not a new automated run or acceptance of all
display behavior. The earlier scroll check compared settled images and did not
observe intermediate frames. The further revision at `b3928ca` adds composited
form panels, suppresses redundant redraws and accumulates small wheel deltas.
Its [exact-package native run](https://github.com/comparativechrono/workbench/actions/runs/37453380541)
passed all five jobs. Across three panels, 960 sampled desktop frames showed
no unexpected text/background image and all 300 requested endpoint transitions
were observed; all 18 precision-wheel cases passed. The old package also showed
no unexpected frames, so the tester's visual flashing was **not reproduced in
CI**. Six old precision-wheel cases did fail and now pass; that is a separately
reproduced movement defect. The [scroll record](evidence/native-workflow-0.8.0-scroll-2026-10-06.json)
retains these limits and the verified candidate download. The user's subsequent
acceptance supersedes the pending tester-confirmation status; it is user-reported
acceptance, not a new CI observation or broader display-coverage claim.
Version 0.8.0 was published at **2026-10-06T13:12:15Z** as
[app-v0.8.0](https://github.com/comparativechrono/workbench/releases/tag/app-v0.8.0).
Published 0.7.0 and its evidence remain unchanged.

The **0.9.0** CWL export, routed DAG and SVG-derived icon release is now
[published](https://github.com/comparativechrono/workbench/releases/tag/app-v0.9.0)
after exact-package checks and user acceptance. The release promotes application
source `beea34a` unchanged; PR #2 and tag point to `1ee61f1`. Its separate updater
from 0.8.0 passed 13 native checks per path, and the publication workflow verified
all 12 public assets by anonymous download. A separate independent audit also
verified all 12 assets, five ZIP CRCs and three checksum manifests. See the
[0.9.0 handover](cwl-dag-icon-0.9.0-handover.md) and [CWL feature guide](cwl-results.md).

- [Tool Setup 0.10.1 patch handover](tool-setup-0.10.1-handover.md) — scrolling/repaint regression, download diagnostics and exact-candidate evidence; publication status is recorded there.
- [Expandable tool library](expandable-tool-library.md) — 0.11.0 development candidate with native category browsing; validation and release status are recorded separately from 0.10.1.

## Reading order

| File | Question it answers |
| --- | --- |
| [Purpose and decisions](purpose-and-decisions.md) | Who is this for, what approach was chosen, and what must not be lost? |
| [Current state](current-state.md) | What is released, tested, limited or unfinished? |
| [Native UI patch 0.16.1](ui-patch-0.16.1-handover.md) | What changed after the deployment checks, and which exact candidate evidence and limits apply? |
| [Architecture](architecture.md) | Where does each responsibility live, and how does a run work? |
| [Native UI development](native-ui.md) | How do the three panes, standalone tools and workflow canvas work, and what remains to validate? |
| [0.9.0 handover](cwl-dag-icon-0.9.0-handover.md) | Which CWL/DAG/icon bytes were accepted and published, and what passed? |
| [Tool setup](tool-setup.md) | How do Full, Starter and Custom installation work, and what remains before official deployment? |
| [0.10.0 setup handover](tool-setup-0.10.0-handover.md) | Which exact 0.10.0 files were published, and what did their Windows and public-download checks establish? |
| [CWL results](cwl-results.md) | What does an exported workflow contain and what does external execution require? |
| [0.8.0 release handover](native-ui-0.8.0-release-handover.md) | Which exact native-interface bytes were accepted and published? |
| [Starter tool semantics](starter-tool-semantics.md) | Which program does each starter operation run, how does SAM become BAM, and what does faidx mean? |
| [Reference discovery](../docs/reference-discovery-0.7.md) | How are references found, downloaded, reused offline and recorded in runs? |
| [Development](development.md) | How do I recover inputs, build, test and resume work? |
| [Pack development](pack-development.md) | How do I add a real tool without rebuilding the app? |
| [Validation and releases](validation-and-releases.md) | What establishes correctness, and how are artifacts published and trusted? |
| [Catalogue signing](../publishing/catalogue-signing.md) | How does the protected official publisher work, and which one-time owner settings remain necessary? |
| [Roadmap](roadmap.md) | What should be addressed next, and what would count as completion? |
| [Readiness and performance development](readiness-performance.md) | What does the first accepted roadmap milestone implement, and which measurements/privacy/validation limits apply? |
| [Project index](project.json) | Machine-readable entry points and stable constraints. |
| [Release inventory](release-inventory.json) | Dated public versions, download assets, checksums and evidence pointers. |

The repository-root [AGENTS.md](../AGENTS.md) is the short onboarding entry point.
For a new pack, read the pack guide and validation guide together. For a UI or
engine change, start with architecture and development, then check the accepted
interaction decisions.

## Evidence and authority

- Product requirements and design history come from the project owner's
  development conversation, captured explicitly in the decision record. They
  are requirements, not proof that every feature is fully implemented.
- Each dated topic identifies its reviewed source or validation checkpoint;
  newer development is separate from the starting baseline above. Source links
  are repository-relative so they work in a clone and on GitHub.
- Release facts come from published release metadata, accompanying reports and
  named CI runs. A historical pass applies to the tested bytes and environment.
- Proposed next work is labelled as such. Missing evidence is kept visible.

If a page disagrees with current code, reproduce or inspect the behavior and
update the page. Do not change a scientific result or loosen validation merely
to make documentation appear true. Do not let implementation drift silently
override an explicit product requirement: explain the conflict first.

Older documents remain useful for source recovery and release-specific details.
In particular, [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) describes the first
experimental computation module, not the complete current application.
[docs/pack-development-0.6.md](../docs/pack-development-0.6.md) originally
recommended two repositories; its guidance is now corrected to this one
repository with independent application and pack tags. The 18-pack lists under `publishing/`
describe the original 0.6 split, before STAR, kallisto and the later optional
packs. Do not mistake these historical inventories for the latest complete list.

The GATK 1.0.0 source/evidence companion includes a complete `knowledge/` snapshot
and root `AGENTS.md`. Its creation-time pending-final-gate statements remain
historical; use the separate final validation record for completed evidence.
The 0.7 application source packager now includes root `AGENTS.md`, this complete
handover, recursive documentation and workflow definitions in its hashed source
inventory. The older 0.6 source companion remains unchanged.

For the four newer packs, start with the
[connection and installation overview](../docs/ANNOTATION-EXPRESSION-COVERAGE-PHYLOGENETICS.md),
then the individual guides. Preserve each release's source/evidence snapshot and
separate final validation report. DESeq2's R-runtime corresponding sources are a
second release asset, with their own file lock and runtime-bound hash; the small
source/evidence ZIP does not contain those third-party archives. See
[source recovery details](../tools/deseq2/R-RUNTIME-SOURCES.md) and the maintained
pack-development and validation pages before rebuilding.

The [Kraken2/Bracken pipeline guide](../docs/KRAKEN2-BRACKEN-PIPELINE.md) and
[shared resource specification](../docs/METAGENOMICS-RESOURCES.md) describe local
database preparation, descriptor identities, fragment/read semantics and
explicit external-model declarations. Both exact-final packs have successful
Windows installation, graph and scientific evidence. Preserve their full
source/evidence companions and separate final validation records; large
scientific databases are user-selected inputs and are not included in the packs.

## Maintaining the handover

Keep facts close to their source rather than duplicating full specifications.
After a change, update the affected topic and its evidence link. Refresh the
dated current-state/inventory snapshot after a release; do not rewrite an old
successful result to refer to newly built bytes. Preserve superseded versions
and the reason a decision changed.

Before handing work to another agent, record:

1. The task, branch/commit, changed files and whether changes are published.
2. Decisions made and compatibility or scientific behavior affected.
3. Exact verification commands, environment, results, skips and artifact hashes.
4. Remaining work, blockers and the smallest next action.
5. Durable source/evidence locations; avoid relying on a temporary workspace,
   an active browser session or a previous agent's private memory.

Never add patient data, credentials, private keys, account tokens or temporary
session details to this public directory. Synthetic scientific fixtures and
publicly redistributable source/evidence are suitable.
