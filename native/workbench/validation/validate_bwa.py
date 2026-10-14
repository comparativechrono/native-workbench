#!/usr/bin/env python3
"""Validate classic BWA Linux/APE equivalence; does not execute Windows.

Creates a new output directory and retains logs and outputs. Optionally tests
one complete real yeast lane. No timings are interpreted as benchmarks.
"""
import argparse
import gzip
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess

from validate_variant_pipeline import fixture, paired_qc, sam_signature, vcf_signature

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = ('.amb', '.ann', '.bwt', '.pac', '.sa')
RG = r'@RG\tID:truth\tSM:truth\tLB:library1\tPL:ILLUMINA'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Run:
    def __init__(self, folder, backend):
        self.folder, self.backend, self.steps = folder, backend, []
        folder.mkdir(parents=True)

    def command(self, tool, args, output=None, success=True):
        executable = ROOT / 'baselines/bin' / (tool + ('-linux' if self.backend == 'linux' else '-cosmo.exe'))
        command = ([str(ROOT / 'baselines/bin/ape-loader-linux')] if self.backend == 'cosmo' else [])
        command += [str(executable), *map(str, args)]
        number = len(self.steps) + 1
        output = self.folder / (output or f'{number:02d}-{tool}.stdout.txt')
        error = self.folder / f'{number:02d}-{tool}.stderr.txt'
        with output.open('xb') as out, error.open('xb') as err:
            completed = subprocess.run(command, cwd=self.folder, stdin=subprocess.DEVNULL,
                                       stdout=out, stderr=err, timeout=900)
        self.steps.append({'argv': command, 'exit_code': completed.returncode,
                           'stdout': output.name, 'stderr': error.name})
        (self.folder / 'steps.json').write_text(json.dumps(self.steps, indent=2) + '\n')
        if (completed.returncode == 0) != success:
            raise RuntimeError(f'Unexpected exit {completed.returncode}: {command}; {error}')
        return output


def truth_pipeline(run, sam, dataset):
    run.command('samtools', ['sort', '-n', '-m', '256M', '-T', 'name-sort', '-o', 'names.bam', sam])
    run.command('samtools', ['fixmate', '-m', 'names.bam', 'fixed.bam'])
    run.command('samtools', ['sort', '-m', '256M', '-T', 'coordinate-sort', '-o', 'coordinates.bam', 'fixed.bam'])
    run.command('samtools', ['markdup', '-s', '-f', 'duplicates.txt', 'coordinates.bam', 'marked.bam'])
    run.command('samtools', ['index', '-c', 'marked.bam'])
    run.command('samtools', ['quickcheck', '-v', 'marked.bam'])
    run.command('samtools', ['faidx', 'reference with spaces éΔ.fa'])
    run.command('bcftools', ['mpileup', '-f', 'reference with spaces éΔ.fa', '-a', 'FORMAT/DP,FORMAT/AD',
                            '-q', '20', '-Q', '20', '-d', '1000', '-Ob', '-o', 'pileup.bcf', 'marked.bam'])
    run.command('bcftools', ['call', '-m', '-v', '--ploidy', '2', '-Ob', '-o', 'calls.bcf', 'pileup.bcf'])
    run.command('bcftools', ['norm', '-f', 'reference with spaces éΔ.fa', '-m', '-any', '-Ob', '-o', 'normal.bcf', 'calls.bcf'])
    run.command('bcftools', ['filter', '-s', 'LowQual', '-e', 'QUAL<20 || FORMAT/DP<5', '-Oz', '-o', 'variants.vcf.gz', 'normal.bcf'])
    run.command('bcftools', ['index', '--csi', 'variants.vcf.gz'])
    decoded = run.command('samtools', ['view', '-h', 'marked.bam'], 'marked.sam')
    bam = sam_signature(decoded)
    vcf_path = run.command('bcftools', ['view', '-Ov', 'variants.vcf.gz'], 'variants.vcf')
    vcf, variants = vcf_signature(vcf_path)
    keys = ('chrom', 'pos', 'ref', 'alt', 'gt')
    observed = [{key: variant[key] for key in keys} for variant in variants]
    assert observed == dataset['truth']['variants'], observed
    assert all(variant['filter'] == 'PASS' for variant in variants)
    assert bam['metrics']['duplicate_primary'] == 2 * dataset['truth']['duplicate_pairs_added'], bam
    indexed = run.command('bcftools', ['query', '-r', 'fixture:1-6000', '-f', '%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n',
                                     'variants.vcf.gz'], 'indexed-variants.tsv')
    assert indexed.read_bytes() == (Path(dataset['reference']).parent / 'expected-variants.tsv').read_bytes()
    count = run.command('samtools', ['view', '-c', 'marked.bam', 'fixture:1-6000'], 'indexed-bam-count.txt')
    assert int(count.read_text()) == bam['metrics']['records']
    return {'bam': bam, 'vcf': vcf, 'expected_variants': observed,
            'duplicate_pairs': bam['metrics']['duplicate_primary'] // 2,
            'bam_csi_retrieval_passed': True, 'vcf_csi_retrieval_passed': True}


def dataset_test(dataset, output, compressed):
    folder = output / dataset['name']
    inputs = folder / 'inputs with spaces éΔ'
    inputs.mkdir(parents=True)
    reads = []
    for mate in (1, 2):
        path = inputs / (f'mate {mate} éΔ.fastq' + ('.gz' if compressed else ''))
        with open(dataset[f'r{mate}'], 'rb') as src:
            with (gzip.open(path, 'wb', compresslevel=1) if compressed else path.open('wb')) as dst:
                shutil.copyfileobj(src, dst)
        reads.append(path)
    copies = {str(path): sha(path) for path in reads}
    result = {'compressed_reads': compressed, 'paired_qc': paired_qc(*reads), 'backends': {}}
    for backend in ('linux', 'cosmo'):
        print(dataset['name'] + ': ' + backend, flush=True)
        run = Run(folder / backend, backend)
        reference = run.folder / 'reference with spaces éΔ.fa'
        shutil.copyfile(dataset['reference'], reference)
        reference_before = sha(reference)
        prefix = run.folder / 'index with spaces éΔ'
        run.command('bwa', ['index', '-p', prefix, reference])
        indexes = {suffix: sha(Path(str(prefix) + suffix)) for suffix in SUFFIXES}
        assert all(Path(str(prefix) + suffix).stat().st_size for suffix in SUFFIXES)
        sam = run.command('bwa', ['mem', '-t', '2', '-K', '1000000', '-R', RG, prefix, *reads], 'alignment.sam')
        signature = sam_signature(sam)
        assert signature['metrics']['primary'] == 2 * result['paired_qc'][0]['records']
        expected_header = b'@RG\tID:truth\tSM:truth\tLB:library1\tPL:ILLUMINA\n'
        with sam.open('rb') as stream:
            rg_found = False
            for line in stream:
                if line.startswith(b'@'):
                    rg_found |= line == expected_header
                else:
                    assert b'RG:Z:truth' in line.rstrip(b'\n').split(b'\t')[11:]
        assert rg_found
        record = {'indexes_sha256': indexes, 'sam': signature, 'read_group_verified': True}
        if 'truth' in dataset:
            one_thread = run.command('bwa', ['mem', '-t', '1', '-K', '1000000', '-R', RG, prefix, *reads], 'one-thread.sam')
            assert sam_signature(one_thread)['ordered_sha256_without_PG_header'] == signature['ordered_sha256_without_PG_header']
            # BWA deliberately rejects actual TABs; adapters must pass literal backslash-t.
            bad = run.command('bwa', ['mem', '-R', RG.replace('\\t', '\t'), prefix, *reads], 'invalid-read-group.sam', success=False)
            assert not bad.stat().st_size
            record['one_vs_two_threads_equal'] = True
            record['actual_tab_read_group_rejected'] = True
            record['truth_pipeline'] = truth_pipeline(run, sam, dataset)
        assert sha(reference) == reference_before
        record['reference_unchanged'] = True
        record['steps'] = run.steps
        result['backends'][backend] = record
    a, b = (result['backends'][name] for name in ('linux', 'cosmo'))
    assert a['indexes_sha256'] == b['indexes_sha256']
    assert a['sam']['ordered_sha256_without_PG_header'] == b['sam']['ordered_sha256_without_PG_header']
    assert a['sam']['canonical_records_and_headers_sha256'] == b['sam']['canonical_records_and_headers_sha256']
    if 'truth' in dataset:
        assert a['truth_pipeline']['bam']['ordered_sha256_without_PG_header'] == b['truth_pipeline']['bam']['ordered_sha256_without_PG_header']
        assert a['truth_pipeline']['vcf']['normalized_sha256'] == b['truth_pipeline']['vcf']['normalized_sha256']
    assert copies == {path: sha(Path(path)) for path in copies}
    result.update(status='passed', indexes_byte_identical=True, sam_equal_omitting_only_PG_header=True,
                  reads_unchanged=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--practical-dir', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'host': platform.platform(), 'native_windows_execution_verified': False,
              'scope': 'Linux-host native/APE correctness checks; no Windows or performance claims',
              'validator_sha256': sha(Path(__file__)), 'results': {}}
    report['binaries_sha256'] = {str(path.relative_to(ROOT)): sha(path) for path in
        [ROOT / 'baselines/bin/ape-loader-linux', *[ROOT / 'baselines/bin' / (tool + suffix)
         for tool in ('bwa', 'samtools', 'bcftools') for suffix in ('-linux', '-cosmo.exe')]]}
    try:
        tiny = fixture(output / 'fixture')
        datasets = [(tiny, False), ({**tiny, 'name': 'tiny-truth-gzip'}, True)]
        if args.practical_dir:
            directory = args.practical_dir.resolve(strict=True)
            datasets.append(({'name': 'yeast-lane1-gzip',
                              'reference': directory / 'Saccharomyces_cerevisiae.EF4.68.dna.toplevel.fa',
                              'r1': directory / 'lane1/s-7-1.fastq', 'r2': directory / 'lane1/s-7-2.fastq'}, True))
        originals = {str(data[key]): sha(Path(data[key])) for data, _ in datasets for key in ('reference', 'r1', 'r2')}
        report['inputs_sha256'] = originals
        for data, compressed in datasets:
            report['results'][data['name']] = dataset_test(data, output, compressed)
            (output / 'validation-summary.json').write_text(json.dumps(report, indent=2) + '\n')
        assert originals == {path: sha(Path(path)) for path in originals}
        assert report['binaries_sha256'] == {path: sha(ROOT / path) for path in report['binaries_sha256']}
        report['inputs_unchanged'] = True
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=repr(error))
        raise
    finally:
        (output / 'validation-summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(output / 'validation-summary.json')


if __name__ == '__main__':
    main()
