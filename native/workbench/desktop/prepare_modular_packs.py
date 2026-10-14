#!/usr/bin/env python3
"""Build self-contained format-2 tool packs from pinned executable builds."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.4.0'
FASTQ = 'FASTQ reads|*.fastq;*.fq;*.fastq.gz;*.fq.gz|All files|*.*'
FASTA = 'Uncompressed FASTA reference|*.fa;*.fasta;*.fna|All files|*.*'
BAM = 'Alignments|*.bam;*.sam|All files|*.*'
VCF = 'Variants|*.vcf;*.vcf.gz;*.bcf|All files|*.*'


def field(id, label, type='file', **options):
    return dict(id=id, label=label, type=type, required='true', **options)


def number(id, label, default, minimum=0, maximum=100000, **options):
    return field(id, label, 'integer', default=str(default), min=str(minimum), max=str(maximum), **options)


def artifact(id, label, path, final=True, nonempty=True):
    return dict(id=id, label=label, path=path, final=str(final).lower(), nonempty=str(nonempty).lower())


def execute(id, label, tool, args, stdout=None, produces=()):
    result = dict(id=id, label=label, kind='exec', tool=tool)
    if stdout:
        result['stdout'] = stdout
    if produces:
        result['produces'] = ','.join(produces)
    result.update({f'arg.{n}': str(arg) for n, arg in enumerate(args)})
    return result


def copy_reference():
    return dict(id='copy-reference', label='Stage a private reference copy', kind='copy', source='{input:reference}', destination='reference')


def reference_outputs():
    return [artifact('reference', 'Working reference', 'reference.fa', False),
            artifact('reference-index', 'Reference index', 'reference.fa.fai', False)]


def reference_steps():
    return [copy_reference(), execute('index-reference', 'Index reference', 'samtools',
        ['faidx', '{output:reference}'], produces=['reference-index'])]


def workflow(id, name, description, inputs, outputs, steps):
    return dict(id=id, name=name, description=description, inputs=inputs, outputs=outputs, steps=steps)


def reference_field():
    return field('reference', 'Reference genome', filter=FASTA,
        help='Uncompressed FASTA. Workflows that build an index copy this file into the run folder first.')


def threads_field():
    return number('threads', 'Alignment threads', 2, 1, 16,
        help='Minimap2 mapping workers. BAM/VCF preparation uses one thread in this portable release; sort memory is 256 MiB.')


def read_fields():
    return [field('reads1', 'Read 1 (forward)', filter=FASTQ), field('reads2', 'Read 2 (reverse)', filter=FASTQ, **{'different-from':'reads1'},
        help='Use the matching mate file, in the same read order. Plain or gzip FASTQ accepted.')]


def pair_check():
    return execute('check-pairs', 'Validate paired FASTQ records', 'paircheck',
        ['--reads1', '{input:reads1}', '--reads2', '{input:reads2}'], stdout='pair-check')


def calling_fields():
    return [field('ploidy', 'Assumed ploidy', 'choice', default='2', choices='1:Haploid (1)|2:Diploid (2)',
            help='Applies to every contig, including mitochondria. Confirm from sample metadata; this is not inferred from the reads.'),
        number('min-mapq', 'Minimum mapping quality', 20, 0, 60),
        number('min-baseq', 'Minimum base quality', 20, 0, 93),
        number('max-depth', 'Maximum pileup depth per file', 1000, 1, 1000000,
            help='Depth above this cap may be subsampled by BCFtools.'),
        number('min-qual', 'Variant quality threshold', 20, 0, 100000),
        number('min-depth', 'Sample depth threshold', 5, 0, 1000000,
            help='Calls below the quality or sample-depth threshold are labelled LowQual, not deleted.')]


def calling_outputs():
    return [artifact('pileup', 'Genotype likelihoods', 'pileup.bcf', False),
        artifact('calls', 'Raw variant calls', 'calls.bcf', False),
        artifact('normalized', 'Normalized calls', 'normalized.bcf', False),
        artifact('variants', 'Filtered variants (VCF.gz)', 'variants.vcf.gz'),
        artifact('variants-index', 'Variant index (CSI)', 'variants.vcf.gz.csi'),
        artifact('variant-stats', 'Variant summary', 'variant-stats.txt')]


def calling_steps(bam='{output:bam}'):
    return [execute('pileup', 'Calculate genotype likelihoods', 'bcftools',
        ['mpileup', '-f', '{output:reference}', '-a', 'FORMAT/DP,FORMAT/AD', '-q', '{input:min-mapq}',
         '-Q', '{input:min-baseq}', '-d', '{input:max-depth}', '-Ob', '-o', '{output:pileup}', bam], produces=['pileup']),
        execute('call', 'Call SNPs and short indels', 'bcftools',
            ['call', '-m', '-v', '--ploidy', '{input:ploidy}', '-Ob', '-o', '{output:calls}', '{output:pileup}'], produces=['calls']),
        execute('normalize', 'Normalize alleles against the reference', 'bcftools',
            ['norm', '-f', '{output:reference}', '-m', '-any', '-Ob', '-o', '{output:normalized}', '{output:calls}'], produces=['normalized']),
        execute('filter', 'Label calls below the selected thresholds', 'bcftools',
            ['filter', '-s', 'LowQual', '-e', 'QUAL<{input:min-qual} || FORMAT/DP<{input:min-depth}',
             '-Oz', '-o', '{output:variants}', '{output:normalized}'], produces=['variants']),
        execute('index-variants', 'Index the VCF', 'bcftools', ['index', '--csi', '{output:variants}'], produces=['variants-index']),
        execute('variant-stats', 'Summarize variants', 'bcftools', ['stats', '{output:variants}'], stdout='variant-stats')]


def bam_outputs():
    return [artifact('names', 'Name-sorted alignments', 'alignment.names.bam', False),
        artifact('fixed', 'Mate-corrected alignments', 'alignment.fixmate.bam', False),
        artifact('coordinates', 'Coordinate-sorted alignments', 'alignment.sorted.bam', False),
        artifact('bam', 'Sorted, duplicate-marked BAM', 'alignment.marked.bam'),
        artifact('bam-index', 'BAM index (CSI)', 'alignment.marked.bam.csi'),
        artifact('duplicate-stats', 'Duplicate-marking summary', 'duplicates.txt'),
        artifact('flagstat', 'Alignment flag summary', 'flagstat.txt'),
        artifact('alignment-stats', 'Alignment statistics', 'alignment-stats.txt')]


def bam_steps(alignment='{output:sam}'):
    return [execute('name-sort', 'Group read mates by name', 'samtools',
        ['sort', '-n', '-m', '256M', '-T', '{run}/name-sort', '-o', '{output:names}', alignment], produces=['names']),
        execute('fixmate', 'Fill mate coordinates and scores', 'samtools',
            ['fixmate', '-m', '{output:names}', '{output:fixed}'], produces=['fixed']),
        execute('coordinate-sort', 'Sort by genomic position', 'samtools',
            ['sort', '-m', '256M', '-T', '{run}/coordinate-sort', '-o', '{output:coordinates}', '{output:fixed}'], produces=['coordinates']),
        execute('mark-duplicates', 'Mark duplicate fragments', 'samtools',
            ['markdup', '-s', '-T', '{run}/markdup', '-f', '{output:duplicate-stats}', '{output:coordinates}', '{output:bam}'], produces=['duplicate-stats','bam']),
        execute('index-bam', 'Index the BAM', 'samtools', ['index', '-c', '{output:bam}'], produces=['bam-index']),
        execute('flagstat', 'Summarize alignment flags', 'samtools', ['flagstat', '{output:bam}'], stdout='flagstat'),
        execute('alignment-stats', 'Summarize alignment statistics', 'samtools', ['stats', '{output:bam}'], stdout='alignment-stats')]


def all_workflows():
    reads = [workflow('statistics', 'FASTQ statistics', 'Count reads, bases, GC and quality totals in an uncompressed FASTQ.',
        [field('reads','Reads',filter='Uncompressed FASTQ|*.fastq;*.fq')], [artifact('statistics','FASTQ statistics','reads.stats.json')],
        [execute('statistics','Calculate FASTQ statistics','bwfastq',['stats','--input','{input:reads}','--output','-','--threads','1'],stdout='statistics')]),
        workflow('quality-profile','Quality profile','Summarize base composition and quality by read position. Supports gzip FASTQ.',
        [field('reads','Reads',filter=FASTQ)],[artifact('quality','Quality profile','quality-profile.txt')],
        [execute('quality','Profile read quality','seqtk',['fqchk','{input:reads}'],stdout='quality')]),
        workflow('reverse-complement','Reverse complement','Reverse-complement sequence and reverse the matching quality strings.',
        [field('reads','Reads',filter=FASTQ)],[artifact('reversed','Reverse-complemented reads','reverse-complement.fastq')],
        [execute('reverse','Reverse-complement reads','seqtk',['seq','-r','{input:reads}'],stdout='reversed')])]
    reads.append(workflow('check-pairs','Validate read pairs','Check FASTQ structure, qualities, read counts and mate names before alignment. Supports plain or gzip FASTQ.',
        read_fields(),[artifact('pair-check','Read-pair validation','read-pairs.json')],[pair_check()]))
    align=[]
    for paired in (False, True):
        ins=read_fields() if paired else [field('reads1','Reads',filter=FASTQ)]
        args=['-a','-x','sr','-t','{input:threads}','-R',r'@RG\tID:{input:sample}\tSM:{input:sample}\tLB:library1\tPL:ILLUMINA','{input:reference}','{input:reads1}']
        if paired: args+=['{input:reads2}']
        align.append(workflow('paired-end' if paired else 'single-end','Paired-end alignment' if paired else 'Single-end alignment',
            'Align short reads with minimap2, including the sample read group. The paired workflow consumes both mates together.',ins+[reference_field(),field('sample','Sample name','text',default='sample',constraint='identifier'),threads_field()],
            ([artifact('pair-check','Read-pair validation','read-pairs.json')] if paired else [])+[artifact('sam','Alignment SAM','alignment.sam')],
            ([pair_check()] if paired else [])+[execute('align','Align reads','minimap2',args,stdout='sam')]))
    bam=[workflow('prepare','Prepare paired alignments','Name-sort, fix mates, coordinate-sort, mark duplicates, index and summarize. Duplicates are retained.',
            [field('alignment','Paired alignments',filter=BAM),threads_field()],bam_outputs(),bam_steps('{input:alignment}')),
        workflow('sort','Coordinate sort','Sort a SAM or BAM by reference position.',[field('alignment','Alignments',filter=BAM),threads_field()],
            [artifact('sorted','Sorted BAM','sorted.bam')],[execute('sort','Sort alignments','samtools',['sort','-m','256M','-T','{run}/sort','-o','{output:sorted}','{input:alignment}'],produces=['sorted'])]),
        workflow('index','Index a BAM','Create an index beside a private BAM copy; the selected BAM is unchanged.',[field('alignment','Coordinate-sorted BAM',filter='BAM|*.bam')],
            [artifact('alignment','BAM copy','alignment.bam'),artifact('index','BAM index (CSI)','alignment.bam.csi')],
            [dict(id='copy',label='Copy BAM into the run folder',kind='copy',source='{input:alignment}',destination='alignment'),
             execute('index','Index BAM','samtools',['index','-c','{output:alignment}'],produces=['index'])]),
        workflow('flagstat','Alignment flag summary','Count mapped, paired and duplicate read flags.',[field('alignment','Alignments',filter=BAM)],
            [artifact('statistics','Alignment summary','flagstat.txt')],[execute('flagstat','Summarize flags','samtools',['flagstat','{input:alignment}'],stdout='statistics')]),
        workflow('merge','Merge aligned lanes','Merge coordinate-sorted BAMs with the same reference dictionary. Review read groups and sample identities first.',
            [field('alignments','BAM files','files',filter='BAM files|*.bam',help='Select multiple coordinate-sorted BAMs. Each path is passed as a separate argument.'),threads_field()],
            [artifact('merged','Merged BAM','merged.bam')],[execute('merge','Merge BAM files','samtools',['merge','-o','{output:merged}','{inputs:alignments}'],produces=['merged'])])]
    variants=[workflow('call','Call variants from a BAM','Sample identities come from BAM read groups. Selected ploidy applies to all contigs and samples; LowQual is a site-level filter.',
        [field('alignment','Prepared BAM',filter='BAM|*.bam'),reference_field()]+calling_fields(), reference_outputs()+calling_outputs(),reference_steps()+calling_steps('{input:alignment}')),
        workflow('call-bcf','Call from genotype likelihoods','Call variants from BCFtools mpileup output.',
        [field('likelihoods','Genotype likelihoods',filter=VCF),calling_fields()[0]],
        [artifact('calls','Variant calls','calls.bcf')],[execute('call','Call variants','bcftools',['call','-m','-v','--ploidy','{input:ploidy}','-Ob','-o','{output:calls}','{input:likelihoods}'],produces=['calls'])]),
        workflow('normalize','Normalize variants','Left-align alleles and split multiallelic records against a private reference copy.',
        [field('variants','Variants',filter=VCF),reference_field()],reference_outputs()+[artifact('normalized','Normalized variants','normalized.vcf.gz')],
        reference_steps()+[execute('normalize','Normalize alleles','bcftools',['norm','-f','{output:reference}','-m','-any','-Oz','-o','{output:normalized}','{input:variants}'],produces=['normalized'])]),
        workflow('filter','Label low-quality calls','Retain all calls, marking those below quality or FORMAT/DP thresholds as LowQual.',
        [field('variants','Variants',filter=VCF)]+calling_fields()[-2:],[artifact('filtered','Filtered variants','filtered.vcf.gz')],
        [execute('filter','Apply soft filters','bcftools',['filter','-s','LowQual','-e','QUAL<{input:min-qual} || FORMAT/DP<{input:min-depth}','-Oz','-o','{output:filtered}','{input:variants}'],produces=['filtered'])]),
        workflow('statistics','Variant statistics','Summarize an existing VCF or BCF.',[field('variants','Variants',filter=VCF)],
        [artifact('statistics','Variant statistics','variant-stats.txt')],[execute('statistics','Summarize variants','bcftools',['stats','{input:variants}'],stdout='statistics')])]
    bam += [workflow('name-sort','Name sort','Group mates by read name before fixmate.',
        [field('alignment','Alignments',filter=BAM),threads_field()],
        [artifact('sorted','Name-sorted BAM','namesorted.bam')],
        [execute('sort','Sort by read name','samtools',['sort','-n','-m','256M','-T','{run}/name-sort','-o','{output:sorted}','{input:alignment}'],produces=['sorted'])]),
        workflow('fixmate','Fix mate information','Requires name-sorted or name-collated alignments. Adds mate information and scores for duplicate marking.',
        [field('alignment','Name-grouped alignments',filter=BAM),threads_field()],
        [artifact('fixed','Mate-corrected BAM','fixmate.bam')],
        [execute('fixmate','Fix mate information','samtools',['fixmate','-m','{input:alignment}','{output:fixed}'],produces=['fixed'])]),
        workflow('mark-duplicates','Mark duplicates','Requires coordinate-sorted BAM already processed with fixmate -m. Duplicates are flagged and retained.',
        [field('alignment','Prepared coordinate-sorted BAM',filter='BAM|*.bam'),threads_field()],
        [artifact('marked','Duplicate-marked BAM','marked.bam'),artifact('duplicates','Duplicate statistics','duplicates.txt')],
        [execute('mark','Mark duplicate fragments','samtools',['markdup','-s','-T','{run}/markdup','-f','{output:duplicates}','{input:alignment}','{output:marked}'],produces=['marked','duplicates'])]),
        workflow('statistics','Alignment statistics','Detailed read-length, insert-size and alignment statistics.',
        [field('alignment','Alignments',filter=BAM)],[artifact('statistics','Alignment statistics','alignment-stats.txt')],
        [execute('statistics','Summarize alignments','samtools',['stats','{input:alignment}'],stdout='statistics')]),
        workflow('reference-index','Index a reference','Create an index beside a private reference copy; the selected reference is unchanged.',
        [reference_field()],[artifact('reference','Reference copy','reference.fa'),artifact('reference-index','FASTA index','reference.fa.fai')],reference_steps())]
    variants += [workflow('pileup','Calculate genotype likelihoods','Create BCF input for variant calling from a prepared single-sample BAM.',
        [field('alignment','Prepared BAM',filter='BAM|*.bam'),reference_field()]+calling_fields()[1:4],
        reference_outputs()+[artifact('pileup','Genotype likelihoods','pileup.bcf')],reference_steps()+[calling_steps('{input:alignment}')[0]]),
        workflow('index','Index a compressed VCF','Create an index beside a private copy of a sorted, BGZF-compressed VCF.',
        [field('variants','BGZF-compressed VCF',filter='Compressed VCF|*.vcf.gz')],
        [artifact('variants','VCF copy','variants.vcf.gz'),artifact('index','VCF index','variants.vcf.gz.csi')],
        [dict(id='copy',label='Copy VCF into the run folder',kind='copy',source='{input:variants}',destination='variants'),
         execute('index','Index variants','bcftools',['index','--csi','{output:variants}'],produces=['index'])])]
    pipeline_inputs=read_fields()+[reference_field(),field('sample','Sample name','text',default='sample',constraint='identifier',help='Letters, numbers, dots, underscores and hyphens; at most 64 characters.'),threads_field()]+calling_fields()
    pipeline_outputs=[artifact('pair-check','Read-pair validation','read-pairs.json')]+reference_outputs()+[artifact('qc1','Read 1 quality profile','read1-quality.txt'),artifact('qc2','Read 2 quality profile','read2-quality.txt'),artifact('sam','Raw alignment','alignment.sam',False)]+bam_outputs()+calling_outputs()
    pipeline_steps=[pair_check()]+reference_steps()+[
        execute('qc1','Profile read 1 quality','seqtk',['fqchk','{input:reads1}'],stdout='qc1'),
        execute('qc2','Profile read 2 quality','seqtk',['fqchk','{input:reads2}'],stdout='qc2'),
        execute('align','Align read pairs','minimap2',['-a','-x','sr','-t','{input:threads}','-R',r'@RG\tID:{input:sample}\tSM:{input:sample}\tLB:library1\tPL:ILLUMINA','{output:reference}','{input:reads1}','{input:reads2}'],stdout='sam')]+bam_steps()+calling_steps()
    pipeline=[workflow('paired-variants','Paired reads to variants','A complete small-variant teaching workflow. Raw reads are not trimmed; duplicates are marked and retained. Ploidy applies uniformly, including mitochondrial contigs.',pipeline_inputs,pipeline_outputs,pipeline_steps)]
    # HTSlib recursive-condition mutexes are not supported by Cosmopolitan 3.3.10.
    # Keep SAMtools on its validated single-thread path; only minimap2 exposes threads.
    for wf in bam:
        wf['inputs'] = [i for i in wf['inputs'] if i['id'] != 'threads']
    return [('reads','Read quality','#2B8A83','Inspect and transform FASTQ reads.',['bwfastq','seqtk','paircheck'],reads),
        ('align','Read alignment','#4D78C7','Map short reads to a reference genome.',['minimap2','paircheck'],align),
        ('bam','Alignment files','#C2853B','Prepare, sort, merge and inspect BAM files.',['samtools'],bam),
        ('variants','Variant tools','#966AB7','Call, normalize, filter and inspect small variants.',['samtools','bcftools'],variants),
        ('variant-pipeline','Variant pipeline','#CF6D79','From paired reads to an indexed VCF and a reproducible run report.',['seqtk','minimap2','samtools','bcftools','paircheck'],pipeline)]


def main():
    source_pack=ROOT/'packs/core-bio-0.2.0'
    tool_files={k:ROOT/'baselines/bin'/f'{k}-cosmo.exe' for k in ['seqtk','minimap2','samtools','bcftools','paircheck']}
    tool_files['bwfastq']=source_pack/'bin/bwfastq.exe'
    versions=dict(bwfastq='0.1.0-experiment',seqtk='1.4-r122',minimap2='2.28-r1209',samtools='1.24',bcftools='1.24',paircheck='1.0.1')
    for id,name,color,description,tools,workflows in all_workflows():
        folder=ROOT/'packs'/f'{id}-{VERSION}'
        if folder.exists(): shutil.rmtree(folder)
        (folder/'bin').mkdir(parents=True)
        sections=[]
        def section(name,values):
            sections.append('['+name+']\n'+'\n'.join(k+'='+str(v) for k,v in values.items() if k!='id')+'\n')
        sections.append('[pack]\n'+f'format=2\nid={id}\nversion={VERSION}\nname={name}\nplatform=windows-x86_64\ndescription={description}\ncolor={color}\n')
        for tool in tools:
            source=tool_files[tool]
            if not source.is_file(): raise SystemExit(f'Build required tool first: {source}')
            shutil.copy2(source,folder/'bin'/f'{tool}.exe')
            section('tool:'+tool,dict(path=f'bin/{tool}.exe',version=versions[tool],sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        for wf in workflows:
            section('workflow:'+wf['id'],dict(name=wf['name'],description=wf['description'],inputs=','.join(x['id'] for x in wf['inputs']),outputs=','.join(x['id'] for x in wf['outputs']),steps=','.join(x['id'] for x in wf['steps'])))
            for kind,plural in [('input','inputs'),('output','outputs'),('step','steps')]:
                for record in wf[plural]: section(f'{kind}:{wf["id"]}:{record["id"]}',record)
        (folder/'pack.ini').write_text('\n'.join(sections),encoding='utf-8')
        shutil.copytree(source_pack/'licenses',folder/'licenses')
        additional=ROOT/'vendor-variant/licenses'
        if any(t in tools for t in ('samtools','bcftools')):
            if not additional.is_dir(): raise SystemExit('Variant licenses are missing')
            shutil.copytree(additional,folder/'licenses/variant-tools')
        (folder/'PACK-README.md').write_text(f'# {name}\n\n{description}\n\nVersion {VERSION}. This is a self-contained format-2 pack. Its workflows, fields, ordered steps and output paths are defined in pack.ini; no application code is needed to add a workflow.\n\n'+ '\n'.join('- '+w['name']+': '+w['description'] for w in workflows)+'\n')
        print(id,len(workflows),'workflows',sum(len(w['steps']) for w in workflows),'steps')


if __name__=='__main__':main()
