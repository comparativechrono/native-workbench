#!/usr/bin/env python3
"""Recover exact upstream Bracken and private CPython build inputs; no analysis downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'tools/bracken/windows-lock.json'
CACHE = ROOT / 'build/bracken-inputs'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def obtain(pin, destination, fetch=False):
    destination = Path(destination)
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Reuse only exact verified upstream bytes; never inherit another pack's
        # modified runtime or a user Python installation.
        existing = ROOT / 'build/deseq2-inputs' / pin['filename']
        if existing.is_file() and existing.stat().st_size == pin['bytes'] and sha(existing) == pin['sha256']:
            shutil.copyfile(existing, destination)
        elif fetch:
            temporary = destination.with_suffix(destination.suffix + '.download')
            try:
                with urllib.request.urlopen(pin['url'], timeout=180) as response, temporary.open('wb') as output:
                    shutil.copyfileobj(response, output)
                if temporary.stat().st_size != pin['bytes'] or sha(temporary) != pin['sha256']:
                    raise ValueError('Downloaded build input differs from pinned size/SHA-256: ' + pin['filename'])
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            raise ValueError('Missing pinned build input; use --fetch: ' + str(destination))
    if destination.stat().st_size != pin['bytes'] or sha(destination) != pin['sha256']:
        raise ValueError('Build input differs from pinned size/SHA-256: ' + str(destination))
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=CACHE)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    for pin in [lock['upstreamSource'], *lock['python']]:
        path = obtain(pin, args.cache / pin['filename'], args.fetch)
        print(json.dumps({'file': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}))


if __name__ == '__main__':
    main()
