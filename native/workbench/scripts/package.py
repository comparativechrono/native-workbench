#!/usr/bin/env python3
"""Create a bounded source/binary preview ZIP, excluding generated large data."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package(destination):
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bw-package-', dir=destination.parent) as temp:
        stage = Path(temp) / 'native-workbench'
        stage.mkdir()

        def copy(source, target=None):
            source = Path(source)
            output = stage / (target or source)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, output)

        for name in ('README.md', 'LICENSE', 'START-WINDOWS.cmd', 'CHECK-WINDOWS.cmd'):
            copy(name)
        for name in ('include', 'src', 'scripts', 'platform_windows', 'desktop', 'packs', 'tests', 'docs', 'examples'):
            for path in sorted((ROOT / name).rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.o', '.obj', '.tmp'):
                    copy(path.relative_to(ROOT))
        for path in sorted((ROOT / 'results').glob('*.json')):
            copy(path.relative_to(ROOT))
        for name in ('README.md', 'build_upstream.py', 'benchmark_upstream.py'):
            copy('baselines/' + name)
        for path in sorted((ROOT / 'baselines/licenses').rglob('*')):
            if path.is_file():
                copy(path.relative_to(ROOT))
        for folder in ('results', 'results-200000'):
            for path in sorted((ROOT / 'baselines' / folder).iterdir()):
                if path.suffix in ('.json', '.stderr'):
                    copy(path.relative_to(ROOT))

        mapping = {
            'build/desktop/NativeWorkbench.exe': 'NativeWorkbench.exe',
            'build/bwfastq-linux': 'bin/linux/bwfastq',
            'build/windows/bwfastq.exe': 'bin/windows/bwfastq.exe',
            'baselines/bin/seqtk-linux': 'bin/linux/seqtk',
            'baselines/bin/minimap2-linux': 'bin/linux/minimap2',
            'baselines/bin/ape-loader-linux': 'bin/linux/ape-loader',
            'baselines/bin/seqtk-cosmo.exe': 'bin/portable/seqtk.exe',
            'baselines/bin/minimap2-cosmo.exe': 'bin/portable/minimap2.exe',
        }
        for source, target in mapping.items():
            copy(source, target)
            copy(source)  # Keep source-tree paths used by reproducibility scripts.
        for name in ('bwfastq-linux-direct', 'fastq.module', 'fastq.elf', 'module.json'):
            copy('build/' + name)
        copy('build/windows/structural-report.json')
        copy('vendor/provenance.json')
        provenance = json.loads((ROOT / 'vendor/provenance.json').read_text())
        # Unpack exactly the pinned upstream archives, excluding local compiler debris.
        for source in provenance['source_archives']:
            relative = Path('vendor') / source['file']
            archive = ROOT / relative
            if digest(archive) != source['sha256']:
                raise RuntimeError('Source archive checksum mismatch: ' + str(relative))
            copy(relative)
            with tarfile.open(archive) as tar:
                for member in tar:
                    parts = PurePosixPath(member.name)
                    if parts.is_absolute() or '..' in parts.parts:
                        raise RuntimeError('Unsafe source archive path')
                    if not member.isfile():
                        if not member.isdir():
                            raise RuntimeError('Unexpected source archive member')
                        continue
                    output = stage / 'vendor' / member.name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as src, output.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
                    output.chmod(member.mode & 0o777)

        files = [{'path': p.relative_to(stage).as_posix(), 'bytes': p.stat().st_size,
                  'sha256': digest(p)} for p in sorted(stage.rglob('*')) if p.is_file()]
        manifest = {'format_version': 1, 'name': 'Native Workbench desktop preview', 'version': '0.2.1',
                    'desktop_native_windows_execution_verified': False,
                    'bundled_tools_windows_checks': 'User reported all 9 checks passed on 2026-10-01; see results/windows-user-observation.json',
                    'manifest_includes_itself': False, 'files': files}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        pending = destination.with_name(destination.name + '.partial')
        with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    z.write(path, path.relative_to(stage.parent))
        os.replace(pending, destination)
    print(json.dumps({'path': str(destination), 'bytes': destination.stat().st_size,
                      'sha256': digest(destination), 'files': len(files) + 1}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'native-workbench-0.2.1-windows.zip')
    package(parser.parse_args().output)
