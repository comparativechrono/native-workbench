"""Reference library/download transaction tests with deterministic HTTP doubles."""
from copy import deepcopy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference_manager import ReferenceManager, ReferenceError, ReferenceCancelled, _bsd_update


def bsd(data):
    value = 0
    for byte in data:
        value = (value // 2 + (value % 2) * 32768 + byte) % 65536
    return value


class Response(io.BytesIO):
    def __init__(self, data, url, length=True, callback=None):
        super().__init__(data)
        self.url = url
        self.headers = {'ETag': 'fixture-etag', 'Last-Modified': 'Mon, 05 Oct 2026 00:00:00 GMT'}
        if length is not False:
            self.headers['Content-Length'] = str(len(data) if length is True else length)
        self.callback = callback
    def getcode(self):
        return 200
    def geturl(self):
        return self.url
    def read(self, length=-1):
        value = super().read(min(length, 31))
        if value and self.callback:
            self.callback()
        return value


class Provider:
    def __init__(self):
        self.calls = []
        self.data = {}
        self.files = []
        self.length = True
        self.callback = None
        self.fail_network = False
        self.add('genome', b'>chromosome1\nACGTNACGT\n')
        self.add('annotation', '##gtf-version 2\nchr1\tensembl\tgene\t1\t9\t.\t+\t.\tgene_id "g1"; gene_name "\u03b1";\n'.encode())
    def add(self, identity, plain, raw=None):
        raw = gzip.compress(plain, mtime=0) if raw is None else raw
        filename = identity + ('.gtf.gz' if identity == 'annotation' else '.fa.gz')
        url = 'https://ftp.ensembl.org/pub/release-116/' + filename
        self.data[url] = raw
        self.files = [item for item in self.files if item['id'] != identity]
        self.files.append({'id': identity, 'kind': identity, 'label': identity.title(), 'filename': filename,
                           'url': url, 'bytes': len(raw), 'format': 'gtf' if identity == 'annotation' else 'fasta',
                           'checksum': {'algorithm': 'bsd-sum', 'value': bsd(raw), 'blocks': (len(raw) + 1023) // 1024},
                           'checksum_manifest': {'url': url + '/CHECKSUMS', 'sha256': 'a'*64, 'text': 'published manifest\n'},
                           'sequence_scope': 'primary_assembly' if identity == 'genome' else None})
        return self.files[-1]
    def descriptor(self):
        return {'id': 'ensembl-archive', 'name': 'Ensembl archive', 'default_release': 116}
    def releases(self, **kwargs):
        self.calls.append('releases')
        return [116, 115]
    def species(self, release, query='', **kwargs):
        self.calls.append(('species', release, query))
        return [{'id': 'test_species', 'name': 'Test species', 'assembly': 'fixture1',
                 'assembly_accession': 'GCA_000000001.1', 'release': release}]
    def discover(self, release, species_id, **kwargs):
        return {'provider': 'ensembl-archive', 'release': release,
                'species': self.species(release)[0], 'assembly': 'fixture1',
                'assembly_accession': 'GCA_000000001.1', 'source_catalog': {'url': 'https://example/catalog', 'sha256': 'b'*64},
                'files': deepcopy(self.files)}
    def open_url(self, url, cancel=None):
        self.calls.append(('GET', url))
        if self.fail_network:
            raise AssertionError('Unexpected network request')
        return Response(self.data[url], url, self.length, self.callback)


class ReferenceManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'Application'
        self.root.mkdir()
        self.destination = Path(self.temp.name) / 'Reference data \u03b1'
        self.destination.mkdir()
        self.provider = Provider()
        self.manager = ReferenceManager(self.root, self.provider)
    def tearDown(self):
        self.temp.cleanup()
    def selection(self):
        return self.manager.discover(116, 'test_species')['discovery']['selection_id']
    def download(self, ids=None, **kwargs):
        return self.manager.download(self.selection(), ids or ['genome', 'annotation'], str(self.destination), **kwargs)
    def assert_no_download(self):
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(self.manager.snapshot()['local'], [])
    def test_offline_startup_and_snapshot_create_nothing(self):
        self.provider.fail_network = True
        self.assertEqual(self.manager.snapshot()['local'], [])
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])
    def test_default_destination_is_created_only_for_explicit_download(self):
        default = self.manager.snapshot()['default_destination']
        self.assertFalse(Path(default).exists())
        if os.name == 'nt':
            # The native UI receives the ordinary spelling, while the manager
            # retains a long-path IO spelling. Both identify the same default.
            self.assertNotEqual(str(self.manager.data), default)
            from pack_manager import filesystem_path
            self.assertEqual(filesystem_path(default), self.manager.data)
        result = self.manager.download(self.selection(), ['genome'], default)
        self.assertTrue(Path(result['local'][0]['folder']).is_relative_to(Path(default)))
        self.assertTrue(Path(default, 'library.json').is_file())
    def test_nondefault_missing_destination_is_not_created(self):
        destination = self.destination / 'not created'
        with self.assertRaisesRegex(ReferenceError, 'existing reference destination'):
            self.manager.download(self.selection(), ['genome'], str(destination))
        self.assertFalse(destination.exists())
        self.assertFalse(self.manager.data.exists())
        self.assertEqual(self.manager.snapshot()['local'], [])
    def test_explicit_search_preserves_release_and_species(self):
        result = self.manager.search(116, 'test')
        self.assertEqual(result['releases'], [116, 115])
        self.assertEqual(result['species'][0]['assembly'], 'fixture1')
        self.assertIn(('species', 116, 'test'), self.provider.calls)
    def test_successful_bundle_expands_hashes_and_records_receipt_offline(self):
        events = []
        result = self.download(event=events.append)
        self.assertEqual(len(result['local']), 1)
        record = result['local'][0]
        self.assertTrue(record['available'])
        self.assertEqual(record['status'], 'ready')
        self.assertEqual(record['label'], 'Test species — fixture1 — release 116')
        self.assertNotIn('{', record['label'])
        self.assertNotIn('text', record['files'][0]['checksum_manifest'])
        receipt_raw = Path(record['receipt_path']).read_bytes()
        self.assertEqual(hashlib.sha256(receipt_raw).hexdigest(), record['receipt_sha256'])
        receipt = json.loads(receipt_raw)
        self.assertEqual(receipt['files'][0]['checksum_manifest']['text'], 'published manifest\n')
        self.assertEqual(receipt['files'][0]['sequence_scope'], 'primary_assembly')
        for item in record['files']:
            plain = Path(item['path']).read_bytes()
            raw = self.provider.data[item['source_url']]
            self.assertEqual(plain, gzip.decompress(raw))
            self.assertEqual(item['sha256'], hashlib.sha256(plain).hexdigest())
            self.assertEqual(item['compressed_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertFalse(item['filename'].endswith('.gz'))
        self.assertFalse(events[-1]['cancellable'])
        self.provider.fail_network = True
        reopened = ReferenceManager(self.root, self.provider)
        self.assertEqual(reopened.snapshot()['local'], result['local'])
        self.assertEqual(reopened.record_folder(record['id']), record['folder'])
        resolved = reopened.resolve_file(record['id'], 'genome')
        self.assertEqual(resolved['record_label'], record['label'])
        self.assertEqual(resolved['path'], record['files'][0]['path'])
        provenance = reopened.provenance_for_path(resolved['path'], resolved['sha256'])
        self.assertEqual(provenance['file']['sha256'], resolved['sha256'])
        self.assertEqual(provenance['release'], 116)
        self.assertIsNone(reopened.provenance_for_path(self.destination / 'other.fa'))
    def test_client_cannot_change_cached_url_or_invent_file(self):
        snapshot = self.manager.discover(116, 'test_species')
        identity = snapshot['discovery']['selection_id']
        snapshot['discovery']['files'][0]['url'] = 'https://malicious.invalid/data'
        with self.assertRaisesRegex(ReferenceError, 'not in this reference discovery'):
            self.manager.download(identity, ['invented'], str(self.destination))
        result = self.manager.download(identity, ['genome'], str(self.destination))
        self.assertTrue(result['local'][0]['files'][0]['source_url'].startswith('https://ftp.ensembl.org/'))
    def test_expired_or_duplicate_selection_is_rejected(self):
        with self.assertRaisesRegex(ReferenceError, 'expired'):
            self.manager.download('x'*32, ['genome'], str(self.destination))
        with self.assertRaisesRegex(ReferenceError, 'distinct'):
            self.manager.download(self.selection(), ['genome', 'genome'], str(self.destination))
        self.assert_no_download()
    def test_cancel_before_network_and_after_first_chunk_cleanup(self):
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(ReferenceCancelled):
            self.manager.download(self.selection(), ['genome'], str(self.destination), cancel=cancel)
        self.assert_no_download()
        cancel.clear(); self.provider.callback = cancel.set
        with self.assertRaises(ReferenceCancelled):
            self.download(cancel=cancel)
        self.assert_no_download()
    def test_truncated_transfer_and_discovery_size_change_fail(self):
        self.provider.length = 10000
        with self.assertRaisesRegex(ReferenceError, 'size changed'):
            self.download()
        self.assert_no_download()
        self.provider.length = True
        for item in self.provider.files:
            item['bytes'] += 1
        with self.assertRaisesRegex(ReferenceError, 'size changed'):
            self.download()
        self.assert_no_download()
    def test_declared_http_length_is_verified_at_eof(self):
        for item in self.provider.files:
            item['bytes'] = None
        self.provider.length = 10000
        with self.assertRaisesRegex(ReferenceError, 'truncated'):
            self.download()
        self.assert_no_download()
    def test_gzip_crc_and_trailer_are_required(self):
        plain = b'>one\nACGT\n'
        raw = bytearray(gzip.compress(plain, mtime=0)); raw[-5] ^= 1
        self.provider.add('genome', plain, bytes(raw))
        with self.assertRaisesRegex(ReferenceError, 'CRC'):
            self.download(['genome'])
        self.assert_no_download()
        self.provider.add('genome', plain, gzip.compress(plain, mtime=0)[:-5])
        with self.assertRaisesRegex(ReferenceError, 'incomplete'):
            self.download(['genome'])
        self.assert_no_download()
    def test_provider_checksum_mismatch_fails_and_bsd_known_vector(self):
        self.assertEqual(_bsd_update(0, b'abc'), 16556)
        self.provider.files[0]['checksum']['value'] ^= 1
        with self.assertRaisesRegex(ReferenceError, 'BSD checksum'):
            self.download()
        self.assert_no_download()
    def test_html_with_valid_gzip_checksum_is_not_a_reference(self):
        self.provider.add('genome', b'<html>proxy error page</html>\n')
        with self.assertRaisesRegex(ReferenceError, 'FASTA'):
            self.download(['genome'])
        self.assert_no_download()
    def test_concatenated_gzip_members_and_unknown_size_work(self):
        first, second = b'>first\nACGT\n', b'>second\nTTAA\n'
        self.provider.add('genome', first + second, gzip.compress(first, mtime=0) + gzip.compress(second, mtime=0))
        self.provider.files[-1]['bytes'] = None
        self.provider.length = False
        item = self.download(['genome'])['local'][0]['files'][0]
        self.assertEqual(Path(item['path']).read_bytes(), first + second)
    def test_expansion_limit_and_initial_disk_floor(self):
        self.provider.add('genome', b'>one\n' + b'A' * 10000 + b'\n')
        with patch('reference_manager.MAX_EXPANDED_BYTES', 100), self.assertRaisesRegex(ReferenceError, 'Expanded'):
            self.download(['genome'])
        self.assert_no_download()
        with patch('reference_manager.shutil.disk_usage', return_value=SimpleNamespace(free=0)), self.assertRaisesRegex(ReferenceError, 'free disk'):
            self.download(['genome'])
        self.assert_no_download()
    def test_ongoing_disk_floor_prevents_publishing(self):
        with patch.object(self.manager, '_disk', side_effect=[None, ReferenceError('disk full')]), self.assertRaisesRegex(ReferenceError, 'disk full'):
            self.download(['genome'])
        self.assert_no_download()
    def test_collision_preserves_existing_directory(self):
        identity = self.selection()
        existing = self.destination / ('ref-' + '1'*16); existing.mkdir()
        marker = existing / 'keep.txt'; marker.write_text('keep')
        with patch('reference_manager.uuid.uuid4', return_value=SimpleNamespace(hex='1'*32)), self.assertRaisesRegex(ReferenceError, 'already exists'):
            self.manager.download(identity, ['genome'], str(self.destination))
        self.assertEqual(marker.read_text(), 'keep')
        self.assertEqual(list(self.destination.iterdir()), [existing])
    def test_second_download_creates_distinct_bundle_without_overwrite(self):
        first = self.download(['genome'])['local'][0]
        second = self.download(['genome'])['local'][-1]
        self.assertNotEqual(first['folder'], second['folder'])
        self.assertTrue(Path(first['files'][0]['path']).is_file())
        self.assertEqual(len(self.manager.snapshot()['local']), 2)
    def test_size_change_missing_file_and_equal_size_hash_change(self):
        record = self.download(['genome'])['local'][0]
        file = record['files'][0]
        path = Path(file['path']); original = path.read_bytes()
        path.write_bytes(original.replace(b'ACGTN', b'TTTTT'))
        self.manager.resolve_file(record['id'], file['id'])
        with self.assertRaisesRegex(ReferenceError, 'changed after retrieval'):
            self.manager.provenance_for_path(path, hashlib.sha256(path.read_bytes()).hexdigest())
        path.write_bytes(b'changed')
        self.assertFalse(self.manager.snapshot()['local'][0]['available'])
        with self.assertRaisesRegex(ReferenceError, 'changed'):
            self.manager.resolve_file(record['id'], file['id'])
        path.unlink()
        with self.assertRaisesRegex(ReferenceError, 'missing'):
            self.manager.resolve_file(record['id'], file['id'])
    def test_receipt_or_registry_metadata_tampering_is_rejected(self):
        record = self.download(['genome'])['local'][0]
        registry = json.loads(self.manager.registry.read_bytes())
        registry['records'][0]['release'] = 115
        self.manager.registry.write_text(json.dumps(registry))
        with self.assertRaisesRegex(ReferenceError, 'does not agree'):
            self.manager.resolve_file(record['id'], 'genome')
        registry['records'][0]['release'] = 116
        self.manager.registry.write_text(json.dumps(registry))
        Path(record['receipt_path']).write_text('{}')
        with self.assertRaisesRegex(ReferenceError, 'receipt has changed'):
            self.manager.resolve_file(record['id'], 'genome')
    def test_registry_rejects_duplicate_json_fields(self):
        self.manager.data.mkdir(parents=True)
        self.manager.registry.write_text('{"schema":1,"schema":1,"records":[]}')
        with self.assertRaisesRegex(ReferenceError, 'damaged'):
            self.manager.snapshot()
    def test_failed_registry_transaction_cleans_own_bundle_only(self):
        marker = self.destination / 'keep.txt'; marker.write_text('keep')
        with patch.object(self.manager, '_write_library', side_effect=OSError('write denied')), self.assertRaises(ReferenceError):
            self.download(['genome'])
        self.assertEqual(list(self.destination.iterdir()), [marker])
        self.assertEqual(self.manager.snapshot()['local'], [])
        self.assertFalse((self.manager.data / '_publish.lock').exists())
    def test_snapshot_error_after_commit_does_not_delete_ready_reference(self):
        identity = self.selection()
        with patch.object(self.manager, 'snapshot', side_effect=ReferenceError('report failed')), self.assertRaisesRegex(ReferenceError, 'report failed'):
            self.manager.download(identity, ['genome'], str(self.destination))
        result = self.manager.snapshot()
        self.assertEqual(len(result['local']), 1)
        self.assertTrue(result['local'][0]['available'])
    def test_another_instance_publication_lease_preserved_and_old_marker_does_not_block(self):
        from reference_transfer import file_lease
        self.manager.data.mkdir(parents=True)
        lock = self.manager.data / '_publish.lock'; lock.write_text('old interrupted instance')
        with file_lease(self.manager.data / '_library.lease'):
            with self.assertRaisesRegex(ReferenceError, 'Another Workbench'):
                self.download(['genome'])
        self.assertEqual(lock.read_text(), 'old interrupted instance')
        self.assert_no_download()
        self.assertEqual(len(self.download(['genome'])['local']), 1)
    def test_snapshot_bounds_response_and_reports_omitted_records(self):
        self.download(['genome'])
        with patch('reference_manager.MAX_SNAPSHOT_LOCAL_BYTES', 1):
            result = self.manager.snapshot()
        self.assertEqual(result['local'], [])
        self.assertEqual(result['omitted_local'], 1)
        self.assertIn('older bundles remain on disk', result['notice'])
    def test_symlink_destination_and_changed_file_link_rejected(self):
        link = Path(self.temp.name) / 'linked'
        try:
            link.symlink_to(self.destination, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation is unavailable for this account')
        with self.assertRaisesRegex(ReferenceError, 'links or junctions'):
            self.manager.download(self.selection(), ['genome'], str(link))
        record = self.download(['genome'])['local'][0]
        file = Path(record['files'][0]['path']); copy = self.destination / 'copy.fa'
        shutil.copyfile(file, copy); file.unlink(); file.symlink_to(copy)
        with self.assertRaisesRegex(ReferenceError, 'links or junctions'):
            self.manager.resolve_file(record['id'], 'genome')


if __name__ == '__main__':
    unittest.main()
