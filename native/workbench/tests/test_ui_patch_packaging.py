"""Patch ownership and committed-source checks; no native Windows execution."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_ui_patch_candidate as candidate


def put(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class PatchOwnership(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name)
        self.base, self.target = self.parent / 'baseline', self.parent / 'candidate'
        for folder in candidate.PACKS:
            put(self.base, 'packs/' + folder + '/pack.ini', folder.encode())
        for name in ('runtime/python/python.exe', 'workspace/setup-profile.json', 'workspace/catalog-sources.json'):
            put(self.base, name, name.encode())
        shutil.copytree(self.base, self.target)
        self.old = {'version': '0.16.0', 'starter_packs': [{'id': 'align', 'version': '0.4.0'}],
                    'additional_packs': [{'id': 'align', 'version': '0.4.1'}], 'files': []}
        self.new = copy.deepcopy(self.old)
        self.new['version'] = '0.16.1'

    def tearDown(self):
        self.temp.cleanup()

    def verify(self):
        return candidate.verify_preserved(self.base, self.target, self.old, self.new)

    def test_published_packs_and_runtime_are_retained(self):
        self.assertEqual(self.verify(), {'packs': 4, 'runtime': 1})

    def test_additional_pack_mutation_is_rejected(self):
        put(self.target, 'packs/align-0.4.1/pack.ini', b'changed')
        with self.assertRaisesRegex(ValueError, 'packs bytes changed'):
            self.verify()

    def test_extra_runtime_file_is_rejected(self):
        put(self.target, 'runtime/python/extra.dll', b'new dependency')
        with self.assertRaisesRegex(ValueError, 'runtime bytes changed'):
            self.verify()

    def test_removed_pack_is_rejected(self):
        shutil.rmtree(self.target / 'packs/bam-0.4.0')
        with self.assertRaisesRegex(ValueError, 'packs bytes changed'):
            self.verify()

    def test_changed_pin_or_additional_inventory_is_rejected(self):
        for field in ('starter_packs', 'additional_packs'):
            with self.subTest(field=field):
                original = copy.deepcopy(self.new[field])
                self.new[field][0]['version'] = '9.0.0'
                with self.assertRaisesRegex(ValueError, 'pins or inventories changed'):
                    self.verify()
                self.new[field] = original

    def test_core_cannot_claim_pack_files(self):
        self.new['files'] = [{'path': 'packs/align-0.4.1/pack.ini'}]
        with self.assertRaisesRegex(ValueError, 'Core update cannot own packs'):
            self.verify()

    def test_selection_and_trust_mutation_are_rejected(self):
        for name in ('workspace/setup-profile.json', 'workspace/catalog-sources.json'):
            with self.subTest(name=name):
                put(self.target, name, b'changed')
                with self.assertRaisesRegex(ValueError, 'selection/trust changed'):
                    self.verify()
                shutil.copyfile(self.base / name, self.target / name)

    def test_wrong_patch_version_is_rejected(self):
        self.new['version'] = '0.16.0'
        with self.assertRaisesRegex(ValueError, 'Unexpected patch version'):
            self.verify()


class SourceCorrespondence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        put(self.root, 'workspace/app_version.py', b'APP_VERSION = "0.16.1"\n')
        subprocess.run(['git', 'add', 'workspace/app_version.py'], cwd=self.root, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        'commit', '-qm', 'Source fixture'], cwd=self.root, check=True)
        self.commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.root, text=True).strip()
        self.raw = (self.root / 'workspace/app_version.py').read_bytes()
        self.source, self.starter = self.root / 'source.zip', self.root / 'starter.zip'

    def tearDown(self):
        self.temp.cleanup()

    def archives(self, source_raw=None, runtime_raw=None):
        raw = self.raw if source_raw is None else source_raw
        path = 'current/workspace/app_version.py'
        row = {'path': path, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        with zipfile.ZipFile(self.source, 'w') as zipped:
            zipped.writestr(path, raw)
            zipped.writestr('SOURCE-RECOVERY.json', json.dumps({'current_source_files': [row]}))
        with zipfile.ZipFile(self.starter, 'w') as zipped:
            zipped.writestr('native-workbench/workspace/app_version.py', self.raw if runtime_raw is None else runtime_raw)
            zipped.writestr('native-workbench/SOURCE-AVAILABILITY.json', json.dumps({'sourceArtifact': {
                'bytes': self.source.stat().st_size, 'sha256': candidate.sha256(self.source)}}))

    def verify(self):
        with patch.object(candidate, 'SOURCE_ROOT', self.root):
            return candidate.source_correspondence(self.source, self.starter, self.commit)

    def test_actual_git_blob_and_runtime_correspond(self):
        self.archives()
        self.assertEqual(self.verify()['currentFilesMatchCommit'], 1)

    def test_self_consistent_but_uncommitted_source_is_rejected(self):
        self.archives(source_raw=b'changed but correctly inventoried')
        with self.assertRaisesRegex(ValueError, 'Source mismatch'):
            self.verify()

    def test_runtime_not_matching_archived_source_is_rejected(self):
        self.archives(runtime_raw=b'different runtime')
        with self.assertRaisesRegex(ValueError, 'Runtime/source mismatch'):
            self.verify()


if __name__ == '__main__':
    unittest.main(verbosity=2)
