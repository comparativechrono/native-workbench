#!/usr/bin/env python3
"""Measure a proposed full bundle without downloading or building its payload.

Input is a saved live-release metadata snapshot with a ``packs`` array. Numeric
HTTP ranges retrieve each published ZIP's directory and small API envelope;
payload sizes are reconciled against that envelope. This is sizing evidence,
not full-archive integrity verification or Windows execution evidence.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile


MAX_METADATA_RANGE = 4 * 1024 * 1024
MAX_TRANSFER_PER_ARCHIVE = 8 * 1024 * 1024
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def safe_path(name):
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
            'Invalid ZIP member path')
    require(all(part not in ('', '.', '..') for part in name.split('/')),
            'Unsafe ZIP member path: ' + name)
    return name


class RemoteZip(io.RawIOBase):
    """Seekable, bounded, cached byte ranges; a server ignoring Range is rejected."""
    def __init__(self, url, size, timeout=35):
        require(url.startswith('https://github.com/'), 'Expected a public GitHub release URL')
        require(type(size) is int and size > 0, 'Invalid published archive size')
        self.url, self.size, self.timeout = url, size, timeout
        self.position = 0
        self.cache = []
        self.transferred_bytes = 0
        self.requests = []
        # 65,557 covers the EOCD plus the maximum legal ZIP comment.
        self._fetch(max(0, size - 65557), size)
        self._fetch(0, min(size, 512 * 1024))

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        target = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        require(whence in (0, 1, 2) and 0 <= target <= self.size, 'ZIP seek leaves the archive')
        self.position = target
        return target

    def _fetch(self, start, end):
        for at, data in self.cache:
            if at <= start and end <= at + len(data):
                return data[start-at:end-at]
        length = end-start
        require(0 <= start < end <= self.size and length <= MAX_METADATA_RANGE,
                'Unexpectedly large ZIP metadata read')
        require(self.transferred_bytes + length <= MAX_TRANSFER_PER_ARCHIVE,
                'ZIP metadata transfer exceeded its budget')
        request = urllib.request.Request(self.url, headers={
            'Range': f'bytes={start}-{end-1}', 'Accept-Encoding': 'identity',
            'User-Agent': 'NativeWorkbench-bundle-sizing/1'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    require(response.status == 206, 'Server did not honour the numeric byte range')
                    expected = f'bytes {start}-{end-1}/{self.size}'
                    require(response.headers.get('Content-Range') == expected,
                            'Content-Range differs from the published asset size/request')
                    require(response.headers.get('Content-Encoding', 'identity') == 'identity',
                            'Unexpected HTTP content encoding')
                    data = response.read(length + 1)
                    require(len(data) == length, 'Incomplete or oversized HTTP byte range')
                self.cache.append((start, data))
                self.transferred_bytes += length
                self.requests.append({'start': start, 'end_inclusive': end-1, 'bytes': length,
                                      'status': 206, 'attempts': attempt+1})
                return data
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 2:
                    raise
                time.sleep(attempt+1)
        raise AssertionError('unreachable')

    def read(self, size=-1):
        end = self.size if size is None or size < 0 else min(self.size, self.position+size)
        if end == self.position:
            return b''
        data = self._fetch(self.position, end)
        self.position = end
        return data


def zip_members(zipped):
    members, folded = {}, set()
    for info in zipped.infolist():
        if info.is_dir():
            safe_path(info.filename.rstrip('/'))
            continue
        safe_path(info.filename)
        require(info.filename.casefold() not in folded, 'Duplicate/case-colliding ZIP member')
        require(not info.flag_bits & 1, 'Encrypted ZIP member is unsupported')
        require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                'Unexpected ZIP compression method')
        folded.add(info.filename.casefold())
        members[info.filename] = info
    return members


def measure_pack(entry):
    asset = entry['primary_asset']
    remote = RemoteZip(asset['download_url'], asset['bytes'])
    with zipfile.ZipFile(remote) as zipped:
        members = zip_members(zipped)
        require('workbench-pack.json' in members, 'Missing pack API envelope')
        envelope_info = members['workbench-pack.json']
        require(envelope_info.file_size <= MAX_ENVELOPE_BYTES and
                envelope_info.compress_size <= MAX_ENVELOPE_BYTES, 'Oversized pack API envelope')
        envelope_raw = zipped.read(envelope_info)  # zipfile checks this member's CRC.
        envelope = strict_json(envelope_raw)
        require(envelope.get('schema') == 1 and envelope.get('packApi') == 1 and
                envelope.get('platform') == 'windows-x86_64', 'Unsupported pack API envelope')
        require((envelope.get('id'), envelope.get('version')) == (entry['id'], entry['version']),
                'Envelope identity differs from release metadata')
        require(isinstance(envelope.get('files'), list) and 1 <= len(envelope['files']) <= 2000,
                'Invalid envelope inventory')
        inventory = {}
        for item in envelope['files']:
            require(isinstance(item, dict) and set(item) == {'path', 'size', 'sha256'},
                    'Invalid pack inventory entry')
            name = safe_path(item['path'])
            require(name not in inventory and type(item['size']) is int and item['size'] >= 0 and
                    re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None,
                    'Invalid duplicate/file-size/hash inventory entry')
            inventory[name] = item
        require(set(members) == {'workbench-pack.json', *('pack/'+name for name in inventory)},
                'ZIP payload paths differ from the envelope inventory')
        for name, item in inventory.items():
            require(members['pack/'+name].file_size == item['size'],
                    'ZIP uncompressed size differs from envelope: ' + name)
        require('pack.ini' in inventory and inventory['pack.ini']['sha256'] == envelope['manifestSha256'],
                'Manifest identity differs between envelope and file inventory')
        payload = [members['pack/'+name] for name in inventory]
        receipt = {key: envelope[key] for key in
                   ('schema', 'id', 'version', 'packApi', 'minAppVersion', 'platform', 'manifestSha256')}
        # Match current PackManager's receipt serialization exactly.
        receipt_size = len(json.dumps(receipt, sort_keys=True).encode('utf-8'))
        result = {
            'id': entry['id'], 'version': entry['version'], 'release_url': entry['release_url'],
            'included_in_starter': entry['included_in_starter'], 'primary_asset': asset,
            'manifest_sha256': envelope['manifestSha256'],
            'expanded_payload_bytes': sum(i.file_size for i in payload),
            'compressed_payload_bytes': sum(i.compress_size for i in payload),
            'payload_files': len(payload),
            'license_tree_bytes': sum(i.file_size for i in payload if i.filename.startswith('pack/licenses/')),
            'runtime_directory_bytes': sum(i.file_size for i in payload if i.filename.startswith('pack/runtime/')),
            'compatibility_receipt_bytes': receipt_size,
            'envelope_bytes': len(envelope_raw), 'envelope_sha256': hashlib.sha256(envelope_raw).hexdigest(),
            'verification': {'envelope_crc': True, 'directory_paths_and_sizes_match_envelope': True,
                             'payload_hashes_verified': False, 'whole_archive_sha256_verified': False,
                             'whole_archive_crc_verified': False},
            'http_range_bytes_received': remote.transferred_bytes, 'http_ranges': remote.requests,
        }
        # Retain only the three tiny starter inventories for overlap verification.
        if entry['included_in_starter']:
            result['_starter_inventory'] = inventory
        return result


def measure_starter(path, expected_sha, packs):
    actual_sha = sha256_file(path)
    require(actual_sha == expected_sha, 'Local starter differs from its supplied SHA-256')
    with zipfile.ZipFile(path) as zipped:
        members = zip_members(zipped)
        require(zipped.testzip() is None, 'Local starter failed ZIP CRC verification')
        manifest = strict_json(zipped.read('native-workbench/manifest.json'))
        require(manifest.get('ownership') == 'core' and manifest.get('pack_management') == 'independent',
                'Expected an independent-core starter')
        pins = {p['id']: p for p in manifest['starter_packs']}
        starter_packs = [p for p in packs if p['included_in_starter']]
        require(set(pins) == {p['id'] for p in starter_packs}, 'Starter selection differs from metadata')
        for pack in starter_packs:
            pin = pins[pack['id']]
            require((pin['version'], pin['manifestSha256']) == (pack['version'], pack['manifest_sha256']),
                    'Starter pack pin differs from the current published pack')
            prefix = 'native-workbench/' + pin['folder'] + '/'
            inventory = pack.pop('_starter_inventory')
            require({name[len(prefix):] for name in members if name.startswith(prefix)} == set(inventory),
                    'Starter pack file set differs from published envelope')
            for name, item in inventory.items():
                info = members[prefix+name]
                require(info.file_size == item['size'] and
                        hashlib.sha256(zipped.read(info)).hexdigest() == item['sha256'],
                        'Starter pack content differs from published envelope: ' + name)
        return {
            'file': path.name, 'version': manifest['version'], 'download_bytes': path.stat().st_size,
            'sha256': actual_sha, 'expanded_bytes': sum(i.file_size for i in members.values()),
            'compressed_payload_bytes': sum(i.compress_size for i in members.values()),
            'files': len(members), 'starter_pack_count': len(pins),
            'whole_archive_sha256_verified': True, 'whole_archive_crc_verified': True,
            'starter_payloads_match_published_pack_envelopes': True,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True, type=Path)
    parser.add_argument('--starter', required=True, type=Path)
    parser.add_argument('--starter-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=4, choices=range(1, 7))
    args = parser.parse_args()
    require(re.fullmatch('[0-9a-f]{64}', args.starter_sha256) is not None, 'Invalid starter SHA-256')
    metadata = strict_json(args.metadata.read_bytes())
    entries = metadata['packs']
    require(len({p['id'] for p in entries}) == len(entries), 'Duplicate current pack ID')
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(measure_pack, entry): entry['id'] for entry in entries}
        for future in as_completed(futures):
            pack = future.result()
            results.append(pack)
            print(f"{pack['id']}: {pack['expanded_payload_bytes']:,} installed bytes; "
                  f"{pack['http_range_bytes_received']:,} metadata bytes read", file=sys.stderr, flush=True)
    results.sort(key=lambda p: p['id'])
    starter = measure_starter(args.starter, args.starter_sha256, results)
    optional = [pack for pack in results if not pack['included_in_starter']]
    report = {
        'schema': 'native-workbench-full-bundle-sizing/1',
        'measured_at': datetime.now(timezone.utc).isoformat(),
        'metadata_snapshot': {'file': args.metadata.name, 'sha256': sha256_file(args.metadata),
                              'checked_on': metadata.get('checked_on'), 'url': metadata.get('metadata_url')},
        'starter': starter, 'packs': results,
        'totals': {
            'all_pack_count': len(results), 'additional_pack_count': len(optional),
            'all_pack_download_bytes': sum(p['primary_asset']['bytes'] for p in results),
            'additional_pack_download_bytes': sum(p['primary_asset']['bytes'] for p in optional),
            'starter_plus_additional_zip_download_bytes': starter['download_bytes'] + sum(p['primary_asset']['bytes'] for p in optional),
            'all_pack_expanded_payload_bytes': sum(p['expanded_payload_bytes'] for p in results),
            'additional_pack_expanded_payload_bytes': sum(p['expanded_payload_bytes'] for p in optional),
            'full_install_payload_bytes': starter['expanded_bytes'] + sum(p['expanded_payload_bytes'] for p in optional),
            'full_install_payload_files': starter['files'] + sum(p['payload_files'] for p in optional),
            'additional_pack_receipt_bytes': sum(p['compatibility_receipt_bytes'] for p in optional),
            'full_install_with_additional_receipts_bytes': starter['expanded_bytes'] + sum(p['expanded_payload_bytes'] + p['compatibility_receipt_bytes'] for p in optional),
            'all_pack_license_tree_bytes': sum(p['license_tree_bytes'] for p in results),
            'combined_compressed_payload_bytes': starter['compressed_payload_bytes'] + sum(p['compressed_payload_bytes'] for p in optional),
            'remote_metadata_bytes_received': sum(p['http_range_bytes_received'] for p in results),
        },
        'scope': {
            'method': 'Explicit HTTP 206 numeric byte ranges read ZIP directories and CRC-checked pack envelopes. Every payload path and uncompressed size is reconciled to the published envelope. Local starter is fully SHA-256/CRC checked, and its three pack payloads are hash-matched to their published envelopes. Each current pack is counted once.',
            'compressed_size': 'Starter plus the additional optional published ZIPs is an exact sum of current download sizes, not the exact size of a newly built combined ZIP. Combined compressed payload bytes omit ZIP headers, filenames and new bundle metadata; no combined archive was built or recompressed.',
            'installed_size': 'Logical file lengths, not filesystem allocation or peak extraction space. Includes unchanged published licenses/source trees and bundled runtimes; excludes separately published source/evidence companions, user references/databases, results, and per-run expanded runtimes. Additional manager receipt bytes are listed separately; a bundle inventory has not been designed.',
            'limits': 'Remote payloads were not downloaded, CRC-tested or hashed. GitHub digest fields are metadata, not independently verified archive hashes in this measurement. No all-pack native execution, startup timing or full-bundle coexistence check was performed. No application, pack, packaging default or release was changed.',
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['totals'], indent=2))


if __name__ == '__main__':
    main()
