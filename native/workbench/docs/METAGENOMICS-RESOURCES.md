# Local Kraken2 and Bracken resources

This contract separates small executable packs from potentially large scientific
databases. It uses ordinary files and the existing Workbench 0.6.0 graph types;
it does not require an application update, database upload, system interpreter,
shell, Docker or WSL. The shared implementation is
[`tools/metagenomics/resources.py`](../tools/metagenomics/resources.py).

These are resource and provenance checks, not validation of taxonomic accuracy.
Hashes identify unchanged bytes. They do not authenticate a database publisher,
prove that a distribution was built from particular reference genomes, or make
user-editable JSON resistant to forgery.

## Database preparation and selection

The Kraken2 adapter's registration operation selects the existing `hash.k2d`
file. It locates `opts.k2d` and `taxo.k2d` in the same folder, inspects the actual
Kraken options and rejects unsupported database formats. It records a label,
source description, source URL when available, release, file sizes and SHA-256
hashes. It never changes or copies that database. Optional Bracken distribution
files are individually selected and hashed.

Registering an external Bracken distribution requires an explicit user
declaration that it was generated for these exact Kraken2 database bytes, its
stated read length and the standard classification model. A filename such as
`database150mers.kmer_distrib` supplies a declared read length, not proof of it.
Colocation and matching taxonomy identifiers do not establish model origin.
Methods and provenance must retain `user-attested-external` for that association.

For downloaded local `.tar`, `.tar.gz` or `.tgz` resources, the archive helper
extracts the three Kraken index files. Classification-only mode, the helper's
default, skips Bracken distributions. Explicitly selecting matching-model
registration also extracts up to 64 standard-named Bracken distributions.
Unsafe archive members are rejected even when their contents would be skipped.
The helper creates a unique `database-resource-*` child in the selected
results location. It records the original archive's name, size and SHA-256.
The registration adapter must still inspect the extracted options and obtain
the same source and model declarations; extraction does not establish them.

Required files may appear at the archive root or under one common directory
prefix. Links, special files, sparse members, parent traversal, absolute paths,
duplicate/case-colliding paths and inconsistent required-file prefixes fail.
The reader streams payloads, permits at most 100,000 headers, bounds member paths
to 1,024 characters and extension headers to 1 MiB each / 16 MiB total with at
most 32 nested extensions, and checks free disk before
each selected file. Ignored ordinary ancillary files are not extracted. Gzip
streams are consumed through their trailers to validate CRC and length. Failure
removes only the helper's newly created child. Successful extracted databases
remain in the result folder and must be retained for later classification.

The executable pack's 1 GiB expanded-size limit does not apply to these local
scientific inputs. Database size, verification time, memory and storage still
matter. Registration and Kraken classification hash all three index files;
large databases therefore incur sequential disk reads. The adapter checks again
after classification and fails if the database changed. This observes file
changes; it is not an operating-system transaction against hostile modification.
Bracken uses the distribution and report, so it does not rescan unused Kraken
indexes or require them to remain present when a retained descriptor and
classification record are sufficient.

## Database descriptor, schema 1

All fields below are required unless indicated. Unknown fields, duplicate JSON
keys, nonfinite numbers, invalid integers and documents over 4 MiB fail.

| Field | Meaning |
| --- | --- |
| `schema` | Integer `1`. |
| `kind` | `native-workbench-kraken2-database`. |
| `databaseRoot` | Absolute local registration path, or `.` / a safe descendant path relative to the descriptor. |
| `label` | User-facing database label. |
| `source` | Object with `description`, `url` (may be empty) and `release`. Optional `archive` has `name`, `bytes`, `sha256`. |
| `files` | Exactly `hash.k2d`, `opts.k2d` and `taxo.k2d`, each with positive integer `bytes` and lowercase `sha256`. |
| `databaseFingerprint` | SHA-256 of the canonical UTF-8 `files` object described below. |
| `kmerLength`, `minimizerLength` | Actual options inspected by the Kraken adapter, not inferred from a distribution filename. |
| `alphabet` | `nucleotide`; translated protein databases are outside this pack contract. |
| `brackenDistributions` | Zero to 64 distribution records, with a unique read length and path for each. |

The fingerprint uses Python's equivalent of
`json.dumps(files, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)`
encoded as UTF-8, then SHA-256. Absolute filenames, display labels, distribution
files and source text are excluded. This allows relocation without changing the
identity of the three Kraken indexes.

Each distribution record contains:

| Field | Meaning |
| --- | --- |
| `readLength`, `kmerLength` | Declared simulated single-read length and matching database k-mer length. |
| `path`, `bytes`, `sha256` | Absolute explicitly selected filename, or a safe descendant path relative to `databaseRoot`, and its content identity. |
| `databaseFingerprint` | Exact identity of the associated three-file Kraken database. |
| `association` | `user-attested-external`, or `locally-built` only when a separate verified construction process establishes that association. Registration never claims `locally-built`. |
| `source` | Description, URL and release, with optional original archive identity. |
| `classifierSettings` | `confidence`, `minimumHitGroups`, `minimumBaseQuality`, `quick`; registration records the explicitly declared standard model `0`, `2`, `0`, `false`. |

All referenced consumed files must be ordinary files. Symbolic links, Windows
junctions/reparse points and such ancestors fail. Relative paths cannot escape
their base or use Windows reserved names. Absolute paths from another operating
system require local registration again. The adapter does not silently search
other drives, directories or the network when a resource has moved.

The descriptor is an ordinary graph `file`. Released 0.6.0 parses and renders
manifest `directory` inputs, but its graph preparation still requires ordinary
files. A directory port therefore cannot implement this contract on that
release. Database registration avoids both this mismatch and the need to encode
large scientific data inside executable pack archives.

## Classification record, schema 1

Kraken produces a normal six-column report as an independently visible output.
Its pipeline connection to Bracken is a small ordinary `file` with these fields:

| Field | Meaning |
| --- | --- |
| `schema`, `kind`, `success` | `1`, `native-workbench-kraken2-classification`, `true`. Failed classifications cannot produce a successful record. |
| `databaseFingerprint` | Exact registered Kraken index identity used for this run. |
| `report` | `path` is a sibling filename; `bytes` and `sha256` bind its content; `format` is `kraken2-six-column`. |
| `classifier` | `name: Kraken2`, actual upstream `version`, plus the four classifier settings above. |
| `reads` | Counts and observed mate statistics as specified below. |

`reads` has `paired`, `unit`, `fragments`, `reads`, `bases`,
`classifiedFragments`, `unclassifiedFragments`, `mate1` and `mate2`.
Single-read input uses `unit: reads`, `reads == fragments`, and `mate2: null`.
Paired input uses `unit: fragments`, `reads == 2 * fragments`, and both mate
statistics. Each mate object contains `records`, `bases`, `minLength` and
`maxLength`. Mate record counts equal the fragment count, lengths and base totals
must agree, and classified plus unclassified fragments must partition all
inputs. An all-unclassified run is valid classification evidence, not a failed
program or an abundance estimate.

Kraken's paired classification assigns one label per pair. Neither the raw
report nor Bracken output should be relabelled as individual-mate counts or
doubled. Bracken's distribution read length is the individual read length,
not the insert size or the sum of mate lengths. The estimation adapter checks
the exact selected distribution, standard model settings, read-length policy,
report tree/count structure and no-hit behavior separately. A representative
read-length approximation, if exposed, must be explicitly selected and recorded.

The shared validator checks record semantics and report identity; the Bracken
adapter validates actual six-column tree syntax and counts before running the
unchanged upstream estimator. Standard six-column output is deliberate: MPA
reports and extra minimizer-column reports are different formats.

An optional external-report operation must require explicit database/model,
read-length and unit declarations. It must record user-attested external
classification provenance, not fabricate a successful Workbench classification
record or treat filename/format compatibility as provenance.

## Shared Python API

| Function | Contract |
| --- | --- |
| `file_record(path)` | Return `{bytes, sha256}` for an ordinary file; reject observed changes during hashing. |
| `database_fingerprint(files)` | Validate and fingerprint exactly the three index records. |
| `write_json(path, document)` | Write LF-terminated UTF-8 JSON with exclusive creation. |
| `validate_resource(path, verify_database=False)` | Return `{document, path, sha256, root, paths}`. `paths` maps index names to absolute `Path` objects. Set `verify_database=True` before and after Kraken use. |
| `choose_distribution(resource, read_length, verify=True)` | Return `{document, path}` for one exact length; hash the consumed distribution by default. |
| `validate_classification(path, resource)` | Return `{document, path, sha256, report}` after checking schema, units, selected database identity and sibling report hash. |
| `validate_registration_metadata(*, label, source_description, source_url, source_release, archive=None)` | Validate inexpensive declarations before archive extraction; return the validated source object. |
| `register_database(anchor, output, *, label, source_description, source_url, source_release, kmer_length, minimizer_length, distributions=(), attest_distributions=False, archive=None)` | Create a descriptor for inspected existing index files; return its validated resource. |
| `extract_database_archive(archive, output_parent, include_distributions=False)` | Return `{root, anchor, distributions, archive}` after safe extraction. Set `include_distributions=True` only for explicitly selected model registration. `archive` is original archive identity for registration. Caller retains/removes the owned root according to subsequent registration success. |

Focused non-scientific tests are in
[`tests/test_metagenomics_resources.py`](../tests/test_metagenomics_resources.py).
They use synthetic byte files to check integrity, provenance, paired units,
relocation, path rejection, archive bounds and cleanup. They do not execute
Kraken2 or Bracken and do not establish native Windows scientific behavior.

## Upstream references

- [Kraken2 manual](https://github.com/DerrickWood/kraken2/wiki/Manual): the three database files, paired fragment output, report formats and classification settings.
- [Bracken README](https://github.com/jenniferlu717/Bracken/blob/master/README.md): database-specific/read-length-specific distributions and upstream abundance estimation.
- [Bracken manual](https://www.ccb.jhu.edu/software/bracken/index.shtml?t=manual): distribution construction from the database reference sequences.

Use the corresponding pinned upstream sources in each pack's build record when
rebuilding; these live manuals can change independently of a released pack.
