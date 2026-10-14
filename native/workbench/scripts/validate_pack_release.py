#!/usr/bin/env python3
"""Audit an independent pack ZIP without extracting or executing its contents."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'workspace'))
from catalog import ID, VERSION, SHA, _relative, parse_pack, _validate_workbench_schema
from pack_security import PackError, require, strict_json
from pack_manager import _archive_envelope

MAX_BYTES = 1024 ** 3
MAX_FILES = 2000


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inspect_release(path):
    """Return catalogue fields after auditing envelope, inventory and manifests.

    This is a static integrity check. It does not run the scientific self-checks
    or establish that a native executable works on Windows.
    """
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Expected a regular pack ZIP')
    require(0 < path.stat().st_size <= MAX_BYTES + 8 * 1024 * 1024, 'Pack ZIP exceeds the installation limit')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        require(0 < len(entries) <= MAX_FILES + 2, 'Pack ZIP has too many entries')
        files, names, total = {}, set(), 0
        for info in entries:
            name = info.filename
            require(name and name == info.orig_filename and '\x00' not in name, 'Unsafe ZIP filename')
            _relative(name[:-1] if info.is_dir() else name)
            require(not info.flag_bits & 1, 'Encrypted ZIP entries are unsupported')
            require(stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR) and not info.external_attr & 0x400, 'Pack ZIP cannot contain links or special files')
            require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Unsupported ZIP compression')
            require('\\' not in name, 'Pack ZIP paths must use forward slashes')
            folded = name.rstrip('/').casefold()
            require(folded not in names, 'Duplicate or case-colliding ZIP entry')
            names.add(folded)
            if name == 'pack/':
                require(info.is_dir(), 'pack must be a directory')
                continue
            require(name == 'workbench-pack.json' or name.startswith('pack/'), 'Unexpected file outside pack/')
            if name.startswith('pack/'):
                relative = name[5:].rstrip('/')
                _relative(relative)
            if info.is_dir():
                require(info.file_size == 0, 'Directory ZIP entry contains data')
                continue
            total += info.file_size
            require(total <= MAX_BYTES + 2 * 1024 * 1024, 'Pack expands beyond the installation limit')
            files[name] = info
        require('workbench-pack.json' in files and 'pack/pack.ini' in files, 'Missing pack envelope or manifest')
        require(files['workbench-pack.json'].file_size <= 2 * 1024 * 1024, 'Pack envelope is too large')
        envelope = strict_json(archive.read('workbench-pack.json'))
        # Share application compatibility and inventory rules. Additional checks
        # below audit bytes directly, without an expanded duplicate of the pack.
        _archive_envelope(envelope)
        expected_keys = {'schema', 'id', 'version', 'packApi', 'minAppVersion', 'platform', 'manifestSha256', 'files'}
        require(isinstance(envelope, dict) and set(envelope) == expected_keys, 'Invalid pack envelope fields')
        require(type(envelope['schema']) is int and envelope['schema'] == 1, 'Unsupported pack envelope schema')
        require(type(envelope['packApi']) is int and envelope['packApi'] == 1, 'Unsupported pack API')
        require(envelope['platform'] == 'windows-x86_64', 'Unsupported platform')
        for key, pattern in [('id', ID), ('version', VERSION), ('minAppVersion', VERSION), ('manifestSha256', SHA)]:
            require(isinstance(envelope[key], str) and pattern.fullmatch(envelope[key]), 'Invalid envelope ' + key)
        require(isinstance(envelope['files'], list) and 1 <= len(envelope['files']) <= MAX_FILES, 'Invalid file inventory')
        inventory, inventory_folded = {}, set()
        for item in envelope['files']:
            require(isinstance(item, dict) and set(item) == {'path', 'size', 'sha256'}, 'Invalid inventory entry')
            relative = item['path']
            require(isinstance(relative, str) and '\\' not in relative, 'Invalid inventory path')
            _relative(relative)
            require(relative.casefold() not in inventory_folded, 'Duplicate inventory path')
            inventory_folded.add(relative.casefold())
            require(type(item['size']) is int and 0 <= item['size'] <= MAX_BYTES, 'Invalid inventory size')
            require(isinstance(item['sha256'], str) and SHA.fullmatch(item['sha256']), 'Invalid inventory hash')
            inventory[relative] = item
        require(set(files) == {'workbench-pack.json'} | {'pack/' + name for name in inventory}, 'Archive and inventory differ')
        allowed_directories = {'pack'}
        for relative in inventory:
            parts = ('pack/' + relative).split('/')
            allowed_directories.update('/'.join(parts[:index]) for index in range(1, len(parts)))
        require(all(info.filename[:-1] in allowed_directories for info in entries if info.is_dir()), 'ZIP contains undeclared directories')
        directories = set()
        for relative in inventory:
            parent = Path(relative).parent
            while parent.as_posix() != '.':
                directories.add(parent.as_posix().casefold())
                parent = parent.parent
        require(not directories.intersection(inventory_folded), 'A pack file collides with a directory')
        require(len(inventory) + len(directories) <= MAX_FILES, 'Pack files and implied directories exceed the installation limit')
        for relative, item in inventory.items():
            info = files['pack/' + relative]
            require(info.file_size == item['size'], 'Inventory size differs: ' + relative)
            digest = hashlib.sha256()
            with archive.open(info) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            require(digest.hexdigest() == item['sha256'], 'Inventory hash differs: ' + relative)
        require(inventory['pack.ini']['sha256'] == envelope['manifestSha256'], 'Manifest hash differs from envelope')
        require(inventory['pack.ini']['size'] <= 8 * 1024 * 1024, 'Manifest is too large')
        pack = parse_pack(archive.read('pack/pack.ini').decode('utf-8-sig'))
        require(pack['id'] == envelope['id'] and pack['version'] == envelope['version'], 'Manifest identity differs from envelope')
        declared = {'pack.ini', 'pack-readme.md', 'pack-readme.txt', 'readme.txt'}
        for item in [*pack['tools'].values(), *pack['assets'].values()]:
            require(item['path'] in inventory and inventory[item['path']]['sha256'] == item['sha256'], 'Declared file absent or hash differs: ' + item['path'])
            require(inventory[item['path']]['size'] <= 512 * 1024 * 1024, 'Runtime file exceeds native import limit')
            declared.add(item['path'].lower())
        require(all(name.lower() in declared or name.lower().startswith('licenses/') for name in inventory), 'Undeclared runtime file in pack')
        category = 'Other tools'
        schema_asset = pack['assets'].get('workbench-schema')
        if schema_asset:
            require(inventory[schema_asset['path']]['size'] <= 2 * 1024 * 1024, 'Scientific metadata is too large')
            metadata = _validate_workbench_schema(strict_json(archive.read('pack/' + schema_asset['path'])), pack)
            categories = sorted({item['category'] for item in metadata.values()})
            category = categories[0] if len(categories) == 1 else 'Multiple categories'
    return {
        'id': pack['id'], 'name': pack['name'], 'version': pack['version'],
        'toolVersions': {key: item['version'] for key, item in pack['tools'].items()},
        'description': pack['description'], 'category': category,
        'platform': envelope['platform'], 'packApi': envelope['packApi'],
        'minAppVersion': envelope['minAppVersion'], 'size': path.stat().st_size,
        'sha256': sha_file(path), 'manifestSha256': envelope['manifestSha256'],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect_release(args.archive)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, UnicodeError) as exc:
        parser.exit(1, 'Pack validation failed: ' + str(exc) + '\n')
    print(json.dumps({'validation': 'static-integrity-only', 'pack': result}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
