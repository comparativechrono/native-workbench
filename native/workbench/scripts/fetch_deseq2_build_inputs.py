#!/usr/bin/env python3
"""Fetch the reviewed, immutable R/Bioconductor/CRAN build input lock."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'tools/deseq2/windows-lock.json'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def obtain(pin, cache):
    path = cache / pin['filename']
    if path.is_file() and path.stat().st_size == pin['bytes'] and sha(path) == pin['sha256']:
        return path
    temporary = path.with_name(path.name + '.partial')
    digest = hashlib.sha256(); total = 0
    with urllib.request.urlopen(pin['url'], timeout=180) as response, temporary.open('wb') as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk); digest.update(chunk); total += len(chunk)
    if total != pin['bytes'] or digest.hexdigest() != pin['sha256']:
        temporary.unlink(missing_ok=True)
        raise ValueError('Upstream build input does not match its reviewed pin: ' + pin['filename'])
    temporary.replace(path)
    if path.stat().st_size != pin['bytes'] or sha(path) != pin['sha256']:
        raise ValueError('Build cache changed while fetching: ' + str(path))
    return path


def all_pins(lock):
    return list(lock['R'].values()) + lock['python'] + [p[k] for p in lock['packages'] for k in ('binary', 'source')]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, default=ROOT / 'build/deseq2-inputs')
    a = p.parse_args(); a.cache.mkdir(parents=True, exist_ok=True)
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        paths = list(executor.map(lambda pin: obtain(pin, a.cache), all_pins(lock)))
    print(json.dumps({'files': len(paths), 'verified': True, 'lockSha256': sha(LOCK)}, indent=2))

if __name__ == '__main__': main()
