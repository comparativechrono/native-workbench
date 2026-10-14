# featureCounts gene-counting pack 1.0.0

For Native Workbench 0.6.0 or later on Windows x86-64. Uses the unmodified
official Subread **featureCounts 2.1.1** executable. No Docker, WSL, shell,
system Python/Java, browser or analysis-time download is required.

The two operations count single-end reads or paired-end fragments from one RNA
BAM against matching uncompressed GTF exon features grouped by `gene_id`.
STAR and HISAT2 RNA BAM outputs connect directly using `bam-rna` ports.
Strandedness is required: 0 unstranded; 1 read/read 1 follows the transcript;
2 read/read 1 opposes the transcript. Consult the library preparation; it is
not inferred. Do not count transcriptome-aligned BAM against genomic GTF.

Paired mode explicitly uses `-p --countReadPairs -B -C`: a fragment is counted
once, both ends must be aligned, and upstream's chimera filter excludes mates
on different chromosomes or the same strand. No fragment-length filter is
applied. Single mode counts reads individually. Both use exon overlap and
exclude secondary alignments (`--primary`), NH-tagged multimappers and reads
ambiguous between genes. Duplicate-marked reads are retained. The mapping
quality threshold defaults to zero; in paired mode at least one mate must pass.
The two-thread default is exercised by the bundled scientific checks.

A separate native guard reads the BAM before counting and checks pairing flags,
record sizes, decompression and the reference dictionary. It rejects
supplementary alignments (flag 0x800), mixed single/paired data and malformed
pair flags. This avoids silently assigning supplementary records as additional
reads; filter them deliberately before using this pack. It also checks every
GTF exon has a quoted nonempty `gene_id`, a + or - strand, valid bounds and an
exact contig name present in the BAM dictionary. Unlike upstream's optional
chromosome-name inference, `chr1` and `1` must match exactly. The guard does not
prove genome sequence identity, sample identity or biological suitability and
adds an extra sequential BAM read. It imposes bounds of 199 bytes per contig
name, 64 MiB header, 16 MiB record and 1 MiB GTF line. Long-read counting is
outside the supported interface. Coordinate- and name-sorted BAM are accepted;
featureCounts performs its own pairing when needed. No BAM index is required.

Results are raw integer `gene-counts.tsv`, the upstream assignment-reason
summary and `input-validation.json`, plus Workbench methods and provenance.
Gene length is the union of annotated exons, not transcript length. Zero counts
are legitimate. No TPM, normalization, replicate modeling or differential
expression is performed. One BAM is one sample per run; outputs can subsequently
be joined by gene ID in an appropriate analysis. Multiple BAMs, GFF3/SAF,
gzip-compressed GTF, CRAM, fractional multimapping, junction counting and
single-cell processing are not exposed by this initial pack. ASCII paths are
required; spaces are supported. Use short paths where upstream Windows limits
apply. The pack contains GPL source, the separate MIT guard, zlib source,
notices and provenance under `licenses/`.

Build from the repository root (an existing compiler/toolchain is needed only
for pack development):

```sh
python3 scripts/build_featurecounts_native.py --fetch
python3 scripts/build_featurecounts_native.py --linux
python3 scripts/prepare_featurecounts_pack.py
python3 -m unittest discover -s tests -p test_featurecounts_pack.py -v
python3 scripts/package_split.py pack --pack-root packs/featurecounts-1.0.0 --output /path/to/native-workbench-pack-featurecounts-1.0.0.zip
python3 scripts/validate_pack_release.py /path/to/native-workbench-pack-featurecounts-1.0.0.zip
```

`--cache`, `--toolchain` and preparation `--destination` allow explicit paths.
Preparation requires an empty destination. Linux tests use the exact unmodified
Subread source and guard, and check independent synthetic overlap/strand/mate
truth and invalid-input rejection. They do not establish native Windows
execution. Bundled installation checks run six real counting cases across
single/paired and all three strand modes; the release must additionally pass
the native Windows import/execution gate at ordinary and spaced paths.

Upstream: [Subread 2.1.1 downloads](https://sourceforge.net/projects/subread/files/subread-2.1.1/).
Cite Liao, Smyth and Shi (2014), Bioinformatics 30:923–930,
[doi:10.1093/bioinformatics/btt656](https://doi.org/10.1093/bioinformatics/btt656).
