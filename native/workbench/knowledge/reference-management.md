# Reference management

This is the **unpublished 0.15.0** reference-management set, developed on
`feature/reference-management` from the frozen 0.14.0 review branch at
`38917349449ce56a45d3e0f4f41b7d2a38621c6d`. It implements the first group of
remaining accepted work. Other groups in the [roadmap](roadmap.md) remain
separate. Published 0.11.0 and the tested 0.14.0 candidate are unchanged.

## Explicit retrieval and resumption

References remains a native window. Opening it, listing ready or pending files,
selecting local inputs and running analysis do not contact a provider. Search,
discovery, Download and Resume are explicit online actions. No analysis files,
sample metadata or local import descriptions are uploaded.

Downloads retain compressed bytes in private staging below
`user-data/references/pending`. **Pause** retains a checkpoint; **Resume** first
checks its pinned discovery and recorded prefix hash, then requests the remainder
when the server supplies a usable entity/date validator. Ignored ranges, changed
validators or unsuitable responses cause a checked full restart, not blind
concatenation. A network interruption or application crash can leave a resumable
job. Nothing in pending storage is offered as a ready analysis input.
An abrupt kill during expansion can also leave an unregistered destination
staging folder; it remains unavailable and is not treated as a completed bundle.

**Cancel** discards the active incomplete download; **Discard** removes a selected
pending job. Completed references remain unchanged. Users must explicitly resume
paused/interrupted work; application startup never starts network work.

All selected compressed files must pass their provider transfer checksums and
complete gzip CRC, bounded expansion and basic FASTA/GTF checks before the bundle
is published. SHA-256 records compressed and expanded byte identities. Ensembl
uses BSD sum; NCBI uses MD5. These provider checksums are transfer-integrity
evidence, not signed publisher authentication. Atomic registry publication and
OS-managed leases protect concurrent operations; a process crash does not leave
an ownership-marker lock that must be manually bypassed.

Compressed staging requires additional local disk space. Limits remain 100 GiB
compressed and 500 GiB expanded per selection, with bounded metadata and pending
jobs. A retained checkpoint may need to restart when a provider changes an
object or supplies no usable range validator. It cannot guarantee that a public
provider will retain historical bytes indefinitely.

## Ensembl archive and NCBI RefSeq

The existing Ensembl archive provider retains releases 100–116 and all five
roles: genome, GTF, cDNA, ncRNA and protein. It is not relabelled as the newest
Ensembl platform.

The additional **NCBI RefSeq** provider looks up one exact **versioned assembly
accession**, such as `GCF_000146045.2`. This is an accession lookup, not a general
species-name search. It queries the official NCBI Datasets assembly report and
discovers supported files from the corresponding approved GCF FTP directory and
`md5checksums.txt`. Genome FASTA, GTF and protein are offered when available.
NCBI's combined RNA file is not presented as cDNA or ncRNA. The supplied genome's
sequence scope and lowercase masking are retained in provenance.

An assembly accession is not an immutable annotation release. NCBI can update
annotation files for the same assembly. Receipts therefore record the observed
annotation name, provider/date, metadata and checksum-manifest hashes, URLs and
exact downloaded bytes. Where supplied, GTF assembly/annotation headers are
checked against discovery. A later discovery can produce different byte identities
without changing the assembly accession; existing local receipts remain fixed.

Official contracts:

- [NCBI Datasets REST API](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/rest-api/)
- [Assembly data report](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/reference-docs/data-reports/genome-assembly/)
- [Genome FTP files and annotation updates](https://www.ncbi.nlm.nih.gov/datasets/docs/v2/data-processing/policies-annotation/genomeftp/)

The transport accepts only approved HTTPS API/FTP objects and validates redirects.
Custom user URLs, GenBank accessions, new-platform Ensembl, known-sites bundles
and arbitrary database imports are outside this provider contract.

## Import existing local reference files

Import local accepts one file per selected role, up to five: genome FASTA, gene
annotation GTF, cDNA, ncRNA and protein. Plain files and gzip files are supported.
The user supplies descriptive species, assembly/accession, release and source
fields and chooses a destination. Preview hashes the source, validates/expands
gzip as needed and shows the exact file identities. Confirmation rechecks those
reviewed bytes, copies the files into a new owned bundle, rehashes the copy and
records it atomically. Original input files remain unchanged.

Imported descriptions are explicitly **user-declared**. A local SHA-256 match
does not authenticate the stated species, assembly or source, and basic format
checks do not establish scientific compatibility. Provenance and methods text
preserve this distinction from provider retrieval. Existing ordinary unregistered
local inputs continue to work.

Reviews are bounded, expire after 15 minutes and can be committed once. Changed
files, altered/replayed reviews or a changed library require another preview.
Cancellation and failed writes do not publish a partly imported bundle.

## Change the library location

The relocation review inventories every active bundle and verifies its file and
receipt identities. Confirmation copies the bundles into the chosen destination,
rehashes the copies, then atomically switches the library and default download
destination. The registry remains in application user-data, so normal application
updates preserve it.

**Original folders and receipts are retained.** Saved workflows and frozen queued
plans may still name those paths, and their original provenance remains available.
Relocation does not rewrite completed results, frozen plans or saved graphs.
It does not automatically reclaim disk space. Delete an old folder only after
separately resolving every workflow or result that still needs it; this feature
does not make that decision for the user.

All active bundles must be present and unchanged for relocation. A missing or
modified file stops the operation. Failed copies or registry writes leave the
original library usable. Abrupt interruption can leave unregistered staging or
copied directories for inspection; unregistered copies are not ready references.
Symlinks and Windows junctions are rejected for managed locations.

## Implementation and evidence

`reference_transfer.py` owns persistent compressed staging and resume rules;
`reference_library.py` owns local import and relocation reviews;
`reference_ncbi.py` owns the additional provider. `ReferenceManager` integrates
these with existing receipts. The service supplies asynchronous operations,
private one-use review tokens and cancellation; the native References window
provides the controls.

Current validation status is recorded in [current state](current-state.md) and
the [candidate handover](reference-management-0.15.0-handover.md). Source fixtures,
live Linux transport, exact packaged Windows execution and representative-machine
acceptance remain distinct. This set does not perform the broader benchmark
programme or authorize publication.
