# Scientific pack metadata

The execution authority remains `pack.ini`. A format-2 pack can declare
`[asset:workbench-schema]`, with a relative JSON path and its SHA-256. The
catalogue verifies that asset at discovery, preparation and execution. Every
manifest file input and output must occur exactly once in the metadata. Unknown
fields, types and rules are rejected; there is no fallback to filename inference.

The additions below require **Native Workbench 0.5.3 or later**. Workbench 0.5.2
rejects their unknown metadata fields and types. Pack READMEs must state the
minimum supported workbench version. No schema field supplies executable code.

## Paths and related parameters

These optional fields belong inside a workflow definition:

```json
{
  "pathPolicy": {
    "asciiOnly": true,
    "forbiddenCharacters": [","]
  },
  "parameterConstraints": [
    {"left": "min-insert", "operator": "<=", "right": "max-insert"}
  ]
}
```

Path restrictions apply to installation/tool paths, selected local inputs,
upstream products and the selected output directory. Invalid output paths are
rejected before creating a run. Spaces remain valid unless explicitly forbidden.
The restrictions describe limitations of an actual native executable—for example,
a filename-list argument that splits a path at commas. They do not escape or
rewrite paths. Filename checks use the path text, including Windows paths when
the checks themselves run on Linux.

Parameter comparisons accept `<=` between two distinct declared integer
parameters. **Workbench 0.5.4 or later** also accepts `!=` between two distinct
declared text parameters, for example:

```json
{"left": "tumor-sample", "operator": "!=", "right": "normal-sample"}
```

Text comparisons are exact and case-sensitive, matching SAM sample identifiers.
At most 16 comparisons are allowed. Defaults and user values undergo the same
checks before execution. A comparison is skipped if an optional parameter is
omitted; missing required parameters still fail validation. Earlier workbench
versions reject the new operator.

For decimal settings, **Workbench 0.5.4 or later** can constrain an ordinary
manifest text parameter without changing the argument text:

```json
"parameterRanges": [{"parameter": "contamination", "min": 0, "max": 1}]
```

The engine accepts decimal or scientific notation, rejects nonfinite values,
and compares the value to inclusive bounds using decimal arithmetic. The
original string is retained in arguments, presets and methods. Defaults and
saved settings obey the same checks. Values are limited to 128 characters and
four exponent digits. Metadata bounds must be finite JSON numbers within
`-1e100` to `1e100`; each declared text parameter can have at most one range.

For file inputs, the existing manifest `different-from=other-input-id` constraint
rejects two paths that identify the same physical file, including hard links.
The graph engine checks selected local files during validation and repeats the
check with resolved pipeline outputs before execution. The native runner also
enforces this constraint. Distinct filenames alone do not establish different
samples or donors.

## Alignment meaning

`sam` and `bam` are the alignment types accepted by the existing DNA workflows.
`sam-rna` and `bam-rna` use the same physical file formats but identify an RNA
alignment workflow. They do not connect implicitly to DNA variant-calling or
DNA preparation ports. HISAT2 RNA operations therefore include their own BAM
conversion, coordinate sorting and indexing. File-signature normalization
preserves the RNA type.

Alignment state may record `sort` and `pairing` (`single` or `paired`). Declare
only transformations actually performed: alignment alone does not establish
coordinate order, mate repair, duplicate marking or indexing. An output may use
`propagateStateFrom` to preserve known input state, with its explicit state
describing the changes it actually makes.

A BAM port can request a coordinate header and a single sample:

```json
{
  "id": "alignment",
  "type": "bam",
  "accepts": ["bam"],
  "manifestInputs": ["alignment"],
  "requiredState": {"sort": "coordinate"},
  "validation": {"singleSample": true, "sampleParameter": "sample"}
}
```

`sampleParameter` must name a declared text parameter. The check requires
nonempty, distinct `@RG` IDs, an `SM` value on every read group, exactly one
distinct sample, and agreement with that parameter. This is a header check;
it does not establish that every alignment record carries an `RG` tag.

When the operation also consumes a `reference` port, the engine compares BAM
contig names and lengths with the selected FASTA, and compares sequence MD5
values when the header provides them. Headers without `M5` cannot prove base
sequence identity. A composed graph must connect a consistent reference source
through its alignment and calling branches.

## Target intervals

`bed` denotes genomic intervals. Optional port rules are:

```json
{
  "minColumns": 4,
  "referenceBounds": true,
  "nonOverlapping": true
}
```

Validation reads tab-separated BED with zero-based, half-open coordinates. It
requires nonnegative integer starts and strictly greater ends. With four or more
required columns, the fourth column must contain a region name. Reference-bound
checks require matching contig names and ends within the selected FASTA. Blank
lines and `#`, `track ` and `browser ` headers are accepted.

Overlap rejection is optional. When requested, duplicate or overlapping targets
fail; adjacent intervals remain valid. A pack should request this only when
overlaps could cause repeated calls without an explicit deduplication step.
The validator supports at most 1,000,000 target intervals.

## Variant resource headers

**Workbench 0.5.4 or later** supports required INFO declarations on `vcf` and
`vcf-pass` ports. For a population allele-frequency resource, use:

```json
{
  "validation": {
    "requiredInfoFields": [{"id": "AF", "number": "A", "type": "Float"}]
  }
}
```

The validator reads the plain or gzip/BGZF header and requires the selected INFO
field to declare exactly that VCF Number and Type. It accepts reordered metadata
attributes and quoted descriptions, rejects duplicate INFO declarations, and
limits a header to 8 MiB with a maximum line length of 1 MiB. At most 16 distinct
fields may be required. Binary BCF inputs cannot use this rule.

This establishes a header contract only. It does not validate every record's AF
value, confirm the reference build, or establish population suitability. Pack
help and methods must explain those remaining requirements; a generic called
VCF is not automatically an appropriate population resource.

## Installation-check truth

`[asset:workbench-checks]` is another SHA-pinned JSON asset. Its fixtures must be
declared pack assets. Each check invokes the normal frozen graph engine using
the installed native backend. Check specifications contain assertions, never
commands or expressions. The existing `text`, `fasta` and `fastq` assertions
remain supported.

SAM assertions can verify actual mapping truth:

```json
{
  "output": "aligned-sam", "kind": "sam", "records": 2,
  "mapped": 2, "paired": 2, "properPairs": 2, "spliced": 1,
  "references": {"chr1": 1000}, "samples": ["validation"],
  "allReadGroups": true,
  "alignments": [
    {"name": "junction", "reference": "chr1", "position": 101,
     "cigar": "30M100N30M", "flag": 99,
     "tags": {"RG": "validation", "XS": "+"}}
  ]
}
```

Flag counts count SAM **records**, not read pairs. `spliced` counts records with
an `N` CIGAR operation. Optional `secondary` and `supplementary` counts inspect
their corresponding flags. Expected reference dictionaries and sample lists are
exact. Alignment predicates match distinct records and may select a subset of
record fields and optional tags. SAM positions are one-based.

VCF assertions support both genotyped and site-only calls:

```json
{
  "output": "variants", "kind": "vcf", "records": 1, "samples": [],
  "variants": [
    {"chrom": "chr1", "pos": 200, "ref": "A", "alt": "G",
     "filter": "PASS", "info": {"DP": "60", "AF": "0.200000"}}
  ],
  "absentVariants": [{"chrom": "chr1", "pos": 201, "alt": "T"}]
}
```

`samples: []` asserts a site-only VCF. For sample columns, use their exact names
and optionally assert `genotypes: {"validation": "0/1"}` within a variant
predicate. INFO values compare as strings; flag INFO fields compare with `true`.
VCF positions are one-based. Predicates match distinct rows; record counts also
detect extra calls. Plain and gzip/BGZF text are supported with a 4 MiB bound on
both the stored and decompressed fixture output.

Installation checks establish fixture behavior and integrity. A Linux reference
adapter must report its substituted binary hashes and cannot claim that Windows
execution occurred. New packs must include meaningful native fixture checks so
the same assertions can be exercised through **Check installation** on Windows.

## Explicit reusable minimap2 indexes (application 0.13.0)

A new pack version may declare `referenceIndex` on an index builder or
`requiresReferenceIndex` on its consumer. These schema fields require a
distribution `minAppVersion` of at least `0.13.0`; older application parsers
reject the extension. Existing published pack manifests must not be changed.
The first supported format is `minimap2-sr-v1` and semantic type
`minimap2-sr-index`, not the generic `index` type.

Builder metadata:

```json
"referenceIndex": {
  "format": "minimap2-sr-v1", "tool": "minimap2",
  "referencePort": "reference", "outputPort": "index"
}
```

It requires exactly one ordinary `reference` file port and one nonempty
`minimap2-sr-index` file output; the named executable must actually occur in its
manifest steps. The complete reference, pack, command, executable, parameter
and output inventory participates in the cache identity. The command remains
in the manifest; metadata cannot add or rewrite a command. Selecting this
explicit operation requests verified local reuse, which must be explained in
its description and methods.

Consumer metadata:

```json
"requiresReferenceIndex": {
  "format": "minimap2-sr-v1", "tool": "minimap2", "port": "index"
}
```

The index port must be one required file. It accepts only the matching builder's
graph output, with identical indexing/mapping executable ID, version and SHA-256.
Raw external `.mmi` files have no proven preset/tool identity and are rejected.
This initial contract does not add general directory outputs or imply support
for STAR/BWA/other index formats. See
[the implementation and provenance guide](../knowledge/reference-indexes.md).
