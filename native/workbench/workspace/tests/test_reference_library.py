"""Local reference import/relocation contracts; no network or scientific executables."""
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_manager import ReferenceManager, ReferenceError, ReferenceCancelled
from reference_provenance import collect_references, methods_text
from test_reference_manager import Provider


class ReferenceLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='local reference library ')
        self.base = Path(self.temp.name)
        self.root = self.base / 'Application'; self.root.mkdir()
        self.inputs = self.base / 'Original sources'; self.inputs.mkdir()
        self.target = self.base / 'Reference data α'; self.target.mkdir()
        self.new = self.base / 'Relocated library β'; self.new.mkdir()
        self.genome = self.inputs / 'genome.fa'; self.genome.write_bytes(b'>chr1\nACGTACGT\n')
        self.gtf = self.inputs / 'genes.gtf'
        self.gtf.write_bytes(b'chr1\tfixture\tgene\t1\t8\t.\t+\t.\tgene_id "g1";\n')
        self.metadata = {'species': 'Fixture species', 'assembly': 'User assembly',
                         'assembly_accession': 'User accession', 'source': 'My assembly notebook', 'release': 'v1'}
        self.provider = Provider(); self.provider.fail_network = True
        self.manager = ReferenceManager(self.root, self.provider)

    def tearDown(self):
        self.temp.cleanup()

    def preview(self, files=None, metadata=None, destination=None, **kwargs):
        return self.manager.preview_import(files or [{'kind': 'genome', 'path': str(self.genome)}],
            self.metadata if metadata is None else metadata, str(destination or self.target), **kwargs)

    def imported(self, **kwargs):
        return self.manager.import_local(self.preview(**kwargs))['local'][0]

    def test_review_has_hashes_and_creates_no_library_or_copy(self):
        result = self.preview()
        self.assertEqual(result['files'][0]['sha256'], hashlib.sha256(self.genome.read_bytes()).hexdigest())
        self.assertEqual(result['source_bytes'], self.genome.stat().st_size)
        self.assertIn('user-declared', result['notice'])
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertFalse(self.manager.registry.exists())
        self.assertEqual(self.provider.calls, [])

    def test_local_import_owned_copy_receipt_and_offline_provenance(self):
        original = self.genome.read_bytes()
        result = self.imported()
        self.assertEqual(result['provider'], 'local-import')
        self.assertEqual(result['origin'], 'local-import')
        self.assertEqual(result['user_declared'], self.metadata)
        self.assertNotIn('downloaded_at', result)
        self.assertEqual(self.genome.read_bytes(), original)
        item = result['files'][0]
        self.assertEqual(Path(item['path']).read_bytes(), original)
        self.assertEqual(item['source_sha256'], item['sha256'])
        receipt_raw = Path(result['receipt_path']).read_bytes()
        self.assertEqual(hashlib.sha256(receipt_raw).hexdigest(), result['receipt_sha256'])
        self.assertEqual(json.loads(receipt_raw)['user_declared'], self.metadata)
        reopened = ReferenceManager(self.root, self.provider)
        provenance = reopened.provenance_for_path(item['path'], item['sha256'])
        self.assertEqual(provenance['origin'], 'local-import')
        text = methods_text({item['path']: provenance}, {item['path']}, verified=True)
        self.assertIn('user-declared species Fixture species', text)
        self.assertIn('Imported locally', text)
        self.assertIn('User-declared source: My assembly notebook', text)
        self.assertNotIn('Retrieved ', text)
        self.assertNotIn('download receipts', text)
        self.assertEqual(self.provider.calls, [])

    def test_gzip_multiple_members_expands_and_records_both_identities(self):
        path = self.inputs / 'multi.fa.gz'
        raw = gzip.compress(b'>one\nACGT\n', mtime=0) + gzip.compress(b'>two\nTGCA\n', mtime=0)
        path.write_bytes(raw)
        record = self.imported(files=[{'kind': 'genome', 'path': str(path)}])
        item = record['files'][0]
        self.assertEqual(item['compressed_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(item['sha256'], hashlib.sha256(gzip.decompress(raw)).hexdigest())
        self.assertEqual(Path(item['path']).read_bytes(), gzip.decompress(raw))
        self.assertTrue(path.exists())

    def test_all_five_roles_are_independent_and_gtf_is_verified(self):
        files = [{'kind': 'annotation', 'path': str(self.gtf)}]
        for kind in ('genome', 'cdna', 'ncrna', 'protein'):
            path = self.inputs / (kind + '.fa'); path.write_bytes(b'>sequence\nACGT\n')
            files.append({'kind': kind, 'path': str(path)})
        record = self.imported(files=files)
        self.assertEqual({item['id'] for item in record['files']}, {item['kind'] for item in files})
        self.assertEqual(len(record['files']), 5)

    def test_changed_bytes_after_review_reject_even_same_length(self):
        review = self.preview()
        self.genome.write_bytes(self.genome.read_bytes().replace(b'ACGT', b'AAAA'))
        with self.assertRaisesRegex(ReferenceError, 'bytes changed'):
            self.manager.import_local(review)
        self.assertFalse(self.manager.registry.exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_review_tampering_and_replay_reject(self):
        review = self.preview(); changed = deepcopy(review); changed['metadata']['assembly'] = 'forged'
        with self.assertRaisesRegex(ReferenceError, 'expired or changed'):
            self.manager.import_local(changed)
        review = self.preview(); self.manager.import_local(review)
        with self.assertRaisesRegex(ReferenceError, 'expired or changed'):
            self.manager.import_local(review)

    def test_expired_review_reject(self):
        review = self.preview()
        with patch('reference_library.time.monotonic', return_value=10**15):
            with self.assertRaisesRegex(ReferenceError, 'expired'):
                self.manager.import_local(review)

    def test_other_instance_import_makes_review_stale(self):
        review = self.preview()
        other = ReferenceManager(self.root, self.provider)
        other.import_local(other.preview_import([{'kind': 'genome', 'path': str(self.genome)}], {}, str(self.target)))
        raw = self.manager.registry.read_bytes()
        with self.assertRaisesRegex(ReferenceError, 'changed since review'):
            self.manager.import_local(review)
        self.assertEqual(self.manager.registry.read_bytes(), raw)
        self.assertEqual(len(self.manager.snapshot()['local']), 1)

    def test_invalid_format_truncated_gzip_and_bad_crc_reject_without_copy(self):
        cases = {'bad.fa': b'not FASTA\n', 'bad.gtf': b'chr1\tbad\n',
                 'truncated.fa.gz': gzip.compress(b'>chr1\nACGT\n')[:-3],
                 'crc.fa.gz': gzip.compress(b'>chr1\nACGT\n')[:-8] + b'12345678'}
        for filename, data in cases.items():
            with self.subTest(filename=filename):
                path = self.inputs / filename; path.write_bytes(data)
                with self.assertRaises(ReferenceError):
                    self.preview(files=[{'kind': 'annotation' if filename.endswith('.gtf') else 'genome', 'path': str(path)}])
        self.assertEqual(list(self.target.iterdir()), [])

    def test_unrecognized_extension_role_duplicates_and_collisions_reject(self):
        for files in ([{'kind': 'bed', 'path': str(self.genome)}],
                      [{'kind': 'genome', 'path': str(self.genome)}] * 2,
                      [{'kind': 'genome', 'path': str(self.genome)}, {'kind': 'cdna', 'path': str(self.genome)}]):
            with self.assertRaises(ReferenceError):
                self.preview(files=files)
        txt = self.inputs / 'reference.txt'; txt.write_bytes(self.genome.read_bytes())
        with self.assertRaisesRegex(ReferenceError, 'FASTA'):
            self.preview(files=[{'kind': 'genome', 'path': str(txt)}])
        with self.assertRaisesRegex(ReferenceError, 'description'):
            self.preview(metadata={'provider': 'forged-provider'})
        with self.assertRaisesRegex(ReferenceError, 'single-line'):
            self.preview(metadata={'source': 'first\nsecond'})

    def test_cancel_review_and_copy_leaves_original_and_no_bundle(self):
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(ReferenceCancelled):
            self.preview(cancel=cancel)
        cancel.clear(); review = self.preview()
        def stop(event):
            if event['phase'] == 'importing':
                cancel.set()
        with self.assertRaises(ReferenceCancelled):
            self.manager.import_local(review, cancel=cancel, event=stop)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertFalse(self.manager.registry.exists())
        self.assertTrue(self.genome.is_file())

    def test_corrupt_written_import_copy_is_detected(self):
        review = self.preview(); original = self.manager._read_local_reference
        def corrupt(*args, **kwargs):
            result = original(*args, **kwargs)
            output = args[5] if len(args) > 5 else kwargs.get('output')
            if output is not None:
                output.seek(0); output.write(b'!')
            return result
        with patch.object(self.manager, '_read_local_reference', side_effect=corrupt):
            with self.assertRaisesRegex(ReferenceError, 'changed or is damaged'):
                self.manager.import_local(review)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_import_commit_failure_rolls_back_copies(self):
        review = self.preview()
        with patch.object(self.manager, '_write_library', side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):
                self.manager.import_local(review)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertFalse(self.manager.registry.exists())

    def test_import_default_destination_created_only_when_confirmed(self):
        destination = self.manager.snapshot()['default_destination']
        review = self.preview(destination=Path(destination))
        self.assertFalse(Path(destination).exists())
        record = self.manager.import_local(review)['local'][0]
        self.assertTrue(Path(record['folder']).is_relative_to(Path(destination)))

    def test_relocation_keeps_old_bytes_and_both_location_provenance(self):
        original = self.imported(); item = original['files'][0]
        old_receipt = Path(original['receipt_path']).read_bytes()
        old_file = Path(item['path']).read_bytes()
        review = self.manager.preview_relocation(str(self.new))
        self.assertIn('No old files are deleted', review['notice'])
        result = self.manager.relocate_library(review)
        copied = result['local'][0]
        self.assertEqual(copied['id'], original['id'])
        self.assertNotEqual(copied['folder'], original['folder'])
        self.assertEqual(result['default_destination'], str(self.new))
        self.assertEqual(Path(item['path']).read_bytes(), old_file)
        self.assertEqual(Path(original['receipt_path']).read_bytes(), old_receipt)
        self.assertEqual(Path(copied['files'][0]['path']).read_bytes(), old_file)
        reopened = ReferenceManager(self.root, self.provider)
        self.assertEqual(reopened.snapshot()['default_destination'], str(self.new))
        old = reopened.provenance_for_path(item['path'], item['sha256'])
        new = reopened.provenance_for_path(copied['files'][0]['path'], item['sha256'])
        self.assertEqual(old['receipt_sha256'], original['receipt_sha256'])
        self.assertEqual(new['receipt_sha256'], copied['receipt_sha256'])
        self.assertEqual(old['file']['path'], item['path'])
        self.assertEqual(len(reopened._previous_records()), 1)

    def test_repeated_relocation_retains_each_old_location_and_download_receipts(self):
        self.provider.fail_network = False
        selection = self.manager.discover(116, 'test_species')['discovery']['selection_id']
        original = self.manager.download(selection, ['genome'], str(self.target))['local'][0]
        self.provider.fail_network = True
        self.manager.relocate_library(self.manager.preview_relocation(str(self.new)))
        last = self.base / 'Third library'; last.mkdir()
        result = self.manager.relocate_library(self.manager.preview_relocation(str(last)))
        self.assertEqual(len(self.manager._previous_records()), 2)
        old = self.manager.provenance_for_path(original['files'][0]['path'], original['files'][0]['sha256'])
        self.assertEqual(old['provider'], 'ensembl-archive')
        self.assertEqual(old['receipt_sha256'], original['receipt_sha256'])
        self.assertEqual(result['default_destination'], str(last))

    def test_relocation_failure_or_cancellation_leaves_original_registry_and_files(self):
        original = self.imported(); raw = self.manager.registry.read_bytes()
        review = self.manager.preview_relocation(str(self.new))
        cancel = threading.Event()
        def stop(event):
            if event['phase'] == 'relocating':
                cancel.set()
        with self.assertRaises(ReferenceCancelled):
            self.manager.relocate_library(review, cancel=cancel, event=stop)
        self.assertEqual(self.manager.registry.read_bytes(), raw)
        self.assertEqual(list(self.new.iterdir()), [])
        review = self.manager.preview_relocation(str(self.new))
        with patch.object(self.manager, '_write_library', side_effect=OSError('write failed')):
            with self.assertRaises(OSError):
                self.manager.relocate_library(review)
        self.assertEqual(self.manager.registry.read_bytes(), raw)
        self.assertEqual(list(self.new.iterdir()), [])
        self.assertTrue(Path(original['folder']).is_dir())

    def test_changed_reference_blocks_relocation_and_preserves_evidence(self):
        record = self.imported(); raw = self.manager.registry.read_bytes()
        review = self.manager.preview_relocation(str(self.new))
        path = Path(record['files'][0]['path']); path.write_bytes(path.read_bytes().replace(b'ACGT', b'TTTT'))
        with self.assertRaisesRegex(ReferenceError, 'changed or is damaged'):
            self.manager.relocate_library(review)
        self.assertEqual(self.manager.registry.read_bytes(), raw)
        self.assertEqual(list(self.new.iterdir()), [])

    def test_receipt_tamper_and_nested_destination_block_relocation(self):
        record = self.imported()
        with self.assertRaisesRegex(ReferenceError, 'inside an existing'):
            self.manager.preview_relocation(record['folder'])
        receipt = Path(record['receipt_path']); receipt.write_bytes(receipt.read_bytes() + b' ')
        with self.assertRaisesRegex(ReferenceError, 'receipt has changed'):
            self.manager.preview_relocation(str(self.new))

    def test_empty_library_can_set_a_default_explicitly(self):
        review = self.manager.preview_relocation(str(self.new))
        self.assertEqual(review['bundles'], 0)
        result = self.manager.relocate_library(review)
        self.assertEqual(result['local'], [])
        self.assertEqual(result['default_destination'], str(self.new))
        self.assertEqual(list(self.new.iterdir()), [])

    def test_registry_extensions_survive_new_import_and_download(self):
        self.imported()
        self.manager.relocate_library(self.manager.preview_relocation(str(self.new)))
        before = self.manager._library_document()
        self.imported()
        self.provider.fail_network = False
        selection = self.manager.discover(116, 'test_species')['discovery']['selection_id']
        self.manager.download(selection, ['genome'], str(self.new))
        after = self.manager._library_document()
        self.assertEqual(after['previous_records'], before['previous_records'])
        self.assertEqual(after['default_destination'], before['default_destination'])
        self.assertEqual(len(after['records']), 3)

    def test_symlink_source_or_destination_rejected(self):
        link = self.inputs / 'linked.fa'
        try:
            link.symlink_to(self.genome)
        except OSError as exc:
            self.skipTest('This host cannot create the symlink fixture: ' + str(exc))
        with self.assertRaisesRegex(ReferenceError, 'symbolic links or junctions'):
            self.preview(files=[{'kind': 'genome', 'path': str(link)}])
        folder = self.base / 'linked destination'; folder.symlink_to(self.target, target_is_directory=True)
        with self.assertRaisesRegex(ReferenceError, 'symbolic links or junctions'):
            self.preview(destination=folder)

    def test_library_lease_contention_preserves_registry_and_rolls_back_copy(self):
        from reference_transfer import file_lease
        self.imported()
        raw = self.manager.registry.read_bytes()
        review = self.preview()
        before = set(self.target.iterdir())
        with file_lease(self.manager.data / '_library.lease'):
            with self.assertRaisesRegex(ReferenceError, 'Another Workbench'):
                self.manager.import_local(review)
        self.assertEqual(self.manager.registry.read_bytes(), raw)
        self.assertEqual(set(self.target.iterdir()), before)

    def test_frozen_run_and_new_old_path_run_keep_original_receipt_after_relocation(self):
        from catalog import load_catalog
        from engine import Engine
        from test_pack_versions import make_pack, RecordingBackend
        make_pack(self.root, '1.0.0')
        original = self.imported(); item = original['files'][0]
        graph = {'schema': 1, 'name': 'Reference preservation', 'sources': [
            {'id': 'input-1', 'type': 'file', 'files': {'source': item['path']}}], 'nodes': [
            {'id': 'step-1', 'tool': 'example/process', 'params': {}, 'inputs': {'source': ['input-1']}}]}
        engine = Engine(self.root, load_catalog(self.root), backend=RecordingBackend())
        plan = engine.prepare(graph, self.root)
        frozen_plan = (Path(plan['folder']) / 'plan.json').read_bytes()
        frozen_receipt = (Path(plan['folder']) / 'reference-provenance.json').read_bytes()
        self.manager.relocate_library(self.manager.preview_relocation(str(self.new)))
        self.assertEqual((Path(plan['folder']) / 'plan.json').read_bytes(), frozen_plan)
        self.assertEqual((Path(plan['folder']) / 'reference-provenance.json').read_bytes(), frozen_receipt)
        result = engine.execute(plan)
        self.assertTrue(result['success'], result)
        self.assertEqual(next(iter(result['references'].values()))['receipt_sha256'], original['receipt_sha256'])
        later = engine.prepare(graph, self.root)
        self.assertEqual(next(iter(later['references'].values()))['receipt_sha256'], original['receipt_sha256'])

    def test_malformed_historical_registry_fails_closed(self):
        self.imported()
        document = self.manager._library_document(); document['previous_records'] = [{'id': 'broken'}]
        self.manager.registry.write_text(json.dumps(document))
        before = self.manager.registry.read_bytes()
        with self.assertRaisesRegex(ReferenceError, 'historical'):
            self.preview()
        self.assertEqual(self.manager.registry.read_bytes(), before)

    def test_limits_and_disk_shortage_reject_without_copy(self):
        with patch('reference_manager.MAX_EXPANDED_BYTES', 4):
            with self.assertRaisesRegex(ReferenceError, 'supported size'):
                self.preview()
        with patch.object(self.manager, '_disk', side_effect=ReferenceError('not enough free disk space')):
            with self.assertRaisesRegex(ReferenceError, 'disk space'):
                self.preview()
        self.assertEqual(list(self.target.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
