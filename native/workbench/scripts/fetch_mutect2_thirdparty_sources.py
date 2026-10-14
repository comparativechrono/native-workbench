#!/usr/bin/env python3
"""Verify exact GATK dependency source/notice inventory, optionally restoring or downloading.

No runtime files are modified. Downloaded bytes must match the pinned inventory.
Generated metadata is retained in the source delivery or restored from pack licenses.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'vendor-expanded' / 'gatk-thirdparty'
INVENTORY_NAME = 'gatk-thirdparty-source-inventory.json'
INVENTORY_SHA256 = '9b7390d1da5e84da71b826a88c62d324a55e51b5d2172bb5cec91626fc40cd5e'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--download', action='store_true')
    p.add_argument('--directory', type=Path, default=DEFAULT)
    p.add_argument('--restore-sources', type=Path,
                   help='Flat licenses directory from an official Mutect2 pack')
    a = p.parse_args()
    a.directory.mkdir(parents=True, exist_ok=True)
    inventory_path = a.directory / INVENTORY_NAME
    if not inventory_path.exists():
        for source_dir in [a.restore_sources, DEFAULT]:
            if source_dir and (source_dir / INVENTORY_NAME).is_file():
                source = source_dir / INVENTORY_NAME
                if digest(source) != INVENTORY_SHA256:
                    raise ValueError('Inventory checksum mismatch: ' + str(source))
                shutil.copyfile(source, inventory_path)
                break
    if not inventory_path.exists() or digest(inventory_path) != INVENTORY_SHA256:
        raise ValueError('Missing or modified pinned dependency inventory; restore it from source delivery/pack licenses')
    inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
    seen = set()
    for item in inventory['files']:
        name = item['name']
        if name in seen or Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Unsafe or duplicate inventory filename')
        seen.add(name)
        target = a.directory / name
        if not target.exists():
            for source_dir in [a.restore_sources, DEFAULT]:
                if source_dir and (source_dir / name).is_file():
                    source = source_dir / name
                    if digest(source) != item['sha256']:
                        raise ValueError('Restore checksum mismatch: ' + name)
                    shutil.copyfile(source, target)
                    break
        if not target.exists():
            if not a.download or not item.get('url'):
                raise FileNotFoundError('Missing ' + name + '; use --download for upstream files or --restore-sources for retained metadata')
            temporary = target.with_name(name + '.partial')
            try:
                request = urllib.request.Request(item['url'], headers={'User-Agent': 'Native-Workbench-source-fetch/0.5.4'})
                with urllib.request.urlopen(request, timeout=180) as response, temporary.open('wb') as stream:
                    shutil.copyfileobj(response, stream, length=1024 * 1024)
                if temporary.stat().st_size != item['bytes'] or digest(temporary) != item['sha256']:
                    raise ValueError('Downloaded checksum mismatch: ' + name)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        if target.is_symlink() or target.stat().st_size != item['bytes'] or digest(target) != item['sha256']:
            raise ValueError('Existing source/notice checksum mismatch: ' + name)
    print(json.dumps({'verifiedFiles': len(seen), 'sourceArchives': inventory['sourceArchiveCount'],
                      'bytes': sum(x['bytes'] for x in inventory['files']), 'inventorySha256': INVENTORY_SHA256}))


if __name__ == '__main__':
    main()
