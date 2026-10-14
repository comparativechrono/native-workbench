# LoFreq quality-aware variant calling

Pack 0.5.3 requires Native Workbench 0.5.3. LoFreq 2.1.5 (workbench-port2) with HTSlib 1.24 and SAMtools 1.24, compiled as local Cosmopolitan x86-64 executables. No Docker, Linux installation, remote compute, shell or external Python is used by these workflows. Single-threaded operation is deliberate.

Three individual/pipeline tools: SNV calling; Illumina Dindel indel-quality preparation; preparation followed by SNV+indel calling. Coordinate-sorted DNA BAM and the exact uncompressed reference are required. Duplicate-marked alignments are recommended. Spliced RNA alignments are not supported by indel preparation. Dindel qualities assume Illumina errors and replace existing BI/BD tags only in a new output BAM. They are not BQSR or realignment; do not realign after this step.

LoFreq uses sequencing/mapping/alignment error probabilities, dynamic Bonferroni correction and default post-call coverage/strand-bias filters. Output is PASS sites only. AF is the observed alternate read fraction, not a genotype. QUAL measures evidence against the error model, not a calibrated clinical pathogenicity probability. VCF has eight columns, no sample genotypes/ploidy model. Low-frequency calls require suitable depth, controls and assay-specific validation; this pack does not claim somatic tumor-normal inference. Defaults may require adjustment for a given assay. Target BED restriction is not exposed in this initial pack, so targeted analyses retain default dynamic whole-input testing.

Reference indexes and any new BAM indexes are built beside private run copies/results. Original inputs are read-only. The calling SNP operation does not need to modify/index the input BAM. The complete original LoFreq call/filter calculations are retained. Its internal shell filter launch is replaced with a direct call to its own filter function using separate argv elements; temporary VCFs are reserved in the run folder. Paths with spaces are tested on Linux/APE; Windows filesystem behavior remains subject to native validation.

## Redistribution and source

LoFreq is MIT, uthash BSD, HTSlib/SAMtools MIT/BSD and Cosmopolitan permissive with included third-party notices. Upstream includes an unused cdflib90 directory carrying older ACM copy restrictions; `uniq` is therefore unavailable and neither its binom/CDF code nor historical prebuilt dist archives is redistributed or linked. licenses/provenance.json records the original source URL/hash and exact excluded members; the corresponding permitted source subset, patch, build scripts and linked-library sources/notices are included. No algorithm used by call, filter or indelqual was changed. Rebuild from the source subset using build_lofreq.py --source-archive; the script verifies its pinned hash, applies the included changes and uses explicit source lists; original upstream downloads are optional for provenance verification, not redistribution.

## Validation scope

Scientific fixtures test a balanced-strand 10% SNV (40/400 reads) with rejected low-quality noise and a 20% insertion (80/400) after Dindel preparation. Linux-native and actual portable APE binaries are compared. These are synthetic correctness fixtures, not sensitivity/specificity benchmarks. Windows execution has not been performed here: Check installation runs the actual packaged executables and structural VCF assertions on the user's machine. Upstream version, argv, input hashes and methods are recorded for each run.

Citation: Wilm et al. (2012), Nucleic Acids Research 40:11189–11201, doi:10.1093/nar/gks918. Dindel: Albers et al. (2011), Genome Research 21:961–973, doi:10.1101/gr.112326.110.
