"""Publishing preparation retains exact pins and never keeps partial downloads."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_setup_catalogue as prepare


class SetupCataloguePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.lock = json.loads((ROOT / 'publishing/setup-assets.json').read_text())
        self.profile = json.loads((ROOT / 'workspace/setup-profile.json').read_text())

    def read(self):
        lock_path = self.root / 'lock.json'
        profile_path = self.root / 'profile.json'
        lock_path.write_text(json.dumps(self.lock))
        profile_path.write_text(json.dumps(self.profile))
        return prepare.read_lock(lock_path, profile_path)

    def test_locked_profile_has_current_selection_and_three_starter_packs(self):
        self.assertEqual(len(self.read()['packs']), 32)
        self.assertEqual({row['id'] for row in self.profile['packs'] if row['starter']},
                         {'align', 'bam', 'variants'})

    def test_changed_profile_pin_cannot_prepare_another_catalogue(self):
        self.profile['packs'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'profile and acquisition lock differ'):
            self.read()

    def test_url_must_name_the_exact_independent_release(self):
        self.lock['packs'][0]['downloadURL'] = self.lock['packs'][1]['downloadURL']
        with self.assertRaisesRegex(ValueError, 'immutable per-version'):
            self.read()

    def test_rejects_duplicate_ids_and_unapproved_hosts(self):
        self.lock['packs'].append(copy.deepcopy(self.lock['packs'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate setup pack ID'):
            self.read()
        self.lock['packs'].pop()
        self.lock['packs'][0]['downloadURL'] = 'https://untrusted.example/pack.zip'
        with self.assertRaisesRegex(ValueError, 'host is not approved'):
            self.read()

    def test_interrupted_download_cleans_partial_and_preserves_completed_files(self):
        completed = self.root / 'completed.zip'
        completed.write_bytes(b'previous successful pack')
        def fail_download(url, hosts, destination, limit, **kwargs):
            Path(destination).write_bytes(b'partial')
            raise ValueError('simulated interruption')
        with patch.object(prepare, '_download', side_effect=fail_download):
            with self.assertRaisesRegex(ValueError, 'simulated interruption'):
                prepare.acquire(self.lock['packs'][0], self.root, True)
        self.assertEqual(list(self.root.iterdir()), [completed])
        self.assertEqual(completed.read_bytes(), b'previous successful pack')

    def test_cached_archive_is_rehashed_and_fully_inspected_without_network(self):
        row = copy.deepcopy(self.lock['packs'][0])
        payload = b'cached test bytes'
        row.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        archive = self.root / row['archive']
        archive.write_bytes(payload)
        with patch.object(prepare, '_download') as download, patch.object(prepare, 'inspect_release', return_value=row) as inspect:
            result = prepare.acquire(row, self.root, False)
        download.assert_not_called()
        inspect.assert_called_once_with(archive)
        self.assertTrue(result['reusedArchive'])
        archive.write_bytes(b'tampered cache')
        with self.assertRaisesRegex(ValueError, 'Cached archive differs'):
            prepare.acquire(row, self.root, True)
        self.assertEqual(archive.read_bytes(), b'tampered cache')


if __name__ == '__main__':
    unittest.main()
