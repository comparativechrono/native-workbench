# BEDTools genomic intervals

Pack **bedtools 1.0.0** targets Native Workbench **0.6.0** or newer. It packages
upstream BEDTools **2.31.1**, identified as `2.31.1-workbench1`, compiled as a
native Windows x86-64 executable. No WSL, Docker, shell, system Python or analysis
network connection is required.

## Operations and scientific meaning

| Operation | Result |
| --- | --- |
| Overlapping intervals | Each complete A interval once when at least one B interval overlaps it; `intersect -u` |
| Same-strand overlapping intervals | The same selection, requiring explicit matching BED6 `+` or `-` strands |
| Intervals without an overlap | Complete A intervals with no B overlap; `intersect -v` |
| Subtract intervals | Remaining pieces of A after removing bases overlapped by B; A metadata retained |
| Interval coverage | A columns, overlapping B-feature count, covered bases, A length, covered fraction |
| Sort intervals | Lexical contig-name and numerical start ordering |
| Merge intervals | Sort, then merge overlaps and book-ended intervals; optional maximum positive gap; BED3 output |
| Extract interval sequences | Genomic DNA FASTA for each interval, ignoring strand |
| Extract sequences by strand | BED6 sequence extraction, reverse-complementing minus-strand intervals |

BED coordinates are **zero-based, half-open**. `[0,4)` covers bases 1–4.
Intervals ending at the start of another interval do not intersect; they do
merge with the default merge distance of zero. Merge ignores strand and discards
names/scores/strands. Increasing its distance joins intervening gaps deliberately.
Coverage is per A interval and uses the union of B-covered bases for the fraction;
overlapping B records contribute separately to feature count. It is not normalized
RNA expression, sequencing-depth coverage, or a statistical enrichment test.

Use the same genome assembly and contig naming in A, B and the reference.
Interval overlap alone cannot establish assembly compatibility. No chromosome
renaming or coordinate conversion is inferred. BED12 block/exon semantics, BAM,
GFF/GTF and VCF inputs are intentionally outside this pack's exposed interface.

## Input, output and resource limits

- Plain tab-separated **BED3 through BED6**, with a consistent column count per
  file, positive-length intervals and valid fields. BED6 strand is `+`, `-`, or
  `.`; stranded operations require explicit `+` or `-` on every record.
  Score is `0`–`1000` or `.`. Header/comment lines accepted by the upstream parser
  do not represent intervals.
- Workbench 0.6.0's core BED validator currently limits each input to **1,000,000
  intervals** and rejects empty BED inputs. A valid no-hit operation still
  succeeds with an empty result and an interval count of zero; that empty result
  cannot feed a downstream tool requiring intervals in this app version.
- Input paths must be ASCII; spaces are supported. Short practical paths are
  recommended; these tools do not promise arbitrary Windows long-path support.
- Sequence extraction needs matching, uncompressed genomic nucleotide FASTA.
  The original input is read-only. A private reference copy and `.fai` index are
  created in the run directory. Allow disk space for this copy. The bundled
  upstream faidx interface limits individual reference contigs to 2,147,483,647
  bases, checked before indexing. Extraction returns full interval spans, not
  BED12 blocks. Headers identify coordinates; repeated identical intervals can
  therefore generate duplicate FASTA identifiers.
- The interval operations retain upstream 64-bit coordinate handling, including
  checks with coordinates beyond 2^31. They use a single worker. Sorting and
  overlap operations load data into RAM; no memory limit or external-memory sort
  is implied. Very large jobs may need a larger computer or an established HPC
  workflow.
- Upstream has additional subcommands, but only the declared operations above
  are supported. Developer regression-shell commands, CRAM, remote inputs and
  optional bzip2/lzma codecs are outside this pack.

## Reproducibility, source and licensing

Methods previews, tool/pack versions, exact argument arrays, input hashes and
run provenance are provided by Workbench. The methods paragraph is a draft to
adapt to the study; it is not evidence of completion when a run fails.

The pack includes SHA-pinned complete BEDTools and zlib source archives, the
exact compatibility patch, build/packaging recipes, helper source, compiler
notices and build provenance in `licenses/`. BEDTools' top-level release licence
is MIT; the original archive preserves embedded third-party and historical
file-level notices. HTSlib, zlib, LLVM and MinGW notices are retained.

The narrow port changes address native binary I/O, missing direct includes,
MinGW formatting/mkdir compatibility, 64-bit integer declarations and existing
undefined behaviour (uninitialized flags and mismatched array deletion). The
upstream overlap, merge, coverage and sequence algorithms are unchanged. A
small Workbench helper validates this pack's BED/reference contract and counts
output records; it does not implement interval arithmetic.

Scientific checks cover exact overlaps, same strand, no hits, subtraction,
coverage fractions, adjacency and gap merging, 64-bit coordinates, forward and
reverse-complement extraction. Linux comparison against an unmodified pinned
upstream build is distinct from native Windows execution. See the accompanying
release validation record for the exact archive, platform and checks actually
run. These synthetic examples do not establish clinical validation or performance
on arbitrary datasets.

Build from a checkout (replace toolchain path for your environment):

```sh
python3 scripts/build_bedtools_native.py --fetch --cache ../popular-build/bedtools --toolchain /path/to/llvm-mingw
python3 scripts/build_bedtools_native.py --linux --cache ../popular-build/bedtools
python3 scripts/build_bedtools_native.py --linux --upstream --cache ../popular-build/bedtools
python3 scripts/prepare_bedtools_pack.py --cache ../popular-build/bedtools --toolchain /path/to/llvm-mingw
python3 -m unittest discover -s tests -p test_bedtools_pack.py -v
python3 scripts/package_split.py pack --pack-root packs/bedtools-1.0.0 --output /path/to/native-workbench-pack-bedtools-1.0.0.zip
```

Citation: Quinlan AR, Hall IM. BEDTools: a flexible suite of utilities for
comparing genomic features. *Bioinformatics* (2010), 26:841–842.
<https://doi.org/10.1093/bioinformatics/btq033>.
Upstream: <https://github.com/arq5x/bedtools2/releases/tag/v2.31.1>.
