# NCBI BLAST+ local similarity pack

Pack `blast` 1.0.0 exposes upstream BLAST+ 2.17.0 in Workbench 0.6.0. It builds
a private database from local FASTA sequences, performs a local search and saves
the scientific results. It never requests an NCBI remote search or downloads a
sequence database. NCBI usage reporting is explicitly disabled for child tools.
Implicit GenBank sequence loaders are disabled, and formatting a result whose
local database is missing fails locally instead of contacting a remote server.

| Operation | Query input | Database input |
| --- | --- | --- |
| `blastn` | Nucleotide FASTA | Nucleotide FASTA |
| `blastp` | Protein FASTA | Protein FASTA |
| `blastx` | Nucleotide FASTA, translated in six frames | Protein FASTA |
| `tblastn` | Protein FASTA | Nucleotide FASTA, translated in six frames |

Use **Manage tools > Import pack ZIP** with the installable `native-workbench-pack-`
archive. Use **Check installation** to run the five synthetic scientific cases,
including known alignment coordinates and a legitimate no-hit result. These are
research and teaching operations, not clinically validated interpretation.

## Inputs and choices

Inputs must be uncompressed, unaligned FASTA. The adapter scans every record
before indexing. The first header token is a unique identifier of at most 200
ASCII letters, digits, underscores, dots, colons or hyphens. Pipes are deliberately
rejected because NCBI treats them as structured sequence IDs. Headers must be
printable ASCII; sequences must contain residues without whitespace or gaps.
Nucleotide inputs accept IUPAC DNA, including ambiguous bases but excluding U.
Protein inputs accept standard amino acids, B/J/O/U/X/Z and `*`. No conversion,
gene prediction or inference of the biological alphabet is performed. Empty
records, duplicate IDs and malformed data fail before database construction.

Choose the E-value threshold and target cap for the scientific question. The
default is `1e-5`, 500 target sequences and two search threads. E-values depend
on database size. The target cap is BLAST's heuristic retention limit, not an
exhaustive guarantee of every equally good hit. Database record order can break
ties. Similarity alone does not establish gene function or organism identity.

BLASTN offers `blastn`, `megablast` and `blastn-short`. Both strands are searched
with DUST masking enabled. Protein/translated searches use SEG masking and
upstream BLOSUM62, gap and composition-statistics defaults. For translated
searches, select the genetic code from the nucleotide sample's biology; the
pack does not infer it. Other advanced switches are not exposed in this version.

## Results

- `hits.tsv`: one line per retained HSP, no header; legitimately empty if there
  are no hits. Columns are `qseqid sseqid pident length mismatch gapopen qstart
  qend sstart send evalue bitscore qlen slen qframe sframe`, separated by tabs.
- `search-report.txt`: the same fields with BLAST comments, version, query and
  database details, explicit column headings and per-query hit counts.
- `search.asn`: the native BLAST ASN.1 archive. Preserve the complete run folder
  and its private `blast-database.*` files if reformatting this archive later;
  the archive is not advertised as an independent reusable database product.
- Validation JSON files and database-build log; Workbench also retains its
  methods, versions, parameter values, commands and input provenance.

Coordinates are **one-based and inclusive**, as defined by BLAST. Nucleotide
coordinates in translated searches are still nucleotide positions, while
alignment length is in aligned amino acids. Reverse-strand coordinates can
decrease; the query/subject frame columns retain upstream values (BLASTP reports
1/1 for protein alignments, not biological nucleotide reading frames). Multiple HSPs are
possible for a query/subject pair. These files are similarity results, not SAM,
BAM, gene counts, variant calls or a multiple-sequence alignment.

Each run builds a parsed-ID version-4 BLAST database. Workbench 0.6.0 does not
support reusable directory-valued graph products, so existing NCBI database
folders and reusable BLAST indexes are not exposed. Keep sufficient local disk
for the database, archive and reports; large searches can require substantial
RAM, time and storage. The thread setting is not a memory cap. Remote searches,
automatic database retrieval, taxonomy assignment, PSI/DELTA/RPS-BLAST and VDB
searches are outside this pack.

## Build and validation

The release recipe uses the official, SHA-pinned NCBI source archive with no
scientific algorithm changes. One path compatibility patch quotes the absolute
database name when makeblastdb reopens its new database to write metadata;
upstream 2.17.0 otherwise splits a path containing spaces and fails after writing
the index. A second bounded patch disables implicit GenBank loaders and removes
the formatter's remote fallback when its local database cannot be opened, plus
both shared query-scope remote BLAST database fallbacks. Optional absent local
query loaders remain absent; failure of an explicit database remains an error.
Original and patched source-file hashes are checked before packaging. NCBI's
supported MSVC CMake static-runtime setting
is used to avoid depending on an installed Visual C++ Redistributable. SQLite
3.50.4 is built from its pinned public-domain amalgamation with the same static
runtime; other required libraries come from the NCBI source tree. No separately
downloaded MSVC runtime DLLs are included. Build prerequisites apply to pack
maintainers, not users of a prepared pack.

On Windows with a licensed Visual Studio 2022 C++ x64 build environment, CMake
3.31.6 and Python available for packaging:

```powershell
./scripts/build_blast_windows.ps1 -Output C:/blast-build
python scripts/prepare_blast_pack.py --native-build C:/blast-build --destination C:/packs/blast-1.0.0
python scripts/package_split.py pack --pack-root C:/packs/blast-1.0.0 --output C:/releases/native-workbench-pack-blast-1.0.0.zip
python scripts/validate_pack_release.py C:/releases/native-workbench-pack-blast-1.0.0.zip
```

The build record includes source, compiler, configuration, executable hashes,
runtime version checks and observed DLL imports. The small Workbench C++ boundary
adapter validates FASTA and launches only exposed BLAST programs with separate
arguments, disabled telemetry/configuration and explicit BLAST database-list
quoting. It does not alter scoring or alignment algorithms. The Windows process
runner's cancellation job covers descendants. The adapter does not create a
security sandbox.

The Windows adapter explicitly forwards the parent's standard handles to its
hidden child, preserving BLAST's diagnostic output in the run log. An adapter-only
rebuild, when used, retains the original scientific build record unchanged and
adds a separate `adapter-provenance.json`, bound to all six original executable
hashes and the new adapter's source, compiler and startup checks.

Full matching NCBI and SQLite source archives, notices, build provenance and the
adapter source are included under shallow `licenses/` paths. Keep exact final
native Windows evidence separately: preparation and Linux reference tests do
not establish Windows scientific execution. Final publication notes must name
the exact archive hash and native test run, including any remaining limitations.

Sources: [NCBI source and releases](https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/),
[BLAST manual](https://www.ncbi.nlm.nih.gov/books/NBK279690/),
[BLAST+ paper](https://doi.org/10.1186/1471-2105-10-421).
