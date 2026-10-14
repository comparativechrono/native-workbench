#!/usr/bin/env python3
"""Assemble and verify the 0.4 research release and corresponding source."""
import argparse
import configparser
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.4.0'
PACKS = ['reads', 'align', 'bam', 'variants', 'variant-pipeline',
         'trimming', 'fastp', 'bwa', 'freebayes', 'research-variants']
OMIT_SUFFIXES = {'.o', '.obj', '.pyc', '.tmp', '.dbg'}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def files_in(folder):
    for path in sorted(folder.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in OMIT_SUFFIXES:
            if path.is_symlink():
                raise ValueError(f'Unexpected symlink: {path}')
            yield path


def archive(tree, destination):
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in files_in(tree):
            z.write(path, Path('native-workbench') / path.relative_to(tree))
    with zipfile.ZipFile(destination) as z:
        assert z.testzip() is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT.parent / f'native-workbench-{VERSION}-windows.zip')
    parser.add_argument('--cosmo-source', type=Path, default=ROOT / 'variant-build/cosmopolitan-3.3.10.tar.gz')
    args = parser.parse_args()
    destination = args.output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bw04-package-', dir=destination.parent) as temp:
        stage, source = Path(temp) / 'app', Path(temp) / 'source'
        stage.mkdir()
        source.mkdir()

        def copy(origin, target, base=stage):
            target = base / target
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)

        def tree(origin, target, base=stage):
            assert origin.is_dir(), origin
            for file in files_in(origin):
                copy(file, Path(target) / file.relative_to(origin), base)

        copy(ROOT / 'build/desktop/NativeWorkbench.exe', 'NativeWorkbench.exe')
        copy(ROOT / 'build/pipeline-checks/WindowsPipelineChecks.exe', 'WindowsPipelineChecks.exe')
        copy(ROOT / 'README-0.4.txt', 'README.txt')
        copy(ROOT / 'LICENSE', 'LICENSE')
        for name in ('PACK-FORMAT.txt', 'BUILD-0.4.txt', 'RESEARCH-WORKFLOWS.txt'):
            copy(ROOT / 'docs' / name, Path('docs') / name)
        copy(ROOT / 'tests/WINDOWS-PIPELINES.txt', 'docs/WINDOWS-PIPELINES.txt')
        for name, command in [('start-windows.cmd', 'start "" "%~dp0NativeWorkbench.exe"'),
                              ('check-windows.cmd', 'start "" "%~dp0NativeWorkbench.exe" --check'),
                              ('check-pipelines.cmd', '"%~dp0WindowsPipelineChecks.exe"\r\npause')]:
            (stage / name).write_bytes(('@echo off\r\nsetlocal DisableDelayedExpansion\r\n' + command + '\r\n').encode('ascii'))

        workflow_count = 0
        for pack in PACKS:
            relative = Path('packs') / f'{pack}-{VERSION}'
            tree(ROOT / relative, relative)
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(stage / relative / 'pack.ini', encoding='utf-8')
            declared = {'pack.ini', 'PACK-README.md'}
            for section in cfg.sections():
                if section.startswith(('tool:', 'asset:')):
                    item = cfg[section]
                    assert sha(stage / relative / item['path']) == item['sha256'], section
                    declared.add(item['path'].replace('\\', '/'))
                workflow_count += section.startswith('workflow:')
            for path in files_in(stage / relative):
                rel = path.relative_to(stage / relative).as_posix()
                assert rel in declared or rel.startswith('licenses/'), rel
        assert workflow_count == 43, workflow_count
        tree(ROOT / 'examples', 'examples')

        # Compact evidence only: exclude read/BAM/VCF data and failed trial runs.
        reports = {
            'validation/desktop-build-0.4.json': 'desktop-build.json',
            'validation/release-platform-correction.json': 'release-platform-correction.json',
            'validation/plans/research-final-20261002/plan.json': 'research-plan.json',
            'validation/plans/research-final-20261002/real-fastp-freebayes-plan.json': 'research-fastp-plan.json',
            'validation/results/research-final-20261002/validation-summary.json': 'research-pipelines.json',
            'validation/results/research-final-fastp-real-20261002/validation-summary.json': 'research-fastp-freebayes-yeast.json',
            'validation/results/research-final-20261002/decoded-fastq-comparisons.json': 'research-decoded-fastq.json',
            'validation/results/research-final-fastp-real-20261002/decoded-fastq-comparisons.json': 'research-fastp-decoded-fastq.json',
            'validation/results/cutadapt-oracle-final-20261002/cutadapt-fixture-validation.json': 'cutadapt-independent-oracle.json',
            'validation/results/cutadapt-observed-sequence-20261002/initial-failure-audit.json': 'earlier-run-audit.json',
            'validation/results/cutadapt-observed-sequence-20261002/report.json': 'cutadapt-observed-stages.json',
            'vendor-expanded/bwa/validation-summary.json': 'bwa-equivalence.json',
            'vendor-expanded/freebayes/validation/release-final/validation.json': 'freebayes-fixture.json',
            'vendor-expanded/freebayes/validation/yeast-contig-I/validation.json': 'freebayes-yeast-contig-I.json',
            'vendor-expanded/freebayes/validation/math-validation.json': 'freebayes-math.json',
            'fastp-build/validation-20261002-150749/fastp-validation.json': 'fastp-independent-and-yeast.json',
            'fastp-build/orphan-validation/results.json': 'fastp-optional-outputs.json',
            'fastp-build/paircheck-1.0.1-validation.json': 'paircheck-1.0.1.json',
        }
        for origin, target in reports.items():
            copy(ROOT / origin, Path('validation') / target)
        for name in ('research-pipelines.json', 'research-fastp-freebayes-yeast.json'):
            report = json.loads((stage / 'validation' / name).read_text())
            assert report['status'] == 'passed', name
            for tool, command in report['tools']['portable'].items():
                if tool == 'python':
                    continue  # Linux reference Python was used; Windows wheels remain unexecuted.
                released = stage / 'packs/research-variants-0.4.0/bin' / (tool + '.exe')
                assert sha(released) == report['executables_sha256'][command[-1]], tool

        # Ship source separately so Windows Extract All never expands deep build paths.
        for folder in ('desktop', 'tools', 'tests', 'src', 'include', 'platform_windows',
                       'scripts', 'docs', 'examples', 'vendor/archives', 'baselines/licenses',
                       'vendor-variant/archives', 'vendor-variant/licenses',
                       'vendor-expanded/archives', 'vendor-expanded/fastp-assets',
                       'vendor-expanded/fastp-licenses', 'vendor-expanded/cutadapt/archives',
                       'vendor-expanded/cutadapt/windows-wheels', 'vendor-expanded/cutadapt/linux-wheels',
                       'vendor-expanded/cutadapt/licenses', 'vendor-expanded/bwa/archives',
                       'vendor-expanded/bwa/licenses', 'vendor-expanded/freebayes/archives',
                       'vendor-expanded/freebayes/compat', 'vendor-expanded/freebayes/licenses',
                       'baselines/bin', 'packs/core-bio-0.2.0'):
            tree(ROOT / folder, folder, source)
        for name in ('LICENSE', 'README-0.4.txt', 'variant-protocol.txt', 'variant-provenance.json',
                     'build_variant.py', 'vendor/provenance.json',
                     'vendor-expanded/cutadapt/provenance.json', 'vendor-expanded/bwa/provenance.json',
                     'vendor-expanded/bwa/BUILD-NOTES.txt', 'vendor-expanded/fastp-provenance.json',
                     'vendor-expanded/fastp-offline-report.patch',
                     'vendor-expanded/freebayes/provenance.json', 'vendor-expanded/freebayes/release.json',
                     'vendor-expanded/freebayes/README.txt', 'vendor-expanded/freebayes/validate.py',
                     'vendor-expanded/freebayes/validate_region.py',
                     'baselines/build_upstream.py', 'baselines/benchmark_upstream.py', 'baselines/README.md'):
            copy(ROOT / name, name, source)
        for path in sorted((ROOT / 'validation').glob('*.py')):
            copy(path, Path('validation') / path.name, source)
        for pack in PACKS:
            copy(ROOT / 'packs' / f'{pack}-{VERSION}' / 'pack.ini', Path('pack-examples') / f'{pack}.ini', source)
        tree(stage / 'validation', 'validation/release-evidence', source)
        host = ROOT / 'build/bwfastq-linux'
        copy(host if host.exists() else ROOT / 'bin/linux/bwfastq', 'build/bwfastq-linux', source)
        copy(args.cosmo_source, 'variant-build/cosmopolitan-3.3.10.tar.gz', source)
        (stage / 'source').mkdir()
        archive(source, stage / 'source/native-workbench-source.zip')

        model = ROOT / 'build/model/test_pack_model'
        check = subprocess.run([str(model), *map(str, sorted((stage / 'packs').glob('*/pack.ini')))],
                               text=True, capture_output=True, check=True)
        release = {'version': VERSION, 'pack_model_check_stdout': check.stdout.strip(),
                   'pack_count': len(PACKS), 'workflow_count': workflow_count,
                   'native_windows_checks_available': 34,
                   'desktop_cross_compilation': 'passed',
                   'native_windows_execution_verified_for_0_4': False,
                   'native_visual_verification_for_0_4': False,
                   'note': 'Linux execution of portable tools is not native Windows execution. Run Check installation.'}
        (stage / 'validation/release-checks.json').write_text(json.dumps(release, indent=2) + '\n')
        files = [{'path': path.relative_to(stage).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)}
                 for path in files_in(stage)]
        (stage / 'manifest.json').write_text(json.dumps({'format_version': 2, 'name': 'Native Workbench',
            'version': VERSION, 'manifest_includes_itself': False, 'files': files}, indent=2) + '\n')
        # Typical Downloads extraction prefix, including the outer ZIP-named directory.
        windows_prefix = 'C:/Users/Tim_H/Downloads/native-workbench-0.4.0-windows/native-workbench/'
        longest = max(len(windows_prefix) + len(p.relative_to(stage).as_posix()) for p in files_in(stage))
        assert longest < 260, longest
        pending = destination.with_suffix('.zip.partial')
        archive(stage, pending)
        with zipfile.ZipFile(pending) as z:
            seen = set()
            for name in z.namelist():
                assert name.casefold() not in seen, name
                seen.add(name.casefold())
            manifest = json.loads(z.read('native-workbench/manifest.json'))
            for item in manifest['files']:
                data = z.read('native-workbench/' + item['path'])
                assert len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'], item['path']
        pending.replace(destination)
    print(json.dumps({'path': str(destination), 'bytes': destination.stat().st_size, 'sha256': sha(destination),
                      'files': len(files) + 1, 'packs': len(PACKS), 'workflows': workflow_count,
                      'longest_typical_extraction_path': longest, 'model_check': check.stdout.strip()}, indent=2))


if __name__ == '__main__':
    main()
