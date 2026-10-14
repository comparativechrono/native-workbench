# Reference discovery and local downloads

Native Workbench 0.7 adds a native **References** window. Reference datasets are
independent of executable packs. The starter still contains only minimap2,
SAMtools and BCFtools; it does not bundle a human genome or a taxonomic database.

## Using references

1. Open **References**, choose an Ensembl archive release and search for a
   species. Check the assembly name and accession in the result.
2. Select the species and find its files. Choose the resources needed by your
   analysis, then choose a local destination and download them.
3. The download is checked and expanded into ordinary FASTA/GTF files. A bundle
   appears in the local library only after all selected files succeed.
4. Add a tool to your analysis, select a downloaded file and choose its compatible
   input using **Use for input**. Existing named inputs are listed explicitly;
   a download does not silently replace an analysis input.
5. Review the methods text before running. The engine hashes the selected local
   inputs and checks registered reference identities before freezing the run.

The local library works offline. You can also browse directly to a downloaded
file using an ordinary tool input. A registered file's provenance follows its
path into the run whichever selection route you use. Arbitrary existing local
files continue to work without registration.

## What the initial provider covers

The first provider is **Ensembl archive**, releases 100–116, using the compact
release-specific species catalogue for vertebrates and selected model organisms.
It does not cover every Ensembl division or every assembly available elsewhere.
The exact available files are discovered from published directory manifests;
filenames are not synthesized from a release number.

| Resource | Meaning |
| --- | --- |
| Genome FASTA | Unmasked primary assembly where available; otherwise the archive's unmasked toplevel file. The selected sequence set is recorded. |
| Gene annotation GTF | Annotation distributed for that species in the selected archive release. Its filename can carry a different Ensembl Genomes release number. |
| Transcripts, excluding ncRNA | `cdna.all` annotated transcripts, including applicable pseudogene/NMD transcripts; not a complete transcriptome including ncRNA. |
| ncRNA FASTA | Separate noncoding RNA sequences. |
| Protein FASTA | Annotated protein translations, not ab initio predictions. |

No identifier rewriting, sequence conversion or cDNA/ncRNA concatenation is
performed. Original contig and transcript version identifiers are retained.
Unavailable resource kinds are reported. A GTF and a genome need matching
assemblies and contig names; provenance does not make an arbitrary combination
biologically compatible. Downloading a reference does not reduce a tool's RAM,
disk or indexing requirements.

Ensembl's classic platform ends at release 116. The replacement platform has
different data releases and a changing download layout. This provider is
deliberately labelled as an archive and makes no claim to serve the newest
Ensembl data. A future provider can be added without changing local reference
receipts or tool-pack versions. See the [official transition announcement](https://www.ensembl.info/2026/02/12/whats-coming-in-ensembl-release-116-ensembl-genomes-63/).

## Local files, integrity and provenance

Each successful selection produces a new `ref-…` directory containing expanded
files and `reference.json`. Existing reference bundles are never overwritten.
The application's `user-data/references/library.json` records their locations.
Keep the downloaded folder in place and retain `user-data` when updating the app.
The core updater preserves this data and optional packs.

The receipt records provider, archive release, species, assembly/accession,
selected sequence set, source catalogue and checksum-manifest hashes, requested
and effective HTTPS URLs, retrieval time, compressed/expanded sizes and SHA-256
hashes. gzip CRC and basic FASTA/GTF header checks are applied. These header checks
are not a complete scientific validation of every annotation or sequence.

Classic Ensembl `CHECKSUMS` contains **BSD sum**, computed over compressed bytes,
and a count of 1024-byte blocks. It is not MD5 or a cryptographic signature.
Workbench verifies that transfer checksum and computes SHA-256 locally for
subsequent identity checks. Neither constitutes a signed publisher attestation.
Release URLs can be corrected by the provider; saved hashes identify the actual
bytes obtained. Provider data notices are retained; data is not assigned the
software's licence merely because it was downloaded through Workbench.

For registered reference inputs, a prepared run contains:

- `plan.json`: frozen reference metadata alongside exact input hashes;
- `reference-provenance.json`: reference download evidence for its inputs;
- `methods-planned.txt` and, after execution, `methods-completed.txt`: species,
  assembly, release and resource descriptions;
- `run.json`: frozen reference metadata and each step's completion status.

Completed methods describe references attached to successfully completed steps.
They use the frozen plan even if the local library is later changed or removed.
A registered reference whose bytes differ from its receipt is rejected before a
new run is created. For an intentionally edited reference, use an independent
local copy; it must not inherit the original download's identity.

## Network and interruption behavior

Only explicit discovery/download actions contact the provider. Startup, local
library browsing, methods previews and scientific execution do not refresh
references. No reads, sample names or analysis files are uploaded by this feature.
The finder uses standard HTTPS with certificate checks and normal system proxy
handling. It does not bypass institutional network policy or require a browser.

Downloads stream into a private temporary directory and support cancellation.
Truncated transfers, changed discovered sizes, checksum failures, corrupt gzip
data and insufficient disk space fail without publishing an incomplete bundle.
Expanded files can be substantially larger than the displayed download size.
This first version restarts interrupted downloads; it does not resume byte ranges.
An application/process crash can leave a temporary directory for manual cleanup,
but a partial directory is never treated as a ready reference.

The first version does not discover NCBI/RefSeq, new-platform Ensembl datasets,
custom URLs, known-site VCF bundles or Kraken/Bracken databases. Existing local
input and pack-specific database workflows remain available.

## Implementation and extension contract

- `workspace/reference_provider.py`: bounded, release-specific metadata discovery
  and restricted HTTPS transport, including redirect validation.
- `workspace/reference_manager.py`: streaming transfer, validation, atomic local
  publication, receipts and offline library lookup.
- `workspace/reference_provenance.py`: offline preview/frozen-run evidence and
  methods text; the graph cannot assert trusted reference provenance.
- `workspace/service.py` and `desktop_host.py`: asynchronous operation lifecycle,
  progress, cancellation, explicit input binding and shutdown.
- `desktop/desktop_workspace.cpp`: native finder/library window and file dialogs.

Providers resolve immutable session selections; a client requests known resource
IDs from such a selection, never an arbitrary URL. New providers need their own
discovery semantics, checksum interpretation, limits, provenance and tests. Do
not merge a modern Ensembl assembly release or annotation date into an archive
release's identity. Reference data remains outside executable packs and the core
application inventory.
