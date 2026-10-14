# Recovery, execution resources and portable projects

This is the unpublished 0.14.0 development contract. See
[current state](current-state.md) for candidate evidence; historical passes do
not validate new bytes. Published 0.11.0 remains unchanged.

## Restart at completed-step boundaries

Restart reviews an earlier recorded analysis and prepares a **new** result
folder. It does not edit the earlier result or resume inside a running tool.
Only successful steps with a complete declared output inventory are eligible.
The application compares exact tool and manifest pins, installed tool/asset
bytes, parameters, input hashes, reference provenance and upstream dependencies.
It hashes the old outputs and binds the review to the old plan and run records.
Changed or incomplete steps and their downstream consumers run again.
Known Kraken2/Bracken descriptor operations and directory-valued resources run
again because the current pack declarations do not inventory their transitive
external state. Restart does not certify undeclared dependencies in arbitrary
third-party tool code.

Reuse copies verified products into the new result and rechecks their bytes
when consumed. It never treats the original output folder as the new output
folder. Built-in reports run again because their contents include result paths.
Methods, execution records and performance records distinguish copied products
from actual commands; a reused step has no invented native timing or counters.
The exported CWL retains the complete workflow needed for an independent replay.

The native restart review explains which steps can be reused and which must
run again. Queueing is explicit and creates a paused job. A completed-step
restart cannot recover unfinished files from an interrupted scientific command.
If review evidence changes before execution, the operation fails rather than
silently approving different outputs.

## Declared CPU admission budgets

Resource settings control how many ready, independent DAG steps can run
together. They comprise a total logical-CPU scheduling budget, a maximum number
of concurrent steps, optional CPU reservations for individual steps, and a
temporary-storage folder. The default maximum concurrency is one.

**A reservation is not an operating-system CPU limit.** Match each reservation
to the tool's configured thread count. The app neither infers thread use from
option names nor rewrites scientific arguments. A step without a reservation
consumes the whole scheduling budget and runs alone. The sum of admitted
reservations and the number of running steps must fit the selected limits.
Failure blocks dependent steps; independent branches can still complete.
Cancellation reaches active commands and prevents more steps from starting.

General settings persist locally. Per-step reservations are tied to an exact
graph snapshot, including parameter values. Editing the graph invalidates those
reservations; review them again before requesting parallel execution. Prepared
jobs retain their frozen resource policy. The durable queue still executes one
job at a time; concurrency occurs inside that job's DAG.

Temporary work uses an application-owned run-specific directory beneath the
chosen existing folder. Tool subprocesses receive TMP, TEMP and TMPDIR pointing
at their own temporary directory. These owned scratch directories are retained for inspection after a run; the
user may remove them once the run finishes. The application never removes the
user's selected root or unrelated files. Available disk space is an observed snapshot, not a
guarantee that a large analysis will fit. Peak memory, expansion size and tool
CPU usage remain unknown unless separately measured.

## Portable project bundles

An explicitly exported `.nwproject.zip` contains a workflow, exact pack
requirements, file hashes, reference metadata, available sample metadata and a
planned CWL workflow. Data inclusion is optional and explicit. Executable packs,
private runtimes, trust settings and credentials are not bundled.

Portable inputs use dependency IDs. Import inspects the full bounded archive,
reports missing or incompatible exact packs and lets the user map missing data
to local files. Hashes must match. It never silently substitutes a newer pack,
downloads dependencies or runs the imported workflow. Import creates a new
project folder; opening that folder after moving it rebinds included/copied data
relative to its current location. After reopening the application, use **Open
project** to restore those bindings and metadata; ordinary saved workflow
templates are a separate feature. Already queued project jobs retain their
frozen context across application restart. The imported folder has a complete
integrity inventory: keep new analysis results elsewhere, because added, missing
or changed files prevent reopening. Historical project context follows the exact
opened graph; graph edits and rebound batch inputs do not inherit it automatically.
Imported reference receipts retain historical
provenance; they do not authenticate a publisher or register a downloaded
reference in the local library.

The initial contract covers explicitly bound, semantically typed ordinary
scientific input files (for example FASTA, FASTQ, BAM, VCF, BED and metrics).
Generic `file` workflow inputs, directories and database descriptors are rejected because
their full external dependencies cannot yet be established. This conservative
boundary also excludes some ordinary generic-file operations; it is not a claim
that all 32 packs can be bundled. Those types need an explicit closure contract. Archive
validation rejects traversal, links, duplicate/case-colliding members,
undeclared files, excessive sizes/expansion, malformed JSON and mismatched hashes.
These checks are integrity controls, not a sandbox for untrusted native tools.

The bundle's Linux profile states its execution requirements and limitations.
External CWL needs a CWL engine, Python and matching tools/data. A report-only
Linux fixture, if recorded as passing, establishes that fixture's portability;
it does not establish Windows–Linux equivalence for scientific packs or replace
the accepted benchmark programme.

## Implementation and evidence

The engine uses `recovery.py` for completed-product verification and
`execution_resources.py` for admission-policy validation. `project_manager.py`
owns offline bundle contracts. `service.py` and `desktop_host.py` expose bounded
review tokens and explicit commits; the native dialogs are in
`desktop/recovery_ui.h`. `scripts/package_split.py` includes the new runtime
modules in the application inventory.

The candidate workflow is
[native-recovery-candidate.yml](../.github/workflows/native-recovery-candidate.yml).
It must bind reports to exact source, Starter and executable hashes, with
ordinary and spaced Windows paths and separate extractions for independent
gates. Source tests, exact native execution, instrumented transport tests and
manual device acceptance are separate claims. No updater, publication,
representative-machine acceptance or realistic benchmark is implied.
