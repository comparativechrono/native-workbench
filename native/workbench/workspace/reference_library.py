"""Reviewed local reference imports and copy-only library relocation.

All data reads stay local. A receipt establishes exact local bytes, never the
truth of user-entered biological descriptions or a publisher's identity. Old
locations are retained so saved graphs and frozen runs remain valid.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid
import zlib

from pack_manager import filesystem_path

REVIEW_SECONDS = 15 * 60
MAX_REVIEWS = 20
LABELS = {'genome': 'Genome FASTA', 'annotation': 'Gene annotation GTF',
          'cdna': 'cDNA FASTA', 'ncrna': 'ncRNA FASTA', 'protein': 'Protein FASTA'}
IMPORT_NOTICE = ('Files are copied into a verified local bundle. Species, assembly and source are '
                 'user-declared, not provider-authenticated. Original files are retained. '
                 'Basic FASTA/GTF checks do not establish biological compatibility.')
RELOCATION_NOTICE = ('All active bundles are copied and rehashed before the library switches. '
                     'Original folders and receipts are retained for saved workflows and queued runs. '
                     'No old files are deleted and no disk space is reclaimed automatically.')


def _manager():
    # Delayed import avoids a cycle when ReferenceManager inherits this mixin.
    import reference_manager
    return reference_manager


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _path_key(path):
    m = _manager()
    return os.path.normcase(m._ordinary(filesystem_path(path).resolve()))


class ReferenceLibraryMixin:
    def _library_document(self):
        m = _manager()
        m._no_links(self.registry)
        if not self.registry.exists():
            return {'schema': 1, 'records': []}
        document, _ = m._read_json(self.registry, m.MAX_REGISTRY_BYTES)
        m._require(isinstance(document, dict) and type(document.get('schema')) is int and document['schema'] == 1 and
                   isinstance(document.get('records'), list) and len(document['records']) <= m.MAX_RECORDS,
                   'Unsupported or damaged local reference library.')
        previous = document.get('previous_records', [])
        m._require(isinstance(previous, list) and len(previous) <= m.MAX_RECORDS,
                   'Damaged historical reference library; existing files were preserved.')
        folders, active_ids = set(), set()
        for index, record in enumerate([*document['records'], *previous]):
            m._require(isinstance(record, dict) and isinstance(record.get('id'), str) and
                       m.IDENTITY.fullmatch(record['id']) and isinstance(record.get('folder'), str) and
                       Path(record['folder']).is_absolute() and isinstance(record.get('receipt_path'), str) and
                       isinstance(record.get('receipt_sha256'), str) and m.SHA.fullmatch(record['receipt_sha256']) and
                       isinstance(record.get('files'), list) and 1 <= len(record['files']) <= len(m.KINDS),
                       'Damaged historical reference record; existing files were preserved.')
            if index < len(document['records']):
                m._require(record['id'] not in active_ids, 'Duplicate active reference identifier.')
                active_ids.add(record['id'])
            folder = os.path.normcase(record['folder'])
            m._require(folder not in folders, 'Duplicate historical reference location.')
            folders.add(folder)
            ids, names = set(), set()
            for item in record['files']:
                m._require(isinstance(item, dict) and item.get('id') in m.KINDS and item.get('kind') in m.KINDS and
                           item['id'] not in ids and type(item.get('bytes')) is int and item['bytes'] > 0 and
                           isinstance(item.get('sha256'), str) and m.SHA.fullmatch(item['sha256']) and
                           isinstance(item.get('path'), str), 'Damaged historical reference file record.')
                name = m._filename(item.get('filename'))
                m._require(name.casefold() not in names and
                           filesystem_path(item['path']) == filesystem_path(record['folder']) / name,
                           'Historical reference file is outside its recorded bundle.')
                ids.add(item['id']); names.add(name.casefold())
            m._require(filesystem_path(record['receipt_path']) == filesystem_path(record['folder']) / 'reference.json',
                       'Historical reference receipt is outside its recorded bundle.')
        destination = document.get('default_destination')
        m._require(destination is None or isinstance(destination, str) and destination and
                   len(destination) < 32700 and Path(destination).is_absolute(),
                   'Damaged default reference destination; existing files were preserved.')
        return document

    def _previous_records(self):
        return self._library_document().get('previous_records', [])

    def _default_destination(self):
        return self._library_document().get('default_destination', _manager()._ordinary(self.data))

    def _write_library(self, document):
        _manager()._atomic_json(self.registry, document)

    @contextmanager
    def _library_lease(self):
        from reference_transfer import file_lease
        m = _manager()
        with self.lock:
            m._directory(self.data, create=True)
            with file_lease(self.data / '_library.lease'):
                yield

    @contextmanager
    def _library_operation(self):
        m = _manager()
        m._require(self._operation_lock.acquire(blocking=False), 'Another reference operation is already running.')
        try:
            yield
        finally:
            self._operation_lock.release()

    def _registry_identity(self):
        m = _manager()
        m._no_links(self.registry)
        if not self.registry.exists():
            return None
        _, raw = m._read_json(self.registry, m.MAX_REGISTRY_BYTES)
        return hashlib.sha256(raw).hexdigest()

    def _remember_library_review(self, review):
        with self.lock:
            reviews = getattr(self, '_library_reviews', {})
            now = time.monotonic()
            reviews = {key: value for key, value in reviews.items() if now - value[0] <= REVIEW_SECONDS}
            identity = uuid.uuid4().hex
            review['review_id'] = identity
            reviews[identity] = (now, deepcopy(review))
            while len(reviews) > MAX_REVIEWS:
                reviews.pop(next(iter(reviews)))
            self._library_reviews = reviews
        return deepcopy(review)

    def _consume_library_review(self, review, kind):
        m = _manager()
        with self.lock:
            m._require(isinstance(review, dict), 'Reference review is invalid; review it again.')
            identity = review.get('review_id')
            cached = getattr(self, '_library_reviews', {}).pop(identity, None) if isinstance(identity, str) else None
            m._require(cached is not None and time.monotonic() - cached[0] <= REVIEW_SECONDS and
                       review == cached[1] and review.get('kind') == kind,
                       'Reference review expired or changed; review it again.')
            self._require_registry_identity(review)
            return deepcopy(cached[1])

    def _require_registry_identity(self, review):
        _manager()._require(self._registry_identity() == review['registry_sha256'],
                            'The reference library changed since review; review the operation again.')

    def _library_destination(self, value, *, create=False):
        m = _manager()
        m._require(isinstance(value, str) and value and len(value) < 32700 and Path(value).is_absolute(),
                   'Choose an absolute reference destination folder.')
        path = m._no_links(filesystem_path(value).absolute())
        if path == self.data and not path.exists():
            if create:
                return m._directory(path, create=True)
            return path
        return m._directory(path)

    def _destination_disk(self, path, needed=0):
        candidate = path
        while not candidate.exists():
            candidate = candidate.parent
        self._disk(candidate, needed)

    @staticmethod
    def _import_metadata(metadata):
        m = _manager()
        allowed = {'label': 300, 'species': 300, 'assembly': 300, 'assembly_accession': 128,
                   'source': 2000, 'release': 128}
        m._require(isinstance(metadata, dict) and not set(metadata) - set(allowed),
                   'Unsupported local reference description.')
        result = {}
        for key, value in metadata.items():
            m._require(isinstance(value, str) and len(value) <= allowed[key] and
                       all(ord(c) >= 32 and ord(c) != 127 for c in value),
                       'Reference descriptions must be bounded single-line text.')
            result[key] = value.strip()
        return result

    def _local_file(self, path_value, kind):
        m = _manager()
        m._require(isinstance(kind, str) and kind in m.KINDS and isinstance(path_value, str) and path_value and
                   len(path_value) < 32700 and Path(path_value).is_absolute(),
                   'Choose an absolute local FASTA or GTF file and a supported reference role.')
        path = m._no_links(filesystem_path(path_value).absolute())
        m._require(path.is_file(), 'A selected local reference file is missing.')
        name = m._filename(path.name)
        compressed = name.lower().endswith('.gz')
        output_name = m._filename(name[:-3] if compressed else name)
        extensions = ('.gtf',) if kind == 'annotation' else ('.fa', '.fasta', '.fna', '.ffn', '.faa', '.fas')
        m._require(output_name.lower().endswith(extensions),
                   'Local reference roles require FASTA sequence files or GTF annotation files (optionally gzip).')
        size = path.stat().st_size
        m._require(0 < size <= (m.MAX_DOWNLOAD_BYTES if compressed else m.MAX_EXPANDED_BYTES),
                   'The local reference is empty or exceeds the supported size.')
        return path, output_name, compressed

    def _read_local_reference(self, path, kind, compressed, cancel, event, output=None, *, phase='reviewing-import'):
        """Read once, computing source/expanded hashes and validating all gzip CRCs."""
        m = _manager()
        m._no_links(path)
        before = path.stat()
        source_hash, expanded_hash = hashlib.sha256(), hashlib.sha256()
        source_bytes = expanded_bytes = members = 0
        prefix = bytearray()
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if compressed else None
        last_event = 0.0
        with path.open('rb') as source:
            m._require(os.path.samestat(before, os.fstat(source.fileno())), 'Local reference changed while opening it.')
            while True:
                m._cancelled(cancel)
                block = source.read(m.CHUNK)
                if not block:
                    break
                source_hash.update(block); source_bytes += len(block)
                m._require(source_bytes <= (m.MAX_DOWNLOAD_BYTES if compressed else m.MAX_EXPANDED_BYTES),
                           'Local reference exceeds the supported size.')
                pending = block
                while pending:
                    m._cancelled(cancel)
                    if compressed:
                        if decoder.eof:
                            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                        try:
                            plain = decoder.decompress(pending, m.CHUNK)
                        except zlib.error as exc:
                            raise m.ReferenceError('Local gzip reference is corrupt or its CRC check failed.') from exc
                        pending = decoder.unused_data if decoder.eof else decoder.unconsumed_tail
                        if decoder.eof:
                            members += 1
                    else:
                        plain, pending = pending, b''
                    expanded_bytes += len(plain)
                    m._require(expanded_bytes <= m.MAX_EXPANDED_BYTES, 'Expanded local reference exceeds the supported size.')
                    if len(prefix) < 65536:
                        prefix.extend(plain[:65536 - len(prefix)])
                    expanded_hash.update(plain)
                    if output is not None and plain:
                        self._disk(Path(output.name).parent, len(plain))
                        output.write(plain)
                now = time.monotonic()
                if now - last_event >= .15:
                    m._event(event, phase, filename=path.name, bytes=source_bytes, total=before.st_size,
                             expanded_bytes=expanded_bytes, message='Checking local reference ' + path.name, cancellable=True)
                    last_event = now
            after = os.fstat(source.fileno())
        m._no_links(path)
        current = path.stat()
        m._require(source_bytes == before.st_size == after.st_size == current.st_size and
                   os.path.samestat(before, after) and os.path.samestat(before, current) and
                   before.st_mtime_ns == after.st_mtime_ns == current.st_mtime_ns,
                   'Local reference changed while it was being checked; review it again.')
        m._require(not compressed or decoder.eof and members > 0,
                   'Local gzip reference is incomplete; no reference was added.')
        m._check_format(prefix, kind, path.name)
        m._cancelled(cancel)
        return {'source_bytes': source_bytes, 'source_sha256': source_hash.hexdigest(),
                'bytes': expanded_bytes, 'sha256': expanded_hash.hexdigest()}

    def preview_import(self, files, metadata, destination, cancel=None, event=None):
        m = _manager()
        with self._library_operation():
            m._cancelled(cancel)
            self._library_document()
            registry_sha = self._registry_identity()
            destination_path = self._library_destination(destination)
            metadata = self._import_metadata(metadata)
            m._require(isinstance(files, list) and 1 <= len(files) <= len(m.KINDS),
                       'Select one to five distinct reference roles for local import.')
            selected, roles, names, paths = [], set(), set(), set()
            for item in files:
                m._require(isinstance(item, dict) and not set(item) - {'kind', 'path'}, 'Invalid local reference selection.')
                kind = item.get('kind')
                m._require(isinstance(kind, str) and kind not in roles, 'Select each reference role only once.')
                path, name, compressed = self._local_file(item.get('path'), kind)
                m._require(name.casefold() not in names and _path_key(path) not in paths,
                           'Local reference filenames or selected source files collide.')
                evidence = self._read_local_reference(path, kind, compressed, cancel, event)
                selected.append({'kind': kind, 'path': m._ordinary(path), 'filename': name,
                                 'source_filename': path.name, 'compressed': compressed, **evidence})
                roles.add(kind); names.add(name.casefold()); paths.add(_path_key(path))
            expanded = sum(item['bytes'] for item in selected)
            compressed = sum(item['source_bytes'] for item in selected if item['compressed'])
            m._require(expanded <= m.MAX_EXPANDED_BYTES and compressed <= m.MAX_DOWNLOAD_BYTES,
                       'Selected local references exceed the supported total size.')
            self._destination_disk(destination_path, expanded)
            review = {'schema': 1, 'kind': 'local-import', 'registry_sha256': registry_sha,
                      'destination': m._ordinary(destination_path), 'files': selected, 'metadata': metadata,
                      'bytes': expanded, 'source_bytes': sum(item['source_bytes'] for item in selected),
                      'notice': IMPORT_NOTICE}
            self._require_registry_identity(review)
            return self._remember_library_review(review)

    def import_local(self, review, cancel=None, event=None):
        m = _manager()
        with self._library_operation():
            review = self._consume_library_review(review, 'local-import')
            m._cancelled(cancel)
            destination = self._library_destination(review['destination'], create=True)
            self._destination_disk(destination, review['bytes'])
            identity = uuid.uuid4().hex
            final = destination / ('ref-' + identity[:16])
            m._require(not final.exists() and not final.is_symlink(), 'Reference destination already exists.')
            temporary = Path(tempfile.mkdtemp(prefix='_ref-import-', dir=destination))
            published = registered = False
            try:
                files = []
                for item in review['files']:
                    path, filename, compressed = self._local_file(item['path'], item['kind'])
                    m._require(filename == item['filename'] and compressed == item['compressed'],
                               'Local reference selection changed; review it again.')
                    with (temporary / filename).open('xb') as output:
                        evidence = self._read_local_reference(path, item['kind'], compressed, cancel, event,
                                                              output, phase='importing')
                        m._require(all(evidence[key] == item[key] for key in evidence),
                                   'Local reference bytes changed since review; review it again.')
                        output.flush(); os.fsync(output.fileno())
                    self._hash_reference_file({'path': str(temporary / filename), 'filename': filename,
                                               'bytes': evidence['bytes'], 'sha256': evidence['sha256']},
                                              cancel, event, phase='verifying-import')
                    files.append({'id': item['kind'], 'kind': item['kind'], 'label': LABELS[item['kind']],
                                  'filename': filename, 'path': m._ordinary(final / filename),
                                  'bytes': evidence['bytes'], 'sha256': evidence['sha256'],
                                  'source_filename': path.name, 'original_path': m._ordinary(path),
                                  'source_bytes': evidence['source_bytes'], 'source_sha256': evidence['source_sha256'],
                                  'format': 'gtf' if item['kind'] == 'annotation' else 'fasta',
                                  'validation': {'gzip_crc': 'passed' if compressed else 'not applicable',
                                                 'format_header': 'passed (basic prefix only)',
                                                 'sha256': 'computed locally; not a publisher signature'},
                                  **({'compressed_bytes': evidence['source_bytes'],
                                      'compressed_sha256': evidence['source_sha256']} if compressed else {})})
                metadata = review['metadata']
                record = {'schema': 1, 'id': identity, 'provider': 'local-import', 'provider_name': 'Local reference import',
                          'origin': 'local-import', 'user_declared': deepcopy(metadata), 'imported_at': _now(),
                          'label': metadata.get('label') or ' — '.join(value for value in
                              (metadata.get('species'), metadata.get('assembly'), 'Local reference import') if value),
                          'species': metadata.get('species', ''), 'assembly': metadata.get('assembly', ''),
                          'assembly_accession': metadata.get('assembly_accession', ''),
                          'release': metadata.get('release', ''), 'source': metadata.get('source', ''),
                          'folder': m._ordinary(final), 'receipt_path': m._ordinary(final / 'reference.json'),
                          'files': files, 'integrity_notice': IMPORT_NOTICE}
                self._write_receipt(temporary, record)
                with self._library_lease():
                    self._require_registry_identity(review)
                    document = self._library_document()
                    m._require(len(document['records']) < m.MAX_RECORDS, 'The local reference library is full.')
                    m._directory(destination)
                    m._require(not final.exists() and not final.is_symlink(), 'Reference destination already exists.')
                    m._cancelled(cancel)
                    m._event(event, 'publishing', message='Adding the verified local import.', cancellable=False)
                    os.rename(temporary, final); published = True
                    document['records'] = [*document['records'], record]
                    self._write_library(document); registered = True
                return self.snapshot()
            finally:
                if published and not registered:
                    shutil.rmtree(final, ignore_errors=True)
                if temporary.exists():
                    shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _write_receipt(temporary, record):
        m = _manager()
        raw = m._json_bytes({key: value for key, value in record.items() if key != 'receipt_sha256'})
        m._require(len(raw) <= m.MAX_RECEIPT_BYTES, 'Reference provenance is unexpectedly large.')
        with (temporary / 'reference.json').open('xb') as output:
            output.write(raw); output.flush(); os.fsync(output.fileno())
        record['receipt_sha256'] = hashlib.sha256(raw).hexdigest()

    def _hash_reference_file(self, item, cancel, event, output=None, *, phase=None):
        m = _manager()
        path = self._verify_file(item)
        digest, size = hashlib.sha256(), 0
        before = path.stat()
        with path.open('rb') as source:
            m._require(os.path.samestat(before, os.fstat(source.fileno())), 'Reference file changed while opening it.')
            while True:
                m._cancelled(cancel)
                block = source.read(m.CHUNK)
                if not block:
                    break
                size += len(block)
                m._require(size <= item['bytes'], 'Reference file grew during relocation.')
                digest.update(block)
                if output is not None:
                    self._disk(Path(output.name).parent, len(block))
                    output.write(block)
                m._event(event, phase or ('relocating' if output is not None else 'reviewing-relocation'),
                         filename=item['filename'], bytes=size, total=item['bytes'],
                         message='Verifying reference ' + item['filename'], cancellable=True)
            after = os.fstat(source.fileno())
        m._no_links(path)
        current = path.stat()
        m._require(size == item['bytes'] and digest.hexdigest() == item['sha256'] and
                   os.path.samestat(before, after) and os.path.samestat(before, current) and
                   before.st_mtime_ns == after.st_mtime_ns == current.st_mtime_ns,
                   'A reference changed or is damaged; relocation stopped and original files were preserved.')
        return size

    def preview_relocation(self, destination, cancel=None, event=None):
        m = _manager()
        with self._library_operation():
            m._cancelled(cancel)
            registry_sha = self._registry_identity()
            document = self._library_document()
            target = self._library_destination(destination)
            records = deepcopy(document['records'])
            resolved_target = target.resolve()
            m._require(_path_key(target) != _path_key(self._default_destination()) or
                       any(_path_key(Path(record['folder']).parent) != _path_key(target) for record in records),
                       'Choose a different default reference destination.')
            total = 0
            for record in records:
                folder = filesystem_path(record['folder']).resolve()
                m._require(resolved_target != folder and not resolved_target.is_relative_to(folder),
                           'The new library destination cannot be inside an existing reference bundle.')
                self._verify_record(record)
                for item in record['files']:
                    total += self._hash_reference_file(item, cancel, event)
            self._destination_disk(target, total)
            review = {'schema': 1, 'kind': 'library-relocation', 'registry_sha256': registry_sha,
                      'destination': m._ordinary(target), 'records': records,
                      'bundles': len(records), 'files': sum(len(record['files']) for record in records),
                      'bytes': total, 'notice': RELOCATION_NOTICE}
            self._require_registry_identity(review)
            return self._remember_library_review(review)

    def relocate_library(self, review, cancel=None, event=None):
        m = _manager()
        with self._library_operation():
            review = self._consume_library_review(review, 'library-relocation')
            m._cancelled(cancel)
            destination = self._library_destination(review['destination'], create=True)
            self._destination_disk(destination, review['bytes'])
            temporary = Path(tempfile.mkdtemp(prefix='_ref-relocate-', dir=destination))
            published, registered, copies = [], False, []
            try:
                for old in review['records']:
                    self._verify_record(old)
                    record = deepcopy(old)
                    name = 'ref-' + old['id'][:16] + '-' + uuid.uuid4().hex[:8]
                    folder, final = temporary / name, destination / name
                    m._require(not final.exists() and not final.is_symlink(), 'Reference destination already exists.')
                    folder.mkdir()
                    for item in record['files']:
                        with (folder / item['filename']).open('xb') as output:
                            self._hash_reference_file(item, cancel, event, output)
                            output.flush(); os.fsync(output.fileno())
                        self._hash_reference_file({**item, 'path': str(folder / item['filename'])},
                                                  cancel, event, phase='verifying-relocation')
                        item['path'] = m._ordinary(final / item['filename'])
                    record.update(folder=m._ordinary(final), receipt_path=m._ordinary(final / 'reference.json'),
                                  relocated_at=_now(), previous_location={'folder': old['folder'],
                                  'receipt_path': old['receipt_path'], 'receipt_sha256': old['receipt_sha256']})
                    self._write_receipt(folder, record)
                    copies.append((folder, final, record))
                with self._library_lease():
                    self._require_registry_identity(review)
                    document = self._library_document()
                    m._require(document['records'] == review['records'],
                               'The reference library changed since review; review relocation again.')
                    previous = list(document.get('previous_records', []))
                    locations = {os.path.normcase(record['folder']) for record in previous}
                    for record in document['records']:
                        if os.path.normcase(record['folder']) not in locations:
                            previous.append(record); locations.add(os.path.normcase(record['folder']))
                    m._require(len(previous) <= m.MAX_RECORDS,
                               'Historical reference locations are full; relocation was not committed.')
                    document.update(records=[record for _, _, record in copies], previous_records=previous,
                                    default_destination=m._ordinary(destination))
                    m._require(len(m._json_bytes(document)) <= m.MAX_REGISTRY_BYTES, 'The local reference library is full.')
                    m._directory(destination)
                    for _, final, _ in copies:
                        m._require(not final.exists() and not final.is_symlink(), 'Reference destination already exists.')
                    m._cancelled(cancel)
                    m._event(event, 'publishing', message='Switching to verified copies; original locations are retained.',
                             cancellable=False)
                    for folder, final, _ in copies:
                        os.rename(folder, final); published.append(final)
                    self._write_library(document); registered = True
                return self.snapshot()
            finally:
                if not registered:
                    for final in published:
                        shutil.rmtree(final, ignore_errors=True)
                if temporary.exists():
                    shutil.rmtree(temporary, ignore_errors=True)
