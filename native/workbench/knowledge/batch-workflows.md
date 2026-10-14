# Sample tables and durable analysis queues

This describes the **unpublished 0.13.0 development candidate**. It is a behavior
and recovery guide, not release or native validation evidence. See
[current state](current-state.md) for the candidate's exact validation status.

## Import and review samples

Build a workflow with explicit named inputs, then open **Samples**. The window
uses a copy of the workflow selected when it opens; later workspace edits do not
alter that copy. Close and reopen Samples to use a different draft.

1. Choose and load a UTF-8 CSV or TSV file containing an exact `sample_id` column.
   IDs must be unique, including letter case. Relative file paths resolve against
   the table's own folder; they do not use the application's working directory.
2. In **Independent samples**, map table columns to the named workflow inputs.
   Map read 1 and read 2 separately. No filename guessing supplies missing mates.
   Options can also be mapped explicitly to columns, such as a sample/read-group
   name. Pack-declared sample identity options initially select `sample_id`.
3. Reference inputs can keep their shared workflow value. Other eligible resources
   need an explicit shared-resource choice. Reads, alignments and sample variant
   files cannot be declared shared across independent rows. Repeated non-shared
   file paths are rejected. Existing sample bindings do not silently become
   inputs for every row.
4. Choose **Preview analyses**. All rows are checked before a batch can be accepted.
   Preview creates no run folders and executes no tools. Correct invalid rows or
   import a deliberately smaller table; there is no automatic skipping of rows.
5. Choose a parent output folder, then **Queue reviewed analyses**. This prepares
   and hashes every accepted analysis. Open **Analysis queue** and choose
   **Start queued** separately to begin execution.

Condition, replicate and other imported columns remain local provenance. They do
not automatically configure a statistical model, prove biological independence,
or select case/control groups. Those choices remain explicit tool options and
workflow connections. Actual input hashes and scientific preflight belong to
preparation/execution; a successful table preview is not a completed analysis.

An imported table and an accepted preview each have an immutable, host-local
15-minute token. Editing the table file afterward does not change the imported
copy. Expired or evicted tokens require loading/reviewing again. A batch preview
can be queued once. Changing mappings requires a new preview.

## Explicit combined reports

**Combined reports** creates one job from a chosen table column and an explicitly
selected report input. This is available only for a pack-declared many-valued
`metrics` or `text` port with one file field. Each row supplies a separately named
source; duplicate files, incompatible types and exceeded port cardinality fail
validation. Additional workflow inputs must be valid shared resources.

This mode combines already produced report inputs. It does not pool reads,
perform cohort variant calling or infer a differential-expression design. All
row metadata is retained in the single job, subject to the per-job metadata
limit. An oversized combined report must be split explicitly; metadata is never
silently discarded to fit.

## Queue behavior and frozen results

**Queue current analysis** adds the current individual tool or workflow without a
sample table. It freezes the committed draft using the same engine as Run.
Samples and individual analyses share one serial execution queue.

Each job binds exact tool/version/manifest pins, parameters, external input hashes,
reference provenance and the prepared result-folder files. The application
records the plan and companion file hashes in `user-data/run-queue.json`. Before
execution it rejects changed preparation files, unexpected result-folder entries
and plans that already started. The engine independently checks its plan/CWL
binding, installed tools, external files and upstream outputs before consumption.

Source data are referenced and hashed, **not copied into the queue**. Keep those
files and the required installed pack versions available and unchanged. A newer
installed pack does not silently replace a queued pin. Editing the workspace
while a run executes changes only the next draft.

**Start queued** selects the jobs already ready at that moment. New additions
need another explicit Start after the current selection finishes. **Pause after
current job** lets the running analysis finish and leaves its successors queued.
Cancelling a waiting job affects that job; cancelling a running job also pauses
its successors. Cancelling preparation stops the entire preparing batch. If any
row fails preparation, none of that batch becomes executable. If execution fails,
the remaining jobs stay queued until the user explicitly starts them again.

Batch identity, sample identity, imported columns and explicit mappings are frozen
into `plan.json`, carried into `run.json`, and included in the packed CWL metadata.
Each independent sample has a separate result folder. Existing methods, commands,
reference provenance, output hashes and performance records remain per-run
artifacts. Redacted diagnostic exports do not include the sample table metadata.

## Reopening, ownership and recovery

The queue never starts automatically when the application opens. Clean closure
cancels current preparation/execution and preserves waiting jobs. After an abrupt
host exit, recorded `preparing` or `running` jobs become **interrupted**; their
result folders remain available for inspection. Other ready jobs remain queued.

There is no automatic retry or restart from a completed step in this tranche.
Inspect a failed, cancelled or interrupted result, correct its cause, then prepare
a new job with a new result folder. Do not delete a run marker or edit a saved plan
to make it appear unstarted. Some failed batch preparations may leave prepared
folders; those are evidence, not independently approved jobs.

An operating-system lock allows only one host to own writes/execution for an
installation. A second host reports that it is read-only and can inspect drafts
and diagnostics. Close the owning host, then reopen the second window to acquire
ownership. A leftover lock filename is harmless: the operating system releases
the lock when its owner exits. Never delete a lock file to steal ownership.

Malformed queue state is preserved and blocks execution rather than becoming an
empty queue. Keep `user-data/run-queue.json`, the results and available diagnostic
evidence for recovery. Do not overwrite the file or mark an uncertain job complete.
Queue updates use atomic replacement and file synchronization; this does not
promise recovery from physical disk damage or arbitrary filesystem corruption.
On Windows, a short-lived reader can obstruct atomic receipt replacement. Queue
and run-history commits retry only that prepared rename, up to nine attempts
with 550 ms total retry waits for sharing/access errors. Persistent errors still
propagate, preserving the previously committed file and state. The retry never
restarts an analysis and does not remove the destination as a fallback.

## Bounds and implementation map

| Area | Current bound |
| --- | --- |
| Imported table | 8 MiB UTF-8; 1,000 rows; 64 columns; 4,096 characters per cell |
| Identifiers | `sample_id`: 1–128 letters/digits/underscore/hyphen/dot, starting with a letter or digit; column names: 1–64 characters, starting with a letter |
| Independent queued batch | At most 200 jobs; every row must validate |
| Queue records | At most 200 retained entries and 4 MiB serialized state; terminal entries may be removed from the queue list to make room, preserving result folders and the separately bounded run history |
| Expanded batch snapshot | 32 MiB; four tokens and 32 MiB retained total per token cache; expiry after 15 minutes |
| Per-job batch metadata | 16 KiB including its batch/sample wrapper; no silent truncation |
| Displayed table preview | First 100 rows, additionally bounded to 256 KiB; omitted rows are reported |
| Displayed preview errors/warnings | 200 entries or 256 KiB each; omission counts are explicit; hidden display details do not change validation outcome |

`workspace/sample_table.py` parses and validates explicit mappings;
`workspace/run_queue.py` owns the durable store, OS lock and frozen-file checks;
`workspace/service.py` owns preparation, token snapshots and serial dispatch;
`workspace/desktop_host.py` exposes the private bounded JSON-lines methods;
`desktop/desktop_workspace.cpp` supplies the native Samples and Analysis queue
windows. Source lifecycle/negative controls live in
`workspace/tests/test_run_queue.py` and `workspace/tests/test_sample_table.py`.
Exact packaged Windows checks are defined separately in
`scripts/check_batch_windows.py`; their existence alone is not a pass claim.
The [candidate handover](batch-queue-indexes-0.13.0-handover.md) binds their
recorded outcomes to the exact packaged application and validator revisions.
