#!/usr/bin/env python3
"""Package the modular release, source, tiny fixture and compact evidence."""
import argparse
import configparser
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKS = ['reads', 'align', 'bam', 'variants', 'variant-pipeline']
VERSION = '0.3.0'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path,
                    default=ROOT.parent / 'native-workbench-0.3.0-windows.zip')
    args = ap.parse_args()
    destination = args.output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bw03-package-', dir=destination.parent) as temp:
        stage = Path(temp) / 'native-workbench'
        stage.mkdir()

        def copy(source, target):
            output = stage / target
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)

        def tree(source, target):
            for file in sorted(source.rglob('*')):
                if file.is_file() and '__pycache__' not in file.parts and file.suffix not in ('.o', '.obj', '.tmp', '.pyc', '.dbg'):
                    copy(file, Path(target) / file.relative_to(source))

        copy(ROOT / 'build/desktop/NativeWorkbench.exe', 'NativeWorkbench.exe')
        copy(ROOT / 'README-0.3.txt', 'README.txt')
        for filename in ('LICENSE', 'variant-protocol.txt'):
            copy(ROOT / filename, filename)
        for filename in ('PACK-FORMAT.txt', 'BUILD-0.3.txt', 'ui-preview.svg'):
            copy(ROOT / 'docs' / filename, Path('docs') / filename)
        for filename, argument in [('start-windows.cmd', ''), ('check-windows.cmd', ' --check')]:
            (stage / filename).write_bytes((
                '@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
                'start "" "%~dp0NativeWorkbench.exe"' + argument + '\r\n').encode('ascii'))

        workflow_count = 0
        for pack in PACKS:
            relative = Path('packs') / f'{pack}-{VERSION}'
            tree(ROOT / relative, relative)
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(stage / relative / 'pack.ini', encoding='utf-8')
            for section in cfg.sections():
                if section.startswith('tool:'):
                    tool = cfg[section]
                    assert sha(stage / relative / tool['path']) == tool['sha256'], section
                workflow_count += section.startswith('workflow:')
        assert workflow_count == 24

        fixture = ROOT / 'validation/results/tiny-final-csi-20261002/fixture'
        tree(fixture, 'examples/variant-truth')
        for filename in ('reads.fastq', 'reference.fa', 'tiny.fastq', 'tiny.expected.json'):
            copy(ROOT / 'examples' / filename, Path('examples') / filename)
        reports = {
            ROOT / 'validation/results/complete-20261002/validation-summary.json': 'variant-validation-real-and-truth.json',
            ROOT / 'validation/results/tiny-final-csi-20261002/validation-summary.json': 'variant-validation-final-csi.json',
            ROOT / 'validation/pack-smoke-final/smoke-results.json': 'pack-workflows-24.json',
            ROOT.parent / 'paircheck-validation.json': 'paircheck-validation.json',
        }
        for source, target in reports.items():
            copy(source, Path('validation') / target)

        src = Path('source/native-workbench')
        for folder in ('desktop', 'tools', 'tests', 'src', 'include', 'platform_windows', 'scripts', 'docs', 'examples', 'packs', 'vendor', 'baselines/licenses', 'vendor-variant/archives', 'vendor-variant/licenses'):
            tree(ROOT / folder, src / folder)
        for filename in ('LICENSE', 'README-0.3.txt', 'variant-protocol.txt', 'variant-provenance.json', 'build_variant.py'):
            copy(ROOT / filename, src / filename)
        for filename in ('build_upstream.py', 'benchmark_upstream.py', 'README.md'):
            copy(ROOT / 'baselines' / filename, src / 'baselines' / filename)
        tree(ROOT / 'baselines/bin', src / 'baselines/bin')
        for filename in ('validate_variant_pipeline.py', 'smoke_pack_workflows.py'):
            copy(ROOT / 'validation' / filename, src / 'validation' / filename)
        host = ROOT / 'build/bwfastq-linux'
        if not host.exists():
            host = ROOT / 'bin/linux/bwfastq'
        copy(host, src / 'build/bwfastq-linux')
        tree(fixture, src / 'examples/variant-truth')

        model = ROOT / 'build/model/test_pack_model'
        check = subprocess.run([str(model), *map(str, sorted((stage / src / 'packs').glob('*/pack.ini')))],
                               text=True, capture_output=True, check=True)
        report = {'version': VERSION, 'pack_model_check_stdout': check.stdout.strip(),
                  'pack_count': len(PACKS), 'workflow_count': workflow_count,
                  'native_windows_checks_available': 18,
                  'desktop_cross_compilation': 'passed',
                  'desktop_native_windows_execution_verified': False,
                  'new_tools_native_windows_execution_verified': False,
                  'scientific_validation': 'Portable and Linux pipelines passed on tiny truth and both yeast lanes; see reports.',
                  'sampling_note': 'No Windows execution is inferred from Linux portability checks.'}
        (stage / 'validation/release-checks.json').write_text(json.dumps(report, indent=2) + '\n')
        files = [{'path': p.relative_to(stage).as_posix(), 'bytes': p.stat().st_size, 'sha256': sha(p)}
                 for p in sorted(stage.rglob('*')) if p.is_file()]
        (stage / 'manifest.json').write_text(json.dumps({
            'format_version': 2, 'name': 'Native Workbench modular Windows preview', 'version': VERSION,
            'desktop_native_windows_execution_verified': False,
            'manifest_includes_itself': False, 'files': files}, indent=2) + '\n')
        pending = destination.with_suffix('.zip.partial')
        with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for file in sorted(stage.rglob('*')):
                if file.is_file():
                    z.write(file, file.relative_to(stage.parent))
        with zipfile.ZipFile(pending) as z:
            assert z.testzip() is None
            manifest = json.loads(z.read('native-workbench/manifest.json'))
            for entry in manifest['files']:
                data = z.read('native-workbench/' + entry['path'])
                assert len(data) == entry['bytes']
                assert hashlib.sha256(data).hexdigest() == entry['sha256']
        pending.replace(destination)
    print(json.dumps({'path': str(destination), 'bytes': destination.stat().st_size,
                      'sha256': sha(destination), 'files': len(files) + 1,
                      'workflows': workflow_count, 'model_check': check.stdout.strip()}, indent=2))


if __name__ == '__main__':
    main()
