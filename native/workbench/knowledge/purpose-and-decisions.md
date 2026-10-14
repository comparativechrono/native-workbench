# Purpose and decisions

Reviewed 2026-10-06. Product decisions below capture the project owner's explicit
requirements and tester feedback from the development conversation. Technical
status must be read with [current state](current-state.md), not inferred from a
requirement alone.

## The problem being solved

Bioinformatics teaching, researchers without access to managed compute, and
workplaces with Windows-only machines need to run established tools locally.
Many users do not have the Linux, shell, container or filesystem-mounting skills
usually assumed by tool documentation. Some settings cannot send analysis data
to an external service. Workplace browser restrictions also make a browser UI
an unsuitable required entry point.

Workbench should let a user choose local files and output folders, understand
the analysis, run a tool or assemble a scientifically compatible pipeline, and
receive interpretable results with reproducible methods and provenance.
Installing optional tools should not require rebuilding the application or
configuring a Linux environment. These users deserve real scientific software,
clear limits and useful errors, not simplified substitute algorithms.

The initial request explored whether Linux could be made into a lightweight
application. The demonstrated approach became **prepared native/portable
computation plus a small local orchestration layer**. It does not boot Linux or
promise to execute arbitrary Linux binaries. No claim of an unprecedented OS
technique or universal speed/memory advantage is established. Docker, WSL and
QEMU remain useful alternatives; avoiding them here is a usability/deployment
choice, not a claim that they inherently repartition or damage a PC.

## Accepted decisions

| ID | Decision and reason | Consequence for future work |
| --- | --- | --- |
| D01 | Local analysis is the default. Data locality is necessary for teaching and restricted workplaces. | Analysis files remain local. Public reference downloads and pack downloads are distinct, explicit operations. No hidden uploads or cloud fallback. |
| D02 | Use real pinned upstream tools with bounded portability adaptations. | Prefer native Windows builds, portable runtimes or a pack-private language runtime according to the tool. Preserve algorithms, record patches and compare scientific outputs. |
| D03 | The supported entry point is a native desktop app. The browser prototype was unsuitable for some workplace policies. | Preserve Win32 UI and private pipe-based backend. A browser or listening HTTP server must not become necessary to launch or run analysis. |
| D04 | Application and packs have independent lifecycles. Retain a small Starter; the 2026-10-06 setup decision recommends Full for new installations. | Starter pack IDs are `align` (minimap2), `bam` (SAMtools), `variants` (BCFtools). Optional packs install through the manager or offline ZIP import. One repository with independent tags is sufficient. |
| D05 | A pack represents one tool or a small closely related operation set, such as indexing plus alignment. | New tools declare their own inputs, parameters and outputs. Existing multi-tool packs remain compatible; do not delete or rename published identities to impose the new preference retroactively. |
| D06 | Individual tools and assembled pipelines are both first-class. | Keep one clear library selection path, standalone operations and distinct saved tool settings versus saved pipeline graphs. Do not relabel one tool's settings as a complete pipeline. |
| D07 | Pipelines support branching, fan-out and merging, not just a list. | Draw a layered DAG with shared-output consumers at the same dependency level when dependencies permit. Show each input's producing step/output. Support step removal and validate the remaining graph. |
| D08 | Methods and provenance are part of the result, not an afterthought. | Show a methods preview before running; retain methods, DAG, commands, versions, parameters, input hashes and execution records with outputs. Methods are a reviewable draft, not a guarantee of publication sufficiency. |
| D09 | Reproducibility includes preserving installed versions. | Saved pipelines pin pack version and manifest hash. Updates install alongside old versions and require an explicit pipeline upgrade. Published bytes are immutable. |
| D10 | Trust and integrity must remain explicit. | Verify installed/archive inventories and signed online catalogues. An offline ZIP checksum does not authenticate its publisher. Never silently create a new trust root or bypass signing to make online installation work. |
| D11 | Design is guided by novice-user testing. | Preserve the accepted library/editor direction and readable layouts. Add resource needs, compatible input guidance and actionable errors without exposing unnecessary implementation details. |

## Interaction history worth preserving

The project tried a coloured corner wheel, then a rotating category wheel with a
second tool ring. Testers rejected the double ring and accepted the subsequent
tool-library design. Do not revive the wheel because an old screenshot or source
file still contains it. Modern rounded styling was desired; clarity of selection,
readable descriptions and restrained colours matter more than a decorative
control. Resizing, scrolling, focus outlines and text overlap were actual
reported problems and should be checked in UI work.

Testers also identified missing step removal and ambiguous shared outputs.
The resulting expectation is a Snakemake-style dependency diagram with clear
input sources. This is a layout and graph requirement; it does not imply that
the current scheduler runs independent branches concurrently. A merge requires
compatible ports and real tool support, not merely drawing two arrows into a
node. See [architecture](architecture.md) for the implementation boundaries.

Users want optional reports at meaningful points in a pipeline and public
reference discovery, including Ensembl. Downloaded references must become
explicit local, versioned inputs with provenance. Do not imply every reference
database, report format or downstream analysis is already integrated.

Large scientific resources follow the same separation of application and packs.
The Kraken2/Bracken implementation keeps executable packs small enough for the
existing importer while reference indexes and read-length models remain explicit
local inputs. A descriptor records their identity and provenance; it does not
contain the database or silently download missing files. Users may prepare an
already downloaded archive locally, or register existing files without copying
them. Classification-only preparation does not require an abundance model.
This is an implementation of D01/D04/D08, not a new database-hosting service.

Tools remain independently usable. Bracken can consume a saved Workbench
classification record, or an external report with explicitly declared database,
model, read-length and counting-unit provenance. The external path must preserve
its weaker evidence instead of inventing a Workbench execution history. Hashes
establish unchanged files; they cannot prove an external model was trained on
the stated database. These contracts are specified in
[local metagenomics resources](../docs/METAGENOMICS-RESOURCES.md); release status
and successful gate claims belong in dated evidence.

## Reference acquisition, 2026-10-05

The user selected reference discovery/download as the next application feature.
The 0.7 implementation provides an explicit native finder and a reusable local
library, separate from both executable packs and analysis execution. Downloads
produce ordinary files, receipts and hashes; tool inputs and pipelines continue
to consume local paths. Reference identity appears in pre-run methods and is
verified and frozen with the run's input evidence.

The initial provider uses Ensembl archive releases 100–116, because Ensembl's
replacement platform uses different release identities and a transitioning
download layout. This is an implementation scope decision, not a statement that
archive 116 is the newest available Ensembl data. Label it visibly and add modern
Ensembl as a separate provider once its download contract is verified.

Genome, annotation, cDNA, ncRNA and protein resources retain their distinct
roles. cDNA alone must not be labelled a complete transcriptome. No downloads
occur automatically when a saved pipeline is loaded or run. Dataset hashes
record exact bytes and detect later changes; weak provider transfer checksums
must not be described as cryptographic publisher authentication. Interrupted
downloads remain incomplete rather than entering the ready local library.

## Scientific and deployment boundaries

An accepted file extension is not sufficient evidence of compatibility. Genome
and transcript references differ; DNA and splice-aware RNA alignments differ;
sorted BAM is not necessarily duplicate-marked or recalibrated BAM. Sample
identity, reference assembly, strandedness and quantitative assumptions should
be checked or made explicit where required.

Do not equate a PASS VCF filter or a small synthetic fixture with diagnostic
validation. The project supports research workflows and teaching. Workplace/NHS
motivation does not establish clinical suitability, organisational approval or
regulatory status. Normal desktop operation needs no administrator account, but
application-control approval can include the private runtime and every tool.

The native tools are trusted code running as the user. The callback ABI,
argument validation and checksums do not create an isolation sandbox. Treat a
new pack publisher as a trust decision. Keep secrets and user datasets out of
public builds, tests and CI logs.

## How to change a decision

State the problem, proposed change, affected saved contracts and validation
needed. Record whether the change is an implementation detail, a new proposal,
or a user-approved product change. Add a dated replacement decision and link the
superseded one; do not erase the reason for the previous approach. Never treat
this record as authorization to publish or alter account settings in a new
session.

## Galaxy-inspired native interface, 2026-10-05

Following tester feedback, the user approved a Galaxy-like three-pane layout
and workflow editor. This updates D06/D07/D11's presentation direction while
preserving D03's native desktop requirement and the accepted searchable tool
library. The previous central graph/step-list/editor arrangement is superseded;
the rejected wheel designs remain historical.

Tools appear on the left. Selecting one in Tools mode opens its standalone
inputs and options in the centre. General settings occupy the right pane,
including input/output folders and References. A Workflow button opens a canvas
for dragging tools and connecting compatible named outputs/inputs; selecting a
step displays its options on the right. Workbench keeps its own branding and
native controls, with no copied Galaxy assets or dataset-history pane.

Standalone settings and the workflow remain independent, with edits retained
when switching modes within the running process. Saved tool presets and saved
pipeline graphs keep their separate established persistence contracts. Input
folder selection supplies browsing context, not automatic scientific bindings.
Canvas connections retain semantic typing, cardinality, cycle rejection and
exact pack pins; drawing a link is never sufficient evidence of compatibility.

The [native UI guide](native-ui.md) records implementation boundaries and the
0.8.0 development checkpoint. This is a user-approved product direction; native
Windows acceptance and publication are separate evidence, pending at the time
of this decision entry. The completed 0.7.0 release is unchanged.

## Workflow feedback and explicit inputs, 2026-10-06

Testers accepted the three-pane layout but found that automatically creating
file-input cards for each workflow tool obscured chaining and duplicated file
controls. The user requested Galaxy-like explicit inputs: add and name a
reference or a single/paired FASTQ input once, bind its files, and connect that
input or an earlier tool's output to compatible tool ports. This supersedes
automatic input allocation for new Workflow-mode tools. Standalone tools retain
their direct file fields, and existing saved workflow sources, connections and
exact pack pins remain valid.

Each workflow input owns its file controls; selected tools show connections and
run parameters without repeating those file editors. Shared inputs support
fan-out, paired reads retain explicit mate roles, and reference-library binding
works before an input is connected. Removing an input or tool disconnects its
consumers and supports Undo rather than silently bypassing a missing step.

The requested canvas navigation includes dragging empty space to pan, visible
zoom controls and trackpad pinch support where Windows supplies pan/zoom
gestures. Hovering over a card header exposes a delete cross. These are native
presentation features and do not alter dependency order or scientific graph
semantics. Physical trackpad behavior needs hardware validation separately from
automated mouse and keyboard checks.

Testers also requested scientific program names in the tool library and clearer
alignment/indexing guidance. Display labels should name the actual program and
operation while keeping published IDs and saved pins unchanged. The existing
SAMtools sort operation already converts starter minimap2 SAM to sorted BAM;
a duplicate conversion pack is not necessary for this workflow. The standalone
SAMtools faidx operation exports a FASTA lookup index, distinct from aligner
mapping indexes. Starter alignments and variant operations prepare their own
required indexes. The [starter audit](starter-tool-semantics.md) records the
exact supported contracts and limitations.

Scrolling text corruption and the first-open Manage tools array error are bugs
to fix and reproduce in native gates. Source fixes and layout acceptance alone
do not establish a complete workflow acceptance or a released version; current
artifact-specific evidence remains in the [native UI guide](native-ui.md).


## Full, Starter and Custom tool setup, 2026-10-06

After reviewing the measured size of all 32 current packs, the user approved a
small native setup flow that retrieves the existing independently released packs.
**Full is the recommended selection**, Starter keeps the three bundled tools,
and Custom allows a selected subset. This updates D04's onboarding preference;
it does not merge optional tools into core ownership or remove the small Starter.
The measured current selection is approximately 3.81 GB downloaded and 4.67 GB
of initial files, excluding scientific databases, results and run-time expansion.
See the [sizing record](full-bundle-sizing-2026-10-06.md) for exact scope.

Downloads require an explicit user action. Show the missing selection's download
size and per-pack progress; keep each fully verified installed pack if a later
pack fails or installation is cancelled. Persist the exact queue so retry does
not silently select a different version or publisher. Incomplete pack transfers
must not be exposed as installed tools. Starter and offline use remain available.

Keep Manage tools and offline import for future official packs and other
developers' packs. Installed versions, private runtimes, scientific metadata,
licences and matching sources remain pack-owned. Saved workflows keep their
exact existing pins. Core updates preserve packs, user setup state, publisher
configuration, settings, reference files and results.

The bundled Full selection lock records what to install; it is not a trust
root. Official online setup requires a signed catalogue and a reviewed public
source configuration distributed with the application. The existing key policy
(D10) remains binding: a repository token or checksum cannot replace the
maintainer's external signing key. Development fixture keys must never become
production trust. The [setup guide](tool-setup.md) separates implemented behavior
from pending official deployment and exact Windows evidence.
