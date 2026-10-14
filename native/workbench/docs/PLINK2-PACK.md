# PLINK2 genotype summaries pack

Pack **plink2 1.0.0** supplies PLINK **2.0.0-a.7.12** as a local native Windows
x86-64 build from unchanged upstream source. It is an unpublished review candidate.
One operation, `summarize-vcf`, reports ALT allele frequencies, genotype hardcall
counts, per-sample missingness and per-variant missingness. The bundled tools run
locally without analysis-time downloads, WSL, Docker or a system interpreter.

## Input and interpretation

Select a reviewed, uncompressed VCF 4.2 or 4.3 containing human autosomes **1–22**,
biallelic SNPs with distinct uppercase A/C/G/T REF and ALT, and a **GT-only** FORMAT.
The supported calls are diploid `0/0`, `0/1`, `1/0`, `1/1`, or `./.`; phased equivalents
are accepted, but these measurements do not use phase. Haploid/polyploid calls,
half-missing calls, multiallelic variants, indels, sex/mitochondrial chromosomes and
additional FORMAT fields such as DS, GP, GL, PL, DP and GQ are rejected. Export a
reviewed GT-only input explicitly rather than silently discarding those fields.

Bounds are 2–1000 samples, 1–100000 variants, at most 10000000 genotypes and 64 MiB.
IDs must be unique and nonmissing, with 1–128 ASCII letters, digits, underscore,
dot or hyphen; the single identifier `.` and sample ID `0` are unsupported. Sample
IDs are preserved with explicit `--const-fid 0`, including underscores and leading
zeros. Installation, input and output paths must be ASCII; spaces are supported.
These bounds are not predictions of runtime or total memory use.

Every supplied sample and variant is included, **regardless of FILTER**. There is
no quality, missingness, MAF or HWE filtering and no automatic QC acceptance label.
ALT frequency is ALT allele observations divided by called allele observations;
it can exceed 0.5 and is not necessarily minor allele frequency. Missingness uses
all retained variants or samples in its denominator. An all-missing variant has
undefined allele frequency (`nan` or an upstream missing marker), not frequency zero. Monomorphic records remain.
`--nonfounders` makes inclusion of all supplied samples explicit; this VCF-only
operation imports no pedigrees or phenotypes. Selection of samples, relationships,
variants and any LD treatment remains a scientific decision.

The pack requests one PLINK compute thread and `--memory 640 require`, a 640 MiB
main workspace allocation. PLINK and the adapter also allocate memory outside
that workspace; it is **not a whole-process cap**. The adapter checks input and
output counts, preserves the input file, stages work privately and publishes the
four scientific tables only after PLINK succeeds and validation completes.

## Results and guidance

- `plink.afreq`: per-variant ALT frequencies and observed allele counts.
- `plink.gcount`: homozygous REF, heterozygous, homozygous ALT and missing counts.
- `plink.smiss` / `plink.vmiss`: sample/variant missing counts and fractions.
- `summary.json`: recorded totals and missing fraction, without QC thresholds.
- `settings.json`: exact bounded options and subprocess arguments.
- `plink.log` / `adapter.log`: upstream and execution diagnostics.

Workbench Results exposes these files and recorded tool versions/provenance;
this pack does not add native JSON summary tiles. Missing executable: reinstall
the exact pack. A rejected input: follow the named VCF contract error and review
any conversion before retrying. Upstream execution failure: inspect both logs,
check the writable fresh output folder and available memory. Output files from a
failed operation must not be treated as completed results.

PCA, ancestry inference, associations, phenotypes, PGEN reuse and filtering are
not included in this initial pack. PCA requires separate scientific contracts,
LD/relatedness/variant-selection decisions and a reviewed linear algebra runtime.
No clinical or biological acceptance conclusion is established by fixture checks.

## Build and source correspondence

Official source tag `v2.0.0-a.7.12`, commit
`5c1f185d4144e62fa23087d68760162f712cd2a8`:
`https://codeload.github.com/chrchang/plink-ng/tar.gz/5c1f185d4144e62fa23087d68760162f712cd2a8`.
Source archive SHA-256:
`bcfa30a7cfca2e117bacb94c94a2248ab190396ff8d2711f600ef42ebf5f9198`.
Zlib 1.3.2 SHA-256:
`bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16`.

`build_plink2_native.py` compiles the pinned upstream Makefile CLI source list with
baseline x86-64 options and `NOLAPACK`, statically linking pinned zlib and the
upstream bundled libdeflate/zstd sources. No upstream source is patched. A forced
standard `math.h` include supplies a missing declaration on that build route.
The banner appends `NL` to denote no LAPACK. The build records compiler identity,
commands, executable hashes and PE imports; compilation alone does not establish
Windows execution. Original complete source archives, recipes, adapter and notices
are retained under `licenses/` and in the matching source/evidence companion.

```sh
python scripts/build_plink2_native.py --fetch --linux
python tests/test_plink2_pack.py --build build/plink2-linux --report build/plink2-source-tests.json
python scripts/build_plink2_native.py --fetch --toolchain /path/to/llvm-mingw
python scripts/prepare_plink2_pack.py --destination build/plink2-pack
python scripts/package_split.py pack --pack-root build/plink2-pack --output build/native-workbench-pack-plink2-1.0.0.zip
python scripts/validate_pack_release.py build/native-workbench-pack-plink2-1.0.0.zip
```

The four-sample/six-variant synthetic fixture assigns genotypes before invoking
PLINK: 24 total genotypes, 17 called, seven missing, 34 called allele observations
and 18 ALT observations. Independent integer arithmetic checks each variant and
sample, including fixed REF/ALT, all-missing and ALT frequency above 0.5. Source,
native Windows and desktop checks are separate evidence; see the maintained
handover for actual candidate outcomes.

Scientific reference: Chang CC et al. (2015), *Second-generation PLINK: rising to
the challenge of larger and richer datasets*, GigaScience 4:7,
https://doi.org/10.1186/s13742-015-0047-8. Operational documentation:
https://www.cog-genomics.org/plink/2.0/basic_stats and
https://www.cog-genomics.org/plink/2.0/dev.
