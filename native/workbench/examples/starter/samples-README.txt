Synthetic sample table

samples.csv describes one artificial sample, starter: 101 paired reads and the
3,000-base synthetic starter reference. It uses the same unchanged input data as
the alignment-with-QC and variant-calling training workflows. There are no
independent biological replicates in this example.

Open Samples and choose Example to inspect verified absolute input paths in the
native editor, or import samples.csv directly. For the CSV, keep this folder as
the base for relative paths. Map read1 and read2 explicitly to their paired-read
fields and reference to the workflow's reference field. Map sample_id to the
pack's sample option where needed. The table does not choose or run a workflow.

The native Example action requires exact align 0.4.0 and verifies the original
fixture bytes. Curated workflows list their additional exact requirements and
known answers. Expected answers apply only to the unchanged training workflow,
inputs, tool versions and settings. They are not general QC pass thresholds.

When saving a table elsewhere, mark every column containing file paths. Save as
converts only those explicitly marked cells to absolute paths; other columns
remain unchanged metadata. Choose a new filename: existing files are preserved.
If you move this folder, importing this relative CSV still uses its new folder;
an exported table with absolute paths must be edited to reflect moved inputs.

Synthetic fixture and table: repository MIT license; see LICENSE.
