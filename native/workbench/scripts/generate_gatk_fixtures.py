#!/usr/bin/env python3
"""Generate public synthetic GATK germline controls, without a native tool.

These tiny diploid, Illumina-style alignments are known-answer installation
controls, not an accuracy benchmark. BAM encoding uses the published BAM/BGZF
layout; no scientific analysis or output is simulated by this generator.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import struct
import zlib

SEED = 470041
REFERENCE_LENGTH = 5000
READ_LENGTH = 150
ALT = {'A': 'C', 'C': 'G', 'G': 'T', 'T': 'A'}


def reference_sequence():
    rng = random.Random(SEED)
    return ''.join(rng.choice('ACGT') for _ in range(REFERENCE_LENGTH))


def _bgzf(data):
    blocks = []
    for offset in range(0, len(data), 60000):
        chunk = data[offset:offset + 60000]
        compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
        compressed = compressor.compress(chunk) + compressor.flush()
        length = 18 + len(compressed) + 8
        blocks.append(b'\x1f\x8b\x08\x04\0\0\0\0\0\xff' +
                      struct.pack('<H2sHH', 6, b'BC', 2, length - 1) + compressed +
                      struct.pack('<II', zlib.crc32(chunk), len(chunk)))
    # Required BGZF EOF marker, also a valid empty gzip member.
    blocks.append(bytes.fromhex('1f8b08040000000000ff0600424302001b0003000000000000000000'))
    return b''.join(blocks)


def write_bam(path, reference, sample, records):
    """Write coordinate-sorted, single-contig BAM from generated records."""
    group = sample.lower() + '-rg'
    header = ('@HD\tVN:1.6\tSO:coordinate\n@SQ\tSN:chr1\tLN:' + str(len(reference)) +
              '\tM5:' + hashlib.md5(reference.encode()).hexdigest() +
              '\n@RG\tID:' + group + '\tSM:' + sample + '\tLB:synthetic-library' +
              '\tPL:ILLUMINA\tPU:synthetic-unit\n').encode('ascii')
    payload = bytearray(b'BAM\1' + struct.pack('<i', len(header)) + header +
                        struct.pack('<i', 1) + struct.pack('<i', 5) + b'chr1\0' +
                        struct.pack('<i', len(reference)))
    base_codes = {base: value for value, base in enumerate('=ACMGRSVTWYHKDBN')}
    for record in sorted(records, key=lambda r: (r['start'], r['name'], r['flag'])):
        name = record['name'].encode('ascii') + b'\0'
        sequence = record['sequence']
        encoded = bytearray()
        for index in range(0, len(sequence), 2):
            encoded.append((base_codes[sequence[index]] << 4) |
                           (base_codes[sequence[index + 1]] if index + 1 < len(sequence) else 0))
        # Every synthetic read is wholly within the first 16-kb BAM bin.
        core = struct.pack('<iiIIiiii', 0, record['start'] - 1,
                           (4681 << 16) | (60 << 8) | len(name),
                           (record['flag'] << 16) | 1, len(sequence), 0,
                           record['mate_start'] - 1, record['tlen'])
        body = (core + name + struct.pack('<I', len(sequence) << 4) + encoded +
                bytes(record.get('quality', [40] * len(sequence))) +
                b'RGZ' + group.encode('ascii') + b'\0')
        payload += struct.pack('<i', len(body)) + body
    Path(path).write_bytes(_bgzf(bytes(payload)))


def _pair(reference, name, start, variants=(), quality=40):
    result = []
    for mate, position in enumerate((start, start + 90)):
        sequence = list(reference[position - 1:position - 1 + READ_LENGTH])
        for coordinate, alternative in variants:
            if position <= coordinate < position + READ_LENGTH:
                sequence[coordinate - position] = alternative
        result.append(dict(name=name, start=position, mate_start=start + (90 if mate == 0 else 0),
                           flag=99 if mate == 0 else 147, tlen=240 if mate == 0 else -240,
                           sequence=''.join(sequence), quality=[quality] * READ_LENGTH))
    return result


def _vcf_header(reference, samples=(), gvcf=False):
    lines = ['##fileformat=VCFv4.2', f'##contig=<ID=chr1,length={len(reference)}>',
             '##FILTER=<ID=PASS,Description="All filters passed">',
             '##INFO=<ID=AC,Number=A,Type=Integer,Description="Alternate allele count">',
             '##INFO=<ID=AF,Number=A,Type=Float,Description="Alternate allele frequency">',
             '##INFO=<ID=AN,Number=1,Type=Integer,Description="Called allele count">',
             '##INFO=<ID=DP,Number=1,Type=Integer,Description="Read depth">',
             '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
             '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">',
             '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">',
             '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">',
             '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Phred genotype likelihoods">']
    if gvcf:
        lines += ['##ALT=<ID=NON_REF,Description="Represents any possible alternative allele at this location">',
                  '##INFO=<ID=END,Number=1,Type=Integer,Description="End position of reference block">',
                  '##FORMAT=<ID=MIN_DP,Number=1,Type=Integer,Description="Minimum depth in reference block">',
                  '##GVCFBlock0-100=minGQ=0(inclusive),maxGQ=100(exclusive)']
    lines += ['#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO' +
              ('\tFORMAT\t' + '\t'.join(samples) if samples else '')]
    return lines


def generate(folder, samtools=None):
    """Write deterministic fixtures. ``samtools`` is accepted but not required."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    reference = reference_sequence()
    (folder / 'reference.fa').write_text('>chr1\n' + '\n'.join(reference[i:i + 80] for i in range(0, len(reference), 80)) + '\n', encoding='ascii')
    (folder / 'targets.bed').write_text('chr1\t0\t5000\n', encoding='ascii')
    (folder / 'empty-targets.bed').write_text('chr1\t0\t200\n', encoding='ascii')
    truth_variants = [dict(chrom='chr1', pos=position, ref=reference[position - 1],
                           alt=ALT[reference[position - 1]],
                           genotypes={'SAMPLE_A': '0/1' if position == 1000 else '0/0',
                                      'SAMPLE_B': '1/1' if position == 1000 else '0/1'})
                      for position in (1000, 2000)]
    for sample, leaf in (('SAMPLE_A', 'sample-a'), ('SAMPLE_B', 'sample-b')):
        records = []
        for variant in truth_variants:
            genotype = variant['genotypes'][sample]
            for number in range(48):
                alternate = genotype == '1/1' or genotype == '0/1' and number % 2 == 0
                records += _pair(reference, f'{leaf}-{variant["pos"]}-{number:03d}',
                                 variant['pos'] - 125 + number,
                                 [(variant['pos'], variant['alt'])] if alternate else [])
        write_bam(folder / (leaf + '.bam'), reference, sample, records)

    duplicates = []
    for name, start, quality in [('original-a', 400, 40), ('copy-a-one', 400, 25),
                                  ('copy-a-two', 400, 20), ('original-b', 800, 40),
                                  ('original-c', 1200, 40)]:
        duplicates += _pair(reference, name, start, quality=quality)
    write_bam(folder / 'duplicates.bam', reference, 'SAMPLE_A', duplicates)

    recalibration = []
    for number in range(200):
        records = _pair(reference, f'recalibrate-{number:03d}', 300 + number * 20)
        for mate, record in enumerate(records):
            # A distributed sequencing-error covariate, not another polymorphism:
            # 10% of reads have a mismatch at one sequencing cycle.
            if (number + mate) % 10 == 0:
                at = 19 if mate == 0 else READ_LENGTH - 20
                sequence = list(record['sequence'])
                sequence[at] = ALT[sequence[at]]
                record['sequence'] = ''.join(sequence)
        recalibration += records
    write_bam(folder / 'recalibration.bam', reference, 'SAMPLE_A', recalibration)

    known = _vcf_header(reference)
    for variant in truth_variants:
        known.append(f'chr1\t{variant["pos"]}\t.\t{variant["ref"]}\t{variant["alt"]}\t100\tPASS\tAC=1;AF=0.5;AN=2')
    (folder / 'known-sites.vcf').write_text('\n'.join(known) + '\n', encoding='ascii')

    for sample, leaf in (('SAMPLE_A', 'sample-a'), ('SAMPLE_B', 'sample-b')):
        lines = _vcf_header(reference, [sample], gvcf=True)
        for start, end in ((1, 999), (1000, 1000), (1001, 1999), (2000, 2000), (2001, 5000)):
            variant = next((v for v in truth_variants if v['pos'] == start), None)
            genotype = variant['genotypes'][sample] if variant else '0/0'
            if genotype == '0/0':
                lines.append(f'chr1\t{start}\t.\t{reference[start - 1]}\t<NON_REF>\t.\t.\tEND={end}\tGT:DP:GQ:MIN_DP:PL\t0/0:40:99:40:0,120,1200')
            else:
                evidence = '20,20,0:40:99:600,0,600,900,900,1200' if genotype == '0/1' else '0,40,0:40:99:1200,120,0,1500,1500,1800'
                lines.append(f'chr1\t{start}\t.\t{variant["ref"]}\t{variant["alt"]},<NON_REF>\t600\t.\tDP=40\tGT:AD:DP:GQ:PL\t{genotype}:{evidence}')
        (folder / (leaf + '.g.vcf')).write_text('\n'.join(lines) + '\n', encoding='ascii')

    variants = _vcf_header(reference, ['SAMPLE_A'])
    for pos, quality, alt in ((1000, 60, truth_variants[0]['alt']),
                              (2000, 10, truth_variants[1]['alt']),
                              (3000, 50, reference[2999] + 'AC')):
        variants.append(f'chr1\t{pos}\t.\t{reference[pos - 1]}\t{alt}\t{quality}\tPASS\tAC=1;AF=0.5;AN=2;DP=40\tGT:AD:DP:GQ:PL\t0/1:20,20:40:99:600,0,600')
    (folder / 'variants.vcf').write_text('\n'.join(variants) + '\n', encoding='ascii')
    truth = dict(schema=1, seed=SEED, referenceMd5=hashlib.md5(reference.encode()).hexdigest(),
                 referenceLength=len(reference), samples=['SAMPLE_A', 'SAMPLE_B'],
                 readLength=READ_LENGTH, callingReadsPerSample=192,
                 duplicateFixture=dict(reads=10, duplicateReads=4, readPairsExamined=5, readPairDuplicates=2),
                 recalibrationFixture=dict(reads=400, bases=60000, inputQuality=40, sequencingErrors=40),
                 variants=truth_variants,
                 explanation='Public synthetic diploid controls. Manually specified gVCF likelihoods are independent inputs for merging/genotyping, not HaplotypeCaller outputs. No donor data or inferred biological accuracy.')
    (folder / 'truth.json').write_text(json.dumps(truth, indent=2) + '\n', encoding='ascii')
    return truth


def self_checks():
    """Bounded known-answer assertions executed by the installed native runner."""
    reference = reference_sequence()
    def inputs(**items):
        return {key: [{key: 'fixture-' + value}] for key, value in items.items()}
    def variant(pos, sample='SAMPLE_A', genotype='0/1', **extra):
        return dict(chrom='chr1', pos=pos, ref=reference[pos - 1], alt=ALT[reference[pos - 1]],
                    genotypes={sample: genotype}, **extra)
    checks = []
    def add(identity, workflow, bindings, expectations, **params):
        checks.append(dict(id=identity, workflow=workflow, inputs=bindings,
                           params=dict(memory=1024, **params), expect=expectations))
    add('duplicate-pairs-marked-not-removed', 'mark-duplicates',
        inputs(bam='duplicates'),
        [dict(output='metrics', kind='text', contains=['READ_PAIRS_EXAMINED', 'READ_PAIR_DUPLICATES', 'synthetic-library\t0\t5\t0\t0\t0\t2\t0\t0.4']),
         dict(output='bam-summary', kind='text', contains=['"records": 10', '"duplicates": 4'])])
    add('base-quality-recalibration-observations', 'bqsr',
        dict(inputs(bam='recalibration', reference='reference', targets='targets'),
             **{'known-sites': [{'known-sites': 'fixture-known-sites'}]}),
        [dict(output='recalibration', kind='text', contains=['#:GATKReport', 'RecalTable0', 'RecalTable1', 'RecalTable2',
              'synthetic-unit', '59970   40.00']),
         dict(output='bam-summary', kind='text', contains=['"records": 400', '"duplicates": 0', '"35": 400', '"36": 59600'])], sample='SAMPLE_A')
    add('heterozygous-germline-snp', 'haplotypecaller-vcf',
        inputs(bam='sample-a', reference='reference', targets='targets'),
        [dict(output='variants', kind='vcf', records=1, samples=['SAMPLE_A'],
              variants=[variant(1000)], absentVariants=[dict(chrom='chr1', pos=2000)])], sample='SAMPLE_A')
    add('reference-confidence-gvcf', 'haplotypecaller-gvcf',
        inputs(bam='sample-a', reference='reference', targets='targets'),
        [dict(output='gvcf', kind='vcf', records=91, samples=['SAMPLE_A'], variants=[
            dict(chrom='chr1', pos=1, alt='<NON_REF>', info={'END': '874'}, genotypes={'SAMPLE_A': '0/0'}),
            dict(chrom='chr1', pos=1000, ref=reference[999], alt=ALT[reference[999]] + ',<NON_REF>', genotypes={'SAMPLE_A': '0/1'}),
            dict(chrom='chr1', pos=2152, alt='<NON_REF>', info={'END': '5000'}, genotypes={'SAMPLE_A': '0/0'})])], sample='SAMPLE_A')
    add('gvcf-sample-merge', 'combine-gvcfs',
        dict(inputs(reference='reference'), gvcfs=[{'gvcfs': 'fixture-gvcf-a'}, {'gvcfs': 'fixture-gvcf-b'}]),
        [dict(output='gvcf', kind='vcf', records=5, samples=['SAMPLE_A', 'SAMPLE_B'],
              variants=[dict(chrom='chr1', pos=1000, alt=ALT[reference[999]] + ',<NON_REF>',
                             genotypes={'SAMPLE_A': './.', 'SAMPLE_B': './.'})])])
    add('gvcf-genotyping', 'genotype-gvcfs', inputs(reference='reference', gvcf='gvcf-a'),
        [dict(output='variants', kind='vcf', records=1, samples=['SAMPLE_A'], variants=[variant(1000)])])
    add('select-snps', 'select-variants', inputs(reference='reference', variants='variants'),
        [dict(output='variants', kind='vcf', records=2, samples=['SAMPLE_A'],
              variants=[variant(1000), variant(2000)], absentVariants=[dict(chrom='chr1', pos=3000)])], **{'variant-type': 'SNP'})
    add('explicit-quality-filter-label', 'variant-filtration', inputs(reference='reference', variants='variants'),
        [dict(output='variants', kind='vcf', records=3, samples=['SAMPLE_A'],
              variants=[variant(1000, filter='PASS'), variant(2000, filter='LowQual'),
                        dict(chrom='chr1', pos=3000, filter='PASS')])], **{'filter-annotation': 'QUAL', 'filter-comparison': 'lt', 'filter-threshold': '30', 'filter-name': 'LowQual'})
    add('validate-reference-alleles-and-genotypes', 'validate-variants', inputs(reference='reference', variants='variants'),
        [dict(output='validation', kind='text', contains=['"valid": true'])])
    return dict(schema=1, checks=checks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.folder), indent=2))
