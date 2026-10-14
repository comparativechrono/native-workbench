#!/usr/bin/env python3
"""Recover immutable GATK build inputs; downloads require explicit --fetch.

This is a developer build helper, never an analysis-time dependency. The seed
is the published Mutect2 pack, preserving its unchanged GATK local JAR, private
Windows Java runtime, path adaptation and corresponding source/licence material.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

from build_mutect2_compat import COMPILER_NAME, COMPILER_SHA256, COMPILER_URL
from fetch_mutect2_vendor import REFERENCE
from validate_pack_release import inspect_release

ROOT = Path(__file__).resolve().parents[1]
SEED_URL = 'https://github.com/comparativechrono/workbench/releases/download/pack-mutect2-v0.5.4/native-workbench-pack-mutect2-0.5.4.zip'
SEED_SHA = '25786d85b3679f172331142f890b1bffe5f5e77497b97eb91af855f2858ce08b'
STARTER_URL = 'https://github.com/comparativechrono/workbench/releases/download/app-v0.6.0/native-workbench-0.6.0-starter-windows.zip'
STARTER_SHA = '16fa802304c734b5721d838ff38b7e90ed36ccfc185a22239859cc3762af695a'
COSMO_URL = 'https://cosmo.zip/pub/cosmocc/cosmocc-3.3.10.zip'
COSMO_SHA = '00d61c1215667314f66e288c8285bae38cc6137fca083e5bba6c74e3a52439de'
LOADER_SHA = 'ad98161cba98163f6aa383595804489cec52a9ff3b902be16b29368e171ba359'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def recover(path, url, expected, fetch):
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(f'Missing {path}; use --fetch to download the pinned public build input')
        partial = path.with_name(path.name + '.partial')
        try:
            with urllib.request.urlopen(url, timeout=180) as response, partial.open('xb') as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            if sha(partial) != expected:
                raise ValueError('Downloaded SHA-256 differs: ' + path.name)
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    if path.is_symlink() or not path.is_file() or sha(path) != expected:
        raise ValueError('Build input SHA-256 differs: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/gatk-downloads')
    parser.add_argument('--output', type=Path, required=True, help='New empty directory for recovered inputs')
    parser.add_argument('--linux-reference', action='store_true')
    parser.add_argument('--released-app', action='store_true')
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError('Use a new output directory; recovery does not overwrite builds')
    items = [('mutect2.zip', SEED_URL, SEED_SHA, 'seed'),
             (COMPILER_NAME, COMPILER_URL, COMPILER_SHA256, 'jdk')]
    if args.linux_reference:
        name, (url, pin) = next(iter(REFERENCE.items()))
        items.append((name, url, pin, 'linux-jre'))
        items.append(('cosmocc-3.3.10.zip', COSMO_URL, COSMO_SHA, 'linux-tools'))
    if args.released_app:
        items.append(('starter.zip', STARTER_URL, STARTER_SHA, 'released-app'))
    for name, url, pin, _ in items:
        recover(args.cache / name, url, pin, args.fetch)
    seed = inspect_release(args.cache / 'mutect2.zip')
    if (seed['id'], seed['version']) != ('mutect2', '0.5.4'):
        raise ValueError('Unexpected seed pack identity')
    args.output.mkdir(parents=True)
    for name, _, _, destination in items:
        path = args.cache / name
        target = args.output / destination
        target.mkdir()
        if destination == 'linux-tools':
            with zipfile.ZipFile(path) as archive:
                names = [name for name in archive.namelist() if name.endswith('bin/ape-x86_64.elf')]
                if len(names) != 1:
                    raise ValueError('Expected exactly one pinned APE loader')
                data = archive.read(names[0])
            if hashlib.sha256(data).hexdigest() != LOADER_SHA:
                raise ValueError('Pinned APE loader differs')
            loader = target / 'ape-loader-linux'
            loader.write_bytes(data)
            loader.chmod(0o755)
        elif name.endswith('.zip'):
            # These exact ZIPs are SHA-pinned, and the seed additionally passed
            # the application's full bounded archive/schema/inventory audit.
            with zipfile.ZipFile(path) as archive:
                archive.extractall(target)
        else:
            with tarfile.open(path) as archive:
                archive.extractall(target, filter='data')
    evidence = {'schema': 1, 'purpose': 'Developer build inputs; no scientific or Windows execution',
                'inputs': [{'name': name, 'url': url, 'sha256': pin, 'bytes': (args.cache / name).stat().st_size}
                           for name, url, pin, _ in items]}
    (args.output / 'recovery.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
