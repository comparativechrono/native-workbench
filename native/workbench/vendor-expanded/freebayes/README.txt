FreeBayes 1.3.10 for Native Workbench

This is the real upstream FreeBayes caller, built from the official pinned source
release, with bundled SeqLib, fastahack, smithwaterman, minimal vcflib and ttmath.
Tabix++ 1.1.2, SIMDe 0.8.2, pinned IntervalTree and HTSlib 1.24 are included in
the build. The portable x86-64 APE includes its C/C++ runtime. The Linux binary
is a reference build linked to the host's shared runtime libraries.

Example command (stdout is a VCF):
  freebayes --fasta-reference reference.fa --ploidy 2 \
    --min-mapping-quality 20 --min-base-quality 20 --strict-vcf input.bam

Use indexed coordinate-sorted BAM with read groups/sample identifiers and an
indexed reference. Run in the job's private output directory. A downstream
bcftools norm step gives consistent minimal representations for indels.
The selected ploidy applies to this invocation; it must match the experiment.

Rebuild from the project root after preparing the pinned HTSlib static builds:
  python3 tools/build_freebayes.py --target all --jobs 2
Optional --cosmocc-root and --htslib-build-root point to other build locations.
Every source archive is hash-checked. The required dependencies' archives are
in archives/. HTSlib and Cosmopolitan provenance are referenced in provenance.json.
The build follows upstream's bundled source lists directly, avoiding unused
system-library detection. Compiler argument vectors are retained in build logs.

Compatibility changes are limited to public 64-bit file offsets, a diagnostic
backtrace guard, and the missing C99 llrintl runtime function. The latter is the
unchanged x86-64 source from musl 1.2.5, checked against its pinned source archive.
It retains long-double precision and the active x87 rounding mode. Its 84-case
test matches glibc values and FE_INVALID/FE_INEXACT flags in all rounding modes.
No FreeBayes variant-calling algorithm has been replaced or modified.

Validation:
  python3 vendor-expanded/freebayes/validate.py --output NEW_EMPTY_DIRECTORY
The independent tiny truth fixture passes all four known alleles/genotypes.
Native and portable diploid, haploid and gVCF outputs have identical scientific
headers and every VCF record column (after normalization for variant-only VCF).
The haploid mode comparison uses the same diploid fixture and is a portability
comparison, not a separate haploid truth experiment. Validation reports include
commands, binary/input hashes and original stderr. Existing inputs stay intact.

All execution in this build environment was on Linux x86-64. The APE is built
for Windows compatibility; its Windows execution still needs local validation.
No performance claim is made. The recorded comparisons do not establish general
scientific or clinical accuracy outside the tested fixtures and parameters.

Use one caller process with no HTSlib worker pool. A known Cosmopolitan 3.3.10
recursive-mutex/condition-variable incompatibility prevents claiming HTSlib
thread-pool support. Parallel shell wrappers are not supplied. Network/cloud
inputs, dynamic plugins, bzip2/lzma and libdeflate are disabled in this HTSlib;
ordinary local BAM and gzip/BGZF support is retained.

The licenses/ directory contains flat filenames for short Windows import paths,
full dependency licenses, original source-header notices, C++ runtime licenses,
and the portable executable's embedded runtime notices. Its inventory records
each origin and hash. See provenance.json for exact source and binary hashes.
