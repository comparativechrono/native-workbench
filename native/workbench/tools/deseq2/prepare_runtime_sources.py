#!/usr/bin/env python3
"""Recover and package the separately published R-runtime corresponding sources.

Build-time network access is optional. This is never invoked during analysis.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(path, pin):
    return path.is_file() and path.stat().st_size == pin['bytes'] and sha(path) == pin['sha256']


def obtain(root, pin, fetch):
    relative = PurePosixPath(pin['path'])
    if relative.is_absolute() or '..' in relative.parts or '\\' in pin['path']:
        raise ValueError('Unsafe source-lock path')
    target = root.joinpath(*relative.parts)
    if verify(target, pin):
        return target
    if not fetch:
        raise ValueError('Missing or changed source input: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.download')
    errors = []
    for url in pin['urls']:
        if not url.startswith('https://'):
            continue
        try:
            with urllib.request.urlopen(url, timeout=90) as response, temporary.open('wb') as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
            if not verify(temporary, pin):
                raise ValueError('Source hash/size mismatch')
            temporary.replace(target)
            return target
        except Exception as exc:
            errors.append(str(exc))
            temporary.unlink(missing_ok=True)
    raise ValueError('Cannot recover ' + pin['path'] + ': ' + '; '.join(errors))


def add(zipper, source, name):
    info = zipfile.ZipInfo('r-runtime-sources/' + name, (2026, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_STORED if name.endswith(('.xz', '.gz', '.bz2', '.zip')) else zipfile.ZIP_DEFLATED
    with source.open('rb') as stream, zipper.open(info, 'w', force_zip64=True) as output:
        shutil.copyfileobj(stream, output, 1024 * 1024)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    lock_path = HERE / 'r-runtime-source-lock.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    if args.destination.exists():
        raise ValueError('Destination must not exist')
    inputs = [(pin, obtain(args.cache, pin, args.fetch)) for pin in lock['files']]
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.destination, 'x', allowZip64=True) as zipper:
        for pin, source in inputs:
            add(zipper, source, pin['path'])
        for name in ('r-runtime-source-lock.json', 'R-RUNTIME-SOURCES.md', 'prepare_runtime_sources.py'):
            add(zipper, HERE / name, name)
    # Verify the actual published archive members, not just the input cache.
    with zipfile.ZipFile(args.destination) as zipper:
        for pin, source in inputs:
            with zipper.open('r-runtime-sources/' + pin['path']) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != pin['sha256']:
                    raise ValueError('Source archive member changed')
    evidence = {'schema': 1, 'name': args.destination.name, 'bytes': args.destination.stat().st_size,
                'sha256': sha(args.destination), 'sourceLockSha256': sha(lock_path),
                'sourceFiles': len(inputs), 'RVersion': lock['RVersion'],
                'correspondingRuntimeSha256': lock['correspondingRuntimeSha256'],
                'scope': 'Corresponding third-party sources, R-project patches and build recipes for the private Windows R runtime; the pack itself contains R, Python and R-package sources.'}
    args.destination.with_suffix('.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
