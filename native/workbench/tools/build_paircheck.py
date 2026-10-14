#!/usr/bin/env python3
"""Build paircheck using system GCC/zlib and pinned Cosmopolitan 3.3.10.

Cosmopolitan provides its own namespaced zlib; no DLL or -lz is used for
the portable executable. The existing verified toolchain is reused.
"""
import argparse
import hashlib
import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test_builds(practical_data=None):
    commands = {
        'linux': [str(ROOT / 'baselines/bin/paircheck-linux')],
        'cosmo': [str(ROOT / 'baselines/bin/ape-loader-linux'),
                  str(ROOT / 'baselines/bin/paircheck-cosmo.exe')],
    }
    first = b'@fragment/1 comment\nACGTRY\n+\nIIIIII\n'
    second = b'@fragment/2 comment\nRYACGT\n+\nIIIIII\n'
    expected = {'valid': True, 'pairs': 1, 'reads': 2, 'bases': 12,
                'bases_r1': 6, 'bases_r2': 6}
    wrapped = b'@fragment/1 comment\r\nACG\r\nTRY\r\n+\r\nII\r\nIIII\r\n'
    cases = [
        ('plain', first, second, True),
        ('wrapped-crlf', wrapped, second, True),
        ('no-final-newline', first.rstrip(b'\n'), second.rstrip(b'\n'), True),
        ('gzip-both', gzip.compress(first), gzip.compress(second), True),
        ('gzip-mixed', gzip.compress(first), second, True),
        ('no-mate-suffix', first.replace(b'/1', b''), second.replace(b'/2', b''), True),
        ('quality-header-characters', first.replace(b'IIIIII', b'@+IIII'), second, True),
        ('names-differ', first, second.replace(b'fragment', b'another'), False),
        ('counts-differ', first + first, second, False),
        ('short-quality', first.replace(b'IIIIII', b'III'), second, False),
        ('long-quality', first.replace(b'IIIIII', b'IIIIIII'), second, False),
        ('missing-quality', b'@fragment/1\nACGTRY\n', second, False),
        ('fasta', b'>fragment/1\nACGTRY\n', second, False),
        ('invalid-base', first.replace(b'ACGTRY', b'ACGT?Y'), second, False),
        ('invalid-quality', first.replace(b'IIIIII', b'II III'), second, False),
        ('wrong-mate-suffix', first.replace(b'/1', b'/2'), second, False),
        ('empty', b'', b'', False),
        ('empty-read', b'@fragment/1\n+\n\n', second, False),
        ('trailing-junk', first + b'junk\n', second, False),
        ('gzip-truncated-trailer', gzip.compress(first)[:-4], second, False),
        ('gzip-truncated-payload', gzip.compress(first)[:20], second, False),
        ('gzip-bad-crc', gzip.compress(first)[:-8] + b'\0\0\0\0' + gzip.compress(first)[-4:], second, False),
        ('gzip-next-header-one-byte', gzip.compress(first) + b'\x1f', second, False),
        ('gzip-next-header-two-bytes', gzip.compress(first) + b'\x1f\x8b', second, False),
        ('gzip-trailing-garbage', gzip.compress(first) + b'garbage', second, False),
        ('gzip-concatenated', gzip.compress(first[:13]) + gzip.compress(first[13:]), second, True),
        ('gzip-empty-member', gzip.compress(b'') + gzip.compress(first) + gzip.compress(b''), second, True),
    ]
    records = []
    with tempfile.TemporaryDirectory(prefix='paircheck-tests-', dir=ROOT / 'variant-build/tmp') as folder:
        folder = Path(folder)
        for name, one, two, valid in cases:
            paths = [folder / 'mate 1.fastq', folder / 'mate 2.fastq']
            paths[0].write_bytes(one)
            paths[1].write_bytes(two)
            results = []
            for target, command in commands.items():
                result = subprocess.run([*command, '--reads1', str(paths[0]), '--reads2', str(paths[1])],
                                        capture_output=True, timeout=20)
                assert (result.returncode == 0) == valid, (name, target, result)
                if valid:
                    assert json.loads(result.stdout) == expected, (name, target, result.stdout)
                else:
                    assert not result.stdout and result.stderr, (name, target, result)
                results.append(result.stdout)
            assert results[0] == results[1], name
            records.append({'case': name, 'builds': list(commands), 'passed': True})
        # Cross compressed/decompressed buffering boundaries. A complete
        # FASTQ record count alone cannot prove gzip CRC/end-of-stream validity.
        large_first = (b'@record/1\n' + b'ACGT'*25 + b'\n+\n' + b'I'*100 + b'\n')*100000
        large_second = large_first.replace(b'/1\n', b'/2\n')
        compressed = gzip.compress(large_first, mtime=0)
        mid = len(large_first)//2
        member1 = gzip.compress(large_first[:mid], mtime=0)
        member2 = gzip.compress(large_first[mid:], mtime=0)
        large_cases = [
            ('large-gzip-valid', compressed, True),
            ('large-gzip-truncated4', compressed[:-4], False),
            ('large-gzip-truncated8', compressed[:-8], False),
            ('large-gzip-bad-crc', compressed[:-8]+b'\0'*4+compressed[-4:], False),
            ('large-multimember-valid', member1+member2, True),
            ('large-multimember-truncated4', member1+member2[:-4], False),
            ('large-multimember-truncated8', member1+member2[:-8], False),
            ('large-multimember-bad-crc', member1+member2[:-8]+b'\0'*4+member2[-4:], False),
            ('large-gzip-trailing-header', compressed+b'\x1f', False),
            ('large-gzip-trailing-garbage', compressed+b'garbage', False),
        ]
        second_path = folder/'large-mate2.fastq.gz'
        second_path.write_bytes(gzip.compress(large_second, mtime=0))
        for name, data, valid in large_cases:
            path = folder/'large-mate1.fastq.gz'
            path.write_bytes(data)
            python_valid = True
            try:
                assert gzip.decompress(data) == large_first
            except (EOFError, gzip.BadGzipFile):
                python_valid = False
            assert python_valid == valid, name
            results = []
            for target, command in commands.items():
                result = subprocess.run([*command, '--reads1', str(path), '--reads2', str(second_path)],
                                        capture_output=True, timeout=30)
                assert (result.returncode == 0) == valid, (name, target, result)
                if valid:
                    assert json.loads(result.stdout) == {'valid': True, 'pairs': 100000, 'reads': 200000,
                            'bases': 20000000, 'bases_r1': 10000000, 'bases_r2': 10000000}
                else:
                    assert not result.stdout and result.stderr, (name, target, result)
                results.append(result.stdout)
            assert results[0] == results[1], name
            records.append({'case': name, 'builds': list(commands), 'passed': True,
                            'python_gzip_oracle_checked': True})
        if practical_data:
            for lane in ('lane1', 'lane2'):
                paths = [practical_data / lane / f's-7-{mate}.fastq' for mate in (1, 2)]
                results = []
                for target, command in commands.items():
                    result = subprocess.run([*command, '--reads1', str(paths[0]), '--reads2', str(paths[1])],
                                            capture_output=True, timeout=120, check=True)
                    results.append(result.stdout)
                assert results[0] == results[1], lane
                records.append({'case': lane, 'builds': list(commands), 'passed': True,
                                'summary': json.loads(results[0])})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', choices=('all', 'linux', 'cosmo'), default='all')
    parser.add_argument('--cosmocc-root', type=Path,
                        default=ROOT / 'variant-build/cosmocc-3.3.10')
    parser.add_argument('--test', action='store_true', help='Check both builds against valid and malformed inputs')
    parser.add_argument('--practical-data', type=Path, help='Also check lane1 and lane2 in the university VariantCalling folder')
    args = parser.parse_args()
    output = ROOT / 'baselines/bin'
    output.mkdir(parents=True, exist_ok=True)
    temporary = ROOT / 'variant-build/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'tools/paircheck.c'
    records = []
    for target in ('linux', 'cosmo') if args.build == 'all' else (args.build,):
        path = output / f'paircheck-{target}{".exe" if target == "cosmo" else ""}'
        if target == 'linux':
            command = ['gcc']
            includes, libraries = [], ['-lz']
        else:
            compiler = args.cosmocc_root.resolve()
            command = [str(compiler / 'bin/x86_64-unknown-cosmo-cc')]
            includes = ['-I' + str(compiler / 'include/third_party/zlib')]
            libraries = []
        command += ['-std=c11', '-O2', '-Wall', '-Wextra', '-Wpedantic',
                    *includes, str(source), '-o', str(path), *libraries]
        subprocess.run(command, cwd=ROOT, check=True,
                       env={**os.environ, 'TMPDIR': str(temporary)})
        records.append({'target': target, 'path': str(path),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'bytes': path.stat().st_size, 'command': command})
    report = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'builds': records}
    if args.test or args.practical_data:
        report['checks'] = test_builds(args.practical_data)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
