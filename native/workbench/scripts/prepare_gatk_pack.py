#!/usr/bin/env python3
"""Prepare an independent GATK 4 germline pack from the immutable Mutect2 seed.

No downloads occur here. Recover the exact released seed and pinned compiler
using scripts/fetch_gatk_build_inputs.py. Never modify the published seed pack.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from prepare_modular_packs import field, number, artifact, execute, workflow
from generate_gatk_fixtures import generate, self_checks
PACK_VERSION = '1.0.0'
GATK = '4.7.0.0'
JAVA = '17.0.20.1+1'
SEED_MANIFEST_SHA256 = 'bef9c8ee3b35b3b4ead54ed359a019d6592933e5ee84a05e449d014891f7ab3e'
GATK_SHA256 = '882e180707e0e6887885853fc486fa54098620fe9a80bdcdaaa655c7e3861365'
COMPAT_SHA256 = 'd3a35b8cf2790f12b5d57574b7d46de3598a8836201f3f9b899798521db9e78a'
CITATIONS = [
    {'text': 'Van der Auwera GA and O\'Connor BD (2020). Genomics in the Cloud. O\'Reilly Media. GATK germline short variant discovery.', 'url': 'https://gatk.broadinstitute.org/'},
    {'text': 'McKenna et al. (2010). The Genome Analysis Toolkit: a MapReduce framework for analyzing next-generation DNA sequencing data. Genome Research 20:1297–1303.', 'url': 'https://doi.org/10.1101/gr.107524.110'},
    {'text': 'DePristo et al. (2011). A framework for variation discovery and genotyping using next-generation DNA sequencing data. Nature Genetics 43:491–498.', 'url': 'https://doi.org/10.1038/ng.806'},
]


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def definitions():
    workflows = []
    schema = dict(schema=1, category='Variant calling', citations=CITATIONS, workflows={})
    labels = {
        'mark-duplicates': ('MarkDuplicates: mark DNA duplicates', 'Coordinate-based duplicate marking without removing reads; optical duplicate detection is disabled.'),
        'bqsr': ('Base-quality recalibration: learn and apply', 'Learn BQSR from selected intervals and explicitly supplied known sites, then apply it to the complete BAM.'),
        'haplotypecaller-vcf': ('HaplotypeCaller: single-sample VCF', 'Call germline SNPs and indels in selected BED intervals; output unfiltered variant calls.'),
        'haplotypecaller-gvcf': ('HaplotypeCaller: reference-confidence gVCF', 'Generate single-sample GATK gVCF blocks and likelihoods for subsequent genotyping.'),
        'combine-gvcfs': ('CombineGVCFs: combine a small cohort', 'Combine two or more distinct-sample GATK gVCFs while retaining reference-confidence likelihoods.'),
        'genotype-gvcfs': ('GenotypeGVCFs: genotype one or more samples', 'Genotype a single-sample or combined GATK gVCF to produce ordinary unfiltered VCF calls.'),
        'select-variants': ('SelectVariants: select SNPs or indels', 'Retain all variants or select SNP/INDEL records without claiming that retained records pass quality criteria.'),
        'variant-filtration': ('VariantFiltration: label a chosen criterion', 'Label records using a chosen site annotation and threshold; retain input records and existing filters.'),
        'validate-variants': ('ValidateVariants: check reference and VCF', 'Run GATK reference-allele, alternate-allele and chromosome-count checks; no dbSNP ID membership check.'),
    }
    for identity, (label, description) in labels.items():
        fields, ports, outputs, products = [], [], [], []
        parameters, input_args = [], []

        def input_file(key, label, kind, help='', multiple=False, maximum=1, minimum=1, **metadata):
            filters = {'reference': 'Uncompressed FASTA|*.fa;*.fasta;*.fna', 'bam': 'Coordinate-sorted DNA BAM|*.bam',
                       'bed': 'BED intervals|*.bed', 'vcf': 'VCF calls|*.vcf;*.vcf.gz', 'file': 'GATK gVCF|*.g.vcf;*.g.vcf.gz;*.vcf;*.vcf.gz'}
            fields.append(field(key, label, 'files' if multiple else 'file', filter=filters[kind], help=help))
            ports.append(dict(id=key, type=kind, manifestInputs=[key], min=minimum, max=maximum, **metadata))
            input_args.extend(['--' + key, '{inputs:' + key + '}' if multiple else '{input:' + key + '}'])

        def product(key, label, path, kind, state=None, propagate=None):
            outputs.append(artifact(key, label, path))
            item = dict(id=key, type=kind, manifestOutputs=[key])
            if state: item['state'] = state
            if propagate: item['propagateStateFrom'] = propagate
            products.append(item)

        if identity != 'mark-duplicates':
            input_file('reference', 'Matching reference genome', 'reference', 'The exact uncompressed genomic FASTA used for alignment/calling. A private copy, FAI and sequence dictionary are built in this run.', requiredState={'compression': 'none'})
        if identity in ('mark-duplicates', 'bqsr', 'haplotypecaller-vcf', 'haplotypecaller-gvcf'):
            validation = {'singleSample': True}
            if identity != 'mark-duplicates': validation['sampleParameter'] = 'sample'
            input_file('bam', 'Coordinate-sorted single-sample DNA BAM', 'bam', 'Read-group SM labels must name one sample. Prepare DNA alignments and mark duplicates before BQSR/calling. RNA-specific calling is not exposed.',
                       requiredState={'sort': 'coordinate'}, validation=validation)
            if identity != 'mark-duplicates':
                fields.append(field('sample', 'Sample name (BAM SM)', 'text', default='SAMPLE', constraint='identifier', help='Must exactly match the BAM SM label; ASCII letters, digits, dot, underscore or hyphen.'))
                parameters += ['--sample', '{input:sample}']
                input_file('targets', 'Analysis intervals (BED3)', 'bed', 'Zero-based, end-exclusive BED intervals. Full-contig intervals can cover a complete reference. For BQSR, these intervals train the model; the whole BAM is then recalibrated.', validation={'minColumns': 3, 'referenceBounds': True})
        if identity == 'bqsr':
            input_file('known-sites', 'Known polymorphic sites (one or more VCFs)', 'vcf', 'Trusted known polymorphisms for the identical organism and reference assembly. Do not use called variants from this sample as a substitute. No resource is downloaded automatically.', multiple=True, maximum=32)
            product('recalibration', 'BQSR model table', 'recalibration.table', 'file')
        if identity in ('mark-duplicates', 'bqsr'):
            product('bam', 'Duplicate-marked BAM' if identity == 'mark-duplicates' else 'Base-quality recalibrated BAM', 'output.bam', 'bam',
                    {'sort': 'coordinate', **({'duplicates': 'marked'} if identity == 'mark-duplicates' else {})}, 'bam')
            product('bam-index', 'BAM BAI index', 'output.bam.bai', 'index')
            product('bam-summary', 'Read/duplicate counts and quality histogram', 'bam-summary.json', 'metrics')
            if identity == 'mark-duplicates': product('metrics', 'Duplicate-marking metrics', 'duplicate-metrics.txt', 'metrics')
        if identity.startswith('haplotypecaller-'):
            for name, text, value, low, high in [('ploidy', 'Sample ploidy', 2, 1, 32), ('min-mapq', 'Minimum read mapping quality', 20, 0, 60), ('min-baseq', 'Minimum base quality', 10, 6, 93)]:
                fields.append(number(name, text, value, low, high, help='Ploidy applies to every selected interval; split analyses where contig ploidy differs.' if name == 'ploidy' else 'Recorded GATK read/base inclusion setting.'))
                parameters += ['--' + name, '{input:' + name + '}']
        if identity == 'combine-gvcfs':
            input_file('gvcfs', 'GATK gVCFs from distinct samples', 'file', 'Select two to 32 HaplotypeCaller/CombineGVCFs gVCFs with NON_REF likelihoods, unique sample labels and the same reference. Ordinary VCF cannot reconstruct reference confidence.', multiple=True, minimum=2, maximum=32)
        elif identity == 'genotype-gvcfs':
            input_file('gvcf', 'Single or combined GATK gVCF', 'file', 'GATK reference-confidence gVCF with NON_REF alleles and PL likelihoods. An ordinary VCF or BQSR table is rejected by the adapter.')
        elif identity in ('select-variants', 'variant-filtration', 'validate-variants'):
            input_file('variants', 'Ordinary VCF calls', 'vcf', 'Plain or gzip-compressed VCF, using the selected reference. gVCFs must be genotyped first.', accepts=['vcf', 'vcf-pass'])
        if identity == 'select-variants':
            fields.append(field('variant-type', 'Records to retain', 'choice', default='SNP', choices='ALL:All variants|SNP:SNP records|INDEL:Insertion/deletion records', help='Upstream record-type selection; mixed records are not split or normalized.'))
            parameters += ['--variant-type', '{input:variant-type}']
        if identity == 'variant-filtration':
            fields += [field('filter-annotation', 'Site annotation', 'choice', default='QUAL', choices='QUAL:Variant QUAL|QD:Quality by depth (QD)|FS:Fisher strand (FS)|SOR:Strand odds ratio (SOR)|MQ:RMS mapping quality (MQ)|MQRankSum:Mapping quality rank sum|ReadPosRankSum:Read position rank sum|DP:Site depth (DP)', help='One site-level criterion per operation. Chain operations to apply further criteria. Missing evaluated annotations fail.'),
                       field('filter-comparison', 'Label when value is', 'choice', default='lt', choices='lt:Less than threshold|gt:Greater than threshold'),
                       field('filter-threshold', 'Threshold', 'text', default='30', help='A finite decimal number, including negative rank-sum thresholds. Default QUAL below 30 is an editable example, not a recommended filtering protocol.'),
                       field('filter-name', 'FILTER label', 'text', default='LowQual', constraint='identifier', help='Distinct ASCII identifier beginning with a letter; do not use PASS. Choose a descriptive different label for each criterion.')]
            for name in ('filter-annotation', 'filter-comparison', 'filter-threshold', 'filter-name'): parameters += ['--' + name, '{input:' + name + '}']
        if identity in ('haplotypecaller-gvcf', 'combine-gvcfs'):
            product('gvcf', 'GATK reference-confidence gVCF (requires genotyping)', 'output.g.vcf', 'file')
        elif identity in ('haplotypecaller-vcf', 'genotype-gvcfs', 'select-variants', 'variant-filtration'):
            product('variants', 'VCF with retained FILTER labels' if identity == 'variant-filtration' else 'Unfiltered/selected VCF calls', 'variants.vcf', 'vcf',
                    {'compression': 'none', 'selection': 'all-calls-with-filter-labels'} if identity == 'variant-filtration' else {'compression': 'none'})
        elif identity == 'validate-variants':
            product('validation', 'Successful validation record', 'validation.json', 'metrics')
        fields.append(number('memory', 'Maximum GATK Java heap (MiB)', 2048, 512, 65536, help='Heap per GATK subprocess, not total RAM: the adapter, Java overhead and OS need additional memory. Large genomes/cohorts may require substantially more RAM/disk.'))
        product('commands', 'Exact GATK command arguments', 'commands.json', 'metrics')
        product('input-check', 'Completed local-input checks', 'input-validation.json', 'metrics')
        args = ['-Xms32m', '-Xmx256m', '-XX:+ExitOnOutOfMemoryError', '-XX:+DisableAttachMechanism', '-XX:-UsePerfData', '-Djava.awt.headless=true',
                '-Dfile.encoding=UTF-8', '-Djava.io.tmpdir={run}', '-Dsamjdk.use_jdk_inflater=true', '-Dsamjdk.use_jdk_deflater=true',
                '-Dsamjdk.use_libdeflate=false', '-Dsamjdk.snappy.disable=true', '-jar', '{asset:adapter}', identity, '{run}', '{input:memory}', *parameters, *input_args]
        steps = []
        if identity in ('mark-duplicates', 'bqsr', 'haplotypecaller-vcf', 'haplotypecaller-gvcf'):
            steps.append(execute('check-bam', 'Check BAM file integrity', 'samtools', ['quickcheck', '-v', '{input:bam}']))
        steps.append(execute('run', label, 'java', args, produces=[x['id'] for x in outputs]))
        workflows.append(workflow(identity, label, description, fields, outputs, steps))
        methods = {
            'mark-duplicates': 'DNA read duplicates were marked with GATK/Picard MarkDuplicates 4.7.0.0 using coordinate-sorted single-sample alignments. Reads were retained; optical-duplicate detection was explicitly disabled because read-name geometry is assay-specific. Duplicate metrics and an indexed BAM were retained.',
            'bqsr': 'Base quality score recalibration was learned with GATK BaseRecalibrator 4.7.0.0 over the recorded BED intervals using the explicitly selected local known-polymorphism resources. ApplyBQSR applied that model to the complete input BAM. Default upstream covariates and recalibration parameters were retained. The supplied resources must match the organism and assembly; this workflow does not discover known sites.',
            'haplotypecaller-vcf': 'Germline SNPs and indels were called with GATK HaplotypeCaller 4.7.0.0 over the recorded BED intervals, with the recorded sample ploidy, mapping/base quality thresholds and upstream default calling settings. Pure-Java LOGLESS_CACHING PairHMM and JAVA Smith-Waterman were used. The resulting single-sample VCF is unfiltered; duplicate marking, BQSR and downstream filtering are separate operations.',
            'haplotypecaller-gvcf': 'GATK HaplotypeCaller 4.7.0.0 was run in GVCF reference-confidence mode over the recorded BED intervals using the recorded sample ploidy and read/base quality thresholds, upstream default GQ bands, pure-Java LOGLESS_CACHING PairHMM and JAVA Smith-Waterman. NON_REF likelihoods and reference blocks were retained for subsequent genotyping. A gVCF is not a final set of variant calls.',
            'combine-gvcfs': 'Reference-confidence gVCFs from distinct samples were combined with GATK CombineGVCFs 4.7.0.0 using the selected common reference. NON_REF likelihoods were retained. This sequential operation targets small cohorts; no GenomicsDB, Spark or distributed execution was used. Joint genotyping and filtering remain separate operations.',
            'genotype-gvcfs': 'Genotypes were calculated with GATK GenotypeGVCFs 4.7.0.0 from the selected single-sample or combined GATK reference-confidence gVCF using the selected matching reference and upstream default genotyping settings. Variant-only VCF output was retained without normalization or filtering. Ploidy/likelihoods originate in the supplied gVCF.',
            'select-variants': 'GATK SelectVariants 4.7.0.0 retained the recorded variant type (ALL, SNP or INDEL). Records were not split, normalized or filtered by quality. Existing FILTER labels were retained; type selection does not establish variant reliability.',
            'variant-filtration': 'GATK VariantFiltration 4.7.0.0 applied the recorded FILTER label when the selected site annotation (QUAL, QD, FS, SOR, MQ, MQRankSum, ReadPosRankSum or DP) met the recorded less-than/greater-than threshold, retaining all records and existing filters. Missing evaluated annotation values were configured to fail. One explicit criterion was applied per operation; operations may be chained with distinct labels. The chosen thresholds require assay-specific review and validation; VQSR was not performed.',
            'validate-variants': 'GATK ValidateVariants 4.7.0.0 checked the ordinary VCF against the selected reference, retaining default reference-allele, alternate-allele and chromosome-count validation. The IDS check was explicitly excluded because no dbSNP membership resource was supplied. Successful format/reference validation does not establish biological or clinical accuracy.',
        }[identity]
        methods += ' The unchanged upstream local JAR ran with Workbench local-path adaptation 1 and a private Java 17 runtime, JDK compression, disabled Snappy/libdeflate and run-local temporary copies/indexes. Exact child arguments were recorded in commands.json.'
        schema['workflows'][identity] = dict(ports=ports, outputs=products, methods=methods)
    return workflows, schema


def verify_seed(seed):
    if sha(seed.parent / 'workbench-pack.json') != '03cfbc1874fa59c27332fa9986974ac9d65ed87fc3ce5e9f3cfbb64e9f5922ac':
        raise ValueError('Published seed envelope checksum differs')
    envelope = json.loads((seed.parent / 'workbench-pack.json').read_text(encoding='utf-8'))
    if envelope['id'] != 'mutect2' or envelope['version'] != '0.5.4' or envelope['manifestSha256'] != SEED_MANIFEST_SHA256 or sha(seed / 'pack.ini') != SEED_MANIFEST_SHA256:
        raise ValueError('Expected the unchanged published mutect2 0.5.4 seed')
    records = envelope['files']
    expected = set()
    for record in records:
        relative = Path(record['path'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in record['path'] or record['path'] in expected:
            raise ValueError('Unsafe/repeated seed inventory path')
        expected.add(record['path']); path = seed / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size != record['size'] or sha(path) != record['sha256']:
            raise ValueError('Seed inventory differs: ' + record['path'])
    actual = {p.relative_to(seed).as_posix() for p in seed.rglob('*') if p.is_file()}
    if actual != expected: raise ValueError('Seed contains undeclared or missing files')
    if sha(seed / 'assets/gatk.jar') != GATK_SHA256 or sha(seed / 'assets/gatk-path-compat.jar') != COMPAT_SHA256:
        raise ValueError('Pinned GATK/compatibility JAR differs')
    return envelope


def prepare(seed, output, javac):
    seed, output, javac = Path(seed).resolve(), Path(output).resolve(), Path(javac).resolve()
    envelope = verify_seed(seed)
    if output.exists() and any(output.iterdir()): raise ValueError('Output must be new or empty')
    output.mkdir(parents=True, exist_ok=True)
    # Copy only the authenticated inventory, using streamed I/O rather than
    # platform fast-copy shortcuts, and verify the destination too. A source
    # checked before copying does not prove that a later copy is complete.
    for record in envelope['files']:
        relative = record['path']
        if not (relative.startswith(('runtime/', 'licenses/')) or relative in ('assets/gatk.jar', 'assets/gatk-path-compat.jar', 'bin/samtools.exe')):
            continue
        target = output / relative; target.parent.mkdir(parents=True, exist_ok=True)
        with (seed / relative).open('rb') as source_handle, target.open('xb') as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, 1024 * 1024)
        if target.stat().st_size != record['size'] or sha(target) != record['sha256']:
            raise ValueError('Copied seed file differs from pinned inventory: ' + relative)
    (output / 'fixtures').mkdir()
    if os.name != 'nt' and (sha(javac) != '50d09f424b513525af1f0b05cd948ed7890a8d60fef7f7797e20892705b0067d' or sha(javac.parent.parent / 'lib/modules') != '6a1b657bd845397ab30fe2d4d78d80c4fdc05107182843669fc928655c227241'):
        raise ValueError('Pinned Linux compiler or module image differs')
    env = dict(os.environ)
    if os.name != 'nt': env['LD_LIBRARY_PATH'] = str(javac.parent.parent / 'lib') + ':' + str(javac.parent.parent / 'lib/server')
    version_run = subprocess.run([str(javac), '-version'], capture_output=True, text=True, env=env, check=True)
    compiler = (version_run.stdout + version_run.stderr).strip()
    if compiler != 'javac 17.0.20.1': raise ValueError('Expected pinned Java 17.0.20.1 compiler; got ' + compiler)
    source = ROOT / 'tools/gatk/WorkbenchGatk.java'
    with tempfile.TemporaryDirectory(prefix='gatk-classes-', dir=output.parent) as temporary:
        command = [str(javac), '--release', '17', '-encoding', 'UTF-8', '-proc:none', '-g:source,lines', '-cp', str(output / 'assets/gatk.jar'), '-d', temporary, str(source)]
        subprocess.run(command, check=True, env=env)
        with zipfile.ZipFile(output / 'assets/gatk-path-compat.jar') as archive:
            manifest = archive.read('META-INF/MANIFEST.MF').decode('utf-8')
        # Preserve upstream Add-Opens while changing only the entry point and class path.
        manifest = manifest.replace('Main-Class: org.broadinstitute.hellbender.Main', 'Main-Class: WorkbenchGatk').replace('Class-Path: gatk.jar', 'Class-Path: gatk-path-compat.jar gatk.jar')
        if 'Main-Class: WorkbenchGatk' not in manifest: raise ValueError('Upstream main class differs')
        entries = [('META-INF/MANIFEST.MF', manifest.encode('utf-8'))] + [(p.relative_to(temporary).as_posix(), p.read_bytes()) for p in sorted(Path(temporary).rglob('*.class'))]
        with zipfile.ZipFile(output / 'assets/workbench-gatk.jar', 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in entries:
                info = zipfile.ZipInfo(name, (2026, 10, 4, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
    generate(output / 'fixtures')
    workflows, schema = definitions(); dump(output / 'workbench-schema.json', schema); dump(output / 'workbench-checks.json', self_checks())
    assets = {'adapter': 'assets/workbench-gatk.jar', 'gatk': 'assets/gatk.jar', 'gatk-compat': 'assets/gatk-path-compat.jar', 'workbench-schema': 'workbench-schema.json', 'workbench-checks': 'workbench-checks.json'}
    fixture_ids = {'sample-a.g.vcf': 'gvcf-a', 'sample-b.g.vcf': 'gvcf-b'}
    for path in sorted((output / 'fixtures').iterdir()): assets['fixture-' + fixture_ids.get(path.name, path.stem)] = 'fixtures/' + path.name
    for path in sorted((output / 'runtime').rglob('*')):
        relative = path.relative_to(output).as_posix()
        if path.is_file() and relative != 'runtime/java/bin/java.exe': assets['runtime-' + hashlib.sha256(relative.encode()).hexdigest()[:16]] = relative
    sections = []
    def section(name, values):
        sections.append('[' + name + ']\n' + '\n'.join(k + '=' + str(v) for k, v in values.items() if k != 'id' or name == 'pack') + '\n')
    section('pack', dict(format=2, id='gatk', version=PACK_VERSION, name='GATK germline variants and preparation', platform='windows-x86_64', color='#796FA9',
                        description='GATK 4.7.0.0 germline calling, reference-confidence genotyping, duplicate marking, BQSR and VCF operations. Private Java included.'))
    section('tool:java', dict(path='runtime/java/bin/java.exe', version='Temurin-' + JAVA, sha256=sha(output / 'runtime/java/bin/java.exe')))
    section('tool:samtools', dict(path='bin/samtools.exe', version='1.24', sha256=sha(output / 'bin/samtools.exe')))
    for identity, path in assets.items(): section('asset:' + identity, dict(path=path, sha256=sha(output / path)))
    for wf in workflows:
        section('workflow:' + wf['id'], dict(name=wf['name'], description=wf['description'], inputs=','.join(x['id'] for x in wf['inputs']), outputs=','.join(x['id'] for x in wf['outputs']), steps=','.join(x['id'] for x in wf['steps'])))
        for kind in ('input', 'output', 'step'):
            for record in wf[kind + 's']: section(kind + ':' + wf['id'] + ':' + record['id'], record)
    (output / 'pack.ini').write_text('\n'.join(sections), encoding='utf-8')
    for path in (source, Path(__file__), ROOT / 'scripts/generate_gatk_fixtures.py', ROOT / 'LICENSE'): shutil.copy2(path, output / 'licenses' / path.name)
    (output / 'PACK-README.md').write_text(README, encoding='utf-8')
    dump(output / 'licenses/GATK-GERMLINE-PROVENANCE.json', dict(schema=1, packId='gatk', packVersion=PACK_VERSION, gatkVersion=GATK, javaVersion=JAVA,
         seedRelease='https://github.com/comparativechrono/workbench/releases/tag/pack-mutect2-v0.5.4', seedManifestSha256=SEED_MANIFEST_SHA256,
         seedEnvelopeSha256='03cfbc1874fa59c27332fa9986974ac9d65ed87fc3ce5e9f3cfbb64e9f5922ac',
         seedArchiveSha256='25786d85b3679f172331142f890b1bffe5f5e77497b97eb91af855f2858ce08b',
         gatkJarSha256=GATK_SHA256, compatibilityJarSha256=COMPAT_SHA256, adapterCompiler=compiler, compilerExecutableSha256=sha(javac),
         adapterSourceSha256=sha(source), adapterJarSha256=sha(output / 'assets/workbench-gatk.jar'), compilerArguments=['--release', '17', '-encoding', 'UTF-8', '-proc:none', '-g:source,lines'],
         source='Complete unchanged GATK/OpenJDK/dependency source and licensing material copied from the verified seed inventory; Workbench adapter source and recipe included.',
         algorithmsModified=False, nativeWindowsExecutedDuringBuild=False, supportedOperations=list(schema['workflows']),
         compatibility='Generic file graph ports for gVCF on application 0.6.0; adapter enforces NON_REF and PL contracts. Not general Windows support for all GATK tools.'))
    sys.path.insert(0, str(ROOT / 'workspace'))
    from catalog import load_pack
    pack = load_pack(output / 'pack.ini')
    members = list(output.rglob('*')); size = sum(p.stat().st_size for p in members if p.is_file())
    if len(members) > 2000 or size > 1024**3 or any(p.is_file() and p.stat().st_size > 512*1024**2 for p in members): raise ValueError('Pack exceeds import inventory bounds')
    return dict(packRoot=str(output), packId='gatk', packVersion=PACK_VERSION, workflows=list(pack['workflows']), manifestSha256=sha(output / 'pack.ini'), expandedBytes=size)


README = '''# GATK germline variants and preparation

Optional pack gatk 1.0.0 for Native Workbench 0.6.0 or newer. Includes GATK 4.7.0.0, its existing Workbench local-path compatibility adaptation and a complete private Temurin Java 17 runtime. No system Java, WSL, Docker, browser, administrator rights or analysis-time downloads are required. The original Mutect2 pack is unchanged and remains the somatic calling interface.

Nine independent operations expose MarkDuplicates, BaseRecalibrator+ApplyBQSR, HaplotypeCaller VCF, HaplotypeCaller gVCF, CombineGVCFs, GenotypeGVCFs, SelectVariants, VariantFiltration and ValidateVariants. Each can run alone or connect to a pipeline. All scientific algorithms use the unchanged upstream GATK JAR. The adapter stages explicitly chosen local files, creates private indexes, validates contracts and invokes the upstream commands with argument arrays. Child commands and normal Workbench methods/provenance are retained. Child processes use the pack-private Java runtime and inherit the runner process tree.

Supply coordinate-sorted single-sample DNA BAM with read groups, an RG tag on every record, and ASCII SM labels, the exact uncompressed reference, and explicit BED intervals for calling/BQSR. BQSR requires appropriate known polymorphism VCFs for the organism/assembly. Its BED intervals train the model; ApplyBQSR applies the model to the complete BAM. MarkDuplicates retains all reads and disables optical duplicate detection; optical duplicate metrics are therefore not estimated. RNA-specific preprocessing/calling, UMI-aware deduplication and optical duplicate detection are not provided.

HaplotypeCaller uses pure-Java LOGLESS_CACHING PairHMM and JAVA Smith-Waterman; JDK compression is explicit throughout and Snappy/libdeflate are disabled. This favors Windows portability over native SIMD speed. The memory option caps one GATK Java heap, not total RAM; a 256 MiB adapter heap, JVM overhead and OS memory are additional. Private copies can need substantial disk space. BAI indexing imposes its usual contig coordinate limits. Small synthetic checks do not establish human-genome throughput or clinical suitability.

A gVCF retains reference-confidence likelihoods and must be genotyped before ordinary VCF processing. Application 0.6.0 represents gVCF as a generic file port with explicit gVCF labels, so other generic files can be connected visually; the adapter rejects files without the required NON_REF/sample/PL data. Ordinary VCF and gVCF ports have distinct graph types. CombineGVCFs accepts two to 32 distinct-sample inputs and targets smaller cohorts. GenomicsDBImport, Spark, cohort-scale performance, VQSR, CNV tools, Python-dependent tools and every possible GATK switch are outside this pack.

VariantFiltration preserves every record and existing filters, and labels one chosen site-level annotation/comparison/threshold criterion. Supported annotations are QUAL, QD, FS, SOR, MQ, MQRankSum, ReadPosRankSum and DP. Chain operations with distinct filter labels for additional criteria. Missing evaluated annotation values fail. The editable default QUAL below 30 is not a validated filtering recommendation or complete GATK Best Practices protocol. ValidateVariants checks reference/alleles/chromosome counts but excludes dbSNP ID membership because no dbSNP resource is supplied. Empty ordinary VCF results are valid; gVCF inputs must contain reference-confidence records. No calling operation automatically applies duplicate marking, BQSR or variant filtering.

The seed runtime/licenses were verified against the immutable mutect2 0.5.4 inventory. Complete GATK, OpenJDK and dependency source/licensing material is retained under licenses, alongside the adapter and preparation recipe. Historical seed BUILD-PROVENANCE.json describes the inherited Mutect2 build; GATK-GERMLINE-PROVENANCE.json describes this pack. Java is GPLv2 with Classpath Exception; GATK is Apache 2.0 and bundled dependencies keep their own terms, including separate Microsoft runtime component terms. The upstream jar is unchanged; the inherited path patch and its source are included. Linux tests, static Windows validation and actual native Windows execution are separate evidence levels.
'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-pack', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--javac', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.seed_pack, args.output, args.javac), indent=2))
