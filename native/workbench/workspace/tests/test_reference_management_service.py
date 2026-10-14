"""Native transport contracts for explicit reference reviews and paused downloads."""
import copy
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_reference_service import Manager, catalog_fixture
from desktop_host import DesktopHost
from desktop_model import DesktopModel
from service import Workbench


class ManagementFixture(Manager):
    def __init__(self, root):
        super().__init__(root)
        self.paused = threading.Event()
        self.pending = []
        self.committed = []

    def snapshot(self):
        return dict(super().snapshot(), pending=copy.deepcopy(self.pending))

    def search(self, release, query, *, provider_id=None, cancel, event):
        return self._work('search', (provider_id, release, query), cancel, event)

    def discover(self, release, species_id, *, provider_id=None, cancel, event):
        return self._work('discover', (provider_id, release, species_id), cancel, event)

    def pause(self):
        self.paused.set()

    def download(self, selection_id, file_ids, destination, *, cancel, event):
        from reference_manager import ReferencePaused
        self.started.set()
        self.pending = [{'id': 'a' * 32, 'status': 'downloading'}]
        while not self.release.wait(.01):
            if cancel.is_set():
                self.pending = []
                raise InterruptedError('Discarded incomplete download.')
            if self.paused.is_set():
                self.pending[0]['status'] = 'paused'
                raise ReferencePaused('Paused; incomplete bytes retained.')
        return self.snapshot()

    def resume(self, job_id, *, cancel, event):
        self.committed.append(('resume', job_id))
        self.pending = []
        return self.snapshot()

    def discard(self, job_id):
        self.committed.append(('discard', job_id))
        self.pending = []
        return self.snapshot()

    def preview_import(self, files, metadata, destination, *, cancel, event):
        return {'kind': 'import', 'files': copy.deepcopy(files), 'metadata': copy.deepcopy(metadata),
                'destination': destination, 'notice': 'Metadata is user-declared.'}

    def preview_relocation(self, destination, *, cancel, event):
        return {'kind': 'relocate', 'destination': destination, 'records': [],
                'notice': 'Original files are retained.'}

    def import_local(self, review, *, cancel, event):
        self.committed.append(('import', copy.deepcopy(review)))
        return self.snapshot()

    def relocate_library(self, review, *, cancel, event):
        self.committed.append(('relocate', copy.deepcopy(review)))
        return self.snapshot()


class ReferenceManagementServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = Workbench(self.root, catalog=catalog_fixture())
        self.manager = ManagementFixture(self.root)
        self.app._reference_manager = self.manager
        self.model = DesktopModel(self.root, self.app.catalog)
        self.host = DesktopHost(self.root, app=self.app, model=self.model)

    def tearDown(self):
        self.manager.release.set()
        self.host.close(grace=2)
        self.tmp.cleanup()

    def complete(self, action, params):
        self.host.dispatch('references/' + action, params)
        self.app._reference_worker.join(3)
        self.assertFalse(self.app._reference_worker.is_alive())
        return self.host.dispatch('references/status', {})

    def preview(self):
        return self.complete('import-preview', {'files': [{'kind': 'genome', 'path': str(self.manager.path)}],
                              'metadata': {'species': 'Example species', 'assembly': 'Declared assembly'},
                              'destination': str(self.root)})['review']

    def test_versioned_refseq_lookup_is_distinct_from_archive_release(self):
        self.manager.release.set()
        self.complete('search', {'provider_id': 'ncbi-refseq', 'query': 'GCF_000146045.2'})
        self.assertEqual(self.manager.calls[-1], ('search', ('ncbi-refseq', 'assembly', 'GCF_000146045.2')))
        self.complete('discover', {'provider_id': 'ncbi-refseq', 'species_id': 'GCF_000146045.2'})
        self.assertEqual(self.manager.calls[-1], ('discover', ('ncbi-refseq', 'assembly', 'GCF_000146045.2')))
        for params in ({'provider_id': 'custom-url'}, {'provider_id': 'ncbi-refseq', 'release': 116},
                       {'provider_id': 'ensembl-archive', 'release': 'assembly'}, {'url': 'https://example.test'}):
            with self.assertRaises(ValueError):
                self.host.dispatch('references/search', params)

    def test_preview_never_imports_or_changes_graph_and_requires_one_use_token(self):
        before = copy.deepcopy(self.model.graph)
        review = self.preview()
        self.assertEqual(review['kind'], 'import')
        self.assertFalse(self.manager.committed)
        self.assertEqual(self.model.graph, before)
        with self.assertRaises(ValueError):
            self.host.dispatch('references/import', {'token': review['token'], 'files': []})
        with self.assertRaises(ValueError):
            self.host.dispatch('references/relocate', {'token': review['token']})
        result = self.complete('import', {'token': review['token']})
        self.assertEqual(result['operation']['status'], 'completed')
        self.assertIsNone(result['review'])
        self.assertEqual(self.manager.committed[-1][0], 'import')
        self.assertEqual(self.model.graph, before)
        with self.assertRaisesRegex(ValueError, 'review'):
            self.host.dispatch('references/import', {'token': review['token']})

    def test_expired_and_superseded_reviews_cannot_commit(self):
        first = self.preview()
        second = self.preview()
        with self.assertRaises(ValueError):
            self.host.dispatch('references/import', {'token': first['token']})
        self.app._reference_review['created'] -= 901
        self.assertIsNone(self.host.dispatch('references/status', {})['review'])
        with self.assertRaises(ValueError):
            self.host.dispatch('references/import', {'token': second['token']})
        self.assertFalse(self.manager.committed)

    def test_review_response_cannot_change_private_commit(self):
        review = self.preview()
        review['metadata']['assembly'] = 'Forged assembly'
        self.complete('import', {'token': review['token']})
        committed = self.manager.committed[-1][1]
        self.assertEqual(committed['metadata']['assembly'], 'Declared assembly')
        self.assertNotIn('token', committed)

    def test_relocation_uses_explicit_review_and_keeps_graph_paths(self):
        before = copy.deepcopy(self.model.graph)
        state = self.complete('relocate-preview', {'destination': str(self.root)})
        self.assertFalse(self.manager.committed)
        self.assertEqual(state['review']['kind'], 'relocate')
        self.complete('relocate', {'token': state['review']['token']})
        self.assertEqual(self.manager.committed[-1][0], 'relocate')
        self.assertEqual(self.model.graph, before)

    def test_pause_retains_pending_work_and_resume_is_explicit(self):
        self.host.dispatch('references/download', {'selection_id': 'fixture', 'file_ids': ['genome'],
                                                  'destination': str(self.root)})
        self.assertTrue(self.manager.started.wait(2))
        self.host.dispatch('references/pause', {})
        self.app._reference_worker.join(3)
        state = self.host.dispatch('references/status', {})
        self.assertEqual(state['operation']['status'], 'paused')
        self.assertFalse(state['operation']['active'])
        self.assertFalse(state['operation']['success'])
        self.assertEqual(state['pending'][0]['status'], 'paused')
        self.assertFalse(self.manager.committed)
        state = self.complete('resume', {'job_id': state['pending'][0]['id']})
        self.assertEqual(state['operation']['status'], 'completed')
        self.assertEqual(state['pending'], [])

    def test_cancel_discards_incomplete_work_and_pause_requires_active_transfer(self):
        with self.assertRaises(ValueError):
            self.host.dispatch('references/pause', {})
        self.host.dispatch('references/download', {'selection_id': 'fixture', 'file_ids': ['genome'],
                                                  'destination': str(self.root)})
        self.assertTrue(self.manager.started.wait(2))
        self.host.dispatch('references/cancel', {})
        self.app._reference_worker.join(3)
        state = self.host.dispatch('references/status', {})
        self.assertEqual(state['operation']['status'], 'cancelled')
        self.assertEqual(state['pending'], [])

    def test_discard_invalidates_review_without_touching_completed_references(self):
        review = self.preview()
        local = copy.deepcopy(self.manager.local)
        state = self.complete('discard', {'job_id': 'a' * 32})
        self.assertEqual(state['local'], local)
        self.assertIsNone(state['review'])
        with self.assertRaises(ValueError):
            self.host.dispatch('references/import', {'token': review['token']})

    def test_invalid_local_file_requests_rejected_before_worker_starts(self):
        common = {'files': [{'kind': 'genome', 'path': str(self.manager.path)}], 'destination': str(self.root)}
        invalid = [dict(common, files=[]), dict(common, files=common['files'] * 2),
                   dict(common, metadata={'provider_verified': True}), dict(common, metadata={'species': ['not text']}),
                   dict(common, files=[{'kind': 'genome', 'path': 'relative.fa'}]),
                   dict(common, files=[{'kind': 'database', 'path': str(self.manager.path)}]),
                   dict(common, files=[{'kind': [], 'path': str(self.manager.path)}]),
                   dict(common, destination='relative-folder')]
        for params in invalid:
            with self.subTest(params=params):
                with self.assertRaises(ValueError):
                    self.host.dispatch('references/import-preview', params)
        self.assertIsNone(self.app._reference_worker)
        self.assertFalse(self.manager.committed)

    def test_missing_analysis_graph_reports_validation_error_without_starting(self):
        with self.assertRaisesRegex(ValueError, 'workflow'):
            self.app.start({'output_folder': str(self.root)})
        self.assertFalse(self.app.runs)

    def test_source_change_after_real_review_is_rejected_without_import(self):
        from reference_manager import ReferenceManager
        real = ReferenceManager(self.root)
        self.app._reference_manager = real
        review = self.preview()
        self.manager.path.write_text('>chr1\nTTTT\n')
        result = self.complete('import', {'token': review['token']})
        self.assertEqual(result['operation']['status'], 'failed')
        self.assertEqual(real.snapshot()['local'], [])

    def test_real_import_and_relocation_keep_offline_old_and_new_path_provenance(self):
        from reference_manager import ReferenceManager
        real = ReferenceManager(self.root)
        self.app._reference_manager = real
        with patch('socket.socket', side_effect=AssertionError('No network for local reference management')):
            review = self.preview()
            state = self.complete('import', {'token': review['token']})
            self.assertEqual(state['operation']['status'], 'completed', state['operation'])
            old = state['local'][0]['files'][0]
            old_path = Path(old['path'])
            moved = self.root / 'Moved reference library'
            moved.mkdir()
            review = self.complete('relocate-preview', {'destination': str(moved)})['review']
            state = self.complete('relocate', {'token': review['token']})
            self.assertEqual(state['operation']['status'], 'completed', state['operation'])
            new = state['local'][0]['files'][0]
            self.assertNotEqual(new['path'], old['path'])
            self.assertEqual(old_path.read_bytes(), Path(new['path']).read_bytes())
            self.assertEqual(real.provenance_for_path(old['path'], old['sha256'])['file']['sha256'], old['sha256'])
            self.assertEqual(real.provenance_for_path(new['path'], new['sha256'])['file']['sha256'], new['sha256'])
            self.assertEqual(Path(real.snapshot()['default_destination']), moved)


if __name__ == '__main__':
    unittest.main(verbosity=2)
