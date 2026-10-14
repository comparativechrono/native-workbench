#!/usr/bin/env python3
"""Generate expanded research packs; every workflow is a declarative pack."""
import argparse
import copy
import hashlib
from pathlib import Path
import shutil
import prepare_modular_packs as base

ROOT = base.ROOT
VERSION = base.VERSION
PACK_VERSIONS = {'fastp': '0.4.1', 'research-variants': '0.4.1'}
field, number, artifact, execute, workflow = base.field, base.number, base.artifact, base.execute, base.workflow


def choice(id, label, default, choices, **kw):
    return field(id, label, 'choice', default=default, choices=choices, **kw)


def threads():
    return number('threads', 'Trimming / alignment workers', 2, 1, 64,
                  help='Workers used by Cutadapt, fastp and the aligner. SAMtools and BCFtools remain single-threaded in this build.')


def groups():
    return [field('sample', 'Sample name (SM)', 'text', default='sample', constraint='identifier'),
            field('read-group', 'Read group ID', 'text', default='group1', constraint='identifier',
                  help='Use a unique read-group ID for each lane when merging lanes.'),
            field('library', 'Library ID (LB)', 'text', default='library1', constraint='identifier',
                  help='Lanes from the same physical library should share LB; independent libraries should not.'),
            field('platform-unit', 'Platform unit (PU)', 'text', default='unit1', constraint='identifier',
                  help='For Illumina, a flowcell/lane identifier is customary.'),
            choice('platform', 'Sequencing platform (PL)', 'ILLUMINA', 'ILLUMINA:Illumina|DNBSEQ:DNBSEQ (MGI/BGI)')]


def read_group():
    return r'@RG\tID:{input:read-group}\tSM:{input:sample}\tLB:{input:library}\tPL:{input:platform}\tPU:{input:platform-unit}'


def trimming_fields(adapters=True, paired=True):
    result = []
    if adapters:
        result.append(field('adapter1', "Read 1 3' adapter sequence", 'text', constraint='dna',
                            help="Enter the sequence appropriate to the library using IUPAC DNA letters. No adapter is assumed."))
        if paired:
            result.append(field('adapter2', "Read 2 3' adapter sequence", 'text', constraint='dna',
                                help="Enter the mate-specific adapter, not the reverse complement of the read."))
        result += [number('trim-overlap', 'Minimum adapter overlap', 3, 1, 1000),
                   choice('trim-error', 'Maximum adapter error rate', '0.1', '0.0:0%|0.05:5%|0.1:10%|0.15:15%|0.2:20%')]
    return result + [number('trim-quality', "3' quality trimming cutoff", 20, 0, 93,
                           help='Phred+33 input; zero disables quality trimming. Cutadapt uses its quality-trimming algorithm, not a sliding window.'),
                     number('min-length', 'Minimum retained read length', 35, 1, 100000,
                            help='For paired data, both mates must pass; a pair is rejected if either mate is too short.')]


def trim_outputs(paired=True):
    outputs = [artifact('trimmed1', 'Trimmed read 1', 'reads1.trimmed.fastq.gz'),
               artifact('rejected1', 'Rejected short read 1', 'reads1.rejected.fastq.gz'),
               artifact('trim-json', 'Trimming metrics (JSON)', 'trimming.json'),
               artifact('trim-report', 'Trimming report', 'trimming.txt')]
    if paired:
        outputs[1:1] = [artifact('trimmed2', 'Trimmed read 2', 'reads2.trimmed.fastq.gz')]
        outputs += [artifact('rejected2', 'Rejected short read 2', 'reads2.rejected.fastq.gz')]
    return outputs


def cutadapt_step(adapters=True, paired=True):
    args = ['-I', '-B', '-m', 'cutadapt', '--cores', '{input:threads}', '--quality-base', '33',
            '-q', '{input:trim-quality}', '--minimum-length', '{input:min-length}',
            '--json', '{output:trim-json}', '-o', '{output:trimmed1}',
            '--too-short-output', '{output:rejected1}']
    produces = ['trimmed1', 'rejected1', 'trim-json']
    if adapters:
        args += ['-a', '{input:adapter1}', '--overlap', '{input:trim-overlap}', '--error-rate', '{input:trim-error}']
    if paired:
        args += ['--pair-filter', 'any', '-Q', '{input:trim-quality}', '-p', '{output:trimmed2}',
                 '--too-short-paired-output', '{output:rejected2}']
        if adapters:
            args += ['-A', '{input:adapter2}']
        produces += ['trimmed2', 'rejected2']
    args += ['{input:reads1}']
    if paired:
        args += ['{input:reads2}']
    return execute('trim', 'Trim adapters and low-quality tails' if adapters else 'Trim low-quality tails',
                   'python', args, stdout='trim-report', produces=produces)


def fastp_fields():
    return [field('adapter1', "Read 1 3' adapter", 'text', constraint='dna', help='Known adapter sequence for this library. fastp also trims adapters using paired-read overlap.'),
            field('adapter2', "Read 2 3' adapter", 'text', constraint='dna', help='Mate-specific adapter sequence; use A, C, G and T.'),
            number('trim-quality', 'Tail-window mean quality', 20, 1, 30),
            number('trim-window', 'Tail-window size', 4, 1, 1000),
            number('min-length', 'Minimum retained read length', 35, 1, 100000),
            number('qualified-quality', 'Qualified base Phred score', 15, 0, 93),
            number('unqualified-percent', 'Maximum low-quality bases (%)', 40, 0, 100),
            number('max-n', 'Maximum N bases per read', 5, 0, 100000)]


def fastp_outputs():
    return [artifact('trimmed1', 'Trimmed read 1', 'reads1.trimmed.fastq.gz'),
            artifact('trimmed2', 'Trimmed read 2', 'reads2.trimmed.fastq.gz'),
            artifact('unpaired1', 'Passing read 1 with rejected mate', 'reads1.unpaired.fastq', nonempty=False),
            artifact('unpaired2', 'Passing read 2 with rejected mate', 'reads2.unpaired.fastq', nonempty=False),
            artifact('failed-reads', 'Reads rejected by fastp', 'reads.failed.fastq', nonempty=False),
            artifact('trim-json', 'fastp metrics (JSON)', 'trimming.json'),
            artifact('trim-html', 'Offline interactive quality report', 'trimming.html'),
            artifact('plotly-js', 'Offline report graphics', 'plotly-1.2.0.min.js', False)]


def fastp_steps():
    return [dict(id='report-assets', label='Stage offline report graphics', kind='copy', source='{asset:plotly}', destination='plotly-js'),
            execute('trim', 'Trim adapters and filter paired reads with fastp', 'fastp',
                ['-i', '{input:reads1}', '-I', '{input:reads2}', '-o', '{output:trimmed1}', '-O', '{output:trimmed2}',
                 '--adapter_sequence', '{input:adapter1}', '--adapter_sequence_r2', '{input:adapter2}',
                 '--cut_tail', '--cut_tail_window_size', '{input:trim-window}', '--cut_tail_mean_quality', '{input:trim-quality}',
                 '--length_required', '{input:min-length}', '--qualified_quality_phred', '{input:qualified-quality}',
                 '--unqualified_percent_limit', '{input:unqualified-percent}', '--n_base_limit', '{input:max-n}',
                 '--thread', '{input:threads}', '--dont_eval_duplication', '--disable_trim_poly_g', '--dont_overwrite',
                 '--unpaired1', '{output:unpaired1}', '--unpaired2', '{output:unpaired2}', '--failed_out', '{output:failed-reads}',
                 '--json', '{output:trim-json}', '--html', '{output:trim-html}'],
                produces=['trimmed1', 'trimmed2', 'unpaired1', 'unpaired2', 'failed-reads', 'trim-json', 'trim-html'])]


def pair_check(id='check-pairs', one='{input:reads1}', two='{input:reads2}', output='pair-check'):
    return execute(id, 'Validate paired FASTQ records', 'paircheck', ['--reads1', one, '--reads2', two], stdout=output)


def bwa_outputs():
    return [artifact('bwa-' + ext, 'BWA index (' + ext + ')', 'bwa-reference.' + ext, False)
            for ext in ('amb', 'ann', 'bwt', 'pac', 'sa')]


def bwa_index():
    return execute('bwa-index', 'Build BWA reference index', 'bwa',
                   ['index', '-p', '{run}/bwa-reference', '{output:reference}'],
                   produces=['bwa-' + ext for ext in ('amb', 'ann', 'bwt', 'pac', 'sa')])


def alignment_step(aligner, trimmed=True, stream_sort=False):
    reads = ['{output:trimmed1}', '{output:trimmed2}'] if trimmed else ['{input:reads1}', '{input:reads2}']
    if aligner == 'bwa':
        args = ['mem', '-t', '{input:threads}', '-R', read_group(), '{run}/bwa-reference', *reads]
    else:
        args = ['-a', '-x', 'sr', '-t', '{input:threads}', '-R', read_group(), '{output:reference}', *reads]
    step = execute('align', 'Align and name-sort read pairs' if stream_sort else 'Align read pairs and stream to BAM', aligner, args, produces=['names' if stream_sort else 'aligned'])
    step['kind'] = 'pipe'
    step['sink-tool'] = 'samtools'
    sink = ['sort', '-n', '-m', '{input:sort-memory}M', '-T', '{run}/name-sort', '-o', '{output:names}', '-'] if stream_sort else ['view', '-b', '-o', '{output:aligned}', '-']
    step.update({f'sink-arg.{i}': a for i, a in enumerate(sink)})
    return step


def sort_memory():
    return number('sort-memory', 'SAMtools sort memory (MiB)', 512, 64, 32768,
                  help='Memory for each single-threaded sort. Alignment needs additional RAM depending on reference size.')


def preparation_steps():
    # The alignment pipe already performs name sorting, so no SAM or unsorted
    # BAM intermediate is materialized for full research workflows.
    steps = base.bam_steps('{output:aligned}')[1:]
    for s in steps:
        for k, v in list(s.items()):
            if k.startswith('arg.') and v == '256M':
                s[k] = '{input:sort-memory}M'
    return steps


def call_fields(caller):
    fields = base.calling_fields()
    fields[0]['help'] = 'Uniform ploidy across all contigs. Use region-aware downstream workflows for mixed-ploidy chromosomes; this field does not infer sex or karyotype.'
    if caller == 'freebayes':
        fields = [f for f in fields if f['id'] != 'max-depth']
        fields += [number('min-alt-count', 'Minimum alternate observations', 2, 1, 1000000),
                   choice('min-alt-fraction', 'Minimum alternate allele fraction', '0.2',
                          '0.01:1%|0.05:5%|0.1:10%|0.2:20%|0.3:30%',
                          help='FreeBayes candidate threshold; choose for the assay and ploidy. This is a germline workflow.')]
    return fields


def research_call_outputs(caller):
    return ([artifact('pileup', 'Genotype likelihoods', 'pileup.bcf', False)] if caller == 'bcftools' else []) + [
        artifact('calls', 'Raw calls', 'calls.bcf' if caller == 'bcftools' else 'calls.vcf', False),
        artifact('normalized', 'Normalized unfiltered calls', 'normalized.bcf', False),
        artifact('variants', 'All normalized calls with filter labels', 'variants.vcf.gz'),
        artifact('variants-index', 'All-call VCF index', 'variants.vcf.gz.csi'),
        artifact('pass-variants', 'PASS calls only', 'variants.pass.vcf.gz'),
        artifact('pass-index', 'PASS VCF index', 'variants.pass.vcf.gz.csi'),
        artifact('variant-stats', 'All-call statistics', 'variant-stats.txt'),
        artifact('pass-stats', 'PASS-call statistics', 'variants.pass.stats.txt')]


def research_call_steps(caller, bam='{output:bam}'):
    if caller == 'bcftools':
        steps = base.calling_steps(bam)
    else:
        steps = [execute('call', 'Call germline variants with FreeBayes', 'freebayes',
                          ['-f', '{output:reference}', '-p', '{input:ploidy}', '-m', '{input:min-mapq}',
                           '-q', '{input:min-baseq}', '-C', '{input:min-alt-count}', '-F', '{input:min-alt-fraction}', '--strict-vcf', bam],
                          stdout='calls')] + base.calling_steps(bam)[2:]
    for step in steps:
        if step['id'] == 'filter':
            old = [step[k] for k in sorted((k for k in step if k.startswith('arg.')), key=lambda k: int(k.split('.')[1]))]
            step.update({f'arg.{i}': value for i, value in enumerate([old[0], '-m', '+', *old[1:]])})
    steps += [execute('pass-only', 'Write a separate PASS-only VCF', 'bcftools',
                      ['view', '-f', 'PASS', '-Oz', '-o', '{output:pass-variants}', '{output:variants}'], produces=['pass-variants']),
              execute('pass-index', 'Index PASS calls', 'bcftools', ['index', '--csi', '{output:pass-variants}'], produces=['pass-index']),
              execute('pass-stats', 'Summarize PASS calls', 'bcftools', ['stats', '{output:pass-variants}'], stdout='pass-stats')]
    return steps


def research_workflow(aligner, caller, adapters=True):
    identity = f'cutadapt-{aligner}-{caller}' + ('' if adapters else '-quality-only')
    title = f'Cutadapt + {"BWA-MEM" if aligner == "bwa" else "minimap2"} + {"FreeBayes" if caller == "freebayes" else "BCFtools"}'
    if not adapters:
        title += ' (quality only)'
    description = ('Paired short-read germline SNP/indel workflow. ' +
        ('Adapter sequences must match your library. ' if adapters else 'Quality trimming only; use for adapter-free or previously adapter-trimmed libraries. ') +
        'Duplicates are marked and excluded from calling. Uniform ploidy; separate all-call and PASS VCFs. Reference indexes are built privately.')
    inputs = base.read_fields() + [base.reference_field()] + groups() + [threads(), sort_memory()] + trimming_fields(adapters) + call_fields(caller)
    outputs = [artifact('pair-check', 'Raw read-pair validation', 'read-pairs.json')] + base.reference_outputs()
    outputs += [artifact('raw-qc1', 'Raw read 1 quality profile', 'raw-read1-quality.txt'),
                artifact('raw-qc2', 'Raw read 2 quality profile', 'raw-read2-quality.txt')]
    outputs += trim_outputs() + [artifact('trim-pair-check', 'Trimmed read-pair validation', 'trimmed-read-pairs.json'),
        artifact('trim-qc1', 'Trimmed read 1 quality profile', 'trimmed-read1-quality.txt'),
        artifact('trim-qc2', 'Trimmed read 2 quality profile', 'trimmed-read2-quality.txt')]
    if aligner == 'bwa':
        outputs += bwa_outputs()
    outputs += base.bam_outputs() + [artifact('coverage', 'Per-contig depth and coverage', 'coverage.tsv')] + research_call_outputs(caller)
    steps = [pair_check()] + base.reference_steps() + [
        execute('raw-qc1', 'Profile raw read 1', 'seqtk', ['fqchk', '{input:reads1}'], stdout='raw-qc1'),
        execute('raw-qc2', 'Profile raw read 2', 'seqtk', ['fqchk', '{input:reads2}'], stdout='raw-qc2'),
        cutadapt_step(adapters), pair_check('trim-pairs', '{output:trimmed1}', '{output:trimmed2}', 'trim-pair-check'),
        execute('trim-qc1', 'Profile trimmed read 1', 'seqtk', ['fqchk', '{output:trimmed1}'], stdout='trim-qc1'),
        execute('trim-qc2', 'Profile trimmed read 2', 'seqtk', ['fqchk', '{output:trimmed2}'], stdout='trim-qc2')]
    if aligner == 'bwa':
        steps += [bwa_index()]
    steps += [alignment_step(aligner, stream_sort=True)] + preparation_steps() + [
        execute('coverage', 'Summarize per-contig coverage', 'samtools', ['coverage', '{output:bam}'], stdout='coverage')]
    steps += research_call_steps(caller)
    return workflow(identity, title, description, inputs, outputs, steps)


def fastp_research_workflow(aligner, caller):
    wf = copy.deepcopy(research_workflow(aligner, caller))
    wf['id'] = wf['id'].replace('cutadapt-', 'fastp-', 1)
    wf['name'] = wf['name'].replace('Cutadapt', 'fastp', 1)
    wf['description'] += ' fastp poly-G trimming, read correction and duplicate estimation are disabled; orphan reads are saved but not aligned.'
    old_inputs = {i['id'] for i in trimming_fields()}
    wf['inputs'] = [i for i in wf['inputs'] if i['id'] not in old_inputs] + fastp_fields()
    old_outputs = {o['id'] for o in trim_outputs()}
    wf['outputs'] = [o for o in wf['outputs'] if o['id'] not in old_outputs] + fastp_outputs()
    steps = []
    for s in wf['steps']:
        steps.extend(fastp_steps() if s['id'] == 'trim' else [s])
    wf['steps'] = steps
    return wf


def expanded_workflows(include_freebayes=True, include_fastp=True):
    trimming = []
    for paired, adapters, ident in [(True, True, 'cutadapt-paired'), (False, True, 'cutadapt-single'), (True, False, 'cutadapt-quality-paired')]:
        inputs = base.read_fields() if paired else [field('reads1', 'Reads', filter=base.FASTQ)]
        inputs += [threads()] + trimming_fields(adapters, paired)
        outputs = trim_outputs(paired) + ([artifact('pair-check', 'Input pair validation', 'read-pairs.json')] if paired else [])
        steps = ([pair_check()] if paired else []) + [cutadapt_step(adapters, paired)]
        trimming.append(workflow(ident, 'Cutadapt: ' + ('paired adapters + quality' if paired and adapters else 'single-end adapters + quality' if adapters else 'paired quality only'),
            'Explicit Phred+33 trimming with JSON metrics and rejected short reads. Paired reads are retained or rejected together.', inputs, outputs, steps))
    packs = [('trimming', 'Read trimming', '#229A64', 'Cutadapt adapter and quality trimming with a private, offline Python runtime.', ['python', 'paircheck'], trimming)]
    if include_fastp:
        fp = workflow('paired', 'fastp: paired adapter and quality filtering',
            'Trim known adapters and paired-read overlaps; sliding-window tail trimming with explicit quality/length/N filters. Poly-G trimming and duplicate estimation are disabled. Orphans and failures are retained.',
            base.read_fields() + [threads()] + fastp_fields(),
            [artifact('pair-check', 'Input pair validation', 'read-pairs.json')] + fastp_outputs(),
            [pair_check()] + fastp_steps())
        packs += [('fastp', 'fastp quality control', '#36959F', 'Paired-read preprocessing with an offline HTML report.', ['fastp', 'paircheck'], [fp])]
    bwa = [workflow('index', 'Build BWA index', 'Create an index from a private reference copy.', [base.reference_field()],
                    [artifact('reference', 'Reference copy', 'reference.fa')] + bwa_outputs(), [base.copy_reference(), bwa_index()]),
           workflow('paired-end', 'BWA-MEM paired alignment', 'Align paired short reads, with explicit read groups, streaming directly to BAM.',
                    base.read_fields() + [base.reference_field()] + groups() + [threads()],
                    [artifact('pair-check', 'Read-pair validation', 'read-pairs.json'), artifact('reference', 'Working reference', 'reference.fa', False)] + bwa_outputs() +
                    [artifact('aligned', 'Unsorted alignment BAM', 'alignment.unsorted.bam')],
                    [pair_check(), base.copy_reference(), bwa_index(), alignment_step('bwa', False)])]
    packs += [('bwa', 'BWA alignment', '#486FB0', 'BWA-MEM short-read alignment with explicit sample and library read groups.', ['bwa', 'samtools', 'paircheck'], bwa)]
    callers = ['bcftools'] + (['freebayes'] if include_freebayes else [])
    if include_freebayes:
        freebayes = workflow('call', 'FreeBayes germline variants', 'Call SNPs and indels from a prepared BAM, normalize, soft-filter and index. Sample names come from BAM read groups.',
            [field('alignment', 'Prepared coordinate-sorted BAM', filter='BAM|*.bam'), base.reference_field()] + call_fields('freebayes'),
            base.reference_outputs() + research_call_outputs('freebayes'), base.reference_steps() + research_call_steps('freebayes', '{input:alignment}'))
        packs += [('freebayes', 'FreeBayes variants', '#A05CB0', 'An alternative haplotype-based germline caller.', ['freebayes', 'samtools', 'bcftools'], [freebayes])]
    pipelines = [research_workflow(a, c, adapters) for adapters in (True, False) for a in ('bwa', 'minimap2') for c in callers]
    tools = ['python', 'paircheck', 'seqtk', 'bwa', 'minimap2', 'samtools', 'bcftools'] + (['freebayes'] if include_freebayes else [])
    if include_fastp:
        pipelines += [fastp_research_workflow(a, c) for a in ('bwa', 'minimap2') for c in callers]
        tools += ['fastp']
    packs += [('research-variants', 'Research variants', '#C75D71', 'Paired short-read germline pipelines with trimming, alternative aligners/callers, coverage and indexed VCFs.', tools, pipelines)]
    return packs


def emit_pack(record):
    id, name, color, description, tools, workflows = record
    version = PACK_VERSIONS.get(id, VERSION)
    folder = ROOT / 'packs' / f'{id}-{version}'
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    sections = []
    def section(name, values):
        sections.append('[' + name + ']\n' + '\n'.join(k + '=' + str(v) for k, v in values.items() if k != 'id') + '\n')
    sections.append('[pack]\n' + f'format=2\nid={id}\nversion={version}\nname={name}\nplatform=windows-x86_64\ndescription={description}\ncolor={color}\n')
    versions = dict(bwfastq='0.1.0-experiment', seqtk='1.4-r122', minimap2='2.28-r1209', samtools='1.24', bcftools='1.24', paircheck='1.0.1', bwa='0.7.19-r1273', freebayes='1.3.10', python='3.13.16-Cutadapt-5.2', fastp='1.3.7')
    versions['fastp'] = '1.3.7-reportfix1'
    for tool in tools:
        if tool == 'python':
            runtime = ROOT / 'vendor-expanded/cutadapt/runtime'
            shutil.copytree(runtime, folder / 'runtime/python')
            relative = 'runtime/python/python.exe'
        else:
            source = ROOT / 'baselines/bin' / f'{tool}-cosmo.exe'
            relative = f'bin/{tool}.exe'
            (folder / 'bin').mkdir(exist_ok=True)
            shutil.copy2(source, folder / relative)
        section('tool:' + tool, dict(path=relative, version=versions[tool], sha256=hashlib.sha256((folder / relative).read_bytes()).hexdigest()))
    if 'python' in tools:
        for n, path in enumerate(sorted((folder / 'runtime/python').rglob('*'))):
            if path.is_file() and path.name != 'python.exe':
                section(f'asset:python-{n}', dict(path=path.relative_to(folder).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    if 'fastp' in tools:
        path = folder / 'assets/plotly-1.2.0.min.js'
        path.parent.mkdir(exist_ok=True)
        shutil.copy2(ROOT / 'vendor-expanded/fastp-assets/plotly-1.2.0.min.js', path)
        section('asset:plotly', dict(path=path.relative_to(folder).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for wf in workflows:
        assert len(wf['inputs']) <= 32, wf['id']
        assert len(wf['outputs']) <= 64 and len(wf['steps']) <= 64, wf['id']
        section('workflow:' + wf['id'], dict(name=wf['name'], description=wf['description'], inputs=','.join(x['id'] for x in wf['inputs']), outputs=','.join(x['id'] for x in wf['outputs']), steps=','.join(x['id'] for x in wf['steps'])))
        for kind, plural in [('input', 'inputs'), ('output', 'outputs'), ('step', 'steps')]:
            for entry in wf[plural]:
                section(f'{kind}:{wf["id"]}:{entry["id"]}', entry)
    (folder / 'pack.ini').write_text('\n'.join(sections), encoding='utf-8')
    shutil.copytree(ROOT / 'packs/core-bio-0.2.0/licenses', folder / 'licenses')
    if 'samtools' in tools or 'bcftools' in tools:
        shutil.copytree(ROOT / 'vendor-variant/licenses', folder / 'licenses/variant-tools')
    for tool in tools:
        source = ROOT / 'vendor-expanded' / ('cutadapt' if tool == 'python' else tool) / 'licenses'
        if tool == 'fastp':
            source = ROOT / 'vendor-expanded/fastp-licenses'
        if source.is_dir():
            shutil.copytree(source, folder / 'licenses' / ('cutadapt' if tool == 'python' else tool))
    (folder / 'PACK-README.md').write_text(f'# {name}\n\n{description}\n\nVersion {version}; all processing stays on this computer.\n\n' + '\n'.join('- ' + w['name'] + ': ' + w['description'] for w in workflows) + '\n')
    print(id, len(workflows), 'workflows', sum(len(w['steps']) for w in workflows), 'steps')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--without-freebayes', action='store_true')
    parser.add_argument('--without-fastp', action='store_true')
    args = parser.parse_args()
    base.main()
    for record in expanded_workflows(not args.without_freebayes, not args.without_fastp):
        emit_pack(record)


if __name__ == '__main__':
    main()
