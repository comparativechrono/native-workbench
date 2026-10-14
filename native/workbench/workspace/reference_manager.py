"""Explicit public-reference retrieval and an offline local reference library.

The provider resolves release-pinned URLs; clients can only download a cached
selection. Files are streamed, checked and expanded inside a private directory,
then published together with their provenance. No network is used by startup,
snapshot, local resolution or analysis-time provenance lookup.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
import zlib

from pack_manager import filesystem_path, ordinary_windows_path
from pack_security import strict_json, PackError
from reference_provider import EnsemblArchiveProvider, ReferenceCancelled
from reference_transfer import ReferenceTransferMixin, ReferencePaused
from reference_library import ReferenceLibraryMixin

CHUNK = 1024 * 1024
MAX_DOWNLOAD_BYTES = 100 * 1024**3
MAX_EXPANDED_BYTES = 500 * 1024**3
MAX_REGISTRY_BYTES = 16 * 1024**2
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_RECORDS = 10000
MAX_SNAPSHOT_LOCAL_BYTES = 3 * 1024**2
DISK_FLOOR = 16 * 1024**2
KINDS = {'genome', 'annotation', 'cdna', 'ncrna', 'protein'}
SHA = re.compile(r'[0-9a-f]{64}\Z')
IDENTITY = re.compile(r'[0-9a-f]{32}\Z')


class ReferenceError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ReferenceError(message)


def _cancelled(cancel):
    if cancel is not None and (cancel.is_set() if hasattr(cancel, 'is_set') else cancel()):
        raise ReferenceCancelled('Reference download cancelled; no incomplete reference was added.')


def _event(callback, phase, **fields):
    if callback:
        callback({'phase': phase, **fields})


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _ordinary(path):
    return ordinary_windows_path(path) if os.name == 'nt' else str(path)


def _no_links(path):
    """Reject symlinks and Windows reparse points, including parent junctions."""
    path = filesystem_path(path)
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        _require(not stat.S_ISLNK(info.st_mode) and
                 not getattr(info, 'st_file_attributes', 0) & 0x400,
                 'Reference locations cannot use symbolic links or junctions.')
    return path


def _directory(path, create=False):
    path = _no_links(path)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    _require(path.is_dir(), 'Choose an existing reference destination folder.')
    return _no_links(path)


def _filename(value):
    _require(isinstance(value, str) and 1 <= len(value) <= 180 and
             value not in {'.', '..'} and not any(c in value for c in '/\\:*?"<>|') and
             all(ord(c) >= 32 and ord(c) != 127 for c in value) and
             not value.endswith((' ', '.')), 'Provider supplied an unsafe reference filename.')
    _require(value.split('.')[0].upper() not in
             {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
              *(f'LPT{i}' for i in range(1, 10))}, 'Provider supplied a reserved filename.')
    return value


def _read_json(path, limit):
    path = _no_links(path)
    _require(path.is_file() and path.stat().st_size <= limit, 'Reference metadata is missing or too large.')
    try:
        raw = path.read_bytes()
        _require(len(raw) <= limit, 'Reference metadata is too large.')
        return strict_json(raw), raw
    except PackError as exc:
        raise ReferenceError('Reference metadata is damaged; existing files were preserved.') from exc


def _atomic_json(path, value):
    raw = _json_bytes(value)
    _require(len(raw) <= MAX_REGISTRY_BYTES, 'The local reference library is full.')
    _no_links(path)
    fd, name = tempfile.mkstemp(prefix='_write-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _no_links(path)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _bsd_update(value, block):
    # Ensembl CHECKSUMS uses BSD sum -r over compressed bytes, not MD5/SysV.
    for byte in block:
        value = (((value >> 1) | ((value & 1) << 15)) + byte) & 0xffff
    return value


def _check_format(prefix, kind, filename):
    # GTF attributes and FASTA descriptions can contain UTF-8. Validate the
    # structural ASCII bytes only, without decoding a potentially partial prefix.
    lines = [line for line in bytes(prefix).splitlines() if line.strip()]
    if kind == 'annotation':
        rows = [line for line in lines if not line.startswith(b'#')]
        _require(bool(rows), 'Downloaded annotation contains no GTF feature rows.')
        fields = rows[0].split(b'\t')
        _require(len(fields) == 9 and fields[3].isdigit() and fields[4].isdigit() and
                 0 < int(fields[3]) <= int(fields[4]), 'Downloaded annotation does not have a GTF header/feature row.')
    else:
        _require(bool(lines) and lines[0].startswith(b'>') and len(lines[0]) > 1,
                 'Downloaded sequence file does not begin with a FASTA record.')
        _require(any(line and not line.startswith(b'>') for line in lines[1:]),
                 'Downloaded sequence file contains no sequence after its FASTA header.')


def _public(value):
    result = deepcopy(value)
    if isinstance(result, dict):
        for file in result.get('files', []):
            manifest = file.get('checksum_manifest')
            if isinstance(manifest, dict):
                manifest.pop('text', None)
    return result


class ReferenceManager(ReferenceLibraryMixin, ReferenceTransferMixin):
    def __init__(self, app_root, provider=None):
        self.root = filesystem_path(app_root).absolute()
        self.data = self.root / 'user-data' / 'references'
        self.registry = self.data / 'library.json'
        self.provider = provider if provider is not None else EnsemblArchiveProvider()
        self.providers = {self.provider.descriptor()['id']: self.provider}
        if provider is None:
            from reference_ncbi import NCBIRefSeqProvider
            ncbi = NCBIRefSeqProvider()
            self.providers[ncbi.descriptor()['id']] = ncbi
        self._active_provider = self.provider.descriptor()['id']
        self._pause = threading.Event()
        self._active_job = None
        self.lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._releases = []
        self._species = []
        self._discovery = None
        self._selections = {}

    def _records(self):
        _no_links(self.registry)
        if not self.registry.exists():
            return []
        document, _ = _read_json(self.registry, MAX_REGISTRY_BYTES)
        _require(isinstance(document, dict) and type(document.get('schema')) is int and document['schema'] == 1 and
                 isinstance(document.get('records'), list) and len(document['records']) <= MAX_RECORDS,
                 'Unsupported or damaged local reference library.')
        seen = set()
        for record in document['records']:
            _require(isinstance(record, dict) and isinstance(record.get('id'), str) and
                     IDENTITY.fullmatch(record['id']) and record['id'] not in seen and
                     isinstance(record.get('folder'), str) and Path(record['folder']).is_absolute() and
                     isinstance(record.get('receipt_path'), str) and
                     isinstance(record.get('receipt_sha256'), str) and SHA.fullmatch(record['receipt_sha256']) and
                     isinstance(record.get('files'), list) and 1 <= len(record['files']) <= len(KINDS),
                     'Damaged local reference record; existing files were preserved.')
            seen.add(record['id'])
            ids, names = set(), set()
            for file in record['files']:
                _require(isinstance(file, dict) and isinstance(file.get('id'), str) and isinstance(file.get('kind'), str) and
                         file['id'] in KINDS and file['kind'] in KINDS and
                         file['id'] not in ids and type(file.get('bytes')) is int and file['bytes'] > 0 and
                         isinstance(file.get('sha256'), str) and SHA.fullmatch(file['sha256']) and
                         isinstance(file.get('path'), str), 'Damaged local reference file record.')
                name = _filename(file.get('filename'))
                _require(name.casefold() not in names and
                         filesystem_path(file['path']) == filesystem_path(record['folder']) / name,
                         'Reference file is outside its recorded bundle.')
                ids.add(file['id']); names.add(name.casefold())
            _require(filesystem_path(record['receipt_path']) == filesystem_path(record['folder']) / 'reference.json',
                     'Reference receipt is outside its recorded bundle.')
        return document['records']

    def snapshot(self):
        with self.lock:
            records, used = [], 0
            all_records = self._records()
            for raw_record in reversed(all_records):
                record = _public(raw_record)
                amount = len(_json_bytes(record))
                if used + amount > MAX_SNAPSHOT_LOCAL_BYTES:
                    break
                used += amount
                try:
                    self._verify_record(raw_record)
                    for file in record['files']:
                        self._verify_file(file)
                    record.update(available=True, status='ready', error='')
                except (ReferenceError, OSError) as exc:
                    record.update(available=False, status='unavailable', error=str(exc))
                records.append(record)
            records.reverse()
            omitted = len(all_records) - len(records)
            return {'schema': 1, 'providers': [deepcopy(p.descriptor()) for p in self.providers.values()],
                    'active_provider': self._active_provider, 'pending': self._pending_snapshot(),
                    'releases': deepcopy(self._releases), 'species': deepcopy(self._species),
                    'discovery': _public(self._discovery), 'local': records, 'omitted_local': omitted,
                    'default_destination': self._default_destination(),
                    'notice': 'Public reference discovery and downloads connect only when requested. '
                              'Downloaded files remain local. Ensembl archive releases are not the new Ensembl platform.' +
                              (f' Showing the newest {len(records)} bundles; {omitted} older bundles remain on disk.' if omitted else '')}

    def _get_provider(self, provider_id=None):
        provider_id = provider_id or self.provider.descriptor()['id']
        _require(isinstance(provider_id, str) and provider_id in self.providers, 'Choose an available reference provider.')
        return self.providers[provider_id]

    def search(self, release, query, cancel=None, event=None, provider_id=None):
        _cancelled(cancel)
        provider = self._get_provider(provider_id)
        releases = provider.releases(cancel=cancel, event=event)
        species = provider.species(release, query=query, cancel=cancel, event=event)
        _cancelled(cancel)
        with self.lock:
            self._active_provider = provider.descriptor()['id']
            self._releases, self._species = deepcopy(releases), deepcopy(species)
            self._discovery = None
        return self.snapshot()

    def discover(self, release, species_id, cancel=None, event=None, provider_id=None):
        _cancelled(cancel)
        provider = self._get_provider(provider_id)
        discovery = deepcopy(provider.discover(release, species_id, cancel=cancel, event=event))
        _require(isinstance(discovery, dict) and discovery.get('provider') == provider.descriptor()['id'], 'Provider discovery identity does not match the selected provider.')
        _require(isinstance(discovery, dict) and isinstance(discovery.get('files'), list) and
                 1 <= len(discovery['files']) <= len(KINDS), 'Provider found no supported reference files.')
        selection_id = uuid.uuid4().hex
        discovery['selection_id'] = selection_id
        _cancelled(cancel)
        with self.lock:
            self._active_provider = provider.descriptor()['id']
            self._discovery = discovery
            self._selections[selection_id] = deepcopy(discovery)
            # Bounded session selections; old UI requests must rediscover explicitly.
            while len(self._selections) > 20:
                self._selections.pop(next(iter(self._selections)))
        return self.snapshot()

    def _verify_record(self, record):
        _directory(record['folder'])
        receipt, raw = _read_json(record['receipt_path'], MAX_RECEIPT_BYTES)
        _require(hashlib.sha256(raw).hexdigest() == record['receipt_sha256'],
                 'The reference provenance receipt has changed or is damaged.')
        _require(receipt == {key: value for key, value in record.items() if key != 'receipt_sha256'},
                 'The reference library does not agree with its original provenance receipt.')

    def _verify_file(self, file):
        path = _no_links(file['path'])
        _require(path.is_file(), 'A registered reference file is missing: ' + file['filename'])
        info = path.stat()
        _require(info.st_size == file['bytes'], 'A registered reference file has changed: ' + file['filename'])
        return path

    def _record(self, record_id):
        _require(isinstance(record_id, str), 'Invalid local reference identifier.')
        record = next((record for record in self._records() if record['id'] == record_id), None)
        _require(record is not None, 'This downloaded reference is no longer in the local library.')
        self._verify_record(record)
        return record

    def resolve_file(self, record_id, file_id):
        with self.lock:
            record = self._record(record_id)
            file = next((file for file in record['files'] if file['id'] == file_id), None)
            _require(file is not None, 'This file was not downloaded in the selected reference bundle.')
            self._verify_file(file)
            return {**_public({'files': [file]})['files'][0], 'record_id': record['id'], 'record_label': record.get('label', ''),
                    **{key: deepcopy(record.get(key)) for key in
                       ('provider', 'release', 'species', 'assembly', 'assembly_accession',
                        'receipt_path', 'receipt_sha256', 'downloaded_at', 'origin', 'provider_name',
                        'imported_at', 'user_declared', 'source', 'relocated_at', 'previous_location')}}

    def record_folder(self, record_id):
        with self.lock:
            return _ordinary(_directory(self._record(record_id)['folder']))

    def provenance_for_path(self, path, sha256=None):
        key = os.path.normcase(_ordinary(filesystem_path(path).resolve()))
        with self.lock:
            for record in [*self._records(), *self._previous_records()]:
                for file in record['files']:
                    if os.path.normcase(_ordinary(filesystem_path(file['path']).resolve())) != key:
                        continue
                    self._verify_record(record)
                    self._verify_file(file)
                    if sha256 is not None:
                        _require(sha256 == file['sha256'],
                                 'A registered reference changed after retrieval. Restore the file or select an independent local copy.')
                    return {key: deepcopy(record.get(key)) for key in
                            ('provider', 'release', 'species', 'assembly', 'assembly_accession',
                             'receipt_path', 'receipt_sha256', 'downloaded_at', 'source_catalog', 'origin',
                             'provider_name', 'imported_at', 'user_declared', 'source', 'relocated_at', 'previous_location')} | {
                                'record_id': record['id'], 'record_label': record.get('label', ''),
                                'file': _public({'files': [file]})['files'][0]}
        return None

    @staticmethod
    def _disk(path, needed=0):
        _require(shutil.disk_usage(path).free >= needed + DISK_FLOOR,
                 'There is not enough free disk space for this reference download.')
