# SnpEff and SnpSift pack 1.0.0

Optional Native Workbench 0.6.0 pack `snpeff`, using the **unmodified official
SnpEff/SnpSift 5.4c scientific classes** and a private Temurin 21.0.9+10 Windows x64 JRE.
No system Java, Python, Docker, WSL, browser or administrator installation is
required. Only selected local files are used during analysis. Database downloads,
usage telemetry and update checks are disabled with upstream `-noLog` and
`-noDownload`; these are not a network security sandbox.

## Operations

- **Build local annotation database:** matching DNA FASTA, GFF3/GTF2.2 and CDS
  FASTA, explicit assembly ID/annotation release, and genetic code produce a
  reusable database ZIP. CDS identifiers must correspond to transcripts.
  Upstream CDS checking has zero tolerated mismatches; a separate protein
  comparison is disabled. Checking supplied CDS does not prove annotation
  completeness. Choose the default genetic code and explicitly name any
  vertebrate mitochondrial contigs to override it; no code is guessed from names.
- **Annotate variant consequences:** ordinary small-variant VCF plus a checked
  database ZIP produce VCF ANN consequences. The resource inventory is checked,
  every input REF allele must match its reference, and existing ANN is rejected.
  All transcripts are considered; upstream/downstream distance and splice-site
  width are exposed. HGVS follows upstream defaults; LOF/NMD tags and HTML
  statistics are disabled. Loci, alleles, samples, filters and genotypes remain;
  upstream may reformat numeric QUAL. Consequences are not clinical verdicts.
- **Annotate from local VCF:** select INFO IDs to transfer with `DB_` prefixes.
  Both inputs must have normalized biallelic records, matching assembly and
  contig naming. Matching uses chromosome, position, REF and ALT. Original IDs
  and genotypes are retained. Conflicting reference headers and existing target
  INFO headers are rejected. The assembly is explicitly user-declared; absent
  headers cannot prove identity. There is no liftover or external reference
  validation here. Staged database indexing does not change the selected file.
- **Select consequence impact:** SnpSift keeps whole records if **any** ANN entry
  has one selected exact impact. Multiallelic records retain all their alleles
  and genotypes, including nonmatching impacts; existing FILTER stays unchanged.
  Header-only results are valid. No arbitrary filter code or shell is exposed.

Inputs are plain/gzip VCF; BCF, gVCF, symbolic/breakend alleles are not supported.
Reference FASTA is uncompressed with regular line wrapping. Contig names are
case-sensitive. ASCII paths, including spaces, are supported; semicolons are
rejected because they delimit the Windows Java classpath. The heap selector
caps the child Java heap, not total RAM. Allow another 512 MiB adapter heap plus
JVM overhead, and disk for private input/reference/database staging. Human-scale
performance has not been established by the synthetic checks.

## Separate database resources

A tool pack ZIP installs executable software. A **database resource ZIP** is a
normal selected file containing `database.json`, `reference.fa` and named
`data/<assembly>/*.bin` files. Metadata records exact SnpEff format version,
assembly, annotation release, default/per-contig genetic codes, origin and complete file sizes and
SHA-256 checksums. It is graph type `file` because released Workbench has no
special database type. The adapter rejects other files, missing inventory,
unlisted/duplicate/unsafe ZIP names, bad checksums and oversized resources
(maximum 20,000 files, 32 GiB/member and 64 GiB expanded). Hashes identify bytes;
they do not authenticate the biological source or make imported data trusted.

Build one from matching local reference/annotation/CDS files in the GUI, then
save/reuse its ZIP independently of this tool pack. Reference providers can
also convert an explicitly downloaded official database with the included
publisher helper; this command performs **no download**:

```sh
python3 tools/snpeff/prepare_database_resource.py \
  --upstream downloaded-snpeff-database.zip --sha256 EXPECTED_SHA256 \
  --reference matching-reference.fa --config snpEff.config \
  --assembly EXACT_UPSTREAM_DATABASE_ID \
  --release ANNOTATION_RELEASE --source-url https://OFFICIAL_SOURCE \
  --output versioned-database-resource.zip
```

The provider must verify the exact assembly/annotation identity and test
representative variants before publishing the resource. Existing official SnpEff
archives with `data/<ID>` or `snpEff/data/<ID>` layouts are accepted. Only binary
predictor/sequence members are transferred; arbitrary upstream configuration is
not executed. The pinned official 5.4c configuration is required: only its
selected assembly default/per-contig codon mappings are transferred, so normal
human nuclear and mitochondrial codes are preserved. Config identity and mappings
are retained in resource provenance. No preselected human database is bundled. The tiny synthetic
resource is an installation fixture, not a reference for biological analyses.

## Reproduce and validate

```sh
python3 scripts/fetch_snpeff_build_inputs.py --cache build/snpeff-inputs
python3 scripts/prepare_snpeff_pack.py --cache build/snpeff-inputs \
  --destination packs/snpeff-1.0.0
python3 tests/test_snpeff_pack.py --pack packs/snpeff-1.0.0 \
  --java build/snpeff-inputs/jdk/jdk-21.0.9+10/bin/java \
  --report build/snpeff-linux-validation.json
```

On Windows omit `--java` to use the pack-private runtime. Native Windows evidence
must come from execution of the exact published archive through the released
application, separately from Linux tests. Four manifest checks exercise all
operations with independent codon truth: GCT→GTT Ala→Val (missense), GCT→GCC
Ala→Ala (synonymous), and CAA→TAA Gln→stop. Regression tests also cover wrong
allele joins, reference mismatch, corrupt resources, empty outcomes and
multiallelic record selection, and explicit standard/mitochondrial genetic-code
behavior without inherited per-contig assembly settings. These are software checks, not clinical or
whole-genome validation.

The adapter passes the private database directory as the relative path `data`,
with the child working directory and generated configuration in the same private
run folder. This avoids upstream SnpEff treating a Windows drive-prefixed data
path as relative and prepending it a second time. Scientific classes are unchanged.

## Sources and licensing

`licenses/` contains the adapter/build source, immutable input URL/hash pins,
SnpEff source commit `0201ed20051d43628e51dcf48e774adac5b5e025` (v5.4c), SnpSift
source commit `a9122d0283cad1475ec475b1623f87bbd8fbfec5` (v5.4b), dependency sources
and notices, OpenJDK corresponding sources and runtime notices. The latter
SnpSift commit is the latest upstream commit before the official 5.4c core build;
its displayed version comes from its bundled SnpEff dependency. The JAR containers omit only unused legacy Sun Binary Code-licensed
`javax/vecmath/*` entries used by structural/PDB operations, which this pack does
not expose. Every retained class/resource byte is verified identical to the pinned
official distribution. Per-JAR JSON records original/packaged hashes and every
omitted path/hash; the build recipe reconstructs this change. Scientific classes
are not recompiled or modified.
This source correspondence does not claim bit-for-bit reproduction of upstream's
compiler environment. The source project's stale Maven LGPL declaration is
retained; the distribution and current source LICENSE state MIT. Dependencies
retain their own terms. OpenJDK includes GPLv2/ClassPath Exception code and
separately licensed third-party components. Never omit the notices/sources when
redistributing this prepared pack.
