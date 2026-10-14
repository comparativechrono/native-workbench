#!/usr/bin/env python3
"""Assemble an isolated Windows Cutadapt runtime from pinned upstream files.

No system installation, pip, PATH modification, or network access is required
on the user's Windows machine. Downloads are a build-time operation only.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'vendor-expanded/cutadapt'


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def extract(archive, destination):
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            p = PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in item.filename or ':' in item.filename:
                raise ValueError('Unsafe archive member')
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Archive symlinks are not permitted')
            output = destination.joinpath(*p.parts)
            if item.is_dir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(z.read(item))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='Download missing pinned build inputs')
    parser.add_argument('--linux-reference', action='store_true', help='Install the pinned Linux wheels into a local venv')
    args = parser.parse_args()
    provenance = json.loads((VENDOR / 'provenance.json').read_text())
    for record in provenance['files']:
        path = VENDOR / record['file']
        if not path.exists() and args.download:
            path.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(record['url'], timeout=120) as stream, path.open('wb') as target:
                shutil.copyfileobj(stream, target)
        if not path.exists() or digest(path) != record['sha256']:
            raise SystemExit('Missing or changed pinned input: ' + str(path))
    runtime = VENDOR / 'runtime'
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir()
    extract(VENDOR / 'archives/python-3.13.16-embed-amd64.zip', runtime)
    packages = runtime / 'packages'
    for wheel in sorted((VENDOR / 'windows-wheels').glob('*.whl')):
        extract(wheel, packages)
    # _pth enforces an isolated import path, including for multiprocessing child
    # interpreters; do not import site or consult global/user installations.
    (runtime / 'python313._pth').write_text('python313.zip\n.\npackages\n', encoding='ascii')
    licenses = VENDOR / 'licenses'
    licenses.mkdir(exist_ok=True)
    shutil.copy2(runtime / 'LICENSE.txt', licenses / 'Python-LICENSE.txt')
    for info in packages.glob('*.dist-info'):
        for path in info.rglob('*'):
            if path.is_file() and ('license' in path.name.lower() or 'copying' in path.name.lower() or 'notice' in path.name.lower()):
                output = licenses / info.name / path.relative_to(info)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, output)
    (licenses / 'RUNTIME-NOTES.txt').write_text(
        'Cutadapt 5.2 and its dependencies are unmodified upstream wheels.\n'
        'CPython 3.13.16 is the official Windows x64 embeddable distribution.\n'
        'The python313._pth configuration adds only the bundled packages directory.\n'
        'Workflows invoke -I -B -m cutadapt: isolated imports, no bytecode writes.\n'
        'Source archives, wheel hashes, versions and download URLs accompany the release.\n'
        'Native Windows execution must be checked with Check installation.\n')
    if args.linux_reference:
        venv = ROOT / 'expanded-build/cutadapt-linux'
        if not (venv / 'bin/python').exists():
            subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
        subprocess.run([str(venv / 'bin/python'), '-m', 'pip', 'install', '--no-index',
                        '--find-links', str(VENDOR / 'linux-wheels'),
                        'cutadapt==5.2', 'dnaio==1.2.4', 'xopen==2.1.0', 'isal==1.8.0',
                        'zlib-ng==1.0.0', 'backports.zstd==1.7.0'], check=True)
        subprocess.run([str(venv / 'bin/python'), '-I', '-B', '-m', 'cutadapt', '--version'], check=True)
    files = [p for p in runtime.rglob('*') if p.is_file()]
    print(json.dumps({'runtime': str(runtime), 'files': len(files), 'bytes': sum(p.stat().st_size for p in files),
                      'python_sha256': digest(runtime / 'python.exe')}, indent=2))


if __name__ == '__main__':
    main()
