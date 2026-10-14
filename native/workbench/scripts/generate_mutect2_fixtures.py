#!/usr/bin/env python3
"""Create deterministic, openly generated somatic-calling validation data.

The aligned synthetic reads are test inputs, not a sensitivity benchmark or a
replacement for validation with biological truth sets. No donor data are used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def self_checks():
    """Data-only expectations established with genuine pinned GATK 4.7.0.0."""
    records = [dict(chrom='chr1',pos=1000,ref='C',alt='G',filter='PASS'),
               dict(chrom='chr1',pos=2000,ref='T',alt='TAGC',filter='PASS'),
               dict(chrom='chr1',pos=3001,ref='GTTT',alt='G',filter='PASS')]
    cases = []
    for workflow in ('tumor-only','tumor-normal','tumor-only-resources','tumor-normal-resources'):
        paired = 'normal' in workflow
        resources = workflow.endswith('-resources')
        inputs = {'tumor':[{'tumor':'fixture-tumor'}],
                  'reference':[{'reference':'fixture-reference'}],
                  'targets':[{'targets':'fixture-targets'}]}
        params = {'tumor-sample':'TUMOR','memory':1024}
        samples = ['NORMAL','TUMOR'] if paired else ['TUMOR']
        if paired:
            inputs['normal'] = [{'normal':'fixture-normal'}]
            params['normal-sample'] = 'NORMAL'
        if resources:
            inputs['germline-resource'] = [{'germline-resource':'fixture-germline'}]
            inputs['panel-of-normals'] = [{'panel-of-normals':'fixture-pon'}]
        expected = [dict(record) for record in (records[1:] if resources else records)]
        if not paired:
            expected.append(dict(chrom='chr1',pos=4000,ref='T',alt='A',filter='germline' if resources else 'PASS'))
        for record in expected:
            record['genotypes'] = {'NORMAL':'0/0','TUMOR':'0/1'} if paired else {'TUMOR':'0/1'}
        passing = [dict(record) for record in expected if record['filter']=='PASS']
        absent = [dict(chrom='chr1',pos=4500)]
        if paired:
            absent.append(dict(chrom='chr1',pos=4000))
        if resources:
            absent.append(dict(chrom='chr1',pos=1000))
        expect = [dict(output='variants',kind='vcf',records=len(expected),samples=samples,variants=expected,absentVariants=absent),
                  dict(output='pass-variants',kind='vcf',records=len(passing),samples=samples,variants=passing)]
        cases.append(dict(id=workflow+'-somatic-germline-controls',workflow=workflow,params=params,inputs=inputs,expect=expect))
    return dict(schema=1,checks=cases)


def generate(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(5407)
    reference = ''.join(rng.choice('ACGT') for _ in range(5000))
    alternate = {'A': 'C', 'C': 'G', 'G': 'T', 'T': 'A'}
    insertion = 'AGC' if reference[1999] != 'C' else 'AGT'
    deletion = 3000
    while reference[deletion-1] == reference[deletion+2]:
        deletion += 1
    variants = [
        dict(chrom='chr1', pos=1000, ref=reference[999], alt=alternate[reference[999]], kind='snv', tumorFraction=0.3, normalFraction=0.0),
        dict(chrom='chr1', pos=2000, ref=reference[1999], alt=reference[1999]+insertion, kind='insertion', tumorFraction=0.3, normalFraction=0.0),
        dict(chrom='chr1', pos=deletion, ref=reference[deletion-1:deletion+3], alt=reference[deletion-1], kind='deletion', tumorFraction=0.3, normalFraction=0.0),
        dict(chrom='chr1', pos=4000, ref=reference[3999], alt=alternate[reference[3999]], kind='germline', tumorFraction=0.5, normalFraction=0.5),
        dict(chrom='chr1', pos=4500, ref=reference[4499], alt=alternate[reference[4499]], kind='low-quality-noise', tumorFraction=0.02, normalFraction=0.0),
    ]
    (folder/'reference.fa').write_text('>chr1\n'+'\n'.join(reference[i:i+80] for i in range(0,len(reference),80))+'\n', encoding='ascii')
    (folder/'targets.bed').write_text('chr1\t0\t5000\tvalidation\n', encoding='ascii')
    (folder/'empty.bed').write_text('chr1\t0\t200\tno_coverage\n', encoding='ascii')

    def read(start, variant, alt):
        position = variant['pos']
        sequence = reference[start-1:start-1+150]
        qualities = ['I'] * 150
        cigar = '150M'
        reference_length = 150
        if alt and start <= position < start+147:
            at = position-start
            if variant['kind'] == 'insertion':
                left = at+1
                sequence = reference[start-1:position]+insertion+reference[position:position+150-left-3]
                cigar = f'{left}M3I{150-left-3}M'
                reference_length = 147
            elif variant['kind'] == 'deletion':
                left = at+1
                sequence = reference[start-1:position]+reference[position+3:position+3+150-left]
                cigar = f'{left}M3D{150-left}M'
                reference_length = 153
            else:
                sequence = sequence[:at]+variant['alt']+sequence[at+1:]
                if variant['kind'] == 'low-quality-noise':
                    qualities[at] = '#'  # Phred 2, below Mutect2 calling threshold.
        assert len(sequence) == len(qualities) == 150
        return sequence, ''.join(qualities), cigar, reference_length

    samtools = ROOT/'baselines/bin/samtools-linux'
    samtools.chmod(samtools.stat().st_mode | 0o100)
    for sample, fraction_key in [('TUMOR', 'tumorFraction'), ('NORMAL', 'normalFraction')]:
        rg = sample.lower()+'-rg'
        headers = ['@HD\tVN:1.6\tSO:coordinate',
                   '@SQ\tSN:chr1\tLN:5000\tM5:'+hashlib.md5(reference.encode()).hexdigest(),
                   f'@RG\tID:{rg}\tSM:{sample}\tLB:{sample.lower()}\tPL:ILLUMINA\tPU:synthetic-unit']
        rows = []
        for locus, variant in enumerate(variants):
            for pair in range(120):
                # Unique starts, both pair orientations, both strands and a
                # spread of read positions prevent artificial strand/end bias.
                start = variant['pos']-180+(pair*17)%70
                starts = [start, start+90]
                alt = pair % 100 < round(100*variant[fraction_key])
                # Exact fractions across 120 fragments for the truth sites.
                if variant['kind'] != 'low-quality-noise':
                    alt = pair % 10 < round(10*variant[fraction_key])
                fragments = [read(value,variant,alt) for value in starts]
                span = starts[1]+fragments[1][3]-starts[0]
                flags = [99,147] if pair % 2 == 0 else [163,83]
                for mate in (0,1):
                    seq,qual,cigar,_ = fragments[mate]
                    fields = [f'{sample.lower()}-{locus}-{pair:03d}',str(flags[mate]),'chr1',str(starts[mate]),'60',cigar,'=',str(starts[1-mate]),str(span if mate == 0 else -span),seq,qual,'RG:Z:'+rg]
                    rows.append((starts[mate], fields[0], mate, '\t'.join(fields)))
        rows.sort()
        path = folder/(sample.lower()+'.sam')
        path.write_text('\n'.join(headers+[row[3] for row in rows])+'\n', encoding='ascii')
        subprocess.run([str(samtools),'view','--no-PG','-b','-o',str(folder/(sample.lower()+'.bam')),str(path)],check=True,capture_output=True)
        # The user-facing pack needs only BAM inputs; generator SAM is a
        # reproducible intermediate and does not enlarge its pinned inventory.
        path.unlink()

    header = ['##fileformat=VCFv4.2','##contig=<ID=chr1,length=5000>',
              '##INFO=<ID=AF,Number=A,Type=Float,Description="Synthetic population allele frequency">',
              '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO']
    germline = variants[3]
    (folder/'germline.vcf').write_text('\n'.join(header+[f"chr1\t4000\t.\t{germline['ref']}\t{germline['alt']}\t.\tPASS\tAF=0.1"])+ '\n', encoding='ascii')
    # Deliberately put the truth SNV in a synthetic PoN. The resources tests
    # must then suppress it, proving the supplied PoN actually affects calls.
    snv = variants[0]
    (folder/'pon.vcf').write_text('\n'.join(header+[f"chr1\t1000\t.\t{snv['ref']}\t{snv['alt']}\t.\tPASS\t."])+ '\n', encoding='ascii')
    truth = dict(schema=1,seed=5407,referenceMd5=hashlib.md5(reference.encode()).hexdigest(),
                 samples=['NORMAL','TUMOR'],fragmentsPerLocusPerSample=120,readLength=150,
                 explanation='Deterministic synthetic aligned pairs; nominal fractions refer to fragments. Somatic SNV/insertion/deletion, shared germline SNV and Phred-2 alternate noise. Synthetic PoN deliberately lists the truth SNV to test resource-driven suppression.',
                 variants=variants)
    (folder/'truth.json').write_text(json.dumps(truth,indent=2)+'\n')
    return truth


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.folder),indent=2))
