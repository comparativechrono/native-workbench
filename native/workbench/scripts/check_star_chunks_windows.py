#!/usr/bin/env python3
"""Verify native STAR chunk recycling after the immutable pack is installed.

Usage: python check_star_chunks_windows.py --app-root EXTRACTED_APP --report JSON
Run after check_pack_release_windows.py. This offline native-only gate compares
200 paired reads using default buffers against tiny, repeatedly recycled input
and SAM output buffers. Both runs use two threads, two passes and gene counts.
It invokes the installed hash-verified STAR.exe directly; the separate pack gate
tests the released Workbench engine. No installed pack bytes are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def snapshot(folder):
    result = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('Installed pack must not contain links.')
        if path.is_file():
            result[path.relative_to(folder).as_posix()] = digest(path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--pack-version', default='1.0.0')
    parser.add_argument('--timeout-seconds', type=int, default=120,
                        help='Timeout for each of three native invocations (10–300 seconds).')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        parser.exit(1, 'This chunk-buffer gate must run on native Windows.\n')
    if not 10 <= args.timeout_seconds <= 300:
        parser.error('--timeout-seconds must be between 10 and 300')
    app = args.app_root.resolve()
    if not (app / 'WorkbenchBridge.exe').is_file():
        parser.exit(1, 'Expected an extracted native Workbench application.\n')
    sys.path.insert(0, str(app / 'workspace'))
    from catalog import load_catalog, load_pack

    report = {'schema': 1, 'packId': 'star', 'packVersion': args.pack_version,
              'nativeWindowsHost': True, 'nativeWindowsExecuted': False,
              'threads': 2, 'passes': 2, 'readPairs': 200,
              'timeoutSecondsPerProcess': args.timeout_seconds,
              'scope': 'Direct native STAR external-buffer regression; installation and Workbench execution checked separately.',
              'success': False, 'passed': 0, 'failed': 1, 'commands': []}
    started = time.monotonic()
    pack_root = before = None
    try:
        catalog = load_catalog(app)
        choices = [row for row in catalog['packs'] if row['id'] == 'star' and row['version'] == args.pack_version]
        if len(choices) != 1:
            raise ValueError('Expected exactly one already-installed STAR pack at the requested version.')
        pack_root = (app / choices[0]['folder']).resolve()
        if not pack_root.is_relative_to(app):
            raise ValueError('Installed pack folder escapes the application.')
        before = snapshot(pack_root)
        pack = load_pack(pack_root / 'pack.ini')
        binary = pack_root / pack['tools']['star']['path']
        if digest(binary) != pack['tools']['star']['sha256']:
            raise ValueError('Native STAR executable checksum differs from the manifest.')
        def asset(name):
            declaration = pack['assets'][name]
            path = (pack_root / declaration['path']).resolve()
            if not path.is_relative_to(pack_root) or digest(path) != declaration['sha256']:
                raise ValueError('Fixture checksum/path differs: ' + name)
            return path
        reference = asset('fixture-reference')
        annotation = asset('fixture-annotation')
        original_reads = [asset('fixture-rna-r1'), asset('fixture-rna-r2')]
        results = app / 'results'; results.mkdir(exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix='star-chunk-check-', dir=results))
        report.update(folder=str(folder), manifestSha256=pack['manifestSha256'],
                      nativeExecutableSha256=digest(binary), installedFiles=len(before))
        def run(label, arguments):
            command = [str(binary), *map(str, arguments)]
            report['commands'].append(command)
            with (folder / (label + '.stdout.txt')).open('wb') as stdout, (folder / (label + '.stderr.txt')).open('wb') as stderr:
                # STAR uses threads, not child processes, in these selected modes.
                # Kill and wait explicitly, so timeout never leaves STAR running.
                with subprocess.Popen(command, cwd=folder, stdout=stdout, stderr=stderr) as process:
                    report['nativeWindowsExecuted'] = True
                    try:
                        returncode = process.wait(timeout=args.timeout_seconds)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise ValueError(label + ' exceeded the native process timeout.')
            if returncode:
                raise ValueError(label + ' failed with exit code ' + str(returncode))
        run('index', ['--runMode', 'genomeGenerate', '--genomeDir', str(folder / 'index') + '/',
                     '--genomeFastaFiles', reference, '--genomeSAindexNbases', '0', '--runThreadN', '2',
                     '--outFileNamePrefix', str(folder / 'build-'), '--sjdbGTFfile', annotation, '--sjdbOverhang', '99'])
        reads = []
        for mate, original in enumerate(original_reads, 1):
            text = original.read_text(encoding='ascii')
            path = folder / ('many-r' + str(mate) + '.fastq')
            path.write_text(''.join(text.replace('@rna_pair', '@rna_pair_' + str(i)) for i in range(200)),
                            encoding='ascii', newline='\n')
            reads.append(path)
        products = []
        for name, limits in [('normal', []), ('tiny', ['--limitIObufferSize', '204000', '6000', '--limitOutSAMoneReadBytes', '1000'])]:
            output = folder / name; output.mkdir()
            run(name, ['--genomeDir', str(folder / 'index') + '/', '--runThreadN', '2',
                       '--outFileNamePrefix', str(output) + '/', '--readFilesIn', *reads,
                       '--outSAMtype', 'SAM', '--outSAMunmapped', 'Within', '--outSAMattributes',
                       'NH', 'HI', 'AS', 'nM', 'NM', 'MD', 'XS', '--outSAMattrRGline',
                       'ID:validation', 'SM:validation', 'PL:ILLUMINA', '--twopassMode', 'Basic',
                       '--alignIntronMin', '21', '--alignIntronMax', '1000000', '--alignMatesGapMax',
                       '1000000', '--quantMode', 'GeneCounts', *limits])
            lines = sorted(line for line in (output / 'Aligned.out.sam').read_text().splitlines() if not line.startswith('@'))
            if len(lines) != 400:
                raise ValueError(name + ': expected 400 SAM records, found ' + str(len(lines)))
            fields = [line.split('\t') for line in lines]
            if (sum(row[5] == '50M800N50M' for row in fields) != 200
                    or sum(row[1] == '99' for row in fields) != 200
                    or sum(row[1] == '147' for row in fields) != 200
                    or len({row[0] for row in fields}) != 200):
                raise ValueError(name + ': spliced alignments, mate flags or unique read names differ.')
            counts = (output / 'ReadsPerGene.out.tab').read_text()
            if 'gene1\t200\t200\t0' not in counts.splitlines():
                raise ValueError(name + ': gene counts differ.')
            products.append((lines, counts))
        if products[0] != products[1]:
            raise ValueError('Native normal and recycled tiny chunks disagree.')
        report.update(samRecords=400, splicedRecords=200, geneCounts=[200, 200, 0],
                      normalAndRecycledChunksIdentical=True, success=True, passed=1, failed=0)
    except Exception as error:
        report['error'] = str(error)
    finally:
        if before is not None:
            try:
                report['installedPackUnchanged'] = snapshot(pack_root) == before
            except Exception as error:
                report['installedPackUnchanged'] = False
                report['error'] = str(error)
            if not report['installedPackUnchanged']:
                report.update(success=False, passed=0, failed=1, error='Installed STAR pack changed during validation.')
        report['elapsedSeconds'] = round(time.monotonic() - started, 3)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('success', 'nativeWindowsExecuted', 'passed', 'failed', 'elapsedSeconds')}))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
