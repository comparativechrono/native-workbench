"""Durable compressed staging; only fully checked files enter the local library.

Lock files are permanent rendezvous inodes, never ownership markers. The OS
releases their advisory locks after process death, including abrupt termination.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import zlib

from reference_provider import ReferenceCancelled, ReferenceHTTPError, ReferenceProviderError

MAX_PENDING = 50
MAX_JOB_BYTES = 6 * 1024**2
WRITE_TEMP = re.compile(r'_write-[a-zA-Z0-9_-]{6,40}\.json\Z')


class ReferencePaused(ReferenceCancelled):
    pass


@contextmanager
def file_lease(path):
    from reference_manager import _no_links, ReferenceError
    path = _no_links(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b'\0')
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ReferenceError('Another Workbench instance is updating these references. Retry after it finishes.') from exc
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ReferenceError('Another Workbench instance is updating these references. Retry after it finishes.') from exc
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _validator(headers):
    etag = headers.get('ETag')
    if isinstance(etag, str) and len(etag) <= 500 and re.fullmatch(r'"[^"\\\r\n]+"', etag):
        return 'etag', etag
    modified = headers.get('Last-Modified')
    if isinstance(modified, str) and re.fullmatch(r'[A-Z][a-z]{2}, [0-9]{2} [A-Z][a-z]{2} [0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT', modified):
        return 'last_modified', modified
    return None, None


class ReferenceTransferMixin:
    def _transfer_check(self, cancel):
        from reference_manager import _cancelled
        _cancelled(cancel)  # Explicit Cancel wins over a simultaneous Pause.
        if self._pause.is_set():
            raise ReferencePaused('Reference download paused; partial download retained. Resume or discard it in References.')

    def pause(self):
        self._pause.set()

    def _pending_root(self, create=False):
        from reference_manager import _directory, _no_links
        root = self.data / 'pending'
        return _directory(root, create=True) if create else _no_links(root)

    def _job_path(self, identity):
        from reference_manager import _require, IDENTITY
        _require(isinstance(identity, str) and IDENTITY.fullmatch(identity), 'Invalid pending reference identifier.')
        return self._pending_root() / identity

    def _read_job(self, identity):
        from reference_manager import _read_json, _require, _no_links, _directory, KINDS, SHA, MAX_DOWNLOAD_BYTES
        folder = _directory(self._job_path(identity))
        job, _ = _read_json(folder / 'job.json', MAX_JOB_BYTES)
        _require(isinstance(job, dict) and job.get('schema') == 1 and job.get('id') == identity and
                 job.get('status') in ('downloading', 'interrupted', 'paused') and
                 isinstance(job.get('destination'), str) and Path(job['destination']).is_absolute() and
                 isinstance(job.get('selection'), dict) and isinstance(job.get('files'), list) and
                 1 <= len(job['files']) <= len(KINDS) and isinstance(job.get('states'), dict),
                 'Pending reference checkpoint is damaged. Discard it and discover the reference again.')
        pin, pin_raw = _read_json(folder / 'pin.json', MAX_JOB_BYTES)
        _require(isinstance(job.get('pin_sha256'), str) and hashlib.sha256(pin_raw).hexdigest() == job['pin_sha256'] and
                 pin == {key: job[key] for key in ('id', 'selection', 'files', 'destination')},
                 'Pending reference discovery pin has changed; discard and discover again.')
        _require(isinstance(job.get('label'), str) and len(job['label']) <= 1000 and
                 isinstance(job.get('error'), str) and len(job['error']) <= 500, 'Pending reference checkpoint metadata is damaged.')
        selection = job['selection']
        self._get_provider(selection.get('provider'))
        ids = [item.get('id') for item in job['files'] if isinstance(item, dict)]
        _require(len(ids) == len(job['files']) and all(isinstance(identity, str) for identity in ids) and len(set(ids)) == len(ids) and
                 set(ids) <= KINDS and set(job['states']) == set(ids), 'Pending reference checkpoint contains invalid files.')
        self._validate_items(job['files'])
        allowed = {'job.json', 'pin.json', '.lease', *(identity + '.gz' for identity in ids)}
        for child in folder.iterdir():
            _no_links(child)
            _require((child.name in allowed or WRITE_TEMP.fullmatch(child.name)) and child.is_file(),
                     'Pending reference checkpoint contains unexpected files.')
        for state in job['states'].values():
            _require(isinstance(state, dict) and type(state.get('bytes')) is int and
                     0 <= state['bytes'] <= MAX_DOWNLOAD_BYTES and isinstance(state.get('sha256'), str) and
                     SHA.fullmatch(state['sha256']) and type(state.get('complete')) is bool and
                     (state.get('total') is None or type(state['total']) is int and 0 < state['total'] <= MAX_DOWNLOAD_BYTES) and
                     (state.get('validator_kind') is None or state['validator_kind'] in ('etag', 'last_modified')) and
                     (state.get('validator') is None or isinstance(state['validator'], str) and len(state['validator']) <= 500),
                     'Pending reference checkpoint is damaged. Discard it and discover the reference again.')
        _require(job.get('publication_sha256') is None or isinstance(job['publication_sha256'], str) and
                 SHA.fullmatch(job['publication_sha256']), 'Pending reference publication checkpoint is damaged.')
        return job

    def _clean_checkpoint_temps(self, identity):
        from reference_manager import _directory, _no_links, _require
        for path in _directory(self._job_path(identity)).iterdir():
            _no_links(path)
            if WRITE_TEMP.fullmatch(path.name):
                _require(path.is_file(), 'Pending reference checkpoint contains an unexpected folder.')
                path.unlink()

    def _orphan_record(self, job, final, cancel=None, hashes=True):
        from reference_manager import _read_json, _require, _directory, _no_links, _ordinary, MAX_RECEIPT_BYTES, CHUNK
        final = _directory(final)
        record, raw = _read_json(final / 'reference.json', MAX_RECEIPT_BYTES)
        _require(isinstance(record, dict) and job.get('publication_sha256') and hashlib.sha256(raw).hexdigest() == job['publication_sha256'] and
                 record.get('id') == job['id'] and record.get('folder') == _ordinary(final) and
                 record.get('receipt_path') == _ordinary(final / 'reference.json'),
                 'Reference destination contains an unrecognized incomplete publication; existing files were preserved.')
        files = record.get('files', [])
        names = {item['filename'][:-3] for item in job['files']}
        _require(isinstance(files, list) and len(files) == len(names) and
                 all(isinstance(f, dict) and isinstance(f.get('filename'), str) for f in files) and {f['filename'] for f in files} == names and
                 {p.name for p in final.iterdir()} == names | {'reference.json'},
                 'Incomplete reference publication contains unexpected files; existing files were preserved.')
        for file in files:
            path = _no_links(final / file['filename'])
            _require(file.get('path') == _ordinary(path) and path.is_file() and path.stat().st_size == file.get('bytes'),
                     'Incomplete reference publication has changed; existing files were preserved.')
            if hashes:
                sha = hashlib.sha256()
                with path.open('rb') as stream:
                    while block := stream.read(CHUNK):
                        self._transfer_check(cancel); sha.update(block)
                _require(sha.hexdigest() == file.get('sha256'), 'Incomplete reference publication has changed; existing files were preserved.')
        record['receipt_sha256'] = hashlib.sha256(raw).hexdigest()
        return record

    def _save_job(self, job):
        from reference_manager import _atomic_json, _json_bytes, _require
        _require(len(_json_bytes(job)) <= MAX_JOB_BYTES, 'Reference download checkpoint is too large.')
        _atomic_json(self._job_path(job['id']) / 'job.json', job)

    def _pending_snapshot(self):
        from reference_manager import _require, ReferenceError, IDENTITY
        root = self._pending_root()
        if not root.exists():
            return []
        _require(root.is_dir(), 'The pending reference location is not a directory.')
        children = sorted(root.iterdir(), key=lambda p: p.name)
        _require(len(children) <= MAX_PENDING, 'Too many pending references; remove completed or discarded downloads.')
        result = []
        for folder in children:
            if not IDENTITY.fullmatch(folder.name):
                raise ReferenceError('The pending reference location contains unexpected entries.')
            try:
                job = self._read_job(folder.name)
                states = list(job['states'].values())
                result.append({'id': job['id'], 'status': ('interrupted' if job['status'] == 'downloading' and getattr(self, '_active_job', None) != job['id'] else job['status']),
                               'provider': job['selection']['provider'], 'label': job.get('label', 'Reference download'),
                               'destination': job['destination'], 'bytes': sum(s['bytes'] for s in states),
                               'total': sum(s['total'] for s in states) if all(s['total'] is not None for s in states) else None,
                               'files': [dict(id=f['id'], filename=f['filename']) for f in job['files']],
                               'error': job.get('error', ''), 'resumable': True})
            except (ReferenceError, OSError, ValueError) as exc:
                result.append({'id': folder.name, 'status': 'damaged', 'label': 'Damaged pending reference',
                               'bytes': 0, 'total': None, 'resumable': False, 'error': str(exc)})
        return result

    def _remove_job(self, identity, job=None):
        from reference_manager import _directory, _no_links, _require, filesystem_path
        folder = _directory(self._job_path(identity))
        # No recursive traversal of untrusted links, including discarded corrupt jobs.
        for child in folder.iterdir():
            _no_links(child)
            _require(child.is_file(), 'Pending reference contains an unexpected folder; existing files were preserved.')
        if job is not None and job.get('publication_sha256'):
            final = filesystem_path(job['destination']) / ('ref-' + identity[:16])
            if final.exists() and not any(r['id'] == identity for r in self._records()):
                self._orphan_record(job, final, hashes=False)
                shutil.rmtree(final)
        shutil.rmtree(folder)

    def discard(self, job_id):
        from reference_manager import _require, _directory
        _require(self._operation_lock.acquire(blocking=False), 'Another reference operation is already running.')
        try:
            _directory(self.data, create=True)
            with file_lease(self.data / '_transfer.lease'):
                try:
                    job = self._read_job(job_id)
                except (ValueError, OSError):
                    job = None
                self._remove_job(job_id, job)
            return self.snapshot()
        finally:
            self._operation_lock.release()

    def _validate_items(self, items):
        from reference_manager import _require, _filename, KINDS, MAX_DOWNLOAD_BYTES
        names = []
        for item in items:
            _require(isinstance(item, dict) and isinstance(item.get('id'), str) and isinstance(item.get('kind'), str) and
                     item['id'] in KINDS and item['kind'] in KINDS,
                     'Provider supplied an unknown reference type.')
            filename = _filename(item.get('filename'))
            _require(filename.endswith('.gz'), 'Only provider-resolved gzip reference files are supported.')
            names.append(_filename(filename[:-3]).casefold())
            size = item.get('bytes', item.get('size'))
            _require(size is None or type(size) is int and 0 < size <= MAX_DOWNLOAD_BYTES,
                     'Reference download exceeds the supported size.')
            checksum = item.get('checksum')
            good = isinstance(checksum, dict) and (
                checksum.get('algorithm') == 'bsd-sum' and type(checksum.get('value')) is int and
                0 <= checksum['value'] <= 65535 and type(checksum.get('blocks')) is int and checksum['blocks'] > 0 or
                checksum.get('algorithm') == 'md5' and isinstance(checksum.get('value'), str) and
                re.fullmatch(r'[a-f0-9]{32}', checksum['value']))
            _require(good, 'Provider supplied no supported integrity checksum.')
            _require(isinstance(item.get('url'), str), 'Provider supplied no reference URL.')
        _require(len(set(names)) == len(names) and 'reference.json' not in names, 'Provider filenames collide.')
        _require(sum(item.get('bytes') or 0 for item in items) <= MAX_DOWNLOAD_BYTES,
                 'Selected references exceed the compressed download limit.')

    def download(self, selection_id, file_ids, destination, cancel=None, event=None):
        from reference_manager import _require, _cancelled, _directory, _ordinary, _no_links, filesystem_path, KINDS, uuid
        _require(self._operation_lock.acquire(blocking=False), 'Another reference operation is already running.')
        self._pause.clear()
        try:
            with self.lock:
                selection = deepcopy(self._selections.get(selection_id)) if isinstance(selection_id, str) else None
            _require(selection is not None, 'This reference selection expired. Discover its files again.')
            _require(isinstance(file_ids, list) and 1 <= len(file_ids) <= len(KINDS) and
                     all(isinstance(v, str) for v in file_ids) and len(set(file_ids)) == len(file_ids),
                     'Select one or more distinct reference files.')
            by_id = {item['id']: item for item in selection['files']}
            _require(all(identity in by_id for identity in file_ids), 'A requested file was not in this reference discovery.')
            items = [by_id[identity] for identity in file_ids]
            self._validate_items(items)
            _require(isinstance(destination, str) and destination and len(destination) < 32700 and Path(destination).is_absolute(),
                     'Choose an absolute reference destination folder.')
            _cancelled(cancel)
            # UI paths may use ordinary or 8.3 spellings while self.data uses
            # extended long paths. Reject links before resolving the existing
            # ancestors for physical path comparison; retain the IO spelling.
            destination_path = _no_links(filesystem_path(destination).absolute())
            managed_path = _no_links(self.data)
            destination_identity = destination_path.resolve(strict=False)
            is_managed = destination_identity == managed_path.resolve(strict=False)
            destination_path = _directory(destination_path, create=is_managed)
            pending_root = self._pending_root().resolve(strict=False)
            _require(destination_identity != pending_root and pending_root not in destination_identity.parents,
                     'Choose a reference destination outside incomplete download staging.')
            self._disk(destination_path, sum(item.get('bytes') or 0 for item in items))
            identity = uuid.uuid4().hex
            final = destination_path / ('ref-' + identity[:16])
            _require(not final.exists() and not final.is_symlink(), 'Reference destination already exists; existing files were preserved.')
            root = self._pending_root(create=True)
            with file_lease(self.data / '_transfer.lease'):
                _require(len(list(root.iterdir())) < MAX_PENDING, 'Too many pending references. Resume or discard older downloads first.')
                (root / identity).mkdir()
                species = selection.get('species', {})
                label = selection.get('label') or (species.get('name', 'Reference') if isinstance(species, dict) else str(species))
                job = {'schema': 1, 'id': identity, 'selection': selection, 'files': items,
                       'destination': _ordinary(destination_path), 'label': label, 'status': 'downloading', 'error': '',
                       'states': {item['id']: {'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest(), 'complete': False,
                                              'total': item.get('bytes'), 'validator_kind': None, 'validator': None}
                                  for item in items}}
                try:
                    from reference_manager import _json_bytes
                    pin_raw = _json_bytes({key: job[key] for key in ('id', 'selection', 'files', 'destination')})
                    with (root / identity / 'pin.json').open('xb') as stream:
                        stream.write(pin_raw); stream.flush(); os.fsync(stream.fileno())
                    job['pin_sha256'] = hashlib.sha256(pin_raw).hexdigest()
                    self._save_job(job)
                except OSError as exc:
                    self._remove_job(identity)
                    from reference_manager import ReferenceError
                    raise ReferenceError('Could not save the reference download checkpoint; check destination permissions.') from exc
                except BaseException:
                    self._remove_job(identity)
                    raise
                return self._run_transfer(job, cancel, event)
        finally:
            self._operation_lock.release()

    def resume(self, job_id, cancel=None, event=None):
        from reference_manager import _require, _directory
        _require(self._operation_lock.acquire(blocking=False), 'Another reference operation is already running.')
        self._pause.clear()
        try:
            _directory(self.data, create=True)
            with file_lease(self.data / '_transfer.lease'):
                job = self._read_job(job_id)
                self._clean_checkpoint_temps(job_id)
                return self._run_transfer(job, cancel, event)
        finally:
            self._operation_lock.release()

    def _prefix(self, path, state, cancel):
        from reference_manager import _require, _no_links, CHUNK
        _no_links(path)
        sha = hashlib.sha256()
        if not path.exists():
            _require(state['bytes'] == 0, 'Pending reference compressed prefix is missing; discard and download again.')
            return sha
        _require(path.is_file() and path.stat().st_size >= state['bytes'],
                 'Pending reference compressed prefix is truncated; discard and download again.')
        remaining = state['bytes']
        with path.open('rb') as stream:
            while remaining:
                self._transfer_check(cancel)
                block = stream.read(min(CHUNK, remaining))
                _require(bool(block), 'Pending reference compressed prefix is truncated.')
                sha.update(block); remaining -= len(block)
        _require(sha.hexdigest() == state['sha256'], 'Pending reference compressed prefix has changed; discard and download again.')
        # A crash between fsync(data) and replace(checkpoint) may leave an
        # uncommitted suffix. It is never trusted or sent as a resume offset.
        if path.stat().st_size != state['bytes']:
            with path.open('r+b') as stream:
                stream.truncate(state['bytes']); stream.flush(); os.fsync(stream.fileno())
        return sha

    def _fetch_compressed(self, job, item, cancel, event):
        from reference_manager import _require, _event, CHUNK, MAX_DOWNLOAD_BYTES, ReferenceError
        state = job['states'][item['id']]
        path = self._job_path(job['id']) / (item['id'] + '.gz')
        sha = self._prefix(path, state, cancel)
        if state['complete']:
            return path
        provider = self._get_provider(job['selection']['provider'])
        offset = state['bytes']
        headers = {'Range': f'bytes={offset}-', 'If-Range': state['validator']} if offset and state.get('validator') else None
        # A prefix without a strong entity/date validator cannot safely resume.
        if offset and headers is None:
            offset = 0
        try:
            response = provider.open_url(item['url'], cancel=cancel, **({'headers': headers} if headers else {}))
        except ReferenceHTTPError as exc:
            if headers and exc.status == 416:
                response = provider.open_url(item['url'], cancel=cancel)
                offset = 0
            else:
                raise
        with response:
            code = response.getcode()
            _require(response.headers.get('Content-Encoding', 'identity').lower() in ('', 'identity'),
                     'Reference server returned unsupported HTTP encoding.')
            raw_length = response.headers.get('Content-Length')
            _require(raw_length is None or isinstance(raw_length, str) and re.fullmatch(r'[0-9]{1,20}', raw_length) and
                     0 < int(raw_length) <= MAX_DOWNLOAD_BYTES, 'Reference server returned an invalid or excessive content length.')
            length = int(raw_length) if raw_length is not None else None
            kind, validator = _validator(response.headers)
            if code == 206:
                _require(headers is not None and offset > 0, 'Unexpected partial reference response.')
                match = re.fullmatch(r'bytes ([0-9]+)-([0-9]+)/([0-9]+)', response.headers.get('Content-Range', ''))
                valid = bool(match and int(match[1]) == offset and int(match[2]) >= offset and
                             int(match[3]) > int(match[2]) and int(match[2]) == int(match[3]) - 1 and
                             int(match[3]) <= MAX_DOWNLOAD_BYTES and length == int(match[2]) - offset + 1 and
                             (state.get('total') is None or int(match[3]) == state['total']) and
                             kind == state.get('validator_kind') and validator == state.get('validator'))
                if not valid:
                    response.close()
                    state.update(bytes=0, sha256=hashlib.sha256(b'').hexdigest(), complete=False, validator=None, validator_kind=None)
                    if path.exists():
                        with path.open('wb') as stream:
                            stream.flush(); os.fsync(stream.fileno())
                    self._save_job(job)
                    # A malformed/changed range is never appended. Retry once
                    # as an ordinary full request whose checksum still pins it.
                    return self._fetch_compressed(job, item, cancel, event)
                total = int(match[3])
            else:
                _require(code == 200, 'Reference server did not return an ordinary file.')
                offset = 0
                total = length
            size = item.get('bytes', item.get('size'))
            _require(size is None or total is None or size == total, 'Reference size changed since discovery; discover files again.')
            if not offset:
                sha = hashlib.sha256()
                state.update(bytes=0, sha256=sha.hexdigest(), complete=False)
            state.update(total=total if total is not None else size, validator_kind=kind, validator=validator,
                         etag=response.headers.get('ETag'), last_modified=response.headers.get('Last-Modified'), effective_url=response.geturl())
            mode = 'r+b' if offset else 'wb'
            started, last_progress = time.monotonic(), 0.0
            with path.open(mode) as stream:
                stream.seek(offset)
                self._save_job(job)
                while True:
                    self._transfer_check(cancel)
                    _require(time.monotonic() - started < 48 * 3600, 'Reference download exceeded its 48-hour limit.')
                    block = response.read(CHUNK)
                    if not block:
                        break
                    self._disk(path.parent, len(block))
                    count = state['bytes'] + len(block)
                    _require(sum(s['bytes'] for s in job['states'].values()) + len(block) <= MAX_DOWNLOAD_BYTES,
                             'Selected references exceed the compressed download limit.')
                    _require((total is None or count <= total) and (size is None or count <= size),
                             'Reference server sent more bytes than declared.')
                    stream.write(block); stream.flush(); os.fsync(stream.fileno())
                    sha.update(block); state.update(bytes=count, sha256=sha.hexdigest())
                    self._save_job(job)
                    now = time.monotonic()
                    if now - last_progress >= .15:
                        _event(event, 'downloading', message='Downloading ' + item.get('label', item['filename']),
                               job_id=job['id'], filename=item['filename'], bytes=sum(s['bytes'] for s in job['states'].values()),
                               total=sum(s['total'] for s in job['states'].values()) if all(s['total'] is not None for s in job['states'].values()) else None,
                               cancellable=True, pausable=True)
                        last_progress = now
            if state['bytes'] == 0 or total is not None and state['bytes'] != total or size is not None and state['bytes'] != size:
                raise OSError('Reference download was truncated; compressed progress was retained for Resume.')
            state['complete'] = True
            self._save_job(job)
        return path

    def _expand_checked(self, job, item, source, folder, expanded_total, cancel, event):
        from reference_manager import _require, _event, _bsd_update, _check_format, CHUNK, MAX_EXPANDED_BYTES, ReferenceError
        checksum = item['checksum']; bsd = compressed = expanded = members = 0
        compressed_hash, expanded_hash, md5 = hashlib.sha256(), hashlib.sha256(), hashlib.md5(usedforsecurity=False)
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        prefix = bytearray(); name = item['filename'][:-3]
        target = folder / name
        _event(event, 'verifying', message='Checking and expanding ' + item.get('label', name), cancellable=True, pausable=True)
        with source.open('rb') as stream, target.open('xb') as output:
            while block := stream.read(CHUNK):
                self._transfer_check(cancel)
                compressed += len(block); compressed_hash.update(block)
                if checksum['algorithm'] == 'bsd-sum':
                    bsd = _bsd_update(bsd, block)
                else:
                    md5.update(block)
                pending = block
                while pending:
                    self._transfer_check(cancel)
                    if decompressor.eof:
                        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    try:
                        plain = decompressor.decompress(pending, CHUNK)
                    except zlib.error as exc:
                        raise ReferenceError('Downloaded gzip data is corrupt or its CRC check failed: ' + item['filename']) from exc
                    pending = decompressor.unused_data if decompressor.eof else decompressor.unconsumed_tail
                    if decompressor.eof:
                        members += 1
                    expanded += len(plain)
                    _require(expanded_total + expanded <= MAX_EXPANDED_BYTES, 'Expanded reference files exceed the supported size limit.')
                    if len(prefix) < 65536:
                        prefix.extend(plain[:65536 - len(prefix)])
                    if plain:
                        self._disk(folder, len(plain)); output.write(plain); expanded_hash.update(plain)
            _require(decompressor.eof and members > 0, 'Downloaded gzip file is incomplete; no reference was added.')
            if checksum['algorithm'] == 'bsd-sum':
                _require(bsd == checksum['value'] and (compressed + 1023) // 1024 == checksum['blocks'],
                         'Reference does not match the provider BSD checksum; no reference was added.')
            else:
                _require(md5.hexdigest() == checksum['value'], 'Reference does not match the provider MD5 checksum; no reference was added.')
            _check_format(prefix, item['kind'], item['filename'])
            validate_prefix = getattr(self._get_provider(job['selection']['provider']), 'validate_download_prefix', None)
            if validate_prefix is not None:
                try:
                    validate_prefix(item, bytes(prefix), job['selection'])
                except ReferenceProviderError as exc:
                    raise ReferenceError(str(exc)) from exc
            output.flush(); os.fsync(output.fileno())
        state = job['states'][item['id']]
        _require(compressed == state['bytes'] and compressed_hash.hexdigest() == state['sha256'],
                 'Reference compressed staging changed while being verified; no reference was added.')
        return {**deepcopy(item), 'filename': name, 'source_filename': item['filename'], 'bytes': expanded,
                'sha256': expanded_hash.hexdigest(), 'compressed_bytes': compressed, 'compressed_sha256': compressed_hash.hexdigest(),
                'source_url': item['url'], 'effective_url': state.get('effective_url', item['url']),
                'etag': state.get('etag'), 'last_modified': state.get('last_modified'),
                'sequence_choice': item.get('sequence_scope', item.get('sequence_choice', item.get('sequence_set'))),
                'masking': item.get('masking'), 'format': item.get('format', 'gtf' if item['kind'] == 'annotation' else 'fasta'),
                'validation': {'gzip_crc': 'passed', 'provider_' + ('bsd_sum' if checksum['algorithm'] == 'bsd-sum' else 'md5'): 'passed',
                               'format_header': 'passed (basic prefix only)', 'sha256': 'computed locally; not a publisher signature'}}

    def _run_transfer(self, job, cancel, event):
        from reference_manager import _directory, _ordinary, _require, _event, _json_bytes, MAX_RECEIPT_BYTES, MAX_RECORDS, ReferenceError
        temporary = None; published = registered = False; final = None
        self._active_job = job['id']
        try:
            self._transfer_check(cancel)
            destination = _directory(job['destination'])
            final = destination / ('ref-' + job['id'][:16])
            # A process can die after registry commit but before staging cleanup.
            existing = next((r for r in self._records() if r['id'] == job['id']), None)
            if existing:
                self._verify_record(existing)
                _require(existing['folder'] == _ordinary(final), 'Pending reference identity collides with another bundle.')
                self._remove_job(job['id'])
                return self.snapshot()
            if final.exists() and job.get('publication_sha256'):
                with self._library_lease():
                    record = self._orphan_record(job, final, cancel)
                    document = self._library_document()
                    _require(len(document['records']) < MAX_RECORDS and not any(r['id'] == job['id'] for r in document['records']),
                             'Reference library is full or already contains this publication.')
                    self._transfer_check(cancel)
                    _event(event, 'publishing', message='Adding the verified reference to your local library.',
                           bytes=sum(s['bytes'] for s in job['states'].values()), total=sum(s['bytes'] for s in job['states'].values()),
                           cancellable=False, pausable=False)
                    document['records'].append(record)
                    self._write_library(document); registered = True
                self._remove_job(job['id'])
                return self.snapshot()
            _require(not final.exists() and not final.is_symlink(), 'Reference destination already exists; existing files were preserved.')
            job.update(status='downloading', error=''); self._save_job(job)
            compressed = [(item, self._fetch_compressed(job, item, cancel, event)) for item in job['files']]
            temporary = Path(tempfile.mkdtemp(prefix='_ref-', dir=destination))
            files, expanded = [], 0
            for item, source in compressed:
                file = self._expand_checked(job, item, source, temporary, expanded, cancel, event)
                file['path'] = _ordinary(final / file['filename']); files.append(file); expanded += file['bytes']
            self._transfer_check(cancel)
            selection = job['selection']
            record = {key: deepcopy(value) for key, value in selection.items() if key not in {'files', 'selection_id'}}
            species = selection.get('species', 'Reference')
            species_name = species.get('name', species.get('id', 'Reference')) if isinstance(species, dict) else str(species)
            assembly = selection.get('assembly') or (species.get('assembly', '') if isinstance(species, dict) else '')
            record.update(schema=1, id=job['id'], label=selection.get('label') or
                          (species_name + (' — ' + assembly if assembly else '') + ' — release ' + str(selection.get('release', ''))),
                          folder=_ordinary(final), receipt_path=_ordinary(final / 'reference.json'), files=files,
                          downloaded_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                          integrity_notice='Provider transfer checksums detect transfer errors; local SHA-256 records file identity. Neither is a publisher signature.')
            raw = _json_bytes(record)
            _require(len(raw) <= MAX_RECEIPT_BYTES, 'Reference provenance is unexpectedly large.')
            with (temporary / 'reference.json').open('xb') as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            record['receipt_sha256'] = hashlib.sha256(raw).hexdigest()
            job['publication_sha256'] = record['receipt_sha256']
            self._save_job(job)
            with self._library_lease():
                document = self._library_document()
                _require(len(document['records']) < MAX_RECORDS, 'The local reference library is full.')
                _require(not final.exists() and not final.is_symlink(), 'Reference destination already exists; existing files were preserved.')
                _directory(destination); self._transfer_check(cancel)
                _event(event, 'publishing', message='Adding the verified reference to your local library.',
                       bytes=sum(s['bytes'] for s in job['states'].values()), total=sum(s['bytes'] for s in job['states'].values()),
                       cancellable=False, pausable=False)
                os.rename(temporary, final); published = True
                document['records'].append(record)
                self._write_library(document); registered = True
            self._remove_job(job['id'])
            return self.snapshot()
        except ReferencePaused:
            if not registered:
                job.update(status='paused', error=''); self._save_job(job)
            raise
        except ReferenceCancelled:
            if not registered:
                self._remove_job(job['id'], job)
            raise
        except (OSError, HTTPException, ReferenceProviderError) as exc:
            if not registered:
                job.update(status='interrupted', error=str(exc)[:500]); self._save_job(job)
            raise ReferenceError('Reference retrieval interrupted. Resume the retained download or discard it. ' + str(exc)[:300]) from exc
        except (ReferenceError, ValueError):
            # Integrity and state errors never expose ready data or trigger
            # automatic network retries. Preserve unknown publication folders.
            if not registered:
                self._remove_job(job['id'], job)
            raise
        finally:
            self._active_job = None
            if published and not registered and final is not None:
                shutil.rmtree(final, ignore_errors=True)
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
