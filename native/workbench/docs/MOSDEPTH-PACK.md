# mosdepth coverage pack 1.0.0

This optional pack adds **mosdepth 0.3.14** to Native Workbench 0.6.0 without
Docker, WSL, a browser, administrator rights or a system runtime. The two
operations work independently or in a pipeline: `coverage` for all BAM reference
bases, and `targets` for an explicit BED3/BED4 interval list. Outputs include
mean depth, selected depth-threshold breadth, original mosdepth reports,
BGZF-compressed per-base/target intervals, CSI indexes and input-validation JSON.
Everything is local; no references or user data are downloaded or uploaded.

## Scientific contract

Use binary coordinate-sorted BAM (DNA or RNA), with `SO:coordinate` and matching
actual record order. The guard validates the private staged BAM's dictionary,
records, CIGAR bounds, BGZF EOF and ordering, then creates a private CSI index.
It never changes the original BAM/index. BED coordinates are zero-based,
end-exclusive, sorted in BAM dictionary order, nonoverlapping and within the
BAM's contig bounds. BED4 names are retained. Empty or out-of-bounds intervals,
unknown contigs and overlapping target intervals are rejected. Valid selected
regions with zero coverage are retained. BAM-header contigs define the reference;
**assembly identity is not verified against FASTA**. All BAM samples/read groups
are aggregated. RNA coverage is genomic coverage, not expression quantification.

Accurate upstream mode interprets CIGAR operations and counts overlapping bases
of proper paired alignments once. Deletions and splice gaps do not count; insert
sequence does not add reference depth. No fast/fragment mode is exposed.
Mapping quality defaults to 0; reads below the selected threshold are excluded.
MAPQ 255 remains eligible. **No base-quality filter exists in mosdepth: Q0 bases
still count.** There is no fragment-length or read-group filter in this pack.
The upstream default exclusion mask 1796 removes unmapped, secondary, QC-failed
and duplicate reads but retains supplementary alignments. Mask 3844 additionally
excludes supplementary reads. Mask 772 retains duplicate-marked reads. Those
choices, threads and three strictly increasing breadth thresholds are recorded.
Default thresholds are 1, 10 and 20; breadth counts bases at or above the threshold.

### Denominators and the primary summary

Upstream mosdepth 0.3.14 omits chromosomes without any alignment records from
its summary/distribution denominators, although its per-base BED correctly
includes those chromosomes at zero depth. Both the official Linux binary and
this source build exhibit this behavior. **Raw observed-contig reports are
retained unchanged and explicitly labelled.**

The primary `coverage.full-summary.tsv` is a separate Workbench aggregation of
upstream per-base coverage intervals. It checks that the intervals partition the
complete BAM reference dictionary in order, with no missing/overlapping bases.
For interval length L and upstream depth D, depth sum contributes L×D; breadth
at threshold T contributes L if D≥T. Mean is depth sum divided by full length;
breadth fraction is qualifying bases divided by full length. Intersections with
each nonoverlapping target provide the same quantities for its full length.
Thus empty contigs and uncovered target bases remain in the denominator. This
streaming aggregation does not reinterpret reads or implement a new coverage
algorithm. Raw and derived reports can legitimately have different totals.

## Resource and portability bounds

Windows x86-64, ASCII local paths (spaces supported); SAM/CRAM and remote paths
are rejected. No D4 support. Mosdepth uses roughly four bytes times the longest
contig length for its main array (about 1 GB for a 250 Mb contig), plus runtime
and BAM buffers. Threads affect decompression, not a total RAM cap. The pack
creates a full-size private BAM copy and CSI index, and always retains per-base
BGZF output to support complete-reference aggregation. Plan disk space for the
input copy and potentially large coverage output; the small synthetic tests are
not a whole-human-genome performance claim. BAM contig length is limited to
2,147,483,646 by the upstream representation used here.

## Reproducible build and source

`python scripts/fetch_mosdepth_build_inputs.py` downloads pinned public inputs
only during development. SHA-256 mismatches fail. The recipes pin mosdepth
0.3.14, HTSlib 1.23.1/its bundled HTScodecs, hts-nim commit
50b64d8843f20326d113c1ef1f29dc773f32915b, docopt 0.7.1, nim-regex 0.26.3,
unicodedb 0.13.2, zlib 1.3.2, PCRE2 10.46, LLVM/MinGW 20260922 and the Nim
2.2 branch compiler at 94f8857d5955d2a1fa0b36f81762fa173844f104 (2.2.13).
The official mosdepth 0.3.14 Linux binary is independently hash-pinned for comparison.

```sh
python scripts/fetch_mosdepth_build_inputs.py
python tools/mosdepth/build.py --output build/mosdepth-windows
python tools/mosdepth/build.py --linux --output build/mosdepth-linux
python scripts/prepare_mosdepth_pack.py --build build/mosdepth-windows --destination packs/mosdepth-1.0.0
python tests/test_mosdepth_pack.py --pack packs/mosdepth-1.0.0 --linux-build build/mosdepth-linux --upstream build/mosdepth-inputs/upstream-mosdepth --report build/mosdepth-science.json
python scripts/package_split.py pack --pack-root packs/mosdepth-1.0.0 --output build/native-workbench-pack-mosdepth-1.0.0.zip
python scripts/validate_pack_release.py build/native-workbench-pack-mosdepth-1.0.0.zip
```

Use new build/output directories. Nim uses `--mm:refc` as upstream requires.
No coverage algorithm is modified. A three-line mosdepth boundary patch fixes report precision to two decimal places, ignores the host REF_PATH (only explicit local BAM is exposed), and labels the runtime 0.3.14-workbench1. This prevents inherited environment variables from silently changing selected behavior. The patch and upstream source are retained. HTSlib and hts-nim source are unchanged. HTSlib's
MinGW build uses PCRE2's POSIX header as `regex.h` and statically linked PCRE2
because the toolchain has no POSIX regex library; exposed coverage operations do
not use HTSlib filter expressions. Network plugins/curl/cloud support and unused
CRAM optional bzip2/lzma codecs are disabled. The HTSlib DLL is private to `bin`;
other imports are Windows/UCRT system libraries. Compiler/runtime licenses,
exact source archives, commands and hashes are retained under `licenses`.
SAMtools 1.24 is a hash-pinned unchanged helper recovered from the released
0.6.0 starter; its inherited notices are retained in a shallow ZIP. It performs
a real quickcheck step and supports the released app's own BAM preflight.

## Validation and evidence boundaries

Synthetic fixtures independently cover proper-mate overlap, gaps/deletions,
spliced reads, low MAPQ, low base quality, secondary/QC-failed/duplicate and
supplementary flags, empty regions/contigs, empty BAM, sortedness/contig/bounds
rejections and threshold denominators. Regression tests compare every raw
scientific output to the pinned unmodified official Linux binary where available,
and compare the derived summary to explicit interval truth. Installation checks
exercise both workflows with two decompression threads and multiple filters.

For native Windows, run the source regression script with `--pack` set to the
freshly installed pack and `--report` to an evidence path. It uses installed PE
executables directly; no compiler, system runtime or upstream Linux binary is
needed. The separate release gate imports the exact ZIP through the released
native bridge and verifies duplicate-version rejection. Linux results, PE import
inspection, native Windows execution, GUI acceptance and clinical validation are
distinct evidence. Build provenance alone does not claim Windows execution.
