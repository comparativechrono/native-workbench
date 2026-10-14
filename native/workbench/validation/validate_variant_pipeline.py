#!/usr/bin/env python3
"""Reproducible end-to-end variant portability checks; stdlib, Linux validation.

Run with --output NEW_DIRECTORY [--practical-dir PATH]. Override each argv
prefix using --tools-json with keys linux/portable, each mapping seqtk,
minimap2, samtools, bcftools to an array of executable/loader arguments.
No shell, no networking, no edits to selected inputs, no timing claims.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = 'Saccharomyces_cerevisiae.EF4.68.dna.toplevel.fa'
TOOLS = ('seqtk', 'minimap2', 'samtools', 'bcftools')


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def find_existing(*paths):
    for path in paths:
        if path.is_file():
            return str(path.resolve())
    raise FileNotFoundError('Missing executable; looked for ' + ', '.join(map(str, paths)))


def default_tools():
    linux, portable = {}, {}
    loader = find_existing(ROOT / 'bin/linux/ape-loader', ROOT / 'baselines/bin/ape-loader-linux')
    for name in TOOLS:
        linux[name] = [find_existing(ROOT / 'bin/linux' / name, ROOT / 'baselines/bin' / (name + '-linux'))]
        portable[name] = [loader, find_existing(ROOT / 'bin/portable' / (name + '.exe'),
                                               ROOT / 'baselines/bin' / (name + '-cosmo.exe'))]
    return {'linux': linux, 'portable': portable}


def read_fastq(path):
    with (gzip.open(path, 'rb') if str(path).endswith('.gz') else open(path, 'rb')) as f:
        i = 0
        while True:
            header = f.readline()
            if not header:
                return
            sequence, plus, quality = f.readline(), f.readline(), f.readline()
            i += 1
            header, sequence, plus, quality = (x.rstrip(b'\r\n') for x in (header, sequence, plus, quality))
            if (not header.startswith(b'@') or not plus.startswith(b'+') or not sequence
                    or len(sequence) != len(quality) or set(sequence.upper()) - set(b'ACGTN')
                    or not quality or min(quality) < 33 or max(quality) > 126):
                raise ValueError(f'Invalid strict Phred33 FASTQ record {i}: {path}')
            yield header, sequence, quality


def mate_key(header):
    name = header[1:].split()[0]
    return name[:-2] if name.endswith((b'/1', b'/2')) else name


def paired_qc(r1, r2):
    from itertools import zip_longest
    counts = [{'records': 0, 'bases': 0, 'gc_bases': 0, 'n_bases': 0,
               'min_length': None, 'max_length': 0, 'phred33_sum': 0} for _ in range(2)]
    for a, b in zip_longest(read_fastq(r1), read_fastq(r2)):
        if a is None or b is None or mate_key(a[0]) != mate_key(b[0]):
            raise ValueError('Mate count or name mismatch')
        for c, (_, sequence, quality) in zip(counts, (a, b)):
            sequence = sequence.upper()
            c['records'] += 1
            c['bases'] += len(sequence)
            c['gc_bases'] += sequence.count(b'G') + sequence.count(b'C')
            c['n_bases'] += sequence.count(b'N')
            c['min_length'] = min(c['min_length'] or len(sequence), len(sequence))
            c['max_length'] = max(c['max_length'], len(sequence))
            c['phred33_sum'] += sum(quality) - 33 * len(quality)
    if not counts[0]['records']:
        raise ValueError('Empty FASTQ')
    return counts


def fixture(folder):
    folder.mkdir()
    rng = random.Random(20261002)
    ref = ''.join(rng.choice('ACGT') for _ in range(6000))
    alt_base = lambda x: 'ACGT'[('ACGT'.index(x) + 1) % 4]
    # Avoid equivalent left shifts so the independent truth is already normalized.
    ins = 'GT' + alt_base(ref[2499])
    deletion = next(p for p in range(4500, 4520) if ref[p - 1] != ref[p + 2])
    edits = [(1501, ref[1500], alt_base(ref[1500]), '0/1'),
             (2500, ref[2499], ref[2499] + ins, '1/1'),
             (3501, ref[3500], alt_base(ref[3500]), '1/1'),
             (deletion, ref[deletion - 1:deletion + 3], ref[deletion - 1], '1/1')]
    haps = []
    for hap in (0, 1):
        seq = ref
        for pos, before, after, gt in reversed(edits):
            if gt == '1/1' or hap:
                assert seq[pos - 1:pos - 1 + len(before)] == before
                seq = seq[:pos - 1] + after + seq[pos - 1 + len(before):]
        haps.append(seq)
    reference = folder / 'reference.fa'
    reference.write_text('>fixture\n' + '\n'.join(ref[i:i + 60] for i in range(0, len(ref), 60)) + '\n')
    paths = [folder / 'reads1.fastq', folder / 'reads2.fastq']
    pair_count = 0
    reverse = str.maketrans('ACGT', 'TGCA')
    duplicates = []
    with paths[0].open('w') as r1, paths[1].open('w') as r2:
        for hap, sequence in enumerate(haps):
            for start in range(30 + hap * 3, len(sequence) - 400, 6):
                span = 280 + rng.randrange(70)
                reads = (sequence[start:start + 150], sequence[start + span - 150:start + span].translate(reverse)[::-1])
                pair_count += 1
                name = f'fragment{pair_count:06d}'
                for mate, (stream, read) in enumerate(zip((r1, r2), reads), 1):
                    stream.write(f'@{name}/{mate}\n{read}\n+\n' + 'I' * 150 + '\n')
                if pair_count % 101 == 0 and len(duplicates) < 12:
                    duplicates.append(reads)
        for i, reads in enumerate(duplicates):
            pair_count += 1
            for mate, (stream, read) in enumerate(zip((r1, r2), reads), 1):
                stream.write(f'@duplicate{i:03d}/{mate}\n{read}\n+\n' + 'H' * 150 + '\n')
    truth = {'seed': 20261002, 'read_pairs': pair_count, 'duplicate_pairs_added': len(duplicates),
             'variants': [{'chrom': 'fixture', 'pos': p, 'ref': r, 'alt': a, 'gt': g} for p, r, a, g in edits]}
    write_json(folder / 'truth.json', truth)
    (folder / 'expected-variants.tsv').write_text(''.join(f'fixture\t{p}\t{r}\t{a}\t{g}\n' for p, r, a, g in edits))
    return {'name': 'tiny-truth', 'reference': reference, 'r1': paths[0], 'r2': paths[1], 'truth': truth}


class Runner:
    def __init__(self, commands, folder):
        self.commands, self.folder, self.steps = commands, folder, []
        folder.mkdir(parents=True)

    def run(self, tool, args, stdout=None):
        number = len(self.steps) + 1
        stem = f'{number:02d}-{tool}-{args[0] if args and not args[0].startswith("-") else "run"}'
        log = self.folder / (stem + '.stderr.txt')
        target = self.folder / (stdout or stem + '.stdout.txt')
        command = self.commands[tool] + list(map(str, args))
        entry = {'argv': command, 'stderr': log.name, 'stdout': target.name}
        self.steps.append(entry)
        with log.open('xb') as err, target.open('xb') as out:
            result = subprocess.run(command, cwd=self.folder, stdin=subprocess.DEVNULL, stdout=out, stderr=err, check=False)
        entry['exit_code'] = result.returncode
        if result.returncode:
            raise RuntimeError(f'{tool} failed ({result.returncode}); see {log}')
        return target


def sam_signature(path):
    ordered, headers, record_hashes = hashlib.sha256(), [], []
    metrics = {'records': 0, 'primary': 0, 'mapped_primary': 0, 'duplicate_primary': 0,
               'proper_pair_primary': 0, 'secondary': 0, 'supplementary': 0}
    with path.open('rb') as stream:
        for line in stream:
            if line.startswith(b'@PG\t'):
                continue
            ordered.update(line)
            if line.startswith(b'@'):
                headers.append(line)
                continue
            fields = line.rstrip(b'\r\n').split(b'\t')
            if len(fields) < 11:
                raise ValueError('Truncated SAM record')
            record_hashes.append(hashlib.sha256(b'\t'.join(fields[:11] + sorted(fields[11:]))).digest())
            flag = int(fields[1])
            metrics['records'] += 1
            metrics['secondary'] += bool(flag & 256)
            metrics['supplementary'] += bool(flag & 2048)
            if not flag & (256 | 2048):
                metrics['primary'] += 1
                metrics['mapped_primary'] += not bool(flag & 4)
                metrics['duplicate_primary'] += bool(flag & 1024)
                metrics['proper_pair_primary'] += bool(flag & 2)
    h = hashlib.sha256(b''.join(headers))
    for record in sorted(record_hashes):
        h.update(record)
    return {'ordered_sha256_without_PG_header': ordered.hexdigest(),
            'canonical_records_and_headers_sha256': h.hexdigest(), 'metrics': metrics}


def vcf_signature(path):
    h, variants, omitted = hashlib.sha256(), [], []
    with path.open('rb') as f:
        for line in f:
            if (re.match(rb'##bcftools[^=]*(?:Version|Command)=', line)
                    or line.startswith((b'##reference=', b'##fileDate='))):
                omitted.append(line.split(b'=', 1)[0].decode())
                continue
            h.update(line)
            if line.startswith(b'#'):
                continue
            fields = line.decode().rstrip('\r\n').split('\t')
            if len(fields) != 10:
                raise ValueError('Expected one-sample VCF')
            fmt = dict(zip(fields[8].split(':'), fields[9].split(':')))
            variants.append({'chrom': fields[0], 'pos': int(fields[1]), 'ref': fields[3], 'alt': fields[4],
                             'gt': fmt.get('GT'), 'filter': fields[6], 'qual': fields[5], 'dp': fmt.get('DP')})
    return {'normalized_sha256': h.hexdigest(), 'record_count': len(variants),
            'pass_records': sum(v['filter'] == 'PASS' for v in variants),
            'metadata_keys_omitted': sorted(set(omitted))}, variants


def pipeline(dataset, commands, folder, settings):
    runner = Runner(commands, folder)
    reference = folder / 'reference.fa'
    shutil.copyfile(dataset['reference'], reference)
    expected_qc = dataset['qc']
    result = {'dataset': dataset['name'], 'steps': runner.steps, 'status': 'running'}
    try:
        for i in (1, 2):
            qcfile = runner.run('seqtk', ['fqchk', dataset['r' + str(i)]], f'reads{i}.qc.txt')
            lines = qcfile.read_text().splitlines()
            summary = re.match(r'min_len: (\d+); max_len: (\d+);', lines[0])
            if (not summary or tuple(map(int, summary.groups())) !=
                    (expected_qc[i - 1]['min_length'], expected_qc[i - 1]['max_length'])
                    or int(lines[2].split('\t')[1]) != expected_qc[i - 1]['bases']
                    or int(lines[3].split('\t')[1]) != expected_qc[i - 1]['records']):
                raise ValueError(f'seqtk QC differs from independent FASTQ counts: mate {i}')
        runner.run('minimap2', ['-a', '-x', 'sr', '-t', str(settings['threads']), '-R',
                   '@RG\\tID:truth\\tSM:truth\\tLB:library1\\tPL:ILLUMINA',
                   'reference.fa', dataset['r1'], dataset['r2']], 'alignment.sam')
        # The pinned Cosmo/HTSlib stack rejects the recursive mutex used by the
        # threaded BGZF pool. Default zero matches the safe, validated pack.
        # An explicit override remains available to reproduce that regression.
        io_threads = ['-@', str(settings['samtools_threads'])] if settings['samtools_threads'] else []
        runner.run('samtools', ['sort', '-n', '-m', '256M'] + io_threads + ['-T', 'name-sort', '-o', 'namesorted.bam', 'alignment.sam'])
        runner.run('samtools', ['fixmate', '-m'] + io_threads + ['namesorted.bam', 'fixmate.bam'])
        runner.run('samtools', ['sort', '-m', '256M'] + io_threads + ['-T', 'coordinate-sort', '-o', 'coordinates.bam', 'fixmate.bam'])
        runner.run('samtools', ['markdup', '-s'] + io_threads + ['-T', 'markdup', '-f', 'duplicates.txt', 'coordinates.bam', 'alignment.marked.bam'])
        runner.run('samtools', ['index', '-c', 'alignment.marked.bam'])
        runner.run('samtools', ['quickcheck', '-v', 'alignment.marked.bam'])
        runner.run('samtools', ['flagstat', 'alignment.marked.bam'], 'flagstat.txt')
        runner.run('samtools', ['stats', 'alignment.marked.bam'], 'alignment.stats.txt')
        runner.run('samtools', ['faidx', 'reference.fa'])
        runner.run('bcftools', ['mpileup', '-f', 'reference.fa', '-a', 'FORMAT/DP,FORMAT/AD',
                   '-q', str(settings['min_mapq']), '-Q', str(settings['min_baseq']), '-d', str(settings['max_depth']),
                   '-Ob', '-o', 'pileup.bcf', 'alignment.marked.bam'])
        runner.run('bcftools', ['call', '-m', '-v', '--ploidy', str(settings['ploidy']), '-Ob', '-o', 'calls.bcf', 'pileup.bcf'])
        runner.run('bcftools', ['norm', '-f', 'reference.fa', '-m', '-any', '-Ob', '-o', 'normalized.bcf', 'calls.bcf'])
        runner.run('bcftools', ['filter', '-s', 'LowQual', '-e', settings['filter'], '-Oz', '-o', 'variants.vcf.gz', 'normalized.bcf'])
        runner.run('bcftools', ['index', '--csi', 'variants.vcf.gz'])
        runner.run('bcftools', ['stats', 'variants.vcf.gz'], 'variant.stats.txt')
        decoded = runner.run('samtools', ['view', '-h', 'alignment.marked.bam'], 'marked.decoded.sam')
        result['bam'] = sam_signature(decoded)
        if result['bam']['metrics']['primary'] != 2 * expected_qc[0]['records']:
            raise ValueError('Primary alignment count differs from input read count')
        vcf = runner.run('bcftools', ['view', '-Ov', 'variants.vcf.gz'], 'variants.decoded.vcf')
        result['vcf'], variants = vcf_signature(vcf)
        if 'truth' in dataset:
            keys = ('chrom', 'pos', 'ref', 'alt', 'gt')
            observed = [{k: v[k] for k in keys} for v in variants]
            if observed != dataset['truth']['variants']:
                raise ValueError(f'Tiny truth allele/genotype mismatch: {observed}')
            if any(v['filter'] != 'PASS' for v in variants):
                raise ValueError('Tiny truth calls did not pass the declared filter')
            if result['bam']['metrics']['duplicate_primary'] < 2 * dataset['truth']['duplicate_pairs_added']:
                raise ValueError('Known duplicate pairs were not marked')
            result['truth_validation'] = 'all four exact normalized alleles and genotypes passed; known duplicates marked'
        # Exercise indexes through a real query, independently count matching SAM records.
        first = (folder / 'reference.fa.fai').read_text().splitlines()[0].split('\t')
        contig, end = first[0], min(int(first[1]), 10000)
        region = f'{contig}:1-{end}'
        count_path = runner.run('samtools', ['view', '-c', 'alignment.marked.bam', region], 'indexed-bam-count.txt')
        # Counting any reference-consuming overlap with 1..end is exactly POS <= end for this interval.
        streaming_count = 0
        with decoded.open() as f:
            for line in f:
                if line.startswith('@'):
                    continue
                fields = line.rstrip('\n').split('\t')
                if fields[2] == contig and 0 < int(fields[3]) <= end:
                    streaming_count += 1
        if int(count_path.read_text().strip()) != streaming_count:
            raise ValueError('Indexed BAM region count differs from sequential count')
        query_format = '%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n'
        indexed = runner.run('bcftools', ['query', '-r', region, '--regions-overlap', '0', '-f', query_format, 'variants.vcf.gz'], 'indexed-vcf-query.txt')
        sequential = ''.join(f'{v["chrom"]}\t{v["pos"]}\t{v["ref"]}\t{v["alt"]}\t{v["gt"]}\n'
                             for v in variants if v['chrom'] == contig and 1 <= v['pos'] <= end)
        if indexed.read_text() != sequential:
            raise ValueError('Indexed VCF query differs from sequential records')
        result['index_checks'] = {'region': region, 'bam_count': streaming_count, 'passed': True}
        result['outputs'] = {name: sha(folder / name) for name in
                             ('reference.fa.fai', 'alignment.marked.bam', 'alignment.marked.bam.csi', 'variants.vcf.gz', 'variants.vcf.gz.csi')}
        result['qc_outputs_sha256'] = {f'reads{i}.qc.txt': sha(folder / f'reads{i}.qc.txt') for i in (1, 2)}
        result['status'] = 'passed'
    except Exception as error:
        result.update(status='failed', error=str(error))
        raise
    finally:
        write_json(folder / 'validation.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--practical-dir', type=Path)
    parser.add_argument('--tools-json', type=Path)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--samtools-threads', type=int, default=0,
                        help='Diagnostic only: nonzero currently fails in the pinned portable HTSlib thread pool.')
    args = parser.parse_args()
    if not 1 <= args.threads <= 64:
        parser.error('threads must be 1..64')
    if not 0 <= args.samtools_threads <= 16:
        parser.error('samtools-threads must be 0..16')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 1, 'status': 'running', 'host': platform.platform(),
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'scope': 'Linux host end-to-end correctness comparison, not Windows runtime validation or timing benchmark',
              'validator_sha256': sha(Path(__file__)),
              'settings': {'threads': args.threads, 'samtools_threads': args.samtools_threads, 'ploidy': 2, 'min_mapq': 20, 'min_baseq': 20,
                           'max_depth': 1000, 'filter': 'QUAL<20 || FORMAT/DP<5'},
              'datasets': [], 'results': {}, 'comparisons': {}}
    try:
        commands = json.loads(args.tools_json.read_text()) if args.tools_json else default_tools()
        for backend in ('linux', 'portable'):
            for tool in TOOLS:
                cmd = commands[backend][tool]
                if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
                    raise ValueError('Each tool argv prefix must be a nonempty string array')
                commands[backend][tool] = [str(Path(x).resolve(strict=True)) for x in cmd]
        report['commands'] = commands
        report['executables_sha256'] = {x: sha(x) for b in commands.values() for c in b.values() for x in c}
        datasets = [fixture(output / 'fixture')]
        if args.practical_dir:
            practical = args.practical_dir.resolve(strict=True)
            for lane in ('lane1', 'lane2'):
                datasets.append({'name': 'yeast-' + lane, 'reference': practical / REFERENCE,
                                 'r1': practical / lane / 's-7-1.fastq', 'r2': practical / lane / 's-7-2.fastq'})
        source_hashes = {}
        for dataset in datasets:
            dataset['qc'] = paired_qc(dataset['r1'], dataset['r2'])
            for key in ('reference', 'r1', 'r2'):
                source_hashes[str(dataset[key])] = sha(dataset[key])
            report['datasets'].append({'name': dataset['name'], 'qc': dataset['qc'],
                                       'inputs': {k: str(dataset[k]) for k in ('reference', 'r1', 'r2')}})
        report['inputs_sha256'] = source_hashes
        for dataset in datasets:
            name = dataset['name']
            report['results'][name] = {}
            for backend in ('linux', 'portable'):
                print(f'{name}: {backend}', flush=True)
                report['results'][name][backend] = pipeline(dataset, commands[backend], output / name / backend, report['settings'])
                write_json(output / 'validation-summary.json', report)
            a, b = (report['results'][name][x] for x in ('linux', 'portable'))
            comparison = {'bam_ordered_equal': a['bam']['ordered_sha256_without_PG_header'] == b['bam']['ordered_sha256_without_PG_header'],
                          'bam_all_record_fields_equal': a['bam']['canonical_records_and_headers_sha256'] == b['bam']['canonical_records_and_headers_sha256'],
                          'vcf_all_scientific_fields_equal': a['vcf']['normalized_sha256'] == b['vcf']['normalized_sha256'],
                          'fai_equal': a['outputs']['reference.fa.fai'] == b['outputs']['reference.fa.fai'],
                          'qc_reports_equal': a['qc_outputs_sha256'] == b['qc_outputs_sha256']}
            report['comparisons'][name] = comparison
            if not all(comparison.values()):
                raise ValueError(f'Native/portable output difference for {name}: {comparison}')
        if source_hashes != {p: sha(p) for p in source_hashes}:
            raise ValueError('Selected input changed during validation')
        report['inputs_unchanged'] = True
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=str(error))
        print(str(error), file=sys.stderr)
    finally:
        report['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        write_json(output / 'validation-summary.json', report)
    print(output / 'validation-summary.json')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
