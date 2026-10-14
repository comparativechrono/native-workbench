#!/usr/bin/env python3
"""Recover SHA-pinned IQ-TREE/private-Python inputs; never used during analysis."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'tools/iqtree/input-lock.json'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def recover(cache, fetch=False):
    cache.mkdir(parents=True, exist_ok=True)
    lock = json.loads(LOCK.read_text())
    for item in lock['inputs']:
        path = cache / item['filename']
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            if not fetch:
                raise FileNotFoundError('Missing pinned build input; use --fetch: ' + str(path))
            partial = path.with_suffix(path.suffix + '.partial')
            try:
                with urllib.request.urlopen(item['url'], timeout=180) as response, partial.open('xb') as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
                if sha(partial) != item['sha256'] or partial.stat().st_size != item['bytes']:
                    raise ValueError('Downloaded build input differs: ' + item['filename'])
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
        if path.is_symlink() or sha(path) != item['sha256'] or path.stat().st_size != item['bytes']:
            raise ValueError('Pinned input differs: ' + str(path))
    return lock


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / 'build/iqtree-inputs')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    print(json.dumps(recover(args.cache, args.fetch), indent=2))
