# GATK germline pack

This optional pack extends Native Workbench with GATK **4.7.0.0** germline
operations. It uses the unchanged upstream local JAR and the documented
`4.7.0.0-workbench1` local-path compatibility adaptation already distributed in
the Mutect2 pack. A complete private Temurin Java **17.0.20.1+1** runtime runs the
tools locally on Windows x86-64. No system Java, Python launcher, Docker, WSL,
browser or analysis-time download is required. The existing Mutect2 pack and its
saved pipelines retain their versions and contents.

Pack **1.0.0** is available from the
[GATK release](https://github.com/comparativechrono/workbench/releases/tag/pack-gatk-v1.0.0).
In Workbench **0.6.0 or later**, choose **Manage tools → Import pack ZIP** and
select `native-workbench-pack-gatk-1.0.0.zip`, then run **File → Check installation**.
The pack can be copied to an offline machine; the starter application is unchanged.
Its pack version is distinct from upstream GATK 4.7.0.0.

## Individual tools and pipelines

The pack exposes nine operations:

| Operation | Purpose |
| --- | --- |
| MarkDuplicates | Mark duplicate alignments and retain duplication metrics; reads are not removed |
| Base-quality recalibration | Run BaseRecalibrator and ApplyBQSR with explicitly selected local known-site resources |
| HaplotypeCaller: VCF | Call germline short variants for one prepared DNA sample |
| HaplotypeCaller: gVCF | Produce reference-confidence records for later genotyping |
| CombineGVCFs | Combine two to 32 explicitly selected, distinct-sample GATK gVCFs |
| GenotypeGVCFs | Genotype a single or combined GATK gVCF |
| SelectVariants | Select the requested variant class |
| VariantFiltration | Apply the selected hard-filter criterion, retaining filter-labelled records |
| ValidateVariants | Check the selected VCF against the matching reference |

Each operation has its own inputs, settings, outputs, methods and installation
checks. Users can run one tool, save its settings, or connect operations in the
pipeline editor. Shared references and BAMs can feed several branches. Compatible
sample gVCFs can merge before joint genotyping. Workbench retains the DAG,
methods, versions, parameters, input hashes and run logs alongside the results;
the pack also retains its actual GATK child-process arguments.

GVCFs are **not final variant callsets**. Released Workbench 0.6.0 has no dedicated
gVCF graph type, so this pack uses explicitly labelled generic file ports for
them. This prevents automatic connections to ordinary VCF ports. The pack's
adapter additionally validates gVCF content before calling GATK. A generic file
connection alone does not establish compatibility. GenotypeGVCFs produces the
ordinary VCF used by downstream variant selection/filtering.

The adapter checks reference-confidence records, NON_REF alleles and PL
likelihoods, and rejects repeated physical merge inputs or repeated sample
labels. A BQSR table or another generic file does not become a gVCF merely by
connecting it to that port. Empty ordinary VCFs remain valid results: headers
can retain NON_REF declarations after genotyping and selecting away every
variant, so that header alone cannot identify a file as a gVCF.

## Scientific choices and limits

Provide the exact uncompressed reference FASTA and prepared, coordinate-sorted
DNA BAMs. Calling and recalibration require the declared sample name to match
the BAM read-group sample. Each alignment record must carry an RG tag resolving
to a declared read group; a valid header alone is insufficient. This prevents
GATK's read filters silently discarding reads with missing group metadata.
Intervals are BED coordinates: zero-based starts and
end-exclusive ends. References, known sites and gVCFs must agree in assembly and
contig definitions. Inputs are staged privately before indexing; allow disk
space for copies and intermediate outputs. Original inputs are not modified.

BQSR requires suitable known-site resources for the organism and reference.
The pack does not download human resources, infer a suitable database, or apply
recalibration automatically to every experiment. Likewise, duplicate marking,
sample ploidy and filtering choices must fit the assay. Hard filtering is not
VQSR; a retained PASS record is not proof that the variant is biologically real.
Review generated methods before using them in a publication.

MarkDuplicates requires only a BAM. It marks coordinate-based duplicates and
retains reads; optical duplicate detection is explicitly disabled because
interpreting read-name geometry depends on the assay. It does not perform
UMI-aware deduplication. BQSR learns its model over the selected BED intervals
and applies it to the complete BAM, preserving sequence and alignment positions.
Calling ploidy applies to all selected intervals; use separate analyses where
contigs require different ploidies.

VariantFiltration offers QUAL, QD, FS, SOR, MQ, MQRankSum, ReadPosRankSum and DP,
a less-than/greater-than comparison, a decimal threshold and a FILTER label.
It retains every record and existing filters. Missing evaluated annotations
fail the selected criterion. Chain operations with distinct labels for several
criteria. The initial QUAL threshold is an editable example, not a complete
filtering recommendation. SelectVariants chooses ALL, SNP or INDEL records
without splitting mixed records. ValidateVariants excludes the dbSNP ID check
because no dbSNP resource is supplied, while retaining reference, allele and
chromosome-count checks.

HaplotypeCaller uses `LOGLESS_CACHING` PairHMM and `JAVA` Smith-Waterman. JDK
compression is explicit; native acceleration is not required. These choices
preserve upstream implementations but can be slower than accelerated Linux
GATK. The Java heap setting is not a limit on total process or machine RAM.
CombineGVCFs is the local alternative to GenomicsDB for this pack; small fixture
success does not establish large-cohort or human whole-genome performance.

GenomicsDBImport, Spark tools, Python-dependent CNV/neural-network workflows,
VQSR, R plots, cloud inputs and arbitrary GATK command entry are outside this
pack's initial scope. Broad does not officially support native Windows. The
Workbench compatibility claim is limited to the explicitly tested operations
and exact released bytes.

## Rebuilding and source recovery

The seed is the immutable published Mutect2 0.5.4 pack, verified by SHA-256 and
its complete archive inventory. Its GATK JAR, path adaptation, private Windows
JRE, third-party notices and corresponding source are retained. The new adapter
only validates/stages inputs, constructs argument arrays and records outputs;
it does not reimplement GATK scientific algorithms. Adapter source, compiler
identity and build provenance accompany the pack.

From a checkout, Python 3.12 or newer can recover the pinned build inputs into
a new directory:

```sh
python3 scripts/fetch_gatk_build_inputs.py --fetch --linux-reference --released-app --output build/gatk-recovered
python3 scripts/prepare_gatk_pack.py --seed-pack build/gatk-recovered/seed/pack --javac build/gatk-recovered/jdk/jdk-17.0.20.1+1/bin/javac --output packs/gatk-1.0.0
NW_GATK_JAVA_HOME="$PWD/build/gatk-recovered/linux-jre/jdk-17.0.20.1+1-jre" NW_GATK_LOADER="$PWD/build/gatk-recovered/linux-tools/ape-loader-linux" python3 tests/test_gatk_pack.py --report build/gatk-evidence/linux.json
python3 scripts/package_split.py pack --pack-root packs/gatk-1.0.0 --output dist/native-workbench-pack-gatk-1.0.0.zip
python3 scripts/validate_pack_release.py dist/native-workbench-pack-gatk-1.0.0.zip
NW_GATK_STARTER_ZIP="$PWD/build/gatk-downloads/starter.zip" NW_GATK_ARCHIVE="$PWD/dist/native-workbench-pack-gatk-1.0.0.zip" python3 tests/test_gatk_pipeline.py --report build/gatk-evidence/graph.json
```

This build-time download is explicit. `--fetch` can be omitted when the pinned
archives are already present in the cache. The seed archive is large because it
retains the complete private runtime and source/licence coverage. Keep matching
source/evidence companions and the pack's `licenses` directory when
redistributing it.

The preparation recipe verifies the pinned Linux compiler as well as the seed
inventory; use its `--help` for explicit paths. A fresh output directory is
required. The pack requires application 0.6.0 or later. Graph tests run in a
fresh process against the released starter; the graph test's temporary parent
can be selected with `NW_GATK_TEMP_DIR`.

The release's matching source/evidence companion includes the adapter, recipes,
fixtures, build provenance, test records, full `knowledge/` snapshot and root
`AGENTS.md`. Its creation-time pending-final-gate statements are historical;
the separate final Windows validation report records completion. Do not replace
the immutable source ZIP to revise that status.

## Verification boundaries

`scripts/generate_gatk_fixtures.py` generates small public synthetic DNA fixtures
with specified variants/genotypes, duplicate pairs, sequencing errors, reference
blocks and independently specified gVCF likelihoods. The fixture generator does
not simulate GATK analysis results. `tests/test_gatk_pack.py` exercises scientific
outputs and rejection cases; `tests/test_gatk_pipeline.py` checks compatibility
with the unchanged released application. `workbench-checks.json` supplies the
installed **File → Check installation** checks.

Linux execution, static ZIP validation, released-app graph checks and native
Windows execution are separate evidence levels. Final release evidence records
their commands, tested archive/manifest hashes, results and native run URLs.
Neither these synthetic controls nor the Windows CLI gate establish interactive
GUI acceptance, institutional approval, diagnostic validity or large-data
performance.

## Recorded release evidence

The [dated validation record](../knowledge/evidence/gatk-1.0.0-validation-2026-10-04.json)
and [final Windows report](https://github.com/comparativechrono/workbench/releases/download/pack-gatk-v1.0.0/native-workbench-gatk-1.0.0-windows-validation.json)
identify the exact tested bytes. At source
`eb4a255b69a2eabfb539937218a1d0e57c5776a3`:

| Gate | Result and scope |
| --- | --- |
| Linux scientific/regression suite | 14 tests passed, including known variants/genotypes, duplicate flags, recalibrated qualities, invalid-input rejection, missing per-read RG rejection and legitimate empty VCF subsets |
| Native Windows candidate | [Run 37220034835](https://github.com/comparativechrono/workbench/actions/runs/37220034835): nine scientific checks and seven graph/archive contracts passed in each path |
| Exact final native Windows archive | [Run 37220420948](https://github.com/comparativechrono/workbench/actions/runs/37220420948): nine scientific checks and seven graph/archive contracts passed in each ordinary/space-containing `windows-2022` path, with no failures/errors/skips |

The scientific gate imports through the released native bridge and checks
duplicate-version rejection. The separate graph/archive suite runs the
unchanged released application code and uses a Python copy callback for folder
publication; it does not itself run the scientific tools or native importer.
The Linux graph suite's six graph/application checks passed, but the strict
archive-copy check encountered transient files or changed hashes in disposable
copies. Those diagnostics are retained; no clean seven-test Linux graph pass is
claimed. Both Windows paths passed the unchanged strict archive assertions.

Final ZIP SHA-256:
`e9eb3a4966f83d667ebb424612aaedd07236bac98c3462d4efbe02c55166bb24`.
Final manifest SHA-256:
`4d876053d922628f8c97896268a32c72a648b6c51b93d3364beecc641293e713`.

Upstream references:

- <https://github.com/broadinstitute/gatk/releases/tag/4.7.0.0>
- <https://github.com/broadinstitute/gatk>
- <https://gatk.broadinstitute.org/hc/en-us/articles/360035889971--How-to-Consolidate-GVCFs-for-joint-calling-with-GenotypeGVCFs>
