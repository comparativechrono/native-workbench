#!/usr/bin/env python3
"""Acquire exact published setup packs and prepare an untrusted catalogue preview.

This maintainer command does not install packs, execute tools, sign, publish,
generate keys, or change application trust. It fully checks every local archive
before writing a release map usable by publish_pack_catalog.py. Existing valid
downloads are reusable; incomplete downloads are deleted after any failure.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'workspace'))
from catalog import ID, VERSION, SHA
from pack_manager import MAX_ARCHIVE_BYTES, _download
from pack_security import require, strict_json, https_url
from publish_pack_catalog import make_payload
from validate_pack_release import inspect_release, sha_file

HOSTS = {'github.com', 'release-assets.githubusercontent.com'}
PREFIX = 'https://github.com/comparativechrono/workbench/releases/download/'
PROFILE_FIELDS = {'id', 'version', 'name', 'size', 'sha256', 'manifestSha256', 'starter'}


def read_lock(path, profile_path):
    """Bind reviewable acquisition URLs to the bundled selection profile."""
    lock = strict_json(Path(path).read_bytes())
    profile = strict_json(Path(profile_path).read_bytes())
    require(isinstance(lock, dict) and set(lock) ==
            {'schema', 'repository', 'sourceId', 'catalogUrl', 'allowedHosts', 'packs'},
            'Invalid setup asset lock')
    require(type(lock['schema']) is int and lock['schema'] == 1, 'Invalid lock schema')
    require(lock['repository'] == 'https://github.com/comparativechrono/workbench',
            'Unexpected setup repository')
    require(lock['allowedHosts'] == sorted(HOSTS), 'Unexpected setup download hosts')
    require(lock['sourceId'] == 'native-workbench-official', 'Unexpected setup source')
    require(lock['catalogUrl'] ==
            'https://raw.githubusercontent.com/comparativechrono/workbench/catalogue/catalogue.json',
            'Unexpected planned catalogue URL')
    require(isinstance(profile, dict) and set(profile) == {'schema', 'sourceId', 'packs'}
            and type(profile['schema']) is int and profile['schema'] == 1
            and profile['sourceId'] == lock['sourceId'], 'Invalid setup profile')
    require(isinstance(lock['packs'], list) and 1 <= len(lock['packs']) <= 2000,
            'Invalid setup pack count')
    expected, identities, names = [], set(), set()
    for row in lock['packs']:
        require(isinstance(row, dict) and set(row) == PROFILE_FIELDS | {'archive', 'downloadURL'},
                'Invalid locked pack fields')
        require(isinstance(row['id'], str) and ID.fullmatch(row['id']), 'Invalid pack ID')
        require(isinstance(row['version'], str) and VERSION.fullmatch(row['version']), 'Invalid pack version')
        require(isinstance(row['name'], str) and 0 < len(row['name']) <= 100
                and all(ord(c) >= 32 and ord(c) != 127 for c in row['name']), 'Invalid pack name')
        require(type(row['size']) is int and 0 < row['size'] <= MAX_ARCHIVE_BYTES, 'Invalid archive size')
        require(all(isinstance(row[key], str) and SHA.fullmatch(row[key])
                    for key in ('sha256', 'manifestSha256')), 'Invalid locked hash')
        require(type(row['starter']) is bool, 'Invalid Starter flag')
        require(row['id'] not in identities, 'Duplicate setup pack ID')
        identities.add(row['id'])
        filename = row['archive']
        require(isinstance(filename, str) and filename.endswith('.zip') and
                filename == Path(filename).name and '/' not in filename and '\\' not in filename
                and all(c.isascii() and (c.isalnum() or c in '.-_') for c in filename),
                'Unsafe archive filename')
        require(filename.casefold() not in names, 'Duplicate archive filename')
        names.add(filename.casefold())
        https_url(row['downloadURL'], HOSTS)
        require(row['downloadURL'] == PREFIX + 'pack-' + row['id'] + '-v' + row['version'] + '/' + filename,
                'Expected an immutable per-version pack release URL')
        expected.append({key: row[key] for key in PROFILE_FIELDS})
    require(profile['packs'] == expected, 'Setup profile and acquisition lock differ')
    return lock


def acquire(row, cache, allow_download):
    destination = Path(cache) / row['archive']
    reused = destination.exists()
    if reused:
        require(destination.is_file() and not destination.is_symlink(), 'Archive cache is not a regular file')
        require(destination.stat().st_size == row['size'] and sha_file(destination) == row['sha256'],
                'Cached archive differs from lock: ' + row['archive'])
    else:
        require(allow_download, 'Archive absent; supply --download to retrieve: ' + row['archive'])
        with tempfile.TemporaryDirectory(prefix='.setup-download-', dir=cache) as temporary:
            partial = Path(temporary) / 'download.zip'
            _download(row['downloadURL'], HOSTS, partial, row['size'],
                      expected_size=row['size'], expected_sha=row['sha256'])
            # Check all declared paths, file SHA-256s, ZIP CRCs and metadata before
            # moving a completed archive into the reusable cache.
            checked = inspect_release(partial)
            for key in ('id', 'version', 'size', 'sha256', 'manifestSha256'):
                require(checked[key] == row[key], 'Downloaded archive differs from lock: ' + key)
            require(not destination.exists(), 'Archive appeared during download')
            partial.replace(destination)
    checked = inspect_release(destination) if reused else checked
    for key in ('id', 'version', 'size', 'sha256', 'manifestSha256'):
        require(checked[key] == row[key], 'Archive differs from lock: ' + key)
    return {'id': row['id'], 'version': row['version'], 'archive': str(destination.resolve()),
            'downloadURL': row['downloadURL'], 'size': row['size'], 'sha256': checked['sha256'],
            'manifestSha256': checked['manifestSha256'], 'reusedArchive': reused,
            'wholeArchiveSha256Verified': True, 'memberCrcAndInventorySha256Verified': True,
            'manifestAndScientificMetadataValidated': True, 'executed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=ROOT / 'publishing/setup-assets.json')
    parser.add_argument('--profile', type=Path, default=ROOT / 'workspace/setup-profile.json')
    parser.add_argument('--archives', required=True, type=Path, help='Reusable archive cache directory')
    parser.add_argument('--output', required=True, type=Path, help='New output directory, never overwritten')
    parser.add_argument('--download', action='store_true', help='Explicitly permit missing archive downloads')
    parser.add_argument('--workers', type=int, default=3, choices=range(1, 9))
    args = parser.parse_args(argv)
    try:
        lock = read_lock(args.lock, args.profile)
        require(not args.output.exists(), 'Output directory exists; choose a new directory')
        args.archives.mkdir(parents=True, exist_ok=True)
        require(not any(p.is_symlink() for p in (args.archives, *args.archives.parents)),
                'Archive cache cannot use symlinks')
        verified = []
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            pending = {executor.submit(acquire, row, args.archives, args.download): row['id']
                       for row in lock['packs']}
            for future in as_completed(pending):
                row = future.result()
                verified.append(row)
                print(row['id'] + ': archive and every inventoried file verified', file=sys.stderr, flush=True)
        verified.sort(key=lambda row: row['id'])
        releases = [{'archive': row['archive'], 'downloadURL': row['downloadURL']} for row in verified]
        payload = make_payload([(Path(row['archive']), row['downloadURL']) for row in releases], HOSTS)
        report = {'schema': 1, 'preparedAt': datetime.now(timezone.utc).isoformat(),
                  'lockSha256': sha_file(args.lock), 'profileSha256': sha_file(args.profile),
                  'sourceId': lock['sourceId'], 'plannedCatalogUrl': lock['catalogUrl'],
                  'signed': False, 'uploaded': False, 'applicationTrustChanged': False,
                  'scope': 'Complete archive, member CRC, inventory SHA-256, manifest and metadata checks. No pack execution or native Windows claim.',
                  'packCount': len(verified), 'archiveBytes': sum(row['size'] for row in verified),
                  'packs': verified}
        args.output.mkdir(parents=True)
        for name, document in [('release-map.json', {'schema': 1, 'releases': releases}),
                               ('catalogue-preview.UNSIGNED.json', payload), ('preparation-report.json', report)]:
            with (args.output / name).open('xb') as stream:
                stream.write(json.dumps(document, indent=2, ensure_ascii=True).encode('ascii') + b'\n')
    except (OSError, ValueError, KeyError, UnicodeError, zipfile.BadZipFile) as exc:
        parser.exit(1, 'Setup catalogue preparation failed: ' + str(exc) + '\n')
    print(json.dumps({'output': str(args.output.resolve()), 'packs': len(verified), 'signed': False,
                      'uploaded': False, 'archiveBytes': report['archiveBytes']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
